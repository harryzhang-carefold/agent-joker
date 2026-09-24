"""本地 fallback embedding（S03，LLM-02 闭环兜底）。

确定性字符 n-gram 哈希向量：
- 同一文本永远返回同一向量（无随机、无外部依赖）
- 接口与真实 endpoint 一致（list[float]，维度 = LLM_LOCAL_FALLBACK_DIM，默认 256）
- 用途：真实 embedding 端点不可用时的自测闭环（card_common 明确允许）

算法：
1. 归一化（lowercase + 空白折叠，ASCII 折叠不做——保留 Unicode 字符）
2. 取 (n-1)-gram 与 n-gram（n=LLM_LOCAL_FALLBACK_NGRAM，默认 3）；短文本（<n）整体+首尾补界
3. 每个 gram 用 fnv1a64 哈希 → 桶索引 = h % dim，符号 = (h>>61)&1
4. 累加到向量后 L2 归一化（零向量返回全 0）
"""
from __future__ import annotations

import re
from typing import Sequence

from joker_shared.config import settings

_WS = re.compile(r"\s+")


def _fnv1a64(s: str) -> int:
    h = 0xCBF29CE484222325
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def local_fallback_embedding(text: str, dim: int | None = None) -> list[float]:
    """确定性向量（维度默认取 settings.LLM_LOCAL_FALLBACK_DIM）。"""
    dim = dim or settings.LLM_LOCAL_FALLBACK_DIM
    n = settings.LLM_LOCAL_FALLBACK_NGRAM
    if dim <= 0:
        raise ValueError("dim must be > 0")
    norm = _WS.sub(" ", (text or "").strip().lower())
    if len(norm) < n:
        grams = [f"§{norm}§"] if norm else []
    else:
        grams = [norm[i : i + n - 1] for i in range(len(norm) - n + 2)]
        grams += [norm[i : i + n] for i in range(len(norm) - n + 1)]
    vec = [0.0] * dim
    for g in grams:
        h = _fnv1a64(g)
        idx = h % dim
        sign = -1.0 if (h >> 61) & 1 else 1.0
        vec[idx] += sign
    sq = sum(v * v for v in vec)
    if sq > 0:
        inv = 1.0 / sq ** 0.5
        vec = [v * inv for v in vec]
    return vec


def local_fallback_embeddings(texts: Sequence[str], dim: int | None = None) -> list[list[float]]:
    return [local_fallback_embedding(t, dim) for t in texts]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度（自测/调试用）。"""
    if len(a) != len(b):
        raise ValueError("dimension mismatch")
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)
