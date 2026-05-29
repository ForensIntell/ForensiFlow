#!/usr/bin/env python3
"""Smoke tests for ForensiFlow evidence integrity helpers."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.forensiflow.core.evidence_integrity import (  # noqa: E402
    append_chain_event,
    build_manifest,
    verify_chain,
    verify_manifest,
)


def test_manifest_roundtrip() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="ff_integrity_"))
    try:
        (temp_dir / "records.json").write_text(json.dumps({"records": [{"a": 1}]}), encoding="utf-8")
        (temp_dir / "records_debug.json").write_text(json.dumps({"records": [{"a": 1, "_debug": {}}]}), encoding="utf-8")
        append_chain_event(temp_dir, "test_started", {"case": "roundtrip"}, actor="test")
        manifest = build_manifest(temp_dir, case_id="case-1", device_serial="serial-1", app_name="App", package_name="pkg", target="target")
        assert manifest["file_count"] >= 2
        result = verify_manifest(temp_dir)
        assert result["ok"], result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_manifest_detects_tampering() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="ff_integrity_tamper_"))
    try:
        target = temp_dir / "records.json"
        target.write_text(json.dumps({"records": [{"a": 1}]}), encoding="utf-8")
        build_manifest(temp_dir)
        target.write_text(json.dumps({"records": [{"a": 2}]}), encoding="utf-8")
        result = verify_manifest(temp_dir)
        assert not result["ok"]
        assert any(issue.get("type") == "sha256_mismatch" for issue in result["issues"])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_chain_detects_tampering() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="ff_integrity_chain_"))
    try:
        append_chain_event(temp_dir, "one", {}, actor="test")
        append_chain_event(temp_dir, "two", {}, actor="test")
        assert verify_chain(temp_dir)["ok"]
        chain_path = temp_dir / "evidence_chain.jsonl"
        lines = chain_path.read_text(encoding="utf-8").splitlines()
        first = json.loads(lines[0])
        first["payload"] = {"changed": True}
        lines[0] = json.dumps(first, ensure_ascii=False, sort_keys=True)
        chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_chain(temp_dir)
        assert not result["ok"]
        assert any(issue.get("type") == "event_hash_mismatch" for issue in result["issues"])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_manifest_detects_untracked_files() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="ff_integrity_untracked_"))
    try:
        (temp_dir / "records.json").write_text(json.dumps({"records": [{"a": 1}]}), encoding="utf-8")
        build_manifest(temp_dir)
        (temp_dir / "late_added.json").write_text(json.dumps({"extra": True}), encoding="utf-8")
        result = verify_manifest(temp_dir)
        assert not result["ok"]
        assert any(issue.get("type") == "untracked_manifest_file" for issue in result["issues"])
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
    test_manifest_roundtrip()
    test_manifest_detects_tampering()
    test_chain_detects_tampering()
    test_manifest_detects_untracked_files()
    print("evidence integrity tests ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
