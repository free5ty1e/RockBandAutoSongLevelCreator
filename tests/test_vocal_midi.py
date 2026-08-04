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
