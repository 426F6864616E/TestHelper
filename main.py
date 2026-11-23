"""TestHelper entry point."""
from __future__ import annotations

import logging
import sys

from app import __app_name__, __version__
from app.ai import AIRouter
from app.browser import BrowserBridge
from app.core.config import ConfigManager
from app.core.history import HistoryStore
from app.core.scanner import ScanService
from app.i18n import I18n
from app.logging_setup import setup_logging
from app.paths import BROWSER_PROFILE_DIR, CONFIG_FILE, HISTORY_FILE, LOCALES_DIR

log = logging.getLogger("main")


def _single_instance() -> object | None:
    """Prevents running two copies of the app (Windows named mutex)."""
    if sys.platform != "win32":
        return object()
    import ctypes

    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\TestHelper.SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def main() -> int:
    setup_logging()
    log.info("Starting %s %s", __app_name__, __version__)

    lock = _single_instance()
    if lock is None:
        log.warning("Another instance is already running")
        return 0

    config = ConfigManager(CONFIG_FILE)
    s = config.settings
    i18n = I18n(LOCALES_DIR, s.language)
    router = AIRouter(config.provider_plans)
    browser = BrowserBridge(s.browser_port, BROWSER_PROFILE_DIR, s.browser_path)
    scanner = ScanService(config, browser, router, i18n)
    history = HistoryStore(HISTORY_FILE)

    from app.ui.app_window import MainWindow  # import Tk only after logging is set up

    window = MainWindow(config, i18n, router, browser, scanner, history)
    try:
        window.mainloop()
    except KeyboardInterrupt:
        window.quit_app()
    return 0


if __name__ == "__main__":
    sys.exit(main())
