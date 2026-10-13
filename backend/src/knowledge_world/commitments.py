import json
from datetime import datetime
from .common import uid, dumps, digest, require, check_version, public, local_ms
from .economy import append


def proposal(c, data):
    rules = c.rules()
    modern = "system" in rules
    if modern:
        require(c.scalar("SELECT enabled FROM skill_settings WHERE owner_id=:o AND skill='wager'", {"o": c.owner}), "SKILL_DISABLED", "对赌 Skill 已关闭，已有合约继续履行")
    limits = rules["wager"] if modern else rules["commitments"]
    stake = data.stake_points if modern else data.stake_coins
    bonus = data.bonus_points if modern else data.bonus_coins
    require(
        stake <= limits["max_stake_points" if modern else "max_stake_coins"]
        and bonus <= limits["max_success_bonus_points" if modern else "max_success_bonus_coins"],
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
        "stake_points": stake,
        "bonus_points": bonus,
        "deadline_at": deadline,
        "scope": limits["counting_scope"],
        "grace_hours": limits["pending_decision_grace_hours" if modern else "pending_assessment_grace_hours"],
        "eligible_credit_types": limits.get("eligible_credit_types", []),
        "timezone": c.tz,
        "missing_system_evidence_result": "void_and_refund",
    }
    same = c.one("""SELECT id FROM commitments WHERE owner_id=:o AND state='proposed' AND accepted_at IS NULL AND title=:t
        AND target_points=:target AND stake_coins=:s AND bonus_coins=:b AND deadline_at=:d AND terms_json=:terms AND rule_version=:v LIMIT 1""",
        {"o": c.owner, "t": data.title, "target": data.target_points, "s": stake, "b": bonus, "d": deadline, "terms": dumps(terms), "v": rules["version"]})
    if same:
        # Identical open terms are one proposal, never a second card.
        return detail(c, same["id"])
    row = c.insert(
        "commitments",
        id=uid(),
        owner_id=c.owner,
        title=data.title,
        target_points=data.target_points,
        stake_coins=stake,
        bonus_coins=bonus,
        terms_json=dumps(terms),
        rule_version=rules["version"],
        state="proposed",
        deadline_at=deadline,
        grace_deadline_at=deadline + terms["grace_hours"] * 3600000,
        timezone_snapshot=c.tz,
        created_at=c.now,
    )
    return detail(c, row["id"])


def progress(c, row):
    if row["accepted_at"] is None:
        return 0, 0
    if json.loads(row["terms_json"])["scope"] == "eligible_earned_points_after_acceptance":
        total, pending = 0, 0
        boundary = c.one("SELECT * FROM wager_acceptance_boundaries WHERE contract_id=:id", {"id": row["id"]})
        excluded = set(json.loads(boundary["same_instant_action_ids_json"])) if boundary else set()
        for action in c.all("SELECT * FROM system_actions WHERE owner_id=:o AND first_submitted_at>=:start AND first_submitted_at<:end",
            {"o": c.owner, "start": row["accepted_at"], "end": row["deadline_at"]}):
            if action["id"] in excluded:
                continue
            decision = c.one("SELECT approved_points FROM system_decisions WHERE action_id=:id AND state='applied' AND evidence_cutoff_at<:end ORDER BY action_version DESC LIMIT 1", {"id": action["id"], "end": row["deadline_at"]})
            if decision:
                total += max(0, min(decision["approved_points"], action["net_points"]))
            pending += int(action["state"] in {"submitted", "failed", "needs_review", "needs_configuration"})
        total += c.scalar("SELECT COALESCE(sum(l.available_delta),0) FROM habit_occurrences h JOIN habit_plans p ON p.id=h.plan_id JOIN ledger_entries l ON l.id=h.settlement_ledger_id WHERE h.owner_id=:o AND p.kind='checkin' AND h.state='completed' AND h.completed_at>=:start AND h.completed_at<:end AND l.available_delta>0 AND l.sequence>:cutoff",
            {"o": c.owner, "start": row["accepted_at"], "end": row["deadline_at"], "cutoff": boundary["ledger_sequence"] if boundary else 0})
        return total, pending
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
    if row["settlement_ledger_id"]:
        settlement = c.get("ledger_entries", row["settlement_ledger_id"])
        amount, pending = json.loads(settlement["detail_json"]).get("progress_points", amount), 0
    return {
        **public(row),
        "terms_hash": digest(row["terms_json"]),
        "progress_points": amount,
        "pending_assessments": pending,
        "stake_points": row["stake_coins"],
        "bonus_points": row["bonus_coins"],
        "legacy_compatibility": json.loads(row["terms_json"])["scope"] != "eligible_earned_points_after_acceptance",
        "ledger_entry_ids": [r["id"] for r in c.all("SELECT id FROM ledger_entries WHERE owner_id=:o AND origin_type='commitment' AND origin_id=:id ORDER BY sequence", {"o": c.owner, "id": identity})],
        "game_event_ids": [r["id"] for r in c.all("SELECT id FROM game_events WHERE owner_id=:o AND origin_type='commitment' AND origin_id=:id ORDER BY sequence", {"o": c.owner, "id": identity})],
    }


def accept(c, identity, data):
    row = c.get("commitments", identity)
    if row["accepted_at"] is not None:
        require(data.terms_hash == digest(row["terms_json"]), "TERMS_CHANGED", "条款已变化")
        return detail(c, identity)
    if "system" in c.rules():
        require(c.scalar("SELECT enabled FROM skill_settings WHERE owner_id=:o AND skill='wager'", {"o": c.owner}), "SKILL_DISABLED", "对赌 Skill 已关闭，已有合约继续履行")
        require(row["rule_version"] == c.rules()["version"], "TERMS_CHANGED", "新规则已生效，请重新获取提案")
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
    held_receipt = append(
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
    if json.loads(row["terms_json"])["scope"] == "eligible_earned_points_after_acceptance":
        c.insert("wager_acceptance_boundaries", contract_id=identity, ledger_sequence=held_receipt["sequence"],
            same_instant_action_ids_json=dumps([r["id"] for r in c.all("SELECT id FROM system_actions WHERE owner_id=:o AND first_submitted_at=:now", {"o": c.owner, "now": c.now})]))
    c.update(
        "commitments",
        identity,
        state="active",
        accepted_at=c.now,
        accepted_business_date=c.today,
        version=row["version"] + 1,
    )
    from .game_events import emit
    held_entry = c.scalar("SELECT id FROM ledger_entries WHERE owner_id=:o AND source_key=:k", {"o": c.owner, "k": f"commitment:{identity}:hold"})
    emit(c, f"wager:{identity}:hold", "wager_accepted", "commitment", identity,
        before={"state": "proposed"}, after={"state": "active", "held_points": row["stake_coins"]}, ledger_ids=[held_entry],
        rule_version=row["rule_version"], detail={"reason": row["title"], "stake_points": row["stake_coins"], "bonus_points": row["bonus_coins"]})
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
        if pending and not terminal and row["state"] != "pending_settlement":
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
                "returned_stake_points": row["stake_coins"] if terminal in {"won", "voided"} else 0,
                "extra_bonus_points": row["bonus_coins"] if terminal == "won" else 0,
                "spent_stake_points": row["stake_coins"] if terminal == "lost" else 0,
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
            "对赌合约已结算",
            {
                "won": "达成目标，押金和奖金已到账",
                "lost": "本次未达成，已按条款消费冻结押金",
                "voided": "系统异常，押金已退回",
            }[terminal],
            f"/system?wager={identity}",
        )
        from .game_events import emit
        emit(c, f"wager:{identity}:settlement", "wager_" + terminal, "commitment", identity,
            before={"state": row["state"]}, after={"state": terminal, "progress_points": points}, ledger_ids=[receipt["id"]],
            rule_version=row["rule_version"], detail={"reason": row["title"], "returned_stake_points": row["stake_coins"] if terminal != "lost" else 0,
                "extra_bonus_points": row["bonus_coins"] if terminal == "won" else 0, "spent_stake_points": row["stake_coins"] if terminal == "lost" else 0})
    return detail(c, identity)


def evaluate_all(c):
    for row in c.all(
        "SELECT id FROM commitments WHERE owner_id=:o AND state IN ('active','pending_settlement')",
        {"o": c.owner},
    ):
        evaluate(c, row["id"])
