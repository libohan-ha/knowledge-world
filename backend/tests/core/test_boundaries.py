"""Cutoffs, corrections and fixed terms, using explicit synthetic judgments."""

import pytest

from knowledge_world import identity, system
from knowledge_world.common import local_ms, uid
from knowledge_world.providers import FakeProvider
from test_core_behavior import accept, buy, judge


def test_unchanged_uncertain_evidence_can_complete_wager_during_grace(h, monkeypatch):
    h.fund(20)
    wager = accept(h, h.post("/system/wagers", {"target_points": 30, "stake_points": 20, "bonus_points": 80}))
    with h.db.transaction(True, h.owner) as c:
        action = system.create_action(c, uid(), "SYNTHETIC 截止前已经提交的行动证据", queue=False)
        system.propose_decision(c, action["id"], {"points": 0, "status": "needs_review", "reason": "SYNTHETIC 需要核对", "basis": "action"})
        original_cutoff = c.scalar("SELECT evidence_cutoff_at FROM system_decisions WHERE action_id=:id", {"id": action["id"]})
    h.clock.set("2026-10-11", "00:10")
    assert h.post(f"/system/wagers/{wager['id']}/settle")["state"] == "pending_settlement"
    monkeypatch.setattr(FakeProvider, "structured", lambda *_: {"points": 30, "reason": "SYNTHETIC 对原证据的有效判断", "basis": "action"})
    continued = h.post(f"/system/actions/{action['id']}/resume")
    assert continued["version"] == 2 and continued["content"] == action["content"]
    h.drain()
    settled = h.get(f"/system/wagers/{wager['id']}")
    assert settled["state"] == "won" and settled["progress_points"] == 30
    with h.db.transaction(owner=h.owner) as c:
        assert c.scalar("SELECT evidence_cutoff_at FROM system_decisions WHERE action_id=:id AND action_version=2", {"id": action["id"]}) == original_cutoff
    h.reconcile()


def test_new_evidence_after_wager_deadline_cannot_be_backdated(h):
    h.fund(20)
    wager = accept(h, h.post("/system/wagers", {"target_points": 30, "stake_points": 20, "bonus_points": 80}))
    decision = judge(h, 10)
    h.clock.set("2026-10-11", "00:10")
    h.post(f"/system/actions/{decision['action_id']}/revisions", {"expected_version": 1, "content": "SYNTHETIC 截止后才新增的行动成果"})
    judge(h, 80, action_id=decision["action_id"])
    current = h.get(f"/system/wagers/{wager['id']}")
    assert current["progress_points"] == 10 and current["state"] == "lost"
    judge(h, 30)  # A new post-deadline action cannot change a terminal contract.
    assert h.get(f"/system/wagers/{wager['id']}")["state"] == "lost"


def test_system_failure_voids_only_its_hold_after_original_grace(h):
    h.fund(100)
    wager = accept(h, h.post("/system/wagers", {"target_points": 30, "stake_points": 20, "bonus_points": 80}))
    buy(h, "leisure", next(r["id"] for r in h.get("/rewards") if r["price_points"] == 30))
    h.post("/system/actions", {"client_action_id": uid(), "content": "[测试：超时] SYNTHETIC 截止前的事实需要等待服务恢复"})
    h.drain()
    h.clock.set("2026-10-11", "23:59")
    assert h.post(f"/system/wagers/{wager['id']}/settle")["state"] == "pending_settlement"
    h.clock.set("2026-10-12", "00:00")
    assert h.post(f"/system/wagers/{wager['id']}/settle")["state"] == "voided"
    assert h.get("/wallet")["held_points"] == 30
    assert h.get("/wallet")["available_points"] == 70
    h.reconcile()


def test_insufficient_correction_retries_same_evidence_without_provider(h, monkeypatch):
    decision = judge(h, 80)
    h.post("/system/adjustments", {"points": -80, "reason": "SYNTHETIC 已消费", "command_key": uid()})
    h.post(f"/system/actions/{decision['action_id']}/revisions", {"expected_version": 1, "content": "SYNTHETIC 明确更正，此事未完成"})
    waiting = judge(h, 0, action_id=decision["action_id"])
    assert waiting["state"] == "needs_review" and waiting["review_code"] == "insufficient_available"
    h.fund(80)
    monkeypatch.setattr(FakeProvider, "structured", lambda *_: pytest.fail("An approved correction must not buy another model judgment"))
    restored = h.post(f"/system/actions/{decision['action_id']}/resume")
    assert restored["state"] == "settled" and restored["net_points"] == 0 and restored["version"] == 3
    latest = next(d for d in restored["decisions"] if d["action_version"] == 3)
    assert latest["applied_delta"] == -80 and latest["supersedes_id"] == decision["id"]
    assert h.get("/wallet")["available_points"] == 0
    h.reconcile()


def test_refunding_old_penalty_does_not_require_reenabling_disabled_rule(h):
    h.fund(100)
    rule = h.post("/system/penalty-rules", {"title": "SYNTHETIC 原授权", "condition": "已核对具体事实", "points": 50})
    h.clock.advance(days=1)
    original = judge(h, -50, basis=f"rule:{rule['id']}")
    h.request("DELETE", f"/system/penalty-rules/{rule['id']}")
    h.post(f"/system/actions/{original['action_id']}/revisions", {"expected_version": 1, "content": "SYNTHETIC 核对后仅有一部分符合条件"})
    corrected = judge(h, -20, action_id=original["action_id"], basis=f"rule:{rule['id']}")
    assert corrected["applied_delta"] == 30 and h.get("/wallet")["available_points"] == 80
    h.reconcile()


def test_positive_correction_does_not_reopen_daily_reward_cap(h):
    decisions = [judge(h, 200) for _ in range(5)]
    first = decisions[0]
    h.post(f"/system/actions/{first['action_id']}/revisions", {"expected_version": 1, "content": "SYNTHETIC 撤销第一项错误奖励"})
    assert judge(h, 0, action_id=first["action_id"])["applied_delta"] == -200
    assert judge(h, 200)["applied_delta"] == 0
    h.clock.advance(days=1)
    assert judge(h, 30)["applied_delta"] == 30


def test_fixed_challenge_terms_and_pending_result_preserve_one_action(h):
    proposal = h.post("/system/challenges", {"title": "SYNTHETIC 条件任务", "goal": "写出实际产出", "reward_points": 80, "penalty_points": 30, "penalty_condition": "明确自认满足失败条件"})
    h.post(f"/system/challenges/{proposal['id']}/resolve", {"expected_version": 1, "outcome": "failed", "evidence": "尚未接受"}, status=409)
    accepted = h.post(f"/system/challenges/{proposal['id']}/accept", {"expected_version": 1, "terms_hash": proposal["terms_hash"]})
    original = judge(h, 100)
    h.post("/system/adjustments", {"points": -100, "reason": "SYNTHETIC 验证纠错边界", "command_key": uid()})
    result = h.post(f"/system/challenges/{proposal['id']}/resolve", {"expected_version": accepted["version"], "outcome": "completed", "evidence": "SYNTHETIC 任务仅应给80，原行动多给20", "action_id": original["action_id"]})
    assert result["state"] == "needs_review"
    h.fund(20)
    final = h.post(f"/system/challenges/{proposal['id']}/resolve", {"expected_version": result["version"], "outcome": "completed", "evidence": "SYNTHETIC 余额补齐，继续同一任务的实际差额"})
    assert final["state"] == "completed" and final["action_id"] == original["action_id"]
    assert h.scalar("SELECT count(*) FROM system_actions") == 1
    assert h.get("/wallet")["available_points"] == 0
    h.reconcile()


def test_rules_publish_does_not_rewrite_accepted_terms_or_old_quotes(h):
    h.fund(300)
    wager = accept(h, h.post("/system/wagers", {"target_points": 30, "stake_points": 20, "bonus_points": 800}))
    quote = h.post("/roster/quotes", {"operation": "hero_train", "attribute": "mana"})
    rules = h.get("/rules")["rules"]
    updated = h.post("/rules/versions", {"based_on_version": rules["version"], "changes": {"system.daily_positive_action_cap": 40}})
    assert updated["version"] != rules["version"]
    h.post("/roster/orders", {"quote_token": quote["quote_token"]}, status=409)
    judge(h, 80)
    settled = h.get(f"/system/wagers/{wager['id']}")
    assert settled["state"] == "won" and settled["rule_version"] == wager["rule_version"]
    assert settled["terms_hash"] == wager["terms_hash"]
    entry = h.get(f"/ledger/{settled['settlement_ledger_id']}")
    assert entry["available_delta"] == 820
    with h.db.transaction(owner=h.owner) as c:
        assert c.rules(rules["version"]) == rules


def test_checkin_window_timezone_and_streak_break_are_server_authoritative(h):
    h.clock.set("2026-10-10", "06:44")
    h.post("/system/checkin", status=409)
    h.clock.set("2026-10-10", "06:45")
    first = h.post("/system/checkin")
    assert first["awarded_points"] == 5
    profile = h.get("/me")["profile"]
    h.patch("/me", {"expected_version": profile["version"], "timezone": "Pacific/Kiritimati"})
    h.clock.set("2026-10-11", "00:45")  # Local next day 06:45, only 18 real hours later.
    with h.db.transaction(True, h.owner) as c:
        identity.apply_pending_timezone(c)
    assert not h.get("/system/checkin")["eligible"]
    h.post("/system/checkin", status=409)
    h.clock.value = local_ms("2026-10-12", "07:15", "Pacific/Kiritimati")
    with h.db.transaction(True, h.owner) as c:
        c.insert("service_availability", id=uid(), process_id="SYNTHETIC observed window", started_at=local_ms("2026-10-12", "06:40", c.tz), through_at=c.now)
    assert h.get("/system/checkin")["occurrence"]["state"] == "missed"
    h.post("/system/checkin", status=409)
    h.clock.value = local_ms("2026-10-13", "06:45", "Pacific/Kiritimati")
    next_check = h.post("/system/checkin")
    assert next_check["streak"] == 1 and next_check["awarded_points"] == 5
    with h.db.transaction(owner=h.owner) as c:
        original = c.get("habit_occurrences", first["occurrence"]["id"])
        assert original["timezone_snapshot"] == "Asia/Shanghai"
    h.reconcile()


def test_expired_session_is_rejected_even_for_the_only_local_account(h):
    """Single-account deployments still enforce session authentication."""
    with h.db.transaction(True, h.owner) as c:
        c.execute("UPDATE auth_sessions SET expires_at=:at WHERE owner_id=:o", {"at": c.now - 1, "o": h.owner})
    h.request("GET", "/me", status=401)
