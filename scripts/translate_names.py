# -*- coding: utf-8 -*-
"""翻译任意一批成分名，并合并进 data/ingredient_zh.json。

与 translate_ingredients.py 共用同一套翻译规则（宁可未知不可编造），
区别只是输入来自命令行而不是某味药的成分列表。

用法：
    python scripts/translate_names.py "glycyrrhizin" "berberine" ...
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.llm.client import LLMClient  # noqa: E402
from tcmqa.settings import DATA_DIR  # noqa: E402
from scripts.translate_ingredients import SYSTEM  # noqa: E402
from tcmqa.logging import setup_logging  # noqa: E402

ZH_PATH = DATA_DIR / "ingredient_zh.json"


def main() -> None:
    names = [n for n in sys.argv[1:] if n.strip()]
    if not names:
        print("用法: python scripts/translate_names.py <name1> <name2> ...")
        return

    setup_logging("WARNING")
    existing: dict[str, str] = {}
    if ZH_PATH.exists():
        existing = json.loads(ZH_PATH.read_text(encoding="utf-8"))

    todo = [n for n in names if n not in existing]
    print(f"输入 {len(names)}，已有 {len(names) - len(todo)}，待翻译 {len(todo)}")

    if todo:
        llm = LLMClient()
        try:
            data, result = llm.chat_json(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(todo, ensure_ascii=False)},
                ],
                temperature=0.0,
                max_tokens=1500,
            )
        finally:
            llm.close()

        added = 0
        for en, zh in data.items():
            if en in todo and isinstance(zh, str) and zh.strip():
                existing[en] = zh.strip()
                added += 1
        print(f"新增 {added} 条（{result.latency_ms:.0f}ms）")
        ZH_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )

    for n in names:
        print(f"  {n:<26} -> {existing.get(n, '未翻译')}")


if __name__ == "__main__":
    main()
