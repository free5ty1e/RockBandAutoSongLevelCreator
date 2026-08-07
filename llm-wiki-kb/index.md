---
title: AutoRB Knowledge Base
date: 2026-08-07
---
# AutoRB Knowledge Base

This is the project wiki for **AutoRB** (MP3 -> CON): an end-to-end Python tool that turns raw audio + lyrics into playable Rock Band 3 Xbox 360 CON files (and PS4 PKG via the vendored ForgeTool). It is an **incremental, LLM-maintained wiki** (per the [llm-wiki guide](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f/raw/ac46de1ad27f92b28ac95459c782c07f6b8c964a/llm-wiki.md)): every page captures a decision, its reasoning, and its history so an agent (or human) can quickly come up to speed without re-deriving the hard-won domain knowledge.

## Where to start

If you are new, read in this order:

1. **[[rock_band_customs_domain]]** — the Rock Band charting rules and pitfalls that shape everything (MIDI requirements, count-in, tempo maps, freestyle gating).
2. **[[architecture]]** — the end-to-end pipeline and where each piece lives.
3. Then dive into the area you are working on via the topic list below.

## Topic index

| Page | What it covers |
| :--- | :--- |
| [[architecture]] | End-to-end pipeline, packaging, supported Python range, release wheel naming. |
| [[rock_band_customs_domain]] | Rock Band charting domain rules, MIDI requirements, count-in, tempo maps, difficulty ranks. |
| [[vocal_alignment]] | LRC ingestion, WhisperX alignment, onset-snapped timing, pyin-primary pitch resolution, note-end clipping. |
| [[con_stfs_format]] | Xbox 360 STFS / CON container format and block addressing. |
| [[mogg_audio_format]] | MOGG container layout, Ogg page-size constraints, channel layout, song_length. |
| [[forgetool_compat]] | ForgeTool / LibForge CON->PKG compatibility: crashes fixed, interleave-aware I/O, freestyle patch. |
| [[ps4-environment]] | The live PS4 RB4DX test environment, ground-truth findings, and open questions. |

## How this wiki is maintained

- **[[index]]** is the entry point / landing page (this file).
- **[[log]]** is the append-only ledger of every change to this wiki: timestamped, with what was added and why.
- Each topic page is a **living document**: append new sections with a version tag (e.g. `## v0.0073`) rather than rewriting history, so the reasoning chain stays intact.
- Pages are linked with Obsidian `[[wikilinks]]` so the whole KB renders as a navigable graph. The `.obsidian/` folder holds the vault config.

## Project pointers

- Root README: `../README.md` (user-facing install/usage docs).
- Roadmap: `../ROADMAP.md`. Spec/task tracking: `../AGENT_PLAN.md`.
- Changelog: `../CHANGELOG.md`. Version: `autorb/version.py`.
