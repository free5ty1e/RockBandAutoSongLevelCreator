"""Batch store: stage songs once, re-run the same batch over and over.

The user's workflow (verbatim intent): package several test songs (Open Road
Song, Brian Wilson, future additions) into ONE multi-song CON and ONE PS4
PKG, re-deploying repeatedly while iterating on the charting algorithms —
so a batch must be SAVABLE to a JSON file and RELOADABLE later with all
files and metadata ready to go.

Layout under the jobs root:
    batch_store/<song_id>/uploads/...        staged files (durable)
    batch_store/batches/<slug>.json         saved batch definitions

The JSON references staged files by path relative to the jobs root, so a
batch survives browser reloads and machine reboots (as long as the jobs
root is kept). Loading validates every referenced file still exists.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from .jobs import JobError

BATCH_FORMAT = "autorb-batch/1"


class BatchStore:
    def __init__(self, jobs_root: Path):
        self.jobs_root = Path(jobs_root)
        self.store_root = self.jobs_root / "batch_store"
        self.batches_dir = self.store_root / "batches"
        self.store_root.mkdir(parents=True, exist_ok=True)
        self.batches_dir.mkdir(parents=True, exist_ok=True)

    # ---- staging ----
    def new_song_dir(self) -> Path:
        song_id = uuid.uuid4().hex[:8]
        d = self.store_root / song_id / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d.parent

    def song_record(self, song_id: str, options: dict,
                    files: dict[str, str]) -> dict:
        """Serialize one staged song; file paths relative to jobs root."""
        rel_files = {}
        for role, p in files.items():
            if p:
                rp = Path(p).resolve().relative_to(self.jobs_root.resolve())
                rel_files[role] = rp.as_posix()
            else:
                rel_files[role] = None
        return {"song_id": song_id, "options": options, "files": rel_files}

    # ---- save / load ----
    def _slug(self, name: str) -> str:
        s = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip()).strip("_")
        return (s or "batch")[:60]

    def save(self, name: str, songs: list[dict],
             ps4_pkg_id: str | None = None) -> Path:
        """Validate songs + write the batch JSON. Returns its path."""
        if not name or not str(name).strip():
            raise JobError("Batch name is required")
        if not songs:
            raise JobError("Batch has no songs")
        seen = set()
        for s in songs:
            sid = s.get("song_id")
            if not sid:
                raise JobError("batch song missing song_id")
            if sid in seen:
                raise JobError(f"duplicate song_id in batch: {sid}")
            seen.add(sid)
            self.resolve_song_files(s)  # raises if files vanished
        doc = {
            "format": BATCH_FORMAT,
            "name": str(name).strip(),
            "ps4_pkg_id": ps4_pkg_id or None,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "songs": songs,
        }
        path = self.batches_dir / f"{self._slug(str(name))}.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return path

    def resolve_song_files(self, song: dict) -> dict[str, Path | None]:
        """Resolve a song record's files to absolute paths, verifying each
        exists. Raises JobError naming the missing file otherwise."""
        files: dict[str, Path | None] = {}
        for role, rel in (song.get("files") or {}).items():
            if not rel:
                files[role] = None
                continue
            p = (self.jobs_root / rel).resolve()
            if not p.exists():
                raise JobError(
                    f"batch song '{song.get('song_id')}' is missing its "
                    f"{role} file ({rel}) — stage the files again or pick a "
                    f"batch whose files are still present")
            if not str(p).startswith(str(self.jobs_root.resolve())):
                raise JobError(f"{role} path escapes the jobs root: {rel}")
            files[role] = p
        if not (files.get("audio") or files.get("stems")):
            raise JobError(
                f"batch song '{song.get('song_id')}' has neither audio nor "
                f"stems staged")
        return files

    def load(self, json_path: Path) -> dict:
        """Load + validate a batch JSON (server-side path or uploaded)."""
        try:
            doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise JobError(f"could not read batch file: {e}")
        if doc.get("format") != BATCH_FORMAT:
            raise JobError(
                f"not an AutoRB batch file (format={doc.get('format')!r}, "
                f"expected {BATCH_FORMAT!r})")
        if not isinstance(doc.get("songs"), list) or not doc["songs"]:
            raise JobError("batch file contains no songs")
        for s in doc["songs"]:
            self.resolve_song_files(s)
        return doc

    def list_saved(self) -> list[dict]:
        out = []
        for p in sorted(self.batches_dir.glob("*.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                out.append({
                    "name": doc.get("name", p.stem),
                    "file": p.name,
                    "songs": len(doc.get("songs", [])),
                    "created": doc.get("created"),
                    "path": str(p),
                })
            except Exception:
                continue
        return out
