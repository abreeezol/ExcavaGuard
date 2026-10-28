# ExcavaGuard 项目记忆

### 2026-10-27 登录与授权项目切换

- 新增本地独立账号、获授权工程选择、系统管理员创建工程和admin/reviewer/engineer/viewer角色；兼容原共享密码/localhost模式，未自动初始化真实账号。
- CLI `tools/access/manage.mjs` 管理账号及授权；私有 `var/access/directory.json` 包含scrypt哈希和签名材料，初始凭据文件0600，均忽略Git。初始化保留既有项目授权及UUID，账号改密/停用和撤销授权影响后续请求。
- 项目会话决定文件、规范和运行的归属；前端切换卸载旧工作台、重载当前工程资产，附带期望工程头以拒绝旧标签页操作。同项目不同账号共享历史，复核人单独记录，创建人不被覆盖。
- 尚无Supabase Auth/SSO、多文件汇总或完整上传者来源审计；单服务私有授权目录须持久化备份。详见20号说明。未自动提交推送。

### 2026-10-27 速度与审查稳定性优化

- 用户继续授权性能优化。规范检索由4路批次改成8路滚动线程，进度和检查点串行；停止新排队、排空在途请求的失败保护不变。
- 修复审计非法响应默认空列表的隐患；给出完整审计输出结构，增加无密钥/响应正文的错误分类及失败轨迹。
- 语义审查只看完整模型段落，保留关联点完整风险与弃权、相关周期行及整体缺测信息，并区分数值规则来源与RAG引用；确定性审计仍完整读取全部文件。
- 纯手工85通道日报最终实测24.67秒，检索6.42秒、36次请求、29本覆盖、3次真实DeepSeek调用、0轮修订，真实语义审查通过；另一次通过用时41.51秒且1轮有效修订。非时延保证，不含上传和云存储。
- Windows Vitest126通过/6个live跳过；多规范原生15通过，多周期原生13通过。记录见17_检索并发与模型稳定性优化.md。未自动推送。

### 2026-10-27 全规范检索与可读引用（service-v5）

- 用户要求扩大三Agent运行时RAG检索，并将总表/附表证据索引显示为规范名称。
- 根因是普通主题检索和返回过滤均锁定GB50497-2019；改为29个规范编号逐本查询+全部测项跨规范主题查询，4路并发，主候选按规范轮转最多96条，多日预警追加保留。
- 证据快照新增coverage和comparisons，披露无命中、效力及截断；未命中不能宣称无要求，检索不改变数值判据。
- 正文、附表页脚/备注、超限表、周期明细及前端显示名称+编号+条文；内部ID/哈希仍保留。新增规范证据索引、检索覆盖、要求对照三张表，模板v5，旧文件不改写。
- 用既有85通道数据完成离线日报/周报与篡改审计；真实Pinecone逐本查询29本，命中26本84条候选，原文和元数据与源资产核对。85通道真实模型外传未获明确授权；已改用手写8条纯模拟观测完成DeepSeek三角色真实调用及语义审查（3次调用、0轮修订）。
- Windows完整Vitest122通过、6个live默认跳过；修复映射盘符下载误判和换行测试兼容。语义审查仅接收已写正文及对应引用，确定性审计完整核对所有表格。
- 复现命令及当前验证结果见 `方案与迭代note/16_全规范检索与引用验收.md`。

### 2026-10-27 多周期报告

- 用户授权实现日报、连续7日周报、自然月报、自定义区间（含首尾1～366天），不涉及多用户。
- 新增周期独立契约、Python 确定性区间统计、缺测/未知披露、三张周期明细表；原日报兼容。必要历史保留、未来截断、不重新归零，附表为最严重原观测而非期末值。
- AI 模式沿用原检索后对同点同测项至少两日预警追加跨规范查证；只核查已配置知识库的现行候选，无命中不能证明无要求，工程师确认适用性，不改风险判据。
- 前端选择周期，历史恢复区间；API、三件套、文件审计、下载、人工复核接通。四份业务 Skill 和设计同步更新，说明见 `方案与迭代note/14_多周期报告使用与验收.md`。
- 当前 WSL 依赖为 Windows 安装的 node_modules，原 Vitest 缺 Linux 原生绑定；新增原生 Node 测试入口使用真实应用模块、Python、导出和审计，外部模型/检索为明确 SIMULATED 响应，不能当作线上服务验收。

> 本文件保存经过确认、需要跨任务延续的项目信息。临时执行日志、未经验证的猜测、密钥和原始敏感数据不得写入。

## 项目目标

ExcavaGuard 面向基坑监测工程师，将当日监测数据和施工工况整理为可复核、可追溯的监测日报草稿，并对异常条目提供受约束的辅助归因。

系统不替代工程师承担安全判断、预警发布、审核和签发责任。

## 当前状态

更新时间：2026-10-14

### 框架层（2026-09-22 建立）

- 项目根目录已经建立。
- `方案与迭代note/初步方案.md` 已记录项目定位、总体架构、MVP 和评测方向。
- `方案与迭代note/框架demo.md` 已记录 Skill 编排、多 Agent 设计、共享状态和审计回路。
- `skills/` 已建立八个业务 Skill 的目录和 `SKILL.md`。
- Skill 目录已清理：根 `skills/` 第一层只保留 8 个 canonical 业务 Skill、
  `deep-pit-monitoring-report` 参考资产与 `_archive/`；原编排说明合并进
  `skills/README.md`。
- 本地项目已初始化 Git 仓库，当前分支为 `main`，远程 `origin` 指向 `https://github.com/abreeezol/ExcavaGuard.git`。
- 八个 Skill 中已有六个具备可调用实现：`parse-monitoring-data`、
  `normalize-monitoring-data`、`evaluate-thresholds`、`retrieve-standard-evidence`、
  `render-daily-report`、`validate-report`；其余两个仍只有 `SKILL.md` 契约。

### 确定性计算层（2026-10-09 落地）

- **阶段语义（唯一口径）**：
  - 阶段一 **数据准备** —— 用户上传数据与模拟数据统一作为风险识别参数的输入依据；
  - 阶段二 **确定性计算** —— 累计值 / 本次变化量 / 变化速率 / 趋势斜率；
  - 阶段三 **规范比对** —— 与规范判据比对，识别风险并分级。
  三个阶段是**流程先后关系**，不是「通用方案进阶到专项方案」的递进关系。
- 代码：`确定性计算层/pipeline/`（`stage1_data_preparation` / `stage2_deterministic_calc` /
  `stage3_standard_comparison` / `orchestrator.py`），回归测试 **242 项全部通过**。
- 规范库：`确定性计算层/standards/default/`（`规范库索引.json` 30 本规范 +
  `thresholds_gb50497_2019.json` 条文级阈值，**22 项监测项**）；`standards/user_uploaded/` 用户上传目录
  （默认空，**未上传时不作任何特殊处理**）。
- 模拟数据：`确定性计算层/data_simulated/`（S1~S27，27 个场景，57 测点，3,420 条记录，
  场景覆盖率 100%），与原始数据、`derived/` 完全隔离；覆盖参数清单全部 20 个可测参数，
  与规范库 22 个监测项一一对应。
- 真实数据验证：`tools/run_real_data_demo.py`（2,868 条隧道观测）与
  `tools/run_combined_real_and_simulated.py`（真实 + 模拟合并，按来源分开统计）。
- **日报接口契约（已冻结）**：`contracts/daily_report_input.schema.json`
  （`excavaguard.daily_report_input/v1`，JSON Schema 2020-12，字段只增不改）
  + 校验工具 `tools/validate_daily_report_input.py` + 说明 `04_日报模块接口契约.md`。
  载荷顶层 13 键，含 `items` / `alerts` / `review_queue` / `summary` / `data_quality`
  与 `project`（工程概况，调用方注入，未提供则 `null`，不臆造）。
  **本层只产出载荷，不生成日报正文与版式文件**；日报由后续独立 Agent 实现。
  A/B/C 三组实跑载荷均已通过契约校验，落盘 `derived/日报接口载荷_*.json`。
- 旧实现（按阈值来源分层的语义）已移入 `确定性计算层/legacy/` 留档，其 57 项测试仍可通过。
- 规范 RAG：本地 BGE + ChromaDB 原型与知识资产已进入仓库。`data/ocr_text/` 含 30 份文本，
  `data/chunks.jsonl` 含 8,698 个唯一切片，collection `jikeng_norms` 含 8,698 条
  512 维 cosine 向量；`models/bge-small-zh/pytorch_model.bin` 通过 Git LFS 分发。
- 双 Provider 适配器与 `retrieve-standard-evidence` runner 已接通；Pinecone 使用
  integrated embedding 文本检索，runner 负责查询校验、弃权、人工复核提示和轨迹。
  `tools/rag/` dry-run 从现有资产生成 7,180 条候选记录，来源映射零遗漏、ID 零冲突。
  目标索引 `excava-guard` 已完成连接和只读兼容性校验（AWS `us-east-1`、
  NVIDIA `llama-text-embed-v2`、语义字段 `text`）。29 个规范编号经团队人工复核后，
  `standards-v1` 已导入 7,180 records；真实语义查询返回 5 hits，正文与来源元数据
  和本地清单逐字段一致。本地 FastAPI 已实现统一 `POST /api/evidence/search`，
  使用可审计规范元数据、BGE 与 Chroma 运行副本，真实 Next.js Retriever/Skill 3 项验收通过。

### Web 入口层（2026-10-10 接通）

- **存储**：`src/server/storage/` 已实现 local / Supabase 双 Provider；
  `.env.local` 当前显式使用 Supabase。对象路径**一律由 project_id / kind / file_id /
  服务端固定名生成**，不用用户文件名；扩展名白名单 + 20 MB 上限 + SHA-256 指纹。
  Python 使用随机临时目录读取云端文件并在调用后清理。
- **引擎桥接**：`src/server/skills/python-bridge.ts` —— Node 子进程调用
  `skills/*/scripts/*.py`（stdin/stdout JSON）。**判定逻辑不重写为 TypeScript**。
  桥接脚本：`parse-monitoring-data/scripts/inspect_file.py`、
  `normalize-monitoring-data/scripts/normalize_records.py`、
  `evaluate-thresholds/scripts/{run_judgement,check_strictness}.py`。
- **API**：`GET/POST /api/monitoring-files`（上传即返回解析报告）、
  `GET /api/monitoring-files/sample`（示例数据 CSV）、
  `GET/POST /api/standards`（**上传即校验严格程度**）、`POST /api/runs`（真实三阶段；
  `options.generate_report=true` 时继续同步报告/审计）、
  `GET /api/report-artifacts/<draft_id>/<file_name>`（三件套只读下载）。
- **可视化测试工作台** `/workbench`：四步操作（工程条件 → 上传数据 → 用户规范 → 运行分析），
  右栏展示总览 / 风险分布 / 宽松告警 / 报警清单 / 待复核 / 逐测点明细 / 原始载荷。
  **页面不做任何判定**，只展示引擎结果。操作手册见
  `方案与迭代note/11_可视化测试指引.md`。
- **本地交付闭环（2026-10-14）**：输入、冻结结果、逐步检查点、失败和人工决定
  落在 `var/runs/<run_id>/<revision>.json`；原子追加修订和并发版本校验
  防止覆盖。历史/详情/复核/显式续跑 API 与工作台已接通。
- **访问边界**：单操作者单项目；开发期绑定 localhost 并拒绝跨站请求，
  可选密码 HttpOnly 会话，生产缺访问配置则拒绝业务接口。文件和运行绑定项目，
  下载核对当前通过审计的草稿及文件指纹。没有 Supabase Auth 或多用户项目 ACL。
- **Supabase 接入准备（2026-10-14）**：项目 URL + publishable key 公共连接验证成功；
  改用 `sb_secret_...` 服务端配置契约，已提供五张元数据表、RLS、私有 bucket 幂等迁移
  和脱敏连接/写探针工具。服务端 secret、五张表、RLS、private bucket 与真实数据库/
  对象写入下载清理探针均已验证；应用 Provider 纵向回归已通过并切至 Supabase。
- **未做**：云端存储、多用户身份与权限、自动异步恢复、正式工程归档、部署与 CI。
- **报告/审计与同步 Agent 主链**：canonical 报告适配器只消费冻结日报载荷与稳定
  证据 ID，生成结构化草稿、Excel + 两份 Markdown、事实/单元格绑定和文件哈希；
  独立审计重新读取三件套并核对事实、引用、章节与责任措辞。同步执行器根据 Supervisor
  动作完成报告、审计、最多两轮退回和人工复核交接。
  原型自带的计算、阈值重判和本地 RAG 不进入服务端主链。
- **AI 日报与 RAG 主链（2026-10-14）**：`report_mode=ai` 下 Supervisor 调用 LLM
  规划重点和证据主题，并调用 `retrieve-standard-evidence` 做运行时 RAG；报告交付 Agent
  调用 LLM 生成受约束正文；审计 Agent 在确定性文件审计通过后调用独立 LLM 做语义审查。
  模型只能引用冻结事实占位符和本次证据 ID。真实 Pinecone 纵向验收已通过；当前本机缺
  `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`，所以真实模型日报质量尚未验收。

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
- `报告交付 Agent`
- `审计 Agent`

首版于 2026-10-12 收敛为以上三个逻辑 Agent。数据解析、确定性判定、证据检索和工况分析
作为 Skill / 服务能力由 Supervisor 调用，不再各自设置 Agent。

Supervisor 是唯一总控角色。报告交付与审计 Agent 不能绕过 Supervisor 改变流程状态，
审计 Agent 不能直接修改源事实。自动修订最多两轮，达到次数、时间或调用预算后转工程师。

## Skill 组成

| Skill | 当前职责 |
| --- | --- |
| `parse-monitoring-data` | 解析长表或明确表头的混合宽表并核验字段 |
| `normalize-monitoring-data` | 统一点号、时间、单位和量值语义，保留来源限制与日报聚合统计 |
| `evaluate-thresholds` | 执行确定性的三重判据计算 |
| `retrieve-standard-evidence` | 检索规范条文、版本和适用条件 |
| `retrieve-similar-cases` | 检索相似工程与工况案例 |
| `analyze-work-condition` | 分析异常事实与施工工况的关联 |
| `render-daily-report` | 按模板生成监测日报草稿 |
| `validate-report` | 校验数字、状态、引用、模板和责任措辞 |

## 稳定原则

- 规则主判，RAG 举证，模型表达；RAG 不参与或改写风险判定。
- 规范判据决定超限事实，案例不改变阈值。
- 阈值判据必须来自现行规范条文并标注条文出处；用于真实工程前须由设计方确认
  （GB 50497-2019 第 8.0.1 条）。
- 模拟数据仅用于验证流程健壮性与场景覆盖，**不替代真实数据**，
  必须带 `data_origin = "simulated"` 标识并与真实数据分开统计。
- 高严重度数据质量问题的期次不参与风险判定，一律弃权转人工复核。
- **缺基坑设计深度 H 时，不得用绝对量限值替代 `min(绝对量, %H)`**：绝对量只作上界，
  未超上界 → 弃权（`MISSING_H`）且不得判为「正常」；已超上界 → 超限结论必然成立。
- **上传文件落盘名一律由 `file_id` 生成**，不用用户文件名（防路径穿越）；
  存储 provider 未真正实现时必须显式报错，不得提供空壳。
- **判定逻辑不得用 TypeScript 重写**：Web 侧只做协议转换（子进程调用 Python 脚本）。
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
├── src/                              Next.js 16 全栈工程（含 /workbench 与运行/复核 API）
├── tests/                            Vitest 118 项通过（另 6 项 live 默认跳过）
├── var/
│   ├── uploads/                      上传文件存储（gitignore）
│   ├── runs/                         运行、检查点和人工复核修订（gitignore）
│   └── report-artifacts/             日报三件套运行产物（gitignore）
├── 确定性计算层/                      三阶段引擎（242 项回归测试）
├── 数据资产/                          仅本地：模拟数据快照 + 原始数据备份（已 gitignore）
├── tools/bridge-smoke/               引擎桥接冒烟测试
├── source/                            离线 RAG 构建、查询与 FastAPI 原型
├── data/{ocr_text,chunks.jsonl,chroma_db}  已入库的规范文本、切片与本地向量库
├── models/bge-small-zh/               本地 Embedding 模型（权重由 Git LFS 分发）
├── 确定性计算层_监测参数清单与规范依据.md
├── 方案与迭代note/
│   ├── 初步方案.md
│   ├── 框架demo.md
│   ├── 链路口语化.md
│   └── 07/08/10/11 系列文档           可行性分析 / 阈值口径 / 开发推进 / 可视化指引
├── skills/
│   ├── README.md
│   ├── parse-monitoring-data/scripts/inspect_file.py
│   ├── normalize-monitoring-data/scripts/normalize_records.py
│   ├── evaluate-thresholds/scripts/{run_judgement,check_strictness}.py
│   ├── retrieve-standard-evidence/
│   ├── retrieve-similar-cases/
│   ├── analyze-work-condition/
│   ├── render-daily-report/scripts/
│   ├── validate-report/scripts/
│   ├── deep-pit-monitoring-report/   日报表式与实现参考资产
│   └── _archive/prototypes/          非主链团队原型留档
└── rag/
    └── README.md                      双 Provider 证据接口契约
```

## 尚未确定

以下内容仍需讨论，不应被 Agent 默认：

- 使用本地模型还是远程模型；
- Pinecone rerank 模型仍未确定；
- 规范和案例资料的具体来源与授权方式；
- 项目专项方案与通用规范的优先级配置方式；
- 正式原始数据的逐单元来源、插值与末值保持标记格式；
- 日报模板的最终版本；
- 是否必须完全离线运行；
- Demo 的部署与打包形式。

## 待推进事项

已完成：

- ✅ 确认最小输入数据契约（见 `确定性计算层/pipeline/stage1_data_preparation/ingest.py`）。
- ✅ 确认阈值与规范适用规则（默认规范库 + 用户上传字段级覆盖）。
- ✅ 建设最小规范库（30 本规范索引 + GB 50497-2019 条文级阈值）。
- ✅ 跑通正常、超限、数据错误、弃权四类流程（**242 项回归测试** + 27 个模拟场景）。
- ✅ 补齐《监测参数清单与规范依据》的全部参数缺口（20/20 可测参数覆盖，模拟数据与规范库各 22 项对齐）。
- ✅ 建立 `ExcavaGuard/数据资产/`（模拟数据快照 + 原始数据备份，逐字节校验一致）。
- ✅ 冻结日报模块接口契约（`excavaguard.daily_report_input/v1` + JSON Schema + 校验工具），
  A/B/C 三组实跑载荷均通过契约校验。
- ✅ 参数查漏：新增 7 项遗漏参数（土体温度 + 6 项勘察/设计参数），完成原始数据剖析，
  并把 `soil_temperature` 接入规范库与模拟数据。
- ✅ 目标实现度评估：定位 2 个 P0 阻塞与 3 个 P1 隐患（`06_..._目标实现度评估.md`）。
- ✅ **P0-1 时序派生**：`baseline` / `previous` / `interval_days` 由测点时序确定性派生
  （显式值优先，打 `*_DERIVED` 标记）—— 解除"原始观测表 100% 弃权"的阻塞。
- ✅ **P1-1 规范严格度校验**：`limit_strictness.py`，三处接入，只反馈不阻断。
- ✅ **P1-2 缺 H 行为**：绝对量只作上界，未超上界弃权 `MISSING_H` 并降级为「未知」。
- ✅ **P0-2 用户数据接入通道**：`file_reader.py`（编码探测 + 列名别名）+ 上传端点 +
  存储层 + 前端接线 + 可视化测试工作台 `/workbench`。
- ✅ **最终混合宽表接入**：85 通道宽表可展开为 85,680 条源记录，保留原始值/
  已有累计量语义、来源限制和日内统计；按报告日生成逐通道每日末值历史。
  真实上传与 `/api/runs` 验收通过。

待推进（**按优先级**）：

1. **企业身份**：Supabase业务存储已实现；2026-10-27已新增本地独立账号和项目成员权限，后续可接入Supabase Auth / 企业SSO。
2. **既有本地资产迁移**：`var/` 中已有本地测试历史保留，尚未显式复制到云端；
   不自动删除。
3. **正式归档与异步编排**：工程师接受/退回/拒绝已实现；后续建设正式归档、
   异步 worker 和自动恢复，不得自动签发。
4. **真实模型与引用质量评测**：配置 LLM 后运行 `npm run ai:test`，并评测正式报告
   场景的正文质量、RAG 引用准确率、无命中弃权和审计问题召回。
5. **其余两个 Skill 实体化**：`retrieve-similar-cases` / `analyze-work-condition`。
6. **P2-1 温度补偿**：轴力类判据可能混入温度效应（已接入 `soil_temperature` 数据）。
7. **P1-3 工程条件交互补全**：缺什么提示补什么（目前页面已给出提示，但未做逐项引导）。
8. 部署与 CI。
9. 案例知识库（脱敏后）—— 可选，须先确认授权。

## 记忆维护规则

- 只记录已经确认且后续仍有价值的信息。
- 新决策应写明日期，并修改对应的旧结论，避免同时保留互相冲突的描述。
- 已完成事项从“待推进事项”移入“当前状态”。
- 技术选型经确认后补充具体版本和验证过的运行命令。
- 架构发生变化时，同时更新 `AGENTS.md`、`方案与迭代note/框架demo.md` 和相关 `SKILL.md`。
- 不写入密码、Token、个人身份信息、未经脱敏的工程数据或大段运行日志。

## 决策记录

### 2026-10-14 · Supabase 公共连接与基础设施准备

- 用户已在 `.env.local` 配置项目 URL 和 publishable key；`npm run supabase:check`
  实测为 `public_connected`，只证明公共客户端可达。
- 按 Supabase 新式 key 口径，浏览器使用 `sb_publishable_...`，服务端改用
  `SUPABASE_SECRET_KEY=sb_secret_...`；数据库密码不进入应用配置。对话中出现过的旧
  数据库密码应在 Dashboard 轮换，轮换值不得写入记忆或仓库。
- `supabase/migrations/202610140001_excavaguard_storage.sql` 已准备项目、成员、
  文件、运行修订、报告产物五张表，RLS 默认只读及私有 `excavaguard-private` bucket。
- `npm run supabase:check` 只读检查，`npm run supabase:verify` 使用随机项目和对象
  完成真实上传/下载/删除并清理；两者都不回显 key。
- 后续用户已正确配置 `SUPABASE_SECRET_KEY`；私有 `excavaguard-private` bucket 已通过
  Storage 管理 API 创建并验证。真实写探针定位到五张元数据表尚未进入 Data API schema；
  修复检查器以真实 GET 代替会对缺表产生假阳性的 HEAD 检查。
- 用户随后在 SQL Editor 执行完整迁移，界面返回 `Success. No rows returned`；
  `npm run supabase:verify` 实测 `infrastructure_verified`，五张表与私有 bucket 全部通过，
  随机数据库记录和私有对象完成写入、下载、publishable key 拒绝及清理，错误和残留均为 0。
- Supabase 应用 Provider 随后完成：监测数据与用户规范进入私有 Storage 和文件元数据表；
  Python 子进程使用验哈希临时文件；运行状态进入不可变 revision 表并以主键实现 CAS；
  审计通过后三件套进入私有 bucket，下载与接受从云端重新验哈希。
- `.env.local` 已显式设置 `EXCAVAGUARD_STORAGE_PROVIDER=supabase`。真实 simulated
  纵向验收覆盖双类型上传、分析、并发 revision、报告下载、人工接受、对象篡改阻断
  及清理，1/1 通过；
  初次验收定位并修复 Supabase `+00:00` 时间格式边界和缺表 HEAD 假阳性。
- 基础设施验证不等于应用 Provider 已实现。Provider 完成上传、Python 临时读取、
  运行并发修订、三件套下载、失败清理回归前，storage provider 必须保持 local。

### 2026-10-14 · 本地日报交付闭环

- 保留 Next.js + Python 技术栈，不引入新生产依赖；确定性引擎与规范资产不变。
- 运行输入在计算前保存，冻结结果和 Agent 报告/审计转换后保存完整检查点；
  失败保存真实错误码。每次写入不可变修订，旧修订提交返回 409。
- 工作台默认显式开启报告链，API 默认仍只分析。历史可恢复结果与原输入；
  人工决定绑定记录修订号和完整草稿引用，接受只表示草稿复核。退回/拒绝关闭下载，
  修正输入后建立关联新运行，旧报告和理由保留。
- Supervisor 路由进入轨迹；能力调用保存实际起止时间。原预算内支持显式续跑，
  无检查点、活动任务或预算到期时需新建关联运行；没有异步 worker 或自动恢复。
- 单操作者密码会话和单项目隔离已实现，生产未配置时拒绝业务 API；
  历史无归属上传只绑定固定默认项目，切换配置不转移文件。
- 上传索引原子替换并使用文件锁；运行用完整临时文件与排他发布防并发覆盖。
  索引或运行损坏必须明确报错，不退回旧成功状态或静默按空处理。
- 下载绑定当前项目持久化审计结果，并重新验证大小和 SHA-256；
  当时 Supabase Provider、多用户 ACL、正式工程签发归档仍待实现；同日后续 Provider
  已接通，见上方 Supabase 决策记录。
- 验收：`npm run check` 105 项通过，3 项 local-RAG live 默认跳过；
  `npm run build` 13 条路由生成，部署依赖清单含运行/环境/临时文件数为 0；
  真实 85 通道宽表完成落盘恢复和接受；浏览器验证刷新恢复、退回关闭下载、
  修正输入后的关联重跑、三 Agent 轨迹、Excel 下载和接受草稿。

### 2026-10-14 · 日报三件套与三 Agent 同步主链接通

- `render-daily-report` 模板升级为 `deep-pit-monitoring-report/service-v2`，只消费
  `excavaguard.daily_report_input/v1`，输出 Excel、封面 Markdown、附表及清单
  Markdown；文件落在 `var/report-artifacts/<draft_id>/`。
- Excel 包含封面、实际出现的附表 A～F、超限清单、待复核事项和来源说明。未知测项
  不默认塞入表 A；未提供巡视记录时不生成表 G，且明确不得判为巡视正常。
- `ReportDraft` 新增三件套清单与逐单元格事实绑定；内容哈希覆盖结构化草稿、文件清单
  和单元格绑定。审计核对文件 SHA-256、字节数、工作表、单元格、Markdown 和责任边界。
- `src/server/agents/executor.ts` 已按 Supervisor 动作串联报告与审计，报告责任问题最多
  自动重渲染两轮，审计通过后停在 `awaiting_human_review`。
- `POST /api/runs` 默认仍只返回冻结载荷；显式 `options.generate_report=true` 时执行
  同步三 Agent 链并在审计通过后返回三件套下载地址。当时运行状态尚不落盘，
  同日后续已完成本地持久化与复核闭环，见上方决策。
- 最终 85 通道宽表已完成真实纵向验收：A～F 六类附表全部生成，G 省略，文件审计通过，
  下载端点可读取 Excel，路径穿越被拒绝。
- 当前“独立审计”是确定性一致性与责任边界审计，不等于独立 LLM 语义审计，也不能证明
  规范适用性或工程判断正确。
- 验收：引擎回归 242 项；`npm run check` 88 项通过、3 项 local-RAG live 默认跳过；
  `npm run build` 生成 9 条路由。

### 2026-10-14 · 最终混合宽表接入与标准化 Skill 实体化

- `file_reader.py` 支持 `监测项目-测点号-量值语义(单位)` 混合宽表；
  未识别通道会整表拒绝，不静默丢列。最终工作簿 85 通道 × 1,008 时刻展开为
  85,680 条源记录。
- `precomputed_cumulative` 使用语义零基准并留
  `PRECOMPUTED_CUMULATIVE` / `SEMANTIC_BASELINE_ZERO` 标记；若同时显式提供非零基准，
  记高严重度 `SEMANTIC_BASELINE_CONFLICT` 并阻塞该条判定。
- 时序派生、质量扫描、趋势、速率历史和质量阻塞键统一改为
  `(point_id, metric_key)`，裂缝长度/宽度共享点号时不再串线。
- 宽表进入 `/api/runs` 前按报告日生成逐通道每日末值历史，并保留日内样本数、
  起止时间、首末值、极值、最大相邻变化及工作簿级时间对齐/重采样/插值/
  末值保持限制；未提供逐单元格来源标记时显式留痕。
- `normalize-monitoring-data` 已有 Python 适配脚本、Next.js runner 和注册表实现；
  Python 桥接优先使用仓库 `.venv`，根依赖新增 `openpyxl`。
- 最终工作簿真实上传与分析通过：报告日 `2026-10-08` 使用 340 条每日历史计算，
  日报载荷只交付当日 85 条；累计通道不二次归零，未知的水平位移对象及裂缝对象
  保持 `UNKNOWN_METRIC` 人工复核。
- 引擎回归 242 项、当时 `npm run check` 83 项通过。后续日报三件套与三 Agent
  同步执行器已在同日接通。

### 2026-10-13 · 本地 RAG HTTP 兼容与最终输入核查

- `source/evidence_api.py` 实现统一证据请求/响应与候选 ID 过滤，`source/server.py`
  提供 `POST /api/evidence/search`；旧 `/api/search` 保留给历史原型。
- `source/query_kb.py::runtime_database_dir()` 自动复制到 `var/rag/chroma_db/`，
  查询 CLI 与旧 demo 同样改用运行副本，模型仅从本机完整 BGE 权重加载。
- Python 接口回归 8 项、真实 BGE/Chroma → Next.js Retriever/Skill 3 项均通过；
  真实查询命中 GB 50497-2019 8.0.1/8.0.5/8.0.4，未改变发布基线或在线 Provider 配置。
- `final_test/监测数据整合_7天_10分钟.xlsx` 有 1,008 个时刻、85 通道，
  包含累计位移和原始观测值混合列；当日核查时长表读取器尚不能直接接受。
  来源说明记录时间平移、线性插值和末值保持，不得称为原始同步实测。
- 最终交付建议采用团队的日报三件套（xlsx + 封面 md + 附表/清单 md）
  并附工程事实、证据、审计与轨迹 JSON。宽表接入、日频/日内口径、xlsx 导出和同步
  三 Agent API 已于 2026-10-14 完成；持久化已完成，独立 LLM 语义审计接线已完成但
  真实模型质量仍需配置 LLM 后验收。

### 2026-10-13 · 报告与审计 Skill 服务端契约接入

- `deep-pit-monitoring-report` 作为团队交付的日报表式与实现参考资产归入 `skills/`，
  不新增第九个业务 Skill 或第四个 Agent。
- canonical `render-daily-report` 只消费 `excavaguard.daily_report_input/v1`、
  结构化证据与分析快照，生成草稿、Markdown、事实绑定和证据引用；不重算数值或风险等级。
- canonical `validate-report` 使用相同上游快照独立重渲染，核对事实值与 SHA-256 绑定、
  稳定 evidence ID、批准模板版本、必填章节和责任措辞；失败只返回问题清单。
- `deep-pit-monitoring-report` 自带的计算、阈值重判和本地 Chroma 检索不进入服务端主链，
  判定唯一来源仍是 `evaluate-thresholds`，规范证据唯一入口仍是
  `retrieve-standard-evidence`。
- 当时八个业务 Skill 中有五个可调用实现，报告交付与审计 Agent 标记为 `foundation`；
  后续 normalize、三件套和同步执行器已于 2026-10-14 接通。
- 当时 `npm run check` 实跑 79 项通过、`npm run build` 生成 8 条路由；当前验收见
  2026-10-14 决策记录。

### 2026-10-13 · Pinecone 在线规范 RAG 导入与检索基础

- 在线索引采用 Pinecone integrated embedding；文档与查询都发送文本，不复用或混入
  本地 BGE 的 512 维向量。目标索引 `excava-guard` 使用 NVIDIA
  `llama-text-embed-v2`、1024 维 cosine、语义字段 `text`；`standards-v1` 已导入
  7,180 records，远端记录数和本地清单一致。
- `tools/rag/` 已实现来源精确映射、状态门禁、索引兼容性检查、显式建索引和 96 条一批的
  幂等 upsert；dry-run 生成 7,180 条候选记录。
- 排除项为：项目文件 16 条、GB55003 非首选 OCR 来源 108 条、无条文号切片 1,375 条；
  超过 420 字符的切片 24 条；规范来源映射零遗漏、候选 ID 零冲突。
- `rag/standard-status.json` 是生效状态的人工复核入口。任何 `unknown`、缺复核人或缺复核时间
  都会阻止真实上传；2026-10-13 用户确认 29 个规范编号均已由团队人工复核，现均为 `active`。
- `PineconeStandardEvidenceRetriever` 已改用 `searchRecords`，`retrieve-standard-evidence`
  runner 已实现成功、无命中、非法输入、Provider 不可用和非现行证据弃权路径。
- 首次导入在 2,016 records 处因瞬时网络错误中断；工具补充单批指数退避后幂等重跑完成。
  真实语义查询返回 5 hits，返回正文、规范编号、条文号、来源位置和状态均与本地清单一致。
- `npm run check` 实跑 75 项通过，`npm run build` 成功生成 8 条路由。
- `.env.local` 已配置索引、namespace、cloud/region、模型和文本字段，真实密钥保持在
  gitignore 文件中。

### 2026-10-12 · 三 Agent 收敛与 Supervisor 基础状态机

- 首版由原六角色设计收敛为 `Supervisor` / `报告交付` / `独立审计` 三个逻辑 Agent；
  数据解析、确定性判定、证据检索与工况分析保留为 Skill / 服务能力。
- `src/contracts/agent-runtime.ts` 定义 `excavaguard.agent_state/v1`，分离保存引擎事实快照、
  证据、分析、草稿、审计、人工复核和运行轨迹；所有产物带版本与内容哈希。
- `src/server/agents/supervisor.ts` 使用显式 TypeScript 状态机，不引入 LangGraph.js；
  支持能力不可用等待、最多两轮报告修订、模型调用/时间预算、责任归属与人工接管。
- 修改草稿使旧审计失效；修改引擎、证据或分析快照使受影响的下游产物失效。
- 当前只完成 Supervisor 基础，不代表报告生成与审计 Skill 已实现，也未接入 API 或持久化。
- `npm run check` 实跑 60 项通过，其中 Agent Runtime 10 项，6 个上传到分析端到端用例未跳过。

### 2026-10-12 · 规范 RAG 资产入库与本地环境验证

- 远端 `main` 新增 `data/ocr_text/`、`data/chunks.jsonl`、`data/chroma_db/`；
  提交记录声明已完成权利人/作者授权决策。重新分发和公开部署前仍须留存并核验授权依据。
- 本地知识库实测为 30 个来源、8,698 个唯一切片与 8,698 条 Chroma 向量，
  collection 为 `jikeng_norms`，向量维度 512，距离度量 cosine。
- 仓库 `.venv/` 使用 Python 3.13.13 安装完整 `requirements.txt`；
  已验证 `chromadb 1.5.9`、`sentence-transformers 6.1.0`、`torch 2.14.1`
  可加载本地 BGE 权重并查询现有 ChromaDB。
- Git LFS 3.8.0 已完成 `pull` 与 `fsck`。当前开发机存在全局 `core.hooksPath`，
  应使用 `git lfs install --skip-repo`，不得用 `--force` 覆盖已有 hook。
- 下一步是统一本地证据接口并实体化 `retrieve-standard-evidence`，随后再按同一
  512 维 Embedding 口径批量导入 Pinecone；不能直接把 ChromaDB 二进制目录上传为 Pinecone 索引。

### 2026-10-10（深夜·续）· 推送远端：受阻，已备好通道

- **目标**：把成果推送到 `https://github.com/abreeezol/ExcavaGuard` 的 `main`。
- **受阻**（两个独立原因）：
  1. **网络**：本机 `github.com` 不可达（代理 CONNECT 502，直连超时）。
     仅 `api.github.com` / `codeload.github.com` 可达 → `git push` 不可能成功。
  2. **权限**：GitHub 连接器**只读**，建分支 / 写文件 / fork 全部 403。
     连接器身份与仓库所有者不是同一账号。
- **已备通道**：`.artifacts/publish/`（本地专用，不入库）——
  `push_to_github.py`（纯 API 发布，需 PAT）+ `manifest.json`（3 次提交 / 106 文件）
  + `PR_BODY.md` + `ExcavaGuard_payload.tar.gz`（离线包）。
- **差异口径**（vs 远端 main `6f0b6d3`）：新增 87 / 修改 19 / 相同 36 / 远端独有 0。
- **本地资产不入库**：`数据资产/` 与两处大体积行级明细转储已加入 `.gitignore`。

### 2026-10-10（深夜）· ⑤ 上传端点 + P1-2 修复 + 可视化工作台

- **用户要求**：先做 ⑤ 上传端点，做完再完成 P1-2，最后给一个可可视化测试的方法。
- **⑤ 上传端点**：
  - 存储层用**本地文件系统**（`var/uploads/`），落盘名由 `file_id` 生成；
    用户规范放独立目录，保证判定只加载"本次那一份"。
  - **Supabase 适配器明确不实现**：缺 bucket 与元数据表、无法验证，
    不提供"看起来能跑"的空壳（声明 supabase provider 会直接报错并说明原因）。
  - 端点：`/api/monitoring-files`（上传即解析报告）、`/api/monitoring-files/sample`、
    `/api/standards`（上传即校验严格程度）、`/api/runs`（原 501 → 真实三阶段）。
  - 引擎桥接：新增 `inspect_file.py` / `check_strictness.py`，扩展 `run_judgement.py`
    支持 `options.file_path`（引擎侧读文件，复用编码探测）。
  - **过程中修掉真 bug**：`check_upload_strictness()` 从 registry 取"合并后规则"，
    但上传校验发生在落盘**之前**，拿到的是默认规则 → 用户值被默认值顶掉，
    校验**永远显示"无差异"**。改为现场合成 `{**default_rule, **user_rule}`。
  - 测试：`tests/routes.test.ts`（24 项协议边界）+ `tests/upload-and-run.test.ts`
    （6 项端到端，需 Python，自动探测找不到则跳过）。`npm run check` 50 项全绿。
  - 注意：探测 Python 必须用**异步** `spawn` —— `spawnSync` 在受限环境下返回 `EBUSY`，
    会把"环境不支持同步 spawn"误判成"没有 Python"。
- **P1-2 缺 H 不得放宽判据**：
  - 缺 H 时绝对量只作**上界**（`cumulative_upper_bound_only`）：
    未超上界 → 弃权 `MISSING_H` + `H_MISSING_CUMULATIVE_ABSTAINED`，且落在「正常」时降级为「未知」；
    已超上界 → 超限结论必然成立，照常判定。
  - 把"是否真正判定过"的判据从 `bool(j.checks)` 改为 `bool(utils) or convergence_fired`，
    否则说明性 check 会把弃权项撑成"正常"。
  - **顺带修掉**：`run_pipeline()` 会把 `rate_history` 写回调用方的 `ctx`，
    同一 ctx 复用于第二批数据时会沿用旧速率历史 → 改为内部使用副本。
  - 测试 203 → **223 项**。
- **可视化测试工作台**：
  - `/workbench` 页面（`page.tsx` + `workbench-client.tsx`），走真实 API，**不做任何判定**。
  - 示例数据 CSV：5 测点 × 7 天，**只有 6 列、故意不含派生列**，中文表头 + UTF-8 BOM；
    其中 `WTHD-03`（累计 24 mm）刻意设计成"默认判危险报警、放宽阈值后降为预警"。
  - 操作手册 `方案与迭代note/11_可视化测试指引.md`
    （启动、四步操作、三个验证点、常见问题、API 替代方式）。
  - 实测：默认库 `{危险报警:17, 正常:10, 未知:5, 关注:2, 预警:1}`；
    用户宽松规范 `{危险报警:10, 正常:12, 预警:7, 未知:5, 报警:1}`，**9 条降级**；
    缺 H 时 15 条 `MISSING_H`，**其中 0 条被判为「正常」**。
  - 首页与侧栏加入口；`npm run build` 8 条路由全部生成。
- **未推送远程**：① 的阈值口径统一仍只产出替换文本，需用户授权后才推送。

### 2026-10-10（晚·续）· 路径 A：远程代码合并到本地

- **用户选择**：路径 A（拉远程到本地），要求「只复制有变动的部分」「删除重复部分」
  「保留新开发的确定性计算部分」。
- **执行方式**：`git fetch` 被代理阻断（502）、`raw.githubusercontent.com` 超时，
  但 **`codeload.github.com` 可用** → 下载 tarball 解压后逐文件比对。
  *经验：本机环境访问 GitHub 用 codeload tarball，不要用 git fetch / raw。*
- **合并结果**：远程新增 **38** 个全部引入；本地未改动而远程较新的 **7** 个取远程新版；
  本地已改动的 **6** 个（`AGENTS.md` / `memory.md` / 4 个 SKILL.md）**保留不覆盖**；
  删除重复的空目录 `ExcavaGuard-main/`。
- **口径修正**：远程 `skills/README.md` 写「后续 TypeScript 确定性实现」，
  与已定的 Python 子进程方案冲突 → 已改写为 Python 并说明不重写引擎的理由。
- **`.gitignore` 补充**：忽略 `数据资产/原始数据备份/`（37 MB）与
  `确定性计算层/derived/日报接口载荷_*.json`（36 MB）；入库体积由 76 MB 降至约 3 MB。
- **验证**：`npm ci` 404 包成功 → **`npm run check` 全绿**（ESLint + TS + **Vitest 32/32**）
  → **`npm run build` 成功**（Next.js 16.4.0，4 条路由）；
  引擎 203 项、留档 57 项、场景 27/27、桥接 13/13 全绿；原始数据指纹未变。
- **意义**：`src/` 与 `确定性计算层/` 已在同一工作区，**⑤⑥ 的阻塞已解除**。

### 2026-10-10（晚）· 按建议顺序推进开发 ①~④

- **① 统一阈值口径**：清查确认本地 8 个 `SKILL.md` 已无 demo 表述；
  产出 `方案与迭代note/08_阈值口径统一说明.md`（含远程替换全文）。
  **远程同步未执行**（需授权）。
- **② 建立文件契约**：修复原 **P0-1** —— `baseline_value` / `previous_value` / `interval_days`
  改为**按测点时序确定性派生**（显式优先、打 `*_DERIVED` 标记）。
  实测：5 列原始观测表由「7/7 全弃权」变为「弃权 1/7，识别出 6 期危险报警」。
  新增 `file_reader.py`（编码探测 + 88 条监测项别名 + 25 条方向别名）、
  `contracts/monitoring_input.contract.json`（由代码导出）、`09_用户数据文件契约.md`。
  **顺带修掉生成器缺陷**：非数值字符串（`"N/A"`）被当作有效观测推进间隔，导致速率被放大 2 倍。
- **③ 实现宽松度校验**（原 **P1-1**）：新增 `limit_strictness.py`，三处接入
  （`upload_standard` / `resolve_limit` / `build_daily_report_input`），载荷新增
  `standard_override_warnings`。**只反馈不阻断**，每条差异带默认值的规范名称与条文号。
  开发中发现并修掉一个真 bug：用户只覆盖 `cumulative_mm` 时须用**合并后**规则取值
  （`cumulative_pct_H` 会继承默认值），否则放宽幅度会算错。
- **④ 单点连通验证**：`skills/evaluate-thresholds/scripts/run_judgement.py`（stdin/stdout JSON）
  + `tools/bridge-smoke/run_judgement.mjs`（纯 Node，`runner.ts` 原型）。**13/13 通过**。
  技术路线确定：**Python 子进程**，不采用 TypeScript 重写引擎。
- **回归**：主测试 **203 项全绿**、留档 57 项、场景 27/27、日报契约校验通过。
- **⑤⑥ 未开始**：需改远程 Next.js 工程（本地无 `src/`）。待用户确认是否拉远程代码到本地
  与是否授权推送。

### 2026-10-10（下午）· 远程仓库对比与两项可行性分析

- **仓库关系**：本地 `.git` 的 origin 即 `github.com/abreeezol/ExcavaGuard.git`，
  但本地是 **2026-09-29 的独立快照**（单提交 `887ba18`，作者 Codex，分支 `task/project-inspection`），
  **无上游跟踪、与远程 `main` 无共同历史**。远程 `main` = `6f0b6d3`（2026-10-09 11:45），另有分支 `zhangxiaolong`。
  合并时须用 `--allow-unrelated-histories`，或**以远程为基新建分支后拷贝本地新增目录**（更干净）。
- **远程已有**：Next.js 16.4.0 全栈前端（工作台 + `/api/health` + `/api/runs`）、
  六类 Agent 注册（`status: planned`）、八 Skill 契约登记（`status: not_implemented`）、
  RAG 双 Provider 适配器（Pinecone / 本地 loopback）、32 条 Vitest 测试。
- **远程没有**：任何业务实现、文件上传、Supabase 表结构、真实知识库。
- **本地独有**：完整确定性计算引擎（纯 Python 标准库、零第三方依赖）、22 项规范阈值库、
  27 场景模拟数据、203 项测试、日报冻结契约、数据资产备份。
- **上传未实现**：前端有上传 UI 占位但按钮 `disabled`；无上传 API；`POST /api/runs` 恒返回 501，
  契约要求 `monitoring_file_id: uuid`（文件须先在存储中）。
- **打通路径**：远程 README 已规定确定性 Skill 放 `skills/<name>/scripts/`。
  推荐 **Python 子进程 → 独立 Python 服务**；**不建议用 TypeScript 重写引擎**
  （二次实现会给已验证的判定逻辑引入偏差）。
- **★ 合并前必须先解决的冲突**：远程 `skills/evaluate-thresholds/SKILL.md` 仍写
  「仅接受 `source_type=demo` 且标签含"演示"的阈值」，与本地已确认的
  「GB 50497-2019 真实条文阈值 + 标注出处 + 设计方确认」**安全口径冲突**，须以本地为准同步远程。
- **机制 E 待新增模块**：`limit_strictness.py` —— 校验用户阈值是否比默认更宽松，
  命中则反馈具体差异并注明对应国家标准条文号。设计已定（见 `07_..._两项可行性分析.md`），**未开发**。
  两个关键陷阱：`min_ratio_of_design` 是「越大越严」（方向与其余字段相反）；
  缺 H 时 `%H` 类字段标 `incomparable` 而非默认通过。

### 2026-10-10

- **参数查漏（用户要求）**：对照《监测参数清单与规范依据》核查四类原始数据，发现 **7 项遗漏参数**：
  - 监测类 1 项：**土体温度**（依据 §8.0.9-6 / §7.0.4-12；隧道数据 2,951 条，12.8~21.4 ℃）
    —— 这是全部参数中**唯一有真实数据支撑**的一项；
  - 勘察/设计类 6 项：不排水抗剪强度 Cu（168 组）、SPT 击数 N（152 组 / 9 钻孔）、
    分层测压管水头（3 个含水层）、地层顶面高程、开挖宽度 B、案例刚度参数。
  - 已修改参数表：§一 新增序号 24、25；§九 重构为 9.1（加「当前状态」列）+ 9.2（新增 11~17 项）。
  - 已基于原始数据剖析：`tools/analyze_supplementary_params.py` → `derived/补充参数剖析.json`。
- **顺带修复的真实缺陷**：`℃` 单位此前被判为 `UNSUPPORTED_UNIT`（高严重度阻塞码），
  导致**含温度列的真实数据整批弃权**。已新增 `TEMPERATURE_UNITS` 并加 3 项回归测试。
- **目标实现度评估（用户要求）**：结论见 `06_上传数据到风险识别链路_目标实现度评估.md`。
  **计算引擎与规范机制已可用，但"用户上传"入口未打通**。实测证据：
  仅含 `point_id/timestamp/metric/value/unit` 的原始观测表 → **7/7 全部弃权**
  （`MISSING_BASELINE` + `MISSING_PREVIOUS`），零风险识别输出。
  根因：`baseline_value` / `previous_value` / `interval_days` 被当作**输入字段**而非**时序派生量**，
  而 `build_point_series()` 已建好序列却只用于斜率。
- **新增安全边界（写入 `AGENTS.md`）**：
  ① 用户上传规范的严格度不得低于默认库，宽于默认必须提示；
  ② 缺 H 时不得用绝对量限值替代 `min(绝对量, %H)`，应弃权或降级。
  两条的自动化校验**尚未实现**，已在「尚未实现」中列明。

### 2026-10-09

- **阶段语义修正（用户明确纠正）**：「第一阶段→第二阶段→第三阶段」= 数据准备 → 确定性计算 → 规范比对，
  是流程先后关系，**不是**「通用方案进阶到专项方案」的递进关系。
  禁止在任何文档或代码注释中使用该表述；旧实现移入 `legacy/`。
- **模拟数据的用途边界**：仅用于验证 Agent 处理噪音与缺失的能力与场景覆盖，**不替代真实数据**。
- **规范来源**：默认读 `基坑智守项目相关规范`（视为覆盖大多数情况的通用规范），
  保留用户上传接口，**用户未上传时不作任何特殊处理**。
- **阈值口径（用户确认）**：保留 GB 50497-2019 **真实条文阈值**作为默认规范库判据，
  同步修改 `AGENTS.md` 与 `skills/evaluate-thresholds/SKILL.md`，
  解除原先「仅接受 demo 阈值」的限制，改为「判据来自现行规范条文并标注条文出处，
  用于真实工程前须设计方确认」。
- **数据质量阻塞**：新增高严重度质量问题阻塞机制，粗差、非数值、日期不可解析、
  单位不可识别、传感器漂移的期次一律弃权转人工复核，禁止"带病判定"。
- **粗差判据**：改为「孤立尖峰」（相邻两步大小相当、方向相反、总摆幅超阈值），
  不再对原始值做 ±kσ 统计离群 —— 后者会把真实突变与趋势尾部误判为粗差，属危险的漏判。
- **模拟数据集**：`data_simulated/`，S1~S27 共 27 个场景 / 57 测点 / 3,420 条记录，
  场景覆盖率 100%，与原始数据完全隔离。
- **参数缺口补齐（用户确认）**：对照《监测参数清单与规范依据》补齐 5 项缺口 ——
  ① 顶部竖向位移、② 地表裂缝（原仅建筑裂缝）、③ 管线水平位移、④ 立柱内力、⑤ 土体分层竖向位移。
  规范库同步新增 2 项：`pipeline_horizontal_displacement`（表8.0.5 管线行）、
  `soil_layered_vertical_displacement`（`limit_mode=none`，按 §8.0.1 待设计方确定）。
  新增场景 S24~S27；模拟数据与规范库各 22 项，**差集为空**。
  **关键原则**：规范无判据的项目必须弃权（`NO_APPLICABLE_RULE` → 未知），**不得判为「正常」**。
- **数据资产文件夹**：`ExcavaGuard/数据资产/`（只读快照）—— 模拟数据快照 + 原始数据备份（51 文件 / 37 MB，
  SHA256 逐字节校验一致）+ 覆盖核对报告 + README。
  **规范目录（30 本 PDF / 445 MB）经用户确认不纳入备份**，需要时直读原目录。
- **日报模块边界（用户确认）**：日报生成**由后续专门 Agent 负责**，本层只预留接口。
  据此把 `build_daily_report_input()` 从薄接入点加固为**冻结契约**
  `excavaguard.daily_report_input/v1`：补齐工程概况、逐测点成果字段、报警清单、
  人工复核队列、免责声明；修掉原先按位置 `zip` 对齐的脆弱点，改为按
  `(point_id, timestamp, metric_key)` 关联。配套产出 JSON Schema 与校验工具。
  **本层不生成日报正文与版式文件，不撰写结论与建议措辞。**
- **`risk_level = "未知"` 语义**：表示弃权，**不是"安全"**；必须转人工复核，
  日报中不得渲染为正常项。此约束已写入 `AGENTS.md` 工程安全边界。
- **当时决策（已于 2026-10-12 解除）**：本阶段暂缓 RAG，后续设计约束保留；
  2026-10-12 起已恢复规范证据检索建设。

### 2026-09-22

- 项目英文名确定为 `ExcavaGuard`。
- 项目采用 Skill 与 RAG 作为底层能力，但比赛展示增加多 Agent 协作。
- 多 Agent 采用 Supervisor、数据治理、判据与规范、风险归因、报告交付和审计六类角色。
- 暂不创建传统后端代码脚手架，优先完善 Skill、Agent、RAG 和项目文档结构。
- GitHub 远程仓库确定为 `https://github.com/abreeezol/ExcavaGuard.git`。

## 项目补充规范（2026-10-27）

新增全文上传 `/api/project-standards` 与工作台入口；独立 SQLite/FTS5 库 `var/project-standards/<project_id>/standards.sqlite3`，不写公共RAG。工程师确认地区/效力/范围后启用；运行冻结文档ID、哈希及清单，历史续跑不混入新增文件。AI正文须引用每份命中的补充规范，分类表及“项目补充要求核查”保留具名原文候选。PDF不自动覆盖数值阈值，沿用已有JSON阈值与严格度校验。当前仍单项目服务端UUID隔离；Supabase业务存储不改变该专库需本地持久卷的要求。16项专库回归通过；234页真实地方标准676切片，真实模型+RAG命中8条、正文引用5条、独立语义审查通过。特殊字体PDF乱码明确拒绝并提示OCR。细节和验收命令见18号说明。

## 周报每日变化可读展示（2026-10-27，本地未推送）

每日事实hash是冻结当天全部观测的校验指纹，不可反解数据。移除Excel/Markdown可见hash列，换成最多5条真实冻结观测摘要及当天完整明细跳转；明细保留全部观测并补基准/上次/变化量/单位及来源。后台hash不变，摘要和链接都经文件审计。11项Python周期回归通过，新增摘要/链接篡改、缺测、预览截断验证；既有合成周报快照已重渲染并审计，位于工作区 `process_file/周报可读数据展示/`。本次未调用外部模型，未跑通Node回归（当前node_modules缺typescript）；未声明全栈回归重新通过。

## 最新测试包与周报发布整理（2026-10-27）

按用户要求，将周报可读展示代码、update.md、19号剩余任务核对及精选合成测试包一并提交上游。入口 `final_test/latest/README.md`，分inputs/snapshots/reports/validation，不复制旧85通道文件。全部新增观测为人工合成，另附非真实标准的上传测试文本；不纳入真实工程文件、规范PDF、var数据库、完整日志或本机启动脚本。新增 `.venv/bin/python tools/test/verify-weekly-sample.py` 离线检查清单哈希、输入、快照及三件套；整数浮点JSON往返的摘要显示已统一。历史“未推送”段落描述当时状态，以本轮Git提交及发布结果为准。


### 2026-10-27 登录与项目授权功能发布

用户明确要求推送上游。本次发布独立账号、获授权项目选择、工程创建和四类角色、项目内文件与历史共享及服务端权限约束，同时更新项目规范Skill、使用说明、20号验收记录和update.md。保留原有本机启动脚本，不提交var账号目录、密码文件、.env.local或process_file验收截图。沿用本轮已完成验收：全量137通过/6项外部服务跳过，周期13通过，项目规范14通过/2项可选PDF跳过，合成周报离线复现及浏览器7项通过，生产构建完成；现有Next.js安全升级提示已披露。未初始化用户真实账号。
## 2026-10-28 Next.js 安全补丁升级

- 独立 worktree 分支 `security/next-16.4.3`：Next.js 与 eslint-config-next 从 16.4.0 精确升级至 16.4.3，更新 npm lockfile；显式配置 `experimental.agentUpgrade = "security"`，保留其他配置。
- 已检查本地与远端分支/提交及 GitHub 开放 PR，未发现等效升级。`gh` 不可用，改用 GitHub API；只读 Git 元数据阻止 fetch，使用 ls-remote 确认远端分支与本地跟踪记录一致。
- 验证：npm ci 成功，Next.js v16.4.3；清空继承的外部服务配置、指定现有项目 Python 虚拟环境后 npm run check 137 通过、6 项 live 跳过；NODE_ENV=production npm run build 成功；生产服务 health/workbench HTTP 200。
- 安装过程中修复 npm 可选依赖记录与离线缓存缺失导致的原生包问题；首次构建受环境非标准 NODE_ENV 影响，显式 production 后通过。原工作区未提交改动未纳入本分支；尚未推送或创建 PR。
