#!/usr/bin/env python
"""Preview AutoRB stems without needing PS4.

Quickly inspect the pipeline's audio artifacts:

    python -m autorb.audio.preview mix          # Sum all stems -> preview_mix.wav
    python -m autorb.audio.preview --list       # List the available stems
    python -m autorb.audio.preview vocals       # Print path to the vocals stem
    python -m autorb.audio.preview drums        # Print path to the drums stem

Individual stems can be opened/played directly by any audio player (their
files are normal WAVs). ``mix`` produces a summed stereo WAV of all four stems
for a full-band preview; pair it with ``lyrics_preview.srt`` (written by the
pipeline) in VLC/MPV for a rewindable lyric-sync review.
"""

import argparse
import sys
from pathlib import Path

from autorb.audio.mix_preview import mix_stems

STEM_NAMES = ["drums.wav", "bass.wav", "vocals.wav", "other.wav"]
TRACK_ALIASES = {
    "drums": "drums.wav",
    "bass": "bass.wav",
    "vocals": "vocals.wav",
    "other": "other.wav",
}


def _find_stems_dir(output_dir: Path) -> Path:
    candidates = [
        output_dir / "stems",
        Path(output_dir),
    ]
    for c in candidates:
        if (c / "drums.wav").exists():
            return c
    return output_dir / "stems"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Preview AutoRB stems")
    parser.add_argument("command", nargs="?", default="mix",
                        choices=["mix", "--list"] + list(TRACK_ALIASES),
                        help="What to preview (default: mix = sum all stems)")
    parser.add_argument("--output-dir", type=Path, default=Path("./output"),
                        help="Output directory (default: ./output)")
    parser.add_argument("--list", action="store_true", help="List available stems")
    args = parser.parse_args(argv)

    stems_dir = _find_stems_dir(args.output_dir)
    if args.list or args.command == "--list":
        print(f"Stems directory: {stems_dir}")
        found = 0
        for name in STEM_NAMES:
            p = stems_dir / name
            mark = "OK" if p.exists() else "missing"
            if p.exists():
                found += 1
            print(f"  {name:12s} [{mark}] {p}")
        print(f"\n{found}/{len(STEM_NAMES)} stems present. "
              "Individual stems can be opened directly in any audio player.")
        return 0

    if not stems_dir.exists():
        print(f"Error: stems directory not found: {stems_dir}. Run the pipeline first.",
              file=sys.stderr)
        return 1

    if args.command in TRACK_ALIASES:
        p = stems_dir / TRACK_ALIASES[args.command]
        if not p.exists():
            print(f"Error: stem not found: {p}", file=sys.stderr)
            return 1
        print(p)
        print(f"Open it in any audio player to review the {args.command} stem.")
        return 0

    # Default: sum all stems into preview_mix.wav
    out = args.output_dir / "preview_mix.wav"
    mix_stems(stems_dir, out)
    print(f"\nPair it with lyrics_preview.srt (pipeline output) in VLC/MPV "
          f"(Tools -> Subtitles -> Add) for a rewindable lyric-sync review.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
