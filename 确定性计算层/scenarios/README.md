# 场景画像（Scenario Profile）

## 这是什么

三阶段引擎原本默认按「基坑工程监测」写死了一批假设：判据库在哪、条件维度叫什么、
比例限值除的是什么、监测项有哪些别名、日报走哪套附表。**场景画像**把这些假设搬到
JSON 里，让引擎按画像取值；画像没声明的仍走代码内置默认。

```
确定性计算层/scenarios/
├── scenario.py                    加载器 + 访问器 + 规范库工厂
├── jikeng.json                    基坑基线（取值与改造前的内置默认逐项一致）
├── tunnel.json                    隧道施工场景（status=active，判据库已按条文接入）
├── scenario_profile.schema.json   画像契约
├── tunnel_rag_plan.md             隧道规范 RAG 接入方案
└── tests/
    ├── test_scenarios.py          画像等价性 / 判据库接入 / 新增能力（92 项）
    └── test_tunnel_judgement.py   管理等级 / 收敛稳定 / 断面综合判定（64 项）
```

隧道判据库：`确定性计算层/standards/tunnel/thresholds_tunnel_gb50911_jtg3660.json`
（43 条规则 / 29 个测项 / 8 条危险报警条件，逐条带规范名与条文号）。
规范语料：`data_tunnel/ocr_text/`（4 本核心规范已 OCR，见 `方案与迭代note/24_...md`）。

## 怎么切换

| 方式 | 写法 | 适用 |
|---|---|---|
| 环境变量 | `EXCAVAGUARD_SCENARIO=tunnel` | 服务端整体切换 |
| 代码 | `run_pipeline(..., scenario=load_profile("tunnel"))` | 单次运行/测试 |
| 桥接协议 | `options.scenario = "tunnel"` | Node → Python 入口 |

未指定时默认 `jikeng`，即改造前行为。

## 画像能控制什么

| 段 | 作用 | 缺省（基坑） |
|---|---|---|
| `standards.default_dir` | 默认判据库目录 | `standards/default` |
| `standards.origin_display_*` | 结果里"依据来自哪"的显示名 | 「默认规范库（基坑智守项目相关规范）」 |
| `conditions.dimensions` | 判据匹配的工程条件维度 | 安全等级/支护形式/管线类型/道路类型/裂缝状态 |
| `conditions.specificity_dimensions` | 命中多条判据时的具体度排序 | 后 4 个维度 |
| `reference_lengths` | 比例限值除的参照长度 | `excavation_depth_m`（基坑设计深度 H） |
| `metric_aliases.extra` | 追加监测项简称 | 无 |
| `problem_categories.extra` | 追加问题类别 | 无 |
| `derived_metrics` | 差值型派生（断面收敛） | 无 |
| `section_judgment` | 断面级综合判定：是否启用、必测项、缺测是否否决"正常" | 关闭 |
| `report.*` | 日报模板版本、附表分组、是否可渲染 | 附录 A~G，`renderable=true` |
| `rag.*` | 知识库 collection / namespace | `jikeng_norms` / `standards-v1` |

**画像不含任何阈值数字。** 阈值只能来自 `standards/` 下的判据库，且必须带规范名称、
版本、条文号。

## 安全约束

1. `status=skeleton` 的画像不得产出工程结论 —— 缺判据的测项一律 `NO_APPLICABLE_RULE` 弃权，
   绝不因为"没超限"就判"正常"（回归里专门断言了这一点）。
   隧道画像现为 `active`（判据库已接入）；但仍有一批测项**故意留空**（规范未给数值控制值），
   这些测项依旧弃权，逐条原因写在判据库的 `note` 里。
5. 断面级判定只按**显式映射**归组测点，未归属的单独披露，不按点号前缀推断。
6. 收敛稳定性只回答"是否满足规范量化条件"，不替工程师决定停测。
2. 比例限值缺参照长度时，绝对量只能作为**上界**；实测未超上界 → 弃权（`MISSING_REF_LENGTH`）。
3. 差值型派生**必须显式给出点对**，系统不按点号前缀猜配对。
4. 日报表式未确认（`report.renderable=false`）时渲染直接拒绝，不沿用基坑附录表头拼接。

## 已验证命令

```bash
cd 确定性计算层
python -B pipeline/tests/test_pipeline_stages.py     # 244 项通过
python -B scenarios/tests/test_scenarios.py          # 92 项通过
python -B scenarios/tests/test_tunnel_judgement.py   # 64 项通过（管理等级/稳定性/断面判定）
python -B scenarios/tests/test_tunnel_report.py      # 32 项通过（附录D表式/三件套/审计）
cd ..
node tools/bridge-smoke/run_judgement.mjs            # 13 项通过

# 规范语料（需要 pymupdf；扫描件 OCR 需要 rapidocr-onnxruntime）
python -B 确定性计算层/tools/build_tunnel_corpus.py \
    --source-root "C:/Study/bisai/Hai AI Agent/隧道施工相关规范" \
    --out data_tunnel/ocr_text --manifest data_tunnel/corpus_manifest.json
python -B 确定性计算层/tools/ocr_scanned_norms.py \
    --source-root "C:/Study/bisai/Hai AI Agent/隧道施工相关规范" \
    --out data_tunnel/ocr_text --include "GB 50911-2013" --dpi 200
```

## 新增一个场景要做什么

1. 复制 `tunnel.json` 改 `id`（必须与文件名一致）、`name`、`status`；
2. 建 `standards/<id>/` 放判据库 JSON（`metrics` 段为必需），空判据也能跑，但会全部弃权；
3. 在判据库里逐条填 `cumulative_mm` / `cumulative_pct_ref` / `rate_mm_per_day` 等，
   每条必须带 `evidence.standard` + `evidence.clause`；
4. 补齐 `pending_inputs`，全部清空后才把 `status` 改为 `active`；
5. 跑 `scenarios/tests/test_scenarios.py` 与 `pipeline/tests/test_pipeline_stages.py`。
