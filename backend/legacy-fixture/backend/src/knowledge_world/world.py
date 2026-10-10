import json
from .common import uid, dumps, require, check_version, public, STAGES
from .economy import append, wallet


def grant_achievement(c, code, evidence):
    previous = c.scalar(
        "SELECT id FROM achievement_grants WHERE owner_id=:o AND code=:code",
        {"o": c.owner, "code": code},
    )
    if previous:
        return previous
    identity = uid()
    reward_code = "first_chapter_landmark" if code.startswith("chapter:") else code
    amount = c.rules()["world"]["milestone_coin_rewards"][reward_code]
    receipt = append(
        c,
        "achievement",
        "achievement",
        f"achievement:{code}",
        "achievement",
        identity,
        available=amount,
        detail={"code": code, "evidence": evidence},
    )
    c.insert(
        "achievement_grants",
        id=identity,
        owner_id=c.owner,
        code=code,
        evidence_json=dumps(evidence),
        ledger_id=receipt["id"] if receipt else None,
        created_at=c.now,
    )
    return identity


def project_learning(c, point_id, assessment_id, receipt, correction=False):
    point = c.get("knowledge_points", point_id)
    mastery = c.get("point_mastery", point_id, key="point_id")
    rules = c.rules()["review"]
    rows = c.all(
        """SELECT a.*,cl.first_submitted_at FROM assessments a JOIN learning_claims cl ON cl.id=a.claim_id
        WHERE a.owner_id=:o AND cl.point_id=:p AND a.state='accepted' ORDER BY a.evidence_cutoff_at,a.created_at""",
        {"o": c.owner, "p": point_id},
    )
    stage, first, latest, delayed_dates = 1, None, None, set()
    for row in rows:
        for result in json.loads(row["point_results_json"]):
            if result["point_id"] != point_id:
                continue
            if result["can_explain"]:
                stage = max(stage, 2)
            if result["can_apply_independently"]:
                at = row["evidence_cutoff_at"]
                stage = max(stage, 3)
                if first is None:
                    first = at
                elif at - first >= rules["consolidation_min_first_gap_hours"] * 3600000:
                    delayed_dates.add(at // 86400000)
                latest = at
    if (
        first is not None
        and latest is not None
        and len(delayed_dates) >= rules["consolidation_min_delayed_passes"]
        and latest - first >= rules["consolidation_min_latest_gap_days"] * 86400000
    ):
        stage = 4
    best = stage if correction else max(mastery["best_stage"], stage)
    c.update(
        "point_mastery",
        point_id,
        key="point_id",
        current_stage=stage,
        best_stage=best,
        first_application_at=first,
        latest_verification_at=latest,
        delayed_pass_count=len(delayed_dates),
        consolidated_at=(mastery["consolidated_at"] or c.now) if stage == 4 else None,
        evidence_snapshot_json=dumps({"assessment_ids": [r["id"] for r in rows], "corrected": correction}),
        version=mastery["version"] + 1,
        updated_at=c.now,
    )
    c.execute(
        "UPDATE world_plots SET unlocked_at=COALESCE(unlocked_at,:at),version=version+1 WHERE point_id=:id",
        {"at": c.now, "id": point_id},
    )
    growth = 2 if stage == 4 else 1 if stage >= 3 else 0
    c.execute(
        "UPDATE plants SET growth_stage=:g,state=:s,version=version+1 WHERE point_id=:p AND state!='harvested'",
        {"g": growth, "s": "mature" if growth == 2 else "growing", "p": point_id},
    )
    c.insert(
        "world_events",
        id=uid(),
        owner_id=c.owner,
        event_key=f"assessment:{assessment_id}",
        point_id=point_id,
        ledger_id=receipt["id"] if receipt else None,
        kind="learning",
        payload_json=dumps({
            "before_stage": mastery["current_stage"], "stage": stage, "best_stage": best,
            "assessment_id": assessment_id,
            "presentation": {
                "version": 1,
                "before": {"current_stage": STAGES[mastery["current_stage"]], "best_stage": STAGES[mastery["best_stage"]], "landmark_present": None},
                "after": {"current_stage": STAGES[stage], "best_stage": STAGES[best], "landmark_present": None},
                "is_correction": bool(correction),
            },
        }),
        created_at=c.now,
    )
    if stage >= 3:
        grant_achievement(
            c, "first_verified_learning", {"point_id": point_id, "assessment_id": assessment_id}
        )
    if stage == 4:
        grant_achievement(
            c, "first_consolidated_point", {"point_id": point_id, "assessment_id": assessment_id}
        )
    if point["chapter_id"]:
        counts = c.one(
            "SELECT count(*) total, sum(m.current_stage=4) consolidated FROM knowledge_points p JOIN point_mastery m ON m.point_id=p.id WHERE p.chapter_id=:ch AND p.archived_at IS NULL",
            {"ch": point["chapter_id"]},
        )
        if (
            counts["total"]
            and counts["consolidated"] * 100
            >= counts["total"] * c.rules()["world"]["chapter_landmark_consolidated_percent"]
        ):
            achievement_id = grant_achievement(
                c,
                f"chapter:{point['chapter_id']}",
                {
                    "chapter_id": point["chapter_id"],
                    "denominator": counts["total"],
                    "consolidated": counts["consolidated"],
                },
            )
            event_key = f"chapter-landmark:{achievement_id}"
            if not c.scalar("SELECT 1 FROM world_events WHERE event_key=:k", {"k": event_key}):
                # Persist the anchor at first unlock; new chapter content cannot
                # move or erase an already earned landmark.
                anchor = c.scalar(
                    "SELECT id FROM knowledge_points WHERE chapter_id=:ch AND archived_at IS NULL ORDER BY created_at,id LIMIT 1",
                    {"ch": point["chapter_id"]},
                )
                c.insert("world_events", id=uid(), owner_id=c.owner, event_key=event_key,
                    point_id=anchor, kind="chapter_landmark",
                    payload_json=dumps({
                        "chapter_id": point["chapter_id"], "achievement_id": achievement_id,
                        "presentation": {
                            "version": 1,
                            "before": {"current_stage": None, "best_stage": None, "landmark_present": False},
                            "after": {"current_stage": None, "best_stage": None, "landmark_present": True},
                            "is_correction": False,
                        },
                    }),
                    created_at=c.now)
    c.change("point", "world", "monitor")


def world_view(c):
    regions = c.all(
        "SELECT r.*,s.name FROM world_regions r JOIN subjects s ON s.id=r.subject_id WHERE r.owner_id=:o AND s.archived_at IS NULL ORDER BY s.sort_order",
        {"o": c.owner},
    )
    return {
        "regions": [public(r) for r in regions],
        "level": wallet(c)["learning_points"] // c.rules()["world"]["level_step_points"] + 1,
        "companion": companion(c),
        "events": [
            public(r)
            for r in c.all(
                "SELECT * FROM world_events WHERE owner_id=:o ORDER BY created_at DESC LIMIT 20",
                {"o": c.owner},
            )
        ],
    }


def region_view(c, identity, chapter_id=None, limit=150, point_id=None, focus=None):
    from .library import ACTIVE_POINT_SQL, point_active

    region = c.get("world_regions", identity)
    require(c.get("subjects", region["subject_id"])["archived_at"] is None, message="学科已归档")
    require(focus in {None, "today", "due", "camp"}, "INVALID_INPUT", "地图定位方式无效", 400)
    if chapter_id:
        chapter = c.get("chapters", chapter_id)
        require(
            chapter["subject_id"] == region["subject_id"] and chapter["archived_at"] is None,
            message="请选择当前学科的有效章节",
        )
    params = {"id": identity, "ch": chapter_id, "limit": limit, "o": c.owner, "day": c.today, "at": c.now}
    if not point_id and focus in {"today", "due"}:
        condition = (
            "EXISTS (SELECT 1 FROM learning_claims cl JOIN activities a ON a.claim_id=cl.id WHERE cl.point_id=p.id AND a.business_date=:day AND a.state='settled')"
            if focus == "today"
            else "EXISTS (SELECT 1 FROM cards ca JOIN review_schedules s ON s.card_id=ca.id WHERE ca.point_id=p.id AND ca.state='active' AND s.due_at<=:at)"
        )
        point_id = c.scalar(
            "SELECT p.id FROM knowledge_points p JOIN world_plots w ON w.point_id=p.id WHERE w.region_id=:id AND "
            + ACTIVE_POINT_SQL
            + " AND "
            + condition
            + " AND (:ch IS NULL OR p.chapter_id=:ch) ORDER BY p.updated_at DESC LIMIT 1",
            params,
        )
    if point_id:
        point = c.get("knowledge_points", point_id)
        require(
            point["subject_id"] == region["subject_id"] and point_active(c, point),
            message="知识不属于当前有效区域",
        )
        center = c.one("SELECT grid_x,grid_y FROM world_plots WHERE point_id=:p", {"p": point_id})
    else:
        center = {"grid_x": 0, "grid_y": 0}
    params.update(cx=center["grid_x"], cy=center["grid_y"], point=point_id)
    where = (
        "w.region_id=:id AND (w.point_id IS NULL OR ("
        + ACTIVE_POINT_SQL
        + ")) AND (:ch IS NULL OR p.chapter_id=:ch OR w.point_id IS NULL OR w.point_id=:point)"
    )
    rows = c.all(
        """SELECT w.*,p.title,p.chapter_id,m.current_stage,m.best_stage,
        EXISTS (SELECT 1 FROM cards ca JOIN review_schedules s ON s.card_id=ca.id WHERE ca.point_id=p.id AND ca.state='active' AND s.due_at<=:at) due
        FROM world_plots w LEFT JOIN knowledge_points p ON p.id=w.point_id LEFT JOIN point_mastery m ON m.point_id=p.id WHERE """
        + where
        + """
        ORDER BY abs(w.grid_x-:cx)+abs(w.grid_y-:cy),w.grid_y,w.grid_x LIMIT :limit""",
        params,
    )
    ids = dumps([row["id"] for row in rows])
    plants, items = {}, {}
    for plant in c.all(
        "SELECT * FROM plants WHERE plot_id IN (SELECT value FROM json_each(:ids)) AND state!='harvested'",
        {"ids": ids},
    ):
        plants.setdefault(plant["plot_id"], []).append(public(plant))
    for item in c.all(
        "SELECT i.*,cat.kind,cat.asset_key FROM inventory_items i JOIN catalog_items cat ON cat.code=i.catalog_code WHERE i.placed_plot_id IN (SELECT value FROM json_each(:ids)) AND i.state='placed'",
        {"ids": ids},
    ):
        items.setdefault(item["placed_plot_id"], []).append(public(item))
    plots = [
        {
            **public(row),
            "current_stage": STAGES[row["current_stage"] or 0],
            "best_stage": STAGES[row["best_stage"] or 0],
            "plants": plants.get(row["id"], []),
            "items": items.get(row["id"], []),
            "due": bool(row["due"]),
        }
        for row in rows
    ]
    landmarks = {r["point_id"]: public(r) for r in c.all(
        "SELECT e.* FROM world_events e JOIN world_plots w ON w.point_id=e.point_id WHERE w.region_id=:id AND e.kind='chapter_landmark'",
        {"id": identity},
    )}
    for plot in plots:
        plot["chapter_landmark"] = landmarks.get(plot["point_id"])
    total = c.scalar(
        "SELECT count(*) FROM world_plots w LEFT JOIN knowledge_points p ON p.id=w.point_id WHERE " + where,
        params,
    )
    target = (
        next((row["id"] for row in rows if row["point_id"] == point_id), None)
        if point_id
        else next((row["id"] for row in rows if row["terrain"] == "camp"), None)
    )
    return {
        **public(region),
        "plots": plots,
        "visible_limit": limit,
        "total_plots": total,
        "focus_plot_id": target,
        "focus_found": bool(point_id) if focus in {"today", "due"} else True,
    }


def owned_plot(c, identity):
    row = c.get("world_plots", identity)
    c.get("world_regions", row["region_id"])
    return row


def plant(c, identity, data):
    plot = owned_plot(c, identity)
    seed = c.get("inventory_items", data.seed_item_id)
    existing = c.one("SELECT * FROM plants WHERE seed_item_id=:id", {"id": seed["id"]})
    if existing:
        require(
            existing["plot_id"] == identity and existing["point_id"] == data.point_id,
            message="种子已经在其他位置使用",
        )
        return public(existing)
    check_version(plot, data.expected_version)
    require(seed["catalog_code"] == "seed_basic" and seed["state"] == "owned", message="需要背包中的种子")
    require(
        plot["unlocked_at"] is not None and plot["point_id"] == data.point_id,
        message="请选择已经探索的对应知识地块",
    )
    require(
        not c.scalar("SELECT count(*) FROM plants WHERE plot_id=:p AND state!='harvested'", {"p": identity}),
        message="地块已有植物",
    )
    mastery = c.get("point_mastery", data.point_id, key="point_id")
    stage = 2 if mastery["current_stage"] == 4 else 1 if mastery["current_stage"] >= 3 else 0
    row = c.insert(
        "plants",
        id=uid(),
        owner_id=c.owner,
        plot_id=identity,
        point_id=data.point_id,
        seed_item_id=seed["id"],
        growth_stage=stage,
        state="mature" if stage == 2 else "growing",
        created_at=c.now,
    )
    c.update("inventory_items", seed["id"], state="consumed", version=seed["version"] + 1)
    c.update("world_plots", identity, version=plot["version"] + 1)
    c.change("world")
    return public(c.get("plants", row["id"]))


def harvest(c, identity, version):
    row = c.get("plants", identity)
    if row["state"] == "harvested":
        return public(row)
    check_version(row, version)
    require(row["state"] == "mature", message="稳定巩固对应知识后才可收获")
    item = c.insert(
        "inventory_items",
        id=uid(),
        owner_id=c.owner,
        catalog_code="harvest_collectible",
        grant_key=f"harvest:{identity}",
        state="owned",
        created_at=c.now,
    )
    c.update(
        "plants",
        identity,
        state="harvested",
        harvest_item_id=item["id"],
        harvested_at=c.now,
        version=row["version"] + 1,
    )
    c.change("world")
    return public(c.get("plants", identity))


def place(c, identity, data):
    row = c.get("inventory_items", identity)
    check_version(row, data.expected_version)
    plot = owned_plot(c, data.plot_id)
    cat = c.get("catalog_items", row["catalog_code"], key="code", owned=False)
    require(
        cat["kind"] in {"decoration", "upgrade", "collectible"} and row["state"] in {"owned", "placed"},
        message="道具不能摆放",
    )
    require(plot["unlocked_at"] is not None, message="请先探索地块")
    require(set(data.placement) <= {"x", "y", "rotation"}, "INVALID_INPUT", "摆放参数无效", 400)
    require(
        all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) <= 128
            for value in data.placement.values()
        ),
        "INVALID_INPUT",
        "摆放坐标超出地块",
        400,
    )
    if cat["kind"] == "upgrade":
        require(plot["point_id"] is not None, message="请选择知识建筑")
        mastery = c.get("point_mastery", plot["point_id"], key="point_id")
        require(mastery["current_stage"] >= 3, message="建筑升级需要独立运用该知识")
    c.update(
        "inventory_items",
        identity,
        state="placed",
        placed_plot_id=data.plot_id,
        placement_json=dumps(data.placement),
        version=row["version"] + 1,
    )
    c.change("world")
    return public(c.get("inventory_items", identity))


def companion(c):
    row = c.one("SELECT * FROM companions WHERE owner_id=:o", {"o": c.owner})
    recent = (
        c.one(
            "SELECT * FROM companion_interactions WHERE companion_id=:id ORDER BY created_at DESC LIMIT 1",
            {"id": row["id"]},
        )
        if row
        else None
    )
    return {
        **public(row),
        "outfit_unlocked": bool(row["affinity"]),
        "latest_response": recent["response_text"] if recent else "灯还亮着。今天，想先探索哪一点知识？",
    }


def interact(c):
    row = c.one("SELECT * FROM companions WHERE owner_id=:o", {"o": c.owner})
    previous = c.one(
        "SELECT * FROM companion_interactions WHERE companion_id=:id AND business_date=:d AND affinity_delta>0",
        {"id": row["id"], "d": c.today},
    )
    if previous:
        return {**companion(c), "interaction": public(previous)}
    point = c.one(
        "SELECT p.id,p.title FROM activities a JOIN learning_claims cl ON cl.id=a.claim_id JOIN knowledge_points p ON p.id=cl.point_id WHERE a.owner_id=:o AND a.business_date=:d AND a.state='settled' ORDER BY a.updated_at DESC LIMIT 1",
        {"o": c.owner, "d": c.today},
    )
    response = (
        f"今天你认真照料了「{point['title']}」。我们一起把这片小小的进步留住。"
        if point
        else "先坐一会儿吧。准备好时，我们从一件小事开始。"
    )
    gain = c.rules()["world"]["daily_companion_affinity_gain"]
    c.insert(
        "companion_interactions",
        id=uid(),
        companion_id=row["id"],
        business_date=c.today,
        affinity_delta=gain,
        response_text=response,
        evidence_refs_json=dumps([point["id"]] if point else []),
        created_at=c.now,
    )
    c.update("companions", row["id"], affinity=row["affinity"] + gain, version=row["version"] + 1)
    return companion(c)
