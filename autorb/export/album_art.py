#!/usr/bin/env python
"""Default generic album art for AutoRB customs ('Chris Prime Custom')."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Fonts are bundled with the package (autorb/export/data/fonts) so the art
# renders identically on any OS regardless of system font paths. On Linux the
# same DejaVu fonts are also commonly installed system-wide, but we never rely
# on that — the bundled copy is the source of truth.
_DATA_DIR = Path(__file__).parent / "data" / "fonts"
_FONT_BOLD = _DATA_DIR / "DejaVuSans-Bold.ttf"
_FONT_REGULAR = _DATA_DIR / "DejaVuSans.ttf"

# Fallback search paths for systems where the bundled font is unavailable
# (e.g. a loose-source checkout missing package data).
_OS_FONT_CANDIDATES = [
    # macOS (Homebrew / Framework font dirs)
    "/opt/homebrew/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/local/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    # Linux (Debian/Ubuntu + others)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
_OS_FONT_REGULAR_CANDIDATES = [
    "/opt/homebrew/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/local/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _resolve_font(bundled: Path, os_candidates: list[str]) -> Path | None:
    if bundled.is_file():
        return bundled
    for candidate in os_candidates:
        if Path(candidate).is_file():
            return Path(candidate)
    return None


def _load_font(bundled: Path, os_candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    """Load a TrueType font, preferring the bundled copy, then known OS paths.

    Falls back to Pillow's built-in scalable default (``load_default(size=)``,
    Pillow >= 10.1) so text is still legible even if no TTF can be found.
    """
    resolved = _resolve_font(bundled, os_candidates)
    if resolved is not None:
        return ImageFont.truetype(str(resolved), size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has no size arg
        return ImageFont.load_default()


def _font_bold(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(_FONT_BOLD, _OS_FONT_CANDIDATES, size)


def _font_regular(size: int) -> ImageFont.FreeTypeFont:
    return _load_font(_FONT_REGULAR, _OS_FONT_REGULAR_CANDIDATES, size)


def _draw_cp_logo(draw: ImageDraw.ImageDraw, size: int, margin: int) -> None:
    """Draws a 'CP' monogram in the top-left corner: a thick C forming the outer
    circle (open on the right), with a P inscribed inside."""
    logo_d = max(14, int(size * 0.14))
    logo_cx = margin + logo_d // 2 + 2
    logo_cy = margin + logo_d // 2 + 2

    # Thick 'C' that forms the outer circle (open on the right ~40° gap).
    # The C stroke is the circle itself - no separate outer ring.
    stroke = max(3, logo_d // 10)
    radius = logo_d // 2 - stroke // 2

    # C: arc from 45° to 315° (leaves a gap at 0° / 3 o'clock)
    draw.arc(
        [logo_cx - radius, logo_cy - radius, logo_cx + radius, logo_cy + radius],
        start=45, end=315,
        fill=(255, 150, 0, 255),
        width=stroke,
    )

    # 'P' inscribed inside the C: vertical stem on the left interior,
    # bowl on the right interior (curving into the C's gap).
    inner_radius = int(radius * 0.45)
    p_stroke = max(2, logo_d // 14)

    # P stem: vertical line on left side of interior
    stem_x = logo_cx - int(inner_radius * 0.3)
    stem_top = logo_cy - int(inner_radius * 0.7)
    stem_bot = logo_cy + int(inner_radius * 0.7)
    draw.line(
        [stem_x, stem_top, stem_x, stem_bot],
        fill=(255, 255, 255, 255),
        width=p_stroke,
    )

    # P bowl: arc on right side of interior, curving into C's gap
    bowl_r = inner_radius
    bowl_cx = stem_x + bowl_r
    bowl_cy = stem_top + bowl_r
    # Arc from 270° (bottom) to 90° (top) - right-facing bowl
    draw.arc(
        [bowl_cx - bowl_r, bowl_cy - bowl_r, bowl_cx + bowl_r, bowl_cy + bowl_r],
        start=270, end=90,
        fill=(255, 255, 255, 255),
        width=p_stroke,
    )


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
    title_font = _font_bold(max(14, size // 7))
    sub_font = _font_bold(max(10, size // 10))
    tag_font = _font_regular(max(8, size // 18))
    badge_font = _font_bold(max(9, size // 16))

    def _center(text, font, y, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((size - tw) / 2 - bbox[0], y), text, font=font, fill=fill)

    _center("CHRIS", title_font, int(size * 0.12), (255, 255, 255, 255))
    _center("PRIME", title_font, int(size * 0.24), (255, 255, 255, 255))
    _center("CUSTOM", sub_font, int(size * 0.36), (255, 150, 0, 255))
    _center("rock band custom song", tag_font, int(size * 0.84), (200, 200, 200, 255))

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

    # "CP" monogram logo in the top-left corner: thick C as outer circle, P inscribed inside
    _draw_cp_logo(draw, size, m)

    # Flatten onto an opaque black canvas so the texture encodes as DXT1
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    return Image.alpha_composite(bg, img).convert("RGBA")
