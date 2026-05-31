"""
Task Scheduler with ForensiVision API Integration

Orchestrates the execution of tasks using ForensiVision API for UI detection.
"""

import logging
import time
import json
import os
import pathlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable

from .modules.screenshot import ScreenshotModule
from .modules.executor import ExecutorModule
from .modules.storage import StorageModule
from .semantic_matcher import SemanticMatcher, SemanticMatcherMock
from .rag_template_matcher import RAGTemplateMatcher, RAGTemplateMatcherMock
from .script_registry import ScriptRegistry
from .xml_utils import XMLSimplifier
from .config import DEFAULT_MIMO_API_BASE, DEFAULT_MIMO_MODEL, get_llm_config
from runner.forensiflow.perception import VISUAL_BACKEND_ROOT


@dataclass
class StepConfig:
    """Configuration for a single execution step."""
    name: str
    enabled: bool = True
    pre_wait: float = 0.0  # Wait time before step (seconds)
    post_wait: float = 0.0  # Wait time after step (seconds)


class TaskSchedulerVT:
    """
    Task Scheduler with ForensiVision Integration

    使用 ForensiVision 进行 UI 检测的任务调度器。
    """

    # ==================== 配置常量 ====================
    class _Config:
        """硬编码常量配置集中管理"""

        # API 端点配置
        QWEN_API_URL = (
            os.getenv("FORENSIFLOW_API_BASE")
            or os.getenv("FORENSIFLOW_LLM_API_BASE")
            or os.getenv("LLM_API_BASE")
            or os.getenv("PAGE_AGENT_MOBILE_API_BASE")
            or os.getenv("QWEN_API_URL")
            or os.getenv("YUNWU_API_URL", DEFAULT_MIMO_API_BASE)
        )
        CHATGLM_API_URL = os.getenv("CHATGLM_API_URL", "https://open.bigmodel.cn/api/paas/v4")

        # 默认模型配置
        QWEN_DEFAULT_MODEL = (
            os.getenv("FORENSIFLOW_MODEL")
            or os.getenv("FORENSIFLOW_LLM_MODEL")
            or os.getenv("LLM_MODEL")
            or os.getenv("PAGE_AGENT_MOBILE_MODEL")
            or os.getenv("QWEN_DEFAULT_MODEL", DEFAULT_MIMO_MODEL)
        )
        CHATGLM_DEFAULT_MODEL = "glm-4-flash"

        # ForensiVision 路径配置
        VISUAL_BACKEND_PATH = str(VISUAL_BACKEND_ROOT)
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

    # Default step configuration for ForensiVision
    DEFAULT_STEPS = [
        StepConfig(name="screenshot", pre_wait=3.0),
        StepConfig(name="ui_detection"),      # ForensiVision UI 检测
        StepConfig(name="planning"),           # Planner 决策
        StepConfig(name="xml_matching"),       # XML 文本匹配（快速匹配）
        StepConfig(name="element_matching"),   # 元素匹配（ForensiVision fallback）
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
        Initialize task scheduler with ForensiVision API integration.

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

        # Initialize XML simplifier
        self.xml_simplifier = XMLSimplifier(max_length=12000)

        # ForensiVision 模块引用（直接导入，保持模型常驻内存）
        self._visual_models_loaded = False
        self._visual_models = None  # 存储 (_model_ver, _model_det, _model_cls, _preprocess, _ocr)
        self._visual_module_path = self._Config.VISUAL_BACKEND_PATH
        self._visual_process_img = None  # process_img 函数引用

        # Planner configuration: all OpenAI-compatible model calls share the same Mimo/Momi config.
        llm_config = get_llm_config(
            api_key=planner_api_key,
            api_base=planner_base_url,
            model=planner_model,
        )
        self.planner_api_key = llm_config.api_key
        self.planner_model = llm_config.model
        self.planner_base_url = llm_config.api_base

        # 根据提供商设置默认值
        if planner_provider == "qwen":
            if not self.planner_base_url:
                self.planner_base_url = self._Config.QWEN_API_URL
            if not self.planner_model:
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
        self.script_results: List[Dict[str, Any]] = []
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

    def _load_visual_models(self):
        """加载 ForensiVision 模型（整个任务期间只加载一次）"""
        if self._visual_models_loaded:
            logging.info("ForensiVision 模型已加载，跳过")
            return True

        try:
            logging.info(f"\n{'='*60}")
            logging.info(f"🔄 正在加载 ForensiVision 模型...")
            logging.info(f"{'='*60}")

            import sys
            import os

            # 保存原始工作目录
            original_cwd = os.getcwd()

            # 切换到 ForensiVision 目录（模型文件使用相对路径）
            os.chdir(self._visual_module_path)

            # 将 ForensiVision 添加到 sys.path（GUI.py 也会自己添加，但这里添加更保险）
            if self._visual_module_path not in sys.path:
                sys.path.insert(0, self._visual_module_path)

            try:
                # 导入配置
                from core.Config import alg, accurate_ocr, label_path_dir, high_conf_flag
                from core.Config import clean_save, ocr_save_flag, ocr_output_only, workflow_only

                # 将相对路径转换为绝对路径（因为后续会切换工作目录）
                if not os.path.isabs(label_path_dir):
                    label_path_dir = os.path.join(self._visual_module_path, label_path_dir)

                # 导入模型加载函数
                import core.import_models as import_models

                visual_mode = os.getenv(
                    "FORENSIFLOW_VISUAL_MODE",
                    os.getenv("FORENSIFLOW_VT_MODE", "auto"),
                ).strip().lower()
                min_mem_gb = float(
                    os.getenv(
                        "FORENSIFLOW_VISUAL_FULL_MIN_MEM_GB",
                        os.getenv("FORENSIFLOW_VT_FULL_MIN_MEM_GB", "5.5"),
                    )
                )
                if visual_mode in {"ocr", "ocr_only", "light"} or (
                    visual_mode == "auto" and self._available_memory_gb() < min_mem_gb
                ):
                    logging.info("🔎 ForensiVision 使用 OCR-only 轻量兜底模式，避免完整模型加载触发 OOM")
                    loaded = self._load_visual_ocr_fallback(import_models, label_path_dir)
                    if loaded:
                        return True

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
                self._visual_models = (_model_ver, _model_det, _model_cls, _preprocess, _ocr)
                self._visual_process_img = process_img
                self._visual_models_loaded = True

                # 保存配置到实例变量
                self._visual_alg = alg
                self._visual_accurate_ocr = accurate_ocr
                self._visual_label_path_dir = label_path_dir
                self._visual_high_conf_flag = high_conf_flag
                self._visual_clean_save = clean_save
                self._visual_ocr_save_flag = ocr_save_flag
                self._visual_ocr_output_only = ocr_output_only
                self._visual_workflow_only = workflow_only

            finally:
                # 恢复原始工作目录
                os.chdir(original_cwd)

            logging.info(f"✓ ForensiVision 模型加载成功！")
            logging.info(f"{'='*60}\n")

            return True

        except Exception as e:
            logging.error(f"✗ ForensiVision 模型加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _available_memory_gb(self) -> float:
        """Return currently available memory in GiB, best-effort."""
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) / 1024 / 1024
        except Exception:
            pass
        return 0.0

    def _load_visual_ocr_fallback(self, import_models, label_path_dir: str) -> bool:
        """Load a lightweight OCR-backed ForensiVision fallback.

        The full ForensiVision path loads PaddleOCR, YOLO and CLIP. On memory
        constrained experiment hosts that can be killed by the OS before Python
        can raise an exception. The OCR fallback still uses screenshots,
        PaddleOCR, semantic matching and LLM decision, which is sufficient when
        XML matching fails because text is visually present but absent/stale in
        the dumped hierarchy.
        """
        try:
            import_models._prepare_paddleocr_top_level_imports()
            from paddleocr import PaddleOCR

            ocr = PaddleOCR(use_angle_cls=True, show_log=False)
            self._visual_models = ("ocr_only", None, None, None, ocr)
            self._visual_process_img = self._process_img_ocr_fallback
            self._visual_models_loaded = True
            self._visual_alg = "ocr_only"
            self._visual_accurate_ocr = False
            self._visual_label_path_dir = label_path_dir
            self._visual_high_conf_flag = False
            self._visual_clean_save = True
            self._visual_ocr_save_flag = "save"
            self._visual_ocr_output_only = True
            self._visual_workflow_only = True
            logging.info("✓ ForensiVision OCR-only 兜底加载成功")
            return True
        except Exception as exc:
            logging.error(f"✗ ForensiVision OCR-only 兜底加载失败: {exc}")
            import traceback
            traceback.print_exc()
            return False

    def _process_img_ocr_fallback(
        self,
        label_path_dir,
        img_path,
        output_root,
        layout_json_dir,
        high_conf_flag,
        alg,
        clean_save,
        plot_show,
        ocr_save_flag,
        model_ver,
        model_det,
        model_cls,
        preprocess,
        pd_free_ocr=None,
        ocr_only=True,
        workflow_only=True,
        accurate_ocr=False,
        lang="zh",
    ):
        """Return ForensiVision-compatible text elements from PaddleOCR."""
        ocr = pd_free_ocr
        if ocr is None:
            return []
        raw = ocr.ocr(img_path, cls=True)
        elements = []

        def is_ocr_line(value):
            if not isinstance(value, (list, tuple)) or len(value) < 2:
                return False
            box, text_score = value[0], value[1]
            if not isinstance(box, (list, tuple)) or len(box) < 4:
                return False
            if not all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in box[:4]):
                return False
            return isinstance(text_score, (list, tuple)) and len(text_score) >= 1 and isinstance(text_score[0], str)

        def iter_lines(payload):
            if not payload:
                return
            if is_ocr_line(payload):
                yield payload
                return
            if isinstance(payload, (list, tuple)):
                for item in payload:
                    yield from iter_lines(item)

        for index, line in enumerate(iter_lines(raw) or []):
            try:
                box = line[0]
                text = str(line[1][0] or "").strip()
                score = float(line[1][1]) if len(line[1]) > 1 else 0.0
                if not text:
                    continue
                xs = [float(point[0]) for point in box]
                ys = [float(point[1]) for point in box]
                elements.append(
                    {
                        "id": f"ocr_{index}",
                        "class": "Text",
                        "text_content": text,
                        "sub_class": "OCRText",
                        "score": score,
                        "location": {
                            "left": int(min(xs)),
                            "top": int(min(ys)),
                            "right": int(max(xs)),
                            "bottom": int(max(ys)),
                        },
                    }
                )
            except Exception:
                continue

        os.makedirs(layout_json_dir or output_root, exist_ok=True)
        return elements

    def _format_rag_prompt_examples(self, matches, max_examples: int = 3) -> str:
        """Format RAG examples without initializing another matcher/model."""
        if not matches:
            return ""
        examples = ["\n## 📚 参考案例（相似历史任务）\n以下是与你当前任务相似的历史任务案例，请直接参考其结构：\n"]
        for match in matches[:max_examples]:
            template = match.template
            example_obj = {
                "相似度": f"{match.score:.2f}",
                "app": template.get('app', 'Unknown'),
                "task": template.get('task', ''),
                "steps": template.get('steps', []),
            }
            examples.append("```json\n" + json.dumps(example_obj, ensure_ascii=False, indent=2) + "\n```\n")
        return "\n".join(examples)

    def _unload_visual_models(self):
        """释放 ForensiVision 模型资源"""
        if not self._visual_models_loaded:
            return

        try:
            logging.info(f"\n{'='*60}")
            logging.info(f"🔄 正在释放 ForensiVision 模型资源...")
            logging.info(f"{'='*60}")

            # 清空模型引用
            self._visual_models = None
            self._visual_process_img = None
            self._visual_models_loaded = False

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

            logging.info(f"✓ ForensiVision 模型资源已释放")
            logging.info(f"{'='*60}\n")

        except Exception as e:
            logging.warning(f"释放模型资源时出现警告: {e}")

    def _plan_task_with_app(self, abstract_task: str, app_name: str = None, external_template: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        使用 LLM 规划任务并识别应用，生成可执行的步骤序列

        Args:
            abstract_task: 抽象任务描述，如"打开微信朋友圈"
            app_name: 应用名称（如果已知，会提供给 planner）
            external_template: 外部传入的模板（来自调度器选择器，已通过 BGE 匹配）

        Returns:
            {
                "app": "应用名称",
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
        if app_name:
            logging.info(f"目标应用: {app_name}")
        logging.info(f"{'='*60}\n")

        # 🔍 RAG 模板检索（使用外部传入的模板）
        rag_examples = ""
        if external_template:
            # 使用调度器选择器传入的模板
            try:
                logging.info(f"📚 使用调度器选择器提供的模板:")
                logging.info(f"   [{external_template.get('app', 'Unknown')}] {external_template.get('task', 'Unknown')}")

                # 格式化为 Few-Shot 示例
                from .rag_template_matcher import TemplateMatch
                mock_match = TemplateMatch(
                    template=external_template,
                    score=1.0,  # 外部传入的模板已经通过阈值筛选
                    rank=1
                )
                rag_examples = self._format_rag_prompt_examples([mock_match], max_examples=1)
                logging.info(f"✅ 外部模板示例已添加到提示词\n")

            except Exception as e:
                logging.warning(f"⚠️  外部模板格式化失败: {e}")
                logging.warning(f"💡 将不使用模板示例\n")
        else:
            # 回退到内部 RAG 检索（如果启用了 rag_matcher）
            if hasattr(self, 'rag_matcher') and self.rag_matcher:
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
                        logging.info(f"📚 内部 RAG 检索到最佳匹配模板:")
                        logging.info(f"   [{match.template.get('app', 'Unknown')}] {match.template.get('task', 'Unknown')} (相似度: {match.score:.3f})")

                        # 格式化为 Few-Shot 示例
                        rag_examples = self._format_rag_prompt_examples(top_matches, max_examples=1)
                        logging.info(f"✅ RAG 示例已添加到提示词\n")
                    else:
                        logging.info(f"ℹ️  未找到足够相似的任务模板 (最佳匹配: {top_matches[0].score if top_matches else 0:.3f})\n")

                except Exception as e:
                    logging.warning(f"⚠️  内部 RAG 检索失败: {e}")
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
""" + (f"\n目标应用：{app_name}" if app_name else "") + f"""

## 📚 参考案例（供你吸收并纠正自身规划路线）
{rag_examples}

## 输出要求
请严格按照以下JSON格式输出（格式与参考案例保持一致）：
- 在 reasoning 中说明你是如何利用参考案例来纠正或优化你的常规操作路线的
""" + (f"- app 字段必须使用目标应用名称：{app_name}" if app_name else "- app 字段根据任务描述推断应用名称") + """
```json
{{
  "app": """ + (f'"{app_name}"' if app_name else '"应用名称（如：微信、淘宝、WhatsApp等）"') + """,
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

            response_text = self._extract_llm_response_text(response)

            logging.info(f"\n{'='*60}")
            logging.info(f"📥 LLM 规划响应:")
            logging.info(f"{'='*60}")
            logging.info(f"{response_text}")
            logging.info(f"{'='*60}\n")

            # 解析 JSON 响应
            result = self._extract_json_from_response(response_text)

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
            screenshot_path = os.path.abspath(os.path.join(self.run_data_dir, f"check_completion_{self.step}.jpg"))
            self.device.screenshot(screenshot_path)

            # 2. ForensiVision 检测
            ui_json_path = os.path.abspath(os.path.join(self.run_data_dir, f"ui_check_{self.step}.json"))

            original_cwd = os.getcwd()
            os.chdir(self._visual_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._visual_models
                result_js = self._visual_process_img(
                    label_path_dir=self._visual_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._visual_high_conf_flag,
                    alg=self._visual_alg,
                    clean_save=self._visual_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._visual_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._visual_ocr_output_only,
                    workflow_only=self._visual_workflow_only,
                    accurate_ocr=self._visual_accurate_ocr
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

            response_text = self._extract_llm_response_text(response)

            logging.info(f"\n{'='*60}")
            logging.info(f"📥 LLM 任务完成判断响应:")
            logging.info(f"{'='*60}")
            logging.info(f"{response_text}")
            logging.info(f"{'='*60}\n")

            # 7. 解析 JSON 响应
            result = self._extract_json_from_response(response_text)

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
        执行预定义的步骤（XML优先，失败则ForensiVision fallback）

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

            if action_lower == "launch":
                package_name = step.get("package_name") or params.get("package_name")
                app_name = step.get("app_name") or params.get("app_name")
                if package_name:
                    logging.info(f"    📱 Launch 已由步骤序列入口处理，确认包名: {package_name}")
                elif app_name:
                    logging.info(f"    📱 Launch 已由步骤序列入口处理，确认应用: {app_name}")
                else:
                    logging.info("    📱 Launch step skipped: app already launched by scheduler")
                return True

            if action_lower == "click":
                return self._execute_click_step(step)

            elif action_lower == "input":
                text = params.get("text", "")
                return self._execute_input_step(target, text)

            elif action_lower == "swipe":
                direction = params.get("direction") or step.get("direction") or "down"
                return self._execute_swipe_step(direction, step)

            elif action_lower == "wait":
                duration = (
                    params.get("duration")
                    or params.get("duration_seconds")
                    or step.get("duration")
                    or step.get("duration_seconds")
                    or 2
                )
                if step.get("duration_ms"):
                    duration = float(step["duration_ms"]) / 1000.0
                logging.info(f"    ⏱️ 等待 {duration} 秒...")
                time.sleep(float(duration))
                return True

            elif action_lower in {"back", "pressback", "press_back"}:
                logging.info("    ↩️ 返回上一页")
                self.device.keyevent("BACK")
                time.sleep(1)
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

                script_result = ScriptRegistry.get_last_execution_result()
                if script_result:
                    self.script_results.append(script_result)

                if success:
                    # 记录到 reacts
                    self.reacts.append({
                        "reasoning": f"执行取证脚本: {script_name}",
                        "function": {
                            "name": "CallScript",
                            "parameters": {
                                "script": script_name,
                                "script_result": script_result or {}
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

    def _click_target_value(self, target):
        """Return the actual click locator from a planner/template step."""
        if isinstance(target, dict):
            for nested_key in ("target", "match"):
                nested = target.get(nested_key)
                if isinstance(nested, (dict, str)) and nested:
                    return nested
        return target

    def _click_target_display(self, target) -> str:
        target = self._click_target_value(target)
        spec = self._parse_structured_click_target(target)
        if spec:
            parts = []
            for key in ("resource_id", "text", "content_desc", "class"):
                if spec.get(key):
                    parts.append(f"{key}={spec[key]}")
            return "{" + ", ".join(parts) + "}"
        return str(target or "")

    def _parse_structured_click_target(self, target):
        if isinstance(target, dict):
            raw = target
        else:
            text = str(target or "").strip()
            if not (text.startswith("{") and text.endswith("}")):
                return {}
            try:
                import ast
                raw = ast.literal_eval(text)
            except Exception:
                try:
                    import json
                    raw = json.loads(text)
                except Exception:
                    return {}
            if not isinstance(raw, dict):
                return {}

        aliases = {
            "resource_id": ("resource_id", "resource-id", "id"),
            "text": ("text", "target_text", "label", "title"),
            "content_desc": ("content_desc", "content-desc", "description", "desc"),
            "class": ("class", "class_name", "className"),
        }
        spec = {}
        for canonical, keys in aliases.items():
            for key in keys:
                value = str(raw.get(key) or "").strip()
                if value:
                    spec[canonical] = value
                    break
        bounds = raw.get("bounds")
        if isinstance(bounds, dict):
            try:
                spec["bounds"] = {
                    "left": int(bounds["left"]),
                    "top": int(bounds["top"]),
                    "right": int(bounds["right"]),
                    "bottom": int(bounds["bottom"]),
                }
            except Exception:
                pass
        elif isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            try:
                spec["bounds"] = {
                    "left": int(bounds[0]),
                    "top": int(bounds[1]),
                    "right": int(bounds[2]),
                    "bottom": int(bounds[3]),
                }
            except Exception:
                pass
        elif isinstance(bounds, str) and bounds.strip():
            parsed = self._parse_xml_bounds(bounds)
            if parsed:
                spec["bounds"] = parsed
        return spec

    def _execute_click_step(self, target) -> bool:
        """
        执行点击步骤（XML优先）

        Args:
            target: 目标文本

        Returns:
            bool: 是否执行成功
        """
        target = self._click_target_value(target)
        target_spec = self._parse_structured_click_target(target)
        target_display = self._click_target_display(target)
        logging.info(f"    🎯 点击目标: {target_display}")

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
                    "reasoning": f"通过 XML 匹配点击 '{target_display}'",
                    "function": {
                        "name": "click",
                        "parameters": {"target": target_display, "x": center_x, "y": center_y}
                    },
                    "action_index": self.step
                })

                time.sleep(1)
                return True
            logging.info(f"    ✗ XML 未找到匹配元素: {target_display}")

        except Exception as e:
            logging.info(f"    ✗ XML 匹配失败: {e}")

            # 记录失败尝试（用于上下文提示词）
            if self._planned_steps:
                self._failed_attempts.append({
                    "action": "click",
                    "target": target_display,
                    "method": "XML 匹配",
                    "reason": str(e) if e else "未找到匹配元素"
                })

        if target_spec.get("bounds"):
            bounds = target_spec["bounds"]
            center_x = (bounds["left"] + bounds["right"]) // 2
            center_y = (bounds["top"] + bounds["bottom"]) // 2
            logging.info(f"    ✓ 使用模板 bounds 兜底点击: ({center_x}, {center_y})")
            self.device.click(center_x, center_y)
            self.reacts.append({
                "reasoning": f"通过模板 bounds 点击 '{target_display}'",
                "function": {
                    "name": "click",
                    "parameters": {"target": target_display, "x": center_x, "y": center_y, "method": "template_bounds"}
                },
                "action_index": self.step
            })
            time.sleep(1)
            return True

        if target_spec:
            logging.warning(f"    ⚠️ 结构化目标未命中 XML，跳过语义兜底以避免误点: {target_display}")
            return False

        # 2. XML 失败，尝试 ForensiVision + LLM 动态上下文循环
        logging.info(f"    🔍 步骤 2/2: 尝试 ForensiVision + LLM 动态上下文循环...")

        try:
            # 判断是否使用上下文提示词（如果是步骤序列模式且有上下文信息）
            use_context = self._planned_steps and len(self._planned_steps) > 0

            if use_context:
                # 使用动态上下文循环（支持滑动、多轮决策）
                return self._execute_step_with_dynamic_context("click", target_display)
            else:
                # 原有逻辑：单次 LLM 决策（非步骤序列模式）
                return self._execute_click_legacy_fallback(target_display)

        except Exception as e:
            logging.error(f"    ✗ ForensiVision + LLM 匹配失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        logging.error(f"    ✗ 所有匹配方式均失败")
        return False

    def _execute_click_legacy_fallback(self, target: str) -> bool:
        """
        原有的 ForensiVision + LLM 决策逻辑（非步骤序列模式的回退方案）

        Args:
            target: 目标文本

        Returns:
            bool: 是否执行成功
        """
        import time

        try:
            # 截图
            screenshot_path = os.path.abspath(os.path.join(self.run_data_dir, f"{self.step}.jpg"))
            self.device.screenshot(screenshot_path)
            logging.info(f"    📸 截图已保存: {screenshot_path}")

            # ForensiVision 检测
            ui_json_path = os.path.abspath(os.path.join(self.run_data_dir, f"ui_{self.step}.json"))

            original_cwd = os.getcwd()
            os.chdir(self._visual_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._visual_models

                result_js = self._visual_process_img(
                    label_path_dir=self._visual_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._visual_high_conf_flag,
                    alg=self._visual_alg,
                    clean_save=self._visual_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._visual_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._visual_ocr_output_only,
                    workflow_only=self._visual_workflow_only,
                    accurate_ocr=self._visual_accurate_ocr
                )
            finally:
                os.chdir(original_cwd)

            # 保存 JSON
            with open(ui_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            logging.info(f"    📄 UI JSON 已保存: {ui_json_path}")
            logging.info(f"    ✓ ForensiVision detected {len(result_js) if isinstance(result_js, list) else 0} elements")

            # 使用 LLM 决策（不使用上下文提示词）
            decision = self._decide_action_with_llm(
                result_js,
                f"点击{target}",
                use_context_prompt=False
            )

            # 从 ForensiVision JSON 中查找 LLM 决策的元素
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
            logging.error(f"    ✗ ForensiVision + LLM 匹配失败: {e}")
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

        if not self._visual_models_loaded or self._visual_models is None or self._visual_process_img is None:
            logging.info("    🔄 ForensiVision 模型未就绪，尝试重新加载...")
            if not self._load_visual_models():
                logging.error("    ✗ ForensiVision 模型不可用，无法执行视觉兜底决策")
                return False

        for iteration in range(max_iterations):
            logging.info(f"\n    🔄 动态上下文循环 {iteration + 1}/{max_iterations}")

            # 1. 截图
            screenshot_path = os.path.abspath(os.path.join(self.run_data_dir, f"{self.step}_iter{iteration}.jpg"))
            self.device.screenshot(screenshot_path)
            logging.info(f"    📸 截图已保存: {screenshot_path}")

            # 2. ForensiVision 检测
            ui_json_path = os.path.abspath(os.path.join(self.run_data_dir, f"ui_{self.step}_iter{iteration}.json"))

            original_cwd = os.getcwd()
            os.chdir(self._visual_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._visual_models
                result_js = self._visual_process_img(
                    label_path_dir=self._visual_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._visual_high_conf_flag,
                    alg=self._visual_alg,
                    clean_save=self._visual_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._visual_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._visual_ocr_output_only,
                    workflow_only=self._visual_workflow_only,
                    accurate_ocr=self._visual_accurate_ocr
                )
            finally:
                os.chdir(original_cwd)

            # 保存 UI JSON
            with open(ui_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            logging.info(f"    📄 UI JSON 已保存: {ui_json_path}")
            logging.info(f"    ✓ ForensiVision detected {len(result_js) if isinstance(result_js, list) else 0} elements")

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
            step_completed = decision.get("step_completed")

            logging.info(f"    🎯 LLM 决策: {action}, 当前步骤是否完成: {step_completed}, 理由: {reasoning}")

            # 不区分大小写
            action_lower = action.lower()

            # 4. 根据决策执行操作
            if action_lower == "done":
                if decision.get("step_completed") is False:
                    logging.warning(f"    ⚠️ LLM 输出 done 但当前步骤是否完成=false，继续重试当前步骤")
                    time.sleep(1)
                    continue

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

                        if self._decision_completes_current_step(decision, current_target, llm_target):
                            logging.info(f"    ✓ 当前步骤目标已执行: {current_target}")
                            return True

                        logging.info(
                            f"    ↻ 已执行清障/中间动作 '{llm_target}'，继续重试当前步骤: {current_target}"
                        )
                        continue
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
                        if self._decision_completes_current_step(decision, current_target, llm_target):
                            logging.info(f"    ✓ 当前步骤目标已执行: {current_target}")
                            return True

                        logging.info(
                            f"    ↻ 已执行清障/中间输入 '{llm_target}'，继续重试当前步骤: {current_target}"
                        )
                        continue
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

    def _decision_completes_current_step(
        self,
        decision: Dict[str, Any],
        current_target: str,
        decision_target: str
    ) -> bool:
        """
        判断一次 LLM fallback 操作是否完成当前步骤。

        优先使用模型显式输出的 step_completed。只有旧模型输出没有该字段时，
        才退回到目标文本匹配，兼容旧格式。
        """
        step_completed = decision.get("step_completed")
        if isinstance(step_completed, bool):
            return step_completed

        return self._is_decision_target_current_step(current_target, decision_target)

    def _is_decision_target_current_step(self, current_target: str, decision_target: str) -> bool:
        """
        判断 fallback 决策是否真正执行了当前步骤目标。

        LLM 在弹窗/引导页上可能会先点击“以后再说”等清障元素。清障动作是合理的，
        但不能被当成“点击 新聊天 #fab”这类原始步骤已经完成。
        """
        def normalize(value: str) -> str:
            value = (value or "").strip().lower()
            if "#" in value:
                value = value.split("#", 1)[0]
            for token in ["按钮键", "按钮", "键", "图标", "标题", "target", "click"]:
                value = value.replace(token, "")
            return "".join(ch for ch in value if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")

        current_norm = normalize(current_target)
        decision_norm = normalize(decision_target)

        if not current_norm or not decision_norm:
            return False

        return current_norm in decision_norm or decision_norm in current_norm

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

        # 2. ForensiVision + LLM 决策 Fallback
        logging.info(f"    🔍 步骤 2/2: 尝试 ForensiVision + LLM 决策...")

        try:
            screenshot_path = os.path.abspath(os.path.join(self.run_data_dir, f"{self.step}.jpg"))
            self.device.screenshot(screenshot_path)

            ui_json_path = os.path.abspath(os.path.join(self.run_data_dir, f"ui_{self.step}.json"))

            original_cwd = os.getcwd()
            os.chdir(self._visual_module_path)

            try:
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._visual_models
                result_js = self._visual_process_img(
                    label_path_dir=self._visual_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._visual_high_conf_flag,
                    alg=self._visual_alg,
                    clean_save=self._visual_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._visual_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._visual_ocr_output_only,
                    workflow_only=self._visual_workflow_only,
                    accurate_ocr=self._visual_accurate_ocr
                )
            finally:
                os.chdir(original_cwd)

            with open(ui_json_path, 'w', encoding='utf-8') as f:
                import json
                json.dump(result_js, f, indent=4, ensure_ascii=False)

            logging.info(f"    📄 UI JSON 已保存: {ui_json_path}")
            logging.info(f"    ✓ ForensiVision detected {len(result_js) if isinstance(result_js, list) else 0} elements")

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

            # 从 ForensiVision JSON 中查找 LLM 决策的元素
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
            logging.error(f"    ✗ ForensiVision + LLM 匹配失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _execute_swipe_step(self, direction: str, step: Optional[Dict[str, Any]] = None) -> bool:
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
            if isinstance(step, dict) and {"start_y", "end_y"} <= set(step):
                raw_device = getattr(self.device, "d", None)
                if raw_device is None:
                    raise RuntimeError("raw uiautomator2 device is not available for coordinate swipe")
                width, height = self._device_window_size()
                x_ratio = float(step.get("x_ratio", step.get("x", 0.5)))
                x = int(width * x_ratio) if 0 < x_ratio <= 1 else int(x_ratio)
                start_y_raw = float(step.get("start_y", 0.8))
                end_y_raw = float(step.get("end_y", 0.4))
                start_y = int(height * start_y_raw) if 0 < start_y_raw <= 1 else int(start_y_raw)
                end_y = int(height * end_y_raw) if 0 < end_y_raw <= 1 else int(end_y_raw)
                duration = float(step.get("duration", step.get("duration_seconds", 0.3)))
                logging.info(f"    👆 区域滑动: ({x}, {start_y}) -> ({x}, {end_y}), duration={duration}")
                raw_device.swipe(x, start_y, x, end_y, duration=duration)
            else:
                # 执行滑动
                self.device.swipe(actual_direction)

            # 记录到 reacts
            self.reacts.append({
                "reasoning": f"向{direction}滑动（内容滚动）",
                "function": {
                    "name": "swipe",
                    "parameters": {"direction": direction, "actual_direction": actual_direction, "step": step or {}}
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

    def _device_window_size(self) -> tuple:
        raw_device = getattr(self.device, "d", None)
        if raw_device is not None:
            try:
                width, height = raw_device.window_size()
                return int(width), int(height)
            except Exception:
                pass
        return 1080, 1920

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
            ui_elements: ForensiVision 检测到的 UI 元素列表
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
                    # 适配 ForensiVision 格式
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
                        "step_completed": True,
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
        messages = self._build_visual_perception_messages(prompt)

        # 4. 调用 LLM
        response = self.planner_client.chat.completions.create(
            model=self.planner_model,
            messages=messages,
            temperature=0.3,
            top_p=0.7
        )

        # 5. 解析响应
        decision_text = self._extract_llm_response_text(response)

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
        logging.info(f"       - Step completed: {decision.get('step_completed', None)}")
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
        use_abstract_task: bool = False,  # 新增：是否使用抽象任务模式
        rag_template: Dict[str, Any] = None  # 新增：外部传入的 RAG 模板（来自调度器选择器）
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
            rag_template: 外部传入的 RAG 模板（由调度器选择器提供，已通过 BGE 匹配）

        Returns:
            Dictionary with execution results
        """
        # Create timestamped subdirectory for this run
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_data_dir = str(pathlib.Path(self.data_dir).resolve() / f"run_{timestamp}")
        os.makedirs(self.run_data_dir, exist_ok=True)

        # Also create subdirectories for ForensiVision output
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
        self.script_results = []
        self.step = 0

        # 抽象任务模式：LLM 拆分任务为步骤序列，然后逐步执行
        if use_abstract_task:
            logging.info(f"\n{'='*60}")
            logging.info(f"🔄 步骤序列模式")
            logging.info(f"原始任务: {task}")
            logging.info(f"{'='*60}\n")

            try:
                # 1. LLM 任务规划 + 应用识别 + 步骤拆分
                # 使用外部传入的模板（如果提供）
                # 传递应用名称给 planner
                plan_result = self._plan_task_with_app(task, app_name=app, external_template=rag_template)

                # 2. 启动应用（从模板第一步提取包名）
                app_name = plan_result.get('app') or plan_result.get('app_name')
                steps = plan_result['steps']
                if rag_template and isinstance(rag_template.get("steps"), list):
                    template_steps = rag_template["steps"]
                    if template_steps:
                        logging.info("📌 使用外部模板步骤覆盖规划结果中的脚本边界步骤，确保 CallScript 与注册表一致")
                        steps = template_steps
                        plan_result["steps"] = steps

                # 初始化任务上下文管理
                self._original_task = task
                self._planned_steps = steps
                self._current_step_index = 0
                self._failed_attempts = []

                # 确定包名（优先使用模板中的包名）
                package_name = None
                if rag_template and rag_template.get('steps'):
                    # 从模板的第一步提取包名
                    first_step = rag_template['steps'][0]
                    if first_step.get('action') == 'Launch' and first_step.get('package_name'):
                        package_name = first_step['package_name']
                        # 同时更新应用名称（使用模板中的完整名称）
                        app_name_from_template = first_step.get('app_name', app_name)
                        if app_name_from_template:
                            app_name = app_name_from_template

                logging.info(f"\n{'='*60}")
                logging.info(f"📱 启动应用: {app_name}")
                if package_name:
                    logging.info(f"   包名: {package_name} (来自模板)")
                    logging.info(f"   来源: {rag_template.get('task', 'Unknown')}")
                logging.info(f"{'='*60}\n")

                # 启动应用
                if package_name:
                    # 直接使用包名启动（来自模板）
                    self.device.app_start(package_name)
                else:
                    # 回退到应用名称查找（硬编码字典）
                    self.device.start_app(app_name)

                # 3. 等待应用加载
                logging.info(f"⏳ 等待应用加载...")
                import time
                time.sleep(5)  # 等待应用启动

                logging.info(f"✓ 应用已启动\n")

                # 4. 仅当步骤需要文本/视觉定位时加载 ForensiVision。
                needs_visual_matching = any(
                    str(step.get("action", "")).lower() in {"click", "input"}
                    for step in steps
                )
                if needs_visual_matching:
                    self._load_visual_models()

                # 5. 逐步执行步骤序列
                logging.info(f"\n{'='*60}")
                logging.info(f"🚀 开始执行步骤序列（共 {len(steps)} 步）")
                logging.info(f"{'='*60}\n")

                all_steps_success = True
                failed_step_index = None
                failed_step = None

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
                        all_steps_success = False
                        failed_step_index = self.step
                        failed_step = step
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
                if all_steps_success:
                    logging.info(f"✓ 步骤序列执行完成")
                else:
                    logging.error(f"✗ 步骤序列未完成，失败步骤: {failed_step_index}/{len(steps)}")
                logging.info(f"✓ 任务执行结束，不再检查是否完成")
                logging.info(f"{'='*60}\n")

                # 保存最终结果（任务执行完成后直接结束）
                self.storage_module.save_actions(app_name, old_task, task, self.actions)
                self.storage_module.save_reacts(self.reacts)

                result = {
                    "completed": all_steps_success,
                    "total_steps": len(self.actions),
                    "actions": self.actions,
                    "reacts": self.reacts,
                    "script_results": self.script_results,
                    "data_dir": self.run_data_dir
                }
                if not all_steps_success:
                    result["error"] = f"Failed at step {failed_step_index}: {failed_step}"

                return result

            except Exception as e:
                logging.error(f"✗ 任务执行失败: {e}")
                import traceback
                traceback.print_exc()
                return {
                    "completed": False,
                    "total_steps": len(self.actions),
                    "actions": self.actions,
                    "reacts": self.reacts,
                    "script_results": self.script_results,
                    "data_dir": self.run_data_dir,
                    "error": f"Failed to execute task: {e}"
                }
            finally:
                # 释放 ForensiVision 模型资源
                self._unload_visual_models()

        # 原有的逐步决策模式（保留兼容性）
        # 加载 ForensiVision 模型（整个任务期间只加载一次）
        if not self._load_visual_models():
            return {
                "completed": False,
                "total_steps": 0,
                "actions": [],
                "reacts": [],
                "data_dir": self.run_data_dir,
                "error": "Failed to load ForensiVision models"
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
            # 释放 ForensiVision 模型资源
            self._unload_visual_models()

        # Save final results
        self.storage_module.save_actions(app, old_task, task, self.actions)
        self.storage_module.save_reacts(self.reacts)

        return {
            "completed": result.get("completed", False),
            "total_steps": len(self.actions),
            "actions": self.actions,
            "reacts": self.reacts,
            "script_results": self.script_results,
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
        """Execute UI detection step using ForensiVision（直接调用，模型已常驻内存）."""
        logging.info(f"    Running ForensiVision UI detection...")

        # 检查模型是否已加载
        if not self._visual_models_loaded or self._visual_process_img is None:
            logging.error("    ForensiVision models not loaded!")
            context["ui_detection_error"] = "Models not loaded"
            context["stop"] = True
            return context

        try:
            # Use run-specific directory
            screenshot_path = os.path.abspath(os.path.join(self.run_data_dir, f"{self.step}.jpg"))
            ui_json_path = os.path.abspath(os.path.join(self.run_data_dir, f"ui_{self.step}.json"))

            # 检查截图文件是否存在
            if not os.path.exists(screenshot_path):
                raise FileNotFoundError(f"截图文件不存在: {screenshot_path}")

            logging.info(f"    Screenshot: {screenshot_path}")
            logging.info(f"    Output JSON: {ui_json_path}")

            # 直接调用 process_img 函数（模型已在内存中）
            import time
            start_time = time.time()

            # 临时切换到 ForensiVision 目录（process_img 内部使用相对路径）
            original_cwd = os.getcwd()
            os.chdir(self._visual_module_path)

            try:
                # 解包模型
                _model_ver, _model_det, _model_cls, _preprocess, _ocr = self._visual_models

                # 调用检测函数
                result_js = self._visual_process_img(
                    label_path_dir=self._visual_label_path_dir,
                    img_path=screenshot_path,
                    output_root=self.run_data_dir,
                    layout_json_dir=self.run_data_dir,
                    high_conf_flag=self._visual_high_conf_flag,
                    alg=self._visual_alg,
                    clean_save=self._visual_clean_save,
                    plot_show=False,
                    ocr_save_flag=self._visual_ocr_save_flag,
                    model_ver=_model_ver,
                    model_det=_model_det,
                    model_cls=_model_cls,
                    preprocess=_preprocess,
                    pd_free_ocr=_ocr,
                    ocr_only=self._visual_ocr_output_only,
                    workflow_only=self._visual_workflow_only,
                    accurate_ocr=self._visual_accurate_ocr
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

            logging.info(f"    ✓ ForensiVision detected {len(context['ui_elements'])} elements")
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

            # Build ForensiVision-style prompt
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

            # 构建 ForensiVision 风格的消息（包含 Few-shot Learning）
            messages = self._build_visual_perception_messages(prompt)

            # Call ChatGLM API
            response = self.planner_client.chat.completions.create(
                model=self.planner_model,
                messages=messages,
                temperature=0.3,  # 降低温度以获得更确定的输出
                top_p=0.7
            )

            # Parse response
            decision_text = self._extract_llm_response_text(response)

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
                # ForensiVision 格式：不记录完成操作到历史
            else:
                # 记录操作历史（ForensiVision 格式）
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
        to ForensiVision's vision-based matching.
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

                    # Mark as matched to skip ForensiVision matching
                    context["xml_matched"] = True
                else:
                    logging.warning(f"    XML element found but no bounds: {matched_element}")
                    context["xml_matched"] = False
            else:
                logging.info(f"    XML matching failed, will try ForensiVision...")
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

        Directly extracts position from ForensiVision JSON instead of using element_matcher.
        This is a fallback step if XML matching failed.
        """
        # Skip if XML matching already succeeded
        if context.get("xml_matched"):
            logging.info(f"    Element already matched by XML, skipping ForensiVision matching")
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

        logging.info(f"    🔍 ForensiVision Matching: Looking for '{target}' (XML fallback)")

        try:
            # 从 ForensiVision JSON 中查找匹配的元素
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
                        "method": "forensivision",
                        "confidence": 1.0
                    }
                    logging.info(f"    ✓ ForensiVision matched '{target}' at ({center_x}, {center_y})")
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
        """从 ForensiVision JSON 中查找匹配的元素.

        Args:
            ui_elements: ForensiVision 返回的元素列表
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
        """Find a click target in Android XML.

        The scheduler normally receives plain text targets, but Codex-generated
        RAG templates can also carry structured targets from action_path.json.
        Search both the simplified tree and the raw dump so simplification does
        not drop narrow controls such as Google Maps filter chips.
        """
        import xml.etree.ElementTree as ET

        target_spec = self._parse_structured_click_target(target_text)
        target_plain = "" if target_spec else str(target_text or "").strip()

        roots = []
        try:
            simplified_root = self.xml_simplifier.simplify_to_tree(xml_content)
            if simplified_root is not None:
                roots.append(("simplified", simplified_root))
        except Exception as e:
            logging.warning(f"    XML 简化异常: {e}，继续使用原始 XML")

        try:
            raw_root = ET.fromstring(xml_content)
            roots.append(("raw", raw_root))
        except ET.ParseError as parse_error:
            logging.error(f"    原始 XML 解析失败: {parse_error}")

        if not roots:
            return None

        def parse_bounds(bounds_str):
            return self._parse_xml_bounds(bounds_str)

        def class_matches(actual, expected):
            actual = str(actual or "").strip()
            expected = str(expected or "").strip()
            if not actual or not expected:
                return False
            return actual == expected or actual.split(".")[-1] == expected.split(".")[-1]

        def resource_id_matches(actual, expected):
            actual = str(actual or "").strip()
            expected = str(expected or "").strip()
            if not actual or not expected:
                return False
            if actual == expected:
                return True
            actual_tail = actual.rsplit("/", 1)[-1].rsplit(":id/", 1)[-1]
            expected_tail = expected.rsplit("/", 1)[-1].rsplit(":id/", 1)[-1]
            return actual_tail == expected_tail

        def node_texts(node):
            values = []
            for key in ("text", "content-desc", "resource-id"):
                value = str(node.get(key, "") or "").strip()
                if value:
                    values.append(value)
            return values

        def descendant_texts(node):
            values = []
            for child in node:
                values.extend(node_texts(child))
                values.extend(descendant_texts(child))
            return values

        def make_result(node, match_type, score=0):
            bounds = parse_bounds(node.get("bounds", ""))
            if not bounds:
                return None
            text = node.get("text", "") or node.get("content-desc", "") or node.get("resource-id", "")
            return {
                "text": text,
                "class": node.get("class", ""),
                "bounds": bounds,
                "resource_id": node.get("resource-id", ""),
                "match_type": match_type,
                "score": score,
            }

        def structured_match(node):
            resource_id = str(node.get("resource-id", "") or "").strip()
            text = str(node.get("text", "") or "").strip()
            content_desc = str(node.get("content-desc", "") or "").strip()
            klass = str(node.get("class", "") or "").strip()

            score = 0
            has_locator = any(target_spec.get(key) for key in ("resource_id", "text", "content_desc"))
            if not has_locator:
                return None

            expected_id = target_spec.get("resource_id")
            if expected_id:
                if not resource_id_matches(resource_id, expected_id):
                    return None
                score += 10

            expected_text = target_spec.get("text")
            if expected_text:
                if text == expected_text:
                    score += 6
                elif content_desc == expected_text:
                    score += 5
                else:
                    descendant_values = descendant_texts(node)
                    if expected_text in descendant_values:
                        score += 4
                    else:
                        return None

            expected_desc = target_spec.get("content_desc")
            if expected_desc:
                if content_desc == expected_desc:
                    score += 6
                elif text == expected_desc:
                    score += 4
                else:
                    descendant_values = descendant_texts(node)
                    if expected_desc in descendant_values:
                        score += 4
                    else:
                        return None

            expected_class = target_spec.get("class")
            if expected_class and class_matches(klass, expected_class):
                score += 2

            return make_result(node, "structured", score)

        def search_structured(root):
            best = None

            def visit(node):
                nonlocal best
                candidate = structured_match(node)
                if candidate and (best is None or candidate.get("score", 0) > best.get("score", 0)):
                    best = candidate
                for child in node:
                    visit(child)

            visit(root)
            return best

        def search_exact(root):
            target_lower = target_plain.lower()

            def visit(node):
                text = node.get("text", "")
                content_description = node.get("content-desc", "")
                resource_id = node.get("resource-id", "")
                descendant_values = [value.lower() for value in descendant_texts(node)]

                if text and text.strip().lower() == target_lower:
                    return make_result(node, "exact")
                if content_description and content_description.strip().lower() == target_lower:
                    return make_result(node, "exact")
                if resource_id and resource_id.strip().lower() == target_lower:
                    return make_result(node, "resource_id_exact")
                if resource_id and resource_id_matches(resource_id.lower(), target_lower):
                    return make_result(node, "resource_id_exact")
                if target_lower in descendant_values:
                    return make_result(node, "descendant_text_exact")

                for child in node:
                    result = visit(child)
                    if result:
                        return result
                return None

            return visit(root)

        def search_fallback(root):
            target_lower = target_plain.lower()

            def visit(node):
                text = node.get("text", "")
                content_description = node.get("content-desc", "")
                resource_id = node.get("resource-id", "")
                descendant_values = [value.lower() for value in descendant_texts(node)]

                if text and target_lower in text.strip().lower():
                    return make_result(node, "contains")
                if content_description and target_lower in content_description.strip().lower():
                    return make_result(node, "contains")
                if resource_id:
                    id_name = resource_id.lower()
                    if target_lower in id_name or id_name in target_lower:
                        return make_result(node, "resource_id")
                for descendant_text in descendant_values:
                    if target_lower in descendant_text or descendant_text in target_lower:
                        return make_result(node, "descendant_text")

                for child in node:
                    result = visit(child)
                    if result:
                        return result
                return None

            return visit(root)

        if target_spec:
            for _, root in roots:
                result = search_structured(root)
                if result:
                    return result
            return None

        if not target_plain:
            return None

        for _, root in roots:
            result = search_exact(root)
            if result:
                return result
        for _, root in roots:
            result = search_fallback(root)
            if result:
                return result
        return None

    @staticmethod
    def _parse_xml_bounds(bounds_str):
        """Parse Android XML bounds: [left,top][right,bottom]."""
        try:
            import re
            matches = re.findall(r'\[(\d+),(\d+)\]', bounds_str or "")
            if len(matches) == 2:
                left, top = int(matches[0][0]), int(matches[0][1])
                right, bottom = int(matches[1][0]), int(matches[1][1])
                return {"left": left, "top": top, "right": right, "bottom": bottom}
        except Exception as e:
            logging.debug(f"    Failed to parse bounds '{bounds_str}': {e}")
        return None

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
        Convert UI elements to ForensiVision-style hierarchical description.

        ForensiVision format:
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
        Build ForensiVision-style prompt with Few-shot Learning examples.

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
- 你必须输出“当前步骤是否完成：true/false”
- 如果你点击的是弹窗、引导页、权限页或遮挡页上的跳过/关闭/允许等清障元素，当前步骤是否完成必须是 false
- 如果你点击/输入/滑动后已经真正达成【当前步骤目标】，当前步骤是否完成才可以是 true

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
        import json
        import re

        text = (response_text or "").strip()
        if not text:
            raise ValueError("无法在响应中找到有效的 JSON")

        fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        else:
            generic_fence = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
            if generic_fence:
                text = generic_fence.group(1).strip()

        try:
            return json.loads(text)
        except Exception:
            pass

        start = text.find("{")
        while start != -1:
            depth = 0
            in_string = False
            escape = False
            for idx in range(start, len(text)):
                ch = text[idx]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : idx + 1]
                        try:
                            return json.loads(candidate)
                        except Exception:
                            break
            start = text.find("{", start + 1)

        raise ValueError("无法在响应中找到有效的 JSON")

    def _extract_llm_response_text(self, response: Any) -> str:
        """兼容 OpenAI SDK 对象、dict 响应和字符串响应。"""
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            try:
                return response["choices"][0]["message"]["content"]
            except Exception:
                return json.dumps(response, ensure_ascii=False)
        try:
            return response.choices[0].message.content
        except Exception:
            return str(response)

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

    def _build_visual_perception_messages(self, user_prompt: str) -> List[Dict[str, str]]:
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
当前步骤是否完成：[true/false]
决策理由：[为什么这样操作]

【示例】
操作类型：click
目标元素：返回
当前步骤是否完成：true
决策理由：点击返回按钮

操作类型：input
目标元素：默认文本: 搜索
输入内容：周杰伦演唱会
当前步骤是否完成：true
决策理由：在搜索框输入关键词

操作类型：done
当前步骤是否完成：true
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
当前步骤是否完成：true
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
当前步骤是否完成：true
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
当前步骤是否完成：true
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
            if "```json" in response_clean or response_clean.startswith("{") or "{" in response_clean:
                decision = self._extract_json_from_response(response_clean)
                return self._normalize_decision_fields(decision)

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
                "reasoning": "",
                "step_completed": None
            }

            lines = response.split('\n')

            # 找到第一个操作块（从"操作类型："到下一个"操作类型："或结束）
            first_action_found = False
            current_action = {
                "action": "unknown",
                "target": "",
                "parameters": {},
                "reasoning": "",
                "step_completed": None
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

                # 解析当前步骤是否完成
                elif (
                    line.startswith("当前步骤是否完成：")
                    or line.startswith("当前步骤是否完成:")
                    or line.startswith("是否完成当前步骤：")
                    or line.startswith("是否完成当前步骤:")
                    or line.startswith("step_completed:")
                    or line.startswith("step_completed：")
                ):
                    bool_value = line.split('：', 1)[-1].split(':', 1)[-1].strip()
                    current_action["step_completed"] = self._parse_bool_value(bool_value)

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
                "reasoning": reasoning if reasoning else response_clean[:200],
                "step_completed": None
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
                "reasoning": response[:200],
                "step_completed": None
            }

    def _normalize_decision_fields(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """统一 JSON/键值对决策字段，兼容中文字段名。"""
        if not isinstance(decision, dict):
            return decision

        if "step_completed" not in decision:
            for key in ["当前步骤是否完成", "是否完成当前步骤", "completed", "is_completed"]:
                if key in decision:
                    decision["step_completed"] = self._parse_bool_value(decision.get(key))
                    break
        elif not isinstance(decision.get("step_completed"), bool):
            decision["step_completed"] = self._parse_bool_value(decision.get("step_completed"))

        decision.setdefault("parameters", {})
        decision.setdefault("reasoning", "")
        return decision

    def _parse_bool_value(self, value: Any) -> Optional[bool]:
        """解析模型输出中的 true/false 布尔值。无法识别时返回 None。"""
        if isinstance(value, bool):
            return value
        if value is None:
            return None

        value_str = str(value).strip().lower()
        if value_str in {"true", "yes", "y", "1", "是", "完成", "已完成"}:
            return True
        if value_str in {"false", "no", "n", "0", "否", "未完成", "没有完成"}:
            return False
        return None

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
