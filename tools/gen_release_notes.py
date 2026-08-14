#!/usr/bin/env python3
"""Generate the user-facing release notes for AutoRB.

Composes release notes from two sources of truth:
  * the CHANGELOG.md entry for the current version (a "What's Changed in this release" section), and
  * the user-facing README.md sections (features, known limitations, roadmap,
    installation/how-to, quick start, previewing, master stems).

The result is used two ways:
  * as the GitHub Release body — the CI workflow runs this with --out RELEASE_BODY.md, and
  * bundled inside the wheel/sdist archive as RELEASE_NOTES.txt, so anyone who downloads the
    archive gets the same helpful "what is this and how do I use it" content without a browser.

Run from the repo root:  python tools/gen_release_notes.py [--tag v0.0.91test02]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
VERSION_FILE = REPO_ROOT / "autorb" / "version.py"

# User-facing README sections (matched by heading text; emoji prefixes are allowed),
# in the order they appear in the release notes. The internal sections (Architecture
# & Pipeline, the duplicate "Usage" block, Development/Testing, Project Structure,
# Disclaimer) are deliberately excluded.
README_SECTIONS = [
    "Key Features",
    "Known Limitations",
    "Next Steps / Roadmap",
    "Installation & Getting Started (Fresh Users)",
    "Quick Start & Usage",
    "Previewing Results",
    "Using Original Master Stems (For Bands/Artists)",
]

HEADING_RE = re.compile(r"^(#{2,3})[ \t]+(.*)$")


def current_version() -> str:
    ns: dict[str, str] = {}
    exec(VERSION_FILE.read_text(encoding="utf-8"), ns)
    return ns["__version__"]


def changelog_section(version: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not m:
        sys.stderr.write(f"error: no CHANGELOG entry for [{version}] — add one before tagging\n")
        sys.exit(1)
    return m.group(1).strip()


def readme_section(wanted: str) -> str:
    """Return a top-level README section (all its ### subsections included)."""
    lines = README.read_text(encoding="utf-8").splitlines()
    top = []
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group(1) == "##":
            top.append((i, m.group(2).strip()))
    for idx, (lineno, text) in enumerate(top):
        if text == wanted or text.endswith(wanted):
            end = top[idx + 1][0] if idx + 1 < len(top) else len(lines)
            return "\n".join(lines[lineno:end])
    sys.stderr.write(f"warning: README section {wanted!r} not found — skipping\n")
    return ""


def build(version: str, tag: str | None) -> str:
    header = [f"# AutoRB {version}"]
    if tag and tag != f"v{version}":
        header.append(f"*(test release — tag {tag})*")
    header += [
        "",
        "Automated Rock Band 3 CON & PS4 PKG Generator using Machine Learning & Signal Processing.",
    ]
    body = "\n".join(header)
    body += "\n\n---\n\n## What's Changed in this release\n\n" + changelog_section(version)
    for section in README_SECTIONS:
        chunk = readme_section(section)
        if chunk:
            body += "\n\n---\n\n" + chunk
    body += (
        "\n\n---\n\n"
        "Full documentation, troubleshooting, and the changelog live in the repository: "
        "https://github.com/free5ty1e/RockBandAutoSongLevelCreator (README.md / CHANGELOG.md)."
    )
    return body


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="RELEASE_NOTES.txt", help="output path (default: RELEASE_NOTES.txt)")
    ap.add_argument("--tag", default=None, help="git tag (e.g. v0.0.91test02) — shown as a test-release note")
    ap.add_argument("--version", default=None, help="version to document (default: autorb/version.py)")
    args = ap.parse_args()
    version = args.version or current_version()
    out = REPO_ROOT / args.out
    out.write_text(build(version, args.tag), encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT)} for AutoRB {version}")


if __name__ == "__main__":
    main()
