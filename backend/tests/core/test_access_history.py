"""Ownership and stable pagination with synthetic identities in a real WAL DB."""
import json
import time
from pathlib import Path
from urllib.parse import urlencode

from knowledge_world import core_rules, game_events, identity
from knowledge_world.common import uid
from test_core_behavior import accept, buy, judge


def test_private_game_resources_require_login_and_match_owner(h):
    h.fund(100)
    thread = h.post("/system/threads", {"title": "SYNTHETIC private thread", "context": {}})
    action = judge(h, 30)
    wager = accept(h, h.post("/system/wagers", {"stake_points": 10, "target_points": 50, "bonus_points": 20}))
    ticket, _ = buy(h, "leisure", h.get("/rewards")[0]["id"])
    roster = h.get("/roster")
    home = h.get("/world/home")
    combat = h.post("/world/battles", {"outpost_id": "fern_gate", "team_version": roster["team"]["version"], "command_key": uid()})
    h.drain()
    backup = h.post("/backups")
    first_page = h.get("/world/history?limit=1")
    protected = [
        f"/system/threads/{thread['id']}", f"/system/actions/{action['action_id']}",
        f"/system/wagers/{wager['id']}", f"/leisure/{ticket['entity_id']}",
        f"/world/battles/{combat['id']}", f"/jobs/{combat['job_id']}",
        f"/ledger/{action['ledger_id']}", f"/ledger/{action['ledger_id']}/source",
        f"/backups/{backup['backup_id']}/file",
    ]
    h.client.cookies.clear()
    for path in [*protected, "/world/history", "/world/events", "/roster", "/backups"]:
        h.request("GET", path, status=401)
    with h.db.transaction(True, h.owner) as c:
        original = c.profile
        other = uid()
        c.insert("profiles", id=other, display_name="SYNTHETIC other owner", password_hash=original["password_hash"], timezone="Asia/Shanghai", created_at=c.now, updated_at=c.now)
        c.insert("wallets", owner_id=other, updated_at=c.now)
        c.owner = other
        core_rules.initialize_account(c)
        token, csrf = identity.create_session(c, other)
    h.client.cookies.set("kw_session", token)
    h.client.cookies.set("kw_csrf", csrf)
    for path in protected:
        h.request("GET", path, status=404)
    h.post("/roster/quotes", {"operation": "monster_train", "target_id": roster["monsters"][0]["id"]}, status=404)
    other_team = h.get("/roster")
    h.request("PUT", "/roster/team", {"expected_version": other_team["team"]["version"], "member_ids": [other_team["hero"]["id"], roster["monsters"][0]["id"]]}, status=404)
    h.request("PUT", f"/world/home/placements/{home['items'][0]['id']}", {"expected_version": home["items"][0]["version"], "x": 5, "z": 5, "rotation": 0}, status=404)
    h.post(f"/leisure/{ticket['entity_id']}/start", {"expected_version": 1}, status=404)
    h.post(f"/system/wagers/{wager['id']}/settle", status=404)
    h.request("GET", "/world/history?" + urlencode({"limit": 1, "cursor": first_page["next_cursor"]}), status=400)
    assert h.get("/system/wagers")["items"] == []
    assert h.get("/leisure") == []
    assert h.get("/backups")["items"] == []
    assert len(h.get("/world/history")["items"]) == 1  # Own opening event only.


def test_history_fifty_thousand_events_stable_dates_cursor_and_restore(h):
    """Measure the first production HTTP query, then prove full-page coverage."""
    total = 50_000
    with h.db.transaction(True, h.owner) as c:
        version = c.rules()["version"]
        # Bulk fixture rows avoid spending this performance test on 50k writes.
        c.s.connection().exec_driver_sql(
            "INSERT INTO game_events (id,owner_id,source_key,kind,object_id,origin_type,origin_id,before_json,after_json,receipt_json,rule_version,business_date,timezone_snapshot,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(f"synthetic-event-{i}", h.owner, f"synthetic:{i}", "home_placed", "synthetic-object", "home_item", "synthetic-object", '{"x":0}', '{"x":1}', '{}', version,
              "2026-10-01" if i < total // 2 else "2026-10-10", "Asia/Shanghai", c.now) for i in range(total)],
        )
    start = time.perf_counter()
    page = h.get("/world/history?start_date=2026-04-11&end_date=2026-10-10&limit=100")
    first_ms = (time.perf_counter() - start) * 1000
    assert page["coverage"]["total_events"] == total + 1  # Opening event.
    upper = page["upper_sequence"]
    with h.db.transaction(True, h.owner) as c:
        later = game_events.emit(c, "synthetic:late", "home_placed", "home_item", "synthetic-late", before={}, after={})
    original_cursor = page["next_cursor"]
    seen = [row["id"] for row in page["items"]]
    timings = []
    while page["next_cursor"]:
        start = time.perf_counter()
        page = h.get("/world/history?" + urlencode({"start_date": "2026-04-11", "end_date": "2026-10-10", "limit": 100, "cursor": page["next_cursor"]}))
        timings.append((time.perf_counter() - start) * 1000)
        assert page["upper_sequence"] == upper
        seen.extend(row["id"] for row in page["items"])
    assert len(seen) == len(set(seen)) == total + 1
    assert later["id"] not in seen and page["coverage"]["complete"]
    assert h.get("/world/history?start_date=2026-10-01&end_date=2026-10-01")["coverage"]["total_events"] == total // 2
    h.request("GET", "/world/history?" + urlencode({"start_date": "2026-10-01", "end_date": "2026-10-10", "cursor": original_cursor}), status=400)
    with h.db.transaction(True, h.owner) as c:
        c.execute("UPDATE world_history_state SET epoch=:epoch WHERE id=1", {"epoch": uid()})
    h.request("GET", "/world/history?" + urlencode({"start_date": "2026-04-11", "end_date": "2026-10-10", "cursor": original_cursor}), status=409)
    artifact = Path(__file__).resolve().parents[3] / "artifacts/refactor/history-performance.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps({"synthetic": True, "events": total, "first_http_query_ms": first_ms, "page_count": len(timings) + 1,
        "subsequent_page_p95_ms": sorted(timings)[int(len(timings) * .95)], "duplicate_or_missing": False,
        "scope": "server HTTP including serialization, not browser rendering or mobile hardware"}, indent=2), encoding="utf-8")
