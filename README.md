# 基坑智守 · 规范 RAG 知识库

基于 **30 部基坑/地基基础相关国家与行业标准** 构建的本地 RAG（检索增强生成）知识库，
支持**规范条款检索**、**监测数据合规核对**、**规范格式日报自动生成**。

全程**离线运行**：嵌入模型、向量库、demo 服务均在本地，数据不出本机。

---

## 目录结构

```
jikeng-rag/
├── source/                     # 源代码
│   ├── ocr_extract.py          #   规范 PDF 文本提取（文本层直取 + 扫描件 OCR，多进程）
│   ├── build_kb.py             #   知识库构建（条款切分 → 向量化 → ChromaDB）
│   ├── query_kb.py             #   命令行检索工具
│   ├── report_core.py          #   日报核对与生成核心逻辑（含报警值规则表）
│   └── server.py               #   互动 demo 服务（FastAPI）
├── data/
│   ├── docs/                   # 规范源文件（30 部 PDF，按类别分目录）
│   ├── ocr_text/               # OCR/提取后的纯文本（每部规范一个 .txt）
│   ├── chroma_db/              # ★ 成品向量库（纯文件，拷贝即迁移，免重新训练）
│   └── chunks.jsonl            # 条款块清单（可审查每块内容与出处）
├── models/bge-small-zh/        # 本地中文嵌入模型（93MB）
├── demo/index.html             # 互动测试页面
├── tests/test_kb.py            # 验证测试脚本
├── requirements.txt
└── README.md
```

## 一、新设备迁移（三步，无需重新训练）

> 向量库 = 一堆普通文件。整个文件夹拷走就是完整知识库。

```bash
# 1. 拷贝整个 jikeng-rag 文件夹到新设备（U盘/网盘/scp 均可）

# 2. 安装依赖（仅首次，Python 3.10+）
cd jikeng-rag
pip install -r requirements.txt

# 3. 直接使用
python source/query_kb.py "基坑顶部水平位移报警值"   # 命令行检索
python source/server.py --port 8600                  # 或启动互动 demo
# 浏览器打开 http://localhost:8600
```

> ⚠️ 注意：嵌入模型已随包附带（models/bge-small-zh），**无需联网下载**。
> 若新设备无网，pip 依赖请提前在有网机器上下载 whl 离线包：
> `pip download -r requirements.txt -d wheels`，目标机 `pip install --no-index --find-links wheels -r requirements.txt`

## 二、知识库更新（仅当规范文件变化时）

```bash
# 1. 将新规范 PDF/Word 放入 data/docs/（可按类别建子目录）
# 2. 提取文本（扫描件自动 OCR，断点续跑）
python source/ocr_extract.py --workers 8
# 3. 重建知识库
python source/build_kb.py --rebuild
```

伪文本层（只有页眉水印的扫描 PDF）强制重跑 OCR：
```bash
python source/ocr_extract.py --workers 8 --force-ocr
```

## 三、互动 Demo：监测描述 → 规范核对 → 日报

```bash
python source/server.py --port 8600   # 浏览器访问 http://localhost:8600
```

测试链路（与需求对应）：

1. **模拟测试者输入现场描述**，例如：
   > 3号测点今日累计沉降32mm，日变化速率4.2mm/d；CX1测斜孔深层水平位移累计28.5mm，速率2.6mm/d；SW2水位累计下降0.8m；ZC3支撑轴力本次1850kN，设计值2600kN
2. **规范核对**：系统自动解析监测项 → 检索知识库命中规范条款 →
   按 GB 50497-2019 报警值规则逐项判定：✅正常（<70%）/ ⚠️需关注（70~100%）/ 🚨报警（≥100%），
   并附**条款出处**（规范名 + 条款号）。
3. **生成日报**：按项目《监测日报编制细则》五节模板输出
   （工程概况与工况 / 数据汇总表 / 分析评价 / 结论建议 / 签字栏），可下载 Markdown。

命令行模式（无浏览器时）：
```bash
python source/report_core.py
```

## 四、内置规范清单（30 部）

| 类别 | 规范 |
|---|---|
| 强制性通用规范 | GB 55001 / 55003 / 55017 / 55018 / 55030 / 55032 / 55033 / 55034 |
| 监测类 | GB 50497-2019 建筑基坑工程监测技术标准 等 |
| 勘察与设计类 | GB 50007-2011、GB 50021-2001(2009版)、GB 50330-2013 |
| 配套行业标准 | JGJ 111 / 120 / 180 / 311 / 33 / 46 / 59 |
| 施工与验收类 | GB 50201 / 50202 / 50300 / 51004 / 51254、GB/T 51351 |
| 特殊土与特殊条件 | GB 50025 / 50324、GB/T 50942 / 51238 |
| 项目文件 | 基坑智守项目监测日报编制细则（日报格式依据） |

## 五、判定规则说明

- 报警值规则表内置于 `source/report_core.py` 的 `DEFAULT_ALARM_RULES`，源自 GB 50497-2019
  第 8.2/8.3 条（一级/二级基坑）；可新建 `config/alarm_rules.json` 覆盖（同结构 JSON）。
- 三级结论判定（正常/需关注/报警）依据项目细则第 4 节：70% 阈值。
- 检索引用由 bge-small-zh + ChromaDB 向量检索给出，每条核对结果附规范出处。

## 六、常见问题

| 问题 | 处理 |
|---|---|
| 新设备打开 demo 报"知识库未就绪" | 确认 `data/chroma_db/` 与 `models/` 已随包完整拷贝 |
| 检索结果不准 | 规范扫描件 OCR 可能存在错字，可用 `--force-ocr --dpi 200` 提高精度后重建 |
| 想接入大模型生成更自然的日报 | `report_core.py` 输出的结构化结果（checks）可直接喂给任意 LLM |
| 内存/显存不足 | 本方案全 CPU 运行，bge-small-zh 仅需约 500MB 内存 |

## 公开仓库说明（合规）
本公开仓库**不含**规范知识库原始数据：`data/ocr_text/`（规范全文）、`data/chunks.jsonl`、`data/chroma_db/`（向量库）已通过 `.gitignore` 排除，以避免公开分发受版权保护的 GB 标准全文。
如需在本机运行 RAG / demo，请使用本地已授权的规范源文件，执行：
```bash
python source/ocr_extract.py --workers 8   # 若仅有 PDF 源
python source/build_kb.py --rebuild        # 重建 data/chroma_db/
```
重建后即可 `python source/server.py --port 8600` 正常检索与生成日报。代码与本地嵌入模型（models/bge-small-zh）随仓库提供。
