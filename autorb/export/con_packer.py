#!/usr/bin/env python
from pathlib import Path
import shutil
import click
import os
import struct
import subprocess
import sys
import tempfile

BLOCK_SIZE = 0x1000
MILO_A_MAGIC = 0xCABEDEAF
ADDE_PADDING = b'\xad\xde\xad\xde'

def repair_milo(milo_bytes: bytes) -> bytes:
    magic = int.from_bytes(milo_bytes[0:4], 'little')
    if magic != MILO_A_MAGIC: return milo_bytes
    offset = int.from_bytes(milo_bytes[4:8], 'little')
    block_count = int.from_bytes(milo_bytes[8:12], 'little')
    if block_count == 0: return milo_bytes
    total_size = sum(int.from_bytes(milo_bytes[0x10 + i * 4: 0x14 + i * 4], 'little') for i in range(block_count))
    data_region = milo_bytes[offset: offset + total_size]
    if len(data_region) >= 4 and data_region[-4:] == ADDE_PADDING: return milo_bytes
    out = bytearray(milo_bytes)
    last_field = 0x10 + (block_count - 1) * 4
    cur = int.from_bytes(milo_bytes[last_field:last_field + 4], 'little')
    out[last_field:last_field + 4] = (cur + 4).to_bytes(4, 'little')
    out.extend(ADDE_PADDING)
    return bytes(out)

def logical_to_physical(logical: int) -> int:
    block_adjust = 0
    if logical >= 0xAA: block_adjust += (logical // 0xAA) + 1
    if logical >= 0x70E4: block_adjust += (logical // 0x70E4) + 1
    return logical + block_adjust

def set_entry_name(con_data: bytearray, ft_offset: int, entry_idx: int, new_name: str):
    entry_addr = ft_offset + entry_idx * 0x40
    name_bytes = new_name.encode('ascii', errors='ignore')[:0x28]
    con_data[entry_addr : entry_addr + 0x28] = b'\x00' * 0x28
    con_data[entry_addr : entry_addr + len(name_bytes)] = name_bytes
    is_dir = (con_data[entry_addr + 0x28] & 0x80) != 0
    con_data[entry_addr + 0x28] = (len(name_bytes) & 0x3F) | (0x80 if is_dir else 0x40)

def set_entry_allocation(con_data: bytearray, ft_offset: int, entry_idx: int, start_block: int, size: int):
    entry_addr = ft_offset + entry_idx * 0x40
    block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
    con_data[entry_addr + 0x34 : entry_addr + 0x38] = size.to_bytes(4, 'big')
    con_data[entry_addr + 0x29 : entry_addr + 0x2C] = block_count.to_bytes(3, 'little')
    con_data[entry_addr + 0x2C : entry_addr + 0x2F] = block_count.to_bytes(3, 'little')
    con_data[entry_addr + 0x2F : entry_addr + 0x32] = start_block.to_bytes(3, 'little')

def patch_stfs_header_metadata(con_data: bytearray, title: str, artist: str):
    title_encoded = title.encode('utf-16-be')
    con_data[0x43D : 0x43D + len(title_encoded)] = title_encoded
    artist_encoded = artist.encode('utf-16-be')
    con_data[0x413 : 0x413 + len(artist_encoded)] = artist_encoded

def package_con(
    output_dir: str | Path,
    song_id: str,
    mogg_path: Path,
    midi_path: Path,
    dta_path: Path,
    title: str = "Open Road Song",
    artist: str = "Eve 6",
    album_art_bytes: bytes | None = None
) -> Path:
    output_path = Path(output_dir)
    songs_root = output_path / "songs"
    song_staging_dir = songs_root / song_id
    gen_staging_dir = song_staging_dir / "gen"
    gen_staging_dir.mkdir(parents=True, exist_ok=True)

    target_dta_parent = songs_root / "songs.dta"
    target_dta_sub = song_staging_dir / "songs.dta"

    if dta_path.resolve() != target_dta_parent.resolve():
        shutil.copy2(dta_path, target_dta_parent)
    shutil.copy2(target_dta_parent, target_dta_sub)

    target_mogg = song_staging_dir / f"{song_id}.mogg"
    target_mid = song_staging_dir / f"{song_id}.mid"

    if mogg_path.resolve() != target_mogg.resolve():
        shutil.copy2(mogg_path, target_mogg)
    if midi_path.resolve() != target_mid.resolve():
        shutil.copy2(midi_path, target_mid)

    template_con = Path(__file__).parent / "data/template.con"
    milo_bin = Path(__file__).parent / "data/template_milo.bin"
    png_bin = Path(__file__).parent / "data/template_png.bin"

    con_file_path = output_path / f"{song_id}.con"

    if not template_con.exists():
        raise FileNotFoundError(f"Template CON not found at {template_con}")

    shutil.copy2(template_con, con_file_path)
    con_data = bytearray(con_file_path.read_bytes())
    ft_offset = 0xC000

    patch_stfs_header_metadata(con_data, title, artist)

    target_milo = gen_staging_dir / f"{song_id}.milo_xbox"
    target_png = gen_staging_dir / f"{song_id}_keep.png_xbox"

    raw_milo = milo_bin.read_bytes() if milo_bin.exists() else b''
    repaired_milo = repair_milo(raw_milo)
    target_milo.write_bytes(repaired_milo)

    png_bytes = album_art_bytes if album_art_bytes is not None else (png_bin.read_bytes() if png_bin.exists() else b'')
    target_png.write_bytes(png_bytes)

    dta_content = target_dta_parent.read_bytes()
    midi_content = target_mid.read_bytes()
    mogg_content = target_mogg.read_bytes()
    milo_content = repaired_milo
    png_content = target_png.read_bytes()

    set_entry_name(con_data, ft_offset, 1, song_id)
    set_entry_name(con_data, ft_offset, 4, f"{song_id}.mid")
    set_entry_name(con_data, ft_offset, 5, f"{song_id}.mogg")
    set_entry_name(con_data, ft_offset, 6, f"{song_id}.milo_xbox")
    set_entry_name(con_data, ft_offset, 7, f"{song_id}_keep.png_xbox")

    dta_size = len(dta_content)
    dta_blocks = (dta_size + BLOCK_SIZE - 1) // BLOCK_SIZE
    mid_size = len(midi_content)
    mid_blocks = (mid_size + BLOCK_SIZE - 1) // BLOCK_SIZE
    mogg_size = len(mogg_content)
    mogg_blocks = (mogg_size + BLOCK_SIZE - 1) // BLOCK_SIZE
    milo_size = len(milo_content)
    milo_blocks = (milo_size + BLOCK_SIZE - 1) // BLOCK_SIZE
    png_size = len(png_content)
    png_blocks = (png_size + BLOCK_SIZE - 1) // BLOCK_SIZE
    
    dta_start = 1
    mid_start = dta_start + dta_blocks
    mogg_start = mid_start + mid_blocks
    milo_start = mogg_start + mogg_blocks
    png_start = milo_start + milo_blocks

    set_entry_allocation(con_data, ft_offset, 3, dta_start, dta_size)
    set_entry_allocation(con_data, ft_offset, 4, mid_start, mid_size)
    set_entry_allocation(con_data, ft_offset, 5, mogg_start, mogg_size)
    set_entry_allocation(con_data, ft_offset, 6, milo_start, milo_size)
    set_entry_allocation(con_data, ft_offset, 7, png_start, png_size)

    total_allocated = 1 + dta_blocks + mid_blocks + mogg_blocks + milo_blocks + png_blocks
    con_data[0x395 : 0x399] = total_allocated.to_bytes(4, 'big')
    con_data[0x399 : 0x39D] = (0).to_bytes(4, 'big')

    def write_payload(start_block: int, content: bytes):
        size = len(content)
        block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
        for i in range(block_count):
            payload_offset = 0xC000 + logical_to_physical(start_block + i) * BLOCK_SIZE
            chunk = content[i * BLOCK_SIZE: (i + 1) * BLOCK_SIZE]
            chunk = chunk + b'\x00' * (BLOCK_SIZE - len(chunk))
            end = payload_offset + BLOCK_SIZE
            if len(con_data) < end:
                con_data.extend(b'\x00' * (end - len(con_data)))
            con_data[payload_offset: end] = chunk

    write_payload(dta_start, dta_content)
    write_payload(mid_start, midi_content)
    write_payload(mogg_start, mogg_content)
    write_payload(milo_start, milo_content)
    write_payload(png_start, png_content)

    con_file_path.write_bytes(con_data)
    os.utime(con_file_path, None)
    click.echo(f"Successfully patched CON: {con_file_path}")
    return con_file_path


def read_con_payloads(con_path: Path) -> tuple[str | None, dict]:
    """Parse an AutoRB-produced CON and return (song_id, {filename: bytes}).

    Uses the same file-table convention our writer produces (name ASCII at
    entry offset 0..0x28, flag byte at +0x28, size BE at +0x34, start block
    LE at +0x2F). Payload bytes are extracted via logical_to_physical().
    """
    data = Path(con_path).read_bytes()
    FT = 0xC000
    entries = []
    for i in range(64):
        a = FT + i * 0x40
        if a + 0x40 > len(data):
            break
        flag = data[a + 0x28]
        if flag == 0:
            continue
        name = data[a:a + 0x28].split(b'\x00')[0].decode('ascii', 'ignore')
        is_dir = (flag & 0x80) != 0
        size = int.from_bytes(data[a + 0x34:a + 0x38], 'big')
        start = int.from_bytes(data[a + 0x2F:a + 0x32], 'little')
        entries.append((name, is_dir, start, size))

    files = {}
    song_id = None
    for name, is_dir, start, size in entries:
        if is_dir:
            if name not in ("songs", "gen") and song_id is None:
                song_id = name
            continue
        off = FT + logical_to_physical(start) * BLOCK_SIZE
        files[name] = data[off:off + size]
    if song_id is None:
        for k in files:
            if k.endswith(".mid"):
                song_id = k[:-4]
                break
    return song_id, files


def combine_songs_dta(dta_list: list[bytes]) -> bytes:
    """Concatenate multiple per-song ``songs.dta`` payloads into one file.

    Rock Band's ``songs.dta`` is a top-level list of ``(song_id ...)`` forms,
    so simple concatenation of the individual payloads is valid.
    """
    return b"".join(dta_list)


def package_con_multi(output_dir: str | Path, songs: list[dict],
                      title: str = "Custom Song Pack", artist: str = "AutoRB") -> Path:
    """Build a single multi-song CON from a list of song payload dicts.

    Each ``song`` dict must contain: ``song_id``, ``mid`` (bytes), ``mogg``
    (bytes), ``milo`` (bytes), ``png`` (bytes), ``dta`` (bytes, the per-song
    ``songs.dta``). The per-song ``dta`` payloads are combined into a single
    shared ``songs.dta`` at the ``songs/`` root while each song retains its own
    mid/mogg/milo/png under ``songs/<song_id>/``.

    The STFS file-table entries follow the GameArchives layout exactly:
      * name ASCII at offset 0x00 (length ``flags & 0x3f``)
      * flags at 0x28 (0x80 = directory, 0x40 = file => sequential blocks)
      * numBlocks (uint24 LE) at 0x29
      * startBlock (uint24 LE) at 0x2F
      * parentDir (int16 BE) at 0x32  -> ordinal of the parent directory
      * size (uint32 BE) at 0x34
    Ordinals are assigned by entry position (root = -1 at 0xFFFF); the directory
    reader walks the table top-to-bottom and breaks at the first empty entry, so
    entries must be contiguous from index 0.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    con_file_path = output_path / "song_pack.con"

    template_con = Path(__file__).parent / "data/template.con"
    if not template_con.exists():
        raise FileNotFoundError(f"Template CON not found at {template_con}")

    con_data = bytearray(template_con.read_bytes())
    ft_offset = 0xC000
    patch_stfs_header_metadata(con_data, title, artist)

    combined_dta = combine_songs_dta([s["dta"] for s in songs if s.get("dta")])

    # Ordered plan. Directory ordinals == plan index; each entry's parentDir
    # references the parent's plan index. Layout mirrors stock RB CONs:
    #   songs/ (root)
    #     songs.dta
    #     <song>/            (parent: songs)
    #       gen/             (parent: <song>)
    #         <song>.milo_xbox
    #         <song>_keep.png_xbox
    #       <song>.mid
    #       <song>.mogg
    plan: list[tuple[str, bool, bytes, int]] = [("songs", True, b"", -1)]
    plan.append(("songs.dta", False, combined_dta, 0))
    for s in songs:
        sid = s["song_id"]
        song_idx = len(plan)
        plan.append((sid, True, b"", 0))                 # song dir -> songs
        gen_idx = len(plan)
        plan.append(("gen", True, b"", song_idx))        # gen dir -> song dir
        plan.append((f"{sid}.mid", False, s["mid"], song_idx))
        plan.append((f"{sid}.mogg", False, s["mogg"], song_idx))
        plan.append((f"{sid}.milo_xbox", False, s["milo"], gen_idx))
        plan.append((f"{sid}_keep.png_xbox", False, s["png"], gen_idx))

    if len(plan) > 64:
        raise ValueError(f"Too many songs for one CON file table: {len(plan)} > 64")

    # Zero the file-table block so stale template entries don't leak.
    for i in range(64):
        entry_addr = ft_offset + i * 0x40
        if entry_addr + 0x40 <= len(con_data):
            con_data[entry_addr:entry_addr + 0x40] = b'\x00' * 0x40

    # Assign sequential data blocks starting right after the 1-block table.
    next_block = 1
    written = []  # (idx, start_block, content)
    for idx, (name, is_dir, content, parent) in enumerate(plan):
        entry_addr = ft_offset + idx * 0x40
        namelen = min(len(name), 0x28)
        con_data[entry_addr:entry_addr + namelen] = name[:namelen].encode('latin-1')
        if is_dir:
            flags = 0x80 | namelen
            size = 0
            blocks = 0
            start_block = 0
        else:
            flags = 0x40 | namelen   # 0x40 => sequential blocks (no hash table needed)
            size = len(content)
            blocks = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
            start_block = next_block if size > 0 else 0
            next_block += blocks
        con_data[entry_addr + 0x28] = flags
        con_data[entry_addr + 0x29:entry_addr + 0x2C] = blocks.to_bytes(3, 'little')
        con_data[entry_addr + 0x2C:entry_addr + 0x2F] = blocks.to_bytes(3, 'little')
        con_data[entry_addr + 0x2F:entry_addr + 0x32] = start_block.to_bytes(3, 'little')
        parent_field = 0xFFFF if parent < 0 else parent
        con_data[entry_addr + 0x32:entry_addr + 0x34] = parent_field.to_bytes(2, 'big')
        con_data[entry_addr + 0x34:entry_addr + 0x38] = size.to_bytes(4, 'big')
        if not is_dir and size > 0:
            written.append((start_block, content))

    total_allocated = next_block
    con_data[0x395:0x399] = total_allocated.to_bytes(4, 'big')
    con_data[0x399:0x39D] = (0).to_bytes(4, 'big')

    def write_payload(start_block: int, content: bytes):
        size = len(content)
        block_count = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
        for i in range(block_count):
            payload_offset = 0xC000 + logical_to_physical(start_block + i) * BLOCK_SIZE
            chunk = content[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]
            chunk = chunk + b'\x00' * (BLOCK_SIZE - len(chunk))
            end = payload_offset + BLOCK_SIZE
            if len(con_data) < end:
                con_data.extend(b'\x00' * (end - len(con_data)))
            con_data[payload_offset:end] = chunk

    for start_block, content in written:
        write_payload(start_block, content)

    con_file_path.write_bytes(con_data)
    os.utime(con_file_path, None)
    click.echo(f"Successfully built combined CON with {len(songs)} song(s): {con_file_path}")
    return con_file_path

def _find_forgetool() -> Path:
    """Locates the `tools/forgetool` wrapper.

    `--build-pkg` requires a full git clone (the ForgeTool .NET binaries are
    not shipped in the pip wheel), so the tool is not installed with `autorb`.
    This searches:
      1. The current working directory and its immediate children (the CLI is
         often run from a parent of the clone, e.g. `temp/` with the clone at
         `temp/RockBandAutoSongLevelCreator/`).
      2. Every ancestor directory of the CWD (walking up to the filesystem root).
      3. sys.prefix / sys.base_prefix.
    The first hit wins.
    """
    cwd = Path.cwd()
    seen: set[Path] = set()
    candidates: list[Path] = []

    # (1) CWD and its immediate child dirs.
    candidates.append(cwd / "tools" / "forgetool")
    if cwd.is_dir():
        for child in cwd.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                candidates.append(child / "tools" / "forgetool")

    # (2) Ancestors of the CWD, from closest to root.
    for ancestor in cwd.parents:
        candidates.append(ancestor / "tools" / "forgetool")

    # (3) Interpreter roots.
    candidates.append(Path(sys.prefix) / "tools" / "forgetool")
    candidates.append(Path(sys.base_prefix) / "tools" / "forgetool")

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "ForgeTool not found. `--build-pkg` requires a full git clone with the "
        "vendored toolchain built:\n"
        "  git clone https://github.com/free5ty1e/RockBandAutoSongLevelCreator.git\n"
        "  cd RockBandAutoSongLevelCreator\n"
        "  tools/build_forgetool.sh\n"
        "  # then run the CLI from the clone, or from anywhere within/near it "
        "(the tool is auto-discovered by searching the CWD, its child dirs, and its ancestors).\n"
        "Building the toolchain needs the .NET SDK 8 (`dotnet`) and mono-devel, "
        "e.g.: `sudo apt install mono-devel` (or `brew install mono` on macOS), "
        "plus `brew install --cask dotnet-sdk@8` (macOS) / the .NET 8 SDK installer (Linux).\n"
        "`tools/build_forgetool.sh` checks for these and prints install instructions."
    )


def build_ps4_pkg(con_path: Path, output_dir: Path, pkg_id_16: str) -> Path:
    pkg_dir = output_dir / "pkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    forgetool = _find_forgetool()
    cmd = [
        str(forgetool),
        "con2pkg",
        "--id", pkg_id_16,
        "--desc", f"Custom Song - {pkg_id_16}",
        str(con_path),
        str(pkg_dir)
    ]
    click.echo(f"Running ForgeTool: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        click.echo(f"Error during PKG conversion: {result.stderr}", err=True)
        raise RuntimeError(f"ForgeTool failed to build PKG: {result.stderr}")
    # ForgeTool names the PKG with the full 36-char Content ID, not the
    # 16-char custom suffix we pass via --id.
    pkg_file = pkg_dir / f"UP8802-CUSA02084_00-{pkg_id_16}.pkg"
    return pkg_file


def build_ps4_pkg_from_con_dir(con_dir: Path, pkg_id_16: str | None = None) -> Path:
    """
    Package all .con files in a directory into a single PS4 PKG.

    Each individual CON is parsed to extract its song payloads (mid/mogg/
    milo/png) and per-song ``songs.dta``. The per-song DTAs are combined into
    one shared ``songs.dta`` and all songs are repacked into a single
    multi-song CON, which ForgeTool then converts into one PS4 PKG installer.
    """
    con_dir = Path(con_dir)
    con_files = sorted(p for p in con_dir.glob("*.con") if p.stem != "song_pack")
    if not con_files:
        raise FileNotFoundError(f"No .con files found in {con_dir}")

    click.echo(f"Found {len(con_files)} CON file(s) to package: {[f.name for f in con_files]}")

    songs = []
    for cf in con_files:
        try:
            song_id, files = read_con_payloads(cf)
        except Exception as e:
            click.echo(f"  Skipping {cf.name}: failed to parse CON ({e})", err=True)
            continue
        if song_id is None or "songs.dta" not in files:
            click.echo(f"  Skipping {cf.name}: not a valid AutoRB CON", err=True)
            continue
        songs.append({
            "song_id": song_id,
            "mid": files.get(f"{song_id}.mid", b""),
            "mogg": files.get(f"{song_id}.mogg", b""),
            "milo": files.get(f"{song_id}.milo_xbox", b""),
            "png": files.get(f"{song_id}_keep.png_xbox", b""),
            "dta": files["songs.dta"],
        })
        click.echo(f"  Loaded song '{song_id}' from {cf.name}")

    if not songs:
        raise RuntimeError("No valid AutoRB CON files found to package")

    # Derive a pack title/artist from the first song for the CON header.
    pack_title = songs[0]["song_id"].replace("_", " ").title()
    pack_artist = "AutoRB"

    # If no PKG ID provided, auto-generate from the first CON filename.
    if pkg_id_16 is None:
        pkg_id_16 = songs[0]["song_id"].upper().replace("-", "").replace("_", "")[:16].ljust(16, "0")

    combined_con = package_con_multi(con_dir, songs, title=pack_title, artist=pack_artist)
    return build_ps4_pkg(combined_con, con_dir, pkg_id_16)
