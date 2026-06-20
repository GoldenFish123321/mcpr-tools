# mcpr-tools

Minecraft Replay Mod `.mcpr` → 世界存档提取。

**⚠️ 仅支持 Minecraft 1.16.5 / protocol 754 的录制文件。其他版本兼容性未知。**

## 项目结构

```
mcpr-tools/
├── extract_batch.py    385 行  — 主入口，编排整个提取管线
├── block_data.py        42 行  — blocks.json 加载、bn()/bp()、biome 常量
├── protocol.py          67 行  — rv() VarInt 解码、packets() 流解析器
├── nbt_reader.py       143 行  — NR/NRD NBT 读取器（网络+磁盘双格式）
├── mca_writer.py        47 行  — make_entry()、write_region() MCA 组装
├── level_utils.py       83 行  — build_level_dat() 纯函数，level.dat 唯一真相源
├── seed_validator.py   123 行  — cubiomes 群系校验（仅 --seed 时加载）
└── blocks.json                 — Minecraft 1.16.5 官方 block states 数据
```

### 模块职责

| 模块 | 职责 |
|---|---|
| `extract_batch.py` | 遍历 `.mcpr` → 四层过滤 → 组装 MCA → 生成 level.dat |
| `block_data.py` | 加载官方 `blocks.json`，提供 `bn(bid)` / `bp(bid)` 查询和 `END_BIOMES` / `NETHER_BIOMES` 常量 |
| `protocol.py` | Minecraft 协议 VarInt 解码 `rv()` 和 `.tmcpr` 流解析器 `packets()` |
| `nbt_reader.py` | 轻量 NBT 解析——`NR`（网络格式 VarInt string）、`NRD`（磁盘格式 2-byte string） |
| `mca_writer.py` | Anvil `.mca` 区域文件写入——sector 布局、zlib 压缩、偏移表 |
| `level_utils.py` | 构建合法 1.16.5 `level.dat`（旁观模式、作弊开启），支持 `--seed` 切换虚空/真实地形 |
| `seed_validator.py` | 基于 cubiomes C 库的精确群系校验——16/16 格 100% 匹配 |

### 过滤逻辑（四层）

1. **End/Nether 维度** — 剔除 End（biome 9,40-43）和 Nether（biome 8,170-173）
2. **Y=1 全泥土** — 剔除 lobby/city 平地世界
3. **Y=0 全基岩** — 剔除没有基岩层的 chunk
4. **种子群系精确匹配** — 当提供 `--seed` 时，要求 chunk 的 16 个 biome 格与 cubiomes 预测 **100% 一致**（scale=4 biome 坐标），剔除不属于该种子的 lobby/其他世界

## 依赖

```bash
pip install nbtlib minecraft-data
```

### 可选依赖（`--seed` 功能）

```bash
pip install cubiomespi
```

仓库自带预编译的 `lib.dll`（Windows）和 `lib.so`（Linux）——**无需手动编译**。`seed_validator.py` 会自动找到它们。

如果因为某些原因需要自行编译（例如升级 cubiomes 版本），参考以下步骤：

**Windows (PowerShell)**：
```powershell
git clone https://github.com/Cubitect/cubiomes.git
cd cubiomes
gcc -shared -o lib.dll -fPIC -O2 `
  path\to\mcpr-tools\newlib.c `
  util.c noise.c layers.c generator.c finders.c biomes.c biomenoise.c quadbase.c `
  -I. -lm
cp lib.dll path\to\mcpr-tools\
```

**Linux**：
```bash
git clone https://github.com/Cubitect/cubiomes.git
cd cubiomes
gcc -shared -o lib.so -fPIC -O2 \
  /path/to/mcpr-tools/newlib.c \
  util.c noise.c layers.c generator.c finders.c biomes.c biomenoise.c quadbase.c \
  -I. -lm
cp lib.so /path/to/mcpr-tools/
```

不编译也可以：脚本会自动回退到 scale=1，功能正常但匹配精度略低。
```

## 用法

```bash
# 虚空世界（默认）
python3 extract_batch.py /path/to/mcpr_files/ output_survival

# 带种子的真实地形 + 群系过滤
python3 extract_batch.py /path/to/mcpr_files/ output_survival --seed -1054699291496705673
```

输出：`output_survival/survival_world/` — 可直接用 Minecraft 1.16.5 打开的存档。

## 以模块方式使用

```python
from level_utils import build_level_dat
from nbtlib import File

# 虚空世界
root = build_level_dat()
File(root, gzipped=True, byteorder="big").save("level.dat")

# 真实地形世界
root = build_level_dat(seed=123456)
File(root, gzipped=True, byteorder="big").save("level.dat")
```

```python
from seed_validator import check_biomes_exact
from cubiomespi import MCVersion

# 校验单个 chunk 的群系是否与种子匹配
matched, mismatches = check_biomes_exact(
    MCVersion.MC_1_16_5,      # version
    123456,                    # seed
    0, 0,                      # chunk (cx, cz)
    packet_biomes,             # 1024 ints from ChunkData packet
)
# matched == 16 表示完全一致
```
