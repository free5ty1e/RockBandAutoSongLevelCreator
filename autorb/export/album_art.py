#!/usr/bin/env python
"""Default generic album art for AutoRB customs ('Chris Prime Custom')."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def build_default_album_art(size: int = 256) -> Image.Image:
    """Draws the generic 'Chris Prime Custom' album art at ``size`` x ``size``."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # Diagonal charcoal gradient
    for y in range(size):
        t = y / max(1, size - 1)
        r = int(20 + 20 * t)
        g = int(22 + 22 * t)
        b = int(26 + 24 * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    # Subtle radial glow behind the text
    cx = cy = size // 2
    radius = int(size * 0.45)
    glow = Image.new("L", (size, size), 0)
    gd = ImageDraw.Draw(glow)
    for rr in range(radius, 0, -8):
        a = int(60 * (1 - rr / radius))
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=a)
    img = Image.alpha_composite(img, Image.merge("RGBA", (glow, glow, glow, glow)))

    draw = ImageDraw.Draw(img)

    # Thin border frame
    m = max(6, size // 32)
    draw.rectangle([m, m, size - m, size - m], outline=(255, 255, 255, 60), width=max(2, size // 96))

    # Equalizer bars motif
    bars = [0.3, 0.7, 0.45, 0.9, 0.55, 0.75, 0.35, 0.85, 0.5, 0.65, 0.4, 0.8]
    bar_w = max(3, size // 42)
    gap = max(2, size // 64)
    total_w = len(bars) * bar_w + (len(bars) - 1) * gap
    x0 = (size - total_w) // 2
    bar_base = int(size * 0.78)
    for i, hfrac in enumerate(bars):
        bh = int(size * 0.10 * hfrac)
        draw.rectangle(
            [x0 + i * (bar_w + gap), bar_base - bh, x0 + i * (bar_w + gap) + bar_w, bar_base],
            fill=(255, 150, 0, 235),
        )

    # Title text
    title_font = _font(_FONT_BOLD, max(14, size // 7))
    sub_font = _font(_FONT_BOLD, max(10, size // 10))
    tag_font = _font(_FONT_REGULAR, max(8, size // 18))
    badge_font = _font(_FONT_BOLD, max(9, size // 16))

    def _center_text(d, text, font, y, fill):
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        d.text(((size - tw) / 2 - bbox[0], y), text, font=font, fill=fill)

    _center_text(draw, "CHRIS", title_font, int(size * 0.12), (255, 255, 255, 255))
    _center_text(draw, "PRIME", title_font, int(size * 0.24), (255, 255, 255, 255))
    _center_text(draw, "CUSTOM", sub_font, int(size * 0.36), (255, 150, 0, 255))
    _center_text(draw, "rock band custom song", tag_font, int(size * 0.84), (200, 200, 200, 255))

    # "BOT" badge in the top-right corner so songlists show this was script-made
    badge_w = int(size * 0.16)
    badge_h = int(size * 0.07)
    bx = size - m - badge_w - 4
    by = m + 4
    draw.rounded_rectangle(
        [bx, by, bx + badge_w, by + badge_h],
        radius=max(3, badge_h // 3),
        fill=(255, 150, 0, 255),
        outline=(255, 255, 255, 220),
        width=1,
    )
    bbox = draw.textbbox((0, 0), "BOT", font=badge_font)
    draw.text(
        (bx + (badge_w - (bbox[2] - bbox[0])) / 2 - bbox[0], by + (badge_h - (bbox[3] - bbox[1])) / 2 - bbox[1]),
        "BOT",
        font=badge_font,
        fill=(20, 20, 20, 255),
    )

    # Flatten onto an opaque black canvas so the texture encodes as DXT1
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    return Image.alpha_composite(bg, img).convert("RGBA")
