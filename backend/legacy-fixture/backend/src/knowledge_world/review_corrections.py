"""Append grading decisions and replay schedules without rewriting historical events."""

import json
import math
from .common import uid, dumps, digest, require, check_version


def record_grade(c, identity, correctness, explanation, model_info, reason=""):
    revision = (
        c.scalar("SELECT max(revision) FROM attempt_gradings WHERE attempt_id=:id", {"id": identity}) or 0
    ) + 1
    return c.insert(
        "attempt_gradings",
        id=uid(),
        owner_id=c.owner,
        attempt_id=identity,
        revision=revision,
        correctness=correctness,
        explanation_md=explanation,
        reason=reason,
        model_info_json=dumps(model_info),
        created_at=c.now,
    )


def reassess(c, identity, data):
    from .providers import provider_for
    from .jobs import enqueue
    from .review import attempt_view

    row = c.get("card_attempts", identity)
    require(row["answered_at"] is not None, message="请先提交回答")
    require(
        c.get("cards", row["card_id"])["card_type"] == "short_answer",
        message="客观题依据确定答案判断；题目有误请在知识库修订",
    )
    active = c.one(
        "SELECT * FROM jobs WHERE kind='grade' AND json_extract(payload_json,'$.attempt_id')=:id AND state IN ('queued','running','retry_wait')",
        {"id": identity},
    )
    if active:
        return {**attempt_view(c, identity), "job_id": active["id"]}
    check_version(row, data.expected_version)
    config = provider_for(c, "chat")
    revision = row["version"] + 1
    c.update("card_attempts", identity, version=revision)
    job = enqueue(
        c,
        "grade",
        f"regrade:{identity}:{revision}",
        {
            "attempt_id": identity,
            "provider": config,
            "reason": data.reason,
            "rating": row["requested_rating"],
        },
    )
    c.audit("attempt.reassess", "card_attempt", identity, {"reason": data.reason})
    return {**attempt_view(c, identity), "job_id": job["id"]}


def replay_schedule(c, row, grading):
    current = c.get("review_schedules", row["card_id"], key="card_id")
    events = c.all(
        "SELECT * FROM review_events WHERE card_id=:id ORDER BY schedule_generation", {"id": row["card_id"]}
    )
    require(events, message="缺少可重算的调度历史")
    state = json.loads(events[0]["before_json"])
    replayed = []
    for event in events:
        attempt = c.get("card_attempts", event["attempt_id"])
        rules = c.rules(event["rule_version"])["review"]
        intervals = rules["interval_days"]
        independent = attempt["correctness"] == "correct" and attempt["independent"]
        rating = attempt["requested_rating"] or "good"
        index = state["stage_index"]
        if independent:
            index = (
                0
                if state["relearning"] or state["generation"] == 1
                else min(
                    index + (2 if rating == "easy" else 1 if rating == "good" else 0), len(intervals) - 1
                )
            )
            days = (
                max(
                    rules["minimum_day_interval"],
                    math.ceil(intervals[index] * rules["hard_interval_percent"] / 100),
                )
                if rating == "hard"
                else intervals[index]
            )
            opportunity = digest("corrected-opportunity:" + event["id"])
            due = attempt["answered_at"] + days * 86400000
        else:
            index, opportunity = 0, state["opportunity_key"]
            due = attempt["answered_at"] + rules["again_delay_minutes"] * 60000
        state = {
            **state,
            "stage_index": index,
            "due_at": due,
            "opportunity_key": opportunity,
            "relearning": int(not independent),
            "generation": state["generation"] + 1,
        }
        replayed.append({"event_id": event["id"], "after": state.copy()})
    after = {k: state[k] for k in ("stage_index", "due_at", "opportunity_key", "relearning")}
    after.update(generation=current["generation"] + 1, version=current["version"] + 1, updated_at=c.now)
    c.update("review_schedules", row["card_id"], key="card_id", **after)
    c.insert(
        "review_corrections",
        id=uid(),
        owner_id=c.owner,
        card_id=row["card_id"],
        attempt_id=row["id"],
        grading_id=grading["id"],
        before_json=dumps(current),
        after_json=dumps(after),
        replayed_events_json=dumps(replayed),
        created_at=c.now,
    )


def correct_reward(c, row):
    from .review import reward_answer
    from .learning import accept_assessment, activity_detail, submit

    if row["occurrence_kind"] == "verification":
        if row["activity_id"]:
            activity = c.get("activities", row["activity_id"])
            submit(c, activity["id"], activity["version"])
        return
    candidate = c.one(
        "SELECT * FROM card_attempts WHERE card_id=:id AND answer_business_date=:d AND correctness='correct' AND independent=1 AND rating IS NOT NULL AND occurrence_kind!='verification' ORDER BY answered_at DESC,id DESC LIMIT 1",
        {"id": row["card_id"], "d": row["answer_business_date"]},
    )
    schedule = c.get("review_schedules", row["card_id"], key="card_id")
    if candidate:
        reward_answer(c, candidate, schedule, c.rules(schedule["rule_version"]))
    elif row["activity_id"]:
        activity = activity_detail(c, row["activity_id"])
        payload = {
            "verdict": "not_met",
            "difficulty": "standard",
            "breakthrough": "none",
            "completed_criteria": [],
            "missing_criteria": ["独立回答正确"],
            "evidence_refs": [row["id"]],
            "point_results": [],
            "reasoning_summary": "题卡判断已更正：本次回答尚未达到独立回答标准；原币作为误判补偿保留。",
            "next_action": "查看解析后按新安排复习。",
        }
        accept_assessment(
            c,
            activity["id"],
            payload,
            {"provider": "grading_correction", "is_test_adapter": c.db.settings.fake_provider},
        )


def apply_grade(c, identity, output, model_info, rating=None, reason=""):
    from .review import finalize, attempt_view

    row = c.get("card_attempts", identity)
    grading = record_grade(c, identity, output["correctness"], output["explanation"], model_info, reason)
    if output["correctness"] == "uncertain" and row["correctness"] in {"correct", "incorrect"}:
        c.update("card_attempts", identity, version=row["version"] + 1)
        return attempt_view(c, identity)
    c.update(
        "card_attempts",
        identity,
        correctness=output["correctness"],
        grading_state="needs_review" if output["correctness"] == "uncertain" else "graded",
        explanation_md=output["explanation"],
        version=row["version"] + 1,
    )
    if output["correctness"] == "uncertain":
        return attempt_view(c, identity)
    changed = row["correctness"] in {"correct", "incorrect"} and row["correctness"] != output["correctness"]
    if changed and row["rating"]:
        actual = (
            row["requested_rating"] or "good"
            if output["correctness"] == "correct" and row["independent"]
            else "again"
        )
        c.update("card_attempts", identity, rating=actual)
        if c.scalar("SELECT count(*) FROM review_events WHERE attempt_id=:id", {"id": identity}):
            replay_schedule(c, row, grading)
        correct_reward(c, c.get("card_attempts", identity))
    elif row["rating"] is None and (
        output["correctness"] == "incorrect"
        or not row["independent"]
        or row["occurrence_kind"] != "review"
        or rating
    ):
        finalize(c, identity, rating or "good")
    c.change("point", "world", "monitor", "review")
    return attempt_view(c, identity)
