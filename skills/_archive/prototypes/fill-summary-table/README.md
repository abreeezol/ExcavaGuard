# fill-summary-table · 安装与使用

把**杂乱的**基坑应力/轴力监测数据（表 C、表 D）按 GB 50497-2019 附录 C/D 表式，
规范地填入与「示例汇总表」**同构**的工作簿；也可按 10 列**判定汇总表**版式输出。

| 输出形态 | `--layout` | 内容 |
|---|:--:|---|
| 规范表式（默认） | `cd` | `表C` / `表D` / `汇总` |
| 判定汇总表 | `verdict` | `表C判定汇总` / `表D判定汇总` / `说明`（含 `规范条文`、`规范依据摘要` 两列） |
| **附录原表式** | `af` | `附表C` / `附表D`（默认）；`--tables cdef` 加 `附表E` / `附表F`。抬头 5 行 + 表头第 6 行 + 备注内嵌判定 |
| 两者同时 | `both` | `cd` + `verdict` |
| 三者同时 | `all` | `cd` + `verdict` + `af` |

---

## 1. 目录结构

```
fill-summary-table/
├── SKILL.md                                      ← Skill 契约（触发条件/输入输出/流程/边界）
├── README.md                                     ← 本文件
├── 验证说明_给同事.md                             ← 一页验证说明（给验证人）
├── .gitignore                                    ← 打包/入库排除项
├── references/
│   ├── 01_GB50497-2019_附录CD_表式字段说明.md      ← 规范字段定义（含 PDF 页码定位）
│   ├── 02_现有数据特征分析.md                      ← 项目已有数据的覆盖情况与可复用特征
│   ├── 03_示例汇总表格式规范.md                    ← 目标格式的精确行锚点与样式规格
│   ├── 04_判定汇总表格式规范.md                    ← 10 列判定汇总表版式 + I/J 列口径
│   ├── 05_附录CDEF表式规范.md                     ← 附录 C/D/E/F 原表式 + 点号前缀反推规则
│   └── 06_开发故障排查与自检.md                    ← 故障排查手册（现象→根因→解决→预防）
├── scripts/
│   ├── fill_summary_table.py                     ← 主脚本（纯标准库 + openpyxl）
│   ├── verdict_table.py                          ← 判定汇总表模块
│   ├── appendix_table.py                         ← 附录 C/D/E/F 原表式模块
│   ├── rate_rules.py                             ← 速率口径判据（8.0.3 / 8.0.9-1）
│   └── rag_lookup.py                             ← 知识库检索桥（可选增强）
└── assets/
    ├── standards/
    │   └── GB50497-2019_预警值判据库.json          ← 内置判据库（22 个监测项 + 规范条文出处）
    ├── rag_hits.json                             ← 知识库命中缓存（离线可用）
    ├── demo/
    │   ├── meta.example.json                     ← 元数据模板
    │   └── design.example.json                   ← 设计值模板（判定汇总表用）
    ├── 示例输入_宽表.csv                          ← 宽表样例（时间列 + 每列一个测点）
    ├── 示例输入_杂乱表C.csv                        ← 长表样例（含标题行/单位变体/格式不一致）
    ├── 示例输出_宽表填入.xlsx                      ← 宽表输入的填充结果
    ├── 示例输出_已填表.xlsx                        ← 长表输入的填充结果
    ├── 示例输出_判定汇总表.xlsx                    ← 判定汇总表示例输出
    ├── 示例输出_附录CD表式.xlsx                    ← 附录表式示例输出（附表C/D，与参考文档逐格一致）
    ├── 示例输出_单独附表C.xlsx / _附表D.xlsx        ← `--split` 单独提取的附表 C / D
    ├── meta.example.json
    └── limits.example.json                       ← 阈值模板（可选增强）
```

---

## 2. 安装

### 2.1 安装为 Skill

> ⚠️ **文件夹名必须保持 `fill-summary-table`** —— 本机 Skills 目录的实际约定是
> **目录名 = `SKILL.md` 的 `name` 字段**（已核对 `~/.workbuddy-ai/skills/` 下现有的
> `deep-research` / `github` / `task-alignment` 三个技能，目录名与 `name` 全部一致）。
> 若改成别的名字，Skill 可能识别不到。

把整个 `fill-summary-table` 目录**原样**复制到 Skills 目录即可（无需再改名）：

**用户级**（所有项目可用，推荐）：

```bash
cp -r fill-summary-table  ~/.workbuddy-ai/skills/fill-summary-table
#   Windows: 复制到  C://Users//<你>//.workbuddy-ai//skills//fill-summary-table
```

**项目级**（仅当前项目可用）：

```bash
mkdir -p "<你的项目>/.workbuddy-ai/skills"
cp -r fill-summary-table  "<你的项目>/.workbuddy-ai/skills/fill-summary-table"
```

安装后，对话中出现「按规范格式整理表 C / 表 D」「填进汇总表」「判定汇总表」
「附录表式」等意图时，Skill 会被自动匹配（依据 `SKILL.md` 的 `description`）。

### 2.2 依赖

| 依赖 | 必要性 | 说明 |
|---|:--:|---|
| Python ≥ 3.9 | **必需** | 脚本使用 `from __future__ import annotations` 与新式类型标注 |
| `openpyxl ≥ 3.1.0` | **必需** | 唯一必需的第三方依赖；脚本启动时**自动检测并安装**，也可手动 `pip install openpyxl` |
| `torch(cpu)` + `chromadb` + `sentence-transformers` | **可选** | 仅 `--layout verdict` 且需要**实时**检索知识库时需要。有 `assets/rag_hits.json` 缓存时**不需要**（`--rag auto` 直接读缓存） |

主流程（`--layout cd`、以及 `--layout verdict --rag auto` 命中缓存）**全部使用标准库**
（`csv` / `json` / `re` / `datetime` / `pathlib` / `collections`）。

> 把 Skill 分发给他人时：`assets/rag_hits.json` 已内置，**对方无需安装 torch / chromadb
> 也能得到带「RAG命中」的 I/J 两列**。若对方要自己重跑检索，再加 `--rag refresh`。

---

## 3. 使用

### 3.1 最小用法

```bash
python scripts/fill_summary_table.py \
  --input  你的监测数据.xlsx \
  --output 已填汇总表.xlsx
```

### 3.2 带元数据（抬头字段）

```bash
python scripts/fill_summary_table.py \
  --input  ./监测数据/ \
  --output ./输出/汇总表.xlsx \
  --meta   meta.json
```

`meta.json` 示例（见 `assets/meta.example.json`）：

```json
{
  "project": "××市轨道交通 X 号线 XX 站基坑工程",
  "report_no": "JK-2026-007",
  "times": 7,
  "weather": "多云",
  "observer": "张三",
  "calculator": "李四",
  "checker": "王五",
  "instrument_model": "XP99 频率读数仪",
  "instrument_no": "XP99-021",
  "instrument_valid": "2027-06-30",
  "previous_time": "2026-10-06 23:00",
  "work_condition": "当日东侧第三层土方开挖，分段长度约 20 m；第二道钢支撑已施工完成并施加预应力。",
  "analysis": "本期应力与轴力测点中，支撑轴力较上期明显增长，累计值已接近报警值，需关注支撑受力状态。"
}
```

> 未提供的字段会在表中留 `＿＿＿＿`，**不会臆造**。

### 3.3 指定目标期

```bash
python scripts/fill_summary_table.py --input data/ --output out.xlsx --date 2026-10-07
```

不指定时默认取**最新一期**（数据的最后一天）。

### 3.4 可选：启用阈值判定

> ⚠️ **本 Skill 默认不做风险判定**。仅当你明确需要时再启用。

```bash
python scripts/fill_summary_table.py --input data/ --output out.xlsx --limits limits.json
```

### 3.5 输出清洗报告

```bash
python scripts/fill_summary_table.py --input data/ --output out.xlsx --report report.json
```

### 3.6 判定汇总表（10 列版式，独立文件）

输出 `监测项目 | 点号 | 本次变化量 | 变化速率 | 累计变化量 | 报警值 | 控制值 | 等级 | 规范条文 | 规范依据摘要`。

```bash
python scripts/fill_summary_table.py \
  --input  你的监测数据.xlsx \
  --output 判定汇总表.xlsx \
  --layout verdict \
  --meta   assets/demo/meta.example.json \
  --design assets/demo/design.example.json
```

- `--design`（可选）：设计值 JSON，如 `{"支撑轴力": 800, "锚杆轴力": 300}`。
  **不提供**时，内力/轴力类的报警值/控制值以占比文本（`60%f2`）展示，等级为 `未知`。
- `--period`（默认 `interval`）：`interval` = 末期与相邻上一期（与样例图片一致）；
  `daily` = 当日末次 − 前日末次。
- `--safety-level`（默认 `一级`）：决定取判据库中的哪一档限值。
- `--rag`（默认 `auto`）：知识库检索。`auto` 优先用 `assets/rag_hits.json` 缓存；
  `refresh` 重新检索并更新缓存；`off` 不检索（I/J 的 RAG 部分留空并注明）。
- 知识库自动探测顺序：`--rag-dir` → 环境变量 `JIKENG_RAG_DIR` → 上级目录下的 `jikeng-rag`。
  **探测不到时安静降级**，不影响主流程，也不补造条文。

### 3.7 两者同时产出

```bash
python scripts/fill_summary_table.py \
  --input data/ --output 汇总表.xlsx --layout both \
  --verdict-out 判定汇总表.xlsx
```

### 3.8 附录 C/D/E/F 原表式（`--layout af`）

```bash
python scripts/fill_summary_table.py \
  --input  你的监测数据.xlsx \
  --output 附录表式.xlsx \
  --layout af --appendix-periods 3 --derived-note auto
```

- **默认输出 附表C / 附表D 两张 sheet**（参考文档点名的两张）；需要表 E / 表 F 时加 `--tables cdef`。
- **可直接读取 GB 50497 附录原表式工作簿**（抬头 5 行、表头第 6 行、组号点号在末尾、
  无「监测项目」列、预警等级内嵌在「备注」里）—— 监测项目由**点号前缀**反推。
- `--appendix-periods`（默认 3）：每个测点保留最后几期。
- `--derived-note`（默认 `auto`）：`auto` 仅在确实由序列推算时在备注末端追加来源说明；
  `always` 与参考文档逐字一致；`never` 不追加。
- `--tables`（默认 `cd`）：`cd` = 只出 附表C / 附表D；`cdef` = 四张全出。
- `--rate-rules`（默认 `on`）：速率口径判据（第 8.0.3 条「连续 3 次超 70%」、
  第 8.0.9-1 条「突然明显增大」）。`--sudden-factor`（默认 3.0）控制突变倍数，设 0 关闭该条。
- `--ack-sudden-factor`：**确认启用**「突然明显增大」判据。运行时会在控制台打印提示块；
  **未确认时该条不参与判定**（流程不中断），仅在产物中注明「已停用」。
  也可用环境变量 `EXCAVAGUARD_ACK_SUDDEN_FACTOR=1`。

### 3.9 每张附表单独提取

```bash
python scripts/fill_summary_table.py \
  --input data.xlsx --output 附录表式.xlsx --layout af --split
```

除合并工作簿外，另生成 `附录表式_附表C.xlsx` / `附录表式_附表D.xlsx`
（加 `--tables cdef` 时再加 `_附表E.xlsx` / `_附表F.xlsx`）。

---

## 4. 输入数据的容错能力

脚本可处理真实记录中常见的以下问题：

| 问题 | 处理 |
|---|---|
| **宽表格式**（一行一个时刻、一列一个测点，列名如 `土压力 TY-01 (kPa)`） | **自动识别并融化为长表** |
| **附录原表式**（抬头 5 行、表头第 6 行、组号点号在末尾、无「监测项目」列） | **自动识别**，监测项目由**点号前缀**反推 |
| 附录表式「备注」里内嵌的 `预警等级：…；报警值：…；占报警值：…` | 自动解析并**原样引用** |
| 附录表式的页脚行（`工况描述：`/`简要分析…`/`第 页 共 页`/`·…`） | 自动跳过，不计入待复核 |
| 非记录表 sheet（`超限测点清单` / 文字说明页 / `汇总`） | 整表跳过，并在读取报告中列出 |
| 编码混杂（GBK / GB18030 / UTF-8 BOM / Big5） | 自动探测 |
| 含标题行、元数据行、空行 | 前 12 行内自动定位真实表头 |
| 列名不统一（中文 / 英文 / 简写） | 别名映射（见 `SKILL.md`） |
| 单位大小写与量纲不一致（`kpa` / `KPa` / `千帕` / `MPa`） | 归一化到 kPa / kN / mm |
| 时间格式混杂（`2026-10-07 08:00` / `2026/10/7 8:00` / `2026年10月7日`） | 多格式依次尝试 |
| 含非目标表的监测项目（表 A / 表 B） | 不写入，记入**待复核**并注明「不在处理范围」 |
| 测值缺失 / 非数值 | 填 `—`，等级 `未判定(待复核)` |
| 单位量纲不符（如表 C 项目填了 `mm`） | 同上 |

---

## 5. 验证

### 5.1 宽表输入（推荐先试这个）

```bash
python scripts/fill_summary_table.py \
  --input  assets/示例输入_宽表.csv \
  --output /tmp/out_wide.xlsx
```

`assets/示例输入_宽表.csv` 是 GBK 编码、含标题行与空行、第一列为时间、其余列每列一个测点。

预期输出：

```
读取 1 个文件，共 12 行原始记录
清洗后有效记录 12 条，待复核 0 项
目标期：2026-10-07（每日取最后一次观测；累计变化基准为该测点首期）
  表C：4 条
  表D：2 条
✓ 已生成 /tmp/out_wide.xlsx
```

### 5.2 长表输入（杂乱样例）

```bash
python scripts/fill_summary_table.py \
  --input  assets/示例输入_杂乱表C.csv \
  --output /tmp/out_long.xlsx
```

预期输出：

```
读取 1 个文件，共 9 行原始记录
清洗后有效记录 8 条，待复核 1 项
  表C：3 条
  表D：2 条
```

其中：

- `kpa` / `KPa` / `千帕` / `KN` / `kn` 全部被正确归一；
- `沉降` 不属于表 C/D，被正确拦截并记入待复核；
- 输入自带的「预警等级」被**原样引用**（黄色预警 / 橙色预警 / 正常）。

### 5.3 宽表数据集成品（CD_data）

`CD_data/` 下的 10 个文件即为宽表格式（时间列 + 每列一个测点，5 分钟间隔）：

```bash
python scripts/fill_summary_table.py \
  --input  "../CD_data/SIMULATED_浅基坑B_应力轴力_7天.xlsx" \
  --output /tmp/out_from_cddata.xlsx
```

脚本会自动定位第 4 行表头、识别 8 个宽表列并融化为 16,128 条长表记录。

### 5.4 判定汇总表（推荐用这条命令核对版式）

```bash
python scripts/fill_summary_table.py \
  --input  "../CD_data/SIMULATED_浅基坑B_应力轴力_7天.xlsx" \
  --output "assets/示例输出_判定汇总表.xlsx" \
  --layout verdict \
  --meta   assets/demo/meta.example.json \
  --design assets/demo/design.example.json
```

预期输出：

```
读取 1 个文件，共 16128 行原始记录
清洗后有效记录 16128 条，待复核 0 项

[判定汇总表] 目标期：2026-10-07（末期与相邻上一期（保留原始采样间隔））
✓ 已生成判定汇总表 …/示例输出_判定汇总表.xlsx
  sheet：['表C判定汇总', '表D判定汇总', '说明']
  行数 8；等级分布 正常 0 / 黄色 0 / 橙色 0 / 红色 2 / 未知 6
  知识库检索：已接入
```

结果解读（**这是数据集本身的如实反映，不是脚本错误**）：

| 测点 | 等级 | 原因 |
|---|:--:|---|
| 支撑轴力 ZL-01 | 红色 | 测值 1,095 kN ≥ 控制值 640 kN（80% × f2 800 kN）—— 与 `CD_data/README.md` 记录的「137% 超限」一致 |
| 锚杆轴力 MG-01 | 红色 | 测值约 174 kN < 报警值 240 kN（80% × fy 300 kN）—— **模拟数据集的锚杆量级按 0.58×设计值生成，低于规范下限 80%fy**，故如实判为红色（预应力偏低） |
| 土压力 / 孔隙水压力 / 围护墙内力 | 未知 | 规范限值为设计值占比（`60%f1` / `60%f2`），未提供 f1 / f2 → 弃权 |
| 立柱内力 | 未知 | GB 50497-2019 表 8.0.4 **未给出**立柱内力预警值 → I 列退化为 `RAG命中 GB50497-2019` |

> 若要看到「正常 / 黄色 / 橙色」分支，可加 `--limits limits.json` 直接给绝对量限值，
> 或补全 `--design` 中的 f1 / f2。

### 5.5 附录表式：与参考工作簿逐格比对（`--layout af`）

拿**参考工作簿自身**当输入，重新生成 附表 C/D/E/F，再与原文逐单元格比对：

```bash
python scripts/fill_summary_table.py \
  --input  "../../监测日报_附表AF_RAG.xlsx" \
  --output "assets/示例输出_附录CD表式.xlsx" \
  --layout af --appendix-periods 3 --derived-note always --rag off
```

预期输出：

```
读取 1 个文件，共 246 行原始记录
清洗后有效记录 36 条，待复核 210 项

[附录表式] 输出 表C、表D；每测点保留 3 期；速率口径判据 开
  表C：15 条
  表D：6 条
  提示：另有 表E、表F 类测点 15 条未输出（加 --tables cdef 可一并输出）
✓ 已生成附录表式 …/示例输出_附录CD表式.xlsx
  sheet：['附表C_围护墙内力等监测日报表', '附表D_支撑轴力等监测日报表']
```

**比对结果：附表 C + D 数据区 168 格 / 0 差异 / 一致率 100.0%。**
（加 `--tables cdef` 时附表 C/D/E/F 共 303 格，同样 100%。）

- 210 项待复核全部来自 **附表A（119 行）与附表B（119 行）**，属表 A / 表 B，
  **不在本 Skill 处理范围**，被明确记入待复核而不是静默丢弃。
- 使用默认 `--derived-note auto` 时，仅备注末端的来源说明有 15 格差异
  （本 Skill 只在确实推算时才声明来源，比参考文档更严谨）。

---

## 6. 边界声明（必须遵守）

1. **不插值、不补造数据**：缺失一律填 `—`，并在备注说明。
2. **不代填签署栏**：工程负责人 / 监测单位 / 编制 / 审核 / 签发留 `＿＿＿＿`。
3. **不做风险判定与预警发布**：本 Skill 只整理数据与填表；
   预警等级默认**原样引用输入**，无输入则 `未判定(待复核)`。
4. **`未判定(待复核)` 表示弃权，不是「安全」**，必须转人工复核。
5. **阈值必须来自项目专项监测方案**（GB 50497-2019 第 8.0.1 条）；
   脚本内置的示例阈值**不是规范判据**。
6. 输出的表为**辅助材料**，不替代责任单位出具的正式监测报告。
7. 判定汇总表的 `未知` 等级 = **弃权，不是「安全」**；判据库未收录该监测项、
   未提供设计值、知识库未接入等情形一律 `未知` 并转人工复核。
8. **不臆造表号、条文号、页码或来源**；知识库未命中时如实注明，不补造条文。
9. 附录表式的**签署栏**（工程负责人 / 监测单位 / 编制 / 审核 / 签发）一律留 `＿＿＿＿`，**不得代填**；
   缺失值一律填 `—`，**不插值**。
9b. 速率口径判据中的**突变倍数**规范**未定量**（默认 3.0），属**工程经验判据**。
   脚本会在运行时**先在控制台打印提示块**，且**未确认（`--ack-sudden-factor`）时该条不参与判定**，
   须由项目专项监测方案确认后方可启用。
10. 表 A（水平位移、竖向位移）与表 B（深层水平位移）**不在本 Skill 处理范围**，
    其数据行会被明确记入**待复核**，不做静默丢弃。
11. **不猜测监测项目**：附录表式中点号前缀未匹配到已知映射时，该行记入待复核，
    不按 sheet 名或位置臆断。
