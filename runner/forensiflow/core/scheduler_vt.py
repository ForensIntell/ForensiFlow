"""
Task Scheduler with VisionTasker API Integration

Orchestrates the execution of tasks using VisionTasker API for UI detection.
"""

import logging
import time
import json
import os
import pathlib
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable

from .modules.screenshot import ScreenshotModule
from .modules.executor import ExecutorModule
from .modules.storage import StorageModule
from .semantic_matcher import SemanticMatcher, SemanticMatcherMock
from .rag_template_matcher import RAGTemplateMatcher, RAGTemplateMatcherMock
from .script_registry import ScriptRegistry
# VisionTasker 集成已移除，改用 API 调用


@dataclass
class StepConfig:
    """Configuration for a single execution step."""
    name: str
    enabled: bool = True
    pre_wait: float = 0.0  # Wait time before step (seconds)
    post_wait: float = 0.0  # Wait time after step (seconds)


class TaskSchedulerVT:
    """
    Task Scheduler with VisionTasker Integration

    使用 VisionTasker 进行 UI 检测的任务调度器。
    """

    # ==================== 配置常量 ====================
    class _Config:
        """硬编码常量配置集中管理"""

        # API 端点配置
        QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        CHATGLM_API_URL = "https://open.bigmodel.cn/api/paas/v4"

        # 默认模型配置
        QWEN_DEFAULT_MODEL = "qwen-plus"  # qwen-turbo, qwen-plus, qwen-max
        CHATGLM_DEFAULT_MODEL = "glm-4-flash"

        # VisionTasker 路径配置
        VISIONTASKER_PATH = "/root/MobiAgent/external/VisionTasker"
        MODEL_PATH = "pt_model/yolo_mdl.pt"
        MODEL_PREFIX = "pt_model/yolo_vins_"
        MODEL_SUFFIX = "_mdl.pt"
        CLIP_MODEL_PATH = "pt_model/clip_mdl.pth"

        # 时间配置（秒）
        WAIT_UI_STABILIZE = 1.0
        WAIT_AFTER_INPUT_CLICK = 0.5
        WAIT_AFTER_APP_LAUNCH = 5.0
        WAIT_AFTER_ACTION = 1.0

        # LLM 参数配置
        LLM_TEMPERATURE_LOW = 0.01
        LLM_TEMPERATURE_MEDIUM = 0.3
        LLM_TOP_P = 0.7

        # 迭代限制
        MAX_STEPS_DEFAULT = 35
        MAX_COMPLETION_CHECKS = 10
        MAX_DYNAMIC_CONTEXT_ITERATIONS = 5
        MAX_UI_DETECTION_FAILURES = 3

        # UI 描述配置
        UI_DESCRIPTION_MAX_LENGTH = 200

    # Default step configuration for VisionTasker
    DEFAULT_STEPS = [
        StepConfig(name="screenshot", pre_wait=3.0),
        StepConfig(name="ui_detection"),      # VisionTasker UI 检测
        StepConfig(name="planning"),           # Planner 决策
        StepConfig(name="xml_matching"),       # XML 文本匹配（快速匹配）
        StepConfig(name="element_matching"),   # 元素匹配（VisionTasker fallback）
        StepConfig(name="execute", post_wait=5.0),  # 执行后等待 5 秒
        StepConfig(name="store"),
    ]

    def __init__(
        self,
        device,
        device_type: str = "Android",
        planner_api_key: str = None,
        planner_base_url: str = None,
        planner_model: str = None,
        planner_provider: str = "qwen",  # qwen, chatglm
        data_dir: str = "./data",
        resize_factor: float = 0.5,
        steps: Optional[List[StepConfig]] = None,
        custom_handlers: Optional[Dict[str, Callable]] = None
    ):
        """
        Initialize task scheduler with VisionTasker API integration.

        Args:
            device: Device object (AndroidDevice or HarmonyDevice)
            device_type: Device type (Android or Harmony)
            planner_api_key: Planner API 密钥（Qwen 或 ChatGLM）
            planner_base_url: Planner API 端点（可选，使用默认值）
            planner_model: Planner 模型名称（可选，使用默认值）
            planner_provider: Planner 提供商 (qwen, chatglm)
            data_dir: Directory for data storage
            resize_factor: Image resize factor
            steps: Custom step configuration
            custom_handlers: Custom step handlers (optional)
        """
        self.device = device
        self.device_type = device_type
        self.data_dir = data_dir
        self.planner_provider = planner_provider
        self.steps = steps if steps is not None else self.DEFAULT_STEPS.copy()
        self.custom_handlers = custom_handlers or {}

        # Initialize modules
        self.screenshot_module = ScreenshotModule(resize_factor=resize_factor)
        self.executor_module = ExecutorModule(device)
        self.storage_module = StorageModule(data_dir)

        # VisionTasker 模块引用（直接导入，保持模型常驻内存）
        self._vt_models_loaded = False
        self._vt_models = None  # 存储 (_model_ver, _model_det, _model_cls, _preprocess, _ocr)
        self._vt_module_path = self._Config.VISIONTASKER_PATH
        self._vt_process_img = None  # process_img 函数引用

        # Planner configuration
        self.planner_api_key = planner_api_key
        self.planner_model = planner_model
        self.planner_base_url = planner_base_url

        # 根据提供商设置默认值
        if planner_provider == "qwen":
            if not planner_base_url:
                self.planner_base_url = self._Config.QWEN_API_URL
            if not planner_model:
                self.planner_model = self._Config.QWEN_DEFAULT_MODEL
        elif planner_provider == "chatglm":
            if not planner_base_url:
                self.planner_base_url = self._Config.CHATGLM_API_URL
            if not planner_model:
                self.planner_model = self._Config.CHATGLM_DEFAULT_MODEL

        # 延迟初始化 Planner 客户端
        self._planner_client = None

        # Execution state
        self.history: List[str] = []
        self.actions: List[Dict[str, Any]] = []
        self.reacts: List[Dict[str, Any]] = []
        self.step = 0

        # 任务上下文管理（用于步骤序列模式）
        self._original_task: str = ""  # 原始任务描述
        self._planned_steps: List[Dict[str, Any]] = []  # LLM 规划的完整步骤序列
        self._current_step_index: int = 0  # 当前执行到的步骤索引
        self._failed_attempts: List[Dict[str, Any]] = []  # 失败的尝试记录

        # 语义匹配器（延迟加载）
        self._semantic_matcher = None

        # RAG 模板匹配器（延迟加载）
        self._rag_matcher = None

        logging.info(f"TaskSchedulerVT initialized with {planner_provider.upper()} model: {self.planner_model}")

    @property
    def planner_client(self):
        """延迟初始化 Planner 客户端"""
        if self._planner_client is None and self.planner_api_key:
            try:
                from openai import OpenAI
                self._planner_client = OpenAI(
                    api_key=self.planner_api_key,
                    base_url=self.planner_base_url
                )
                logging.info(f"{self.planner_provider.upper()} API client initialized: {self.planner_base_url}")
            except Exception as e:
                logging.error(f"Failed to initialize {self.planner_provider.upper()} API client: {e}")
        return self._planner_client

    @property
    def semantic_matcher(self):
        """延迟初始化语义匹配器"""
        if self._semantic_matcher is None:
            try:
                # 导入配置
                import sys
                import os
                # 添加项目根目录到 Python 路径
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                from runner.forensiflow.core.config import get_config

                config = get_config()

                # 检查是否启用
                if not config.semantic_matcher_enabled:
                    logging.info("⚠️  语义匹配器已禁用，将直接调用 LLM")
                    self._semantic_matcher = SemanticMatcherMock()
                    return self._semantic_matcher

                # 初始化语义匹配器
                logging.info(f"\n{'='*60}")
                logging.info(f"🔄 正在初始化语义匹配器...")
                logging.info(f"{'='*60}")

                self._semantic_matcher = SemanticMatcher(
                    model_path=config.semantic_matcher_model_path,
                    threshold=config.semantic_matcher_threshold,
                    cache_size=config.semantic_matcher_cache_size,
                    device=config.semantic_matcher_device
                )

                logging.info(f"✅ 语义匹配器初始化完成")
                logging.info(f"   - 模型路径: {config.semantic_matcher_model_path}")
                logging.info(f"   - 阈值: {config.semantic_matcher_threshold}")
                logging.info(f"   - 设备: {config.semantic_matcher_device}")
                logging.info(f"{'='*60}\n")

            except Exception as e:
                logging.warning(f"⚠️  语义匹配器初始化失败: {e}")
                logging.warning(f"💡 将直接使用 LLM 匹配")
                self._semantic_matcher = SemanticMatcherMock()

        return self._semantic_matcher

    @property
    def rag_matcher(self):
        """延迟初始化 RAG 模板匹配器"""
        if self._rag_matcher is None:
            try:
                # 导入配置
                import sys
                import os
                # 添加项目根目录到 Python 路径
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
                if project_root not in sys.path:
                    sys.path.insert(0, project_root)

                from runner.forensiflow.core.config import get_config

                config = get_config()

                # 检查是否启用
                if not config.rag_enabled:
                    logging.info("⚠️  RAG 模板匹配器已禁用")
                    self._rag_matcher = RAGTemplateMatcherMock()
                    return self._rag_matcher

                # 初始化 RAG 模板匹配器
                logging.info(f"\n{'='*60}")
                logging.info(f"🔄 正在初始化 RAG 模板匹配器...")
                logging.info(f"{'='*60}")

                self._rag_matcher = RAGTemplateMatcher(
                    model_path=config.rag_model_path,
                    templates_dir=config.rag_templates_dir,
                    top_k=config.rag_top_k,
                    device=config.rag_device
                )

                logging.info(f"✅ RAG 模板匹配器初始化完成")
                logging.info(f"   - 模型路径: {config.rag_model_path}")
                logging.info(f"   - 模板目录: {config.rag_templates_dir}")
                logging.info(f"   - Top-K: {config.rag_top_k}")
                logging.info(f"   - 阈值: {config.rag_threshold}")
                logging.info(f"   - 设备: {config.rag_device}")
                logging.info(f"{'='*60}\n")

            except Exception as e:
                logging.warning(f"⚠️  RAG 模板匹配器初始化失败: {e}")
                logging.warning(f"💡 将不使用模板示例")
                self._rag_matcher = RAGTemplateMatcherMock()

        return self._rag_matcher

    def _load_visiontasker_models(self):
        """加载 VisionTasker 模型（整个任务期间只加载一次）"""
        if self._vt_models_loaded:
            logging.info("VisionTasker 模型已加载，跳过")
            return True

        try:
            logging.info(f"\n{'='*60}")
            logging.info(f"🔄 正在加载 VisionTasker 模型...")
            logging.info(f"{'='*60}")

            import sys
            import os

            # 保存原始工作目录
            original_cwd = os.getcwd()

            # 切换到 VisionTasker 目录（模型文件使用相对路径）
            os.chdir(self._vt_module_path)

            # 将 VisionTasker 添加到 sys.path（GUI.py 也会自己添加，但这里添加更保险）
            if self._vt_module_path not in sys.path:
                sys.path.insert(0, self._vt_module_path)

            try:
                # 导入配置
                from core.Config import alg, accurate_ocr, label_path_dir, high_conf_flag
                from core.Config import clean_save, ocr_save_flag, ocr_output_only, workflow_only

                # 将相对路径转换为绝对路径（因为后续会切换工作目录）
                if not os.path.isabs(label_path_dir):
                    label_path_dir = os.path.join(self._vt_module_path, label_path_dir)

                # 导入模型加载函数
                import core.import_models as import_models

                # 加载模型
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = import_models.import_all_models(
                    alg,
                    accurate_ocr=accurate_ocr,
                    model_path_yolo='pt_model/yolo_mdl.pt',
                    model_path_vins_dir='pt_model/yolo_vins_',
                    model_ver='14',
                    model_path_vins_file='_mdl.pt',
                    model_path_cls='pt_model/clip_mdl.pth'
                )

                # 导入 process_img 函数（GUI.py 会自动处理 layout 导入问题）
                from core.process_img_script import process_img

                # 保存模型引用
                self._vt_models = (_model_ver, _model_det, _model_cls, _preprocess, _ocr)
                self._vt_process_img = process_img
                self._vt_models_loaded = True

                # 保存配置到实例变量
                self._vt_alg = alg
                self._vt_accurate_ocr = accurate_ocr
                self._vt_label_path_dir = label_path_dir
                self._vt_high_conf_flag = high_conf_flag
                self._vt_clean_save = clean_save
                self._vt_ocr_save_flag = ocr_save_flag
                self._vt_ocr_output_only = ocr_output_only
                self._vt_workflow_only = workflow_only

            finally:
                # 恢复原始工作目录
                os.chdir(original_cwd)

            logging.info(f"✓ VisionTasker 模型加载成功！")
            logging.info(f"{'='*60}\n")

            return True

        except Exception as e:
            logging.error(f"✗ VisionTasker 模型加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _unload_visiontasker_models(self):
        """释放 VisionTasker 模型资源"""
        if not self._vt_models_loaded:
            return

        try:
            logging.info(f"\n{'='*60}")
            logging.info(f"🔄 正在释放 VisionTasker 模型资源...")
            logging.info(f"{'='*60}")

            # 清空模型引用
            self._vt_models = None
            self._vt_process_img = None
            self._vt_models_loaded = False

            # 使用垃圾回收释放内存
            import gc
            gc.collect()

            # 如果有 CUDA，清理 GPU 缓存
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logging.info("✓ GPU 缓存已清理")
            except:
                pass

            logging.info(f"✓ VisionTasker 模型资源已释放")
            logging.info(f"{'='*60}\n")

        except Exception as e:
            logging.warning(f"释放模型资源时出现警告: {e}")

    def _plan_task_with_app(self, abstract_task: str) -> Dict[str, Any]:
        """
        使用 LLM 规划任务并识别应用，生成可执行的步骤序列

        Args:
            abstract_task: 抽象任务描述，如"打开微信朋友圈"

        Returns:
            {
                "app_name": "微信",
                "reasoning": "选择理由",
                "steps": [
                    {"action": "click", "target": "我的"},
                    {"action": "swipe", "params": {"direction": "down"}},
                    {"action": "click", "target": "朋友圈"}
                ]
            }
        """
        if not self.planner_client:
            raise RuntimeError("Planner client not initialized")

        logging.info(f"\n{'='*60}")
        logging.info(f"🤖 LLM 任务规划中...")
        logging.info(f"原始任务: {abstract_task}")
        logging.info(f"{'='*60}\n")

        # 🔍 RAG 模板检索
        rag_examples = ""
        try:
            # 搜索所有应用的模板，找出最相似的任务模板
            all_matches = []

            # 遍历所有应用进行搜索
            for app_name in self.rag_matcher.templates.keys():
                matches = self.rag_matcher.search(app=app_name, task=abstract_task, top_k=2)
                all_matches.extend(matches)

            # 按相似度排序并取最佳匹配
            all_matches.sort(key=lambda x: x.score, reverse=True)
            top_matches = all_matches[:1]  # 只取最相似的1个模板

            if top_matches and top_matches[0].score >= 0.6:  # 阈值可配置
                match = top_matches[0]
                logging.info(f"📚 RAG 检索到最佳匹配模板:")
                logging.info(f"   [{match.template.get('app', 'Unknown')}] {match.template.get('task', 'Unknown')} (相似度: {match.score:.3f})")

                # 格式化为 Few-Shot 示例
                rag_examples = self.rag_matcher.format_prompt_examples(top_matches, max_examples=1)
                logging.info(f"✅ RAG 示例已添加到提示词\n")
            else:
                logging.info(f"ℹ️  未找到足够相似的任务模板 (最佳匹配: {top_matches[0].score if top_matches else 0:.3f})\n")

        except Exception as e:
            logging.warning(f"⚠️  RAG 检索失败: {e}")
            logging.warning(f"💡 将不使用模板示例\n")

        # 构建 Prompt - 要求输出步骤序列
        prompt = f"""## 角色定义
你是一个具备高度自主规划能力的UI自动化取证专家。你需要理解用户意图，并将任务拆解为可执行的步骤。

## ⚠️ 重要约束（必须遵守）
1. **应用会自动启动**：系统会自动识别并启动目标应用，你的步骤序列中**严禁包含**"启动XX应用"、"打开XX应用"这样的步骤。
2. **从应用内开始**：步骤序列应该从应用启动后的第一个界面操作开始。
3. **禁止搜索操作**：你的步骤序列中**严禁包含**任何搜索相关的操作（如：点击搜索框、输入搜索关键词、点击搜索按钮等）。

## ⚠️ 避坑与纠错机制 (重要)
作为通用大模型，你关于App操作的"常识"在当前的专业取证工具环境下可能会导致错误（例如：试图通过繁琐的"新建群聊"去获取联系人，而不是使用高效的快捷键）。
为了纠正这些潜在的错误路线，系统为你提供了【参考案例】。你必须主动从案例中学习并提取以下信息来修正你的规划：
1. **优先使用特有UI**：如果案例中使用了特定的UI元素（如"加号键"、"消息/信息图标"等），说明这是该取证系统验证过的最优入口，你应当放弃你原本规划的常规路径，优先采纳这些UI节点。
2. **识别脚本边界**：如果案例中使用了 `CallScript` 动作，这代表该任务的深层数据抓取交由底层代码完成。你只需规划到达该界面的 UI 前置步骤，然后在最后一步规划输出该动作 `CallScript`，绝对不要试图自己去规划复杂的滚动和抓取动作！

## 动作空间（你被授权使用的合法操作，严禁编造其他动作）
- **click**: 点击操作，格式：`{{"action": "click", "target": "目标文本"}}`
- **CallScript**: 调用底层自动化提取脚本，格式：`{{"action": "CallScript", "target": "调用的脚本名称"}}`
- **swipe**: 滑动操作，格式：`{{"action": "swipe", "params": {{"direction": "up/down/left/right"}}}}`
- **wait**: 等待操作，格式：`{{"action": "wait", "params": {{"duration": 秒数}}}}`


## 已知输入
原始用户任务描述："{abstract_task}"

## 📚 参考案例（供你吸收并纠正自身规划路线）
{rag_examples}

## 输出要求
请严格按照以下JSON格式输出（格式与参考案例保持一致）：
- 在 reasoning 中说明你是如何利用参考案例来纠正或优化你的常规操作路线的

```json
{{
  "app": "应用名称（如：微信、淘宝、WhatsApp等）",
  "reasoning": "简要说明你的规划思路，以及你是如何吸收参考案例中的特定动作（如特定的点击目标或 CallScript）来优化路径的。",
  "steps": [
    {{"action": "Click", "target": "目标文本1"}},
    {{"action": "Swipe", "params": {{"direction": "down"}}}},
    {{"action": "Click", "target": "目标文本2"}},
    {{"action": "CallScript", "target": "脚本名称"}}
  ]
}}
```
"""

        logging.info(f"发送给 LLM 的 Prompt (包含 RAG {'示例' if rag_examples else '无示例'}):\n{prompt}\n")

        try:
            # 调用 LLM
            response = self.planner_client.chat.completions.create(
                model=self.planner_model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.01  # 低温度获得稳定输出
            )

            response_text = response.choices[0].message.content

            logging.info(f"\n{'='*60}")
            logging.info(f"📥 LLM 规划响应:")
            logging.info(f"{'='*60}")
            logging.info(f"{response_text}")
            logging.info(f"{'='*60}\n")

            # 解析 JSON 响应
            import re
            import json

            # 尝试提取 JSON
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 尝试直接查找 JSON 对象
                json_match = re.search(r'(\{.*?\})', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    raise ValueError("无法在响应中找到有效的 JSON")

            result = json.loads(json_str)

            # 验证必需字段（支持新格式 app 和旧格式 app_name）
            if "app" not in result and "app_name" not in result:
                raise ValueError("LLM 响应缺少必需字段 (app 或 app_name)")

            # 兼容两种格式
            if "app_name" in result and "app" not in result:
                result["app"] = result.pop("app_name")

            if not isinstance(result["steps"], list):
                raise ValueError("steps 必须是数组")

            # 验证每个步骤的格式
            for i, step in enumerate(result["steps"]):
                if "action" not in step:
                    raise ValueError(f"步骤 {i+1} 缺少 action 字段")

            logging.info(f"✓ 规划完成:")
            logging.info(f"  - 应用: {result.get('app', 'Unknown')}")
            logging.info(f"  - 步骤数: {len(result['steps'])}")
            for i, step in enumerate(result["steps"]):
                logging.info(f"    {i+1}. {step.get('action', 'unknown')} - {step.get('target', step.get('params', ''))}")
            logging.info(f"  - 理由: {result.get('reasoning', 'N/A')}\n")

            return result

        except Exception as e:
            logging.error(f"✗ 任务规划失败: {e}")
            raise

    def _check_task_completion_and_plan_next(
        self,
        max_iterations: int = 10
    ) -> Dict[str, Any]:
        """
        检查任务是否完成，如果未完成则规划下一批步骤

        Args:
            max_iterations: 最大循环次数（防止无限循环）

        Returns:
            {
                "completed": bool,  # 任务是否完成
                "new_steps": list,   # 如果未完成，新生成的步骤列表
                "reasoning": str     # 判断理由
            }
        """
        if not self.planner_client:
            raise RuntimeError("Planner client not initialized")

        logging.info(f"\n{'='*60}")
        logging.info(f"🤔 检查任务是否完成...")
        logging.info(f"{'='*60}\n")

        try:
            # 1. 截图当前界面
            screenshot_path = os.path.join(self.run_data_dir, f"check_completion_{self.step}.jpg")
            self.device.screenshot(screenshot_path)

            # 2. VisionTasker 检测
            ui_json_path = os.path.join(self.run_data_dir, f"ui_check_{self.step}.json")

            original_cwd = os.getcwd()
            os.chdir(self._vt_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._vt_models
                result_js = self._vt_process_img(
                    label_path_dir=self._vt_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._vt_high_conf_flag,
                    alg=self._vt_alg,
                    clean_save=self._vt_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._vt_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._vt_ocr_output_only,
                    workflow_only=self._vt_workflow_only,
                    accurate_ocr=self._vt_accurate_ocr
                )
            finally:
                os.chdir(original_cwd)

            # 保存 UI JSON
            with open(ui_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            # 3. 构建 UI 描述
            ui_description = self._ui_elements_to_description(result_js)

            # 4. 构建已完成步骤的描述
            completed_steps_desc = [
                self._build_step_description(step, i+1)
                for i, step in enumerate(self._planned_steps)
            ]
            completed_str = "\n".join(completed_steps_desc) if completed_steps_desc else "（无）"

            # 5. 构建 Prompt
            prompt = f"""## 角色定义
你是一个UI自动化任务评估专家，负责判断当前任务是否已经完成。

## 原始任务
{self._original_task}

## 已执行的步骤
{completed_str}

## 当前界面状态
{ui_description}

## 你的任务
请判断：原始任务是否已经完成？

## 输出格式
请严格按照以下JSON格式输出：
```json
{{
  "completed": true/false,
  "reasoning": "判断理由（说明为什么任务已完成或未完成）",
  "next_steps": []  // 如果未完成，列出接下来需要执行的步骤
}}
```

## 输出规则
- 如果任务已完成：completed=true，next_steps=[]
- 如果任务未完成：completed=false，next_steps 包含下一步需要执行的操作

## 可用的操作类型
- **click**: 点击操作，{{"action": "click", "target": "目标文本"}}
- **input**: 输入操作，{{"action": "input", "target": "输入框", "text": "内容"}}
- **swipe**: 滑动操作，{{"action": "swipe", "params": {{"direction": "up/down/left/right"}}}}
- **forensics**: 取证操作，{{"action": "forensics", "params": {{"app": "应用名", "type": "取证类型"}}}}
  - 例如: {{"action": "forensics", "params": {{"app": "whatsapp", "type": "whatsapp_chat"}}}}

## 示例
输入：原始任务="依次打开每一个联系人"，已执行步骤="步骤1: 点击'张三'"，当前界面="张三的详情页，有返回按钮"
输出：
```json
{{
  "completed": false,
  "reasoning": "任务要求依次打开每一个联系人，当前只打开了张三，还需要继续打开其他联系人",
  "next_steps": [
    {{"action": "click", "target": "返回"}},
    {{"action": "click", "target": "李四"}}
  ]
}}
```
"""

            logging.info(f"发送给 LLM 的 Prompt:\n{prompt}\n")

            # 6. 调用 LLM
            response = self.planner_client.chat.completions.create(
                model=self.planner_model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.01  # 低温度获得稳定输出
            )

            response_text = response.choices[0].message.content

            logging.info(f"\n{'='*60}")
            logging.info(f"📥 LLM 任务完成判断响应:")
            logging.info(f"{'='*60}")
            logging.info(f"{response_text}")
            logging.info(f"{'='*60}\n")

            # 7. 解析 JSON 响应
            import re
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'(\{.*?\})', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    raise ValueError("无法在响应中找到有效的 JSON")

            result = json.loads(json_str)

            # 8. 验证并返回结果
            completed = result.get("completed", False)
            reasoning = result.get("reasoning", "")
            next_steps = result.get("next_steps", [])

            if completed:
                logging.info(f"✓ LLM 判断任务已完成: {reasoning}")
            else:
                logging.info(f"⚠️ LLM 判断任务未完成: {reasoning}")
                logging.info(f"📋 建议的下一步骤: {next_steps}")

            return {
                "completed": completed,
                "new_steps": next_steps,
                "reasoning": reasoning
            }

        except Exception as e:
            logging.error(f"✗ 任务完成判断失败: {e}")
            import traceback
            traceback.print_exc()
            # 出错时保守处理，假设任务已完成
            return {
                "completed": True,
                "new_steps": [],
                "reasoning": f"判断过程出错，假设任务已完成: {e}"
            }

    def _execute_predefined_step(self, step: Dict[str, Any]) -> bool:
        """
        执行预定义的步骤（XML优先，失败则VisionTasker fallback）

        Args:
            step: 步骤字典，格式：{"action": "click", "target": "我的"}

        Returns:
            bool: 是否执行成功
        """
        action = step.get("action", "")
        target = step.get("target", "")
        params = step.get("params", {})

        import time

        try:
            # 1. 等待一下，让界面稳定
            time.sleep(1)

            # 2. 根据操作类型执行（不区分大小写）
            action_lower = action.lower()

            if action_lower == "click":
                return self._execute_click_step(target)

            elif action_lower == "input":
                text = params.get("text", "")
                return self._execute_input_step(target, text)

            elif action_lower == "swipe":
                direction = params.get("direction", "down")
                return self._execute_swipe_step(direction)

            elif action_lower == "wait":
                duration = params.get("duration", 2)
                logging.info(f"    ⏱️ 等待 {duration} 秒...")
                time.sleep(duration)
                return True

            elif action_lower == "forensics":
                app_name = params.get("app", "")
                forensics_type = params.get("type", "")
                return self._execute_forensics_step(app_name, forensics_type)

            elif action_lower == "callscript":
                # 调用取证脚本
                script_name = step.get("target", "")
                logging.info(f"    📜 CallScript: {script_name}")

                # 使用脚本注册表执行
                success = ScriptRegistry.execute_script(
                    script_name=script_name,
                    device=self.device
                )

                if success:
                    # 记录到 reacts
                    self.reacts.append({
                        "reasoning": f"执行取证脚本: {script_name}",
                        "function": {
                            "name": "CallScript",
                            "parameters": {
                                "script": script_name
                            }
                        },
                        "action_index": self.step
                    })

                return success

            else:
                logging.warning(f"    ⚠️ 未知操作类型: {action}")
                return False

        except Exception as e:
            logging.error(f"    ✗ 执行步骤失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _execute_click_step(self, target: str) -> bool:
        """
        执行点击步骤（XML优先）

        Args:
            target: 目标文本

        Returns:
            bool: 是否执行成功
        """
        logging.info(f"    🎯 点击目标: {target}")

        # 1. 尝试 XML 匹配
        logging.info(f"    🔍 步骤 1/2: 尝试 XML 匹配...")

        try:
            # 获取 XML
            xml_path = os.path.join(self.run_data_dir, f"hierarchy_{self.step}.xml")
            xml_content = self.device.dump_xml(xml_path)

            logging.info(f"    📄 XML 已保存: {xml_path}")

            # 在 XML 中查找元素
            matched_element = self._find_element_in_xml(xml_content, target)

            if matched_element and matched_element.get("bounds"):
                bounds = matched_element["bounds"]
                center_x = (bounds["left"] + bounds["right"]) // 2
                center_y = (bounds["top"] + bounds["bottom"]) // 2

                logging.info(f"    ✓ XML 匹配成功: ({center_x}, {center_y})")
                logging.info(f"      - 文本: {matched_element.get('text', '')}")
                logging.info(f"      - Class: {matched_element.get('class', '')}")

                # 执行点击
                self.device.click(center_x, center_y)

                # 记录到 reacts
                self.reacts.append({
                    "reasoning": f"通过 XML 匹配点击 '{target}'",
                    "function": {
                        "name": "click",
                        "parameters": {"target": target, "x": center_x, "y": center_y}
                    },
                    "action_index": self.step
                })

                time.sleep(1)
                return True

        except Exception as e:
            logging.info(f"    ✗ XML 匹配失败: {e}")

            # 记录失败尝试（用于上下文提示词）
            if self._planned_steps:
                self._failed_attempts.append({
                    "action": "click",
                    "target": target,
                    "method": "XML 匹配",
                    "reason": str(e) if e else "未找到匹配元素"
                })

        # 2. XML 失败，尝试 VisionTasker + LLM 动态上下文循环
        logging.info(f"    🔍 步骤 2/2: 尝试 VisionTasker + LLM 动态上下文循环...")

        try:
            # 判断是否使用上下文提示词（如果是步骤序列模式且有上下文信息）
            use_context = self._planned_steps and len(self._planned_steps) > 0

            if use_context:
                # 使用动态上下文循环（支持滑动、多轮决策）
                return self._execute_step_with_dynamic_context("click", target)
            else:
                # 原有逻辑：单次 LLM 决策（非步骤序列模式）
                return self._execute_click_legacy_fallback(target)

        except Exception as e:
            logging.error(f"    ✗ VisionTasker + LLM 匹配失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        logging.error(f"    ✗ 所有匹配方式均失败")
        return False

    def _execute_click_legacy_fallback(self, target: str) -> bool:
        """
        原有的 VisionTasker + LLM 决策逻辑（非步骤序列模式的回退方案）

        Args:
            target: 目标文本

        Returns:
            bool: 是否执行成功
        """
        import time

        try:
            # 截图
            screenshot_path = os.path.join(self.run_data_dir, f"{self.step}.jpg")
            self.device.screenshot(screenshot_path)
            logging.info(f"    📸 截图已保存: {screenshot_path}")

            # VisionTasker 检测
            ui_json_path = os.path.join(self.run_data_dir, f"ui_{self.step}.json")

            original_cwd = os.getcwd()
            os.chdir(self._vt_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._vt_models

                result_js = self._vt_process_img(
                    label_path_dir=self._vt_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._vt_high_conf_flag,
                    alg=self._vt_alg,
                    clean_save=self._vt_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._vt_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._vt_ocr_output_only,
                    workflow_only=self._vt_workflow_only,
                    accurate_ocr=self._vt_accurate_ocr
                )
            finally:
                os.chdir(original_cwd)

            # 保存 JSON
            with open(ui_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            logging.info(f"    📄 UI JSON 已保存: {ui_json_path}")
            logging.info(f"    ✓ VisionTasker detected {len(result_js) if isinstance(result_js, list) else 0} elements")

            # 使用 LLM 决策（不使用上下文提示词）
            decision = self._decide_action_with_llm(
                result_js,
                f"点击{target}",
                use_context_prompt=False
            )

            # 从 VisionTasker JSON 中查找 LLM 决策的元素
            llm_target = decision.get("target", "")
            if not llm_target:
                logging.error(f"    ✗ LLM 未返回目标元素")
                return False

            logging.info(f"    Matching element: '{llm_target}'")
            matched_element = self._find_element_by_text(result_js, llm_target)

            if matched_element:
                location = matched_element.get("location", {})
                if location:
                    left = location.get("left", 0)
                    top = location.get("top", 0)
                    right = location.get("right", 0)
                    bottom = location.get("bottom", 0)

                    center_x = (left + right) // 2
                    center_y = (top + bottom) // 2

                    logging.info(f"    ✓ LLM 决策成功，点击坐标: ({center_x}, {center_y})")

                    # 执行点击
                    self.device.click(center_x, center_y)

                    # 记录到 reacts
                    self.reacts.append({
                        "reasoning": decision.get("reasoning", f"LLM 决策点击 '{llm_target}'"),
                        "function": {
                            "name": "click",
                            "parameters": {"target": llm_target, "x": center_x, "y": center_y}
                        },
                        "action_index": self.step
                    })

                    time.sleep(1)
                    return True
            else:
                logging.error(f"    ✗ 未找到 LLM 决策的元素: '{llm_target}'")
                return False

        except Exception as e:
            logging.error(f"    ✗ VisionTasker + LLM 匹配失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _execute_step_with_dynamic_context(
        self,
        current_action: str,
        current_target: str,
        max_iterations: int = 5
    ) -> bool:
        """
        使用动态上下文循环执行步骤（支持滑动、多轮决策）

        当 XML 匹配失败后，使用此方法进行动态循环：
        1. 截图 → Vision 检测 → LLM 决策
        2. 根据决策执行操作：
           - swipe: 执行滑动，继续循环
           - click/input: 执行操作，如果成功返回 True
           - done: 返回 True（当前步骤已完成）

        Args:
            current_action: 当前尝试的操作类型 (click/input/swipe)
            current_target: 当前尝试的目标元素
            max_iterations: 最大循环次数

        Returns:
            bool: 是否执行成功
        """
        import time

        for iteration in range(max_iterations):
            logging.info(f"\n    🔄 动态上下文循环 {iteration + 1}/{max_iterations}")

            # 1. 截图
            screenshot_path = os.path.join(self.run_data_dir, f"{self.step}_iter{iteration}.jpg")
            self.device.screenshot(screenshot_path)
            logging.info(f"    📸 截图已保存: {screenshot_path}")

            # 2. VisionTasker 检测
            ui_json_path = os.path.join(self.run_data_dir, f"ui_{self.step}_iter{iteration}.json")

            original_cwd = os.getcwd()
            os.chdir(self._vt_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._vt_models
                result_js = self._vt_process_img(
                    label_path_dir=self._vt_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._vt_high_conf_flag,
                    alg=self._vt_alg,
                    clean_save=self._vt_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._vt_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._vt_ocr_output_only,
                    workflow_only=self._vt_workflow_only,
                    accurate_ocr=self._vt_accurate_ocr
                )
            finally:
                os.chdir(original_cwd)

            # 保存 UI JSON
            with open(ui_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            logging.info(f"    📄 UI JSON 已保存: {ui_json_path}")
            logging.info(f"    ✓ VisionTasker detected {len(result_js) if isinstance(result_js, list) else 0} elements")

            # 3. LLM 决策（使用上下文提示词）
            decision = self._decide_action_with_llm(
                result_js,
                f"{current_action} {current_target}",
                use_context_prompt=True,
                current_action=current_action,
                current_target=current_target
            )

            action = decision.get("action", "")
            reasoning = decision.get("reasoning", "")
            params = decision.get("parameters", {})

            logging.info(f"    🎯 LLM 决策: {action}, 理由: {reasoning}")

            # 不区分大小写
            action_lower = action.lower()

            # 4. 根据决策执行操作
            if action_lower == "done":
                logging.info(f"    ✓ LLM 认为当前步骤已完成")
                self.reacts.append({
                    "reasoning": reasoning,
                    "function": {"name": "done", "parameters": {}},
                    "action_index": self.step
                })
                return True

            elif action_lower == "swipe":
                direction = params.get("direction", "down")
                logging.info(f"    👆 执行滑动: {direction}")
                self._execute_swipe_step(direction)
                # 继续循环
                time.sleep(1)
                continue

            elif action_lower == "click":
                llm_target = decision.get("target", "")
                if not llm_target:
                    logging.error(f"    ✗ LLM 未返回目标元素")
                    # 记录失败并继续
                    self._failed_attempts.append({
                        "action": "click",
                        "target": current_target,
                        "method": "LLM 决策",
                        "reason": "LLM 未返回目标元素"
                    })
                    time.sleep(1)
                    continue

                # 查找元素
                matched_element = self._find_element_by_text(result_js, llm_target)
                if matched_element:
                    location = matched_element.get("location", {})
                    if location:
                        left = location.get("left", 0)
                        top = location.get("top", 0)
                        right = location.get("right", 0)
                        bottom = location.get("bottom", 0)

                        center_x = (left + right) // 2
                        center_y = (top + bottom) // 2

                        logging.info(f"    ✓ 点击坐标: ({center_x}, {center_y})")
                        self.device.click(center_x, center_y)

                        self.reacts.append({
                            "reasoning": reasoning,
                            "function": {
                                "name": "click",
                                "parameters": {"target": llm_target, "x": center_x, "y": center_y}
                            },
                            "action_index": self.step
                        })

                        time.sleep(1)
                        return True
                else:
                    logging.error(f"    ✗ 未找到元素: '{llm_target}'")
                    self._failed_attempts.append({
                        "action": "click",
                        "target": current_target,
                        "method": "LLM 决策",
                        "reason": f"未找到 LLM 决策的元素: {llm_target}"
                    })
                    time.sleep(1)
                    continue

            elif action_lower == "input":
                llm_target = decision.get("target", "")
                text = params.get("text", "")
                if not llm_target:
                    logging.error(f"    ✗ LLM 未返回目标元素")
                    self._failed_attempts.append({
                        "action": "input",
                        "target": current_target,
                        "method": "LLM 决策",
                        "reason": "LLM 未返回目标元素"
                    })
                    time.sleep(1)
                    continue

                # 查找元素
                matched_element = self._find_element_by_text(result_js, llm_target)
                if matched_element:
                    location = matched_element.get("location", {})
                    if location:
                        left = location.get("left", 0)
                        top = location.get("top", 0)
                        right = location.get("right", 0)
                        bottom = location.get("bottom", 0)

                        center_x = (left + right) // 2
                        center_y = (top + bottom) // 2

                        logging.info(f"    ✓ 点击输入框: ({center_x}, {center_y})")
                        self.device.click(center_x, center_y)
                        time.sleep(0.5)

                        if text:
                            logging.info(f"    ⌨️ 输入文字: {text}")
                            self.device.input_text(text)

                        self.reacts.append({
                            "reasoning": reasoning,
                            "function": {
                                "name": "input",
                                "parameters": {"target": llm_target, "text": text}
                            },
                            "action_index": self.step
                        })

                        time.sleep(1)
                        return True
                else:
                    logging.error(f"    ✗ 未找到元素: '{llm_target}'")
                    self._failed_attempts.append({
                        "action": "input",
                        "target": current_target,
                        "method": "LLM 决策",
                        "reason": f"未找到 LLM 决策的元素: {llm_target}"
                    })
                    time.sleep(1)
                    continue

            else:
                logging.warning(f"    ⚠️ 未知操作类型: {action}")
                self._failed_attempts.append({
                    "action": current_action,
                    "target": current_target,
                    "method": "LLM 决策",
                    "reason": f"未知的操作类型: {action}"
                })
                time.sleep(1)
                continue

        # 循环结束仍未完成
        logging.error(f"    ✗ 动态上下文循环达到最大次数 ({max_iterations})，仍未完成")
        return False

    def _execute_input_step(self, target: str, text: str) -> bool:
        """
        执行输入步骤（XML优先）

        Args:
            target: 输入框文本
            text: 要输入的内容

        Returns:
            bool: 是否执行成功
        """
        logging.info(f"    ⌨️  输入到 '{target}': {text}")

        # 1. 尝试 XML 匹配
        logging.info(f"    🔍 步骤 1/2: 尝试 XML 匹配...")

        try:
            xml_path = os.path.join(self.run_data_dir, f"hierarchy_{self.step}.xml")
            xml_content = self.device.dump_xml(xml_path)

            matched_element = self._find_element_in_xml(xml_content, target)

            if matched_element and matched_element.get("bounds"):
                bounds = matched_element["bounds"]
                center_x = (bounds["left"] + bounds["right"]) // 2
                center_y = (bounds["top"] + bounds["bottom"]) // 2

                logging.info(f"    ✓ XML 匹配成功: ({center_x}, {center_y})")

                # 点击输入框
                self.device.click(center_x, center_y)
                time.sleep(0.5)

                # 输入文字
                self.device.input_text(text)

                # 记录到 reacts
                self.reacts.append({
                    "reasoning": f"通过 XML 匹配输入到 '{target}'",
                    "function": {
                        "name": "input",
                        "parameters": {"target": target, "text": text}
                    },
                    "action_index": self.step
                })

                time.sleep(1)
                return True

        except Exception as e:
            logging.info(f"    ✗ XML 匹配失败: {e}")

            # 记录失败尝试（用于上下文提示词）
            if self._planned_steps:
                self._failed_attempts.append({
                    "action": "input",
                    "target": target,
                    "text": text,
                    "method": "XML 匹配",
                    "reason": str(e) if e else "未找到匹配元素"
                })

        # 2. VisionTasker + LLM 决策 Fallback
        logging.info(f"    🔍 步骤 2/2: 尝试 VisionTasker + LLM 决策...")

        try:
            screenshot_path = os.path.join(self.run_data_dir, f"{self.step}.jpg")
            self.device.screenshot(screenshot_path)

            ui_json_path = os.path.join(self.run_data_dir, f"ui_{self.step}.json")

            original_cwd = os.getcwd()
            os.chdir(self._vt_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._vt_models
                result_js = self._vt_process_img(
                    label_path_dir=self._vt_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._vt_high_conf_flag,
                    alg=self._vt_alg,
                    clean_save=self._vt_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._vt_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._vt_ocr_output_only,
                    workflow_only=self._vt_workflow_only,
                    accurate_ocr=self._vt_accurate_ocr
                )
            finally:
                os.chdir(original_cwd)

            with open(ui_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            logging.info(f"    📄 UI JSON 已保存: {ui_json_path}")
            logging.info(f"    ✓ VisionTasker detected {len(result_js) if isinstance(result_js, list) else 0} elements")

            # 判断是否使用上下文提示词（如果是步骤序列模式且有上下文信息）
            use_context = self._planned_steps and len(self._planned_steps) > 0

            # 使用 LLM 决策（支持上下文提示词）
            decision = self._decide_action_with_llm(
                result_js,
                f"在输入框输入'{text}'",
                use_context_prompt=use_context,
                current_action="input",
                current_target=target
            )

            # 从 VisionTasker JSON 中查找 LLM 决策的元素
            llm_target = decision.get("target", "")
            if not llm_target:
                logging.error(f"    ✗ LLM 未返回目标元素")
                return False

            logging.info(f"    Matching element: '{llm_target}'")
            matched_element = self._find_element_by_text(result_js, llm_target)

            if matched_element:
                location = matched_element.get("location", {})
                if location:
                    left = location.get("left", 0)
                    top = location.get("top", 0)
                    right = location.get("right", 0)
                    bottom = location.get("bottom", 0)

                    center_x = (left + right) // 2
                    center_y = (top + bottom) // 2

                    logging.info(f"    ✓ LLM 决策成功，点击输入框: ({center_x}, {center_y})")

                    self.device.click(center_x, center_y)
                    time.sleep(0.5)
                    self.device.input_text(text)

                    self.reacts.append({
                        "reasoning": decision.get("reasoning", f"LLM 决策输入到 '{llm_target}'"),
                        "function": {
                            "name": "input",
                            "parameters": {"target": llm_target, "text": text}
                        },
                        "action_index": self.step
                    })

                    time.sleep(1)
                    return True
            else:
                logging.error(f"    ✗ 未找到 LLM 决策的元素: '{llm_target}'")
                return False

        except Exception as e:
            logging.error(f"    ✗ VisionTasker + LLM 匹配失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _execute_swipe_step(self, direction: str) -> bool:
        """
        执行滑动步骤

        Args:
            direction: 滑动方向 (up/down/left/right)

        Returns:
            bool: 是否执行成功

        Note:
            滑动方向定义：
            - down: 内容向下滚动（手指向上滑）
            - up: 内容向上滚动（手指向下滑）
            - left: 内容向左滚动（手指向右滑）
            - right: 内容向右滚动（手指向左滑）
        """
        # 反转方向：uiautomator2 的方向是手指移动方向
        # 我们的定义是内容滚动方向
        direction_map = {
            "down": "up",      # 内容向下 = 手指向上
            "up": "down",      # 内容向上 = 手指向下
            "left": "right",   # 内容向左 = 手指向右
            "right": "left"    # 内容向右 = 手指向左
        }

        actual_direction = direction_map.get(direction, direction)
        logging.info(f"    👆 滑动方向: {direction} (内容方向) → {actual_direction} (手指方向)")

        import time

        try:
            # 执行滑动
            self.device.swipe(actual_direction)

            # 记录到 reacts
            self.reacts.append({
                "reasoning": f"向{direction}滑动（内容滚动）",
                "function": {
                    "name": "swipe",
                    "parameters": {"direction": direction, "actual_direction": actual_direction}
                },
                "action_index": self.step
            })

            time.sleep(1)
            return True

        except Exception as e:
            logging.error(f"    ✗ 滑动失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _execute_forensics_step(self, app_name: str, forensics_type: str) -> bool:
        """
        执行取证步骤（调用取证脚本）- 已废弃，请使用 CallScript

        Args:
            app_name: 应用名称（如 "whatsapp"、"wechat"）
            forensics_type: 取证类型（如 "whatsapp_chat"、"wechat_chat"）

        Returns:
            bool: 是否执行成功
        """
        logging.warning(f"    ⚠️ 'forensics' 动作已废弃，请使用 'CallScript' 代替")
        logging.warning(f"    💡 参考: {{'action': 'CallScript', 'target': '调用所有联系人信息及聊天记录脚本提取'}}")

        # 为了向后兼容，仍然执行
        import time
        import sys
        import os

        logging.info(f"    🔍 开始取证操作")
        logging.info(f"      - 应用: {app_name}")
        logging.info(f"      - 类型: {forensics_type}")

        try:
            # 根据取证类型调用相应的取证脚本
            if forensics_type == "whatsapp_chat" or app_name.lower() == "whatsapp":
                logging.info(f"    📱 调用 WhatsApp 取证脚本...")

                # 动态导入取证脚本
                try:
                    from runner.forensiflow.scripts import WhatsAppUniversalExtractor

                    # 获取设备序列号
                    device_serial = getattr(self.device, 'device_id', '')

                    # 创建提取器实例
                    extractor = WhatsAppUniversalExtractor(device_serial=device_serial)

                    # 执行取证
                    logging.info(f"    ⏳ 正在提取 WhatsApp 聊天记录，这可能需要较长时间...")
                    extractor.browse_and_extract()

                    # 获取输出文件路径
                    output_file = extractor.output_file

                    logging.info(f"    ✓ WhatsApp 取证完成")
                    logging.info(f"      - 输出文件: {output_file}")

                    # 记录到 reacts
                    self.reacts.append({
                        "reasoning": f"执行 WhatsApp 取证，提取聊天记录到 {output_file}",
                        "function": {
                            "name": "forensics",
                            "parameters": {
                                "app": app_name,
                                "type": forensics_type,
                                "output_file": output_file
                            }
                        },
                        "action_index": self.step
                    })

                    return True

                except ImportError as e:
                    logging.error(f"    ✗ 无法导入 WhatsApp 取证脚本: {e}")
                    logging.error(f"    💡 提示：请确保脚本位于 runner/forensiflow/scripts/whatsapp_raw_extractor.py")
                    return False

            elif forensics_type == "wechat_chat" or app_name.lower() in ["wechat", "微信"]:
                logging.warning(f"    ⚠️ 微信取证功能尚未实现")
                return False

            else:
                logging.warning(f"    ⚠️ 不支持的取证类型: {forensics_type}")
                return False

        except Exception as e:
            logging.error(f"    ✗ 取证操作失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _decide_action_with_llm(
        self,
        ui_elements: List[Dict[str, Any]],
        task_target: str,
        use_context_prompt: bool = False,
        current_action: str = "click",
        current_target: str = ""
    ) -> Dict[str, Any]:
        """
        使用语义匹配器 + LLM 决策操作

        流程：
        1. 先使用 BGE 语义匹配进行快速匹配
        2. 如果匹配成功（score >= 阈值），直接返回结果，跳过 LLM 调用
        3. 如果匹配失败，降级到 LLM 进行智能决策

        Args:
            ui_elements: VisionTasker 检测到的 UI 元素列表
            task_target: 当前步骤的目标（如"点击我的主页"）
            use_context_prompt: 是否使用包含完整上下文的提示词（用于步骤序列模式）
            current_action: 当前尝试的操作类型 (click/input/swipe)
            current_target: 当前尝试的目标元素

        Returns:
            决策字典，包含 action, target, reasoning
        """
        # 🎯 第一层：语义匹配（BGE 快速匹配）
        try:
            logging.info(f"\n{'='*60}")
            logging.info(f"🎯 步骤 1/2: 尝试语义匹配...")
            logging.info(f"   目标: {task_target}")
            logging.info(f"   候选数: {len(ui_elements)}")
            logging.info(f"{'='*60}\n")

            # 提取关键目标文本（去除动作前缀）
            target_text = task_target
            for prefix in ["点击", "输入", "滑动", "查找"]:
                if target_text.startswith(prefix):
                    target_text = target_text[len(prefix):]
                    break

            # 检查是否有语义匹配器可用
            if hasattr(self.semantic_matcher, 'model'):
                # 使用 BGE 匹配
                from runner.forensiflow.core.semantic_matcher import MatchResult

                match_result = self.semantic_matcher._bge_match(target_text, ui_elements)

                # 检查分数是否达标
                if match_result.score >= self.semantic_matcher.threshold:
                    # 适配 VisionTasker 格式
                    element_text = match_result.element.get('text_content') or 'Unknown'
                    logging.info(f"✅ 语义匹配成功!")
                    logging.info(f"   匹配元素: {element_text}")
                    logging.info(f"   相似度: {match_result.score:.3f} >= {self.semantic_matcher.threshold}")
                    logging.info(f"   跳过 LLM 调用")

                    # 保存语义匹配详细结果
                    try:
                        match_result_data = {
                            "success": True,
                            "score": match_result.score,
                            "threshold": self.semantic_matcher.threshold,
                            "matched_element": {
                                "text": element_text,
                                "class": match_result.element.get('class', 'Unknown'),
                                "id": match_result.element.get('id', 'Unknown'),
                                "location": match_result.element.get('location', {})
                            },
                            "method": "bge"
                        }

                        # 只保存 Top-10 候选（避免文件过大）
                        top_candidates = match_result.all_candidates[:10] if match_result.all_candidates else []

                        self.storage_module.save_semantic_match_result(
                            step=self.step,
                            target=target_text,
                            match_result=match_result_data,
                            candidates=top_candidates
                        )
                    except Exception as e:
                        logging.warning(f"⚠️  保存语义匹配结果失败: {e}")

                    # 构造决策结果
                    return {
                        "action": current_action,
                        "target": element_text,
                        "reasoning": f"语义匹配成功 (BGE, score={match_result.score:.3f})",
                        "method": "semantic_match",
                        "element": match_result.element
                    }
                else:
                    logging.info(f"⚠️  语义匹配未达到阈值")
                    logging.info(f"   最高分: {match_result.score:.3f} < {self.semantic_matcher.threshold}")
                    logging.info(f"   降级到 LLM 决策")

                    # 保存未达标的匹配结果
                    try:
                        match_result_data = {
                            "success": False,
                            "score": match_result.score,
                            "threshold": self.semantic_matcher.threshold,
                            "reason": "Score below threshold",
                            "matched_element": {
                                "text": match_result.element.get('text_content', 'Unknown'),
                                "class": match_result.element.get('class', 'Unknown'),
                                "id": match_result.element.get('id', 'Unknown'),
                                "location": match_result.element.get('location', {})
                            },
                            "method": "bge"
                        }

                        top_candidates = match_result.all_candidates[:10] if match_result.all_candidates else []

                        self.storage_module.save_semantic_match_result(
                            step=self.step,
                            target=target_text,
                            match_result=match_result_data,
                            candidates=top_candidates
                        )
                    except Exception as e:
                        logging.warning(f"⚠️  保存语义匹配结果失败: {e}")

        except Exception as e:
            logging.warning(f"⚠️  语义匹配失败: {e}，降级到 LLM")
            import traceback
            traceback.print_exc()

        # 🤖 第二层：LLM 智能决策
        logging.info(f"\n{'='*60}")
        logging.info(f"🤖 步骤 2/2: 调用 LLM 进行智能决策...")
        logging.info(f"{'='*60}\n")

        if not self.planner_client:
            raise RuntimeError("Planner client not initialized")

        # 1. 转换 UI 元素为描述
        ui_description = self._ui_elements_to_description(ui_elements)

        # 2. 根据模式选择不同的提示词构建方法
        if use_context_prompt and self._planned_steps:
            # 使用包含完整上下文的提示词
            prompt = self._build_step_context_prompt(
                current_action=current_action,
                current_target=current_target,
                ui_description=ui_description
            )
        else:
            # 使用原始格式的 prompt
            prompt = self._build_planner_prompt(
                task=task_target,
                ui_description=ui_description,
                history=""  # 步骤序列模式不使用历史
            )

        logging.info(f"\n{'='*60}")
        logging.info(f"    📤 发送给 LLM 的提示词 (Step {self.step}):")
        logging.info(f"{'='*60}")
        logging.info(f"{prompt}")
        logging.info(f"{'='*60}\n")

        # 3. 构建消息（使用原始格式）
        messages = self._build_visiontasker_messages(prompt)

        # 4. 调用 LLM
        response = self.planner_client.chat.completions.create(
            model=self.planner_model,
            messages=messages,
            temperature=0.3,
            top_p=0.7
        )

        # 5. 解析响应
        decision_text = response.choices[0].message.content

        logging.info(f"\n{'='*60}")
        logging.info(f"    📥 LLM 的响应 (Step {self.step}):")
        logging.info(f"{'='*60}")
        logging.info(f"{decision_text}")
        logging.info(f"{'='*60}\n")

        # 6. 解析决策
        decision = self._parse_planner_response(decision_text)

        logging.info(f"    📊 解析后的决策:")
        logging.info(f"       - Action: {decision.get('action', 'unknown')}")
        logging.info(f"       - Target: {decision.get('target', '(none)')}")
        logging.info(f"       - Reasoning: {decision.get('reasoning', '')}")
        logging.info(f"")

        return decision

    def run_task(
        self,
        app: str,
        old_task: str,
        task: str,
        max_steps: int = 35,
        bbox_flag: bool = True,
        use_abstract_task: bool = False  # 新增：是否使用抽象任务模式
    ) -> Dict[str, Any]:
        """
        Run a complete task execution loop.

        Args:
            app: Application name (可忽略，如果使用抽象任务模式)
            old_task: Original task description
            task: Current task description（可以是抽象任务，如"打开微信朋友圈"）
            max_steps: Maximum number of steps to execute
            bbox_flag: Whether to use bbox for grounding (not used in VT mode)
            use_abstract_task: 是否使用抽象任务模式（True=先规划+启动应用+执行步骤序列）

        Returns:
            Dictionary with execution results
        """
        # Create timestamped subdirectory for this run
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_data_dir = str(pathlib.Path(self.data_dir).resolve() / f"run_{timestamp}")
        os.makedirs(self.run_data_dir, exist_ok=True)

        # Also create subdirectories for VisionTasker output
        for subdir in ['ocr', 'ip', 'yolo', 'clip', 'workflow']:
            os.makedirs(os.path.join(self.run_data_dir, subdir), exist_ok=True)

        logging.info(f"\n{'='*60}")
        logging.info(f"📁 本次运行数据将保存到: {self.run_data_dir}")
        logging.info(f"{'='*60}\n")

        # 更新 storage_module 的目录到本次运行目录
        self.storage_module.data_dir = self.run_data_dir

        # Reset state
        self.history = []
        self.actions = []
        self.reacts = []
        self.step = 0

        # 抽象任务模式：LLM 拆分任务为步骤序列，然后逐步执行
        if use_abstract_task:
            logging.info(f"\n{'='*60}")
            logging.info(f"🔄 步骤序列模式")
            logging.info(f"原始任务: {task}")
            logging.info(f"{'='*60}\n")

            try:
                # 1. LLM 任务规划 + 应用识别 + 步骤拆分
                plan_result = self._plan_task_with_app(task)

                # 2. 启动应用（兼容新格式 app 和旧格式 app_name）
                app_name = plan_result.get('app') or plan_result.get('app_name')
                steps = plan_result['steps']

                # 初始化任务上下文管理
                self._original_task = task
                self._planned_steps = steps
                self._current_step_index = 0
                self._failed_attempts = []

                logging.info(f"\n{'='*60}")
                logging.info(f"📱 启动应用: {app_name}")
                logging.info(f"{'='*60}\n")

                self.device.start_app(app_name)

                # 3. 等待应用加载
                logging.info(f"⏳ 等待应用加载...")
                import time
                time.sleep(5)  # 等待应用启动

                logging.info(f"✓ 应用已启动\n")

                # 4. 加载 VisionTasker 模型（仅在需要时加载，作为 fallback）
                self._load_visiontasker_models()

                # 5. 逐步执行步骤序列
                logging.info(f"\n{'='*60}")
                logging.info(f"🚀 开始执行步骤序列（共 {len(steps)} 步）")
                logging.info(f"{'='*60}\n")

                for i, step in enumerate(steps):
                    # 更新当前步骤索引
                    self._current_step_index = i

                    self.step = i + 1
                    action = step.get("action", "")

                    logging.info(f"\n{'─'*60}")
                    logging.info(f"步骤 {self.step}/{len(steps)}: {action.upper()}")
                    logging.info(f"{'─'*60}\n")

                    # 执行步骤
                    success = self._execute_predefined_step(step)

                    if not success:
                        logging.error(f"✗ 步骤 {self.step} 执行失败，停止任务")
                        break

                    # 步骤成功后清空失败尝试记录
                    self._failed_attempts = []

                    # 记录动作
                    self.actions.append({
                        "type": action,
                        "step": self.step,
                        "action_index": self.step
                    })

                logging.info(f"\n{'='*60}")
                logging.info(f"✓ 步骤序列执行完成")
                logging.info(f"{'='*60}\n")

                # 6. 检查任务是否完成，如果未完成则继续规划并执行
                max_completion_checks = 10  # 最多检查 10 次，防止无限循环
                completion_check_count = 0
                task_completed = False

                while completion_check_count < max_completion_checks:
                    completion_check_count += 1

                    logging.info(f"\n{'='*60}")
                    logging.info(f"🔄 任务完成检查 #{completion_check_count}/{max_completion_checks}")
                    logging.info(f"{'='*60}\n")

                    # 调用 planner 判断任务是否完成
                    check_result = self._check_task_completion_and_plan_next()

                    if check_result["completed"]:
                        logging.info(f"✓ 任务已完成: {check_result['reasoning']}")
                        task_completed = True
                        break
                    else:
                        logging.info(f"⚠️ 任务未完成: {check_result['reasoning']}")

                        # 获取 planner 生成的新步骤
                        new_steps = check_result["new_steps"]

                        if not new_steps:
                            logging.warning(f"⚠️ LLM 判断任务未完成，但没有生成新步骤，停止任务")
                            break

                        logging.info(f"\n{'='*60}")
                        logging.info(f"📋 执行新步骤（共 {len(new_steps)} 步）")
                        logging.info(f"{'='*60}\n")

                        # 更新 planned_steps 为新步骤
                        self._planned_steps = new_steps
                        self._current_step_index = 0
                        self._failed_attempts = []

                        # 执行新步骤
                        for i, step in enumerate(new_steps):
                            # 更新当前步骤索引
                            self._current_step_index = i

                            self.step = len(self.actions) + 1
                            action = step.get("action", "")

                            logging.info(f"\n{'─'*60}")
                            logging.info(f"新步骤 {i+1}/{len(new_steps)}: {action.upper()}")
                            logging.info(f"{'─'*60}\n")

                            # 执行步骤
                            success = self._execute_predefined_step(step)

                            if not success:
                                logging.error(f"✗ 步骤执行失败，停止任务")
                                break

                            # 步骤成功后清空失败尝试记录
                            self._failed_attempts = []

                            # 记录动作
                            self.actions.append({
                                "type": action,
                                "step": self.step,
                                "action_index": self.step
                            })

                        logging.info(f"\n{'='*60}")
                        logging.info(f"✓ 新步骤序列执行完成")
                        logging.info(f"{'='*60}\n")

                        # 继续下一轮检查

                if completion_check_count >= max_completion_checks:
                    logging.warning(f"⚠️ 达到最大检查次数 ({max_completion_checks})，停止任务")

                # 保存最终结果
                self.storage_module.save_actions(app_name, old_task, task, self.actions)
                self.storage_module.save_reacts(self.reacts)

                return {
                    "completed": True,
                    "total_steps": len(self.actions),
                    "actions": self.actions,
                    "reacts": self.reacts,
                    "data_dir": self.run_data_dir
                }

            except Exception as e:
                logging.error(f"✗ 任务执行失败: {e}")
                import traceback
                traceback.print_exc()
                return {
                    "completed": False,
                    "total_steps": len(self.actions),
                    "actions": self.actions,
                    "reacts": self.reacts,
                    "data_dir": self.run_data_dir,
                    "error": f"Failed to execute task: {e}"
                }
            finally:
                # 释放 VisionTasker 模型资源
                self._unload_visiontasker_models()

        # 原有的逐步决策模式（保留兼容性）
        # 加载 VisionTasker 模型（整个任务期间只加载一次）
        if not self._load_visiontasker_models():
            return {
                "completed": False,
                "total_steps": 0,
                "actions": [],
                "reacts": [],
                "data_dir": self.run_data_dir,
                "error": "Failed to load VisionTasker models"
            }

        try:
            # Main execution loop
            while self.step < max_steps:
                self.step += 1

                # Execute each step in the pipeline
                result = self._execute_step_pipeline(
                    app,
                    old_task,
                    task
                )

                # Check if task is completed
                if result.get("completed"):
                    break

                # Check if should stop
                if result.get("stop"):
                    break

        finally:
            # 释放 VisionTasker 模型资源
            self._unload_visiontasker_models()

        # Save final results
        self.storage_module.save_actions(app, old_task, task, self.actions)
        self.storage_module.save_reacts(self.reacts)

        return {
            "completed": result.get("completed", False),
            "total_steps": len(self.actions),
            "actions": self.actions,
            "reacts": self.reacts,
            "data_dir": self.run_data_dir
        }

    def _execute_step_pipeline(
        self,
        app: str,
        old_task: str,
        task: str
    ) -> Dict[str, Any]:
        """
        Execute a single step through the pipeline.

        Args:
            app: App name
            old_task: Original task
            task: Current task

        Returns:
            Step result dictionary
        """
        context = {
            "step": self.step,
            "app": app,
            "old_task": old_task,
            "task": task,
            "history": self.history
        }

        # Execute each configured step
        for step_config in self.steps:
            if not step_config.enabled:
                continue

            # Pre-wait
            if step_config.pre_wait > 0:
                time.sleep(step_config.pre_wait)

            # Execute step
            context = self._execute_step(
                step_config.name,
                context
            )

            # Post-wait
            if step_config.post_wait > 0:
                time.sleep(step_config.post_wait)

            # Check for completion
            if context.get("completed") or context.get("stop"):
                break

        return {
            "completed": context.get("completed", False),
            "stop": context.get("stop", False)
        }

    def _execute_step(
        self,
        step_name: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a single step.

        Args:
            step_name: Name of the step to execute
            context: Current context

        Returns:
            Updated context
        """
        # Check for custom handler
        if step_name in self.custom_handlers:
            return self.custom_handlers[step_name](context)

        # Default step handlers
        if step_name == "screenshot":
            return self._step_screenshot(context)
        elif step_name == "ui_detection":
            return self._step_ui_detection(context)
        elif step_name == "planning":
            return self._step_planning(context)
        elif step_name == "xml_matching":
            return self._step_xml_matching(context)
        elif step_name == "element_matching":
            return self._step_element_matching(context)
        elif step_name == "execute":
            return self._step_execute(context)
        elif step_name == "store":
            return self._step_store(context)
        else:
            logging.warning(f"Unknown step: {step_name}")
            return context

    def _step_screenshot(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute screenshot step."""
        logging.info(f"    Capturing screenshot from {self.device_type} device...")
        screenshot_data = self.screenshot_module.capture(self.device, self.device_type)

        # Save original screenshot to run-specific directory
        save_path = os.path.join(self.run_data_dir, f"{self.step}.jpg")
        self.screenshot_module.save_original(self.device, self.device_type, save_path)

        # 更新 screenshot_data 中的路径为实际保存的路径
        screenshot_data["path"] = save_path
        context["screenshot"] = screenshot_data

        logging.info(f"    ✓ Screenshot saved to: {save_path}")

        return context

    def _step_ui_detection(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute UI detection step using VisionTasker（直接调用，模型已常驻内存）."""
        logging.info(f"    Running VisionTasker UI detection...")

        # 检查模型是否已加载
        if not self._vt_models_loaded or self._vt_process_img is None:
            logging.error("    VisionTasker models not loaded!")
            context["ui_detection_error"] = "Models not loaded"
            context["stop"] = True
            return context

        try:
            # Use run-specific directory
            screenshot_path = os.path.join(self.run_data_dir, f"{self.step}.jpg")
            ui_json_path = os.path.join(self.run_data_dir, f"ui_{self.step}.json")

            # 检查截图文件是否存在
            if not os.path.exists(screenshot_path):
                raise FileNotFoundError(f"截图文件不存在: {screenshot_path}")

            logging.info(f"    Screenshot: {screenshot_path}")
            logging.info(f"    Output JSON: {ui_json_path}")

            # 直接调用 process_img 函数（模型已在内存中）
            import time
            start_time = time.time()

            # 临时切换到 VisionTasker 目录（process_img 内部使用相对路径）
            original_cwd = os.getcwd()
            os.chdir(self._vt_module_path)

            try:
                # 解包模型
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._vt_models

                # 调用检测函数
                result_js = self._vt_process_img(
                    label_path_dir=self._vt_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._vt_high_conf_flag,
                    alg=self._vt_alg,
                    clean_save=self._vt_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._vt_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._vt_ocr_output_only,
                    workflow_only=self._vt_workflow_only,
                    accurate_ocr=self._vt_accurate_ocr
                )
            finally:
                # 恢复工作目录
                os.chdir(original_cwd)

            elapsed_time = time.time() - start_time
            logging.info(f"    ✓ Detection completed in {elapsed_time:.2f}s")

            # 保存 JSON 文件
            with open(ui_json_path, 'w', encoding='utf-8') as f:
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            context["ui_json"] = result_js
            context["ui_elements"] = result_js if isinstance(result_js, list) else []

            logging.info(f"    ✓ VisionTasker detected {len(context['ui_elements'])} elements")
            logging.info(f"    ✓ UI JSON saved to: {ui_json_path}")

        except Exception as e:
            logging.error(f"    UI detection failed: {e}")
            context["ui_detection_error"] = str(e)
            import traceback
            traceback.print_exc()
            # 连续失败太多就停止
            if not hasattr(self, '_ui_detection_failures'):
                self._ui_detection_failures = 0
            self._ui_detection_failures += 1
            if self._ui_detection_failures >= 3:
                logging.error("    UI detection failed 3 times in a row, stopping...")
                context["stop"] = True

        return context

    def _step_planning(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute planning step using ChatGLM API."""
        if not self.planner_client:
            logging.warning("    Planner client not initialized, skipping planning")
            return context

        logging.info(f"    Calling ChatGLM API for decision...")

        try:
            # Convert UI elements to natural language description
            ui_elements = context.get("ui_elements", [])

            # 调试：检查 UI elements 的类型和内容
            logging.info(f"    🔍 UI elements 类型: {type(ui_elements)}, 数量: {len(ui_elements) if isinstance(ui_elements, list) else 'N/A'}")

            ui_description = self._ui_elements_to_description(ui_elements)

            # 调试：显示 UI description 的前 200 个字符
            if len(ui_description) > 200:
                logging.info(f"    🔍 UI description (前 200 字): {ui_description[:200]}...")
            else:
                logging.info(f"    🔍 UI description: {ui_description}")

            # Build VisionTasker-style prompt
            prompt = self._build_planner_prompt(
                task=context["task"],
                ui_description=ui_description,
                history=""
            )

            # 详细日志：发送给 ChatGLM 的提示词
            logging.info(f"\n{'='*60}")
            logging.info(f"    📤 发送给 ChatGLM 的提示词 (Step {self.step}):")
            logging.info(f"{'='*60}")
            logging.info(f"{prompt}")
            logging.info(f"{'='*60}\n")

            # 构建 VisionTasker 风格的消息（包含 Few-shot Learning）
            messages = self._build_visiontasker_messages(prompt)

            # Call ChatGLM API
            response = self.planner_client.chat.completions.create(
                model=self.planner_model,
                messages=messages,
                temperature=0.3,  # 降低温度以获得更确定的输出
                top_p=0.7
            )

            # Parse response
            decision_text = response.choices[0].message.content

            # 详细日志：ChatGLM 的响应
            logging.info(f"\n{'='*60}")
            logging.info(f"    📥 ChatGLM 的响应 (Step {self.step}):")
            logging.info(f"{'='*60}")
            logging.info(f"{decision_text}")
            logging.info(f"{'='*60}\n")

            # 解析响应
            decision = self._parse_planner_response(decision_text)

            # 详细日志：解析后的决策
            logging.info(f"    📊 解析后的决策:")
            logging.info(f"       - Action: {decision.get('action', 'unknown')}")
            logging.info(f"       - Target: {decision.get('target', '(none)')}")
            logging.info(f"       - Parameters: {decision.get('parameters', {})}")
            logging.info(f"       - Reasoning: {decision.get('reasoning', '')}")
            logging.info(f"")

            context["decision"] = decision
            context["action"] = decision.get("action", "unknown")
            context["target"] = decision.get("target", "")
            context["reasoning"] = decision.get("reasoning", "")

            logging.info(f"    ✓ Decision: {decision.get('action', 'unknown').upper()}")
            if decision.get('target'):
                logging.info(f"    ✓ Target: {decision.get('target')}")
            if decision.get('reasoning'):
                logging.info(f"    ✓ Reasoning: {decision.get('reasoning')}")

            # Add to reacts
            self.reacts.append({
                "reasoning": decision.get("reasoning", ""),
                "function": {
                    "name": decision.get("action", "unknown"),
                    "parameters": decision.get("parameters", {})
                },
                "action_index": self.step
            })

            # Check for completion
            if decision.get("action", "").lower() in ["done", "stop", "terminate", "完成"]:
                self.actions.append({
                    "type": "done",
                    "action_index": self.step
                })
                context["completed"] = True
                # VisionTasker 格式：不记录完成操作到历史
            else:
                # 记录操作历史（VisionTasker 格式）
                action = decision.get("action", "")
                target = decision.get("target", "")
                params = decision.get("parameters", {})

                if action == "click" and target:
                    # 点击：`（点击['QQ']）`
                    history_entry = f"点击了['{target}']"
                    self.history.append(history_entry)
                elif action == "input" and target:
                    # 输入：`（在输入框:['搜索']输入（'设置'）并回车）`
                    input_text = params.get("text", "")
                    history_entry = f"在输入框:['{target}']输入（'{input_text}'）并回车"
                    self.history.append(history_entry)
                elif action == "swipe":
                    # 滑动：`（向下滑动）`
                    direction = params.get("direction", "")
                    direction_str = {
                        "up": "上",
                        "down": "下",
                        "left": "左",
                        "right": "右"
                    }.get(direction, direction)
                    history_entry = f"向{direction_str}滑动"
                    self.history.append(history_entry)

        except Exception as e:
            logging.error(f"    Planning failed: {e}")
            context["planning_error"] = str(e)
            import traceback
            traceback.print_exc()

        return context

    def _step_xml_matching(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute XML matching step for fast text-based element matching.

        This step attempts to match elements using XML hierarchy before falling back
        to VisionTasker's vision-based matching.
        """
        action = context.get("action", "").lower()

        # Only match for click actions (fast path for clicks)
        if action != "click":
            logging.info(f"    Skipping XML matching for action: {action}")
            return context

        target = context.get("target", "")
        if not target:
            logging.warning("    No target specified for XML matching")
            return context

        logging.info(f"    🔍 XML Matching: Looking for '{target}'")

        try:
            # 1. Dump XML from device and save to data directory
            xml_path = os.path.join(self.run_data_dir, f"hierarchy_{self.step}.xml")

            logging.info(f"    📄 Dumping XML to: {xml_path}")
            xml_content = self.device.dump_xml(xml_path)

            context["xml_path"] = xml_path
            context["xml_content"] = xml_content

            # 2. Parse XML and find matching element
            matched_element = self._find_element_in_xml(xml_content, target)

            if matched_element:
                # Extract bounds
                bounds = matched_element.get("bounds", {})
                if bounds:
                    # Calculate center point
                    left = bounds.get("left", 0)
                    top = bounds.get("top", 0)
                    right = bounds.get("right", 0)
                    bottom = bounds.get("bottom", 0)

                    center_x = (left + right) // 2
                    center_y = (top + bottom) // 2

                    context["grounding_result"] = {
                        "position": (center_x, center_y),
                        "bounds": (left, top, right, bottom),
                        "method": "xml",
                        "confidence": 1.0,
                        "matched_text": matched_element.get("text", ""),
                        "matched_class": matched_element.get("class", "")
                    }

                    logging.info(f"    ✓ XML Matched '{target}' at ({center_x}, {center_y})")
                    logging.info(f"      - Text: {matched_element.get('text', '')}")
                    logging.info(f"      - Class: {matched_element.get('class', '')}")
                    logging.info(f"      - Bounds: {bounds}")

                    # Mark as matched to skip VisionTasker matching
                    context["xml_matched"] = True
                else:
                    logging.warning(f"    XML element found but no bounds: {matched_element}")
                    context["xml_matched"] = False
            else:
                logging.info(f"    XML matching failed, will try VisionTasker...")
                context["xml_matched"] = False

        except Exception as e:
            logging.error(f"    XML matching failed: {e}")
            context["xml_matched"] = False
            context["xml_matching_error"] = str(e)
            import traceback
            traceback.print_exc()

        return context

    def _step_element_matching(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute element matching step.

        Directly extracts position from VisionTasker JSON instead of using element_matcher.
        This is a fallback step if XML matching failed.
        """
        # Skip if XML matching already succeeded
        if context.get("xml_matched"):
            logging.info(f"    Element already matched by XML, skipping VisionTasker matching")
            return context

        action = context.get("action", "").lower()

        # Only match for click and input actions
        if action not in ["click", "input"]:
            logging.info(f"    Skipping element matching for action: {action}")
            return context

        target = context.get("target", "")
        if not target:
            logging.warning("    No target specified for element matching")
            return context

        logging.info(f"    🔍 VisionTasker Matching: Looking for '{target}' (XML fallback)")

        try:
            # 从 VisionTasker JSON 中查找匹配的元素
            matched_element = self._find_element_by_text(
                context.get("ui_elements", []),
                target
            )

            if matched_element:
                # 提取位置信息
                location = matched_element.get("location", {})
                if location:
                    # 计算中心点
                    left = location.get("left", 0)
                    top = location.get("top", 0)
                    right = location.get("right", 0)
                    bottom = location.get("bottom", 0)

                    center_x = (left + right) // 2
                    center_y = (top + bottom) // 2

                    context["grounding_result"] = {
                        "position": (center_x, center_y),
                        "bounds": (left, top, right, bottom),
                        "method": "visiontasker",
                        "confidence": 1.0
                    }
                    logging.info(f"    ✓ VisionTasker matched '{target}' at ({center_x}, {center_y})")
                else:
                    logging.warning(f"    Element '{target}' has no location info")
                    context["match_failed"] = True
            else:
                logging.warning(f"    Element '{target}' not found in UI")
                context["match_failed"] = True

        except Exception as e:
            logging.error(f"    Element matching failed: {e}")
            context["matching_error"] = str(e)

        return context

    def _find_element_by_text(self, ui_elements, target_text):
        """从 VisionTasker JSON 中查找匹配的元素.

        Args:
            ui_elements: VisionTasker 返回的元素列表
            target_text: 目标文本描述

        Returns:
            匹配的元素字典，未找到返回 None
        """
        def search_elements(elements):
            for element in elements:
                # 跳过字符串元素
                if not isinstance(element, dict):
                    continue

                # 检查当前元素是否匹配
                if element.get("class") in ["Compo", "Text"]:
                    text_content = element.get("text_content", "")
                    sub_class = element.get("sub_class", "")

                    # 尝试多种匹配方式
                    # 1. 精确匹配 text_content
                    if text_content and text_content.strip() == target_text.strip():
                        return element

                    # 2. 包含匹配（目标文本在 text_content 中）
                    if text_content and target_text.strip() in text_content.strip():
                        return element

                    # 3. 包含匹配（text_content 在目标文本中）
                    if text_content and text_content.strip() in target_text.strip():
                        return element

                    # 4. 匹配 sub_class
                    if sub_class and sub_class.strip() == target_text.strip():
                        return element

                # 递归搜索 children
                if "children" in element and isinstance(element["children"], list):
                    result = search_elements(element["children"])
                    if result:
                        return result

            return None

        return search_elements(ui_elements)

    def _find_element_in_xml(self, xml_content, target_text):
        """从 Android UI XML 中查找匹配的元素.

        Args:
            xml_content: Android dump_hierarchy 返回的 XML 字符串
            target_text: 目标文本描述

        Returns:
            匹配的元素字典，包含 text, class, bounds，未找到返回 None
        """
        import xml.etree.ElementTree as ET

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            logging.error(f"    Failed to parse XML: {e}")
            return None

        def parse_bounds(bounds_str):
            """解析 bounds 属性: [left,top][right,bottom]"""
            try:
                # 格式: [123,456][789,1011]
                import re
                matches = re.findall(r'\[(\d+),(\d+)\]', bounds_str)
                if len(matches) == 2:
                    left, top = int(matches[0][0]), int(matches[0][1])
                    right, bottom = int(matches[1][0]), int(matches[1][1])
                    return {"left": left, "top": top, "right": right, "bottom": bottom}
            except Exception as e:
                logging.debug(f"    Failed to parse bounds '{bounds_str}': {e}")
            return None

        def search_node(node):
            """递归搜索节点树"""
            # 获取节点的 text 属性
            text = node.get('text', '')
            content_description = node.get('content-description', '')
            resource_id = node.get('resource-id', '')

            # 检查各种文本属性
            target_lower = target_text.strip().lower()

            # 优先级 1: 精确匹配 text 属性
            if text and text.strip().lower() == target_lower:
                bounds = parse_bounds(node.get('bounds', ''))
                return {
                    "text": text,
                    "class": node.get('class', ''),
                    "bounds": bounds,
                    "resource_id": resource_id
                }

            # 优先级 2: 包含匹配 text 属性
            if text and target_lower in text.strip().lower():
                bounds = parse_bounds(node.get('bounds', ''))
                return {
                    "text": text,
                    "class": node.get('class', ''),
                    "bounds": bounds,
                    "resource_id": resource_id
                }

            # 优先级 3: 匹配 content-description
            if content_description and target_lower in content_description.strip().lower():
                bounds = parse_bounds(node.get('bounds', ''))
                return {
                    "text": content_description,
                    "class": node.get('class', ''),
                    "bounds": bounds,
                    "resource_id": resource_id
                }

            # 优先级 4: 匹配 resource-id（简化版，取最后一个部分）
            if resource_id:
                id_parts = resource_id.split('/')
                if len(id_parts) > 1:
                    id_name = id_parts[-1].lower()
                    if target_lower in id_name or id_name in target_lower:
                        bounds = parse_bounds(node.get('bounds', ''))
                        return {
                            "text": text or resource_id,
                            "class": node.get('class', ''),
                            "bounds": bounds,
                            "resource_id": resource_id
                        }

            # 递归搜索子节点
            for child in node:
                result = search_node(child)
                if result:
                    return result

            return None

        return search_node(root)

    def _step_execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute action step."""
        action = context.get("action", "").lower()

        # Skip execution for terminal actions
        if action in ["done", "stop", "terminate"]:
            logging.info(f"    Terminal action '{action.upper()}', stopping execution")
            return context

        # Skip if matching failed
        if context.get("match_failed"):
            logging.warning("    Skipping execution due to matching failure")
            return context

        # Skip if no grounding_result for click/input actions
        if action in ["click", "input"]:
            if not context.get("grounding_result"):
                logging.warning(f"    Skipping {action} action: no grounding result available")
                return context

        # Execute action
        if action in ["click", "input", "swipe", "wait"]:
            logging.info(f"    Executing {action.upper()} action on device...")

            execution_result = self.executor_module.execute(
                action,
                context.get("decision", {}).get("parameters", {}),
                context.get("grounding_result")
            )
            execution_result["action_index"] = self.step
            context["execution_result"] = execution_result
            self.actions.append(execution_result)

            # 注意：不将 reasoning 添加到 history，避免污染提示词
            # history 只包含实际执行的操作（在 _step_planning 中已添加）

            logging.info(f"    Action executed successfully")

        return context

    def _step_store(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute storage step (already handled in main loop)."""
        return context

    def _ui_elements_to_description(self, ui_elements: List[Dict[str, Any]]) -> str:
        """
        Convert UI elements to VisionTasker-style hierarchical description.

        VisionTasker format:
        第1行 - 从左到右为以下控件:
            ['按钮1']； ['按钮2']； 输入框: ['默认文本:']；
        第2行 - 从左到右为以下控件:
            ['按钮3']； ['按钮4']；
        """
        if not ui_elements:
            return "当前界面为空"

        # 处理第一个元素：alignment 字符串
        alignment = "v"  # 默认垂直
        if isinstance(ui_elements[0], str) and "alignment:" in ui_elements[0]:
            alignment = ui_elements[0].split(":")[1].strip()

        # 递归转换函数
        def convert_element(element, level=0, line_num=1, parent_alignment="v"):
            if not isinstance(element, dict):
                return "", line_num

            elem_class = element.get("class", "")
            elem_id = element.get("id", "")

            # 处理 Block 元素（容器）
            if elem_class == "Block" and elem_id.startswith("b-"):
                # Block 会改变布局方向
                block_alignment = element.get("alignment", "h")
                direction_str = "从左到右" if block_alignment == "h" else "从上到下"

                # 计算缩进
                indent = "    " * level
                output = f"{indent}第{line_num}行 - {direction_str}为以下控件:\n"

                # 递归处理子元素
                if "children" in element and isinstance(element["children"], list):
                    for child in element["children"]:
                        child_output, line_num = convert_element(
                            child, level + 1, line_num, block_alignment
                        )
                        output += child_output

                return output, line_num + 1

            # 处理 Compo/Text 元素（具体控件）
            elif elem_class in ["Compo", "Text"]:
                text_content = element.get("text_content", "")
                sub_class = element.get("sub_class", "")

                # 优先使用 text_content
                if not text_content:
                    display_text = sub_class
                else:
                    display_text = text_content

                # 计算缩进
                indent = "    " * level

                # 检查是否为输入框
                if sub_class in ["edittext", "autocompletetextview"]:
                    output = f"{indent}输入框: ['{display_text}']；"
                else:
                    output = f"{indent}['{display_text}']；"

                return output + "\n", line_num

            # 处理 List 元素
            elif elem_class == "List" and elem_id.startswith("l-"):
                list_alignment = element.get("list_alignment", "h")
                direction_str = "从左到右" if list_alignment == "h" else "从上到下"

                indent = "    " * level
                output = f"{indent}第{line_num}行 - {direction_str}为以下控件:\n"

                # 递归处理 list_items
                if "list_items" in element and isinstance(element["list_items"], list):
                    for list_item in element["list_items"]:
                        for item_element in list_item:
                            child_output, line_num = convert_element(
                                item_element, level + 1, line_num, list_alignment
                            )
                            output += child_output

                return output, line_num + 1

            return "", line_num

        # 转换所有元素
        result = ""
        current_line = 1

        for element in ui_elements[1:]:  # 跳过第一个 alignment 字符串
            output, current_line = convert_element(element, 0, current_line, alignment)
            result += output

        return result.strip() if result else "未检测到可交互的 UI 元素"

    def _build_planner_prompt(
        self,
        task: str,
        ui_description: str,
        history: str
    ) -> str:
        """
        Build VisionTasker-style prompt with Few-shot Learning examples.

        Format: Q：任务描述，历史操作，当前界面有以下按钮：...
               A：tap_action: 点击['xxx']
                  或 input_action: 在输入框:['xxx']输入（"yyy"）并回车
                  或 end_action: 任务已完成
        """
        # 构建历史操作字符串
        if not self.history:
            history_str = ""
        else:
            history_str = "，现在已经" + "，然后".join(self.history)

        return f"""Q：{task}{history_str}，当前界面有以下按钮：
{ui_description}"""

    def _build_step_context_prompt(
        self,
        current_action: str,
        current_target: str,
        ui_description: str
    ) -> str:
        """
        构建包含完整任务上下文的提示词（用于步骤序列模式的 XML 失败场景）

        Args:
            current_action: 当前尝试的操作类型 (click/input/swipe)
            current_target: 当前尝试的目标元素
            ui_description: 当前界面元素描述

        Returns:
            str: 包含完整上下文的提示词

        提示词结构：
        - 原始任务
        - 已完成的步骤
        - 当前步骤目标
        - 剩余待执行的步骤
        - XML 匹配失败的尝试记录
        - 当前界面描述
        """
        # 1. 构建已完成步骤的描述
        completed_steps_desc = [
            self._build_step_description(step, i+1)
            for i, step in enumerate(self._planned_steps[:self._current_step_index])
        ]
        completed_str = "\n".join(completed_steps_desc) if completed_steps_desc else "（无）"

        # 2. 构建当前步骤的描述
        current_step_str = self._build_step_description(
            self._planned_steps[self._current_step_index],
            self._current_step_index + 1
        )

        # 3. 构建剩余步骤的描述
        remaining_steps_desc = [
            self._build_step_description(step, i)
            for i, step in enumerate(self._planned_steps[self._current_step_index + 1:], start=self._current_step_index + 2)
        ]
        remaining_str = "\n".join(remaining_steps_desc) if remaining_steps_desc else "（无）"

        # 4. 构建失败尝试记录
        failed_attempts_desc = []
        for attempt in self._failed_attempts:
            attempt_action = attempt.get("action", "")
            attempt_target = attempt.get("target", "")
            attempt_method = attempt.get("method", "unknown")
            attempt_reason = attempt.get("reason", "")

            if attempt_action == "click":
                failed_attempts_desc.append(
                    f"- 尝试使用{attempt_method}点击'{attempt_target}'，失败原因: {attempt_reason}"
                )
            elif attempt_action == "input":
                text = attempt.get("text", "")
                failed_attempts_desc.append(
                    f"- 尝试使用{attempt_method}在'{attempt_target}'输入'{text}'，失败原因: {attempt_reason}"
                )

        failed_str = "\n".join(failed_attempts_desc) if failed_attempts_desc else "（无）"

        # 5. 组装完整提示词
        prompt = f"""【任务上下文】
原始任务: {self._original_task}

【已完成步骤】
{completed_str}

【当前步骤目标】
{current_step_str}
⚠️ 当前步骤遇到了困难：XML 匹配失败，需要你来决策如何完成这一步

【剩余待执行步骤】
{remaining_str}

【失败尝试记录】
{failed_str}

【当前界面状态】
{ui_description}

【请你决策】
根据以上上下文信息，判断当前界面是否已经满足当前步骤的目标。
- 如果已满足，输出：操作类型：done，决策理由：当前步骤已完成
- 如果未满足，请根据当前界面状态，决定下一步操作（可能需要滑动查找、点击、或输入等）

请严格按照上述格式输出："""

        return prompt

    # ==================== 辅助方法 ====================

    def _calculate_element_center(self, bounds: Dict[str, int]) -> tuple:
        """
        计算 UI 元素的中心点坐标

        Args:
            bounds: 包含 left, top, right, bottom 的字典

        Returns:
            (center_x, center_y) 元组
        """
        center_x = (bounds["left"] + bounds["right"]) // 2
        center_y = (bounds["top"] + bounds["bottom"]) // 2
        return center_x, center_y

    def _extract_json_from_response(self, response_text: str) -> dict:
        """
        从 LLM 响应中提取 JSON（统一的 JSON 解析方法）

        Args:
            response_text: LLM 响应文本

        Returns:
            解析后的字典

        Raises:
            ValueError: 如果无法找到有效的 JSON
        """
        # 尝试提取 ```json ... ``` 格式
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            return json.loads(json_str)

        # 尝试提取 { ... } 格式
        json_match = re.search(r'(\{.*?\})', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
            return json.loads(json_str)

        raise ValueError("无法在响应中找到有效的 JSON")

    def _build_step_description(self, step: Dict[str, Any], step_index: int) -> str:
        """
        构建步骤的描述字符串（统一步骤描述逻辑）

        Args:
            step: 步骤字典
            step_index: 步骤索引（从 1 开始）

        Returns:
            步骤描述字符串
        """
        action = step.get("action", "")
        target = step.get("target", "")
        params = step.get("params", {})

        if action == "click":
            return f"步骤{step_index}: 点击'{target}'"
        elif action == "input":
            text = params.get("text", "")
            return f"步骤{step_index}: 在'{target}'输入'{text}'"
        elif action == "swipe":
            direction = params.get("direction", "")
            return f"步骤{step_index}: 向{direction}滑动"
        elif action == "wait":
            duration = params.get("duration", 2)
            return f"步骤{step_index}: 等待{duration}秒"
        elif action == "forensics":
            app = params.get("app", "")
            ftype = params.get("type", "")
            return f"步骤{step_index}: 执行{app}取证({ftype})"
        else:
            return f"步骤{step_index}: {action}"

    def _build_visiontasker_messages(self, user_prompt: str) -> List[Dict[str, str]]:
        """
        Build messages with clear format requirements.

        Returns a list of message dictionaries with system prompt and examples.
        """
        messages = [
            {
                "role": "system",
                "content": """你是移动端 UI 自动化操作助手。

【重要原则】
- 每次只输出**当前一步**的操作，不要输出完整计划
- 这是一个迭代过程，你会被多次调用，每次只决定下一步做什么
- 不要预测未来步骤，只需根据当前界面状态决定下一步操作
- **禁止使用搜索功能，不要点击搜索框或搜索按钮**

【输出格式要求】
你必须严格按照以下格式输出，不要有任何额外文字：

操作类型：[click/input/done/swipe]
目标元素：[按钮文字，仅对 click/input]
输入内容：[输入文字，仅对 input]
滑动方向：[up/down/left/right，仅对 swipe]
决策理由：[为什么这样操作]

【示例】
操作类型：click
目标元素：返回
决策理由：点击返回按钮

操作类型：input
目标元素：默认文本: 搜索
输入内容：周杰伦演唱会
决策理由：在搜索框输入关键词

操作类型：done
决策理由：任务已完成"""
            },
            {
                "role": "user",
                "content": """Q：我想返回主页面，当前界面有以下按钮:
第1行 - 从左到右为以下控件:
 ['返回']； ['主页']； ['菜单']；"""
            },
            {
                "role": "assistant",
                "content": """操作类型：click
目标元素：返回
决策理由：点击返回按钮回到主页"""
            },
            {
                "role": "user",
                "content": """Q：我要搜索"周杰伦演唱会"，当前界面有以下按钮:
第1行 - 从左到右为以下控件:
 ['返回']； 输入框: ['默认文本: 搜索']； ['搜索按钮']；"""
            },
            {
                "role": "assistant",
                "content": """操作类型：input
目标元素：默认文本: 搜索
输入内容：周杰伦演唱会
决策理由：在搜索框输入关键词"""
            },
            {
                "role": "user",
                "content": """Q：任务已完成，当前界面有以下按钮:
第1行 - 从左到右为以下控件:
 ['完成']； ['关闭']；"""
            },
            {
                "role": "assistant",
                "content": """操作类型：done
决策理由：任务已完成"""
            },
            {
                "role": "user",
                "content": user_prompt + "\n\n请严格按照上述格式输出："
            }
        ]

        return messages

    def _parse_planner_response(self, response: str) -> Dict[str, Any]:
        """
        Parse LLM response - 支持多种格式：
        1. 键值对格式（优先）：操作类型：click\n目标元素：xxx
        2. JSON 格式：{"action": "click", "target": "xxx"}
        3. 自然语言格式（回退）
        """
        try:
            response_clean = response.strip()

            # 优先解析键值对格式
            if "操作类型：" in response_clean or "目标元素：" in response_clean:
                return self._parse_key_value_format(response_clean)

            # 尝试解析 JSON 格式
            if "```json" in response_clean:
                start = response_clean.find("```json") + 7
                end = response_clean.find("```", start)
                json_str = response_clean[start:end].strip()
                decision = json.loads(json_str)
                return decision

            elif response_clean.startswith("{"):
                decision = json.loads(response_clean)
                return decision

            # 回退到自然语言格式解析
            return self._parse_natural_language_response(response_clean)

        except Exception as e:
            logging.warning(f"响应解析失败: {e}，使用关键词匹配")
            return self._parse_natural_language_response(response.strip())

    def _parse_key_value_format(self, response: str) -> Dict[str, Any]:
        """解析键值对格式的响应

        如果响应中包含多个操作，只解析第一个有效的操作
        """
        try:
            result = {
                "action": "unknown",
                "target": "",
                "parameters": {},
                "reasoning": ""
            }

            lines = response.split('\n')

            # 找到第一个操作块（从"操作类型："到下一个"操作类型："或结束）
            first_action_found = False
            current_action = {
                "action": "unknown",
                "target": "",
                "parameters": {},
                "reasoning": ""
            }

            action_count = 0  # 统计操作数量

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # 如果遇到第二个"操作类型"，停止解析
                if line.startswith("操作类型：") or line.startswith("操作类型:"):
                    action_count += 1
                    if first_action_found:
                        # 已经找到第一个操作了，这里是第二个操作，停止
                        break
                    first_action_found = True

                    action_value = line.split('：', 1)[-1].split(':', 1)[-1].strip().lower()
                    action_map = {
                        "click": "click",
                        "点击": "click",
                        "input": "input",
                        "输入": "input",
                        "done": "done",
                        "完成": "done",
                        "swipe": "swipe",
                        "滑动": "swipe",
                        "wait": "wait",
                        "等待": "wait"
                    }
                    current_action["action"] = action_map.get(action_value, action_value)

                # 解析目标元素
                elif line.startswith("目标元素：") or line.startswith("目标元素:"):
                    current_action["target"] = line.split('：', 1)[-1].split(':', 1)[-1].strip()

                # 解析输入内容
                elif line.startswith("输入内容：") or line.startswith("输入内容:"):
                    text_value = line.split('：', 1)[-1].split(':', 1)[-1].strip()
                    current_action["parameters"]["text"] = text_value

                # 解析滑动方向
                elif line.startswith("滑动方向：") or line.startswith("滑动方向:"):
                    direction_value = line.split('：', 1)[-1].split(':', 1)[-1].strip().lower()
                    current_action["parameters"]["direction"] = direction_value

                # 解析决策理由
                elif line.startswith("决策理由：") or line.startswith("决策理由:"):
                    current_action["reasoning"] = line.split('：', 1)[-1].split(':', 1)[-1].strip()

            # 返回第一个操作（如果没有找到有效操作，返回空结果）
            if first_action_found:
                # 如果 LLM 输出了多个操作，记录警告
                if action_count > 1:
                    logging.warning(f"    ⚠️ LLM 输出了 {action_count} 个操作，但只应输出当前一步操作。已自动取第一个操作。")

                # 如果没有 reasoning，从 response 中提取
                if not current_action["reasoning"]:
                    current_action["reasoning"] = response[:200]
                return current_action
            else:
                # 没有找到操作类型，返回默认值
                return result

        except Exception as e:
            logging.warning(f"键值对格式解析失败: {e}")
            raise

    def _parse_natural_language_response(self, response: str) -> Dict[str, Any]:
        """解析自然语言格式的响应（回退方案）"""
        try:
            # 清理响应文本
            response_clean = response.strip()

            # 提取 action 类型
            action = "unknown"
            target = ""
            parameters = {}
            reasoning = ""

            # 检测操作类型
            if "tap_action" in response_clean or "点击" in response_clean:
                action = "click"
                # 提取目标
                import re
                match = re.search(r"点击\['(.+?)'\]|点击\【(.+?)\】|点击\「(.+?)\」", response_clean)
                if match:
                    target = match.group(1) or match.group(2) or match.group(3)
                else:
                    # 尝试从整行提取
                    match = re.search(r"点击.*?\[(.+?)\]", response_clean)
                    if match:
                        target = match.group(1)

                reasoning = f"点击[{target}]" if target else "点击操作"

            elif "input_action" in response_clean or "输入" in response_clean:
                action = "input"
                import re

                # 提取输入框
                input_box_match = re.search(r"在输入框:\['(.+?)'\]|在输入框：\【(.+?)\】|在输入框：\「(.+?)\」", response_clean)
                if input_box_match:
                    target = input_box_match.group(1) or input_box_match.group(2) or input_box_match.group(3)

                # 提取输入文本
                text_match = re.search(r"输入（[\"'『](.+?)[\"'』]）|输入\(\"(.+?)\"\)|输入『(.+?)』", response_clean)
                if text_match:
                    input_text = text_match.group(1) or text_match.group(2) or text_match.group(3)
                    parameters["text"] = input_text

                reasoning = f"在输入框[{target}]输入('{parameters.get('text', '')}')并回车" if target else "输入操作"

            elif "end_action" in response_clean or "任务已完成" in response_clean or "完成" in response_clean:
                action = "done"
                reasoning = "任务已完成"

            elif "swipe" in response_clean or "滑动" in response_clean or "scroll" in response_clean:
                action = "swipe"
                # 提取方向
                if "上" in response_clean or "up" in response_clean.lower():
                    parameters["direction"] = "up"
                elif "下" in response_clean or "down" in response_clean.lower():
                    parameters["direction"] = "down"
                elif "左" in response_clean or "left" in response_clean.lower():
                    parameters["direction"] = "left"
                elif "右" in response_clean or "right" in response_clean.lower():
                    parameters["direction"] = "right"

                reasoning = f"向{parameters.get('direction', '')}滑动"

            else:
                # 无法识别的操作
                reasoning = response_clean[:200]

            return {
                "action": action,
                "target": target,
                "parameters": parameters,
                "reasoning": reasoning if reasoning else response_clean[:200]
            }

        except Exception as e:
            logging.warning(f"自然语言解析失败: {e}，使用关键词匹配")

            # 最后的回退：关键词匹配
            action = "unknown"
            response_lower = response.lower()

            if "click" in response_lower or "点击" in response:
                action = "click"
            elif "input" in response_lower or "输入" in response:
                action = "input"
            elif "swipe" in response_lower or "scroll" in response_lower or "滑动" in response or "滚动" in response:
                action = "swipe"
            elif "done" in response_lower or "complete" in response_lower or "完成" in response or "结束" in response:
                action = "done"

            return {
                "action": action,
                "target": "",
                "parameters": {},
                "reasoning": response[:200]
            }

    def set_steps(self, steps: List[StepConfig]):
        """Customize the execution steps."""
        self.steps = steps

    def add_custom_handler(self, step_name: str, handler: Callable):
        """Add a custom step handler."""
        self.custom_handlers[step_name] = handler

    def get_state(self) -> Dict[str, Any]:
        """Get current execution state."""
        return {
            "step": self.step,
            "history": self.history,
            "actions": self.actions,
            "reacts": self.reacts
        }
