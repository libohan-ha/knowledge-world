import json
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from .common import uid, dumps, digest, require, next_day, check_version, public, day_at
from .game_events import wallet_view
from .models import DisplayPreferences

hasher = PasswordHasher()


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        require(False, "INVALID_INPUT", "时区无效", 400)


def create_session(c, owner):
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    c.insert(
        "auth_sessions",
        id=uid(),
        owner_id=owner,
        token_hash=digest(token),
        csrf_token_hash=digest(csrf),
        expires_at=c.now + 30 * 86400000,
        created_at=c.now,
    )
    return token, csrf


def setup(c, data):
    validate_timezone(data.timezone)
    require(not c.scalar("SELECT count(*) FROM profiles"), "ALREADY_INITIALIZED", "本地账户已经创建")
    owner = uid()
    c.insert("profiles", id=owner, display_name=data.display_name.strip(), password_hash=hasher.hash(data.password),
        timezone=data.timezone, created_at=c.now, updated_at=c.now)
    c.owner = owner
    c.insert("wallets", owner_id=owner, updated_at=c.now)
    from .core_rules import initialize_account
    initialize_account(c)
    return create_session(c, owner)


def login(c, password):
    profile = c.one("SELECT * FROM profiles LIMIT 1")
    require(profile is not None, "AUTH_REQUIRED", "请先创建账户", 401)
    try:
        hasher.verify(profile["password_hash"], password)
    except (VerifyMismatchError, VerificationError):
        require(False, "AUTH_REQUIRED", "密码不正确", 401)
    c.owner = profile["id"]
    return create_session(c, c.owner)


def profile_view(c):
    profile = public(c.profile)
    # Routes return JSONResponse directly; response_model does not fill defaults.
    # Normalize at the shared boundary without writing defaults to saved choices.
    profile["preferences"] = DisplayPreferences.model_validate(profile["preferences"]).model_dump()
    return profile


def me(c):
    return {
        "profile": profile_view(c),
        "wallet": wallet_view(c),
        "business_date": c.today,
        "is_test_adapter": c.db.settings.fake_provider,
        "display_epoch": c.scalar("SELECT epoch FROM world_history_state WHERE id=1"),
    }


def edit_profile(c, data):
    row = c.profile
    check_version(row, data.expected_version)
    values = {"version": row["version"] + 1, "updated_at": c.now}
    if data.display_name is not None:
        values["display_name"] = data.display_name
    if data.timezone is not None:
        validate_timezone(data.timezone)
        values.update(pending_timezone=data.timezone, timezone_effective_date=next_day(c.today))
    c.update("profiles", c.owner, **values)
    c.audit("profile.update", "profile", c.owner)
    return me(c)


def apply_pending_timezone(c):
    row = c.profile
    if row["pending_timezone"] and day_at(c.now, row["timezone"]) >= row["timezone_effective_date"]:
        c.insert(
            "profile_timezone_changes",
            id=uid(),
            owner_id=c.owner,
            effective_date=row["timezone_effective_date"],
            previous_timezone=row["timezone"],
            timezone=row["pending_timezone"],
            created_at=c.now,
        )
        c.update(
            "profiles",
            c.owner,
            timezone=row["pending_timezone"],
            pending_timezone=None,
            timezone_effective_date=None,
            version=row["version"] + 1,
            updated_at=c.now,
        )


def timezone_for_day(c, day):
    profile = c.profile
    if (
        profile["pending_timezone"]
        and day >= profile["timezone_effective_date"]
        and day_at(c.now, profile["timezone"]) >= profile["timezone_effective_date"]
    ):
        return profile["pending_timezone"]
    change = c.one(
        "SELECT * FROM profile_timezone_changes WHERE owner_id=:o AND effective_date<=:d ORDER BY effective_date DESC,created_at DESC LIMIT 1",
        {"o": c.owner, "d": day},
    )
    if change:
        return change["timezone"]
    first = c.one(
        "SELECT * FROM profile_timezone_changes WHERE owner_id=:o ORDER BY effective_date,created_at LIMIT 1",
        {"o": c.owner},
    )
    return first["previous_timezone"] if first else profile["timezone"]


def edit_preferences(c, data):
    row = c.profile
    check_version(row, data.expected_version)
    prefs = json.loads(row["preferences_json"])
    prefs.update(data.model_dump(exclude_none=True, exclude={"expected_version"}))
    c.update("profiles", c.owner, preferences_json=dumps(prefs), version=row["version"] + 1, updated_at=c.now)
    return profile_view(c)
