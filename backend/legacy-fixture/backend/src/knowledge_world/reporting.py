from datetime import date, timedelta
from .common import require, public, iso, dumps, digest, local_ms, cursor_offset, next_cursor
from .plans import valid_date
from .library import ACTIVE_POINT_SQL


SUBJECT_CLAIMS_SQL = """SELECT cl.id FROM learning_claims cl
    JOIN knowledge_points p ON p.id=cl.point_id
    WHERE p.owner_id=:o AND p.subject_id=:sub"""


def account_ledger_days(c, start, end):
    # Coin scope is always the entire account, including subject-filtered views.
    return c.all(
        """SELECT l.business_date, sum(l.learning_delta) learning,
        sum(CASE WHEN l.available_delta+l.held_delta>0 THEN l.available_delta+l.held_delta ELSE 0 END) earned,
        sum(CASE WHEN l.entry_type IN ('purchase','redemption_spend') THEN -l.available_delta-l.held_delta ELSE 0 END) spent,
        sum(CASE WHEN l.entry_type IN ('habit_penalty','commitment_loss') THEN -l.available_delta-l.held_delta ELSE 0 END) penalized
        FROM ledger_entries l
        WHERE l.owner_id=:o AND l.business_date BETWEEN :start AND :end GROUP BY l.business_date""",
        {"o": c.owner, "start": start, "end": end},
    )


def date_range(c, start, end, selected=None):
    valid_date(start)
    valid_date(end)
    require(
        start <= end <= c.today and (date.fromisoformat(end) - date.fromisoformat(start)).days < 366,
        "INVALID_DATE",
        "查询范围须在今天及以前，跨度不超过 366 天",
        400,
    )
    if selected:
        require(start <= selected <= end, "INVALID_DATE", "所选日期不在范围内", 400)


def series(c, start, end, subject_id=None):
    date_range(c, start, end)
    if subject_id:
        c.get("subjects", subject_id)
    params = {"o": c.owner, "start": start, "end": end, "sub": subject_id}
    # Coins always cover the account. Resolve a subject's learning history once,
    # including the opening balance, rather than rebuilding its claim set twice.
    rows = account_ledger_days(c, start, end)
    mapping = {r["business_date"]: r for r in rows}
    if subject_id:
        for row in mapping.values():
            row["learning"] = 0
        learning_rows = c.all(
            f"""SELECT l.business_date, sum(l.learning_delta) learning
            FROM ledger_entries l
            WHERE l.owner_id=:o AND l.business_date<=:end
                AND l.claim_id IN ({SUBJECT_CLAIMS_SQL}) GROUP BY l.business_date""",
            params,
        )
        cumulative = 0
        for row in learning_rows:
            if row["business_date"] < start:
                cumulative += row["learning"]
            else:
                mapping[row["business_date"]]["learning"] = row["learning"]
    else:
        cumulative = c.scalar(
            """SELECT COALESCE(sum(learning_delta),0) FROM ledger_entries
            WHERE owner_id=:o AND business_date<:start""",
            params,
        )
    unlocked = {
        r["completion_business_date"]: r["n"]
        for r in c.all(
            "SELECT completion_business_date,count(*) n FROM study_tasks WHERE owner_id=:o AND task_kind!='group' AND completion_business_date BETWEEN :start AND :end GROUP BY completion_business_date",
            params,
        )
    }
    screens = {
        r["business_date"]: r["minutes"]
        for r in c.all(
            "SELECT business_date,minutes FROM screen_records s WHERE owner_id=:o AND business_date BETWEEN :start AND :end AND revision=(SELECT max(revision) FROM screen_records sr WHERE sr.owner_id=s.owner_id AND sr.business_date=s.business_date)",
            params,
        )
    }
    result = []
    day = date.fromisoformat(start)
    while day.isoformat() <= end:
        key = day.isoformat()
        row = mapping.get(key, {})
        net = row.get("learning", 0)
        cumulative += net
        result.append(
            {
                "date": key,
                "learning_points_net": net,
                "learning_points_cumulative": cumulative,
                "coins_earned": row.get("earned", 0),
                "coins_spent": row.get("spent", 0),
                "coins_penalized": row.get("penalized", 0),
                "unlocked_task_count": unlocked.get(key, 0),
                "screen_minutes": screens.get(key),
                "partial_day": key == c.today,
            }
        )
        day += timedelta(days=1)
    updated = c.scalar("SELECT max(created_at) FROM ledger_entries WHERE owner_id=:o", {"o": c.owner})
    return {
        "items": result,
        "timezone": c.tz,
        "coin_scope": "account",
        "task_scope": "plan",
        "learning_subject_id": subject_id,
        "data_updated_at": iso(updated),
    }


def summary(c, start, end, selected=None, subject_id=None):
    selected = selected or end
    date_range(c, start, end, selected)
    if subject_id:
        c.get("subjects", subject_id)
    params = {"o": c.owner, "day": selected, "sub": subject_id, "at": c.now}
    # The summary needs one day and its opening balance, not an entire curve.
    # A scalar aggregate avoids sorting all historical subject entries by day.
    scope = f" AND l.claim_id IN ({SUBJECT_CLAIMS_SQL})" if subject_id else ""
    learning = c.one(
        """SELECT COALESCE(sum(l.learning_delta),0) cumulative,
            COALESCE(sum(CASE WHEN l.business_date=:day THEN l.learning_delta ELSE 0 END),0) daily
        FROM ledger_entries l WHERE l.owner_id=:o AND l.business_date<=:day""" + scope,
        params,
    )
    coins = next(iter(account_ledger_days(c, selected, selected)), {})
    plan = c.one(
        """SELECT count(*) total, COALESCE(sum(t.completed_at IS NOT NULL),0) unlocked
        FROM study_tasks t JOIN daily_plans p ON p.id=t.plan_id
        WHERE t.owner_id=:o AND p.business_date=:day AND t.state!='archived' AND t.parent_id IS NULL""",
        params,
    )
    unlocked = c.scalar(
        "SELECT count(*) FROM study_tasks WHERE owner_id=:o AND task_kind!='group' AND completion_business_date=:day",
        params,
    )
    screen = c.scalar(
        "SELECT minutes FROM screen_records WHERE owner_id=:o AND business_date=:day ORDER BY revision DESC LIMIT 1",
        params,
    )
    due = c.scalar(
        f"SELECT count(*) FROM knowledge_points p WHERE p.owner_id=:o AND {ACTIVE_POINT_SQL} AND (:sub IS NULL OR p.subject_id=:sub) AND EXISTS (SELECT 1 FROM cards ca JOIN review_schedules s ON s.card_id=ca.id WHERE ca.point_id=p.id AND ca.state='active' AND s.due_at<=:at)",
        params,
    )
    updated = c.scalar("SELECT max(created_at) FROM ledger_entries WHERE owner_id=:o", params)
    return {
        "date": selected,
        "learning_points_net": learning["daily"],
        "learning_points_cumulative": learning["cumulative"],
        "coins_earned": coins.get("earned", 0),
        "coins_spent": coins.get("spent", 0),
        "coins_penalized": coins.get("penalized", 0),
        "unlocked_task_count": unlocked,
        "screen_minutes": screen,
        "partial_day": selected == c.today,
        "selected_date": selected,
        "plan_total": plan["total"],
        "plan_unlocked": plan["unlocked"],
        "plan_ratio": plan["unlocked"] / plan["total"] if plan["total"] else None,
        "due_points_now": due,
        "as_of": iso(c.now),
        "coin_scope": "account",
        "task_scope": "plan",
        "timezone": c.tz,
        "data_updated_at": iso(updated),
    }


def day_detail(c, day, subject_id=None, limit=100, cursor=None):
    date_range(c, day, day)
    require(1 <= limit <= 100, "INVALID_INPUT", "每页最多 100 条", 400)
    offset = cursor_offset(cursor)
    rows = c.all(
        """SELECT a.*,p.id point_id,p.title point_title,cl.task_id,t.title task_title,aw.current_points,ass.reasoning_summary,ass.verdict
        FROM activities a JOIN learning_claims cl ON cl.id=a.claim_id JOIN knowledge_points p ON p.id=cl.point_id
        LEFT JOIN study_tasks t ON t.id=cl.task_id LEFT JOIN learning_awards aw ON aw.claim_id=cl.id LEFT JOIN assessments ass ON ass.id=aw.current_assessment_id
        WHERE a.owner_id=:o AND a.business_date=:d AND (:sub IS NULL OR p.subject_id=:sub) ORDER BY a.submitted_at DESC,a.id LIMIT :n OFFSET :offset""",
        {"o": c.owner, "d": day, "sub": subject_id, "n": limit + 1, "offset": offset},
    )
    more = len(rows) > limit
    rows = rows[:limit]
    for row in rows:
        row["receipts"] = [
            public(r)
            for r in c.all(
                "SELECT * FROM ledger_entries WHERE claim_id=:id ORDER BY sequence", {"id": row["claim_id"]}
            )
        ]
        row["submitted_business_date"] = row["business_date"]
    return {
        "date": day,
        "items": [public(r) for r in rows],
        "timezone": c.tz,
        "next_cursor": next_cursor(offset + limit) if more else None,
    }


def archive(c, start, end, subject_id=None, timer_cursor=None):
    data = series(c, start, end, subject_id)
    params = {"o": c.owner, "start": start, "end": end, "sub": subject_id}
    points = c.all(
        f"SELECT p.id,p.title,m.current_stage,m.best_stage FROM knowledge_points p JOIN point_mastery m ON m.point_id=p.id WHERE p.owner_id=:o AND {ACTIVE_POINT_SQL} AND (:sub IS NULL OR p.subject_id=:sub) ORDER BY m.current_stage,p.title LIMIT 30",
        params,
    )
    attempts = c.one(
        """SELECT count(*) total,COALESCE(sum(a.correctness='correct' AND a.independent=1),0) passed FROM card_attempts a JOIN cards ca ON ca.id=a.card_id JOIN knowledge_points p ON p.id=ca.point_id
        WHERE a.owner_id=:o AND COALESCE(a.answer_business_date,date(a.answered_at/1000,'unixepoch')) BETWEEN :start AND :end AND (:sub IS NULL OR p.subject_id=:sub)""",
        {
            **params,
        },
    )
    reports = [
        public(r)
        for r in c.all(
            "SELECT * FROM study_reports WHERE owner_id=:o AND start_date>=:start AND end_date<=:end ORDER BY created_at DESC",
            params,
        )
    ]
    timers = c.all(
        "SELECT ts.* FROM timer_sessions ts LEFT JOIN study_tasks t ON t.id=ts.task_id LEFT JOIN knowledge_points p ON p.id=t.point_id WHERE ts.owner_id=:o AND ts.created_at BETWEEN :a AND :b AND (:sub IS NULL OR p.subject_id=:sub) ORDER BY ts.created_at DESC,ts.id LIMIT 101 OFFSET :offset",
        {
            **params,
            "a": local_ms(start, tz=c.tz),
            "b": local_ms(end, tz=c.tz, offset=1) - 1,
            "offset": cursor_offset(timer_cursor),
        },
    )
    return {
        **data,
        "weak_points": points,
        "review": attempts,
        "reports": reports,
        "timers": [public(r) for r in timers[:100]],
        "timer_next_cursor": next_cursor(cursor_offset(timer_cursor) + 100) if len(timers) > 100 else None,
    }


def report_input(c, start, end):
    data = archive(c, start, end)
    rows = c.all(
        "SELECT * FROM activities WHERE owner_id=:o AND business_date BETWEEN :start AND :end ORDER BY submitted_at",
        {"o": c.owner, "start": start, "end": end},
    )
    data.pop("reports")
    data.pop("data_updated_at", None)
    data["activities"] = [public(r) for r in rows]
    return data, digest(dumps(data))
