import asyncio
import base64
import json
import logging
import os
import secrets
from typing import Annotated
from uuid import UUID
from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, IntegrityError
from starlette.concurrency import run_in_threadpool
from .config import Settings, ROOT
from .db import Database, Context, controlled_path
from .common import DomainError, require, uid, dumps, digest, public, page, iso, check_version
from . import models as m
from . import (
    identity,
    library,
    plans,
    learning,
    review,
    world,
    world_history,
    routines,
    commitments,
    rewards,
    providers,
    reporting,
    jobs,
    shiyi,
)

logger = logging.getLogger("knowledge_world.api")
UPLOAD_LIMIT = json.loads((ROOT / "docs/contracts/default-rules.json").read_text(encoding="utf-8"))[
    "storage"
]["max_upload_bytes"]


async def bounded_body(request):
    # Bound the stream before Starlette buffers it, including chunked requests.
    limit = (
        512 * 1024 * 1024
        if request.url.path.endswith("/restore-previews")
        else UPLOAD_LIMIT
        if request.url.path == "/api/v1/materials"
        else 1024 * 1024
    ) + 65536
    length = request.headers.get("content-length")
    if length:
        require(length.isdecimal(), "INVALID_INPUT", "请求长度无效", 400)
        require(int(length) <= limit, "PAYLOAD_TOO_LARGE", "请求内容超过大小限制", 413)
    parts, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        require(size <= limit, "PAYLOAD_TOO_LARGE", "请求内容超过大小限制", 413)
        parts.append(chunk)
    request._body = b"".join(parts)
    return request._body


def response(c, data, status=200):
    return JSONResponse(
        {
            "data": data,
            "meta": {
                "request_id": getattr(c, "request_id", uid()),
                "server_time": iso(c.now),
                "changed_resources": c.changed,
            },
        },
        status_code=status,
    )


def error_response(exc, request_id):
    return JSONResponse(
        {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "retryable": exc.status >= 500,
            },
            "meta": {"request_id": request_id},
        },
        status_code=exc.status,
    )


class TransactionRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            db = request.app.state.db
            rid = uid()
            write = request.method not in {"GET", "HEAD", "OPTIONS"}
            materializing_read = request.url.path in {"/api/v1/habits", "/api/v1/screen-time"}
            session = Session(db.engine)
            c = Context(db, session)
            c.request_id = rid
            request.state.context = c
            idem = None
            public_paths = {"/api/v1/health", "/api/v1/setup/status", "/api/v1/setup", "/api/v1/auth/login"}
            try:
                body = await bounded_body(request)
                if (db.settings.data_dir / ".maintenance").exists():
                    raise DomainError("MAINTENANCE", "正在恢复数据，请稍后重新登录", 503)
                if write or materializing_read:
                    await run_in_threadpool(session.execute, text("BEGIN IMMEDIATE"))
                if write:
                    origins = {db.settings.origin.rstrip("/")}
                    if db.settings.mode in {"test", "development"}:
                        origins |= {"http://testserver", "http://127.0.0.1:5173", "http://localhost:5173"}
                    require(
                        request.headers.get("origin", "") in origins,
                        "CSRF_REJECTED",
                        "请求来源不符合当前站点设置",
                        403,
                    )
                if request.url.path not in public_paths:
                    token = request.cookies.get("kw_session", "")
                    auth = await run_in_threadpool(
                        c.one,
                        "SELECT * FROM auth_sessions WHERE token_hash=:h AND revoked_at IS NULL AND expires_at>:at",
                        {"h": digest(token), "at": c.now},
                    )
                    require(auth is not None, "AUTH_REQUIRED", "请先登录", 401)
                    c.owner = auth["owner_id"]
                    c.auth_session = auth
                    if write:
                        require(
                            secrets.compare_digest(
                                auth["csrf_token_hash"], digest(request.headers.get("x-csrf-token", ""))
                            ),
                            "CSRF_REJECTED",
                            "登录校验已过期，请刷新页面",
                            403,
                        )
                        key = request.headers.get("idempotency-key")
                        require(key and len(key) <= 128, "INVALID_INPUT", "需要有效的 Idempotency-Key", 400)
                        route = request.method + " " + request.url.path
                        fingerprint = digest(body)
                        previous = c.one(
                            "SELECT * FROM idempotency_keys WHERE owner_id=:o AND route=:r AND key=:k",
                            {"o": c.owner, "r": route, "k": key},
                        )
                        if previous:
                            require(
                                previous["request_hash"] == fingerprint,
                                "IDEMPOTENCY_CONFLICT",
                                "相同请求标识对应了不同内容",
                            )
                            require(previous["state"] == "completed", "REQUEST_IN_PROGRESS", "请求仍在处理中")
                            await run_in_threadpool(session.rollback)
                            return JSONResponse(
                                json.loads(previous["response_json"]), status_code=previous["http_status"]
                            )
                        c.insert(
                            "idempotency_keys",
                            owner_id=c.owner,
                            route=route,
                            key=key,
                            request_hash=fingerprint,
                            state="processing",
                            created_at=c.now,
                            expires_at=c.now + 72 * 3600000,
                        )
                        idem = (route, key)
                result = await original(request)
                if result.status_code >= 400:
                    await run_in_threadpool(session.rollback)
                else:
                    if idem and hasattr(result, "body") and result.media_type == "application/json":
                        c.execute(
                            "UPDATE idempotency_keys SET state='completed',http_status=:s,response_json=:body WHERE owner_id=:o AND route=:r AND key=:k",
                            {
                                "s": result.status_code,
                                "body": result.body.decode(),
                                "o": c.owner,
                                "r": idem[0],
                                "k": idem[1],
                            },
                        )
                    await run_in_threadpool(session.commit)
                return result
            except DomainError as exc:
                await run_in_threadpool(session.rollback)
                return error_response(exc, rid)
            except RequestValidationError as exc:
                await run_in_threadpool(session.rollback)
                # Omit input values: validation errors may involve passwords/API keys.
                return error_response(
                    DomainError(
                        "INVALID_INPUT",
                        "输入格式不符合要求",
                        422,
                        fields=[
                            {"location": error["loc"], "message": error["msg"]} for error in exc.errors()
                        ],
                    ),
                    rid,
                )
            except OperationalError:
                await run_in_threadpool(session.rollback)
                return error_response(DomainError("DATABASE_BUSY", "数据库正忙，请稍后重试", 503), rid)
            except IntegrityError:
                await run_in_threadpool(session.rollback)
                return error_response(
                    DomainError("STATE_CONFLICT", "数据或状态已发生冲突，请刷新后重试"), rid
                )
            except Exception as exc:
                await run_in_threadpool(session.rollback)
                logger.error("request_failed request_id=%s type=%s", rid, type(exc).__name__)
                return error_response(
                    DomainError("INTERNAL_ERROR", "请求未完成，请保留请求编号并查看服务诊断", 500), rid
                )
            finally:
                await run_in_threadpool(session.close)

        return handler


def context(request: Request):
    return request.state.context


router = APIRouter(prefix="/api/v1", route_class=TransactionRoute)
C = Depends(context)


def paginate(
    c,
    table,
    where="1=1",
    params=None,
    limit=20,
    cursor=None,
    order="created_at DESC,id",
    owned=True,
    transform=public,
):
    require(1 <= limit <= 100, "INVALID_INPUT", "每页最多 100 条", 400)
    try:
        offset = int(base64.urlsafe_b64decode(cursor).decode()) if cursor else 0
        require(0 <= offset <= 10_000_000, "INVALID_INPUT", "分页游标无效", 400)
    except (ValueError, TypeError):
        raise DomainError("INVALID_INPUT", "分页游标无效", 400)
    query = (
        f"SELECT * FROM {table} WHERE "
        + ("owner_id=:o AND " if owned else "")
        + where
        + f" ORDER BY {order} LIMIT :n OFFSET :offset"
    )
    rows = c.all(query, {"o": c.owner, "n": limit + 1, "offset": offset, **(params or {})})
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode() if len(rows) > limit else None
    )
    return page([transform(r) for r in rows[:limit]], next_cursor)


@router.get("/health")
def health(c=C):
    return response(c, {"status": "ok"})


@router.get("/setup/status")
def setup_status(c=C):
    return response(c, {"initialized": bool(c.scalar("SELECT count(*) FROM profiles"))})


def session_response(c, tokens):
    token, csrf = tokens
    result = response(c, {**identity.me(c), "csrf_token": csrf})
    result.set_cookie(
        "kw_session",
        token,
        httponly=True,
        secure=c.db.settings.secure_cookie,
        samesite="strict",
        max_age=30 * 86400,
    )
    result.set_cookie(
        "kw_csrf",
        csrf,
        httponly=False,
        secure=c.db.settings.secure_cookie,
        samesite="strict",
        max_age=30 * 86400,
    )
    return result


@router.post("/setup")
def setup(data: m.Setup, c=C):
    return session_response(c, identity.setup(c, data))


@router.post("/auth/login")
def login(data: m.Login, request: Request, c=C):
    attempts = request.app.state.login_attempts
    address = request.client.host if request.client else "local"
    history = [stamp for stamp in attempts.get(address, []) if c.now - stamp < 60000]
    require(len(history) < 10, "RATE_LIMITED", "尝试次数较多，请一分钟后重试", 429)
    attempts[address] = history + [c.now]
    return session_response(c, identity.login(c, data.password))


@router.post("/auth/logout")
def logout(c=C):
    c.update("auth_sessions", c.auth_session["id"], revoked_at=c.now)
    result = response(c, {"logged_out": True})
    result.delete_cookie("kw_session")
    result.delete_cookie("kw_csrf")
    return result


@router.post("/auth/revoke-others")
def revoke_others(c=C):
    c.execute(
        "UPDATE auth_sessions SET revoked_at=:at WHERE owner_id=:o AND id!=:id AND revoked_at IS NULL",
        {"at": c.now, "o": c.owner, "id": c.auth_session["id"]},
    )
    return response(c, {"revoked": True})


@router.get("/me", response_model=m.Envelope[m.CurrentUser])
def me(c=C):
    return response(c, identity.me(c))


@router.patch("/me", response_model=m.Envelope[m.CurrentUser])
def me_edit(data: m.ProfileEdit, c=C):
    return response(c, identity.edit_profile(c, data))


@router.get("/settings")
def settings(c=C):
    import sqlite3

    return response(
        c,
        {
            "profile": public(c.profile),
            "providers": [
                providers.safe_config(r)
                for r in c.all("SELECT * FROM provider_configs WHERE owner_id=:o", {"o": c.owner})
            ],
            "is_test_adapter": c.db.settings.fake_provider,
            "mode": c.db.settings.mode,
            "sqlite_version": sqlite3.sqlite_version,
            "rules_version": c.rules()["version"],
            "jobs": [
                jobs.job_view(c, r["id"])
                for r in c.all(
                    "SELECT id FROM jobs WHERE owner_id=:o ORDER BY updated_at DESC LIMIT 20", {"o": c.owner}
                )
            ],
        },
    )


@router.patch("/settings")
def settings_edit(data: m.Preferences, c=C):
    return response(c, identity.edit_preferences(c, data))


@router.get("/rules")
def rules(c=C):
    return response(
        c,
        {
            "rules": c.rules(),
            "locked_paths": [
                "commitments.max_active",
                "commitments.max_acceptances_per_local_day",
                "world.plant_stage_count",
                "screen_time.input_method",
            ],
        },
    )


@router.post("/rules/versions")
def rule_version(data: m.RuleChange, c=C):
    current = c.rules()
    require(current["version"] == data.based_on_version, "VERSION_CONFLICT", "规则版本已更新")
    allowed = {
        "scoring.micro_review_daily_cap",
        "scoring.productive_attempt_daily_cap",
        "screen_time.default_limit_minutes",
        "screen_time.success_reward_coins",
        "habits.max_total_daily_penalty_coins",
        "generation.max_images_per_day",
        "generation.max_story_chapters_per_day",
    }
    require(set(data.changes) <= allowed, "INVALID_INPUT", "只支持声明的数值规则修改", 400)
    for key, value in data.changes.items():
        require(type(value) is int and 0 <= value <= 10000, "INVALID_INPUT", "规则数值无效", 400)
        group, name = key.split(".")
        current[group][name] = value
    current["version"] = c.today + "." + uid()[:8]
    c.execute("UPDATE rule_versions SET is_active=0 WHERE is_active=1")
    c.insert(
        "rule_versions", id=current["version"], payload_json=dumps(current), is_active=1, created_at=c.now
    )
    c.audit("rules.publish", "rule_version", current["version"], {"changes": data.changes})
    return response(c, current, 201)


@router.get("/providers")
def get_providers(c=C):
    return response(
        c,
        page(
            [
                providers.safe_config(r)
                for r in c.all("SELECT * FROM provider_configs WHERE owner_id=:o", {"o": c.owner})
            ]
        ),
    )


@router.put("/providers/{role}")
def put_provider(role: str, data: m.ProviderConfig, c=C):
    return response(c, providers.configure(c, role, data))


@router.post("/providers/{role}/test")
def test_provider(role: str, c=C):
    config = providers.provider_for(c, role, testing=True)
    job = jobs.enqueue(c, "provider_test", f"provider-test:{role}:{uid()}", {"provider": config})
    return response(c, {"job_id": job["id"], "state": "queued"}, 202)


def shiyi_response(c, name, query, extra=None):
    arguments, cursor = shiyi.query_arguments(query)
    result = response(c, shiyi.fetch_for_request(c, name, {**arguments, **(extra or {})}, cursor))
    result.headers["Cache-Control"] = "no-store"
    return result


@router.get("/integrations/shiyi", response_model=m.Envelope[shiyi.ShiyiConnectionResult])
def shiyi_connection(c=C):
    return response(c, {"connection": shiyi.view(shiyi.current(c)), "job_id": None})


@router.put("/integrations/shiyi", response_model=m.Envelope[shiyi.ShiyiConnectionResult])
def shiyi_configure(data: shiyi.ConnectionConfig, c=C):
    result = shiyi.configure(c, data)
    return response(c, result, 202 if result["job_id"] else 200)


@router.post("/integrations/shiyi/check", response_model=m.Envelope[shiyi.ShiyiConnectionResult])
def shiyi_check(data: m.Expected, c=C):
    return response(c, shiyi.enqueue_check(c, data.expected_version), 202)


@router.get("/integrations/shiyi/context", response_model=m.Envelope[shiyi.ShiyiContext])
def shiyi_context(query: Annotated[shiyi.ContextQuery, Query()], c=C):
    return shiyi_response(c, "shiyi_context", query)


@router.get("/integrations/shiyi/reviews", response_model=m.Envelope[shiyi.ShiyiReviews])
def shiyi_reviews(query: Annotated[shiyi.ReviewsQuery, Query()], c=C):
    return shiyi_response(c, "shiyi_reviews", query)


@router.get("/integrations/shiyi/due", response_model=m.Envelope[shiyi.ShiyiDue])
def shiyi_due(query: Annotated[shiyi.DueQuery, Query()], c=C):
    return shiyi_response(c, "shiyi_due", query)


@router.get("/integrations/shiyi/weaknesses", response_model=m.Envelope[shiyi.ShiyiPage])
def shiyi_weaknesses(query: Annotated[shiyi.WeaknessesQuery, Query()], c=C):
    return shiyi_response(c, "shiyi_weaknesses", query)


@router.get("/integrations/shiyi/items", response_model=m.Envelope[shiyi.ShiyiPage])
def shiyi_items(query: Annotated[shiyi.SearchQuery, Query()], c=C):
    return shiyi_response(c, "shiyi_search", query)


@router.get("/integrations/shiyi/items/{identity}", response_model=m.Envelope[shiyi.ShiyiItem])
def shiyi_item(identity: UUID, query: Annotated[shiyi.ItemQuery, Query()], c=C):
    return shiyi_response(c, "shiyi_item", query, {"item_id": str(identity)})


@router.get("/integrations/shiyi/media/{identity}", responses={200: {"content": {mime: {} for mime in shiyi.IMAGE_TYPES}}})
def shiyi_media(identity: UUID, query: Annotated[m.Input, Query()], c=C):
    result = shiyi.fetch_for_request(c, "shiyi_image", {"media_id": str(identity)})
    blob, mime = shiyi.media_bytes(result)
    return Response(blob, media_type=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/subjects")
def subjects(limit: int = 100, cursor: str | None = None, c=C):
    return response(
        c, paginate(c, "subjects", "archived_at IS NULL", limit=limit, cursor=cursor, order="sort_order,id")
    )


@router.post("/subjects")
def subject_create(data: m.SubjectCreate, c=C):
    return response(c, library.create_subject(c, data), 201)


@router.patch("/subjects/{identity}")
def subject_edit(identity: str, data: m.SubjectEdit, c=C):
    return response(c, library.edit_entity(c, "subjects", identity, data))


@router.post("/subjects/{identity}/archive")
def subject_archive(identity: str, data: m.Expected, c=C):
    return response(c, library.archive(c, "subjects", identity, data.expected_version))


@router.get("/chapters")
def chapters(subject_id: str | None = None, limit: int = 100, cursor: str | None = None, c=C):
    return response(
        c,
        paginate(
            c,
            "chapters",
            "archived_at IS NULL AND (:sub IS NULL OR subject_id=:sub) AND subject_id IN (SELECT id FROM subjects WHERE archived_at IS NULL)",
            {"sub": subject_id},
            limit,
            cursor,
            "sort_order,id",
        ),
    )


@router.post("/chapters")
def chapter_create(data: m.ChapterCreate, c=C):
    return response(c, library.create_chapter(c, data), 201)


@router.patch("/chapters/{identity}")
def chapter_edit(identity: str, data: m.ChapterEdit, c=C):
    return response(c, library.edit_entity(c, "chapters", identity, data))


@router.post("/chapters/{identity}/archive")
def chapter_archive(identity: str, data: m.Expected, c=C):
    return response(c, library.archive(c, "chapters", identity, data.expected_version))


@router.get("/points", response_model=m.Envelope[m.Page[m.PointView]])
def points(
    subject_id: str | None = None,
    chapter_id: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
    query: str = "",
    c=C,
):
    return response(
        c,
        paginate(
            c,
            "knowledge_points",
            "archived_at IS NULL AND subject_id IN (SELECT id FROM subjects WHERE archived_at IS NULL) AND (chapter_id IS NULL OR chapter_id IN (SELECT id FROM chapters WHERE archived_at IS NULL)) AND (:sub IS NULL OR subject_id=:sub) AND (:ch IS NULL OR chapter_id=:ch) AND (:q='' OR instr(lower(title),lower(:q))>0)",
            {"sub": subject_id, "ch": chapter_id, "q": query[:200]},
            limit,
            cursor,
            transform=lambda row: library.point_view(c, row["id"]),
        ),
    )


@router.post("/points", response_model=m.Envelope[m.PointView])
def point_create(data: m.PointCreate, c=C):
    return response(c, library.create_point(c, data), 201)


@router.get("/points/{identity}", response_model=m.Envelope[m.PointView])
def point_get(identity: str, c=C):
    return response(c, library.point_view(c, identity))


@router.patch("/points/{identity}")
def point_edit(identity: str, data: m.PointEdit, c=C):
    return response(c, library.edit_entity(c, "knowledge_points", identity, data))


@router.post("/points/{identity}/archive")
def point_archive(identity: str, data: m.Expected, c=C):
    return response(c, library.archive(c, "knowledge_points", identity, data.expected_version))


@router.get("/search")
def search(query: str, subject_id: str | None = None, c=C):
    return response(c, page(library.search(c, query, subject_id)))


@router.get("/materials")
def materials(
    subject_id: str | None = None,
    state: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    query: str = "",
    c=C,
):
    return response(
        c,
        paginate(
            c,
            "materials",
            "(:sub IS NULL OR subject_id=:sub) AND (:state IS NULL OR state=:state) AND (:q='' OR instr(lower(title),lower(:q))>0)",
            {"sub": subject_id, "state": state, "q": query[:200]},
            limit,
            cursor,
        ),
    )


@router.post("/materials")
async def material_create(
    title: str = Form(...),
    subject_id: str | None = Form(None),
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    c=C,
):
    require((text is not None) != (file is not None), "INVALID_INPUT", "请选择一个文件或一段文字", 400)
    content = await file.read(c.rules()["storage"]["max_upload_bytes"] + 1) if file else text.encode("utf-8")
    return response(
        c, library.save_material(c, title, subject_id, content, file.filename if file else None), 201
    )


@router.get("/materials/{identity}")
def material_get(identity: str, c=C):
    return response(c, library.material_detail(c, identity))


def authorized_file(c, row, mime="application/octet-stream", name=None):
    path = controlled_path(c.db.settings.data_dir, row["relative_path"])
    require(
        path.is_file() and digest(path.read_bytes()) == row["sha256"],
        "FILE_CORRUPT",
        "文件缺失或损坏，无法下载",
    )
    return FileResponse(
        path,
        media_type=mime,
        filename=name or path.name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get("/materials/{identity}/file")
def material_file(identity: str, c=C):
    row = c.get("materials", identity)
    return authorized_file(c, row, row["media_type"])


@router.post("/materials/{identity}/confirm")
def material_confirm(identity: str, data: m.ConfirmMaterial, c=C):
    return response(c, library.confirm_material(c, identity, data))


@router.post("/materials/{identity}/retry")
def material_retry(identity: str, data: m.Expected, c=C):
    row = c.get("materials", identity)
    check_version(row, data.expected_version)
    require(row["state"] in {"failed", "needs_confirmation"}, message="材料无需重试")
    c.update("materials", identity, state="uploaded", version=row["version"] + 1, updated_at=c.now)
    job = jobs.enqueue(
        c, "parse_material", f"material:{identity}:parse:{row['version'] + 1}", {"material_id": identity}
    )
    return response(c, {"job_id": job["id"], "resource_id": identity}, 202)


@router.post("/materials/{identity}/generate-cards")
def generate_cards(identity: str, data: m.GenerateCards, c=C):
    c.get("materials", identity)
    for chunk_id in data.confirmed_chunk_ids:
        chunk = library.confirmed_chunk(c, chunk_id)
        require(chunk["material_id"] == identity, message="来源不属于此材料")
    config = providers.provider_for(c, "chat")
    job = jobs.enqueue(
        c,
        "generate_cards",
        f"cards:{identity}:{digest(dumps(data.model_dump()))}",
        {"material_id": identity, **data.model_dump(), "provider": config},
    )
    return response(c, {"job_id": job["id"]}, 202)


@router.get("/cards")
def cards(point_id: str | None = None, limit: int = 100, cursor: str | None = None, query: str = "", c=C):
    return response(
        c,
        paginate(
            c,
            "cards",
            "(:p IS NULL OR point_id=:p) AND is_verification=0 AND (:q='' OR instr(lower(question_json),lower(:q))>0) AND point_id IN (SELECT p.id FROM knowledge_points p WHERE "
            + library.ACTIVE_POINT_SQL
            + ")",
            {"p": point_id, "q": query[:200]},
            limit,
            cursor,
        ),
    )


@router.post("/cards")
def card_create(data: m.CardCreate, c=C):
    return response(c, library.create_card(c, data), 201)


@router.patch("/cards/{identity}")
def card_edit(identity: str, data: m.CardEdit, c=C):
    return response(c, library.edit_card(c, identity, data))


@router.get("/plans/{day}", response_model=m.Envelope[m.DailyPlan])
def plan_get(day: str, c=C):
    return response(c, plans.get_plan(c, day))


@router.put("/plans/{day}")
def plan_put(day: str, data: m.PlanEdit, c=C):
    plan = plans.writable_plan(c, day, data.expected_version)
    c.update("daily_plans", plan["id"], note=data.note)
    c.change("plan", "monitor", dates=[day])
    return response(c, plans.get_plan(c, day))


@router.post("/plans/{day}/tasks")
def plan_tasks(day: str, data: m.PlanTasks, c=C):
    plan = plans.writable_plan(c, day, data.expected_plan_version)
    for item in data.items:
        plans.create_task(c, item, plan)
    return response(c, plans.get_plan(c, day), 201)


@router.put("/plans/{day}/order")
def plan_order(day: str, data: m.PlanOrder, c=C):
    return response(c, plans.reorder(c, day, data))


@router.get("/tasks", response_model=m.Envelope[m.Page[m.TaskView]])
def tasks(limit: int = 100, cursor: str | None = None, query: str = "", c=C):
    return response(
        c,
        paginate(
            c,
            "study_tasks",
            "state!='archived' AND (:q='' OR instr(lower(title),lower(:q))>0)",
            params={"q": query[:200]},
            limit=limit,
            cursor=cursor,
            transform=lambda row: plans.task_view(c, row["id"]),
        ),
    )


@router.post("/tasks", response_model=m.Envelope[m.TaskView])
def task_create(data: m.TaskCreate, c=C):
    return response(c, plans.create_task(c, data), 201)


@router.get("/tasks/{identity}", response_model=m.Envelope[m.TaskView])
def task_get(identity: str, c=C):
    result = plans.task_view(c, identity)
    result["activities"] = [
        public(r)
        for r in c.all(
            "SELECT a.* FROM activities a JOIN learning_claims cl ON cl.id=a.claim_id WHERE cl.task_id=:id ORDER BY a.created_at DESC",
            {"id": identity},
        )
    ]
    return response(c, result)


@router.patch("/tasks/{identity}")
def task_edit(identity: str, data: m.TaskEdit, c=C):
    return response(c, plans.edit_task(c, identity, data))


@router.post("/tasks/{identity}/start")
def task_start(identity: str, data: m.Expected, c=C):
    return response(c, plans.start_task(c, identity, data.expected_version))


@router.post("/tasks/{identity}/complete")
def task_complete(identity: str, data: m.Expected, c=C):
    return response(c, plans.complete_personal(c, identity, data.expected_version))


@router.post("/tasks/{identity}/reopen")
def task_reopen(identity: str, data: m.Reopen, c=C):
    return response(c, plans.complete_personal(c, identity, data.expected_version, True, data.reason))


@router.post("/tasks/{identity}/archive")
def task_archive(identity: str, data: m.Expected, c=C):
    return response(c, plans.archive_task(c, identity, data.expected_version))


@router.post("/tasks/{identity}/replan")
def task_replan(identity: str, data: m.Replan, c=C):
    return response(c, plans.replan(c, identity, data))


@router.post("/timers")
def timer_create(data: m.TimerCreate, c=C):
    return response(c, plans.timer_create(c, data.task_id), 201)


@router.get("/timers/current")
def timer_current(c=C):
    row = c.one(
        "SELECT * FROM timer_sessions WHERE owner_id=:o AND state IN ('running','paused') ORDER BY (state='running') DESC,updated_at DESC LIMIT 1",
        {"o": c.owner},
    )
    return response(c, plans.timer_view(c, row))


@router.post("/timers/{identity}/{action}")
def timer_action(identity: str, action: str, data: m.Expected, c=C):
    require(action in {"pause", "resume", "stop"}, "RESOURCE_NOT_FOUND", "操作不存在", 404)
    return response(c, plans.timer_action(c, identity, action, data.expected_version))


@router.post("/activities")
def activity_create(data: m.ActivityCreate, c=C):
    return response(c, learning.create_activity(c, data), 201)


@router.get("/activities/{identity}")
def activity_get(identity: str, c=C):
    return response(c, learning.activity_detail(c, identity))


@router.patch("/activities/{identity}")
def activity_edit(identity: str, data: m.ActivityEdit, c=C):
    row = c.get("activities", identity)
    check_version(row, data.expected_version)
    if row["submitted_at"] is None:
        c.update(
            "activities",
            identity,
            narrative_md=data.narrative_md if data.narrative_md is not None else row["narrative_md"],
            version=row["version"] + 1,
            updated_at=c.now,
        )
        if data.narrative_md:
            c.insert(
                "evidence_items",
                id=uid(),
                activity_id=identity,
                kind="text",
                content_text=data.narrative_md,
                sha256=digest(data.narrative_md + uid()),
                created_at=c.now,
            )
        return response(c, learning.activity_detail(c, identity))
    claim = c.get("learning_claims", row["claim_id"])
    result = learning.create_activity(
        c,
        m.ActivityCreate(
            point_id=claim["point_id"],
            task_id=claim["task_id"],
            claim_id=claim["id"],
            template_code=claim["template_code"],
            narrative_md=data.narrative_md if data.narrative_md is not None else row["narrative_md"],
            evidence_ids=data.evidence_ids,
        ),
    )
    return response(c, result, 201)


@router.post("/activities/{identity}/submit")
def activity_submit(identity: str, data: m.Expected, c=C):
    return response(c, learning.submit(c, identity, data.expected_version), 202)


@router.post("/activities/{identity}/evidence")
def activity_evidence(identity: str, data: m.EvidenceCreate, c=C):
    return response(c, learning.add_evidence(c, identity, data))


@router.post("/assessments/{identity}/reassess")
def reassess(identity: str, data: m.Reassess, c=C):
    assessment = c.get("assessments", identity)
    claim = c.get("learning_claims", assessment["claim_id"])
    check_version(claim, data.expected_claim_version)
    activity = c.get("activities", assessment["activity_id"])
    for evidence_id in data.new_evidence_ids:
        evidence = c.get("evidence_items", evidence_id)
        associated = c.get("activities", evidence["activity_id"])
        require(associated["claim_id"] == claim["id"], message="补充证据不属于同一成果")
        activity = associated
    c.audit("assessment.reassess", "assessment", identity, {"reason": data.reason})
    return response(c, learning.submit(c, activity["id"], activity["version"]), 202)


@router.get("/wallet", response_model=m.Envelope[m.Wallet])
def wallet(c=C):
    return response(c, public(c.get("wallets", c.owner, key="owner_id")))


@router.get("/ledger", response_model=m.Envelope[m.Page[m.Receipt]])
@router.get("/monitor/ledger", response_model=m.Envelope[m.Page[m.Receipt]])
def ledger(
    category: str | None = None,
    start: str | None = Query(None, alias="from"),
    end: str | None = Query(None, alias="to"),
    limit: int = 20,
    cursor: str | None = None,
    c=C,
):
    return response(
        c,
        paginate(
            c,
            "ledger_entries",
            "(:cat IS NULL OR category=:cat) AND (:start IS NULL OR business_date>=:start) AND (:end IS NULL OR business_date<=:end)",
            {"cat": category, "start": start, "end": end},
            limit,
            cursor,
            "sequence DESC",
        ),
    )


@router.get("/ledger/{identity}")
def ledger_get(identity: str, c=C):
    return response(c, public(c.get("ledger_entries", identity)))


@router.get("/review/summary")
def review_summary(subject_id: str | None = None, c=C):
    return response(c, review.summary(c, subject_id))


@router.post("/review/rounds")
def review_create(data: m.ReviewRoundCreate, c=C):
    return response(c, review.start_round(c, data), 201)


@router.get("/review/rounds/{identity}")
def review_get(identity: str, c=C):
    return response(c, review.round_view(c, identity))


@router.post("/review/rounds/{identity}/advance")
def review_advance(identity: str, data: m.Expected, c=C):
    return response(c, review.advance(c, identity, data.expected_version))


@router.post("/review/rounds/{identity}/end")
def review_end(identity: str, data: m.Expected, c=C):
    return response(c, review.advance(c, identity, data.expected_version, True))


@router.get("/attempts/{identity}", response_model=m.Envelope[m.AttemptView])
def attempt_get(identity: str, c=C):
    return response(c, review.attempt_view(c, identity))


@router.post("/attempts/{identity}/reveal")
def attempt_reveal(identity: str, data: m.Expected, c=C):
    return response(c, review.reveal(c, identity, data.expected_version))


@router.post("/attempts/{identity}/answer")
def attempt_answer(identity: str, data: m.Answer, c=C):
    return response(c, review.answer(c, identity, data))


@router.post("/attempts/{identity}/rating")
def attempt_rating(identity: str, data: m.Rating, c=C):
    return response(c, review.rate(c, identity, data))


@router.post("/attempts/{identity}/reassess")
def attempt_reassess(identity: str, data: m.Regrade, c=C):
    from .review_corrections import reassess

    return response(c, reassess(c, identity, data), 202)


@router.get("/world")
def world_get(c=C):
    return response(c, world.world_view(c))


@router.get('/world/history', response_model=m.Envelope[m.WorldHistoryPage])
def world_history_get(
    date_from: str, date_to: str, region_id: str | None = None,
    cursor: str | None = Query(None, max_length=8192),
    limit: int = Query(20, ge=1, le=100), c=C,
):
    return response(c, world_history.history(c, date_from, date_to, region_id, cursor, limit))


@router.get("/world/regions/{identity}")
def region_get(
    identity: str, chapter_id: str | None = None, point_id: str | None = None, focus: str | None = None, c=C
):
    return response(c, world.region_view(c, identity, chapter_id, point_id=point_id, focus=focus))


@router.patch("/world/regions/{identity}/viewport")
def viewport(identity: str, data: m.Viewport, c=C):
    row = c.get("world_regions", identity)
    check_version(row, data.expected_version)
    c.update(
        "world_regions",
        identity,
        viewport_json=dumps(data.model_dump(exclude={"expected_version"})),
        version=row["version"] + 1,
    )
    return response(c, public(c.get("world_regions", identity)))


@router.get("/world/plots/{identity}")
def plot_get(identity: str, c=C):
    row = world.owned_plot(c, identity)
    point = library.point_view(c, row["point_id"]) if row["point_id"] else None
    return response(c, {**public(row), "point": point})


@router.post("/world/plots/{identity}/plant")
def plant(identity: str, data: m.PlantSeed, c=C):
    return response(c, world.plant(c, identity, data))


@router.post("/plants/{identity}/harvest")
def harvest(identity: str, data: m.Expected, c=C):
    return response(c, world.harvest(c, identity, data.expected_version))


@router.get("/inventory")
def inventory(
    kind: str | None = None, state: str | None = None, limit: int = 100, cursor: str | None = None, c=C
):
    return response(
        c,
        paginate(
            c,
            "inventory_items i JOIN catalog_items cat ON cat.code=i.catalog_code",
            "(:kind IS NULL OR cat.kind=:kind) AND (:state IS NULL OR i.state=:state)",
            {"kind": kind, "state": state},
            limit,
            cursor,
            "i.created_at DESC,i.id",
        ),
    )


@router.post("/inventory/{identity}/place")
def item_place(identity: str, data: m.PlaceItem, c=C):
    return response(c, world.place(c, identity, data))


@router.post("/inventory/{identity}/store")
def item_store(identity: str, data: m.Expected, c=C):
    row = c.get("inventory_items", identity)
    check_version(row, data.expected_version)
    require(row["state"] == "placed", message="此道具未摆放")
    c.update(
        "inventory_items",
        identity,
        state="owned",
        placed_plot_id=None,
        placement_json=None,
        version=row["version"] + 1,
    )
    c.change("world")
    return response(c, public(c.get("inventory_items", identity)))


@router.post("/inventory/{identity}/equip")
def item_equip(identity: str, data: m.EquipItem, c=C):
    item = c.get("inventory_items", identity)
    check_version(item, data.expected_version)
    companion = c.get("companions", data.companion_id)
    require(companion["affinity"] > 0, message="先和苔苔打一次招呼，再为它穿上围巾")
    require(
        item["catalog_code"] == "companion_outfit" and item["state"] in {"owned", "equipped"},
        message="此道具不是可穿戴外观",
    )
    if companion["outfit_item_id"]:
        old = c.get("inventory_items", companion["outfit_item_id"])
        c.update("inventory_items", old["id"], state="owned", version=old["version"] + 1)
    c.update("inventory_items", identity, state="equipped", version=item["version"] + 1)
    c.update("companions", companion["id"], outfit_item_id=identity, version=companion["version"] + 1)
    return response(c, world.companion(c))


@router.get("/companion")
def companion(c=C):
    return response(c, world.companion(c))


@router.post("/companion/interactions")
def interact(data: m.Interact, c=C):
    return response(c, world.interact(c))


@router.get("/achievements")
def achievements(c=C):
    return response(
        c,
        {
            "grants": [
                public(r)
                for r in c.all(
                    "SELECT * FROM achievement_grants WHERE owner_id=:o ORDER BY created_at", {"o": c.owner}
                )
            ],
            "conditions": {
                "first_verified_learning": "第一次有证据的独立运用",
                "first_consolidated_point": "第一次稳定巩固",
                "first_chapter_landmark": f"章节中至少 {c.rules()['world']['chapter_landmark_consolidated_percent']}% 的有效知识稳定巩固",
            },
        },
    )


@router.get("/habits")
def habits(day: str | None = Query(None, alias="date"), c=C):
    return response(c, routines.habits_view(c, day or c.today))


@router.post("/habit-plans")
def habit_create(data: m.HabitCreate, c=C):
    return response(c, routines.create_plan(c, data), 201)


@router.post("/habit-plans/{identity}/revisions")
def habit_revise(identity: str, data: m.HabitRevision, c=C):
    return response(c, routines.revise(c, identity, data))


@router.post("/habit-plans/{identity}/archive")
def habit_archive(identity: str, data: m.Expected, c=C):
    return response(c, library.archive(c, "habit_plans", identity, data.expected_version))


@router.put("/habit-plans/{identity}/rest-days/{day}")
def set_rest(identity: str, day: str, c=C):
    return response(c, routines.rest_day(c, identity, day))


@router.delete("/habit-plans/{identity}/rest-days/{day}")
def delete_rest(identity: str, day: str, c=C):
    return response(c, routines.rest_day(c, identity, day, True))


@router.post("/habit-occurrences/{identity}/complete")
def habit_complete(identity: str, data: m.HabitComplete, c=C):
    return response(c, routines.complete_custom(c, identity, data))


@router.post("/checkins")
def checkin(c=C):
    return response(c, routines.checkin(c))


@router.post("/checkins/{identity}/complete")
def checkin_complete(identity: str, data: m.CheckinComplete, c=C):
    return response(c, routines.complete_checkin(c, identity, data))


@router.get("/screen-time")
def screen_time(day: str | None = Query(None, alias="date"), c=C):
    return response(c, routines.screen_view(c, day or c.today))


@router.post("/screen-time/{day}/records")
def screen_record(day: str, data: m.ScreenRecord, c=C):
    return response(c, routines.record_screen(c, day, data))


@router.get("/commitments")
def commitment_list(state: str | None = None, limit: int = 20, cursor: str | None = None, c=C):
    return response(
        c,
        paginate(
            c,
            "commitments",
            "(:state IS NULL OR state=:state)",
            {"state": state},
            limit,
            cursor,
            transform=lambda r: commitments.detail(c, r["id"]),
        ),
    )


@router.post("/commitments/proposals")
def commitment_proposal(data: m.CommitmentProposal, c=C):
    return response(c, commitments.proposal(c, data), 201)


@router.get("/commitments/{identity}")
def commitment_get(identity: str, c=C):
    return response(c, commitments.detail(c, identity))


@router.post("/commitments/{identity}/accept")
def commitment_accept(identity: str, data: m.AcceptTerms, c=C):
    return response(c, commitments.accept(c, identity, data))


@router.post("/commitments/{identity}/cancel-proposal")
def commitment_cancel(identity: str, data: m.Expected, c=C):
    row = c.get("commitments", identity)
    check_version(row, data.expected_version)
    require(row["state"] == "proposed", message="只能取消未接受的提案")
    c.update("commitments", identity, state="cancelled", version=row["version"] + 1)
    return response(c, commitments.detail(c, identity))


@router.post("/commitments/{identity}/abandon")
def commitment_abandon(identity: str, data: m.AcceptTerms, c=C):
    row = c.get("commitments", identity)
    check_version(row, data.expected_version)
    require(data.terms_hash == digest(row["terms_json"]), "TERMS_CHANGED", "条款已变化")
    return response(c, commitments.evaluate(c, identity, True))


@router.get("/catalog")
def catalog(kind: str | None = None, c=C):
    rows = c.all(
        "SELECT * FROM catalog_items WHERE enabled=1 AND (:k IS NULL OR kind=:k) ORDER BY price_coins,code",
        {"k": kind},
    )
    for row in rows:
        row["available"] = True
        if row["kind"] in {"image", "chapter"}:
            try:
                providers.provider_for(c, "image" if row["kind"] == "image" else "chat")
            except DomainError:
                row["available"] = False
    return response(c, page([public(r) for r in rows]))


@router.post("/redemption-quotes")
def redemption_quote(data: m.Quote, c=C):
    return response(c, rewards.quote(c, data))


@router.post("/redemptions")
def redemption_create(data: m.Redeem, c=C):
    return response(c, rewards.redeem(c, data.quote_token), 201)


@router.get("/redemptions")
def redemption_list(limit: int = 20, cursor: str | None = None, c=C):
    return response(
        c,
        paginate(
            c,
            "redemptions",
            limit=limit,
            cursor=cursor,
            transform=lambda r: rewards.redemption_detail(c, r["id"]),
        ),
    )


@router.get("/redemptions/{identity}")
def redemption_get(identity: str, c=C):
    return response(c, rewards.redemption_detail(c, identity))


@router.post("/redemptions/{identity}/retry")
def redemption_retry(identity: str, data: m.Expected, c=C):
    return response(c, rewards.retry(c, identity, data.expected_version))


@router.post("/redemptions/{identity}/cancel")
def redemption_cancel(identity: str, data: m.Expected, c=C):
    return response(c, rewards.cancel(c, identity, data.expected_version))


@router.get("/assets")
def assets(
    kind: str | None = None, favorite: bool | None = None, limit: int = 20, cursor: str | None = None, c=C
):
    return response(
        c,
        paginate(
            c,
            "generated_assets",
            "(:k IS NULL OR kind=:k) AND (:f IS NULL OR favorite=:f)",
            {"k": kind, "f": favorite},
            limit,
            cursor,
        ),
    )


@router.get("/assets/{identity}/file")
def asset_file(identity: str, c=C):
    row = c.get("generated_assets", identity)
    return authorized_file(c, row, row["mime_type"])


@router.patch("/assets/{identity}")
def asset_favorite(identity: str, data: m.Favorite, c=C):
    row = c.get("generated_assets", identity)
    check_version(row, data.expected_version)
    c.update("generated_assets", identity, favorite=int(data.favorite), version=row["version"] + 1)
    return response(c, public(c.get("generated_assets", identity)))


@router.get("/stories")
def stories(limit: int = 20, cursor: str | None = None, c=C):
    return response(c, paginate(c, "story_series", limit=limit, cursor=cursor))


@router.post("/stories")
def story_create(data: m.StoryCreate, c=C):
    row = c.insert(
        "story_series",
        id=uid(),
        owner_id=c.owner,
        title=data.title,
        bible_json=dumps(data.bible),
        created_at=c.now,
        updated_at=c.now,
    )
    return response(c, public(c.get("story_series", row["id"])), 201)


@router.get("/stories/{identity}")
def story_get(identity: str, c=C):
    row = c.get("story_series", identity)
    return response(
        c,
        {
            **public(row),
            "chapters": [
                public(r)
                for r in c.all(
                    "SELECT * FROM story_chapters WHERE series_id=:id ORDER BY number", {"id": identity}
                )
            ],
        },
    )


@router.patch("/stories/{identity}")
def story_edit(identity: str, data: m.StoryEdit, c=C):
    row = c.get("story_series", identity)
    check_version(row, data.expected_version)
    c.update(
        "story_series",
        identity,
        title=data.title or row["title"],
        bible_json=dumps(data.bible) if data.bible is not None else row["bible_json"],
        bible_version=row["bible_version"] + int(data.bible is not None),
        version=row["version"] + 1,
        updated_at=c.now,
    )
    return response(c, public(c.get("story_series", identity)))


@router.get("/stories/{identity}/chapters/{number}")
def story_chapter(identity: str, number: int, c=C):
    c.get("story_series", identity)
    row = c.one(
        "SELECT * FROM story_chapters WHERE series_id=:id AND number=:n", {"id": identity, "n": number}
    )
    require(row is not None, "RESOURCE_NOT_FOUND", "章节不存在", 404)
    return response(c, public(row))


@router.get("/stories/{identity}/export")
def story_export(identity: str, format: str = "md", c=C):
    row = c.get("story_series", identity)
    require(format in {"md", "txt"}, "INVALID_INPUT", "不支持的导出格式", 400)
    chapters = c.all(
        "SELECT * FROM story_chapters WHERE series_id=:id AND state='ready' ORDER BY number", {"id": identity}
    )
    content = (
        "# "
        + row["title"]
        + "\n\n"
        + "\n\n".join(f"## {r['number']}. {r['title']}\n\n{r['body_md']}" for r in chapters)
    )
    return Response(
        content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="story.{format}"'},
    )


@router.get("/monitor/summary")
def monitor_summary(
    start: str = Query(..., alias="from"),
    end: str = Query(..., alias="to"),
    selected_date: str | None = None,
    subject_id: str | None = None,
    c=C,
):
    return response(c, reporting.summary(c, start, end, selected_date, subject_id))


@router.get("/monitor/series")
def monitor_series(
    start: str = Query(..., alias="from"),
    end: str = Query(..., alias="to"),
    subject_id: str | None = None,
    c=C,
):
    return response(c, reporting.series(c, start, end, subject_id))


@router.get("/monitor/days/{day}")
def monitor_day(day: str, subject_id: str | None = None, limit: int = 100, cursor: str | None = None, c=C):
    return response(c, reporting.day_detail(c, day, subject_id, limit, cursor))


@router.get("/archive")
def archive(
    start: str = Query(..., alias="from"),
    end: str = Query(..., alias="to"),
    subject_id: str | None = None,
    timer_cursor: str | None = None,
    c=C,
):
    return response(c, reporting.archive(c, start, end, subject_id, timer_cursor))


@router.post("/reports")
def report_create(data: m.ReportCreate, c=C):
    inputs, hash_value = reporting.report_input(c, data.start_date, data.end_date)
    existing = c.one(
        "SELECT * FROM study_reports WHERE owner_id=:o AND period_kind=:k AND start_date=:s AND end_date=:e AND input_hash=:h",
        {"o": c.owner, "k": data.period_kind, "s": data.start_date, "e": data.end_date, "h": hash_value},
    )
    if existing:
        return response(c, {"report_id": existing["id"], "state": "succeeded"})
    provider = providers.provider_for(c, "chat")
    job = jobs.enqueue(
        c,
        "report",
        f"report:{c.owner}:{data.period_kind}:{data.start_date}:{data.end_date}:{hash_value}",
        {**data.model_dump(), "input": inputs, "input_hash": hash_value, "provider": provider},
    )
    return response(c, {"job_id": job["id"]}, 202)


@router.get("/reports/{identity}")
def report_get(identity: str, c=C):
    return response(c, public(c.get("study_reports", identity)))


@router.get("/jobs")
def job_list(limit: int = 20, cursor: str | None = None, c=C):
    return response(c, paginate(c, "jobs", limit=limit, cursor=cursor, transform=lambda row: jobs.job_summary(c, row)))


@router.get("/jobs/{identity}")
def job_get(identity: str, c=C):
    return response(c, jobs.job_view(c, identity))


@router.post("/jobs/{identity}/retry")
def job_retry(identity: str, data: m.RetryJob, c=C):
    return response(c, jobs.retry_job(c, identity, data.expected_state))


@router.get("/jobs/{identity}/events")
def job_events(identity: str, request: Request, c=C):
    c.get("jobs", identity)
    db, owner = c.db, c.owner
    try:
        last = int(request.headers.get("last-event-id", request.query_params.get("after", "0")))
    except ValueError:
        raise DomainError("INVALID_INPUT", "事件游标无效", 400)

    async def events():
        cursor = last
        while True:
            if await request.is_disconnected():
                break
            with db.transaction(owner=owner) as current:
                job = current.get("jobs", identity)
                rows = current.all(
                    "SELECT * FROM job_events WHERE job_id=:id AND id>:cursor ORDER BY id LIMIT 100",
                    {"id": identity, "cursor": cursor},
                )
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {row['payload_json']}\n\n"
            if job["state"] in {"succeeded", "failed", "needs_review", "cancelled"} and len(rows) < 100:
                break
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/notifications")
def notifications(unread_only: bool = False, limit: int = 20, cursor: str | None = None, c=C):
    return response(
        c,
        paginate(
            c, "notifications", "(:unread=0 OR read_at IS NULL)", {"unread": unread_only}, limit, cursor
        ),
    )


@router.post("/notifications/{identity}/read")
def notification_read(identity: str, c=C):
    row = c.get("notifications", identity)
    if row["read_at"] is None:
        c.update("notifications", identity, read_at=c.now)
    return response(c, public(c.get("notifications", identity)))


@router.get("/agent/threads")
def threads(c=C):
    return response(c, paginate(c, "agent_threads", limit=100, order="updated_at DESC,id"))


@router.post("/agent/threads")
def thread_create(data: m.ThreadCreate, c=C):
    from .agent import create_thread

    return response(c, create_thread(c, data), 201)


@router.get("/agent/threads/{identity}")
def thread_get(identity: str, c=C):
    from .agent import thread_detail

    return response(c, thread_detail(c, identity))


@router.post("/agent/threads/{identity}/messages")
def message_create(identity: str, data: m.MessageCreate, c=C):
    from .agent import add_message

    return response(c, add_message(c, identity, data), 202)


@router.post("/agent/messages/{identity}/resume")
def message_resume(identity: str, c=C):
    from .agent import resume_message

    return response(c, resume_message(c, identity), 202)


@router.post("/agent/actions/{identity}/confirm")
def action_confirm(identity: str, data: m.ActionConfirm, c=C):
    from .agent import confirm_action

    return response(c, confirm_action(c, identity, data.action_hash))


@router.post("/agent/runs/{identity}/cancel")
def agent_cancel(identity: str, c=C):
    run = c.get("agent_runs", identity)
    c.update("agent_runs", identity, state="cancelled", completed_at=c.now)
    if run["job_id"]:
        c.execute(
            "UPDATE jobs SET state='cancelled',lease_token=lease_token+1 WHERE id=:id AND state NOT IN ('succeeded','failed')",
            {"id": run["job_id"]},
        )
    return response(c, {"cancelled": True})


@router.post("/backups")
def backup_create(c=C):
    row = c.insert("backup_records", id=uid(), owner_id=c.owner, state="queued", created_at=c.now)
    job = jobs.enqueue(c, "backup", f"backup:{row['id']}", {"backup_id": row["id"]})
    return response(c, {"backup_id": row["id"], "job_id": job["id"]}, 202)


@router.get("/backups")
def backups(c=C):
    return response(c, paginate(c, "backup_records", limit=100))


@router.get("/backups/{identity}/file")
def backup_file(identity: str, c=C):
    row = c.get("backup_records", identity)
    require(row["state"] == "ready", message="备份尚未完成")
    return authorized_file(c, row, "application/zip")


@router.post("/restore-previews")
async def restore_preview(file: UploadFile = File(...), c=C):
    from .backup import preview

    result = await run_in_threadpool(preview, c.db.settings, await file.read(512 * 1024 * 1024 + 1))
    token = rewards.signer(c.db.settings).dumps(
        {"owner_id": c.owner, "preview_id": result["preview_id"], "kind": "restore"}
    )
    return response(c, {**result, "preview_token": token})


@router.post("/restores")
def restore(data: m.Restore, c=C):
    from itsdangerous import BadSignature, SignatureExpired

    try:
        token = rewards.signer(c.db.settings).loads(data.preview_token, max_age=1800)
    except (BadSignature, SignatureExpired):
        raise DomainError("QUOTE_EXPIRED", "恢复预检已过期或无效")
    require(
        token.get("kind") == "restore" and token["owner_id"] == c.owner,
        "RESOURCE_NOT_FOUND",
        "恢复预览不存在",
        404,
    )
    c.audit("restore.confirm", "restore", token["preview_id"])
    job = jobs.enqueue(c, "restore", f"restore:{token['preview_id']}", {"preview_id": token["preview_id"]})
    return response(c, {"job_id": job["id"], "requires_login_after_restore": True}, 202)


@router.get("/diagnostics")
def diagnostics(c=C):
    import sqlite3
    from .economy import reconcile

    return response(
        c,
        {
            "sqlite_version": sqlite3.sqlite_version,
            "journal_mode": c.scalar("PRAGMA journal_mode"),
            "reconciliation": reconcile(c),
            "schema_version": c.scalar("SELECT version_num FROM alembic_version"),
        },
    )


@router.get("/exports")
def export(format: str = "json", scope: str = "learning", c=C):
    from .exports import export_data

    body, mime = export_data(c, format, scope)
    return Response(
        body,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="knowledge-world-{scope}.{format}"'},
    )


def create_app(settings: Settings | None = None, clock=None):
    settings = settings or Settings()
    db = Database(settings, **({"clock": clock} if clock else {}))

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(db.migrate)
        # Environment credentials are referenced, not copied into the database.
        with db.transaction(True) as c:
            profile = c.one("SELECT * FROM profiles LIMIT 1")
            if profile:
                c.owner = profile["id"]
                for role in ("chat", "vision", "image"):
                    prefix = f"AI_{role.upper()}_"
                    if (
                        os.getenv(prefix + "BASE_URL")
                        and os.getenv(prefix + "MODEL")
                        and not c.scalar(
                            "SELECT count(*) FROM provider_configs WHERE owner_id=:o AND role=:r",
                            {"o": c.owner, "r": role},
                        )
                    ):
                        providers.configure(
                            c,
                            role,
                            m.ProviderConfig(
                                base_url=os.environ[prefix + "BASE_URL"],
                                model=os.environ[prefix + "MODEL"],
                                secret_env=prefix + "API_KEY",
                            ),
                        )
        yield
        db.engine.dispose()

    app = FastAPI(title="知识世界 API", version="0.1.0", lifespan=lifespan)
    app.state.db = db
    app.state.login_attempts = {}
    app.include_router(router)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        )
        return response

    dist = ROOT / "frontend/dist"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="web-assets")
    if (dist / "world-art").is_dir():
        app.mount("/world-art", StaticFiles(directory=dist / "world-art"), name="world-art")
    if (dist / "licenses").is_dir():
        app.mount("/licenses", StaticFiles(directory=dist / "licenses"), name="licenses")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"error": {"code": "RESOURCE_NOT_FOUND", "message": "接口不存在"}}, 404)
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return JSONResponse({"message": "前端尚未构建，请运行 scripts/dev.ps1 或先构建前端。"})

    return app


app = create_app()
