"""
Keys (Keyboard) transcription for Rock Band charts.

Since the user requested that Keys be a playable 5-lane copy of the guitar track 
(mapped to the keyboard controller), this module simply proxies to the new ML-based 
Guitar transcription and updates the metadata.
"""

from pathlib import Path
from .difficulty import InstrumentChart, create_all_difficulties
from .guitar import transcribe_guitar

def transcribe_keys(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    """
    Main keys transcription pipeline.
    
    Reuses the basic_pitch guitar transcription directly for a 5-lane playable
    keyboard chart that matches the guitar part.
    """
    chart = transcribe_guitar(stem_path, tempo_map, song_end, sr)
    chart.metadata['instrument'] = 'keys'
    return chart

def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    """Generate Hard, Medium, Easy from Expert."""
    return create_all_difficulties(expert_chart, 'keys')