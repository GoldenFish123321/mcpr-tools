#!/usr/bin/env python3
"""Lightweight NBT readers for Minecraft network and disk formats.

Canonical: extract_batch.py lines 90-154.
"""
import struct
from nbtlib import tag as nbt_tag
from protocol import rv


def _rs(data, offset):
    """Read a VarInt-prefixed string (network format)."""
    l, offset = rv(data, offset)
    return data[offset:offset + l].decode('utf-8', 'replace'), offset + l


def _rs_disk(data, offset):
    """Read a 2-byte-prefixed string (disk/Anvil format)."""
    l = struct.unpack('>H', data[offset:offset + 2])[0]
    offset += 2
    return data[offset:offset + l].decode('utf-8', 'replace'), offset + l


class NR:
    """Network-format NBT reader (VarInt string lengths)."""

    def __init__(self, data, offset=0):
        self.d = data
        self.o = offset

    def r(self):
        """Read next tag, return (name, value, new_offset)."""
        t = self.d[self.o]
        self.o += 1
        if t == 0:
            return "", None, self.o
        nl = struct.unpack('>H', self.d[self.o:self.o + 2])[0]
        self.o += 2
        nm = self.d[self.o:self.o + nl].decode('utf-8', 'replace') if nl > 0 else ""
        self.o += nl
        v, self.o = self._p(t, self.o)
        if v is None:
            return "", None, self.o
        return nm, v, self.o

    def _p(self, t, offset):
        d = self.d
        if t == 0:
            return None, offset
        if t == 1:
            return nbt_tag.Byte(d[offset]), offset + 1
        if t == 2:
            return nbt_tag.Short(struct.unpack('>h', d[offset:offset + 2])[0]), offset + 2
        if t == 3:
            return nbt_tag.Int(struct.unpack('>i', d[offset:offset + 4])[0]), offset + 4
        if t == 4:
            return nbt_tag.Long(struct.unpack('>q', d[offset:offset + 8])[0]), offset + 8
        if t == 5:
            return nbt_tag.Float(struct.unpack('>f', d[offset:offset + 4])[0]), offset + 4
        if t == 6:
            return nbt_tag.Double(struct.unpack('>d', d[offset:offset + 8])[0]), offset + 8
        if t == 7:
            l = struct.unpack('>i', d[offset:offset + 4])[0]
            offset += 4
            return nbt_tag.ByteArray(d[offset:offset + l]), offset + l
        if t == 8:
            v, offset = _rs(d, offset)
            return nbt_tag.String(v), offset
        if t == 9:
            ct = d[offset]
            offset += 1
            l = struct.unpack('>i', d[offset:offset + 4])[0]
            offset += 4
            M = {
                1: nbt_tag.Byte, 2: nbt_tag.Short, 3: nbt_tag.Int,
                4: nbt_tag.Long, 5: nbt_tag.Float, 6: nbt_tag.Double,
                7: nbt_tag.ByteArray, 8: nbt_tag.String, 9: nbt_tag.List,
                10: nbt_tag.Compound, 11: nbt_tag.IntArray, 12: nbt_tag.LongArray,
            }
            lst = nbt_tag.List[M.get(ct, nbt_tag.Compound)]()
            for _ in range(l):
                i, offset = self._p(ct, offset)
                lst.append(i)
            return lst, offset
        if t == 10:
            c = nbt_tag.Compound()
            while d[offset] != 0:
                self.o = offset
                nm, v, offset = self.r()
                if v is not None:
                    c[nm] = v
            return c, offset + 1
        if t == 11:
            l = struct.unpack('>i', d[offset:offset + 4])[0]
            offset += 4
            return nbt_tag.IntArray([
                struct.unpack('>i', d[offset + i * 4:offset + i * 4 + 4])[0]
                for i in range(l)
            ]), offset + l * 4
        if t == 12:
            l = struct.unpack('>i', d[offset:offset + 4])[0]
            offset += 4
            return nbt_tag.LongArray([
                struct.unpack('>q', d[offset + i * 8:offset + i * 8 + 8])[0]
                for i in range(l)
            ]), offset + l * 8
        return None, offset


class NRD(NR):
    """Disk-format NBT reader (2-byte string lengths for tag type 8)."""

    def _p(self, t, offset):
        if t == 8:
            v, offset = _rs_disk(self.d, offset)
            return nbt_tag.String(v), offset
        return super()._p(t, offset)


def rnbt(data, offset=0):
    """Read one tag from network-format NBT, return (value, new_offset)."""
    if offset >= len(data):
        return None, offset
    t = data[offset]
    offset += 1
    if t == 0:
        return None, offset
    r = NR(data, offset - 1)
    _, v, no = r.r()
    return v, no


def rnbt_disk(data, offset=0):
    """Read one tag from disk-format NBT, return (value, new_offset)."""
    if offset >= len(data):
        return None, offset
    t = data[offset]
    offset += 1
    if t == 0:
        return None, offset
    r = NRD(data, offset - 1)
    _, v, no = r.r()
    return v, no
