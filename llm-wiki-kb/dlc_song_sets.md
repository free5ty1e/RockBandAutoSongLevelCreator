# Official-DLC Song Sets — verified YouTube + LRC + tab matches (v0.1.41)

Curated song sets for the ground-truth loop: every row has (1) an official
Rock Band chart (fetch the CON from your DLC archive), (2) a YouTube upload
of the same master (duration verified via `tools/rb_song_matcher.py`), and
(3) a synced LRC on lrclib.net. Most rows also have a full-band Guitar Pro
tab in the git-ignored `tabs/` collection. Δ = |YouTube duration − LRC
duration| in seconds; RB DLC uses the album master + ~1–2 s of lead-in
silence, so a few seconds of Δ is expected — the CON's mogg gives the exact
in-game length once the file is in hand.

**LRC links:** `LRC page` = the human-readable lrclib.net song page (the
synced lyrics render there, "Copy" / "Download" available). `LRC API` = the
direct JSON endpoint (`syncedLyrics` field = the .lrc content; save it as
`<song>.lrc`). Both verified live 2026-10-28.

**RB source labels:**
- `RB3 on-disc` — one of the 83 songs with full metadata in
  `hmxmilohax/rock-band-3-deluxe` `_ark/dx/song_updates/rb3_songs.dta`
- `RB TP Vol 1/2`, `Classic Rock TP` — annotated
  `(game_origin rbtp_*)` in the same repo's `official_additional_metadata.dta`
- `RB legacy catalog` — id present in the 2559-song `songs_yarg.dta`
  Harmonix list in that repo

## Tier 1 — tab + near-exact length match (start here)

| # | Artist – Title | RB source | Δ | YouTube (dur s) | LRC dur | lrclib id | LRC page | LRC API (download) | Tab (tabs/) |
|--:|---|---|--:|---|---:|---|---|---|---|
| 1 | Weezer – Say It Ain't So | RB legacy catalog | **+0.0** | [OoPHItnUFkw](https://www.youtube.com/watch?v=OoPHItnUFkw) (259) | 259 | 36953128 | [page](https://lrclib.net/weezer/say-it-aint-so) | [api](https://lrclib.net/api/search?track_name=Say%20It%20Ain%27t%20So&artist_name=Weezer) | `tabs/W/Weezer - Say It Aint So.gp3` |
| 2 | Foo Fighters – Everlong | RB legacy catalog | **+0.0** | [YLRlOvzs-XU](https://www.youtube.com/watch?v=YLRlOvzs-XU) (251) | 251 | 37021528 | [page](https://lrclib.net/foo-fighters/everlong) | [api](https://lrclib.net/api/search?track_name=Everlong&artist_name=Foo%20Fighters) | `tabs/E/Foo Fighters - Everlong.gp3` |
| 3 | Rammstein – Du Hast | RB legacy catalog | **+0.4** | [W3q8Od5qJio](https://www.youtube.com/watch?v=W3q8Od5qJio) (236) | 235.6 | 22369476 | [page](https://lrclib.net/rammstein/du-hast) | [api](https://lrclib.net/api/search?track_name=Du%20Hast&artist_name=Rammstein) | `tabs/Q/Rammstein - Du Hast.gp3` |
| 4 | T. Rex – 20th Century Boy | RB3 on-disc | +1.0 | [67XvTTTXNdQ](https://www.youtube.com/watch?v=67XvTTTXNdQ) (215) | 216 | 37507841 | [page](https://lrclib.net/t-rex/20th-century-boy) | [api](https://lrclib.net/api/search?track_name=20th%20Century%20Boy&artist_name=T.%20Rex) | `tabs/T/T-Rex - 20th Century Boy.gp4` |
| 5 | The Offspring – Self Esteem | RB legacy catalog | +1.0 | [ZF5MTyGI2j4](https://www.youtube.com/watch?v=ZF5MTyGI2j4) (265) | 266 | 36846170 | [page](https://lrclib.net/the-offspring/self-esteem) | [api](https://lrclib.net/api/search?track_name=Self%20Esteem&artist_name=The%20Offspring) | `tabs/N/Offspring - Self Esteem.gp3` |
| 6 | Foreigner – Cold as Ice | RB3 on-disc | +1.0 | [SVrG05r9DKA](https://www.youtube.com/watch?v=SVrG05r9DKA) (200) | 199 | 36985042 | [page](https://lrclib.net/foreigner/cold-as-ice) | [api](https://lrclib.net/api/search?track_name=Cold%20as%20Ice&artist_name=Foreigner) | `tabs/Pop_Rock/Foreigner/Foreigner - Cold As Ice.gp4` |
| 7 | Blink-182 – All The Small Things | RB TP Vol 1 | +2.0 | [MyNQNVUwi8Y](https://www.youtube.com/watch?v=MyNQNVUwi8Y) (220) | 218 | 36939151 | [page](https://lrclib.net/blink-182/all-the-small-things) | [api](https://lrclib.net/api/search?track_name=All%20The%20Small%20Things&artist_name=Blink-182) | `tabs/B/Blink 182 - All The Small Things.gp3` |
| 8 | Anthrax – Caught in a Mosh | RB3 on-disc | +2.0 | [XphUURIAx5g](https://www.youtube.com/watch?v=XphUURIAx5g) (301) | 299 | 37506831 | [page](https://lrclib.net/anthrax/caught-in-a-mosh) | [api](https://lrclib.net/api/search?track_name=Caught%20in%20a%20Mosh&artist_name=Anthrax) | `tabs/A/Anthrax/Anthrax - Caught in A Mosh.gp3` |
| 9 | Avenged Sevenfold – Beast and the Harlot | RB legacy catalog | +2.0 | [QRJbIXezn8c](https://www.youtube.com/watch?v=QRJbIXezn8c) (342) | 344 | 34583640 | [page](https://lrclib.net/avenged-sevenfold/beast-and-the-harlot) | [api](https://lrclib.net/api/search?track_name=Beast%20and%20the%20Harlot&artist_name=Avenged%20Sevenfold) | `tabs/Hard_Heavy/Avenged_Sevenfold/Avenged Sevenfold - Beast And The Harlot.gp4` |
| 10 | Muse – Time Is Running Out | RB TP Vol 2 | +2.7 | [yTM0uZfysqk](https://www.youtube.com/watch?v=yTM0uZfysqk) (239) | 236.3 | 17314202 | [page](https://lrclib.net/muse/time-is-running-out) | [api](https://lrclib.net/api/search?track_name=Time%20Is%20Running%20Out&artist_name=Muse) | `tabs/M/Muse/Muse - Time Is Running Out.gp4` |
| 11 | Sum 41 – Fat Lip | RB legacy catalog | +3.0 | [atjJVwok9ws](https://www.youtube.com/watch?v=atjJVwok9ws) (178) | 181 | 36976000 | [page](https://lrclib.net/sum-41/fat-lip) | [api](https://lrclib.net/api/search?track_name=Fat%20Lip&artist_name=Sum%2041) | `tabs/Punk_Grunge/Sum_41/Sum 41 - Fat Lip.gp4` |

## Tier 2 — good, slightly larger deltas or partial material

| # | Artist – Title | RB source | Δ | YouTube (dur s) | LRC dur | lrclib id | LRC page | LRC API (download) | Tab (tabs/) |
|--:|---|---|--:|---|---:|---|---|---|---|
| 1 | The Doobie Brothers – China Grove | RB3 on-disc | +1.0 | [MCpI645baoU](https://www.youtube.com/watch?v=MCpI645baoU) (196) | 195 | 37016904 | [page](https://lrclib.net/the-doobie-brothers/china-grove) | [api](https://lrclib.net/api/search?track_name=China%20Grove&artist_name=The%20Doobie%20Brothers) | — |
| 2 | Nazareth – Hair of the Dog | Classic Rock TP | +2.0 | [Ef2SLZdhNrY](https://www.youtube.com/watch?v=Ef2SLZdhNrY) (247) | 249 | 37020917 | [page](https://lrclib.net/nazareth/hair-of-the-dog) | [api](https://lrclib.net/api/search?track_name=Hair%20of%20the%20Dog&artist_name=Nazareth) | — |
| 3 | Kiss – Calling Dr. Love | RB TP Vol 1 | +7.0 | [moCVaMu4EaE](https://www.youtube.com/watch?v=moCVaMu4EaE) (206) | 199 | 37103592 | [page](https://lrclib.net/kiss/calling-dr-love) | [api](https://lrclib.net/api/search?track_name=Calling%20Dr.%20Love&artist_name=Kiss) | `tabs/Hard_Heavy/Kiss/Kiss - Calling Dr. Love.gp3` |
| 4 | Ozzy Osbourne – Crazy Train | RB legacy catalog | +7.0 | [Djrl6fu8myo](https://www.youtube.com/watch?v=Djrl6fu8myo) (297) | 290 | 36996649 | [page](https://lrclib.net/ozzy-osbourne/crazy-train) | [api](https://lrclib.net/api/search?track_name=Crazy%20Train&artist_name=Ozzy%20Osbourne) | `tabs/Hard_Heavy/Osbourne/Osbourne, Ozzy - Ozzy Osbourne Crazy Train (Live At Budokan).gp3` ⚠ live tab |
| 5 | Slipknot – Before I Forget | RB3 on-disc | +8.0 | [Zo2aOEvdDug](https://www.youtube.com/watch?v=Zo2aOEvdDug) (259) | 267 | 36987821 | [page](https://lrclib.net/slipknot/before-i-forget) | [api](https://lrclib.net/api/search?track_name=Before%20I%20Forget&artist_name=Slipknot) | `tabs/Neo_Metal_Indus/Slipknot/Slipknot - Before I Forget.gp4` |
| 6 | Lynyrd Skynyrd – Free Bird | RB legacy catalog | +7.9 | [0LwcvjNJTuM](https://www.youtube.com/watch?v=0LwcvjNJTuM) (551) | 558.9 | 17954434 | [page](https://lrclib.net/lynyrd-skynyrd/free-bird) | [api](https://lrclib.net/api/search?track_name=Free%20Bird&artist_name=Lynyrd%20Skynyrd) | `tabs/L/Lynyrd Skynyrd - Freebird.gp3` |
| 7 | Queen – Bohemian Rhapsody | RB legacy catalog | +9.0 | [fJ9rUzIMcZQ](https://www.youtube.com/watch?v=fJ9rUzIMcZQ) (360) | 351 | 36902193 | [page](https://lrclib.net/queen/bohemian-rhapsody) | [api](https://lrclib.net/api/search?track_name=Bohemian%20Rhapsody&artist_name=Queen) | `tabs/Q/Queen - Bohemian Rhapsody.gp3` |
| 8 | The Police – Truth Hits Everybody | RB TP Vol 2 | +9.0 | [GGvgHd0iwRs](https://www.youtube.com/watch?v=GGvgHd0iwRs) (213) | 204 | 36958157 | [page](https://lrclib.net/the-police/truth-hits-everybody) | [api](https://lrclib.net/api/search?track_name=Truth%20Hits%20Everybody&artist_name=The%20Police) | — |
| 9 | Blink-182 – Dammit | RB legacy catalog | +10.0 | [njvq1L-iXzQ](https://www.youtube.com/watch?v=njvq1L-iXzQ) (176) | 186 | 37036917 | [page](https://lrclib.net/blink-182/dammit) | [api](https://lrclib.net/api/search?track_name=Dammit&artist_name=Blink-182) | `tabs/B/Blink 182 - Dammit.gp4` |
| 10 | Sublime – Santeria | RB legacy catalog | +13.0 | [AEYN5w4T_aM](https://www.youtube.com/watch?v=AEYN5w4T_aM) (196) | 183 | 36952503 | [page](https://lrclib.net/sublime/santeria) | [api](https://lrclib.net/api/search?track_name=Santeria&artist_name=Sublime) | `tabs/S/Sublime/Sublime - Santeria.gp3` |

## Caveats / avoid

| Artist – Title | Issue |
|---|---|
| Weezer – Buddy Holly | RB TP Vol 1; tab exists (`tabs/W/Weezer - Buddy Holly.gp3`), LRC 263 s — but the top YT hits are truncated/live cuts (242 s). Find the *Blues Traveler/album* studio upload (~4:24) before use. |
| RHCP – Snow (Hey Oh) | Δ +30 s: the YT pick is a version mismatch. Find the album cut (5:35). Tab + LRC fine otherwise. |
| Boston – More Than a Feeling | LRC matched a ~16 min live compilation — no usable synced LRC yet. |
| The J. Geils Band – Centerfold | No YouTube hit found by the matcher; LRC exists (id 36909727, [page](https://lrclib.net/the-j-geils-band/centerfold)). |
| 30 Seconds To Mars – The Kill | YT search throttled during the run; LRC exists (id 37005701-class hits via [api](https://lrclib.net/api/search?track_name=The%20Kill&artist_name=30%20Seconds%20To%20Mars)). Retry with the matcher. |
| Lit – My Own Worst Enemy | Full-band tab (`tabs/L/Lit - My Own Worst Enemy.gp3`) + RB catalog, but **no synced LRC on lrclib** (plain only) — needs a hand-made LRC. |

## How to turn a row into a ground-truth song set

1. **CON** — fetch from your RB DLC archive into `input/rockbanddlc/`.
2. **Audio** — download the linked YouTube upload (or the album track) as
   mp3 into `input/rockbanddlc/<Artist> - <Title>.mp3`.
3. **LRC** — open the `LRC API` link, save the `syncedLyrics` field as
   `<Artist> - <Title>.lrc` beside the mp3 (the `LRC page` works too:
   copy from the site).
4. **Verify** — the CON's mogg length should be ≈ the LRC duration + 1–2 s
   lead-in (`ffprobe` / `read_mogg_duration_ms`). If it's off by more than
   ~5 s, the upload is the wrong version — check another YT hit from the
   matcher report.
5. **Tab** — the `tabs/` path column gives the full-band GP file for the
   tab-backed lane work.
6. **Run the loop** — `python -m autorb.cli <mp3> --artist ... --title ...
   --lyrics <lrc> --guitar-tab <gp> --build-clone-hero`, then
   `tools/dlc_ground_truth.py align <official.mid> <out>/validation/notes.mid`.

Provenance: found via `tools/rb_song_matcher.py` (v0.1.40 run, report in
`.tmp/match_report.json` — regenerate any time); RB catalog sources and the
matcher's mechanics are documented in `[[research_tooling]]`. All songs are
official Rock Band releases (RB1/2/3 on-disc, DLC, or official track packs).

Copyright: same rules as everywhere — CONs/mp3s/LRCs/tabs stay in git-ignored
folders (`input/rockbanddlc/`, `tabs/`); only measurements and code are
committed. This page stores LINKS and metadata only, never song content.
