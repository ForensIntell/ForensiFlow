"""Android UI controller for the ForensiFlow Codex mobile agent."""

from __future__ import annotations

import re
import time
import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def parse_bounds(bounds: str) -> Optional[Tuple[int, int, int, int]]:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    return tuple(int(match.group(i)) for i in range(1, 5))  # type: ignore[return-value]


def center_of(bounds: str) -> Optional[List[int]]:
    parsed = parse_bounds(bounds)
    if not parsed:
        return None
    left, top, right, bottom = parsed
    return [(left + right) // 2, (top + bottom) // 2]


@dataclass
class MobileUIState:
    packages: List[str]
    header: str
    content: str
    footer: str
    xml: str


class MobilePageController:
    """Small Android controller used by the Codex mobile runtime.

    It indexes visible/clickable nodes and gives the model only a compact,
    current-screen outline. Actions are coordinate based but the model is asked
    to pick coordinates from the indexed outline.
    """

    def __init__(self, device: Any):
        self.device = device
        self.last_dump_at = 0.0

    def get_ui_state(self) -> MobileUIState:
        xml = self.device.dump_hierarchy()
        self.last_dump_at = time.time()
        packages = self._packages(xml)
        content, scrollables = self._outline(xml)
        header = "Current Android UI\nPackages: " + ", ".join(packages[:8])
        footer = self._footer(scrollables)
        return MobileUIState(packages=packages, header=header, content=content, footer=footer, xml=xml)

    def launch_app(self, package_name: str) -> str:
        self.device.app_start(package_name)
        time.sleep(2.0)
        return f"OK launched {package_name}"

    def tap(self, x: int, y: int, target: str = "") -> str:
        self.device.click(int(x), int(y))
        time.sleep(1.0)
        return f"OK tapped ({x}, {y}) {target}".strip()

    def swipe(self, direction: str, scale: float = 0.55) -> str:
        direction = direction.lower().strip()
        scale = max(0.1, min(float(scale), 0.95))
        if hasattr(self.device, "swipe"):
            self.device.swipe(direction=direction, scale=scale)
        else:
            self.device.swipe_ext(direction=direction, scale=scale)
        time.sleep(1.0)
        return f"OK swiped {direction} scale={scale}"

    def scroll_to_top(self, max_swipes: int = 20, stable_rounds: int = 2, scale: float = 0.75) -> Dict[str, Any]:
        return self._scroll_to_edge(
            edge="top",
            direction="down",
            max_swipes=max_swipes,
            stable_rounds=stable_rounds,
            scale=scale,
        )

    def scroll_to_bottom(self, max_swipes: int = 20, stable_rounds: int = 2, scale: float = 0.75) -> Dict[str, Any]:
        clicked = self._click_scroll_bottom_if_visible()
        result = self._scroll_to_edge(
            edge="bottom",
            direction="up",
            max_swipes=max_swipes,
            stable_rounds=stable_rounds,
            scale=scale,
        )
        result["clicked_scroll_bottom"] = clicked
        return result

    def input_text(self, text: str) -> str:
        if hasattr(self.device, "input"):
            self.device.input(text)
        else:
            self.device.send_keys(text, clear=False)
        time.sleep(0.8)
        return f"OK input text length={len(text)}"

    def press_back(self) -> str:
        if hasattr(self.device, "keyevent"):
            self.device.keyevent("back")
        else:
            self.device.press("back")
        time.sleep(1.0)
        return "OK pressed back"

    def _scroll_to_edge(
        self,
        edge: str,
        direction: str,
        max_swipes: int,
        stable_rounds: int,
        scale: float,
    ) -> Dict[str, Any]:
        max_swipes = max(1, min(int(max_swipes), 80))
        stable_rounds = max(1, min(int(stable_rounds), 5))
        stable = 0
        before = self._xml_signature(self.device.dump_hierarchy())
        swipes = 0
        for _ in range(max_swipes):
            self.swipe(direction, scale)
            swipes += 1
            after_xml = self.device.dump_hierarchy()
            after = self._xml_signature(after_xml)
            if after == before:
                stable += 1
            else:
                stable = 0
            before = after
            if stable >= stable_rounds:
                break
        return {
            "ok": True,
            "edge": edge,
            "direction": direction,
            "swipes": swipes,
            "stable_rounds": stable,
            "reached_edge": stable >= stable_rounds,
            "signature": before,
        }

    def _xml_signature(self, xml: str) -> str:
        try:
            root = ET.fromstring(xml)
        except Exception:
            return hashlib.sha256(xml.encode("utf-8", errors="ignore")).hexdigest()
        parts: List[str] = []
        for node in root.iter("node"):
            attrs = node.attrib
            text = attrs.get("text") or ""
            desc = attrs.get("content-desc") or ""
            rid = attrs.get("resource-id") or ""
            cls = attrs.get("class") or ""
            bounds = attrs.get("bounds") or ""
            if text or desc or rid:
                parts.append("|".join((rid, cls, text, desc, bounds)))
        return hashlib.sha256("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()

    def _click_scroll_bottom_if_visible(self) -> bool:
        try:
            root = ET.fromstring(self.device.dump_hierarchy())
        except Exception:
            return False
        for node in root.iter("node"):
            rid = node.get("resource-id") or ""
            text = node.get("text") or ""
            desc = node.get("content-desc") or ""
            if "scroll_bottom" not in rid and "移至最新消息" not in text and "移至最新消息" not in desc:
                continue
            center = center_of(node.get("bounds") or "")
            if not center:
                continue
            self.tap(center[0], center[1], "scroll_bottom")
            time.sleep(0.8)
            return True
        return False

    def _packages(self, xml: str) -> List[str]:
        try:
            root = ET.fromstring(xml)
        except Exception:
            return []
        packages = []
        seen = set()
        for node in root.iter("node"):
            package = node.get("package") or ""
            if package and package not in seen:
                seen.add(package)
                packages.append(package)
        return packages

    def _outline(self, xml: str, limit: int = 12000) -> Tuple[str, List[str]]:
        try:
            root = ET.fromstring(xml)
        except Exception:
            return xml[:limit], []

        lines: List[str] = []
        scrollables: List[str] = []

        def walk(node: ET.Element, depth: int = 0) -> None:
            attrs = node.attrib
            text = (attrs.get("text") or "").strip()
            desc = (attrs.get("content-desc") or "").strip()
            rid = attrs.get("resource-id") or ""
            class_name = attrs.get("class") or node.tag
            short_class = class_name.split(".")[-1]
            bounds = attrs.get("bounds") or ""
            center = center_of(bounds)
            clickable = attrs.get("clickable") == "true"
            scrollable = attrs.get("scrollable") == "true"
            selected = attrs.get("selected") == "true"
            checked = attrs.get("checked") == "true"
            enabled = attrs.get("enabled", "true") == "true"
            visibleish = text or desc or rid or clickable or scrollable or selected or checked

            if visibleish:
                parts = [f"{'  ' * depth}- {short_class}"]
                if text:
                    parts.append(f'"{text}"')
                elif desc:
                    parts.append(f'"{desc}"')
                if center:
                    parts.append(f"center={center}")
                traits = []
                if clickable:
                    traits.append("clickable")
                if scrollable:
                    traits.append("scrollable")
                    scrollables.append(bounds)
                if selected:
                    traits.append("selected")
                if checked:
                    traits.append("checked")
                if not enabled:
                    traits.append("disabled")
                if traits:
                    parts.append("(" + ", ".join(traits) + ")")
                if rid:
                    parts.append("#" + rid.split("/")[-1])
                lines.append(" ".join(parts))

            for child in list(node):
                walk(child, depth + (1 if visibleish else 0))

        walk(root)
        result = "\n".join(lines)
        if len(result) > limit:
            result = result[:limit] + "\n... <UI outline truncated>"
        return result, scrollables

    def _footer(self, scrollables: List[str]) -> str:
        if scrollables:
            return "Scrollable areas visible: " + ", ".join(scrollables[:8])
        return "No explicit scrollable node visible"
