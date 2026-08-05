from autorb.export.key_detect import detect_vocal_key


def test_detect_vocal_key_major_c():
    """A C-major melody (C D E G A, sustained) must be detected as C major."""
    notes = [
        [0.0, 1.0, 60],  # C4
        [1.0, 2.0, 62],  # D4
        [2.0, 3.0, 64],  # E4
        [3.0, 4.0, 67],  # G4
        [4.0, 6.0, 69],  # A4 (held)
        [6.0, 9.0, 60],  # back to C, held
    ]
    tonic, tonality = detect_vocal_key(notes)
    assert tonic == 0, f"expected C, got {tonic}"
    assert tonality == 0, f"expected major, got {tonality}"


def test_detect_vocal_key_minor_a():
    """An A-minor melody (A B C D E G) must be detected as A minor."""
    notes = [
        [0.0, 2.0, 57],  # A3 (tonic, held)
        [2.0, 3.0, 59],  # B3
        [3.0, 4.0, 60],  # C4
        [4.0, 5.0, 62],  # D4
        [5.0, 6.0, 64],  # E4
        [6.0, 8.0, 55],  # G3
        [8.0, 10.0, 57],  # A3, held
    ]
    tonic, tonality = detect_vocal_key(notes)
    assert tonic == 9, f"expected A, got {tonic}"
    assert tonality == 1, f"expected minor, got {tonality}"


def test_detect_vocal_key_empty_falls_back():
    assert detect_vocal_key([]) == (4, 0)
    assert detect_vocal_key(None) == (4, 0)
