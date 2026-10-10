import json
from datetime import datetime
from .common import uid, dumps, digest, require, check_version, public, local_ms
from .economy import append


def proposal(c, data):
    rules = c.rules()
    limits = rules["commitments"]
    require(
        data.stake_coins <= limits["max_stake_coins"]
        and data.bonus_coins <= limits["max_success_bonus_coins"],
        "INVALID_INPUT",
        "押金或奖金超过规则上限",
        400,
    )
    if data.deadline_at:
        try:
            stamp = datetime.fromisoformat(data.deadline_at)
            require(stamp.tzinfo is not None, "INVALID_INPUT", "截止时间需带时区", 400)
            deadline = int(stamp.timestamp() * 1000)
        except ValueError:
            require(False, "INVALID_INPUT", "截止时间无效", 400)
    else:
        deadline = local_ms(c.today, tz=c.tz, offset=1)
    require(c.now < deadline <= c.now + 30 * 86400000, "INVALID_INPUT", "截止时间须在未来 30 天内", 400)
    terms = {
        "target_points": data.target_points,
        "stake_coins": data.stake_coins,
        "bonus_coins": data.bonus_coins,
        "deadline_at": deadline,
        "scope": limits["counting_scope"],
        "grace_hours": limits["pending_assessment_grace_hours"],
    }
    row = c.insert(
        "commitments",
        id=uid(),
        owner_id=c.owner,
        title=data.title,
        target_points=data.target_points,
        stake_coins=data.stake_coins,
        bonus_coins=data.bonus_coins,
        terms_json=dumps(terms),
        rule_version=rules["version"],
        state="proposed",
        deadline_at=deadline,
        grace_deadline_at=deadline + limits["pending_assessment_grace_hours"] * 3600000,
        timezone_snapshot=c.tz,
        created_at=c.now,
    )
    return detail(c, row["id"])


def progress(c, row):
    if row["accepted_at"] is None:
        return 0, 0
    claims = c.all(
        "SELECT cl.*,aw.current_points FROM learning_claims cl LEFT JOIN learning_awards aw ON aw.claim_id=cl.id WHERE cl.owner_id=:o AND cl.first_submitted_at>=:start AND cl.first_submitted_at<:end",
        {"o": c.owner, "start": row["accepted_at"], "end": row["deadline_at"]},
    )
    total = 0
    pending = 0
    for claim in claims:
        assessment = c.one(
            "SELECT target_points FROM assessments WHERE claim_id=:id AND state IN ('accepted','superseded') AND evidence_cutoff_at<:end ORDER BY revision DESC LIMIT 1",
            {"id": claim["id"], "end": row["deadline_at"]},
        )
        if assessment:
            total += min(assessment["target_points"], claim["current_points"] or 0)
        pending += c.scalar(
            "SELECT count(*) FROM activities WHERE claim_id=:id AND submitted_at<:end AND state IN ('submitted','assessing','failed','needs_review')",
            {"id": claim["id"], "end": row["deadline_at"]},
        )
    return total, pending


def detail(c, identity):
    row = c.get("commitments", identity)
    amount, pending = progress(c, row)
    return {
        **public(row),
        "terms_hash": digest(row["terms_json"]),
        "progress_points": amount,
        "pending_assessments": pending,
    }


def accept(c, identity, data):
    row = c.get("commitments", identity)
    if row["accepted_at"] is not None:
        require(data.terms_hash == digest(row["terms_json"]), "TERMS_CHANGED", "条款已变化")
        return detail(c, identity)
    check_version(row, data.expected_version)
    require(row["state"] == "proposed" and row["deadline_at"] > c.now, "TERMS_CHANGED", "提案已失效")
    require(data.terms_hash == digest(row["terms_json"]), "TERMS_CHANGED", "请重新阅读当前条款")
    require(
        not c.scalar(
            "SELECT count(*) FROM commitments WHERE owner_id=:o AND state IN ('active','pending_settlement')",
            {"o": c.owner},
        ),
        "ACTIVE_COMMITMENT_EXISTS",
        "已有进行中的承诺",
    )
    require(
        not c.scalar(
            "SELECT count(*) FROM commitments WHERE owner_id=:o AND accepted_business_date=:d",
            {"o": c.owner, "d": c.today},
        ),
        "DAILY_LIMIT_REACHED",
        "今天已接受过一项承诺",
    )
    append(
        c,
        "commitment_hold",
        "commitment",
        f"commitment:{identity}:hold",
        "commitment",
        identity,
        available=-row["stake_coins"],
        held=row["stake_coins"],
        rule_version=row["rule_version"],
        detail=json.loads(row["terms_json"]),
    )
    c.update(
        "commitments",
        identity,
        state="active",
        accepted_at=c.now,
        accepted_business_date=c.today,
        version=row["version"] + 1,
    )
    return detail(c, identity)


def evaluate(c, identity, abandon=False):
    row = c.get("commitments", identity)
    if row["state"] not in {"active", "pending_settlement"}:
        return detail(c, identity)
    points, pending = progress(c, row)
    terminal = None
    if abandon:
        terminal = "lost"
    elif points >= row["target_points"]:
        terminal = "won"
    elif c.now >= row["deadline_at"]:
        terminal = "voided" if pending and c.now >= row["grace_deadline_at"] else None if pending else "lost"
        if pending and not terminal:
            c.update("commitments", identity, state="pending_settlement", version=row["version"] + 1)
    if terminal:
        available = (
            row["stake_coins"] + row["bonus_coins"]
            if terminal == "won"
            else row["stake_coins"]
            if terminal == "voided"
            else 0
        )
        receipt = append(
            c,
            {"won": "commitment_win", "lost": "commitment_loss", "voided": "commitment_refund"}[terminal],
            "commitment",
            f"commitment:{identity}:settlement",
            "commitment",
            identity,
            available=available,
            held=-row["stake_coins"],
            rule_version=row["rule_version"],
            detail={
                "progress_points": points,
                "target_points": row["target_points"],
                "reason": "主动放弃"
                if abandon
                else "系统评估未能在宽限内恢复，退还押金"
                if terminal == "voided"
                else terminal,
            },
        )
        c.update(
            "commitments",
            identity,
            state=terminal,
            settled_at=c.now,
            settlement_ledger_id=receipt["id"],
            version=row["version"] + 1,
        )
        c.notify(
            f"commitment:{identity}:settlement",
            "学习承诺已结算",
            {
                "won": "达成目标，押金和奖金已到账",
                "lost": "本次未达成，已按条款消费冻结押金",
                "voided": "系统异常，押金已退回",
            }[terminal],
            "/commitments",
        )
    return detail(c, identity)


def evaluate_all(c):
    for row in c.all(
        "SELECT id FROM commitments WHERE owner_id=:o AND state IN ('active','pending_settlement')",
        {"o": c.owner},
    ):
        evaluate(c, row["id"])
