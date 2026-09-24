---
name: strip-merge-position-aware
description: "Strip merges in stems.py must be position-aware (flush-to-tail strip breaks sequential crossfade assumption); solo detection needs register energy, not root contour"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1da62c8c-2a31-4d74-867a-5910bdb836b9
  modified: 2026-09-19T20:13:47.364Z
---

Two hard-won findings from the v0.1.19 guitar/stems work:

1. **Strip merges must be position-aware.** The final flush-to-tail strip
   (start = n - strip_len) has a non-regular gap from the previous strip, so
   its true overlap exceeds the nominal `overlap_seconds`. A sequential
   "assume each strip begins overlap after the output" merge corrupts the
   tail (Open Road Song outro: correlation 0.998 → ~0 from ~175 s; content
   blended 21.9 s shifted). Correct approach (in `_merge_strips_by_position`):
   separation writes RAW strips; the merge places each strip at its ACTUAL
   start, applies fades once, divides by summed weights. Also:
   `SoundFile.read()` squeezes mono to 1-D — use `always_2d=True` or a
   (N,1) weight slice broadcasts to (N,N) and OOM-kills.

**Why:** The outro corruption was reported by the user as "glitchy, skips
around, mixes incorrectly" right at the outro; both the geometry math and
the correlation measurements pinned it to the flush-tail strip.

**How to apply:** For ANY strip/chunk reassembly, never assume regular
gaps — pass the actual start offsets through and merge by position. Verify
with a synthetic known-truth test (content = absolute time) over the same
irregular geometry (tests/test_stems_strip_merge.py).

2. **Lead-solo detection needs register energy.** During solos the rhythm
   guitar keeps playing (root contour unchanged), so detect via high-band
   (600-1600 Hz) / low-band (80-230 Hz) RMS ratio ≥ 1.5 instead.
   `--guitar-solo-charting` (experimental) charts solo regions as single
   lead notes via pyin in the lead register. Related:
   [[guitar-strum-backbone-approach]].
