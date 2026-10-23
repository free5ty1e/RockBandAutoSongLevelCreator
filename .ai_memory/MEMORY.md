# Memory Index

- [Release validation workflow](release-validation-workflow.md) — user tags, I monitor+audit (audit_release.py 6 stages, functional conversion w/ free benchmark + git-ignored local ORS); never commit copyrighted material; Pages = landing page only (PNA blocks loopback)
- [Web UI architecture](webui-architecture.md) — engine wraps real CLI; jobs/batches/output-folder browse/endpoints; label-based drop zones; headless reveal; busy-state contract
- [Current work state](current-work-state.md) — as of 2026-10-23: PR #4 (Pages landing) awaiting merge + live-site validation; v0.1.33 local audit deferred
- [Guitar strum backbone approach](guitar-strum-backbone-approach.md) — guitar timing from audio strum backbone, not Basic Pitch; validate with tools/guitar_tab_alignment
- [BN pipeline OOM avoidance](bn-pipeline-oom-avoidance.md) — use --skip-separation on cached stems to re-chart fast without OOM on 8 GB host
- [Strip merge position-aware](strip-merge-position-aware.md) — flush-to-tail strip breaks sequential crossfade; merge by actual start + weight normalization; solo detection = register energy
