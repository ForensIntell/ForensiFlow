"""
取证脚本注册表

定义脚本名称与实际脚本代码的映射关系
"""

import logging
from typing import Dict, Callable, Optional
from pathlib import Path


class ScriptRegistry:
    """取证脚本注册表"""

    # 脚本映射表：脚本名称 -> 脚本信息
    SCRIPTS = {
        # WhatsApp 脚本
        "调用当前账号的身份信息脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_profile_info",
            "description": "提取WhatsApp当前账号的身份信息"
        },
        "调用隐私和安全设置状态脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_privacy_settings",
            "description": "提取WhatsApp的隐私和安全设置状态"
        },
        "调用云端备份配置和状态脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_backup_config",
            "description": "提取WhatsApp云端备份配置和状态"
        },
        "调用已关联的设备和活跃状态脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_linked_devices",
            "description": "提取WhatsApp已关联的设备和活跃状态"
        },
        "调用所有的通话记录列表及详情脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_Communicate",
            "class": "WhatsAppCallLogExtractor",
            "method": "extract_call_logs",
            "description": "提取WhatsApp中所有的通话记录列表及详情"
        },
        "调用联系人列表脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_informaition",
            "class": "WhatsAppProfileExtractor",
            "method": "extract_profiles",
            "description": "提取WhatsApp联系人列表"
        },
        "调用所有联系人聊天记录脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "browse_and_extract",
            "description": "提取WhatsApp所有联系人信息及聊天记录"
        },
        "调用与特定联系人的完整聊天记录脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_chat_with_contact",
            "description": "提取WhatsApp中与特定联系人的完整聊天记录"
        },
        "调用与特定联系人聊天中的媒体、链接和文档清单脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_chat_media_links_docs",
            "description": "提取WhatsApp与特定联系人聊天中的媒体、链接和文档清单"
        },
        "调用特定联系人的详细信息脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_informaition",
            "class": "WhatsAppProfileExtractor",
            "method": "extract_profiles",
            "description": "提取WhatsApp特定联系人的详细信息"
        },
        "调用所有收藏的消息脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_starred_messages",
            "description": "提取WhatsApp中所有收藏的消息"
        },
        "调用归档的聊天列表及记录脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_archived_chats",
            "description": "提取WhatsApp中归档的聊天列表及记录"
        },
        "调用所有群组的信息和聊天记录脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_all_groups",
            "description": "提取WhatsApp所有群组的信息和聊天记录"
        },
        "调用特定群组的信息和聊天记录脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_group_info",
            "description": "提取WhatsApp特定群组的信息和聊天记录"
        },
        "调用社群(Communities)架构及子群组脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_communities",
            "description": "提取WhatsApp社群(Communities)架构及子群组"
        },
        "调用关注的频道及记录脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_channels",
            "description": "提取WhatsApp关注的频道及记录"
        },
        "调用动态隐私设置脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_status_privacy",
            "description": "提取WhatsApp动态隐私设置"
        },
        "调用用户发布的动态信息脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_user_status",
            "description": "提取WhatsApp用户发布的动态信息"
        },
        "调用已封锁的联系人名单(黑名单)脚本提取": {
            "app": "WhatsApp",
            "module": "whatsapp_raw_extractor",
            "class": "WhatsAppUniversalExtractor",
            "method": "extract_blocked_contacts",
            "description": "提取WhatsApp已封锁的联系人名单(黑名单)"
        },
    }

    @classmethod
    def get_script_info(cls, script_name: str) -> Optional[Dict]:
        """
        获取脚本信息

        Args:
            script_name: 脚本名称

        Returns:
            脚本信息字典，如果不存在则返回 None
        """
        return cls.SCRIPTS.get(script_name)

    @classmethod
    def list_scripts(cls, app: Optional[str] = None) -> Dict[str, str]:
        """
        列出所有可用脚本

        Args:
            app: 应用名称过滤（可选）

        Returns:
            脚本名称到描述的映射
        """
        if app:
            return {
                name: info["description"]
                for name, info in cls.SCRIPTS.items()
                if info["app"].lower() == app.lower()
            }
        else:
            return {
                name: info["description"]
                for name, info in cls.SCRIPTS.items()
            }

    @classmethod
    def execute_script(cls, script_name: str, device, **kwargs) -> bool:
        """
        执行指定的取证脚本

        Args:
            script_name: 脚本名称
            device: 设备对象
            **kwargs: 额外参数

        Returns:
            是否执行成功
        """
        script_info = cls.get_script_info(script_name)

        if not script_info:
            logging.error(f"❌ 未找到脚本: {script_name}")
            logging.info(f"💡 可用脚本: {', '.join(cls.SCRIPTS.keys())}")
            return False

        try:
            # 动态导入模块
            module_name = script_info["module"]
            if module_name.endswith(".py"):
                # 如果是独立的Python脚本
                import importlib.util
                import sys

                # 构建脚本路径
                script_path = Path(__file__).parent.parent / "scripts" / module_name
                spec = importlib.util.spec_from_file_location(module_name[:-3], script_path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name[:-3]] = module
                spec.loader.exec_module(module)
            else:
                # 如果是包模块
                module = __import__(f"runner.forensiflow.scripts.{module_name}", fromlist=[module_name])

            # 获取类
            class_name = script_info["class"]
            ScriptClass = getattr(module, class_name)

            # 创建实例
            device_serial = getattr(device, 'device_id', '')
            script_instance = ScriptClass(device_serial=device_serial)

            # 调用方法
            method_name = script_info["method"]
            method = getattr(script_instance, method_name)

            logging.info(f"🔧 执行脚本: {script_name}")
            logging.info(f"   - 应用: {script_info['app']}")
            logging.info(f"   - 模块: {module_name}")
            logging.info(f"   - 类: {class_name}")
            logging.info(f"   - 方法: {method_name}")

            # 执行方法
            result = method(**kwargs)

            logging.info(f"✅ 脚本执行完成")
            return result

        except Exception as e:
            logging.error(f"❌ 脚本执行失败: {e}")
            import traceback
            traceback.print_exc()
            return False
