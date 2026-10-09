"""Open a folder in the OS file manager (the "Show in Explorer" button).

Cross-platform:
  * Windows: os.startfile (opens Explorer on the folder)
  * macOS:   `open <folder>` (Finder)
  * Linux:   `xdg-open <folder>` (GNOME Files, KDE Dolphin, ...)

Returns (ok, message) so the API layer can report what happened without
crashing the job (a headless Linux server may have no file manager at all —
that's a UX nit, not a failure of the build).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def reveal_in_file_manager(path: str | Path) -> tuple[bool, str]:
    """Open ``path`` (folder preferred) in the OS file manager.

    Returns ``(ok, message)``. Never raises.
    """
    path = Path(path)
    if not path.exists():
        return False, f"Path does not exist: {path}"

    target = str(path if path.is_dir() else path.parent)

    try:
        if sys.platform == "win32":
            # os.startfile is Windows-only and opens Explorer at the folder.
            os_startfile(target)  # noqa: F821 — resolved below
            return True, f"Opened in Explorer: {target}"
        if sys.platform == "darwin":
            subprocess.run(["open", target], check=False, timeout=10)
            return True, f"Opened in Finder: {target}"
        # Linux / everything else: xdg-open; fall back to known DE openers.
        for opener in ("xdg-open", "gio", "nautilus", "dolphin"):
            if shutil.which(opener):
                subprocess.run([opener, target], check=False, timeout=10)
                return True, f"Opened with {opener}: {target}"
        return False, ("No file manager found (xdg-open/gio/nautilus/dolphin). "
                       "The job folder is at: " + target)
    except Exception as e:  # never fail the API over a UX nicety
        return False, f"Could not open file manager: {e} (folder: {target})"


def os_startfile(target: str) -> None:  # pragma: no cover - Windows only
    """Thin indirection so tests can monkeypatch; real impl uses os.startfile."""
    import os
    os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
