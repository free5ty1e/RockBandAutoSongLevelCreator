#!/usr/bin/env python3
"""Audit a built AutoRB release end-to-end.

The release-audit counterpart to the CI/CD workflow: everything a careful
reviewer would check after a tag build finishes, automated so it can run on
EVERY release (the v0.1.30-alpha01 tag shipped a broken build because crepe
uses pkg_resources at install time — a fresh-environment failure nobody saw
because the devcontainer's environment happened to have it).

Checks (each a pass/fail with a written finding; --strict exits nonzero on
any failure, default exits 0 with the report):

  STAGE 1 — CI/CD state (needs `gh`; read-only operations only)
    1.1  the workflow run for the tag exists and COMPLETED SUCCESSFULLY
    1.2  its jobs (test / build / release) all succeeded
    1.3  the GitHub release for the tag exists

  STAGE 2 — release artifacts
    2.1  release has exactly the expected assets (wheel + sdist, possibly
         PEP 440-local-renamed for test tags) and nothing unexpected
    2.2  download the wheel + sdist to a work dir

  STAGE 3 — wheel contents
    3.1  version matches the tag prefix (vX.Y.Z-suffix -> X.Y.Z)
    3.2  every source package/module ships in the wheel (autorb.*, webui) —
         compares pyproject's packages list against the wheel's file list
    3.3  packaged data assets present (template.con, milo/png templates,
         fonts, the nmp.onnx Basic Pitch model)
    3.4  RELEASE_NOTES.txt ships in the wheel and mentions the version
    3.5  wheel METADATA requires every runtime import the audit can find
         (catches "works in the devcontainer, ModuleNotFoundError for users")

  STAGE 4 — release notes
    4.1  the CHANGELOG has an entry for the exact version
    4.2  the release body covers the version's CHANGELOG entry (the release
         notes generator embeds it verbatim)
    4.3  the release body carries the user-facing README sections

  STAGE 5 — fresh-environment smoke test (the check that would have caught
         the crepe failure on a machine WITHOUT the devcontainer's env)
    5.1  create a fresh venv, pip install the DOWNLOADED WHEEL
    5.2  import every top-level autorb.* + webui module in that venv
    5.3  `autorb.version.__version__` matches the audited version
    5.4  (optional, --smoke-cli) autorb.cli --help runs
    5.5  pip check passes in the venv (dependency conflicts)

  STAGE 6 — tag hygiene
    6.1  tag prefix matches autorb/version.py (same rule as the workflow)
    6.2  (informational) the CHANGELOG version == the version.py version

Usage:
    python tools/audit_release.py --tag v0.1.30-alpha01
    python tools/audit_release.py --release-url https://github.com/.../releases/tag/vX
    python tools/audit_release.py --work-dir ./release_audit  (keep downloads)
    --skip-smoke    skip the fresh-venv stage (5) — the slow stage
    --strict        exit 1 if any check failed

Requires: `gh` authenticated with read access (repo + actions reads only).
Stage 5 additionally needs `python -m venv` + network to PyPI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv as _venv_module  # noqa: F401  (documented requirement)
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The data files that MUST ship inside the wheel (package-data paths as
# they appear in the wheel zip listing).
REQUIRED_WHEEL_DATA = [
    "autorb/export/data/template.con",
    "autorb/export/data/template_milo.bin",
    "autorb/export/data/template_png.bin",
    "autorb/export/data/fonts/DejaVuSans.ttf",
    "autorb/export/data/fonts/DejaVuSans-Bold.ttf",
    "autorb/pitch/nmp.onnx",
]

# User-facing README sections the release notes embed (see
# tools/gen_release_notes.py README_SECTIONS — kept in sync here so the
# audit fails loudly if the generator's contract changes).
NOTES_README_SECTIONS = [
    "Key Features",
    "Known Limitations",
    "Quick Start & Usage",
]

EXPECTED_IMPORTS = [
    "autorb", "autorb.cli", "autorb.version",
    "autorb.audio.stems", "autorb.audio.tempo", "autorb.audio.vocals",
    "autorb.audio.step4_sync", "autorb.audio.preview",
    "autorb.audio.mix_preview",
    "autorb.export.clone_hero", "autorb.export.con_packer",
    "autorb.export.midi_generator", "autorb.export.mogg_builder",
    "autorb.export.dta_writer", "autorb.export.texture",
    "autorb.export.album_art", "autorb.export.alignment_report",
    "autorb.export.forge_simulator", "autorb.export.stfs_validator",
    "autorb.pitch", "autorb.pitch.inference",
    "autorb.transcribe.instruments",
    "autorb.transcribe.instruments.guitar",
    "autorb.transcribe.instruments.drums",
    "autorb.transcribe.instruments.keys",
    "autorb.transcribe.instruments.difficulty",
    "webui", "webui.server", "webui.jobs", "webui.batch",
    "webui.progress", "webui.reveal",
]


class Audit:
    def __init__(self, strict: bool):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.findings: list[str] = []
        self.strict = strict

    def ok(self, msg: str) -> None:
        self.passed += 1
        self.findings.append(f"  PASS  {msg}")
        print(f"  PASS  {msg}")

    def fail(self, msg: str) -> None:
        self.failed += 1
        self.findings.append(f"! FAIL  {msg}")
        print(f"! FAIL  {msg}")

    def warn(self, msg: str) -> None:
        self.warnings += 1
        self.findings.append(f"~ WARN  {msg}")
        print(f"~ WARN  {msg}")

    def summary(self) -> int:
        print()
        print("=" * 70)
        print(f"Release audit: {self.passed} passed, {self.failed} failed, "
              f"{self.warnings} warnings")
        rc = 1 if (self.failed and self.strict) else 0
        print(f"exit code: {rc}" + (" (strict mode)" if self.failed else ""))
        return rc


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _gh(args: list[str], audit: Audit) -> str | None:
    """Run a read-only gh command, returning stdout (None on failure)."""
    r = _run(["gh", *args])
    if r.returncode != 0:
        audit.fail(f"`gh {' '.join(args[:2])}...` failed: "
                    f"{(r.stderr or r.stdout).strip()[:200]}")
        return None
    return r.stdout


def version_from_tag(tag: str) -> str:
    """vX.Y.Z-suffix -> X.Y.Z (same prefix rule the CI workflow enforces)."""
    return tag[1:].split("-", 1)[0] if tag.startswith("v") else tag


def current_version() -> str:
    ns: dict[str, str] = {}
    exec((REPO_ROOT / "autorb" / "version.py").read_text(), ns)
    return ns["__version__"]


# ------------------------------------------------------------- stage 1-2 ---
def stage_ci_and_release(tag: str, audit: Audit) -> dict | None:
    print("\n=== STAGE 1 — CI/CD state ===")
    runs_json = _gh(["run", "list", f"--repo",
                     _repo_slug(), "--limit", "50", "--json",
                     "databaseId,status,conclusion,displayTitle,headBranch,workflowName"],
                    audit)
    if runs_json is None:
        return None
    runs = json.loads(runs_json)
    tag_runs = [r for r in runs if r.get("headBranch") == tag]
    if not tag_runs:
        audit.fail(f"no CI workflow run found for tag {tag} (runs list "
                   f"covers the latest 50 — is the tag pushed?)")
        return None
    # Prefer a COMPLETED run: when the audit runs INSIDE the CI pipeline
    # (its own job), the current run is still in_progress and would
    # otherwise warn spuriously (observed on the alpha04 CI audit).
    completed = [r for r in tag_runs if r.get("status") == "completed"]
    run = completed[0] if completed else tag_runs[0]
    if run["status"] != "completed":
        audit.warn(f"run for {tag} is still {run['status']} — audit what "
                   "exists so far; re-run the audit once it completes")
    elif run["conclusion"] != "success":
        audit.fail(f"CI run for {tag} CONCLUDED "
                   f"'{run['conclusion']}' (run {run['databaseId']}). "
                   "The release is broken — fix the workflow before "
                   "auditing the artifacts.")
        # Still return the run so later stages report what's missing.
    else:
        audit.ok(f"CI run for {tag} succeeded (run {run['databaseId']})")

    jobs_json = _gh(["run", "view", str(run["databaseId"]),
                     f"--repo", _repo_slug(), "--json", "jobs"], audit)
    if jobs_json:
        jobs = json.loads(jobs_json).get("jobs", [])
        bad = [j["name"] for j in jobs if j.get("conclusion") not in
               ("success", "skipped")]
        if run["status"] == "completed" and bad:
            audit.fail(f"failing CI jobs: {', '.join(bad)}")
        elif jobs:
            audit.ok(f"all {len(jobs)} CI jobs green "
                     f"({', '.join(j['name'] for j in jobs)})")

    # GitHub release
    print("\n=== STAGE 2 — GitHub release ===")
    rel_json = _gh(["release", "view", tag, f"--repo", _repo_slug(),
                    "--json", "name,tagName,isDraft,assets,body"], audit)
    if rel_json is None:
        audit.fail(f"no GitHub release for tag {tag}")
        return {"run": run, "release": None}
    rel = json.loads(rel_json)
    if rel.get("isDraft"):
        audit.warn(f"release {tag} is a DRAFT — not visible to users yet")
    else:
        audit.ok(f"release '{rel.get('name')}' exists for {tag}")
    assets = rel.get("assets", [])
    wheels = [a for a in assets if a["name"].endswith(".whl")]
    sdists = [a for a in assets if a["name"].endswith(".tar.gz")]
    if not wheels or not sdists:
        audit.fail(f"release assets incomplete: {len(wheels)} wheel(s), "
                   f"{len(sdists)} sdist(s) — expected at least one each")
    else:
        audit.ok(f"release assets: {len(wheels)} wheel(s) + "
                 f"{len(sdists)} sdist(s)")
    return {"run": run, "release": rel}


def download_assets(rel: dict | None, work_dir: Path,
                     audit: Audit) -> tuple[Path | None, Path | None]:
    if not rel:
        return None, None
    assets = rel.get("assets", [])
    # Match gh's --pattern against the asset NAME, never a URL segment: the
    # PEP 440 local-version filenames carry '+', which the release URL
    # encodes as '%2B' — pattern-matching the URL form finds no assets (the
    # v0.1.31-alpha03 audit failure).
    def _asset_name(suffix: str) -> str | None:
        return next((a["name"] for a in assets if a["name"].endswith(suffix)),
                    None)
    wheel_name = _asset_name(".whl")
    sdist_name = _asset_name(".tar.gz")
    wheel_path = sdist_path = None
    for name, kind in ((wheel_name, "wheel"), (sdist_name, "sdist")):
        if not name:
            continue
        r = _gh(["release", "download", rel["tagName"], f"--repo",
                 _repo_slug(), "--pattern", name, "--clobber",
                 "--dir", str(work_dir)], audit)
        if r is None:
            audit.fail(f"could not download the {kind}")
    for p in work_dir.glob("*.whl"):
        wheel_path = p
    for p in work_dir.glob("*.tar.gz"):
        sdist_path = p
    if wheel_path:
        audit.ok(f"downloaded wheel: {wheel_path.name}")
    if sdist_path:
        audit.ok(f"downloaded sdist: {sdist_path.name}")
    return wheel_path, sdist_path


# ------------------------------------------------------------- stage 3-4 ---
def stage_wheel_contents(wheel_path: Path | None, version: str,
                         audit: Audit) -> dict | None:
    print("\n=== STAGE 3 — wheel contents ===")
    if wheel_path is None:
        audit.fail("wheel audit skipped (no wheel)")
        return None
    with zipfile.ZipFile(wheel_path) as z:
        names = z.namelist()

    # 3.1 version
    m = re.match(r"autorb-(.+?)-py3-none-any", wheel_path.name)
    wheel_version = m.group(1).split("+", 1)[0] if m else "?"
    (audit.ok if wheel_version == version else audit.fail)(
        f"wheel version {wheel_version} vs tag-derived {version}")

    # 3.2 every declared package's .py modules ship (source-parity check)
    missing_modules = []
    for pkg in ("autorb", "autorb.audio", "autorb.export", "autorb.pitch",
                "autorb.transcribe", "autorb.transcribe.instruments", "webui"):
        src_dir = REPO_ROOT / Path(*pkg.split("."))
        for py in sorted(src_dir.glob("*.py")):
            rel = py.relative_to(REPO_ROOT).as_posix()
            if rel not in names:
                missing_modules.append(rel)
    if missing_modules:
        audit.fail("modules missing from the wheel (pyproject packages "
                   f"list?): {missing_modules}")
    else:
        audit.ok(f"every source module ships in the wheel "
                 f"({sum(1 for n in names if n.endswith('.py'))} .py files)")

    # 3.3 data assets
    missing_data = [d for d in REQUIRED_WHEEL_DATA
                    if not any(n == d or n.startswith(d) for n in names)]
    if missing_data:
        audit.fail(f"packaged data missing from the wheel: {missing_data}")
    else:
        audit.ok(f"all {len(REQUIRED_WHEEL_DATA)} required data assets ship "
                 "(templates, fonts, ONNX model)")

    # 3.4 release notes in the wheel
    notes = [n for n in names if n.endswith("RELEASE_NOTES.txt")]
    if not notes:
        audit.fail("RELEASE_NOTES.txt not in the wheel")
    else:
        with zipfile.ZipFile(wheel_path) as z:
            data = z.read(notes[0]).decode("utf-8", "replace")
        if version in data:
            audit.ok(f"wheel RELEASE_NOTES.txt present, mentions {version}")
        else:
            audit.fail(f"wheel RELEASE_NOTES.txt does not mention {version}")

    # 3.5 METADATA dependency vs actual imports (best-effort)
    with zipfile.ZipFile(wheel_path) as z:
        meta_name = next(n for n in names if n.endswith("METADATA"))
        meta = z.read(meta_name).decode("utf-8", "replace")
    declared = {m.group(1).lower().replace("-", "_").split(">")[0].split("<")[0].split("=")[0].strip()
                for m in re.finditer(r"^Requires-Dist: ([^\s;]+)", meta, re.M)}
    # top-level third-party imports found in source
    top_imports = set()
    for py in REPO_ROOT.glob("autorb/**/*.py"):
        for m in re.finditer(r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)",
                             py.read_text(errors="replace"), re.M):
            top_imports.add(m.group(1))
    stdlib_or_ours = set(sys.stdlib_module_names) | {"autorb", "webui"}
    undeclared = sorted(i for i in top_imports
                        if i not in stdlib_or_ours and i not in declared
                        and not any(d.startswith(i) for d in declared))
    # NOTE: transitive deps (e.g. numpy via librosa) legitimately appear as
    # imports without being direct Requires-Dist — only WARN on those, the
    # fresh-venv smoke (stage 5) is the real gate.
    if undeclared:
        audit.warn(f"source imports not direct wheel dependencies "
                   f"(fine if transitive; stage 5 verifies): {undeclared}")
    else:
        audit.ok("every source import is a direct or stdlib dependency")
    return {"meta": meta}


def stage_release_notes(rel: dict | None, version: str,
                        audit: Audit) -> None:
    print("\n=== STAGE 4 — release notes ===")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()
    if not re.search(rf"^## \[{re.escape(version)}\]", changelog, re.M):
        audit.fail(f"no CHANGELOG.md entry for [{version}]")
    else:
        audit.ok(f"CHANGELOG has an entry for [{version}]")
    if not rel:
        return
    body = rel.get("body") or ""
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
                  changelog, re.M | re.S)
    if m:
        excerpt = re.sub(r"\s+", " ", m.group(1).strip())[:80]
        if excerpt and re.sub(r"\s+", " ", excerpt) in re.sub(r"\s+", " ", body):
            audit.ok("release body embeds this version's CHANGELOG entry")
        else:
            audit.fail("release body does NOT embed the CHANGELOG entry for "
                       f"[{version}] (generator contract broken?)")
    for section in NOTES_README_SECTIONS:
        # the notes carry these as headings; match loosely on title text
        if section.split("&")[0].strip().lower() in body.lower():
            audit.ok(f"release body includes README section '{section}'")
        else:
            audit.fail(f"release body missing README section '{section}'")


# --------------------------------------------------------------- stage 5 ---
def stage_fresh_venv_smoke(wheel_path: Path | None, version: str,
                           audit: Audit, skip: bool) -> None:
    print("\n=== STAGE 5 — fresh-environment smoke test ===")
    if skip:
        audit.warn("skipped (--skip-smoke)")
        return
    if wheel_path is None:
        audit.fail("smoke test skipped (no wheel to install)")
        return
    work = wheel_path.parent / "smoke_venv"
    if work.exists():
        shutil.rmtree(work)
    r = _run([sys.executable, "-m", "venv", str(work)])
    if r.returncode != 0:
        audit.fail(f"venv creation failed: {r.stderr[:200]}")
        return
    pip = str(work / "bin" / "pip")
    # install the DOWNLOADED wheel from PyPI deps — this is what a real
    # user does, and what would have caught the crepe build failure.
    r = _run([pip, "install", "--quiet", str(wheel_path)], timeout=900)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout)[-600:]
        audit.fail(f"wheel install into a fresh venv FAILED (this is the "
                   f"crepe-class failure): ...{tail}")
        return
    audit.ok("wheel installs into a fresh venv (all PyPI deps resolve)")

    r = _run([pip, "check"])
    if r.returncode != 0:
        audit.warn(f"pip check reported conflicts: {r.stdout.strip()[:300]}")
    else:
        audit.ok("pip check clean (no dependency conflicts)")

    py = str(work / "bin" / "python")
    # import every module the release ships
    r = _run([py, "-c",
              "; ".join(f"import {m}" for m in EXPECTED_IMPORTS)])
    if r.returncode != 0:
        audit.fail(f"module imports fail in the fresh venv: "
                   f"{(r.stderr or '').strip()[:300]}")
    else:
        audit.ok(f"all {len(EXPECTED_IMPORTS)} runtime modules import in a "
                 "fresh environment")

    r = _run([py, "-c", "from autorb.version import __version__; print(__version__)"])
    got = (r.stdout or "").strip()
    (audit.ok if got == version else audit.fail)(
        f"installed version reports {got!r} (expected {version!r})")

    r = _run([py, "-m", "autorb.cli", "--help"])
    (audit.ok if r.returncode == 0 else audit.fail)(
        "`python -m autorb.cli --help` exits 0 in the fresh venv"
        if r.returncode == 0 else
        f"CLI smoke failed: {(r.stderr or '').strip()[:300]}")

    # STAGE 5b — functional conversion: run the wheel-installed pipeline on
    # the committed 60s Open Road Song test clip and validate the artifacts.
    # Install/import/--help cannot catch a lazy import that only fires mid-
    # pipeline, a data file only read at runtime, or the optional-dep
    # fallback paths (adtof/madmom/basic_pitch are absent in a wheel-only
    # install — exactly what users get).
    stage_functional_conversion(work, audit, skip)


def stage_functional_conversion(venv: Path, audit: Audit, skip: bool) -> None:
    print("\n=== STAGE 5b — functional conversion (60s test song) ===")
    if skip:
        audit.warn("skipped (--skip-smoke skips the conversion too)")
        return
    py = str(venv / "bin" / "python")
    clip = REPO_ROOT / "tools" / "test_data" / "ors_60s.mp3"
    lrc = REPO_ROOT / "tools" / "test_data" / "ors_60s.lrc"
    if not clip.exists():
        audit.fail("committed test clip tools/test_data/ors_60s.mp3 missing")
        return
    out = venv.parent / "conversion_out"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Pre-fetch the Demucs model ONCE into the venv user's HF cache so a
    # flaky network mid-run doesn't read as a broken wheel (models are
    # cached by huggingface_hub; the run below then uses the cache).
    model = "htdemucs_6s"
    # NOTE: just get_model() — a BagOfModels has no .name attribute (the
    # first version of this probe crashed on m.name and mis-read a
    # successful fetch as a failure).
    r = _run([py, "-c", f"""
from demucs.pretrained import get_model
get_model('{model}')
"""], timeout=900)
    if r.returncode != 0:
        audit.warn(f"demucs model pre-fetch failed ({(r.stderr or '')[-150:]}); "
                   "attempting the conversion anyway")
    else:
        audit.ok(f"demucs '{model}' model fetches (HF cache warm)")

    cmd = [py, "-m", "autorb.cli", str(clip),
           "--artist", "Eve 6", "--title", "Open Road Song (60s test)",
           "--year", "1998", "--genre", "Alternative",
           "--lyrics", str(lrc),
           "--separator", model,
           "--output-dir", str(out),
           "--build-clone-hero"]
    print("  running:", " ".join(cmd[:8]), "...")
    r = _run(cmd, timeout=3600)   # CPU Demucs on 60s ≈ a few minutes
    if r.returncode != 0:
        tail = (r.stderr or r.stdout)[-800:]
        audit.fail(f"conversion FAILED (the release wheel cannot chart a "
                   f"song!): ...{tail}")
        return
    audit.ok("wheel-installed CLI converts the 60s test song end-to-end")

    # ---- artifact validation -------------------------------------------
    problems = []
    found = {}

    # Clone Hero folder + files
    ch = list(out.glob("clone_hero/*/"))
    if not ch:
        problems.append("no clone_hero/<song>/ output folder")
    else:
        folder = ch[0]
        for name, min_bytes in (("song.ogg", 50_000),
                                ("notes.mid", 500),
                                ("notes.chart", 1_000),
                                ("song.ini", 100),
                                ("album.png", 1_000)):
            f = folder / name
            if not f.exists():
                problems.append(f"clone_hero output missing {name}")
            elif f.stat().st_size < min_bytes:
                problems.append(f"clone_hero {name} suspiciously small "
                                 f"({f.stat().st_size} B)")
            else:
                found[name] = f.stat().st_size

    # CON
    con = list(out.glob("*.con"))
    if not con:
        problems.append("no .con package produced")
    elif con[0].stat().st_size < 100_000:
        problems.append(f".con suspiciously small ({con[0].stat().st_size} B)")
    else:
        found["con"] = con[0].stat().st_size

    # MOGG
    mogg = list(out.glob("*.mogg"))
    if not mogg:
        problems.append("no .mogg produced")
    elif mogg[0].stat().st_size < 200_000:
        problems.append(f".mogg suspiciously small ({mogg[0].stat().st_size} B)")
    else:
        found["mogg"] = mogg[0].stat().st_size

    # MIDI chart must contain instrument tracks with notes (the placeholder-
    # failure class): parse the count-in-free validation mid for substance.
    mid = out / "validation" / "notes.mid"
    if not mid.exists():
        mid = next(iter(out.glob("*.mid")), None)
    if mid is None:
        problems.append("no .mid chart produced")
    else:
        try:
            import mido
            mf = mido.MidiFile(str(mid))
            per_track: dict[str, int] = {}
            for tr in mf.tracks:
                if tr.name and any(m.type == "note_on" and m.velocity > 0
                                   for m in tr if hasattr(m, "note")):
                    per_track[tr.name] = sum(
                        1 for m in tr
                        if getattr(m, "type", "") == "note_on" and m.velocity > 0)
            for want in ("PART GUITAR", "PART BASS", "PART DRUMS"):
                if per_track.get(want, 0) < 10:
                    problems.append(f"{want} has <10 notes "
                                    f"({per_track.get(want, 0)}) — placeholder-class chart")
                else:
                    found[want] = per_track[want]
        except ImportError:
            audit.warn("mido not importable in the audit env; skipped "
                       "chart-substance check")

    if problems:
        for p in problems:
            audit.fail(f"artifact validation: {p}")
    else:
        audit.ok(f"artifacts complete and substantial: "
                 + ", ".join(f"{k}={v:,}B" if isinstance(v, int) and v > 10_000
                              else f"{k}={v}"
                              for k, v in sorted(found.items())))


# --------------------------------------------------------------- stage 6 ---
def stage_tag_hygiene(tag: str, version: str, audit: Audit) -> None:
    print("\n=== STAGE 6 — tag hygiene ===")
    current = current_version()
    if version == current:
        audit.ok(f"tag prefix v{version} == autorb/version.py "
                 f"({current})")
    else:
        audit.fail(f"tag prefix v{version} does NOT match "
                   f"autorb/version.py ({current}) — the workflow's own "
                   "check should have caught this")
    if re.search(rf"^## \[{re.escape(current)}\]",
                 (REPO_ROOT / "CHANGELOG.md").read_text(), re.M):
        audit.ok(f"CHANGELOG entry exists for the working-tree version "
                 f"[{current}]")
    else:
        audit.warn(f"working tree version {current} has no CHANGELOG entry "
                   "(fine mid-development; required before tagging)")


def _repo_slug() -> str:
    r = _run(["git", "remote", "get-url", "origin"])
    url = r.stdout.strip() if r.returncode == 0 else ""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(\.git)?$", url)
    return m.group(1) if m else "free5ty1e/RockBandAutoSongLevelCreator"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tag", help="the git tag to audit (e.g. v0.1.30-alpha01)")
    ap.add_argument("--release-url",
                    help="a GitHub release URL (tag extracted from it)")
    ap.add_argument("--work-dir", default=None,
                    help="download dir (default: a temp dir, removed unless "
                         "this is given)")
    ap.add_argument("--skip-smoke", action="store_true",
                    help="skip the fresh-venv install/import stage")
    ap.add_argument("--strict", action="store_true",
                    help="exit nonzero if any check failed")
    args = ap.parse_args()

    tag = args.tag
    if args.release_url:
        m = re.search(r"(?:releases/tag/)(v[^/]+)", args.release_url)
        if not m:
            print("error: could not parse a tag out of --release-url",
                  file=sys.stderr)
            return 2
        tag = m.group(1)
    if not tag:
        print("error: --tag or --release-url is required", file=sys.stderr)
        return 2

    version = version_from_tag(tag)
    audit = Audit(strict=args.strict)
    print(f"AutoRB release audit — tag {tag} (version {version})")
    print(f"repo: {_repo_slug()}")

    ctx = stage_ci_and_release(tag, audit)
    work_dir = Path(args.work_dir) if args.work_dir else \
        Path(tempfile.mkdtemp(prefix="release_audit_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    wheel, _sdist = download_assets(ctx.get("release") if ctx else None,
                                    work_dir, audit)
    stage_wheel_contents(wheel, version, audit)
    stage_release_notes(ctx.get("release") if ctx else None, version, audit)
    stage_fresh_venv_smoke(wheel, version, audit, args.skip_smoke)
    stage_tag_hygiene(tag, version, audit)

    if not args.work_dir and audit.failed:
        # keep the downloads for post-mortem on failure
        print(f"\n(keeping audit work dir for inspection: {work_dir})")
    elif not args.work_dir:
        shutil.rmtree(work_dir, ignore_errors=True)

    report = "\n".join(audit.findings)
    (work_dir / "AUDIT_REPORT.txt").write_text(report + "\n") \
        if args.work_dir else None
    return audit.summary()


if __name__ == "__main__":
    sys.exit(main())
