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

        with open(job.log_path, "w", encoding="utf-8") as log_file:
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
                job.ingest_line(line)
            exit_code = job.proc.wait()
        job.proc = None
        job.exit_code = exit_code
        if exit_code == 0:
            job.set_status("success")
        else:
            job.set_status("failed",
                           f"Pipeline exited with code {exit_code}")
