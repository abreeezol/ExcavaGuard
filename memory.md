# ExcavaGuard 项目记忆

> 本文件保存经过确认、需要跨任务延续的项目信息。临时执行日志、未经验证的猜测、密钥和原始敏感数据不得写入。

## 项目目标

ExcavaGuard 面向基坑监测工程师，将当日监测数据和施工工况整理为可复核、可追溯的监测日报草稿，并对异常条目提供受约束的辅助归因。

系统不替代工程师承担安全判断、预警发布、审核和签发责任。

## 当前状态

更新时间：2026-09-22

- 项目根目录已经建立。
- `方案与迭代note/初步方案.md` 已记录项目定位、总体架构、MVP 和评测方向。
- `方案与迭代note/框架demo.md` 已记录 Skill 编排、多 Agent 设计、共享状态和审计回路。
- `skills/` 已建立八个业务 Skill 的目录和 `SKILL.md`。
- 每个 Skill 已预留 `references/`、`scripts/`、`skills/` 和 `tests/`。
- `skills/.agents/` 已建立编排层说明。
- `rag/` 当前只有设计占位说明，尚未导入知识资产。
- 当前没有可执行的业务代码、前端应用、模型服务或正式测试集。
- 本地项目已初始化 Git 仓库，当前分支为 `main`，远程 `origin` 指向 `https://github.com/abreeezol/ExcavaGuard.git`。远程仓库已完成首次推送，`main` 分支已创建，远程 `HEAD` 指向 `main`。

## 已确认架构

采用以下组合：

> 多 Agent 协作 + Skill 工具层 + 双知识库 RAG + 确定性规则引擎 + 工程师签发

职责分配：

- Agent：任务理解、动态规划、路由、冲突处理和结果组织；
- Skill：执行可测试、可复现的具体业务能力；
- RAG：提供规范和历史案例证据；
- 规则引擎：完成数值计算与阈值判断；
- LLM：生成受约束的解释和报告语言；
- 工程师：确认关键配置、处理冲突并最终签发。

## Agent 组成

- `Supervisor Agent`
- `数据治理 Agent`
- `判据与规范 Agent`
- `风险归因 Agent`
- `报告交付 Agent`
- `审计 Agent`

Supervisor 是唯一总控角色。专业 Agent 不能绕过 Supervisor 改变流程状态，审计 Agent 不能直接修改源事实。

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

- 最终开发语言和前后端框架；
- 多 Agent 编排框架；
- 使用本地模型还是远程模型；
- Embedding 与 rerank 模型；
- FAISS、Qdrant 或其他向量存储；
- 规范和案例资料的具体来源与授权方式；
- 项目专项方案与通用规范的优先级配置方式；
- 真实输入文件格式和字段名称；
- 日报模板的最终版本；
- 是否必须完全离线运行；
- Demo 的部署与打包形式。

## 待推进事项

1. 确认最小输入数据契约。
2. 确认项目阈值和规范适用规则。
3. 为八个 Skill 补充 references、scripts 和 tests。
4. 定义共享工程状态 Schema。
5. 定义 Supervisor 的路由、重试和终止规则。
6. 建设最小规范知识库。
7. 建设经过脱敏的案例知识库。
8. 跑通正常、超限、数据错误和证据不足四类流程。
9. 增加审计 Agent 的退回机制。
10. 开发可视化 Demo 和日报导出能力。

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
