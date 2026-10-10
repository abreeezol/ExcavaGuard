# SIMULATED 数据集字段字典（v1）

> 本数据集为**模拟/生成数据**，不是真实工程监测数据。

## 记录字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `point_id` | string | 测点编号 |
| `timestamp` | ISO 8601 | 观测日期 |
| `metric` | string | 监测项键，与 `standards/default` 中的 `metric_key` 一致 |
| `value` | number | 观测值 |
| `unit` | string | 单位（mm / kN / kPa / 1） |
| `direction` | string | 方向（positive / negative） |
| `baseline_value` | number | 初始值（首个有效观测） |
| `previous_value` | number | 上次观测值（前一有效观测） |
| `interval_hours` | number | 与上次观测的间隔（小时），本数据集固定 24 |
| `scenario_id` | string | 场景编号 S1~S27 |
| `scenario_name` | string | 场景名称 |
| `problem_category` | string | 问题类别 |
| `risk_level_expected` | string | 该场景**期望**达到的风险等级（真值标签） |
| `data_origin` | string | **恒为 `simulated`** |
| `source_dataset` | string | 溯源标识 `SIMULATED-EXCAVAGUARD-V1` |
| `is_simulated` | string | **恒为 `TRUE`** |
| `note` | string | 人工注入说明（缺测/污染/粗差等） |

## 配套文件

| 文件 | 说明 |
|---|---|
| `SIMULATED_工程条件_v1.json` | 安全等级、支护形式、开挖深度 H、设计值、逐测点条件、底板浇筑日 |
| `SIMULATED_场景清单_v1.json` | 场景定义 + 测点 + **期望风险等级/期望数据质量码**（用于覆盖率验证） |

## 观测设定

- 观测窗口：60 天，日频
- 底板浇筑日：第 40 天（此后位移速率限值 ×0.7）
- 安全等级：一级；支护形式：地下连续墙；开挖深度 H = 20 m
