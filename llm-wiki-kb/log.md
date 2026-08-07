---
title: AutoRB Knowledge Base Log
date: 2026-08-07
---
# Log

Append-only ledger of changes to this knowledge base. Newest first. Each entry records: timestamp, what was added, and why (the reasoning that future agents should not have to re-derive).

## 2026-08-07 — Wiki restructured to llm-wiki conventions (v0.0073)

**What:** Added `[[index]]` (entry-point landing page) and `[[log]]` (this ledger), slimmed `README.md` to a minimal pointer, added `.obsidian/` vault config, and corrected stale `--skip-mogg` count-in wording in `[[vocal_alignment]]` and `[[architecture]]`.

**Why:** The KB previously had only a short `README.md` listing pages via markdown links. To follow the karpathy llm-wiki guide and make the KB work as an Obsidian vault (graph visualization, agent navigation), it needs an explicit entry point (`index.md`), a change ledger (`log.md`), `[[wikilinks]]`, and a vault config. Also, `--skip-mogg` no longer disables the count-in (v0.0073: it is derived unconditionally from the cached beat grid so a reused, already-count-in MOGG stays in sync), so the old "disables the count-in" statements were factually wrong and had to be updated.

**Pages now:** `index.md`, `log.md`, `architecture.md`, `rock_band_customs_domain.md`, `vocal_alignment.md`, `con_stfs_format.md`, `mogg_audio_format.md`, `forgetool_compat.md`, `ps4-environment.md`.

---

## Origin — KB creation

**What:** Created the initial 7 topic pages (`architecture`, `rock_band_customs_domain`, `vocal_alignment`, `con_stfs_format`, `mogg_audio_format`, `forgetool_compat`, `ps4-environment`) plus a short `README.md`.

**Why:** To capture the hard-won domain knowledge and architectural decisions accumulated across development cycles (STFS/MOGG formats, ForgeTool crash root-causes, vocal alignment fixes, PS4 test findings) so future agents can come up to speed without re-deriving them.

> Omissions and corrections welcome. Prefer appending dated entries over rewriting history so the reasoning chain stays intact.
