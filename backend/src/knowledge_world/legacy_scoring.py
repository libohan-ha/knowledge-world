"""Pinned legacy scoring, only for accepted legacy contracts."""
from .common import require, public
from .economy import append

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
