#!/usr/bin/env python3
"""Track player position using Entity Teleport + Entity Position packets."""
import zipfile, struct, os, sys

def read_varint(data, offset):
    value = 0; shift = 0
    while True:
        b = data[offset]; offset += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return value, offset

def track_all_positions(filepath):
    z = zipfile.ZipFile(filepath)
    data = z.read('recording.tmcpr')
    z.close()
    
    offset = 0
    pkt_count = 0
    positions = []
    self_eid = None
    
    while offset + 8 <= len(data):
        ts = struct.unpack('>i', data[offset:offset+4])[0]
        offset += 4
        length = struct.unpack('>i', data[offset:offset+4])[0]
        offset += 4
        
        if length <= 0 or offset + length > len(data):
            break
        
        pkt_data = data[offset:offset+length]
        offset += length
        pkt_count += 1
        if length == 0: continue
        
        try:
            pid = 0; shift = 0; poff = 0
            while poff < len(pkt_data):
                b = pkt_data[poff]; poff += 1
                pid |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift += 7
            
            payload = pkt_data[poff:]
            
            # JoinGame = 0x24 → get self entity ID
            if pid == 0x24 and len(payload) >= 7:
                self_eid = struct.unpack('>i', payload[0:4])[0]
                # Get spawn position from JoinGame? No, it's not in JoinGame
                # But we know the player spawns at world spawn initially
            
            # Entity Teleport = 0x56 (1.16.2: ordinal 86? let me check)
            # Actually, ENTITY_TELEPORT = 0x61? Let me try common PIDs
            if pid == 0x56 and len(payload) >= 29:  # Try PID 0x56
                eid, off = read_varint(payload, 0)
                if eid == self_eid:
                    x = struct.unpack('>d', payload[off:off+8])[0]; off += 8
                    y = struct.unpack('>d', payload[off:off+8])[0]; off += 8
                    z = struct.unpack('>d', payload[off:off+8])[0]; off += 8
                    positions.append((ts, x, y, z, 'TP'))
            
            # Player Position = 0x34
            if pid == 0x34 and len(payload) >= 33:
                x = struct.unpack('>d', payload[0:8])[0]
                y = struct.unpack('>d', payload[8:16])[0]
                z = struct.unpack('>d', payload[16:24])[0]
                positions.append((ts, x, y, z, 'PP'))
            
            # Entity Position = 0x27 (1.16.2: ordinal 39)
            # Format: entity_id VarInt, dx int16, dy int16, dz int16
            if pid == 0x27 and len(payload) >= 8:
                eid, off = read_varint(payload, 0)
                if eid == self_eid:
                    dx = struct.unpack('>h', payload[off:off+2])[0]
                    dy = struct.unpack('>h', payload[off+2:off+4])[0]
                    dz = struct.unpack('>h', payload[off+4:off+6])[0]
                    # dx,dy,dz are in 1/4096ths of a block... actually in 1.16 they're in 1/4096
                    # No wait - in 1.9+ they're the raw delta in encoder units
                    # Actually they're (current * 32 - prev * 32) * 128 as VarInt...
                    # For relative tracking we'd need to maintain state. Skip for now.
                    pass
            
            # Entity Position and Rotation = 0x28
            if pid == 0x28 and len(payload) >= 8:
                eid, off = read_varint(payload, 0)
                if eid == self_eid:
                    dx = struct.unpack('>h', payload[off:off+2])[0]
                    dy = struct.unpack('>h', payload[off+2:off+4])[0]
                    dz = struct.unpack('>h', payload[off+4:off+6])[0]
                    # Same as above - relative movement
            
        except:
            pass
        
        if pkt_count % 3000000 == 0:
            print(f'  ...{pkt_count//1000000}M, {len(positions)} positions', file=sys.stderr)
    
    return pkt_count, positions

if __name__ == '__main__':
    d = '/root/ctf/minecraft_replay_mod/mcpr_files'
    fname = '2021_10_03_18_59_20.mcpr'
    fp = os.path.join(d, fname)
    
    print(f'Analyzing: {fname}')
    pkt_count, positions = track_all_positions(fp)
    print(f'Packets: {pkt_count:,}  Positions: {len(positions)}')
    
    if not positions:
        print('No positions! Trying without self_eid filter...')
        sys.exit(1)
    
    # Group by type
    pp = [p for p in positions if p[4] == 'PP']
    tp = [p for p in positions if p[4] == 'TP']
    print(f'PlayerPosition: {len(pp)}, Teleports: {len(tp)}')
    
    # Find jumps
    all_pos = sorted(positions, key=lambda p: p[0])
    jumps = []
    prev = all_pos[0]
    for curr in all_pos[1:]:
        dx = curr[1] - prev[1]; dy = curr[2] - prev[2]; dz = curr[3] - prev[3]
        dist = (dx*dx+dy*dy+dz*dz)**0.5
        dt = (curr[0] - prev[0]) / 1000
        if dist > 50:
            tag = 'PP' if curr[4]=='PP' else 'TP'
            jumps.append((prev[0], curr[0], prev[1], prev[2], prev[3], curr[1], curr[2], curr[3], dist, tag))
        prev = curr
    
    print(f'\nPosition jumps (>50 blocks): {len(jumps)}')
    for i, (t1, t2, x1, y1, z1, x2, y2, z2, dist, tag) in enumerate(jumps):
        print(f'  [{t1/1000:.1f}s -> {t2/1000:.1f}s] ({x1:.0f},{y1:.0f},{z1:.0f}) -> ({x2:.0f},{y2:.0f},{z2:.0f}) d={dist:.0f} [{tag}]')
    
    xs = [p[1] for p in all_pos]; ys = [p[2] for p in all_pos]; zs = [p[3] for p in all_pos]
    print(f'\nPosition range: X=[{min(xs):.0f},{max(xs):.0f}] Y=[{min(ys):.0f},{max(ys):.0f}] Z=[{min(zs):.0f},{max(zs):.0f}]')
