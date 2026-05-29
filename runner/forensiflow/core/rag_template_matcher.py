"""
RAG 模板匹配模块 - 使用 bge-large-zh-v1.5 进行任务模板检索

功能：
1. 加载和管理任务模板库
2. 使用 BGE 模型进行语义检索
3. 返回 Top-K 最相似的任务模板
4. 为 LLM 提供 Few-Shot 参考案例
"""

import json
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import numpy as np

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


def _template_package_name(template: Dict[str, Any]) -> str:
    if template.get("package_name"):
        return str(template.get("package_name") or "")
    steps = template.get("steps")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        return str(steps[0].get("package_name") or "")
    return ""


def _template_script_name(template: Dict[str, Any]) -> str:
    script_generation = template.get("script_generation") if isinstance(template.get("script_generation"), dict) else {}
    if script_generation.get("script_name"):
        return str(script_generation.get("script_name") or "")
    steps = template.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and str(step.get("action") or "").lower() == "callscript":
                return str(step.get("target") or "")
    return ""


_PACKAGE_APP_NAMES = {
    "com.android.chrome": "Chrome",
    "com.google.android.gm": "Gmail",
    "com.google.android.apps.maps": "Google Maps",
    "com.whatsapp": "WhatsApp",
}


def _canonical_app_name_for_package(package_name: str) -> str:
    return _PACKAGE_APP_NAMES.get(str(package_name or "").strip(), "")


def _is_reusable_extraction_template(template: Dict[str, Any]) -> bool:
    if template.get("template_type") == "navigation_only":
        return False
    if template.get("script_generation_success") is False:
        return False
    steps = template.get("steps")
    if not isinstance(steps, list) or not steps:
        return False
    first = steps[0] if isinstance(steps[0], dict) else {}
    if str(first.get("action") or "").lower() != "launch":
        return False
    return bool(_template_package_name(template) and _template_script_name(template))


def _normalize_app_name(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    for token in (" messenger", " app", " application"):
        normalized = normalized.replace(token, "")
    return normalized.strip()


def _task_mentions_app(task: str, app: str) -> bool:
    task_norm = str(task or "").casefold()
    app_norm = _normalize_app_name(app)
    aliases = {
        "chrome": ["chrome", "浏览器", "历史记录", "下载记录", "书签"],
        "gmail": ["gmail", "邮件", "收件箱", "发件箱", "inbox", "sent"],
        "google maps": ["google maps", "maps", "地图", "地点", "路线", "saved"],
    }
    for alias in aliases.get(app_norm, [app_norm]):
        if alias and alias in task_norm:
            return True
    return False


@dataclass
class TemplateMatch:
    """模板匹配结果"""
    template: Dict[str, Any]
    score: float
    rank: int


class RAGTemplateMatcher:
    """RAG 模板匹配器"""

    def __init__(
        self,
        model_path: Optional[str] = None,
        templates_dir: Optional[str] = None,
        top_k: int = 3,
        device: str = 'cpu'
    ):
        """
        初始化 RAG 模板匹配器

        Args:
            model_path: BGE 模型路径
            templates_dir: 模板目录
            top_k: 返回前 K 个最相似的模板
            device: 运行设备
        """
        self.top_k = top_k
        self.device = device

        # 模板库
        self.templates = {}  # {app_name: [templates]}
        self.template_embeddings = {}  # {app_name: np.ndarray}

        # 加载模型
        if model_path is None:
            model_path = Path(__file__).parent.parent.parent.parent / "external" / "models" / "bge-large-zh-v1.5"

        model_path = Path(model_path)
        if not model_path.exists():
            raise ValueError(f"❌ BGE 模型不存在: {model_path}")

        logger.info(f"🔄 加载 BGE-Large 模型: {model_path}")

        # 加载本地模型
        import os
        original_cwd = os.getcwd()
        os.chdir(str(model_path.parent))
        try:
            self.model = SentenceTransformer(
                model_path.name,
                device=device,
                cache_folder=str(model_path.parent),
                local_files_only=True
            )
        finally:
            os.chdir(original_cwd)

        logger.info(f"✅ BGE-Large 模型加载完成 (设备: {device})")

        # 加载模板
        if templates_dir is None:
            templates_dir = Path(__file__).parent.parent.parent.parent / "external" / "rag_templates"

        templates_dir = Path(templates_dir)
        if templates_dir.exists():
            self._load_templates(templates_dir)
            logger.info(f"✅ 已加载 {sum(len(v) for v in self.templates.values())} 个模板")
        else:
            logger.warning(f"⚠️  模板目录不存在: {templates_dir}")
            self.templates = {}

    def _load_templates(self, templates_dir: Path):
        """加载模板文件（只加载 all_templates.json）"""
        # 只加载 all_templates.json 文件
        all_templates_file = templates_dir / "all_templates.json"

        if not all_templates_file.exists():
            logger.warning(f"   ⚠️  all_templates.json 不存在，尝试加载其他模板文件")
            # 如果 all_templates.json 不存在，则加载所有 JSON 文件（回退行为）
            for template_file in templates_dir.glob("*.json"):
                self._load_single_template_file(template_file)
            return

        # 只加载 all_templates.json
        self._load_single_template_file(all_templates_file)

    def _load_single_template_file(self, template_file: Path):
        """加载单个模板文件"""
        try:
            with open(template_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 支持两种格式
            if isinstance(data, list):
                templates = data
            elif isinstance(data, dict) and 'templates' in data:
                templates = data['templates']
            else:
                logger.warning(f"   ⚠️  跳过不支持的格式: {template_file.name}")
                return

            # 按应用分组
            for template in templates:
                if not _is_reusable_extraction_template(template):
                    logger.info(f"   ⏭️  跳过非可复用提取模板: {template.get('task', '')}")
                    continue
                template = dict(template)
                package_name = _template_package_name(template)
                canonical_app = _canonical_app_name_for_package(package_name)
                if canonical_app and _normalize_app_name(template.get("app", "")) != _normalize_app_name(canonical_app):
                    template["original_app"] = template.get("app", "")
                    template["app"] = canonical_app
                app = template.get('app', 'Unknown')
                if app not in self.templates:
                    self.templates[app] = []

                self.templates[app].append(template)

            logger.info(f"   📄 加载模板: {template_file.name} ({len(templates)} 个)")

        except Exception as e:
            logger.error(f"   ❌ 加载模板失败 {template_file}: {e}")

        # 预计算所有模板的向量
        self._precompute_embeddings()

    def _precompute_embeddings(self):
        """预计算所有模板的向量"""
        for app, templates in self.templates.items():
            if not templates:
                continue

            # 提取任务描述
            task_descriptions = [t.get('task', '') for t in templates]
            embeddings = self.model.encode(task_descriptions, convert_to_numpy=True, show_progress_bar=False)

            # 标准化
            embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

            self.template_embeddings[app] = {
                'embeddings': embeddings,
                'templates': templates
            }

        logger.info(f"   ✅ 已预计算 {sum(len(v['templates']) for v in self.template_embeddings.values())} 个模板向量")

    def search(
        self,
        app: str,
        task: str,
        package_name: str = "",
        top_k: Optional[int] = None
    ) -> List[TemplateMatch]:
        """
        搜索最相似的任务模板

        Args:
            app: 应用名称
            task: 任务描述
            top_k: 返回前 K 个结果

        Returns:
            匹配结果列表
        """
        if top_k is None:
            top_k = self.top_k

        requested_package = str(package_name or "").strip()
        # 检查应用是否有模板；兼容 WhatsApp / WhatsApp Messenger 这类命名差异。
        app_keys = [app] if app in self.template_embeddings else []
        if not app_keys:
            requested = _normalize_app_name(app)
            app_keys = [key for key in self.template_embeddings if _normalize_app_name(key) == requested]
        if not app_keys and requested_package:
            package_app = _canonical_app_name_for_package(requested_package)
            if package_app:
                app_keys = [key for key in self.template_embeddings if _normalize_app_name(key) == _normalize_app_name(package_app)]
            if not app_keys:
                app_keys = [
                    key
                    for key, template_data in self.template_embeddings.items()
                    if any(_template_package_name(template) == requested_package for template in template_data["templates"])
                ]
            if app_keys:
                logger.warning(f"⚠️  应用 [{app}] 无直接模板，按 package [{requested_package}] 使用候选: {app_keys}")
        if not app_keys:
            logger.warning(f"⚠️  应用 [{app}] 没有模板，启用全库兜底检索")
            app_keys = list(self.template_embeddings.keys())

        # 编码查询
        query_emb = self.model.encode(task, convert_to_numpy=True, show_progress_bar=False)
        query_emb = query_emb / np.linalg.norm(query_emb)

        # 计算相似度
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for app_key in app_keys:
            template_data = self.template_embeddings[app_key]
            embeddings = template_data['embeddings']
            templates = template_data['templates']
            scores = np.dot(embeddings, query_emb)
            for score, template in zip(scores, templates):
                package_name = _template_package_name(template)
                if requested_package and package_name and package_name != requested_package:
                    continue
                if package_name and app_keys != [app] and not _task_mentions_app(task, template.get("app", "")):
                    requested_app = _normalize_app_name(app)
                    template_app = _normalize_app_name(template.get("app", ""))
                    if requested_app and template_app and requested_app != template_app:
                        score = float(score) * 0.9
                scored.append((float(score), template))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [
            TemplateMatch(template=template, score=score, rank=rank + 1)
            for rank, (score, template) in enumerate(scored[:top_k])
        ]

        logger.info(f"🔍 RAG 检索: 应用=[{app}], package=[{requested_package}], 任务=[{task}]")
        if results:
            logger.info(f"   最佳匹配: rank=1, score={results[0].score:.3f}")

        return results

    def get_best_template(
        self,
        app: str,
        task: str,
        threshold: float = 0.75
    ) -> Optional[Dict[str, Any]]:
        """
        获取最佳模板（如果满足阈值）

        Args:
            app: 应用名称
            task: 任务描述
            threshold: 相似度阈值

        Returns:
            模板字典，如果未满足阈值则返回 None
        """
        results = self.search(app, task, top_k=1)

        if results and results[0].score >= threshold:
            return results[0].template

        return None

    def format_prompt_examples(
        self,
        matches: List[TemplateMatch],
        max_examples: int = 3
    ) -> str:
        """
        格式化提示词示例（原始 JSON 格式）

        Args:
            matches: 匹配结果列表
            max_examples: 最多显示示例数

        Returns:
            格式化的示例文本（JSON 格式）
        """
        if not matches:
            return ""

        examples = []

        # 添加说明头部
        header = """
## 📚 参考案例（相似历史任务）
以下是与你当前任务相似的历史任务案例，请直接参考其结构：
"""
        examples.append(header)

        import json

        for i, match in enumerate(matches[:max_examples]):
            template = match.template

            # 构建 JSON 对象（包含相似度）
            example_obj = {
                "相似度": f"{match.score:.2f}",
                "app": template.get('app', 'Unknown'),
                "task": template.get('task', ''),
                "steps": template.get('steps', [])
            }

            # 格式化为 JSON 字符串
            example_json = json.dumps(example_obj, ensure_ascii=False, indent=2)
            example = f"""
```json
{example_json}
```
"""
            examples.append(example)

        return '\n'.join(examples)

    def add_template(
        self,
        app: str,
        task: str,
        steps: List[Dict[str, Any]],
        save_path: Optional[str] = None
    ):
        """
        动态添加新模板

        Args:
            app: 应用名称
            task: 任务描述
            steps: 执行步骤
            save_path: 保存路径（可选）
        """
        template = {
            'app': app,
            'task': task,
            'steps': steps,
            'created_at': str(np.datetime64('now'))
        }

        # 添加到内存
        if app not in self.templates:
            self.templates[app] = []

        self.templates[app].append(template)

        # 更新向量
        self._precompute_embeddings()

        # 可选：保存到文件
        if save_path:
            self._save_template(template, save_path)

        logger.info(f"✅ 已添加新模板: {task}")

    def _save_template(self, template: Dict[str, Any], save_path: str):
        """保存模板到文件"""
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # 读取现有模板
        templates = []
        if save_path.exists():
            with open(save_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    templates = data
                elif isinstance(data, dict) and 'templates' in data:
                    templates = data['templates']

        templates.append(template)

        # 保存
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=4)


class RAGTemplateMatcherMock:
    """RAG 模板匹配器的 Mock 版本"""
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️  使用 RAG 模板匹配器 Mock（直接返回空结果）")

    def search(self, app: str, task: str, top_k: int = 3):
        return []

    def get_best_template(self, app: str, task: str, threshold: float = 0.75):
        return None

    def format_prompt_examples(self, matches, max_examples=3):
        return ""
