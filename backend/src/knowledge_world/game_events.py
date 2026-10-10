"""Append-only game presentation data. Display never performs settlement."""
from itsdangerous import BadSignature
from .common import uid, dumps, public, require, valid_date, DomainError
from .economy import wallet
from .signing import signer


def wallet_view(c):
    row = wallet(c)
    return {"available_points": row["available_coins"], "held_points": row["held_coins"], "version": row["version"]}


def emit(c, source_key, kind, origin_type, origin_id, *, before=None, after=None,
         ledger_ids=None, object_id=None, region_id=None, rule_version=None, detail=None,
         created_at=None, business_date=None, timezone=None):
    existing = c.one("SELECT * FROM game_events WHERE owner_id=:o AND source_key=:k", {"o": c.owner, "k": source_key})
    if existing:
        return public(existing)
    identity = uid()
    receipt = {"command_id": origin_id, "ledger_entry_ids": ledger_ids or [], "game_event_ids": [identity],
               "wallet": wallet_view(c), **(detail or {})}
    c.insert("game_events", id=identity, owner_id=c.owner, source_key=source_key, kind=kind,
        object_id=object_id or origin_id, region_id=region_id, origin_type=origin_type, origin_id=origin_id,
        before_json=dumps(before) if before is not None else None, after_json=dumps(after) if after is not None else None,
        receipt_json=dumps(receipt), rule_version=rule_version or c.rules()["version"],
        business_date=business_date or c.today, timezone_snapshot=timezone or c.tz, created_at=created_at if created_at is not None else c.now)
    c.change("game_events", "home", "system", "roster", "world_map")
    return public(c.get("game_events", identity))


def history(c, *, start_date=None, end_date=None, kind=None, cursor=None, limit=30):
    require(1 <= limit <= 100, "INVALID_INPUT", "每页最多 100 条", 400)
    if start_date:
        valid_date(start_date)
    if end_date:
        valid_date(end_date)
    require(not (start_date and end_date) or start_date <= end_date, "INVALID_DATE", "日期范围无效", 400)
    epoch = c.scalar("SELECT epoch FROM world_history_state WHERE id=1")
    filters = {"start": start_date, "end": end_date, "kind": kind}
    upper = c.scalar("SELECT COALESCE(max(sequence),0) FROM game_events WHERE owner_id=:o", {"o": c.owner})
    after = 0
    if cursor:
        try:
            token = signer(c.db.settings).loads(cursor)
        except BadSignature:
            raise DomainError("INVALID_CURSOR", "历史游标无效", 400)
        require(token.get("kind") == "game_history" and token.get("owner") == c.owner,
                "INVALID_CURSOR", "历史游标不属于当前账户", 400)
        require(token.get("epoch") == epoch, "HISTORY_RESET", "数据已恢复，请重新读取历史")
        require(token.get("filters") == filters, "INVALID_CURSOR", "查询范围已变化", 400)
        after, upper = token["after"], token["upper"]
    where = "owner_id=:o AND sequence<=:upper"
    params = {"o": c.owner, "upper": upper, "after": after, "n": limit + 1}
    for value, sql, key in [(start_date, "business_date>=:start", "start"),
                             (end_date, "business_date<=:end", "end"), (kind, "kind=:kind", "kind")]:
        if value:
            where += " AND " + sql
            params[key] = value
    rows = c.all(f"SELECT * FROM game_events WHERE {where} AND sequence>:after ORDER BY sequence LIMIT :n", params)
    total = c.scalar(f"SELECT count(*) FROM game_events WHERE {where}", params)
    next_cursor = None
    if len(rows) > limit:
        next_cursor = signer(c.db.settings).dumps({"kind": "game_history", "owner": c.owner, "epoch": epoch,
            "filters": filters, "upper": upper, "after": rows[limit - 1]["sequence"]})
    return {"items": [public(r) for r in rows[:limit]], "next_cursor": next_cursor, "upper_sequence": upper,
            "display_epoch": epoch, "coverage": {"start_date": start_date, "end_date": end_date,
                "total_events": total, "complete": next_cursor is None, "legacy_before_state_may_be_missing": True}}
