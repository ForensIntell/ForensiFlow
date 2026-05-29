#!/usr/bin/env python3
"""
ForensiFlow - WhatsApp 通话记录全量取证脚本

特性：
- 自动切换至“通话”标签页
- 提取 [联系人, 通话时间, 通话状态(呼入/呼出/未接)]
- 自动过滤底部“推荐联系人”脏数据
- 动态滑动去重与实时 JSON 落盘

作者：ForensiFlow Team
"""

import os
import sys
import time
import json
import logging
import xml.etree.ElementTree as ET

try:
    import uiautomator2 as u2
except ImportError:
    print("❌ 错误：未安装 uiautomator2")
    print("请运行：pip install uiautomator2")
    sys.exit(1)


class WhatsAppCallLogExtractor:
    def __init__(self, device_serial: str = ""):
        self.d = u2.connect(device_serial) if device_serial else u2.connect()
        self.d.implicitly_wait(3.0)

        self.output_file = "forensiflow_call_logs.json"
        self.seen_identifiers = set()
        self.call_logs = []

        # 初始化输出文件
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=4)
        logging.info(f"📁 已初始化通话记录取证数据文件: {os.path.abspath(self.output_file)}")

    def switch_to_calls_tab(self):
        """确保当前处于 '通话' 标签页"""
        logging.info("🔄 正在检测并切换至【通话】标签页...")
        
        # 尝试通过文本标签寻找底部导航栏的“通话”按钮
        tab_large = self.d(text="通话", resourceId="com.whatsapp:id/navigation_bar_item_large_label_view")
        tab_small = self.d(text="通话", resourceId="com.whatsapp:id/navigation_bar_item_small_label_view")
        
        if tab_large.exists:
            logging.info("   ✓ 当前已在通话页面。")
            return
        elif tab_small.exists:
            tab_small.click(timeout=3)
            time.sleep(2)
            logging.info("   ✓ 成功切换至通话页面。")
        else:
            # 兜底逻辑：尝试使用 content-desc 点击
            if self.d(description="通话").exists:
                self.d(description="通话").click()
                time.sleep(2)

    def _parse_bounds(self, bounds_str: str) -> list:
        import re
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
        if match:
            return [int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))]
        return [0, 0, 0, 0]

    def extract_call_logs(self):
        """滑动遍历并提取全部通话记录"""
        self.switch_to_calls_tab()
        
        logging.info(f"\n{'='*60}\n📞 全量通话记录吸尘器引擎启动\n{'='*60}")

        no_new_logs_streak = 0
        MAX_STREAK = 3

        while True:
            new_logs_found = False
            page_xml = self.d.dump_hierarchy()

            try:
                root = ET.fromstring(page_xml)
            except Exception as e:
                logging.error(f"   ⚠️ XML解析失败: {e}")
                continue

            # 提取当前屏幕内所有的通话行容器
            call_rows = root.findall('.//node[@resource-id="com.whatsapp:id/call_row_container"]')

            for row in call_rows:
                bounds = self._parse_bounds(row.get('bounds', ''))
                
                # 顶部和底部边缘的安全裁剪，防止残缺的 UI 导致解析报错
                if bounds[1] < 300 or bounds[3] > 2100:
                    continue

                # 在行容器内部精准定位三个核心信息节点
                name_node = row.find('.//node[@resource-id="com.whatsapp:id/contact_name"]')
                time_node = row.find('.//node[@resource-id="com.whatsapp:id/subtitle"]')
                icon_node = row.find('.//node[@resource-id="com.whatsapp:id/call_type_icon"]')

                # 如果缺少任何一个核心节点（例如底部的系统推荐联系人），则判定为无效记录并跳过
                if name_node is None or time_node is None or icon_node is None:
                    continue

                name = name_node.get('text', '')
                call_time = time_node.get('text', '')
                call_status = icon_node.get('content-desc', '')

                # 拼接唯一标识符进行去重
                identifier = f"{name}::{(call_time)}::{call_status}"

                if identifier not in self.seen_identifiers:
                    self.seen_identifiers.add(identifier)
                    
                    log_entry = {
                        "contact_name": name,
                        "call_time": call_time,
                        "call_status": call_status
                    }
                    self.call_logs.append(log_entry)
                    new_logs_found = True
                    
                    logging.info(f"   ⏺️ 成功提取: [{name}] | 状态: {call_status} | 时间: {call_time}")

                    # 实时落盘
                    try:
                        with open(self.output_file, 'w', encoding='utf-8') as f:
                            json.dump(self.call_logs, f, ensure_ascii=False, indent=4)
                    except Exception as e:
                        logging.error(f"   ❌ 保存数据失败: {e}")

            if not new_logs_found:
                no_new_logs_streak += 1
                if no_new_logs_streak >= MAX_STREAK:
                    logging.info(f"\n✅ 已到达通话记录列表底部，取证结束。")
                    break
            else:
                no_new_logs_streak = 0

            logging.info("⬇️ 向下滑动获取更早的通话记录...")
            self.d.swipe(0.5, 0.8, 0.5, 0.25, duration=0.5)
            time.sleep(1.5)

        logging.info(f"\n{'='*60}\n🎉 通话数据固化完成: {os.path.abspath(self.output_file)}\n{'='*60}")

        return True  # ✅ 返回 True 表示脚本执行成功

def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    extractor = WhatsAppCallLogExtractor()
    extractor.extract_call_logs()

if __name__ == "__main__":
    main()