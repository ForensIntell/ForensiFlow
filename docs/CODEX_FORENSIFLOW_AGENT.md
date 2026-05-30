# Codex ForensiFlow Agent

Codex is the current exploration backend for ForensiFlow mobile forensic tasks. It uses the local `$forensiflow-mobile-agent` skill to navigate Android UI, confirm target pages, generate and repair extraction scripts, run them, and validate `records.json` plus `records_debug.json`.

## Canonical CLI

```bash
python -m runner.forensiflow.agents.codex_mobile.cli \
  --device-serial <DEVICE_SERIAL> \
  --package-name com.whatsapp \
  --app-name WhatsApp \
  --target "提取联系人示例对象的所有聊天记录" \
  --agent-backend codex
```

The old command remains compatible:

```bash
python -m page_agent_mobile.cli --help
```

## Environment

Preferred variables:

```bash
export FORENSIFLOW_MOBILE_AGENT_BACKEND=codex
export FORENSIFLOW_CODEX_RUN_ROOT=data/codex_mobile_agent_runs
export FORENSIFLOW_CODEX_FULL_TIMEOUT_SECONDS=1800
export FORENSIFLOW_CODEX_SCRIPT_TIMEOUT_SECONDS=900
```

Legacy `PAGE_AGENT_MOBILE_*` variables are still read for compatibility.

## Direct Full-Agent Runner

```bash
python tools/run_codex_forensiflow_full_agent.py \
  --device-serial <DEVICE_SERIAL> \
  --package-name com.whatsapp \
  --app-name WhatsApp \
  --target "提取 WhatsApp 中示例对象聊天记录"
```

To reproduce a hand-tested prompt:

```bash
FORENSIFLOW_CODEX_MANUAL_PROMPT='使用 $forensiflow-mobile-agent skills完成提取 WhatsApp 中示例对象聊天记录的任务' \
python tools/run_codex_forensiflow_full_agent.py \
  --device-serial <DEVICE_SERIAL> \
  --package-name com.whatsapp \
  --app-name WhatsApp \
  --target "提取 WhatsApp 中示例对象聊天记录" \
  --prompt-mode manual
```

## Python API

```python
from runner.forensiflow.agents.codex_mobile.codex_agent import run_codex_forensiflow_full_agent

result = run_codex_forensiflow_full_agent(
    device_serial="<DEVICE_SERIAL>",
    package_name="com.whatsapp",
    app_name="WhatsApp",
    target="提取联系人示例对象的所有聊天记录",
)
```

Script-workspace repair remains available:

```python
from runner.forensiflow.agents.codex_mobile.codex_agent import run_codex_forensiflow_agent

result = run_codex_forensiflow_agent(script_workspace, target="提取联系人示例对象的所有聊天记录")
```

Compatibility imports from `page_agent_mobile.codex_agent` still work.

## Runtime Outputs

New runs default to:

```text
data/codex_mobile_agent_runs/<device_serial>/codex_full_agent_run_<timestamp>/
```

Important files:

- `script_workspace/workspace_context.json`
- `script_workspace/generated_script.py`
- `script_workspace/run_state.json`
- `script_workspace/records.json`
- `script_workspace/records_debug.json`
- `evidence_manifest.json`
- `evidence_chain.jsonl`
- `evidence_chain_state.json`
- `script_workspace/codex_agent/result.json`
- `script_workspace/codex_agent/stdout.txt`
- `script_workspace/codex_agent/stderr.txt`

Verify integrity after a run:

```bash
python tools/verify_evidence_integrity.py <run_dir>
```

## Local Codex Setup

- `CODEX_HOME`: `<REPO_ROOT>/.codex-forensiflow-agent`
- skill: `$forensiflow-mobile-agent`
- local MIMO Responses proxy: `http://127.0.0.1:8788/v1`
- preferred local source-built binary:
  `external/codex/codex-rs/target/forensiflow/release/codex`
- fallback wrapper:
  `external/codex/codex-cli/bin/codex.js`

Runner resolution order:

1. `FORENSIFLOW_CODEX_BIN`, if set.
2. The local source-built binary above, if it exists.
3. The Node `codex.js` wrapper and its npm/native Codex release.

To force the old wrapper path for comparison:

```bash
FORENSIFLOW_CODEX_DISABLE_SOURCE_BIN=1 python tools/run_codex_forensiflow_full_agent.py ...
```

Full mobile control requires `danger-full-access` because ADB and uiautomator2 use local sockets. Script-workspace repair defaults to `workspace-write`.
