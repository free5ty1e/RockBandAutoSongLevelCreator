# Memory Index

- [Guitar strum backbone approach](guitar-strum-backbone-approach.md) — guitar timing from audio strum backbone, not Basic Pitch; validate with tools/guitar_tab_alignment
- [BN pipeline OOM avoidance](bn-pipeline-oom-avoidance.md) — use --skip-separation on cached stems to re-chart fast without OOM on 8 GB host
- [Strip merge position-aware](strip-merge-position-aware.md) — flush-to-tail strip breaks sequential crossfade; merge by actual start + weight normalization; solo detection = register energy
