"""
语义匹配模块 - 使用 BGE 模型进行快速元素匹配

作为第一道防线，在调用 LLM 之前先进行语义匹配。
如果匹配成功（相似度 > 阈值），直接返回结果，避免昂贵的 LLM 调用。
如果匹配失败，降级到 LLM 进行智能决策。
"""

import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, Tuple
from dataclasses import dataclass
import numpy as np

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """匹配结果"""
    element: Dict[str, Any]
    score: float
    method: str  # 'bge' or 'llm'
    all_candidates: Optional[List[Dict[str, Any]]] = None  # 所有候选元素及分数（可选）


class SemanticMatcher:
    """语义匹配器"""

    def __init__(
        self,
        model_path: Optional[str] = None,
        threshold: float = 0.75,
        cache_size: int = 5,
        device: str = 'cpu'
    ):
        """
        初始化语义匹配器

        Args:
            model_path: BGE 模型路径
            threshold: 相似度阈值，高于此值直接返回，不调用 LLM
            cache_size: 缓存屏幕向量数量
            device: 运行设备 ('cpu' 或 'cuda')
        """
        self.threshold = threshold
        self.cache_size = cache_size
        self.device = device

        # 缓存：{screen_hash: (encodings, timestamp)}
        self._cache = {}

        # 加载模型
        if model_path is None:
            model_path = Path(__file__).parent.parent.parent.parent / "external" / "models" / "bge-small-zh-v1.5"

        model_path = Path(model_path)
        if not model_path.exists():
            raise ValueError(f"❌ BGE 模型不存在: {model_path}")

        logger.info(f"🔄 加载 BGE 模型: {model_path}")

        # 加载本地模型（强制使用本地文件）
        import os
        original_cwd = os.getcwd()

        # 切换到模型目录的父目录，然后使用相对路径
        os.chdir(str(model_path.parent))
        try:
            self.model = SentenceTransformer(
                model_path.name,
                device=device,
                cache_folder=str(model_path.parent),
                local_files_only=True  # 关键：强制只使用本地文件
            )
        finally:
            os.chdir(original_cwd)

        logger.info(f"✅ BGE 模型加载完成 (设备: {device})")

    def match_or_fallback(
        self,
        target: str,
        candidates: List[Dict[str, Any]],
        fallback_func: Callable,
        **fallback_kwargs
    ) -> Dict[str, Any]:
        """
        语义匹配或降级到 LLM

        Args:
            target: 目标查询文本（如 "点击登录按钮"）
            candidates: 候选元素列表
            fallback_func: 降级函数（LLM 匹配函数）
            **fallback_kwargs: 传递给 fallback_func 的额外参数

        Returns:
            匹配的元素
        """
        # 1. 检查候选列表
        if not candidates:
            logger.warning("⚠️ 候选元素列表为空，直接调用 LLM")
            return fallback_func(target, candidates, **fallback_kwargs)

        # 2. BGE 快速匹配
        try:
            result = self._bge_match(target, candidates)

            if result.score >= self.threshold:
                logger.info(
                    f"✅ BGE 匹配成功: score={result.score:.3f} ≥ {self.threshold} "
                    f"(元素: {self._get_element_name(result.element)})"
                )
                return result.element
            else:
                logger.info(
                    f"⚠️ BGE 未匹配: score={result.score:.3f} < {self.threshold}，降级到 LLM"
                )

        except Exception as e:
            logger.error(f"❌ BGE 匹配出错: {e}，降级到 LLM")

        # 3. 降级到 LLM
        logger.info(f"🤖 调用 LLM 进行智能决策 (目标: {target})")
        llm_result = fallback_func(target, candidates, **fallback_kwargs)
        return llm_result

    def _bge_match(self, target: str, candidates: List[Dict[str, Any]]) -> MatchResult:
        """
        BGE 核心匹配逻辑

        Args:
            target: 目标查询
            candidates: 候选元素列表（ForensiVision 输出格式）

        Returns:
            MatchResult 包含最佳匹配元素、分数和所有候选
        """
        # 1. 过滤和展开候选元素
        valid_elements = []
        for elem in candidates:
            # 跳过字符串元素（如 "alignment: v"）
            if isinstance(elem, str):
                continue

            # 如果是字典且包含 children，递归展开
            if isinstance(elem, dict) and 'children' in elem:
                children = self._extract_elements_recursive(elem)
                valid_elements.extend(children)
            elif isinstance(elem, dict):
                valid_elements.append(elem)

        if not valid_elements:
            # 如果没有有效元素，返回低分结果
            return MatchResult(element={}, score=0.0, method='bge', all_candidates=[])

        # 2. 构建候选文本
        candidate_texts = [self._build_element_text(c) for c in valid_elements]

        # 3. 编码
        target_emb = self.model.encode(target, convert_to_numpy=True, show_progress_bar=False)
        candidate_embs = self._get_cached_encodings(candidate_texts)

        # 4. 计算相似度
        scores = self._cosine_similarity(target_emb, candidate_embs)

        # 5. 返回最高分
        max_idx = int(np.argmax(scores))
        max_score = float(scores[max_idx])

        # 6. 构建所有候选元素及其分数的列表
        all_candidates = []
        for i, (elem, score) in enumerate(zip(valid_elements, scores)):
            all_candidates.append({
                "rank": i + 1,
                "score": float(score),
                "element": elem,
                "element_text": elem.get('text_content', 'Unknown'),
                "element_class": elem.get('class', 'Unknown'),
                "element_id": elem.get('id', 'Unknown')
            })

        # 按分数排序
        all_candidates.sort(key=lambda x: x['score'], reverse=True)

        return MatchResult(
            element=valid_elements[max_idx],
            score=max_score,
            method='bge',
            all_candidates=all_candidates
        )

    def _extract_elements_recursive(self, element: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        递归提取元素（处理嵌套的 Block 结构）

        Args:
            element: 元素字典

        Returns:
            扁平化的元素列表
        """
        elements = []

        # 如果是叶子节点（有 text_content），添加到列表
        if 'text_content' in element and element['text_content']:
            elements.append(element)

        # 如果有 children，递归处理
        if 'children' in element and element['children']:
            for child in element['children']:
                elements.extend(self._extract_elements_recursive(child))

        return elements

    def _build_element_text(self, element: Dict[str, Any]) -> str:
        """
        构建元素描述文本（适配 ForensiVision 格式）

        Args:
            element: 元素字典（ForensiVision 格式）

        Returns:
            描述文本
        """
        parts = []

        # ForensiVision 格式的字段
        if element.get('text_content'):
            parts.append(f"文字:{element['text_content']}")

        if element.get('class'):
            # 使用完整类名（Compo, Text, Block 等）
            class_name = element.get('class')
            parts.append(f"类型:{class_name}")

        if element.get('sub_class'):
            sub_class = element.get('sub_class')
            parts.append(f"子类型:{sub_class}")

        return '，'.join(parts) if parts else "未知元素"

    def _get_cached_encodings(self, texts: List[str]) -> np.ndarray:
        """
        获取缓存的编码或重新编码

        Args:
            texts: 文本列表

        Returns:
            编码向量数组
        """
        # 生成屏幕哈希（基于所有文本）
        screen_hash = self._hash_texts(texts)

        # 检查缓存
        if screen_hash in self._cache:
            logger.debug(f"💾 命中缓存: {screen_hash[:8]}")
            return self._cache[screen_hash]

        # 编码
        logger.debug(f"🔄 编码 {len(texts)} 个候选元素")
        encodings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

        # 缓存
        self._cache[screen_hash] = encodings

        # 限制缓存大小
        if len(self._cache) > self.cache_size:
            # 删除最旧的缓存
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            logger.debug(f"🗑️ 清理缓存: {oldest_key[:8]}")

        return encodings

    def _hash_texts(self, texts: List[str]) -> str:
        """生成文本列表的哈希值"""
        combined = '|'.join(texts)
        return hashlib.md5(combined.encode()).hexdigest()

    @staticmethod
    def _cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> np.ndarray:
        """
        计算余弦相似度

        Args:
            vec1: 向量 (D,)
            vec2: 向量矩阵 (N, D)

        Returns:
            相似度数组 (N,)
        """
        dot = np.dot(vec2, vec1)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2, axis=1)
        return dot / (norm1 * norm2 + 1e-8)

    @staticmethod
    def _get_element_name(element: Dict[str, Any]) -> str:
        """获取元素名称（用于日志）"""
        name = element.get('text') or element.get('content-desc') or element.get('class', 'Unknown')
        return name[:30]  # 限制长度


class SemanticMatcherMock:
    """
    语义匹配器的 Mock 版本（用于测试）
    直接调用 LLM，不进行 BGE 匹配
    """

    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ 使用 SemanticMatcher Mock（直接调用 LLM）")

    def match_or_fallback(
        self,
        target: str,
        candidates: List[Dict[str, Any]],
        fallback_func: Callable,
        **fallback_kwargs
    ) -> Dict[str, Any]:
        """直接调用 fallback"""
        logger.info(f"🤖 Mock 模式：直接调用 LLM (目标: {target})")
        return fallback_func(target, candidates, **fallback_kwargs)
