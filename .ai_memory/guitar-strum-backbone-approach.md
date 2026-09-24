---
name: guitar-strum-backbone-approach
description: "Guitar chart timing must come from an audio strum backbone, not Basic Pitch onsets; validation tooling lives in tools/guitar_tab_alignment/"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1da62c8c-2a31-4d74-867a-5910bdb836b9
  modified: 2026-09-17T00:09:30.747Z
---

AutoRB's guitar chart rhythm is driven 1:1 by an **audio strum backbone**
(`_strum_backbone` in `autorb/transcribe/instruments/guitar.py`: librosa onset
strength, delta=0.08, 60 ms dedup — calibrated to the human-audible strum count)
because Basic Pitch over-detects rhythm-guitar onsets (~1814 vs ~700 real strums
on Open Road Song; it splits each strum's chord tones into separate onsets) and
its raw onsets collapsed dense 8th-note runs into held notes. Basic Pitch is
used ONLY for pitch/lane assignment: each note snaps onto its nearest backbone
strum (≤0.15 s), then strums with no BP note are gap-filled from a neighboring
matched strum.

**Why:** The user's recurring complaint pattern is per-instrument chart accuracy
validated by ear in Clone Hero playtests (drums sync, bass matching, guitar
rhythm wrong). Objective measurement beats threshold-tuning: `tools/guitar_tab_alignment/`
scores strum coverage recall/precision/F1 against the audio stem itself.

**How to apply:** When guitar strum rhythm regresses, run
`tools/guitar_tab_alignment/validate_chart.py` against the Clone Hero
`notes.mid` (offset 0 — CH charts are count-in-free; CON charts need the
count-in offset). Two validator gotchas fixed there: convert ticks→seconds by
**integrating the dynamic tempo map** (single-tempo conversion drifts ~seconds
over a song), and count **Expert pitches only** (60-64; lower difficulties are
re-quantized onto coarser grids and create phantom slots). Also: there are NO
tab files in the repo and tab-site fetches fail — never fabricate tab data;
the audio-derived backbone is the ground truth for rhythm. Related:
[[bn-pipeline-oom-avoidance]].
