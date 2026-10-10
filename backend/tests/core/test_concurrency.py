"""Independent sessions and HTTP requests against an actual temporary WAL file."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

from knowledge_world import commitments, game, jobs, models as m, system
from knowledge_world.common import DomainError, uid


def parallel(actions):
    barrier = Barrier(len(actions))

    def execute(action):
        barrier.wait(timeout=10)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(execute, actions))


def race(h, actions):
    def execute(action):
        try:
            with h.db.transaction(True, h.owner) as c:
                return action(c)
        except DomainError as exc:
            return {"error": exc.code}

    return parallel([lambda action=action: execute(action) for action in actions])


def http_call(h, path, body, key=None):
    return h.client.post("/api/v1" + path, json=body, headers=h.headers(key))


def test_training_recruitment_leisure_penalty_and_wager_compete_for_one_wallet(h):
    h.fund(150)
    rule = h.post("/system/penalty-rules", {"title": "SYNTHETIC 明确罚则", "condition": "已确认的一次违约", "points": 100})
    h.clock.advance(days=1)
    leisure_id = next(r["id"] for r in h.get("/rewards") if r["price_points"] == 120)
    quotes = [
        h.post("/roster/quotes", {"operation": "hero_train", "attribute": "strength"}),
        h.post("/roster/quotes", {"operation": "monster_recruit", "target_id": "shadow_wolf"}),
        h.post("/rewards/quotes", {"operation": "leisure", "target_id": leisure_id}),
    ]
    wager = h.post("/system/wagers", {"stake_points": 100, "target_points": 500, "bonus_points": 800})
    with h.db.transaction(True, h.owner) as c:
        action = system.create_action(c, uid(), "SYNTHETIC 已确认一次违约", queue=False)
        decision = system.propose_decision(c, action["id"], {"points": -100, "reason": "SYNTHETIC 竞争余额", "basis": f"rule:{rule['id']}"})
        assert c.scalar("PRAGMA journal_mode") == "wal"
    results = race(h, [
        *[lambda c, quote=quote: game.order(c, quote["quote_token"]) for quote in quotes],
        lambda c: commitments.accept(c, wager["id"], m.AcceptTerms(expected_version=1, terms_hash=wager["terms_hash"])),
        lambda c: system.apply_decision(c, decision["id"]),
    ])
    assert any(result.get("error") == "INSUFFICIENT_COINS" for result in results)
    assert all(result.get("error") in {None, "INSUFFICIENT_COINS"} for result in results)
    wallet = h.get("/wallet")
    assert 0 <= wallet["available_points"] + wallet["held_points"] <= 150
    h.reconcile()


def test_parallel_http_quote_replay_and_same_key_changed_payload(h):
    h.fund(200)
    quote = h.post("/roster/quotes", {"operation": "monster_recruit", "target_id": "shadow_wolf"})
    bodies = parallel([lambda: http_call(h, "/roster/orders", {"quote_token": quote["quote_token"]}) for _ in range(8)])
    assert all(r.status_code == 200 for r in bodies), [r.text for r in bodies]
    assert len({r.json()["data"]["command_id"] for r in bodies}) == 1
    assert len(h.get("/roster")["monsters"]) == 2
    assert h.get("/wallet")["available_points"] == 50
    key, command_key = uid(), uid()
    conflicts = parallel([
        lambda points=points: http_call(h, "/system/adjustments", {"points": points, "reason": "SYNTHETIC 同键异载荷", "command_key": command_key}, key)
        for points in (10, 20)
    ])
    assert sorted(r.status_code for r in conflicts) == [200, 409]
    assert next(r for r in conflicts if r.status_code == 409).json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert h.get("/wallet")["available_points"] in {60, 70}
    h.reconcile()


def test_leisure_start_and_refund_have_only_one_winner(h):
    h.fund(120)
    reward = next(r for r in h.get("/rewards") if r["price_points"] == 120)
    quote = h.post("/rewards/quotes", {"operation": "leisure", "target_id": reward["id"]})
    ticket_id = h.post("/rewards/orders", {"quote_token": quote["quote_token"]})["entity_id"]
    results = parallel([
        lambda action=action: http_call(h, f"/leisure/{ticket_id}/{action}", {"expected_version": 1})
        for action in ("start", "cancel")
    ])
    assert sorted(r.status_code for r in results) == [200, 409], [r.text for r in results]
    ticket = h.get(f"/leisure/{ticket_id}")
    wallet = h.get("/wallet")
    assert wallet["held_points"] == 0
    assert (ticket["state"], wallet["available_points"]) in {("running", 0), ("cancelled", 120)}
    assert h.scalar("SELECT count(*) FROM ledger_entries WHERE origin_type='leisure' AND entry_type IN ('redemption_spend','redemption_refund')") == 1
    if ticket["state"] == "running":
        h.post(f"/leisure/{ticket_id}/cancel", {"expected_version": ticket["version"]}, status=409)
    h.reconcile()


def test_competing_leisure_starts_keep_unstarted_reservation(h):
    h.fund(400)
    reward = h.get("/rewards")[0]
    ticket_ids = []
    for _ in range(2):
        quote = h.post("/rewards/quotes", {"operation": "leisure", "target_id": reward["id"]})
        ticket_ids.append(h.post("/rewards/orders", {"quote_token": quote["quote_token"]})["entity_id"])
    results = parallel([lambda identity=identity: http_call(h, f"/leisure/{identity}/start", {"expected_version": 1}) for identity in ticket_ids])
    assert sorted(r.status_code for r in results) == [200, 409]
    assert {h.get(f"/leisure/{identity}")["state"] for identity in ticket_ids} == {"running", "reserved"}
    assert h.get("/wallet")["held_points"] == reward["price_points"]
    h.reconcile()


def test_concurrent_wager_accept_and_settlement_use_one_hold(h):
    h.fund(100)
    proposal = h.post("/system/wagers", {"stake_points": 100, "target_points": 5, "bonus_points": 800})
    accepted = parallel([lambda: http_call(h, f"/system/wagers/{proposal['id']}/accept", {"expected_version": 1, "terms_hash": proposal["terms_hash"]}) for _ in range(6)])
    assert all(r.status_code == 200 for r in accepted)
    h.clock.set("2026-10-10", "06:45")
    # Check-in records the qualifying award; parallel settle commands then race.
    h.post("/system/checkin")
    settled = parallel([lambda: http_call(h, f"/system/wagers/{proposal['id']}/settle", {}) for _ in range(6)])
    assert all(r.status_code == 200 for r in settled)
    assert {r.json()["data"]["state"] for r in settled} == {"won"}
    assert len({r.json()["data"]["settlement_ledger_id"] for r in settled}) == 1
    assert h.get("/wallet")["available_points"] == 905
    assert h.scalar("SELECT count(*) FROM ledger_entries WHERE origin_type='commitment'") == 2
    h.reconcile()


def test_concurrent_first_clear_is_one_atomic_award_and_occupation(h):
    team_version = h.get("/roster")["team"]["version"]
    battles = [h.post("/world/battles", {"outpost_id": "fern_gate", "team_version": team_version, "command_key": uid()}) for _ in range(4)]
    assert all(parallel([lambda: jobs.run_once(h.db, "SYNTHETIC concurrent worker") for _ in battles]))
    results = [h.get(f"/world/battles/{b['id']}")["result"] for b in battles]
    assert all(r["outcome"] == "won" for r in results)
    assert sum(r["first_clear"] for r in results) == 1
    assert sum(r["reward_points"] for r in results) == 10
    assert h.scalar("SELECT count(*) FROM occupations") == 1
    assert h.scalar("SELECT count(*) FROM game_events WHERE kind='outpost_occupied'") == 1
    assert h.scalar("SELECT count(*) FROM ledger_entries WHERE economic_kind='first_clear'") == 1
    h.reconcile()


def test_provider_concurrency_uses_live_request_leases_and_releases_finished_calls(h):
    config = {"role": "chat", "model": "SYNTHETIC no network", "base_url": "https://synthetic.invalid", "capabilities": {"daily_request_limit": 100}}
    with h.db.transaction(True, h.owner) as c:
        for _ in range(3):
            jobs.enqueue(c, "provider_test", uid(), {"provider": config})
    claimed = [jobs.claim_job(h.db, "SYNTHETIC request boundary") for _ in range(3)]

    def record(job):
        try:
            return {"id": jobs.record_external(h.db, job, config), "job": job}
        except DomainError as exc:
            return {"error": exc.code, "job": job}

    results = parallel([lambda job=job: record(job) for job in claimed])
    assert [r.get("error") for r in results].count("PROVIDER_BUSY") == 1
    assert h.scalar("SELECT count(*) FROM provider_calls") == 2
    completed = next(r for r in results if "id" in r)
    waiting = next(r for r in results if "error" in r)
    with h.db.transaction(True, h.owner) as c:
        assert c.get("jobs", waiting["job"]["id"])["external_request_started_at"] is None
        c.update("provider_calls", completed["id"], completed_at=c.now, state="completed")
    assert "id" in record(waiting["job"])


def test_real_write_lock_returns_retryable_error_without_consuming_request_key(h):
    body = {"points": 30, "reason": "SYNTHETIC 锁释放后原请求重试", "command_key": uid()}
    key = uid()
    # A separate sqlite3 connection holds the write lock beyond the API's real timeout.
    connection = sqlite3.connect(h.db.settings.database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        assert h.get("/wallet")["available_points"] == 0  # WAL readers still work.
        failed = http_call(h, "/system/adjustments", body, key)
        assert failed.status_code == 503, failed.text
        assert failed.json()["error"]["code"] == "DATABASE_BUSY"
        assert failed.json()["error"]["retryable"]
    finally:
        connection.rollback()
        connection.close()
    first = h.post("/system/adjustments", body, key=key)
    assert h.post("/system/adjustments", body, key=key) == first
    assert h.get("/wallet")["available_points"] == 30
    h.reconcile()
