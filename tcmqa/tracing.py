# -*- coding: utf-8 -*-
"""轻量链路追踪。

不引 Langfuse/OpenTelemetry 这种重方案，自己实现一个 Span 模型就够用：
每个请求生成一条 Trace，内部按阶段开 Span，结束后落 SQLite。
这样能回答面试里最常问的那几个问题——
「这次请求慢在哪」「一次问答花多少 token / 多少钱」「失败率最高的阶段是哪个」。
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class Span:
    name: str
    started_at: float
    ended_at: float | None = None
    status: str = "ok"
    error: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return round((end - self.started_at) * 1000, 2)


@dataclass
class LLMCall:
    purpose: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    ok: bool = True


class Trace:
    """一次问答的完整轨迹。"""

    def __init__(self, question: str, session_id: str | None = None) -> None:
        self.trace_id = uuid.uuid4().hex
        self.session_id = session_id
        self.question = question
        self.started_at = time.perf_counter()
        self.spans: list[Span] = []
        self.llm_calls: list[LLMCall] = []
        self.events: list[dict[str, Any]] = []
        self.attrs: dict[str, Any] = {}

    # ---------- span ----------
    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[Span]:
        sp = Span(name=name, started_at=time.perf_counter(), attrs=dict(attrs))
        self.spans.append(sp)
        try:
            yield sp
        except Exception as exc:  # noqa: BLE001 - 记录后继续抛
            sp.status = "error"
            sp.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            sp.ended_at = time.perf_counter()

    def event(self, name: str, **attrs: Any) -> None:
        self.events.append({"name": name, "at_ms": self.elapsed_ms, **attrs})

    def set(self, **attrs: Any) -> None:
        self.attrs.update(attrs)

    # ---------- 计费 ----------
    def record_llm(
        self,
        purpose: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        ok: bool = True,
    ) -> None:
        self.llm_calls.append(
            LLMCall(purpose, model, prompt_tokens, completion_tokens, latency_ms, ok)
        )

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.llm_calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.llm_calls)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def cost_cny(self, price_in: float, price_out: float) -> float:
        """按「未命中缓存」的输入价估算，真实账单会略低。"""
        return round(
            self.prompt_tokens / 1_000_000 * price_in
            + self.completion_tokens / 1_000_000 * price_out,
            6,
        )

    def stage_ms(self) -> dict[str, float]:
        """同名 span 累加（例如两次 cypher_repair 合并成一项）。"""
        out: dict[str, float] = {}
        for sp in self.spans:
            out[sp.name] = round(out.get(sp.name, 0.0) + sp.duration_ms, 2)
        return out

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started_at) * 1000, 2)

    def to_dict(self, price_in: float = 2.0, price_out: float = 8.0) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "question": self.question,
            "elapsed_ms": self.elapsed_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_cny": self.cost_cny(price_in, price_out),
            "stage_ms": self.stage_ms(),
            "llm_calls": [c.__dict__ for c in self.llm_calls],
            "events": self.events,
            "attrs": self.attrs,
            "spans": [
                {
                    "name": s.name,
                    "duration_ms": s.duration_ms,
                    "status": s.status,
                    "error": s.error,
                    "attrs": s.attrs,
                }
                for s in self.spans
            ],
        }
