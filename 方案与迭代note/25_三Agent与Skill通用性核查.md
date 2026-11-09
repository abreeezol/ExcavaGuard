# 三Agent与Skill通用性核查

> 后续处理：本文发现的问题已在26号重构记录中逐项处理；以下保留核查当时状态，不代表最新实现。

日期：2026-11-03。方式：检查真实运行调用链、注册表、契约、Python入口与模板依赖；本轮不修改业务代码，不新增隧道能力。已有基坑回归通过不等于已通过跨专业迁移测试。

## 结论

角色分工和大部分流程可以复用，但尚不满足“专业差异仅通过读取适配器切换”。现有适配器是能力登记、资产校验和部分配置加载入口，不是完整动态专业执行层。manifest中的代码路径大多用于存在性校验与哈希；实际runner仍调用固定脚本，Python仍导入原模块。

## 三Agent

| 角色 | 可复用部分 | 尚未外置的专业内容 |
|---|---|---|
| Supervisor | 状态机、预算、修订上限、故障终止、工程师反馈流转 | executor未从冻结场景向目录和Retriever传递adapterId；standard-review检索前缀、条件和相关性过滤仍是基坑；period-evidence六类分组及部分接受条件含基坑假设 |
| 报告Agent | 基于冻结事实和引用编写正文、事实占位符约束、工程师意见回应 | report-model中的FORM_RULES为A–F基坑分类；专业字段、部分事实一致性检查固定；模板渲染入口固定 |
| 审计Agent | 独立语义调用、文件事实绑定、引用/哈希校验及审查门禁 | 共用report-model的专业分类/提示；Python校验直接调用基坑build_report，缺少通用检查和专业检查扩展接口 |

工具白名单只表示允许的能力，不代表每个角色已能自主调用所有工具。retrieve-similar-cases只有契约，不能因列在审计白名单就声称已接通。

## 八个业务Skill

| Skill | 核查状态 | 需要调整 |
|---|---|---|
| parse-monitoring-data | 文件解析框架可复用，专业映射部分耦合 | inspect_file固定导入原file_reader；SKILL描述仍限定基坑；字段、别名和宽表语义应加载场景定义 |
| normalize-monitoring-data | 通用时序处理与专业字典混合 | normalize_records直接使用StandardsRegistry默认库构造别名，无场景参数传递 |
| evaluate-thresholds | 部分接入适配器，尚非通用专业执行 | 默认规则目录已由适配器加载；原始数据别名仍使用默认库；ProjectContext和risk_identifier仍是基坑模型；check_strictness未接适配器 |
| retrieve-standard-evidence | 检索接口可复用，专业路由未完成 | factory目前仅验证注册后沿用同一环境Provider；scope未用于选择独立端点/索引；executor默认加载基坑目录 |
| retrieve-similar-cases | 仅契约、未实现 | 定义通用案例查询接口，专业检索条件由适配器提供，不能标记为已验证通用实现 |
| analyze-work-condition | 仅契约、未实现 | 时间/位置关联和证据边界可共用；专业工况字段及相关性规则需适配，不能声称已实现 |
| render-daily-report | 工具职责通用，实现明显耦合基坑 | 固定service-v6模板、deep-pit脚本依赖、A–F分类/表头、封面深度字段；evidence_labels仍固定读取基坑目录 |
| validate-report | 通用核验机制＋基坑预期模型耦合 | 固定导入基坑build_report并重建预期；需保持通用事实/哈希/引用检查，再按适配器执行专业检查 |

## 关键证据

- `src/server/engineering-adapters/registry.ts`：schema将id/type/scope固定为基坑，核心字段固定3项；assets循环读取校验并哈希，不是程序插件分发。
- `src/server/skills/evaluate-thresholds/runner.ts:37`：读取manifest；第42行只将rules所在目录传入Python，第55行仍固定调用run_judgement.py。
- `src/server/agents/executor.ts:377`及382：createStandardEvidenceRetriever和readStandardCatalog均未传场景。
- `src/server/agents/standard-review.ts:66`：查询固定“基坑监测”；第68行固定“基坑工程”；相关性条件包含基坑/支护/地下水。
- `src/server/agents/period-evidence.ts`：GROUPS以及通用处置候选判断仍包含专业假设。
- `src/server/agents/report-model.ts:259`：FORM_RULES；第372行附近检查固定工程条件。
- `skills/normalize-monitoring-data/scripts/normalize_records.py:100`：StandardsRegistry()直接取默认名称。
- `skills/evaluate-thresholds/scripts/run_judgement.py:105`：长表别名映射仍取默认库；第284行创建基坑ProjectContext。
- `skills/evaluate-thresholds/scripts/check_strictness.py:111`：直接创建默认规范注册表。
- `skills/render-daily-report/scripts/report_adapter.py:18`：固定deep-pit实现；第221行固定FORM_NAMES。
- `skills/render-daily-report/scripts/report_artifacts.py:29`：固定附表名称；封面固定专业字段。
- `skills/render-daily-report/scripts/evidence_labels.py:16`：规范名称解析固定基坑目录。
- `skills/validate-report/scripts/validate_report.py:17`：直接从report_adapter导入build_report。
- `src/contracts/runs.ts:36`：请求工程条件仍为基坑固定schema。项目授权目录暂无类型/适配器版本绑定，不能从用户自由文本推断项目类型。

## 推荐改造顺序

1. **统一场景上下文。** 从后端项目绑定加载adapterId/version/配置，贯穿上传检查、标准化、计算、检索、生成和审计。不能仅靠模型读取提示，也不能仅相信请求自报类型。旧基坑项目兼容必须显式定义。
2. **外置专业配置。** 测项/单位/方向、专业核心字段、附表分组、检索词与相关性策略、报告章节与专业审计项。应结构化复用，避免TS/Python各维护一份不同分类。
3. **增加受控专业实现注册。** 复杂计算与专业规则使用服务端白名单handler，不从上传文档或任意路径加载可执行代码。配置仅选择受支持的实现。
4. **真正绑定RAG。** 通过受控连接标识选择专业索引/服务；项目补充库继续按项目隔离；证据必须检查专业和项目范围，不能只在快照上写scope。
5. **拆分通用核验与专业核验。** 数字、事实、引用、文件完整性固定共用；专业字段、表式、语义检查由适配器提供，不能用适配器设置绕过基础审计。
6. **建立第二场景验收。** 在相同Agent/Skill接口下测试一种隧道工法；加入“非A–F报告分类”“无基坑深度字段”“专业库隔离”“未知工法拒绝”“补充规范不跨项目”等样例。单场景回归不能证明多场景通用。

## 不应为了通用而改动的边界

冻结事实、不补造参数、引用来源、权限隔离、最多两轮修订、语义故障阻断和工程师最终确认继续属于通用强制约束。基坑规则可以保留在基坑专业模块中，无需把所有专业算法变成JSON；关键是通用执行器按适配器选择已验证专业实现。

本轮交付核查报告，不实施上述重构，不重新运行外部模型或远端RAG，不提交推送。
