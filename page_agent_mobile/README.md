# page_agent_mobile Compatibility Package

The active ForensiFlow mobile agent implementation has moved to:

```text
runner/forensiflow/agents/codex_mobile/
```

This package remains as a compatibility layer for older commands and imports:

```bash
python -m page_agent_mobile.cli --help
```

New code should import from `runner.forensiflow.agents.codex_mobile`.

Canonical CLI:

```bash
python -m runner.forensiflow.agents.codex_mobile.cli --help
```
