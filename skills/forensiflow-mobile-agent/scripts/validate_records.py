#!/usr/bin/env python3
"""Validate ForensiFlow records.json and records_debug.json shape."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List


DEBUG_FIELDS = {
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
CORE_FIELDS = {
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
    "raw_components",
}


def load_payload(path: Path) -> tuple[List[Any], Dict[str, Any], str]:
    if not path.exists():
        return [], {}, f"missing: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return [], {}, f"parse error: {exc}"
    if isinstance(data, dict):
        records = data.get("records")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    else:
        records = data
        metadata = {}
    if not isinstance(records, list):
        return [], metadata, "records is not a list"
    return records, metadata, ""


def canonical(record: Any) -> str:
    if not isinstance(record, dict):
        return json.dumps(record, ensure_ascii=False, sort_keys=True)
    clean = {k: v for k, v in record.items() if k not in DEBUG_FIELDS and v not in ("", None, [], {})}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_records.py <script_workspace-or-run-dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    workspace = root / "script_workspace" if (root / "script_workspace").is_dir() else root
    records, _, records_error = load_payload(workspace / "records.json")
    debug_records, _, debug_error = load_payload(workspace / "records_debug.json")

    issues: List[str] = []
    if records_error:
        issues.append(f"records.json: {records_error}")
    if debug_error:
        issues.append(f"records_debug.json: {debug_error}")
    if records and debug_records and len(records) != len(debug_records):
        issues.append(f"debug count mismatch: records={len(records)} debug={len(debug_records)}")
    if records:
        leaked = [idx for idx, rec in enumerate(records) if isinstance(rec, dict) and DEBUG_FIELDS.intersection(rec)]
        if leaked:
            issues.append(f"debug fields leaked into records.json at indexes {leaked[:10]}")
        empty_core = [
            idx
            for idx, rec in enumerate(records)
            if isinstance(rec, dict) and not any(rec.get(field) not in ("", None, [], {}) for field in CORE_FIELDS)
        ]
        if empty_core:
            issues.append(f"records without core business fields at indexes {empty_core[:10]}")
        seen = {}
        dups = []
        for idx, rec in enumerate(records):
            key = canonical(rec)
            if key in seen:
                dups.append((seen[key], idx))
            else:
                seen[key] = idx
        if dups:
            issues.append(f"canonical duplicates: {dups[:10]}")
    if debug_records:
        missing_debug = [idx for idx, rec in enumerate(debug_records) if not isinstance(rec, dict) or not isinstance(rec.get("_debug"), dict)]
        if missing_debug:
            issues.append(f"debug records missing _debug at indexes {missing_debug[:10]}")

    print(json.dumps({"ok": not issues, "records_count": len(records), "debug_count": len(debug_records), "issues": issues}, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
