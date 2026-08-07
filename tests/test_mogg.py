import math
import struct
import subprocess
import wave

import numpy as np

from autorb.export.mogg_builder import build_mogg_from_stems


def _make_wav(path, freq, seconds=0.4, rate=44100):
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(5000 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(n)
        )
        w.writeframes(frames)


def _decode_channels(mogg_path, header_size, ch_count, rate):
    data = open(mogg_path, "rb").read()
    with open("/tmp/mogg_test.ogg", "wb") as f:
        f.write(data[header_size:])
    raw = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", "/tmp/mogg_test.ogg",
            "-ar", str(rate), "-ac", str(ch_count), "-f", "s16le", "-",
        ],
        capture_output=True, check=True,
    ).stdout
    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    return arr.reshape(-1, ch_count)


def _rms(x):
    if len(x) == 0:
        return 0.0
    return float(math.sqrt(float((x * x).mean())))


def test_all_ten_channels_carry_audio(tmp_path):
    stems = tmp_path / "stems"
    stems.mkdir()
    _make_wav(stems / "drums.wav", 220)
    _make_wav(stems / "bass.wav", 165)
    _make_wav(stems / "other.wav", 330)
    _make_wav(stems / "vocals.wav", 440)

    out = tmp_path / "out"
    out.mkdir()
    mogg = build_mogg_from_stems(stems, out, "test_song", skip_mogg=False, count_in_ms=0)

    header = open(mogg, "rb").read()[:20]
    version, header_size, _, _, _ = struct.unpack("<IIIII", header)
    assert version == 0x0A
    frames = _decode_channels(mogg, header_size, ch_count=10, rate=44100)

    assert frames.shape[0] > 100
    for ch in range(10):
        r = _rms(frames[int(len(frames) * 0.2):, ch])
        assert r > 50, f"channel {ch} is silent (rms={r:.1f}) - preview mixdown would be silent"
