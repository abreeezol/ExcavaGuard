# 隧道施工场景 · 规范 RAG 接入方案（待语料）

> 状态：**方案定稿，语料未接入**。本文只描述"怎么接"，不含任何条文与阈值。
> 规范文本与适用条件必须由项目方提供并确认现行性，禁止凭模型记忆补造条文。

## 1. 现有基坑链路（已被验证可用的形状）

| 环节 | 资产 / 工具 | 说明 |
|---|---|---|
| 规范原文 | `基坑智守项目相关规范/`（按 6 个类别分子目录） | 只读，不修改原始 PDF |
| 文本层 | `data/ocr_text/<类别>/*.txt` | 扫描件抽取，可文本层缺失 |
| 切片 | `data/chunks.jsonl`（8,702 行，8,698 条唯一） | 字段：`id / content / source / category / clause` |
| 本地向量库 | `data/chroma_db/`，collection `jikeng_norms`，512 维 cosine | 发布基线，运行须复制到 `var/rag/chroma_db/` |
| 本地检索服务 | `source/query_kb.py`、`source/server.py`（`POST /api/evidence/search`） | BGE-small-zh + Chroma |
| 在线检索 | Pinecone index `excava-guard` / namespace `standards-v1`（7,180 records） | integrated embedding，语义字段 `text` |
| 规范目录索引 | `确定性计算层/standards/default/规范库索引.json`（30 本，含 relevance 分级） | 由 `tools/build_standards_index.py` 生成 |
| 效力状态 | `rag/standard-status.json`（29 个编号人工复核） | 存在 `unknown` 时禁止真实上传 |
| 服务端适配 | `src/server/evidence/`（双 Provider 工厂） | 与知识库解耦 |

## 2. 隧道接入要做的事（按顺序）

### 2.1 建规范目录（需项目方提供文件）

```
隧道施工监测相关规范/
├── 监测类/
├── 施工与验收类/
├── 勘察与设计类/
├── 强制性通用规范/
├── 特殊条件（岩溶/瓦斯/高地应力/软土）/
└── 配套行业标准/
```

分类沿用基坑口径，便于复用 `build_standards_index.py` 的 `category` 字段。
画像 `tunnel.json` 中 `standards.index_file` 指向本目录生成的索引。

### 2.2 生成目录索引

`确定性计算层/tools/build_standards_index.py` 目前把规范根目录与输出目录**写死在文件头部**
（`SPEC_ROOT` / `OUT_DIR`），且 `RELEVANCE` 表是基坑专用的「规范编号 → 相关性/类别/适用范围」。
接入隧道需先做一处小改动（本次**未改**，避免交付未经验证的工具）：

1. 把 `SPEC_ROOT` / `OUT_DIR` 改为命令行参数（默认值保持现状，不影响基坑）；
2. 把 `RELEVANCE` 改为可外部覆盖（`--relevance-json`），隧道单独维护一份
   「编号 → relevance / category / scope_note」表；
3. 未登记编号会落到 `reference` 兜底，隧道接入时**不允许**依赖这个兜底蒙混过关 ——
   relevance 必须人工判定（primary / secondary / conditional / reference）。

每条索引需登记：`code / name / file_name / category / pages / text_extractable / relevance / scope_note`。
`scope_note` 要说明"这本规范管什么、能支撑哪类判据"。

### 2.3 抽取文本层并切片

`确定性计算层/tools/extract_pdfs.py` 同样使用写死路径，参数化方式与 2.2 一致。
切片产物 `data_tunnel/chunks_tunnel.jsonl` 必须：

- 与基坑切片**同 schema**（`id/content/source/category/clause`）；
- `clause` 字段尽量填到条文号（如 `5.3.2`、`表 5.3.2`），这是日报引用可读性的前提；
- 无条文号、超长、重复 OCR 来源的切片按基坑的门禁规则剔除（`tools/rag/` 已有实现）；
- **不得**混入基坑语料，也不得把基坑 `chunks.jsonl` 复制过来充数。

### 2.4 建向量集合

- 本地：`data_tunnel/chroma_db/`，collection 名 `tunnel_norms`（画像已声明）。
  运行副本仍须复制到 `var/rag/chroma_db_tunnel/`。
- 在线：新建 Pinecone namespace（如 `standards-tunnel-v1`），**不要**与
  `standards-v1` 混写；索引名可复用 `excava-guard`，但命名空间必须独立，
  避免基坑条文被当作隧道依据检索出来。

### 2.5 效力复核（硬门禁）

新增 `rag/standard-status-tunnel.json`，逐规范编号登记 `effective_status`
与 `reviewed_by / reviewed_at`。存在 `unknown` 时**禁止**执行真实上传，
与基坑门禁保持一致。

### 2.6 服务端切换

`src/server/evidence/` 的 Provider 工厂按场景画像的 `rag` 段取
`collection / pinecone_namespace`。当前代码仍读固定配置，
**这是唯一需要改 TypeScript 的地方，本次未改**（前端与 API 层暂缓，见核查表第 10 步）。

## 3. 检索期必须保留的约束（与基坑一致）

- 全目录覆盖：按索引中的**全部**规范编号逐本检索，不靠模型挑书目。
- 无命中、效力待核、候选预算截断必须逐条披露，不得写成"无此要求"。
- 候选条文不是已确认适用条文，**不替换**确定性判据；判据只来自阶段三的阈值库。
- 引用必须可解析到《规范名称》+ 编号 + 条文号，禁止把切片码写进正文。

## 4. 需要项目方提供

1. 隧道相关规范的正式文本（PDF/DOC），并说明各本是否现行、是否被替代；
2. 每本规范的适用范围（管哪些工法、哪些测项），用于填 `relevance / scope_note`；
3. 项目专项监测方案中"本项目实际执行的判据"，它与通用规范的差异必须以专项方案为准；
4. 是否允许把上述规范文本纳入仓库（授权与脱敏确认）。
