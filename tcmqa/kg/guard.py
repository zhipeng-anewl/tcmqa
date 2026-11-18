# -*- coding: utf-8 -*-
"""Cypher 只读守卫。

LLM 生成的 Cypher 是不可信输入，直接丢给数据库等于把写权限交出去。
这里做四层防护，任何一层失守都不至于造成破坏：

1. 词法层：剥离字符串字面量后再做关键词黑名单匹配，避免把数据里的词误判（也避免用字符串绕过）；
2. 结构层：必须以只读子句开头、必须含 RETURN、不允许分号多语句、不允许注释；
3. 规模层：强制补 LIMIT，并把过大的 LIMIT 压回上限；
4. 执行层（见 kg/client.py）：AccessMode.READ + 查询超时 + 结果行数截断。

第 4 层才是真正的兜底——前三层是「尽量不让危险语句到那一步」。
"""

from __future__ import annotations

import re

# 只读场景下完全不需要的子句
FORBIDDEN = (
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH",
    "REMOVE",
    "SET",
    "DROP",
    "FOREACH",
    "CALL",
    "YIELD",
    "LOAD",
    "USING",
    "GRANT",
    "REVOKE",
    "DENY",
    "ALTER",
    "RENAME",
    "START",
    "STOP",
)

ALLOWED_PREFIXES = ("MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN")

_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_LIMIT_RE = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


def strip_literals(cypher: str) -> str:
    """把引号里的内容换成空串占位，只留结构用于关键词扫描。"""
    return _LITERAL_RE.sub("''", cypher)


def strip_code_fence(text: str) -> str:
    """LLM 有时会套 ```cypher 代码块，先剥掉。"""
    text = text.strip()
    match = re.search(r"```(?:cypher|sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


class CypherGuard:
    def __init__(self, max_rows: int = 200) -> None:
        self.max_rows = max_rows

    # ------------------------------------------------------------------ #
    def validate(self, cypher: str) -> tuple[bool, str]:
        if not cypher or not cypher.strip():
            return False, "Cypher 为空"

        body = strip_code_fence(cypher)

        if ";" in body:
            return False, "不允许分号，只允许单条语句"
        if "//" in body or "/*" in body:
            return False, "不允许注释"

        structure = strip_literals(body).upper()
        for kw in FORBIDDEN:
            if re.search(rf"\b{kw}\b", structure):
                return False, f"包含禁止的子句：{kw}"

        if not structure.strip().startswith(ALLOWED_PREFIXES):
            return False, "查询必须以 MATCH / OPTIONAL MATCH / WITH / UNWIND / RETURN 开头"

        if "RETURN" not in structure:
            return False, "查询必须包含 RETURN"

        return True, ""

    # ------------------------------------------------------------------ #
    def prepare(self, cypher: str) -> str:
        """校验通过后调用：统一剥离代码块、压缩过大的 LIMIT、补默认 LIMIT。"""
        body = strip_code_fence(cypher).strip().rstrip(";").strip()

        match = _LIMIT_RE.search(body)
        if match:
            value = int(match.group(1))
            if value > self.max_rows:
                body = _LIMIT_RE.sub(f"LIMIT {self.max_rows}", body, count=1)
            return body

        return f"{body}\nLIMIT {self.max_rows}"

    # ------------------------------------------------------------------ #
    def check_and_prepare(self, cypher: str) -> str:
        ok, reason = self.validate(cypher)
        if not ok:
            raise ValueError(reason)
        return self.prepare(cypher)
