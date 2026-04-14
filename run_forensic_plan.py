#!/usr/bin/env python3
"""
取证任务执行器 - 智能调度中转站

功能：
1. 从任务规划层读取取证任务规划
2. 使用调度器选择器基于 BGE 语义匹配选择调度器：
   - 相似度 >= 阈值：使用老调度器（复用历史经验）
   - 相似度 < 阈值：使用新调度器（探索新任务）
3. 执行取证任务并保存结果

使用示例：
    python run_forensic_plan.py --plan data/forensic_plan_20260410_123456.json
    python run_forensic_plan.py --plan plan.json --app WeChat --task-index 0
"""

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Any

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from runner.forensiflow.core.scheduler_llm import SimpleLLMScheduler
from runner.forensiflow.core.scheduler_vt import TaskSchedulerVT
from runner.forensiflow.core.scheduler_selector import SchedulerSelector
from runner.forensiflow.core.rag_template_matcher import RAGTemplateMatcher
from runner.forensiflow.devices.android import AndroidDevice

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ForensicTaskExecutor:
    """取证任务执行器 - 智能调度中转站"""

    def __init__(
        self,
        device,
        api_key: str,
        model: str = "qwen3.5-27b",
        threshold: float = 0.75
    ):
        """
        初始化执行器

        Args:
            device: Android 设备对象
            api_key: Qwen API 密钥
            model: LLM 模型名称
            threshold: 调度器选择相似度阈值（默认 0.75）
        """
        self.device = device
        self.api_key = api_key
        self.model = model
        self.threshold = threshold

        logger.info("="*80)
        logger.info("🔧 初始化智能调度中转站")
        logger.info("="*80)

        # 初始化新调度器
        logger.info("🔄 初始化新调度器（探索模式）...")
        self.new_scheduler = SimpleLLMScheduler(
            device=device,
            api_key=api_key,
            model=model
        )
        logger.info("   ✓ 新调度器初始化完成")

        # 初始化老调度器
        logger.info("🔄 初始化老调度器（复用模式）...")
        self.old_scheduler = TaskSchedulerVT(
            device=device,
            planner_api_key=api_key,
            planner_model=model,
            data_dir="./data"
        )
        logger.info("   ✓ 老调度器初始化完成")

        # 初始化 RAG 匹配器（用于调度器选择）
        logger.info("🔄 初始化 RAG 模板匹配器...")
        self.rag_matcher = RAGTemplateMatcher(
            model_path=None,  # 使用默认 BGE 模型路径
            templates_dir=None  # 使用默认模板目录
        )
        logger.info("   ✓ RAG 模板匹配器初始化完成")

        # 初始化调度器选择器（中转站核心）
        logger.info("🔄 初始化调度器选择器（中转站）...")
        self.scheduler_selector = SchedulerSelector(
            rag_matcher=self.rag_matcher,
            threshold=threshold
        )
        logger.info(f"   ✓ 调度器选择器初始化完成（阈值: {threshold}）")

        logger.info("="*80)
        logger.info("✅ 智能调度中转站初始化完成\n")

    def execute_plan(
        self,
        plan_file: str,
        specific_app: str = None,
        specific_task_index: int = None
    ) -> Dict[str, Any]:
        """
        执行取证任务规划

        Args:
            plan_file: 任务规划文件路径
            specific_app: 指定执行某个应用（可选）
            specific_task_index: 指定执行某个任务索引（可选）

        Returns:
            执行结果汇总
        """
        # 加载任务规划
        with open(plan_file, 'r', encoding='utf-8') as f:
            plan = json.load(f)

        logger.info("="*80)
        logger.info("📋 取证任务规划")
        logger.info("="*80)
        logger.info(f"案件分析: {plan.get('case_analysis_summary', '')}")
        logger.info(f"应用数量: {len(plan.get('forensic_plan', []))}")
        logger.info("="*80 + "\n")

        # 执行结果汇总
        execution_summary = {
            "plan_file": plan_file,
            "case_analysis": plan.get('case_analysis_summary', ''),
            "apps_executed": [],
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0
        }

        # 遍历每个应用的任务
        for app_plan in plan.get('forensic_plan', []):
            app_name = app_plan.get('app_name', '')
            package_name = app_plan.get('package_name', '')
            tasks = app_plan.get('tasks', [])

            # 应用过滤
            if specific_app and app_name != specific_app:
                logger.info(f"⏭️  跳过应用: {app_name}")
                continue

            logger.info(f"\n{'='*80}")
            logger.info(f"📱 应用: {app_name} ({package_name})")
            logger.info(f"📋 任务数: {len(tasks)}")
            logger.info(f"{'='*80}\n")

            app_results = {
                "app_name": app_name,
                "package_name": package_name,
                "tasks_executed": [],
                "tasks_completed": [],
                "tasks_failed": []
            }

            # 执行每个任务
            for task_idx, task in enumerate(tasks):
                task_level = task.get('task_level', 0)
                task_type = task.get('task_type', '')
                task_description = task.get('task_description', '')
                target_objects = task.get('target_objects', [])
                constraint = task.get('constraint', '')

                # 任务过滤
                if specific_task_index is not None and task_idx != specific_task_index:
                    logger.info(f"⏭️  跳过任务 #{task_idx}: {task_description}")
                    continue

                logger.info(f"\n{'─'*80}")
                logger.info(f"📝 任务 #{task_idx}: [Level {task_level}] {task_description}")
                if target_objects:
                    logger.info(f"   对象: {', '.join(target_objects)}")
                if constraint:
                    logger.info(f"   约束: {constraint}")
                logger.info(f"{'─'*80}\n")

                # 使用调度器选择器选择合适的调度器
                logger.info(f"🔍 调度器选择分析...")
                selection_result = self.scheduler_selector.select_scheduler(
                    app_name=app_name,
                    task_description=task_description
                )

                logger.info(f"📊 选择结果: {selection_result.reason}")
                logger.info(f"   相似度分数: {selection_result.similarity_score:.3f}")
                logger.info(f"   使用调度器: {'老调度器（复用模式）' if selection_result.scheduler_type == 'old' else '新调度器（探索模式）'}\n")

                # 根据选择结果调用对应调度器
                try:
                    if selection_result.scheduler_type == "old":
                        # 使用老调度器执行
                        result = self.old_scheduler.run_task(
                            app=app_name,
                            old_task=task_description,
                            task=task_description,
                            max_steps=20,
                            use_abstract_task=True,
                            rag_template=selection_result.template  # 传递匹配的模板
                        )
                    else:
                        # 使用新调度器执行
                        result = self.new_scheduler.run_forensic_task(
                            package_name=package_name,
                            app_name=app_name,
                            task_description=task_description,
                            constraint=constraint,
                            max_steps=20
                        )

                    # 记录结果
                    task_result = {
                        "task_index": task_idx,
                        "task_level": task_level,
                        "task_type": task_type,
                        "task_description": task_description,
                        "completed": result.get('completed', False),
                        "total_steps": result.get('total_steps', 0),
                        "data_dir": result.get('data_dir', ''),
                        "error": result.get('error', ''),
                        "scheduler_used": selection_result.scheduler_type,  # 记录使用的调度器
                        "similarity_score": selection_result.similarity_score  # 记录相似度
                    }

                    app_results['tasks_executed'].append(task_result)

                    if result.get('completed'):
                        app_results['tasks_completed'].append(task_idx)
                        execution_summary['completed_tasks'] += 1
                        logger.info(f"✅ 任务 #{task_idx} 完成")
                    else:
                        app_results['tasks_failed'].append(task_idx)
                        execution_summary['failed_tasks'] += 1
                        logger.warning(f"⚠️  任务 #{task_idx} 未完成")

                except Exception as e:
                    logger.error(f"❌ 任务 #{task_idx} 执行异常: {e}")
                    import traceback
                    traceback.print_exc()

                    app_results['tasks_failed'].append(task_idx)
                    execution_summary['failed_tasks'] += 1

                    app_results['tasks_executed'].append({
                        "task_index": task_idx,
                        "task_level": task_level,
                        "task_type": task_type,
                        "task_description": task_description,
                        "completed": False,
                        "error": str(e)
                    })

            execution_summary['apps_executed'].append(app_results)
            execution_summary['total_tasks'] += len(tasks)

        # 保存执行汇总
        self._save_execution_summary(execution_summary, plan_file)

        return execution_summary

    def _save_execution_summary(self, summary: Dict[str, Any], plan_file: str):
        """保存执行汇总"""
        plan_path = Path(plan_file)
        summary_file = plan_path.parent / f"{plan_path.stem}_execution_summary.json"

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        logger.info(f"\n💾 执行汇总已保存: {summary_file}")

        # 打印统计
        logger.info(f"\n{'='*80}")
        logger.info("📊 执行统计")
        logger.info(f"{'='*80}")
        logger.info(f"总任务数: {summary['total_tasks']}")
        logger.info(f"已完成: {summary['completed_tasks']}")
        logger.info(f"失败: {summary['failed_tasks']}")
        logger.info(f"成功率: {summary['completed_tasks']/summary['total_tasks']*100 if summary['total_tasks'] > 0 else 0:.1f}%")
        logger.info(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="取证任务执行器 - 连接任务规划层与新调度器"
    )

    parser.add_argument(
        "--plan",
        type=str,
        required=True,
        help="任务规划 JSON 文件路径"
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
        help="LLM 模型名称"
    )

    args = parser.parse_args()

    # 检查 API 密钥
    api_key = os.getenv("QWEN_API_KEY")
    if not api_key:
        logger.error("❌ 未找到 QWEN_API_KEY 环境变量")
        logger.error("   请在 .env 文件中设置: QWEN_API_KEY=your-key")
        sys.exit(1)

    # 检查规划文件
    if not Path(args.plan).exists():
        logger.error(f"❌ 规划文件不存在: {args.plan}")
        sys.exit(1)

    # 初始化设备
    logger.info(f"🔧 初始化设备...")
    device = AndroidDevice(adb_endpoint=args.device_serial)

    # 创建执行器
    executor = ForensicTaskExecutor(
        device=device,
        api_key=api_key,
        model=args.model
    )

    # 执行任务规划
    executor.execute_plan(
        plan_file=args.plan,
        specific_app=args.app,
        specific_task_index=args.task_index
    )


if __name__ == "__main__":
    main()
