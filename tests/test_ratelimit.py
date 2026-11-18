# -*- coding: utf-8 -*-
"""限流器的单元测试（不需要起服务、不花钱）。"""

from __future__ import annotations

import pytest

from tcmqa.api.ratelimit import RateLimiter, client_ip


class TestTokenBucket:
    def test_disabled_limiter_allows_everything(self):
        limiter = RateLimiter(per_minute=0, daily_limit=0)
        assert not limiter.enabled
        for _ in range(100):
            assert limiter.allow("1.1.1.1")[0]

    def test_burst_then_block(self):
        limiter = RateLimiter(per_minute=3)
        assert [limiter.allow("1.1.1.1")[0] for _ in range(3)] == [True, True, True]
        ok, retry_after, reason = limiter.allow("1.1.1.1")
        assert not ok
        assert reason == "minute"
        assert retry_after >= 1

    def test_buckets_are_per_ip(self):
        limiter = RateLimiter(per_minute=1)
        assert limiter.allow("1.1.1.1")[0]
        assert not limiter.allow("1.1.1.1")[0]
        # 另一个 IP 有自己的桶
        assert limiter.allow("2.2.2.2")[0]

    def test_tokens_refill_over_time(self, monkeypatch):
        limiter = RateLimiter(per_minute=60)  # 每秒补 1 个
        for _ in range(60):
            assert limiter.allow("1.1.1.1")[0]
        assert not limiter.allow("1.1.1.1")[0]

        # 把时间往前拨 2 秒，应该补回 2 个令牌
        import tcmqa.api.ratelimit as mod

        real_time = mod.time.time
        monkeypatch.setattr(mod.time, "time", lambda: real_time() + 2)
        assert limiter.allow("1.1.1.1")[0]
        assert limiter.allow("1.1.1.1")[0]
        assert not limiter.allow("1.1.1.1")[0]


class TestDailyQuota:
    def test_daily_limit_blocks_after_quota(self):
        limiter = RateLimiter(per_minute=0, daily_limit=2)
        assert limiter.allow("a")[0]
        assert limiter.allow("b")[0]
        ok, _, reason = limiter.allow("c")
        assert not ok
        assert reason == "daily"

    def test_stats_shape(self):
        limiter = RateLimiter(per_minute=5, daily_limit=10)
        limiter.allow("1.1.1.1")
        stats = limiter.stats()
        assert stats["per_minute"] == 5
        assert stats["daily_limit"] == 10
        assert stats["used_today"] == 1
        assert stats["tracked_ips"] == 1


class TestClientIp:
    def test_uses_peer_by_default(self):
        headers = {"x-forwarded-for": "9.9.9.9"}
        assert client_ip(headers, "127.0.0.1") == "127.0.0.1"

    def test_trusts_forwarded_header_when_configured(self):
        headers = {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}
        assert client_ip(headers, "127.0.0.1", trust_proxy=True) == "9.9.9.9"

    def test_falls_back_when_header_missing(self):
        assert client_ip({}, "127.0.0.1", trust_proxy=True) == "127.0.0.1"


@pytest.mark.parametrize("path", ["/api/chat", "/api/chat/stream", "/api/vision/search-image"])
def test_costly_paths_are_the_ones_limited_by_middleware(path):
    """中间件用的是同一个前缀表，这里防止以后改路径忘了同步。"""
    costly = ("/api/chat", "/api/vision", "/api/graph/cypher")
    assert path.startswith(costly)
