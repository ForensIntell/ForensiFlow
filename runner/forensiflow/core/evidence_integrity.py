"""Evidence integrity helpers for ForensiFlow run artifacts.

The module provides two small, dependency-free building blocks:

- a manifest that records SHA-256 hashes for selected run files;
- an append-only event log where each line chains to the previous line hash.

It does not try to make local files immutable. Its purpose is to make accidental
or later modification detectable by verification tooling.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


MANIFEST_FILENAME = "evidence_manifest.json"
CHAIN_LOG_FILENAME = "evidence_chain.jsonl"
CHAIN_STATE_FILENAME = "evidence_chain_state.json"
HASH_ALGORITHM = "sha256"

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
}
DEFAULT_EXCLUDE_FILES = {
    MANIFEST_FILENAME,
    CHAIN_LOG_FILENAME,
    CHAIN_STATE_FILENAME,
}
DEFAULT_INCLUDE_SUFFIXES = {
    ".json",
    ".jsonl",
    ".txt",
    ".xml",
    ".md",
    ".py",
    ".log",
}


def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def append_chain_event(
    run_dir: str | Path,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    actor: str = "forensiflow",
) -> Dict[str, Any]:
    """Append a hash-chained integrity event under ``run_dir``."""

    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    chain_path = root / CHAIN_LOG_FILENAME
    state_path = root / CHAIN_STATE_FILENAME
    previous_hash = ""
    sequence = 1
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            previous_hash = str(state.get("last_hash") or "")
            sequence = int(state.get("sequence") or 0) + 1
        except Exception:
            previous_hash, sequence = _read_last_chain_state(chain_path)
            sequence += 1

    event = {
        "sequence": sequence,
        "timestamp": utc_now_iso(),
        "actor": actor,
        "event_type": str(event_type),
        "payload": payload or {},
        "previous_hash": previous_hash,
    }
    event_hash = sha256_bytes(canonical_json(event).encode("utf-8"))
    line = {**event, "event_hash": event_hash}
    with chain_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    state_path.write_text(
        json.dumps(
            {
                "sequence": sequence,
                "last_hash": event_hash,
                "updated_at": utc_now_iso(),
                "chain_log": CHAIN_LOG_FILENAME,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return line


def build_manifest(
    run_dir: str | Path,
    *,
    case_id: str = "",
    device_serial: str = "",
    app_name: str = "",
    package_name: str = "",
    target: str = "",
    include_suffixes: Optional[Iterable[str]] = None,
    max_file_bytes: int = 200 * 1024 * 1024,
    write: bool = True,
) -> Dict[str, Any]:
    """Build and optionally write an evidence manifest for a run directory."""

    root = Path(run_dir).resolve()
    suffixes = {suffix.lower() for suffix in (include_suffixes or DEFAULT_INCLUDE_SUFFIXES)}
    files = []
    for path in _iter_manifest_files(root, suffixes=suffixes, max_file_bytes=max_file_bytes):
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        files.append(
            {
                "path": relative,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": sha256_file(path),
            }
        )
    files.sort(key=lambda item: item["path"])
    root_hash = _manifest_root_hash(files)
    manifest = {
        "schema_version": "1.0",
        "tool": "ForensiFlow evidence integrity",
        "created_at": utc_now_iso(),
        "hash_algorithm": HASH_ALGORITHM,
        "run_dir": str(root),
        "include_suffixes": sorted(suffixes),
        "max_file_bytes": int(max_file_bytes),
        "case_id": case_id,
        "device_serial": device_serial,
        "app_name": app_name,
        "package_name": package_name,
        "target": target,
        "file_count": len(files),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in files),
        "root_hash": root_hash,
        "files": files,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
        },
    }
    manifest["manifest_hash"] = sha256_bytes(
        canonical_json({key: value for key, value in manifest.items() if key != "manifest_hash"}).encode("utf-8")
    )
    if write:
        manifest_path = root / MANIFEST_FILENAME
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        append_chain_event(
            root,
            "manifest_written",
            {
                "manifest_path": MANIFEST_FILENAME,
                "file_count": manifest["file_count"],
                "root_hash": manifest["root_hash"],
                "manifest_hash": manifest["manifest_hash"],
            },
        )
    return manifest


def verify_manifest(run_dir: str | Path, manifest_path: str | Path | None = None) -> Dict[str, Any]:
    """Verify file hashes in an evidence manifest."""

    root = Path(run_dir).resolve()
    path = Path(manifest_path).resolve() if manifest_path else root / MANIFEST_FILENAME
    if not path.exists():
        return {"ok": False, "error": f"manifest not found: {path}", "run_dir": str(root)}

    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "error": f"failed to parse manifest: {exc}", "manifest_path": str(path)}

    expected_manifest_hash = manifest.get("manifest_hash", "")
    recalculated_manifest_hash = sha256_bytes(
        canonical_json({key: value for key, value in manifest.items() if key != "manifest_hash"}).encode("utf-8")
    )
    issues: List[Dict[str, Any]] = []
    if expected_manifest_hash and expected_manifest_hash != recalculated_manifest_hash:
        issues.append(
            {
                "type": "manifest_hash_mismatch",
                "expected": expected_manifest_hash,
                "actual": recalculated_manifest_hash,
            }
        )

    checked_files = 0
    declared_paths = set()
    for entry in manifest.get("files") or []:
        if not isinstance(entry, dict):
            issues.append({"type": "invalid_file_entry", "entry": entry})
            continue
        rel_path = str(entry.get("path") or "")
        declared_paths.add(rel_path)
        file_path = root / rel_path
        if not file_path.exists():
            issues.append({"type": "missing_file", "path": rel_path})
            continue
        checked_files += 1
        stat = file_path.stat()
        expected_size = int(entry.get("size_bytes") or -1)
        expected_hash = str(entry.get("sha256") or "")
        if expected_size != stat.st_size:
            issues.append({"type": "size_mismatch", "path": rel_path, "expected": expected_size, "actual": stat.st_size})
        actual_hash = sha256_file(file_path)
        if expected_hash != actual_hash:
            issues.append({"type": "sha256_mismatch", "path": rel_path, "expected": expected_hash, "actual": actual_hash})

    recalculated_root_hash = _manifest_root_hash(manifest.get("files") or [])
    if manifest.get("root_hash") != recalculated_root_hash:
        issues.append(
            {
                "type": "root_hash_mismatch",
                "expected": manifest.get("root_hash"),
                "actual": recalculated_root_hash,
            }
        )

    suffixes = {str(item).lower() for item in (manifest.get("include_suffixes") or DEFAULT_INCLUDE_SUFFIXES)}
    try:
        max_file_bytes = int(manifest.get("max_file_bytes") or 200 * 1024 * 1024)
    except Exception:
        max_file_bytes = 200 * 1024 * 1024
    current_paths = {path.relative_to(root).as_posix() for path in _iter_manifest_files(root, suffixes=suffixes, max_file_bytes=max_file_bytes)}
    for rel_path in sorted(current_paths - declared_paths):
        issues.append({"type": "untracked_manifest_file", "path": rel_path})

    chain_result = verify_chain(root)
    if not chain_result.get("ok"):
        issues.append({"type": "chain_verification_failed", "details": chain_result})

    return {
        "ok": not issues,
        "manifest_path": str(path),
        "run_dir": str(root),
        "checked_files": checked_files,
        "declared_files": len(manifest.get("files") or []),
        "root_hash": manifest.get("root_hash", ""),
        "manifest_hash": expected_manifest_hash,
        "issues": issues,
        "chain": chain_result,
    }


def verify_chain(run_dir: str | Path, chain_path: str | Path | None = None) -> Dict[str, Any]:
    """Verify the append-only hash chain under a run directory."""

    root = Path(run_dir).resolve()
    path = Path(chain_path).resolve() if chain_path else root / CHAIN_LOG_FILENAME
    if not path.exists():
        return {"ok": True, "chain_path": str(path), "event_count": 0, "last_hash": ""}

    issues: List[Dict[str, Any]] = []
    previous_hash = ""
    last_hash = ""
    event_count = 0
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception as exc:
                issues.append({"type": "invalid_jsonl", "line": line_number, "error": str(exc)})
                continue
            event_count += 1
            event_hash = str(event.get("event_hash") or "")
            unsigned = dict(event)
            unsigned.pop("event_hash", None)
            calculated = sha256_bytes(canonical_json(unsigned).encode("utf-8"))
            if event_hash != calculated:
                issues.append({"type": "event_hash_mismatch", "line": line_number, "expected": event_hash, "actual": calculated})
            if str(event.get("previous_hash") or "") != previous_hash:
                issues.append(
                    {
                        "type": "previous_hash_mismatch",
                        "line": line_number,
                        "expected": previous_hash,
                        "actual": str(event.get("previous_hash") or ""),
                    }
                )
            previous_hash = event_hash
            last_hash = event_hash

    state_path = root / CHAIN_STATE_FILENAME
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            if str(state.get("last_hash") or "") != last_hash:
                issues.append({"type": "chain_state_mismatch", "expected": last_hash, "actual": str(state.get("last_hash") or "")})
        except Exception as exc:
            issues.append({"type": "chain_state_parse_error", "error": str(exc)})

    return {
        "ok": not issues,
        "chain_path": str(path),
        "event_count": event_count,
        "last_hash": last_hash,
        "issues": issues,
    }


def build_workspace_manifest(workspace: str | Path, **metadata: Any) -> Dict[str, Any]:
    """Convenience wrapper for script-workspace manifests."""

    return build_manifest(workspace, **metadata)


def verify_workspace_manifest(workspace: str | Path) -> Dict[str, Any]:
    return verify_manifest(workspace)


def _iter_manifest_files(root: Path, *, suffixes: set[str], max_file_bytes: int) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in DEFAULT_EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in DEFAULT_EXCLUDE_FILES:
            continue
        if path.suffix.lower() not in suffixes:
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        yield path


def _manifest_root_hash(files: List[Dict[str, Any]]) -> str:
    payload = [
        {
            "path": str(item.get("path") or ""),
            "size_bytes": int(item.get("size_bytes") or 0),
            "sha256": str(item.get("sha256") or ""),
        }
        for item in files
    ]
    payload.sort(key=lambda item: item["path"])
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _read_last_chain_state(chain_path: Path) -> Tuple[str, int]:
    last_hash = ""
    sequence = 0
    if not chain_path.exists():
        return last_hash, sequence
    with chain_path.open("r", encoding="utf-8-sig") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            last_hash = str(event.get("event_hash") or "")
            try:
                sequence = int(event.get("sequence") or sequence)
            except Exception:
                pass
    return last_hash, sequence


def safe_case_id(text: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", text.strip())
    return value.strip("._-")[:120]
