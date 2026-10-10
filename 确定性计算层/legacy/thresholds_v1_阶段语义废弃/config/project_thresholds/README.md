# 用户阈值导入目录（阶段2 / 阶段3）

## 用途

把不同标准、地方规程或项目经审批的专项方案阈值文件放进本目录，系统会自动加载并
**按阶段覆盖**内置的通用默认阈值（阶段1）。

## 放置规则

| 阶段 | 文件名要求 | 说明 |
|---|---|---|
| **阶段2 · 导入标准/地方规程** | `*.json`（`stage: 2`） | 覆盖阶段1 |
| **阶段3 · 项目专项方案** | `*.json`（`stage: 3`） | 覆盖阶段2，优先级最高 |

- 文件必须是 UTF-8 JSON，遵循 `../threshold_import.schema.json`
- 文件名以 `.example.json` 结尾的文件**不会被加载**（示例文件）
- 多个同阶段文件按文件名排序依次合并；后加载者覆盖先加载者

## 优先级规则（后一阶段覆盖前一阶段）

```
阶段1 通用默认阈值 (GB 50497-2019)
        ↓ 被覆盖
阶段2 导入标准 / 地方规程阈值
        ↓ 被覆盖
阶段3 项目专项方案 / 人工审定阈值   ← 最终生效
```

- 覆盖粒度为 **`metric_key` + `rule_id` + 字段**
- **只覆盖导入文件中显式出现的字段**；未出现的字段继承上一阶段，不会清空
- 每次判定结果都会输出 `threshold_source_stage` / `threshold_source_label`
  / `overridden_fields`，可逐条追溯

## 最小示例

```json
{
  "schema_version": "1.0",
  "stage": 3,
  "source_id": "PRJ-DEMO-001",
  "source_label": "某某项目基坑监测专项方案（经审批）",
  "source_type": "project_plan",
  "metrics": {
    "wall_top_horizontal_displacement": {
      "rules": [
        {
          "rule_id": "WTHD-L1-PILE",
          "safety_level": ["一级"],
          "support_type": ["地下连续墙"],
          "cumulative_mm": 25,
          "rate_mm_per_day": 2,
          "evidence": { "standard": "某某项目专项方案", "clause": "第5.3条" }
        }
      ]
    }
  }
}
```

> 上例中 `WTHD-L1-PILE` 的 `cumulative_pct_H` 未给出，因此**继承**阶段1 的 0.2%~0.3%H；
> `cumulative_mm` 与 `rate_mm_per_day` 被覆盖为 25 mm 与 2 mm/d。

## 取值区间写法

规范表格常给出区间（如 20~30 mm），支持三种写法：

```json
"cumulative_mm": 25                        // 直接给定值
"cumulative_mm": { "min": 20, "max": 30 }  // 区间，按 selection_policy 解析
"cumulative_mm": null                      // 显式置空（表示不适用）
```

区间解析策略（默认 `conservative` 取下限，偏安全）：

| 策略 | 含义 |
|---|---|
| `conservative` | 取区间**下限**（较严格）—— 默认 |
| `lenient` | 取区间**上限**（较宽松） |
| `midpoint` | 取中值 |

可在导入文件的 `selection_policy.range_resolution` 中覆盖全局默认。

## 校验

导入前建议先校验：

```python
from threshold_loader import ThresholdConfig, ThresholdError
cfg = ThresholdConfig()
problems = cfg.validate_import(payload)   # 返回问题列表，空列表即通过
```

## 安全约束

- 不得在未获设计方确认的情况下，用导入阈值替代经审批的专项方案
- 导入文件必须填写真实的 `source_label`，系统会将该标签原样输出到日报中
- 缺失 `evidence.standard` 的规则会在校验时被标记为问题
