---
name: "parse-monitoring-data"
description: "解析基坑监测 CSV 数据并核验必填字段。上传、导入或读取当日监测原始数据时调用。"
---

# 监测数据解析

## 触发条件

- 收到待导入的基坑监测 CSV 文件或 CSV 文本。
- 后续标准化、阈值判断需要先获得结构化记录。
- 不用于单位换算、数值计算、超限判断或业务归因。

## 输入

输入必须且只能包含以下二者之一：

- `path`：UTF-8 或 UTF-8 BOM 编码的 CSV 文件路径。
- `text`：完整 CSV 文本。

CSV 必填列为：`point_id`、`timestamp`、`metric`、`value`、`unit`、`direction`、`baseline_value`、`previous_value`、`interval_hours`。

## 输出

成功时返回：

- `records`：按原始字段解析的记录列表；
- `source`：文件路径或 `<inline>`；
- `row_count`：数据行数；
- `trace`：解析动作、必填字段、实际字段和行数。

输出只表示语法解析成功，不表示数据已标准化或可用于工程判断。

## 执行流程

1. 校验 `path` 与 `text` 是否恰好提供一个。
2. 使用 UTF-8 BOM 兼容方式读取文件，或直接读取文本。
3. 按 CSV 表头解析并核验全部必填列。
4. 确认至少存在一行数据。
5. 返回原始记录和可追踪信息，交给标准化 Skill。

## 失败与弃权边界

- 同时提供或均未提供 `path`、`text`：以 `INVALID_INPUT` 弃权。
- 缺少任一必填列：以 `MISSING_FIELD` 弃权，并列出缺失列。
- CSV 没有数据行：以 `DATA_QUALITY` 弃权。
- 文件不存在、不可读、编码错误或解析出现未预期异常：安全弃权，不猜测或补造数据。
- 不自动推断缺失字段，不修正单位、方向或数值，不输出安全结论。
