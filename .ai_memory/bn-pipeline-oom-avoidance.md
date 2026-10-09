---
name: bn-pipeline-oom-avoidance
description: 8 GB host OOM-kills full htdemucs_6s separations when system memory is low; use --skip-separation on cached stems to re-chart instead
metadata: 
  node_type: memory
  type: project
  originSessionId: 1da62c8c-2a31-4d74-867a-5910bdb836b9
  modified: 2026-09-17T00:10:30.191Z
---

On this 8 GB devcontainer, a full `--separator htdemucs_6s` run of the 291 s
Barenaked Ladies track was killed mid-separation (strip 3/9) because system
memory (including 4 GB swap) was exhausted — total 7.7 Gi with swap 3.9/4.0 Gi
used. The transcriber/charting stages themselves are cheap.

**Why:** Full separation is ~20 min and the most memory-hostile stage, but it
is only needed when stems change. Iterating on chart logic (guitar/drums/bass
transcription, MIDI, Clone Hero export) does not require re-separating.

**How to apply:** When iterating on chart code with existing output dirs
(e.g. `output_6s_bn_final_both/` holds complete 6-stem output + tempo_map.json +
vocals_cache.json), re-run the pipeline with
`--skip-separation --skip-tempo-detection --skip-vocals --output-dir <same dir>`
to re-chart from the cached stems in ~2 min instead of ~20, avoiding the OOM
window. Only run a fresh separation when the stems themselves are stale.
Related: [[guitar-strum-backbone-approach]].
