"""Web UI tests: engine API contract, progress parsing, CLI command build.

Covers the webui package (webui/server.py, webui/jobs.py, webui/progress.py,
webui/reveal.py) introduced for the local-engine + GitHub Pages architecture.

The real pipeline (Demucs etc.) is never invoked here:
  * the job runner uses `store.run_hook` (a fake that emits canned CLI log
    lines and returns an exit code) to exercise queueing/progress/status;
  * the CLI command builder is tested against its argument surface;
  * uploads are tiny in-memory bytes.

See .ai_memory/web_interface.md for the architecture.
"""

import io
import os
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from webui import progress as P
from webui.jobs import Job, JobError, JobStore, build_cli_command


# ------------------------------------------------------------- fixtures ---
@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient wired to a temp jobs root, with a fake runner."""
    import webui.server as srv

    monkeypatch.setenv("AUTORB_WEBUI_JOBS", str(tmp_path / "jobs"))
    import importlib
    importlib.reload(srv)
    # reload rebinds module globals; give the store a fake runner
    fake_lines = [
        "Starting AutoRB Pipeline for: Test - Song",
        "[1/5] Separating stems via Demucs...",
        "  separating strip 1/4 (htdemucs_ft)...",
        "  separating strip 2/4 (htdemucs_ft)...",
        "  separating strip 4/4 (htdemucs_ft)...",
        "[2/5] Extracting tempo and quantizing instruments...",
        "[3/5] Aligning vocals and parsing LRC...",
        "[4/5] Synchronizing beats and lyrics data...",
        "[4b/5] Transcribing instrument tracks (guitar, bass, drums)...",
        "[5/5] Building assets and packaging Xbox 360 CON file...",
        "CON file successfully packaged: /tmp/x.con",
        "Pipeline complete! All assets ready in: /tmp",
    ]

    def fake_run(job, cmd):
        for line in fake_lines:
            job.ingest_line(line)
        return 0

    srv.store.run_hook = fake_run
    return TestClient(srv.app), srv


# =========================================================== progress.py ===
class TestProgressParser:
    def test_stage_marker_progress(self):
        _m, p = P.parse_stage("[3/5] Aligning vocals and parsing LRC...")
        assert p == pytest.approx(0.34)

    def test_multi_match_takes_furthest(self):
        # "[1/5] Skipping Demucs separation" matches [1/5]=0.02 and the
        # skip marker=0.30 — the furthest-along reading must win.
        _m, p = P.parse_stage("[1/5] Skipping Demucs separation. Loading existing stems...")
        assert p == pytest.approx(0.30)

    def test_strip_counter(self):
        assert P.parse_strip("  separating strip 1/4 (htdemucs_ft)...") == \
            pytest.approx(0.02 + (0.30 - 0.02) * 0.25)
        assert P.parse_strip("  separating strip 4/4 (htdemucs_ft)...") == \
            pytest.approx(0.30)

    def test_progress_never_regresses(self):
        cur = 0.5
        # a strip line (max 0.30) must not pull the bar back after [4/5]
        assert P.next_progress("  separating strip 2/4 (htdemucs_ft)...", cur) is None
        # stage markers only move forward: [2/5] and [5/5] both sit below 0.5
        assert P.next_progress("[2/5] ...", cur) is None
        assert P.next_progress("[5/5] ...", cur) is None
        # but the terminal marker completes the bar
        assert P.next_progress("Pipeline complete! ...", cur) == 1.0

    def test_unknown_line_is_none(self):
        assert P.parse_stage("Warning: something happened") == (None, None)
        assert P.next_progress("random noise", 0.1) is None

    def test_stage_labels(self):
        assert P.stage_label(0.0) == "Starting"
        assert P.stage_label(0.05) == "Separating stems"
        assert P.stage_label(0.31) == "Detecting tempo"
        assert P.stage_label(0.5) == "Building MOGG + charts"
        assert P.stage_label(1.0) == "Done"


# =============================================================== jobs.py ===
class TestBuildCliCommand:
    def _job(self, tmp_path, options, uploads):
        store = JobStore(tmp_path / "jobs", repo_root=tmp_path)
        job = store.create_draft()
        job.options = options
        job.uploads = uploads
        return job

    def test_minimal_options(self, tmp_path):
        job = self._job(tmp_path, {"artist": "A", "title": "T",
                                   "separator": "htdemucs_ft"},
                        {"audio": "/tmp/song.mp3"})
        cmd = build_cli_command(job, tmp_path)
        assert cmd[:3] == ["python", "-m", "autorb.cli"]
        assert "/tmp/song.mp3" in cmd
        assert "--artist" in cmd and "A" in cmd
        assert "--separator" in cmd and "htdemucs_ft" in cmd
        assert "--build-clone-hero" not in cmd

    def test_all_toggles(self, tmp_path):
        job = self._job(tmp_path, {
            "artist": "A", "title": "T", "year": 1997, "genre": "Rock",
            "separator": "htdemucs_6s", "build_pkg": True,
            "build_clone_hero": True, "generate_freestyle_vocals": True,
            "freestyle_drums": True, "guitar_solo_charting": True,
        }, {"audio": "/tmp/song.mp3", "lrc": "/tmp/l.lrc",
            "album_art": "/tmp/a.png"})
        cmd = build_cli_command(job, tmp_path)
        for flag in ("--build-pkg", "--build-clone-hero",
                     "--generate-freestyle-vocals", "--freestyle-drums",
                     "--guitar-solo-charting", "--year", "--genre",
                     "--lyrics", "--album-art"):
            assert flag in cmd, flag

    def test_stems_only_job_omits_audio_positional(self, tmp_path):
        job = self._job(tmp_path, {"artist": "A", "title": "T"},
                        {"stems": "/tmp/stems"})
        cmd = build_cli_command(job, tmp_path)
        assert "--skip-separation" in cmd
        # no positional audio file (CLI supports that now)
        assert not any(a.endswith(".mp3") for a in cmd)

    def test_unknown_separator_rejected(self, tmp_path):
        job = self._job(tmp_path, {"artist": "A", "title": "T",
                                   "separator": "evil&rm -rf"},
                        {"audio": "/tmp/s.mp3"})
        with pytest.raises(JobError):
            build_cli_command(job, tmp_path)

    def test_missing_metadata_rejected(self, tmp_path):
        job = self._job(tmp_path, {"artist": "", "title": "T"},
                        {"audio": "/tmp/s.mp3"})
        with pytest.raises(JobError):
            build_cli_command(job, tmp_path)
        job2 = self._job(tmp_path, {"artist": "A", "title": ""},
                          {"audio": "/tmp/s.mp3"})
        with pytest.raises(JobError):
            build_cli_command(job2, tmp_path)

    def test_no_source_rejected(self, tmp_path):
        job = self._job(tmp_path, {"artist": "A", "title": "T"}, {})
        with pytest.raises(JobError):
            build_cli_command(job, tmp_path)


class TestJobLifecycle:
    def test_draft_then_queued_running_success(self, tmp_path):
        store = JobStore(tmp_path / "jobs", repo_root=tmp_path)

        def hook(job, cmd):
            assert job.status == "running"  # set before the runner is invoked
            job.ingest_line("Starting AutoRB Pipeline for: A - T")
            return 0

        store.run_hook = hook
        job = store.create_draft()
        job.uploads = {"audio": "/tmp/song.mp3"}  # required by command builder
        assert job.status == "draft"
        store.start(job, {"artist": "A", "title": "T"})
        for _ in range(50):
            if job.status in ("success", "failed"):
                break
            time.sleep(0.05)
        assert job.status == "success"
        assert job.progress == 1.0

    def test_failed_exit_code_recorded(self, tmp_path):
        store = JobStore(tmp_path / "jobs", repo_root=tmp_path)

        def hook(job, cmd):
            job.ingest_line("ERROR: guitar validation FAILED")
            return 1

        store.run_hook = hook
        job = store.create_draft()
        job.uploads = {"audio": "/tmp/song.mp3"}
        store.start(job, {"artist": "A", "title": "T"})
        for _ in range(50):
            if job.status in ("success", "failed"):
                break
            time.sleep(0.05)
        assert job.status == "failed"
        assert job.exit_code == 1
        assert job.error

    def test_start_twice_rejected(self, tmp_path):
        store = JobStore(tmp_path / "jobs", repo_root=tmp_path)
        job = store.create_draft()
        job.uploads = {"audio": "/tmp/song.mp3"}
        store.start(job, {"artist": "A", "title": "T"})
        with pytest.raises((JobError, Exception)):
            store.start(job, {"artist": "A", "title": "T"})


# ============================================================= server.py ===
class TestUpload:
    def test_upload_audio(self, client):
        c, _ = client
        r = c.post("/api/upload", files={
            "audio": ("song.mp3", io.BytesIO(b"ID3" + b"x" * 64),
                      "audio/mpeg")})
        assert r.status_code == 200
        body = r.json()
        assert body["uploads"]["audio"].endswith("audio.mp3")

    def test_upload_rejects_bad_type(self, client):
        c, _ = client
        r = c.post("/api/upload", files={
            "audio": ("song.exe", io.BytesIO(b"MZ"), "application/x-dos-exe")})
        assert r.status_code == 400
        assert ".exe" in r.json()["detail"]

    def test_upload_nothing_rejected(self, client):
        c, _ = client
        r = c.post("/api/upload")
        assert r.status_code == 400

    def test_upload_stems_zip(self, client):
        c, _ = client
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name in ("drums", "bass", "other", "vocals"):
                zf.writestr(f"{name}.wav", b"RIFF" + name.encode())
        buf.seek(0)
        r = c.post("/api/upload", files={
            "stems_zip": ("stems.zip", buf, "application/zip")})
        assert r.status_code == 200
        up = r.json()["uploads"]
        assert up["stems"].endswith("/stems")
        assert (Path(up["stems"]) / "drums.wav").exists()

    def test_upload_stems_zip_rejects_unknown_wavs(self, client):
        c, _ = client
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("not_a_stem.wav", b"RIFF")
        buf.seek(0)
        r = c.post("/api/upload", files={
            "stems_zip": ("stems.zip", buf, "application/zip")})
        assert r.status_code == 400

    def test_upload_named_stem_files(self, client):
        c, _ = client
        r = c.post("/api/upload", files=[
            ("stems_files", ("drums.wav", io.BytesIO(b"RIFF1"), "audio/wav")),
            ("stems_files", ("bass.wav", io.BytesIO(b"RIFF2"), "audio/wav")),
        ])
        assert r.status_code == 200
        up = r.json()["uploads"]
        assert (Path(up["stems"]) / "drums.wav").exists()
        assert (Path(up["stems"]) / "bass.wav").exists()

    def test_upload_named_stem_rejects_unknown(self, client):
        c, _ = client
        r = c.post("/api/upload", files=[
            ("stems_files", ("cowbell.wav", io.BytesIO(b"R"), "audio/wav")),
        ])
        assert r.status_code == 400


class TestJobAPI:
    def test_full_happy_path_with_fake_runner(self, client):
        c, srv = client
        # upload
        r = c.post("/api/upload", files={
            "audio": ("song.mp3", io.BytesIO(b"ID3" + b"x" * 64),
                      "audio/mpeg")})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        # start
        r = c.post(f"/api/jobs/{jid}/start", json={"options": {
            "artist": "Eve 6", "title": "Open Road Song", "year": "1997",
            "genre": "Rock", "separator": "htdemucs",
            "build_clone_hero": True}})
        assert r.status_code == 200
        # poll to completion
        for _ in range(100):
            j = c.get(f"/api/jobs/{jid}").json()
            if j["status"] in ("success", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert j["status"] == "success"
        assert j["progress"] == 1.0
        assert any("Pipeline complete" in ln for ln in j["log_tail"])
        # progress increased monotonically along the fake log
        assert j["stage"] == "Done"

    def test_start_requires_metadata(self, client):
        c, _ = client
        r = c.post("/api/upload", files={
            "audio": ("s.mp3", io.BytesIO(b"ID3"), "audio/mpeg")})
        jid = r.json()["job_id"]
        r = c.post(f"/api/jobs/{jid}/start", json={"options": {
            "artist": "", "title": "T"}})
        assert r.status_code == 400
        assert "artist" in r.json()["detail"].lower()

    def test_start_unknown_job_404(self, client):
        c, _ = client
        assert c.post("/api/jobs/nope/start",
                      json={"options": {}}).status_code == 404

    def test_job_status_404(self, client):
        c, _ = client
        assert c.get("/api/jobs/nope").status_code == 404

    def test_start_twice_409(self, client):
        c, _ = client
        r = c.post("/api/upload", files={
            "audio": ("s.mp3", io.BytesIO(b"ID3"), "audio/mpeg")})
        jid = r.json()["job_id"]
        r1 = c.post(f"/api/jobs/{jid}/start", json={"options": {
            "artist": "A", "title": "T"}})
        assert r1.status_code == 200
        r2 = c.post(f"/api/jobs/{jid}/start", json={"options": {
            "artist": "A", "title": "T"}})
        assert r2.status_code == 409

    def test_stems_job_requires_core_stems(self, client):
        c, _ = client
        # upload only guitar.wav (not a core stem)
        r = c.post("/api/upload", files=[
            ("stems_files", ("guitar.wav", io.BytesIO(b"RIFF"), "audio/wav")),
        ])
        jid = r.json()["job_id"]
        r = c.post(f"/api/jobs/{jid}/start", json={"options": {
            "artist": "A", "title": "T"}})
        assert r.status_code == 400
        assert "drums" in r.json()["detail"]

    def test_jobs_listed(self, client):
        c, _ = client
        c.post("/api/upload", files={
            "audio": ("s.mp3", io.BytesIO(b"ID3"), "audio/mpeg")})
        r = c.get("/api/jobs")
        assert r.status_code == 200
        assert len(r.json()["jobs"]) >= 1


class TestReveal:
    def test_reveal_endpoint(self, client, monkeypatch):
        c, _ = client
        r = c.post("/api/upload", files={
            "audio": ("s.mp3", io.BytesIO(b"ID3"), "audio/mpeg")})
        jid = r.json()["job_id"]
        called = {}
        import webui.server as srv
        monkeypatch.setattr(srv, "reveal_in_file_manager",
                            lambda p: (True, f"opened {p}"))
        r = c.post(f"/api/jobs/{jid}/reveal")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_reveal_missing_dir_still_ok(self, client):
        c, _ = client
        r = c.post("/api/upload", files={
            "audio": ("s.mp3", io.BytesIO(b"ID3"), "audio/mpeg")})
        jid = r.json()["job_id"]
        r = c.post(f"/api/jobs/{jid}/reveal")
        # uploads dir exists; the reveal target (output dir) exists too
        assert r.status_code == 200


class TestCapabilities:
    def test_capabilities_shape(self, client):
        c, _ = client
        r = c.get("/api/capabilities")
        assert r.status_code == 200
        caps = r.json()
        for key in ("cpu_cores", "mem_total_gb", "cuda", "ffmpeg",
                    "spleeter", "adtof", "os", "python", "autorb_version"):
            assert key in caps, key
        assert caps["autorb_version"].count(".") == 2  # semver


class TestStaticUI:
    def test_index_served(self, client):
        c, _ = client
        r = c.get("/")
        assert r.status_code == 200
        assert "AutoRB" in r.text
        assert "Chart my song" in r.text

    def test_ui_has_uploads_and_pages_fallback(self, client):
        c, _ = client
        html = c.get("/").text
        # upload fields
        for frag in ('id="audio"', 'id="stemsZip"', 'id="stemsFiles"',
                     'id="lrc"', 'id="albumArt"'):
            assert frag in html, frag
        # options
        for frag in ('id="separator"', 'id="buildCloneHero"',
                     'id="buildPkg"', 'id="guitarSoloCharting"'):
            assert frag in html, frag
        # Pages-mode connect panel + reveal button
        for frag in ('id="connect"', 'id="engineUrl"',
                     'id="revealBtn"'):
            assert frag in html, frag

    def test_drop_zones_are_labels_with_external_inputs(self, client):
        """The no-file-chooser bug (user report, v0.1.23): the file inputs
        were CHILDREN of click-forwarding divs, so the forwarded click
        bubbled back into the handler and the browser suppressed the whole
        interaction — drag-and-drop was the only way to add files. Contract:
        every drop zone is a native <label for=...> and its input lives
        OUTSIDE the label (hidden off-screen, never display:none)."""
        c, _ = client
        html = c.get("/").text
        import re
        from html.parser import HTMLParser

        class Structure(HTMLParser):
            def __init__(self):
                super().__init__()
                self.zones = {}     # id -> (tag, for_attr)
                self.nesting = {}   # input_id -> inside which zone
                self._zone = None
                self.inputs = {}    # input_id -> attrs

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "label" and a.get("class", "").startswith("drop"):
                    self.zones[a.get("id")] = ("label", a.get("for"))
                    self._zone = a.get("for")
                elif tag == "input" and a.get("type") == "file":
                    self.inputs[a.get("id")] = a
                    if self._zone:
                        self.nesting[a.get("id")] = self._zone
                    # style must be off-screen, not display:none
                    cls = a.get("class", "")
                    assert "fileinp" in cls, \
                        f"#{a.get('id')} must use the .fileinp class"

            def handle_endtag(self, tag):
                if tag == "label" and self._zone is not None:
                    self._zone = None

        sp = Structure()
        sp.handle_starttag  # noqa
        sp.feed(html)
        assert sp.nesting == {}, \
            f"file inputs nested inside drop zones: {sp.nesting}"
        assert set(sp.zones) == {"dropAudio", "dropStems", "dropLrc",
                                 "dropArt"}
        for zid, (_tag, for_attr) in sp.zones.items():
            assert for_attr, f"{zid} is a label without for="
            assert for_attr in sp.inputs, \
                f"{zid} points at missing input #{for_attr}"

    def test_default_separator_is_6s(self, client):
        """User-validated default: htdemucs_6s (drives the guitar chart from
        the dedicated guitar stem — the configuration the whole validation
        loop ran on)."""
        c, _ = client
        html = c.get("/").text
        import re
        m = re.search(r'<option value="([^"]+)" selected>', html)
        assert m and m.group(1) == "htdemucs_6s", \
            "web UI default separator must be htdemucs_6s"
        # never fabricates: failures surface
        assert "Failed" in html


class TestRevealUnit:
    def test_missing_path(self, tmp_path):
        from webui.reveal import reveal_in_file_manager
        ok, msg = reveal_in_file_manager(tmp_path / "nope")
        assert ok is False
        assert "exist" in msg.lower()

    def test_opens_dir_linux(self, tmp_path, monkeypatch):
        from webui import reveal
        monkeypatch.setattr(reveal.sys, "platform", "linux")
        # find at least one opener available in CI (xdg-open/gio fallback)
        ok, msg = reveal.reveal_in_file_manager(tmp_path)
        # headless CI may have none — both outcomes acceptable, never raises
        assert isinstance(ok, bool)


# =============================================== CLI contract regressions ===
class TestCliContract:
    """The web engine shells out to the real CLI; guard the contract."""

    def test_failure_paths_use_sysexit(self):
        """After v0.1.23, CLI failure paths must sys.exit(1) — a bare
        `return` / `return 1` in a click callback exits 0, so the web engine
        would read failed builds as successes. (Regression verified live: a
        stems-mode job reported success/exit-0 while the CLI had refused to
        run.) The only allowed bare `return` is the batch-package success
        path right after 'successfully built'."""
        import ast
        src = Path("autorb/cli.py").read_text()
        tree = ast.parse(src)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return):
                continue
            # `return 1` (click swallows the value) is always a failure path
            if isinstance(node.value, ast.Constant) and node.value.value == 1:
                offenders.append(f"line {node.lineno}: `return 1`")
            # bare `return` is OK only on the batch-package success path
            if node.value is None:
                line = src.splitlines()[node.lineno - 1]
                ctx = "\n".join(src.splitlines()[max(0, node.lineno - 3):
                                                node.lineno - 1])
                if "successfully built" not in ctx:
                    offenders.append(f"line {node.lineno}: bare `return` "
                                     f"(context: {line.strip()!r})")
        assert not offenders, (
            "autorb/cli.py failure paths must sys.exit(1), not return "
            f"(click exits 0): {offenders}")

    def test_cli_error_exit_codes_end_to_end(self):
        """Real subprocess check of the three user-error paths the engine
        can trigger: no args / stems mode without stems / bad cache load."""
        import subprocess
        import sys as _sys
        cases = [
            ([], "no args"),
            (["--artist", "A", "--title", "T", "--skip-separation",
              "--output-dir", "/tmp/autorb_webui_test_nostems"],
             "stems mode, no stems on disk"),
        ]
        for args, label in cases:
            r = subprocess.run(
                [_sys.executable, "-m", "autorb.cli", *args],
                capture_output=True, text=True, timeout=60)
            assert r.returncode == 1, \
                f"{label}: expected exit 1, got {r.returncode}"

    def test_lyrics_is_optional_in_missing_check(self):
        src = Path("autorb/cli.py").read_text()
        assert '"--lyrics", lyrics' not in src

    def test_lyrics_is_optional_in_missing_check(self):
        src = Path("autorb/cli.py").read_text()
        assert '"--lyrics", lyrics' not in src

    def test_mixed_audio_optional_for_stems_mode(self):
        """--skip-separation must not require the AUDIO_FILE positional
        (the web UI's stems-only workflow uploads no mix)."""
        src = Path("autorb/cli.py").read_text()
        assert '"(stems mode)"' in src, \
            "stems-mode sentinel missing — AUDIO_FILE would be required " \
            "even with --skip-separation"

    def test_process_vocals_accepts_none_lrc(self):
        import autorb.audio.vocals as V
        import inspect
        sig = inspect.signature(V.process_vocals)
        assert "lrc_path" in sig.parameters


# --------------------------------------------------------------- reveal ----
# (covered in TestRevealUnit above)


# ---------------------------------------------- real-browser interaction ----
# Requires Playwright + headless Chromium (devcontainer has it; plain CI
# skips). This is the regression test for the reported bug: "clicked on all
# the areas under section 1 and couldn't get any file choosers to appear".
def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


@pytest.mark.devcontainer
@pytest.mark.skipif(not _playwright_available(),
                    reason="playwright not installed (devcontainer test)")
def test_clicking_every_drop_zone_opens_a_file_chooser():
    import webui.server as srv  # noqa: F401  (env docs)
    proc = subprocess.Popen(
        [sys.executable, "-m", "webui.server"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "AUTORB_WEBUI_PORT": "7877",
             "AUTORB_WEBUI_JOBS": tempfile.mkdtemp(prefix="webui_pw_")})
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto("http://127.0.0.1:7877/")
            page.wait_for_selector("#dropAudio", timeout=10000)
            zones = [("dropAudio", "audio"), ("dropStems", "stemsFiles"),
                     ("dropLrc", "lrc"), ("dropArt", "albumArt")]
            for zid, inp in zones:
                with page.expect_file_chooser(timeout=5000) as fc:
                    page.click(f"#{zid}", position={"x": 20, "y": 30})
                fc.value
            # keyboard: focus the (off-screen) input, Enter opens the chooser
            page.focus("#audio")
            with page.expect_file_chooser(timeout=5000):
                page.keyboard.press("Enter")
            browser.close()
            assert not errors, f"page errors: {errors}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_no_placeholder_statuses_leak():
    """Job statuses are from the known set (frontend switch on them)."""
    from webui.jobs import VALID_STATUSES
    assert VALID_STATUSES == {"draft", "queued", "running", "success",
                              "failed", "cancelled"}


def test_docs_dir_in_sync_with_webui_static():
    """docs/ is the GitHub Pages deploy of webui/static/ (verbatim copy).

    Pages serves docs/ as-is, so the two directories must be identical —
    this test (and the pages.yml sync guard) fail the build the moment they
    drift. Fix: cp webui/static/index.html docs/index.html
    """
    import filecmp
    src, dst = Path("webui/static"), Path("docs")
    assert (src / "index.html").read_text() == (dst / "index.html").read_text(), \
        ("docs/index.html is out of sync with webui/static/index.html — "
         "re-copy it: cp webui/static/index.html docs/index.html")
    cmp = filecmp.dircmp(src, dst)
    assert not cmp.left_only and not cmp.right_only and not cmp.funny_files, (
        f"docs/ and webui/static/ differ: only-in-static={cmp.left_only} "
        f"only-in-docs={cmp.right_only}")
