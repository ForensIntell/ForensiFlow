#!/usr/bin/env python3
"""Run Codex as the full ForensiFlow mobile agent."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from run_codex_forensiflow_agent import DEFAULT_CODEX_HOME, DEFAULT_SKILL, _codex_cmd_prefix, _ensure_proxy
from run_codex_forensiflow_agent import _artifacts_ok, _workspace_artifacts
from device_serial import resolve_device_serial
from runner.forensiflow.agents.codex_mobile.rag_export import export_full_agent_reuse_artifacts
from runner.forensiflow.core.evidence_integrity import append_chain_event, build_manifest


COMPLETION_STABLE_SECONDS = float(os.getenv("FORENSIFLOW_CODEX_COMPLETION_STABLE_SECONDS", "12"))
COMPLETION_POLL_SECONDS = float(os.getenv("FORENSIFLOW_CODEX_COMPLETION_POLL_SECONDS", "2"))
IDLE_TIMEOUT_SECONDS = float(os.getenv("FORENSIFLOW_CODEX_IDLE_TIMEOUT_SECONDS", "240"))
RETRY_BACKOFF_SECONDS = float(os.getenv("FORENSIFLOW_CODEX_RETRY_BACKOFF_SECONDS", "30"))


def _build_prompt(args: argparse.Namespace, run_dir: Path, workspace: Path) -> str:
    if args.manual_prompt:
        return args.manual_prompt

    return f"""使用 ${args.skill} skills完成{args.target}的任务

环境信息：
- app: {args.app_name} ({args.package_name})
- device serial: {args.device_serial}
- run_dir: {run_dir}
- script_workspace: {workspace}
- ANDROID_SERIAL={args.device_serial}
- constraint: {args.constraint or "只读取证，不发送、不删除、不编辑、不支付、不修改应用状态。"}

执行要求：
- 直接完成导航、探索、脚本生成、运行和验证，不要只输出计划。
- 不要调用计划工具，不要停在 checklist、下一步说明或状态清单；第一步必须实际执行设备连接/页面探测命令。
- package_name 是权威输入，不要用 `pm list packages | grep <app name>` 判定应用是否安装；直接用 package_name 启动应用。
- 单个探测命令返回非 0 时不要停住，改用 uiautomator2/adb 的下一种方法继续推进。
- uiautomator2 已安装；不要执行 pip install。
- 需要创建或修改 workspace 文件时，不要调用 apply_patch 工具；请使用 Python 脚本写入文件。
- 最终产物必须写在 script_workspace 根目录：action_path.json、generated_script.py、records.json、records_debug.json、run_state.json、workspace_context.json。
- records.json 与 records_debug.json 必须能通过 forensiflow-mobile-agent validator。
- action_path.json 会直接进入 RAG 复用库，必须从冷启动可重放：不要省略打开抽屉、打开三点菜单、点击底部 tab、返回上级页、等待页面加载等必要导航动作。
- 复用路径优先写稳定 target：resource-id、content-desc、可见文本；不要只写坐标或依赖“当前页面刚好已经打开”的状态。
- 若任务是 Gmail Sent/已发送，action_path 必须先打开 Gmail 抽屉式导航栏，再点击 已发送/Sent；若为空，records.json 仍需输出一条 empty_state 记录，且必须包含非空 `entity_type="empty_state"`、`mailbox="Sent"`、`empty_state_text`、`content_text`、`title`；如果 XML 的 `empty_text` 节点存在但 text 为空，使用稳定文案 `“已发送”中没有任何内容` 兜底。
- 若任务是 Gmail 收件箱/线程详情，当前若停留在已发送/Sent、空状态页或其他邮箱标签，必须先通过抽屉导航进入收件箱/主要列表，再打开第一封可见邮件线程；不要把 Sent 空状态当作收件箱线程详情。
- 若任务是 Chrome 下载+书签，generated_script.py 必须同时覆盖下载页和书签页；书签入口优先使用 menu_button 与 all_bookmarks_menu_id/书签 文本，不要把可恢复的导航重试写入 run_state.errors。
- 若任务是 Google Maps Saved，action_path 必须先进入底部“我”tab，再进入“已保存/您的地点”；若任务是最近搜索/最近查看，必须清楚记录搜索栏或“我 -> 地图历史记录 -> 搜索过/查看过”的完整只读路径。
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Codex as full ForensiFlow mobile agent.")
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 device serial.")
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--constraint", default="")
    parser.add_argument("--run-root", type=Path, default=Path("data/codex_mobile_agent_runs"))
    parser.add_argument("--codex-home", type=Path, default=DEFAULT_CODEX_HOME)
    parser.add_argument("--skill", default=DEFAULT_SKILL)
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--max-attempts", type=int, default=8, help="Retry Codex if it exits before records are produced.")
    parser.add_argument(
        "--sandbox",
        choices=["workspace-write", "danger-full-access"],
        default=os.getenv("FORENSIFLOW_CODEX_SANDBOX", "danger-full-access"),
        help="Codex sandbox. Full mobile control needs danger-full-access because adb/uiautomator2 require local sockets.",
    )
    parser.add_argument("--prompt-mode", choices=["simple", "manual", "structured"], default="simple")
    parser.add_argument("--manual-prompt", default=os.getenv("FORENSIFLOW_CODEX_MANUAL_PROMPT", ""))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-start-proxy", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _artifact_signature(workspace: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a small stability signature for final workspace artifacts."""
    names = [
        "action_path.json",
        "generated_script.py",
        "records.json",
        "records_debug.json",
        "run_state.json",
    ]
    signature = []
    for name in names:
        path = workspace / name
        try:
            stat = path.stat()
        except FileNotFoundError:
            signature.append((name, -1, -1))
            continue
        signature.append((name, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(signature)


def _terminate_completed_process(proc: subprocess.Popen[str], grace_seconds: float = 10.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _workspace_activity_time(workspace: Path) -> float:
    latest = 0.0
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        try:
            latest = max(latest, path.stat().st_mtime)
        except FileNotFoundError:
            continue
    return latest


def _retryable_codex_failure(stderr_path: Path, stdout_path: Path) -> bool:
    text = ""
    for path in (stderr_path, stdout_path):
        try:
            text += "\n" + path.read_text(encoding="utf-8", errors="replace")[-12000:]
        except Exception:
            continue
    lowered = text.casefold()
    retry_markers = [
        "we're currently experiencing high demand",
        "currently experiencing high demand",
        "temporary errors",
        "error: reconnecting",
        "connection error",
        "timed out",
        "timeout",
        "rate limit",
        "429",
        "502",
        "503",
        "504",
        "econnreset",
        "socket hang up",
    ]
    return any(marker in lowered for marker in retry_markers)


def main() -> int:
    args = build_parser().parse_args()
    args.device_serial = resolve_device_serial(args.device_serial, required=True)
    args.codex_home = args.codex_home.resolve()
    if not (args.codex_home / "skills" / args.skill / "SKILL.md").exists():
        raise SystemExit(f"skill not installed in CODEX_HOME: {args.codex_home / 'skills' / args.skill}")
    if not args.no_start_proxy and not args.dry_run:
        _ensure_proxy(args.codex_home)

    serial = args.device_serial
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = (args.run_root / serial / f"codex_full_agent_run_{stamp}").resolve()
    workspace = run_dir / "script_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "context").mkdir(parents=True, exist_ok=True)

    output_dir = workspace / "codex_agent"
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = output_dir / "prompt.txt"
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    last_message_path = output_dir / "last_message.md"
    result_path = output_dir / "result.json"

    prompt = _build_prompt(args, run_dir, workspace)
    prompt_path.write_text(prompt, encoding="utf-8")
    append_chain_event(
        run_dir,
        "full_agent_prompt_written",
        {
            "device_serial": args.device_serial,
            "package_name": args.package_name,
            "app_name": args.app_name,
            "target": args.target,
            "constraint": args.constraint,
            "prompt_path": str(prompt_path.relative_to(run_dir)),
            "workspace": str(workspace.relative_to(run_dir)),
        },
        actor="codex_full_agent_runner",
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
    env["CODEX_HOME"] = str(args.codex_home)
    if args.device_serial:
        env["ANDROID_SERIAL"] = args.device_serial
        env["FORENSIFLOW_DEVICE_SERIAL"] = args.device_serial
    env.update(
        {
            "FORENSIFLOW_AGENT_WORKSPACE": str(workspace),
            "FORENSIFLOW_TARGET": args.target,
            "FORENSIFLOW_APP_PACKAGE": args.package_name,
            "FORENSIFLOW_APP_NAME": args.app_name,
        }
    )

    if args.dry_run:
        print("CODEX_HOME=" + str(args.codex_home))
        print(" ".join(cmd))
        print("\n--- prompt ---\n" + prompt)
        build_manifest(
            run_dir,
            device_serial=args.device_serial,
            app_name=args.app_name,
            package_name=args.package_name,
            target=args.target,
        )
        return 0

    started = time.time()
    return_code = 0
    attempt_count = 0

    def run_codex_attempt(attempt: int, attempt_prompt: str) -> int:
        (output_dir / f"prompt_attempt_{attempt}.txt").write_text(attempt_prompt, encoding="utf-8")

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
        proc.stdin.write(attempt_prompt)
        proc.stdin.close()

        def pump(stream, log_path: Path, target) -> None:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n===== Codex attempt {attempt} =====\n")
                for line in iter(stream.readline, ""):
                    log.write(line)
                    log.flush()
                    target.write(line)
                    target.flush()

        threads = [
            threading.Thread(target=pump, args=(proc.stdout, stdout_path, sys.stdout), daemon=True),
            threading.Thread(target=pump, args=(proc.stderr, stderr_path, sys.stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()
        rc = 0
        try:
            deadline = time.time() + max(1, int(args.timeout_seconds))
            ok_since = 0.0
            ok_signature: tuple[tuple[str, int, int], ...] | None = None
            poll_seconds = max(0.2, COMPLETION_POLL_SECONDS)
            stable_seconds = max(0.0, COMPLETION_STABLE_SECONDS)
            idle_timeout = max(0.0, IDLE_TIMEOUT_SECONDS)
            last_activity = max(time.time(), _workspace_activity_time(workspace))
            while True:
                current_rc = proc.poll()
                if current_rc is not None:
                    rc = current_rc
                    break

                artifacts = _workspace_artifacts(workspace)
                activity_time = _workspace_activity_time(workspace)
                if activity_time > last_activity:
                    last_activity = activity_time
                if _artifacts_ok(artifacts):
                    signature = _artifact_signature(workspace)
                    now = time.time()
                    if signature == ok_signature:
                        if ok_since and now - ok_since >= stable_seconds:
                            print(
                                "[forensiflow-codex] final artifacts are complete and stable; "
                                f"ending Codex attempt {attempt}",
                                file=sys.stderr,
                                flush=True,
                            )
                            _terminate_completed_process(proc)
                            rc = 0
                            break
                    else:
                        ok_signature = signature
                        ok_since = now
                else:
                    ok_signature = None
                    ok_since = 0.0

                if idle_timeout and time.time() - last_activity >= idle_timeout:
                    print(
                        f"[forensiflow-codex] attempt {attempt} idle for {idle_timeout:.0f}s without complete artifacts; "
                        "terminating Codex for retry",
                        file=sys.stderr,
                        flush=True,
                    )
                    proc.kill()
                    rc = -1
                    break

                if time.time() >= deadline:
                    if _artifacts_ok(_workspace_artifacts(workspace)):
                        print(
                            f"[forensiflow-codex] attempt {attempt} reached timeout with complete artifacts; "
                            "ending Codex attempt as successful",
                            file=sys.stderr,
                            flush=True,
                        )
                        _terminate_completed_process(proc)
                        rc = 0
                    else:
                        print(
                            f"[forensiflow-codex] attempt {attempt} timed out after {args.timeout_seconds}s; terminating Codex",
                            file=sys.stderr,
                            flush=True,
                        )
                        proc.kill()
                        rc = -1
                    break
                time.sleep(poll_seconds)
        except subprocess.TimeoutExpired:
            print(
                f"[forensiflow-codex] attempt {attempt} timed out after {args.timeout_seconds}s; terminating Codex",
                file=sys.stderr,
                flush=True,
            )
            proc.kill()
            rc = -1
        except KeyboardInterrupt:
            proc.kill()
            raise
        for thread in threads:
            thread.join(timeout=2)
        return rc

    current_prompt = prompt
    for attempt in range(1, max(1, args.max_attempts) + 1):
        attempt_count = attempt
        try:
            return_code = run_codex_attempt(attempt, current_prompt)
        except KeyboardInterrupt:
            artifacts = _workspace_artifacts(workspace)
            result = {
                "ok": False,
                "returncode": -2,
                "attempts": attempt,
                "duration_seconds": round(time.time() - started, 3),
                "run_dir": str(run_dir),
                "workspace": str(workspace),
                "codex_home": str(args.codex_home),
                "prompt_path": str(prompt_path),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "last_message_path": str(last_message_path),
                "interrupted": True,
                "evidence_manifest": str(run_dir / "evidence_manifest.json"),
                **artifacts,
            }
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            append_chain_event(
                run_dir,
                "full_agent_interrupted",
                {"attempts": attempt, **artifacts},
                actor="codex_full_agent_runner",
            )
            build_manifest(
                run_dir,
                device_serial=args.device_serial,
                app_name=args.app_name,
                package_name=args.package_name,
                target=args.target,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 130
        artifacts = _workspace_artifacts(workspace)
        if _artifacts_ok(artifacts):
            break
        if return_code not in (0, -1):
            if attempt < max(1, args.max_attempts) and _retryable_codex_failure(stderr_path, stdout_path):
                delay = max(0.0, RETRY_BACKOFF_SECONDS)
                print(
                    "[forensiflow-codex] Codex returned a retryable provider/network error; "
                    f"retrying attempt {attempt + 1} after {delay:.0f}s",
                    file=sys.stderr,
                    flush=True,
                )
                if delay:
                    time.sleep(delay)
            else:
                break
        current_prompt = f"""继续执行同一个任务。上一次运行没有完成。请检查当前 workspace 现有产物后直接继续，不要复述历史日志。

使用 ${args.skill} skills完成{args.target}的任务。

环境信息：
- app: {args.app_name} ({args.package_name})
- device serial: {args.device_serial}
- run_dir: {run_dir}
- script_workspace: {workspace}
- ANDROID_SERIAL={args.device_serial}
- constraint: {args.constraint or "只读取证，不发送、不删除、不编辑、不支付、不修改应用状态。"}

执行要求：
- 直接补齐缺失产物并运行验证，不要只输出计划。
- 不要调用计划工具，不要停在 checklist、下一步说明或状态清单；第一步必须实际检查 workspace 或执行设备命令。
- package_name 是权威输入，不要用 `pm list packages | grep <app name>` 判定应用是否安装；直接用 package_name 启动应用。
- 单个探测命令返回非 0 时不要停住，改用 uiautomator2/adb 的下一种方法继续推进。
- 不要调用 apply_patch 工具；创建或修改 workspace 文件时使用 Python 脚本写入文件。
- 最终产物必须写在 script_workspace 根目录。
"""
    duration = time.time() - started

    artifacts = _workspace_artifacts(workspace)
    artifacts_complete = _artifacts_ok(artifacts)
    reuse_artifacts = {"ok": False, "published": False, "reason": "Codex run did not produce complete reusable artifacts"}
    if artifacts_complete:
        try:
            reuse_artifacts = export_full_agent_reuse_artifacts(
                run_dir=run_dir,
                workspace=workspace,
                app_name=args.app_name,
                package_name=args.package_name,
                target=args.target,
                constraint=args.constraint,
                publish=True,
            )
        except Exception as exc:
            reuse_artifacts = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "published": False}
        append_chain_event(
            run_dir,
            "full_agent_reuse_exported",
            reuse_artifacts,
            actor="codex_full_agent_runner",
        )
    result = {
        "ok": artifacts_complete,
        "returncode": return_code,
        "attempts": attempt_count,
        "duration_seconds": round(duration, 3),
        "run_dir": str(run_dir),
        "workspace": str(workspace),
        "codex_home": str(args.codex_home),
        "prompt_path": str(prompt_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "last_message_path": str(last_message_path),
        "evidence_manifest": str(run_dir / "evidence_manifest.json"),
        "reuse_artifacts": reuse_artifacts,
        **artifacts,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    append_chain_event(
        run_dir,
        "full_agent_finished",
        {
            "ok": bool(result["ok"]),
            "returncode": return_code,
            "attempts": attempt_count,
            **artifacts,
        },
        actor="codex_full_agent_runner",
    )
    build_manifest(
        run_dir,
        device_serial=args.device_serial,
        app_name=args.app_name,
        package_name=args.package_name,
        target=args.target,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
