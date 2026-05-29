#!/usr/bin/env python3
"""
ForensiFlow 端到端执行脚本

功能：
1. 以取证规划层为入口，接收 case 和 goals 输入
2. 自动生成取证任务规划
3. 自动执行生成的取证任务规划
4. 完成从案件分析到任务执行的全流程

使用示例：
    # 基本使用（交互式输入）
    python run_end_to_end.py

    # 直接指定 case 和 goals
    python run_end_to_end.py --case "案件背景" --goals "取证目标1\\n取证目标2"

    # 从文件读取
    python run_end_to_end.py --case-file case.txt --goals-file goals.txt

    # 只执行特定应用
    python run_end_to_end.py --case "..." --goals "..." --app "WhatsApp Messenger"

    # 只执行特定任务
    python run_end_to_end.py --case "..." --goals "..." --task-index 0

    # 使用已有规划文件（跳过规划步骤）
    python run_end_to_end.py --plan data/forensic_plans/forensic_plan_XXX.json
"""

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys
import json
import argparse
import logging
import subprocess
from pathlib import Path
from typing import Optional

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from runner.forensiflow.core.forensic_planner import ForensicPlanner
from runner.forensiflow.core.logging_utils import configure_logging, demo_log_enabled
from runner.forensiflow.core.config import get_llm_config
from runner.forensiflow.devices.android import AndroidDevice
from tools.device_serial import resolve_device_serial

configure_logging()
logger = logging.getLogger(__name__)


def _read_input_text_file(file_path: str) -> str:
    """Read user-provided case/goals file, with examples/ fallback for old commands."""
    path = Path(file_path)
    if not path.exists() and not path.is_absolute():
        fallback = Path(__file__).parent / "examples" / path.name
        if fallback.exists():
            logger.info("输入文件 %s 不存在，改用示例文件: %s", file_path, fallback)
            path = fallback
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()


class EndToEndExecutor:
    """端到端执行器"""

    def __init__(
        self,
        device,
        api_key: str,
        model: str = None,
        api_base: str = None,
        data_dir: str = "./data",
        threshold: float = 0.75,
        device_serial: str = None
    ):
        """
        初始化端到端执行器

        Args:
            device: Android 设备对象
            api_key: LLM API 密钥
            model: LLM 模型名称
            api_base: LLM API endpoint
            data_dir: 数据目录
            threshold: 调度器选择阈值
            device_serial: 设备序列号（用于应用提取）
        """
        llm_config = get_llm_config(api_key=api_key, api_base=api_base, model=model)
        self.device = device
        self.api_key = llm_config.api_key
        self.api_base = llm_config.api_base
        self.model = llm_config.model
        self.threshold = threshold
        self.device_serial = device_serial or getattr(device, 'device_serial', 'unknown_device')

        # 按设备序列号隔离数据目录
        self.data_dir = str(Path(data_dir) / "devices" / self.device_serial)
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

    def _extract_apps(self):
        """步骤 1a：提取设备应用信息（ADB + Google Play）"""
        logger.info("="*80)
        logger.info("📱 步骤 1/3：提取设备应用信息")
        logger.info("="*80)

        app_info_dir = str(Path(self.data_dir) / "app_info")

        extract_cmd = [
            sys.executable,
            str(Path(__file__).parent / "runner" / "forensiflow" / "devices" / "extract_and_query_apps.py"),
            "--third-party",
            "--delay", "1.5",
            "--output-dir", app_info_dir
        ]

        if self.device_serial:
            extract_cmd.extend(["--device", self.device_serial])

        try:
            if demo_log_enabled():
                result = subprocess.run(
                    extract_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            else:
                result = subprocess.run(extract_cmd, capture_output=False)
            if result.returncode != 0:
                logger.warning("⚠️ 应用提取失败，继续使用现有数据...")
        except Exception as e:
            logger.warning(f"⚠️ 应用提取异常: {e}")

    def _generate_plan(self, case_background: str, forensic_goals: str) -> str:
        """步骤 1b：LLM 生成取证规划"""
        logger.info("")
        logger.info("="*80)
        logger.info("🤖 步骤 2/3：生成取证任务规划")
        logger.info("="*80)

        logger.info(f"📝 案件背景: {case_background}")
        logger.info(f"🎯 取证目标: {forensic_goals}")

        planner = ForensicPlanner(
            api_key=self.api_key,
            base_url=self.api_base,
            model=self.model,
            data_dir=self.data_dir
        )

        plan = planner.create_forensic_plan(
            case_background=case_background,
            forensic_goals=forensic_goals
        )

        # 保存规划到设备专属 plans/ 目录
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.data_dir) / "plans"
        output_dir.mkdir(parents=True, exist_ok=True)

        plan_file = output_dir / f"forensic_plan_{timestamp}.json"
        with open(plan_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        logger.info("")
        logger.info("="*80)
        logger.info(f"✅ 取证任务规划生成完成")
        logger.info(f"📄 规划文件: {plan_file}")
        logger.info("="*80)

        return str(plan_file)

    def run_forensic_plan(
        self,
        plan_file: str,
        specific_app: str = None,
        specific_task_index: Optional[int] = None,
        *,
        max_apps: Optional[int] = None,
        max_tasks_per_app: Optional[int] = None,
        selection_only: bool = False,
    ):
        """步骤 2：执行取证任务规划"""
        logger.info("")
        logger.info("="*80)
        logger.info("🚀 步骤 3/3：执行取证任务规划")
        logger.info("="*80)

        from run_forensic_plan import ForensicTaskExecutor

        executor = ForensicTaskExecutor(
            device=self.device,
            api_key=self.api_key,
            api_base=self.api_base,
            model=self.model,
            threshold=self.threshold,
            data_dir=self.data_dir
        )

        summary = executor.execute_plan(
            plan_file=plan_file,
            specific_app=specific_app,
            specific_task_index=specific_task_index,
            max_apps=max_apps,
            max_tasks_per_app=max_tasks_per_app,
            selection_only=selection_only,
        )

        logger.info("")
        logger.info("="*80)
        logger.info("✅ 取证任务执行完成")
        logger.info(f"总任务数: {summary['total_tasks']}")
        logger.info(f"已完成: {summary['completed_tasks']}")
        logger.info(f"失败: {summary['failed_tasks']}")
        logger.info(f"成功率: {summary['completed_tasks']/summary['total_tasks']*100 if summary['total_tasks'] > 0 else 0:.1f}%")
        logger.info("="*80)

        return summary

    def _save_device_info(self):
        """保存设备元信息"""
        info_path = Path(self.data_dir) / "device_info.json"

        # 如果已存在则跳过（设备信息不变）
        if info_path.exists():
            logger.info(f"📋 设备信息已存在: {info_path}")
            return

        try:
            device_info = self.device.get_device_info()
            with open(info_path, 'w', encoding='utf-8') as f:
                json.dump(device_info, f, ensure_ascii=False, indent=2)
            logger.info(f"📋 设备信息已保存: {info_path}")
            logger.info(f"   序列号: {device_info.get('serial', 'N/A')}")
            logger.info(f"   型号: {device_info.get('model', 'N/A')}")
            logger.info(f"   Android: {device_info.get('android_version', 'N/A')}")
        except Exception as e:
            logger.warning(f"⚠️ 保存设备信息失败: {e}")

    def run_end_to_end(
        self,
        case_background: str = "",
        forensic_goals: str = "",
        specific_app: str = None,
        specific_task_index: Optional[int] = None,
        *,
        max_apps: Optional[int] = None,
        max_tasks_per_app: Optional[int] = None,
        selection_only: bool = False,
        skip_app_extract: bool = False,
    ):
        """端到端执行：提取应用 → 生成规划 → 执行规划"""
        logger.info("="*80)
        logger.info("🎯 ForensiFlow 端到端取证执行")
        logger.info(f"📁 设备数据目录: {self.data_dir}")
        logger.info("="*80)
        logger.info("")

        # 保存设备元信息
        self._save_device_info()

        # 默认值
        if not case_background:
            case_background = "需要对移动设备进行取证分析"
        if not forensic_goals:
            forensic_goals = "提取设备上所有应用的相关数据，包括联系人列表、聊天记录、账户信息等"

        # 步骤 1/3：提取应用信息
        if skip_app_extract:
            logger.info("⏭️  跳过应用提取，使用现有应用映射/缓存")
        else:
            self._extract_apps()

        # 步骤 2/3：生成规划
        plan_file = self._generate_plan(case_background, forensic_goals)

        # 步骤 3/3：执行规划
        summary = self.run_forensic_plan(
            plan_file=plan_file,
            specific_app=specific_app,
            specific_task_index=specific_task_index,
            max_apps=max_apps,
            max_tasks_per_app=max_tasks_per_app,
            selection_only=selection_only,
        )

        logger.info("")
        logger.info("="*80)
        logger.info("🎉 端到端执行完成！")
        logger.info("="*80)

        return summary



def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="ForensiFlow 端到端执行脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法：
  # 基本使用（全面取证）
  python run_end_to_end.py

  # 指定案件背景和取证目标
  python run_end_to_end.py --case "涉嫌诈骗案" --goals "提取 WhatsApp 和微信的聊天记录"

  # 从文件读取案件背景和取证目标
  python run_end_to_end.py --case-file case.txt --goals-file goals.txt

  # 只执行特定应用
  python run_end_to_end.py --app "WhatsApp Messenger"

  # 只执行特定任务
  python run_end_to_end.py --task-index 0

  # 指定设备
  python run_end_to_end.py --device-serial emulator-5554

  # 指定模型
  python run_end_to_end.py --model your-model-name
        """
    )

    parser.add_argument(
        "--case",
        type=str,
        help="案件背景（例如：涉嫌诈骗案，需要提取聊天记录）"
    )

    parser.add_argument(
        "--case-file",
        type=str,
        help="从文件读取案件背景"
    )

    parser.add_argument(
        "--goals",
        type=str,
        help="取证目标（例如：提取 WhatsApp 联系人\\n提取微信聊天记录）"
    )

    parser.add_argument(
        "--goals-file",
        type=str,
        help="从文件读取取证目标"
    )

    parser.add_argument(
        "--plan",
        type=str,
        help="直接执行已有的规划文件（跳过规划步骤）"
    )

    parser.add_argument(
        "--app",
        type=str,
        help="只执行指定应用的任务"
    )

    parser.add_argument(
        "--task-index",
        type=int,
        help="只执行指定索引的任务"
    )

    parser.add_argument(
        "--device-serial",
        type=str,
        default=None,
        help="设备序列号（多设备时使用）"
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM 模型名称（默认读取 FORENSIFLOW/MOMI/MIMO/LLM 配置，兼容 PAGE_AGENT_MOBILE 旧变量）"
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="调度器选择阈值（默认：0.75）"
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="只跑规划和路由选择，不真正执行手机任务。"
    )
    parser.add_argument(
        "--max-apps",
        type=int,
        default=None,
        help="限制本次最多处理多少个应用。"
    )
    parser.add_argument(
        "--max-tasks-per-app",
        type=int,
        default=None,
        help="限制每个应用最多处理多少个任务。"
    )
    parser.add_argument(
        "--skip-app-extract",
        action="store_true",
        help="跳过设备应用重新提取，使用已有应用映射/缓存。"
    )

    args = parser.parse_args()

    # 从文件读取 case 和 goals
    if args.case_file:
        args.case = _read_input_text_file(args.case_file)
    if args.goals_file:
        args.goals = _read_input_text_file(args.goals_file)

    # 检查并统一 LLM 配置。优先使用 FORENSIFLOW/MOMI/MIMO/LLM，兼容 PAGE_AGENT_MOBILE/QWEN/YUNWU 旧名称。
    try:
        llm_config = get_llm_config(model=args.model)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # 初始化设备
    logger.info("🔧 初始化设备...")
    resolved_serial = resolve_device_serial(args.device_serial or "", required=True)
    device = AndroidDevice(adb_endpoint=resolved_serial)
    logger.info(f"✓ 设备已连接 (序列号: {device.device_serial})\n")

    # 构建设备数据目录
    device_data_dir = str(Path("./data") / "devices" / device.device_serial)

    try:
        # 如果提供了规划文件，直接执行
        if args.plan:
            from run_forensic_plan import ForensicTaskExecutor

            logger.info(f"📄 使用已有规划文件: {args.plan}")
            logger.info(f"📁 设备数据目录: {device_data_dir}")
            logger.info("")

            executor = ForensicTaskExecutor(
                device=device,
                api_key=llm_config.api_key,
                api_base=llm_config.api_base,
                model=llm_config.model,
                threshold=args.threshold,
                data_dir=device_data_dir
            )

            summary = executor.execute_plan(
                plan_file=args.plan,
                specific_app=args.app,
                specific_task_index=args.task_index,
                max_apps=args.max_apps,
                max_tasks_per_app=args.max_tasks_per_app,
                selection_only=args.selection_only,
            )

        # 否则，运行端到端流程
        else:
            executor = EndToEndExecutor(
                device=device,
                api_key=llm_config.api_key,
                api_base=llm_config.api_base,
                model=llm_config.model,
                threshold=args.threshold,
                device_serial=device.device_serial
            )

            summary = executor.run_end_to_end(
                case_background=args.case or "",
                forensic_goals=args.goals or "",
                specific_app=args.app,
                specific_task_index=args.task_index,
                max_apps=args.max_apps,
                max_tasks_per_app=args.max_tasks_per_app,
                selection_only=args.selection_only,
                skip_app_extract=args.skip_app_extract,
            )

        # 退出码
        sys.exit(0 if summary['failed_tasks'] == 0 else 1)

    except KeyboardInterrupt:
        logger.info("\n\n⚠️  用户中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\n❌ 执行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
