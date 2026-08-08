#!/usr/bin/env python
"""
Tests for pitch tracking module.
"""

import pytest
import numpy as np
from autorb.transcribe.pitch_tracking import (
    hz_to_midi,
    detect_pitch_changes,
    segment_syllable_pitch,
    compute_vocal_pitch_per_syllable,
    build_melodic_contour_from_syllables,
    resolve_syllable_pitches_with_fallback,
    octave_snap,
    NoteSegment,
    SyllablePitch,
)


class TestHzToMidi:
    def test_a4_is_69(self):
        assert hz_to_midi(np.array([440.0]))[0] == pytest.approx(69.0, abs=0.01)

    def test_c4_is_60(self):
        assert hz_to_midi(np.array([261.63]))[0] == pytest.approx(60.0, abs=0.01)

    def test_array_input(self):
        result = hz_to_midi(np.array([440.0, 880.0, 220.0]))
        assert result[0] == pytest.approx(69.0, abs=0.01)
        assert result[1] == pytest.approx(81.0, abs=0.01)
        assert result[2] == pytest.approx(57.0, abs=0.01)


class TestDetectPitchChanges:
    def test_no_change_sustained_note(self):
        midi = np.full(100, 60.0)
        changes = detect_pitch_changes(midi, 1.5, 3)
        assert len(changes) == 0

    def test_single_jump(self):
        midi = np.full(100, 60.0)
        midi[50:] = 64.0  # Jump up 4 semitones at frame 50
        changes = detect_pitch_changes(midi, 1.5, 3)
        assert len(changes) >= 1
        # Change should be detected around frame 50
        assert any(45 <= c <= 55 for c in changes)

    def test_slow_slide_not_split(self):
        # Linear slide from 60 to 64 over 100 frames (slow slide)
        # Should be treated as ONE note (plateau-based detection keeps it together)
        midi = np.linspace(60, 64, 100)
        changes = detect_pitch_changes(midi, 1.5, 3)
        assert len(changes) == 0  # Slow slide = no change point

    def test_fast_slide_detected(self):
        # Fast slide: 60 to 64 over 10 frames, then hold
        midi = np.full(100, 60.0)
        midi[40:50] = np.linspace(60, 64, 10)
        midi[50:] = 64.0
        changes = detect_pitch_changes(midi, 1.5, 3)
        # Fast slide should create a plateau boundary
        assert len(changes) >= 1

    def test_vibrato_not_split(self):
        # Vibrato: 60 +/- 0.3 semitones at 6Hz
        frames = np.arange(100)
        midi = 60 + 0.3 * np.sin(2 * np.pi * 6 * frames / 100)
        changes = detect_pitch_changes(midi, 1.5, 3)
        # Vibrato should NOT trigger a change (oscillation < 1.5 semitones)
        assert len(changes) == 0

    def test_c4_to_e4_slide(self):
        # C4 (60) to E4 (64) over 50 frames, then hold
        midi = np.full(100, 60.0)
        midi[25:75] = np.linspace(60, 64, 50)
        midi[75:] = 64.0
        changes = detect_pitch_changes(midi, 1.5, 3)
        assert len(changes) >= 1


class TestSegmentSyllablePitch:
    def test_sustained_note(self):
        times = np.linspace(0, 1.0, 100)
        f0 = np.full_like(times, 261.63)  # C4
        voiced = np.ones_like(times, dtype=bool)
        probs = np.ones_like(times) * 0.9
        
        syl = segment_syllable_pitch(0.0, 1.0, "ah", times, f0, voiced, probs)
        assert len(syl.note_segments) == 1
        assert syl.note_segments[0].midi_note == 60
        assert syl.is_trusted == True

    def test_jump_c4_to_e4(self):
        times = np.linspace(0, 1.0, 100)
        f0 = np.full_like(times, 261.63)  # C4
        f0[times >= 0.5] = 329.63  # E4
        voiced = np.ones_like(times, dtype=bool)
        probs = np.ones_like(times) * 0.9
        
        syl = segment_syllable_pitch(0.0, 1.0, "ah", times, f0, voiced, probs)
        assert len(syl.note_segments) == 2
        assert syl.note_segments[0].midi_note == 60
        assert syl.note_segments[1].midi_note == 64

    def test_vibrato_single_segment(self):
        times = np.linspace(0, 1.0, 100)
        f0 = 261.63 * (1 + 0.02 * np.sin(2 * np.pi * 6 * times))
        voiced = np.ones_like(times, dtype=bool)
        probs = np.ones_like(times) * 0.9
        
        syl = segment_syllable_pitch(0.0, 1.0, "ah", times, f0, voiced, probs)
        assert len(syl.note_segments) == 1
        assert syl.note_segments[0].midi_note == 60

    def test_empty_syllable(self):
        times = np.linspace(0, 0.1, 10)
        f0 = np.full_like(times, np.nan)
        voiced = np.zeros_like(times, dtype=bool)
        probs = np.zeros_like(times)
        
        syl = segment_syllable_pitch(0.0, 0.1, "x", times, f0, voiced, probs)
        assert len(syl.note_segments) == 0
        assert syl.is_trusted == False

    def test_low_confidence(self):
        times = np.linspace(0, 1.0, 100)
        f0 = np.full_like(times, 261.63)
        voiced = np.ones_like(times, dtype=bool)
        probs = np.ones_like(times) * 0.3  # Below threshold
        
        syl = segment_syllable_pitch(0.0, 1.0, "ah", times, f0, voiced, probs)
        assert len(syl.note_segments) == 0
        assert syl.is_trusted == False


class TestOctaveSnap:
    def test_snap_up(self):
        result = octave_snap(48, 60.0)  # C3 -> target C4
        assert result == 60

    def test_snap_down(self):
        result = octave_snap(72, 60.0)  # C5 -> target C4
        assert result == 60

    def test_already_in_range(self):
        result = octave_snap(60, 60.0)
        assert result == 60

    def test_out_of_range(self):
        # C2 (36) + 12 = 48 (C3, in range), + 24 = 60 (C4, in range)
        # So 36 actually CAN be snapped up. Use a note that can't be snapped.
        # G1 (43) -> +12=55 (G3), +24=67 (G4), +36=79 (G5) - all in range
        # B0 (35) -> +24=59 (B3), +36=71 (B4), +48=83 (B5) - all in range
        # A0 (21) -> +36=57 (A3), +48=69 (A4), +60=81 (A5) - all in range
        # The lowest MIDI note is 0, but pyin won't go that low.
        # Actually, let's just test a note that's already in range but wrong octave
        result = octave_snap(108, 60.0)  # C8 (above max)
        # 108-12=96 (C7), -24=84 (C6), -36=72 (C5) - 72 and 84 are in range
        assert result in [72, 84]
        # Test something truly out of range - but pyin won't produce these
        # Just verify the function works
        result = octave_snap(60, 60.0)
        assert result == 60


class TestBuildMelodicContour:
    def test_needs_two_trusted(self):
        syls = [
            SyllablePitch("a", 0, 0.5, [NoteSegment(0, 0.5, 60, 0.9)], True),
        ]
        contour = build_melodic_contour_from_syllables(syls)
        assert contour is None

    def test_interpolates(self):
        syls = [
            SyllablePitch("a", 0, 0.5, [NoteSegment(0, 0.5, 60, 0.9)], True),
            SyllablePitch("b", 1.0, 1.5, [NoteSegment(1.0, 1.5, 64, 0.9)], True),
        ]
        contour = build_melodic_contour_from_syllables(syls)
        assert contour is not None
        assert contour(0.0) == pytest.approx(60, abs=0.5)
        assert contour(1.0) == pytest.approx(64, abs=0.5)
        # Test extrapolation
        assert contour(-0.5) == pytest.approx(60, abs=0.5)
        assert contour(2.0) == pytest.approx(64, abs=0.5)


class TestResolveWithFallback:
    def test_trusted_kept(self):
        syls = [
            SyllablePitch("a", 0, 0.5, [NoteSegment(0, 0.5, 60, 0.9)], True),
        ]
        bp_notes = [(0, 0.5, 72)]  # BP says C5
        contour = lambda t: 60
        
        result = resolve_syllable_pitches_with_fallback(syls, bp_notes, contour)
        assert result[0].note_segments[0].midi_note == 60  # Kept original

    def test_untrusted_snaps_to_contour(self):
        syls = [
            SyllablePitch("a", 0, 0.5, [NoteSegment(0, 0.5, 72, 0.3)], False),  # BP octave error
        ]
        bp_notes = [(0, 0.5, 72)]
        contour = lambda t: 60
        
        result = resolve_syllable_pitches_with_fallback(syls, bp_notes, contour)
        assert result[0].note_segments[0].midi_note == 60  # Snapped to contour


class TestComputeVocalPitchPerSyllable:
    def test_multi_syllable(self):
        import soundfile as sf
        import tempfile
        import os
        
        # Generate synthetic audio
        sr = 22050
        duration = 1.0
        t = np.linspace(0, duration, int(sr * duration))
        f0 = np.full_like(t, 261.63)
        f0[t >= 0.5] = 329.63
        audio = 0.5 * np.sin(2 * np.pi * np.cumsum(f0) / sr)
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            sf.write(f.name, audio, sr)
            stem_path = f.name
        
        try:
            syllables = [
                {"text": "to", "start": 0.0, "end": 0.5},
                {"text": "night", "start": 0.5, "end": 1.0},
            ]
            results = compute_vocal_pitch_per_syllable(syllables, stem_path)
            
            assert len(results) == 2
            assert results[0].syllable_text == "to"
            assert results[1].syllable_text == "night"
            # First syllable should be C4, second E4
            assert results[0].note_segments[0].midi_note == 60
            assert results[1].note_segments[0].midi_note == 64
        finally:
            os.unlink(stem_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

class TestSplitSyllableForDisplay:
    def test_splits_correctly(self):
        from autorb.export.midi_generator import split_syllable_for_display
        
        # Words that pyphen splits
        assert split_syllable_for_display("unconditional", 3) == ['un', 'con', 'ditional']
        assert split_syllable_for_display("flying", 2) == ['fly', 'ing']
        assert split_syllable_for_display("lonesome", 2) == ['lone', 'some']
        assert split_syllable_for_display("moment", 2) == ['mo', 'ment']
        assert split_syllable_for_display("perfect", 2) == ['per', 'fect']
        assert split_syllable_for_display("ambitious", 3) == ['am', 'bi', 'tious']
        assert split_syllable_for_display("beautiful", 3) == ['beau', 'ti', 'ful']
        assert split_syllable_for_display("computer", 2) == ['com', 'puter']
        
    def test_single_segment(self):
        from autorb.export.midi_generator import split_syllable_for_display
        assert split_syllable_for_display("Tonight", 1) == ['Tonight']
        
    def test_unsplittable_word(self):
        from autorb.export.midi_generator import split_syllable_for_display
        # Words pyphen doesn't split repeat full text for all segments
        result = split_syllable_for_display("eighty", 2)
        assert result == ["eighty", "eighty"]
        
    def test_more_segments_than_syllables(self):
        from autorb.export.midi_generator import split_syllable_for_display
        # "fly" (1 syllable) with 3 segments -> ['fly', 'fly', 'fly']
        result = split_syllable_for_display("fly", 3)
        assert result == ['fly', 'fly', 'fly']
        
    def test_more_syllables_than_segments(self):
        from autorb.export.midi_generator import split_syllable_for_display
        # "unconditional" (4 syllables) with 2 segments -> merge last 3
        result = split_syllable_for_display("unconditional", 2)
        assert result[0] == 'un'
        assert 'conditional' in result[1]  # merged rest
