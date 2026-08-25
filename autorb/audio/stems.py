#!/usr/bin/env python

from pathlib import Path
import gc
import numpy as np
import torch
import librosa
import soundfile as sf
import click
from demucs.apply import apply_model
from demucs.pretrained import get_model

def separate_stems(audio_path: Path, out_dir: Path, device: str = "cpu",
                  model_name: str = "htdemucs") -> dict:
    out_dir = Path(out_dir)
    stems_dir = out_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Loading Demucs model '{model_name}' on {device}...")
    model = get_model(model_name)
    # htdemucs_ft ships as a BagOfModels *ensemble* (several fine-tuned sub-models
    # averaged together). The ensemble is ~4x the weight footprint and OOMs most
    # CPUs on a full track even chunked, so when chunking we unwrap to a single
    # sub-model (still cleaner separation than stock htdemucs, and usable on CPU).
    if model_name == "htdemucs_ft" and hasattr(model, "models") and model.models:
        model = model.models[0]
        click.echo("  htdemucs_ft ensemble -> using single sub-model (fits CPU RAM).")
    # Bound torch's CPU thread pool BEFORE any model use. torch allocates a
    # per-thread workspace that scales with num_threads; on a many-core box the
    # default (all cores) balloons peak memory enough to OOM-kill (SIGKILL,
    # uncatchable) a full 198s separation mid-run -- even chunked, even with the
    # ensemble unwrapped to a single sub-model. 4 threads is the verified-safe
    # ceiling on an 8 GB host (the full ensemble ran to completion at this setting
    # in ft_full_clean.py; the unbounded-CPU default is what died at chunk 31).
    torch.set_num_threads(min(4, torch.get_num_threads()))
    model.to(device)

    click.echo(f"Loading audio file '{audio_path}'...")
    wav_np, sr = librosa.load(str(audio_path), sr=None, mono=False)
    if wav_np.ndim == 1:
        wav_np = np.expand_dims(wav_np, axis=0)
    wav = torch.from_numpy(wav_np).to(device)

    # Demucs expects (batch, channels, time)
    if wav.ndim == 2:
        wav = wav.unsqueeze(0)

    n = wav.shape[2]
    click.echo("Separating stems (this may take a while)...")
    if model_name == "htdemucs_ft":
        # The ensemble OOM-kills the full 198 s track (its ``sources_p``
        # accumulator is sized to the full input -- per-chunk bounding does not
        # bound that). Separate in overlapping 45 s strips (each strip is itself
        # 10 s COLA-chunked internally) and equal-power-merge the strip stems,
        # so peak memory is ~45 s of output instead of 198 s. Strips are freed
        # eagerly (del + gc) as they are merged.
        try:
            sources = _separate_strips(model, wav, sr, device,
                                       strip_seconds=45.0, overlap_seconds=10.0,
                                       chunk_seconds=10.0,
                                       progress=lambda k, m: click.echo(
                                           f"  separating strip {k}/{m} (htdemucs_ft)...",
                                           err=True))
        except (RuntimeError, torch.cuda.OutOfMemoryError):
            click.echo("45 s strips OOM'd; retrying with 20 s strips...")
            try:
                sources = _separate_strips(model, wav, sr, device,
                                           strip_seconds=20.0, overlap_seconds=10.0,
                                           chunk_seconds=10.0,
                                           progress=lambda k, m: click.echo(
                                               f"  separating strip {k}/{m} (htdemucs_ft, 20 s)...",
                                               err=True))
            except (RuntimeError, torch.cuda.OutOfMemoryError):
                click.echo("htdemucs_ft still OOMs on this device; falling back to stock 'htdemucs'.")
                model = get_model("htdemucs"); model.to(device)
                ref = wav.mean(0); wav_n = (wav - ref.mean()) / (ref.std() + 1e-8)
                with torch.no_grad():
                    sources = apply_model(model, wav_n, device=device)[0]
                sources = sources * ref.std() + ref.mean()
    else:
        # htdemucs (single model): the 198 s track fits in CPU RAM in one call.
        sources = _separate_audio(model, wav, sr, device, chunked=False, progress=lambda k, m: click.echo(
            f"  separating chunk {k}/{m} (htdemucs)...", err=True))

    stem_names = model.sources  # ['drums', 'bass', 'other', 'vocals']
    stems_paths = {}

    # Save individual stems
    for i, name in enumerate(stem_names):
        out_file = stems_dir / f"{name}.wav"
        click.echo(f"Saving {name} stem to {out_file}...")
        
        audio_data = sources[i].cpu().numpy()
        if audio_data.ndim == 2:
            audio_data = audio_data.T
            
        sf.write(str(out_file), audio_data, sr)
        stems_paths[name] = out_file

    # Generate preview mix by summing tensors in memory
    click.echo("Generating preview mix...")
    preview_file = out_dir / "preview_mix.mp3"
    mix_data = sources.sum(dim=0).cpu().numpy()
    
    if mix_data.ndim == 2:
        mix_data = mix_data.T
        
    peak = np.max(np.abs(mix_data))
    if peak > 1.0:
        mix_data = mix_data / peak

    # Write to an in-memory WAV buffer, then encode to MP3 using pydub
    import io
    from pydub import AudioSegment

    wav_io = io.BytesIO()
    sf.write(wav_io, mix_data, sr, format='WAV')
    wav_io.seek(0)
    
    preview_audio = AudioSegment.from_wav(wav_io)
    preview_audio.export(str(preview_file), format="mp3", bitrate="192k")
    
    click.echo(f"Preview mix saved to {preview_file}")
    stems_paths["preview_mix"] = preview_file

    return stems_paths


def _separate_audio(model, wav, sr, device, chunked=False, chunk_seconds=20.0,
                    progress=None):
    """Run Demucs separation, optionally chunked to bound memory.

    ``htdemucs`` separates the full track in one call (~198 s fits in CPU RAM).
    The fine-tuned ``htdemucs_ft`` model is a *BagOfModels* ensemble (heavier per
    frame) and the 198 s Eve6 track OOMs on CPU in one pass
    (``RuntimeError``/kill, no traceback). When ``chunked`` is set we split into
    50%-overlapping sine-windowed frames of ``chunk_seconds`` and overlap-add the
    denormalized outputs (constant-overlap reconstruction, no seams), so peak
    memory is bounded by the chunk. Each chunk is mean/std-normalized by the
    global per-track ref (matching the non-chunked path). ``progress`` is an
    optional callable(i, nchunks) for status.
    """
    ref = wav.mean(0)
    wav_n = (wav - ref.mean()) / (ref.std() + 1e-8)

    if not chunked:
        with torch.no_grad():
            sources = apply_model(model, wav_n, device=device)[0]
        return sources * ref.std() + ref.mean()

    n = wav.shape[2]
    chunk = int(chunk_seconds * sr)
    if chunk >= n or chunk <= 0:
        return _separate_audio(model, wav, sr, device, chunked=False, progress=progress)
    step = chunk // 2
    # 50% overlap with a sine (half-cycle raised-cosine) window satisfies COLA for
    # the sum of squared weights: sin^2(x) + sin^2(x + pi/2) = 1, so dividing by
    # the running sum of w^2 reconstructs the interior exactly with no seams.
    #
    # The ONLY defect is the boundary: sample 0 is covered by a single window
    # whose weight -> 0 there, so acc/wsum -> a +1.0 spike at t ~= 0.003s (and
    # the same at the tail). Reflection-padding the input by one hop on each side
    # moves every real output sample into the 2-window interior (where wsum ~= 1),
    # killing the spike while leaving the COLA-true interior untouched.
    i = torch.arange(chunk, dtype=torch.float32, device=device)
    base_win = torch.sin(torch.pi * (i + 0.5) / chunk)

    n_src = len(model.sources)
    wav_p = torch.nn.functional.pad(wav_n, (step, step), mode='reflect')
    sp = wav_p.shape[2]
    n_chunks = max(1, (sp - chunk) // step + 1)
    sources_p = torch.zeros(n_src, wav_p.shape[1], sp, device=device)
    wsum_p = torch.zeros(sp, device=device)
    for k, s in enumerate(range(0, sp - chunk + 1, step)):
        if progress:
            progress(k, n_chunks)
        seg = wav_p[:, :, s:s + chunk]
        with torch.no_grad():
            src = apply_model(model, seg, device=device)[0]
        assert src.shape[2] == chunk, (src.shape, chunk)
        src = src * ref.std() + ref.mean()  # ref is the global per-track ref
        sources_p[:, :, s:s + chunk] += src * base_win
        wsum_p[s:s + chunk] += base_win ** 2
        # Free this chunk's model activations eagerly (see comment above).
        del src, seg
        gc.collect()
    if progress:
        progress(n_chunks, n_chunks)
    wsum_p = torch.clamp(wsum_p, min=1e-8)
    sources_p = sources_p / wsum_p
    # drop the one-hop reflection padding on each side
    return sources_p[:, :, step:step + n]


def _separate_strips(model, wav, sr, device,
                     strip_seconds=45.0, overlap_seconds=10.0,
                     chunk_seconds=10.0, progress=None):
    """Memory-bounded full-track separation for heavy models (e.g. ``htdemucs_ft``).

    The full-length chunked path (:func:`_separate_audio` with ``chunked=True``)
    still allocates its ``sources_p`` accumulator over the *entire* input, so on an
    8 GB host the 198 s Eve6 ``htdemucs_ft`` ensemble OOM-kills mid-run (verified:
    dies ~chunk 4 with no traceback). This splits the track into ``strip_seconds``-
    long strips (``overlap_seconds`` overlap, 50 % step) and separates each strip
    via :func:`_separate_audio` (which 10 s COLA-chunks it internally), then merges
    the strip-level stems with a level-constant linear crossfade over the overlap.

    Peak memory is bounded by one strip (~45 s x 4 stems x 2 ch) instead of the
    full track, so the entire song completes. Strips are freed as they are merged.
    Memory fallback chain (caller): 45 s -> 20 s -> stock ``htdemucs``.
    """
    n = wav.shape[2]
    step = int(round((strip_seconds - overlap_seconds) * sr))
    strip_len = int(round(strip_seconds * sr))
    overlap = int(round(overlap_seconds * sr))
    if step <= 0:
        raise ValueError(f"overlap_seconds ({overlap_seconds}) must be < strip_seconds ({strip_seconds})")
    if strip_len >= n:
        # track is shorter than one strip: fall back to direct chunked separation
        return _separate_audio(model, wav, sr, device,
                               chunked=True, chunk_seconds=chunk_seconds, progress=progress)

    # level-constant crossfade: fade_out (1->0) + fade_in (0->1) sum to 1.0 in the
    # overlap, so acc/wsum preserves level with no seam. (These are smooth stems,
    # so a linear blend over the 10 s overlap is inaudible.)
    lin = torch.linspace(0.0, 1.0, overlap, device=device)
    win_fade_in = lin
    win_fade_out = 1.0 - lin

    starts = list(range(0, n - strip_len + 1, step))
    if not starts or starts[-1] + strip_len < n:
        starts.append(max(0, n - strip_len))  # final strip flush to the tail
    n_strips = len(starts)

    n_src = len(model.sources)
    ch = wav.shape[1]
    full_sources = torch.zeros(n_src, ch, n, device=device)
    wsum = torch.zeros(n, device=device)

    for i, s in enumerate(starts):
        if progress:
            progress(i, n_strips)
        e = min(s + strip_len, n)
        seg = wav[:, :, s:e]
        seg_sources = _separate_audio(model, seg, sr, device,
                                      chunked=True, chunk_seconds=chunk_seconds)
        seg_len = seg_sources.shape[2]
        w = torch.ones(seg_len, device=device)
        if i > 0:                          # fade in the head (overlap prev strip)
            w[:overlap] = win_fade_in[:overlap]
        if i < n_strips - 1:               # fade out the tail (overlap next strip)
            w[-overlap:] = win_fade_out[:overlap]
        full_sources[:, :, s:s + seg_len] += seg_sources * w
        wsum[s:s + seg_len] += w
        del seg, seg_sources
        gc.collect()
    if progress:
        progress(n_strips, n_strips)

    wsum = torch.clamp(wsum, min=1e-8)
    return full_sources / wsum

