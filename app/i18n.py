"""Localization with dotted keys: t("scan.title"), parameter substitution and fallback."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


class I18n:
    FALLBACK = "en"

    def __init__(self, locales_dir: Path, language: str) -> None:
        self._tables: dict[str, dict[str, Any]] = {}
        for file in locales_dir.glob("*.json"):
            try:
                self._tables[file.stem] = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.error("Locale %s is broken: %s", file.name, exc)
        self.language = language
        self._listeners: list[Callable[[], None]] = []

    @property
    def available(self) -> list[str]:
        return sorted(self._tables)

    def set_language(self, language: str) -> None:
        if language != self.language:
            self.language = language
            for cb in list(self._listeners):
                cb()

    def on_change(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _lookup(self, lang: str, key: str) -> Any:
        node: Any = self._tables.get(lang, {})
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def raw(self, key: str) -> Any:
        """Returns the raw node (list/dict) for structured content."""
        value = self._lookup(self.language, key)
        return value if value is not None else self._lookup(self.FALLBACK, key)

    def error_text(self, error_key: str, saved_text: str) -> str:
        """Error text in the current language.

        New entries have an error_key. For old ones (stored as plain text) we find the key
        by comparing the text with every language's errors section.
        """
        if error_key:
            return self.t(error_key)
        for table in self._tables.values():
            key = self._find_key(table.get("errors", {}), saved_text, "errors")
            if key:
                return self.t(key)
        return saved_text

    def _find_key(self, node: Any, text: str, path: str) -> str | None:
        if isinstance(node, dict):
            for k, v in node.items():
                found = self._find_key(v, text, f"{path}.{k}")
                if found:
                    return found
        elif node == text:
            return path
        return None

    def t(self, key: str, **params: Any) -> str:
        value = self._lookup(self.language, key)
        if value is None:
            value = self._lookup(self.FALLBACK, key)
        if value is None:
            return key
        if isinstance(value, list):
            value = "\n".join(value)
        text = str(value)
        if params:
            try:
                text = text.format(**params)
            except (KeyError, IndexError, ValueError):
                pass
        return text
