# ForensiFlow Codex Mobile Agent

This package is the canonical exploration agent for ForensiFlow mobile forensic tasks. It handles low-similarity tasks where the replay path cannot safely reuse an existing template.

Core responsibilities:

- Android UI navigation with one safe action per step.
- Target-page confirmation.
- Workspace context capture.
- Extraction script generation, execution, diagnosis, and repair.
- `records.json` and `records_debug.json` validation.
- Export of successful runs into reusable ForensiFlow artifacts.

## Layout

- `cli.py`: command-line entrypoint.
- `runtime.py`: native OpenAI-compatible runtime (`CodexMobileRuntime`) used when not delegating the full task to Codex CLI.
- `codex_agent.py`: bridges ForensiFlow to Codex CLI and the `$forensiflow-mobile-agent` skill.
- `controller.py`: Android UI XML, tap, swipe, back, wait, and app launch control.
- `script_tools.py`: script workspace read/write/patch/run/inspect helpers.
- `prompts.py`: runtime prompt construction.
- `schema.py`: session and context dataclasses.
- `rag_export.py`: export successful runs into reusable templates/scripts.

## Canonical Command

```bash
python -m runner.forensiflow.agents.codex_mobile.cli \
  --device-serial <serial> \
  --package-name com.whatsapp \
  --app-name WhatsApp \
  --target "提取联系人示例对象的所有聊天记录" \
  --agent-backend codex
```

Old imports and commands under `page_agent_mobile` remain as compatibility wrappers.

## Run Outputs

Full Codex-agent runs default to:

```text
data/codex_mobile_agent_runs/<device_serial>/codex_full_agent_run_<timestamp>/
```

Native runtime runs default to:

```text
data/codex_mobile_agent_runs/<device_serial>/codex_mobile_agent_run_<timestamp>/
```

Do not package run directories, API keys, or device-specific logs as source code.

## Environment

Preferred variables:

- `FORENSIFLOW_MOBILE_AGENT_BACKEND=codex`
- `FORENSIFLOW_CODEX_RUN_ROOT=data/codex_mobile_agent_runs`
- `FORENSIFLOW_CODEX_FULL_TIMEOUT_SECONDS=1800`
- `FORENSIFLOW_CODEX_SCRIPT_TIMEOUT_SECONDS=900`
- `FORENSIFLOW_MOBILE_AGENT_MAX_OUTPUT_TOKENS=12288`
- `FORENSIFLOW_MOBILE_AGENT_RAW_SCRIPT_MAX_OUTPUT_TOKENS=49152`

Legacy `PAGE_AGENT_MOBILE_*` variables are still supported.

## Safety

Treat the connected phone as an evidence source. Navigation and generated scripts should read UI state and write local artifacts only. Do not send messages, delete data, call, pay, authorize, clear history, search inside apps, type into fields, or change settings unless the operator explicitly approves that action.
