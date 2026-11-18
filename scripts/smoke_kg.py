# -*- coding: utf-8 -*-
"""图谱层冒烟测试：连接、统计、实体链接、功效识别、守卫。"""

from __future__ import annotations

import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from tcmqa.kg import CypherGuard, EntityLinker, GraphClient  # noqa: E402


def main() -> None:
    t0 = time.perf_counter()
    client = GraphClient()
    print("连接成功 %.0fms" % ((time.perf_counter() - t0) * 1000))

    stats = client.stats()
    print("节点", stats["nodes"], "关系", stats["relationships"])
    print("标签", stats["labels"])
    print("关系类型", stats["relationship_types"])

    t0 = time.perf_counter()
    linker = EntityLinker(client)
    linker.load()
    print("链接索引加载 %.0fms" % ((time.perf_counter() - t0) * 1000))

    cases = [
        ("人参", "Herb", []),
        ("槲皮素", "Ingredient", ["quercetin"]),
        ("糖尿病", "Disease", ["diabetes", "Diabetes Mellitus"]),
        ("人参皂苷", "Ingredient", []),
        ("EGFR", "Target", []),
    ]
    for raw, etype, aliases in cases:
        res = linker.link(raw, etype, aliases)
        print(f"链接 {raw!r} -> {json.dumps(res.to_dict(), ensure_ascii=False)}")

    print("功效识别:", linker.detect_effects("有哪些清热解毒的药？手脚冰凉的适合吃啥"))

    guard = CypherGuard(max_rows=50)
    tests = [
        "MATCH (h:Herb) RETURN h.name AS herb",
        "MATCH (h:Herb) RETURN h.name AS herb LIMIT 999",
        "CREATE (n:Herb {name:'x'})",
        "MATCH (n) RETURN n; DROP DATABASE neo4j",
        "MATCH (n) // comment\nRETURN n",
        "MATCH (h:Herb) WHERE h.name = 'SET' RETURN h",
    ]
    for q in tests:
        ok, reason = guard.validate(q)
        prepared = guard.prepare(q) if ok else ""
        print(f"[{'PASS' if ok else 'BLOCK'}] {q!r} -> {reason or prepared}")

    client.close()


if __name__ == "__main__":
    main()
