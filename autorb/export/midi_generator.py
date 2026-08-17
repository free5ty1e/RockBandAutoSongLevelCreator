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

# Pyphen for splitting words into display syllables
try:
    import pyphen
    _PYPHEN_DIC = pyphen.Pyphen(lang='en_GB')
except Exception:
    _PYPHEN_DIC = None


def _split_part_at_vowel(part: str):
    """Split a word part at a vowel-cluster boundary, roughly at its midpoint.

    Returns ``[left, right]`` (both non-empty) or ``None`` when the part has no
    usable vowel boundary (e.g. all consonants).
    """
    n = len(part)
    if n < 2:
        return None
    vowels = set("aeiouyAEIOUY")
    mid = n // 2
    best = None
    for i in range(n - 1):
        if part[i] in vowels:
            idx = i + 1
            score = abs(idx - mid)
            if best is None or score < best[0]:
                best = (score, idx)
    if best is None:
        return None
    idx = best[1]
    return [part[:idx], part[idx:]]


def _expand_syllables_to_segments(syllables: list, num_segments: int) -> list:
    """Expand a syllable list into exactly ``num_segments`` non-empty parts.

    Keeps pyphen's real syllable boundaries and only splits further (at vowel
    boundaries, then char-level as a last resort) when a single-syllable word
    has more pitch segments than syllables. Never pads with empty strings
    unless the word has fewer characters than segments (physically impossible
    to split further).
    """
    parts = list(syllables)
    while len(parts) < num_segments:
        idx = max(range(len(parts)), key=lambda i: len(parts[i]))
        if len(parts[idx]) < 2:
            break
        split = _split_part_at_vowel(parts[idx])
        if split is None:
            half = len(parts[idx]) // 2
            split = [parts[idx][:half], parts[idx][half:]]
        parts = parts[:idx] + split + parts[idx + 1:]
    if len(parts) < num_segments:
        parts = parts + [""] * (num_segments - len(parts))
    return parts


def split_syllable_for_display(text: str, num_segments: int) -> list:
    """
    Split a word into display sub-syllables for Rock Band lyric rendering.

    One sub-syllable per pitch segment. Rock Band re-renders the *previous*
    lyric on notes with empty text, which turns a single-syllable word with two
    pitch segments (e.g. "eighty" or "crack" carrying vibrato/slide segments)
    into an audible doubled word ("crack crack"). So every segment always gets
    non-empty text: pyphen's real syllable boundaries are preferred, and when
    there are more pitch segments than syllables the word is split further at
    vowel boundaries (never leaving an empty segment unless the word has fewer
    characters than segments).
    """
    if not text or num_segments <= 1:
        return [text] if num_segments > 0 else []

    if _PYPHEN_DIC is None:
        return _expand_syllables_to_segments([text], num_segments)

    positions = _PYPHEN_DIC.positions(text)
    if not positions:
        # Single syllable word with multiple pitch segments: expand, don't pad
        return _expand_syllables_to_segments([text], num_segments)

    # Build syllable texts from hyphenation positions
    syllables = []
    last = 0
    for pos in positions:
        syllables.append(text[last:pos])
        last = pos
    syllables.append(text[last:])

    if len(syllables) == num_segments:
        return syllables
    elif len(syllables) < num_segments:
        # More segments than syllables: expand the syllable parts further
        return _expand_syllables_to_segments(syllables, num_segments)
    else:
        # More syllables than segments: merge extras onto last segment
        return syllables[:num_segments-1] + ["".join(syllables[num_segments-1:])]

# Mandatory count-in, per the C3 authoring guide: very fast songs (>=160 BPM)
# need a 3-measure count-in. Sized at runtime from the song's opening tempo
# (first beat-grid interval), mirroring stock RB3 DLC (311 - Down bakes ~5s of
# lead-in silence into its MOGG).
COUNT_IN_BEATS = 12  # 3 measures * 4 beats

# Minimum |delta| between consecutive measure-level tempo events (in
# microseconds-per-beat) before a new set_tempo event is emitted. ~0.5 BPM at
# 169 BPM; keeps the tempo track sparse and smooth like stock RB3 charts.
TEMPO_MEASURE_TOL_US = 1000


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


def build_instrument_track(
    charts: dict,  # {difficulty: InstrumentChart}
    instrument: str,
    count_in_ticks: int,
    time_to_tick,
) -> bytes:
    """
    Build a Rock Band instrument track (GUITAR, BASS, DRUMS, KEYS) containing all 4 difficulties.
    
    Rock Band (ForgeTool) stores all difficulties in a single track, distinguished by
    pitch ranges (a packed MIDI where every instrument uses the same scheme):
    - Expert: base 96
    - Hard: base 84
    - Medium: base 72
    - Easy: base 60
    Each note's pitch is ``base + lane`` (lane 0-4); the raw 35-59 drum sound pitches and
    the true key pitches are NOT valid here (they crash ForgeTool's MIDI converter).
    
    Args:
        charts: Dict mapping difficulty -> InstrumentChart
        instrument: 'guitar', 'bass', 'drums', 'keys'
        count_in_ticks: Count-in offset
        time_to_tick: Function to convert seconds to MIDI ticks
    
    Returns:
        MTrk bytes for the instrument track (contains all 4 difficulties)
    """
    # If no real chart data, use the simple placeholder that ForgeTool expects
    if not charts or all(v is None for v in charts.values()):
        return build_placeholder_track(f"PART {instrument.upper()}", start_tick=count_in_ticks)
    
    # Lane base pitches per difficulty (Rock Band / ForgeTool packed-MIDI convention:
    # Easy 60-64 / Medium 72-76 / Hard 84-88 / Expert 96-100, lane = pitch - base).
    LANE_BASE = {
        'expert': 96,
        'hard': 84,
        'medium': 72,
        'easy': 60,
    }

    # Drum pitches (same across difficulties)
    DRUM_PITCHES = {
        'kick': 36,
        'snare': 38,
        'hihat': 42,
        'hihat_open': 46,
        'ride': 51,
        'crash': 49,
        'tom1': 48,
        'tom2': 45,
        'tom3': 43,
    }
    
    difficulties = ['expert', 'hard', 'medium', 'easy']

    # Collect all notes from all difficulties with their target pitches
    all_notes = []  # (tick, pitch, velocity, duration, difficulty)

    for diff in ['expert', 'hard', 'medium', 'easy']:
        # charts may be keyed by the Difficulty enum (from create_all_difficulties)
        # or by plain strings; resolve either way.
        chart = None
        if charts:
            for key in (diff, diff.upper(), diff.capitalize()):
                chart = charts.get(key)
                if chart is not None:
                    break
            if chart is None:
                from autorb.transcribe.instruments.difficulty import Difficulty
                chart = charts.get(Difficulty(diff))
        base = LANE_BASE[diff]
        
        if chart is None:
            # Should not happen since we handled all-None case above, but safety fallback
            pitch = LANE_BASE[diff] if instrument != 'drums' else 36
            all_notes.append((count_in_ticks, pitch, 100, 120, diff))
            continue
        
        notes = sorted(chart.notes, key=lambda n: n.time)
        
        for note in chart.notes:
            target_start = time_to_tick(note.time) + count_in_ticks
            target_end = target_start + int(note.length * 480 * 120 / 60) if note.length > 0 else target_start + 120
            
            # Determine MIDI pitch for this note.
            # ForgeTool (LibForge) requires difficulty-offset pitches for EVERY
            # instrument: Easy 60 / Medium 72 / Hard 84 / Expert 96, lane = key - base
            # (0-4). Raw 35-59 drum sound pitches and true key pitches are NOT accepted
            # by HandleDrumTrk/HandleGuitarBass (they hit the "Unhandled midi note"
            # branch, leaving the difficulty gem-track null and crashing GemTracks.Add
            # with a NullReferenceException). So drums and keys are lane-encoded exactly
            # like guitar/bass.
            if instrument in ('drums', 'keys'):
                lane = note.lane if note.lane is not None else 0
                if lane < 0 or lane > 4:
                    lane = 0
                pitch = base + lane
            else:
                # Rock Band 5-button guitar/bass charts have NO "open" notes; an
                # open-string hit is just a normal strum at its lane. `note.lane`
                # is -1 for open strings (see `fret_string_to_lane`), so clamp to
                # the valid 0-4 range — otherwise `base + (-1)` falls outside the
                # 60-100 difficulty ranges and ForgeTool drops the note.
                lane = note.lane if note.lane is not None else 0
                if lane < 0 or lane > 4:
                    lane = 0
                pitch = base + lane
            
            duration = max(48, int((note.length * 480 * 120 / 60)) if note.length > 0 else 120)
            all_notes.append((target_start, pitch, note.velocity, duration, diff))
    
    # Sort all notes by time, then by difficulty order (expert first for same time)
    diff_order = {'expert': 0, 'hard': 1, 'medium': 2, 'easy': 3}
    all_notes.sort(key=lambda x: (x[0], diff_order.get(x[4] if len(x) > 4 else 'expert', 0)))

    # Build a flat, time-sorted event list of note-on / note-off pairs. Writing
    # each note as a back-to-back (on, off) block and advancing last_tick by the
    # note DURATION (the old approach) displaced any simultaneous chord note to
    # AFTER the previous note ended, so chords never rendered as chords. Using a
    # flat list keyed on absolute tick (on before off at the same tick) keeps
    # simultaneous notes truly simultaneous.
    flat = []
    for target_start, pitch, velocity, duration, _ in all_notes:
        dur = max(48, duration)
        flat.append((target_start, 0, pitch, velocity))      # note-on
        flat.append((target_start + dur, 1, pitch, 0))        # note-off
    flat.sort(key=lambda e: (e[0], e[1]))

    events = bytearray()
    last_tick = 0
    for tick, typ, pitch, vel in flat:
        delta = max(0, tick - last_tick)
        events.extend(encode_varlen(delta))
        if typ == 0:
            events.extend(b"\x90" + bytes([pitch, vel]))
        else:
            events.extend(b"\x80" + bytes([pitch, 0]))
        last_tick = tick

    track_name = f"PART {instrument.upper()}"
    return build_track(track_name, bytes(events))


def build_all_instrument_tracks(
    guitar_charts: dict = None,
    bass_charts: dict = None,
    drum_charts: dict = None,
    keys_charts: dict = None,
    freestyle_drums: bool = False,
    count_in_ticks: int = 0,
    time_to_tick = None,
) -> list[bytes]:
    """
    Build all 4 instrument tracks (DRUMS, BASS, GUITAR, KEYS), each containing 4 difficulties.
    
    Returns list of 4 MTrk bytes: [drums, bass, guitar, keys]

    When ``freestyle_drums`` is True, the drum track is emitted as a single placeholder
    note (drum freestyle throughout the song) instead of using ``drum_charts``.
    """
    if time_to_tick is None:
        def time_to_tick(sec):
            return int(sec * 480 * 120 / 60)

    tracks = []

    if freestyle_drums:
        tracks.append(build_instrument_track({}, 'drums', count_in_ticks, time_to_tick))
    else:
        tracks.append(build_instrument_track(drum_charts or {}, 'drums', count_in_ticks, time_to_tick))
    tracks.append(build_instrument_track(bass_charts or {}, 'bass', count_in_ticks, time_to_tick))
    tracks.append(build_instrument_track(guitar_charts or {}, 'guitar', count_in_ticks, time_to_tick))
    tracks.append(build_instrument_track(keys_charts or {}, 'keys', count_in_ticks, time_to_tick))

    return tracks


def generate_vocal_midi(synced_json_path: str | Path, output_dir: Path, song_id: str,
                        preview_start_ms: int = 50000, song_length_ms: int | None = None,
                        phrase_measures: int = 2, bpm: float = 120.0,
                        beat_times: list | None = None, dynamic_bpms: list | None = None,
                        count_in_ticks: int = 0, count_in_ms: int = 0,
                        guitar_charts: dict = None,  # {diff: InstrumentChart}
                        bass_charts: dict = None,
                        drum_charts: dict = None,
                        keys_charts: dict = None,  # {diff: InstrumentChart}
                        freestyle_drums: bool = False) -> Path:
    """
    Generates a fully compliant Rock Band PART VOCALS MIDI chart from synchronized JSON data.
    Includes PART DRUMS, PART GUITAR, and PART BASS tracks. If instrument charts are provided,
    uses full transcriptions with all four difficulties; otherwise uses placeholder tracks.

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
    ``tempo_map.json``) are provided, the tempo track carries a **sparse,
    measure-level tempo map** (one ``set_tempo`` event per bar, tempo = that
    bar's mean interval, skipping bars within ~0.5 BPM of the last event). The
    raw per-beat grid would otherwise encode a dense, jittery map (391 events,
    alternating ~167/172 BPM) that makes the game drift progressively late;
    stock RB3 charts (311 - Down, Smells Like Nirvana) use ~70-90 smooth events
    spaced every 1-2 bars. Notes are still derived from the exact beat grid via
    ``time_to_tick``, and the map integrates to the true audio within ~0.3ms at
    every measure boundary. Falls back to a flat ``bpm`` when no beat grid is
    available.
    """
    json_path = Path(synced_json_path)
    midi_path = output_dir / f"{song_id}.mid"
    
    track_data = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            track_data = json.load(f)

    header = b"MThd" + struct.pack(">IHHH", 6, 1, 8, 480)

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
        # interval of the *raw* beat grid, matching count_in_params); tick 0
        # must carry it so the game's clock runs at the right BPM through the
        # lead-in silence. All source-grid tempo events then shift past the
        # count-in.
        raw_beats = [float(x) for x in (beat_times or []) if x is not None]
        if len(raw_beats) > 1:
            opening_us = int((raw_beats[1] - raw_beats[0]) * 1_000_000)
        else:
            opening_us = tempo_events[0][1]
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

    # Flatten all syllables with their note segments into a single timeline.
    # Each item (word) now has a "syllables" list, each syllable has "note_segments".
    # We build a flat list of (start_sec, end_sec, pitch, lyric, is_phrase_start)
    # where each note_segment becomes one MIDI note.
    note_items = []
    for word in items:
        syllables = word.get("syllables", [])
        if not syllables:
            # Backward compat: word has no syllables, use its pitch directly
            start_sec = word.get("start", word.get("time", word.get("beat_time", 0.0)))
            end_sec = word.get("end", start_sec + 0.5)
            pitch = word.get("pitch", 60)
            lyric = word.get("word", word.get("lyric", "la"))
            note_items.append((start_sec, end_sec, pitch, lyric, False))
        else:
            # The word's onset-snapped start (the earliest voiced vocal-stem
            # onset) is the true sung attack and anchors the word's FIRST note.
            # Basic-Pitch's own note-segment onset can lag that by 0.2-0.6s (and
            # occasionally lands near the word's end when pitch is only detected
            # late in a held syllable), so the first segment starts at
            # ``word.start`` while later segments keep their own pitch-change
            # times.
            word_start = word.get("start")
            for syl_idx, syl in enumerate(syllables):
                segs = syl.get("note_segments", [])
                syl_text = syl.get("text", "la")
                syl_start = syl.get("start", 0.0)
                syl_end = syl.get("end", syl_start + 0.3)
                
                if not segs:
                    # Fallback
                    pitch = word.get("pitch", 60)
                    if syl_idx == 0 and word_start is not None:
                        syl_start = word_start
                    note_items.append((syl_start, syl_end, pitch, syl_text, False))
                else:
                    # Make segments within the same syllable CONTIGUOUS (no gaps).
                    # The end of segment N = start of segment N+1.
                    # Only the last segment of a syllable can have a gap to the next syllable.
                    contiguous_segs = []
                    for j, seg in enumerate(segs):
                        start_sec = seg.get("start", syl_start)
                        end_sec = seg.get("end", syl_end)
                        if j < len(segs) - 1:
                            # Next segment's start becomes this segment's end
                            next_start = segs[j + 1].get("start", start_sec)
                            end_sec = next_start
                        if syl_idx == 0 and j == 0 and word_start is not None:
                            start_sec = word_start
                        contiguous_segs.append((start_sec, end_sec, seg.get("midi_note", 60)))
                    
                    # Split syllable text into display sub-syllables using pyphen
                    # for Rock Band lyric rendering (one sub-syllable per note segment)
                    sub_syllables = split_syllable_for_display(syl_text, len(contiguous_segs))
                    
                    for j, (start_sec, end_sec, pitch) in enumerate(contiguous_segs):
                        # Assign each segment its sub-syllable for Rock Band display
                        if sub_syllables:
                            lyric = sub_syllables.pop(0)
                        else:
                            lyric = ""
                        note_items.append((start_sec, end_sec, pitch, lyric, False))

    if not note_items:
        # Empty fallback
        note_items = [(0.0, 0.5, 60, "la", False)]

    # Sort by start time
    note_items.sort(key=lambda x: x[0])

    # Now clip overlapping ends (same logic as before, but on the flat note list)
    charted = []
    for start_sec, end_sec, pitch, lyric, _ in note_items:
        charted.append((shifted_time_to_tick(start_sec), shifted_time_to_tick(end_sec)))
    for i in range(len(charted) - 1):
        start_i, end_i = charted[i]
        if end_i > charted[i + 1][0]:
            charted[i] = (start_i, charted[i + 1][0])

    last_event_tick = 0
    first_note_tick = None
    last_note_end_tick = 0

    vocal_events = bytearray()

    last_tick = 0
    current_phrase_idx = None

    for i, (start_sec, end_sec, pitch, lyric, _) in enumerate(note_items):
        target_start_tick, target_end_raw = charted[i]
        next_start_tick = charted[i + 1][0] if i + 1 < len(charted) else target_end_raw
        target_end_tick = max(
            target_start_tick + 48, min(target_end_raw, next_start_tick)
        )

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

        if lyric:
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

    # Track 1-3: instrument charts (DRUMS, BASS, GUITAR - each with 4 difficulties)
    # Each track contains all 4 difficulties (Expert/Hard/Medium/Easy) distinguished by pitch range
    instrument_tracks = build_all_instrument_tracks(
        drum_charts=drum_charts,
        bass_charts=bass_charts,
        guitar_charts=guitar_charts,
        keys_charts=keys_charts,
        freestyle_drums=freestyle_drums,
        count_in_ticks=count_in_ticks,
        time_to_tick=shifted_time_to_tick,
    )
    
    # Vocal track (single track, not per-difficulty)
    t_vocals = build_track("PART VOCALS", bytes(vocal_events))
    
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

    all_tracks = [t0, *instrument_tracks, t_vocals, t5, t6]
    # The MThd track-count must match the number of chunks actually written.
    # If it is too low, strict parsers (e.g. ForgeTool's MidiCS) read one track
    # fewer and silently drop the final (BEAT) track, which then crashes PKG
    # conversion with "Sequence contains no elements" (no BEAT track found).
    # Compute it from the real track list so it can never drift out of sync.
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(all_tracks), 480)

    with open(midi_path, "wb") as f:
        f.write(header)
        for track_bytes in all_tracks:
            f.write(track_bytes)

    logger.info(f"Generated complete vocal MIDI chart at {midi_path}")
    return midi_path


def _build_tempo_grid(beat_times, dynamic_bpms, bpm, ticks_per_beat=480):
    """Returns ``(time_to_tick, tempo_events)``.

    ``time_to_tick(seconds)`` maps an audio timestamp to a MIDI tick and is the
    exact *inverse* of the ``tempo_events`` integration, so chart and tempo map
    are self-consistent (no drift by construction). ``tempo_events`` is a sparse
    list of ``(tick, tempo_us_per_beat)`` emitted once per **measure**.

    The beat tracker's raw per-beat intervals oscillate ~±3 BPM from beat to
    beat (166.7/172.3 alternating); encoding one set_tempo event per beat
    interval yields a dense, jittery map (391 events, 67-185 BPM) that the game
    mishandles — notes drift progressively late. Stock charts instead carry a
    smooth, measure-level tempo map (311 - Down: 69 events over ~176 beats;
    Smells Like Nirvana: 86 events over ~436 beats, spaced 1920-9600 ticks).
    So we emit one event per measure whose tempo is that measure's mean
    interval, skipping measures within ~0.5 BPM of the last emitted event. A
    virtual lead-in interval (audio t=0 to the first tracked beat) is kept raw
    so the song's first beat stays anchored.

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
        # If the first detected beat is very late (>10s), the lead-in is likely
        # a non-rhythmic intro. Cap the virtual interval at a reasonable tempo
        # (max 1,500,000 us/beat = 40 BPM) to avoid MIDI 3-byte tempo overflow
        # (max 16,777,215 us/beat = ~3.58 BPM).
        first_interval = beats[0]
        max_interval_us = 1_500_000  # 40 BPM minimum
        if first_interval * 1_000_000 > max_interval_us:
            # Use a virtual beat at a reasonable tempo for the lead-in
            virtual_beat_time = max_interval_us / 1_000_000
            beats = [0.0, virtual_beat_time] + beats
        else:
            beats = [0.0] + beats

    n = len(beats)
    # Local BPM between consecutive beats; fall back to `bpm` when missing/zero.
    intervals_us = []
    for i in range(n - 1):
        dur = beats[i + 1] - beats[i]
        if dur > 0:
            us = int(60_000_000 / (60.0 / dur))
            # Cap at MIDI tempo meta event limits (3 bytes = 16,777,215 us/beat max)
            # Practical range: 300,000 us/beat (200 BPM max) to 1,500,000 us/beat (40 BPM min)
            us = min(max(us, 300_000), 1_500_000)
            intervals_us.append(us)
        else:
            intervals_us.append(int(60_000_000 / (bpm if bpm and bpm > 0 else 120.0)))

    # One set_tempo event per *measure* (4 beats), tempo = the measure's mean
    # interval. Consecutive measures within ~0.5 BPM (TEMPO_MEASURE_TOL_US) of the
    # last emitted event are skipped, so the track stays sparse and smooth like
    # stock charts (311 - Down: 69 events over ~176 beats; Smells Like Nirvana:
    # 86 events over ~436 beats, spaced 1920-9600 ticks) instead of the dense
    # 1-per-beat jittery map (391 events, 67-185 BPM) that made the game drift
    # progressively late. Tick 0 carries the raw virtual lead-in interval; the
    # count-in shift in generate_vocal_midi replaces it with the song's opening
    # tempo.
    tempo_events = [(0, intervals_us[0])]
    last_us = intervals_us[0]
    j = 0
    while True:
        a = 4 * j + 1  # beats[] index of this measure's first real beat
        b = min(a + 4, n - 1)
        if a >= n - 1:
            break
        span = b - a
        us_j = int((beats[b] - beats[a]) / span * 1_000_000)
        tick = a * ticks_per_beat
        if j == 0 or abs(us_j - last_us) > TEMPO_MEASURE_TOL_US:
            tempo_events.append((tick, us_j))
            last_us = us_j
        if b == n - 1:
            break
        j += 1
    if tempo_events[-1][0] != (n - 1) * ticks_per_beat:
        tempo_events.append(((n - 1) * ticks_per_beat, tempo_events[-1][1]))

    # grid_to_tick is the *inverse* of the tempo track the file will carry, so
    # the chart and the tempo map are self-consistent: whatever tick a note is
    # placed at, the game's tempo-map integration lands on exactly the audio time
    # it was charted for (no drift by construction).
    secs = [0.0]
    for i in range(len(tempo_events) - 1):
        t0, us = tempo_events[i]
        t1 = tempo_events[i + 1][0]
        secs.append(secs[-1] + (t1 - t0) / ticks_per_beat * us / 1e6)

    def grid_to_tick(t):
        if t <= 0:
            return 0
        for i in range(len(tempo_events) - 1):
            if t <= secs[i + 1]:
                t0, us = tempo_events[i]
                return t0 + int((t - secs[i]) / (us / 1e6) * ticks_per_beat)
        # Past the last tempo event: extrapolate with the last tempo.
        t_last, us_last = tempo_events[-1]
        return t_last + int((t - secs[-1]) / (us_last / 1e6) * ticks_per_beat)

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
