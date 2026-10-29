"""Contract tests for the research tooling (v0.1.40).

Pins the devcontainer bake-in so the research workflow survives rebuilds:
the research dependency file exists and stays OUT of the shipped dependency
set, and post-install installs it + builds the CON extractor.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_research_requirements_exist_and_are_separate():
    req = (REPO / "requirements-research.txt").read_text()
    assert "yt-dlp" in req and "pyguitarpro" in req
    # never shipped: the core requirements and pyproject must NOT gain these
    core = (REPO / "requirements.txt").read_text().lower()
    assert "yt-dlp" not in core and "pyguitarpro" not in core
    pyproject = (REPO / "pyproject.toml").read_text()
    m = re.search(r"^dependencies = \[(.*?)^\]", pyproject, re.S | re.M)
    assert m and "yt-dlp" not in m.group(1) and "guitarpro" not in m.group(1)


def test_post_install_wires_research_tooling():
    post = (REPO / ".devcontainer" / "post-install.sh").read_text()
    assert "requirements-research.txt" in post, \
        "post-install must install the research deps (survive rebuilds)"
    assert "con_extract" in post and "mcs" in post, \
        "post-install must build the official-CON extractor"


def test_kb_documents_the_research_tooling():
    kb = (REPO / "llm-wiki-kb" / "research_tooling.md").read_text()
    idx = (REPO / "llm-wiki-kb" / "index.md").read_text()
    for needle in ("con_extract", "dlc_ground_truth", "rb_song_matcher",
                   "lrclib", "requirements-research.txt"):
        assert needle in kb, f"research_tooling KB lost: {needle}"
    assert "[[research_tooling]]" in idx, "KB index must list research_tooling"
    readme = (REPO / "README.md").read_text()
    assert "dlc_ground_truth" in readme and "rb_song_matcher" in readme, \
        "README must document the research tools"
