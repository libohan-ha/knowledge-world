"""Real online backup/restore on temporary WAL files; all funding is synthetic."""
import zipfile

import pytest

from knowledge_world import backup, economy
from knowledge_world.common import DomainError
from knowledge_world.config import Settings
from knowledge_world.db import Database
from test_core_behavior import accept, buy, judge


PRESERVED = (
    "wallets", "ledger_entries", "rule_versions", "habit_occurrences", "commitments",
    "heroes", "monsters", "teams", "home_items", "game_orders", "game_events",
    "battles", "occupations", "leisure_tickets", "leisure_intervals",
    "system_actions", "system_action_revisions", "system_decisions", "system_challenges",
)


def rows(db):
    with db.transaction() as c:
        return {table: c.all(f"SELECT * FROM {table} ORDER BY rowid") for table in PRESERVED}


def package(h):
    result = backup.create_backup(h.db, h.owner)
    return result, h.db.settings.data_dir.joinpath("backups", result["backup_id"] + ".zip").read_bytes()


def test_restore_preserves_game_contracts_holds_and_redacts_sessions(h, tmp_path):
    h.fund(1500)
    judge(h, 40)
    h.clock.set("2026-10-10", "06:50")
    h.post("/system/checkin")
    accept(h, h.post("/system/wagers", {"target_points": 500, "stake_points": 40, "bonus_points": 15}))
    h.post("/system/challenges", {"title": "SYNTHETIC routine", "goal": "Restore accepted terms", "reward_points": 15})
    buy(h, "hero_train", attribute="strength")
    buy(h, "monster_recruit", "shadow_wolf")
    buy(h, "home_buy", "flower_bed")
    reward = h.get("/rewards")[0]
    buy(h, "leisure", reward["id"])
    started, _ = buy(h, "leisure", reward["id"])
    ticket = h.post(f"/leisure/{started['entity_id']}/start", {"expected_version": 1})
    h.clock.advance(seconds=5)
    h.post(f"/leisure/{ticket['id']}/pause", {"expected_version": ticket["version"]})
    roster = h.get("/roster")
    h.post("/world/battles", {"outpost_id": "fern_gate", "team_version": roster["team"]["version"], "command_key": "synthetic-backup-battle"})
    h.drain()
    before = rows(h.db)
    assert all(before[table] for table in PRESERVED)
    old_epoch = h.get("/me")["display_epoch"]
    session_hash = h.scalar("SELECT token_hash FROM auth_sessions LIMIT 1")
    # A credential reference is enough to verify removal, without saving a key.
    with h.db.transaction(True, h.owner) as c:
        c.execute("UPDATE provider_configs SET secret_ref='env:SYNTHETIC_BACKUP_SECRET',enabled=1")
    result, blob = package(h)
    assert result["manifest"]["credentials_included"] is False
    for table in ("heroes", "monsters", "teams", "home_items", "game_events", "battles", "occupations", "leisure_tickets", "system_actions"):
        assert result["manifest"]["counts"][table] == len(before[table])
    with zipfile.ZipFile(h.db.settings.data_dir / "backups" / (result["backup_id"] + ".zip")) as archive:
        assert set(archive.namelist()) == {"database.sqlite", "manifest.json"}
        database = archive.read("database.sqlite")
        assert session_hash.encode() not in database
        assert b"SYNTHETIC_BACKUP_SECRET" not in database

    restored = Database(Settings(data_dir=tmp_path / "restored", mode="test", fake_provider=True), h.clock)
    try:
        restored.migrate()
        checked = backup.preview(restored.settings, blob)
        assert checked["reconciliation"]["ok"]
        receipt = backup.perform_restore(restored, checked["preview_id"])
        assert receipt["restored"] and receipt["requires_login"] and receipt["requires_provider_configuration"]
        assert rows(restored) == before
        with restored.transaction(owner=h.owner) as c:
            assert c.scalar("SELECT count(*) FROM auth_sessions") == 0
            assert c.scalar("SELECT count(*) FROM provider_configs WHERE enabled=1 OR secret_ref!=''") == 0
            assert c.scalar("SELECT epoch FROM world_history_state WHERE id=1") != old_epoch
            assert economy.reconcile(c) == {"ok": True, "differences": [], "integrity": "ok", "foreign_keys": []}
        assert not restored.settings.data_dir.joinpath(".maintenance").exists()
        # Source remains logged in and untouched by the isolated restore.
        assert h.get("/me")["display_epoch"] == old_epoch
        assert h.scalar("SELECT count(*) FROM auth_sessions") == 1
    finally:
        restored.engine.dispose()


def test_restore_rejects_changed_preview_without_touching_live_data(h):
    h.fund(100)
    _, blob = package(h)
    checked = backup.preview(h.db.settings, blob)
    staged = h.db.settings.data_dir / "restore-previews" / checked["preview_id"] / "database.sqlite"
    staged.write_bytes(staged.read_bytes() + b"SYNTHETIC TAMPER")
    with pytest.raises(DomainError, match="预检文件已变化"):
        backup.perform_restore(h.db, checked["preview_id"])
    assert h.get("/wallet")["available_points"] == 100
    h.reconcile()


def test_restore_failure_rolls_back_database_and_exits_maintenance(h, monkeypatch):
    h.fund(100)
    _, blob = package(h)
    h.fund(50)
    checked = backup.preview(h.db.settings, blob)
    before = rows(h.db)

    def fail_migration():
        raise RuntimeError("SYNTHETIC migration failure after swap")

    monkeypatch.setattr(h.db, "migrate", fail_migration)
    with pytest.raises(RuntimeError, match="after swap"):
        backup.perform_restore(h.db, checked["preview_id"])
    assert rows(h.db) == before
    assert h.get("/wallet")["available_points"] == 150
    assert not h.db.settings.data_dir.joinpath(".maintenance").exists()
    assert list(h.db.settings.data_dir.joinpath("backups").glob("before-restore-*.sqlite"))
    h.reconcile()
