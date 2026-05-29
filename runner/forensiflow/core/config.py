"""
ForensiFlow 统一配置管理模块

从环境变量和 .env 文件加载配置，避免硬编码 API Key
"""

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_MIMO_API_BASE = "https://your-openai-compatible-endpoint/v1"
DEFAULT_MIMO_MODEL = "your-model-name"


def _is_placeholder_secret(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return normalized.startswith(("your_", "your-", "changeme", "change_me"))


@dataclass(frozen=True)
class LLMConfig:
    """OpenAI-compatible LLM configuration shared by all model callers."""

    api_key: str
    api_base: str
    model: str


class Config:
    """统一配置管理类"""

    def __init__(self, env_file: Optional[str] = None):
        """
        初始化配置

        Args:
            env_file: .env 文件路径（默认为项目根目录下的 .env）
        """
        # 项目根目录
        self.project_root = Path(__file__).parent.parent.parent.parent

        # .env 文件路径
        if env_file is None:
            env_file = self.project_root / ".env"

        self.env_file = Path(env_file)

        # 加载 .env 文件。额外加载 .env.mimo，方便项目统一使用 Mimo/Momi 配置。
        self._load_env()
        mimo_env = self.project_root / ".env.mimo"
        if mimo_env.exists() and mimo_env != self.env_file:
            self._load_env_file(mimo_env)

    def _load_env(self):
        """加载 .env 文件"""
        if not self.env_file.exists():
            print(f"⚠️  警告：.env 文件不存在: {self.env_file}")
            print(f"💡 提示：请复制 .env.template 为 .env 并配置您的 API Key")
            return
        self._load_env_file(self.env_file)

    def _load_env_file(self, env_file: Path):
        """加载 KEY=VALUE 或 export KEY=VALUE 格式的环境文件。"""
        # 读取 .env 文件并设置环境变量
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过注释和空行
                if not line or line.startswith('#'):
                    continue

                if line.startswith("export "):
                    line = line[len("export "):].strip()

                # 解析 KEY=VALUE 格式
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    try:
                        parsed = shlex.split(value, posix=True)
                        if len(parsed) == 1:
                            value = parsed[0]
                    except ValueError:
                        value = value.strip().strip('"').strip("'")

                    # 如果环境变量尚未设置，则使用 .env 中的值
                    if key not in os.environ:
                        os.environ[key] = value

    # ==================== LLM API 配置 ====================
    def resolve_llm_config(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
    ) -> LLMConfig:
        """解析全项目统一的 Mimo/Momi OpenAI-compatible 配置。

        优先级：显式参数 > FORENSIFLOW/MOMI/MIMO/LLM 环境变量 >
        PAGE_AGENT_MOBILE 旧兼容环境变量 >
        旧 OPENAI/QWEN/YUNWU 兼容环境变量 > OpenAI-compatible 默认 endpoint/model。
        """
        resolved_key = (
            api_key
            or os.getenv("FORENSIFLOW_API_KEY")
            or os.getenv("FORENSIFLOW_LLM_API_KEY")
            or os.getenv("MOMI_API_KEY")
            or os.getenv("MIMO_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("PAGE_AGENT_MOBILE_API_KEY")
            or os.getenv("EXPERIMENTAL_AGENT_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("QWEN_API_KEY")
            or os.getenv("YUNWU_API_KEY")
            or ""
        )
        if not resolved_key or _is_placeholder_secret(resolved_key):
            raise ValueError(
                "❌ LLM API Key 未配置。\n"
                "   请设置 FORENSIFLOW_API_KEY/MOMI_API_KEY/MIMO_API_KEY/LLM_API_KEY，"
                "或使用 .env.mimo 中的兼容 API Key。"
            )

        resolved_base = (
            api_base
            or os.getenv("FORENSIFLOW_API_BASE")
            or os.getenv("FORENSIFLOW_LLM_API_BASE")
            or os.getenv("MOMI_API_BASE")
            or os.getenv("MIMO_API_BASE")
            or os.getenv("LLM_API_BASE")
            or os.getenv("PAGE_AGENT_MOBILE_API_BASE")
            or os.getenv("EXPERIMENTAL_AGENT_API_BASE")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("QWEN_API_URL")
            or os.getenv("YUNWU_API_URL")
            or DEFAULT_MIMO_API_BASE
        )
        resolved_model = (
            model
            or os.getenv("FORENSIFLOW_MODEL")
            or os.getenv("FORENSIFLOW_LLM_MODEL")
            or os.getenv("MOMI_MODEL")
            or os.getenv("MIMO_MODEL")
            or os.getenv("LLM_MODEL")
            or os.getenv("PAGE_AGENT_MOBILE_MODEL")
            or os.getenv("EXPERIMENTAL_AGENT_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_MIMO_MODEL
        )
        return LLMConfig(api_key=resolved_key, api_base=resolved_base, model=resolved_model)

    def configure_llm_environment(self, config: Optional[LLMConfig] = None) -> LLMConfig:
        """Expose the unified LLM config through legacy env names used by old modules."""
        resolved = config or self.resolve_llm_config()
        aliases = {
            "FORENSIFLOW_API_KEY": resolved.api_key,
            "FORENSIFLOW_LLM_API_KEY": resolved.api_key,
            "MOMI_API_KEY": resolved.api_key,
            "MIMO_API_KEY": resolved.api_key,
            "LLM_API_KEY": resolved.api_key,
            "PAGE_AGENT_MOBILE_API_KEY": resolved.api_key,
            "OPENAI_API_KEY": resolved.api_key,
            "QWEN_API_KEY": resolved.api_key,
            "YUNWU_API_KEY": resolved.api_key,
            "FORENSIFLOW_API_BASE": resolved.api_base,
            "FORENSIFLOW_LLM_API_BASE": resolved.api_base,
            "MOMI_API_BASE": resolved.api_base,
            "MIMO_API_BASE": resolved.api_base,
            "LLM_API_BASE": resolved.api_base,
            "PAGE_AGENT_MOBILE_API_BASE": resolved.api_base,
            "OPENAI_BASE_URL": resolved.api_base,
            "QWEN_API_URL": resolved.api_base,
            "YUNWU_API_URL": resolved.api_base,
            "FORENSIFLOW_MODEL": resolved.model,
            "FORENSIFLOW_LLM_MODEL": resolved.model,
            "MOMI_MODEL": resolved.model,
            "MIMO_MODEL": resolved.model,
            "LLM_MODEL": resolved.model,
            "PAGE_AGENT_MOBILE_MODEL": resolved.model,
            "OPENAI_MODEL": resolved.model,
            "QWEN_DEFAULT_MODEL": resolved.model,
        }
        for key, value in aliases.items():
            os.environ[key] = value
        return resolved

    @property
    def llm_api_key(self) -> str:
        """统一 LLM API Key。"""
        return self.resolve_llm_config().api_key

    @property
    def llm_api_base(self) -> str:
        """统一 LLM API endpoint。"""
        return self.resolve_llm_config().api_base

    @property
    def llm_model(self) -> str:
        """统一 LLM 默认模型。"""
        return self.resolve_llm_config().model

    @property
    def qwen_api_key(self) -> str:
        """兼容旧代码：返回统一 LLM API Key。"""
        return self.llm_api_key

    @property
    def chatglm_api_key(self) -> str:
        """获取 ChatGLM API Key"""
        api_key = os.getenv("CHATGLM_API_KEY")
        if not api_key or _is_placeholder_secret(api_key):
            raise ValueError(
                "❌ CHATGLM_API_KEY 未配置！\n"
                "   请在 .env 文件中设置 CHATGLM_API_KEY"
            )
        return api_key

    @property
    def qwen_api_url(self) -> str:
        """兼容旧代码：返回统一 LLM API endpoint。"""
        return self.llm_api_base

    @property
    def chatglm_api_url(self) -> str:
        """ChatGLM API 端点"""
        return os.getenv("CHATGLM_API_URL", "https://open.bigmodel.cn/api/paas/v4")

    @property
    def qwen_default_model(self) -> str:
        """兼容旧代码：返回统一 LLM 默认模型。"""
        return self.llm_model

    @property
    def chatglm_default_model(self) -> str:
        """ChatGLM 默认模型"""
        return os.getenv("CHATGLM_DEFAULT_MODEL", "glm-4-flash")

    # ==================== OCR API 配置 ====================
    @property
    def ocr_api_key(self) -> Optional[str]:
        """OCR API Key（可选）"""
        return os.getenv("OCR_API_KEY")

    @property
    def ocr_secret_key(self) -> Optional[str]:
        """OCR Secret Key（可选）"""
        return os.getenv("OCR_SECRET_KEY")

    # ==================== 其他配置 ====================
    @property
    def data_dir(self) -> str:
        """数据目录"""
        return os.getenv("DATA_DIR", "./data")

    @property
    def log_level(self) -> str:
        """日志级别"""
        return os.getenv("LOG_LEVEL", "INFO")

    # ==================== 语义匹配配置 ====================
    @property
    def semantic_matcher_enabled(self) -> bool:
        """是否启用语义匹配器"""
        return os.getenv("SEMANTIC_MATCHER_ENABLED", "true").lower() == "true"

    @property
    def semantic_matcher_model_path(self) -> str:
        """BGE 模型路径"""
        default_path = self.project_root / "external" / "models" / "bge-small-zh-v1.5"
        return os.getenv("SEMANTIC_MATCHER_MODEL_PATH", str(default_path))

    @property
    def semantic_matcher_threshold(self) -> float:
        """语义匹配阈值（0-1）"""
        try:
            return float(os.getenv("SEMANTIC_MATCHER_THRESHOLD", "0.75"))
        except ValueError:
            return 0.75

    @property
    def semantic_matcher_cache_size(self) -> int:
        """语义匹配缓存大小"""
        try:
            return int(os.getenv("SEMANTIC_MATCHER_CACHE_SIZE", "5"))
        except ValueError:
            return 5

    @property
    def semantic_matcher_device(self) -> str:
        """语义匹配运行设备"""
        return os.getenv("SEMANTIC_MATCHER_DEVICE", "cpu")

    # ==================== RAG 模板匹配配置 ====================
    @property
    def rag_enabled(self) -> bool:
        """是否启用 RAG 模板匹配"""
        return os.getenv("RAG_ENABLED", "true").lower() == "true"

    @property
    def rag_model_path(self) -> str:
        """RAG BGE 模型路径（bge-large-zh-v1.5）"""
        default_path = self.project_root / "external" / "models" / "bge-large-zh-v1.5"
        return os.getenv("RAG_MODEL_PATH", str(default_path))

    @property
    def rag_templates_dir(self) -> str:
        """RAG 模板目录"""
        default_path = self.project_root / "external" / "rag_templates"
        return os.getenv("RAG_TEMPLATES_DIR", str(default_path))

    @property
    def rag_threshold(self) -> float:
        """RAG 匹配阈值（0-1）"""
        try:
            return float(os.getenv("RAG_THRESHOLD", "0.75"))
        except ValueError:
            return 0.75

    @property
    def rag_top_k(self) -> int:
        """RAG 返回前 K 个模板"""
        try:
            return int(os.getenv("RAG_TOP_K", "3"))
        except ValueError:
            return 3

    @property
    def rag_device(self) -> str:
        """RAG 运行设备"""
        return os.getenv("RAG_DEVICE", "cpu")


# 全局配置实例（单例）
_config_instance = None


def get_config() -> Config:
    """获取全局配置实例（单例模式）"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


# 便捷函数
def get_qwen_api_key() -> str:
    """获取统一 LLM API Key（旧函数名兼容）。"""
    return get_config().qwen_api_key


def get_llm_config(
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    model: Optional[str] = None,
) -> LLMConfig:
    """获取统一 LLM 配置。"""
    config = get_config()
    resolved = config.resolve_llm_config(api_key=api_key, api_base=api_base, model=model)
    config.configure_llm_environment(resolved)
    return resolved


def get_chatglm_api_key() -> str:
    """获取 ChatGLM API Key"""
    return get_config().chatglm_api_key


def get_api_key(provider: str = "qwen") -> str:
    """
    根据提供商获取 API Key

    Args:
        provider: 提供商名称 (qwen, chatglm)

    Returns:
        API Key 字符串
    """
    config = get_config()

    if provider.lower() == "qwen":
        return config.qwen_api_key
    elif provider.lower() in ["chatglm", "chatglmu"]:
        return config.chatglm_api_key
    else:
        raise ValueError(f"不支持的提供商: {provider}")
