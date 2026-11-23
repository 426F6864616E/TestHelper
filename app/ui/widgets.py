"""Reusable UI components."""
from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from app.ui import theme as T
from app.ui.theme import Fonts


def _patch_scrollbar() -> None:
    """Removes the forced update_idletasks() from CTkScrollbar._draw.

    CustomTkinter 5–6 calls update_idletasks() after every scrollbar repaint —
    i.e. synchronously repaints the WHOLE window. That happens on every
    list height change, so any action on the "AI providers" page lagged ~0.4 s.
    Without it the scrollbar paints in the normal event loop — one frame later, unnoticeably.
    """
    original = ctk.CTkScrollbar._draw
    if getattr(original, "_no_forced_update", False):
        return

    def _draw(self: ctk.CTkScrollbar, no_color_updates: bool = False) -> None:
        canvas = self._canvas
        canvas.update_idletasks = lambda: None  # type: ignore[method-assign]
        try:
            original(self, no_color_updates)
        finally:
            del canvas.update_idletasks

    _draw._no_forced_update = True  # type: ignore[attr-defined]
    ctk.CTkScrollbar._draw = _draw  # type: ignore[method-assign]


_patch_scrollbar()


class Card(ctk.CTkFrame):
    def __init__(self, master: Any, **kw: Any) -> None:
        kw.setdefault("fg_color", T.SURFACE)
        kw.setdefault("corner_radius", T.RADIUS)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.BORDER)
        super().__init__(master, **kw)


def primary_button(master: Any, text: str, command: Callable[[], None], **kw: Any) -> ctk.CTkButton:
    kw.setdefault("height", 40)
    kw.setdefault("font", Fonts.body_bold())
    return ctk.CTkButton(master, text=text, command=command, fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER,
                         text_color=T.ON_ACCENT, corner_radius=T.RADIUS_SM, **kw)


def secondary_button(master: Any, text: str, command: Callable[[], None], **kw: Any) -> ctk.CTkButton:
    kw.setdefault("height", 36)
    kw.setdefault("font", Fonts.body())
    kw.setdefault("fg_color", T.SURFACE_ALT)
    return ctk.CTkButton(master, text=text, command=command, hover_color=T.SURFACE_HOVER,
                         text_color=T.TEXT, corner_radius=T.RADIUS_SM, border_width=0, **kw)


def ghost_button(master: Any, text: str, command: Callable[[], None], **kw: Any) -> ctk.CTkButton:
    kw.setdefault("height", 30)
    kw.setdefault("font", Fonts.body())
    kw.setdefault("text_color", T.TEXT_MUTED)
    return ctk.CTkButton(master, text=text, command=command, fg_color="transparent", hover_color=T.SURFACE_HOVER,
                         corner_radius=T.RADIUS_SM, **kw)


def danger_button(master: Any, text: str, command: Callable[[], None], **kw: Any) -> ctk.CTkButton:
    kw.setdefault("height", 30)
    kw.setdefault("font", Fonts.body())
    return ctk.CTkButton(master, text=text, command=command, fg_color="transparent", hover_color=T.DANGER_SOFT,
                         text_color=T.DANGER, corner_radius=T.RADIUS_SM, **kw)


class PageHeader(ctk.CTkFrame):
    def __init__(self, master: Any, title: str, subtitle: str = "") -> None:
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=title, font=Fonts.h1(), text_color=T.TEXT, anchor="w").pack(fill="x")
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=Fonts.body(), text_color=T.TEXT_MUTED,
                         anchor="w", justify="left", wraplength=720).pack(fill="x", pady=(2, 0))
        # Size 1×1: an empty CTkFrame defaults to 200×200 and would cover part of the subtitle
        # on pages without buttons. Buttons, if any, stretch this area themselves.
        self.actions = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.actions.place(relx=1.0, rely=0.0, anchor="ne")


class Badge(ctk.CTkLabel):
    def __init__(self, master: Any, text: str, fg: tuple[str, str] = T.ACCENT_SOFT,
                 color: tuple[str, str] = T.ACCENT, **kw: Any) -> None:
        super().__init__(master, text=f"  {text}  ", fg_color=fg, text_color=color, corner_radius=8,
                         font=Fonts.small(), height=22, **kw)


class StatusDot(ctk.CTkFrame):
    """Colored dot + label for sidebar status."""

    def __init__(self, master: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.dot = ctk.CTkFrame(self, width=8, height=8, corner_radius=4, fg_color=T.TEXT_FAINT)
        self.dot.pack(side="left", padx=(0, 8))
        self.label = ctk.CTkLabel(self, text="", font=Fonts.small(), text_color=T.TEXT_MUTED, anchor="w")
        self.label.pack(side="left", fill="x")

    def set(self, text: str, color: tuple[str, str]) -> None:
        self.dot.configure(fg_color=color)
        self.label.configure(text=text)


class SettingRow(ctk.CTkFrame):
    """Settings row: label (+ hint) on the left, control on the right."""

    def __init__(self, master: Any, label: str, hint: str = "") -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        text = ctk.CTkFrame(self, fg_color="transparent")
        text.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(text, text=label, font=Fonts.body(), text_color=T.TEXT, anchor="w").pack(anchor="w")
        if hint:
            ctk.CTkLabel(text, text=hint, font=Fonts.small(), text_color=T.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.slot = ctk.CTkFrame(self, fg_color="transparent")
        self.slot.grid(row=0, column=1, sticky="e")


class Toast:
    """Unobtrusive toast at the bottom of the window."""

    def __init__(self, root: ctk.CTk) -> None:
        self._root = root
        self._label: ctk.CTkLabel | None = None
        self._job: str | None = None

    def show(self, text: str, kind: str = "info", ms: int = 2600) -> None:
        colors = {
            "info": (T.SURFACE_ALT, T.TEXT),
            "success": (T.SUCCESS_SOFT, T.SUCCESS),
            "error": (T.DANGER_SOFT, T.DANGER),
        }
        bg, fg = colors.get(kind, colors["info"])
        if self._label is None:
            self._label = ctk.CTkLabel(self._root, text="", corner_radius=10, font=Fonts.body_bold(), height=38)
        self._label.configure(text=f"   {text}   ", fg_color=bg, text_color=fg)
        self._label.place(relx=0.5, rely=1.0, y=-24, anchor="s")
        self._label.lift()
        if self._job:
            self._root.after_cancel(self._job)
        self._job = self._root.after(ms, self.hide)

    def hide(self) -> None:
        if self._label is not None:
            self._label.place_forget()
        self._job = None
