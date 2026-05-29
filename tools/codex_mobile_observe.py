#!/usr/bin/env python3
"""Persist a mobile UI observation for Codex-driven ForensiFlow runs."""

from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import uiautomator2 as u2


def _rid_short(node: ET.Element) -> str:
    rid = node.get("resource-id", "")
    return rid.rsplit("/", 1)[-1] if "/" in rid else rid.rsplit(":", 1)[-1]


def _label(node: ET.Element) -> str:
    cls = (node.get("class") or "").rsplit(".", 1)[-1]
    text = (node.get("text") or "").strip()
    desc = (node.get("content-desc") or "").strip()
    rid = _rid_short(node)
    parts = [cls or "node"]
    if text:
        parts.append(json.dumps(text[:160], ensure_ascii=False))
    elif desc:
        parts.append("desc=" + json.dumps(desc[:160], ensure_ascii=False))
    if rid:
        parts.append("#" + rid)
    if node.get("scrollable") == "true":
        parts.append("scrollable")
    if node.get("clickable") == "true":
        parts.append("clickable")
    bounds = node.get("bounds", "")
    if bounds:
        parts.append(bounds)
    return " ".join(parts)


def _outline(root: ET.Element, max_lines: int = 400) -> str:
    lines: list[str] = []

    def walk(node: ET.Element, depth: int) -> None:
        if len(lines) >= max_lines:
            return
        has_signal = any(
            (
                (node.get("text") or "").strip(),
                (node.get("content-desc") or "").strip(),
                node.get("resource-id"),
                node.get("scrollable") == "true",
                node.get("clickable") == "true",
            )
        )
        if has_signal:
            lines.append("  " * min(depth, 8) + "- " + _label(node))
        for child in node:
            walk(child, depth + 1)

    walk(root, 0)
    if len(lines) >= max_lines:
        lines.append("... <outline truncated>")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump current Android UI to a Codex script workspace.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--serial", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--preview-lines", type=int, default=35)
    args = parser.parse_args()

    context_dir = args.workspace.resolve() / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    device = u2.connect(args.serial or None)
    xml = device.dump_hierarchy()
    root = ET.fromstring(xml)
    outline = _outline(root)
    stamp = int(time.time() * 1000)
    stem = args.name.strip() or f"ui_{stamp}"

    current_xml = context_dir / "current_page.xml"
    current_outline = context_dir / "current_page_outline.txt"
    snapshot_xml = context_dir / f"{stem}.xml"
    snapshot_outline = context_dir / f"{stem}_outline.txt"
    current_xml.write_text(xml, encoding="utf-8")
    current_outline.write_text(outline, encoding="utf-8")
    snapshot_xml.write_text(xml, encoding="utf-8")
    snapshot_outline.write_text(outline, encoding="utf-8")

    result = {
        "ok": True,
        "app_current": device.app_current(),
        "xml_path": str(current_xml),
        "outline_path": str(current_outline),
        "snapshot_xml_path": str(snapshot_xml),
        "snapshot_outline_path": str(snapshot_outline),
        "xml_chars": len(xml),
        "outline_lines": len(outline.splitlines()),
        "outline_preview": "\n".join(outline.splitlines()[: max(0, args.preview_lines)]),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
