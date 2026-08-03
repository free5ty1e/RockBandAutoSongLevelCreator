import pytest
from pathlib import Path
from autorb.export.con_packer import package_con
from autorb.export.stfs_validator import validate_con

def test_con_packaging_and_validation(tmp_path):
    # Create dummy assets for testing
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    # Create the fixture for the template
    data_dir = Path("autorb/export/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    template_con = data_dir / "template.con"
    if not template_con.exists():
        d = bytearray(0xD000)
        d[0xC000:0xC000+5] = b'songs'
        template_con.write_bytes(d)
    
    songs_dir = output_dir / "songs"
    song_id = "test_song"
    song_staging = songs_dir / song_id
    song_staging.mkdir(parents=True)
    
    dta_path = songs_dir / "songs.dta"
    dta_path.write_text('(test_song (name "Test Song"))')
    
    mogg_path = song_staging / f"{song_id}.mogg"
    mogg_path.write_bytes(b"MOGG_DUMMY_CONTENT" * 100)
    
    midi_path = song_staging / f"{song_id}.mid"
    midi_path.write_bytes(b"MIDI_DUMMY_CONTENT")
    
    con_path = package_con(
        output_dir=output_dir,
        song_id=song_id,
        mogg_path=mogg_path,
        midi_path=midi_path,
        dta_path=dta_path
    )
    
    assert con_path.exists()
    
    # Validate STFS structure using validator
    result = validate_con(con_path)
    assert result["valid"] is True
    assert result["entry_count"] == 8
    assert f"/songs/{song_id}/{song_id}.mogg" in result["virtual_paths"]
    assert f"/songs/{song_id}/{song_id}.mid" in result["virtual_paths"]
    assert "/songs/songs.dta" in result["virtual_paths"]
