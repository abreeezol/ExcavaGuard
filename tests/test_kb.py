# -*- coding: utf-8 -*-
"""
test_kb.py — End-to-end verification for the knowledge base and demo pipeline.

Run: python tests/test_kb.py
Checks:
  1. Vector store is built and non-empty
  2. Key queries retrieve clauses from the expected specs (recall validation)
  3. Report pipeline: normal scenario and alarm scenario judged correctly
  4. Generated report contains all sections required by the spec
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))

PASS, FAIL = "[PASS]", "[FAIL]"
failures = []


def check(name: str, ok: bool, detail: str = ""):
    print(f"{PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main():
    import report_core

    # 1. Vector store
    try:
        coll = report_core._get_coll()
        n = coll.count()
    except Exception as e:  # noqa
        check("vector store opens", False, str(e))
        sys.exit(1)
    check("vector store built", n > 0, f"{n} clause chunks")

    # 2. Retrieval recall validation
    cases = [
        ("基坑支护结构顶部水平位移报警值", ["50497", "监测"]),
        ("监测日报应包括哪些内容", ["日报"]),
        ("基坑巡视检查包括哪些内容", ["巡视"]),
        ("地下水位观测频率", ["水位"]),
    ]
    for q, expect_any in cases:
        hits = report_core.kb_search(q, topk=3)
        blob = " ".join(h["source"] + h["content"] for h in hits)
        ok = any(k in blob for k in expect_any)
        check(f"query [{q}]", ok,
              f"top hit: {hits[0]['source']} clause {hits[0]['clause']}" if hits else "no result")

    # 3. Compliance pipeline
    out_normal = report_core.run_pipeline(
        "1号测点今日累计沉降8.5mm，日变化速率0.9mm/d", {"safety_level": "一级"})
    st = [c["status"] for c in out_normal["checks"]]
    check("normal scenario judgement", st == ["正常"], f"judged={st}")

    out_alarm = report_core.run_pipeline(
        "5号测点今日累计沉降28mm，日变化速率3.8mm/d；CX1测斜孔深层水平位移累计45mm，速率3.9mm/d",
        {"safety_level": "一级"})
    sts = [c["status"] for c in out_alarm["checks"]]
    check("alarm scenario judgement", all(s in ("报警", "需关注") for s in sts) and "报警" in sts,
          f"judged={sts}")

    # 4. Report section completeness
    md = out_alarm["report_md"]
    for sec in ["第一节", "第二节", "第三节", "第四节", "监测数据汇总表", "结论", "签字栏"]:
        check(f"report section [{sec}]", sec in md)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        sys.exit(1)
    print("All tests passed.")


if __name__ == "__main__":
    main()
