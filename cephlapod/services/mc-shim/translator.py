"""
Anthropic Messages API ↔ OpenAI Chat Completions format translation.

Anthropic → OpenAI (for forwarding to llama-server):
  - system: first system message extracted
  - tool definitions: Anthropic tool schema → OpenAI function schema
  - tool_result messages → role=tool messages
  - thinking blocks stripped (we add enable_thinking: false separately)

OpenAI → Anthropic (for returning to Claude Code client):
  - choices[0].message → content blocks
  - function/tool calls → tool_use content blocks
  - finish_reason → stop_reason
  - usage → usage
"""
from __future__ import annotations
import json
from typing import Any


# ── Anthropic → OpenAI ────────────────────────────────────────────────────────

def anthropic_to_openai(body: dict[str, Any]) -> dict[str, Any]:
    messages_in = body.get("messages", [])
    oai_messages: list[dict] = []

    # System prompt
    system = body.get("system", "")
    if isinstance(system, list):  # Anthropic allows system as list of blocks
        system = "\n".join(b.get("text", "") for b in system if b.get("type") == "text")
    if system:
        oai_messages.append({"role": "system", "content": system})

    for msg in messages_in:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "assistant":
            # content may be list of blocks (text + tool_use)
            if isinstance(content, list):
                text_parts = [b["text"] for b in content if b.get("type") == "text"]
                tool_calls = []
                for b in content:
                    if b.get("type") == "tool_use":
                        tool_calls.append({
                            "id": b["id"],
                            "type": "function",
                            "function": {
                                "name": b["name"],
                                "arguments": json.dumps(b.get("input", {})),
                            },
                        })
                oai_msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                oai_messages.append(oai_msg)
            else:
                oai_messages.append({"role": "assistant", "content": content})

        elif role == "user":
            if isinstance(content, list):
                # May contain text, image, tool_result blocks
                oai_parts: list[dict] = []
                pending_tool_results: list[dict] = []
                for b in content:
                    btype = b.get("type")
                    if btype == "text":
                        oai_parts.append({"type": "text", "text": b["text"]})
                    elif btype == "image":
                        src = b.get("source", {})
                        if src.get("type") == "base64":
                            oai_parts.append({
                                "type": "image_url",
                                "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"},
                            })
                        elif src.get("type") == "url":
                            oai_parts.append({"type": "image_url", "image_url": {"url": src["url"]}})
                    elif btype == "tool_result":
                        # Tool results come as separate "tool" role messages in OAI
                        tr_content = b.get("content", "")
                        if isinstance(tr_content, list):
                            tr_content = "\n".join(c.get("text", "") for c in tr_content if c.get("type") == "text")
                        pending_tool_results.append({
                            "role": "tool",
                            "tool_call_id": b["tool_use_id"],
                            "content": str(tr_content),
                        })

                if pending_tool_results:
                    oai_messages.extend(pending_tool_results)
                elif oai_parts:
                    if len(oai_parts) == 1 and oai_parts[0]["type"] == "text":
                        oai_messages.append({"role": "user", "content": oai_parts[0]["text"]})
                    else:
                        oai_messages.append({"role": "user", "content": oai_parts})
            else:
                oai_messages.append({"role": "user", "content": content})

    # Tools
    oai_tools = []
    for t in body.get("tools", []):
        oai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        })

    oai_body: dict[str, Any] = {
        "model": body.get("model", "local"),
        "messages": oai_messages,
        "max_tokens": body.get("max_tokens", 4096),
        "stream": body.get("stream", True),
        "temperature": body.get("temperature", 1.0),
        # Suppress Qwen3 thinking tokens
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if oai_tools:
        oai_body["tools"] = oai_tools
        oai_body["tool_choice"] = "auto"
    if body.get("stop_sequences"):
        oai_body["stop"] = body["stop_sequences"]

    return oai_body


# ── OpenAI streaming chunk → Anthropic SSE events ────────────────────────────

def chunk_to_anthropic_events(
    chunk: dict[str, Any],
    state: dict,  # mutable: tracks block index, current tool state, usage
) -> list[tuple[str, dict]]:
    """
    Convert one OpenAI streaming chunk to ≥0 Anthropic (event_name, data) pairs.
    `state` is mutated across calls for the same stream.
    """
    events: list[tuple[str, dict]] = []
    choice = (chunk.get("choices") or [{}])[0]
    delta = choice.get("delta", {})
    finish = choice.get("finish_reason")

    # Text delta
    text = delta.get("content") or ""
    if text:
        if state.get("block_type") != "text":
            # Close previous block if needed
            if "block_index" in state and state.get("block_type") == "tool":
                events.append(("content_block_stop", {"type": "content_block_stop", "index": state["block_index"]}))
                state["block_index"] = state.get("block_index", 0) + 1

            idx = state.get("block_index", 0)
            state["block_index"] = idx
            state["block_type"] = "text"
            events.append(("content_block_start", {
                "type": "content_block_start", "index": idx,
                "content_block": {"type": "text", "text": ""},
            }))

        events.append(("content_block_delta", {
            "type": "content_block_delta",
            "index": state.get("block_index", 0),
            "delta": {"type": "text_delta", "text": text},
        }))
        state.setdefault("accumulated_text", "")
        state["accumulated_text"] += text

    # Tool call deltas
    for tc in delta.get("tool_calls", []):
        tc_idx = tc.get("index", 0)
        fn = tc.get("function", {})

        if tc.get("id"):
            # New tool call starting
            if state.get("block_type") == "text":
                events.append(("content_block_stop", {
                    "type": "content_block_stop", "index": state.get("block_index", 0),
                }))
                state["block_index"] = state.get("block_index", 0) + 1
            elif state.get("block_type") == "tool" and state.get("tool_oai_index") != tc_idx:
                events.append(("content_block_stop", {
                    "type": "content_block_stop", "index": state.get("block_index", 0),
                }))
                state["block_index"] = state.get("block_index", 0) + 1

            idx = state.get("block_index", 0)
            state["block_type"] = "tool"
            state["tool_oai_index"] = tc_idx
            state["current_tool_id"] = tc["id"]
            state["current_tool_name"] = fn.get("name", "")
            state["current_tool_args_raw"] = ""
            state.setdefault("tool_blocks", {})[tc_idx] = {
                "id": tc["id"], "name": fn.get("name", ""), "args_raw": ""
            }
            events.append(("content_block_start", {
                "type": "content_block_start", "index": idx,
                "content_block": {"type": "tool_use", "id": tc["id"], "name": fn.get("name", ""), "input": {}},
            }))

        if fn.get("arguments"):
            events.append(("content_block_delta", {
                "type": "content_block_delta",
                "index": state.get("block_index", 0),
                "delta": {"type": "input_json_delta", "partial_json": fn["arguments"]},
            }))
            tb = state.get("tool_blocks", {}).get(tc_idx)
            if tb:
                tb["args_raw"] += fn["arguments"]

    # Finish
    if finish:
        if state.get("block_type"):
            events.append(("content_block_stop", {
                "type": "content_block_stop", "index": state.get("block_index", 0),
            }))

        stop_reason = "end_turn"
        if finish == "tool_calls":
            stop_reason = "tool_use"
        elif finish == "length":
            stop_reason = "max_tokens"

        usage = chunk.get("usage") or state.get("usage", {})
        events.append(("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": usage.get("completion_tokens", 0)},
        }))
        events.append(("message_stop", {"type": "message_stop"}))
        state["stop_reason"] = stop_reason
        state["finish_usage"] = usage

    # Usage update (some servers send mid-stream)
    if chunk.get("usage"):
        state["usage"] = chunk["usage"]

    return events


# ── Reconstruct full content from stream state ────────────────────────────────

def extract_content_blocks(state: dict) -> list[dict]:
    """After streaming completes, build the full content block list from state."""
    blocks = []
    text = state.get("accumulated_text", "")
    if text:
        blocks.append({"type": "text", "text": text})
    for tb in sorted(state.get("tool_blocks", {}).values(), key=lambda x: x.get("id", "")):
        try:
            parsed = json.loads(tb["args_raw"]) if tb["args_raw"] else {}
        except json.JSONDecodeError:
            parsed = {"_raw": tb["args_raw"]}  # will be repaired
        blocks.append({"type": "tool_use", "id": tb["id"], "name": tb["name"], "input": parsed})
    return blocks
