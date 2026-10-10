import csv
import io
import json
from pathlib import Path
from .common import uid, dumps, digest, require, check_version, public, STAGES, iso, DomainError
from .db import controlled_path


def index_entity(c, kind, identity, title, body):
    c.execute("DELETE FROM knowledge_fts WHERE entity_type=:t AND entity_id=:id", {"t": kind, "id": identity})
    c.execute(
        "INSERT INTO knowledge_fts(entity_type,entity_id,owner_id,title,body) VALUES (:t,:id,:o,:title,:body)",
        {"t": kind, "id": identity, "o": c.owner, "title": title, "body": body},
    )


def create_subject(c, data):
    count = c.scalar("SELECT count(*) FROM subjects WHERE owner_id=:o", {"o": c.owner})
    row = c.insert(
        "subjects",
        id=uid(),
        owner_id=c.owner,
        name=data.name,
        theme=data.theme,
        sort_order=count,
        created_at=c.now,
        updated_at=c.now,
    )
    region = c.insert(
        "world_regions",
        id=uid(),
        owner_id=c.owner,
        subject_id=row["id"],
        theme=data.theme,
        layout_seed=uid(),
        created_at=c.now,
    )
    c.insert(
        "world_plots", id=uid(), region_id=region["id"], grid_x=0, grid_y=0, terrain="camp", unlocked_at=c.now
    )
    return public(c.get("subjects", row["id"]))


ACTIVE_POINT_SQL = "p.archived_at IS NULL AND p.subject_id IN (SELECT id FROM subjects WHERE archived_at IS NULL) AND (p.chapter_id IS NULL OR p.chapter_id IN (SELECT id FROM chapters WHERE archived_at IS NULL))"


def point_active(c, point):
    return (
        point["archived_at"] is None
        and c.get("subjects", point["subject_id"])["archived_at"] is None
        and (not point["chapter_id"] or c.get("chapters", point["chapter_id"])["archived_at"] is None)
    )


def create_chapter(c, data):
    subject = c.get("subjects", data.subject_id)
    require(subject["archived_at"] is None, message="请先恢复或选择有效学科")
    row = c.insert(
        "chapters", id=uid(), owner_id=c.owner, **data.model_dump(), created_at=c.now, updated_at=c.now
    )
    return public(c.get("chapters", row["id"]))


def confirmed_chunk(c, identity):
    row = c.one(
        "SELECT ch.*,m.owner_id,m.id material_id FROM material_chunks ch JOIN materials m ON m.id=ch.material_id WHERE ch.id=:id AND m.owner_id=:o",
        {"id": identity, "o": c.owner},
    )
    require(row is not None, "RESOURCE_NOT_FOUND", "来源不存在", 404)
    require(row["confirmed_at"] is not None, message="请先校对确认来源文字")
    return row


def create_point(c, data):
    subject = c.get("subjects", data.subject_id)
    require(subject["archived_at"] is None, message="学科已归档")
    if data.chapter_id:
        chapter = c.get("chapters", data.chapter_id)
        require(
            chapter["subject_id"] == data.subject_id and chapter["archived_at"] is None,
            message="章节不属于当前学科",
        )
    if data.source_chunk_id:
        confirmed_chunk(c, data.source_chunk_id)
    values = data.model_dump(exclude={"tags"})
    row = c.insert(
        "knowledge_points",
        id=uid(),
        owner_id=c.owner,
        **values,
        tags_json=dumps(data.tags),
        created_at=c.now,
        updated_at=c.now,
    )
    c.insert("point_mastery", point_id=row["id"], owner_id=c.owner, updated_at=c.now)
    region = c.one("SELECT * FROM world_regions WHERE subject_id=:id", {"id": data.subject_id})
    used = {
        (r["grid_x"], r["grid_y"])
        for r in c.all("SELECT grid_x,grid_y FROM world_plots WHERE region_id=:id", {"id": region["id"]})
    }
    radius = 1
    while True:
        candidates = sorted(
            (
                (x, y)
                for x in range(-radius, radius + 1)
                for y in range(-radius, radius + 1)
                if abs(x) + abs(y) == radius
            ),
            key=lambda p: (p[1], p[0]),
        )
        position = next((p for p in candidates if p not in used), None)
        if position:
            break
        radius += 1
    c.insert(
        "world_plots",
        id=uid(),
        region_id=region["id"],
        point_id=row["id"],
        grid_x=position[0],
        grid_y=position[1],
        terrain=subject["theme"],
    )
    index_entity(c, "point", row["id"], data.title, data.content_md + " " + " ".join(data.tags))
    c.change("point", "world")
    return point_view(c, row["id"])


def point_view(c, identity):
    row = c.get("knowledge_points", identity)
    mastery = c.one("SELECT * FROM point_mastery WHERE point_id=:id", {"id": identity})
    due = c.scalar(
        "SELECT min(s.due_at) FROM review_schedules s JOIN cards ca ON ca.id=s.card_id WHERE ca.point_id=:id AND ca.state='active'",
        {"id": identity},
    )
    return {
        **public(row),
        "current_stage": STAGES[mastery["current_stage"]],
        "best_stage": STAGES[mastery["best_stage"]],
        "review_state": "overdue"
        if due and due < c.now - 86400000
        else "due"
        if due and due <= c.now
        else "not_due",
        "next_review_at": iso(due),
        "mastery": public(mastery),
    }


def edit_entity(c, table, identity, data):
    row = c.get(table, identity)
    check_version(row, data.expected_version)
    values = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    if table == "knowledge_points" and values.get("chapter_id"):
        chapter = c.get("chapters", values["chapter_id"])
        require(chapter["subject_id"] == row["subject_id"], message="章节不属于当前学科")
    if "tags" in values:
        values["tags_json"] = dumps(values.pop("tags"))
    c.update(table, identity, **values, version=row["version"] + 1, updated_at=c.now)
    if table == "knowledge_points":
        result = point_view(c, identity)
        index_entity(
            c, "point", identity, result["title"], result["content_md"] + " " + " ".join(result["tags"])
        )
        return result
    return public(c.get(table, identity))


def archive(c, table, identity, version):
    row = c.get(table, identity)
    check_version(row, version)
    c.update(table, identity, archived_at=c.now, version=row["version"] + 1, updated_at=c.now)
    c.audit("archive", table, identity)
    c.change("point", "world", "monitor")
    return public(c.get(table, identity))


def validate_card(card_type, question, answer):
    require(
        isinstance(question.get("text"), str) and question["text"].strip(),
        "INVALID_INPUT",
        "题目不能为空",
        400,
    )
    require(set(question) <= {"text", "options", "style"}, "INVALID_INPUT", "题面包含不支持的字段", 400)
    if card_type in {"single_choice", "multiple_choice"}:
        options = question.get("options")
        require(
            isinstance(options, list)
            and 2 <= len(options) <= 12
            and all(isinstance(x, str) for x in options),
            "INVALID_INPUT",
            "选择题需要 2—12 个文本选项",
            400,
        )
        correct = answer.get("correct")
        answers = correct if isinstance(correct, list) else [correct]
        require(
            all(isinstance(x, str) and x in options for x in answers) and bool(answers),
            "INVALID_INPUT",
            "答案必须引用题目选项",
            400,
        )
        require(
            card_type != "single_choice" or len(answers) == 1, "INVALID_INPUT", "单选题只能有一个答案", 400
        )
    elif card_type == "cloze":
        require(
            isinstance(answer.get("accepted"), list)
            and bool(answer["accepted"])
            and all(isinstance(x, str) for x in answer["accepted"]),
            "INVALID_INPUT",
            "填空题需要可接受答案列表",
            400,
        )
    else:
        require(
            isinstance(answer.get("criteria"), list) and bool(answer["criteria"]),
            "INVALID_INPUT",
            "简答题需要评分要点",
            400,
        )


def create_card(c, data, verification=False):
    point = c.get("knowledge_points", data.point_id)
    require(point["archived_at"] is None, message="知识点已归档")
    if data.source_chunk_id:
        confirmed_chunk(c, data.source_chunk_id)
    validate_card(data.type, data.question, data.answer)
    row = c.insert(
        "cards",
        id=uid(),
        owner_id=c.owner,
        point_id=data.point_id,
        source_chunk_id=data.source_chunk_id,
        card_type=data.type,
        question_json=dumps(data.question),
        answer_json=dumps(data.answer),
        explanation_md=data.explanation,
        state="active",
        is_verification=int(verification),
        created_at=c.now,
        updated_at=c.now,
    )
    if not verification:
        c.insert(
            "review_schedules",
            card_id=row["id"],
            owner_id=c.owner,
            due_at=c.now,
            opportunity_key=uid(),
            rule_version=c.rules()["version"],
            updated_at=c.now,
        )
        index_entity(c, "card", row["id"], data.question["text"], data.explanation)
    return public(c.get("cards", row["id"]))


def edit_card(c, identity, data):
    row = c.get("cards", identity)
    check_version(row, data.expected_version)
    question = data.question if data.question is not None else json.loads(row["question_json"])
    answer = data.answer if data.answer is not None else json.loads(row["answer_json"])
    validate_card(row["card_type"], question, answer)
    c.update(
        "cards",
        identity,
        question_json=dumps(question),
        answer_json=dumps(answer),
        explanation_md=data.explanation if data.explanation is not None else row["explanation_md"],
        state=data.state or row["state"],
        version=row["version"] + 1,
        updated_at=c.now,
    )
    c.audit("card.revise", "card", identity, {"previous_version": row["version"]})
    index_entity(c, "card", identity, question["text"], data.explanation or row["explanation_md"])
    return public(c.get("cards", identity))


def save_material(c, title, subject_id, content, filename=None):
    if subject_id:
        c.get("subjects", subject_id)
    require(
        len(content) <= c.rules()["storage"]["max_upload_bytes"], "INVALID_INPUT", "材料不得超过 20MB", 400
    )
    sha = digest(content)
    existing = c.one("SELECT * FROM materials WHERE owner_id=:o AND sha256=:h", {"o": c.owner, "h": sha})
    if existing:
        return {**material_detail(c, existing["id"]), "duplicate": True}
    suffix = Path(filename or "material.txt").suffix.lower()
    allowed = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    require(suffix in allowed, "INVALID_INPUT", "不支持此文件类型", 400)
    if suffix == ".pdf":
        require(content.startswith(b"%PDF"), "INVALID_INPUT", "PDF 文件签名不正确", 400)
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        from PIL import Image

        try:
            with Image.open(io.BytesIO(content)) as im:
                im.verify()
        except Exception:
            require(False, "INVALID_INPUT", "图片文件损坏", 400)
    identity = uid()
    relative = f"materials/{identity}{suffix}"
    path = controlled_path(c.db.settings.data_dir, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    row = c.insert(
        "materials",
        id=identity,
        owner_id=c.owner,
        subject_id=subject_id,
        title=title,
        media_type=allowed[suffix],
        relative_path=relative,
        sha256=sha,
        size_bytes=len(content),
        state="uploaded",
        created_at=c.now,
        updated_at=c.now,
    )
    from .jobs import enqueue

    job = enqueue(c, "parse_material", f"material:{identity}:parse:1", {"material_id": identity})
    return {**public(row), "job_id": job["id"]}


def extract_material(settings, row, rules):
    path = controlled_path(settings.data_dir, row["relative_path"])
    data = path.read_bytes()
    require(digest(data) == row["sha256"], "FILE_CORRUPT", "材料校验失败", 409)
    info, chunks = {"parser": "local", "errors": [], "card_drafts": []}, []
    if row["media_type"] == "application/pdf":
        import pymupdf

        with pymupdf.open(path) as document:
            require(
                document.page_count <= rules["storage"]["max_pdf_pages"],
                "INVALID_INPUT",
                "PDF 页数超过限制",
                400,
            )
            for number, page in enumerate(document):
                chunks.append(({"page": number + 1}, page.get_text()))
        info["needs_vision"] = any(not text.strip() for _, text in chunks)
    elif row["media_type"].startswith("image/"):
        info["needs_vision"] = True
        chunks = [({"page": 1}, "")]
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("gb18030")
        if row["media_type"] == "text/csv":
            reader = csv.DictReader(io.StringIO(text))
            required = {"question", "type", "answer", "explanation", "subject", "chapter", "tags"}
            require(
                reader.fieldnames and required <= set(reader.fieldnames),
                "INVALID_INPUT",
                "CSV 缺少模板列：" + ",".join(sorted(required)),
                400,
            )
            for n, item in enumerate(reader, 2):
                chunks.append(({"row": n}, dumps(item)))
                try:
                    require(
                        item.get("question")
                        and item.get("answer")
                        and item.get("type") in {"single_choice", "multiple_choice", "cloze", "short_answer"},
                        "INVALID_INPUT",
                        "题目/答案为空或题型无效",
                        400,
                    )
                    question = (
                        json.loads(item["question"])
                        if item["question"].lstrip().startswith("{")
                        else {"text": item["question"]}
                    )
                    answer_text = item["answer"].strip()
                    raw_answer = (
                        json.loads(answer_text) if answer_text.startswith(("{", "[")) else answer_text
                    )
                    if isinstance(raw_answer, dict):
                        answer = raw_answer
                    elif item["type"] in {"single_choice", "multiple_choice"}:
                        answer = {"correct": raw_answer}
                    else:
                        answer = {
                            "accepted" if item["type"] == "cloze" else "criteria": raw_answer
                            if isinstance(raw_answer, list)
                            else [raw_answer]
                        }
                    validate_card(item["type"], question, answer)
                    info["card_drafts"].append(
                        {
                            "row": n,
                            **item,
                            "question": question,
                            "answer": answer,
                            "tags": [
                                x.strip()
                                for x in (item.get("tags") or "").replace("、", ",").split(",")
                                if x.strip()
                            ],
                        }
                    )
                except (DomainError, ValueError, TypeError, AttributeError) as exc:
                    info["errors"].append(
                        {
                            "row": n,
                            "message": exc.message
                            if isinstance(exc, DomainError)
                            else "题面或答案 JSON 格式无效",
                        }
                    )
        else:
            chunks = [
                ({"paragraph": n + 1}, part) for n, part in enumerate(text.split("\n\n")) if part.strip()
            ]
    return {"chunks": chunks or [({"paragraph": 1}, "")], "info": info}


def material_detail(c, identity):
    row = c.get("materials", identity)
    return {
        **public(row),
        "source_url": f"/api/v1/materials/{identity}/file",
        "chunks": [
            public(x)
            for x in c.all(
                "SELECT * FROM material_chunks WHERE material_id=:id ORDER BY ordinal", {"id": identity}
            )
        ],
    }


def confirm_material(c, identity, data):
    row = c.get("materials", identity)
    check_version(row, data.expected_version)
    require(row["state"] in {"needs_confirmation", "ready"}, message="材料尚未处理完毕")
    for edit in data.chunk_edits:
        chunk = c.get("material_chunks", edit.id)
        require(chunk["material_id"] == identity, "RESOURCE_NOT_FOUND", "来源不属于此材料", 404)
        c.update(
            "material_chunks",
            edit.id,
            content_text=edit.content_text,
            confirmed_at=c.now,
            version=chunk["version"] + 1,
        )
        index_entity(c, "material_chunk", edit.id, row["title"], edit.content_text)
    for draft in [*data.point_drafts, *data.card_drafts, *data.imported_cards]:
        require(draft.source_chunk_id is not None, "INVALID_INPUT", "导入结果必须保留来源片段", 400)
        chunk = confirmed_chunk(c, draft.source_chunk_id)
        require(chunk["material_id"] == identity, message="草稿来源不属于此材料")
    info = json.loads(row["parser_info_json"])
    published = info.setdefault("published_drafts", {})
    points, cards = [], []
    for kind, drafts, create in [
        ("point", data.point_drafts, create_point),
        ("card", data.card_drafts, create_card),
    ]:
        for draft in drafts:
            key = kind + ":" + digest(dumps(draft.model_dump()))
            if key in published:
                continue
            result = create(c, draft)
            published[key] = result["id"]
            (points if kind == "point" else cards).append(result)
    from .models import PointCreate, CardCreate

    for draft in data.imported_cards:
        key = "imported:" + digest(dumps(draft.model_dump()))
        if key in published:
            continue
        point_id = draft.point_id
        if point_id is None:
            require(draft.subject_id is not None, "INVALID_INPUT", "新知识点需要选择学科", 400)
            point = create_point(
                c,
                PointCreate(
                    subject_id=draft.subject_id,
                    chapter_id=draft.chapter_id,
                    title=draft.point_title,
                    tags=draft.tags,
                    source_chunk_id=draft.source_chunk_id,
                    content_md=draft.question["text"] + "\n\n" + draft.explanation,
                ),
            )
            point_id = point["id"]
            points.append(point)
        card = create_card(
            c,
            CardCreate(
                point_id=point_id,
                source_chunk_id=draft.source_chunk_id,
                type=draft.type,
                question=draft.question,
                answer=draft.answer,
                explanation=draft.explanation,
            ),
        )
        cards.append(card)
        published[key] = card["id"]
        completed = info.setdefault("published_csv_rows", [])
        locator = json.loads(c.get("material_chunks", draft.source_chunk_id)["locator_json"])
        if locator.get("row") not in completed:
            completed.append(locator.get("row"))
    if data.card_drafts:
        confirmed_hashes = {digest(dumps(draft.model_dump())) for draft in data.card_drafts}
        info["generated_card_drafts"] = [
            draft
            for draft in info.get("generated_card_drafts", [])
            if digest(dumps(CardCreate.model_validate(draft).model_dump())) not in confirmed_hashes
        ]
    remaining = c.scalar(
        "SELECT count(*) FROM material_chunks WHERE material_id=:id AND confirmed_at IS NULL",
        {"id": identity},
    )
    c.update(
        "materials",
        identity,
        state="ready" if not remaining else "needs_confirmation",
        parser_info_json=dumps(info),
        version=row["version"] + 1,
        updated_at=c.now,
    )
    return {**material_detail(c, identity), "created_points": points, "created_cards": cards}


def search(c, query, subject_id=None, limit=20):
    require(0 < len(query.strip()) <= 200, "INVALID_INPUT", "请输入 1—200 字搜索内容", 400)
    params = {
        "o": c.owner,
        "q": '"' + query.replace('"', '""') + '"',
        "like": "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
        "limit": limit * 3,
    }
    condition = (
        "knowledge_fts MATCH :q"
        if len(query) >= 3
        else "(title LIKE :like ESCAPE '\\' OR body LIKE :like ESCAPE '\\')"
    )
    rows = c.all(
        f"SELECT entity_type,entity_id,title,substr(body,1,240) excerpt FROM knowledge_fts WHERE owner_id=:o AND {condition} LIMIT :limit",
        params,
    )
    results = []
    for row in rows:
        if row["entity_type"] == "point":
            entity = c.get("knowledge_points", row["entity_id"])
            if not point_active(c, entity) or (subject_id and entity["subject_id"] != subject_id):
                continue
        elif row["entity_type"] == "card":
            entity = c.get("cards", row["entity_id"])
            point = c.get("knowledge_points", entity["point_id"])
            if (
                entity["state"] != "active"
                or not point_active(c, point)
                or (subject_id and point["subject_id"] != subject_id)
            ):
                continue
        else:
            entity = c.one(
                "SELECT m.* FROM materials m JOIN material_chunks ch ON ch.material_id=m.id WHERE ch.id=:id",
                {"id": row["entity_id"]},
            )
            if (
                not entity
                or entity["state"] == "archived"
                or (subject_id and entity["subject_id"] != subject_id)
            ):
                continue
        results.append(row)
        if len(results) == limit:
            break
    return results
