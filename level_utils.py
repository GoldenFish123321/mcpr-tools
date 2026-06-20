#!/usr/bin/env python3
"""Build level.dat NBT — canonical from extract_batch.py lines 442-484."""
from nbtlib import tag as nbt_tag


def build_level_dat(
    level_name="survival_world",
    generator_name="default",
    generator_options="",
):
    """Return the root Compound for a Minecraft 1.16.5 level.dat.

    All callers share this single source of truth.
    """
    world_root = nbt_tag.Compound()
    data = nbt_tag.Compound()

    # Version
    ver = nbt_tag.Compound()
    ver["Id"] = nbt_tag.Int(2586)
    ver["Name"] = nbt_tag.String("1.16.5")
    ver["Snapshot"] = nbt_tag.Byte(0)
    data["Version"] = ver

    # Basic
    data["LevelName"] = nbt_tag.String(level_name)
    data["GameType"] = nbt_tag.Int(3)          # Spectator
    data["allowCommands"] = nbt_tag.Byte(1)    # Cheats
    data["Difficulty"] = nbt_tag.Byte(0)
    data["hasBeenLoadedInCreative"] = nbt_tag.Byte(1)
    data["RandomSeed"] = nbt_tag.Long(0)
    data["GameRules"] = nbt_tag.Compound()
    data["initialized"] = nbt_tag.Byte(1)
    data["Time"] = nbt_tag.Long(0)
    data["DayTime"] = nbt_tag.Long(0)
    data["LastPlayed"] = nbt_tag.Long(0)
    data["SizeOnDisk"] = nbt_tag.Long(0)
    data["version"] = nbt_tag.Int(19133)

    # Spawn
    data["SpawnX"] = nbt_tag.Int(0)
    data["SpawnY"] = nbt_tag.Int(80)
    data["SpawnZ"] = nbt_tag.Int(0)

    # Generator
    data["generatorName"] = nbt_tag.String(generator_name)
    data["generatorOptions"] = nbt_tag.String(generator_options)
    data["generatorVersion"] = nbt_tag.Int(0)

    # Player
    pl = nbt_tag.Compound()
    pl["Dimension"] = nbt_tag.String("minecraft:overworld")
    pl["Pos"] = nbt_tag.List[nbt_tag.Double]([
        nbt_tag.Double(0.0), nbt_tag.Double(80.0), nbt_tag.Double(0.0),
    ])
    pl["Rotation"] = nbt_tag.List[nbt_tag.Float]([
        nbt_tag.Float(0.0), nbt_tag.Float(0.0),
    ])
    pl["Motion"] = nbt_tag.List[nbt_tag.Double]([
        nbt_tag.Double(0.0), nbt_tag.Double(0.0), nbt_tag.Double(0.0),
    ])
    pl["playerGameType"] = nbt_tag.Int(3)
    pl["UUID"] = nbt_tag.IntArray([0, 0, 0, 0])
    pl["abilities"] = nbt_tag.Compound()
    pl["abilities"]["flying"] = nbt_tag.Byte(1)
    pl["abilities"]["invulnerable"] = nbt_tag.Byte(1)
    data["Player"] = pl

    # DataPacks
    dp = nbt_tag.Compound()
    dp["Enabled"] = nbt_tag.List[nbt_tag.String]([nbt_tag.String("vanilla")])
    dp["Disabled"] = nbt_tag.List[nbt_tag.String]([])
    data["DataPacks"] = dp

    world_root["Data"] = data
    return world_root
