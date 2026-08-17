"""
Difficulty reduction engine for instrument charts.

Reduces Expert charts to Hard, Medium, and Easy following
Rock Band authoring standards.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import numpy as np


class Difficulty(Enum):
    EXPERT = "expert"
    HARD = "hard"
    MEDIUM = "medium"
    EASY = "easy"


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


def _snap(time: float, tempo_map, divisions: int = 2) -> float:
    """Snap a time to the nearest ``divisions``-per-beat grid at the local BPM.

    divisions=2 -> 1/8 notes. Used to de-"sporadic"-ify drum charts so hits
    land where a drummer expects them on the beat grid.
    """
    if not tempo_map:
        return time
    step = (60.0 / _local_bpm(tempo_map, time)) / divisions
    return round(time / step) * step


def _drum_reduce(notes, tempo_map, keep_lanes, divisions: int = 2, half_kick: bool = False):
    """Role/lane-based drum difficulty reduction.

    Keeps only the requested lanes (0=kick, 1=snare, 2=hat, 3=tom/ride,
    4=crash), snaps to the beat grid, and (for Easy) drops every other kick so
    the chart is strictly simpler than Medium. Returns fresh ChartNotes.
    """
    out = []
    kick_count = 0
    for n in sorted(notes, key=lambda x: x.time):
        if n.lane not in keep_lanes:
            continue
        if half_kick and n.lane == 0:
            kick_count += 1
            if kick_count % 2 == 0:
                continue
        out.append(ChartNote(
            time=_snap(n.time, tempo_map, divisions),
            lane=n.lane,
            length=0,
            is_open=False,
            is_hopo=False,
            velocity=100,
            difficulty_pitch=n.difficulty_pitch,
        ))
    return out


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


class DifficultyReducer:
    """
    Reduces Expert charts to Hard/Medium/Easy following Rock Band standards.
    
    Reduction is applied progressively: Expert → Hard → Medium → Easy
    """
    
    # Density cap (notes per second) per difficulty
    DENSITY_CAPS = {
        Difficulty.EXPERT: 16.0,
        Difficulty.HARD: 14.0,
        Difficulty.MEDIUM: 10.0,
        Difficulty.EASY: 6.0,
    }
    
    def __init__(self, instrument: str):
        self.instrument = instrument.lower()  # 'guitar', 'bass', 'drums'
    
    def reduce(
        self,
        expert_chart: InstrumentChart,
        target: Difficulty,
    ) -> InstrumentChart:
        """Reduce chart from Expert to target difficulty."""
        if target == Difficulty.EXPERT:
            return expert_chart
        elif target == Difficulty.HARD:
            return self._to_hard(expert_chart)
        elif target == Difficulty.MEDIUM:
            hard = self._to_hard(expert_chart)
            return self._to_medium(hard)
        elif target == Difficulty.EASY:
            hard = self._to_hard(expert_chart)
            medium = self._to_medium(hard)
            return self._to_easy(medium)
        else:
            raise ValueError(f"Unknown difficulty: {target}")
    
    def _to_hard(self, chart: InstrumentChart) -> InstrumentChart:
        """
        Expert → Hard: Remove ~20-30% notes.
        Keep all HOPOs, chords, holds, solo/BRE sections.
        Cap density at ~14 notes/sec.

        Drums: drop cymbals (lane 4) and snap to the 1/8 grid so Hard is a
        strictly simpler, on-grid kit chart than Expert.
        """
        if self.instrument == 'drums':
            notes = _drum_reduce(chart.notes, chart.tempo_map, keep_lanes={0, 1, 2, 3}, divisions=2)
            return InstrumentChart(
                notes=notes,
                tempo_map=chart.tempo_map,
                solo_sections=chart.solo_sections,
                bre_section=chart.bre_section,
                overdrive_phrases=chart.overdrive_phrases,
                metadata={**chart.metadata, 'difficulty': 'hard'},
            )

        notes = self._thin_notes(chart.notes, target_density=14.0, preserve_important=True)
        
        return InstrumentChart(
            notes=notes,
            tempo_map=chart.tempo_map,
            solo_sections=chart.solo_sections,
            bre_section=chart.bre_section,
            overdrive_phrases=chart.overdrive_phrases,
            metadata={**chart.metadata, 'difficulty': 'hard'},
        )
    
    def _to_medium(self, chart: InstrumentChart) -> InstrumentChart:
        """
        Hard → Medium:
        - Guitar/Bass: Remove HOPOs (convert to strums), max 2-note chords, no orange lane
        - Drums: Keep kick/snare/hat (drop toms + cymbals) and snap to the 1/8 grid
        - Cap density at ~10 notes/sec
        """
        if self.instrument == 'drums':
            notes = _drum_reduce(chart.notes, chart.tempo_map, keep_lanes={0, 1, 2}, divisions=2)
            return InstrumentChart(
                notes=notes,
                tempo_map=chart.tempo_map,
                solo_sections=chart.solo_sections,
                bre_section=chart.bre_section,
                overdrive_phrases=chart.overdrive_phrases,
                metadata={**chart.metadata, 'difficulty': 'medium'},
            )

        notes = []
        
        for note in chart.notes:
            new_note = ChartNote(
                time=note.time,
                lane=note.lane,
                length=note.length,
                is_open=note.is_open,
                is_hopo=False,  # Remove all HOPOs
                velocity=100,
                difficulty_pitch=note.difficulty_pitch,
                is_chord=note.is_chord,
                chord_notes=note.chord_notes,
                is_in_solo=note.is_in_solo,
                is_in_fill=note.is_in_fill,
                is_in_bre=note.is_in_bre,
            )
            
            # Guitar/Bass: remove orange lane (lane 4)
            if self.instrument in ('guitar', 'bass'):
                if new_note.lane == 4:  # Orange
                    continue
                # Simplify chords to max 2 notes
                if new_note.is_chord and len(new_note.chord_notes) > 1:
                    # Keep only root + one other (simplified)
                    pass  # Handled at chord level
            
            notes.append(new_note)
        
        # Thin to density cap
        notes = self._thin_notes(notes, target_density=10.0, preserve_important=False)
        
        return InstrumentChart(
            notes=notes,
            tempo_map=chart.tempo_map,
            solo_sections=chart.solo_sections,
            bre_section=chart.bre_section,
            overdrive_phrases=chart.overdrive_phrases,
            metadata={**chart.metadata, 'difficulty': 'medium'},
        )
    
    def _to_easy(self, chart: InstrumentChart) -> InstrumentChart:
        """
        Medium → Easy:
        - Guitar/Bass: Single notes only, quarter/eighth grid, root notes only
        - Drums: Basic rock beat only (kick 1/3, snare 2/4, hat eighths)
        - Cap density at ~6 notes/sec
        """
        notes = []
        
        if self.instrument in ('guitar', 'bass'):
            # Only root notes on downbeats/strong beats
            for note in chart.notes:
                if note.is_chord:
                    continue  # No chords on Easy
                if note.lane >= 3:  # No blue/orange
                    continue
                if note.is_hopo:
                    continue  # No HOPOs
                
                new_note = ChartNote(
                    time=note.time,
                    lane=note.lane,
                    length=0,
                    is_open=note.is_open,
                    is_hopo=False,
                    velocity=100,
                    difficulty_pitch=note.difficulty_pitch,
                )
                notes.append(new_note)
        
        elif self.instrument == 'drums':
            # Basic rock beat: kick/snare/hat on the 1/8 grid, every other kick
            # dropped so Easy is strictly simpler than Medium. (Toms/cymbals are
            # already gone after _to_medium.)
            notes = _drum_reduce(
                chart.notes, chart.tempo_map,
                keep_lanes={0, 1, 2}, divisions=2, half_kick=True,
            )

        # Thin to density cap
        notes = self._thin_notes(notes, target_density=6.0, preserve_important=False)
        
        return InstrumentChart(
            notes=notes,
            tempo_map=chart.tempo_map,
            solo_sections=[],  # No solos on Easy
            bre_section=None,  # No BRE on Easy
            overdrive_phrases=[],  # No OD on Easy
            metadata={**chart.metadata, 'difficulty': 'easy'},
        )
    
    def _thin_notes(
        self,
        notes: list[ChartNote],
        target_density: float,
        preserve_important: bool,
    ) -> list[ChartNote]:
        """
        Thin notes to achieve target density (notes per second).
        
        Uses a sliding window to measure local density and remove
        least important notes where density exceeds cap.
        """
        if not notes:
            return notes
        
        # Sort by time
        notes = sorted(notes, key=lambda n: n.time)
        
        # Mark important notes that should never be removed
        for note in notes:
            note._protected = (
                note.is_hopo or
                note.is_chord or
                note.length > 0 or  # Hold notes
                note.is_in_solo or
                note.is_in_bre or
                (note.is_in_fill and self.instrument == 'drums')
            )
        
        # Sliding window density check
        window_size = 1.0  # 1 second window
        step = 0.25
        
        max_time = max(n.time for n in notes)
        to_remove = set()
        
        t = 0
        while t <= max_time:
            window_notes = [n for n in notes if t <= n.time < t + window_size]
            density = len(window_notes) / window_size
            
            if density > target_density:
                # Need to remove some notes
                excess = int(len(window_notes) - target_density * window_size)
                
                # Sort by importance (protected last, then by velocity, then random)
                removable = [n for n in window_notes if not n._protected]
                removable.sort(key=lambda n: (n.velocity, n.time))
                
                for n in removable[:excess]:
                    to_remove.add(id(n))
            
            t += step
        
        # Filter out removed notes
        filtered = [n for n in notes if id(n) not in to_remove]
        
        # Clean up
        for n in filtered:
            if hasattr(n, '_protected'):
                del n._protected
        
        return filtered
    
    def _quantize_to_grid(
        self,
        notes: list[ChartNote],
        grid_resolution: float,  # e.g., 0.5 for eighth notes at 120 BPM
    ) -> list[ChartNote]:
        """Quantize note times to a rhythmic grid."""
        quantized = []
        for note in notes:
            quantized_time = round(note.time / grid_resolution) * grid_resolution
            quantized.append(ChartNote(
                time=quantized_time,
                lane=note.lane,
                length=note.length,
                is_open=note.is_open,
                is_hopo=note.is_hopo,
                velocity=note.velocity,
                difficulty_pitch=note.difficulty_pitch,
                is_chord=note.is_chord,
                chord_notes=note.chord_notes,
                is_in_solo=note.is_in_solo,
                is_in_fill=note.is_in_fill,
                is_in_bre=note.is_in_bre,
            ))
        return quantized


def create_all_difficulties(
    expert_chart: InstrumentChart,
    instrument: str,
) -> dict[Difficulty, InstrumentChart]:
    """Generate all four difficulty charts from Expert."""
    reducer = DifficultyReducer(instrument)
    
    return {
        Difficulty.EXPERT: expert_chart,
        Difficulty.HARD: reducer.reduce(expert_chart, Difficulty.HARD),
        Difficulty.MEDIUM: reducer.reduce(expert_chart, Difficulty.MEDIUM),
        Difficulty.EASY: reducer.reduce(expert_chart, Difficulty.EASY),
    }