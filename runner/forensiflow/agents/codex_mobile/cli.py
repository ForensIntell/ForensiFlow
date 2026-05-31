"""CLI for the ForensiFlow Codex mobile forensic agent."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sys
from pathlib import Path

from runner.forensiflow.core.logging_utils import configure_logging
from runner.forensiflow.core.config import DEFAULT_LLM_API_BASE, DEFAULT_LLM_MODEL, get_llm_config
from runner.forensiflow.devices.android import AndroidDevice

from .codex_agent import run_codex_forensiflow_full_agent
from .runtime import CodexMobileRuntime


REPO_ROOT = Path(__file__).resolve().parents[4]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from device_serial import PLACEHOLDER_SERIALS, adb_devices_text, resolve_device_serial


DEFAULT_API_BASE = DEFAULT_LLM_API_BASE
DEFAULT_MODEL = DEFAULT_LLM_MODEL
DEFAULT_API_KEY = ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ForensiFlow Codex mobile forensic agent.")
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 device serial.")
    parser.add_argument("--package-name", required=True, help="Android package name, e.g. com.whatsapp.")
    parser.add_argument("--app-name", required=True, help="Human-readable app name.")
    parser.add_argument("--target", required=True, help="Forensic navigation/extraction target.")
    parser.add_argument("--constraint", default="", help="Optional forensic constraint.")
    parser.add_argument("--model", default="", help=f"Override model. Default: {DEFAULT_MODEL}.")
    parser.add_argument("--api-base", default="", help=f"Override OpenAI-compatible API base URL. Default: {DEFAULT_API_BASE}.")
    parser.add_argument("--api-key-env", default="", help="Environment variable containing the API key. Defaults to the unified MOMI/MIMO/LLM configuration.")
    parser.add_argument("--no-deepseek-thinking", action="store_true", help="Do not send DeepSeek thinking extra parameters.")
    parser.add_argument("--run-root", type=Path, default=Path("data/codex_mobile_agent_runs"))
    parser.add_argument("--max-attempts", type=int, default=8, help="Retry Codex if it exits before reusable artifacts are produced.")
    parser.add_argument("--dry-run", action="store_true", help="Print the underlying Codex command and prompt without executing the agent.")
    parser.add_argument("--max-steps", type=int, default=60)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--llm-timeout-seconds", type=int, default=120)
    parser.add_argument("--max-output-tokens", type=int, default=12288)
    parser.add_argument(
        "--agent-backend",
        choices=["native", "codex"],
        default=os.getenv("FORENSIFLOW_MOBILE_AGENT_BACKEND") or os.getenv("PAGE_AGENT_MOBILE_AGENT_BACKEND", "codex"),
        help="Full scheduler backend. codex lets Codex + forensiflow-mobile-agent skill handle navigation, script generation, and validation.",
    )
    parser.add_argument(
        "--raw-script-max-output-tokens",
        type=int,
        default=49152,
        help="Output token budget used only for the first write_script_raw full-script response.",
    )
    parser.add_argument(
        "--tool-choice-mode",
        choices=["auto", "named", "required", "none"],
        default="auto",
        help="OpenAI tool_choice strategy. auto disables tool_choice for DeepSeek-style reasoner models.",
    )
    parser.add_argument(
        "--reasoning-log-chars",
        type=int,
        default=2000,
        help="How many model reasoning characters to print per step. Use 0 to hide.",
    )
    parser.add_argument(
        "--script-agent",
        choices=["native", "codex"],
        default=os.getenv("FORENSIFLOW_CODEX_SCRIPT_AGENT") or os.getenv("PAGE_AGENT_MOBILE_SCRIPT_AGENT", "native"),
        help="Script generation backend. Use codex to call the forensiflow-mobile-agent skill via Codex after exploration.",
    )
    return parser


def main() -> int:
    configure_logging()
    logger = logging.getLogger(__name__)
    args = build_parser().parse_args()
    logger.info("ForensiFlow Codex mobile backend: %s", args.agent_backend)
    if args.device_serial.strip() in PLACEHOLDER_SERIALS:
        raise ValueError(
            "--device-serial received a placeholder. Use a real serial from `adb devices`, "
            "or omit --device-serial when only one device is connected.\n\n"
            + adb_devices_text()
        )
    timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    device = None
    device_serial = resolve_device_serial(args.device_serial, required=True)
    if args.agent_backend != "codex":
        try:
            device = AndroidDevice(adb_endpoint=device_serial)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to connect Android device: {exc}\n\nAvailable adb devices:\n{adb_devices_text()}"
            )
    run_dir = args.run_root / device_serial / f"codex_mobile_agent_run_{timestamp}"
    explicit_key = os.getenv(args.api_key_env) if args.api_key_env else DEFAULT_API_KEY or None
    llm_config = get_llm_config(
        api_key=explicit_key,
        api_base=args.api_base or None,
        model=args.model or None,
    )
    api_key = llm_config.api_key
    api_base = llm_config.api_base or DEFAULT_API_BASE
    model = llm_config.model or DEFAULT_MODEL
    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 12 else "<short>"
    logger.info("ForensiFlow Codex mobile API: base=%s model=%s key=%s", api_base, model, masked_key)

    model_extra_body = None
    if "api.deepseek.com" in api_base and not args.no_deepseek_thinking:
        model_extra_body = {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        }

    if args.agent_backend == "codex":
        logger.info("ForensiFlow Codex full-agent run_dir root: %s", args.run_root)
        result = run_codex_forensiflow_full_agent(
            device_serial=device_serial,
            package_name=args.package_name,
            app_name=args.app_name,
            target=args.target,
            constraint=args.constraint,
            run_root=args.run_root,
            timeout_seconds=int(os.getenv("FORENSIFLOW_CODEX_FULL_TIMEOUT_SECONDS") or os.getenv("PAGE_AGENT_MOBILE_CODEX_FULL_TIMEOUT_SECONDS", "1800")),
            max_attempts=args.max_attempts,
            model=args.model or "",
            prompt_mode=os.getenv("FORENSIFLOW_CODEX_PROMPT_MODE", "simple"),
            dry_run=args.dry_run,
        )
        logger.info("Codex full-agent result:\n%s", json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok") else 1

    runtime = CodexMobileRuntime(
        device=device,
        api_key=api_key,
        api_base=api_base,
        model=model,
        run_dir=run_dir,
        app_name=args.app_name,
        package_name=args.package_name,
        target=args.target,
        constraint=args.constraint,
        device_serial=device_serial,
        max_steps=args.max_steps,
        temperature=args.temperature,
        llm_timeout_seconds=args.llm_timeout_seconds,
        max_output_tokens=args.max_output_tokens,
        raw_script_max_output_tokens=args.raw_script_max_output_tokens,
        model_extra_body=model_extra_body,
        tool_choice_mode=args.tool_choice_mode,
        reasoning_log_chars=args.reasoning_log_chars,
        script_agent=args.script_agent,
    )
    logger.info("ForensiFlow Codex mobile run_dir: %s", run_dir)
    result = runtime.run()
    logger.info("ForensiFlow Codex mobile result:\n%s", json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
