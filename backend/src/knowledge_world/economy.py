from .common import uid, dumps, require


def penalties_used(c, business_date):
    return c.scalar(
        "SELECT COALESCE(sum(COALESCE(json_extract(detail_json,'$.penalty_applied'), -MIN(available_delta,0))),0) "
        "FROM ledger_entries WHERE owner_id=:o AND business_date=:d AND (economic_kind IN ('system_penalty','checkin_penalty') OR (economic_kind='' AND entry_type='habit_penalty'))",
        {"o": c.owner, "d": business_date},
    )


def wallet(c):
    return c.get("wallets", c.owner, key="owner_id")


def append(
    c,
    entry_type,
    category,
    source_key,
    origin_type,
    origin_id,
    *,
    learning=0,
    available=0,
    held=0,
    business_date=None,
    rule_version=None,
    claim_id=None,
    assessment_id=None,
    detail=None,
    economic_kind=None,
    correction_of=None,
):
    previous = c.one(
        "SELECT * FROM ledger_entries WHERE owner_id=:o AND source_key=:k", {"o": c.owner, "k": source_key}
    )
    if previous:
        require((previous["learning_delta"], previous["available_delta"], previous["held_delta"]) == (learning, available, held),
            "SOURCE_CONFLICT", "同一经济来源不能以不同金额再次结算")
        return previous
    if learning == available == held == 0:
        return None
    balances = wallet(c)
    require(
        balances["available_coins"] + available >= 0,
        "INSUFFICIENT_COINS",
        "可用积分不足",
        required=-available,
        available=balances["available_coins"],
        held=balances["held_coins"],
    )
    require(
        balances["held_coins"] + held >= 0 and balances["learning_points"] + learning >= 0,
        "BALANCE_INVARIANT",
        "结算余额核对失败",
    )
    # No public endpoint accepts these deltas. Only domain settlement commands call this function.
    row = c.insert(
        "ledger_entries",
        id=uid(),
        owner_id=c.owner,
        entry_type=entry_type,
        category=category,
        source_key=source_key,
        origin_type=origin_type,
        origin_id=origin_id,
        claim_id=claim_id,
        assessment_id=assessment_id,
        learning_delta=learning,
        available_delta=available,
        held_delta=held,
        business_date=business_date or c.today,
        rule_version=rule_version or c.rules()["version"],
        detail_json=dumps(detail or {}),
        economic_kind=economic_kind or entry_type,
        correction_of=correction_of,
        created_at=c.now,
    )
    c.change("wallet", "ledger", "system")
    return c.get("ledger_entries", row["id"])


def reconcile(c):
    mismatches = []
    for row in c.all(
        "SELECT w.*, COALESCE(sum(l.learning_delta),0) lp,COALESCE(sum(l.available_delta),0) ac,COALESCE(sum(l.held_delta),0) hc FROM wallets w LEFT JOIN ledger_entries l ON l.owner_id=w.owner_id GROUP BY w.owner_id"
    ):
        if (row["learning_points"], row["available_coins"], row["held_coins"]) != (
            row["lp"],
            row["ac"],
            row["hc"],
        ):
            mismatches.append({"kind": "wallet", "owner_id": row["owner_id"]})
        expected = c.scalar(
            "SELECT COALESCE(sum(stake_coins),0) FROM commitments WHERE owner_id=:o AND state IN ('active','pending_settlement')",
            {"o": row["owner_id"]},
        )
        expected += c.scalar(
            "SELECT COALESCE(sum(price_coins),0) FROM redemptions WHERE owner_id=:o AND state IN ('reserved','running','needs_review')",
            {"o": row["owner_id"]},
        )
        if c.scalar("SELECT 1 FROM sqlite_master WHERE type='table' AND name='leisure_tickets'"):
            expected += c.scalar(
                "SELECT COALESCE(sum(price_points),0) FROM leisure_tickets WHERE owner_id=:o AND state='reserved'",
                {"o": row["owner_id"]},
            )
        if row["held_coins"] != expected:
            mismatches.append({"kind": "reservations", "expected": expected, "actual": row["held_coins"]})
    for row in c.all(
        "SELECT a.claim_id,a.current_points, COALESCE(sum(l.learning_delta),0) net FROM learning_awards a LEFT JOIN ledger_entries l ON l.claim_id=a.claim_id GROUP BY a.claim_id"
    ):
        if row["current_points"] != row["net"]:
            mismatches.append({"kind": "claim", **row})
    return {
        "ok": not mismatches,
        "differences": mismatches,
        "integrity": c.scalar("PRAGMA integrity_check"),
        "foreign_keys": c.all("PRAGMA foreign_key_check"),
    }
