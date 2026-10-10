# ExcavaGuard

面向基坑监测工程师的 AI 监测日报助手。采用 Next.js 单体全栈：规则主判、RAG 举证、模型表达，工程师负责复核与签发。

**确定性计算层已接通。** 可以上传监测数据与用户规范，运行「阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对」并查看逐测点判定、生效规范来源与待复核项。可视化操作见 `11_可视化测试指引.md`。

仍待实现：鉴权与项目归属校验、运行记录持久化、上传文件的对象存储适配器、Agent 编排层、日报生成与导出。八个业务 Skill 中已有两个（`parse-monitoring-data`、`evaluate-thresholds`）具备可调用实现。

## 本地启动

已在 macOS arm64、Node.js `26.3.1`、npm `11.16.0` 下验证。`.nvmrc` 固定本次验证的 Node 版本；使用 nvm 时先执行 `nvm use`。

```bash
npm ci
npm run dev
```

打开 <http://localhost:3000>；可视化测试工作台在 <http://localhost:3000/workbench>。端口被占用时可使用 `npm run dev -- --port 3001`。

**前置条件：本机需有可用的 Python。** 确定性计算引擎是 `确定性计算层/pipeline/` 下的纯标准库 Python 代码，由 Node 以子进程调用。默认依次尝试 PATH 上的 `python3`、`python`；想指定解释器就在 `.env.local` 写 `EXCAVAGUARD_PYTHON=<绝对路径>`。找不到时会明确返回 `[ENGINE_UNAVAILABLE]`，不会假装成功。

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
│       └── runs/route.ts           # 创建分析任务，返回日报接口载荷
├── components/                    # 服务端界面组件
├── contracts/                     # Zod 请求契约、角色和 Skill 标识
└── server/
    ├── config.ts                  # 按服务读取环境变量
    ├── api/respond.ts             # 统一错误响应与异常映射
    ├── storage/                   # 上传文件存储（本地文件系统实现）
    ├── agents/registry.ts         # 六类角色、职责与工具白名单
    ├── evidence/                  # 规范证据检索接口与双 Provider 适配器
    ├── skills/
    │   ├── registry.ts            # 八个 Skill 的契约路径与实现状态
    │   ├── python-bridge.ts       # Node → Python 子进程桥接
    │   └── {parse-monitoring-data,evaluate-thresholds}/runner.ts
    └── integrations/              # LLM、Supabase、Pinecone 客户端入口
tests/                             # 接口边界、契约一致性、上传到分析端到端
skills/                            # 业务契约；scripts/ 下是引擎桥接脚本（Python）
rag/                               # 知识资产占位，尚未导入规范或案例
方案与迭代note/                     # 业务方案、架构和实现范围
确定性计算层/                       # 三阶段确定性引擎（223 项回归测试）
var/uploads/                       # 上传文件存储（gitignore，删除即重置）
```

页面与 Route Handlers 共用一个 Next.js 应用。`src/server/` 使用 `server-only` 隔离，禁止从 Client Component 导入。`src/contracts/` 只放可共享的数据契约，不引用服务端模块。

**引擎不重写为 TypeScript。** 判定逻辑已有 223 项回归测试覆盖，二次实现会给「同一输入必得同一输出」这条确定性性质引入偏差；Web 侧只做协议转换。

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
| **确定性引擎** | `EXCAVAGUARD_PYTHON`、`EXCAVAGUARD_BRIDGE_TIMEOUT_MS` | 指定 Python 解释器与调用超时；不配则依次尝试 PATH 上的 `python3`、`python` |
| **上传存储** | `EXCAVAGUARD_UPLOAD_ROOT`、`EXCAVAGUARD_STORAGE_PROVIDER` | 存储根目录（默认 `<仓库>/var/uploads`）与 provider（当前仅 `local`） |
| LLM | `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` | 创建 OpenAI 兼容 Chat 适配器；不默认指定供应商或模型 |
| Supabase | `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`SUPABASE_STORAGE_BUCKET` | 创建服务端管理客户端；**尚无表结构与上传逻辑**，存储适配器未实现 |
| RAG 选择 | `RAG_PROVIDER` | 必须显式选择 `pinecone` 或 `local` |
| Pinecone | `PINECONE_API_KEY`、`PINECONE_INDEX`、可选 `PINECONE_NAMESPACE` | 查询已有索引；Embedding 函数由服务端显式注入 |
| 本地 RAG | `LOCAL_RAG_BASE_URL`、`LOCAL_RAG_TIMEOUT_MS` | 调用 loopback 服务的统一证据接口 |

确定性引擎与上传存储**不需要外部服务即可工作**，是当前唯一可端到端跑通的链路。

客户端按需创建，不在页面渲染和构建时读取密钥或发送请求。配置缺失或格式不合法会抛出 `IntegrationConfigError`，错误不携带原始配置值。当前未验证真实云服务连接；完整配置也不代表分析链路已经可用。

Supabase 管理客户端会绕过 RLS。后续启用任何业务接口前，需要实现用户鉴权、项目权限校验和文件所有权校验。不要将任何密钥改为 `NEXT_PUBLIC_*`，也不要提交 `.env.local`。

## 规范证据 Provider

`src/server/evidence/` 提供统一的 `StandardEvidenceRetriever`，上层 Skill 不区分具体向量库：

- `PineconeStandardEvidenceRetriever`：接收显式注入的查询 Embedding，应用规范版本、监测项、基坑等级、地区和生效状态过滤。
- `LocalStandardEvidenceRetriever`：只接受 `localhost`、`127.0.0.1` 或 `::1`，调用 `POST /api/evidence/search`。
- `createStandardEvidenceRetriever`：根据 `RAG_PROVIDER` 选择实现，不会在本地模式读取 Pinecone 配置。

完整本地 HTTP 合同见 [`rag/README.md`](rag/README.md)。两个适配器都要求稳定证据 ID、规范名称和版本、条文号、原文、来源位置及适用条件；旧版只有 `source/clause/content` 的响应会被拒绝。当前没有默认 Embedding 模型、本地 sidecar、规范资产或可供查询的生产索引，`retrieve-standard-evidence` Skill 仍为未实现状态。

## 接口

### 已实现

- `GET /api/health`：返回 `{"status":"ok","service":"ExcavaGuard","stage":"scaffold"}`，只表示进程能响应。
- `GET /api/monitoring-files` / `POST /api/monitoring-files`：列出 / 上传监测数据（`multipart/form-data`，字段名 `file`）。
  上传成功后立即返回**解析报告**：编码、分隔符、列名映射、未识别列、缺失的必填列。
- `GET /api/monitoring-files/sample`：下载示例数据 CSV（6 列、中文表头、UTF-8 BOM）。
- `GET /api/standards` / `POST /api/standards`：列出 / 上传用户规范。
  **上传即校验严格程度** —— 凡比默认规范更宽松的项，连同默认值的规范名称与条文号一并返回。
- `POST /api/runs`：创建分析任务，返回日报接口载荷 `excavaguard.daily_report_input/v1`。

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
  "project": { "name": "××基坑工程" }        // 可选，进入载荷
}
```

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

- **鉴权与项目归属校验**：上传与分析接口目前无用户身份校验，`project_id` 不会被校验是否存在。
- **运行记录持久化**：`run_id` 仅用于本次请求追溯，不写数据库。
- **对象存储**：上传文件用本地文件系统（`var/uploads/`）。声明 `EXCAVAGUARD_STORAGE_PROVIDER=supabase` 会直接报错并说明原因 —— 缺少 bucket 与元数据表，无法验证，因此不提供空壳实现。
- **日报正文**：本层只产出结构化载荷，不生成日报文件、不撰写结论与建议措辞。

## 开发检查

```bash
npm run check       # ESLint、路由类型生成、TypeScript、Vitest
npm run build       # 生产构建，产物在 .next/
npm start           # 运行已经构建的应用
```

`npm test` 运行固定测试，`npm run test:watch` 用于开发。测试覆盖：协议边界（媒体类型、非法 JSON/字段/日期、闰日）、上传边界（非 multipart、缺 `file`、不合法规范结构）、示例数据结构、服务配置缺失、错误不回显密钥、角色白名单、Skill 契约一致性（实现状态与脚本清单一致且脚本真实存在），以及两个规范证据适配器的统一结构、过滤和失败边界。

`tests/upload-and-run.test.ts` 是**端到端**用例（上传 → 解析 → 分析 → 宽松阈值 → 缺 H 弃权），需要 Python；找不到解释器时整个 suite **自动跳过**，其余用例不受影响。

验收（2026-10-10）：`npm run check` 50 条测试通过，`npm run build` 8 条路由全部生成；引擎侧 223 项回归测试、27 个模拟场景、日报契约校验全部通过。真实 HTTP 实测见 `10_开发推进记录.md` 第九节。

在限制写入用户目录的沙箱内，Next.js 命令可添加 `CI=1 NEXT_TELEMETRY_DISABLED=1`，使其配置缓存落在项目 `.next/cache/`。例如 `CI=1 NEXT_TELEMETRY_DISABLED=1 npm run build`。

当前依赖审计存在 5 条开发依赖高危告警，均来自 Next.js ESLint 插件的 `fast-glob → micromatch → braces` 链；npm 当前未给出兼容修复方案。不要执行会将 Next.js ESLint 配置降到 14.x 的 `npm audit fix --force`。本次 `npm audit --omit=dev` 为 0 条告警；后续依赖升级仍需重新核验。

## 后续实现顺序

1. ~~确认 CSV 字段、单位、方向、项目阈值和规则来源~~ ✅ 已完成（`确定性计算层/09_用户数据文件契约.md`）。
2. ~~实现解析、标准化、阈值判断的确定性 Skill~~ ✅ 已完成（`skills/<name>/scripts/`，Python 桥接）。
3. **增加鉴权、项目归属校验、运行记录表与对象存储适配器**，完善共享工程状态。
4. 实现 Supervisor 显式状态图、有限重试、审计退回、人工确认与运行轨迹。
5. 实现日报生成 Agent（消费冻结载荷）与导出；接入规范与案例 RAG、服务端模型。

完整要求见 [AGENTS.md](AGENTS.md)、[项目记忆](memory.md)、[开发推进记录](10_开发推进记录.md)、[可视化测试指引](11_可视化测试指引.md) 和 [框架设计](方案与迭代note/框架demo.md)。系统只输出工程师待复核的草稿，不自动发布预警或签发报告。

---

## 离线规范 RAG 知识库原型（`source/`）

与上方 Web 应用解耦的独立离线 RAG 原型：基于 `source/build_kb.py` 构建条款级向量库（bge-small-zh + ChromaDB），支持规范检索、合规核对与日报生成。

- 嵌入模型 `models/bge-small-zh` 随仓库提供（Git LFS），无需联网。
- 知识库原始规范（`data/ocr_text/`、`data/chunks.jsonl`、`data/chroma_db/`）受版权保护，已通过 `.gitignore` 排除，不进 public 仓库；本机运行请使用本地已授权的规范源，执行 `python source/build_kb.py --rebuild` 重建后再用 `python source/server.py --port 8600` 启动。
- 完整用法、内置规范清单与 FAQ 见 [`source/README.md`](source/README.md)。
