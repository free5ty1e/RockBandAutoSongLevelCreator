"""Tests for the charting-accuracy reference-tab stage (v0.1.37).

Covers: Tier-1 Songsterr search scoring (offline, injected fetch), the
GPX-download attempt logic (PK-zip acceptance, JSON-error rejection), the
stage end-to-end (report.json contract, Tier-0 user-supplied staging,
non-fatal offline behavior), and the WEB UI DISCLAIMER GATE (fetch_tabs
requires tabs_disclaimer_ack; the flag must flow to the CLI command).
"""

import json
from pathlib import Path

import pytest

from autorb.reference.tab_fetch import (
    SONGSTERR_SEARCH_URL,
    TabCandidate,
    attempt_gpx_download,
    run_tab_fetch_stage,
    search_songsterr,
)
from webui.jobs import JobError, JobStore, build_cli_command

# ---------------------------------------------------------------- fixtures

_SEARCH_FIXTURE = json.dumps([
    {"songId": 68042, "artist": "Eve 6", "title": "Open Road Song",
     "hasChords": False,
     "tracks": [{"instrumentId": 30, "instrument": "Distortion Guitar",
                 "difficulty": 4, "tuning": [64, 59, 55, 50, 45, 40],
                 "hash": "guitar_abc123"}]},
    {"songId": 111, "artist": "Cover Band", "title": "Open Road Song (Live)",
     "tracks": []},
    {"songId": 222, "artist": "Someone Else", "title": "Totally Different",
     "tracks": []},
]).encode("utf-8")

_GPX_ZIP = b"PK\x03\x04" + b"\x00" * 64  # plausible GPX (zip container)
_JSON_ERROR = b'{"code":"ERR_NOT_FOUND","error":"Not Found"}'


def _fixture_http(url, fail_urls=()):
    """Injected fetch: search API -> fixture; GPX URLs -> gated JSON error."""
    def fetch(u, timeout=15):
        if u in fail_urls:
            return None
        if u.startswith("https://www.songsterr.com/api/songs"):
            return _SEARCH_FIXTURE
        return _JSON_ERROR
    return fetch


# ------------------------------------------------------- candidate scoring

class TestSearchSongsterr:
    def test_exact_match_scores_highest_and_first(self):
        cands = search_songsterr("Eve 6", "Open Road Song",
                                  http_get=_fixture_http("x"))
        assert cands and cands[0].song_id == 68042
        assert cands[0].score == 1.0
        assert cands[0].guitar_tracks[0]["hash"] == "guitar_abc123"

    def test_unrelated_results_are_dropped(self):
        cands = search_songsterr("Eve 6", "Open Road Song",
                                  http_get=_fixture_http("x"))
        assert all(c.song_id != 222 for c in cands)

    def test_partial_match_survives_below_exact(self):
        cands = search_songsterr("Eve 6", "Open Road Song",
                                  http_get=_fixture_http("x"))
        # the cover band matches the title only -> kept, but below the exact hit
        assert [c.song_id for c in cands][:1] == [68042]
        assert 111 in [c.song_id for c in cands]

    def test_offline_returns_empty(self):
        assert search_songsterr("A", "B", http_get=lambda u, t=15: None) == []

    def test_bad_json_returns_empty(self):
        assert search_songsterr("A", "B",
                                http_get=lambda u, t=15: b"not json") == []


# ------------------------------------------------------------ GPX download

class TestGpxDownload:
    def test_gated_site_yields_no_file(self, tmp_path):
        # Songsterr answers known-pattern misses with a JSON error body —
        # that must NOT be saved as a tab.
        got = attempt_gpx_download(68042, "guitar_abc123",
                                   tmp_path / "out.gpx",
                                   http_get=lambda u, t=15: _JSON_ERROR)
        assert got is None
        assert not (tmp_path / "out.gpx").exists()

    def test_zip_container_is_saved(self, tmp_path):
        def fetch(u, timeout=15):
            return _GPX_ZIP if ".gpx" in u or "/tab/" in u or u.endswith("abc123") else None
        got = attempt_gpx_download(68042, "guitar_abc123",
                                    tmp_path / "out.gpx", http_get=fetch)
        assert got is not None and got.read_bytes()[:2] == b"PK"


# ------------------------------------------------------------------- stage

class TestRunTabFetchStage:
    def test_report_contract_and_tier0_staging(self, tmp_path):
        tab = tmp_path / "mytab.gp5"
        tab.write_bytes(b"fake gp5")
        report = run_tab_fetch_stage(
            "Eve 6", "Open Road Song", tmp_path / "out",
            user_tabs=[tab], http_get=_fixture_http("x"))
        rp = tmp_path / "out" / "reference_tabs" / "report.json"
        assert rp.exists()
        on_disk = json.loads(rp.read_text())
        assert on_disk["schema"] == "autorb-reference-tabs/1"
        assert on_disk["best_match"]["song_id"] == 68042
        assert on_disk["status"] == "found_no_download"  # search hits, GPX gated
        # Tier 0: the user file was staged, not consumed
        staged = tmp_path / "out" / "reference_tabs" / "mytab.gp5"
        assert staged.exists() and staged.read_bytes() == b"fake gp5"
        assert on_disk["user_supplied"][0]["name"] == "mytab.gp5"
        assert report == on_disk

    def test_offline_is_nonfatal_and_reported(self, tmp_path):
        report = run_tab_fetch_stage("A", "B", tmp_path / "out",
                                     http_get=lambda u, t=15: None)
        assert report["status"] == "offline"
        assert (tmp_path / "out" / "reference_tabs" / "report.json").exists()

    def test_not_found_when_no_candidate_scores(self, tmp_path):
        def fetch(u, timeout=15):
            if u.startswith("https://www.songsterr.com/api/songs"):
                return json.dumps([{"songId": 9, "artist": "X", "title": "Y",
                                    "tracks": []}]).encode()
            return None
        report = run_tab_fetch_stage("Eve 6", "Open Road Song",
                                     tmp_path / "out", http_get=fetch)
        assert report["status"] == "not_found"

    def test_download_success_path(self, tmp_path):
        def fetch(u, timeout=15):
            if u.startswith("https://www.songsterr.com/api/songs"):
                return _SEARCH_FIXTURE
            return _GPX_ZIP
        report = run_tab_fetch_stage("Eve 6", "Open Road Song",
                                     tmp_path / "out", http_get=fetch)
        assert report["status"] == "found"
        assert report["downloads"]["guitar_abc123"]["path"].endswith(".gpx")

    def test_no_metadata_skips_fetch(self, tmp_path):
        report = run_tab_fetch_stage("", "", tmp_path / "out",
                                     http_get=_fixture_http("x"))
        assert report["status"] == "no_metadata"

    def test_missing_user_tab_noted_not_fatal(self, tmp_path):
        report = run_tab_fetch_stage(
            "Eve 6", "Open Road Song", tmp_path / "out",
            user_tabs=[tmp_path / "ghost.gp5"],
            http_get=_fixture_http("x"))
        assert any("missing" in n for n in report["notes"])
        assert not (tmp_path / "out" / "reference_tabs" / "ghost.gp5").exists()


# ------------------------------------------------------ the web-UI gate

class TestFetchTabsDisclaimerGate:
    """Opt-in web tab search requires the copyright disclaimer ack (user
    decision 2026-10-24): no ack -> 400 JobError; ack flows to the CLI flag."""

    def _opts(self, **extra):
        from webui.server import _normalize_options
        raw = {"artist": "A", "title": "T", "separator": "htdemucs_ft"}
        raw.update(extra)
        return _normalize_options(raw)

    def test_fetch_tabs_requires_ack(self):
        with pytest.raises(JobError):
            self._opts(fetch_tabs=True)

    def test_fetch_tabs_with_ack(self):
        opts = self._opts(fetch_tabs=True, tabs_disclaimer_ack=True)
        assert opts["fetch_tabs"] is True

    def test_default_off(self):
        assert self._opts()["fetch_tabs"] is False
        # an ack alone never enables fetching
        assert self._opts(tabs_disclaimer_ack=True)["fetch_tabs"] is False

    def test_flag_reaches_cli_command(self, tmp_path):
        store = JobStore(tmp_path / "jobs", repo_root=tmp_path)
        job = store.create_draft()
        job.options = {"artist": "A", "title": "T",
                       "separator": "htdemucs_ft", "fetch_tabs": True}
        job.uploads = {"audio": "/tmp/song.mp3"}
        assert "--fetch-tabs" in build_cli_command(job, tmp_path)
        job.options["fetch_tabs"] = False
        assert "--fetch-tabs" not in build_cli_command(job, tmp_path)
