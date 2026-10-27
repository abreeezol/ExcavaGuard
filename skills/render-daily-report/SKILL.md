---
name: "render-daily-report"
description: "将结构化事实、证据和受约束分析渲染为监测日报草稿。资料齐备并需要固定模板输出时调用。"
---

# 监测日报渲染

## 触发条件

- 数据解析、标准化和阈值判定已成功完成。
- 可用证据与归因结果已经结构化，或已明确记录弃权状态。
- 需要生成供工程师复核的固定格式日报草稿。

## 输入

> **上游契约（已冻结）**：确定性计算层通过 `build_daily_report_input()` 产出
> `excavaguard.daily_report_input/v1` 载荷，契约见
> `确定性计算层/contracts/daily_report_input.schema.json`，
> 消费前可用 `确定性计算层/tools/validate_daily_report_input.py` 校验。
> 本 Skill 由后续独立日报 Agent 实现；确定性计算层**不生成**日报正文与版式文件。

- `daily_report_input`：上述契约载荷，含 `project`（工程概况）、`summary`（整体汇总）、
  `items`（逐测点成果）、`alerts`（报警及以上）、`review_queue`（待人工复核）、
  `data_quality`（数据质量说明）、`standards_sources` 与 `disclaimer`。
- `project_info`：项目与监测日期等模板必填信息（可取自载荷 `project` 字段）。
- `normalized_records`：标准化监测记录。
- `judgments`：规则引擎输出的计算事实与规则 ID（载荷 `items[].checks` / `rule_id` / `evidence`）。
- `standard_evidence`：规范证据或明确的缺失状态（载荷 `items[].evidence` 与 `standards_sources`）。
- `work_condition_analysis`：工况分析或弃权结果。
- `template`：经批准的日报模板及版本。
- 服务端 `analysisSnapshot` 可携带 `excavaguard.report_narrative/v1`：
  报告 Agent 已校验并冻结的工况、分析、建议、局限与逐附表分析；正文中的
  `{{fact:路径}}` 只允许引用上游标量，段落 `evidence_ids` 必须属于本次证据快照。

## 输出

成功时返回：

- `report_draft`：按模板组织的日报草稿；
- `fact_bindings`：报告数字到结构化事实字段的映射；
- `artifacts`：三件套文件清单，固定包含日报 Excel、封面 Markdown 和附表及清单
  Markdown；每项带受控相对路径、SHA-256、字节数和工作表清单；
- `artifact_bindings`：Excel 单元格到冻结载荷事实字段的映射，包含源事实哈希和
  渲染值哈希；
- `citations`：条文与案例引用的证据 ID；
- `template_version`：所用模板版本；
- `review_required=true`：明确需要工程师复核；
- `trace`：渲染输入摘要与模板信息。

## 执行流程

1. 校验模板版本、项目必填信息和上游结果状态。
2. 只从结构化事实字段填充数字、单位、时间和超限状态。
3. 只引用带证据 ID 的规范或案例内容。
4. 将归因表述限制为与其可信等级相符的“可能相关”等措辞。
5. 对弃权项原样写入“信息不足，建议人工复核”。
6. 在 `var/report-artifacts/<draft_id>/` 生成
   `监测日报_<报告日期>_草稿.xlsx`、`监测日报_<报告日期>_草稿_封面.md` 和
   `监测日报_<报告日期>_草稿_附表及清单.md`。
7. Excel 只生成载荷中实际出现的附表 A～F；未提供巡视记录时不生成表 G，
   并在封面、待复核和来源说明中明确记录，禁止写成“巡视正常”。
8. 附表逐测点备注优先写入 `items[].evidence.standard` 与 `clause` 对应的规范编号
   和条文号；来源与预处理标记集中保留在封面及追溯说明中，不得用来源标记替代规范依据。
9. 附表 C～F 的逐测点行以“监测日期、孔号(点号)”开头，并分别绑定
   `items[].timestamp` 与 `items[].point_id`；字段缺失时显示 `—`，不得从名称猜测。
10. 将 `measurement_semantics`、`source_flags` 和
   `source_metadata.daily_aggregation` 原样纳入来源说明，不把时间平移、
   插值、重采样或末值保持描述为原始同步实测。
11. 标记为草稿并交给 `validate-report`，校验通过前不得作为正式报告交付。

## 当前实现

- 服务端 runner：`src/server/skills/render-daily-report/runner.ts`。
- 协议适配器：`scripts/render_daily_report.py`，直接消费冻结的
  `excavaguard.daily_report_input/v1`。
- 表式映射与模板经验来自 `skills/deep-pit-monitoring-report/`；该目录自带的计算、
  阈值重判和本地 RAG 路径不进入服务端主链。
- 产出结构化草稿、三件套文件和 Markdown 预览；事实字段与 Excel 单元格均带
  SHA-256 绑定，证据引用携带稳定 ID。
- 载荷未提供可唯一识别单位时显示 `—` 并加入复核缺口，不从监测项名称猜测单位。
- 当前批准模板为 `deep-pit-monitoring-report/service-v4`。直接复用团队
  `appendix_forms.py` 的表头、列和页脚；日报正文分工况、分析及建议、待复核、
  RAG 规范原文、人工签署五节，两份 Markdown 分别对应封面和其余工作表。
- 表 E 未提供高程基准时高程栏留空，原观测值保留在来源说明；裂缝长度与宽度分列、
  分通道记录，不套用彼此阈值。长条文逐段排版，保留完整命中原文。
- 本 Skill 负责渲染。实际 LLM 写作由 `src/server/agents/report-model.ts` 的
  `report-delivery` 调用完成，不在 Python 中重复调用模型。

## 失败与弃权边界

- 模板、项目必填字段、事实映射或上游关键结果缺失：以 `MISSING_FIELD` 或 `VALIDATION_FAILED` 弃权。
- 导出目录越界、文件写入失败或缺少 `openpyxl`：拒绝生成草稿，不返回残缺三件套。
- 报告数字无法绑定到结构化事实：拒绝渲染该结论。
- 引用缺少证据 ID 或适用状态不明：不生成规范性表述。
- 不自行计算数字，不补造证据，不自动签字，不使用“正式预警”“已确认原因”等越权措辞。

## 多周期渲染扩展（2026-10-27）

- 同一 Skill 同时接受独立的 `excavaguard.period_report_input/v1`，不修改冻结日报 v1。保留现有模板和报告 Agent 职责，不另建重复编报链。
- 周期三件套按 `监测周报|监测月报|监测区间报告_<起日>_<止日>_草稿` 命名。封面披露区间覆盖、阶段风险、未知和缺测、待核事项，以及补充规范候选的人工确认边界。
- A～F 附表展示每通道周期最严重的一条原观测，标注原日期；不得称为期末值。额外生成“周期统计”“每日变化”“周期逐日明细”工作表，统计数值和逐日数据均绑定 `period.*` 冻结事实路径。
- 模型可用 `{{fact:period.*}}` 引用白名单中的覆盖、通道和每日摘要标量；不让模型自行计算统计，也不把完整高频历史塞入模型。
- `extended_review` 保留查询状态、原文证据 ID、补充候选和缺口；未命中不能写成不存在额外要求。无现场工况或缺测须如实披露。
