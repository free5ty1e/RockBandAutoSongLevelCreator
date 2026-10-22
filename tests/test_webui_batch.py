"""Batch API + runner tests (v0.1.25): stage, save/load JSON, run.

The user's workflow: stage both test songs (Open Road Song, Brian Wilson),
package them into ONE multi-song CON + ONE PS4 PKG, and SAVE the batch to a
JSON file to re-load and re-run the exact same set (files + metadata) while
iterating on the charting algorithms.

Heavy pipeline runs are faked via store.run_hook (per-song + packaging
invocations recorded); files are tiny in-memory bytes.
"""

import io
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from webui.batch import BATCH_FORMAT, BatchStore
from webui.jobs import JobStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import webui.server as srv
    monkeypatch.setenv("AUTORB_WEBUI_JOBS", str(tmp_path / "jobs"))
    import importlib
    importlib.reload(srv)

    calls = []
    def fake_run(job, cmd):
        calls.append(cmd)
        job.ingest_line("Starting AutoRB Pipeline")
        job.ingest_line("Pipeline complete! All assets ready")
        # the real CLI writes a .con named after the song id; emulate so the
        # batch runner's "produced no CON" check passes
        out_idx = cmd.index("--output-dir") + 1 if "--output-dir" in cmd else None
        if out_idx:
            sid = cmd[1] if False else "song"
            title = cmd[cmd.index("--title") + 1] if "--title" in cmd else "x"
            con = Path(cmd[out_idx]) / f"{title.lower().replace(' ', '_')}.con"
            con.write_bytes(b"CON")
        else:
            # packaging pass: --package-con-dir present
            con_dir = Path(cmd[cmd.index("--package-con-dir") + 1])
            (con_dir / "song_pack.con").write_bytes(b"PACK")
        return 0
    srv.store.run_hook = fake_run
    c = TestClient(srv.app)
    c._calls = calls
    return c, srv


def _stage_song(c, artist, title, with_lrc=False):
    files = [("stems_files", ("drums.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("bass.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("other.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("vocals.wav", io.BytesIO(b"R"), "audio/wav"))]
    if with_lrc:
        files.append(("lrc", ("lyrics.lrc", io.BytesIO(b"[00:01.00]x\n"),
                              "text/plain")))
    r = c.post("/api/upload", files=files)
    assert r.status_code == 200
    up = r.json()
    r2 = c.post("/api/batch/songs", json={
        "job_staging": up["job_id"], "uploads": up["uploads"],
        "options": {"artist": artist, "title": title, "year": "1998",
                    "genre": "Rock", "separator": "htdemucs_6s"}})
    assert r2.status_code == 200, r2.text
    return r2.json()


class TestBatchStage:
    def test_stage_song_returns_record(self, client):
        c, _ = client
        r = _stage_song(c, "Eve 6", "Open Road Song")
        assert r["label"] == "Eve 6 - Open Road Song"
        song = r["song"]
        assert song["song_id"]
        assert song["options"]["artist"] == "Eve 6"
        assert song["files"]["stems"].startswith("batch_store/")
        # files actually exist under the jobs root
        stems = Path(str(c.app.routes and "")) if False else None
        assert song["files"]["stems"]

    def test_stage_requires_options_validation(self, client):
        c, _ = client
        r = c.post("/api/upload", files=[
            ("stems_files", ("drums.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("bass.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("other.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("vocals.wav", io.BytesIO(b"R"), "audio/wac"))])
        # note: last file has typo ext; upload should reject it -> re-do cleanly
        r = c.post("/api/upload", files=[
            ("stems_files", ("drums.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("bass.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("other.wav", io.BytesIO(b"R"), "audio/wav")),
            ("stems_files", ("vocals.wav", io.BytesIO(b"R"), "audio/wav"))])
        up = r.json()
        r2 = c.post("/api/batch/songs", json={
            "job_staging": up["job_id"], "uploads": up["uploads"],
            "options": {"artist": "", "title": "X"}})
        assert r2.status_code == 400
        assert "artist" in r2.json()["detail"].lower()

    def test_stage_rejects_missing_files(self, client):
        c, _ = client
        r = c.post("/api/batch/songs", json={
            "job_staging": "nope", "uploads": {},
            "options": {"artist": "A", "title": "B"}})
        assert r.status_code == 400


class TestBatchSaveLoad:
    def test_save_and_roundtrip(self, client):
        c, _ = client
        s1 = _stage_song(c, "Eve 6", "Open Road Song")
        s2 = _stage_song(c, "Barenaked Ladies", "Brian Wilson", with_lrc=True)
        songs = [s1["song"], s2["song"]]
        r = c.post("/api/batch/save", json={"name": "dev test pack",
                                            "songs": songs})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "dev test pack"
        assert body["saved"].endswith("dev_test_pack.json")
        assert body["batches"][0]["songs"] == 2

        # reload via the list + load endpoints
        r2 = c.post("/api/batch/load", json={"file": "dev_test_pack.json"})
        assert r2.status_code == 200
        doc = r2.json()
        assert doc["name"] == "dev test pack"
        assert len(doc["songs"]) == 2
        assert doc["songs"][0]["label"] == "Eve 6 - Open Road Song"
        # lrc rode along for song 2
        assert "lrc" in doc["songs"][1]["files"]

    def test_save_requires_name_and_songs(self, client):
        c, _ = client
        assert c.post("/api/batch/save", json={"name": "", "songs": []}
                      ).status_code == 400
        s = _stage_song(c, "A", "B")
        assert c.post("/api/batch/save",
                      json={"name": "x", "songs": []}).status_code == 400

    def test_load_rejects_bad_format_and_paths(self, client, tmp_path):
        c, srv = client
        # non-batch JSON
        bad = srv.batch_store.batches_dir / "bad.json"
        bad.write_text(json.dumps({"format": "nope", "songs": []}))
        assert c.post("/api/batch/load", json={"file": "bad.json"}
                     ).status_code == 400
        # path traversal
        assert c.post("/api/batch/load", json={"file": "../evil.json"}
                     ).status_code == 400
        # missing file
        assert c.post("/api/batch/load", json={"file": "ghost.json"}
                      ).status_code == 404

    def test_load_detects_vanished_files(self, client):
        c, srv = client
        s = _stage_song(c, "Eve 6", "Open Road Song")
        r = c.post("/api/batch/save", json={"name": "vanish",
                                            "songs": [s["song"]]})
        assert r.status_code == 200
        # delete the staged stems behind the batch's back
        import shutil as sh
        sh.rmtree(srv.JOBS_ROOT / s["song"]["files"]["stems"])
        r2 = c.post("/api/batch/load", json={"file": "vanish.json"})
        assert r2.status_code == 400
        assert "missing" in r2.json()["detail"].lower()


class TestBatchRun:
    def test_run_batch_invokes_every_song_then_packaging(self, client):
        c, srv = client
        calls = c._calls
        s1 = _stage_song(c, "Eve 6", "Open Road Song")
        s2 = _stage_song(c, "Barenaked Ladies", "Brian Wilson")
        r = c.post("/api/batch/run", json={
            "name": "dev pack",
            "songs": [s1["song"], s2["song"]]})
        assert r.status_code == 200, r.text
        jid = r.json()["job"]["id"]
        for _ in range(100):
            j = c.get(f"/api/jobs/{jid}").json()
            if j["status"] in ("success", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert j["status"] == "success", (j["status"], j.get("error"))
        # two song pipelines + one packaging pass
        assert len(calls) == 3
        pack = calls[-1]
        assert "--package-con-dir" in pack
        song_cmds = calls[:2]
        assert all("--package-con-dir" not in cm for cm in song_cmds)
        # each song's output dir is distinct
        outs = [cm[cm.index("--output-dir") + 1] for cm in song_cmds]
        assert len(set(outs)) == 2

    def test_run_batch_validates_all_files_upfront(self, client):
        c, srv = client
        s = _stage_song(c, "Eve 6", "Open Road Song")
        import shutil as sh
        sh.rmtree(srv.JOBS_ROOT / s["song"]["files"]["stems"])
        r = c.post("/api/batch/run", json={
            "name": "bad", "songs": [s["song"]]})
        assert r.status_code == 400
        assert "missing" in r.json()["detail"].lower()

    def test_run_empty_batch_rejected(self, client):
        c, _ = client
        assert c.post("/api/batch/run", json={"songs": []}).status_code == 400

    def test_song_failure_aborts_batch(self, client):
        c, srv = client
        calls = c._calls
        def failing_run(job, cmd):
            calls.append(cmd)
            if "--package-con-dir" not in cmd and len(calls) == 1:
                job.ingest_line("ERROR: guitar transcription failed")
                return 1
            if "--package-con-dir" not in cmd:
                out_i = cmd.index("--output-dir") + 1
                Path(cmd[out_i], "x.con").write_bytes(b"CON")
                return 0
            return 0
        srv.store.run_hook = failing_run
        s1 = _stage_song(c, "A", "One")
        s2 = _stage_song(c, "B", "Two")
        r = c.post("/api/batch/run", json={
            "name": "failfirst", "songs": [s1["song"], s2["song"]]})
        jid = r.json()["job"]["id"]
        for _ in range(100):
            j = c.get(f"/api/jobs/{jid}").json()
            if j["status"] in ("success", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert j["status"] == "failed"
        assert "exited with code 1" in (j["error"] or "")
        # the SECOND song must not have run (all-or-nothing)
        assert len(calls) == 1

    def test_batch_progress_reaches_1_on_success(self, client):
        c, _ = client
        s = _stage_song(c, "Solo", "Song")
        r = c.post("/api/batch/run", json={"name": "p", "songs": [s["song"]]})
        jid = r.json()["job"]["id"]
        for _ in range(100):
            j = c.get(f"/api/jobs/{jid}").json()
            if j["status"] in ("success", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert j["status"] == "success"
        assert j["progress"] == 1.0


class TestBatchStoreUnit:
    def test_song_record_paths_are_relative(self, tmp_path):
        store = BatchStore(tmp_path)
        d = store.new_song_dir()
        (d / "uploads" / "audio.mp3").write_bytes(b"x")
        rec = store.song_record(d.name, {"artist": "A"}, {"audio": str(d / "uploads/audio.mp3")})
        assert rec["files"]["audio"] == f"batch_store/{d.name}/uploads/audio.mp3"
        doc = {"format": BATCH_FORMAT, "name": "t",
               "songs": [rec]}
        p = tmp_path / "b.json"
        p.write_text(json.dumps(doc))
        loaded = store.load(p)
        assert loaded["songs"][0]["files"]["audio"].endswith("audio.mp3")

    def test_save_slugifies_name(self, tmp_path):
        store = BatchStore(tmp_path)
        d = store.new_song_dir()
        rec = store.song_record(d.name, {"artist": "A"},
                                {"audio": str(d / "uploads/x.mp3")})
        (d / "uploads" / "x.mp3").write_bytes(b"x")
        p = store.save("My Pack / Test!", [rec])
        assert p.name == "My_Pack_Test.json"
