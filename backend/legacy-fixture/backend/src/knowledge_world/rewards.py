import json
import secrets
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from .common import uid, dumps, digest, require, check_version, public
from .db import controlled_path
from .economy import append
from .providers import provider_for


def signer(settings):
    path = settings.data_dir / ".signing-key"
    if not path.exists():
        try:
            with path.open("x", encoding="ascii") as file:
                file.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    return URLSafeTimedSerializer(path.read_text(encoding="ascii"), salt="knowledge-world-v1")


def quote(c, data):
    item = c.get("catalog_items", data.catalog_code, key="code", owned=False)
    require(item["enabled"] and item["purchasable"], "ACTION_NOT_ALLOWED", "此物品不可购买")
    allowed = {
        "image": {"prompt", "style", "size"},
        "chapter": {"series_id", "chapter_goal"},
        "upgrade": {"point_id"},
    }.get(item["kind"], set())
    require(set(data.input) <= allowed, "INVALID_INPUT", "兑换输入包含不支持的字段", 400)
    if item["kind"] in {"image", "chapter"}:
        provider = provider_for(c, "image" if item["kind"] == "image" else "chat")
        if item["kind"] == "image":
            require(
                isinstance(data.input.get("prompt"), str) and 0 < len(data.input["prompt"].strip()) <= 4000,
                "INVALID_INPUT",
                "请输入 1—4000 字图片主题",
                400,
            )
            sizes = provider["capabilities"].get("sizes", ["1024x1024"])
            require(
                data.input.get("size", "1024x1024") in sizes,
                "PROVIDER_CAPABILITY_MISSING",
                "当前模型不支持该图片尺寸",
            )
        else:
            c.get("story_series", data.input.get("series_id"))
    if item["kind"] == "upgrade":
        mastery = c.get("point_mastery", data.input.get("point_id"), key="point_id")
        require(mastery["current_stage"] >= 3, message="建筑升级需要先独立运用对应知识")
    terms = {
        "owner_id": c.owner,
        "catalog_code": item["code"],
        "catalog_version": item["version"],
        "price_coins": item["price_coins"],
        "input": data.input,
        "input_hash": digest(dumps(data.input)),
        "rule_version": c.rules()["version"],
        "issued_at": c.now,
        "nonce": uid(),
    }
    return {
        "quote_token": signer(c.db.settings).dumps(terms),
        "price_coins": item["price_coins"],
        "name": item["name"],
        "expires_in_seconds": 600,
        "input": data.input,
        "is_test_adapter": c.db.settings.fake_provider,
    }


def decode_quote(c, token):
    try:
        terms = signer(c.db.settings).loads(token, max_age=600)
    except (BadSignature, SignatureExpired):
        require(False, "QUOTE_EXPIRED", "报价无效或已过期，请重新确认")
    require(terms["owner_id"] == c.owner, "RESOURCE_NOT_FOUND", "报价不存在", 404)
    require(c.now - terms["issued_at"] <= 600000, "QUOTE_EXPIRED", "报价已过期")
    return terms


def redeem(c, token):
    from .jobs import enqueue

    terms = decode_quote(c, token)
    # The signed quote's nonce also serves as a permanent order identity.
    existing = c.one(
        "SELECT * FROM redemptions WHERE owner_id=:o AND json_extract(terms_snapshot_json,'$.nonce')=:n",
        {"o": c.owner, "n": terms["nonce"]},
    )
    if existing:
        return redemption_detail(c, existing["id"])
    item = c.get("catalog_items", terms["catalog_code"], key="code", owned=False)
    require(
        item["enabled"] and item["purchasable"] and item["version"] == terms["catalog_version"],
        "TERMS_CHANGED",
        "目录已变化，请重新报价",
    )
    generation = item["kind"] in {"image", "chapter"}
    provider = provider_for(c, "image" if item["kind"] == "image" else "chat") if generation else None
    series = None
    if item["kind"] == "chapter":
        series = c.get("story_series", terms["input"]["series_id"])
        unfinished = c.one(
            "SELECT * FROM story_chapters WHERE series_id=:id AND number=:n",
            {"id": series["id"], "n": series["last_completed_number"] + 1},
        )
        require(
            not unfinished,
            "CHAPTER_PENDING",
            "上一章尚未完成，请重试原章节",
            redemption_id=unfinished["redemption_id"] if unfinished else None,
        )
    identity = uid()
    c.insert(
        "redemptions",
        id=identity,
        owner_id=c.owner,
        catalog_code=item["code"],
        price_coins=terms["price_coins"],
        terms_snapshot_json=dumps(terms),
        input_json=dumps(terms["input"]),
        state="reserved" if generation else "succeeded",
        provider_snapshot_json=dumps(provider) if provider else None,
        rule_version=terms["rule_version"],
        created_at=c.now,
        updated_at=c.now,
    )
    if generation:
        append(
            c,
            "redemption_hold",
            "shop",
            f"redemption:{identity}:attempt:1:hold",
            "redemption",
            identity,
            available=-terms["price_coins"],
            held=terms["price_coins"],
            rule_version=terms["rule_version"],
            detail={"catalog_code": item["code"], "attempt": 1},
        )
        if series:
            context = {
                "bible": json.loads(series["bible_json"]),
                "bible_version": series["bible_version"],
                "rolling_summary": series["rolling_summary"],
                "chapter_number": series["last_completed_number"] + 1,
                "chapter_goal": terms["input"].get("chapter_goal", ""),
            }
            last = c.one(
                "SELECT body_md FROM story_chapters WHERE series_id=:id AND state='ready' ORDER BY number DESC LIMIT 1",
                {"id": series["id"]},
            )
            context["previous_excerpt"] = last["body_md"][-3000:] if last else ""
            c.insert(
                "story_chapters",
                id=uid(),
                series_id=series["id"],
                number=context["chapter_number"],
                redemption_id=identity,
                state="pending",
                context_snapshot_json=dumps(context),
                created_at=c.now,
            )
        enqueue(
            c,
            "generate",
            f"redemption:{identity}:attempt:1",
            {"redemption_id": identity, "attempt": 1, "provider": provider},
        )
    else:
        append(
            c,
            "purchase",
            "shop",
            f"purchase:{identity}",
            "redemption",
            identity,
            available=-terms["price_coins"],
            rule_version=terms["rule_version"],
            detail={"catalog_code": item["code"]},
        )
        c.insert(
            "inventory_items",
            id=uid(),
            owner_id=c.owner,
            catalog_code=item["code"],
            grant_key=f"purchase:{identity}:0",
            state="owned",
            created_at=c.now,
        )
    return redemption_detail(c, identity)


def redemption_detail(c, identity):
    row = c.get("redemptions", identity)
    view = public(row)
    view.pop("provider_snapshot", None)
    view["terms_snapshot"].pop("owner_id", None)
    asset = c.one("SELECT * FROM generated_assets WHERE redemption_id=:id", {"id": identity})
    job = c.one(
        "SELECT * FROM jobs WHERE json_extract(payload_json,'$.redemption_id')=:id ORDER BY created_at DESC LIMIT 1",
        {"id": identity},
    )
    return {
        **view,
        "asset": public(asset),
        "job_id": job["id"] if job else None,
        "receipts": [
            public(r)
            for r in c.all(
                "SELECT * FROM ledger_entries WHERE owner_id=:o AND origin_type='redemption' AND origin_id=:id ORDER BY sequence",
                {"o": c.owner, "id": identity},
            )
        ],
    }


def fail(c, identity, attempt, reason, cancelled=False):
    row = c.get("redemptions", identity)
    if row["attempt_number"] != attempt or row["state"] in {"succeeded", "failed", "cancelled"}:
        return
    append(
        c,
        "redemption_refund",
        "shop",
        f"redemption:{identity}:attempt:{attempt}:settlement",
        "redemption",
        identity,
        available=row["price_coins"],
        held=-row["price_coins"],
        rule_version=row["rule_version"],
        detail={"reason": reason, "attempt": attempt, "supplier_refund_claimed": False},
    )
    c.update(
        "redemptions",
        identity,
        state="cancelled" if cancelled else "failed",
        version=row["version"] + 1,
        updated_at=c.now,
    )
    c.execute(
        "UPDATE story_chapters SET state='failed' WHERE redemption_id=:id AND state='pending'",
        {"id": identity},
    )


def retry(c, identity, version):
    from .jobs import enqueue

    row = c.get("redemptions", identity)
    check_version(row, version)
    require(row["state"] in {"failed", "cancelled"}, message="先结束待确认尝试并退回游戏币，再明确重试")
    item = c.get("catalog_items", row["catalog_code"], key="code", owned=False)
    provider = provider_for(c, "image" if item["kind"] == "image" else "chat")
    attempt = row["attempt_number"] + 1
    append(
        c,
        "redemption_hold",
        "shop",
        f"redemption:{identity}:attempt:{attempt}:hold",
        "redemption",
        identity,
        available=-row["price_coins"],
        held=row["price_coins"],
        rule_version=row["rule_version"],
        detail={"attempt": attempt},
    )
    c.update(
        "redemptions",
        identity,
        state="reserved",
        attempt_number=attempt,
        provider_snapshot_json=dumps(provider),
        version=row["version"] + 1,
        updated_at=c.now,
    )
    c.execute("UPDATE story_chapters SET state='pending' WHERE redemption_id=:id", {"id": identity})
    enqueue(
        c,
        "generate",
        f"redemption:{identity}:attempt:{attempt}",
        {"redemption_id": identity, "attempt": attempt, "provider": provider},
    )
    return redemption_detail(c, identity)


def cancel(c, identity, version):
    row = c.get("redemptions", identity)
    check_version(row, version)
    require(row["state"] != "succeeded", message="作品已经交付")
    fail(c, identity, row["attempt_number"], "用户结束尝试", True)
    c.execute(
        "UPDATE jobs SET state='cancelled',lease_token=lease_token+1,updated_at=:at WHERE json_extract(payload_json,'$.redemption_id')=:id AND state IN ('queued','running','retry_wait','needs_review')",
        {"id": identity, "at": c.now},
    )
    return redemption_detail(c, identity)


def save_generated_file(settings, blob, suffix):
    identity = uid()
    relative = f"assets/{identity}{suffix}"
    path = controlled_path(settings.data_dir, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(blob)
    require(digest(temporary.read_bytes()) == digest(blob), "FILE_CORRUPT", "作品写入校验失败")
    temporary.replace(path)
    return {"relative_path": relative, "sha256": digest(blob), "size_bytes": len(blob)}


def finish(c, identity, attempt, file, metadata, chapter=None):
    row = c.get("redemptions", identity)
    require(
        row["attempt_number"] == attempt and row["state"] in {"reserved", "running"},
        "STALE_JOB",
        "兑换尝试已失效",
    )
    path = controlled_path(c.db.settings.data_dir, file["relative_path"])
    require(
        path.is_file() and digest(path.read_bytes()) == file["sha256"], "FILE_CORRUPT", "作品文件未通过校验"
    )
    asset = c.insert(
        "generated_assets",
        id=uid(),
        owner_id=c.owner,
        redemption_id=identity,
        kind="text" if chapter else "image",
        mime_type="text/markdown" if chapter else "image/png",
        **file,
        prompt_summary=json.loads(row["input_json"]).get("prompt", "连续小说章节"),
        provider_metadata_json=dumps(metadata),
        created_at=c.now,
    )
    if chapter:
        current = c.one("SELECT * FROM story_chapters WHERE redemption_id=:id", {"id": identity})
        series = c.get("story_series", current["series_id"])
        require(
            chapter["chapter_number"] == current["number"] == series["last_completed_number"] + 1,
            message="章节顺序发生冲突",
        )
        c.update(
            "story_chapters",
            current["id"],
            state="ready",
            title=chapter["title"],
            body_md=chapter["body_markdown"],
            summary=chapter["chapter_summary"],
            asset_id=asset["id"],
            completed_at=c.now,
        )
        c.update(
            "story_series",
            series["id"],
            rolling_summary=(
                series["rolling_summary"]
                + "\n"
                + chapter["chapter_summary"]
                + "\n"
                + "\n".join(chapter["continuity_updates"])
            )[-12000:],
            last_completed_number=current["number"],
            version=series["version"] + 1,
            updated_at=c.now,
        )
    append(
        c,
        "redemption_spend",
        "shop",
        f"redemption:{identity}:attempt:{attempt}:settlement",
        "redemption",
        identity,
        held=-row["price_coins"],
        rule_version=row["rule_version"],
        detail={"asset_id": asset["id"], "attempt": attempt},
    )
    c.update("redemptions", identity, state="succeeded", version=row["version"] + 1, updated_at=c.now)
    c.notify(
        f"redemption:{identity}:delivered", "你的奖励准备好了", "作品已保存，可以随时收藏和下载", "/workshop"
    )
    return redemption_detail(c, identity)
