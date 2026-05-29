#!/usr/bin/env python3
"""Test one task through the scheduler selector without running the planning layer."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from template_library import is_runnable_reuse_template, template_summary
from device_serial import resolve_device_serial


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send a single forensic task directly to the SchedulerSelector. "
            "By default this only tests route selection and does not touch the phone."
        )
    )
    parser.add_argument("--app-name", required=True, help="App name used by the RAG matcher, for example WhatsApp.")
    parser.add_argument("--package-name", default="", help="Package name required when executing an exploration task.")
    parser.add_argument("--task", required=True, help="Single forensic task description.")
    parser.add_argument("--constraint", default="", help="Optional task constraint passed to the exploration scheduler.")
    parser.add_argument("--threshold", type=float, default=0.75, help="Similarity threshold for reuse vs exploration.")
    parser.add_argument(
        "--force-route",
        choices=["auto", "reuse", "explore"],
        default="auto",
        help="Override route only for module testing. Default auto uses SchedulerSelector.",
    )
    parser.add_argument("--top-k", type=int, default=1, help="Number of RAG candidates used by SchedulerSelector.")
    parser.add_argument("--templates-dir", type=Path, default=REPO_ROOT / "external" / "rag_templates")
    parser.add_argument("--model-path", type=Path, default=None, help="Optional local BGE model path.")
    parser.add_argument("--matcher-device", default="cpu", help="sentence-transformers device for RAG matching.")
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 serial. Required with --execute.")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--data-dir", default="./data/direct_scheduler_tests")
    parser.add_argument("--model", default="", help="Optional LLM model override for --execute.")
    parser.add_argument("--api-base", default="", help="Optional OpenAI-compatible API base for --execute.")
    parser.add_argument("--execute", action="store_true", help="Actually run the selected scheduler on the connected phone.")
    parser.add_argument("--json", action="store_true", help="Print route selection and execution result as JSON.")
    return parser


def select_route(args: argparse.Namespace):
    from runner.forensiflow.core.rag_template_matcher import RAGTemplateMatcher
    from runner.forensiflow.core.scheduler_selector import SchedulerSelector

    matcher_kwargs: Dict[str, Any] = {
        "templates_dir": str(args.templates_dir),
        "top_k": max(1, args.top_k),
        "device": args.matcher_device,
    }
    if args.model_path is not None:
        matcher_kwargs["model_path"] = str(args.model_path)

    matcher = RAGTemplateMatcher(**matcher_kwargs)
    selector = SchedulerSelector(rag_matcher=matcher, threshold=args.threshold)
    return selector.select_scheduler(
        app_name=args.app_name,
        task_description=args.task,
        package_name=args.package_name,
        top_k=max(1, args.top_k),
    )


def selection_payload(args: argparse.Namespace, selection) -> Dict[str, Any]:
    template = selection.template if isinstance(selection.template, dict) else None
    payload: Dict[str, Any] = {
        "ok": True,
        "mode": "execute" if args.execute else "selection_only",
        "input": {
            "app_name": args.app_name,
            "package_name": args.package_name,
            "task": args.task,
            "constraint": args.constraint,
            "threshold": args.threshold,
            "top_k": args.top_k,
            "force_route": args.force_route,
        },
        "selection": {
            "scheduler_type": selection.scheduler_type,
            "similarity_score": selection.similarity_score,
            "reason": selection.reason,
            "template": template_summary(template) if template else None,
        },
    }
    if selection.scheduler_type == "new" and not args.package_name:
        payload["selection"]["execution_warning"] = (
            "--package-name is required if you later execute an exploration/new-scheduler task."
        )
    return payload


def execute_selected(args: argparse.Namespace, selection) -> Dict[str, Any]:
    if not args.device_serial:
        args.device_serial = resolve_device_serial(args.device_serial, required=True)

    from runner.forensiflow.core.codex_agent_scheduler import CodexAgentScheduler
    from runner.forensiflow.core.config import get_llm_config
    from runner.forensiflow.core.scheduler_vt import TaskSchedulerVT
    from runner.forensiflow.devices.android import AndroidDevice

    cfg = get_llm_config(api_base=args.api_base or None, model=args.model or None)
    device = AndroidDevice(adb_endpoint=args.device_serial)

    if selection.scheduler_type == "old":
        template = selection.template if isinstance(selection.template, dict) else None
        if not template:
            raise SystemExit("SchedulerSelector chose reuse/old mode but did not return a template.")
        if not is_runnable_reuse_template(template):
            raise SystemExit(
                "SchedulerSelector matched a historical template that is not runnable by the reuse module. "
                "Use a task from the runnable RAG template list, or lower/raise the threshold to test exploration."
            )

        scheduler = TaskSchedulerVT(
            device=device,
            planner_api_key=cfg.api_key,
            planner_base_url=cfg.api_base,
            planner_model=cfg.model,
            data_dir=args.data_dir,
        )
        return scheduler.run_task(
            app=str(template.get("app") or args.app_name),
            old_task=str(template.get("task") or args.task),
            task=args.task,
            max_steps=args.max_steps,
            use_abstract_task=True,
            rag_template=template,
        )

    if not args.package_name:
        raise SystemExit("--package-name is required to execute an exploration/new-scheduler task")

    scheduler = CodexAgentScheduler(
        device=device,
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        model=cfg.model,
        data_dir=args.data_dir,
    )
    return scheduler.run_forensic_task(
        package_name=args.package_name,
        app_name=args.app_name,
        task_description=args.task,
        constraint=args.constraint,
        max_steps=args.max_steps,
    )


def print_human(payload: Dict[str, Any]) -> None:
    selection = payload["selection"]
    print("Direct scheduler test:")
    print(f"  app: {payload['input']['app_name']}")
    if payload["input"]["package_name"]:
        print(f"  package: {payload['input']['package_name']}")
    print(f"  task: {payload['input']['task']}")
    print(f"  route: {selection['scheduler_type']}")
    print(f"  similarity: {selection['similarity_score']:.3f}")
    print(f"  reason: {selection['reason']}")
    if selection["template"]:
        template = selection["template"]
        print("  matched template:")
        print(f"    app: {template['app']}")
        print(f"    package: {template['package_name']}")
        print(f"    task: {template['task']}")
        print(f"    runnable: {template['runnable_reuse_template']}")
    if selection.get("execution_warning"):
        print(f"  warning: {selection['execution_warning']}")


def main() -> int:
    args = build_parser().parse_args()
    selection = select_route(args)
    if args.force_route != "auto":
        from runner.forensiflow.core.scheduler_selector import SchedulerSelectionResult

        if args.force_route == "explore":
            selection = SchedulerSelectionResult(
                scheduler_type="new",
                template=None,
                similarity_score=selection.similarity_score,
                reason=f"forced explore for module testing; auto route was {selection.scheduler_type}: {selection.reason}",
            )
        else:
            if selection.scheduler_type != "old":
                raise SystemExit("cannot force reuse: auto route did not return a reusable template")
            selection = SchedulerSelectionResult(
                scheduler_type="old",
                template=selection.template,
                similarity_score=selection.similarity_score,
                reason=f"forced reuse for module testing; auto route was old: {selection.reason}",
            )
    payload = selection_payload(args, selection)

    if args.execute:
        result = execute_selected(args, selection)
        payload["result"] = result
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print_human(payload)
            print("\nExecution result:")
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("completed") else 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print_human(payload)
        print("\nUse --execute --device-serial <serial> to run the selected scheduler on a phone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
