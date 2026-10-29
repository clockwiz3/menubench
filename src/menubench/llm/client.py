"""OpenRouter chat client: retries, fallback models, cost accounting and the response cache."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from menubench.llm.cache import CacheMiss, CacheMode, ResponseCache, cache_key

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    pass


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing environment wins."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.lstrip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


@dataclass(frozen=True)
class ImagePart:
    """An image prepared for a request; the hash stands in for the bytes in cache keys."""

    data_url: str
    sha: str
    width: int
    height: int

    @classmethod
    def from_image(cls, image: Image.Image, max_side: int = 1600, fmt: str = "PNG") -> ImagePart:
        img = image.convert("RGB")
        scale = min(1.0, max_side / max(img.size))
        if scale < 1.0:
            img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        if fmt == "JPEG":
            img.save(buf, format="JPEG", quality=90)
            mime = "image/jpeg"
        else:
            img.save(buf, format="PNG", optimize=True)
            mime = "image/png"
        raw = buf.getvalue()
        return cls(
            data_url=f"data:{mime};base64,{base64.b64encode(raw).decode()}",
            sha=hashlib.sha256(raw).hexdigest(),
            width=img.width,
            height=img.height,
        )


@dataclass
class LLMResponse:
    text: str
    model: str
    cost_usd: float
    latency_s: float
    cached: bool
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageMeter:
    """Accumulates spend; a run can enforce a hard budget."""

    budget_usd: float | None = None
    spent_usd: float = 0.0
    calls: int = 0
    cached_calls: int = 0

    def add(self, response: LLMResponse) -> None:
        self.calls += 1
        if response.cached:
            self.cached_calls += 1
        else:
            self.spent_usd += response.cost_usd

    def check(self) -> None:
        if self.budget_usd is not None and self.spent_usd >= self.budget_usd:
            raise LLMError(f"budget of ${self.budget_usd:.2f} exhausted (spent ${self.spent_usd:.4f})")


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        cache: ResponseCache | None = None,
        mode: CacheMode = CacheMode.RECORD_MISSING,
        concurrency: int = 8,
        timeout_s: float = 120.0,
        meter: UsageMeter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        load_dotenv()
        self._key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.cache = cache
        self.mode = mode
        self.meter = meter or UsageMeter()
        self._sem = asyncio.Semaphore(concurrency)
        self._http = httpx.AsyncClient(timeout=timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def complete(
        self,
        model: str,
        prompt: str,
        *,
        images: list[ImagePart] | None = None,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        prompt_version: str = "",
        fallback_models: list[str] | None = None,
        variant: int = 0,  # distinct cache entries for repeated sampling of the same prompt
        json_schema: dict[str, Any] | None = None,  # structured output, for models that support it
    ) -> LLMResponse:
        images = images or []
        key = cache_key(
            {
                "model": model,
                "fallback": fallback_models or [],
                "system": system,
                "prompt": prompt,
                "prompt_version": prompt_version,
                "images": [i.sha for i in images],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "variant": variant,
                "json_schema": json_schema,
            }
        )
        if self.cache and self.mode is not CacheMode.LIVE:
            hit = self.cache.get(key)
            if hit is not None:
                body, cost, latency = hit
                response = self._parse(body, cost, latency, cached=True)
                self.meter.add(response)
                return response
            if self.mode is CacheMode.REPLAY:
                raise CacheMiss(f"no cached response for {model} ({prompt_version})")

        self.meter.check()
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": i.data_url}} for i in images]
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": content})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        if fallback_models:
            payload["models"] = [model, *fallback_models]
        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": True, "schema": json_schema},
            }
            payload["provider"] = {"require_parameters": True}

        body, latency = await self._post(payload)
        cost = float(body.get("usage", {}).get("cost") or 0.0)
        if self.cache:
            self.cache.put(key, model, body, cost, latency)
        response = self._parse(body, cost, latency, cached=False)
        self.meter.add(response)
        return response

    async def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        if not self._key:
            raise LLMError("OPENROUTER_API_KEY is not set (put it into .env)")
        headers = {
            "Authorization": f"Bearer {self._key}",
            "HTTP-Referer": "https://github.com/menubench/menubench",
            "X-Title": "MenuBench",
        }
        delay = 2.0
        last: str = ""
        attempts = 7
        for attempt in range(attempts):
            wait = delay
            async with self._sem:
                started = time.perf_counter()
                try:
                    r = await self._http.post(API_URL, json=payload, headers=headers)
                except httpx.TransportError as exc:
                    last = f"transport: {exc!r}"
                else:
                    latency = time.perf_counter() - started
                    if r.status_code == 200:
                        body: dict[str, Any] = r.json()
                        if "error" in body:
                            last = f"provider error: {body['error']}"
                        elif body.get("choices"):
                            return body, latency
                        else:
                            last = "empty choices"
                    elif r.status_code in (408, 429) or r.status_code >= 500:
                        last = f"HTTP {r.status_code}: {r.text[:300]}"
                        retry_after = r.headers.get("retry-after", "")
                        if retry_after.replace(".", "", 1).isdigit():
                            wait = max(wait, float(retry_after))
                    else:
                        raise LLMError(f"HTTP {r.status_code}: {r.text[:500]}")
            if attempt < attempts - 1:
                # Jitter spreads retries of many concurrent calls hitting the same upstream limit.
                await asyncio.sleep(wait * (0.75 + random.random() / 2))
                delay = min(delay * 2, 60.0)
        raise LLMError(f"giving up after retries: {last}")

    @staticmethod
    def _parse(body: dict[str, Any], cost: float, latency: float, *, cached: bool) -> LLMResponse:
        message = body["choices"][0].get("message") or {}
        text = message.get("content") or ""
        if isinstance(text, list):  # some providers return content parts
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        return LLMResponse(
            text=str(text),
            model=str(body.get("model", "")),
            cost_usd=cost,
            latency_s=latency,
            cached=cached,
            usage=dict(body.get("usage") or {}),
        )
