# -*- coding: utf-8 -*-
"""SQLite 持久化。

选 SQLite 而不是 Postgres，是因为这个项目的并发量（个人/答辩演示）远达不到需要
独立数据库的程度，单文件零运维，还能直接进 gitignore。

存四类东西：
- 会话与消息：多轮对话要能回放，刷新页面不丢；
- 轨迹 trace：每次问答各阶段耗时、token、成本，用于 /metrics 和排障；
- 反馈：点踩的数据是后续优化的输入（典型 RLHF/评测闭环的起点）；
- 缓存：精确缓存 + 语义缓存的向量，命中率直接体现在成本和延迟上。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta_json TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT,
    question TEXT,
    answer TEXT,
    intent TEXT,
    elapsed_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_cny REAL,
    detail_json TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_time ON traces(created_at DESC);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    rating INTEGER NOT NULL,
    comment TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cache_entries (
    key TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    payload_json TEXT,
    embedding BLOB,
    hits INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    name TEXT,
    config_json TEXT,
    metrics_json TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    question TEXT,
    intent TEXT,
    passed INTEGER,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_cases_run ON eval_cases(run_id);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # 会话
    # ------------------------------------------------------------------ #
    def ensure_session(self, session_id: str | None, title: str | None = None) -> str:
        sid = session_id or uuid.uuid4().hex
        now = time.time()
        existing = self._query("SELECT id FROM sessions WHERE id = ?", (sid,))
        if not existing:
            self._exec(
                "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?,?,?,?)",
                (sid, (title or "新会话")[:60], now, now),
            )
        else:
            self._exec("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, sid))
        return sid

    def list_sessions(self, limit: int = 30) -> list[dict[str, Any]]:
        return self._query(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self._exec(
            "INSERT INTO messages(session_id, role, content, meta_json, created_at) "
            "VALUES (?,?,?,?,?)",
            (session_id, role, content, json.dumps(meta or {}, ensure_ascii=False), time.time()),
        )

    def get_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT role, content, meta_json, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        rows.reverse()
        for r in rows:
            try:
                r["meta"] = json.loads(r.pop("meta_json") or "{}")
            except json.JSONDecodeError:
                r["meta"] = {}
        return rows

    # ------------------------------------------------------------------ #
    # 轨迹
    # ------------------------------------------------------------------ #
    def save_trace(self, payload: dict[str, Any], answer: str, intent: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO traces(trace_id, session_id, question, answer, intent, "
            "elapsed_ms, prompt_tokens, completion_tokens, cost_cny, detail_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload.get("trace_id"),
                payload.get("session_id"),
                payload.get("question"),
                answer[:4000],
                intent,
                payload.get("elapsed_ms"),
                payload.get("prompt_tokens"),
                payload.get("completion_tokens"),
                payload.get("cost_cny"),
                json.dumps(payload, ensure_ascii=False),
                time.time(),
            ),
        )

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT detail_json FROM traces WHERE trace_id = ?", (trace_id,))
        if not rows:
            return None
        try:
            return json.loads(rows[0]["detail_json"])
        except json.JSONDecodeError:
            return None

    def recent_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._query(
            "SELECT trace_id, question, intent, elapsed_ms, prompt_tokens, completion_tokens, "
            "cost_cny, created_at FROM traces ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    def metrics(self) -> dict[str, Any]:
        row = self._query(
            "SELECT count(*) AS total, avg(elapsed_ms) AS avg_ms, "
            "sum(prompt_tokens) AS prompt_tokens, sum(completion_tokens) AS completion_tokens, "
            "sum(cost_cny) AS cost FROM traces"
        )[0]
        intents = self._query(
            "SELECT intent, count(*) AS cnt FROM traces GROUP BY intent ORDER BY cnt DESC"
        )
        total = row["total"] or 0
        return {
            "questions": total,
            "avg_latency_ms": round(row["avg_ms"] or 0, 1),
            "prompt_tokens": row["prompt_tokens"] or 0,
            "completion_tokens": row["completion_tokens"] or 0,
            "total_cost_cny": round(row["cost"] or 0, 4),
            "cost_per_question_cny": round((row["cost"] or 0) / total, 4) if total else 0,
            "intents": {r["intent"]: r["cnt"] for r in intents},
        }

    # ------------------------------------------------------------------ #
    # 反馈
    # ------------------------------------------------------------------ #
    def add_feedback(self, trace_id: str, rating: int, comment: str = "") -> None:
        self._exec(
            "INSERT INTO feedback(trace_id, rating, comment, created_at) VALUES (?,?,?,?)",
            (trace_id, rating, comment[:500], time.time()),
        )

    def feedback_stats(self) -> dict[str, Any]:
        rows = self._query(
            "SELECT rating, count(*) AS cnt FROM feedback GROUP BY rating"
        )
        data = {str(r["rating"]): r["cnt"] for r in rows}
        up = data.get("1", 0)
        down = data.get("-1", 0)
        return {"up": up, "down": down, "total": up + down}

    # ------------------------------------------------------------------ #
    # 缓存
    # ------------------------------------------------------------------ #
    def cache_get(self, key: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM cache_entries WHERE key = ?", (key,))
        if not rows:
            return None
        self._exec("UPDATE cache_entries SET hits = hits + 1 WHERE key = ?", (key,))
        row = rows[0]
        try:
            row["payload"] = json.loads(row.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            row["payload"] = {}
        return row

    def cache_put(
        self,
        key: str,
        question: str,
        answer: str,
        payload: dict[str, Any],
        embedding: bytes | None = None,
    ) -> None:
        self._exec(
            "INSERT OR REPLACE INTO cache_entries(key, question, answer, payload_json, "
            "embedding, hits, created_at) VALUES (?,?,?,?,?,0,?)",
            (key, question, answer, json.dumps(payload, ensure_ascii=False), embedding, time.time()),
        )

    def cache_questions(self, limit: int = 2000) -> list[dict[str, Any]]:
        return self._query(
            "SELECT key, question, embedding, created_at FROM cache_entries "
            "WHERE embedding IS NOT NULL ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    def cache_stats(self) -> dict[str, Any]:
        row = self._query(
            "SELECT count(*) AS entries, coalesce(sum(hits), 0) AS hits FROM cache_entries"
        )[0]
        return {"entries": row["entries"], "hits": row["hits"]}

    def purge_cache(self, ttl_seconds: int) -> int:
        cutoff = time.time() - ttl_seconds
        cur = self._exec("DELETE FROM cache_entries WHERE created_at < ?", (cutoff,))
        return cur.rowcount

    # ------------------------------------------------------------------ #
    # 评测
    # ------------------------------------------------------------------ #
    def save_eval_run(
        self,
        run_id: str,
        name: str,
        config: dict[str, Any],
        metrics: dict[str, Any],
        cases: list[dict[str, Any]],
    ) -> None:
        self._exec(
            "INSERT OR REPLACE INTO eval_runs(run_id, name, config_json, metrics_json, created_at) "
            "VALUES (?,?,?,?,?)",
            (
                run_id,
                name,
                json.dumps(config, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False),
                time.time(),
            ),
        )
        for case in cases:
            self._exec(
                "INSERT INTO eval_cases(run_id, question, intent, passed, detail_json) "
                "VALUES (?,?,?,?,?)",
                (
                    run_id,
                    case.get("question"),
                    case.get("intent"),
                    1 if case.get("passed") else 0,
                    json.dumps(case, ensure_ascii=False),
                ),
            )

    def list_eval_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._query(
            "SELECT run_id, name, metrics_json, created_at FROM eval_runs "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
