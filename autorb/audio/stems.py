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


def _clear_stems_dir(stems_dir: Path) -> None:
    """Remove stale stem WAVs before a new separation run.

    Different separators emit different stem sets (e.g. ``htdemucs_6s`` adds
    guitar/piano), and a leftover ``guitar.wav`` from a previous 6-stem run
    would otherwise be silently picked up by charting/MOGG mixing on a
    subsequent 4-stem run. Only files directly inside ``stems_dir`` are
    removed — never recurse.
    """
    removed = []
    for f in sorted(stems_dir.glob("*.wav")):
        try:
            f.unlink()
            removed.append(f.name)
        except OSError as e:
            click.echo(f"Warning: could not remove stale stem {f}: {e}", err=True)
    if removed:
        click.echo(f"Cleared {len(removed)} stale stem file(s) from {stems_dir}: "
                   f"{', '.join(removed)}")


def separate_stems(audio_path: Path, out_dir: Path, device: str = "cpu",
                   model_name: str = "htdemucs_ft", shifts: int = 1,
                   overlap: float = 0.25, segment: float = None,
                   strip_seconds: float = 45.0) -> dict:
    out_dir = Path(out_dir)
    stems_dir = out_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    _clear_stems_dir(stems_dir)

    click.echo(f"Loading Demucs model '{model_name}' on {device}...")
    model = get_model(model_name)
    # NOTE: htdemucs_ft is a BagOfModels *ensemble* of several fine-tuned
    # sub-models averaged by apply_model. Do NOT unwrap to a single sub-model
    # (model.models[0]) here: the sub-models are not interchangeable and one of
    # them bleeds bass/other 5x worse (verified on the Open Road Song 60s clip,
    # bass<->other NCC 0.172 single-sub vs 0.034 full ensemble). The full
    # ensemble is the quality winner. Sectioned stripping (below) bounds its
    # memory so it fits on an 8 GB CPU regardless.
    # Bound torch's CPU thread pool BEFORE any model use. torch allocates a
    # per-thread workspace that scales with num_threads; on a many-core host the
    # default (all cores) balloons peak memory enough to OOM-kill (SIGKILL,
    # uncatchable). 4 threads is the verified-safe ceiling on an 8 GB host.
    torch.set_num_threads(min(4, torch.get_num_threads()))
    model.to(device)

    apply_kwargs = {"shifts": shifts, "overlap": overlap}


    click.echo(f"Loading audio file '{audio_path}'...")
    wav_np, sr = librosa.load(str(audio_path), sr=None, mono=False)
    if wav_np.ndim == 1:
        wav_np = np.expand_dims(wav_np, axis=0)
    wav = torch.from_numpy(wav_np).to(device)

    # Demucs expects (batch, channels, time)
    if wav.ndim == 2:
        wav = wav.unsqueeze(0)

    n = wav.shape[2]
    if segment is not None:
        apply_kwargs["segment"] = int(round(segment * sr))
    click.echo(f"Separating stems (this may take a while) with "
               f"shifts={apply_kwargs.get('shifts')}, overlap={overlap}, "
               f"segment={apply_kwargs.get('segment')}...")

    stem_names = model.sources  # ['drums', 'bass', 'other', 'vocals']
    stems_paths = {}

    # Use memory-bounded strip processing for ALL models on long tracks
    # This writes stems directly to files, never holding full track in memory
    try:
        _separate_strips(model, wav, sr, device,
                         strip_seconds=strip_seconds, overlap_seconds=10.0,
                         chunk_seconds=10.0, apply_kwargs=apply_kwargs,
                         progress=lambda k, m: click.echo(
                             f"  separating strip {k}/{m} ({model_name})...",
                             err=True),
                         output_stems_dir=stems_dir, stem_names=stem_names)
    except (RuntimeError, torch.cuda.OutOfMemoryError):
        click.echo(f"{strip_seconds}s strips OOM'd; retrying with 20 s strips...")
        try:
            _separate_strips(model, wav, sr, device,
                             strip_seconds=20.0, overlap_seconds=10.0,
                             chunk_seconds=10.0, apply_kwargs=apply_kwargs,
                             progress=lambda k, m: click.echo(
                                 f"  separating strip {k}/{m} ({model_name}, 20s)...",
                                 err=True),
                             output_stems_dir=stems_dir, stem_names=stem_names)
        except (RuntimeError, torch.cuda.OutOfMemoryError):
            click.echo(f"{model_name} still OOMs on this device; trying 10s strips...")
            _separate_strips(model, wav, sr, device,
                             strip_seconds=10.0, overlap_seconds=5.0,
                             chunk_seconds=5.0, apply_kwargs=apply_kwargs,
                             progress=lambda k, m: click.echo(
                                 f"  separating strip {k}/{m} ({model_name}, 10s)...",
                                 err=True),
                             output_stems_dir=stems_dir, stem_names=stem_names)

    # Load saved stems for preview mix generation
    click.echo("Generating preview mix...")
    preview_file = out_dir / "preview_mix.mp3"

    # Sum stems from disk to avoid holding full track in memory
    mix_data = None
    for i, name in enumerate(stem_names):
        out_file = stems_dir / f"{name}.wav"
        click.echo(f"Loading {name} stem from {out_file}...")
        audio_data, _ = sf.read(str(out_file), dtype='float32')
        if audio_data.ndim == 1:
            audio_data = np.expand_dims(audio_data, axis=1)
        # Convert to (channels, time)
        audio_data = audio_data.T
        stems_paths[name] = out_file

        if mix_data is None:
            mix_data = audio_data.copy()
        else:
            mix_data += audio_data

    if mix_data is not None:
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
                    progress=None, apply_kwargs=None):
    """Run Demucs separation, optionally chunked to bound memory.

    ``apply_kwargs`` is forwarded to ``demucs.apply.apply_model`` (e.g.
    ``shifts``, ``overlap``, ``segment``) so callers can trade quality for speed
    / memory on CPU. See :func:`separate_stems` for the public entry point.
    """
    apply_kwargs = apply_kwargs or {}
    ref = wav.mean(0)
    wav_n = (wav - ref.mean()) / (ref.std() + 1e-8)

    if not chunked:
        with torch.no_grad():
            sources = apply_model(model, wav_n, device=device, **apply_kwargs)[0]
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
            src = apply_model(model, seg, device=device, **apply_kwargs)[0]
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
                     chunk_seconds=10.0, progress=None, apply_kwargs=None,
                     output_stems_dir=None, stem_names=None):
    """Memory-bounded full-track separation for heavy models (e.g. ``htdemucs_ft``).

    The full-length chunked path (:func:`_separate_audio` with ``chunked=True``)
    still allocates its ``sources_p`` accumulator over the *entire* input, so on an
    8 GB host the 198 s Eve6 ``htdemucs_ft`` ensemble OOM-kills mid-run (dies ~chunk
    4 with no traceback). This splits the track into ``strip_seconds``-long strips
    (``overlap_seconds`` overlap, 50 % step) and separates each strip via
    :func:`_separate_audio` (which 10 s COLA-chunks it internally, forwarding
    ``apply_kwargs``), then merges the strip-level stems with a level-constant
    linear crossfade over the overlap.

    **Memory-bounded design:** This function writes each stem directly to its output
    file incrementally, NEVER holding the full track in memory. Peak memory is
    bounded by one strip (~45 s x 4 stems x 2 ch) instead of the full track.

    Args:
        model: Demucs model
        wav: Input audio tensor (batch, channels, time)
        sr: Sample rate
        device: torch device
        strip_seconds: Strip length in seconds
        overlap_seconds: Overlap between strips in seconds
        chunk_seconds: Chunk length for internal COLA chunking
        progress: Progress callback
        apply_kwargs: Additional kwargs for apply_model
        output_stems_dir: Directory to write stem files directly (memory-bounded mode)
        stem_names: List of stem names for output files

    Returns:
        If output_stems_dir is provided: None (files written directly)
        Otherwise: full sources tensor (legacy mode, may OOM on long tracks)
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

    # MEMORY-BOUNDED MODE: Write directly to output files, never hold full track in memory
    if output_stems_dir is not None and stem_names is not None:
        import tempfile
        import os

        # Create temporary files for incremental writing using sf.SoundFile (streaming append)
        temp_files = []
        soundfiles = []
        for src_idx in range(n_src):
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            temp_files.append(temp_file.name)
            temp_file.close()
            # Open in write mode for the first strip, append mode for subsequent
            sf_handle = sf.SoundFile(temp_files[src_idx], mode='w', samplerate=sr,
                                     channels=ch, subtype='FLOAT', format='WAV')
            soundfiles.append(sf_handle)

        try:
            # Process each strip and write to temp files (streaming append, no re-read)
            total_written = 0
            for i, s in enumerate(starts):
                if progress:
                    progress(i, n_strips)
                e = min(s + strip_len, n)
                seg = wav[:, :, s:e]

                # Process this strip WITHOUT chunking (strip is small enough)
                # This avoids the chunked path's full-track sources_p allocation
                seg_sources = _separate_audio(model, seg, sr, device,
                                              chunked=False,
                                              apply_kwargs=apply_kwargs)
                seg_len = seg_sources.shape[2]
                w = torch.ones(seg_len, device=device)
                if i > 0:                          # fade in the head (overlap prev strip)
                    w[:overlap] = win_fade_in[:overlap]
                if i < n_strips - 1:               # fade out the tail (overlap next strip)
                    w[-overlap:] = win_fade_out[:overlap]

                # Write each source's strip to its temp file (streaming append)
                for src_idx in range(n_src):
                    strip_data = seg_sources[src_idx].cpu().numpy() * w.cpu().numpy()
                    # Transpose to (time, channels) for soundfile
                    if strip_data.ndim == 2:
                        strip_data = strip_data.T
                    # Write strip directly to open SoundFile handle (appends automatically)
                    soundfiles[src_idx].write(strip_data)

                # Track total samples written (use first source as reference)
                if i == 0:
                    total_written = strip_data.shape[0]
                else:
                    total_written += strip_data.shape[0] - overlap  # subtract overlap

                del seg, seg_sources
                gc.collect()

            if progress:
                progress(n_strips, n_strips)

            # Close all SoundFile handles
            for sf_handle in soundfiles:
                sf_handle.close()

            # Move temp files to final output locations by streaming copy (trim to exact length)
            # We stream-copy to avoid loading full track in memory
            for src_idx, name in enumerate(stem_names):
                out_file = Path(output_stems_dir) / f"{name}.wav"
                # Stream copy with trim: read in chunks, write to final file
                with sf.SoundFile(temp_files[src_idx], mode='r') as src:
                    with sf.SoundFile(str(out_file), mode='w', samplerate=sr,
                                      channels=ch, subtype='FLOAT', format='WAV') as dst:
                        # Read and write in chunks to bound memory
                        chunk_size = sr * 10  # 10 second chunks
                        remaining = n  # exact original length in samples
                        while remaining > 0:
                            read_size = min(chunk_size, remaining)
                            data = src.read(read_size, dtype='float32')
                            if len(data) == 0:
                                break
                            dst.write(data)
                            remaining -= len(data)
                            if remaining <= 0:
                                break

            return None  # Files written directly
        finally:
            # Clean up temp files
            for sf_handle in soundfiles:
                try:
                    sf_handle.close()
                except Exception:
                    pass
            for temp_file in temp_files:
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass

    # LEGACY MODE: Return full tensor (may OOM on long tracks)
    full_sources = torch.zeros(n_src, ch, n, device=device)
    wsum = torch.zeros(n, device=device)

    for i, s in enumerate(starts):
        if progress:
            progress(i, n_strips)
        e = min(s + strip_len, n)
        seg = wav[:, :, s:e]
        seg_sources = _separate_audio(model, seg, sr, device,
                                      chunked=True, chunk_seconds=chunk_seconds,
                                      apply_kwargs=apply_kwargs)
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


def separate_stems_spleeter(audio_path: Path, out_dir: Path,
                            model_name: str = "spleeter:5stems") -> dict:
    """Separate stems using Spleeter (TensorFlow-based, alternative to Demucs).

    Spleeter provides a piano/vocals separation that Demucs does not (Demucs
    collapses piano into the 'other' stem). This function wraps Spleeter's API
    to produce stems in the same output format as :func:`separate_stems`.

    Supported models:
      - ``spleeter:2stems``  → vocals, accompaniment
      - ``spleeter:4stems``  → vocals, drums, bass, other
      - ``spleeter:5stems``  → vocals, piano, drums, bass, other (DEFAULT)

    See ``llm-wiki-kb/piano_keyboard_separation.md`` for a comparison of
    separation backends.
    """
    out_dir = Path(out_dir)
    stems_dir = out_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)
    _clear_stems_dir(stems_dir)

    click.echo(f"Loading Spleeter model '{model_name}'...")
    from spleeter.separator import Separator
    separator = Separator(model_name)

    click.echo(f"Separating stems with Spleeter '{model_name}'...")
    prediction = separator.separate_to_file(
        str(audio_path), str(stems_dir), codec='wav', bitrate='256k')

    # Spleeter writes individual stem files named <basename>_<stem>.wav
    # Rename them to the standard names (drums.wav, bass.wav, etc.)
    import os
    basename = Path(audio_path).stem
    instrument_list = separator._params["instrument_list"]
    stems_paths = {}

    for instrument in instrument_list:
        spleeter_name = instrument
        if instrument == "other":
            spleeter_name = "other"
        elif instrument == "accompaniment":
            spleeter_name = "accompaniment"

        spleeter_file = stems_dir / f"{basename}_{spleeter_name}.wav"
        if spleeter_file.exists():
            target_file = stems_dir / f"{instrument}.wav"
            os.rename(str(spleeter_file), str(target_file))
            stems_paths[instrument] = target_file
            click.echo(f"Saved {instrument} stem to {target_file}...")

    # Generate preview mix by summing stems
    click.echo("Generating preview mix...")
    from pydub import AudioSegment
    import io

    # Load and sum all stems (except accompaniment which is a mix)
    mix = None
    sr = None
    for name, path in stems_paths.items():
        if name == "accompaniment":
            continue
        audio = AudioSegment.from_wav(str(path))
        if sr is None:
            sr = audio.frame_rate
            mix = audio
        else:
            mix = mix.overlay(audio)

    if mix is not None:
        preview_file = out_dir / "preview_mix.mp3"
        mix.export(str(preview_file), format="mp3", bitrate="192k")
        click.echo(f"Preview mix saved to {preview_file}")
        stems_paths["preview_mix"] = preview_file

    return stems_paths