"""Server interval timing, reserved ownership and once-only leisure charges."""
from math import ceil
from .common import uid, public, dumps, require, check_version, iso
from .economy import append
from .game_events import emit, wallet_view


def catalog(c):
    return [public(r) for r in c.all("SELECT * FROM reward_catalog WHERE owner_id=:o AND enabled=1 ORDER BY created_at,id", {"o": c.owner})]


def edit_reward(c, data, identity=None):
    rules = c.rules()["leisure"]
    require(data.price_points <= rules["max_price_points"] and data.duration_minutes <= rules["max_duration_minutes"], "INVALID_INPUT", "奖励超过当前目录上限", 400)
    values = data.model_dump(exclude={"expected_version"})
    if identity:
        row = c.get("reward_catalog", identity)
        check_version(row, data.expected_version)
        c.update("reward_catalog", identity, **values, version=row["version"] + 1, updated_at=c.now)
    else:
        identity = uid()
        c.insert("reward_catalog", id=identity, owner_id=c.owner, code=f"custom:{identity}", **values, created_at=c.now, updated_at=c.now)
    c.change("rewards")
    return public(c.get("reward_catalog", identity))


def disable_reward(c, identity, expected_version=None):
    row = c.get("reward_catalog", identity)
    if expected_version is not None:
        check_version(row, expected_version)
    require(row["enabled"], "REWARD_DISABLED", "奖励已经删除", 409)
    c.update("reward_catalog", identity, enabled=0, version=row["version"] + 1, updated_at=c.now)
    c.change("rewards")
    return public(c.get("reward_catalog", identity))


def used_ms(c, row):
    total = c.scalar("SELECT COALESCE(sum(COALESCE(ended_at,:now)-started_at),0) FROM leisure_intervals WHERE ticket_id=:id", {"id": row["id"], "now": c.now})
    return min(row["duration_seconds"] * 1000, max(0, total))


def view(c, identity):
    row = c.get("leisure_tickets", identity)
    used = used_ms(c, row)
    state = "completed" if row["state"] == "running" and used == row["duration_seconds"] * 1000 else row["state"]
    return {**public(row), "state": state, "used_seconds": used // 1000,
        "remaining_seconds": ceil((row["duration_seconds"] * 1000 - used) / 1000), "server_time": iso(c.now),
        "ledger_entry_ids": [r["id"] for r in c.all("SELECT id FROM ledger_entries WHERE owner_id=:o AND origin_type='leisure' AND origin_id=:id ORDER BY sequence", {"o": c.owner, "id": identity})],
        "game_event_ids": [r["id"] for r in c.all("SELECT id FROM game_events WHERE owner_id=:o AND origin_type='leisure' AND origin_id=:id ORDER BY sequence", {"o": c.owner, "id": identity})]}


def reserve(c, command_id, terms):
    identity = uid()
    snapshot = terms["before"]
    price = terms["price"]
    c.insert("leisure_tickets", id=identity, owner_id=c.owner, catalog_id=snapshot["id"], snapshot_json=dumps(snapshot),
        rule_version=terms["rule_version"], price_points=price, duration_seconds=snapshot["duration_minutes"] * 60,
        quote_nonce=terms["nonce"], state="reserved", created_at=c.now, updated_at=c.now)
    entry = append(c, "redemption_hold", "shop", f"leisure:{identity}:hold", "leisure", identity,
        available=-price, held=price, economic_kind="leisure_hold", rule_version=terms["rule_version"],
        detail={"reason": snapshot["name"], "duration_minutes": snapshot["duration_minutes"]})
    after = view(c, identity)
    event = emit(c, f"leisure:{identity}:reserved", "leisure_reserved", "leisure", identity, before={}, after=after,
        ledger_ids=[entry["id"]] if entry else [], rule_version=terms["rule_version"], detail={"reason": snapshot["name"]})
    return {"command_id": command_id, "operation": "leisure", "entity_id": identity, "entity_version": 1,
        "price_points": price, "before": {}, "after": after, "ledger_entry_ids": [entry["id"]] if entry else [],
        "game_event_ids": [event["id"]], "wallet": wallet_view(c), "rule_version": terms["rule_version"]}


def finish_due(c, row):
    used = used_ms(c, row)
    if row["state"] != "running" or used < row["duration_seconds"] * 1000:
        return False
    # Close exactly at the entitlement boundary, even after a long offline period.
    closed = c.scalar("SELECT COALESCE(sum(ended_at-started_at),0) FROM leisure_intervals WHERE ticket_id=:id AND ended_at IS NOT NULL", {"id": row["id"]})
    end = row["running_since"] + row["duration_seconds"] * 1000 - closed
    c.execute("UPDATE leisure_intervals SET ended_at=:end WHERE ticket_id=:id AND ended_at IS NULL", {"end": end, "id": row["id"]})
    c.update("leisure_tickets", row["id"], state="completed", used_seconds=row["duration_seconds"], running_since=None, version=row["version"] + 1, updated_at=c.now)
    emit(c, f"leisure:{row['id']}:completed", "leisure_completed", "leisure", row["id"], before={"state": "running"}, after={"state": "completed", "remaining_seconds": 0}, rule_version=row["rule_version"], detail={"reason": "休息时光已结束，没有续费或额外扣分"})
    c.notify(f"leisure:{row['id']}:completed", "这段休息时光已结束", "可以慢慢收心。没有自动续费或额外扣分。", f"/leisure/{row['id']}")
    c.change("leisure", "rewards")
    return True


def catchup(c):
    for row in c.all("SELECT * FROM leisure_tickets WHERE owner_id=:o AND state='running'", {"o": c.owner}):
        finish_due(c, row)


def transition(c, identity, action, expected_version):
    require(action in {"start", "pause", "resume", "cancel"}, "INVALID_INPUT", "不支持的休闲操作", 400)
    row = c.get("leisure_tickets", identity)
    finish_due(c, row)
    row = c.get("leisure_tickets", identity)
    if (action in {"start", "resume"} and row["state"] == "running") or (action == "pause" and row["state"] in {"paused", "completed"}) or (action == "cancel" and row["state"] == "cancelled"):
        return view(c, identity)
    check_version(row, expected_version)
    before, entry = view(c, identity), None
    if action in {"start", "resume"}:
        require(row["state"] == ("reserved" if action == "start" else "paused"), "LEISURE_STATE", "此券当前无法开始或续用")
        catchup(c)
        count = c.scalar("SELECT count(*) FROM leisure_tickets WHERE owner_id=:o AND state='running'", {"o": c.owner})
        require(count < c.rules(row["rule_version"])["leisure"]["max_running_per_account"], "LEISURE_RUNNING", "已有正在使用的休闲券，请先暂停它")
        if action == "start":
            require(row["first_started_at"] is None, "LEISURE_STATE", "此券已经开始过")
            entry = append(c, "redemption_spend", "shop", f"leisure:{identity}:spend", "leisure", identity, held=-row["price_points"], economic_kind="leisure_spend", rule_version=row["rule_version"], detail={"reason": "首次开始休闲，消费本券预留积分"})
        # A pause/resume in the very same millisecond is one continuous interval.
        previous = c.one("SELECT * FROM leisure_intervals WHERE ticket_id=:id AND started_at=:now", {"id": identity, "now": c.now})
        if previous:
            c.update("leisure_intervals", previous["id"], ended_at=None)
        else:
            c.insert("leisure_intervals", id=uid(), ticket_id=identity, started_at=c.now)
        c.update("leisure_tickets", identity, state="running", first_started_at=row["first_started_at"] or c.now, running_since=c.now, version=row["version"] + 1, updated_at=c.now)
    elif action == "pause":
        require(row["state"] == "running", "LEISURE_STATE", "只有运行中的券可以暂停")
        used = used_ms(c, row)
        c.execute("UPDATE leisure_intervals SET ended_at=:at WHERE ticket_id=:id AND ended_at IS NULL", {"at": c.now, "id": identity})
        c.update("leisure_tickets", identity, state="paused", running_since=None, used_seconds=used // 1000, version=row["version"] + 1, updated_at=c.now)
    else:
        require(row["state"] == "reserved" and row["first_started_at"] is None, "LEISURE_ALREADY_USED", "只有从未开始的券可以全额退回")
        entry = append(c, "redemption_refund", "shop", f"leisure:{identity}:refund", "leisure", identity, available=row["price_points"], held=-row["price_points"], economic_kind="leisure_refund", rule_version=row["rule_version"], detail={"reason": "未开始的休闲券原价退回"})
        c.update("leisure_tickets", identity, state="cancelled", version=row["version"] + 1, updated_at=c.now)
    after = view(c, identity)
    emit(c, f"leisure:{identity}:v{after['version']}", "leisure_" + action, "leisure", identity, before=before, after=after,
        ledger_ids=[entry["id"]] if entry else [], rule_version=row["rule_version"], detail={"reason": {"start": "开始休闲", "pause": "暂停，保留余量", "resume": "继续休闲", "cancel": "未开始退回"}[action]})
    c.change("leisure", "rewards")
    return view(c, identity)
