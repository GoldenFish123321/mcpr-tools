#!/usr/bin/env python3
"""Rebuild timeline using JUMP-based world switching."""
import zipfile, struct, json

def read_varint(data, offset):
    value = 0; shift = 0
    while offset < len(data):
        b = data[offset]; offset += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80): break; shift += 7
    return value, offset

def parse_stream(fp, pids):
    CHUNK = 8*1024*1024; buf = b''; off = 0
    while True:
        chunk = fp.read(CHUNK)
        if not chunk and not buf: break
        if chunk: buf += chunk
        while off + 8 <= len(buf):
            ts = struct.unpack('>i', buf[off:off+4])[0]
            length = struct.unpack('>i', buf[off+4:off+8])[0]
            if length < 0 or length > 50_000_000: off += 1; continue
            end = off + 8 + length
            if end > len(buf):
                if not chunk: break
                break
            pkt = buf[off+8:end]; off = end
            if length == 0: continue
            try:
                pid = 0; sh = 0; po = 0
                while po < len(pkt):
                    b = pkt[po]; po += 1
                    pid |= (b & 0x7F) << sh
                    if not (b & 0x80): break; sh += 7
                if pid in pids: yield ts, pid, pkt[po:]
            except: pass
        if off > 0: buf = buf[off:]; off = 0
        if not chunk and off + 8 > len(buf): break

# Scan ALL files for positions (skip huge ones)
import os, glob
files = sorted(glob.glob('/root/ctf/minecraft_replay_mod/mcpr_files/*.mcpr'))
all_positions = []

for fp in files:
    fsize = os.path.getsize(fp)
    if fsize > 300_000_000:  # skip huge files
        print(f'  SKIP {os.path.basename(fp)} ({fsize/1e6:.0f}MB)')
        continue
    
    zf = zipfile.ZipFile(fp)
    with zf.open('recording.tmcpr') as f:
        for ts, pid, payload in parse_stream(f, {0x34}):
            if len(payload) >= 33:
                x = struct.unpack('>d', payload[0:8])[0]
                y = struct.unpack('>d', payload[8:16])[0]
                z = struct.unpack('>d', payload[16:24])[0]
                all_positions.append((ts, x, y, z))
    zf.close()
    print(f'  {os.path.basename(fp)}: {len([p for p in all_positions if p[0] >= 0])} total positions')

all_positions.sort()
print(f'\nTotal positions: {len(all_positions)}')

# Jumps > 200 blocks = world switch
# After jump: classify destination cluster
def classify_dest(x, y, z):
    """Classify which world a teleport destination belongs to."""
    dl = ((x+13)**2 + (y-74)**2 + (z-102)**2)**0.5
    dc = ((x-1400)**2 + (y-37)**2 + (z-928)**2)**0.5
    if dl < 200: return 'lobby'
    if dc < 500: return 'city'
    return 'survival'

# Build timeline: between jumps, all positions belong to the same world
segments = []
prev_world = classify_dest(*all_positions[0][1:])
seg_start = all_positions[0][0]

for i in range(1, len(all_positions)):
    t1, x1, y1, z1 = all_positions[i-1]
    t2, x2, y2, z2 = all_positions[i]
    dx = x2-x1; dy = y2-y1; dz = z2-z1
    dist = (dx*dx+dy*dy+dz*dz)**0.5
    
    if dist > 200:
        # World switch! Close previous segment
        segments.append((seg_start, t1, prev_world))
        # New world from destination
        prev_world = classify_dest(x2, y2, z2)
        seg_start = t2

# Close final segment
segments.append((seg_start, all_positions[-1][0], prev_world))

# Merge consecutive same-world segments
merged = []
for t1, t2, w in segments:
    if merged and merged[-1][2] == w:
        merged[-1] = (merged[-1][0], t2, w)
    else:
        merged.append((t1, t2, w))

print(f'\nTimeline ({len(merged)} segments after merge):')
survival_periods = []
for t1, t2, w in merged:
    d = (t2-t1)/1000
    bar = '#' * int(d/100)
    print(f'  [{t1/1000:7.0f}-{t2/1000:7.0f}s] {w:10s} {d:6.0f}s {bar}')
    if w == 'survival':
        survival_periods.append((t1, t2))

total_s = sum(t2-t1 for t1, t2, _ in merged) / 1000
survival_s = sum(t2-t1 for t1, t2 in survival_periods) / 1000
print(f'\nTotal: {total_s:.0f}s, Survival: {survival_s:.0f}s ({survival_s/total_s*100:.0f}%)')

with open('/root/ctf/minecraft_replay_mod/survival_periods.json', 'w') as f:
    json.dump(survival_periods, f)
print(f'Saved {len(survival_periods)} survival periods')
