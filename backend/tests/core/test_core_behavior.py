"""System-core acceptance behavior. All model judgments here are labelled fixtures.

The shared harness uses temporary on-disk WAL databases, never a memory connection.
"""
import json

import pytest

from knowledge_world import game_models as g, system, battle
from knowledge_world.common import uid, DomainError, local_ms
from knowledge_world.config import ROOT


def judge(h, points, *, action_id=None, content="SYNTHETIC: 完成一次晨跑", basis="action"):
    with h.db.transaction(True, h.owner) as c:
        action = system.action_view(c, action_id) if action_id else system.create_action(c, f"test:{uid()}", content, queue=False)
        decision = system.propose_decision(c, action["id"], {"points": points, "reason": "SYNTHETIC validated judgment", "basis": basis}, {"is_test_adapter": True})
        return system.apply_decision(c, decision["id"])


def buy(h, operation, target=None, attribute=None):
    prefix = "/rewards" if operation == "leisure" else "/world/home" if operation.startswith("home_") else "/roster"
    quote = h.post(prefix + "/quotes", {"operation": operation, "target_id": target, "attribute": attribute})
    receipt = h.post(prefix + "/orders", {"quote_token": quote["quote_token"]})
    g.CommandReceipt.model_validate(receipt)
    return receipt, quote


def accept(h, wager):
    return h.post(f"/system/wagers/{wager['id']}/accept", {"expected_version": wager["version"], "terms_hash": wager["terms_hash"]})


def test_clean_setup_and_pydantic_transport(h):
    for path, model in [("/roster", g.Roster), ("/world/home", g.Home), ("/world/map", g.WorldMap), ("/world/history", g.HistoryPage), ("/system/context", g.SystemContext), ("/system/checkin", g.Checkin)]:
        model.model_validate(h.get(path))
    assert h.get("/wallet")["available_points"] == 0
    assert h.scalar("SELECT count(*) FROM subjects") == 0
    assert h.scalar("SELECT count(*) FROM knowledge_points") == 0
    assert len(h.get("/roster")["monsters"]) == 1
    for path in ("/subjects", "/points", "/screen-time", "/monitor", "/activities", "/redemptions"):
        h.request("POST", path, {}, status=410)
    h.reconcile()


def test_reward_can_be_removed_without_touching_issued_ticket(h):
    h.fund(3)
    reward = h.post("/rewards", {"name": "SYNTHETIC removable", "description": "", "price_points": 3, "duration_minutes": 1})
    ticket, _ = buy(h, "leisure", reward["id"])
    h.request("DELETE", f"/rewards/{reward['id']}", {"expected_version": reward["version"]})
    assert all(item["id"] != reward["id"] for item in h.get("/rewards"))
    assert h.get(f"/leisure/{ticket['entity_id']}")["snapshot"]["id"] == reward["id"]
    h.request("POST", "/rewards/quotes", {"operation": "leisure", "target_id": reward["id"]}, status=409)


def test_checkin_is_shared_single_source_and_rest_keeps_streak(h):
    h.clock.set("2026-10-10", "06:45")
    first = h.post("/system/checkin")
    assert first["streak"] == 1 and first["awarded_points"] == 5
    assert h.post("/system/checkin")["ledger_entry_ids"] == first["ledger_entry_ids"]
    h.request("PUT", "/system/checkin/rest-days/2026-10-11", {})
    h.clock.set("2026-10-11", "07:00")
    assert h.get("/system/checkin")["occurrence"]["state"] == "rest"
    h.clock.set("2026-10-12", "07:00")
    assert h.get("/system/checkin")["streak"] == 1
    second = h.post("/system/checkin")
    assert second["streak"] == 2 and second["awarded_points"] == 6
    assert h.get("/wallet")["available_points"] == 11
    assert h.scalar("SELECT count(*) FROM card_attempts") == 0
    h.reconcile()


def test_checkin_outage_is_unknown_enabled_penalty_requires_available_window(h):
    h.fund(100)
    plan = h.get("/system/checkin/settings")
    h.patch("/system/checkin/settings", {"expected_version": plan["version"], "penalty_enabled": True, "weekdays": list(range(7))})
    h.clock.set("2026-10-11", "08:00")
    assert h.get("/system/checkin")["occurrence"]["state"] == "unknown"
    assert h.get("/wallet")["available_points"] == 100
    with h.db.transaction(True, h.owner) as c:
        c.insert("service_availability", id=uid(), process_id="SYNTHETIC full observed window", started_at=local_ms("2026-10-12", "06:40"), through_at=local_ms("2026-10-12", "07:15"))
    h.clock.set("2026-10-12", "07:15")
    checkin = h.get("/system/checkin")
    assert checkin["occurrence"]["state"] == "missed"
    assert h.get("/wallet")["available_points"] == 90
    h.get("/system/checkin")
    assert h.get("/wallet")["available_points"] == 90


def test_action_limits_revision_and_insufficient_reversal(h):
    for _ in range(5):
        assert judge(h, 999)["applied_delta"] == 200
    assert judge(h, 30)["applied_delta"] == 0
    h.clock.advance(days=1)
    decision = judge(h, 30)
    action = h.get(f"/system/actions/{decision['action_id']}")
    h.post(f"/system/actions/{action['id']}/revisions", {"expected_version": 1, "content": "SYNTHETIC: 完整补充了晨跑和拉伸的产出"})
    corrected = judge(h, 80, action_id=action["id"])
    assert corrected["applied_delta"] == 50 and corrected["supersedes_id"] == decision["id"]
    entry = h.get("/ledger")["items"][0]
    assert entry["correction_of"] == decision["ledger_id"]
    with h.db.transaction(True, h.owner) as c:
        assert system.apply_decision(c, corrected["id"])["id"] == corrected["id"]
    available = h.get("/wallet")["available_points"]
    h.post("/system/adjustments", {"points": -available, "reason": "SYNTHETIC spend for reversal boundary", "command_key": uid()})
    h.post(f"/system/actions/{action['id']}/revisions", {"expected_version": 2, "content": "SYNTHETIC: 更正为未完成"})
    assert judge(h, 0, action_id=action["id"])["state"] == "needs_review"
    assert h.get("/wallet")["available_points"] == 0
    h.reconcile()


def test_penalty_authorization_caps_and_revisions_do_not_repeat(h):
    h.fund(300)
    with pytest.raises(DomainError, match="扣分需要"):
        judge(h, -50)
    rule = h.post("/system/penalty-rules", {"title": "已明确启用的规则", "condition": "自己确认已违反的条件", "points": 100})
    with pytest.raises(DomainError, match="未生效"):
        judge(h, -50, basis=f"rule:{rule['id']}")
    h.clock.advance(days=1)
    decision = judge(h, -50, basis=f"rule:{rule['id']}")
    h.post(f"/system/actions/{decision['action_id']}/revisions", {"expected_version": 1, "content": "SYNTHETIC: 重读同一次违反记录"})
    assert judge(h, -50, action_id=decision["action_id"], basis=f"rule:{rule['id']}")["applied_delta"] == 0
    assert judge(h, -100, basis=f"rule:{rule['id']}")["applied_delta"] == -100
    assert judge(h, -100, basis=f"rule:{rule['id']}")["applied_delta"] == -50
    assert h.get("/wallet")["available_points"] == 100


def test_same_action_and_adjustment_keys_reject_changed_payload(h):
    key = uid()
    body = {"client_action_id": key, "content": "SYNTHETIC: 完成十分钟整理房间"}
    first = h.post("/system/actions", body)
    assert h.post("/system/actions", body)["id"] == first["id"]
    h.post("/system/actions", {**body, "content": "不同事实"}, status=409)
    adjustment = {"points": 10, "reason": "SYNTHETIC adjustment", "command_key": uid()}
    h.post("/system/adjustments", adjustment)
    h.post("/system/adjustments", {**adjustment, "reason": "Changed reason"}, status=409)
    assert h.get("/wallet")["available_points"] == 10


def test_wager_counts_earned_after_acceptance_and_settles_once(h):
    h.fund(100)
    judge(h, 30)
    wager = accept(h, h.post("/system/wagers", {"title": "今日行动", "stake_points": 20, "target_points": 5, "bonus_points": 80}))
    assert wager["progress_points"] == 0
    assert h.get("/wallet")["held_points"] == 20
    buy(h, "hero_train", attribute="strength")
    h.post("/system/adjustments", {"points": 100, "reason": "SYNTHETIC excluded funding", "command_key": uid()})
    assert h.get(f"/system/wagers/{wager['id']}")["progress_points"] == 0
    h.clock.set("2026-10-10", "07:00")
    h.post("/system/checkin")
    won = h.post(f"/system/wagers/{wager['id']}/settle")
    g.Wager.model_validate(won)
    assert won["state"] == "won" and won["progress_points"] == 5
    balance = h.get("/wallet")
    assert balance["held_points"] == 0
    assert h.post(f"/system/wagers/{wager['id']}/settle")["settlement_ledger_id"] == won["settlement_ledger_id"]
    assert h.get("/wallet") == balance
    h.reconcile()


def test_skill_disabled_keeps_accepted_wager_and_failure_uses_own_hold(h):
    h.fund(200)
    wager = accept(h, h.post("/system/wagers", {"stake_points": 20, "target_points": 500, "bonus_points": 80}))
    ticket, _ = buy(h, "leisure", h.get("/rewards")[0]["id"])
    h.patch("/settings/skills", {"skill": "wager", "enabled": False, "expected_version": 1})
    h.clock.advance(days=1)
    with h.db.transaction(True, h.owner) as c:
        from knowledge_world.commitments import evaluate_all
        evaluate_all(c)
    assert h.get(f"/system/wagers/{wager['id']}")["state"] == "lost"
    assert h.get(f"/leisure/{ticket['entity_id']}")["state"] == "reserved"
    assert h.get("/wallet")["held_points"] == ticket["price_points"]
    h.reconcile()


def test_ordinary_challenge_links_existing_fact_by_difference(h):
    proposal = h.post("/system/challenges", {"title": "晨跑", "goal": "完成晨跑与拉伸", "reward_points": 80})
    challenge = h.post(f"/system/challenges/{proposal['id']}/accept", {"expected_version": 1, "terms_hash": proposal["terms_hash"]})
    d = judge(h, 30)
    done = h.post(f"/system/challenges/{challenge['id']}/resolve", {"expected_version": challenge["version"], "outcome": "completed", "evidence": "SYNTHETIC: 已完成晨跑与拉伸", "action_id": d["action_id"]})
    assert done["state"] == "completed" and done["action_id"] == d["action_id"]
    assert h.get("/wallet")["available_points"] == 80


def test_training_recruit_quote_reuse_and_team_validation(h):
    h.fund(2000)
    receipt, quote = buy(h, "hero_train", attribute="strength")
    assert receipt["before"]["attributes"]["strength"] + 1 == receipt["after"]["attributes"]["strength"]
    assert h.post("/roster/orders", {"quote_token": quote["quote_token"]})["command_id"] == receipt["command_id"]
    for code in ("shadow_wolf", "star_fox"):
        buy(h, "monster_recruit", code)
    roster = h.get("/roster")
    monster = roster["monsters"][0]
    buy(h, "monster_train", monster["id"])
    members = [m["id"] for m in roster["monsters"]] + [roster["hero"]["id"]]
    h.request("PUT", "/roster/team", {"expected_version": roster["team"]["version"], "member_ids": members})
    h.request("PUT", "/roster/team", {"expected_version": roster["team"]["version"] + 1, "member_ids": [members[0], members[0]]}, status=409)
    h.reconcile()


def test_leisure_freezes_snapshot_pause_resume_and_single_expiry(h):
    h.fund(300)
    reward = h.post("/rewards", {"name": "SYNTHETIC 休闲", "description": "计时边界", "price_points": 30, "duration_minutes": 1})
    receipt, _ = buy(h, "leisure", reward["id"])
    identity = receipt["entity_id"]
    h.patch(f"/rewards/{reward['id']}", {"name": "改价后的目录", "description": "不改旧券", "price_points": 90, "duration_minutes": 2, "expected_version": 1})
    ticket = h.get(f"/leisure/{identity}")
    assert ticket["snapshot"]["price_points"] == 30 and ticket["duration_seconds"] == 60
    ticket = h.post(f"/leisure/{identity}/start", {"expected_version": ticket["version"]})
    h.clock.advance(seconds=10.5)
    ticket = h.post(f"/leisure/{identity}/pause", {"expected_version": ticket["version"]})
    h.clock.advance(days=1)
    ticket = h.post(f"/leisure/{identity}/resume", {"expected_version": ticket["version"]})
    h.clock.advance(seconds=49.5)
    assert h.get(f"/leisure/{identity}")["remaining_seconds"] == 0
    with h.db.transaction(True, h.owner) as c:
        from knowledge_world.leisure import catchup
        catchup(c)
        catchup(c)
    ticket = h.get(f"/leisure/{identity}")
    g.LeisureTicket.model_validate(ticket)
    assert ticket["state"] == "completed"
    assert h.get("/wallet")["available_points"] == 270
    assert h.get("/wallet")["held_points"] == 0
    assert h.scalar("SELECT count(*) FROM notifications WHERE event_key LIKE 'leisure:%'") == 1
    h.reconcile()


def test_unstarted_ticket_refund_and_home_placement(h):
    h.fund(300)
    receipt, _ = buy(h, "leisure", h.get("/rewards")[0]["id"])
    ticket = h.get(f"/leisure/{receipt['entity_id']}")
    h.post(f"/leisure/{ticket['id']}/cancel", {"expected_version": ticket["version"]})
    assert h.get("/wallet")["available_points"] == 300
    decoration, _ = buy(h, "home_buy", "lantern")
    item = h.get("/world/home")["items"][-1]
    item = next(i for i in h.get("/world/home")["items"] if i["id"] == decoration["entity_id"])
    placed = h.request("PUT", f"/world/home/placements/{item['id']}", {"expected_version": item["version"], "x": 4, "z": 5, "rotation": 90}).json()["data"]
    h.request("PUT", f"/world/home/placements/{item['id']}", {"expected_version": placed["version"], "x": None, "z": None, "rotation": 0})
    assert h.get("/wallet")["available_points"] == 260


def test_battle_initial_route_snapshot_and_replay_is_read_only(h):
    world = h.get("/world/map")
    assert len(world["regions"]) >= 3 and len(world["outposts"]) >= 9
    h.post("/world/battles", {"outpost_id": "dawn_core", "team_version": world["team"]["version"], "command_key": uid()}, status=409)
    created = h.post("/world/battles", {"outpost_id": "fern_gate", "team_version": world["team"]["version"], "command_key": uid()})
    g.Battle.model_validate(created)
    h.fund(100)
    buy(h, "hero_train", attribute="agility")
    h.drain()
    finished = h.get(f"/world/battles/{created['id']}")
    g.Battle.model_validate(finished)
    assert finished["snapshot"] == created["snapshot"]
    assert finished["result"]["outcome"] == "won" and finished["result"]["first_clear"]
    assert finished["result"]["events"]
    result = battle.simulate(created["snapshot"], created["seed"])
    assert result["events"] == finished["result"]["events"]
    wallet = h.get("/wallet")
    h.get(f"/world/battles/{created['id']}")
    assert h.get("/wallet") == wallet
    assert h.get("/world/outposts/fern_gate")["status"] == "occupied"
    h.reconcile()


def test_initial_roster_can_progress_through_every_region_and_boss(h):
    """Initial, growing and maximum teams use real quotes and saved battles."""
    evidence, cleared = [], []

    def fight(outpost_id, expected, *, first=True):
        world = h.get("/world/map")
        site = next(item for item in world["outposts"] if item["id"] == outpost_id)
        assert site["status"] in {"available", "occupied"}
        before = h.get("/roster")
        wallet = h.get("/wallet")
        created = h.post("/world/battles", {"outpost_id": outpost_id, "team_version": world["team"]["version"], "command_key": uid()})
        h.drain()
        finished = h.get(f"/world/battles/{created['id']}")
        assert finished["result"]["outcome"] == expected, outpost_id
        assert finished["result"]["first_clear"] is (expected == "won" and first)
        # Combat HP/MP and casualties never mutate owned units or their levels.
        assert h.get("/roster") == before
        if expected == "lost" or not first:
            assert h.get("/wallet") == wallet
            assert finished["result"]["reward_points"] == 0
        else:
            cleared.append(outpost_id)
        saved_wallet = h.get("/wallet")
        assert h.get(f"/world/battles/{created['id']}") == finished
        assert h.get("/wallet") == saved_wallet
        # Record sensitivity to seed as well as the actual persisted HTTP run.
        wins = sum(battle.simulate(finished["snapshot"], f"{seed:032x}")["outcome"] == "won" for seed in range(20))
        assert wins == (20 if expected == "won" else 0), (outpost_id, wins)
        evidence.append({"battle": finished, "seed_sweep_wins": wins, "seed_sweep_count": 20})

    def grow(attribute_steps, monster_level):
        roster = h.get("/roster")
        for attribute in ("strength", "agility", "mana"):
            for _ in range(10 + attribute_steps - roster["hero"]["attributes"][attribute]):
                buy(h, "hero_train", attribute=attribute)
        for monster in roster["monsters"]:
            for _ in range(monster_level - monster["level"]):
                buy(h, "monster_train", monster["id"])

    fight("fern_gate", "won")
    fight("old_bridge", "won")
    fight("ancient_stag", "lost")
    # Synthetic income only supplies training prices; it is not AI evidence or
    # a claim that this amount is awarded at account creation.
    h.fund(50_000)
    buy(h, "monster_recruit", "shadow_wolf")
    buy(h, "monster_recruit", "star_fox")
    roster = h.get("/roster")
    monsters = {monster["code"]: monster["id"] for monster in roster["monsters"]}
    members = [monsters["moss_bear"], roster["hero"]["id"], monsters["shadow_wolf"], monsters["star_fox"]]
    h.request("PUT", "/roster/team", {"expected_version": roster["team"]["version"], "member_ids": members})
    grow(2, 3)
    fight("ancient_stag", "won")
    fight("snow_pass", "won")
    grow(5, 5)
    fight("frozen_lake", "won")
    grow(10, 10)
    for outpost_id in ("frost_crown", "sunken_gate", "star_observatory", "dawn_core"):
        fight(outpost_id, "won")
    assert cleared == [item["id"] for item in h.get("/world/map")["outposts"]]
    assert len(h.get("/world/home")["occupations"]) == 9
    grow(20, 20)
    fight("dawn_core", "won", first=False)
    assert len(h.get("/world/home")["occupations"]) == 9
    h.reconcile()
    artifact = ROOT / "artifacts/refactor/world-progression.json"
    artifact.write_text(json.dumps({"synthetic": True, "real_ai": False, "funding_fixture_points": 50_000,
        "scope": "Initial/growing/maximum roster reachability and settlement, not real-income pacing or visual acceptance",
        "cleared": cleared, "runs": evidence}, ensure_ascii=False, indent=2), encoding="utf-8")
