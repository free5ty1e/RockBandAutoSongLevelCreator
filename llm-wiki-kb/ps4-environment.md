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

- **Does a converted `output/known_good_cons/311 - Down` (0xA unencrypted mogg) actually play with audio on PS4 RB4DX?**
  - The user has confirmed they've played official 311 - Down on PS4, and has reported 0xA works on PS3 — but we still need to confirm they have actually converted *our* 311 CON (0xA) via ForgeTool and played it on the PS4, versus only having played the official encrypted DLC.
  - This is the decisive test for whether unencrypted 0xA moggs are supported by RB4DX, or whether we must produce an **encrypted v13/v16** mogg (the template `SmellsLikeNirvana_rb3con` contains a v13 0x0D encrypted mogg; RB4-era tooling appears to use encrypted moggs).

## Conversion Pipeline (User Side)

- **ForgeToolGUI 0.1.19** on **Windows** performs CON → PKG conversion (LibForge.DLL, MidiCS, DtxCS, GameArchives 0.12).
- LibForge copies the embedded `.mogg` **byte-for-byte** into the PKG — RB4 does not re-encode the audio. So the audio problem is entirely in the CON's `.mogg` (or its placement), not in conversion.
- **Our dev container cannot run ForgeTool/LibForge** (no dotnet/mono) — so CON → PKG conversion cannot be validated locally; it must be tested by the user on Windows.

## Testing Notes

- Current symptom on PS4 RB4DX: chart loads (vocal fretboard + lyrics appear briefly), but **no audio preview in the song list** and the song **"completes instantly" at 0%** with a 0-point taunt.
- Fixes applied and re-tested with the same symptom: small Ogg pages (`-page_duration 40000`), real `(song_length)` from MOGG duration. Chart-side placeholder tracks fixed the earlier ForgeTool NRE (chart now loads).
- **Fresh retest (v0.0063, rebuilt CON/PKG from current code):** the old chart's phrase-close bug was the scoring killer — the stale PKG chart had 18 phrase opens and 0 real closes, so vocal scoring did nothing. After the phrase-close fix, **vocal scoring now works** (phrases recognized, score bar fills). Remaining on PS4:
  - **No audio preview in the song list** — root cause still unresolved.
  - **No count-in / song starts immediately + crowd boos at start** — expected: count-in is audio-based (prepend a 2-measure click at the first bars' tempo to the MOGG; `[music_start]` then fires the crowd cheer after it).
  - **Lyrics drift progressively later** in the song — suspected cause: the chart uses one averaged BPM from a jittery 534-value beat-tracked tempo map instead of a dynamic tempo map (see `rock_band_customs_domain.md`).
