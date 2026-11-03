"""隧道监测日报表式（GB 50911-2013 附录 C / 附录 D）
==================================================

为什么不能沿用基坑附录 A~G
--------------------------
基坑的表式来自 GB 50497-2019 附录，按"水平位移 / 深层水平位移 / 内力 /
轴力 / 水位 / 裂缝"分 6 类；隧道（城市轨道交通）的法定表式来自
**GB 50911-2013 附录 D**，只有 4 类，而且列结构不同：

    附录 D.0.1  水平位移、竖向位移监测日报表   ← 拱顶沉降与净空收敛同属此表
    附录 D.0.2  深层水平位移监测日报表
    附录 D.0.3  轴力（拉力）监测日报表
    附录 D.0.4  应力、压力监测日报表

关键差异（决定了不能直接套用）：
1. D 表把"初始值、控制值（累计/速率）、预警等级"做成独立列；基坑表 A 没有控制值列。
2. D 表把"本次/上次监测时间、仪器型号/出厂编号/检定日期"放在**表头**，表体不再逐行写日期。
3. D.0.3 轴力表用"上次测值/本次测值"（绝对读数），基坑表 D 用累计变化口径。
4. 现场巡查按工法分表（附录 C.0.1 明挖/盖挖、C.0.2 盾构、C.0.3 矿山法），
   基坑表 G 是一张通用清单。

依据条文：GB 50911-2013 第 11.0.5 条明确日报第 3 项为"监测项目日报表……可采用本规范
附录 D 的样式"。因此隧道场景**必须**使用本模块的表式。

表式登记内容只描述"长什么样"，不含任何阈值；数值一律来自冻结载荷。
"""

from __future__ import annotations

import re

# --- 附录 D 表式 ----------------------------------------------------------
# header_lines: 表头文字块（第 1 行为表名，渲染时按 project_line/date_line 注入工程信息）
# header_rows: 表头行数（1 = 单行；2 = "控制值" 这类合并表头）
# columns: 逻辑列数（与 header_row1 长度一致）
# row_keys: 每列对应的取值键，由 report_artifacts 的行构造器实现

_AUTHOR_LINES = [
    "现场监测人：＿＿＿＿　　计算人：＿＿＿＿　　校核人：＿＿＿＿",
    "监测项目负责人：＿＿＿＿　　监测单位：＿＿＿＿",
    "第　页　共　页",
]

TUNNEL_FORMS: dict[str, dict] = {
    "表D1": {
        "key": "D1",
        "clause": "D.0.1",
        "name_cn": "水平位移、竖向位移监测日报表",
        "sheet_title": "附表D1_水平位移竖向位移监测日报表",
        "file_label": "附表D1_水平位移竖向位移监测日报表",
        "unit": "mm",
        "header_rows": 2,
        "project_line": 2,
        "date_line": 3,
        "header_lines": [
            "表 D.0.1　水平位移、竖向位移监测日报表",
            "监测工程名称：{project_name}　　报表编号：{report_no}　　天气：{weather}",
            "本次监测时间：{time_current}　　上次监测时间：{time_previous}",
            "仪器型号：{instrument_model}　　仪器出厂编号：{instrument_serial}　　检定日期：{calibrated_at}",
            "",
        ],
        "header_row1": [
            "监测点号", "初始值(mm)", "上次累计变化量(mm)", "本次累计变化量(mm)",
            "本次变化量(mm)", "变化速率(mm/d)", "控制值", "", "预警等级", "备注",
        ],
        "header_row2": [
            "", "", "", "", "", "", "累计变化值(mm)", "变化速率值(mm/d)", "", "",
        ],
        "merge_groups": [(7, 8)],   # 第 7~8 列在第二表头行合并为"控制值"下的两列
        "columns": [
            "监测点号", "初始值(mm)", "上次累计变化量(mm)", "本次累计变化量(mm)",
            "本次变化量(mm)", "变化速率(mm/d)", "控制值-累计变化值(mm)",
            "控制值-变化速率值(mm/d)", "预警等级", "备注",
        ],
        "footer_lines": _AUTHOR_LINES,
        "basis": "GB 50911-2013 表 D.0.1",
    },
    "表D2": {
        "key": "D2",
        "clause": "D.0.2",
        "name_cn": "深层水平位移监测日报表",
        "sheet_title": "附表D2_深层水平位移监测日报表",
        "file_label": "附表D2_深层水平位移监测日报表",
        "unit": "mm",
        "header_rows": 2,
        "project_line": 2,
        "date_line": 3,
        "header_lines": [
            "表 D.0.2　深层水平位移监测日报表",
            "监测工程名称：{project_name}　　报表编号：{report_no}　　天气：{weather}",
            "本次监测时间：{time_current}　　上次监测时间：{time_previous}",
            "仪器型号：{instrument_model}　　仪器出厂编号：{instrument_serial}　　检定日期：{calibrated_at}",
            "",
        ],
        "header_row1": [
            "监测孔号", "深度(m)", "上次累计变化量(mm)", "本次累计变化量(mm)",
            "本次变化量(mm)", "变化速率(mm/d)", "控制值", "", "监测深度-位移变化量曲线图",
        ],
        "header_row2": [
            "", "", "", "", "", "", "累计变化值(mm)", "变化速率值(mm/d)", "",
        ],
        "merge_groups": [(7, 8)],
        "columns": [
            "监测孔号", "深度(m)", "上次累计变化量(mm)", "本次累计变化量(mm)",
            "本次变化量(mm)", "变化速率(mm/d)", "控制值-累计变化值(mm)",
            "控制值-变化速率值(mm/d)", "监测深度-位移变化量曲线图",
        ],
        "footer_lines": _AUTHOR_LINES,
        "basis": "GB 50911-2013 表 D.0.2",
    },
    "表D3": {
        "key": "D3",
        "clause": "D.0.3",
        "name_cn": "轴力（拉力）监测日报表",
        "sheet_title": "附表D3_轴力拉力监测日报表",
        "file_label": "附表D3_轴力拉力监测日报表",
        "unit": "kN",
        "header_rows": 2,
        "project_line": 2,
        "date_line": 3,
        "header_lines": [
            "表 D.0.3　轴力（拉力）监测日报表",
            "监测工程名称：{project_name}　　报表编号：{report_no}　　天气：{weather}",
            "本次监测时间：{time_current}　　上次监测时间：{time_previous}",
            "仪器型号：{instrument_model}　　仪器出厂编号：{instrument_serial}　　检定日期：{calibrated_at}",
            "",
        ],
        "header_row1": [
            "监测点号", "初始值(kN)", "上次测值(kN)", "本次测值(kN)",
            "本次变化值(kN)", "变化速率(kN/d)", "控制值", "", "预警等级", "备注",
        ],
        "header_row2": [
            "", "", "", "", "", "", "最大值(kN)", "最小值(kN)", "", "",
        ],
        "merge_groups": [(7, 8)],
        "columns": [
            "监测点号", "初始值(kN)", "上次测值(kN)", "本次测值(kN)", "本次变化值(kN)",
            "变化速率(kN/d)", "控制值-最大值(kN)", "控制值-最小值(kN)", "预警等级", "备注",
        ],
        "footer_lines": _AUTHOR_LINES,
        "basis": "GB 50911-2013 表 D.0.3",
    },
    "表D4": {
        "key": "D4",
        "clause": "D.0.4",
        "name_cn": "应力、压力监测日报表",
        "sheet_title": "附表D4_应力压力监测日报表",
        "file_label": "附表D4_应力压力监测日报表",
        "unit": "kPa",
        "header_rows": 1,
        "project_line": 2,
        "date_line": 3,
        "header_lines": [
            "表 D.0.4　应力、压力监测日报表",
            "监测工程名称：{project_name}　　报表编号：{report_no}　　天气：{weather}",
            "本次监测时间：{time_current}　　上次监测时间：{time_previous}",
            "仪器型号：{instrument_model}　　仪器出厂编号：{instrument_serial}　　检定日期：{calibrated_at}",
            "",
        ],
        "header_row1": [
            "监测点号", "初始值(kPa)", "上次测值(kPa)", "本次测值(kPa)",
            "本次变化值(kPa)", "变化速率(kPa/d)", "控制值(kPa)", "预警等级", "备注",
        ],
        "header_row2": None,
        "merge_groups": [],
        "columns": [
            "监测点号", "初始值(kPa)", "上次测值(kPa)", "本次测值(kPa)", "本次变化值(kPa)",
            "变化速率(kPa/d)", "控制值(kPa)", "预警等级", "备注",
        ],
        "footer_lines": _AUTHOR_LINES,
        "basis": "GB 50911-2013 表 D.0.4",
    },
}

# --- 附录 C 现场巡查报表 ---------------------------------------------------
# GB 50911-2013 第 11.0.5 条第 1 款第 2 项要求日报包含"现场巡查信息：巡查照片、记录等"；
# 附录 C 按工法给出三张表，列结构统一为「分类 | 巡查内容 | 巡查结果 | 备注」。
# 这里登记的是**规范列出的应巡查内容**，用于核对巡查表是否覆盖齐全；
# 巡查结果只能来自现场记录，本模块不含任何"默认正常"。

_COMMON_ENVIRONMENT = [
    "建（构）筑物、桥梁墩台或梁体、既有轨道交通结构等的裂缝位置、数量和宽度，"
    "混凝土剥落位置、大小和数量，设施能否正常使用",
    "地下构筑物积水及渗水情况，地下管线的漏水、漏气情况",
    "周边路面或地表的裂缝、沉陷、隆起、冒浆的位置、范围等情况",
    "河流湖泊的水位变化情况，水面有无出现漩涡、气泡及其位置、范围，"
    "堤坡裂缝宽度、深度、数量及发展趋势等",
    "工程周边开挖、堆载、打桩等可能影响工程安全的其他生产活动",
    "其他",
]

_COMMON_FACILITIES = [
    "基准点、监测点的完好状况、保护情况",
    "监测元器件的完好状况、保护情况",
    "其他",
]

_PATROL_FOOTER = [
    "现场巡查人：＿＿＿＿　　监测项目负责人：＿＿＿＿　　监测单位：＿＿＿＿",
    "第　页　共　页",
]

PATROL_FORMS: dict[str, dict] = {
    "表C1": {
        "key": "C1",
        "clause": "C.0.1",
        "name_cn": "明挖法和盖挖法的基坑现场巡查报表",
        "sheet_title": "附表C1_明挖法和盖挖法基坑现场巡查报表",
        "methods": ["明挖法", "盖挖法", "明挖", "盖挖"],
        "header_lines": [
            "表 C.0.1　明挖法和盖挖法的基坑现场巡查报表",
            "监测工程名称：{project_name}　　报表编号：{report_no}",
            "巡查时间：{patrol_time}　　天气：{weather}",
            "",
        ],
        "columns": ["分类", "巡查内容", "巡查结果", "备注"],
        "categories": [
            ("施工工况", [
                "开挖长度、分层高度及坡度，开挖面暴露时间",
                "开挖面岩土体的类型、特征、自稳性，渗漏水量大小及发展情况",
                "降水、回灌等地下水控制效果及设施运转情况",
                "基坑侧壁及周边地表截、排水措施及效果，坑边或基底有无积水",
                "支护桩（墙）后土体有无裂缝、明显沉陷，基坑侧壁或基底有无涌土、流砂、管涌",
                "基坑周边有无超载",
                "放坡开挖的基坑边坡有无位移、坡面有无开裂",
                "其他",
            ]),
            ("支护结构", [
                "支护桩（墙）有无裂缝、侵限情况",
                "冠梁、围檩的连续性，围檩与桩（墙）之间的密贴性，围檩与支撑的防坠落措施",
                "冠梁、围檩、支撑有无过大变形或裂缝",
                "支撑是否及时架设",
                "盖挖法顶板有无明显变形和开裂，顶板与立柱、墙体的连接情况",
                "锚杆、土钉垫板有无明显变形、松动",
                "止水帷幕有无开裂、较严重渗漏水",
                "其他",
            ]),
            ("周边环境", _COMMON_ENVIRONMENT),
            ("监测设施", _COMMON_FACILITIES),
        ],
        "footer_lines": _PATROL_FOOTER,
        "basis": "GB 50911-2013 表 C.0.1",
    },
    "表C2": {
        "key": "C2",
        "clause": "C.0.2",
        "name_cn": "盾构法隧道现场巡查报表",
        "sheet_title": "附表C2_盾构法隧道现场巡查报表",
        "methods": ["盾构法", "盾构"],
        "header_lines": [
            "表 C.0.2　盾构法隧道现场巡查报表",
            "监测工程名称：{project_name}　　报表编号：{report_no}",
            "巡查时间：{patrol_time}　　天气：{weather}",
            "",
        ],
        "columns": ["分类", "巡查内容", "巡查结果", "备注"],
        "categories": [
            ("施工工况", [
                "盾构始发端、接收端土体加固情况",
                "盾构掘进位置（环号）",
                "盾构停机、开仓等的时间和位置",
                "联络通道开洞口情况",
                "其他",
            ]),
            ("管片变形", [
                "管片破损、开裂、错台情况",
                "管片渗漏水情况",
                "其他",
            ]),
            ("周边环境", _COMMON_ENVIRONMENT),
            ("监测设施", _COMMON_FACILITIES),
        ],
        "footer_lines": _PATROL_FOOTER,
        "basis": "GB 50911-2013 表 C.0.2",
    },
    "表C3": {
        "key": "C3",
        "clause": "C.0.3",
        "name_cn": "矿山法隧道现场巡查报表",
        "sheet_title": "附表C3_矿山法隧道现场巡查报表",
        "methods": ["矿山法", "矿山", "钻爆法"],
        "header_lines": [
            "表 C.0.3　矿山法隧道现场巡查报表",
            "监测工程名称：{project_name}　　报表编号：{report_no}",
            "巡查时间：{patrol_time}　　天气：{weather}",
            "",
        ],
        "columns": ["分类", "巡查内容", "巡查结果", "备注"],
        "categories": [
            ("施工工况", [
                "开挖步序、步长、核心土尺寸等情况",
                "开挖面岩土体的类型、特征、自稳性，地下水渗漏及发展情况",
                "开挖面岩土体有无坍塌及坍塌的位置、规模",
                "降水或止水等地下水控制效果及降水设施运转情况",
                "其他",
            ]),
            ("支护结构", [
                "超前支护施作情况及效果、钢拱架架设、挂网及喷射混凝土的及时性、"
                "连接板的连接及锁脚锚杆的打设情况",
                "初期支护结构渗漏水情况",
                "初期支护结构开裂、剥离、掉块情况",
                "临时支撑结构有无明显变位",
                "二衬结构施作时临时支撑结构分段拆除情况",
                "初期支护结构背后回填注浆的及时性",
                "其他",
            ]),
            ("周边环境", _COMMON_ENVIRONMENT),
            ("监测设施", _COMMON_FACILITIES),
        ],
        "footer_lines": _PATROL_FOOTER,
        "basis": "GB 50911-2013 表 C.0.3",
    },
}

# 兼容旧名：现场巡查表按工法分三张，不再是一张通用清单。
TUNNEL_PATROL_FORMS = PATROL_FORMS

TUNNEL_FORM_ORDER = ["表D1", "表D2", "表D3", "表D4"]
TUNNEL_PATROL_ORDER = ["表C1", "表C2", "表C3"]


def form_titles() -> dict[str, str]:
    """{表号: 工作表名}，供渲染器遍历。"""
    return {key: TUNNEL_FORMS[key]["sheet_title"] for key in TUNNEL_FORM_ORDER}


def get_form(key: str) -> dict | None:
    return TUNNEL_FORMS.get(key)


def patrol_form_for_method(method: str | None) -> dict | None:
    """按施工工法选附录 C 的表（C.0.1 明挖/盖挖、C.0.2 盾构、C.0.3 矿山法）。

    工法未知时返回 None —— 不允许"猜一张表"来拼巡查记录。
    """
    text = str(method or "").strip()
    if not text:
        return None
    for key in TUNNEL_PATROL_ORDER:
        form = PATROL_FORMS[key]
        if any(word in text for word in form["methods"]):
            return form
    return None


def patrol_checklist(form_key: str) -> list[tuple[str, str]]:
    """[(分类, 巡查内容)]，用于核对巡查记录是否覆盖规范要求。

    ``form_key`` 同时接受 ``"表C3"`` 与 ``"C3"``。
    """
    key = str(form_key or "")
    form = PATROL_FORMS.get(key) or PATROL_FORMS.get("表" + key) or {}
    return [
        (category, content)
        for category, contents in form.get("categories", [])
        for content in contents
    ]


def unsupported_metrics_note() -> str:
    """规范未规定日报表式的测项，必须在报告中显式披露，不得套用其他标准的表。"""
    return (
        "以下测项在本规范附录 D 中未规定日报表式，未生成附表，数值仍在冻结明细与"
        "超限测点清单中列示，其表式需按项目模板补充：地下水位、裂缝宽度、爆破振动速度。"
    )


def _norm_text(text: object) -> str:
    """比对用归一化：去空白与常见标点，保留汉字与字母数字。"""
    return re.sub(r"[\s，。；、（）()\[\]【】,.;:：\-—/…]", "", str(text or ""))


def match_patrol_records(form_key: str, records: list[dict]) -> tuple[list[dict], list[dict]]:
    """把现场巡查记录对到规范的应巡查内容上。

    返回 ``(rows, extras)``：

    - ``rows``   按规范顺序排列，未填写的项 ``matched=False``；
    - ``extras`` 无法对应到规范清单的记录，按原文保留，不丢弃。

    只做归一化后的整串比对，**不做语义猜测**：对不上就说明对不上。
    """
    rows: list[dict] = []
    consumed: set[int] = set()
    for category, content in patrol_checklist(form_key):
        target = _norm_text(content)
        row = {"category": category, "content": content, "result": None, "note": None, "matched": False}
        for index, record in enumerate(records):
            if index in consumed:
                continue
            raw = record.get("content") if record.get("content") is not None else record.get("item")
            if _norm_text(raw) == target:
                consumed.add(index)
                row.update(result=record.get("result"), note=record.get("note"), matched=True)
                break
        rows.append(row)
    extras = [
        {
            "category": record.get("category") or "其他",
            "content": record.get("content") if record.get("content") is not None else record.get("item"),
            "result": record.get("result"),
            "note": record.get("note"),
            "matched": True,
        }
        for index, record in enumerate(records)
        if index not in consumed
    ]
    return rows, extras
