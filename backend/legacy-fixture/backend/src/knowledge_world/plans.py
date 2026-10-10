import json
from datetime import date
from .common import uid, dumps, require, check_version, public, iso
from .economy import raw_score


def valid_date(value):
    try:
        require(
            date.fromisoformat(value).isoformat() == value, "INVALID_DATE", "日期格式须为 YYYY-MM-DD", 400
        )
    except ValueError:
        require(False, "INVALID_DATE", "日期无效", 400)
    return value


def task_view(c, identity):
    row = c.get("study_tasks", identity)
    plan = c.get("daily_plans", row["plan_id"]) if row["plan_id"] else None
    return {
        **public(row),
        "planned_date": plan["business_date"] if plan else None,
        "execution_state": row["state"],
        "unlock_state": "unlocked" if row["completed_at"] is not None else "locked",
    }


def get_plan(c, day):
    valid_date(day)
    row = c.one("SELECT * FROM daily_plans WHERE owner_id=:o AND business_date=:d", {"o": c.owner, "d": day})
    tasks = (
        c.all(
            "SELECT id FROM study_tasks WHERE plan_id=:id AND state!='archived' ORDER BY plan_order,created_at,id",
            {"id": row["id"]},
        )
        if row
        else []
    )
    views = [task_view(c, task["id"]) for task in tasks]
    top = [task for task in views if task["parent_id"] is None]
    return {
        "id": row["id"] if row else None,
        "date": day,
        "note": row["note"] if row else "",
        "tasks": views,
        "total_top_level": len(top),
        "unlocked_top_level": sum(task["unlock_state"] == "unlocked" for task in top),
        "version": row["version"] if row else 0,
    }


def writable_plan(c, day, expected):
    valid_date(day)
    row = c.one("SELECT * FROM daily_plans WHERE owner_id=:o AND business_date=:d", {"o": c.owner, "d": day})
    require(
        (row["version"] if row else 0) == expected,
        "VERSION_CONFLICT",
        "每日计划已更新，请刷新",
        current_version=row["version"] if row else 0,
    )
    if not row:
        created = c.insert(
            "daily_plans",
            id=uid(),
            owner_id=c.owner,
            business_date=day,
            version=1,
            created_at=c.now,
            updated_at=c.now,
        )
        return c.get("daily_plans", created["id"])
    c.update("daily_plans", row["id"], version=row["version"] + 1, updated_at=c.now)
    return c.get("daily_plans", row["id"])


def touch_plan(c, identity):
    if identity:
        c.execute(
            "UPDATE daily_plans SET version=version+1,updated_at=:at WHERE id=:id",
            {"at": c.now, "id": identity},
        )
    c.change("task", "plan", "monitor")


def create_task(c, data, plan=None):
    rules = c.rules()
    if plan is None and data.planned_date:
        require(data.expected_plan_version is not None, "INVALID_INPUT", "需要计划版本", 400)
        plan = writable_plan(c, data.planned_date, data.expected_plan_version)
    if data.parent_id:
        parent = c.get("study_tasks", data.parent_id)
        require(
            parent["task_kind"] == "group" and parent["state"] != "archived",
            message="只有有效聚合任务可拥有子任务",
        )
        require(parent["plan_id"] == (plan["id"] if plan else None), message="父子任务必须在同一计划")
    if data.point_id:
        point = c.get("knowledge_points", data.point_id)
        require(point["archived_at"] is None, message="知识点已归档")
    if data.template_code:
        require(data.template_code in rules["scoring"]["templates"], "INVALID_INPUT", "任务模板无效", 400)
    complete = data.task_kind != "learning" or (
        data.point_id and data.template_code and data.acceptance.get("criteria")
    )
    terms = {"difficulty": data.difficulty}
    if complete and data.task_kind == "learning":
        terms["estimated_points"] = raw_score(rules, data.template_code, data.difficulty)[0]
    order = c.scalar(
        "SELECT COALESCE(max(plan_order),-1)+1 FROM study_tasks WHERE owner_id=:o AND plan_id IS :p AND parent_id IS :parent",
        {"o": c.owner, "p": plan["id"] if plan else None, "parent": data.parent_id},
    )
    row = c.insert(
        "study_tasks",
        id=uid(),
        owner_id=c.owner,
        parent_id=data.parent_id,
        point_id=data.point_id if data.task_kind == "learning" else None,
        plan_id=plan["id"] if plan else None,
        plan_order=order,
        title=data.title,
        task_kind=data.task_kind,
        template_code=data.template_code if data.task_kind == "learning" else None,
        acceptance_json=dumps(data.acceptance),
        quoted_terms_json=dumps(terms),
        rule_version=rules["version"],
        state="ready" if complete else "draft",
        created_at=c.now,
        updated_at=c.now,
    )
    aggregate_parent(c, data.parent_id)
    c.change("task", "plan", "monitor")
    return task_view(c, row["id"])


def edit_task(c, identity, data):
    row = c.get("study_tasks", identity)
    check_version(row, data.expected_version)
    values = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    if set(values) - {"title"}:
        require(
            row["state"] in {"draft", "ready"}, message="任务已开始，条款变更需建立新任务；纠错请申请重评"
        )
    if values.get("point_id"):
        c.get("knowledge_points", values["point_id"])
    if "template_code" in values:
        require(
            values["template_code"] in c.rules()["scoring"]["templates"], "INVALID_INPUT", "模板无效", 400
        )
    if "acceptance" in values:
        require(
            isinstance(values["acceptance"].get("criteria", []), list),
            "INVALID_INPUT",
            "完成标准须为列表",
            400,
        )
        values["acceptance_json"] = dumps(values.pop("acceptance"))
    if "difficulty" in values:
        terms = json.loads(row["quoted_terms_json"])
        terms["difficulty"] = values.pop("difficulty")
        values["quoted_terms_json"] = dumps(terms)
    template = values.get("template_code", row["template_code"])
    if row["task_kind"] == "learning" and template:
        terms = json.loads(values.get("quoted_terms_json", row["quoted_terms_json"]))
        terms["estimated_points"] = raw_score(c.rules(), template, terms.get("difficulty", "standard"))[0]
        values["quoted_terms_json"] = dumps(terms)
    c.update("study_tasks", identity, **values, version=row["version"] + 1, updated_at=c.now)
    touch_plan(c, row["plan_id"])
    return task_view(c, identity)


def start_task(c, identity, version):
    row = c.get("study_tasks", identity)
    check_version(row, version)
    if row["state"] == "in_progress":
        return task_view(c, identity)
    require(row["task_kind"] != "group", message="请开始一个子任务")
    require(row["state"] in {"draft", "ready", "in_progress"}, message="任务当前不可开始")
    if row["task_kind"] == "learning":
        acceptance = json.loads(row["acceptance_json"])
        require(
            row["point_id"] and row["template_code"] and acceptance.get("criteria"),
            "TASK_INCOMPLETE",
            "开始前请补齐知识点、任务模板和完成标准",
        )
        point = c.get("knowledge_points", row["point_id"])
        from .library import point_active

        require(point_active(c, point), message="知识点或其所属学科、章节已归档")
    rules = c.rules(row["rule_version"]) if row["state"] == "in_progress" else c.rules()
    terms = json.loads(row["quoted_terms_json"])
    terms["fixed_at"] = iso(c.now)
    if row["task_kind"] == "learning":
        terms["estimated_points"] = raw_score(
            rules, row["template_code"], terms.get("difficulty", "standard")
        )[0]
    c.update(
        "study_tasks",
        identity,
        state="in_progress",
        rule_version=rules["version"],
        quoted_terms_json=dumps(terms),
        version=row["version"] + 1,
        updated_at=c.now,
    )
    touch_plan(c, row["plan_id"])
    return task_view(c, identity)


def aggregate_parent(c, parent_id):
    if not parent_id:
        return
    parent = c.get("study_tasks", parent_id)
    children = c.all("SELECT * FROM study_tasks WHERE parent_id=:id AND state!='archived'", {"id": parent_id})
    completed = bool(children) and all(child["completed_at"] is not None for child in children)
    if completed != (parent["completed_at"] is not None):
        c.update(
            "study_tasks",
            parent_id,
            state="completed" if completed else "ready",
            completed_at=c.now if completed else None,
            completion_business_date=c.today if completed else None,
            version=parent["version"] + 1,
            updated_at=c.now,
        )
        aggregate_parent(c, parent["parent_id"])


def complete_personal(c, identity, version, reopen=False, reason=""):
    row = c.get("study_tasks", identity)
    require(row["task_kind"] == "personal", message="学习任务由评估解锁，聚合任务由子任务解锁")
    if not reopen and row["completed_at"]:
        return task_view(c, identity)
    check_version(row, version)
    require(row["state"] != "archived", message="任务已归档")
    c.update(
        "study_tasks",
        identity,
        state="ready" if reopen else "completed",
        completed_at=None if reopen else c.now,
        completion_business_date=None if reopen else c.today,
        version=row["version"] + 1,
        updated_at=c.now,
    )
    c.audit(
        "task.reopen" if reopen else "task.complete",
        "task",
        identity,
        {"reason": reason, "learning_points": 0},
    )
    aggregate_parent(c, row["parent_id"])
    touch_plan(c, row["plan_id"])
    return task_view(c, identity)


def set_learning_completion(c, task_id, activity_id, complete):
    if not task_id:
        return
    row = c.get("study_tasks", task_id)
    if complete == (row["completed_at"] is not None):
        return
    state = "archived" if row["state"] == "archived" else "completed" if complete else "submitted"
    c.update(
        "study_tasks",
        task_id,
        state=state,
        completed_at=c.now if complete else None,
        completion_business_date=c.today if complete else None,
        completion_activity_id=activity_id if complete else None,
        version=row["version"] + 1,
        updated_at=c.now,
    )
    aggregate_parent(c, row["parent_id"])
    touch_plan(c, row["plan_id"])


def reorder(c, day, data):
    plan = writable_plan(c, day, data.expected_plan_version)
    if data.parent_id:
        parent = c.get("study_tasks", data.parent_id)
        require(parent["plan_id"] == plan["id"] and parent["task_kind"] == "group", message="父级不属于计划")
    rows = c.all(
        "SELECT id FROM study_tasks WHERE plan_id=:p AND parent_id IS :parent AND state!='archived'",
        {"p": plan["id"], "parent": data.parent_id},
    )
    require(
        len(data.ordered_task_ids) == len(set(data.ordered_task_ids))
        and set(data.ordered_task_ids) == {r["id"] for r in rows},
        "INVALID_INPUT",
        "排序需包含全部同级事项且不可重复",
        400,
    )
    for i, identity in enumerate(data.ordered_task_ids):
        c.execute(
            "UPDATE study_tasks SET plan_order=:i,version=version+1,updated_at=:at WHERE id=:id",
            {"i": i, "at": c.now, "id": identity},
        )
    c.change("task", "plan", "monitor", dates=[day])
    return get_plan(c, day)


def replan(c, identity, data):
    row = c.get("study_tasks", identity)
    check_version(row, data.expected_version)
    require(not row["completed_at"] and row["state"] != "archived", message="仅未完成事项可以移日")
    require(row["parent_id"] is None, message="请移动整个父任务，保持子树完整")
    source = c.get("daily_plans", row["plan_id"]) if row["plan_id"] else None
    require(
        not source or source["business_date"] != data.target_date, "INVALID_INPUT", "任务已在目标日期", 400
    )
    if source:
        writable_plan(c, source["business_date"], data.expected_source_plan_version)
    else:
        require(data.expected_source_plan_version == 0, "VERSION_CONFLICT", "任务没有原计划")
    target = writable_plan(c, data.target_date, data.expected_target_plan_version)
    c.execute(
        """WITH RECURSIVE subtree(id) AS (SELECT :id UNION ALL SELECT t.id FROM study_tasks t JOIN subtree s ON t.parent_id=s.id)
        UPDATE study_tasks SET plan_id=:p,version=version+1,updated_at=:at WHERE id IN (SELECT id FROM subtree)""",
        {"id": identity, "p": target["id"], "at": c.now},
    )
    c.change(
        "task",
        "plan",
        "monitor",
        dates=[source["business_date"] if source else data.target_date, data.target_date],
    )
    return {
        "task": task_view(c, identity),
        "source_plan": get_plan(c, source["business_date"]) if source else None,
        "target_plan": get_plan(c, data.target_date),
    }


def archive_task(c, identity, version):
    row = c.get("study_tasks", identity)
    check_version(row, version)
    c.execute(
        """WITH RECURSIVE subtree(id) AS (SELECT :id UNION ALL SELECT t.id FROM study_tasks t JOIN subtree s ON t.parent_id=s.id)
        UPDATE study_tasks SET state='archived',version=version+1,updated_at=:at WHERE id IN (SELECT id FROM subtree)""",
        {"id": identity, "at": c.now},
    )
    aggregate_parent(c, row["parent_id"])
    touch_plan(c, row["plan_id"])
    return task_view(c, identity)


def timer_view(c, row):
    if row is None:
        return None
    seconds = row["accumulated_seconds"] + (
        max(0, (c.now - row["segment_started_at"]) // 1000) if row["state"] == "running" else 0
    )
    return {**public(row), "elapsed_seconds": seconds, "server_time": iso(c.now)}


def timer_create(c, task_id):
    if task_id:
        c.get("study_tasks", task_id)
    require(
        not c.scalar(
            "SELECT count(*) FROM timer_sessions WHERE owner_id=:o AND state='running'", {"o": c.owner}
        ),
        "TIMER_RUNNING",
        "已有进行中的计时，请先暂停或结束",
    )
    row = c.insert(
        "timer_sessions",
        id=uid(),
        owner_id=c.owner,
        task_id=task_id,
        state="running",
        segment_started_at=c.now,
        created_at=c.now,
        updated_at=c.now,
    )
    return timer_view(c, c.get("timer_sessions", row["id"]))


def timer_action(c, identity, action, version):
    row = c.get("timer_sessions", identity)
    check_version(row, version)
    require(row["state"] != "stopped", message="计时已经结束")
    segments = json.loads(row["segments_json"])
    elapsed = row["accumulated_seconds"]
    if row["state"] == "running":
        segments.append({"start": row["segment_started_at"], "end": c.now})
        elapsed += max(0, (c.now - row["segment_started_at"]) // 1000)
    if action == "resume":
        require(row["state"] == "paused", message="计时未暂停")
        require(
            not c.scalar(
                "SELECT count(*) FROM timer_sessions WHERE owner_id=:o AND state='running'", {"o": c.owner}
            ),
            "TIMER_RUNNING",
            "已有进行中的计时",
        )
    state = {"pause": "paused", "resume": "running", "stop": "stopped"}[action]
    c.update(
        "timer_sessions",
        identity,
        state=state,
        accumulated_seconds=elapsed,
        segments_json=dumps(segments),
        segment_started_at=c.now if state == "running" else None,
        version=row["version"] + 1,
        updated_at=c.now,
    )
    return timer_view(c, c.get("timer_sessions", identity))
