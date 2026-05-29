"""Codex-backed mobile forensic agent bridge for ForensiFlow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_RUNNER = REPO_ROOT / "tools" / "run_codex_forensiflow_agent.py"
DEFAULT_FULL_RUNNER = REPO_ROOT / "tools" / "run_codex_forensiflow_full_agent.py"
DEFAULT_CODEX_HOME = REPO_ROOT / ".codex-forensiflow-agent"


def run_codex_forensiflow_agent(
    workspace: str | Path,
    target: str = "",
    timeout_seconds: int = 900,
    codex_home: str | Path | None = None,
    runner: str | Path | None = None,
    model: str = "",
) -> Dict[str, Any]:
    """Run Codex on a ForensiFlow script_workspace.

    This is the one-line callable entry point:

        run_codex_forensiflow_agent(script_workspace, target)
    """

    workspace_path = Path(workspace).resolve()
    runner_path = Path(runner or DEFAULT_RUNNER).resolve()
    codex_home_path = Path(codex_home or os.getenv("FORENSIFLOW_CODEX_HOME") or DEFAULT_CODEX_HOME).resolve()

    cmd = [
        sys.executable,
        str(runner_path),
        str(workspace_path),
        "--timeout-seconds",
        str(int(timeout_seconds)),
        "--codex-home",
        str(codex_home_path),
    ]
    if target:
        cmd.extend(["--target", target])
    if model:
        cmd.extend(["--model", model])

    process = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, int(timeout_seconds) + 30),
    )

    result_path = workspace_path / "codex_agent" / "result.json"
    result: Dict[str, Any] = {}
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            result = {"ok": False, "error": f"failed to parse {result_path}: {exc}"}
    if not result:
        result = {
            "ok": False,
            "returncode": process.returncode,
            "workspace": str(workspace_path),
            "codex_home": str(codex_home_path),
            "error": "codex runner did not produce result.json",
        }

    result.setdefault("returncode", process.returncode)
    result.setdefault("stdout_tail", (process.stdout or "")[-4000:])
    result.setdefault("stderr_tail", (process.stderr or "")[-4000:])
    result.setdefault("workspace", str(workspace_path))
    result.setdefault("codex_home", str(codex_home_path))
    return result


def run_for_context(context: Any, timeout_seconds: int = 900, model: str = "") -> Dict[str, Any]:
    """Run the Codex script agent for a MobileAgentContext-like object."""

    workspace = getattr(context, "script_workspace", None)
    if workspace is None:
        raise ValueError("context.script_workspace is not initialized")
    return run_codex_forensiflow_agent(
        workspace=workspace,
        target=str(getattr(context, "target", "") or ""),
        timeout_seconds=timeout_seconds,
        model=model,
    )


def run_codex_forensiflow_full_agent(
    device_serial: str,
    package_name: str,
    app_name: str,
    target: str,
    constraint: str = "",
    run_root: str | Path = "data/codex_mobile_agent_runs",
    timeout_seconds: int = 1800,
    max_attempts: int = 8,
    codex_home: str | Path | None = None,
    model: str = "",
    prompt_mode: str = "simple",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run Codex as the full navigation + extraction scheduler."""

    codex_home_path = Path(codex_home or os.getenv("FORENSIFLOW_CODEX_HOME") or DEFAULT_CODEX_HOME).resolve()
    full_max_attempts = int(os.getenv("FORENSIFLOW_CODEX_MAX_ATTEMPTS", str(int(max_attempts))))
    cmd = [
        sys.executable,
        str(DEFAULT_FULL_RUNNER),
        "--device-serial",
        device_serial,
        "--package-name",
        package_name,
        "--app-name",
        app_name,
        "--target",
        target,
        "--run-root",
        str(run_root),
        "--timeout-seconds",
        str(int(timeout_seconds)),
        "--max-attempts",
        str(full_max_attempts),
        "--codex-home",
        str(codex_home_path),
        "--prompt-mode",
        prompt_mode,
    ]
    if constraint:
        cmd.extend(["--constraint", constraint])
    if model:
        cmd.extend(["--model", model])
    if dry_run:
        cmd.append("--dry-run")

    process = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def pump(stream, chunks: list[str], target) -> None:
        for line in iter(stream.readline, ""):
            chunks.append(line)
            target.write(line)
            target.flush()

    threads = [
        threading.Thread(target=pump, args=(process.stdout, stdout_chunks, sys.stdout), daemon=True),
        threading.Thread(target=pump, args=(process.stderr, stderr_chunks, sys.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        returncode = process.wait(timeout=max(1, int(timeout_seconds) * max(1, full_max_attempts) + 60))
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = -1
    for thread in threads:
        thread.join(timeout=2)

    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)
    if dry_run:
        return {
            "ok": returncode == 0,
            "dry_run": True,
            "returncode": returncode,
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
        }

    result: Dict[str, Any] = {}
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                result = json.loads(line)
                break
            except Exception:
                pass
    if not result:
        result = {
            "ok": False,
            "returncode": returncode,
            "error": "codex full-agent runner did not print result JSON",
        }
    result.setdefault("returncode", returncode)
    result.setdefault("stdout_tail", stdout[-4000:])
    result.setdefault("stderr_tail", stderr[-4000:])
    return result
