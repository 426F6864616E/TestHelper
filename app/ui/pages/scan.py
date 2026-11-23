"""Main page: scanning and showing the answer."""
from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from app.core.config import SCAN_MODES
from app.core.models import ScanResult
from app.ui import theme as T
from app.ui.theme import Fonts
from app.ui.widgets import Card, PageHeader, ghost_button, primary_button, secondary_button

if TYPE_CHECKING:
    from app.ui.app_window import MainWindow


class ScanPage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkFrame, app: "MainWindow") -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        t = app.i18n.t
        self._result: ScanResult | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = PageHeader(self, t("scan.title"), t("scan.subtitle"))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))

        mode_box = ctk.CTkFrame(header.actions, fg_color="transparent")
        mode_box.pack()
        self._mode_labels = {t(f"scan.modes.{m}"): m for m in SCAN_MODES}
        self.mode = ctk.CTkSegmentedButton(
            mode_box, values=list(self._mode_labels), command=self._on_mode,
            font=Fonts.body(), height=32, corner_radius=T.RADIUS_SM,
            selected_color=T.ACCENT, selected_hover_color=T.ACCENT_HOVER,
            unselected_color=T.SURFACE_ALT, unselected_hover_color=T.SURFACE_HOVER,
            fg_color=T.SURFACE_ALT, text_color=T.TEXT,
        )
        self.mode.set(t(f"scan.modes.{app.cfg.settings.scan_mode}"))
        self.mode.pack(anchor="e")
        self.mode_hint = ctk.CTkLabel(mode_box, text="", font=Fonts.small(), text_color=T.TEXT_MUTED)
        self.mode_hint.pack(anchor="e", pady=(4, 0))
        self._update_mode_hint()

        self.card = Card(self)
        self.card.grid(row=1, column=0, sticky="nsew")
        self.body = ctk.CTkFrame(self.card, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=32, pady=28)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.scan_btn = primary_button(footer, f"⚡  {t('scan.button')}", app.request_scan, height=52,
                                       font=Fonts.get(16, "bold"))
        self.scan_btn.grid(row=0, column=0, sticky="ew")
        self.browser_btn = secondary_button(footer, f"🌐  {t('settings.launch_now')}", app.launch_browser,
                                            height=52, width=210)
        self.browser_btn.grid(row=0, column=1, padx=(12, 0))
        self.copy_btn = secondary_button(footer, t("scan.copy"), self._copy, height=52, width=150)
        self.copy_btn.grid(row=0, column=2, padx=(12, 0))

        self.show_empty()

    # ------------------------------------------------------------ states ---
    def _clear(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()

    def show_empty(self) -> None:
        t = self.app.i18n.t
        self._clear()
        box = ctk.CTkFrame(self.body, fg_color="transparent")
        box.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(box, text="◎", font=Fonts.get(54), text_color=T.ACCENT).pack()
        ctk.CTkLabel(box, text=t("scan.empty_title"), font=Fonts.h2(), text_color=T.TEXT).pack(pady=(6, 2))
        ctk.CTkLabel(box, text=t("scan.empty_hint"), font=Fonts.body(), text_color=T.TEXT_MUTED).pack()
        self.copy_btn.configure(state="disabled")

    def show_busy(self, message: str) -> None:
        t = self.app.i18n.t
        self.scan_btn.configure(state="disabled", text=f"⏳  {t('scan.scanning')}")
        if not getattr(self, "_busy_label", None) or not self._busy_label.winfo_exists():
            self._clear()
            box = ctk.CTkFrame(self.body, fg_color="transparent")
            box.place(relx=0.5, rely=0.5, anchor="center")
            bar = ctk.CTkProgressBar(box, mode="indeterminate", width=320, height=6,
                                     progress_color=T.ACCENT, fg_color=T.SURFACE_ALT)
            bar.pack(pady=(0, 16))
            bar.start()
            self._busy_label = ctk.CTkLabel(box, text="", font=Fonts.body(), text_color=T.TEXT_MUTED)
            self._busy_label.pack()
        self._busy_label.configure(text=message)

    def show_result(self, result: ScanResult) -> None:
        t = self.app.i18n.t
        self._busy_label = None
        self._result = result
        self.scan_btn.configure(state="normal", text=f"⚡  {t('scan.button')}")
        self._clear()
        if result.ok:
            self._render_ok(result)
            self.copy_btn.configure(state="normal")
        else:
            self._render_error(result)
            self.copy_btn.configure(state="disabled")

    def _render_ok(self, r: ScanResult) -> None:
        t = self.app.i18n.t
        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=t("scan.answer").upper(), font=Fonts.get(11, "bold"),
                     text_color=T.TEXT_MUTED).pack(side="left")
        ctk.CTkLabel(top, text=t("scan.meta", provider=r.provider, model=r.model, elapsed=r.elapsed),
                     font=Fonts.small(), text_color=T.TEXT_FAINT).pack(side="right")

        ctk.CTkLabel(self.body, text=r.answer, font=Fonts.display(), text_color=T.ACCENT,
                     anchor="w", justify="left", wraplength=760).pack(fill="x", pady=(6, 0))
        if r.answer_text and r.answer_text != r.answer:
            ctk.CTkLabel(self.body, text=r.answer_text, font=Fonts.get(17, "bold"), text_color=T.TEXT,
                         anchor="w", justify="left", wraplength=760).pack(fill="x", pady=(2, 0))

        ctk.CTkFrame(self.body, height=1, fg_color=T.BORDER).pack(fill="x", pady=20)

        conf = ctk.CTkFrame(self.body, fg_color="transparent")
        conf.pack(fill="x")
        ctk.CTkLabel(conf, text=t("scan.confidence"), font=Fonts.body(), text_color=T.TEXT_MUTED,
                     width=110, anchor="w").pack(side="left")
        color = T.confidence_color(r.confidence)
        bar = ctk.CTkProgressBar(conf, height=8, progress_color=color, fg_color=T.SURFACE_ALT)
        bar.set(r.confidence / 100)
        bar.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ctk.CTkLabel(conf, text=f"{r.confidence}%", font=Fonts.body_bold(), text_color=color,
                     width=48, anchor="e").pack(side="left")

        if r.question:
            self._kv(t("scan.question"), r.question)
        if r.explanation and self.app.cfg.settings.show_explanation:
            self._kv(t("scan.explanation"), r.explanation)

    def _kv(self, key: str, value: str) -> None:
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(row, text=key, font=Fonts.body(), text_color=T.TEXT_MUTED, width=110,
                     anchor="nw", justify="left").pack(side="left", anchor="n")
        ctk.CTkLabel(row, text=value, font=Fonts.body(), text_color=T.TEXT, anchor="w",
                     justify="left", wraplength=620).pack(side="left", fill="x", expand=True)

    def _render_error(self, r: ScanResult) -> None:
        t = self.app.i18n.t
        box = ctk.CTkFrame(self.body, fg_color="transparent")
        box.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(box, text="!", font=Fonts.get(26, "bold"), width=56, height=56, corner_radius=28,
                     fg_color=T.DANGER_SOFT, text_color=T.DANGER).pack()
        ctk.CTkLabel(box, text=t("scan.error_title"), font=Fonts.h2(), text_color=T.TEXT).pack(pady=(12, 4))
        ctk.CTkLabel(box, text=self.app.i18n.error_text(r.error_key, r.error), font=Fonts.body(), text_color=T.TEXT_MUTED,
                     wraplength=520, justify="center").pack()
        actions = ctk.CTkFrame(box, fg_color="transparent")
        actions.pack(pady=(16, 0))
        if r.error_code in ("no_keys", "ai"):
            primary_button(actions, t("scan.go_providers"), lambda: self.app.navigate("providers"),
                           height=36).pack(side="left", padx=4)
        else:
            secondary_button(actions, t("scan.open_browser"), self.app.launch_browser).pack(side="left", padx=4)
            ghost_button(actions, t("nav.providers"), lambda: self.app.navigate("providers"),
                         height=36).pack(side="left", padx=4)

    def set_browser_state(self, state: str) -> None:
        """Browser button: off — can launch, launching — starting, on — already running."""
        t = self.app.i18n.t
        if state == "launching":
            self.browser_btn.configure(state="disabled", text=f"⏳  {t('progress.launching_browser')}",
                                       text_color=T.TEXT_MUTED)
        elif state == "on":
            self.browser_btn.configure(state="disabled", text=f"✓  {t('status.browser_on')}",
                                       text_color_disabled=T.SUCCESS)
        else:
            self.browser_btn.configure(state="normal", text=f"🌐  {t('settings.launch_now')}", text_color=T.TEXT)

    # ----------------------------------------------------------- actions ---
    def _on_mode(self, label: str) -> None:
        self.app.cfg.update(scan_mode=self._mode_labels[label])
        self._update_mode_hint()

    def _update_mode_hint(self) -> None:
        mode = self.app.cfg.settings.scan_mode
        self.mode_hint.configure(text=self.app.i18n.t(f"scan.modes_hint.{mode}"))

    def _copy(self) -> None:
        if self._result and self._result.ok:
            self.app.copy_to_clipboard(self._result.short)
            self.app.toast.show(self.app.i18n.t("scan.copied"), "success")

    def on_show(self) -> None:
        pass
