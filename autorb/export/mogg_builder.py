#!/usr/bin/env python

from pathlib import Path
import logging
import struct
import subprocess
import shutil

logger = logging.getLogger(__name__)

# MOGG header constants (see https://milo.ipg.pw/index.php/MOGG_File_Format
# and mtolly/ogg2mogg main.c)
MOGG_VERSION_UNENCRYPTED = 0x0A  # v10 = unencrypted (all RB4 customs use this)
MOGG_MAP_VERSION = 0x10
FRAME_INCREMENT = 20000          # seek-map entries every 20000 samples
SEEK_INCREMENT = 0x8000          # raw-byte stepping used to build the map
PAGE_DURATION_US = 40000         # ogg muxer page target (~2048-3072 sample granules, matching stock RB moggs)


def _parse_ogg_pages(data: bytes) -> list:
    """
    Parse an Ogg bitstream and return [(file_offset, granulepos), ...] for each page.

    granulepos is signed; header pages carry -1, audio pages carry the PCM
    sample position of the last packet completed on that page.
    """
    pages = []
    pos = 0
    n = len(data)
    while pos < n:
        if data[pos:pos + 4] != b"OggS":
            idx = data.find(b"OggS", pos)
            if idx == -1:
                break
            pos = idx
        if pos + 27 > n:
            break
        granule = int.from_bytes(data[pos + 6:pos + 14], "little", signed=True)
        segs = data[pos + 26]
        if pos + 27 + segs > n:
            break
        payload = sum(data[pos + 27:pos + 27 + segs])
        pages.append((pos, granule))
        pos = pos + 27 + segs + payload
    return pages


def read_mogg_duration_ms(mogg_path: str | Path) -> int:
    """
    Return the audio duration of a MOGG in milliseconds, computed from the
    final Ogg granule position and the Vorbis sample rate. Used to populate
    songs.dta's (song_length ...) so metadata matches the actual audio.
    """
    data = Path(mogg_path).read_bytes()
    header_size = int.from_bytes(data[4:8], "little")
    ogg = data[header_size:]
    pos = ogg.find(b"OggS")
    if pos < 0 or pos + 27 > len(ogg):
        raise ValueError(f"Invalid MOGG (no OggS): {mogg_path}")
    segs = ogg[pos + 26]
    laces = list(ogg[pos + 27:pos + 27 + segs])
    packet = b""
    for l in laces:
        packet += ogg[pos + 27 + segs:pos + 27 + segs + l]
        if l < 255:
            break
    if len(packet) < 30 or packet[:7] != b"\x01vorbis":
        raise ValueError(f"Invalid MOGG (bad Vorbis id header): {mogg_path}")
    rate = int.from_bytes(packet[12:16], "little")
    pages = _parse_ogg_pages(ogg)
    granules = [g for _, g in pages if g >= 0]
    if not granules:
        raise ValueError(f"Invalid MOGG (no audio pages): {mogg_path}")
    return int(granules[-1] * 1000 // rate)


def wrap_ogg_as_mogg(ogg_bytes: bytes) -> bytes:
    """
    Prepend the Harmonix MOGG header to a multi-channel Ogg Vorbis bitstream.

    Layout (all little-endian):
        u32 version = 0x0A (unencrypted)
        u32 header size  (byte offset where the Ogg data begins)
        u32 map version  = 0x10
        u32 seek interval = 20000
        u32 entry count
        [u32 byte offset, u32 sample] * entry count   (the OggMap)
        ... raw Ogg Vorbis bytes, byte-identical to the input
    """
    pages = _parse_ogg_pages(ogg_bytes)
    audio_samples = [g for _, g in pages if g >= 0]
    if not audio_samples:
        raise ValueError("No audio pages found in Ogg data; cannot build MOGG.")
    total_samples = audio_samples[-1]
    total_bytes = len(ogg_bytes)

    # For every 0x8000-byte increment of the file, record the granule position
    # of the page containing it. Header pages (-1) are kept as 0xFFFFFFFF so
    # they never satisfy the `<= desired sample` selection below.
    seek_bytes = []
    seek_samples = []
    i = 0
    while i * SEEK_INCREMENT < total_bytes:
        x = i * SEEK_INCREMENT
        sample = 0xFFFFFFFF
        for offset, granule in pages:
            if offset <= x:
                sample = granule if granule >= 0 else 0xFFFFFFFF
            else:
                break
        seek_bytes.append(i * SEEK_INCREMENT)
        seek_samples.append(sample)
        i += 1

    # For each 20000-sample frame, pick the last seek entry whose sample is
    # at or before the frame start (mirrors ogg2mogg's two-pass table build).
    entry_count = (total_samples + FRAME_INCREMENT - 1) // FRAME_INCREMENT
    table = []
    for k in range(entry_count):
        desired = k * FRAME_INCREMENT
        byte_offset = 0
        sample = 0
        for b, s in zip(seek_bytes, seek_samples):
            if s <= desired:
                byte_offset, sample = b, s
            else:
                break
        table.append((byte_offset, sample))

    header = struct.pack(
        "<IIIII",
        MOGG_VERSION_UNENCRYPTED,
        20 + 8 * len(table),
        MOGG_MAP_VERSION,
        FRAME_INCREMENT,
        len(table),
    )
    for byte_offset, sample in table:
        header += struct.pack("<II", byte_offset, sample)

    return header + ogg_bytes


def build_mogg_from_stems(stems_dir: str | Path, output_dir: Path, song_id: str, skip_mogg: bool = False) -> Path:
    """
    Combines stem WAV files into a multi-channel Harmonix MOGG audio container.

    Each stem becomes a stereo pair (mono stems are duplicated to L/R, larger
    channel layouts are downmixed), producing a single multi-channel Ogg Vorbis
    bitstream that is then wrapped with the proprietary MOGG header. The channel
    order matches songs.dta: drums 0-1, bass 2-3, guitar 4-5, vocals 6-7.
    """
    stems_path = Path(stems_dir)
    mogg_path = output_dir / f"{song_id}.mogg"

    if skip_mogg:
        if mogg_path.exists():
            logger.info(f"Skipping MOGG creation. Using existing MOGG at {mogg_path}")
            return mogg_path
        else:
            raise FileNotFoundError(f"Requested to skip MOGG building, but existing MOGG not found at {mogg_path}")

    stem_names = ["drums", "bass", "other", "vocals"]
    input_files = []

    for name in stem_names:
        p = stems_path / f"{name}.wav"
        if p.exists():
            input_files.append(p)

    if not input_files:
        input_files = sorted(list(stems_path.glob("*.wav")))

    if input_files:
        logger.info(f"Combining {len(input_files)} stems into multi-channel MOGG container via ffmpeg.")
        ogg_tmp = output_dir / f"{song_id}.tmp.ogg"
        cmd = ["ffmpeg", "-y"]
        for f in input_files:
            cmd.extend(["-i", str(f)])

        n = len(input_files)
        # Normalize every input to stereo, then merge into a single multi-channel stream.
        filter_parts = [f"[{i}:a]aformat=channel_layouts=stereo[s{i}]" for i in range(n)]
        filter_parts.append("".join(f"[s{i}]" for i in range(n)) + f"amerge=inputs={n}[aout]")

        # Explicitly force the 'ogg' format muxer so ffmpeg accepts the .ogg extension.
        # -page_duration forces small pages (~2048-3072 sample granules) matching
        # stock Harmonix moggs; ffmpeg's default libvorbis paging emits ~1s/56KB
        # pages that Rock Band's Milkshake audio engine cannot decode reliably.
        cmd.extend([
            "-filter_complex", ";".join(filter_parts),
            "-map", "[aout]",
            "-c:a", "libvorbis",
            "-q:a", "5",
            "-page_duration", str(PAGE_DURATION_US),
            "-f", "ogg",
            str(ogg_tmp)
        ])

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg multi-channel merge failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed to build MOGG container: {result.stderr}")

        try:
            ogg_bytes = ogg_tmp.read_bytes()
        finally:
            ogg_tmp.unlink(missing_ok=True)

        if not ogg_bytes:
            raise RuntimeError("FFmpeg produced an empty Ogg file.")

        mogg_bytes = wrap_ogg_as_mogg(ogg_bytes)
        mogg_path.write_bytes(mogg_bytes)
        logger.info(f"Built MOGG (v{MOGG_VERSION_UNENCRYPTED}, {len(mogg_bytes)} bytes) at {mogg_path}")
    else:
        logger.warning("No stem WAV files found. Generating placeholder MOGG container.")
        mogg_path.write_bytes(b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 200)

    return mogg_path
