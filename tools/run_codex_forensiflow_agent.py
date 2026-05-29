#!/usr/bin/env python3
"""Run Codex with the ForensiFlow mobile-agent skill on a script workspace."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from runner.forensiflow.core.evidence_integrity import append_chain_event, build_workspace_manifest


DEFAULT_CODEX_HOME = REPO_ROOT / ".codex-forensiflow-agent"
DEFAULT_SKILL = "forensiflow-mobile-agent"
DEFAULT_PROXY_URL = "http://127.0.0.1:8788/healthz"
DEFAULT_MIMO2CODEX = Path("/root/mimo2codex/dist/cli.js")
LOCAL_CODEX_CLI = REPO_ROOT / "external" / "codex" / "codex-cli" / "bin" / "codex.js"
DEFAULT_PROXY_START_TIMEOUT_SECONDS = 30
DEFAULT_PROXY_POLL_SECONDS = 0.5


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _build_prompt(args: argparse.Namespace, workspace: Path) -> str:
    workspace_context = workspace / "workspace_context.json"
    current_xml = workspace / "context" / "current_page.xml"
    outline = workspace / "context" / "current_page_outline.txt"

    context = _read_json(workspace_context)
    target = args.target or str(context.get("task_goal") or "").strip() or "未指定移动取证提取任务"

    return f"""使用 ${args.skill} skills完成{target}的任务

环境信息：
- script_workspace: {workspace}
- workspace_context: {workspace_context}
- current_page.xml: {current_xml}
- current_page_outline.txt: {outline}
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Codex as the ForensiFlow mobile script agent.")
    parser.add_argument("workspace", type=Path, help="script_workspace directory containing workspace_context.json.")
    parser.add_argument("--target", default="", help="Override target text passed to Codex.")
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--skill", default=DEFAULT_SKILL)
    parser.add_argument("--model", default="", help="Optional Codex model override.")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--sandbox",
        choices=["workspace-write", "danger-full-access"],
        default=os.getenv("FORENSIFLOW_CODEX_SCRIPT_SANDBOX", "workspace-write"),
        help="Codex sandbox for script-workspace repair. Use danger-full-access only when live adb/uiautomator2 access is needed.",
    )
    parser.add_argument("--json", action="store_true", help="Use Codex JSONL output.")
    parser.add_argument("--no-start-proxy", action="store_true", help="Do not auto-start the local MIMO responses proxy.")
    parser.add_argument("--dry-run", action="store_true", help="Print command and prompt without running Codex.")
    return parser


def _proxy_health(url: str = DEFAULT_PROXY_URL) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if not (200 <= resp.status < 300):
                return {}
            return json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return {}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _resolve_node_binary() -> str:
    override = os.getenv("FORENSIFLOW_MIMO2CODEX_NODE") or os.getenv("MIMO2CODEX_NODE")
    if override:
        return override
    nvm_candidates = sorted(
        (Path.home() / ".nvm" / "versions" / "node").glob("v20*/bin/node"),
        key=lambda path: str(path),
        reverse=True,
    )
    for candidate in nvm_candidates:
        if candidate.exists():
            return str(candidate)
    system_node = shutil.which("node")
    if system_node:
        return system_node
    return "node"


def _ensure_proxy(codex_home: Path) -> None:
    health = _proxy_health()
    if health.get("name") == "mimo2codex":
        return
    if health.get("ok"):
        raise RuntimeError(
            f"port 8788 is occupied by a non-mimo2codex proxy: {health}. "
            "Stop it before running the ForensiFlow Codex agent."
        )
    proxy = Path(os.getenv("FORENSIFLOW_MIMO2CODEX_CLI") or DEFAULT_MIMO2CODEX)
    if not proxy.exists():
        raise FileNotFoundError(f"mimo2codex CLI not found: {proxy}")
    auth_path = codex_home / "auth.json"
    api_key = ""
    if auth_path.exists():
        try:
            api_key = json.loads(auth_path.read_text(encoding="utf-8")).get("OPENAI_API_KEY", "")
        except Exception:
            api_key = ""
    log_path = codex_home / "proxy.log"
    log_file = log_path.open("ab")
    env = os.environ.copy()
    if api_key and not env.get("MIMO_API_KEY"):
        env["MIMO_API_KEY"] = api_key
    start_timeout = max(5, _env_int("FORENSIFLOW_MIMO2CODEX_HEALTH_TIMEOUT_SECONDS", DEFAULT_PROXY_START_TIMEOUT_SECONDS))
    poll_seconds = max(0.1, float(os.getenv("FORENSIFLOW_MIMO2CODEX_HEALTH_POLL_SECONDS") or DEFAULT_PROXY_POLL_SECONDS))
    enable_admin = _env_bool("FORENSIFLOW_MIMO2CODEX_ENABLE_ADMIN", _env_bool("MIMO2CODEX_ENABLE_ADMIN", False))
    cmd = [
        _resolve_node_binary(),
        str(proxy),
        "--port",
        "8788",
        "--base-url",
        (
            os.getenv("FORENSIFLOW_MIMO_BASE_URL")
            or os.getenv("MIMO_API_BASE")
            or os.getenv("FORENSIFLOW_API_BASE")
            or "https://your-openai-compatible-endpoint/v1"
        ),
        "--data-dir",
        str(codex_home / "mimo2codex-data"),
        "--no-update-check",
    ]
    if not enable_admin:
        cmd.append("--no-admin")
    subprocess.Popen(
        cmd,
        cwd=str(codex_home),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + start_timeout
    while time.time() < deadline:
        if _proxy_health().get("name") == "mimo2codex":
            return
        time.sleep(poll_seconds)
    proxy_tail = ""
    try:
        proxy_tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
    except Exception:
        proxy_tail = ""
    raise RuntimeError(
        "mimo2codex proxy did not become healthy on http://127.0.0.1:8788/healthz "
        f"within {start_timeout}s. "
        + (f"proxy log tail:\n{proxy_tail}" if proxy_tail else "proxy log tail unavailable.")
    )


def _codex_cmd_prefix() -> list[str]:
    override = os.getenv("FORENSIFLOW_CODEX_BIN")
    if override:
        return shlex.split(override)
    return [_resolve_node_binary(), str(LOCAL_CODEX_CLI)]


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _records_count(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return -1
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return -1
    return sum(1 for item in records if isinstance(item, dict))


def _workspace_artifacts(workspace: Path) -> dict[str, Any]:
    records_path = workspace / "records.json"
    records_debug_path = workspace / "records_debug.json"
    action_path = workspace / "action_path.json"
    generated_script_path = workspace / "generated_script.py"
    run_state_path = workspace / "run_state.json"
    run_state = _load_json_object(run_state_path)
    records_count = _records_count(records_path) if records_path.exists() else 0
    records_debug_count = _records_count(records_debug_path) if records_debug_path.exists() else 0
    return {
        "action_path_exists": action_path.exists(),
        "generated_script_exists": generated_script_path.exists(),
        "records_exists": records_path.exists(),
        "records_debug_exists": records_debug_path.exists(),
        "run_state_exists": run_state_path.exists(),
        "run_state_status": run_state.get("status", ""),
        "run_state_errors": run_state.get("errors", []),
        "records_count": records_count,
        "records_debug_count": records_debug_count,
        "run_state_total_records": run_state.get("total_records"),
    }


def _artifacts_ok(artifacts: dict[str, Any]) -> bool:
    records_count = int(artifacts.get("records_count") or 0)
    records_debug_count = int(artifacts.get("records_debug_count") or 0)
    total_records = artifacts.get("run_state_total_records")
    total_records_zero = False
    if isinstance(total_records, (int, float)):
        total_records_zero = int(total_records) <= 0
    return (
        bool(artifacts.get("action_path_exists"))
        and bool(artifacts.get("generated_script_exists"))
        and bool(artifacts.get("records_exists"))
        and bool(artifacts.get("records_debug_exists"))
        and bool(artifacts.get("run_state_exists"))
        and artifacts.get("run_state_status") == "completed"
        and not artifacts.get("run_state_errors")
        and records_count > 0
        and records_debug_count == records_count
        and not total_records_zero
    )


def main() -> int:
    args = build_parser().parse_args()
    workspace = args.workspace.resolve()
    if not workspace.exists():
        raise SystemExit(f"workspace not found: {workspace}")
    if not (workspace / "workspace_context.json").exists():
        raise SystemExit(f"workspace_context.json not found under: {workspace}")

    codex_home = args.codex_home.resolve()
    skill_dir = codex_home / "skills" / args.skill
    if not (skill_dir / "SKILL.md").exists():
        raise SystemExit(f"skill not installed in CODEX_HOME: {skill_dir}")
    if not args.no_start_proxy:
        _ensure_proxy(codex_home)

    output_dir = workspace / "codex_agent"
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = output_dir / "prompt.txt"
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    last_message_path = output_dir / "last_message.md"
    result_path = output_dir / "result.json"

    prompt = _build_prompt(args, workspace)
    prompt_path.write_text(prompt, encoding="utf-8")
    append_chain_event(
        workspace,
        "script_agent_prompt_written",
        {
            "target": args.target,
            "prompt_path": str(prompt_path.relative_to(workspace)),
            "sandbox": args.sandbox,
        },
        actor="codex_script_agent_runner",
    )

    cmd = [
        *_codex_cmd_prefix(),
        "exec",
        "--cd",
        str(workspace),
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--output-last-message",
        str(last_message_path),
    ]
    if args.json:
        cmd.append("--json")
    if args.model:
        cmd.extend(["--model", args.model])
    cmd.append("-")

    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)

    if args.dry_run:
        print("CODEX_HOME=" + str(codex_home))
        print(" ".join(cmd))
        print("\n--- prompt ---\n" + prompt)
        build_workspace_manifest(workspace, target=args.target)
        return 0

    started = time.time()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(workspace),
        env=env,
        bufsize=1,
    )
    assert proc.stdin is not None
    proc.stdin.write(prompt)
    proc.stdin.close()

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def pump(stream, chunks: list[str], log_path: Path, target) -> None:
        with log_path.open("w", encoding="utf-8") as log:
            for line in iter(stream.readline, ""):
                chunks.append(line)
                log.write(line)
                log.flush()
                target.write(line)
                target.flush()

    threads = [
        threading.Thread(target=pump, args=(proc.stdout, stdout_chunks, stdout_path, sys.stdout), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, stderr_chunks, stderr_path, sys.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        return_code = proc.wait(timeout=args.timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        return_code = -1
    for thread in threads:
        thread.join(timeout=2)
    duration = time.time() - started

    artifacts = _workspace_artifacts(workspace)
    result = {
        "ok": return_code == 0 and _artifacts_ok(artifacts),
        "returncode": return_code,
        "duration_seconds": round(duration, 3),
        "workspace": str(workspace),
        "codex_home": str(codex_home),
        "prompt_path": str(prompt_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "last_message_path": str(last_message_path),
        "evidence_manifest": str(workspace / "evidence_manifest.json"),
        **artifacts,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    append_chain_event(
        workspace,
        "script_agent_finished",
        {
            "ok": bool(result["ok"]),
            "returncode": return_code,
            **artifacts,
        },
        actor="codex_script_agent_runner",
    )
    build_workspace_manifest(workspace, target=args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
