"""Logging helpers for normal and demo runs."""

import logging
import os
import warnings


DEMO_LOG_ENV = "MOBIAGENT_LOG_MODE"


class DemoLogFilter(logging.Filter):
    """Keep terminal output concise for demo recordings."""

    IMPORTANT_MARKERS = (
        "ForensiFlow",
        "端到端",
        "步骤 1/3",
        "步骤 2/3",
        "步骤 3/3",
        "生成取证",
        "规划文件",
        "执行取证",
        "取证任务规划",
        "📱 应用:",
        "任务 #",
        "使用调度器",
        "🔧 执行脚本",
        "CallScript",
        "脚本执行完成",
        "WhatsApp 聊天记录提取开始",
        "处理会话",
        "开始提取聊天记录",
        "已到达历史记录顶部",
        "数据已保存",
        "取证结束",
        "提取结果已保存",
        "任务执行完成",
        "任务执行结束",
        "执行统计",
        "总任务数",
        "已完成",
        "失败",
        "成功率",
    )

    NOISY_MARKERS = (
        "发送给 LLM",
        "LLM 规划响应",
        "LLM原始响应",
        "Prompt",
        "```json",
        '"reasoning"',
        "参考案例",
        "目标应用",
        "使用调度器选择器提供",
        "外部模板示例",
        "规划完成",
        "理由:",
        "UI JSON",
        "XML 已保存",
        "XML Matching",
        "VisionTasker detected",
        "截图已保存",
        "Dumping XML",
        "BGE-Large",
        "模型路径",
        "模板目录",
        "预计算",
        "RAG 检索",
        "Actions saved",
        "Reacts saved",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True

        message = record.getMessage()
        if any(marker in message for marker in self.NOISY_MARKERS):
            return False
        return any(marker in message for marker in self.IMPORTANT_MARKERS)


def demo_log_enabled() -> bool:
    return os.getenv(DEMO_LOG_ENV, "").strip().lower() in {"demo", "brief", "quiet", "1", "true"}


def configure_logging(level: int = logging.INFO, force: bool = True) -> None:
    """Configure root logging, optionally filtering to demo-friendly lines."""
    if demo_log_enabled():
        os.environ.setdefault("TQDM_DISABLE", "1")
        warnings.filterwarnings("ignore", message=".*TypedStorage is deprecated.*")

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=force,
    )

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.filters.clear()
        if demo_log_enabled():
            handler.addFilter(DemoLogFilter())
