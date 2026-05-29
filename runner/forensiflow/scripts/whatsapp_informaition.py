#!/usr/bin/env python3
"""
ForensiFlow - WhatsApp 核心身份画像提取器 (Contact Picker 定制版)

特性：
- 专为“选择联系人”界面定制，100% 精准识别并点击头像
- 自动过滤顶部的“新建群组/社群”等无关按钮
- 自动点击 Info(i) 按钮穿透至详细资料页
- 提取真实手机号、生成高清截图
- 动态滑动去重与实时 JSON 落盘

作者：ForensiFlow Team
"""

import os
import sys
import time
import json
import logging
import re

try:
    import uiautomator2 as u2
except ImportError:
    print("❌ 错误：未安装 uiautomator2，请运行：pip install uiautomator2")
    sys.exit(1)


class WhatsAppProfileExtractor:
    def __init__(self, device_serial: str = ""):
        self.d = u2.connect(device_serial) if device_serial else u2.connect()
        self.d.implicitly_wait(3.0)

        self.visited_contacts = set()
        self.profiles = []
        
        self.output_json = "forensiflow_target_profiles.json"
        self.screenshot_dir = "forensiflow_screenshots"
        
        if not os.path.exists(self.screenshot_dir):
            os.makedirs(self.screenshot_dir)

        with open(self.output_json, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=4)
            
        logging.info(f"📁 已初始化画像数据库: {os.path.abspath(self.output_json)}")
        logging.info(f"📸 截图证据存放目录: {os.path.abspath(self.screenshot_dir)}")

    def sanitize_filename(self, filename: str) -> str:
        """清理文件名中的非法字符"""
        return re.sub(r'[\\/*?:"<>|]', "", filename).strip()

    def extract_profiles(self, max_scrolls=50):
        logging.info(f"\n{'='*60}\n🕵️ 核心身份画像提取引擎启动 (联系人选择界面版)\n{'='*60}")

        no_new_contacts_streak = 0
        MAX_STREAK = 3

        for _ in range(max_scrolls):
            visible_elements = []
            new_elements_found = False

            # 1. 直接扫描所有联系人头像节点 (这是该界面最高效的定位方式)
            for elem in self.d(resourceId="com.whatsapp:id/contactpicker_row_photo"):
                if not elem.exists:
                    continue
                try:
                    # 获取头像上的隐藏描述文字 (真实联系人会有名字，系统按钮则是空的)
                    desc = elem.info.get('contentDescription', '')
                    
                    if desc and desc not in self.visited_contacts:
                        visible_elements.append((desc, elem))
                        new_elements_found = True
                except Exception:
                    continue

            if not new_elements_found:
                no_new_contacts_streak += 1
                if no_new_contacts_streak >= MAX_STREAK:
                    logging.info("\n✅ 已到达联系人列表底部，全量画像提取结束。")
                    break
            else:
                no_new_contacts_streak = 0

            # 2. 依次处理屏幕上的新联系人
            for contact_desc, elem in visible_elements:
                if contact_desc in self.visited_contacts:
                    continue

                logging.info(f"👉 锁定目标: [{contact_desc}]")
                self.visited_contacts.add(contact_desc)

                try:
                    # [动作 1] 狠狠地点这个头像 (100% 触发悬浮卡片)
                    elem.click()
                    time.sleep(1.2)

                    # 检查是否成功弹出悬浮卡片 (寻找 Info 按钮)
                    info_btn = self.d(resourceId="com.whatsapp:id/info_btn")
                    if not info_btn.exists:
                        # 兜底防错
                        self.d.press("back")
                        time.sleep(1)
                        continue

                    # [动作 2] 点击 Info 按钮，穿透进入详细资料页
                    info_btn.click()
                    time.sleep(1.5)

                    # [动作 3] 提取核心身份数据
                    title_elem = self.d(resourceId="com.whatsapp:id/contact_title")
                    subtitle_elem = self.d(resourceId="com.whatsapp:id/contact_subtitle")

                    if title_elem.exists:
                        actual_name = title_elem.get_text(timeout=2)
                        phone_number = subtitle_elem.get_text(timeout=1) if subtitle_elem.exists else "无号码(可能是群组/企业号)"
                        
                        logging.info(f"   🎯 提取成功 | 名称: {actual_name} | 号码: {phone_number}")

                        # [动作 4] 实施截图取证
                        safe_name = self.sanitize_filename(actual_name)
                        safe_phone = self.sanitize_filename(phone_number)
                        timestamp = int(time.time())
                        screenshot_name = f"{safe_name}_{safe_phone}_{timestamp}.jpg"
                        screenshot_path = os.path.join(self.screenshot_dir, screenshot_name)
                        
                        # 等待界面稳定
                        time.sleep(0.3)
                        self.d.screenshot(screenshot_path)
                        logging.info(f"   📸 证据已固化: {screenshot_name}")

                        # 落盘到 JSON
                        profile_data = {
                            "list_desc": contact_desc,
                            "actual_name": actual_name,
                            "phone_number": phone_number,
                            "screenshot_file": screenshot_name
                        }
                        self.profiles.append(profile_data)
                        
                        with open(self.output_json, 'w', encoding='utf-8') as f:
                            json.dump(self.profiles, f, ensure_ascii=False, indent=4)

                    # [动作 5] 战术撤退
                    self.d.press("back") # 退回悬浮卡片或列表
                    time.sleep(1.0)
                    
                    # 如果悬浮卡片还在，再按一次返回键彻底退回列表
                    if self.d(resourceId="com.whatsapp:id/info_btn").exists:
                        self.d.press("back")
                        time.sleep(0.8)

                except Exception as e:
                    logging.error(f"   ❌ 处理 [{contact_desc}] 时发生异常: {e}")
                    self.d.press("back")
                    time.sleep(1)

            # 3. 滑动获取新批次
            logging.info("⬇️ 列表向下滑动获取新目标...")
            self.d.swipe(0.5, 0.8, 0.5, 0.3, duration=0.5)
            time.sleep(1.5)

        logging.info(f"\n{'='*60}\n🎉 身份画像数据库构建完成！\n{'='*60}")

        return True  # ✅ 返回 True 表示脚本执行成功


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    extractor = WhatsAppProfileExtractor()
    extractor.extract_profiles()


if __name__ == "__main__":
    main()