"""
Repair malformed tool call JSON before returning it to the client.
Common failure modes:
  1. Truncated JSON (model hit max_tokens mid-object)
  2. Trailing commas
  3. Single-quoted strings
  4. Control characters in string values
"""
from __future__ import annotations
import json, re


def _strip_trailing_comma(s: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", s)


def _single_to_double_quotes(s: str) -> str:
    # Only safe for simple cases — don't mangle URLs
    return re.sub(r"(?<![\\])'", '"', s)


def _close_open_structures(s: str) -> str:
    """Add missing closing braces/brackets to truncated JSON."""
    stack = []
    in_string = False
    escape = False
    for ch in s:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return s + "".join(reversed(stack))


def repair(raw: str) -> tuple[dict, bool]:
    """
    Try to parse raw JSON string into a dict.
    Returns (parsed_dict, was_repaired).
    Raises ValueError if unrecoverable.
    """
    if not raw.strip():
        return {}, False

    # 1. Try clean parse
    try:
        return json.loads(raw), False
    except json.JSONDecodeError:
        pass

    attempts = [
        _strip_trailing_comma(raw),
        _close_open_structures(raw),
        _close_open_structures(_strip_trailing_comma(raw)),
        _single_to_double_quotes(raw),
        _close_open_structures(_strip_trailing_comma(_single_to_double_quotes(raw))),
    ]
    for attempt in attempts:
        try:
            return json.loads(attempt), True
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Unrecoverable tool JSON: {raw[:200]!r}")


def repair_tool_blocks(blocks: list[dict], session_id: str) -> tuple[list[dict], list[dict]]:
    """
    Scan content blocks for tool_use entries with broken input.
    Returns (repaired_blocks, repair_events) where repair_events are dicts
    ready to be logged.
    """
    import event_log
    repaired = []
    repairs = []
    for block in blocks:
        if block.get("type") != "tool_use":
            repaired.append(block)
            continue
        raw_input = block.get("input")
        if isinstance(raw_input, dict) and "_raw" in raw_input:
            raw_str = raw_input["_raw"]
            try:
                fixed, was_repaired = repair(raw_str)
                if was_repaired:
                    repairs.append({
                        "tool_use_id": block["id"],
                        "tool_name": block.get("name"),
                        "original": raw_str,
                        "repaired": json.dumps(fixed),
                    })
                repaired.append({**block, "input": fixed})
            except ValueError:
                repaired.append({**block, "input": {"_raw": raw_str, "_parse_error": True}})
                repairs.append({
                    "tool_use_id": block["id"],
                    "tool_name": block.get("name"),
                    "original": raw_str,
                    "repaired": None,
                    "error": "unrecoverable",
                })
        else:
            repaired.append(block)
    return repaired, repairs
