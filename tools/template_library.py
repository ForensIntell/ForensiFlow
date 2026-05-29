"""Small helpers for ForensiFlow RAG template-library based tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_LIBRARY = REPO_ROOT / "external" / "rag_templates" / "all_templates.json"


def load_templates(path: str | Path = DEFAULT_TEMPLATE_LIBRARY) -> List[Dict[str, Any]]:
    template_path = Path(path)
    data = json.loads(template_path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        templates = data
    elif isinstance(data, dict) and isinstance(data.get("templates"), list):
        templates = data["templates"]
    else:
        raise ValueError(f"unsupported template library format: {template_path}")
    return [template for template in templates if isinstance(template, dict)]


def is_runnable_reuse_template(template: Dict[str, Any]) -> bool:
    if template.get("template_type") == "navigation_only":
        return False
    if template.get("script_generation_success") is False:
        return False
    steps = template.get("steps")
    if not isinstance(steps, list) or not steps:
        return False
    first = steps[0] if isinstance(steps[0], dict) else {}
    if str(first.get("action") or "").lower() != "launch":
        return False
    if not template_package_name(template):
        return False
    return bool(template_script_name(template))


def template_label(template: Dict[str, Any]) -> str:
    return f"{template.get('app', 'Unknown')} | {template.get('task', '')}"


def template_package_name(template: Dict[str, Any]) -> str:
    return str(template.get("package_name") or _launch_package_name(template) or "")


def template_script_name(template: Dict[str, Any]) -> str:
    script_generation = template.get("script_generation") if isinstance(template.get("script_generation"), dict) else {}
    if script_generation.get("script_name"):
        return str(script_generation.get("script_name") or "")
    steps = template.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and str(step.get("action") or "").lower() == "callscript":
                return str(step.get("target") or "")
    return ""


def template_summary(template: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "app": template.get("app", ""),
        "package_name": template_package_name(template),
        "task": template.get("task", ""),
        "template_type": template.get("template_type"),
        "script_generation_success": template.get("script_generation_success"),
        "steps_count": len(template.get("steps") or []),
        "script_name": template_script_name(template),
        "runnable_reuse_template": is_runnable_reuse_template(template),
        "label": template_label(template),
    }


def find_template(
    templates: List[Dict[str, Any]],
    *,
    index: Optional[int] = None,
    app: str = "",
    task: str = "",
    runnable_only: bool = True,
) -> Dict[str, Any]:
    candidates = [template for template in templates if (is_runnable_reuse_template(template) or not runnable_only)]
    if index is not None:
        if index < 1 or index > len(candidates):
            raise ValueError(f"template index out of range: {index}; available 1..{len(candidates)}")
        return candidates[index - 1]
    app_norm = app.strip().casefold()
    task_norm = task.strip().casefold()
    if not app_norm or not task_norm:
        raise ValueError("either --template-index or both --app-name and --task are required")
    matches = [
        template
        for template in candidates
        if str(template.get("app") or "").strip().casefold() == app_norm
        and str(template.get("task") or "").strip().casefold() == task_norm
    ]
    if not matches:
        hint = "\n".join(f"{i}. {template_label(template)}" for i, template in enumerate(candidates[:20], 1))
        raise ValueError(f"no exact template found for app={app!r}, task={task!r}. Available examples:\n{hint}")
    if len(matches) > 1:
        raise ValueError(f"multiple exact templates found for {app!r} / {task!r}; use --template-index")
    return matches[0]


def print_templates(templates: List[Dict[str, Any]], *, runnable_only: bool = True, limit: int = 0) -> None:
    candidates = [template for template in templates if (is_runnable_reuse_template(template) or not runnable_only)]
    if limit and limit > 0:
        candidates = candidates[:limit]
    for index, template in enumerate(candidates, 1):
        runnable = "runnable" if is_runnable_reuse_template(template) else "not-runnable"
        package_name = template_package_name(template)
        print(
            f"{index:03d} | {runnable:12s} | app={template.get('app', '')} | "
            f"package={package_name} | task={template.get('task', '')}"
        )


def _launch_package_name(template: Dict[str, Any]) -> str:
    steps = template.get("steps")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        return str(steps[0].get("package_name") or "")
    return ""
