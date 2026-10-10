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

## 与 Web 应用的关系

`src/server/skills/registry.ts` 登记本目录八个 Skill 的契约路径、实现状态与脚本清单；
`src/server/agents/registry.ts` 定义角色的工具白名单。

**当前实现状态**（`status` 由脚本清单推导，不是手工标注）：

| Skill | 状态 | 脚本 |
|---|---|---|
| `parse-monitoring-data` | `implemented` | `scripts/inspect_file.py` |
| `evaluate-thresholds` | `implemented` | `scripts/run_judgement.py`、`scripts/check_strictness.py` |
| 其余六个 | `not_implemented` | — |

**确定性实现放在对应 `scripts/` 中，由服务端工具层以子进程方式调用。**

- 实现语言为 **Python**（不是 TypeScript）：确定性计算引擎位于 `确定性计算层/pipeline/`，
  为**纯标准库、零第三方依赖**；`scripts/` 下是**薄协议封装**，不含判定逻辑。
- 不用 TypeScript 重写引擎：判定逻辑已有 223 项回归测试覆盖，
  二次实现会给「同一输入必得同一输出」这条确定性性质引入偏差。
- Node 侧桥接实现：`src/server/skills/python-bridge.ts`（超时、错误码映射、解释器探测）。
- 可运行原型：`tools/bridge-smoke/run_judgement.mjs`，协议见其 `README.md`。
- 具体业务测试放在相应 `tests/` 下；当前端到端用例在根目录
  `tests/upload-and-run.test.ts`（需 Python，找不到时自动跳过）。

## 首批 Skill

1. `parse-monitoring-data`
2. `normalize-monitoring-data`
3. `evaluate-thresholds`
4. `retrieve-standard-evidence`
5. `retrieve-similar-cases`
6. `analyze-work-condition`
7. `render-daily-report`
8. `validate-report`
