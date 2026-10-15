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
