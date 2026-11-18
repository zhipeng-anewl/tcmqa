# -*- coding: utf-8 -*-
"""把消融实验的结果汇总成一张表，并列出失败用例。"""

from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def main() -> None:
    for name in ["vector", "aliases", "repair", "weak", "weak_norepair"]:
        path = BASE / "data" / f"ablation_{name}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = data["summary"]
        cases = data["cases"]
        fails = [c for c in cases if not c["passed"]]
        print(f"== {name}: {summary['passed']}/{summary['total']} 通过，失败 {len(fails)} 条")
        for c in fails:
            print(f"   {c['id']:<4} {c['question'][:32]:<34} {c['reason'][:70]}")
        print()


if __name__ == "__main__":
    main()
