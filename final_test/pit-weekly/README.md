# 基坑当前版本周报测试包

更新：2026-11-19。所有输入均为人工模拟数据，用于软件回归，不是真实工程观测。

## 数据与预期

- 上传文件：`inputs/weekly_simulated.csv`，单个围护墙顶部水平位移测点，2026-10-01至08，共8条，单位mm。
- 工程条件：一级、地下连续墙、开挖深度20m。逐项填写；请求JSON用于自动测试，不作为监测文件上传。
- 周报选择2026-10-02至08，共7天、7条区间记录；10月1日的0mm用于历史基准。
- 区间累计位移依次5、12、22、35、52、60、62mm；速率依次5、7、10、13、17、8、2mm/d。
- 该测试方案的末次累计62mm，整体等级“危险报警”；请核对冻结结果，不将测试条件用于真实工程。

## 自动测试

先按根README准备Node和Python依赖，在仓库根目录运行：

```bash
npm run test:pit-data       # 本测试包、27个引擎场景、上传/分析/报告/篡改拦截
npm run test:data           # 一并检查基坑和隧道
```

入口自动使用临时账号和存储目录，不读取实际工程账号；Python优先使用`.venv`，也可用`EXCAVAGUARD_PYTHON`指定。汇总写入`var/acceptance/test-data/`，场景结果写入`var/acceptance/pit-data/`。

仅校验发布样例时：

```bash
.venv/bin/python tools/test/verify-weekly-sample.py
```

校验包括SHA256、CSV/JSON等价、独立列出的累计/速率预期、冻结事实、Excel单元格/跳转、Markdown和确定性报告审计。无需LLM、联网RAG或原始PDF。

## 文件与复现边界

- `snapshots/weekly_engine_payload.json`为当前代码重算结果，带单位及工程条件字段。
- `snapshots/weekly_evidence.json`为历史公共规范证据快照，仅供离线复现，不表示本次重新检索或核验规范时效。
- `weekly_analysis.json`为null，本包使用确定性模板，不复用旧模型正文，不代表新的LLM语义审查。
- `reports/weekly/`保存当前模板三件套；`validation/files.sha256.json`登记全部输入、快照与报告。
- 旧版样例完整保留在`../latest/`。旧快照缺少新增字段，不能作为当前代码输出的逐字预期。
- 更广泛的27场景、57测点、3420条模拟记录仍在`确定性计算层/data_simulated/`。自动入口调用配套工程条件和逐点设置，不要求用户手工配置全部场景。

显式重建当前样例（会重写本包快照、报告和清单，不会改动历史目录）：

```bash
.venv/bin/python tools/test/generate_pit_weekly_sample.py
.venv/bin/python tools/test/verify-weekly-sample.py
```

真实模型基坑日报另用`npm run ai:test`，需配置LLM及基坑RAG服务；不计入上述离线测试通过结论。
