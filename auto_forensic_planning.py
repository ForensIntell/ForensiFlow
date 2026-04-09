#!/usr/bin/env python3
"""
自动取证规划工具

一键完成：
1. 从设备提取第三方应用包名
2. 查询应用信息（包名、名称、分类）
3. 基于案件背景和目标自动生成取证任务规划

使用示例：
    # 交互式输入
    python auto_forensic_planning.py

    # 直接提供参数
    python auto_forensic_planning.py --device-id <DEVICE> --api-key <API_KEY>

    # 从文件读取案件信息
    python auto_forensic_planning.py --case-file case.txt --goals-file goals.txt
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# 加载.env文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果没有安装python-dotenv，手动读取.env文件
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from runner.forensiflow.core import ForensicPlanner
from runner.forensiflow.devices import extract_and_query_apps


def load_text_from_file(file_path: str) -> str:
    """从文件加载文本内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        logging.error(f"❌ 读取文件失败 {file_path}: {e}")
        sys.exit(1)


def save_plan_to_files(
    plan: dict,
    output_dir: str,
    format: str = "both"
):
    """
    保存取证规划到多种格式

    Args:
        plan: 取证规划字典
        output_dir: 输出目录
        format: 输出格式 (json/txt/both)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = __import__('datetime').datetime.now().strftime("%Y%m%d_%H%M%S")

    # 保存JSON格式
    if format in ["json", "both"]:
        json_file = output_path / f"forensic_plan_{timestamp}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        logging.info(f"✅ JSON格式已保存: {json_file}")

    # 保存TXT格式
    if format in ["txt", "both"]:
        txt_file = output_path / f"forensic_plan_{timestamp}.txt"

        lines = []
        lines.append("=" * 80)
        lines.append("📋 移动设备取证任务规划")
        lines.append("=" * 80)
        lines.append(f"\n🕐 生成时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # 案件分析摘要
        lines.append("\n🔍 案件分析摘要")
        lines.append("-" * 80)
        lines.append(plan.get("case_analysis_summary", "未生成摘要"))
        lines.append("")

        # 取证任务规划
        lines.append("📱 取证任务规划")
        lines.append("-" * 80)

        for i, app_plan in enumerate(plan.get("forensic_plan", []), 1):
            lines.append(f"\n{i}. {app_plan.get('app_name', '未知应用')} ({app_plan.get('package_name', 'unknown')})")

            tasks = app_plan.get("tasks", [])
            for j, task in enumerate(tasks, 1):
                lines.append(f"   {j}. {task}")

        # 统计信息
        total_apps = len(plan.get("forensic_plan", []))
        total_tasks = sum(len(app['tasks']) for app in plan.get("forensic_plan", []))
        lines.append(f"\n" + "=" * 80)
        lines.append(f"📊 统计: {total_apps} 个应用, {total_tasks} 个任务")
        lines.append("=" * 80)

        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logging.info(f"✅ TXT格式已保存: {txt_file}")

    # 返回主文件路径
    if format == "json":
        return str(json_file)
    elif format == "txt":
        return str(txt_file)
    else:
        return str(json_file)


def print_plan_summary(plan: dict):
    """打印取证规划摘要"""
    print("\n" + "=" * 80)
    print("📋 移动设备取证任务规划")
    print("=" * 80 + "\n")

    print("🔍 案件分析摘要")
    print("-" * 80)
    print(plan.get("case_analysis_summary", "未生成摘要"))
    print()

    print("📱 取证任务规划")
    print("-" * 80)

    for i, app_plan in enumerate(plan.get("forensic_plan", []), 1):
        print(f"\n{i}. {app_plan.get('app_name', '未知应用')} ({app_plan.get('package_name', 'unknown')})")

        tasks = app_plan.get("tasks", [])
        for j, task in enumerate(tasks, 1):
            print(f"   {j}. {task}")

    total_apps = len(plan.get("forensic_plan", []))
    total_tasks = sum(len(app['tasks']) for app in plan.get("forensic_plan", []))

    print("\n" + "=" * 80)
    print(f"📊 统计: {total_apps} 个应用, {total_tasks} 个任务")
    print("=" * 80 + "\n")


def interactive_input() -> tuple:
    """交互式输入案件信息"""
    print("\n" + "=" * 80)
    print("📝 取证规划 - 交互式输入模式")
    print("=" * 80 + "\n")

    print("请输入案件背景描述（输入完成后按 Ctrl+D 或 Ctrl+Z 结束）:")
    print("提示: 包含案件类型、时间、涉及范围、主要特征等\n")

    lines = []
    try:
        while True:
            line = input()
            lines.append(line)
    except EOFError:
        pass

    case_background = '\n'.join(lines).strip()

    print("\n" + "-" * 80)
    print("请输入取证目标（每行一个目标，输入完成后按 Ctrl+D 或 Ctrl+Z 结束）:")
    print("提示: 要提取的具体证据类型、要查明的关键事实等\n")

    lines = []
    try:
        while True:
            line = input()
            lines.append(line)
    except EOFError:
        pass

    forensic_goals = '\n'.join(lines).strip()

    return case_background, forensic_goals


def main():
    parser = argparse.ArgumentParser(
        description="自动取证规划工具 - 一键生成取证任务规划",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 交互式输入
  %(prog)s

  # 指定设备ID和API密钥
  %(prog)s --device-id <DEVICE> --api-key <API_KEY>

  # 从文件读取案件信息
  %(prog)s --case-file case.txt --goals-file goals.txt

  # 直接提供案件信息
  %(prog)s --case "案件背景..." --goals "目标1\\n目标2"

  # 跳过应用提取，使用已有映射
  %(prog)s --skip-app-extract --mapping-file ./data/app_info/package_name_mapping.txt

  # 只提取应用信息，不生成规划
  %(prog)s --extract-only
        """
    )

    # 设备和应用提取选项
    parser.add_argument(
        "--device-id",
        type=str,
        help="指定设备ID（多设备时使用）"
    )
    parser.add_argument(
        "--third-party",
        action="store_true",
        default=True,
        help="只提取第三方应用（默认开启）"
    )
    parser.add_argument(
        "--skip-app-extract",
        action="store_true",
        help="跳过应用提取步骤，使用已有映射文件"
    )
    parser.add_argument(
        "--mapping-file",
        type=str,
        help="应用映射文件路径（跳过提取时使用）"
    )

    # 案件信息选项
    parser.add_argument(
        "--case-file",
        type=str,
        help="从文件读取案件背景"
    )
    parser.add_argument(
        "--goals-file",
        type=str,
        help="从文件读取取证目标"
    )
    parser.add_argument(
        "--case",
        type=str,
        help="直接指定案件背景"
    )
    parser.add_argument(
        "--goals",
        type=str,
        help="直接指定取证目标（可使用\\n换行）"
    )

    # LLM配置
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,  # 默认从环境变量读取
        help="Qwen API密钥（默认从环境变量QWEN_API_KEY读取）"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="qwen3.5-plus",
        help="使用的模型名称（默认: qwen-plus）"
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="LLM温度参数（默认: 0.7）"
    )

    # 输出选项
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./data/forensic_plans",
        help="输出目录（默认: ./data/forensic_plans）"
    )
    parser.add_argument(
        "--output-format",
        type=str,
        choices=["json", "txt", "both"],
        default="both",
        help="输出格式（默认: both）"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="安静模式，减少输出"
    )

    # 其他选项
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="只提取应用信息，不生成取证规划"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="应用查询延迟（秒），默认1.5秒"
    )

    args = parser.parse_args()

    # 配置日志
    log_level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # 检查API密钥（仅在非提取模式下验证）
    if not args.extract_only and not args.skip_app_extract:
        # 尝试从环境变量读取API key
        env_api_key = os.getenv("QWEN_API_KEY", "")

        # 如果环境变量也没有，且命令行也没指定，才报错
        if not args.api_key and not env_api_key:
            print("❌ 错误: 需要提供 Qwen API 密钥")
            print("   在.env文件中设置: QWEN_API_KEY=your-key")
            print("   或设置环境变量: export QWEN_API_KEY='your-key'")
            print("   或使用参数: --api-key your-key")
            sys.exit(1)

    print("\n" + "=" * 80)
    print("🔍 自动取证规划工具")
    print("=" * 80)

    # 步骤1: 提取应用信息
    if not args.skip_app_extract:
        print("\n📱 步骤 1/3: 提取设备应用信息")
        print("-" * 80)

        extract_cmd = [
            sys.executable,
            "runner/forensiflow/devices/extract_and_query_apps.py",
            "--third-party" if args.third_party else "",
            "--delay", str(args.delay)
        ]

        if args.device_id:
            extract_cmd.extend(["--device", args.device_id])

        import subprocess
        try:
            result = subprocess.run(extract_cmd, capture_output=False)
            if result.returncode != 0:
                print("\n⚠️ 应用提取失败，但继续使用现有数据...")
        except Exception as e:
            logging.warning(f"⚠️ 应用提取异常: {e}")
            print("\n继续使用现有应用数据...\n")
    else:
        print("\n⏭️  跳过应用提取，使用现有映射文件")

    # 如果只是提取模式，直接退出
    if args.extract_only:
        print("\n✅ 应用信息提取完成")
        print("📁 应用信息保存位置: ./data/app_info/")
        return

    # 步骤2: 获取案件信息
    print("\n📝 步骤 2/3: 获取案件信息")
    print("-" * 80)

    if args.case_file:
        case_background = load_text_from_file(args.case_file)
        print(f"✅ 从文件加载案件背景: {args.case_file}")
    elif args.case:
        case_background = args.case
        print("✅ 使用命令行提供的案件背景")
    else:
        case_background, _ = interactive_input()

    if args.goals_file:
        forensic_goals = load_text_from_file(args.goals_file)
        print(f"✅ 从文件加载取证目标: {args.goals_file}")
    elif args.goals:
        forensic_goals = args.goals.replace('\\n', '\n')
        print("✅ 使用命令行提供的取证目标")
    else:
        _, forensic_goals = interactive_input()

    # 步骤3: 生成取证规划
    print("\n🤖 步骤 3/3: 生成取证任务规划")
    print("-" * 80)

    # 初始化规划器（API key从环境变量读取，或使用参数指定的值）
    planner_kwargs = {
        "model": args.model,
        "temperature": args.temperature,
        "data_dir": "./data"
    }

    # 如果通过参数指定了API key，则使用指定的值
    if args.api_key:
        planner_kwargs["api_key"] = args.api_key

    planner = ForensicPlanner(**planner_kwargs)

    try:
        # 生成规划
        plan = planner.create_forensic_plan(
            case_background=case_background,
            forensic_goals=forensic_goals,
            app_mapping_file=args.mapping_file
        )

        # 打印规划
        if not args.quiet:
            print_plan_summary(plan)

        # 保存规划
        output_file = save_plan_to_files(
            plan,
            args.output_dir,
            args.output_format
        )

        print("=" * 80)
        print(f"✅ 取证规划生成完成！")
        print(f"📁 输出文件: {output_file}")
        print("=" * 80 + "\n")

    except Exception as e:
        logging.error(f"❌ 生成取证规划失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
