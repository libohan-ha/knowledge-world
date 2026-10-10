"""OpenAI-compatible stream variants observed at a real relay boundary."""
import json

import httpx
import pytest

from knowledge_world.providers import OpenAIProvider, ProviderFailure


def provider(monkeypatch, deltas):
    monkeypatch.setenv("AI_STREAM_TEST", "synthetic-not-a-real-key")
    chunks = ["data: " + json.dumps({"choices": [{"delta": d, "finish_reason": None}]}) for d in deltas]
    chunks += ['data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}', "data: [DONE]"]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="\n\n".join(chunks)))
    return OpenAIProvider({"role": "chat", "base_url": "https://synthetic.invalid/v1", "model": "test", "secret_ref": "env:AI_STREAM_TEST"}, {"ai": {"text_timeout_seconds": 10}}, transport)


def test_complete_tools_without_fragment_index_keep_independent_call_ids(monkeypatch):
    calls = [{"id": identity, "type": "function", "function": {"name": name, "arguments": "{}"}} for identity, name in [("call-a", "read_roster"), ("call-b", "read_map")]]
    p = provider(monkeypatch, [{"tool_calls": calls}])
    try:
        result = p.stream_chat([], [], lambda _: None)
        assert result["tool_calls"] == calls
    finally:
        p.close()


def test_indexed_interleaved_tool_fragments_are_still_assembled(monkeypatch):
    p = provider(monkeypatch, [
        {"tool_calls": [{"index": 0, "id": "call-a", "function": {"name": "read_battle", "arguments": '{"id":'}}, {"index": 1, "id": "call-b", "function": {"name": "read_map", "arguments": "{"}}]},
        {"tool_calls": [{"index": 1, "function": {"arguments": "}"}}, {"index": 0, "function": {"arguments": '"battle-a"}'}}]},
    ])
    try:
        calls = p.stream_chat([], [], lambda _: None)["tool_calls"]
        assert [(x["id"], json.loads(x["function"]["arguments"])) for x in calls] == [("call-a", {"id": "battle-a"}), ("call-b", {})]
    finally:
        p.close()


@pytest.mark.parametrize("call", [
    {"function": {"name": "checkin", "arguments": "{}"}},
    {"id": "call-a", "function": {"name": "checkin", "arguments": "{"}},
])
def test_unidentifiable_or_incomplete_unindexed_calls_fail_as_provider_error(monkeypatch, call):
    p = provider(monkeypatch, [{"tool_calls": [call]}])
    try:
        with pytest.raises(ProviderFailure) as failure:
            p.stream_chat([], [], lambda _: None)
        assert failure.value.code == "PROVIDER_INVALID_RESPONSE"
    finally:
        p.close()
