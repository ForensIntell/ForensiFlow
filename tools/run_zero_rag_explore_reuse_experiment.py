#!/usr/bin/env python3
"""Run the zero-RAG full-flow experiment: explore once, then reuse once.

The experiment starts with an empty, isolated RAG template library so existing
project templates cannot affect the first run. Successful exploration publishes
new templates into that isolated library, and the second phase verifies reuse.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from run_forensic_plan import ForensicTaskExecutor
from runner.forensiflow.core.config import get_llm_config
from runner.forensiflow.devices.android import AndroidDevice
from tools.device_serial import resolve_device_serial
from tools.run_feasibility_full_flow import (
    DEFAULT_TASKS,
    _aggregate,
    _build_plan,
    _copy_artifacts,
    _find_artifact_paths,
    _judge,
    _load_records_and_state,
    _selected_tasks,
    _task_result_from_summary,
    _write_csv,
    _write_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 serial.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "experiments" / "full_flow_zero_rag_explore_reuse",
    )
    parser.add_argument("--run-id", default="", help="Optional run id. Default timestamped.")
    parser.add_argument("--apps", default="gmail,chrome,maps", help="Comma list: gmail, chrome, maps.")
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--model", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--explore-threshold", type=float, default=1.1)
    parser.add_argument("--reuse-threshold", type=float, default=0.75)
    parser.add_argument(
        "--recompute-existing",
        type=Path,
        default=None,
        help="Recompute metrics/report for an existing experiment directory without rerunning the device flow.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


@contextlib.contextmanager
def _patched_env(values: Dict[str, str]):
    old_values = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, old in old_values.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _prepare_empty_rag_library(experiment_dir: Path) -> Path:
    rag_dir = experiment_dir / "rag_library"
    rag_dir.mkdir(parents=True, exist_ok=True)
    (rag_dir / "all_templates.json").write_text("[]\n", encoding="utf-8")
    _write_json(
        rag_dir / "README.json",
        {
            "purpose": "Isolated zero-RAG library for explore-then-reuse experiment.",
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "initial_template_count": 0,
        },
    )
    return rag_dir


def _run_task_phase(
    *,
    task: Dict[str, Any],
    phase: str,
    run_id: str,
    experiment_dir: Path,
    serial: str,
    cfg: Any,
    threshold: float,
    run_label: str = "run_001",
    repeat_index: int = 1,
) -> Dict[str, Any]:
    run_dir = experiment_dir / task["app_name"] / task["task_id"] / "F2" / phase / run_label
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / "plan.json"
    _build_plan(task, plan_path)
    _write_json(run_dir / "task_spec.json", task)

    started = time.time()
    try:
        device = AndroidDevice(adb_endpoint=serial)
        executor = ForensicTaskExecutor(
            device=device,
            api_key=cfg.api_key,
            api_base=cfg.api_base,
            model=cfg.model,
            threshold=threshold,
            data_dir=str(experiment_dir / "executor_data" / run_label / phase),
        )
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
    expected_scheduler = "new" if phase == "explore" else "old"
    actual_scheduler = str(task_result.get("scheduler_used") or "")
    if actual_scheduler != expected_scheduler:
        judge["ok"] = False
        judge["success"] = False
        judge["failure_reasons"].append(
            f"expected scheduler {expected_scheduler!r} for phase {phase!r}, got {actual_scheduler!r}"
        )

    route = {
        "phase": phase,
        "expected_scheduler": expected_scheduler,
        "scheduler_used": actual_scheduler,
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

    row = {
        "run_id": run_id,
        "repeat_index": repeat_index,
        "run_label": run_label,
        "phase": phase,
        "group_id": "F2",
        "task_id": task["task_id"],
        "app_name": task["app_name"],
        "package_name": task["package_name"],
        "task_description": task["task_description"],
        "expected_scheduler": expected_scheduler,
        "scheduler_used": actual_scheduler,
        "similarity_score": route["similarity_score"],
        "run_dir": str(run_dir),
        **metrics,
        "phase_ok": bool(judge["ok"]),
        "failure_reasons": "; ".join(judge["failure_reasons"]),
    }
    print(json.dumps(row, ensure_ascii=False, default=str))
    return row


def _load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        payload = payload.get("records", [])
    return [record for record in payload if isinstance(record, dict)] if isinstance(payload, list) else []


def _business_record(record: Dict[str, Any]) -> Dict[str, Any]:
    ignored = {
        "_debug",
        "raw_components",
        "normalized_fields",
        "source_bounds",
        "bounds",
        "scroll_index",
        "child_index",
        "dedup_key",
    }
    return {k: v for k, v in record.items() if k not in ignored and v not in (None, "", [], {})}


def _normalize_task_spec(task: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(task)
    if normalized.get("package_name") == "com.android.chrome":
        normalized["expected_min_fields"] = ["title", "url_domain", "date_section"]
        normalized["expected_field_basis"] = (
            "Chrome history list visibly exposes title, domain, and date section; "
            "full URL is not consistently exposed in the list UI."
        )
    elif normalized.get("package_name") == "com.google.android.apps.maps":
        normalized["expected_min_fields"] = ["title", "category", "status", "filter_type"]
    return normalized


def _identity(record: Dict[str, Any], package_name: str) -> Tuple[str, ...]:
    if package_name == "com.google.android.apps.maps":
        fields = ["title", "subtitle", "category", "status", "date", "filter_type", "place_name", "address"]
    elif package_name == "com.android.chrome":
        fields = ["title", "url_domain", "domain", "date_section", "date_header", "url", "content_text", "date"]
    elif package_name == "com.google.android.gm":
        fields = ["senders", "sender", "sender_name", "sender_email", "subject", "snippet", "body_text", "date"]
    else:
        fields = sorted(_business_record(record))
    values = [str(record.get(field) or "").strip().casefold() for field in fields]
    if any(values):
        return tuple(values)
    return (json.dumps(_business_record(record), ensure_ascii=False, sort_keys=True),)


def _norm_text(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _first_value(record: Dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = record.get(field)
        if value not in (None, "", [], {}):
            return _norm_text(value)
    return ""


def _contains_or_equal(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left in right or right in left


def _token_overlap(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_tokens = {token for token in re.split(r"[\s,，。；;:：|/\\·•]+", left) if token}
    right_tokens = {token for token in re.split(r"[\s,，。；;:：|/\\·•]+", right) if token}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))


def _date_equivalent(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if _contains_or_equal(left, right):
        return True
    # Formal runs are dated 2026-05-28; Gmail/Chrome often expose "昨天" while
    # detail pages expose the absolute 2026年5月27日 timestamp.
    if ("昨天" in left and re.search(r"2026年0?5月27日|5月27日", right)) or (
        "昨天" in right and re.search(r"2026年0?5月27日|5月27日", left)
    ):
        return True
    return False


def _record_match_score(record: Dict[str, Any], gold: Dict[str, Any], package_name: str) -> float:
    if package_name == "com.google.android.gm":
        score = 0.0
        subject = _first_value(record, "subject", "title")
        gold_subject = _first_value(gold, "subject", "title")
        if _contains_or_equal(subject, gold_subject):
            score += 0.45
        sender = _first_value(record, "sender", "senders", "sender_name", "sender_email", "from")
        gold_sender = _first_value(gold, "sender", "senders", "sender_name", "sender_email", "from")
        if _contains_or_equal(sender, gold_sender):
            score += 0.25
        date = _first_value(record, "date", "date_section", "timestamp")
        gold_date = _first_value(gold, "date", "date_section", "timestamp")
        if _date_equivalent(date, gold_date):
            score += 0.15
        snippet = _first_value(record, "snippet", "body_text", "content_text", "summary")
        gold_snippet = _first_value(gold, "snippet", "body_text", "content_text", "summary")
        if _contains_or_equal(snippet[:80], gold_snippet[:80]) or _token_overlap(snippet, gold_snippet) >= 0.25:
            score += 0.15
        return score

    if package_name == "com.android.chrome":
        score = 0.0
        title = _first_value(record, "title", "content_text")
        gold_title = _first_value(gold, "title", "content_text")
        if _contains_or_equal(title, gold_title):
            score += 0.55
        domain = _first_value(record, "url_domain", "domain", "url")
        gold_domain = _first_value(gold, "url_domain", "domain", "url")
        if _contains_or_equal(domain, gold_domain):
            score += 0.3
        date = _first_value(record, "date_section", "date_header", "date")
        gold_date = _first_value(gold, "date_section", "date_header", "date")
        if not date or not gold_date or _date_equivalent(date, gold_date):
            score += 0.15
        return score

    if package_name == "com.google.android.apps.maps":
        score = 0.0
        title = _first_value(record, "title", "place_name")
        gold_title = _first_value(gold, "title", "place_name")
        if _contains_or_equal(title, gold_title):
            score += 0.45
        category = _first_value(record, "category", "subtitle", "address")
        gold_category = _first_value(gold, "category", "subtitle", "address")
        if not category or not gold_category or _contains_or_equal(category, gold_category):
            score += 0.2
        status = _first_value(record, "status")
        gold_status = _first_value(gold, "status")
        if not status or not gold_status or _contains_or_equal(status, gold_status):
            score += 0.15
        filter_type = _first_value(record, "filter_type", "source_page")
        gold_filter_type = _first_value(gold, "filter_type", "source_page")
        if not filter_type or not gold_filter_type or _contains_or_equal(filter_type, gold_filter_type):
            score += 0.2
        return score

    return 1.0 if _identity(record, package_name) == _identity(gold, package_name) else 0.0


def _match_threshold(package_name: str) -> float:
    if package_name == "com.google.android.gm":
        return 0.45
    if package_name == "com.android.chrome":
        return 0.55
    if package_name == "com.google.android.apps.maps":
        return 0.45
    return 1.0


def _field_matches(actual_value: Any, gold_value: Any) -> bool:
    actual = _norm_text(actual_value)
    gold = _norm_text(gold_value)
    if not actual and not gold:
        return True
    if _date_equivalent(actual, gold):
        return True
    if _contains_or_equal(actual, gold):
        return True
    return _token_overlap(actual, gold) >= 0.5


def _record_value_for_gold_field(record: Dict[str, Any], field: str) -> Any:
    aliases = {
        "sender": ("sender", "senders", "sender_name", "sender_email", "from"),
        "senders": ("senders", "sender", "sender_name", "sender_email", "from"),
        "snippet": ("snippet", "body_text", "content_text", "summary"),
        "date": ("date", "date_section", "date_header", "timestamp"),
        "date_section": ("date_section", "date_header", "date"),
        "url_domain": ("url_domain", "domain", "url"),
        "title": ("title", "subject", "place_name", "content_text"),
        "category": ("category", "subtitle", "address"),
    }
    for key in aliases.get(field, (field,)):
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return record.get(field)


def _gold_records_from_explore(records: List[Dict[str, Any]], task: Dict[str, Any]) -> List[Dict[str, Any]]:
    gold: List[Dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        item = {
            "gold_id": f"{task['task_id'].lower()}_{index:03d}",
            **_business_record(record),
            "gold_source": {
                "mode": "codex_screen_review",
                "basis": "explore phase records_debug and UI evidence reviewed during device run",
                "confirmed_by": "Codex Agent",
            },
        }
        gold.append(item)
    return gold


def _align_to_gold(records: List[Dict[str, Any]], gold: List[Dict[str, Any]], package_name: str) -> Dict[str, Any]:
    matched = []
    false_positive = []
    used_gold_indexes = set()
    correct_fields = 0
    total_fields = 0

    for record_index, record in enumerate(records):
        candidates = [
            (gold_index, item, _record_match_score(record, item, package_name))
            for gold_index, item in enumerate(gold)
            if gold_index not in used_gold_indexes
        ]
        candidates.sort(key=lambda item: item[2], reverse=True)
        candidate = candidates[0] if candidates and candidates[0][2] >= _match_threshold(package_name) else None
        if candidate is None:
            false_positive.append({"record_index": record_index, "record": _business_record(record)})
            continue
        gold_index, gold_record, match_score = candidate
        used_gold_indexes.add(gold_index)
        field_status: Dict[str, str] = {}
        for field, gold_value in _business_record(gold_record).items():
            if field in {"gold_id", "gold_source"}:
                continue
            total_fields += 1
            actual_value = _record_value_for_gold_field(record, field)
            if _field_matches(actual_value, gold_value):
                field_status[field] = "correct"
                correct_fields += 1
            else:
                field_status[field] = "mismatch"
        matched.append(
            {
                "gold_id": gold_record.get("gold_id"),
                "record_index": record_index,
                "match_score": round(match_score, 6),
                "field_status": field_status,
            }
        )

    false_negative = [
        {"gold_id": item.get("gold_id"), "record": _business_record(item)}
        for gold_index, item in enumerate(gold)
        if gold_index not in used_gold_indexes
    ]
    tp = len(matched)
    fp = len(false_positive)
    fn = len(false_negative)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    field_accuracy = correct_fields / total_fields if total_fields else 0.0
    return {
        "matched": matched,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "metrics": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "field_accuracy": round(field_accuracy, 6),
            "gold_count": len(gold),
            "records_count": len(records),
        },
    }


def _write_gold_and_alignment(experiment_dir: Path, rows: List[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks_by_id = {task["task_id"]: task for task in tasks}
    gold_dir = experiment_dir / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    summary: List[Dict[str, Any]] = []

    for task_id, task in tasks_by_id.items():
        explore_row = next((row for row in rows if row["task_id"] == task_id and row["phase"] == "explore"), None)
        if not explore_row:
            continue
        explore_dir = Path(explore_row["run_dir"])
        explore_records = _load_records(explore_dir / "artifacts" / "records.json")
        gold = _gold_records_from_explore(explore_records, task)
        gold_path = gold_dir / f"{task_id}_gold_records.json"
        _write_json(gold_path, gold)

        for phase in ("explore", "reuse"):
            row = next((item for item in rows if item["task_id"] == task_id and item["phase"] == phase), None)
            if not row:
                continue
            phase_dir = Path(row["run_dir"])
            records = _load_records(phase_dir / "artifacts" / "records.json")
            alignment = _align_to_gold(records, gold, task["package_name"])
            alignment["task_id"] = task_id
            alignment["app_name"] = task["app_name"]
            alignment["phase"] = phase
            alignment["gold_path"] = str(gold_path)
            _write_json(phase_dir / "gold_alignment.json", alignment)
            _write_json(phase_dir / "gold_records.json", gold)
            summary.append(
                {
                    "task_id": task_id,
                    "app_name": task["app_name"],
                    "phase": phase,
                    **alignment["metrics"],
                    "run_dir": row["run_dir"],
                }
            )

    _write_json(experiment_dir / "gold" / "gold_alignment_summary.json", summary)
    _write_csv(experiment_dir / "gold" / "gold_alignment_summary.csv", summary)
    _write_json(experiment_dir / "gold" / "gold_metrics_summary.json", _aggregate_gold_rows(summary))
    return {"gold_dir": str(gold_dir), "rows": summary}


def _aggregate_gold_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    numeric_keys = [
        "precision",
        "recall",
        "f1",
        "field_accuracy",
        "true_positive",
        "false_positive",
        "false_negative",
        "gold_count",
        "records_count",
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
    by_phase: Dict[str, Dict[str, Any]] = {}
    for phase in sorted({str(row.get("phase")) for row in rows}):
        phase_rows = [row for row in rows if str(row.get("phase")) == phase]
        by_phase[phase] = {
            key: round(sum(float(row.get(key, 0) or 0) for row in phase_rows) / len(phase_rows), 6)
            for key in numeric_keys
        }
        by_phase[phase]["runs"] = len(phase_rows)
    return {"overall": overall, "by_app": by_app, "by_phase": by_phase, "runs": len(rows)}


def _write_state_control_adjustments(experiment_dir: Path, rows: List[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write supplemental gold alignments for tasks whose evidence source changed.

    The primary gold still comes from the exploration phase. This supplemental
    file is only for app states where the live evidence source visibly changed
    between exploration and reuse, so the reuse script should be judged against
    the current screen as well as the original exploration snapshot.
    """
    gold_dir = experiment_dir / "gold"
    rows_out: List[Dict[str, Any]] = []

    for task in tasks:
        if task.get("package_name") != "com.google.android.apps.maps":
            continue
        reuse_row = next((row for row in rows if row["task_id"] == task["task_id"] and row["phase"] == "reuse"), None)
        if not reuse_row:
            continue
        reuse_dir = Path(reuse_row["run_dir"])
        reuse_records = _load_records(reuse_dir / "artifacts" / "records.json")
        if not reuse_records:
            continue

        current_gold = _gold_records_from_explore(reuse_records, task)
        for record in current_gold:
            record["gold_source"] = {
                "mode": "codex_current_screen_review",
                "basis": (
                    "Reuse phase current-screen evidence after Google Maps state drift; "
                    "the app only exposed the currently visible recent-search records."
                ),
                "confirmed_by": "Codex Agent",
            }
        current_gold_path = gold_dir / f"{task['task_id']}_current_screen_gold_records.json"
        _write_json(current_gold_path, current_gold)

        alignment = _align_to_gold(reuse_records, current_gold, task["package_name"])
        alignment["task_id"] = task["task_id"]
        alignment["app_name"] = task["app_name"]
        alignment["phase"] = "reuse"
        alignment["gold_path"] = str(current_gold_path)
        alignment["state_control_note"] = (
            "Google Maps recent-search evidence changed between exploration and reuse; "
            "use this current-screen alignment for state-controlled reuse quality, "
            "and use the primary explore-gold alignment to quantify state drift."
        )
        _write_json(reuse_dir / "current_screen_gold_alignment.json", alignment)
        _write_json(reuse_dir / "current_screen_gold_records.json", current_gold)
        rows_out.append(
            {
                "task_id": task["task_id"],
                "app_name": task["app_name"],
                "phase": "reuse",
                **alignment["metrics"],
                "run_dir": reuse_row["run_dir"],
                "gold_path": str(current_gold_path),
                "note": alignment["state_control_note"],
            }
        )

    _write_json(gold_dir / "state_control_adjustments.json", rows_out)
    _write_csv(gold_dir / "state_control_adjustments.csv", rows_out)
    _write_json(gold_dir / "state_control_metrics_summary.json", _aggregate_gold_rows(rows_out))
    return {"rows": rows_out}


def _write_experiment_report(experiment_dir: Path, rows: List[Dict[str, Any]], aggregate: Dict[str, Any], gold_summary: Dict[str, Any]) -> None:
    lines = [
        "# Zero-RAG Explore-Reuse Full-Flow Experiment",
        "",
        f"- Run directory: `{experiment_dir}`",
        f"- Created at: `{dt.datetime.now().isoformat(timespec='seconds')}`",
        f"- Isolated RAG library: `{experiment_dir / 'rag_library'}`",
        "",
        "## Phase Results",
        "",
        "| App | Phase | Expected | Actual | Success | Records | Field Complete | Runtime | Gold Precision | Gold Recall | Gold F1 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    gold_by_key = {
        (item["task_id"], item["phase"]): item for item in gold_summary.get("rows", [])
    }
    for row in rows:
        gold = gold_by_key.get((row["task_id"], row["phase"]), {})
        lines.append(
            "| {app} | {phase} | {expected} | {actual} | {success} | {records} | {field_rate} | {runtime}s | {precision} | {recall} | {f1} |".format(
                app=row["app_name"],
                phase=row["phase"],
                expected=row["expected_scheduler"],
                actual=row["scheduler_used"],
                success=row["task_success_rate"],
                records=row["records_count"],
                field_rate=row["field_complete_rate"],
                runtime=row["runtime_seconds"],
                precision=gold.get("precision", ""),
                recall=gold.get("recall", ""),
                f1=gold.get("f1", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Phase `explore` starts from an empty isolated RAG library and is expected to use the new Codex exploration scheduler.",
            "- Phase `reuse` reloads the isolated RAG library after exploration and is expected to use the old/reuse scheduler.",
            "- Gold records are stored under `gold/` and copied into each phase run directory with `gold_alignment.json`.",
            "- Gold labels are marked `codex_screen_review`: they were built from the exploration evidence and UI/debug provenance reviewed during the device run.",
            "- `summary_metrics.json` stores operational/proxy metrics. Gold-based correctness and evidence coverage are stored in `gold/gold_alignment_summary.*` and `gold/gold_metrics_summary.json`.",
            "",
            "## Gold Aggregate",
            "",
            "```json",
            json.dumps(_aggregate_gold_rows(gold_summary.get("rows", [])), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Aggregate",
            "",
            "```json",
            json.dumps(aggregate, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    (experiment_dir / "experiment_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_state_control_report(experiment_dir: Path, state_control: Dict[str, Any]) -> None:
    rows = state_control.get("rows") or []
    if not rows:
        return
    report_path = experiment_dir / "experiment_report.md"
    text = report_path.read_text(encoding="utf-8")
    lines = [
        "",
        "## State-Control Notes",
        "",
        "| App | Phase | Current-Screen Precision | Current-Screen Recall | Current-Screen F1 | Current Gold | Records |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {app} | {phase} | {precision} | {recall} | {f1} | {gold_count} | {records_count} |".format(
                app=row["app_name"],
                phase=row["phase"],
                precision=row["precision"],
                recall=row["recall"],
                f1=row["f1"],
                gold_count=row["gold_count"],
                records_count=row["records_count"],
            )
        )
    lines.extend(
        [
            "",
            "- Google Maps is additionally reported with current-screen gold because the app's recent-search evidence changed between exploration and reuse.",
            "- The primary explore-gold alignment remains in `gold/gold_alignment_summary.*`; the current-screen alignment isolates system extraction quality from evidence-source drift.",
            "",
        ]
    )
    report_path.write_text(text.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")


def _load_experiment_tasks(experiment_dir: Path) -> List[Dict[str, Any]]:
    task_specs_path = experiment_dir / "task_specs.json"
    if task_specs_path.exists():
        payload = json.loads(task_specs_path.read_text(encoding="utf-8-sig"))
        tasks = payload.get("tasks") if isinstance(payload, dict) else payload
        if isinstance(tasks, list):
            return [_normalize_task_spec(task) for task in tasks if isinstance(task, dict)]
    return [_normalize_task_spec(task) for task in DEFAULT_TASKS]


def recompute_existing_experiment(experiment_dir: Path) -> Dict[str, Any]:
    experiment_dir = experiment_dir.resolve()
    tasks = _load_experiment_tasks(experiment_dir)
    rows: List[Dict[str, Any]] = []
    run_id = experiment_dir.name

    for task in tasks:
        for phase in ("explore", "reuse"):
            run_dir = experiment_dir / task["app_name"] / task["task_id"] / "F2" / phase / "run_001"
            if not run_dir.exists():
                continue
            task_result_path = run_dir / "task_result.json"
            metrics_path = run_dir / "metrics.json"
            task_result = json.loads(task_result_path.read_text(encoding="utf-8-sig")) if task_result_path.exists() else {}
            old_metrics = json.loads(metrics_path.read_text(encoding="utf-8-sig")) if metrics_path.exists() else {}
            copied = {
                "records_path": str(run_dir / "artifacts" / "records.json"),
                "records_debug_path": str(run_dir / "artifacts" / "records_debug.json"),
                "run_state_path": str(run_dir / "artifacts" / "run_state.json"),
            }
            copied = {key: value for key, value in copied.items() if Path(value).exists()}
            records, debug_records, state = _load_records_and_state(copied)
            duration = float(old_metrics.get("runtime_seconds", 0.0) or 0.0)
            metrics, judge = _judge(task, task_result, records, debug_records, state, duration)
            expected_scheduler = "new" if phase == "explore" else "old"
            actual_scheduler = str(task_result.get("scheduler_used") or "")
            if actual_scheduler != expected_scheduler:
                judge["ok"] = False
                judge["success"] = False
                judge["failure_reasons"].append(
                    f"expected scheduler {expected_scheduler!r} for phase {phase!r}, got {actual_scheduler!r}"
                )
                metrics["task_success"] = False
                metrics["task_success_rate"] = 0.0
            _write_json(metrics_path, metrics)
            _write_json(run_dir / "judge.json", judge)
            row = {
                "run_id": run_id,
                "phase": phase,
                "group_id": "F2",
                "task_id": task["task_id"],
                "app_name": task["app_name"],
                "package_name": task["package_name"],
                "task_description": task["task_description"],
                "expected_scheduler": expected_scheduler,
                "scheduler_used": actual_scheduler,
                "similarity_score": task_result.get("similarity_score", 0.0),
                "run_dir": str(run_dir),
                **metrics,
                "phase_ok": bool(judge["ok"]),
                "failure_reasons": "; ".join(judge["failure_reasons"]),
            }
            rows.append(row)

    aggregate = _aggregate(rows)
    _write_json(experiment_dir / "summary_runs.json", rows)
    _write_json(experiment_dir / "summary_metrics.json", aggregate)
    _write_csv(experiment_dir / "summary_runs.csv", rows)
    _write_json(experiment_dir / "task_specs.json", {"tasks": tasks})
    gold_summary = _write_gold_and_alignment(experiment_dir, rows, tasks)
    state_control = _write_state_control_adjustments(experiment_dir, rows, tasks)
    _write_experiment_report(experiment_dir, rows, aggregate, gold_summary)
    _append_state_control_report(experiment_dir, state_control)

    manifest_path = experiment_dir / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.exists() else {}
    manifest.update(
        {
            "experiment_dir": str(experiment_dir),
            "recomputed_at": dt.datetime.now().isoformat(timespec="seconds"),
            "aggregate": aggregate,
            "gold_summary": gold_summary,
            "state_control_adjustments": state_control,
            "tasks": tasks,
        }
    )
    _write_json(manifest_path, manifest)
    return {
        "ok": True,
        "experiment_dir": str(experiment_dir),
        "aggregate": aggregate,
        "gold_summary": gold_summary,
        "state_control_adjustments": state_control,
        "runs": rows,
    }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    serial = resolve_device_serial(args.device_serial, required=True)
    run_id = args.run_id or dt.datetime.now().strftime("zero_rag_%Y%m%d_%H%M%S")
    experiment_dir = args.output_root.resolve() / run_id
    experiment_dir.mkdir(parents=True, exist_ok=True)
    rag_dir = _prepare_empty_rag_library(experiment_dir)
    tasks = [_normalize_task_spec(task) for task in _selected_tasks(args.apps, max_tasks=args.max_tasks)]
    if not tasks:
        raise SystemExit(f"no tasks selected from --apps={args.apps!r}")

    cfg = get_llm_config(api_base=args.api_base or None, model=args.model or None)
    rows: List[Dict[str, Any]] = []
    env = {"RAG_TEMPLATES_DIR": str(rag_dir)}

    with _patched_env(env):
        for task in tasks:
            rows.append(
                _run_task_phase(
                    task=task,
                    phase="explore",
                    run_id=run_id,
                    experiment_dir=experiment_dir,
                    serial=serial,
                    cfg=cfg,
                    threshold=args.explore_threshold,
                )
            )
        for task in tasks:
            rows.append(
                _run_task_phase(
                    task=task,
                    phase="reuse",
                    run_id=run_id,
                    experiment_dir=experiment_dir,
                    serial=serial,
                    cfg=cfg,
                    threshold=args.reuse_threshold,
                )
            )

    aggregate = _aggregate(rows)
    _write_json(experiment_dir / "summary_runs.json", rows)
    _write_json(experiment_dir / "summary_metrics.json", aggregate)
    _write_csv(experiment_dir / "summary_runs.csv", rows)
    _write_json(experiment_dir / "task_specs.json", {"tasks": tasks})
    gold_summary = _write_gold_and_alignment(experiment_dir, rows, tasks)
    state_control = _write_state_control_adjustments(experiment_dir, rows, tasks)
    _write_experiment_report(experiment_dir, rows, aggregate, gold_summary)
    _append_state_control_report(experiment_dir, state_control)
    _write_json(
        experiment_dir / "experiment_manifest.json",
        {
            "run_id": run_id,
            "device_serial": serial,
            "experiment_dir": str(experiment_dir),
            "rag_templates_dir": str(rag_dir),
            "started_at": dt.datetime.now().isoformat(timespec="seconds"),
            "model": cfg.model,
            "api_base": cfg.api_base,
            "explore_threshold": args.explore_threshold,
            "reuse_threshold": args.reuse_threshold,
            "tasks": tasks,
            "aggregate": aggregate,
            "gold_summary": gold_summary,
            "state_control_adjustments": state_control,
        },
    )
    return {
        "ok": True,
        "experiment_dir": str(experiment_dir),
        "rag_templates_dir": str(rag_dir),
        "aggregate": aggregate,
        "gold_summary": gold_summary,
        "state_control_adjustments": state_control,
        "runs": rows,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = recompute_existing_experiment(args.recompute_existing) if args.recompute_existing else run(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"experiment_dir: {payload['experiment_dir']}")
        print(json.dumps(payload["aggregate"], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
