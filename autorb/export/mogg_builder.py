#!/usr/bin/env python

from pathlib import Path
import logging
import subprocess
import shutil

logger = logging.getLogger(__name__)

def build_mogg_from_stems(stems_dir: str | Path, output_dir: Path, song_id: str) -> Path:
    """
    Combines stem WAV files into a multi-channel MOGG audio container using ffmpeg.
    """
    stems_path = Path(stems_dir)
    mogg_path = output_dir / f"{song_id}.mogg"
    
    stem_names = ["drums", "bass", "other", "vocals"]
    input_files = []
    
    for name in stem_names:
        p = stems_path / f"{name}.wav"
        if p.exists():
            input_files.append(p)
            
    if not input_files:
        input_files = sorted(list(stems_path.glob("*.wav")))

    if input_files:
        logger.info(f"Combining {len(input_files)} stems into multi-channel MOGG container via ffmpeg.")
        cmd = ["ffmpeg", "-y"]
        for f in input_files:
            cmd.extend(["-i", str(f)])
        
        n = len(input_files)
        filter_str = "".join([f"[{i}:a]" for i in range(n)]) + f"amerge=inputs={n}[aout]"
        cmd.extend(["-filter_complex", filter_str, "-map", "[aout]", "-c:a", "libvorbis", "-q:a", "5", str(mogg_path)])
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.warning(f"FFmpeg multi-channel merge failed: {result.stderr}. Falling back to copying primary stem.")
            if input_files:
                shutil.copy2(input_files[0], mogg_path)
    else:
        logger.warning("No stem WAV files found. Generating placeholder MOGG container.")
        mogg_path.write_bytes(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 200)
        
    return mogg_path
