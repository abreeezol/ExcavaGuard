# ExcavaGuard 部署与使用说明

本文档面向**第一次拿到本项目的使用者**，目标是让你在最短时间内把项目跑起来。

> 本说明中的每一步都在 **Windows 11 + Node v22.22.2 + Python 3.13.14** 环境上实测通过（2026-10-15）。
> 实测证据见文末「[验证记录](#验证记录)」。

---

## 一、你有两条路可选

项目包含**两个相互独立**的服务，先想清楚你要用哪个：

| 方案 | 启动命令 | 地址 | 适合场景 | 依赖重量 |
|---|---|---|---|---|
| **A. 离线 RAG Demo**（推荐先跑） | `python start_demo.py` | **自动探测端口** | 想快速看效果：输一段监测描述 → 规范核对 → 生成日报 | 中（需 Python 依赖 + 模型） |
| **B. Next.js 工作台** | `npm run dev` | `http://localhost:3000` | 完整流程：上传 CSV/Excel → 三阶段计算 → 三件套导出 → 审计复核 | 重（486 个 npm 包 + Python 引擎） |

**两个服务可以同时运行，互不冲突。** 如果你只是想验证项目能不能用，走方案 A，5 分钟能出结果。

> **关于端口**：方案 A 的端口**不要写死**。不同电脑的系统保留端口段不同，
> 同一个端口在这台机器能用、在另一台可能直接报错（详见 [A4](#a4-端口自动规避不用改配置)）。
> 本项目的启动器会自动找到可用端口并打印出**本机专属的访问地址**，
> 所以你不需要关心具体端口号——照着终端输出的地址打开即可。

---

## 二、通用前置条件

| 依赖 | 要求 | 检查命令 |
|---|---|---|
| Node.js | 22.13+ / 24.x / 26.x（见 `package.json` `engines`） | `node -v` |
| Python | 3.10+（实测 3.13.14） | `python -V` |
| Git LFS | **必需**，否则模型权重拉不下来 | `git lfs version` |

### 关于 Git LFS（最容易踩的坑）

嵌入模型 `models/bge-small-zh/pytorch_model.bin` 通过 Git LFS 存储，**真实文件大小为 95,842,633 字节**。

如果没装 Git LFS，你 clone 下来的会是**一个 133 字节的文本指针**，形如：

```
version https://git-lfs.github.com/spec/v1
oid sha256:5cc750eb4f5412313aba1482e53aeccd1ed0b97bc213f2962e0c80e6c8809319
size 95842633
```

这时 Demo 能打开，但知识库会显示 **0 个条款块**、检索全空（服务不会报错，只是静默降级——这点很坑）。

```bash
git lfs install      # 首次使用需初始化
git lfs pull         # 拉取真实权重
```

**验证是否拉取成功**：

```bash
# Windows (Git Bash) / Linux / macOS
stat -c "%s" models/bge-small-zh/pytorch_model.bin     # 应输出 95842633
```

若数字是 `133`，说明 LFS 没拉成功，请执行上面的 `git lfs pull` 后重试。

> **没有 Git LFS 的手动兜底方案**：直接从 Hugging Face 下载 `BAAI/bge-small-zh` 的
> `pytorch_model.bin`，放到 `models/bge-small-zh/` 覆盖原文件，并自行校验 SHA-256 是否为
> `5cc750eb4f5412313aba1482e53aeccd1ed0b97bc213f2962e0c80e6c8809319`。

---

## 三、方案 A：离线 RAG Demo（5 分钟跑通）

### A1. 创建 Python 虚拟环境

> ⚠️ **不要用系统全局 Python 直接装依赖。** 请务必建虚拟环境，避免污染本机环境。
> 注意：虚拟环境目录名必须是 `.venv`，因为项目代码会优先查找 `<仓库>/.venv`。

**Windows：**

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
```

**macOS / Linux：**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
```

### A2. 安装 Python 依赖

依赖清单见 `requirements.txt`。**建议分步安装**——如果一次性安装全部依赖中途失败，排查会很困难。

**必需依赖（Demo 最小可运行集）：**

```bash
# Windows
.venv\Scripts\python.exe -m pip install openpyxl fastapi uvicorn pydantic

# macOS / Linux
.venv/bin/python -m pip install openpyxl fastapi uvicorn pydantic
```

**RAG 检索依赖（不装则检索为空）：**

```bash
# Windows
.venv\Scripts\python.exe -m pip install "chromadb>=1.0" torch "sentence-transformers>=3.0"

# macOS / Linux
.venv/bin/python -m pip install "chromadb>=1.0" torch "sentence-transformers>=3.0"
```

> **提示 1**：`torch` 的 CPU 版约 119 MB，安装需要几分钟，请耐心等待。
> 默认安装的就是 CPU 版，`.venv` 全 CPU 运行，`bge-small-zh` 仅需约 500 MB 内存。
>
> **提示 2**：若 `torch` 下载过慢，可指定 PyPI 官方源：
> `--index-url https://pypi.org/simple`
>
> **提示 3**：其余依赖（`sentence-transformers` 会自动带上 `numpy` 等）无需手动处理。
> 如需完整能力（PDF 解析、OCR、Word 语料），再执行 `pip install -r requirements.txt`。

### A3. 启动服务

### A3. 启动服务（推荐用启动器）

项目自带跨平台启动器 `start_demo.py`。它会**自动探测可用端口**，并按你机器的实际情况
打印出**本机专属的访问地址**：

```bash
# Windows
.venv\Scripts\python.exe start_demo.py --open

# macOS / Linux
.venv/bin/python start_demo.py --open
```

或者用一键脚本（Windows 双击即可）：

```bash
# Windows
start_demo.bat

# macOS / Linux
./start_demo.sh
```

启动成功后终端会明确输出一行：

```
  ✅ 服务已就绪： http://127.0.0.1:8666
```

**请以这一行输出的地址为准**（加 `--open` 会自动打开浏览器）。
换一台电脑，端口可能不同，但**这一行始终会给出正确地址**——这就是"稳定生成 local 部署链接"的含义。

> **不想自动打开浏览器**：去掉 `--open`。
> **只想看地址不启动**：`start_demo.py --check-only`（只打印地址后退出，适合脚本调用）。

### A4. 端口自动规避（不用改配置）

**这是本方案存在的意义：你不应该需要关心端口。**

不同电脑的情况并不一致：

- Windows 的 Hyper-V / WSL / Docker 会保留一批动态端口段，**该区间因机器而异，且重启后会漂移**；
- 端口可能被其他程序占用。

落在保留段内的端口会直接报错：

```
ERROR: [Errno 13] error while attempting to bind on address ('127.0.0.1', 8600):
[winerror 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。
```

所以项目内旧文档（`README.md`、`source/README.md`）里写死的 `--port 8600` 在部分机器上必然失败。
**`start_demo.py` 和 `server.py` 现在都内置了自动避让**：

- 启动时对 `127.0.0.1:<port>` 做**真实 bind 探测**（而不是简单的连接测试），
  因此也能识别出保留段这类"连不上也绑不上"的端口；
- 首选端口不可用时，自动向后寻找第一个可用端口（最多尝试 200 个）；
- 终端会同时打印提示和改进后的地址。

沿用旧命令也不会出错——`server.py` 自身同样会自动避让：

```bash
.venv\Scripts\python.exe source/server.py --port 8600   # 不可用时自动改用 8666 等
```

**如需查看本机保留段**（一般不需要，仅供排查）：

```bash
netsh interface ipv4 show excludedportrange protocol=tcp
```

**如需禁用自动避让**（端口冲突时直接失败，便于排查）：

```bash
.venv\Scripts\python.exe start_demo.py --port 8700
.venv\Scripts\python.exe source/server.py --port 8700 --no-auto-port
```

**API 也能查询当前端口**（供脚本/前端动态拼接地址）：

```bash
curl http://127.0.0.1:<实际端口>/api/port
# {"port":8666,"url":"http://127.0.0.1:8666"}
```

### A5. 使用 Demo

页面顶部会显示知识库统计，**正常应显示「知识库 8698 个条款块 / 30 部规范」**。
如果显示「知识库服务未就绪」或数字为 0，请回到 [A2](#a2-安装-python-依赖) 检查 RAG 依赖和 LFS 权重。

页面有两个标签页：

**① 日报核对生成**（默认）

1. 选择基坑安全等级、填天气与施工工况
2. 在文本框输入现场监测描述（测点 + 项目 + 累计值 / 速率，多项用分号隔开）
3. 点「核对规范并生成日报」

页面内置 3 个一键场景，可直接点「全部正常场景 / 单点报警场景 / 多点超限+轴力场景」体验。

**② 规范条款检索**

输入自然语言问题（如「基坑顶部水平位移报警值是多少」），直接检索知识库条款。

### A6. 无浏览器时用命令行

```bash
.venv\Scripts\python.exe source/report_core.py
```

### A7. 启动器全部参数

| 参数 | 作用 |
|---|---|
| `--open` | 启动后自动打开浏览器 |
| `--port <n>` | 首选端口（仍会自动避让） |
| `--check-only` | 只打印可用地址后退出，不启动服务 |

依赖缺失或模型权重大小不对时，启动器会在启动前**主动告警**，避免走到页面才发现检索为空。

---

## 四、方案 B：Next.js 工作台

### B1. 前置：必须已有 Python

确定性计算引擎由 Node 以子进程方式调用 Python 执行。
Node 会**按以下顺序**寻找解释器：

1. 环境变量 `EXCAVAGUARD_PYTHON` 指定的绝对路径（优先级最高，**推荐显式配置**）
2. 仓库内的 `.venv`（Windows 为 `.venv\Scripts\python.exe`，类 Unix 为 `.venv/bin/python`）
3. PATH 上的 `python3`
4. PATH 上的 `python`

找不到时接口会明确返回 `[ENGINE_UNAVAILABLE]`。

**建议做法**：先按 [A1–A2](#a1-创建-python-虚拟环境) 建好 `.venv` 并安装 `openpyxl`
（三件套 Excel 导出必需），这样 Node 能自动找到 `.venv`。

### B2. 安装前端依赖

```bash
npm ci
```

> 本步骤拉取 **486 个 npm 包**，约 1–2 分钟。

### B3. 配置环境变量

```bash
cp .env.example .env.local
```

> **`.env.local` 已被 `.gitignore` 排除，切勿提交，切勿改成 `NEXT_PUBLIC_*`。**

**最小可用配置**（仅本地文件存储 + 确定性模板模式，**不需要任何外部账号**）：

```ini
EXCAVAGUARD_STORAGE_PROVIDER=local
RAG_PROVIDER=local
LOCAL_RAG_BASE_URL=http://127.0.0.1:<方案A实际端口>
EXCAVAGUARD_PYTHON=<仓库绝对路径>/.venv/Scripts/python.exe
```

| 变量 | 说明 |
|---|---|
| `EXCAVAGUARD_STORAGE_PROVIDER` | `local` 走仓库 `var/` 目录；`supabase` 走云端（需下方密钥） |
| `RAG_PROVIDER` | `local` 走本机 sidecar（配合方案 A）；`pinecone` 走在线索引 |
| `LOCAL_RAG_BASE_URL` | 本地 sidecar 地址，**端口必须等于方案 A 实际监听的端口**（见下方说明） |
| `EXCAVAGUARD_PYTHON` | 建议填**绝对路径**，避免命中错误的解释器 |

> **`LOCAL_RAG_BASE_URL` 怎么填？** 先按方案 A 启动，终端会打印
> `✅ 服务已就绪： http://127.0.0.1:8666`，把其中的端口填进来即可。
> 也可以直接查询（把 `<端口>` 换成方案 A 打印的值）：
> ```bash
> curl http://127.0.0.1:<端口>/api/port
> ```
>
> 若方案 A 未启动、或此地址填写错误，工作台会在 AI 日报模式下报
> `RETRIEVER_UNAVAILABLE`。**改用 `report_mode=template` 则完全不依赖 RAG**，
> 适合先验证确定性计算链路。

**需要 AI 生成日报时**（可选，缺省走确定性模板，同样能出日报）：

```ini
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://api.你的供应商.com/v1     # 通常以 /v1 结尾
LLM_MODEL=可调用的模型ID
```

**需要云端存储时**（可选）：

```ini
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
SUPABASE_SECRET_KEY=
SUPABASE_STORAGE_BUCKET=excavaguard-private
```

> Supabase 基础设施准备与迁移执行方式见 [`supabase/README.md`](supabase/README.md)。
> 自检命令：`npm run supabase:check`（只读检查，不输出密钥）。

### B4. 启动

```bash
npm run dev
```

- 首页：<http://localhost:3000>
- **工作台：<http://localhost:3000/workbench>**
- 健康检查：<http://localhost:3000/api/health> 应返回 `{"status":"ok","service":"ExcavaGuard",...}`

端口被占用时：

```bash
npm run dev -- --port 3001
```

### B5. 工作台使用路径

进入 <http://localhost:3000/workbench>，按页面从上到下操作：

1. **填写工程条件**：安全等级、支护形式、基坑设计深度 H、报告日期等
2. **上传监测数据**：点击「选择文件」或虚线框里的「选择监测数据文件」，
   支持 `.csv / .tsv / .txt / .xlsx / .xlsm`
3. **可选上传用户规范**：不上传时直接使用默认规范库，不报错、不提示缺失
4. **点击「运行分析」**：默认勾选「生成并审计日报三件套」，
   成功后显示运行轨迹、下载入口和人工复核按钮

### 上传文件的列要求

必须包含 **5 个必填列**：

| 列名 | 说明 |
|---|---|
| 测点编号 | 测点标识 |
| 观测日期 | 观测时间 |
| 监测项目 | 如「沉降」「深层水平位移」 |
| 本次观测值 | 数值 |
| 单位 | 如 `mm`、`kN`、`m` |

基准值、上次值、间隔天数**可以缺失**，由阶段一按测点时序自动派生。

> `.xlsx` 读取依赖 Python 环境中的 `openpyxl`；CSV 路径是纯标准库，无需额外依赖。

### 示例数据

仓库已提供开箱可用的测试数据：

- `基坑监测7天数据/多工况/` — 6 个 CSV，覆盖 **浅基坑 / 深基坑 × 正常 / 中等预警 / 明显预警** 三种工况
- `final_test/监测数据整合_7天_10分钟.xlsx` — 7 天宽表整合数据（85 通道）

---

## 五、验证清单

部署完成后，逐项核对：

| # | 检查项 | 期望结果 |
|---|---|---|
| 1 | `stat -c "%s" models/bge-small-zh/pytorch_model.bin` | `95842633`（不是 `133`） |
| 2 | 运行 `start_demo.py --check-only` | 打印出一个 `http://127.0.0.1:<端口>` 地址 |
| 3 | 浏览器打开步骤 2 输出的地址 | 显示「知识库 8698 个条款块 / 30 部规范」 |
| 4 | 访问 `http://127.0.0.1:<端口>/api/port` | 返回 `{"port":<端口>,"url":"..."}` |
| 5 | Demo 点「规范条款检索」→ 搜「基坑顶部水平位移报警值」 | 返回带规范名 + 条款号的命中结果 |
| 6 | Demo 点「单点报警场景」→「核对规范并生成日报」 | 表格判定 + 5 节日报 Markdown |
| 7 | <http://localhost:3000/api/health> | `{"status":"ok",...}` |
| 8 | <http://localhost:3000/workbench> | 页面正常渲染 |
| 9 | `npm run check` | ESLint / TypeScript / Vitest 全通过 |

> 第 2–4 项使用**本机实际端口**，不要照抄文档里的示例端口号。

---

## 六、常见问题（FAQ）

| 现象 | 原因与处理 |
|---|---|
| 服务启动报 `WinError 10013` / 端口绑定失败 | 端口落在 Windows 保留段。**用 `start_demo.py` 启动可自动避让**；若手动指定端口则换一个，或用 `netsh interface ipv4 show excludedportrange protocol=tcp` 查看保留段 |
| 不知道服务跑在哪个端口 | 看启动输出里 `✅ 服务已就绪： http://127.0.0.1:<端口>` 那一行，或 `start_demo.py --check-only`，或请求 `/api/port` |
| 工作台报 `RETRIEVER_UNAVAILABLE` | `LOCAL_RAG_BASE_URL` 的端口与方案 A 实际端口不一致。按 `/api/port` 的返回值改正；或改用 `report_mode=template` 绕开 RAG |
| Demo 显示「知识库服务未就绪」 | ① `data/chroma_db/` 或 `models/` 未完整拷贝；② RAG 依赖没装；③ 模型权重是 LFS 指针 |
| 知识库显示 **0 个条款块** | 几乎必然是 **LFS 权重没拉取**。执行 `git lfs pull`，并核对文件大小是否为 95842633 字节 |
| 接口返回 `[ENGINE_UNAVAILABLE]` | Node 找不到 Python。在 `.env.local` 显式配置 `EXCAVAGUARD_PYTHON` 绝对路径 |
| Excel 上传报错 | Python 环境缺 `openpyxl`，执行 `pip install openpyxl` |
| 检索结果不准 | 规范扫描件 OCR 可能有错字，重建知识库：`python source/ocr_extract.py --workers 8 --dpi 200` 后 `python source/build_kb.py --rebuild` |
| 内存不足 | 本方案全 CPU 运行，`bge-small-zh` 仅需约 500 MB 内存 |
| `npm ci` 报 5 个高危告警 | 已知问题，来自 Next.js ESLint 插件的 `fast-glob → micromatch → braces` 链，无兼容修复方案。**不要执行 `npm audit fix --force`**（会把 ESLint 配置降到 14.x） |

---

## 七、开发者检查命令

```bash
npm run check        # ESLint + TypeScript 类型检查 + Vitest 全部测试
npm run test         # 仅运行测试
npm run test:watch   # 测试监听模式
npm run lint         # 仅 ESLint
npm run typecheck    # 仅类型检查
npm run build        # 生产构建，产物在 .next/
npm start            # 运行已构建的应用
```

Python 侧测试：

```bash
.venv\Scripts\python.exe -m pytest source/tests -q
```

> **沙箱/CI 环境提示**：若运行环境限制写入用户目录，可加 `CI=1 NEXT_TELEMETRY_DISABLED=1`，
> 使 Next.js 缓存落到项目内 `.next/cache/`：
> ```bash
> CI=1 NEXT_TELEMETRY_DISABLED=1 npm run build
> ```

---

## 八、依赖版本基线（实测可用组合）

**Python 侧**（实测于 Python 3.13.14）：

| 包 | 实测版本 |
|---|---|
| chromadb | 1.5.9 |
| sentence-transformers | 6.1.0 |
| torch | 2.14.1 (CPU) |
| openpyxl | 3.1.5 |
| fastapi | 0.143.1 |
| uvicorn | 0.54.0 |
| pydantic | 2.14.1 |

**Node 侧**（实测于 Node v22.22.2 / npm 10.9.7）：

| 用途 | 版本 |
|---|---|
| Web 全栈 | Next.js 16.4.0、React 19.3.0 |
| 类型与校验 | TypeScript 6.0.3、Zod 4.6.5 |
| 模型适配 | AI SDK 7.0.136、OpenAI 适配包 4.0.91 |
| 持久化客户端 | Supabase JS 2.117.3 |
| 向量库客户端 | Pinecone 9.0.0 |
| 检查与测试 | ESLint 9.39.5、Vitest 4.1.11 |

版本以 `package-lock.json` 为准。
TypeScript 7 尚不被当前 `eslint-config-next` 的解析器支持，因此固定 TypeScript 6。

---

## 验证记录

本文档所有关键步骤的实测证据（2026-10-15，Windows 11）：

| 验证项 | 实测结果 |
|---|---|
| **跨平台启动器 `start_demo.py --check-only`** | 输出 `[提示] 端口 8600 不可用（被占用或属系统保留段），已自动改用 8666。` + `http://127.0.0.1:8666` |
| **`server.py --port 8600` 自动避让** | 旧命令无需改动，自动改用 8666 并打印地址，**不再报 WinError 10013** |
| **`/api/port`** | 返回 `{"port":8666,"url":"http://127.0.0.1:8666"}` |
| **`start_demo.py` 就绪探测** | 输出 `✅ 服务已就绪： http://127.0.0.1:8666` |
| `npm ci` | 486 个包，约 1 分 43 秒，退出码 0 |
| `npm run dev` | `✓ Ready in 777ms`，3000 端口监听 |
| `/api/health` | HTTP 200，`{"status":"ok","service":"ExcavaGuard","stage":"scaffold"}` |
| `/workbench` | HTTP 200 |
| `/` (Next.js) | HTTP 200 |
| `source/server.py --port 8700` | `Uvicorn running on http://127.0.0.1:8700` |
| `/api/stats` | `chunks: 8698`，`doc_count: 30` |
| `/api/search` | 命中《JGJ120-2012》8.2.19，相关度 0.7778 |
| `/api/check` | 4 个测点全部识别：3号测点沉降 128% → 报警；CX1 深层水平位移 71% → 需关注；SW2 地下水位 80% → 需关注；ZC3 支撑轴力 89% → 需关注 |
| 日报输出 | 5 节结构完整，自动引用 GB 50497-2019 第 8.0.9 条报警程序 |
| 固定端口 `--port 8600`（改动前） | **失败**，`WinError 10013`（8566-8665 为 Windows 保留段）——这正是引入自动避让的原因 |
| 模型权重 SHA-256 | `5cc750eb4f5412313aba1482e53aeccd1ed0b97bc213f2962e0c80e6c8809319`，与 LFS 指针声明**完全一致** |

> **说明**：本机保留段恰好是 `8566-8665`，所以最近可用端口是 8666；
> 你的机器保留段不同，探测结果可能是 8666、8700 或其他值。**这属于预期行为**，
> 不影响安装步骤——始终以启动器打印的地址为准。

---

## 新增/改动的文件一览

为支持"换台电脑也能稳定拿到本机地址"，本次新增/改动以下文件：

| 文件 | 状态 | 作用 |
|---|---|---|
| `DEPLOY.md` | **新增** | 本文档 |
| `start_demo.py` | **新增** | 跨平台启动器：自动探测端口、依赖预检、就绪探测、打印本机 URL |
| `start_demo.bat` | **新增** | Windows 一键启动（双击运行） |
| `start_demo.sh` | **新增** | macOS / Linux 一键启动 |
| `source/server.py` | **改动** | 新增端口自动避让（真实 bind 探测）与 `/api/port` 接口 |

> `source/server.py` 为**向后兼容改动**：原有 `--port 8600` 命令仍可照常使用，
> 只是端口不可用时不再直接失败，而是自动改用可用端口并打印提示。
> 如需恢复严格行为，加 `--no-auto-port`。

---

## 相关文档

- [`README.md`](README.md) — 项目总览与架构说明
- [`source/README.md`](source/README.md) — RAG 知识库构建与 30 部规范清单
- [`rag/README.md`](rag/README.md) — 规范证据 Provider 与 Pinecone 导入流程
- [`supabase/README.md`](supabase/README.md) — 云端存储迁移与控制台操作
- [`final_test/README.md`](final_test/README.md) — 日报三件套交付验收
- [`AGENTS.md`](AGENTS.md) — 开发约定与协作规范

---

**免责声明**：本系统只输出**供工程师复核的草稿**，不自动发布预警，也不替代工程师审核或正式签发报告。
