"""
Difficulty reduction engine for instrument charts.

Reduces Expert charts to Hard / Medium / Easy following the Rock Band
authoring standards documented in ``llm-wiki-kb/difficulty_charting.md``
(distilled from the Harmonix RBN / C3 Customs authoring docs). Each lower
difficulty is a *simplified, structured* version of the one above it, derived
one step at a time (Expert -> Hard -> Medium -> Easy), not a density thinning.

Vocals are NOT reduced here — Rock Band vocals share one note track across all
difficulties; only the game's hit-engine leniency changes (see the KB doc).
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Difficulty(Enum):
    EXPERT = "expert"
    HARD = "hard"
    MEDIUM = "medium"
    EASY = "easy"


# --------------------------------------------------------------------------
# Beat-grid helpers
# --------------------------------------------------------------------------

def _local_bpm(tempo_map, t):
    """BPM in effect at time ``t`` given a (time, bpm) tempo map."""
    bpm = 120.0
    if tempo_map:
        for (tt, bb) in tempo_map:
            if tt <= t:
                bpm = bb
            else:
                break
    return bpm


def _beat_dur(tempo_map, t):
    """Seconds per beat at time ``t``."""
    return 60.0 / _local_bpm(tempo_map, t)


def _measure_dur(tempo_map, t):
    """Seconds per measure (4/4) at time ``t``."""
    return 4.0 * _beat_dur(tempo_map, t)


def _snap(time: float, tempo_map, divisions: float = 2) -> float:
    """Snap a time to the nearest ``divisions``-per-beat grid at the local BPM.

    divisions=1 -> quarter notes, 2 -> 1/8, 0.5 -> half notes. Used to put
    reduced charts on the beat grid where a player expects them.
    """
    if not tempo_map:
        return time
    step = _beat_dur(tempo_map, time) / divisions
    if step <= 0:
        return time
    return round(time / step) * step


def _on_grid(time: float, tempo_map, divisions: float, tol: float = None) -> bool:
    """True if ``time`` lies on the ``divisions``-per-beat grid."""
    if not tempo_map:
        return True
    step = _beat_dur(tempo_map, time) / divisions
    snapped = round(time / step) * step
    if tol is None:
        tol = step * 0.4
    return abs(time - snapped) <= tol


def _build_events(notes, tol: float = 0.012):
    """Group near-simultaneous notes into chord events (one event per attack)."""
    events = []
    for n in sorted(notes, key=lambda x: x.time):
        if events and abs(n.time - events[-1]["time"]) <= tol:
            events[-1]["notes"].append(n)
        else:
            events.append({"time": n.time, "notes": [n]})
    return events


def _lanes(ev):
    """Sorted list of lanes present in a chord event."""
    return sorted(set(n.lane for n in ev["notes"]))


def _to_allowed_2note(lanes):
    """Reduce a chord to a 2-note *allowed* pair (Hard/Medium bans).

    Forbidden pairs (RBN Guitar/Bass Authoring): Green/Blue {0,3},
    Green/Orange {0,4}, Red/Orange {2,4}; 3-note chords are also banned on
    those difficulties. We keep the lowest two lanes, and if that pair is
    itself forbidden we keep only the root.
    """
    lanes = sorted(lanes)
    if len(lanes) >= 2:
        pair = lanes[:2]
        if pair in ([0, 3], [0, 4], [2, 4]):
            return [lanes[0]]
        return pair
    return lanes


def _emit(ev, lanes, is_hopo: bool = False, velocity: int = 100):
    """Build fresh ChartNotes for ``lanes`` of a chord event."""
    out = []
    for lane in lanes:
        src = next((n for n in ev["notes"] if n.lane == lane), ev["notes"][0])
        out.append(ChartNote(
            time=ev["time"],
            lane=lane,
            length=getattr(src, "length", 0) or 0,
            is_open=getattr(src, "is_open", False),
            is_hopo=is_hopo,
            velocity=velocity,
            difficulty_pitch=getattr(src, "difficulty_pitch", 60 + lane),
            is_chord=len(lanes) > 1,
        ))
    return out


def _reapply_hopo(notes):
    """Re-detect game HOPOs on a reduced fretted chart (adjacent lanes <=120 ms,
    same direction, neither open). Mirrors ``guitar.py``'s HOPO pass."""
    notes = sorted(notes, key=lambda n: n.time)
    for i in range(1, len(notes)):
        prev, curr = notes[i - 1], notes[i]
        if curr.time == prev.time or curr.is_chord:
            continue
        td = curr.time - prev.time
        ld = abs(curr.lane - prev.lane)
        if td <= 0.12 and ld == 1 and not prev.is_open and not curr.is_open:
            nxt = notes[min(i + 1, len(notes) - 1)]
            if (curr.lane > prev.lane) == (nxt.lane > curr.lane):
                curr.is_hopo = True
                curr.velocity = 127
    return notes


def _pull_back_sustains(notes, tempo_map, gap_div: float):
    """Cap each sustain so a ``1/gap_div``-note gap remains before the next note
    (Medium quarter-ish, Easy a little more — "reasonable to whammy")."""
    notes = sorted(notes, key=lambda n: n.time)
    for i, n in enumerate(notes):
        if n.length <= 0:
            continue
        nxt = notes[i + 1].time if i + 1 < len(notes) else n.time + 10.0
        gap = _beat_dur(tempo_map, n.time) / gap_div
        max_len = max(0.0, nxt - n.time - gap)
        if n.length > max_len:
            n.length = max_len
    return notes


def _ensure_lane_consistency(expert_notes, reduced_notes, tempo_map, difficulty):
    """Universal principle 3: every lane used in Expert should appear in every
    lower difficulty. For any Expert lane missing from the reduced chart, add a
    strum at one of that lane's Expert occurrences — but ONLY where adding it
    would not recreate a forbidden chord (Hard: Green/Orange & 3-note; Medium:
    G/B, G/O, R/O & 3-note; Easy: any chord). If no safe slot exists, the lane is
    left out rather than violate a hard authoring rule."""
    expert_lanes = set(n.lane for n in expert_notes)
    have = set(n.lane for n in reduced_notes)
    missing = expert_lanes - have
    if not missing:
        return reduced_notes
    div = {Difficulty.MEDIUM: 1, Difficulty.EASY: 0.5}.get(difficulty, 2)
    forbidden = {
        Difficulty.HARD: ({0, 4},),
        Difficulty.MEDIUM: ({0, 3}, {0, 4}, {2, 4}),
    }.get(difficulty, ())  # Easy forbids all chords, handled below.
    occupied = {}
    for n in reduced_notes:
        occupied.setdefault(round(_snap(n.time, tempo_map, div), 4), set()).add(n.lane)
    added = []
    for lane in sorted(missing):
        cands = sorted({round(_snap(n.time, tempo_map, div), 4)
                        for n in expert_notes if n.lane == lane})
        placed = False
        for ct in cands:
            existing = occupied.get(ct, set())
            if existing:
                if difficulty == Difficulty.EASY:
                    continue  # Easy is single-note only; never form a chord
                newset = existing | {lane}
                if any(newset == f for f in forbidden) or len(newset) >= 3:
                    continue
            added.append(ChartNote(
                time=ct, lane=lane, length=0, is_open=False,
                is_hopo=False, velocity=100, difficulty_pitch=60 + lane,
            ))
            occupied.setdefault(ct, set()).add(lane)
            placed = True
            break
        # if not placed, skip (don't violate chord rules)
    return reduced_notes + added


# --------------------------------------------------------------------------
# Fretted instruments (guitar / bass / keys)
# --------------------------------------------------------------------------

def _reduce_fretted(notes, tempo_map, difficulty, all_lanes: bool):
    """Reduce a fretted (guitar/bass/keys) Expert chart to ``difficulty``.

    ``all_lanes`` is True for keys (all 5 colors allowed on every difficulty);
    for guitar/bass the documented lane-focus / chord restrictions apply.
    """
    events = _build_events(notes)
    out = []
    for ev in events:
        lanes = _lanes(ev)
        if difficulty == Difficulty.HARD:
            # No Green/Orange or 3-note chords; keep all other Expert chords.
            if len(lanes) >= 3 or (0 in lanes and 4 in lanes):
                lanes = _to_allowed_2note(lanes)
        elif difficulty == Difficulty.MEDIUM:
            # No G/B, G/O, R/O, or 3-note chords; keep 2-note chords.
            if len(lanes) >= 3 or lanes in ([0, 3], [0, 4], [2, 4]):
                lanes = _to_allowed_2note(lanes)
        elif difficulty == Difficulty.EASY:
            # No chords at all — reduce to the single most prominent note (root).
            lanes = [lanes[0]]
        out.extend(_emit(ev, lanes, is_hopo=False))

    # Quantize to the 1/8 grid (Expert transcription is audio-derived, not
    # pre-quantized) so subsequent grid filtering is stable.
    for n in out:
        n.time = _snap(n.time, tempo_map, 2)

    # De-duplicate simultaneous lanes.
    seen, dedup = set(), []
    for n in sorted(out, key=lambda x: (x.time, x.lane)):
        k = (round(n.time, 4), n.lane)
        if k in seen:
            continue
        seen.add(k)
        dedup.append(n)
    out = dedup

    # Keep only notes that sit on the difficulty's *coarser* grid — this is what
    # actually thins the chart (Medium = 1/8 notes, Easy = half notes); Hard
    # keeps the 1/8 grid. We filter rather than snap off-beats onto the beat, so
    # an 8th-note run becomes an 8th-note (or sparser) run, not a stack of chords.
    # Medium allows eighths (a steady 8th-note groove is standard RB Medium and
    # keeps the kit/guitar feeling like a beat instead of a sparse quarter grid).
    if difficulty == Difficulty.MEDIUM:
        out = [n for n in out if _on_grid(n.time, tempo_map, 2)]
    elif difficulty == Difficulty.EASY:
        out = [n for n in out if _on_grid(n.time, tempo_map, 0.5)]

    if difficulty == Difficulty.HARD:
        out = _reapply_hopo(out)
    elif difficulty in (Difficulty.MEDIUM, Difficulty.EASY):
        gap_div = {Difficulty.MEDIUM: 2, Difficulty.EASY: 1}[difficulty]
        out = _pull_back_sustains(out, tempo_map, gap_div)
    return out


# --------------------------------------------------------------------------
# Drums (standard 4-pad + kick)
# --------------------------------------------------------------------------

def _reduce_drums(notes, tempo_map, difficulty, fills):
    """Reduce a drum Expert chart to ``difficulty`` per the RBN Drum Authoring
    rules: no kicks in fills, no kick/snare between time-keeping gems, no 3-limb
    hits, tempo-driven kick ceilings, max-2-limbs and no kick/hand pairing on
    Easy, single-color crashes on Hard. Expert is passed through (double bass is
    already removed upstream in ``drums.py``)."""
    if difficulty == Difficulty.EXPERT:
        return list(notes)

    events = _build_events(notes)
    fills = fills or []
    out = []
    last_kick_measure = {}

    # Time-keeping (hi-hat / ride) event times — kicks/snares must sit with one.
    tk_times = sorted({
        ev["time"] for ev in events
        if (2 in set(_lanes(ev))) or (3 in set(_lanes(ev)))
    })

    def _nearest_tk(t):
        if not tk_times:
            return None
        best, best_d = None, 1e9
        for tt in tk_times:
            d = abs(tt - t)
            if d < best_d:
                best, best_d = tt, d
        return best

    for ev in events:
        t = ev["time"]
        L = set(_lanes(ev))
        bpm = _local_bpm(tempo_map, t)
        has_tk = (2 in L) or (3 in L)  # hi-hat / ride time-keeping
        in_fill = any(s <= t <= e for (s, e) in fills)

        if difficulty == Difficulty.HARD:
            if 0 in L and in_fill:
                L.discard(0)            # no kicks during drum fills
            if 4 in L and 3 in L:
                L.discard(4)            # collapses crash+ride to a single color

        elif difficulty == Difficulty.MEDIUM:
            # No kicks/snares *between* hi-hat/ride time-keeping gems. Audio-
            # derived onsets jitter, so instead of dropping a kick/snare that is
            # merely offset from the hat, snap it onto the nearest time-keeping
            # gem (within tolerance) so the basic beat survives to Easy.
            if (0 in L or 1 in L) and not has_tk:
                nt = _nearest_tk(t)
                if nt is not None and abs(nt - t) <= 0.13:
                    t = nt                     # re-align kick/snare to the hat
                    L = set(_lanes(ev))        # re-evaluate with the new time
                    has_tk = True
                else:
                    L.discard(0)
                    L.discard(1)
            # No 3-limb hits: drop the kick from any 3+ simultaneous gems.
            if len(L) >= 3 and 0 in L:
                L.discard(0)
            # Crash on an off-beat gets no kick underneath; on-beat crash keeps it.
            if 4 in L and 0 in L and not _on_grid(t, tempo_map, 1):
                L.discard(0)
            # >140 BPM: right hand not expected to keep 8ths -> drop off-beat hats.
            if bpm > 140 and 2 in L and not _on_grid(t, tempo_map, 1):
                L.discard(2)
            # >170 BPM: one kick per measure.
            if bpm > 170 and 0 in L:
                meas = int(t // _measure_dur(tempo_map, t))
                if last_kick_measure.get("m") == meas:
                    L.discard(0)
                else:
                    last_kick_measure["m"] = meas

        elif difficulty == Difficulty.EASY:
            # Easy = the basic rock beat: kick + snare only (no hats / toms /
            # cymbals). This is the canonical "never more than 2 limbs, no hand
            # gems paired with kicks" Easy kit (the documented lane-consistency
            # exception — Easy legitimately uses fewer pads).
            L = L & {0, 1}
            # >170 BPM: one kick per measure.
            if bpm > 170 and 0 in L:
                meas = int(t // _measure_dur(tempo_map, t))
                if last_kick_measure.get("m") == meas:
                    L.discard(0)
                else:
                    last_kick_measure["m"] = meas

        for lane in sorted(L):
            src = next((n for n in ev["notes"] if n.lane == lane), ev["notes"][0])
            out.append(ChartNote(
                time=t,
                lane=lane,
                length=0,
                is_open=False,
                is_hopo=False,
                velocity=100,
                difficulty_pitch=getattr(src, "difficulty_pitch", 60 + lane),
            ))
    return out


# --------------------------------------------------------------------------
# Data classes
# --------------------------------------------------------------------------

@dataclass
class ChartNote:
    """A single note in a chart."""
    time: float              # Time in seconds
    lane: int                # 0-4 (5 lanes)
    length: float = 0.0      # Duration in seconds (0 = regular note)
    is_open: bool = False    # Open string (guitar/bass)
    is_hopo: bool = False    # Hammer-on/pull-off
    velocity: int = 100      # MIDI velocity (100=strum, 127=hopo)
    difficulty_pitch: int = 60  # MIDI pitch for specific difficulty

    # Metadata for reduction decisions
    is_chord: bool = False
    chord_notes: list = field(default_factory=list)  # Other notes in same chord
    is_in_solo: bool = False
    is_in_fill: bool = False
    is_in_bre: bool = False


@dataclass
class InstrumentChart:
    """Complete chart for one instrument at Expert difficulty."""
    notes: list[ChartNote]
    tempo_map: list  # [(time, bpm), ...]
    solo_sections: list = field(default_factory=list)  # [(start, end), ...]
    bre_section: Optional[tuple] = None  # (start, end)
    overdrive_phrases: list = field(default_factory=list)  # [(start, end), ...]
    metadata: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Reducer (public)
# --------------------------------------------------------------------------

class DifficultyReducer:
    """
    Reduces Expert charts to Hard / Medium / Easy following Rock Band standards.

    Reduction is applied progressively: Expert -> Hard -> Medium -> Easy.
    """

    def __init__(self, instrument: str):
        self.instrument = instrument.lower()  # 'guitar', 'bass', 'drums', 'keys'

    def reduce(self, expert_chart: InstrumentChart, target: Difficulty) -> InstrumentChart:
        """Reduce chart from Expert to ``target`` difficulty."""
        if target == Difficulty.EXPERT:
            return expert_chart

        if self.instrument == "drums":
            hard = _reduce_drums(
                expert_chart.notes, expert_chart.tempo_map,
                Difficulty.HARD, expert_chart.overdrive_phrases,
            )
            hard_chart = self._wrap(hard, expert_chart, "hard")
            if target == Difficulty.HARD:
                return hard_chart
            medium = _reduce_drums(
                hard_chart.notes, expert_chart.tempo_map,
                Difficulty.MEDIUM, expert_chart.overdrive_phrases,
            )
            medium_chart = self._wrap(medium, expert_chart, "medium")
            if target == Difficulty.MEDIUM:
                return medium_chart
            easy = _reduce_drums(
                medium_chart.notes, expert_chart.tempo_map,
                Difficulty.EASY, expert_chart.overdrive_phrases,
            )
            return self._wrap(easy, expert_chart, "easy")

        # Guitar / Bass / Keys
        all_lanes = (self.instrument == "keys")
        hard = _reduce_fretted(expert_chart.notes, expert_chart.tempo_map,
                               Difficulty.HARD, all_lanes)
        hard = _ensure_lane_consistency(expert_chart.notes, hard,
                                        expert_chart.tempo_map, Difficulty.HARD)
        hard_chart = self._wrap(hard, expert_chart, "hard")
        if target == Difficulty.HARD:
            return hard_chart
        medium = _reduce_fretted(hard_chart.notes, expert_chart.tempo_map,
                                  Difficulty.MEDIUM, all_lanes)
        # NOTE: lane-consistency is intentionally NOT applied to Medium. Medium
        # is allowed to use fewer lanes than Hard (e.g. it legitimately drops
        # orange / certain 2-note pairs), and forcing every Expert lane into
        # Medium would make Medium denser than Hard, inverting the difficulty
        # ordering. Hard and Easy still get lane-consistency below.
        medium_chart = self._wrap(medium, expert_chart, "medium")
        if target == Difficulty.MEDIUM:
            return medium_chart
        easy = _reduce_fretted(medium_chart.notes, expert_chart.tempo_map,
                               Difficulty.EASY, all_lanes)
        easy = _ensure_lane_consistency(expert_chart.notes, easy,
                                        expert_chart.tempo_map, Difficulty.EASY)
        return self._wrap(easy, expert_chart, "easy")

    def _wrap(self, notes, src, diff):
        return InstrumentChart(
            notes=notes,
            tempo_map=src.tempo_map,
            solo_sections=src.solo_sections if diff != "easy" else [],
            bre_section=src.bre_section if diff != "easy" else None,
            overdrive_phrases=src.overdrive_phrases if diff != "easy" else [],
            metadata={**src.metadata, "difficulty": diff},
        )


def create_all_difficulties(expert_chart: InstrumentChart, instrument: str) -> dict:
    """Generate all four difficulty charts from Expert."""
    reducer = DifficultyReducer(instrument)
    return {
        Difficulty.EXPERT: expert_chart,
        Difficulty.HARD: reducer.reduce(expert_chart, Difficulty.HARD),
        Difficulty.MEDIUM: reducer.reduce(expert_chart, Difficulty.MEDIUM),
        Difficulty.EASY: reducer.reduce(expert_chart, Difficulty.EASY),
    }
