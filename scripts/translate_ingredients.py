# -*- coding: utf-8 -*-
"""给化学成分补中文名（图谱里只有英文名）。

为什么单独做一步：图谱的 Ingredient.name 全是英文（kaempferol、beta-sitosterol），
而用户要的是「山柰酚」「β-谷甾醇」。LLM 能翻，但必须约束好，否则会给一堆看似
专业实则错误的名字——化学名翻错的代价比翻不出更高。

所以规则是：不确定就标「未知」，缩写标「缩写」，CAS 号标「CAS号」，绝不编造。
翻译结果落盘成 data/ingredient_zh.json，可复用、可人工校对、可增量更新。

用法：
    python scripts/translate_ingredients.py --herb 人参
    python scripts/translate_ingredients.py --herb 黄芪 --top 60
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.llm.client import LLMClient  # noqa: E402
from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.llm.prompts import PROMPT_VERSION  # noqa: E402
from tcmqa.settings import DATA_DIR  # noqa: E402

ZH_PATH = DATA_DIR / "ingredient_zh.json"
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

SYSTEM = """你是药物化学命名专家。把给定的英文化学名翻译成**中文通用名**。

规则（很重要，宁可说不知道也不要编）：
1. 优先用中文药典/中文文献里的通用译名，例如 kaempferol→山柰酚、beta-sitosterol→β-谷甾醇。
2. 纯缩写或代号（如 GUP、DBP、MLI、TDA）无法确定全称时，值写 "缩写"。
3. CAS 登记号（如 3691-11-0）值写 "CAS号"。
4. 结构式系统命名（IUPAC，通常很长、含 (1R,4S) 这类手性标记），
   尽力给中文系统名；做不到就写 "复杂IUPAC名"。
5. 拿不准就写 "未知"。**不要猜测，不要编造**。

只输出一个 JSON 对象：{"英文名": "中文名"}，键必须与输入逐字一致。不要任何解释。"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--herb", default="人参")
    parser.add_argument("--top", type=int, default=0, help="只翻译靶点数前 N 个，0 表示全部")
    parser.add_argument("--batch", type=int, default=40)
    parser.add_argument("--out", default="", help="Markdown 输出路径")
    args = parser.parse_args()

    setup_logging("WARNING")

    with GraphClient() as client:
        rows = client.read(
            """
            MATCH (h:Herb {name:$herb})-[:CONTAINS]->(i:Ingredient)
            OPTIONAL MATCH (i)-[:TARGETS]->(t:Target)
            RETURN i.name AS name, i.id AS id, i.molecular_weight AS mw,
                   count(DISTINCT t) AS targets
            ORDER BY targets DESC, i.name
            """,
            {"herb": args.herb},
            limit=1000,
        )
    if not rows:
        print(f"未找到中药「{args.herb}」的成分")
        sys.exit(1)

    if args.top:
        rows = rows[: args.top]
    print(f"{args.herb}: {len(rows)} 个成分")

    existing: dict[str, str] = {}
    if ZH_PATH.exists():
        try:
            existing = json.loads(ZH_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}

    todo = [r["name"] for r in rows if r["name"] and r["name"] not in existing]
    print(f"已有译名 {len(rows) - len(todo)}，待翻译 {len(todo)}")

    llm = LLMClient()
    batches = [todo[i : i + args.batch] for i in range(0, len(todo), args.batch)]
    try:
        for idx, batch in enumerate(batches, start=1):
            payload = json.dumps(batch, ensure_ascii=False)
            try:
                data, result = llm.chat_json(
                    [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": payload},
                    ],
                    temperature=0.0,
                    max_tokens=3000,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  [{idx}/{len(batches)}] 失败：{exc}")
                continue

            added = 0
            for en, zh in data.items():
                if en in batch and isinstance(zh, str) and zh.strip():
                    existing[en] = zh.strip()
                    added += 1
            print(f"  [{idx}/{len(batches)}] 新增 {added} 条 ({result.latency_ms:.0f}ms)")
            ZH_PATH.write_text(
                json.dumps(existing, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8",
            )
            time.sleep(0.2)
    finally:
        llm.close()

    # ---- 输出 Markdown 表 ----
    out = Path(args.out) if args.out else DOCS_DIR / f"{args.herb}_成分表.md"
    lines = [
        f"# {args.herb} 的成分与中文名",
        "",
        f"- 来源：Neo4j 图谱 `(:Herb {{name:'{args.herb}'}})-[:CONTAINS]->(:Ingredient)`",
        f"- 成分数：{len(rows)}（下表按「作用靶点数」降序，靶点为 0 的排在后面）",
        "- 中文名：由 LLM 按「宁可未知不可编造」的规则生成，"
        "标记为「缩写 / CAS号 / 复杂IUPAC名 / 未知」的表示无法可靠翻译",
        f"- Prompt 版本：{PROMPT_VERSION}",
        "",
        "| # | 英文名 | 中文名 | 分子量 | 靶点数 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(rows, start=1):
        zh = existing.get(r["name"], "未翻译")
        mw = f"{float(r['mw']):.1f}" if r.get("mw") else "—"
        name = str(r["name"]).replace("|", "\\|")
        lines.append(f"| {i} | {name} | {zh} | {mw} | {r['targets']} |")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    translated = sum(1 for r in rows if existing.get(r["name"]) not in
                     (None, "未知", "缩写", "CAS号", "复杂IUPAC名"))
    print(f"\n可读中文名 {translated}/{len(rows)}")
    print(f"映射表 → {ZH_PATH}")
    print(f"成分表 → {out}")


if __name__ == "__main__":
    main()
