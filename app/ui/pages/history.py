"""Scan history page."""
from __future__ import annotations

import time
from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from app.core.models import ScanResult
from app.ui import theme as T
from app.ui.theme import Fonts
from app.ui.widgets import Badge, Card, PageHeader, danger_button, ghost_button

if TYPE_CHECKING:
    from app.ui.app_window import MainWindow

_RENDER_LIMIT = 60


class HistoryPage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkFrame, app: "MainWindow") -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        t = app.i18n.t
        self._dirty = True

        header = PageHeader(self, t("history.title"), t("history.subtitle"))
        header.pack(fill="x", pady=(0, 18))
        danger_button(header.actions, t("history.clear"), self._clear, height=34).pack()

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.SURFACE_ALT,
                                           scrollbar_button_hover_color=T.SURFACE_HOVER)
        self.list.pack(fill="both", expand=True)

    def mark_dirty(self) -> None:
        self._dirty = True

    def on_show(self) -> None:
        if self._dirty:
            self._render()
            self._dirty = False

    warm = on_show  # draw the list right away while warming up pages

    def _render(self) -> None:
        for w in self.list.winfo_children():
            w.destroy()
        items = self.app.history.items()
        if not items:
            ctk.CTkLabel(self.list, text=self.app.i18n.t("history.empty"), font=Fonts.body(),
                         text_color=T.TEXT_MUTED).pack(pady=80)
            return
        for item in items[:_RENDER_LIMIT]:
            self._row(item)

    def _row(self, r: ScanResult) -> None:
        card = Card(self.list)
        card.pack(fill="x", pady=5, padx=(0, 6))
        card.grid_columnconfigure(1, weight=1)

        answer_color = T.ACCENT if r.ok else T.DANGER
        ctk.CTkLabel(card, text=r.answer if r.ok else "—", font=Fonts.get(20, "bold"),
                     text_color=answer_color, width=90, anchor="center").grid(row=0, column=0, rowspan=2,
                                                                              padx=(16, 8), pady=14)

        error = self.app.i18n.error_text(r.error_key, r.error)
        title = r.question or r.answer_text or r.page_title or error
        ctk.CTkLabel(card, text=title[:110], font=Fonts.body_bold(), text_color=T.TEXT,
                     anchor="w", justify="left").grid(row=0, column=1, sticky="ew", pady=(14, 0))

        when = time.strftime("%d.%m %H:%M", time.localtime(r.timestamp))
        sub = f"{when}  ·  {r.provider or '—'}  ·  {r.page_title[:50]}" if r.ok else f"{when}  ·  {error[:90]}"
        ctk.CTkLabel(card, text=sub, font=Fonts.small(), text_color=T.TEXT_MUTED,
                     anchor="w").grid(row=1, column=1, sticky="ew", pady=(0, 14))

        right = ctk.CTkFrame(card, fg_color="transparent")
        right.grid(row=0, column=2, rowspan=2, padx=12)
        if r.ok:
            Badge(right, f"{r.confidence}%", fg=T.SURFACE_ALT, color=T.confidence_color(r.confidence)).pack(
                side="left", padx=(0, 6))
            ghost_button(right, "⧉", lambda res=r: self._copy(res), width=34).pack(side="left")

    def _copy(self, r: ScanResult) -> None:
        self.app.copy_to_clipboard(r.short)
        self.app.toast.show(self.app.i18n.t("scan.copied"), "success")

    def _clear(self) -> None:
        if messagebox.askyesno(self.app.i18n.t("history.title"), self.app.i18n.t("history.confirm_clear"),
                               parent=self):
            self.app.history.clear()
            self._render()
