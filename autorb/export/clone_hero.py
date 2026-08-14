#!/usr/bin/env python
"""Clone Hero song-folder exporter (--build-clone-hero).

Builds a standard, Clone Hero-compliant song folder from the pipeline's existing
artifacts so a custom AutoRB chart can be loaded and playtested on a computer
without a PS4 (and without the unseekable MOGG / count-in the Rock Band CON
requires). This is the recommended local review loop for sync iteration.

Clone Hero requirements (https://wiki.clonehero.net/books/clone-hero-manual):
- each song lives in its own folder inside the Songs directory (any number of
  nested group folders are allowed) and must contain at minimum:
    * ``notes.mid`` *or* ``notes.chart`` — we write **both** (the .chart is
      derived from the count-in-free notes.mid; CH accepts either, and the
      .chart parser is the most battle-tested import path)
    * an audio file (``song.ogg``/``song.mp3``/``song.wav``/``song.flac``)
    * ``song.ini`` carrying the song metadata (name + artist at minimum)
- ``song_length`` and ``preview_start_time`` in ``song.ini`` are milliseconds.

Because the CH song has no Rock Band count-in, the chart is re-generated with
``count_in_ticks=0``/``count_in_ms=0`` and the audio is a plain stereo stem mix
(no adelay silence), so chart ticks and audio time agree exactly — this is what
makes rapid, rewindable sync review possible in-game.
"""

from pathlib import Path
import logging
import re
import subprocess

import mido

from autorb.audio.mix_preview import mix_stems
from autorb.export.midi_generator import generate_vocal_midi

logger = logging.getLogger(__name__)

CHARTER_NAME = "AutoRB"

#: The four .chart difficulty sections, in ascending difficulty order.
CHART_DIFFICULTIES = ("Easy", "Medium", "Hard", "Expert")


def midi_to_chart_file(
    midi_path: Path,
    out_path: Path,
    title: str,
    artist: str,
    album: str | None = None,
    genre: str | None = None,
    year: int | None = None,
    charter: str = CHARTER_NAME,
) -> Path:
    """Convert a count-in-free AutoRB ``notes.mid`` into a Clone Hero ``notes.chart``.

    Clone Hero reads either ``notes.mid`` or ``notes.chart``, so emitting both
    maximizes compatibility (CH's .chart reader is the most battle-tested
    import path — a MIDI-only folder is silently rejected if any MIDI quirk
    trips its parser). Lyrics are written exactly the way Moonscraper (the CH
    ecosystem's canonical editor) writes them: as ``[Events]``
    ``phrase_start``/``phrase_end``/``lyric <text>`` events (with one
    ``phrase`` per pitch-105 phrase marker), and the vocal notes as
    ``tick = N <pitch> <sustain>`` on the four difficulty sections. Placeholder
    instrument notes are emitted lane-encoded (``pitch % 12``) so the guitar /
    bass / drums sections stay loadable too.
    """
    mf = mido.MidiFile(str(midi_path))
    ticks_per_beat = mf.ticks_per_beat

    tempo_events: list[tuple[int, str, list]] = []  # (tick, kind, args)
    bpm_events: list[tuple[int, float]] = []  # (tick, exact BPM)
    for tick, msg in _iter_abs(mf.tracks[0]):
        if msg.type == "time_signature":
            if msg.denominator == 4:
                tempo_events.append((tick, "TS", [str(msg.numerator)]))
            else:
                log2_den = int(round(msg.denominator.bit_length() - 1))
                tempo_events.append((tick, "TS", [str(msg.numerator), str(log2_den)]))
        elif msg.type == "set_tempo":
            bpm_events.append((tick, 60_000_000.0 / msg.tempo))
    if bpm_events:
        # Moonscraper (and the Clone Hero reader it was forked from) parse the
        # B field as an *integer* plain-BPM via uint.TryParse and silently DROP
        # any line with a fractional value — writing a float here leaves the
        # chart with no tempo map and the song gets rejected at scan time. The
        # B field cannot carry fractional tempos, so we emit an integer map
        # that cancels the accumulated rounding error: each event's BPM is
        # rounded as usual, but moved one step toward the ceiling/floor when
        # the chart has drifted > BPM_DRIFT_TOL_S from the exact MIDI timeline.
        # That keeps the .chart within ~35ms of the exact tempo over a whole
        # song (plain rounding accumulates ~+175ms of progressive lateness).
        # The notes.mid keeps the exact tempo; the .chart is the playtest copy.
        BPM_DRIFT_TOL_S = 0.020
        chart_bpms: list[tuple[int, int]] = []
        err_s = 0.0  # chart_time - exact_time at the current event tick
        for i, (tick, bpm) in enumerate(bpm_events):
            if i == 0:
                int_bpm = int(round(bpm))
            else:
                prev_tick, prev_exact = bpm_events[i - 1]
                prev_int = chart_bpms[-1][1]
                err_s += (tick - prev_tick) / ticks_per_beat * 60.0 / prev_int
                err_s -= (tick - prev_tick) / ticks_per_beat * 60.0 / prev_exact
                int_bpm = round(bpm)
                if err_s > BPM_DRIFT_TOL_S:
                    int_bpm = max(int_bpm, int(bpm) + 1)
                elif err_s < -BPM_DRIFT_TOL_S:
                    int_bpm = min(int_bpm, int(bpm))
            chart_bpms.append((tick, int(int_bpm)))
        tempo_events.extend((tick, "B", [str(b)]) for tick, b in chart_bpms)
    # Same-tick ordering: time signature before tempo (matches Moonscraper).
    tempo_events.sort(key=lambda e: (e[0], 0 if e[1] == "TS" else 1))

    events: list[tuple[int, int, str]] = []  # (tick, priority, text)
    vocal_notes: list[tuple[int, int, int, str]] = []  # (tick, pitch, sustain, lyric)
    instruments: dict[str, list[tuple[int, int, int]]] = {}

    for tr in mf.tracks:
        name = tr.name
        if name == "EVENTS":
            for tick, msg in _iter_abs(tr):
                if msg.type == "text" and msg.text:
                    text = msg.text.strip()
                    if text.startswith("[") and text.endswith("]"):
                        inner = text[1:-1].strip()
                        if inner.startswith("prc_"):
                            events.append((tick, 3, f"section {inner}"))
        elif name == "PART VOCALS":
            notes, lyrics, phrases = _extract_vocal_data(tr)
            lyric_for_tick = {on_tick: lyric for on_tick, lyric in lyrics.items()}
            vocal_notes = [
                (on_tick, pitch, sustain, lyric_for_tick.get(on_tick, ""))
                for on_tick, pitch, sustain in notes
            ]
            for start, end in phrases:
                events.append((start, 0, "phrase_start"))
                events.append((end, 2, "phrase_end"))
            for tick, lyric in sorted(lyrics.items()):
                events.append((tick, 1, f"lyric {lyric}"))
        elif name in ("PART GUITAR", "PART BASS", "PART DRUMS"):
            inst = name.replace("PART ", "")
            chart_inst = {"DRUMS": "Drums", "GUITAR": "Guitar", "BASS": "Bass"}[inst]
            notes = _extract_notes(tr, exclude=set())
            instruments[chart_inst] = [
                (tick, pitch % 12, sustain) for tick, pitch, sustain in notes
            ]

    events.sort(key=lambda e: (e[0], e[1]))

    lines: list[str] = []
    lines.append("[Song]")
    lines.append("{")
    lines.append(f'  Name = "{_chart_quote(title)}"')
    lines.append(f'  Artist = "{_chart_quote(artist)}"')
    if album:
        lines.append(f'  Album = "{_chart_quote(album)}"')
    if genre:
        lines.append(f'  Genre = "{_chart_quote(genre)}"')
    if year:
        lines.append(f"  Year = {int(year)}")
    lines.append(f'  Charter = "{_chart_quote(charter)}"')
    lines.append(f"  Resolution = {int(ticks_per_beat)}")
    lines.append("  Offset = 0")
    lines.append("}")

    lines.append("")
    lines.append("[SyncTrack]")
    lines.append("{")
    for tick, kind, args in tempo_events:
        lines.append(f"  {tick} = {kind} {' '.join(args)}")
    lines.append("}")

    lines.append("")
    lines.append("[Events]")
    lines.append("{")
    for tick, _, text in events:
        lines.append(f'  {tick} = E "{_chart_quote(text)}"')
    lines.append("}")

    for diff in CHART_DIFFICULTIES:
        lines.append("")
        lines.append(f"[{diff}Vocals]")
        lines.append("{")
        for tick, pitch, sustain, _lyric in sorted(vocal_notes):
            lines.append(f"  {tick} = N {pitch} {sustain}")
        lines.append("}")

    for inst in ("Guitar", "Bass", "Drums"):
        for diff in CHART_DIFFICULTIES:
            lines.append("")
            lines.append(f"[{diff}{inst}]")
            lines.append("{")
            for tick, lane, sustain in sorted(instruments.get(inst, [])):
                lines.append(f"  {tick} = N {lane} {sustain}")
            lines.append("}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _iter_abs(msgs):
    """Yield (absolute_tick, message) for a mido track."""
    tick = 0
    for msg in msgs:
        tick += msg.time
        yield tick, msg


def _extract_notes(events, exclude=None):
    """Return ``[(on_tick, pitch, sustain)]`` from a track of note events."""
    exclude = exclude or set()
    notes, active = [], {}
    for tick, msg in _iter_abs(events):
        if msg.type == "note_on":
            if msg.velocity > 0 and msg.note not in exclude:
                active[msg.note] = tick
            elif msg.velocity == 0 and msg.note not in exclude:
                on = active.pop(msg.note, None)
                if on is not None:
                    notes.append((on, msg.note, max(0, tick - on)))
        elif msg.type == "note_off" and msg.note not in exclude:
            on = active.pop(msg.note, None)
            if on is not None:
                notes.append((on, msg.note, max(0, tick - on)))
    return notes


def _extract_vocal_data(track):
    """Split a PART VOCALS track into notes, lyrics, and phrase markers.

    Returns ``(notes, lyric_by_note_tick, phrases)`` where ``lyric_by_note_tick``
    maps each note's on-tick to the lyric text that follows it (our generator
    writes one ``lyrics`` meta event immediately after each note_on), and
    ``phrases`` is ``[(start_tick, end_tick)]`` from the pitch-105 phrase
    markers.
    """
    notes = _extract_notes(track, exclude={105})
    lyric_by_note_tick: dict[int, str] = {}
    phrases: list[tuple[int, int]] = []
    current_note_tick = None
    phrase_start = None
    for tick, msg in _iter_abs(track):
        if msg.type == "note_on":
            if msg.velocity > 0:
                if msg.note == 105:
                    phrase_start = tick
                else:
                    current_note_tick = tick
            elif msg.note == 105 and phrase_start is not None:
                phrases.append((phrase_start, tick))
                phrase_start = None
        elif msg.type == "note_off":
            if msg.note == 105 and phrase_start is not None:
                phrases.append((phrase_start, tick))
                phrase_start = None
        elif msg.type in ("lyrics", "text"):
            if current_note_tick is not None and msg.text:
                lyric_by_note_tick.setdefault(current_note_tick, msg.text)
    return notes, lyric_by_note_tick, phrases


def _chart_quote(text: str) -> str:
    """Escape a string for a .chart quoted field.

    The .chart format has no escape sequences; Moonscraper substitutes a
    double-quote with a backtick for Clone Hero compatibility, which we mirror.
    """
    return str(text).replace('"', "`").replace("\n", " ").replace("\r", " ")


def sanitize_folder_name(name: str) -> str:
    """Make an arbitrary 'Artist - Title' string a safe folder name."""
    clean = re.sub(r'[<>:"/\\|?*]', "-", name)
    clean = re.sub(r"\s+", " ", clean)
    clean = re.sub(r"-+", "-", clean).strip(" .-")
    return clean or "autorb_song"


def encode_wav_to_ogg(wav_path: Path, ogg_path: Path) -> Path:
    """Encode a stereo WAV to Ogg Vorbis (preferring libvorbis).

    Falls back to the native ``vorbis`` encoder, and finally to leaving the WAV
    in place as ``song.wav`` (Clone Hero accepts WAV) if ffmpeg cannot encode
    Ogg at all, so --build-clone-hero never hard-fails on ffmpeg build quirks.
    """
    for codec in ("libvorbis", "vorbis"):
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(wav_path),
            "-c:a", codec, "-q:a", "5",
            str(ogg_path),
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0 and ogg_path.exists() and ogg_path.stat().st_size > 0:
            wav_path.unlink(missing_ok=True)
            return ogg_path
        logger.warning(f"ffmpeg {codec} encode failed ({result.stderr.strip()}); trying next codec")
        ogg_path.unlink(missing_ok=True)
    return wav_path


def build_clone_hero_song(
    output_dir: Path,
    song_id: str,
    title: str,
    artist: str,
    year: int,
    genre: str,
    stems_dir: Path,
    synced_json: Path,
    beat_times: list,
    dynamic_bpms: list,
    source_length_ms: int,
    avg_bpm: float = 120.0,
    preview_start_ms: int = 50000,
    album_art: Path | None = None,
) -> Path:
    """Export a Clone Hero song folder under ``<output_dir>/clone_hero/``.

    ``source_length_ms`` is the pre-count-in song length (the MOGG duration
    minus the Rock Band count-in), so the CH audio/chart match the source
    timeline exactly.

    Returns the path to the created song folder.
    """
    ch_root = Path(output_dir) / "clone_hero"
    folder = ch_root / sanitize_folder_name(f"{artist} - {title}")
    folder.mkdir(parents=True, exist_ok=True)

    # 1. Stereo mix of the 4 stems -> WAV -> Ogg Vorbis (no count-in silence).
    #    Re-runs keep an existing mix/ogg (mix is expensive; stems rarely change).
    mix_wav = folder / "song.wav"
    song_ogg = folder / "song.ogg"
    if song_ogg.exists() and song_ogg.stat().st_size > 0:
        pass  # keep the already-encoded mix
    else:
        if not mix_wav.exists():
            mix_stems(stems_dir, mix_wav)
        song_ogg = encode_wav_to_ogg(mix_wav, song_ogg)

    # 2. Chart: re-generate the MIDI with the count-in disabled so note ticks
    #    are on the exact audio timeline (CH has no Rock Band lead-in), then
    #    derive notes.chart from it. CH reads either file; shipping both
    #    maximizes loadability (the .chart parser is the most battle-tested).
    generate_vocal_midi(
        synced_json,
        folder,
        "notes",
        song_length_ms=max(0, int(source_length_ms)),
        bpm=avg_bpm,
        beat_times=list(beat_times or []),
        dynamic_bpms=list(dynamic_bpms or []),
        count_in_ticks=0,
        count_in_ms=0,
        preview_start_ms=preview_start_ms,
    )
    midi_to_chart_file(
        folder / "notes.mid",
        folder / "notes.chart",
        title=title,
        artist=artist,
        album=title,
        genre=genre,
        year=year,
    )

    # 3. song.ini metadata (name/artist are mandatory for CH scanning).
    ini = folder / "song.ini"
    lines = [
        "[Song]",
        f"name = {title}",
        f"artist = {artist}",
        f"album = {title}",
        f"genre = {genre}",
        f"year = {year}",
        f"charter = {CHARTER_NAME}",
        f"song_length = {int(max(0, source_length_ms))}",
        f"preview_start_time = {int(max(0, preview_start_ms))}",
        "diff_guitar = -1",
        "diff_rhythm = -1",
        "diff_bass = -1",
        "diff_drums = -1",
        "diff_vocals = -1",
        "",
    ]
    ini.write_text("\n".join(lines), encoding="utf-8")

    # 4. Album art (Clone Hero reads album.png / album.jpg).
    if album_art is not None and Path(album_art).exists():
        import shutil
        dest = folder / "album.png"
        shutil.copyfile(album_art, dest)

    logger.info(f"Clone Hero song exported to {folder} (audio={song_ogg.name})")
    return folder
