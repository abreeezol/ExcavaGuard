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

适配器目前只提供检索基础设施，不执行条文适用性裁决、证据冲突处理或报告生成。案例检索合同将在 `retrieve-similar-cases` 实现时单独定义。

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

队友分支原有的 `GET /api/search?q=...` 和 `source/clause/content` 返回结构不满足该合同，需要在接入前调整。

## Pinecone 元数据

Pinecone 中每条规范记录至少包含：

- `evidence_kind=standard`
- `text`
- `standard_name`
- `standard_version`
- `clause`
- `source_location`
- `applicability`（字符串数组）
- `effective_status`
- `matched_terms`（字符串数组）
- 可选的 `monitoring_item`、`excavation_safety_level`、`region`

Pinecone record ID 作为稳定证据 ID。现有本地向量使用 `BAAI/bge-small-zh`、512 维；
若复用这些向量，Pinecone 索引必须采用 512 维 cosine，查询也必须使用相同模型和查询前缀。
更换 Embedding 模型时必须重建全部文档向量，禁止混用向量空间。rerank 模型尚未确定。

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
