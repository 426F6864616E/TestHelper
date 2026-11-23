"""Info pages: the guide and About."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import customtkinter as ctk
from PIL import Image

from app import __author__, __version__, __app_name__
from app.paths import ASSETS_DIR, DATA_DIR, ICON_PNG
from app.ui import theme as T
from app.ui.theme import Fonts
from app.ui.widgets import Card, PageHeader, primary_button, secondary_button

if TYPE_CHECKING:
    from app.ui.app_window import MainWindow


class GuidePage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkFrame, app: "MainWindow") -> None:
        super().__init__(master, fg_color="transparent")
        t = app.i18n.t
        PageHeader(self, t("guide.title"), t("guide.subtitle")).pack(fill="x", pady=(0, 18))
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.SURFACE_ALT,
                                        scrollbar_button_hover_color=T.SURFACE_HOVER)
        scroll.pack(fill="both", expand=True)
        for step in app.i18n.raw("guide.steps") or []:
            card = Card(scroll)
            card.pack(fill="x", pady=6, padx=(0, 6))
            ctk.CTkLabel(card, text=step.get("title", ""), font=Fonts.h2(), text_color=T.TEXT,
                         anchor="w").pack(fill="x", padx=20, pady=(16, 4))
            ctk.CTkLabel(card, text=step.get("body", ""), font=Fonts.body(), text_color=T.TEXT_MUTED,
                         anchor="w", justify="left", wraplength=740).pack(fill="x", padx=20, pady=(0, 16))

    def on_show(self) -> None:
        pass


# Donation addresses. Checksums verified: BTC — bech32, ETH — EIP-55, SOL — 32-byte base58.
DONATE_WALLETS: tuple[tuple[str, str, str, str], ...] = (
    # (icon, coin, network, address)
    ("btc", "Bitcoin", "BTC", "bc1qqvkf8yd5et8c24d9zml0vhclzk9gqrp2tyhk8r"),
    ("eth", "Ethereum", "ETH · ERC-20", "0x1eDA3EfF5F89bFdFa1262E022a2Bc5653C7104Bb"),
    ("sol", "Solana", "SOL", "yGT8QCYvoxBEDhmjtC3x9i1qLN3u9NvbnL33f1YoqNJ"),
)
DONATE_DIR = ASSETS_DIR / "donate"


def _icon(name: str, size: int) -> ctk.CTkImage | None:
    path = DONATE_DIR / f"{name}.png"
    if not path.exists():
        return None
    img = Image.open(path)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


class AboutPage(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkFrame, app: "MainWindow") -> None:
        super().__init__(master, fg_color="transparent")
        t = app.i18n.t
        card = Card(self)
        card.pack(fill="both", expand=True)
        box = ctk.CTkFrame(card, fg_color="transparent")
        box.place(relx=0.5, rely=0.45, anchor="center")

        if ICON_PNG.exists():
            img = Image.open(ICON_PNG)
            self._logo = ctk.CTkImage(light_image=img, dark_image=img, size=(120, 120))
            ctk.CTkLabel(box, image=self._logo, text="").pack(pady=(0, 16))
        ctk.CTkLabel(box, text=__app_name__, font=Fonts.get(28, "bold"), text_color=T.TEXT).pack()
        version = ctk.CTkLabel(box, text=t("about.version", version=__version__), font=Fonts.body(),
                               text_color=T.ACCENT)
        version.pack(pady=(2, 0))
        version.bind("<Button-1>", app.eggs.version_clicked)  # click 7 times (・ω・)
        self._author = ctk.CTkLabel(box, text=t("about.author", author=__author__), font=Fonts.body(),
                                    text_color=T.TEXT_MUTED)
        self._author.pack(pady=(2, 14))
        self._author_prefix = t("about.author", author="")
        ctk.CTkLabel(box, text=t("about.description"), font=Fonts.body(), text_color=T.TEXT_MUTED,
                     wraplength=520, justify="center").pack()
        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(pady=(18, 0))
        secondary_button(buttons, t("about.open_folder"), lambda: os.startfile(DATA_DIR),  # type: ignore[attr-defined]
                         height=34).pack(side="left", padx=4)
        self._coffee = _icon("coffee", 18)
        primary_button(buttons, t("about.donate"), self._toggle_donate, height=34, image=self._coffee,
                       compound="left").pack(side="left", padx=4)

        self.app = app
        self._donate = self._build_donate(box)

    def _build_donate(self, master: ctk.CTkFrame) -> ctk.CTkFrame:
        """Address card: coin icon, name and network, full address, Copy button."""
        t = self.app.i18n.t
        panel = ctk.CTkFrame(master, fg_color=T.SURFACE_ALT, corner_radius=T.RADIUS_SM)
        ctk.CTkLabel(panel, text=t("about.donate_hint"), font=Fonts.small(), text_color=T.TEXT_MUTED,
                     wraplength=520, justify="center").pack(padx=16, pady=(12, 6))
        self._coin_icons = []
        for icon, coin, network, address in DONATE_WALLETS:
            row = ctk.CTkFrame(panel, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=4)
            image = _icon(icon, 28)
            self._coin_icons.append(image)
            ctk.CTkLabel(row, image=image, text="").pack(side="left", padx=(0, 10))
            names = ctk.CTkFrame(row, fg_color="transparent")
            names.pack(side="left")
            ctk.CTkLabel(names, text=coin, font=Fonts.body_bold(), text_color=T.TEXT, anchor="w",
                         height=16).pack(anchor="w")
            ctk.CTkLabel(names, text=network, font=Fonts.small(), text_color=T.TEXT_FAINT, anchor="w",
                         height=14).pack(anchor="w")
            secondary_button(row, t("about.copy"), lambda c=coin, a=address: self._copy(c, a), height=28,
                             width=90, fg_color=T.SURFACE).pack(side="right")
            ctk.CTkLabel(row, text=address, font=Fonts.mono(), text_color=T.TEXT_MUTED,
                         anchor="e").pack(side="right", padx=12)
        ctk.CTkLabel(panel, text=t("about.donate_note"), font=Fonts.small(), text_color=T.TEXT_FAINT,
                     wraplength=520, justify="center").pack(padx=16, pady=(6, 12))
        return panel

    def _toggle_donate(self) -> None:
        if self._donate.winfo_manager():
            self._donate.pack_forget()
        else:
            self._donate.pack(pady=(16, 0))

    def _copy(self, coin: str, address: str) -> None:
        self.app.copy_to_clipboard(address)
        self.app.toast.show(self.app.i18n.t("about.copied", coin=coin), "success")

    def on_show(self) -> None:
        # Sometimes Claude slides in and writes the nickname (see app/ui/eggs.py).
        self.app.eggs.maybe_sign(self._author, self._author_prefix, __author__)
