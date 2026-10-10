# 引擎桥接冒烟测试

> 目的：证明「Web 入口（Node/TypeScript）→ 确定性计算引擎（Python）」这条单点链路**可打通**。
> 状态：✅ **已验证通过**（2026-10-10，13/13 项）

---

## 这是什么

| 文件 | 角色 | 迁入远程仓库后的位置 |
|---|---|---|
| `skills/evaluate-thresholds/scripts/run_judgement.py` | 引擎桥接脚本（stdin/stdout JSON） | **就是目标位置**（远程 README 规定业务脚本放 `skills/<name>/scripts/`） |
| `tools/bridge-smoke/run_judgement.mjs` | Node 调用器（纯 Node，无依赖） | 逻辑原样搬进 `src/server/skills/evaluate-thresholds/runner.ts` |

`run_judgement.mjs` **不是**最终产物，而是 `runner.ts` 的**可运行原型**：
`spawnJudgement()` 函数可以直接翻译成 TypeScript，其余为冒烟测试代码。

---

## 为什么这样设计

### 1. 不改引擎一行

桥接脚本只做协议转换（JSON ⇄ Python 对象），判定逻辑全部留在
`确定性计算层/pipeline/`。这保证「同一输入必得同一输出」这条确定性性质不被破坏。

### 2. 子进程而非重写

远程 README 已规定确定性 Skill 放 `skills/<name>/scripts/`，但没规定语言。
三条路线中：

| 路线 | 判断 |
|---|---|
| **① Python 子进程** | ✅ **采用**。改动最小，引擎零修改 |
| ② 独立 Python 服务（FastAPI） | 后续可升级，与远程已有的 loopback RAG 模式一致 |
| ③ 用 TypeScript 重写引擎 | ❌ **不采用**。二次实现会给已验证的判定逻辑引入偏差 |

### 3. 引擎零第三方依赖

实测（AST 扫描 `pipeline/**/*.py`）：非标准库导入为**空**。
所以子进程方案不需要任何 `pip install`，部署摩擦极低。

---

## 协议

### 请求（stdin）

```json
{
  "records": [
    {"point_id": "WTHD-01", "timestamp": "2026-08-01",
     "metric": "wall_top_horizontal_displacement", "value": 0.0, "unit": "mm"}
  ],
  "context": {
    "safety_level": "一级",
    "support_type": "地下连续墙",
    "excavation_depth_m": 20.0,
    "design_values": {"support_axial_force": 1000.0},
    "post_slab_from": "2026-09-10",
    "point_overrides": {"LF-01": {"crack_state": "既有裂缝"}}
  },
  "options": {
    "expected_interval_days": 1.0,
    "report_date": "2026-08-07",
    "project": {"name": "××基坑工程"},
    "standards_dir": null
  }
}
```

> `records` 支持**用户原始表形态**：只需 `point_id / timestamp / metric / value / unit`，
> 初始值、上次值、观测间隔由阶段一按测点时序派生（见 `09_用户数据文件契约.md`）。

### 响应（stdout）

```json
{
  "schema": "excavaguard.skill_result/v1",
  "skill": "evaluate-thresholds",
  "ok": true,
  "result": { "...": "excavaguard.daily_report_input/v1 载荷" },
  "summary": { "...": "阶段汇总" },
  "trace": {"elapsed_ms": 214, "records": 7, "engine_dir": "...", "python": "3.13.12"}
}
```

出错时仍返回 JSON，退出码非 0：

```json
{"schema": "...", "skill": "...", "ok": false,
 "error": {"code": "INVALID_INPUT", "message": "..."}}
```

| 退出码 | 含义 |
|:--:|---|
| 0 | 成功 |
| 2 | 输入非法（空 stdin / 非法 JSON / 缺 records / 缺 context） |
| 3 | 引擎异常或引擎目录不存在 |

---

## 运行

```bash
cd ExcavaGuard

# 指定 Python 解释器（生产环境应由配置注入）
export EXCAVAGUARD_PYTHON=/path/to/python

node tools/bridge-smoke/run_judgement.mjs
node tools/bridge-smoke/run_judgement.mjs --request my_request.json
```

### 环境变量

| 变量 | 用途 | 默认 |
|---|---|---|
| `EXCAVAGUARD_PYTHON` | Python 解释器路径 | 依次尝试 `PYTHON` → `python3` → `python` |
| `EXCAVAGUARD_ENGINE_DIR` | 引擎根目录（含 `pipeline/`） | 按脚本相对位置推断 |
| `EXCAVAGUARD_BRIDGE_TIMEOUT_MS` | 子进程超时 | `30000` |

---

## 实测结果

```
========================================================================
引擎桥接冒烟测试（Node → Python）
========================================================================
脚本      : .../skills/evaluate-thresholds/scripts/run_judgement.py
记录数    : 7

[PASS] 引擎返回成功
[PASS] 信封 schema 正确
[PASS] skill 标识正确
[PASS] 返回日报载荷
[PASS] 载荷 schema 正确
[PASS] 载荷含逐条明细
[PASS] 载荷含报警清单
[PASS] 载荷含规范条文依据
[PASS] 原始观测表被正确识别（非全量弃权）
[PASS] trace 含耗时
[PASS] 往返耗时 < 10s

  风险分布 : {"未知":1,"危险报警":6}
  末条等级 : 危险报警
  限值依据 : min(绝对量 20 mm, 0.2%×H=40 mm) = 20 mm
[PASS] 空 records 被拒绝且错误码正确
[PASS] 缺 context 被拒绝

PASS: 13    FAIL: 0
全部通过 —— 引擎与入口可打通
```

**关键证据**：Node 侧只传了 5 列的原始观测记录（无 baseline / previous / interval），
引擎完成时序派生、三项计算、规范比对，返回带 `GB 50497-2019 表8.0.4` 条文依据的完整载荷。

---

## 迁入远程仓库的步骤

```text
① 拷贝 skills/evaluate-thresholds/scripts/run_judgement.py
   → 远程仓库同路径（skills/evaluate-thresholds/scripts/）

② 新建 src/server/skills/evaluate-thresholds/runner.ts
   → 把 spawnJudgement() 翻译成 TS，补齐：
     · readIntegrationConfig("engine") 读取解释器路径与超时
     · 失败时抛 EvidenceRetrievalError 同款的 SkillExecutionError
     · 用 src/contracts/ 的 Zod schema 校验 result

③ 新建 src/contracts/daily-report-input.ts
   → 把 contracts/daily_report_input.schema.json 转成 Zod schema

④ 替换 src/app/api/runs/route.ts 的 501
   → 调用 runner，返回 result

⑤ 把 src/server/skills/registry.ts 中 evaluate-thresholds 的
   status 从 "not_implemented" 改为 "implemented"
```

---

## 已知限制

| # | 限制 | 影响 | 后续 |
|:--:|---|---|---|
| 1 | 依赖宿主机有 Python | Serverless / Vercel 无法运行 | 改走路线 ②（独立服务） |
| 2 | 大文件子进程内存与超时 | 30 万行以上可能超时 | 上传侧限制行数，或改流式 |
| 3 | Windows 默认编码 | 已强制 `PYTHONIOENCODING=utf-8` | — |
| 4 | 缺 `excavation_depth_m` 时只用绝对量限值 | 累计值判定可能偏松 | 引擎侧修 P1-2；桥接层已输出 WARN |
