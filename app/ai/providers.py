"""Registry of free AI providers.

All providers speak the OpenAI-compatible protocol (`/chat/completions`,
`/models`), so a single HTTP client serves them all. Model names are not
hard-coded: on first use the model list is fetched from the API
and ranked by `rank`, so a provider renaming its models
does not break the app.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Models that are definitely not chat models (audio, embeddings, image generation…)
_NON_CHAT = re.compile(
    r"(embed|whisper|tts|audio|transcri|speech|guard|moderat|imagen|veo|"
    r"image-generation|-image|live|aqa|learnlm|ocr|rerank|codestral|devstral|"
    r"computer-use|robotics|native-audio|safety|prompt-guard)",
    re.IGNORECASE,
)


def is_chat_model(model_id: str) -> bool:
    """Whether the model is usable for chat (not embeddings, audio, image generation…)."""
    return not _NON_CHAT.search(model_id)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    vision: bool


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    base_url: str
    key_url: str
    key_hint: str
    description_key: str
    # Returns a priority (lower is better) or None if the model is unsuitable.
    rank: Callable[[str], float | None]
    # Guesses image support from the id when the API does not say explicitly.
    vision_guess: Callable[[str], bool]
    # Fallback models in case `/models` is unavailable.
    fallback_models: tuple[ModelInfo, ...]
    extra_headers: dict[str, str] = field(default_factory=dict)
    max_models: int = 3


def _version(model_id: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", model_id)
    return float(m.group(1)) if m else 0.0


def _preview_penalty(model_id: str) -> float:
    return 0.5 if re.search(r"(preview|exp|experimental)", model_id) else 0.0


# ---------------------------------------------------------------- Gemini ---
# Models proven on the free tier — fast and stable. Newer
# models come later in the chain (on the free tier they are often
# overloaded and take 40+ seconds to answer).
_GEMINI_PROVEN = ("gemini-2.5-flash", "gemini-2.5-flash-lite")


def _gemini_rank(mid: str) -> float | None:
    if _NON_CHAT.search(mid) or not mid.startswith("gemini-"):
        return None
    if mid in _GEMINI_PROVEN:
        return float(_GEMINI_PROVEN.index(mid)) - 100
    if "flash-lite" in mid:
        tier = 20.0
    elif "flash" in mid:
        tier = 10.0
    else:
        return None  # pro models have almost no free-tier quota
    # Newer version = higher priority; preview slightly below stable.
    return tier - _version(mid) + _preview_penalty(mid)


# ------------------------------------------------------------------ Groq ---
_GROQ_PREFS = (
    "llama-4-maverick", "gpt-oss-120b", "llama-4-scout", "kimi-k2",
    "llama-3.3-70b", "qwen", "gpt-oss-20b", "llama-3.1-8b",
)


def _prefs_rank(prefs: tuple[str, ...]) -> Callable[[str], float | None]:
    def rank(mid: str) -> float | None:
        if _NON_CHAT.search(mid):
            return None
        low = mid.lower()
        for i, p in enumerate(prefs):
            if p in low:
                return i + _preview_penalty(low)
        return None

    return rank


def _groq_vision(mid: str) -> bool:
    low = mid.lower()
    return any(t in low for t in ("llama-4", "vision", "-vl"))


# ------------------------------------------------------------ OpenRouter ---
def _openrouter_rank(mid: str) -> float | None:
    if mid == "openrouter/free":
        return 50.0  # universal router over free models — as a fallback
    if not mid.endswith(":free") or _NON_CHAT.search(mid):
        return None
    low = mid.lower()
    prefs = ("gemini", "llama-4", "qwen3", "deepseek", "gpt-oss", "mistral", "nemotron", "gemma")
    for i, p in enumerate(prefs):
        if p in low:
            return float(i)
    return 30.0


def _openrouter_vision(mid: str) -> bool:
    low = mid.lower()
    return mid == "openrouter/free" or any(
        t in low for t in ("vl", "vision", "gemini", "llama-4", "gemma-3", "pixtral", "mistral-small")
    )


# --------------------------------------------------------------- Mistral ---
_MISTRAL_PREFS = ("mistral-medium-latest", "mistral-small-latest", "pixtral-large-latest", "mistral-large-latest")


def _mistral_vision(mid: str) -> bool:
    low = mid.lower()
    return any(t in low for t in ("pixtral", "mistral-medium", "mistral-small", "mistral-large"))


# -------------------------------------------------------------- Cerebras ---
_CEREBRAS_PREFS = ("gpt-oss-120b", "qwen-3", "llama-3.3-70b", "llama-4", "llama3.1-8b")


PROVIDERS: dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (
        ProviderSpec(
            id="gemini",
            name="Google Gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            key_url="https://aistudio.google.com/app/apikey",
            key_hint="AIza…",
            description_key="providers.desc.gemini",
            rank=_gemini_rank,
            vision_guess=lambda _: True,
            fallback_models=(
                ModelInfo("gemini-2.5-flash", True),
                ModelInfo("gemini-2.5-flash-lite", True),
            ),
        ),
        ProviderSpec(
            id="groq",
            name="Groq",
            base_url="https://api.groq.com/openai/v1",
            key_url="https://console.groq.com/keys",
            key_hint="gsk_…",
            description_key="providers.desc.groq",
            rank=_prefs_rank(_GROQ_PREFS),
            vision_guess=_groq_vision,
            fallback_models=(
                ModelInfo("meta-llama/llama-4-scout-17b-16e-instruct", True),
                ModelInfo("openai/gpt-oss-120b", False),
                ModelInfo("llama-3.3-70b-versatile", False),
            ),
        ),
        ProviderSpec(
            id="openrouter",
            name="OpenRouter (free)",
            base_url="https://openrouter.ai/api/v1",
            key_url="https://openrouter.ai/settings/keys",
            key_hint="sk-or-…",
            description_key="providers.desc.openrouter",
            rank=_openrouter_rank,
            vision_guess=_openrouter_vision,
            fallback_models=(ModelInfo("openrouter/free", True),),
            extra_headers={"X-Title": "TestHelper"},
        ),
        ProviderSpec(
            id="mistral",
            name="Mistral AI",
            base_url="https://api.mistral.ai/v1",
            key_url="https://console.mistral.ai/api-keys",
            key_hint="…",
            description_key="providers.desc.mistral",
            rank=_prefs_rank(_MISTRAL_PREFS),
            vision_guess=_mistral_vision,
            fallback_models=(
                ModelInfo("mistral-medium-latest", True),
                ModelInfo("mistral-small-latest", True),
            ),
            max_models=2,
        ),
        ProviderSpec(
            id="cerebras",
            name="Cerebras",
            base_url="https://api.cerebras.ai/v1",
            key_url="https://cloud.cerebras.ai/platform",
            key_hint="csk-…",
            description_key="providers.desc.cerebras",
            rank=_prefs_rank(_CEREBRAS_PREFS),
            vision_guess=lambda _: False,
            fallback_models=(
                ModelInfo("gpt-oss-120b", False),
                ModelInfo("llama-3.3-70b", False),
            ),
            max_models=2,
        ),
    )
}

DEFAULT_ORDER: tuple[str, ...] = tuple(PROVIDERS)

CUSTOM_PREFIX = "custom-"


def is_custom(pid: str) -> bool:
    return pid.startswith(CUSTOM_PREFIX)


# ------------------------------------------------------- custom providers ---
# Any OpenAI-compatible API: the user sets the URL, key and models.
# Presets only fill in the URL; model names and keys are up to the user.
@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    base_url: str
    needs_key: bool = True
    vision: bool = True


PRESETS: tuple[Preset, ...] = (
    Preset("openai", "OpenAI", "https://api.openai.com/v1"),
    Preset("deepseek", "DeepSeek", "https://api.deepseek.com/v1", vision=False),
    Preset("xai", "xAI (Grok)", "https://api.x.ai/v1"),
    Preset("together", "Together AI", "https://api.together.xyz/v1"),
    Preset("ollama", "Ollama (local)", "http://localhost:11434/v1", needs_key=False),
    Preset("lmstudio", "LM Studio (local)", "http://localhost:1234/v1", needs_key=False),
)


def _keep_order(mid: str) -> float | None:
    # For a custom provider we don't guess the "best" models: take chat models in API order.
    return None if _NON_CHAT.search(mid) else 0.0


def custom_spec(pid: str, name: str, base_url: str, vision: bool) -> ProviderSpec:
    """ProviderSpec for a user-added provider."""
    return ProviderSpec(
        id=pid,
        name=name,
        base_url=base_url.rstrip("/"),
        key_url="",
        key_hint="sk-…",
        description_key="",
        rank=_keep_order,
        vision_guess=lambda _mid: vision,
        fallback_models=(),
        max_models=3,
    )
