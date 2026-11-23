"""AI provider management: keys, model choice, custom providers.

Performance: the page is built once. After a change (key, model, toggle) only that provider's
card is rebuilt, and reordering just moves cards — no rebuild.
A full rebuild happens only on first show and on language change.
"""
from __future__ import annotations

import webbrowser
from tkinter import messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from app.ai.providers import PRESETS, ProviderSpec, is_custom
from app.ui import theme as T
from app.ui.theme import Fonts
from app.ui.widgets import Badge, Card, PageHeader, danger_button, ghost_button, primary_button, secondary_button

if TYPE_CHECKING:
    from app.ui.app_window import MainWindow


def mask_key(key: str) -> str:
    return f"{key[:6]}••••••••{key[-4:]}" if len(key) > 14 else "••••••••"


class ProviderCard(Card):
    def __init__(self, master: Any, app: "MainWindow", spec: ProviderSpec, index: int, total: int) -> None:
        super().__init__(master)
        self.app = app
        self.spec = spec
        self.pid = spec.id
        t = app.i18n.t
        settings = app.cfg.provider(spec.id)
        custom = is_custom(spec.id)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(16, 0))
        self.number = ctk.CTkLabel(head, text=f"{index + 1}", font=Fonts.body_bold(), width=26, height=26,
                                   corner_radius=13, fg_color=T.ACCENT_SOFT, text_color=T.ACCENT)
        self.number.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(head, text=spec.name, font=Fonts.h2(), text_color=T.TEXT).pack(side="left")
        if custom:
            Badge(head, t("providers.custom_badge"), fg=T.SURFACE_ALT, color=T.TEXT_MUTED).pack(side="left", padx=8)
        self.count = Badge(head, "0", fg=T.SUCCESS_SOFT, color=T.SUCCESS)

        self.switch = ctk.CTkSwitch(head, text="", width=44, progress_color=T.ACCENT, command=self._toggle)
        if settings.enabled:
            self.switch.select()
        self.switch.pack(side="right")
        self.down = ghost_button(head, "▼", lambda: app.move_provider(spec.id, +1), width=30)
        self.up = ghost_button(head, "▲", lambda: app.move_provider(spec.id, -1), width=30)
        self.down.pack(side="right")
        self.up.pack(side="right")
        if custom:
            danger_button(head, "🗑", self._delete, width=30).pack(side="right", padx=(0, 4))
        elif spec.key_url:
            ghost_button(head, t("providers.get_key"), lambda: webbrowser.open(spec.key_url),
                         text_color=T.ACCENT).pack(side="right", padx=6)
        self.set_position(index, total)

        desc, font = (spec.base_url, Fonts.mono()) if custom else (t(spec.description_key), Fonts.small())
        ctk.CTkLabel(self, text=desc, font=font, text_color=T.TEXT_MUTED, anchor="w", justify="left",
                     wraplength=700).pack(fill="x", padx=20, pady=(6, 0))

        stats = app.router.stats.get(spec.id)
        if stats and (stats.ok or stats.failed):
            line = t("providers.stats", ok=stats.ok, failed=stats.failed)
            if stats.last_model:
                line += "   ·   " + t("providers.last_model", model=stats.last_model)
            ctk.CTkLabel(self, text=line, font=Fonts.small(), text_color=T.TEXT_FAINT,
                         anchor="w").pack(fill="x", padx=20, pady=(4, 0))

        # --- Keys
        self.keys_box = ctk.CTkFrame(self, fg_color="transparent")
        self.keys_box.pack(fill="x", padx=20, pady=(10, 0))
        self.refresh_keys()

        add = ctk.CTkFrame(self, fg_color="transparent")
        add.pack(fill="x", padx=20, pady=(10, 0))
        self.entry = ctk.CTkEntry(add, placeholder_text=t("providers.placeholder", hint=spec.key_hint),
                                  height=36, corner_radius=T.RADIUS_SM, border_color=T.BORDER,
                                  fg_color=T.SURFACE_ALT, font=Fonts.mono())
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self._add())
        primary_button(add, t("providers.add"), self._add, height=36, width=100).pack(side="left", padx=(8, 0))

        # --- Models
        self._models_row(custom)

    # --------------------------------------------------------------- models ---
    def _models_row(self, custom: bool) -> None:
        t = self.app.i18n.t
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(fill="x", padx=20, pady=(14, 16))
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=t("providers.models"), font=Fonts.body_bold(), text_color=T.TEXT).pack(side="left")
        hint = t("providers.models_hint_custom") if custom else t("providers.models_hint")
        ctk.CTkLabel(top, text="  ·  " + hint, font=Fonts.small(), text_color=T.TEXT_FAINT).pack(side="left")

        self.chips = ctk.CTkFrame(box, fg_color="transparent")
        self.chips.pack(fill="x", pady=(6, 0))
        self.refresh_models()

        pick = ctk.CTkFrame(box, fg_color="transparent")
        pick.pack(fill="x", pady=(8, 0))
        known = self.app.router.available_models(self.spec, None)  # cache only — no network on the UI thread
        self.model_box = ctk.CTkComboBox(
            pick, values=known, height=34, corner_radius=T.RADIUS_SM, border_color=T.BORDER,
            fg_color=T.SURFACE_ALT, button_color=T.SURFACE_HOVER, button_hover_color=T.BORDER,
            dropdown_fg_color=T.SURFACE, font=Fonts.mono(), dropdown_font=Fonts.mono(), text_color=T.TEXT,
        )
        self.model_box.set("")
        self.model_box.pack(side="left", fill="x", expand=True)
        self.model_box._entry.bind("<Return>", lambda _e: self._add_model())  # noqa: SLF001
        secondary_button(pick, t("providers.add_model"), self._add_model, height=34, width=130).pack(
            side="left", padx=(8, 0))
        if not known:
            self._load_models()

    def refresh_models(self) -> None:
        """Repaints only the chosen-models row (not the whole card)."""
        t = self.app.i18n.t
        old = list(self.chips.winfo_children())
        models = self.app.cfg.provider(self.pid).models
        if not models:
            ctk.CTkLabel(self.chips, text=t("providers.models_auto"), font=Fonts.small(), text_color=T.TEXT_MUTED,
                         fg_color=T.SURFACE_ALT, corner_radius=T.RADIUS_SM, height=28).pack(side="left", ipadx=10)
        for i, model in enumerate(models):
            chip = ctk.CTkFrame(self.chips, fg_color=T.ACCENT_SOFT, corner_radius=T.RADIUS_SM)
            chip.pack(side="left", padx=(0, 6), pady=2)
            ctk.CTkLabel(chip, text=f"{i + 1}. {model}", font=Fonts.mono(), text_color=T.ACCENT,
                         height=28).pack(side="left", padx=(10, 2))
            ctk.CTkButton(chip, text="✕", width=24, height=24, fg_color="transparent", hover_color=T.SURFACE_HOVER,
                          text_color=T.ACCENT, font=Fonts.small(), corner_radius=6,
                          command=lambda m=model: self.app.remove_model(self.pid, m)).pack(side="left", padx=(0, 4))
        for w in old:
            w.destroy()
        if hasattr(self, "model_box"):
            self.model_box.set("")  # model added — clear the field

    def refresh_keys(self) -> None:
        """Repaints only the key list and the counter in the header."""
        t = self.app.i18n.t
        old = list(self.keys_box.winfo_children())
        keys = self.app.cfg.provider(self.pid).keys
        if keys:
            self.count.configure(text=f"  {len(keys)}  ")
            if not self.count.winfo_manager():
                self.count.pack(side="left", padx=(0, 8))
        elif self.count.winfo_manager():
            self.count.pack_forget()
        if not keys:
            text = t("providers.no_key_local") if is_custom(self.pid) else t("providers.no_keys")
            ctk.CTkLabel(self.keys_box, text=text, font=Fonts.small(), text_color=T.TEXT_FAINT,
                         anchor="w").pack(fill="x")
        for key in keys:
            self._key_row(self.keys_box, key)
        for w in old:
            w.destroy()
        if hasattr(self, "entry"):
            self.entry.delete(0, "end")

    def _load_models(self) -> None:
        """Fetches the model list from the API in the background and fills the dropdown."""
        keys = self.app.cfg.plan_keys(self.pid)
        if not keys:
            return

        def done(models: list[str]) -> None:
            if models and self.model_box.winfo_exists():
                self.model_box.configure(values=models)

        self.app.run_background(lambda: self.app.router.available_models(self.spec, keys[0]), done)

    def _add_model(self) -> None:
        value = self.model_box.get().strip()
        if value:
            self.app.add_model(self.pid, value)

    # ---------------------------------------------------------------- keys ---
    def _key_row(self, master: ctk.CTkFrame, key: str) -> None:
        t = self.app.i18n.t
        row = ctk.CTkFrame(master, fg_color=T.SURFACE_ALT, corner_radius=T.RADIUS_SM)
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=mask_key(key), font=Fonts.mono(), text_color=T.TEXT).pack(side="left", padx=12, pady=7)
        status = ctk.CTkLabel(row, text="", font=Fonts.small(), text_color=T.TEXT_MUTED)
        danger_button(row, "✕", lambda: self.app.remove_key(self.pid, key), width=30).pack(side="right", padx=4)
        test_btn = secondary_button(row, t("providers.test"), lambda: None, height=28, width=90, fg_color=T.SURFACE)
        test_btn.configure(command=lambda: self._test(key, test_btn, status))
        test_btn.pack(side="right", padx=4)
        status.pack(side="right", padx=8)

    def _test(self, key: str, btn: ctk.CTkButton, status: ctk.CTkLabel) -> None:
        t = self.app.i18n.t
        btn.configure(state="disabled", text=t("providers.testing"))

        def done(res: tuple[bool, str]) -> None:
            if not btn.winfo_exists():
                return
            ok, info = res
            btn.configure(state="normal", text=t("providers.test"))
            if ok:
                status.configure(text="✓ " + t("providers.test_ok", count=info), text_color=T.SUCCESS)
                models = self.app.router.available_models(self.spec, None)
                if models and self.model_box.winfo_exists():
                    self.model_box.configure(values=models)
            else:
                status.configure(text="✕ " + t("providers.test_fail", error=info[:60]), text_color=T.DANGER)

        self.app.run_background(lambda: self.app.router.test_key(self.spec, key), done)

    # ---------------------------------------------------------------- misc ---
    def set_position(self, index: int, total: int) -> None:
        self.number.configure(text=f"{index + 1}")
        self.up.configure(state="disabled" if index == 0 else "normal")
        self.down.configure(state="disabled" if index == total - 1 else "normal")

    def _toggle(self) -> None:
        self.app.cfg.set_provider_enabled(self.pid, bool(self.switch.get()))
        self.app.refresh_status()

    def _add(self) -> None:
        value = self.entry.get().strip()
        if value:
            self.app.add_key(self.pid, value)

    def _delete(self) -> None:
        t = self.app.i18n.t
        if messagebox.askyesno(t("providers.delete_title"), t("providers.delete_confirm", name=self.spec.name),
                               parent=self):
            self.app.remove_custom_provider(self.pid)


class AddProviderCard(Card):
    """"Add your own provider" form: any OpenAI-compatible API."""

    def __init__(self, master: Any, app: "MainWindow") -> None:
        super().__init__(master)
        self.app = app
        t = app.i18n.t
        self._presets = {p.name: p for p in PRESETS}
        self._other = t("providers.preset_other")

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(16, 0))
        ctk.CTkLabel(head, text="＋  " + t("providers.add_provider"), font=Fonts.h2(), text_color=T.TEXT).pack(side="left")
        self.toggle_btn = ghost_button(head, t("providers.show_form"), self._toggle, text_color=T.ACCENT)
        self.toggle_btn.pack(side="right")
        ctk.CTkLabel(self, text=t("providers.add_provider_hint"), font=Fonts.small(), text_color=T.TEXT_MUTED,
                     anchor="w", justify="left", wraplength=700).pack(fill="x", padx=20, pady=(6, 14))
        self.form: ctk.CTkFrame | None = None  # the form is built on first open

    def _build_form(self) -> None:
        t = self.app.i18n.t
        grid = self.form = ctk.CTkFrame(self, fg_color="transparent")
        grid.grid_columnconfigure(1, weight=1)

        def label(row: int, text: str) -> None:
            ctk.CTkLabel(grid, text=text, font=Fonts.body(), text_color=T.TEXT_MUTED, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 14), pady=5)

        def entry(row: int, placeholder: str, mono: bool = False) -> ctk.CTkEntry:
            e = ctk.CTkEntry(grid, placeholder_text=placeholder, height=34, corner_radius=T.RADIUS_SM,
                             border_color=T.BORDER, fg_color=T.SURFACE_ALT,
                             font=Fonts.mono() if mono else Fonts.body())
            e.grid(row=row, column=1, sticky="ew", pady=5)
            return e

        label(0, t("providers.f_preset"))
        self.preset = ctk.CTkOptionMenu(
            grid, values=list(self._presets) + [self._other], command=self._apply_preset, height=34,
            corner_radius=T.RADIUS_SM, fg_color=T.SURFACE_ALT, button_color=T.SURFACE_HOVER,
            button_hover_color=T.BORDER, dropdown_fg_color=T.SURFACE, text_color=T.TEXT, font=Fonts.body(),
            dropdown_font=Fonts.body())
        self.preset.grid(row=0, column=1, sticky="w", pady=5)
        label(1, t("providers.f_name"))
        self.name = entry(1, "My API")
        label(2, t("providers.f_url"))
        self.url = entry(2, "https://api.example.com/v1", mono=True)
        label(3, t("providers.f_key"))
        self.key = entry(3, t("providers.f_key_hint"), mono=True)
        label(4, t("providers.f_models"))
        self.models = entry(4, t("providers.f_models_hint"), mono=True)
        label(5, t("providers.f_vision"))
        self.vision = ctk.CTkSwitch(grid, text="", width=44, progress_color=T.ACCENT)
        self.vision.grid(row=5, column=1, sticky="w", pady=5)

        actions = ctk.CTkFrame(grid, fg_color="transparent")
        actions.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 16))
        self.error = ctk.CTkLabel(actions, text="", font=Fonts.small(), text_color=T.DANGER)
        self.error.pack(side="left", padx=10)
        primary_button(actions, t("providers.f_save"), self._save, height=36, width=140).pack(side="left")
        self.preset.set(PRESETS[0].name)
        self._apply_preset(PRESETS[0].name)

    def reset(self) -> None:
        """Clears and collapses the form after a successful add."""
        if self.form is None:
            return
        for e in (self.key, self.models):
            e.delete(0, "end")
        self.preset.set(PRESETS[0].name)
        self._apply_preset(PRESETS[0].name)
        self.error.configure(text="")
        if self.form.winfo_manager():
            self._toggle()

    def _toggle(self) -> None:
        t = self.app.i18n.t
        if self.form is None:
            self._build_form()
        if self.form.winfo_manager():
            self.form.pack_forget()
            self.toggle_btn.configure(text=t("providers.show_form"))
        else:
            self.form.pack(fill="x", padx=20)
            self.toggle_btn.configure(text=t("providers.hide_form"))

    def _apply_preset(self, choice: str) -> None:
        preset = self._presets.get(choice)
        for e in (self.name, self.url):
            e.delete(0, "end")
        if preset:
            self.name.insert(0, preset.name)
            self.url.insert(0, preset.base_url)
            if preset.vision:
                self.vision.select()
            else:
                self.vision.deselect()
        else:
            self.vision.select()

    def _save(self) -> None:
        t = self.app.i18n.t
        name, url = self.name.get().strip(), self.url.get().strip()
        key = self.key.get().strip()
        models = [m.strip() for m in self.models.get().replace(";", ",").split(",") if m.strip()]
        preset = self._presets.get(self.preset.get())
        if not name:
            self.error.configure(text=t("providers.e_name"))
            return
        if not url.startswith(("http://", "https://")):
            self.error.configure(text=t("providers.e_url"))
            return
        if preset and preset.needs_key and not key:
            self.error.configure(text=t("providers.e_key"))
            return
        self.error.configure(text="")
        self.app.add_custom_provider(name, url, bool(self.vision.get()), key, models)


class ProvidersPage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkFrame, app: "MainWindow") -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        t = app.i18n.t
        self._cards: dict[str, ProviderCard] = {}
        PageHeader(self, t("providers.title"), t("providers.subtitle")).pack(fill="x", pady=(0, 12))

        tip = ctk.CTkFrame(self, fg_color=T.ACCENT_SOFT, corner_radius=T.RADIUS_SM)
        tip.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(tip, text="💡  " + t("providers.tip"), font=Fonts.small(), text_color=T.TEXT,
                     justify="left", anchor="w", wraplength=760).pack(fill="x", padx=14, pady=10)

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.SURFACE_ALT,
                                           scrollbar_button_hover_color=T.SURFACE_HOVER)
        self.list.pack(fill="both", expand=True)
        self.render(chunked=True)

    def _signature(self) -> tuple:
        """Everything the cards display. If nothing changed, no rebuild is needed."""
        cfg = self.app.cfg
        stats = self.app.router.stats
        return tuple(
            (pid, tuple(cfg.provider(pid).keys), tuple(cfg.provider(pid).models), cfg.provider(pid).enabled,
             (stats[pid].ok, stats[pid].failed, stats[pid].last_model) if pid in stats else None)
            for pid in cfg.settings.provider_order
        )

    def _order(self) -> list[tuple[str, ProviderSpec]]:
        out = []
        for pid in self.app.cfg.settings.provider_order:
            spec = self.app.cfg.spec(pid)
            if spec:
                out.append((pid, spec))
        return out

    def render(self, chunked: bool = False) -> None:
        """Full rebuild — on first show and on language change.

        chunked=True (background prep after launch): cards are built one at a time with pauses
        so the window stays responsive. Building the whole page at once would block it for ~1.3 s.
        """
        self._build_job_id = getattr(self, "_build_job_id", 0) + 1
        job = self._build_job_id
        self._shown = self._signature()
        if not chunked:
            self.list.pack_forget()  # hide during the rebuild so cards don't pop in one by one
        for w in self.list.winfo_children():
            w.destroy()
        self._cards.clear()
        order = self._order()
        self.add_card = AddProviderCard(self.list, self.app)
        self.add_card.pack(fill="x", pady=(6, 12), padx=(0, 6))
        self.building = True

        def build(i: int) -> None:
            if job != self._build_job_id or not self.winfo_exists():
                return  # a newer rebuild has started
            if i >= len(order):
                self.building = False
                self._renumber()
                self._shown = self._signature()
                if not self.list.winfo_manager():
                    self.list.pack(fill="both", expand=True)
                return
            pid, spec = order[i]
            card = ProviderCard(self.list, self.app, spec, i, len(order))
            card.pack(fill="x", pady=6, padx=(0, 6), before=self.add_card)
            self._cards[pid] = card
            if chunked:
                self.after(15, lambda: build(i + 1))
            else:
                build(i + 1)

        if chunked:
            self.after(30, lambda: build(0))  # first card in its own step, not together with the skeleton
        else:
            build(0)
            self.list.pack(fill="both", expand=True)

    def refresh_card(self, pid: str) -> None:
        """Rebuilds just one card in place."""
        old = self._cards.get(pid)
        order = self._order()
        ids = [p for p, _s in order]
        if old is None or pid not in ids:
            self.render()
            return
        i = ids.index(pid)
        card = ProviderCard(self.list, self.app, order[i][1], i, len(order))
        card.pack(fill="x", pady=6, padx=(0, 6), after=old)
        self._cards[pid] = card
        self._dispose(old)
        self._shown = self._signature()

    def refresh_part(self, pid: str, part: str) -> None:
        """Refreshes only part of a card: 'keys' or 'models'."""
        card = self._cards.get(pid)
        if card is None:
            if not getattr(self, "building", False):
                self.render()
            return
        card.refresh_keys() if part == "keys" else card.refresh_models()
        self._shown = self._signature()

    def _dispose(self, widget: ctk.CTkBaseClass) -> None:
        """Hides the widget immediately and destroys it only after the new one has painted."""
        widget.pack_forget()
        self.after(120, lambda: widget.winfo_exists() and widget.destroy())

    def _renumber(self) -> None:
        order = [p for p, _s in self._order()]
        for i, pid in enumerate(order):
            if pid in self._cards:
                self._cards[pid].set_position(i, len(order))

    def reorder(self) -> None:
        """Reorders existing cards — without unmapping or rebuilding them."""
        order = [p for p, _s in self._order()]
        if set(self._cards) != set(order):
            self.render()
            return
        current = [c for c in self.list.pack_slaves() if isinstance(c, ProviderCard)]
        if [c.pid for c in current] != order:
            prev = None
            for pid in order:
                card = self._cards[pid]
                if prev is None:
                    card.pack_configure(before=current[0])
                else:
                    card.pack_configure(after=prev)
                prev = card
        self._renumber()
        self._shown = self._signature()

    def add_provider_card(self, pid: str) -> None:
        """Adds a new custom provider's card before the form, without rebuilding the page."""
        spec = self.app.cfg.spec(pid)
        if spec is None:
            return
        order = [p for p, _s in self._order()]
        card = ProviderCard(self.list, self.app, spec, order.index(pid), len(order))
        card.pack(fill="x", pady=6, padx=(0, 6), before=self.add_card)
        self._cards[pid] = card
        self._renumber()
        self.add_card.reset()
        self._shown = self._signature()

    def remove_provider_card(self, pid: str) -> None:
        card = self._cards.pop(pid, None)
        if card is not None:
            self._dispose(card)
        self._renumber()
        self._shown = self._signature()

    def warm(self) -> None:
        """Background prep: the page exists and cards are built in chunks."""

    def on_show(self) -> None:
        if getattr(self, "building", False):
            # The user opened the page before the cards finished building in the background:
            # build the rest right away.
            self.render()
            return
        if self._signature() == self._shown:
            return
        if [s[0] for s in self._signature()] != [s[0] for s in self._shown]:
            self.render()
            return
        # Only stats / keys of some providers changed — refresh just those.
        old = {s[0]: s for s in self._shown}
        for sig in self._signature():
            if old.get(sig[0]) != sig:
                self.refresh_card(sig[0])
