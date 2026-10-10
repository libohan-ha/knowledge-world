"""Kill and restart real child processes with file-backed SQLite transactions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from knowledge_world.common import uid


@pytest.fixture
def local_provider():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"synthetic":true}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/synthetic", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def child(h, tmp_path, checkpoint="none", server=""):
    signal = tmp_path / (uid() + ".checkpoint")
    command = [sys.executable, str(Path(__file__).with_name("process_driver.py")), "--directory", str(h.db.settings.data_dir), "--clock", str(h.clock()), "--checkpoint", checkpoint, "--signal", str(signal), "--server", server]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return process, signal


def kill(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True, capture_output=True)
        else:
            process.kill()
    process.wait(timeout=10)
    process.stderr.close()


def crash(h, tmp_path, checkpoint, server=""):
    process, signal = child(h, tmp_path, checkpoint, server)
    try:
        deadline = time.monotonic() + 20
        while not signal.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.025)
        assert signal.exists(), process.stderr.read().decode("utf-8") if process.poll() is not None else f"Checkpoint {checkpoint} not reached"
    finally:
        kill(process)


def restart(h, tmp_path, server=""):
    process, _ = child(h, tmp_path, server=server)
    try:
        _, errors = process.communicate(timeout=20)
        assert process.returncode == 0, errors.decode("utf-8")
    finally:
        if process.poll() is None:
            kill(process)


@pytest.mark.parametrize("checkpoint", ["claimed", "simulated", "before_commit", "after_commit"])
def test_battle_process_termination_preserves_snapshot_and_atomic_first_clear(h, tmp_path, checkpoint):
    original = h.post("/world/battles", {"outpost_id": "fern_gate", "team_version": 1, "command_key": uid()})
    crash(h, tmp_path, checkpoint)
    h.clock.advance(seconds=61)
    restart(h, tmp_path)
    result = h.get(f"/world/battles/{original['id']}")
    assert result["snapshot"] == original["snapshot"] and result["seed"] == original["seed"]
    assert result["state"] == "resolved" and result["result"]["first_clear"]
    assert h.get(f"/jobs/{original['job_id']}")["state"] == "succeeded"
    restart(h, tmp_path)
    assert h.scalar("SELECT count(*) FROM occupations") == 1
    assert h.scalar("SELECT count(*) FROM ledger_entries WHERE economic_kind='first_clear'") == 1
    assert h.scalar("SELECT count(*) FROM notifications WHERE event_key LIKE 'battle:%'") == 1
    h.reconcile()


@pytest.mark.parametrize("checkpoint", ["before_external", "after_external", "before_commit", "after_commit"])
def test_assessment_process_termination_keeps_original_fact_and_unknown_request(h, tmp_path, local_provider, checkpoint):
    server, requests = local_provider
    content = "SYNTHETIC 完成晨跑，已保存真实过程描述；进程中断不能丢失输入。"
    original = h.post("/system/actions", {"client_action_id": uid(), "content": content})
    crash(h, tmp_path, checkpoint, server)
    h.clock.advance(seconds=61)
    restart(h, tmp_path, server)
    action = h.get(f"/system/actions/{original['id']}")
    assert action["content"] == content and action["job_id"] == original["job_id"]
    if checkpoint in {"before_external", "after_commit"}:
        assert action["state"] == "settled" and action["net_points"] == 30
        assert h.scalar("SELECT count(*) FROM ledger_entries WHERE origin_type='system_action'") == 1
    else:
        assert action["state"] == "needs_review" and action["net_points"] == 0
        job = h.get(f"/jobs/{original['job_id']}")
        assert job["state"] == "needs_review" and job["last_error"]["code"] == "PROVIDER_RESULT_UNKNOWN"
        assert h.get("/wallet")["available_points"] == 0
    assert len(requests) == 1, "Unknown paid request must not be silently sent again"
    h.reconcile()


@pytest.mark.parametrize("checkpoint", ["after_external", "after_tool", "after_commit"])
def test_agent_process_recovery_keeps_run_and_committed_tool_receipt(h, tmp_path, local_provider, checkpoint):
    server, requests = local_provider
    thread = h.post("/system/threads", {"title": "SYNTHETIC 原会话"})
    body = {"client_message_id": uid(), "content": "SYNTHETIC 完成晨跑及拉伸，有完整过程说明。"}
    original = h.post(f"/system/threads/{thread['id']}/messages", body)
    crash(h, tmp_path, checkpoint, server)
    count = len(requests)
    h.clock.advance(seconds=61)
    restart(h, tmp_path, server)
    repeated = h.post(f"/system/threads/{thread['id']}/messages", body)
    assert repeated["run_id"] == original["run_id"] and repeated["job_id"] == original["job_id"]
    assert len(requests) == count
    history = h.get(f"/system/threads/{thread['id']}")
    assert history["messages"][0]["content_md"] == body["content"]
    assert h.get("/wallet")["available_points"] == (0 if checkpoint == "after_external" else 30)
    if checkpoint != "after_commit":
        continued = h.post(f"/system/messages/{original['message_id']}/resume")
        assert continued["run_id"] == original["run_id"]
        restart(h, tmp_path, server)
    assert h.get("/wallet")["available_points"] == 30
    assert h.scalar("SELECT count(*) FROM system_actions") == 1
    assert h.scalar("SELECT count(*) FROM ledger_entries WHERE origin_type='system_action'") == 1
    assert h.get(f"/jobs/{original['job_id']}")["state"] == "succeeded"
    h.reconcile()
