# -*- coding: utf-8 -*-
"""Neo4j 访问封装。

设计要点：
- 连接池由 Driver 统一管理，进程内单例，避免每个请求都握手；
- 会话固定 AccessMode.READ + 数据库名 + 查询超时，从驱动层再兜一次只读；
- 返回结果统一转成纯 Python 结构，路由层不用感知 neo4j 的 Node/Relationship 类型。
"""

from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase, RoutingControl
from neo4j.exceptions import ClientError, Neo4jError, ServiceUnavailable

from tcmqa.settings import Settings, get_settings


class GraphError(RuntimeError):
    """图谱查询失败（与 Cypher 语法错误区分开，后者要给 LLM 修复用）。"""


class CypherRuntimeError(GraphError):
    """Cypher 能在语义上执行失败（语法/类型/未知标签），可由 LLM 修复。"""

    def __init__(self, message: str, cypher: str) -> None:
        super().__init__(message)
        self.cypher = cypher


def _serialize(value: Any) -> Any:
    """Node / Relationship / 基础类型 → JSON 可序列化结构。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(v) for v in value]
    if hasattr(value, "items"):  # Node / Relationship
        return {k: _serialize(v) for k, v in dict(value.items()).items()}
    return str(value)


class GraphClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        try:
            self.driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
                max_connection_lifetime=1800,
                connection_timeout=10,
            )
            self.driver.verify_connectivity()
        except Exception as exc:  # noqa: BLE001
            raise GraphError(f"无法连接 Neo4j（{self.settings.neo4j_uri}）：{exc}") from exc

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self.driver.close()

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def read(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """执行只读查询并截断到 limit 行。

        抛 CypherRuntimeError 表示「语句本身可修」，上层可以交给 LLM 重写；
        抛 GraphError 表示连接/权限等不可修问题。
        """
        max_rows = limit or self.settings.neo4j_max_rows
        try:
            records, _, _ = self.driver.execute_query(
                cypher,
                parameters_=params or {},
                database_=self.settings.neo4j_database,
                routing_=RoutingControl.READ,
                timeout=self.settings.neo4j_query_timeout,
            )
        except (ClientError, Neo4jError) as exc:
            code = getattr(exc, "code", "") or ""
            if "Syntax" in code or "Semantic" in code or "TypeError" in code:
                raise CypherRuntimeError(f"{code}: {exc.message}", cypher) from exc
            raise GraphError(f"图谱查询失败（{code}）：{exc}") from exc
        except ServiceUnavailable as exc:
            raise GraphError(f"Neo4j 不可用：{exc}") from exc
        return [_serialize(r.data()) for r in records[:max_rows]]

    def read_one(self, cypher: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        rows = self.read(cypher, params, limit=1)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ #
    def scalar(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        row = self.read_one(cypher, params)
        if not row:
            return None
        return next(iter(row.values()))

    def stats(self) -> dict[str, Any]:
        """节点数、关系数、各类标签/关系分布，用于健康检查与 Schema 说明。"""
        total_nodes = self.scalar("MATCH (n) RETURN count(n) AS c") or 0
        total_rels = self.scalar("MATCH ()-[r]->() RETURN count(r) AS c") or 0
        labels = self.read(
            "MATCH (n) UNWIND labels(n) AS l RETURN l AS label, count(*) AS cnt ORDER BY cnt DESC"
        )
        rels = self.read(
            "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt ORDER BY cnt DESC"
        )
        return {
            "nodes": total_nodes,
            "relationships": total_rels,
            "labels": {r["label"]: r["cnt"] for r in labels},
            "relationship_types": {r["rel"]: r["cnt"] for r in rels},
        }
