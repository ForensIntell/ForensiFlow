#!/usr/bin/env python3
"""Export a completed Codex full-agent run into the RAG reuse library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from runner.forensiflow.agents.codex_mobile.rag_export import export_full_agent_reuse_artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="codex_full_agent_run_* directory.")
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--constraint", default="")
    parser.add_argument("--no-publish", action="store_true", help="Only write workspace rag_template.json.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_dir = args.run_dir.resolve()
    workspace = run_dir / "script_workspace"
    if not workspace.is_dir():
        raise SystemExit(f"script_workspace not found under: {run_dir}")
    result = export_full_agent_reuse_artifacts(
        run_dir=run_dir,
        workspace=workspace,
        app_name=args.app_name,
        package_name=args.package_name,
        target=args.target,
        constraint=args.constraint,
        publish=not args.no_publish,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
