#!/usr/bin/env python3
"""HTTP adapter for the ForensiFlow web UI.

The API exposes real device state, scheduler jobs, runtime artifacts, evidence
files, and audit chains over the existing ForensiFlow execution entrypoints.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DATA_DIR = REPO_ROOT / "data"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
WEB_API_DIR = DATA_DIR / "web_api"
JOBS_DIR = WEB_API_DIR / "jobs"
PLANS_DIR = WEB_API_DIR / "plans"
REPORTS_DIR = DATA_DIR / "web_reports"
LIVE_SCREENSHOT_DIR = WEB_API_DIR / "live_screenshots"

JOBS: Dict[str, Dict[str, Any]] = {}


app = FastAPI(title="ForensiFlow Web API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlanRequest(BaseModel):
    case_name: str = ""
    case_type: str = ""
    case_background: str = ""
    forensic_goals: str = ""
    device_serial: str = ""
    allow_fallback: bool = True


class StartTaskRequest(BaseModel):
    plan: Dict[str, Any]
    device_serial: str = ""
    app_name: str = ""
    task_index: Optional[int] = None
    threshold: float = 0.75
    execution_mode: str = Field(default="planned", description="planned or quick")
    case_name: str = ""


class QuickTaskRequest(BaseModel):
    task_description: str
    device_serial: str = ""
    app_name: str = "WhatsApp Messenger"
    package_name: str = ""
    task_level: int = 3
    task_type: str = "targeted_object_extraction"
    constraint: str = ""
    threshold: float = 0.75
    case_name: str = "快速取证任务"


class ReportRequest(BaseModel):
    run_dir: str = ""
    title: str = "ForensiFlow 取证演示报告"


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _json_dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _safe_rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except Exception:
        return path.as_posix()


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe[:120] or "default"


def _resolve_allowed_file(path_value: str) -> Path:
    raw = Path(path_value)
    path = raw if raw.is_absolute() else REPO_ROOT / raw
    path = path.resolve()
    allowed_roots = [DATA_DIR.resolve(), ARTIFACTS_DIR.resolve(), (REPO_ROOT / "runner").resolve()]
    if not any(str(path).startswith(str(root) + os.sep) or path == root for root in allowed_roots):
        raise HTTPException(status_code=403, detail="file path is outside allowed ForensiFlow artifact roots")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return path


def _run_adb_devices() -> Tuple[bool, List[Dict[str, str]], str]:
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=8)
    except Exception as exc:
        return False, [], str(exc)
    devices = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append({"serial": parts[0], "state": parts[1]})
    return result.returncode == 0, devices, result.stderr.strip()


def _capture_live_screenshot(serial: str = "") -> Dict[str, Any]:
    adb_ok, adb_devices, adb_error = _run_adb_devices()
    connected_serials = [item["serial"] for item in adb_devices if item.get("state") == "device"]
    selected = serial or (connected_serials[0] if connected_serials else "")
    if not adb_ok:
        return {"ok": False, "serial": selected, "error": adb_error or "adb devices failed"}
    if not selected:
        return {"ok": False, "serial": "", "error": "no connected Android device"}
    if selected not in connected_serials:
        return {"ok": False, "serial": selected, "error": f"device {selected} is not connected"}

    LIVE_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = LIVE_SCREENSHOT_DIR / f"{_safe_filename(selected)}.png"
    cmd = ["adb", "-s", selected, "exec-out", "screencap", "-p"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=8)
    except Exception as exc:
        return {"ok": False, "serial": selected, "error": str(exc)}
    if result.returncode != 0 or not result.stdout:
        error = result.stderr.decode("utf-8", errors="replace").strip() or "empty screencap output"
        return {"ok": False, "serial": selected, "error": error}
    path.write_bytes(result.stdout)
    return {
        "ok": True,
        "serial": selected,
        "path": _safe_rel_path(path),
        "url": _file_url(path),
        "capturedAt": _now_iso(),
    }


def _llm_configured() -> bool:
    def is_placeholder(value: str) -> bool:
        normalized = (value or "").strip().lower()
        return normalized.startswith(("your_", "your-", "changeme", "change_me"))

    keys = [
        "MOMI_API_KEY",
        "MIMO_API_KEY",
        "LLM_API_KEY",
        "PAGE_AGENT_MOBILE_API_KEY",
        "OPENAI_API_KEY",
        "QWEN_API_KEY",
    ]
    for key in keys:
        value = os.getenv(key, "")
        if value and not is_placeholder(value):
            return True
    for env_name in [".env", ".env.mimo"]:
        env_path = REPO_ROOT / env_name
        if not env_path.exists():
            continue
        text = env_path.read_text(encoding="utf-8", errors="ignore")
        for key in keys:
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if line.startswith(key + "="):
                    value = line.split("=", 1)[1].strip().strip("'\"")
                    if value and not is_placeholder(value):
                        return True
    return False


def _parse_package_mapping(path: Path) -> List[Dict[str, str]]:
    apps = []
    if not path.exists():
        return apps
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("="):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            apps.append(
                {
                    "package": parts[0].strip(),
                    "name": parts[1].strip() or parts[0].strip(),
                    "category": parts[2].strip() if len(parts) >= 3 else "Unknown",
                }
            )
    return apps


def _load_apps(device_serial: str = "") -> List[Dict[str, str]]:
    candidates = []
    if device_serial:
        candidates.append(DATA_DIR / "devices" / device_serial / "app_info" / "package_name_mapping.txt")
    candidates.extend(
        [
            DATA_DIR / "app_info" / "package_name_mapping.txt",
            DATA_DIR / "app_info_cache" / "package_name_mapping.txt",
        ]
    )
    for candidate in candidates:
        apps = _parse_package_mapping(candidate)
        if apps:
            return apps
    cache_path = DATA_DIR / "app_info_cache" / "app_info_cache.json"
    cache = _json_load(cache_path, {})
    apps = []
    if isinstance(cache, dict):
        for package_name, entry in cache.items():
            data = entry.get("data", entry) if isinstance(entry, dict) else {}
            apps.append(
                {
                    "package": package_name,
                    "name": data.get("title") or package_name,
                    "category": data.get("category") or "Unknown",
                }
            )
    return sorted(apps, key=lambda item: item["name"].lower())


def _package_for_app(app_name: str, device_serial: str = "") -> str:
    normalized = app_name.strip().lower()
    if not normalized:
        return ""
    for app_info in _load_apps(device_serial):
        name = str(app_info.get("name") or "").lower()
        package = str(app_info.get("package") or "")
        if normalized == name or normalized == package.lower() or normalized in name:
            return package
    if "whatsapp" in normalized:
        return "com.whatsapp"
    if "chrome" in normalized:
        return "com.android.chrome"
    return ""


def _device_serial_from_path(path: Path) -> str:
    parts = path.resolve().parts
    if "devices" in parts:
        idx = parts.index("devices")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    for marker in ["page_agent_mobile_runs", "codex_mobile_agent_runs"]:
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return ""


def _iter_record_files(limit: int = 80) -> List[Path]:
    roots = [
        DATA_DIR / "codex_mobile_agent_runs",
        DATA_DIR / "page_agent_mobile_runs",
        DATA_DIR / "devices",
    ]
    roots.extend(DATA_DIR.glob("run_llm_*"))
    paths: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            paths.extend(root.rglob("records.json"))
        except Exception:
            continue
    paths = [path for path in paths if path.is_file()]
    paths.sort(key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    return paths[:limit]


def _extract_records_payload(path: Path) -> Tuple[List[Any], Dict[str, Any], str]:
    payload = _json_load(path)
    if payload is None:
        return [], {}, "invalid json"
    if isinstance(payload, list):
        return payload, {}, ""
    if isinstance(payload, dict):
        records = payload.get("records")
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        if isinstance(records, list):
            return records, metadata, ""
    return [], {}, "expected list or {'records': list}"


def _record_type(record: Any, path: Path) -> str:
    text = json.dumps(record, ensure_ascii=False, default=str).lower()
    path_text = path.as_posix().lower()
    if "url" in text or "chrome" in path_text or "history" in text:
        return "浏览历史"
    if "call" in text or "通话" in path_text:
        return "通话记录"
    if "message" in text or "sender" in text or "聊天" in path_text:
        return "聊天记录"
    if "contact" in text or "联系人" in path_text:
        return "联系人"
    return "结构化记录"


def _evidence_type_for_record_file(records: List[Any], metadata: Dict[str, Any], path: Path) -> str:
    sample = records[0] if records else {}
    metadata_text = json.dumps(metadata, ensure_ascii=False, default=str).lower()
    sidecar_text = json.dumps(_record_file_context(path), ensure_ascii=False, default=str).lower()
    path_text = path.as_posix().lower()
    combined = f"{metadata_text} {sidecar_text} {path_text}"
    if records:
        return _record_type(sample, path)
    if "reverse_timeline" in combined or "chat" in combined or "聊天" in combined or "message" in combined:
        return "聊天记录"
    if "call" in combined or "通话" in combined:
        return "通话记录"
    if "contact" in combined or "联系人" in combined:
        return "联系人"
    if "history" in combined or "chrome" in combined or "浏览" in combined:
        return "浏览历史"
    return "结构化记录"


def _record_file_context(record_path: Path) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    records_debug = _json_load(record_path.with_name("records_debug.json"), {})
    if isinstance(records_debug, dict):
        metadata = records_debug.get("metadata") if isinstance(records_debug.get("metadata"), dict) else {}
        context.update({f"debug_{key}": value for key, value in metadata.items()})
    for parent in [record_path.parent, *record_path.parents]:
        if parent == REPO_ROOT.parent:
            break
        workspace_context = _json_load(parent / "workspace_context.json", {})
        if isinstance(workspace_context, dict) and workspace_context:
            context.update(workspace_context)
            break
    return context


def _summarize_record(record: Any) -> str:
    if not isinstance(record, dict):
        return str(record)[:120]
    for keys in [
        ("sender", "message"),
        ("title", "url"),
        ("name", "phone"),
        ("contact", "message"),
        ("timestamp", "content"),
    ]:
        values = [str(record.get(key, "")).strip() for key in keys if record.get(key)]
        if values:
            return " / ".join(values)[:160]
    for key in ["message", "content", "text", "title", "name", "url"]:
        value = str(record.get(key, "")).strip()
        if value:
            return value[:160]
    return json.dumps(record, ensure_ascii=False, default=str)[:160]


def _file_url(path: Path) -> str:
    return f"/api/files?path={_safe_rel_path(path)}"


def _collect_evidence(limit: int = 200) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for record_path in _iter_record_files():
        records, metadata, error = _extract_records_payload(record_path)
        if error:
            continue
        stat = record_path.stat()
        device_serial = _device_serial_from_path(record_path)
        app_name = str(metadata.get("app_name") or metadata.get("app") or "")
        if not app_name:
            app_name = "Chrome" if "chrome" in record_path.as_posix().lower() else "WhatsApp" if "whatsapp" in record_path.as_posix().lower() else "Unknown"
        digest = _sha256_text(record_path.read_text(encoding="utf-8", errors="replace"))
        task_name = _task_name_for_record_file(record_path, metadata)
        items.append(
            {
                "id": digest[:16],
                "caseId": "runtime-artifacts",
                "deviceSerial": device_serial or "-",
                "evidenceType": _evidence_type_for_record_file(records, metadata, record_path),
                "summary": task_name,
                "app": app_name,
                "page": "records.json",
                "hash": digest[:16],
                "timestamp": dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "sourcePath": _safe_rel_path(record_path),
                "runDir": _safe_rel_path(record_path.parent),
                "downloadUrl": _file_url(record_path),
                "recordCount": len(records),
            }
        )
        if len(items) >= limit:
            return items
    return items


def _task_name_for_record_file(record_path: Path, metadata: Dict[str, Any]) -> str:
    for key in ["target", "task", "task_description", "forensic_target"]:
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    sidecar = _record_file_context(record_path)
    for key in ["target", "task", "task_description", "forensic_target", "debug_target"]:
        value = str(sidecar.get(key) or "").strip()
        if value:
            if key in {"target", "debug_target"} and "聊天" not in value and "chat" not in value.lower() and "whatsapp" in json.dumps(sidecar, ensure_ascii=False).lower():
                return f"提取 WhatsApp 中与 {value} 的聊天记录"
            return value[:180]
    blocker = sidecar.get("blocker") if isinstance(sidecar.get("blocker"), dict) else {}
    blocker_detail = str(blocker.get("detail") or sidecar.get("debug_blocker_detail") or "").strip()
    if blocker_detail:
        target = str(sidecar.get("target") or sidecar.get("debug_target") or "").strip()
        return f"提取 WhatsApp 中与 {target} 的聊天记录" if target else blocker_detail[:180]
    for parent in [record_path.parent, *record_path.parents]:
        if parent == REPO_ROOT.parent:
            break
        for name in ["final.json", "run_state.json", "workspace_context.json"]:
            payload = _json_load(parent / name, {})
            if isinstance(payload, dict):
                for key in ["target", "task", "task_description", "reason"]:
                    value = str(payload.get(key) or "").strip()
                    if value and value.lower() not in {"success", "done"}:
                        return value[:180]
                nested = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                for key in ["target", "task", "task_description"]:
                    value = str(nested.get(key) or "").strip()
                    if value:
                        return value[:180]
    path_text = record_path.as_posix().lower()
    if "chrome" in path_text or "history" in path_text:
        return "提取 Chrome 浏览历史记录"
    if "call" in path_text or "通话" in record_path.as_posix():
        return "提取通话记录"
    if "chat" in path_text or "聊天" in record_path.as_posix():
        return "提取聊天记录"
    return "取证脚本输出 records.json"


def _count_evidence_for_device(serial: str) -> int:
    if not serial:
        return 0
    count = 0
    for path in _iter_record_files(limit=120):
        if _device_serial_from_path(path) == serial:
            records, _, error = _extract_records_payload(path)
            if not error:
                count += len(records)
    return count


def _count_tasks_for_device(serial: str) -> int:
    root = DATA_DIR / "devices" / serial
    if not root.exists():
        return 0
    return len(list(root.rglob("*execution_summary.json"))) + len(list((root / "plans").glob("*.json")) if (root / "plans").exists() else [])


def _collect_devices() -> List[Dict[str, Any]]:
    adb_ok, adb_devices, adb_error = _run_adb_devices()
    connected = {item["serial"]: item for item in adb_devices}
    serials = set(connected.keys())
    devices_root = DATA_DIR / "devices"
    if devices_root.exists():
        serials.update(path.name for path in devices_root.iterdir() if path.is_dir())
    devices = []
    for serial in sorted(serials):
        info = _json_load(devices_root / serial / "device_info.json", {}) if devices_root.exists() else {}
        state = connected.get(serial, {}).get("state", "disconnected")
        status = "connected" if state == "device" else "disconnected"
        devices.append(
            {
                "serial": serial,
                "model": info.get("model") or serial,
                "androidVersion": info.get("android_version") or "",
                "manufacturer": info.get("manufacturer") or "",
                "status": status,
                "adbState": state,
                "taskCount": _count_tasks_for_device(serial),
                "evidenceCount": _count_evidence_for_device(serial),
                "lastActiveAt": _latest_mtime_text(DATA_DIR / "devices" / serial),
            }
        )
    return devices if adb_ok or devices else [{"serial": "", "model": "ADB 未连接", "status": "disconnected", "adbState": adb_error, "taskCount": 0, "evidenceCount": 0, "lastActiveAt": "-"}]


def _latest_mtime_text(path: Path) -> str:
    if not path.exists():
        return "-"
    latest = path.stat().st_mtime
    if path.is_dir():
        for root, _, files in os.walk(path):
            for name in files[:50]:
                try:
                    latest = max(latest, (Path(root) / name).stat().st_mtime)
                except Exception:
                    pass
    return dt.datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M:%S")


def _fallback_plan(request: PlanRequest, apps: List[Dict[str, str]]) -> Dict[str, Any]:
    text = f"{request.case_background}\n{request.forensic_goals}".lower()
    selected = []
    for app_info in apps:
        app_text = f"{app_info.get('name', '')} {app_info.get('package', '')}".lower()
        if "whatsapp" in text and "whatsapp" in app_text:
            selected.append(app_info)
        elif "chrome" in text and "chrome" in app_text:
            selected.append(app_info)
        elif "outlook" in text and "outlook" in app_text:
            selected.append(app_info)
        elif "telegram" in text and "telegram" in app_text:
            selected.append(app_info)
    if not selected and apps:
        selected = apps[:1]
    if not selected:
        selected = [{"name": "WhatsApp Messenger", "package": "com.whatsapp", "category": "通讯"}]

    plans = []
    for app_info in selected[:3]:
        tasks = []
        if any(word in text for word in ["聊天", "chat", "会话", "message"]):
            tasks.append({"task_level": 2, "task_type": "module_extraction", "task_description": "消息/会话总列表界面全量提取", "target_objects": [], "constraint": ""})
        if any(word in text for word in ["通话", "call"]):
            tasks.append({"task_level": 2, "task_type": "module_extraction", "task_description": "通话记录界面遍历抓取", "target_objects": [], "constraint": ""})
        if any(word in text for word in ["联系人", "contact"]):
            tasks.append({"task_level": 1, "task_type": "full_extraction", "task_description": "全局联系人列表界面遍历抓取", "target_objects": [], "constraint": ""})
        if any(word in text for word in ["浏览", "history", "chrome", "历史"]):
            tasks.append({"task_level": 2, "task_type": "module_extraction", "task_description": "浏览器历史记录界面遍历抓取", "target_objects": [], "constraint": ""})
        if not tasks:
            tasks.append({"task_level": 1, "task_type": "full_extraction", "task_description": "应用整体取证相关界面全量提取", "target_objects": [], "constraint": ""})
        plans.append({"app_name": app_info["name"], "package_name": app_info["package"], "tasks": tasks[:5]})
    return {
        "case_analysis_summary": "后端 LLM 规划不可用时生成的安全预览规划。该规划只根据输入关键词和已知应用映射生成，用于演示确认流程；正式执行前建议配置 LLM 后重新规划。",
        "forensic_plan": plans,
    }


def _save_job(job: Dict[str, Any]) -> None:
    _json_dump(JOBS_DIR / job["id"] / "job.json", job)


def _load_jobs() -> List[Dict[str, Any]]:
    jobs = list(JOBS.values())
    seen = {job["id"] for job in jobs}
    if JOBS_DIR.exists():
        for path in JOBS_DIR.glob("*/job.json"):
            job = _json_load(path, {})
            if isinstance(job, dict) and job.get("id") and job["id"] not in seen:
                jobs.append(job)
    jobs.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
    return jobs


def _start_subprocess_job(cmd: List[str], job: Dict[str, Any]) -> None:
    job_dir = JOBS_DIR / job["id"]
    stdout_path = job_dir / "stdout.txt"
    stderr_path = job_dir / "stderr.txt"
    job.update({"status": "running", "startedAt": _now_iso(), "stdoutPath": _safe_rel_path(stdout_path), "stderrPath": _safe_rel_path(stderr_path)})
    _save_job(job)
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=stdout, stderr=stderr, env=env)
        job["pid"] = process.pid
        _save_job(job)
        returncode = process.wait()
    job.update({"status": "succeeded" if returncode == 0 else "failed", "returncode": returncode, "finishedAt": _now_iso()})
    _save_job(job)


def _read_log_tail(path_value: str, tail: int = 20000) -> str:
    if not path_value:
        return ""
    path = REPO_ROOT / path_value if not Path(path_value).is_absolute() else Path(path_value)
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - tail), os.SEEK_SET)
        return handle.read().decode("utf-8", errors="replace")


def _path_from_value(path_value: str) -> Path:
    path = Path(path_value)
    return path if path.is_absolute() else REPO_ROOT / path


def _job_dir(job: Dict[str, Any]) -> Path:
    return JOBS_DIR / str(job.get("id", ""))


def _load_job_plan(job: Dict[str, Any]) -> Dict[str, Any]:
    plan_path_value = str(job.get("planPath") or "")
    candidates = []
    if plan_path_value:
        candidates.append(_path_from_value(plan_path_value))
    candidates.append(_job_dir(job) / "plan.json")
    for candidate in candidates:
        payload = _json_load(candidate, {})
        if isinstance(payload, dict) and payload.get("forensic_plan") is not None:
            return payload
    return {}


def _load_job_summary(job: Dict[str, Any]) -> Dict[str, Any]:
    plan_path_value = str(job.get("planPath") or "")
    candidates = [_job_dir(job) / "plan_execution_summary.json"]
    if plan_path_value:
        plan_path = _path_from_value(plan_path_value)
        candidates.append(plan_path.parent / f"{plan_path.stem}_execution_summary.json")
    for candidate in candidates:
        payload = _json_load(candidate, {})
        if isinstance(payload, dict) and payload.get("apps_executed") is not None:
            return payload
    return {}


def _flatten_plan_tasks(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    sequence = 1
    for app_index, app_plan in enumerate(plan.get("forensic_plan") or []):
        if not isinstance(app_plan, dict):
            continue
        app_name = str(app_plan.get("app_name") or "")
        package_name = str(app_plan.get("package_name") or "")
        for task_index, task in enumerate(app_plan.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            task_description = str(task.get("task_description") or "")
            tasks.append(
                {
                    "id": f"{app_index}-{task_index}",
                    "sequence": sequence,
                    "appIndex": app_index,
                    "taskIndex": task_index,
                    "appName": app_name,
                    "packageName": package_name,
                    "taskLevel": task.get("task_level", 0),
                    "taskType": task.get("task_type", ""),
                    "taskDescription": task_description,
                    "label": f"[L{task.get('task_level', 0)}] {task_description}" if task.get("task_level") else task_description,
                    "targetObjects": task.get("target_objects") or [],
                    "constraint": task.get("constraint") or "",
                    "status": "pending",
                    "schedulerUsed": "",
                    "similarityScore": None,
                    "runDir": "",
                    "error": "",
                }
            )
            sequence += 1
    return tasks


def _apply_summary_to_subtasks(job: Dict[str, Any], subtasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    summary = _load_job_summary(job)
    by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for app_result in summary.get("apps_executed") or []:
        if not isinstance(app_result, dict):
            continue
        app_name = str(app_result.get("app_name") or "")
        for task_result in app_result.get("tasks_executed") or []:
            if isinstance(task_result, dict):
                by_key[(app_name, int(task_result.get("task_index") or 0))] = task_result

    for task in subtasks:
        result = by_key.get((str(task.get("appName") or ""), int(task.get("taskIndex") or 0)))
        if result:
            completed = bool(result.get("completed"))
            task["status"] = "done" if completed else "error"
            task["schedulerUsed"] = result.get("scheduler_used") or ""
            task["similarityScore"] = result.get("similarity_score")
            task["runDir"] = result.get("data_dir") or result.get("run_dir") or ""
            task["error"] = result.get("error") or ""

    if job.get("status") == "running":
        explicit_index = job.get("taskIndex")
        active_marked = False
        for task in subtasks:
            if task["status"] != "pending":
                continue
            if explicit_index is None or int(task.get("taskIndex") or 0) == int(explicit_index):
                task["status"] = "active"
                active_marked = True
                break
        if not active_marked and subtasks:
            for task in reversed(subtasks):
                if task["status"] == "done":
                    task["status"] = "active"
                    break
    elif job.get("status") == "failed":
        for task in subtasks:
            if task["status"] in {"pending", "active"}:
                task["status"] = "error"
                break
    return subtasks


def _subtasks_for_job(job: Dict[str, Any]) -> Dict[str, Any]:
    plan = _load_job_plan(job)
    subtasks = _apply_summary_to_subtasks(job, _flatten_plan_tasks(plan))
    source = str(job.get("executionMode") or "")
    plan_summary = str(plan.get("case_analysis_summary") or "")
    if not source and ("快速任务" in plan_summary or "直接提交" in plan_summary or "工作台快速" in plan_summary):
        source = "quick"
    if not source:
        source = "planned"
    return {
        "source": "quick" if source == "quick" else "planned",
        "planSummary": plan_summary,
        "subtasks": subtasks,
    }


def _create_task_job(
    *,
    plan: Dict[str, Any],
    device_serial: str = "",
    app_name: str = "",
    task_index: Optional[int] = None,
    threshold: float = 0.75,
    execution_mode: str = "planned",
    case_name: str = "",
) -> Dict[str, Any]:
    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    plan_path = job_dir / "plan.json"
    _json_dump(plan_path, plan)
    cmd = [sys.executable, str(REPO_ROOT / "run_end_to_end.py"), "--plan", str(plan_path), "--threshold", str(threshold)]
    if device_serial:
        cmd.extend(["--device-serial", device_serial])
    if app_name:
        cmd.extend(["--app", app_name])
    if task_index is not None:
        cmd.extend(["--task-index", str(task_index)])
    job = {
        "id": job_id,
        "status": "queued",
        "createdAt": _now_iso(),
        "command": cmd,
        "planPath": _safe_rel_path(plan_path),
        "deviceSerial": device_serial,
        "appName": app_name,
        "taskIndex": task_index,
        "executionMode": "quick" if execution_mode == "quick" else "planned",
        "caseName": case_name,
    }
    JOBS[job_id] = job
    _save_job(job)
    thread = threading.Thread(target=_start_subprocess_job, args=(cmd, job), daemon=True)
    thread.start()
    return job


def _latest_job_for_workspace() -> Optional[Dict[str, Any]]:
    jobs = _load_jobs()
    running = [job for job in jobs if job.get("status") == "running"]
    if running:
        return running[0]
    return jobs[0] if jobs else None


def _strip_log_prefix(line: str) -> str:
    value = re.sub(r"^\d{4}-\d{2}-\d{2} [\d:,]+ - [^-]+ - [A-Z]+ -\s*", "", line).strip()
    return value.strip(" \t─=|")


def _action_from_line(line: str) -> Optional[Dict[str, Any]]:
    clean = _strip_log_prefix(line)
    if not clean:
        return None
    patterns: List[Tuple[str, str, str]] = [
        (r"步骤\s+(\d+/\d+):\s*([A-Z_]+)", "执行步骤", "log_step"),
        (r"📜\s*CallScript[:：]\s*(.+)", "调用取证脚本", "call_script"),
        (r"CallScript\s*[-:：]\s*(.+)", "调用取证脚本", "call_script"),
        (r"执行脚本[:：]\s*(.+)", "执行脚本", "script"),
        (r"启动应用[:：]\s*(.+)", "启动应用", "launch"),
        (r"点击(?:操作)?[:：]\s*(.+)", "点击", "click"),
        (r"\bClick\b\s*[-:：]\s*(.+)", "点击", "click"),
        (r"\bSwipe\b\s*[-:：]\s*(.+)", "滑动", "swipe"),
        (r"滑动(?:操作)?[:：]\s*(.+)", "滑动", "swipe"),
        (r"等待应用加载", "等待应用加载", "wait"),
        (r"继续扫描(.+)", "扫描列表", "scan"),
        (r"已到达(.+)", "扫描完成", "scan"),
        (r"提取结果已保存[:：]\s*(.+)", "保存取证结果", "save"),
        (r"选择结果[:：]\s*(.+)", "调度器选择", "scheduler"),
        (r"使用调度器[:：]\s*(.+)", "使用调度器", "scheduler"),
        (r"任务 #?(\d+) 完成", "任务完成", "task_done"),
        (r"任务 #?(\d+) 未完成", "任务未完成", "task_failed"),
        (r"执行失败[:：]\s*(.+)", "执行失败", "error"),
    ]
    for pattern, label, operation in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        target = ""
        if operation == "log_step" and len(match.groups()) >= 2:
            target = f"{match.group(1)} {match.group(2).upper()}"
        elif match.groups():
            target = str(match.group(1)).strip()
        return {"action": label, "operation": operation, "target": target, "raw": clean}
    if "Agent" in clean and ("blocked" in clean.lower() or "BLOCKED" in clean):
        return {"action": "Agent 状态", "operation": "agent_status", "target": clean[:220], "raw": clean}
    return None


def _last_action_from_logs(job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    text = "\n".join(
        [
            _read_log_tail(str(job.get("stdoutPath") or ""), tail=50000),
            _read_log_tail(str(job.get("stderrPath") or ""), tail=50000),
        ]
    )
    for line in reversed(text.splitlines()):
        action = _action_from_line(line)
        if action:
            action["source"] = "runtime_log"
            return action
    return None


def _run_dirs_for_job(job: Dict[str, Any]) -> List[Path]:
    dirs: List[Path] = []
    summary = _load_job_summary(job)
    for app_result in summary.get("apps_executed") or []:
        for task_result in app_result.get("tasks_executed") or []:
            if not isinstance(task_result, dict):
                continue
            for key in ["data_dir", "run_dir"]:
                value = str(task_result.get(key) or "")
                if value:
                    path = _path_from_value(value).resolve()
                    if path.exists() and path.is_dir():
                        dirs.append(path)
    text = "\n".join(
        [
            _read_log_tail(str(job.get("stdoutPath") or ""), tail=60000),
            _read_log_tail(str(job.get("stderrPath") or ""), tail=60000),
        ]
    )
    for pattern in [r"Run directory:\s*(.+)", r"本次运行数据将保存到:\s*(.+)", r"run_dir[=:]\s*(.+)"]:
        for match in re.finditer(pattern, text):
            raw = match.group(1).strip().strip("'\"")
            path = _path_from_value(raw).resolve()
            if path.exists() and path.is_dir():
                dirs.append(path)
    unique: List[Path] = []
    seen = set()
    for path in dirs:
        key = path.as_posix()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _event_action_from_run_dir(run_dir: Path) -> Optional[Dict[str, Any]]:
    event_files = list(run_dir.rglob("events.jsonl")) if run_dir.exists() else []
    event_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for event_path in event_files[:3]:
        lines = event_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in reversed(lines[-200:]):
            try:
                event = json.loads(line)
            except Exception:
                continue
            event_type = event.get("type") or event.get("event") or event.get("name")
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event_type == "action_started":
                name = payload.get("name") or payload.get("action") or "agent_action"
                action_input = payload.get("input") or payload.get("params") or {}
                return {
                    "action": "Agent 正在操作手机",
                    "operation": str(name),
                    "target": json.dumps(action_input, ensure_ascii=False, default=str)[:220],
                    "source": "agent_events",
                    "raw": str(name),
                }
            if event_type == "step_completed":
                action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
                name = action.get("name") or action.get("action") or "agent_step"
                action_input = action.get("input") or action.get("params") or {}
                return {
                    "action": "Agent 完成一步操作",
                    "operation": str(name),
                    "target": json.dumps(action_input, ensure_ascii=False, default=str)[:220],
                    "source": "agent_events",
                    "raw": str(name),
                }
            if event_type == "observation":
                return {
                    "action": "读取手机界面",
                    "operation": "observe",
                    "target": str(payload.get("xml_artifact") or payload.get("step") or ""),
                    "source": "agent_events",
                    "raw": "observation",
                }
    return None


def _scheduler_summary_for_job(job: Dict[str, Any]) -> Dict[str, Any]:
    summary = _load_job_summary(job)
    latest_task: Dict[str, Any] = {}
    for app_result in summary.get("apps_executed") or []:
        for task_result in app_result.get("tasks_executed") or []:
            if isinstance(task_result, dict):
                latest_task = task_result
    scheduler_used = str(latest_task.get("scheduler_used") or "")
    return {
        "schedulerUsed": scheduler_used,
        "schedulerLabel": "复用执行器" if scheduler_used == "old" else "探索 Agent" if scheduler_used == "new" else "",
        "similarityScore": latest_task.get("similarity_score"),
        "taskName": latest_task.get("task_description") or "",
        "runDir": latest_task.get("data_dir") or latest_task.get("run_dir") or "",
    }


def _current_action_for_job(job: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not job:
        return {
            "status": "idle",
            "action": "等待任务提交",
            "operation": "idle",
            "target": "",
            "source": "system",
            "jobId": "",
            "taskName": "",
            "timestamp": _now_iso(),
        }

    scheduler = _scheduler_summary_for_job(job)
    action: Optional[Dict[str, Any]] = None
    for run_dir in _run_dirs_for_job(job):
        action = _event_action_from_run_dir(run_dir)
        if action:
            break
    if not action:
        action = _last_action_from_logs(job)

    if not action:
        status = str(job.get("status") or "queued")
        action = {
            "action": "等待后端执行器启动" if status in {"queued", "running"} else "作业状态已更新",
            "operation": status,
            "target": status,
            "source": "job",
            "raw": status,
        }

    if job.get("status") == "succeeded" and action.get("operation") not in {"task_done", "save", "script"}:
        action = {**action, "action": "作业已完成", "operation": "completed", "target": scheduler.get("taskName") or action.get("target", "")}
    if job.get("status") == "failed":
        action = {**action, "action": "作业执行失败", "operation": "failed", "target": action.get("target", "")}

    return {
        "status": job.get("status") or "unknown",
        "action": action.get("action") or "",
        "operation": action.get("operation") or "",
        "target": action.get("target") or "",
        "source": action.get("source") or "runtime",
        "raw": action.get("raw") or "",
        "jobId": job.get("id") or "",
        "taskName": scheduler.get("taskName") or _first_task_name(_load_job_plan(job)),
        "schedulerUsed": scheduler.get("schedulerUsed") or "",
        "schedulerLabel": scheduler.get("schedulerLabel") or "",
        "similarityScore": scheduler.get("similarityScore"),
        "runDir": scheduler.get("runDir") or "",
        "timestamp": job.get("finishedAt") or job.get("startedAt") or job.get("createdAt") or _now_iso(),
    }


def _first_task_name(plan: Dict[str, Any]) -> str:
    for app_plan in plan.get("forensic_plan") or []:
        for task in app_plan.get("tasks") or []:
            if isinstance(task, dict) and task.get("task_description"):
                return str(task.get("task_description"))
    return ""


def _workspace_state(include_screenshot: bool = True, device_serial: str = "") -> Dict[str, Any]:
    devices = _collect_devices()
    selected_device = next((item for item in devices if item.get("serial") == device_serial), None) if device_serial else None
    if not selected_device:
        selected_device = next((item for item in devices if item.get("status") == "connected"), None) or (devices[0] if devices else None)
    selected_serial = str(selected_device.get("serial") or "") if selected_device else ""
    latest_job = _latest_job_for_workspace()
    subtasks_payload = _subtasks_for_job(latest_job) if latest_job else {"source": "none", "planSummary": "", "subtasks": []}
    execution_mode = str(latest_job.get("executionMode") or "") if latest_job else ""
    if not execution_mode and latest_job:
        execution_mode = "quick" if subtasks_payload["source"] == "quick" else "planned"
    live_screenshot = _capture_live_screenshot(selected_serial) if include_screenshot else {"ok": False, "serial": selected_serial, "error": "screenshot not requested"}
    return {
        "devices": devices,
        "selectedDevice": selected_device,
        "latestJob": latest_job,
        "executionMode": execution_mode,
        "subtaskSource": subtasks_payload["source"],
        "planSummary": subtasks_payload["planSummary"],
        "subtasks": subtasks_payload["subtasks"],
        "currentAction": _current_action_for_job(latest_job),
        "liveScreenshot": live_screenshot,
        "evidence": _collect_evidence(limit=20),
        "auditSessions": _collect_audit_sessions(limit=8),
    }


def _collect_audit_sessions(limit: int = 40) -> List[Dict[str, Any]]:
    sessions: List[Dict[str, Any]] = []
    chain_files = []
    event_files = []
    for root in [DATA_DIR / "codex_mobile_agent_runs", DATA_DIR / "page_agent_mobile_runs", DATA_DIR / "devices", WEB_API_DIR]:
        if root.exists():
            chain_files.extend(root.rglob("evidence_chain.jsonl"))
            event_files.extend(root.rglob("events.jsonl"))
    for chain_path in sorted(chain_files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]:
        steps = []
        for line in chain_path.read_text(encoding="utf-8", errors="replace").splitlines()[:80]:
            try:
                event = json.loads(line)
            except Exception:
                continue
            steps.append(
                {
                    "step": int(event.get("sequence") or len(steps) + 1),
                    "action": event.get("event_type") or "integrity_event",
                    "hash": str(event.get("event_hash") or "")[:16],
                    "timestamp": str(event.get("timestamp") or ""),
                    "result": json.dumps(event.get("payload") or {}, ensure_ascii=False)[:220],
                }
            )
        if steps:
            run_dir = chain_path.parent
            sessions.append(
                {
                    "caseId": run_dir.name,
                    "caseName": "证据完整性链",
                    "deviceSerial": _device_serial_from_path(run_dir) or "-",
                    "deviceModel": _device_serial_from_path(run_dir) or "runtime",
                    "startedAt": steps[0]["timestamp"],
                    "status": "completed",
                    "steps": steps,
                    "runDir": _safe_rel_path(run_dir),
                }
            )
    for event_path in sorted(event_files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]:
        steps = []
        for index, line in enumerate(event_path.read_text(encoding="utf-8", errors="replace").splitlines()[:60], 1):
            try:
                event = json.loads(line)
            except Exception:
                continue
            event_type = event.get("type") or event.get("event") or event.get("name") or "runtime_event"
            steps.append(
                {
                    "step": index,
                    "action": str(event_type),
                    "hash": _sha256_text(line)[:16],
                    "timestamp": str(event.get("timestamp") or event.get("time") or ""),
                    "modelOutput": json.dumps(event.get("data") or event, ensure_ascii=False, default=str)[:260],
                }
            )
        if steps:
            run_dir = event_path.parent
            sessions.append(
                {
                    "caseId": run_dir.name,
                    "caseName": "Agent 运行事件",
                    "deviceSerial": _device_serial_from_path(run_dir) or "-",
                    "deviceModel": _device_serial_from_path(run_dir) or "runtime",
                    "startedAt": steps[0]["timestamp"] or dt.datetime.fromtimestamp(event_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "running" if not (run_dir / "final.json").exists() else "completed",
                    "steps": steps,
                    "runDir": _safe_rel_path(run_dir),
                }
            )
    sessions.sort(key=lambda item: item.get("startedAt") or "", reverse=True)
    return sessions[:limit]


def _collect_screenshots(limit: int = 40) -> List[Dict[str, Any]]:
    roots = [DATA_DIR / "codex_mobile_agent_runs", DATA_DIR / "page_agent_mobile_runs", DATA_DIR / "devices", ARTIFACTS_DIR]
    files: List[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for suffix in ["*.png", "*.jpg", "*.jpeg"]:
            try:
                files.extend(root.rglob(suffix))
            except Exception:
                pass
    files = [path for path in files if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [
        {
            "path": _safe_rel_path(path),
            "url": _file_url(path),
            "name": path.name,
            "mtime": dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "runDir": _safe_rel_path(path.parent),
        }
        for path in files[:limit]
    ]


@app.get("/api/health")
def health() -> Dict[str, Any]:
    adb_ok, adb_devices, adb_error = _run_adb_devices()
    evidence = _collect_evidence(limit=1)
    return {
        "ok": True,
        "repoRoot": str(REPO_ROOT),
        "python": platform.python_version(),
        "adb": {"ok": adb_ok, "devices": adb_devices, "error": adb_error},
        "llmConfigured": _llm_configured(),
        "dataDirExists": DATA_DIR.exists(),
        "evidenceAvailable": bool(evidence),
        "capabilities": [
            "device_status",
            "live_device_screenshot",
            "app_mapping",
            "plan_generation_with_llm_or_fallback",
            "quick_task_direct_scheduler",
            "real_cli_task_start",
            "workspace_state",
            "current_action_from_runtime",
            "runtime_logs",
            "screenshots",
            "evidence_records",
            "audit_events",
            "json_report_download",
        ],
    }


@app.get("/api/dashboard")
def dashboard() -> Dict[str, Any]:
    devices = _collect_devices()
    evidence = _collect_evidence(limit=200)
    jobs = _load_jobs()
    audit = _collect_audit_sessions(limit=8)
    return {
        "devices": devices,
        "metrics": {
            "connectedDevices": sum(1 for item in devices if item.get("status") == "connected"),
            "knownDevices": len(devices),
            "evidenceItems": len(evidence),
            "auditSessions": len(audit),
            "runningJobs": sum(1 for item in jobs if item.get("status") == "running"),
        },
        "recentEvidence": evidence[:8],
        "recentJobs": jobs[:8],
        "auditSessions": audit[:4],
        "screenshots": _collect_screenshots(limit=5),
    }


@app.get("/api/devices")
def devices() -> Dict[str, Any]:
    return {"devices": _collect_devices()}


@app.get("/api/apps")
def apps(device_serial: str = "") -> Dict[str, Any]:
    return {"apps": _load_apps(device_serial)}


@app.get("/api/device/live-screenshot")
def live_screenshot(device_serial: str = "") -> Dict[str, Any]:
    result = _capture_live_screenshot(device_serial)
    return {"screenshot": result}


@app.get("/api/current-action")
def current_action() -> Dict[str, Any]:
    return {"currentAction": _current_action_for_job(_latest_job_for_workspace())}


@app.get("/api/workspace-state")
def workspace_state(include_screenshot: bool = True, device_serial: str = "") -> Dict[str, Any]:
    return _workspace_state(include_screenshot=include_screenshot, device_serial=device_serial)


@app.post("/api/plans")
def create_plan(request: PlanRequest) -> Dict[str, Any]:
    warnings: List[str] = []
    apps_for_fallback = _load_apps(request.device_serial)
    source = "llm"
    plan: Dict[str, Any]
    try:
        from runner.forensiflow.core.config import get_llm_config
        from runner.forensiflow.core.forensic_planner import ForensicPlanner

        llm_config = get_llm_config()
        planner = ForensicPlanner(
            api_key=llm_config.api_key,
            base_url=llm_config.api_base,
            model=llm_config.model,
            data_dir=str(DATA_DIR / "devices" / request.device_serial) if request.device_serial else str(DATA_DIR),
        )
        mapping_file = DATA_DIR / "devices" / request.device_serial / "app_info" / "package_name_mapping.txt" if request.device_serial else None
        plan = planner.create_forensic_plan(
            case_background=request.case_background or request.case_name,
            forensic_goals=request.forensic_goals,
            app_mapping_file=str(mapping_file) if mapping_file and mapping_file.exists() else None,
        )
    except Exception as exc:
        if not request.allow_fallback:
            raise HTTPException(status_code=503, detail=f"LLM planning unavailable: {exc}") from exc
        source = "fallback"
        warnings.append(f"LLM 规划不可用，已生成本地安全预览规划: {type(exc).__name__}: {exc}")
        plan = _fallback_plan(request, apps_for_fallback)

    plan_id = uuid.uuid4().hex
    plan_path = PLANS_DIR / f"forensic_plan_{plan_id}.json"
    _json_dump(plan_path, plan)
    return {"ok": True, "source": source, "warnings": warnings, "plan": plan, "planPath": _safe_rel_path(plan_path)}


@app.post("/api/tasks/start")
def start_task(request: StartTaskRequest) -> Dict[str, Any]:
    job = _create_task_job(
        plan=request.plan,
        device_serial=request.device_serial,
        app_name=request.app_name,
        task_index=request.task_index,
        threshold=request.threshold,
        execution_mode=request.execution_mode,
        case_name=request.case_name,
    )
    return {"ok": True, "job": job}


@app.post("/api/tasks/quick")
def start_quick_task(request: QuickTaskRequest) -> Dict[str, Any]:
    if not request.task_description.strip():
        raise HTTPException(status_code=400, detail="task_description is required")
    package_name = request.package_name or _package_for_app(request.app_name, request.device_serial)
    plan = {
        "case_analysis_summary": "快速取证任务：绕过案件规划层，将单个任务直接提交给调度器选择复用执行或探索 Agent。",
        "forensic_plan": [
            {
                "app_name": request.app_name,
                "package_name": package_name,
                "tasks": [
                    {
                        "task_level": request.task_level,
                        "task_type": request.task_type,
                        "task_description": request.task_description.strip(),
                        "target_objects": [],
                        "constraint": request.constraint,
                    }
                ],
            }
        ],
    }
    job = _create_task_job(
        plan=plan,
        device_serial=request.device_serial,
        app_name=request.app_name,
        task_index=None,
        threshold=request.threshold,
        execution_mode="quick",
        case_name=request.case_name,
    )
    return {"ok": True, "job": job}


@app.get("/api/jobs")
def jobs() -> Dict[str, Any]:
    return {"jobs": _load_jobs()}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> Dict[str, Any]:
    for job in _load_jobs():
        if job.get("id") == job_id:
            return {"job": job, "logs": {"stdout": _read_log_tail(job.get("stdoutPath", "")), "stderr": _read_log_tail(job.get("stderrPath", ""))}}
    raise HTTPException(status_code=404, detail="job not found")


@app.get("/api/evidence")
def evidence(limit: int = Query(default=200, ge=1, le=1000)) -> Dict[str, Any]:
    return {"evidence": _collect_evidence(limit=limit)}


@app.get("/api/audit")
def audit(limit: int = Query(default=40, ge=1, le=120)) -> Dict[str, Any]:
    return {"sessions": _collect_audit_sessions(limit=limit)}


@app.get("/api/screenshots")
def screenshots(limit: int = Query(default=40, ge=1, le=120)) -> Dict[str, Any]:
    return {"screenshots": _collect_screenshots(limit=limit)}


@app.get("/api/files")
def files(path: str) -> FileResponse:
    return FileResponse(_resolve_allowed_file(path))


@app.post("/api/reports")
def create_report(request: ReportRequest) -> Dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "title": request.title,
        "createdAt": _now_iso(),
        "runDir": request.run_dir,
        "devices": _collect_devices(),
        "evidence": _collect_evidence(limit=300),
        "auditSessions": _collect_audit_sessions(limit=60),
        "jobs": _load_jobs()[:20],
    }
    filename = f"forensiflow_report_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = REPORTS_DIR / filename
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"ok": True, "reportPath": _safe_rel_path(path), "downloadUrl": f"/api/reports/{filename}", "summary": {"evidenceItems": len(report["evidence"]), "auditSessions": len(report["auditSessions"])}}


@app.get("/api/reports/{filename}")
def download_report(filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid report filename")
    path = REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="report not found")
    return FileResponse(path, media_type="application/json", filename=filename)


def main() -> int:
    parser = argparse.ArgumentParser(description="ForensiFlow web frontend API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
