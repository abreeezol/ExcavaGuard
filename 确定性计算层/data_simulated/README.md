# data_simulated —— 模拟/生成数据（与原始数据完全隔离）

## 性质

本目录内**全部为模拟/生成数据**，不是真实工程监测数据。

隔离措施：

1. 独立目录，**不在** `基坑智守项目相关数据/` 之下，也不与 `derived/` 混放；
2. 文件名统一含 `SIMULATED`；
3. 每条记录带 `data_origin = "simulated"`、`is_simulated = TRUE`；
4. 每条记录带 `source_dataset = "SIMULATED-EXCAVAGUARD-V1"` 溯源标识；
5. 汇总统计中 `simulated_records` 与 `real_records` **分列**，绝不合并。

## 用途

1. 为确定性计算与规范比对提供**带真值标签**的多风险测试集（S1~S27）；
2. 与真实数据结合，一起送入三阶段流程，验证混合输入下的流程稳定性。

## 生成

```
python -B tools/generate_simulated_dataset.py
```

## 验证

```
python -B tools/run_simulated_validation.py          # 场景覆盖率验证
python -B tools/run_combined_real_and_simulated.py   # 真实 + 模拟合并跑通
```

## 禁止

- 不得用于任何真实工程判定；
- 不得与真实数据合并统计而不加区分；
- 不得将其结果表述为工程结论。
