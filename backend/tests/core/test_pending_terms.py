"""Pending terms cards: one card per identical proposal, gone once accepted, declined or expired."""
from knowledge_world import agent, system, game_models as g, models as m
from knowledge_world.common import uid, dumps

TERMS = {"title": "早睡早起 +10h学习", "goal": "数学/408/英语三线开花", "reward_points": 80, "penalty_points": 20, "penalty_condition": "未完成 10 小时"}


def thread_with_runs(c, count):
    thread = agent.create_thread(c, m.ThreadCreate(title="SYNTHETIC terms", context={}))
    runs = []
    for _ in range(count):
        run = c.insert("agent_runs", id=uid(), owner_id=c.owner, thread_id=thread["id"], state="succeeded", prompt_version="test",
            provider_snapshot_json="{}", context_snapshot_json=dumps({"message_id": uid()}), created_at=c.now)
        runs.append(c.get("agent_runs", run["id"]))
    return thread, runs


def call(c, run, name, arguments):
    result = agent.execute_tool(c, name, arguments, run, "SYNTHETIC")
    agent.save_tool_call(c, run, name, arguments, result, uid())
    return result


def test_identical_challenge_proposed_twice_is_one_entity_and_one_card(h):
    with h.db.transaction(True, h.owner) as c:
        thread, (first_run, second_run) = thread_with_runs(c, 2)
        first = call(c, first_run, "propose_challenge", TERMS)
        again = call(c, first_run, "propose_challenge", {**TERMS, "title": " " + TERMS["title"] + " "})
        later = call(c, second_run, "propose_challenge", TERMS)
        assert first["id"] == again["id"] == later["id"]
        assert c.scalar("SELECT count(*) FROM system_challenges WHERE owner_id=:o", {"o": c.owner}) == 1
        cards = agent.thread_detail(c, thread["id"])["actions"]
        assert len(cards) == 1 and cards[0]["run_id"] == second_run["id"]
        different = call(c, second_run, "propose_challenge", {**TERMS, "reward_points": 60})
        assert different["id"] != first["id"] and len(agent.thread_detail(c, thread["id"])["actions"]) == 2


def test_identical_wager_proposal_is_reused(h):
    with h.db.transaction(True, h.owner) as c:
        thread, (run,) = thread_with_runs(c, 1)
        terms = {"title": "今天再向前一步", "target_points": 300, "stake_points": 100, "bonus_points": 100}
        assert call(c, run, "propose_wager", terms)["id"] == call(c, run, "propose_wager", terms)["id"]
        assert len(agent.thread_detail(c, thread["id"])["actions"]) == 1


def test_legacy_duplicate_rows_collapse_and_expired_or_declined_terms_leave(h):
    with h.db.transaction(True, h.owner) as c:
        thread, (run,) = thread_with_runs(c, 1)
        deadline = "2026-10-10T21:00:00+08:00"
        for _ in range(2):  # rows created before proposals were idempotent
            identity = uid()
            data = g.ChallengeProposal(**TERMS, deadline_at=deadline)
            c.insert("system_challenges", id=identity, owner_id=c.owner, **data.model_dump(exclude={"deadline_at"}), deadline_at=c.now + 3600_000,
                rule_version=c.rules()["version"], terms_json=dumps(data.model_dump()), state="proposed", created_at=c.now)
            agent.save_tool_call(c, run, "propose_challenge", {}, system.challenge_view(c, identity), uid())
        assert len(agent.thread_detail(c, thread["id"])["actions"]) == 1
    h.clock.advance(seconds=3601)
    with h.db.transaction(True, h.owner) as c:
        assert agent.thread_detail(c, thread["id"])["actions"] == []
        declined = call(c, run, "propose_challenge", TERMS)
        assert len(agent.thread_detail(c, thread["id"])["actions"]) == 1
        c.update("system_challenges", declined["id"], state="cancelled")
        assert agent.thread_detail(c, thread["id"])["actions"] == []


def test_declining_a_card_withdraws_the_proposal(h):
    with h.db.transaction(True, h.owner) as c:
        thread, (run,) = thread_with_runs(c, 1)
        challenge = call(c, run, "propose_challenge", TERMS)
    card = h.get(f"/system/threads/{thread['id']}")["actions"][0]
    h.post(f"/system/actions/{card['id']}/decline")
    assert h.get(f"/system/threads/{thread['id']}")["actions"] == []
    assert next(r for r in h.get("/system/context")["challenges"] if r["id"] == challenge["id"])["state"] == "cancelled"
