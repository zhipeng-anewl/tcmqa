# -*- coding: utf-8 -*-
"""进程内限流：按 IP 的令牌桶 + 每日全局配额。

为什么要有：
    公网部署时用的是一张真实的 DeepSeek 账单，一次问答 3 次 LLM 调用（约 ¥0.006）。
    一个爬虫或者一条被转发的链接就能把额度打光，所以限流不是「加分项」，是公网上线的底线。

为什么不用 Redis：
    单机单进程，进程内字典足够；引入 Redis 只多一个故障点。
    多副本部署时把 `RateLimiter.allow` 换成 Redis 的 INCR + EXPIRE 即可，接口不变。

两个阈值分工不同：
    - 每分钟令牌桶：挡住瞬时刷接口（连点、脚本循环）；
    - 每日全局配额：兜住总成本，晚上被人转发到群里也不会烧穿账单。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    """一个 IP 的令牌桶。"""

    tokens: float
    updated: float


class RateLimiter:
    """线程安全的令牌桶 + 每日配额。

    参数为 0 表示关闭对应限制：
        limiter = RateLimiter(per_minute=6, daily_limit=800)
        ok, retry_after, reason = limiter.allow("1.2.3.4")
    """

    def __init__(self, per_minute: int = 0, daily_limit: int = 0) -> None:
        self.per_minute = max(0, int(per_minute))
        self.daily_limit = max(0, int(daily_limit))
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._day = time.strftime("%Y-%m-%d")
        self._used_today = 0
        self._last_sweep = time.time()

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0 or self.daily_limit > 0

    def allow(self, key: str) -> tuple[bool, int, str]:
        """尝试消耗一个令牌。

        返回 ``(是否放行, Retry-After 秒数, 拒绝原因)``；
        放行时后两项为空。拒绝原因是 ``"minute"`` / ``"daily"``。
        """
        now = time.time()
        with self._lock:
            day = time.strftime("%Y-%m-%d")
            if day != self._day:  # 跨天重置全局配额
                self._day = day
                self._used_today = 0

            if self.daily_limit and self._used_today >= self.daily_limit:
                # 到明天零点还有多久，粗略按 1 小时给建议值即可
                return False, 3600, "daily"

            if self.per_minute:
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = _Bucket(tokens=float(self.per_minute), updated=now)
                    self._buckets[key] = bucket

                rate = self.per_minute / 60.0  # 每秒补充的令牌数
                bucket.tokens = min(
                    float(self.per_minute), bucket.tokens + (now - bucket.updated) * rate
                )
                bucket.updated = now

                if bucket.tokens < 1.0:
                    retry = max(1, int((1.0 - bucket.tokens) / rate) + 1)
                    return False, retry, "minute"

                bucket.tokens -= 1.0

            self._used_today += 1
            if len(self._buckets) > 5000:
                self._sweep(now)
            return True, 0, ""

    def _sweep(self, now: float) -> None:
        """清掉 10 分钟没动过的桶，避免字典无限增长（单机长跑时很重要）。"""
        stale = [ip for ip, b in self._buckets.items() if now - b.updated > 600]
        for ip in stale:
            self._buckets.pop(ip, None)
        self._last_sweep = now

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "per_minute": self.per_minute,
                "daily_limit": self.daily_limit,
                "used_today": self._used_today,
                "tracked_ips": len(self._buckets),
            }


def client_ip(headers: dict[str, str] | None, peer: str, trust_proxy: bool = False) -> str:
    """取真实客户端 IP。

    只有明确知道自己在反向代理后面时才信 ``X-Forwarded-For``——
    否则任何人都能伪造这个头绕过限流。
    """
    if trust_proxy and headers:
        forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip() or peer
    return peer or "unknown"
