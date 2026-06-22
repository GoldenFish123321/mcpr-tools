#!/usr/bin/env python3
"""Item data: item ID → 'minecraft:name' mapping from PrismarineJS items.json."""

import os
import json

_ITEMS_PATH = os.path.join(os.path.dirname(__file__), 'items.json')

_ITEM_MAP = {}

def _load():
    """Lazy-load items.json into _ITEM_MAP."""
    if _ITEM_MAP:
        return
    if os.path.exists(_ITEMS_PATH):
        with open(_ITEMS_PATH) as f:
            items = json.load(f)
        for item in items:
            _ITEM_MAP[item['id']] = item['name']
    else:
        # Fallback: try minecraft-data clone
        fallback_path = '/tmp/minecraft-data/data/pc/1.16.2/items.json'
        if os.path.exists(fallback_path):
            with open(fallback_path) as f:
                items = json.load(f)
            for item in items:
                _ITEM_MAP[item['id']] = item['name']


def item_name(item_id):
    """Return 'minecraft:name' string for a protocol-level item ID.
    
    Returns 'minecraft:air' for id 0, 'minecraft:unknown_item_{id}' for unknown IDs.
    """
    if item_id == 0:
        return 'minecraft:air'
    _load()
    name = _ITEM_MAP.get(item_id)
    if name:
        return f'minecraft:{name}'
    return f'minecraft:unknown_item_{item_id}'
