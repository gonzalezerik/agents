"""
Characterization tests for translator.py — documents current behavior as it exists today.
Covers anthropic_to_openai(), chunk_to_anthropic_events(), and extract_content_blocks().
Suspected bugs are noted in comments but NOT fixed here.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json
import pytest
import translator


# ── anthropic_to_openai() ─────────────────────────────────────────────────────

class TestAnthropicToOpenai:
    def test_simple_user_string_message(self):
        body = {
            "model": "claude-3-5-sonnet",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
        }
        out = translator.anthropic_to_openai(body)
        assert out["messages"] == [{"role": "user", "content": "Hello"}]
        assert out["max_tokens"] == 100
        assert out["stream"] is True  # default

    def test_system_string_prepended(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "system": "You are a helpful assistant.",
        }
        out = translator.anthropic_to_openai(body)
        assert out["messages"][0] == {"role": "system", "content": "You are a helpful assistant."}
        assert out["messages"][1] == {"role": "user", "content": "Hi"}

    def test_system_as_list_of_blocks(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "system": [
                {"type": "text", "text": "Be helpful."},
                {"type": "text", "text": " Be concise."},
            ],
        }
        out = translator.anthropic_to_openai(body)
        assert out["messages"][0]["role"] == "system"
        assert "Be helpful." in out["messages"][0]["content"]
        assert "Be concise." in out["messages"][0]["content"]

    def test_empty_system_not_prepended(self):
        body = {
            "messages": [{"role": "user", "content": "Hi"}],
            "system": "",
        }
        out = translator.anthropic_to_openai(body)
        assert out["messages"][0]["role"] == "user"

    def test_tools_converted_to_functions(self):
        body = {
            "messages": [{"role": "user", "content": "run it"}],
            "tools": [{
                "name": "bash",
                "description": "Execute a shell command",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            }],
        }
        out = translator.anthropic_to_openai(body)
        assert len(out["tools"]) == 1
        fn = out["tools"][0]
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "bash"
        assert fn["function"]["description"] == "Execute a shell command"
        assert fn["function"]["parameters"]["properties"]["command"]["type"] == "string"
        assert out["tool_choice"] == "auto"

    def test_no_tools_no_tool_choice(self):
        body = {"messages": [{"role": "user", "content": "hi"}]}
        out = translator.anthropic_to_openai(body)
        assert "tools" not in out
        assert "tool_choice" not in out

    def test_assistant_text_content(self):
        body = {
            "messages": [
                {"role": "user", "content": "What is 2+2?"},
                {"role": "assistant", "content": "4"},
            ],
        }
        out = translator.anthropic_to_openai(body)
        assert out["messages"][-1] == {"role": "assistant", "content": "4"}

    def test_assistant_with_tool_use_block(self):
        # Multi-content assistant message with text + tool_use
        body = {
            "messages": [{
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Let me run that."},
                    {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "ls"}},
                ],
            }],
        }
        out = translator.anthropic_to_openai(body)
        msg = out["messages"][0]
        assert msg["role"] == "assistant"
        assert msg["content"] == "Let me run that."
        assert len(msg["tool_calls"]) == 1
        assert msg["tool_calls"][0]["id"] == "tu_1"
        assert msg["tool_calls"][0]["function"]["name"] == "bash"
        assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"command": "ls"}

    def test_user_tool_result_becomes_tool_role(self):
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "file1.txt\nfile2.txt"},
                ],
            }],
        }
        out = translator.anthropic_to_openai(body)
        assert len(out["messages"]) == 1
        msg = out["messages"][0]
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "tu_1"
        assert msg["content"] == "file1.txt\nfile2.txt"

    def test_user_tool_result_list_content_joined(self):
        # tool_result.content can be a list of text blocks
        body = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "tu_1",
                    "content": [
                        {"type": "text", "text": "line 1"},
                        {"type": "text", "text": "line 2"},
                    ],
                }],
            }],
        }
        out = translator.anthropic_to_openai(body)
        msg = out["messages"][0]
        assert "line 1" in msg["content"]
        assert "line 2" in msg["content"]

    def test_user_text_dropped_when_tool_result_present(self):
        # BUG: if a user message has both text and tool_result blocks,
        # the text oai_parts are silently dropped because of the `if pending_tool_results: ... elif oai_parts:` logic.
        # Documenting current behavior — text IS dropped.
        body = {
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "here is the result:"},
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "output"},
                ],
            }],
        }
        out = translator.anthropic_to_openai(body)
        # Only the tool message is emitted; user text is lost
        assert len(out["messages"]) == 1
        assert out["messages"][0]["role"] == "tool"
        # The text "here is the result:" does NOT appear in any message

    def test_multi_turn_with_tool_call_and_result(self):
        body = {
            "messages": [
                {"role": "user", "content": "List my files"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"command": "ls ~"}},
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "tu_1", "content": "Desktop\nDocuments"},
                ]},
            ],
        }
        out = translator.anthropic_to_openai(body)
        assert len(out["messages"]) == 3
        assert out["messages"][0] == {"role": "user", "content": "List my files"}
        assert out["messages"][1]["role"] == "assistant"
        assert out["messages"][1]["tool_calls"][0]["id"] == "tu_1"
        assert out["messages"][2]["role"] == "tool"
        assert out["messages"][2]["content"] == "Desktop\nDocuments"

    def test_stop_sequences_forwarded(self):
        body = {
            "messages": [{"role": "user", "content": "x"}],
            "stop_sequences": ["STOP", "END"],
        }
        out = translator.anthropic_to_openai(body)
        assert out["stop"] == ["STOP", "END"]

    def test_temperature_forwarded(self):
        body = {
            "messages": [{"role": "user", "content": "x"}],
            "temperature": 0.7,
        }
        out = translator.anthropic_to_openai(body)
        assert out["temperature"] == 0.7

    def test_thinking_suppressed(self):
        # Qwen3 thinking tokens suppressed via chat_template_kwargs
        body = {"messages": [{"role": "user", "content": "think"}]}
        out = translator.anthropic_to_openai(body)
        assert out.get("chat_template_kwargs", {}).get("enable_thinking") is False

    def test_image_base64_converted(self):
        body = {
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "abc123"},
                }],
            }],
        }
        out = translator.anthropic_to_openai(body)
        parts = out["messages"][0]["content"]
        img_part = next(p for p in parts if p["type"] == "image_url")
        assert img_part["image_url"]["url"] == "data:image/png;base64,abc123"


# ── chunk_to_anthropic_events() ───────────────────────────────────────────────

class TestChunkToAnthropicEvents:
    """
    Simulate streaming OAI chunks and verify the Anthropic SSE event sequence.
    State dict is mutated across calls, mimicking real stream processing.
    """

    def _text_chunk(self, text: str, finish: str | None = None) -> dict:
        return {
            "choices": [{"delta": {"content": text}, "finish_reason": finish}]
        }

    def _tool_start_chunk(self, tc_id: str, name: str, tc_idx: int = 0) -> dict:
        return {
            "choices": [{"delta": {"tool_calls": [{"index": tc_idx, "id": tc_id,
                "function": {"name": name, "arguments": ""}}]}, "finish_reason": None}]
        }

    def _tool_arg_chunk(self, partial_args: str, tc_idx: int = 0) -> dict:
        return {
            "choices": [{"delta": {"tool_calls": [{"index": tc_idx,
                "function": {"arguments": partial_args}}]}, "finish_reason": None}]
        }

    def _finish_chunk(self, finish_reason: str, usage: dict | None = None) -> dict:
        chunk: dict = {"choices": [{"delta": {}, "finish_reason": finish_reason}]}
        if usage:
            chunk["usage"] = usage
        return chunk

    def test_text_only_stream(self):
        state: dict = {}
        events = []

        events += translator.chunk_to_anthropic_events(self._text_chunk("Hello"), state)
        events += translator.chunk_to_anthropic_events(self._text_chunk(", world"), state)
        events += translator.chunk_to_anthropic_events(self._finish_chunk("stop"), state)

        names = [e[0] for e in events]
        assert names[0] == "content_block_start"
        assert events[0][1]["content_block"]["type"] == "text"
        assert all(e[0] == "content_block_delta" for e in events if e[0] == "content_block_delta")
        assert "content_block_stop" in names
        assert "message_delta" in names
        assert "message_stop" in names

        # Accumulated text
        assert state["accumulated_text"] == "Hello, world"

    def test_text_block_start_emitted_once(self):
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._text_chunk("a"), state)
        events += translator.chunk_to_anthropic_events(self._text_chunk("b"), state)
        starts = [e for e in events if e[0] == "content_block_start"]
        # Only one content_block_start for the text block
        assert len(starts) == 1

    def test_tool_call_stream(self):
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._tool_start_chunk("tc_abc", "bash"), state)
        events += translator.chunk_to_anthropic_events(self._tool_arg_chunk('{"cmd":'), state)
        events += translator.chunk_to_anthropic_events(self._tool_arg_chunk('"ls"}'), state)
        events += translator.chunk_to_anthropic_events(self._finish_chunk("tool_calls",
            {"prompt_tokens": 50, "completion_tokens": 10}), state)

        names = [e[0] for e in events]
        assert "content_block_start" in names
        start_evt = next(e[1] for e in events if e[0] == "content_block_start")
        assert start_evt["content_block"]["type"] == "tool_use"
        assert start_evt["content_block"]["id"] == "tc_abc"
        assert start_evt["content_block"]["name"] == "bash"

        # Check argument deltas accumulated
        tb = state["tool_blocks"][0]
        assert tb["args_raw"] == '{"cmd":"ls"}'

        # Stop reason
        assert state["stop_reason"] == "tool_use"

    def test_finish_reason_stop_maps_to_end_turn(self):
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._text_chunk("ok"), state)
        events += translator.chunk_to_anthropic_events(self._finish_chunk("stop"), state)
        delta_evt = next(e[1] for e in events if e[0] == "message_delta")
        assert delta_evt["delta"]["stop_reason"] == "end_turn"

    def test_finish_reason_tool_calls_maps_to_tool_use(self):
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._tool_start_chunk("tc_1", "read"), state)
        events += translator.chunk_to_anthropic_events(self._finish_chunk("tool_calls"), state)
        delta_evt = next(e[1] for e in events if e[0] == "message_delta")
        assert delta_evt["delta"]["stop_reason"] == "tool_use"

    def test_finish_reason_length_maps_to_max_tokens(self):
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._text_chunk("trunca"), state)
        events += translator.chunk_to_anthropic_events(self._finish_chunk("length"), state)
        delta_evt = next(e[1] for e in events if e[0] == "message_delta")
        assert delta_evt["delta"]["stop_reason"] == "max_tokens"

    def test_text_then_tool_call(self):
        # Text block closes, tool block opens
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._text_chunk("Let me check: "), state)
        events += translator.chunk_to_anthropic_events(self._tool_start_chunk("tc_1", "bash"), state)
        events += translator.chunk_to_anthropic_events(self._finish_chunk("tool_calls"), state)

        names = [e[0] for e in events]
        # content_block_start appears twice (once for text, once for tool)
        starts = [e for e in events if e[0] == "content_block_start"]
        assert len(starts) == 2
        assert starts[0][1]["content_block"]["type"] == "text"
        assert starts[1][1]["content_block"]["type"] == "tool_use"

        # Text block stop comes before tool block start
        stops = [i for i, e in enumerate(events) if e[0] == "content_block_stop"]
        tool_start_idx = next(i for i, e in enumerate(events)
                              if e[0] == "content_block_start" and e[1]["content_block"]["type"] == "tool_use")
        assert stops[0] < tool_start_idx

    def test_index_increments_across_blocks(self):
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._text_chunk("hi"), state)
        events += translator.chunk_to_anthropic_events(self._tool_start_chunk("tc_1", "bash"), state)
        events += translator.chunk_to_anthropic_events(self._finish_chunk("tool_calls"), state)

        starts = [e[1] for e in events if e[0] == "content_block_start"]
        assert starts[0]["index"] == 0  # text block at index 0
        assert starts[1]["index"] == 1  # tool block at index 1

    def test_empty_chunk_produces_no_events(self):
        state: dict = {}
        events = translator.chunk_to_anthropic_events({"choices": [{"delta": {}, "finish_reason": None}]}, state)
        assert events == []

    def test_usage_captured_in_state(self):
        state: dict = {}
        events = []
        events += translator.chunk_to_anthropic_events(self._text_chunk("x"), state)
        events += translator.chunk_to_anthropic_events(
            self._finish_chunk("stop", {"prompt_tokens": 100, "completion_tokens": 20}), state)
        assert state["finish_usage"]["prompt_tokens"] == 100
        assert state["finish_usage"]["completion_tokens"] == 20


# ── extract_content_blocks() ─────────────────────────────────────────────────

class TestExtractContentBlocks:
    def test_text_only_state(self):
        state = {"accumulated_text": "Hello world", "block_index": 0, "block_type": "text"}
        blocks = translator.extract_content_blocks(state)
        assert blocks == [{"type": "text", "text": "Hello world"}]

    def test_no_text_no_tools(self):
        state = {}
        blocks = translator.extract_content_blocks(state)
        assert blocks == []

    def test_tool_block_clean_json(self):
        state = {
            "tool_blocks": {0: {"id": "tc_1", "name": "bash", "args_raw": '{"command": "ls"}'}},
            "block_type": "tool",
        }
        blocks = translator.extract_content_blocks(state)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "tool_use"
        assert blocks[0]["id"] == "tc_1"
        assert blocks[0]["input"] == {"command": "ls"}

    def test_tool_block_truncated_json_gets_raw_marker(self):
        # Truncated args → json.loads fails → stored as {"_raw": ...}
        state = {
            "tool_blocks": {0: {"id": "tc_1", "name": "bash", "args_raw": '{"command": "ls"'}},
            "block_type": "tool",
        }
        blocks = translator.extract_content_blocks(state)
        assert blocks[0]["input"] == {"_raw": '{"command": "ls"'}

    def test_text_and_tool_blocks(self):
        state = {
            "accumulated_text": "Running now:",
            "tool_blocks": {0: {"id": "tc_1", "name": "bash", "args_raw": '{"cmd": "ls"}'}},
        }
        blocks = translator.extract_content_blocks(state)
        assert blocks[0]["type"] == "text"
        assert blocks[1]["type"] == "tool_use"

    def test_empty_args_raw(self):
        # Empty args_raw → empty dict, no repair
        state = {
            "tool_blocks": {0: {"id": "tc_1", "name": "noop", "args_raw": ""}},
        }
        blocks = translator.extract_content_blocks(state)
        assert blocks[0]["input"] == {}


# ── Golden session corpus: real sessions from gpuhost ───────────────────────
# These are the actual sessions captured from the acceptance test run.
# They demonstrate the full event chain for a simple text request.

GOLDEN_SESSION = {
    "session_id": "accept-t1-1788563939",
    "events": [
        {"seq": 1, "event_type": "user_message", "payload": {
            "messages": [{"role": "user", "content": "Say hi in one word"}],
            "model_requested": "auto", "max_tokens": 16, "tools": [], "system": "", "stream": True,
        }},
        {"seq": 2, "event_type": "orchestrator_plan", "payload": {
            "orchestrator_model_id": "gpuhost:qwen3.6-35b-a3b-cpu",
            "latency_ms": 3115,
        }},
        {"seq": 3, "event_type": "agent_selected", "payload": {
            "model_id": "gpuhost:qwen3.6-35b-a3b-cpu",
            "reason": "This is the only available agent and is capable of handling simple text generation tasks like saying hi.",
            "latency_ms": 3115,
        }},
        {"seq": 4, "event_type": "agent_response", "payload": {
            "model_id": "gpuhost:qwen3.6-35b-a3b-cpu",
            "content_blocks": [{"type": "text", "text": "Hello"}],
            "stop_reason": "end_turn", "tokens_in": None, "tokens_out": None, "latency_ms": 201,
        }},
        {"seq": 5, "event_type": "final_response", "payload": {
            "stop_reason": "end_turn", "total_latency_ms": 201, "had_repairs": False,
        }},
    ],
}

class TestGoldenSessionTranslation:
    """Verify that the user_message from the golden session translates correctly."""

    def test_golden_session_user_message_translates(self):
        payload = GOLDEN_SESSION["events"][0]["payload"]
        out = translator.anthropic_to_openai(payload)
        assert out["messages"][-1] == {"role": "user", "content": "Say hi in one word"}
        assert out["max_tokens"] == 16

    def test_golden_session_has_expected_event_chain(self):
        event_types = [e["event_type"] for e in GOLDEN_SESSION["events"]]
        assert event_types == [
            "user_message", "orchestrator_plan", "agent_selected",
            "agent_response", "final_response",
        ]

    def test_golden_session_no_repairs(self):
        final = GOLDEN_SESSION["events"][-1]["payload"]
        assert final["had_repairs"] is False
