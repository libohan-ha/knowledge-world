import hashlib
import json
import time
import uuid
import base64
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def uid():
    return str(uuid.uuid4())


def now_ms():
    return time.time_ns() // 1_000_000


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else str(value).encode("utf-8")).hexdigest()


def iso(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat() if value is not None else None


def day_at(value, tz="Asia/Shanghai"):
    return datetime.fromtimestamp(value / 1000, ZoneInfo(tz)).date().isoformat()


def local_ms(day, clock="00:00", tz="Asia/Shanghai", offset=0):
    target = date.fromisoformat(day) + timedelta(days=offset)
    return int(datetime.fromisoformat(f"{target}T{clock}").replace(tzinfo=ZoneInfo(tz)).timestamp() * 1000)


def next_day(day):
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


class DomainError(Exception):
    def __init__(self, code, message, status=409, **details):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


def require(condition, code="ACTION_NOT_ALLOWED", message="当前状态不允许此操作", status=409, **details):
    if not condition:
        raise DomainError(code, message, status, **details)


def check_version(row, expected):
    require(
        row["version"] == expected,
        "VERSION_CONFLICT",
        "记录已更新，请刷新后重试",
        current_version=row["version"],
    )


STAGES = ["unseen", "exploring", "understood", "applicable", "consolidated"]


def public(row):
    if row is None:
        return None
    result = {}
    private = {
        "password_hash",
        "token_hash",
        "csrf_token_hash",
        "secret_ref",
        "owner_id",
        "lease_owner",
        "lease_token",
        "frozen_answer_json",
    }
    for key, value in dict(row).items():
        if key in private:
            continue
        if key.endswith("_json"):
            result[key[:-5]] = json.loads(value) if value is not None else None
        elif key.endswith("_at") or key in {"lease_until", "expires_at"}:
            result[key] = iso(value)
        else:
            result[key] = value
    return result


def page(items, next_cursor=None):
    return {"items": items, "next_cursor": next_cursor}


def cursor_offset(cursor):
    try:
        offset = int(base64.urlsafe_b64decode(cursor).decode()) if cursor else 0
        require(0 <= offset <= 10_000_000, "INVALID_INPUT", "分页游标无效", 400)
        return offset
    except (ValueError, TypeError):
        raise DomainError("INVALID_INPUT", "分页游标无效", 400)


def next_cursor(offset):
    return base64.urlsafe_b64encode(str(offset).encode()).decode()
