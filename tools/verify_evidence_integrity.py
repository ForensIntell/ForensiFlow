#!/usr/bin/env python3
"""Build or verify ForensiFlow evidence integrity manifests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from runner.forensiflow.core.evidence_integrity import build_manifest, verify_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or verify ForensiFlow evidence integrity manifests.")
    parser.add_argument("path", type=Path, help="Run directory or script_workspace directory.")
    parser.add_argument("--write", action="store_true", help="Build and write evidence_manifest.json before verifying.")
    parser.add_argument("--case-id", default="")
    parser.add_argument("--device-serial", default="")
    parser.add_argument("--app-name", default="")
    parser.add_argument("--package-name", default="")
    parser.add_argument("--target", default="")
    parser.add_argument("--manifest", type=Path, default=None, help="Optional manifest path for verification.")
    parser.add_argument("--json", action="store_true", help="Print full JSON result.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    target_path = args.path.resolve()
    if not target_path.exists():
        raise SystemExit(f"path not found: {target_path}")

    built = None
    if args.write:
        built = build_manifest(
            target_path,
            case_id=args.case_id,
            device_serial=args.device_serial,
            app_name=args.app_name,
            package_name=args.package_name,
            target=args.target,
        )

    result = verify_manifest(target_path, args.manifest)
    if built is not None:
        result["built_manifest"] = {
            "file_count": built.get("file_count"),
            "root_hash": built.get("root_hash"),
            "manifest_hash": built.get("manifest_hash"),
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "OK" if result.get("ok") else "FAILED"
        print(f"{status}: {result.get('manifest_path', '')}")
        print(f"files: {result.get('checked_files', 0)}/{result.get('declared_files', 0)}")
        print(f"root_hash: {result.get('root_hash', '')}")
        issues = result.get("issues") or []
        if issues:
            print("issues:")
            for issue in issues[:20]:
                print("  - " + json.dumps(issue, ensure_ascii=False, sort_keys=True))
            if len(issues) > 20:
                print(f"  ... {len(issues) - 20} more")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
