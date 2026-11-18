# -*- coding: utf-8 -*-
"""金标集加载。

每条用例描述「问什么、期望什么意图、怎么判对错」：
- mode=set    ：用 gold_cypher 现算标准结果集，与系统返回做集合比对
- mode=number ：用 gold_cypher 现算标准数值，与系统给出的数值比对（带容差）
- mode=hit    ：语义检索题，检查期望文档是否出现在召回结果里
- mode=none   ：只判意图/关键词/是否被拦截

标准答案**在评测时现算**而不是写死，这样图谱更新后金标集不会过期。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tcmqa.settings import DATA_DIR

DEFAULT_PATH = DATA_DIR / "golden_set.jsonl"


@dataclass
class GoldenCase:
    id: str
    question: str
    intent: str
    mode: str = "none"
    gold_cypher: str = ""
    gold_label: str = ""
    threshold: float = 0.8
    tolerance: float = 0.05
    expect_docs: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    expect_blocked: bool = False
    history: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    judge: bool = False
    difficulty: str = "normal"  # normal | hard

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "GoldenCase":
        return cls(
            id=str(raw["id"]),
            question=str(raw["question"]),
            intent=str(raw.get("intent") or "relation"),
            mode=str(raw.get("mode") or "none"),
            gold_cypher=str(raw.get("gold_cypher") or ""),
            gold_label=str(raw.get("gold_label") or ""),
            threshold=float(raw.get("threshold") or 0.8),
            tolerance=float(raw.get("tolerance") or 0.05),
            expect_docs=list(raw.get("expect_docs") or []),
            must_include=list(raw.get("must_include") or []),
            expect_blocked=bool(raw.get("expect_blocked") or False),
            history=list(raw.get("history") or []),
            tags=list(raw.get("tags") or []),
            judge=bool(raw.get("judge") or False),
            difficulty=str(raw.get("difficulty") or "normal"),
        )


def load_cases(path: Path | str | None = None) -> list[GoldenCase]:
    file = Path(path) if path else DEFAULT_PATH
    if not file.exists():
        raise FileNotFoundError(f"金标集不存在：{file}")

    cases: list[GoldenCase] = []
    with file.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                cases.append(GoldenCase.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{file}:{lineno} 解析失败：{exc}") from exc
    return cases
