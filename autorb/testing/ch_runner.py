"""autorb.testing — headless Clone Hero playtesting harness.

See .ai_memory/plans/clone_hero_devcontainer_playtesting.md. This package is the
devcontainer-only loop for load-testing AutoRB's Clone Hero exports against a real
Clone Hero instance (the parser/renderer the user actually plays against).

It is NOT part of the default `pytest`/CI run (GitHub Actions has no X11/audio
stack). Mark related tests with `@pytest.mark.devcontainer`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# repo root = parents[2] of this file (autorb/testing/<this>)
REPO_ROOT = Path(__file__).resolve().parents[2]
HEADLESS_SH = REPO_ROOT / "tools" / "clone_hero_headless.sh"


def run_load_gate(
    song_folder: str | Path,
    wait: int = 20,
    variance_threshold: float = 8.0,
    shot: str | Path | None = None,
) -> dict:
    """Phase 1 loadability gate.

    Launches Clone Hero headless on ``song_folder``, captures one frame, and
    checks the song was accepted (not listed in badsongs.txt) and actually
    rendered (frame variance above threshold). Returns a result dict.

    A deliberately broken export (e.g. fractional-BPM ``.chart``) should be
    caught here by a badsongs.txt entry and/or a black/error frame.
    """
    import shutil

    import numpy as np
    from PIL import Image

    song_folder = Path(song_folder).resolve()
    if not song_folder.is_dir():
        raise FileNotFoundError(f"song folder not found: {song_folder}")

    shot = Path(shot) if shot else (Path("/tmp") / "ch_load_gate.png")
    shot = shot.resolve()

    if not HEADLESS_SH.exists():
        raise RuntimeError(f"headless launcher missing: {HEADLESS_SH}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required for frame capture")

    cmd = [
        "bash", str(HEADLESS_SH),
        "--song", str(song_folder),
        "--shot", str(shot),
        "--wait", str(wait),
        "--player", "Guitar,Expert",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {
            "song": str(song_folder),
            "launched": False,
            "passed": False,
            "error": f"launcher exited {proc.returncode}",
            "stderr": proc.stderr[-2000:],
        }

    rendered = False
    variance = None
    if shot.exists():
        with Image.open(shot) as im:
            arr = np.asarray(im.convert("L")).astype("float32")
        variance = float(arr.std())
        rendered = variance >= variance_threshold

    rejected, badsongs_entries = check_badsongs(song_folder)

    passed = (not rejected) and rendered
    return {
        "song": str(song_folder),
        "launched": True,
        "frame_captured": shot.exists(),
        "frame_variance": variance,
        "rendered": rendered,
        "rejected": rejected,
        "badsongs_entries": badsongs_entries,
        "passed": passed,
    }


def check_badsongs(song_folder: str | Path) -> tuple[bool, list[str]]:
    """Return (rejected, entries) where ``rejected`` is True if ``song_folder``
    appears in any badsongs.txt CH wrote during load/scan."""
    song_folder = Path(song_folder).resolve()
    name = song_folder.name

    candidates: list[Path] = []
    # CH writes badsongs.txt next to the song folders (the Songs root = parent).
    parent = song_folder.parent
    candidates.append(parent / "badsongs.txt")
    # Also scan CH data dirs (varies by build).
    for base in (Path.home(), Path("/root")):
        candidates.append(base / ".config" / "unity3d" / "srylain Inc_" / "Clone Hero" / "badsongs.txt")
        candidates.append(base / ".clonehero" / "badsongs.txt")

    entries: list[str] = []
    for f in candidates:
        if not f.exists():
            continue
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line_s = line.strip()
            if not line_s:
                continue
            entries.append(line_s)
            if name in line_s or str(song_folder) in line_s:
                return True, entries
    return False, entries
