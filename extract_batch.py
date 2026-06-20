#!/usr/bin/env python3
"""Unified extraction: all files -> _chunks/ -> MCA assembly -> level.dat

Filters (two layers):
  1. bottom bedrock check  — reject chunks where Y=0 has no bedrock (lobby/city flat world)
  2. biome check           — dimension-based (reject End/Nether chunks)
"""
import zipfile, struct, os, sys, glob, zlib, io, time, shutil, math
from collections import Counter
from nbtlib import File as NBTFile, tag as nbt_tag

from block_data import bn, bp, END_BIOMES, NETHER_BIOMES
from protocol import rv, packets
from nbt_reader import rnbt, rnbt_disk
from mca_writer import make_entry, write_region, CS
from level_utils import build_level_dat
from seed_validator import check_biomes_exact, is_available as seed_validator_available, maybe_warn_fallback


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    # Parse CLI: positional args = mcpr_dir out_dir, optional --seed N
    args = sys.argv[1:]
    pos_args = []
    seed = None
    i = 0
    while i < len(args):
        if args[i] == '--seed' and i + 1 < len(args):
            seed = int(args[i + 1])
            i += 2
        elif not args[i].startswith('--'):
            pos_args.append(args[i])
            i += 1
        else:
            i += 1

    mcpr_dir = pos_args[0] if pos_args else 'mcpr_files'
    out_dir = pos_args[1] if len(pos_args) > 1 else 'output_survival'

    # Seed biome validation setup
    if seed is not None:
        if seed_validator_available():
            from cubiomespi import MCVersion
            MC_VER = MCVersion.MC_1_16_5
            print(f"[*] Seed: {seed} — biome validation enabled")
            maybe_warn_fallback()
        else:
            print(f"WARNING: cubiomes library not available, --seed {seed} ignored for biome filtering",
                  file=sys.stderr)
            seed = None  # fall back to void world / no validation

    # --- Find files ---
    files = sorted(glob.glob(os.path.join(mcpr_dir, '*.mcpr')))
    if not files:
        print(f"ERROR: no .mcpr files found in {mcpr_dir}", file=sys.stderr)
        sys.exit(1)

    chunk_dir = os.path.join(out_dir, '_chunks')
    os.makedirs(chunk_dir, exist_ok=True)

    stats = Counter()
    total = 0
    # Biome cache: full chunks store their biomes, partial chunks look up from here.
    biome_cache = {}  # {(cx, cz): [biome_id, ...]}

    for fi, fp in enumerate(files):
        fn = os.path.basename(fp)
        size_mb = os.path.getsize(fp) // 1024 // 1024
        t0 = time.time()
        kept = 0
        file_errors = 0
        file_failed = False

        try:
            with zipfile.ZipFile(fp) as zf:
                try:
                    with zf.open('recording.tmcpr') as f:
                        for ts, pid, payload in packets(f):
                            if pid != 0x20: continue
                            stats['total_020'] += 1

                            try:
                                o = 0
                                cx = struct.unpack('>i',payload[o:o+4])[0];o+=4
                                cz = struct.unpack('>i',payload[o:o+4])[0];o+=4
                                full = payload[o]!=0;o+=1
                                mask,o = rv(payload,o)

                                # --- Read biomes for filter ③ BEFORE building NBT ---
                                hm,o = rnbt(payload,o)
                                biomes=None
                                if full:
                                    bc,o=rv(payload,o);biomes=[]
                                    for _ in range(bc):
                                        if o >= len(payload): break
                                        b,o=rv(payload,o);biomes.append(b)
                                    biome_cache[(cx, cz)] = biomes
                                else:
                                    # Partial chunk: look up biomes from a previously seen full chunk
                                    biomes = biome_cache.get((cx, cz))

                                # Filter ③: dimension (End/Nether)
                                if biomes:
                                    bs = set(biomes)
                                    if bs & END_BIOMES:
                                        stats['end'] += 1; continue
                                    if bs & NETHER_BIOMES:
                                        stats['nether'] += 1; continue

                                # --- Parse sections ---
                                ds,o=rv(payload,o)
                                if ds<0 or o+ds>len(payload):continue
                                sd=payload[o:o+ds];o+=ds

                                bec,o=rv(payload,o);bes=[]
                                for ei in range(bec):
                                    try: be,o=rnbt_disk(payload,o)
                                    except: continue
                                    if be:
                                        # Ensure sign tile entities have GlowingText (required by 1.16.5)
                                        if hasattr(be, 'get') and str(be.get('id','')) == 'minecraft:sign':
                                            if 'GlowingText' not in be:
                                                be['GlowingText'] = nbt_tag.Byte(0)
                                        bes.append(be)

                                secs=[None]*16;so=0
                                for y in range(16):
                                    if not(mask&(1<<y)):continue
                                    if so+2>len(sd):break
                                    _=struct.unpack('>H',sd[so:so+2])[0];so+=2
                                    if so>=len(sd):break
                                    bpb=sd[so];so+=1
                                    pal=None
                                    if bpb<=8:
                                        if so>=len(sd):break
                                        pl,so=rv(sd,so);pal=[]
                                        for _ in range(pl):
                                            if so>=len(sd):break
                                            e,so=rv(sd,so);pal.append(e)
                                    if so>=len(sd):break
                                    dl,so=rv(sd,so);bs=[]
                                    for _ in range(dl):
                                        if so+8>len(sd):break
                                        bs.append(struct.unpack('>q',sd[so:so+8])[0]);so+=8
                                    # 1.16+ aligned encoding: blocks do NOT span long boundaries.
                                    if bpb > 0:
                                        bpl = 64 // bpb
                                        expected = (4096 + bpl - 1) // bpl
                                        if len(bs) > expected:
                                            bs = bs[:expected]

                                    secs[y]=(bpb,pal,bs)

                                # --- Filter ②: bottom bedrock check + Y=1 dirt check ---
                                if secs[0] is not None:
                                    bpb0, pal0, bs0 = secs[0]

                                    def decode_block(idx, bpb, bs, pal):
                                        bpl = 64 // bpb
                                        long_idx = idx // bpl
                                        bit_off = (idx % bpl) * bpb
                                        if long_idx < len(bs):
                                            bid = (bs[long_idx] >> bit_off) & ((1 << bpb) - 1)
                                        else:
                                            bid = 0
                                        if pal is not None:
                                            return bn(pal[bid]) if bid < len(pal) else 'unknown'
                                        return bn(bid)

                                    # Check Y=1 for all-dirt FIRST (catches flat world regardless of Y=0)
                                    y1_all_dirt = True
                                    for i in range(256, 512):
                                        if decode_block(i, bpb0, bs0, pal0) != 'minecraft:dirt':
                                            y1_all_dirt = False; break
                                    if y1_all_dirt:
                                        stats['no_bedrock'] += 1; continue

                                    # Check Y=0 for all-bedrock
                                    y0_ok = True
                                    for i in range(256):
                                        if decode_block(i, bpb0, bs0, pal0) != 'minecraft:bedrock':
                                            y0_ok = False; break
                                    if not y0_ok:
                                            stats['no_bedrock'] += 1; continue

                                # --- Filter ④: exact seed biome match ---
                                if seed is not None and biomes:
                                    matched, _ = check_biomes_exact(
                                        MC_VER, seed, cx, cz, biomes)
                                    if matched != 16:
                                        stats['seed_mismatch'] += 1
                                        continue

                                # --- Build chunk NBT ---
                                lv=nbt_tag.Compound()
                                lv["xPos"]=nbt_tag.Int(cx);lv["zPos"]=nbt_tag.Int(cz)
                                lv["LastUpdate"]=nbt_tag.Long(0)
                                sl=nbt_tag.List[nbt_tag.Compound]()
                                # Process existing sections, fill missing Y=0..15 with air
                                for y in range(16):
                                    if secs[y] is not None:
                                        bpb, pal, bs = secs[y]
                                        # Convert DIRECT palette (bpb>8, pal=None) to regular palette
                                        if pal is None and bpb > 0:
                                            bpl_d = 64 // max(bpb, 1)
                                            # Collect unique state IDs
                                            seen = {}
                                            idxs = []
                                            for i in range(4096):
                                                li = i // bpl_d
                                                bo = (i % bpl_d) * bpb
                                                sid = (bs[li] >> bo) & ((1 << bpb) - 1) if li < len(bs) else 0
                                                if sid not in seen:
                                                    seen[sid] = len(seen)
                                                idxs.append(seen[sid])
                                            # Build palette and re-encode
                                            pal = list(seen.keys())
                                            new_bpb = max(1, math.ceil(math.log2(len(pal)))) if pal else 4
                                            new_bpl = 64 // new_bpb
                                            new_longs = [0] * ((4096 + new_bpl - 1) // new_bpl)
                                            for i, pid in enumerate(idxs):
                                                li = i // new_bpl
                                                bo = (i % new_bpl) * new_bpb
                                                new_longs[li] |= (pid & ((1 << new_bpb) - 1)) << bo
                                            bs = new_longs
                                        ss = nbt_tag.Compound();ss["Y"] = nbt_tag.Byte(y);ss["BlockStates"] = nbt_tag.LongArray(bs)
                                        if pal is not None:
                                            pl=nbt_tag.List[nbt_tag.Compound]()
                                            if pal:
                                                for bid in pal:
                                                    name, props = bp(bid)
                                                    e=nbt_tag.Compound();e["Name"]=nbt_tag.String(name)
                                                    if props:
                                                        pc=nbt_tag.Compound()
                                                        for k,v in props.items():
                                                            pc[k]=nbt_tag.String(v)
                                                        e["Properties"]=pc
                                                    pl.append(e)
                                            else:
                                                e=nbt_tag.Compound();e["Name"]=nbt_tag.String("minecraft:air");pl.append(e)
                                            ss["Palette"]=pl
                                    else:
                                        # Missing section → fill with air
                                        ss=nbt_tag.Compound();ss["Y"]=nbt_tag.Byte(y)
                                        pl=nbt_tag.List[nbt_tag.Compound]()
                                        e=nbt_tag.Compound();e["Name"]=nbt_tag.String("minecraft:air");pl.append(e)
                                        ss["Palette"]=pl
                                        ss["BlockStates"]=nbt_tag.LongArray([0]*64)
                                    sl.append(ss)
                                lv["Sections"]=sl
                                # Heightmaps: use real data from packet if available.
                                # If missing, set Status="spawn" to force the game to recalculate
                                # light and heightmaps on load (avoids all-zero heightmap bugs).
                                if hm and dict(hm):
                                    lv["Heightmaps"] = hm
                                    lv["Status"] = nbt_tag.String("full")
                                else:
                                    lv["Status"] = nbt_tag.String("spawn")
                                lv["Biomes"]=nbt_tag.IntArray(biomes if biomes else [1]*1024)
                                tl=nbt_tag.List[nbt_tag.Compound]()
                                for be in bes:tl.append(be)
                                lv["TileEntities"]=tl
                                lv["InhabitedTime"]=nbt_tag.Long(0);lv["isLightOn"]=nbt_tag.Byte(0)
                                lv["Entities"]=nbt_tag.List[nbt_tag.Compound]([])
                                lv["TileTicks"]=nbt_tag.List[nbt_tag.Compound]([])
                                lv["LiquidTicks"]=nbt_tag.List[nbt_tag.Compound]([])
                                lv["Structures"]=nbt_tag.Compound()
                                root=nbt_tag.Compound();root["Level"]=lv;root["DataVersion"]=nbt_tag.Int(2586)

                                chunk_bytes = make_entry(root)

                                # --- Save to _chunks/ ---
                                rx,rz=cx>>5,cz>>5
                                lx,lz=cx%32,cz%32
                                if lx<0:lx+=32
                                if lz<0:lz+=32

                                rd=os.path.join(chunk_dir,f'{rx}.{rz}')
                                os.makedirs(rd,exist_ok=True)
                                cf_path = os.path.join(rd,f'{lx}.{lz}')

                                with open(cf_path,'wb') as cf:
                                    cf.write(chunk_bytes)
                                kept+=1
                                stats['saved'] += 1

                            except:
                                stats['parse_error'] += 1
                                file_errors += 1
                                continue

                except KeyError:
                    print(f"  [{fi+1}/{len(files)}] {fn}: SKIPPED - no recording.tmcpr inside zip",
                          file=sys.stderr)
                    file_failed = True

        except zipfile.BadZipFile:
            print(f"  [{fi+1}/{len(files)}] {fn}: SKIPPED - not a valid zip file",
                  file=sys.stderr)
            file_failed = True
        except Exception as e:
            print(f"  [{fi+1}/{len(files)}] {fn}: SKIPPED - {e}", file=sys.stderr)
            file_failed = True

        if file_failed:
            continue

        total += kept
        elapsed = time.time() - t0
        status = f"  [{fi+1}/{len(files)}] {fn} ({size_mb}MB): {kept} chunks ({elapsed:.0f}s) [{total} total]"
        if file_errors:
            status += f"  ({file_errors} parse errors)"
        print(status)

    print(f"\n[+] Extraction done: {total} chunks in {chunk_dir}/")

    # --- Assemble MCA ---
    print(f"\n[*] Assembling MCA...")
    rdir = os.path.join(out_dir, 'survival_world', 'region')
    if os.path.exists(rdir): shutil.rmtree(rdir)
    os.makedirs(rdir, exist_ok=True)

    mca_count = 0
    mca_chunks = 0
    mca_skip = 0
    for dname in sorted(os.listdir(chunk_dir)):
        dp = os.path.join(chunk_dir, dname)
        if not os.path.isdir(dp): continue
        chunks = {}
        for cn in os.listdir(dp):
            cp = os.path.join(dp, cn)
            try:
                a,b = cn.split('.')
                lx,lz = int(a), int(b)
                idx = lx + lz * CS
                with open(cp,'rb') as cf: chunks[idx] = cf.read()
            except:
                mca_skip += 1
                continue
        if chunks:
            write_region(os.path.join(rdir, f'r.{dname}.mca'), chunks)
            mca_count += 1
            mca_chunks += len(chunks)

    print(f"  {mca_count} MCA files, {mca_chunks} chunks", end='')
    if mca_skip:
        print(f"  ({mca_skip} unparseable chunk files skipped)")
    else:
        print()

    # --- Write level.dat ---
    print(f"\n[*] Writing level.dat...")
    lvl_path = os.path.join(out_dir, 'survival_world', 'level.dat')
    NBTFile(build_level_dat(seed=seed), gzipped=True, byteorder='big').save(lvl_path)

    # --- Summary ---
    print(f"\n{'='*55}")
    print(f"  ChunkData packets scanned:  {stats['total_020']:>8,}")
    print(f"  Parse errors:               {stats['parse_error']:>8,}")
    print(f"  Rejected (no bedrock):       {stats['no_bedrock']:>8,}")
    print(f"  Rejected (seed mismatch):    {stats['seed_mismatch']:>8,}")
    print(f"  Rejected (End biomes):      {stats['end']:>8,}")
    print(f"  Rejected (Nether biomes):   {stats['nether']:>8,}")
    print(f"  Saved (overworld): {stats['saved']:>16,}")
    print(f"  ───────────────────────────")
    print(f"  MCA files: {mca_count}, chunks: {mca_chunks}")

    # Bounds
    coords = set()
    for dname in os.listdir(rdir):
        if not dname.endswith('.mca'): continue
        parts = dname.replace('r.','').replace('.mca','').split('.')
        rx,rz = int(parts[0]), int(parts[1])
        with open(os.path.join(rdir, dname), 'rb') as f:
            hdr = f.read(CS*CS*4)
            for i in range(CS*CS):
                if struct.unpack('>I', hdr[i*4:i*4+4])[0]:
                    coords.add((rx*32 + i%32, rz*32 + i//32))
    if coords:
        xs = [c[0] for c in coords]; zs = [c[1] for c in coords]
        print(f"  Bounds: cx=[{min(xs)},{max(xs)}], cz=[{min(zs)},{max(zs)}]")
        print(f"  Area: {max(xs)-min(xs)+1} × {max(zs)-min(zs)+1}")

    print(f"  World: {out_dir}/survival_world/")
