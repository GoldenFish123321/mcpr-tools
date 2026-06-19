#!/usr/bin/env python3
"""Unified extraction: all files → _chunks/ → MCA assembly → dimension clean → level.dat

Filters (four layers):
  ① survival_periods.json    — time-based (only extract packets during survival periods)
  ② bottom bedrock check     — reject chunks where Y=0 section has no bedrock (lobby/city flat world)
  ③ coordinate cluster        — space-based (reject far-away Multiverse worlds)
  ④ biome check               — dimension-based (reject End/Nether chunks)
"""
import zipfile, struct, os, sys, glob, json, zlib, io, time, shutil
from collections import defaultdict, Counter
from nbtlib import File as NBTFile, tag as nbt_tag
import minecraft_data

# ============================================================
# Setup
# ============================================================
mc = minecraft_data("1.16.5")
BLOCK = {}
for b in mc.blocks_list:
    n = "minecraft:" + b["name"]
    for s in range(b["minStateId"], b["maxStateId"] + 1):
        BLOCK[s] = n
def bn(bid): return BLOCK.get(bid, f"minecraft:block_{bid}")

END_BIOMES   = {9, 40, 41, 42, 43}
NETHER_BIOMES = {8, 170, 171, 172, 173}

# ============================================================
# Streaming parser
# ============================================================
def rv(d, o):
    v = 0; s = 0
    while o < len(d):
        b = d[o]; o += 1
        v |= (b & 0x7F) << s
        if not (b & 0x80): break
        s += 7
    return v, o

def packets(fp):
    buf = b''; off = 0
    while True:
        chunk = fp.read(4*1024*1024)
        if not chunk and not buf: break
        if chunk: buf += chunk
        while off + 8 <= len(buf):
            ts = struct.unpack('>i', buf[off:off+4])[0]
            ln = struct.unpack('>i', buf[off+4:off+8])[0]
            if ln < 0 or ln > 50_000_000: off += 1; continue
            end = off + 8 + ln
            if end > len(buf):
                if not chunk: break
                break
            pkt = buf[off+8:end]; off = end
            if ln == 0: continue
            try:
                pid = 0; s = 0; p = 0
                while p < len(pkt):
                    b = pkt[p]; p += 1
                    pid |= (b & 0x7F) << s
                    if not (b & 0x80): break
                    s += 7
                yield ts, pid, pkt[p:]
            except: pass
        if off > 0: buf = buf[off:]; off = 0
        if not chunk and off + 8 > len(buf): break

# ============================================================
# NBT reader
# ============================================================
def _rs(d, o):
    l, o = rv(d, o); return d[o:o+l].decode('utf-8','replace'), o+l

class NR:
    def __init__(s, d, o=0): s.d = d; s.o = o
    def r(s):
        t = s.d[s.o]; s.o += 1
        if t == 0: return "", None, s.o
        nl = struct.unpack('>H', s.d[s.o:s.o+2])[0]; s.o += 2
        nm = s.d[s.o:s.o+nl].decode('utf-8','replace') if nl>0 else ""; s.o += nl
        v, s.o = s._p(t, s.o)
        if v is None: return "", None, s.o
        return nm, v, s.o
    def _p(s, t, o):
        d = s.d
        if t == 0: return None, o
        if t == 1: return nbt_tag.Byte(d[o]), o+1
        if t == 2: return nbt_tag.Short(struct.unpack('>h',d[o:o+2])[0]), o+2
        if t == 3: return nbt_tag.Int(struct.unpack('>i',d[o:o+4])[0]), o+4
        if t == 4: return nbt_tag.Long(struct.unpack('>q',d[o:o+8])[0]), o+8
        if t == 5: return nbt_tag.Float(struct.unpack('>f',d[o:o+4])[0]), o+4
        if t == 6: return nbt_tag.Double(struct.unpack('>d',d[o:o+8])[0]), o+8
        if t == 7: l=struct.unpack('>i',d[o:o+4])[0];o+=4;return nbt_tag.ByteArray(d[o:o+l]),o+l
        if t == 8: v,o=_rs(d,o);return nbt_tag.String(v),o
        if t == 9:
            ct=d[o];o+=1;l=struct.unpack('>i',d[o:o+4])[0];o+=4
            M={1:nbt_tag.Byte,2:nbt_tag.Short,3:nbt_tag.Int,4:nbt_tag.Long,5:nbt_tag.Float,6:nbt_tag.Double,7:nbt_tag.ByteArray,8:nbt_tag.String,9:nbt_tag.List,10:nbt_tag.Compound,11:nbt_tag.IntArray,12:nbt_tag.LongArray}
            lst=nbt_tag.List[M.get(ct,nbt_tag.Compound)]()
            for _ in range(l): i,o=s._p(ct,o);lst.append(i)
            return lst,o
        if t == 10:
            c=nbt_tag.Compound()
            while d[o]!=0:
                s.o=o;nm,v,o=s.r()
                if v is not None:c[nm]=v
            return c,o+1
        if t == 11: l=struct.unpack('>i',d[o:o+4])[0];o+=4;return nbt_tag.IntArray([struct.unpack('>i',d[o+i*4:o+i*4+4])[0] for i in range(l)]),o+l*4
        if t == 12: l=struct.unpack('>i',d[o:o+4])[0];o+=4;return nbt_tag.LongArray([struct.unpack('>q',d[o+i*8:o+i*8+8])[0] for i in range(l)]),o+l*8
        return None,o

def rnbt(d,o=0):
    if o>=len(d):return None,o
    t=d[o];o+=1
    if t==0:return None,o
    r=NR(d,o-1);_,v,no=r.r();return v,no

# ============================================================
# MCA writer
# ============================================================
SECTOR=4096; CS=32

def make_entry(nbt_root):
    buf=io.BytesIO()
    NBTFile(nbt_root,gzipped=False,byteorder='big').write(buf)
    c=zlib.compress(buf.getvalue())
    return struct.pack('>I',len(c)+1)+b'\x02'+c

def write_region(path, chunks):
    offs=[0]*(CS*CS);tss=[0]*(CS*CS);sec=2;co={}
    for idx,data in sorted(chunks.items()):
        s=(len(data)+SECTOR-1)//SECTOR;co[idx]=(sec,s);sec+=s
    with open(path,'wb') as f:
        for idx in range(CS*CS):
            if idx in co: o,s=co[idx];offs[idx]=(o<<8)|s
            f.write(struct.pack('>I',offs[idx]))
        for idx in range(CS*CS):f.write(struct.pack('>I',tss[idx]))
        for idx in range(CS*CS):
            if idx in chunks:
                d=chunks[idx];f.write(d)
                pad=(SECTOR-len(d)%SECTOR)%SECTOR
                if pad:f.write(b'\x00'*pad)

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    mcpr_dir = sys.argv[1] if len(sys.argv) > 1 else 'mcpr_files'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'output_survival'

    # --- Load survival periods (filter ①: time) ---
    with open('survival_periods.json') as f:
        sp = [(t1,t2) for t1,t2 in json.load(f) if t2-t1 > 1000]
    print(f"[*] {len(sp)} survival periods")

    def iss(ts):
        for t1,t2 in sp:
            if t1 <= ts <= t2: return True
        return False

    # --- Filter ②: coordinate cluster bounds ---
    # Origin cluster: rx ≈ [-9, 7], rz ≈ [-22, 7] (from verified data)
    # Use generous bounds to catch all survival-world chunks
    RX_MIN, RX_MAX = -15, 15
    RZ_MIN, RZ_MAX = -30, 15

    def is_origin_cluster(cx, cz):
        rx, rz = cx >> 5, cz >> 5
        return RX_MIN <= rx <= RX_MAX and RZ_MIN <= rz <= RZ_MAX

    # --- Process files ---
    files = sorted(glob.glob(os.path.join(mcpr_dir, '*.mcpr')))
    chunk_dir = os.path.join(out_dir, '_chunks')
    os.makedirs(chunk_dir, exist_ok=True)

    stats = Counter()                       # total_020, in_survival, saved, far_world, end_nether
    total = 0

    for fi, fp in enumerate(files):
        fn = os.path.basename(fp)
        size_mb = os.path.getsize(fp) // 1024 // 1024
        t0 = time.time()
        zf = zipfile.ZipFile(fp)
        kept = 0
        last_report = t0

        with zf.open('recording.tmcpr') as f:
            for ts, pid, payload in packets(f):
                if pid != 0x20: continue
                stats['total_020'] += 1

                if not iss(ts): continue          # filter ①: time
                stats['in_survival'] += 1

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

                    # Filter ②: coordinate cluster (DISABLED)
                    # if not is_origin_cluster(cx, cz):
                    #     stats['far_world'] += 1
                    #     continue

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
                    for _ in range(bec):
                        try: be,o=rnbt(payload,o)
                        except: continue
                        if be:bes.append(be)

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
                        # Each long holds floor(64/bpb) blocks; remaining bits are padding.
                        # bpb=5: 12 blocks/long → ceil(4096/12) = 342 longs
                        if bpb > 0:
                            bpl = 64 // bpb  # blocks per long
                            expected = (4096 + bpl - 1) // bpl  # ceil(4096 / bpl)
                            if len(bs) > expected:
                                bs = bs[:expected]
                        
                        secs[y]=(bpb,pal,bs)

                    # --- Filter ②: bottom bedrock check ---
                    # Y=0 layer (indices 0-255, 16×16) must be all bedrock
                    # Y=1 layer (indices 256-511) reject if all dirt (lobby/city flat world)
                    if secs[0] is not None:
                        bpb0, pal0, bs0 = secs[0]
                        def decode_block(idx, bpb, bs, pal):
                            # 1.16+ aligned: blocks do NOT span long boundaries
                            bpl = 64 // bpb  # blocks per long
                            long_idx = idx // bpl
                            bit_off = (idx % bpl) * bpb
                            if long_idx < len(bs):
                                bid = (bs[long_idx] >> bit_off) & ((1 << bpb) - 1)
                            else:
                                bid = 0
                            if pal is not None:
                                return bn(pal[bid]) if bid < len(pal) else 'unknown'
                            return bn(bid)

                        y0_ok = True
                        for i in range(256):
                            if decode_block(i, bpb0, bs0, pal0) != 'minecraft:bedrock':
                                y0_ok = False; break
                        if not y0_ok:
                            stats['no_bedrock'] += 1; continue

                        y1_all_dirt = True
                        for i in range(256, 512):
                            if decode_block(i, bpb0, bs0, pal0) != 'minecraft:dirt':
                                y1_all_dirt = False; break
                        if y1_all_dirt:
                            stats['no_bedrock'] += 1; continue

                    # --- Build NBT ---
                    lv=nbt_tag.Compound()
                    lv["xPos"]=nbt_tag.Int(cx);lv["zPos"]=nbt_tag.Int(cz)
                    lv["Status"]=nbt_tag.String("full");lv["LastUpdate"]=nbt_tag.Long(0)
                    sl=nbt_tag.List[nbt_tag.Compound]()
                    for y,s in enumerate(secs):
                        if s is None:continue
                        _,pal,bs=s
                        ss=nbt_tag.Compound();ss["Y"]=nbt_tag.Byte(y);ss["BlockStates"]=nbt_tag.LongArray(bs)
                        if pal is not None:
                            pl=nbt_tag.List[nbt_tag.Compound]()
                            if pal:
                                for bid in pal:
                                    e=nbt_tag.Compound();e["Name"]=nbt_tag.String(bn(bid));pl.append(e)
                            else:
                                e=nbt_tag.Compound();e["Name"]=nbt_tag.String("minecraft:air");pl.append(e)
                            ss["Palette"]=pl
                        sl.append(ss)
                    lv["Sections"]=sl
                    lv["Heightmaps"]=hm if hm else nbt_tag.Compound()
                    if not dict(lv["Heightmaps"]):lv["Heightmaps"]["MOTION_BLOCKING"]=nbt_tag.LongArray([0]*36)
                    lv["Biomes"]=nbt_tag.IntArray(biomes if biomes else [1]*1024)
                    tl=nbt_tag.List[nbt_tag.Compound]()
                    for be in bes:tl.append(be)
                    lv["TileEntities"]=tl
                    lv["InhabitedTime"]=nbt_tag.Long(0);lv["isLightOn"]=nbt_tag.Byte(1)
                    root=nbt_tag.Compound();root["Level"]=lv

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

                except: continue

        zf.close()
        total += kept
        elapsed = time.time()-t0
        print(f"  [{fi+1}/{len(files)}] {fn} ({size_mb}MB): {kept} chunks ({elapsed:.0f}s) [{total} total]")

    print(f"\n[+] Extraction done: {total} chunks in {chunk_dir}/")

    # --- Assemble MCA ---
    print(f"\n[*] Assembling MCA...")
    rdir = os.path.join(out_dir, 'survival_world', 'region')
    if os.path.exists(rdir): shutil.rmtree(rdir)
    os.makedirs(rdir, exist_ok=True)

    mca_count = 0
    mca_chunks = 0
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
            except: continue
        if chunks:
            write_region(os.path.join(rdir, f'r.{dname}.mca'), chunks)
            mca_count += 1
            mca_chunks += len(chunks)

    print(f"  {mca_count} MCA files, {mca_chunks} chunks")

    # --- Write level.dat ---
    print(f"\n[*] Writing level.dat...")
    world_root = nbt_tag.Compound()
    data = nbt_tag.Compound()
    # Required for Minecraft 1.16.5
    ver = nbt_tag.Compound()
    ver['Id'] = nbt_tag.Int(2586); ver['Name'] = nbt_tag.String('1.16.5'); ver['Snapshot'] = nbt_tag.Byte(0)
    data['Version'] = ver
    data['LevelName'] = nbt_tag.String('survival_world')
    data['GameType'] = nbt_tag.Int(3)
    data['generatorName'] = nbt_tag.String('flat')
    data['generatorOptions'] = nbt_tag.String('3;minecraft:air;1;minecraft:the_void')
    data['generatorVersion'] = nbt_tag.Int(0)
    data['SpawnX'] = nbt_tag.Int(0); data['SpawnY'] = nbt_tag.Int(80); data['SpawnZ'] = nbt_tag.Int(0)
    data['allowCommands'] = nbt_tag.Byte(1)
    data['Difficulty'] = nbt_tag.Byte(0)
    data['GameRules'] = nbt_tag.Compound()
    data['RandomSeed'] = nbt_tag.Long(0)
    data['version'] = nbt_tag.Int(19133)
    data['initialized'] = nbt_tag.Byte(1)
    data['Time'] = nbt_tag.Long(0)
    data['DayTime'] = nbt_tag.Long(0)
    data['LastPlayed'] = nbt_tag.Long(0)
    data['SizeOnDisk'] = nbt_tag.Long(0)
    pl = nbt_tag.Compound()
    pl['Dimension'] = nbt_tag.String('minecraft:overworld')
    pl['Pos'] = nbt_tag.List[nbt_tag.Double]([nbt_tag.Double(0.0), nbt_tag.Double(80.0), nbt_tag.Double(0.0)])
    pl['Rotation'] = nbt_tag.List[nbt_tag.Float]([nbt_tag.Float(0.0), nbt_tag.Float(0.0)])
    pl['Motion'] = nbt_tag.List[nbt_tag.Double]([nbt_tag.Double(0.0), nbt_tag.Double(0.0), nbt_tag.Double(0.0)])
    pl['playerGameType'] = nbt_tag.Int(3)
    pl['UUID'] = nbt_tag.IntArray([0, 0, 0, 0])
    pl['abilities'] = nbt_tag.Compound()
    pl['abilities']['flying'] = nbt_tag.Byte(1)
    pl['abilities']['invulnerable'] = nbt_tag.Byte(1)
    data['Player'] = pl
    data['hasBeenLoadedInCreative'] = nbt_tag.Byte(1)
    dp = nbt_tag.Compound()
    dp['Enabled'] = nbt_tag.List[nbt_tag.String]([nbt_tag.String('vanilla')])
    dp['Disabled'] = nbt_tag.List[nbt_tag.String]([])
    data['DataPacks'] = dp
    world_root['Data'] = data
    lvl_path = os.path.join(out_dir, 'survival_world', 'level.dat')
    NBTFile(world_root, gzipped=True, byteorder='big').save(lvl_path)

    # --- Summary ---
    print(f"\n{'='*55}")
    print(f"  ChunkData packets scanned:  {stats['total_020']:>8,}")
    print(f"  In survival periods:        {stats['in_survival']:>8,}")
    print(f"  Rejected (no bedrock):       {stats['no_bedrock']:>8,}")
    print(f"  Rejected (far world):       {stats['far_world']:>8,}")
    print(f"  Rejected (End biomes):      {stats['end']:>8,}")
    print(f"  Rejected (Nether biomes):   {stats['nether']:>8,}")
    print(f"  Saved (overworld survival): {stats['saved']:>8,}")
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
