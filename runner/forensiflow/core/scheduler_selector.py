"""
调度器选择器 - 基于任务相似度智能选择调度器

功能：
1. 使用 RAG 模板匹配器计算任务相似度
2. 根据阈值选择新调度器或老调度器
3. 提供统一的选择接口

架构位置：
    规划层 → 调度器选择器（中转站） → 新/老调度器
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SchedulerSelectionResult:
    """调度器选择结果"""
    scheduler_type: str  # "new" or "old"
    template: Optional[Dict[str, Any]]  # 如果是 old 调度器，返回匹配的模板
    similarity_score: float  # 相似度分数
    reason: str  # 选择原因


class SchedulerSelector:
    """
    调度器选择器（中转站）

    职责：
    1. 接收规划层的任务（应用名 + 任务描述）
    2. 使用 BGE 进行 RAG 模板匹配
    3. 根据相似度阈值选择调度器
    4. 返回选择结果和匹配的模板（如果有）
    """

    def __init__(
        self,
        rag_matcher,
        threshold: float = 0.75
    ):
        """
        初始化调度器选择器

        Args:
            rag_matcher: RAG 模板匹配器实例 (RAGTemplateMatcher)
            threshold: 相似度阈值（默认 0.75）
                      - >= threshold: 使用老调度器（复用历史经验）
                      - < threshold: 使用新调度器（探索新任务）
        """
        self.rag_matcher = rag_matcher
        self.threshold = threshold

        logger.info(f"📊 调度器选择器初始化完成")
        logger.info(f"   相似度阈值: {self.threshold}")
        logger.info(f"   选择逻辑: >= {self.threshold} → 老调度器, < {self.threshold} → 新调度器")

    def select_scheduler(
        self,
        app_name: str,
        task_description: str,
        package_name: str = "",
        top_k: int = 1
    ) -> SchedulerSelectionResult:
        """
        选择调度器

        Args:
            app_name: 应用名称
            task_description: 任务描述
            top_k: 返回前 k 个最相似的模板

        Returns:
            SchedulerSelectionResult
        """
        logger.info(f"🔍 分析任务: [{app_name}] {task_description}")

        # 使用 RAG 检索相似模板
        try:
            matches = self.rag_matcher.search(
                app=app_name,
                task=task_description,
                package_name=package_name,
                top_k=top_k
            )

            if matches and matches[0].score >= self.threshold:
                # 高相似度 → 使用老调度器
                best_match = matches[0]
                logger.info(f"✅ 匹配到历史模板（相似度: {best_match.score:.3f} >= {self.threshold}）")
                logger.info(f"   模板任务: {best_match.template.get('task', 'Unknown')}")

                return SchedulerSelectionResult(
                    scheduler_type="old",
                    template=best_match.template,
                    similarity_score=best_match.score,
                    reason=f"相似度 {best_match.score:.3f} >= 阈值 {self.threshold}，使用老调度器复用历史经验"
                )
            else:
                # 低相似度 → 使用新调度器
                best_score = matches[0].score if matches else 0.0
                logger.info(f"🆕 未找到足够相似的历史模板（最佳相似度: {best_score:.3f} < {self.threshold}）")
                logger.info(f"   使用新调度器进行任务探索和经验积累")

                return SchedulerSelectionResult(
                    scheduler_type="new",
                    template=None,
                    similarity_score=best_score,
                    reason=f"相似度 {best_score:.3f} < 阈值 {self.threshold}，使用新调度器探索"
                )

        except Exception as e:
            logger.warning(f"⚠️ RAG 检索失败: {e}")
            logger.info(f"   降级使用新调度器")

            return SchedulerSelectionResult(
                scheduler_type="new",
                template=None,
                similarity_score=0.0,
                reason=f"RAG 检索异常，降级使用新调度器"
            )

    def is_reusable_template(self, template: Optional[Dict[str, Any]]) -> bool:
        if not template:
            return False
        try:
            from tools.template_library import is_runnable_reuse_template
            return is_runnable_reuse_template(template)
        except Exception:
            steps = template.get("steps")
            if not isinstance(steps, list) or not steps:
                return False
            first = steps[0] if isinstance(steps[0], dict) else {}
            return str(first.get("action") or "").lower() == "launch" and bool(template.get("package_name"))
