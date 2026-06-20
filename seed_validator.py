#!/usr/bin/env python3
"""Seed-based biome validator using cubiomes C library via ctypes.

Only loaded when --seed is provided.  Performs exact comparison of
all 16 biome cells in a chunk against cubiomes predictions.
"""
import ctypes
import os
import platform
import sys

# ── Shared library ───────────────────────────────────────────
try:
    import cubiomespi
    _pkg_dir = os.path.dirname(cubiomespi.__file__)
except ImportError:
    _pkg_dir = None


def _load_lib():
    """Find and load the cubiomes shared library."""
    if _pkg_dir:
        if platform.system() == 'Windows':
            path = os.path.join(_pkg_dir, 'lib', 'lib.dll')
        else:
            path = os.path.join(_pkg_dir, 'lib', 'lib.so')
        if os.path.exists(path):
            return ctypes.CDLL(path)
    return None


_lib = _load_lib()
_has_scale4 = False

if _lib:
    _lib.INTERFACE_getBiomeAt.restype = ctypes.c_int
    _lib.INTERFACE_getBiomeAt.argtypes = [
        ctypes.c_int,      # mcVersion
        ctypes.c_uint64,   # seed
        ctypes.c_int,      # dimension
        ctypes.c_int,      # x
        ctypes.c_int,      # y
        ctypes.c_int,      # z
    ]
    # INTERFACE_getBiomeAtScale is NOT in the pip package DLL.
    # It requires recompiling lib with the newlib.c from this repo.
    try:
        _lib.INTERFACE_getBiomeAtScale.restype = ctypes.c_int
        _lib.INTERFACE_getBiomeAtScale.argtypes = [
            ctypes.c_int,      # mcVersion
            ctypes.c_uint64,   # seed
            ctypes.c_int,      # dimension
            ctypes.c_int,      # scale
            ctypes.c_int,      # x
            ctypes.c_int,      # y
            ctypes.c_int,      # z
        ]
        _has_scale4 = True
    except AttributeError:
        pass  # old DLL — will use scale=1 fallback


def is_available():
    """Return True if the cubiomes library was loaded successfully."""
    return _lib is not None


def get_biome_at(mc_version, seed, x, z, y=0):
    """Return the biome ID at world coordinates (x, y, z) for the given seed."""
    if not _lib:
        raise RuntimeError("cubiomes library not available")
    return _lib.INTERFACE_getBiomeAt(mc_version, seed, 0, x, y, z)


def check_biomes_exact(mc_version, seed, cx, cz, packet_biomes):
    """Exact-match all 16 biome cells against cubiomes predictions.

    Uses scale=4 (biome-grid coordinates) when the recompiled DLL is
    available, otherwise falls back to scale=1 (block coordinates).
    """
    if not _lib:
        return 16, []  # no validator, passthrough

    matches = 0
    mismatches = []
    for gx in range(4):
        for gz in range(4):
            if _has_scale4:
                biome_x = cx * 4 + gx
                biome_z = cz * 4 + gz
                expected = _lib.INTERFACE_getBiomeAtScale(
                    mc_version, seed, 0, 4, biome_x, 255, biome_z)
            else:
                # Fallback: scale=1 with block corner coordinates
                bx = cx * 16 + gx * 4
                bz = cz * 16 + gz * 4
                expected = _lib.INTERFACE_getBiomeAt(
                    mc_version, seed, 0, bx, 255, bz)

            # Packet biomes: X→Z→Y order.  Y=0 layer is indices 0..15.
            idx = gz * 4 + gx
            actual = packet_biomes[idx] if idx < len(packet_biomes) else -1

            if expected == actual:
                matches += 1
            else:
                mismatches.append((gx, gz, expected, actual))

    return matches, mismatches


_warned_fallback = False


def maybe_warn_fallback():
    """Print one-time warning if using scale=1 fallback."""
    global _warned_fallback
    if _lib and not _has_scale4 and not _warned_fallback:
        print("WARNING: cubiomes DLL lacks INTERFACE_getBiomeAtScale.",
              "Biome matching uses scale=1 fallback.",
              "Recompile lib.dll / lib.so with newlib.c from this repo for scale=4.",
              file=sys.stderr)
        _warned_fallback = True
