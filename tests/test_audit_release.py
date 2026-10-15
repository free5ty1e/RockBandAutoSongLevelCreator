"""Release-audit tool tests (v0.1.30): tools/audit_release.py contract.

The v0.1.30-alpha01 tag shipped a BROKEN build (crepe's pkg_resources
build failure broke `pip install -r requirements.txt` on fresh CI runners)
and nobody noticed until the user asked for an artifact audit. These tests
pin the audit tool's own logic so it stays reliable:
  * version parsing from tags (the workflow's prefix rule)
  * repo-slug extraction from the git remote
  * the audit result plumbing (ok/fail/strict exit codes)
  * the required-data / import lists reference real files
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from audit_release import (  # noqa: E402
    Audit, EXPECTED_IMPORTS, NOTES_README_SECTIONS, REQUIRED_WHEEL_DATA,
    REPO_ROOT, current_version, version_from_tag,
)


class TestVersionFromTag:
    def test_plain(self):
        assert version_from_tag("v0.0.91") == "0.0.91"

    def test_suffix(self):
        # the workflow allows suffix tags for test releases
        assert version_from_tag("v0.1.30-alpha01") == "0.1.30"
        # NOTE: a suffix WITHOUT a separator (v0.0.91test02) is ambiguous —
        # the workflow deliberately forbids digits-only suffixes. The audit
        # strips only '-suffix' forms; 'test02' glued on stays in the
        # version string and will fail the version-match check downstream,
        # which is the safe behavior for an ambiguous tag.
        assert version_from_tag("v0.0.91test02") == "0.0.91test02"

    def test_no_v_prefix(self):
        assert version_from_tag("0.1.30") == "0.1.30"


class TestAuditResult:
    def test_strict_exit_code_on_failure(self):
        a = Audit(strict=True)
        a.fail("something broke")
        assert a.summary() == 1

    def test_strict_passes_when_green(self):
        a = Audit(strict=True)
        a.ok("fine")
        assert a.summary() == 0

    def test_non_strict_zero_on_failure(self):
        a = Audit(strict=False)
        a.fail("recorded but not fatal")
        assert a.summary() == 0

    def test_findings_recorded(self):
        a = Audit(strict=False)
        a.ok("one")
        a.fail("two")
        assert any("one" in f for f in a.findings)
        assert any("two" in f for f in a.findings)
        assert a.passed == 1 and a.failed == 1


class TestListsReferenceReality:
    def test_required_wheel_data_exists_in_source(self):
        for rel in REQUIRED_WHEEL_DATA:
            assert (REPO_ROOT / rel).exists(), \
                f"REQUIRED_WHEEL_DATA lists a file that no longer exists: {rel}"

    def test_expected_imports_are_real_modules(self):
        for mod in EXPECTED_IMPORTS:
            parts = mod.split(".")
            pkg_dir = REPO_ROOT.joinpath(*parts[:-1]) if len(parts) > 1 else None
            leaf = parts[-1]
            base = (pkg_dir / leaf) if pkg_dir else (REPO_ROOT / leaf)
            as_pkg = base / "__init__.py"
            as_mod = base.with_suffix(".py")
            as_ns = base.is_dir()          # implicit namespace package
            assert as_pkg.exists() or as_mod.exists() or as_ns, \
                f"EXPECTED_IMPORTS names a module that doesn't exist: {mod}"

    def test_notes_sections_match_generator(self):
        """NOTES_README_SECTIONS must stay consistent with
        tools/gen_release_notes.py's README_SECTIONS contract."""
        gen = (REPO_ROOT / "tools" / "gen_release_notes.py").read_text()
        for section in NOTES_README_SECTIONS:
            assert f'"{section}"' in gen, \
                (f"audit expects README section {section!r} but "
                 "gen_release_notes.py doesn't emit it — update "
                 "NOTES_README_SECTIONS")

    def test_current_version_has_changelog_entry(self):
        import re
        v = current_version()
        assert re.search(rf"^## \[{re.escape(v)}\]",
                         (REPO_ROOT / "CHANGELOG.md").read_text(), re.M), \
            f"no CHANGELOG entry for the current version [{v}] — required " \
            "before tagging"


class TestRequirementsSanity:
    def test_no_pkg_resources_buildtime_deps_in_requirements(self):
        """The crepe failure class: a requirements.txt entry whose BUILD
        imports pkg_resources breaks every fresh install under
        setuptools>=82. We can't parse every package's setup.py here, but
        we CAN pin that crepe itself never sneaks back in."""
        reqs = (REPO_ROOT / "requirements.txt").read_text()
        assert not re.search(r"^\s*crepe\b", reqs, re.M), \
            "crepe reintroduced — its build needs pkg_resources and breaks " \
            "fresh CI installs (v0.1.30-alpha01 failure)"

    def test_webui_deps_are_core(self):
        """webui ships in the wheel with a console script, so its deps
        must be CORE install_requires (the [web] extra alone left a plain
        `pip install autorb` unable to run autorb-webui)."""
        src = (REPO_ROOT / "pyproject.toml").read_text()
        m = re.search(r"^dependencies = \[(.*?)^\]", src, re.S | re.M)
        assert m and "fastapi" in m.group(1) and "uvicorn" in m.group(1), \
            "web deps must be in core dependencies (webui ships as core)"


import re  # noqa: E402  (used by TestRequirementsSanity)


class TestReleaseDocsConsistency:
    """The KB page + CLAUDE.md rules must stay true to the code they
    describe (added when they were written, v0.1.31): if the release
    machinery changes shape, these docs must change with it."""

    def test_kb_release_process_page_exists_and_matches_tool(self):
        kb = (REPO_ROOT / "llm-wiki-kb" / "release_process.md").read_text()
        tool = (REPO_ROOT / "tools" / "audit_release.py").read_text()
        # the KB describes the audit's stages and key lists
        for needle in ("audit_release.py", "EXPECTED_IMPORTS",
                       "REQUIRED_WHEEL_DATA", "fresh-venv",
                       "setuptools].packages", "package-data"):
            assert needle in kb, f"KB release_process.md lost mention of {needle}"
        # and the tool still HAS the things the KB says it has
        assert "EXPECTED_IMPORTS" in tool and "REQUIRED_WHEEL_DATA" in tool

    def test_kb_index_lists_release_process(self):
        idx = (REPO_ROOT / "llm-wiki-kb" / "index.md").read_text()
        assert "[[release_process]]" in idx, \
            "KB index must list the release_process page"

    def test_agent_rules_have_release_section(self):
        cm = (REPO_ROOT / "CLAUDE.md").read_text()
        assert "## Release Rules" in cm, \
            "CLAUDE.md must keep the Release Rules section"
        assert "audit_release.py" in cm, "rules must point at the audit tool"
        assert "Never claim a release is good" in cm, \
            "the never-claim rule is the core contract"

    def test_workflow_has_audit_job(self):
        wf = (REPO_ROOT / ".github" / "workflows" / "ci-cd.yml").read_text()
        assert "tools/audit_release.py" in wf and "audit:" in wf, \
            "the CI audit job must run the audit on every tag"


class TestPep427WheelFilenames:
    """v0.1.31-alpha03 audit finding: the tag-renamed wheel filename
    carried a DASH inside the PEP 440 local-version segment
    (autorb-0.1.31+v0.1.31-alpha03-py3-none-any.whl) and pip rejects it —
    "Invalid build number: alpha03". Users literally cannot install the
    release wheel. Pin the workflow's sanitizer so dashes can never reach
    the local segment again."""

    def test_workflow_local_version_has_no_dashes(self):
        wf = (REPO_ROOT / ".github" / "workflows" / "ci-cd.yml").read_text()
        m = re.search(r'LOCAL="\$\{TAG//\[\^a-zA-Z0-9\._\]/(\S+)\}"', wf)
        assert m, "workflow must sanitize the tag into LOCAL=..."
        excluded = m.group(1)
        assert "-" not in excluded, \
            ("dashes are allowed into the local-version label — pip rejects "
             "the resulting wheel filename with 'Invalid build number' "
             "(v0.1.31-alpha03 audit finding)")

    def test_pip_accepts_dash_free_local_version(self):
        """End-to-end proof: rename the actual released wheel per the fixed
        sanitizer and pip --dry-run must accept it. Skips when pip or the
        packaging example is unavailable."""
        import subprocess
        import sys as _sys
        import tempfile
        import shutil as _sh
        whl = None
        for base in (REPO_ROOT / "dist", Path(tempfile.gettempdir()) / "audit_alpha03"):
            if base.exists():
                cands = list(base.glob("*.whl"))
                if cands:
                    whl = cands[0]
                    break
        if whl is None:
            import pytest
            pytest.skip("no release wheel on disk to rename")
        with tempfile.TemporaryDirectory() as td:
            # rename per the FIXED sanitizer: non-alnum(keep . _) -> '.'
            stem = whl.name[:-len("-py3-none-any.whl")] if whl.name.endswith("py3-none-any.whl") else whl.name[:-4]
            local = re.sub(r"[^a-zA-Z0-9._]", ".", stem.split("+")[-1])
            base_ver = stem.split("+")[0]
            fixed = f"{base_ver}+{local}-py3-none-any.whl"
            dst = Path(td) / fixed
            _sh.copy2(whl, dst)
            r = subprocess.run([_sys.executable, "-m", "pip", "install",
                                "--dry-run", "--no-deps", str(dst)],
                               capture_output=True, text=True, timeout=180)
            assert r.returncode == 0, \
                f"pip rejected the dash-free rename {fixed}: " \
                f"{(r.stderr or '').strip()[-200:]}"
