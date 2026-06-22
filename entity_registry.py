#!/usr/bin/env python3
"""Minecraft 1.16.5 (protocol 754) BuiltInRegistries.ENTITY_TYPE mapping.

Auto-generated from PrismarineJS/minecraft-data data/pc/1.16.2/entities.json
(same registry across 1.16.2–1.16.5).
"""
ENTITY_NAMES = {
    0: "area_effect_cloud",
    1: "armor_stand",
    2: "arrow",
    3: "bat",
    4: "bee",
    5: "blaze",
    6: "boat",
    7: "cat",
    8: "cave_spider",
    9: "chicken",
    10: "cod",
    11: "cow",
    12: "creeper",
    13: "dolphin",
    14: "donkey",
    15: "dragon_fireball",
    16: "drowned",
    17: "elder_guardian",
    18: "end_crystal",
    19: "ender_dragon",
    20: "enderman",
    21: "endermite",
    22: "evoker",
    23: "evoker_fangs",
    24: "experience_orb",
    25: "eye_of_ender",
    26: "falling_block",
    27: "firework_rocket",
    28: "fox",
    29: "ghast",
    30: "giant",
    31: "guardian",
    32: "hoglin",
    33: "horse",
    34: "husk",
    35: "illusioner",
    36: "iron_golem",
    37: "item",
    38: "item_frame",
    39: "fireball",
    40: "leash_knot",
    41: "lightning_bolt",
    42: "llama",
    43: "llama_spit",
    44: "magma_cube",
    45: "minecart",
    46: "chest_minecart",
    47: "command_block_minecart",
    48: "furnace_minecart",
    49: "hopper_minecart",
    50: "spawner_minecart",
    51: "tnt_minecart",
    52: "mule",
    53: "mooshroom",
    54: "ocelot",
    55: "painting",
    56: "panda",
    57: "parrot",
    58: "phantom",
    59: "pig",
    60: "piglin",
    61: "piglin_brute",
    62: "pillager",
    63: "polar_bear",
    64: "tnt",
    65: "pufferfish",
    66: "rabbit",
    67: "ravager",
    68: "salmon",
    69: "sheep",
    70: "shulker",
    71: "shulker_bullet",
    72: "silverfish",
    73: "skeleton",
    74: "skeleton_horse",
    75: "slime",
    76: "small_fireball",
    77: "snow_golem",
    78: "snowball",
    79: "spectral_arrow",
    80: "spider",
    81: "squid",
    82: "stray",
    83: "strider",
    84: "egg",
    85: "ender_pearl",
    86: "experience_bottle",
    87: "potion",
    88: "trident",
    89: "trader_llama",
    90: "tropical_fish",
    91: "turtle",
    92: "vex",
    93: "villager",
    94: "vindicator",
    95: "wandering_trader",
    96: "witch",
    97: "wither",
    98: "wither_skeleton",
    99: "wither_skull",
    100: "wolf",
    101: "zoglin",
    102: "zombie",
    103: "zombie_horse",
    104: "zombie_villager",
    105: "zombified_piglin",
    106: "player",
    107: "fishing_bobber",
}


def entity_name(type_id):
    """Return 'minecraft:name' for a protocol-level entity type ID."""
    name = ENTITY_NAMES.get(type_id)
    if name:
        return f"minecraft:{name}"
    return f"minecraft:unknown_{type_id}"


# ── Entity Metadata parser (1.16.5 protocol) ──────────────────

import struct as _struct

def _read_byte(payload, o):
    return payload[o], o + 1

def _read_varint(payload, o):
    from protocol import rv
    return rv(payload, o)

def _read_float(payload, o):
    return _struct.unpack('>f', payload[o:o+4])[0], o + 4

def _read_string(payload, o):
    from protocol import rv
    length, o = rv(payload, o)
    return payload[o:o+length].decode('utf-8', errors='replace'), o + length

def _read_chat(payload, o):
    return _read_string(payload, o)

def _read_opt_chat(payload, o):
    present = payload[o]; o += 1
    if present:
        return _read_string(payload, o)
    return None, o

def _read_boolean(payload, o):
    return payload[o] != 0, o + 1

def _read_slot(payload, o):
    present = payload[o]; o += 1
    if present:
        from protocol import rv
        item_id, o = rv(payload, o)
        if item_id != -1:
            count = payload[o]; o += 1
            from nbt_reader import rnbt
            try:
                tag, o = rnbt(payload, o)
                return {'id': item_id, 'Count': count, 'tag': tag}, o
            except Exception as e:
                import sys
                print(f"  [DEBUG] _read_slot NBT parse error item_id={item_id}: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
                return {'id': item_id, 'Count': count, 'tag': None}, o
        return None, o
    return None, o

def _read_rotation(payload, o):
    return (_struct.unpack('>f', payload[o:o+4])[0],
            _struct.unpack('>f', payload[o+4:o+8])[0],
            _struct.unpack('>f', payload[o+8:o+12])[0]), o + 12

def _read_position(payload, o):
    from protocol import rv
    val, o = rv(payload, o)
    x = val >> 38
    y = val & 0xFFF
    z = (val >> 12) & 0x3FFFFFF
    if x >= 1 << 25: x -= 1 << 26
    if y >= 1 << 11: y -= 1 << 12
    if z >= 1 << 25: z -= 1 << 26
    return (x, y, z), o

def _read_opt_position(payload, o):
    if payload[o]: o += 1; return _read_position(payload, o)
    return None, o + 1

def _read_direction(payload, o):
    from protocol import rv; return rv(payload, o)

def _read_opt_uuid(payload, o):
    if payload[o]: o += 1; return payload[o:o+16], o + 16
    return None, o + 1

def _read_block_state(payload, o):
    from protocol import rv; return rv(payload, o)

def _read_nbt(payload, o):
    from nbt_reader import rnbt_disk; return rnbt_disk(payload, o)

def _read_particle(payload, o):
    from protocol import rv
    pid, o = rv(payload, o); o += 8  # skip 2 floats
    return None, o

def _read_villager_data(payload, o):
    from protocol import rv
    v1, o = rv(payload, o)
    v2, o = rv(payload, o)
    v3, o = rv(payload, o)
    return (v1, v2, v3), o

def _read_opt_varint(payload, o):
    from protocol import rv
    vid, o = rv(payload, o)
    if vid > 0: return rv(payload, o)
    return None, o

def _read_pose(payload, o):
    from protocol import rv; return rv(payload, o)

_META_READERS = {
    0: _read_byte, 1: _read_varint, 2: _read_float, 3: _read_string,
    4: _read_chat, 5: _read_opt_chat, 6: _read_slot, 7: _read_boolean,
    8: _read_rotation, 9: _read_position, 10: _read_opt_position,
    11: _read_direction, 12: _read_opt_uuid, 13: _read_block_state,
    14: _read_nbt, 15: _read_particle, 16: _read_villager_data,
    17: _read_opt_varint, 18: _read_pose,
}


def parse_entity_metadata(payload, offset=0, debug_ctx=""):
    """Parse 1.16.5 entity metadata from packet payload.
    Returns (dict of {index: value}, new_offset). Stops at 0xFF."""
    from protocol import rv
    import sys
    meta = {}
    start_offset = offset
    while offset < len(payload):
        index = payload[offset]; offset += 1
        if index == 0xFF: break
        tid, offset = rv(payload, offset)
        reader = _META_READERS.get(tid)
        if reader:
            try:
                meta[index], offset = reader(payload, offset)
            except Exception as e:
                ctx = f" [meta idx={index} type={tid}]" if debug_ctx else ""
                print(f"  [DEBUG] meta parse error{debug_ctx} idx={index} type={tid}: {type(e).__name__}: {e} "
                      f"near offset={offset} "
                      f"bytes={payload[max(0,offset-4):offset+8].hex()}", file=sys.stderr)
                break
        else:
            ctx = f" [meta idx={index}]" if debug_ctx else ""
            print(f"  [DEBUG] unknown meta type{debug_ctx} idx={index} tid={tid} "
                  f"offset={offset} bytes={payload[max(0,offset-4):offset+8].hex()}", file=sys.stderr)
            break
    return meta, offset


def armor_stand_meta_to_nbt(meta):
    """Convert armor stand metadata dict to NBT tags dict.
    Returns {tag_name: nbt_tag_value}."""
    import nbtlib.tag as T
    tags = {}
    # Index 0: status flags — bit 5 = invisible
    if 0 in meta and meta[0] & 0x20:
        tags['Invisible'] = T.Byte(1)
    # Index 2: Optional Chat → CustomName
    if 2 in meta and meta[2] is not None:
        tags['CustomName'] = T.String(meta[2])
    # Index 3: Boolean → CustomNameVisible
    if 3 in meta:
        tags['CustomNameVisible'] = T.Byte(1 if meta[3] else 0)
    # Index 14: armor stand flags
    if 14 in meta:
        f = meta[14]
        if f & 0x01: tags['Small'] = T.Byte(1)
        tags['NoGravity'] = T.Byte(0 if (f & 0x02) else 1)  # inverted
        if f & 0x08: tags['NoBasePlate'] = T.Byte(1)
        if f & 0x10: tags['Marker'] = T.Byte(1)
    # Indices 16-21: Rotation (head, body, left arm, right arm, left leg, right leg)
    POSE_KEYS = ['Head', 'Body', 'LeftArm', 'RightArm', 'LeftLeg', 'RightLeg']
    pose_parts = {}
    for idx, key in enumerate(POSE_KEYS):
        if idx + 16 in meta:
            pose_parts[key] = T.List[T.Float]([T.Float(v) for v in meta[idx + 16]])
    if pose_parts:
        pc = T.Compound()
        for k, v in pose_parts.items():
            pc[k] = v
        tags['Pose'] = pc
    return tags


# ── Villager profession / type mappings (1.16.5) ──────────────

VILLAGER_TYPES = {0: "desert", 1: "jungle", 2: "plains", 3: "savanna",
                   4: "snow", 5: "swamp", 6: "taiga"}

VILLAGER_PROFESSIONS = {
    0: "none", 1: "armorer", 2: "butcher", 3: "cartographer",
    4: "cleric", 5: "farmer", 6: "fisherman", 7: "fletcher",
    8: "leatherworker", 9: "librarian", 10: "mason", 11: "nitwit",
    12: "shepherd", 13: "toolsmith", 14: "weaponsmith",
}


def villager_meta_to_nbt(meta):
    """Convert villager metadata (index 16: VillagerData) to NBT."""
    if 16 not in meta: return {}
    import nbtlib.tag as T
    vtype_id, profession_id, level = meta[16]
    vd = T.Compound()
    vd["level"] = T.Int(level)
    vd["profession"] = T.String(
        f"minecraft:{VILLAGER_PROFESSIONS.get(profession_id, 'none')}")
    vd["type"] = T.String(
        f"minecraft:{VILLAGER_TYPES.get(vtype_id, 'plains')}")
    return {"VillagerData": vd}


# ── Unified entity metadata → NBT ────────────────────────────

def entity_meta_to_nbt(entity_type, meta):
    """Build NBT tags dict from entity metadata for any entity type."""
    import nbtlib.tag as T
    tags = {}
    # Index 0: status flags — bit 5 = invisible (for ALL entities)
    if 0 in meta and meta[0] & 0x20:
        tags['Invisible'] = T.Byte(1)
    # Index 2: Optional Chat → CustomName
    if 2 in meta and meta[2] is not None:
        tags['CustomName'] = T.String(meta[2])
    # Index 3: Boolean → CustomNameVisible
    if 3 in meta:
        tags['CustomNameVisible'] = T.Byte(1 if meta[3] else 0)
    # Health — set for living entities (metadata index 8=health float in 1.16)
    # Actually health is in metadata index 8 for living entities
    # But we set a safe default instead to avoid relying on partial metadata
    # Per-entity overrides below

    # Armor stand (type 1)
    if entity_type == 1:
        tags.update(armor_stand_meta_to_nbt(meta))
    # Villager (type 93)
    elif entity_type == 93:
        tags.update(villager_meta_to_nbt(meta))
    # Wandering trader (type 95) - same VillagerData structure
    elif entity_type == 95:
        tags.update(villager_meta_to_nbt(meta))
    # Item frame (type 38)
    elif entity_type == 38:
        from item_data import item_name
        if 7 in meta and meta[7] is not None:  # Item (Slot)
            item = meta[7]
            it = T.Compound()
            it["id"] = T.String(item_name(item['id']))
            it["Count"] = T.Byte(item['Count'])
            if item.get('tag') is not None:
                it["tag"] = item['tag']
            tags['Item'] = it
        if 8 in meta:  # ItemRotation
            tags['ItemRotation'] = T.Byte(meta[8])
    # Item entity (type 37) — drops floating on ground
    elif entity_type == 37:
        from item_data import item_name
        if 7 in meta and meta[7] is not None:  # Item (Slot)
            item = meta[7]
            it = T.Compound()
            it["id"] = T.String(item_name(item['id']))
            it["Count"] = T.Byte(item['Count'])
            if item.get('tag') is not None:
                it["tag"] = item['tag']
            tags['Item'] = it
            # Set age/health for item entity
            tags['Health'] = T.Short(5)
            tags['Age'] = T.Short(0)

    return tags

# ── Painting Motive registry (1.16.5 VarInt ID → name) ──────

PAINTING_MOTIVES = {
    0: 'kebab', 1: 'aztec', 2: 'alban', 3: 'aztec2',
    4: 'bomb', 5: 'plant', 6: 'wasteland',
    7: 'pool', 8: 'courbet', 9: 'sea', 10: 'sunset', 11: 'creebet',
    12: 'wanderer', 13: 'graham',
    14: 'match', 15: 'bust', 16: 'stage', 17: 'void',
    18: 'skull_and_roses', 19: 'wither',
    20: 'fighters', 21: 'pointer', 22: 'pigscene', 23: 'burning_skull',
    24: 'skeleton', 25: 'donkey_kong',
}
