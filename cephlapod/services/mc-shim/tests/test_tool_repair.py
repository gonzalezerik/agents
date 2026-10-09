"""
Characterization tests for tool_repair.py — documents current behavior as it exists today.
Do not modify tests to make them pass; a failure after a move is a finding.

Suspected bugs are noted in comments but NOT fixed here.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import tool_repair


# ── repair() ─────────────────────────────────────────────────────────────────

class TestRepair:
    def test_clean_json_roundtrips_unchanged(self):
        result, was_repaired = tool_repair.repair('{"key": "value"}')
        assert result == {"key": "value"}
        assert was_repaired is False

    def test_empty_string_returns_empty_dict(self):
        # Whitespace-only also treated as empty
        result, was_repaired = tool_repair.repair('')
        assert result == {}
        assert was_repaired is False

    def test_whitespace_only_returns_empty_dict(self):
        result, was_repaired = tool_repair.repair('   ')
        assert result == {}
        assert was_repaired is False

    def test_trailing_comma_in_object(self):
        result, was_repaired = tool_repair.repair('{"a": 1,}')
        assert result == {"a": 1}
        assert was_repaired is True

    def test_trailing_comma_in_nested_object(self):
        result, was_repaired = tool_repair.repair('{"a": {"b": 2,}}')
        assert result == {"a": {"b": 2}}
        assert was_repaired is True

    def test_trailing_comma_in_array(self):
        result, was_repaired = tool_repair.repair('{"arr": [1, 2, 3,]}')
        assert result == {"arr": [1, 2, 3]}
        assert was_repaired is True

    def test_truncated_open_object(self):
        # Model hit max_tokens mid-object
        result, was_repaired = tool_repair.repair('{"command": "ls /home"')
        assert result == {"command": "ls /home"}
        assert was_repaired is True

    def test_truncated_nested_object(self):
        result, was_repaired = tool_repair.repair('{"outer": {"inner": "val"')
        assert result == {"outer": {"inner": "val"}}
        assert was_repaired is True

    def test_truncated_array(self):
        result, was_repaired = tool_repair.repair('{"items": ["a", "b"')
        assert result == {"items": ["a", "b"]}
        assert was_repaired is True

    def test_trailing_comma_plus_truncated(self):
        # Both failure modes at once
        result, was_repaired = tool_repair.repair('{"a": 1, "b": [2, 3,]')
        assert result == {"a": 1, "b": [2, 3]}
        assert was_repaired is True

    def test_unrecoverable_raises_value_error(self):
        with pytest.raises(ValueError):
            tool_repair.repair('not json at all !!!{{{')

    def test_deeply_truncated_raises_value_error(self):
        # Truncated in the middle of a string value — unrecoverable
        with pytest.raises(ValueError):
            tool_repair.repair('{"cmd": "ls /ho')

    def test_complex_clean_json(self):
        # Representative real-world tool call body
        raw = '{"command": "grep -r TODO /opt/mc-shim", "timeout": 30}'
        result, was_repaired = tool_repair.repair(raw)
        assert result == {"command": "grep -r TODO /opt/mc-shim", "timeout": 30}
        assert was_repaired is False

    def test_numeric_values_preserved(self):
        result, was_repaired = tool_repair.repair('{"n": 42, "f": 3.14}')
        assert result == {"n": 42, "f": 3.14}
        assert was_repaired is False

    def test_bool_values_preserved(self):
        result, was_repaired = tool_repair.repair('{"ok": true, "fail": false}')
        assert result == {"ok": True, "fail": False}
        assert was_repaired is False


# ── repair_tool_blocks() ──────────────────────────────────────────────────────

class TestRepairToolBlocks:
    def test_no_tool_blocks_passthrough(self):
        blocks = [{"type": "text", "text": "hello world"}]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired == blocks
        assert repairs == []

    def test_clean_tool_use_no_raw_key_passthrough(self):
        # tool_use with proper dict input — no _raw key, no repair needed
        blocks = [{"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "ls"}}]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired == blocks
        assert repairs == []

    def test_raw_key_with_clean_json_is_parsed(self):
        # _raw key containing valid JSON is cleaned up with no repair event
        blocks = [{"type": "tool_use", "id": "tu_1", "name": "bash",
                   "input": {"_raw": '{"command": "ls"}'}}]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired[0]["input"] == {"command": "ls"}
        # NOTE: was_repaired=False for clean JSON, so no repair event emitted
        assert repairs == []

    def test_raw_key_truncated_json_repaired(self):
        blocks = [{"type": "tool_use", "id": "tu_2", "name": "read_file",
                   "input": {"_raw": '{"path": "/etc/hosts"'}}]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired[0]["input"] == {"path": "/etc/hosts"}
        assert len(repairs) == 1
        assert repairs[0]["tool_use_id"] == "tu_2"
        assert repairs[0]["tool_name"] == "read_file"
        assert "error" not in repairs[0]  # no error key when repair succeeds

    def test_raw_key_trailing_comma_repaired(self):
        blocks = [{"type": "tool_use", "id": "tu_3", "name": "write",
                   "input": {"_raw": '{"path": "/tmp/x", "content": "hello",}'}}]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired[0]["input"] == {"path": "/tmp/x", "content": "hello"}
        assert len(repairs) == 1

    def test_raw_key_unrecoverable_preserves_parse_error(self):
        blocks = [{"type": "tool_use", "id": "tu_4", "name": "bash",
                   "input": {"_raw": "not json !!!"}}]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired[0]["input"]["_parse_error"] is True
        assert repaired[0]["input"]["_raw"] == "not json !!!"
        assert len(repairs) == 1
        assert repairs[0]["error"] == "unrecoverable"
        assert repairs[0]["repaired"] is None

    def test_mixed_blocks_correct_handling(self):
        blocks = [
            {"type": "text", "text": "thinking..."},
            {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "ls"}},
            {"type": "tool_use", "id": "tu_2", "name": "write",
             "input": {"_raw": '{"path": "/tmp/x"'}},
        ]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired[0] == blocks[0]               # text passthrough
        assert repaired[1] == blocks[1]               # clean tool_use passthrough
        assert repaired[2]["input"] == {"path": "/tmp/x"}  # repaired
        assert len(repairs) == 1                       # only one repair event
        assert repairs[0]["tool_use_id"] == "tu_2"

    def test_multiple_broken_blocks_all_repaired(self):
        blocks = [
            {"type": "tool_use", "id": "tu_1", "name": "read",
             "input": {"_raw": '{"path": "/etc"'}},
            {"type": "tool_use", "id": "tu_2", "name": "bash",
             "input": {"_raw": '{"cmd": "ls",}'}},
        ]
        repaired, repairs = tool_repair.repair_tool_blocks(blocks, "test-session")
        assert repaired[0]["input"] == {"path": "/etc"}
        assert repaired[1]["input"] == {"cmd": "ls"}
        assert len(repairs) == 2

    def test_empty_blocks_list(self):
        repaired, repairs = tool_repair.repair_tool_blocks([], "test-session")
        assert repaired == []
        assert repairs == []
