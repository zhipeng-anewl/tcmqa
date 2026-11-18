# -*- coding: utf-8 -*-
"""问答编排：整个系统的骨架。

一次请求的顺序：
    输入防护 → 缓存 → 规划(改写+路由+抽实体) → 混合检索(图谱/向量) → 证据装配
    → 答案合成(强制引用) → 引用校验 → 落库

每个阶段都在 Trace 里开一个 span，所以任何一次问答都能回答
「慢在哪一步、花了多少 token、哪条证据被引用了」。
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator

from tcmqa.guard import check_input
from tcmqa.kg.client import GraphClient
from tcmqa.kg.linker import EntityLinker
from tcmqa.llm.client import LLMClient
from tcmqa.llm.prompts import (
    ANSWER_SYSTEM,
    ANSWER_USER,
    CHITCHAT_SYSTEM,
    OUT_OF_SCOPE_SYSTEM,
)
from tcmqa.logging import get_logger
from tcmqa.rag.cache import SemanticCache
from tcmqa.rag.graph_retriever import GraphRetriever
from tcmqa.rag.planner import Planner, QueryPlan
from tcmqa.rag.retriever import SemanticRetriever
from tcmqa.settings import Settings, get_settings
from tcmqa.store.sqlite import Database
from tcmqa.tracing import Trace

logger = get_logger(__name__)

CITATION_RE = re.compile(r"\[(E\d+)\]")


@dataclass
class Evidence:
    id: str
    kind: str  # graph / herb / effect / disease
    title: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "text": self.text,
            "payload": self.payload,
        }


@dataclass
class AnswerResult:
    answer: str
    trace_id: str
    session_id: str
    intent: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    cypher: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    vector_hits: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    citations: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    blocked: bool = False
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "intent": self.intent,
            "plan": self.plan,
            "evidence": [e.to_dict() for e in self.evidence],
            "cypher": self.cypher,
            "attempts": self.attempts,
            "links": self.links,
            "vector_hits": self.vector_hits,
            "rows": self.rows,
            "citations": self.citations,
            "trace": self.trace,
            "cached": self.cached,
            "blocked": self.blocked,
            "latency_ms": self.latency_ms,
        }


class QAPipeline:
    def __init__(
        self,
        llm: LLMClient,
        graph: GraphClient,
        linker: EntityLinker,
        semantic: SemanticRetriever,
        db: Database,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.graph = graph
        self.linker = linker
        self.semantic = semantic
        self.db = db

        self.planner = Planner(llm, linker, self.settings)
        # 消融实验：把重试次数压到 0，等价于「没有自修复闭环」
        retriever_settings = self.settings
        if self.settings.ablate_repair:
            retriever_settings = self.settings.model_copy(update={"cypher_max_repair": 0})
        self.graph_retriever = GraphRetriever(graph, llm, linker, retriever_settings)
        self.cache = SemanticCache(db, semantic.embedder, self.settings)

    # ================================================================== #
    # 对外：非流式
    # ================================================================== #
    def answer(
        self,
        question: str,
        session_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        use_cache: bool = True,
    ) -> AnswerResult:
        started = time.perf_counter()
        trace = Trace(question)
        sid = self.db.ensure_session(session_id, title=question[:40])
        trace.session_id = sid

        guard = check_input(question, self.settings.max_question_chars)
        if not guard.allowed:
            result = self._blocked_answer(guard.reason, guard.hint, trace, sid)
            self._persist(result, trace)
            return result

        if use_cache:
            hit = self.cache.get(question)
            if hit:
                trace.set(cache="hit", cache_kind=hit.kind, cache_score=round(hit.score, 4))
                payload = hit.payload or {}
                result = AnswerResult(
                    answer=hit.answer,
                    trace_id=trace.trace_id,
                    session_id=sid,
                    intent=payload.get("intent", ""),
                    plan=payload.get("plan", {}),
                    evidence=[Evidence(**e) for e in payload.get("evidence", [])],
                    cypher=payload.get("cypher", ""),
                    links=payload.get("links", []),
                    citations=payload.get("citations", {}),
                    cached=True,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                result.trace = trace.to_dict(
                    self.settings.price_input_cache_miss, self.settings.price_output
                )
                self._persist(result, trace)
                return result

        plan = self.planner.plan(question, history, trace)
        trace.set(intent=plan.intent, plan_source=plan.source)

        if plan.intent in ("chitchat", "out_of_scope"):
            text = self._direct_answer(question, plan.intent, trace)
            result = AnswerResult(
                answer=text,
                trace_id=trace.trace_id,
                session_id=sid,
                intent=plan.intent,
                plan=plan.to_dict(),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        else:
            evidence, meta = self._retrieve(question, plan, trace)
            answer = self._synthesize(question, evidence, trace)
            citations = self._verify_citations(answer, evidence)
            result = AnswerResult(
                answer=answer,
                trace_id=trace.trace_id,
                session_id=sid,
                intent=plan.intent,
                plan=plan.to_dict(),
                evidence=evidence,
                cypher=meta.get("cypher", ""),
                attempts=meta.get("attempts", []),
                links=meta.get("links", []),
                vector_hits=meta.get("vector_hits", []),
                rows=meta.get("rows", []),
                citations=citations,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            if use_cache and answer and not _is_empty_answer(answer):
                self.cache.put(question, answer, self._cache_payload(result))

        result.trace = trace.to_dict(
            self.settings.price_input_cache_miss, self.settings.price_output
        )
        self._persist(result, trace)
        return result

    # ================================================================== #
    # 对外：流式（SSE 用）
    # ================================================================== #
    def stream(
        self,
        question: str,
        session_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        use_cache: bool = True,
    ) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        trace = Trace(question)
        sid = self.db.ensure_session(session_id, title=question[:40])
        trace.session_id = sid
        yield {"type": "meta", "data": {"trace_id": trace.trace_id, "session_id": sid}}

        guard = check_input(question, self.settings.max_question_chars)
        if not guard.allowed:
            text = guard.hint or f"无法处理该问题：{guard.reason}"
            yield {"type": "token", "data": text}
            result = self._blocked_answer(guard.reason, guard.hint, trace, sid)
            self._persist(result, trace)
            yield {"type": "done", "data": result.to_dict()}
            return

        if use_cache:
            hit = self.cache.get(question)
            if hit:
                trace.set(cache="hit", cache_kind=hit.kind)
                yield {"type": "cached", "data": {"kind": hit.kind, "score": round(hit.score, 4)}}
                yield {"type": "token", "data": hit.answer}
                payload = hit.payload or {}
                cfg = self.settings
                result = AnswerResult(
                    answer=hit.answer,
                    trace_id=trace.trace_id,
                    session_id=sid,
                    intent=payload.get("intent", ""),
                    plan=payload.get("plan", {}),
                    evidence=[Evidence(**e) for e in payload.get("evidence", [])],
                    cypher=payload.get("cypher", ""),
                    links=payload.get("links", []),
                    citations=payload.get("citations", {}),
                    cached=True,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                result.trace = trace.to_dict(cfg.price_input_cache_miss, cfg.price_output)
                self._persist(result, trace)
                yield {"type": "done", "data": result.to_dict()}
                return

        plan = self.planner.plan(question, history, trace)
        trace.set(intent=plan.intent, plan_source=plan.source)
        yield {"type": "plan", "data": plan.to_dict()}

        if plan.intent in ("chitchat", "out_of_scope"):
            answer = ""
            sink: dict[str, Any] = {}
            messages = self._direct_messages(question, plan.intent)
            with trace.span("answer_direct"):
                for piece in self.llm.stream(messages, temperature=0.3, max_tokens=300, usage_sink=sink):
                    answer += piece
                    yield {"type": "token", "data": piece}
            self._record_stream_usage(trace, "answer_direct", sink, answer)
            result = AnswerResult(
                answer=answer,
                trace_id=trace.trace_id,
                session_id=sid,
                intent=plan.intent,
                plan=plan.to_dict(),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        else:
            evidence, meta = self._retrieve(question, plan, trace)
            yield {
                "type": "retrieval",
                "data": {
                    "cypher": meta.get("cypher", ""),
                    "attempts": meta.get("attempts", []),
                    "links": meta.get("links", []),
                    "vector_hits": meta.get("vector_hits", []),
                },
            }
            yield {"type": "evidence", "data": [e.to_dict() for e in evidence]}

            if not evidence:
                answer = (
                    "图谱里没有查询到能回答这个问题的数据。"
                    "可能是问题里的实体名称与图谱不一致，或者该内容暂未收录。"
                )
                yield {"type": "token", "data": answer}
                result = AnswerResult(
                    answer=answer,
                    trace_id=trace.trace_id,
                    session_id=sid,
                    intent=plan.intent,
                    plan=plan.to_dict(),
                    evidence=[],
                    cypher=meta.get("cypher", ""),
                    attempts=meta.get("attempts", []),
                    links=meta.get("links", []),
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            else:
                messages = self._answer_messages(question, evidence)
                answer = ""
                sink = {}
                with trace.span("synthesize"):
                    for piece in self.llm.stream(messages, temperature=0.2, max_tokens=1200, usage_sink=sink):
                        answer += piece
                        yield {"type": "token", "data": piece}
                self._record_stream_usage(trace, "synthesize", sink, answer)
                citations = self._verify_citations(answer, evidence)
                yield {"type": "citations", "data": citations}

                result = AnswerResult(
                    answer=answer,
                    trace_id=trace.trace_id,
                    session_id=sid,
                    intent=plan.intent,
                    plan=plan.to_dict(),
                    evidence=evidence,
                    cypher=meta.get("cypher", ""),
                    attempts=meta.get("attempts", []),
                    links=meta.get("links", []),
                    vector_hits=meta.get("vector_hits", []),
                    rows=meta.get("rows", []),
                    citations=citations,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                if use_cache and answer and not _is_empty_answer(answer):
                    self.cache.put(question, answer, self._cache_payload(result))

        result.trace = trace.to_dict(
            self.settings.price_input_cache_miss, self.settings.price_output
        )
        self._persist(result, trace)
        yield {"type": "done", "data": result.to_dict()}

    # ================================================================== #
    # 内部：检索
    # ================================================================== #
    def _retrieve(
        self, question: str, plan: QueryPlan, trace: Trace
    ) -> tuple[list[Evidence], dict[str, Any]]:
        meta: dict[str, Any] = {"cypher": "", "attempts": [], "links": [], "vector_hits": [], "rows": []}
        evidence: list[Evidence] = []

        if plan.needs_graph:
            graph_result = self.graph_retriever.retrieve(question, plan, trace)
            meta["cypher"] = graph_result.cypher
            meta["attempts"] = [a.to_dict() for a in graph_result.attempts]
            meta["links"] = graph_result.links
            meta["rows"] = graph_result.rows
            evidence.extend(self._evidence_from_graph(graph_result.rows))

        if plan.needs_vector:
            with trace.span("vector_retrieve"):
                fused = self.semantic.search(question)
            meta["vector_hits"] = [
                {"id": f.doc.id, "kind": f.doc.kind, "title": f.doc.title,
                 "score": f.score, "sources": f.sources}
                for f in fused
            ]
            offset = len(evidence)
            evidence.extend(self._evidence_from_docs(fused, offset))

        return evidence, meta

    def _evidence_from_graph(self, rows: list[dict[str, Any]]) -> list[Evidence]:
        items: list[Evidence] = []
        for idx, row in enumerate(rows[:10], start=1):
            parts = []
            for key, value in row.items():
                if isinstance(value, list):
                    value = "、".join(str(v) for v in value[:8])
                parts.append(f"{key}={value}")
            items.append(
                Evidence(
                    id=f"E{idx}",
                    kind="graph",
                    title="图谱查询结果",
                    text="，".join(parts),
                    payload=row,
                )
            )
        if len(rows) > 10:
            items.append(
                Evidence(
                    id=f"E{len(items) + 1}",
                    kind="graph",
                    title="结果统计",
                    text=f"图谱共返回 {len(rows)} 行，此处仅展示前 10 行。",
                    payload={"total_rows": len(rows)},
                )
            )
        return items

    def _evidence_from_docs(self, fused, offset: int) -> list[Evidence]:
        items: list[Evidence] = []
        for idx, item in enumerate(fused, start=offset + 1):
            items.append(
                Evidence(
                    id=f"E{idx}",
                    kind=item.doc.kind,
                    title=item.doc.title,
                    text=item.doc.text,
                    payload={"id": item.doc.id, "score": round(item.score, 4),
                             "sources": item.sources},
                )
            )
        return items

    # ================================================================== #
    # 内部：生成
    # ================================================================== #
    def _answer_messages(self, question: str, evidence: list[Evidence]) -> list[dict[str, str]]:
        evidence_text = "\n\n".join(
            f"[{e.id}]（{e.kind}）{e.title}：{e.text}" for e in evidence
        )
        return [
            {"role": "system", "content": ANSWER_SYSTEM},
            {
                "role": "user",
                "content": ANSWER_USER.format(question=question, evidence=evidence_text),
            },
        ]

    def _synthesize(self, question: str, evidence: list[Evidence], trace: Trace) -> str:
        if not evidence:
            return (
                "图谱里没有查询到能回答这个问题的数据。"
                "可能是问题里的实体名称与图谱不一致，或者该内容暂未收录。"
            )
        messages = self._answer_messages(question, evidence)
        with trace.span("synthesize"):
            result = self.llm.chat(messages, temperature=0.2, max_tokens=1200)
            trace.record_llm(
                "synthesize", result.model, result.prompt_tokens,
                result.completion_tokens, result.latency_ms,
            )
        return result.text.strip()

    def _direct_messages(self, question: str, intent: str) -> list[dict[str, str]]:
        system = CHITCHAT_SYSTEM if intent == "chitchat" else OUT_OF_SCOPE_SYSTEM
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ]

    def _direct_answer(self, question: str, intent: str, trace: Trace) -> str:
        with trace.span("answer_direct"):
            result = self.llm.chat(
                self._direct_messages(question, intent), temperature=0.3, max_tokens=300
            )
            trace.record_llm(
                "answer_direct", result.model, result.prompt_tokens,
                result.completion_tokens, result.latency_ms,
            )
        return result.text.strip()

    # ================================================================== #
    # 内部：校验与持久化
    # ================================================================== #
    @staticmethod
    def _verify_citations(answer: str, evidence: list[Evidence]) -> dict[str, Any]:
        cited = set(CITATION_RE.findall(answer))
        valid_ids = {e.id for e in evidence}
        invalid = sorted(cited - valid_ids)
        used = cited & valid_ids
        return {
            "cited": sorted(cited),
            "invalid": invalid,
            "used_count": len(used),
            "evidence_count": len(valid_ids),
            "citation_recall": round(len(used) / len(valid_ids), 3) if valid_ids else 0.0,
            "has_invalid": bool(invalid),
        }

    def _cache_payload(self, result: AnswerResult) -> dict[str, Any]:
        return {
            "intent": result.intent,
            "plan": result.plan,
            "evidence": [e.to_dict() for e in result.evidence],
            "cypher": result.cypher,
            "links": result.links,
            "citations": result.citations,
        }

    def _blocked_answer(self, reason: str, hint: str, trace: Trace, sid: str) -> AnswerResult:
        text = hint or f"无法处理该问题：{reason}"
        trace.set(blocked=True, block_reason=reason)
        return AnswerResult(
            answer=text,
            trace_id=trace.trace_id,
            session_id=sid,
            intent="blocked",
            blocked=True,
            latency_ms=trace.elapsed_ms,
        )

    def _record_stream_usage(
        self, trace: Trace, purpose: str, sink: dict[str, Any], text: str
    ) -> None:
        trace.record_llm(
            purpose,
            self.settings.llm_model,
            int(sink.get("prompt_tokens") or 0),
            int(sink.get("completion_tokens") or len(text) // 2),
            0.0,
        )

    def _persist(self, result: AnswerResult, trace: Trace) -> None:
        try:
            self.db.append_message(result.session_id, "user", trace.question)
            self.db.append_message(
                result.session_id,
                "assistant",
                result.answer,
                {
                    "trace_id": result.trace_id,
                    "intent": result.intent,
                    "cypher": result.cypher,
                    "cached": result.cached,
                    "blocked": result.blocked,
                },
            )
            self.db.save_trace(result.trace, result.answer, result.intent)
        except Exception as exc:  # noqa: BLE001 - 落库失败不影响回答
            logger.warning("持久化失败：%s", exc)


def _is_empty_answer(answer: str) -> bool:
    return any(k in answer for k in ("没有查询到", "暂时无法", "没有找到"))
