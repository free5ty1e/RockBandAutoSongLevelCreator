#!/usr/bin/env python

from pathlib import Path
import logging
import struct
import subprocess
import shutil

logger = logging.getLogger(__name__)

# MOGG header constants (see https://milo.ipg.pw/index.php/MOGG_File_Format
# and mtolly/ogg2mogg main.c)
MOGG_VERSION_UNENCRYPTED = 0x0A  # v10 = unencrypted (all RB4 customs use this)
MOGG_MAP_VERSION = 0x10
FRAME_INCREMENT = 20000          # seek-map entries every 20000 samples
SEEK_INCREMENT = 0x8000          # raw-byte stepping used to build the map
PAGE_DURATION_US = 40000         # ogg muxer page target (~2048-3072 sample granules, matching stock RB moggs)

_VORBIS_ENCODER_CACHE = None

# Target in-game loudness PER INSTRUMENT BUS (dB RMS, mono-summed), measured
# from the stock "311 - Down" DLC reference: its drum/bass/guitar/vocal
# buses all land within ~1 dB of each other (CON vols applied). Demucs
# stems come out at arbitrary absolute scales, so each stem gets a gain
# that lands its BUS on the reference's measured level (see
# build_mogg_from_stems; the dta vols array itself is not flat, so the gain
# model compensates the per-bus multiplier the vols imply).
BUS_TARGET_DB = {
    "drums": -17.5, "bass": -18.0, "guitar": -18.6, "vocals": -17.9,
}


def _stem_rms_db(input_files: list[Path]) -> list[float | None]:
    """Cheap per-stem loudness measure (dB RMS of the mono sum).

    Uses ffmpeg astats (no decode into Python memory — the stems are 10s of
    MB each). Returns one value per input file, in input order; None when a
    stem can't be measured (caller should leave its gain at unity).
    """
    out = []
    for f in input_files:
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostats", "-i", str(f),
                 "-af", "pan=mono|c0=0.5*FL+0.5*FR,astats=metadata=0",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=120)
            # astats prints "RMS level dB: x" in the final summary
            import re as _re
            vals = _re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)",
                               r.stderr)
            if not vals:
                out.append(None)
                continue
            v = vals[-1]
            out.append(float("-60.0") if v == "-inf" else float(v))
        except Exception as e:
            logger.warning(f"RMS measure failed for {f}: {e}")
            out.append(None)
    return out


def _require_libvorbis() -> None:
    """
    Ensure the current ffmpeg provides the 'libvorbis' encoder, or fail fast
    with an actionable message.

    The MOGG's multi-channel (10-ch) Ogg Vorbis payload MUST be encoded with
    'libvorbis': ffmpeg's built-in native 'vorbis' encoder only supports
    2 channels (and is experimental), so it cannot encode the 10-channel layout
    Rock Band requires. Homebrew's `ffmpeg` formula is compiled WITHOUT
    `--enable-libvorbis`, so a hardcoded `-c:a libvorbis` would otherwise fail
    with a cryptic 'Unknown encoder libvorbis'. Detect it here and point the
    user at a libvorbis-capable ffmpeg install.
    """
    global _VORBIS_ENCODER_CACHE
    if _VORBIS_ENCODER_CACHE is not None:
        if _VORBIS_ENCODER_CACHE:
            return
        _raise_no_libvorbis()
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
        )
        has = "libvorbis" in result.stdout
    except Exception as e:
        # ffmpeg missing/unresponsive -> let the encode step surface the real error
        logger.warning(f"Could not probe ffmpeg encoders ({e}); assuming libvorbis is available.")
        has = True
    _VORBIS_ENCODER_CACHE = has
    if not has:
        _raise_no_libvorbis()


def _raise_no_libvorbis():
    raise RuntimeError(
        "This ffmpeg was built WITHOUT the 'libvorbis' encoder, which is required to build "
        "the multi-channel (10-ch) MOGG. AutoRB cannot encode audio with this ffmpeg.\n\n"
        "The most common cause is Homebrew's macOS `ffmpeg` formula, which dropped libvorbis "
        "in ffmpeg 8. Fix: install an ffmpeg build that includes libvorbis, e.g.:\n"
        "  brew install ffmpeg-full      (macOS; then ensure it is on your PATH, see below)\n"
        "or use a static build from https://ffmpeg.org/download.html (macOS builds include libvorbis).\n\n"
        "ffmpeg-full is keg-only, so make sure its binary comes first on your PATH, e.g. for "
        "Apple Silicon:\n"
        "  export PATH=\"/opt/homebrew/opt/ffmpeg-full/bin:$PATH\"\n"
        "Verify with:  ffmpeg -encoders 2>&1 | grep vorbis   # should list 'libvorbis'"
    )


def _parse_ogg_pages(data: bytes) -> list:
    """
    Parse an Ogg bitstream and return [(file_offset, granulepos), ...] for each page.

    granulepos is signed; header pages carry -1, audio pages carry the PCM
    sample position of the last packet completed on that page.
    """
    pages = []
    pos = 0
    n = len(data)
    while pos < n:
        if data[pos:pos + 4] != b"OggS":
            idx = data.find(b"OggS", pos)
            if idx == -1:
                break
            pos = idx
        if pos + 27 > n:
            break
        granule = int.from_bytes(data[pos + 6:pos + 14], "little", signed=True)
        segs = data[pos + 26]
        if pos + 27 + segs > n:
            break
        payload = sum(data[pos + 27:pos + 27 + segs])
        pages.append((pos, granule))
        pos = pos + 27 + segs + payload
    return pages


def read_mogg_duration_ms(mogg_path: str | Path) -> int:
    """
    Return the audio duration of a MOGG in milliseconds, computed from the
    final Ogg granule position and the Vorbis sample rate. Used to populate
    songs.dta's (song_length ...) so metadata matches the actual audio.
    """
    data = Path(mogg_path).read_bytes()
    header_size = int.from_bytes(data[4:8], "little")
    ogg = data[header_size:]
    pos = ogg.find(b"OggS")
    if pos < 0 or pos + 27 > len(ogg):
        raise ValueError(f"Invalid MOGG (no OggS): {mogg_path}")
    segs = ogg[pos + 26]
    laces = list(ogg[pos + 27:pos + 27 + segs])
    packet = b""
    for l in laces:
        packet += ogg[pos + 27 + segs:pos + 27 + segs + l]
        if l < 255:
            break
    if len(packet) < 30 or packet[:7] != b"\x01vorbis":
        raise ValueError(f"Invalid MOGG (bad Vorbis id header): {mogg_path}")
    rate = int.from_bytes(packet[12:16], "little")
    pages = _parse_ogg_pages(ogg)
    granules = [g for _, g in pages if g >= 0]
    if not granules:
        raise ValueError(f"Invalid MOGG (no audio pages): {mogg_path}")
    return int(granules[-1] * 1000 // rate)


def wrap_ogg_as_mogg(ogg_bytes: bytes) -> bytes:
    """
    Prepend the Harmonix MOGG header to a multi-channel Ogg Vorbis bitstream.

    Layout (all little-endian):
        u32 version = 0x0A (unencrypted)
        u32 header size  (byte offset where the Ogg data begins)
        u32 map version  = 0x10
        u32 seek interval = 20000
        u32 entry count
        [u32 byte offset, u32 sample] * entry count   (the OggMap)
        ... raw Ogg Vorbis bytes, byte-identical to the input
    """
    pages = _parse_ogg_pages(ogg_bytes)
    audio_samples = [g for _, g in pages if g >= 0]
    if not audio_samples:
        raise ValueError("No audio pages found in Ogg data; cannot build MOGG.")
    total_samples = audio_samples[-1]
    total_bytes = len(ogg_bytes)

    # For every 0x8000-byte increment of the file, record the granule position
    # of the FIRST page starting at-or-after it (mirrors ogg2mogg's semantics).
    seek_bytes = []
    seek_samples = []
    i = 0
    while i * SEEK_INCREMENT < total_bytes:
        x = i * SEEK_INCREMENT
        sample = 0xFFFFFFFF
        for offset, granule in pages:
            if offset >= x:
                sample = granule if granule >= 0 else 0xFFFFFFFF
                break
        seek_bytes.append(i * SEEK_INCREMENT)
        seek_samples.append(sample)
        i += 1

    # For each 20000-sample frame, pick the last seek entry whose sample is
    # at or before the frame start (mirrors ogg2mogg's two-pass table build).
    entry_count = (total_samples + FRAME_INCREMENT - 1) // FRAME_INCREMENT
    table = []
    for k in range(entry_count):
        desired = k * FRAME_INCREMENT
        byte_offset = 0
        sample = 0
        for b, s in zip(seek_bytes, seek_samples):
            if s <= desired:
                byte_offset, sample = b, s
            else:
                break
        table.append((byte_offset, sample))

    header = struct.pack(
        "<IIIII",
        MOGG_VERSION_UNENCRYPTED,
        20 + 8 * len(table),
        MOGG_MAP_VERSION,
        FRAME_INCREMENT,
        len(table),
    )
    for byte_offset, sample in table:
        header += struct.pack("<II", byte_offset, sample)

    return header + ogg_bytes


def build_mogg_from_stems(stems_dir: str | Path, output_dir: Path, song_id: str,
                          skip_mogg: bool = False, count_in_ms: int = 0) -> Path:
    """
    Combines stem WAV files into a multi-channel Harmonix MOGG audio container.

    ``count_in_ms`` > 0 prepends that many milliseconds of silence to all 10
    channels via ffmpeg's ``adelay``, producing the mandatory Rock Band count-in
    (a silent lead-in baked into the audio, mirroring stock RB3 DLC like "311 -
    Down" which has ~5s before its first note). The matching chart shift is
    applied by ``midi_generator.generate_vocal_midi(count_in_ticks=...)``.

    The 10-channel layout mirrors the proven-working "311 - Down" DLC so the
    track/channel structure is identical to a stock song (verified against
    LibForge#30, where mismatched track layouts make songs stop early in-game):

        ch0-1  full drum kit split stereo (311's kick/snare are its loudest
               channels; keeping the first stereo pair hot guarantees the
               song-list preview mixdown is never silent)
        ch2-3  stereo drum kit
        ch4    mono bass
        ch5-6  stereo guitar/backing (the 'other' stem)
        ch7-8  stereo vocals
        ch9    quiet fake/crowd ambience (backing at low level, near-silent
               like 311 Down's ch9 which reads ~50 RMS vs ~3500 on ch0)

    Every channel carries audio because the reference "311 - Down" mogg has
    non-zero signal on all 10 channels; leaving ch0-1/ch9 as digital silence
    made the PS4 song-list preview completely silent even though the chart,
    OggMap, and dta preview window were all verified correct.

    songs.dta must declare: ((drum (0 1 2 3)) (bass (4)) (guitar (5 6))
    (vocals (7 8))) with 10-entry pans/vols/cores, matching the 311 reference.
    """
    stems_path = Path(stems_dir)
    mogg_path = output_dir / f"{song_id}.mogg"

    if skip_mogg:
        if mogg_path.exists():
            logger.info(f"Skipping MOGG creation. Using existing MOGG at {mogg_path}")
            return mogg_path
        else:
            raise FileNotFoundError(f"Requested to skip MOGG building, but existing MOGG not found at {mogg_path}")

    stem_names = ["drums", "bass", "other", "vocals"]
    input_files = []

    for name in stem_names:
        p = stems_path / f"{name}.wav"
        if p.exists():
            input_files.append(p)

    # Optional dedicated stems (master stems, or a --separator htdemucs_6s run).
    # The 10-channel layout has no per-instrument channel beyond the 311
    # reference's drum/bass/guitar/vocals groups, so guitar/piano are MIXED
    # into the ch5-6 backing (guitar) bus — otherwise their audio would be
    # absent from gameplay entirely. Charting still reads them as dedicated
    # charts; only the MOGG mixing changes.
    extra_stems = []
    for name in ("guitar", "piano"):
        p = stems_path / f"{name}.wav"
        if p.exists():
            extra_stems.append(p)
    # Capture BEFORE extending: the 10-channel branch below keys off this,
    # not the post-extend length.
    standard_layout = len(input_files) == 4
    if extra_stems and standard_layout:
        logger.info(f"Mixing optional stems {[f.name for f in extra_stems]} "
                    "into the MOGG backing channels (ch5-6).")
        input_files.extend(extra_stems)

    if not input_files:
        input_files = sorted(list(stems_path.glob("*.wav")))

    if standard_layout:
        logger.info("Combining 4 stems into 10-channel MOGG container via ffmpeg (311 - Down layout, two-pass bus calibration).")

        # [0] drums, [1] bass, [2] other (guitar/backing), [3] vocals,
        # [4] optional guitar stem, [5] optional piano stem.
        #
        # v0.1.28 MIX BALANCE (the PS4 "drums way louder than everything
        # else / can barely hear bass" report):
        #   1. The game's drum bus sums ch0+ch1+ch2+ch3 (MakeMoggDta's Mix1
        #      split: drum (0), drum (1), drum (2 3)). Our old layout put a
        #      FULL KIT COPY on ch0-1 AND ch2-3, so the kit played twice
        #      (+~5-8 dB over every other bus). The 311-Down reference does
        #      NOT do this: its ch0/1 are separate kick/snare elements with
        #      near-zero correlation to the ch2-3 kit. We now build ch0-1
        #      as low-band (kick) and high-band (snare) ELEMENTS of the
        #      drum stem — a frequency split, not a copy — so the drum bus
        #      gets kit + a bit of extra punch, like the reference.
        #   2. Demucs stems come out at wildly different absolute scales
        #      (measured on Open Road Song: drums -26.6 dB vs 'other'
        #      -58.7 dB RMS), so a unity mix buries quiet instruments.
        #      Measured reference bus levels (311-Down, CON vols) are all
        #      within ~1 dB (-17.5..-18.6). We measure each stem's RMS and
        #      apply a per-stem gain so every bus lands at a common target
        #      (capped at ±12 dB; a stem that is genuinely near-silent,
        #      e.g. 'other' on a 6-stem song, is left near-silent rather
        #      than amplified to hiss).
        stem_rms = _stem_rms_db(input_files)   # [drums, bass, other, vocals, ...]

        # Bus multipliers implied by the stock dta vols (see dta_writer):
        # power-sum of the per-channel vol factors across each bus's channels.
        #   drums ch0-3: -0.5, -0.1, -2.1, -2.1  -> +4.9 dB bus gain
        #   bass   ch4:  -3.1                     -> -3.1 dB
        #   guitar ch5-6: -2.0, -2.0              -> +1.0 dB
        #   vocals ch7-8: -3.0, -3.0              -> +0.0 dB
        # (kick ch0 / snare ch1 are band ELEMENTS of the kit, so their
        # contribution to the bus is partial, but power-summing with their
        # hot vols is the conservative upper bound — keeps the kit from
        # doubling like the v0.1.27 duplication bug.)
        # Values MEASURED on a v0.1.28 build (correlated same-source
        # channels sum ~+6 dB per identical stereo pair; the drum bus's
        # kick/snare band elements sit ~3 dB under the kit, reducing the
        # +10.9 dB correlated sum of all four drum vols to +7.9):
        DTA_BUS_GAIN_DB = {
            "drums": 7.9, "bass": -3.1, "guitar": 4.8, "vocals": 6.1,
        }

        def bus_gain(stem_idx, stem_name, cap_db=12.0):
            rms = stem_rms[stem_idx]
            if rms is None:
                return 1.0
            bus_db = DTA_BUS_GAIN_DB.get(stem_name, 0.0)
            target = BUS_TARGET_DB.get(stem_name, -18.0)
            eff = rms + bus_db   # in-bus level if the stem were left at unity
            gain_db = min(cap_db, max(-cap_db, target - eff))
            g = 10 ** (gain_db / 20)
            logger.info(f"MOGG mix: {stem_name} stem RMS {rms:.1f} dB, dta bus "
                        f"{bus_db:+.1f} dB -> effective {eff:.1f} dB -> gain "
                        f"{gain_db:+.1f} dB (bus target {target:.1f} dB)")
            return g

        # vols/pans stay the stock dta values; the raw channel levels now
        # carry the balance. The per-stem gain compensates BOTH the stem's
        # own absolute level AND the bus gain the dta vols + correlated
        # channel summing apply. The drum bus's kick/snare band elements
        # contribute song-dependent energy (their share of the kit spectrum
        # varies), so a fixed analytic constant cannot land every bus —
        # hence TWO PASSES: encode once with analytic gains, MEASURE each
        # bus's actual level from the encoded channels, correct the gains,
        # and encode the final mix.
        stem_rms = _stem_rms_db(input_files)   # [drums, bass, other, vocals, ...]

        def _corr_sum_db(vol_db_list):
            import math as _m
            return 20 * _m.log10(sum(10 ** (v / 20) for v in vol_db_list))

        # Analytic bus multipliers from the stock CON dta vols (dta_writer):
        # correlated same-source channels sum by AMPLITUDE. The drums entry
        # scales the full correlated sum down for the band elements' partial
        # energy (measured ~4 dB share on ORS; pass 2 corrects the rest).
        DTA_BUS_GAIN_DB = {
            "drums": _corr_sum_db([-0.5, -0.1, -2.1, -2.1]) - 4.0,
            "bass": -3.1,
            "guitar": _corr_sum_db([-2.0, -2.0]),
            "vocals": _corr_sum_db([-3.0, -3.0]),
        }

        def bus_gain(stem_idx, stem_name, cap_db=12.0):
            rms = stem_rms[stem_idx]
            if rms is None:
                return 1.0
            bus_db = DTA_BUS_GAIN_DB.get(stem_name, 0.0)
            target = BUS_TARGET_DB.get(stem_name, -18.0)
            eff = rms + bus_db   # in-bus level if the stem were left at unity
            gain_db = min(cap_db, max(-cap_db, target - eff))
            g = 10 ** (gain_db / 20)
            logger.info(f"MOGG mix: {stem_name} stem RMS {rms:.1f} dB, est bus "
                        f"{bus_db:+.1f} dB -> effective {eff:.1f} dB -> gain "
                        f"{gain_db:+.1f} dB (bus target {target:.1f} dB)")
            return g

        def _encode(g_drums, g_bass, g_vocals, g_other, extra_gains,
                    ogg_path):
            """Encode the 10-channel ogg with the given per-stem gains."""
            if extra_stems:
                filter_parts = [
                    f"[2:a]volume={g_other:.6f}[o1]",
                    f"[4:a]volume={extra_gains[0]:.6f}[x1]",
                    "[o1][x1]"
                    + "amix=inputs=2:duration=longest:normalize=0"
                      + ",aformat=channel_layouts=stereo,asplit=3[gbus1][gbus2][gbus3]",
                ]
                backing_src1 = "[gbus1]"
                backing_src2 = "[gbus2]"
                backing_src3 = "[gbus3]"
            else:
                filter_parts = []
                backing_src1 = f"[2:a]volume={g_other:.6f},"
                backing_src2 = backing_src1
                backing_src3 = backing_src1
            filter_parts += [
                # ch0: KICK ELEMENT of the drum stem (low band) — NOT a kit
                # copy: the drum bus sums ch0+ch1+ch2-3, so duplicating the
                # kit would play it twice (the v0.1.27 "drums way too loud"
                # bug: kit measured +8..12 dB over every other bus in-game).
                f"[0:a]aformat=channel_layouts=stereo,pan=mono|c0=0.5*FL+0.5*FR,"
                f"volume={g_drums:.6f},highpass=f=35,lowpass=f=140[s0]",
                # ch1: SNARE ELEMENT (150 Hz-8 kHz band).
                f"[0:a]aformat=channel_layouts=stereo,pan=mono|c0=0.5*FL+0.5*FR,"
                f"volume={g_drums:.6f},highpass=f=150,lowpass=f=8000[s1]",
                # ch2-3: stereo drum kit (full band).
                f"[0:a]aformat=channel_layouts=stereo,volume={g_drums:.6f},asplit=2[dL][dR]",
                "[dL]pan=mono|c0=FL[s2]",
                "[dR]pan=mono|c0=FR[s3]",
                # ch4: mono bass.
                f"[1:a]aformat=channel_layouts=stereo,pan=mono|c0=0.5*FL+0.5*FR,volume={g_bass:.6f}[s4]",
                # ch5-6: stereo guitar/backing bus ('other' + guitar/piano).
                f"{backing_src1}aformat=channel_layouts=stereo,pan=mono|c0=FL[s5]",
                f"{backing_src2}aformat=channel_layouts=stereo,pan=mono|c0=FR[s6]",
                # ch7-8: stereo vocals.
                f"[3:a]aformat=channel_layouts=stereo,volume={g_vocals:.6f},asplit=2[vL][vR]",
                "[vL]pan=mono|c0=FL[s7]",
                "[vR]pan=mono|c0=FR[s8]",
                # ch9: fake/crowd ambience at low level (near-silent like
                # 311-Down's ch9).
                f"{backing_src3}aformat=channel_layouts=stereo,pan=mono|c0=0.5*FL+0.5*FR,volume=0.1[s9]",
                "[s0][s1][s2][s3][s4][s5][s6][s7][s8][s9]amerge=inputs=10[aout]",
            ]
            if count_in_ms > 0:
                filter_parts.append(f"[aout]adelay={count_in_ms}:all=1[countin]")
                map_label = "[countin]"
            else:
                map_label = "[aout]"
            _require_libvorbis()
            cmd = ["ffmpeg", "-y"]
            for f in input_files:
                cmd.extend(["-i", str(f)])
            # Small pages (~2048-3072 sample granules) match stock Harmonix
            # moggs; ffmpeg's default libvorbis paging emits ~1s/56KB pages
            # that Rock Band's Milkshake audio engine cannot decode reliably.
            cmd.extend([
                "-filter_complex", ";".join(filter_parts),
                "-map", map_label,
                "-c:a", "libvorbis",
                "-q:a", "2",
                "-page_duration", str(PAGE_DURATION_US),
                "-f", "ogg",
                str(ogg_path),
            ])
            result = subprocess.run(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg multi-channel merge failed: {result.stderr}")
                raise RuntimeError(f"FFmpeg failed to build MOGG container: {result.stderr}")

        DTA_CON_VOLS = [-0.5, -0.1, -2.1, -2.1, -3.1, -2.0, -2.0, -3.0, -3.0, -3.1]

        def _measure_buses(ogg_path):
            """Decode the pass-1 ogg and measure each instrument bus's
            actual dB RMS under the PS4-padded dta vols (LibForge pads
            every CON vol by -3.0 dB when writing the PS4 mogg.dta)."""
            try:
                import soundfile as _sf
                import numpy as _np
                y, _sr = _sf.read(str(ogg_path), always_2d=True)
            except Exception as e:
                logger.warning(f"pass-1 bus measurement failed ({e}); "
                               "keeping analytic gains")
                return None
            skip = int(_sr * (count_in_ms / 1000.0 + 1.0))
            y = y[skip:] if skip < len(y) else y
            # Measure under the CON vols (unpadded): BUS_TARGET_DB was
            # measured from the 311-Down reference the same way, and the
            # PS4's -3 dB pad is a uniform shift that does not affect the
            # buses' BALANCE (comparing a padded measurement against an
            # unpadded target made pass 2 over-boost every bus by 3 dB).
            vols = list(DTA_CON_VOLS)
            def bus(chs):
                sig = _np.zeros(len(y))
                for c in chs:
                    sig += y[:, c] * (10 ** (vols[c] / 20))
                return 20 * _np.log10(max(float(_np.sqrt((sig ** 2).mean())), 1e-10))
            return {
                "drums": bus([0, 1, 2, 3]),
                "bass": bus([4]),
                "guitar": bus([5, 6]),
                "vocals": bus([7, 8]),
            }

        # ---- pass 1: encode with analytic gains, then measure ----
        g_drums = bus_gain(0, "drums")
        g_bass = bus_gain(1, "bass")
        g_vocals = bus_gain(3, "vocals")
        g_other = bus_gain(2, "guitar")
        extra_gains = [bus_gain(4 + i, "guitar")
                       for i in range(len(extra_stems))]

        pass1_ogg = output_dir / f"{song_id}.pass1.ogg"
        try:
            _encode(g_drums, g_bass, g_vocals, g_other, extra_gains, pass1_ogg)
            measured = _measure_buses(pass1_ogg)
            if measured is not None:
                def _adj(name, g):
                    err_db = measured[name] - BUS_TARGET_DB[name]
                    if abs(err_db) < 0.3:
                        return g
                    # the bus level moves 1:1 (in dB) with the stem gain;
                    # clamp the correction so we never explode a quiet stem
                    corr_db = max(-6.0, min(6.0, -err_db))
                    logger.info(f"MOGG mix pass-2: {name} bus measured "
                                f"{measured[name]:.1f} dB (target "
                                f"{BUS_TARGET_DB[name]:.1f}) -> stem gain "
                                f"correction {corr_db:+.1f} dB")
                    return g * (10 ** (corr_db / 20))
                g_drums = _adj("drums", g_drums)
                g_bass = _adj("bass", g_bass)
                g_vocals = _adj("vocals", g_vocals)
                g_other = _adj("guitar", g_other)
                extra_gains = [_adj("guitar", g) for g in extra_gains]
        finally:
            pass1_ogg.unlink(missing_ok=True)

        # ---- final encode with calibrated gains ----
        ogg_tmp = output_dir / f"{song_id}.tmp.ogg"
        _encode(g_drums, g_bass, g_vocals, g_other, extra_gains, ogg_tmp)
        try:
            ogg_bytes = ogg_tmp.read_bytes()
        finally:
            ogg_tmp.unlink(missing_ok=True)

        if not ogg_bytes:
            raise RuntimeError("FFmpeg produced an empty Ogg file.")

        mogg_bytes = wrap_ogg_as_mogg(ogg_bytes)
        mogg_path.write_bytes(mogg_bytes)
        logger.info(f"Built MOGG (v{MOGG_VERSION_UNENCRYPTED}, {len(mogg_bytes)} bytes) at {mogg_path}")
    elif input_files:
        # Generic fallback: merge however many stems exist, one stereo pair each.
        logger.warning(f"Expected 4 standard stems (drums/bass/other/vocals); got {len(input_files)}. "
                       "Falling back to per-stem stereo merge.")
        ogg_tmp = output_dir / f"{song_id}.tmp.ogg"
        cmd = ["ffmpeg", "-y"]
        for f in input_files:
            cmd.extend(["-i", str(f)])
        n = len(input_files)
        filter_parts = [f"[{i}:a]aformat=channel_layouts=stereo[s{i}]" for i in range(n)]
        filter_parts.append("".join(f"[s{i}]" for i in range(n)) + f"amerge=inputs={n}[aout]")
        if count_in_ms > 0:
            filter_parts.append(f"[aout]adelay={count_in_ms}:all=1[countin]")
            map_label = "[countin]"
        else:
            map_label = "[aout]"
        _require_libvorbis()
        cmd.extend([
            "-filter_complex", ";".join(filter_parts),
            "-map", map_label,
            "-c:a", "libvorbis",
            "-q:a", "2",
            "-page_duration", str(PAGE_DURATION_US),
            "-f", "ogg",
            str(ogg_tmp)
        ])
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg multi-channel merge failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed to build MOGG container: {result.stderr}")
        try:
            ogg_bytes = ogg_tmp.read_bytes()
        finally:
            ogg_tmp.unlink(missing_ok=True)
        if not ogg_bytes:
            raise RuntimeError("FFmpeg produced an empty Ogg file.")
        mogg_bytes = wrap_ogg_as_mogg(ogg_bytes)
        mogg_path.write_bytes(mogg_bytes)
        logger.info(f"Built MOGG (v{MOGG_VERSION_UNENCRYPTED}, {len(mogg_bytes)} bytes) at {mogg_path}")
    else:
        logger.warning("No stem WAV files found. Generating placeholder MOGG container.")
        mogg_path.write_bytes(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 200)

    return mogg_path
