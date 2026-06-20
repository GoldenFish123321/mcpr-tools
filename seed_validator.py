#!/usr/bin/env python3
"""Seed-based biome validator using cubiomes C library via ctypes.

Only loaded when --seed is provided.  Performs exact comparison of
all 16 biome cells in a chunk against cubiomes predictions.
"""
import ctypes
import os
import platform

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


def is_available():
    """Return True if the cubiomes library was loaded successfully."""
    return _lib is not None


def get_biome_at(mc_version, seed, x, z, y=0):
    """Return the biome ID at world coordinates (x, y, z) for the given seed.

    Uses scale=1 (block coordinates).
    """
    if not _lib:
        raise RuntimeError("cubiomes library not available")
    return _lib.INTERFACE_getBiomeAt(mc_version, seed, 0, x, y, z)


def get_biome_at_scale4(mc_version, seed, biome_x, biome_z):
    """Return the biome ID at biome-grid coordinates for the given seed.

    Uses scale=4 — each unit is one 4×4 biome cell.
    biome_x = chunk_x * 4 + grid_x  (grid_x in 0..3)
    biome_z = chunk_z * 4 + grid_z
    """
    if not _lib:
        raise RuntimeError("cubiomes library not available")
    return _lib.INTERFACE_getBiomeAtScale(mc_version, seed, 0, 4, biome_x, 255, biome_z)


def check_biomes_exact(mc_version, seed, cx, cz, packet_biomes):
    """Exact-match all 16 biome cells against cubiomes predictions.

    Packet biomes are in X→Z→Y order (1024 = 4×4×64).
    1.16.5 overworld is 2D — all Y layers share the same values,
    so only the first layer (indices 0..15, Y=0) is compared.

    Grid cell (gx, gz) maps to world corner coordinate:
        block_x = cx * 16 + gx * 4
        block_z = cz * 16 + gz * 4

    Args:
        mc_version:     MCVersion constant (e.g. MCVersion.MC_1_16_5 = 20)
        seed:           64-bit world seed
        cx, cz:         chunk coordinates
        packet_biomes:  list of 1024 biome IDs from the ChunkData packet

    Returns:
        (match_count: int, mismatches: list of (gx, gz, expected, actual))
    """
    if not _lib:
        return 16, []  # no validator, passthrough

    matches = 0
    mismatches = []
    for gx in range(4):
        for gz in range(4):
            # Scale-4 biome coordinates — direct match to the 4×4 grid
            biome_x = cx * 4 + gx
            biome_z = cz * 4 + gz
            expected = _lib.INTERFACE_getBiomeAtScale(mc_version, seed, 0, 4, biome_x, 255, biome_z)

            # Packet biomes: X→Z→Y order.  Y=0 layer is indices 0..15.
            idx = gz * 4 + gx
            actual = packet_biomes[idx] if idx < len(packet_biomes) else -1

            if expected == actual:
                matches += 1
            else:
                mismatches.append((gx, gz, expected, actual))

    return matches, mismatches
