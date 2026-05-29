"""Export Codex mobile-agent successes into the ForensiFlow reuse system."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from . import script_tools
from .schema import MobileAgentContext, compact_json


logger = logging.getLogger(__name__)

ALLOWED_TEMPLATE_ACTIONS = {"Launch", "Click", "Swipe", "Wait", "Back", "CallScript"}
SCRIPT_ACTIONS = {
    "mark_navigation_complete",
    "read_latest_ui_xml",
    "probe_scroll_position",
    "update_workspace_context",
    "read_workspace_context",
    "set_extraction_plan",
    "write_script_raw",
    "write_script",
    "read_script",
    "read_script_index",
    "grep_script",
    "edit_script",
    "patch_script",
    "replace_script_lines",
    "run_script",
    "inspect_records",
    "done",
    "runtime_error",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def export_reuse_artifacts(
    context: MobileAgentContext,
    history: List[Dict[str, Any]],
    *,
    client: Any = None,
    model: str = "",
    constraint: str = "",
    llm_timeout_seconds: int = 90,
    publish_fallback: bool = False,
) -> Dict[str, Any]:
    """Archive the generated script and publish a compatible RAG template."""
    script_path = script_tools.workspace_path(context, "generated_script.py")
    if not script_path.exists():
        return {"ok": False, "error": f"generated script not found: {script_path}"}

    records_path = script_tools.script_workspace(context) / "records.json"
    records_count = _records_count(records_path)
    script_registration = register_generated_script(
        context,
        script_path=script_path,
        records_path=records_path,
        records_count=records_count,
        constraint=constraint,
    )
    if not script_registration.get("ok"):
        return script_registration

    steps_result = distill_template_steps(
        context,
        history,
        script_registration=script_registration,
        client=client,
        model=model,
        constraint=constraint,
        timeout_seconds=llm_timeout_seconds,
    )
    template = build_rag_template(
        context,
        script_registration=script_registration,
        steps=steps_result["steps"],
        constraint=constraint,
        distillation=steps_result,
    )

    workspace = script_tools.script_workspace(context)
    template_path = workspace / "rag_template.json"
    template_path.write_text(json.dumps([template], ensure_ascii=False, indent=2), encoding="utf-8")
    registry_entry_path = workspace / "script_registry_entry.json"
    registry_entry_path.write_text(
        json.dumps(script_registration["registry_entry"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    should_publish = steps_result.get("method") == "llm_distilled" or bool(publish_fallback)
    rag_publish: Dict[str, Any] = {"ok": False, "published": False, "reason": "not published"}
    if should_publish:
        rag_publish = append_to_rag_library(template)
    else:
        rag_publish["reason"] = "template was built by mechanical fallback; saved locally but not added to global RAG"

    return {
        "ok": True,
        "script_name": script_registration["script_name"],
        "archived_script_path": script_registration["archived_script_path"],
        "registry_path": script_registration["registry_path"],
        "registry_mirror_path": script_registration["registry_mirror_path"],
        "registry_entry_path": str(registry_entry_path),
        "template_path": str(template_path),
        "rag_library": rag_publish,
        "template_build_method": steps_result.get("method"),
        "template_confidence": steps_result.get("confidence"),
        "dropped_steps": steps_result.get("dropped_steps", []),
        "records_count": records_count,
    }


def export_full_agent_reuse_artifacts(
    *,
    run_dir: Path,
    workspace: Path,
    app_name: str,
    package_name: str,
    target: str,
    constraint: str = "",
    publish: bool = True,
) -> Dict[str, Any]:
    """Publish a successful standalone Codex full-agent run into RAG reuse.

    The full-agent path is driven by the Codex CLI + skill, so it does not have
    native runtime history. Its reusable path comes from action_path.json.
    """
    workspace = workspace.resolve()
    run_dir = run_dir.resolve()
    script_path = workspace / "generated_script.py"
    records_path = workspace / "records.json"
    records_debug_path = workspace / "records_debug.json"
    action_path = workspace / "action_path.json"

    if not script_path.exists():
        return {"ok": False, "error": f"generated script not found: {script_path}"}
    if not records_path.exists():
        return {"ok": False, "error": f"records.json not found: {records_path}"}
    if not records_debug_path.exists():
        return {"ok": False, "error": f"records_debug.json not found: {records_debug_path}"}

    records_count = _records_count(records_path)
    if records_count <= 0:
        return {"ok": False, "error": "records.json has no reusable records"}
    debug_count = _records_count(records_debug_path)
    if debug_count != records_count:
        return {
            "ok": False,
            "error": f"records_debug.json count {debug_count} does not match records.json count {records_count}",
        }
    state_check = _run_state_ok(workspace / "run_state.json")
    if not state_check.get("ok"):
        return state_check

    context = SimpleNamespace(
        app_name=app_name,
        package_name=package_name,
        target=target,
        session=SimpleNamespace(run_dir=run_dir),
        script_workspace=workspace,
        workspace_context_files={},
    )

    script_index = _refresh_workspace_script_index(context)
    script_registration = register_generated_script(
        context,  # type: ignore[arg-type]
        script_path=script_path,
        records_path=records_path,
        records_count=records_count,
        constraint=constraint,
    )
    if not script_registration.get("ok"):
        return script_registration
    _write_archived_script_index(script_registration, script_index)

    action_payload = _load_json_any(action_path)
    steps = _steps_from_action_path(
        action_payload,
        context,  # type: ignore[arg-type]
        script_registration,
    )
    distillation = {
        "method": "action_path",
        "confidence": 0.85 if action_path.exists() else 0.65,
        "source": str(action_path) if action_path.exists() else "",
    }
    template = build_rag_template(
        context,  # type: ignore[arg-type]
        script_registration=script_registration,
        steps=steps,
        constraint=constraint,
        distillation=distillation,
    )

    template_path = workspace / "rag_template.json"
    template_path.write_text(json.dumps([template], ensure_ascii=False, indent=2), encoding="utf-8")
    registry_entry_path = workspace / "script_registry_entry.json"
    registry_entry_path.write_text(
        json.dumps(script_registration["registry_entry"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rag_publish: Dict[str, Any] = {"ok": False, "published": False, "reason": "publish disabled"}
    if publish:
        rag_publish = append_to_rag_library(template)

    return {
        "ok": True,
        "script_name": script_registration["script_name"],
        "archived_script_path": script_registration["archived_script_path"],
        "registry_path": script_registration["registry_path"],
        "registry_mirror_path": script_registration["registry_mirror_path"],
        "registry_entry_path": str(registry_entry_path),
        "template_path": str(template_path),
        "script_index": script_index,
        "rag_library": rag_publish,
        "template_build_method": distillation["method"],
        "template_confidence": distillation["confidence"],
        "records_count": records_count,
        "debug_count": debug_count,
    }


def register_generated_script(
    context: MobileAgentContext,
    *,
    script_path: Path,
    records_path: Path,
    records_count: int,
    constraint: str = "",
) -> Dict[str, Any]:
    root = repo_root()
    generated_dir = root / "runner" / "forensiflow" / "scripts" / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    script_name = _script_name(context.app_name, context.target, constraint)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    archived_script_path = generated_dir / f"{timestamp}_{_safe_filename(script_name)}.py"
    source = script_path.read_text(encoding="utf-8", errors="replace")
    header = (
        "# Auto-archived ForensiFlow Codex mobile-agent extraction script.\n"
        f"# Registered name: {script_name}\n"
        f"# Source script: {script_path}\n\n"
    )
    archived_script_path.write_text(header + source, encoding="utf-8")

    registry_path = generated_dir / "registry.json"
    registry_mirror_path = root / "data" / "generated_script_registry.json"
    entry = {
        "script_name": script_name,
        "app": context.app_name,
        "package_name": context.package_name,
        "task": context.target,
        "constraint": constraint,
        "script_path": str(archived_script_path.resolve()),
        "source_script_path": str(script_path.resolve()),
        "script_index_path": str(archived_script_path.with_suffix(".index.json").resolve()),
        "results_json": str(records_path.resolve()) if records_path.exists() else "",
        "source_run_dir": str(context.session.run_dir.resolve()),
        "reuse_log_dir": str((context.session.run_dir / "script_reuse_logs").resolve()),
        "records_count": int(records_count),
        "attempts": 1,
        "registered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": "codex_mobile_agent_generated_script",
        "legacy_type": "page_agent_mobile_generated_script",
    }
    registry = _load_json_object(registry_path)
    registry[script_name] = entry
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    registry_mirror_path.parent.mkdir(parents=True, exist_ok=True)
    registry_mirror_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "script_name": script_name,
        "archived_script_path": str(archived_script_path.resolve()),
        "registry_path": str(registry_path.resolve()),
        "registry_mirror_path": str(registry_mirror_path.resolve()),
        "registry_entry": entry,
    }


def distill_template_steps(
    context: MobileAgentContext,
    history: List[Dict[str, Any]],
    *,
    script_registration: Dict[str, Any],
    client: Any = None,
    model: str = "",
    constraint: str = "",
    timeout_seconds: int = 90,
) -> Dict[str, Any]:
    mechanical = _mechanical_steps(context, history, script_registration)
    required_navigation = _required_navigation_steps(mechanical)
    if client is None or not model:
        return {
            "method": "mechanical_fallback",
            "confidence": 0.35,
            "steps": mechanical,
            "dropped_steps": [],
            "error": "LLM client/model unavailable",
        }
    prompt = _distillation_prompt(context, history, script_registration, constraint)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是 ForensiFlow RAG 模板蒸馏器，只输出合法 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4000,
            timeout=max(10, int(timeout_seconds)),
        )
        content = response.choices[0].message.content or ""
        parsed = _parse_json_object(content)
        steps = parsed.get("steps") if isinstance(parsed, dict) else None
        dropped_steps = parsed.get("dropped_steps") if isinstance(parsed, dict) else []
        confidence = float(parsed.get("confidence") or 0.0) if isinstance(parsed, dict) else 0.0
        validated = validate_template_steps(
            context,
            steps or [],
            script_registration,
            required_navigation_steps=required_navigation,
        )
        return {
            "method": "llm_distilled",
            "confidence": max(0.0, min(confidence or 0.75, 1.0)),
            "steps": validated,
            "dropped_steps": dropped_steps if isinstance(dropped_steps, list) else [],
            "raw_model_output": content[:4000],
        }
    except Exception as exc:
        logger.warning("RAG template distillation failed; using mechanical fallback: %s", exc)
        return {
            "method": "mechanical_fallback",
            "confidence": 0.35,
            "steps": mechanical,
            "dropped_steps": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def validate_template_steps(
    context: MobileAgentContext,
    steps: List[Any],
    script_registration: Dict[str, Any],
    required_navigation_steps: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in steps or []:
        if not isinstance(item, dict):
            continue
        step = _normalize_template_step(item)
        if not step:
            continue
        if step["action"] == "CallScript":
            continue
        if normalized and normalized[-1] == step:
            continue
        normalized.append(step)
        if len(normalized) >= 30:
            break

    launch = {"action": "Launch", "package_name": context.package_name, "app_name": context.app_name}
    if not normalized or normalized[0].get("action") != "Launch":
        normalized.insert(0, launch)
    else:
        normalized[0]["package_name"] = normalized[0].get("package_name") or context.package_name
        normalized[0]["app_name"] = normalized[0].get("app_name") or context.app_name

    normalized = _ensure_required_navigation(normalized, required_navigation_steps or [])

    normalized.append(
        {
            "action": "CallScript",
            "target": script_registration["script_name"],
            "params": {"registry": script_registration["registry_path"]},
        }
    )
    return normalized


def build_rag_template(
    context: MobileAgentContext,
    *,
    script_registration: Dict[str, Any],
    steps: List[Dict[str, Any]],
    constraint: str = "",
    distillation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "app": context.app_name,
        "package_name": context.package_name,
        "task": context.target,
        "constraint": constraint,
        "created_at": datetime.now().isoformat(),
        "scheduler_type": "codex_mobile_agent",
        "legacy_scheduler_type": "page_agent_mobile",
        "template_type": "full_extraction",
        "script_generation_success": True,
        "template_build_method": (distillation or {}).get("method", "unknown"),
        "template_confidence": (distillation or {}).get("confidence", 0),
        "steps": steps,
        "script_generation": {
            "script_name": script_registration["script_name"],
            "registry": script_registration["registry_path"],
            "registry_mirror": script_registration.get("registry_mirror_path", ""),
            "script_path": (script_registration.get("registry_entry") or {}).get("script_path", ""),
            "script_index_path": (script_registration.get("registry_entry") or {}).get("script_index_path", ""),
            "records_count": int((script_registration.get("registry_entry") or {}).get("records_count") or 0),
        },
    }


def append_to_rag_library(template: Dict[str, Any]) -> Dict[str, Any]:
    root = repo_root()
    template_dir = Path(os.getenv("RAG_TEMPLATES_DIR") or root / "external" / "rag_templates")
    template_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    app_name = str(template.get("app") or "Unknown")
    task = str(template.get("task") or "task")
    single_path = template_dir / f"{timestamp}_{_safe_filename(app_name)}_{_safe_filename(task[:40])}.json"
    single_path.write_text(json.dumps([template], ensure_ascii=False, indent=2), encoding="utf-8")

    app_path = template_dir / f"{app_name.lower()}_templates.json"
    app_templates = _load_json_list(app_path)
    app_templates = _upsert_template(app_templates, template)
    app_path.write_text(json.dumps(app_templates, ensure_ascii=False, indent=2), encoding="utf-8")

    global_path = template_dir / "all_templates.json"
    all_templates = _load_json_list(global_path)
    all_templates = _upsert_template(all_templates, template)
    global_path.write_text(json.dumps(all_templates, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "published": True,
        "single_template_path": str(single_path.resolve()),
        "app_templates_path": str(app_path.resolve()),
        "global_templates_path": str(global_path.resolve()),
        "template_count": len(all_templates),
    }


def _refresh_workspace_script_index(context: Any) -> Dict[str, Any]:
    try:
        return script_tools.refresh_script_index(
            context,
            relative_path="generated_script.py",
            reason="full_agent_rag_export",
        )
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _write_archived_script_index(script_registration: Dict[str, Any], workspace_index: Dict[str, Any]) -> None:
    entry = script_registration.get("registry_entry") if isinstance(script_registration.get("registry_entry"), dict) else {}
    archived_script_path = Path(str(script_registration.get("archived_script_path") or ""))
    index_path = Path(str(entry.get("script_index_path") or archived_script_path.with_suffix(".index.json")))
    if not archived_script_path.exists():
        return
    try:
        index = script_tools._build_script_index(  # type: ignore[attr-defined]
            archived_script_path,
            relative_path=archived_script_path.name,
            reason="archive_register",
        )
    except Exception as exc:
        index = {
            "ok": False,
            "script_path": str(archived_script_path),
            "error": f"{type(exc).__name__}: {exc}",
            "source_workspace_index": workspace_index,
        }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_json_any(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _steps_from_action_path(
    action_payload: Any,
    context: MobileAgentContext,
    script_registration: Dict[str, Any],
) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for item in _iter_action_path_items(action_payload):
        mapped = _map_action_path_item(item, context)
        if mapped and (not steps or steps[-1] != mapped):
            steps.append(mapped)

    launch = {"action": "Launch", "package_name": context.package_name, "app_name": context.app_name}
    if not steps or steps[0].get("action") != "Launch":
        steps.insert(0, launch)
    else:
        steps[0]["package_name"] = steps[0].get("package_name") or context.package_name
        steps[0]["app_name"] = steps[0].get("app_name") or context.app_name

    steps = _stabilize_action_path_steps(context, steps)

    call_script = {
        "action": "CallScript",
        "target": script_registration["script_name"],
        "params": {"registry": script_registration["registry_path"]},
    }
    if not steps or steps[-1].get("action") != "CallScript":
        steps.append(call_script)
    else:
        steps[-1] = call_script

    validated = validate_template_steps(context, steps, script_registration)
    if not any(step.get("action") == "CallScript" for step in validated):
        validated.append(call_script)
    return validated


def _stabilize_action_path_steps(
    context: MobileAgentContext,
    steps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Make known high-value app paths cold-start replayable.

    Full-agent action paths are authored by the Codex skill. They can contain
    correct evidence navigation while still depending on transient UI state
    such as an already-open drawer. This normalizes only narrow, observed
    formal-study paths where cold-start replay is otherwise brittle.
    """
    package_name = str(context.package_name or "")
    task_text = str(context.target or "").casefold()
    launch = next(
        (step for step in steps if step.get("action") == "Launch"),
        {"action": "Launch", "package_name": context.package_name, "app_name": context.app_name},
    )
    navigation = [step for step in steps if step.get("action") not in {"Launch", "CallScript"}]

    gmail_sent_target = (
        ("已发送" in task_text or re.search(r"\bsent\b", task_text))
        and not any(marker in task_text for marker in ("收件箱", "主要列表", "inbox", "primary"))
    )
    if package_name == "com.google.android.gm" and gmail_sent_target:
        return [
            launch,
            {
                "action": "Click",
                "target": {
                    "content_desc": "打开抽屉式导航栏",
                    "class": "android.widget.ImageButton",
                },
            },
            {"action": "Wait", "params": {"duration": 1.0}},
            {
                "action": "Click",
                "target": {
                    "resource_id": "hub_drawer_label_title",
                    "text": "已发送",
                    "class": "android.widget.TextView",
                },
            },
            {"action": "Wait", "params": {"duration": 2.0}},
        ]

    gmail_inbox_thread_target = package_name == "com.google.android.gm" and (
        "收件箱" in task_text
        or "主要列表" in task_text
        or re.search(r"\binbox\b", task_text)
        or re.search(r"\bprimary\b", task_text)
    ) and (
        "线程" in task_text
        or "邮件" in task_text
        or re.search(r"\bthread\b", task_text)
        or re.search(r"\bemail\b", task_text)
    )
    if gmail_inbox_thread_target:
        return [
            launch,
            {
                "action": "Click",
                "target": {
                    "content_desc": "打开抽屉式导航栏",
                    "class": "android.widget.ImageButton",
                },
            },
            {"action": "Wait", "params": {"duration": 1.0}},
            {
                "action": "Click",
                "target": {
                    "resource_id": "hub_drawer_label_title",
                    "text": "主要",
                    "class": "android.widget.TextView",
                },
            },
            {"action": "Wait", "params": {"duration": 2.0}},
            {
                "action": "Click",
                "target": {
                    "resource_id": "subject",
                    "class": "android.widget.TextView",
                },
            },
            {"action": "Wait", "params": {"duration": 2.0}},
        ]

    if package_name == "com.android.chrome" and ("下载" in task_text and "书签" in task_text):
        return [
            launch,
            {"action": "Wait", "params": {"duration": 2.0}},
            {
                "action": "Click",
                "target": {
                    "resource_id": "com.android.chrome:id/menu_button",
                },
            },
            {"action": "Wait", "params": {"duration": 1.0}},
            {
                "action": "Click",
                "target": {
                    "resource_id": "com.android.chrome:id/downloads_menu_id",
                },
            },
            {"action": "Wait", "params": {"duration": 2.0}},
        ]

    if package_name == "com.google.android.apps.maps" and (
        "最近搜索" in task_text or "最近查看" in task_text or "recent" in task_text
    ):
        return [
            launch,
            {"action": "Wait", "params": {"duration": 4.0}},
            {
                "action": "Click",
                "target": {
                    "resource_id": "com.google.android.apps.maps:id/saved_tab_strip_button",
                    "text": "我",
                    "content_desc": "我",
                },
            },
            {"action": "Wait", "params": {"duration": 2.0}},
            {"action": "Click", "target": {"text": "地图历史记录"}},
            {"action": "Wait", "params": {"duration": 1.5}},
            {"action": "Click", "target": {"text": "搜索过"}},
            {"action": "Wait", "params": {"duration": 1.5}},
            {"action": "Click", "target": {"text": "应用"}},
            {"action": "Wait", "params": {"duration": 2.0}},
        ]

    if package_name == "com.google.android.apps.maps" and (
        "saved" in task_text or "已保存" in task_text or "您的地点" in task_text
    ):
        return [
            launch,
            {"action": "Wait", "params": {"duration": 4.0}},
            {
                "action": "Click",
                "target": {
                    "resource_id": "com.google.android.apps.maps:id/saved_tab_strip_button",
                    "text": "我",
                    "content_desc": "我",
                },
            },
            {"action": "Wait", "params": {"duration": 2.0}},
            {"action": "Click", "target": {"text": "已保存"}},
            {"action": "Wait", "params": {"duration": 1.5}},
            {"action": "Click", "target": {"text": "全部"}},
            {"action": "Wait", "params": {"duration": 1.0}},
            {"action": "Click", "target": {"text": "应用"}},
            {"action": "Wait", "params": {"duration": 2.0}},
        ]

    if navigation:
        return [launch, *navigation]
    return [launch]


def _iter_action_path_items(action_payload: Any) -> List[Dict[str, Any]]:
    if isinstance(action_payload, list):
        return [item for item in action_payload if isinstance(item, dict)]
    if isinstance(action_payload, dict):
        for key in ("actions", "steps", "path", "action_path"):
            value = action_payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _map_action_path_item(item: Dict[str, Any], context: MobileAgentContext) -> Optional[Dict[str, Any]]:
    action = _action_path_name(item)
    if action in {"launch", "launch_app", "app_start", "start_app"}:
        return {
            "action": "Launch",
            "package_name": str(item.get("package_name") or item.get("package") or item.get("app_package") or context.package_name),
            "app_name": str(item.get("app_name") or item.get("app") or context.app_name),
        }
    if action in {"tap", "click"}:
        target = _action_path_target(item)
        if target:
            return {"action": "Click", "target": target}
        return None
    if action in {"swipe", "scroll"}:
        direction = _action_path_direction(item)
        if direction:
            return {"action": "Swipe", "params": {"direction": direction}}
        return None
    if action in {"back", "press_back", "key_back"}:
        return {"action": "Back"}
    if action == "wait":
        return {"action": "Wait", "params": {"duration": _action_path_wait_seconds(item)}}
    if action in {"run_script", "call_script", "callscript"}:
        return {"action": "CallScript", "target": "__placeholder__"}
    return None


def _action_path_name(item: Dict[str, Any]) -> str:
    value = item.get("action") or item.get("action_type") or item.get("type") or item.get("name") or ""
    return str(value).strip().lower()


def _parse_bounds(bounds: Any) -> Optional[Dict[str, int]]:
    if isinstance(bounds, dict):
        try:
            return {
                "left": int(bounds["left"]),
                "top": int(bounds["top"]),
                "right": int(bounds["right"]),
                "bottom": int(bounds["bottom"]),
            }
        except Exception:
            return None
    if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        try:
            return {
                "left": int(bounds[0]),
                "top": int(bounds[1]),
                "right": int(bounds[2]),
                "bottom": int(bounds[3]),
            }
        except Exception:
            return None
    try:
        matches = re.findall(r"\[(\d+),(\d+)\]", str(bounds or ""))
        if len(matches) == 2:
            return {
                "left": int(matches[0][0]),
                "top": int(matches[0][1]),
                "right": int(matches[1][0]),
                "bottom": int(matches[1][1]),
            }
    except Exception:
        return None
    return None


def _normalize_structured_target(value: Any) -> Any:
    if not isinstance(value, dict):
        text = str(value or "").strip()
        return text[:200] if text else ""

    aliases = {
        "resource_id": ("resource_id", "resource-id", "id"),
        "text": ("text", "target_text", "label", "title"),
        "content_desc": ("content_desc", "content-desc", "description", "desc"),
        "class": ("class", "class_name", "className"),
    }
    normalized: Dict[str, str] = {}
    for canonical, keys in aliases.items():
        for key in keys:
            raw = value.get(key)
            text = str(raw or "").strip()
            if text:
                normalized[canonical] = text
                break
    bounds = value.get("bounds")
    if isinstance(bounds, dict):
        try:
            normalized["bounds"] = {
                "left": int(bounds["left"]),
                "top": int(bounds["top"]),
                "right": int(bounds["right"]),
                "bottom": int(bounds["bottom"]),
            }
        except Exception:
            pass
    elif isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        try:
            normalized["bounds"] = {
                "left": int(bounds[0]),
                "top": int(bounds[1]),
                "right": int(bounds[2]),
                "bottom": int(bounds[3]),
            }
        except Exception:
            pass
    elif isinstance(bounds, str) and bounds.strip():
        parsed = _parse_bounds(bounds)
        if parsed:
            normalized["bounds"] = parsed

    for key in ("x", "y"):
        raw = value.get(key)
        if raw not in (None, ""):
            try:
                normalized[key] = int(float(raw))
            except Exception:
                pass
    return normalized or ""


def _normalize_structured_swipe(value: Any) -> Any:
    if not isinstance(value, dict):
        return ""
    normalized: Dict[str, Any] = {}
    for key in ("direction", "region"):
        raw = value.get(key)
        text = str(raw or "").strip()
        if text:
            normalized[key] = text
    for key in ("x_ratio", "start_x", "end_x", "start_y", "end_y", "duration", "duration_seconds"):
        raw = value.get(key)
        if raw in (None, "", [], {}):
            continue
        try:
            normalized[key] = float(raw)
        except Exception:
            normalized[key] = str(raw).strip()
    start = value.get("start") if isinstance(value.get("start"), dict) else None
    end = value.get("end") if isinstance(value.get("end"), dict) else None
    if isinstance(start, dict):
        normalized["start"] = {k: start[k] for k in ("x", "y") if k in start}
    if isinstance(end, dict):
        normalized["end"] = {k: end[k] for k in ("x", "y") if k in end}
    return normalized or ""


def _action_path_target(item: Dict[str, Any]) -> Any:
    direct_target = item.get("target")
    if isinstance(direct_target, dict):
        normalized = _normalize_structured_target(direct_target)
        if normalized:
            return normalized

    structured: Dict[str, Any] = {}
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    for source in (item, params):
        if not isinstance(source, dict):
            continue
        for key in ("resource_id", "resource-id", "id", "text", "target_text", "label", "title", "content_desc", "content-desc", "description", "desc", "class", "bounds", "x", "y"):
            value = source.get(key)
            if value in (None, "", [], {}):
                continue
            if key in {"resource_id", "resource-id", "id"} and "resource_id" not in structured:
                structured["resource_id"] = str(value).strip()
            elif key in {"content_desc", "content-desc", "description", "desc"} and "content_desc" not in structured:
                structured["content_desc"] = str(value).strip()
            elif key in {"text", "target_text", "label", "title"} and "text" not in structured:
                structured["text"] = str(value).strip()
            elif key == "class" and "class" not in structured:
                structured["class"] = str(value).strip()
            elif key == "bounds" and "bounds" not in structured:
                normalized_bounds = _normalize_structured_target({"bounds": value})
                if isinstance(normalized_bounds, dict) and normalized_bounds.get("bounds"):
                    structured["bounds"] = normalized_bounds["bounds"]
            elif key in {"x", "y"}:
                try:
                    structured[key] = int(float(value))
                except Exception:
                    pass
    if structured:
        normalized = _normalize_structured_target(structured)
        if normalized:
            return normalized

    for key in ("target", "target_text", "text", "label", "title", "content_desc", "description", "resource_id"):
        value = item.get(key)
        if isinstance(value, dict):
            normalized = _normalize_structured_target(value)
            if normalized:
                return normalized
        value = str(value or "").strip()
        if value:
            return value[:200]
    for key in ("target", "target_text", "text", "label", "content_desc", "resource_id"):
        value = params.get(key)
        if isinstance(value, dict):
            normalized = _normalize_structured_target(value)
            if normalized:
                return normalized
        value = str(value or "").strip()
        if value:
            return value[:200]
    return ""


def _action_path_direction(item: Dict[str, Any]) -> str:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    raw = str(params.get("direction") or item.get("direction") or "").strip().lower()
    aliases = {
        "finger_up": "down",
        "finger_down": "up",
        "finger_left": "right",
        "finger_right": "left",
        "content_up": "up",
        "content_down": "down",
        "content_left": "left",
        "content_right": "right",
        "left_to_right": "left",
        "swipe_left_to_right": "left",
        "right_to_left": "right",
        "swipe_right_to_left": "right",
        "top_to_bottom": "up",
        "swipe_top_to_bottom": "up",
        "bottom_to_top": "down",
        "swipe_bottom_to_top": "down",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
    }
    if raw in aliases:
        return aliases[raw]
    start = item.get("start") if isinstance(item.get("start"), dict) else params.get("start")
    end = item.get("end") if isinstance(item.get("end"), dict) else params.get("end")
    start_y = item.get("start_y", params.get("start_y"))
    end_y = item.get("end_y", params.get("end_y"))
    start_x = item.get("start_x", params.get("start_x"))
    end_x = item.get("end_x", params.get("end_x"))
    start_point = item.get("start_point", params.get("start_point"))
    end_point = item.get("end_point", params.get("end_point"))
    if start_point is None:
        start_point = item.get("startPoint", params.get("startPoint"))
    if end_point is None:
        end_point = item.get("endPoint", params.get("endPoint"))
    if isinstance(start, dict):
        start_y = start.get("y", start_y)
        start_x = start.get("x", start_x)
    if isinstance(end, dict):
        end_y = end.get("y", end_y)
        end_x = end.get("x", end_x)
    point_values = _action_path_point_xy(start_point)
    if point_values:
        start_x, start_y = point_values
    point_values = _action_path_point_xy(end_point)
    if point_values:
        end_x, end_y = point_values
    try:
        if start_y is not None and end_y is not None:
            # Template Swipe directions are content directions. Android swipe
            # coordinates describe finger movement, so vertical movement is
            # inverted for the old scheduler.
            return "down" if float(start_y) > float(end_y) else "up"
    except Exception:
        pass
    try:
        if start_x is not None and end_x is not None:
            return "right" if float(start_x) > float(end_x) else "left"
    except Exception:
        pass
    return ""


def _action_path_point_xy(value: Any) -> Optional[Tuple[Any, Any]]:
    if isinstance(value, dict):
        x = value.get("x")
        y = value.get("y")
        if x is not None and y is not None:
            return x, y
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return value[0], value[1]
    return None


def _action_path_wait_seconds(item: Dict[str, Any]) -> float:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    value = (
        item.get("duration")
        or item.get("seconds")
        or item.get("wait_seconds")
        or params.get("duration")
        or params.get("seconds")
        or item.get("timeout_sec")
        or params.get("timeout_sec")
    )
    if value is None:
        value = item.get("duration_ms") or params.get("duration_ms")
        try:
            return max(0.2, min(float(value) / 1000.0, 15.0))
        except Exception:
            return 2.0
    try:
        return max(0.2, min(float(value), 15.0))
    except Exception:
        return 2.0


def _distillation_prompt(
    context: MobileAgentContext,
    history: List[Dict[str, Any]],
    script_registration: Dict[str, Any],
    constraint: str,
) -> str:
    compact_history = []
    for event in history:
        action = event.get("action") or {}
        output = action.get("output") if isinstance(action.get("output"), dict) else {}
        compact_history.append(
            {
                "step": event.get("stepIndex"),
                "action": action.get("name"),
                "input": _compact_action_input(action.get("input") or {}),
                "ok": output.get("ok"),
                "result_hint": str(output.get("result") or output.get("error") or output.get("hint") or "")[:240],
                "evaluation": ((event.get("reflection") or {}).get("evaluation_previous_goal") or "")[:300],
                "next_goal": ((event.get("reflection") or {}).get("next_goal") or "")[:240],
            }
        )
    payload = {
        "app": context.app_name,
        "package_name": context.package_name,
        "task": context.target,
        "constraint": constraint,
        "script_name": script_registration["script_name"],
        "registry": script_registration["registry_path"],
        "history": compact_history,
    }
    return (
        "请从 ForensiFlow Codex mobile-agent 的原始执行历史中蒸馏可复用的 RAG 模板步骤。\n"
        "只保留真正到达目标脚本起点所需的有效导航动作；删除试错、点错后返回、探测、读取 XML、workspace 更新、脚本生成、脚本运行和 done 动作。\n"
        "注意：Codex mobile-agent 生成的动态脚本通常只负责在 mark_navigation_complete 后的目标页面内提取数据，不负责从应用首页导航到目标页。因此 mark_navigation_complete 之前用于到达目标页的有效点击/滑动必须保留，不能简化成 Launch 后直接 CallScript，除非历史明确显示 Launch 后已经天然位于目标页。\n"
        "允许动作仅为 Launch, Click, Swipe, Wait, Back, CallScript。\n"
        "Click 必须使用可复用 target 文本，不要输出坐标。Swipe 使用 params.direction=up/down/left/right。Back 只在它是有效路径的一部分时保留，不能用来保留错误试错路径。\n"
        "第一步必须是 Launch，最后一步必须是 CallScript。\n"
        "只输出 JSON，不要 markdown。格式：{\"steps\":[...],\"dropped_steps\":[{\"source_step\":1,\"reason\":\"...\"}],\"confidence\":0.0到1.0}\n\n"
        f"输入：\n{compact_json(payload, limit=18000)}"
    )


def _mechanical_steps(
    context: MobileAgentContext,
    history: List[Dict[str, Any]],
    script_registration: Dict[str, Any],
) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = [
        {"action": "Launch", "package_name": context.package_name, "app_name": context.app_name}
    ]
    for event in history:
        action = event.get("action") or {}
        name = str(action.get("name") or "")
        if name in SCRIPT_ACTIONS:
            if name == "mark_navigation_complete":
                break
            continue
        payload = action.get("input") if isinstance(action.get("input"), dict) else {}
        mapped: Optional[Dict[str, Any]] = None
        if name == "tap" and payload.get("target"):
            mapped = {"action": "Click", "target": str(payload.get("target"))}
        elif name == "tap":
            target = _infer_tap_target(event)
            if target:
                mapped = {"action": "Click", "target": target}
        elif name == "swipe":
            mapped = {"action": "Swipe", "params": {"direction": str(payload.get("direction") or "up").lower()}}
        elif name == "wait":
            mapped = {"action": "Wait", "params": {"duration": float(payload.get("seconds") or 2)}}
        elif name == "press_back":
            mapped = {"action": "Back"}
        if mapped and (not steps or steps[-1] != mapped):
            steps.append(mapped)
    return validate_template_steps(context, steps, script_registration)


def _required_navigation_steps(mechanical_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the navigation floor that an LLM-distilled template may not drop.

    Generated scripts are page-local unless proven otherwise. If the real run
    needed actions between Launch and mark_navigation_complete, a reusable RAG
    template must keep those actions before CallScript.
    """
    required: List[Dict[str, Any]] = []
    for step in mechanical_steps:
        action = step.get("action")
        if action in {"Launch", "CallScript"}:
            continue
        if action in {"Click", "Swipe", "Wait", "Back"}:
            required.append(step)
    return required


def _ensure_required_navigation(
    normalized: List[Dict[str, Any]],
    required_navigation_steps: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not required_navigation_steps:
        return normalized
    existing_navigation = [
        step for step in normalized
        if step.get("action") not in {"Launch", "CallScript"}
    ]
    if existing_navigation:
        return normalized

    launch = normalized[:1] if normalized else []
    tail = normalized[1:] if normalized else []
    merged = list(launch)
    for step in required_navigation_steps:
        if not merged or merged[-1] != step:
            merged.append(step)
    for step in tail:
        if step.get("action") == "CallScript":
            continue
        if not merged or merged[-1] != step:
            merged.append(step)
    return merged


def _infer_tap_target(event: Dict[str, Any]) -> str:
    reflection = event.get("reflection") if isinstance(event.get("reflection"), dict) else {}
    texts = [
        str(reflection.get("next_goal") or ""),
        str(reflection.get("memory") or ""),
        str(reflection.get("evaluation_previous_goal") or ""),
    ]
    combined = "\n".join(texts)
    patterns = [
        r"(?:点击|点按|选择|打开|进入)[^\"'“”《》]{0,20}[\"“']([^\"“”']{1,40})[\"”']",
        r"(?:点击|点按|选择|打开|进入)[^《》]{0,20}《([^》]{1,40})》",
        r"(?:点击|点按|选择|打开|进入)(?:底部|顶部|左侧|右侧)?(?:导航栏|标签栏|菜单)?(?:的)?([\w\u4e00-\u9fff ._-]{1,20})(?:标签|按钮|入口|页面|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, combined)
        if not match:
            continue
        target = _clean_inferred_target(match.group(1))
        if target:
            return target
    return ""


def _clean_inferred_target(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip(" ，。,.：:;；")
    value = re.sub(r"^(?:的|底部|顶部|导航栏|标签栏)+", "", value).strip(" ，。,.：:;；")
    value = re.sub(r"(?:标签页|标签|按钮|入口|页面)$", "", value).strip(" ，。,.：:;；")
    if not value or len(value) > 30:
        return ""
    blocked = {"当前", "目标", "页面", "应用", "这里", "下一步"}
    if value in blocked:
        return ""
    return value


def _normalize_template_step(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw_action = str(item.get("action") or "").strip()
    aliases = {
        "launch": "Launch",
        "click": "Click",
        "tap": "Click",
        "swipe": "Swipe",
        "wait": "Wait",
        "back": "Back",
        "pressback": "Back",
        "press_back": "Back",
        "callscript": "CallScript",
    }
    action = aliases.get(raw_action.lower(), raw_action)
    if action not in ALLOWED_TEMPLATE_ACTIONS:
        return None
    if action == "Launch":
        return {
            "action": "Launch",
            "package_name": str(item.get("package_name") or ""),
            "app_name": str(item.get("app_name") or ""),
        }
    if action == "Click":
        target = _normalize_structured_target(item.get("target"))
        if not target:
            return None
        return {"action": "Click", "target": target}
    if action == "Swipe":
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        direction = str(params.get("direction") or item.get("direction") or "").lower()
        if direction not in {"up", "down", "left", "right"}:
            return None
        swipe_params = {"direction": direction}
        structured_swipe = _normalize_structured_swipe(params if params else item)
        if isinstance(structured_swipe, dict):
            swipe_params.update(structured_swipe)
        return {"action": "Swipe", "params": swipe_params}
    if action == "Wait":
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        duration = params.get("duration", item.get("duration", 2))
        try:
            duration = max(0.2, min(float(duration), 15.0))
        except Exception:
            duration = 2
        return {"action": "Wait", "params": {"duration": duration}}
    if action == "Back":
        return {"action": "Back"}
    if action == "CallScript":
        target = str(item.get("target") or "").strip()
        if not target:
            return None
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        return {"action": "CallScript", "target": target, "params": params}
    return None


def _compact_action_input(payload: Dict[str, Any]) -> Dict[str, Any]:
    keep = {}
    for key in ("package_name", "x", "y", "target", "direction", "scale", "seconds", "text"):
        if key in payload:
            keep[key] = payload[key]
    return keep


def _records_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return 0
    records = data.get("records") if isinstance(data, dict) else data
    return len(records) if isinstance(records, list) else 0


def _run_state_ok(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"ok": False, "error": f"run_state.json not found: {path}"}
    try:
        state = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "error": f"run_state.json parse error: {exc}"}
    if not isinstance(state, dict):
        return {"ok": False, "error": "run_state.json is not an object"}
    status = str(state.get("status") or "")
    if status != "completed":
        return {"ok": False, "error": f"run_state status is {status!r}"}
    errors = state.get("errors")
    if errors:
        return {"ok": False, "error": f"run_state errors: {errors}"}
    total = state.get("total_records")
    try:
        if total is not None and int(total) <= 0:
            return {"ok": False, "error": f"run_state total_records is {total!r}"}
    except Exception:
        pass
    return {"ok": True}


def _script_name(app_name: str, task: str, constraint: str = "") -> str:
    task_text = re.sub(r"\s+", "", task or "取证任务")
    task_text = re.sub(r"[^\w\u4e00-\u9fff]", "", task_text)[:36] or "取证任务"
    if constraint:
        digest = hashlib.sha1(constraint.encode("utf-8", errors="ignore")).hexdigest()[:8]
        task_text = f"{task_text}_{digest}"
    return f"动态脚本:{app_name or 'Unknown'}:{task_text}"


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value).strip("_")
    return safe[:100] or "generated"


def _parse_json_object(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if match:
        data = json.loads(match.group(1))
        if isinstance(data, dict):
            return data
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            return data
    raise ValueError("model did not return a JSON object")


def _load_json_object(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("templates"), list):
        return [item for item in data["templates"] if isinstance(item, dict)]
    return []


def _template_key(template: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(template.get("app") or ""),
        str(template.get("package_name") or ""),
        str(template.get("task") or ""),
        str(template.get("constraint") or ""),
    )


def _upsert_template(templates: List[Dict[str, Any]], new_template: Dict[str, Any]) -> List[Dict[str, Any]]:
    key = _template_key(new_template)
    next_templates: List[Dict[str, Any]] = []
    replaced = False
    new_records = _template_records_count(new_template)
    for item in templates:
        if _template_key(item) != key:
            next_templates.append(item)
            continue
        old_records = _template_records_count(item)
        if new_records >= old_records:
            next_templates.append(new_template)
            replaced = True
        else:
            next_templates.append(item)
            replaced = True
    if not replaced:
        next_templates.append(new_template)
    return next_templates


def _template_records_count(template: Dict[str, Any]) -> int:
    script_generation = template.get("script_generation") if isinstance(template.get("script_generation"), dict) else {}
    value = script_generation.get("records_count") or template.get("records_count") or 0
    try:
        return int(value)
    except Exception:
        return 0
