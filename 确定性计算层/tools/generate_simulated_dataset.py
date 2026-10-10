"""
模拟监测数据生成器（覆盖多风险场景）
====================================

【性质声明 · 务必阅读】
------------------------------------------------------------------
本脚本生成的全部数据都是 **模拟/生成数据**，不是真实工程监测数据。

- 文件名含 `SIMULATED`
- 每条记录带 `data_origin = "simulated"`、`is_simulated = TRUE`
- 每条记录带 `source_dataset` 溯源字段
- 输出写入**独立目录** `data_simulated/`，与原始数据目录、derived/ 完全隔离
- 统计时与真实数据**分开计数**

【用途】
------------------------------------------------------------------
1. 覆盖《监测参数清单与规范依据》§5.1 的 S1~S17 全部风险场景 + 10 个扩展场景
   （S18~S23 深化场景，S24~S27 补齐参数缺口），为确定性计算与规范比对提供带真值的测试集；
2. 与真实数据**结合**一起送入三阶段流程（见 tools/run_combined_real_and_simulated.py），
   验证「真实数据 + 模拟数据」混合输入下的流程稳定性与可区分性。

【禁止】
------------------------------------------------------------------
- 不修改、不覆盖、不删除任何原始文件；
- 不把模拟数据当作真实工程数据对外输出结论；
- 不与真实数据合并统计而不加区分。

【模拟工程设定】
------------------------------------------------------------------
一级基坑 / 地下连续墙 / 开挖深度 H = 20 m / 日频观测 60 天
底板浇筑日：第 40 天（此后位移速率限值按 GB 50497-2019 表 8.0.4 注 ×0.7）

【阈值来源】
------------------------------------------------------------------
GB 50497-2019 表 8.0.4 / 表 8.0.5 / 第 8.0.9 条，
经 `standards/default/thresholds_gb50497_2019.json` 条文级摘录后由阶段三加载。

运行：
    python -B tools/generate_simulated_dataset.py
"""

from __future__ import annotations

import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "data_simulated"

# ---------------------------------------------------------------------------
# 工程设定
# ---------------------------------------------------------------------------
N_DAYS = 60
START = date(2026, 8, 1)
SLAB_DAY = 40
SOURCE_DATASET = "SIMULATED-EXCAVAGUARD-V1"

SAFETY_LEVEL = "一级"
SUPPORT_TYPE = "地下连续墙"
EXCAVATION_DEPTH_M = 20.0

DESIGN_VALUES = {
    "support_axial_force": 1000.0,   # kN，构件承载能力设计值 f2
    "anchor_axial_force": 200.0,     # kN，锚杆预应力设计值 fy
    "wall_internal_force": 500.0,
    "earth_pressure": 200.0,         # kPa
    "pore_pressure": 100.0,          # kPa
}


def d(i: int) -> str:
    return (START + timedelta(days=i)).isoformat()


# ---------------------------------------------------------------------------
# 轨迹函数
# ---------------------------------------------------------------------------
def t_sat(A: float, tau: float):
    """指数收敛：A*(1-e^(-t/tau))，用于"开挖后逐步收敛"的正常工况。"""
    return lambda t: A * (1 - math.exp(-t / tau))


def t_linear(target: float):
    return lambda t: target * t / (N_DAYS - 1)


def t_accel(target: float):
    """二次加速：用于"位移不收敛"。"""
    return lambda t: target * (t / (N_DAYS - 1)) ** 2


def t_decay(A0: float, Aend: float, tau: float):
    """从 A0 衰减到 Aend，用于锚杆预应力损失。"""
    return lambda t: A0 + (Aend - A0) * (1 - math.exp(-t / tau))


def t_phases(phases: list[tuple[int, float]], start: float = 0.0):
    """分段线性：phases = [(天数, 每日增量), ...]，自动累积保证连续。"""
    bounds, t, v = [], 0, start
    for days, per in phases:
        bounds.append((t, t + days, v, per))
        v += days * per
        t += days

    def f(x: float) -> float:
        for a, b, v0, per in bounds:
            if x < b:
                return v0 + (x - a) * per
        a, b, v0, per = bounds[-1]
        return v0 + (x - a) * per

    return f


# ---------------------------------------------------------------------------
# 场景定义
# ---------------------------------------------------------------------------
SCENARIOS: dict[str, dict] = {
    "S1": {"name": "正常稳定", "category": "变形过大", "level": "正常",
           "desc": "开挖后逐步收敛，各判据利用率 < 0.5"},
    "S2": {"name": "持续增长", "category": "变形过大", "level": "预警",
           "desc": "匀速持续增长，累计值利用率进入 0.7~1.0"},
    "S3": {"name": "突变异常", "category": "变形过大/支护受力异常", "level": "报警",
           "desc": "台阶式突变，变化速率超限（跳变后维持在新水平，属真实变形而非粗差）"},
    "S4": {"name": "累计值超限", "category": "变形过大", "level": "报警",
           "desc": "累计值越过限值"},
    "S5": {"name": "速率超限", "category": "变形过大", "level": "报警",
           "desc": "累计值未超限但变化速率超限"},
    "S6": {"name": "连续接近预警", "category": "变形过大", "level": "预警",
           "desc": "速率长期处于限值 70% 以上（连续 3 次超 70% 判据）"},
    "S7": {"name": "渗漏水关联", "category": "渗漏水与地下水异常", "level": "报警",
           "desc": "地下水位骤降并带动周边沉降"},
    "S8": {"name": "支撑轴力异常", "category": "支护受力异常", "level": "报警",
           "desc": "支撑轴力超过构件承载能力设计值的 60%"},
    "S9": {"name": "锚杆松弛", "category": "支护受力异常", "level": "报警",
           "desc": "锚杆轴力低于预应力设计值的 80%"},
    "S10": {"name": "多点联动异常", "category": "支护失稳风险", "level": "预警",
            "desc": "墙顶位移 + 深层位移 + 支撑轴力同步接近限值"},
    "S11": {"name": "位移不收敛", "category": "支护失稳风险", "level": "预警",
            "desc": "二次加速，瞬时速率显著高于序列平均速率（JGJ 120-2012 §8.2.23-2）"},
    "S12": {"name": "坑底隆起", "category": "支护失稳风险", "level": "报警",
            "desc": "坑底回弹累计值超限"},
    "S13": {"name": "数据缺测", "category": "数据质量异常", "level": "未知",
            "desc": "多期观测值缺失，该期弃权"},
    "S14": {"name": "粗差异常", "category": "数据质量异常", "level": "未知",
            "desc": "孤立尖峰（跳变后立即跳回），该期及相邻期不参与判定"},
    "S15": {"name": "单位与格式错误", "category": "数据质量异常", "level": "未知",
            "desc": "单位不可识别、数值非数值、日期无法解析"},
    "S16": {"name": "传感器漂移", "category": "数据质量异常", "level": "未知",
            "desc": "连续多期数值不变（FLATLINE），疑似传感器失效"},
    "S17": {"name": "危险报警综合", "category": "危险报警", "level": "危险报警",
            "desc": "多参数严重超限 + 触发 GB 50497-2019 第 8.0.9 条危险报警条件"},
    "S18": {"name": "底板浇筑后速率超限", "category": "变形过大", "level": "报警",
            "desc": "速率未超原限值，但超过底板浇筑后折减限值（×0.7）"},
    "S19": {"name": "裂缝发展", "category": "裂缝发展", "level": "危险报警",
            "desc": "既有裂缝宽度累计增长超过限值"},
    "S20": {"name": "建筑倾斜超限", "category": "变形过大", "level": "危险报警",
            "desc": "周边建筑倾斜度超过 2/1000"},
    "S21": {"name": "管线与道路沉降", "category": "变形过大", "level": "报警",
            "desc": "柔性管线与一般城市道路沉降超限"},
    "S22": {"name": "土压力与内力超限", "category": "支护受力异常", "level": "报警",
            "desc": "土压力、孔隙水压力、围护墙内力超过设计控制比例"},
    "S23": {"name": "建筑沉降速率超限", "category": "变形过大", "level": "危险报警",
            "desc": "周边建筑沉降速率超限"},
    # ---- 以下为补齐《监测参数清单与规范依据》参数缺口新增 ------------------
    "S24": {"name": "顶部竖向位移超限", "category": "变形过大", "level": "报警",
            "desc": "围护墙顶部竖向位移累计值超限（GB 50497-2019 表8.0.4）"},
    "S25": {"name": "地表裂缝发展", "category": "裂缝发展", "level": "报警",
            "desc": "地表既有裂缝持续发展超限、新增裂缝达到预警（表8.0.5）"},
    "S26": {"name": "管线水平位移超限", "category": "变形过大", "level": "报警",
            "desc": "柔性管线累计超限；刚性管道无累计值判据，仅速率接近预警（表8.0.5）"},
    "S27": {"name": "规范判据待补充", "category": "变形过大", "level": "未知",
            "desc": "立柱内力、土体分层竖向位移、土体温度：规范未给出预警值，按 §8.0.1 待设计方确定，一律弃权转人工复核"},
}


# ---------------------------------------------------------------------------
# 测点定义
#   traj        轨迹函数
#   jumps       [(天数, 增量), ...]   台阶式突变
#   missing     [天数, ...]           观测值缺失
#   mutate      [(天数, 字段, 值), ...]  字段级污染（格式/单位/粗差）
#   flatline    (起始天, 结束天)       连续数值不变
#   overrides   逐测点工程条件覆盖
#   exp_level   期望在序列中出现的最低（至少）风险等级
#   exp_blocked 期望出现「数据质量阻塞」弃权
#   exp_codes   期望被识别的数据质量问题码
# ---------------------------------------------------------------------------
P = lambda **kw: kw  # noqa: E731

POINTS: list[dict] = [
    # ---- S1 正常稳定 ------------------------------------------------------
    P(pid="ZQS-01", metric="wall_top_horizontal_displacement", sc="S1", unit="mm", direction="positive", traj=t_sat(8.0, 15.0)),
    P(pid="DB-01", metric="surface_settlement", sc="S1", unit="mm", direction="negative", traj=t_sat(-10.0, 15.0)),
    P(pid="LZ-01", metric="column_vertical_displacement", sc="S1", unit="mm", direction="negative", traj=t_sat(-8.0, 15.0)),

    # ---- S2 持续增长 ------------------------------------------------------
    P(pid="ZQS-02", metric="wall_top_horizontal_displacement", sc="S2", unit="mm", direction="positive", traj=t_linear(17.2)),
    P(pid="CX-01", metric="deep_horizontal_displacement", sc="S2", unit="mm", direction="positive", traj=t_linear(26.5)),
    P(pid="DB-02", metric="surface_settlement", sc="S2", unit="mm", direction="negative", traj=t_linear(-21.5)),

    # ---- S3 突变异常（置于底板浇筑前，避免叠加浇筑后速率折减）---------------
    P(pid="ZQS-03", metric="wall_top_horizontal_displacement", sc="S3", unit="mm", direction="positive",
      traj=t_linear(5.0), jumps=[(30, 2.2)]),
    P(pid="ZL-01", metric="support_axial_force", sc="S3", unit="kN", direction="positive",
      traj=t_linear(400.0), jumps=[(30, 300.0)]),

    # ---- S4 累计值超限 ----------------------------------------------------
    P(pid="ZQS-04", metric="wall_top_horizontal_displacement", sc="S4", unit="mm", direction="positive", traj=t_linear(21.5)),
    P(pid="CX-02", metric="deep_horizontal_displacement", sc="S4", unit="mm", direction="positive", traj=t_linear(33.5)),

    # ---- S5 速率超限（累计值不超限，仅速率超限；置于底板浇筑前）------------
    P(pid="ZQS-05", metric="wall_top_horizontal_displacement", sc="S5", unit="mm", direction="positive",
      traj=t_phases([(25, 0.05), (6, 2.2), (29, 0.05)])),
    P(pid="DB-03", metric="surface_settlement", sc="S5", unit="mm", direction="negative",
      traj=t_phases([(25, -0.08), (6, -2.2), (29, -0.08)])),

    # ---- S6 连续接近预警（累计值仅"关注"，靠速率与连续 3 次超 70% 判据）----
    P(pid="ZQS-06", metric="wall_top_horizontal_displacement", sc="S6", unit="mm", direction="positive",
      traj=t_phases([(20, 0.15), (3, 1.5), (1, 1.0), (36, 0.1)])),

    # ---- S7 渗漏水关联 ----------------------------------------------------
    P(pid="SW-01", metric="groundwater_level", sc="S7", unit="mm", direction="negative",
      traj=t_phases([(30, -2.0), (10, -104.0), (20, -2.0)])),
    P(pid="DB-04", metric="surface_settlement", sc="S7", unit="mm", direction="negative",
      traj=t_phases([(30, -0.05), (10, -1.4), (20, -0.05)])),

    # ---- S8 支撑轴力异常 --------------------------------------------------
    P(pid="ZL-02", metric="support_axial_force", sc="S8", unit="kN", direction="positive", traj=t_sat(700.0, 18.0)),
    P(pid="ZL-03", metric="support_axial_force", sc="S8", unit="kN", direction="positive",
      traj=t_sat(520.0, 18.0), exp_level="预警"),

    # ---- S9 锚杆松弛 ------------------------------------------------------
    P(pid="MG-01", metric="anchor_axial_force", sc="S9", unit="kN", direction="positive", traj=t_decay(200.0, 150.0, 25.0)),
    P(pid="MG-02", metric="anchor_axial_force", sc="S9", unit="kN", direction="positive",
      traj=t_decay(200.0, 170.0, 25.0), exp_level="预警"),

    # ---- S10 多点联动异常 -------------------------------------------------
    P(pid="ZQS-07", metric="wall_top_horizontal_displacement", sc="S10", unit="mm", direction="positive", traj=t_linear(19.2)),
    P(pid="CX-03", metric="deep_horizontal_displacement", sc="S10", unit="mm", direction="positive", traj=t_linear(29.3)),
    P(pid="ZL-04", metric="support_axial_force", sc="S10", unit="kN", direction="positive", traj=t_sat(555.0, 20.0)),

    # ---- S11 位移不收敛 ---------------------------------------------------
    P(pid="ZQS-08", metric="wall_top_horizontal_displacement", sc="S11", unit="mm", direction="positive", traj=t_accel(13.0)),
    P(pid="CX-04", metric="deep_horizontal_displacement", sc="S11", unit="mm", direction="positive", traj=t_accel(22.5)),

    # ---- S12 坑底隆起 -----------------------------------------------------
    P(pid="KD-01", metric="basal_heave", sc="S12", unit="mm", direction="positive", traj=t_linear(33.5)),
    P(pid="KD-02", metric="basal_heave", sc="S12", unit="mm", direction="positive",
      traj=t_linear(25.5), exp_level="预警"),

    # ---- S13 数据缺测 -----------------------------------------------------
    P(pid="ZQS-09", metric="wall_top_horizontal_displacement", sc="S13", unit="mm", direction="positive",
      traj=t_sat(6.0, 15.0), missing=[20, 21, 22, 30, 40, 41],
      exp_codes=["MISSING_VALUE"]),

    # ---- S14 粗差异常 -----------------------------------------------------
    P(pid="ZQS-10", metric="wall_top_horizontal_displacement", sc="S14", unit="mm", direction="positive",
      traj=t_sat(6.5, 15.0), mutate=[(35, "value", 95.0)],
      exp_blocked=True, exp_codes=["OUTLIER"]),

    # ---- S15 单位与格式错误 -----------------------------------------------
    P(pid="DB-05", metric="surface_settlement", sc="S15", unit="mm", direction="negative",
      traj=t_sat(-6.0, 15.0),
      mutate=[(25, "unit", "厘米"), (30, "value", "N/A"), (35, "timestamp", "昨天"), (40, "unit", "mm/s")],
      exp_blocked=True, exp_codes=["UNSUPPORTED_UNIT", "NON_NUMERIC_VALUE", "UNPARSED_TIMESTAMP"]),

    # ---- S16 传感器漂移 ---------------------------------------------------
    P(pid="ZQS-12", metric="wall_top_horizontal_displacement", sc="S16", unit="mm", direction="positive",
      traj=t_sat(4.0, 12.0), flatline=(21, 40),
      exp_blocked=True, exp_codes=["FLATLINE"]),

    # ---- S17 危险报警综合 -------------------------------------------------
    P(pid="ZQS-13", metric="wall_top_horizontal_displacement", sc="S17", unit="mm", direction="positive",
      traj=t_linear(40.0), overrides={"danger_signals": {"DANGER-1": True, "DANGER-2": True}}),
    P(pid="SW-02", metric="groundwater_level", sc="S17", unit="mm", direction="negative", traj=t_linear(-1300.0)),
    P(pid="DB-06", metric="surface_settlement", sc="S17", unit="mm", direction="negative", traj=t_linear(-32.0)),
    P(pid="ZL-05", metric="support_axial_force", sc="S17", unit="kN", direction="positive", traj=t_sat(780.0, 18.0)),

    # ---- S18 底板浇筑后速率超限 -------------------------------------------
    P(pid="ZQS-14", metric="wall_top_horizontal_displacement", sc="S18", unit="mm", direction="positive",
      traj=t_phases([(41, 0.08), (3, 1.5), (16, 0.05)])),

    # ---- S19 裂缝发展 -----------------------------------------------------
    P(pid="LF-01", metric="crack_width_building", sc="S19", unit="mm", direction="positive",
      traj=t_linear(1.8), overrides={"crack_state": "既有裂缝"}),
    P(pid="LF-02", metric="crack_width_building", sc="S19", unit="mm", direction="positive",
      traj=t_linear(1.2), overrides={"crack_state": "既有裂缝"}, exp_level="预警"),

    # ---- S20 建筑倾斜超限 -------------------------------------------------
    P(pid="JQ-01", metric="building_inclination", sc="S20", unit="1", direction="positive",
      traj=t_linear(0.0024), digits=6),
    P(pid="JQ-02", metric="building_inclination", sc="S20", unit="1", direction="positive",
      traj=t_linear(0.0016), digits=6, exp_level="预警"),

    # ---- S21 管线与道路沉降 -----------------------------------------------
    P(pid="GX-01", metric="pipeline_settlement", sc="S21", unit="mm", direction="negative",
      traj=t_linear(-3.3), overrides={"pipeline_type": "柔性管线"}),
    P(pid="DL-01", metric="road_settlement", sc="S21", unit="mm", direction="negative",
      traj=t_linear(-3.5), overrides={"road_type": "一般城市道路"}),

    # ---- S22 土压力与内力超限 ---------------------------------------------
    P(pid="TL-01", metric="earth_pressure", sc="S22", unit="kPa", direction="positive", traj=t_sat(135.0, 18.0)),
    P(pid="KX-01", metric="pore_pressure", sc="S22", unit="kPa", direction="positive", traj=t_sat(68.0, 18.0)),
    P(pid="QL-01", metric="wall_internal_force", sc="S22", unit="kN", direction="positive", traj=t_sat(330.0, 18.0)),

    # ---- S23 建筑沉降速率超限 ---------------------------------------------
    P(pid="JZ-01", metric="building_settlement", sc="S23", unit="mm", direction="negative",
      traj=t_phases([(56, -0.05), (4, -2.4)])),
    P(pid="JZ-02", metric="building_settlement", sc="S23", unit="mm", direction="negative",
      traj=t_phases([(56, -0.05), (4, -1.2)]), exp_level="预警"),

    # ---- S24 顶部竖向位移超限（补齐参数 #2）--------------------------------
    # 一级 + 地下连续墙：累计限值 min(10~20mm, 0.1%~0.2%×20m) = 10mm，速率限值 2mm/d
    P(pid="ZJS-01", metric="wall_top_vertical_displacement", sc="S24", unit="mm", direction="negative",
      traj=t_linear(-11.0)),
    P(pid="ZJS-02", metric="wall_top_vertical_displacement", sc="S24", unit="mm", direction="negative",
      traj=t_sat(-8.5, 15.0), exp_level="预警"),
    P(pid="ZJS-03", metric="wall_top_vertical_displacement", sc="S24", unit="mm", direction="negative",
      traj=t_sat(-3.0, 15.0), exp_level="正常"),

    # ---- S25 地表裂缝发展（补齐参数 #11 的地表裂缝部分）--------------------
    # 既有裂缝累计限值 min(10~15mm) = 10mm；新增裂缝累计限值 min(1~3mm) = 1mm
    P(pid="DBLF-01", metric="crack_width_surface", sc="S25", unit="mm", direction="positive",
      traj=t_linear(11.5), overrides={"crack_state": "既有裂缝"}),
    P(pid="DBLF-02", metric="crack_width_surface", sc="S25", unit="mm", direction="positive",
      traj=t_linear(0.85), overrides={"crack_state": "新增裂缝"}, exp_level="预警"),

    # ---- S26 管线水平位移超限（补齐参数 #19）------------------------------
    # 柔性管线：累计限值 min(3~5mm) = 3mm，速率限值 10mm/d
    # 刚性管道（压力）：无累计值判据，仅速率限值 10mm/d（置于底板浇筑前，避免 ×0.7 折减）
    P(pid="GXSP-01", metric="pipeline_horizontal_displacement", sc="S26", unit="mm", direction="negative",
      traj=t_linear(-3.2), overrides={"pipeline_type": "柔性管线"}),
    P(pid="GXSP-02", metric="pipeline_horizontal_displacement", sc="S26", unit="mm", direction="negative",
      traj=t_phases([(30, -0.05), (5, -7.5), (25, -0.05)]),
      overrides={"pipeline_type": "刚性管道（压力）"}, exp_level="预警"),
    P(pid="GXSP-03", metric="pipeline_horizontal_displacement", sc="S26", unit="mm", direction="negative",
      traj=t_sat(-1.0, 15.0), overrides={"pipeline_type": "柔性管线"}, exp_level="正常"),

    # ---- S27 规范判据待补充（补齐参数 #14 立柱内力、#18 土体分层竖向位移）---
    # 表8.0.4 对立柱内力标「—」，表8.0.4/8.0.5 均无土体分层竖向位移预警值，
    # 按 GB 50497-2019 §8.0.1 应由设计方确定 → 一律弃权，不得判为正常。
    P(pid="LZNL-01", metric="column_internal_force", sc="S27", unit="kN", direction="positive",
      traj=t_sat(300.0, 18.0)),
    P(pid="FCCJ-01", metric="soil_layered_vertical_displacement", sc="S27", unit="mm", direction="negative",
      traj=t_linear(-9.0)),
    P(pid="WD-01", metric="soil_temperature", sc="S27", unit="℃", direction="positive",
      traj=t_linear(6.0), digits=2),
]


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def build_records(spec: dict) -> tuple[list[dict], dict]:
    traj = spec["traj"]
    vals = [traj(t) for t in range(N_DAYS)]

    # 台阶式突变
    for day, delta in spec.get("jumps", []):
        for t in range(day, N_DAYS):
            vals[t] += delta

    # 传感器漂移：把一段区间拉平
    if spec.get("flatline"):
        a, b = spec["flatline"]
        held = vals[a]
        for t in range(a, min(b + 1, N_DAYS)):
            vals[t] = held

    # 字段级污染（粗差等），先作用在数值上
    mutate = spec.get("mutate", [])
    for day, field, value in mutate:
        if field == "value":
            vals[day] = value

    # 观测值缺失
    missing = set(spec.get("missing", []))
    for day in missing:
        vals[day] = None

    # 基准值与上次值：基准取首个有效观测，上次值取前一有效观测
    # "有效观测"= 数值可解析；非数值字符串（模拟格式污染）不推进基准/上次值/间隔，
    # 与阶段一的判定口径保持一致，避免间隔与"上一次有效观测"对不上。
    def _is_num(v) -> bool:
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            return False

    baseline = next((v for v in vals if v is not None and _is_num(v)), None)
    digits = spec.get("digits", 3)

    def rnd(v):
        """数值四舍五入；非数值（模拟格式污染）原样透传，交由阶段一识别。"""
        if v is None:
            return None
        try:
            return round(float(v), digits)
        except (TypeError, ValueError):
            return v

    rows = []
    prev = None
    prev_day = None
    for t in range(N_DAYS):
        cur = vals[t]
        # 间隔按"距上次有效观测"的真实天数给出：缺测期之后间隔会大于 1 天，
        # 这样变化速率不会被错误地按 1 天计算（否则会把缺测误判为速率异常）。
        gap_hours = "" if prev_day is None else (t - prev_day) * 24
        rec = {
            "point_id": spec["pid"],
            "timestamp": d(t),
            "metric": spec["metric"],
            "value": rnd(cur),
            "unit": spec["unit"],
            "direction": spec["direction"],
            "baseline_value": rnd(baseline),
            "previous_value": rnd(prev),
            "interval_hours": gap_hours,
            "scenario_id": spec["sc"],
            "scenario_name": SCENARIOS[spec["sc"]]["name"],
            "problem_category": SCENARIOS[spec["sc"]]["category"],
            "risk_level_expected": SCENARIOS[spec["sc"]]["level"],
            "data_origin": "simulated",
            "source_dataset": SOURCE_DATASET,
            "is_simulated": "TRUE",
            "note": "",
        }
        if t in missing:
            rec["note"] = "模拟：观测值缺失"
        if cur is not None and _is_num(cur):
            prev = cur
            prev_day = t
        rows.append(rec)

    # 非数值 / 单位 / 日期污染（作用在记录字段上）
    for day, field, value in mutate:
        if field in ("unit", "timestamp"):
            rows[day][field] = value
            rows[day]["note"] = (rows[day]["note"] + "；" if rows[day]["note"] else "") + f"模拟：{field} 污染"
        elif field == "value" and isinstance(value, str):
            rows[day]["value"] = value
            rows[day]["note"] = "模拟：数值字段非数值"
        elif field == "value":
            rows[day]["note"] = "模拟：孤立尖峰（粗差）"
    return rows, {"point_id": spec["pid"], "metric": spec["metric"], "scenario": spec["sc"]}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[1] 输出目录（与原始数据、derived/ 完全隔离）：{OUT}")

    all_rows: list[dict] = []
    manifest_points: list[dict] = []
    for spec in POINTS:
        rows, _meta = build_records(spec)
        all_rows.extend(rows)
        sc = SCENARIOS[spec["sc"]]
        manifest_points.append(
            {
                "point_id": spec["pid"],
                "metric_key": spec["metric"],
                "unit": spec["unit"],
                "scenario_id": spec["sc"],
                "scenario_name": sc["name"],
                "problem_category": sc["category"],
                "expected_level": spec.get("exp_level", sc["level"]),
                "expected_blocked": bool(spec.get("exp_blocked", False)),
                "expected_quality_codes": spec.get("exp_codes", []),
                "overrides": spec.get("overrides", {}),
                "records": len(rows),
            }
        )

    csv_path = OUT / "SIMULATED_基坑监测数据集_v1.csv"
    fields = [
        "point_id", "timestamp", "metric", "value", "unit", "direction",
        "baseline_value", "previous_value", "interval_hours",
        "scenario_id", "scenario_name", "problem_category", "risk_level_expected",
        "data_origin", "source_dataset", "is_simulated", "note",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)
    print(f"[2] 数据集：{csv_path.name}  （{len(all_rows)} 条记录 / {len(POINTS)} 个测点 / {N_DAYS} 天）")

    # 工程条件
    ctx = {
        "project_name": "SIM-地铁车站深基坑（模拟工程）",
        "is_simulated": True,
        "data_origin": "simulated",
        "source_dataset": SOURCE_DATASET,
        "safety_level": SAFETY_LEVEL,
        "support_type": SUPPORT_TYPE,
        "excavation_depth_m": EXCAVATION_DEPTH_M,
        "post_slab_from": d(SLAB_DAY),
        "post_slab_note": "底板浇筑后位移速率限值按 GB 50497-2019 表 8.0.4 注 ×0.7",
        "design_values": DESIGN_VALUES,
        "point_overrides": {p["point_id"]: p["overrides"] for p in manifest_points if p["overrides"]},
        "danger_signals_note": "S17 的 ZQS-13 触发 GB 50497-2019 第 8.0.9 条危险报警条件",
        "threshold_source": "standards/default/thresholds_gb50497_2019.json（GB 50497-2019 条文摘录）",
        "observation_window": {"start": d(0), "end": d(N_DAYS - 1), "freq": "1 天"},
        "disclaimer": "本工程为模拟工程，全部数据为模拟/生成数据，不得用于任何真实工程判定。",
    }
    ctx_path = OUT / "SIMULATED_工程条件_v1.json"
    ctx_path.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[3] 工程条件：{ctx_path.name}")

    # 场景清单
    by_scenario: dict[str, dict] = {}
    for p in manifest_points:
        node = by_scenario.setdefault(
            p["scenario_id"],
            {
                "scenario_id": p["scenario_id"],
                "scenario_name": p["scenario_name"],
                "description": SCENARIOS[p["scenario_id"]]["desc"],
                "problem_category": p["problem_category"],
                "expected_level": p["expected_level"],
                "points": [],
                "expected_blocked": False,
                "expected_quality_codes": [],
            },
        )
        node["points"].append(p["point_id"])
        node["expected_blocked"] = node["expected_blocked"] or p["expected_blocked"]
        for c in p["expected_quality_codes"]:
            if c not in node["expected_quality_codes"]:
                node["expected_quality_codes"].append(c)

    manifest = {
        "schema": "excavaguard.simulated_dataset/v1",
        "is_simulated": True,
        "data_origin": "simulated",
        "source_dataset": SOURCE_DATASET,
        "dataset_file": csv_path.name,
        "context_file": ctx_path.name,
        "records": len(all_rows),
        "points": len(POINTS),
        "days": N_DAYS,
        "scenario_count": len(by_scenario),
        "scenarios": list(by_scenario.values()),
        "point_details": manifest_points,
        "disclaimer": "全部为模拟/生成数据，与真实数据分开统计，不得用于真实工程判定。",
    }
    mf_path = OUT / "SIMULATED_场景清单_v1.json"
    mf_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[4] 场景清单：{mf_path.name}  （{len(by_scenario)} 个场景）")

    # 数据字典
    dict_md = OUT / "SIMULATED_数据字典_v1.md"
    dict_md.write_text(DATA_DICTIONARY, encoding="utf-8")
    print(f"[5] 数据字典：{dict_md.name}")

    readme = OUT / "README.md"
    readme.write_text(README, encoding="utf-8")
    print(f"[6] 说明：{readme.name}")

    print()
    print("=== 场景覆盖统计 ===")
    lv: dict[str, int] = {}
    for s in by_scenario.values():
        lv[s["expected_level"]] = lv.get(s["expected_level"], 0) + 1
    print("  场景数：", len(by_scenario))
    print("  期望等级分布：", lv)
    print("  数据质量类场景：", [k for k, v in by_scenario.items() if v["expected_quality_codes"]])
    print()
    print("★ 提醒：以上全部为【模拟/生成数据】，文件名含 SIMULATED，")
    print("  每条记录带 data_origin=simulated 与 source_dataset 溯源字段，与真实数据分开统计。")
    return 0


DATA_DICTIONARY = """# SIMULATED 数据集字段字典（v1）

> 本数据集为**模拟/生成数据**，不是真实工程监测数据。

## 记录字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `point_id` | string | 测点编号 |
| `timestamp` | ISO 8601 | 观测日期 |
| `metric` | string | 监测项键，与 `standards/default` 中的 `metric_key` 一致 |
| `value` | number | 观测值 |
| `unit` | string | 单位（mm / kN / kPa / 1） |
| `direction` | string | 方向（positive / negative） |
| `baseline_value` | number | 初始值（首个有效观测） |
| `previous_value` | number | 上次观测值（前一有效观测） |
| `interval_hours` | number | 与上次观测的间隔（小时），本数据集固定 24 |
| `scenario_id` | string | 场景编号 S1~S27 |
| `scenario_name` | string | 场景名称 |
| `problem_category` | string | 问题类别 |
| `risk_level_expected` | string | 该场景**期望**达到的风险等级（真值标签） |
| `data_origin` | string | **恒为 `simulated`** |
| `source_dataset` | string | 溯源标识 `SIMULATED-EXCAVAGUARD-V1` |
| `is_simulated` | string | **恒为 `TRUE`** |
| `note` | string | 人工注入说明（缺测/污染/粗差等） |

## 配套文件

| 文件 | 说明 |
|---|---|
| `SIMULATED_工程条件_v1.json` | 安全等级、支护形式、开挖深度 H、设计值、逐测点条件、底板浇筑日 |
| `SIMULATED_场景清单_v1.json` | 场景定义 + 测点 + **期望风险等级/期望数据质量码**（用于覆盖率验证） |

## 观测设定

- 观测窗口：60 天，日频
- 底板浇筑日：第 40 天（此后位移速率限值 ×0.7）
- 安全等级：一级；支护形式：地下连续墙；开挖深度 H = 20 m
"""

README = """# data_simulated —— 模拟/生成数据（与原始数据完全隔离）

## 性质

本目录内**全部为模拟/生成数据**，不是真实工程监测数据。

隔离措施：

1. 独立目录，**不在** `基坑智守项目相关数据/` 之下，也不与 `derived/` 混放；
2. 文件名统一含 `SIMULATED`；
3. 每条记录带 `data_origin = "simulated"`、`is_simulated = TRUE`；
4. 每条记录带 `source_dataset = "SIMULATED-EXCAVAGUARD-V1"` 溯源标识；
5. 汇总统计中 `simulated_records` 与 `real_records` **分列**，绝不合并。

## 用途

1. 为确定性计算与规范比对提供**带真值标签**的多风险测试集（S1~S27）；
2. 与真实数据结合，一起送入三阶段流程，验证混合输入下的流程稳定性。

## 生成

```
python -B tools/generate_simulated_dataset.py
```

## 验证

```
python -B tools/run_simulated_validation.py          # 场景覆盖率验证
python -B tools/run_combined_real_and_simulated.py   # 真实 + 模拟合并跑通
```

## 禁止

- 不得用于任何真实工程判定；
- 不得与真实数据合并统计而不加区分；
- 不得将其结果表述为工程结论。
"""


if __name__ == "__main__":
    sys.exit(main())
