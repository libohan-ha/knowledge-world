import argparse
import getpass
import json
import sqlite3
import sys
from pathlib import Path
from .config import Settings
from .db import Database


def main():
    parser = argparse.ArgumentParser(prog="knowledge-world")
    parser.add_argument(
        "command",
        choices=[
            "doctor",
            "init",
            "migrate",
            "create-account",
            "reconcile",
            "backup",
            "restore-preview",
            "restore",
            "openapi",
        ],
    )
    parser.add_argument("--file")
    parser.add_argument("--preview-id")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "doctor":
        print(
            json.dumps(
                {
                    "python": sys.version,
                    "sqlite": sqlite3.sqlite_version,
                    "sqlite_supported": sqlite3.sqlite_version_info >= (3, 51, 3),
                    "mode": settings.mode,
                    "test_adapter": settings.fake_provider,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    db = Database(settings)
    db.migrate()
    if args.command in {"init", "migrate"}:
        print("数据库迁移完成")
    elif args.command == "create-account":
        from .identity import setup
        from .models import Setup

        name = input("显示名：")
        password = getpass.getpass("密码（至少8位）：")
        with db.transaction(True) as c:
            setup(c, Setup(display_name=name, password=password))
        print("账户已创建")
    elif args.command == "reconcile":
        from .economy import reconcile

        with db.transaction() as c:
            result = reconcile(c)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"] or result["integrity"] != "ok" or result["foreign_keys"]:
            raise SystemExit(1)
    elif args.command == "backup":
        from .backup import create_backup

        with db.transaction() as c:
            owner = c.scalar("SELECT id FROM profiles LIMIT 1")
        print(json.dumps(create_backup(db, owner), ensure_ascii=False, indent=2))
    elif args.command == "restore-preview":
        from .backup import preview

        if not args.file:
            parser.error("restore-preview 需要 --file")
        print(json.dumps(preview(settings, Path(args.file).read_bytes()), ensure_ascii=False, indent=2))
    elif args.command == "restore":
        from .backup import perform_restore

        if not args.preview_id:
            parser.error("restore 需要已校验的 --preview-id")
        print(json.dumps(perform_restore(db, args.preview_id), ensure_ascii=False, indent=2))
    elif args.command == "openapi":
        from .api import create_app

        target = Path(args.file or "../artifacts/openapi.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(create_app(settings).openapi(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(str(target.resolve()))


if __name__ == "__main__":
    main()
