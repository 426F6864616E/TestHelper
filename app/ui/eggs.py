"""Easter eggs and a "living" UI (・ω・)ノ

Hidden (triggered by an action):
* 5 quick clicks on the sidebar logo — a random phrase;
* 7 clicks on the version on the About page — "developer mode";
* launching at night (00–05), on Friday, New Year or Halloween — a special greeting;
* About page: sometimes (≈ every third visit, at most once per 3 min) Claude ✻
  slides in, writes the developer's nickname letter by letter, waves and leaves.

"Living" UI: every 2.5–6 min, only while the window is open and idle,
one of these appears:
* a kaomoji in the empty part of the sidebar (blinks, looks around, falls asleep, waves; cat, bear…);
* a kaomoji peeking from behind the sidebar edge ┤･ω･)ﾉ;
* a tiny scene: someone walks across the sidebar, flips and restores a table, goes fishing;
* one tab's icon briefly turns into a face and blinks;
* the tagline under the title turns into a meme for 6 seconds;
* "dance break": all sidebar icons dance for a few seconds (rare);
* a meme toast — usually situational: about the last answer and its confidence,
  the number of scans, the open tab, time of day, Mondays.
"""
from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any, Callable

import customtkinter as ctk

from app.ui import theme as T
from app.ui.theme import Fonts

if TYPE_CHECKING:
    from app.ui.app_window import MainWindow

Frames = tuple[tuple[str, int], ...]  # (frame, duration in ms)

CLAUDE_COLOR = ("#C15F3C", "#D97757")  # Claude's signature orange

_DANCE_ICONS = ("(ﾉ◕ヮ◕)ﾉ", "ヽ(•‿•)ノ", "\\(^o^)/", "(☞ﾟ∀ﾟ)☞", "(≧▽≦)", "ᕕ( ᐛ )ᕗ")

_PEEKERS: tuple[Frames, ...] = (
    (("(•‿•)", 900), ("(-‿-)", 140), ("(•‿•)", 700), ("(-‿-)", 120), ("(•‿•)", 1000)),       # blinks
    (("(•_•)", 700), ("( •_•)", 600), ("(•_• )", 600), ("( •_•)", 500), ("(•‿•)", 1000)),    # looks around
    (("(・_・)", 700), ("(・‿・)", 600), ("(◕‿◕)", 900), ("(◕‿◕)ノ", 1300)),                  # smiles
    (("(－_－)", 800), ("(－_－) z", 600), ("(－_－) zZ", 600), ("(－_－) zZz", 900),
     ("(°o°)!", 700), ("(•_•)", 700)),                                                          # falls asleep
    (("=^･ω･^=", 1000), ("=^-ω-^=", 150), ("=^･ω･^=", 900), ("=^･ω･^= ♪", 1100)),           # cat
    (("ʕ•ᴥ•ʔ", 900), ("ʕ-ᴥ-ʔ", 150), ("ʕ•ᴥ•ʔ", 600), ("ʕ•ᴥ•ʔノ", 1200)),                     # bear
    (("(¬_¬)", 900), ("(¬‿¬)", 900), ("(¬‿¬)b", 1100)),                                       # sly
    (("(°ロ°)", 700), ("(°ロ°) !", 500), ("(°ロ°) !!", 500), ("( ˘▽˘)っ♨", 1300)),            # startled → tea
)
_WALL_PEEK: Frames = (("┤", 300), ("┤･", 220), ("┤･ω", 220), ("┤･ω･)", 900), ("┤･ω･)ﾉ", 1200),
                      ("┤･ω･)", 400), ("┤･ω", 180), ("┤･", 180), ("┤", 200))
_TABLE_FLIP: Frames = (("(°-°)  ┬─┬", 900), ("(°□°)  ┬─┬", 500), ("(╯°□°)╯︵ ┻━┻", 1300),
                       ("(・_・)   ┻━┻", 800), ("┬─┬ノ( º _ ºノ)", 1400))
_FISHING: Frames = (("( ´ー`)y-~~", 900), ("( ´ー`)y-~~  ><>", 900), ("( ´ー`)y-~~ ><>", 700),
                    ("(°ー°)y-~~><>", 500), ("(^ー^)y-><>  ✓", 1300))
_WALKERS = (("ᕕ( ᐛ )ᕗ", "ᕕ( ᐖ )ᕗ"), ("ε=ε=┌( >_<)┘", "ε=ε=└( >_<)┐"), ("(っ•́｡•́)♪", "(っ•̀｡•̀)♬"))
_NAV_FACES = ("◕‿◕", "•‿•", "^‿^", "°‿°", "ᵔ‿ᵔ")

# How often: first appearance 1–2.5 min after launch, then every 2.5–6 min.
_FIRST_DELAY = (60_000, 150_000)
_NEXT_DELAY = (150_000, 360_000)
_AMBIENT = {"peeker": 22, "wall": 12, "scene": 16, "nav": 10, "tagline": 10, "meme": 24, "dance": 6}

# Claude and the nickname: chance per About visit and minimum pause between appearances.
_SIGN_CHANCE = 0.35
_SIGN_COOLDOWN = 180.0


class EasterEggs:
    def __init__(self, app: "MainWindow") -> None:
        self.app = app
        self._started = time.time()
        self._logo_clicks: list[float] = []
        self._version_clicks = 0
        self._ambient_busy = False
        self._dancing = False
        self._last_sign = -_SIGN_COOLDOWN

    # ------------------------------------------------------------ helpers ---
    def _t(self, key: str, **kw: Any) -> str:
        return self.app.i18n.t(f"eggs.{key}", **kw)

    def _pick(self, key: str, **kw: Any) -> str:
        options = self.app.i18n.raw(f"eggs.{key}") or [key]
        text = random.choice(options) if isinstance(options, list) else str(options)
        try:
            return text.format(**kw) if kw else text
        except (KeyError, IndexError, ValueError):
            return text

    def _animate(self, frames: Frames, show: Callable[[str], bool], on_end: Callable[[], Any]) -> None:
        """Plays frames; show returns False if the widget is already destroyed."""
        self._ambient_busy = True

        def step(i: int) -> None:
            if i >= len(frames) or not show(frames[i][0]):
                on_end()
                self._ambient_busy = False
                return
            self.app.after(frames[i][1], lambda: step(i + 1))

        step(0)

    # -------------------------------------------------------------- logo ---
    def logo_clicked(self, _event: Any = None) -> None:
        now = time.monotonic()
        self._logo_clicks = [t for t in self._logo_clicks if now - t < 2.5] + [now]
        if len(self._logo_clicks) >= 5:
            self._logo_clicks.clear()
            self.app.toast.show(self._pick("logo"), ms=3200)

    # ----------------------------------------------------------- version ---
    def version_clicked(self, _event: Any = None) -> None:
        self._version_clicks += 1
        left = 7 - self._version_clicks
        if 0 < left <= 3:
            self.app.toast.show(self._t("dev_steps", count=left), ms=1200)
        elif left <= 0:
            self._version_clicks = 0
            self.app.toast.show(self._t("dev_done"), "success", ms=3600)

    # ------------------------------------------------------------ startup ---
    def on_start(self) -> None:
        now = time.localtime()
        day = (now.tm_mon, now.tm_mday)
        greeting = None
        if day >= (12, 25) or day <= (1, 2):
            greeting = "new_year"
        elif day == (10, 31):
            greeting = "halloween"
        elif now.tm_hour < 5:
            greeting = "night"
        elif now.tm_wday == 4 and random.random() < 0.5:
            greeting = "friday"
        if greeting:
            self.app.after(1200, lambda: self.app.toast.show(self._t(greeting), ms=4200))
        self._schedule(_FIRST_DELAY)

    # ------------------------------------------- Claude signs the developer ---
    def maybe_sign(self, label: ctk.CTkLabel, prefix: str, nickname: str, force: bool = False) -> None:
        """Sometimes Claude ✻ slides in and writes the developer's nickname letter by letter.

        label — the "Developer: …" label in a pack layout; prefix — "Developer: ", nickname — the nick.
        """
        now = time.monotonic()
        if not force and (self._ambient_busy or now - self._last_sign < _SIGN_COOLDOWN
                          or random.random() > _SIGN_CHANCE):
            return
        self._last_sign = now
        self._ambient_busy = True
        label.configure(text=prefix)
        claude = ctk.CTkLabel(label.master, text="", font=Fonts.body_bold(), text_color=CLAUDE_COLOR,
                              fg_color="transparent")

        def alive() -> bool:
            return label.winfo_exists() and claude.winfo_exists()

        def finish() -> None:
            if label.winfo_exists():
                label.configure(text=prefix + nickname)
            if claude.winfo_exists():
                claude.destroy()
            self._ambient_busy = False

        def at(x: int, text: str) -> None:
            claude.configure(text=text)
            claude.place(in_=label, relx=1.0, x=x, rely=0.5, anchor="w")

        # 1) slides in from the side
        slide_in = [(x, "✻(•‿•)") for x in (150, 120, 92, 66, 44, 26, 14, 8)]
        # 2) writes the nickname letter by letter
        # 3) admires it, waves
        # 4) slides back out
        slide_out = [(x, "✻(•‿•)") for x in (14, 30, 54, 84, 120, 160)]

        def run_slide(steps: list[tuple[int, str]], then: Callable[[], None]) -> None:
            def step(i: int) -> None:
                if not alive():
                    finish()
                    return
                if i >= len(steps):
                    then()
                    return
                at(*steps[i])
                self.app.after(45, lambda: step(i + 1))

            step(0)

        def write(i: int = 0) -> None:
            if not alive():
                finish()
                return
            if i > len(nickname):
                show_off()
                return
            label.configure(text=prefix + nickname[:i])
            at(8, "✻(•̀ᴗ•́)✎" if i % 2 == 0 else "✻(•̀ᴗ•́)✐")
            self.app.after(random.randint(90, 170), lambda: write(i + 1))

        def show_off() -> None:
            seq = [("✻(◕‿◕)", 700), ("✻(◕‿◕)ノ", 600), ("✻(◕‿◕)ﾉ", 500), ("✻(◕‿◕)ノ", 600)]

            def step(i: int) -> None:
                if not alive():
                    finish()
                    return
                if i >= len(seq):
                    run_slide(slide_out, finish)
                    return
                at(8, seq[i][0])
                self.app.after(seq[i][1], lambda: step(i + 1))

            step(0)

        self.app.after(350, lambda: run_slide(slide_in, lambda: self.app.after(250, write)))

    # ----------------------------------------------------- living UI ---
    def _schedule(self, delay: tuple[int, int]) -> None:
        self.app.after(random.randint(*delay), self._ambient_tick)

    def _can_show(self) -> bool:
        app = self.app
        return (not self._ambient_busy and not self._dancing and app.state() == "normal"
                and not app.scanner.busy
                and app.toast._job is None)  # noqa: SLF001 — don't interrupt real notifications

    def _ambient_tick(self) -> None:
        if self.app._closing:  # noqa: SLF001
            return
        try:
            if self._can_show():
                self.ambient()
        finally:
            self._schedule(_NEXT_DELAY)

    def ambient(self, kind: str | None = None) -> None:
        """One random "living" touch. kind can be set explicitly (for testing)."""
        kind = kind or random.choices(list(_AMBIENT), weights=list(_AMBIENT.values()))[0]
        getattr(self, f"_ambient_{kind}")()

    def _sidebar_label(self, color: Any) -> ctk.CTkLabel:
        return ctk.CTkLabel(self.app.sidebar, text="", font=Fonts.get(15), text_color=color,
                            fg_color="transparent")

    def _play_label(self, label: ctk.CTkLabel, frames: Frames) -> None:
        def show(text: str) -> bool:
            if not label.winfo_exists():
                return False
            label.configure(text=text)
            return True

        self._animate(frames, show, lambda: label.winfo_exists() and label.destroy())

    def _ambient_peeker(self) -> None:
        """A kaomoji in the empty part of the sidebar."""
        label = self._sidebar_label(T.TEXT_MUTED)
        label.place(relx=random.uniform(0.12, 0.5), rely=random.uniform(0.52, 0.74), anchor="w")
        self._play_label(label, random.choice(_PEEKERS))

    def _ambient_wall(self) -> None:
        """Peeks from behind the right edge of the sidebar: ┤･ω･)ﾉ"""
        label = self._sidebar_label(T.TEXT_MUTED)
        label.place(relx=1.0, x=-4, rely=random.uniform(0.5, 0.75), anchor="e")
        self._play_label(label, _WALL_PEEK)

    def _ambient_scene(self) -> None:
        """A tiny sidebar scene: walking across, flipping a table, or fishing."""
        choice = random.choice(("walk", "flip", "fish"))
        label = self._sidebar_label(T.TEXT_MUTED)
        if choice != "walk":
            label.place(relx=0.1, rely=random.uniform(0.55, 0.72), anchor="w")
            self._play_label(label, _TABLE_FLIP if choice == "flip" else _FISHING)
            return
        a, b = random.choice(_WALKERS)
        rely = random.uniform(0.55, 0.72)
        steps = 22
        self._ambient_busy = True

        def step(i: int) -> None:
            if not label.winfo_exists() or i > steps:
                if label.winfo_exists():
                    label.destroy()
                self._ambient_busy = False
                return
            label.configure(text=a if i % 2 else b)
            label.place(relx=-0.25 + 1.2 * i / steps, rely=rely, anchor="w")
            self.app.after(170, lambda: step(i + 1))

        step(0)

    def _ambient_nav(self) -> None:
        """One tab's icon briefly turns into a face and blinks."""
        btn = random.choice(list(self.app._nav.values()))  # noqa: SLF001
        original = btn.cget("text")
        name = original.strip().split(maxsplit=1)[-1]
        face = random.choice(_NAV_FACES)
        blink = "-" + face[1:-1] + "-"
        frames: Frames = ((face, 1100), (blink, 150), (face, 900), (blink, 130), (face, 900))

        def show(text: str) -> bool:
            if not btn.winfo_exists() or self._dancing:
                return False
            btn.configure(text=f"  {text}   {name}")
            return True

        def restore() -> None:
            if btn.winfo_exists() and not self._dancing:
                btn.configure(text=original)

        self._animate(frames, show, restore)

    def _ambient_tagline(self) -> None:
        """The tagline under the app name turns into a meme for 6 seconds."""
        tag = self.app.tagline_label
        original = tag.cget("text")
        self._animate(((self._pick("taglines"), 6000),),
                      lambda text: bool(tag.winfo_exists()) and (tag.configure(text=text) or True),
                      lambda: tag.winfo_exists() and tag.configure(text=original))

    def _ambient_dance(self) -> None:
        """Dance break: sidebar icons dance for a few seconds."""
        self._dancing = True
        self.app.toast.show(self._pick("dance"), "success", ms=3600)
        buttons = list(self.app._nav.values())  # noqa: SLF001
        originals = [b.cget("text") for b in buttons]

        def tick(i: int) -> None:
            alive = all(b.winfo_exists() for b in buttons)
            if not alive or i >= 14:
                if alive:
                    for b, text in zip(buttons, originals):
                        b.configure(text=text)
                self._dancing = False
                return
            for n, (b, text) in enumerate(zip(buttons, originals)):
                label = text.strip().split(maxsplit=1)[-1]
                b.configure(text=f"  {_DANCE_ICONS[(i + n) % len(_DANCE_ICONS)]}   {label}")
            self.app.after(260, lambda: tick(i + 1))

        tick(0)

    # ---------------------------------------------------------------- memes ---
    def _context_memes(self) -> list[str]:
        """Memes that depend on what is happening in the app right now."""
        app = self.app
        out: list[str] = []
        items = app.history.items()
        session = [r for r in items if r.timestamp >= self._started]
        if items:
            last = items[0]
            if not last.ok:
                out.append(self._pick("ctx.last_error"))
            elif last.confidence < 55:
                out.append(self._pick("ctx.low_conf", c=last.confidence))
            elif last.confidence >= 95:
                out.append(self._pick("ctx.high_conf", c=last.confidence))
            if last.ok and last.provider:
                out.append(self._pick("ctx.provider", p=last.provider))
        if len(session) >= 8:
            out.append(self._pick("ctx.many_scans", n=len(session)))
        if not items:
            out.append(self._pick("ctx.no_history"))
        page = app._current  # noqa: SLF001
        if app.i18n.raw(f"eggs.ctx.page.{page}"):
            out.append(self._pick(f"ctx.page.{page}"))
        hour = time.localtime().tm_hour
        if 6 <= hour < 10:
            out.append(self._pick("ctx.morning"))
        elif hour >= 22:
            out.append(self._pick("ctx.late"))
        if time.localtime().tm_wday == 0:
            out.append(self._pick("ctx.monday"))
        return out

    def _ambient_meme(self) -> None:
        context = self._context_memes()
        text = random.choice(context) if context and random.random() < 0.65 else self._pick("memes")
        self.app.toast.show(text, ms=4600)
