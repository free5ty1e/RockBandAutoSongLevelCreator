#!/usr/bin/env python3
"""CI guard: the GitHub Pages site is a self-contained LANDING PAGE.

Architecture (v0.1.34): the live control panel runs on the user's own
machine, served by the engine at http://127.0.0.1:7860 — same-origin, no
browser restrictions. The Pages site (https://free5ty1e.github.io/...) is a
static landing page with install/launch instructions pointing there.

WHY not a copy of the engine UI: browsers' Private Network Access policy
denies a public https origin (Pages) permission to reach the `loopback`
address space — Chrome logs "Permission was denied for this request to
access the loopback address space" and uvicorn's CORS middleware answers
the PNA preflight with "400 Disallowed CORS private-network". A Pages copy
of the UI could therefore NEVER connect to a local engine; shipping it
produced a control panel that just showed "connect to your engine" forever.

This check runs in the Pages deploy workflow (and as a pytest).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LANDING = REPO / "docs" / "index.html"
ENGINE_UI = REPO / "webui" / "static" / "index.html"


def check() -> list[str]:
    problems: list[str] = []
    if not LANDING.exists():
        return [f"missing {LANDING}"]
    html = LANDING.read_text(encoding="utf-8")

    # 1. Must NOT be a stale copy of the engine UI: the engine UI contains
    #    the engine-calling JS the landing page must not have.
    if html == ENGINE_UI.read_text(encoding="utf-8"):
        problems.append(
            "docs/index.html is a copy of the engine UI — it can never "
            "connect to a loopback engine from the https Pages origin "
            "(Private Network Access). Rewrite it as the landing page.")
    for marker in ("api(\"POST\", \"/api/jobs", "ON_PAGES", "127.0.0.1:7860/api/"):
        if marker in html:
            problems.append(
                f"landing page contains engine-calling code ({marker!r}) — "
                "the Pages origin is blocked from loopback by PNA; the "
                "landing page must only INSTRUCT, not connect")

    # 2. Must point users at the engine's own UI.
    if "http://127.0.0.1:7860" not in html:
        problems.append("landing page must name the engine UI address "
                        "(http://127.0.0.1:7860)")
    # 3. Must carry the install/launch instructions.
    for needle in ("pip install", "webui.server", "autorb-webui"):
        if needle not in html:
            problems.append(f"landing page missing instruction fragment "
                           f"{needle!r}")
    # 4. Sanity: valid enough HTML with a title.
    if not re.search(r"<title>.+</title>", html):
        problems.append("landing page has no <title>")

    return problems


def main() -> int:
    problems = check()
    for p in problems:
        print(f"::error::{p}")
    if problems:
        return 1
    print("docs/index.html landing page OK "
          "(instructions only, no engine-calling code)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
