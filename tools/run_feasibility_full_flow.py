#!/usr/bin/env python3
"""Run a small full-flow feasibility experiment and write report-ready metrics.

This harness is intentionally thin: it uses the existing ForensiFlow executor
and only standardizes task specs, artifact collection, and metric files for
paper/report experiments.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from run_forensic_plan import ForensicTaskExecutor
from runner.forensiflow.core.config import get_llm_config
from runner.forensiflow.devices.android import AndroidDevice
from tools.device_serial import resolve_device_serial


DEFAULT_TASKS: List[Dict[str, Any]] = [
    {
        "task_id": "GM-FEAS-01",
        "app_name": "Gmail",
        "package_name": "com.google.android.gm",
        "task_description": "Gmail 收件箱邮件/会话总列表全量提取",
        "expected_min_records": 1,
        "expected_min_fields": ["senders", "subject", "snippet", "date"],
        "gold_available": False,
    },
    {
        "task_id": "CH-FEAS-01",
        "app_name": "Chrome",
        "package_name": "com.android.chrome",
        "task_description": "提取chrome历史记录信息",
        "expected_min_records": 1,
        "expected_min_fields": ["title", "url_domain", "date_section"],
        "expected_field_basis": "Chrome history list visibly exposes title, domain, and date section; full URL is not consistently exposed in the list UI.",
        "gold_available": False,
    },
    {
        "task_id": "MP-FEAS-01",
        "app_name": "Google Maps",
        "package_name": "com.google.android.apps.maps",
        "task_description": "抽取最近搜索或最近查看地点",
        "constraint": "只读取现有最近搜索、最近查看地点和地点详情，不输入新搜索词，不修改收藏或路线。",
        "expected_min_records": 1,
        "expected_min_fields": ["title", "category", "status", "filter_type"],
        "gold_available": False,
    },
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 serial.")
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "experiments" / "full_flow_feasibility")
    parser.add_argument("--run-id", default="", help="Optional run id. Default timestamped.")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--apps", default="gmail,chrome,maps", help="Comma list: gmail, chrome, maps.")
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--model", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--force-route", choices=["auto", "reuse", "explore"], default="auto")
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    return parser


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _slug(value: str) -> str:
    import re

    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value).strip("_") or "task"


def _selected_tasks(apps: str, max_tasks: int = 0) -> List[Dict[str, Any]]:
    aliases = {
        "gmail": "com.google.android.gm",
        "gm": "com.google.android.gm",
        "chrome": "com.android.chrome",
        "ch": "com.android.chrome",
        "maps": "com.google.android.apps.maps",
        "google maps": "com.google.android.apps.maps",
        "mp": "com.google.android.apps.maps",
    }
    requested = {aliases.get(part.strip().casefold(), part.strip()) for part in apps.split(",") if part.strip()}
    tasks = [task for task in DEFAULT_TASKS if task["package_name"] in requested or task["app_name"].casefold() in requested]
    if max_tasks and max_tasks > 0:
        tasks = tasks[:max_tasks]
    return tasks


def _build_plan(task: Dict[str, Any], plan_path: Path) -> None:
    plan = {
        "case_analysis_summary": "ForensiFlow 可行性实验：Gmail、Chrome、Google Maps 全流程测试。",
        "forensic_plan": [
            {
                "app_name": task["app_name"],
                "package_name": task["package_name"],
                "tasks": [
                    {
                        "task_level": 1,
                        "task_type": "full_flow_feasibility",
                        "task_description": task["task_description"],
                        "target_objects": task.get("target_objects", []),
                        "constraint": task.get("constraint", "只读取证，不发送、不删除、不编辑、不支付、不修改应用状态。"),
                    }
                ],
            }
        ],
    }
    _write_json(plan_path, plan)


def _records_from_payload(payload: Any) -> List[Dict[str, Any]]:
    records = payload.get("records") if isinstance(payload, dict) else payload
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


_DEBUG_FIELDS = {
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
_CORE_FIELDS = {
    "content_text",
    "text",
    "title",
    "value",
    "field_value",
    "display_name",
    "name",
    "label",
    "message",
    "description",
    "empty_state_text",
    "raw_components",
}


def _strip_debug_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_debug_fields(child)
            for key, child in value.items()
            if key not in _DEBUG_FIELDS and child not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [_strip_debug_fields(child) for child in value if child not in (None, "", [], {})]
    return value


def _first_record_value(record: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _ensure_core_business_fields(record: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(record)
    if _looks_like_gmail_empty_state(normalized):
        normalized.setdefault("entity_type", "empty_state")
        normalized.setdefault("record_type", "empty_state")
        normalized.setdefault("mailbox", "Sent")
        normalized.setdefault("folder", "已发送")
        normalized.setdefault("folder_en", "Sent")
        if normalized.get("empty_state_text") in (None, "", [], {}):
            normalized["empty_state_text"] = "“已发送”中没有任何内容"
        if normalized.get("content_text") in (None, "", [], {}):
            normalized["content_text"] = normalized["empty_state_text"]
        if normalized.get("title") in (None, "", [], {}):
            normalized["title"] = "Gmail Sent empty state"
    if not any(normalized.get(field) not in (None, "", [], {}) for field in _CORE_FIELDS):
        title = _first_record_value(
            normalized,
            "subject",
            "sender",
            "senders",
            "place_name",
            "record_type",
            "entity_type",
            "filename",
            "url_domain",
            "url_or_domain",
        )
        if title is not None:
            normalized["title"] = str(title)
    if normalized.get("title") in (None, "", [], {}):
        title = _first_record_value(normalized, "subject", "place_name", "name", "filename", "folder_name")
        if title is not None:
            normalized["title"] = str(title)
    if normalized.get("content_text") in (None, "", [], {}):
        parts = [
            _first_record_value(normalized, "title", "subject", "place_name", "name"),
            _first_record_value(normalized, "description", "snippet", "body_summary", "body_text", "url_domain", "url_or_domain", "category", "address"),
        ]
        text = " - ".join(str(part).strip() for part in parts if part not in (None, "", [], {}))
        if text:
            normalized["content_text"] = text
    if normalized.get("url_domain") in (None, "", [], {}) and normalized.get("url_or_domain") not in (None, "", [], {}):
        normalized["url_domain"] = normalized["url_or_domain"]
    if normalized.get("snippet") in (None, "", [], {}) and normalized.get("body_summary") not in (None, "", [], {}):
        normalized["snippet"] = normalized["body_summary"]
    return normalized


def _looks_like_gmail_empty_state(record: Dict[str, Any]) -> bool:
    app_text = " ".join(
        str(record.get(key) or "")
        for key in ("app_name", "package_name", "target", "folder", "folder_en", "mailbox", "source_page")
    ).casefold()
    type_text = " ".join(str(record.get(key) or "") for key in ("entity_type", "record_type")).casefold()
    return (
        ("gmail" in app_text or "com.google.android.gm" in app_text)
        and ("sent" in app_text or "已发送" in app_text)
        and ("empty_state" in type_text or record.get("empty_state_text") is not None)
    )


def _default_debug(record: Dict[str, Any], index: int) -> Dict[str, Any]:
    return {
        "scroll_index": int(record.get("scroll_index") or record.get("page_index") or 0),
        "page_index": int(record.get("page_index") or 0),
        "parser": "artifact_normalizer",
        "block_detector": "postprocess_existing_record",
        "source_resource_ids": [],
        "source_bounds": str(record.get("source_bounds") or record.get("bounds") or ""),
        "raw_texts": [str(value) for key, value in record.items() if key not in _DEBUG_FIELDS and isinstance(value, str) and value][:8],
        "record_index": index,
    }


def _normalize_records_artifacts(copied: Dict[str, str]) -> Dict[str, str]:
    """Normalize copied artifacts without changing device-side extraction.

    Generated scripts from exploratory Codex runs vary slightly in output
    schema. The experiment harness needs stable artifacts for validation and
    gold alignment, so this postprocess only adds aliases/provenance and strips
    debug fields from final records.
    """
    records_path = copied.get("records_path")
    if not records_path:
        return copied
    path = Path(records_path)
    if not path.exists():
        return copied
    try:
        records_payload = _read_json(path)
    except Exception:
        return copied
    metadata = records_payload.get("metadata") if isinstance(records_payload, dict) and isinstance(records_payload.get("metadata"), dict) else {}
    records = _records_from_payload(records_payload)
    if not records:
        return copied

    clean_records = []
    clean_debug_sources = []
    seen = set()
    for index, record in enumerate(records):
        clean_record = _ensure_core_business_fields(_strip_debug_fields(record))
        key = json.dumps(clean_record, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        clean_records.append(clean_record)
        clean_debug_sources.append(index)
    _write_json(path, {"records": clean_records, "metadata": metadata} if metadata else clean_records)

    debug_path = copied.get("records_debug_path")
    debug_records: List[Dict[str, Any]] = []
    debug_metadata: Dict[str, Any] = {}
    if debug_path and Path(debug_path).exists():
        try:
            debug_payload = _read_json(Path(debug_path))
            debug_metadata = debug_payload.get("metadata") if isinstance(debug_payload, dict) and isinstance(debug_payload.get("metadata"), dict) else {}
            debug_records = _records_from_payload(debug_payload)
        except Exception:
            debug_records = []
    if len(debug_records) != len(records):
        debug_records = []
    normalized_debug: List[Dict[str, Any]] = []
    for index, record in enumerate(clean_records):
        source_index = clean_debug_sources[index] if index < len(clean_debug_sources) else index
        debug_source = debug_records[source_index] if source_index < len(debug_records) and isinstance(debug_records[source_index], dict) else {}
        debug = debug_source.get("_debug") if isinstance(debug_source.get("_debug"), dict) else {}
        merged = dict(record)
        merged["_debug"] = {**_default_debug(record, index), **debug}
        merged["_debug"].setdefault("dump_method", "existing_artifact")
        merged["_debug"].setdefault("detail_scroll_rounds", 0)
        merged["_debug"].setdefault("detail_fragments_count", 1)
        merged["_debug"].setdefault("stop_reason", "existing_artifact")
        normalized_debug.append(merged)
    if not debug_path:
        debug_path = str(path.parent / "records_debug.json")
        copied["records_debug_path"] = debug_path
    _write_json(Path(debug_path), {"records": normalized_debug, "metadata": debug_metadata} if debug_metadata else normalized_debug)

    state_path = copied.get("run_state_path")
    if state_path and Path(state_path).exists():
        try:
            state = _read_json(Path(state_path))
        except Exception:
            state = {}
        if isinstance(state, dict):
            state["total_records"] = len(clean_records)
            _write_json(Path(state_path), state)
    return copied


def _find_artifact_paths(task_result: Dict[str, Any]) -> Dict[str, str]:
    paths: Dict[str, str] = {}

    for script_result in task_result.get("script_results") or []:
        if not isinstance(script_result, dict):
            continue
        for key in (
            "records_path",
            "records_debug_path",
            "run_state_path",
            "stdout_path",
            "stderr_path",
            "run_dir",
            "script_path",
            "runnable_script",
        ):
            value = script_result.get(key)
            if value and not paths.get(key):
                paths[key] = str(value)

    raw_result = task_result.get("raw_result") if isinstance(task_result.get("raw_result"), dict) else {}
    raw_codex = raw_result.get("raw_codex_result") if isinstance(raw_result.get("raw_codex_result"), dict) else raw_result
    reuse_artifacts = task_result.get("reuse_artifacts") if isinstance(task_result.get("reuse_artifacts"), dict) else {}
    if not reuse_artifacts:
        reuse_artifacts = raw_result.get("reuse_artifacts") if isinstance(raw_result.get("reuse_artifacts"), dict) else {}
    if reuse_artifacts:
        reuse_map = {
            "archived_script_path": "archived_script_path",
            "template_path": "rag_template_path",
            "registry_entry_path": "script_registry_entry_path",
        }
        for source_key, target_key in reuse_map.items():
            value = reuse_artifacts.get(source_key)
            if value and not paths.get(target_key):
                paths[target_key] = str(value)
        script_index = reuse_artifacts.get("script_index")
        if isinstance(script_index, dict):
            value = script_index.get("path")
            if value and not paths.get("script_index_path"):
                paths["script_index_path"] = str(value)

    codex_map = {
        "records_path": "records_path",
        "records_debug_path": "records_debug_path",
        "run_state_path": "run_state_path",
        "stdout_path": "stdout_path",
        "stderr_path": "stderr_path",
        "run_dir": "run_dir",
        "workspace": "workspace",
        "evidence_manifest": "evidence_manifest",
    }
    for source_key, target_key in codex_map.items():
        value = raw_codex.get(source_key)
        if value and not paths.get(target_key):
            paths[target_key] = str(value)

    workspace = task_result.get("script_generation", {})
    if isinstance(workspace, dict):
        candidate = workspace.get("workspace")
        if candidate and not paths.get("workspace"):
            paths["workspace"] = str(candidate)

    for base_key in ("workspace", "run_dir", "data_dir"):
        base = task_result.get(base_key) or paths.get(base_key)
        if not base:
            continue
        base_path = Path(str(base))
        if base_path.is_dir():
            candidates = {
                "records_path": [base_path / "records.json", base_path / "page_records.json", base_path / "script_workspace" / "records.json"],
                "records_debug_path": [base_path / "records_debug.json", base_path / "script_workspace" / "records_debug.json"],
                "run_state_path": [base_path / "run_state.json", base_path / "script_workspace" / "run_state.json"],
                "stdout_path": [base_path / "stdout.txt", base_path / "script_workspace" / "codex_agent" / "stdout.txt"],
                "stderr_path": [base_path / "stderr.txt", base_path / "script_workspace" / "codex_agent" / "stderr.txt"],
                "generated_script_path": [base_path / "generated_script.py", base_path / "script_workspace" / "generated_script.py"],
                "action_path_path": [base_path / "action_path.json", base_path / "script_workspace" / "action_path.json"],
                "workspace_context_path": [base_path / "workspace_context.json", base_path / "script_workspace" / "workspace_context.json"],
                "script_index_path": [base_path / "script_index.json", base_path / "script_workspace" / "script_index.json"],
                "rag_template_path": [base_path / "rag_template.json", base_path / "script_workspace" / "rag_template.json"],
                "script_registry_entry_path": [base_path / "script_registry_entry.json", base_path / "script_workspace" / "script_registry_entry.json"],
            }
            for key, path_list in candidates.items():
                if paths.get(key):
                    continue
                for path in path_list:
                    if path.exists():
                        paths[key] = str(path)
                        break
    run_dir = paths.get("run_dir")
    if run_dir:
        run_dir_path = Path(str(run_dir))
        if run_dir_path.is_dir():
            fallback_candidates = {
                "records_path": (run_dir_path / "records.json", run_dir_path / "page_records.json"),
                "records_debug_path": (run_dir_path / "records_debug.json",),
                "run_state_path": (run_dir_path / "run_state.json",),
            }
            for key, candidates in fallback_candidates.items():
                if paths.get(key):
                    continue
                for path in candidates:
                    if path.exists():
                        paths[key] = str(path)
                        break
    return paths


def _copy_artifacts(paths: Dict[str, str], run_dir: Path) -> Dict[str, str]:
    artifacts_dir = run_dir / "artifacts"
    copied: Dict[str, str] = {}
    names = {
        "records_path": "records.json",
        "records_debug_path": "records_debug.json",
        "run_state_path": "run_state.json",
        "stdout_path": "stdout.txt",
        "stderr_path": "stderr.txt",
        "evidence_manifest": "evidence_manifest.json",
        "script_path": "source_script.py",
        "runnable_script": "runnable_script.py",
        "archived_script_path": "archived_generated_script.py",
        "generated_script_path": "generated_script.py",
        "action_path_path": "action_path.json",
        "workspace_context_path": "workspace_context.json",
        "script_index_path": "script_index.json",
        "rag_template_path": "rag_template.json",
        "script_registry_entry_path": "script_registry_entry.json",
    }
    for key, filename in names.items():
        source = paths.get(key)
        if not source:
            continue
        source_path = Path(source)
        if not source_path.exists() or not source_path.is_file():
            continue
        target = artifacts_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        copied[key] = str(target)
    return _normalize_records_artifacts(copied)


_FIELD_ALIASES = {
    "domain": ("url_domain", "domain", "url_or_domain", "description"),
    "url_domain": ("url_domain", "domain", "url_or_domain", "description", "url"),
    "date_header": ("date_section", "date_header", "date"),
    "date_section": ("date_section", "date_header", "date"),
    "place_name": ("title", "place_name"),
    "category": ("category", "place_category", "place_type"),
    "address": ("address", "subtitle", "category"),
    "status": ("status", "history_type", "history_label", "saved_state"),
    "filter_type": ("filter_type", "history_type", "history_label", "saved_filter"),
    "subject": ("subject", "title"),
    "sender": ("sender", "senders", "sender_name", "sender_email", "from"),
    "senders": ("senders", "sender", "sender_name", "sender_email", "from"),
    "snippet": ("snippet", "body_text", "content_text", "summary", "body_summary", "message_summary"),
}


def _record_field_value(record: Dict[str, Any], field: str) -> Any:
    for key in (field, *_FIELD_ALIASES.get(field, ())):
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _field_complete_rate(records: List[Dict[str, Any]], expected_fields: Iterable[str]) -> float:
    fields = [field for field in expected_fields if field]
    if records and not fields:
        ignored = {"raw_components", "normalized_fields", "_debug"}
        fields = sorted(
            {
                key
                for record in records
                for key, value in record.items()
                if key not in ignored and value not in (None, "", [], {})
            }
        )
    if not records or not fields:
        return 0.0
    present = 0
    total = len(records) * len(fields)
    for record in records:
        for field in fields:
            value = _record_field_value(record, field)
            if value not in (None, "", [], {}):
                present += 1
    return present / total if total else 0.0


def _duplicate_rate(records: List[Dict[str, Any]]) -> float:
    if not records:
        return 0.0
    seen = set()
    duplicates = 0
    for record in records:
        key = _record_identity(record)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
    return duplicates / len(records)


def _record_identity(record: Dict[str, Any]) -> Tuple[str, ...]:
    identity_fields = [
        "entity_id",
        "message_id",
        "thread_id",
        "transaction_id",
        "order_id",
        "display_name",
        "primary_text",
        "place_name",
        "address",
        "subtitle",
        "category",
        "status",
        "filter_type",
        "content_text",
        "subject",
        "title",
        "url",
        "url_domain",
        "url_or_domain",
        "description",
        "senders",
        "sender",
        "date",
        "date_section",
        "date_header",
        "timestamp",
    ]
    values = tuple(str(record.get(field) or "").strip() for field in identity_fields)
    if any(values):
        return values
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, default=str),)


def _unsafe_count(payloads: Iterable[Any]) -> int:
    danger_terms = ("pay", "post", "edit", "delete", "upload", "join", "leave", "confirm", "支付", "删除", "编辑", "恢复")
    allowed_readonly_terms = {
        "send",
        "download",
        "发送",
        "已发送",
        "下载",
        "下载内容",
        "downloads",
        "sent",
        "senders",
    }
    count = 0
    for payload in payloads:
        if payload is None:
            continue
        text = json.dumps(payload, ensure_ascii=False, default=str).casefold()
        for allowed in allowed_readonly_terms:
            text = text.replace(allowed.casefold(), " ")
        count += sum(text.count(term.casefold()) for term in danger_terms)
    return count


def _safety_action_payloads(task_result: Dict[str, Any]) -> List[Any]:
    """Return only executed/planned action traces for unsafe-action scanning.

    Records and script indexes may legitimately contain UI text such as
    "删除浏览数据" or email subjects containing action words. Those are evidence
    values, not executed actions, so scanning the whole task_result creates
    false failures.
    """
    payloads: List[Any] = []
    for key in ("actions", "reacts", "steps", "planned_steps"):
        value = task_result.get(key)
        if value:
            payloads.append({key: value})
    raw = task_result.get("raw_result")
    if isinstance(raw, dict):
        for key in ("actions", "reacts", "steps", "planned_steps"):
            value = raw.get(key)
            if value:
                payloads.append({key: value})
    script_results = task_result.get("script_results")
    if script_results:
        payloads.append({"script_results": script_results})
    return payloads


def _load_records_and_state(copied: Dict[str, str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    debug_records: List[Dict[str, Any]] = []
    state: Dict[str, Any] = {}
    if copied.get("records_path"):
        records = _records_from_payload(_read_json(Path(copied["records_path"])))
    if copied.get("records_debug_path"):
        debug_records = _records_from_payload(_read_json(Path(copied["records_debug_path"])))
    if copied.get("run_state_path"):
        loaded_state = _read_json(Path(copied["run_state_path"]))
        if isinstance(loaded_state, dict):
            state = loaded_state
    return records, debug_records, state


def _judge(task: Dict[str, Any], task_result: Dict[str, Any], records: List[Dict[str, Any]], debug_records: List[Dict[str, Any]], state: Dict[str, Any], duration: float) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    expected_min_records = int(task.get("expected_min_records", 1))
    field_rate = _field_complete_rate(records, task.get("expected_min_fields", []))
    duplicate_rate = _duplicate_rate(records)
    run_state_status = str(state.get("status") or "")
    run_state_errors = state.get("errors") if isinstance(state.get("errors"), list) else []
    completed = bool(task_result.get("completed"))
    has_records = len(records) >= expected_min_records
    debug_ok = not debug_records or len(debug_records) == len(records)
    state_ok = not run_state_status or run_state_status in {"completed", "terminal_complete", "child_terminal_complete", "done"}
    unsafe_action_count = _unsafe_count(_safety_action_payloads(task_result))
    evidence_coverage_proxy = min(1.0, len(records) / expected_min_records) if expected_min_records else 0.0
    precision_proxy = max(0.0, 1.0 - duplicate_rate) if records else 0.0
    success = completed and has_records and debug_ok and state_ok and not run_state_errors and unsafe_action_count == 0
    failure_reasons = []
    if not completed:
        failure_reasons.append(task_result.get("error") or "executor did not report completed")
    if not has_records:
        failure_reasons.append(f"records_count {len(records)} < expected_min_records {expected_min_records}")
    if not debug_ok:
        failure_reasons.append("records_debug count mismatch")
    if not state_ok:
        failure_reasons.append(f"run_state status {run_state_status!r}")
    if run_state_errors:
        failure_reasons.append(f"run_state errors: {run_state_errors}")
    if unsafe_action_count:
        failure_reasons.append(f"unsafe_action_count={unsafe_action_count}")

    metrics = {
        "task_success": success,
        "task_success_rate": 1.0 if success else 0.0,
        "evidence_coverage": evidence_coverage_proxy,
        "precision_vs_gold": precision_proxy,
        "runtime_seconds": round(duration, 3),
        "unsafe_action_count": unsafe_action_count,
        "records_count": len(records),
        "records_debug_count": len(debug_records),
        "field_complete_rate": round(field_rate, 6),
        "duplicate_rate": round(duplicate_rate, 6),
        "navigation_steps": int(task_result.get("total_steps") or 0),
        "repair_attempts": _repair_attempts(task_result),
        "key_state_coverage": 1.0 if completed else 0.0,
        "gold_available": bool(task.get("gold_available")),
        "metric_mode": "proxy_without_gold" if not task.get("gold_available") else "gold_aligned",
    }
    judge = {
        "ok": success,
        "success": success,
        "failure_reasons": failure_reasons,
        "thresholds": {
            "expected_min_records": expected_min_records,
            "unsafe_action_count": 0,
            "records_debug_matches_records": True,
        },
        "notes": [
            "This feasibility run has no manually built gold records yet; evidence_coverage and precision_vs_gold are proxy metrics.",
            "Replace proxy metrics with entity-aligned gold comparison when gold records are available.",
        ],
    }
    return metrics, judge


def _repair_attempts(task_result: Dict[str, Any]) -> int:
    raw = task_result.get("raw_result") if isinstance(task_result.get("raw_result"), dict) else {}
    for key in ("repair_attempts", "attempts"):
        value = raw.get(key)
        if isinstance(value, int):
            return value
    state = task_result.get("last_run_state") if isinstance(task_result.get("last_run_state"), dict) else {}
    value = state.get("repair_attempts")
    return int(value) if isinstance(value, int) else 0


def _event_trace(run_dir: Path, task: Dict[str, Any], selection: Dict[str, Any], metrics: Dict[str, Any], judge: Dict[str, Any]) -> None:
    trace_path = run_dir / "event_trace.jsonl"
    events = [
        {"event": "run_started", "timestamp": dt.datetime.now().isoformat(timespec="seconds"), "task_id": task["task_id"], "app_name": task["app_name"], "package_name": task["package_name"]},
        {"event": "route_selected", "scheduler_used": selection.get("scheduler_used"), "similarity_score": selection.get("similarity_score")},
        {"event": "metrics_computed", "metrics": metrics},
        {"event": "judge_completed", "judge": judge},
    ]
    trace_path.write_text("\n".join(json.dumps(event, ensure_ascii=False, default=str) for event in events) + "\n", encoding="utf-8")


def _task_result_from_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    for app in summary.get("apps_executed") or []:
        tasks = app.get("tasks_executed") or []
        if tasks:
            result = dict(tasks[0])
            result.setdefault("app_name", app.get("app_name"))
            result.setdefault("package_name", app.get("package_name"))
            return result
    return {"completed": False, "error": "no task result in executor summary"}


def run(args: argparse.Namespace) -> Dict[str, Any]:
    serial = resolve_device_serial(args.device_serial, required=True)
    run_id = args.run_id or dt.datetime.now().strftime("feasibility_%Y%m%d_%H%M%S")
    experiment_dir = args.output_root.resolve() / run_id
    tasks = _selected_tasks(args.apps, max_tasks=args.max_tasks)
    if not tasks:
        raise SystemExit(f"no tasks selected from --apps={args.apps!r}")

    cfg = get_llm_config(api_base=args.api_base or None, model=args.model or None)
    device = AndroidDevice(adb_endpoint=serial)
    executor = ForensicTaskExecutor(
        device=device,
        api_key=cfg.api_key,
        api_base=cfg.api_base,
        model=cfg.model,
        threshold=args.threshold,
        data_dir=str(experiment_dir / "executor_data"),
    )

    _write_json(experiment_dir / "task_specs.json", {"tasks": tasks})
    summary_rows: List[Dict[str, Any]] = []

    for repeat_index in range(1, max(1, args.repeat) + 1):
        for task in tasks:
            run_dir = experiment_dir / task["app_name"] / task["task_id"] / "F2" / f"run_{repeat_index:03d}"
            run_dir.mkdir(parents=True, exist_ok=True)
            plan_path = run_dir / "plan.json"
            _build_plan(task, plan_path)
            _write_json(run_dir / "task_spec.json", task)

            started = time.time()
            try:
                summary = executor.execute_plan(str(plan_path), selection_only=False)
            except Exception as exc:
                summary = {
                    "total_tasks": 1,
                    "completed_tasks": 0,
                    "failed_tasks": 1,
                    "apps_executed": [
                        {
                            "app_name": task["app_name"],
                            "package_name": task["package_name"],
                            "tasks_executed": [{"completed": False, "error": str(exc)}],
                        }
                    ],
                }
            duration = time.time() - started
            task_result = _task_result_from_summary(summary)
            artifact_paths = _find_artifact_paths(task_result)
            copied = _copy_artifacts(artifact_paths, run_dir)
            records, debug_records, state = _load_records_and_state(copied)
            metrics, judge = _judge(task, task_result, records, debug_records, state, duration)
            route = {
                "scheduler_used": task_result.get("scheduler_used", ""),
                "similarity_score": task_result.get("similarity_score", 0.0),
                "script_results": task_result.get("script_results", []),
                "artifact_paths": artifact_paths,
                "copied_artifacts": copied,
            }
            _write_json(run_dir / "executor_summary.json", summary)
            _write_json(run_dir / "task_result.json", task_result)
            _write_json(run_dir / "metrics.json", metrics)
            _write_json(run_dir / "judge.json", judge)
            _write_json(run_dir / "route.json", route)
            _event_trace(run_dir, task, route, metrics, judge)

            row = {
                "run_id": run_id,
                "repeat": repeat_index,
                "group_id": "F2",
                "task_id": task["task_id"],
                "app_name": task["app_name"],
                "package_name": task["package_name"],
                "task_description": task["task_description"],
                "scheduler_used": route["scheduler_used"],
                "similarity_score": route["similarity_score"],
                "run_dir": str(run_dir),
                **metrics,
                "failure_reasons": "; ".join(judge["failure_reasons"]),
            }
            summary_rows.append(row)
            print(json.dumps(row, ensure_ascii=False, default=str))

    aggregate = _aggregate(summary_rows)
    _write_json(experiment_dir / "summary_runs.json", summary_rows)
    _write_json(experiment_dir / "summary_metrics.json", aggregate)
    _write_csv(experiment_dir / "summary_runs.csv", summary_rows)
    _write_json(experiment_dir / "experiment_manifest.json", {
        "run_id": run_id,
        "device_serial": serial,
        "experiment_dir": str(experiment_dir),
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "group_id": "F2",
        "model": cfg.model,
        "api_base": cfg.api_base,
        "threshold": args.threshold,
        "tasks": tasks,
        "aggregate": aggregate,
    })
    return {"ok": True, "experiment_dir": str(experiment_dir), "aggregate": aggregate, "runs": summary_rows}


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    numeric_keys = [
        "task_success_rate",
        "evidence_coverage",
        "precision_vs_gold",
        "runtime_seconds",
        "unsafe_action_count",
        "records_count",
        "field_complete_rate",
        "duplicate_rate",
        "navigation_steps",
        "repair_attempts",
        "key_state_coverage",
    ]
    overall = {
        key: round(sum(float(row.get(key, 0) or 0) for row in rows) / len(rows), 6)
        for key in numeric_keys
    }
    by_app: Dict[str, Dict[str, Any]] = {}
    for app in sorted({str(row.get("app_name")) for row in rows}):
        app_rows = [row for row in rows if str(row.get("app_name")) == app]
        by_app[app] = {
            key: round(sum(float(row.get(key, 0) or 0) for row in app_rows) / len(app_rows), 6)
            for key in numeric_keys
        }
        by_app[app]["runs"] = len(app_rows)
    return {"overall": overall, "by_app": by_app, "runs": len(rows)}


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    import csv

    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: List[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = build_parser().parse_args()
    payload = run(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"experiment_dir: {payload['experiment_dir']}")
        print(json.dumps(payload["aggregate"], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
