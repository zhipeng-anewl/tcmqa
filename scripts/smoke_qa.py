# -*- coding: utf-8 -*-
"""端到端冒烟：规划 → 检索 → 合成 → 引用校验。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.kg.client import GraphClient  # noqa: E402
from tcmqa.kg.linker import EntityLinker  # noqa: E402
from tcmqa.llm.client import LLMClient  # noqa: E402
from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.rag.pipeline import QAPipeline  # noqa: E402
from tcmqa.rag.retriever import SemanticRetriever  # noqa: E402
from tcmqa.settings import get_settings  # noqa: E402
from tcmqa.store.sqlite import Database  # noqa: E402

QUESTIONS = [
    "人参含有哪些化学成分？",
    "槲皮素作用于哪些靶点？",
    "有哪些清热解毒的中药？",
    "为什么麻黄能治疗哮喘？",
    "治疗乳腺癌的中药有多少味？",
]


def main() -> None:
    setup_logging("WARNING")
    settings = get_settings()

    graph = GraphClient()
    linker = EntityLinker(graph)
    linker.load()
    llm = LLMClient()
    semantic = SemanticRetriever(settings)
    semantic.load()
    db = Database(settings.sqlite_path)

    pipeline = QAPipeline(llm, graph, linker, semantic, db, settings)

    for question in QUESTIONS:
        print("=" * 78)
        print("问题：", question)
        t0 = time.perf_counter()
        result = pipeline.answer(question, session_id="smoke")
        took = (time.perf_counter() - t0) * 1000

        print(f"意图：{result.intent}  耗时：{took:.0f}ms  证据数：{len(result.evidence)}")
        print("规划：", json.dumps(result.plan, ensure_ascii=False))
        if result.cypher:
            print("Cypher：", result.cypher.replace("\n", " "))
        if result.attempts:
            print("尝试次数：", len(result.attempts),
                  [(a["ok"], a["rows"], a["error"][:60]) for a in result.attempts])
        print("引用校验：", result.citations)
        print("回答：", result.answer[:400].replace("\n", " "))
        print("trace：", json.dumps(
            {
                "elapsed_ms": result.trace.get("elapsed_ms"),
                "tokens": result.trace.get("total_tokens"),
                "cost": result.trace.get("cost_cny"),
                "stages": result.trace.get("stage_ms"),
            },
            ensure_ascii=False,
        ))

    print("=" * 78)
    print("指标：", json.dumps(db.metrics(), ensure_ascii=False))

    db.close()
    semantic.embedder._model = None
    graph.close()
    llm.close()


if __name__ == "__main__":
    main()
