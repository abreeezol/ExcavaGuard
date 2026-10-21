# -*- coding: utf-8 -*-
"""appendix_forms.py — GB 50497-2019 附录 A~G 监测日报表表式注册表。

供 convert_wide_to_appendix.py（宽表 → 附录表式日报表）与
gen_daily_report_rag.py（RAG 阈值判定 + 监测日报）共用，使 skill 对
附录 A~G 全部测项走同一套流程。

每个附录模板含：
  key          附录代号（A~G）
  name_cn      监测项目中文名（用于 RAG 检索与日报叙述）
  sheet_title  输出工作表名
  form_kind    "disp_a" / "disp_b" / "force_c" / "force_d" / "disp_e" / "crack_f" / "patrol_g"
               决定表头块、列、渲染方式
  point_prefix 宽表点号前缀（用于把宽表测点归属到该附录）
  rule_key     rag_alarm_rules.json 中的规则键（design_ratio 类需按点号细分，见 resolve_rule_key）
  unit         计量单位（仅用于说明与备注，不影响数值）
  header_lines 表头块文本（已合并通栏）
  columns      数据列表头
  footer_lines 表尾签栏文本（已合并通栏）

判定口径（与 rag_alarm_rules.json 一致）：
  * absolute 类（位移/水位/裂缝）：报警值取规范绝对值；累计占比 正常<70% / 需关注70~100% / 报警≥100%。
  * design_ratio 类（围护墙内力/立柱内力/土压力/孔隙水/支撑轴力/锚杆轴力）：
      报警值 = 设计值 × 比例（表8.0.4）；缺设计值则标「未判定」并注明依据的具体表号，
      不再写「需专项监测方案确认」。
"""
import re

# ----------------------------- 附录注册表 -----------------------------
APPENDIX_FORMS = {
    "A": {
        "key": "A",
        "name_cn": "水平位移(墙顶水平/竖向位移)",
        "sheet_title": "附表A_水平位移监测日报表",
        "form_kind": "disp_a",
        "point_prefix": "A",
        "rule_key": "围护墙顶部水平位移",
        "unit": "mm",
        "header_lines": [
            "第（      ）次",
            "工程名称：＿＿＿＿        报表编号：＿＿＿＿",
            "观测者：＿＿＿＿   计算者：＿＿＿＿   校核者：＿＿＿＿",
            "仪器型号：＿＿＿＿   仪器编号：＿＿＿＿   检定有效期：＿＿＿＿",
            "本次监测时间：＿＿＿＿        上次监测时间：＿＿＿＿",
        ],
        "columns": ["监测日期", "点号", "累计位移量(mm)", "本次变化量(mm)", "变化速率(mm/d)", "备注"],
        "footer_lines": [
            "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "工程负责人：＿＿＿＿        监测单位：＿＿＿＿",
            "第      页 共      页",
        ],
    },
    "B": {
        "key": "B",
        "name_cn": "深层水平位移",
        "sheet_title": "附表B_深层水平位移监测日报表",
        "form_kind": "disp_b",
        "rule_key": "深层水平位移",
        "unit": "mm",
        "header_lines": [
            "孔号（      ）第（      ）次",
            "工程名称：＿＿＿＿        报表编号：＿＿＿＿",
            "观测者：＿＿＿＿   计算者：＿＿＿＿   交核者：＿＿＿＿",
            "仪器型号：＿＿＿＿   仪器编号：＿＿＿＿   检定有效期：＿＿＿＿",
            "本次监测时间：＿＿＿＿",
        ],
        "columns": ["监测日期", "孔号(点号)", "深度(m)", "累计位移(mm)", "本次变化量(mm)", "变化速率(mm/d)", "备注"],
        "footer_lines": [
            "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "工程负责人：＿＿＿＿        监测单位：＿＿＿＿",
            "第      页 共      页",
        ],
    },
    "C": {
        "key": "C",
        "name_cn": "围护墙内力/立柱内力/土压力/孔隙水压力",
        "sheet_title": "附表C_围护墙内力等监测日报表",
        "form_kind": "force_c",
        "rule_key": None,  # 按点号前缀细分（见 FORCE_RULE_PREFIX）
        "unit": "kN·m / kPa",
        "header_lines": [
            "第（      ）次",
            "工程名称：＿＿＿＿        报表编号：＿＿＿＿",
            "天气：＿＿＿＿   观测者：＿＿＿＿   计算者：＿＿＿＿   校核者：＿＿＿＿",
            "仪器型号：＿＿＿＿   仪器编号：＿＿＿＿   检定有效期：＿＿＿＿",
            "本次监测时间：＿＿＿＿        上次监测时间：＿＿＿＿",
        ],
        "columns": ["监测日期", "孔号(点号)", "深度(m)", "本次测值", "上次测值", "本次变化", "累计变化", "组号", "备注"],
        "footer_lines": [
            "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "工程负责人：＿＿＿＿        监测单位：＿＿＿＿",
            "第      页 共      页",
        ],
    },
    "D": {
        "key": "D",
        "name_cn": "支撑轴力/锚杆轴力",
        "sheet_title": "附表D_支撑轴力等监测日报表",
        "form_kind": "force_d",
        "rule_key": None,  # 按点号前缀细分
        "unit": "kN",
        "header_lines": [
            "第（      ）次",
            "工程名称：＿＿＿＿        报表编号：＿＿＿＿",
            "观测者：＿＿＿＿   计算者：＿＿＿＿   校核者：＿＿＿＿",
            "仪器型号：＿＿＿＿   仪器编号：＿＿＿＿   检定有效期：＿＿＿＿",
            "本次监测时间：＿＿＿＿        上次监测时间：＿＿＿＿",
        ],
        "columns": ["监测日期", "孔号(点号)", "深度(m)", "本次测值", "上次测值", "本次变化", "累计变化", "组号", "备注"],
        "footer_lines": [
            "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "工程负责人：＿＿＿＿        监测单位：＿＿＿＿",
            "第      页 共      页",
        ],
    },
    "E": {
        "key": "E",
        "name_cn": "地下水位/地表竖向位移/分层竖向位移/坑底隆起",
        "sheet_title": "附表E_地下水位等监测日报表",
        "form_kind": "disp_e",
        "rule_key": None,  # 按点号前缀细分（见 DISP_E_RULE_PREFIX）
        "unit": "mm / m",
        "header_lines": [
            "第（      ）次",
            "工程名称：＿＿＿＿        报表编号：＿＿＿＿",
            "天气：＿＿＿＿   观测者：＿＿＿＿   计算者：＿＿＿＿   校核者：＿＿＿＿",
            "仪器型号：＿＿＿＿   仪器编号：＿＿＿＿   检定有效期：＿＿＿＿",
            "本次监测时间：＿＿＿＿        上次监测时间：＿＿＿＿",
        ],
        "columns": ["监测日期", "孔号(点号)", "初始高程", "本次高程", "上次高程", "本次变化", "累计变化", "变化速率", "编号", "备注"],
        "footer_lines": [
            "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "工程负责人：＿＿＿＿        监测单位：＿＿＿＿",
            "第      页 共      页",
        ],
    },
    "F": {
        "key": "F",
        "name_cn": "裂缝",
        "sheet_title": "附表F_裂缝监测日报表",
        "form_kind": "crack_f",
        "rule_key": "建筑结构性裂缝",
        "unit": "mm",
        "header_lines": [
            "第（      ）次",
            "工程名称：＿＿＿＿        报表编号：＿＿＿＿",
            "观测者：＿＿＿＿   计算者：＿＿＿＿   交核者：＿＿＿＿",
            "仪器型号：＿＿＿＿   仪器编号：＿＿＿＿   检定有效期：＿＿＿＿",
            "本次监测时间：＿＿＿＿        上次监测时间：＿＿＿＿",
        ],
        "columns": ["监测日期", "孔号(点号)", "长度(mm)", "宽度(mm)", "本次测试值", "单次变化", "累计变化", "变化速率", "形态", "备注"],
        "footer_lines": [
            "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "当日监测的简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "工程负责人：＿＿＿＿        监测单位：＿＿＿＿",
            "第      页 共      页",
        ],
    },
    "G": {
        "key": "G",
        "name_cn": "巡视检查",
        "sheet_title": "附表G_巡视检查日报表",
        "form_kind": "patrol_g",
        "rule_key": None,
        "unit": "（定性）",
        "header_lines": [
            "第（      ）次",
            "工程名称：＿＿＿＿        报表编号：＿＿＿＿",
            "巡视时间：＿＿＿＿   观测者：＿＿＿＿",
            "天气：＿＿＿＿   气温：＿＿＿＿",
        ],
        "columns": ["巡视部位", "巡视内容", "异常情况描述", "处理建议", "备注"],
        "footer_lines": [
            "工况描述：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "简要分析及判断性结论：＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿",
            "工程负责人：＿＿＿＿        监测单位：＿＿＿＿",
            "第      页 共      页",
        ],
    },
}

# design_ratio 类（C/D）按点号前缀细分到 rag_alarm_rules 规则键
FORCE_RULE_PREFIX = {
    "CN": "围护墙内力", "CL": "立柱内力",
    "CT": "围护墙侧向土压力", "CK": "孔隙水压力",
    "DN": "支撑轴力", "DM": "锚杆轴力",
}
# 附录 E 含多测项，按点号前缀细分
DISP_E_RULE_PREFIX = {
    "EW": "地下水位", "ES": "周边地表竖向位移", "EL": "周边地表竖向位移", "EB": "坑底隆起(回弹)",
}

# 颜色映射（与 gen 脚本 LEVEL_FILL 一致）
LEVEL_FILL = {"正常": "C6EFCE", "需关注": "FFEB9C", "报警": "FFC7CE", "未判定": "D9D9D9"}
LEVEL_FONT = {"正常": "006100", "需关注": "9C6500", "报警": "9C0006", "未判定": "3F3F3F"}


def get_appendix(key):
    return APPENDIX_FORMS.get(key)


def all_keys():
    return list(APPENDIX_FORMS.keys())


def resolve_form(point_id, sheet_title=""):
    """宽表点号 -> 附录代号（A~G）。优先点号首字母；其次 sheet 名关键词。"""
    pid = (point_id or "").strip().upper()
    if pid and pid[0] in APPENDIX_FORMS:
        return pid[0]
    title = (sheet_title or "")
    if "深层" in title or "测斜" in title:
        return "B"
    if "内力" in title or "土压力" in title or "孔隙水" in title:
        return "C"
    if "轴力" in title or "锚杆" in title:
        return "D"
    if "水位" in title or "竖向位移" in title or "坑底隆起" in title:
        return "E"
    if "裂缝" in title:
        return "F"
    if "巡视" in title:
        return "G"
    return "A"


def resolve_rule_key(form_key, point_id, override=None):
    """返回该测点在 rag_alarm_rules 中的规则键。"""
    if override:
        return override
    pid = (point_id or "").strip().upper()
    if form_key in ("C", "D"):
        pre = pid[:2]
        return FORCE_RULE_PREFIX.get(pre)
    if form_key == "E":
        pre = pid[:2]
        return DISP_E_RULE_PREFIX.get(pre)
    f = APPENDIX_FORMS.get(form_key)
    return f.get("rule_key") if f else None


def compute_alarm(rule, level, design_value=None):
    """根据 rag_alarm_rules 规则计算累计报警值。

    返回 (alarm_cum, note)：
      * absolute 类：直接取 level 的 cum（取区间下界）。
      * design_ratio 类：需 design_value；alarm = design_value × pct/100（pct 取该 level）。
        缺 design_value -> (None, 未判定说明，注明表号)。
    """
    if not rule:
        return None, "未配置阈值规则"
    lvl = rule.get("level%d" % level)
    if not lvl:
        return None, "规则未定义该安全等级"
    if rule.get("type") == "design_ratio":
        pct = (lvl.get("pct") or rule.get("design_pct", {}).get({1: "一级", 2: "二级", 3: "三级"}.get(level, "一级")) or 80)
        if design_value in (None, 0):
            src = rule.get("source", "GB 50497-2019 表8.0.4")
            return None, "报警值=设计值×%s%%（%s），本测点缺设计值，依规范无法量化判定" % (pct, src)
        return design_value * pct / 100.0, ""
    # absolute
    cum = lvl.get("cum")
    if isinstance(cum, list):
        return cum[0], ""
    return cum, ""


def judge(cum, alarm_cum):
    """返回 (level, ratio)。alarm_cum 为 None -> 未判定。"""
    if alarm_cum in (None, 0):
        return "未判定", None
    # 按"量值"判定（取绝对值）：隆起/沉降、受压方向差异不应掩盖超限事实
    ratio = abs(cum) / float(alarm_cum)
    if ratio >= 1.0:
        return "报警", round(ratio * 100.0, 1)
    if ratio >= 0.7:
        return "需关注", round(ratio * 100.0, 1)
    return "正常", round(ratio * 100.0, 1)


def _fmt_num(x):
    """智能格式化数值：整数显示整数，小数保留最多 3 位有效小数（去除尾随 0）。"""
    if x is None:
        return "—"
    f = float(x)
    if f == int(f):
        return str(int(f))
    return ("%.3f" % f).rstrip("0").rstrip(".")


def level_note(lvl, alarm_cum, ratio, unit="mm", extra=""):
    """生成写入「备注」列的预警等级说明。"""
    disp = {"正常": "正常", "需关注": "黄色(需关注)", "报警": "红色(报警)", "未判定": "未判定"}[lvl]
    if lvl == "未判定":
        return "预警等级：未判定；" + (alarm_cum or "缺报警值/设计值，依规范无法量化判定") + ("；" + extra if extra else "")
    alarm_txt = _fmt_num(alarm_cum) if alarm_cum else "未配置"
    return ("预警等级：%s；报警值：%s %s；占报警值：%s%%；超报警值：%s；"
            % (disp, alarm_txt, unit, ratio if ratio is not None else "—",
               "是" if (ratio is not None and ratio >= 100.0) else "否")) + ("本次变化量/变化速率由累计序列推算；" + extra if extra else "本次变化量/变化速率由累计序列推算")


def render_row(form_key, rec, unit="mm"):
    """按附录表式把一条 rec 渲染成与 columns 对齐的值列表。

    rec 字段：date, point, cum(累计变化), delta(本次变化), rate(变化速率),
             base(前次累计，用于本次/上次测值), depth(可选), note(等级备注)
    """
    pid = rec.get("point", "")
    cum = rec.get("cum", 0.0)
    delta = rec.get("delta", 0.0)
    rate = rec.get("rate", 0.0)
    base = rec.get("base", cum - delta)
    note = rec.get("note", "")
    kind = APPENDIX_FORMS[form_key]["form_kind"]

    def r1(x):
        return round(x, 1)

    if kind == "disp_a":
        return [rec.get("date"), pid, r1(cum), r1(delta), round(rate, 2), note]
    if kind == "disp_b":
        return [rec.get("date"), pid, rec.get("depth", "—"), r1(cum), r1(delta), round(rate, 2), note]
    if kind in ("force_c", "force_d"):
        # 本次测值/上次测值 用累计序列端点（累计变化口径，注明推算）
        return [rec.get("depth", "—"), r1(cum), r1(base), r1(delta), r1(cum), "—", pid, note]
    if kind == "disp_e":
        return ["—", "—", "—", r1(delta), r1(cum), round(rate, 2), "—", pid, note]
    if kind == "crack_f":
        return ["—", r1(cum), r1(cum), r1(delta), r1(cum), round(rate, 2), pid, "—", note]
    # patrol_g 等其它：通用占位
    return [pid, "", "", note]
