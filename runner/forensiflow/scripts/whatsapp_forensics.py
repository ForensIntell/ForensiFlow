#!/usr/bin/env python3
"""
ForensiFlow - WhatsApp 全量通用取证脚本 (Raw Data 无死角直拉版)

特性：
- 全量底层 UI 元素提取（不依赖具体 ResourceID）
- XML 快照冻结 + 边界裁剪
- 完整证据链保留
- 实时数据落盘

作者：ForensiFlow Team
版本：1.0
"""

import os
import sys
import time
import json
import logging
import re
import xml.etree.ElementTree as ET

# 添加项目根目录到 Python 路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    import uiautomator2 as u2
except ImportError:
    print("❌ 错误：未安装 uiautomator2")
    print("请运行：pip install uiautomator2")
    sys.exit(1)


class WhatsAppUniversalExtractor:
    """WhatsApp 全量通用取证提取器"""

    def __init__(self, device_serial: str = ""):
        """
        初始化提取器

        Args:
            device_serial: Android 设备序列号，空字符串表示使用默认设备
        """
        self.d = u2.connect(device_serial) if device_serial else u2.connect()
        self.d.implicitly_wait(3.0)

        self.visited_contacts = set()
        self.max_contacts = 1000
        self.output_file = "forensiflow_universal_raw_data.json"

        # 初始化输出文件
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=4)
        logging.info(f"📁 已初始化全量底层取证数据文件: {os.path.abspath(self.output_file)}")

    def append_contact_to_json(self, contact_data: dict):
        """
        将联系人数据追加到 JSON 文件（实时落盘）

        Args:
            contact_data: 联系人数据字典
        """
        try:
            with open(self.output_file, 'r', encoding='utf-8') as f:
                current_data = json.load(f)

            current_data.append(contact_data)

            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(current_data, f, ensure_ascii=False, indent=4)

            logging.info(f"   💾 [{contact_data['contact_name']}] 的底层数据已安全落盘。")
        except Exception as e:
            logging.error(f"   ❌ 保存 [{contact_data['contact_name']}] 数据时失败: {e}")

    def _parse_bounds(self, bounds_str: str) -> list:
        """
        解析 bounds 字符串为坐标数组

        Args:
            bounds_str: bounds 字符串，格式 "[left,top][right,bottom]"

        Returns:
            [left, top, right, bottom]
        """
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
        if match:
            return [int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))]
        return [0, 0, 0, 0]

    def parse_universal_raw_node(self, row_node) -> dict:
        """
        全量通用解析引擎：不判断类型，直接提取行内所有带有内容的 UI 节点

        Args:
            row_node: XML 节点对象（一行消息的容器）

        Returns:
            包含 raw_components 的字典，如果无内容则返回 None
        """
        raw_data = {}

        # 遍历该行容器下的所有子孙节点
        for node in row_node.iter('node'):
            res_id = node.get('resource-id', '')
            text_content = node.get('text', '')
            desc_content = node.get('content-desc', '')

            # 过滤掉没有任何实质内容的空节点
            if not text_content and not desc_content:
                continue

            # 精简 ID 名称，去除冗长前缀
            if res_id:
                short_id = res_id.replace('com.whatsapp:id/', '')
                short_id = short_id.replace('android:id/', '')
            else:
                short_id = node.get('class', 'unknown_node').split('.')[-1]

            # 优先提取具体文本，其次提取无障碍描述
            value = text_content if text_content else f"[描述] {desc_content}"

            # 存入字典。如果遇到同名 ID，则转为列表存储
            if short_id in raw_data:
                if isinstance(raw_data[short_id], list):
                    raw_data[short_id].append(value)
                else:
                    raw_data[short_id] = [raw_data[short_id], value]
            else:
                raw_data[short_id] = value

        # 只要提取到了任何有效键值对，就返回
        if raw_data:
            return {"raw_components": raw_data}
        return None

    def extract_full_chat_history(self, contact_name: str) -> list:
        """
        提取完整的聊天历史记录

        Args:
            contact_name: 联系人名称

        Returns:
            聊天历史列表，每个元素是一行消息的原始 UI 数据
        """
        chat_history = []
        seen_identifiers = set()

        no_new_msg_streak = 0
        MAX_MSG_STREAK = 3

        logging.info(f"   📥 开始拉取 [{contact_name}] 的全量底层结构数据...")

        while True:
            current_view_msgs = []
            new_msgs_found = False

            # XML 快照冻结当前屏幕状态
            page_xml = self.d.dump_hierarchy()
            try:
                root = ET.fromstring(page_xml)
            except Exception as e:
                logging.error(f"   ⚠️ XML解析失败: {e}")
                continue

            # 动态计算列表边界
            safe_top = 150
            safe_bottom = 2000
            list_node = root.find('.//node[@resource-id="android:id/list"]')
            if list_node is not None:
                _, safe_top, _, safe_bottom = self._parse_bounds(list_node.get('bounds', ''))
                safe_top += 5
                safe_bottom -= 5

            # 搜集当前屏幕上的直接行容器（ViewGroup）
            raw_rows = []
            if list_node is not None:
                for row_node in list_node.findall('./node'):
                    bounds = self._parse_bounds(row_node.get('bounds', ''))

                    # 边界裁剪：抛弃跨越安全边界的残缺行
                    if bounds[1] < safe_top or bounds[3] > safe_bottom:
                        if not (bounds[1] < safe_top and bounds[3] > safe_bottom):
                            continue

                    raw_rows.append({
                        'node': row_node,
                        'y': bounds[1]
                    })

            # 基于绝对 Y 坐标全局排序，重建时间线
            raw_rows.sort(key=lambda x: x['y'])

            for item in raw_rows:
                parsed_msg = self.parse_universal_raw_node(item['node'])

                if parsed_msg:
                    # 使用 JSON 序列化作为哈希标识（完美去重）
                    identifier = json.dumps(parsed_msg, sort_keys=True)

                    if identifier not in seen_identifiers:
                        seen_identifiers.add(identifier)
                        new_msgs_found = True
                        current_view_msgs.append(parsed_msg)

            if not new_msgs_found:
                no_new_msg_streak += 1
                if no_new_msg_streak >= MAX_MSG_STREAK:
                    logging.info(f"   ✅ [{contact_name}] 的底层数据已全部拉取完毕。")
                    break
            else:
                no_new_msg_streak = 0
                chat_history = current_view_msgs + chat_history

            # 向上滑动加载更早的消息
            self.d.swipe(0.5, 0.25, 0.5, 0.8, duration=0.4)
            time.sleep(1.5)

        return chat_history

    def browse_and_extract(self):
        """遍历联系人并提取聊天记录"""
        logging.info(f"\n{'='*60}\n🚀 ForensiFlow 全量底层吸尘器引擎启动\n{'='*60}")

        visited_count = 0
        contact_name_id = "com.whatsapp:id/conversations_row_contact_name"

        no_new_contacts_streak = 0
        MAX_CONTACT_STREAK = 2

        while visited_count < self.max_contacts:
            visible_elements = []
            new_elements_found = False

            # 获取当前屏幕上的所有联系人
            for elem in self.d(resourceId=contact_name_id):
                if not elem.exists:
                    continue
                try:
                    text = elem.info.get('text', '')
                    if text and text not in self.visited_contacts:
                        visible_elements.append((text, elem))
                        new_elements_found = True
                except Exception:
                    continue

            if not new_elements_found:
                no_new_contacts_streak += 1
                if no_new_contacts_streak >= MAX_CONTACT_STREAK:
                    logging.info("\n✅ 已到达联系人列表底部，取证结束。")
                    break
            else:
                no_new_contacts_streak = 0

            # 依次访问每个联系人
            if visible_elements:
                for text, elem in visible_elements:
                    if visited_count >= self.max_contacts:
                        break
                    if text in self.visited_contacts:
                        continue

                    logging.info(f"👉 进入目标 #{visited_count + 1}: {text}")

                    try:
                        # 点击进入聊天界面
                        elem.click(timeout=3)
                        self.visited_contacts.add(text)
                        visited_count += 1

                        time.sleep(2.0)

                        # 提取聊天历史
                        msgs = self.extract_full_chat_history(text)

                        contact_data = {
                            "contact_name": text,
                            "message_count": len(msgs),
                            "messages": msgs
                        }

                        # 实时保存
                        self.append_contact_to_json(contact_data)

                        # 返回联系人列表
                        self.d.press("back")
                        time.sleep(1.5)

                    except Exception as e:
                        logging.error(f"✗ 处理 [{text}] 时发生异常: {e}")
                        self.d.press("back")
                        time.sleep(1)

            # 向下滑动查找更多联系人
            if visited_count < self.max_contacts and no_new_contacts_streak < MAX_CONTACT_STREAK:
                logging.info("⬇️ 列表向下滑动获取新目标...")
                self.d.swipe(0.5, 0.8, 0.5, 0.2, duration=0.5)
                time.sleep(1.5)

        logging.info(f"\n{'='*60}\n🎉 全量底层数据固化完成: {os.path.abspath(self.output_file)}\n{'='*60}")


def auto_detect_device() -> str:
    """
    自动检测 Android 设备

    Returns:
        设备序列号
    """
    import subprocess

    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')

    devices = []
    for line in lines[1:]:  # 跳过第一行 "List of devices attached"
        if line.strip() and "offline" not in line.lower():
            parts = line.split('\t')
            if len(parts) >= 2:
                devices.append(parts[0])

    if not devices:
        logging.error("✗ 未找到在线的 Android 设备")
        logging.info("请先连接设备：adb connect <IP:端口>")
        sys.exit(1)

    if len(devices) > 1:
        logging.info(f"⚠️ 检测到多个设备，将使用第一个: {devices[0]}")

    return devices[0]


def main():
    """主函数"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )

    print("=" * 60)
    print("ForensiFlow - WhatsApp 全量通用取证工具")
    print("=" * 60)

    # 自动检测设备
    device_serial = auto_detect_device()
    logging.info(f"✓ 使用设备: {device_serial}\n")

    # 创建提取器
    extractor = WhatsAppUniversalExtractor(device_serial)

    # 开始取证
    extractor.browse_and_extract()


if __name__ == "__main__":
    main()
