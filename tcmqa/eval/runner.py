# -*- coding: utf-8 -*-
"""评测执行器。

跑一遍金标集，产出：
- 汇总指标（路由准确率、执行准确率、语义命中率、延迟分位、成本、引用合法率、修复率）
- 逐条明细（哪道题错了、错在哪、系统的 Cypher 长什么样）
- 一份 Markdown 报告，可直接贴进 README

金标集里 graph 题的期望是现算的，所以每次跑都在和「最新图谱」比对。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tcmqa.eval import metrics
from tcmqa.eval.golden import GoldenCase
from tcmqa.kg.client import GraphClient
from tcmqa.kg.linker import EntityLinker
from tcmqa.llm.client import LLMClient
from tcmqa.rag.pipeline import AnswerResult, QAPipeline
from tcmqa.settings import Settings, get_settings
from tcmqa.store.sqlite import Database

logger = logging.getLogger(__name__)


@dataclass
class CaseResult:
    case: GoldenCase
    answer: str
    predicted_intent: str
    routing_ok: bool
    passed: bool
    reason: str = ""
    scores: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    tokens: int = 0
    cost_cny: float = 0.0
    repairs: int = 0
    citation_ok: bool = True
    judge: dict[str, Any] = field(default_factory=dict)
    cypher: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "question": self.case.question,
            "intent": self.case.intent,
            "predicted_intent": self.predicted_intent,
            "mode": self.case.mode,
            "passed": self.passed,
            "routing_ok": self.routing_ok,
            "reason": self.reason,
            "scores": self.scores,
            "latency_ms": self.latency_ms,
            "tokens": self.tokens,
            "cost_cny": self.cost_cny,
            "repairs": self.repairs,
            "citation_ok": self.citation_ok,
            "judge": self.judge,
            "cypher": self.cypher,
            "answer": self.answer[:600],
            "error": self.error,
        }


class Evaluator:
    def __init__(
        self,
        pipeline: QAPipeline,
        graph: GraphClient,
        linker: EntityLinker,
        llm: LLMClient,
        db: Database,
        settings: Settings | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.graph = graph
        self.linker = linker
        self.llm = llm
        self.db = db
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    def run(
        self,
        cases: list[GoldenCase],
        name: str = "eval",
        *,
        judge: bool = True,
        judge_ratio: float = 0.3,
        persist: bool = True,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        results: list[CaseResult] = []

        for idx, case in enumerate(cases, start=1):
            result = self._run_case(case, judge=judge, judge_ratio=judge_ratio, index=idx)
            results.append(result)
            flag = "PASS" if result.passed else "FAIL"
            logger.info(
                "[%d/%d] %s %s %s", idx, len(cases), flag, case.id, case.question[:30]
            )
            if not result.passed:
                logger.info("        原因：%s", result.reason)

        summary = self._aggregate(results, name=name, run_id=run_id,
                                  elapsed=time.perf_counter() - started)
        if persist:
            try:
                self.db.save_eval_run(
                    run_id, name, summary["config"], summary, [r.to_dict() for r in results]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("评测结果落库失败：%s", exc)

        summary["cases"] = [r.to_dict() for r in results]
        return summary

    # ------------------------------------------------------------------ #
    def _run_case(
        self, case: GoldenCase, *, judge: bool, judge_ratio: float, index: int
    ) -> CaseResult:
        t0 = time.perf_counter()
        result: CaseResult | None = None

        try:
            answer: AnswerResult = self.pipeline.answer(
                case.question, session_id=f"eval-{case.id}", use_cache=False,
                history=case.history or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("用例执行失败 %s", case.id)
            return CaseResult(
                case=case, answer="", predicted_intent="", routing_ok=False,
                passed=False, reason=f"执行异常：{exc}", latency_ms=0.0,
            )

        elapsed = (time.perf_counter() - t0) * 1000
        predicted = "blocked" if result_blocked(answer) else answer.intent
        routing_ok = self._routing_ok(case, predicted)

        cr = CaseResult(
            case=case,
            answer=answer.answer,
            predicted_intent=predicted,
            routing_ok=routing_ok,
            passed=False,
            latency_ms=round(elapsed, 2),
            tokens=answer.trace.get("total_tokens", 0),
            cost_cny=answer.trace.get("cost_cny", 0.0),
            repairs=max(0, len(answer.attempts) - 1) if answer.attempts else 0,
            citation_ok=not answer.citations.get("has_invalid", False),
            cypher=answer.cypher,
        )

        try:
            passed, reason, scores = self._grade(case, answer, routing_ok)
        except Exception as exc:  # noqa: BLE001
            passed, reason, scores = False, f"判分异常：{exc}", {}

        cr.passed = passed
        cr.reason = reason
        cr.scores = scores

        # LLM 评审：显式标记的用例全评，其余按比例抽样，控制成本
        if judge and not case.expect_blocked:
            should = case.judge or (index % max(1, int(1 / max(judge_ratio, 0.01))) == 0)
            if should and answer.answer:
                evidence_text = "\n".join(f"[{e.id}] {e.text}" for e in answer.evidence)
                cr.judge = self._judge(case, answer, evidence_text)

        return cr

    # ------------------------------------------------------------------ #
    def _grade(
        self, case: GoldenCase, answer: AnswerResult, routing_ok: bool
    ) -> tuple[bool, str, dict[str, Any]]:
        scores: dict[str, Any] = {}

        if case.expect_blocked:
            blocked = answer.blocked
            return blocked, "" if blocked else "未被防护拦截", {"blocked": blocked}

        if case.mode == "set":
            universe = self.linker.name_universe(case.gold_label)
            gold_rows = self.graph.read(case.gold_cypher, limit=5000)
            gold = {str(next(iter(r.values()))) for r in gold_rows if r}
            gold &= universe
            pred = metrics.extract_values(answer.rows, case.gold_label, universe)
            scores = metrics.set_scores(pred, gold)
            scores["gold_size"] = len(gold)
            scores["pred_size"] = len(pred)
            ok = scores["f1"] >= case.threshold
            reason = "" if ok else (
                f"结果集不符：F1={scores['f1']:.2f} < {case.threshold}"
                f"（gold={len(gold)}, pred={len(pred)}）"
            )
            return ok, reason, scores

        if case.mode == "number":
            gold_rows = self.graph.read(case.gold_cypher, limit=1)
            if not gold_rows:
                return False, "标准答案查询无结果", {}
            gold_value = float(next(iter(gold_rows[0].values())))
            pred_numbers = metrics.numbers_in(answer.rows) + metrics.numbers_in(answer.answer)
            ok = metrics.number_matches(pred_numbers, gold_value, case.tolerance)
            scores = {"gold": gold_value, "matched": ok}
            return ok, "" if ok else f"数值不符：期望 {gold_value}", scores

        if case.mode == "hit":
            titles = [h.get("title", "") for h in answer.vector_hits]
            hit = any(any(exp in title for title in titles) for exp in case.expect_docs)
            scores = {"expected": case.expect_docs, "top_titles": titles[:5], "hit": hit}
            return hit, "" if hit else f"召回未命中：期望 {case.expect_docs}", scores

        # mode=none
        missing = [kw for kw in case.must_include if kw not in answer.answer]
        ok = routing_ok and not missing
        reason = ""
        if not routing_ok:
            reason = f"意图不符：期望 {case.intent}，实际 {answer.intent}"
        elif missing:
            reason = f"回答缺少关键词：{missing}"
        scores = {"missing_keywords": missing}
        return ok, reason, scores

    def _routing_ok(self, case: GoldenCase, predicted: str) -> bool:
        if case.expect_blocked:
            return predicted == "blocked"
        return predicted == case.intent

    # ------------------------------------------------------------------ #
    def _judge(
        self, case: GoldenCase, answer: AnswerResult, evidence_text: str
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            faith = metrics.judge_faithfulness(self.llm, answer.answer, evidence_text)
            out["faithful"] = faith.get("faithful")
            out["unsupported"] = faith.get("unsupported_claims", [])[:3]
        except Exception as exc:  # noqa: BLE001
            out["faithful_error"] = str(exc)

        try:
            rel = metrics.judge_relevance(self.llm, case.question, answer.answer)
            out["relevance"] = rel.get("score")
        except Exception as exc:  # noqa: BLE001
            out["relevance_error"] = str(exc)
        return out

    # ------------------------------------------------------------------ #
    def _aggregate(
        self, results: list[CaseResult], *, name: str, run_id: str, elapsed: float
    ) -> dict[str, Any]:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        routing = sum(1 for r in results if r.routing_ok)

        by_mode: dict[str, dict[str, Any]] = {}
        for r in results:
            bucket = by_mode.setdefault(r.case.mode, {"n": 0, "passed": 0, "f1": []})
            bucket["n"] += 1
            bucket["passed"] += 1 if r.passed else 0
            if "f1" in r.scores:
                bucket["f1"].append(r.scores["f1"])
        for bucket in by_mode.values():
            bucket["pass_rate"] = round(bucket["passed"] / bucket["n"], 3) if bucket["n"] else 0
            bucket["avg_f1"] = round(sum(bucket["f1"]) / len(bucket["f1"]), 3) if bucket["f1"] else None
            bucket.pop("f1")

        by_intent: dict[str, dict[str, Any]] = {}
        for r in results:
            bucket = by_intent.setdefault(r.case.intent, {"n": 0, "passed": 0})
            bucket["n"] += 1
            bucket["passed"] += 1 if r.passed else 0
        for bucket in by_intent.values():
            bucket["pass_rate"] = round(bucket["passed"] / bucket["n"], 3)

        by_difficulty: dict[str, dict[str, Any]] = {}
        for r in results:
            bucket = by_difficulty.setdefault(r.case.difficulty, {"n": 0, "passed": 0})
            bucket["n"] += 1
            bucket["passed"] += 1 if r.passed else 0
        for bucket in by_difficulty.values():
            bucket["pass_rate"] = round(bucket["passed"] / bucket["n"], 3)

        latencies = [r.latency_ms for r in results]
        judged = [r for r in results if r.judge.get("faithful") is not None]
        # 切题度只在「本来就该回答」的意图上统计：
        # out_of_scope / chitchat 的正确答案是「不回答」，算切题度会系统性拉低均值。
        ANSWERABLE = {"lookup", "relation", "aggregate", "mechanism", "semantic"}
        relevance = [
            r.judge["relevance"]
            for r in results
            if r.case.intent in ANSWERABLE
            and isinstance(r.judge.get("relevance"), (int, float))
        ]

        return {
            "run_id": run_id,
            "name": name,
            "total": total,
            "passed": passed,
            "pass_rate": round(passed / total, 3) if total else 0.0,
            "routing_accuracy": round(routing / total, 3) if total else 0.0,
            "citation_valid_rate": round(
                sum(1 for r in results if r.citation_ok) / total, 3
            ) if total else 0.0,
            "repair_rate": round(sum(1 for r in results if r.repairs > 0) / total, 3) if total else 0.0,
            "by_mode": by_mode,
            "by_intent": by_intent,
            "by_difficulty": by_difficulty,
            "latency_ms": {
                "avg": round(sum(latencies) / len(latencies), 1) if latencies else 0,
                "p50": metrics.percentile(latencies, 0.5),
                "p95": metrics.percentile(latencies, 0.95),
                "max": round(max(latencies), 1) if latencies else 0,
            },
            "tokens": {
                "total": sum(r.tokens for r in results),
                "avg": round(sum(r.tokens for r in results) / total, 1) if total else 0,
            },
            "cost_cny": {
                "total": round(sum(r.cost_cny for r in results), 4),
                "per_question": round(sum(r.cost_cny for r in results) / total, 5) if total else 0,
            },
            "judge": {
                "n": len(judged),
                "faithful_rate": round(
                    sum(1 for r in judged if r.judge.get("faithful")) / len(judged), 3
                ) if judged else None,
                "avg_relevance": round(sum(relevance) / len(relevance), 3) if relevance else None,
            },
            "elapsed_sec": round(elapsed, 1),
            "config": {
                "model": self.settings.llm_model,
                "embedding_model": self.settings.embedding_model,
                "cypher_max_repair": self.settings.cypher_max_repair,
            },
        }


def result_blocked(result: AnswerResult) -> bool:
    return bool(result.blocked)


# ---------------------------------------------------------------------- #
def render_markdown(summary: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    lines = [
        "# 评测报告",
        "",
        f"- 运行 ID：`{summary['run_id']}`",
        f"- 模型：`{summary['config']['model']}` / embedding `{summary['config']['embedding_model']}`",
        f"- 用例数：**{summary['total']}**，通过 **{summary['passed']}**（{summary['pass_rate']:.1%}）",
        f"- 总耗时：{summary['elapsed_sec']}s",
        "",
        "## 汇总指标",
        "",
        "| 指标 | 数值 | 说明 |",
        "| --- | --- | --- |",
        f"| 端到端通过率 | {summary['pass_rate']:.1%} | 所有用例的综合通过率 |",
        f"| 意图路由准确率 | {summary['routing_accuracy']:.1%} | 规划器判断的意图是否与标注一致 |",
        f"| 引用合法率 | {summary['citation_valid_rate']:.1%} | 答案里的 [En] 是否都能在证据中找到 |",
        f"| 自修复触发率 | {summary['repair_rate']:.1%} | 需要二次生成 Cypher 的比例 |",
        f"| 平均延迟 | {summary['latency_ms']['avg']} ms | P50 {summary['latency_ms']['p50']} / P95 {summary['latency_ms']['p95']} |",
        f"| 平均 token | {summary['tokens']['avg']} | 单次问答输入+输出 |",
        f"| 单次成本 | ¥{summary['cost_cny']['per_question']} | 按 DeepSeek 官方价估算 |",
    ]

    judge = summary.get("judge") or {}
    if judge.get("n"):
        lines.append(
            f"| 忠实度（LLM 评审） | {judge['faithful_rate']:.1%} | 抽评 {judge['n']} 条，答案是否都能被证据支持 |"
        )
    if judge.get("avg_relevance") is not None:
        lines.append(f"| 切题度（LLM 评审） | {judge['avg_relevance']:.2f} / 1 | 抽评答案与问题的相关程度 |")

    lines += ["", "## 分类表现", "", "| 类型 | 用例 | 通过 | 通过率 | 平均 F1 |", "| --- | --- | --- | --- | --- |"]
    for mode, bucket in summary["by_mode"].items():
        f1 = f"{bucket['avg_f1']:.2f}" if bucket["avg_f1"] is not None else "—"
        lines.append(
            f"| {mode} | {bucket['n']} | {bucket['passed']} | {bucket['pass_rate']:.1%} | {f1} |"
        )

    lines += ["", "## 按意图", "", "| 意图 | 用例 | 通过 | 通过率 |", "| --- | --- | --- | --- |"]
    for intent, bucket in summary["by_intent"].items():
        lines.append(
            f"| {intent} | {bucket['n']} | {bucket['passed']} | {bucket['pass_rate']:.1%} |"
        )

    by_difficulty = summary.get("by_difficulty") or {}
    if by_difficulty:
        lines += ["", "## 按难度", "", "| 难度 | 用例 | 通过 | 通过率 |", "| --- | --- | --- | --- |"]
        for level, bucket in by_difficulty.items():
            name = {"normal": "常规", "hard": "难例"}.get(level, level)
            lines.append(
                f"| {name} | {bucket['n']} | {bucket['passed']} | {bucket['pass_rate']:.1%} |"
            )

    lines += ["", "## 逐条结果", "", "| ID | 问题 | 意图 | 结果 | 耗时 | 备注 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for case in cases:
        flag = "✅" if case["passed"] else "❌"
        reason = (case.get("reason") or "").replace("|", "\\|")[:70]
        lines.append(
            f"| {case['id']} | {case['question'][:28]} | {case['intent']} | {flag} | "
            f"{case['latency_ms']:.0f}ms | {reason} |"
        )

    lines += [
        "",
        "> 说明：`mode=set` 的用例用「标准 Cypher 现算结果集」与系统返回做集合比对；",
        "> 标准集大于 30 时因系统受 LIMIT 约束只计算精度，不再计算召回。",
    ]
    return "\n".join(lines)
