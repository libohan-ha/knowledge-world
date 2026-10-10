"""Fault-injection child. Explicit isolated test settings; no production hooks."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import threading

import httpx

from knowledge_world import agent, battle, jobs
from knowledge_world.config import Settings
from knowledge_world.db import Database
from knowledge_world.providers import FakeProvider


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--clock", type=int, required=True)
    parser.add_argument("--checkpoint", default="none")
    parser.add_argument("--signal", type=Path, required=True)
    parser.add_argument("--server", default="")
    args = parser.parse_args()

    def checkpoint(name):
        if args.checkpoint == name:
            args.signal.write_text(json.dumps({"synthetic": True, "checkpoint": name}), encoding="utf-8")
            threading.Event().wait(45)
            raise RuntimeError("Parent did not terminate the child")

    original_claim = jobs.claim_job

    def claim(*values):
        result = original_claim(*values)
        if result:
            checkpoint("claimed")
        return result

    jobs.claim_job = claim
    original_simulate = battle.simulate

    def simulate(*values):
        result = original_simulate(*values)
        checkpoint("simulated")
        return result

    battle.simulate = simulate
    original_external = jobs.record_external

    def external(*values):
        checkpoint("before_external")
        return original_external(*values)

    jobs.record_external = external

    def request(payload):
        response = httpx.post(args.server, json={"synthetic": True, **payload}, timeout=5)
        response.raise_for_status()
        checkpoint("after_external")

    def structured(self, prompt, payload, schema):
        request({"kind": "assessment", "action_id": payload["action"]["id"]})
        return schema.model_validate({"points": 30, "reason": "SYNTHETIC 已提供完整行动产出", "basis": "action"}).model_dump()

    def stream_chat(self, messages, offered, on_text):
        request({"kind": "agent"})
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not results:
            name, arguments = "record_action", {}
        elif not any(r.get("state") == "applied" for r in results):
            name, arguments = "propose_judgment", {"action_id": results[0]["id"], "points": 30, "reason": "SYNTHETIC 晨跑有具体产出", "basis": "action"}
        else:
            return {"role": "assistant", "content": "SYNTHETIC 系统已按正式回执记录 30 积分。"}
        return {"role": "assistant", "content": None, "tool_calls": [{"id": name, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}

    FakeProvider.structured = structured
    FakeProvider.stream_chat = stream_chat
    original_local = agent.local_tool

    def local_tool(*values, **kwargs):
        result = original_local(*values, **kwargs)
        if result.get("state") == "applied":
            checkpoint("after_tool")
        return result

    agent.local_tool = local_tool
    original_complete = jobs.complete_job

    def complete(*values):
        result = original_complete(*values)
        checkpoint("before_commit")
        return result

    jobs.complete_job = complete
    original_transaction = Database.transaction

    @contextmanager
    def transaction(self, *values, **kwargs):
        terminal = False
        with original_transaction(self, *values, **kwargs) as c:
            yield c
            if args.checkpoint == "after_commit":
                terminal = bool(c.scalar("SELECT count(*) FROM jobs WHERE state='succeeded'"))
        if terminal:
            checkpoint("after_commit")

    Database.transaction = transaction
    db = Database(Settings(data_dir=args.directory, mode="test", fake_provider=True), lambda: args.clock)
    try:
        jobs.run_once(db, "SYNTHETIC PROCESS RECOVERY")
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
