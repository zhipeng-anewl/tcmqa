# -*- coding: utf-8 -*-
"""LLM 客户端：DeepSeek（OpenAI 兼容协议），同步 + 流式。

自己做封装而不是直接 import openai，是因为这里要解决四件事：
1. 统一重试（429 / 5xx / 超时），带指数退避；
2. 把 usage 回传给 Trace，做 token 与成本核算；
3. 流式输出给 SSE 用，要让上层能拿到增量文本；
4. JSON 模式要能拿到结构化结果，解析失败时能降级重试。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from tcmqa.settings import Settings, get_settings


class LLMError(RuntimeError):
    """不可恢复的调用错误（配置缺失、4xx 等）。"""


class LLMTransientError(LLMError):
    """可重试错误（限流、网关错误、超时）。"""


@dataclass
class LLMResult:
    text: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.deepseek_api_key:
            raise LLMError("未配置 DEEPSEEK_API_KEY，请在项目根目录 .env 中填写")
        self._client = httpx.Client(
            base_url=self.settings.llm_base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=10.0, read=self.settings.llm_timeout, write=30.0, pool=10.0
            ),
            headers={
                "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
        )

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def _payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @retry(
        retry=retry_if_exception_type(LLMTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            resp = self._client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"LLM 请求超时：{exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError(f"LLM 网络错误：{exc}") from exc

        if resp.status_code in (429, 500, 502, 503, 504):
            raise LLMTransientError(f"LLM 暂时不可用（HTTP {resp.status_code}）")
        if resp.status_code != 200:
            raise LLMError(f"LLM 调用失败（HTTP {resp.status_code}）：{resp.text[:400]}")
        return resp

    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1500,
        json_mode: bool = False,
    ) -> LLMResult:
        payload = self._payload(messages, temperature, max_tokens, json_mode, stream=False)
        started = time.perf_counter()
        resp = self._post(payload)
        latency = round((time.perf_counter() - started) * 1000, 2)
        data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"LLM 返回结构异常：{data}")
        message = choices[0].get("message") or {}
        usage = data.get("usage") or {}
        return LLMResult(
            text=message.get("content") or "",
            model=data.get("model", self.settings.llm_model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            cached_tokens=int(usage.get("prompt_cache_hit_tokens") or 0),
            latency_ms=latency,
            finish_reason=choices[0].get("finish_reason") or "",
            raw=data,
        )

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> tuple[dict[str, Any], LLMResult]:
        """JSON 模式；解析失败时补一句纠正再试一次。"""
        result = self.chat(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=True
        )
        try:
            return json.loads(result.text), result
        except json.JSONDecodeError:
            repair = messages + [
                {"role": "assistant", "content": result.text},
                {
                    "role": "user",
                    "content": "上面的输出不是合法 JSON。只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。",
                },
            ]
            retry_result = self.chat(
                repair, temperature=0.0, max_tokens=max_tokens, json_mode=True
            )
            try:
                return json.loads(retry_result.text), retry_result
            except json.JSONDecodeError as exc:
                raise LLMError(f"LLM 无法返回合法 JSON：{retry_result.text[:300]}") from exc

    # ------------------------------------------------------------------ #
    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1500,
        usage_sink: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """逐 token 产出文本增量。异常在生成器内部抛出，由上层兜底。

        usage_sink 传入一个 dict，流结束前会把 usage 写进去（deepseek 在最后一个
        chunk 里带 usage），否则流式请求的 token 计费就统计不到。
        """
        payload = self._payload(messages, temperature, max_tokens, False, stream=True)
        try:
            with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", "replace")
                    if resp.status_code in (429, 500, 502, 503, 504):
                        raise LLMTransientError(f"流式请求失败（HTTP {resp.status_code}）")
                    raise LLMError(f"流式请求失败（HTTP {resp.status_code}）：{body[:400]}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    if usage_sink is not None and data.get("usage"):
                        usage_sink.update(data["usage"])
                    for choice in data.get("choices") or []:
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            yield piece
        except httpx.TimeoutException as exc:
            raise LLMTransientError(f"流式请求超时：{exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMTransientError(f"流式网络错误：{exc}") from exc
