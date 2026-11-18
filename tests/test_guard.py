# -*- coding: utf-8 -*-
"""Cypher 只读守卫的单元测试。

这些用例不需要连数据库，跑得很快，适合放进 CI：
    pytest tests/ -q
"""

from __future__ import annotations

import pytest

from tcmqa.kg.guard import CypherGuard, strip_code_fence, strip_literals


@pytest.fixture()
def guard() -> CypherGuard:
    return CypherGuard(max_rows=50)


# ---------------------------------------------------------------------- #
class TestValidation:
    def test_allows_plain_read(self, guard):
        ok, reason = guard.validate("MATCH (h:Herb) RETURN h.name AS name")
        assert ok, reason

    def test_allows_optional_match(self, guard):
        ok, _ = guard.validate("OPTIONAL MATCH (n) RETURN n")
        assert ok

    @pytest.mark.parametrize(
        "cypher",
        [
            "CREATE (n:Herb {name:'x'})",
            "MATCH (n) DETACH DELETE n",
            "MATCH (n) SET n.name = 'x' RETURN n",
            "MERGE (n:Herb) RETURN n",
            "MATCH (n) REMOVE n.name RETURN n",
            "CALL db.labels()",
            "MATCH (n) RETURN n UNION MATCH (m) FOREACH (x IN [1] | SET m.p = x) RETURN m",
            "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
        ],
    )
    def test_blocks_writes(self, guard, cypher):
        ok, reason = guard.validate(cypher)
        assert not ok, f"应拦截但通过了：{cypher}"
        assert reason

    def test_blocks_multi_statement(self, guard):
        ok, reason = guard.validate("MATCH (n) RETURN n; MATCH (m) RETURN m")
        assert not ok
        assert "分号" in reason

    @pytest.mark.parametrize(
        "cypher",
        [
            "MATCH (n) // 注释\nRETURN n",
            "MATCH (n) /* 块注释 */ RETURN n",
        ],
    )
    def test_blocks_comments(self, guard, cypher):
        ok, reason = guard.validate(cypher)
        assert not ok
        assert "注释" in reason

    def test_requires_return(self, guard):
        ok, reason = guard.validate("MATCH (n:Herb)")
        assert not ok
        assert "RETURN" in reason

    def test_rejects_empty(self, guard):
        ok, _ = guard.validate("   ")
        assert not ok

    def test_keyword_inside_literal_is_not_blocked(self, guard):
        """数据里可能有叫 'SET' 或 'CREATE' 的值，不能误杀。"""
        ok, reason = guard.validate("MATCH (h:Herb) WHERE h.name = 'SET' RETURN h")
        assert ok, reason

    def test_uppercase_keyword_inside_literal(self, guard):
        ok, _ = guard.validate('MATCH (h:Herb) WHERE h.name = "DROP TABLE" RETURN h')
        assert ok


# ---------------------------------------------------------------------- #
class TestLimit:
    def test_appends_limit_when_missing(self, guard):
        prepared = guard.prepare("MATCH (h:Herb) RETURN h.name AS name")
        assert prepared.endswith("LIMIT 50")

    def test_shrinks_oversized_limit(self, guard):
        prepared = guard.prepare("MATCH (h:Herb) RETURN h.name AS name LIMIT 9999")
        assert "LIMIT 50" in prepared
        assert "9999" not in prepared

    def test_keeps_smaller_limit(self, guard):
        prepared = guard.prepare("MATCH (h:Herb) RETURN h.name AS name LIMIT 5")
        assert "LIMIT 5" in prepared

    def test_strips_trailing_semicolon(self, guard):
        prepared = guard.prepare("MATCH (h:Herb) RETURN h.name LIMIT 5;")
        assert not prepared.endswith(";")


# ---------------------------------------------------------------------- #
class TestHelpers:
    def test_strip_code_fence(self):
        raw = "```cypher\nMATCH (n) RETURN n\n```"
        assert strip_code_fence(raw) == "MATCH (n) RETURN n"

    def test_strip_literals(self):
        assert strip_literals("WHERE h.name = 'SET'") == "WHERE h.name = ''"

    def test_check_and_prepare_raises(self, guard):
        with pytest.raises(ValueError):
            guard.check_and_prepare("DELETE n")
