import json
from datetime import date, timedelta
from .common import uid, dumps, require, check_version, public, local_ms, next_day, iso, day_at
from .economy import append, wallet
from .plans import valid_date


def resolved_terms(c, kind, given, rules=None):
    rules = rules or c.rules()
    values = given.model_dump(exclude_none=True) if hasattr(given, "model_dump") else dict(given)
    defaults = {
        "penalty_enabled": False,
        "penalty_coins": rules["habits"]["default_miss_penalty_coins"],
        "reward_coins": rules["habits"]["default_daily_reward_coins"],
        "condition": "完成当天约定",
    }
    if kind == "screen_time":
        defaults.update(
            limit_minutes=rules["screen_time"]["default_limit_minutes"],
            scope=rules["screen_time"]["default_scope"],
            reward_coins=rules["screen_time"]["success_reward_coins"],
            penalty_coins=rules["screen_time"]["default_failure_penalty_coins"],
        )
    if kind == "checkin":
        defaults.update(
            reward_coins=rules["checkin"]["base_coins"],
            penalty_coins=rules["checkin"]["default_miss_penalty_coins"],
        )
    return {**defaults, **values, "kind": kind}


def create_plan(c, data):
    if data.kind in {"checkin", "screen_time"}:
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
    if plan["kind"] in {"checkin", "screen_time"} and not existing:
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
    if kind == "screen_time":
        return local_ms(
            row["business_date"],
            rules["screen_time"]["record_deadline_next_day"],
            row["timezone_snapshot"],
            1,
        )
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
    rules = c.rules(row["rule_version"])
    deadline = occurrence_deadline(c, row)
    require(terms["kind"] != "screen_time" or c.now >= deadline, message="屏幕时间需在次日截止后结算")
    require(row["state"] in {"completed", "rest"} or c.now >= deadline, message="习惯尚未到结算时间")
    state = row["state"]
    amount, record_id, detail = 0, None, {"kind": terms["kind"], "terms": terms, "deadline": iso(deadline)}
    if state != "rest" and terms["kind"] == "screen_time":
        record = c.one(
            "SELECT * FROM screen_records WHERE occurrence_id=:id AND confirmed_at<:deadline ORDER BY revision DESC LIMIT 1",
            {"id": identity, "deadline": deadline},
        )
        if record:
            record_id = record["id"]
            state = "completed" if record["minutes"] <= terms["limit_minutes"] else "missed"
            detail["record"] = public(record)
        else:
            state = "unknown"
    elif state == "due":
        state = "missed"
    if state == "completed":
        amount = terms["reward_coins"]
        if terms["kind"] == "checkin":
            streak = checkin_streak(c, row["business_date"])
            amount = min(
                rules["checkin"]["max_daily_coins"],
                rules["checkin"]["base_coins"] + (streak - 1) * rules["checkin"]["streak_increment_coins"],
            )
            detail["streak"] = streak
    elif state == "missed" and terms["penalty_enabled"]:
        used = c.scalar(
            "SELECT COALESCE(-sum(available_delta),0) FROM ledger_entries WHERE owner_id=:o AND business_date=:d AND entry_type='habit_penalty'",
            {"o": c.owner, "d": row["business_date"]},
        )
        amount = -min(
            terms["penalty_coins"],
            wallet(c)["available_coins"],
            max(0, rules["habits"]["max_total_daily_penalty_coins"] - used),
        )
        detail["undeducted"] = terms["penalty_coins"] + amount
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
    return c.get("habit_occurrences", identity)


def checkin_streak(c, day):
    rows = c.all(
        "SELECT o.business_date,o.state FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind='checkin' AND o.business_date<=:d ORDER BY o.business_date DESC",
        {"o": c.owner, "d": day},
    )
    count, cursor = 0, date.fromisoformat(day)
    for row in rows:
        if row["business_date"] != cursor.isoformat() or row["state"] not in {"completed", "rest"}:
            break
        if row["state"] == "completed":
            count += 1
        cursor -= timedelta(days=1)
    return max(count, 1)


def screen_view(c, day):
    row = special_occurrence(c, "screen_time", day)
    records = c.all(
        "SELECT * FROM screen_records WHERE owner_id=:o AND business_date=:d ORDER BY revision DESC",
        {"o": c.owner, "d": day},
    )
    latest = records[0] if records else None
    terms = json.loads(row["terms_snapshot_json"])
    projected = (
        0
        if latest is None
        else terms["reward_coins"]
        if latest["minutes"] <= terms["limit_minutes"]
        else -terms["penalty_coins"]
        if terms["penalty_enabled"]
        else 0
    )
    return {
        "source": "manual",
        "date": day,
        "minutes": latest["minutes"] if latest else None,
        "scope": terms["scope"],
        "note": latest["note"] if latest else "",
        "record_revision": latest["revision"] if latest else 0,
        "record_deadline": iso(occurrence_deadline(c, row)),
        "projected_coins": projected,
        "settlement_state": "settled" if row["settled_at"] else "pending",
        "settled_receipt_id": row["settlement_ledger_id"],
        "occurrence": public(row),
        "revisions": [public(r) for r in records],
    }


def record_screen(c, day, data):
    valid_date(day)
    require(day <= c.today, "INVALID_DATE", "不能记录未来的使用时间", 400)
    row = special_occurrence(c, "screen_time", day)
    latest = c.scalar(
        "SELECT COALESCE(max(revision),0) FROM screen_records WHERE owner_id=:o AND business_date=:d",
        {"o": c.owner, "d": day},
    )
    require(data.expected_revision == latest, "VERSION_CONFLICT", "屏幕记录已更新", current_version=latest)
    terms = json.loads(row["terms_snapshot_json"])
    require(data.scope == terms["scope"], "INVALID_SCOPE", "请使用当日条款约定的统计口径", 400)
    if c.now >= occurrence_deadline(c, row) and row["settled_at"] is None:
        row = settle(c, row["id"])
    c.insert(
        "screen_records",
        id=uid(),
        owner_id=c.owner,
        occurrence_id=row["id"],
        business_date=day,
        revision=latest + 1,
        scope=data.scope,
        minutes=data.minutes,
        note=data.note,
        confirmed_at=c.now,
        after_settlement=int(row["settled_at"] is not None),
    )
    c.change("monitor")
    return screen_view(c, day)


def checkin(c):
    from .review import create_attempt, attempt_view

    row = special_occurrence(c, "checkin", c.today)
    terms = json.loads(row["terms_snapshot_json"])
    rules = c.rules(row["rule_version"])["checkin"]
    start = local_ms(row["business_date"], rules["window_start"], row["timezone_snapshot"])
    end = local_ms(row["business_date"], rules["window_end_exclusive"], row["timezone_snapshot"])
    detail = json.loads(row["settlement_detail_json"])
    if not detail.get("checkin_at") or (start <= c.now < end and not start <= detail["checkin_at"] < end):
        detail["checkin_at"] = c.now
        c.update("habit_occurrences", row["id"], settlement_detail_json=dumps(detail))
    eligible = start <= c.now < end and row["state"] not in {"rest", "missed"} and row["settled_at"] is None
    if not row["startup_attempt_id"] and eligible:
        card = c.one(
            "SELECT ca.id FROM cards ca JOIN knowledge_points p ON p.id=ca.point_id WHERE ca.owner_id=:o AND ca.state='active' AND ca.is_verification=0 AND p.archived_at IS NULL ORDER BY ca.created_at LIMIT 1",
            {"o": c.owner},
        )
        if card:
            attempt = create_attempt(c, card["id"], "startup")
            c.update(
                "habit_occurrences", row["id"], startup_attempt_id=attempt["id"], version=row["version"] + 1
            )
    row = c.get("habit_occurrences", row["id"])
    return {
        "occurrence": public(row),
        "eligible": eligible,
        "window": f"{rules['window_start']}—{rules['window_end_exclusive']}",
        "attempt": attempt_view(c, row["startup_attempt_id"]) if row["startup_attempt_id"] else None,
        "message": "完成启动题即可签到，答错也没关系"
        if eligible
        else "已记录今天来过；早起奖励只在签到窗口内发放",
        "terms": terms,
    }


def complete_checkin(c, identity, data):
    row = c.get("habit_occurrences", identity)
    if row["state"] == "completed":
        return public(row)
    check_version(row, data.expected_version)
    terms = json.loads(row["terms_snapshot_json"])
    require(
        terms["kind"] == "checkin"
        and row["startup_attempt_id"] == data.startup_attempt_id
        and row["state"] != "rest",
        message="启动题与签到不匹配",
    )
    attempt = c.get("card_attempts", data.startup_attempt_id)
    checkin_at = json.loads(row["settlement_detail_json"]).get("checkin_at", 0)
    rules = c.rules(row["rule_version"])["checkin"]
    start, end = (
        local_ms(row["business_date"], rules["window_start"], row["timezone_snapshot"]),
        occurrence_deadline(c, row),
    )
    require(
        attempt["answered_at"] is not None
        and start <= attempt["answered_at"] < end
        and start <= checkin_at < end
        and c.now < end,
        "CHECKIN_WINDOW_CLOSED",
        "签到操作及启动题需要在窗口内完成",
    )
    # A timezone change cannot mint a second early checkin inside 20 real hours.
    recent = c.scalar(
        "SELECT count(*) FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND p.kind='checkin' AND o.id!=:id AND o.state='completed' AND o.completed_at>:cut",
        {"o": c.owner, "id": identity, "cut": c.now - 20 * 3600000},
    )
    require(not recent, "ALREADY_SETTLED", "同一真实日期已领取签到奖励")
    c.update("habit_occurrences", identity, state="completed", completed_at=c.now)
    return public(settle(c, identity))


def complete_custom(c, identity, data):
    row = c.get("habit_occurrences", identity)
    if row["state"] == "completed":
        return public(row)
    check_version(row, data.expected_version)
    terms = json.loads(row["terms_snapshot_json"])
    require(
        terms["kind"] == "custom"
        and row["state"] == "due"
        and row["business_date"] == c.today
        and c.now < occurrence_deadline(c, row),
        message="只能完成当天有效的自报习惯",
    )
    c.update(
        "habit_occurrences",
        identity,
        state="completed",
        completed_at=c.now,
        settlement_detail_json=dumps({"note": data.note}),
    )
    return public(settle(c, identity))


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
    plans = c.all("SELECT * FROM habit_plans WHERE owner_id=:o ORDER BY created_at", {"o": c.owner})
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
        "SELECT * FROM habit_occurrences WHERE owner_id=:o AND settled_at IS NULL", {"o": c.owner}
    )
    pending.sort(key=lambda row: (row["business_date"], occurrence_deadline(c, row), row["id"]))
    for row in pending:
        if c.now >= occurrence_deadline(c, row):
            settle(c, row["id"])


def habits_view(c, day):
    valid_date(day)
    plans = c.all(
        "SELECT * FROM habit_plans WHERE owner_id=:o AND archived_at IS NULL ORDER BY created_at",
        {"o": c.owner},
    )
    for plan in plans:
        if day <= c.today:
            ensure_occurrence(c, plan, day)
    occurrences = c.all(
        "SELECT o.*,p.title,p.kind FROM habit_occurrences o JOIN habit_plans p ON p.id=o.plan_id WHERE o.owner_id=:o AND o.business_date=:d ORDER BY p.created_at",
        {"o": c.owner, "d": day},
    )
    return {
        "date": day,
        "plans": [plan_view(c, p["id"]) for p in plans],
        "occurrences": [{**public(row), "deadline": iso(occurrence_deadline(c, row))} for row in occurrences],
    }
