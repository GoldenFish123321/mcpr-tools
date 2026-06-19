#!/usr/bin/env python3
"""Filter End/Nether chunks from MCA files. Biome-only — no block heuristics."""
import os, sys, struct, zlib, shutil

SCAN_DIR = sys.argv[1] if len(sys.argv) > 1 else 'output_survival/survival_world/region'
CLEAN_DIR = sys.argv[2] if len(sys.argv) > 2 else 'output_survival/survival_world_clean/region'

SECTOR = 4096

END_BIOMES = {9, 40, 41, 42, 43}           # the_end, small_end_islands, end_midlands, end_highlands, end_barrens
NETHER_BIOMES = {8, 170, 171, 172, 173}    # nether_wastes, soul_sand_valley, crimson_forest, warped_forest, basalt_deltas


def extract_biomes_from_nbt(nbt_data):
    """Extract biome IDs from chunk NBT. Returns set of biome ints or None."""
    idx = nbt_data.find(b'Biomes')
    if idx == -1 or idx < 5:
        return None
    # TAG_IntArray(0x0b) + 2-byte name_len + "Biomes"(6) + 4-byte count + ints
    tag_pos = idx - 3
    if tag_pos < 0 or nbt_data[tag_pos] != 0x0b:
        return None
    data_start = idx + 6
    if data_start + 4 > len(nbt_data):
        return None
    count = struct.unpack('>i', nbt_data[data_start:data_start+4])[0]
    if count < 1 or count > 4096:
        return None
    biomes = set()
    for i in range(min(count, 1024)):
        off = data_start + 4 + i * 4
        if off + 4 > len(nbt_data):
            break
        biomes.add(struct.unpack('>i', nbt_data[off:off+4])[0])
    return biomes


def classify_chunk(nbt_data):
    """Returns 'overworld', 'end', or 'nether'. Biome-only."""
    biomes = extract_biomes_from_nbt(nbt_data)
    if not biomes:
        return 'overworld'
    if biomes & END_BIOMES:
        return 'end'
    if biomes & NETHER_BIOMES:
        return 'nether'
    return 'overworld'


def filter_region(src_path, dst_path):
    """Read MCA, keep only overworld chunks, write clean MCA."""
    with open(src_path, 'rb') as f:
        header = f.read(8192)

    kept_chunks = {}
    stats = {'total': 0, 'kept': 0, 'end': 0, 'nether': 0}

    for idx in range(1024):
        off_field = struct.unpack('>I', header[idx*4:idx*4+4])[0]
        if off_field == 0:
            continue
        sector_off = off_field >> 8
        try:
            with open(src_path, 'rb') as f:
                f.seek(sector_off * SECTOR)
                length = struct.unpack('>I', f.read(4))[0]
                if length < 2 or length > 10_000_000:
                    continue
                comp_type = f.read(1)[0]
                if comp_type != 2:
                    continue
                compressed = f.read(length - 1)
                nbt = zlib.decompress(compressed)
                raw_data = struct.pack('>I', length) + bytes([comp_type]) + compressed
        except:
            continue

        stats['total'] += 1
        dim = classify_chunk(nbt)

        if dim == 'overworld':
            kept_chunks[idx] = raw_data
            stats['kept'] += 1
        elif dim == 'end':
            stats['end'] += 1
        elif dim == 'nether':
            stats['nether'] += 1

    if stats['kept'] == 0:
        return stats

    # Write clean MCA
    offsets = [0] * 1024
    coord = {}
    sector = 2

    for idx in sorted(kept_chunks.keys()):
        sectors_needed = (len(kept_chunks[idx]) + SECTOR - 1) // SECTOR
        coord[idx] = (sector, sectors_needed)
        sector += sectors_needed

    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    with open(dst_path, 'wb') as f:
        for idx in range(1024):
            f.write(struct.pack('>I', (coord[idx][0] << 8) | coord[idx][1] if idx in coord else 0))
        for idx in range(1024):
            f.write(struct.pack('>I', 0))  # timestamps
        for idx in range(1024):
            if idx in kept_chunks:
                data = kept_chunks[idx]
                f.write(data)
                pad = (SECTOR - len(data) % SECTOR) % SECTOR
                if pad:
                    f.write(b'\x00' * pad)

    return stats


def main():
    if os.path.exists(CLEAN_DIR):
        shutil.rmtree(CLEAN_DIR)
    os.makedirs(CLEAN_DIR, exist_ok=True)

    mca_files = sorted(f for f in os.listdir(SCAN_DIR) if f.endswith('.mca'))
    total_stats = {'total': 0, 'kept': 0, 'end': 0, 'nether': 0}

    for fname in mca_files:
        src = os.path.join(SCAN_DIR, fname)
        dst = os.path.join(CLEAN_DIR, fname)
        stats = filter_region(src, dst)

        for k in total_stats:
            total_stats[k] += stats.get(k, 0)

        removed = stats['end'] + stats['nether']
        flag = f" [removed {removed} end/nether]" if removed else ""
        if stats['kept']:
            print(f"  {fname}: {stats['kept']} kept / {stats['total']}{flag}")
        else:
            print(f"  {fname}: empty (all {stats['total']} non-overworld)")

    print(f"\n[*] Summary:")
    print(f"    Total chunks:  {total_stats['total']}")
    print(f"    Kept (OW):     {total_stats['kept']}")
    print(f"    End removed:   {total_stats['end']}")
    print(f"    Nether removed:{total_stats['nether']}")
    print(f"[+] Cleaned world → {CLEAN_DIR}/")


if __name__ == '__main__':
    main()
