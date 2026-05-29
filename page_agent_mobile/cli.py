"""Compatibility CLI for the old page_agent_mobile module path."""

from runner.forensiflow.agents.codex_mobile.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
