"""Shiyi's read-only adapter. Remote facts never enter the learning ledger."""

import base64
import io
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from email.message import Message
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import keyring
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, StrictBool

from .common import DomainError, check_version, digest, dumps, iso, public, require, uid
from .models import Input, Expected, View
from .providers import resolve_secret
from .signing import signer
from .vendor.shiyi.shiyi_api import normalize_url, ClientError, redact
from .vendor.shiyi.shiyi_tools import TOOLS, call_tool, validate_arguments

TOOL_NAMES = frozenset(entry["function"]["name"] for entry in TOOLS)
SUBJECTS = Literal["408", "math", "english"]
IMAGE_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP", "image/gif": "GIF"}


class ConnectionConfig(Expected):
    api_url: str = Field(max_length=2048)
    enabled: StrictBool = False
    api_key: str | None = Field(default=None, max_length=4096)
    secret_env: str | None = Field(default=None, max_length=128)
    new_connection: StrictBool = False


class ContextQuery(Input):
    refresh: bool = False


class PageQuery(ContextQuery):
    limit: int = Field(default=10, ge=1, le=20)
    cursor: str | None = Field(default=None, max_length=4096)
    subject: SUBJECTS | None = None


class ReviewsQuery(PageQuery):
    item_id: UUID | None = None
    rating: Literal["again", "hard", "good", "easy"] | None = None
    independent_completed: bool | None = None
    has_blocker: bool | None = None
    date_from: date | None = None
    date_to: date | None = None


class DueQuery(ContextQuery):
    subject: SUBJECTS | None = None
    limit: int = Field(default=10, ge=1, le=20)


class WeaknessesQuery(PageQuery):
    days: int = Field(default=30, ge=1, le=365)


class SearchQuery(PageQuery):
    q: str | None = Field(default=None, max_length=200)
    source_item_id: UUID | None = None


class ItemQuery(Input):
    include_answer: bool = False


class ShiyiConnection(BaseModel):
    id: str
    api_url: str
    enabled: bool
    version: int
    has_key: bool
    readable: bool
    checked_at: str | None
    last_success_at: str | None
    last_error_code: str | None
    capabilities: dict[str, Any]


class ShiyiConnectionResult(BaseModel):
    connection: ShiyiConnection | None
    job_id: str | None = None


class ShiyiSource(BaseModel):
    system: Literal["shiyi"] = "shiyi"
    connection_id: str
    connection_version: int
    fetched_at: str
    timezone: str
    study_date: str
    freshness: Literal["live"] = "live"
    source_server_time: str | None


class ShiyiContext(View):
    agent_api_version: int
    study_date: str
    timezone: str
    permissions: list[str]
    summary: dict[str, Any]
    source: ShiyiSource


class ShiyiPage(View):
    items: list[dict[str, Any]]
    next_cursor: str | None
    source_total: int
    source: ShiyiSource


class ShiyiReviewItem(View):
    id: str
    title: str
    subject: SUBJECTS
    kind: str
    status: str


class ShiyiReview(View):
    id: str
    item: ShiyiReviewItem
    rating: int
    independent_completed: bool | None
    duration_ms: int | None = None
    reviewed_at: str
    blocker: str | None = None
    was_new: bool | None = None
    undone: bool = False


class ShiyiReviews(ShiyiPage):
    items: list[ShiyiReview]


class ShiyiDue(View):
    items: list[dict[str, Any]]
    due_count: int
    new_count: int
    source: ShiyiSource


class ShiyiItem(View):
    id: str
    title: str
    question: str = ""
    question_media: list[str] = Field(default_factory=list)
    answer: str | None = None
    answer_media: list[str] = Field(default_factory=list)
    source: ShiyiSource


def query_arguments(query):
    args = query.model_dump(mode="json", exclude_none=True)
    cursor = args.pop("cursor", None)
    args.pop("refresh", None)  # All queries are live; no stale fallback.
    if isinstance(query, PageQuery):
        args["page_size"] = args.pop("limit")
    return args, cursor


def valid_arguments(name, arguments):
    try:
        args = validate_arguments(name, arguments)
        require(args.get("page", 1) <= 100000, "INVALID_INPUT", "拾忆分页范围过大，请缩小日期范围", 400)
        return args
    except (ValueError, TypeError):
        raise DomainError("INVALID_INPUT", "拾忆查询参数不符合约定", 400) from None


class ReadOnlyClient:
    """Use the licensed tool dispatcher with bounded, fixed-origin GET requests."""

    def __init__(self, url, key, transport=None):
        require(bool(key), "SHIYI_NOT_CONFIGURED", "拾忆服务端凭据不可读取", 409)
        self.api_url, self.key = normalize_url(url), key
        self.http = httpx.Client(timeout=10, follow_redirects=False, trust_env=False, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.http.close()

    def download(self, path, query=None, health=False):
        allowed = {"/agent/context", "/agent/reviews", "/agent/weaknesses", "/reviews/due", "/items"}
        require(
            path in allowed
            or re.fullmatch(r"/(items|media)/[0-9a-fA-F-]{36}", path)
            or health
            and path == "/api/health",
            "ACTION_NOT_ALLOWED",
            "拾忆连接仅允许预定义的读取路径",
            403,
        )
        url = (self.api_url[:-7] if health else self.api_url) + path
        try:
            with self.http.stream(
                "GET",
                url,
                params={
                    k: str(v).lower() if isinstance(v, bool) else v
                    for k, v in (query or {}).items()
                    if v is not None
                },
                headers={} if health else {"Authorization": "Bearer " + self.key},
            ) as response:
                if response.status_code == 401:
                    raise DomainError("SHIYI_AUTH_FAILED", "拾忆凭据已失效，请在连接设置中重新配置", 424)
                if response.status_code == 403:
                    raise DomainError("SHIYI_SCOPE_MISSING", "拾忆凭据没有读取权限", 424)
                if response.status_code == 404 and path == "/agent/context":
                    raise DomainError("SHIYI_API_UNSUPPORTED", "拾忆尚不支持 Agent API v1，请升级源站", 424)
                if response.status_code == 404:
                    raise DomainError("SHIYI_RECORD_NOT_FOUND", "拾忆记录不存在或已不可读取", 404)
                if response.status_code == 429:
                    retry = response.headers.get("retry-after", "")
                    raise DomainError(
                        "SHIYI_RATE_LIMITED",
                        "拾忆暂时限流，请稍后刷新",
                        429,
                        retry_after=int(retry) if retry.isdecimal() else None,
                    )
                require(
                    not response.is_redirect,
                    "SHIYI_UNAVAILABLE",
                    "拾忆地址发生重定向，请在设置中填写源站最终地址",
                    503,
                )
                require(
                    response.status_code == 200,
                    "SHIYI_UNAVAILABLE",
                    "拾忆服务当前不可用，未返回有效数据",
                    503,
                )
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    require(
                        size <= 2 * 1024 * 1024,
                        "SHIYI_INVALID_RESPONSE",
                        "拾忆响应超过读取上限，请缩小范围",
                        502,
                    )
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", "").split(";")[0]
        except httpx.TimeoutException:
            raise DomainError("SHIYI_TIMEOUT", "读取拾忆超时，原有本地记录不受影响", 504) from None
        except httpx.HTTPError:
            raise DomainError("SHIYI_UNAVAILABLE", "无法连接拾忆，请检查地址与服务状态", 503) from None

    def request(self, method, path, *, query=None, **kwargs):
        require(method == "GET" and not kwargs, "ACTION_NOT_ALLOWED", "拾忆连接不允许写入", 403)
        blob, mime = self.download(path, query)
        require(
            mime == "application/json" or mime.endswith("+json"),
            "SHIYI_INVALID_RESPONSE",
            "拾忆未返回 JSON 数据",
            502,
        )
        return self.decode(blob)

    def decode(self, blob):
        try:
            result = redact(json.loads(blob), self.key)
        except (ValueError, UnicodeDecodeError):
            raise DomainError("SHIYI_INVALID_RESPONSE", "拾忆未返回有效 JSON", 502) from None
        require(isinstance(result, dict), "SHIYI_INVALID_RESPONSE", "拾忆响应结构无效", 502)
        return result

    @contextmanager
    def open(self, method, path):
        require(
            method == "GET" and path.startswith("/media/"), "ACTION_NOT_ALLOWED", "仅允许读取指定图片", 403
        )
        blob, mime = self.download(path)
        validate_image(blob, mime)
        with io.BytesIO(blob) as result:
            result.headers = Message()
            result.headers["Content-Type"] = mime
            yield result


def validate_image(blob, mime):
    require(
        mime in IMAGE_TYPES and bool(blob), "SHIYI_INVALID_RESPONSE", "拾忆图片格式不受支持或内容为空", 502
    )
    try:
        with Image.open(io.BytesIO(blob)) as picture:
            require(
                picture.format == IMAGE_TYPES[mime] and picture.width * picture.height <= 32_000_000,
                "SHIYI_INVALID_RESPONSE",
                "拾忆图片类型或像素尺寸无效",
                502,
            )
            picture.verify()
        with Image.open(io.BytesIO(blob)) as picture:
            picture.load()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise DomainError("SHIYI_INVALID_RESPONSE", "拾忆图片损坏或无法解码", 502) from None


def current(c):
    return c.one("SELECT * FROM shiyi_connections WHERE owner_id=:o AND retired_at IS NULL", {"o": c.owner})


def view(row):
    if not row:
        return None
    return ShiyiConnection.model_validate(
        {
            **public(row),
            "has_key": bool(row["secret_ref"]),
            "readable": bool(row["enabled"] and row["checked_at"] and not row["last_error_code"]),
        }
    ).model_dump()


def configure(c, data):
    previous = current(c)
    require(
        (previous["version"] if previous else 0) == data.expected_version,
        "VERSION_CONFLICT",
        "拾忆连接配置已更新",
    )
    require(not (data.api_key and data.secret_env), "INVALID_INPUT", "Key 和环境变量引用二选一", 400)
    try:
        url = normalize_url(data.api_url)
    except ClientError:
        raise DomainError(
            "INVALID_INPUT", "请输入拾忆网站根地址或 /api/v1 地址，不能包含凭据、查询参数或片段", 400
        ) from None
    if data.new_connection and previous:
        c.update(
            "shiyi_connections", previous["id"], enabled=0, retired_at=c.now, version=previous["version"] + 1
        )
        previous = None
    identity = previous["id"] if previous else uid()
    secret_ref = previous["secret_ref"] if previous else ""
    if data.api_key:
        require(
            not any(ch.isspace() for ch in data.api_key), "INVALID_INPUT", "拾忆 Key 不能包含空白字符", 400
        )
        reference = f"{digest(str(c.db.settings.data_dir))[:12]}/{c.owner}/{identity}/{uid()}"
        try:
            keyring.set_password("knowledge-world", reference, data.api_key)
        except Exception:
            raise DomainError(
                "CREDENTIAL_STORE_UNAVAILABLE", "系统凭据库不可用，请使用服务端环境变量引用", 503
            ) from None
        secret_ref = "keyring:" + reference
    elif data.secret_env:
        require(
            bool(re.fullmatch(r"SHIYI_[A-Z0-9_]+", data.secret_env)),
            "INVALID_INPUT",
            "请使用 SHIYI_ 开头的服务端环境变量",
            400,
        )
        secret_ref = "env:" + data.secret_env
    values = {
        "api_url": url,
        "secret_ref": secret_ref,
        "enabled": 0,
        "checked_at": None,
        "last_error_code": None,
        "last_success_at": None,
        "capabilities_json": "{}",
        "updated_at": c.now,
    }
    if previous:
        c.update("shiyi_connections", identity, version=previous["version"] + 1, **values)
    else:
        c.insert("shiyi_connections", id=identity, owner_id=c.owner, created_at=c.now, **values)
    c.audit("shiyi.configure", "shiyi_connection", identity, {"new_connection": data.new_connection})
    c.change("shiyi")
    job_id = (
        enqueue_check(c, c.get("shiyi_connections", identity)["version"])["job_id"] if data.enabled else None
    )
    return {"connection": view(c.get("shiyi_connections", identity)), "job_id": job_id}


def enqueue_check(c, version):
    from .jobs import enqueue

    row = current(c)
    require(row is not None, "SHIYI_NOT_CONFIGURED", "请先保存拾忆地址与凭据", 409)
    check_version(row, version)
    # Each explicit check fences earlier in-flight responses.
    c.update(
        "shiyi_connections",
        row["id"],
        enabled=0,
        version=version + 1,
        checked_at=None,
        last_error_code=None,
        updated_at=c.now,
    )
    job = enqueue(
        c,
        "shiyi_check",
        f"shiyi-check:{row['id']}:{version + 1}",
        {"connection_id": row["id"], "connection_version": version + 1},
    )
    c.change("shiyi")
    return {"connection": view(c.get("shiyi_connections", row["id"])), "job_id": job["id"]}


def validate_context(result):
    require(
        type(result.get("agent_api_version")) is int and result["agent_api_version"] == 1,
        "SHIYI_API_UNSUPPORTED",
        "拾忆 Agent API 版本不受支持，需要 v1",
        424,
    )
    require(
        isinstance(result.get("permissions"), list) and "read" in result["permissions"],
        "SHIYI_SCOPE_MISSING",
        "拾忆没有返回有效的读取权限",
        424,
    )
    try:
        date.fromisoformat(result["study_date"])
        timezone = result.get("timezone") or result["profile"]["preferences"]["timezone"]
        ZoneInfo(timezone)
        require(
            datetime.fromisoformat(result["server_time"]).tzinfo is not None,
            "SHIYI_INVALID_RESPONSE",
            "拾忆服务器时间没有时区",
            502,
        )
        require(isinstance(result["summary"], dict), "SHIYI_INVALID_RESPONSE", "拾忆概况结构无效", 502)
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
        raise DomainError("SHIYI_INVALID_RESPONSE", "拾忆未返回有效的学习日期、时区或概况", 502) from None
    return {**result, "timezone": timezone}


def snapshot(c):
    require(c.scalar("SELECT enabled FROM skill_settings WHERE owner_id=:o AND skill='shiyi'", {"o": c.owner}), "SKILL_DISABLED", "拾忆 Skill 已关闭", 409)
    row = current(c)
    require(row is not None, "SHIYI_NOT_CONFIGURED", "尚未配置拾忆连接", 409)
    require(row["enabled"], "SHIYI_DISABLED", "拾忆连接尚未启用或需要重新检查", 409)
    require(resolve_secret(row["secret_ref"]), "SHIYI_NOT_CONFIGURED", "拾忆服务端凭据不可读取", 409)
    return row


def check_current(c, config):
    require(c.scalar("SELECT enabled FROM skill_settings WHERE owner_id=:o AND skill='shiyi'", {"o": c.owner}), "SKILL_DISABLED", "拾忆 Skill 已关闭", 409)
    row = current(c)
    require(
        row and row["id"] == config["id"] and row["version"] == config["version"] and row["enabled"],
        "VERSION_CONFLICT",
        "拾忆连接已改变，请刷新后重新读取",
    )
    return row


def check_job(db, job):
    from .jobs import complete_job, ensure_lease

    payload = json.loads(job["payload_json"])
    with db.transaction(owner=job["owner_id"]) as c:
        ensure_lease(c, job)
        config = c.get("shiyi_connections", payload["connection_id"])
        check_version(config, payload["connection_version"])
        require(config["retired_at"] is None, "VERSION_CONFLICT", "拾忆账户连接已更换")
    try:
        key = resolve_secret(config["secret_ref"])
        require(key, "SHIYI_NOT_CONFIGURED", "拾忆服务端凭据不可读取", 409)
        with ReadOnlyClient(config["api_url"], key) as client:
            health = client.decode(client.download("/api/health", health=True)[0])
            require(health.get("status") == "ok", "SHIYI_UNAVAILABLE", "拾忆健康检查未通过", 503)
            context = validate_context(call_tool("shiyi_context", {}, client))
        with db.transaction(True, job["owner_id"]) as c:
            ensure_lease(c, job)
            row = c.get("shiyi_connections", config["id"])
            check_version(row, config["version"])
            require(row["retired_at"] is None, "VERSION_CONFLICT", "拾忆账户连接已更换")
            capabilities = {
                "agent_api_version": 1,
                "permissions": context["permissions"],
                "study_date": context["study_date"],
                "timezone": context["timezone"],
            }
            c.update(
                "shiyi_connections",
                row["id"],
                enabled=1,
                checked_at=c.now,
                last_success_at=c.now,
                last_error_code=None,
                capabilities_json=dumps(capabilities),
                updated_at=c.now,
            )
            result = {"connection_id": config["id"], "readable": True, "capabilities": capabilities}
            complete_job(c, job, result)
        return result
    except (KeyError, ValueError, TypeError):
        exc = DomainError("SHIYI_INVALID_RESPONSE", "拾忆能力检查响应无效", 502)
        record_failure(db, job["owner_id"], config, exc, job=job, disable=True)
        raise exc from None
    except DomainError as exc:
        record_failure(db, job["owner_id"], config, exc, job=job, disable=True)
        raise


def record_failure(db, owner, config, exc, *, job=None, disable=False):
    with db.transaction(True, owner) as c:
        if job:
            from .jobs import ensure_lease

            try:
                ensure_lease(c, job)
            except DomainError:
                return
        row = current(c)
        if (
            row
            and row["id"] == config["id"]
            and row["version"] == config["version"]
            and exc.code.startswith("SHIYI_")
        ):
            values = {"last_error_code": exc.code, "updated_at": c.now}
            if disable:
                values["checked_at"] = c.now
            if disable or exc.code in {
                "SHIYI_AUTH_FAILED",
                "SHIYI_SCOPE_MISSING",
                "SHIYI_API_UNSUPPORTED",
                "SHIYI_NOT_CONFIGURED",
            }:
                values["enabled"] = 0
            c.update("shiyi_connections", row["id"], **values)


def safe_result(value, *, answers=False):
    """Never persist secrets or inline media from an external JSON response."""
    private = {
        "api_key",
        "api_keys",
        "secret",
        "secret_ref",
        "password",
        "password_hash",
        "token",
        "authorization",
        "image_url",
    }
    if not answers:
        private |= {"answer", "answer_text", "answer_media", "mistake_reason", "takeaway"}
    if isinstance(value, dict):
        return {k: safe_result(v, answers=answers) for k, v in value.items() if k.lower() not in private}
    if isinstance(value, list):
        return [safe_result(v, answers=answers) for v in value]
    if isinstance(value, str) and "data:image/" in value:
        return "[私有图片需要通过图像工具读取]"
    return value


def fetch_remote(db, owner, config, name, arguments, cursor=None):
    """Network only. Caller must release all database transactions first."""
    args = valid_arguments(name, arguments)
    try:
        with ReadOnlyClient(config["api_url"], resolve_secret(config["secret_ref"])) as client:
            context = validate_context(call_tool("shiyi_context", {}, client))
            if name == "shiyi_reviews":
                end = args.get("date_to") or context["study_date"]
                args.update(
                    date_to=end,
                    date_from=args.get("date_from")
                    or (date.fromisoformat(end) - timedelta(days=29)).isoformat(),
                )
                args = valid_arguments(name, args)
            binding = digest(
                dumps(
                    {
                        "owner": owner,
                        "connection": config["id"],
                        "version": config["version"],
                        "tool": name,
                        "filters": {k: v for k, v in args.items() if k != "page"},
                    }
                )
            )
            if cursor:
                try:
                    decoded = signer(db.settings).loads(cursor, max_age=86400)
                    require(
                        decoded.get("purpose") == "shiyi-page"
                        and decoded["binding"] == binding
                        and type(decoded["page"]) is int
                        and 1 <= decoded["page"] <= 100000,
                        "INVALID_CURSOR",
                        "分页条件或连接已改变，请从第一页重新查询",
                        400,
                    )
                    args["page"] = decoded["page"]
                except DomainError:
                    raise
                except Exception:
                    raise DomainError("INVALID_CURSOR", "拾忆分页游标无效或已过期", 400) from None
            result = context if name == "shiyi_context" else call_tool(name, args, client)
        if name != "shiyi_image":
            result = safe_result(
                result, answers=bool(args.get("include_answer") or args.get("include_answers"))
            )
        if name in {"shiyi_reviews", "shiyi_search", "shiyi_weaknesses", "shiyi_due"}:
            require(
                isinstance(result.get("items"), list)
                and all(isinstance(item, dict) for item in result["items"]),
                "SHIYI_INVALID_RESPONSE",
                "拾忆列表结构无效",
                502,
            )
            require(
                len(result["items"]) <= args.get("page_size", args.get("limit", 10)),
                "SHIYI_INVALID_RESPONSE",
                "拾忆返回的记录超过本页限制",
                502,
            )
        if name in {"shiyi_reviews", "shiyi_search", "shiyi_weaknesses"}:
            require(
                type(result.get("has_more")) is bool
                and type(result.get("total")) is int
                and result["total"] >= 0
                and result.get("page") == args.get("page", 1)
                and result.get("page_size") == args["page_size"],
                "SHIYI_INVALID_RESPONSE",
                "拾忆分页信息不完整",
                502,
            )
            result["source_total"] = result["total"]
            result["next_cursor"] = (
                signer(db.settings).dumps(
                    {"purpose": "shiyi-page", "binding": binding, "page": args.get("page", 1) + 1}
                )
                if result["has_more"]
                else None
            )
        if name == "shiyi_reviews":
            for item in result["items"]:
                require(
                    type(item.get("rating")) is int
                    and 1 <= item["rating"] <= 4
                    and (
                        item.get("independent_completed") is None
                        or type(item["independent_completed"]) is bool
                    ),
                    "SHIYI_INVALID_RESPONSE",
                    "拾忆复习评分或独立完成字段不符合 v1 协议",
                    502,
                )
                UUID(item["id"])
                require(
                    isinstance(item.get("item"), dict)
                    and item["item"].get("subject") in {"408", "math", "english"},
                    "SHIYI_INVALID_RESPONSE",
                    "拾忆记录缺少有效题目来源",
                    502,
                )
                UUID(item["item"]["id"])
                require(
                    item.get("duration_ms") is None
                    or type(item["duration_ms"]) is int
                    and item["duration_ms"] >= 0,
                    "SHIYI_INVALID_RESPONSE",
                    "拾忆时长无效",
                    502,
                )
            result.update(date_from=args["date_from"], date_to=args["date_to"])
        if name == "shiyi_due":
            require(
                all(type(result.get(key)) is int and result[key] >= 0 for key in ("due_count", "new_count")),
                "SHIYI_INVALID_RESPONSE",
                "拾忆到期数量无效",
                502,
            )
        if name == "shiyi_item":
            require(
                result.get("id") == args["item_id"], "SHIYI_INVALID_RESPONSE", "拾忆题目与请求不一致", 502
            )
        result["source"] = {
            "system": "shiyi",
            "connection_id": config["id"],
            "connection_version": config["version"],
            "fetched_at": iso(db.clock()),
            "timezone": context["timezone"],
            "study_date": context["study_date"],
            "freshness": "live",
            "source_server_time": result.get("server_time", context["server_time"]),
        }
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        raise DomainError("SHIYI_INVALID_RESPONSE", "拾忆响应不符合读取协议", 502) from None


def fetch_for_request(c, name, arguments, cursor=None):
    valid_arguments(name, arguments)
    config = snapshot(c)
    c.s.rollback()  # Release authentication/config reads before the remote GET.
    try:
        result = fetch_remote(c.db, c.owner, config, name, arguments, cursor)
    except DomainError as exc:
        record_failure(c.db, c.owner, config, exc)
        raise
    with c.db.transaction(True, c.owner) as check:
        check_current(check, config)
        require(
            check.scalar(
                "SELECT 1 FROM auth_sessions WHERE id=:id AND revoked_at IS NULL AND expires_at>:at",
                {"id": c.auth_session["id"], "at": check.now},
            ),
            "AUTH_REQUIRED",
            "会话已失效，请重新登录",
            401,
        )
        require(
            not c.db.settings.data_dir.joinpath(".maintenance").exists(),
            "MAINTENANCE",
            "正在恢复数据，请稍后重新登录",
            503,
        )
        check.update("shiyi_connections", config["id"], last_success_at=check.now, last_error_code=None)
    return result


def media_bytes(result):
    return base64.b64decode(result["image_url"].split(",", 1)[1], validate=True), result["mime_type"]


def available_tools(c):
    row = current(c)
    enabled = c.scalar("SELECT enabled FROM skill_settings WHERE owner_id=:o AND skill='shiyi'", {"o": c.owner})
    return TOOLS if enabled and row and row["enabled"] else []
