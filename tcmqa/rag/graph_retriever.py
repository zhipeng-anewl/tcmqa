# -*- coding: utf-8 -*-
"""Text2Cypher 检索器（带自修复）。

LLM 一次写对 Cypher 的概率远没有想象中高——标签名、属性名、跨语言实体名
任何一处出错都会失败。所以这里做成「生成 → 校验 → 执行 → 失败回灌错误重写」的闭环，
并显式覆盖两种失败：

1. **执行报错**（语法/标签不存在）：把 Neo4j 的报错原文回灌，修复率很高；
2. **执行成功但 0 行**：多半是实体名不匹配（中文问、英文存），
   这时提示模型放宽为 CONTAINS 或改用已解析到的候选名。

没有这个闭环，实测端到端成功率大概六七成；加上闭环后能到九成以上，
而且成本只增加失败那部分请求。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from tcmqa.kg.client import CypherRuntimeError, GraphClient, GraphError
from tcmqa.kg.guard import CypherGuard, strip_code_fence
from tcmqa.kg.linker import EntityLinker, LinkResult
from tcmqa.kg.schema import build_schema_text
from tcmqa.llm.client import LLMClient
from tcmqa.llm.prompts import CYPHER_REPAIR_USER, CYPHER_SYSTEM
from tcmqa.rag.few_shots import FewShotLibrary
from tcmqa.rag.planner import QueryPlan
from tcmqa.settings import Settings, get_settings
from tcmqa.tracing import Trace

logger = logging.getLogger(__name__)


@dataclass
class Attempt:
    cypher: str
    ok: bool
    rows: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cypher": self.cypher,
            "ok": self.ok,
            "rows": self.rows,
            "error": self.error,
        }


@dataclass
class GraphResult:
    cypher: str = ""
    rows: list[dict[str, Any]] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.rows)

    @property
    def repairs(self) -> int:
        return max(0, len(self.attempts) - 1)


class GraphRetriever:
    def __init__(
        self,
        client: GraphClient,
        llm: LLMClient,
        linker: EntityLinker,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.llm = llm
        self.linker = linker
        self.settings = settings or get_settings()
        self.guard = CypherGuard(max_rows=self.settings.neo4j_max_rows)
        self.few_shots = FewShotLibrary()
        self._stats: dict[str, Any] | None = None

    # ------------------------------------------------------------------ #
    def stats(self) -> dict[str, Any]:
        if self._stats is None:
            try:
                self._stats = self.client.stats()
            except GraphError:
                self._stats = {}
        return self._stats

    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        question: str,
        plan: QueryPlan,
        trace: Trace | None = None,
    ) -> GraphResult:
        links = [
            self.linker.link(
                e.text,
                e.etype,
                [] if self.settings.ablate_aliases else e.aliases,
            )
            for e in plan.entities
        ]
        entity_hint = self._render_entities(links)
        result = GraphResult(links=[link.to_dict() for link in links])

        weak = getattr(self.settings, "ablate_weak_prompt", False)
        schema = build_schema_text(self.stats(), minimal=weak)
        examples = (
            []
            if weak
            else self.few_shots.select(question, k=self.settings.few_shot_top_k)
        )
        system_prompt = CYPHER_SYSTEM.format(
            schema=schema, few_shots=FewShotLibrary.render(examples)
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"## 已解析实体\n{entity_hint}\n\n## 用户问题\n{question}",
            },
        ]

        try:
            cypher = self._call_llm(messages, trace, "cypher_generate")
        except Exception as exc:  # noqa: BLE001 - 生成阶段失败直接返回空结果
            logger.warning("Cypher 生成失败：%s", exc)
            result.error = f"生成失败：{exc}"
            return result

        error_hint = ""
        for attempt_idx in range(self.settings.cypher_max_repair + 1):
            if attempt_idx > 0:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": CYPHER_REPAIR_USER.format(
                            question=question,
                            cypher=cypher,
                            error=error_hint,
                            entities=entity_hint,
                        ),
                    },
                ]
                try:
                    cypher = self._call_llm(messages, trace, "cypher_repair")
                except Exception as exc:  # noqa: BLE001
                    result.error = f"修复失败：{exc}"
                    break

            attempt = Attempt(cypher=cypher, ok=False)
            result.attempts.append(attempt)

            ok, reason = self.guard.validate(cypher)
            if not ok:
                attempt.error = f"守卫拦截：{reason}"
                error_hint = (
                    f"生成的语句未通过安全校验：{reason}。"
                    "请只使用 MATCH/WHERE/WITH/RETURN 等只读子句，不要使用任何写操作或过程调用。"
                )
                logger.info("守卫拦截：%s", reason)
                continue

            prepared = self.guard.prepare(cypher)
            try:
                rows = self.client.read(prepared)
            except CypherRuntimeError as exc:
                attempt.error = str(exc)
                error_hint = str(exc)
                logger.info("Cypher 执行报错，准备修复：%s", str(exc)[:200])
                continue
            except GraphError as exc:
                attempt.error = str(exc)
                error_hint = str(exc)
                break

            attempt.ok = True
            attempt.rows = len(rows)
            if rows:
                result.cypher = prepared
                result.rows = rows
                result.error = ""
                break

            # 执行成功但没数据：多半跨语言实体名没对上
            attempt.error = "查询成功但返回 0 行"
            error_hint = (
                "查询语法正确，但返回 0 行。常见原因是实体名不匹配："
                "中药名是中文、成分/靶点/疾病名是英文。"
                "请放宽条件，改用 toLower(name) CONTAINS '关键词' 匹配，"
                "或改用「已解析实体」里给出的候选名。"
            )
            logger.info("Cypher 返回 0 行，准备放宽条件重试")

        if not result.rows and result.attempts:
            result.cypher = result.attempts[-1].cypher
        return result

    # ------------------------------------------------------------------ #
    def _call_llm(
        self,
        messages: list[dict[str, str]],
        trace: Trace | None,
        purpose: str,
    ) -> str:
        if trace is not None:
            with trace.span(purpose):
                result = self.llm.chat(messages, temperature=0.0, max_tokens=900)
                trace.record_llm(
                    purpose, result.model, result.prompt_tokens,
                    result.completion_tokens, result.latency_ms,
                )
        else:
            result = self.llm.chat(messages, temperature=0.0, max_tokens=900)

        return self._clean_cypher(result.text)

    @staticmethod
    def _clean_cypher(text: str) -> str:
        cypher = strip_code_fence(text)
        cypher = re.sub(r"^\s*Cypher\s*[:：]\s*", "", cypher, flags=re.IGNORECASE)
        return cypher.strip().strip("`").strip()

    @staticmethod
    def _render_entities(links: list[LinkResult]) -> str:
        if not links:
            return "（问题中未识别到图谱实体）"
        lines = []
        for link in links:
            if link.matched:
                names = "、".join(link.names(5))
                method = link.best.method if link.best else ""
                tag = {"exact": "精确匹配", "alias": "别名匹配",
                       "contains": "模糊包含", "fuzzy": "近似匹配"}.get(method, method)
                lines.append(f"- {link.etype}（原始词：{link.raw}）→ {tag}到：{names}")
            else:
                lines.append(
                    f"- {link.etype}（原始词：{link.raw}）→ 未在图谱中直接找到，"
                    "请改用 CONTAINS 模糊匹配，或在回答中说明未找到"
                )
        return "\n".join(lines)
