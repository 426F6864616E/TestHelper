"""Generates installer/setup.ico: the app icon + a green "install" arrow badge.

Usage:  python installer/make_setup_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "icon.png"
OUT = ROOT / "installer" / "setup.ico"

S = 1024  # draw large, then scale down


def badge_layer(scale: float) -> Image.Image:
    """Badge in the bottom-right corner; scale is a fraction of the icon side."""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = int(S * scale / 2)
    cx, cy = S - r - 4, S - r - 4
    ring = max(int(r * 0.14), 8)
    # white ring to separate the badge from the purple background
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255))
    ri = r - ring
    d.ellipse((cx - ri, cy - ri, cx + ri, cy + ri), fill=(22, 163, 74, 255))
    # down arrow
    w = int(ri * 0.22)  # line width
    top, tip = cy - int(ri * 0.55), cy + int(ri * 0.22)
    d.line((cx, top, cx, tip - w // 2), fill="white", width=w)
    head = int(ri * 0.42)
    d.polygon([(cx - head, tip - head), (cx + head, tip - head), (cx, tip + w // 2)], fill="white")
    # tray under the arrow
    ty = cy + int(ri * 0.55)
    d.rounded_rectangle((cx - int(ri * 0.55), ty - w // 2, cx + int(ri * 0.55), ty + w // 2),
                        radius=w // 2, fill="white")
    return layer


def render(size: int) -> Image.Image:
    base = Image.open(SRC).convert("RGBA").resize((S, S), Image.LANCZOS)
    # bigger badge at small sizes, otherwise it's invisible
    scale = 0.62 if size <= 24 else 0.56 if size <= 48 else 0.5
    out = Image.alpha_composite(base, badge_layer(scale))
    return out.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    imgs = [render(s) for s in sizes]
    imgs[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=imgs[:-1])
    render(256).save(OUT.with_suffix(".png"))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
