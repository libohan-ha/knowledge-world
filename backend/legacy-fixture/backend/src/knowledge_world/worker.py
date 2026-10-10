import argparse
import time
from .config import Settings
from .db import Database
from .jobs import run_once, enqueue
from .common import uid, local_ms


def maintenance_tick(db):
    from .routines import daily_catchup
    from .commitments import evaluate_all
    from .identity import apply_pending_timezone

    with db.transaction(True) as c:
        profile = c.one("SELECT * FROM profiles LIMIT 1")
        if not profile:
            return
        c.owner = profile["id"]
        apply_pending_timezone(c)
        daily_catchup(c)
        evaluate_all(c)
        backup_at = local_ms(c.today, c.rules()["storage"]["backup_local_time"], c.tz)
        if c.now >= backup_at:
            key = f"scheduled-backup:{c.today}"
            if not c.scalar("SELECT count(*) FROM jobs WHERE job_key=:k", {"k": key}):
                identity = uid()
                c.insert("backup_records", id=identity, owner_id=c.owner, state="queued", created_at=c.now)
                enqueue(c, "backup", key, {"backup_id": identity})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    db = Database(Settings())
    db.migrate()
    worker_id = uid()
    last_tick = 0
    try:
        while True:
            if not (db.settings.data_dir / ".maintenance").exists():
                if time.monotonic() - last_tick > 30:
                    maintenance_tick(db)
                    last_tick = time.monotonic()
                worked = run_once(db, worker_id)
            else:
                worked = False
            if args.once:
                break
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
