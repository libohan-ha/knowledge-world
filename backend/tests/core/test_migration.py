import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
from knowledge_world.api import create_app
from knowledge_world.config import Settings
from knowledge_world.common import uid
from knowledge_world import core_rules
from conftest import Clock, Harness


def test_legacy_contract_checkin_assets_and_rules_survive_and_remain_fulfillable(tmp_path):
    directory = tmp_path / "legacy-world"
    command = [sys.executable, "-X", "utf8", str(Path(__file__).with_name("build_legacy_fixture.py")), "--directory", str(directory)]
    built = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert built.returncode == 0, built.stderr
    before = json.loads((directory / "synthetic-before.json").read_text(encoding="utf-8"))
    clock = Clock()
    clock.value = before["now"]
    app = create_app(Settings(data_dir=directory, mode="test", fake_provider=True, origin="http://testserver"), clock)
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"password": "testing-password"}, headers={"Origin": "http://testserver"})
        assert response.status_code == 200, response.text
        h = Harness(client, clock, app.state.db, before["owner"])
        with h.db.transaction(True, h.owner) as c:
            assert c.scalar("SELECT version_num FROM alembic_version") == "0015"
            for original in before["ledger"]:
                current = c.get("ledger_entries", original["id"])
                assert {key: current[key] for key in original} == original
            current_wallet = c.get("wallets", h.owner, key="owner_id")
            assert current_wallet == before["wallet"]
            assert c.get("commitments", before["contract"]["id"]) == before["contract"]
            for rule in before["rules"]:
                assert c.get("rule_versions", rule["id"])["payload_json"] == rule["payload_json"]
            for occurrence in before["occurrences"]:
                assert c.get("habit_occurrences", occurrence["id"]) == occurrence
            assert c.get("jobs", before["retired_job_id"])["state"] == "cancelled"
            assert c.get("redemptions", before["unknown_order_id"])["state"] == "needs_review"
            sizes = {name:c.scalar(f"SELECT count(*) FROM {name}") for name in ["heroes","monsters","home_items","game_events","ledger_entries"]}
            core_rules.activate(c)
            assert sizes == {name:c.scalar(f"SELECT count(*) FROM {name}") for name in sizes}
        h.reconcile()
        home = h.get("/world/home")
        assert any(item["legacy_ref"] for item in home["items"])
        assert h.get("/world/history")["coverage"]["total_events"] >= 1
        asset = before["assets"][0]
        assert h.request("GET", f"/assets/{asset['id']}/file").content
        clock.set("2026-10-10", "06:45")
        old_attempts = h.scalar("SELECT count(*) FROM card_attempts")
        checked = h.post("/system/checkin")
        assert checked["streak"] == 2 and checked["awarded_points"] == 6
        assert checked["terms"]["penalty_enabled"] and checked["terms"]["penalty_coins"] == 17
        assert h.scalar("SELECT count(*) FROM card_attempts") == old_attempts
        wager_id = before["contract"]["id"]
        skill = next(s for s in h.get("/settings/skills")["skills"] if s["skill"] == "wager")
        h.patch("/settings/skills", {"skill":"wager", "enabled":False, "expected_version":skill["version"]})
        h.drain()  # Original accepted contract's pending assessment still runs.
        current = h.get(f"/system/wagers/{wager_id}")
        assert current["legacy_compatibility"] and current["progress_points"] == 50 and current["state"] == "active"
        fact = h.post(f"/system/wagers/{wager_id}/facts", {"client_fact_id":uid(), "title":"SYNTHETIC 新兼容产出", "evidence":"[测试：通过] SYNTHETIC 我给出了第二份完整推导与核对依据，此证据通过存量合约内部路径提交，不建设新的学习产品。"})
        h.post(f"/system/legacy-facts/{fact['id']}/revisions", {"expected_version":fact["version"], "content":"[测试：通过] SYNTHETIC 补充原推导的边界条件与结论，保留最初提交时间。"})
        h.drain()
        settled = h.get(f"/system/wagers/{wager_id}")
        assert settled["state"] == "won" and settled["progress_points"] == 100
        assert settled["rule_version"] == before["contract"]["rule_version"]
        assert settled["terms_hash"] == current["terms_hash"]
        ledger = h.get(f"/ledger/{settled['settlement_ledger_id']}")
        assert ledger["available_delta"] == 180 and ledger["held_delta"] == -100
        assert h.post(f"/system/wagers/{wager_id}/settle")["settlement_ledger_id"] == settled["settlement_ledger_id"]
        h.request("POST", f"/system/wagers/{wager_id}/facts", {"client_fact_id":uid(), "title":"不应重开学习", "evidence":"SYNTHETIC "*10}, status=410)
        order = next(o for o in h.get('/maintenance/legacy-orders')["items"] if o["id"] == before["unknown_order_id"])
        assert order["state"] == "needs_review" and order["can_close"]
        close = {"expected_version":order["version"], "reason":"SYNTHETIC 用户明确结束旧未知尝试"}
        first = h.post(f"/maintenance/legacy-orders/{order['id']}/close", close, key="same-close")
        assert h.post(f"/maintenance/legacy-orders/{order['id']}/close", close, key="same-close") == first
        h.reconcile()
        assert h.scalar("SELECT count(*) FROM heroes") == 1
