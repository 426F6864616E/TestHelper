"""Request router with automatic failover.

Strategy: providers are tried in the user's priority order,
within a provider from the best model to the fallback, and for each
model all keys in turn (round-robin). Each failure puts only the
combination that actually failed on cooldown:

* 429 / per-minute limit → pause the (key, model) pair for Retry-After;
* daily quota            → the (key, model) pair rests for an hour;
* invalid key            → the key is disabled until restart;
* model gone             → the model is dropped from the chain;
* 5xx / network          → short pause for the model.

So one exhausted key never stops the app — the request
quietly moves on to the next available combination.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from app.ai.client import ChatMessage, ErrorKind, OpenAICompatClient, ProviderError
from app.ai.providers import ModelInfo, ProviderSpec, is_chat_model

log = logging.getLogger(__name__)

_MODELS_TTL = 6 * 3600
_MAX_ATTEMPTS = 16
_DEADLINE = 100.0

_COOLDOWNS = {
    ErrorKind.RATE_LIMIT: 30.0,
    ErrorKind.QUOTA: 3600.0,
    ErrorKind.SERVER: 30.0,
    ErrorKind.NETWORK: 15.0,
    ErrorKind.OTHER: 60.0,
}


@dataclass(frozen=True)
class ProviderPlan:
    """Snapshot of a provider's settings at request time.

    models — the user's chosen models (in priority order). For built-in
    providers, auto-picked models follow as fallbacks; for custom ones
    (only_listed=True) only the listed ones are used, and if the list is empty —
    the chat models from the provider's API.
    """
    spec: ProviderSpec
    keys: tuple[str, ...]
    models: tuple[str, ...] = ()
    only_listed: bool = False

    @property
    def id(self) -> str:
        return self.spec.id


@dataclass
class AIResult:
    text: str
    provider_id: str
    provider_name: str
    model: str
    elapsed: float
    attempts: int


@dataclass
class ProviderStats:
    ok: int = 0
    failed: int = 0
    last_model: str = ""
    last_error: str = ""
    last_used: float = 0.0
    models: list[str] = field(default_factory=list)
    invalid_keys: int = 0


class NoProvidersError(Exception):
    """No keys are configured."""


class AllProvidersFailedError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors[-4:]) if errors else "no available providers")
        self.errors = errors


def _fp(key: str) -> str:
    return f"…{key[-6:]}" if len(key) > 6 else key


class AIRouter:
    def __init__(self, plans: Callable[[], list[ProviderPlan]]) -> None:
        self._plans = plans
        self._client = OpenAICompatClient()
        self._lock = threading.RLock()
        self._cooldown: dict[tuple[str, str, str], float] = {}     # (pid, key, model) -> until
        self._model_down: dict[tuple[str, str], float] = {}         # (pid, model) -> until
        self._invalid_keys: set[tuple[str, str]] = set()
        self._dead_models: set[tuple[str, str]] = set()
        self._no_vision: set[tuple[str, str]] = set()
        self._models_cache: dict[str, tuple[float, list[ModelInfo]]] = {}
        self._all_models: dict[str, list[ModelInfo]] = {}  # all chat models from the API — for picking in the UI
        self._rr: dict[tuple[str, str], int] = defaultdict(int)
        self.stats: dict[str, ProviderStats] = defaultdict(ProviderStats)

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------ helpers ---
    def _usable_keys(self, pid: str, keys: tuple[str, ...]) -> list[str]:
        return [k for k in keys if (pid, k) not in self._invalid_keys]

    def _models_for(self, spec: ProviderSpec, plan: ProviderPlan, keys: list[str]) -> list[ModelInfo]:
        if plan.models and plan.only_listed:
            # Custom provider with a model list — fetch nothing, use it as is.
            return self._apply_choice(spec, plan, [])
        with self._lock:
            cached = self._models_cache.get(spec.id)
        if cached and time.time() - cached[0] < _MODELS_TTL:
            ranked = cached[1]
        else:
            ranked = self._discover(spec, keys)
            with self._lock:
                self._models_cache[spec.id] = (time.time(), ranked)
                self.stats[spec.id].models = [m.id for m in ranked]

        return self._apply_choice(spec, plan, ranked)

    def _apply_choice(self, spec: ProviderSpec, plan: ProviderPlan, ranked: list[ModelInfo]) -> list[ModelInfo]:
        """Puts the user's chosen models first (or only them, for custom providers)."""
        if plan.models:
            with self._lock:
                known = {m.id: m for m in self._all_models.get(spec.id, [])}
            known.update({m.id: m for m in ranked})
            chosen = [known.get(mid) or ModelInfo(mid, spec.vision_guess(mid)) for mid in plan.models]
            ranked = chosen if plan.only_listed else chosen + [m for m in ranked if m.id not in plan.models]
        return [m for m in ranked if (spec.id, m.id) not in self._dead_models]

    def _discover(self, spec: ProviderSpec, keys: list[str]) -> list[ModelInfo]:
        for key in keys[:2]:
            try:
                available = self._client.list_models(spec, key)
            except ProviderError as exc:
                if exc.kind is ErrorKind.AUTH:
                    self._mark_invalid(spec.id, key)
                log.warning("Model discovery failed for %s: %s", spec.id, exc)
                continue
            self._remember_models(spec, available)
            scored = [(spec.rank(m.id), m) for m in available]
            ranked = [m for score, m in sorted((s for s in scored if s[0] is not None),
                                               key=lambda s: s[0])]
            if ranked:
                chosen = ranked[: spec.max_models]
                # Make sure the chain has at least one vision model, if any exists.
                if not any(m.vision for m in chosen):
                    vision = next((m for m in ranked if m.vision), None)
                    if vision:
                        chosen.append(vision)
                log.info("%s models: %s", spec.id, ", ".join(m.id for m in chosen))
                return chosen
        log.info("%s: using built-in fallback models", spec.id)
        return list(spec.fallback_models)

    def _mark_invalid(self, pid: str, key: str) -> None:
        with self._lock:
            self._invalid_keys.add((pid, key))
            self.stats[pid].invalid_keys = sum(1 for p, _ in self._invalid_keys if p == pid)

    def _rotated(self, pid: str, model: str, keys: list[str]) -> list[str]:
        with self._lock:
            start = self._rr[(pid, model)] % len(keys)
            self._rr[(pid, model)] += 1
        return keys[start:] + keys[:start]

    def _apply_error(self, pid: str, key: str, model: str, exc: ProviderError) -> None:
        now = time.time()
        with self._lock:
            st = self.stats[pid]
            st.failed += 1
            st.last_error = str(exc)[:160]
            if exc.kind is ErrorKind.AUTH:
                self._invalid_keys.add((pid, key))
                st.invalid_keys = sum(1 for p, _ in self._invalid_keys if p == pid)
            elif exc.kind is ErrorKind.BAD_MODEL:
                self._dead_models.add((pid, model))
            elif exc.kind is ErrorKind.NO_VISION:
                self._no_vision.add((pid, model))
            elif exc.kind in (ErrorKind.SERVER, ErrorKind.NETWORK):
                self._model_down[(pid, model)] = now + (exc.retry_after or _COOLDOWNS[exc.kind])
            else:
                wait = _COOLDOWNS.get(exc.kind, 60.0)
                if exc.retry_after and exc.kind is ErrorKind.RATE_LIMIT:
                    wait = min(max(exc.retry_after, 2.0), 300.0)
                self._cooldown[(pid, key, model)] = now + wait

    def _available(self, pid: str, key: str, model: str) -> bool:
        now = time.time()
        return (self._cooldown.get((pid, key, model), 0) <= now
                and self._model_down.get((pid, model), 0) <= now)

    # ----------------------------------------------------------- public ---
    def has_keys(self) -> bool:
        return any(p.keys for p in self._plans())

    def complete(self, msg: ChatMessage, on_progress: Callable[[str], None] | None = None) -> AIResult:
        plans = [p for p in self._plans() if p.keys]
        if not plans:
            raise NoProvidersError()

        started = time.monotonic()
        errors: list[str] = []
        attempts = 0

        for plan in plans:
            spec = plan.spec
            keys = self._usable_keys(spec.id, plan.keys)
            if not keys:
                errors.append(f"{spec.name}: all keys invalid")
                continue
            models = self._models_for(spec, plan, keys)
            keys = self._usable_keys(spec.id, plan.keys)  # discovery may have found invalid ones

            for model in models:
                wants_image = msg.image_jpeg is not None
                for key in self._rotated(spec.id, model.id, keys):
                    model_vision = model.vision and (spec.id, model.id) not in self._no_vision
                    if wants_image and not model_vision and not msg.user_text.strip():
                        break  # the model can't see images and there is no text
                    request = msg if (model_vision or not wants_image) else ChatMessage(msg.system, msg.user_text)
                    if (spec.id, key) in self._invalid_keys or not self._available(spec.id, key, model.id):
                        continue
                    if attempts >= _MAX_ATTEMPTS or time.monotonic() - started > _DEADLINE:
                        raise AllProvidersFailedError(errors + ["attempt limit reached"])
                    attempts += 1
                    if on_progress:
                        on_progress(f"{spec.name} · {model.id}")
                    try:
                        text = self._client.chat(spec, key, model.id, request)
                    except ProviderError as exc:
                        log.warning("%s/%s key %s failed: %s [%s]", spec.id, model.id, _fp(key), exc, exc.kind.value)
                        errors.append(f"{spec.name}/{model.id}: {exc.kind.value}")
                        self._apply_error(spec.id, key, model.id, exc)
                        if exc.kind is ErrorKind.BAD_MODEL:
                            break  # next model
                        if exc.kind is ErrorKind.NO_VISION and request.image_jpeg and msg.user_text.strip():
                            # Retry with the same key, but without the image.
                            try:
                                text = self._client.chat(spec, key, model.id, ChatMessage(msg.system, msg.user_text))
                            except ProviderError as exc2:
                                self._apply_error(spec.id, key, model.id, exc2)
                                continue
                        else:
                            continue

                    elapsed = time.monotonic() - started
                    with self._lock:
                        st = self.stats[spec.id]
                        st.ok += 1
                        st.last_model = model.id
                        st.last_used = time.time()
                        st.last_error = ""
                    log.info("Answer from %s/%s in %.1fs (%d attempts)", spec.id, model.id, elapsed, attempts)
                    return AIResult(text, spec.id, spec.name, model.id, elapsed, attempts)

        raise AllProvidersFailedError(errors)

    def test_key(self, spec: ProviderSpec, key: str) -> tuple[bool, str]:
        """Checks a key without spending quota (only lists models)."""
        try:
            models = self._client.list_models(spec, key)
        except ProviderError as exc:
            return False, f"{exc.kind.value}: {str(exc)[:120]}"
        with self._lock:
            self._invalid_keys.discard((spec.id, key))
            self._models_cache.pop(spec.id, None)
        self._remember_models(spec, models)
        usable = sum(1 for m in models if spec.rank(m.id) is not None)
        return True, str(usable)

    def _remember_models(self, spec: ProviderSpec, models: list[ModelInfo]) -> None:
        # For picking, show all chat models, not just the ones the app considers "best".
        chat = [m for m in models if is_chat_model(m.id)]
        with self._lock:
            self._all_models[spec.id] = chat

    def available_models(self, spec: ProviderSpec, key: str | None) -> list[str]:
        """Provider models for the UI picker (from cache or the API). Empty when offline."""
        with self._lock:
            cached = self._all_models.get(spec.id)
        if cached is None and key is not None:
            try:
                models = self._client.list_models(spec, key)
            except ProviderError as exc:
                log.info("Cannot list models for %s: %s", spec.id, exc)
                return []
            self._remember_models(spec, models)
            with self._lock:
                cached = self._all_models.get(spec.id, [])
        return sorted({m.id for m in cached or []})

    def forget(self, pid: str) -> None:
        """Clears a provider's model cache (after changing models or deleting the provider)."""
        with self._lock:
            self._models_cache.pop(pid, None)
            self._all_models.pop(pid, None)
            self._dead_models = {(p, m) for p, m in self._dead_models if p != pid}

    def reset_state(self) -> None:
        with self._lock:
            self._cooldown.clear()
            self._model_down.clear()
            self._invalid_keys.clear()
            self._dead_models.clear()
            self._models_cache.clear()
