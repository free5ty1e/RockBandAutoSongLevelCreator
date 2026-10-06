"""AutoRB web engine: FastAPI server that wraps the real pipeline CLI.

Run locally:   python -m webui.server        (http://127.0.0.1:7860)
   or:          autorb-webui                (console script, same thing)
Env:
  AUTORB_WEBUI_HOST   bind host (default 127.0.0.1 — local only; set 0.0.0.0
                      to expose on the LAN at your own risk: no auth)
  AUTORB_WEBUI_PORT   bind port (default 7860)
  AUTORB_WEBUI_JOBS   jobs root (default ./webui_jobs)

Flow:
  POST /api/upload                 multipart files -> draft job (id returned)
  POST /api/jobs/{id}/start        options JSON -> job queued (single worker)
  GET  /api/jobs/{id}              status/progress/log tail (poll)
  POST /api/jobs/{id}/cancel       SIGTERM the pipeline
  POST /api/jobs/{id}/reveal       open the job's output folder in Explorer
  GET  /api/jobs/{id}/files        artifact list (download links)
  GET  /api/capabilities           what this machine can do (UI greys options)
  GET  /                           the same static UI GitHub Pages serves

The same static UI (webui/static/index.html) is published to GitHub Pages via
docs/ — there it shows "connect to your engine" instructions and posts to the
engine URL (default http://127.0.0.1:7860), because Pages can't execute the
pipeline; the engine only runs on the user's own machine.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import zipfile
from pathlib import Path

try:
    from fastapi import Body, FastAPI, File, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as _e:  # pragma: no cover - UX guard
    raise SystemExit(
        "The AutoRB web engine needs FastAPI which is not installed.\n"
        "Install the web extras and retry:\n"
        "    pip install -e '.[web]'\n"
        f"(missing module: {_e.name})"
    ) from _e

from .jobs import (
    ART_EXTS, AUDIO_EXTS, LRC_EXTS, SEPARATORS, STEM_NAMES, JobError, JobStore,
)
from .reveal import reveal_in_file_manager

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
JOBS_ROOT = Path(os.environ.get("AUTORB_WEBUI_JOBS",
                                str(REPO_ROOT / "webui_jobs")))

MAX_AUDIO_BYTES = 600 * 1024 * 1024   # 600 MB
MAX_LRC_BYTES = 2 * 1024 * 1024       # 2 MB
MAX_ART_BYTES = 20 * 1024 * 1024      # 20 MB
MAX_STEM_BYTES = 600 * 1024 * 1024    # per stem
MAX_STEMS_ZIP_BYTES = 600 * 1024 * 1024

# Artifact extensions surfaced by /api/jobs/{id}/files (everything else in
# the output dir is still on disk and reachable via /files/<id>/output/...).
ARTIFACT_EXTS = {".con", ".pkg", ".mid", ".mogg", ".ogg", ".wav", ".png",
                 ".json", ".srt", ".ini", ".chart", ".dta"}

app = FastAPI(title="AutoRB Web Engine", version=__import__(
    "autorb.version", fromlist=["__version__"]).__version__)

# The Pages-hosted UI (https://free5ty1e.github.io/...) posts to this local
# engine from a public origin, so CORS must be open. This binds to 127.0.0.1
# by default and holds nothing secret; worst case a LAN user (if you opted
# into 0.0.0.0) could start a charting job.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = JobStore(JOBS_ROOT, repo_root=REPO_ROOT)


# --------------------------------------------------------------- uploads ---
def _ext(name: str | None) -> str:
    return Path(name or "").suffix.lower()


async def _save(f: UploadFile, dest_dir: Path, base: str, allowed: set,
               max_bytes: int, role: str) -> Path:
    """Stream an UploadFile to dest_dir/<base><ext>, enforcing size+ext."""
    ext = _ext(f.filename)
    if ext not in allowed:
        raise HTTPException(
            400, f"{role}: unsupported file type '{ext or '(none)'}' "
                 f"(allowed: {', '.join(sorted(allowed))})")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{base}{ext}"
    size = 0
    with open(dest, "wb") as out:
        while chunk := await f.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    400, f"{role}: file too large "
                         f"(max {max_bytes // (1024 * 1024)} MB)")
            out.write(chunk)
    return dest


@app.post("/api/upload")
async def upload(
    audio: UploadFile | None = File(None),
    lrc: UploadFile | None = File(None),
    album_art: UploadFile | None = File(None),
    stems_zip: UploadFile | None = File(None),
    stems_files: list[UploadFile] | None = File(None),
):
    """Create a draft job and save its uploaded files.

    Provide either `audio`, or pre-separated stems: individual
    drums.wav/bass.wav/other.wav/vocals.wav (plus optional guitar.wav /
    piano.wav) via `stems_files`, or one .zip containing them via
    `stems_zip`. `lrc` and `album_art` are always optional.
    """
    has_audio = audio is not None and (audio.filename or "") != ""
    has_zip = stems_zip is not None and (stems_zip.filename or "") != ""
    has_stem_files = bool(stems_files)
    if not (has_audio or has_zip or has_stem_files):
        raise HTTPException(400, "Upload an audio file, individual stems, "
                                 "or a stems .zip")

    job = store.create_draft()
    up = job.uploads_dir

    if has_audio:
        job.uploads["audio"] = str(await _save(
            audio, up, "audio", AUDIO_EXTS, MAX_AUDIO_BYTES, "audio file"))
    if lrc is not None and (lrc.filename or ""):
        job.uploads["lrc"] = str(await _save(
            lrc, up, "lyrics", LRC_EXTS, MAX_LRC_BYTES, "lyrics (LRC) file"))
    if album_art is not None and (album_art.filename or ""):
        job.uploads["album_art"] = str(await _save(
            album_art, up, "album_art", ART_EXTS, MAX_ART_BYTES,
            "album art (PNG/JPG)"))

    if has_zip:
        zpath = await _save(stems_zip, up, "stems", {".zip"},
                            MAX_STEMS_ZIP_BYTES, "stems .zip")
        stems_dir = up / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zpath) as zf:
                for member in zf.namelist():
                    m = Path(member)
                    if m.suffix.lower() == ".wav" and m.stem in STEM_NAMES:
                        with zf.open(member) as src, \
                                open(stems_dir / m.name, "wb") as out:
                            shutil.copyfileobj(src, out)
        except zipfile.BadZipFile:
            raise HTTPException(400, "stems .zip is not a valid zip archive")
        finally:
            zpath.unlink(missing_ok=True)
        if not any(stems_dir.glob("*.wav")):
            raise HTTPException(
                400, "stems .zip contained no drums/bass/other/vocals "
                     "guitar/piano .wav files at its root")
        job.uploads["stems"] = str(stems_dir)

    if has_stem_files:
        stems_dir = up / "stems"
        stems_dir.mkdir(parents=True, exist_ok=True)
        for f in stems_files:
            if not f.filename:
                continue
            stem_name = Path(f.filename).stem
            if stem_name not in STEM_NAMES:
                raise HTTPException(
                    400, f"unknown stem '{f.filename}' — must be one of: "
                         f"{', '.join(sorted(STEM_NAMES))}")
            await _save(f, stems_dir, stem_name, {".wav"}, MAX_STEM_BYTES,
                        f"stem {stem_name}")
        if not any(stems_dir.glob("*.wav")):
            raise HTTPException(400, "no valid stem files uploaded")
        job.uploads["stems"] = str(stems_dir)

    return {"job_id": job.id, "uploads": dict(job.uploads)}


# ------------------------------------------------------------------ jobs ---
def _normalize_options(raw: dict) -> dict:
    """Coerce/validate the form options; raises JobError on bad input."""
    if not isinstance(raw, dict):
        raise JobError("options must be a JSON object")

    def text(key: str, required: bool = False, default: str = "") -> str:
        val = str(raw.get(key) or "").strip()
        if not val:
            if required:
                raise JobError(f"{key} is required")
            return default
        return val

    opts: dict = {}
    opts["artist"] = text("artist", required=True)
    opts["title"] = text("title", required=True)
    opts["genre"] = text("genre") or "Rock"

    year = str(raw.get("year") or "").strip()
    if year:
        try:
            opts["year"] = int(year)
        except ValueError:
            raise JobError(f"year must be a number, got '{year}'")
    else:
        opts["year"] = None

    if "stems" in (raw.get("_sources") or []):  # never trust; recomputed below
        pass

    sep = str(raw.get("separator") or "htdemucs_ft")
    if sep not in SEPARATORS:
        raise JobError(f"unknown separator '{sep}' "
                       f"(allowed: {', '.join(SEPARATORS)})")
    opts["separator"] = sep

    def num(key: str, cast, default, lo=None, hi=None):
        val = raw.get(key)
        if val in (None, ""):
            return default
        try:
            v = cast(val)
        except (TypeError, ValueError):
            raise JobError(f"{key} must be a number, got {val!r}")
        if lo is not None and v < lo or hi is not None and v > hi:
            raise JobError(f"{key} out of range ({lo}..{hi})")
        return v

    opts["ft_shifts"] = num("ft_shifts", int, 1, 1, 8)
    opts["ft_strip_seconds"] = num("ft_strip_seconds", float, 45.0, 10.0, 240.0)
    opts["ft_segment"] = num("ft_segment", float, None, 1.0, 60.0)
    opts["ft_overlap"] = num("ft_overlap", float, 0.25, 0.0, 0.75)

    for flag in ("build_pkg", "build_clone_hero", "generate_freestyle_vocals",
                 "freestyle_drums", "guitar_solo_charting"):
        opts[flag] = bool(raw.get(flag))

    return opts


@app.post("/api/jobs/{job_id}/start")
async def start_job(job_id: str, payload: dict = Body(...)):
    """Validate options + uploads, stage stems, and queue the job."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status != "draft":
        raise HTTPException(409, f"Job already {job.status}")

    raw_opts = (payload or {}).get("options") or payload or {}
    try:
        opts = _normalize_options(raw_opts)
    except JobError as e:
        raise HTTPException(400, str(e))

    has_audio = "audio" in job.uploads
    has_stems = "stems" in job.uploads
    if not (has_audio or has_stems):
        raise HTTPException(400, "This job has no audio or stems uploaded")
    if has_stems:
        # The CLI's --skip-separation reads <output-dir>/stems/*.wav —
        # copy the uploaded stems there before the run starts.
        dest = job.output_dir / "stems"
        dest.mkdir(parents=True, exist_ok=True)
        for f in sorted(Path(job.uploads["stems"]).glob("*.wav")):
            shutil.copy2(f, dest / f.name)
        missing = [s for s in ("drums", "bass", "other", "vocals")
                   if not (dest / f"{s}.wav").exists()]
        if missing:
            raise HTTPException(
                400, "stems upload is missing core stems: "
                     f"{', '.join(missing)}.wav (from a Demucs/spleeter "
                     "separation; guitar/piano are optional extras)")

    store.start(job, opts)
    return {"job": job.to_dict()}


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": store.list()}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    ok, msg = store.cancel(job_id)
    if not ok:
        raise HTTPException(409, msg)
    return {"ok": True, "message": msg}


@app.post("/api/jobs/{job_id}/reveal")
async def reveal_job(job_id: str):
    """Open the job's output folder in the OS file manager (Explorer/Finder)."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    target = job.output_dir if job.output_dir.exists() else job.dir
    ok, msg = reveal_in_file_manager(target)
    return {"ok": ok, "message": msg, "path": str(target)}


@app.get("/api/jobs/{job_id}/files")
async def job_files(job_id: str):
    """Interesting artifacts in the job's output dir, with download URLs."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    files = []
    if job.output_dir.exists():
        for p in sorted(job.output_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in ARTIFACT_EXTS:
                rel = p.relative_to(job.output_dir)
                files.append({
                    "name": str(rel),
                    "size": p.stat().st_size,
                    "url": f"/files/{job.id}/output/{rel.as_posix()}",
                })
    return {"files": files[:300]}


# --------------------------------------------------------- capabilities ---
@app.get("/api/capabilities")
async def capabilities():
    """What this engine machine can do (the UI greys out what's missing)."""
    return {
        "cpu_cores": os.cpu_count(),
        "mem_total_gb": round(_mem_total_gb(), 1),
        "cuda": _module_available("torch") and _torch_cuda(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "spleeter": _module_available("spleeter"),
        "adtof": _module_available("adtof_pytorch"),
        "os": sys.platform,
        "python": sys.version.split()[0],
        "autorb_version": _autorb_version(),
    }


def _mem_total_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError:
        pass
    try:
        import resource
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if pages > 0 and page_size > 0:
            return pages * page_size / 1e9
    except (ValueError, OSError):
        pass
    return 0.0


def _torch_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _module_available(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def _autorb_version() -> str:
    try:
        from autorb.version import __version__
        return __version__
    except Exception:
        return "?"


# ---------------------------------------------------------------- static ---
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
async def favicon():
    p = STATIC_DIR / "favicon.svg"
    if p.exists():
        return FileResponse(p, media_type="image/svg+xml")
    raise HTTPException(404)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/files", StaticFiles(directory=JOBS_ROOT), name="files")


def main() -> None:
    """Console-script entry point (`autorb-webui`)."""
    import uvicorn
    host = os.environ.get("AUTORB_WEBUI_HOST", "127.0.0.1")
    port = int(os.environ.get("AUTORB_WEBUI_PORT", "7860"))
    print(f"AutoRB web engine: http://{host}:{port}  "
          f"(jobs: {JOBS_ROOT})", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
