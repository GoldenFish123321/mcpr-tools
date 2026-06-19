# mcpr-tools

Minecraft Replay Mod `.mcpr` → 世界存档提取。

## 脚本

| 脚本 | 用途 |
|------|------|
| `extract_batch.py` | **主入口** — 提取 → 四层过滤 → 组装 MCA → level.dat |
| `assemble_mca.py` | `_chunks/` → MCA 组装 |
| `filter_dimensions.py` | End/Nether biome 移除 |
| `build_timeline_v2.py` | PlayerPosition → 生存区时间线 |
| `create_level.py` | 生成 level.dat |
| `track_position.py` | 玩家位置追踪调试 |

## 依赖

```
pip install nbtlib minecraft-data
```

## 用法

```bash
python3 extract_batch.py /path/to/mcpr_files/ output_survival
```
