# -*- coding: utf-8 -*-
"""查询规划器：一次 LLM 调用完成「指代改写 + 意图路由 + 实体抽取」。

为什么合并成一次：
- 拆成三步就是三次往返，多约 1.5s 延迟和三次计费；
- 三次独立调用对「问题里提到了谁」可能给出不一致的答案，后面链路就崩了。

LLM 结果不可靠时要有确定性兜底，所以下面保留了一套纯规则的降级方案。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from tcmqa.kg.linker import EntityLinker
from tcmqa.llm.client import LLMClient, LLMError
from tcmqa.llm.prompts import PLANNER_SYSTEM
from tcmqa.tracing import Trace

logger = logging.getLogger(__name__)

VALID_INTENTS = {
    "lookup",
    "relation",
    "aggregate",
    "mechanism",
    "semantic",
    "chitchat",
    "out_of_scope",
}

# 意图 → 默认走哪条检索路
INTENT_ROUTE: dict[str, tuple[bool, bool]] = {
    "lookup": (True, False),
    "relation": (True, False),
    "aggregate": (True, False),
    "mechanism": (True, True),
    "semantic": (False, True),
    "chitchat": (False, False),
    "out_of_scope": (False, False),
}

OUT_OF_SCOPE_PATTERNS = (
    r"剂量", r"多少克", r"吃几", r"处方", r"开药", r"怎么治", r"能不能治好",
    r"诊断", r"我是不是", r"化验", r"报告单",
)

CHITCHAT_PATTERNS = (
    r"^(你好|您好|hi|hello|在吗|测试)",
    r"(你能做什么|你会什么|能干什么|怎么用|使用说明|帮助)",
)


@dataclass
class PlannedEntity:
    text: str
    etype: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class QueryPlan:
    intent: str
    rewritten_query: str
    entities: list[PlannedEntity] = field(default_factory=list)
    needs_graph: bool = True
    needs_vector: bool = False
    effects: list[str] = field(default_factory=list)
    source: str = "llm"  # llm | fallback
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "rewritten_query": self.rewritten_query,
            "entities": [
                {"text": e.text, "type": e.etype, "aliases": e.aliases[:5]}
                for e in self.entities
            ],
            "needs_graph": self.needs_graph,
            "needs_vector": self.needs_vector,
            "effects": self.effects,
            "source": self.source,
        }


def _heuristic_intent(question: str) -> str:
    q = question.strip()
    if any(re.search(p, q, re.IGNORECASE) for p in CHITCHAT_PATTERNS):
        return "chitchat"
    if any(re.search(p, q) for p in OUT_OF_SCOPE_PATTERNS):
        return "out_of_scope"
    if re.search(r"(为什么|机制|原理|通路|怎么起效|如何起效)", q):
        return "mechanism"
    if re.search(r"(多少|几种|几个|最多|最少|排名|排序|对比|统计)", q):
        return "aggregate"
    # 语义类必须排在「有哪些/什么」之前：否则「手脚冰凉适合吃什么」会被当成关系查询
    if re.search(r"(适合|调理|体质|症状|上火|怕冷|冰凉|失眠|气血|养生)", q):
        return "semantic"
    if re.search(r"(有哪些|什么|哪些|列出|列举|包括)", q):
        return "relation"
    return "relation"


class Planner:
    def __init__(self, llm: LLMClient, linker: EntityLinker, settings=None) -> None:
        self.llm = llm
        self.linker = linker
        self.settings = settings

    # ------------------------------------------------------------------ #
    def plan(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        trace: Trace | None = None,
    ) -> QueryPlan:
        history_text = self._render_history(history)

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM},
            {
                "role": "user",
                "content": (
                    (f"## 最近对话\n{history_text}\n\n" if history_text else "")
                    + f"## 当前问题\n{question}"
                ),
            },
        ]

        try:
            if trace is not None:
                with trace.span("plan"):
                    data, result = self.llm.chat_json(messages, temperature=0.0, max_tokens=600)
                    trace.record_llm(
                        "plan", result.model, result.prompt_tokens,
                        result.completion_tokens, result.latency_ms,
                    )
            else:
                data, _ = self.llm.chat_json(messages, temperature=0.0, max_tokens=600)
            plan = self._from_payload(data, question)
        except (LLMError, ValueError, KeyError) as exc:
            logger.warning("规划器降级为规则：%s", exc)
            plan = self._fallback(question)

        plan.effects = self.linker.detect_effects(plan.rewritten_query)
        if plan.effects:
            # 提到功效分类（"清热解毒的药"）时，语义检索一定有用
            plan.needs_vector = True

        # 消融实验：强制关掉向量分支
        if self.settings is not None and getattr(self.settings, "ablate_vector", False):
            plan.needs_vector = False
            if not plan.needs_graph:
                plan.needs_graph = True

        return plan

    # ------------------------------------------------------------------ #
    def _from_payload(self, data: dict[str, Any], question: str) -> QueryPlan:
        intent = str(data.get("intent") or "").strip()
        if intent not in VALID_INTENTS:
            intent = _heuristic_intent(question)

        entities: list[PlannedEntity] = []
        for raw in data.get("entities") or []:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            etype = str(raw.get("type") or "Herb").strip()
            if etype not in ("Herb", "Ingredient", "Target", "Disease"):
                etype = "Herb"
            aliases = [
                str(a).strip() for a in (raw.get("aliases") or []) if str(a).strip()
            ][:6]
            entities.append(PlannedEntity(text=text, etype=etype, aliases=aliases))

        default_graph, default_vector = INTENT_ROUTE.get(intent, (True, False))
        needs_graph = bool(data.get("needs_graph", default_graph))
        needs_vector = bool(data.get("needs_vector", default_vector))

        rewritten = str(data.get("rewritten_query") or "").strip() or question

        return QueryPlan(
            intent=intent,
            rewritten_query=rewritten,
            entities=entities,
            needs_graph=needs_graph,
            needs_vector=needs_vector,
            source="llm",
            raw=data,
        )

    def _fallback(self, question: str) -> QueryPlan:
        intent = _heuristic_intent(question)
        needs_graph, needs_vector = INTENT_ROUTE.get(intent, (True, False))
        return QueryPlan(
            intent=intent,
            rewritten_query=question,
            entities=[],
            needs_graph=needs_graph,
            needs_vector=needs_vector,
            source="fallback",
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _render_history(history: list[dict[str, str]] | None) -> str:
        if not history:
            return ""
        lines = []
        for msg in history[-6:]:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = str(msg.get("content") or "").strip().replace("\n", " ")
            if content:
                lines.append(f"{role}：{content[:200]}")
        return "\n".join(lines)
