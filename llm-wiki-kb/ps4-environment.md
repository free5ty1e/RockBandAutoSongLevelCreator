# PS4 Test Environment (RB4DX)

The user's live test environment and experience — the ground truth our PS4 compatibility work is validated against. Update this page as we learn more.

## Console & Game

- **Console:** PlayStation 4 (homebrew-enabled, GoldHEN-style custom FW assumed but unconfirmed).
- **Game:** Rock Band 4 **Deluxe (RB4DX)** — nightly build **20260627**.
- **Custom songs installed:** via PKG packages (created from CON files with ForgeToolGUI on Windows, then installed on the console).

## User Experience Level

- **Expert.** Years of Rock Band customs experience across **PS3** and **PS4**.
- Has played **thousands of customs**; not a novice. Do not condescend or re-explain basics.
- Converts CON → PKG and installs the resulting PKGs themselves; comfortable running CLI / console tooling and installing homebrew.

## Reference / Known-Good Content

- Plays the **official 311 - Down DLC** on PS4 — previews audio and plays perfectly. (This is the gold-standard reference for what a working RB4 audio setup looks like.)

## Historical Findings (PS3 RB3)

- **Unencrypted (v10 / 0x0A) moggs CAN play on PS3 RB3.** The user has, in the past, had to run the **C3 Tools decrypter** on certain songs and the decrypted versions then worked. So on PS3 the 0xA path is proven to be playable.
- Whether 0xA moggs are sufficient on **PS4 RB4DX** is the open question (see below).

## Open Questions / Pending Tests

- **Unencrypted 0xA moggs on PS4 RB4DX are now CONFIRMED playable in-game.** The v0.0068 CON/PKG (0xA mogg) installed and played: chart loads, vocal fretboard + lyrics appear, audio plays (user reported the constant ~1s timing offset rather than "no audio"). Only the song-list *preview* and freestyle lines remain broken.
- **Remaining to confirm on the next retest (v0.0069):** whether filling all 10 MOGG channels (ch0/1 = drums, ch9 = low ambience, mirroring 311 Down where every channel carries signal) restores the song-list preview audio.

## Conversion Pipeline (User Side)

- **ForgeToolGUI 0.1.19** on **Windows** performs CON → PKG conversion (LibForge.DLL, MidiCS, DtxCS, GameArchives 0.12).
- LibForge copies the embedded `.mogg` **byte-for-byte** into the PKG — RB4 does not re-encode the audio. So the audio problem is entirely in the CON's `.mogg` (or its placement), not in conversion.
- **Our dev container CAN run ForgeTool.** The devcontainer Dockerfile installs `mono-devel` (apt) + the .NET SDK 8 to `/tmp/dotnet`, and `.devcontainer/post-install.sh` runs `tools/build_forgetool.sh`. That script now auto-detects mono's reference-assembly dir (Linux `/usr/lib/mono/4.7.1-api` vs macOS `/Library/Frameworks/Mono.framework/...`) instead of hardcoding the Linux path, so CON → PKG conversion can be validated locally on both OSes (verified: `ForgeTool.exe con2gp4` converted `output/open_road_song.con` → GP4 successfully).

## Testing Notes

- **v0.0068 retest (user, PS4 RB4DX 20260627):** three remaining issues, all confirmed with correct test conditions (count-in plays normally — silence, count-in beats, then music; preview in the song list is **completely silent**; Freestyle Vocals was ON in RB4 Options and Solo Vocals played on Hard/Expert, yet no guide lines). Vocal scoring and chart load work; no "instant 0%" behavior.
- **v0.0068 file-level verification (exhaustive, all layers consistent within ~30ms):** the CON's embedded `rbmid_ps4` parses end-to-end (first vocal tick 6071 ↔ StartMillis 5037.445ms; `PreviewStartMillis` 54457.59; 391 tempos reproducing every note time; `FinalEventTick` 274900); the CON/PKG MOGG is byte-identical to `output/open_road_song.mogg` (md5 `aa5765806d645ce8bfa629b74f0afbd9`); `songs.dta` `(preview 50636 80636)` is **milliseconds** (RB3 authoring guide + 311 Down corroboration) and lands in loud music; the OggMap byte offsets decode to their claimed samples; Ogg page sizes are small (≤2752 granules). **Therefore the ~1s offset and silent preview are NOT reproducible from the files** — the remaining suspects are game-side.
- **v0.0069 hypothesis (implemented, awaiting retest):** silent MOGG channels → silent preview. 311 Down's mogg has non-zero signal on ALL 10 channels (ch0/1 loudest, ~3500 RMS; ch9 ~50 RMS); our v0.0068 mogg had ch0/1/9 forced to digital zero. Any preview mixdown keyed to the front stereo pair was therefore silent while gameplay (mixing ch2-8) worked. v0.0069 fills all channels. OggMap re-validated (64/64 sampled), preview windows (50.636s / 54.458s) still land in loud audio (RMS > 1500).
- **~1s audio-ahead-of-notes offset (ROOT CAUSE FOUND v0.0072):** the v0.0064 count-in hypothesis is **disproven** (count-in plays normally in-game and files agree within ~30ms). The v0.0070 retest isolated the *remaining rate problem*: the first word is right-on but every subsequent note drifted **progressively later**. Two hypotheses were tested and ruled out: (a) the dense per-beat tempo track — v0.0071 shipped a sparse measure-level map (94 smooth events, ~168-173 BPM body, matching stock 311-Down/SLN references), yet the drift persisted; and (b) ForgeTool conversion — the rbmid `StartMillis` round-tripped our chart's tempo-map times to <1ms. **v0.0072 found the real bug in note emission:** `synced_track.json` word `end` times stretch past the *next* word's start ("Tonight" ends 0.94s, "I" starts 0.85s), and `generate_vocal_midi()` emitted each note at `max(target_start, previous_end)` — so every overlapping pair pushed the next note later and the pushes **accumulated** (index-aligned charted-vs-whisper error: 0 → 5.2s → 8.4s first→last word). Fix: each note's duration is **clipped to the next note's charted start**; rebuilt charted-vs-whisper error med **+5.088s → 0.000s**. Rebuilt CON/PKG (`output/pkg/UP8802-CUSA02084_00-0000000000000001.pkg`) awaiting PS4 retest.
- **Silent song-list preview (v0.0069 hypothesis shipped, still failing):** 311 Down's mogg has non-zero signal on ALL 10 channels (ch0/1 loudest, ~3500 RMS; ch9 ~50 RMS); our older mogg had ch0/1/9 forced to digital zero. v0.0069 fills all channels (RMS 433/521/171 on ch0/1/9), OggMap re-validated (64/64 sampled), preview windows (50.636s / 54.458s) still land in loud audio (RMS > 1500), yet the PS4 song-list preview remains completely silent in-game. Chart/dta/MOGG all agree on the preview region — so the remaining failure is likely how the game reads the PKG preview (not the files).
- **Freestyle lines absent despite correct conditions:** the PKG `songdta_ps4` parses to `HasFreestyleVocals=1` and the rbmid carries 24 freestyle regions, yet RB4DX draws no lines. Both gates the manual documents are satisfied, so the failure is likely RB4DX-side (how it reads/commits `HasFreestyleVocals`, or a re-scan/re-install requirement) rather than the files. The vendored ForgeTool path (patched `SongDataConverter.cs`) is verified writing the flag.
- **Resolved earlier:** progressive lyric drift (fixed v0.0072 — see the root-cause note above; the v0.0063/v0.0071 tempo-map changes were necessary but insufficient); count-in/crowd-boo at start (fixed v0.0064 — count-in now plays correctly); "completes instantly at 0%" (fixed by small Ogg pages + real `(song_length)` + placeholder tracks).
