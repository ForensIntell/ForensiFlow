# Project Cleanup Notes

Last updated: 2026-05-24

This document records the project structure decisions used before the next experiment round. It is intentionally conservative: runtime behavior, model assets, generated scripts, RAG templates, and historical experiment data are preserved unless a future task explicitly says otherwise.

## Current Mainline

- `run_end_to_end.py`: end-to-end entrypoint for planning and execution.
- `auto_forensic_planning.py`: planning-only entrypoint.
- `run_forensic_plan.py`: execution-only entrypoint for an existing plan.
- `runner/forensiflow/`: core device bridge, planner, route selector, replay runner, script registry, and extraction scripts.
- `runner/forensiflow/agents/codex_mobile/`: canonical Codex mobile-agent runtime and script-generation tooling.
- `page_agent_mobile/`: backward-compatible wrapper for old imports and commands.
- `forensiflow-web/`: React/Vite frontend prototype. It is not yet connected to the Python execution layer.
- `tools/`: Codex agent wrappers and support utilities.
- `external/ForensiVision/`, `external/models/`, `external/rag_templates/`: required local assets for replay, matching, and reuse.
- `data/`, `artifacts/`: local experiment data and debugging output. Treat as evidence-like runtime material.
- `runner/forensiflow/core/evidence_integrity.py`: SHA-256 manifest and hash-chain helpers for experiment artifact integrity.

## Cleanup Policy

Safe to remove when needed:

- Python bytecode caches: `__pycache__/`, `*.pyc`, `*.pyo`.
- frontend build output: `forensiflow-web/dist/`.
- transient logs such as `*.log`, after checking they are not part of an active run.
- package-manager caches outside the committed source tree.

Do not remove without an explicit task:

- `data/` and `artifacts/`.
- `.env`, `.env.mimo`, and local Codex auth/config files.
- `external/models/` and `external/ForensiVision/pt_model/`.
- `external/rag_templates/`.
- `runner/forensiflow/scripts/generated/` and generated script registries.
- `archive/`, `old/`, and external source checkouts unless a migration/deprecation decision has been made.

## Known Structure Issues

- The frontend currently uses mock data and has no backend API wiring.
- Some generated RAG templates and generated script metadata contain old absolute paths from `<REPO_ROOT> and old `page_agent_mobile` names. They are preserved for provenance; runtime lookup should prefer current repo-relative registry paths where available.
- `data/` is large and mixed: it contains sample data, real run data, debug dumps, generated templates, and device-specific outputs. A future data-retention policy should split these categories.
- The repository contains third-party or vendored trees (`external/codex`, `external/smolagents`, `opencode`). They should be considered external dependencies, not core ForensiFlow code.

## Verification Baseline

After structural cleanup, run at minimum:

```bash
python -m compileall -q auto_forensic_planning.py run_forensic_plan.py run_end_to_end.py runner page_agent_mobile tools tests
python tests/test_auto_planning.py
python auto_forensic_planning.py --help
python run_forensic_plan.py --help
python run_end_to_end.py --help
python -m runner.forensiflow.agents.codex_mobile.cli --help
python -m page_agent_mobile.cli --help
python tools/verify_evidence_integrity.py --help
cd forensiflow-web && npm run build
```
