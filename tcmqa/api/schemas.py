# -*- coding: utf-8 -*-
"""接口的请求/响应模型。

用 Pydantic 定义而不是裸 dict，换来的是：自动文档（/docs）、入参校验、
错误的统一格式，以及前端可以直接据此生成类型。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    session_id: str | None = Field(None, description="会话 ID，不传则新建")
    use_cache: bool = Field(True, description="是否允许命中缓存")


class EvidenceModel(BaseModel):
    id: str
    kind: str
    title: str
    text: str
    payload: dict[str, Any] = Field(default_factory=dict)


class PlanModel(BaseModel):
    intent: str = ""
    rewritten_query: str = ""
    entities: list[dict[str, Any]] = Field(default_factory=list)
    needs_graph: bool = False
    needs_vector: bool = False
    effects: list[str] = Field(default_factory=list)
    source: str = ""


class AttemptModel(BaseModel):
    cypher: str = ""
    ok: bool = False
    rows: int = 0
    error: str = ""


class ChatResponse(BaseModel):
    answer: str
    trace_id: str
    session_id: str
    intent: str = ""
    plan: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceModel] = Field(default_factory=list)
    cypher: str = ""
    attempts: list[AttemptModel] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)
    vector_hits: list[dict[str, Any]] = Field(default_factory=list)
    citations: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    blocked: bool = False
    latency_ms: float = 0.0


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: Literal[-1, 1]
    comment: str = Field("", max_length=500)


class NeighborRequest(BaseModel):
    name: str
    label: Literal["Herb", "Ingredient", "Target", "Disease"] = "Herb"
    limit: int = Field(30, ge=1, le=100)


class CypherRequest(BaseModel):
    cypher: str = Field(..., max_length=3000)


class SessionSummary(BaseModel):
    id: str
    title: str | None = None
    updated_at: float
