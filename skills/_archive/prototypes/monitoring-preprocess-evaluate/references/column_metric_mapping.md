# 列名 → 监测项映射明细

本 skill 处理的宽表 CSV 列命名规则（由 `generate_3files_per_foundation.py` 生成）：

| 原始列名（示例） | 提取点号 | metric_key | 中文监测项 | 表 | 默认库阈值规则 |
|---|---|---|---|---|---|
| `地下水位-SW-01-原始值(mm)` | SW-01 | `groundwater_level` | 地下水位 | E | GWL-ALL（表 8.0.5） |
| `地表竖向位移-DBC-01-原始值(mm)` | DBC-01 | `surface_settlement` | 周边地表竖向位移 | E | SS-L1/L2/L3（表 8.0.4） |
| `分层竖向位移-FC-01-原始值(mm)` | FC-01 | `soil_layered_vertical_displacement` | 土体分层竖向位移 | E | **默认库无阈值 → 弃权 UNKNOWN_METRIC** |
| `坑底隆起-KB-01-原始值(mm)` | KB-01 | `basal_heave` | 坑底隆起（回弹） | E | BH-ALL（表 8.0.4） |
| `裂缝-LF-01-长度-原始值(mm)` | LF-01 | （无独立阈值） | 地表裂缝长度 | F | 仅监测记录，等级弃权 |
| `裂缝-LF-01-宽度-原始值(mm)` | LF-01 | `crack_width_surface` | 地表裂缝宽度 | F | CWS-NEW（新增裂缝，表 8.0.5） |

## 判定取值口径

- `报警值` = 阈值区间下限 `min`（偏安全，`range_resolution=conservative`）。
- `控制值` = 阈值区间上限 `max`（危险报警阈值）。
- 速率因子 = `1440 / interval_minutes`（5 分钟采样 → ×288，单位 mm/d）。
- 四级：红色（累计≥控制值）/ 橙色（累计≥报警值 或 速率≥报警速率）/ 黄色（累计≥0.7×报警值）/ 正常。

## 安全等级来源

- `深基础` → 一级；`浅基础` → 三级（由 `--foundation` 或文件名推断）。
- 无法解析时整批点标记 `未知`（MISSING_SAFETY_LEVEL），不判级。

## RAG 证据映射

- 有阈值的监测项：检索 `data/chroma_db/` 集合 `jikeng_norms`（标准库），
  查询语句含监测项中文名 + `evidence.clause`（如 `表8.0.4` / `表8.0.5`）。
- 本项目 RAG 当前仅含标准库，无独立案例库集合；案例检索未建时返回「信息不足」。
