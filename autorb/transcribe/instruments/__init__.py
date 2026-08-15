"""
Instrument transcription package for Rock Band chart generation.

This package provides automatic transcription of guitar, bass, drums, and keys
into playable Rock Band 3 charts following Harmonix authoring standards.
"""

from .guitar import transcribe_guitar
from .bass import transcribe_bass
from .drums import transcribe_drums
from .keys import transcribe_keys
from .difficulty import (
    DifficultyReducer,
    InstrumentChart,
    ChartNote,
    Difficulty,
)

__all__ = [
    "transcribe_guitar",
    "transcribe_bass",
    "transcribe_drums",
    "transcribe_keys",
    "DifficultyReducer",
    "InstrumentChart",
    "ChartNote",
    "Difficulty",
]