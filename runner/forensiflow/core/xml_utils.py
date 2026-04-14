"""
XML 简化工具类 - 新老调度器共享

功能：
1. 将 Android XML 简化为可搜索的树结构
2. 移除无意义的布局容器和隐藏元素
3. 保留重要的可交互元素
"""

import xml.etree.ElementTree as ET
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class XMLSimplifier:
    """XML 简化器 - 将 Android XML 转换为简化的树结构"""

    def __init__(self, max_length: int = 12000):
        """
        初始化简化器

        Args:
            max_length: 最大输出长度（超过则截断）
        """
        self.max_length = max_length

    def simplify_to_tree(self, xml_content: str) -> Optional[ET.Element]:
        """
        简化 XML 并返回可搜索的树结构

        Args:
            xml_content: Android dump_hierarchy 返回的原始 XML

        Returns:
            简化后的根节点（Element 对象），失败返回 None
        """
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logging.error(f"XML 解析失败: {e}")
            return None

        # 创建新的简化树
        simplified_root = self._simplify_node(root)
        return simplified_root

    def _simplify_node(self, node: ET.Element) -> Optional[ET.Element]:
        """
        递归简化单个节点

        返回:
            简化后的节点，如果节点应该被移除则返回 None
        """
        # 过滤无效元素
        bounds = node.get('bounds', '')
        if bounds == '[0,0][0,0]':
            return None

        # 提取属性
        node_class = node.get('class', '').split('.')[-1]
        text = node.get('text', '')
        desc = node.get('content-desc', '')
        res_id = node.get('resource-id', '').split('/')[-1]

        is_clickable = node.get('clickable') == 'true'
        is_scrollable = node.get('scrollable') == 'true'
        is_long_clickable = node.get('long-clickable') == 'true'
        is_selected = node.get('selected') == 'true'
        is_checked = node.get('checked') == 'true'
        is_enabled = node.get('enabled') == 'true'

        # 布局容器类型
        layout_classes = {
            'FrameLayout', 'LinearLayout', 'RelativeLayout',
            'ViewGroup', 'View', 'ConstraintLayout', 'TableLayout'
        }

        # 判断是否保留节点
        has_text_or_desc = bool(text or desc)
        is_interactive = (
            is_clickable or is_scrollable or is_long_clickable or
            is_selected or is_checked or
            node_class in ['EditText', 'CheckBox', 'Switch', 'Button', 'RadioButton']
        )
        is_layout_container = node_class in layout_classes

        keep_node = False
        if has_text_or_desc:
            keep_node = True
        elif is_interactive:
            keep_node = True
        elif not is_layout_container and res_id:
            keep_node = True

        # 如果不保留当前节点，直接返回子节点的简化结果
        if not keep_node:
            # 递归处理子节点
            simplified_children = []
            for child in node:
                simplified_child = self._simplify_node(child)
                if simplified_child is not None:
                    simplified_children.append(simplified_child)

            # 如果有子节点，返回虚拟容器
            if simplified_children:
                return self._create_container_node(simplified_children)
            return None

        # 保留当前节点，创建简化节点
        simplified_node = ET.Element('node')
        simplified_node.set('class', node_class)
        simplified_node.set('bounds', bounds)

        if text:
            simplified_node.set('text', text)
        if desc:
            simplified_node.set('content-desc', desc)
        if res_id:
            simplified_node.set('resource-id', res_id)

        # 复制重要属性
        if is_clickable:
            simplified_node.set('clickable', 'true')
        if is_scrollable:
            simplified_node.set('scrollable', 'true')
        if is_long_clickable:
            simplified_node.set('long-clickable', 'true')
        if is_selected:
            simplified_node.set('selected', 'true')
        if is_checked:
            simplified_node.set('checked', 'true')
        if not is_enabled:
            simplified_node.set('enabled', 'false')

        # 递归处理子节点
        simplified_children = []
        for child in node:
            simplified_child = self._simplify_node(child)
            if simplified_child is not None:
                simplified_children.append(simplified_child)

        # 添加子节点
        for child in simplified_children:
            simplified_node.append(child)

        return simplified_node

    def _create_container_node(self, children: List[ET.Element]) -> ET.Element:
        """创建虚拟容器节点"""
        container = ET.Element('container')
        for child in children:
            container.append(child)
        return container

    def simplify(self, xml_content: str) -> str:
        """
        简化 XML 并返回文本格式（用于 LLM prompt）

        Args:
            xml_content: Android dump_hierarchy 返回的原始 XML

        Returns:
            简化后的文本（Yaml 风格）
        """
        try:
            root = ET.fromstring(xml_content)
            simplified_data = self._simplify_ui_tree(root)
            llm_text_lines = self._to_llm_friendly_text(simplified_data)
            llm_output = "\n".join(llm_text_lines)

            if len(llm_output) > self.max_length:
                llm_output = llm_output[:self.max_length] + "\n... (UI树过长，已截断)"

            return llm_output
        except Exception as e:
            logging.warning(f"⚠️ UI树精简失败: {e}，返回原XML前段")
            return xml_content[:5000]

    def _simplify_ui_tree(self, node) -> List[dict]:
        """
        简化 UI 树为字典列表（用于文本输出）

        简化规则：
        1. 移除 bounds = [0,0][0,0] 的元素
        2. 只保留有意义的元素
        3. 移除纯布局容器
        """
        if node.attrib.get('bounds') == '[0,0][0,0]':
            return []

        simplified_children = []
        for child in node:
            simplified_children.extend(self._simplify_ui_tree(child))

        node_class = node.attrib.get('class', '').split('.')[-1]
        text = node.attrib.get('text', '')
        desc = node.attrib.get('content-desc', '')
        res_id = node.attrib.get('resource-id', '').split('/')[-1]

        is_clickable = node.attrib.get('clickable') == 'true'
        is_scrollable = node.attrib.get('scrollable') == 'true'
        is_long_clickable = node.attrib.get('long-clickable') == 'true'
        is_selected = node.attrib.get('selected') == 'true'
        is_checked = node.attrib.get('checked') == 'true'
        is_enabled = node.attrib.get('enabled') == 'true'

        layout_classes = {
            'FrameLayout', 'LinearLayout', 'RelativeLayout',
            'ViewGroup', 'View', 'ConstraintLayout', 'TableLayout'
        }

        has_text_or_desc = bool(text or desc)
        is_interactive = (
            is_clickable or is_scrollable or is_long_clickable or
            is_selected or is_checked or
            node_class in ['EditText', 'CheckBox', 'Switch', 'Button', 'RadioButton']
        )
        is_layout_container = node_class in layout_classes

        keep_node = False
        if has_text_or_desc:
            keep_node = True
        elif is_interactive:
            keep_node = True
        elif not is_layout_container and res_id:
            keep_node = True

        if not keep_node:
            return simplified_children

        clean_node = {
            "class": node_class,
            "center": self._get_center_point(node.attrib.get('bounds', ''))
        }

        if text:
            clean_node["text"] = text
        if desc:
            clean_node["desc"] = desc
        if res_id:
            clean_node["id"] = res_id

        if is_clickable:
            clean_node["clickable"] = True
        if is_scrollable:
            clean_node["scrollable"] = True
        if is_long_clickable:
            clean_node["long_clickable"] = True
        if is_selected:
            clean_node["selected"] = True
        if is_checked:
            clean_node["checked"] = True
        if not is_enabled:
            clean_node["disabled"] = True

        if simplified_children:
            clean_node["children"] = simplified_children

        return [clean_node]

    def _get_center_point(self, bounds_str: str):
        """从 bounds 字符串提取中心点"""
        import re
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
        if match:
            x1, y1, x2, y2 = map(int, match.groups())
            return [int((x1 + x2) / 2), int((y1 + y2) / 2)]
        return None

    def _to_llm_friendly_text(self, nodes: List[dict], indent=0) -> List[str]:
        """
        将简化后的节点转换为 LLM 友好的文本

        格式：
        - NodeClass(x, y) (traits) #id
          - ChildNode(x, y)
        """
        lines = []
        prefix = "  " * indent
        for node in nodes:
            parts = [f"{prefix}- {node.get('class', 'Node')}"]
            if 'text' in node:
                parts.append(f'"{node["text"]}"')
            elif 'desc' in node:
                parts.append(f'"{node["desc"]}"')
            if 'center' in node:
                parts.append(f"{node['center']}")
            traits = []
            if node.get('clickable'):
                traits.append('clickable')
            if node.get('long_clickable'):
                traits.append('long-clickable')
            if node.get('scrollable'):
                traits.append('scrollable')
            if node.get('selected'):
                traits.append('selected')
            if node.get('checked'):
                traits.append('checked')
            if node.get('disabled'):
                traits.append('disabled')
            if traits:
                parts.append(f"({', '.join(traits)})")
            if 'id' in node:
                parts.append(f"#{node['id']}")
            lines.append(" ".join(parts))
            if 'children' in node:
                lines.extend(self._to_llm_friendly_text(node['children'], indent + 1))
        return lines
