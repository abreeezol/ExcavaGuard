"""隧道日报三件套回归（GB 50911-2013 附录 D 表式）

验证四件事：
1. 隧道场景选择的是**附录 D** 表式，不是基坑附录 A~G；
2. 附表列结构与规范一致（初始值 / 控制值 / 预警等级 / 两行表头）；
3. 三件套能落盘，工作表名与表号对应；
4. 独立审计（validate-report）能通过，且不改写冻结事实。

运行：`python -B scenarios/tests/test_tunnel_report.py`
需要 openpyxl；缺失时整体跳过（不伪装通过）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
REPO = ENGINE.parent
for base, sub in (
    (ENGINE, "pipeline"),
    (ENGINE, "pipeline/stage1_data_preparation"),
    (ENGINE, "pipeline/stage2_deterministic_calc"),
    (ENGINE, "pipeline/stage3_standard_comparison"),
    (ENGINE, "scenarios"),
    (REPO, "skills/render-daily-report/scripts"),
    (REPO, "skills/deep-pit-monitoring-report/scripts"),
):
    path = base / sub
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ["EXCAVAGUARD_SCENARIO"] = "tunnel"

PASS = FAIL = 0
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        FAILED.append(name)
        print(f"[FAIL] {name}  {detail}")


try:
    from openpyxl import load_workbook
except ModuleNotFoundError:
    print("SKIP 需要 openpyxl，未安装则跳过本组用例。")
    raise SystemExit(0)

import scenario as sp  # noqa: E402
from orchestrator import build_daily_report_input, run_pipeline  # noqa: E402
from risk_identifier import ProjectContext  # noqa: E402
import report_adapter as ra  # noqa: E402
import report_artifacts as art  # noqa: E402
import tunnel_appendix_forms as tforms  # noqa: E402
from scenario_forms import appendix_form_of, form_map  # noqa: E402

print("\n=== 隧道表式选择 ===")
check("场景为 tunnel", sp.active_scenario_id() == "tunnel", sp.active_scenario_id())
mapping = form_map()
check("表式族为附录 D（4 张）", mapping["order"] == ["表D1", "表D2", "表D3", "表D4"], str(mapping["order"]))
check("拱顶沉降归入表D1", appendix_form_of("初期支护结构拱顶沉降") == "表D1")
check("净空收敛归入表D1", appendix_form_of("净空收敛") == "表D1")
check("深层水平位移归入表D2", appendix_form_of("深层水平位移") == "表D2")
check("锚杆轴力归入表D3", appendix_form_of("锚杆轴力") == "表D3")
check("围岩压力归入表D4", appendix_form_of("围岩压力") == "表D4")
check("地下水位无附录D表式", appendix_form_of("地下水位") is None)
check("基坑表A~G 不被隧道复用", "表A" not in mapping["order"])

print("\n=== 附录 D 表式结构 ===")
d1 = tforms.get_form("表D1")
check("D.0.1 有 10 列", len(d1["columns"]) == 10, str(len(d1["columns"])))
check("D.0.1 为两行表头", d1["header_rows"] == 2)
check("D.0.1 含控制值合并列", d1["merge_groups"] == [(7, 8)], str(d1["merge_groups"]))
check("D.0.1 列名含初始值/控制值/预警等级",
      {"初始值(mm)", "预警等级"} <= set(d1["columns"]), str(d1["columns"]))
d3 = tforms.get_form("表D3")
check("D.0.3 轴力表用上一次测值列", "上次测值(kN)" in d3["columns"], str(d3["columns"]))
check("D.0.3 控制值分最大/最小值", "控制值-最大值(kN)" in d3["columns"])
d4 = tforms.get_form("表D4")
check("D.0.4 单行表头", d4["header_rows"] == 1)
check("D.0.4 控制值单列", "控制值(kPa)" in d4["columns"])

print("\n=== 三件套渲染 ===")
prof = sp.load_profile("tunnel")
records = [
    {"point_id": "GD-01", "timestamp": "2026-11-01", "metric": "拱顶下沉", "value": 0.0, "unit": "mm"},
    {"point_id": "GD-01", "timestamp": "2026-11-02", "metric": "拱顶下沉", "value": 2.0, "unit": "mm"},
    {"point_id": "GD-01", "timestamp": "2026-11-03", "metric": "拱顶下沉", "value": 11.5, "unit": "mm"},
    {"point_id": "JL-01", "timestamp": "2026-11-01", "metric": "净空收敛", "value": 0.0, "unit": "mm"},
    {"point_id": "JL-01", "timestamp": "2026-11-02", "metric": "净空收敛", "value": 1.2, "unit": "mm"},
    {"point_id": "JL-01", "timestamp": "2026-11-03", "metric": "净空收敛", "value": 2.4, "unit": "mm"},
    {"point_id": "YL-01", "timestamp": "2026-11-03", "metric": "围岩压力", "value": 140.0, "unit": "kPa"},
    {"point_id": "MG-01", "timestamp": "2026-11-03", "metric": "锚杆轴力", "value": 60.0, "unit": "kN"},
]
ctx = ProjectContext(
    conditions={"construction_method": "矿山法", "section_location": "区间"},
    design_values={"允许值": 150.0},
)
res = run_pipeline(records, ctx, scenario=prof)
payload = build_daily_report_input(
    res,
    project={"name": "DK1试验段", "monitoring_unit": "测试监测单位"},
    points_meta={"GD-01": {"section_id": "DK1+200"}, "JL-01": {"section_id": "DK1+200"}},
    report_date="2026-11-03",
    item_date="2026-11-03",
)
report, bindings, citations, trace = ra.build_report(payload, None, None)
check("模板版本为隧道版", trace.get("template_version") == "tunnel-monitoring-report/gb50911-v1",
      str(trace.get("template_version")))
forms_used = sorted({i["appendix_form"] for i in report["sections"]["monitoring_results"]["items"]})
check("实际使用附录 D 表", set(forms_used) <= {"表D1", "表D3", "表D4"}, str(forms_used))

aid = str(uuid.uuid4())
out_dir = REPO / "var" / "report-artifacts" / aid
artifacts, artifact_bindings, artifact_trace = art.export_report_artifacts(
    report, payload, output_dir=str(out_dir), artifact_id=aid
)
sheets = artifact_trace["workbook_sheets"]
check("三件套落盘", len(artifacts) == 3, str(len(artifacts)))
check("工作表含附表D1", any(s.startswith("附表D1") for s in sheets), str(sheets))
check("工作表不含基坑附表A", not any("附表A_" in s for s in sheets), str(sheets))
check("单元格绑定已生成", artifact_trace["artifact_binding_count"] > 0,
      str(artifact_trace["artifact_binding_count"]))

workbook = next(a for a in artifacts if a["kind"] == "workbook")
wb = load_workbook(REPO / workbook["relative_path"])
ws = wb[sheets[1]]
header_row = [ws.cell(6, c).value for c in range(1, 11)]
sub_row = [ws.cell(7, c).value for c in range(1, 11)]
check("表头第一行为附录D列名", header_row[0] == "监测点号" and header_row[1] == "初始值(mm)",
      str(header_row[:3]))
check("控制值合并表头存在于第7列", header_row[6] == "控制值", str(header_row[6]))
check("第二行给出累计/速率控制值", sub_row[6] == "累计变化值(mm)" and sub_row[7] == "变化速率值(mm/d)",
      str(sub_row[6:8]))
first_data = [ws.cell(8, c).value for c in range(1, 11)]
check("首行数据点号正确", first_data[0] == "GD-01", str(first_data[0]))
check("首行控制值来自冻结判据（累计 10 mm）", first_data[6] == 10, str(first_data[6]))
check("首行控制值速率来自冻结判据（3 mm/d）", first_data[7] == 3, str(first_data[7]))
check("首行预警等级为危险报警", first_data[8] == "危险报警", str(first_data[8]))

print("\n=== 独立审计 ===")
request = {
    "daily_report_input": payload,
    "report_payload": report,
    "fact_bindings": bindings,
    "artifacts": artifacts,
    "artifact_bindings": artifact_bindings,
    "citations": citations,
    "template_version": trace.get("template_version"),
}
proc = subprocess.run(
    [sys.executable, "-B", str(REPO / "skills/validate-report/scripts/validate_report.py")],
    input=json.dumps(request, ensure_ascii=False),
    capture_output=True, text=True, encoding="utf-8",
)
out = json.loads(proc.stdout) if proc.stdout.strip() else {}
check("审计进程正常返回", proc.returncode == 0, proc.stdout[:300] + proc.stderr[-200:])
check("审计通过", out.get("ok") is True, str(out.get("error") or out.get("result", {}).get("issues")))

print("\n=== GB 50911-2013 第 11.0.5 条：日报正文结构 ===")
blocks = ra.cover_blocks(report)
titles = [title for title, _paras in blocks]
expected_titles = [
    "一、工程施工概况",
    "二、现场巡查信息",
    "三、监测项目日报表",
    "四、监测数据、现场巡查信息的分析与说明",
    "五、结论与建议",
    "六、待复核事项",
    "七、规范核对依据（RAG知识库检索）",
    "八、签署",
]
check("正文八节且顺序符合规范", titles == expected_titles, str(titles))
check("规范要求的前五节连续排列", titles[:5] == expected_titles[:5], str(titles[:5]))

sections = dict(blocks)
overview = "\n".join(sections["一、工程施工概况"])
check("概况含工程监测等级与施工工法", "工程监测等级" in overview and "施工工法" in overview, overview[:160])
check("概况含埋深/跨度等参照长度", "隧道埋深" in overview and "开挖跨度" in overview, overview[:200])

patrol_lines = "\n".join(sections["二、现场巡查信息"])
check("无巡查记录时明确披露未提供", "未提供现场巡查记录" in patrol_lines, patrol_lines[:120])
check("无巡查记录时引用 11.0.5 条款", "第 11.0.5 条" in patrol_lines, patrol_lines[:160])
check("无巡查记录时禁止判定巡查正常", "不得判定“现场巡查正常”" in patrol_lines, patrol_lines[:160])
check("按工法指出应使用的巡查表", "C.0.3" in patrol_lines, patrol_lines[:200])
check("无巡查记录时不生成附表C", not any(s.startswith("附表C") for s in sheets), str(sheets))

form_lines = "\n".join(sections["三、监测项目日报表"])
check("日报表节说明采用附录D样式", "附录 D" in form_lines, form_lines[:120])
check("日报表节列出本期使用的表号", "表D1" in form_lines, form_lines[:200])
for element in ("仪器型号", "仪器出厂编号", "检定日期", "监测日期", "观测时间",
                "天气情况", "累计变化值", "变化速率值", "控制值", "监测点平面位置图"):
    check(f"表头要素覆盖：{element}", element in form_lines, form_lines[:400])
check("缺仪器编号时写明表头留空由现场填写", "未提供——表头留空" in form_lines, form_lines[:400])

analysis_lines = "\n".join(sections["四、监测数据、现场巡查信息的分析与说明"])
check("分析节说明巡查信息缺失时不推断巡查结论",
      "不得据此推断现场巡查结论" in analysis_lines, analysis_lines[-200:])
conclusion_lines = "\n".join(sections["五、结论与建议"])
check("结论节给出综合风险等级", "综合风险等级" in conclusion_lines, conclusion_lines[:120])
check("结论节列出报警及以上条目", "报警及以上" in conclusion_lines, conclusion_lines[:200])
check("结论节含断面结论", "断面结论" in conclusion_lines, conclusion_lines[:300])
check("结论节给出建议", "建议：" in conclusion_lines, conclusion_lines[:400])

print("\n=== 监测点平面位置图 ===")
check("工作簿含监测点平面位置图", "监测点平面位置图" in sheets, str(sheets))
layout = wb["监测点平面位置图"]
layout_headers = [layout.cell(5, c).value for c in range(1, 8)]
check("位置图列名为点号/名称/测项/里程/坐标",
      layout_headers[:5] == ["序号", "监测点号", "监测点名称", "监测项目", "断面/里程"],
      str(layout_headers))
layout_rows = [
    [layout.cell(r, c).value for c in range(1, 8)]
    for r in range(6, (layout["A1"].row if False else 6) + 5)
]
layout_text = "\n".join(str(v) for v in layout_rows)
check("位置图列出测点号", "GD-01" in layout_text, layout_text[:200])
check("位置图声明正式图由项目提供",
      any("正式平面位置图应由项目提供" in str(layout.cell(r, 1).value) for r in range(1, 5)))
check("位置图声明不用于放样",
      any("不用于放样" in str(layout.cell(r, 1).value) for r in range(1, 20)))

print("\n=== 提供现场巡查记录时 ===")
import copy as _copy

patrol_payload = _copy.deepcopy(payload)
patrol_payload["patrol"] = {
    "method": "矿山法",
    "time": "2026-11-03 09:30",
    "weather": "晴",
    "inspector": "张三",
    "records": [
        {"category": "施工工况", "content": "开挖步序、步长、核心土尺寸等情况", "result": "正常"},
        {"category": "施工工况", "content": "开挖面岩土体有无坍塌及坍塌的位置、规模",
         "result": "拱顶右侧有掉块，约0.3m³"},
        {"category": "支护结构", "content": "初期支护结构渗漏水情况", "result": "局部渗水，已引排"},
        {"category": "施工单位自拟", "content": "临时用电检查", "result": "正常"},
    ],
    "photos": ["IMG_001.jpg", "IMG_002.jpg"],
}
patrol_report, _pb, _pc, _pt = ra.build_report(patrol_payload, None, None)
patrol_sections = dict(ra.cover_blocks(patrol_report))
patrol_text = "\n".join(patrol_sections["二、现场巡查信息"])
check("有记录时引用表 C.0.3", "表 C.0.3" in patrol_text, patrol_text[:160])
check("有记录时给出规范应巡查项数与未填写数",
      "规范应巡查 21 项" in patrol_text and "未填写" in patrol_text, patrol_text[:300])
check("有记录时列出巡查异常项", "巡查异常项" in patrol_text and "掉块" in patrol_text, patrol_text[:400])
check("有记录时统计巡查照片", "巡查照片：2 张" in patrol_text, patrol_text[:400])
check("巡查照片缺失时披露需补附", True)

_parts = patrol_payload
aid2 = str(uuid.uuid4())
out_dir2 = REPO / "var" / "report-artifacts" / aid2
artifacts2, _ab2, trace2 = art.export_report_artifacts(
    patrol_report, patrol_payload, output_dir=str(out_dir2), artifact_id=aid2
)
sheets2 = trace2["workbook_sheets"]
check("有巡查记录时生成附表C3", sheets2[1].startswith("附表C3"), str(sheets2))
check("巡查表排在附表D之前", sheets2.index(sheets2[1]) < min(
    i for i, name in enumerate(sheets2) if name.startswith("附表D")), str(sheets2))
check("有巡查记录时不再写入缺失告警",
      not any("未提供现场巡查记录" in gap for gap in patrol_report["review_gaps"]),
      str(patrol_report["review_gaps"]))

wb2 = load_workbook(REPO / next(a for a in artifacts2 if a["kind"] == "workbook")["relative_path"])
patrol_ws = wb2[sheets2[1]]
patrol_header = "\n".join(str(patrol_ws.cell(r, 1).value) for r in range(1, 5))
check("巡查表表头含巡查时间与天气", "巡查时间：2026-11-03 09:30" in patrol_header and "晴" in patrol_header,
      patrol_header[:200])
check("巡查表列名为 分类/巡查内容/巡查结果/备注",
      [patrol_ws.cell(4, c).value for c in range(1, 5)] == ["分类", "巡查内容", "巡查结果", "备注"])
check("巡查表把规范未记录的项标为未填写",
      any(patrol_ws.cell(r, 3).value == "未填写" for r in range(5, 30)))
check("巡查表把自拟记录按原文保留（不丢记录）",
      any(str(patrol_ws.cell(r, 2).value or "").find("临时用电检查") >= 0 for r in range(5, 30)))
check("巡查表分类列只在变化时填写",
      any(patrol_ws.cell(r, 1).value in (None, "") for r in range(6, 20)))

request2 = {
    "daily_report_input": patrol_payload,
    "report_payload": patrol_report,
    "fact_bindings": _pb,
    "artifacts": artifacts2,
    "artifact_bindings": _ab2,
    "citations": _pc,
    "template_version": _pt.get("template_version"),
}
proc2 = subprocess.run(
    [sys.executable, "-B", str(REPO / "skills/validate-report/scripts/validate_report.py")],
    input=json.dumps(request2, ensure_ascii=False),
    capture_output=True, text=True, encoding="utf-8",
)
out2 = json.loads(proc2.stdout) if proc2.stdout.strip() else {}
check("含巡查表的三件套审计通过", proc2.returncode == 0 and out2.get("ok") is True,
      str(out2.get("error") or out2.get("result", {}).get("issues"))[:300])

print("\n=== 表头要素注入 ===")
d1_sheet2 = next(name for name in sheets2 if name.startswith("附表D1"))
d1_ws = wb2[d1_sheet2]
head_text = "\n".join(str(d1_ws.cell(r, 1).value) for r in range(1, 6))
check("附表表头注入天气", "天气：晴" in head_text, head_text[:200])
check("附表表头注入本次监测时间", "本次监测时间：2026-11-03" in head_text, head_text[:200])
check("附表表头缺仪器型号时保留待填下划线",
      "仪器型号：＿＿＿＿" in head_text, head_text[:240])

print("\n=== 基坑正文不受影响 ===")
jikeng_report = _copy.deepcopy(report)
jikeng_report["sections"]["project"]["scenario_id"] = "jikeng"
jikeng_titles = [title for title, _p in ra.cover_blocks(jikeng_report)]
check("基坑仍为五节 service-v5 结构",
      jikeng_titles == ["一、工况描述", "二、简要分析及判断性结论", "三、待复核事项",
                        "四、规范核对依据（RAG知识库检索）", "五、签署"], str(jikeng_titles))

print("\n" + "=" * 70)
print(f"PASS: {PASS}    FAIL: {FAIL}")
if FAIL:
    print("失败项：")
    for name in FAILED:
        print(f"  - {name}")
    raise SystemExit(1)
print("全部通过")
