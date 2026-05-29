"""Schemas for the ForensiFlow Codex mobile forensic agent."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class AgentSession:
    run_dir: Path

    def __post_init__(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    @property
    def artifacts_dir(self) -> Path:
        return self.run_dir / "artifacts"

    @property
    def history_path(self) -> Path:
        return self.run_dir / "history.jsonl"

    @property
    def events_path(self) -> Path:
        return self.run_dir / "events.jsonl"

    def artifact_path(self, name: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
        return self.artifacts_dir / safe_name

    def append_jsonl(self, path: Path, item: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    def append_history(self, event: Dict[str, Any]) -> None:
        self.append_jsonl(self.history_path, event)

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.append_jsonl(
            self.events_path,
            {"type": event_type, "timestamp": time.time(), "payload": payload},
        )


@dataclass
class MobileAgentContext:
    device: Any
    session: AgentSession
    app_name: str
    package_name: str
    target: str
    device_serial: str = ""
    phase: str = "navigation"
    navigation_completed: bool = False
    last_ui_xml: str = ""
    last_ui_outline: str = ""
    last_ui_artifact: str = ""
    script_workspace: Optional[Path] = None
    workspace_context_files: Dict[str, str] = field(default_factory=dict)
    script_read_state: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    last_run_state: Optional[Dict[str, Any]] = None
    last_xml_signature: str = ""
    last_action_monitor: Optional[Dict[str, Any]] = None


def compact_json(data: Any, limit: int = 20000) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... <truncated>"
