#!/usr/bin/env python3
"""Run the formal three-app six-task experiment on the connected Android device.

Scope is intentionally limited to the apps requested for the current study:
Gmail, Chrome, and Google Maps.  Each app has two formal tasks from the
experiment plan.  G1 is a fixed read-only reference extractor; G2 is the
current ForensiFlow full flow with an isolated zero-RAG explore phase followed
by a reuse phase.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from runner.forensiflow.core.config import get_llm_config
from tools.device_serial import resolve_device_serial
from tools.run_feasibility_full_flow import (
    _duplicate_rate,
    _field_complete_rate,
    _load_records_and_state,
    _normalize_records_artifacts,
    _unsafe_count,
    _write_csv,
    _write_json,
)
from tools.run_zero_rag_explore_reuse_experiment import (
    _aggregate,
    _align_to_gold,
    _business_record,
    _patched_env,
    _prepare_empty_rag_library,
    _run_task_phase,
)


FORMAL_TASKS: List[Dict[str, Any]] = [
    {
        "task_id": "GM-01",
        "app_name": "Gmail",
        "package_name": "com.google.android.gm",
        "task_description": "抽取 Gmail 已发送/Sent 中最近邮件记录；若当前已发送为空，输出一条 empty_state 记录并保留空状态文案",
        "expected_min_records": 1,
        "expected_min_fields": ["mailbox", "entity_type", "empty_state_text"],
        "gold_available": True,
        "formal_task": True,
    },
    {
        "task_id": "GM-02",
        "app_name": "Gmail",
        "package_name": "com.google.android.gm",
        "task_description": "从 Gmail 收件箱/主要列表打开第一封可见邮件线程，抽取线程标题、发件人、日期、正文摘要和附件元数据；如果当前停留在已发送/Sent 或空状态页，必须先通过抽屉导航切回收件箱/主要；不点击回复、转发、归档或写邮件",
        "expected_min_records": 1,
        "expected_min_fields": ["subject", "sender", "date", "snippet"],
        "gold_available": True,
        "formal_task": True,
    },
    {
        "task_id": "CH-01",
        "app_name": "Chrome",
        "package_name": "com.android.chrome",
        "task_description": "抽取 Chrome 最近历史记录",
        "expected_min_records": 1,
        "expected_min_fields": ["title", "url_domain", "date_section"],
        "gold_available": True,
        "formal_task": True,
    },
    {
        "task_id": "CH-02",
        "app_name": "Chrome",
        "package_name": "com.android.chrome",
        "task_description": "抽取 Chrome 下载记录与书签目录/书签列表",
        "expected_min_records": 2,
        "expected_min_fields": ["entity_type", "title"],
        "gold_available": True,
        "formal_task": True,
    },
    {
        "task_id": "MP-01",
        "app_name": "Google Maps",
        "package_name": "com.google.android.apps.maps",
        "task_description": "抽取 Google Maps 最近搜索或最近查看地点",
        "constraint": "只读取已有最近搜索、最近查看地点和地点摘要，不输入新搜索词，不点击路线、保存、分享或菜单。",
        "expected_min_records": 1,
        "expected_min_fields": ["title", "category", "status", "filter_type"],
        "gold_available": True,
        "formal_task": True,
    },
    {
        "task_id": "MP-02",
        "app_name": "Google Maps",
        "package_name": "com.google.android.apps.maps",
        "task_description": "抽取 Google Maps Saved 中的地点列表和第一个可见地点详情",
        "constraint": "只读取 Saved 地点列表和只读地点详情，不点击路线、预订、保存切换、分享、菜单或搜索输入。",
        "expected_min_records": 2,
        "expected_min_fields": ["entity_type", "title"],
        "gold_available": True,
        "formal_task": True,
    },
]

APP_ALIASES = {
    "gmail": "com.google.android.gm",
    "gm": "com.google.android.gm",
    "chrome": "com.android.chrome",
    "ch": "com.android.chrome",
    "maps": "com.google.android.apps.maps",
    "google maps": "com.google.android.apps.maps",
    "mp": "com.google.android.apps.maps",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-serial", default="", help="ADB/uiautomator2 serial.")
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "experiments" / "three_app_formal")
    parser.add_argument("--run-id", default="", help="Optional run id. Default timestamped.")
    parser.add_argument("--apps", default="gmail,chrome,maps", help="Comma list: gmail, chrome, maps.")
    parser.add_argument("--groups", default="G1,G2", help="Comma list: G1, G2.")
    parser.add_argument("--max-tasks", type=int, default=0)
    parser.add_argument("--repeat-count", type=int, default=1, help="Number of G2 formal repetitions to run serially.")
    parser.add_argument("--explore-threshold", type=float, default=1.1)
    parser.add_argument("--reuse-threshold", type=float, default=0.75)
    parser.add_argument("--model", default="")
    parser.add_argument("--api-base", default="")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def selected_tasks(apps: str, max_tasks: int = 0) -> List[Dict[str, Any]]:
    requested = {APP_ALIASES.get(part.strip().casefold(), part.strip()) for part in apps.split(",") if part.strip()}
    tasks = [task for task in FORMAL_TASKS if task["package_name"] in requested or task["app_name"].casefold() in requested]
    return tasks[:max_tasks] if max_tasks and max_tasks > 0 else tasks


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_bounds(bounds: str) -> Optional[Dict[str, int]]:
    matches = re.findall(r"\[(\d+),(\d+)\]", bounds or "")
    if len(matches) != 2:
        return None
    left, top = int(matches[0][0]), int(matches[0][1])
    right, bottom = int(matches[1][0]), int(matches[1][1])
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def bounds_center(bounds: Dict[str, int]) -> Tuple[int, int]:
    return (bounds["left"] + bounds["right"]) // 2, (bounds["top"] + bounds["bottom"]) // 2


def node_text(node: ET.Element) -> str:
    return ((node.get("text") or "").strip() or (node.get("content-desc") or "").strip()).strip()


def clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def iter_nodes(xml: str, package_name: str = "") -> Iterable[ET.Element]:
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        if package_name:
            package = node.get("package") or ""
            if package and package != package_name and package != "android":
                continue
        yield node


def visible_text_nodes(xml: str, package_name: str = "") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for node in iter_nodes(xml, package_name):
        text = clean_text(node_text(node))
        if not text:
            continue
        out.append(
            {
                "text": text,
                "resource_id": node.get("resource-id") or "",
                "class": node.get("class") or "",
                "bounds": node.get("bounds") or "",
            }
        )
    return out


def exists(selector: Any, timeout: float = 0.0) -> bool:
    try:
        return bool(selector.exists(timeout=timeout))
    except TypeError:
        return bool(selector.exists)


def click_text_or_desc(d: Any, texts: List[str], timeout: float = 1.0) -> bool:
    for text in texts:
        if not text:
            continue
        candidates = [
            d(text=text),
            d(description=text),
            d(textContains=text),
            d(descriptionContains=text),
        ]
        for selector in candidates:
            if exists(selector, timeout=timeout):
                selector.click()
                time.sleep(1.2)
                return True
    return False


def click_resource(d: Any, resource_id: str, timeout: float = 1.0) -> bool:
    selector = d(resourceId=resource_id)
    if exists(selector, timeout=timeout):
        selector.click()
        time.sleep(1.2)
        return True
    return False


def click_xml_text(d: Any, text: str, package_name: str = "", x_ratio: float = 0.5) -> bool:
    xml = d.dump_hierarchy()
    best: Optional[Dict[str, Any]] = None
    needle = text.casefold()
    for node in iter_nodes(xml, package_name):
        value = clean_text(node_text(node))
        if not value:
            continue
        if value.casefold() == needle or needle in value.casefold():
            bounds = parse_bounds(node.get("bounds") or "")
            if not bounds:
                continue
            score = 10 if value.casefold() == needle else 5
            if best is None or score > best["score"]:
                best = {"bounds": bounds, "score": score, "text": value}
    if not best:
        return False
    bounds = best["bounds"]
    x = int(bounds["left"] + (bounds["right"] - bounds["left"]) * x_ratio)
    y = (bounds["top"] + bounds["bottom"]) // 2
    d.click(x, y)
    time.sleep(1.2)
    return True


def dump_evidence(d: Any, artifacts: Path, label: str, package_name: str) -> str:
    xml = d.dump_hierarchy()
    (artifacts / f"{label}.xml").write_text(xml, encoding="utf-8")
    _write_json(artifacts / f"{label}_nodes.json", visible_text_nodes(xml, package_name))
    try:
        d.screenshot(str(artifacts / f"{label}.png"))
    except Exception:
        pass
    return xml


def start_app(d: Any, package_name: str, wait_seconds: float = 4.5) -> List[Dict[str, Any]]:
    d.app_stop(package_name)
    time.sleep(0.8)
    d.app_start(package_name)
    time.sleep(wait_seconds)
    return [{"action": "launch_app", "package_name": package_name, "ok": True}]


def ensure_gmail_inbox(d: Any, actions: List[Dict[str, Any]]) -> None:
    for _ in range(2):
        xml = d.dump_hierarchy()
        if "com.google.android.gm:id/viewified_conversation_item_view" in xml and "“已发送”中没有任何内容" not in xml:
            return
        if click_text_or_desc(d, ["打开抽屉式导航栏"], timeout=0.5) or click_xml_text(d, "打开抽屉式导航栏", "com.google.android.gm"):
            actions.append({"action": "tap", "target": "打开抽屉式导航栏", "ok": True})
            time.sleep(0.8)
            if click_text_or_desc(d, ["主要", "收件箱", "Inbox", "Primary"], timeout=0.5) or click_xml_text(d, "主要", "com.google.android.gm"):
                actions.append({"action": "tap", "target": "Gmail inbox/primary", "ok": True})
                time.sleep(2)
                return
        d.press("back")
        actions.append({"action": "back", "ok": True})
        time.sleep(1)


def gmail_sent_boundary(xml: str) -> bool:
    if "“已发送”中没有任何内容" in xml or "已发送”中没有任何内容" in xml:
        return True
    filter_hits = sum(1 for text in ("已发送", "收件人", "附件", "日期") if text in xml)
    return filter_hits >= 2 and "hub_drawer_label_title" not in xml


def open_gmail_drawer(d: Any, actions: List[Dict[str, Any]]) -> bool:
    xml = d.dump_hierarchy()
    if "hub_drawer_label_title" in xml and "已发送" in xml:
        return True
    if click_text_or_desc(d, ["打开抽屉式导航栏"], timeout=0.5) or click_xml_text(d, "打开抽屉式导航栏", "com.google.android.gm"):
        actions.append({"action": "tap", "target": "打开抽屉式导航栏", "ok": True})
        time.sleep(1.0)
        return True
    try:
        d.swipe(20, 960, 620, 960, duration=0.2)
        actions.append({"action": "swipe", "direction": "right", "target": "Gmail drawer edge", "ok": True})
        time.sleep(1.0)
        return "hub_drawer_label_title" in d.dump_hierarchy()
    except Exception as exc:
        actions.append({"action": "swipe", "direction": "right", "target": "Gmail drawer edge", "ok": False, "error": str(exc)})
        return False


def navigate_gmail_sent(d: Any, actions: List[Dict[str, Any]]) -> None:
    for _ in range(5):
        if gmail_sent_boundary(d.dump_hierarchy()):
            return
        open_gmail_drawer(d, actions)
        if click_text_or_desc(d, ["已发送", "Sent"], timeout=0.5) or click_xml_text(d, "已发送", "com.google.android.gm"):
            actions.append({"action": "tap", "target": "已发送/Sent", "ok": True})
            time.sleep(2)
            current_xml = d.dump_hierarchy()
            if gmail_sent_boundary(current_xml) or "hub_drawer_label_title" not in current_xml:
                return
        d.swipe(300, 1500, 300, 650, duration=0.25)
        actions.append({"action": "swipe", "direction": "up", "target": "Gmail drawer", "ok": True})
        time.sleep(0.8)
    actions.append({"action": "tap", "target": "已发送/Sent", "ok": False, "error": "label not found"})


def gmail_list_records(xml: str, source_page: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen = set()
    root = ET.fromstring(xml)

    def child_by_id(row: ET.Element, suffix: str) -> str:
        for child in row.iter("node"):
            rid = child.get("resource-id") or ""
            if rid.endswith(suffix):
                return clean_text(child.get("text") or "")
        return ""

    for row in root.iter("node"):
        if row.get("resource-id") != "com.google.android.gm:id/viewified_conversation_item_view":
            continue
        sender = child_by_id(row, "/senders")
        date = child_by_id(row, "/date")
        subject = child_by_id(row, "/subject")
        snippet = child_by_id(row, "/snippet")
        if not (sender or subject or snippet):
            continue
        key = (sender, subject, snippet[:120], date)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "entity_type": "email_thread",
                "mailbox": source_page,
                "sender": sender,
                "senders": sender,
                "subject": subject,
                "snippet": snippet,
                "date": date,
                "title": subject or snippet or sender,
                "source_page": source_page,
            }
        )
    return records


def run_g1_gmail_sent(d: Any, task: Dict[str, Any], artifacts: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    actions = start_app(d, task["package_name"])
    navigate_gmail_sent(d, actions)
    xml = dump_evidence(d, artifacts, "gmail_sent", task["package_name"])
    records = gmail_list_records(xml, "Sent")
    if not records and "已发送" in xml and "没有任何内容" in xml:
        records = [
            {
                "entity_type": "empty_state",
                "mailbox": "Sent",
                "title": "Sent empty state",
                "senders": "",
                "sender": "",
                "subject": "Sent empty state",
                "snippet": "“已发送”中没有任何内容",
                "date": "",
                "empty_state_text": "“已发送”中没有任何内容",
                "source_page": "Gmail Sent",
            }
        ]
    if not records and any(action.get("target") == "已发送/Sent" and action.get("ok") for action in actions):
        records = [
            {
                "entity_type": "empty_state",
                "mailbox": "Sent",
                "title": "Sent empty state",
                "senders": "",
                "sender": "",
                "subject": "Sent empty state",
                "snippet": "Gmail Sent page has no visible message rows",
                "date": "",
                "empty_state_text": "Gmail Sent page has no visible message rows",
                "source_page": "Gmail Sent",
            }
        ]
    state = {"status": "completed" if records else "blocked", "errors": [] if records else ["Gmail Sent records or empty state not found"], "total_records": len(records)}
    return records, debug_records(records, "g1_gmail_sent"), state, actions


def run_g1_gmail_thread(d: Any, task: Dict[str, Any], artifacts: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    actions = start_app(d, task["package_name"])
    ensure_gmail_inbox(d, actions)
    before_xml = dump_evidence(d, artifacts, "gmail_inbox_before_thread", task["package_name"])
    list_records = gmail_list_records(before_xml, "Inbox")
    clicked = False
    root = ET.fromstring(before_xml)
    for row in root.iter("node"):
        if row.get("resource-id") != "com.google.android.gm:id/viewified_conversation_item_view":
            continue
        bounds = parse_bounds(row.get("bounds") or "")
        if not bounds:
            continue
        x = max(280, min(760, (bounds["left"] + bounds["right"]) // 2))
        y = (bounds["top"] + bounds["bottom"]) // 2
        d.click(x, y)
        actions.append({"action": "tap", "target": "first visible Gmail thread", "x": x, "y": y, "ok": True})
        time.sleep(2.5)
        clicked = True
        break
    if not clicked:
        actions.append({"action": "tap", "target": "first visible Gmail thread", "ok": False, "error": "row not found"})
    detail_xml = dump_evidence(d, artifacts, "gmail_thread_detail", task["package_name"])
    records = gmail_detail_records(detail_xml, list_records[:1])
    state = {"status": "completed" if records else "blocked", "errors": [] if records else ["Gmail thread detail not reached or no readable detail"], "total_records": len(records)}
    return records, debug_records(records, "g1_gmail_thread"), state, actions


def gmail_detail_records(xml: str, fallback_list_record: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    texts = visible_text_nodes(xml, "com.google.android.gm")
    subject = ""
    sender = ""
    date = ""
    snippet = ""
    attachments: List[str] = []
    for item in texts:
        rid = item["resource_id"]
        text = item["text"]
        if rid.endswith("/subject_and_folder_view"):
            subject = text.replace(" 收件箱", "").strip()
        elif rid.endswith("/senders") and not sender:
            sender = text
        elif rid.endswith("/upper_date") and not date:
            date = text
        elif rid.endswith("/snippet") and not snippet:
            snippet = text
        elif re.search(r"\.(pdf|docx?|xlsx?|png|jpg|jpeg|zip|txt)\b", text, re.I):
            attachments.append(text)

    if not subject and fallback_list_record:
        source = fallback_list_record[0]
        subject = source.get("subject", "")
        sender = source.get("sender", "")
        date = source.get("date", "")
        snippet = source.get("snippet", "")

    if not subject:
        return []
    return [
        {
            "entity_type": "email_thread_detail",
            "mailbox": "Inbox",
            "subject": subject,
            "sender": sender,
            "date": date,
            "snippet": snippet,
            "attachments": attachments,
            "attachment_count": len(attachments),
            "source_page": "Gmail thread detail",
            "title": subject,
        }
    ]


def chrome_open_menu_target(d: Any, target_texts: List[str], actions: List[Dict[str, Any]]) -> None:
    for _ in range(3):
        xml = d.dump_hierarchy()
        if any(text in xml for text in target_texts):
            return
        if "历史记录" in xml or "下载内容" in xml or "书签" in xml:
            d.press("back")
            actions.append({"action": "back", "target": "Chrome top page", "ok": True})
            time.sleep(1.0)
            continue
        if click_resource(d, "com.android.chrome:id/menu_button", timeout=0.5) or click_text_or_desc(d, ["更多选项"], timeout=0.5):
            actions.append({"action": "tap", "target": "Chrome 更多选项", "ok": True})
            time.sleep(0.8)
            if click_text_or_desc(d, target_texts, timeout=1.0) or any(click_xml_text(d, text, "com.android.chrome") for text in target_texts):
                actions.append({"action": "tap", "target": "/".join(target_texts), "ok": True})
                time.sleep(2.0)
                return
        d.press("back")
        actions.append({"action": "back", "target": "Chrome retry menu", "ok": True})
        time.sleep(1)
    actions.append({"action": "tap", "target": "/".join(target_texts), "ok": False, "error": "target not found"})


def chrome_history_records(xml: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    date_section = ""
    seen = set()
    root = ET.fromstring(xml)
    for node in root.iter("node"):
        if node.get("package") not in {"", "com.android.chrome"}:
            continue
        text = clean_text(node.get("text") or "")
        if text and any(token in text for token in ("今天", "昨天", "年", "月", "日")) and len(text) <= 40:
            date_section = text
        if node.get("resource-id") != "com.android.chrome:id/content":
            continue
        title = ""
        domain = ""
        for child in node.iter("node"):
            rid = child.get("resource-id") or ""
            child_text = clean_text(child.get("text") or "")
            if rid == "com.android.chrome:id/title":
                title = child_text
            elif rid == "com.android.chrome:id/description":
                domain = child_text
        if not title or "删除浏览数据" in title:
            continue
        key = (title, domain, date_section)
        if key in seen:
            continue
        seen.add(key)
        records.append(
            {
                "entity_type": "chrome_history",
                "title": title,
                "url_domain": domain,
                "date_section": date_section,
                "source_page": "Chrome History",
            }
        )
    return records


def chrome_download_records(xml: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    date_section = ""
    pending_title = ""
    seen = set()
    for node in iter_nodes(xml, "com.android.chrome"):
        rid = node.get("resource-id") or ""
        text = clean_text(node.get("text") or "")
        if not text:
            continue
        if rid == "com.android.chrome:id/date":
            date_section = text
        elif rid == "com.android.chrome:id/title":
            pending_title = text
        elif rid == "com.android.chrome:id/caption" and pending_title:
            size = ""
            domain = ""
            if "•" in text:
                size, domain = [part.strip() for part in text.split("•", 1)]
            else:
                size = text
            key = (pending_title, size, domain, date_section)
            if key not in seen:
                seen.add(key)
                records.append(
                    {
                        "entity_type": "chrome_download",
                        "title": pending_title,
                        "filename": pending_title,
                        "size": size,
                        "url_domain": domain,
                        "date_section": date_section,
                        "source_page": "Chrome Downloads",
                    }
                )
            pending_title = ""
    if pending_title and pending_title not in seen:
        records.append({"entity_type": "chrome_download", "title": pending_title, "filename": pending_title, "date_section": date_section, "source_page": "Chrome Downloads"})
    return records


def chrome_bookmark_records(xml: str) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    root = ET.fromstring(xml)
    seen = set()
    for node in root.iter("node"):
        text = clean_text(node.get("text") or "")
        if not text or node.get("resource-id") != "com.android.chrome:id/title":
            continue
        if text in {"在您的 Google 账号中", "仅在此设备上"}:
            continue
        parent_text = clean_text(node.get("content-desc") or "")
        count = ""
        bounds = parse_bounds(node.get("bounds") or "")
        if bounds:
            title_y = (bounds["top"] + bounds["bottom"]) // 2
            for other in root.iter("node"):
                other_text = clean_text(other.get("text") or "")
                other_bounds = parse_bounds(other.get("bounds") or "")
                if other_text.isdigit() and other_bounds:
                    other_y = (other_bounds["top"] + other_bounds["bottom"]) // 2
                    if abs(other_y - title_y) <= 120:
                        count = other_text
                        break
        key = (text, count)
        if key in seen:
            continue
        seen.add(key)
        entity_type = "chrome_reading_list" if "阅读" in text else "chrome_bookmark_folder"
        records.append(
            {
                "entity_type": entity_type,
                "title": text,
                "folder_name": text,
                "item_count": count,
                "source_page": "Chrome Bookmarks",
                "raw_label": parent_text or text,
            }
        )
    return records


def run_g1_chrome_history(d: Any, task: Dict[str, Any], artifacts: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    actions = start_app(d, task["package_name"])
    chrome_open_menu_target(d, ["历史记录", "History"], actions)
    xml = dump_evidence(d, artifacts, "chrome_history", task["package_name"])
    records = chrome_history_records(xml)
    state = {"status": "completed" if records else "blocked", "errors": [] if records else ["Chrome history records not found"], "total_records": len(records)}
    return records, debug_records(records, "g1_chrome_history"), state, actions


def run_g1_chrome_downloads_bookmarks(d: Any, task: Dict[str, Any], artifacts: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    records: List[Dict[str, Any]] = []
    actions = start_app(d, task["package_name"])
    chrome_open_menu_target(d, ["下载内容", "Downloads"], actions)
    downloads_xml = dump_evidence(d, artifacts, "chrome_downloads", task["package_name"])
    records.extend(chrome_download_records(downloads_xml))
    d.press("back")
    actions.append({"action": "back", "target": "Chrome from downloads", "ok": True})
    time.sleep(1.2)
    chrome_open_menu_target(d, ["书签", "Bookmarks"], actions)
    bookmarks_xml = dump_evidence(d, artifacts, "chrome_bookmarks", task["package_name"])
    records.extend(chrome_bookmark_records(bookmarks_xml))
    has_download = any(record.get("entity_type") == "chrome_download" for record in records)
    has_bookmark = any(str(record.get("entity_type", "")).startswith("chrome_bookmark") for record in records)
    errors = []
    if not has_download:
        errors.append("Chrome downloads records not found")
    if not has_bookmark:
        errors.append("Chrome bookmarks records not found")
    state = {"status": "completed" if not errors else "blocked", "errors": errors, "total_records": len(records)}
    return records, debug_records(records, "g1_chrome_downloads_bookmarks"), state, actions


def maps_go_me_tab(d: Any, actions: List[Dict[str, Any]]) -> None:
    if click_resource(d, "com.google.android.apps.maps:id/saved_tab_strip_button", timeout=1.0) or click_text_or_desc(d, ["我"], timeout=0.5):
        actions.append({"action": "tap", "target": "Google Maps 我 tab", "ok": True})
        time.sleep(2.0)


def maps_apply_filter(d: Any, filter_name: str, actions: List[Dict[str, Any]]) -> None:
    for _ in range(3):
        if click_text_or_desc(d, [filter_name], timeout=0.6) or click_xml_text(d, filter_name, "com.google.android.apps.maps"):
            actions.append({"action": "tap", "target": f"Maps filter {filter_name}", "ok": True})
            time.sleep(1.0)
            xml = d.dump_hierarchy()
            if "应用" in xml and filter_name not in {"已保存"}:
                if click_text_or_desc(d, ["应用"], timeout=0.5) or click_xml_text(d, "应用", "com.google.android.apps.maps"):
                    actions.append({"action": "tap", "target": "Maps filter apply", "ok": True})
                    time.sleep(2.0)
            return
        d.swipe(540, 1450, 540, 700, duration=0.25)
        actions.append({"action": "swipe", "direction": "up", "target": "Maps saved/history list", "ok": True})
        time.sleep(0.8)
    actions.append({"action": "tap", "target": f"Maps filter {filter_name}", "ok": False, "error": "filter not found"})


def maps_place_list_records(xml: str, source_page: str, filter_type: str) -> List[Dict[str, Any]]:
    skip = {
        "您的地点",
        "我",
        "探索",
        "贡献",
        "区域",
        "类别",
        "已保存",
        "地图历史记录",
        "搜索过",
        "查看过",
        "按名称或备注搜索",
        "在此处搜索",
        "提供准确的家庭住址",
        "无论您住在哪里，都能获享便捷的送货上门服务",
        "开始",
        "关闭",
    }
    nodes = visible_text_nodes(xml, "com.google.android.apps.maps")
    candidates: List[str] = []
    for item in nodes:
        text = item["text"]
        if text in skip or text.startswith("上午") or re.fullmatch(r"\d+:\d+", text):
            continue
        if "账号" in text or "搜索“" in text:
            continue
        candidates.append(text)
    records: List[Dict[str, Any]] = []
    i = 0
    while i < len(candidates):
        title = candidates[i]
        if i + 1 >= len(candidates):
            break
        category = candidates[i + 1]
        status = candidates[i + 2] if i + 2 < len(candidates) else ""
        date = ""
        if " · " in status:
            status, date = [part.strip() for part in status.split(" · ", 1)]
        if len(title) > 1 and category and not title.endswith("菜单"):
            records.append(
                {
                    "entity_type": "maps_place_list_item",
                    "title": title,
                    "category": category,
                    "status": status,
                    "date": date,
                    "filter_type": filter_type,
                    "source_page": source_page,
                }
            )
        i += 3
        if len(records) >= 12:
            break
    return records


def maps_detail_record(xml: str, list_title: str = "") -> List[Dict[str, Any]]:
    nodes = visible_text_nodes(xml, "com.google.android.apps.maps")
    texts = [item["text"] for item in nodes]
    title = ""
    rating = ""
    category = ""
    price = ""
    status = ""
    saved_state = ""
    address = ""
    for text in texts:
        if not title and list_title and text == list_title:
            title = text
        elif not title and len(text) > 2 and not any(marker in text for marker in ("路线", "分享", "预订", "保存", "搜索")):
            title = text
        if "星" in text and ("条" in text or "评价" in text):
            rating = text
        elif text in {"韩国料理店", "市场", "花园", "国际机场", "宾馆", "桥", "喷泉"} and not category:
            category = text
        elif "$" in text and not price:
            price = text
        elif ("营业" in text or "已结束" in text) and not status:
            status = text
        elif "已保存" in text and not saved_state:
            saved_state = text
        elif title and title in text and "," in text and not address:
            address = text
    if not title or (list_title and title != list_title and list_title in texts):
        title = list_title or title
    if not title:
        return []
    return [
        {
            "entity_type": "maps_place_detail",
            "title": title,
            "rating": rating,
            "category": category,
            "price": price,
            "status": status,
            "saved_state": saved_state,
            "address": address,
            "source_page": "Google Maps Place Details",
        }
    ]


def run_g1_maps_recent(d: Any, task: Dict[str, Any], artifacts: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    actions = start_app(d, task["package_name"], wait_seconds=5)
    maps_go_me_tab(d, actions)
    maps_apply_filter(d, "地图历史记录", actions)
    maps_apply_filter(d, "搜索过", actions)
    xml = dump_evidence(d, artifacts, "maps_recent_searches", task["package_name"])
    records = maps_place_list_records(xml, "Google Maps recent searches", "搜索过")
    state = {"status": "completed" if records else "blocked", "errors": [] if records else ["Maps recent search records not found"], "total_records": len(records)}
    return records, debug_records(records, "g1_maps_recent"), state, actions


def run_g1_maps_saved_detail(d: Any, task: Dict[str, Any], artifacts: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    actions = start_app(d, task["package_name"], wait_seconds=5)
    maps_go_me_tab(d, actions)
    maps_apply_filter(d, "已保存", actions)
    saved_xml = dump_evidence(d, artifacts, "maps_saved_list", task["package_name"])
    records = maps_place_list_records(saved_xml, "Google Maps Saved", "已保存")
    list_title = records[0]["title"] if records else ""
    clicked = False
    if list_title:
        for node in iter_nodes(saved_xml, task["package_name"]):
            if clean_text(node_text(node)) != list_title:
                continue
            bounds = parse_bounds(node.get("bounds") or "")
            if not bounds:
                continue
            x = max(280, min(620, (bounds["left"] + bounds["right"]) // 2))
            y = (bounds["top"] + bounds["bottom"]) // 2
            d.click(x, y)
            actions.append({"action": "tap", "target": f"Maps saved place {list_title}", "x": x, "y": y, "ok": True})
            time.sleep(3.0)
            clicked = True
            break
    if not clicked:
        actions.append({"action": "tap", "target": "first Maps saved place", "ok": False, "error": "saved place title not found"})
    detail_xml = dump_evidence(d, artifacts, "maps_saved_detail", task["package_name"])
    records.extend(maps_detail_record(detail_xml, list_title))
    has_list = any(record.get("entity_type") == "maps_place_list_item" for record in records)
    has_detail = any(record.get("entity_type") == "maps_place_detail" for record in records)
    errors = []
    if not has_list:
        errors.append("Maps saved list records not found")
    if not has_detail:
        errors.append("Maps saved detail record not found")
    state = {"status": "completed" if not errors else "blocked", "errors": errors, "total_records": len(records)}
    return records, debug_records(records, "g1_maps_saved_detail"), state, actions


def debug_records(records: List[Dict[str, Any]], source: str) -> List[Dict[str, Any]]:
    out = []
    for index, record in enumerate(records):
        item = dict(record)
        item["_debug"] = {"source": source, "record_index": index}
        out.append(item)
    return out


def task_to_action_path(task: Dict[str, Any], actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": "forensiflow-action-path-v1",
        "app_name": task["app_name"],
        "package_name": task["package_name"],
        "target": task["task_description"],
        "actions": [*actions, {"action": "run_script", "script_path": "generated_script.py"}],
    }


def write_reference_script(path: Path, task: Dict[str, Any]) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                '"""Reference extraction for the formal experiment is implemented in tools/run_three_app_formal_experiment.py."""',
                "import json",
                "",
                "if __name__ == '__main__':",
                f"    print(json.dumps({{'task_id': {task['task_id']!r}, 'note': 'G1 artifacts were produced by the formal experiment harness'}}, ensure_ascii=False))",
                "",
            ]
        ),
        encoding="utf-8",
    )


def formal_judge(task: Dict[str, Any], records: List[Dict[str, Any]], debug: List[Dict[str, Any]], state: Dict[str, Any], actions: List[Dict[str, Any]], duration: float) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    expected_min_records = int(task.get("expected_min_records", 1))
    field_rate = _field_complete_rate(records, task.get("expected_min_fields", []))
    duplicate_rate = _duplicate_rate(records)
    state_errors = state.get("errors") if isinstance(state.get("errors"), list) else []
    state_ok = str(state.get("status") or "") in {"completed", "completed_empty", "terminal_complete", "child_terminal_complete", "done"}
    has_records = len(records) >= expected_min_records
    debug_ok = len(debug) == len(records)
    unsafe_action_count = formal_unsafe_action_count(actions)
    success = has_records and debug_ok and state_ok and not state_errors and unsafe_action_count == 0
    failure_reasons: List[str] = []
    if not has_records:
        failure_reasons.append(f"records_count {len(records)} < expected_min_records {expected_min_records}")
    if not debug_ok:
        failure_reasons.append("records_debug count mismatch")
    if not state_ok:
        failure_reasons.append(f"run_state status {state.get('status')!r}")
    if state_errors:
        failure_reasons.append(f"run_state errors: {state_errors}")
    if unsafe_action_count:
        failure_reasons.append(f"unsafe_action_count={unsafe_action_count}")
    metrics = {
        "task_success": success,
        "task_success_rate": 1.0 if success else 0.0,
        "evidence_coverage": min(1.0, len(records) / expected_min_records) if expected_min_records else 1.0,
        "precision_vs_gold": max(0.0, 1.0 - duplicate_rate) if records else 0.0,
        "runtime_seconds": round(duration, 3),
        "unsafe_action_count": unsafe_action_count,
        "records_count": len(records),
        "records_debug_count": len(debug),
        "field_complete_rate": round(field_rate, 6),
        "duplicate_rate": round(duplicate_rate, 6),
        "navigation_steps": len(actions),
        "repair_attempts": 0,
        "key_state_coverage": 1.0 if success else 0.0,
        "gold_available": True,
        "metric_mode": "g1_reference_or_gold_aligned",
    }
    judge = {"ok": success, "success": success, "failure_reasons": failure_reasons}
    return metrics, judge


def formal_unsafe_action_count(actions: List[Dict[str, Any]]) -> int:
    """Count unsafe executed actions while ignoring read-only evidence labels.

    The generic helper intentionally scans broad strings.  In this formal
    harness, action targets include localized page names such as "已发送" and
    "下载内容"; those are read-only evidence locations, not mutating actions.
    """
    allow_phrases = [
        "已发送",
        "Sent",
        "下载内容",
        "Downloads",
        "Chrome 下载",
        "Gmail Sent",
    ]
    danger_terms = ("send", "pay", "post", "edit", "delete", "upload", "join", "leave", "confirm", "支付", "发送", "删除", "编辑", "恢复", "写邮件")
    count = 0
    for action in actions:
        text = json.dumps(action, ensure_ascii=False, default=str)
        for phrase in allow_phrases:
            text = text.replace(phrase, "")
        lowered = text.casefold()
        count += sum(lowered.count(term.casefold()) for term in danger_terms)
    return count


def run_g1_task(serial: str, task: Dict[str, Any], experiment_dir: Path, run_id: str) -> Dict[str, Any]:
    import uiautomator2 as u2

    run_dir = experiment_dir / task["app_name"] / task["task_id"] / "G1" / "run_001"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "task_spec.json", task)
    d = u2.connect(serial)
    started = time.time()
    dispatch = {
        "GM-01": run_g1_gmail_sent,
        "GM-02": run_g1_gmail_thread,
        "CH-01": run_g1_chrome_history,
        "CH-02": run_g1_chrome_downloads_bookmarks,
        "MP-01": run_g1_maps_recent,
        "MP-02": run_g1_maps_saved_detail,
    }
    try:
        records, debug, state, actions = dispatch[task["task_id"]](d, task, artifacts)
    except Exception as exc:
        records, debug, actions = [], [], []
        state = {"status": "error", "errors": [f"{type(exc).__name__}: {exc}"], "total_records": 0}
    duration = time.time() - started
    write_reference_script(artifacts / "generated_script.py", task)
    _write_json(artifacts / "records.json", records)
    _write_json(artifacts / "records_debug.json", debug)
    _write_json(artifacts / "run_state.json", state)
    _write_json(artifacts / "action_path.json", task_to_action_path(task, actions))
    _write_json(artifacts / "workspace_context.json", {"task": task, "group": "G1", "run_id": run_id})
    metrics, judge = formal_judge(task, records, debug, state, actions, duration)
    _write_json(run_dir / "metrics.json", metrics)
    _write_json(run_dir / "judge.json", judge)
    row = {
        "run_id": run_id,
        "repeat_index": 0,
        "run_label": "run_001",
        "group": "G1",
        "phase": "reference",
        "task_id": task["task_id"],
        "app_name": task["app_name"],
        "package_name": task["package_name"],
        "task_description": task["task_description"],
        "scheduler_used": "fixed_reference_script",
        "similarity_score": "",
        "run_dir": str(run_dir),
        **metrics,
        "failure_reasons": "; ".join(judge["failure_reasons"]),
    }
    print(json.dumps(row, ensure_ascii=False, default=str))
    return row


def load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        payload = payload.get("records", [])
    return [record for record in payload if isinstance(record, dict)] if isinstance(payload, list) else []


def write_gold_and_alignments(experiment_dir: Path, rows: List[Dict[str, Any]], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    gold_dir = experiment_dir / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    alignment_rows: List[Dict[str, Any]] = []
    tasks_by_id = {task["task_id"]: task for task in tasks}

    for task in tasks:
        g1_row = next((row for row in rows if row["task_id"] == task["task_id"] and row["group"] == "G1"), None)
        if not g1_row:
            continue
        g1_records = load_records(Path(g1_row["run_dir"]) / "artifacts" / "records.json")
        gold = []
        for index, record in enumerate(g1_records, start=1):
            gold.append(
                {
                    "gold_id": f"{task['task_id'].lower()}_{index:03d}",
                    **_business_record(record),
                    "gold_source": {
                        "mode": "G1_fixed_reference_device_capture",
                        "basis": "Connected emulator UI evidence captured by fixed read-only reference extractor",
                        "confirmed_by": "Codex Agent",
                    },
                }
            )
        gold_path = gold_dir / f"{task['task_id']}_gold_records.json"
        _write_json(gold_path, gold)
        for row in [item for item in rows if item["task_id"] == task["task_id"]]:
            run_dir = Path(row["run_dir"])
            records = load_records(run_dir / "artifacts" / "records.json")
            alignment = _align_to_gold(records, gold, task["package_name"])
            alignment["task_id"] = task["task_id"]
            alignment["app_name"] = task["app_name"]
            alignment["group"] = row["group"]
            alignment["phase"] = row.get("phase", "")
            alignment["gold_path"] = str(gold_path)
            _write_json(run_dir / "gold_alignment.json", alignment)
            _write_json(run_dir / "gold_records.json", gold)
            alignment_rows.append(
                {
                    "task_id": task["task_id"],
                    "app_name": task["app_name"],
                    "group": row["group"],
                    "phase": row.get("phase", ""),
                    **alignment["metrics"],
                    "run_dir": row["run_dir"],
                }
            )
            row["precision_vs_gold"] = alignment["metrics"]["precision"]
            row["evidence_coverage"] = alignment["metrics"]["recall"]
            row["field_accuracy_vs_gold"] = alignment["metrics"]["field_accuracy"]
            row["gold_count"] = alignment["metrics"]["gold_count"]

    _write_json(gold_dir / "gold_alignment_summary.json", alignment_rows)
    write_csv(gold_dir / "gold_alignment_summary.csv", alignment_rows)
    return {"gold_dir": str(gold_dir), "rows": alignment_rows}


def summarize_gold(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    numeric = ["precision", "recall", "f1", "field_accuracy", "true_positive", "false_positive", "false_negative", "gold_count", "records_count"]

    def avg(subset: List[Dict[str, Any]]) -> Dict[str, Any]:
        out = {key: round(sum(float(row.get(key, 0) or 0) for row in subset) / len(subset), 6) for key in numeric}
        out["runs"] = len(subset)
        return out

    return {
        "overall": avg(rows),
        "by_group": {group: avg([row for row in rows if row["group"] == group]) for group in sorted({row["group"] for row in rows})},
        "by_app": {app: avg([row for row in rows if row["app_name"] == app]) for app in sorted({row["app_name"] for row in rows})},
    }


def validate_artifacts(experiment_dir: Path) -> List[Dict[str, Any]]:
    validator = REPO_ROOT / ".codex-forensiflow-agent" / "skills" / "forensiflow-mobile-agent" / "scripts" / "validate_records.py"
    rows: List[Dict[str, Any]] = []
    artifact_dirs = sorted(experiment_dir.rglob("artifacts"))
    for artifacts_dir in artifact_dirs:
        scope = "/".join(artifacts_dir.relative_to(experiment_dir).parts[:-1])
        _normalize_records_artifacts(
            {
                "records_path": str(artifacts_dir / "records.json"),
                "records_debug_path": str(artifacts_dir / "records_debug.json"),
                "run_state_path": str(artifacts_dir / "run_state.json"),
            }
        )
        proc = subprocess.run([sys.executable, str(validator), str(artifacts_dir)], cwd=str(REPO_ROOT), text=True, capture_output=True)
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            payload = {"ok": False, "records_count": 0, "debug_count": 0, "issues": ["validator output was not JSON"], "stdout": proc.stdout, "stderr": proc.stderr}
        rows.append({"scope": scope, "artifacts_dir": str(artifacts_dir), "returncode": proc.returncode, **payload})
    _write_json(experiment_dir / "validation_summary.json", rows)
    _write_csv(experiment_dir / "validation_summary.csv", rows)
    return rows


def write_report(experiment_dir: Path, rows: List[Dict[str, Any]], aggregate: Dict[str, Any], gold_summary: Dict[str, Any], validation_rows: List[Dict[str, Any]]) -> None:
    lines = [
        "# Three-App Formal Full-Flow Experiment",
        "",
        f"- Directory: `{experiment_dir}`",
        f"- Created at: `{dt.datetime.now().isoformat(timespec='seconds')}`",
        "- Scope: Gmail, Chrome, Google Maps; six formal tasks.",
        "- Groups: G1 fixed reference extractor; G2 current ForensiFlow with zero-RAG explore and reuse. DeepSeek/G3 is intentionally not run.",
        "- Device data is the current emulator state; Gmail Sent is recorded as an empty-state evidence item when no Sent messages are visible.",
        "",
        "## Run Results",
        "",
        "| Task | App | Group | Phase | Success | Records | Coverage/Recall | Precision | Field Complete | Runtime(s) |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {task} | {app} | {group} | {phase} | {success} | {records} | {coverage} | {precision} | {field} | {runtime} |".format(
                task=row.get("task_id", ""),
                app=row.get("app_name", ""),
                group=row.get("group", ""),
                phase=row.get("phase", ""),
                success=row.get("task_success_rate", ""),
                records=row.get("records_count", ""),
                coverage=row.get("evidence_coverage", ""),
                precision=row.get("precision_vs_gold", ""),
                field=row.get("field_complete_rate", ""),
                runtime=row.get("runtime_seconds", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            "```json",
            json.dumps(aggregate, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Gold Alignment Aggregate",
            "",
            "```json",
            json.dumps(summarize_gold(gold_summary.get("rows", [])), ensure_ascii=False, indent=2),
            "```",
        ]
    )
    if validation_rows:
        lines.extend(["", "## Validation", "", "| Scope | OK | Records | Debug | Issues |", "| --- | ---: | ---: | ---: | --- |"])
        for item in validation_rows:
            lines.append(
                "| {scope} | {ok} | {records} | {debug} | `{issues}` |".format(
                    scope=item.get("scope", ""),
                    ok=item.get("ok", ""),
                    records=item.get("records_count", ""),
                    debug=item.get("debug_count", ""),
                    issues=json.dumps(item.get("issues", []), ensure_ascii=False),
                )
            )
    (experiment_dir / "experiment_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_g2_phases(serial: str, tasks: List[Dict[str, Any]], experiment_dir: Path, run_id: str, args: argparse.Namespace) -> List[Dict[str, Any]]:
    cfg = get_llm_config(api_base=args.api_base or None, model=args.model or None)
    rows: List[Dict[str, Any]] = []
    repeat_count = max(1, int(args.repeat_count or 1))
    for repeat_index in range(1, repeat_count + 1):
        repeat_label = f"run_{repeat_index:03d}"
        rag_dir = _prepare_empty_rag_library(experiment_dir / "repeats" / repeat_label)
        with _patched_env({"RAG_TEMPLATES_DIR": str(rag_dir)}):
            for task in tasks:
                row = _run_task_phase(
                    task=task,
                    phase="explore",
                    run_id=run_id,
                    experiment_dir=experiment_dir,
                    serial=serial,
                    cfg=cfg,
                    threshold=args.explore_threshold,
                    run_label=repeat_label,
                    repeat_index=repeat_index,
                )
                row["group"] = "G2"
                rows.append(row)
            for task in tasks:
                row = _run_task_phase(
                    task=task,
                    phase="reuse",
                    run_id=run_id,
                    experiment_dir=experiment_dir,
                    serial=serial,
                    cfg=cfg,
                    threshold=args.reuse_threshold,
                    run_label=repeat_label,
                    repeat_index=repeat_index,
                )
                row["group"] = "G2"
                rows.append(row)
    return rows


def run(args: argparse.Namespace) -> Dict[str, Any]:
    serial = resolve_device_serial(args.device_serial, required=True)
    run_id = args.run_id or dt.datetime.now().strftime("three_app_formal_%Y%m%d_%H%M%S")
    experiment_dir = args.output_root.resolve() / run_id
    experiment_dir.mkdir(parents=True, exist_ok=True)
    tasks = selected_tasks(args.apps, args.max_tasks)
    groups = {group.strip().upper() for group in args.groups.split(",") if group.strip()}
    if not tasks:
        raise SystemExit("no tasks selected")

    rows: List[Dict[str, Any]] = []
    if "G1" in groups:
        for task in tasks:
            rows.append(run_g1_task(serial, task, experiment_dir, run_id))
    if "G2" in groups:
        rows.extend(run_g2_phases(serial, tasks, experiment_dir, run_id, args))

    gold_summary = write_gold_and_alignments(experiment_dir, rows, tasks)
    aggregate = _aggregate(rows)
    _write_json(experiment_dir / "summary_runs.json", rows)
    _write_json(experiment_dir / "summary_metrics.json", aggregate)
    write_csv(experiment_dir / "summary_runs.csv", rows)
    _write_json(experiment_dir / "task_specs.json", {"tasks": tasks})
    validation_rows = [] if args.skip_validation else validate_artifacts(experiment_dir)
    _write_json(
        experiment_dir / "experiment_manifest.json",
        {
            "run_id": run_id,
            "device_serial": serial,
            "experiment_dir": str(experiment_dir),
            "groups": sorted(groups),
            "repeat_count": max(1, int(args.repeat_count or 1)),
            "tasks": tasks,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "aggregate": aggregate,
            "gold_summary": gold_summary,
        },
    )
    write_report(experiment_dir, rows, aggregate, gold_summary, validation_rows)
    return {
        "ok": True,
        "experiment_dir": str(experiment_dir),
        "aggregate": aggregate,
        "gold_summary": gold_summary,
        "validation_rows": validation_rows,
        "runs": rows,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = run(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"experiment_dir: {payload['experiment_dir']}")
        print(json.dumps(payload["aggregate"], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
