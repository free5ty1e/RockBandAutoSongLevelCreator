#!/usr/bin/env python

from pathlib import Path
import numpy as np
import soundfile as sf

def mix_stems(stems_dir: Path, output_file: Path):
    # Standard 4 stems (always present)
    stem_names = ["drums.wav", "bass.wav", "other.wav", "vocals.wav"]
    # Optional dedicated stems from 6-stem separators (htdemucs_6s, spleeter:5stems)
    optional_stems = ["guitar.wav", "piano.wav"]

    combined_signal = None
    sample_rate = None

    print("Summing stems into preview mix...")
    # Sum standard stems
    for stem_name in stem_names:
        file_path = stems_dir / stem_name
        if not file_path.exists():
            print(f"Warning: {stem_name} not found in {stems_dir}")
            continue

        data, sr = sf.read(file_path)

        if sample_rate is None:
            sample_rate = sr

        if combined_signal is None:
            combined_signal = np.zeros_like(data)

        combined_signal += data

    # Sum optional dedicated stems (guitar, piano) if present
    # These replace the corresponding content in 'other' for a cleaner mix
    for stem_name in optional_stems:
        file_path = stems_dir / stem_name
        if file_path.exists():
            data, sr = sf.read(file_path)
            if combined_signal is None:
                combined_signal = np.zeros_like(data)
                sample_rate = sr
            combined_signal += data

    # Safeguard against clipping if sum slightly exceeds 0 dBFS
    peak = np.max(np.abs(combined_signal))
    if peak > 1.0:
        combined_signal = combined_signal / peak

    sf.write(output_file, combined_signal, sample_rate)
    print(f"Success! Preview mix saved to: {output_file}")

if __name__ == "__main__":
    stems_folder = Path("./output/stems")
    output_mix = Path("./output/preview_mix.wav")
    mix_stems(stems_folder, output_mix)
    