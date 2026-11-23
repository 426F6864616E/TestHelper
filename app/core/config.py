"""Typed settings with atomic saving and migration from the old format."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.ai.providers import CUSTOM_PREFIX, DEFAULT_ORDER, PROVIDERS, ProviderSpec, custom_spec, is_custom
from app.ai.router import ProviderPlan

log = logging.getLogger(__name__)

SCAN_MODES = ("auto", "text", "vision")
THEMES = ("dark", "light", "system")
LANGUAGES = ("ua", "en", "ru")


@dataclass
class ProviderSettings:
    enabled: bool = True
    keys: list[str] = field(default_factory=list)
    # Models chosen by the user, in priority order. Empty means automatic.
    models: list[str] = field(default_factory=list)


@dataclass
class CustomProvider:
    """A user-added provider: any OpenAI-compatible API."""
    name: str
    base_url: str
    vision: bool = True


@dataclass
class Settings:
    language: str = "ua"
    theme: str = "dark"
    scan_mode: str = "auto"
    provider_order: list[str] = field(default_factory=lambda: list(DEFAULT_ORDER))
    providers: dict[str, ProviderSettings] = field(
        default_factory=lambda: {pid: ProviderSettings() for pid in DEFAULT_ORDER}
    )
    custom_providers: dict[str, CustomProvider] = field(default_factory=dict)
    browser_port: int = 9222
    browser_path: str = ""
    auto_launch_browser: bool = True
    close_to_tray: bool = True
    always_on_top: bool = False
    notifications: bool = True
    show_explanation: bool = True


class ConfigManager:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.settings = self._load()

    # ---------------------------------------------------------------- I/O ---
    def _load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("Config is unreadable, using defaults: %s", exc)
            return Settings()
        settings = self._from_dict(raw)
        if "api_keys" in raw:  # v1.x format → rewrite in the new one right away
            log.info("Migrated legacy config (v1.x)")
            self._write(settings)
        return settings

    @staticmethod
    def _from_dict(raw: dict[str, Any]) -> Settings:
        s = Settings()
        for name in ("language", "theme", "scan_mode", "browser_path"):
            if isinstance(raw.get(name), str):
                setattr(s, name, raw[name])
        for name in ("auto_launch_browser", "close_to_tray", "always_on_top", "notifications", "show_explanation"):
            if isinstance(raw.get(name), bool):
                setattr(s, name, raw[name])
        if isinstance(raw.get("browser_port"), int):
            s.browser_port = raw["browser_port"]

        custom = raw.get("custom_providers")
        if isinstance(custom, dict):
            for pid, data in custom.items():
                if is_custom(pid) and isinstance(data, dict) and data.get("name") and data.get("base_url"):
                    s.custom_providers[pid] = CustomProvider(
                        name=str(data["name"])[:40], base_url=str(data["base_url"]).strip(),
                        vision=bool(data.get("vision", True)),
                    )

        providers = raw.get("providers")
        if isinstance(providers, dict):
            for pid, data in providers.items():
                if (pid in PROVIDERS or pid in s.custom_providers) and isinstance(data, dict):
                    models = [m.strip() for m in data.get("models", []) if isinstance(m, str) and m.strip()]
                    legacy = str(data.get("preferred_model", "")).strip()  # format from before model lists existed
                    if legacy and legacy not in models:
                        models.insert(0, legacy)
                    s.providers[pid] = ProviderSettings(
                        enabled=bool(data.get("enabled", True)),
                        keys=[k.strip() for k in data.get("keys", []) if isinstance(k, str) and k.strip()],
                        models=models,
                    )
        for pid in s.custom_providers:
            s.providers.setdefault(pid, ProviderSettings())
        valid = set(PROVIDERS) | set(s.custom_providers)
        order = raw.get("provider_order")
        known = [p for p in order if p in valid] if isinstance(order, list) else []
        s.provider_order = known + [p for p in list(DEFAULT_ORDER) + list(s.custom_providers) if p not in known]

        # --- v1.x migration: {"api_keys": [...], "provider": "Gemini", "vision_mode": bool}
        legacy_keys = raw.get("api_keys")
        if isinstance(legacy_keys, list):
            target = "gemini" if str(raw.get("provider", "Gemini")).lower() == "gemini" else None
            if target:
                merged = s.providers[target].keys
                for k in legacy_keys:
                    if isinstance(k, str) and k.strip() and k.strip() not in merged:
                        merged.append(k.strip())
            if raw.get("vision_mode") is True and "scan_mode" not in raw:
                s.scan_mode = "auto"

        if s.language not in LANGUAGES:
            s.language = "ua"
        if s.theme not in THEMES:
            s.theme = "dark"
        if s.scan_mode not in SCAN_MODES:
            s.scan_mode = "auto"
        return s

    def _write(self, settings: Settings) -> None:
        data = asdict(settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.error("Failed to save config: %s", exc)
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def save(self) -> None:
        with self._lock:
            self._write(self.settings)

    def update(self, **changes: Any) -> None:
        with self._lock:
            for name, value in changes.items():
                if not hasattr(self.settings, name):
                    raise AttributeError(name)
                setattr(self.settings, name, value)
            self._write(self.settings)

    # ---------------------------------------------------------- providers ---
    def provider(self, pid: str) -> ProviderSettings:
        with self._lock:
            return self.settings.providers.setdefault(pid, ProviderSettings())

    def add_key(self, pid: str, key: str) -> bool:
        key = key.strip()
        with self._lock:
            ps = self.provider(pid)
            if not key or key in ps.keys:
                return False
            ps.keys.append(key)
            self.save()
            return True

    def remove_key(self, pid: str, key: str) -> None:
        with self._lock:
            ps = self.provider(pid)
            if key in ps.keys:
                ps.keys.remove(key)
                self.save()

    def set_provider_enabled(self, pid: str, enabled: bool) -> None:
        with self._lock:
            self.provider(pid).enabled = enabled
            self.save()

    def move_provider(self, pid: str, delta: int) -> None:
        with self._lock:
            order = self.settings.provider_order
            i = order.index(pid)
            j = max(0, min(len(order) - 1, i + delta))
            order[i], order[j] = order[j], order[i]
            self.save()

    def spec(self, pid: str) -> ProviderSpec | None:
        """Provider description: built-in or user-added."""
        if pid in PROVIDERS:
            return PROVIDERS[pid]
        with self._lock:
            cp = self.settings.custom_providers.get(pid)
        return custom_spec(pid, cp.name, cp.base_url, cp.vision) if cp else None

    def plan_keys(self, pid: str) -> tuple[str, ...]:
        """Keys for requests. A keyless custom provider (Ollama, LM Studio) works with an empty one."""
        ps = self.settings.providers.get(pid)
        if not ps:
            return ()
        if ps.keys:
            return tuple(ps.keys)
        return ("",) if pid in self.settings.custom_providers else ()

    def provider_plans(self) -> list[ProviderPlan]:
        with self._lock:
            plans = []
            for pid in self.settings.provider_order:
                ps = self.settings.providers.get(pid)
                spec = self.spec(pid)
                keys = self.plan_keys(pid)
                if ps and ps.enabled and spec and keys:
                    plans.append(ProviderPlan(spec, keys, tuple(ps.models), only_listed=is_custom(pid)))
            return plans

    def total_keys(self) -> int:
        """How many access points are ready: keys + keyless custom providers."""
        with self._lock:
            return sum(len(self.plan_keys(pid)) for pid, p in self.settings.providers.items()
                       if p.enabled and (pid in PROVIDERS or pid in self.settings.custom_providers))

    # -------------------------------------------------------------- models ---
    def add_model(self, pid: str, model: str) -> bool:
        model = model.strip()
        with self._lock:
            ps = self.provider(pid)
            if not model or model in ps.models:
                return False
            ps.models.append(model)
            self.save()
            return True

    def remove_model(self, pid: str, model: str) -> None:
        with self._lock:
            ps = self.provider(pid)
            if model in ps.models:
                ps.models.remove(model)
                self.save()

    # ---------------------------------------------------- custom providers ---
    def add_custom_provider(self, name: str, base_url: str, vision: bool, key: str = "",
                            models: list[str] | None = None) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "api"
        pid = f"{CUSTOM_PREFIX}{slug}-{uuid.uuid4().hex[:6]}"
        with self._lock:
            self.settings.custom_providers[pid] = CustomProvider(name.strip()[:40], base_url.strip().rstrip("/"), vision)
            self.settings.providers[pid] = ProviderSettings(
                keys=[key.strip()] if key.strip() else [],
                models=[m.strip() for m in models or [] if m.strip()],
            )
            self.settings.provider_order.append(pid)
            self.save()
        return pid

    def remove_custom_provider(self, pid: str) -> None:
        with self._lock:
            self.settings.custom_providers.pop(pid, None)
            self.settings.providers.pop(pid, None)
            if pid in self.settings.provider_order:
                self.settings.provider_order.remove(pid)
            self.save()
