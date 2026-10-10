import json
from datetime import date, timedelta
from .common import uid, dumps, require, check_version, public, local_ms, next_day, iso, day_at
from .economy import append, wallet, penalties_used
from .common import valid_date


def resolved_terms(c, kind, given, rules=None):
    rules = rules or c.rules()
    values = given.model_dump(exclude_none=True) if hasattr(given, "model_dump") else dict(given)
    if "system" in rules:
        require(kind == "checkin", "PRODUCT_RETIRED", "独立习惯和屏幕时间已退出产品", 410)
        check = rules["checkin"]
        return {"penalty_enabled": check["penalty_enabled_by_default"], "penalty_coins": check["default_miss_penalty_points"],
            "reward_coins": check["base_points"], "condition": "在早起窗口内签到", **values, "kind": "checkin"}
    defaults = {
        "penalty_enabled": False,
        "penalty_coins": rules["habits"]["default_miss_penalty_coins"],
        "reward_coins": rules["habits"]["default_daily_reward_coins"],
        "condition": "完成当天约定",
    }
    if kind == "checkin":
        defaults.update(
            reward_coins=rules["checkin"]["base_coins"],
            penalty_coins=rules["checkin"]["default_miss_penalty_coins"],
        )
    return {**defaults, **values, "kind": kind}


def create_plan(c, data):
    require(data.kind == "checkin", "PRODUCT_RETIRED", "只保留签到计划", 410)
    if data.kind == "checkin":
        require(
            not c.scalar(
                "SELECT count(*) FROM habit_plans WHERE owner_id=:o AND kind=:k AND archived_at IS NULL",
                {"o": c.owner, "k": data.kind},
            ),
            "HABIT_EXISTS",
            "此类习惯计划已经存在",
        )
    row = c.insert(
        "habit_plans",
        id=uid(),
        owner_id=c.owner,
        kind=data.kind,
        title=data.title,
        effective_from=c.today,
        created_at=c.now,
        updated_at=c.now,
    )
    terms = resolved_terms(c, data.kind, data.terms)
    today_terms = {**terms, "penalty_enabled": False}
    c.insert(
        "habit_plan_revisions",
        plan_id=row["id"],
        revision=1,
        effective_from=c.today,
        weekdays_json=dumps(sorted(set(data.weekdays))),
        terms_json=dumps(today_terms),
        rule_version=c.rules()["version"],
        created_at=c.now,
    )
    if terms["penalty_enabled"]:
        c.insert(
            "habit_plan_revisions",
            plan_id=row["id"],
            revision=2,
            effective_from=next_day(c.today),
            weekdays_json=dumps(sorted(set(data.weekdays))),
            terms_json=dumps(terms),
            rule_version=c.rules()["version"],
            created_at=c.now,
        )
    ensure_occurrence(c, c.get("habit_plans", row["id"]), c.today)
    return plan_view(c, row["id"])


def plan_view(c, identity):
    row = c.get("habit_plans", identity)
    return {
        **public(row),
        "revisions": [
            public(r)
            for r in c.all(
                "SELECT * FROM habit_plan_revisions WHERE plan_id=:id ORDER BY revision", {"id": identity}
            )
        ],
        "rest_days": [
            r["business_date"]
            for r in c.all(
                "SELECT business_date FROM habit_rest_days WHERE plan_id=:id ORDER BY business_date",
                {"id": identity},
            )
        ],
    }


def revise(c, identity, data):
    row = c.get("habit_plans", identity)
    check_version(row, data.expected_version)
    require(row["archived_at"] is None, message="计划已归档")
    last = c.one(
        "SELECT * FROM habit_plan_revisions WHERE plan_id=:id ORDER BY revision DESC LIMIT 1",
        {"id": identity},
    )
    terms = resolved_terms(c, row["kind"], data.terms) if data.terms else json.loads(last["terms_json"])
    c.insert(
        "habit_plan_revisions",
        plan_id=identity,
        revision=last["revision"] + 1,
        effective_from=next_day(c.today),
        weekdays_json=dumps(sorted(set(data.weekdays)))
        if data.weekdays is not None
        else last["weekdays_json"],
        terms_json=dumps(terms),
        rule_version=c.rules()["version"],
        created_at=c.now,
    )
    c.update("habit_plans", identity, version=row["version"] + 1, updated_at=c.now)
    return plan_view(c, identity)


def ensure_occurrence(c, plan, day):
    from .identity import timezone_for_day

    timezone = timezone_for_day(c, day)
    valid_date(day)
    require(day <= c.today, "INVALID_DATE", "未来日期尚未开始", 400)
    existing = c.one(
        "SELECT * FROM habit_occurrences WHERE plan_id=:p AND business_date=:d", {"p": plan["id"], "d": day}
    )
    if plan["kind"] == "checkin" and not existing:
        existing = c.one(
            "SELECT o.* FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind=:k AND o.business_date=:d ORDER BY p.created_at LIMIT 1",
            {"o": c.owner, "k": plan["kind"], "d": day},
        )
    if existing:
        return existing
    revision = c.one(
        "SELECT * FROM habit_plan_revisions WHERE plan_id=:id AND effective_from<=:d ORDER BY revision DESC LIMIT 1",
        {"id": plan["id"], "d": day},
    )
    if (
        not revision
        or day < plan["effective_from"]
        or (plan["archived_at"] and day > day_at(plan["archived_at"], c.tz))
    ):
        return None
    terms = json.loads(revision["terms_json"])
    rest = date.fromisoformat(day).weekday() not in json.loads(revision["weekdays_json"])
    rest = rest or bool(
        c.scalar(
            "SELECT count(*) FROM habit_rest_days WHERE plan_id=:p AND business_date=:d AND declared_at<:start",
            {"p": plan["id"], "d": day, "start": local_ms(day, tz=timezone)},
        )
    )
    identity = uid()
    c.insert(
        "habit_occurrences",
        id=identity,
        owner_id=c.owner,
        plan_id=plan["id"],
        business_date=day,
        timezone_snapshot=timezone,
        terms_snapshot_json=dumps({**terms, "revision": revision["revision"]}),
        rule_version=revision["rule_version"],
        state="rest" if rest else "due",
    )
    return c.get("habit_occurrences", identity)


def special_occurrence(c, kind, day):
    existing = c.one(
        "SELECT o.* FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind=:k AND o.business_date=:d ORDER BY p.created_at LIMIT 1",
        {"o": c.owner, "k": kind, "d": day},
    )
    if existing:
        return existing
    plan = c.one(
        "SELECT * FROM habit_plans WHERE owner_id=:o AND kind=:k AND archived_at IS NULL",
        {"o": c.owner, "k": kind},
    )
    require(plan is not None, "RESOURCE_NOT_FOUND", "请先创建对应习惯计划", 404)
    row = ensure_occurrence(c, plan, day)
    require(row is not None, "INVALID_DATE", "当日尚未建立此计划", 400)
    return row


def occurrence_deadline(c, row):
    rules = c.rules(row["rule_version"])
    kind = json.loads(row["terms_snapshot_json"])["kind"]
    if kind == "checkin":
        return local_ms(
            row["business_date"], rules["checkin"]["window_end_exclusive"], row["timezone_snapshot"]
        )
    return local_ms(row["business_date"], tz=row["timezone_snapshot"], offset=1)


def settle(c, identity):
    row = c.get("habit_occurrences", identity)
    if row["settled_at"] is not None:
        return row
    terms = json.loads(row["terms_snapshot_json"])
    require(terms["kind"] == "checkin", "PRODUCT_RETIRED", "仅保留签到结算；退出功能不再补扣奖励或罚分", 410)
    rules = c.rules(row["rule_version"])
    deadline = occurrence_deadline(c, row)
    require(row["state"] in {"completed", "rest"} or c.now >= deadline, message="习惯尚未到结算时间")
    state = row["state"]
    amount, record_id, detail = 0, None, {**json.loads(row["settlement_detail_json"]), "kind": terms["kind"], "terms": terms, "deadline": iso(deadline)}
    if state == "due":
        from .availability import covered
        start = local_ms(row["business_date"], rules["checkin"]["window_start"], row["timezone_snapshot"])
        available = covered(c, start, deadline)
        state = "missed" if available else "unknown"
        detail["service_window_observed"] = available
        if not available:
            detail["reason"] = "签到窗口缺少连续服务可用性证据，不判罚并保留连签"
    if state == "completed":
        amount = terms["reward_coins"]
        if terms["kind"] == "checkin":
            streak = checkin_streak(c, row["business_date"])
            check = rules["checkin"]
            amount = min(check.get("max_daily_points", check.get("max_daily_coins")),
                check.get("base_points", check.get("base_coins")) + (streak - 1) * check.get("streak_increment_points", check.get("streak_increment_coins")))
            detail["streak"] = streak
    elif state == "missed" and terms["penalty_enabled"]:
        used = penalties_used(c, row["business_date"])
        amount = -min(
            terms["penalty_coins"],
            wallet(c)["available_coins"],
            max(0, (rules["system"]["daily_penalty_cap"] if "system" in rules else rules["habits"]["max_total_daily_penalty_coins"]) - used),
        )
        detail["undeducted"] = terms["penalty_coins"] + amount
        detail["penalty_applied"] = -amount
    detail["result"] = state
    receipt = append(
        c,
        "habit_reward" if amount > 0 else "habit_penalty",
        "habit",
        f"habit:{identity}:settlement",
        "habit_occurrence",
        identity,
        available=amount,
        business_date=row["business_date"],
        rule_version=row["rule_version"],
        detail=detail,
        economic_kind="checkin_reward" if amount > 0 else "checkin_penalty",
    )
    c.update(
        "habit_occurrences",
        identity,
        state=state,
        settled_at=c.now,
        screen_record_id=record_id,
        settlement_ledger_id=receipt["id"] if receipt else None,
        settlement_detail_json=dumps(detail),
        version=row["version"] + 1,
    )
    from .game_events import emit
    emit(c, f"checkin:{identity}:settlement", "checkin_reward" if amount > 0 else "checkin_penalty" if amount < 0 else "checkin_record",
        "habit_occurrence", identity, before={"state": row["state"]}, after={"state": state, "points": amount, "streak": detail.get("streak", 0)},
        ledger_ids=[receipt["id"]] if receipt else [], rule_version=row["rule_version"], business_date=row["business_date"], timezone=row["timezone_snapshot"],
        detail={"reason": "早起签到" if amount > 0 else "已启用的签到条款" if amount < 0 else "签到日期记录", "points": amount})
    c.change("checkin", "system")
    return c.get("habit_occurrences", identity)


def checkin_streak(c, day):
    rows = c.all(
        "SELECT o.business_date,o.state FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind='checkin' AND o.business_date<=:d ORDER BY o.business_date DESC",
        {"o": c.owner, "d": day},
    )
    count, cursor = 0, date.fromisoformat(day)
    for row in rows:
        if row["business_date"] != cursor.isoformat():
            break
        if row["business_date"] == day and row["state"] == "due":
            cursor -= timedelta(days=1)
            continue
        if row["state"] not in {"completed", "rest", "unknown"}:
            break
        if row["state"] == "completed":
            count += 1
        cursor -= timedelta(days=1)
    return count






def checkin(c):
    daily_catchup(c)
    row = special_occurrence(c, "checkin", c.today)
    rules = c.rules(row["rule_version"])["checkin"]
    start = local_ms(row["business_date"], rules["window_start"], row["timezone_snapshot"])
    end = local_ms(row["business_date"], rules["window_end_exclusive"], row["timezone_snapshot"])
    if row["state"] == "completed":
        return checkin_status(c)
    require(start <= c.now < end and row["state"] == "due" and row["settled_at"] is None, "CHECKIN_WINDOW_CLOSED", "签到需在当日有效早起窗口内完成")
    recent = c.scalar("SELECT count(*) FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind='checkin' AND o.id!=:id AND o.state='completed' AND o.completed_at>:cut",
        {"o": c.owner, "id": row["id"], "cut": c.now - rules.get("min_real_hours_between_rewards", 20) * 3600000})
    require(not recent, "ALREADY_SETTLED", "距离上次签到尚不足规定的真实时间间隔")
    detail = {**json.loads(row["settlement_detail_json"]), "checkin_at": c.now,
        "startup_requirement_waived_by": "system-core-2026-10-10.2"}
    c.update("habit_occurrences", row["id"], state="completed", completed_at=c.now, settlement_detail_json=dumps(detail))
    settle(c, row["id"])
    from .commitments import evaluate_all
    evaluate_all(c)
    return checkin_status(c)


def checkin_status(c):
    daily_catchup(c)
    row = special_occurrence(c, "checkin", c.today)
    rules = c.rules(row["rule_version"])["checkin"]
    start = local_ms(row["business_date"], rules["window_start"], row["timezone_snapshot"])
    end = occurrence_deadline(c, row)
    recent = c.scalar("SELECT count(*) FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind='checkin' AND o.id!=:id AND o.state='completed' AND o.completed_at>:cut",
        {"o": c.owner, "id": row["id"], "cut": c.now - rules.get("min_real_hours_between_rewards", 20) * 3600000})
    entry = c.one("SELECT available_delta FROM ledger_entries WHERE id=:id", {"id": row["settlement_ledger_id"]})
    return {"occurrence": public(row), "eligible": start <= c.now < end and row["state"] == "due" and not bool(recent),
        "window": f"{rules['window_start']}—{rules['window_end_exclusive']}", "terms": json.loads(row["terms_snapshot_json"]),
        "message": "今日已签到" if row["state"] == "completed" else "今天是预设休息日" if row["state"] == "rest" else "在早起窗口和世界打个招呼，无需学习题。",
        "streak": checkin_streak(c, c.today), "awarded_points": entry["available_delta"] if entry else 0,
        "ledger_entry_ids": [row["settlement_ledger_id"]] if row["settlement_ledger_id"] else [],
        "game_event_ids": [r["id"] for r in c.all("SELECT id FROM game_events WHERE owner_id=:o AND source_key=:k", {"o": c.owner, "k": f"checkin:{row['id']}:settlement"})],
        "server_time": iso(c.now)}






def rest_day(c, identity, day, remove=False):
    valid_date(day)
    c.get("habit_plans", identity)
    require(day > c.today, "INVALID_DATE", "休息日必须在目标日开始前设置", 400)
    if remove:
        c.execute(
            "DELETE FROM habit_rest_days WHERE plan_id=:id AND business_date=:d", {"id": identity, "d": day}
        )
    else:
        c.execute(
            "INSERT OR IGNORE INTO habit_rest_days(plan_id,business_date,declared_at) VALUES (:id,:d,:at)",
            {"id": identity, "d": day, "at": c.now},
        )
    return plan_view(c, identity)


def daily_catchup(c):
    # Retained scheduler: it must never materialize retired screen/review branches.
    plans = c.all("SELECT * FROM habit_plans WHERE owner_id=:o AND kind='checkin' ORDER BY created_at", {"o": c.owner})
    for plan in plans:
        # Find the first missing day once; settled history is not rescanned every 30 seconds.
        latest = plan["materialized_through"]
        start = (
            date.fromisoformat(latest) + timedelta(days=1)
            if latest
            else date.fromisoformat(plan["effective_from"])
        )
        last = date.fromisoformat(c.today)
        if plan["archived_at"]:
            last = min(last, date.fromisoformat(day_at(plan["archived_at"], c.tz)))
        while start <= last:
            ensure_occurrence(c, plan, start.isoformat())
            start += timedelta(days=1)
        if not latest or latest < last.isoformat():
            c.update("habit_plans", plan["id"], materialized_through=last.isoformat())
    pending = c.all(
        "SELECT o.* FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind='checkin' AND o.settled_at IS NULL", {"o": c.owner}
    )
    pending.sort(key=lambda row: (row["business_date"], occurrence_deadline(c, row), row["id"]))
    for row in pending:
        if c.now >= occurrence_deadline(c, row):
            settle(c, row["id"])
