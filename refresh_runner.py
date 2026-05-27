from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_COMMAND = [sys.executable, str(BASE_DIR / "fetch_football_data.py"), "--force-refresh"]
RUNS: dict[str, "RefreshRun"] = {}
RUNS_LOCK = threading.Lock()
CURRENT_RUN_ID: str | None = None


@dataclass
class RefreshRun:
    run_id: str
    status: str
    requested_at: str
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    command: list[str] | None = None
    stdout_tail: list[str] | None = None
    stderr_tail: list[str] | None = None
    reports_index_path: str | None = None
    reports_index_mtime: str | None = None
    error: str | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tail_lines(text: str, limit: int = 80) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-limit:]


def get_runner_secret() -> str:
    return os.getenv("PIPELINE_REFRESH_RUNNER_SECRET", "").strip()


def get_runner_command() -> list[str]:
    override = os.getenv("PIPELINE_REFRESH_COMMAND", "").strip()
    if override:
        return shlex.split(override)
    return list(DEFAULT_COMMAND)


def reports_index_metadata() -> tuple[str | None, str | None]:
    index_path = BASE_DIR / "reports" / "index.json"
    if not index_path.is_file():
        return None, None
    modified_at = datetime.fromtimestamp(index_path.stat().st_mtime, timezone.utc).isoformat()
    return str(index_path), modified_at


def latest_run() -> RefreshRun | None:
    if not RUNS:
        return None
    return max(RUNS.values(), key=lambda run: run.requested_at)


def run_status_url(handler: BaseHTTPRequestHandler, run_id: str) -> str:
    proto = handler.headers.get("X-Forwarded-Proto", "http")
    host = handler.headers.get("Host", f"127.0.0.1:{handler.server.server_port}")
    return f"{proto}://{host}/refresh?run_id={run_id}"


def serialize_run(handler: BaseHTTPRequestHandler, run: RefreshRun) -> dict:
    payload = asdict(run)
    payload["status_url"] = run_status_url(handler, run.run_id)
    return payload


def execute_refresh(run_id: str) -> None:
    global CURRENT_RUN_ID

    command = get_runner_command()

    with RUNS_LOCK:
        run = RUNS[run_id]
        run.status = "running"
        run.started_at = now_iso()
        run.command = command

    try:
        result = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        index_path, index_mtime = reports_index_metadata()

        with RUNS_LOCK:
            run = RUNS[run_id]
            run.return_code = result.returncode
            run.stdout_tail = tail_lines(result.stdout)
            run.stderr_tail = tail_lines(result.stderr)
            run.finished_at = now_iso()
            run.status = "succeeded" if result.returncode == 0 else "failed"
            run.reports_index_path = index_path
            run.reports_index_mtime = index_mtime
    except Exception as exc:
        with RUNS_LOCK:
            run = RUNS[run_id]
            run.status = "failed"
            run.finished_at = now_iso()
            run.error = str(exc)
            run.stderr_tail = [str(exc)]
    finally:
        with RUNS_LOCK:
            if CURRENT_RUN_ID == run_id:
                CURRENT_RUN_ID = None


def start_refresh() -> tuple[RefreshRun, bool]:
    global CURRENT_RUN_ID

    with RUNS_LOCK:
        if CURRENT_RUN_ID:
            current = RUNS.get(CURRENT_RUN_ID)
            if current and current.status in {"queued", "running"}:
                return current, False

        run_id = str(uuid.uuid4())
        run = RefreshRun(run_id=run_id, status="queued", requested_at=now_iso())
        RUNS[run_id] = run
        CURRENT_RUN_ID = run_id

    thread = threading.Thread(target=execute_refresh, args=(run_id,), daemon=True)
    thread.start()
    return run, True


class RefreshRunnerHandler(BaseHTTPRequestHandler):
    server_version = "J-SodraRefreshRunner/1.0"

    def _write_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _is_authorized(self) -> bool:
        expected = get_runner_secret()
        if not expected:
            return True

        auth_header = self.headers.get("Authorization", "")
        if auth_header == f"Bearer {expected}":
            return True

        self._write_json(401, {"error": "Unauthorized"})
        return False

    def do_OPTIONS(self) -> None:
        self._write_json(200, {"ok": True})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/health":
            with RUNS_LOCK:
                current = RUNS.get(CURRENT_RUN_ID) if CURRENT_RUN_ID else None
                latest = latest_run()
            self._write_json(
                200,
                {
                    "ok": True,
                    "current_run": serialize_run(self, current) if current else None,
                    "latest_run": serialize_run(self, latest) if latest else None,
                },
            )
            return

        if parsed.path != "/refresh":
            self._write_json(404, {"error": "Not found"})
            return

        if not self._is_authorized():
            return

        params = parse_qs(parsed.query)
        run_id = params.get("run_id", [None])[0]

        with RUNS_LOCK:
            run = RUNS.get(run_id) if run_id else (RUNS.get(CURRENT_RUN_ID) if CURRENT_RUN_ID else latest_run())

        if not run:
            self._write_json(404, {"error": "Refresh run not found"})
            return

        self._write_json(200, serialize_run(self, run))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/refresh":
            self._write_json(404, {"error": "Not found"})
            return

        if not self._is_authorized():
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length:
            self.rfile.read(content_length)

        run, started = start_refresh()
        self._write_json(
            202,
            {
                **serialize_run(self, run),
                "accepted": started,
                "already_running": not started,
            },
        )


def main() -> int:
    host = os.getenv("PIPELINE_REFRESH_RUNNER_HOST", "0.0.0.0")
    port = int(os.getenv("PIPELINE_REFRESH_RUNNER_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), RefreshRunnerHandler)
    print(f"Refresh runner listening on http://{host}:{port}")
    print(f"Pipeline command: {' '.join(get_runner_command())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())