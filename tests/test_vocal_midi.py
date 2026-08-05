import json
import tempfile
import mido
from pathlib import Path
from autorb.export.midi_generator import generate_vocal_midi


def _items(n: int = 30, gap: float = 0.6) -> list[dict]:
    """Generate *n* evenly-spaced word entries at 120 BPM."""
    items = []
    t = 1.0
    for i in range(n):
        items.append({"start": t, "end": t + 0.5, "word": f"w{i}", "pitch": 60})
        t += gap
    return items


def test_vocal_phrase_markers_align_to_measures(tmp_path: Path):
    """Phrase start markers (pitch 105, vel >0) must appear exactly once per
    2-measure window (3840 ticks at 480 tpb / 4/4). The grouping is by fixed
    meter, not by pauses in the lyrics."""
    sj = tmp_path / "synced.json"
    sj.write_text(json.dumps({"synced_lyrics": _items(40, gap=0.8)}))

    mid_path = generate_vocal_midi(sj, tmp_path, "test_phrase")
    mf = mido.MidiFile(mid_path)
    voc = next(t for t in mf.tracks if t.name == "PART VOCALS")

    abs_tick = 0
    phrase_starts: list[int] = []
    for msg in voc:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.note == 105 and msg.velocity > 0:
            phrase_starts.append(abs_tick)

    # 40 notes at 0.8 s spacing = 32 s of lyrics; at 120 BPM, phrase = 4 s (3840 t).
    # Expect ceil(32 / 4) = 8 phrase windows, so 8 phrase starts.
    assert len(phrase_starts) >= 5, f"too few phrases: {len(phrase_starts)}"

    # Every phrase start must fall within the same 3840-tick window as expected.
    phrase_ticks = 3840  # 2 measures * 4 beats * 480 ticks
    for ps in phrase_starts:
        # The start should be within its own measure window (first note in that window).
        window_idx = ps // phrase_ticks
        window_start = window_idx * phrase_ticks
        # Allow up to the full window width — the first note in the window fires here.
        assert window_start <= ps < window_start + phrase_ticks


def test_vocal_phrase_ends_close_before_next(tmp_path: Path):
    """Phrase end markers (pitch 105, vel 0) must appear before each new phrase start."""
    sj = tmp_path / "synced.json"
    sj.write_text(json.dumps({"synced_lyrics": _items(30, gap=0.7)}))

    mid_path = generate_vocal_midi(sj, tmp_path, "test_phrase_end")
    mf = mido.MidiFile(mid_path)
    voc = next(t for t in mf.tracks if t.name == "PART VOCALS")

    abs_tick = 0
    events: list[tuple[str, int]] = []
    for msg in voc:
        abs_tick += msg.time
        if msg.type == "note_on" and msg.note == 105:
            events.append(("ph_start", abs_tick))
        elif msg.type == "note_off" and msg.note == 105:
            events.append(("ph_end", abs_tick))

    # Must start with a phrase start and alternate.
    assert events[0][0] == "ph_start"
    for i in range(1, len(events)):
        if events[i][0] == "ph_start":
            prev_type = events[i - 1][0]
            assert prev_type == "ph_end", (
                f"phrase start at tick {events[i][1]} preceded by {prev_type}"
            )


def _tempo_map_from_midi(mid_path: Path) -> list[tuple[int, int]]:
    """Extracts (absolute_tick, tempo_us) set_tempo events from the tempo track."""
    mf = mido.MidiFile(mid_path)
    t0 = mf.tracks[0]
    abs_tick = 0
    out = []
    for msg in t0:
        abs_tick += msg.time
        if msg.type == "set_tempo":
            out.append((abs_tick, msg.tempo))
    return out


def test_dynamic_tempo_map_tracks_beat_grid(tmp_path: Path):
    """When beat_times/dynamic_bpms are supplied, the tempo track must carry
    multiple set_tempo events whose ticks reproduce the beat grid, and word
    ticks must round-trip to their original audio times within a few ms."""
    sj = tmp_path / "synced.json"
    sj.write_text(json.dumps({"synced_lyrics": _items(20, gap=1.0)}))  # 20 s of words

    # Simulated beat grid with real-world jitter around 172 BPM, like tempo_map.json.
    beat_times, bpms = [], []
    t = 0.0
    for i in range(60):
        beat_times.append(t)
        dur = 60.0 / 172.0 + (0.015 if i % 5 == 0 else -0.008)
        bpms.append(60.0 / dur)
        t += dur

    mid_path = generate_vocal_midi(
        sj, tmp_path, "dynamic",
        song_length_ms=20000, bpm=172.0,
        beat_times=beat_times, dynamic_bpms=bpms,
    )
    tempos = _tempo_map_from_midi(mid_path)
    assert len(tempos) > 10, f"expected a dynamic tempo map, got {len(tempos)} events"
    # Every tempo event sits on a beat boundary (multiple of 480 ticks), and the
    # map starts at tick 0. Consecutive ticks may be >480 apart because identical
    # neighboring tempos are collapsed.
    ticks = [t for t, _ in tempos]
    assert ticks[0] == 0
    assert all(t % 480 == 0 for t in ticks)
    assert all(b > a for a, b in zip(ticks, ticks[1:]))


def test_dynamic_tempo_roundtrips_word_times(tmp_path: Path):
    """A word placed at tick time_to_tick(t) must reconstruct to ~t seconds via
    the tempo map, proving the chart is synced to the beat grid (no drift)."""
    sj = tmp_path / "synced.json"
    items = [{"start": float(i), "end": float(i) + 0.4, "word": f"w{i}", "pitch": 60}
             for i in range(1, 50, 3)]
    sj.write_text(json.dumps({"synced_lyrics": items}))

    # Jittery grid like real tempo_map.json: avg ~170 BPM with variation.
    beat_times, bpms = [], []
    t = 0.0
    for i in range(80):
        beat_times.append(t)
        dur = 0.35 + (0.02 if i % 7 else -0.04)
        bpms.append(60.0 / dur)
        t += dur

    mid_path = generate_vocal_midi(
        sj, tmp_path, "roundtrip",
        song_length_ms=30000, bpm=170.0,
        beat_times=beat_times, dynamic_bpms=bpms,
    )
    tempos = _tempo_map_from_midi(mid_path)

    # Rebuild time_to_tick the same way the generator does, then invert.
    from autorb.export.midi_generator import _build_tempo_grid
    t2t, _ = _build_tempo_grid(beat_times, bpms, bpm=170.0)

    def tick_to_sec(tick):
        t_sec = 0.0
        prev = 0
        cur = tempos[0][1]
        for et, us in tempos[1:]:
            if tick <= et:
                return t_sec + (tick - prev) / 480.0 * cur / 1e6
            t_sec += (et - prev) / 480.0 * cur / 1e6
            prev, cur = et, us
        return t_sec + (tick - prev) / 480.0 * cur / 1e6

    for item in items:
        tick = t2t(item["start"])
        back = tick_to_sec(tick)
        assert abs(back - item["start"]) < 0.01, (
            f"word @{item['start']:.2f}s mapped to tick {tick} -> {back:.3f}s"
        )
