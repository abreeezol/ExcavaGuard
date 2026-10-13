# RAG 目录

本目录记录 ExcavaGuard 的 RAG 接入合同。仓库当前包含经提交记录声明已完成授权决策的
规范 OCR 文本、条文切片、ChromaDB 向量库和本地 BGE 模型；重新分发或公开部署前仍须
核验并留存授权范围。工程案例与监测数据不得在未脱敏、未授权时进入知识库。

## Provider 架构

规范证据通过 `src/server/evidence/` 中的统一接口检索：

```text
retrieve-standard-evidence Skill
                ↓
     StandardEvidenceRetriever
          ↙              ↘
      Pinecone       本地 loopback HTTP
```

`retrieve-standard-evidence` 已提供服务端 runner，负责参数校验、无结果弃权、
非现行证据拦截和查询轨迹；它不执行条文语义裁决或报告生成。案例检索合同将在
`retrieve-similar-cases` 实现时单独定义。

## 本地 HTTP 合同

本地 sidecar 必须实现：

```text
POST /api/evidence/search
Content-Type: application/json
```

请求示例：

```json
{
  "query": "测试监测项适用什么规范",
  "filters": {
    "standard_versions": ["demo-2026"],
    "monitoring_item": "测试监测项",
    "excavation_safety_level": "demo",
    "region": "测试区域",
    "effective_status": "active"
  },
  "top_k": 3
}
```

响应示例中的内容仅用于接口测试，不代表真实工程要求：

```json
{
  "evidence": [
    {
      "id": "std-demo-2026-8.0.1",
      "text": "仅用于测试的规范条文占位文本。",
      "metadata": {
        "standard_name": "测试规范",
        "standard_version": "demo-2026",
        "clause": "8.0.1",
        "source_location": "测试页 1",
        "applicability": ["仅用于自动化测试"],
        "effective_status": "active",
        "monitoring_item": "测试监测项",
        "excavation_safety_level": "demo",
        "region": "测试区域"
      },
      "score": 0.91,
      "matched_terms": ["测试监测项"]
    }
  ]
}
```

约束：

- 地址只允许 `localhost`、`127.0.0.1` 或 `::1`。
- `id` 必须在知识库版本内稳定，不能按每次查询随机生成。
- 规范名称、版本、条文号、原文、来源位置和适用条件缺一不可。
- 无命中时返回 `{"evidence":[]}`，不得补造条文。
- 非 2xx、非法 JSON 或字段不完整会被主应用拒绝。
- 错误响应不得包含规范全文、查询凭证、文件路径或密钥。

`source/server.py` 现已实现该合同；旧 `GET /api/search?q=...` 保留给历史原型页面。
新接口不调用历史原型的判定或报告生成路径。

启动本地 Provider：

```bash
.venv/bin/python -B source/server.py --port 8600
```

服务启动时用 Node 运行现有 `preparePineconeImport()`，生成可审计条文清单，不访问云端。
需要已安装 Node 依赖和仓库 `.venv/` 的 RAG 依赖。启动期预加载模型，首启可能较慢；
`GET /api/evidence/health` 返回 `{"ready":true}` 后再发起 Next.js 查询。

仅在希望切换本地检索时配置：

```env
RAG_PROVIDER=local
LOCAL_RAG_BASE_URL=http://127.0.0.1:8600
LOCAL_RAG_TIMEOUT_MS=10000
```

当前在线配置保持有效，兼容修复不强制切换 Provider。浏览器通过 Next.js 服务端
Retriever 查询本地服务，不持有底层凭证。前端证据展示与三 Agent 执行器仍待串联。

实现要点：

- BGE 和既有 8,698 条 Chroma 向量不重建；PersistentClient 仅打开
  `var/rag/chroma_db/` 运行副本，首次使用自动复制发布基线；
- 完整来源的候选 ID 复用在线清单，先按版本/生效状态过滤，再在这些 ID 内检索；
- 状态清单每次查询重新读取；未登记的地区/测项/等级不能根据文本猜测；
- 无命中返回空列表；模型、清单或来源正文不完整时显式失败；
- 模型只从本机加载，不回退联网下载；不写入 `data/chroma_db/`。

验证：

```bash
.venv/bin/python -B -m unittest discover -s source/tests -v
# 服务启动后，显式运行真实模型/向量库/Next.js 合同验收：
EXCAVAGUARD_TEST_LOCAL_RAG=1 npx vitest run tests/local-rag-live.test.ts
```

2026-10-13 实跑：Python 8 项通过；真实 Next.js 本地 Provider 3 项通过。
检索“监测预警值应由基坑工程设计方确定”命中 GB 50497-2019 第 8.0.1、
8.0.5、8.0.4 条，返回稳定证据 ID 和完整来源元数据。

## Pinecone 在线索引

在线索引使用 Pinecone integrated embedding。模型与语义文本字段分别由
`PINECONE_EMBED_MODEL`、`PINECONE_TEXT_FIELD` 配置；写入和查询均发送文本，
不在应用侧另行生成查询向量。当前目标索引使用 NVIDIA `llama-text-embed-v2`
和 `text` 字段。已有本地 BGE 向量不能直接复制到该索引，也不能与在线模型向量混用。

导入前先运行：

```bash
npm run rag:prepare
```

该命令不访问云端，只在 `var/rag/` 生成：

- `pinecone-records.jsonl`：候选在线记录；
- `pinecone-import-report.json`：来源映射、排除项、生效状态和冲突审计报告。

当前资产会形成 7,180 条候选记录：项目文件、无条文号切片、超过本地构建器 420 字符
上限的切片和同一规范的非首选 OCR 副本不会进入索引。创建索引时显式配置
`truncate=NONE`，避免超长正文被静默截断为不完整证据。`rag/standard-status.json`
中任何规范仍为 `unknown`，或未填写复核人和复核时间时，真实上传一律拒绝。
当前 29 个规范编号均已由项目团队人工复核并标记为 `active`。

状态清单与 `.env.local` 均确认后，导入已有索引：

```bash
npm run rag:import
```

仅在索引尚不存在并明确同意创建云资源时使用：

```bash
npm run rag:import -- --create-index
```

创建时启用删除保护，按 96 条顺序批量 upsert；瞬时失败按指数退避最多尝试 5 次。
重复执行使用稳定 chunk ID 覆盖同一记录，可在中断后重跑。命令不会打印 API key
或远端错误正文。

### 记录字段

导入清单统一使用本地字段 `chunk_text`，上传时映射到 `PINECONE_TEXT_FIELD`。Pinecone
中每条规范记录至少包含：

- `evidence_kind=standard`
- 配置指定的 integrated embedding 文本字段（当前为 `text`）
- `standard_name`
- `standard_version`
- `clause`
- `source_location`
- `applicability`（字符串数组）
- `effective_status`
- `standard_code`
- `source_category`
- `source_name`
- `registry_relevance`
- 可选的 `monitoring_item`、`excavation_safety_level`、`region`

Pinecone record ID 直接使用现有稳定 chunk ID。`source_location` 指向
`data/ocr_text/<分类>/<来源>.txt#chunk=<id>`；没有可靠页码时不补造页码。
`monitoring_item`、基坑等级和地区当前不从正文猜测，因此现有记录不包含这些可选字段。
integrated dense retrieval 不提供词项命中信息，统一证据输出中的 `matched_terms` 返回空数组。
更换 integrated embedding 模型时必须新建或重建索引。rerank 模型尚未确定。

## 资产边界

当前已入库资产：

- `data/ocr_text/`：30 份规范/项目文本；
- `data/chunks.jsonl`：8,698 个唯一切片；
- `data/chroma_db/`：8,698 条 512 维 cosine 向量；
- `models/bge-small-zh/`：本地 Embedding 模型，权重由 Git LFS 分发。

以下内容仍不得进入主代码仓：

- 未确认再分发授权的新规范原文及其派生产物；
- 未脱敏、未授权的工程案例和监测数据；
- 密钥、访问令牌和 Pinecone 连接凭证。

检索实现上线前仍需验证版本有效性、适用范围、来源定位、无结果行为和引用准确率。证据不足或冲突时，上层 Skill 必须主动弃权。

当前 `excava-guard / standards-v1` 已导入 7,180 条记录；远端记录数与本地清单一致，
真实语义查询返回的正文和来源元数据已逐字段比对通过。Supervisor/API 尚未调用该 Skill，
正式报告场景的引用准确率评测也尚未完成。
