"""Persistent history of scan results."""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict
from pathlib import Path

from app.core.models import ScanResult

log = logging.getLogger(__name__)


class HistoryStore:
    def __init__(self, path: Path, limit: int = 300) -> None:
        self.path = path
        self.limit = limit
        self._lock = threading.Lock()
        self._items: list[ScanResult] = self._load()

    def _load(self) -> list[ScanResult]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            fields = ScanResult.__dataclass_fields__
            return [ScanResult(**{k: v for k, v in item.items() if k in fields}) for item in raw]
        except (OSError, ValueError, TypeError) as exc:
            log.warning("History is unreadable, starting fresh: %s", exc)
            return []

    def _persist(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps([asdict(i) for i in self._items], ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.error("Failed to save history: %s", exc)

    def add(self, item: ScanResult) -> None:
        with self._lock:
            self._items.insert(0, item)
            del self._items[self.limit:]
            self._persist()

    def items(self) -> list[ScanResult]:
        with self._lock:
            return list(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._persist()
