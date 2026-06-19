#!/usr/bin/env python3
"""Create level.dat for the survival world and validate MCA files."""
import os, struct, zlib, sys
from nbtlib import File, tag as nbt_tag

OUT = sys.argv[1] if len(sys.argv) > 1 else 'output_survival/survival_world'

# ── Create level.dat ──
lv = nbt_tag.Compound()
d = nbt_tag.Compound()
d["version"] = nbt_tag.Int(19133)
d["LevelName"] = nbt_tag.String("Survival")
d["GameType"] = nbt_tag.Int(3)          # Spectator
d["allowCommands"] = nbt_tag.Byte(1)    # Cheats enabled
d["Difficulty"] = nbt_tag.Byte(0)
d["hasBeenLoadedInCreative"] = nbt_tag.Byte(1)
d["RandomSeed"] = nbt_tag.Long(0)
d["GameRules"] = nbt_tag.Compound()
v = nbt_tag.Compound()
v["Id"] = nbt_tag.Int(2586)
v["Name"] = nbt_tag.String("1.16.5")
v["Snapshot"] = nbt_tag.Byte(0)
d["Version"] = v
dp = nbt_tag.Compound()
dp["Enabled"] = nbt_tag.List[nbt_tag.String]([nbt_tag.String("vanilla")])
dp["Disabled"] = nbt_tag.List[nbt_tag.String]([])
d["DataPacks"] = dp
d["generatorName"] = nbt_tag.String("flat")
d["generatorOptions"] = nbt_tag.String("3;minecraft:air;1;minecraft:the_void")
d["generatorVersion"] = nbt_tag.Int(0)
lv["Data"] = d

os.makedirs(OUT, exist_ok=True)
File(lv, gzipped=True, byteorder='big').save(os.path.join(OUT, 'level.dat'))
print("[+] level.dat created")

# ── Validate a few MCA files ──
region_dir = os.path.join(OUT, 'region')
mca_files = sorted(os.listdir(region_dir))[:5]
for mca_name in mca_files:
    mca_path = os.path.join(region_dir, mca_name)
    if not mca_name.endswith('.mca'):
        continue
    with open(mca_path, 'rb') as f:
        header = f.read(8192)
    chunks_found = 0
    for i in range(1024):
        off = struct.unpack('>I', header[i*4:i*4+4])[0]
        if off != 0:
            chunks_found += 1
    fs = os.path.getsize(mca_path)
    print(f"  {mca_name}: {chunks_found} chunks, {fs//1024}KB")

# ── Quick decompress test on one chunk ──
test_mca = os.path.join(region_dir, mca_files[0]) if mca_files else None
if test_mca:
    with open(test_mca, 'rb') as f:
        header = f.read(8192)
    for i in range(1024):
        off_field = struct.unpack('>I', header[i*4:i*4+4])[0]
        if off_field == 0:
            continue
        sector_off = off_field >> 8
        with open(test_mca, 'rb') as f:
            f.seek(sector_off * 4096)
            length = struct.unpack('>I', f.read(4))[0]
            comp_type = f.read(1)[0]
            compressed = f.read(length - 1)
            nbt_data = zlib.decompress(compressed)
        print(f"  [verify] {mca_files[0]} chunk[{i}]: compressed={len(compressed)}B, nbt={len(nbt_data)}B, comp_type={comp_type}")
        break

print(f"\n[+] Validation complete")
