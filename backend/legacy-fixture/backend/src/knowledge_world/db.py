from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from alembic.config import Config
from alembic import command
from .common import DomainError, uid, now_ms, dumps, day_at
from .config import ROOT


class Database:
    def __init__(self, settings, clock=now_ms):
        if sqlite3.sqlite_version_info < (3, 51, 3):
            raise RuntimeError(
                f"SQLite {sqlite3.sqlite_version} 不满足要求（至少 3.51.3），请运行 uv sync --python 3.14"
            )
        self.settings, self.clock = settings, clock
        self.engine = create_engine(
            f"sqlite:///{settings.database.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
            pool_pre_ping=True,
        )

        @event.listens_for(self.engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA synchronous=FULL")

    def migrate(self):
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.commit()
            config = Config(str(ROOT / "backend/alembic.ini"))
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            # New indexes otherwise have no selectivity statistics on upgraded
            # databases. SQLite limits this maintenance to tables that need it.
            conn.exec_driver_sql("PRAGMA optimize=0x10002")
            conn.commit()

    @contextmanager
    def transaction(self, write=False, owner=None):
        with Session(self.engine) as session:
            if write:
                session.execute(text("BEGIN IMMEDIATE"))
            ctx = Context(self, session, owner)
            try:
                yield ctx
                session.commit()
            except BaseException:
                session.rollback()
                raise


class Context:
    def __init__(self, db, session, owner=None):
        self.db, self.s, self.owner = db, session, owner
        self.now = db.clock()
        self.changed = []

    def execute(self, sql, params=None):
        return self.s.execute(text(sql), params or {})

    def one(self, sql, params=None):
        row = self.execute(sql, params).mappings().first()
        return dict(row) if row else None

    def all(self, sql, params=None):
        return [dict(row) for row in self.execute(sql, params).mappings()]

    def scalar(self, sql, params=None):
        return self.execute(sql, params).scalar()

    def get(self, table, identity, *, key="id", owned=True):
        # Identifiers are exclusively application constants, never user input.
        row = self.one(f"SELECT * FROM {table} WHERE {key}=:identity", {"identity": identity})
        if row is None or (owned and row.get("owner_id", self.owner) != self.owner):
            raise DomainError("RESOURCE_NOT_FOUND", "记录不存在", 404)
        return row

    def insert(self, table, **values):
        self.execute(
            f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join(':' + k for k in values)})", values
        )
        return values

    def update(self, table, identity, *, key="id", **values):
        self.execute(
            f"UPDATE {table} SET {','.join(k + '=:' + k for k in values)} WHERE {key}=:__identity",
            {**values, "__identity": identity},
        )

    @property
    def profile(self):
        return self.get("profiles", self.owner, owned=False)

    @property
    def tz(self):
        profile = self.profile
        return profile["timezone"]

    @property
    def today(self):
        return day_at(self.now, self.tz)

    def rules(self, version=None):
        row = self.one(
            "SELECT * FROM rule_versions WHERE id=:v"
            if version
            else "SELECT * FROM rule_versions WHERE is_active=1",
            {"v": version},
        )
        return json.loads(row["payload_json"])

    def audit(self, action, kind, identity, detail=None, actor="user"):
        self.insert(
            "audit_events",
            id=uid(),
            owner_id=self.owner,
            actor_kind=actor,
            action=action,
            entity_type=kind,
            entity_id=identity,
            detail_json=dumps(detail or {}),
            created_at=self.now,
        )

    def notify(self, event_key, title, body="", path="/today", kind="info"):
        preferences = json.loads(self.profile["preferences_json"])
        if not preferences.get("notifications", True):
            return
        self.execute(
            "INSERT OR IGNORE INTO notifications (id,owner_id,event_key,kind,title,body,target_path,created_at) VALUES (:id,:o,:k,:kind,:t,:b,:p,:at)",
            {
                "id": uid(),
                "o": self.owner,
                "k": event_key,
                "kind": kind,
                "t": title,
                "b": body,
                "p": path,
                "at": self.now,
            },
        )

    def change(self, *kinds, dates=None):
        self.changed.extend({"kind": kind, "business_dates": dates or []} for kind in kinds)


def controlled_path(root: Path, relative: str):
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise DomainError("INVALID_INPUT", "文件路径无效", 400)
    return target
