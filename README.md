# mcpr-tools

Minecraft Replay Mod `.mcpr` → 世界存档提取。

**⚠️ 仅支持 Minecraft 1.16.5 / protocol 754 的录制文件。其他版本兼容性未知。**

## 脚本

| 脚本 | 用途 |
|------|------|
| `extract_batch.py` | **主入口** — 提取 → 过滤 → 组装 MCA → level.dat |
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

输出：`output_survival/survival_world/` — 可直接用 Minecraft 1.16.5 打开的存档。
