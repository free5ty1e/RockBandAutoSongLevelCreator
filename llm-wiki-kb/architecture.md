# AutoRB Knowledge Base - Architecture & Pipeline

The AutoRB pipeline is an end-to-end automation system for converting raw audio and lyrics into playable Xbox 360 CON and PlayStation 4 PKG custom song packages.

## Pipeline Components

1.  **Audio Processing (`autorb.audio`)**:
    *   **Stem Separation**: Uses Meta's **Demucs** to isolate drums, bass, vocals, and instruments (`other`).
    *   **Tempo Detection**: Uses `librosa` to compute a tempo map (`tempo_map.json`).
    *   **Vocal Extraction**: Uses **WhisperX** for speech-to-text and alignment.
2.  **Transcription (`autorb.transcribe`)**:
    *   Converts pitch and transient audio into quantized MIDI (`.mid`) charts using signal processing and machine learning models.
3.  **Export & Packaging (`autorb.export`)**:
    *   **Asset Generation**: Generates `songs.dta` metadata, default album art (`_keep.png_xbox`), and milo assets.
    *   **CON Packaging**: Builds a fully compliant Xbox 360 STFS CON container using a verified template.
    *   **PS4 Packaging**: Leverages the vendored `ForgeTool` to convert the CON into a playable `.pkg` installer for PS4.
4.  **Tooling Integration**:
    *   The `ForgeTool` is built from vendored source within the `tools/libforge/` directory using .NET SDK 8 and Mono, ensuring full reproducibility within the development container.
    *   Pipeline supports automatic PKG generation via the `--build-pkg` flag.
