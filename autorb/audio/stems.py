#!/usr/bin/env python

from pathlib import Path
import numpy as np
import torch
import librosa
import soundfile as sf
from demucs.apply import apply_model
from demucs.pretrained import get_model

def separate_stems(audio_path: Path, out_dir: Path, device: str = "cpu") -> dict:
    out_dir = Path(out_dir)
    stems_dir = out_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading Demucs model 'htdemucs' on {device}...")
    model = get_model("htdemucs")
    model.to(device)

    print(f"Loading audio file '{audio_path}'...")
    wav_np, sr = librosa.load(str(audio_path), sr=None, mono=False)
    if wav_np.ndim == 1:
        wav_np = np.expand_dims(wav_np, axis=0)
    wav = torch.from_numpy(wav_np).to(device)

    # Demucs expects (batch, channels, time)
    if wav.ndim == 2:
        wav = wav.unsqueeze(0)

    print("Separating stems (this may take a while)...")
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / ref.std()
    
    with torch.no_grad():
        sources = apply_model(model, wav, device=device)[0]

    sources = sources * ref.std() + ref.mean()
    stem_names = model.sources  # ['drums', 'bass', 'other', 'vocals']
    stems_paths = {}

    # Save individual stems
    for i, name in enumerate(stem_names):
        out_file = stems_dir / f"{name}.wav"
        print(f"Saving {name} stem to {out_file}...")
        
        audio_data = sources[i].cpu().numpy()
        if audio_data.ndim == 2:
            audio_data = audio_data.T
            
        sf.write(str(out_file), audio_data, sr)
        stems_paths[name] = out_file

    # Generate preview mix by summing tensors in memory
    print("Generating preview mix...")
    preview_file = out_dir / "preview_mix.wav"
    mix_data = sources.sum(dim=0).cpu().numpy()
    
    if mix_data.ndim == 2:
        mix_data = mix_data.T
        
    peak = np.max(np.abs(mix_data))
    if peak > 1.0:
        mix_data = mix_data / peak

    sf.write(str(preview_file), mix_data, sr)
    print(f"Preview mix saved to {preview_file}")
    stems_paths["preview_mix"] = preview_file

    return stems_paths