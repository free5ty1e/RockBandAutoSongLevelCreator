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

def build_track(name: str, events_bytes: bytes) -> bytes:
    """Wraps MIDI events into a single named MTrk chunk."""
    name_chunk = b"\x00\xFF\x03" + bytes([len(name)]) + name.encode('ascii')
    content = name_chunk + events_bytes + b"\x00\xFF\x2F\x00"
    return b"MTrk" + struct.pack(">I", len(content)) + content


def build_events_track(
    first_note_tick: int,
    last_note_end_tick: int,
    preview_start_tick: int,
) -> bytes:
    """Builds the EVENTS track with the required Rock Band text markers.

    Stock RB3 charts always carry ``[music_start]``, ``[preview]``,
    ``[music_end]`` and ``[end]`` in the EVENTS track.  ForgeTool/Magma
    hard-errors on charts missing them, and in-game the missing ``[preview]``
    marker kills the song-list preview while a missing ``[music_end]``/``[end]``
    makes the song finish instantly at 0% (with a full-combo jingle) because
    the game believes the chart ends immediately.
    """
    events = bytearray()

    # Assign a tick to each marker (text events carry deltas too).
    markers = [
        (0, "[prc_intro]"),
        (0, "[music_start]"),
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


def build_placeholder_track(name: str, pitches: tuple = PLACEHOLDER_DIFFICULTY_PITCHES) -> bytes:
    """Builds a minimal valid instrument track with one note per difficulty."""
    events = bytearray()
    for pitch in pitches:
        events.extend(encode_varlen(0))
        events.extend(b"\x90" + bytes([pitch, 100]))
    for pitch in pitches:
        events.extend(encode_varlen(120 if pitch == pitches[0] else 0))
        events.extend(b"\x80" + bytes([pitch, 0]))
    return build_track(name, bytes(events))

def generate_vocal_midi(synced_json_path: str | Path, output_dir: Path, song_id: str,
                        preview_start_ms: int = 50000, song_length_ms: int | None = None) -> Path:
    """
    Generates a fully compliant Rock Band PART VOCALS MIDI chart from synchronized JSON data.
    Includes placeholder PART DRUMS, PART GUITAR, and PART BASS tracks (one note each) so that
    every instrument advertised in songs.dta has a corresponding chart track.
    """
    json_path = Path(synced_json_path)
    midi_path = output_dir / f"{song_id}.mid"
    
    track_data = {}
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            track_data = json.load(f)

    header = b"MThd" + struct.pack(">IHHH", 6, 1, 7, 480)

    ticks_per_second = 480 * (120 / 60)

    # Track 0: BEAT (tempo map + quarter-note markers, matching stock RB3 charts)
    track0_data = (
        b"\x00\xFF\x58\x04\x04\x02\x18\x08" +  # 4/4 Time Signature
        b"\x00\xFF\x51\x03\x07\xA1\x20"      # 120 BPM (480 ticks/quarter)
    )

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
    for item in items:
        start_sec = item.get("start", item.get("time", item.get("beat_time", 0.0)))
        end_sec = item.get("end", start_sec + 0.5)
        lyric = item.get("word", item.get("lyric", "la"))
        pitch = item.get("pitch", 60)
        
        target_start_tick = int(start_sec * ticks_per_second)
        target_end_tick = int(end_sec * ticks_per_second)
        
        delta_on = max(0, target_start_tick - last_event_tick)
        duration = max(48, target_end_tick - target_start_tick)
        
        vocal_events.extend(encode_varlen(delta_on))
        vocal_events.extend(b"\x90" + bytes([pitch, 100]))
        
        lyric_bytes = lyric.encode('utf-8')
        vocal_events.extend(b"\x00\xFF\x05" + bytes([len(lyric_bytes)]) + lyric_bytes)
        
        vocal_events.extend(encode_varlen(duration))
        vocal_events.extend(b"\x80" + bytes([pitch, 0]))
        
        last_event_tick = target_start_tick + duration
        if first_note_tick is None:
            first_note_tick = target_start_tick
        last_note_end_tick = max(last_note_end_tick, target_start_tick + duration)

    if not items:
        vocal_events.extend(
            b"\x00\x90\x3C\x64" +
            b"\x00\xFF\x05\x02la" +
            b"\x83\x60\x80\x3C\x00"
        )
        first_note_tick = 0
        last_note_end_tick = 480

    if song_length_ms is None:
        song_length_ms = int(last_note_end_tick / ticks_per_second * 1000) + 1000
    total_beats = max(1, int(song_length_ms / 1000 * 2))

    # Track 0: tempo map (name = song id, mirroring stock RB3 charts like 311 - Down)
    tempo_data = (
        b"\x00\xFF\x58\x04\x04\x02\x18\x08" +  # 4/4 Time Signature
        b"\x00\xFF\x51\x03\x07\xA1\x20"      # 120 BPM (480 ticks/quarter)
    )
    t0 = build_track(song_id, tempo_data)

    # Track 1-4: instrument charts
    t1 = build_placeholder_track("PART DRUMS")
    t2 = build_placeholder_track("PART BASS")
    t3 = build_placeholder_track("PART GUITAR")
    t4 = build_track("PART VOCALS", bytes(vocal_events))

    # Track 5: EVENTS with the required [music_start]/[preview]/[music_end]/[end] markers
    t5 = build_events_track(
        first_note_tick=first_note_tick or 0,
        last_note_end_tick=max(last_note_end_tick, int(song_length_ms * ticks_per_second / 1000)),
        preview_start_tick=int(preview_start_ms * ticks_per_second / 1000),
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
