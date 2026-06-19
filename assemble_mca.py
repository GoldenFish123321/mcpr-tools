#!/usr/bin/env python3
"""Assemble _chunks/ intermediate files into Anvil .mca region files."""
import os, sys, struct

SECTOR = 4096
CS = 32  # 32x32 chunks per region

def write_region(path, chunks):
    """chunks: dict {index: raw_bytes} where index = lx + lz*32"""
    offsets = [0] * (CS * CS)
    timestamps = [0] * (CS * CS)
    coord = {}
    sector = 2  # first data sector (0 and 1 are headers)

    for idx, data in sorted(chunks.items()):
        sectors_needed = (len(data) + SECTOR - 1) // SECTOR
        coord[idx] = (sector, sectors_needed)
        sector += sectors_needed

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        # Header: 4KB of offsets
        for idx in range(CS * CS):
            if idx in coord:
                off, sec_count = coord[idx]
                offsets[idx] = (off << 8) | sec_count
            f.write(struct.pack('>I', offsets[idx]))

        # Header: 4KB of timestamps
        for idx in range(CS * CS):
            f.write(struct.pack('>I', timestamps[idx]))

        # Chunk data blocks (in index order, padded to sector boundary)
        for idx in range(CS * CS):
            if idx in chunks:
                data = chunks[idx]
                f.write(data)
                pad = (SECTOR - len(data) % SECTOR) % SECTOR
                if pad:
                    f.write(b'\x00' * pad)

    return len(chunks)


def main():
    chunk_dir = sys.argv[1] if len(sys.argv) > 1 else 'output_survival/_chunks'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'output_survival/survival_world/region'

    if not os.path.isdir(chunk_dir):
        print(f"[-] Chunk dir not found: {chunk_dir}")
        sys.exit(1)

    region_dirs = sorted(
        d for d in os.listdir(chunk_dir)
        if os.path.isdir(os.path.join(chunk_dir, d))
    )
    print(f"[*] Found {len(region_dirs)} region directories")

    total_chunks = 0
    for dname in region_dirs:
        dp = os.path.join(chunk_dir, dname)
        chunks = {}
        for cn in os.listdir(dp):
            cp = os.path.join(dp, cn)
            try:
                a, b = cn.split('.')
                lx, lz = int(a), int(b)
                idx = lx + lz * CS
                with open(cp, 'rb') as cf:
                    chunks[idx] = cf.read()
            except (ValueError, OSError) as e:
                print(f"  [!] Skipping {cn} in {dname}: {e}")
                continue

        if not chunks:
            print(f"  [-] {dname}: empty, skipping")
            continue

        mca_path = os.path.join(out_dir, f'r.{dname}.mca')
        n = write_region(mca_path, chunks)
        total_chunks += n
        print(f"  [+] r.{dname}.mca : {n} chunks")

    print(f"\n[+] Done! {total_chunks} chunks across {len(region_dirs)} regions → {out_dir}/")

if __name__ == '__main__':
    main()
