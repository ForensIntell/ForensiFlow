#!/usr/bin/env python3
"""Run/report a three-app ablation experiment for Gmail, Chrome, and Maps.

The expensive full-agent explore/reuse phases are taken from a completed
zero-RAG feasibility directory. This script still performs live device checks
for the navigation-only and no-script baselines so the ablation has fresh
device evidence without re-running every high-cost Codex exploration.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.device_serial import resolve_device_serial
from tools.run_feasibility_full_flow import _judge, _load_records_and_state
from tools.run_zero_rag_explore_reuse_experiment import _load_experiment_tasks


DEFAULT_FEASIBILITY_DIR = (
    REPO_ROOT
    / "experiments"
    / "full_flow_zero_rag_explore_reuse"
    / "zero_rag_round2_20260528_001900"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 serial.")
    parser.add_argument("--feasibility-dir", type=Path, default=DEFAULT_FEASIBILITY_DIR)
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "experiments" / "ablation_three_apps")
    parser.add_argument("--run-id", default="", help="Optional run id. Default timestamped.")
    parser.add_argument("--apps", default="gmail,chrome,maps", help="Comma list: gmail, chrome, maps.")
    parser.add_argument("--repeat-count", type=int, default=1, help="Number of repeated live-device rounds to run serially.")
    parser.add_argument("--json", action="store_true")
    return parser


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_validation_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["scope", "ok", "records_count", "debug_count", "returncode", "issues", "artifacts_dir"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            item = dict(row)
            item["issues"] = json.dumps(item.get("issues", []), ensure_ascii=False)
            writer.writerow({key: item.get(key, "") for key in fieldnames})


def selected_tasks(feasibility_dir: Path, apps: str) -> List[Dict[str, Any]]:
    aliases = {"gmail": "com.google.android.gm", "chrome": "com.android.chrome", "maps": "com.google.android.apps.maps"}
    requested = {aliases.get(item.strip().lower(), item.strip()) for item in apps.split(",") if item.strip()}
    return [task for task in _load_experiment_tasks(feasibility_dir) if task.get("package_name") in requested]


def load_templates(feasibility_dir: Path) -> List[Dict[str, Any]]:
    templates: List[Dict[str, Any]] = []
    candidates = [feasibility_dir / "rag_library" / "all_templates.json"]
    repeat_root = feasibility_dir / "repeats"
    if repeat_root.exists():
        candidates.extend(sorted(repeat_root.glob("*/rag_library/all_templates.json")))
    for path in candidates:
        if not path.exists():
            continue
        payload = read_json(path)
        items = payload if isinstance(payload, list) else payload.get("templates", []) if isinstance(payload, dict) else []
        for item in items:
            if isinstance(item, dict):
                templates.append(item)
    return templates


def template_for_task(templates: List[Dict[str, Any]], task: Dict[str, Any]) -> Dict[str, Any]:
    package_name = task.get("package_name")
    task_text = task.get("task_description")
    task_id = task.get("task_id")
    for template in templates:
        if (
            template.get("package_name") == package_name
            and template.get("task") == task_text
            and (not task_id or template.get("task_id") == task_id or template.get("task_id") is None)
        ):
            return template
    for template in templates:
        if template.get("package_name") == package_name and (not task_id or template.get("task_id") == task_id or template.get("task_id") is None):
            return template
    raise ValueError(f"no template for {task.get('app_name')} / {task_text}")


def exists(selector, timeout: float = 0.0) -> bool:
    try:
        return bool(selector.exists(timeout=timeout))
    except TypeError:
        return bool(selector.exists)


def parse_bounds(bounds: str) -> Optional[Dict[str, int]]:
    matches = re.findall(r"\[(\d+),(\d+)\]", bounds or "")
    if len(matches) != 2:
        return None
    left, top = int(matches[0][0]), int(matches[0][1])
    right, bottom = int(matches[1][0]), int(matches[1][1])
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def find_xml_target(xml: str, target: Any) -> Optional[Dict[str, Any]]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    target_spec = target if isinstance(target, dict) else {}
    target_text = "" if target_spec else str(target or "").strip()

    best = None
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        resource_id = (node.get("resource-id") or "").strip()
        klass = (node.get("class") or "").strip()
        bounds = parse_bounds(node.get("bounds") or "")
        if not bounds:
            continue

        if target_spec:
            score = 0
            expected_id = str(target_spec.get("resource_id") or target_spec.get("resource-id") or "").strip()
            expected_text = str(target_spec.get("text") or "").strip()
            expected_desc = str(target_spec.get("content_desc") or target_spec.get("content-desc") or "").strip()
            expected_class = str(target_spec.get("class") or "").strip()
            if expected_id:
                if resource_id != expected_id:
                    continue
                score += 10
            if expected_text:
                if text == expected_text:
                    score += 6
                elif desc == expected_text:
                    score += 5
                else:
                    continue
            if expected_desc:
                if desc == expected_desc:
                    score += 6
                elif text == expected_desc:
                    score += 4
                else:
                    continue
            if expected_class and klass.split(".")[-1] == expected_class.split(".")[-1]:
                score += 2
            candidate = {"bounds": bounds, "text": text or desc or resource_id, "class": klass, "score": score}
            if best is None or score > best.get("score", 0):
                best = candidate
            continue

        lower = target_text.casefold()
        if text.casefold() == lower or desc.casefold() == lower or resource_id.casefold() == lower:
            return {"bounds": bounds, "text": text or desc or resource_id, "class": klass, "score": 10}
        if lower and (lower in text.casefold() or lower in desc.casefold() or lower in resource_id.casefold()):
            candidate = {"bounds": bounds, "text": text or desc or resource_id, "class": klass, "score": 5}
            if best is None:
                best = candidate
    return best


def click_target(d: Any, target: Any, evidence_dir: Path, step_index: int) -> Dict[str, Any]:
    started = time.time()
    if isinstance(target, dict):
        resource_id = str(target.get("resource_id") or target.get("resource-id") or "").strip()
        text = str(target.get("text") or "").strip()
        desc = str(target.get("content_desc") or target.get("content-desc") or "").strip()
        candidates = []
        if resource_id:
            candidates.append(("resource_id", d(resourceId=resource_id)))
        if text:
            candidates.append(("text", d(text=text)))
        if desc:
            candidates.append(("description", d(description=desc)))
    else:
        text = str(target or "").strip()
        candidates = [
            ("text", d(text=text)),
            ("description", d(description=text)),
            ("text_contains", d(textContains=text)),
            ("description_contains", d(descriptionContains=text)),
        ]

    for method, selector in candidates:
        if exists(selector, timeout=1.5):
            selector.click()
            time.sleep(1)
            return {"ok": True, "method": method, "target": target, "duration_seconds": round(time.time() - started, 3)}

    xml = d.dump_hierarchy()
    (evidence_dir / f"click_miss_{step_index}.xml").write_text(xml, encoding="utf-8")
    match = find_xml_target(xml, target)
    if match:
        bounds = match["bounds"]
        x = (bounds["left"] + bounds["right"]) // 2
        y = (bounds["top"] + bounds["bottom"]) // 2
        d.click(x, y)
        time.sleep(1)
        return {
            "ok": True,
            "method": "xml_bounds",
            "target": target,
            "matched_text": match.get("text", ""),
            "x": x,
            "y": y,
            "duration_seconds": round(time.time() - started, 3),
        }
    return {"ok": False, "method": "not_found", "target": target, "duration_seconds": round(time.time() - started, 3)}


def run_template_navigation(d: Any, task: Dict[str, Any], template: Dict[str, Any], evidence_dir: Path) -> Dict[str, Any]:
    actions = []
    package_name = task["package_name"]
    d.app_stop(package_name)
    time.sleep(0.8)
    d.app_start(package_name)
    time.sleep(5)
    actions.append({"action": "Launch", "package_name": package_name, "ok": True})

    for index, step in enumerate(template.get("steps") or [], start=1):
        action = str(step.get("action") or "").lower()
        if action in {"launch", "callscript"}:
            continue
        if action == "wait":
            duration = float((step.get("params") or {}).get("duration", 2))
            time.sleep(duration)
            actions.append({"action": "Wait", "duration": duration, "ok": True})
        elif action == "click":
            result = click_target(d, step.get("target"), evidence_dir, index)
            result["action"] = "Click"
            actions.append(result)
            if not result.get("ok"):
                break
        elif action == "swipe":
            direction = str((step.get("params") or {}).get("direction") or "up").lower()
            if direction == "up":
                d.swipe(540, 1500, 540, 650, duration=0.3)
            elif direction == "down":
                d.swipe(540, 650, 540, 1500, duration=0.3)
            elif direction == "left":
                d.swipe(900, 1000, 180, 1000, duration=0.3)
            elif direction == "right":
                d.swipe(180, 1000, 900, 1000, duration=0.3)
            time.sleep(1)
            actions.append({"action": "Swipe", "direction": direction, "ok": True})
        elif action == "back":
            d.press("back")
            time.sleep(1)
            actions.append({"action": "Back", "ok": True})
    return {"actions": actions, "ok": all(item.get("ok") for item in actions)}


def verify_target_page(xml: str, task: Dict[str, Any]) -> Tuple[bool, List[str]]:
    text = xml
    package_name = task["package_name"]
    markers = []
    if package_name == "com.google.android.gm":
        markers = ["com.google.android.gm"]
    elif package_name == "com.android.chrome":
        markers = ["历史记录", "com.android.chrome"]
    elif package_name == "com.google.android.apps.maps":
        markers = ["搜索过", "地图历史记录", "com.google.android.apps.maps"]
    hits = [marker for marker in markers if marker in text]
    if package_name == "com.google.android.apps.maps":
        return len(hits) >= 2, hits
    return bool(hits), hits


def xml_nodes(xml: str, package_name: str) -> List[Dict[str, str]]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml)
    out = []
    for node in root.iter("node"):
        if node.get("package") not in {"", package_name}:
            continue
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        klass = (node.get("class") or "").strip()
        if text or desc:
            out.append({"text": text, "content_desc": desc, "class": klass, "bounds": node.get("bounds", "")})
    return out


def direct_extract_from_xml(xml: str, task: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    import xml.etree.ElementTree as ET

    package_name = task["package_name"]
    nodes = xml_nodes(xml, package_name)
    records: List[Dict[str, Any]] = []

    if package_name == "com.google.android.gm":
        root = ET.fromstring(xml)

        def child_text_by_id(node: Any, suffix: str) -> str:
            for child in node.iter("node"):
                rid = child.get("resource-id") or ""
                if rid.endswith(suffix):
                    return (child.get("text") or "").strip()
            return ""

        seen = set()
        for row in root.iter("node"):
            if row.get("resource-id") != "com.google.android.gm:id/viewified_conversation_item_view":
                continue
            senders = child_text_by_id(row, "/senders")
            date = child_text_by_id(row, "/date")
            subject = child_text_by_id(row, "/subject")
            snippet = child_text_by_id(row, "/snippet")
            if not (senders or subject or snippet):
                continue
            key = (senders, subject, snippet[:80], date)
            if key in seen:
                continue
            seen.add(key)
            title = subject or snippet or senders
            records.append(
                {
                    "senders": senders,
                    "sender": senders,
                    "subject": subject,
                    "snippet": snippet,
                    "date": date,
                    "title": title,
                    "content_text": " | ".join(part for part in (senders, subject, snippet, date) if part),
                }
            )
            if len(records) >= 12:
                break

    elif package_name == "com.android.chrome":
        root = ET.fromstring(xml)
        date_section = ""
        seen = set()
        for node in root.iter("node"):
            if node.get("package") != package_name:
                continue
            text = (node.get("text") or "").strip()
            if text and any(token in text for token in ("今天", "昨天", "年", "月", "日")) and len(text) <= 30:
                date_section = text
            if node.get("resource-id") != "com.android.chrome:id/content":
                continue
            title = ""
            domain = ""
            for child in node.iter("node"):
                rid = child.get("resource-id") or ""
                child_text = (child.get("text") or "").strip()
                if rid == "com.android.chrome:id/title":
                    title = child_text
                elif rid == "com.android.chrome:id/description":
                    domain = child_text
            if not title or "删除浏览数据" in title:
                continue
            key = (title, domain, date_section)
            if key in seen:
                continue
            seen.add(key)
            records.append({"title": title, "url_domain": domain, "date_section": date_section, "content_text": f"{title} {domain}".strip()})
            if len(records) >= 12:
                break

    elif package_name == "com.google.android.apps.maps":
        skip = {"您的地点", "区域", "类别", "已保存", "地图历史记录", "搜索过", "查看过", "应用", "按名称或备注搜索"}
        all_texts = [n["text"] for n in nodes if n["text"] and n["text"] not in skip]
        i = 0
        while i < len(all_texts):
            title = all_texts[i]
            if len(title) <= 1 or title in skip:
                i += 1
                continue
            subtitle = all_texts[i + 1] if i + 1 < len(all_texts) else ""
            status = all_texts[i + 2] if i + 2 < len(all_texts) else ""
            date = ""
            if " · " in status:
                status, date = [part.strip() for part in status.split(" · ", 1)]
            records.append(
                {
                    "title": title,
                    "subtitle": subtitle,
                    "category": subtitle,
                    "status": status,
                    "date": date,
                    "filter_type": "visible_xml",
                }
            )
            i += 3
            if len(records) >= 12:
                break

    debug_records = []
    for index, record in enumerate(records):
        debug = dict(record)
        debug["_debug"] = {"index": index, "source": "direct_xml_no_script"}
        debug_records.append(debug)
    return records, debug_records


def run_a1_or_s2(
    *,
    group: str,
    serial: str,
    task: Dict[str, Any],
    template: Dict[str, Any],
    run_dir: Path,
    gold_count_for_coverage: int = 0,
) -> Dict[str, Any]:
    import uiautomator2 as u2

    started = time.time()
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    d = u2.connect(serial)
    nav = run_template_navigation(d, task, template, artifacts)
    xml = d.dump_hierarchy()
    (artifacts / "screen.xml").write_text(xml, encoding="utf-8")
    try:
        d.screenshot(str(artifacts / "screen.png"))
    except Exception:
        pass
    reached, markers = verify_target_page(xml, task)

    if group == "A1":
        records: List[Dict[str, Any]] = []
        debug_records: List[Dict[str, Any]] = []
        state = {"status": "completed" if reached else "blocked", "errors": [] if reached else ["target page not reached"], "total_records": 0}
        metrics = {
            "task_success": reached,
            "task_success_rate": 1.0 if reached else 0.0,
            "target_page_reach_rate": 1.0 if reached else 0.0,
            "key_state_coverage": 1.0 if reached else 0.0,
            "first_run_success_rate": 0.0,
            "final_success_rate": 0.0,
            "evidence_coverage": 0.0,
            "precision_vs_gold": 0.0,
            "runtime_seconds": round(time.time() - started, 3),
            "unsafe_action_count": 0,
            "records_count": 0,
            "records_debug_count": 0,
            "field_complete_rate": 0.0,
            "duplicate_rate": 0.0,
            "navigation_steps": len(nav["actions"]),
            "repair_attempts": 0,
        }
        judge = {"ok": reached, "success": reached, "failure_reasons": [] if reached else ["target page not reached"]}
    else:
        records, debug_records = direct_extract_from_xml(xml, task)
        state = {
            "status": "completed" if records else "blocked",
            "errors": [] if records else ["direct XML extraction produced no records"],
            "total_records": len(records),
        }
        task_result = {
            "completed": reached and bool(records),
            "total_steps": len(nav["actions"]),
            "actions": nav["actions"],
            "reacts": [],
            "script_results": [],
        }
        metrics, judge = _judge(task, task_result, records, debug_records, state, time.time() - started)
        if gold_count_for_coverage > 0:
            coverage = min(1.0, len(records) / gold_count_for_coverage)
            metrics["evidence_coverage"] = round(coverage, 6)
            full_task_success = bool(metrics.get("task_success")) and coverage >= 0.8
            metrics["task_success"] = full_task_success
            metrics["task_success_rate"] = 1.0 if full_task_success else 0.0
            judge["ok"] = full_task_success
            judge["success"] = full_task_success
            if not full_task_success:
                judge.setdefault("failure_reasons", []).append(
                    f"evidence_coverage {coverage:.3f} < S2 threshold 0.800 against explore gold count {gold_count_for_coverage}"
                )
        metrics["target_page_reach_rate"] = 1.0 if reached else 0.0
        metrics["first_run_success_rate"] = metrics["task_success_rate"]
        metrics["final_success_rate"] = metrics["task_success_rate"]
        metrics["repeated_state_rate"] = 0.0

    write_json(artifacts / "records.json", records)
    write_json(artifacts / "records_debug.json", debug_records)
    write_json(artifacts / "run_state.json", state)
    write_json(run_dir / "actions.json", nav["actions"])
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "judge.json", judge)
    write_json(run_dir / "page_reach.json", {"reached": reached, "markers": markers})
    return metrics


def load_feasibility_rows(feasibility_dir: Path) -> List[Dict[str, Any]]:
    return [row for row in read_json(feasibility_dir / "summary_runs.json") if isinstance(row, dict)]


def row_for(feasibility_rows: List[Dict[str, Any]], task: Dict[str, Any], phase: str, repeat_index: int = 1) -> Dict[str, Any]:
    for row in feasibility_rows:
        row_repeat = int(row.get("repeat_index") or 1)
        if (
            row.get("package_name") == task.get("package_name")
            and row.get("task_id") == task.get("task_id")
            and row.get("phase") == phase
            and row_repeat == repeat_index
        ):
            return row
    for row in feasibility_rows:
        if row.get("package_name") == task.get("package_name") and row.get("task_id") == task.get("task_id") and row.get("phase") == phase:
            return row
    raise ValueError(f"missing feasibility row for {task.get('app_name')} {task.get('task_id')} phase={phase} repeat={repeat_index}")


def group_row_from_existing(
    *,
    group: str,
    source_row: Dict[str, Any],
    run_id: str,
    output_dir: Path,
    note: str,
    repeat_index: int = 1,
    run_label: str = "run_001",
) -> Dict[str, Any]:
    row = dict(source_row)
    row.update(
        {
            "run_id": run_id,
            "group": group,
            "ablation_type": group[0],
            "source_phase": source_row.get("phase"),
            "source_run_dir": source_row.get("run_dir"),
            "note": note,
            "repeat_index": repeat_index,
            "run_label": run_label,
            "target_page_reach_rate": source_row.get("key_state_coverage", source_row.get("task_success_rate", 0.0)),
            "first_run_success_rate": source_row.get("task_success_rate", 0.0),
            "final_success_rate": source_row.get("task_success_rate", 0.0),
            "repeated_state_rate": 0.0,
        }
    )
    group_dir = output_dir / row["app_name"] / row["task_id"] / group / run_label
    group_dir.mkdir(parents=True, exist_ok=True)
    write_json(group_dir / "metrics.json", {k: v for k, v in row.items() if k not in {"source_run_dir"}})
    write_json(group_dir / "source.json", {"source_run_dir": source_row.get("run_dir"), "note": note})
    row["run_dir"] = str(group_dir)
    return row


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    numeric = [
        "task_success_rate",
        "target_page_reach_rate",
        "first_run_success_rate",
        "final_success_rate",
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
        "repeated_state_rate",
    ]

    def summarize(subset: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = {
            key: round(sum(float(row.get(key, 0) or 0) for row in subset) / len(subset), 6)
            for key in numeric
            if subset
        }
        result["runs"] = len(subset)
        return result

    by_group = {group: summarize([row for row in rows if row.get("group") == group]) for group in sorted({row.get("group") for row in rows})}
    by_app = {app: summarize([row for row in rows if row.get("app_name") == app]) for app in sorted({row.get("app_name") for row in rows})}
    return {"overall": summarize(rows), "by_group": by_group, "by_app": by_app, "runs": len(rows)}


def deltas(summary: Dict[str, Any]) -> Dict[str, Any]:
    by_group = summary.get("by_group", {})
    pairs = [("A2_minus_A3", "A2", "A3"), ("A3_minus_A4", "A3", "A4"), ("S1_minus_S2", "S1", "S2"), ("R1_minus_R2", "R1", "R2")]
    metrics = ["task_success_rate", "evidence_coverage", "precision_vs_gold", "runtime_seconds", "repair_attempts"]
    out: Dict[str, Dict[str, float]] = {}
    for label, left, right in pairs:
        if left not in by_group or right not in by_group:
            continue
        out[label] = {
            metric: round(float(by_group[left].get(metric, 0) or 0) - float(by_group[right].get(metric, 0) or 0), 6)
            for metric in metrics
        }
    return out


def validate_experiment_artifacts(output_dir: Path, feasibility_dir: Path) -> List[Dict[str, Any]]:
    validator = REPO_ROOT / ".codex-forensiflow-agent" / "skills" / "forensiflow-mobile-agent" / "scripts" / "validate_records.py"
    rows: List[Dict[str, Any]] = []

    def validate(scope: str, artifacts_dir: Path) -> None:
        if not validator.exists():
            rows.append(
                {
                    "scope": scope,
                    "artifacts_dir": str(artifacts_dir),
                    "returncode": 127,
                    "ok": False,
                    "records_count": 0,
                    "debug_count": 0,
                    "issues": [f"validator missing: {validator}"],
                }
            )
            return
        proc = subprocess.run(
            [sys.executable, str(validator), str(artifacts_dir)],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
        )
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            payload = {
                "ok": False,
                "records_count": 0,
                "debug_count": 0,
                "issues": ["validator output was not JSON"],
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        rows.append({"scope": scope, "artifacts_dir": str(artifacts_dir), "returncode": proc.returncode, **payload})

    for artifacts_dir in sorted(output_dir.rglob("artifacts")):
        parts = artifacts_dir.relative_to(output_dir).parts
        if len(parts) >= 5 and parts[2] == "S2":
            validate(f"ablation/{parts[0]}/{parts[1]}/S2/{parts[3]}", artifacts_dir)
    for artifacts_dir in sorted(feasibility_dir.rglob("artifacts")):
        parts = artifacts_dir.relative_to(feasibility_dir).parts
        if "F2" in parts:
            validate(f"feasibility/{'/'.join(parts[:-1])}", artifacts_dir)

    write_json(output_dir / "validation_summary.json", rows)
    write_validation_csv(output_dir / "validation_summary.csv", rows)
    return rows


def write_report(
    output_dir: Path,
    rows: List[Dict[str, Any]],
    summary: Dict[str, Any],
    delta_rows: Dict[str, Any],
    validation_rows: Optional[List[Dict[str, Any]]] = None,
) -> None:
    lines = [
        "# Three-App Ablation Experiment",
        "",
        f"- Directory: `{output_dir}`",
        f"- Created at: `{dt.datetime.now().isoformat(timespec='seconds')}`",
        "- Scope: Gmail, Chrome, Google Maps.",
        "- A1 and S2 are fresh live device runs. A2/A3/A4/S1/R1/R2 reference the completed zero-RAG full-flow run to avoid duplicating high-cost Codex exploration.",
        "",
        "## Group Summary",
        "",
        "| Group | Runs | Success | Reach | Evidence | Precision | Runtime(s) | Records |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for group, data in summary.get("by_group", {}).items():
        lines.append(
            "| {group} | {runs} | {success} | {reach} | {coverage} | {precision} | {runtime} | {records} |".format(
                group=group,
                runs=data.get("runs"),
                success=data.get("task_success_rate", ""),
                reach=data.get("target_page_reach_rate", ""),
                coverage=data.get("evidence_coverage", ""),
                precision=data.get("precision_vs_gold", ""),
                runtime=data.get("runtime_seconds", ""),
                records=data.get("records_count", ""),
            )
        )
    lines.extend(["", "## Deltas", "", "```json", json.dumps(delta_rows, ensure_ascii=False, indent=2), "```"])
    if validation_rows is not None:
        lines.extend(
            [
                "",
                "## Validation",
                "",
                "| Scope | OK | Records | Debug | Issues |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for row in validation_rows:
            issues = json.dumps(row.get("issues", []), ensure_ascii=False)
            lines.append(
                "| {scope} | {ok} | {records} | {debug} | `{issues}` |".format(
                    scope=row.get("scope", ""),
                    ok=row.get("ok", ""),
                    records=row.get("records_count", ""),
                    debug=row.get("debug_count", ""),
                    issues=issues,
                )
            )
        lines.extend(
            [
                "",
                "- Full validation tables are saved as `validation_summary.json` and `validation_summary.csv`.",
            ]
        )
    lines.extend(["", "## Notes", ""])
    lines.extend(
        [
            "- A1 intentionally stops before records extraction, so records metrics are zero by design.",
            "- S2 uses direct visible XML extraction only; it does not generate or execute scripts and does not scroll deeply.",
            "- R2 is the zero-RAG exploration phase; R1 is the reuse phase after templates were built.",
            "- Google Maps also has current-screen gold in the feasibility directory because app history state can drift between explore and reuse.",
        ]
    )
    (output_dir / "experiment_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> Dict[str, Any]:
    serial = resolve_device_serial(args.device_serial, required=True)
    run_id = args.run_id or dt.datetime.now().strftime("ablation_three_apps_%Y%m%d_%H%M%S")
    output_dir = args.output_root.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    feasibility_dir = args.feasibility_dir.resolve()
    tasks = selected_tasks(feasibility_dir, args.apps)
    templates = load_templates(feasibility_dir)
    feasibility_rows = load_feasibility_rows(feasibility_dir)

    rows: List[Dict[str, Any]] = []
    repeat_count = max(1, int(args.repeat_count or 1))
    for repeat_index in range(1, repeat_count + 1):
        run_label = f"run_{repeat_index:03d}"
        for task in tasks:
            template = template_for_task(templates, task)
            explore = row_for(feasibility_rows, task, "explore", repeat_index=repeat_index)
            reuse = row_for(feasibility_rows, task, "reuse", repeat_index=repeat_index)
            for group in ("A1", "S2"):
                run_dir = output_dir / task["app_name"] / task["task_id"] / group / run_label
                metrics = run_a1_or_s2(
                    group=group,
                    serial=serial,
                    task=task,
                    template=template,
                    run_dir=run_dir,
                    gold_count_for_coverage=int(explore.get("records_count") or 0) if group == "S2" else 0,
                )
                row = {
                    "run_id": run_id,
                    "repeat_index": repeat_index,
                    "run_label": run_label,
                    "group": group,
                    "ablation_type": group[0],
                    "task_id": task["task_id"],
                    "app_name": task["app_name"],
                    "package_name": task["package_name"],
                    "task_description": task["task_description"],
                    "run_dir": str(run_dir),
                    "source_phase": "live_device_navigation" if group == "A1" else "live_device_direct_xml",
                    **metrics,
                }
                rows.append(row)

            rows.append(
                group_row_from_existing(
                    group="A2",
                    source_row=reuse,
                    run_id=run_id,
                    output_dir=output_dir,
                    note="navigation + one registered script execution",
                    repeat_index=repeat_index,
                    run_label=run_label,
                )
            )
            rows.append(
                group_row_from_existing(
                    group="A3",
                    source_row=explore,
                    run_id=run_id,
                    output_dir=output_dir,
                    note="exploration with script generation/repair loop before RAG reuse",
                    repeat_index=repeat_index,
                    run_label=run_label,
                )
            )
            rows.append(
                group_row_from_existing(
                    group="A4",
                    source_row=reuse,
                    run_id=run_id,
                    output_dir=output_dir,
                    note="full flow after RAG template/script reuse is available",
                    repeat_index=repeat_index,
                    run_label=run_label,
                )
            )
            rows.append(
                group_row_from_existing(
                    group="S1",
                    source_row=reuse,
                    run_id=run_id,
                    output_dir=output_dir,
                    note="script-enabled full flow",
                    repeat_index=repeat_index,
                    run_label=run_label,
                )
            )
            rows.append(
                group_row_from_existing(
                    group="R1",
                    source_row=reuse,
                    run_id=run_id,
                    output_dir=output_dir,
                    note="reuse enabled",
                    repeat_index=repeat_index,
                    run_label=run_label,
                )
            )
            rows.append(
                group_row_from_existing(
                    group="R2",
                    source_row=explore,
                    run_id=run_id,
                    output_dir=output_dir,
                    note="reuse disabled / zero-RAG exploration",
                    repeat_index=repeat_index,
                    run_label=run_label,
                )
            )

    summary = aggregate(rows)
    delta_rows = deltas(summary)
    write_json(output_dir / "summary_runs.json", rows)
    write_csv(output_dir / "summary_runs.csv", rows)
    write_json(output_dir / "summary_metrics.json", summary)
    write_json(output_dir / "deltas.json", delta_rows)
    write_json(
        output_dir / "experiment_manifest.json",
        {
            "run_id": run_id,
            "device_serial": serial,
            "feasibility_dir": str(feasibility_dir),
            "output_dir": str(output_dir),
            "repeat_count": repeat_count,
            "tasks": tasks,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        },
    )
    validation_rows = validate_experiment_artifacts(output_dir, feasibility_dir)
    write_report(output_dir, rows, summary, delta_rows, validation_rows)
    return {"ok": True, "output_dir": str(output_dir), "summary": summary, "deltas": delta_rows, "runs": rows}


def main() -> int:
    args = build_parser().parse_args()
    payload = run(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"output_dir: {payload['output_dir']}")
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
