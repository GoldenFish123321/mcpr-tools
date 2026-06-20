# mcpr-tools

Minecraft Replay Mod `.mcpr` → 世界存档提取。

**⚠️ 仅支持 Minecraft 1.16.5 / protocol 754 的录制文件。其他版本兼容性未知。**

## 项目结构

```
mcpr-tools/
├── extract_batch.py    299 行  — 主入口，编排整个提取管线
├── block_data.py        42 行  — blocks.json 加载、bn()/bp()、biome 常量
├── protocol.py          69 行  — rv() VarInt 解码、packets() 流解析器
├── nbt_reader.py       143 行  — NR/NRD NBT 读取器（网络+磁盘双格式）
├── mca_writer.py        47 行  — make_entry()、write_region() MCA 组装
├── level_utils.py       76 行  — build_level_dat() 纯函数，level.dat 唯一真相源
└── blocks.json                 — Minecraft 1.16.5 官方 block states 数据
```

### 模块职责

| 模块 | 职责 |
|---|---|
| `extract_batch.py` | 遍历 `.mcpr` → 过滤 ChunkData(0x20) → 双层过滤（基岩+biome）→ 组装 MCA → 生成 level.dat |
| `block_data.py` | 加载官方 `blocks.json`，提供 `bn(bid)` / `bp(bid)` 查询和 `END_BIOMES` / `NETHER_BIOMES` 常量 |
| `protocol.py` | Minecraft 协议 VarInt 解码 `rv()` 和 `.tmcpr` 流解析器 `packets()` |
| `nbt_reader.py` | 轻量 NBT 解析——`NR`（网络格式 VarInt string）、`NRD`（磁盘格式 2-byte string） |
| `mca_writer.py` | Anvil `.mca` 区域文件写入——sector 布局、zlib 压缩、偏移表 |
| `level_utils.py` | 构建合法 1.16.5 `level.dat`（旁观模式、作弊开启），两处复用同一份代码 |

### 过滤逻辑

1. **Y=1 全泥土检查** — 剔除 lobby/city 平地世界
2. **Y=0 全基岩检查** — 剔除没有基岩层的 chunk
3. **Biome 检查** — 剔除 End（biome 9,40-43）和 Nether（biome 8,170-173）维度

## 依赖

```bash
pip install nbtlib minecraft-data
```

## 用法

```bash
python3 extract_batch.py /path/to/mcpr_files/ output_survival
```

输出：`output_survival/survival_world/` — 可直接用 Minecraft 1.16.5 打开的存档。

## 以模块方式使用

所有模块可独立 import：

```python
from level_utils import build_level_dat
from nbtlib import File

# 虚空世界
root = build_level_dat(level_name="void", generator_name="flat", generator_options="3;minecraft:air;64;minecraft:the_void")
File(root, gzipped=True, byteorder="big").save("level.dat")
```
