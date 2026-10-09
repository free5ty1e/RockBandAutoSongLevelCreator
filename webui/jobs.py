"""Job store + pipeline runner for the AutoRB web UI.

One job = one song through the real AutoRB CLI (`python -m autorb.cli`), run
as a subprocess with unbuffered stdout/stderr so the UI can stream the log and
estimate progress (webui/progress.py parses the CLI's own stage markers).

Design constraints from the pipeline itself:
  * ONE job runs at a time (Demucs + WhisperX + ADTOF need ~all of 8 GB RAM);
    further jobs queue. The executor below is a single-worker queue.
  * Uploads land in <jobs_root>/<job_id>/uploads/; outputs in
    <jobs_root>/<job_id>/output/. Nothing ever leaves the user's machine.
  * The CLI is run with cwd = repo root so packaged relative paths resolve.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import progress as progress_mod

# Upload limits (defensive; a local tool, but a stray click shouldn't post a
# 2 GB "audio" file into an 8 GB box).
MAX_AUDIO_BYTES = 600 * 1024 * 1024        # 600 MB
MAX_STEM_BYTES = 600 * 1024 * 1024        # per stem
MAX_ART_BYTES = 20 * 1024 * 1024          # 20 MB
MAX_LRC_BYTES = 1024 * 1024               # 1 MB

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
LRC_EXTS = {".lrc", ".txt"}
ART_EXTS = {".png", ".jpg", ".jpeg"}
STEM_NAMES = {"drums", "bass", "other", "vocals", "guitar", "piano"}
SEPARATORS = ["htdemucs_ft", "htdemucs", "htdemucs_6s", "spleeter:5stems"]

LOG_TAIL_LINES = 400

# draft = uploaded files, not yet started (options not validated/attached)
VALID_STATUSES = {"draft", "queued", "running", "success", "failed", "cancelled"}


class JobError(Exception):
    """Validation or state error the UI should show as a form error."""


class Job:
    """One charting job: parameters, uploaded files, and runtime state."""

    def __init__(self, job_id: str, jobs_root: Path):
        self.id = job_id
        self.dir = Path(jobs_root) / job_id
        self.uploads_dir = self.dir / "uploads"
        self.output_dir = self.dir / "output"
        self.log_path = self.dir / "job.log"
        self.lock = threading.Lock()
        self.status = "draft"   # draft|queued|running|success|failed|cancelled
        self.stage = "Queued"
        self.progress = 0.0
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.exit_code: int | None = None
        self.error: str | None = None
        self.proc: subprocess.Popen | None = None
        self.uploads: dict[str, str] = {}   # role -> absolute path
        self.options: dict = {}
        self.log_lines: list[str] = []
        # Batch mode: list of per-song dicts {label, options, files} that the
        # worker runs sequentially, then packages all CONs into one multi-song
        # CON + one PS4 PKG. None for normal single-song jobs.
        self.batch_songs: list[dict] | None = None
        self.batch_name: str | None = None
        self.ps4_pkg_id: str | None = None
        # Progress is rescaled in batch mode: songs occupy [0, 0.9] equally,
        # packaging [0.9, 1.0]. Each song's stage markers are tracked on
        # their OWN 0..1 scale (a marker like "[2/5]"=0.30 must register for
        # song 2 even though the GLOBAL bar already sits at 0.45).
        self._batch_total: int = 0
        self._song_progress: float = 0.0

    # ---- serialization ----
    def to_dict(self, include_log: bool = True) -> dict:
        with self.lock:
            d = {
                "id": self.id,
                "status": self.status,
                "stage": self.stage,
                "progress": round(self.progress, 4),
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "exit_code": self.exit_code,
                "error": self.error,
                "uploads": {k: v for k, v in self.uploads.items()},
                "options": dict(self.options),
                "dir": str(self.dir),
                "output_dir": str(self.output_dir),
            }
            if include_log:
                d["log_tail"] = list(self.log_lines[-LOG_TAIL_LINES:])
            return d

    # ---- runtime helpers (called from the worker thread) ----
    def set_running(self) -> None:
        with self.lock:
            self.status = "running"
            self.started_at = time.time()
            self.stage = "Starting"

    def set_status(self, status: str, error: str | None = None) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        with self.lock:
            self.status = status
            if error is not None:
                self.error = error
            if status in ("success", "failed", "cancelled"):
                self.finished_at = time.time()
                if status == "success":
                    self.progress = 1.0
                    self.stage = "Done"
                elif status == "cancelled":
                    self.stage = "Cancelled"
                else:
                    self.stage = "Failed"

    def ingest_line(self, line: str) -> None:
        """Fold one CLI log line into progress + log tail (worker thread)."""
        new = progress_mod.next_progress(line, self.progress)
        with self.lock:
            if new is not None:
                self.progress = new
            self.log_lines.append(line)
            self.stage = progress_mod.stage_label(self.progress)

    # ---- batch progress scaling ----
    def begin_batch(self, name: str, songs: list[dict],
                    ps4_pkg_id: str | None) -> None:
        self.batch_name = name
        self.batch_songs = songs
        self.ps4_pkg_id = ps4_pkg_id
        self._batch_total = len(songs)

    def batch_ingest(self, song_index: int, line: str) -> None:
        """ingest_line for one batch song, rescaled to its bar slice.

        The song's markers are parsed on their OWN 0..1 scale (tracked in
        _song_progress) and mapped into [0.9*i/n, 0.9*(i+1)/n) of the
        global bar — so song 2's early stages register even though the
        global bar starts the song at ~0.45."""
        with self.lock:
            new = progress_mod.next_progress(line, self._song_progress)
            if new is not None:
                self._song_progress = new
            self.log_lines.append(line)
            lo = 0.9 * song_index / max(1, self._batch_total)
            hi = 0.9 * (song_index + 1) / max(1, self._batch_total)
            if new is not None:
                self.progress = lo + (hi - lo) * new
            label = (self.batch_songs[song_index].get("label")
                     if self.batch_songs else None) or f"song {song_index+1}"
            self.stage = f"[{label}] " + progress_mod.stage_label(
                self._song_progress)

    def batch_ingest_packaging(self, line: str) -> None:
        """ingest for the final --package-con-dir run (0.9 -> 1.0)."""
        new = progress_mod.next_progress(line, self.progress)
        with self.lock:
            self.log_lines.append(line)
            if new is not None:
                self.progress = 0.9 + 0.1 * new
            self.stage = f"[packaging] " + progress_mod.stage_label(self.progress)


def build_cli_command(job: Job, repo_root: Path) -> list[str]:
    """Build the `python -m autorb.cli ...` argument list for a job.

    Mirrors the CLI's option surface 1:1 (see autorb/cli.py); unknown options
    are rejected so the UI can't smuggle in arbitrary flags.
    """
    opts = job.options
    args = [
        "python", "-m", "autorb.cli",
    ]

    # ---- positional: audio file (omitted entirely for stems-only jobs;
    #      the CLI accepts that with --skip-separation and skips the
    #      mixed-audio drum fallback) ----
    audio = job.uploads.get("audio")
    use_stems = bool(job.uploads.get("stems"))
    if use_stems:
        if audio:
            # Original mix was provided too — pass it so drums can use the
            # best fallback source.
            args.append(str(Path(audio).resolve()))
        # else: no positional at all (stems-only workflow)
    elif audio:
        args.append(str(Path(audio).resolve()))
    else:
        raise JobError("No audio file or stems provided")

    # ---- metadata ----
    artist = str(opts.get("artist") or "").strip()
    title = str(opts.get("title") or "").strip()
    if not artist:
        raise JobError("Artist is required")
    if not title:
        raise JobError("Title is required")
    args += ["--artist", artist, "--title", title]
    if opts.get("year"):
        args += ["--year", str(int(opts["year"]))]
    if opts.get("genre"):
        args += ["--genre", str(opts["genre"])]

    # ---- files ----
    if job.uploads.get("lrc"):
        args += ["--lyrics", str(Path(job.uploads["lrc"]).resolve())]
    if job.uploads.get("album_art"):
        args += ["--album-art", str(Path(job.uploads["album_art"]).resolve())]

    # ---- separation ----
    if use_stems:
        args.append("--skip-separation")
    else:
        separator = str(opts.get("separator") or "htdemucs_ft")
        if separator not in SEPARATORS:
            raise JobError(f"Unknown separator: {separator}")
        args += ["--separator", separator]
        if opts.get("ft_shifts") is not None:
            args += ["--ft-shifts", str(int(opts["ft_shifts"]))]
        if opts.get("ft_strip_seconds") is not None:
            args += ["--ft-strip-seconds", str(float(opts["ft_strip_seconds"]))]
        if opts.get("ft_segment") not in (None, ""):
            args += ["--ft-segment", str(float(opts["ft_segment"]))]
        if opts.get("ft_overlap") is not None:
            args += ["--ft-overlap", str(float(opts["ft_overlap"]))]

    # ---- outputs ----
    args += ["--output-dir", str(job.output_dir.resolve())]

    # ---- toggles ----
    if opts.get("build_pkg"):
        args.append("--build-pkg")
    if opts.get("build_clone_hero"):
        args.append("--build-clone-hero")
    if opts.get("generate_freestyle_vocals"):
        args.append("--generate-freestyle-vocals")
    if opts.get("freestyle_drums"):
        args.append("--freestyle-drums")
    if opts.get("guitar_solo_charting"):
        args.append("--guitar-solo-charting")

    return args


class JobStore:
    """Thread-safe registry of jobs + the single background worker."""

    def __init__(self, jobs_root: Path, repo_root: Path | None = None):
        self.jobs_root = Path(jobs_root)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.repo_root = Path(repo_root) if repo_root else \
            Path(__file__).resolve().parents[1]
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._worker: threading.Thread | None = None
        # Test seam: when set, called instead of the real subprocess run.
        self.run_hook = None

    # ---- public API (called from FastAPI handlers) ----
    def create_draft(self) -> Job:
        """Register a job whose files are being uploaded (no options yet)."""
        job_id = uuid.uuid4().hex[:8]
        job = Job(job_id, self.jobs_root)
        job.uploads_dir.mkdir(parents=True, exist_ok=True)
        job.output_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def start_batch(self, job: Job) -> None:
        """Queue a batch job (per-song commands are validated during run)."""
        with job.lock:
            if job.status != "draft":
                raise JobError(f"Job already {job.status}")
            job.status = "queued"
            job.stage = "Queued (batch)"
        with self._lock:
            self._queue.append(job.id)
        self._ensure_worker()

    def start(self, job: Job, options: dict) -> None:
        """Attach validated options and queue the job for the worker.

        The CLI command is built EAGERLY here so a bad combination (no
        audio/stems, missing artist/title, unknown separator) raises
        JobError to the API caller as a 400 — instead of failing silently
        in the worker minutes later.
        """
        job.options = dict(options)
        build_cli_command(job, self.repo_root)  # raises JobError on bad input
        with job.lock:
            if job.status != "draft":
                raise JobError(f"Job already {job.status}")
            job.status = "queued"
            job.stage = "Queued"
        with self._lock:
            self._queue.append(job.id)
        self._ensure_worker()

    def create(self, options: dict, uploads: dict) -> Job:
        job_id = uuid.uuid4().hex[:8]
        job = Job(job_id, self.jobs_root)
        job.uploads_dir.mkdir(parents=True, exist_ok=True)
        job.output_dir.mkdir(parents=True, exist_ok=True)
        job.options = dict(options)
        job.uploads = dict(uploads)
        with self._lock:
            self._jobs[job_id] = job
            self._queue.append(job_id)
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [j.to_dict(include_log=False) for j in
                sorted(jobs, key=lambda j: j.created_at, reverse=True)]

    def cancel(self, job_id: str) -> tuple[bool, str]:
        job = self.get(job_id)
        if job is None:
            return False, "Job not found"
        if job.status == "queued":
            with self._lock:
                if job_id in self._queue:
                    self._queue.remove(job_id)
            job.set_status("cancelled")
            return True, "Cancelled while queued"
        if job.status == "running":
            proc = job.proc
            if proc is not None:
                try:
                    proc.terminate()  # SIGTERM; the CLI exits with nonzero
                except ProcessLookupError:
                    pass
                job.set_status("cancelled", "Cancelled by user")
                return True, "Cancelled"
            job.set_status("cancelled", "Cancelled by user")
            return True, "Cancelled"
        return False, f"Job already {job.status}"

    # ---- worker ----
    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run_worker, daemon=True, name="autorb-jobs")
                self._worker.start()

    def _run_worker(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                job_id = self._queue.pop(0)
                job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                continue
            try:
                self._execute(job)
            except Exception as e:  # runner bugs must not kill the worker
                job.set_status("failed", f"Internal runner error: {e!r}")

    def _execute(self, job: Job) -> None:
        if job.batch_songs is not None:
            self._execute_batch(job)
            return
        cmd = build_cli_command(job, self.repo_root)
        job.set_running()
        if self.run_hook is not None:
            # Test seam: fake runner (returns exit code, writes log lines)
            exit_code = self.run_hook(job, cmd)
            job.exit_code = exit_code
            if exit_code == 0:
                job.set_status("success")
            else:
                job.set_status("failed",
                               f"Pipeline exited with code {exit_code}")
            return

        exit_code = self._run_cli(job, cmd)
        job.exit_code = exit_code
        if exit_code == 0:
            job.set_status("success")
        else:
            job.set_status("failed",
                           f"Pipeline exited with code {exit_code}")

    def _run_cli(self, job: Job, cmd: list[str],
                 ingest=None) -> int:
        """Run one CLI subprocess, streaming its output into the job's log.

        ``ingest(job_line_handler)`` optionally overrides the per-line
        progress ingestion (batch mode scales each song's output)."""
        with open(job.log_path, "a", encoding="utf-8") as log_file:
            job.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.repo_root,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            assert job.proc.stdout is not None
            for line in job.proc.stdout:
                line = line.rstrip()
                log_file.write(line + "\n")
                log_file.flush()
                if ingest is not None:
                    ingest(line)
                else:
                    job.ingest_line(line)
            exit_code = job.proc.wait()
        job.proc = None
        return exit_code

    def _execute_batch(self, job: Job) -> None:
        """Run every song's pipeline in sequence, then package all CONs.

        Each song runs in its own sub-output-dir so its CON is produced
        independently (a song's failure aborts the whole batch — the user
        re-runs the exact same batch after iterating; partial CON sets
        silently missing from the pack would be a lie).
        """
        job.set_running()
        songs = job.batch_songs
        con_paths = []
        for i, song in enumerate(songs):
            label = song.get("label") or f"song {i+1}"
            # filesystem-safe dir name (a label like "AC/DC - Back in Black"
            # must not create nested dirs)
            safe = re.sub(r"[^a-zA-Z0-9 _-]+", "", label).strip()[:60] or "song"
            song_out = job.output_dir / f"song_{i+1:02d}_{safe}"
            song_out.mkdir(parents=True, exist_ok=True)
            job.ingest_line(f"=== batch song {i+1}/{len(songs)}: {label} ===")

            # build a pseudo-Job whose options/uploads the command builder
            # reads, but run it as this job (shared log + progress + proc)
            sj = Job(f"{job.id}-s{i+1}", job.dir)
            sj.options = song["options"]
            sj.uploads = {k: str(v) for k, v in song["files"].items()
                          if v is not None}
            sj.output_dir = song_out
            if "stems" in sj.uploads:
                stems_src = Path(sj.uploads["stems"])
                dest = song_out / "stems"
                dest.mkdir(parents=True, exist_ok=True)
                for f in sorted(stems_src.glob("*.wav")):
                    shutil.copy2(f, dest / f.name)
                sj.uploads["stems"] = str(dest)

            try:
                cmd = build_cli_command(sj, self.repo_root)
            except JobError as e:
                job.set_status("failed", f"[{label}] {e}")
                return
            if self.run_hook is not None:
                exit_code = self.run_hook(job, cmd)
            else:
                exit_code = self._run_cli(
                    job, cmd,
                    ingest=lambda ln, i=i: job.batch_ingest(i, ln))
            job.exit_code = exit_code
            if exit_code != 0:
                job.set_status("failed",
                               f"[{label}] pipeline exited with code {exit_code}")
                return
            cons = sorted(song_out.glob("*.con"))
            if not cons:
                job.set_status("failed", f"[{label}] produced no CON file")
                return
            con_paths.append(cons[0])

        # ---- package all CONs into one multi-song CON + one PS4 PKG ----
        job.ingest_line(f"=== packaging {len(con_paths)} CONs into the "
                        f"multi-song pack ===")
        pkg_dir = job.output_dir / "con_pack"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        for p in con_paths:
            shutil.copy2(p, pkg_dir / p.name)
        args = ["python", "-m", "autorb.cli", "--package-con-dir",
                str(pkg_dir)]
        if job.ps4_pkg_id:
            args += ["--ps4-pkg-id", job.ps4_pkg_id]
        if self.run_hook is not None:
            exit_code = self.run_hook(job, args)
        else:
            exit_code = self._run_cli(
                job, args, ingest=job.batch_ingest_packaging)
        job.exit_code = exit_code
        if exit_code == 0:
            job.set_status("success")
        else:
            job.set_status("failed",
                           f"packaging exited with code {exit_code}")
