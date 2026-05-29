"""Codex-backed mobile forensic runtime.

The runtime observes Android UI state, builds compact LLM prompts, executes one
safe macro action per step, and records the run history for later reuse.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import AuthenticationError, OpenAI, OpenAIError

from .controller import MobilePageController, MobileUIState
from .prompts import SYSTEM_PROMPT, build_user_request
from .schema import AgentSession, MobileAgentContext, compact_json
from . import codex_agent, rag_export, script_tools
from runner.forensiflow.core.evidence_integrity import append_chain_event, build_manifest


logger = logging.getLogger(__name__)


SCRIPT_GUIDANCE_PATH = Path(__file__).resolve().parent / "script_generation_guidance.md"
EXPLORATION_GUIDANCE_PATH = Path(__file__).resolve().parent / "script_exploration_guidance.md"


LOG_PREFIX = "[forensiflow-codex-mobile]"


class CodexMobileRuntime:
    """ForensiFlow Android automation runtime used by the Codex mobile agent."""

    def __init__(
        self,
        device: Any,
        api_key: str,
        api_base: str,
        model: str,
        run_dir: Path,
        app_name: str,
        package_name: str,
        target: str,
        constraint: str = "",
        device_serial: str = "",
        max_steps: int = 50,
        temperature: float = 0.1,
        llm_timeout_seconds: int = 120,
        max_output_tokens: int = 12288,
        raw_script_max_output_tokens: int = 49152,
        model_extra_body: Optional[Dict[str, Any]] = None,
        tool_choice_mode: str = "auto",
        reasoning_log_chars: int = 2000,
        script_agent: str = "native",
    ) -> None:
        self.client = OpenAI(api_key=api_key, base_url=api_base.rstrip("/"))
        self.model = model
        self.temperature = temperature
        self.max_steps = max_steps
        self.llm_timeout_seconds = llm_timeout_seconds
        self.max_output_tokens = max_output_tokens
        self.raw_script_max_output_tokens = max(raw_script_max_output_tokens, max_output_tokens)
        self.model_extra_body = model_extra_body or {}
        self.tool_choice_mode = tool_choice_mode
        self.reasoning_log_chars = reasoning_log_chars
        self.script_agent = (script_agent or "native").strip().lower()
        self.codex_script_invoked = False
        self.session = AgentSession(Path(run_dir))
        self.context = MobileAgentContext(
            device=device,
            session=self.session,
            app_name=app_name,
            package_name=package_name,
            target=target,
            device_serial=device_serial,
        )
        self.constraint = constraint
        self.controller = MobilePageController(device)
        self.history: List[Dict[str, Any]] = []

    def run(self) -> Dict[str, Any]:
        self.session.append_event(
            "run_started",
            {
                "model": self.model,
                "app_name": self.context.app_name,
                "package_name": self.context.package_name,
                "target": self.context.target,
                "constraint": self.constraint,
            },
        )
        append_chain_event(
            self.session.run_dir,
            "run_started",
            {
                "model": self.model,
                "app_name": self.context.app_name,
                "package_name": self.context.package_name,
                "target": self.context.target,
                "constraint": self.constraint,
                "device_serial": self.context.device_serial,
            },
            actor="codex_mobile_runtime",
        )

        final: Dict[str, Any] = {
            "success": False,
            "finished": False,
            "reason": "max steps reached",
            "run_dir": str(self.session.run_dir),
        }

        for step_index in range(1, self.max_steps + 1):
            logger.info("%s step %s/%s", LOG_PREFIX, step_index, self.max_steps)
            try:
                ui_state = self._observe(step_index)
                codex_result = self._maybe_run_codex_script_agent(step_index)
                if codex_result is not None:
                    output = {
                        "evaluation_previous_goal": "Codex script agent 已执行。",
                        "memory": "",
                        "script_context": "script phase delegated to Codex forensiflow-mobile-agent skill.",
                        "next_goal": "根据 Codex 结果结束或回退原生脚本流程。",
                        "action": {
                            "name": "done" if codex_result.get("ok") else "codex_script_agent",
                            "input": {
                                "success": bool(codex_result.get("ok")),
                                "text": str(codex_result.get("reason") or codex_result.get("error") or "Codex script agent finished"),
                            },
                        },
                    }
                    action_result = (
                        {"ok": True, "data": {"success": True, "text": "Codex script agent completed"}, "codex_result": codex_result}
                        if codex_result.get("ok")
                        else codex_result
                    )
                else:
                    output = self._call_agent(step_index, ui_state)
                    action_result = self._execute_action(output.get("action") or {})
            except AuthenticationError as exc:
                final.update({"finished": True, "reason": f"LLM authentication failed: {exc}"})
                self._write_final(final)
                return final
            except OpenAIError as exc:
                final.update({"finished": True, "reason": f"LLM API error: {exc}"})
                self._write_final(final)
                return final
            except KeyboardInterrupt:
                final.update({"finished": True, "reason": "interrupted by user"})
                self._write_final(final)
                raise
            except Exception as exc:
                logger.exception("%s step failed", LOG_PREFIX)
                action_result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                output = {
                    "evaluation_previous_goal": "本步执行时发生运行时异常。",
                    "memory": "",
                    "script_context": "",
                    "next_goal": "根据错误恢复或结束。",
                    "action": {"name": "runtime_error", "input": {}},
                }

            event = self._build_step_event(step_index, output, action_result)
            action_name = (output.get("action") or {}).get("name")
            logger.info(
                "%s action=%s result=%s",
                LOG_PREFIX,
                action_name,
                compact_json(action_result, limit=1200).replace("\n", " "),
            )
            self.history.append(event)
            self.session.append_history(event)
            self.session.append_event("step_completed", event)
            append_chain_event(
                self.session.run_dir,
                "step_completed",
                {
                    "step": step_index,
                    "action": action_name,
                    "ok": bool(action_result.get("ok", False)),
                    "phase": self.context.phase,
                },
                actor="codex_mobile_runtime",
            )

            if action_name == "done":
                data = action_result.get("data") or {}
                reuse_artifacts: Dict[str, Any] = {}
                if bool(data.get("success")):
                    reuse_artifacts = self._export_reuse_artifacts()
                final = {
                    "success": bool(data.get("success")),
                    "finished": True,
                    "reason": str(data.get("text") or ""),
                    "run_dir": str(self.session.run_dir),
                    "navigation_completed": self.context.navigation_completed,
                    "phase": self.context.phase,
                    "script_workspace": str(self.context.script_workspace) if self.context.script_workspace else "",
                    "workspace_context_files": self.context.workspace_context_files,
                    "last_run_state": self.context.last_run_state,
                    "reuse_artifacts": reuse_artifacts,
                }
                self._write_final(final)
                return final

        final.update(
            {
                "navigation_completed": self.context.navigation_completed,
                "phase": self.context.phase,
                "script_workspace": str(self.context.script_workspace) if self.context.script_workspace else "",
                "workspace_context_files": self.context.workspace_context_files,
                "last_run_state": self.context.last_run_state,
            }
        )
        self._write_final(final)
        return final

    def _maybe_run_codex_script_agent(self, step_index: int) -> Optional[Dict[str, Any]]:
        if self.script_agent != "codex":
            return None
        if self.codex_script_invoked:
            return None
        if self.context.phase != "script":
            return None
        gate = script_tools.script_generation_gate(self.context)
        if not gate.get("ok"):
            logger.info("%s codex script agent gated: %s", LOG_PREFIX, compact_json(gate, limit=800).replace("\n", " "))
            return None

        self.codex_script_invoked = True
        timeout = int(os.getenv("FORENSIFLOW_CODEX_SCRIPT_TIMEOUT_SECONDS") or os.getenv("PAGE_AGENT_MOBILE_CODEX_TIMEOUT_SECONDS", "900"))
        logger.info(
            "%s delegating script phase to Codex: workspace=%s timeout=%ss",
            LOG_PREFIX,
            self.context.script_workspace,
            timeout,
        )
        result = codex_agent.run_for_context(self.context, timeout_seconds=timeout)
        self.session.append_event("codex_script_agent", {"step": step_index, "result": result})

        run_state_path = script_tools.script_workspace(self.context) / "run_state.json"
        if run_state_path.exists():
            try:
                self.context.last_run_state = json.loads(run_state_path.read_text(encoding="utf-8-sig"))
            except Exception:
                pass
        return result

    def _observe(self, step_index: int) -> MobileUIState:
        ui_state = self.controller.get_ui_state()
        artifact = self.session.artifact_path(f"ui_step_{step_index:03d}.xml")
        artifact.write_text(ui_state.xml, encoding="utf-8")
        self.context.last_ui_xml = ui_state.xml
        self.context.last_ui_outline = ui_state.content
        self.context.last_ui_artifact = str(artifact)
        self.context.last_xml_signature = script_tools.xml_signature(ui_state.xml)
        self.session.append_event(
            "observation",
            {
                "step": step_index,
                "packages": ui_state.packages,
                "xml_artifact": str(artifact),
                "outline_chars": len(ui_state.content),
                "xml_chars": len(ui_state.xml),
            },
        )
        return ui_state

    def _call_agent(self, step_index: int, ui_state: MobileUIState) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._assemble_user_prompt(step_index, ui_state)},
        ]
        raw_script_mode = self._raw_script_write_mode()
        max_tokens = self.raw_script_max_output_tokens if raw_script_mode else self.max_output_tokens
        args = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "timeout": self.llm_timeout_seconds,
        }
        if raw_script_mode:
            logger.info(
                "%s step %s raw script write mode: max_tokens=%s",
                LOG_PREFIX,
                step_index,
                max_tokens,
            )
        if not raw_script_mode:
            args["tools"] = [self._agent_output_tool()]
            tool_choice = self._initial_tool_choice()
            if tool_choice is not None:
                args["tool_choice"] = tool_choice
        if self.model_extra_body:
            args["extra_body"] = self.model_extra_body
        try:
            response = self.client.chat.completions.create(**args)
        except OpenAIError as exc:
            message = str(exc).lower()
            if "tool_choice" not in message and "named" not in message and "function" not in message:
                raise
            if "tool_choice" not in args:
                raise
            logger.warning("%s named tool_choice failed, retrying with required: %s", LOG_PREFIX, exc)
            args["tool_choice"] = "required"
            try:
                response = self.client.chat.completions.create(**args)
            except OpenAIError as required_exc:
                required_message = str(required_exc).lower()
                if "tool_choice" not in required_message and "required" not in required_message:
                    raise
                logger.warning("%s required tool_choice failed, retrying without tool_choice: %s", LOG_PREFIX, required_exc)
                args.pop("tool_choice", None)
                response = self.client.chat.completions.create(**args)

        choice = response.choices[0]
        message = choice.message
        raw = message.model_dump(exclude_none=True) if hasattr(message, "model_dump") else dict(message)
        diagnostics = self._llm_response_diagnostics(response, raw, choice)
        self.session.append_event("llm_response", {"step": step_index, "message": raw, "diagnostics": diagnostics})
        self.session.append_event("llm_response_diagnostics", {"step": step_index, **diagnostics})
        self._log_llm_message(step_index, raw)
        tool_calls = raw.get("tool_calls") or []
        if tool_calls:
            fn = tool_calls[0].get("function") or {}
            name = str(fn.get("name") or "")
            if name == "AgentOutput":
                return self._parse_agent_output(fn.get("arguments") or "{}", step_index=step_index, source="tool_arguments")
            return self._wrap_direct_tool_call(tool_calls)
        content = raw.get("content") or "{}"
        if raw_script_mode:
            return self._parse_raw_script_output(str(content), step_index=step_index, source="content")
        return self._parse_agent_output(content, step_index=step_index, source="content")

    def _raw_script_write_mode(self) -> bool:
        if self.context.phase != "script":
            return False
        try:
            path = script_tools.workspace_path(self.context, "generated_script.py")
        except Exception:
            return False
        return not path.exists()

    def _parse_raw_script_output(self, text: str, step_index: int = 0, source: str = "content") -> Dict[str, Any]:
        agent_match = re.search(r"<AGENT_OUTPUT>\s*(.*?)\s*</AGENT_OUTPUT>", text or "", flags=re.DOTALL)
        script_match = re.search(r"<BEGIN_SCRIPT>\s*(.*?)\s*<END_SCRIPT>", text or "", flags=re.DOTALL)
        if not agent_match or not script_match:
            self._record_parse_error(
                step_index,
                source,
                text,
                ValueError("raw script output must contain AGENT_OUTPUT and BEGIN_SCRIPT/END_SCRIPT blocks"),
                "raw_script_blocks_missing",
            )
            raise ValueError("raw script output must contain <AGENT_OUTPUT> and <BEGIN_SCRIPT>...<END_SCRIPT>")

        output = self._parse_agent_output(agent_match.group(1), step_index=step_index, source=f"{source}:agent_output")
        action = output.get("action") or {}
        if action.get("name") != "write_script_raw":
            self._record_parse_error(
                step_index,
                source,
                text,
                ValueError("raw script mode requires write_script_raw action"),
                "raw_script_wrong_action",
            )
            raise ValueError("raw script mode requires AgentOutput.action write_script_raw")

        script = script_match.group(1)
        script = self._strip_optional_code_fence(script)
        if not script.strip():
            self._record_parse_error(
                step_index,
                source,
                text,
                ValueError("raw script block is empty"),
                "raw_script_empty",
            )
            raise ValueError("raw script block is empty")
        action_input = dict(action.get("input") or {})
        action_input["content"] = script
        action.setdefault("input", {})
        output["action"] = {"name": "write_script_raw", "input": action_input}
        return output

    def _strip_optional_code_fence(self, script: str) -> str:
        text = script.strip("\n")
        match = re.fullmatch(r"\s*```(?:python|py)?\s*\n(.*?)\n```\s*", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1)
        return script

    def _llm_response_diagnostics(self, response: Any, raw: Dict[str, Any], choice: Any) -> Dict[str, Any]:
        tool_calls = raw.get("tool_calls") or []
        tool_arg_lengths = []
        tool_names = []
        for call in tool_calls:
            fn = call.get("function") or {}
            tool_names.append(str(fn.get("name") or ""))
            tool_arg_lengths.append(len(str(fn.get("arguments") or "")))
        content = str(raw.get("content") or "")
        usage = getattr(response, "usage", None)
        if hasattr(usage, "model_dump"):
            usage_data = usage.model_dump(exclude_none=True)
        elif usage is not None:
            usage_data = dict(usage) if isinstance(usage, dict) else {"raw": str(usage)}
        else:
            usage_data = {}
        return {
            "finish_reason": getattr(choice, "finish_reason", None),
            "has_tool_calls": bool(tool_calls),
            "tool_call_count": len(tool_calls),
            "tool_names": tool_names,
            "tool_argument_lengths": tool_arg_lengths,
            "content_length": len(content),
            "content_starts_with_tool_call": content.lstrip().startswith("<tool_call>"),
            "content_has_agent_output_function": "<function=AgentOutput>" in content,
            "content_open_braces": content.count("{"),
            "content_close_braces": content.count("}"),
            "content_open_quotes": content.count('"'),
            "usage": usage_data,
            "max_output_tokens": self.max_output_tokens,
        }

    def _wrap_direct_tool_call(self, tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        first = tool_calls[0]
        fn = first.get("function") or {}
        name = str(fn.get("name") or "")
        if len(tool_calls) > 1:
            names = [str((call.get("function") or {}).get("name") or "") for call in tool_calls]
            logger.warning(
                "%s model returned multiple direct tool calls %s; executing the first one only",
                LOG_PREFIX,
                names,
            )
        logger.warning(
            "%s model returned direct tool call %s instead of AgentOutput; wrapping as macro action",
            LOG_PREFIX,
            name,
        )
        try:
            payload = json.loads(fn.get("arguments") or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return {
            "evaluation_previous_goal": "模型直接调用了内部动作，runtime 已兼容包装为 AgentOutput。",
            "memory": "",
            "script_context": "",
            "next_goal": f"执行动作 {name} 并在下一步根据结果继续。",
            "action": {"name": name, "input": payload},
        }

    def _log_llm_message(self, step_index: int, raw: Dict[str, Any]) -> None:
        reasoning = raw.get("reasoning_content") or raw.get("reasoning") or ""
        if reasoning and self.reasoning_log_chars:
            text = str(reasoning)
            if len(text) > self.reasoning_log_chars:
                text = text[: self.reasoning_log_chars] + "\n... <reasoning truncated>"
            logger.info("%s step %s reasoning:\n%s", LOG_PREFIX, step_index, text)
        tool_calls = raw.get("tool_calls") or []
        if tool_calls:
            for idx, call in enumerate(tool_calls, 1):
                fn = call.get("function") or {}
                args = str(fn.get("arguments") or "")
                if len(args) > 1200:
                    args = args[:1200] + "... <arguments truncated>"
                logger.info(
                    "%s step %s tool_call[%s]=%s args=%s",
                    LOG_PREFIX,
                    step_index,
                    idx,
                    fn.get("name"),
                    args,
                )
        elif raw.get("content"):
            content = str(raw.get("content") or "")
            logger.info("%s step %s content:\n%s", LOG_PREFIX, step_index, content[:2000])

    def _initial_tool_choice(self) -> Optional[Any]:
        mode = (self.tool_choice_mode or "auto").lower().strip()
        if mode == "none":
            return None
        if mode == "required":
            return "required"
        if mode == "named":
            return {"type": "function", "function": {"name": "AgentOutput"}}
        if mode != "auto":
            logger.warning("%s unknown tool_choice_mode=%s, using auto", LOG_PREFIX, self.tool_choice_mode)
        # DeepSeek reasoner accepts tools but rejects tool_choice. It still returns
        # tool_calls when the prompt and only exposed tool make the contract clear.
        model_hint = self.model.lower()
        if "deepseek" in model_hint or "reasoner" in model_hint:
            return None
        return {"type": "function", "function": {"name": "AgentOutput"}}

    def _parse_agent_output(self, text: str, step_index: int = 0, source: str = "unknown") -> Dict[str, Any]:
        try:
            data = json.loads(text)
        except Exception as first_exc:
            data = self._parse_pseudo_agent_output(text)
            if data is None:
                start = text.find("{")
                end = text.rfind("}")
                if start < 0 or end <= start:
                    self._record_parse_error(step_index, source, text, first_exc, "no_json_object")
                    raise ValueError("model did not call AgentOutput and did not return JSON")
                try:
                    data = json.loads(text[start : end + 1])
                except json.JSONDecodeError as exc:
                    self._record_parse_error(step_index, source, text, exc, "malformed_json_substring")
                    raise ValueError(
                        "model returned malformed AgentOutput JSON, likely from a truncated large action payload; "
                        "retry with write_script using a shorter prototype or patch in smaller focused edits"
                    ) from exc
        if not isinstance(data, dict):
            self._record_parse_error(step_index, source, text, ValueError("AgentOutput must be a JSON object"), "not_object")
            raise ValueError("AgentOutput must be a JSON object")
        action = data.get("action")
        if isinstance(action, str):
            try:
                action = json.loads(action)
            except Exception as exc:
                self._record_parse_error(step_index, source, text, exc, "action_string_malformed_json")
                raise ValueError(
                    "AgentOutput.action was returned as a string and could not be parsed. "
                    "Return action as a JSON object, not a quoted JSON string. Example: "
                    '{"action":{"edit_script":{"relative_path":"generated_script.py","old_string":"...","new_string":"..."}}}. '
                    "For large or quote-heavy code repairs, use replace_script_lines with start_line/end_line/new_text."
                ) from exc
        if not isinstance(action, dict):
            self._record_parse_error(step_index, source, text, ValueError("AgentOutput.action is required"), "missing_action")
            raise ValueError("AgentOutput.action is required")
        data["action"] = self._normalize_action(action)
        data.setdefault("evaluation_previous_goal", "")
        data.setdefault("memory", "")
        data.setdefault("script_context", "")
        data.setdefault("next_goal", "")
        return data

    def _record_parse_error(self, step_index: int, source: str, text: str, exc: Exception, category: str) -> None:
        payload = {
            "step": step_index,
            "source": source,
            "category": category,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "text_length": len(text or ""),
            "head": (text or "")[:1200],
            "tail": (text or "")[-1200:],
            "starts_with_tool_call": (text or "").lstrip().startswith("<tool_call>"),
            "has_agent_output_function": "<function=AgentOutput>" in (text or ""),
            "open_braces": (text or "").count("{"),
            "close_braces": (text or "").count("}"),
            "open_quotes": (text or "").count('"'),
        }
        self.session.append_event("agent_output_parse_error", payload)

    def _parse_pseudo_agent_output(self, text: str) -> Optional[Dict[str, Any]]:
        if "<function=AgentOutput>" not in text:
            return None
        fields: Dict[str, str] = {}
        for name in ("evaluation_previous_goal", "memory", "script_context", "next_goal", "action"):
            pattern = rf"<parameter={re.escape(name)}>(.*?)</parameter>"
            match = re.search(pattern, text, flags=re.DOTALL)
            if match:
                fields[name] = match.group(1).strip()
        if "action" not in fields:
            return None
        try:
            action = json.loads(fields["action"])
        except Exception:
            return None
        return {
            "evaluation_previous_goal": fields.get("evaluation_previous_goal", ""),
            "memory": fields.get("memory", ""),
            "script_context": fields.get("script_context", ""),
            "next_goal": fields.get("next_goal", ""),
            "action": action,
        }

    def _normalize_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if "name" in action:
            payload = action.get("input") or {}
            return {"name": str(action.get("name") or ""), "input": payload if isinstance(payload, dict) else {}}
        action_keys = [key for key in action.keys() if action.get(key) is not None]
        if len(action_keys) != 1:
            raise ValueError("AgentOutput.action must contain exactly one action key")
        name = action_keys[0]
        payload = action.get(name) or {}
        return {"name": str(name), "input": payload if isinstance(payload, dict) else {}}

    def _execute_action(self, action: Dict[str, Any]) -> Dict[str, Any]:
        name = str(action.get("name") or "")
        payload = action.get("input") or {}
        if not isinstance(payload, dict):
            payload = {}
        self.session.append_event("action_started", {"name": name, "input": payload})
        before_signature = self.context.last_xml_signature or script_tools.xml_signature(self.context.last_ui_xml)
        monitor_after = name in {"swipe", "scroll_to_top", "scroll_to_bottom"}

        if name == "launch_app":
            package_name = str(payload.get("package_name") or self.context.package_name)
            return {"ok": True, "result": self.controller.launch_app(package_name)}
        if name == "tap":
            return {
                "ok": True,
                "result": self.controller.tap(
                    int(payload.get("x")),
                    int(payload.get("y")),
                    str(payload.get("target") or ""),
                ),
            }
        if name == "swipe":
            result = {
                "ok": True,
                "result": self.controller.swipe(
                    str(payload.get("direction") or "up"),
                    float(payload.get("scale") or 0.55),
                ),
            }
            return self._attach_action_monitor(name, result, before_signature, str(payload.get("direction") or "up")) if monitor_after else result
        if name == "scroll_to_top":
            result = self.controller.scroll_to_top(
                max_swipes=int(payload.get("max_swipes") or 20),
                stable_rounds=int(payload.get("stable_rounds") or 2),
                scale=float(payload.get("scale") or 0.75),
            )
            return self._attach_action_monitor(name, result, before_signature, "down")
        if name == "scroll_to_bottom":
            result = self.controller.scroll_to_bottom(
                max_swipes=int(payload.get("max_swipes") or 20),
                stable_rounds=int(payload.get("stable_rounds") or 2),
                scale=float(payload.get("scale") or 0.75),
            )
            return self._attach_action_monitor(name, result, before_signature, "up")
        if name == "input_text":
            return {"ok": True, "result": self.controller.input_text(str(payload.get("text") or ""))}
        if name == "press_back":
            return {"ok": True, "result": self.controller.press_back()}
        if name == "wait":
            seconds = max(0.2, min(float(payload.get("seconds") or 1), 15.0))
            time.sleep(seconds)
            return {"ok": True, "result": f"waited {seconds}s"}
        if name == "mark_navigation_complete":
            self.context.navigation_completed = True
            self.context.phase = "exploration"
            workspace_context = script_tools.persist_current_page_context(
                self.context,
                reason="mark_navigation_complete",
            )
            exploration_context = script_tools.bootstrap_workspace_context(
                self.context,
                reason="mark_navigation_complete",
            )
            return {
                "ok": True,
                "result": str(payload.get("evidence") or "navigation complete"),
                "workspace_context": {
                    "current_page_xml": workspace_context.get("xml_path"),
                    "current_page_outline": workspace_context.get("outline_path"),
                    "current_page_context": workspace_context.get("context_path"),
                    "snapshot_page_xml": workspace_context.get("snapshot_xml_path"),
                    "snapshot_page_outline": workspace_context.get("snapshot_outline_path"),
                    "xml_signature": workspace_context.get("xml_signature"),
                    "workspace_context_json": exploration_context.get("path"),
                    "extraction_inference": (exploration_context.get("workspace_context") or {}).get("extraction_inference"),
                },
            }
        if name == "read_latest_ui_xml":
            if self.context.phase == "navigation":
                return {
                    "ok": False,
                    "error": "read_latest_ui_xml is not needed during navigation. The runtime automatically observes the current UI and provides a simplified <ui_state> at the next step after every action.",
                    "hint": "Use the current ui_state to choose a navigation action, or call mark_navigation_complete only after reaching the real extraction page.",
                    "phase": self.context.phase,
                    "navigation_completed": self.context.navigation_completed,
                }
            workspace_context = script_tools.persist_current_page_context(
                self.context,
                reason="read_latest_ui_xml",
            )
            include_content = bool(payload.get("include_content"))
            default_limit = 12000 if self.context.phase == "exploration" else 20000
            max_limit = 20000 if self.context.phase == "exploration" else 40000
            content_limit = max(1000, min(int(payload.get("content_limit") or default_limit), max_limit))
            content = self.context.last_ui_xml[:content_limit] if include_content else ""
            return {
                "ok": True,
                "xml_artifact": self.context.last_ui_artifact,
                "workspace_xml_path": workspace_context.get("xml_path"),
                "workspace_outline_path": workspace_context.get("outline_path"),
                "workspace_snapshot_xml_path": workspace_context.get("snapshot_xml_path"),
                "workspace_snapshot_outline_path": workspace_context.get("snapshot_outline_path"),
                "xml_signature": workspace_context.get("xml_signature"),
                "xml_chars": len(self.context.last_ui_xml),
                "xml_summary": script_tools.summarize_ui_xml(self.context.last_ui_xml),
                "content": content,
                "content_omitted": not include_content,
                "truncated": include_content and len(self.context.last_ui_xml) > content_limit,
                "note": "Full XML is always saved to workspace_xml_path. Do not request full content unless a small exact snippet is needed.",
                "next_step_required": "Call update_workspace_context with ui_observations and extraction_inference before generating scripts.",
            }
        if name == "probe_scroll_position":
            if self.context.phase == "navigation":
                self.context.phase = "exploration"
            return self._probe_scroll_position(payload)
        if name == "update_workspace_context":
            if self.context.phase == "navigation":
                self.context.phase = "exploration"
            return script_tools.update_workspace_context(self.context, payload)
        if name == "read_workspace_context":
            return script_tools.read_workspace_context(self.context)
        if name == "set_extraction_plan":
            if self.context.phase == "navigation":
                self.context.phase = "exploration"
            return script_tools.set_extraction_plan(self.context, payload)
        if name == "codex_script_agent":
            self.context.phase = "script"
            timeout = int(
                payload.get("timeout_seconds")
                or os.getenv("FORENSIFLOW_CODEX_SCRIPT_TIMEOUT_SECONDS")
                or os.getenv("PAGE_AGENT_MOBILE_CODEX_TIMEOUT_SECONDS", "900")
            )
            result = codex_agent.run_for_context(self.context, timeout_seconds=timeout)
            run_state_path = script_tools.script_workspace(self.context) / "run_state.json"
            if run_state_path.exists():
                try:
                    self.context.last_run_state = json.loads(run_state_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    pass
            return result
        if name == "write_script_raw":
            gate = script_tools.script_generation_gate(self.context)
            if not gate.get("ok") and not bool(payload.get("force")):
                return gate
            self.context.phase = "script"
            return script_tools.write_script(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                content=str(payload.get("content") or ""),
                overwrite=True if "overwrite" not in payload else bool(payload.get("overwrite")),
            )
        if name == "read_script":
            self.context.phase = "script"
            return script_tools.read_script(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                offset=int(payload.get("offset") or 1),
                limit=int(payload.get("limit") or script_tools.DEFAULT_SCRIPT_READ_LIMIT),
            )
        if name == "read_script_index":
            self.context.phase = "script"
            return script_tools.read_script_index(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
            )
        if name == "grep_script":
            self.context.phase = "script"
            return script_tools.grep_script(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                pattern=str(payload.get("pattern") or ""),
                case_sensitive=True if "case_sensitive" not in payload else bool(payload.get("case_sensitive")),
                context_lines=int(payload.get("context_lines") or 2),
                max_matches=int(payload.get("max_matches") or script_tools.MAX_GREP_MATCHES),
                regex=True if "regex" not in payload else bool(payload.get("regex")),
            )
        if name == "write_script":
            gate = script_tools.script_generation_gate(self.context)
            if not gate.get("ok") and not bool(payload.get("force")):
                return gate
            content = str(payload.get("content") or "")
            if len(content) > 12000:
                return {
                    "ok": False,
                    "error": "large write_script.content is disabled because JSON tool arguments are fragile for long code. Use write_script_raw with <BEGIN_SCRIPT>...<END_SCRIPT> raw protocol for the first complete script.",
                    "content_chars": len(content),
                    "recommended_action": "write_script_raw",
                }
            self.context.phase = "script"
            return script_tools.write_script(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                content=content,
                overwrite=True if "overwrite" not in payload else bool(payload.get("overwrite")),
            )
        if name == "patch_script":
            self.context.phase = "script"
            return script_tools.patch_script(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                old_text=str(payload.get("old_text") or ""),
                new_text=str(payload.get("new_text") or ""),
                replace_all=bool(payload.get("replace_all") or False),
            )
        if name == "edit_script":
            self.context.phase = "script"
            return script_tools.edit_script(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                old_string=str(payload.get("old_string") or payload.get("old_text") or ""),
                new_string=str(payload.get("new_string") or payload.get("new_text") or ""),
                replace_all=bool(payload.get("replace_all") or False),
            )
        if name == "replace_script_lines":
            self.context.phase = "script"
            return script_tools.replace_script_lines(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                start_line=int(payload.get("start_line") or 1),
                end_line=int(payload.get("end_line") or 1),
                new_text=str(payload.get("new_text") or ""),
            )
        if name == "run_script":
            self.context.phase = "script"
            return script_tools.run_script(
                self.context,
                relative_path=str(payload.get("relative_path") or "generated_script.py"),
                timeout_seconds=int(payload.get("timeout_seconds") or 180),
            )
        if name == "inspect_records":
            self.context.phase = "script"
            return script_tools.inspect_records(self.context, limit=int(payload.get("limit") or 20))
        if name == "done":
            return {"ok": True, "data": {"success": bool(payload.get("success")), "text": str(payload.get("text") or "")}}
        return {"ok": False, "error": f"unknown action: {name}", "input": payload}

    def _assemble_user_prompt(self, step_index: int, ui_state: MobileUIState) -> str:
        parts = [
            "<user_request>",
            build_user_request(self.context.app_name, self.context.package_name, self.context.target, self.constraint),
            "</user_request>",
            "",
            "<agent_state>",
            compact_json(
                {
                    "step": step_index,
                    "max_steps": self.max_steps,
                    "phase": self.context.phase,
                    "navigation_completed": self.context.navigation_completed,
                    "script_workspace": str(self.context.script_workspace) if self.context.script_workspace else "",
                    "workspace_context_files": self.context.workspace_context_files,
                    "last_ui_xml_artifact": self.context.last_ui_artifact,
                    "last_action_monitor": self.context.last_action_monitor,
                    "last_run_state": self._compact_last_run_state(),
                },
                limit=6000,
            ),
            "</agent_state>",
            "",
        ]
        if self.context.phase == "exploration":
            parts.extend(
                [
                    "<script_exploration_guidance>",
                    self._exploration_guidance(),
                    "</script_exploration_guidance>",
                    "",
                ]
            )
        if self.context.phase in {"exploration", "script"} or self.context.navigation_completed:
            parts.extend(
                [
                    "<workspace_context>",
                    self._workspace_context_for_prompt(),
                    "</workspace_context>",
                    "",
                ]
            )
        if self.context.phase == "script":
            parts.extend(
                [
                    "<script_generation_guidance>",
                    self._script_generation_guidance(),
                    "</script_generation_guidance>",
                    "",
                ]
            )
            if self._raw_script_write_mode():
                parts.extend(
                    [
                        "<raw_script_write_protocol>",
                        "本步是首版完整脚本写入模式。不要调用 tool/function call，不要把脚本放进 JSON 字符串。必须直接输出：",
                        "<AGENT_OUTPUT>",
                        '{"evaluation_previous_goal":"...","memory":"","script_context":"...","next_goal":"写入首版完整脚本","action":{"write_script_raw":{"relative_path":"generated_script.py","overwrite":true}}}',
                        "</AGENT_OUTPUT>",
                        "<BEGIN_SCRIPT>",
                        "#!/usr/bin/env python3",
                        "# 完整 Python 脚本原文",
                        "<END_SCRIPT>",
                        "</raw_script_write_protocol>",
                        "",
                    ]
                )
        parts.extend(
            [
                "<agent_history>",
                self._format_history(),
                "</agent_history>",
                "",
                "<ui_state>",
                ui_state.header,
                "",
                ui_state.content or "<empty ui outline>",
                "",
                ui_state.footer,
                "</ui_state>",
                "",
                "<available_actions>",
                self._available_actions_text(),
                "</available_actions>",
            ]
        )
        return "\n".join(parts)

    def _exploration_guidance(self) -> str:
        try:
            text = EXPLORATION_GUIDANCE_PATH.read_text(encoding="utf-8")
        except Exception as exc:
            return f"<guidance_unavailable>{type(exc).__name__}: {exc}</guidance_unavailable>"
        max_chars = 24000
        if len(text) > max_chars:
            return text[:max_chars] + "\n... <script exploration guidance truncated>"
        return text

    def _script_generation_guidance(self) -> str:
        try:
            text = SCRIPT_GUIDANCE_PATH.read_text(encoding="utf-8")
        except Exception as exc:
            return f"<guidance_unavailable>{type(exc).__name__}: {exc}</guidance_unavailable>"
        max_chars = 30000
        if len(text) > max_chars:
            return text[:max_chars] + "\n... <script guidance truncated>"
        return text

    def _workspace_context_for_prompt(self) -> str:
        try:
            result = script_tools.read_workspace_context(self.context)
            text = json.dumps(result.get("workspace_context") or {}, ensure_ascii=False, indent=2)
        except Exception as exc:
            return f"<workspace_context_unavailable>{type(exc).__name__}: {exc}</workspace_context_unavailable>"
        max_chars = 12000
        if len(text) > max_chars:
            return text[:max_chars] + "\n... <workspace context truncated>"
        return text

    def _probe_scroll_position(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Directly probe whether the active scroll container is at top/bottom."""
        scale = max(0.03, min(float(payload.get("scale") or 0.10), 0.9))
        duration = max(0.05, min(float(payload.get("duration") or 0.25), 2.0))
        initial_xml = self.controller.device.dump_hierarchy()
        initial_content_signature = self._probe_content_signature(initial_xml)
        initial_xml_signature = script_tools.xml_signature(initial_xml)
        bounds = self._probe_active_bounds(initial_xml)

        down_changed = self._probe_changed_after_swipe("down", bounds, scale, duration, initial_content_signature)
        if down_changed:
            self._probe_swipe("up", bounds, scale, duration)
        is_top = not down_changed

        middle_xml = self.controller.device.dump_hierarchy()
        middle_content_signature = self._probe_content_signature(middle_xml)
        up_changed = self._probe_changed_after_swipe("up", bounds, scale, duration, middle_content_signature)
        if up_changed:
            self._probe_swipe("down", bounds, scale, duration)
        is_bottom = not up_changed

        is_scrollable = bool(down_changed or up_changed)
        if not is_scrollable:
            is_top = True
            is_bottom = True

        final_xml = self.controller.device.dump_hierarchy()
        final_content_signature = self._probe_content_signature(final_xml)
        final_xml_signature = script_tools.xml_signature(final_xml)
        restored_to_initial = final_content_signature == initial_content_signature

        if is_top and is_bottom and not is_scrollable:
            position_hint = "not_scrollable_or_content_fits_viewport"
        elif is_top:
            position_hint = "top"
        elif is_bottom:
            position_hint = "bottom"
        else:
            position_hint = "middle"

        monitor = {
            "ok": True,
            "action": "probe_scroll_position",
            "before_signature": initial_xml_signature,
            "after_signature": final_xml_signature,
            "xml_changed": final_xml_signature != initial_xml_signature,
            "possible_edge": bool(is_top or is_bottom),
            "hint": f"scroll position probe: is_top={is_top}, is_bottom={is_bottom}, is_scrollable={is_scrollable}",
            "checked_at": time.time(),
        }
        self.context.last_action_monitor = monitor
        self.context.last_xml_signature = final_xml_signature
        self.context.last_ui_xml = final_xml

        result = {
            "probe_type": "direct_top_bottom_probe",
            "is_top": is_top,
            "is_bottom": is_bottom,
            "is_scrollable": is_scrollable,
            "position_hint": position_hint,
            "probe_scale": scale,
            "duration": duration,
            "bounds": list(bounds),
            "down_changed": down_changed,
            "up_changed": up_changed,
            "restored_to_initial_signature": restored_to_initial,
            "gesture_semantics": {
                "down": "finger swipes down; if unchanged, the page is at top",
                "up": "finger swipes up; if unchanged, the page is at bottom",
            },
            "evidence": [
                f"finger down {'changed' if down_changed else 'did not change'} content",
                f"finger up {'changed' if up_changed else 'did not change'} content",
            ],
            "confidence": 0.86 if restored_to_initial else 0.68,
            "before_signature": initial_xml_signature,
            "restored_signature": final_xml_signature,
            "action_monitor": monitor,
        }
        saved = script_tools.update_workspace_context(self.context, {"scroll_position": result})
        return {"ok": True, **result, "workspace_context_path": saved.get("path")}

    def _probe_active_bounds(self, xml_text: str) -> Tuple[int, int, int, int]:
        try:
            root = ET.fromstring(xml_text or "")
        except Exception:
            root = None
        best_bounds: Optional[Tuple[int, int, int, int]] = None
        best_area = 0
        if root is not None:
            for node in root.iter("node"):
                if (node.get("package") or "") == "com.android.systemui":
                    continue
                cls = node.get("class") or ""
                if node.get("scrollable") != "true" and not cls.endswith(("ListView", "RecyclerView", "ScrollView")):
                    continue
                bounds = self._probe_parse_bounds(node.get("bounds") or "")
                if not bounds:
                    continue
                x1, y1, x2, y2 = bounds
                area = max(0, x2 - x1) * max(0, y2 - y1)
                if area > best_area:
                    best_area = area
                    best_bounds = bounds
        if best_bounds:
            return best_bounds
        width, height = self.controller.device.window_size()
        return (0, int(height * 0.15), int(width), int(height * 0.85))

    def _probe_parse_bounds(self, value: str) -> Optional[Tuple[int, int, int, int]]:
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value or "")
        if not match:
            return None
        return tuple(int(match.group(index)) for index in range(1, 5))  # type: ignore[return-value]

    def _probe_content_signature(self, xml_text: str) -> str:
        try:
            root = ET.fromstring(xml_text or "")
        except Exception:
            return hashlib.sha256((xml_text or "").encode("utf-8", errors="ignore")).hexdigest()
        parts: List[str] = []
        for node in root.iter("node"):
            if (node.get("package") or "") == "com.android.systemui":
                continue
            text = (node.get("text") or "").strip()
            desc = (node.get("content-desc") or "").strip()
            rid = node.get("resource-id") or ""
            cls = node.get("class") or ""
            if text or desc or rid:
                parts.append("|".join((rid, cls, text, desc)))
        return hashlib.sha256("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()

    def _probe_swipe(self, direction: str, bounds: Tuple[int, int, int, int], scale: float, duration: float) -> None:
        self.controller.swipe(direction, scale)

    def _probe_changed_after_swipe(
        self,
        direction: str,
        bounds: Tuple[int, int, int, int],
        scale: float,
        duration: float,
        before_signature: str,
    ) -> bool:
        self._probe_swipe(direction, bounds, scale, duration)
        after_xml = self.controller.device.dump_hierarchy()
        return self._probe_content_signature(after_xml) != before_signature

    def _attach_action_monitor(
        self,
        action_name: str,
        result: Dict[str, Any],
        before_signature: str,
        direction: str = "",
    ) -> Dict[str, Any]:
        try:
            after_xml = self.controller.device.dump_hierarchy()
            after_signature = script_tools.xml_signature(after_xml)
        except Exception as exc:
            monitor = {
                "ok": False,
                "action": action_name,
                "error": f"{type(exc).__name__}: {exc}",
            }
            result["action_monitor"] = monitor
            self.context.last_action_monitor = monitor
            return result

        changed = bool(after_signature and after_signature != before_signature)
        possible_edge = not changed
        if action_name == "swipe":
            hint = f"XML did not change after swipe {direction}; possibly at page/list edge or no more content." if possible_edge else "XML changed after swipe."
        elif action_name == "scroll_to_top":
            hint = "XML did not change after scroll_to_top; likely already at top or no scrollable content." if possible_edge else "XML changed during scroll_to_top."
        elif action_name == "scroll_to_bottom":
            hint = "XML did not change after scroll_to_bottom; likely already at bottom or no scrollable content." if possible_edge else "XML changed during scroll_to_bottom."
        else:
            hint = "XML did not change after exploration gesture; possible boundary." if possible_edge else "XML changed after exploration gesture."

        monitor = {
            "ok": True,
            "action": action_name,
            "direction": direction,
            "before_signature": before_signature,
            "after_signature": after_signature,
            "xml_changed": changed,
            "possible_edge": possible_edge,
            "hint": hint,
            "checked_at": time.time(),
        }
        self.context.last_action_monitor = monitor
        self.context.last_xml_signature = after_signature
        self.context.last_ui_xml = after_xml
        try:
            script_tools.update_workspace_context(self.context, {"action_monitor": monitor})
        except Exception:
            logger.debug("%s failed to persist action monitor", LOG_PREFIX, exc_info=True)
        result["action_monitor"] = monitor
        return result

    def _format_history(self) -> str:
        if not self.history:
            return "<empty>"
        parts = []
        for idx, event in enumerate(self.history):
            reflection = event.get("reflection") or {}
            action = event.get("action") or {}
            keep_full_result = len(self.history) - idx <= 2
            parts.extend(
                [
                    f"<step_{event.get('stepIndex')}>",
                    f"Evaluation of Previous Step: {reflection.get('evaluation_previous_goal') or ''}",
                    f"Navigation Memory: {reflection.get('memory') or ''}",
                    f"Script Context: {reflection.get('script_context') or ''}",
                    f"Next Goal: {reflection.get('next_goal') or ''}",
                    f"Action: {self._format_action_input_for_prompt(action)}",
                    f"Action Results: {self._format_action_output_for_prompt(action, keep_full_result)}",
                    f"</step_{event.get('stepIndex')}>",
                ]
            )
        return "\n".join(parts)

    def _format_action_output_for_prompt(self, action: Dict[str, Any], keep_full_result: bool) -> str:
        name = str(action.get("name") or "")
        output = action.get("output") or {}
        if not isinstance(output, dict):
            return compact_json(output, limit=2500)
        if name == "read_script":
            if keep_full_result:
                return compact_json(output, limit=30000)
            return compact_json(self._summarize_read_script_output(output), limit=2500)
        if name == "grep_script":
            return compact_json(output, limit=12000 if keep_full_result else 3500)
        if name == "read_latest_ui_xml":
            if keep_full_result:
                return compact_json(output, limit=60000)
            return compact_json(
                {
                    "ok": output.get("ok"),
                    "xml_artifact": output.get("xml_artifact"),
                    "workspace_xml_path": output.get("workspace_xml_path"),
                    "workspace_outline_path": output.get("workspace_outline_path"),
                    "xml_chars": output.get("xml_chars"),
                    "truncated": output.get("truncated"),
                    "content_omitted": "Full XML from this older tool result was cleared. Use read_latest_ui_xml again if exact XML is needed.",
                },
                limit=2500,
            )
        if name in {"edit_script", "patch_script", "replace_script_lines", "write_script"}:
            limit = 12000 if keep_full_result else 2500
            return compact_json(output, limit=limit)
        return compact_json(output, limit=4000 if keep_full_result else 2500)

    def _format_action_input_for_prompt(self, action: Dict[str, Any]) -> str:
        name = str(action.get("name") or "")
        payload = action.get("input") or {}
        if not isinstance(payload, dict):
            return compact_json(payload, limit=1200)
        if name == "write_script":
            summarized = dict(payload)
            content = str(summarized.pop("content", "") or "")
            summarized["content_chars"] = len(content)
            summarized["content_preview"] = content[:160]
            summarized["content_omitted"] = "Full script omitted from prompt history; use read_script if needed."
            return compact_json(summarized, limit=1200)
        return compact_json(payload, limit=1200)

    def _summarize_read_script_output(self, output: Dict[str, Any]) -> Dict[str, Any]:
        if output.get("type") == "script_unchanged":
            return output
        return {
            "ok": output.get("ok"),
            "type": output.get("type"),
            "path": output.get("path"),
            "offset": output.get("offset"),
            "limit": output.get("limit"),
            "total_lines": output.get("total_lines"),
            "returned_lines": output.get("returned_lines"),
            "has_more": output.get("has_more"),
            "is_partial_view": output.get("is_partial_view"),
            "start_line": output.get("start_line"),
            "end_line": output.get("end_line"),
            "repeat_exact": output.get("repeat_exact"),
            "overlap": output.get("overlap"),
            "read_guidance": output.get("read_guidance"),
            "content_omitted": "Older read_script content was cleared from prompt history. Use script_context summary or call read_script again if exact code is needed.",
        }

    def _build_step_event(self, step_index: int, output: Dict[str, Any], action_result: Dict[str, Any]) -> Dict[str, Any]:
        action = output.get("action") or {}
        return {
            "type": "step",
            "stepIndex": step_index,
            "timestamp": time.time(),
            "reflection": {
                "evaluation_previous_goal": str(output.get("evaluation_previous_goal") or ""),
                "memory": str(output.get("memory") or ""),
                "script_context": str(output.get("script_context") or ""),
                "next_goal": str(output.get("next_goal") or ""),
            },
            "action": {
                "name": action.get("name"),
                "input": action.get("input") or {},
                "output": action_result,
            },
        }

    def _compact_last_run_state(self) -> Optional[Dict[str, Any]]:
        if not self.context.last_run_state:
            return None
        state = dict(self.context.last_run_state)
        for key in ("stdout_tail", "stderr_tail"):
            if key in state and isinstance(state[key], str):
                state[key] = state[key][-1200:]
        return state

    def _export_reuse_artifacts(self) -> Dict[str, Any]:
        try:
            return rag_export.export_reuse_artifacts(
                self.context,
                self.history,
                client=self.client,
                model=self.model,
                constraint=self.constraint,
                llm_timeout_seconds=min(self.llm_timeout_seconds, 120),
            )
        except Exception as exc:
            logger.warning("%s failed to export reuse artifacts: %s", LOG_PREFIX, exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _write_final(self, final: Dict[str, Any]) -> None:
        path = self.session.run_dir / "final.json"
        final["evidence_manifest"] = str(self.session.run_dir / "evidence_manifest.json")
        path.write_text(json.dumps(final, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.session.append_event("run_finished", final)
        append_chain_event(
            self.session.run_dir,
            "run_finished",
            {
                "success": bool(final.get("success")),
                "finished": bool(final.get("finished")),
                "reason": str(final.get("reason") or ""),
                "phase": str(final.get("phase") or ""),
                "script_workspace": str(final.get("script_workspace") or ""),
            },
            actor="codex_mobile_runtime",
        )
        try:
            build_manifest(
                self.session.run_dir,
                device_serial=self.context.device_serial,
                app_name=self.context.app_name,
                package_name=self.context.package_name,
                target=self.context.target,
            )
        except Exception as exc:
            logger.warning("%s failed to write evidence manifest: %s", LOG_PREFIX, exc)

    def _available_actions_text(self) -> str:
        return """AgentOutput.action 必须是只包含一个动作 key 的对象，例如 {"tap":{"x":100,"y":200}}：
严禁把 action 写成字符串，例如 {"action":"{\\"edit_script\\":{...}}"}。修脚本时 action 仍必须是对象；复杂长代码优先用 replace_script_lines 降低 JSON 转义风险。
- launch_app {package_name?}: 启动目标应用。
- tap {x,y,target?}: 点击当前 ui_state 中某个 center 坐标。
- swipe {direction,scale?}: direction 为 up/down/left/right；脚本调试时也可用来恢复页面。
- scroll_to_top {max_swipes?,stable_rounds?,scale?}: 连续滑到当前滚动区顶部，直到 XML 稳定。
- scroll_to_bottom {max_swipes?,stable_rounds?,scale?}: 连续滑到当前滚动区底部/最新消息；会优先点击 WhatsApp 的“移至最新消息”按钮。
- input_text {text}: 默认禁止。只有用户明确批准输入文字时才可用；本取证任务禁止搜索和输入文字。
- press_back {}: 返回上一级。
- wait {seconds}: 等待页面加载或脚本影响。
- mark_navigation_complete {evidence}: 记录已到达目标页，切换到脚本前置探索阶段；不是硬锁。
- read_latest_ui_xml {include_content?,content_limit?}: 只在 mark_navigation_complete 后的探索/脚本阶段读取完整 XML；导航阶段每步已自动提供简化 ui_state，不需要调用此工具。
- probe_scroll_position {scale?,duration?}: 做短距离双向探测，直接返回 is_top/is_bottom/is_scrollable，并尝试恢复探测前位置；自动写入 workspace_context.json。
- update_workspace_context {ui_observations?,scroll_position?,extraction_inference?,item_schema?,pagination_state?,section_map?,nested_flow_map?,...}: 将结构化探索结果合并写入 workspace_context.json；只写 JSON。
- read_workspace_context {}: 读取 workspace_context.json，供脚本生成前参考。
- set_extraction_plan {extraction_pattern,target?,initial_position_strategy?,collection_finger_swipe_direction?,collection_scroll_direction?,scroll_direction?,required_context?,available_context?,missing_context?,notes?}: 保存最终提取计划；上下文满足时进入脚本阶段。滚动方向字段必须表示手指滑动方向，推荐写 finger_up/finger_down，避免“向下浏览”和“手指下滑”混淆。
- codex_script_agent {timeout_seconds?}: 将脚本阶段委托给 Codex + $forensiflow-mobile-agent skill，生成/修复并运行 generated_script.py。
- write_script_raw {relative_path?,overwrite?}: 首版长脚本专用动作；只在 <raw_script_write_protocol> 模式中使用，完整 Python 代码必须放在 <BEGIN_SCRIPT>...<END_SCRIPT> 文本块，不放进 JSON。
- write_script {relative_path?,content,overwrite?}: 短脚本/兼容写入；长代码不要用此动作，首版完整脚本优先用 write_script_raw。若语法失败，后续用 patch_script/replace_script_lines 修补，不要重复整文件生成。
- read_script {relative_path?,offset?,limit?}: 读取脚本副本；默认读取最多 2000 行，指定 offset/limit 可定向查看。
- read_script_index {relative_path?}: 读取自动生成的 script_index.json，包含函数/类/常量/重要逻辑区域和 read_hint；优先用它定位，再按需 read_script 局部片段。
- grep_script {relative_path?,pattern,regex?,case_sensitive?,context_lines?,max_matches?}: 在脚本里搜索关键符号/字段/错误文本，返回匹配行和少量上下文；大脚本定位优先 grep_script，再 read_script 大窗口。
- edit_script {relative_path?,old_string,new_string,replace_all?}: 推荐的脚本修复动作；用 opencode 风格匹配链执行 old_string -> new_string，支持 exact、去行号、trim、锚点块、空白归一、缩进归一、转义归一、上下文相似匹配；失败时返回候选片段。action 必须是对象，不能字符串化。
- patch_script {relative_path?,old_text,new_text,replace_all?}: 兼容旧动作，内部等同 edit_script；新修复优先用 edit_script。
- replace_script_lines {relative_path?,start_line,end_line,new_text}: 按行替换脚本。
- run_script {relative_path?,timeout_seconds?}: 运行脚本副本并检查 records.json；如果存在 records_debug.json，会返回 provenance 摘要和样本。
- inspect_records {limit?}: 查看 records.json 样本；同时返回 records_debug.json 中带 _debug provenance 的样本，供定位 parser/block_detector。
- done {success,text}: 完成或失败退出。
"""

    def _agent_output_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "AgentOutput",
                "description": "ForensiFlow mobile-agent macro output. The model must choose exactly one action for this step.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "evaluation_previous_goal": {
                            "type": "string",
                            "description": "Evaluate whether the previous step achieved its goal.",
                        },
                        "memory": {
                            "type": "string",
                            "description": "Navigation memory summary. Keep it compact and durable.",
                        },
                        "script_context": {
                            "type": "string",
                            "description": "Script/XML/debug context summary. Keep important implementation facts only.",
                        },
                        "next_goal": {
                            "type": "string",
                            "description": "The concrete next goal for this single step.",
                        },
                        "action": {
                            "type": "object",
                            "properties": {
                                "launch_app": {"type": "object", "additionalProperties": True},
                                "tap": {"type": "object", "additionalProperties": True},
                                "swipe": {"type": "object", "additionalProperties": True},
                                "scroll_to_top": {"type": "object", "additionalProperties": True},
                                "scroll_to_bottom": {"type": "object", "additionalProperties": True},
                                "input_text": {"type": "object", "additionalProperties": True},
                                "press_back": {"type": "object", "additionalProperties": True},
                                "wait": {"type": "object", "additionalProperties": True},
                                "mark_navigation_complete": {"type": "object", "additionalProperties": True},
                                "read_latest_ui_xml": {"type": "object", "additionalProperties": True},
                                "probe_scroll_position": {"type": "object", "additionalProperties": True},
                                "update_workspace_context": {"type": "object", "additionalProperties": True},
                                "read_workspace_context": {"type": "object", "additionalProperties": True},
                                "set_extraction_plan": {"type": "object", "additionalProperties": True},
                                "codex_script_agent": {"type": "object", "additionalProperties": True},
                                "write_script_raw": {"type": "object", "additionalProperties": True},
                                "write_script": {"type": "object", "additionalProperties": True},
                                "read_script": {"type": "object", "additionalProperties": True},
                                "read_script_index": {"type": "object", "additionalProperties": True},
                                "grep_script": {"type": "object", "additionalProperties": True},
                                "edit_script": {"type": "object", "additionalProperties": True},
                                "patch_script": {"type": "object", "additionalProperties": True},
                                "replace_script_lines": {"type": "object", "additionalProperties": True},
                                "run_script": {"type": "object", "additionalProperties": True},
                                "inspect_records": {"type": "object", "additionalProperties": True},
                                "done": {"type": "object", "additionalProperties": True},
                            },
                            "minProperties": 1,
                            "maxProperties": 1,
                            "additionalProperties": False,
                        },
                    },
                    "required": [
                        "evaluation_previous_goal",
                        "memory",
                        "script_context",
                        "next_goal",
                        "action",
                    ],
                    "additionalProperties": False,
                },
            },
        }


# Backward compatibility for historical imports and generated artifacts.
PageAgentMobileRuntime = CodexMobileRuntime
