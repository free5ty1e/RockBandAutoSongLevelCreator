#!/usr/bin/env python
"""HMXBitmap (Milo engine) texture encoder/decoder for Rock Band album art.

The `_keep.png_xbox` files inside Rock Band CON song folders are standalone
Milo ``HMXBitmap`` textures: a 32-byte header followed by S3TC (DXT) block
compressed pixel data whose 16-bit words are byte-swapped for Xbox 360.

This encoder mirrors what SuperFreq's ``png2tex --platform x360`` produces
(the community-proven format used by Rock Band 3 Deluxe / GH2 Deluxe custom
artwork): a single mip level (``MipMaps = 0``) of DXT1 (encoding 8, bpp 4)
for fully opaque images or DXT5 (encoding 24, bpp 8) when the image carries
an alpha channel.  Verified against the official DLC texture found in the
SmellsLikeNirvana template CON (DXT5, 256x256, mips 4) and against a
SuperFreq-produced ``_keep.png_xbox`` (DXT5, 256x256, mips 0).
"""

from __future__ import annotations

import struct

import numpy as np
from PIL import Image

TEXTURE_HEADER_SIZE = 32
ENCODING_DXT1 = 8
ENCODING_DXT5 = 24

_LUMA = np.array([0.299, 0.587, 0.114], dtype=np.float64)


def _quantize_rgb565(pixel):
    r, g, b = pixel
    r5 = (int(round(r)) * 31) // 255
    g6 = (int(round(g)) * 63) // 255
    b5 = (int(round(b)) * 31) // 255
    return (r5 << 11) | (g6 << 5) | b5


def _unquantize_rgb565(word):
    r = (word >> 11) & 0x1F
    g = (word >> 5) & 0x3F
    b = word & 0x1F
    return np.array([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], dtype=np.uint8)


def _palette_colors(c0, c1):
    c0f = c0.astype(np.int32)
    c1f = c1.astype(np.int32)
    return np.stack([
        c0,
        c1,
        ((2 * c0f + c1f) // 3).astype(np.uint8),
        ((c0f + 2 * c1f) // 3).astype(np.uint8),
    ])


def _dxt1_color_block(pixels):
    """Encodes 16 RGBA pixels into the 8-byte color half of a DXT block."""
    rgb = pixels[:, :3].astype(np.float64)
    lum = rgb @ _LUMA
    c0 = rgb[int(lum.argmin())]
    c1 = rgb[int(lum.argmax())]

    for _ in range(6):
        d0 = np.sum((rgb - c0) ** 2, axis=1)
        d1 = np.sum((rgb - c1) ** 2, axis=1)
        g0 = d0 <= d1
        g1 = ~g0
        if g0.any():
            c0 = rgb[g0].mean(axis=0)
        if g1.any():
            c1 = rgb[g1].mean(axis=0)

    w0 = _quantize_rgb565(np.clip(c0, 0, 255))
    w1 = _quantize_rgb565(np.clip(c1, 0, 255))
    if w0 <= w1:
        w0, w1 = w1, w0

    palette = _palette_colors(_unquantize_rgb565(w0), _unquantize_rgb565(w1))
    dist = np.sum((pixels[:, None, :3].astype(np.int32) - palette[None, :, :].astype(np.int32)) ** 2, axis=2)
    idx = dist.argmin(axis=1)

    indices = int(0)
    for i in range(16):
        indices |= int(idx[i]) << (2 * i)
    return struct.pack("<HH", w0, w1) + indices.to_bytes(4, "little")


def _dxt5_alpha_block(alphas):
    """Encodes 16 alpha values into the 8-byte alpha half of a DXT5 block."""
    a0 = int(alphas.max())
    a1 = int(alphas.min())
    if a0 > a1:
        table = [a0, a1] + [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
    else:
        table = [a0, a1] + [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255]
    table = np.array(table, dtype=np.int32)
    idx = np.abs(alphas.astype(np.int32)[:, None] - table[None, :]).argmin(axis=1)

    group0 = int(0)
    group1 = int(0)
    for i in range(8):
        group0 |= int(idx[i]) << (3 * i)
        group1 |= int(idx[8 + i]) << (3 * i)
    return bytes([a0, a1]) + group0.to_bytes(3, "little") + group1.to_bytes(3, "little")


def _swap_bytes(data: bytes) -> bytes:
    """Swaps every 16-bit word (Xbox 360 endianness for S3TC data)."""
    words = np.frombuffer(data, dtype="<u2")
    swapped = ((words & 0xFF) << 8) | (words >> 8)
    return swapped.tobytes()


def _unswap_bytes(data: bytes) -> bytes:
    return _swap_bytes(data)


def encode_keep_texture(image: Image.Image) -> bytes:
    """Encodes a PIL image into Rock Band ``_keep.png_xbox`` bytes.

    Width/height must each be a power of two and at least 4 pixels; the
    caller is responsible for resizing (256x256 is the standard album art).
    """
    rgba = image.convert("RGBA")
    w, h = rgba.size
    if w < 4 or h < 4 or (w & (w - 1)) or (h & (h - 1)):
        raise ValueError(f"Image dimensions must be powers of two >= 4, got {w}x{h}")

    pixels = np.asarray(rgba, dtype=np.uint8)
    has_alpha = bool((pixels[:, :, 3] < 255).any())

    if has_alpha:
        encoding, bpp = ENCODING_DXT5, 8
    else:
        encoding, bpp = ENCODING_DXT1, 4

    blocks_x = w // 4
    blocks_y = h // 4
    block_count = blocks_x * blocks_y

    if has_alpha:
        payload = bytearray(block_count * 16)
    else:
        payload = bytearray(block_count * 8)

    for by in range(blocks_y):
        for bx in range(blocks_x):
            block_pixels = pixels[by * 4:by * 4 + 4, bx * 4:bx * 4 + 4].reshape(16, 4)
            color = _dxt1_color_block(block_pixels)
            if has_alpha:
                alpha = _dxt5_alpha_block(block_pixels[:, 3])
                off = (by * blocks_x + bx) * 16
                payload[off:off + 16] = alpha + color
            else:
                off = (by * blocks_x + bx) * 8
                payload[off:off + 8] = color

    header = (
        b"\x01"
        + bytes([bpp])
        + struct.pack("<i", encoding)
        + b"\x00"                       # MipMaps = 0
        + struct.pack("<h", w)
        + struct.pack("<h", h)
        + struct.pack("<h", (w * bpp) // 8)
        + b"\x00" * 19
    )
    return header + _swap_bytes(bytes(payload))


def decode_keep_texture(data: bytes) -> Image.Image:
    """Decodes ``_keep.png_xbox`` bytes back into a PIL image (base mip only)."""
    if data[0] not in (0x01, 0x02):
        raise ValueError(f"Not an HMXBitmap texture (magic {data[0]:#x})")
    bpp = data[1]
    encoding = int.from_bytes(data[2:6], "little")
    w = int.from_bytes(data[7:9], "little")
    h = int.from_bytes(data[9:11], "little")
    bpl = int.from_bytes(data[11:13], "little")
    del bpl

    if encoding not in (ENCODING_DXT1, ENCODING_DXT5):
        raise ValueError(f"Unsupported texture encoding {encoding}")

    block_bytes = 8 if encoding == ENCODING_DXT1 else 16
    base_bytes = (w * h * block_bytes * 4) // 16
    raw = _unswap_bytes(data[TEXTURE_HEADER_SIZE:TEXTURE_HEADER_SIZE + base_bytes])

    img = np.zeros((h, w, 4), dtype=np.uint8)
    blocks_x = w // 4
    for by in range(h // 4):
        for bx in range(w // 4):
            off = (by * blocks_x + bx) * block_bytes
            block = raw[off:off + block_bytes]

            if encoding == ENCODING_DXT1:
                w0 = block[0] | (block[1] << 8)
                w1 = block[2] | (block[3] << 8)
                c0, c1 = _unquantize_rgb565(w0), _unquantize_rgb565(w1)
                inds = int.from_bytes(block[4:8], "little")
                if w0 > w1:
                    palette = _palette_colors(c0, c1)
                else:
                    palette = _palette_colors(c0, c1)
                    palette[3] = np.zeros(3, dtype=np.uint8)
                for i in range(16):
                    x, y = i & 3, i >> 2
                    ci = (inds >> (2 * i)) & 3
                    if ci == 3 and w0 <= w1:
                        img[y + by * 4, x + bx * 4] = [0, 0, 0, 0]
                    else:
                        img[y + by * 4, x + bx * 4] = np.append(palette[ci], 255)
            else:
                a0, a1 = block[0], block[1]
                ai_bits = int.from_bytes(block[2:8], "little")
                w0 = block[8] | (block[9] << 8)
                w1 = block[10] | (block[11] << 8)
                c0, c1 = _unquantize_rgb565(w0), _unquantize_rgb565(w1)
                palette = _palette_colors(c0, c1)
                inds = int.from_bytes(block[12:16], "little")
                if a0 > a1:
                    alphas = [a0, a1] + [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
                else:
                    alphas = [a0, a1] + [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255]
                for i in range(16):
                    x, y = i & 3, i >> 2
                    ci = (inds >> (2 * i)) & 3
                    ai = (ai_bits >> (3 * i)) & 7
                    img[y + by * 4, x + bx * 4] = np.append(palette[ci][:3], alphas[ai])

    return Image.fromarray(img, "RGBA")


def keep_texture_from_image(image_path, size: int = 256) -> bytes:
    """Loads an image file, cover-fits it to a square power-of-two size and encodes it."""
    from PIL import ImageOps

    with Image.open(image_path) as src:
        fitted = ImageOps.fit(src.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
        return encode_keep_texture(fitted)


def default_album_art_bytes(size: int = 256) -> bytes:
    """Generates the generic 'Chris Prime Custom' album art texture."""
    from autorb.export.album_art import build_default_album_art
    return encode_keep_texture(build_default_album_art(size))
