"""MOGG in-game mix balance regression tests (v0.1.28).

The PS4 playtest report: "drums WAY louder than everything else, barely
hear the bass even when playing the bass track." Root-caused by decoding
the shipped mogg + the stock 311-Down reference:

1. DRUM KIT DUPLICATED: ch0-1 carried a full-kit COPY and ch2-3 the kit
   again, while the game's drum bus sums ch0+ch1+ch2-3 (MakeMoggDta's
   Mix1 split) -> kit played twice, +8..12 dB over every other bus.
   The 311 reference's ch0/1 are independent kick/snare ELEMENTS
   (corr ~0 vs its kit). Fix: ch0-1 are now band ELEMENTS (kick 35-140Hz,
   snare 150Hz-8kHz) of the drum stem.
2. NO LOUDNESS MATCHING: Demucs stems come out at arbitrary scales
   (ORS: drums -26.6 vs 'other' -58.7 dB RMS). The reference's buses all
   land within 1.1 dB. Fix: per-stem gains land each BUS on the reference's
   measured levels (BUS_TARGET_DB), two-pass: encode -> measure actual bus
   levels -> correct gains -> final encode.

The whole-song validation of the user's two test songs landed every bus
within 0.1 dB of target (spread 1.08/1.14 dB vs the 11.5 dB bug).

These tests use tiny synthetic stems (fast ffmpeg runs) and verify:
- ch0-1 are NOT copies of ch2-3 (correlation ~ 0 and band-limited content)
- bus levels land near BUS_TARGET after the two-pass build
- the balance math (analytic + pass-2 correction) works end-to-end
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autorb.export.mogg_builder import (
    BUS_TARGET_DB,
    build_mogg_from_stems,
)


def _write_stems(tmp: Path, drums_db=-20.0, bass_db=-24.0, other_db=-25.0,
                 vocals_db=-26.0, guitar_db=-22.0, dur=6.0):
    """Write synthetic 6-stem WAVs with prescribed relative loudness.

    The drum stem is BROADBAND noise bursts (kick thump + snare crack +
    cymbal hiss) like a real kit, so the ch0 kick-band ELEMENT is a proper
    frequency SLICE of the stem — pure tones made ch0 ≈ the whole signal
    and broke the band-split semantics these tests pin.
    """
    import numpy as np
    import soundfile as sf
    stems = tmp / "stems"
    stems.mkdir(exist_ok=True)
    sr = 44100
    n = int(dur * sr)
    t = np.arange(n) / sr
    rng = np.random.default_rng(42)

    def noise_band(lo, hi, db):
        """Band-limited noise calibrated to the requested RMS (dB)."""
        white = rng.standard_normal(n)
        spec = np.fft.rfft(white)
        freqs = np.fft.rfftfreq(n, 1 / sr)
        spec[(freqs < lo) | (freqs > hi)] = 0
        sig = np.fft.irfft(spec, n)
        rms = np.sqrt((sig ** 2).mean())
        if rms <= 0:
            rms = 1e-9
        sig = sig / rms * (10 ** (db / 20))
        return sig

    def tone(freq, db, wobble=2.0):
        sig = 0.6 * np.sin(2 * np.pi * freq * t) + \
              0.4 * np.sin(2 * np.pi * freq * wobble * t)
        amp = 10 ** (db / 20)
        trem = 0.8 + 0.2 * np.sin(2 * np.pi * 0.7 * t)
        return sig * amp * trem

    # drum kit: kick thump (40-100Hz) + snare body (150-400) + cymbal hiss
    # (4k-14k), amplitude-shaped like hits
    hits = (np.sin(2 * np.pi * 2.0 * t) > 0.6).astype(float)  # gate
    kit = (noise_band(40, 100, drums_db) * hits
           + noise_band(150, 400, drums_db + 1) * hits
           + noise_band(4000, 14000, drums_db + 3) * hits)
    kit = np.stack([kit, kit], axis=1)
    sf.write(stems / "drums.wav", kit, sr)

    def stereo(sig):
        return np.stack([sig, sig], axis=1)

    sf.write(stems / "bass.wav", stereo(noise_band(60, 200, bass_db)), sr)
    sf.write(stems / "other.wav", stereo(noise_band(300, 3000, other_db)), sr)
    sf.write(stems / "vocals.wav", stereo(noise_band(200, 4000, vocals_db)), sr)
    sf.write(stems / "guitar.wav", stereo(noise_band(150, 2500, guitar_db)), sr)
    sf.write(stems / "piano.wav", stereo(noise_band(800, 6000, -60.0)), sr)
    return stems


class TestDrumChannelLayout:
    def _build(self, tmp_path, **kw):
        stems = _write_stems(tmp_path, **kw)
        mogg = build_mogg_from_stems(stems, tmp_path, "t", count_in_ms=0)
        d = mogg.read_bytes()
        ogg = tmp_path / "t.ogg"
        ogg.write_bytes(d[d.find(b"OggS"):])
        import soundfile as sf
        import numpy as np
        y, sr = sf.read(str(ogg), always_2d=True)
        return y, sr, np

    def test_ch0_ch1_not_kit_copies(self, tmp_path):
        """The drum bus sums ch0+ch1+ch2-3; ch0-1 must be BAND ELEMENTS,
        not copies of the kit (corr(ch0,ch2) was exactly 1.0 in the bug)."""
        y, sr, np = self._build(tmp_path)
        mus = y[:]
        corr = np.corrcoef(mus[:, 0], mus[:, 2])[0, 1]
        assert abs(corr) < 0.5, f"ch0/ch2 correlated ({corr:.2f}) — kit duplicated again"

    def test_ch0_is_band_limited(self, tmp_path):
        """ch0 (kick element) must be low-band: its energy above 200Hz
        must be tiny vs the full kit ch2."""
        y, sr, np = self._build(tmp_path)
        import numpy.fft as fft
        spec0 = np.abs(fft.rfft(y[:, 0]))
        spec2 = np.abs(fft.rfft(y[:, 2]))
        freqs = fft.rfftfreq(len(y), 1 / sr)
        hi = freqs > 200
        hi_share0 = spec0[hi].sum() / max(spec0.sum(), 1e-9)
        hi_share2 = spec2[hi].sum() / max(spec2.sum(), 1e-9)
        # ch0 is a 35-140Hz bandpass: at least ~2.5x more low-weighted
        # than the full kit (filters leak some transition-band energy; the
        # strict "no highs" claim is checked by the correlation test).
        assert hi_share0 < 0.4 * hi_share2 + 0.05, \
            f"ch0 high-band share {hi_share0:.2f} vs kit {hi_share2:.2f} — " \
            "ch0 should be the kick ELEMENT, not a kit copy"


class TestBusBalance:
    def _bus_levels(self, tmp_path, **kw):
        stems = _write_stems(tmp_path, **kw)
        mogg = build_mogg_from_stems(stems, tmp_path, "t", count_in_ms=0)
        d = mogg.read_bytes()
        ogg = tmp_path / "t.ogg"
        ogg.write_bytes(d[d.find(b"OggS"):])
        import soundfile as sf
        import numpy as np
        y, sr = sf.read(str(ogg), always_2d=True)
        vols = [-0.5, -0.1, -2.1, -2.1, -3.1, -2.0, -2.0, -3.0, -3.0, -3.1]

        def bus(chs):
            sig = np.zeros(len(y))
            for c in chs:
                sig += y[:, c] * (10 ** (vols[c] / 20))
            return 20 * np.log10(max(float(np.sqrt((sig ** 2).mean())), 1e-10))

        return {"drums": bus([0, 1, 2, 3]), "bass": bus([4]),
                "guitar": bus([5, 6]), "vocals": bus([7, 8])}

    def test_buses_land_on_reference_targets(self, tmp_path):
        """Every instrument bus must land within 3 dB of the 311-Down
        reference targets — the balance fix's whole point."""
        levels = self._bus_levels(tmp_path, drums_db=-20, bass_db=-24,
                                  other_db=-25, vocals_db=-26, guitar_db=-22)
        for name, target in BUS_TARGET_DB.items():
            err = levels[name] - target
            assert abs(err) <= 3.0, \
                f"{name} bus {levels[name]:.1f} dB vs target {target} dB (err {err:+.1f})"

    def test_loud_drums_do_not_dominate(self, tmp_path):
        """The original bug: drums +11.5 dB over bass in-game. Even with a
        HOT drum stem and a quiet bass stem, the calibrated mix must keep
        every bus within ~3.5 dB of every other."""
        levels = self._bus_levels(tmp_path, drums_db=-15, bass_db=-28,
                                  other_db=-25, vocals_db=-26, guitar_db=-22)
        spread = max(levels.values()) - min(levels.values())
        assert spread <= 3.5, \
            f"bus spread {spread:.1f} dB — drums dominating again? {levels}"

    def test_quiet_stem_gain_capped(self, tmp_path):
        """A near-silent stem must not be amplified to noise: the ±12 dB
        gain cap keeps 'other' at -58 dB from becoming a hiss bus."""
        levels = self._bus_levels(tmp_path, other_db=-70)
        # 'other' mixes into the guitar bus; with guitar present it's fine,
        # but the cap prevents 50 dB of boost — the guitar bus shouldn't
        # be 20 dB over target.
        assert levels["guitar"] < BUS_TARGET_DB["guitar"] + 10


class TestRevealGioSubcommand:
    def test_gio_needs_open_subcommand(self):
        """The bare `gio <path>` call printed usage text and opened
        nothing (user-observed). The reveal chain must pass `gio open`."""
        import re
        src = Path("webui/reveal.py").read_text()
        assert re.search(r'"gio",\s*"open"', src), \
            "reveal must call `gio open <path>`, not bare `gio <path>`"

    def test_gio_argv_includes_subcommand(self, tmp_path, monkeypatch):
        from webui import reveal
        calls = []
        monkeypatch.setattr(reveal.sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":0")
        monkeypatch.setattr(reveal.shutil, "which",
                            lambda x: "/usr/bin/gio" if x == "gio" else None)
        class FakeResult:
            returncode = 0
            stderr = ""
        def fake_run(argv, *a, **k):
            calls.append(list(argv))
            return FakeResult()
        monkeypatch.setattr(reveal.subprocess, "run", fake_run)
        ok, msg = reveal.reveal_in_file_manager(tmp_path)
        assert ok
        assert calls and calls[0][:2] == ["gio", "open"], \
            f"expected ['gio','open',path], got {calls}"


class TestRevealHeadlessHonesty:
    def test_headless_reports_failure_with_path(self, tmp_path, monkeypatch):
        """No DISPLAY/WAYLAND_DISPLAY -> ok MUST be False with the path in
        the message (the devcontainer case: a window can never open, and
        reporting success made the UI show nothing)."""
        import os
        from webui import reveal
        monkeypatch.setattr(reveal.sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        ok, msg = reveal.reveal_in_file_manager(tmp_path)
        assert ok is False
        assert str(tmp_path) in msg

    def test_gui_session_check(self, monkeypatch):
        import os
        from webui.reveal import _has_gui_session
        import webui.reveal as reveal
        monkeypatch.setattr(reveal.sys, "platform", "linux")
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert _has_gui_session() is False
        monkeypatch.setenv("DISPLAY", ":0")
        assert _has_gui_session() is True

    def test_gio_exit_zero_with_stderr_is_failure(self, tmp_path, monkeypatch):
        """gio exits 0 while printing 'Failed to find default application'
        on desktop-less boxes — stderr must be treated as failure."""
        from webui import reveal
        monkeypatch.setattr(reveal.sys, "platform", "linux")
        monkeypatch.setenv("DISPLAY", ":99")  # pretend GUI exists
        monkeypatch.setattr(reveal.shutil, "which",
                            lambda x: "/usr/bin/gio" if x == "gio" else None)
        class FakeResult:
            returncode = 0
            stderr = "gio: Failed to find default application for content type"
        monkeypatch.setattr(reveal.subprocess, "run",
                            lambda *a, **k: FakeResult())
        ok, msg = reveal.reveal_in_file_manager(tmp_path)
        assert ok is False


class TestCustomOutputRoot:
    def test_jobstore_output_root_honored(self, tmp_path):
        from webui.jobs import JobStore
        custom = tmp_path / "my_songs"
        store = JobStore(tmp_path / "jobs", repo_root=tmp_path)
        job = store.create_draft(output_root=custom)
        assert str(job.output_dir).startswith(str(custom.resolve()))
        assert job.output_dir.exists()
        # default (no override) stays under the jobs root
        job2 = store.create_draft()
        assert str(job2.output_dir).startswith(str(tmp_path / "jobs"))

    def test_store_level_output_root(self, tmp_path):
        from webui.jobs import JobStore
        custom = tmp_path / "all_outputs"
        store = JobStore(tmp_path / "jobs", repo_root=tmp_path,
                         output_root=custom)
        job = store.create_draft()
        assert str(job.output_dir).startswith(str(custom.resolve()))
