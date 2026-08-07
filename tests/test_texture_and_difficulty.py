import numpy as np
import pytest
from PIL import Image

from autorb.export.album_art import build_default_album_art
from autorb.export.difficulty import compute_ranks, count_notes_per_track
from autorb.export.texture import (
    decode_keep_texture,
    default_album_art_bytes,
    encode_keep_texture,
)


def _write_midi(path, tracks):
    import struct

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), 480)
    chunks = []
    for name, events in tracks:
        name_chunk = b"\x00\xFF\x03" + bytes([len(name)]) + name.encode("ascii")
        content = name_chunk + events + b"\x00\xFF\x2F\x00"
        chunks.append(b"MTrk" + struct.pack(">I", len(content)) + content)
    path.write_bytes(header + b"".join(chunks))


def _note(pitch, vel=100, dur=120):
    return (
        b"\x00\x90" + bytes([pitch, vel]) +
        b"\x00\x80" + bytes([pitch, 0])
    )


def test_dxt1_roundtrip_opaque():
    image = Image.new("RGBA", (256, 256), (200, 30, 60, 255))
    for x in range(0, 256, 8):
        for y in range(0, 256, 8):
            image.putpixel((x, y), (x % 256, y % 256, 128, 255))

    encoded = encode_keep_texture(image)
    assert encoded[0] == 0x01
    assert encoded[1] == 4          # bpp DXT1
    assert int.from_bytes(encoded[2:6], "little") == 8

    decoded = decode_keep_texture(encoded)
    assert decoded.size == (256, 256)
    assert np.all(np.asarray(decoded)[:, :, 3] == 255)
    diff = np.abs(np.asarray(image).astype(int) - np.asarray(decoded).astype(int))
    assert diff[:, :, :3].mean() < 12.0


def test_default_album_art_is_valid_texture():
    data = default_album_art_bytes()
    assert data[0] == 0x01
    decoded = decode_keep_texture(data)
    assert decoded.size == (256, 256)
    # Fully opaque art should be compact DXT1 (0.5 bytes/pixel)
    assert len(data) == 32 + (256 * 256) // 2
    assert np.all(np.asarray(decoded)[:, :, 3] == 255)


def test_custom_album_art_file():
    image = build_default_album_art(256)
    encoded = encode_keep_texture(image)
    decoded = decode_keep_texture(encoded)
    assert decoded.size == (256, 256)


def test_album_art_title_is_legible():
    # Regression: the title must render at the real DejaVu size (thousands of
    # glyph pixels on 256px art), NOT Pillow's tiny 8px load_default fallback
    # (a few hundred px) that made the art illegible on macOS. Also the bundled
    # font must be found regardless of OS font paths.
    image = build_default_album_art(256)
    region = image.crop((0, int(256 * 0.10), 256, int(256 * 0.45)))
    white = sum(1 for p in region.getdata() if p[0] > 200 and p[1] > 200 and p[2] > 200)
    assert white > 2000


def test_album_art_has_cp_logo():
    # The circular "CP" monogram lives in the bottom-right corner.
    image = build_default_album_art(256)
    region = image.crop((int(256 * 0.72), int(256 * 0.72), 256, 256))
    pixels = list(region.getdata())
    orange = sum(1 for p in pixels if p[0] > 200 and 100 < p[1] < 200 and p[2] < 120)
    white = sum(1 for p in pixels if p[0] > 200 and p[1] > 200 and p[2] > 200)
    assert orange > 50   # the outer ring
    assert white > 50    # the C + P glyphs


def test_difficulty_ranks_use_chart_density(tmp_path):
    midi = tmp_path / "song.mid"
    # 50 drum notes + 4 vocal notes over a nominal 10s song
    _write_midi(midi, [
        ("BEAT", b""),
        ("PART DRUMS", b"".join(_note(36 + (i % 4)) for i in range(50))),
        ("PART VOCALS", b"".join(_note(60) for _ in range(4))),
    ])
    counts = count_notes_per_track(midi)
    assert counts["PART DRUMS"] == 50
    assert counts["PART VOCALS"] == 4

    ranks = compute_ranks(midi, 10000)
    assert ranks["drum"] > ranks["vocals"]
    # band = hardest charted instrument (drum, level 2) -> band level-2 midpoint
    assert ranks["band"] == 188
    assert ranks["keys"] == 0
    assert ranks["real_guitar"] == 0


def test_empty_chart_gets_floor_rank(tmp_path):
    midi = tmp_path / "empty.mid"
    _write_midi(midi, [("BEAT", b""), ("PART GUITAR", b"")])
    ranks = compute_ranks(midi, 60000)
    assert ranks["guitar"] >= 1
