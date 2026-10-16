---
title: Release Process, Validation, and Auditing
date: 2026-10-15
---
# Release Process, Validation, and Auditing

How AutoRB releases are built, what must be true before tagging, how the
build is validated, and how to audit the finished release. Established
v0.1.31 after the **v0.1.30-alpha01 incident**: that tag's CI build
failed (no GitHub release was ever published) because `crepe` — a
dependency never imported anywhere — uses `pkg_resources` during its own
install, which breaks every fresh environment under setuptools≥82. The
devcontainer masked it by having crepe pre-installed. Nobody noticed for
two days until the user asked for an artifact audit.

See also: `[[architecture]]` § Release Packaging (wheel naming, Python
range), `[[log]]` 2026-10-14 for the incident record.

## The release pipeline (what happens on a tag)

`.github/workflows/ci-cd.yml`, on `push` of a `v*` tag:

1. **test** — `pip install -r requirements.txt` + `pip install -e .` on a
   clean ubuntu runner, then the full pytest suite. This is where the
   crepe failure lived: fresh-runner dependency resolution is the FIRST
   environment without the devcontainer's pre-installed packages, so any
   broken/outdated dependency pin surfaces here.
2. **build** — reads the version from `autorb/version.py`, generates
   `RELEASE_NOTES.txt` (see below), builds sdist+wheel, runs the
   **wheel-content check** (every required module + data asset must be in
   the wheel), uploads `dist/*` as artifacts.
3. **release** — renames artifacts to PEP 440 local versions carrying the
   tag, verifies the tag matches `autorb/version.py` (prefix must match;
   suffix allowed but must not start with a digit), regenerates the notes
   as the GitHub Release body, publishes.
4. **audit** *(v0.1.31+)* — runs `tools/audit_release.py --tag <tag>
   --strict` and uploads `AUDIT_REPORT.txt` as an artifact. The release
   audit is part of the pipeline, not a manual step.

## Pre-tag checklist (do all of these BEFORE asking the user to tag)

The CI's tag-matching check will fail the release for a version mismatch;
the audit will fail it for anything else. Run through this first:

1. **Version**: `autorb/version.py` contains the version being released.
2. **CHANGELOG entry**: `CHANGELOG.md` has a `## [X.Y.Z] — date` section
   for that exact version (the notes generator hard-exits without it, and
   the release body embeds it verbatim).
3. **New package?** If this release added a package (or moved modules),
   it MUST be listed in `[tool.setuptools].packages` AND its files in the
   CI wheel-content check AND in `tools/audit_release.py`'s
   `EXPECTED_IMPORTS`/`REQUIRED_WHEEL_DATA`. **The editable install in the
   devcontainer masks a missing package entry forever** — this is exactly
   how v0.1.30 nearly shipped wheels without the entire
   `autorb.transcribe.instruments` package (no guitar/bass/drums/keys
   charts for any user).
4. **New data asset?** Add it to `[tool.setuptools.package-data]` and the
   CI check (the `webui/static/index.html` miss: the wheel's engine had no
   UI page to serve).
5. **New dependency?** It must be importable in a FRESH environment:
   - never add anything whose *build* requires `pkg_resources`
     (setuptools≥82 removed it — the crepe failure class);
   - check the package is actually imported by the code (crepe never was);
   - if it's an optional path with a guarded import, keep it out of the
     core deps and document the guard (like `adtof-pytorch` and `spleeter`).
6. **Console script deps are core**: anything shipped under
   `[project.scripts]` must have all its imports in the *core*
   dependencies, not an extra — a plain `pip install autorb` has to run it
   (the `[web]`-extra mistake).
7. **Full suite green** locally: `python -m pytest tests/ -q --deselect
   tests/test_quality_validation.py::TestSyncedTrackQuality`.
8. **Local wheel smoke** (cheap, catches 3/5/6 above in seconds):
   `python -m pip wheel --no-deps -w /tmp/wheelcheck .` then list the zip
   and confirm the new module/data files are present.

Tag rule: `v` + exact version from `autorb/version.py`, optionally with a
suffix that does NOT start with a digit (`v0.1.31-alpha01` ✓,
`v0.1.311` ✗ ambiguous). Test releases keep the version and add a suffix;
the release notes show the suffix as a test-release note.

## The release audit (`tools/audit_release.py`)

Run: `python tools/audit_release.py --tag v0.1.31 --strict`
(or `--release-url <github releases URL>`; `--work-dir` keeps downloads;
`--skip-smoke` skips stage 5). Read-only `gh` reads; safe any time.

| Stage | What it verifies |
| :--- | :--- |
| 1 CI/CD | the tag has a workflow run; it COMPLETED SUCCESSFULLY; all jobs green. A failed run means **there is no release** — stop and fix. |
| 2 Assets | GitHub release exists (not draft); wheel + sdist present; downloads them. |
| 3 Wheel | version matches the tag prefix; **source parity** — every `.py` under the packaged trees ships in the wheel (the instruments-package catcher); all data assets (CON/milo/png templates, fonts, `nmp.onnx`, web UI static); `RELEASE_NOTES.txt` present and mentions the version. |
| 4 Notes | CHANGELOG has the entry; the release body embeds it verbatim; the body carries the user-facing README sections (Key Features / Known Limitations / Quick Start...). |
| 5 Fresh-venv smoke | creates a brand-new venv, `pip install` the **downloaded wheel** (resolving deps from PyPI — the crepe catcher), `pip check`, imports **all** `EXPECTED_IMPORTS` modules, checks `autorb.version.__version__`, runs `python -m autorb.cli --help`. |
| 6 Tag hygiene | tag prefix == `autorb/version.py`; CHANGELOG entry exists for the working-tree version. |

Exit code: 0 always unless `--strict` and something failed (CI uses
`--strict`). On failure with no `--work-dir`, downloads are kept for
post-mortem. The report (`AUDIT_REPORT.txt`) uploads as a CI artifact.

The audit's own contracts are pinned by `tests/test_audit_release.py` —
including that `EXPECTED_IMPORTS`/`REQUIRED_WHEEL_DATA` reference files
that actually exist, and that its README-section list matches
`tools/gen_release_notes.py` (if the generator contract changes, the
test forces the audit to change with it).

## Release notes (`tools/gen_release_notes.py`)

Composed from two sources of truth: the CHANGELOG entry for the version,
and the user-facing README sections (Key Features / Known Limitations /
Roadmap / Installation / Quick Start / Previewing / Master Stems). One
generator serves both the GitHub Release body and the
`RELEASE_NOTES.txt` bundled into the wheel/sdist, so they can never
diverge. The README-section list lives in the generator's
`README_SECTIONS` and is mirrored in the audit tool —
`test_notes_sections_match_generator` fails the suite if they drift.

## Audit-findings history (what the audit has caught)

- **v0.1.30-alpha01**: crepe's pkg_resources install failure broke the CI
  test job — the audit's stage 1 reports "CI CONCLUDED 'failure' … The
  release is broken" and stages 2–5 then enumerate everything missing.
- **During the audit tool's own first run** (it was tested against the
  broken tag): `autorb.transcribe.instruments` missing from
  `[tool.setuptools].packages` (wheels shipped with NO instrument
  charting), `webui/static/index.html` missing from package-data (wheel
  engine had no UI), web deps hidden in an optional extra while the
  `autorb-webui` script shipped as core. All three were invisible in the
  devcontainer's editable install.

**Lesson (do not repeat):** "works in the devcontainer" ≠ "works in the
release." The editable install masks missing package listings, missing
package-data, and pre-installed-but-declared deps. The wheel build + the
fresh-venv smoke are the only gates that see the real user experience —
which is why the audit runs them on every tag, automatically.
