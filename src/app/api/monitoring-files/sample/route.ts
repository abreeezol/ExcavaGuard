export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * 示例监测数据（GET，直接下载 CSV）
 *
 * 用**用户最自然的表结构**：只有「测点编号 / 观测日期 / 监测项目 / 本次观测值 /
 * 单位 / 方向」6 列，**不含** baseline_value / previous_value / interval_days。
 * 这三项由阶段一按测点时序派生 —— 这正是 `06_..._目标实现度评估.md` 里
 * P0-1 修复后的行为，用来验证「用户上传原始观测表能否直接算」。
 *
 * 表头用中文、编码用 UTF-8 BOM，用来验证列名别名映射与编码探测。
 * 数据本身是**演示用构造值**，不是任何真实工程。
 */

const SAMPLE_NAME = "ExcavaGuard_示例监测数据.csv";

/** [测点, 监测项目, 方向, 每日累计值] */
const SERIES: Array<[string, string, string, number[]]> = [
  // 超限点：7 天累计 60.8 mm，一级基坑地下连续墙限值 20 mm → 危险报警
  ["WTHD-01", "围护墙顶部水平位移", "正", [0, 5.2, 12.4, 22.1, 35.6, 52.3, 60.8]],
  // 正常点：增长平缓
  ["WTHD-02", "围护墙顶部水平位移", "正", [0, 1.2, 2.4, 3.1, 4.0, 4.6, 5.1]],
  // 中间点：累计 24 mm、速率 4 mm/d。
  // 默认限值 20 mm / 2 mm/d → 危险报警；
  // 若用户把限值放宽到 50 mm / 5 mm/d，则降为预警 —— 用来直观展示"放宽阈值会降级"
  ["WTHD-03", "围护墙顶部水平位移", "正", [0, 4.0, 8.0, 12.0, 16.0, 20.0, 24.0]],
  // 地表沉降：负向累计
  ["ZBDM-01", "周边地表竖向位移", "负", [0, -1.8, -4.5, -8.2, -13.0, -18.6, -24.3]],
  // 地下水位下降
  ["SW-01", "地下水位", "负", [0, -0.05, -0.12, -0.18, -0.25, -0.31, -0.36]],
];

function buildCsv(): string {
  const lines = ["测点编号,观测日期,监测项目,本次观测值,单位,方向"];
  for (const [pointId, metric, direction, values] of SERIES) {
    const unit = metric === "地下水位" ? "m" : "mm";
    values.forEach((value, index) => {
      const day = String(index + 1).padStart(2, "0");
      lines.push(`${pointId},2026-08-${day},${metric},${value},${unit},${direction}`);
    });
  }
  return `${lines.join("\n")}\n`;
}

export function GET() {
  // 加 BOM：Excel 直接双击打开不乱码，也顺带验证读取器的 utf-8-sig 分支
  const body = `\ufeff${buildCsv()}`;
  const encodedName = encodeURIComponent(SAMPLE_NAME);
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": `attachment; filename="ExcavaGuard_sample.csv"; filename*=UTF-8''${encodedName}`,
      "Cache-Control": "no-store",
    },
  });
}
