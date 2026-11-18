# -*- coding: utf-8 -*-
"""调试：直接看规划器的原始输出。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.kg.linker import EntityLinker  # noqa: E402
from tcmqa.llm.client import LLMClient  # noqa: E402
from tcmqa.rag.planner import Planner  # noqa: E402


def main() -> None:
    graph = GraphClient()
    linker = EntityLinker(graph)
    linker.load()
    llm = LLMClient()
    planner = Planner(llm, linker)

    for q in [
        "麻黄治疗哮喘的作用机制是什么？",
        "为什么麻黄能治疗哮喘？",
        "人参含有哪些化学成分？",
    ]:
        plan = planner.plan(q)
        print("问题:", q)
        print("  intent =", plan.intent, "| source =", plan.source)
        print("  raw =", json.dumps(plan.raw, ensure_ascii=False))
        print()

    llm.close()
    graph.close()


if __name__ == "__main__":
    main()
