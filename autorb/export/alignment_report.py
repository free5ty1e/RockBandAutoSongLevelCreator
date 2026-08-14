#!/usr/bin/env python
"""Headless sync validation: charted-note-vs-audio alignment report + lyrics SRT.

Reads the pipeline artifacts (``synced_track.json``, the Clone Hero ``notes.mid``
chart, and the vocal stem WAV) and produces:

1. ``lyrics_preview.srt`` — karaoke-style subtitles from the charted word
   timings. Load it alongside ``preview_mix.wav`` in any subtitle-capable player
   (VLC, MPV) to review lyric↔audio sync with full seek/rewind — no PS4 needed.
2. ``alignment_report.json`` — for every charted word, the charted audio time
   (recovered from the MIDI tempo map, so it is exactly what the game reads)
   vs the nearest real vocal onset in the vocal stem. Summaries (median/p90 of
   absolute error, counts of early/late outliers) give a pass/fail signal that
   an agent can iterate against without a human in the loop.
3. ``alignment_*.png`` — annotated waveform + spectrogram around each flagged
   outlier (charted time dashed, detected onset solid) for visual inspection.

This is the automated half of the "rapid local iteration" loop: the developer
(or an agent) rebuilds the song, regenerates this report, and reads off exactly
which words still don't land on the sung audio.
"""

from pathlib import Path
import json
import logging

import numpy as np

logger = logging.getLogger(__name__)

# A word is flagged when its charted start differs from the nearest vocal onset
# by more than this many seconds either direction.
LATE_THRESH_S = 0.30
EARLY_THRESH_S = 0.30
# Search window around the charted start for the true vocal onset (mirrors the
# pipeline's ONSET_SEARCH_BEFORE / ONSET_SEARCH_AFTER constants).
ONSET_SEARCH_BEFORE = 1.50
ONSET_SEARCH_AFTER = 0.05
# Max number of outlier spectrograms to render (keeps the report cheap).
MAX_SPECS = 8


def _srt_time(sec: float) -> str:
    """Format seconds as SRT's HH:MM:SS,mmm."""
    ms = max(0, int(round(sec * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, mmm = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{mmm:03d}"


def build_lyrics_srt(synced_json: str | Path, out_path: str | Path, offset_ms: int = 0) -> Path:
    """Write a karaoke .srt from the charted word timings.

    ``offset_ms`` shifts all entries (e.g. if the preview audio carries a lead-in).
    """
    with open(synced_json, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("synced_lyrics", data.get("synced_words", []))
    items = sorted(items, key=lambda w: w.get("start", 0.0))

    off = offset_ms / 1000.0
    lines: list[str] = []
    for i, w in enumerate(items, start=1):
        start = w.get("start", 0.0) + off
        end = w.get("end", start + 0.4) + off
        text = w.get("word", "") or " "
        # Subtitle per word, kept on screen for the note's duration.
        lines.append(str(i))
        lines.append(f"{_srt_time(start)} --> {_srt_time(end)}")
        lines.append(text)
        lines.append("")

    out = Path(out_path)
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Wrote lyrics preview subtitle file: {out} ({len(items)} entries)")
    return out


def _tick_to_sec(mid_path: Path) -> callable:
    """Return a ``tick -> seconds`` function by integrating the MIDI tempo map.

    This is the exact inverse of the generator's ``grid_to_tick``, so a note's
    charted tick converts back to the audio time the game plays it at.
    """
    import mido

    mf = mido.MidiFile(mid_path)
    tempos: list[tuple[int, int]] = []
    for tr in mf.tracks:
        tick = 0
        for msg in tr:
            tick += msg.time
            if msg.type == "set_tempo":
                tempos.append((tick, msg.tempo))
    if not tempos:
        tempos = [(0, 500000)]

    def f(tick: int) -> float:
        sec = 0.0
        prev = 0
        cur = tempos[0][1]
        for et, us in tempos[1:]:
            if tick <= et:
                return sec + (tick - prev) / 480.0 * cur / 1e6
            sec += (et - prev) / 480.0 * cur / 1e6
            prev, cur = et, us
        return sec + (tick - prev) / 480.0 * cur / 1e6

    return f


def _charted_vocal_times(mid_path: Path) -> list[tuple[int, float]]:
    """Return (tick, lyric) for every charted vocal note (phrase markers excluded)."""
    import mido

    mf = mido.MidiFile(mid_path)
    voc = next((t for t in mf.tracks if t.name == "PART VOCALS"), None)
    if voc is None:
        return []
    out: list[tuple[int, str]] = []
    abs_tick = 0
    pending: int | None = None
    for msg in voc:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.note != 105:
            pending = abs_tick
        elif msg.type == "lyrics" and pending is not None:
            out.append((pending, msg.text))
            pending = None
        elif msg.type == "note_off":
            pending = None
    return out


def _vocal_onset_times(vocals_stem: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Detect vocal onsets in the stem audio: returns (onset_times, hop-ms)."""
    import librosa

    y, sr = librosa.load(str(vocals_stem), sr=22050, mono=True)
    o_env = librosa.onset.onset_strength(y=y, sr=sr)
    frames = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, backtrack=True)
    times = librosa.frames_to_time(frames, sr=sr)
    hop = librosa.frames_to_time(1, sr=sr)
    return np.asarray(times, dtype=float), float(hop)


def build_alignment_report(
    synced_json: str | Path,
    notes_mid: str | Path,
    vocals_stem: str | Path,
    out_json: str | Path,
    spec_dir: str | Path | None = None,
    max_specs: int = MAX_SPECS,
) -> Path:
    """Compare every charted vocal note's audio time against the vocal stem.

    Writes a JSON report: per-word charted-vs-onset delta, summary statistics,
    and (when ``spec_dir`` is given) annotated spectrograms of the worst
    outliers. Returns the report path.
    """
    with open(synced_json, encoding="utf-8") as f:
        data = json.load(f)
    words = sorted(data.get("synced_lyrics", data.get("synced_words", [])), key=lambda w: w.get("start", 0.0))

    notes = _charted_vocal_times(Path(notes_mid))
    if not notes:
        notes = [(w.get("start", 0.0), w.get("word", "")) for w in words]
    t2s = _tick_to_sec(Path(notes_mid))

    onset_times, _hop = _vocal_onset_times(vocals_stem)

    rows = []
    for (tick, lyric), w in zip(notes, words):
        charted = t2s(tick)
        before = onset_times[(onset_times >= charted - ONSET_SEARCH_BEFORE) & (onset_times <= charted + ONSET_SEARCH_AFTER)]
        if len(before):
            onset = float(before[-1])  # latest onset at-or-before the boundary
        else:
            onset = float("nan")
        delta = (onset - charted) if np.isfinite(onset) else float("nan")
        late = np.isfinite(delta) and delta > LATE_THRESH_S
        early = np.isfinite(delta) and delta < -EARLY_THRESH_S
        rows.append({
            "index": len(rows),
            "lyric": lyric,
            "charted_sec": round(charted, 3),
            "nearest_onset_sec": round(onset, 3) if np.isfinite(onset) else None,
            "delta_sec": round(delta, 3) if np.isfinite(delta) else None,
            "flag": "late" if late else ("early" if early else "ok"),
        })

    deltas = np.array([r["delta_sec"] for r in rows if r["delta_sec"] is not None])
    summary = {
        "n_words": len(rows),
        "n_late": sum(1 for r in rows if r["flag"] == "late"),
        "n_early": sum(1 for r in rows if r["flag"] == "early"),
        "n_ok": sum(1 for r in rows if r["flag"] == "ok"),
        "median_abs_delta_s": round(float(np.median(np.abs(deltas))), 3) if len(deltas) else None,
        "p90_abs_delta_s": round(float(np.percentile(np.abs(deltas), 90)), 3) if len(deltas) else None,
        "max_abs_delta_s": round(float(np.max(np.abs(deltas))), 3) if len(deltas) else None,
        "thresholds_s": {"early": EARLY_THRESH_S, "late": LATE_THRESH_S},
    }
    report = {"summary": summary, "words": rows}

    out = Path(out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if spec_dir is not None:
        flagged = [r for r in rows if r["flag"] != "ok" and r["delta_sec"] is not None]
        flagged.sort(key=lambda r: abs(r["delta_sec"]), reverse=True)
        for r in flagged[:max_specs]:
            _render_alignment_spec(vocals_stem, r, Path(spec_dir), t2s=t2s)

    logger.info(
        f"Alignment report: {summary['n_ok']}/{summary['n_words']} ok, "
        f"{summary['n_late']} late, {summary['n_early']} early "
        f"(median |delta| {summary['median_abs_delta_s']}s, p90 {summary['p90_abs_delta_s']}s)"
    )
    return out


def _render_alignment_spec(vocals_stem: str | Path, row: dict, spec_dir: Path, t2s=None) -> Path | None:
    """Render an annotated waveform + spectrogram around a flagged word."""
    try:
        import librosa
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        logger.warning(f"Could not render spectrogram ({e}); skipping")
        return None

    center = row["charted_sec"]
    win = 2.0
    y, sr = librosa.load(str(vocals_stem), sr=22050, mono=True)
    seg = y[int(max(0, center - win) * sr):int((center + win) * sr)]
    spec_dir.mkdir(parents=True, exist_ok=True)

    fig, (ax0, ax1) = plt.subplots(
        2, 1, figsize=(12, 6),
        gridspec_kw={"height_ratios": [1, 3]},
    )
    times = np.linspace(center - win, center + win, len(seg))
    ax0.plot(times, seg, lw=0.6)
    ax0.set_ylabel("wave")
    ax0.axvline(center, color="r", ls="--", lw=1.2, label="charted")
    if row.get("nearest_onset_sec") is not None:
        ax0.axvline(row["nearest_onset_sec"], color="g", ls=":", lw=1.2, label="onset")
    ax0.legend(fontsize=7)

    S = librosa.feature.melspectrogram(y=seg, sr=sr, n_mels=64)
    librosa.display.specshow(librosa.power_to_db(S, ref=np.max), sr=sr, x_axis="time",
                             y_axis="mel", ax=ax1,
                             x_coords=np.linspace(center - win, center + win, S.shape[1]))
    ax1.axvline(center, color="r", ls="--", lw=1.2, label="charted")
    if row.get("nearest_onset_sec") is not None:
        ax1.axvline(row["nearest_onset_sec"], color="g", ls=":", lw=1.2, label="onset")
    ax1.set_title(f"{row['index']}: '{row['lyric']}' charted={row['charted_sec']}s "
                  f"delta={row['delta_sec']}s [{row['flag']}]")
    fig.tight_layout()
    png = spec_dir / f"alignment_{row['index']:03d}_{row['flag']}.png"
    fig.savefig(png, dpi=110)
    plt.close(fig)
    return png
