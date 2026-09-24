#!/usr/bin/env python3
"""
Chart Evaluation Module

Compares generated charts against reference (known good) charts.
Extracts metrics for timing, pitch, sustain, and difficulty accuracy.
"""

import mido
import json
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

# Instrument track names in Rock Band MIDI
INSTRUMENT_TRACKS = {
    'PART DRUMS': 'drums',
    'PART BASS': 'bass',
    'PART GUITAR': 'guitar',
    'PART KEYS': 'keys',
    'PART VOCALS': 'vocals',
}

# Difficulty pitch bases
DIFFICULTY_BASES = {
    'expert': 96,
    'hard': 84,
    'medium': 72,
    'easy': 60,
}

# Drum lane mapping
DRUM_LANES = {0: 'kick', 1: 'snare', 2: 'hihat', 3: 'ride', 4: 'crash'}

# Guitar/bass lane mapping
FRETTED_LANES = {0: 'green', 1: 'red', 2: 'yellow', 3: 'blue', 4: 'orange'}

@dataclass
class NoteEvent:
    tick: int
    pitch: int
    velocity: int
    lane: int
    difficulty: str
    is_chord: bool = False

@dataclass
class NoteComparison:
    ref_tick: int
    gen_tick: int
    ref_lane: int
    gen_lane: int
    tick_diff: int
    lane_match: bool
    velocity_match: bool

@dataclass
class InstrumentMetrics:
    instrument: str
    difficulty: str
    total_ref_notes: int
    total_gen_notes: int
    matched_notes: int
    false_positives: int
    false_negatives: int
    timing_errors_ms: list
    lane_accuracy: float
    onset_accuracy_ms: float
    sustain_accuracy_ms: float

class ChartEvaluator:
    def __init__(self, max_tick_diff: int = 240):  # ~50ms at 480tpb, 120bpm
        self.max_tick_diff = max_tick_diff
    
    def parse_midi(self, midi_path: Path) -> dict:
        """Parse MIDI file and extract notes per instrument per difficulty."""
        mid = mido.MidiFile(str(midi_path))
        tracks = {}
        
        for track in mid.tracks:
            if track.name not in INSTRUMENT_TRACKS:
                continue
            
            instrument = INSTRUMENT_TRACKS[track.name]
            notes_by_diff = {d: [] for d in DIFFICULTY_BASES}
            
            t = 0
            active_notes = {}  # (pitch, velocity) -> tick_on
            
            for msg in track:
                t += msg.time
                if msg.type == 'note_on' and msg.velocity > 0:
                    pitch = msg.note
                    for diff, base in DIFFICULTY_BASES.items():
                        if base <= pitch < base + 5:
                            lane = pitch - base
                            notes_by_diff[diff].append({
                                'tick': t,
                                'pitch': pitch,
                                'velocity': msg.velocity,
                                'lane': lane,
                                'is_chord': False  # Will be determined later
                            })
                            break
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    pass  # We'll handle sustains separately if needed
            
            # Detect chords (simultaneous notes on same diff within 5 ticks)
            for diff in notes_by_diff:
                notes = sorted(notes_by_diff[diff], key=lambda n: n['tick'])
                for i, n in enumerate(notes):
                    if i > 0 and abs(n['tick'] - notes[i-1]['tick']) <= 5:
                        n['is_chord'] = True
                        notes[i-1]['is_chord'] = True
                notes_by_diff[diff] = notes
            
            tracks[instrument] = notes_by_diff
        
        return tracks
    
    def match_notes(self, ref_notes: list, gen_notes: list, max_tick_diff: int = None) -> list:
        """Match generated notes to reference notes."""
        if max_tick_diff is None:
            max_tick_diff = self.max_tick_diff
        
        matches = []
        matched_gen = set()
        
        for ref in ref_notes:
            best_match = None
            best_diff = max_tick_diff + 1
            
            for i, gen in enumerate(gen_notes):
                if i in matched_gen:
                    continue
                tick_diff = abs(ref['tick'] - gen['tick'])
                if tick_diff <= max_tick_diff and tick_diff < best_diff:
                    best_diff = tick_diff
                    best_match = gen
            
            if best_match:
                matches.append(NoteComparison(
                    ref_tick=ref['tick'],
                    gen_tick=best_match['tick'],
                    ref_lane=ref['lane'],
                    gen_lane=best_match['lane'],
                    tick_diff=best_diff,
                    lane_match=(ref['lane'] == best_match['lane']),
                    velocity_match=(ref['velocity'] == best_match['velocity'])
                ))
                matched_gen.add(gen_notes.index(best_match))
            else:
                matches.append(NoteComparison(
                    ref_tick=ref['tick'],
                    gen_tick=-1,
                    ref_lane=ref['lane'],
                    gen_lane=-1,
                    tick_diff=999999,
                    lane_match=False,
                    velocity_match=False
                ))
        
        return matches
    
    def evaluate(self, ref_midi: Path, gen_midi: Path) -> dict:
        """Evaluate generated MIDI against reference."""
        ref_tracks = self.parse_midi(ref_midi)
        gen_tracks = self.parse_midi(gen_midi)
        
        results = {}
        
        for instrument in INSTRUMENT_TRACKS.values():
            if instrument not in ref_tracks or instrument not in gen_tracks:
                continue
            
            for diff in DIFFICULTY_BASES:
                ref_notes = ref_tracks[instrument].get(diff, [])
                gen_notes = gen_tracks[instrument].get(diff, [])
                
                if not ref_notes and not gen_notes:
                    continue
                
                matches = self.match_notes(ref_notes, gen_notes)
                
                total_ref = len(ref_notes)
                total_gen = len(gen_notes)
                matched = sum(1 for m in matches if m.tick_diff <= self.max_tick_diff)
                false_positives = total_gen - matched
                false_negatives = total_ref - matched
                
                timing_errors = [m.tick_diff for m in matches if m.tick_diff <= self.max_tick_diff]
                lane_accuracy = sum(1 for m in matches if m.lane_match and m.tick_diff <= self.max_tick_diff) / max(matched, 1)
                
                # Convert ticks to ms (approximate at 120 BPM, 480 tpb)
                # 1 tick = 1/480 beat = 60/(120*480) = 1.04ms at 120 BPM
                # Use approximate conversion
                timing_errors_ms = [t * 1.04 for t in timing_errors]
                
                results[f"{instrument}_{diff}"] = InstrumentMetrics(
                    instrument="drums" if instrument == "drums" else instrument,
                    difficulty=diff,
                    total_ref_notes=total_ref,
                    total_gen_notes=total_gen,
                    matched_notes=matched,
                    false_positives=false_positives,
                    false_negatives=false_negatives,
                    timing_errors_ms=timing_errors_ms,
                    lane_accuracy=lane_accuracy,
                    onset_accuracy_ms=sum(timing_errors_ms) / max(len(timing_errors_ms), 1) if timing_errors_ms else 0,
                    sustain_accuracy_ms=0  # TODO: implement sustain comparison
                )
        
        return results

def evaluate_generated_vs_reference(ref_con: Path, gen_con: Path, output_json: Path = None):
    """Main evaluation function."""
    evaluator = ChartEvaluator()
    
    # Extract MIDI from CON files (they contain MIDI in the CON package)
    # For now, assume we have MIDI files extracted
    ref_midi = Path("/tmp/reference_311_down.mid")
    gen_midi = Path("/workspaces/RockBandAutoSongLevelCreator/output/validation/notes.mid")
    
    results = evaluator.evaluate(ref_midi, gen_midi)
    
    # Print summary
    print("=== CHART EVALUATION RESULTS ===")
    for key, metrics in results.items():
        print(f"\n{metrics.instrument} - {metrics.difficulty}:")
        print(f"  Reference notes: {metrics.total_ref_notes}")
        print(f"  Generated notes: {metrics.total_gen_notes}")
        print(f"  Matched: {metrics.matched_notes}")
        print(f"  False positives: {metrics.false_positives}")
        print(f"  False negatives: {metrics.false_negatives}")
        print(f"  Lane accuracy: {metrics.lane_accuracy:.2%}")
        print(f"  Onset accuracy: {metrics.onset_accuracy_ms:.1f}ms avg")
        if metrics.timing_errors_ms:
            print(f"  Timing errors: median={sorted(metrics.timing_errors_ms)[len(metrics.timing_errors_ms)//2]:.1f}ms, "
                  f"max={max(metrics.timing_errors_ms):.1f}ms")
    
    if output_json:
        with open(output_json, 'w') as f:
            json.dump({k: v.__dict__ for k, v in results.items()}, f, indent=2)
    
    return results

if __name__ == "__main__":
    import sys
    ref = sys.argv[1] if len(sys.argv) > 1 else "/tmp/reference_311_down.mid"
    gen = sys.argv[2] if len(sys.argv) > 2 else "/workspaces/RockBandAutoSongLevelCreator/output/validation/notes.mid"
    evaluate_generated_vs_reference(Path(ref), Path(gen), Path("/tmp/eval_results.json"))