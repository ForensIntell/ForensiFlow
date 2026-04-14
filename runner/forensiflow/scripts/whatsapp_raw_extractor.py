#!/usr/bin/env python3
"""
ForensiFlow - WhatsApp 终极通用全量取证脚本 (Raw Data 无死角直拉版)

特性：
- 全量底层 UI 元素提取（不依赖具体 ResourceID）
- XML 快照冻结 + 边界裁剪
- 完整证据链保留
- 实时数据落盘

作者：ForensiFlow Team
版本：1.1 (优化版)
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
    """
    WhatsApp 全量通用取证提取器

    通过全量提取 UI 元素的底层原始数据，实现与 WhatsApp 版本无关的通用取证。
    """

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

    def parse_universal_raw_node(self, row_node, contact_name: str) -> dict:
        """
        全量通用解析引擎：自动推理发件人身份，并提取 UI 节点
        """
        raw_data = {}
        
        # 默认发件人设定为当前的聊天对象
        sender = contact_name 
        is_system_msg = False

        # 遍历该行容器下的所有子孙节点
        for node in row_node.iter('node'):
            res_id = node.get('resource-id', '')
            text_content = node.get('text', '')
            desc_content = node.get('content-desc', '')

            # ==========================================
            # 🕵️ 发件人身份推理逻辑
            # ==========================================
            # 1. 识别时间分割线或系统提示 (通常居中显示日期)
            if 'conversation_date' in res_id or 'divider' in res_id:
                is_system_msg = True

            # 2. 识别“我”发出的消息 (只有我发的消息，才带有状态回执图标)
            if 'status' in res_id.lower() or 'message_status' in res_id.lower():
                sender = "我 (Me)"

            # 3. 识别群组中其他人的名字
            if 'name_in_group' in res_id.lower() and text_content:
                sender = text_content

            # ==========================================
            # 原始数据提取逻辑
            # ==========================================
            if not text_content and not desc_content:
                continue

            if res_id:
                short_id = res_id.replace('com.whatsapp:id/', '')
                short_id = short_id.replace('android:id/', '')
            else:
                short_id = node.get('class', 'unknown_node').split('.')[-1]

            value = text_content if text_content else f"[描述] {desc_content}"

            if short_id in raw_data:
                if isinstance(raw_data[short_id], list):
                    raw_data[short_id].append(value)
                else:
                    raw_data[short_id] = [raw_data[short_id], value]
            else:
                raw_data[short_id] = value

        if raw_data:
            # 如果判定为系统消息，强制覆盖发送者身份
            if is_system_msg:
                sender = "系统/时间"

            # 返回带有发件人标签的结构化数据
            return {
                "sender": sender,
                "raw_components": raw_data
            }
        return None

    def extract_full_chat_history(self, contact_name: str) -> list:
        """
        提取完整聊天记录（通过滑动遍历）
        """
        chat_history = []
        seen_identifiers = set()

        no_new_msg_streak = 0
        MAX_MSG_STREAK = 3

        logging.info(f"   📥 开始拉取 [{contact_name}] 的全量底层结构数据...")

        while True:
            current_view_msgs = []
            new_msgs_found = False

            page_xml = self.d.dump_hierarchy()
            try:
                root = ET.fromstring(page_xml)
            except Exception as e:
                logging.error(f"   ⚠️ XML解析失败: {e}")
                continue

            safe_top = 150
            safe_bottom = 2000
            list_node = root.find('.//node[@resource-id="android:id/list"]')
            if list_node is not None:
                _, safe_top, _, safe_bottom = self._parse_bounds(list_node.get('bounds', ''))
                safe_top += 5
                safe_bottom -= 5

            raw_rows = []
            if list_node is not None:
                for row_node in list_node.findall('./node'):
                    bounds = self._parse_bounds(row_node.get('bounds', ''))

                    if bounds[1] < safe_top or bounds[3] > safe_bottom:
                        if not (bounds[1] < safe_top and bounds[3] > safe_bottom):
                            continue

                    raw_rows.append({
                        'node': row_node,
                        'y': bounds[1]
                    })

            raw_rows.sort(key=lambda x: x['y'])

            for item in raw_rows:
                # 💡 核心修改：将当前的联系人名字传入解析引擎，作为推理依据
                parsed_msg = self.parse_universal_raw_node(item['node'], contact_name)

                if parsed_msg:
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

            self.d.swipe(0.5, 0.25, 0.5, 0.8, duration=0.4)
            time.sleep(1.5)

        return chat_history

    def browse_and_extract(self):
        """
        浏览联系人列表并提取所有聊天记录
        主流程函数，自动遍历联系人、普通群组，并穿透提取社群(Community)内的子群组数据
        """
        logging.info(f"\n{'='*60}\n🚀 全量底层吸尘器引擎启动 (支持社群穿透)\n{'='*60}")

        visited_count = 0
        contact_name_id = "com.whatsapp:id/conversations_row_contact_name"

        no_new_contacts_streak = 0
        MAX_CONTACT_STREAK = 2

        while visited_count < self.max_contacts:
            visible_elements = []
            new_elements_found = False

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

            if visible_elements:
                for text, elem in visible_elements:
                    if visited_count >= self.max_contacts:
                        break
                    if text in self.visited_contacts:
                        continue

                    logging.info(f"👉 锁定目标 #{visited_count + 1}: {text}")

                    try:
                        elem.click(timeout=3)
                        self.visited_contacts.add(text)
                        visited_count += 1
                        time.sleep(2.0)

                        # ==========================================
                        # 💡 核心修复：社群 (Community) 穿透检测逻辑
                        # ==========================================
                        if self.d(resourceId="com.whatsapp:id/community_navigation_subgroup_recycler_view").exists:
                            logging.info(f"   🏘️ 发现社群导航页: [{text}]，启动子群穿透模式...")
                            community_name = text
                            subgroup_visited = set()
                            no_new_subgroups = 0
                            
                            while True:
                                subgroup_elems = []
                                for sub_elem in self.d(resourceId=contact_name_id):
                                    if not sub_elem.exists: continue
                                    sub_text = sub_elem.info.get('text', '')
                                    if sub_text and sub_text not in subgroup_visited:
                                        subgroup_elems.append((sub_text, sub_elem))

                                if not subgroup_elems:
                                    no_new_subgroups += 1
                                    if no_new_subgroups >= 2:
                                        logging.info(f"   ✅ 社群 [{community_name}] 内的所有子群已遍历完毕。")
                                        break
                                else:
                                    no_new_subgroups = 0

                                for sub_text, sub_elem in subgroup_elems:
                                    if sub_text in subgroup_visited: continue
                                    logging.info(f"      ↳ 进入社群子群组: [{sub_text}]")
                                    
                                    sub_elem.click(timeout=3)
                                    time.sleep(2.0)

                                    # 在子群组内拉取聊天记录
                                    full_name = f"【社群】{community_name} -> {sub_text}"
                                    msgs = self.extract_full_chat_history(full_name)

                                    contact_data = {
                                        "contact_name": full_name,
                                        "message_count": len(msgs),
                                        "messages": msgs
                                    }
                                    self.append_contact_to_json(contact_data)

                                    self.d.press("back") # 退回到社群导航页
                                    subgroup_visited.add(sub_text)
                                    time.sleep(1.5)

                                # 在社群导航页内向下滑动，寻找更多子群
                                self.d.swipe(0.5, 0.8, 0.5, 0.2, duration=0.5)
                                time.sleep(1.5)

                            # 社群遍历结束，退回到主聊天列表
                            self.d.press("back")
                            time.sleep(1.5)

                        # ==========================================
                        # 正常逻辑：普通联系人或普通群组
                        # ==========================================
                        else:
                            msgs = self.extract_full_chat_history(text)
                            contact_data = {
                                "contact_name": text,
                                "message_count": len(msgs),
                                "messages": msgs
                            }
                            self.append_contact_to_json(contact_data)

                            self.d.press("back") # 退回到主聊天列表
                            time.sleep(1.5)

                    except Exception as e:
                        logging.error(f"   ✗ 处理 [{text}] 时发生异常: {e}")
                        self.d.press("back")
                        time.sleep(1)

            if visited_count < self.max_contacts and no_new_contacts_streak < MAX_CONTACT_STREAK:
                logging.info("⬇️ 主列表向下滑动获取新目标...")
                self.d.swipe(0.5, 0.8, 0.5, 0.2, duration=0.5)
                time.sleep(1.5)

        logging.info(f"\n{'='*60}\n🎉 全量底层数据固化完成: {os.path.abspath(self.output_file)}\n{'='*60}")

        return True  # ✅ 返回 True 表示脚本执行成功


def main():
    """命令行入口函数"""
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    device_serial = ""  # 留空使用默认设备
    extractor = WhatsAppUniversalExtractor(device_serial)
    extractor.browse_and_extract()


if __name__ == "__main__":
    main()
