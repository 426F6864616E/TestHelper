"""Minimal OpenAI-compatible HTTP client with normalized errors."""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from enum import Enum

import httpx

from app.ai.providers import ModelInfo, ProviderSpec

log = logging.getLogger(__name__)

# Short read timeout: switching to another model fast beats waiting.
_TIMEOUT = httpx.Timeout(connect=8.0, read=35.0, write=20.0, pool=8.0)


class ErrorKind(str, Enum):
    RATE_LIMIT = "rate_limit"     # 429 — per-minute limit
    QUOTA = "quota"               # daily quota exhausted
    AUTH = "auth"                 # invalid key
    BAD_MODEL = "bad_model"       # model missing / request not supported
    NO_VISION = "no_vision"       # model does not accept images
    SERVER = "server"             # 5xx, overloaded
    NETWORK = "network"           # timeout, DNS, connection drop
    OTHER = "other"


class ProviderError(Exception):
    def __init__(self, kind: ErrorKind, message: str, status: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after

    def __str__(self) -> str:
        code = f"HTTP {self.status}: " if self.status else ""
        return f"{code}{self.args[0]}"[:300]


@dataclass(frozen=True)
class ChatMessage:
    system: str
    user_text: str
    image_jpeg: bytes | None = None


_RETRY_RE = re.compile(r"retry (?:in|after)\s*([\d.]+)\s*(ms|s)?", re.IGNORECASE)
_DAILY_RE = re.compile(r"(per ?day|daily|PerDay|RPD|tokens per day|free-models-per-day)", re.IGNORECASE)


def _classify(resp: httpx.Response) -> ProviderError:
    status = resp.status_code
    try:
        payload = resp.json()
        err = payload.get("error", payload) if isinstance(payload, dict) else payload
        if isinstance(err, list) and err:
            err = err[0].get("error", err[0]) if isinstance(err[0], dict) else err[0]
        message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
    except ValueError:
        message = resp.text[:300] or resp.reason_phrase

    retry_after: float | None = None
    header = resp.headers.get("retry-after")
    if header:
        try:
            retry_after = float(header)
        except ValueError:
            pass
    if retry_after is None:
        m = _RETRY_RE.search(message)
        if m:
            value = float(m.group(1))
            retry_after = value / 1000 if m.group(2) == "ms" else value

    low = message.lower()
    if status in (401, 403) and "region" not in low:
        return ProviderError(ErrorKind.AUTH, message, status)
    if status == 429 or "resource_exhausted" in low or "quota" in low:
        kind = ErrorKind.QUOTA if _DAILY_RE.search(message) else ErrorKind.RATE_LIMIT
        return ProviderError(kind, message, status, retry_after)
    if status in (400, 404, 422):
        if any(t in low for t in ("image", "vision", "multimodal", "content type", "image_url")):
            return ProviderError(ErrorKind.NO_VISION, message, status)
        if any(t in low for t in ("model", "not found", "does not exist", "decommission")):
            return ProviderError(ErrorKind.BAD_MODEL, message, status)
        if "api key" in low or "api_key" in low:
            return ProviderError(ErrorKind.AUTH, message, status)
        return ProviderError(ErrorKind.OTHER, message, status)
    if status >= 500:
        return ProviderError(ErrorKind.SERVER, message, status, retry_after)
    return ProviderError(ErrorKind.OTHER, message, status)


class OpenAICompatClient:
    """Thread-safe client; one instance for the whole app."""

    def __init__(self) -> None:
        self._http = httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                                  headers={"User-Agent": "TestHelper/1"})

    def close(self) -> None:
        self._http.close()

    @staticmethod
    def _headers(spec: ProviderSpec, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", **spec.extra_headers}

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            resp = self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError(ErrorKind.NETWORK, f"Timeout: {exc}", retry_after=600.0) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ErrorKind.NETWORK, f"Network error: {exc}") from exc
        if resp.status_code >= 400:
            raise _classify(resp)
        return resp

    # -------------------------------------------------------------- API ---
    def list_models(self, spec: ProviderSpec, key: str) -> list[ModelInfo]:
        resp = self._request("GET", f"{spec.base_url}/models", headers=self._headers(spec, key))
        data = resp.json().get("data", [])
        models: list[ModelInfo] = []
        for item in data:
            mid = str(item.get("id", "")).removeprefix("models/")
            if not mid:
                continue
            vision = spec.vision_guess(mid)
            arch = item.get("architecture") or {}
            caps = item.get("capabilities") or {}
            if isinstance(arch.get("input_modalities"), list):        # OpenRouter
                vision = "image" in arch["input_modalities"]
            elif isinstance(caps, dict) and "vision" in caps:          # Mistral
                vision = bool(caps["vision"])
                if caps.get("completion_chat") is False:
                    continue
            models.append(ModelInfo(mid, vision))
        return models

    def chat(self, spec: ProviderSpec, key: str, model: str, msg: ChatMessage,
             max_tokens: int = 2048) -> str:
        user_content: list[dict] | str
        if msg.image_jpeg:
            b64 = base64.b64encode(msg.image_jpeg).decode("ascii")
            user_content = [
                {"type": "text", "text": msg.user_text},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]
        else:
            user_content = msg.user_text

        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": msg.system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        resp = self._request("POST", f"{spec.base_url}/chat/completions",
                             headers=self._headers(spec, key), json=body)
        try:
            choice = resp.json()["choices"][0]
            content = choice["message"].get("content") or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(ErrorKind.SERVER, f"Malformed response: {resp.text[:200]}") from exc
        if isinstance(content, list):  # some providers return a list of parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not content.strip():
            raise ProviderError(ErrorKind.SERVER, "Empty response from model")
        return content.strip()
