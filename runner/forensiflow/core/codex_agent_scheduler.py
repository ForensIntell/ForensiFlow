"""ForensiFlow Codex mobile-agent scheduler.

This adapter keeps the planner and scheduler-selector contract stable while
routing low-similarity mobile forensic tasks to the Codex-backed agent runtime.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from runner.forensiflow.agents.codex_mobile.codex_agent import run_codex_forensiflow_full_agent
from runner.forensiflow.agents.codex_mobile.runtime import CodexMobileRuntime
from runner.forensiflow.core.config import DEFAULT_MIMO_API_BASE, DEFAULT_MIMO_MODEL, get_llm_config


logger = logging.getLogger(__name__)


class CodexAgentScheduler:
    """Adapter exposing the same high-level methods as the legacy scheduler."""

    DEFAULT_API_BASE = DEFAULT_MIMO_API_BASE
    DEFAULT_MODEL = DEFAULT_MIMO_MODEL

    def __init__(
        self,
        device: Any,
        api_key: str,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_steps: int = 60,
        data_dir: str = "./data",
        llm_timeout_seconds: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        raw_script_max_output_tokens: Optional[int] = None,
        tool_choice_mode: str = "auto",
        reasoning_log_chars: int = 2000,
        script_agent: str = "native",
        agent_backend: str = "codex",
    ) -> None:
        llm_config = get_llm_config(api_key=api_key, api_base=api_base, model=model)
        self.device = device
        self.api_key = llm_config.api_key
        self.api_base = llm_config.api_base or self.DEFAULT_API_BASE
        self.model = llm_config.model or self.DEFAULT_MODEL
        self.temperature = temperature
        self.max_steps = max_steps
        self.data_dir = data_dir
        self.llm_timeout_seconds = llm_timeout_seconds or _env_int("FORENSIFLOW_MOBILE_AGENT_LLM_TIMEOUT_SECONDS", _env_int("PAGE_AGENT_MOBILE_LLM_TIMEOUT_SECONDS", 120))
        self.max_output_tokens = max_output_tokens or _env_int("FORENSIFLOW_MOBILE_AGENT_MAX_OUTPUT_TOKENS", _env_int("PAGE_AGENT_MOBILE_MAX_OUTPUT_TOKENS", 12288))
        self.raw_script_max_output_tokens = raw_script_max_output_tokens or _env_int(
            "FORENSIFLOW_MOBILE_AGENT_RAW_SCRIPT_MAX_OUTPUT_TOKENS",
            _env_int("PAGE_AGENT_MOBILE_RAW_SCRIPT_MAX_OUTPUT_TOKENS", 49152),
        )
        self.tool_choice_mode = (
            os.getenv("FORENSIFLOW_MOBILE_AGENT_TOOL_CHOICE_MODE")
            or os.getenv("PAGE_AGENT_MOBILE_TOOL_CHOICE_MODE")
            or tool_choice_mode
        )
        self.reasoning_log_chars = _env_int(
            "FORENSIFLOW_MOBILE_AGENT_REASONING_LOG_CHARS",
            _env_int("PAGE_AGENT_MOBILE_REASONING_LOG_CHARS", reasoning_log_chars),
        )
        self.script_agent = (
            os.getenv("FORENSIFLOW_CODEX_SCRIPT_AGENT")
            or os.getenv("PAGE_AGENT_MOBILE_SCRIPT_AGENT")
            or script_agent
        )
        self.agent_backend = (
            os.getenv("FORENSIFLOW_MOBILE_AGENT_BACKEND")
            or os.getenv("PAGE_AGENT_MOBILE_AGENT_BACKEND")
            or agent_backend
        )
        self._last_result: Optional[Dict[str, Any]] = None

    def run_task(self, task: str, max_steps: Optional[int] = None) -> Dict[str, Any]:
        return self.run_forensic_task(task_description=task, max_steps=max_steps)

    def run_forensic_task(
        self,
        package_name: Optional[str] = None,
        app_name: Optional[str] = None,
        task_description: str = "",
        constraint: str = "",
        max_steps: Optional[int] = None,
    ) -> Dict[str, Any]:
        device_serial = self._device_serial()
        timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        run_root = Path(
            os.getenv("FORENSIFLOW_CODEX_RUN_ROOT")
            or os.getenv("PAGE_AGENT_MOBILE_RUN_ROOT")
            or "data/codex_mobile_agent_runs"
        )
        run_dir = run_root / device_serial / f"codex_mobile_agent_run_{timestamp}"

        model_extra_body = self._model_extra_body()
        logger.info("\n%s", "=" * 60)
        logger.info("ForensiFlow Codex Agent Scheduler started")
        logger.info("Run directory: %s", run_dir)
        logger.info("App: %s (%s)", app_name or "Unknown", package_name or "")
        logger.info("Task: %s", task_description)
        if constraint:
            logger.info("Constraint: %s", constraint)
        logger.info("Model: %s", self.model)
        logger.info("%s\n", "=" * 60)

        if self.agent_backend == "codex":
            result = run_codex_forensiflow_full_agent(
                device_serial=device_serial,
                package_name=package_name or "",
                app_name=app_name or "Unknown",
                target=task_description,
                constraint=constraint,
                run_root=run_root,
                timeout_seconds=_env_int(
                    "FORENSIFLOW_CODEX_FULL_TIMEOUT_SECONDS",
                    _env_int("PAGE_AGENT_MOBILE_CODEX_FULL_TIMEOUT_SECONDS", 1800),
                ),
                model=os.getenv("FORENSIFLOW_CODEX_MODEL") or os.getenv("PAGE_AGENT_MOBILE_CODEX_MODEL") or self.model or "",
                prompt_mode=os.getenv("FORENSIFLOW_CODEX_PROMPT_MODE", "simple"),
            )
            self._last_result = result
            return self._to_executor_result(
                {
                    "success": bool(result.get("ok")),
                    "run_dir": result.get("run_dir", ""),
                    "script_workspace": result.get("workspace", ""),
                    "last_run_state": {
                        "records_exists": result.get("records_exists"),
                        "records_debug_exists": result.get("records_debug_exists"),
                        "records_count": result.get("records_count", 0),
                        "records_debug_count": result.get("records_debug_count", 0),
                        "run_state_status": result.get("run_state_status", ""),
                        "run_state_errors": result.get("run_state_errors", []),
                    },
                    "reuse_artifacts": result.get("reuse_artifacts"),
                    "reason": result.get("error") or "",
                    "raw_codex_result": result,
                }
            )

        runtime = CodexMobileRuntime(
            device=self.device,
            api_key=self.api_key,
            api_base=self.api_base,
            model=self.model,
            run_dir=run_dir,
            app_name=app_name or "Unknown",
            package_name=package_name or "",
            target=task_description,
            constraint=constraint,
            device_serial=device_serial,
            max_steps=max_steps or self.max_steps,
            temperature=self.temperature,
            llm_timeout_seconds=self.llm_timeout_seconds,
            max_output_tokens=self.max_output_tokens,
            raw_script_max_output_tokens=self.raw_script_max_output_tokens,
            model_extra_body=model_extra_body,
            tool_choice_mode=self.tool_choice_mode,
            reasoning_log_chars=self.reasoning_log_chars,
            script_agent=self.script_agent,
        )

        result = runtime.run()
        self._last_result = result
        return self._to_executor_result(result)

    def _to_executor_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        success = bool(result.get("success"))
        last_run_state = result.get("last_run_state") if isinstance(result.get("last_run_state"), dict) else {}
        script_generation = {
            "success": success and bool(last_run_state.get("records_exists", success)),
            "records_count": last_run_state.get("records_count", 0),
            "run_state": last_run_state,
            "workspace": result.get("script_workspace", ""),
            "reuse_artifacts": result.get("reuse_artifacts"),
        }
        return {
            "completed": success,
            "navigation_completed": bool(result.get("navigation_completed", success)),
            "script_generation": script_generation,
            "total_steps": result.get("total_steps", 0),
            "history": result.get("history", []),
            "data_dir": result.get("run_dir", ""),
            "run_dir": result.get("run_dir", ""),
            "phase": result.get("phase", ""),
            "last_run_state": last_run_state,
            "reuse_artifacts": result.get("reuse_artifacts"),
            "error": "" if success else str(result.get("reason") or result.get("error") or ""),
            "raw_result": result,
        }

    def _device_serial(self) -> str:
        serial = getattr(self.device, "device_serial", "") or ""
        if serial:
            return str(serial)
        raw = getattr(self.device, "d", None)
        try:
            serial = getattr(raw, "serial", "") or ""
        except Exception:
            serial = ""
        return str(serial or "unknown_device")

    def _model_extra_body(self) -> Optional[Dict[str, Any]]:
        if _env_bool("FORENSIFLOW_MOBILE_AGENT_DISABLE_EXTRA_BODY", _env_bool("PAGE_AGENT_MOBILE_DISABLE_EXTRA_BODY", False)):
            return None
        if "api.deepseek.com" in (self.api_base or ""):
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": os.getenv("FORENSIFLOW_MOBILE_AGENT_REASONING_EFFORT") or os.getenv("PAGE_AGENT_MOBILE_REASONING_EFFORT", "high"),
            }
        return None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Environment variable %s=%r is not an integer; using default %s", name, value, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Backward compatibility for historical imports.
PageAgentMobileScheduler = CodexAgentScheduler
