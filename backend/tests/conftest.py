"""Integration fixtures: every test uses an actual temporary SQLite WAL file."""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from knowledge_world.api import create_app
from knowledge_world.common import uid, local_ms
from knowledge_world.config import Settings
from knowledge_world import economy, jobs


class Clock:
    def __init__(self):
        self.value = local_ms("2026-10-10", "06:30")

    def __call__(self):
        return self.value

    def set(self, day, time="12:00"):
        self.value = local_ms(day, time)

    def advance(self, seconds=0, days=0):
        self.value += (seconds + days * 86400) * 1000


@dataclass
class Harness:
    client: TestClient
    clock: Clock
    db: object
    owner: str

    def headers(self, key=None):
        return {
            "Origin": "http://testserver",
            "X-CSRF-Token": self.client.cookies.get("kw_csrf", ""),
            "Idempotency-Key": key or uid(),
        }

    def request(self, method, path, body=None, *, status=None, key=None, **kwargs):
        response = self.client.request(
            method,
            "/api/v1" + path,
            headers=self.headers(key),
            **({"json": body} if body is not None else {}),
            **kwargs,
        )
        if status is not None:
            assert response.status_code == status, response.text
        else:
            assert response.status_code in {200, 201, 202}, response.text
        return response

    def get(self, path):
        return self.request("GET", path).json()["data"]

    def post(self, path, body=None, **kwargs):
        response = self.request("POST", path, {} if body is None else body, **kwargs)
        return response.json().get("data", response.json())

    def patch(self, path, body, **kwargs):
        return self.request("PATCH", path, body, **kwargs).json().get("data")

    def fund(self, amount):
        with self.db.transaction(True, self.owner) as c:
            economy.append(
                c,
                "achievement",
                "achievement",
                f"TEST-FUND:{uid()}",
                "achievement",
                uid(),
                available=amount,
                detail={"test_fixture": True},
            )

    def drain(self, limit=30):
        count = 0
        while count < limit and jobs.run_once(self.db, "test-worker"):
            count += 1
        assert count < limit, "Worker did not become idle"
        return count

    def reconcile(self):
        result = self.get("/diagnostics")["reconciliation"]
        assert result == {"ok": True, "differences": [], "integrity": "ok", "foreign_keys": []}

    def scalar(self, sql, params=None):
        with self.db.transaction(owner=self.owner) as c:
            return c.scalar(sql, params)


@pytest.fixture
def h(tmp_path):
    clock = Clock()
    app = create_app(
        Settings(data_dir=tmp_path / "world", mode="test", fake_provider=True, origin="http://testserver"),
        clock,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/setup",
            json={"display_name": "验收账户", "password": "testing-password", "timezone": "Asia/Shanghai"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200, response.text
        yield Harness(client, clock, app.state.db, response.json()["data"]["profile"]["id"])
