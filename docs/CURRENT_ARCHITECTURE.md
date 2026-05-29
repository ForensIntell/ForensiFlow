# ForensiFlow Current Architecture

Last updated: 2026-05-24

This document describes the current mainline structure after the Codex mobile-agent refactor. The project keeps backward-compatible wrappers for old imports, but new code should use the canonical ForensiFlow/Codex names below.

## Main Flow

```text
run_end_to_end.py / run_forensic_plan.py
  -> ForensicTaskExecutor
  -> Route Selector
  -> Experience Matcher
  -> similarity >= threshold: Replay Runner
  -> similarity < threshold: Codex Agent Scheduler
  -> Codex mobile agent navigates, extracts, validates, and exports reusable artifacts
```

## Canonical Modules

| Module | Path | Responsibility |
| --- | --- | --- |
| Case Planner | `auto_forensic_planning.py`, `runner/forensiflow/core/forensic_planner.py` | Generate structured forensic plans from case background and goals. |
| Task Executor | `run_forensic_plan.py`, `run_end_to_end.py` | Execute tasks from a generated plan. |
| Route Selector | `runner/forensiflow/core/scheduler_selector.py` | Select replay or exploration based on template similarity. |
| Experience Matcher | `runner/forensiflow/core/rag_template_matcher.py` | Retrieve historical task templates. |
| Replay Runner | `runner/forensiflow/core/scheduler_vt.py` | Reuse high-similarity historical templates, with XML matching and ForensiVision fallback. |
| Codex Agent Scheduler | `runner/forensiflow/core/codex_agent_scheduler.py` | Adapter from planner tasks to the Codex-backed mobile agent. |
| Codex Mobile Agent | `runner/forensiflow/agents/codex_mobile/` | Navigation, script generation, script execution, repair, validation, and artifact export. |
| Script Registry | `runner/forensiflow/core/script_registry.py` | Manage reusable generated and built-in extraction scripts. |
| Device Bridge | `runner/forensiflow/devices/android.py` | Android connection, UI XML, screenshots, taps, swipes, and app launching. |

## Compatibility Paths

These paths remain to avoid breaking old commands, generated artifacts, and archived experiments:

- `page_agent_mobile/`
- `runner/forensiflow/core/page_agent_mobile_scheduler.py`
- `PageAgentMobileRuntime`
- `PageAgentMobileScheduler`
- `PAGE_AGENT_MOBILE_*` environment variables

New code should prefer:

- `runner.forensiflow.agents.codex_mobile`
- `runner.forensiflow.core.codex_agent_scheduler.CodexAgentScheduler`
- `CodexMobileRuntime`
- `FORENSIFLOW_*` and `FORENSIFLOW_CODEX_*` environment variables

## Data Boundaries

Do not casually move or rewrite these directories:

- `data/`: real run data, device-specific outputs, script workspaces, and generated registries.
- `artifacts/`: manual or debugging outputs.
- `external/rag_templates/`: reusable templates and provenance records.
- `runner/forensiflow/scripts/generated/`: generated extraction scripts and registry metadata.
- `archive/` and `old/`: historical material kept for audit and migration reference.
- `.codex-forensiflow-agent/`: local Codex home, auth, sessions, and proxy state.

Historical generated scripts and registries may still mention `page_agent_mobile` or old absolute paths. Treat those as provenance unless a dedicated data migration task is requested.

## Current Entry Points

```bash
python auto_forensic_planning.py --help
python run_forensic_plan.py --help
python run_end_to_end.py --help
python tools/test_experience_reuse.py --list
python tools/test_direct_scheduler.py --help
python -m runner.forensiflow.agents.codex_mobile.cli --help
```

The old CLI still works:

```bash
python -m page_agent_mobile.cli --help
```
