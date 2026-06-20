#!/usr/bin/env python3
"""Block data: state_id → (name, properties) mapping and biome constants.

Canonical: extract_batch.py lines 16-45.
"""
import os
import json as _json
import minecraft_data

mc = minecraft_data("1.16.5")

# Load official state_id → properties mapping from data generator
_reports_path = os.path.join(os.path.dirname(__file__), "blocks.json")
_STATE_PROPS = {}
if os.path.exists(_reports_path):
    with open(_reports_path) as f:
        _reports = _json.load(f)
    for name, data in _reports.items():
        for s in data["states"]:
            _STATE_PROPS[s["id"]] = (name, s.get("properties", {}))


def bn(bid):
    """Return block name string for palette (no properties)."""
    if bid in _STATE_PROPS:
        return _STATE_PROPS[bid][0]
    # Fallback: minecraft-data
    for b in mc.blocks_list:
        if b["minStateId"] <= bid <= b["maxStateId"]:
            return "minecraft:" + b["name"]
    return f"minecraft:block_{bid}"


def bp(bid):
    """Return (name, props_dict) for building Anvil palette entry."""
    if bid in _STATE_PROPS:
        return _STATE_PROPS[bid]
    return bn(bid), {}


END_BIOMES = {9, 40, 41, 42, 43}
NETHER_BIOMES = {8, 170, 171, 172, 173}
