#!/usr/bin/env python
# encoding: utf-8
#
# Vendored subset of Spotify's "basic-pitch" (Apache License 2.0).
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
#
# This package bundles the Basic Pitch ICASSP 2022 model (nmp.onnx) and the
# minimal pure-Python inference/post-processing routines needed to transcribe
# audio into MIDI. It deliberately runs through ONNX Runtime only (no
# TensorFlow), which lets autorb install on platforms that have no
# tensorflow-macos wheels (e.g. macOS arm64 + Python 3.12).
#
# Original project: https://github.com/spotify/basic-pitch

import pathlib

ICASSP_2022_MODEL_PATH = pathlib.Path(__file__).parent / "nmp.onnx"
