"""Design tokens: colors (light, dark), typography, spacing."""
from __future__ import annotations

import customtkinter as ctk

# Each color is a (light, dark) pair; CustomTkinter picks the right one.
BG = ("#F4F5F9", "#0E1014")
SIDEBAR = ("#FFFFFF", "#13161C")
SURFACE = ("#FFFFFF", "#181B22")
SURFACE_ALT = ("#EEF0F5", "#1F232C")
SURFACE_HOVER = ("#E4E7EE", "#262B35")
BORDER = ("#E2E5EC", "#262A33")

TEXT = ("#12141A", "#E9EBF1")
TEXT_MUTED = ("#646B7B", "#8A92A6")
TEXT_FAINT = ("#9AA0AE", "#5C6375")

ACCENT = ("#5B4DF5", "#7C6CFF")
ACCENT_HOVER = ("#4A3CE0", "#6A59F5")
ACCENT_SOFT = ("#ECEAFE", "#221F3D")
ON_ACCENT = ("#FFFFFF", "#FFFFFF")

SUCCESS = ("#14955A", "#34D399")
SUCCESS_SOFT = ("#E3F6EC", "#12291F")
WARNING = ("#B7791F", "#FBBF24")
WARNING_SOFT = ("#FDF3E1", "#2C2413")
DANGER = ("#D63A3A", "#F87171")
DANGER_SOFT = ("#FDE8E8", "#2E1719")

RADIUS = 14
RADIUS_SM = 9
PAD = 24

FONT_FAMILY = "Segoe UI"  # fallback when Segoe UI Variable is missing (Windows 10)
MONO_FAMILY = "Cascadia Mono"

# Segoe UI Variable (Windows 11) has separate optical sizes: Display for headings,
# Text for body text, Small for fine print. Each is drawn for its own size,
# so text looks cleaner. Bold is replaced with Semibold — lighter
# and more modern. Tk sees each face as a separate family (names truncated to 31 chars).
_VARIABLE = {
    # optical size: (regular, semibold)
    "display": ("Segoe UI Variable Display", "Segoe UI Variable Display Semib"),
    "text": ("Segoe UI Variable Text", "Segoe UI Variable Text Semibold"),
    "small": ("Segoe UI Variable Small", "Segoe UI Variable Small Semibol"),
}
_FALLBACK = ("Segoe UI", "Segoe UI Semibold")
_MONO_FALLBACKS = (MONO_FAMILY, "Cascadia Code", "Consolas", "Courier New")


class Fonts:
    """Fonts are created after Tk initializes, hence lazily."""

    _cache: dict[tuple, ctk.CTkFont] = {}
    _families: set[str] | None = None

    @classmethod
    def _installed(cls) -> set[str]:
        if cls._families is None:
            import tkinter.font as tkfont

            cls._families = set(tkfont.families())
        return cls._families

    @classmethod
    def _resolve(cls, size: int, weight: str) -> tuple[str, str]:
        """Picks a face for the size and weight. Returns (family, weight for Tk)."""
        cut = "display" if size >= 20 else "small" if size <= 11 else "text"
        regular, semibold = _VARIABLE[cut]
        installed = cls._installed()
        if weight == "bold":
            if semibold in installed:
                return semibold, "normal"
            if _FALLBACK[1] in installed:
                return _FALLBACK[1], "normal"
            return _FALLBACK[0], "bold"
        return (regular if regular in installed else _FALLBACK[0]), weight

    @classmethod
    def get(cls, size: int, weight: str = "normal", family: str | None = None) -> ctk.CTkFont:
        key = (size, weight, family)
        if key not in cls._cache:
            if family is None:
                fam, w = cls._resolve(size, weight)
            else:
                fam, w = family, weight
            cls._cache[key] = ctk.CTkFont(family=fam, size=size, weight=w)
        return cls._cache[key]

    @classmethod
    def display(cls) -> ctk.CTkFont:
        return cls.get(44, "bold")

    @classmethod
    def h1(cls) -> ctk.CTkFont:
        return cls.get(26, "bold")

    @classmethod
    def h2(cls) -> ctk.CTkFont:
        return cls.get(16, "bold")

    @classmethod
    def body(cls) -> ctk.CTkFont:
        return cls.get(13)

    @classmethod
    def body_bold(cls) -> ctk.CTkFont:
        return cls.get(13, "bold")

    @classmethod
    def small(cls) -> ctk.CTkFont:
        return cls.get(11)

    @classmethod
    def mono(cls) -> ctk.CTkFont:
        family = next((f for f in _MONO_FALLBACKS if f in cls._installed()), "Courier New")
        return cls.get(12, family=family)


def confidence_color(value: int) -> tuple[str, str]:
    if value >= 75:
        return SUCCESS
    if value >= 45:
        return WARNING
    return DANGER
