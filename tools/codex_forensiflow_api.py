#!/usr/bin/env python3
"""Small HTTP API for running the Codex ForensiFlow mobile script agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "tools" / "run_codex_forensiflow_agent.py"
JOBS: dict[str, dict[str, Any]] = {}


def _start_job(payload: dict[str, Any]) -> str:
    workspace = payload.get("workspace")
    if not workspace:
        raise ValueError("workspace is required")
    job_id = uuid.uuid4().hex
    cmd = [sys.executable, str(RUNNER), str(Path(workspace).expanduser())]
    if payload.get("target"):
        cmd.extend(["--target", str(payload["target"])])
    if payload.get("timeout_seconds"):
        cmd.extend(["--timeout-seconds", str(int(payload["timeout_seconds"]))])
    if payload.get("json"):
        cmd.append("--json")

    job_dir = REPO_ROOT / "data" / "codex_forensiflow_api_jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = job_dir / "stdout.txt"
    stderr_path = job_dir / "stderr.txt"
    out = stdout_path.open("wb")
    err = stderr_path.open("wb")
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=out, stderr=err)
    JOBS[job_id] = {
        "id": job_id,
        "status": "running",
        "returncode": None,
        "cmd": cmd,
        "workspace": str(workspace),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }

    def wait() -> None:
        rc = proc.wait()
        out.close()
        err.close()
        JOBS[job_id]["returncode"] = rc
        JOBS[job_id]["status"] = "succeeded" if rc == 0 else "failed"

    threading.Thread(target=wait, daemon=True).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"ok": True})
            return
        if self.path.startswith("/jobs/"):
            job_id = self.path.rsplit("/", 1)[-1]
            job = JOBS.get(job_id)
            self._json(200 if job else 404, job or {"error": "job not found"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/run":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        try:
            job_id = _start_job(payload)
        except Exception as exc:
            self._json(400, {"error": str(exc)})
            return
        self._json(202, {"ok": True, "job_id": job_id, "job": JOBS[job_id]})


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex ForensiFlow agent HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    print(f"listening on http://{args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
