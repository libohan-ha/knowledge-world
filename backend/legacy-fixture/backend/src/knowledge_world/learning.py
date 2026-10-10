import json
from datetime import datetime
from .common import uid, dumps, digest, require, check_version, public, day_at
from .models import AssessmentPayload
from .economy import raw_score, settle_learning
from .plans import set_learning_completion


def create_activity(c, data, source="manual", canonical=None, submitted_at=None, submission_timezone=None):
    point = c.get("knowledge_points", data.point_id)
    from .library import point_active

    require(point_active(c, point), message="知识点或其所属学科、章节已归档")
    require(data.template_code in c.rules()["scoring"]["templates"], "INVALID_INPUT", "模板无效", 400)
    task = c.get("study_tasks", data.task_id) if data.task_id else None
    if task:
        require(
            task["task_kind"] == "learning"
            and task["point_id"] == data.point_id
            and task["template_code"] == data.template_code,
            message="任务、知识点和模板不一致",
        )
        require(
            task["state"] in {"in_progress", "submitted", "completed", "archived"},
            message="请先开始任务并固定完成标准",
        )
    key = canonical or (
        f"new_knowledge:{data.point_id}:initial"
        if data.template_code == "new_knowledge"
        else f"task:{data.task_id}:milestone:{data.milestone_id or 'main'}"
        if task
        else f"manual:{data.point_id}:{data.template_code}:{digest(data.narrative_md.strip())}"
    )
    if data.claim_id:
        claim = c.get("learning_claims", data.claim_id)
        require(
            claim["point_id"] == data.point_id and (not task or claim["task_id"] == task["id"]),
            message="成果来源与任务不匹配",
        )
    else:
        claim = c.one(
            "SELECT * FROM learning_claims WHERE owner_id=:o AND canonical_key=:k", {"o": c.owner, "k": key}
        )
    if claim is None:
        row = c.insert(
            "learning_claims",
            id=uid(),
            owner_id=c.owner,
            canonical_key=key,
            task_id=data.task_id,
            point_id=data.point_id,
            template_code=data.template_code,
            quoted_terms_json=task["quoted_terms_json"] if task else dumps({"difficulty": "standard"}),
            rule_version=task["rule_version"] if task else c.rules()["version"],
            timezone_snapshot=c.tz,
            created_at=c.now,
        )
        claim = c.get("learning_claims", row["id"])
    occurred = None
    if data.self_reported_occurred_at:
        try:
            moment = datetime.fromisoformat(data.self_reported_occurred_at)
            require(moment.tzinfo is not None, "INVALID_INPUT", "自报时间需带时区", 400)
            occurred = int(moment.timestamp() * 1000)
        except ValueError:
            require(False, "INVALID_INPUT", "自报时间格式无效", 400)
    row = c.insert(
        "activities",
        id=uid(),
        owner_id=c.owner,
        claim_id=claim["id"],
        source_kind=source,
        narrative_md=data.narrative_md,
        self_reported_occurred_at=occurred,
        state="draft",
        created_at=c.now,
        updated_at=c.now,
    )
    if data.narrative_md.strip():
        c.insert(
            "evidence_items",
            id=uid(),
            activity_id=row["id"],
            kind="text",
            content_text=data.narrative_md,
            sha256=digest(data.narrative_md),
            created_at=c.now,
        )
    for identity in data.evidence_ids:
        evidence = c.get("evidence_items", identity)
        activity = c.get("activities", evidence["activity_id"])
        require(activity["claim_id"] == claim["id"], message="证据不属于同一成果")
        values = {
            key: evidence[key]
            for key in (
                "kind",
                "material_chunk_id",
                "card_attempt_id",
                "material_id",
                "content_text",
                "sha256",
            )
        }
        if not c.scalar(
            "SELECT count(*) FROM evidence_items WHERE activity_id=:id AND sha256=:sha",
            {"id": row["id"], "sha": values["sha256"]},
        ):
            c.insert("evidence_items", id=uid(), activity_id=row["id"], **values, created_at=c.now)
    if submitted_at is not None:
        stamp_submission(c, row["id"], submitted_at, submission_timezone)
    return activity_detail(c, row["id"])


def stamp_submission(c, identity, at=None, timezone=None):
    row = c.get("activities", identity)
    claim = c.get("learning_claims", row["claim_id"])
    at = at if at is not None else c.now
    snapshot_timezone = (
        (timezone or c.tz) if claim["first_submitted_at"] is None else claim["timezone_snapshot"]
    )
    business = day_at(at, snapshot_timezone)
    if claim["first_submitted_at"] is None:
        c.update(
            "learning_claims",
            claim["id"],
            first_submitted_at=at,
            first_business_date=business,
            timezone_snapshot=snapshot_timezone,
        )
    if row["submitted_at"] is None:
        c.update(
            "activities",
            identity,
            submitted_at=at,
            business_date=business,
            state="submitted",
            version=row["version"] + 1,
            updated_at=c.now,
        )
    c.execute(
        "UPDATE point_mastery SET current_stage=max(current_stage,1),best_stage=max(best_stage,1),version=version+1,updated_at=:at WHERE point_id=:p",
        {"at": c.now, "p": claim["point_id"]},
    )
    c.execute(
        "UPDATE world_plots SET unlocked_at=COALESCE(unlocked_at,:at),version=version+1 WHERE point_id=:p",
        {"at": c.now, "p": claim["point_id"]},
    )
    if claim["task_id"]:
        c.execute(
            "UPDATE study_tasks SET state='submitted',version=version+1,updated_at=:at WHERE id=:id AND completed_at IS NULL AND state!='archived'",
            {"at": c.now, "id": claim["task_id"]},
        )
    c.change("task", "plan", "point", "world", "monitor")


def submit(c, identity, version):
    from .providers import provider_for
    from .jobs import enqueue

    row = c.get("activities", identity)
    active = c.one(
        "SELECT * FROM jobs WHERE owner_id=:o AND kind='assess' AND json_extract(payload_json,'$.activity_id')=:id AND state IN ('queued','running','retry_wait')",
        {"o": c.owner, "id": identity},
    )
    if active:
        return {"job_id": active["id"], "resource_id": identity, "state": active["state"]}
    check_version(row, version)
    stamp_submission(c, identity)
    try:
        provider = provider_for(c, "chat")
    except Exception as exc:
        from .common import DomainError

        if not isinstance(exc, DomainError):
            raise
        c.update("activities", identity, state="needs_review", updated_at=c.now)
        return {
            "resource_id": identity,
            "state": "needs_configuration",
            "message": "复盘及原提交日期已保存，配置 AI 后可继续评估。",
        }
    row = c.get("activities", identity)
    claim = c.get("learning_claims", row["claim_id"])
    job = enqueue(
        c,
        "assess",
        f"assess:{identity}:{row['version']}:{claim['version']}",
        {
            "activity_id": identity,
            "activity_version": row["version"],
            "claim_version": claim["version"],
            "provider": provider,
        },
    )
    return {"job_id": job["id"], "resource_id": identity, "state": job["state"]}


def add_evidence(c, identity, data):
    row = c.get("activities", identity)
    check_version(row, data.expected_version)
    values = {"kind": data.kind, "content_text": data.text}
    if data.kind == "text":
        require(data.text and data.text.strip(), "INVALID_INPUT", "证据文字不能为空", 400)
    elif data.kind == "material_chunk":
        from .library import confirmed_chunk

        chunk = confirmed_chunk(c, data.reference_id)
        values["material_chunk_id"] = chunk["id"]
    elif data.kind == "card_attempt":
        attempt = c.get("card_attempts", data.reference_id)
        require(attempt["activity_id"] == identity, message="作答不属于当前活动")
        values["card_attempt_id"] = attempt["id"]
    else:
        material = c.get("materials", data.reference_id)
        values["material_id"] = material["id"]
    sha = digest(dumps(values))
    if not c.scalar(
        "SELECT count(*) FROM evidence_items WHERE activity_id=:id AND sha256=:sha",
        {"id": identity, "sha": sha},
    ):
        c.insert("evidence_items", id=uid(), activity_id=identity, **values, sha256=sha, created_at=c.now)
        c.update(
            "activities",
            identity,
            state="draft" if row["submitted_at"] is None else "needs_evidence",
            version=row["version"] + 1,
            updated_at=c.now,
        )
    return activity_detail(c, identity)


def assessment_input(c, identity):
    row = c.get("activities", identity)
    claim = c.get("learning_claims", row["claim_id"])
    point = c.get("knowledge_points", claim["point_id"])
    task = c.get("study_tasks", claim["task_id"]) if claim["task_id"] else None
    evidence = c.all("SELECT * FROM evidence_items WHERE activity_id=:id", {"id": identity})
    verified = []
    chunk_ids = {e["material_chunk_id"] for e in evidence if e["material_chunk_id"]}
    if point["source_chunk_id"]:
        chunk_ids.add(point["source_chunk_id"])
    for chunk_id in chunk_ids:
        chunk = c.get("material_chunks", chunk_id)
        if chunk["confirmed_at"] is not None:
            verified.append(public(chunk))
    attempts = c.all(
        "SELECT * FROM card_attempts WHERE activity_id=:id AND answered_at IS NOT NULL", {"id": identity}
    )
    return {
        "protocol_version": "assessment.1",
        "activity_id": identity,
        "claim_id": claim["id"],
        "point": public(point),
        "task": {
            "template_code": claim["template_code"],
            "point_id": claim["point_id"],
            "criteria": json.loads(task["acceptance_json"]).get("criteria", [])
            if task
            else ["解释并给出可验证的学习产出"],
            "quoted_difficulty": json.loads(claim["quoted_terms_json"]).get("difficulty", "standard"),
        },
        "narrative": row["narrative_md"],
        "evidence": [public(e) for e in evidence],
        "verified_sources": verified,
        "verification_results": [
            {
                "attempt_id": a["id"],
                "correctness": a["correctness"],
                "independent": bool(a["independent"]),
                "answer": json.loads(a["answer_json"]),
            }
            for a in attempts
        ],
        "relevant_history": [
            public(x)
            for x in c.all(
                "SELECT * FROM assessments WHERE owner_id=:o AND claim_id=:id AND state IN ('accepted','superseded') ORDER BY revision DESC LIMIT 5",
                {"o": c.owner, "id": claim["id"]},
            )
        ],
    }


def accept_assessment(
    c, identity, payload, model_info, *, claim_version=None, activity_version=None, deterministic=False
):
    p = AssessmentPayload.model_validate(payload)
    activity = c.get("activities", identity)
    claim = c.get("learning_claims", activity["claim_id"])
    if claim_version is not None:
        check_version(claim, claim_version)
    if activity_version is not None:
        check_version(activity, activity_version)
    require(activity["submitted_at"] is not None, message="未提交的记录不能评估")
    inputs = assessment_input(c, identity)
    evidence_ids = {x["id"] for x in inputs["evidence"]} | {
        x["attempt_id"] for x in inputs["verification_results"]
    }
    evidence_ids |= {x["id"] for x in inputs["verified_sources"]}
    require(set(p.evidence_refs) <= evidence_ids, "ASSESSMENT_UNCERTAIN", "评估引用了不存在的证据", 422)
    require(
        all(
            r.point_id == claim["point_id"] and set(r.supporting_refs) <= evidence_ids
            for r in p.point_results
        ),
        "ASSESSMENT_UNCERTAIN",
        "知识判断引用无效",
        422,
    )
    if p.verdict in {"verified", "progress"}:
        require(bool(p.evidence_refs), "EVIDENCE_INSUFFICIENT", "缺少可核对的学习证据", 422)
    if p.verdict == "verified":
        require(
            not p.missing_criteria and set(inputs["task"]["criteria"]) <= set(p.completed_criteria),
            "EVIDENCE_INSUFFICIENT",
            "仍有完成标准未满足",
            422,
        )
    quoted = inputs["task"]["quoted_difficulty"]
    if p.difficulty != quoted:
        require(
            bool(inputs["relevant_history"]) and bool(p.evidence_refs),
            "ASSESSMENT_UNCERTAIN",
            "难度调整须经过有证据的重评",
            422,
        )
    if p.breakthrough != "none":
        require(bool(inputs["relevant_history"]), "ASSESSMENT_UNCERTAIN", "突破奖励缺少历史依据", 422)
    for result in p.point_results:
        if result.can_apply_independently:
            supporting = [
                a
                for a in inputs["verification_results"]
                if a["attempt_id"] in result.supporting_refs
                and a["independent"]
                and a["correctness"] == "correct"
            ]
            # Open work can be evaluated against confirmed source/criteria; mere self report is insufficient.
            concrete = bool(inputs["verified_sources"]) and any(
                e["id"] in result.supporting_refs and e.get("content_text") and len(e["content_text"]) >= 30
                for e in inputs["evidence"]
            )
            require(
                bool(supporting) or concrete or deterministic,
                "EVIDENCE_INSUFFICIENT",
                "独立运用需要作答或可核对的完整产出",
                422,
            )
    revision = (
        c.scalar("SELECT max(revision) FROM assessments WHERE claim_id=:id", {"id": claim["id"]}) or 0
    ) + 1
    previous = c.one("SELECT * FROM learning_awards WHERE claim_id=:id", {"id": claim["id"]})
    effective_template = "productive_attempt" if p.verdict == "progress" else claim["template_code"]
    raw, category = raw_score(
        c.rules(claim["rule_version"]),
        effective_template,
        p.difficulty,
        p.breakthrough,
        p.additional_progress_steps,
    )
    if p.verdict not in {"verified", "progress"}:
        raw = 0
    cutoff = max(
        [
            activity["submitted_at"],
            *[
                e["created_at"]
                for e in c.all(
                    "SELECT created_at FROM evidence_items WHERE activity_id=:id", {"id": identity}
                )
            ],
            *[
                a["answered_at"]
                for a in c.all(
                    "SELECT answered_at FROM card_attempts WHERE activity_id=:id AND answered_at IS NOT NULL",
                    {"id": identity},
                )
            ],
        ]
    )
    row = c.insert(
        "assessments",
        id=uid(),
        owner_id=c.owner,
        claim_id=claim["id"],
        activity_id=identity,
        revision=revision,
        supersedes_id=previous["current_assessment_id"] if previous else None,
        verdict=p.verdict,
        state="proposed",
        difficulty=p.difficulty,
        breakthrough=p.breakthrough,
        additional_progress_steps=p.additional_progress_steps,
        reasoning_summary=p.reasoning_summary,
        evidence_refs_json=dumps(p.evidence_refs),
        point_results_json=dumps([r.model_dump() for r in p.point_results]),
        rubric_json=dumps(
            {
                "completed_criteria": p.completed_criteria,
                "missing_criteria": p.missing_criteria,
                "next_action": p.next_action,
            }
        ),
        model_info_json=dumps(model_info),
        reward_category=category,
        evidence_cutoff_at=cutoff,
        rule_version=claim["rule_version"],
        created_at=c.now,
    )
    # Uncertain re-evaluation preserves the previous accepted award until a definite correction.
    if p.verdict in {"uncertain", "insufficient"}:
        c.update(
            "activities",
            identity,
            state="needs_review" if p.verdict == "uncertain" else "needs_evidence",
            version=activity["version"] + 1,
            updated_at=c.now,
        )
        return activity_detail(c, identity)
    receipt = settle_learning(c, claim, row, raw, category)
    c.update(
        "activities",
        identity,
        state="settled" if p.verdict in {"verified", "progress"} else "needs_evidence",
        version=activity["version"] + 1,
        updated_at=c.now,
    )
    set_learning_completion(c, claim["task_id"], identity, p.verdict == "verified")
    from .world import project_learning

    project_learning(c, claim["point_id"], row["id"], receipt, correction=p.verdict == "not_met")
    c.notify(f"assessment:{row['id']}", "学习记录已评估", p.reasoning_summary, f"/activities/{identity}")
    from .commitments import evaluate_all

    evaluate_all(c)
    return activity_detail(c, identity)


def activity_detail(c, identity):
    row = c.get("activities", identity)
    claim = c.get("learning_claims", row["claim_id"])
    assessments = c.all(
        "SELECT * FROM assessments WHERE claim_id=:id ORDER BY revision DESC", {"id": claim["id"]}
    )
    receipts = c.all(
        "SELECT * FROM ledger_entries WHERE claim_id=:id ORDER BY sequence DESC", {"id": claim["id"]}
    )
    from .review import attempt_view

    attempts = c.all("SELECT id FROM card_attempts WHERE activity_id=:id", {"id": identity})
    return {
        **public(row),
        "claim": public(claim),
        "assessments": [public(a) for a in assessments],
        "receipts": [public(r) for r in receipts],
        "evidence": [
            public(e)
            for e in c.all(
                "SELECT * FROM evidence_items WHERE activity_id=:id ORDER BY created_at", {"id": identity}
            )
        ],
        "verification_items": [attempt_view(c, a["id"]) for a in attempts],
    }
