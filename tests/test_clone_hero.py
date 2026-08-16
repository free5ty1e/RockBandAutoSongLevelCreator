"""Tests for the Clone Hero song-folder exporter (--build-clone-hero)."""

import json
import mido
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from autorb.export.clone_hero import (
    build_clone_hero_song,
    midi_to_chart_file,
    remap_drums_for_clone_hero,
    sanitize_folder_name,
)
from autorb.export.midi_generator import generate_vocal_midi


def _write_synced_json(path: Path, n: int = 12, gap: float = 0.8) -> None:
    items = []
    t = 1.0
    for i in range(n):
        items.append({
            "start": t, "end": t + 0.5, "word": f"word{i}", "pitch": 60,
            "syllables": [{
                "text": f"word{i}", "start": t, "end": t + 0.5,
                "note_segments": [{"start": t, "end": t + 0.5, "midi_note": 60}],
                "pitch_trusted": True,
            }],
        })
        t += gap
    path.write_text(json.dumps({"synced_lyrics": items}), encoding="utf-8")


def _make_stems(stems_dir: Path, sr: int = 22050, secs: float = 8.0) -> None:
    stems_dir.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(sr * secs)) / sr
    for name in ("drums", "bass", "other", "vocals"):
        freq = {"drums": 60.0, "bass": 90.0, "other": 200.0, "vocals": 330.0}[name]
        data = 0.2 * np.sin(2 * np.pi * freq * t)
        sf.write(stems_dir / f"{name}.wav", data, sr)


def _beat_grid(bpm: float = 120.0, n: int = 40) -> tuple[list, list]:
    beats, bpms = [], []
    t = 0.0
    for _ in range(n):
        beats.append(t)
        bpms.append(bpm)
        t += 60.0 / bpm
    return beats, bpms


def test_sanitize_folder_name():
    assert sanitize_folder_name('Eve 6 - Open Road Song') == 'Eve 6 - Open Road Song'
    assert sanitize_folder_name('A/B:C*D') == 'A-B-C-D'
    assert sanitize_folder_name('   ') == 'autorb_song'


def test_build_clone_hero_song_writes_compliant_folder(tmp_path: Path):
    stems_dir = tmp_path / "stems"
    _make_stems(stems_dir)
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced)

    beats, bpms = _beat_grid()
    out_dir = tmp_path / "out"
    folder = build_clone_hero_song(
        output_dir=out_dir,
        song_id="open_road_song",
        title="Open Road Song",
        artist="Eve 6",
        year=1998,
        genre="Alternative",
        stems_dir=stems_dir,
        synced_json=synced,
        beat_times=beats,
        dynamic_bpms=bpms,
        source_length_ms=8000,
        avg_bpm=120.0,
    )

    assert folder.is_dir()
    # Clone Hero requires at minimum: notes.mid or notes.chart, an audio file,
    # and song.ini — we ship both chart formats for maximum loadability.
    assert (folder / "notes.mid").exists()
    assert (folder / "notes.chart").exists()
    assert (folder / "song.ini").exists()
    audio = folder / "song.ogg"
    assert audio.exists(), "expected an encoded song.ogg"
    assert audio.read_bytes()[:4] == b"OggS"


def test_song_ini_metadata_and_units(tmp_path: Path):
    stems_dir = tmp_path / "stems"
    _make_stems(stems_dir)
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced)

    beats, bpms = _beat_grid()
    folder = build_clone_hero_song(
        output_dir=tmp_path / "out",
        song_id="s",
        title="Open Road Song",
        artist="Eve 6",
        year=1998,
        genre="Alternative",
        stems_dir=stems_dir,
        synced_json=synced,
        beat_times=beats,
        dynamic_bpms=bpms,
        source_length_ms=123456,
        avg_bpm=120.0,
        preview_start_ms=50000,
    )
    ini_text = (folder / "song.ini").read_text(encoding="utf-8")
    assert "name = Open Road Song" in ini_text
    assert "artist = Eve 6" in ini_text
    # song_length and preview_start_time are milliseconds.
    assert "song_length = 123456" in ini_text
    assert "preview_start_time = 50000" in ini_text
    assert "charter = AutoRB" in ini_text


def test_notes_mid_has_no_count_in_shift(tmp_path: Path):
    """The CH chart must use the raw audio timeline: with count-in disabled, a
    word at source time t lands at the unshifted tick t*960 (120 BPM @ 480 tpb)."""
    stems_dir = tmp_path / "stems"
    _make_stems(stems_dir)
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced)

    beats, bpms = _beat_grid()
    folder = build_clone_hero_song(
        output_dir=tmp_path / "out",
        song_id="s",
        title="T",
        artist="A",
        year=2020,
        genre="Rock",
        stems_dir=stems_dir,
        synced_json=synced,
        beat_times=beats,
        dynamic_bpms=bpms,
        source_length_ms=10000,
        avg_bpm=120.0,
    )
    mf = mido.MidiFile(folder / "notes.mid")
    voc = next(t for t in mf.tracks if t.name == "PART VOCALS")
    abs_tick = 0
    first_phrase = None
    for msg in voc:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.note == 105 and msg.velocity > 0:
            first_phrase = abs_tick
            break
    # First word at 1.0s @ 120 BPM = 960 ticks, no count-in added.
    assert first_phrase is not None
    assert first_phrase == 960, f"first phrase {first_phrase} should be 960 (no count-in)"


def test_album_art_copied_when_provided(tmp_path: Path):
    stems_dir = tmp_path / "stems"
    _make_stems(stems_dir)
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced)
    beats, bpms = _beat_grid()

    art = tmp_path / "album_art_preview.png"
    art.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    folder = build_clone_hero_song(
        output_dir=tmp_path / "out",
        song_id="s",
        title="T",
        artist="A",
        year=2020,
        genre="Rock",
        stems_dir=stems_dir,
        synced_json=synced,
        beat_times=beats,
        dynamic_bpms=bpms,
        source_length_ms=8000,
        album_art=art,
    )
    assert (folder / "album.png").exists()
    assert (folder / "album.png").read_bytes() == art.read_bytes()


def test_clone_hero_chart_matches_validation_chart(tmp_path: Path):
    """The CH notes.mid and the pipeline's validation notes.mid (both
    count-in-free, same inputs) must produce identical vocal note ticks."""
    stems_dir = tmp_path / "stems"
    _make_stems(stems_dir)
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced)
    beats, bpms = _beat_grid()

    val_midi = generate_vocal_midi(
        synced, tmp_path, "notes",
        song_length_ms=10000, bpm=120.0,
        beat_times=beats, dynamic_bpms=bpms,
        count_in_ticks=0, count_in_ms=0,
    )
    folder = build_clone_hero_song(
        output_dir=tmp_path / "out",
        song_id="s",
        title="T",
        artist="A",
        year=2020,
        genre="Rock",
        stems_dir=stems_dir,
        synced_json=synced,
        beat_times=beats,
        dynamic_bpms=bpms,
        source_length_ms=10000,
        avg_bpm=120.0,
    )

    def vocal_ticks(path: Path) -> list[int]:
        mf = mido.MidiFile(path)
        voc = next(t for t in mf.tracks if t.name == "PART VOCALS")
        abs_tick = 0
        ticks = []
        for msg in voc:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0 and msg.note != 105:
                ticks.append(abs_tick)
        return ticks

    assert vocal_ticks(val_midi) == vocal_ticks(folder / "notes.mid")


def _build_folder(tmp_path: Path, n: int = 12) -> Path:
    stems_dir = tmp_path / "stems"
    _make_stems(stems_dir)
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced)
    beats, bpms = _beat_grid()
    return build_clone_hero_song(
        output_dir=tmp_path / "out",
        song_id="s",
        title="Open Road Song",
        artist="Eve 6",
        year=1998,
        genre="Alternative",
        stems_dir=stems_dir,
        synced_json=synced,
        beat_times=beats,
        dynamic_bpms=bpms,
        source_length_ms=10000,
        avg_bpm=120.0,
    )


def _parse_chart_sections(text: str) -> dict[str, list[str]]:
    """Parse a .chart file into {section: [event lines]} (lines without tick)."""
    sections, current, current_lines = {}, None, []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if current is not None:
                sections[current] = current_lines
            current, current_lines = stripped[1:-1], []
        elif current is not None and stripped and not stripped.startswith("//"):
            current_lines.append(stripped)
    if current is not None:
        sections[current] = current_lines
    return sections


def test_notes_chart_structure_and_lyrics(tmp_path: Path):
    folder = _build_folder(tmp_path)
    chart_text = (folder / "notes.chart").read_text(encoding="utf-8")
    sections = _parse_chart_sections(chart_text)

    # [Song] metadata + resolution.
    assert sections["Song"], "chart must have a [Song] section"
    assert any('Name = "Open Road Song"' in s for s in sections["Song"])
    assert any('Artist = "Eve 6"' in s for s in sections["Song"])
    assert any("Resolution = 480" in s for s in sections["Song"])

    # [SyncTrack] must carry the tempo + time signature.
    assert sections["SyncTrack"]
    assert any(s.endswith("= TS 4") for s in sections["SyncTrack"])
    assert any(" = B " in s for s in sections["SyncTrack"])

    # Lyrics as global events: phrase markers + one lyric event per word.
    events = sections["Events"]
    assert any(s.endswith('= E "phrase_start"') for s in events)
    assert any(s.endswith('= E "phrase_end"') for s in events)
    lyrics = [s for s in events if '"lyric ' in s]
    assert len(lyrics) == 12, f"expected 12 lyric events, got {len(lyrics)}"

    # Vocal notes on all four difficulty sections, matching the lyric count,
    # sorted by tick.
    for diff in ("Easy", "Medium", "Hard", "Expert"):
        notes = [s for s in sections[f"{diff}Vocals"] if " = N " in s]
        assert len(notes) == 12, f"{diff}Vocals should carry 12 notes"
        ticks = [int(s.split("=")[0]) for s in notes]
        assert ticks == sorted(ticks), f"{diff}Vocals must be tick-sorted"

    # Placeholder instrument sections exist on each difficulty.
    for inst in ("Guitar", "Bass", "Drums"):
        for diff in ("Easy", "Medium", "Hard", "Expert"):
            assert sections.get(f"{diff}{inst}"), f"missing [{diff}{inst}]"


def _bpm_lines(chart_text: str) -> list[tuple[int, int]]:
    """Return ``[(tick, bpm)]`` for every ``B`` line in a .chart's [SyncTrack]."""
    sections = _parse_chart_sections(chart_text)
    out = []
    for s in sections["SyncTrack"]:
        m = re.fullmatch(r"(\d+) = B (\d+)", s.strip())
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def test_chart_bpm_is_integer_and_matches_midi_tempo(tmp_path: Path):
    """Moonscraper and the Clone Hero reader it was forked from parse the B
    field as an *integer* plain-BPM via uint.TryParse and silently DROP any
    line with a fractional value. A float BPM therefore leaves the chart with
    no tempo map at all and the song is rejected at scan time. Every B line
    must be a whole number, none dropped vs the MIDI tempo track, each within
    1 BPM of the exact MIDI tempo, and the integer map must not drift from the
    exact timeline (plain rounding accumulates ~175ms over a song — the drift
    this test guards against)."""
    folder = _build_folder(tmp_path)
    bpm_lines = _bpm_lines((folder / "notes.chart").read_text(encoding="utf-8"))

    mf = mido.MidiFile(folder / "notes.mid")
    tempos = []
    tick = 0
    for msg in mf.tracks[0]:
        tick += msg.time
        if msg.type == "set_tempo":
            tempos.append((tick, 60_000_000.0 / msg.tempo))

    assert bpm_lines, "chart must carry tempo markers"
    assert len(bpm_lines) == len(tempos), (
        f"chart {len(bpm_lines)} B lines != midi {len(tempos)} set_tempo — "
        "a parser would have silently dropped tempo lines"
    )
    for (ctick, cbpm), (mtick, mbpm) in zip(bpm_lines, tempos):
        assert ctick == mtick
        assert abs(cbpm - mbpm) <= 1.0, f"tick {ctick}: chart {cbpm} vs midi {mbpm}"

    ppq = mf.ticks_per_beat

    def time_at(events, tick):
        sec = 0.0
        prev = 0
        cur = events[0][1]
        for et, b in events[1:]:
            if tick <= et:
                return sec + (tick - prev) / ppq * 60.0 / cur
            sec += (et - prev) / ppq * 60.0 / cur
            prev, cur = et, b
        return sec + (tick - prev) / ppq * 60.0 / cur

    last = max(t for t, _ in tempos)
    drift = abs(time_at([(t, b) for t, b in bpm_lines], last) - time_at(tempos, last))
    assert drift <= 0.100, f"chart tempo drifts {drift * 1000:.0f} ms from midi"


def test_chart_bpm_rounds_fractional_tempo(tmp_path: Path):
    """A fractional MIDI tempo (168.064 BPM, the AutoRB dynamic-map norm) must
    be emitted as the integer 168 in the .chart — never as a float that the
    Moonscraper/CH reader would drop."""
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced, n=4)
    beats, bpms = _beat_grid(bpm=168.064)
    midi_path = generate_vocal_midi(
        synced, tmp_path, "notes",
        song_length_ms=10000, bpm=168.064,
        beat_times=beats, dynamic_bpms=bpms,
        count_in_ticks=0, count_in_ms=0,
    )
    out = tmp_path / "notes.chart"
    midi_to_chart_file(midi_path, out, title="T", artist="A")

    bpm_lines = _bpm_lines(out.read_text(encoding="utf-8"))
    assert bpm_lines
    assert all(bpm == 168 for _, bpm in bpm_lines), bpm_lines


def test_notes_chart_is_count_in_free(tmp_path: Path):
    """The .chart must sit on the raw audio timeline: first word at 1.0s @ 120
    BPM = tick 960 (no count-in shift), matching the notes.mid first phrase."""
    folder = _build_folder(tmp_path)
    chart_text = (folder / "notes.chart").read_text(encoding="utf-8")
    events = _parse_chart_sections(chart_text)["Events"]
    phrase_starts = [int(s.split("=")[0]) for s in events
                     if s.endswith('= E "phrase_start"')]
    assert phrase_starts and phrase_starts[0] == 960, (
        f"first phrase_start {phrase_starts[0] if phrase_starts else None} "
        "should be 960 (no count-in)"
    )

    mf = mido.MidiFile(folder / "notes.mid")
    voc = next(t for t in mf.tracks if t.name == "PART VOCALS")
    abs_tick = 0
    midi_first = None
    for msg in voc:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.note == 105 and msg.velocity > 0:
            midi_first = abs_tick
            break
    assert midi_first == phrase_starts[0]


def test_midi_to_chart_file_roundtrip(tmp_path: Path):
    """Converting the validation notes.mid directly must produce a .chart whose
    first vocal note and first lyric event match the source MIDI exactly."""
    synced = tmp_path / "synced_track.json"
    _write_synced_json(synced)
    beats, bpms = _beat_grid()
    midi_path = generate_vocal_midi(
        synced, tmp_path, "notes",
        song_length_ms=10000, bpm=120.0,
        beat_times=beats, dynamic_bpms=bpms,
        count_in_ticks=0, count_in_ms=0,
    )
    out = tmp_path / "notes.chart"
    midi_to_chart_file(midi_path, out, title="T", artist="A")

    mf = mido.MidiFile(midi_path)
    voc = next(t for t in mf.tracks if t.name == "PART VOCALS")
    first_note = first_lyric = None
    abs_tick = 0
    for msg in voc:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.velocity > 0 and msg.note != 105 \
                and first_note is None:
            first_note = abs_tick
        elif msg.type == "lyrics" and first_lyric is None:
            first_lyric = abs_tick

    sections = _parse_chart_sections(out.read_text(encoding="utf-8"))
    expert = [s for s in sections["ExpertVocals"] if " = N " in s]
    events = sections["Events"]
    lyric_events = [s for s in events if '"lyric ' in s]

    assert int(expert[0].split("=")[0]) == first_note
    assert int(lyric_events[0].split("=")[0]) == first_lyric


def _make_drum_mid(path: Path, rb_pitches=(96, 97, 98)):
    """Minimal .mid with PART DRUMS at difficulty-offset pitches — the scheme the
    CON `.mid` now writes (Easy 60 / Medium 72 / Hard 84 / Expert 96 + lane 0-4).
    The three notes here are Expert: kick=96 (lane 0), snare=97 (lane 1),
    open-hat=98 (lane 2)."""
    mf = mido.MidiFile(ticks_per_beat=480)
    tt = mido.MidiTrack(); tt.name = "notes"
    tt.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120)))
    mf.tracks.append(tt)
    dt = mido.MidiTrack(); dt.name = "PART DRUMS"
    t = 0
    for p in rb_pitches:
        dt.append(mido.Message("note_on", note=p, velocity=100, time=t)); t = 480
        dt.append(mido.Message("note_off", note=p, velocity=0, time=240)); t = 240
    mf.tracks.append(dt)
    mf.save(str(path))


def test_remap_drums_for_clone_hero_uses_ch_offset_format(tmp_path: Path):
    """Clone Hero's .mid drums must be difficulty-offset (Easy 60 / Medium 72 /
    Hard 84 / Expert 96 + lane 0-4). The CON `PART DRUMS` is already in this scheme
    (ForgeTool/PKG requires it), and `remap_drums_for_clone_hero` re-emits every hit
    into all four difficulties so Clone Hero loads a drums player. Each input hit
    becomes one note per difficulty."""
    mid = tmp_path / "d.mid"
    _make_drum_mid(mid)
    remap_drums_for_clone_hero(mid)

    mf = mido.MidiFile(mid)
    dt = next(t for t in mf.tracks if t.name == "PART DRUMS")
    pitches = [m.note for m in dt if m.type == "note_on" and m.velocity > 0]
    # 3 RB pitches x 4 difficulties = 12 notes, all in CH's 60-101 range.
    assert len(pitches) == 12
    assert all(60 <= p <= 101 for p in pitches)
    # kick(36)->0, snare(38)->1, open-hat(46)->2 ; each emitted in all 4 difficulties.
    assert sorted(pitches) == [60, 61, 62, 72, 73, 74, 84, 85, 86, 96, 97, 98]


def test_chart_drums_use_lanes_not_midi_pitches(tmp_path: Path):
    """The .chart [ExpertDrums] section must use Clone Hero lanes 0-4 (sustain 0),
    never raw pitches, or CH rejects the drum chart."""
    mid = tmp_path / "d2.mid"
    _make_drum_mid(mid)
    remap_drums_for_clone_hero(mid)
    chart = tmp_path / "d2.chart"
    midi_to_chart_file(mid, chart, title="T", artist="A")

    sections = _parse_chart_sections(chart.read_text(encoding="utf-8"))
    expert = [s for s in sections["ExpertDrums"] if " = N " in s]
    lanes = [int(s.split("=")[1].split()[1]) for s in expert]
    assert lanes == [0, 1, 2]  # kick/snare/open-hat -> 0/1/2
    # drum sustains are hits (0), not rolls
    assert all(int(s.split("=")[1].split()[2]) == 0 for s in expert)
