"""Create labelled legacy obligations using the preserved pre-refactor program.

Runs only in an explicitly supplied isolated directory, never the user's data.
"""
# ruff: noqa: E402 -- imports must follow the preserved baseline path selection.
import argparse
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
baseline = root / "backend/legacy-fixture"
target = args.directory.resolve()
assert target != (root / "data").resolve() and not target.exists()
target.mkdir(parents=True)
os.environ["KW_DATA_DIR"] = str(target)
sys.path.insert(0, str(baseline / "backend/src"))
sys.path.insert(0, str(baseline / "backend/tests"))
from conftest import Clock, Harness
from fastapi.testclient import TestClient
from knowledge_world.api import create_app
from knowledge_world.config import Settings
from knowledge_world import jobs, routines

clock = Clock()
clock.set("2026-10-08", "06:30")
app = create_app(Settings(data_dir=target, mode="test", fake_provider=True, origin="http://testserver"), clock)
with TestClient(app) as client:
    response = client.post("/api/v1/setup", json={"display_name": "SYNTHETIC 旧账户", "password": "testing-password", "timezone": "Asia/Shanghai"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 200, response.text
    h = Harness(client, clock, app.state.db, response.json()["data"]["profile"]["id"])
    h.fund(2000)
    point = h.point("SYNTHETIC 历史成果")
    activity = h.activity(point=point, narrative="SYNTHETIC 旧成果与学习积分，迁移不得重新兑换。")
    h.assess(activity)
    card = h.card(point=point)
    clock.set("2026-10-08", "06:45")
    checkin = h.post("/checkins")
    h.answer(checkin["attempt"], "SYNTHETIC 已回答启动题")
    h.post(f"/checkins/{checkin['occurrence']['id']}/complete", {"expected_version": checkin["occurrence"]["version"], "startup_attempt_id": checkin["attempt"]["id"]})
    plan = next(p for p in h.get("/habits")["plans"] if p["kind"] == "checkin")
    h.request("PUT", f"/habit-plans/{plan['id']}/rest-days/2026-10-09", {})
    h.post(f"/habit-plans/{plan['id']}/revisions", {"expected_version": plan["version"], "terms": {"penalty_enabled": True, "penalty_coins": 17}})
    decoration = h.redeem("decoration_basic")
    delivered = h.redeem("generated_image", {"prompt": "SYNTHETIC licensed test fixture"})
    h.drain()
    clock.set("2026-10-09", "08:00")
    with h.db.transaction(True, h.owner) as c:
        routines.daily_catchup(c)
    clock.set("2026-10-10", "06:40")
    wager = h.post("/commitments/proposals", {"title": "SYNTHETIC 旧学习口径合约", "target_points": 100, "stake_coins": 100, "bonus_coins": 80})
    wager = h.post(f"/commitments/{wager['id']}/accept", {"expected_version": wager["version"], "terms_hash": wager["terms_hash"]})
    old_fact = h.activity(point=h.point("SYNTHETIC 接受后待评估事实"), narrative="[测试：通过] SYNTHETIC 这是截止前已提交的旧合约产出，附有完整解释与推导，等待原规则评估。")
    h.post(f"/activities/{old_fact['id']}/submit", {"expected_version": old_fact["version"]})
    unknown = h.redeem("generated_image", {"prompt": "SYNTHETIC 外部结果未知，不得自动重发"})
    with h.db.transaction(True, h.owner) as c:
        c.execute("UPDATE jobs SET state='running',external_request_started_at=:at,lease_until=:until WHERE json_extract(payload_json,'$.redemption_id')=:id", {"at": c.now, "until": c.now+60000, "id": unknown["id"]})
        c.update("redemptions", unknown["id"], state="running")
        retired = jobs.enqueue(c, "report", "SYNTHETIC-retired-report", {})
        before = {
            "synthetic": True, "owner": h.owner, "rule_version": c.rules()["version"], "now": clock(),
            "wallet": c.get("wallets", h.owner, key="owner_id"),
            "ledger": c.all("SELECT * FROM ledger_entries ORDER BY sequence"),
            "contract": c.get("commitments", wager["id"]), "plan": c.get("habit_plans", plan["id"]),
            "occurrences": c.all("SELECT * FROM habit_occurrences WHERE plan_id=:id", {"id": plan["id"]}),
            "old_fact_id": old_fact["id"], "unknown_order_id": unknown["id"],
            "delivered_order_id": delivered["id"], "retired_job_id": retired["id"],
            "assets": c.all("SELECT * FROM generated_assets"), "inventory": c.all("SELECT * FROM inventory_items"),
            "rules": c.all("SELECT * FROM rule_versions"),
        }
    h.reconcile()
    (target / "synthetic-before.json").write_text(json.dumps(before, ensure_ascii=False), encoding="utf-8")
print(json.dumps({"synthetic": True, "head": "0010", "directory": str(target), "contract_id": wager["id"]}, ensure_ascii=False))
