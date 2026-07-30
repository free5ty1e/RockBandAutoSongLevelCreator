#!/usr/bin/env python

import os
import torch
import torchaudio
from pathlib import Path
from demucs.pretrained import get_model
from demucs.apply import apply_model

def separate_stems(audio_path, output_dir, device="cpu", model_name="htdemucs"):
    """
    Separates audio into drums, bass, other, and vocals stems using Demucs.
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    stems_out_dir = output_dir / "stems"
    stems_out_dir.mkdir(exist_ok=True)
    
    print(f"Loading Demucs model '{model_name}' on {device}...")
    model = get_model(model_name)
    model.to(device)
    model.eval()
    
    print(f"Loading audio file '{audio_path}'...")
    try:
        # wav, sr = torchaudio.load(str(audio_path))
        import librosa
        import torch
        import numpy as np

        # Load via librosa to bypass the torchaudio CUDA dependency bug
        wav_np, sr = librosa.load(str(audio_path), sr=None, mono=False)
        
        # Ensure the array is 2D (channels, time) as expected by Demucs
        if wav_np.ndim == 1:
            wav_np = np.expand_dims(wav_np, axis=0)
            
        wav = torch.from_numpy(wav_np)

    except Exception as e:
        raise RuntimeError(f"Failed to load audio: {e}")
        
    wav = wav.to(device)
    
    # torchaudio.load returns (channels, length), apply_model expects (batch, channels, length)
    wav = wav.unsqueeze(0) 
    
    print("Separating stems (this may take a while)...")
    with torch.no_grad():
        # apply_model returns (batch, sources, channels, length)
        sources = apply_model(model, wav, split=True, overlap=0.25, progress=True)[0]
        
    stem_names = ['drums', 'bass', 'other', 'vocals']
    separated_files = {}
    
    for i, stem in enumerate(stem_names):
        out_file = stems_out_dir / f"{stem}.wav"
        print(f"Saving {stem} stem to {out_file}...")
        # torchaudio.save(str(out_file), sources[i].cpu(), sr)
        import soundfile as sf
        # Convert the PyTorch tensor back to a NumPy array
        audio_data = sources[i].cpu().numpy()
        # PyTorch uses (channels, frames), but soundfile expects (frames, channels)
        if audio_data.ndim == 2:
            audio_data = audio_data.T
        # Write the WAV file using soundfile to bypass torchaudio completely
        sf.write(str(out_file), audio_data, sr)
        separated_files[stem] = out_file
        
    return separated_files
