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
    
    # If a template/valid MOGG already exists for this song, reuse it
    if mogg_path.exists() and mogg_path.stat().st_size > 100000:
        logger.info(f"Reusing existing valid MOGG container at {mogg_path}")
        return mogg_path
    
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
        
        # Explicitly force the 'ogg' format muxer so ffmpeg accepts the .mogg extension
        cmd.extend([
            "-filter_complex", filter_str,
            "-map", "[aout]",
            "-c:a", "libvorbis",
            "-q:a", "5",
            "-f", "ogg",
            str(mogg_path)
        ])
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg multi-channel merge failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed to build MOGG container: {result.stderr}")
    else:
        logger.warning("No stem WAV files found. Generating placeholder MOGG container.")
        mogg_path.write_bytes(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 200)
        
    return mogg_path
