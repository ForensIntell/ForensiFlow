"""
取证脚本注册表

定义脚本名称与实际脚本代码的映射关系
"""

import json
import logging
import re
import subprocess
import sys
import time
from typing import Dict, Callable, Optional, List
from pathlib import Path


class ScriptRegistry:
    """取证脚本注册表"""

    LAST_EXECUTION_RESULT: Optional[Dict] = None

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
    def get_dynamic_script_info(cls, script_name: str) -> Optional[Dict]:
        """Look up generated script metadata written by the new scheduler."""
        for registry_path in cls._dynamic_registry_paths():
            if not registry_path.exists():
                continue
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8-sig", errors="replace"))
            except Exception as exc:
                logging.warning(f"⚠️ 动态脚本注册表读取失败 {registry_path}: {exc}")
                continue
            if not isinstance(registry, dict):
                continue
            info = registry.get(script_name)
            if isinstance(info, dict):
                return cls._with_local_dynamic_paths(info)
            info = cls._find_dynamic_script_by_alias(registry, script_name)
            if isinstance(info, dict):
                resolved_name = info.get("script_name") or script_name
                logging.info(f"🔁 动态脚本别名匹配: {script_name} -> {resolved_name}")
                return cls._with_local_dynamic_paths(info)
        return None

    @classmethod
    def _find_dynamic_script_by_alias(cls, registry: Dict, script_name: str) -> Optional[Dict]:
        target = cls._normalize_script_lookup_text(script_name)
        if not target:
            return None
        best_info = None
        best_score = 0
        for key, info in registry.items():
            if not isinstance(info, dict):
                continue
            candidates = [
                key,
                info.get("script_name", ""),
                info.get("task", ""),
                info.get("app", ""),
            ]
            for candidate in candidates:
                score = cls._script_lookup_score(target, cls._normalize_script_lookup_text(candidate))
                if score > best_score:
                    best_score = score
                    best_info = info
        return best_info if best_score >= 3 else None

    @staticmethod
    def _normalize_script_lookup_text(value: str) -> str:
        text = str(value or "").casefold()
        for token in [
            "动态脚本",
            "script",
            "gmail",
            "whatsapp",
            "提取",
            "调用",
            "脚本",
            "信息",
            "列表",
            "界面",
            "全量",
            "inbox",
            "full",
            "extraction",
        ]:
            text = text.replace(token, " ")
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", text).strip()

    @staticmethod
    def _script_lookup_score(left: str, right: str) -> int:
        if not left or not right:
            return 0
        if left == right or left in right or right in left:
            return max(len(left.split()), len(right.split()), 3)
        left_tokens = {token for token in left.split() if len(token) > 1}
        right_tokens = {token for token in right.split() if len(token) > 1}
        return len(left_tokens & right_tokens)

    @classmethod
    def _with_local_dynamic_paths(cls, info: Dict) -> Dict:
        """Prefer the current checkout's archived script when registries contain old absolute paths."""
        normalized = dict(info)
        repo_root = Path(__file__).parent.parent.parent.parent
        generated_dir = repo_root / "runner" / "forensiflow" / "scripts" / "generated"
        script_path = Path(str(normalized.get("script_path") or ""))
        local_script = generated_dir / script_path.name if script_path.name else None
        if local_script and local_script.exists():
            normalized["script_path"] = str(local_script.resolve())
        index_path = Path(str(normalized.get("script_index_path") or ""))
        if local_script:
            local_index = local_script.with_suffix(".index.json")
            if local_index.exists() or not index_path.exists():
                normalized["script_index_path"] = str(local_index.resolve())
        reuse_log_raw = str(normalized.get("reuse_log_dir") or "")
        if not reuse_log_raw or reuse_log_raw.startswith("<REPO_ROOT>"):
            safe_name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(normalized.get("script_name") or "dynamic_script")).strip("_")
            normalized["reuse_log_dir"] = str((repo_root / "data" / "script_reuse_logs" / safe_name).resolve())
        return normalized

    @classmethod
    def _dynamic_registry_paths(cls) -> List[Path]:
        repo_root = Path(__file__).parent.parent.parent.parent
        return [
            repo_root / "runner" / "forensiflow" / "scripts" / "generated" / "registry.json",
            repo_root / "data" / "generated_script_registry.json",
        ]

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
        cls.LAST_EXECUTION_RESULT = None
        dynamic_info = cls.get_dynamic_script_info(script_name)
        if dynamic_info:
            return cls.execute_dynamic_script(script_name, dynamic_info, device=device, **kwargs)

        script_info = cls.get_script_info(script_name)

        if not script_info:
            logging.error(f"❌ 未找到脚本: {script_name}")
            logging.info(f"💡 可用脚本: {', '.join(cls.SCRIPTS.keys())}")
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": False,
                "error": "script not found",
            }
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
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": bool(result),
                "script_type": "builtin",
                "app": script_info.get("app", ""),
                "module": module_name,
                "class": class_name,
                "method": method_name,
            }
            return result

        except Exception as e:
            logging.error(f"❌ 脚本执行失败: {e}")
            import traceback
            traceback.print_exc()
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": False,
                "script_type": "builtin",
                "error": str(e),
            }
            return False

    @classmethod
    def execute_dynamic_script(cls, script_name: str, script_info: Dict, device, **kwargs) -> bool:
        """Execute a generated standalone Python script registered by xin_an_sai."""
        script_path = Path(script_info.get("script_path", ""))
        if not script_path.exists():
            logging.error(f"❌ 动态脚本不存在: {script_path}")
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": False,
                "script_type": "dynamic",
                "script_path": str(script_path),
                "error": "dynamic script missing",
            }
            return False

        logging.info(f"🔧 执行动态生成脚本: {script_name}")
        logging.info(f"   - 路径: {script_path}")
        logging.info(f"   - 来源: {script_info.get('source_run_dir', '')}")

        env = dict(**__import__("os").environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        repo_root = Path(__file__).parent.parent.parent.parent
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(repo_root) if not existing_pythonpath else f"{repo_root}:{existing_pythonpath}"

        log_dir = Path(script_info.get("reuse_log_dir") or Path(script_info.get("source_run_dir", ".")) / "reuse_logs")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        run_dir = log_dir / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "context").mkdir(parents=True, exist_ok=True)
        device_serial = cls._resolve_device_serial(device, script_info)
        env["FORENSIFLOW_AGENT_WORKSPACE"] = str(run_dir)
        env["FORENSIFLOW_DEVICE_SERIAL"] = device_serial
        env["FORENSIFLOW_TARGET"] = str(script_info.get("task") or "")
        env["FORENSIFLOW_APP_PACKAGE"] = str(script_info.get("package_name") or "")
        runnable_script = cls._prepare_dynamic_script_instance(script_path, run_dir, device_serial=device_serial)

        try:
            process = subprocess.run(
                [sys.executable, "-u", str(runnable_script)],
                cwd=str(run_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=int(kwargs.get("timeout_seconds", script_info.get("timeout_seconds", 180))),
                check=False,
            )
        except subprocess.TimeoutExpired:
            logging.error(f"❌ 动态脚本执行超时: {script_name}")
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": False,
                "script_type": "dynamic",
                "script_path": str(script_path),
                "run_dir": str(run_dir),
                "stdout_path": str(run_dir / "stdout.txt"),
                "stderr_path": str(run_dir / "stderr.txt"),
                "error": "dynamic script timeout",
            }
            return False
        except Exception as exc:
            logging.error(f"❌ 动态脚本执行异常: {exc}")
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": False,
                "script_type": "dynamic",
                "script_path": str(script_path),
                "run_dir": str(run_dir),
                "stdout_path": str(run_dir / "stdout.txt"),
                "stderr_path": str(run_dir / "stderr.txt"),
                "error": str(exc),
            }
            return False

        (run_dir / "stdout.txt").write_text(process.stdout or "", encoding="utf-8")
        (run_dir / "stderr.txt").write_text(process.stderr or "", encoding="utf-8")

        if process.returncode != 0:
            logging.error(f"❌ 动态脚本执行失败，return_code={process.returncode}")
            if process.stderr:
                logging.error(process.stderr[-2000:])
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": False,
                "script_type": "dynamic",
                "script_path": str(script_path),
                "runnable_script": str(runnable_script),
                "run_dir": str(run_dir),
                "returncode": process.returncode,
                "stdout_path": str(run_dir / "stdout.txt"),
                "stderr_path": str(run_dir / "stderr.txt"),
                "error": "dynamic script returned non-zero",
            }
            return False
        output_check = cls._dynamic_script_outputs_ok(run_dir, script_info=script_info)
        if not output_check.get("ok"):
            logging.error(f"❌ 动态脚本未产出可复用记录: {output_check.get('error')}")
            cls.LAST_EXECUTION_RESULT = {
                "script_name": script_name,
                "ok": False,
                "script_type": "dynamic",
                "script_path": str(script_path),
                "runnable_script": str(runnable_script),
                "run_dir": str(run_dir),
                "returncode": process.returncode,
                "stdout_path": str(run_dir / "stdout.txt"),
                "stderr_path": str(run_dir / "stderr.txt"),
                "error": output_check.get("error", "dynamic script output check failed"),
            }
            return False

        logging.info(f"✅ 动态脚本执行完成: {script_name}")
        logging.info(f"   - 复用结果目录: {run_dir}")
        logging.info(f"   - 记录数: {output_check.get('records_count')}")
        cls.LAST_EXECUTION_RESULT = {
            "script_name": script_name,
            "ok": True,
            "script_type": "dynamic",
            "script_path": str(script_path),
            "runnable_script": str(runnable_script),
            "run_dir": str(run_dir),
            "returncode": process.returncode,
            "records_count": output_check.get("records_count", 0),
            "records_path": output_check.get("records_path", ""),
            "records_debug_path": str(run_dir / "records_debug.json") if (run_dir / "records_debug.json").exists() else "",
            "run_state_path": str(run_dir / "run_state.json") if (run_dir / "run_state.json").exists() else "",
            "stdout_path": str(run_dir / "stdout.txt"),
            "stderr_path": str(run_dir / "stderr.txt"),
        }
        return True

    @classmethod
    def get_last_execution_result(cls) -> Optional[Dict]:
        return dict(cls.LAST_EXECUTION_RESULT) if isinstance(cls.LAST_EXECUTION_RESULT, dict) else None

    @classmethod
    def _dynamic_script_outputs_ok(cls, run_dir: Path, script_info: Optional[Dict] = None) -> Dict:
        record_candidates = [run_dir / "records.json", run_dir / "page_records.json"]
        records_count = 0
        records_path = None
        for path in record_candidates:
            if not path.exists():
                continue
            records_path = path
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                return {"ok": False, "error": f"{path.name} parse error: {exc}"}
            records = payload.get("records") if isinstance(payload, dict) else payload
            if isinstance(records, list):
                records_count = len(records)
            break
        if records_path is None:
            return {"ok": False, "error": "records.json/page_records.json missing"}
        if records_count <= 0:
            return {"ok": False, "error": f"{records_path.name} has no records"}
        if cls._requires_records_debug(script_info):
            debug_path = run_dir / "records_debug.json"
            if not debug_path.exists():
                return {"ok": False, "error": "records_debug.json missing for Codex generated script"}
            try:
                debug_payload = json.loads(debug_path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                return {"ok": False, "error": f"records_debug.json parse error: {exc}"}
            debug_records = debug_payload.get("records") if isinstance(debug_payload, dict) else debug_payload
            if not isinstance(debug_records, list):
                return {"ok": False, "error": "records_debug.json is not a list or records object"}
            if len(debug_records) != records_count:
                return {
                    "ok": False,
                    "error": f"records_debug count {len(debug_records)} does not match records count {records_count}",
                }
        state_path = run_dir / "run_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                return {"ok": False, "error": f"run_state.json parse error: {exc}"}
            if isinstance(state, dict):
                status = str(state.get("status") or "")
                errors = state.get("errors")
                if status and status not in {"completed", "terminal_complete", "child_terminal_complete", "done"}:
                    return {"ok": False, "error": f"run_state status is {status!r}"}
                if errors:
                    return {"ok": False, "error": f"run_state errors: {errors}"}
        return {"ok": True, "records_count": records_count, "records_path": str(records_path)}

    @classmethod
    def _requires_records_debug(cls, script_info: Optional[Dict]) -> bool:
        if not isinstance(script_info, dict):
            return False
        script_type = str(script_info.get("type") or "")
        legacy_type = str(script_info.get("legacy_type") or "")
        return "codex_mobile_agent_generated_script" in {script_type, legacy_type}

    @classmethod
    def _resolve_device_serial(cls, device, script_info: Dict) -> str:
        for attr in ("device_serial", "device_id", "adb_endpoint"):
            value = getattr(device, attr, "")
            if value:
                return str(value)
        return str(script_info.get("device_serial") or "")

    @classmethod
    def _prepare_dynamic_script_instance(cls, source_script: Path, run_dir: Path, device_serial: str = "") -> Path:
        """Copy a generated script and redirect its common output path constants."""
        run_dir.mkdir(parents=True, exist_ok=True)
        script_text = source_script.read_text(encoding="utf-8", errors="replace")
        replacements = {
            "BASE_DIR": str(run_dir),
            "STATE_PATH": str(run_dir / "run_state.json"),
            "RECORDS_PATH": str(run_dir / "page_records.json"),
            "REPORT_PATH": str(run_dir / "page_report.txt"),
        }
        if device_serial:
            replacements["DEVICE_SERIAL"] = device_serial
        for name, value in replacements.items():
            pattern = rf"^({name}\s*=\s*)(?:r)?[\"'].*?[\"']\s*$"
            replacement = rf"\1{json.dumps(value, ensure_ascii=False)}"
            script_text = re.sub(pattern, replacement, script_text, flags=re.MULTILINE)
        runnable_script = run_dir / source_script.name
        runnable_script.write_text(script_text, encoding="utf-8")
        return runnable_script
