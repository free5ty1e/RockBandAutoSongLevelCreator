"""Open a folder in the OS file manager (the "Show in Explorer" button).

Cross-platform:
  * Windows: os.startfile (opens Explorer on the folder)
  * macOS:   `open <folder>` (Finder)
  * Linux:   `xdg-open` / `gio open` / DE-specific openers

Returns (ok, message) so the API layer can report what happened. Never
raises. ``ok`` is True ONLY when a window plausibly opened — a headless
server (the devcontainer: no DISPLAY, no desktop) or an opener that exits
nonzero must NOT be reported as success, or the UI silently shows nothing
(the v0.1.28 "button does nothing" report: bare `gio` printed usage; even
`gio open` fails with no desktop file associations but exits 0, which a
check=False run swallowed as success).

Callers should pair a False result with the path so the user can still
copy it into their own file manager.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _has_gui_session() -> bool:
    """True if a graphical session plausibly exists on this machine.

    Linux only: DISPLAY or WAYLAND_DISPLAY must be set. A server/container
    without them has no desktop for a file manager to open on — reporting
    success there is a lie the UI renders as "button does nothing".
    """
    import os
    if sys.platform == "win32" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def reveal_in_file_manager(path: str | Path) -> tuple[bool, str]:
    """Open ``path`` (folder preferred) in the OS file manager.

    Returns ``(ok, message)``. ``ok`` False means no window opened — the
    message explains why and names the path so the UI can offer a copy.
    """
    path = Path(path)
    if not path.exists():
        return False, f"Path does not exist: {path}"

    target = str(path if path.is_dir() else path.parent)

    # Headless (container/server): no desktop to open a window on. Be honest
    # so the UI shows the copyable path instead of silently doing nothing.
    if not _has_gui_session():
        return False, (
            "This machine has no graphical session (running in a "
            "container/server), so no file manager window can open here. "
            f"Copy this path into your file manager: {target}")

    try:
        if sys.platform == "win32":
            os_startfile(target)
            return True, f"Opened in Explorer: {target}"
        if sys.platform == "darwin":
            r = subprocess.run(["open", target], capture_output=True,
                               text=True, timeout=10)
            if r.returncode != 0:
                return False, (f"`open` failed (rc={r.returncode}): "
                               f"{r.stderr.strip() or '?'} — path: {target}")
            return True, f"Opened in Finder: {target}"
        # Linux: xdg-open, then gio open, then DE-specific launchers.
        # Each opener is checked for a NONZERO exit or error output —
        # gio famously exits 0 while printing "Failed to find default
        # application" when no desktop is installed, which a check=False
        # call would swallow as success.
        for argv in (("xdg-open", target), ("gio", "open", target),
                     ("nautilus", target), ("dolphin", target)):
            exe = shutil.which(argv[0])
            if not exe:
                continue
            r = subprocess.run(list(argv), capture_output=True, text=True,
                               timeout=10)
            err = (r.stderr or "").strip()
            if r.returncode == 0 and not err:
                return True, f"Opened with {' '.join(argv[:-1])}: {target}"
            # opener present but failed — try the next one
            continue
        return False, (
            "No file manager on this machine could open the folder "
            f"(tried xdg-open/gio/nautilus/dolphin). Path: {target}")
    except Exception as e:  # never fail the API over a UX nicety
        return False, f"Could not open file manager: {e} (folder: {target})"


def os_startfile(target: str) -> None:  # pragma: no cover - Windows only
    """Thin indirection so tests can monkeypatch; real impl uses os.startfile."""
    import os
    os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
