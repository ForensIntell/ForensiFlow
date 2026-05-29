"""Experimental page perception fusion for VisionTasker and Android XML.

This module is intentionally independent from the forensic execution path. It
normalizes VisionTasker page-perception JSON and simplified Android XML nodes,
then groups nodes whose vertical pixel ranges overlap into fused UI regions.
"""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


Bounds = Tuple[int, int, int, int]


LAYOUT_CLASSES = {
    "FrameLayout",
    "LinearLayout",
    "RelativeLayout",
    "ViewGroup",
    "View",
    "ConstraintLayout",
    "TableLayout",
}


@dataclass
class NormalizedElement:
    source: str
    source_id: str
    bounds: Bounds
    text: str = ""
    label: str = ""
    class_name: str = ""
    sub_class: str = ""
    resource_id: str = ""
    content_desc: str = ""
    clickable: bool = False
    scrollable: bool = False
    selected: bool = False
    checked: bool = False
    disabled: bool = False
    depth: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def x1(self) -> int:
        return self.bounds[0]

    @property
    def y1(self) -> int:
        return self.bounds[1]

    @property
    def x2(self) -> int:
        return self.bounds[2]

    @property
    def y2(self) -> int:
        return self.bounds[3]

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def center(self) -> List[int]:
        return [(self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2]

    @property
    def display_text(self) -> str:
        return self.text or self.label or self.content_desc or self.resource_id or self.sub_class or self.class_name

    def to_summary(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "source": self.source,
            "source_id": self.source_id,
            "bounds": list(self.bounds),
            "center": self.center,
            "class": self.class_name,
        }
        if self.sub_class:
            data["sub_class"] = self.sub_class
        if self.text:
            data["text"] = self.text
        if self.label and self.label != self.text:
            data["label"] = self.label
        if self.content_desc:
            data["content_desc"] = self.content_desc
        if self.resource_id:
            data["resource_id"] = self.resource_id
        traits = []
        if self.clickable:
            traits.append("clickable")
        if self.scrollable:
            traits.append("scrollable")
        if self.selected:
            traits.append("selected")
        if self.checked:
            traits.append("checked")
        if self.disabled:
            traits.append("disabled")
        if traits:
            data["traits"] = traits
        return data


@dataclass
class FusionConfig:
    vertical_overlap_threshold: float = 0.60
    horizontal_overlap_threshold: float = 0.10
    include_vision_containers: bool = False
    max_group_height_ratio: float = 0.45
    point_box_radius: int = 6
    max_description_regions: int = 80
    max_items_per_region: int = 30


def parse_bounds(value: Any, *, point_radius: int = 0) -> Optional[Bounds]:
    """Parse supported Android/VisionTasker bounds formats."""
    if value is None:
        return None

    if isinstance(value, dict):
        if {"left", "top", "right", "bottom"}.issubset(value):
            return (
                int(value["left"]),
                int(value["top"]),
                int(value["right"]),
                int(value["bottom"]),
            )
        if {"column_min", "row_min", "column_max", "row_max"}.issubset(value):
            return (
                int(value["column_min"]),
                int(value["row_min"]),
                int(value["column_max"]),
                int(value["row_max"]),
            )

    if isinstance(value, (list, tuple)) and len(value) == 4:
        return tuple(int(v) for v in value)  # type: ignore[return-value]

    if isinstance(value, (list, tuple)) and len(value) == 2:
        x, y = [int(v) for v in value]
        return (x - point_radius, y - point_radius, x + point_radius, y + point_radius)

    text = str(value or "").strip()
    nums = re.findall(r"-?\d+", text)
    if len(nums) == 4:
        x1, y1, x2, y2 = [int(v) for v in nums]
        return (x1, y1, x2, y2)
    if len(nums) == 2:
        x, y = [int(v) for v in nums]
        return (x - point_radius, y - point_radius, x + point_radius, y + point_radius)
    return None


def union_bounds(bounds_list: Sequence[Bounds]) -> Bounds:
    return (
        min(b[0] for b in bounds_list),
        min(b[1] for b in bounds_list),
        max(b[2] for b in bounds_list),
        max(b[3] for b in bounds_list),
    )


def _overlap_1d(a1: int, a2: int, b1: int, b2: int) -> int:
    return max(0, min(a2, b2) - max(a1, b1))


def vertical_overlap_ratio(a: Bounds, b: Bounds) -> float:
    overlap = _overlap_1d(a[1], a[3], b[1], b[3])
    denom = max(1, min(max(1, a[3] - a[1]), max(1, b[3] - b[1])))
    return overlap / denom


def horizontal_overlap_ratio(a: Bounds, b: Bounds) -> float:
    overlap = _overlap_1d(a[0], a[2], b[0], b[2])
    denom = max(1, min(max(1, a[2] - a[0]), max(1, b[2] - b[0])))
    return overlap / denom


def iou(a: Bounds, b: Bounds) -> float:
    inter_w = _overlap_1d(a[0], a[2], b[0], b[2])
    inter_h = _overlap_1d(a[1], a[3], b[1], b[3])
    inter = inter_w * inter_h
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    denom = area_a + area_b - inter
    if denom <= 0:
        return 0.0
    return inter / denom


def _short_resource_id(resource_id: str) -> str:
    if "/" in resource_id:
        return resource_id.rsplit("/", 1)[-1]
    return resource_id


def _short_class(class_name: str) -> str:
    if "." in class_name:
        return class_name.rsplit(".", 1)[-1]
    return class_name


def _bool_attr(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def extract_xml_elements_from_content(xml_content: str) -> List[NormalizedElement]:
    root = ET.fromstring(xml_content)
    elements: List[NormalizedElement] = []
    counter = 0

    def walk(node: ET.Element, depth: int) -> None:
        nonlocal counter
        attrs = node.attrib
        bounds = parse_bounds(attrs.get("bounds"))
        if bounds and bounds != (0, 0, 0, 0):
            class_name = _short_class(attrs.get("class") or node.tag)
            text = (attrs.get("text") or "").strip()
            desc = (attrs.get("content-desc") or "").strip()
            resource_id = _short_resource_id(attrs.get("resource-id") or "")
            clickable = _bool_attr(attrs.get("clickable"))
            scrollable = _bool_attr(attrs.get("scrollable"))
            long_clickable = _bool_attr(attrs.get("long-clickable"))
            selected = _bool_attr(attrs.get("selected"))
            checked = _bool_attr(attrs.get("checked"))
            enabled = _bool_attr(attrs.get("enabled"), True)

            has_text = bool(text or desc)
            is_interactive = clickable or scrollable or long_clickable or selected or checked
            is_layout = class_name in LAYOUT_CLASSES
            keep = has_text or is_interactive or (bool(resource_id) and not is_layout)

            if keep:
                counter += 1
                elements.append(
                    NormalizedElement(
                        source="xml",
                        source_id=f"x-{counter}",
                        bounds=bounds,
                        text=text or desc,
                        label=text or desc or resource_id,
                        class_name=class_name,
                        resource_id=resource_id,
                        content_desc=desc,
                        clickable=clickable or long_clickable,
                        scrollable=scrollable,
                        selected=selected,
                        checked=checked,
                        disabled=not enabled,
                        depth=depth,
                        raw=dict(attrs),
                    )
                )

        for child in list(node):
            walk(child, depth + 1)

    walk(root, 0)
    return elements


def extract_xml_elements_from_simplified_json(data: Any, config: Optional[FusionConfig] = None) -> List[NormalizedElement]:
    config = config or FusionConfig()
    elements: List[NormalizedElement] = []
    counter = 0

    def iter_nodes(payload: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(payload, dict) and "snapshots" in payload:
            for snapshot in payload.get("snapshots") or []:
                yield from iter_nodes(snapshot.get("elements") or [])
            return
        if isinstance(payload, dict) and "elements" in payload:
            yield from iter_nodes(payload.get("elements") or [])
            return
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item
            return
        if isinstance(payload, dict):
            yield payload

    def walk(node: Dict[str, Any], depth: int) -> None:
        nonlocal counter
        bounds = parse_bounds(
            node.get("bounds") or node.get("location") or node.get("position") or node.get("center"),
            point_radius=config.point_box_radius,
        )
        if bounds:
            counter += 1
            text = str(node.get("text") or node.get("desc") or "").strip()
            elements.append(
                NormalizedElement(
                    source="xml",
                    source_id=f"x-{counter}",
                    bounds=bounds,
                    text=text,
                    label=text or str(node.get("id") or ""),
                    class_name=str(node.get("class") or ""),
                    resource_id=str(node.get("id") or ""),
                    content_desc=str(node.get("desc") or ""),
                    clickable=bool(node.get("clickable") or node.get("long_clickable")),
                    scrollable=bool(node.get("scrollable")),
                    selected=bool(node.get("selected")),
                    checked=bool(node.get("checked")),
                    disabled=bool(node.get("disabled")),
                    depth=depth,
                    raw=dict(node),
                )
            )
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, depth + 1)

    for root in iter_nodes(data):
        walk(root, 0)
    return elements


def extract_visiontasker_elements(data: Any, config: Optional[FusionConfig] = None) -> List[NormalizedElement]:
    config = config or FusionConfig()
    elements: List[NormalizedElement] = []

    def walk(node: Any, depth: int, path: str) -> None:
        if isinstance(node, str):
            return
        if isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, depth, f"{path}.{index}")
            return
        if not isinstance(node, dict):
            return

        children = node.get("children")
        list_items = node.get("list_items")
        has_children = isinstance(children, list) and bool(children)
        has_list_items = isinstance(list_items, list) and bool(list_items)

        bounds = parse_bounds(node.get("location") or node.get("position") or node.get("bounds"))
        include_node = bool(bounds) and (
            config.include_vision_containers
            or not has_children
            or node.get("class") not in {"Block", "List"}
            or bool(node.get("text_content"))
        )

        if bounds and include_node:
            text = str(node.get("text_content") or "").strip()
            sub_class = str(node.get("sub_class") or "")
            elements.append(
                NormalizedElement(
                    source="visiontasker",
                    source_id=str(node.get("id") or f"v-{len(elements) + 1}"),
                    bounds=bounds,
                    text=text,
                    label=text or sub_class,
                    class_name=str(node.get("class") or ""),
                    sub_class=sub_class,
                    depth=depth,
                    raw=dict(node),
                )
            )

        if has_children:
            for index, child in enumerate(children):
                walk(child, depth + 1, f"{path}.children.{index}")
        if has_list_items:
            for item_index, list_item in enumerate(list_items):
                if isinstance(list_item, list):
                    for child_index, child in enumerate(list_item):
                        walk(child, depth + 1, f"{path}.list_items.{item_index}.{child_index}")
                else:
                    walk(list_item, depth + 1, f"{path}.list_items.{item_index}")

    walk(data, 0, "root")
    return elements


def _screen_height(elements: Sequence[NormalizedElement]) -> int:
    bottoms = [element.y2 for element in elements if element.y2 > element.y1]
    return max(bottoms) if bottoms else 0


def _is_region_seed(element: NormalizedElement, screen_height: int, config: FusionConfig) -> bool:
    if element.height <= 0:
        return False
    if element.source == "xml" and element.height > max(1, int(screen_height * config.max_group_height_ratio)):
        return bool(element.text or element.content_desc)
    return True


def _group_by_vertical_overlap(
    elements: Sequence[NormalizedElement],
    config: FusionConfig,
) -> List[List[NormalizedElement]]:
    screen_height = _screen_height(elements)
    seeds = [
        element
        for element in elements
        if _is_region_seed(element, screen_height, config)
    ]
    seeds.sort(key=lambda e: (e.y1, e.x1, e.y2, e.x2))

    groups: List[List[NormalizedElement]] = []
    group_bounds: List[Bounds] = []

    for element in seeds:
        placed = False
        for index, bounds in enumerate(group_bounds):
            overlap = vertical_overlap_ratio(element.bounds, bounds)
            center_y = element.center[1]
            center_inside = bounds[1] <= center_y <= bounds[3]
            if overlap >= config.vertical_overlap_threshold or center_inside:
                groups[index].append(element)
                group_bounds[index] = union_bounds([group_bounds[index], element.bounds])
                placed = True
                break
        if not placed:
            groups.append([element])
            group_bounds.append(element.bounds)

    groups.sort(key=lambda g: (min(e.y1 for e in g), min(e.x1 for e in g)))
    return groups


def _match_score(xml_element: NormalizedElement, vision_element: NormalizedElement) -> Dict[str, float]:
    v_overlap = vertical_overlap_ratio(xml_element.bounds, vision_element.bounds)
    h_overlap = horizontal_overlap_ratio(xml_element.bounds, vision_element.bounds)
    box_iou = iou(xml_element.bounds, vision_element.bounds)
    score = (0.65 * v_overlap) + (0.25 * h_overlap) + (0.10 * box_iou)
    return {
        "score": round(score, 4),
        "vertical_overlap": round(v_overlap, 4),
        "horizontal_overlap": round(h_overlap, 4),
        "iou": round(box_iou, 4),
    }


def _unique_texts(elements: Sequence[NormalizedElement]) -> List[str]:
    seen = set()
    output: List[str] = []
    for element in sorted(elements, key=lambda e: (e.y1, e.x1)):
        text = " ".join((element.display_text or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _format_element_brief(element: NormalizedElement) -> str:
    text = element.display_text
    parts = [element.source]
    if element.class_name:
        parts.append(element.class_name)
    if element.sub_class and element.sub_class != element.class_name:
        parts.append(element.sub_class)
    if text:
        parts.append(f'"{text}"')
    parts.append(f"@{list(element.bounds)}")
    return " ".join(parts)


def _build_region_description(region: Dict[str, Any]) -> str:
    items = region.get("fused_items") or []
    if not items:
        return ""
    item_texts = []
    for item in items:
        fused_text = item.get("fused_text") or ""
        source_text = "+".join(item.get("sources") or [])
        bounds = item.get("bounds")
        if fused_text:
            item_texts.append(f"{fused_text} ({source_text}, {bounds})")
        else:
            item_texts.append(f"{source_text} {bounds}")
    return "; ".join(item_texts)


def fuse_page_perception(
    *,
    vision_elements: Sequence[NormalizedElement],
    xml_elements: Sequence[NormalizedElement],
    config: Optional[FusionConfig] = None,
) -> Dict[str, Any]:
    """Fuse normalized VisionTasker and XML elements into row-like regions."""
    config = config or FusionConfig()
    all_elements = list(vision_elements) + list(xml_elements)
    groups = _group_by_vertical_overlap(all_elements, config)

    regions: List[Dict[str, Any]] = []
    matched_vision_ids = set()
    matched_xml_ids = set()

    for index, group in enumerate(groups, start=1):
        group = sorted(group, key=lambda e: (e.x1, e.y1, e.x2, e.y2))
        region_bounds = union_bounds([element.bounds for element in group])
        xml_group = [element for element in group if element.source == "xml"]
        vision_group = [element for element in group if element.source == "visiontasker"]

        fused_items: List[Dict[str, Any]] = []
        used_vision = set()

        for xml_element in sorted(xml_group, key=lambda e: (e.x1, e.y1)):
            matches = []
            for vision_element in vision_group:
                if vision_element.source_id in used_vision:
                    continue
                metrics = _match_score(xml_element, vision_element)
                if (
                    metrics["vertical_overlap"] >= config.vertical_overlap_threshold
                    and metrics["horizontal_overlap"] >= config.horizontal_overlap_threshold
                ):
                    matches.append((vision_element, metrics))
            matches.sort(key=lambda item: item[1]["score"], reverse=True)

            best_matches = matches[:3]
            for vision_element, _metrics in best_matches:
                used_vision.add(vision_element.source_id)
                matched_vision_ids.add(vision_element.source_id)
            if best_matches:
                matched_xml_ids.add(xml_element.source_id)

            fused_text_parts = [xml_element.display_text]
            for vision_element, _metrics in best_matches:
                if vision_element.display_text and vision_element.display_text not in fused_text_parts:
                    fused_text_parts.append(vision_element.display_text)

            fused_items.append(
                {
                    "type": "xml_with_vision_matches" if best_matches else "xml_only",
                    "sources": ["xml"] + (["visiontasker"] if best_matches else []),
                    "bounds": list(union_bounds([xml_element.bounds] + [v.bounds for v, _ in best_matches])),
                    "fused_text": " | ".join(part for part in fused_text_parts if part),
                    "xml": xml_element.to_summary(),
                    "vision_matches": [
                        {
                            "element": vision_element.to_summary(),
                            "metrics": metrics,
                        }
                        for vision_element, metrics in best_matches
                    ],
                }
            )

        for vision_element in sorted(vision_group, key=lambda e: (e.x1, e.y1)):
            if vision_element.source_id in used_vision:
                continue
            fused_items.append(
                {
                    "type": "vision_only",
                    "sources": ["visiontasker"],
                    "bounds": list(vision_element.bounds),
                    "fused_text": vision_element.display_text,
                    "vision": vision_element.to_summary(),
                }
            )

        fused_items.sort(key=lambda item: (item["bounds"][0], item["bounds"][1]))
        if len(fused_items) > config.max_items_per_region:
            fused_items = fused_items[: config.max_items_per_region]

        region = {
            "region_id": f"r-{index:03d}",
            "bounds": list(region_bounds),
            "y_range": [region_bounds[1], region_bounds[3]],
            "source_counts": {
                "xml": len(xml_group),
                "visiontasker": len(vision_group),
            },
            "texts": {
                "combined": _unique_texts(group),
                "xml": _unique_texts(xml_group),
                "visiontasker": _unique_texts(vision_group),
            },
            "xml_nodes": [element.to_summary() for element in xml_group],
            "vision_elements": [element.to_summary() for element in vision_group],
            "fused_items": fused_items,
        }
        region["description"] = _build_region_description(region)
        regions.append(region)

    description = render_fused_description(regions, config=config)
    return {
        "schema_version": "forensiflow.page_perception_fusion.v1",
        "parameters": {
            "vertical_overlap_threshold": config.vertical_overlap_threshold,
            "horizontal_overlap_threshold": config.horizontal_overlap_threshold,
            "include_vision_containers": config.include_vision_containers,
        },
        "stats": {
            "vision_elements": len(vision_elements),
            "xml_nodes": len(xml_elements),
            "regions": len(regions),
            "matched_vision_elements": len(matched_vision_ids),
            "matched_xml_nodes": len(matched_xml_ids),
            "vision_only_regions": sum(1 for r in regions if r["source_counts"]["xml"] == 0),
            "xml_only_regions": sum(1 for r in regions if r["source_counts"]["visiontasker"] == 0),
        },
        "regions": regions,
        "description": description,
    }


def render_fused_description(regions: Sequence[Dict[str, Any]], config: Optional[FusionConfig] = None) -> str:
    config = config or FusionConfig()
    lines = ["Fused page perception description:"]
    for region in regions[: config.max_description_regions]:
        counts = region.get("source_counts") or {}
        header = (
            f"- {region.get('region_id')} y={region.get('y_range')} "
            f"bounds={region.get('bounds')} "
            f"sources(xml={counts.get('xml', 0)}, vision={counts.get('visiontasker', 0)})"
        )
        lines.append(header)
        combined_text = region.get("texts", {}).get("combined") or []
        if combined_text:
            lines.append(f"  texts: {' | '.join(combined_text[:12])}")
        description = region.get("description") or ""
        if description:
            lines.append(f"  fused: {description}")
    if len(regions) > config.max_description_regions:
        lines.append(f"... truncated {len(regions) - config.max_description_regions} regions")
    return "\n".join(lines)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_visiontasker_json(path: Path, config: Optional[FusionConfig] = None) -> List[NormalizedElement]:
    return extract_visiontasker_elements(load_json(path), config=config)


def load_xml_or_simplified(path: Path, config: Optional[FusionConfig] = None) -> List[NormalizedElement]:
    suffixes = "".join(path.suffixes).lower()
    if path.suffix.lower() == ".xml":
        return extract_xml_elements_from_content(path.read_text(encoding="utf-8"))
    if suffixes.endswith(".json"):
        return extract_xml_elements_from_simplified_json(load_json(path), config=config)
    raise ValueError(f"Unsupported XML/simplified input: {path}")


def fuse_files(
    *,
    vision_json_path: Path,
    xml_or_simplified_path: Path,
    config: Optional[FusionConfig] = None,
) -> Dict[str, Any]:
    config = config or FusionConfig()
    vision_elements = load_visiontasker_json(vision_json_path, config=config)
    xml_elements = load_xml_or_simplified(xml_or_simplified_path, config=config)
    result = fuse_page_perception(
        vision_elements=vision_elements,
        xml_elements=xml_elements,
        config=config,
    )
    result["inputs"] = {
        "vision_json": str(vision_json_path),
        "xml_or_simplified": str(xml_or_simplified_path),
    }
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fuse VisionTasker page JSON and simplified Android XML into a page description."
    )
    parser.add_argument("--vision-json", required=True, type=Path)
    parser.add_argument("--xml", dest="xml_or_simplified", required=True, type=Path)
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-text", type=Path)
    parser.add_argument("--vertical-threshold", type=float, default=0.60)
    parser.add_argument("--horizontal-threshold", type=float, default=0.10)
    parser.add_argument("--include-vision-containers", action="store_true")
    parser.add_argument("--print", dest="print_description", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = FusionConfig(
        vertical_overlap_threshold=args.vertical_threshold,
        horizontal_overlap_threshold=args.horizontal_threshold,
        include_vision_containers=args.include_vision_containers,
    )
    result = fuse_files(
        vision_json_path=args.vision_json,
        xml_or_simplified_path=args.xml_or_simplified,
        config=config,
    )

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.out_text:
        args.out_text.parent.mkdir(parents=True, exist_ok=True)
        args.out_text.write_text(result["description"], encoding="utf-8")
    if args.print_description or not (args.out_json or args.out_text):
        print(result["description"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
