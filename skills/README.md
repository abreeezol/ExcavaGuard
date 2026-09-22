# ExcavaGuard Skills

本目录集中管理项目的业务 Skill。每个 Skill 都是一个可独立理解、测试和组合的能力单元。

## 目录约定

```text
<skill-name>/
├── SKILL.md       # 能力定义、触发条件、输入输出和执行流程
├── references/    # 规范摘录、字段契约、示例和领域参考
├── scripts/       # 确定性计算、转换与校验脚本
├── skills/        # 仅存放该能力依赖的子 Skill
└── tests/         # 测试数据、预期结果和回归用例
```

## 设计原则

- 数值计算必须由 `scripts/` 中的确定性程序完成。
- `SKILL.md` 负责描述何时调用、如何调用及如何处理失败。
- 规范与案例检索结果必须携带来源和证据标识。
- 证据不足时必须弃权，不得生成确定性归因。
- Skill 之间通过结构化数据传递，不通过自然语言隐式传值。
- 正式预警和签发不属于任何自动化 Skill。

## 首批 Skill

1. `parse-monitoring-data`
2. `normalize-monitoring-data`
3. `evaluate-thresholds`
4. `retrieve-standard-evidence`
5. `retrieve-similar-cases`
6. `analyze-work-condition`
7. `render-daily-report`
8. `validate-report`
