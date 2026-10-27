---
name: "project-standard-library"
description: "上传、停用和检索工程师确认的项目补充规范；需要为当前工程增加地方标准、行业标准或专项要求时调用，不写入公共知识库。"
---

# 项目补充规范库

## 触发与输入

- 上传使用 `POST /api/project-standards`：multipart `file`、`standard_name`、`standard_version`、`region`、`applicability`、`confirmed=true`。
- 工程标识仅从服务端访问会话取得，不能用客户端指定项目覆盖它。
- 支持20MB以内可搜索PDF、UTF-8 TXT/Markdown。PDF最多1000页，全文最多500万字符、10000切片；文字层缺失/乱码明确拒绝，提示OCR，不伪造原文。
- 工程师确认文件名称、编号、效力及工程适用范围后启用；确认并不代表每条要求均适用或已经执行。

## 执行与输出

1. 按页提取原文，按可识别条文号拆分，保留页码；无可靠条文号标为待复核，不能编造编号。使用中文二元词和SQLite FTS5/BM25进行本地检索，不发送全文到公共向量库。
2. 原文件BLOB、文档元数据、切片、FTS索引均保存到 `EXCAVAGUARD_PROJECT_STANDARDS_ROOT/<project_id>/standards.sqlite3`，默认 `var/project-standards/`。上传成功返回不可变 `document_id`、文件SHA-256、页数、切片数、未完整提取页码及启用状态。
3. 同项目相同内容及元数据重复上传幂等；同编号新文件自动替换启用来源。停用保留原文及历史版本；历史冻结引用仍可检索。
4. 新建运行自动选择当前工程全部启用文档；可通过 `project_standard_ids` 显式选择子集，`[]` 表示不选。运行保存实际ID与文档清单；续跑使用原清单，不重新扫描当前启用列表。
5. AI模式合并公共目录和本项目目录，保持逐规范与跨测项检索；同编号上传版本在检索中优先。模板模式只查询项目补充规范，不声明已检索公共库。已有数值引擎不受PDF候选影响。
6. `provider=project` 证据保留名称、编号、条文、页码、适用条件、project_id、document_id、content_sha256。规范名称和条文用于展示，内部ID用于审计。
7. 命中项目条文时，报告模型必须在分析、建议或附表分析中引用每份命中文档，否则有限重试后停止交付。渲染器为相关分类表保留补充依据，增加“项目补充要求核查”，无命中记为人工查证。

## 失败与边界

- 越权项目、非法ID、未确认文件、停用文档用于新运行、不可读PDF：拒绝或`INVALID_STANDARD`；不作为正常入库。
- 检索无结果不等于无新增要求；目录覆盖、缺失文字页和差异均转工程师核验。
- 不从自然语言PDF自动覆盖数值阈值、降低风险或声称已经符合规范。新增数值判据使用现有工程师上传JSON及严格度校验链路。
- 此专库为服务端独立本地数据库，即使其他业务使用Supabase，仍须单独挂载持久卷和备份。当前单操作者项目边界由 `EXCAVAGUARD_PROJECT_ID` 控制；改工程名称不是切换项目，不能宣称已有多租户权限。

## 验证

`npm run test:project-standards`：正常上传、幂等、条件过滤、无命中、非法输入、跨项目隔离、停用和冻结版本、真实Python报告与审计、AI角色集成（模型显式模拟）。

设置 `EXCAVAGUARD_TEST_STANDARD_PDF` 可额外验证真实标准PDF和最终三件套。真实模型验收另用 `tools/test/project-standard-live.mjs`，仅允许公开标准和人工合成监测，显式设置 `EXCAVAGUARD_TEST_PROJECT_STANDARD_LIVE=1`。
