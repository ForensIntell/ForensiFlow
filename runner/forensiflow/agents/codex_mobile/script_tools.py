"""Script workspace helpers for the ForensiFlow Codex mobile agent."""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import py_compile
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .schema import MobileAgentContext


SCRIPT_UNCHANGED_STUB = (
    "Script unchanged since last read. The content from the earlier read_script "
    "result is still current; refer to that instead of re-reading."
)
DEFAULT_SCRIPT_READ_LIMIT = 2000
MAX_SCRIPT_LINE_LENGTH = 2000
MAX_GREP_MATCHES = 100
DIAGNOSTIC_SEVERITY_ORDER = {"pass": 0, "warn": 1, "suspect": 2, "fail": 3}
SINGLE_CANDIDATE_SIMILARITY_THRESHOLD = 0.0
MULTIPLE_CANDIDATES_SIMILARITY_THRESHOLD = 0.3

GENERIC_CONTROL_TEXTS = {
    "back",
    "cancel",
    "close",
    "delete",
    "done",
    "edit",
    "home",
    "menu",
    "more",
    "next",
    "no",
    "ok",
    "previous",
    "recent apps",
    "save",
    "search",
    "send",
    "settings",
    "yes",
    "add",
    "menu",
    "cover photo",
    "profile picture",
    "edit cover photo button",
    "edit profile",
    "edit profile button",
    "edit cover photo",
    "filter",
    "reels",
    "live",
    "manage posts",
    "share what's new",
    "create story",
    "主屏幕",
    "返回",
    "取消",
    "完成",
    "更多",
    "更多选项",
    "菜单",
    "添加",
    "查看全部",
    "搜索",
    "发送",
    "设置",
    "编辑",
    "编辑资料",
    "编辑个人主页",
    "编辑个人详情",
    "更多个人主页设置",
    "发布快拍",
    "分享新鲜事",
    "筛选条件",
    "直播",
    "管理帖子",
    "头像",
    "添加头像",
    "封面照片",
    "最近运行的应用",
}

GENERIC_CORE_FIELDS = (
    "content_text",
    "title",
    "text",
    "value",
    "field_value",
    "display_name",
    "name",
    "label",
    "url",
    "phone",
    "email",
    "message",
    "description",
)

GENERIC_OPTIONAL_QUALITY_FIELDS = (
    "timestamp",
    "date",
    "time",
    "sender",
    "title",
    "url",
    "field_name",
    "field_value",
)

SOURCE_EVIDENCE_FIELDS = {
    "_debug",
    "source_bounds",
    "bounds",
    "raw_node_signature",
    "page_index",
    "scroll_index",
    "row_index",
    "message_index",
    "dedup_key",
}

RECORDS_FILENAME = "records.json"
RECORDS_DEBUG_FILENAME = "records_debug.json"

VERBOSE_RECORD_FIELDS = {
    "breadcrumbs",
    "page_path",
    "screen_path",
    "app",
    "source_app",
}

VERBOSE_METADATA_FIELDS = {
    "target_name",
    "contact_name",
    "app",
    "source_app",
    "extraction_pattern",
    "notes",
    "extraction_notes",
    "extracted_at",
}

UI_OBSERVATION_RUNTIME_FIELDS = {
    "source_artifact",
    "current_page_xml",
    "current_page_outline",
    "current_page_context",
    "snapshot_page_xml",
    "snapshot_page_outline",
    "xml_chars",
    "outline_chars",
    "xml_signature",
    "reason",
    "observed_at",
}

GENERIC_UI_NOISE_PATTERNS = (
    re.compile(r"第\s*\d+\s*/\s*\d+\s*个选项卡"),
    re.compile(r"第\s*\d+\s*项\s*[，,]\s*共\s*\d+\s*项"),
    re.compile(r"\btab\b", re.IGNORECASE),
    re.compile(r"\bbutton\b", re.IGNORECASE),
)

CONTROL_COMPONENT_KEYS = {
    "button",
    "imagebutton",
    "tab",
    "tabwidget",
    "toolbar",
    "navigationbar",
    "menuitem",
}

PATTERN_REQUIRED_CONTEXT: Dict[str, List[str]] = {
    "STATIC_SCREEN": ["ui_observations", "extraction_plan"],
    "SCROLL_LIST": ["ui_observations", "scroll_position", "extraction_plan"],
    "REVERSE_TIMELINE": ["ui_observations", "scroll_position", "extraction_plan"],
    "FORWARD_TIMELINE": ["ui_observations", "scroll_position", "extraction_plan"],
    "LIST_DETAIL": ["ui_observations", "scroll_position", "extraction_plan", "item_schema"],
    "PAGINATED_LIST": ["ui_observations", "extraction_plan", "pagination_state"],
    "MULTI_SECTION": ["ui_observations", "extraction_plan", "section_map"],
    "MULTI_LEVEL_DETAIL": ["ui_observations", "extraction_plan", "nested_flow_map"],
    "UNKNOWN": ["ui_observations"],
}


def _safe_snapshot_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return value.strip("._") or "script"


def script_workspace(context: MobileAgentContext) -> Path:
    if context.script_workspace is None:
        context.script_workspace = context.session.run_dir / "script_workspace"
        context.script_workspace.mkdir(parents=True, exist_ok=True)
    return context.script_workspace


def workspace_context_dir(context: MobileAgentContext) -> Path:
    path = script_workspace(context) / "context"
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_context_path(context: MobileAgentContext) -> Path:
    return script_workspace(context) / "workspace_context.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _deep_merge(base: Any, updates: Any) -> Any:
    if isinstance(base, dict) and isinstance(updates, dict):
        merged = dict(base)
        for key, value in updates.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    return updates


def _normalize_workspace_context(context: MobileAgentContext, data: Any = None) -> Dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    normalized = {
        "task_goal": context.target,
        "ui_observations": {},
        "scroll_position": {},
        "extraction_inference": {},
        "extraction_plan": {},
        "updated_at": _utc_now_iso(),
    }
    return _deep_merge(normalized, data)


def _load_workspace_context(context: MobileAgentContext) -> Dict[str, Any]:
    path = workspace_context_path(context)
    if not path.exists():
        return _normalize_workspace_context(context)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        data = {}
    return _normalize_workspace_context(context, data)


def _save_workspace_context(context: MobileAgentContext, data: Dict[str, Any]) -> Dict[str, Any]:
    path = workspace_context_path(context)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _normalize_workspace_context(context, data)
    payload["updated_at"] = _utc_now_iso()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    context.workspace_context_files["workspace_context"] = str(path)
    return payload


def _current_context_observations(context: MobileAgentContext) -> Dict[str, Any]:
    return {
        "last_ui_artifact": context.last_ui_artifact,
        "current_page_xml": context.workspace_context_files.get("current_page_xml", ""),
        "current_page_outline": context.workspace_context_files.get("current_page_outline", ""),
        "current_page_context": context.workspace_context_files.get("current_page_context", ""),
        "snapshot_page_xml": context.workspace_context_files.get("snapshot_page_xml", ""),
        "snapshot_page_outline": context.workspace_context_files.get("snapshot_page_outline", ""),
        "xml_chars": len(context.last_ui_xml or ""),
        "outline_chars": len(context.last_ui_outline or ""),
    }


def _fresh_ui_observation_meta(context: MobileAgentContext, reason: str) -> Dict[str, Any]:
    return {
        "source_artifact": context.last_ui_artifact,
        "current_page_xml": context.workspace_context_files.get("current_page_xml", ""),
        "current_page_outline": context.workspace_context_files.get("current_page_outline", ""),
        "current_page_context": context.workspace_context_files.get("current_page_context", ""),
        "snapshot_page_xml": context.workspace_context_files.get("snapshot_page_xml", ""),
        "snapshot_page_outline": context.workspace_context_files.get("snapshot_page_outline", ""),
        "xml_chars": len(context.last_ui_xml or ""),
        "outline_chars": len(context.last_ui_outline or ""),
        "xml_signature": xml_signature(context.last_ui_xml or ""),
        "reason": reason,
        "observed_at": _utc_now_iso(),
    }


def _append_ui_observation_history(data: Dict[str, Any]) -> None:
    previous = data.get("ui_observations")
    if not _has_meaningful_value(previous) or not isinstance(previous, dict):
        return
    entry = {
        "source_artifact": previous.get("source_artifact"),
        "snapshot_page_xml": previous.get("snapshot_page_xml"),
        "xml_signature": previous.get("xml_signature"),
        "reason": previous.get("reason"),
        "page_type_evidence": previous.get("page_type_evidence"),
        "observed_at": previous.get("observed_at"),
    }
    history = list(data.get("ui_observation_history") or [])
    if history and history[-1] == entry:
        return
    history.append(entry)
    data["ui_observation_history"] = history[-10:]


def _available_context_keys(data: Dict[str, Any]) -> List[str]:
    keys = []
    for key in ("ui_observations", "scroll_position", "extraction_inference", "extraction_plan", "item_schema", "pagination_state", "section_map", "nested_flow_map"):
        if _has_meaningful_value(data.get(key)):
            keys.append(key)
    return keys


def _missing_context_for_pattern(pattern: str, available_keys: List[str]) -> List[str]:
    required = PATTERN_REQUIRED_CONTEXT.get(pattern or "UNKNOWN", PATTERN_REQUIRED_CONTEXT["UNKNOWN"])
    missing = [key for key in required if key not in available_keys]
    if pattern == "LIST_DETAIL" and "item_schema" in missing and "nested_flow_map" in available_keys:
        missing.remove("item_schema")
    return missing


def bootstrap_workspace_context(context: MobileAgentContext, reason: str = "navigation_complete") -> Dict[str, Any]:
    data = _load_workspace_context(context)
    data["task_goal"] = context.target
    _append_ui_observation_history(data)
    data["ui_observations"] = _fresh_ui_observation_meta(context, reason)
    if not _has_meaningful_value(data.get("extraction_inference")):
        data["extraction_inference"] = {
            "extraction_pattern": "UNKNOWN",
            "confidence": 0.0,
            "evidence": [],
            "source": "unset_model_must_infer",
        }
    data["updated_at"] = _utc_now_iso()
    saved = _save_workspace_context(context, data)
    return {"ok": True, "path": str(workspace_context_path(context)), "workspace_context": saved}


def read_workspace_context(context: MobileAgentContext) -> Dict[str, Any]:
    path = workspace_context_path(context)
    data = _load_workspace_context(context)
    if not path.exists():
        data = _save_workspace_context(context, data)
    return {"ok": True, "path": str(path), "workspace_context": data}


def update_workspace_context(context: MobileAgentContext, updates: Dict[str, Any]) -> Dict[str, Any]:
    data = _load_workspace_context(context)
    patch = dict(updates or {})
    if "workspace_context" in patch and isinstance(patch["workspace_context"], dict):
        patch = patch["workspace_context"]
    if "ui_observations" in patch and isinstance(patch["ui_observations"], dict):
        persist_current_page_context(context, reason="update_workspace_context")
        ui_observations = {
            key: value
            for key, value in dict(patch.pop("ui_observations") or {}).items()
            if key not in UI_OBSERVATION_RUNTIME_FIELDS
        }
        _append_ui_observation_history(data)
        data["ui_observations"] = _deep_merge(
            _fresh_ui_observation_meta(context, "update_workspace_context"),
            ui_observations,
        )
    data = _deep_merge(data, patch)
    data["task_goal"] = context.target
    data["updated_at"] = _utc_now_iso()
    saved = _save_workspace_context(context, data)
    return {"ok": True, "path": str(workspace_context_path(context)), "workspace_context": saved}


def set_extraction_plan(context: MobileAgentContext, plan: Dict[str, Any]) -> Dict[str, Any]:
    data = _load_workspace_context(context)
    plan_input = dict(plan or {})
    if "plan" in plan_input and isinstance(plan_input["plan"], dict):
        plan_input = plan_input["plan"]
    plan_input.pop("recommended" + "_template", None)
    extraction_pattern = str(plan_input.get("extraction_pattern") or "").strip() or str(
        data.get("extraction_inference", {}).get("extraction_pattern") or "UNKNOWN"
    )
    required_context = PATTERN_REQUIRED_CONTEXT.get(extraction_pattern, PATTERN_REQUIRED_CONTEXT["UNKNOWN"])
    data["extraction_plan"] = _deep_merge(
        {
            "extraction_pattern": extraction_pattern,
            "target": plan_input.get("target") or context.target,
            "initial_position_strategy": plan_input.get("initial_position_strategy")
            or plan_input.get("start_position_strategy")
            or "",
            "collection_scroll_direction": plan_input.get("collection_scroll_direction")
            or plan_input.get("scroll_direction")
            or "unknown",
            "scroll_direction": plan_input.get("scroll_direction") or plan_input.get("collection_scroll_direction") or "unknown",
            "required_context": list(plan_input.get("required_context") or required_context),
            "available_context": [],
            "missing_context": [],
            "notes": list(plan_input.get("notes") or []),
        },
        {k: v for k, v in plan_input.items() if k != "plan"},
    )
    data["task_goal"] = context.target
    available_context = _available_context_keys(data)
    data["extraction_plan"]["available_context"] = available_context
    data["extraction_plan"]["required_context"] = list(required_context)
    data["extraction_plan"]["missing_context"] = _missing_context_for_pattern(
        extraction_pattern,
        available_context,
    )
    data["updated_at"] = _utc_now_iso()
    if extraction_pattern != "UNKNOWN" and not data["extraction_plan"]["missing_context"]:
        context.phase = "script"
    saved = _save_workspace_context(context, data)
    return {"ok": True, "path": str(workspace_context_path(context)), "workspace_context": saved}


def script_generation_gate(context: MobileAgentContext) -> Dict[str, Any]:
    data = _load_workspace_context(context)
    plan = data.get("extraction_plan") if isinstance(data.get("extraction_plan"), dict) else {}
    pattern = str(plan.get("extraction_pattern") or "").strip()
    missing = list(plan.get("missing_context") or [])
    if not pattern:
        return {
            "ok": False,
            "reason": "extraction_plan is missing; run exploration and call set_extraction_plan first",
            "workspace_context_path": str(workspace_context_path(context)),
        }
    if missing:
        return {
            "ok": False,
            "reason": "extraction_plan still has missing_context",
            "missing_context": missing,
            "workspace_context_path": str(workspace_context_path(context)),
        }
    return {
        "ok": True,
        "extraction_pattern": pattern,
        "workspace_context_path": str(workspace_context_path(context)),
    }


def xml_signature(xml_text: str) -> str:
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return hashlib.sha256((xml_text or "").encode("utf-8", errors="ignore")).hexdigest()
    parts = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        rid = node.get("resource-id") or ""
        cls = node.get("class") or ""
        bounds = node.get("bounds") or ""
        if text or desc or rid:
            parts.append("|".join((rid, cls, text, desc, bounds)))
    return hashlib.sha256("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()

def summarize_ui_xml(xml_text: str, max_items: int = 80) -> Dict[str, Any]:
    try:
        root = ET.fromstring(xml_text or "")
    except Exception as exc:
        return {"parse_error": str(exc), "xml_chars": len(xml_text or "")}
    resource_ids: Dict[str, int] = {}
    classes: Dict[str, int] = {}
    texts: List[str] = []
    scrollables: List[Dict[str, str]] = []
    clickables: List[Dict[str, str]] = []
    node_count = 0
    for node in root.iter("node"):
        node_count += 1
        rid = node.get("resource-id") or ""
        cls = node.get("class") or ""
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        bounds = node.get("bounds") or ""
        if rid:
            resource_ids[rid.split("/")[-1]] = resource_ids.get(rid.split("/")[-1], 0) + 1
        if cls:
            classes[cls.split(".")[-1]] = classes.get(cls.split(".")[-1], 0) + 1
        sample = text or desc
        if sample and len(texts) < max_items and sample not in texts:
            texts.append(sample[:120])
        if node.get("scrollable") == "true" and len(scrollables) < 12:
            scrollables.append({"resource_id": rid, "class": cls, "bounds": bounds, "content_desc": desc[:80]})
        if node.get("clickable") == "true" and len(clickables) < 20:
            clickables.append({"text": text[:80], "content_desc": desc[:80], "resource_id": rid, "class": cls, "bounds": bounds})
    top_resource_ids = sorted(resource_ids.items(), key=lambda item: item[1], reverse=True)[:40]
    top_classes = sorted(classes.items(), key=lambda item: item[1], reverse=True)[:30]
    return {
        "xml_chars": len(xml_text or ""),
        "node_count": node_count,
        "top_resource_ids": top_resource_ids,
        "top_classes": top_classes,
        "text_samples": texts,
        "scrollables": scrollables,
        "clickables": clickables,
    }


def persist_current_page_context(context: MobileAgentContext, reason: str = "script_stage") -> Dict[str, Any]:
    """Persist the latest observed page into the script workspace.

    The prompt history may be compacted, but these files remain available to the
    agent and to generated scripts for exact XML/page inspection.
    """
    ctx_dir = workspace_context_dir(context)
    xml_path = ctx_dir / "current_page.xml"
    outline_path = ctx_dir / "current_page_outline.txt"
    meta_path = ctx_dir / "current_page_context.json"
    snapshots_dir = ctx_dir / "page_snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    artifact_stem = _safe_snapshot_name(Path(context.last_ui_artifact or "page").stem)
    reason_stem = _safe_snapshot_name(reason)
    snapshot_stem = f"{artifact_stem}_{reason_stem}_{int(time.time() * 1000)}"
    snapshot_xml_path = snapshots_dir / f"{snapshot_stem}.xml"
    snapshot_outline_path = snapshots_dir / f"{snapshot_stem}_outline.txt"
    xml_path.write_text(context.last_ui_xml or "", encoding="utf-8")
    outline_path.write_text(context.last_ui_outline or "", encoding="utf-8")
    snapshot_xml_path.write_text(context.last_ui_xml or "", encoding="utf-8")
    snapshot_outline_path.write_text(context.last_ui_outline or "", encoding="utf-8")
    payload = {
        "reason": reason,
        "xml_path": str(xml_path),
        "outline_path": str(outline_path),
        "context_path": str(meta_path),
        "snapshot_xml_path": str(snapshot_xml_path),
        "snapshot_outline_path": str(snapshot_outline_path),
        "source_artifact": context.last_ui_artifact,
        "xml_chars": len(context.last_ui_xml or ""),
        "outline_chars": len(context.last_ui_outline or ""),
        "xml_signature": xml_signature(context.last_ui_xml or ""),
        "updated_at": time.time(),
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    context.workspace_context_files.update(
        {
            "current_page_xml": str(xml_path),
            "current_page_outline": str(outline_path),
            "current_page_context": str(meta_path),
            "snapshot_page_xml": str(snapshot_xml_path),
            "snapshot_page_outline": str(snapshot_outline_path),
        }
    )
    return {"ok": True, **payload}


def persist_active_script_snapshot(
    context: MobileAgentContext,
    relative_path: str = "generated_script.py",
    reason: str = "script_update",
) -> Dict[str, Any]:
    path = workspace_path(context, relative_path)
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    ctx_dir = workspace_context_dir(context)
    content = path.read_text(encoding="utf-8", errors="replace")
    snapshot_path = ctx_dir / "active_script_snapshot.py"
    snapshot_path.write_text(content, encoding="utf-8")
    meta = {
        "reason": reason,
        "script_path": str(path),
        "active_script_snapshot": str(snapshot_path),
        "script_chars": len(content),
        "script_lines": len(content.splitlines()),
        "updated_at": time.time(),
    }
    (ctx_dir / "active_script_context.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    context.workspace_context_files.update(
        {
            "active_script": str(path),
            "active_script_snapshot": str(snapshot_path),
            "active_script_context": str(ctx_dir / "active_script_context.json"),
        }
    )
    return {"ok": True, **meta}


def snapshot_script_version(
    context: MobileAgentContext,
    path: Path,
    reason: str,
) -> Dict[str, Any]:
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    snapshots_dir = script_workspace(context) / "script_snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_reason = _safe_snapshot_name(reason)
    snapshot_path = snapshots_dir / f"{path.stem}_{stamp}_{safe_reason}{path.suffix}"
    content = path.read_text(encoding="utf-8", errors="replace")
    snapshot_path.write_text(content, encoding="utf-8")
    return {
        "ok": True,
        "snapshot_path": str(snapshot_path),
        "bytes": len(content.encode("utf-8")),
        "reason": reason,
    }


def refresh_workspace_context(
    context: MobileAgentContext,
    relative_path: str = "generated_script.py",
    reason: str = "script_stage",
) -> Dict[str, Any]:
    page = persist_current_page_context(context, reason=reason)
    script = persist_active_script_snapshot(context, relative_path=relative_path, reason=reason)
    index: Dict[str, Any] = {}
    if script.get("ok"):
        index = refresh_script_index(context, relative_path=relative_path, reason=reason)
    return {"ok": True, "page_context": page, "script_context": script, "script_index": index}


def workspace_path(context: MobileAgentContext, relative_path: str = "generated_script.py") -> Path:
    workspace = script_workspace(context).resolve()
    path = (workspace / relative_path).resolve()
    if workspace != path and workspace not in path.parents:
        raise ValueError(f"path outside script workspace: {relative_path}")
    return path


def _compile_script(path: Path) -> Dict[str, Any]:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return {"syntax_ok": False, "syntax_error": str(exc)}
    except Exception as exc:
        return {"syntax_ok": False, "syntax_error": f"{type(exc).__name__}: {exc}"}
    return {"syntax_ok": True, "syntax_error": ""}


SCRIPT_SECTION_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "parse_logic": (
        "dump_hierarchy",
        "elementtree",
        "fromstring",
        "parse(",
        ".iter(",
        "resource-id",
        "content-desc",
        "raw_components",
        "normalize_block",
        "extract_visible",
        "collect_raw",
    ),
    "scroll_logic": (
        "swipe",
        "scroll",
        "fling",
        "drag",
        "scroll_to",
        "older",
        "newer",
    ),
    "dedup_logic": (
        "seen",
        "dedup",
        "duplicate",
        "hashlib",
        "canonical",
        "fingerprint",
        "unique",
    ),
    "output_logic": (
        "json.dump",
        RECORDS_FILENAME,
        "output_path",
        "write_text",
        "records_path",
    ),
    "field_logic": (
        "normalized_fields",
        "raw_components",
        "content_text",
        "metadata",
        "field",
        "sender",
        "timestamp",
    ),
    "device_logic": (
        "uiautomator2",
        "u2.connect",
        "device_serial",
        "app_package",
    ),
}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    if isinstance(node, ast.Call):
        return _call_name(node.func)
    return ""


def _literal_value(node: ast.AST) -> Any:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)) and len(value) <= 20:
        return list(value)
    if isinstance(value, dict) and len(value) <= 20:
        return value
    return f"<{type(value).__name__}>"


def _node_line_range(node: ast.AST) -> Tuple[int, int]:
    start = int(getattr(node, "lineno", 1) or 1)
    end = int(getattr(node, "end_lineno", start) or start)
    return start, max(start, end)


def _classify_source(name: str, source: str) -> List[Dict[str, Any]]:
    lowered = f"{name}\n{source}".lower()
    matches: List[Dict[str, Any]] = []
    for section, keywords in SCRIPT_SECTION_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword.lower() in lowered]
        if hits:
            matches.append({"section": section, "matched_keywords": hits[:8]})
    return matches


def _index_imports(tree: ast.Module) -> List[str]:
    imports: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend(f"{module}.{alias.name}" if module else alias.name for alias in node.names)
    return imports


def _index_constants(tree: ast.Module) -> Dict[str, Any]:
    constants: Dict[str, Any] = {}
    for node in tree.body:
        targets: List[ast.AST] = []
        value: Optional[ast.AST] = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if value is None:
            continue
        literal = _literal_value(value)
        if literal is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                constants[target.id] = literal
    return constants


def _index_function(node: ast.AST, source_lines: List[str], class_name: str = "") -> Dict[str, Any]:
    start, end = _node_line_range(node)
    source = "\n".join(source_lines[start - 1 : end])
    calls = sorted(
        {
            _call_name(call.func)
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and _call_name(call.func)
        }
    )
    args: List[str] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = [arg.arg for arg in node.args.args]
    name = getattr(node, "name", "")
    qualified_name = f"{class_name}.{name}" if class_name else name
    labels = _classify_source(qualified_name, source)
    return {
        "name": name,
        "qualified_name": qualified_name,
        "start_line": start,
        "end_line": end,
        "line_count": end - start + 1,
        "args": args,
        "calls": calls[:60],
        "section_labels": labels,
        "read_hint": {"action": "read_script", "offset": start, "limit": end - start + 1},
    }


def _build_script_index(path: Path, relative_path: str, reason: str) -> Dict[str, Any]:
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    payload: Dict[str, Any] = {
        "ok": True,
        "version": 1,
        "reason": reason,
        "script_path": str(path),
        "relative_path": relative_path,
        "script_hash": hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest(),
        "script_chars": len(content),
        "script_lines": len(lines),
        "generated_at": time.time(),
        "imports": [],
        "constants": {},
        "classes": [],
        "functions": [],
        "important_sections": {},
    }
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError as exc:
        payload.update(
            {
                "ok": False,
                "parse_error": f"SyntaxError: {exc}",
                "error_line": int(exc.lineno or 0),
                "read_hint": {"action": "read_script", "offset": max(1, int(exc.lineno or 1) - 20), "limit": 60},
            }
        )
        return payload

    payload["imports"] = _index_imports(tree)
    payload["constants"] = _index_constants(tree)

    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            start, end = _node_line_range(node)
            class_item = {
                "name": node.name,
                "start_line": start,
                "end_line": end,
                "line_count": end - start + 1,
                "methods": [],
                "read_hint": {"action": "read_script", "offset": start, "limit": end - start + 1},
            }
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    item = _index_function(child, lines, class_name=node.name)
                    class_item["methods"].append(item)
                    functions.append(item)
            classes.append(class_item)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_index_function(node, lines))

    payload["classes"] = classes
    payload["functions"] = functions
    important: Dict[str, List[Dict[str, Any]]] = {}
    for item in functions:
        for label in item.get("section_labels", []):
            section = str(label.get("section") or "")
            if not section:
                continue
            important.setdefault(section, []).append(
                {
                    "function": item.get("qualified_name"),
                    "start_line": item.get("start_line"),
                    "end_line": item.get("end_line"),
                    "matched_keywords": label.get("matched_keywords", []),
                    "read_hint": item.get("read_hint"),
                }
            )
    payload["important_sections"] = important
    return payload


def refresh_script_index(
    context: MobileAgentContext,
    relative_path: str = "generated_script.py",
    reason: str = "script_update",
) -> Dict[str, Any]:
    path = workspace_path(context, relative_path)
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    index = _build_script_index(path, relative_path=relative_path, reason=reason)
    index_path = script_workspace(context) / "script_index.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    context.workspace_context_files["script_index"] = str(index_path)
    return {
        "ok": bool(index.get("ok")),
        "path": str(index_path),
        "script_path": str(path),
        "script_hash": index.get("script_hash"),
        "script_lines": index.get("script_lines"),
        "function_count": len(index.get("functions") or []),
        "class_count": len(index.get("classes") or []),
        "important_sections": index.get("important_sections") or {},
        "parse_error": index.get("parse_error", ""),
        "read_hint": index.get("read_hint", {}),
    }


def read_script_index(context: MobileAgentContext, relative_path: str = "generated_script.py") -> Dict[str, Any]:
    index_path = script_workspace(context) / "script_index.json"
    script_path = workspace_path(context, relative_path)
    if not index_path.exists() and script_path.exists():
        refresh_script_index(context, relative_path=relative_path, reason="read_script_index_missing")
    if not index_path.exists():
        return {"ok": False, "error": "script_index.json not found"}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"script_index.json parse error: {exc}", "path": str(index_path)}
    current_hash = ""
    if script_path.exists():
        content = script_path.read_text(encoding="utf-8", errors="replace")
        current_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    return {
        "ok": True,
        "path": str(index_path),
        "script_path": str(script_path),
        "stale": bool(current_hash and data.get("script_hash") != current_hash),
        "index": data,
        "repair_targets": _script_repair_targets(context, data),
    }


def _script_repair_targets(context: MobileAgentContext, index: Dict[str, Any]) -> List[Dict[str, Any]]:
    run_state = context.last_run_state or {}
    diagnostics = run_state.get("script_diagnostics") or {}
    issues = diagnostics.get("issues") or []
    if not isinstance(issues, list):
        return []
    important = index.get("important_sections") or {}

    def section_hints(names: List[str], max_hints: int = 4) -> List[Dict[str, Any]]:
        hints: List[Dict[str, Any]] = []
        seen = set()
        for name in names:
            for item in important.get(name) or []:
                if not isinstance(item, dict):
                    continue
                key = (item.get("function"), item.get("start_line"), item.get("end_line"))
                if key in seen:
                    continue
                seen.add(key)
                hint = item.get("read_hint") or {}
                hints.append(
                    {
                        "function": item.get("function"),
                        "start_line": item.get("start_line"),
                        "end_line": item.get("end_line"),
                        "read_hint": hint,
                    }
                )
                if len(hints) >= max_hints:
                    return hints
        return hints

    targets: List[Dict[str, Any]] = []
    for issue in issues[:5]:
        if not isinstance(issue, dict):
            continue
        issue_type = str(issue.get("type") or "")
        evidence = str(issue.get("evidence") or "")
        sections = ["parse_logic", "field_logic"]
        action = "inspect parser/filter logic and patch the smallest complete function"
        if issue_type in {"global_hash_duplicates", "duplicate_records"} or "duplicate" in evidence.lower():
            sections = ["dedup_logic", "output_logic"]
            action = "patch canonical hash/global seen logic, then rerun"
        elif issue_type in {"field_completeness", "missing_core_fields"}:
            sections = ["field_logic", "parse_logic", "output_logic"]
            if "date" in evidence.lower() or "timestamp" in evidence.lower():
                action = "patch date/timestamp propagation in normalize/process/main logic only if task depends on full date"
            else:
                action = "patch field normalization only if core evidence is missing"
        elif issue_type in {"parser_or_filter_failed", "records_empty"}:
            sections = ["parse_logic", "field_logic"]
            action = "patch parser/filter functions before rerun"
        elif "scroll" in issue_type or "scroll" in evidence.lower():
            sections = ["scroll_logic", "parse_logic"]
            action = "patch scroll bounds/direction or stop condition"
        elif "workspace_xml" in issue_type:
            sections = ["device_logic", "parse_logic"]
            action = "patch XML path loading before rerun"
        targets.append(
            {
                "issue_type": issue_type,
                "severity": issue.get("severity"),
                "evidence": evidence,
                "recommended_action": action,
                "recommended_reads": section_hints(sections),
            }
        )
    return targets


def _syntax_error_line(compile_result: Dict[str, Any]) -> int:
    text = str(compile_result.get("syntax_error") or "")
    match = re.search(r"line\s+(\d+)", text)
    return int(match.group(1)) if match else 0


def write_script(
    context: MobileAgentContext,
    relative_path: str = "generated_script.py",
    content: str = "",
    overwrite: bool = True,
) -> Dict[str, Any]:
    """Write a complete script file, intended for the initial prototype.

    This action deliberately does not require a prior read_script. It avoids
    the brittle "blank file + huge replace_script_lines" path for first script
    generation while preserving read-before-edit checks for later repairs.
    """
    path = workspace_path(context, relative_path)
    if path.exists() and not overwrite:
        return {"ok": False, "error": "script already exists; set overwrite=true or use patch_script", "path": str(path)}
    previous_snapshot: Dict[str, Any] = {}
    if path.exists():
        previous_snapshot = snapshot_script_version(context, path, reason="before_write_script_overwrite")
    if not isinstance(content, str) or not content.strip():
        return {"ok": False, "error": "content is empty; write_script requires a complete runnable prototype"}
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    context.phase = "script"
    context.script_read_state[str(path)] = {
        "mtime": path.stat().st_mtime,
        "content": content,
        "offset": 1,
        "limit": 0,
        "is_partial_view": False,
        "read_ranges": [{"start_line": 1, "end_line": len(content.splitlines()), "limit": 0}],
    }
    page_context = persist_current_page_context(context, reason="write_script")
    active_snapshot = persist_active_script_snapshot(context, relative_path=relative_path, reason="after_write_script")
    script_index = refresh_script_index(context, relative_path=relative_path, reason="after_write_script")
    compile_result = _compile_script(path)
    syntax_line = _syntax_error_line(compile_result)
    repair_guidance = ""
    if not compile_result.get("syntax_ok"):
        repair_guidance = (
            "Script was written to disk but failed syntax check. Do not call write_script again for the same prototype; "
            "use read_script and edit_script or replace_script_lines to repair the existing file."
        )
    return {
        "ok": bool(compile_result.get("syntax_ok")),
        "path": str(path),
        "bytes": len(content.encode("utf-8")),
        "lines": len(content.splitlines()),
        "previous_script_snapshot": previous_snapshot.get("snapshot_path"),
        "active_script_snapshot": active_snapshot.get("active_script_snapshot"),
        "workspace_context": {
            "current_page_xml": page_context.get("xml_path"),
            "active_script_snapshot": active_snapshot.get("active_script_snapshot"),
            "script_index": script_index.get("path"),
        },
        "script_index": script_index,
        "syntax_error_line": syntax_line,
        "repair_guidance": repair_guidance,
        "recommended_next_action": "read_script_then_patch" if repair_guidance else "",
        **compile_result,
    }


def read_script(
    context: MobileAgentContext,
    relative_path: str = "generated_script.py",
    offset: int = 1,
    limit: int = DEFAULT_SCRIPT_READ_LIMIT,
) -> Dict[str, Any]:
    path = workspace_path(context, relative_path)
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    content = path.read_text(encoding="utf-8", errors="replace")
    mtime = path.stat().st_mtime
    lines = content.splitlines()
    start = max(1, int(offset))
    requested_limit = int(limit)
    selected = lines[start - 1 :] if requested_limit <= 0 else lines[start - 1 : start - 1 + requested_limit]
    has_more = start - 1 + len(selected) < len(lines)
    is_partial_view = start != 1 or has_more
    state = context.script_read_state.get(str(path)) or {}
    read_ranges = list(state.get("read_ranges") or [])
    end_line = start + len(selected) - 1 if selected else start - 1
    overlap = _read_range_overlap(read_ranges, start, end_line) if selected else None
    repeat_exact = bool(
        overlap
        and overlap.get("exact")
        and state.get("mtime") == mtime
        and state.get("content") == content
    )
    read_ranges.append({"start_line": start, "end_line": end_line, "limit": requested_limit})
    read_ranges = read_ranges[-20:]
    context.script_read_state[str(path)] = {
        "mtime": mtime,
        "content": content,
        "offset": start,
        "limit": requested_limit,
        "is_partial_view": is_partial_view,
        "read_ranges": read_ranges,
    }
    numbered_lines = []
    for idx, line in enumerate(selected, start):
        suffix = ""
        if len(line) > MAX_SCRIPT_LINE_LENGTH:
            line = line[:MAX_SCRIPT_LINE_LENGTH]
            suffix = f"... (line truncated to {MAX_SCRIPT_LINE_LENGTH} chars)"
        numbered_lines.append(f"{idx}: {line}{suffix}")
    numbered = "\n".join(numbered_lines)
    return {
        "ok": True,
        "type": "script_text",
        "path": str(path),
        "offset": start,
        "limit": requested_limit,
        "total_lines": len(lines),
        "returned_lines": len(selected),
        "has_more": has_more,
        "is_partial_view": is_partial_view,
        "start_line": start,
        "end_line": end_line,
        "repeat_exact": repeat_exact,
        "overlap": overlap or {},
        "read_guidance": (
            "This is an exact repeat of a range already read; use the existing context, grep_script, "
            "or edit/replace next instead of repeatedly reading the same slice."
            if repeat_exact
            else "Read output is line-numbered as '<line>: <content>'. Do not include line prefixes in edit_script old_string/new_string."
        ),
        "line_numbered_content": numbered,
    }


def _read_range_overlap(read_ranges: List[Dict[str, Any]], start: int, end: int) -> Optional[Dict[str, Any]]:
    if end < start:
        return None
    best: Optional[Dict[str, Any]] = None
    best_count = 0
    for item in read_ranges:
        old_start = int(item.get("start_line") or 0)
        old_end = int(item.get("end_line") or 0)
        if not old_start or not old_end:
            continue
        overlap_start = max(start, old_start)
        overlap_end = min(end, old_end)
        if overlap_end < overlap_start:
            continue
        count = overlap_end - overlap_start + 1
        if count > best_count:
            requested = end - start + 1
            best_count = count
            best = {
                "start_line": old_start,
                "end_line": old_end,
                "overlap_lines": count,
                "overlap_ratio": round(count / max(1, requested), 3),
                "exact": old_start == start and old_end == end,
            }
    return best


def grep_script(
    context: MobileAgentContext,
    relative_path: str = "generated_script.py",
    pattern: str = "",
    case_sensitive: bool = True,
    context_lines: int = 2,
    max_matches: int = MAX_GREP_MATCHES,
    regex: bool = True,
) -> Dict[str, Any]:
    path = workspace_path(context, relative_path)
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    if not pattern:
        return {"ok": False, "error": "pattern is required"}
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(pattern if regex else re.escape(pattern), flags)
    except re.error as exc:
        return {"ok": False, "error": f"invalid regex: {exc}"}
    matches: List[Dict[str, Any]] = []
    context_n = max(0, min(int(context_lines), 10))
    for idx, line in enumerate(lines, 1):
        if not compiled.search(line):
            continue
        start = max(1, idx - context_n)
        end = min(len(lines), idx + context_n)
        snippet = "\n".join(f"{line_no}: {lines[line_no - 1]}" for line_no in range(start, end + 1))
        matches.append({"line": idx, "text": line[:MAX_SCRIPT_LINE_LENGTH], "snippet": snippet})
        if len(matches) >= max(1, min(int(max_matches), MAX_GREP_MATCHES)):
            break
    truncated = len(matches) >= max(1, min(int(max_matches), MAX_GREP_MATCHES))
    return {
        "ok": True,
        "path": str(path),
        "pattern": pattern,
        "regex": regex,
        "case_sensitive": case_sensitive,
        "match_count": len(matches),
        "truncated": truncated,
        "matches": matches,
        "read_guidance": "Use read_script with a larger window around the relevant match, then edit_script or replace_script_lines.",
    }


def _validate_script_writable(context: MobileAgentContext, path: Path) -> Dict[str, Any]:
    state = context.script_read_state.get(str(path))
    if not state:
        return {"ok": False, "error": "script has not been read yet; call read_script first"}
    current_mtime = path.stat().st_mtime
    current_content = path.read_text(encoding="utf-8", errors="replace")
    if current_mtime > float(state.get("mtime") or 0) and current_content != state.get("content"):
        return {"ok": False, "error": "script has changed since last read; call read_script again before editing"}
    return {
        "ok": True,
        "content": current_content,
        "read_was_partial": bool(state.get("is_partial_view")),
    }


def _normalize_patch_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _detect_line_ending(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _convert_line_endings(text: str, ending: str) -> str:
    normalized = _normalize_line_endings(text)
    return normalized if ending == "\n" else normalized.replace("\n", ending)


def _line_start_index(lines: List[str], line_index: int) -> int:
    return sum(len(lines[idx]) + 1 for idx in range(line_index))


def _line_block_text(content: str, start_line_index: int, end_line_index: int) -> str:
    lines = content.split("\n")
    start = _line_start_index(lines, start_line_index)
    end = start
    for idx in range(start_line_index, end_line_index + 1):
        end += len(lines[idx])
        if idx < end_line_index:
            end += 1
    return content[start:end]


def _levenshtein(a: str, b: str) -> int:
    if not a or not b:
        return max(len(a), len(b))
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


def _strip_common_indentation(text: str) -> str:
    lines = text.split("\n")
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return text
    min_indent = min(len(re.match(r"^\s*", line).group(0)) for line in non_empty)
    if min_indent <= 0:
        return text
    return "\n".join(line[min_indent:] if line.strip() else line for line in lines)


def _unescape_patch_text(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        value = match.group(1)
        return {
            "n": "\n",
            "t": "\t",
            "r": "\r",
            "'": "'",
            '"': '"',
            "`": "`",
            "\\": "\\",
            "\n": "\n",
            "$": "$",
        }.get(value, match.group(0))

    return re.sub(r"\\(n|t|r|'|\"|`|\\|\n|\$)", repl, text)


def _normalized_patch_variants(old_text: str) -> List[Tuple[str, str]]:
    stripped = _strip_numbered_line_prefixes(old_text)
    variants = [("exact", old_text)]
    if stripped != old_text:
        variants.append(("line_number_prefix_stripped", stripped))
    return [(strategy, text) for strategy, text in variants if text]


def _opencode_replacer_matches(content: str, find: str) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []

    def add(strategy: str, text: str) -> None:
        if not text:
            return
        start = 0
        while True:
            idx = content.find(text, start)
            if idx == -1:
                break
            matches.append({"strategy": strategy, "match_text": text, "start_char": idx, "end_char": idx + len(text)})
            start = idx + max(1, len(text))

    for strategy, candidate in _normalized_patch_variants(find):
        add(strategy, candidate)
        if matches:
            return matches

    content_lines = content.split("\n")
    find_lines = (_strip_numbered_line_prefixes(find) or find).split("\n")
    if find_lines and find_lines[-1] == "":
        find_lines = find_lines[:-1]

    # Line-trimmed block match.
    if find_lines:
        for idx in range(0, len(content_lines) - len(find_lines) + 1):
            if all(content_lines[idx + j].strip() == find_lines[j].strip() for j in range(len(find_lines))):
                matches.append(
                    {
                        "strategy": "line_trimmed",
                        "match_text": "\n".join(content_lines[idx : idx + len(find_lines)]),
                        "start_line": idx + 1,
                        "end_line": idx + len(find_lines),
                    }
                )
        if matches:
            return matches

    # Block anchor match: first and last trimmed lines anchor the block; middle can drift.
    if len(find_lines) >= 3:
        first = find_lines[0].strip()
        last = find_lines[-1].strip()
        candidates: List[Tuple[int, int]] = []
        for idx, line in enumerate(content_lines):
            if line.strip() != first:
                continue
            for end_idx in range(idx + 2, len(content_lines)):
                if content_lines[end_idx].strip() == last:
                    candidates.append((idx, end_idx))
                    break
        if len(candidates) == 1:
            start_idx, end_idx = candidates[0]
            actual = content_lines[start_idx : end_idx + 1]
            lines_to_check = min(max(0, len(find_lines) - 2), max(0, len(actual) - 2))
            similarity = 1.0
            if lines_to_check:
                scores = []
                for offset in range(1, lines_to_check + 1):
                    a = actual[offset].strip()
                    b = find_lines[offset].strip()
                    max_len = max(len(a), len(b))
                    scores.append(1 - (_levenshtein(a, b) / max_len if max_len else 0))
                similarity = sum(scores) / len(scores)
            if similarity >= SINGLE_CANDIDATE_SIMILARITY_THRESHOLD:
                matches.append(
                    {
                        "strategy": "block_anchor",
                        "match_text": "\n".join(actual),
                        "start_line": start_idx + 1,
                        "end_line": end_idx + 1,
                        "similarity": round(similarity, 3),
                    }
                )
                return matches
        elif candidates:
            best: Optional[Tuple[float, int, int]] = None
            for start_idx, end_idx in candidates:
                actual = content_lines[start_idx : end_idx + 1]
                lines_to_check = min(max(0, len(find_lines) - 2), max(0, len(actual) - 2))
                similarity = 1.0
                if lines_to_check:
                    scores = []
                    for offset in range(1, lines_to_check + 1):
                        a = actual[offset].strip()
                        b = find_lines[offset].strip()
                        max_len = max(len(a), len(b))
                        scores.append(1 - (_levenshtein(a, b) / max_len if max_len else 0))
                    similarity = sum(scores) / len(scores)
                if best is None or similarity > best[0]:
                    best = (similarity, start_idx, end_idx)
            if best and best[0] >= MULTIPLE_CANDIDATES_SIMILARITY_THRESHOLD:
                _, start_idx, end_idx = best
                matches.append(
                    {
                        "strategy": "block_anchor",
                        "match_text": "\n".join(content_lines[start_idx : end_idx + 1]),
                        "start_line": start_idx + 1,
                        "end_line": end_idx + 1,
                        "similarity": round(best[0], 3),
                    }
                )
                return matches

    # Whitespace-normalized single-line and block matches.
    normalized_find = _normalize_patch_text(_strip_numbered_line_prefixes(find) or find)
    if normalized_find:
        for line in content_lines:
            normalized_line = _normalize_patch_text(line)
            if normalized_line == normalized_find:
                add("whitespace_normalized", line)
                if matches:
                    return matches
            if normalized_find in normalized_line:
                words = re.split(r"\s+", (_strip_numbered_line_prefixes(find) or find).strip())
                pattern = r"\s+".join(re.escape(word) for word in words if word)
                if pattern:
                    try:
                        hit = re.search(pattern, line)
                    except re.error:
                        hit = None
                    if hit:
                        add("whitespace_normalized", hit.group(0))
                        if matches:
                            return matches
        if len(find_lines) > 1:
            for idx in range(0, len(content_lines) - len(find_lines) + 1):
                block = "\n".join(content_lines[idx : idx + len(find_lines)])
                if _normalize_patch_text(block) == normalized_find:
                    matches.append(
                        {
                            "strategy": "whitespace_normalized",
                            "match_text": block,
                            "start_line": idx + 1,
                            "end_line": idx + len(find_lines),
                        }
                    )
            if matches:
                return matches

    # Indentation-flexible block match.
    if find_lines:
        normalized_find_indent = _strip_common_indentation(_strip_numbered_line_prefixes(find) or find)
        for idx in range(0, len(content_lines) - len(find_lines) + 1):
            block = "\n".join(content_lines[idx : idx + len(find_lines)])
            if _strip_common_indentation(block) == normalized_find_indent:
                matches.append(
                    {
                        "strategy": "indentation_flexible",
                        "match_text": block,
                        "start_line": idx + 1,
                        "end_line": idx + len(find_lines),
                    }
                )
        if matches:
            return matches

    # Escape-normalized match.
    unescaped_find = _unescape_patch_text(_strip_numbered_line_prefixes(find) or find)
    add("escape_normalized", unescaped_find)
    if matches:
        return matches
    unescaped_find_lines = unescaped_find.split("\n")
    if len(unescaped_find_lines) > 1:
        for idx in range(0, len(content_lines) - len(unescaped_find_lines) + 1):
            block = "\n".join(content_lines[idx : idx + len(unescaped_find_lines)])
            if _unescape_patch_text(block) == unescaped_find:
                matches.append(
                    {
                        "strategy": "escape_normalized",
                        "match_text": block,
                        "start_line": idx + 1,
                        "end_line": idx + len(unescaped_find_lines),
                    }
                )
        if matches:
            return matches

    # Trimmed-boundary match.
    stripped_find = (_strip_numbered_line_prefixes(find) or find).strip()
    if stripped_find and stripped_find != find:
        add("trimmed_boundary", stripped_find)
        if matches:
            return matches
        for idx in range(0, len(content_lines) - len(find_lines) + 1):
            block = "\n".join(content_lines[idx : idx + len(find_lines)])
            if block.strip() == stripped_find:
                matches.append(
                    {
                        "strategy": "trimmed_boundary",
                        "match_text": block,
                        "start_line": idx + 1,
                        "end_line": idx + len(find_lines),
                    }
                )
        if matches:
            return matches

    # Context-aware match: first and last line anchors with at least 50% middle line agreement.
    if len(find_lines) >= 3:
        first = find_lines[0].strip()
        last = find_lines[-1].strip()
        for idx, line in enumerate(content_lines):
            if line.strip() != first:
                continue
            for end_idx in range(idx + 2, len(content_lines)):
                if content_lines[end_idx].strip() != last:
                    continue
                block_lines = content_lines[idx : end_idx + 1]
                if len(block_lines) != len(find_lines):
                    break
                matching = 0
                total = 0
                for offset in range(1, len(block_lines) - 1):
                    actual = block_lines[offset].strip()
                    expected = find_lines[offset].strip()
                    if actual or expected:
                        total += 1
                        matching += int(actual == expected)
                if total == 0 or matching / total >= 0.5:
                    matches.append(
                        {
                            "strategy": "context_aware",
                            "match_text": "\n".join(block_lines),
                            "start_line": idx + 1,
                            "end_line": end_idx + 1,
                        }
                    )
                    return matches
                break

    return matches


def _strip_numbered_line_prefixes(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"^\s*\d{1,6}:\s?", "", line))
    return "\n".join(lines)


def _find_opencode_style_match(content: str, old_text: str, replace_all: bool = False) -> Dict[str, Any]:
    matches = _opencode_replacer_matches(content, old_text)
    if not matches:
        return {"ok": False, "error": "not_found", "candidate_count": 0}
    first = matches[0]
    match_text = str(first.get("match_text") or "")
    occurrences = content.count(match_text)
    if replace_all:
        return {
            "ok": True,
            "match_text": match_text,
            "strategy": first.get("strategy") or "unknown",
            "occurrences": occurrences,
            "all_matches": matches[:10],
        }
    if occurrences == 1:
        return {
            "ok": True,
            "match_text": match_text,
            "strategy": first.get("strategy") or "unknown",
            "occurrences": 1,
            "match": {k: v for k, v in first.items() if k != "match_text"},
        }
    return {
        "ok": False,
        "error": "multiple_matches",
        "occurrences": occurrences,
        "strategy": first.get("strategy") or "unknown",
        "candidate_snippets": _nearby_patch_candidates(content, old_text),
    }


def _nearby_patch_candidates(content: str, old_text: str, limit: int = 5) -> List[Dict[str, Any]]:
    target = _normalize_patch_text(_strip_numbered_line_prefixes(old_text) or old_text)
    if not target:
        return []
    lines = content.splitlines()
    old_line_count = max(1, len(old_text.splitlines()))
    scored: List[tuple] = []
    for idx in range(len(lines)):
        snippet = "\n".join(lines[idx : min(len(lines), idx + old_line_count)])
        score = difflib.SequenceMatcher(None, target, _normalize_patch_text(snippet)).ratio()
        scored.append((score, idx + 1, min(len(lines), idx + old_line_count), snippet))
    scored.sort(reverse=True)
    return [
        {"score": round(score, 3), "start_line": start, "end_line": end, "snippet": snippet}
        for score, start, end, snippet in scored[:limit]
        if score >= 0.45
    ]


def patch_script(
    context: MobileAgentContext,
    relative_path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> Dict[str, Any]:
    return edit_script(
        context,
        relative_path=relative_path,
        old_string=old_text,
        new_string=new_text,
        replace_all=replace_all,
        tool_name="patch_script",
    )


def edit_script(
    context: MobileAgentContext,
    relative_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    tool_name: str = "edit_script",
) -> Dict[str, Any]:
    path = workspace_path(context, relative_path)
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    if old_string == new_string:
        return {"ok": False, "error": "old_string and new_string are identical"}
    validation = _validate_script_writable(context, path)
    if not validation.get("ok"):
        return validation
    content = str(validation.get("content") or "")
    ending = _detect_line_ending(content)
    search = _convert_line_endings(old_string, ending)
    replacement = _convert_line_endings(new_string, ending)
    match = _find_opencode_style_match(content, search, replace_all=replace_all)
    if not match.get("ok"):
        error = match.get("error") or "old_string not found"
        return {
            "ok": False,
            "error": "old_string not found" if error == "not_found" else "old_string appears multiple times; provide more surrounding context or set replace_all=true",
            "match_error": error,
            "suggestion": "Read a larger surrounding block and retry with unique first/last anchor lines, or use replace_script_lines for a known line range.",
            "match_strategy": match.get("strategy"),
            "occurrences": match.get("occurrences", 0),
            "candidate_snippets": match.get("candidate_snippets") or _nearby_patch_candidates(content, old_string),
        }
    match_text = str(match.get("match_text") or "")
    matches = int(match.get("occurrences") or content.count(match_text))
    previous_snapshot = snapshot_script_version(context, path, reason=f"before_{tool_name}")
    next_content = content.replace(match_text, replacement, -1 if replace_all else 1)
    diff = "".join(
        difflib.unified_diff(
            _normalize_line_endings(content).splitlines(keepends=True),
            _normalize_line_endings(next_content).splitlines(keepends=True),
            fromfile=f"{path.name} before",
            tofile=f"{path.name} after",
            n=3,
        )
    )
    path.write_text(next_content, encoding="utf-8")
    context.script_read_state[str(path)] = {
        "mtime": path.stat().st_mtime,
        "content": next_content,
        "offset": 1,
        "limit": 0,
        "is_partial_view": False,
        "read_ranges": [{"start_line": 1, "end_line": len(next_content.splitlines()), "limit": 0}],
    }
    active_snapshot = persist_active_script_snapshot(context, relative_path=relative_path, reason=f"after_{tool_name}")
    script_index = refresh_script_index(context, relative_path=relative_path, reason=f"after_{tool_name}")
    compile_result = _compile_script(path)
    return {
        "ok": True,
        "path": str(path),
        "replacements": matches if replace_all else 1,
        "match_strategy": match.get("strategy") or "unknown",
        "match": match.get("match", {}),
        "read_was_partial": bool(validation.get("read_was_partial")),
        "previous_script_snapshot": previous_snapshot.get("snapshot_path"),
        "active_script_snapshot": active_snapshot.get("active_script_snapshot"),
        "script_index": script_index,
        "syntax_error_line": _syntax_error_line(compile_result),
        "recommended_next_action": "run_script" if compile_result.get("syntax_ok") else "read_script_then_repair_syntax",
        **compile_result,
        "diff": diff[-6000:],
    }


def replace_script_lines(
    context: MobileAgentContext,
    relative_path: str,
    start_line: int,
    end_line: int,
    new_text: str,
) -> Dict[str, Any]:
    path = workspace_path(context, relative_path)
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    validation = _validate_script_writable(context, path)
    if not validation.get("ok"):
        return validation
    content = str(validation.get("content") or "")
    lines = content.splitlines(keepends=True)
    start = max(1, int(start_line))
    end = max(start, int(end_line))
    previous_snapshot = snapshot_script_version(context, path, reason="before_replace_script_lines")
    replacement = new_text if new_text.endswith("\n") else new_text + "\n"
    next_lines = lines[: start - 1] + replacement.splitlines(keepends=True) + lines[end:]
    next_content = "".join(next_lines)
    diff = "".join(
        difflib.unified_diff(
            content.splitlines(keepends=True),
            next_content.splitlines(keepends=True),
            fromfile=f"{path.name} before",
            tofile=f"{path.name} after",
            n=3,
        )
    )
    path.write_text(next_content, encoding="utf-8")
    context.script_read_state[str(path)] = {
        "mtime": path.stat().st_mtime,
        "content": next_content,
        "offset": 1,
        "limit": 0,
        "is_partial_view": False,
        "read_ranges": [{"start_line": 1, "end_line": len(next_content.splitlines()), "limit": 0}],
    }
    active_snapshot = persist_active_script_snapshot(context, relative_path=relative_path, reason="after_replace_script_lines")
    script_index = refresh_script_index(context, relative_path=relative_path, reason="after_replace_script_lines")
    compile_result = _compile_script(path)
    return {
        "ok": True,
        "path": str(path),
        "start_line": start,
        "end_line": end,
        "previous_script_snapshot": previous_snapshot.get("snapshot_path"),
        "active_script_snapshot": active_snapshot.get("active_script_snapshot"),
        "script_index": script_index,
        "syntax_error_line": _syntax_error_line(compile_result),
        "recommended_next_action": "run_script" if compile_result.get("syntax_ok") else "read_script_then_repair_syntax",
        **compile_result,
        "diff": diff[-6000:],
    }


def run_script(context: MobileAgentContext, relative_path: str = "generated_script.py", timeout_seconds: int = 180) -> Dict[str, Any]:
    path = workspace_path(context, relative_path)
    if not path.exists():
        return {"ok": False, "error": f"script not found: {path}"}
    workspace = script_workspace(context).resolve()
    script_index = refresh_script_index(context, relative_path=relative_path, reason="before_run_script")
    current_xml = context.workspace_context_files.get("current_page_xml", "")
    current_outline = context.workspace_context_files.get("current_page_outline", "")
    workspace_context_file = context.workspace_context_files.get("workspace_context", str(workspace_context_path(context)))
    current_xml_path = str(Path(current_xml).resolve()) if current_xml else ""
    current_outline_path = str(Path(current_outline).resolve()) if current_outline else ""
    workspace_context_file_path = str(Path(workspace_context_file).resolve()) if workspace_context_file else ""
    env = dict(os.environ)
    env.update(
        {
            "FORENSIFLOW_AGENT_WORKSPACE": str(workspace),
            "FORENSIFLOW_DEVICE_SERIAL": context.device_serial,
            "FORENSIFLOW_TARGET": context.target,
            "FORENSIFLOW_APP_PACKAGE": context.package_name,
            "FORENSIFLOW_CURRENT_UI_XML": current_xml_path,
            "FORENSIFLOW_CURRENT_UI_OUTLINE": current_outline_path,
            "FORENSIFLOW_WORKSPACE_CONTEXT": workspace_context_file_path,
            "FORENSIFLOW_SCRIPT_INDEX": str((workspace / "script_index.json").resolve()),
        }
    )
    started = time.time()
    timed_out = False
    try:
        process = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(workspace),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
        )
        return_code = process.returncode
        stdout = process.stdout or ""
        stderr = process.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = -1
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    duration = time.time() - started
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "stdout.txt").write_text(stdout, encoding="utf-8")
    (workspace / "stderr.txt").write_text(stderr, encoding="utf-8")
    records_path = workspace / RECORDS_FILENAME
    records_debug_path = workspace / RECORDS_DEBUG_FILENAME
    records_count = 0
    records_sample: List[Any] = []
    records_exists = records_path.exists()
    records_parse_error = ""
    if records_exists:
        try:
            data = json.loads(records_path.read_text(encoding="utf-8-sig"))
            records = data.get("records") if isinstance(data, dict) else data
            if isinstance(records, list):
                records_count = len(records)
                records_sample = records[:5]
        except Exception as exc:
            records_parse_error = str(exc)
    debug_records, debug_metadata, records_debug_parse_error = _extract_records_payload(records_debug_path)
    records_debug_exists = records_debug_path.exists()
    records_debug_count = len(debug_records) if isinstance(debug_records, list) else 0
    records_debug_sample = debug_records[:3] if isinstance(debug_records, list) else []
    records_debug_summary = _records_debug_summary(debug_records)
    diagnostics = stdout_diagnostics(stdout, records_count, records_exists, records_parse_error)
    script_diagnostics = diagnose_script_run(
        context,
        return_code=return_code,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        records_path=records_path,
        records_exists=records_exists,
        records_count=records_count,
        records_parse_error=records_parse_error,
        records_debug_path=records_debug_path,
        records_debug_exists=records_debug_exists,
        records_debug_count=records_debug_count,
        records_debug_parse_error=records_debug_parse_error,
    )
    state = {
        "ok": return_code == 0 and not timed_out and records_exists and not records_parse_error,
        "return_code": return_code,
        "timed_out": timed_out,
        "duration_seconds": round(duration, 2),
        "records_exists": records_exists,
        "records_count": records_count,
        "records_sample": records_sample,
        "records_parse_error": records_parse_error,
        "records_debug_exists": records_debug_exists,
        "records_debug_count": records_debug_count,
        "records_debug_sample": records_debug_sample,
        "records_debug_parse_error": records_debug_parse_error,
        "records_debug_summary": records_debug_summary,
        "diagnostics": diagnostics,
        "script_diagnostics": script_diagnostics,
        "script_index": script_index,
        "quality_ok": script_diagnostics.get("overall") in {"pass", "warn"},
        "completion_ready": bool(script_diagnostics.get("can_done")),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }
    context.last_run_state = state
    (workspace / "run_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def inspect_records(context: MobileAgentContext, limit: int = 20) -> Dict[str, Any]:
    workspace = script_workspace(context)
    path = workspace / RECORDS_FILENAME
    if not path.exists():
        return {"ok": False, "error": "records.json not found"}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "error": f"records parse error: {exc}"}
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return {"ok": False, "error": "records is not a list"}
    debug_records, debug_metadata, debug_error = _extract_records_payload(workspace / RECORDS_DEBUG_FILENAME)
    debug_sample = debug_records[: max(1, min(int(limit), 20))] if isinstance(debug_records, list) else []
    return {
        "ok": True,
        "records_count": len(records),
        "records_sample": records[: max(1, min(int(limit), 100))],
        "records_debug_exists": (workspace / RECORDS_DEBUG_FILENAME).exists(),
        "records_debug_count": len(debug_records) if isinstance(debug_records, list) else 0,
        "records_debug_sample": debug_sample,
        "records_debug_parse_error": debug_error,
        "records_debug_summary": _records_debug_summary(debug_records),
        "records_debug_metadata": debug_metadata,
    }


def _severity_max(*values: str) -> str:
    result = "pass"
    for value in values:
        if DIAGNOSTIC_SEVERITY_ORDER.get(value, 0) > DIAGNOSTIC_SEVERITY_ORDER.get(result, 0):
            result = value
    return result


def _issue(issue_type: str, severity: str, confidence: float, evidence: str, recommendation: str = "") -> Dict[str, Any]:
    item = {
        "type": issue_type,
        "severity": severity,
        "confidence": round(float(confidence), 2),
        "evidence": evidence,
    }
    if recommendation:
        item["recommendation"] = recommendation
    return item


def _extract_records_payload(records_path: Path) -> Tuple[Optional[List[Any]], Dict[str, Any], str]:
    if not records_path.exists():
        return None, {}, ""
    try:
        data = json.loads(records_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return None, {}, str(exc)
    metadata = data.get("metadata") if isinstance(data, dict) and isinstance(data.get("metadata"), dict) else {}
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return None, metadata, "records is not a list"
    return records, metadata, ""


def _records_debug_summary(records: Optional[List[Any]]) -> Dict[str, Any]:
    """Summarize provenance data from records_debug.json for script repair routing."""
    if not isinstance(records, list):
        return {
            "available": False,
            "records_with_debug": 0,
            "parser_counts": {},
            "block_detector_counts": {},
            "source_resource_id_counts": {},
            "sample_repair_hints": [],
        }
    parser_counts: Counter[str] = Counter()
    block_detector_counts: Counter[str] = Counter()
    resource_counts: Counter[str] = Counter()
    records_with_debug = 0
    sample_repair_hints: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        debug = record.get("_debug")
        if not isinstance(debug, dict):
            continue
        records_with_debug += 1
        parser = str(debug.get("parser") or "").strip()
        block_detector = str(debug.get("block_detector") or "").strip()
        if parser:
            parser_counts[parser] += 1
        if block_detector:
            block_detector_counts[block_detector] += 1
        source_ids = debug.get("source_resource_ids")
        if isinstance(source_ids, list):
            for rid in source_ids:
                if isinstance(rid, str) and rid.strip():
                    resource_counts[rid.strip()] += 1
        if len(sample_repair_hints) < 5:
            sample_repair_hints.append(
                {
                    "record_index": index,
                    "parser": parser,
                    "block_detector": block_detector,
                    "source_resource_ids": source_ids if isinstance(source_ids, list) else [],
                    "source_bounds": debug.get("source_bounds"),
                    "raw_texts": debug.get("raw_texts"),
                    "suggested_code_area": "parse_logic" if parser else "block_detection",
                    "suggested_functions": [value for value in (block_detector, parser) if value],
                }
            )
    return {
        "available": records_with_debug > 0,
        "records_with_debug": records_with_debug,
        "records_without_debug": max(len(records) - records_with_debug, 0),
        "parser_counts": dict(parser_counts.most_common(12)),
        "block_detector_counts": dict(block_detector_counts.most_common(12)),
        "source_resource_id_counts": dict(resource_counts.most_common(20)),
        "sample_repair_hints": sample_repair_hints,
    }


def _xml_candidate_summary(context: MobileAgentContext) -> Dict[str, Any]:
    path_text = context.workspace_context_files.get("current_page_xml") or ""
    path = Path(path_text) if path_text else workspace_context_dir(context) / "current_page.xml"
    summary: Dict[str, Any] = {
        "xml_path": str(path),
        "xml_exists": path.exists(),
        "candidate_text_count": 0,
        "candidate_resource_count": 0,
        "scrollable_count": 0,
        "text_samples": [],
        "resource_samples": [],
    }
    if not path.exists():
        return summary
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        summary["xml_parse_error"] = str(exc)
        return summary

    text_samples: List[str] = []
    resource_samples: List[str] = []
    for node in root.iter():
        rid = str(node.get("resource-id") or "")
        cls = str(node.get("class") or "")
        text = (str(node.get("text") or "") or str(node.get("content-desc") or "")).strip()
        if node.get("scrollable") == "true" or cls.endswith(("ListView", "RecyclerView", "ScrollView")):
            summary["scrollable_count"] += 1
        if rid and not rid.startswith("com.android.systemui"):
            short = rid.rsplit("/", 1)[-1] if "/" in rid else rid.rsplit(":", 1)[-1]
            if short and short not in {"back", "home", "menuitem_overflow", "entry"}:
                resource_samples.append(short)
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            continue
        if normalized.lower() in GENERIC_CONTROL_TEXTS:
            continue
        if len(normalized) < 2 and not re.search(r"\d", normalized):
            continue
        text_samples.append(normalized[:80])

    summary["candidate_text_count"] = len(text_samples)
    summary["candidate_resource_count"] = len(resource_samples)
    summary["text_samples"] = text_samples[:20]
    summary["resource_samples"] = list(dict.fromkeys(resource_samples))[:30]
    return summary


def _record_has_core_value(record: Dict[str, Any]) -> bool:
    for key in GENERIC_CORE_FIELDS:
        if _has_meaningful_value(record.get(key)):
            return True
    return False


def _semantic_record_key(record: Dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    payload = {
        key: value
        for key, value in record.items()
        if key not in SOURCE_EVIDENCE_FIELDS and _has_meaningful_value(value)
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _core_duplicate_key(record: Dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return ""
    core_value = ""
    for key in GENERIC_CORE_FIELDS:
        value = record.get(key)
        if _has_meaningful_value(value):
            core_value = str(value).strip()
            break
    if not core_value:
        return ""
    parts = [
        str(record.get("entity_type") or ""),
        str(record.get("record_type") or record.get("message_type") or record.get("type") or ""),
        str(record.get("sender") or record.get("source") or record.get("field_name") or ""),
        core_value,
    ]
    return "|".join(parts)


def _canonical_hash_key(record: Any) -> str:
    """Build a broad global deduplication hash key from normalized business content."""
    if not isinstance(record, dict):
        normalized = re.sub(r"\s+", " ", str(record)).strip().casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    core_key = _core_duplicate_key(record)
    if core_key:
        normalized = re.sub(r"\s+", " ", core_key).strip().casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    payload = {
        key: value
        for key, value in record.items()
        if key not in SOURCE_EVIDENCE_FIELDS and _has_meaningful_value(value)
    }
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _record_completeness_score(record: Any) -> int:
    if not isinstance(record, dict):
        return 0
    score = 0
    for key, value in record.items():
        if key in SOURCE_EVIDENCE_FIELDS:
            continue
        if _has_meaningful_value(value):
            score += 2
    for key in GENERIC_CORE_FIELDS:
        value = record.get(key)
        if _has_meaningful_value(value):
            score += min(len(str(value).strip()), 80)
            break
    for key in ("timestamp", "date", "time", "title", "url", "field_value", "sender"):
        if _has_meaningful_value(record.get(key)):
            score += 5
    bounds = _bounds_tuple(record.get("source_bounds") or record.get("bounds"))
    if bounds:
        _, y1, _, y2 = bounds
        if y1 <= 10 or y2 >= 2000 or y2 - y1 <= 80:
            score -= 10
    return score


def _record_core_text(record: Dict[str, Any]) -> str:
    for key in GENERIC_CORE_FIELDS:
        value = record.get(key)
        if _has_meaningful_value(value):
            return re.sub(r"\s+", " ", str(value)).strip()
    return ""


def _normalize_ui_noise_text(value: str) -> List[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    variants = {text, text.casefold()}
    # Values generated by scripts often look like "[desc] 菜单" or
    # "查看全部 [desc: 查看全部]"; judge the wrapped text as well.
    variants.add(re.sub(r"^\[desc(?:ription)?\]\s*", "", text, flags=re.IGNORECASE).strip())
    variants.update(match.strip() for match in re.findall(r"\[desc\s*:\s*([^\]]+)\]", text, flags=re.IGNORECASE))
    if "[desc:" in text:
        variants.add(re.sub(r"\s*\[desc\s*:\s*[^\]]+\]", "", text, flags=re.IGNORECASE).strip())
    return [variant for variant in variants if variant]


def _looks_like_generic_ui_noise(value: str) -> bool:
    variants = _normalize_ui_noise_text(value)
    if not variants:
        return False
    for normalized in variants:
        folded = normalized.casefold()
        if folded in GENERIC_CONTROL_TEXTS:
            return True
        if any(pattern.search(normalized) for pattern in GENERIC_UI_NOISE_PATTERNS):
            return True
    return False


def _flatten_record_values(value: Any) -> List[str]:
    if isinstance(value, dict):
        result: List[str] = []
        for child in value.values():
            result.extend(_flatten_record_values(child))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for child in value:
            result.extend(_flatten_record_values(child))
        return result
    if isinstance(value, str):
        return [value]
    return []


def _raw_component_noise_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    noisy_records = 0
    noisy_values = 0
    total_values = 0
    control_key_hits = Counter()
    examples: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        raw_components = record.get("raw_components")
        if not isinstance(raw_components, dict):
            continue
        record_noisy = False
        for key, value in raw_components.items():
            key_text = str(key or "").rsplit(".", 1)[-1].casefold()
            values = _flatten_record_values(value)
            total_values += len(values)
            key_is_control = key_text in CONTROL_COMPONENT_KEYS or key_text.endswith("button")
            if key_is_control and values:
                control_key_hits[key_text] += len(values)
            for item in values:
                item_is_noise = _looks_like_generic_ui_noise(item)
                if key_is_control or item_is_noise:
                    noisy_values += 1
                    record_noisy = True
                    if len(examples) < 5:
                        examples.append({"record_index": index, "component": key, "value": item})
        if record_noisy:
            noisy_records += 1
    return {
        "noisy_records": noisy_records,
        "noisy_values": noisy_values,
        "total_values": total_values,
        "control_key_hits": dict(control_key_hits.most_common(8)),
        "examples": examples,
    }


def global_hash_deduplicate_payload(data: Any) -> Tuple[Any, Dict[str, Any]]:
    """Deduplicate records globally using canonical hashes, keeping the richest representative."""
    records = data.get("records") if isinstance(data, dict) else data
    if not isinstance(records, list):
        return data, {"enabled": False, "reason": "records is not a list"}

    first_order: List[str] = []
    best_by_hash: Dict[str, Any] = {}
    best_score_by_hash: Dict[str, int] = {}
    duplicate_examples: List[Dict[str, Any]] = []
    for index, record in enumerate(records):
        key = _canonical_hash_key(record)
        score = _record_completeness_score(record)
        if key in best_by_hash:
            if len(duplicate_examples) < 5:
                duplicate_examples.append({"index": index, "hash": key, "record": record})
            if score > best_score_by_hash.get(key, -10**9):
                best_by_hash[key] = record
                best_score_by_hash[key] = score
        else:
            first_order.append(key)
            best_by_hash[key] = record
            best_score_by_hash[key] = score

    deduped = [best_by_hash[key] for key in first_order]

    removed_count = len(records) - len(deduped)
    postprocess = {
        "enabled": True,
        "strategy": "global_canonical_hash",
        "representative": "highest_completeness_score",
        "original_count": len(records),
        "deduped_count": len(deduped),
        "removed_count": removed_count,
        "duplicate_examples": duplicate_examples,
    }
    if removed_count <= 0:
        return data, postprocess

    if isinstance(data, dict):
        next_data = dict(data)
        next_data["records"] = deduped
        metadata = dict(next_data.get("metadata") or {})
        metadata["pre_global_hash_count"] = len(records)
        metadata["global_hash_unique_count"] = len(deduped)
        metadata["global_hash_removed_count"] = removed_count
        metadata["global_hash_strategy"] = "global_canonical_hash"
        metadata["global_hash_representative"] = "highest_completeness_score"
        if isinstance(metadata.get("unique_count"), int):
            metadata["script_unique_count_before_global_hash"] = metadata.get("unique_count")
        if isinstance(metadata.get("duplicate_count"), int):
            metadata["script_duplicate_count_before_global_hash"] = metadata.get("duplicate_count")
            metadata["duplicate_count"] = int(metadata.get("duplicate_count") or 0) + removed_count
        metadata["unique_count"] = len(deduped)
        metadata["records_count"] = len(deduped)
        next_data["metadata"] = metadata
        return next_data, postprocess
    return deduped, postprocess


def _global_hash_duplicate_issue(records: List[Any]) -> Optional[Dict[str, Any]]:
    if len(records) < 2:
        return None
    hashes = [_canonical_hash_key(record) for record in records]
    counts = Counter(hashes)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    if duplicate_count <= 0:
        return None
    ratio = duplicate_count / max(len(records), 1)
    if ratio > 0.25:
        severity = "fail"
    elif ratio > 0.08:
        severity = "suspect"
    else:
        severity = "warn"
    examples: List[Any] = []
    duplicate_hashes = {key for key, count in counts.items() if count > 1}
    for record, key in zip(records, hashes):
        if key in duplicate_hashes:
            examples.append(record)
            if len(examples) >= 3:
                break
    issue = _issue(
        "global_hash_duplicates",
        severity,
        0.82,
        f"{duplicate_count}/{len(records)} records duplicate under global canonical hash (ratio={ratio:.2f})",
        "Patch the generated script to perform global canonical hash dedup before writing records.json; do not rely on runtime post-processing.",
    )
    issue["examples"] = examples
    return issue


def _bounds_tuple(value: Any) -> Optional[Tuple[int, int, int, int]]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return tuple(int(v) for v in value)  # type: ignore[return-value]
        except Exception:
            return None
    if isinstance(value, str):
        match = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value)
        if match:
            return tuple(int(v) for v in match.groups())  # type: ignore[return-value]
    return None


def _records_quality_issues(records: List[Any], metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    dict_records = [record for record in records if isinstance(record, dict)]
    total = len(records)
    dict_total = len(dict_records)
    if total and dict_total < total:
        issues.append(
            _issue(
                "non_object_records",
                "warn" if dict_total / max(total, 1) >= 0.8 else "suspect",
                0.72,
                f"{total - dict_total}/{total} records are not JSON objects",
                "Prefer list[dict] records with stable field names.",
            )
        )
    if not dict_records:
        return issues

    ui_noise_records = [
        record
        for record in dict_records
        if _looks_like_generic_ui_noise(_record_core_text(record))
    ]
    if len(ui_noise_records) >= 3:
        ratio = len(ui_noise_records) / max(dict_total, 1)
        if ratio > 0.35:
            severity = "suspect"
        elif ratio > 0.15:
            severity = "warn"
        else:
            severity = "pass"
        if severity != "pass":
            issues.append(
                _issue(
                    "generic_ui_text_noise",
                    severity,
                    0.62,
                    f"{len(ui_noise_records)}/{dict_total} records look like generic UI controls or navigation labels",
                    "Tighten generated-script field filtering so records represent target data, not buttons, tabs, or media/control labels.",
                )
            )
            issues[-1]["examples"] = [_record_core_text(record) for record in ui_noise_records[:5]]

    raw_noise = _raw_component_noise_summary(dict_records)
    raw_noisy_records = int(raw_noise.get("noisy_records") or 0)
    raw_total_values = int(raw_noise.get("total_values") or 0)
    raw_noisy_values = int(raw_noise.get("noisy_values") or 0)
    if raw_noisy_records and raw_total_values:
        record_ratio = raw_noisy_records / max(dict_total, 1)
        value_ratio = raw_noisy_values / max(raw_total_values, 1)
        if record_ratio > 0.45 or value_ratio > 0.35:
            severity = "suspect"
        elif record_ratio > 0.2 or value_ratio > 0.15:
            severity = "warn"
        else:
            severity = "pass"
        if severity != "pass":
            issue = _issue(
                "raw_components_ui_control_noise",
                severity,
                0.82,
                f"{raw_noisy_records}/{dict_total} records and {raw_noisy_values}/{raw_total_values} raw component values look like controls",
                "Patch collect_raw_components: skip Button/ImageButton/toolbar/tab/menu/edit/share/search controls by class/resource-id and normalize [desc]/[desc: ...] text before filtering.",
            )
            issue["control_key_hits"] = raw_noise.get("control_key_hits") or {}
            issue["examples"] = raw_noise.get("examples") or []
            issues.append(issue)

    debug_field_counts = Counter(
        key
        for record in dict_records
        for key in SOURCE_EVIDENCE_FIELDS
        if key in record
    )
    if debug_field_counts:
        examples = dict(debug_field_counts.most_common(8))
        issues.append(
            _issue(
                "debug_fields_in_output",
                "warn",
                0.74,
                f"final records still contain screen/debug fields: {examples}",
                "Use bounds/signatures internally, but remove source_bounds/bounds/raw_node_signature/dedup_key/page/row indexes before writing records.json.",
            )
        )

    verbose_record_counts = Counter(
        key
        for record in dict_records
        for key in VERBOSE_RECORD_FIELDS
        if key in record
    )
    verbose_metadata_keys = sorted(key for key in VERBOSE_METADATA_FIELDS if key in metadata)
    if verbose_record_counts or verbose_metadata_keys:
        evidence_parts: List[str] = []
        if verbose_record_counts:
            evidence_parts.append(f"record fields: {dict(verbose_record_counts.most_common(8))}")
        if verbose_metadata_keys:
            evidence_parts.append(f"metadata fields: {verbose_metadata_keys}")
        issues.append(
            _issue(
                "verbose_non_evidence_output",
                "warn",
                0.76,
                "; ".join(evidence_parts),
                "Remove breadcrumbs/page path and narrative metadata by default; keep only evidence fields and minimal aggregate stats.",
            )
        )

    empty_core = sum(1 for record in dict_records if not _record_has_core_value(record))
    empty_core_ratio = empty_core / dict_total
    if empty_core_ratio > 0.6:
        severity = "fail"
    elif empty_core_ratio > 0.35:
        severity = "suspect"
    elif empty_core_ratio > 0.15:
        severity = "warn"
    else:
        severity = "pass"
    if severity != "pass":
        issues.append(
            _issue(
                "empty_core_fields",
                severity,
                0.75,
                f"{empty_core}/{dict_total} records have no common core field ({', '.join(GENERIC_CORE_FIELDS[:6])}, ...)",
                "Check parser field extraction and record filtering.",
            )
        )

    for field in GENERIC_OPTIONAL_QUALITY_FIELDS:
        present = [record for record in dict_records if field in record]
        if len(present) < 5:
            continue
        empty = sum(1 for record in present if not _has_meaningful_value(record.get(field)))
        ratio = empty / len(present)
        if ratio > 0.6:
            severity = "suspect"
        elif ratio > 0.35:
            severity = "warn"
        elif ratio > 0.15:
            severity = "warn"
        else:
            continue
        issues.append(
            _issue(
                "field_completeness",
                severity,
                0.62,
                f"field '{field}' is empty in {empty}/{len(present)} records where the field is present",
                "This may be acceptable for optional fields; patch only if the task depends on this field.",
            )
        )

    sender_values = [
        str(record.get("sender") or record.get("source") or "").strip()
        for record in dict_records
        if _has_meaningful_value(record.get("sender") or record.get("source"))
    ]
    if len(sender_values) >= 20:
        sender_counts = Counter(sender_values)
        if len(sender_counts) == 1:
            issues.append(
                _issue(
                    "single_sender_detected",
                    "warn",
                    0.58,
                    f"all {len(sender_values)} records with sender/source use the same value: {next(iter(sender_counts))!r}",
                    "This may be valid for one-sided data, but in chat/task timelines it often means sender inference used row bounds instead of message bubble bounds.",
                )
            )

    semantic_keys = [_semantic_record_key(record) for record in dict_records]
    nonempty_keys = [key for key in semantic_keys if key and key != "{}"]
    unique_count = len(set(nonempty_keys))
    duplicate_ratio = 1 - (unique_count / max(len(nonempty_keys), 1))
    if len(nonempty_keys) >= 5:
        if duplicate_ratio > 0.7:
            severity = "suspect"
        elif duplicate_ratio > 0.4:
            severity = "warn"
        else:
            severity = "pass"
        if severity != "pass":
            issues.append(
                _issue(
                    "semantic_duplicates",
                    severity,
                    0.68,
                    f"semantic duplicate ratio is {duplicate_ratio:.2f} ({len(nonempty_keys) - unique_count}/{len(nonempty_keys)} duplicate-like records)",
                    "Review dedup keys and whether source/page fields are leaking into business identity.",
                )
            )

    core_keys = [_core_duplicate_key(record) for record in dict_records]
    core_keys = [key for key in core_keys if key]
    if len(core_keys) >= 5:
        counts = Counter(core_keys)
        duplicate_like = sum(count - 1 for count in counts.values() if count > 1)
        ratio = duplicate_like / max(len(core_keys), 1)
        if ratio > 0.35:
            severity = "suspect"
        elif ratio > 0.12:
            severity = "warn"
        else:
            severity = "pass"
        if severity != "pass":
            examples = [key.split("|")[-1][:60] for key, count in counts.items() if count > 1][:3]
            issues.append(
                _issue(
                    "core_value_duplicates",
                    severity,
                    0.58,
                    f"{duplicate_like}/{len(core_keys)} records share the same generic core identity; examples={examples}",
                    "This can be normal for repeated real-world values, but also catches partial+complete duplicate records.",
                )
            )

    raw_count = metadata.get("raw_count")
    unique_meta = metadata.get("unique_count") or metadata.get("records_count")
    if isinstance(raw_count, int) and isinstance(unique_meta, int) and raw_count >= 5 and raw_count >= unique_meta:
        raw_duplicate_ratio = (raw_count - unique_meta) / max(raw_count, 1)
        if raw_duplicate_ratio > 0.75:
            severity = "suspect"
        elif raw_duplicate_ratio > 0.5:
            severity = "warn"
        else:
            severity = "pass"
        if severity != "pass":
            issues.append(
                _issue(
                    "high_raw_duplicate_ratio",
                    severity,
                    0.6,
                    f"metadata raw_count={raw_count}, unique_count={unique_meta}, duplicate ratio={raw_duplicate_ratio:.2f}",
                    "High overlap can be normal for conservative scrolling; verify stop condition and dedup logic.",
                )
            )

    edge_like = 0
    edge_with_missing = 0
    for record in dict_records:
        bounds = _bounds_tuple(record.get("source_bounds") or record.get("bounds"))
        if not bounds:
            continue
        _, y1, _, y2 = bounds
        if y1 <= 10 or y2 >= 0 and y2 - y1 <= 80 or y2 >= 2000:
            edge_like += 1
            if not _record_has_core_value(record) or any(
                field in record and not _has_meaningful_value(record.get(field))
                for field in ("timestamp", "date", "title", "field_value")
            ):
                edge_with_missing += 1
    if edge_with_missing >= 5 and edge_like:
        ratio = edge_with_missing / max(edge_like, 1)
        issues.append(
            _issue(
                "edge_or_partial_records",
                "warn" if ratio < 0.5 else "suspect",
                0.55,
                f"{edge_with_missing} edge-position records also have missing common fields",
                "Some visible rows may be clipped by the viewport; consider filtering or replacing partial records.",
            )
        )

    return issues


def diagnose_script_run(
    context: MobileAgentContext,
    *,
    return_code: int,
    timed_out: bool,
    stdout: str,
    stderr: str,
    records_path: Path,
    records_exists: bool,
    records_count: int,
    records_parse_error: str,
    records_debug_path: Optional[Path] = None,
    records_debug_exists: bool = False,
    records_debug_count: int = 0,
    records_debug_parse_error: str = "",
) -> Dict[str, Any]:
    """Run broad, non-task-specific diagnostics for a generated extraction script."""
    records, metadata, payload_error = _extract_records_payload(records_path)
    if records_parse_error and not payload_error:
        payload_error = records_parse_error
    debug_records = None
    if records_debug_path is not None and records_debug_exists and not records_debug_parse_error:
        debug_records, _, debug_payload_error = _extract_records_payload(records_debug_path)
        if debug_payload_error and not records_debug_parse_error:
            records_debug_parse_error = debug_payload_error
    xml_summary = _xml_candidate_summary(context)
    visible_values = [int(m.group(1)) for m in re.finditer(r"visible=(\d+)", stdout or "")]
    new_values = [int(m.group(1)) for m in re.finditer(r"new=(\d+)", stdout or "")]
    issues: List[Dict[str, Any]] = []

    if timed_out:
        issues.append(_issue("script_timeout", "fail", 0.98, "script execution timed out", "Patch timeout/loop/stop conditions."))
    if return_code != 0:
        issues.append(_issue("script_return_code", "fail", 0.98, f"script returned non-zero code {return_code}", "Inspect stderr and patch the script."))
    if not records_exists:
        issues.append(_issue("records_missing", "fail", 0.98, "records.json was not created", "Write records.json to FORENSIFLOW_AGENT_WORKSPACE."))
    if payload_error:
        issues.append(_issue("records_parse_error", "fail", 0.95, payload_error, "Ensure records.json is valid JSON containing a list or {'records': list}."))

    combined_log = "\n".join([stdout or "", stderr or ""])
    xml_read_failed = bool(
        re.search(r"(Error parsing XML|No such file or directory|FileNotFoundError|XML parse error)", combined_log, re.IGNORECASE)
        and re.search(r"(current_page\.xml|FORENSIFLOW_CURRENT_UI_XML|XML Path|\.xml)", combined_log, re.IGNORECASE)
    )
    if xml_read_failed:
        issues.append(
            _issue(
                "workspace_xml_read_failed",
                "warn" if records_count > 0 else "suspect",
                0.78,
                "script log indicates the saved workspace XML could not be read or parsed",
                "Use absolute FORENSIFLOW_CURRENT_UI_XML, avoid cwd-relative paths, and patch XML parsing if fallback/live extraction was required.",
            )
        )

    candidate_count = int(xml_summary.get("candidate_text_count") or 0) + int(xml_summary.get("candidate_resource_count") or 0)
    if records_exists and not payload_error and records_count <= 0:
        if candidate_count >= 8:
            issues.append(
                _issue(
                    "parser_or_filter_failed",
                    "fail",
                    0.86,
                    f"records_count=0 while current page XML has {candidate_count} candidate data signals",
                    "Inspect generated_script.py parser functions and compare their selectors against current_page.xml.",
                )
            )
        else:
            issues.append(
                _issue(
                    "records_empty",
                    "suspect",
                    0.55,
                    "records_count=0 and the saved XML has few candidate data signals",
                    "Confirm whether the target page is empty or navigation/scroll position is wrong.",
                )
            )

    if records_exists and records_count > 0:
        if not records_debug_exists:
            issues.append(
                _issue(
                    "records_debug_missing",
                    "warn",
                    0.82,
                    f"{RECORDS_DEBUG_FILENAME} was not created alongside {RECORDS_FILENAME}",
                    "Patch output logic to write clean records.json plus records_debug.json with per-record _debug provenance.",
                )
            )
        elif records_debug_parse_error:
            issues.append(
                _issue(
                    "records_debug_parse_error",
                    "warn",
                    0.78,
                    records_debug_parse_error,
                    "Ensure records_debug.json is valid JSON containing the same records plus _debug provenance.",
                )
            )
        elif records_debug_count < records_count:
            issues.append(
                _issue(
                    "records_debug_incomplete",
                    "warn",
                    0.7,
                    f"{RECORDS_DEBUG_FILENAME} has {records_debug_count} records but {RECORDS_FILENAME} has {records_count}",
                    "Write one debug record for every final record so repair can map bad output back to parser functions.",
                )
            )

    if visible_values and max(visible_values) == 0 and candidate_count >= 8:
        issues.append(
            _issue(
                "visible_zero_with_xml_candidates",
                "fail" if records_count <= 0 else "suspect",
                0.84,
                f"stdout reports visible=0 but current page XML has {candidate_count} candidate data signals",
                "Parser selectors likely do not match the UI XML.",
            )
        )
    if visible_values and records_count > 0 and max(visible_values) > records_count * 3:
        issues.append(
            _issue(
                "visible_far_exceeds_records",
                "warn",
                0.58,
                f"max visible={max(visible_values)} is much larger than records_count={records_count}",
                "This may be normal with heavy deduplication; review parser/filters if output looks sparse.",
            )
        )
    if visible_values and new_values and max(visible_values) > max(new_values) and records_count > 0:
        issues.append(
            _issue(
                "new_less_than_visible",
                "warn",
                0.45,
                f"max visible={max(visible_values)}, max new={max(new_values)}",
                "Often normal due to overlap/dedup; only patch if records look incomplete.",
            )
        )

    if records:
        global_duplicate_issue = _global_hash_duplicate_issue(records)
        if global_duplicate_issue:
            issues.append(global_duplicate_issue)
        issues.extend(_records_quality_issues(records, metadata))

    overall = "pass"
    for item in issues:
        overall = _severity_max(overall, str(item.get("severity") or "pass"))
    confidence_values = [float(item.get("confidence") or 0) for item in issues]
    confidence = max(confidence_values) if confidence_values else 0.8
    if overall == "pass":
        recommendation = "Result passed broad script diagnostics."
    elif overall == "warn":
        recommendation = "Result is probably usable, but mention or review warnings if they affect the task."
    elif overall == "suspect":
        recommendation = "Prefer patching or inspecting records before done; can still proceed with explicit risk if the output is sufficient."
    else:
        recommendation = "Do not call done(success=true); patch the script or recover navigation and rerun."

    return {
        "overall": overall,
        "confidence": round(confidence, 2),
        "can_done": overall != "fail",
        "can_done_with_risk": overall != "fail",
        "should_patch": overall in {"suspect", "fail"},
        "recommendation": recommendation,
        "issues": issues[:20],
        "summary": {
            "records_count": records_count,
            "xml_candidate_text_count": xml_summary.get("candidate_text_count", 0),
            "xml_candidate_resource_count": xml_summary.get("candidate_resource_count", 0),
            "visible_values_sample": visible_values[:10],
            "new_values_sample": new_values[:10],
            "metadata": metadata,
            "xml_text_samples": xml_summary.get("text_samples", [])[:8],
            "xml_resource_samples": xml_summary.get("resource_samples", [])[:12],
            "records_debug": _records_debug_summary(debug_records),
        },
    }


def stdout_diagnostics(stdout: str, records_count: int, records_exists: bool, parse_error: str) -> Dict[str, Any]:
    diagnostics: Dict[str, Any] = {}
    if not records_exists:
        diagnostics["records_missing"] = True
    if parse_error:
        diagnostics["records_parse_error"] = parse_error
    if records_exists and records_count <= 0:
        diagnostics["records_empty"] = True
    visible_values = [int(m.group(1)) for m in re.finditer(r"visible=(\d+)", stdout)]
    new_values = [int(m.group(1)) for m in re.finditer(r"new=(\d+)", stdout)]
    if records_exists and records_count <= 0 and visible_values and max(visible_values) == 0:
        diagnostics["no_visible_records"] = True
    if visible_values and max(visible_values) > records_count:
        diagnostics["visible_exceeds_records"] = True
    if visible_values and new_values and max(visible_values) > max(new_values):
        diagnostics["new_less_than_visible"] = True
    return diagnostics
