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

`src/server/skills/registry.ts` 登记本目录八个 Skill 的契约路径、实现状态、脚本与服务端 runner；
`src/server/agents/registry.ts` 定义角色的工具白名单。

根目录下只保留两类内容：

- 八个 canonical 业务 Skill：名称必须出现在 `src/contracts/identifiers.ts` 的 `skillIdSchema` 中；
- 明确标注为实现参考资产的目录，例如 `deep-pit-monitoring-report`。

不再参与主链或尚未纳入 Skill 枚举的团队原型放入 `_archive/prototypes/`，
避免与正式业务 Skill 混淆。归档目录只作参考，不会被服务端注册表自动接入。

**当前实现状态**（`status` 由真实实现路径推导，不是手工标注）：

| Skill | 状态 | 实现 |
|---|---|---|
| `parse-monitoring-data` | `implemented` | `scripts/inspect_file.py` |
| `evaluate-thresholds` | `implemented` | `scripts/run_judgement.py`、`scripts/check_strictness.py` |
| `retrieve-standard-evidence` | `implemented` | `src/server/skills/retrieve-standard-evidence/runner.ts` |
| `render-daily-report` | `implemented` | `scripts/render_daily_report.py` + 服务端 runner |
| `validate-report` | `implemented` | `scripts/validate_report.py` + 服务端 runner |
| 其余三个 | `not_implemented` | — |

**确定性计算实现放在对应 `scripts/` 中，由服务端工具层以子进程方式调用。**

- 实现语言为 **Python**（不是 TypeScript）：确定性计算引擎位于 `确定性计算层/pipeline/`，
  为**纯标准库、零第三方依赖**；`scripts/` 下是**薄协议封装**，不含判定逻辑。
- 不用 TypeScript 重写引擎：判定逻辑已有 223 项回归测试覆盖，
  二次实现会给「同一输入必得同一输出」这条确定性性质引入偏差。
- Node 侧桥接实现：`src/server/skills/python-bridge.ts`（超时、错误码映射、解释器探测）。
- 规范证据检索是服务端 TypeScript runner，通过统一 Retriever 调用 Pinecone 或本地 Provider；
  它只返回带来源证据和弃权结果，不重写引擎事实。
- 报告与审计适配器复用 `deep-pit-monitoring-report` 的表式映射经验，但只消费冻结引擎事实
  和稳定证据 ID；该参考资产自带的计算、阈值重判和本地 RAG 不进入服务端主链。
- 可运行原型：`tools/bridge-smoke/run_judgement.mjs`，协议见其 `README.md`。
- 具体业务测试放在相应 `tests/` 下；当前端到端用例在根目录
  `tests/upload-and-run.test.ts`（需 Python，找不到时自动跳过）。

## Agent 编排约定

首版编排层收敛为三个逻辑 Agent：

- `Supervisor Agent`：选择专业 Agent、维护共享状态、控制重试、退回、终止和人工确认；
- `报告交付 Agent`：调用报告生成 Skill，只消费结构化事实、证据和分析快照；
- `审计 Agent`：调用报告校验 Skill，将问题退回报告交付 Agent 或提交工程师。

数据解析、数据准备、确定性计算、规范比对、证据检索和工况分析属于 Skill / 服务能力，
由 Supervisor 按共享状态调用，不再为每项能力额外设置 Agent。Skill 尚未实现或模型配置
缺失时必须返回明确的能力不可用状态，不得用 Mock 或自然语言结果冒充成功。

这些角色在同一个 Next.js 应用进程中运行，不要求多个模型或独立服务。角色之间只传递经过
Schema 校验的共享状态；每个角色必须声明职责、可用 Skill、输入输出、失败边界和终止条件。

编排层不得自行计算监测数值或报警阈值，不得修改 Skill 返回的结构化事实，不得使用案例结论
覆盖规范判据，不得自动签发报告或发布正式预警。

首版自动修订最多两轮。修改草稿必须使旧审计失效；修改上游事实或证据必须使受影响的下游分析、
草稿和审计失效。达到次数、调用或时间预算后转工程师复核。

## 首批 Skill

1. `parse-monitoring-data`
2. `normalize-monitoring-data`
3. `evaluate-thresholds`
4. `retrieve-standard-evidence`
5. `retrieve-similar-cases`
6. `analyze-work-condition`
7. `render-daily-report`
8. `validate-report`

## 参考与归档资产

- `deep-pit-monitoring-report/`：日报表式与实现参考资产。服务端只通过 canonical
  `render-daily-report` / `validate-report` 适配器复用其中的表式经验。
- `_archive/prototypes/fill-summary-table/`：附录 C/D/E/F 与判定汇总表填表原型。
- `_archive/prototypes/monitoring-preprocess-evaluate/`：宽表预处理、附表 E/F 和预警评价原型。

归档资产中的脚本可能包含独立计算、重判或本地 RAG 路径；除非先完成契约评审和服务端适配，
不得直接接入主链。
