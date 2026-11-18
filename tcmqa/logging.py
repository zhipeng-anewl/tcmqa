# -*- coding: utf-8 -*-
"""结构化日志：一行一个 JSON，方便 grep / 接 Loki / 做耗时统计。

关键点是 request_id 用 contextvars 传递，不用在每层函数签名里加参数。
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> contextvars.Token:
    return request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    request_id_var.reset(token)


def current_request_id() -> str:
    return request_id_var.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    # 第三方库降噪
    for noisy in (
        "neo4j", "httpx", "httpcore", "urllib3", "sentence_transformers",
        "jieba", "transformers", "torch", "huggingface_hub", "filelock",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.LoggerAdapter:
    return logging.LoggerAdapter(logging.getLogger(name), {})


def log_extra(**fields) -> dict:
    """给 logger 传结构化字段：logger.info("x", extra=log_extra(k=v))。"""
    return {"fields": fields}
