"""Domain data models."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ScanResult:
    ok: bool
    answer: str = ""
    answer_text: str = ""
    question: str = ""
    explanation: str = ""
    confidence: int = 0
    provider: str = ""
    model: str = ""
    elapsed: float = 0.0
    page_title: str = ""
    page_url: str = ""
    mode: str = ""
    error: str = ""
    error_key: str = ""  # i18n error key: the text is translated when shown
    error_code: str = ""  # no_keys | browser | ai | no_question | empty_page
    timestamp: float = field(default_factory=time.time)

    @property
    def short(self) -> str:
        """One-line representation for the tray / clipboard."""
        if not self.ok:
            return self.error
        tail = f" — {self.answer_text}" if self.answer_text and self.answer_text != self.answer else ""
        return f"{self.answer}{tail}"
