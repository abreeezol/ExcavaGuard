---
name: "normalize-monitoring-data"
description: "统一监测记录的点号、时间、方向、单位和数值格式。解析完成后、阈值计算前调用。"
---

# 监测数据标准化

## 触发条件

- 已获得 `parse-monitoring-data` 输出的非空记录列表。
- 需要把不同长度单位统一为毫米，并校验点号、时间、方向和重复记录。
- 不用于解析原始文件、选择阈值或生成结论。

## 输入

- `records`：非空对象列表。
- 每条记录需包含 `point_id`、`timestamp`、`metric`、`value`、`unit`。
- `baseline_value`、`previous_value`、`interval_days` / `interval_hours` **可缺失**，
  由本环节按测点时序派生（见下）。
- `direction` 可选，支持 `positive` / `negative` 及中文与符号写法（`正` `负` `+` `-` `上升` `下降` `隆起` `沉降` 等）。
- 当前支持单位：长度 `mm` `cm` `dm` `m` `km`；压强 `pa` `kpa` `mpa`；力 `n` `kn` `mn`；
  无量纲（`1` `ratio` `%` `度` `°`）；温度（`℃` `°C` `c` `celsius` `摄氏度`）。

## 时序派生（本环节职责）

按 `point_id` 分组、`timestamp` 升序，对**缺失**的字段确定性派生：

| 字段 | 派生规则 |
|---|---|
| `baseline_value` | 该测点首个有效观测值 |
| `previous_value` | 该测点前一个有效观测值；首期为 `null` |
| `interval_days` | 本期与前一有效观测的时间差（天）；首期为 `null` |

- 「有效观测」= 数值可解析的记录；**空值与非数值不参与派生**；
- 跨缺测期间隔按**真实天数**计算，不按 1 天；
- **显式提供的值优先**，派生不覆盖用户给的值；
- 派生字段打 `BASELINE_DERIVED` / `PREVIOUS_DERIVED` / `INTERVAL_DERIVED` 标记，
  使结果与日报能区分「用户给定的」与「系统算出的」。

## 输出

成功时返回：

- `records`：标准化记录列表；
- 点号去除首尾空白并转为大写；
- 时间转为 ISO 8601；
- `value`、`baseline_value`、`previous_value` 按量纲换算为标准单位；
- 监测项名称映射为规范库 `metric_key`（支持中文标准名、去括号简称与常见俗称）；
- `derived`：派生统计（各字段派生条数、测点数）；
- `trace`：记录数量、规范单位和规则标识。

## 执行流程

1. 校验 `records` 为非空列表且每行均为对象。
2. 规范单位文本，并按确定性换算因子转换数值。
3. 解析时间、数值和采样间隔。
4. 规范点号、监测项和方向。
5. 以“点号 + 时间 + 监测项”检查重复记录。
6. **按测点时序派生缺失的初始值、上次值与观测间隔。**
7. 任一行失败则整批弃权；全部通过后返回标准化结果。

## 失败与弃权边界

- 输入为空或类型错误：以 `INVALID_INPUT` 弃权。
- 单位不受支持：以 `UNSUPPORTED_UNIT` 整批弃权。
- 日期、数值、点号、监测项或方向无效：以 `DATA_QUALITY` 弃权。
- 发现重复键：以 `DATA_QUALITY` 弃权。
- **不猜测未知单位，不插补缺失观测值，不静默丢弃问题行。**
- **时序派生是确定性规则，不是插补**：派生的是「相对量」（初始值/上次值/间隔），
  不是伪造观测值；任何观测值缺失仍然保持缺失并如实弃权。

## 参考实现

`确定性计算层/pipeline/stage1_data_preparation/ingest.py`（`normalize_records` / `derive_temporal_fields`），
契约文档 `确定性计算层/09_用户数据文件契约.md`。
