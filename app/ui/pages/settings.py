"""Settings page."""
from __future__ import annotations

import os
from tkinter import filedialog
from typing import TYPE_CHECKING, Any, Callable

import customtkinter as ctk

from app.core.config import LANGUAGES, THEMES
from app.paths import LOG_DIR
from app.ui import theme as T
from app.ui.theme import Fonts
from app.ui.widgets import Card, PageHeader, SettingRow, secondary_button

if TYPE_CHECKING:
    from app.ui.app_window import MainWindow

_LANG_NAMES = {"ua": "Українська", "en": "English", "ru": "Русский"}


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkFrame, app: "MainWindow") -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        t = app.i18n.t

        PageHeader(self, t("settings.title"), t("settings.subtitle")).pack(fill="x", pady=(0, 18))
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.SURFACE_ALT,
                                        scrollbar_button_hover_color=T.SURFACE_HOVER)
        scroll.pack(fill="both", expand=True)
        self._scroll = scroll
        # Sections are built one at a time with pauses so the window stays responsive during
        # background prep (all together they'd block it for ~0.6 s). If the page is opened
        # earlier, on_show() builds the rest right away.
        self._steps = [self._build_interface, self._build_behavior, self._build_browser, self._build_maintenance]
        self.after(20, self._next_step)

    def _next_step(self) -> None:
        if self._steps and self.winfo_exists():
            self._steps.pop(0)()
            if self._steps:
                self.after(20, self._next_step)

    def _finish(self) -> None:
        while self._steps:
            self._steps.pop(0)()

    def _build_interface(self) -> None:
        app, t, s, scroll = self.app, self.app.i18n.t, self.app.cfg.settings, self._scroll
        # --- Interface
        sec = self._section(scroll, t("settings.interface"))
        lang_names = {_LANG_NAMES[c]: c for c in LANGUAGES}
        self._option(sec, t("settings.language"), list(lang_names), _LANG_NAMES[s.language],
                     lambda v: app.set_language(lang_names[v]))
        theme_names = {t(f"settings.themes.{k}"): k for k in THEMES}
        self._option(sec, t("settings.theme"), list(theme_names), t(f"settings.themes.{s.theme}"),
                     lambda v: app.set_theme(theme_names[v]))
        self._switch(sec, t("settings.show_explanation"), s.show_explanation,
                     lambda v: app.cfg.update(show_explanation=v))

    def _build_behavior(self) -> None:
        app, t, s, scroll = self.app, self.app.i18n.t, self.app.cfg.settings, self._scroll
        # --- Behavior
        sec = self._section(scroll, t("settings.behavior"))
        self._switch(sec, t("settings.close_to_tray"), s.close_to_tray, lambda v: app.cfg.update(close_to_tray=v))
        self._switch(sec, t("settings.always_on_top"), s.always_on_top, app.set_always_on_top)
        self._switch(sec, t("settings.notifications"), s.notifications, lambda v: app.cfg.update(notifications=v))

    def _build_browser(self) -> None:
        app, t, s, scroll = self.app, self.app.i18n.t, self.app.cfg.settings, self._scroll
        # --- Browser
        sec = self._section(scroll, t("settings.browser"))
        self._switch(sec, t("settings.auto_launch"), s.auto_launch_browser,
                     lambda v: app.cfg.update(auto_launch_browser=v))

        row = SettingRow(sec, t("settings.port"))
        row.pack(fill="x", pady=6)
        self.port = ctk.CTkEntry(row.slot, width=90, height=32, justify="center", fg_color=T.SURFACE_ALT,
                                 border_color=T.BORDER, font=Fonts.mono())
        self.port.insert(0, str(s.browser_port))
        self.port.bind("<FocusOut>", lambda _e: self._save_port())
        self.port.bind("<Return>", lambda _e: self._save_port())
        self.port.pack()

        row = SettingRow(sec, t("settings.browser_path"), t("settings.browser_path_hint"))
        row.pack(fill="x", pady=6)
        self.path = ctk.CTkEntry(row.slot, width=300, height=32, fg_color=T.SURFACE_ALT, border_color=T.BORDER,
                                 font=Fonts.small())
        self.path.insert(0, s.browser_path)
        self.path.bind("<FocusOut>", lambda _e: self._save_path())
        self.path.pack(side="left")
        secondary_button(row.slot, t("settings.browse"), self._browse, height=32, width=80).pack(side="left", padx=(6, 0))

        secondary_button(sec, t("settings.launch_now"), app.launch_browser, height=34).pack(anchor="w", pady=(10, 0))

    def _build_maintenance(self) -> None:
        t, scroll = self.app.i18n.t, self._scroll
        # --- Maintenance
        sec = self._section(scroll, t("settings.maintenance"))
        box = ctk.CTkFrame(sec, fg_color="transparent")
        box.pack(fill="x")
        secondary_button(box, t("settings.open_logs"), self._open_logs, height=34).pack(side="left")
        secondary_button(box, t("settings.reset_limits"), self._reset_limits, height=34).pack(side="left", padx=8)

    # ---------------------------------------------------------- builders ---
    def _section(self, master: Any, title: str) -> ctk.CTkFrame:
        card = Card(master)
        card.pack(fill="x", pady=(0, 14), padx=(0, 6))
        ctk.CTkLabel(card, text=title, font=Fonts.h2(), text_color=T.TEXT, anchor="w").pack(
            fill="x", padx=20, pady=(16, 6))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=20, pady=(0, 16))
        return inner

    def _option(self, master: Any, label: str, values: list[str], current: str,
                on_change: Callable[[str], None]) -> None:
        row = SettingRow(master, label)
        row.pack(fill="x", pady=6)
        menu = ctk.CTkOptionMenu(row.slot, values=values, command=on_change, width=180, height=32,
                                 fg_color=T.SURFACE_ALT, button_color=T.SURFACE_HOVER,
                                 button_hover_color=T.BORDER, text_color=T.TEXT, font=Fonts.body(),
                                 dropdown_font=Fonts.body(), corner_radius=T.RADIUS_SM)
        menu.set(current)
        menu.pack()

    def _switch(self, master: Any, label: str, value: bool, on_change: Callable[[bool], None]) -> None:
        row = SettingRow(master, label)
        row.pack(fill="x", pady=6)
        sw = ctk.CTkSwitch(row.slot, text="", width=44, progress_color=T.ACCENT)
        sw.configure(command=lambda: on_change(bool(sw.get())))
        if value:
            sw.select()
        sw.pack()

    # ----------------------------------------------------------- actions ---
    def _save_port(self) -> None:
        try:
            port = int(self.port.get())
            if not 1024 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.port.delete(0, "end")
            self.port.insert(0, str(self.app.cfg.settings.browser_port))
            return
        if port != self.app.cfg.settings.browser_port:
            self.app.cfg.update(browser_port=port)
            self.app.browser.port = port

    def _save_path(self) -> None:
        value = self.path.get().strip()
        if value != self.app.cfg.settings.browser_path:
            self.app.cfg.update(browser_path=value)
            self.app.browser.executable = value

    def _browse(self) -> None:
        path = filedialog.askopenfilename(parent=self, filetypes=[("Executable", "*.exe"), ("All", "*.*")])
        if path:
            self.path.delete(0, "end")
            self.path.insert(0, os.path.normpath(path))
            self._save_path()

    def _open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(LOG_DIR)  # type: ignore[attr-defined]  # Windows-only

    def _reset_limits(self) -> None:
        self.app.router.reset_state()
        self.app.toast.show(self.app.i18n.t("settings.reset_done"), "success")

    def on_show(self) -> None:
        self._finish()
