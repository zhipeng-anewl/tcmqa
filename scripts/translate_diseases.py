# -*- coding: utf-8 -*-
"""批量生成疾病中文译名（可选增强）。

为什么需要：图谱里的疾病名是英文 ICD 术语（`Psoriasis`、`Osteoporosis`），
而 bge-small-zh 是中文模型，用户说「银屑病」「骨质疏松」时向量检索召回不到。
把 867 个病名翻译成中文后拼进语料，中文提问就能命中疾病文档。

做法：分批（默认 40 个/批）让模型输出 JSON 映射表，失败重试、断点续跑。
成本：约 20 次调用，几分钱。

用法：
    python scripts/translate_diseases.py
    python scripts/translate_diseases.py --batch 30
生成 data/disease_zh.json 后，重新跑 scripts/build_index.py 才会生效。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.llm.client import LLMClient  # noqa: E402
from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.settings import DATA_DIR  # noqa: E402

OUT_PATH = DATA_DIR / "disease_zh.json"

SYSTEM = """你是医学翻译。把用户给出的英文疾病名翻译成规范的中文医学名词。

要求：
1. 用中国大陆临床常用的标准译名（如 Psoriasis → 银屑病，Hypertension → 高血压）。
2. 不确定时给出最接近的通用译名，不要留空，不要解释。
3. 只输出 JSON 对象，键是原始英文名（必须逐字保留、大小写一致），值是中文名。
4. 不要输出任何其他文字。"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, default=40)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    setup_logging("WARNING")

    with GraphClient() as client:
        rows = client.read("MATCH (d:Disease) RETURN d.name AS name ORDER BY d.name", limit=5000)
    names = [str(r["name"]) for r in rows if r.get("name")]
    if args.limit:
        names = names[: args.limit]

    existing: dict[str, str] = {}
    if OUT_PATH.exists():
        try:
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    todo = [n for n in names if n not in existing]
    print(f"疾病总数 {len(names)}，已有译名 {len(existing)}，待翻译 {len(todo)}")

    if not todo:
        print("无需翻译")
        return

    llm = LLMClient()
    batches = [todo[i : i + args.batch] for i in range(0, len(todo), args.batch)]

    try:
        for idx, batch in enumerate(batches, start=1):
            payload = "\n".join(batch)
            try:
                data, result = llm.chat_json(
                    [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": payload},
                    ],
                    temperature=0.0,
                    max_tokens=2000,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{idx}/{len(batches)}] 失败：{exc}")
                continue

            added = 0
            for en, zh in data.items():
                if isinstance(zh, str) and zh.strip() and en in batch:
                    existing[en] = zh.strip()
                    added += 1
            print(f"[{idx}/{len(batches)}] 新增 {added} 条（{result.latency_ms:.0f}ms）")

            OUT_PATH.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            time.sleep(0.3)
    finally:
        llm.close()

    print(f"完成，共 {len(existing)} 条 → {OUT_PATH}")
    print("提示：重新运行 python scripts/build_index.py 让译名进入检索语料")


if __name__ == "__main__":
    main()
