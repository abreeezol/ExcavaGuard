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
- 每条记录需包含 `point_id`、`timestamp`、`metric`、`value`、`unit`、`direction`、`baseline_value`、`previous_value`、`interval_hours`。
- 当前支持单位：`mm`、`cm`、`m`；方向仅支持 `positive`、`negative`。

## 输出

成功时返回：

- `records`：标准化记录列表；
- 点号去除首尾空白并转为大写；
- 时间转为 ISO 8601；
- `value`、`baseline_value`、`previous_value` 统一换算为毫米；
- `unit` 固定为 `mm`；
- `trace`：记录数量、规范单位和规则标识。

## 执行流程

1. 校验 `records` 为非空列表且每行均为对象。
2. 规范单位文本，并按确定性换算因子转换数值。
3. 解析时间、数值和采样间隔，确认间隔大于零。
4. 规范点号、监测项和方向。
5. 以“点号 + 时间 + 监测项”检查重复记录。
6. 任一行失败则整批弃权；全部通过后返回标准化结果。

## 失败与弃权边界

- 输入为空或类型错误：以 `INVALID_INPUT` 弃权。
- 单位不受支持：以 `UNSUPPORTED_UNIT` 整批弃权。
- 日期、数值、点号、监测项、方向或间隔无效：以 `DATA_QUALITY` 弃权。
- 发现重复键：以 `DATA_QUALITY` 弃权。
- 不猜测未知单位，不插补缺失值，不静默丢弃问题行，不改变原始工程含义。
