# ExcavaGuard Agent 协作规范

## 项目概述

ExcavaGuard 是面向基坑监测场景的 AI 监测日报智能体。系统读取监测数据和施工工况，通过确定性规则完成数值计算与阈值判断，通过 RAG 提供规范和案例证据，通过多 Agent 协作完成数据治理、辅助归因、报告生成与独立审计。

系统只生成供工程师复核的日报草稿，不替代工程师发布预警、审核或签发正式报告。

## 当前阶段

项目处于「**确定性计算层已闭环，Web 入口已接通，上层编排层仍在设计**」的阶段。

### 已实现（截至 2026-10-10）

- `确定性计算层/`：三阶段流程 —— **阶段一 数据准备 → 阶段二 确定性计算 → 阶段三 规范比对**；
- 阶段一：数据接入与归一化（单位按量纲换算、日期解析、来源标识）、14 类噪音与缺失识别（只识别不修改）；
- 阶段二：累计值 / 本次变化量 / 变化速率 / 最小二乘趋势斜率，输入不足时弃权并给出明确弃权码；
- 阶段三：默认规范库（`基坑智守项目相关规范`，30 本规范索引 + GB 50497-2019 条文级阈值）
  + 用户上传规范接口（字段级覆盖，**用户未上传时不作任何特殊处理**），五级风险分级；
- 多风险模拟数据集 `data_simulated/`（S1~S27，27 个场景，57 测点，3,420 条记录，100% 场景覆盖，
  覆盖《监测参数清单与规范依据》§一 全部 25 项参数中的可测项，与规范库 22 个监测项一一对应）；
- 补充参数剖析 `tools/analyze_supplementary_params.py`（温度 / 不排水抗剪强度 Cu / SPT 击数 / 分层测压管水头，只读）；
- **用户数据文件契约**（`contracts/monitoring_input.contract.json`）：必填 5 列
  （测点/时间/项目/数值/单位），`baseline_value` / `previous_value` / `interval_days`
  **由阶段一按测点时序确定性派生**（显式提供的值优先，派生打 `*_DERIVED` 标记）；
  通用读取器 `file_reader.py` 支持编码探测（utf-8-sig/utf-8/gb18030/gbk/big5/latin-1）、
  中英文列名别名（88 条监测项别名 + 25 条方向别名）、CSV/TSV/Excel；
- 日报模块接口契约 `contracts/daily_report_input.schema.json`（`excavaguard.daily_report_input/v1`）
  + 校验工具 `tools/validate_daily_report_input.py`；
- **用户数据上传通道（⑤）**：存储层 `src/server/storage/`（本地文件系统，落盘名由 `file_id` 生成）、
  `POST /api/monitoring-files`（含上传即解析报告）、`POST /api/standards`（**上传即校验严格程度**）、
  `POST /api/runs`（真实三阶段分析）、`GET /api/monitoring-files/sample`（示例数据）；
- **Node → Python 引擎桥接**：`src/server/skills/python-bridge.ts` + `skills/*/scripts/*.py`
  （`inspect_file.py` / `run_judgement.py` / `check_strictness.py`），子进程协议，零引擎改动；
- **可视化测试工作台** `/workbench`（见 `11_可视化测试指引.md`）；
- 引擎回归测试 **223 项全部通过**（`python -B pipeline/tests/test_pipeline_stages.py`）；
  全栈检查 `npm run check` **50 项通过**（含 6 项端到端），`npm run build` 8 条路由全部生成。

### 尚未实现

- **编排层（⑥）**：Supervisor 路由、共享工程状态、审计回环均未实现；
- **鉴权与持久化**：上传与分析接口无用户鉴权、无项目归属校验；运行记录不落库
  （`run_id` 仅用于本次请求追溯）；上传文件用**本地文件系统**存储，Supabase 适配器未实现
  （缺 bucket 与元数据表，无法验证，故不提供空壳）；
- 八个业务 Skill 中仍有六个只有 `SKILL.md` 契约
  （`normalize-monitoring-data` / `retrieve-standard-evidence` / `retrieve-similar-cases` /
  `analyze-work-condition` / `render-daily-report` / `validate-report`）；
  已实现的两个是 `parse-monitoring-data`（解析检查）与 `evaluate-thresholds`（判定 + 严格度校验）；
- **温度补偿**未实现，轴力类判据可能混入温度效应（P2-1）；
- **日报生成**：由后续独立 Agent 实现。本层只产出结构化载荷（`build_daily_report_input()`），
  **不生成日报正文与版式文件**，不撰写结论与建议措辞；
- 部署与 CI；
- RAG 检索（**本项目暂缓**，见「RAG 约束」）。

> **已修复（原 P0-1）**：用户上传原始观测表不再 100% 弃权。
> 2026-10-10 实测：仅含 5 个必填列的 7 期数据 → 弃权 1/7，正确识别出 6 期危险报警。
>
> **已实现（原 P1-1）**：用户阈值宽松度校验 —— `limit_strictness.py`，
> 在 `upload_standard()` / `resolve_limit()` / `build_daily_report_input()` 三处接入，
> 检出更宽松时反馈具体差异并注明默认值的规范名称与条文号（**只反馈、不阻断**）。
> 载荷新增 `standard_override_warnings` 字段。
>
> **已修复（原 P1-2）**：缺 `excavation_depth_m` 时**不得**用绝对量限值替代 `min(绝对量, %H)`。
> 现改为：绝对量只作**上界**，实测值未超上界 → 弃权（`MISSING_H`）并降级为「未知」；
> 已超上界 → 超限结论必然成立，照常判定。`MISSING_H` 不再是死代码。
>
> **已验证（④）**：引擎与 Web 入口可打通 —— `skills/evaluate-thresholds/scripts/run_judgement.py`
> + `tools/bridge-smoke/`，Node 子进程调用 Python，13/13 通过（见 `10_开发推进记录.md`）。

任何 Agent 都不得把规划中的技术选型描述为已经实现，也不得把已实现的能力描述为尚未实现。

## 权威文档

开始工作前按以下顺序读取：

1. `AGENTS.md`：全局协作规则和安全边界；
2. `memory.md`：当前稳定决策、项目状态与待确认事项；
3. `确定性计算层_监测参数清单与规范依据.md`：参数清单、计算公式与规范依据（**参数查漏后的最新版**）；
4. `确定性计算层/02_三阶段流程与规范比对说明.md`：三阶段流程与判据细则；
5. `确定性计算层/04_日报模块接口契约.md`：日报交接契约（已冻结）；
6. `确定性计算层/05_参数查漏与补充分析.md`：参数查漏结论与补充参数画像；
7. `确定性计算层/06_上传数据到风险识别链路_目标实现度评估.md`：**目标实现度、关键差距与风险点**；
8. `08_阈值口径统一说明.md`：阈值来源的**唯一权威口径**与远程同步方案；
9. `确定性计算层/09_用户数据文件契约.md`：用户数据文件契约（列名/编码/派生规则）；
10. `10_开发推进记录.md`：①~⑤ 开发进度、P1-2 修复、交付物与待决事项；
11. `11_可视化测试指引.md`：**端到端可视化验证的操作手册**（启动、四步操作、三个验证点）；
12. `07_远程仓库对比与两项可行性分析.md`：本地与远程仓库的差异、打通路径与风险；
13. `方案与迭代note/初步方案.md`：业务目标和初步技术判断；
14. `方案与迭代note/框架demo.md`：Skill 编排和多 Agent 设计；
15. `skills/README.md`：Skill 目录约定；
16. 目标 Skill 下的 `SKILL.md`：具体能力契约。

当文档发生冲突时，以工程师最新明确确认的内容为准，并同步修正文档，禁止私自选择对实现最方便的解释。

## 项目结构

```text
ExcavaGuard/
├── AGENTS.md / memory.md                  全局规则与项目记忆
├── src/                             ← Next.js 16 全栈工程（2026-10-10 从远程合并）
│   ├── app/
│   │   ├── page.tsx                       日报工作台首页
│   │   ├── workbench/                     ← 可视化测试工作台（page + client）
│   │   └── api/
│   │       ├── health/route.ts            存活检查
│   │       ├── monitoring-files/route.ts  GET 列表 / POST 上传监测数据
│   │       ├── monitoring-files/sample/   示例数据 CSV
│   │       ├── standards/route.ts         GET 列表 / POST 上传用户规范（含严格度校验）
│   │       └── runs/route.ts              POST 创建分析任务（真实三阶段）
│   ├── components/                        服务端界面组件
│   ├── contracts/                         Zod 请求契约（含 monitoring-files.ts）
│   └── server/
│       ├── api/respond.ts                 统一错误响应与异常映射
│       ├── storage/                       上传文件存储（本地文件系统）
│       ├── skills/python-bridge.ts        Node → Python 子进程桥接
│       ├── skills/{parse-monitoring-data,evaluate-thresholds}/runner.ts
│       ├── agents/registry.ts             六类角色注册
│       ├── evidence/                      规范证据检索（双 Provider 适配器）
│       └── config.ts / integrations/      环境配置与外部客户端
├── tests/                                 Vitest（50 项，`npm run check` 全绿）
├── package.json / tsconfig.json / next.config.ts / vitest.config.ts / eslint.config.mjs
├── .env.example / .nvmrc / .gitignore
├── README.md / 项目介绍.html
├── var/uploads/                     ← 上传文件存储（已 gitignore，删除即可重置）
├── 确定性计算层/                    ← 已实现：三阶段确定性流程
│   ├── 01_数据清单与可用性评估.md
│   ├── 02_三阶段流程与规范比对说明.md
│   ├── 03_本次新增文件清单.md
│   ├── 04_日报模块接口契约.md
│   ├── 05_参数查漏与补充分析.md
│   ├── 06_上传数据到风险识别链路_目标实现度评估.md
│   ├── 09_用户数据文件契约.md
│   ├── pipeline/
│   │   ├── stage1_data_preparation/      阶段一 · 数据准备（含 file_reader.py）
│   │   ├── stage2_deterministic_calc/    阶段二 · 确定性计算
│   │   ├── stage3_standard_comparison/   阶段三 · 规范比对（含 limit_strictness.py）
│   │   ├── orchestrator.py               三阶段编排 + 日报接口
│   │   └── tests/                        223 项回归测试
│   ├── contracts/                        日报接口契约 + 用户数据文件契约
│   ├── standards/
│   │   ├── default/                      默认规范库（基坑智守项目相关规范，22 项监测项）
│   │   └── user_uploaded/                用户上传规范（默认空，不作提示）
│   ├── data_simulated/                   模拟数据集（与原始数据隔离）
│   ├── tools/                            只读分析与生成脚本（12 个）
│   ├── derived/                          派生结果
│   └── legacy/                           已废弃的旧阶段语义实现（留档）
├── 数据资产/                        ← **仅本地**（已 gitignore）：模拟数据快照 + 原始数据只读备份
├── tools/
│   └── bridge-smoke/                     ← 引擎桥接冒烟测试（Node → Python，13 项）
├── 确定性计算层_监测参数清单与规范依据.md
├── 方案与迭代note/
│   ├── 初步方案.md
│   ├── 框架demo.md
│   └── 链路口语化.md
├── skills/
│   ├── README.md
│   ├── .agents/
│   ├── parse-monitoring-data/
│   │   └── scripts/inspect_file.py       ← 解析检查桥接脚本
│   ├── normalize-monitoring-data/
│   ├── evaluate-thresholds/
│   │   └── scripts/                      ← run_judgement.py / check_strictness.py
│   ├── retrieve-standard-evidence/
│   ├── retrieve-similar-cases/
│   ├── analyze-work-condition/
│   ├── render-daily-report/
│   └── validate-report/
├── 07_远程仓库对比与两项可行性分析.md
├── 08_阈值口径统一说明.md
├── 10_开发推进记录.md
└── 11_可视化测试指引.md
```

每个业务 Skill 使用以下结构：

```text
<skill-name>/
├── SKILL.md
├── references/
├── scripts/
├── skills/
└── tests/
```

## 架构原则

- Agent 负责理解目标、规划步骤、调用 Skill、管理状态和处理冲突。
- Skill 负责执行边界明确、可测试、可复现的业务操作。
- RAG 负责提供带来源的规范和案例证据。
- 确定性程序负责数值计算、单位换算、阈值判断和一致性校验。
- LLM 只负责规划、解释和语言组织，不得改写结构化工程事实。
- 工程师负责最终预警、审核和报告签发。

规范判据的优先级高于案例经验。历史案例只能辅助解释原因，不能改变超限事实或降低风险等级。

## Agent 设计

当前规划包含一个 Supervisor 和五个专业 Agent：

- `Supervisor Agent`：任务规划、Agent 路由、共享状态管理、冲突处理和终止控制；
- `数据治理 Agent`：调用解析与标准化 Skill，决定数据是否可以进入分析；
- `判据与规范 Agent`：调用阈值判断与规范检索 Skill，绑定计算事实和规范依据；
- `风险归因 Agent`：调用案例检索与工况分析 Skill，给出候选原因和可信等级；
- `报告交付 Agent`：调用报告生成 Skill，只使用结构化事实生成草稿；
- `审计 Agent`：调用报告校验 Skill，从反方检查数字、引用、适用性和责任边界。

审计 Agent 发现问题后应退回对应责任 Agent，不得直接修改源事实。自动退回必须有次数上限，无法消解的冲突交给工程师。

## Skill 开发规范

每个 `SKILL.md` 必须包含：

- 合法的 YAML frontmatter；
- 唯一且稳定的 `name`；
- 同时说明“做什么”和“何时调用”的 `description`；
- 触发条件；
- 输入字段及约束；
- 输出字段及语义；
- 执行流程；
- 失败与弃权边界。

目录内容职责如下：

- `references/`：字段契约、规范元数据、示例和领域参考；
- `scripts/`：确定性解析、计算、转换与校验程序；
- `skills/`：当前 Skill 依赖的子 Skill；
- `tests/`：测试输入、预期结果和回归用例。

Skill 之间只传递结构化数据，不把自然语言摘要作为下游计算输入。修改输入输出字段时，需要同步更新调用方、测试和 `方案与迭代note/框架demo.md`。

## RAG 约束

> **范围说明**：本项目**暂缓** RAG 检索能力建设。确定性计算层明确不做 RAG，
> 阶段三的规范比对直接读取默认规范库的条文级阈值文件。
> 本节保留为后续若要引入检索能力时的设计约束，当前不作为实现要求。

- 规范知识必须保存规范名称、版本、条文号、原文、适用条件和来源位置。
- 案例知识必须保存工程特征、来源、可信等级、相似条件和差异项。
- 检索优先使用元数据过滤，再组合关键词检索和向量检索。
- 检索结果必须携带稳定的证据 ID。
- 不得伪造条文、页码、规范版本、案例来源或匹配分数。
- 未检索到证据时返回“信息不足”，不能依靠模型常识补造。
- 规范全文和工程案例进入仓库前，必须确认授权和脱敏要求。

## 工程安全边界

以下规则不可绕过：

- 阈值判据必须来自**现行规范条文**，并标注规范名称、版本、条文号与出处位置。
  禁止使用无出处的经验数字，禁止伪造条文。
- 规范条文阈值在用于真实工程前，**必须由基坑工程设计方确认**；
  GB 50497-2019 第 8.0.1 条明确「监测预警值应由基坑工程设计方确定」。
  用户上传的地方规程 / 项目专项方案按字段覆盖默认规范库，未覆盖字段继承默认库。
- 用户未上传规范时**不作任何特殊处理**：不报错、不告警、不提示缺失，直接使用默认规范库。
- **用户上传规范的严格度不得低于默认规范库**：若用户阈值宽于默认值，必须在结果中显著提示
  （flag `USER_LIMIT_LOOSER_THAN_DEFAULT`），不得静默采用而放宽判据。
  已实现：`limit_strictness.py`，在 `upload_standard()`（上传即反馈）、
  `resolve_limit()`（判定兜底）、`build_daily_report_input()`（载荷 `standard_override_warnings`）
  三处接入，**只反馈、不阻断**。
- **缺少基坑设计深度 H 时，不得用「绝对量限值」替代「min(绝对量, %H)」限值**。
  GB 50497-2019 表 8.0.4 规定累计值取两者较小值。已实现：缺 H 时绝对量只作**上界**，
  实测值未超上界 → 弃权（`MISSING_H`）且不得判为「正常」；
  已超上界 → 超限结论必然成立，照常判定。
- 模拟数据必须带 `data_origin = "simulated"` 标识、文件名含 `SIMULATED`、
  保留 `source_dataset` 溯源字段，写入独立目录，且与真实数据**分开统计**。
- 高严重度数据质量问题（孤立尖峰粗差、非数值、日期不可解析、单位不可识别、传感器漂移）
  的期次**不得参与风险判定**，一律弃权并转人工复核，禁止"带病判定"。
- 不自动修复未知单位、方向、测点映射或缺失字段。
- **上传文件的落盘名一律由 `file_id` 生成**，不使用用户提供的文件名（防路径穿越）；
  原始文件名只作元数据展示。存储 provider 未真正实现时**必须显式报错**，
  不得提供"看起来能跑"的空壳。
- 确定性计算层**只产出结构化载荷**（`excavaguard.daily_report_input/v1`），
  不生成日报正文与版式文件、不撰写结论与建议措辞；日报由后续独立 Agent 负责。
  载荷中 `risk_level = "未知"` 表示弃权，**不是"安全"**，必须转人工复核，禁止渲染为正常项。
- **引擎判定逻辑不得用 TypeScript 重写**。判定已有 223 项回归测试覆盖，
  二次实现会给「同一输入必得同一输出」这条确定性性质引入偏差；
  Web 侧只做协议转换（子进程调用 `skills/*/scripts/*.py`）。
- 不使用案例相似性证明因果关系。
- 不自动发布黄色、橙色或红色预警。
- 不生成自动签字、自动审核或已正式签发的表述。
- 不隐藏规范冲突、数据缺口、低可信结果或异常执行记录。
- 关键校验失败时停止输出报告成品，只返回错误和待确认项。

## 修改方式

- 优先做范围清晰的小改动，避免在一次任务中同时重构目录、契约和业务逻辑。
- 开始实现前先读取目标 Skill 的 `SKILL.md`。
- 新增顶层 Agent、Skill、RAG 数据集或共享状态字段时，先更新设计文档。
- 不在未确认技术栈前创建大型脚手架或引入生产依赖。
- 不修改原始规范和案例文件；清洗结果、索引和派生数据应存放在独立目录。
- 不提交密钥、访问令牌、个人信息或未经脱敏的工程数据。
- 不删除方案、证据或测试资产，除非用户明确要求。

## 测试要求

每个 Skill 实现后至少覆盖：

- 一条正常输入；
- 一条边界输入；
- 一条非法输入；
- 一条需要弃权的输入；
- 输出字段和错误码验证；
- 运行轨迹与证据 ID 验证。

计算类 Skill 必须使用人工可核验的固定样例，并验证全部中间值。检索类 Skill 必须验证来源、版本、适用性过滤和无结果行为。报告类 Skill 必须验证数字与结构化事实逐字段一致。

在项目提供正式构建、检查和测试命令前，不得臆造命令。新增工具链后，应将经过实际验证的命令补充到本文件。

### 已验证的命令（2026-10-10 实跑）

```bash
# --- 引擎（纯标准库 Python，无第三方依赖）---
cd 确定性计算层
python -B pipeline/tests/test_pipeline_stages.py                                # 223 项
python -B tools/run_simulated_validation.py                                     # 场景 27/27
python -B tools/run_combined_real_and_simulated.py                              # 真实 + 模拟合并
python -B tools/export_input_contract.py                                        # 导出数据契约
python -B tools/validate_daily_report_input.py --self-test                      # 日报契约校验
python -B legacy/thresholds_v1_阶段语义废弃/tests/test_threshold_loader.py       # 留档 57 项

# --- 桥接（纯 Node，无依赖）---
cd ..
node tools/bridge-smoke/run_judgement.mjs                                       # 13 项

# --- Web 全栈 ---
npm ci
npm run check                                                                   # ESLint + TypeScript + Vitest 50 项
npm run build                                                                   # 8 条路由
npm run dev                                                                     # http://localhost:3000/workbench
```

`npm run check` 中的 `tests/upload-and-run.test.ts` 需要 Python；
找不到解释器时该 suite **自动跳过**，其余用例不受影响。

## 完成标准

一项修改只有在以下条件满足后才算完成：

- 改动符合目标 Skill 的职责边界；
- 输入输出契约同步更新；
- 对应测试或测试样例已经补充；
- 没有引入未经确认的工程事实；
- 错误、弃权和人工确认路径均有定义；
- 相关方案文档和 `memory.md` 已按需更新；
- 最终回复准确说明已完成内容、未完成内容和验证结果。
