#!/usr/bin/env python3
"""Two-phase extraction: phase1 processes each mcpr individually, 
phase2 assembles MCA. Resumable — skip already-processed files."""
import zipfile, struct, os, sys, glob, zlib, io, time, shutil, math
from collections import Counter
from nbtlib import File as NBTFile, tag as nbt_tag
import minecraft_data
import json as _json

# ============================================================
# Setup (same as extract_batch.py)
# ============================================================
mc = minecraft_data("1.16.5")
_reports_path = os.path.join(os.path.dirname(__file__), "..", "generated", "reports", "blocks.json")
_STATE_PROPS = {}
if os.path.exists(_reports_path):
    with open(_reports_path) as f:
        _reports = _json.load(f)
    for name, data in _reports.items():
        for s in data["states"]:
            _STATE_PROPS[s["id"]] = (name, s.get("properties", {}))

def bn(bid):
    if bid in _STATE_PROPS:
        return _STATE_PROPS[bid][0]
    for b in mc.blocks_list:
        if b["minStateId"] <= bid <= b["maxStateId"]:
            return "minecraft:" + b["name"]
    return f"minecraft:block_{bid}"

def bp(bid):
    if bid in _STATE_PROPS:
        return _STATE_PROPS[bid]
    return bn(bid), {}

END_BIOMES   = {9, 40, 41, 42, 43}
NETHER_BIOMES = {8, 170, 171, 172, 173}

# ============================================================
# Streaming parser (same as extract_batch.py)
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

# ============================================================
# NBT readers (same as extract_batch.py)
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

def _rs_disk(d, o):
    l = struct.unpack('>H', d[o:o+2])[0]; o += 2
    return d[o:o+l].decode('utf-8','replace'), o+l

class NRD(NR):
    def _p(s, t, o):
        if t == 8:
            v, o = _rs_disk(s.d, o)
            return nbt_tag.String(v), o
        return super()._p(t, o)

def rnbt_disk(d, o=0):
    if o >= len(d): return None, o
    t = d[o]; o += 1
    if t == 0: return None, o
    r = NRD(d, o-1)
    _, v, no = r.r()
    return v, no

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
# Phase 1: Extract all mcpr files to _chunks/
# ============================================================
def decode_block(idx, bpb, bs, pal):
    """1.16+ aligned decode — blocks do NOT span long boundaries."""
    if bpb == 0: return 0
    bpl = 64 // bpb
    long_idx = idx // bpl
    bit_off = (idx % bpl) * bpb
    mask = (1 << bpb) - 1
    if long_idx < len(bs):
        # Handle signed longs: convert to unsigned for bit operations
        lv = bs[long_idx]
        if lv < 0:
            lv &= 0xFFFFFFFFFFFFFFFF
        return (lv >> bit_off) & mask
    return 0

def decode_block_name(idx, bpb, bs, pal):
    bid = decode_block(idx, bpb, bs, pal)
    if pal is not None:
        return bn(pal[bid]) if bid < len(pal) else 'unknown'
    return bn(bid)

SKIP_FILES = {'2022_06_21_12_50_26.mcpr', '2022_06_21_13_31_40.mcpr'}

def phase1_extract(mcpr_dir, chunk_dir):
    files = sorted(glob.glob(os.path.join(mcpr_dir, '*.mcpr')))
    os.makedirs(chunk_dir, exist_ok=True)
    
    stats = Counter()
    total_chunks = 0
    
    for fi, fp in enumerate(files):
        fn = os.path.basename(fp)
        
        if fn in SKIP_FILES:
            print(f"  [{fi+1}/{len(files)}] {fn}: SKIPPED (mc.mimicraft.cn)")
            continue
        
        size_mb = os.path.getsize(fp) // 1024 // 1024
        print(f"  [{fi+1}/{len(files)}] {fn} ({size_mb}MB)...", end='', flush=True)
        t0 = time.time()
        
        kept = 0
        try:
            zf = zipfile.ZipFile(fp)
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
                        
                        # Heightmaps
                        hm,o = rnbt(payload,o)
                        
                        # Biomes
                        biomes=None
                        if full:
                            bc,o=rv(payload,o);biomes=[]
                            for _ in range(bc):
                                if o >= len(payload): break
                                b,o=rv(payload,o);biomes.append(b)
                        
                        # Dimension filter
                        if biomes:
                            bs_biome = set(biomes)
                            if bs_biome & END_BIOMES:
                                stats['end'] += 1; continue
                            if bs_biome & NETHER_BIOMES:
                                stats['nether'] += 1; continue
                        
                        # Sections
                        ds,o=rv(payload,o)
                        if ds<0 or o+ds>len(payload):continue
                        sd=payload[o:o+ds];o+=ds
                        
                        # Block entities (disk format)
                        bec,o=rv(payload,o);bes=[]
                        for ei in range(bec):
                            try: be,o=rnbt_disk(payload,o)
                            except: continue
                            if be:
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
                            # Aligned encoding truncation
                            if bpb > 0:
                                bpl = 64 // bpb
                                expected = (4096 + bpl - 1) // bpl
                                if len(bs) > expected:
                                    bs = bs[:expected]
                            secs[y]=(bpb,pal,bs)
                        
                        # Bedrock check + Y=1 dirt check + skyblock filter
                        if secs[0] is not None:
                            bpb0, pal0, bs0 = secs[0]
                            # Check Y=1 for all-dirt (lobby/city flat world)
                            y1_all_dirt = True
                            for i in range(256, 512):
                                if decode_block_name(i, bpb0, bs0, pal0) != 'minecraft:dirt':
                                    y1_all_dirt = False; break
                            if y1_all_dirt:
                                stats['no_bedrock'] += 1; continue
                            # Check Y=0 for all-bedrock (survival world indicator)
                            y0_ok = True
                            for i in range(256):
                                if decode_block_name(i, bpb0, bs0, pal0) != 'minecraft:bedrock':
                                    y0_ok = False; break
                            if not y0_ok:
                                stats['no_bedrock'] += 1; continue
                            # Skyblock filter: count sections with any non-air blocks
                            non_air = 0
                            for y in range(16):
                                if secs[y] is not None:
                                    bpb_s, pal_s, bs_s = secs[y]
                                    if pal_s is not None:
                                        has_block = False
                                        for bid in pal_s:
                                            if bn(bid) != 'minecraft:air':
                                                has_block = True; break
                                        if has_block:
                                            non_air += 1
                                    else:
                                        non_air += 1  # DIRECT palette = has blocks
                            if non_air < 5:
                                stats['no_bedrock'] += 1; continue
                        
                        # Build NBT
                        lv=nbt_tag.Compound()
                        lv["xPos"]=nbt_tag.Int(cx);lv["zPos"]=nbt_tag.Int(cz)
                        lv["Status"]=nbt_tag.String("full");lv["LastUpdate"]=nbt_tag.Long(0)
                        sl=nbt_tag.List[nbt_tag.Compound]()
                        
                        for y in range(16):
                            if secs[y] is not None:
                                bpb, pal, bs = secs[y]
                                # Convert DIRECT palette
                                if pal is None and bpb > 0:
                                    bpl_d = 64 // max(bpb, 1)
                                    seen = {}
                                    idxs = []
                                    for i in range(4096):
                                        sid = decode_block(i, bpb, bs, None)
                                        if sid not in seen:
                                            seen[sid] = len(seen)
                                        idxs.append(seen[sid])
                                    pal = list(seen.keys())
                                    new_bpb = max(1, math.ceil(math.log2(len(pal)))) if pal else 4
                                    new_bpl = 64 // new_bpb
                                    new_longs = [0] * ((4096 + new_bpl - 1) // new_bpl)
                                    for i, pid_val in enumerate(idxs):
                                        li = i // new_bpl
                                        bo = (i % new_bpl) * new_bpb
                                        new_longs[li] |= (pid_val & ((1 << new_bpb) - 1)) << bo
                                    bs = new_longs
                                
                                # Handle negative longs before passing to nbtlib
                                bs_signed = []
                                for lv in bs:
                                    if lv < 0:
                                        bs_signed.append(lv)
                                    else:
                                        bs_signed.append(lv if lv < 0x8000000000000000 else lv - 0x10000000000000000)
                                
                                ss = nbt_tag.Compound()
                                ss["Y"] = nbt_tag.Byte(y)
                                ss["BlockStates"] = nbt_tag.LongArray(bs_signed)
                                
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
                                # Missing → air
                                ss=nbt_tag.Compound();ss["Y"]=nbt_tag.Byte(y)
                                pl=nbt_tag.List[nbt_tag.Compound]()
                                e=nbt_tag.Compound();e["Name"]=nbt_tag.String("minecraft:air");pl.append(e)
                                ss["Palette"]=pl
                                ss["BlockStates"]=nbt_tag.LongArray([0]*64)
                            sl.append(ss)
                        
                        lv["Sections"]=sl
                        lv["Heightmaps"]=hm if hm else nbt_tag.Compound()
                        if not dict(lv["Heightmaps"]):
                            lv["Heightmaps"]["MOTION_BLOCKING"]=nbt_tag.LongArray([0]*36)
                        lv["Biomes"]=nbt_tag.IntArray(biomes if biomes else [1]*1024)
                        tl=nbt_tag.List[nbt_tag.Compound]()
                        for be in bes:tl.append(be)
                        lv["TileEntities"]=tl
                        lv["InhabitedTime"]=nbt_tag.Long(0)
                        lv["isLightOn"]=nbt_tag.Byte(0)
                        lv["Entities"]=nbt_tag.List[nbt_tag.Compound]([])
                        lv["TileTicks"]=nbt_tag.List[nbt_tag.Compound]([])
                        lv["LiquidTicks"]=nbt_tag.List[nbt_tag.Compound]([])
                        lv["Structures"]=nbt_tag.Compound()
                        root=nbt_tag.Compound()
                        root["Level"]=lv
                        root["DataVersion"]=nbt_tag.Int(2586)
                        
                        chunk_bytes = make_entry(root)
                        
                        # Save to _chunks
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
                        continue
            
            zf.close()
        except Exception as e:
            print(f" ERROR: {e}")
            continue
        
        elapsed = time.time()-t0
        total_chunks += kept
        print(f" {kept} chunks ({elapsed:.0f}s) [{total_chunks} total]")
    
    return stats, total_chunks

# ============================================================
# Phase 2: Assemble MCA from _chunks/
# ============================================================
def phase2_assemble(chunk_dir, rdir):
    if os.path.exists(rdir):
        shutil.rmtree(rdir)
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
                idx = lx + lz * 32
                with open(cp,'rb') as cf: chunks[idx] = cf.read()
            except: continue
        if chunks:
            write_region(os.path.join(rdir, f'r.{dname}.mca'), chunks)
            mca_count += 1
            mca_chunks += len(chunks)
    
    return mca_count, mca_chunks

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    mcpr_dir = sys.argv[1] if len(sys.argv) > 1 else 'mcpr_files'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'output_full'
    
    chunk_dir = os.path.join(out_dir, '_chunks')
    
    print(f"[Phase 1] Extracting chunks from {mcpr_dir}/ → {chunk_dir}/")
    stats, total = phase1_extract(mcpr_dir, chunk_dir)
    
    print(f"\n[Phase 1 done] {total} chunks in {chunk_dir}/")
    print(f"  Scanned: {stats['total_020']:,}")
    print(f"  No bedrock: {stats['no_bedrock']:,}")
    print(f"  End: {stats['end']:,}")
    print(f"  Nether: {stats['nether']:,}")
    print(f"  Saved: {stats['saved']:,}")
    
    print(f"\n[Phase 2] Assembling MCA...")
    rdir = os.path.join(out_dir, 'survival_world', 'region')
    mca_count, mca_chunks = phase2_assemble(chunk_dir, rdir)
    print(f"  {mca_count} MCA files, {mca_chunks} chunks")
    
    # level.dat
    print(f"\n[Phase 3] Writing level.dat...")
    world_root = nbt_tag.Compound()
    data = nbt_tag.Compound()
    ver = nbt_tag.Compound()
    ver['Id'] = nbt_tag.Int(2586); ver['Name'] = nbt_tag.String('1.16.5'); ver['Snapshot'] = nbt_tag.Byte(0)
    data['Version'] = ver
    data['LevelName'] = nbt_tag.String('survival_world')
    data['GameType'] = nbt_tag.Int(3)
    data['generatorName'] = nbt_tag.String('default')
    data['generatorOptions'] = nbt_tag.String('')
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
    
    print(f"  Written: {lvl_path}")
    print(f"\nDone! World: {out_dir}/survival_world/")
