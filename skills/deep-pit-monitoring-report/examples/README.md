# 示例数据与复跑方法

本目录是验证时使用的输入与产物，覆盖两种输入形态，可直接复跑整条链路。

| 文件 | 说明 |
| --- | --- |
| `示例监测数据.csv` | 形态②：13 测点 / 61 条流水记录，含超限、速率触发、数据缺失、疑似粗差、日期格式异常、水位(m)、轴力(kN)、土压力(kPa) |
| `示例阈值配置.json` | 形态②阈值（累计值 + 速率双控），故意留一项未配置以验证"待复核" |
| `示例表头.json` | 报表表头字段（观测者、仪器编号等留空，验证不编造） |
| `示例日报_附录表式.md` | 形态②产物：GB 50497-2019 附录 A~G 表式的日报草稿 |
| `示例监测数据_附录表式.xlsx` | 形态①：按附录 A~G 表式集中在一个 Excel 中的数据（7 个 sheet：表A~表G），含指标缺失、测值差与本次变化不一致、阈值未配置等情形 |
| `示例阈值配置_excel版.json` | 形态①阈值，单位与附录表列单位一致（表 E 变化量栏为 mm） |
| `示例汇总表.xlsx` | 形态①产物：监测数据汇总表（汇总页 + 表A~表G 分页，含预警等级分色、工况描述、简要分析及判断性结论、留空签栏） |
| `示例日报_excel版.md` | 形态①产物：同一份解析结果渲染的附录表式日报草稿（与示例汇总表同源，日报形态） |
| `自检_示例日报_excel版.md` | 上述日报的自动数值自检结果（108 个数值单元格全部可追溯） |
| `监测数据_附录表式_丰富版.xlsx` | 形态①丰富版：覆盖附录 A~F 全部数据类型（墙顶水平/竖向位移、双孔测斜、围护墙/立柱内力、土压力、孔隙水压力、两道支撑轴力、锚杆轴力、水位/地表/分层竖向位移、坑底隆起、裂缝长度宽度分项），56 行 |
| `thresholds_丰富版.json` | 丰富版阈值（13 类测项全覆盖，锚杆轴力故意未配置） |
| `分析意见_丰富版.json` | 丰富版分析意见（总体分析 + 表A~F 逐表专属工况/分析/结论） |
| `监测日报_丰富版.md` | 丰富版产物：附录表式日报草稿（无表G，56 测点，红色 5） |
| `自检_丰富版.md` | 丰富版日报的自动数值自检（375 个数值单元格全部可追溯） |
| `监测日报.md` | 汇总页形态：仅保留汇总表「汇总」sheet 内容的 md |

## 复跑：形态②（CSV 流水，仅标准库）

```bash
python scripts/compute_metrics.py --data examples/示例监测数据.csv \
  --config examples/示例阈值配置.json --date 2026-10-09 --out result.json

python scripts/render_report.py --result result.json --meta examples/示例表头.json \
  --form-map references/item_form_map.json --out 监测日报_20261009.md

python scripts/validate_report.py --report 监测日报_20261009.md --result result.json \
  --config examples/示例阈值配置.json --out 自检结果.md
```

预期：测点 13 个（正常 2、黄色 1、橙色 7、红色 1、未判定 2），超限 9，红色预警 1，疑似粗差 1（ZQS-06），日期异常 1 条（ZQS-07）。

## 复跑：形态①（附录表式 Excel，依赖 openpyxl）

```bash
python scripts/parse_appendix_excel.py --excel examples/示例监测数据_附录表式.xlsx \
  --config examples/示例阈值配置_excel版.json --date 2026-10-09 --out result_excel.json

python scripts/render_summary.py --result result_excel.json --out 监测数据汇总表_20261009.xlsx

python scripts/render_report.py --result result_excel.json --out 监测日报_20261009.md

python scripts/validate_report.py --report 监测日报_20261009.md --result result_excel.json \
  --config examples/示例阈值配置_excel版.json --out 自检结果.md
```

预期：7 个 sheet、17 行测点（正常 3、黄色 3、橙色 6、红色 2、未判定 3），超限 11，待复核 4（ZQS-05 指标缺失、TY-01/LF-01 阈值未配置、ZL-01 测值差与本次变化不一致），表式分布 表A(7)+表B(4)+表C(1)+表D(1)+表E(3)+表F(1)+表G。

## 复跑：形态①丰富版（覆盖附录 A~F 全部数据类型，依赖 openpyxl）

```bash
python scripts/parse_appendix_excel.py --excel examples/监测数据_附录表式_丰富版.xlsx \
  --config examples/thresholds_丰富版.json --date 2026-10-10 --out result_丰富版.json

python scripts/render_report.py --result result_丰富版.json --analysis examples/分析意见_丰富版.json \
  --form-map references/item_form_map.json --no-form-g --out 监测日报_丰富版.md

python scripts/validate_report.py --report 监测日报_丰富版.md --result result_丰富版.json \
  --config examples/thresholds_丰富版.json --out 自检_丰富版.md
```

预期：7 个 sheet、56 行测点（正常 24、黄色 13、橙色 11、红色 5、未判定 3），超限 29，待复核 4（ZQS-07 指标缺失、MG-01/MG-02 锚杆轴力阈值未配置、ZL2-1 测值差与本次变化不一致）；红色 5 项：ZQS-03、SW-03、DBC-05、KD-01、LF-03；表式分布 表A(12)+表B(14)+表C(7)+表D(6)+表E(13)+表F(4)。表B 两孔自动加"点号"列区分；不需要表G 时给 render_report / render_summary 加 `--no-form-g`。
