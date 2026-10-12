"""CON payload block-read regression tests (v0.1.27): the PS4 "songs don't
show up" bug.

Root cause (found with a GameArchives/.NET probe on the user's DevTestPack):
``read_con_payloads`` read each payload as ONE CONTIGUOUS BYTE SLICE, but
STFS interleaves hash-table blocks every 0xAA data blocks — the slice read
THROUGH the gaps, inserting zero/hash bytes and shifting everything after.
The user's two-song pack read its inputs through this bug (the ORS mogg came
back with 2 junk blocks at exactly byte 557056 = the phys 170/171 slots) and
baked the corruption into the multi-song CON, so the PS4 PKG contained
garbage audio/chart data and the songs never appeared in the game list.

The fix reads payloads BLOCK BY BLOCK via logical_to_physical (the same
layout the writer produces). These tests pin that behavior.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autorb.export.con_packer import (
    BLOCK_SIZE, FT_OFF, _read_payload_blocks, logical_to_physical,
    package_con, package_con_multi, read_con_payloads,
)


def _filler(n, seed):
    out = bytearray()
    for i in range(n):
        out.append((seed + i) & 0xFF)
    return bytes(out)


class TestBlockRead:
    def test_read_payload_blocks_across_table_gaps(self):
        """A payload spanning multiple 0xAA groups must read back exactly,
        with hash-table gap blocks skipped."""
        # Build a fake image: give every LOGICAL block a recognizable
        # pattern; leave physical hash-table slots poisoned.
        n_logical = 0xAA * 3 + 5            # spans 3+ table boundaries
        phys_end = logical_to_physical(n_logical) + 1
        img = bytearray(b"\xcc" * (FT_OFF + phys_end * BLOCK_SIZE))
        start = 0
        content = bytes(range(256)) * (BLOCK_SIZE * 2 // 256) + _filler(BLOCK_SIZE, 7)
        # write the payload the way write_payload does
        blocks = (len(content) + BLOCK_SIZE - 1) // BLOCK_SIZE
        for i in range(blocks):
            off = FT_OFF + logical_to_physical(start + i) * BLOCK_SIZE
            img[off:off + BLOCK_SIZE] = content[i*BLOCK_SIZE:(i+1)*BLOCK_SIZE].ljust(BLOCK_SIZE, b"\x00")
        readback = _read_payload_blocks(bytes(img), start, len(content))
        assert readback == content, "block-wise read must reproduce the payload exactly"

    def test_contiguous_slice_would_fail_here(self):
        """Documents WHY block reads are required: a plain slice crosses
        the phys 170/171 gap and returns different bytes."""
        n_logical = 200
        phys_end = logical_to_physical(n_logical) + 1
        img = bytearray(b"\x00" * (FT_OFF + phys_end * BLOCK_SIZE))
        content = bytes(range(256)) * 16  # 4096 bytes = 1 block
        content = (content * 3)[:4096*3]  # 3 blocks
        for i in range(3):
            off = FT_OFF + logical_to_physical(200 + i) * BLOCK_SIZE
            img[off:off + BLOCK_SIZE] = content[i*4096:(i+1)*4096]
        start, size = 200, len(content)
        slice_off = FT_OFF + logical_to_physical(start) * BLOCK_SIZE
        sliced = bytes(img[slice_off:slice_off + size])
        blocked = _read_payload_blocks(bytes(img), start, size)
        assert blocked == content
        if logical_to_physical(start + 1) - logical_to_physical(start) > 1:
            # a table gap lies inside this span: the naive slice MUST differ
            assert sliced != content, "slice should cross a gap and corrupt"


class TestRoundTrip:
    def _big_song(self, tmp_path, name, mogg_mb=1):
        """Build a song whose mogg spans several 0xAA groups (the case the
        slice bug corrupted)."""
        from autorb.export.mogg_builder import build_mogg_from_stems
        # Synthesize a small but >170-block mogg by padding: 171 blocks
        # = 699136 bytes.
        payload = _filler(BLOCK_SIZE * 171, seed=0xAB) + b"TAIL"
        mogg = tmp_path / f"{name}.mogg"
        mogg.write_bytes(payload)
        mid = tmp_path / f"{name}.mid"
        mid.write_bytes(b"MThd" + _filler(600, 3))
        return mogg, mid, payload

    def test_single_con_round_trip_large_mogg(self, tmp_path):
        mogg_p, mid_p, payload = self._big_song(tmp_path, "bigsong")
        dta_p = tmp_path / "songs.dta"
        dta_p.write_bytes(b"(bigsong\n   (name \"Big Song\")\n   (artist \"T\")\n)\n")
        out = tmp_path / "out"
        package_con(out, "bigsong", mogg_p, mid_p, dta_p,
                    title="Big Song", artist="T", album_art_bytes=None)
        sid, files = read_con_payloads(out / "bigsong.con")
        assert sid == "bigsong"
        assert files["bigsong.mogg"] == payload, \
            "mogg spanning >170 blocks must round-trip byte-exactly"

    def test_multi_con_round_trip_two_songs(self, tmp_path):
        # two songs, the second's mogg starts deep in the block space
        # (start > 5500 logical) — the DevTestPack geometry
        payloads = {}
        songs = []
        for name, seed in (("song_a", 1), ("song_b", 2)):
            payload = _filler(BLOCK_SIZE * 60, seed=seed) + name.encode()
            payloads[name] = payload
            songs.append({
                "song_id": name,
                "mid": b"MThd" + _filler(600, seed),
                "mogg": payload,
                "milo": _filler(81894, seed),
                "png": _filler(32800, seed),
                "dta": f"({name}\n   (name \"{name}\"))\n".encode(),
            })
        out = tmp_path / "multi"
        package_con_multi(out, songs, title="Pack", artist="AutoRB")
        sid, files = read_con_payloads(out / "song_pack.con")
        for name, payload in payloads.items():
            got = files[f"{name}.mogg"]
            assert got == payload, f"{name}.mogg corrupted in multi pack"

    def test_multi_pack_from_con_dir_large_mogg(self, tmp_path):
        """The actual user path: build_ps4_pkg_from_con_dir reads the
        SINGLE cons via read_con_payloads — the read bug corrupted HERE."""
        from autorb.export.con_packer import build_ps4_pkg_from_con_dir
        con_dir = tmp_path / "cons"
        con_dir.mkdir()
        payload = _filler(BLOCK_SIZE * 175, seed=0x5A) + b"END"  # spans a gap
        for name in ("song_x", "song_y"):
            mogg_p = tmp_path / f"{name}.mogg"; mogg_p.write_bytes(payload)
            mid_p = tmp_path / f"{name}.mid"; mid_p.write_bytes(b"MThd" + _filler(600, 9))
            dta_p = tmp_path / f"{name}_songs.dta"
            dta_p.write_bytes(f"({name}\n   (name \"{name}\"))\n".encode())
            out = tmp_path / f"out_{name}"
            package_con(out, name, mogg_p, mid_p, dta_p, title=name, artist="T")
            shutil_copy(out / f"{name}.con", con_dir / f"{name}.con")
        # read each single CON back: payloads must be byte-exact
        for name in ("song_x", "song_y"):
            sid, files = read_con_payloads(con_dir / f"{name}.con")
            assert files[f"{name}.mogg"] == payload, \
                f"{name}: single-CON read corrupted the >170-block mogg"


def shutil_copy(src, dst):
    import shutil
    shutil.copy2(src, dst)


@pytest.mark.devcontainer
def test_gamearchives_reads_multi_pack_correctly(tmp_path):
    """AUTHORITATIVE integration: read the multi-song CON with GameArchives
    (the exact library ForgeTool uses to build the PKG) and require the
    mogg bytes to be byte-identical to what we staged. Skips where the
    .NET runtime / built GameArchives.dll is unavailable."""
    import importlib.util
    import shutil as sh
    import subprocess
    repo = Path(__file__).resolve().parents[1]
    forgetool = repo / "tools" / "forgetool"
    ga_dll = repo / "tools/libforge/LibForge/ForgeTool/bin/Release/GameArchives.dll"
    mono = sh.which("mono")
    mcs = sh.which("mcs")
    if not (forgetool.exists() and ga_dll.exists() and mono and mcs):
        pytest.skip("GameArchives probe requires mono + built LibForge (devcontainer)")

    # build a two-song pack with >170-block moggs
    payload = _filler(BLOCK_SIZE * 175, seed=0xC3) + b"END"
    songs = []
    for name, seed in (("ga_a", 0x11), ("ga_b", 0x22)):
        songs.append({"song_id": name,
                      "mid": b"MThd" + _filler(600, seed),
                      "mogg": payload,
                      "milo": _filler(81894, seed),
                      "png": _filler(32800, seed),
                      "dta": f"({name}\n   (name \"{name}\"))\n".encode()})
    out = tmp_path / "pack"
    package_con_multi(out, songs, title="GA", artist="AutoRB")

    # compile+run the probe
    probe_src = tmp_path / "probe.cs"
    probe_src.write_text("""
using System;
using System.IO;
using GameArchives;
using GameArchives.STFS;
class Dump {
  static void Main(string[] args) {
    var con = STFSPackage.OpenFile(GameArchives.Util.LocalFile(args[0]));
    var songs = con.RootDirectory.GetDirectory("songs");
    foreach (var sd in songs.Dirs) {
      IFile mogg = null;
      if (sd.TryGetFile(sd.Name + ".mogg", out mogg)) {
        var s = mogg.GetStream();
        var buf = new byte[mogg.Size];
        s.Read(buf, 0, (int)mogg.Size);
        File.WriteAllBytes(args[1] + "_" + sd.Name + ".mogg", buf);
      }
    }
  }
}
""")
    work = tmp_path / "probe"
    work.mkdir()
    sh.copy2(ga_dll, work / "GameArchives.dll")
    r = subprocess.run([mcs, "-out:probe.exe", "-r:GameArchives.dll", str(probe_src)],
                       cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r2 = subprocess.run([mono, str(work / "probe.exe"), str(out / "song_pack.con"),
                         str(tmp_path / "ga")], cwd=work,
                        capture_output=True, text=True, timeout=300)
    assert r2.returncode == 0, r2.stderr
    for name in ("ga_a", "ga_b"):
        got = (tmp_path / f"ga_{name}.mogg").read_bytes()
        assert got == payload, f"{name}: GameArchives read corrupted the mogg"
