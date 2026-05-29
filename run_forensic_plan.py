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
from typing import Dict, Any, Optional

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from runner.forensiflow.core.codex_agent_scheduler import CodexAgentScheduler
from runner.forensiflow.core.scheduler_vt import TaskSchedulerVT
from runner.forensiflow.core.scheduler_selector import SchedulerSelector
from runner.forensiflow.core.rag_template_matcher import RAGTemplateMatcher
from runner.forensiflow.core.logging_utils import configure_logging
from runner.forensiflow.core.config import get_config, get_llm_config
from runner.forensiflow.devices.android import AndroidDevice
from tools.device_serial import resolve_device_serial
from tools.template_library import is_runnable_reuse_template

configure_logging()
logger = logging.getLogger(__name__)


class ForensicTaskExecutor:
    """取证任务执行器 - 智能调度中转站"""

    def __init__(
        self,
        device,
        api_key: str,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        threshold: float = 0.75,
        data_dir: str = "./data"
    ):
        """
        初始化执行器

        Args:
            device: Android 设备对象
            api_key: LLM API 密钥
            model: LLM 模型名称
            api_base: LLM API endpoint
            threshold: 调度器选择相似度阈值（默认 0.75）
            data_dir: 数据目录（设备隔离目录，如 data/devices/{serial}/）
        """
        llm_config = get_llm_config(api_key=api_key, api_base=api_base, model=model)
        self.device = device
        self.api_key = llm_config.api_key
        self.api_base = llm_config.api_base
        self.model = llm_config.model
        self.threshold = threshold
        self.data_dir = data_dir
        self.new_scheduler = None
        self.old_scheduler = None

        logger.info("="*80)
        logger.info("🔧 初始化智能调度中转站")
        logger.info("="*80)

        # 初始化 RAG 匹配器（用于调度器选择）
        logger.info("🔄 初始化 RAG 模板匹配器...")
        app_config = get_config()
        self.rag_matcher = RAGTemplateMatcher(
            model_path=app_config.rag_model_path,
            templates_dir=app_config.rag_templates_dir,
            top_k=app_config.rag_top_k,
            device=app_config.rag_device,
        )
        logger.info(f"   - RAG 模板目录: {app_config.rag_templates_dir}")
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

    def _get_new_scheduler(self) -> CodexAgentScheduler:
        if self.new_scheduler is None:
            if self.device is None:
                raise RuntimeError("new scheduler requires a connected device")
            logger.info("🔄 初始化新调度器（ForensiFlow Codex Agent 探索模式）...")
            self.new_scheduler = CodexAgentScheduler(
                device=self.device,
                api_key=self.api_key,
                api_base=self.api_base,
                model=self.model,
                data_dir=self.data_dir,
            )
            logger.info("   ✓ ForensiFlow Codex Agent 新调度器初始化完成")
        return self.new_scheduler

    def _get_old_scheduler(self) -> TaskSchedulerVT:
        if self.old_scheduler is None:
            if self.device is None:
                raise RuntimeError("old scheduler requires a connected device")
            logger.info("🔄 初始化老调度器（复用模式）...")
            self.old_scheduler = TaskSchedulerVT(
                device=self.device,
                planner_api_key=self.api_key,
                planner_base_url=self.api_base,
                planner_model=self.model,
                data_dir=self.data_dir
            )
            logger.info("   ✓ 老调度器初始化完成")
        return self.old_scheduler

    def execute_plan(
        self,
        plan_file: str,
        specific_app: str = None,
        specific_task_index: int = None,
        *,
        max_apps: Optional[int] = None,
        max_tasks_per_app: Optional[int] = None,
        selection_only: bool = False,
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
        if selection_only:
            execution_summary["selection_only"] = True
            execution_summary["selected_routes"] = []

        # 遍历每个应用的任务
        apps_seen = 0
        for app_plan in plan.get('forensic_plan', []):
            if max_apps is not None and apps_seen >= max_apps:
                logger.info(f"⏭️  已达到 max_apps={max_apps}，停止后续应用执行")
                break
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
            apps_seen += 1

            # 执行每个任务
            tasks_seen = 0
            for task_idx, task in enumerate(tasks):
                if max_tasks_per_app is not None and tasks_seen >= max_tasks_per_app:
                    logger.info(f"⏭️  已达到 max_tasks_per_app={max_tasks_per_app}，停止本应用后续任务")
                    break
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
                    task_description=task_description,
                    package_name=package_name
                )

                logger.info(f"📊 选择结果: {selection_result.reason}")
                logger.info(f"   相似度分数: {selection_result.similarity_score:.3f}")
                logger.info(f"   使用调度器: {'老调度器（复用模式）' if selection_result.scheduler_type == 'old' else '新调度器（ForensiFlow Codex Agent 探索模式）'}\n")
                if selection_result.scheduler_type == "old" and not is_runnable_reuse_template(selection_result.template or {}):
                    logger.warning("⚠️ 匹配模板不可执行，降级为新调度器探索模式")
                    selection_result.scheduler_type = "new"
                    selection_result.template = None

                route_record = {
                    "app_name": app_name,
                    "package_name": package_name,
                    "task_index": task_idx,
                    "task_description": task_description,
                    "scheduler_type": selection_result.scheduler_type,
                    "similarity_score": selection_result.similarity_score,
                    "reason": selection_result.reason,
                    "template_task": (selection_result.template or {}).get("task", ""),
                    "template_script": ((selection_result.template or {}).get("script_generation") or {}).get("script_name", ""),
                }
                if selection_only:
                    execution_summary["selected_routes"].append(route_record)
                    app_results["tasks_executed"].append({
                        "task_index": task_idx,
                        "task_level": task_level,
                        "task_type": task_type,
                        "task_description": task_description,
                        "selected_scheduler": selection_result.scheduler_type,
                        "similarity_score": selection_result.similarity_score,
                        "selection_only": True,
                    })
                    tasks_seen += 1
                    continue

                # 根据选择结果调用对应调度器
                try:
                    if selection_result.scheduler_type == "old":
                        # 使用老调度器执行
                        result = self._get_old_scheduler().run_task(
                            app=app_name,
                            old_task=task_description,
                            task=task_description,
                            max_steps=20,
                            use_abstract_task=True,
                            rag_template=selection_result.template  # 传递匹配的模板
                        )
                    else:
                        # 使用新调度器执行
                        result = self._get_new_scheduler().run_forensic_task(
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
                        "navigation_completed": result.get('navigation_completed', result.get('completed', False)),
                        "script_generation": result.get('script_generation'),
                        "total_steps": result.get('total_steps', 0),
                        "data_dir": result.get('data_dir', ''),
                        "run_dir": result.get('run_dir', result.get('data_dir', '')),
                        "script_results": result.get('script_results', []),
                        "reuse_artifacts": result.get('reuse_artifacts'),
                        "last_run_state": result.get('last_run_state'),
                        "raw_result": result.get('raw_result'),
                        "error": result.get('error', ''),
                        "scheduler_used": selection_result.scheduler_type,  # 记录使用的调度器
                        "similarity_score": selection_result.similarity_score  # 记录相似度
                    }

                    app_results['tasks_executed'].append(task_result)
                    tasks_seen += 1

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
                    tasks_seen += 1

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
        default=None,
        help="LLM 模型名称（默认读取 MOMI/MIMO/LLM/FORENSIFLOW 配置，兼容 PAGE_AGENT_MOBILE 旧变量）"
    )
    parser.add_argument(
        "--selection-only",
        action="store_true",
        help="只做路由选择，不真正执行手机任务。"
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

    args = parser.parse_args()

    # 检查并统一 LLM 配置。优先使用 MOMI/MIMO/LLM/FORENSIFLOW 配置，兼容 PAGE_AGENT_MOBILE/QWEN/YUNWU 旧名称。
    try:
        llm_config = get_llm_config(model=args.model)
    except ValueError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # 检查规划文件
    if not Path(args.plan).exists():
        logger.error(f"❌ 规划文件不存在: {args.plan}")
        sys.exit(1)

    # 初始化设备
    logger.info(f"🔧 初始化设备...")
    resolved_serial = resolve_device_serial(args.device_serial or "", required=not args.selection_only)
    device = None
    if args.selection_only:
        logger.info("   ✓ selection-only 模式，未连接设备")
    else:
        device = AndroidDevice(adb_endpoint=resolved_serial)
        logger.info(f"   ✓ 设备已连接 (序列号: {device.device_serial})")

    # 构建设备数据目录
    device_data_dir = str(Path("./data") / "devices" / (device.device_serial if device else resolved_serial or "unknown_device"))

    # 创建执行器
    executor = ForensicTaskExecutor(
        device=device,
        api_key=llm_config.api_key,
        api_base=llm_config.api_base,
        model=llm_config.model,
        data_dir=device_data_dir
    )

    # 执行任务规划
    executor.execute_plan(
        plan_file=args.plan,
        specific_app=args.app,
        specific_task_index=args.task_index,
        max_apps=args.max_apps,
        max_tasks_per_app=args.max_tasks_per_app,
        selection_only=args.selection_only,
    )


if __name__ == "__main__":
    main()
