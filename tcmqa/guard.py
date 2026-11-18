# -*- coding: utf-8 -*-
"""输入侧防护。

要防的东西和纯文本 LLM 应用不完全一样：
- 提示注入：让模型忽略系统提示、套出 prompt、扮演别的角色；
- 越权：诱导生成写操作（虽然 Cypher 守卫会兜住，但不必浪费 token）；
- 医疗越界：要求诊断、开处方剂量——这是合规问题，比安全问题更实际。

只做「廉价且确定性」的判断，语义层面的拦截交给规划器的 out_of_scope 意图。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS = (
    r"忽略(以上|之前|上面|前面|所有)的?(所有)?(指令|提示|要求|规则)",
    r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions",
    r"(你现在是|从现在开始你是|扮演|假装你是)",
    r"(输出|显示|打印|重复).{0,6}(系统)?(提示词|prompt|指令)",
    r"repeat\s+your\s+(system\s+)?prompt",
    r"<\s*\|.*?\|\s*>",  # 特殊 token 注入
    r"(drop|delete|truncate)\s+(database|table)",
    r"(写入|删除|修改).{0,4}(数据库|图谱|节点)",
)

MEDICAL_RISK_PATTERNS = (
    r"(每天|每次|一日|一天).{0,6}(吃|服|用).{0,6}(克|g|片|粒|毫升|ml)",
    r"(开|配|抓).{0,8}(药方|方子|处方)",
    r"(给我|帮我|直接).{0,10}(开药|配药|开方|下药)",
    r"我(是不是|得了|患了).{0,10}(病|癌|炎|症)",
)

_COMPILED_INJECTION = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_COMPILED_MEDICAL = [re.compile(p) for p in MEDICAL_RISK_PATTERNS]


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    category: str = ""  # length | injection | medical | empty
    hint: str = ""


def check_input(question: str, max_chars: int = 500) -> GuardResult:
    text = (question or "").strip()

    if not text:
        return GuardResult(False, "问题为空", "empty")

    if len(text) > max_chars:
        return GuardResult(
            False,
            f"问题过长（{len(text)} 字），请控制在 {max_chars} 字以内",
            "length",
        )

    for pattern in _COMPILED_INJECTION:
        if pattern.search(text):
            return GuardResult(
                False,
                "检测到疑似提示注入的内容，已拦截",
                "injection",
                hint="我只能回答中医药知识图谱内的问题。",
            )

    for pattern in _COMPILED_MEDICAL:
        if pattern.search(text):
            return GuardResult(
                False,
                "涉及具体用药剂量或诊断，系统不能提供此类建议",
                "medical",
                hint="建议咨询执业中医师；我可以帮你查这味药的功效、成分和靶点。",
            )

    return GuardResult(True)
