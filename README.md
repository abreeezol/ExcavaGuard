# ExcavaGuard

面向基坑监测工程师的 AI 监测日报助手。采用 Next.js 单体全栈：规则主判、RAG 举证、模型表达，工程师负责复核与签发。

**当前为初始化工程。** 工作台可独立启动；六类 Agent 和八个业务 Skill 已建立注册关系，尚未执行分析。上传、鉴权、数据库表、知识检索、编排、日报生成与导出均待实现。

## 本地启动

已在 macOS arm64、Node.js `26.3.1`、npm `11.16.0` 下验证。`.nvmrc` 固定本次验证的 Node 版本；使用 nvm 时先执行 `nvm use`。

```bash
npm ci
npm run dev
```

打开 <http://localhost:3000>。初始页面不需要任何外部服务密钥。端口被占用时可使用 `npm run dev -- --port 3001`。

## 目录

```text
src/
├── app/
│   ├── layout.tsx                  # 页面布局与元信息
│   ├── page.tsx                    # 工作台空状态
│   ├── globals.css                 # 响应式样式
│   └── api/
│       ├── health/route.ts         # 应用存活检查
│       └── runs/route.ts           # 校验请求，明确返回尚未实现
├── components/                    # 服务端界面组件
├── contracts/                     # Zod 请求契约、角色和 Skill 标识
└── server/
    ├── config.ts                  # 按服务读取环境变量
    ├── agents/registry.ts         # 六类角色、职责与工具白名单
    ├── skills/registry.ts         # 八个 Skill 的契约路径与实现状态
    └── integrations/              # LLM、Supabase、Pinecone 客户端入口
tests/                             # 接口边界、配置与契约一致性测试
skills/                            # 原有业务契约；scripts/ 承载后续确定性实现
rag/                               # 知识资产占位，尚未导入规范或案例
方案与迭代note/                     # 业务方案、架构和实现范围
```

页面与 Route Handlers 共用一个 Next.js 应用。`src/server/` 使用 `server-only` 隔离，禁止从 Client Component 导入。`src/contracts/` 只放可共享的数据契约，不引用服务端模块。

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
| LLM | `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` | 创建 OpenAI 兼容 Chat 适配器；不默认指定供应商或模型 |
| Supabase | `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`SUPABASE_STORAGE_BUCKET` | 创建服务端管理客户端；尚无表结构、上传或持久化 |
| Pinecone | `PINECONE_API_KEY`、`PINECONE_INDEX` | 引用已有索引；尚无向量写入或检索 |

客户端按需创建，不在页面渲染和构建时读取密钥或发送请求。配置缺失或格式不合法会抛出 `IntegrationConfigError`，错误不携带原始配置值。当前未验证真实云服务连接；完整配置也不代表分析链路已经可用。

Supabase 管理客户端会绕过 RLS。后续启用任何业务接口前，需要实现用户鉴权、项目权限校验和文件所有权校验。不要将任何密钥改为 `NEXT_PUBLIC_*`，也不要提交 `.env.local`。

## 接口外壳

- `GET /api/health`：返回 `{"status":"ok","service":"ExcavaGuard","stage":"scaffold"}`，只表示进程能响应。
- `POST /api/runs`：接受 JSON，字段严格限定为 `project_id`、`monitoring_file_id`、`report_date`。前两者为 UUID，日期为有效的 `YYYY-MM-DD`。

`POST /api/runs` 的返回：

| 状态码 | 错误码 | 含义 |
| --- | --- | --- |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | 正文类型不是 `application/json` |
| 400 | `INVALID_JSON` | JSON 解析失败 |
| 400 | `INVALID_REQUEST` | 必填字段缺失、值无效或包含额外字段 |
| 501 | `FEATURE_NOT_IMPLEMENTED` | 格式合法，但业务链路尚未接入 |

当前所有请求均不会创建任务、调用模型、写数据库或输出报告；不会伪造运行 ID。完整工程状态仍见架构笔记，后续按 Skill 契约逐项实现，不能用空对象替代事实校验。

## 开发检查

```bash
npm run check       # ESLint、路由类型生成、TypeScript、Vitest
npm run build       # 生产构建，产物在 .next/
npm start           # 运行已经构建的应用
```

`npm test` 运行固定测试，`npm run test:watch` 用于开发。测试覆盖：有效请求的明确拒绝、非法 JSON/字段/日期、闰日边界、服务配置缺失、错误不回显密钥，以及角色白名单与原有 Skill 契约的一致性。

初始化验收（2026-10-09）：`npm ci`、Lint、类型检查、22 条测试和生产构建通过；开发与生产服务均已启动验证。浏览器已核验空状态、六类角色和页内导航；接口实测健康检查为 200、合法运行请求为 501。尚未执行真实 LLM、数据库或 RAG 联调。

在限制写入用户目录的沙箱内，Next.js 命令可添加 `CI=1 NEXT_TELEMETRY_DISABLED=1`，使其配置缓存落在项目 `.next/cache/`。例如 `CI=1 NEXT_TELEMETRY_DISABLED=1 npm run build`。

当前依赖审计存在 5 条开发依赖高危告警，均来自 Next.js ESLint 插件的 `fast-glob → micromatch → braces` 链；npm 当前未给出兼容修复方案。不要执行会将 Next.js ESLint 配置降到 14.x 的 `npm audit fix --force`。本次 `npm audit --omit=dev` 为 0 条告警；后续依赖升级仍需重新核验。

## 后续实现顺序

1. 确认 CSV 字段、单位、方向、项目阈值和规则来源，准备明确标记的演示样例。
2. 实现解析、标准化、阈值判断和报告校验的确定性 Skill；业务脚本保留在根目录 `skills/<name>/scripts/`。
3. 增加鉴权、Supabase 表结构与文件存储，完善共享工程状态。
4. 实现 Supervisor 显式状态图、有限重试、审计退回、人工确认与运行轨迹。
5. 接入规范和案例 RAG、服务端模型，完成基础草稿与导出。

完整要求见 [AGENTS.md](AGENTS.md)、[项目记忆](memory.md) 和 [框架设计](方案与迭代note/框架demo.md)。系统只输出工程师待复核的草稿，不自动发布预警或签发报告。
