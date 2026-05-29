---
name: forensiflow-mobile-agent
description: Mobile forensic Android extraction workflow for ForensiFlow/PageAgent tasks. Use when generating, repairing, or reviewing mobile app extraction agents/scripts, Android uiautomator XML parsers, records.json/records_debug.json outputs, WhatsApp/chat/history/contact/order extraction, scrolling/timeline/list-detail extraction, deduplication, or provenance/debug quality checks.
---

# ForensiFlow Mobile Agent

Use this skill to build or repair a mobile forensic extraction flow after an Android app has been navigated to a target page, or to analyze logs/results from `page_agent_mobile`.

## Operating Model

1. Treat the phone and app as evidence sources. Do not send messages, delete data, call, pay, authorize, clear history, search inside apps, use search boxes, type text into fields, or change settings.
2. Separate the flow into navigation, exploration, script generation, script run, diagnosis, and repair.
3. Do not invent helper APIs. Generated scripts may use standard Python, `xml.etree.ElementTree`, environment variables listed in `references/script-rules.md`, `uiautomator2`, `adb`, and local files.
4. Prefer robust XML/block extraction over brittle field whitelists. Preserve unknown but relevant business content in `raw_components`.
5. Validate outputs before declaring success. `records.json` alone is not enough; `records_debug.json` with per-record provenance is required.

## Completion Contract

This skill is used by automated runners, not only interactive chat.

- A single invocation must execute the whole workflow end to end: navigate if needed, explore, generate or repair the script, run it, validate outputs, and finish with usable artifacts.
- Do not stop after announcing the next step, listing a plan, confirming the current page, or saying what you are about to do. Continue executing commands until the task is complete or a concrete blocker prevents progress.
- If previous artifacts exist in the workspace, inspect them and continue from the latest useful state instead of restarting or replaying prior logs.
- Completion means `action_path.json`, `generated_script.py`, `records.json`, and `records_debug.json` exist in the active workspace, represent the requested target, and pass the validation reasoning below. If they do not exist, keep working.
- `action_path.json` must be reusable by the RAG library. Prefer this top-level shape: `{"schema_version":"forensiflow-action-path-v1","app_name":"...","package_name":"...","target":"...","actions":[...]}`. Each action should use one of `launch_app`, `tap`/`click`, `swipe`, `wait`, `back`/`press_back`, `run_script`; include stable `target` text for taps/clicks instead of bare coordinates whenever possible. The first action launches `package_name`; the final action is `{"action":"run_script","script_path":"generated_script.py"}`.
- Keep final artifact paths canonical inside `FORENSIFLOW_AGENT_WORKSPACE` / `script_workspace`: `action_path.json`, `generated_script.py`, `script_index.json` if available, `records.json`, `records_debug.json`, `run_state.json`, and `workspace_context.json`. Do not write the reusable final files only under nested temp/debug directories.
- If blocked, write the reason and the last useful state to stdout and any available debug artifact; do not report success.

## Reference Loading

Load only the references needed for the current task:

- For choosing task type or writing `workspace_context.json`: read `references/task-patterns.md`.
- For generating or repairing `generated_script.py`: read `references/script-rules.md`.
- For WhatsApp chat records or any chat timeline: read `references/whatsapp-chat.md` and `references/script-rules.md`.
- For output quality, deduplication, provenance, or diagnostics: read `references/output-validation.md`.

## Workflow

1. Confirm the target page boundary. For chat records, navigation is complete only when the toolbar/contact matches the target and message rows are visible.
2. Classify the extraction pattern using only the allowed pattern names in `references/task-patterns.md`.
3. Write or repair `workspace_context.json` with structured `ui_observations`, `extraction_inference`, and `extraction_plan`; do not use unsupported pattern names.
4. Write `action_path.json` with replayable actions from app launch to target page and final `run_script`.
5. Generate a target-page extraction script that verifies the boundary, reads workspace XML first, then optionally dumps live XML via `uiautomator2`.
6. Run the action path or manually follow it, run the script, and inspect `run_state.json`, `stdout.txt`, `stderr.txt`, `records.json`, and `records_debug.json`.
7. Patch the specific failing function. Do not repeatedly rewrite the whole script unless the architecture is fundamentally wrong.
8. Finish only when `records.json` is deduplicated and clean, `records_debug.json` maps one-to-one to records, and diagnostics are pass/warn with understood risk.

## Hard Requirements

- `extraction_pattern` must be one of: `STATIC_SCREEN`, `SCROLL_LIST`, `REVERSE_TIMELINE`, `FORWARD_TIMELINE`, `LIST_DETAIL`, `PAGINATED_LIST`, `MULTI_SECTION`, `MULTI_LEVEL_DETAIL`, `UNKNOWN`.
- Navigation must not use app search features or search boxes, and must not input/type text into the device. Use only safe observation, tap, back, wait, and scroll/swipe actions unless explicitly approved.
- Chat records default to `REVERSE_TIMELINE`. From the bottom/latest message, use hand `finger_down` to fetch earlier messages above.
- Do not use names such as `SCROLL_AND_EXTRACT`, `scroll_and_extract_list_items`, or custom patterns unless the codebase explicitly supports them.
- Do not generate scripts that call undefined helpers like `scroll_to_top()`, `get_current_xml()`, `is_at_bottom()`, or `swipe_up()` unless the script defines them.
- Final `records.json` must not contain `_debug`, bounds, source paths, row/page/scroll indexes, or dedup keys.
- `records_debug.json` must contain the same records plus `_debug` provenance.

## Validation Helper

Run the bundled checker when reviewing outputs:

```bash
python "$CODEX_HOME/skills/forensiflow-mobile-agent/scripts/validate_records.py" /path/to/script_workspace
```

Use its findings as a fast pre-check, not as a substitute for task-specific reasoning.
