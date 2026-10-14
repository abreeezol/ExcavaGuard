# ExcavaGuard

面向基坑监测工程师的 AI 监测日报助手。采用 Next.js 单体全栈：规则主判、RAG 举证、模型表达，工程师负责复核与签发。

**确定性计算层已接通。** 可以上传监测数据与用户规范，运行「阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对」并查看逐测点判定、生效规范来源与待复核项。可视化操作见 `方案与迭代note/11_可视化测试指引.md`。

三 Agent 首版已收敛为 Supervisor、报告交付与独立审计。Supervisor 的共享状态、
确定性路由、两轮退回、预算和失效规则已由同步执行器串联；报告/审计 Skill 可生成并
审计 Excel + 两份 Markdown 三件套。八个业务 Skill 中已有六个具备可调用实现。
工作台现已接通本地运行持久化、历史恢复、三 Agent 轨迹、三件套下载及人工接受/
退回/拒绝。接受仅记录草稿复核，不等于工程签发。

## 本地启动

已在 macOS arm64、Node.js `26.3.1`、npm `11.16.0` 下验证。`.nvmrc` 固定本次验证的 Node 版本；使用 nvm 时先执行 `nvm use`。

```bash
npm ci
npm run dev
```

打开 <http://localhost:3000>；可视化测试工作台在 <http://localhost:3000/workbench>。端口被占用时可使用 `npm run dev -- --port 3001`。

**前置条件：本机需有可用的 Python。** 确定性计算引擎由 Node 以子进程调用。
默认优先使用仓库 `.venv/bin/python`，再尝试 PATH 上的 `python3`、`python`；
三件套导出需要 `openpyxl`。想指定解释器就在 `.env.local` 写
`EXCAVAGUARD_PYTHON=<绝对路径>`。找不到时会明确返回 `[ENGINE_UNAVAILABLE]`。

## 目录

```text
src/
├── app/
│   ├── layout.tsx                  # 页面布局与元信息
│   ├── page.tsx                    # 工作台首页
│   ├── workbench/                  # 可视化测试工作台（page + client）
│   ├── globals.css                 # 响应式样式
│   └── api/
│       ├── health/route.ts         # 应用存活检查
│       ├── monitoring-files/       # 上传监测数据（含上传即解析报告）+ 示例数据
│       ├── standards/route.ts      # 上传用户规范（上传即校验阈值严格程度）
│       ├── runs/route.ts           # 三阶段分析；可显式开启报告/审计
│       └── report-artifacts/       # 三件套只读下载；URL 仅在审计通过后返回
├── components/                    # 服务端界面组件
├── contracts/                     # Zod 请求契约、角色和 Skill 标识
└── server/
    ├── config.ts                  # 按服务读取环境变量
    ├── api/respond.ts             # 统一错误响应与异常映射
    ├── storage/                   # local / Supabase 文件、运行与报告 Provider
    ├── agents/                    # 三 Agent 注册 + Supervisor + 同步执行器
    ├── evidence/                  # 规范证据检索接口与双 Provider 适配器
    ├── skills/
    │   ├── registry.ts            # 八个 Skill 的契约路径与实现状态
    │   ├── python-bridge.ts       # Node → Python 子进程桥接
    │   └── {parse-monitoring-data,evaluate-thresholds}/runner.ts
    └── integrations/              # LLM、Supabase、Pinecone 客户端入口
tests/                             # 接口边界、契约一致性、上传到分析端到端
skills/                            # 业务契约；scripts/ 下是引擎桥接脚本（Python）
rag/                               # RAG 接入合同与规范有效性审核清单
方案与迭代note/                     # 业务方案、架构和实现范围
确定性计算层/                       # 三阶段确定性引擎（242 项回归测试）
var/uploads/                       # 切换前的本地上传资产（gitignore，保留）
var/report-artifacts/              # 报告渲染临时目录及旧本地产物（gitignore）
var/runs/                          # 切换前的本地运行修订（gitignore，保留）
```

页面与 Route Handlers 共用一个 Next.js 应用。`src/server/` 使用 `server-only` 隔离，禁止从 Client Component 导入。`src/contracts/` 只放可共享的数据契约，不引用服务端模块。

**引擎不重写为 TypeScript。** 判定逻辑已有 242 项回归测试覆盖，二次实现会给「同一输入必得同一输出」这条确定性性质引入偏差；Web 侧只做协议转换。

## 依赖基线

| 用途 | 已安装版本 |
| --- | --- |
| Web 全栈 | Next.js 16.4.0、React 19.3.0 |
| 类型与校验 | TypeScript 6.0.3、Zod 4.6.5 |
| 模型适配 | AI SDK 7.0.136、OpenAI 适配包 4.0.91 |
| 持久化客户端 | Supabase JS 2.117.3 |
| 向量库客户端 | Pinecone 9.0.0 |
| 检查与测试 | ESLint 9.39.5、Vitest 4.1.11 |

版本以 `package-lock.json` 为准。TypeScript 7 尚不被当前 `eslint-config-next` 的解析器支持，因此固定 TypeScript 6。LangGraph.js、Embedding、rerank 和 DOCX 工具尚未引入。

## 服务端配置

需要接入外部服务时，将 `.env.example` 复制为 `.env.local`：

```bash
cp .env.example .env.local
```

| 服务 | 环境变量 | 当前行为 |
| --- | --- | --- |
| **确定性引擎** | `EXCAVAGUARD_PYTHON`、`EXCAVAGUARD_BRIDGE_TIMEOUT_MS` | 指定 Python 解释器与调用超时；不配则优先仓库 `.venv`，再尝试 PATH 上的 `python3`、`python` |
| **上传存储** | `EXCAVAGUARD_UPLOAD_ROOT`、`EXCAVAGUARD_STORAGE_PROVIDER` | `local` 或 `supabase`；当前本机已显式切至 Supabase |
| **运行存储** | `EXCAVAGUARD_RUN_ROOT` | 默认 `<仓库>/var/runs/<run_id>/<revision>.json`；不可变修订，原子发布 |
| **访问控制** | `EXCAVAGUARD_ACCESS_PASSWORD`、`EXCAVAGUARD_SESSION_SECRET`、`EXCAVAGUARD_PROJECT_ID` | 单操作者单项目；开发期无密码只允许本机；生产期必须配置密码和签名密钥 |
| LLM | `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` | 创建 OpenAI 兼容 Chat 适配器；不默认指定供应商或模型 |
| Supabase 公共连接 | `NEXT_PUBLIC_SUPABASE_URL`、`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 项目可达性已验证；publishable key 只具备 RLS 允许的低权限 |
| Supabase 服务端 | `SUPABASE_SECRET_KEY`、`SUPABASE_STORAGE_BUCKET` | 新式 secret key 仅供受保护服务端；上传、运行 revision 和报告 Provider 已接通 |
| RAG 选择 | `RAG_PROVIDER` | 必须显式选择 `pinecone` 或 `local` |
| Pinecone | `PINECONE_API_KEY`、`PINECONE_INDEX`、`PINECONE_TEXT_FIELD`、可选 `PINECONE_NAMESPACE` | 查询 integrated embedding 索引 |
| Pinecone 导入 | `PINECONE_CLOUD`、`PINECONE_REGION`、`PINECONE_EMBED_MODEL` | 仅供离线建索引/批量导入工具使用 |
| 本地 RAG | `LOCAL_RAG_BASE_URL`、`LOCAL_RAG_TIMEOUT_MS` | 调用 loopback 服务的统一证据接口 |

确定性引擎、上传存储和不附在线证据的基础日报链**不需要外部服务即可工作**。

客户端按需创建，不在页面渲染和构建时读取密钥或发送请求。配置缺失或格式不合法会抛出 `IntegrationConfigError`，错误不携带原始配置值。目标 Pinecone 索引已完成连接、配置、导入和查询验收；完整配置仍不代表 Supervisor 主链路已经接通。

Supabase 管理客户端会绕过 RLS，云端接入仍需用户身份、项目成员权限和文件归属设计。
当前访问边界只是单操作者单项目，不代表已实现 Supabase Auth 或多用户 ACL。
不要将任何密钥改为 `NEXT_PUBLIC_*`，也不要提交 `.env.local`。

Supabase 基础设施准备：

```bash
npm run supabase:check    # 当前配置和只读检查，不输出 key
npm run supabase:verify   # 迁移和 secret 配置后，执行可清理的真实写探针
```

迁移文件、控制台操作和状态说明见
[`supabase/README.md`](supabase/README.md)。`public_connected` 只证明项目 URL 与
publishable key 可达。当前基础设施写探针已达到 `infrastructure_verified`；
应用 Provider 真实纵向回归也已通过并显式切换。

## 规范证据 Provider

`src/server/evidence/` 提供统一的 `StandardEvidenceRetriever`，上层 Skill 不区分具体向量库：

- `PineconeStandardEvidenceRetriever`：调用 integrated embedding 的 `searchRecords` 文本检索，应用规范版本、监测项、基坑等级、地区和生效状态过滤。
- `LocalStandardEvidenceRetriever`：只接受 `localhost`、`127.0.0.1` 或 `::1`，调用 `POST /api/evidence/search`。
- `createStandardEvidenceRetriever`：根据 `RAG_PROVIDER` 选择实现，不会在本地模式读取 Pinecone 配置。

`retrieve-standard-evidence` 服务端 runner 已实现无命中弃权、非现行证据拦截、人工复核提示和查询轨迹。完整合同与 Pinecone 导入流程见 [`rag/README.md`](rag/README.md)。
`npm run rag:prepare` 可从现有资产生成 7,180 条候选记录和审计报告，不访问云端；
真实导入前必须在 `rag/standard-status.json` 完成 29 个规范编号的状态复核。
当前清单已由团队人工复核，目标索引 `excava-guard` 的 `standards-v1` namespace 已写入
7,180 条记录；真实语义查询和本地字段逐项比对通过。本地 sidecar 已实现
统一 HTTP 合同并完成真实 Next.js Retriever/Skill 验收。启动命令：

```bash
.venv/bin/python -B source/server.py --port 8600
```

模型在启动期预加载，`/api/evidence/health` 就绪后可使用本地 Provider；
只打开 `var/rag/chroma_db/` 运行副本，不写版本化知识资产。接口回归及真实验收命令见
[`rag/README.md`](rag/README.md)。
最终 7 天混合宽表已接入长表展开、累计量语义、来源留痕与日报聚合；
日报三件套的数据来源边界和交付验收见
[`final_test/README.md`](final_test/README.md)。

## 接口

### 已实现

- `GET /api/health`：返回 `{"status":"ok","service":"ExcavaGuard","stage":"scaffold"}`，只表示进程能响应。
- `GET /api/monitoring-files` / `POST /api/monitoring-files`：列出 / 上传监测数据（`multipart/form-data`，字段名 `file`）。
  上传成功后立即返回**解析报告**：编码、分隔符、列名映射、未识别列、缺失的必填列。
- `GET /api/monitoring-files/sample`：下载示例数据 CSV（6 列、中文表头、UTF-8 BOM）。
- `GET /api/standards` / `POST /api/standards`：列出 / 上传用户规范。
  **上传即校验严格程度** —— 凡比默认规范更宽松的项，连同默认值的规范名称与条文号一并返回。
- `POST /api/runs`：创建分析任务，默认返回日报接口载荷
  `excavaguard.daily_report_input/v1`；显式设置 `options.generate_report=true`
  时继续执行报告、审计和人工复核交接。
- `GET /api/report-artifacts/<draft_id>/<file_name>`：只读下载 Excel 或 Markdown
  草稿产物；必须绑定当前项目、当前已审计草稿，重新验证文件大小和 SHA-256。
- `GET/POST/DELETE /api/session`：访问状态、密码登录、退出，使用 HttpOnly 会话。
- `GET /api/runs` / `GET /api/runs/<run_id>`：最近 100 次摘要 / 完整请求与结果。
- `POST /api/runs/<run_id>/review`：`expected_revision`、完整 `draft_ref`、
  `decision`（accepted / needs_changes / rejected）、必填 `reason`。
  旧版本或重复决定返回 409；退回和拒绝关闭下载，不修改事实。
- `POST /api/runs/<run_id>/resume`：显式提交 `expected_revision`，只续跑已保存的
  Agent 检查点；不重置原预算。无检查点、活动任务或预算到期时需加载输入新建关联运行。

`POST /api/runs` 请求体：

```jsonc
{
  "project_id": "uuid",
  "monitoring_file_id": "uuid",
  "report_date": "YYYY-MM-DD",
  "standards_file_id": "uuid | null",     // 可选；不传则用默认规范库
  "context": {                             // 必填，引擎不做任何默认假设
    "safety_level": "一级",                // 一级 / 二级 / 三级
    "support_type": "地下连续墙",
    "excavation_depth_m": 20,              // 允许 null = 暂未提供（不会放宽判据，转为弃权）
    "post_slab_from": "YYYY-MM-DD | null",
    "design_values": { "support_axial_force": 1000 }
  },
  "project": { "name": "××基坑工程" },       // 可选，进入载荷
  "options": {
    "generate_report": true                  // 可选；默认 false
  }
}
```

开启报告链后，响应的 `agent_run.state` 保存 engineSnapshot、报告草稿、审计结果和轨迹；
正常完成时状态为 `awaiting_human_review`，`agent_run.downloads` 提供固定三件套地址。
这只表示确定性审计通过，仍不代表工程师已审核、已发布预警或已正式签发。
响应同时包含 `record`（版本化持久化记录）。原 API 默认只分析，工作台默认显式开启
报告链。页面「运行历史」打开已保存结果，「加载输入并新建关联运行」恢复原工程条件和
文件引用；修正后新建 `parent_run_id` 关联运行，原记录和复核理由保留。

本地启动绑定 localhost。可选密码至少 12 字符、签名密钥至少 32 字符；生产未配置
时业务 API 返回 `ACCESS_NOT_CONFIGURED`。会话 8 小时过期；更换密码或项目使旧会话失效。
历史无项目字段的上传文件只归入固定默认项目，切换配置不会自动转移文件。
运行目录和上传目录应一起备份；不要直接清理有引用的上传或报告文件。
上传索引写入锁若因进程崩溃遗留，先停止全部服务并确认没有写入，再清理
`var/uploads/index.json.lock` 空锁目录后重启。运行修订无需锁目录。

`POST /api/runs` 的返回：

| 状态码 | 错误码 | 含义 |
| --- | --- | --- |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 正文类型不是 `application/json` |
| 400 | `INVALID_JSON` | JSON 解析失败 |
| 400 | `INVALID_REQUEST` | 必填字段缺失、值无效或包含额外字段 |
| 404 | `FILE_NOT_FOUND` | 引用的监测文件或规范文件不存在 |
| 415 / 413 / 400 | `UNSUPPORTED_FILE_TYPE` / `FILE_TOO_LARGE` / `FILE_EMPTY` | 上传文件不合法 |
| 422 | `MISSING_FIELD` / `DATA_QUALITY` / `FILE_UNREADABLE` | 文件缺必填列 / 无有效数据行 / 读不出来 |
| 400 | `INVALID_STANDARD` | 用户规范结构不合法 |
| 503 | `ENGINE_UNAVAILABLE` | 找不到 Python 解释器或引擎脚本 |
| 500 | `ENGINE_NOT_FOUND` / `ENGINE_ERROR` | 引擎目录不完整 / 引擎运行报错（附 `engine_code`） |

`payload` 中 `risk_level = "未知"` 表示**弃权，不是「安全」**，对应条目会进入 `review_queue`。

### 尚未实现

- **多用户身份与权限**：当前只有单操作者密码会话和单项目隔离，未实现用户注册、
  项目成员权限或 Supabase Auth。
- **既有本地资产迁移**：Supabase Provider 已用于新上传、运行 revision 和三件套；
  `var/` 中已有本地测试历史保留，未自动复制或删除。
- **正式签发与归档**：接受/退回/拒绝和本地复核记录已接通，仍没有正式签发或工程档案系统。
- **异步编排与语义审计**：已保存检查点并支持原预算内显式续跑；未实现异步 worker、
  自动恢复、Supervisor 内规范证据检索和独立模型语义审计。

## 开发检查

```bash
npm run check       # ESLint、路由类型生成、TypeScript、Vitest
npm run build       # 生产构建，产物在 .next/
npm start           # 运行已经构建的应用
```

`npm test` 运行固定测试，`npm run test:watch` 用于开发。测试覆盖：协议边界（媒体类型、非法 JSON/字段/日期、闰日）、上传边界（非 multipart、缺 `file`、不合法规范结构）、示例数据结构、服务配置缺失、错误不回显密钥、三 Agent 角色白名单、Supervisor 路由/失效/两轮退回/预算、Skill 契约一致性，以及两个规范证据适配器的统一结构、过滤和失败边界。

`tests/upload-and-run.test.ts` 是**端到端**用例（上传 → 解析 → 分析 → 宽松阈值 → 缺 H 弃权），需要 Python；找不到解释器时整个 suite **自动跳过**，其余用例不受影响。

验收（更新至 2026-10-14）：`npm run check` 105 条测试通过，3 条 local-RAG 与
1 条 Supabase Provider live 测试默认跳过；已覆盖 15 条 Agent Runtime/Executor、8 条上传/纵向
端到端（含最终 85 通道宽表）、12 条持久化/访问边界及 6 条报告/审计 Skill 用例。
`npm run build` 生成 13 条路由；浏览器验证历史恢复、退回、关联重跑、轨迹、下载与接受。
`npm run supabase:test` 另有 1 条真实云端纵向验收通过并自动清理测试资产。
引擎侧历史验收为 242 项回归测试、27 个模拟场景和日报契约校验通过。

在限制写入用户目录的沙箱内，Next.js 命令可添加 `CI=1 NEXT_TELEMETRY_DISABLED=1`，使其配置缓存落在项目 `.next/cache/`。例如 `CI=1 NEXT_TELEMETRY_DISABLED=1 npm run build`。

当前依赖审计存在 5 条开发依赖高危告警，均来自 Next.js ESLint 插件的 `fast-glob → micromatch → braces` 链；npm 当前未给出兼容修复方案。不要执行会将 Next.js ESLint 配置降到 14.x 的 `npm audit fix --force`。本次 `npm audit --omit=dev` 为 0 条告警；后续依赖升级仍需重新核验。

## 后续实现顺序

1. ~~确认 CSV 字段、单位、方向、项目阈值和规则来源~~ ✅ 已完成（`确定性计算层/09_用户数据文件契约.md`）。
2. ~~实现解析、标准化、阈值判断的确定性 Skill~~ ✅ 已完成（`skills/<name>/scripts/`，Python 桥接）。
3. ~~接入真实 Supabase 项目、私有 bucket、上传/运行/报告 Provider~~ ✅；
   下一步接入 Supabase Auth 与多用户项目成员权限。
4. ~~建立 Supervisor 显式状态图、有限重试、失效规则与运行轨迹基础~~ ✅ 已完成。
5. ~~实现日报三件套、独立审计、同步 Agent 执行器与 API~~ ✅ 已完成；
   本地人工复核、访问边界、运行持久化和前端入口也已接通。

完整要求见 [AGENTS.md](AGENTS.md)、[项目记忆](memory.md)、
[开发推进记录](方案与迭代note/10_开发推进记录.md)、
[可视化测试指引](方案与迭代note/11_可视化测试指引.md) 和
[框架设计](方案与迭代note/框架demo.md)。系统只输出工程师待复核的草稿，
不自动发布预警或签发报告。

---

## 离线规范 RAG 知识库原型（`source/`）

与上方 Web 应用解耦的独立离线 RAG 原型：基于 `source/build_kb.py` 构建条款级向量库（bge-small-zh + ChromaDB），支持规范检索、合规核对与日报生成。

- 嵌入模型 `models/bge-small-zh` 随仓库提供（Git LFS），无需联网。
- 知识库原始规范（`data/ocr_text/`、`data/chunks.jsonl`、`data/chroma_db/`）已随仓库纳入版本管理（经权利人/作者授权决策后公开）；克隆后无需重新构建即可直接使用，或执行 `python source/build_kb.py --rebuild` 重建、`python source/server.py --port 8600` 启动本地服务。
- 完整用法、内置规范清单与 FAQ 见 [`source/README.md`](source/README.md)。
