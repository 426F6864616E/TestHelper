"""Main window: sidebar navigation, pages, background task dispatch."""
from __future__ import annotations

import ctypes
import logging
import queue
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import customtkinter as ctk
from PIL import Image

from app import __app_name__, __version__
from app.ai import AIRouter
from app.browser import BrowserBridge, BrowserError
from app.core.config import ConfigManager
from app.core.history import HistoryStore
from app.core.models import ScanResult
from app.core.scanner import ScanService
from app.i18n import I18n
from app.paths import ICON_ICO, ICON_PNG
from app.ui import theme as T
from app.ui.pages.history import HistoryPage
from app.ui.pages.info import AboutPage, GuidePage
from app.ui.pages.providers import ProvidersPage
from app.ui.pages.scan import ScanPage
from app.ui.pages.settings import SettingsPage
from app.ui.eggs import EasterEggs
from app.ui.freeze import FreezeFrame
from app.ui.theme import Fonts
from app.ui.tray import TrayIcon
from app.ui.widgets import StatusDot, Toast

log = logging.getLogger(__name__)

# How long to keep the old page's freeze frame while the new one paints underneath.
_COVER_MS = 100


NAV_ITEMS: tuple[tuple[str, str, type], ...] = (
    ("scan", "⚡", ScanPage),
    ("history", "🕘", HistoryPage),
    ("providers", "🔑", ProvidersPage),
    ("settings", "⚙", SettingsPage),
    ("guide", "📖", GuidePage),
    ("about", "ℹ", AboutPage),
)


class MainWindow(ctk.CTk):
    def __init__(self, config: ConfigManager, i18n: I18n, router: AIRouter, browser: BrowserBridge,
                 scanner: ScanService, history: HistoryStore) -> None:
        ctk.set_appearance_mode(config.settings.theme)
        super().__init__(fg_color=T.BG)
        self.cfg = config
        self.i18n = i18n
        self.router = router
        self.browser = browser
        self.scanner = scanner
        self.history = history

        self._tasks: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="worker")
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._nav: dict[str, ctk.CTkButton] = {}
        self._current = "scan"
        self._shown_page: ctk.CTkFrame | None = None
        self._warm: set[str] = set()  # pages that have been laid out at full size at least once
        self._launching = False  # browser is launching — don't let status polling override the button
        self._closing = False

        self._setup_window()
        self.toast = Toast(self)
        self.freeze = FreezeFrame(self)  # freeze frame while switching tabs
        self.eggs = EasterEggs(self)
        self._build()
        self.tray = TrayIcon(i18n, on_scan=lambda: self.post(self.request_scan),
                             on_show=lambda: self.post(self.show_window),
                             on_exit=lambda: self.post(self.quit_app))
        self.tray.start()

        self.bind_all("<F8>", lambda _e: self.request_scan())
        self.bind_all("<Control-Return>", lambda _e: self.request_scan())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Back in the window (taskbar, Alt+Tab) — the answer was seen, tray goes purple again.
        self.bind("<FocusIn>", lambda e: self.tray.reset() if e.widget is self else None, add="+")
        self.after(40, self._drain)
        self.after(300, self._poll_status)
        self.after(400, self._prebuild_pages)
        self.eggs.on_start()

    # ------------------------------------------------------------ setup ---
    def _setup_window(self) -> None:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("testhelper.app.1")
        except (AttributeError, OSError):
            pass
        self.title(__app_name__)
        self.geometry("1120x740")
        self.minsize(940, 620)
        if ICON_ICO.exists():
            self.after(200, lambda: self.iconbitmap(str(ICON_ICO)))
        self.attributes("-topmost", self.cfg.settings.always_on_top)

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=T.PAD + 4, pady=T.PAD)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.navigate(self._current)
        self.refresh_status()

    def _build_sidebar(self) -> None:
        t = self.i18n.t
        bar = ctk.CTkFrame(self, width=236, corner_radius=0, fg_color=T.SIDEBAR,
                           border_width=0)
        bar.grid(row=0, column=0, sticky="nsew")
        bar.grid_propagate(False)
        bar.pack_propagate(False)
        self.sidebar = bar

        brand = ctk.CTkFrame(bar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(24, 26))
        if ICON_PNG.exists():
            img = Image.open(ICON_PNG)
            self._brand_img = ctk.CTkImage(light_image=img, dark_image=img, size=(36, 36))
            logo = ctk.CTkLabel(brand, image=self._brand_img, text="")
            logo.pack(side="left", padx=(0, 10))
            logo.bind("<Button-1>", self.eggs.logo_clicked)
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left")
        ctk.CTkLabel(names, text="TestHelper", font=Fonts.get(17, "bold"), text_color=T.TEXT,
                     anchor="w").pack(anchor="w")
        self.tagline_label = ctk.CTkLabel(names, text=t("app.tagline"), font=Fonts.small(),
                                          text_color=T.TEXT_MUTED, anchor="w")
        self.tagline_label.pack(anchor="w")

        self._nav.clear()
        for key, icon, _cls in NAV_ITEMS:
            btn = ctk.CTkButton(
                bar, text=f"  {icon}   {t(f'nav.{key}')}", anchor="w", height=40, corner_radius=T.RADIUS_SM,
                font=Fonts.body(), fg_color="transparent", hover_color=T.SURFACE_HOVER,
                text_color=T.TEXT_MUTED, command=lambda k=key: self.navigate(k),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._nav[key] = btn

        footer = ctk.CTkFrame(bar, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=20, pady=20)
        self.browser_status = StatusDot(footer)
        self.browser_status.pack(fill="x", pady=2)
        self.keys_status = StatusDot(footer)
        self.keys_status.pack(fill="x", pady=2)
        ctk.CTkLabel(footer, text=f"v{__version__}", font=Fonts.small(), text_color=T.TEXT_FAINT,
                     anchor="w").pack(fill="x", pady=(10, 0))

    # -------------------------------------------------------- navigation ---
    def navigate(self, key: str) -> None:
        previous = self._current
        self._current = key
        # Repaint only the two buttons whose state changed, not all of them.
        for k in {previous, key}:
            btn = self._nav.get(k)
            if btn is not None:
                active = k == key
                btn.configure(fg_color=T.ACCENT_SOFT if active else "transparent",
                              text_color=T.ACCENT if active else T.TEXT_MUTED,
                              font=Fonts.body_bold() if active else Fonts.body())
        page = self._page(key)
        if hasattr(page, "on_show"):
            page.on_show()  # refresh content before showing so repainting isn't visible
        if self._shown_page is page:
            return
        # Pages are stacked; only the top one is visible.
        # Tk paints a new page widget by widget, which shows up as torn frames.
        # So during the switch we put a freeze frame of the old page over the page area
        # (a separate borderless window) and the new page paints underneath. Once everything
        # is painted the freeze frame is removed — the new page appears whole at once.
        slow = key not in self._warm
        if slow:
            self.configure(cursor="watch")  # first opening of a page that isn't warmed up yet
        covered = self.state() == "normal" and self._shown_page is not None and self.freeze.cover(self.content)
        # All pages are already stacked in one grid cell — just raise the one we need.
        # Re-laying out (grid/grid_remove) makes CustomTkinter repaint every
        # widget (~300 ms on "AI providers"), while raising only repaints what's visible.
        page.tkraise()
        self._shown_page = page
        self._warm.add(key)
        self.update_idletasks()
        if slow:
            self.configure(cursor="")
        if covered:
            # let Windows process the repaint and only then remove the freeze frame
            self.freeze.release(_COVER_MS)

    def _prebuild_pages(self, pending: list[str] | None = None) -> None:
        """After startup, builds and warms up the remaining pages one by one so first opening is instant.

        A page's first show is slow (200–450 ms): Tk lays it out at real size for the first time
        and CustomTkinter paints every widget. So each page is briefly laid out once
        under the current one (invisible), allowed to paint, and removed again.
        After that, switching takes 20–80 ms.
        """
        if pending is None:
            # Light pages first, the heaviest ("AI providers") last.
            pending = [k for k, _i, _c in NAV_ITEMS if k != "providers"] + ["providers"]
        while pending and pending[0] in self._warm:
            pending.pop(0)
        if self._closing or not pending:
            return
        key = pending.pop(0)
        page = self._page(key)
        if page is not self._shown_page:
            if hasattr(page, "warm"):
                page.warm()  # type: ignore[attr-defined]
            self.update_idletasks()
        self._warm.add(key)
        self.after(60, lambda: self._prebuild_pages(pending))

    def _rebuild(self) -> None:
        for page in self._pages.values():
            page.destroy()
        self._pages.clear()
        self._warm.clear()
        self._shown_page = None
        self.sidebar.destroy()
        self.content.destroy()
        self._build()
        self.after(200, self._prebuild_pages)  # warm up the pages again in the new language

    # ---------------------------------------------------------- threading ---
    def post(self, fn: Callable[[], None]) -> None:
        """Thread-safely queues a call onto the main Tk thread."""
        self._tasks.put(fn)

    def _drain(self) -> None:
        try:
            while True:
                fn = self._tasks.get_nowait()
                try:
                    fn()
                except Exception:  # noqa: BLE001 — a UI error must not kill the loop
                    log.exception("UI task failed")
        except queue.Empty:
            pass
        if not self._closing:
            self.after(40, self._drain)

    def run_background(self, work: Callable[[], Any], on_done: Callable[[Any], None] | None = None) -> None:
        def task() -> None:
            try:
                result = work()
            except Exception:  # noqa: BLE001
                log.exception("Background task failed")
                return
            if on_done:
                self.post(lambda: on_done(result))

        self._pool.submit(task)

    # ------------------------------------------------------------- scan ---
    def request_scan(self) -> None:
        if self.scanner.busy:
            return
        t = self.i18n.t
        if self.state() != "withdrawn":
            self.navigate("scan")
        scan_page: ScanPage = self._page("scan")  # type: ignore[assignment]
        scan_page.show_busy(t("progress.reading_page"))
        self.tray.set_state("working", t("tray.processing"))

        def progress(msg: str) -> None:
            self.post(lambda: scan_page.show_busy(msg) if scan_page.winfo_exists() else None)

        def work() -> ScanResult | None:
            # An unexpected exception must not leave the "Analyzing…" button stuck forever:
            # return None and _on_scan_done restores the UI.
            try:
                return self.scanner.scan(progress)
            except Exception:  # noqa: BLE001
                log.exception("Scan crashed")
                return None

        self.run_background(work, self._on_scan_done)

    def _on_scan_done(self, result: ScanResult | None) -> None:
        if result is None:  # unexpected error in the background thread (already logged)
            self.tray.set_state("error")
            page = self._pages.get("scan")
            if page is not None:
                page.show_empty()  # type: ignore[attr-defined]
                page.scan_btn.configure(state="normal",  # type: ignore[attr-defined]
                                        text=f"⚡  {self.i18n.t('scan.button')}")
            return
        self.history.add(result)
        if "history" in self._pages:
            self._pages["history"].mark_dirty()  # type: ignore[attr-defined]
        page: ScanPage = self._page("scan")  # type: ignore[assignment]
        page.show_result(result)
        self.tray.set_state("ready" if result.ok else "error", f"{__app_name__}: {result.short}")
        if self.cfg.settings.notifications and not self._has_focus():
            self.tray.notify(result.short)
        self.refresh_status()

    def _has_focus(self) -> bool:
        if self.state() in ("withdrawn", "iconic"):
            return False
        try:
            return self.focus_get() is not None
        except KeyError:  # focus is in a system dialog
            return True

    def _page(self, key: str) -> ctk.CTkFrame:
        """Returns a page, creating it lazily on first access."""
        page = self._pages.get(key)
        if page is None:
            cls = next(c for k, _i, c in NAV_ITEMS if k == key)
            page = cls(self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            # Under the current page (not under everything: content has a background canvas that would hide it).
            if self._shown_page is not None:
                page.lower(self._shown_page)
            self._pages[key] = page
        return page

    # ---------------------------------------------------------- actions ---
    def launch_browser(self) -> None:
        t = self.i18n.t
        scan_page = self._pages.get("scan")
        if self._launching:
            return
        self._launching = True
        if scan_page is not None:
            scan_page.set_browser_state("launching")  # type: ignore[attr-defined]

        def work() -> str:
            try:
                self.browser.launch()
                return ""
            except BrowserError as exc:
                return t(f"errors.browser.{exc.code}")

        def done(err: str) -> None:
            self._launching = False
            self.toast.show(err or t("settings.launched"), "error" if err else "success", ms=4000 if err else 2400)
            self.refresh_status()

        self.run_background(work, done)

    def add_key(self, provider_id: str, key: str) -> None:
        t = self.i18n.t
        if self.cfg.add_key(provider_id, key):
            self.toast.show(t("providers.key_added"), "success")
        else:
            self.toast.show(t("providers.key_exists"))
        self._refresh_providers(provider_id)

    def remove_key(self, provider_id: str, key: str) -> None:
        self.cfg.remove_key(provider_id, key)
        self._refresh_providers(provider_id)

    def add_model(self, provider_id: str, model: str) -> None:
        t = self.i18n.t
        if self.cfg.add_model(provider_id, model):
            self.toast.show(t("providers.model_added", model=model), "success")
        else:
            self.toast.show(t("providers.model_exists"))
        self._refresh_providers(provider_id, "models")

    def remove_model(self, provider_id: str, model: str) -> None:
        self.cfg.remove_model(provider_id, model)
        self._refresh_providers(provider_id, "models")

    def move_provider(self, provider_id: str, delta: int) -> None:
        self.cfg.move_provider(provider_id, delta)
        page = self._pages.get("providers")
        if page:
            page.reorder()  # type: ignore[attr-defined]

    def add_custom_provider(self, name: str, base_url: str, vision: bool, key: str, models: list[str]) -> None:
        pid = self.cfg.add_custom_provider(name, base_url, vision, key, models)
        self.toast.show(self.i18n.t("providers.provider_added", name=name), "success")
        page = self._pages.get("providers")
        if page:
            page.add_provider_card(pid)  # type: ignore[attr-defined]
        self.refresh_status()

    def remove_custom_provider(self, provider_id: str) -> None:
        self.cfg.remove_custom_provider(provider_id)
        self.router.forget(provider_id)
        page = self._pages.get("providers")
        if page:
            page.remove_provider_card(provider_id)  # type: ignore[attr-defined]
        self.refresh_status()

    def _refresh_providers(self, provider_id: str | None = None, part: str = "keys") -> None:
        """Refreshes the providers page: part of one card, or (pid=None) the whole page."""
        page = self._pages.get("providers")
        if page:
            if provider_id:
                page.refresh_part(provider_id, part)  # type: ignore[attr-defined]
            else:
                page.render()  # type: ignore[attr-defined]
        self.refresh_status()

    def set_language(self, lang: str) -> None:
        self.cfg.update(language=lang)
        self.i18n.set_language(lang)
        self._current = "settings"
        self._rebuild()

    def set_theme(self, theme: str) -> None:
        self.cfg.update(theme=theme)
        ctk.set_appearance_mode(theme)

    def set_always_on_top(self, value: bool) -> None:
        self.cfg.update(always_on_top=value)
        self.attributes("-topmost", value)

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    # ----------------------------------------------------------- status ---
    def refresh_status(self) -> None:
        t = self.i18n.t
        keys = self.cfg.total_keys()
        if keys:
            self.keys_status.set(t("status.keys", count=keys), T.SUCCESS)
        else:
            self.keys_status.set(t("status.no_keys"), T.DANGER)

        def done(running: bool) -> None:
            if self.browser_status.winfo_exists():
                self.browser_status.set(t("status.browser_on") if running else t("status.browser_off"),
                                        T.SUCCESS if running else T.TEXT_FAINT)
            scan_page = self._pages.get("scan")
            if scan_page is not None and scan_page.winfo_exists() and not self._launching:
                scan_page.set_browser_state("on" if running else "off")  # type: ignore[attr-defined]

        self.run_background(self.browser.is_running, done)

    def _poll_status(self) -> None:
        if self._closing:
            return
        if self.state() != "withdrawn":
            self.refresh_status()
        self.after(4000, self._poll_status)

    # -------------------------------------------------------- lifecycle ---
    def show_window(self) -> None:
        self.tray.reset()  # the answer was seen — icon is purple again
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_close(self) -> None:
        if self.cfg.settings.close_to_tray:
            self.withdraw()
        else:
            self.quit_app()

    def quit_app(self) -> None:
        if self._closing:
            return
        self._closing = True
        log.info("Shutting down")
        self.tray.stop()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.router.close()
        self.browser.close()
        self.quit()
        self.destroy()
