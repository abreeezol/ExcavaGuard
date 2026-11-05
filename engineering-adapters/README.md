# 工程场景适配器 v2

当前架构：通用三Agent与Skill执行框架，加载开发者部署的场景适配器。专业配置和专业程序均属于适配器；不是仅切换提示词，也不是上传PDF后自动生成算法。

## 组成

```text
engineering-adapters/<adapter-id>/
├── manifest.json          身份、版本、支持范围、核心字段、处理器与资产
├── context.schema.json    当前专业的工程参数校验
├── policy.json            分类、检索策略、三角色专业要求
├── runtime/               专业Python处理器及依赖
└── requirements/          专业细则参考（如有）
```

基坑适配器为`foundation-pit@2.1.0`，专业桥接、模板、表格及文件审计已迁入runtime；底层既有Python计算/规则库按清单引用复用，不重写判据。八个业务Skill均已具备实现；案例与工况通过项目辅助资料条件调用，当前为明确测项/关键词检索、同日位置关联及结构化冲突检查。

## 通用执行链

1. 用户创建工程时选择已部署的场景，后端保存适配器ID和版本。旧工程未绑定时显式兼容原基坑场景，不猜测工程类型。
2. 工作台从`/api/projects/current/engineering`读取核心字段，动态展示参数。没有虚构工程默认值，可选且允许null的字段缺失时记录null。
3. 项目管理员确认配置后保存参数、修订号、确认人和时间；后续自动复用。PUT使用expected_revision防止覆盖他人更新；不允许通过该接口切换已有工程类型。
4. 上传检查、计算入口由后端当前工程选择处理器；请求或文件不能修改场景归属。已确认工程参数优先于本次请求参数。
5. 通用Skill桥接仅运行适配器登记的仓库内处理器。项目补充规范SQLite工具属于共用基础设施，不随专业切换。
6. 事实中冻结适配器版本、登记资产哈希和professional_parameters。三Agent共享此上下文；分类不再固定A–F，检索词与专业检查从policy读取。
7. 渲染/审计按适配器选择实现。通用审计额外独立核查文件路径、大小、SHA-256和引用范围，专业处理器不能关闭这些检查；源快照、语义审查、最多两轮修订和最终人工确认边界保持。
8. 编报或审计时发现适配器版本/登记资产指纹变化，要求新建运行重新计算，不能混用新旧能力。历史文件不改写。

## 处理器接口

`manifest.handlers`使用下列稳定键，值为仓库内受控Python脚本路径：

- `parse-monitoring-data/inspect_file.py`
- `normalize-monitoring-data/normalize_records.py`
- `evaluate-thresholds/run_judgement.py`
- `evaluate-thresholds/check_strictness.py`
- `render-daily-report/render_daily_report.py`
- `validate-report/validate_report.py`

正式场景必须提供全部六个入口（计算包括阈值上传核验）。脚本沿用JSON stdin/stdout信封及现有冻结事实、三件套和审计契约。旧`skills/*/scripts`保留兼容入口；应用主链直接使用已加载适配器中的处理器。

复杂算法可作为适配器代码提供，无需强行转换成JSON。通用框架不自动下载或执行用户提供的代码。契约发生破坏性变化仍需升级框架契约，不承诺任意业务无条件接入。

## RAG连接与隔离

适配器通过`retrieval.connection`引用服务端连接配置。基坑保留`legacy-pit`别名，兼容原环境变量；其他场景缺少独立连接时拒绝执行，不回退基坑库。

服务器可配置`EXCAVAGUARD_RAG_CONNECTIONS`，例如（不含真实凭据）：

```json
{
  "tunnel-kb": {
    "provider": "local",
    "base_url": "http://127.0.0.1:8700",
    "timeout_ms": 30000
  },
  "another-kb": {
    "provider": "pinecone",
    "index": "independent-index",
    "namespace": "standards-v1",
    "api_key_env": "ENGINEERING_PINECONE_API_KEY",
    "text_field": "text"
  }
}
```

本地服务继续限制loopback地址。连接应由部署人员指向正确的独立索引/服务；系统不能仅凭URL证明数据库内容属于某专业。专业目录过滤、证据审核与项目补充库隔离继续执行。项目补充规范只提供本项目证据，不自动修改执行阈值。

## 新场景接入方法

新增完整的适配器目录，提供参数schema、策略、专业处理器、独立规范目录/知识库连接及测试；无需给Supervisor、报告Agent、审计Agent各复制一份代码。注册表发现合法目录后，工程创建界面自动列出。需要新计算或表式时，在适配器中实现，并验证I/O与专业正确性。

`verification-monitoring`为测试专用适配器：不同工程参数、非A–F的M分类、独立模拟计算/渲染/审计，证明同一主链可选择不同实现。它不是隧道适配器，没有真实工程判据，在生产环境禁止加载和展示。

## 验收

```bash
npm run adapter:validate
npm run test:adapter
```

`test:adapter`覆盖基坑与跨场景验证。全量测试使用临时EXCAVAGUARD_ACCESS_FILE，避免已有真实账号使匿名测试返回401。真实模型、远端RAG和实际工程师认可需另行验收。

当前版本升级采用“管理员确认升级＋新建运行”，没有旧程序版本自动归档或回滚服务。指纹是登记资产的追踪信息，不是数字签名，也不覆盖远端向量库全部内容。新增真实隧道能力仍需专业适配和验证。


## 项目辅助资料

工作台“案例、工况与巡视资料”支持上传、下载模板及启停。案例支持JSON、UTF-8 TXT/MD；工况与巡视使用带时间、位置和记录人的JSON。PDF、图片、CSV工况导入尚未接入此入口。

资料存放于独立`var/project-context/<project_id>/`，可通过EXCAVAGUARD_PROJECT_CONTEXT_ROOT配置持久目录。与规范RAG分离，不参与规则阈值覆盖。存储原结构化内容/提取文本、来源和SHA-256，上传同内容去重；停用只影响新运行。当前为单服务文件存储，不是云端共享向量库。

policy.supporting_context规定位置字段、同日时间策略和候选预算；案例语义词由该场景测项/表式字典提供。当前算法明确为显式测项/关键词检索，不使用模型编造相似度或推断因果。结构化冲突要求同时间、同位置、同断言键且取值不同；不宣称能自动识别所有自然语言矛盾。

辅助快照纳入engine.project.supporting_context并独立留痕，报告Agent和审计Agent使用同一份资料。规范evidence_ids与案例文档ID分开；辅助标量通过事实占位符引用。没有资料、没有命中或资料不可用时披露状态，继续已有监测报告；正式的规范检索与语义审查故障边界不因此放宽。


2026-11-04：新增tunnel-shield（盾构周边地表/建筑沉降）及独立SQLite规范候选库；foundation-pit升级2.2.0。通用框架与专业边界见[最新交付](../方案与迭代note/28_五项迁移完善与隧道验收.md)。


2026-11-04全规范版：新增[tunnel-monitoring](tunnel-monitoring/README.md)，16本独立隧道规范候选库、按工程类别/工法/阶段/特殊地质过滤，支持四类变形测项及单独控制值。tunnel-shield仍为原3本规范范围，不静默迁移旧工程。最终验收见[29号记录](../方案与迭代note/29_隧道全规范RAG与分类适配器.md)。


## 2026-11-04 工程类型统一（当前交互）

用户只选择基坑工程或隧道工程及必要参数，不选择适配器或知识库。隧道共用一个处理入口，工法/工况为工程参数，上传后识别测项与日期，再按测项确认控制要求。已有隧道参数与辅助资料兼容保留，历史资源不展示为另一项选择；不使用配置JSON作为业务入口。230项通过/6外部跳过，类型/lint/build通过，未推送。详见[30号记录](../方案与迭代note/30_工程类型统一入口与隧道参数路由.md)，此前29号“单独选择新适配器”的操作说明已被本记录取代。
