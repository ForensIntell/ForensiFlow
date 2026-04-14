#!/usr/bin/env python3
"""
MobiAgent 端到端执行脚本

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
from runner.forensiflow.devices.android import AndroidDevice

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EndToEndExecutor:
    """端到端执行器"""

    def __init__(
        self,
        device,
        api_key: str,
        model: str = "qwen3.5-27b",
        data_dir: str = "./data",
        threshold: float = 0.75,
        device_serial: str = None
    ):
        """
        初始化端到端执行器

        Args:
            device: Android 设备对象
            api_key: Qwen API 密钥
            model: LLM 模型名称
            data_dir: 数据目录
            threshold: 调度器选择阈值
            device_serial: 设备序列号（用于应用提取）
        """
        self.device = device
        self.api_key = api_key
        self.model = model
        self.data_dir = data_dir
        self.threshold = threshold
        self.device_serial = device_serial

    def _extract_apps(self):
        """步骤 1a：提取设备应用信息（ADB + Google Play）"""
        logger.info("="*80)
        logger.info("📱 步骤 1/3：提取设备应用信息")
        logger.info("="*80)

        extract_cmd = [
            sys.executable,
            str(Path(__file__).parent / "runner" / "forensiflow" / "devices" / "extract_and_query_apps.py"),
            "--third-party",
            "--delay", "1.5"
        ]

        if self.device_serial:
            extract_cmd.extend(["--device", self.device_serial])

        try:
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
            model=self.model,
            data_dir=self.data_dir
        )

        plan = planner.create_forensic_plan(
            case_background=case_background,
            forensic_goals=forensic_goals
        )

        # 保存规划
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.data_dir) / "forensic_plans"
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
        specific_task_index: Optional[int] = None
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
            model=self.model,
            threshold=self.threshold
        )

        summary = executor.execute_plan(
            plan_file=plan_file,
            specific_app=specific_app,
            specific_task_index=specific_task_index
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

    def run_end_to_end(
        self,
        case_background: str = "",
        forensic_goals: str = "",
        specific_app: str = None,
        specific_task_index: Optional[int] = None
    ):
        """端到端执行：提取应用 → 生成规划 → 执行规划"""
        logger.info("="*80)
        logger.info("🎯 MobiAgent 端到端取证执行")
        logger.info("="*80)
        logger.info("")

        # 默认值
        if not case_background:
            case_background = "需要对移动设备进行取证分析"
        if not forensic_goals:
            forensic_goals = "提取设备上所有应用的相关数据，包括联系人列表、聊天记录、账户信息等"

        # 步骤 1/3：提取应用信息
        self._extract_apps()

        # 步骤 2/3：生成规划
        plan_file = self._generate_plan(case_background, forensic_goals)

        # 步骤 3/3：执行规划
        summary = self.run_forensic_plan(
            plan_file=plan_file,
            specific_app=specific_app,
            specific_task_index=specific_task_index
        )

        logger.info("")
        logger.info("="*80)
        logger.info("🎉 端到端执行完成！")
        logger.info("="*80)

        return summary



def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="MobiAgent 端到端执行脚本",
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
  python run_end_to_end.py --model qwen3.5-27b
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
        default="qwen3.5-27b",
        help="LLM 模型名称（默认：qwen3.5-27b）"
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="调度器选择阈值（默认：0.75）"
    )

    args = parser.parse_args()

    # 从文件读取 case 和 goals
    if args.case_file:
        with open(args.case_file, 'r', encoding='utf-8') as f:
            args.case = f.read().strip()
    if args.goals_file:
        with open(args.goals_file, 'r', encoding='utf-8') as f:
            args.goals = f.read().strip()

    # 检查 API 密钥
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        logger.error("❌ 未找到 QWEN_API_KEY 环境变量")
        logger.error("   请在 .env 文件中设置: QWEN_API_KEY=your-key")
        sys.exit(1)

    # 初始化设备
    logger.info("🔧 初始化设备...")
    device = AndroidDevice(adb_endpoint=args.device_serial)
    logger.info("✓ 设备已连接\n")

    try:
        # 如果提供了规划文件，直接执行
        if args.plan:
            from run_forensic_plan import ForensicTaskExecutor

            logger.info(f"📄 使用已有规划文件: {args.plan}")
            logger.info("")

            executor = ForensicTaskExecutor(
                device=device,
                api_key=api_key,
                model=args.model,
                threshold=args.threshold
            )

            summary = executor.execute_plan(
                plan_file=args.plan,
                specific_app=args.app,
                specific_task_index=args.task_index
            )

        # 否则，运行端到端流程
        else:
            executor = EndToEndExecutor(
                device=device,
                api_key=api_key,
                model=args.model,
                threshold=args.threshold,
                device_serial=args.device_serial
            )

            summary = executor.run_end_to_end(
                case_background=args.case or "",
                forensic_goals=args.goals or "",
                specific_app=args.app,
                specific_task_index=args.task_index
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
