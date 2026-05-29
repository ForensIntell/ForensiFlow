"""Backward-compatible imports for the old page_agent_mobile package.

The maintained implementation lives in runner.forensiflow.agents.codex_mobile.
"""

from runner.forensiflow.agents.codex_mobile import CodexMobileRuntime, PageAgentMobileRuntime

__all__ = ["CodexMobileRuntime", "PageAgentMobileRuntime"]
