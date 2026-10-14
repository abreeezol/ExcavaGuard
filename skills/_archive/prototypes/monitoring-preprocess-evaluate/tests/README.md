# 测试说明

运行主脚本需 Python 3.10+；确定性层（阶段 A）仅依赖标准库，无需 chromadb。
xlsx 输出依赖 openpyxl（缺失时仅产出 CSV，不阻断主流程）。

## 输出格式（对齐真实基坑监测日报）

- `附表E_格式化.csv` / `.xlsx`：列 = 初始高程, 本次高程, 上次高程, 本次变化, 累计变化, 变化速率, 编号, 点号, 备注。
  每测点按监测日展开为多行；`备注` 集中承载预警信息（预警等级 / 报警值 / 控制值 / 占报警值% / 超报警值 / 超控制值 / 规范依据(RAG)）。
- `附表F_格式化.csv` / `.xlsx`：列 = 长度(mm), 宽度(mm), 本次测试值, 单次变化, 累计变化, 变化速率, 点号, 形态, 备注。
- `evaluation.json`：含 `summary.level_counts`（三级：正常 / 黄色(需关注) / 红色(报警) / 未判定）、`analysis`（附表 E/F 的「简要分析及判断性结论」文本）、逐测点明细与 RAG 证据。

## 用例 1：内置 self-test（正常 + 边界）
```bash
python scripts/run.py --self-test
```
用内置 4 行样例验证累计/变化/速率与三级判定的最小可运行路径，输出 JSON 状态。

## 用例 2：基本样例（红色 + 弃权，覆盖正常/边界/弃权）
```bash
python scripts/run.py --csv tests/sample_basic.csv --foundation 深基础 --output-dir tests/_out_basic
```
预期（见 `expected_basic.json`）：
- 等级分布：正常 3 / 红色(报警) 1（SW-01 累计 2010 ≥ 报警值 1000，占 201%）/ 未判定 1（FC-01 分层竖向位移无阈值）。
- 红色点：SW-01；未判定点：FC-01。
- 备注文本形如：`预警等级：红色(报警)；报警值：1000 mm；控制值：2000 mm；占报警值：201.0%；超报警值：是；超控制值：是；依据表8.0.5；RAG命中 …`。

## 用例 3：非法输入
```bash
python scripts/run.py --csv /不存在的路径.csv
# → {"status":"INVALID_INPUT","reason":"FILE_NOT_FOUND"}，退出码 2
```

## 用例 4：RAG 证据层（需 chromadb + openpyxl）
```bash
# 先安装依赖：pip install chromadb sentence-transformers openpyxl
python scripts/run.py --csv tests/sample_basic.csv --foundation 深基础 --output-dir tests/_out_rag
```
- 有阈值的监测项应返回 `rag_evidence.status=OK` 与 `jikeng_norms` 命中（含 source/clause/score）；
- 若未安装 chromadb，RAG 层返回 `EVIDENCE_NOT_FOUND(reason=RAG_DEPENDENCY_MISSING)`，确定性层照常完成（退出码 0）。

## 端到端验证（6 个多工况文件）
对 `基坑监测7天数据/多工况/` 下深/浅基础 × 正常/中等预警/明显预警 共 6 个文件运行，
等级分布应为：正常={'正常':30,'未判定':6}；中等预警={'正常':27,'红色(报警)':3,'未判定':6}；
明显预警={'正常':26,'红色(报警)':4,'未判定':6}；浅基础同构。红色点应与数据生成 manifest 一致
（明显预警 = SW-07 地下水位 / DBC-07 地表 / KB-01 坑底 / LF-04 裂缝）。

## 验证清单（对照 AGENTS.md 测试要求）
- [x] 正常输入（用例 1 / 用例 2 正常点）
- [x] 边界输入（用例 2 红色点累计达/超报警值）
- [x] 非法输入（用例 3）
- [x] 需弃权输入（用例 2 分层竖向位移 未判定）
- [x] 输出字段与错误码（evaluation.json + 退出码）
- [x] 证据 ID（RAG 命中携带 source/clause/score）
- [x] 输出格式对齐真实日报（附表 E/F 列结构 + 备注文本 + 简要分析）
