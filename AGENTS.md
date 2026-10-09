# ExcavaGuard Agent 协作规范

## 项目概述

ExcavaGuard 是面向基坑监测场景的 AI 监测日报智能体。系统读取监测数据和施工工况，通过确定性规则完成数值计算与阈值判断，通过 RAG 提供规范和案例证据，通过多 Agent 协作完成数据治理、辅助归因、报告生成与独立审计。

系统只生成供工程师复核的日报草稿，不替代工程师发布预警、审核或签发正式报告。

## 当前阶段

项目目前处于应用初始化阶段：

- 已形成初步方案和多 Agent 架构设计；
- 已建立八个业务 Skill 的目录与 `SKILL.md`；
- 已确认主交付为独立 Web 多智能体应用，MVP 采用 Next.js + TypeScript 单体全栈；
- 已确认 WorkBuddy 专家、企业智能体或 MCP 仅作为主链路完成后的附加适配；
- 已建立 Next.js App Router 工作台空状态、Route Handlers、Zod 入口契约、角色和 Skill 注册信息；
- 已建立 LLM、Supabase、Pinecone 的服务端客户端入口，但尚未接通业务或真实云服务；
- `rag/` 仅为占位目录；
- 已固定依赖版本于 `package-lock.json`；具体 LLM、Embedding、rerank 模型和部署平台尚未确定；
- 尚未实现业务 Skill、Supervisor 状态图、鉴权、上传、工程测试数据和知识库；当前测试仅覆盖初始化工程边界。

任何 Agent 都不得把规划中的技术选型描述为已经实现。

## 权威文档

开始工作前按以下顺序读取：

1. `AGENTS.md`：全局协作规则和安全边界；
2. `memory.md`：当前稳定决策、项目状态与待确认事项；
3. `方案与迭代note/初步方案.md`：业务目标和初步技术判断；
4. `方案与迭代note/框架demo.md`：Skill 编排和多 Agent 设计；
5. `skills/README.md`：Skill 目录约定；
6. 目标 Skill 下的 `SKILL.md`：具体能力契约。

当文档发生冲突时，以工程师最新明确确认的内容为准，并同步修正文档，禁止私自选择对实现最方便的解释。

## 项目结构

```text
ExcavaGuard/
├── AGENTS.md
├── memory.md
├── README.md
├── package.json / package-lock.json
├── .env.example
├── src/
│   ├── app/                     # 页面与 Route Handlers
│   ├── components/              # 服务端界面组件
│   ├── contracts/               # 共享 Zod 入口契约
│   └── server/                  # Agent、Skill 注册与外部服务客户端入口
├── tests/
├── 方案与迭代note/
│   ├── 初步方案.md
│   └── 框架demo.md
├── skills/
│   ├── README.md
│   ├── .agents/
│   ├── parse-monitoring-data/
│   ├── normalize-monitoring-data/
│   ├── evaluate-thresholds/
│   ├── retrieve-standard-evidence/
│   ├── retrieve-similar-cases/
│   ├── analyze-work-condition/
│   ├── render-daily-report/
│   └── validate-report/
└── rag/
    └── README.md
```

每个业务 Skill 使用以下结构：

```text
<skill-name>/
├── SKILL.md
├── references/
├── scripts/
├── skills/
└── tests/
```

## 架构原则

- Agent 负责理解目标、规划步骤、调用 Skill、管理状态和处理冲突。
- Skill 负责执行边界明确、可测试、可复现的业务操作。
- RAG 负责提供带来源的规范和案例证据。
- 确定性程序负责数值计算、单位换算、阈值判断和一致性校验。
- LLM 只负责规划、解释和语言组织，不得改写结构化工程事实。
- 工程师负责最终预警、审核和报告签发。
- 六类 Agent 是单一 Web 应用中的逻辑角色，不要求多个独立模型服务；角色之间只通过经过 Schema 校验的共享状态协作。
- Web MVP 使用 Next.js + TypeScript 与服务端 Route Handlers，不在浏览器侧保存或调用任何密钥。
- `src/server/` 模块使用 `server-only` 隔离，Client Component 不得导入；共享契约放在 `src/contracts/`，不得反向引用服务端模块。
- 当前 `/api/health` 只表示进程存活；`/api/runs` 对合法输入仍返回 501。启用任务创建前必须补齐鉴权、资源授权、持久化与显式编排。
- Supabase 用于结构化状态与文件持久化，Pinecone 用于规范与案例向量索引；检索记录必须继续满足本文件的证据约束。
- 外部 LLM、Supabase 或 Pinecone 不可用时，只允许降级到确定性计算与基础模板草稿，不得把降级结果描述为完整智能分析。

规范判据的优先级高于案例经验。历史案例只能辅助解释原因，不能改变超限事实或降低风险等级。

## Agent 设计

当前规划包含一个 Supervisor 和五个专业 Agent：

- `Supervisor Agent`：任务规划、Agent 路由、共享状态管理、冲突处理和终止控制；
- `数据治理 Agent`：调用解析与标准化 Skill，决定数据是否可以进入分析；
- `判据与规范 Agent`：调用阈值判断与规范检索 Skill，绑定计算事实和规范依据；
- `风险归因 Agent`：调用案例检索与工况分析 Skill，给出候选原因和可信等级；
- `报告交付 Agent`：调用报告生成 Skill，只使用结构化事实生成草稿；
- `审计 Agent`：调用报告校验 Skill，从反方检查数字、引用、适用性和责任边界。

审计 Agent 发现问题后应退回对应责任 Agent，不得直接修改源事实。自动退回必须有次数上限，无法消解的冲突交给工程师。

Supervisor 与专业 Agent 优先使用 LangGraph.js 或同等显式状态图实现。首条纵向链路可以先采用 TypeScript 状态机，但路由、重试、终止、人工确认和运行轨迹必须结构化，不能只依靠自然语言 Prompt 隐式控制。

## Skill 开发规范

每个 `SKILL.md` 必须包含：

- 合法的 YAML frontmatter；
- 唯一且稳定的 `name`；
- 同时说明“做什么”和“何时调用”的 `description`；
- 触发条件；
- 输入字段及约束；
- 输出字段及语义；
- 执行流程；
- 失败与弃权边界。

目录内容职责如下：

- `references/`：字段契约、规范元数据、示例和领域参考；
- `scripts/`：确定性解析、计算、转换与校验程序；
- `skills/`：当前 Skill 依赖的子 Skill；
- `tests/`：测试输入、预期结果和回归用例。

Skill 之间只传递结构化数据，不把自然语言摘要作为下游计算输入。修改输入输出字段时，需要同步更新调用方、测试和 `方案与迭代note/框架demo.md`。

## RAG 约束

- 规范知识必须保存规范名称、版本、条文号、原文、适用条件和来源位置。
- 案例知识必须保存工程特征、来源、可信等级、相似条件和差异项。
- 检索优先使用元数据过滤，再组合关键词检索和向量检索。
- 检索结果必须携带稳定的证据 ID。
- 不得伪造条文、页码、规范版本、案例来源或匹配分数。
- 未检索到证据时返回“信息不足”，不能依靠模型常识补造。
- 规范全文和工程案例进入仓库前，必须确认授权和脱敏要求。

## 工程安全边界

以下规则不可绕过：

- 不在代码、示例或测试中写入未经专业人员确认的真实工程阈值。
- 演示阈值必须明确标记为 `demo`，并声明不得用于真实工程。
- 不自动修复未知单位、方向、测点映射或缺失字段。
- 不使用案例相似性证明因果关系。
- 不自动发布黄色、橙色或红色预警。
- 不生成自动签字、自动审核或已正式签发的表述。
- 不隐藏规范冲突、数据缺口、低可信结果或异常执行记录。
- 关键校验失败时停止输出报告成品，只返回错误和待确认项。

## 修改方式

- 优先做范围清晰的小改动，避免在一次任务中同时重构目录、契约和业务逻辑。
- 开始实现前先读取目标 Skill 的 `SKILL.md`。
- 新增顶层 Agent、Skill、RAG 数据集或共享状态字段时，先更新设计文档。
- 创建 Web 脚手架或引入生产依赖前，核对 `memory.md` 中已确认的技术方向；具体版本必须通过实际安装和运行验证。
- 不修改原始规范和案例文件；清洗结果、索引和派生数据应存放在独立目录。
- 不提交密钥、访问令牌、个人信息或未经脱敏的工程数据。
- 不删除方案、证据或测试资产，除非用户明确要求。

## 测试要求

每个 Skill 实现后至少覆盖：

- 一条正常输入；
- 一条边界输入；
- 一条非法输入；
- 一条需要弃权的输入；
- 输出字段和错误码验证；
- 运行轨迹与证据 ID 验证。

计算类 Skill 必须使用人工可核验的固定样例，并验证全部中间值。检索类 Skill 必须验证来源、版本、适用性过滤和无结果行为。报告类 Skill 必须验证数字与结构化事实逐字段一致。

在项目提供正式构建、检查和测试命令前，不得臆造命令。新增工具链后，应将经过实际验证的命令补充到本文件。

### 初始化工程命令

- 环境：Node.js 26.3.1（`.nvmrc`），npm；完整依赖版本见 `package-lock.json`。
- 安装：`npm ci`。
- 启动：`npm run dev`，本地访问 `http://localhost:3000`；初始页面不需要 `.env.local`。
- 检查：`npm run check`，依次执行 ESLint、路由类型生成、TypeScript 与 Vitest。
- 构建：`npm run build`，产物为 `.next/`；构建后使用 `npm start`。
- 沙箱中执行 Next.js 命令时可使用 `CI=1 NEXT_TELEMETRY_DISABLED=1`，避免写入用户目录缓存。
- `tests/server-only.ts` 仅供 Vitest 替换导入标记，不得用于绕过生产构建的服务端边界。
- 当前没有可执行的工程计算、检索或报告类 Skill；实现后仍须遵守上面的完整业务测试要求。

## 完成标准

一项修改只有在以下条件满足后才算完成：

- 改动符合目标 Skill 的职责边界；
- 输入输出契约同步更新；
- 对应测试或测试样例已经补充；
- 没有引入未经确认的工程事实；
- 错误、弃权和人工确认路径均有定义；
- 相关方案文档和 `memory.md` 已按需更新；
- 最终回复准确说明已完成内容、未完成内容和验证结果。
