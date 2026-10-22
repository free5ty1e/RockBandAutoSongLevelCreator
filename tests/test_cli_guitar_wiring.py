"""CLI wiring tests for the guitar transcription path.

A v0.1.19 regression shipped to the user because a variable rename
(`solo_charting` -> `guitar_solo_charting`) left a stale reference in
cli.py's success branch: the NameError was caught by the broad `except`,
the CLI printed one warning line, and the export silently fell back to a
single placeholder gem per difficulty — "guitar intro totally blank except
one single note BEFORE the audio starts." These tests pin the wiring so a
stale name or silent placeholder fallback can never ship again.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLI_PATH = Path(__file__).resolve().parents[1] / "autorb" / "cli.py"


def test_cli_has_no_stale_solo_charting_names():
    """Every `solo_charting` reference in cli.py must be the click param or
    a keyword argument — a bare use would NameError only on the SUCCESS
    path (post-transcription), i.e. exactly when nobody is looking."""
    src = CLI_PATH.read_text()
    tree = ast.parse(src)
    # collect assigned names in main() (click params are main() arguments)
    main_fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "main")
    params = {a.arg for a in main_fn.args.args}
    bad = []
    for node in ast.walk(main_fn):
        if isinstance(node, ast.Name) and node.id == "solo_charting":
            # bare name use — only legal if a param/variable with that name exists
            if "solo_charting" not in params and not _is_assigned(main_fn, node):
                bad.append(node.lineno)
    assert not bad, f"bare solo_charting uses at lines {bad}: rename to guitar_solo_charting"


def _is_assigned(fn, node):
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = getattr(n, "targets", None) or ([n.target] if getattr(n, "target", None) else [])
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "solo_charting":
                    return True
    return False


def test_guitar_transcription_failure_is_fatal():
    """The guitar `except` must abort with a nonzero process exit, not fall
    through to a placeholder chart export.

    NOTE: since v0.1.23 the mechanism is `sys.exit(1)` — a bare `return 1`
    inside a click callback exits the process with code 0, which the web
    engine read as a successful build."""
    src = CLI_PATH.read_text()
    m = re.search(r"except Exception as e:\n(.*?guitar transcription failed.*?)\n(.*?)sys\.exit\(1\)", src, re.S)
    assert m, "guitar except block must abort with `sys.exit(1)` (placeholder charts are never shippable)"


def test_validation_fail_is_fatal():
    """A failed tab validation must abort the pipeline (nonzero exit), not
    continue and hand off a bad build."""
    src = CLI_PATH.read_text()
    assert "guitar validation FAILED" in src, "validation failure must print a loud error"
    # the FAIL branch must abort with a real nonzero exit (sys.exit, not a
    # click-swallowed `return 1`)
    fail_pos = src.index("guitar validation FAILED")
    after = src[fail_pos:fail_pos + 1200]
    assert "sys.exit(1)" in after, "validation FAIL must abort the run"


def test_transcribe_guitar_accepts_solo_charting():
    """The signature the CLI calls must exist (catches parameter drift)."""
    import inspect
    from autorb.transcribe.instruments.guitar import transcribe_guitar
    sig = inspect.signature(transcribe_guitar)
    assert "solo_charting" in sig.parameters, f"missing solo_charting: {list(sig.parameters)}"


def test_placeholder_only_when_charts_none():
    """Export writes a placeholder ONLY when charts are None — sanity-pins
    the midi_generator contract the failure path depends on."""
    import inspect
    from autorb.export import midi_generator
    src = inspect.getsource(midi_generator)
    assert "all(v is None for v in charts.values())" in src
