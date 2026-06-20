#!/usr/bin/env python3
"""Seed-based biome validator using cubiomes C library via ctypes.

Only loaded when --seed is provided.  Validates that a chunk's biome
data matches what the world seed predicts for those coordinates.
"""
import ctypes
import os
import platform

# ── Shared library ───────────────────────────────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
# cubiomespi is installed as a pip package; its lib lives there.
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


def is_available():
    """Return True if the cubiomes library was loaded successfully."""
    return _lib is not None


def get_biome_at(mc_version, seed, x, z, y=255):
    """Return the biome ID at world coordinates (x, y, z) for the given seed."""
    if not _lib:
        raise RuntimeError("cubiomes library not available")
    return _lib.INTERFACE_getBiomeAt(mc_version, seed, 0, x, y, z)


def validate_chunk_biomes(mc_version, seed, cx, cz, packet_biomes, threshold=0.15):
    """Check whether a chunk's biome data matches the seed's expected biomes.

    Args:
        mc_version:  MCVersion constant (e.g. MCVersion.MC_1_16_5 = 20)
        seed:        64-bit world seed
        cx, cz:      chunk coordinates
        packet_biomes: list of 1024 biome IDs from the ChunkData packet
        threshold:   minimum fraction of matching sample points (default 0.15).
                     Low threshold avoids rejecting chunks on biome boundaries
                     (where ~50% cells match).  Wrong-seed chunks have near-zero
                     match rate due to unrelated biome maps.

    Returns:
        (passed: bool, match_rate: float)
    """
    if not _lib:
        return True, 1.0  # no validator, let everything through

    samples = 16  # 4×4 grid
    matches = 0
    for gx in range(4):
        for gz in range(4):
            # World block coords: centre of each 4×4 sub-chunk cell
            bx = cx * 16 + gx * 4 + 2
            bz = cz * 16 + gz * 4 + 2

            expected = _lib.INTERFACE_getBiomeAt(mc_version, seed, 0, bx, 255, bz)

            # 1.16.5 overworld is 2D — all four Y layers are identical.
            # Packet biomes are in X→Z→Y order (1024 = 4×4×64).
            # Take Y=0 layer: index = gz*4 + gx  (X fastest, then Z).
            actual = packet_biomes[gz * 4 + gx] if gz * 4 + gx < len(packet_biomes) else -1

            if expected == actual:
                matches += 1

    rate = matches / samples
    return rate >= threshold, rate
