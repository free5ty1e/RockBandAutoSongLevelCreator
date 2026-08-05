#!/usr/bin/env python

from pathlib import Path
import json
import logging
import struct

logger = logging.getLogger(__name__)

def encode_varlen(value: int) -> bytes:
    """Encodes an integer into MIDI variable-length quantity (VLQ)."""
    if value < 0:
        value = 0
    
    buffer = value & 0x7F
    res = bytearray()
    res.append(buffer)
    
    value >>= 7
    while value > 0:
        buffer = (value & 0x7F) | 0x80
        res.append(buffer)
        value >>= 7
        
    res.reverse()
    return bytes(res)

PLACEHOLDER_NOTE_PITCH = 60
PLACEHOLDER_DIFFICULTY_PITCHES = (60, 72, 84, 96)

# Mandatory count-in, per the C3 authoring guide: very fast songs (>=160 BPM)
# need a 3-measure count-in. Sized at runtime from the song's opening tempo
# (first beat-grid interval), mirroring stock RB3 DLC (311 - Down bakes ~5s of
# lead-in silence into its MOGG).
COUNT_IN_BEATS = 12  # 3 measures * 4 beats


def count_in_params(beat_times, ticks_per_beat: int = 480) -> tuple[int, int]:
    """Return ``(count_in_ticks, count_in_ms)`` for the mandatory lead-in.

    Uses the song's opening tempo (first beat-grid interval) to size a
    3-measure count-in. Returns ``(0, 0)`` when no usable beat grid exists,
    which disables the count-in entirely.
    """
    beats = [float(b) for b in (beat_times or []) if b is not None]
    if len(beats) < 2:
        return 0, 0
    opening_sec = beats[1] - beats[0]
    count_in_ticks = COUNT_IN_BEATS * ticks_per_beat
    count_in_ms = int(round(COUNT_IN_BEATS * opening_sec * 1000))
    return count_in_ticks, count_in_ms

def build_track(name: str, events_bytes: bytes) -> bytes:
    """Wraps MIDI events into a single named MTrk chunk."""
    name_chunk = b"\x00\xFF\x03" + bytes([len(name)]) + name.encode('ascii')
    content = name_chunk + events_bytes + b"\x00\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(content)) + content


def build_events_track(
    first_note_tick: int,
    last_note_end_tick: int,
    preview_start_tick: int,
    count_in_ticks: int = 0,
) -> bytes:
    """Builds the EVENTS track with the required Rock Band text markers.

    Stock RB3 charts always carry ``[music_start]``, ``[preview]``,
    ``[music_end]`` and ``[end]`` in the EVENTS track.  ForgeTool/Magma
    hard-errors on charts missing them, and in-game the missing ``[preview]``
    marker kills the song-list preview while a missing ``[music_end]``/``[end]``
    makes the song finish instantly at 0% (with a full-combo jingle) because
    the game believes the chart ends immediately.

    ``[prc_intro]`` and ``[music_start]`` are placed at ``count_in_ticks`` (the
    end of the count-in) rather than tick 0, mirroring stock charts where the
    intro markers sit after the silent lead-in (311 - Down: ``[music_start]``
    at 5280).
    """
    events = bytearray()

    # Assign a tick to each marker (text events carry deltas too).
    markers = [
        (count_in_ticks, "[prc_intro]"),
        (count_in_ticks, "[music_start]"),
        (first_note_tick, "[prc_verse_1]"),
        (preview_start_tick, "[preview]"),
        ((first_note_tick + last_note_end_tick) // 2, "[prc_chorus_1]"),
        (max(first_note_tick, last_note_end_tick - 1920), "[prc_outro]"),
        (last_note_end_tick, "[music_end]"),
        (last_note_end_tick + 2400, "[end]"),
    ]
    prev = 0
    for tick, label in markers:
        delta = max(0, tick - prev)
        events.extend(encode_varlen(delta))
        events.extend(b"\xFF\x01" + bytes([len(label)]) + label.encode("latin1"))
        prev = tick

    return build_track("EVENTS", bytes(events))


def build_placeholder_track(name: str, pitches: tuple = PLACEHOLDER_DIFFICULTY_PITCHES,
                            start_tick: int = 0) -> bytes:
    """Builds a minimal valid instrument track with one note per difficulty.

    ``start_tick`` offsets the gem cluster past the count-in (tick 0 is the
    start of the lead-in silence, so notes must land after it).
    """
    events = bytearray()
    for i, pitch in enumerate(pitches):
        delta = max(0, start_tick) if i == 0 else 0
        events.extend(encode_varlen(delta))
        events.extend(b"\x90" + bytes([pitch, 100]))
    for pitch in pitches:
        events.extend(encode_varlen(120 if pitch == pitches[0] else 0))
        events.extend(b"\x80" + bytes([pitch, 0]))
    return build_track(name, bytes(events))

def generate_vocal_midi(synced_json_path: str | Path, output_dir: Path, song_id: str,
                        preview_start_ms: int = 50000, song_length_ms: int | None = None,
                        phrase_measures: int = 2, bpm: float = 120.0,
                        beat_times: list | None = None, dynamic_bpms: list | None = None,
                        count_in_ticks: int = 0, count_in_ms: int = 0) -> Path:
    """
    Generates a fully compliant Rock Band PART VOCALS MIDI chart from synchronized JSON data.
    Includes placeholder PART DRUMS, PART GUITAR, and PART BASS tracks (one note each) so that
    every instrument advertised in songs.dta has a corresponding chart track.

    ``count_in_ticks`` shifts the whole chart so tick 0 is the start of the
    MOGG's count-in silence and the first musical event lands at
    ``count_in_ticks``. This mirrors stock RB3 DLC where the MOGG bakes in a
    silent lead-in (311 - Down has ~5s before its first note) and keeps the
    first vocal phrase well past ForgeTool's 640-tick ``StartTicks - 640``
    offset, which underflows to ~4294966967 when a chart starts its first
    phrase at tick < 640 (making the first phrase StartMillis land at end of
    song and the vocal guide broken).

    Vocal phrase markers (pitch 105) group the lyrics into fixed-length phrases of
    ``phrase_measures`` measures (Rock Band convention is 2 or 4 bars per phrase).

    Tempo map: when ``beat_times``/``dynamic_bpms`` (the beat-tracked grid from
    ``tempo_map.json``) are provided, the tempo track carries a **dynamic tempo map**
    with a ``set_tempo`` event per beat interval and every note/beat tick is derived
    from the real beat grid (tick 480*i == ``beat_times[i]``). This mirrors stock RB3
    charts (311 - Down changes tempo every ~2 bars) and keeps the chart perfectly
    synced to the audio, eliminating the progressive lyric drift a single averaged
    BPM causes. Falls back to a flat ``bpm`` when no beat grid is available.
    """
    json_path = Path(synced_json_path)
    midi_path = output_dir / f"{song_id}.mid"
    
    track_data = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            track_data = json.load(f)

    header = b"MThd" + struct.pack(">IHHH", 6, 1, 7, 480)

    ticks_per_beat = 480
    beats_per_measure = 4
    phrase_ticks = phrase_measures * beats_per_measure * ticks_per_beat

    # Build the time->tick mapping + per-beat tempo events from the beat grid.
    time_to_tick, tempo_events = _build_tempo_grid(
        beat_times, dynamic_bpms, bpm=120.0 if not (bpm and bpm > 0) else bpm,
        ticks_per_beat=ticks_per_beat,
    )

    # The audio pipeline prepends count_in_ms of silence to the MOGG; shift every
    # chart event by the equivalent ticks so tick 0 == start of that silence.
    def shifted_time_to_tick(sec: float) -> int:
        return time_to_tick(sec) + count_in_ticks

    if count_in_ticks > 0 and tempo_events:
        # The count-in clicks at the song's opening tempo (first real beat
        # interval, tempo_events[1]); tick 0 must carry it so the game's clock
        # runs at the right BPM through the lead-in silence. All source-grid
        # tempo events then shift past the count-in.
        opening_us = tempo_events[1][1] if len(tempo_events) > 1 else tempo_events[0][1]
        tempo_events = [(0, opening_us)] + [
            (t + count_in_ticks, us) for t, us in tempo_events
        ]

    items = []
    if isinstance(track_data, dict):
        items = track_data.get("synced_lyrics", track_data.get("synced_words", []))
    elif isinstance(track_data, list):
        items = track_data

    try:
        items = sorted(items, key=lambda x: x.get("start", 0.0))
    except Exception:
        pass

    last_event_tick = 0
    first_note_tick = None
    last_note_end_tick = 0

    vocal_events = bytearray()

    last_tick = 0
    current_phrase_idx = None

    for item in items:
        start_sec = item.get("start", item.get("time", item.get("beat_time", 0.0)))
        end_sec = item.get("end", start_sec + 0.5)
        lyric = item.get("word", item.get("lyric", "la"))
        pitch = item.get("pitch", 60)

        target_start_tick = shifted_time_to_tick(start_sec)
        target_end_tick = max(target_start_tick + 48, shifted_time_to_tick(end_sec))

        phrase_idx = target_start_tick // phrase_ticks

        if current_phrase_idx is None:
            # Open the first phrase at the first note.
            vocal_events.extend(encode_varlen(max(0, target_start_tick - last_tick)))
            vocal_events.extend(b"\x90\x69\x64")  # phrase start: pitch 105, vel 100
            last_tick = target_start_tick
            current_phrase_idx = phrase_idx
        elif phrase_idx != current_phrase_idx:
            # The phrase window rolled over: close the previous phrase at the end
            # of its last note and open the next one at this note's start.
            vocal_events.extend(encode_varlen(0))
            vocal_events.extend(b"\x80\x69\x00")  # phrase end: pitch 105, vel 0
            vocal_events.extend(encode_varlen(max(0, target_start_tick - last_tick)))
            vocal_events.extend(b"\x90\x69\x64")
            last_tick = target_start_tick
            current_phrase_idx = phrase_idx

        # Note
        delta_on = max(0, target_start_tick - last_tick)
        duration = max(48, target_end_tick - target_start_tick)

        vocal_events.extend(encode_varlen(delta_on))
        vocal_events.extend(b"\x90" + bytes([pitch, 100]))

        lyric_bytes = lyric.encode('utf-8')
        vocal_events.extend(b"\x00\xFF\x05" + bytes([len(lyric_bytes)]) + lyric_bytes)

        vocal_events.extend(encode_varlen(duration))
        vocal_events.extend(b"\x80" + bytes([pitch, 0]))

        last_tick = target_start_tick + duration

        if first_note_tick is None:
            first_note_tick = target_start_tick
        last_note_end_tick = max(last_note_end_tick, last_tick)

    # Close the final phrase at the end of the last note.
    if current_phrase_idx is not None:
        vocal_events.extend(encode_varlen(0))
        vocal_events.extend(b"\x80\x69\x00")

    if not items:
        vocal_events.extend(
            b"\x00\x90\x3C\x64" +
            b"\x00\xFF\x05\x02la" +
            b"\x83\x60\x80\x3C\x00"
        )
        first_note_tick = 0
        last_note_end_tick = 480

    if song_length_ms is None:
        song_length_ms = int(last_note_end_tick / 480 * 60_000 / (bpm if bpm and bpm > 0 else 120.0)) + 1000
    # song_length_ms is the full MOGG duration, which now includes the count-in
    # silence prepended by the audio pipeline. The chart content lives past the
    # count-in, so map only the source portion through the beat grid, then add
    # the count-in tick offset back on.
    source_len_ms = max(0, song_length_ms - count_in_ms)
    song_end_tick = shifted_time_to_tick(source_len_ms / 1000.0)
    # The BEAT track must cover the whole song, so base its length on the tempo map,
    # not on a hardcoded 120 BPM (which left the grid short at faster tempos).
    total_beats = max(1, song_end_tick // ticks_per_beat + 2)

    # Track 0: tempo map (name = song id, mirroring stock RB3 charts like 311 - Down).
    # Carries a dynamic tempo map (one set_tempo per beat interval) when the beat
    # grid is available, so the game clock tracks the audio exactly.
    tempo_data = (
        b"\x00\xFF\x58\x04\x04\x02\x18\x08" +  # 4/4 Time Signature
        _build_tempo_events(tempo_events)
    )
    t0 = build_track(song_id, tempo_data)

    # Track 1-4: instrument charts
    t1 = build_placeholder_track("PART DRUMS", start_tick=count_in_ticks)
    t2 = build_placeholder_track("PART BASS", start_tick=count_in_ticks)
    t3 = build_placeholder_track("PART GUITAR", start_tick=count_in_ticks)
    t4 = build_track("PART VOCALS", bytes(vocal_events))

    # Track 5: EVENTS with the required [music_start]/[preview]/[music_end]/[end] markers
    t5 = build_events_track(
        first_note_tick=first_note_tick or count_in_ticks,
        last_note_end_tick=max(last_note_end_tick, song_end_tick),
        preview_start_tick=shifted_time_to_tick(preview_start_ms / 1000.0),
        count_in_ticks=count_in_ticks,
    )

    # Track 6: BEAT - one quarter-note marker per beat (downbeat pitch 12 vel 101,
    # other beats pitch 13 vel 100), spaced 480 ticks apart like stock charts.
    beat_events = bytearray()
    for i in range(total_beats):
        pitch = 12 if i % 4 == 0 else 13
        vel = 101 if i % 4 == 0 else 100
        beat_events.extend(encode_varlen(0))
        beat_events.extend(b"\x90" + bytes([pitch, vel]))
        beat_events.extend(encode_varlen(480))
        beat_events.extend(b"\x80" + bytes([pitch, 0]))
    t6 = build_track("BEAT", bytes(beat_events))

    with open(midi_path, "wb") as f:
        f.write(header)
        f.write(t0)
        f.write(t1)
        f.write(t2)
        f.write(t3)
        f.write(t4)
        f.write(t5)
        f.write(t6)

    logger.info(f"Generated complete vocal MIDI chart at {midi_path}")
    return midi_path


def _build_tempo_grid(beat_times, dynamic_bpms, bpm, ticks_per_beat=480):
    """Returns ``(time_to_tick, tempo_events)``.

    ``time_to_tick(seconds)`` maps an audio timestamp to a MIDI tick via linear
    interpolation on the beat grid (tick 480*i == beat_times[i]). ``tempo_events``
    is a list of ``(tick, tempo_us_per_beat)`` with one entry per beat interval,
    reproducing that exact grid through the MIDI tempo track.

    Without a usable beat grid, falls back to a flat ``bpm`` map.
    """
    beats = [float(x) for x in (beat_times or []) if x is not None]
    bpms = list(dynamic_bpms or [])

    if len(beats) < 2:
        bpm = bpm if bpm and bpm > 0 else 120.0
        us = int(60_000_000 / bpm)

        def flat_to_tick(t):
            return int(t * ticks_per_beat * bpm / 60.0)

        return flat_to_tick, [(0, us)]

    # Anchor tick 0 to audio time 0. The beat tracker starts its grid at
    # beat_times[0] (>0 usually), so without a virtual beat at t=0 the whole
    # chart is shifted early by that constant lead-in and lyrics never align
    # with the audio. Prepend a virtual beat at t=0 with the first interval's
    # tempo so tick 0 == audio 0 and the real first beat lands on its true tick.
    if beats[0] > 1e-6:
        beats = [0.0] + beats

    n = len(beats)
    # Local BPM between consecutive beats; fall back to `bpm` when missing/zero.
    intervals_us = []
    for i in range(n - 1):
        dur = beats[i + 1] - beats[i]
        if dur > 0:
            intervals_us.append(int(60_000_000 / (60.0 / dur)))
        else:
            intervals_us.append(int(60_000_000 / (bpm if bpm and bpm > 0 else 120.0)))

    first_us = intervals_us[0]
    last_us = intervals_us[-1]
    sec_per_beat_first = first_us / 1_000_000.0
    sec_per_beat_last = last_us / 1_000_000.0

    def grid_to_tick(t):
        if t <= beats[0]:
            return max(0, int(t * ticks_per_beat / sec_per_beat_first))
        if t >= beats[-1]:
            tail = t - beats[-1]
            return (n - 1) * ticks_per_beat + int(tail * ticks_per_beat / sec_per_beat_last)
        # Binary search for the interval containing t.
        lo, hi = 0, n - 2
        while lo <= hi:
            mid = (lo + hi) // 2
            if beats[mid] <= t <= beats[mid + 1]:
                frac = (t - beats[mid]) / (beats[mid + 1] - beats[mid])
                return mid * ticks_per_beat + int(frac * ticks_per_beat)
            elif t < beats[mid]:
                hi = mid - 1
            else:
                lo = mid + 1
        return max(0, int(t * ticks_per_beat / sec_per_beat_first))

    # One set_tempo event per beat interval, starting at tick 0.
    tempo_events = []
    for i, us in enumerate(intervals_us):
        tempo_events.append((i * ticks_per_beat, us))
    tempo_events.append(((n - 1) * ticks_per_beat, last_us))

    return grid_to_tick, tempo_events


def _build_tempo_events(tempo_events):
    """Encodes a list of (tick, tempo_us) as chained FF 51 03 set_tempo events.

    Consecutive entries with the same tempo are collapsed, and the first event is
    placed at tick 0 (it may repeat tick 0's tempo, which is harmless).
    """
    if not tempo_events:
        return b"\x00\xFF\x51\x03\x07\xA1\x20"

    # Sort + dedupe consecutive identical tempos, guaranteeing a tick-0 event.
    evs = sorted(tempo_events, key=lambda e: e[0])
    deduped = []
    for tick, us in evs:
        if not deduped or deduped[-1][1] != us:
            deduped.append((tick, us))

    # Ensure there is an event at tick 0.
    if deduped[0][0] != 0:
        deduped.insert(0, (0, deduped[0][1]))

    out = bytearray()
    prev = 0
    for tick, us in deduped:
        delta = max(0, tick - prev)
        out.extend(encode_varlen(delta))
        out.extend(b"\xFF\x51\x03" + int(us).to_bytes(3, "big"))
        prev = tick
    return bytes(out)
