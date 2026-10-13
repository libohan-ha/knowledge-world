import asyncio


import base64


import json


import logging


import os


import secrets


from typing import Annotated


from uuid import UUID


from contextlib import asynccontextmanager


from fastapi import APIRouter, Depends, FastAPI, File, Query, Request, UploadFile


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


from .common import DomainError, require, uid, dumps, digest, public, page, iso


from . import models as m
from . import game_models as g
from .signing import signer
from .core_api import register


from . import (
    identity,
    providers,
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
            materializing_read = request.url.path in {"/api/v1/system/checkin", "/api/v1/system/checkin/settings"}
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
            except OperationalError as exc:
                await run_in_threadpool(session.rollback)
                if "locked" in str(exc.orig).lower() or "busy" in str(exc.orig).lower():
                    return error_response(DomainError("DATABASE_BUSY", "数据库正忙，请稍后重试", 503), rid)
                logger.error("database_operation_failed request_id=%s type=%s", rid, type(exc.orig).__name__)
                return error_response(DomainError("DATABASE_ERROR", "数据库操作未完成，未提交本次变更", 500), rid)
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


@router.get("/settings", response_model=m.Envelope[g.AppSettings])
def settings(c=C):
    import sqlite3

    return response(
        c,
        {
            "profile": identity.profile_view(c),
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


@router.get("/rules", response_model=m.Envelope[g.RulesView])
def rules(c=C):
    return response(
        c,
        {
            "rules": c.rules(),
            "locked_paths": [
                "wager.max_active",
                "wager.max_acceptances_per_local_day",
                "currency.convert_legacy_learning_points",
            ],
        },
    )


@router.post("/rules/versions")
def rule_version(data: m.RuleChange, c=C):
    current = c.rules()
    require(current["version"] == data.based_on_version, "VERSION_CONFLICT", "规则版本已更新")
    allowed = {
        "system.daily_positive_action_cap",
        "system.max_award_per_action",
        "system.daily_penalty_cap",
        "system.max_penalty_per_action",
    }
    require(set(data.changes) <= allowed, "INVALID_INPUT", "只支持声明的数值规则修改", 400)
    for key, value in data.changes.items():
        require(type(value) is int and 0 <= value <= 10000, "INVALID_INPUT", "规则数值无效", 400)
        group, name = key.split(".")
        current[group][name] = value
    current["version"] = "system-core-" + c.today + "." + uid()[:8]
    c.execute("UPDATE rule_versions SET is_active=0 WHERE is_active=1")
    c.insert(
        "rule_versions", id=current["version"], payload_json=dumps(current), is_active=1, created_at=c.now
    )
    c.audit("rules.publish", "rule_version", current["version"], {"changes": data.changes})
    from .core_rules import ensure_catalog
    ensure_catalog(c, current)
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


@router.post("/providers/chat/models", response_model=m.Envelope[m.ModelList])
def provider_models(data: m.ModelDiscovery, c=C):
    result = response(c, providers.discover_models(c, data))
    result.headers["Cache-Control"] = "no-store"
    return result


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


@router.get("/assets/{identity}/file")
def legacy_asset_file(identity: str, c=C):
    row = c.get("generated_assets", identity)
    return authorized_file(c, row, row["mime_type"])


@router.get("/jobs", response_model=m.Envelope[m.Page[g.BackgroundJob]])
def job_list(limit: int = 20, cursor: str | None = None, c=C):
    return response(c, paginate(c, "jobs", limit=limit, cursor=cursor, transform=lambda row: jobs.job_summary(c, row)))


@router.get("/jobs/{identity}", response_model=m.Envelope[g.BackgroundJob])
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


@router.get("/notifications", response_model=m.Envelope[m.Page[g.Notification]])
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


@router.get("/system/threads", response_model=m.Envelope[m.Page[g.AgentThread]])
def threads(c=C):
    return response(c, paginate(c, "agent_threads", limit=100, order="updated_at DESC,id"))


@router.post("/system/threads", response_model=m.Envelope[g.AgentThread])
def thread_create(data: m.ThreadCreate, c=C):
    from .agent import create_thread

    return response(c, create_thread(c, data), 201)


@router.get("/system/threads/{identity}", response_model=m.Envelope[g.AgentThread])
def thread_get(identity: str, c=C):
    from .agent import thread_detail

    return response(c, thread_detail(c, identity))


@router.post("/system/threads/{identity}/messages", response_model=m.Envelope[g.MessageReceipt])
def message_create(identity: str, data: m.MessageCreate, c=C):
    from .agent import add_message

    return response(c, add_message(c, identity, data), 202)


@router.post("/system/messages/{identity}/resume", response_model=m.Envelope[g.MessageReceipt])
def message_resume(identity: str, c=C):
    from .agent import resume_message

    return response(c, resume_message(c, identity), 202)


@router.post("/system/actions/{identity}/confirm")
def action_confirm(identity: str, data: m.ActionConfirm, c=C):
    from .agent import confirm_action

    return response(c, confirm_action(c, identity, data.action_hash))


@router.post("/system/actions/{identity}/decline")
def action_decline(identity: str, c=C):
    from .agent import decline_action

    return response(c, decline_action(c, identity))


@router.post("/system/runs/{identity}/cancel")
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
    token = signer(c.db.settings).dumps(
        {"owner_id": c.owner, "preview_id": result["preview_id"], "kind": "restore"}
    )
    return response(c, {**result, "preview_token": token})


@router.post("/restores")
def restore(data: m.Restore, c=C):
    from itsdangerous import BadSignature, SignatureExpired

    try:
        token = signer(c.db.settings).loads(data.preview_token, max_age=1800)
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
def export(format: str = "json", scope: str = "all", c=C):
    from .exports import export_data

    body, mime = export_data(c, format, scope)
    return Response(
        body,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="knowledge-world-{scope}.{format}"'},
    )


register(router, C, response, paginate)


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
        from .availability import heartbeat
        process_id = uid()
        await run_in_threadpool(heartbeat, db, process_id)

        async def observe_availability():
            while True:
                await asyncio.sleep(15)
                if not (settings.data_dir / ".maintenance").exists():
                    try:
                        await run_in_threadpool(heartbeat, db, process_id)
                    except Exception:
                        logging.getLogger(__name__).exception("API availability observation failed")

        observer = asyncio.create_task(observe_availability())
        try:
            yield
        finally:
            observer.cancel()
            try:
                await observer
            except asyncio.CancelledError:
                pass
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
