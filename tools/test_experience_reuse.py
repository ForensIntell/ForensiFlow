#!/usr/bin/env python3
"""Run or inspect the ForensiFlow experience-reuse module using existing RAG templates only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from template_library import (
    find_template,
    is_runnable_reuse_template,
    load_templates,
    print_templates,
    template_label,
    template_package_name,
)
from device_serial import resolve_device_serial


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test the experience-reuse runner with a task that already exists in the RAG template library."
    )
    parser.add_argument("--templates", type=Path, default=REPO_ROOT / "external" / "rag_templates" / "all_templates.json")
    parser.add_argument("--list", action="store_true", help="List runnable templates and exit.")
    parser.add_argument("--list-all", action="store_true", help="List all templates, including non-runnable historical templates.")
    parser.add_argument("--limit", type=int, default=0, help="Limit rows when listing templates.")
    parser.add_argument("--template-index", type=int, help="1-based index from the runnable template list.")
    parser.add_argument("--app-name", default="", help="Exact template app name. Must match the template library.")
    parser.add_argument("--task", default="", help="Exact template task. Must match the template library.")
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 serial for real execution.")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--data-dir", default="./data/reuse_module_tests")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--execute", action="store_true", help="Actually run TaskSchedulerVT. Without this, only validates selection.")
    parser.add_argument("--json", action="store_true", help="Print selected template/result as JSON.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    templates = load_templates(args.templates)
    runnable_count = sum(1 for template in templates if is_runnable_reuse_template(template))

    if args.list or args.list_all:
        print_templates(templates, runnable_only=not args.list_all, limit=args.limit)
        print(f"\nTotal templates: {len(templates)}; runnable reuse templates: {runnable_count}")
        return 0

    template = find_template(
        templates,
        index=args.template_index,
        app=args.app_name,
        task=args.task,
        runnable_only=True,
    )
    if not is_runnable_reuse_template(template):
        raise SystemExit("selected template is not runnable by the reuse module")

    selected = {
        "ok": True,
        "mode": "selection_only" if not args.execute else "execute",
        "template": template,
        "label": template_label(template),
        "steps_count": len(template.get("steps") or []),
        "script_generation": template.get("script_generation"),
    }

    if not args.execute:
        if args.json:
            print(json.dumps(selected, ensure_ascii=False, indent=2))
        else:
            print("Selected reusable template:")
            print(f"  app: {template.get('app')}")
            print(f"  package: {template_package_name(template)}")
            print(f"  task: {template.get('task')}")
            print(f"  steps: {len(template.get('steps') or [])}")
            print("\nUse --execute --device-serial <serial> to run this template on a phone.")
        return 0

    if not args.device_serial:
        args.device_serial = resolve_device_serial(args.device_serial, required=True)

    from runner.forensiflow.core.config import get_llm_config
    from runner.forensiflow.core.scheduler_vt import TaskSchedulerVT
    from runner.forensiflow.devices.android import AndroidDevice

    cfg = get_llm_config(api_base=args.api_base or None, model=args.model or None)
    device = AndroidDevice(adb_endpoint=args.device_serial)
    scheduler = TaskSchedulerVT(
        device=device,
        planner_api_key=cfg.api_key,
        planner_base_url=cfg.api_base,
        planner_model=cfg.model,
        data_dir=args.data_dir,
    )
    result = scheduler.run_task(
        app=str(template.get("app") or args.app_name),
        old_task=str(template.get("task") or args.task),
        task=str(template.get("task") or args.task),
        max_steps=args.max_steps,
        use_abstract_task=True,
        rag_template=template,
    )
    payload = {"selected_template": selected, "result": result}
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
