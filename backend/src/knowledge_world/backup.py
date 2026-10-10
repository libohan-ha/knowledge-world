import json
import shutil
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory
from .common import uid, dumps, digest, require, now_ms, DomainError
from .config import ROOT
from .db import controlled_path
from .economy import reconcile


def redact(value):
    if isinstance(value, dict):
        return {
            key: "" if key in {"secret_ref", "api_key", "secret_env"} else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def online_copy(source, target):
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def scrub_snapshot(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("DELETE FROM auth_sessions")
        conn.execute("UPDATE provider_configs SET secret_ref='',enabled=0")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_history_state'").fetchone():
            # A restored database is a new history lineage, even if every event
            # has the same timestamp and append sequence as the previous file.
            conn.execute("UPDATE world_history_state SET epoch=? WHERE id=1", (uid(),))
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shiyi_connections'"
        ).fetchone():
            conn.execute(
                "UPDATE shiyi_connections SET secret_ref='',enabled=0,version=version+1,checked_at=NULL,last_success_at=NULL,last_error_code=NULL,capabilities_json='{}'"
            )
            conn.execute(
                "UPDATE jobs SET state='cancelled',lease_owner=NULL,lease_until=NULL,lease_token=lease_token+1 WHERE kind='shiyi_check' AND state NOT IN ('succeeded','failed','cancelled')"
            )
        for table, column in [
            ("jobs", "payload_json"),
            ("agent_runs", "provider_snapshot_json"),
            ("redemptions", "provider_snapshot_json"),
        ]:
            for identity, text in conn.execute(
                f"SELECT id,{column} FROM {table} WHERE {column} IS NOT NULL"
            ).fetchall():
                conn.execute(
                    f"UPDATE {table} SET {column}=? WHERE id=?", (dumps(redact(json.loads(text))), identity)
                )
        conn.execute("DELETE FROM idempotency_keys")
        conn.execute(
            "UPDATE jobs SET state='needs_review',lease_owner=NULL,lease_until=NULL,lease_token=lease_token+1 WHERE state='running' AND external_request_started_at IS NOT NULL"
        )
        conn.execute(
            "UPDATE jobs SET state='queued',lease_owner=NULL,lease_until=NULL,lease_token=lease_token+1 WHERE state='running' AND external_request_started_at IS NULL"
        )
        conn.execute("UPDATE redemptions SET state='needs_review' WHERE state='running'")
        conn.execute(
            "UPDATE jobs SET state='cancelled',lease_owner=NULL,lease_until=NULL,lease_token=lease_token+1 WHERE kind IN ('restore','backup') AND state NOT IN ('succeeded','failed','cancelled')"
        )
        conn.execute("UPDATE backup_records SET state='failed',relative_path=NULL WHERE state!='failed'")
        conn.commit()
        # Remove deleted session tokens and credential references from free pages, too.
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def create_backup(db, owner, identity=None):
    identity = identity or uid()
    root = db.settings.data_dir
    staging = root / "backup-staging" / identity
    staging.mkdir(parents=True, exist_ok=True)
    snapshot = staging / "database.sqlite"
    online_copy(db.settings.database, snapshot)
    scrub_snapshot(snapshot)
    with closing(sqlite3.connect(snapshot)) as conn:
        references = conn.execute(
            "SELECT relative_path,sha256 FROM materials WHERE relative_path IS NOT NULL UNION ALL SELECT relative_path,sha256 FROM generated_assets"
        ).fetchall()
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {
            name: conn.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in ("profiles", "wallets", "ledger_entries", "commitments", "habit_occurrences", "system_actions", "system_decisions", "system_challenges", "leisure_tickets", "leisure_intervals", "heroes", "monsters", "teams", "home_items", "game_events", "battles", "occupations", "generated_assets", "knowledge_points", "activities")
        }
    manifest = {
        "format": "knowledge-world.backup.1",
        "created_at": now_ms(),
        "schema_version": version,
        "database_sha256": digest(snapshot.read_bytes()),
        "counts": tables,
        "files": [],
        "credentials_included": False,
        "sessions_included": False,
        "rules_version": None,
    }
    with closing(sqlite3.connect(snapshot)) as conn:
        manifest["rules_version"] = conn.execute("SELECT id FROM rule_versions WHERE is_active=1").fetchone()[0]
    relative = f"backups/{identity}.zip"
    destination = controlled_path(root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot, "database.sqlite")
        for path, sha in references:
            source = controlled_path(root, path)
            require(
                source.is_file() and digest(source.read_bytes()) == sha,
                "FILE_CORRUPT",
                "备份引用的文件丢失或损坏",
            )
            archive.write(source, "files/" + path)
            manifest["files"].append({"path": path, "sha256": sha, "size_bytes": source.stat().st_size})
        archive.writestr("manifest.json", dumps(manifest))
    sha = digest(destination.read_bytes())
    with db.transaction(True, owner) as c:
        exists = c.one("SELECT * FROM backup_records WHERE id=:id", {"id": identity})
        values = {
            "relative_path": relative,
            "state": "ready",
            "manifest_json": dumps(manifest),
            "sha256": sha,
            "completed_at": c.now,
        }
        if exists:
            c.update("backup_records", identity, **values)
        else:
            c.insert("backup_records", id=identity, owner_id=owner, created_at=c.now, **values)
        keep = c.rules()["storage"]["backup_keep_count"]
        expired = c.all(
            "SELECT id,relative_path FROM backup_records WHERE owner_id=:o AND state='ready' ORDER BY completed_at DESC,id DESC LIMIT -1 OFFSET :keep",
            {"o": owner, "keep": keep},
        )
        for row in expired:
            c.update("backup_records", row["id"], state="failed", relative_path=None)
    for row in expired:
        if row["relative_path"]:
            controlled_path(root, row["relative_path"]).unlink(missing_ok=True)
    # Only the known temporary database, never a computed directory tree, is removed.
    snapshot.unlink(missing_ok=True)
    return {"backup_id": identity, "sha256": sha, "manifest": manifest}


def preview(settings, blob):
    require(len(blob) <= 512 * 1024 * 1024, "INVALID_INPUT", "备份包超过 512MB", 400)
    identity = uid()
    staging = settings.data_dir / "restore-previews" / identity
    staging.mkdir(parents=True, exist_ok=True)
    package = staging / "package.zip"
    package.write_bytes(blob)
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            require(
                len(names) == len(set(names)) and len(names) <= 100000,
                "INVALID_INPUT",
                "备份目录重复或过大",
                400,
            )
            for info in archive.infolist():
                path = Path(info.filename)
                require(
                    not path.is_absolute()
                    and ".." not in path.parts
                    and "\\" not in info.filename
                    and ":" not in info.filename,
                    "INVALID_INPUT",
                    "备份包含危险路径",
                    400,
                )
                require(
                    info.file_size <= 512 * 1024 * 1024 and (info.external_attr >> 16) & 0o170000 != 0o120000,
                    "INVALID_INPUT",
                    "备份包含不支持的文件",
                    400,
                )
            required_space = sum(info.file_size for info in archive.infolist())
            require(
                required_space < 2 * 1024**3
                and shutil.disk_usage(settings.data_dir).free > required_space * 2 + 50 * 1024**2,
                "INVALID_INPUT",
                "备份过大或磁盘空间不足",
                400,
            )
            manifest = json.loads(archive.read("manifest.json"))
            known_versions = {
                revision.revision
                for revision in ScriptDirectory.from_config(
                    Config(str(ROOT / "backend/alembic.ini"))
                ).walk_revisions()
            }
            require(
                manifest["format"] == "knowledge-world.backup.1"
                and manifest["schema_version"] in known_versions,
                "INVALID_INPUT",
                "备份格式或数据库版本不受支持",
                400,
            )
            database = archive.read("database.sqlite")
            require(digest(database) == manifest["database_sha256"], "FILE_CORRUPT", "数据库哈希不匹配")
            (staging / "database.sqlite").write_bytes(database)
            for item in manifest["files"]:
                target = controlled_path(staging / "files", item["path"])
                data = archive.read("files/" + item["path"])
                require(
                    len(data) == item["size_bytes"] and digest(data) == item["sha256"],
                    "FILE_CORRUPT",
                    "备份文件哈希不匹配",
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            expected = {
                "manifest.json",
                "database.sqlite",
                *["files/" + item["path"] for item in manifest["files"]],
            }
            require(set(names) == expected, "INVALID_INPUT", "备份包含未登记文件", 400)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        raise DomainError("INVALID_INPUT", "备份包无法完整读取", 400)
    with closing(sqlite3.connect(staging / "database.sqlite")) as conn:
        conn.row_factory = sqlite3.Row
        require(
            conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == manifest["schema_version"],
            "FILE_CORRUPT",
            "备份声明的迁移版本与数据库不一致",
        )
        require(
            conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            and not conn.execute("PRAGMA foreign_key_check").fetchall(),
            "FILE_CORRUPT",
            "备份数据库完整性检查失败",
        )
        refs = conn.execute(
            "SELECT relative_path,sha256 FROM materials WHERE relative_path IS NOT NULL UNION ALL SELECT relative_path,sha256 FROM generated_assets"
        ).fetchall()
        require(
            {(r[0], r[1]) for r in refs} == {(item["path"], item["sha256"]) for item in manifest["files"]},
            "FILE_CORRUPT",
            "数据库文件引用与清单不一致",
        )

        class Snapshot:
            def all(self, sql, params=None):
                return [dict(row) for row in conn.execute(sql, params or {}).fetchall()]

            def scalar(self, sql, params=None):
                return conn.execute(sql, params or {}).fetchone()[0]

        reconciliation = reconcile(Snapshot())
        require(reconciliation["ok"], "RESTORE_RECONCILIATION_FAILED", "备份账本与余额或冻结来源不一致")
    (staging / "manifest.json").write_text(
        dumps({**manifest, "validated_at": now_ms(), "package_sha256": digest(blob)}), encoding="utf-8"
    )
    return {"preview_id": identity, "manifest": manifest, "reconciliation": reconciliation}


def perform_restore(db, preview_id):
    root = db.settings.data_dir
    staging = controlled_path(root, f"restore-previews/{preview_id}")
    manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
    require(now_ms() - manifest["validated_at"] <= 30 * 60 * 1000, "QUOTE_EXPIRED", "恢复预检已过期")
    require(
        digest((staging / "database.sqlite").read_bytes()) == manifest["database_sha256"],
        "FILE_CORRUPT",
        "预检文件已变化",
    )
    maintenance = root / ".maintenance"
    maintenance.write_text("正在恢复已验证的备份", encoding="utf-8")
    safety = root / "backups" / f"before-restore-{uid()}.sqlite"
    safety.parent.mkdir(parents=True, exist_ok=True)
    swapped = False
    try:
        db.engine.dispose()
        online_copy(db.settings.database, safety)
        for item in manifest["files"]:
            source = controlled_path(staging / "files", item["path"])
            require(digest(source.read_bytes()) == item["sha256"], "FILE_CORRUPT", "预检资源已变化")
            destination = controlled_path(root, item["path"])
            if destination.exists():
                require(
                    digest(destination.read_bytes()) == item["sha256"],
                    "FILE_COLLISION",
                    "已有文件与备份发生冲突，原数据保留",
                )
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        # SQLite Online Backup writes an atomic database image even with existing readers.
        online_copy(staging / "database.sqlite", db.settings.database)
        swapped = True
        scrub_snapshot(db.settings.database)
        db.engine.dispose()
        db.migrate()
        with db.transaction() as c:
            result = reconcile(c)
            require(
                result["ok"] and result["integrity"] == "ok" and not result["foreign_keys"],
                "RESTORE_RECONCILIATION_FAILED",
                "恢复后的账本核对失败",
            )
        return {
            "restored": True,
            "requires_login": True,
            "requires_provider_configuration": True,
            "reconciliation": result,
        }
    except BaseException:
        if swapped:
            db.engine.dispose()
            online_copy(safety, db.settings.database)
        raise
    finally:
        db.engine.dispose()
        maintenance.unlink(missing_ok=True)
