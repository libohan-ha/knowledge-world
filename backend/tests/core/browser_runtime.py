"""Explicitly synthetic browser runtime; never loads the production data folder.

Uses the real API, migrations, Worker and built React application. Only provider
outputs and the shared clock are test adapters. No extra HTTP test endpoints.
"""
# ruff: noqa: E402 -- standalone helper selects the current source tree first.
import argparse
import json
import sys
import time
from pathlib import Path

import uvicorn

# Running this file directly from an isolated browser process does not install
# the package; resolve the source tree explicitly before importing the app.
SOURCE = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SOURCE))
from knowledge_world.api import create_app
from knowledge_world.common import local_ms
from knowledge_world.config import ROOT, Settings
from knowledge_world.db import Database
from knowledge_world.jobs import run_once
from knowledge_world.worker import maintenance_tick


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["api", "worker"])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    root = args.data_dir.resolve()
    if not root.is_relative_to((ROOT / "artifacts/refactor/runtime").resolve()):
        raise RuntimeError("Browser fixtures require an isolated artifacts/refactor/runtime directory")
    settings = Settings(data_dir=root, mode="test", fake_provider=True, origin=f"http://127.0.0.1:{args.port}")
    marker = root / "synthetic-clock.json"
    if args.role == "api":
        marker.write_text(json.dumps({"synthetic": True, "clock_started": time.time(), "base_ms": local_ms("2026-10-10", "06:45")}), encoding="utf-8")
    clock_data = json.loads(marker.read_text(encoding="utf-8"))

    def clock():
        return clock_data["base_ms"] + int((time.time() - clock_data["clock_started"]) * 1000)

    if args.role == "api":
        uvicorn.run(create_app(settings, clock), host="127.0.0.1", port=args.port, access_log=False)
    else:
        db = Database(settings, clock)
        try:
            while True:
                if not root.joinpath(".maintenance").exists():
                    maintenance_tick(db)
                    run_once(db, "synthetic-browser-worker")
                time.sleep(0.25)
        finally:
            db.engine.dispose()


if __name__ == "__main__":
    main()
