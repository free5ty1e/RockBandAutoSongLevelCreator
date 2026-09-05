"""
Bass transcription for Rock Band charts.

Delegates to the shared Basic Pitch + 5-lane mapper in ``guitar.py`` (bass is a
4-string instrument, guitar is 6-string — the mapper handles both via the
``instrument`` argument).
"""

from pathlib import Path
from .guitar import _transcribe_fretted
from .difficulty import InstrumentChart, create_all_difficulties


def transcribe_bass(
    stem_path: Path,
    tempo_map: list,
    song_end: float,
    sr: int = 44100,
) -> InstrumentChart:
    return _transcribe_fretted(stem_path, tempo_map, song_end, sr, "bass")


def generate_all_difficulties(expert_chart: InstrumentChart) -> dict:
    return create_all_difficulties(expert_chart, "bass")
