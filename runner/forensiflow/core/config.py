"""
ForensiFlow 统一配置管理模块

从环境变量和 .env 文件加载配置，避免硬编码 API Key
"""

import os
from pathlib import Path
from typing import Optional


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

        # 加载 .env 文件
        self._load_env()

    def _load_env(self):
        """加载 .env 文件"""
        if not self.env_file.exists():
            print(f"⚠️  警告：.env 文件不存在: {self.env_file}")
            print(f"💡 提示：请复制 .env.template 为 .env 并配置您的 API Key")
            return

        # 读取 .env 文件并设置环境变量
        with open(self.env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过注释和空行
                if not line or line.startswith('#'):
                    continue

                # 解析 KEY=VALUE 格式
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    # 如果环境变量尚未设置，则使用 .env 中的值
                    if key not in os.environ:
                        os.environ[key] = value

    # ==================== LLM API 配置 ====================
    @property
    def qwen_api_key(self) -> str:
        """获取 Qwen API Key"""
        api_key = os.getenv("QWEN_API_KEY")
        if not api_key or api_key == "your_qwen_api_key_here":
            raise ValueError(
                "❌ QWEN_API_KEY 未配置！\n"
                "   请在 .env 文件中设置 QWEN_API_KEY"
            )
        return api_key

    @property
    def chatglm_api_key(self) -> str:
        """获取 ChatGLM API Key"""
        api_key = os.getenv("CHATGLM_API_KEY")
        if not api_key or api_key == "your_chatglm_api_key_here":
            raise ValueError(
                "❌ CHATGLM_API_KEY 未配置！\n"
                "   请在 .env 文件中设置 CHATGLM_API_KEY"
            )
        return api_key

    @property
    def qwen_api_url(self) -> str:
        """Qwen API 端点"""
        return os.getenv("QWEN_API_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    @property
    def chatglm_api_url(self) -> str:
        """ChatGLM API 端点"""
        return os.getenv("CHATGLM_API_URL", "https://open.bigmodel.cn/api/paas/v4")

    @property
    def qwen_default_model(self) -> str:
        """Qwen 默认模型"""
        return os.getenv("QWEN_DEFAULT_MODEL", "qwen-plus")

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
    """获取 Qwen API Key"""
    return get_config().qwen_api_key


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
