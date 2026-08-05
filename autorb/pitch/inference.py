#!/usr/bin/env python
# encoding: utf-8
#
# Copyright 2022 Spotify AB
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import enum
import json
import logging
import os
import pathlib
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import numpy as np
import numpy.typing as npt
import librosa
import pretty_midi

try:
    import onnxruntime as ort
except ImportError:
    ort = None

from autorb.pitch.constants import (
    AUDIO_SAMPLE_RATE,
    AUDIO_N_SAMPLES,
    ANNOTATIONS_FPS,
    FFT_HOP,
)
from autorb.pitch.commandline_printing import no_tf_warnings
from autorb.pitch import note_creation as infer
from autorb.pitch import ICASSP_2022_MODEL_PATH

ONNX_PRESENT = ort is not None


class Model:
    class MODEL_TYPES(enum.Enum):
        ONNX = enum.auto()

    def __init__(self, model_path: Union[pathlib.Path, str]):
        if not ONNX_PRESENT:
            raise ValueError(
                "The Basic Pitch ONNX model requires onnxruntime to be installed. "
                "Please install onnxruntime (e.g. `pip install onnxruntime`)."
            )
        self.model_type = Model.MODEL_TYPES.ONNX
        self.model = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])

    def predict(self, x: npt.NDArray[np.float32]) -> Dict[str, npt.NDArray[np.float32]]:
        return {
            k: v
            for k, v in zip(
                ["note", "onset", "contour"],
                self.model.run(
                    [
                        "StatefulPartitionedCall:1",
                        "StatefulPartitionedCall:2",
                        "StatefulPartitionedCall:0",
                    ],
                    {"serving_default_input_2:0": x},
                ),
            )
        }


def window_audio_file(
    audio_original: npt.NDArray[np.float32], hop_size: int
) -> Iterable[Tuple[npt.NDArray[np.float32], Dict[str, float]]]:
    """
    Pad appropriately an audio file, and return as
    windowed signal, with window length = AUDIO_N_SAMPLES

    Returns:
        audio_windowed: tensor with shape (n_windows, AUDIO_N_SAMPLES, 1)
            audio windowed into fixed length chunks
        window_times: list of {'start':.., 'end':...} objects (times in seconds)

    """
    for i in range(0, audio_original.shape[0], hop_size):
        window = audio_original[i : i + AUDIO_N_SAMPLES]
        if len(window) < AUDIO_N_SAMPLES:
            window = np.pad(
                window,
                pad_width=[[0, AUDIO_N_SAMPLES - len(window)]],
            )
        t_start = float(i) / AUDIO_SAMPLE_RATE
        window_time = {
            "start": t_start,
            "end": t_start + (AUDIO_N_SAMPLES / AUDIO_SAMPLE_RATE),
        }
        yield np.expand_dims(window, axis=-1), window_time


def get_audio_input(
    audio_path: Union[pathlib.Path, str], overlap_len: int, hop_size: int
) -> Iterable[Tuple[npt.NDArray[np.float32], Dict[str, float], int]]:
    """
    Read wave file (as mono), pad appropriately, and return as
    windowed signal, with window length = AUDIO_N_SAMPLES

    Returns:
        audio_windowed: tensor with shape (n_windows, AUDIO_N_SAMPLES, 1)
            audio windowed into fixed length chunks
        window_times: list of {'start':.., 'end':...} objects (times in seconds)
        audio_original_length: int
            length of original audio file, in frames, BEFORE padding.

    """
    assert overlap_len % 2 == 0, f"overlap_length must be even, got {overlap_len}"

    audio_original, _ = librosa.load(str(audio_path), sr=AUDIO_SAMPLE_RATE, mono=True)

    original_length = audio_original.shape[0]
    audio_original = np.concatenate([np.zeros((int(overlap_len / 2),), dtype=np.float32), audio_original])
    for window, window_time in window_audio_file(audio_original, hop_size):
        yield np.expand_dims(window, axis=0), window_time, original_length


def unwrap_output(
    output: npt.NDArray[np.float32],
    audio_original_length: int,
    n_overlapping_frames: int,
) -> np.array:
    """Unwrap batched model predictions to a single matrix.

    Args:
        output: array (n_batches, n_times_short, n_freqs)
        audio_original_length: length of original audio signal (in samples)
        n_overlapping_frames: number of overlapping frames in the output

    Returns:
        array (n_times, n_freqs)
    """
    if len(output.shape) != 3:
        return None

    n_olap = int(0.5 * n_overlapping_frames)
    if n_olap > 0:
        # remove half of the overlapping frames from beginning and end
        output = output[:, n_olap:-n_olap, :]

    output_shape = output.shape
    n_output_frames_original = int(np.floor(audio_original_length * (ANNOTATIONS_FPS / AUDIO_SAMPLE_RATE)))
    unwrapped_output = output.reshape(output_shape[0] * output_shape[1], output_shape[2])
    return unwrapped_output[:n_output_frames_original, :]  # trim to original audio length


def run_inference(
    audio_path: Union[pathlib.Path, str],
    model_or_model_path: Union[Model, pathlib.Path, str],
    debug_file: Optional[pathlib.Path] = None,
) -> Dict[str, np.array]:
    """Run the model on the input audio path.

    Args:
        audio_path: The audio to run inference on.
        model_or_model_path: A loaded Model or path to a serialized model to load.
        debug_file: An optional path to output debug data to. Useful for testing/verification.

    Returns:
       A dictionary with the notes, onsets and contours from model inference.
    """
    if isinstance(model_or_model_path, Model):
        model = model_or_model_path
    else:
        model = Model(model_or_model_path)

    # overlap 30 frames
    n_overlapping_frames = 30
    overlap_len = n_overlapping_frames * FFT_HOP
    hop_size = AUDIO_N_SAMPLES - overlap_len

    output: Dict[str, Any] = {"note": [], "onset": [], "contour": []}
    for audio_windowed, _, audio_original_length in get_audio_input(audio_path, overlap_len, hop_size):
        for k, v in model.predict(audio_windowed).items():
            output[k].append(v)

    unwrapped_output = {
        k: unwrap_output(np.concatenate(output[k]), audio_original_length, n_overlapping_frames) for k in output
    }

    if debug_file:
        with open(debug_file, "w") as f:
            json.dump(
                {
                    "audio_original_length": audio_original_length,
                    "hop_size_samples": hop_size,
                    "overlap_length_samples": overlap_len,
                    "unwrapped_output": {k: v.tolist() for k, v in unwrapped_output.items()},
                },
                f,
            )

    return unwrapped_output


def predict(
    audio_path: Union[pathlib.Path, str],
    model_or_model_path: Union[Model, pathlib.Path, str] = ICASSP_2022_MODEL_PATH,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    minimum_note_length: float = 127.70,
    minimum_frequency: Optional[float] = None,
    maximum_frequency: Optional[float] = None,
    multiple_pitch_bends: bool = False,
    melodia_trick: bool = True,
    debug_file: Optional[pathlib.Path] = None,
    midi_tempo: float = 120,
) -> Tuple[
    Dict[str, np.array],
    pretty_midi.PrettyMIDI,
    List[Tuple[float, float, int, float, Optional[List[int]]]],
]:
    """Run a single prediction.

    Args:
        audio_path: File path for the audio to run inference on.
        model_or_model_path: A loaded Model or path to a serialized model to load.
        onset_threshold: Minimum energy required for an onset to be considered present.
        frame_threshold: Minimum energy requirement for a frame to be considered present.
        minimum_note_length: The minimum allowed note length in milliseconds.
        minimum_freq: Minimum allowed output frequency, in Hz. If None, all frequencies are used.
        maximum_freq: Maximum allowed output frequency, in Hz. If None, all frequencies are used.
        multiple_pitch_bends: If True, allow overlapping notes in midi file to have pitch bends.
        melodia_trick: Use the melodia post-processing step.
        debug_file: An optional path to output debug data to. Useful for testing/verification.
    Returns:
        The model output, midi data and note events from a single prediction
    """

    with no_tf_warnings():
        model_output = run_inference(audio_path, model_or_model_path, debug_file)
        min_note_len = int(np.round(minimum_note_length / 1000 * (AUDIO_SAMPLE_RATE / FFT_HOP)))
        midi_data, note_events = infer.model_output_to_notes(
            model_output,
            onset_thresh=onset_threshold,
            frame_thresh=frame_threshold,
            min_note_len=min_note_len,  # convert to frames
            min_freq=minimum_frequency,
            max_freq=maximum_frequency,
            multiple_pitch_bends=multiple_pitch_bends,
            melodia_trick=melodia_trick,
            midi_tempo=midi_tempo,
        )

    if debug_file:
        with open(debug_file) as f:
            debug_data = json.load(f)
        with open(debug_file, "w") as f:
            json.dump(
                {
                    **debug_data,
                    "min_note_length": min_note_len,
                    "onset_thresh": onset_threshold,
                    "frame_thresh": frame_threshold,
                    "estimated_notes": [
                        (
                            float(start_time),
                            float(end_time),
                            int(pitch),
                            float(amplitude),
                            [int(b) for b in pitch_bends] if pitch_bends else None,
                        )
                        for start_time, end_time, pitch, amplitude, pitch_bends in note_events
                    ],
                },
                f,
            )

    return model_output, midi_data, note_events
