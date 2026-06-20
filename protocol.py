#!/usr/bin/env python3
"""Minecraft protocol streaming parser.

Canonical: extract_batch.py lines 50-85.
"""
import struct


def rv(data, offset):
    """Read a VarInt from data at offset, return (value, new_offset)."""
    value = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        offset += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return value, offset


def packets(fp):
    """Yield (timestamp, packet_id, payload) tuples from a .tmcpr stream.

    Format: [4 bytes timestamp][4 bytes length][payload bytes]...
    """
    buf = b''
    off = 0
    while True:
        chunk = fp.read(4 * 1024 * 1024)
        if not chunk and not buf:
            break
        if chunk:
            buf += chunk
        while off + 8 <= len(buf):
            ts = struct.unpack('>i', buf[off:off + 4])[0]
            ln = struct.unpack('>i', buf[off + 4:off + 8])[0]
            if ln < 0 or ln > 50_000_000:
                off += 1
                continue
            end = off + 8 + ln
            if end > len(buf):
                if not chunk:
                    break
                break
            pkt = buf[off + 8:end]
            off = end
            if ln == 0:
                continue
            try:
                pid = 0
                s = 0
                p = 0
                while p < len(pkt):
                    b = pkt[p]
                    p += 1
                    pid |= (b & 0x7F) << s
                    if not (b & 0x80):
                        break
                    s += 7
                yield ts, pid, pkt[p:]
            except Exception:
                pass
        if off > 0:
            buf = buf[off:]
            off = 0
        if not chunk and off + 8 > len(buf):
            break
