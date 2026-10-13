"""Itemized self-report scoring. Judgments come from the labelled test adapter or explicit fixtures."""
import json

from knowledge_world import system, core_rules
from knowledge_world.common import uid, dumps
from knowledge_world.providers import FakeProvider


def report(h, content):
    action = h.post("/system/actions", {"client_action_id": uid(), "content": content})
    h.drain()
    return h.get(f"/system/actions/{action['id']}")


def test_multi_item_day_sums_tier_values_instead_of_one_action(h):
    heavy = report(h, "[测试：分项]\n算法题5道 [测试：困难]\n408真题一套 [测试：困难]\n数学4小时 [测试：困难]\n英语1小时")
    decision = heavy["decisions"][-1]
    assert [i["points"] for i in decision["items"]] == [80, 80, 80, 30]
    assert decision["applied_delta"] == 270 and heavy["net_points"] == 270
    light = report(h, "[测试：分项]\n数学2.5小时 [测试：困难]\n英语1小时\n背单词20分钟 [测试：轻量]")
    assert light["decisions"][-1]["applied_delta"] == 120 < decision["applied_delta"]
    entry = h.get("/ledger/" + decision["ledger_id"])
    assert len(entry["detail"]["items"]) == 4
    assert h.get("/wallet")["available_points"] == 390
    h.reconcile()


def test_off_tier_item_is_invalid_output_and_needs_review(h):
    action = report(h, "[测试：分项] [测试：档外]\n数学4小时 [测试：困难]\n英语1小时")
    decision = action["decisions"][-1]
    assert decision["state"] == "needs_review" and decision["review_code"] == "invalid_items"
    assert action["state"] == "needs_review" and h.get("/wallet")["available_points"] == 0


def test_per_item_cap_and_daily_cap_still_hold(h):
    with h.db.transaction(True, h.owner) as c:
        action = system.create_action(c, f"test:{uid()}", "SYNTHETIC 多项", queue=False)
        items = [{"name": f"突破 {n}", "tier": "breakthrough", "points": 150} for n in range(8)]
        decision = system.propose_decision(c, action["id"], {"reason": "SYNTHETIC", "items": items}, {"is_test_adapter": True})
        assert decision["proposed_points"] == 1200
        applied = system.apply_decision(c, decision["id"])
    # 8 × 150 is allowed per item (each ≤ max_award_per_action) but the day stops at 1000.
    assert applied["approved_points"] == 1000 and h.get("/wallet")["available_points"] == 1000
    h.reconcile()


def test_legacy_single_point_judgment_still_capped_per_action(h):
    with h.db.transaction(True, h.owner) as c:
        action = system.create_action(c, f"test:{uid()}", "SYNTHETIC 旧式判定", queue=False)
        decision = system.propose_decision(c, action["id"], {"points": 500, "reason": "SYNTHETIC"}, {"is_test_adapter": True})
        assert system.apply_decision(c, decision["id"])["approved_points"] == 200


def test_judge_receives_tier_criteria_and_recent_calibration(h, monkeypatch):
    report(h, "[测试：分项]\n408真题一套 [测试：困难]")
    seen = {}
    original = FakeProvider.structured

    def spy(self, prompt, payload, schema):
        seen.update(prompt=prompt, payload=payload)
        return original(self, prompt, payload, schema)
    monkeypatch.setattr(FakeProvider, "structured", spy)
    report(h, "[测试：分项]\n数学4小时 [测试：困难]")
    assert set(seen["payload"]["tier_criteria"]) == {"small", "normal", "difficult", "breakthrough"}
    anchors = seen["payload"]["calibration"]
    assert len(anchors) == 1 and anchors[0]["points"] == 80 and anchors[0]["items"][0]["tier"] == "difficult"
    assert "items" in seen["prompt"] and "档位外" in seen["prompt"]


def test_activated_older_rules_get_a_new_derived_version(h):
    with h.db.transaction(True, h.owner) as c:
        current = c.rules()
        assert current["version"] == core_rules.TARGET and "tier_criteria" in current["system"]
        old = json.loads(dumps(current))
        old["version"] = "system-core-2026-10-10.custom"
        for key in core_rules.UPGRADES[core_rules.TARGET]:
            old["system"].pop(key)
        old["system"]["daily_positive_action_cap"] = 777
        c.execute("UPDATE rule_versions SET is_active=0 WHERE is_active=1")
        c.insert("rule_versions", id=old["version"], payload_json=dumps(old), is_active=1, created_at=c.now)
        core_rules.activate(c)
        upgraded = c.rules()
        assert upgraded["version"] != old["version"] and upgraded["derived_from"] == old["version"]
        assert upgraded["system"]["daily_positive_action_cap"] == 777 and "tier_criteria" in upgraded["system"]
        assert json.loads(c.get("rule_versions", old["version"])["payload_json"]) == old
