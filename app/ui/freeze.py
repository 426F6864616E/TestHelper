"""Freeze frame for smooth tab switching (Windows only).

Tk paints a new page widget by widget, so without protection the user sees torn frames:
pieces of the old page under the new one. So during the switch we put a still
snapshot of what was there over the page area, the new page paints underneath,
and the snapshot is removed once it is ready.

The snapshot window is created once and then only shown/hidden with direct
Windows calls. A newly created Tk window appears only after the event queue runs, i.e. too late:
in measurements that produced both mixed frames and an empty rectangle.

The window is click-through (WS_EX_TRANSPARENT), never takes focus (WS_EX_NOACTIVATE)
and doesn't appear on the taskbar (WS_EX_TOOLWINDOW).
"""
from __future__ import annotations

import ctypes
import logging
import sys
import tkinter as tk

from PIL import ImageGrab, ImageTk

log = logging.getLogger(__name__)

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_LWA_ALPHA = 0x2
_OFFSCREEN = -32000
_HWND_TOPMOST = -1
# SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
_SWP_RAISE_ONLY = 0x0001 | 0x0002 | 0x0010


class FreezeFrame:
    def __init__(self, root: tk.Misc) -> None:
        self._root = root
        self._ok = False
        self._img: ImageTk.PhotoImage | None = None
        self._hide_job: str | None = None
        if sys.platform != "win32":
            return
        try:
            win = tk.Toplevel(root)
            win.overrideredirect(True)
            # Topmost: Tk doesn't apply transient to borderless windows, so otherwise the snapshot
            # ends up BELOW the main window. Outside a switch the window is transparent, clicks
            # pass through it and it sits off-screen — in nobody's way.
            win.attributes("-topmost", True)
            win.geometry(f"1x1+{_OFFSCREEN}+{_OFFSCREEN}")
            self._label = tk.Label(win, borderwidth=0, highlightthickness=0, bg="#0E1014")
            self._label.pack(fill="both", expand=True)
            win.update_idletasks()
            self._win = win
            user32 = ctypes.windll.user32
            # The real outer Windows window (winfo_id is only Tk's inner container).
            self._hwnd = int(win.wm_frame(), 16)
            style = user32.GetWindowLongW(self._hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(self._hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT
                                  | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE)
            self._alpha(0)
            self._ok = True
        except Exception:  # noqa: BLE001 — works without the freeze frame too, just less smoothly
            log.debug("Freeze frame unavailable", exc_info=True)

    def _alpha(self, value: int) -> None:
        ctypes.windll.user32.SetLayeredWindowAttributes(self._hwnd, 0, value, _LWA_ALPHA)

    def _move(self, x: int, y: int, w: int, h: int) -> None:
        # Position is set via Tk: if the window is moved directly, Tk moves it back
        # to "its" place (off-screen) on the next layout, and the freeze frame is invisible.
        self._win.geometry(f"{w}x{h}+{x}+{y}")
        self._win.update_idletasks()
        if x != _OFFSCREEN:
            # To the very top of the topmost layer — above the main window even
            # when "Always on top" is enabled in settings.
            ctypes.windll.user32.SetWindowPos(self._hwnd, _HWND_TOPMOST, 0, 0, 0, 0, _SWP_RAISE_ONLY)

    def cover(self, area: tk.Misc) -> bool:
        """Instantly covers area with its own current snapshot. Returns True on success."""
        if not self._ok:
            return False
        if self._hide_job:
            self._root.after_cancel(self._hide_job)
            self._hide_job = None
        try:
            x, y, w, h = area.winfo_rootx(), area.winfo_rooty(), area.winfo_width(), area.winfo_height()
            if w < 10 or h < 10:
                return False
            shot = ImageGrab.grab((x, y, x + w, y + h), all_screens=True)
            self._alpha(0)
            self._img = ImageTk.PhotoImage(shot, master=self._win)
            self._label.configure(image=self._img)
            self._move(x, y, w, h)  # in place with the image, but still fully transparent
            self._alpha(255)  # show in a single frame
            return True
        except Exception:  # noqa: BLE001
            log.debug("Freeze frame failed", exc_info=True)
            self.hide()
            return False

    def release(self, delay_ms: int) -> None:
        """Removes the snapshot once the main window has finished painting the new page."""
        if not self._ok:
            return
        if self._hide_job:
            self._root.after_cancel(self._hide_job)
        self._hide_job = self._root.after(delay_ms, lambda: self._root.after_idle(self.hide))

    def hide(self) -> None:
        self._hide_job = None
        if not self._ok:
            return
        try:
            self._alpha(0)
            self._move(_OFFSCREEN, _OFFSCREEN, 1, 1)
            self._label.configure(image="")
            self._img = None
        except Exception:  # noqa: BLE001
            log.debug("Freeze frame hide failed", exc_info=True)
