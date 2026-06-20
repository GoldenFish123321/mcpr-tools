#!/usr/bin/env python3
"""Diagnostic: scan all mcpr files for ChunkData packets at a specific chunk coordinate.
Reports: filename, timestamp, full/partial, biomes (first 10), seed match result.
"""
import zipfile, struct, os, sys, glob

from protocol import rv, packets
from nbt_reader import rnbt

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: diag_chunk.py <mcpr_dir> <cx> <cz> [--seed N]")
        sys.exit(1)

    mcpr_dir = sys.argv[1]
    target_cx = int(sys.argv[2])
    target_cz = int(sys.argv[3])
    seed = None
    if '--seed' in sys.argv:
        idx = sys.argv.index('--seed')
        seed = int(sys.argv[idx + 1])

    if seed is not None:
        from seed_validator import check_biomes_exact, is_available
        if is_available():
            from cubiomespi import MCVersion
            MC_VER = MCVersion.MC_1_16_5
            print(f"Seed: {seed} — biome validation enabled\n")
        else:
            print("WARNING: cubiomes not available, --seed ignored\n")
            seed = None

    files = sorted(glob.glob(os.path.join(mcpr_dir, '*.mcpr')))
    print(f"Scanning {len(files)} mcpr files for chunk({target_cx},{target_cz})...\n")

    total_hits = 0
    for fp in files:
        fn = os.path.basename(fp)
        try:
            with zipfile.ZipFile(fp) as zf:
                try:
                    recording = zf.read('recording.tmcpr')
                except KeyError:
                    continue
                for ts, pid, payload in packets(recording):
                    if pid != 0x22:
                        continue
                    o = 0
                    cx = struct.unpack('>i', payload[o:o+4])[0]; o += 4
                    cz = struct.unpack('>i', payload[o:o+4])[0]; o += 4
                    if cx != target_cx or cz != target_cz:
                        continue
                    total_hits += 1
                    full = payload[o] != 0; o += 1
                    mask, o = rv(payload, o)

                    # Read biomes
                    hm, o = rnbt(payload, o)
                    biomes = None
                    if full:
                        bc, o = rv(payload, o)
                        biomes = []
                        for _ in range(bc):
                            if o >= len(payload):
                                break
                            b, o = rv(payload, o)
                            biomes.append(b)

                    # Seed match check
                    seed_result = "N/A"
                    if seed is not None and biomes:
                        matched, info = check_biomes_exact(MC_VER, seed, cx, cz, biomes)
                        seed_result = f"{matched}/16 match" if matched == 16 else f"{matched}/16 MISMATCH {info[:3] if info else ''}"

                    kind = "FULL" if full else "PARTIAL"
                    bio_preview = biomes[:10] if biomes else "NONE"
                    sections = bin(mask).count('1') if mask else 0
                    print(f"  {fn:45s} ts={ts:>10d}  {kind:7s}  sections={sections}  biomes={bio_preview}  seed={seed_result}")
        except Exception as e:
            print(f"  {fn}: ERROR {e}")

    print(f"\nTotal hits for chunk({target_cx},{target_cz}): {total_hits}")
