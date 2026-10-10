from .common import uid, dumps, require, public


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
):
    previous = c.one(
        "SELECT * FROM ledger_entries WHERE owner_id=:o AND source_key=:k", {"o": c.owner, "k": source_key}
    )
    if previous:
        return previous
    if learning == available == held == 0:
        return None
    balances = wallet(c)
    require(
        balances["available_coins"] + available >= 0,
        "INSUFFICIENT_COINS",
        "可用奖励币不足",
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
        created_at=c.now,
    )
    c.change("wallet", "ledger", "monitor")
    return row


def raw_score(rules, template, difficulty="standard", breakthrough="none", steps=0):
    scoring = rules["scoring"]
    require(template in scoring["templates"], "INVALID_INPUT", "未知任务模板", 400)
    t = scoring["templates"][template]
    if template in {"scheduled_review", "flashcard"}:
        return t["base"], "micro_review"
    if template == "productive_attempt":
        return min(
            t["max"],
            t["base"]
            + min(steps, scoring["productive_progress_steps_max"])
            * scoring["productive_progress_step_points"],
        ), "productive_attempt"
    return min(
        t["max"],
        (t["base"] * scoring["difficulty_percent"][difficulty] + 50) // 100
        + scoring["breakthrough_bonus"][breakthrough],
    ), "deep_learning"


def capped_target(c, claim, category, raw, rules):
    cap_key = {
        "micro_review": "micro_review_daily_cap",
        "productive_attempt": "productive_attempt_daily_cap",
    }.get(category)
    if not cap_key:
        return raw
    peaks = c.all(
        """SELECT a.claim_id, max(a.target_points) peak FROM assessments a JOIN learning_claims cl ON cl.id=a.claim_id
        WHERE a.owner_id=:o AND cl.first_business_date=:d AND a.reward_category=:cat
        AND a.state IN ('accepted','superseded') GROUP BY a.claim_id""",
        {"o": c.owner, "d": claim["first_business_date"], "cat": category},
    )
    used = sum(row["peak"] for row in peaks)
    own = next((row["peak"] for row in peaks if row["claim_id"] == claim["id"]), 0)
    return min(raw, own + max(0, rules["scoring"][cap_key] - used))


def settle_learning(c, claim, assessment, raw, category):
    rules = c.rules(claim["rule_version"])
    previous = c.one("SELECT * FROM learning_awards WHERE claim_id=:id", {"id": claim["id"]})
    target = capped_target(c, claim, category, raw, rules)
    current, high = (previous["current_points"], previous["coin_high_water"]) if previous else (0, 0)
    coin_target = target * rules["scoring"]["coins_per_learning_point"]
    if previous:
        c.update("assessments", previous["current_assessment_id"], state="superseded")
    c.update("assessments", assessment["id"], target_points=target, state="accepted", accepted_at=c.now)
    receipt = append(
        c,
        "learning_correction" if previous else "learning_grant",
        category,
        f"learning:{claim['id']}:assessment:{assessment['revision']}",
        "activity",
        assessment["activity_id"],
        learning=target - current,
        available=max(0, coin_target - high),
        business_date=claim["first_business_date"],
        rule_version=claim["rule_version"],
        claim_id=claim["id"],
        assessment_id=assessment["id"],
        detail={
            "source_previous_points": current,
            "raw_target": raw,
            "target_points": target,
            "cap_reduction": raw - target,
            "coin_high_water_before": high,
            "template_code": claim["template_code"],
            "difficulty": assessment["difficulty"],
            "breakthrough": assessment["breakthrough"],
            "reason": assessment["reasoning_summary"],
            "compensation": "向下纠错保留已发奖励币" if target < current else None,
        },
    )
    values = dict(
        current_assessment_id=assessment["id"],
        current_points=target,
        coin_high_water=max(high, coin_target),
        updated_at=c.now,
    )
    if previous:
        c.update("learning_awards", claim["id"], key="claim_id", version=previous["version"] + 1, **values)
    else:
        c.insert("learning_awards", claim_id=claim["id"], **values)
    c.update("learning_claims", claim["id"], version=claim["version"] + 1)
    return public(receipt)


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
