from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.forensiflow.perception.fusion import (
    FusionConfig,
    extract_visual_elements,
    extract_xml_elements_from_content,
    fuse_page_perception,
    load_xml_or_simplified,
    render_fused_description,
)


class PagePerceptionFusionTests(unittest.TestCase):
    def test_extract_visual_elements_flattens_blocks(self) -> None:
        payload = [
            "alignment: v",
            {
                "id": "b-0",
                "class": "Block",
                "alignment": "v",
                "children": [
                    {
                        "id": "c-1",
                        "class": "Compo",
                        "sub_class": "buttonicon",
                        "text_content": "同意并继续",
                        "location": {"left": 10, "top": 100, "right": 110, "bottom": 180},
                    },
                    {
                        "id": "c-2",
                        "class": "Text",
                        "sub_class": "Text",
                        "text_content": "标题：欢迎使用",
                        "location": {"left": 10, "top": 190, "right": 200, "bottom": 250},
                    },
                ],
            },
        ]
        elements = extract_visual_elements(payload)
        self.assertEqual(len(elements), 2)
        self.assertEqual(elements[0].text, "同意并继续")
        self.assertEqual(elements[1].sub_class, "Text")
        self.assertEqual(elements[1].bounds, (10, 190, 200, 250))

    def test_extract_xml_elements_from_content_keeps_visible_nodes(self) -> None:
        xml = """
        <hierarchy>
          <node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
            <node class="android.widget.TextView" text="Inbox" bounds="[100,100][300,160]" clickable="true" resource-id="pkg:id/title"/>
            <node class="android.widget.ImageView" content-desc="Star" bounds="[900,100][980,180]" clickable="true" resource-id="pkg:id/star"/>
          </node>
        </hierarchy>
        """
        elements = extract_xml_elements_from_content(xml)
        self.assertEqual([e.text or e.content_desc for e in elements], ["Inbox", "Star"])
        self.assertTrue(elements[0].clickable)
        self.assertEqual(elements[1].resource_id, "star")

    def test_fuse_page_perception_merges_vertical_overlap(self) -> None:
        vision = [
            {
                "id": "b-0",
                "class": "Block",
                "alignment": "v",
                "children": [
                    {
                        "id": "c-1",
                        "class": "Text",
                        "sub_class": "Text",
                        "text_content": "标题：Hello",
                        "location": {"left": 100, "top": 100, "right": 300, "bottom": 180},
                    },
                    {
                        "id": "c-2",
                        "class": "Compo",
                        "sub_class": "buttonicon",
                        "text_content": "按钮",
                        "location": {"left": 100, "top": 220, "right": 220, "bottom": 300},
                    },
                ],
            }
        ]
        xml = """
        <hierarchy>
          <node class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
            <node class="android.widget.TextView" text="标题：Hello" bounds="[96,96][304,184]" clickable="true"/>
            <node class="android.widget.Button" text="按钮" bounds="[96,216][224,304]" clickable="true"/>
          </node>
        </hierarchy>
        """
        result = fuse_page_perception(
            vision_elements=extract_visual_elements(vision),
            xml_elements=extract_xml_elements_from_content(xml),
            config=FusionConfig(vertical_overlap_threshold=0.35, horizontal_overlap_threshold=0.05),
        )
        self.assertEqual(result["stats"]["regions"], 2)
        self.assertGreaterEqual(result["stats"]["matched_visual_elements"], 1)
        self.assertIn("标题：Hello", result["description"])
        self.assertIn("按钮", result["description"])

    def test_load_xml_or_simplified_supports_simplified_json(self) -> None:
        simplified = [
            {
                "class": "Text",
                "text": "Hello",
                "center": [100, 120],
                "children": [
                    {
                        "class": "Text",
                        "text": "World",
                        "center": [120, 180],
                    }
                ],
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.simplified.json"
            path.write_text(json.dumps(simplified), encoding="utf-8")
            elements = load_xml_or_simplified(path)
        self.assertEqual(len(elements), 2)
        self.assertEqual({e.text for e in elements}, {"Hello", "World"})

    def test_render_fused_description_limits_regions(self) -> None:
        regions = [
            {
                "region_id": "r-001",
                "bounds": [0, 0, 100, 100],
                "y_range": [0, 100],
                "source_counts": {"xml": 1, "visual": 1},
                "texts": {"combined": ["A"], "xml": ["A"], "visual": ["A"]},
                "description": "A",
            }
        ]
        text = render_fused_description(regions)
        self.assertIn("r-001", text)
        self.assertIn("sources(xml=1, visual=1)", text)


if __name__ == "__main__":
    unittest.main()
