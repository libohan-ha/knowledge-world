import json
import math
from .common import uid, dumps, require, check_version, public, day_at
from .models import ActivityCreate


def create_attempt(c, card_id, kind="review", activity_id=None):
    card = c.get("cards", card_id)
    from .library import point_active

    require(
        point_active(c, c.get("knowledge_points", card["point_id"])), message="知识点或其所属学科、章节已归档"
    )
    require(card["state"] == "active", message="题卡已停用")
    schedule = c.one("SELECT * FROM review_schedules WHERE card_id=:id", {"id": card_id})
    attempt = c.insert(
        "card_attempts",
        id=uid(),
        owner_id=c.owner,
        card_id=card_id,
        activity_id=activity_id,
        occurrence_kind=kind,
        opportunity_key=schedule["opportunity_key"] if schedule else uid(),
        schedule_generation=schedule["generation"] if schedule else None,
        question_version=card["version"],
        frozen_question_json=card["question_json"],
        frozen_answer_json=card["answer_json"],
        grading_state="unanswered",
        explanation_md=card["explanation_md"],
        created_at=c.now,
    )
    return c.get("card_attempts", attempt["id"])


def attempt_view(c, identity):
    row = c.get("card_attempts", identity)
    card = c.get("cards", row["card_id"])
    result = {
        "id": row["id"],
        "card_id": row["card_id"],
        "point_id": card["point_id"],
        "question": json.loads(row["frozen_question_json"]),
        "card_type": card["card_type"],
        "grading_state": row["grading_state"],
        "correctness": row["correctness"],
        "independent": bool(row["independent"]),
        "rating": row["rating"],
        "version": row["version"],
        "revealed": row["revealed_at"] is not None,
        "occurrence_kind": row["occurrence_kind"],
        "activity_id": row["activity_id"],
    }
    if row["answered_at"] is not None:
        result["submitted_answer"] = json.loads(row["answer_json"])
    if row["revealed_at"] is not None or row["grading_state"] == "graded":
        result["answer"] = json.loads(row["frozen_answer_json"])
        result["explanation"] = row["explanation_md"]
    event = c.one("SELECT after_json FROM review_events WHERE attempt_id=:id", {"id": identity})
    if event:
        result["schedule_at_submission"] = json.loads(event["after_json"])
        result["schedule"] = public(c.get("review_schedules", row["card_id"], key="card_id"))
        result["schedule_corrected"] = bool(
            c.scalar("SELECT count(*) FROM review_corrections WHERE card_id=:id", {"id": row["card_id"]})
        )
    result["gradings"] = [
        public(r)
        for r in c.all(
            "SELECT * FROM attempt_gradings WHERE attempt_id=:id ORDER BY revision DESC", {"id": identity}
        )
    ]
    active = c.one(
        "SELECT id,state FROM jobs WHERE kind='grade' AND json_extract(payload_json,'$.attempt_id')=:id ORDER BY created_at DESC,id DESC LIMIT 1",
        {"id": identity},
    )
    if active:
        result["job_id"], result["job_state"] = active["id"], active["state"]
    return result


def start_round(c, data):
    if data.subject_id:
        c.get("subjects", data.subject_id)
    active = c.one(
        "SELECT * FROM review_rounds WHERE owner_id=:o AND state='active' AND filters_json=:f ORDER BY created_at DESC LIMIT 1",
        {"o": c.owner, "f": dumps(data.model_dump())},
    )
    if active:
        return round_view(c, active["id"])
    rules = c.rules()["review"]
    rows = c.all(
        """SELECT ca.id,s.generation FROM cards ca JOIN knowledge_points p ON p.id=ca.point_id JOIN subjects su ON su.id=p.subject_id JOIN review_schedules s ON s.card_id=ca.id
        WHERE ca.owner_id=:o AND ca.state='active' AND ca.is_verification=0 AND p.archived_at IS NULL AND su.archived_at IS NULL
        AND (p.chapter_id IS NULL OR p.chapter_id IN (SELECT id FROM chapters WHERE archived_at IS NULL))
        AND s.due_at<=:at AND (:sub IS NULL OR p.subject_id=:sub) ORDER BY (s.generation>1) DESC,s.due_at,ca.id LIMIT :limit""",
        {"o": c.owner, "at": c.now, "sub": data.subject_id, "limit": rules["round_size"] * 4},
    )
    new_count, selected = 0, []
    for row in rows:
        if row["generation"] == 1:
            if not data.include_new or new_count >= rules["new_cards_per_round_max"]:
                continue
            new_count += 1
        selected.append(row)
        if len(selected) == rules["round_size"]:
            break
    row = c.insert(
        "review_rounds",
        id=uid(),
        owner_id=c.owner,
        filters_json=dumps(data.model_dump()),
        state="active" if selected else "completed",
        created_at=c.now,
        completed_at=None if selected else c.now,
    )
    for i, card in enumerate(selected):
        attempt = create_attempt(c, card["id"])
        c.insert("review_round_items", round_id=row["id"], ordinal=i, attempt_id=attempt["id"])
    return round_view(c, row["id"])


def round_view(c, identity):
    row = c.get("review_rounds", identity)
    items = c.all(
        "SELECT ri.*,a.correctness,a.independent,a.grading_state,a.rating FROM review_round_items ri JOIN card_attempts a ON a.id=ri.attempt_id WHERE ri.round_id=:id ORDER BY ri.ordinal",
        {"id": identity},
    )
    current = next((x for x in items if x["ordinal"] == row["current_ordinal"]), None)
    return {
        **public(row),
        "items": items,
        "total": len(items),
        "correct_count": sum(x["correctness"] == "correct" and bool(x["independent"]) for x in items),
        "current_attempt": attempt_view(c, current["attempt_id"])
        if current and row["state"] == "active"
        else None,
    }


def reveal(c, identity, version):
    row = c.get("card_attempts", identity)
    if row["revealed_at"] is None:
        check_version(row, version)
        c.update("card_attempts", identity, revealed_at=c.now, version=row["version"] + 1)
    return attempt_view(c, identity)


def check_schedule(c, attempt):
    schedule = c.one("SELECT * FROM review_schedules WHERE card_id=:id", {"id": attempt["card_id"]})
    if schedule:
        require(
            schedule["generation"] == attempt["schedule_generation"],
            "STALE_REVIEW_SCHEDULE",
            "这张卡已在另一个页面完成，请刷新",
        )
    return schedule


def deterministic_grade(card_type, answer, expected):
    if card_type in {"single_choice", "multiple_choice"}:
        actual = answer if isinstance(answer, list) else [answer]
        correct = expected["correct"] if isinstance(expected["correct"], list) else [expected["correct"]]
        return set(actual) == set(correct)
    if card_type == "cloze":
        if not isinstance(answer, str):
            return False

        def normalize(value):
            return " ".join((value if expected.get("case_sensitive") else value.casefold()).strip().split())

        return normalize(answer) in {normalize(x) for x in expected["accepted"]}
    return None


def answer(c, identity, data):
    row = c.get("card_attempts", identity)
    if row["answered_at"] is not None:
        require(json.loads(row["answer_json"]) == data.answer, "ANSWER_ALREADY_SUBMITTED", "答案已经提交")
        return attempt_view(c, identity)
    check_version(row, data.expected_version)
    check_schedule(c, row)
    card = c.get("cards", row["card_id"])
    require(
        card["state"] == "active" and card["version"] == row["question_version"],
        "TERMS_CHANGED",
        "题目已修订，请重新获取题卡",
    )
    correct = deterministic_grade(card["card_type"], data.answer, json.loads(row["frozen_answer_json"]))
    c.update(
        "card_attempts",
        identity,
        answer_json=dumps(data.answer),
        answered_at=c.now,
        answer_business_date=c.today,
        answer_timezone=c.tz,
        requested_rating=data.rating,
        independent=int(row["revealed_at"] is None),
        grading_state="pending" if correct is None else "graded",
        correctness=None if correct is None else "correct" if correct else "incorrect",
        version=row["version"] + 1,
    )
    if correct is None:
        from .providers import provider_for
        from .jobs import enqueue

        try:
            provider = provider_for(c, "chat")
        except Exception as exc:
            from .common import DomainError

            if not isinstance(exc, DomainError):
                raise
            c.update("card_attempts", identity, grading_state="needs_review", correctness="uncertain")
            return {**attempt_view(c, identity), "message": "回答已保存，配置 AI 后可继续判断"}
        job = enqueue(
            c,
            "grade",
            f"grade:{identity}",
            {"attempt_id": identity, "provider": provider, "rating": data.rating},
        )
        return {**attempt_view(c, identity), "job_id": job["id"]}
    from .review_corrections import record_grade

    record_grade(
        c,
        identity,
        "correct" if correct else "incorrect",
        row["explanation_md"],
        {"provider": "deterministic"},
    )
    if not correct or row["revealed_at"] is not None or row["occurrence_kind"] != "review" or data.rating:
        finalize(c, identity, data.rating or "good")
    return attempt_view(c, identity)


def finalize(c, identity, rating="good"):
    row = c.get("card_attempts", identity)
    if row["rating"] is not None:
        return attempt_view(c, identity)
    require(row["grading_state"] == "graded", message="答案尚未完成判断")
    schedule = check_schedule(c, row)
    rules = c.rules(schedule["rule_version"] if schedule else None)
    independent = row["correctness"] == "correct" and row["independent"]
    actual_rating = rating if independent else "again"
    if schedule:
        index = schedule["stage_index"]
        intervals = rules["review"]["interval_days"]
        if not independent:
            index, relearning = 0, 1
            due = row["answered_at"] + rules["review"]["again_delay_minutes"] * 60000
            opportunity = schedule["opportunity_key"]
        else:
            relearning = 0
            if schedule["relearning"] or schedule["generation"] == 1:
                index = 0
            elif rating == "good":
                index = min(index + 1, len(intervals) - 1)
            elif rating == "easy":
                index = min(index + 2, len(intervals) - 1)
            days = intervals[index]
            if rating == "hard":
                days = max(
                    rules["review"]["minimum_day_interval"],
                    math.ceil(days * rules["review"]["hard_interval_percent"] / 100),
                )
            due = row["answered_at"] + days * 86400000
            opportunity = uid()
        after = {
            "stage_index": index,
            "due_at": due,
            "opportunity_key": opportunity,
            "generation": schedule["generation"] + 1,
            "relearning": relearning,
        }
        c.insert(
            "review_events",
            id=uid(),
            owner_id=c.owner,
            card_id=row["card_id"],
            attempt_id=identity,
            schedule_generation=schedule["generation"],
            before_json=dumps(schedule),
            after_json=dumps(after),
            rule_version=rules["version"],
            created_at=c.now,
        )
        c.update(
            "review_schedules",
            row["card_id"],
            key="card_id",
            **after,
            version=schedule["version"] + 1,
            updated_at=c.now,
        )
    c.update(
        "card_attempts", identity, rating=actual_rating, requested_rating=rating, version=row["version"] + 1
    )
    card = c.get("cards", row["card_id"])
    if independent and row["occurrence_kind"] != "verification":
        reward_answer(c, row, schedule, rules)
    elif not independent:
        c.execute(
            "UPDATE point_mastery SET current_stage=min(current_stage,2),version=version+1,updated_at=:at WHERE point_id=:p",
            {"at": c.now, "p": card["point_id"]},
        )
    c.change("point", "world", "monitor")
    return attempt_view(c, identity)


def reward_answer(c, row, schedule, rules):
    identity = row["id"]
    card = c.get("cards", row["card_id"])
    from .learning import create_activity, accept_assessment

    business_day = row["answer_business_date"] or day_at(row["answered_at"], c.tz)
    # A card has one monetary claim per business day, including startup/relearning uses.
    from .learning import activity_detail

    activity = (
        activity_detail(c, row["activity_id"])
        if row["activity_id"]
        else create_activity(
            c,
            ActivityCreate(
                point_id=card["point_id"],
                template_code="flashcard",
                narrative_md=f"主动回答：{json.loads(row['frozen_question_json'])['text']}",
            ),
            source="review",
            canonical=f"review:{row['card_id']}:{business_day}",
            submitted_at=row["answered_at"],
            submission_timezone=row["answer_timezone"],
        )
    )
    c.update("card_attempts", identity, activity_id=activity["id"])
    c.execute(
        "UPDATE evidence_items SET created_at=:at WHERE activity_id=:id",
        {"at": row["answered_at"], "id": activity["id"]},
    )
    c.update("learning_claims", activity["claim"]["id"], rule_version=rules["version"])
    payload = {
        "verdict": "verified",
        "difficulty": "standard",
        "breakthrough": "none",
        "completed_criteria": ["解释并给出可验证的学习产出"],
        "missing_criteria": [],
        "evidence_refs": [identity],
        "point_results": [
            {
                "point_id": card["point_id"],
                "can_explain": True,
                "can_apply_independently": True,
                "is_delayed_verification": schedule is not None and schedule["generation"] > 1,
                "supporting_refs": [identity],
            }
        ],
        "reasoning_summary": "先独立作答，再查看解析；按题卡答案完成判断。",
        "next_action": "按下次复习日期回来巩固。",
    }
    accept_assessment(
        c,
        activity["id"],
        payload,
        {
            "provider": "deterministic" if card["card_type"] != "short_answer" else "provider_graded",
            "is_test_adapter": c.db.settings.fake_provider,
        },
        deterministic=True,
    )


def rate(c, identity, data):
    row = c.get("card_attempts", identity)
    if row["rating"] is not None:
        return attempt_view(c, identity)
    check_version(row, data.expected_version)
    require(row["correctness"] == "correct" and row["independent"], message="只有独立答对才可选择难度")
    return finalize(c, identity, data.rating)


def advance(c, identity, version, end=False):
    row = c.get("review_rounds", identity)
    if row["state"] != "active":
        return round_view(c, identity)
    check_version(row, version)
    current = c.one(
        "SELECT * FROM review_round_items WHERE round_id=:id AND ordinal=:i",
        {"id": identity, "i": row["current_ordinal"]},
    )
    attempt = c.get("card_attempts", current["attempt_id"]) if current else None
    if attempt and attempt["grading_state"] == "graded" and attempt["rating"] is None:
        finalize(c, attempt["id"])
    if not end:
        require(attempt and attempt["grading_state"] == "graded", message="请先完成当前题")
    total = c.scalar("SELECT count(*) FROM review_round_items WHERE round_id=:id", {"id": identity})
    ordinal = row["current_ordinal"] + 1
    state = "ended" if end else "completed" if ordinal >= total else "active"
    c.update(
        "review_rounds",
        identity,
        current_ordinal=ordinal,
        state=state,
        completed_at=c.now if state != "active" else None,
        version=row["version"] + 1,
    )
    return round_view(c, identity)


def summary(c, subject_id=None):
    counts = c.one(
        """SELECT COALESCE(sum(s.generation=1),0) new,COALESCE(sum(s.due_at<=:at AND s.generation>1),0) due,
        COALESCE(sum(s.relearning),0) weak FROM review_schedules s
        WHERE s.owner_id=:o AND s.card_id IN (
            SELECT ca.id FROM cards ca WHERE ca.state='active' AND ca.point_id IN (
                SELECT p.id FROM knowledge_points p WHERE p.owner_id=:o AND p.archived_at IS NULL
                AND p.subject_id IN (SELECT id FROM subjects WHERE archived_at IS NULL)
                AND (p.chapter_id IS NULL OR p.chapter_id IN (SELECT id FROM chapters WHERE archived_at IS NULL))
                AND (:sub IS NULL OR p.subject_id=:sub)
            )
        )""",
        {"o": c.owner, "at": c.now, "sub": subject_id},
    )
    active = c.one(
        "SELECT id FROM review_rounds WHERE owner_id=:o AND state='active' ORDER BY created_at DESC LIMIT 1",
        {"o": c.owner},
    )
    used = c.scalar(
        "SELECT COALESCE(sum(peak),0) FROM (SELECT max(a.target_points) peak FROM assessments a JOIN learning_claims cl ON cl.id=a.claim_id WHERE a.owner_id=:o AND cl.first_business_date=:d AND a.reward_category='micro_review' AND a.state IN ('accepted','superseded') GROUP BY a.claim_id)",
        {"o": c.owner, "d": c.today},
    )
    return {
        **counts,
        "daily_used": used,
        "daily_cap": c.rules()["scoring"]["micro_review_daily_cap"],
        "active_round_id": active["id"] if active else None,
    }
