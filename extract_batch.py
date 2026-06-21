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
from entity_registry import entity_name, parse_entity_metadata, armor_stand_meta_to_nbt


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
    entity_state = {} # {entity_id: {'type': int, 'x': float, 'y': float, 'z': float, 'uuid': bytes}}

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
                            # --- Entity tracking ---
                            if pid == 0x02:      # Spawn Living Entity
                                try:
                                    o = 0
                                    eid, o = rv(payload, o)
                                    uuid_bytes = payload[o:o+16]; o += 16
                                    etype, o = rv(payload, o)
                                    ex = struct.unpack('>d', payload[o:o+8])[0]; o += 8
                                    ey = struct.unpack('>d', payload[o:o+8])[0]; o += 8
                                    ez = struct.unpack('>d', payload[o:o+8])[0]; o += 8
                                    # Skip yaw(1)+pitch(1)+head_pitch(1)+vx(2)+vy(2)+vz(2) = 9 bytes
                                    o += 9
                                    # Parse entity metadata (non-fatal: store entity even on parse error)
                                    try:
                                        meta, _ = parse_entity_metadata(payload, o)
                                    except Exception:
                                        meta = {}
                                    entity_state[eid] = {
                                        'type': etype, 'x': ex, 'y': ey, 'z': ez,
                                        'uuid': uuid_bytes, 'meta': meta,
                                    }
                                except: pass
                                continue
                            elif pid == 0x56: # Entity Teleport
                                try:
                                    o = 0
                                    eid, o = rv(payload, o)
                                    ex = struct.unpack('>d', payload[o:o+8])[0]; o += 8
                                    ey = struct.unpack('>d', payload[o:o+8])[0]; o += 8
                                    ez = struct.unpack('>d', payload[o:o+8])[0]; o += 8
                                    if eid in entity_state:
                                        entity_state[eid]['x'] = ex
                                        entity_state[eid]['y'] = ey
                                        entity_state[eid]['z'] = ez
                                except: pass
                                continue
                            elif pid == 0x36: # Destroy Entities
                                try:
                                    o = 0
                                    count, o = rv(payload, o)
                                    for _ in range(count):
                                        eid, o = rv(payload, o)
                                        entity_state.pop(eid, None)
                                except: pass
                                continue
                            elif pid == 0x44: # Entity Metadata — merge into existing state
                                try:
                                    o = 0
                                    eid, o = rv(payload, o)
                                    if eid in entity_state:
                                        try:
                                            new_meta, _ = parse_entity_metadata(payload, o)
                                        except Exception:
                                            new_meta = {}
                                        entity_state[eid].setdefault('meta', {}).update(new_meta)
                                except: pass
                                continue

                            if pid != 0x20: continue
                            stats['total_020'] += 1

                            try:
                                o = 0
                                cx = struct.unpack('>i',payload[o:o+4])[0];o+=4
                                cz = struct.unpack('>i',payload[o:o+4])[0];o+=4
                                full = payload[o]!=0;o+=1
                                mask,o = rv(payload,o)

                                # Filter ①: skip chunk unload events (mask==0, no section data)
                                if mask == 0:
                                    stats['mask_zero'] += 1; continue

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
                                if seed is not None:
                                    if not biomes:
                                        # Partial chunk with no cached biomes — skip
                                        stats['seed_unknown_biomes'] += 1; continue
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
                                        # Convert unsigned >2^63 to two's complement signed int64
                                        MASK63 = (1 << 63)
                                        MASK64 = (1 << 64)
                                        bs = [v - MASK64 if v >= MASK63 else v for v in bs]
                                        ss = nbt_tag.Compound();ss["Y"] = nbt_tag.Byte(y)
                                        ss["BlockStates"] = nbt_tag.LongArray(bs)
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

                            except Exception as exc:
                                stats['parse_error'] += 1
                                file_errors += 1
                                if file_errors <= 3:
                                    import traceback
                                    print(f"    parse error: chunk({cx},{cz}) {type(exc).__name__}: {exc}",
                                          file=sys.stderr)
                                    traceback.print_exc(file=sys.stderr)

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

    # --- Inject entities ---
    print(f"\n[*] Injecting entities...")
    # Debug: show what was tracked
    if entity_state:
        from collections import Counter
        types = Counter()
        for ent in entity_state.values():
            types[entity_name(ent['type'])] += 1
        print(f"  Tracked {len(entity_state)} entities: {dict(types.most_common(10))}")
    else:
        print(f"  No entities tracked (all destroyed or none recorded)")
    # Build spatial index: chunk → entities
    entity_by_chunk = {}
    for eid, ent in entity_state.items():
        ecx, ecz = int(ent['x']) >> 4, int(ent['z']) >> 4
        entity_by_chunk.setdefault((ecx, ecz), []).append(ent)
    injected = 0
    for dname in sorted(os.listdir(chunk_dir)):
        dp = os.path.join(chunk_dir, dname)
        if not os.path.isdir(dp): continue
        rx, rz = int(dname.split('.')[0]), int(dname.split('.')[1])
        for cn in os.listdir(dp):
            cp = os.path.join(dp, cn)
            try:
                lx, lz = map(int, cn.split('.'))
                cx, cz = rx * 32 + lx, rz * 32 + lz
                ents_in_chunk = entity_by_chunk.get((cx, cz))
                if not ents_in_chunk: continue

                # Read, parse, inject entities, re-serialize
                with open(cp, 'rb') as cf:
                    raw = cf.read()
                data = zlib.decompress(raw[5:5 + struct.unpack('>I', raw[:4])[0] - 1])
                root = NBTFile.parse(io.BytesIO(data))
                lv = root["Level"]

                ent_list = nbt_tag.List[nbt_tag.Compound]()
                for ent in ents_in_chunk:
                    e = nbt_tag.Compound()
                    e["id"] = nbt_tag.String(entity_name(ent['type']))
                    e["Pos"] = nbt_tag.List[nbt_tag.Double]([
                        nbt_tag.Double(ent['x']), nbt_tag.Double(ent['y']), nbt_tag.Double(ent['z']),
                    ])
                    u = ent['uuid']
                    e["UUID"] = nbt_tag.IntArray([
                        struct.unpack('>i', u[0:4])[0], struct.unpack('>i', u[4:8])[0],
                        struct.unpack('>i', u[8:12])[0], struct.unpack('>i', u[12:16])[0],
                    ])
                    # Apply armor stand metadata (Invisible, CustomName, etc.)
                    if ent['type'] == 1 and ent.get('meta'):
                        for k, v in armor_stand_meta_to_nbt(ent['meta']).items():
                            e[k] = v
                    e["NoAI"] = nbt_tag.Byte(1)
                    e["PersistenceRequired"] = nbt_tag.Byte(1)
                    ent_list.append(e)
                lv["Entities"] = ent_list

                buf = io.BytesIO()
                NBTFile(root, gzipped=False, byteorder='big').write(buf)
                compressed = zlib.compress(buf.getvalue())
                new_entry = struct.pack('>I', len(compressed) + 1) + b'\x02' + compressed
                with open(cp, 'wb') as cf:
                    cf.write(new_entry)
                injected += len(ent_list)
            except Exception as e:
                import traceback
                print(f"    entity injection FAIL chunk({cx},{cz}): {type(e).__name__}: {e}", file=sys.stderr)
                continue
    print(f"  {injected} entities injected into chunks")

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
    print(f"  Rejected (mask=0 unload):    {stats['mask_zero']:>8,}")
    print(f"  Rejected (no bedrock):       {stats['no_bedrock']:>8,}")
    print(f"  Rejected (unknown biomes):   {stats['seed_unknown_biomes']:>8,}")
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
