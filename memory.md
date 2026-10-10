# ExcavaGuard 项目记忆

> 本文件保存经过确认、需要跨任务延续的项目信息。临时执行日志、未经验证的猜测、密钥和原始敏感数据不得写入。

## 项目目标

ExcavaGuard 面向基坑监测工程师，将当日监测数据和施工工况整理为可复核、可追溯的监测日报草稿，并对异常条目提供受约束的辅助归因。

系统不替代工程师承担安全判断、预警发布、审核和签发责任。

## 当前状态

更新时间：2026-10-09

### 框架层（2026-09-22 建立）

- 项目根目录已经建立。
- `方案与迭代note/初步方案.md` 已记录项目定位、总体架构、MVP 和评测方向。
- `方案与迭代note/框架demo.md` 已记录 Skill 编排、多 Agent 设计、共享状态和审计回路。
- `skills/` 已建立八个业务 Skill 的目录和 `SKILL.md`。
- `skills/.agents/` 已建立编排层说明。
- 本地项目已初始化 Git 仓库，当前分支为 `main`，远程 `origin` 指向 `https://github.com/abreeezol/ExcavaGuard.git`。
- 八个 Skill 的 `references/`、`scripts/`、`tests/` **仍未建立**（仅有 `SKILL.md` 契约）。

### 确定性计算层（2026-10-09 落地）

- **阶段语义（唯一口径）**：
  - 阶段一 **数据准备** —— 用户上传数据与模拟数据统一作为风险识别参数的输入依据；
  - 阶段二 **确定性计算** —— 累计值 / 本次变化量 / 变化速率 / 趋势斜率；
  - 阶段三 **规范比对** —— 与规范判据比对，识别风险并分级。
  三个阶段是**流程先后关系**，不是「通用方案进阶到专项方案」的递进关系。
- 代码：`确定性计算层/pipeline/`（`stage1_data_preparation` / `stage2_deterministic_calc` /
  `stage3_standard_comparison` / `orchestrator.py`），回归测试 **223 项全部通过**。
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
- RAG：**暂缓**，`rag/` 仍为占位目录。

### Web 入口层（2026-10-10 接通）

- **存储**：`src/server/storage/monitoring-file-store.ts`，本地文件系统实现，
  根目录 `<仓库>/var/uploads`（已 gitignore）。落盘名**一律由 `file_id` 生成**，不用用户文件名；
  用户规范放**独立目录**（`standard/<file_id>/standard.json`），保证判定只加载"本次那一份"。
  扩展名白名单 + 20 MB 上限 + SHA-256 指纹。
  **Supabase provider 明确不实现**（缺 bucket 与元数据表，无法验证，不提供空壳）。
- **引擎桥接**：`src/server/skills/python-bridge.ts` —— Node 子进程调用
  `skills/*/scripts/*.py`（stdin/stdout JSON）。**判定逻辑不重写为 TypeScript**。
  桥接脚本：`parse-monitoring-data/scripts/inspect_file.py`、
  `evaluate-thresholds/scripts/{run_judgement,check_strictness}.py`。
- **API**：`GET/POST /api/monitoring-files`（上传即返回解析报告）、
  `GET /api/monitoring-files/sample`（示例数据 CSV）、
  `GET/POST /api/standards`（**上传即校验严格程度**）、`POST /api/runs`（真实三阶段）。
- **可视化测试工作台** `/workbench`：四步操作（工程条件 → 上传数据 → 用户规范 → 运行分析），
  右栏展示总览 / 风险分布 / 宽松告警 / 报警清单 / 待复核 / 逐测点明细 / 原始载荷。
  **页面不做任何判定**，只展示引擎结果。操作手册见 `11_可视化测试指引.md`。
- **未做**：鉴权、项目归属校验、运行记录持久化（`run_id` 仅本次请求追溯）、部署与 CI。

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

- 规则主判，RAG 举证（本项目暂缓），模型表达。
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
├── src/                              Next.js 16 全栈工程（含 /workbench 与 5 个 API 路由）
├── tests/                            Vitest 50 项（含 6 项端到端，需 Python）
├── var/uploads/                      上传文件存储（gitignore，删除即重置）
├── 确定性计算层/                      三阶段引擎（223 项回归测试）
├── 数据资产/                          仅本地：模拟数据快照 + 原始数据备份（已 gitignore）
├── tools/bridge-smoke/               引擎桥接冒烟测试
├── 确定性计算层_监测参数清单与规范依据.md
├── 07/08/10/11 系列文档               可行性分析 / 阈值口径 / 开发推进 / 可视化指引
├── 方案与迭代note/
│   ├── 初步方案.md
│   └── 框架demo.md
├── skills/
│   ├── README.md
│   ├── .agents/
│   ├── parse-monitoring-data/scripts/inspect_file.py
│   ├── normalize-monitoring-data/
│   ├── evaluate-thresholds/scripts/{run_judgement,check_strictness}.py
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

已完成：

- ✅ 确认最小输入数据契约（见 `确定性计算层/pipeline/stage1_data_preparation/ingest.py`）。
- ✅ 确认阈值与规范适用规则（默认规范库 + 用户上传字段级覆盖）。
- ✅ 建设最小规范库（30 本规范索引 + GB 50497-2019 条文级阈值）。
- ✅ 跑通正常、超限、数据错误、弃权四类流程（**223 项回归测试** + 27 个模拟场景）。
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

待推进（**按优先级**）：

1. **⑥ 编排层**：Supervisor 路由、共享工程状态 Schema、审计回环与退回机制。
2. **鉴权与持久化**：上传与分析接口的用户鉴权、项目归属校验、运行记录落库；
   上传文件的 Supabase/对象存储适配器（当前仅本地文件系统）。
3. **其余六个 Skill 实体化**：`normalize-monitoring-data` / `retrieve-standard-evidence` /
   `retrieve-similar-cases` / `analyze-work-condition` / `render-daily-report` / `validate-report`。
4. **日报生成 Agent（独立实现，非本层）**：消费 `excavaguard.daily_report_input/v1` 载荷，
   按 GB 50497-2019 第 9.0.7 条组织日报章节。本层已完成接口预留，不再改动载荷契约。
5. **P2-1 温度补偿**：轴力类判据可能混入温度效应（已接入 `soil_temperature` 数据）。
6. **P1-3 工程条件交互补全**：缺什么提示补什么（目前页面已给出提示，但未做逐项引导）。
7. 部署与 CI。
6. P2-1 温度补偿（轴力类判据）。
7. 为其余六个 Skill 补充 `references/`、`scripts/` 和 `tests/`。
8. 定义共享工程状态 Schema，并把 `pipeline` 封装为可被 Skill 调用的能力。
9. 定义 Supervisor 的路由、重试和终止规则。
10. **日报生成 Agent（独立实现，非本层）**：消费 `excavaguard.daily_report_input/v1` 载荷，
    按 GB 50497-2019 第 9.0.7 条组织日报章节。本层已完成接口预留，不再改动载荷契约。
11. 增加审计 Agent 的退回机制。
12. 开发可视化 Demo 与前端。
13. 案例知识库（脱敏后）—— 可选，须先确认授权。

## 记忆维护规则

- 只记录已经确认且后续仍有价值的信息。
- 新决策应写明日期，并修改对应的旧结论，避免同时保留互相冲突的描述。
- 已完成事项从“待推进事项”移入“当前状态”。
- 技术选型经确认后补充具体版本和验证过的运行命令。
- 架构发生变化时，同时更新 `AGENTS.md`、`方案与迭代note/框架demo.md` 和相关 `SKILL.md`。
- 不写入密码、Token、个人身份信息、未经脱敏的工程数据或大段运行日志。

## 决策记录

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
  - 操作手册 `11_可视化测试指引.md`（启动、四步操作、三个验证点、常见问题、API 替代方式）。
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
  产出 `08_阈值口径统一说明.md`（含远程替换全文）。**远程同步未执行**（需授权）。
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
- **RAG 暂缓**：本项目当前不做 RAG，`AGENTS.md` 的 RAG 章节保留为后续设计约束。

### 2026-09-22

- 项目英文名确定为 `ExcavaGuard`。
- 项目采用 Skill 与 RAG 作为底层能力，但比赛展示增加多 Agent 协作。
- 多 Agent 采用 Supervisor、数据治理、判据与规范、风险归因、报告交付和审计六类角色。
- 暂不创建传统后端代码脚手架，优先完善 Skill、Agent、RAG 和项目文档结构。
- GitHub 远程仓库确定为 `https://github.com/abreeezol/ExcavaGuard.git`。
