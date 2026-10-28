# ExcavaGuard Agent 协作规范

## 项目概述

ExcavaGuard 是面向基坑监测场景的 AI 监测日报智能体。系统读取监测数据和施工工况，通过确定性规则完成数值计算与阈值判断，通过 RAG 提供规范和案例证据，通过多 Agent 协作完成数据治理、辅助归因、报告生成与独立审计。

系统只生成供工程师复核的日报草稿，不替代工程师发布预警、审核或签发正式报告。

## 当前阶段

项目处于「**确定性计算层、日报三件套、三 Agent 主链与 Supabase 云端交付闭环已接通，
本地多用户项目权限已接通、企业身份与正式归档待建设**」的阶段。

### 已实现（截至 2026-10-14）

- `确定性计算层/`：三阶段流程 —— **阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对**；
- 阶段一：数据接入与归一化（单位按量纲换算、日期解析、来源标识）、14 类噪音与缺失识别（只识别不修改）；
- 阶段二：累计值 / 本次变化量 / 变化速率 / 最小二乘趋势斜率，输入不足时弃权并给出明确弃权码；
- 阶段三：默认规范库（`基坑智守项目相关规范`，30 本规范索引 + GB 50497-2019 条文级阈值）
  + 用户上传规范接口（字段级覆盖，**用户未上传时不作任何特殊处理**），五级风险分级；
- 多风险模拟数据集 `data_simulated/`（S1~S27，27 个场景，57 测点，3,420 条记录，100% 场景覆盖，
  覆盖《监测参数清单与规范依据》§一 全部 25 项参数中的可测项，与规范库 22 个监测项一一对应）；
- 补充参数剖析 `tools/analyze_supplementary_params.py`（温度 / 不排水抗剪强度 Cu / SPT 击数 / 分层测压管水头，只读）；
- **用户数据文件契约**（`contracts/monitoring_input.contract.json`）：必填 5 列
  （测点/时间/项目/数值/单位），`baseline_value` / `previous_value` / `interval_days`
  **由阶段一按测点时序确定性派生**（显式提供的值优先，派生打 `*_DERIVED` 标记）；
  通用读取器 `file_reader.py` 支持编码探测（utf-8-sig/utf-8/gb18030/gbk/big5/latin-1）、
  中英文列名别名（90 条监测项别名 + 25 条方向别名）、CSV/TSV/Excel；
- **最终混合宽表接入**：`file_reader.py` 可解析
  `监测项目-测点号-量值语义(单位)`，`normalize-monitoring-data` 已实现 Python 脚本与
  服务端 runner；已有累计量使用语义零基准，不按上传窗口重新归零；
  时序、质量和趋势统一按 `(point_id, metric_key)` 分组；宽表按报告日保留逐通道
  每日末值历史与日内统计，并透传时间对齐、重采样、插值和末值保持限制；
- 日报模块接口契约 `contracts/daily_report_input.schema.json`（`excavaguard.daily_report_input/v1`）
  + 校验工具 `tools/validate_daily_report_input.py`；
- **用户数据上传通道（⑤）**：存储层 `src/server/storage/`（local / Supabase 双 Provider，
  对象名由 `file_id` 生成）、
  `POST /api/monitoring-files`（含上传即解析报告）、`POST /api/standards`（**上传即校验严格程度**）、
  `POST /api/runs`（真实三阶段分析）、`GET /api/monitoring-files/sample`（示例数据）；
- **Node → Python 引擎桥接**：`src/server/skills/python-bridge.ts` + `skills/*/scripts/*.py`
  （`inspect_file.py` / `run_judgement.py` / `check_strictness.py`），子进程协议，零引擎改动；
- **可视化测试工作台** `/workbench`
  （见 `方案与迭代note/11_可视化测试指引.md`）；
- **规范 RAG 资产与离线原型**：`models/bge-small-zh/`（Git LFS）、`data/ocr_text/`（30 份文本）、
  `data/chunks.jsonl`（8,698 个唯一切片）与 `data/chroma_db/`
  （collection `jikeng_norms`，8,698 条 512 维 cosine 向量）已纳入仓库；
  `source/query_kb.py` 可使用本地 BGE + ChromaDB 离线检索；
- **规范证据双 Provider 适配器**：`src/server/evidence/` 已实现 Pinecone / 本地 loopback
  的公共查询契约与工厂；Pinecone 已改为 integrated embedding 文本检索，
  `retrieve-standard-evidence` runner 已实现查询校验、弃权、人工复核提示和轨迹；
- **本地 RAG HTTP 兼容链路**：`source/server.py` 已实现
  `POST /api/evidence/search`，复用可审计规范元数据并按候选 ID 先过滤后查询；
  BGE/Chroma 只使用 `var/rag/chroma_db/` 运行副本，已完成真实 Next.js
  Retriever/Skill 3 项验收；Python 接口回归 8 项通过；
- **Pinecone 可审计导入链路**：`tools/rag/` 可从现有切片生成 7,180 条候选记录，
  排除项目文件、无条文号/超长切片和重复 OCR 来源；`rag/standard-status.json`
  保存人工复核状态，存在 `unknown` 时禁止真实上传；
- **Pinecone 目标索引配置**：`excava-guard` 已创建并完成只读兼容性校验
  （AWS `us-east-1`、NVIDIA `llama-text-embed-v2`、语义字段 `text`）；
  29 个规范编号经团队人工复核后，`standards-v1` 已导入 7,180 records，
  真实语义查询返回 5 hits，文本和来源元数据与本地清单逐字段一致；
- **三 Agent 编排基础**：首版收敛为 Supervisor / 报告交付 / 独立审计；
  `src/contracts/agent-runtime.ts` 定义版本化快照、草稿、审计、预算与轨迹契约，
  `src/server/agents/supervisor.ts` 已实现确定性路由、最多两轮修订、能力缺失等待、
  上游变更导致下游失效及工程师接管；
- **日报三件套与逐单元格审计**：`render-daily-report` 只消费冻结载荷，生成
  `xlsx + 封面 Markdown + 附表及清单 Markdown`、事实/单元格绑定和文件哈希；
  `validate-report` 重新读取文件，核对哈希、Excel 单元格、Markdown、引用、章节和
  责任措辞。只生成实际出现的附表 A～F；缺巡视时省略 G 并明确不得判为巡视正常；
- **三 Agent 同步执行器与 API**：`src/server/agents/executor.ts` 已串联
  engineSnapshot → Supervisor → 报告 → 审计 → 人工复核，报告责任问题最多自动重渲染
  两轮；`POST /api/runs` 通过显式 `options.generate_report=true` 开启，
  审计通过后提供三件套只读下载地址。默认行为仍只返回确定性载荷；
- **AI 日报主链**：报告链默认使用 `report_mode=ai`。Supervisor 先调用 LLM 规划重点测项
  与规范检索主题，再调用 `retrieve-standard-evidence` 做运行时 RAG；报告交付 Agent
  调用 LLM 生成受约束正文，审计 Agent 在确定性文件审计通过后再调用独立 LLM 做语义审查。
  模型只能使用冻结事实占位符和本次证据 ID，不得改写风险等级或规范原文；缺少 LLM 配置、
  检索服务不可用、引用非法、模型输出越界或预算耗尽时停止完整 AI 交付并保留检查点。
- 引擎回归测试 **242 项全部通过**（`python -B pipeline/tests/test_pipeline_stages.py`）；
- **版本化交付闭环**：运行输入、冻结结果、逐步骤检查点、失败、人工接受/退回/拒绝
  按不可变 revision 保存，支持并发版本校验；
  `/workbench` 默认开启报告链，可查看历史、恢复输入、展示三 Agent 轨迹、下载三件套、
  提交复核并建立关联重跑。人工接受只表示草稿复核，不代表正式签发；
- **工程师风险评价闭环**：审计通过后，`admin / reviewer` 可对冻结载荷中
  「关注 / 预警 / 报警 / 危险报警」逐项记录确认、持续跟踪或异议及说明，再提交整份
  草稿复核。接受要求全部风险已评价且无异议；评价随不可变 revision 保存，不改写风险
  等级、规范依据或报告文件。「正常」与表示弃权的「未知」不进入该评价表；
- **登录与项目成员边界**：独立账号使用scrypt密码哈希与8小时HttpOnly签名会话，兼容原共享密码；
  登录后选择获授权工程，四类成员角色约束上传、生成、复核。同项目共享历史，跨项目拒绝访问；
  下载核验持久化审计清单与SHA-256。账号目录为私有本地文件，未使用Supabase Auth；
- **Supabase 应用 Provider**：项目 URL + publishable / secret key、迁移与私有 bucket 已验证；
  新式 `sb_secret_...` 配置契约、五张元数据表 + RLS + 私有 bucket 幂等迁移及无密钥
  回显的检查/写探针工具已准备；监测文件/用户规范上传、Python 安全临时物化、运行 revision
  CAS、审计后三件套上传、云端哈希下载与人工复核已接通，`.env.local` 已显式切至 supabase；
- 全栈检查 `npm run check` **141 项通过**（另有 4 个 live suite 的 6 项测试默认跳过：
  真实 LLM、local-RAG、Pinecone-RAG、Supabase live；
  含 8 项上传/纵向端到端 + 16 项 Agent Executor + 12 项持久化/访问边界
  + 10 项服务配置 + 7 项报告/审计 Skill），`npm run build` 13 条路由生成；
  运行目录、环境文件和临时验收文件已从部署依赖追踪中排除。
- `npm run supabase:test` **1 项真实纵向验收通过**：simulated 监测数据 + 用户规范上传、
  确定性分析、并发 revision 冲突、三件套私有下载、人工接受、对象篡改阻断和云端清理。
- `npm run rag:test` **1 项真实 Pinecone 纵向验收通过**：85 通道最终宽表 → AI 模式
  mock LLM 响应 → 真实 Pinecone RAG → Python 三件套 → 确定性审计；逐字段比对远端返回文本
  与 `var/rag/pinecone-records.jsonl` 本地清单，RAG 证据进入日报第四节。

### 尚未实现

- **异步编排**：已有文件检查点和原预算内显式续跑，无异步 worker 或自动恢复；
  计算未产出快照、活动任务或预算到期时需要加载输入新建关联运行；
- **企业身份**：本地账号及项目成员权限已实现；Supabase Auth / 企业SSO尚未实现。
  服务端secret绕过RLS，因此现有身份、项目和角色访问校验不可删除；
- **既有本地资产迁移**：Provider 切换只影响新写入；`var/` 中已有本地测试历史保留，
  尚未自动复制或删除；
- 八个业务 Skill 中仍有两个只有 `SKILL.md` 契约：
  `retrieve-similar-cases` / `analyze-work-condition`。
  已实现的六个是 `parse-monitoring-data`、`normalize-monitoring-data`、`evaluate-thresholds`、
  `retrieve-standard-evidence`、`render-daily-report` 与 `validate-report`；
- **温度补偿**未实现，轴力类判据可能混入温度效应（P2-1）；
- **正式工程归档**：本地复核和三件套下载已接通，尚无正式签发与工程档案系统；
- 部署与 CI；
- **真实 LLM 质量验收**：OpenAI-compatible 适配器和三角色调用链已实现，但当前
  `.env.local` 缺 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`，因此真实模型日报质量
  尚未验收；`npm run ai:test` 需配置后显式运行。
- **正式报告引用准确率评测**：RAG 已接入 AI 日报主链并通过真实 Pinecone 纵向验收，
  但尚未做成体系的工程场景引用准确率评测。
- **最终输入兼容性**：`final_test/监测数据整合_7天_10分钟.xlsx` 的 85 通道混合宽表
  已通过真实上传和 `/api/runs` 验收（85,680 条源记录；报告日 `2026-10-08`
  聚合为 340 条计算历史，日报载荷只交付当日 85 条），并通过三 Agent 三件套生成、
  A～F 表式、无 G 行为、审计及下载验收，见 `final_test/README.md`。

> **已修复（原 P0-1）**：用户上传原始观测表不再 100% 弃权。
> 2026-10-10 实测：仅含 5 个必填列的 7 期数据 → 弃权 1/7，正确识别出 6 期危险报警。
>
> **已实现（原 P1-1）**：用户阈值宽松度校验 —— `limit_strictness.py`，
> 在 `upload_standard()` / `resolve_limit()` / `build_daily_report_input()` 三处接入，
> 检出更宽松时反馈具体差异并注明默认值的规范名称与条文号（**只反馈、不阻断**）。
> 载荷新增 `standard_override_warnings` 字段。
>
> **已修复（原 P1-2）**：缺 `excavation_depth_m` 时**不得**用绝对量限值替代 `min(绝对量, %H)`。
> 现改为：绝对量只作**上界**，实测值未超上界 → 弃权（`MISSING_H`）并降级为「未知」；
> 已超上界 → 超限结论必然成立，照常判定。`MISSING_H` 不再是死代码。
>
> **已验证（④）**：引擎与 Web 入口可打通 —— `skills/evaluate-thresholds/scripts/run_judgement.py`
> + `tools/bridge-smoke/`，Node 子进程调用 Python，13/13 通过
> （见 `方案与迭代note/10_开发推进记录.md`）。

任何 Agent 都不得把规划中的技术选型描述为已经实现，也不得把已实现的能力描述为尚未实现。

## 权威文档

开始工作前按以下顺序读取：

1. `AGENTS.md`：全局协作规则和安全边界；
2. `memory.md`：当前稳定决策、项目状态与待确认事项；
3. `确定性计算层_监测参数清单与规范依据.md`：参数清单、计算公式与规范依据（**参数查漏后的最新版**）；
4. `确定性计算层/02_三阶段流程与规范比对说明.md`：三阶段流程与判据细则；
5. `确定性计算层/04_日报模块接口契约.md`：日报交接契约（已冻结）；
6. `确定性计算层/05_参数查漏与补充分析.md`：参数查漏结论与补充参数画像；
7. `确定性计算层/06_上传数据到风险识别链路_目标实现度评估.md`：**目标实现度、关键差距与风险点**；
8. `方案与迭代note/08_阈值口径统一说明.md`：阈值来源的**唯一权威口径**与远程同步方案；
9. `确定性计算层/09_用户数据文件契约.md`：用户数据文件契约（列名/编码/派生规则）；
10. `方案与迭代note/10_开发推进记录.md`：①~⑤ 开发进度、P1-2 修复、交付物与待决事项；
11. `方案与迭代note/11_可视化测试指引.md`：**端到端可视化验证的操作手册**（启动、四步操作、三个验证点）；
12. `方案与迭代note/07_远程仓库对比与两项可行性分析.md`：本地与远程仓库的差异、打通路径与风险；
13. `方案与迭代note/初步方案.md`：业务目标和初步技术判断；
14. `方案与迭代note/框架demo.md`：Skill 编排和多 Agent 设计；
15. `skills/README.md`：Skill 目录约定；
16. 目标 Skill 下的 `SKILL.md`：具体能力契约。

当文档发生冲突时，以工程师最新明确确认的内容为准，并同步修正文档，禁止私自选择对实现最方便的解释。

## 项目结构

```text
ExcavaGuard/
├── AGENTS.md / memory.md                  全局规则与项目记忆
├── src/                             ← Next.js 16 全栈工程（2026-10-10 从远程合并）
│   ├── app/
│   │   ├── page.tsx                       日报工作台首页
│   │   ├── workbench/                     ← 可视化测试工作台（page + client）
│   │   └── api/
│   │       ├── health/route.ts            存活检查
│   │       ├── monitoring-files/route.ts  GET 列表 / POST 上传监测数据
│   │       ├── monitoring-files/sample/   示例数据 CSV
│   │       ├── standards/route.ts         GET 列表 / POST 上传用户规范（含严格度校验）
│   │       ├── runs/                      创建/历史/详情/复核/显式续跑
│   │       ├── session/                   独立账号/兼容密码会话
│   │       ├── projects/                  获授权工程列表、创建与选择
│   │       └── report-artifacts/          审计通过的三件套只读下载
│   ├── components/                        服务端界面组件
│   ├── contracts/                         Zod 请求契约（含 monitoring-files.ts）
│   └── server/
│       ├── api/respond.ts                 统一错误响应与异常映射
│       ├── storage/                       local / Supabase 文件、运行和报告 Provider
│       ├── skills/python-bridge.ts        Node → Python 子进程桥接
│       ├── skills/{parse-monitoring-data,evaluate-thresholds}/runner.ts
│       ├── skills/retrieve-standard-evidence/runner.ts
│       ├── skills/{render-daily-report,validate-report}/runner.ts
│       ├── agents/                        三 Agent 注册 + Supervisor + 同步执行器
│       ├── evidence/                      规范证据检索（双 Provider 适配器）
│       └── config.ts / integrations/      环境配置与外部客户端
├── tests/                                 Vitest（141 项通过，6 项 live 默认跳过）
├── package.json / tsconfig.json / next.config.ts / vitest.config.ts / eslint.config.mjs
├── .env.example / .nvmrc / .gitignore
├── README.md / 项目介绍.html
├── var/
│   ├── uploads/                           上传文件存储（已 gitignore）
│   ├── runs/                              运行和复核不可变修订（已 gitignore）
│   └── report-artifacts/                  日报三件套运行产物（已 gitignore）
├── 确定性计算层/                    ← 已实现：三阶段确定性流程
│   ├── 01_数据清单与可用性评估.md
│   ├── 02_三阶段流程与规范比对说明.md
│   ├── 03_本次新增文件清单.md
│   ├── 04_日报模块接口契约.md
│   ├── 05_参数查漏与补充分析.md
│   ├── 06_上传数据到风险识别链路_目标实现度评估.md
│   ├── 09_用户数据文件契约.md
│   ├── pipeline/
│   │   ├── stage1_data_preparation/      阶段一 · 数据准备（含 file_reader.py）
│   │   ├── stage2_deterministic_calc/    阶段二 · 确定性计算
│   │   ├── stage3_standard_comparison/   阶段三 · 规范比对（含 limit_strictness.py）
│   │   ├── orchestrator.py               三阶段编排 + 日报接口
│   │   └── tests/                        242 项回归测试
│   ├── contracts/                        日报接口契约 + 用户数据文件契约
│   ├── standards/
│   │   ├── default/                      默认规范库（基坑智守项目相关规范，22 项监测项）
│   │   └── user_uploaded/                用户上传规范（默认空，不作提示）
│   ├── data_simulated/                   模拟数据集（与原始数据隔离）
│   ├── tools/                            只读分析与生成脚本（12 个）
│   ├── derived/                          派生结果
│   └── legacy/                           已废弃的旧阶段语义实现（留档）
├── 数据资产/                        ← **仅本地**（已 gitignore）：模拟数据快照 + 原始数据只读备份
├── tools/
│   ├── bridge-smoke/                     ← 引擎桥接冒烟测试（Node → Python，13 项）
│   └── rag/                              ← Pinecone 导入清单、门禁与批量上传工具
├── 确定性计算层_监测参数清单与规范依据.md
├── 方案与迭代note/
│   ├── 初步方案.md
│   ├── 框架demo.md
│   ├── 链路口语化.md
│   ├── 07_远程仓库对比与两项可行性分析.md
│   ├── 08_阈值口径统一说明.md
│   ├── 10_开发推进记录.md
│   └── 11_可视化测试指引.md
├── skills/
│   ├── README.md
│   ├── parse-monitoring-data/
│   │   └── scripts/inspect_file.py       ← 解析检查桥接脚本
│   ├── normalize-monitoring-data/scripts/normalize_records.py
│   ├── evaluate-thresholds/
│   │   └── scripts/                      ← run_judgement.py / check_strictness.py
│   ├── retrieve-standard-evidence/
│   ├── retrieve-similar-cases/
│   ├── analyze-work-condition/
│   ├── render-daily-report/scripts/       ← 草稿 + 三件套确定性渲染
│   ├── validate-report/scripts/           ← 事实、引用与文件审计
│   ├── deep-pit-monitoring-report/        ← 日报表式与实现参考资产
│   └── _archive/prototypes/               ← 非主链团队原型留档
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

规范判据的优先级高于案例经验。历史案例只能辅助解释原因，不能改变超限事实或降低风险等级。

## Agent 设计

首版收敛为三个逻辑 Agent：

- `Supervisor Agent`：任务规划、Agent 路由、共享状态管理、冲突处理和终止控制；
- `报告交付 Agent`：调用报告生成 Skill，只使用结构化事实生成草稿；
- `审计 Agent`：调用报告校验 Skill，从反方检查数字、引用、适用性和责任边界。

数据解析、确定性判定、规范/案例检索与工况分析属于 Skill / 服务能力，由 Supervisor
按状态调用，不再为每项能力设置独立 Agent。审计 Agent 发现报告责任问题后可退回
报告交付 Agent，发现上游事实或证据问题时交给 Supervisor 停止自动修订并转工程师；
审计不得直接修改源事实。自动修订最多两轮，达到次数、时间或调用预算后转人工接管。

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

> **范围说明**：规范 RAG 资产与离线检索原型已存在，下一阶段建设统一证据接口与业务 Skill。
> 确定性计算层仍不做 RAG，阶段三的规范比对直接读取默认规范库的条文级阈值文件；
> RAG 只负责提供可追溯证据，不得参与或改写风险判定。

- 规范知识必须保存规范名称、版本、条文号、原文、适用条件和来源位置。
- 案例知识必须保存工程特征、来源、可信等级、相似条件和差异项。
- 检索优先使用元数据过滤，再组合关键词检索和向量检索。
- 检索结果必须携带稳定的证据 ID。
- 不得伪造条文、页码、规范版本、案例来源或匹配分数。
- 未检索到证据时返回“信息不足”，不能依靠模型常识补造。
- 规范全文和工程案例进入仓库前，必须确认授权和脱敏要求。

## 工程安全边界

以下规则不可绕过：

- 阈值判据必须来自**现行规范条文**，并标注规范名称、版本、条文号与出处位置。
  禁止使用无出处的经验数字，禁止伪造条文。
- 规范条文阈值在用于真实工程前，**必须由基坑工程设计方确认**；
  GB 50497-2019 第 8.0.1 条明确「监测预警值应由基坑工程设计方确定」。
  用户上传的地方规程 / 项目专项方案按字段覆盖默认规范库，未覆盖字段继承默认库。
- 用户未上传规范时**不作任何特殊处理**：不报错、不告警、不提示缺失，直接使用默认规范库。
- **用户上传规范的严格度不得低于默认规范库**：若用户阈值宽于默认值，必须在结果中显著提示
  （flag `USER_LIMIT_LOOSER_THAN_DEFAULT`），不得静默采用而放宽判据。
  已实现：`limit_strictness.py`，在 `upload_standard()`（上传即反馈）、
  `resolve_limit()`（判定兜底）、`build_daily_report_input()`（载荷 `standard_override_warnings`）
  三处接入，**只反馈、不阻断**。
- **缺少基坑设计深度 H 时，不得用「绝对量限值」替代「min(绝对量, %H)」限值**。
  GB 50497-2019 表 8.0.4 规定累计值取两者较小值。已实现：缺 H 时绝对量只作**上界**，
  实测值未超上界 → 弃权（`MISSING_H`）且不得判为「正常」；
  已超上界 → 超限结论必然成立，照常判定。
- 模拟数据必须带 `data_origin = "simulated"` 标识、文件名含 `SIMULATED`、
  保留 `source_dataset` 溯源字段，写入独立目录，且与真实数据**分开统计**。
- 高严重度数据质量问题（孤立尖峰粗差、非数值、日期不可解析、单位不可识别、传感器漂移）
  的期次**不得参与风险判定**，一律弃权并转人工复核，禁止"带病判定"。
- 不自动修复未知单位、方向、测点映射或缺失字段。
- **上传文件的落盘名一律由 `file_id` 生成**，不使用用户提供的文件名（防路径穿越）；
  原始文件名只作元数据展示。存储 provider 未真正实现时**必须显式报错**，
  不得提供"看起来能跑"的空壳。
- 确定性计算层**只产出结构化载荷**（日报 `excavaguard.daily_report_input/v1` 或周期 `excavaguard.period_report_input/v1`），
  不生成日报正文与版式文件、不撰写结论与建议措辞；日报由后续独立 Agent 负责。
  载荷中 `risk_level = "未知"` 表示弃权，**不是"安全"**，必须转人工复核，禁止渲染为正常项。
- **引擎判定逻辑不得用 TypeScript 重写**。判定已有 242 项回归测试覆盖，
  二次实现会给「同一输入必得同一输出」这条确定性性质引入偏差；
  Web 侧只做协议转换（子进程调用 `skills/*/scripts/*.py`）。
- 不使用案例相似性证明因果关系。
- 不自动发布黄色、橙色或红色预警。
- 不生成自动签字、自动审核或已正式签发的表述。
- 不隐藏规范冲突、数据缺口、低可信结果或异常执行记录。
- 关键校验失败时停止输出报告成品，只返回错误和待确认项。

## 修改方式

- 优先做范围清晰的小改动，避免在一次任务中同时重构目录、契约和业务逻辑。
- 开始实现前先读取目标 Skill 的 `SKILL.md`。
- 新增顶层 Agent、Skill、RAG 数据集或共享状态字段时，先更新设计文档。
- 不在未确认技术栈前创建大型脚手架或引入生产依赖。
- 不修改原始规范和案例文件；清洗结果、索引和派生数据应存放在独立目录。
- 不提交密钥、访问令牌、个人信息或未经脱敏的工程数据。
- 不删除方案、证据或测试资产，除非用户明确要求。

## 环境初始化与依赖

- Node 依赖使用 `npm ci`，不得手工修改 `node_modules/`。
- Python 依赖安装在仓库内 `.venv/`，不要写入系统或 Conda base 环境。
- macOS 首次使用先安装 Git LFS。当前开发机配置了全局 `core.hooksPath`，
  `git lfs install` 会与已有 `pre-push` hook 冲突；不得使用 `--force` 覆盖，
  应使用 `git lfs install --skip-repo` 后再拉取和校验 LFS 对象。
- `models/bge-small-zh/pytorch_model.bin` 的实际大小应为 `95,842,633` 字节；
  只有约 130 字节时仍是 LFS 指针，不能启动离线检索。
- `data/chroma_db/` 是版本化发布基线，不得提交运行产生的锁记录或迁移结果。
  Chroma `PersistentClient` 会写入 `acquire_write`；正式接入时必须先复制到
  `var/rag/chroma_db/` 等 gitignore 运行目录，再由服务读取运行时副本。

```bash
# --- Git LFS（macOS）---
brew install git-lfs
git lfs install --skip-repo
git lfs pull
git lfs fsck
test "$(wc -c < models/bge-small-zh/pytorch_model.bin)" -eq 95842633

# --- Python / RAG ---
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

2026-10-12 已在 macOS arm64、Python 3.13.13 验证：
`chromadb 1.5.9`、`sentence-transformers 6.1.0`、`torch 2.14.1`、
`fastapi 0.143.0` 可读取现有 8,698 条 Chroma 向量并完成离线查询。

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

### 已验证的命令（更新至 2026-10-14）

```bash
# --- 引擎（纯标准库 Python，无第三方依赖）---
cd 确定性计算层
python -B pipeline/tests/test_pipeline_stages.py                                # 242 项
python -B tools/run_simulated_validation.py                                     # 场景 27/27
python -B tools/run_combined_real_and_simulated.py                              # 真实 + 模拟合并
python -B tools/export_input_contract.py                                        # 导出数据契约
python -B tools/validate_daily_report_input.py --self-test                      # 日报契约校验
python -B legacy/thresholds_v1_阶段语义废弃/tests/test_threshold_loader.py       # 留档 57 项

# --- 桥接（纯 Node，无依赖）---
cd ..
node tools/bridge-smoke/run_judgement.mjs                                       # 13 项

# --- Web 全栈 ---
npm ci
npm run check                                                                   # 141 项通过，6 项 live 默认跳过
npm run build                                                                   # 13 条路由；运行数据不打包
npm run dev                                                                     # http://localhost:3000/workbench
npm run supabase:verify                                                         # 基础设施真实写探针
npm run supabase:test                                                           # 应用 Provider 真实纵向验收
npm run rag:test                                                                # 真实 Pinecone + 最终宽表 + 三件套验收
npm run ai:test                                                                 # 需配置 LLM 三项；真实 LLM + RAG 验收

# --- 在线 RAG 导入准备（只读源资产，不访问云端）---
npm run rag:prepare                                                             # 7,180 条已复核候选
npm run rag:import                                                              # 幂等导入 Pinecone standards-v1

# --- 本地 RAG 接口（模型预加载，运行副本，不修改发布基线）---
.venv/bin/python -B source/server.py --port 8600
.venv/bin/python -B -m unittest discover -s source/tests -v                      # 8 项接口回归
EXCAVAGUARD_TEST_LOCAL_RAG=1 npx vitest run tests/local-rag-live.test.ts           # 服务启动后 3 项真实验收

# --- RAG 依赖与发布基线检查 ---
.venv/bin/python -m pip check
sqlite3 data/chroma_db/chroma.sqlite3 "SELECT COUNT(*) FROM embeddings;"         # 8698
```

`npm run check` 中的 `tests/upload-and-run.test.ts` 需要 Python；
找不到解释器时该 suite **自动跳过**，其余用例不受影响。

## 完成标准

一项修改只有在以下条件满足后才算完成：

- 改动符合目标 Skill 的职责边界；
- 输入输出契约同步更新；
- 对应测试或测试样例已经补充；
- 没有引入未经确认的工程事实；
- 错误、弃权和人工确认路径均有定义；
- 相关方案文档和 `memory.md` 已按需更新；
- 最终回复准确说明已完成内容、未完成内容和验证结果。

## 多周期报告维护约束（2026-10-27）

- 日报请求保持兼容；周报、自然月、自定义使用独立 `period_report_input/v1`，不得修改冻结日报 schema。
- 统计由 Python `pipeline/period_reports.py` 生成并重建校验；保留区间前历史，排除未来记录，最严重原观测与期末值不得混称。未知、缺测与日内峰值限制必须披露。
- 多日预警按同点同测项不同日期去重，至少两日触发 AI 模式追加规范检索；只扩展当前知识库内的现行候选，不自动改变阈值，不声称全网最新法规已核实。
- 测试：`npm run test:period`（Node24 或支持 registerHooks 的版本，Python 需 openpyxl）及 `python -B 确定性计算层/pipeline/tests/test_period_reports.py`。具体环境与本次结果见 `方案与迭代note/14_多周期报告使用与验收.md`。

## 全规范检索与人可读引用（2026-10-27，service-v5）

- AI检索由程序覆盖默认索引与效力清单中的全部唯一规范编号（当前29本），然后逐实际测项跨规范检索。不得重新硬编码仅允许GB50497-2019，也不得依赖模型只选择少数书目。
- 强制保留逐规范覆盖、无命中/效力待核及候选预算截断说明；相关候选不是已确认适用条文，不替换确定性判据。
- 用户可见的总表、附表、索引及轨迹使用规范名称/编号/条文；内部ID和哈希保留作机器追溯，不能以书名替换主键。
- 新增回归 `npm run test:standards`；真实Pinecone和模型验收分别显式开启，不把模拟响应当线上验收。实际结果见 `方案与迭代note/16_全规范检索与引用验收.md`。

## 性能与模型响应维护（2026-10-27）

- 规范查询默认8路滚动并发，所有进度/检查点回调串行；故障停止新排队并等待已发请求结束。保留全部目录覆盖和证据校验。
- 非法审计JSON/缺字段不能静默转换为空问题列表；安全错误分类和失败轨迹不得包含API原始响应、请求头或密钥。
- 语义审查完整模型自写段落及其引用、关联测点和周期上下文；程序生成的统计/索引/文件由确定性审计完整核对，不能以性能为由省略。性能结果和复测见17号说明。

## 项目补充规范维护（2026-10-27）

- 全文规范走 `project-standard-library` 和 `/api/project-standards`，原JSON阈值入口保持兼容。仅服务端当前project_id选择/启停/检索，禁止写入公共Pinecone/Chroma或默认判据。
- 原文件BLOB、切片、FTS5索引在独立项目SQLite库；按ID与哈希冻结到运行，禁用不删除历史，续跑不重新读取当前启用列表。同编号每项目只启用一个来源。
- 字体乱码/扫描PDF没有可靠文字层时拒绝并提示OCR，不把空索引当作成功。模型必须引用各份已命中的项目文档；候选适用性、实际执行和数值差异由工程师确认。
- 验证：`npm run test:project-standards`；真实PDF通过 `EXCAVAGUARD_TEST_STANDARD_PDF` 显式提供。真实模型只用公开标准与合成观测，详见18号说明。
