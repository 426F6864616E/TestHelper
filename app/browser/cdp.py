"""Talks to the browser directly over the Chrome DevTools Protocol.

Unlike Selenium, no chromedriver is needed and there are no
version mismatches: any Chromium browser is supported
(Chrome, Edge, Brave) started with `--remote-debugging-port`.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import websocket

log = logging.getLogger(__name__)

_IGNORED_SCHEMES = ("devtools://", "chrome://", "chrome-extension://", "edge://", "about:", "brave://")

# Collects the page's visible text including all reachable iframes and shadow DOM,
# and marks the answer options the user has already selected.
_EXTRACT_JS = r"""
(() => {
  const parts = [];
  const seen = new Set();
  const visit = (doc, depth) => {
    if (!doc || depth > 5 || seen.has(doc)) return;
    seen.add(doc);
    try {
      const body = doc.body;
      if (body) {
        let text = body.innerText || "";
        body.querySelectorAll('*').forEach(el => {
          if (el.shadowRoot) text += "\n" + (el.shadowRoot.textContent || "");
        });
        doc.querySelectorAll('input[type=radio]:checked, input[type=checkbox]:checked').forEach(el => {
          const label = el.closest('label') || doc.querySelector(`label[for="${el.id}"]`);
          if (label) text += "\n[SELECTED BY USER] " + label.innerText.trim();
        });
        parts.push(text);
      }
      doc.querySelectorAll('iframe, frame').forEach(f => {
        try { visit(f.contentDocument, depth + 1); } catch (e) {}
      });
    } catch (e) {}
  };
  visit(document, 0);
  return JSON.stringify({ title: document.title, url: location.href, text: parts.join("\n\n") });
})()
"""


class BrowserError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code  # localization key: not_running / no_tab / launch_failed / cdp


@dataclass(frozen=True)
class PageSnapshot:
    title: str
    url: str
    text: str
    screenshot_jpeg: bytes | None


def find_browser_executable() -> str | None:
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    pf86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    candidates = [
        Path(pf) / "Google/Chrome/Application/chrome.exe",
        Path(pf86) / "Google/Chrome/Application/chrome.exe",
        Path(local) / "Google/Chrome/Application/chrome.exe",
        Path(pf) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(local) / "BraveSoftware/Brave-Browser/Application/brave.exe",
        Path(pf86) / "Microsoft/Edge/Application/msedge.exe",
        Path(pf) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


class _CDPSession:
    """Short synchronous session to a single tab."""

    def __init__(self, ws_url: str, timeout: float = 15.0) -> None:
        try:
            self._ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        except Exception as exc:  # noqa: BLE001 — any connection error
            raise BrowserError("cdp", str(exc)) from exc
        self._next_id = 0

    def call(self, method: str, timeout: float | None = None, **params) -> dict:
        self._next_id += 1
        msg_id = self._next_id
        old_timeout = self._ws.gettimeout()
        if timeout is not None:
            self._ws.settimeout(timeout)
        try:
            self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
            while True:
                data = json.loads(self._ws.recv())
                if data.get("id") == msg_id:
                    if "error" in data:
                        raise BrowserError("cdp", data["error"].get("message", "CDP error"))
                    return data.get("result", {})
        except BrowserError:
            raise
        except Exception as exc:  # noqa: BLE001 — timeout / connection drop
            raise BrowserError("cdp", f"{method}: {exc}") from exc
        finally:
            if timeout is not None:
                self._ws.settimeout(old_timeout)

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "_CDPSession":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class BrowserBridge:
    def __init__(self, port: int, profile_dir: Path, executable: str = "") -> None:
        self.port = port
        self.profile_dir = profile_dir
        self.executable = executable
        self._launch_lock = threading.Lock()
        self._http = httpx.Client(timeout=3.0, trust_env=False)

    @property
    def _endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        try:
            return self._http.get(f"{self._endpoint}/json/version").status_code == 200
        except httpx.HTTPError:
            return False

    def launch(self, url: str = "https://www.google.com") -> None:
        with self._launch_lock:
            if self.is_running():
                return
            exe = self.executable or find_browser_executable()
            if not exe:
                raise BrowserError("not_found")
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                exe,
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                url,
            ]
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            log.info("Launching browser: %s", exe)
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            except OSError as exc:
                raise BrowserError("launch_failed", str(exc)) from exc
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self.is_running():
                    return
                time.sleep(0.4)
            raise BrowserError("launch_failed", "debug port did not open")

    def _active_tab(self) -> dict:
        try:
            targets = self._http.get(f"{self._endpoint}/json/list").json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BrowserError("not_running", str(exc)) from exc
        # Chrome returns tabs in order of last activation.
        for t in targets:
            if t.get("type") == "page" and not str(t.get("url", "")).startswith(_IGNORED_SCHEMES):
                if t.get("webSocketDebuggerUrl"):
                    return t
        raise BrowserError("no_tab")

    def snapshot(self, with_text: bool = True, with_screenshot: bool = False) -> PageSnapshot:
        if not self.is_running():
            raise BrowserError("not_running")
        tab = self._active_tab()
        title, url, text, shot = tab.get("title", ""), tab.get("url", ""), "", None

        with _CDPSession(tab["webSocketDebuggerUrl"]) as cdp:
            _wait_until_loaded(cdp)
            if with_text:
                res = cdp.call("Runtime.evaluate", expression=_EXTRACT_JS, returnByValue=True)
                payload = res.get("result", {}).get("value")
                if payload:
                    data = json.loads(payload)
                    title, url, text = data.get("title", title), data.get("url", url), data.get("text", "")
            if with_screenshot:
                try:
                    shot = _capture(cdp)
                except BrowserError as exc:
                    # No screenshot, but scanning still works with text.
                    if not text.strip():
                        raise
                    log.warning("Screenshot unavailable, continuing with text only: %s", exc)

        return PageSnapshot(title=title, url=url, text=_clean_text(text), screenshot_jpeg=shot)

        return PageSnapshot(title=title, url=url, text=_clean_text(text), screenshot_jpeg=shot)

    def close(self) -> None:
        self._http.close()


def _wait_until_loaded(cdp: _CDPSession, limit: float = 8.0) -> None:
    """A freshly opened page may still be empty — wait for readyState."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        res = cdp.call("Runtime.evaluate", expression="document.readyState", returnByValue=True)
        if res.get("result", {}).get("value") in ("interactive", "complete"):
            return
        time.sleep(0.25)


def _restore_window(cdp: _CDPSession) -> None:
    """A minimized Chrome window isn't painted, so no screenshot is possible — restore it."""
    try:
        win = cdp.call("Browser.getWindowForTarget", timeout=3)
        if win.get("bounds", {}).get("windowState") == "minimized":
            cdp.call("Browser.setWindowBounds", timeout=3, windowId=win["windowId"],
                     bounds={"windowState": "normal"})
            time.sleep(0.4)
    except BrowserError as exc:
        log.debug("Cannot restore browser window: %s", exc)


def _capture(cdp: _CDPSession, attempts: int = 3) -> bytes | None:
    _restore_window(cdp)
    last: BrowserError | None = None
    for attempt in range(attempts):
        try:
            if attempt:
                # Background tab or frame not painted yet — bring the tab to front and retry.
                cdp.call("Page.bringToFront", timeout=3)
                time.sleep(0.35 * attempt)
            res = cdp.call("Page.captureScreenshot", timeout=6, format="jpeg", quality=82,
                           captureBeyondViewport=False, fromSurface=True)
            return base64.b64decode(res["data"]) if res.get("data") else None
        except BrowserError as exc:
            last = exc
            log.info("Screenshot attempt %d failed: %s", attempt + 1, exc)
    assert last is not None
    raise last


def _clean_text(text: str, limit: int = 15000) -> str:
    lines, prev = [], None
    for line in text.splitlines():
        line = " ".join(line.split())
        if line and line != prev:
            lines.append(line)
            prev = line
    cleaned = "\n".join(lines)
    return cleaned[:limit]
