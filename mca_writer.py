#!/usr/bin/env python3
"""MCA (Minecraft Anvil) region file writer.

Canonical: extract_batch.py lines 159-181.
"""
import struct
import io
import zlib
from nbtlib import File as NBTFile

SECTOR = 4096
CS = 32  # chunks per side (32×32 = 1024 per region)


def make_entry(nbt_root):
    """Encode an NBT root compound into an Anvil chunk entry (compressed)."""
    buf = io.BytesIO()
    NBTFile(nbt_root, gzipped=False, byteorder='big').write(buf)
    c = zlib.compress(buf.getvalue())
    return struct.pack('>I', len(c) + 1) + b'\x02' + c


def write_region(path, chunks):
    """Write an .mca region file from {local_index: raw_chunk_bytes} dict."""
    offs = [0] * (CS * CS)
    tss = [0] * (CS * CS)
    sec = 2
    co = {}
    for idx, data in sorted(chunks.items()):
        s = (len(data) + SECTOR - 1) // SECTOR
        co[idx] = (sec, s)
        sec += s
    with open(path, 'wb') as f:
        for idx in range(CS * CS):
            if idx in co:
                o, s = co[idx]
                offs[idx] = (o << 8) | s
            f.write(struct.pack('>I', offs[idx]))
        for idx in range(CS * CS):
            f.write(struct.pack('>I', tss[idx]))
        for idx in range(CS * CS):
            if idx in chunks:
                d = chunks[idx]
                f.write(d)
                pad = (SECTOR - len(d) % SECTOR) % SECTOR
                if pad:
                    f.write(b'\x00' * pad)
