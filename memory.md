# ExcavaGuard 项目记忆

> 本文件保存经过确认、需要跨任务延续的项目信息。临时执行日志、未经验证的猜测、密钥和原始敏感数据不得写入。

## 项目目标

ExcavaGuard 面向基坑监测工程师，将当日监测数据和施工工况整理为可复核、可追溯的监测日报草稿，并对异常条目提供受约束的辅助归因。

系统不替代工程师承担安全判断、预警发布、审核和签发责任。

## 当前状态

更新时间：2026-10-09

- 项目根目录已经建立。
- `方案与迭代note/初步方案.md` 已记录项目定位、总体架构、MVP 和评测方向。
- `方案与迭代note/框架demo.md` 已记录 Skill 编排、多 Agent 设计、共享状态和审计回路。
- `skills/` 已建立八个业务 Skill 的目录和 `SKILL.md`。
- 每个 Skill 已预留 `references/`、`scripts/`、`skills/` 和 `tests/`。
- `skills/.agents/` 已建立编排层说明。
- `rag/` 当前只有设计占位说明，尚未导入知识资产。
- 已确认最终主交付形态为独立 Web 多智能体应用，WorkBuddy 专家作为主链路完成后的附加适配项。
- 已确认 MVP 采用 Next.js + TypeScript 的单体全栈方案，不额外拆分 Python 后端。
- 已建立 Next.js App Router 初始化工程、工作台空状态、健康检查和运行请求校验接口。
- 已建立六类 Agent 的静态职责与工具白名单，以及八个 Skill 的契约映射；尚无可执行的 Agent 编排或业务 Skill。
- 已建立仅服务端使用的 LLM、Supabase、Pinecone 客户端入口；尚未进行真实服务联调、建立数据库表或导入知识。
- 已确认规范证据检索采用统一 Provider 接口，支持 Pinecone 托管方向与可选本地 RAG；两者共享证据 Schema 和上层 Skill，不复制业务链路。
- 已添加接口边界、环境变量与注册契约的固定测试；尚无工程业务测试集。
- 当前运行接口对合法输入返回 `501 FEATURE_NOT_IMPLEMENTED`，不创建运行记录或报告；页面不需要密钥即可启动。
- 本地项目已初始化 Git 仓库，当前分支为 `main`，远程 `origin` 指向 `https://github.com/abreeezol/ExcavaGuard.git`。远程仓库已完成首次推送，`main` 分支已创建，远程 `HEAD` 指向 `main`。

## 已确认架构

采用以下组合：

> 独立 Web 应用 + 多 Agent 协作 + Skill 工具层 + 双知识库 RAG + 确定性规则引擎 + 工程师签发

职责分配：

- Web 应用：提供对话、文件上传、运行轨迹、证据展开、人工确认和日报预览；
- Agent：任务理解、动态规划、路由、冲突处理和结果组织；
- Skill：执行可测试、可复现的具体业务能力；
- RAG：提供规范和历史案例证据；
- 规则引擎：完成数值计算与阈值判断；
- LLM：生成受约束的解释和报告语言；
- 工程师：确认关键配置、处理冲突并最终签发。

## 已确认应用技术方向

- 主应用采用 Next.js + TypeScript，前端与服务端 Route Handlers 保持在同一代码库。
- MVP 不单独建设 Python 或 FastAPI 后端；全部 LLM、数据库和文件访问必须在服务端执行。
- 模型接入优先采用 Vercel AI SDK 或等价的服务端适配层，禁止浏览器直接持有模型密钥。
- 多 Agent 编排优先采用 LangGraph.js；若首条链路尚不需要框架能力，可先以显式 TypeScript 状态机实现，但必须保持相同的状态与路由契约。
- 使用 Zod 定义共享状态、Agent 输入输出和 Skill 调用 Schema。
- Supabase PostgreSQL 保存项目、会话、运行状态、证据、人工确认和审计记录；Supabase Storage 保存原始文件与生成报告。
- Pinecone 保存规范库和案例库的向量索引，检索结果仍需携带来源元数据和稳定证据 ID。
- 本地规范 RAG 作为可选 Provider 通过 loopback HTTP 接入；本地模型、规范文本、切片与向量索引不进入主代码仓，也不成为 Web 主链路的必选依赖。
- 确定性数据处理、规则计算和报告校验使用 TypeScript 实现；测试优先采用 Vitest，日报优先生成 DOCX。
- Web 应用是比赛主交付物。WorkBuddy 专家、企业智能体或 MCP 接入只作为主链路稳定后的附加展示，不成为核心业务逻辑的唯一载体。
- 当前方案依赖远程 LLM、Pinecone 和 Supabase，不再宣称“完全离线静态包”；外部服务不可用时仅允许降级到确定性计算与基础模板草稿。

## Agent 组成

- `Supervisor Agent`
- `数据治理 Agent`
- `判据与规范 Agent`
- `风险归因 Agent`
- `报告交付 Agent`
- `审计 Agent`

Supervisor 是唯一总控角色。专业 Agent 不能绕过 Supervisor 改变流程状态，审计 Agent 不能直接修改源事实。

六类 Agent 是单一 Web 应用进程中的逻辑角色，不要求部署六个模型或六个独立服务。它们可以共享同一模型供应商，但必须具有独立职责、提示词、工具白名单、结构化输入输出和终止条件，并通过统一工程状态协作。

## Skill 组成

| Skill | 当前职责 |
| --- | --- |
| `parse-monitoring-data` | 解析 CSV 和核验必填字段 |
| `normalize-monitoring-data` | 统一点号、时间、单位、方向和数值格式 |
| `evaluate-thresholds` | 执行确定性的三重判据计算 |
| `retrieve-standard-evidence` | 检索规范条文、版本和适用条件 |
| `retrieve-similar-cases` | 检索相似工程与工况案例 |
| `analyze-work-condition` | 分析异常事实与施工工况的关联 |
| `render-daily-report` | 按模板生成监测日报草稿 |
| `validate-report` | 校验数字、状态、引用、模板和责任措辞 |

## 稳定原则

- 规则主判，RAG 举证，模型表达。
- 规范判据决定超限事实，案例不改变阈值。
- Skill 之间通过结构化数据传递。
- 报告数字必须来自结构化事实表。
- 所有规范和案例引用必须具有证据 ID。
- 信息不足时主动弃权。
- 多 Agent 需要形成规划、执行、审计和退回过程，不能只是多个 Prompt 并行输出。
- 审计不通过时退回责任 Agent；无法消解的冲突交给工程师。
- 系统输出始终标记为草稿，禁止自动签发或发布正式预警。

## 当前目录

```text
ExcavaGuard/
├── AGENTS.md
├── memory.md
├── README.md
├── package.json / package-lock.json
├── .env.example
├── src/
│   ├── app/                     # 工作台与 Route Handlers
│   ├── components/              # 服务端界面组件
│   ├── contracts/               # Zod 入口契约与角色标识
│   └── server/                  # 角色、Skill 注册与服务端客户端入口
├── tests/                       # 初始化工程边界测试
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

## 尚未确定

以下内容仍需讨论，不应被 Agent 默认：

- 最终使用的 LLM、Embedding 与 rerank 模型及版本；
- LangGraph.js 的具体版本和是否在首条 MVP 链路立即引入；
- 规范和案例资料的具体来源与授权方式；
- 项目专项方案与通用规范的优先级配置方式；
- 真实输入文件格式和字段名称；
- 日报模板的最终版本；
- Web Demo 的托管平台、域名和部署方式；
- WorkBuddy 附加适配采用个人专家、企业智能体还是 MCP。

## 待推进事项

1. 确认最小 CSV 输入数据契约、项目阈值和规范适用规则。
2. 在已建立的 Next.js 工程中实现用户鉴权、项目权限及文件上传。
3. 定义 Zod 共享状态 Schema、Agent 事件和持久化数据结构。
4. 实现数据解析、标准化、阈值判断和报告校验等确定性 Skill。
5. 定义 Supervisor 的路由、重试、退回、终止和人工确认规则。
6. 建设最小规范知识库与经过脱敏的案例知识库。
7. 接入服务端 LLM API、Supabase 和 Pinecone。
8. 跑通正常、超限、数据错误和证据不足四类流程。
9. 增加审计 Agent 的退回机制、运行轨迹和日报导出能力。
10. 主链路稳定后再制作 WorkBuddy 专家或 MCP 适配。

## 记忆维护规则

- 只记录已经确认且后续仍有价值的信息。
- 新决策应写明日期，并修改对应的旧结论，避免同时保留互相冲突的描述。
- 已完成事项从“待推进事项”移入“当前状态”。
- 技术选型经确认后补充具体版本和验证过的运行命令。
- 架构发生变化时，同时更新 `AGENTS.md`、`方案与迭代note/框架demo.md` 和相关 `SKILL.md`。
- 不写入密码、Token、个人身份信息、未经脱敏的工程数据或大段运行日志。

## 决策记录

### 2026-09-22

- 项目英文名确定为 `ExcavaGuard`。
- 项目采用 Skill 与 RAG 作为底层能力，但比赛展示增加多 Agent 协作。
- 多 Agent 采用 Supervisor、数据治理、判据与规范、风险归因、报告交付和审计六类角色。
- 暂不创建传统后端代码脚手架，优先完善 Skill、Agent、RAG 和项目文档结构。
- GitHub 远程仓库确定为 `https://github.com/abreeezol/ExcavaGuard.git`。

### 2026-10-03

- 比赛主交付形态确定为独立 Web 多智能体应用，不依赖 Codex、TRAE 或 WorkBuddy 才能运行。
- WorkBuddy 专家或企业智能体接入调整为主链路完成后的附加项，用于展示同一核心能力可以被桌面 Agent 调用。
- MVP 技术方向确定为 Next.js + TypeScript 单体全栈，使用 Route Handlers 承载服务端逻辑，不额外拆分 Python 后端。
- Agent 采用 Supervisor 与五个专业 Agent 的逻辑多角色结构，在单一应用进程中围绕共享状态协作，不要求多个独立模型服务。
- 初步基础设施确定为服务端 LLM API、Supabase PostgreSQL/Storage 与 Pinecone；Vercel AI SDK、LangGraph.js、Zod、Vitest 和 DOCX 工具作为优先选型，具体版本待实现时验证。
- 项目不再以“完全离线静态包”为交付承诺；外部模型或知识库不可用时只保留确定性计算和基础模板降级。

### 2026-10-09

- Next.js 初始化工程落地，延续既有 `skills/` 与 `rag/`；应用代码放入 `src/`，确定性业务实现仍应放入相应 Skill 的 `scripts/`。
- 接口初始化仅定义资源 UUID 与报告日期，不提前填充阈值、工程事实、证据或完整运行状态；六类角色注册信息不代表编排已经运行。
- 使用按服务延迟读取配置的客户端入口，没有默认模型；不填外部服务配置也可启动工作台。
- 依赖基线为 Next.js 16.4.0、React 19.3.0、TypeScript 6.0.3、Zod 4.6.5、Vitest 4.1.11，完整版本固定于 `package-lock.json`。TypeScript 7 与当前 Next.js ESLint 解析器不兼容。
- `.nvmrc` 固定本次验证环境 Node.js 26.3.1。启动与检查命令见根目录 `README.md`。
- 规范证据检索新增双 Provider 决策：Pinecone 与本地 RAG 必须返回相同的稳定证据字段；Pinecone 的 Embedding 模型仍需显式选择，本地 sidecar 和知识资产尚未合入。
