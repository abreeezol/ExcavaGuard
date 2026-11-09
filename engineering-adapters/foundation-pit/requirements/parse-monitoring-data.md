---
name: "parse-monitoring-data"
description: "解析基坑监测数据文件（CSV/TSV/Excel）并核验必填字段。上传、导入或读取当日监测原始数据时调用。"
---

# 监测数据解析

## 触发条件

- 收到待导入的基坑监测数据文件（CSV / TSV / Excel）或 CSV 文本。
- 后续标准化、阈值判断需要先获得结构化记录。
- 不用于单位换算、数值计算、超限判断或业务归因。

## 输入

输入必须且只能包含以下二者之一：

- `path`：数据文件路径。编码按 `utf-8-sig → utf-8 → gb18030 → gbk → big5 → latin-1` 顺序自动探测。
- `text`：完整 CSV 文本。

**必填列（5 个）**：`point_id`、`timestamp`、`metric`、`value`、`unit`

**可派生列（缺失时由 `normalize-monitoring-data` 按测点时序派生，不是必填）**：
`baseline_value`、`previous_value`、`interval_days`、`interval_hours`

**可选列**：`direction`、`data_origin`、`note`

列名支持中英文常见写法（如「测点编号 / 观测日期 / 监测项目 / 本次观测值 / 单位」），
完整别名表见 `确定性计算层/contracts/monitoring_input.contract.json`。

## 输出

成功时返回：

- `records`：按规范字段名解析的记录列表（数值原样保留为字符串，不做转换）；
- `source`：文件路径或 `<inline>`；
- `row_count`：数据行数；
- `report`：编码、分隔符、列映射、未映射列、缺列清单；
- `trace`：解析动作、必填字段、实际字段和行数。

输出只表示语法解析成功，不表示数据已标准化或可用于工程判断。

## 执行流程

1. 校验 `path` 与 `text` 是否恰好提供一个。
2. 探测编码与分隔符并读取。
3. 按表头做列名映射，核验 5 个必填列。
4. 确认至少存在一行数据。
5. 返回原始记录与映射报告，交给标准化 Skill。

## 失败与弃权边界

- 同时提供或均未提供 `path`、`text`：以 `INVALID_INPUT` 弃权。
- 缺少任一必填列：以 `MISSING_FIELD` 弃权，并列出缺失列。
- 文件没有数据行：以 `DATA_QUALITY` 弃权。
- 文件不存在、不可读、编码错误或解析出现未预期异常：安全弃权，不猜测或补造数据。
- 不自动推断缺失字段，不修正单位、方向或数值，不输出安全结论。
- **不要求用户预先计算初始值、上次值与观测间隔** —— 这三项由后续环节按测点时序派生。

## 参考实现

`确定性计算层/pipeline/stage1_data_preparation/file_reader.py`，
契约文档 `确定性计算层/09_用户数据文件契约.md`。
