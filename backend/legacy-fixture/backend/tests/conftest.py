"""Integration fixtures: every test uses an actual temporary SQLite WAL file."""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from knowledge_world.api import create_app
from knowledge_world.common import uid, local_ms
from knowledge_world.config import Settings
from knowledge_world import economy, jobs, learning, review


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

    def point(self, title="定积分的几何意义", subject=None, **values):
        return self.post(
            "/points",
            {"title": title, "subject_id": subject or self.get("/subjects")["items"][0]["id"], **values},
        )

    def card(self, point=None, kind="cloze", **values):
        point = point or self.point()
        return self.post(
            "/cards",
            {
                "point_id": point["id"],
                "type": kind,
                "question": {"text": "写出 apple 的中文含义"},
                "answer": {"accepted": ["苹果"]},
                "explanation": "apple 表示苹果。",
                **values,
            },
        )

    def task(self, point=None, **values):
        point = point or self.point()
        task = self.post(
            "/tasks",
            {
                "title": "解释概念并独立练习",
                "point_id": point["id"],
                "template_code": "new_knowledge",
                "acceptance": {"criteria": ["解释概念"]},
                **values,
            },
        )
        return self.post(f"/tasks/{task['id']}/start", {"expected_version": task["version"]})

    def activity(
        self, point=None, task=None, narrative="我尝试用自己的话解释这个概念。", template="new_knowledge"
    ):
        return self.post(
            "/activities",
            {
                "point_id": task["point_id"] if task else (point or self.point())["id"],
                "task_id": task["id"] if task else None,
                "template_code": task["template_code"] if task else template,
                "narrative_md": narrative,
            },
        )

    def assess(self, activity, verdict="verified", apply=False, **overrides):
        """Inject a labelled validated provider result, never masquerade as real AI."""
        with self.db.transaction(True, self.owner) as c:
            learning.stamp_submission(c, activity["id"])
            inputs = learning.assessment_input(c, activity["id"])
            refs = [x["id"] for x in inputs["evidence"]]
            payload = {
                "verdict": verdict,
                "difficulty": inputs["task"]["quoted_difficulty"],
                "breakthrough": "none",
                "completed_criteria": inputs["task"]["criteria"] if verdict == "verified" else [],
                "missing_criteria": [] if verdict == "verified" else inputs["task"]["criteria"],
                "evidence_refs": refs,
                "point_results": [
                    {
                        "point_id": inputs["point"]["id"],
                        "can_explain": verdict in {"verified", "progress"},
                        "can_apply_independently": apply,
                        "is_delayed_verification": False,
                        "supporting_refs": refs,
                    }
                ],
                "reasoning_summary": "TEST FIXTURE: validated assessment protocol",
                "next_action": "继续复习",
                **overrides,
            }
            return learning.accept_assessment(c, activity["id"], payload, {"is_test_adapter": True})

    def attempt(self, card, kind="review"):
        with self.db.transaction(True, self.owner) as c:
            row = review.create_attempt(c, card["id"], kind)
            return review.attempt_view(c, row["id"])

    def answer(self, attempt, value="苹果", rating=None):
        return self.post(
            f"/attempts/{attempt['id']}/answer",
            {
                "answer": value,
                "expected_version": attempt["version"],
                **({"rating": rating} if rating else {}),
            },
        )

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

    def redeem(self, code="seed_basic", inputs=None):
        quote = self.post("/redemption-quotes", {"catalog_code": code, "input": inputs or {}})
        return self.post("/redemptions", {"quote_token": quote["quote_token"]})

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
