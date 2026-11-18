# -*- coding: utf-8 -*-
"""图谱相关接口：概览、节点详情、邻居扩展、手工 Cypher。

提供手工 Cypher 的入口不是为了炫技，而是为了能直接对比
「人手写一条查询」和「Text2Cypher 生成一条查询」的差异——答辩时很好用。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from tcmqa.api.deps import get_services
from tcmqa.api.schemas import CypherRequest, NeighborRequest
from tcmqa.kg.aliases import get_disease_alias
from tcmqa.kg.client import CypherRuntimeError, GraphError
from tcmqa.kg.guard import CypherGuard

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])

LABEL_MAP = {
    "Herb": "Herb",
    "Ingredient": "Ingredient",
    "Target": "Target",
    "Disease": "Disease",
}


def resolve_disease_name(name: str) -> str:
    """中文病名 → 图谱里的英文病名；解析不了就原样返回。

    只接受高分匹配（完全一致，或查询里包含某个中文病名），避免把
    「糖尿病」错配成「糖尿病肾病」之外的一堆近似项。
    """
    for hit in get_disease_alias().lookup(name):
        if hit.score >= 0.9:
            return hit.en
    return name


@router.get("/overview")
def overview(request: Request) -> dict[str, Any]:
    services = get_services(request.app)
    try:
        stats = services.graph.stats()
    except GraphError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    top_herbs = services.graph.read(
        "MATCH (h:Herb)-[:CONTAINS]->(i:Ingredient) "
        "RETURN h.name AS name, count(DISTINCT i) AS value ORDER BY value DESC LIMIT 10"
    )
    top_diseases = services.graph.read(
        "MATCH (h:Herb)-[:TREATS]->(d:Disease) "
        "RETURN d.name AS name, count(DISTINCT h) AS value ORDER BY value DESC LIMIT 10"
    )
    effects = services.graph.read(
        "MATCH (h:Herb) WHERE h.effect IS NOT NULL "
        "RETURN h.effect AS name, count(*) AS value ORDER BY value DESC LIMIT 15"
    )
    return {
        "stats": stats,
        "top_herbs": top_herbs,
        "top_diseases": top_diseases,
        "effects": effects,
    }


@router.get("/node")
def node_detail(
    request: Request,
    name: str,
    label: str = "Herb",
    limit: int = 40,
) -> dict[str, Any]:
    services = get_services(request.app)
    if label not in LABEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的标签：{label}")

    # 疾病用英文记录，用户可能直接传中文（「糖尿病」）
    resolved = resolve_disease_name(name)
    alias_zh = ""
    if resolved != name:
        alias_zh = name
        name = resolved

    guard = CypherGuard(max_rows=200)
    cypher = (
        f"MATCH (n:{LABEL_MAP[label]}) WHERE toLower(n.name) = toLower($name) "
        "OPTIONAL MATCH (n)-[r]-(m) "
        "RETURN n, collect(DISTINCT {rel: type(r), dir: CASE WHEN startNode(r)=n THEN 'out' ELSE 'in' END, "
        "label: labels(m)[0], name: m.name}) AS neighbors LIMIT 1"
    )
    rows = services.graph.read(guard.prepare(cypher), {"name": name})
    if not rows:
        raise HTTPException(status_code=404, detail=f"未找到节点：{name}")

    row = rows[0]
    node = row.get("n") or {}
    neighbors = [n for n in (row.get("neighbors") or []) if n and n.get("name")]
    deduped: dict[str, dict] = {}
    for n in neighbors:
        deduped[f"{n.get('rel')}|{n.get('label')}|{n.get('name')}"] = n

    return {
        "label": label,
        "name": name,
        "alias_zh": alias_zh or get_disease_alias().zh_of(name),
        "properties": node,
        "neighbors": list(deduped.values())[:limit],
        "neighbor_count": len(deduped),
    }


@router.post("/neighbors")
def neighbors(req: NeighborRequest, request: Request) -> dict[str, Any]:
    services = get_services(request.app)
    label = LABEL_MAP.get(req.label, "Herb")
    name = resolve_disease_name(req.name) if label == "Disease" else req.name
    cypher = (
        f"MATCH (n:{label}) WHERE toLower(n.name) = toLower($name) "
        "OPTIONAL MATCH (n)-[r]-(m) "
        "RETURN type(r) AS rel, labels(m)[0] AS label, m.name AS name, "
        "CASE WHEN startNode(r)=n THEN 'out' ELSE 'in' END AS dir "
        "LIMIT $limit"
    )
    try:
        rows = services.graph.read(cypher, {"name": req.name, "limit": req.limit})
    except GraphError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"name": req.name, "label": req.label, "neighbors": rows}


@router.post("/cypher")
def run_cypher(req: CypherRequest, request: Request) -> dict[str, Any]:
    """手工执行只读 Cypher，走同一套守卫。"""
    services = get_services(request.app)
    guard = CypherGuard(max_rows=services.settings.neo4j_max_rows)

    ok, reason = guard.validate(req.cypher)
    if not ok:
        raise HTTPException(status_code=400, detail=f"查询被守卫拦截：{reason}")

    prepared = guard.prepare(req.cypher)
    try:
        rows = services.graph.read(prepared)
    except CypherRuntimeError as exc:
        raise HTTPException(status_code=400, detail=f"查询执行失败：{exc}") from exc
    except GraphError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"cypher": prepared, "rows": rows, "row_count": len(rows)}


@router.get("/search")
def search_nodes(request: Request, q: str, label: str | None = None, limit: int = 10) -> dict:
    """按名称搜索节点，供前端做实体联想。

    疾病在图谱里是英文（Diabetes mellitus / Asthma），用户输入中文（糖尿病）时
    直接查 name 会一无所获。所以中文查询会先过一遍病名映射，
    把命中的英文病名一并查出来，并把中文名作为 alias 返回给前端展示。
    """
    services = get_services(request.app)
    if label and label not in LABEL_MAP:
        raise HTTPException(status_code=400, detail=f"不支持的标签：{label}")

    if label:
        cypher = (
            f"MATCH (n:{LABEL_MAP[label]}) WHERE toLower(n.name) CONTAINS toLower($q) "
            "RETURN n.name AS name, labels(n)[0] AS label, n.id AS id LIMIT $limit"
        )
    else:
        cypher = (
            "MATCH (n) WHERE (n:Herb OR n:Ingredient OR n:Target OR n:Disease) "
            "AND toLower(n.name) CONTAINS toLower($q) "
            "RETURN n.name AS name, labels(n)[0] AS label, n.id AS id LIMIT $limit"
        )
    rows = services.graph.read(cypher, {"q": q, "limit": limit})

    alias = get_disease_alias()
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 中文查询：先把映射到的英文病名放前面（这是用户真正想要的）
    if not q.isascii():
        hits = alias.lookup(q, limit=limit)
        if hits:
            names = [h.en for h in hits]
            found = services.graph.read(
                "MATCH (d:Disease) WHERE d.name IN $names "
                "RETURN d.name AS name, 'Disease' AS label, d.id AS id",
                {"names": names},
                limit=limit,
            )
            by_name = {r["name"]: r for r in found}
            for h in hits:
                r = by_name.get(h.en)
                if not r or r["id"] in seen:
                    continue
                seen.add(r["id"])
                merged.append({**r, "alias": h.zh, "matched_by": "alias"})

    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        zh = alias.zh_of(r["name"]) if r["label"] == "Disease" else ""
        merged.append({**r, "alias": zh, "matched_by": "name"})

    return {"query": q, "results": merged[:limit]}
