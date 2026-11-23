"""System tray icon with states.

The icon color shows what is happening:
* idle    — purple (brand) — the app is waiting;
* working — amber with three running dots — looking for the answer;
* ready   — green with a check mark — the answer is ready;
* error   — red with an exclamation mark — failed.

After ready / error the icon goes back to purple when the window is opened
or after 90 seconds.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from app import __app_name__
from app.i18n import I18n
from app.paths import ICON_PNG

log = logging.getLogger(__name__)

_S = 256          # draw large and scale down for smooth edges
_SIZE = 64        # tray size
_RESET_AFTER = 90.0
_DOT_FRAMES = 3   # frames of the "searching" animation
_DOT_PERIOD = 0.35

# (top-left, bottom-right) gradient colors
_GRADIENTS = {
    "idle": ((150, 132, 255), (84, 64, 232)),
    "working": ((252, 196, 64), (234, 136, 12)),
    "ready": ((74, 222, 160), (16, 150, 96)),
    "error": ((252, 120, 120), (210, 40, 40)),
}


def _base(state: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    c1, c2 = _GRADIENTS[state]
    # smooth diagonal gradient: 2×2 pixels with the corner colors, stretched bilinearly
    mid = tuple((a + b) // 2 for a, b in zip(c1, c2))
    seed = Image.new("RGB", (2, 2))
    seed.putdata([c1, mid, mid, c2])
    color = seed.resize((_S, _S), Image.BILINEAR)
    mask = Image.new("L", (_S, _S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((8, 8, _S - 8, _S - 8), radius=58, fill=255)
    img = Image.new("RGBA", (_S, _S), (0, 0, 0, 0))
    img.paste(color, (0, 0), mask)
    return img, ImageDraw.Draw(img)


def _check(d: ImageDraw.ImageDraw) -> None:
    pts = [(66, 136), (108, 178), (186, 96)]
    d.line(pts, fill="white", width=30, joint="curve")
    for x, y in (pts[0], pts[2]):
        d.ellipse((x - 15, y - 15, x + 15, y + 15), fill="white")


@lru_cache(maxsize=None)
def state_icon(state: str, frame: int = 0) -> Image.Image:
    """State icon. idle uses the brand logo; the rest are drawn in the same style."""
    if state == "idle" and ICON_PNG.exists():
        return Image.open(ICON_PNG).convert("RGBA").resize((_SIZE, _SIZE), Image.LANCZOS)
    img, d = _base(state if state in _GRADIENTS else "idle")
    if state in ("idle", "ready"):
        _check(d)
    elif state == "working":
        # three dots; the active one is bigger and brighter, in turn, like a loading indicator
        for i, x in enumerate((76, 128, 180)):
            active = i == frame % _DOT_FRAMES
            r = 23 if active else 15
            d.ellipse((x - r, 128 - r, x + r, 128 + r), fill="white" if active else (255, 240, 205))
    elif state == "error":
        d.rounded_rectangle((113, 58, 143, 150), radius=15, fill="white")
        d.ellipse((111, 168, 145, 202), fill="white")
    return img.resize((_SIZE, _SIZE), Image.LANCZOS)


class TrayIcon:
    def __init__(self, i18n: I18n, on_scan: Callable[[], None], on_show: Callable[[], None],
                 on_exit: Callable[[], None]) -> None:
        t = i18n.t
        self._t = t
        menu = pystray.Menu(
            pystray.MenuItem(lambda _i: t("tray.scan"), lambda: on_scan(), default=True),
            pystray.MenuItem(lambda _i: t("tray.show"), lambda: on_show()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _i: t("tray.exit"), lambda: on_exit()),
        )
        self._icon = pystray.Icon("TestHelper", state_icon("idle"), f"{__app_name__} — {t('tray.idle')}", menu)
        self._thread: threading.Thread | None = None
        self.state = "idle"
        self._lock = threading.Lock()
        self._anim_stop = threading.Event()
        self._reset_timer: threading.Timer | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:  # noqa: BLE001
            log.exception("Tray icon crashed")

    # ------------------------------------------------------------ states ---
    def set_state(self, state: str, status: str | None = None) -> None:
        """Changes the icon color (idle / working / ready / error) and, if needed, the tooltip."""
        with self._lock:
            self.state = state
            self._anim_stop.set()  # stop the previous animation
            if self._reset_timer:
                self._reset_timer.cancel()
                self._reset_timer = None
            try:
                self._icon.icon = state_icon(state)
            except Exception:  # noqa: BLE001 — the tray may not be running yet
                log.debug("Tray icon update failed", exc_info=True)
            if state == "working":
                self._anim_stop = threading.Event()
                threading.Thread(target=self._animate, args=(self._anim_stop,), name="tray-anim",
                                 daemon=True).start()
            elif state in ("ready", "error"):
                self._reset_timer = threading.Timer(_RESET_AFTER, self.reset)
                self._reset_timer.daemon = True
                self._reset_timer.start()
        if status is not None:
            self.set_status(status)
        elif state == "idle":
            self.set_status(f"{__app_name__} — {self._t('tray.idle')}")

    def reset(self) -> None:
        """Restores the normal purple icon after ready / error."""
        if self.state in ("ready", "error"):
            self.set_state("idle")

    def _animate(self, stop: threading.Event) -> None:
        frame = 0
        while not stop.wait(_DOT_PERIOD):
            frame += 1
            try:
                self._icon.icon = state_icon("working", frame % _DOT_FRAMES)
            except Exception:  # noqa: BLE001
                return

    # -------------------------------------------------------- tooltip ---
    def set_status(self, text: str) -> None:
        # Windows limits the tooltip to ~127 characters.
        self._icon.title = " ".join(str(text).split())[:120]

    def notify(self, message: str, title: str = __app_name__) -> None:
        try:
            self._icon.notify(message[:250], title)
        except Exception:  # noqa: BLE001 — notifications are not critical
            log.debug("Tray notification failed", exc_info=True)

    def stop(self) -> None:
        self._anim_stop.set()
        if self._reset_timer:
            self._reset_timer.cancel()
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            pass
