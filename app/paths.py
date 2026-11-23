"""Central paths to the app's resources and data.

Supports both running from source and a PyInstaller build (sys._MEIPASS).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _resource_root() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent.parent


def _data_root() -> Path:
    # The built .exe usually lives in Program Files, which is not writable,
    # so data goes to %APPDATA%\TestHelper. Portable mode: a file named
    # "portable" next to the .exe — then data is stored next to it.
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "portable").exists():
            return exe_dir
        appdata = os.environ.get("APPDATA")
        root = Path(appdata) / "TestHelper" if appdata else exe_dir
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(__file__).resolve().parent.parent


RESOURCE_DIR = _resource_root()
DATA_DIR = _data_root()

ASSETS_DIR = RESOURCE_DIR / "assets"
LOCALES_DIR = RESOURCE_DIR / "locales"
ICON_PNG = ASSETS_DIR / "icon.png"
ICON_ICO = ASSETS_DIR / "icon.ico"

CONFIG_FILE = DATA_DIR / "config.json"
HISTORY_FILE = DATA_DIR / "history.json"
LOG_DIR = DATA_DIR / "logs"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"
