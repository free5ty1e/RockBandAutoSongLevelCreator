from pathlib import Path

from autorb.export.dta_writer import generate_songs_dta


def _write_dta(tmp_path: Path, freestyle: bool) -> str:
    metadata = {"title": "Test", "artist": "Tester", "year": 2024, "genre": "Rock",
                "song_id_num": 86876552}
    ranks = {"drum": 100, "guitar": 100, "bass": 100, "vocals": 100, "keys": 0,
             "real_guitar": 0, "real_bass": 0, "real_keys": 0, "band": 100}
    dta_path = generate_songs_dta(
        "test_song", metadata, tmp_path, song_length=200000, ranks=ranks,
        freestyle_vocals=freestyle,
    )
    return dta_path.read_text(encoding="latin1")


def test_freestyle_vocals_flag_written_when_enabled(tmp_path: Path):
    dta = _write_dta(tmp_path, freestyle=True)
    assert "(freestyle_vocals 1)" in dta
    assert dta.endswith("   (song_tonality 0)\n   (freestyle_vocals 1)\n)\n")


def test_freestyle_vocals_flag_omitted_by_default(tmp_path: Path):
    dta = _write_dta(tmp_path, freestyle=False)
    assert "(freestyle_vocals" not in dta
    assert "(vocal_tonic_note" in dta
    assert "(song_tonality" in dta
