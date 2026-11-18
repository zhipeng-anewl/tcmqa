# -*- coding: utf-8 -*-
"""评测指标与 LLM 评审。

指标分三层，对应三个失败来源：
1. **路由准确率**：意图判断错了，后面检索必然跑偏；
2. **执行准确率**：Cypher 跑出来的结果集对不对（用集合精度/召回衡量）；
3. **答案质量**：生成的事实是否被证据支持（faithfulness）、是否切题（relevance）。

关于「结果集很大时只算精度」：系统受 LIMIT 约束，标准答案可能有 190 个成分而
系统只返回 20 个，这时算召回没有意义。所以规则是：标准集 ≤30 时算 F1，
否则只算精度（返回的都对就算通过）。这个取舍会写进报告，不藏。
"""

from __future__ import annotations

import json
import re
from typing import Any

from tcmqa.llm.client import LLMClient, LLMError
from tcmqa.llm.prompts import (
    JUDGE_ANSWER_VS_GOLD_SYSTEM,
    JUDGE_FAITHFULNESS_SYSTEM,
    JUDGE_RELEVANCE_SYSTEM,
)

SMALL_GOLD = 30


# ---------------------------------------------------------------------- #
# 集合类
# ---------------------------------------------------------------------- #
def extract_values(rows: list[dict[str, Any]], label: str, universe: set[str]) -> set[str]:
    """从结果行里抽出「属于该标签的实体名」。

    不依赖列名，避免系统把列起成 ingredient 还是 name 影响判分。
    """
    values: set[str] = set()
    for row in rows:
        for value in row.values():
            if isinstance(value, str) and value in universe:
                values.add(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item in universe:
                        values.add(item)
    return values


def set_scores(pred: set[str], gold: set[str]) -> dict[str, float]:
    if not pred and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    hit = len(pred & gold)
    precision = hit / len(pred)
    recall = hit / len(gold) if gold else 0.0

    if len(gold) > SMALL_GOLD:
        # 标准集大于 LIMIT，召回不可比，只评精度
        return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(precision, 4)}

    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


# ---------------------------------------------------------------------- #
# 数值类
# ---------------------------------------------------------------------- #
def numbers_in(obj: Any, depth: int = 0) -> list[float]:
    if depth > 4:
        return []
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", obj) if len(x) < 12]
    if isinstance(obj, dict):
        out: list[float] = []
        for v in obj.values():
            out.extend(numbers_in(v, depth + 1))
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for v in obj:
            out.extend(numbers_in(v, depth + 1))
        return out
    return []


def number_matches(pred_values: list[float], gold: float, tolerance: float) -> bool:
    if gold == 0:
        return any(abs(v) <= max(tolerance, 1e-6) for v in pred_values)
    return any(abs(v - gold) / abs(gold) <= tolerance for v in pred_values)


# ---------------------------------------------------------------------- #
# 统计
# ---------------------------------------------------------------------- #
def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    idx = (len(ordered) - 1) * p
    low = int(idx)
    high = min(low + 1, len(ordered) - 1)
    frac = idx - low
    return round(ordered[low] * (1 - frac) + ordered[high] * frac, 2)


# ---------------------------------------------------------------------- #
# LLM 评审
# ---------------------------------------------------------------------- #
def _judge(llm: LLMClient, system: str, user: str) -> dict[str, Any]:
    try:
        data, _ = llm.chat_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            max_tokens=400,
        )
        return data
    except (LLMError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def judge_faithfulness(llm: LLMClient, answer: str, evidence_text: str) -> dict[str, Any]:
    return _judge(
        llm,
        JUDGE_FAITHFULNESS_SYSTEM,
        f"## 证据\n{evidence_text[:4000]}\n\n## 回答\n{answer[:2000]}",
    )


def judge_relevance(llm: LLMClient, question: str, answer: str) -> dict[str, Any]:
    return _judge(
        llm, JUDGE_RELEVANCE_SYSTEM, f"## 问题\n{question}\n\n## 回答\n{answer[:2000]}"
    )


def judge_answer(llm: LLMClient, question: str, answer: str, reference: str) -> dict[str, Any]:
    return _judge(
        llm,
        JUDGE_ANSWER_VS_GOLD_SYSTEM,
        f"## 问题\n{question}\n\n## 标准答案（自动从图谱算出）\n{reference[:2000]}\n\n"
        f"## 系统回答\n{answer[:2000]}",
    )
