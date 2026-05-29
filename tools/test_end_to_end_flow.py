#!/usr/bin/env python3
"""Experiment runner for the ForensiFlow full planning -> routing -> execution flow."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from device_serial import resolve_device_serial
from runner.forensiflow.core.config import get_llm_config
from runner.forensiflow.core.forensic_planner import ForensicPlanner
from runner.forensiflow.devices.android import AndroidDevice
from run_forensic_plan import ForensicTaskExecutor


DEFAULT_CASE = "这是一次ForensiFlow实验案件，需要验证规划、调度选择、探索生成和经验复用的全流程能力。"
DEFAULT_GOALS = "提取Gmail收件箱列表界面证据，并验证历史经验复用能力。"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 serial.")
    parser.add_argument("--case", default=DEFAULT_CASE)
    parser.add_argument("--goals", default=DEFAULT_GOALS)
    parser.add_argument("--plan", type=Path, default=None, help="Use an existing plan instead of generating one.")
    parser.add_argument("--app", default="", help="Only execute/select one app from the plan.")
    parser.add_argument("--task-index", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--max-apps", type=int, default=1)
    parser.add_argument("--max-tasks-per-app", type=int, default=1)
    parser.add_argument("--selection-only", action="store_true", help="Plan and select routes, but do not execute phone tasks.")
    parser.add_argument("--execute", action="store_true", help="Actually execute selected tasks on the phone.")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data" / "end_to_end_flow_tests")
    parser.add_argument("--json", action="store_true")
    return parser


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _generate_plan(args: argparse.Namespace, cfg, data_dir: Path) -> Path:
    planner = ForensicPlanner(
        api_key=cfg.api_key,
        base_url=cfg.api_base,
        model=cfg.model,
        temperature=0.1,
        data_dir=str(data_dir),
    )
    plan = planner.create_forensic_plan(args.case, args.goals)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    plan_path = data_dir / "plans" / f"e2e_flow_plan_{stamp}.json"
    _write_json(plan_path, plan)
    return plan_path


def run(args: argparse.Namespace) -> Dict[str, Any]:
    if args.execute and args.selection_only:
        raise SystemExit("--execute and --selection-only are mutually exclusive")
    if not args.execute:
        args.selection_only = True

    serial = resolve_device_serial(args.device_serial, required=bool(args.execute))
    data_dir = (args.output_dir / (serial or "selection_only")).resolve()
    cfg = get_llm_config(api_base=args.api_base or None, model=args.model or None)

    plan_path = args.plan.resolve() if args.plan else _generate_plan(args, cfg, data_dir)
    if not plan_path.exists():
        raise SystemExit(f"plan not found: {plan_path}")

    device = AndroidDevice(adb_endpoint=serial) if args.execute else None
    executor = ForensicTaskExecutor(
        device=device,
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        model=cfg.model,
        threshold=args.threshold,
        data_dir=str(data_dir),
    )
    summary = executor.execute_plan(
        plan_file=str(plan_path),
        specific_app=args.app or None,
        specific_task_index=args.task_index,
        max_apps=args.max_apps,
        max_tasks_per_app=args.max_tasks_per_app,
        selection_only=args.selection_only,
    )
    payload = {
        "ok": summary.get("failed_tasks", 0) == 0,
        "mode": "execute" if args.execute else "selection_only",
        "device_serial": serial,
        "plan_path": str(plan_path),
        "data_dir": str(data_dir),
        "summary": summary,
    }
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    result_path = data_dir / f"e2e_flow_result_{stamp}.json"
    _write_json(result_path, payload)
    payload["result_path"] = str(result_path)
    return payload


def main() -> int:
    args = build_parser().parse_args()
    payload = run(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"mode: {payload['mode']}")
        print(f"plan: {payload['plan_path']}")
        print(f"result: {payload['result_path']}")
        summary = payload["summary"]
        print(f"tasks: {summary.get('completed_tasks', 0)} completed, {summary.get('failed_tasks', 0)} failed")
        for route in summary.get("selected_routes", [])[:10]:
            print(
                f"- {route.get('app_name')} | {route.get('task_description')} -> "
                f"{route.get('scheduler_type')} ({route.get('similarity_score'):.3f})"
            )
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
