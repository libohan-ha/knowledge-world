"""Exporting an API contract must never initialize or migrate user data."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from knowledge_world.config import ROOT


@pytest.mark.parametrize("existing_database", [False, True])
def test_openapi_export_leaves_selected_database_untouched(tmp_path, existing_database):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "knowledge-world.db"
    if existing_database:
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE preserved_history (value TEXT)")
            connection.execute("INSERT INTO preserved_history VALUES ('SYNTHETIC prior data')")
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data_dir.iterdir()}
    output = tmp_path / "openapi.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith("AI_")}
    env.update(KW_DATA_DIR=str(data_dir), KW_MODE="production", KW_FAKE_PROVIDER="0", PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, "-m", "knowledge_world.cli", "openapi", "--file", str(output)],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    contract = json.loads(output.read_text(encoding="utf-8"))
    assert "/api/v1/system/checkin" in contract["paths"]
    assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in data_dir.iterdir()} == before
