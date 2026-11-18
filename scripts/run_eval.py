# -*- coding: utf-8 -*-
"""跑金标集评测并生成报告。

用法：
    python scripts/run_eval.py                     # 全量
    python scripts/run_eval.py --limit 8           # 先跑前 8 条冒烟
    python scripts/run_eval.py --no-judge          # 关闭 LLM 评审（只算客观指标）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcmqa.api.deps import build_services  # noqa: E402
from tcmqa.eval.golden import load_cases  # noqa: E402
from tcmqa.eval.runner import Evaluator, render_markdown  # noqa: E402
from tcmqa.logging import setup_logging  # noqa: E402
from tcmqa.settings import get_settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--name", default="full")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--judge-ratio", type=float, default=0.3)
    parser.add_argument("--out", default="docs/eval_report.md")
    parser.add_argument("--json-out", default="data/eval_last.json")
    parser.add_argument(
        "--ablate",
        nargs="*",
        choices=["none", "vector", "aliases", "repair", "weak_prompt"],
        default=[],
        help="消融实验：可组合，如 --ablate weak_prompt repair（弱提示词 + 关修复）",
    )
    parser.add_argument("--ids", default="", help="只跑指定 ID，逗号分隔，如 R01,R07")
    args = parser.parse_args()

    setup_logging("WARNING")
    settings = get_settings()
    flags = [f for f in (args.ablate or []) if f != "none"]
    if flags:
        settings = settings.model_copy(update={f"ablate_{f}": True for f in flags})

    services = build_services(settings)

    cases = load_cases()
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[: args.limit]
    label = args.name if not flags else f"{args.name}-ablate-{'+'.join(flags)}"
    print(f"加载用例 {len(cases)} 条" + (f"（消融：{'+'.join(flags)}）" if flags else ""))

    evaluator = Evaluator(
        services.pipeline, services.graph, services.linker, services.llm,
        services.db, services.settings,
    )
    summary = evaluator.run(
        cases,
        name=label,
        judge=not args.no_judge,
        judge_ratio=args.judge_ratio,
    )

    case_rows = summary.pop("cases")
    report = render_markdown(summary, case_rows)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(
        json.dumps({"summary": summary, "cases": case_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(report.split("## 分类表现")[0])
    print(f"\n报告已写入 {out}")

    services.close()


if __name__ == "__main__":
    main()
