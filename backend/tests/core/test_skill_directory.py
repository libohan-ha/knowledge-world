import json

from knowledge_world.common import uid
from knowledge_world.providers import FakeProvider


def test_installed_but_unconfigured_shiyi_is_described_to_agent(h, monkeypatch):
    directory = h.get("/settings/skills")
    skill = next(s for s in directory["skills"] if s["skill"] == "shiyi")
    assert skill["status"] == "not_configured" and skill["available"] is False
    assert skill["settings_path"] == "/settings?tab=integrations"
    assert "read_skills" in {t["name"] for t in directory["tools"]}
    seen = []
    def stream(self, messages, tools, on_text):
        seen.append(messages[0]["content"])
        assert '"status":"not_configured"' in messages[0]["content"]
        if messages[-1]["role"] != "tool":
            return {"role": "assistant", "tool_calls": [{"id": "skills", "type": "function", "function": {"name": "read_skills", "arguments": "{}"}}]}
        result = json.loads(messages[-1]["content"])
        assert any(s["skill"] == "shiyi" and not s["available"] for s in result["skills"])
        return {"role": "assistant", "content": "拾忆已安装，当前账户尚未配置连接，请到设置的 Skill 页面连接。"}
    monkeypatch.setattr(FakeProvider, "stream_chat", stream)
    thread = h.post("/system/threads")
    receipt = h.post(f"/system/threads/{thread['id']}/messages", {"content": "可以调用 shiyi skills 吗", "client_message_id": uid()})
    h.drain()
    assert h.get("/jobs/"+receipt["job_id"])["state"] == "succeeded"
    assert seen and h.scalar("SELECT count(*) FROM ledger_entries") == 0


def test_disabled_shiyi_is_not_exposed_but_remains_in_directory(h):
    h.patch("/settings/skills", {"skill": "shiyi", "enabled": False, "expected_version": 1})
    directory = h.get("/settings/skills")
    assert next(s for s in directory["skills"] if s["skill"] == "shiyi")["status"] == "disabled"
    assert not any(t["name"].startswith("shiyi_") for t in directory["tools"])
