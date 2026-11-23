"""Scan orchestration: browser → prompt → AI → structured answer."""
from __future__ import annotations

import io
import json
import logging
import re
import threading
from typing import Callable

from PIL import Image

from app.ai import AIRouter, AllProvidersFailedError, ChatMessage, NoProvidersError
from app.browser import BrowserBridge, BrowserError
from app.core.config import ConfigManager
from app.core.models import ScanResult
from app.i18n import I18n

log = logging.getLogger(__name__)

_LANG_NAMES = {"ua": "Ukrainian", "en": "English", "ru": "Russian"}

_SYSTEM_PROMPT = """You are a meticulous subject-matter expert who solves test and quiz questions.
You receive the visible content of a web page (text and/or a screenshot). Steps:
1. Locate the CURRENT test question on the page (ignore navigation, menus, ads, timers).
2. Identify all answer options in their on-page order and numbering.
3. Solve the question carefully. For multi-select questions return every correct option.
4. Lines marked "[SELECTED BY USER]" only show what the user ticked — do not trust them.

Respond with ONLY a compact JSON object, no markdown, no code fences:
{{"question": "<question summarised in at most 12 words>",
  "answer": "<option number(s)/letter(s) as shown on the page, e.g. \\"2\\" or \\"1, 3\\" or \\"B\\"; for open questions the short answer itself>",
  "answer_text": "<the text of the chosen option(s), short>",
  "confidence": <integer 0-100>,
  "explanation": "<one or two sentences why, in {language}>"}}
If no test question is visible, respond {{"question": "", "answer": "", "answer_text": "", "confidence": 0, "explanation": "NO_QUESTION"}}."""


def _jpeg_downscale(data: bytes, max_side: int = 1600) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=82, optimize=True)
    return out.getvalue()


def parse_answer(raw: str) -> dict:
    """Extracts JSON from the model reply; tolerant of ``` fences and reasoning text."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    for match in reversed(list(re.finditer(r"\{.*?\}", cleaned, flags=re.DOTALL))):
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and "answer" in data:
                return data
        except ValueError:
            continue
    try:
        start, end = cleaned.index("{"), cleaned.rindex("}") + 1
        data = json.loads(cleaned[start:end])
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    # Fallback: the model answered in free text.
    m = re.search(r"(?:answer|відповідь|ответ)\s*[:\-]\s*(.+)", cleaned, flags=re.IGNORECASE)
    return {"answer": (m.group(1) if m else cleaned).strip()[:120], "confidence": 0, "explanation": ""}


class ScanService:
    def __init__(self, config: ConfigManager, browser: BrowserBridge, router: AIRouter, i18n: I18n) -> None:
        self.config = config
        self.browser = browser
        self.router = router
        self.i18n = i18n
        self._busy = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def scan(self, on_progress: Callable[[str], None] | None = None) -> ScanResult | None:
        """Returns None if a scan is already running."""
        if not self._busy.acquire(blocking=False):
            return None
        try:
            return self._scan(on_progress or (lambda _m: None))
        finally:
            self._busy.release()

    def _scan(self, progress: Callable[[str], None]) -> ScanResult:
        t = self.i18n.t
        s = self.config.settings
        mode = s.scan_mode

        if not self.router.has_keys():
            return ScanResult(ok=False, mode=mode, error=t("errors.no_keys"), error_key="errors.no_keys", error_code="no_keys")

        progress(t("progress.reading_page"))
        try:
            if not self.browser.is_running() and s.auto_launch_browser:
                progress(t("progress.launching_browser"))
                self.browser.launch()
            snap = self.browser.snapshot(
                with_text=mode in ("auto", "text"),
                with_screenshot=mode in ("auto", "vision"),
            )
        except BrowserError as exc:
            log.warning("Browser error: %s (%s)", exc.code, exc)
            return ScanResult(ok=False, mode=mode, error=t(f"errors.browser.{exc.code}"), error_key=f"errors.browser.{exc.code}", error_code="browser")

        if not snap.text.strip() and not snap.screenshot_jpeg:
            return ScanResult(ok=False, mode=mode, page_title=snap.title, page_url=snap.url,
                              error=t("errors.empty_page"), error_key="errors.empty_page", error_code="empty_page")

        image = _jpeg_downscale(snap.screenshot_jpeg) if snap.screenshot_jpeg else None
        user_text = f"Page title: {snap.title}\nURL: {snap.url}\n"
        if snap.text:
            user_text += f"\n--- PAGE TEXT ---\n{snap.text}\n--- END ---\n"
        if image:
            user_text += "\nA screenshot of the visible part of the page is attached."
        system = _SYSTEM_PROMPT.format(language=_LANG_NAMES.get(s.language, "English"))

        progress(t("progress.asking_ai"))
        try:
            result = self.router.complete(
                ChatMessage(system=system, user_text=user_text, image_jpeg=image),
                on_progress=lambda where: progress(t("progress.asking", where=where)),
            )
        except NoProvidersError:
            return ScanResult(ok=False, mode=mode, error=t("errors.no_keys"), error_key="errors.no_keys", error_code="no_keys")
        except AllProvidersFailedError as exc:
            log.error("All providers failed: %s", exc.errors)
            return ScanResult(ok=False, mode=mode, page_title=snap.title, page_url=snap.url,
                              error=t("errors.all_failed"), error_key="errors.all_failed", error_code="ai")

        data = parse_answer(result.text)
        explanation = str(data.get("explanation", "")).strip()
        if explanation == "NO_QUESTION" or not str(data.get("answer", "")).strip():
            return ScanResult(ok=False, mode=mode, page_title=snap.title, page_url=snap.url,
                              provider=result.provider_name, model=result.model, elapsed=result.elapsed,
                              error=t("errors.no_question"), error_key="errors.no_question", error_code="no_question")
        try:
            confidence = max(0, min(100, int(float(data.get("confidence", 0)))))
        except (TypeError, ValueError):
            confidence = 0

        return ScanResult(
            ok=True,
            answer=str(data.get("answer", "")).strip(),
            answer_text=str(data.get("answer_text", "")).strip(),
            question=str(data.get("question", "")).strip(),
            explanation=explanation,
            confidence=confidence,
            provider=result.provider_name,
            model=result.model,
            elapsed=round(result.elapsed, 2),
            page_title=snap.title,
            page_url=snap.url,
            mode=mode,
        )
