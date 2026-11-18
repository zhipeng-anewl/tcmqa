# -*- coding: utf-8 -*-
"""中文病名 → 图谱英文病名。

图谱里的疾病用英文 ICD 术语记录（`Diabetes mellitus`、`Asthma`），
用户却习惯说「糖尿病」「哮喘」。没有这层映射，搜索框直接查不到东西。

数据来自 `data/disease_zh.json`（由 scripts/translate_diseases.py 用 LLM 批量生成）。
这里只做**确定性的**字符串匹配，不调用模型：
- 完全一致 → 1.0
- 查询里包含某个中文病名（「2型糖尿病」含「糖尿病」）→ 0.9
- 某个中文病名包含查询（「糖尿病」被「糖尿病肾病」包含）→ 0.8

匹配不到就返回空，由上层决定要不要退回别的策略。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from tcmqa.settings import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_PATH = DATA_DIR / "disease_zh.json"


@dataclass(frozen=True)
class AliasHit:
    zh: str
    en: str
    score: float


class DiseaseAlias:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH
        self._en_to_zh: dict[str, str] = {}
        self._zh_items: list[tuple[str, str]] = []
        self._loaded = False

    # ------------------------------------------------------------------ #
    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self._en_to_zh = {}
        self._zh_items = []
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("病名映射解析失败：%s", self.path)
                raw = {}
            for en, zh in raw.items():
                if not en or not zh:
                    continue
                self._en_to_zh[str(en)] = str(zh)
                self._zh_items.append((str(zh), str(en)))
            logger.info("中文病名映射已加载：%d 条", len(self._zh_items))
        else:
            logger.info("未找到 %s，中文病名搜索不可用", self.path)
        self._loaded = True

    # ------------------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        self.load()
        return bool(self._zh_items)

    def zh_of(self, en_name: str) -> str:
        """英文病名 → 中文（用于展示）。"""
        self.load()
        return self._en_to_zh.get(en_name, "")

    def lookup(self, text: str, limit: int = 8) -> list[AliasHit]:
        """中文病名 → 候选英文病名。纯 ASCII 查询直接跳过。"""
        self.load()
        query = (text or "").strip()
        if not query or not self._zh_items:
            return []
        if query.isascii():
            return []

        hits: list[AliasHit] = []
        for zh, en in self._zh_items:
            if zh == query:
                score = 1.0
            elif zh and zh in query:
                # 查询更具体：「2型糖尿病」→ 命中「糖尿病」
                score = 0.9
            elif query in zh:
                # 查询更泛：「糖尿病」→ 命中「糖尿病肾病」
                score = 0.8
            else:
                continue
            hits.append(AliasHit(zh=zh, en=en, score=score))

        # 分数高的在前；同分时短名优先（更贴近用户意图）
        hits.sort(key=lambda h: (-h.score, len(h.zh), h.en))
        return hits[:limit]


# 进程内单例，避免每次请求都读文件
_default: DiseaseAlias | None = None


def get_disease_alias() -> DiseaseAlias:
    global _default
    if _default is None:
        _default = DiseaseAlias()
    return _default
