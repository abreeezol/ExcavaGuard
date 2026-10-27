---
name: "retrieve-standard-evidence"
description: "检索带来源与适用条件的规范条文证据。需要解释规则依据或核对规范适用性时调用。"
---

# 规范证据检索

## 触发条件

- 阈值或报告结论需要关联规范名称、版本、条文号和来源定位。
- 需要核验某监测项、工程条件或地区对应的适用条文。
- 不用于执行数值计算，也不凭检索结果自动作出安全判定。

## 输入

- `query`：非空检索问题，应包含监测项或待核验规则。
- `filters`：可选元数据过滤条件，如规范版本、监测项目、基坑等级、地区、生效状态。
- `limit`：可选返回数量，默认 3。
- 运行上下文必须配置规范证据检索器。

## 输出

成功时返回：

- `status = "success"`；
- `evidence`：证据列表，每项含稳定证据标识 `id`、条文文本 `text`、匹配分数 `score`、检索来源 `provider`、`matched_terms`，以及以下 `metadata`：
  - `standard_name`：规范名称；
  - `standard_version`：规范版本；
  - `clause`：条文号；
  - `source_location`：页码或其他稳定来源位置；
  - `applicability`：适用条件列表；
  - `effective_status`：`active`、`inactive` 或 `unknown`；
  - 可选的 `monitoring_item`、`excavation_safety_level` 和 `region`；
- `notice`：检索结果适用性须由专业工程师核验；
- `trace`：查询条件、命中数量和证据 ID。

弃权时返回 `status = "abstained"`、`code`、`message`、候选 `evidence`（如有）、
`notice` 和同结构 `trace`，不得把弃权结果当作确定依据。

## 执行流程

1. 确认规范检索器可用并校验查询文本。
2. 优先应用版本、监测项和适用条件等元数据过滤。
3. 执行检索并限制候选数量。
4. 保留原文、来源元数据、匹配分数和证据标识。
5. 将证据交给后续解释或报告流程，不改写规则引擎事实。

## 失败与弃权边界

- 未配置检索器或 Provider 调用失败：以 `EVIDENCE_UNAVAILABLE` 弃权。
- `query` 为空或参数无效：以 `INVALID_INPUT` 弃权。
- 未找到适用条文：以 `EVIDENCE_NOT_FOUND` 弃权，并明确不得作规范性结论。
- 证据版本失效、适用条件不明或多条证据冲突：以 `EVIDENCE_CONFLICT` 弃权并要求人工复核。
- 不伪造条文、版本、页码或来源，不把低相关命中表述为确定依据。

## 参考实现

- 服务端 runner：`src/server/skills/retrieve-standard-evidence/runner.ts`
- Provider 适配器：`src/server/evidence/`
- Pinecone 导入与元数据门禁：`tools/rag/`、`rag/standard-status.json`
- AI 日报模式由 `src/server/agents/executor.ts` 的 Supervisor 阶段调用本 Skill；
  证据只进入报告引用和语义审计上下文，不参与或改写确定性风险判定。

## 多日预警扩展核查（2026-10-27）

AI 报告模式保持原有 GB50497-2019 主题检索。周期载荷中，同点同测项至少两个不同日期达到预警及以上时，Supervisor 再调用本 Skill：

1. 按六类测项合并查询，追加连续异常、监测加密、复测、现场核查和应急处置要求；最多六组，每组最多8条候选。
2. 追加查询取消单一规范版本限制，保留 `effective_status=active`。来源必须来自当前配置的本地/Pinecone 知识库，保留条文原文、版本、出处、适用条件和查询轨迹。
3. 过滤失效、无关及缺少要求性语句的命中，与原检索证据 ID 比较，输出 `extended_review.checks[].additional_evidence_ids`；新增仅表示相对本次基线检索的补充候选，不表示法规新颁布。
4. 无命中、冲突或不适用必须保留缺口并转人工确认，不能得出“无额外要求”；服务不可用停止 AI 报告交付并保留检查点。
5. 不修改数值、限值或风险级别，不根据候选自动发布预警。未查询全网，也未实时确认规范更新；工程师负责最终适用性核查。

实现：`src/server/agents/period-evidence.ts`、`executor.ts`；扩展结果供报告 Agent 和独立审计共同使用。模板模式不调用 RAG，并在工作台提示该模式限制。
