// Run INSIDE a temporary test container with local storage and synthetic auth.
const base = "http://127.0.0.1:3000";
async function json(path, options = {}) {
  const response = await fetch(base + path, options);
  if (!response.ok) throw new Error(`SMOKE_HTTP_${response.status}: ${path}`);
  return response.json();
}
await json("/api/health");
const login = await fetch(base + "/api/session", {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ password: process.env.EXCAVAGUARD_ACCESS_PASSWORD }),
});
if (!login.ok) throw new Error("SMOKE_LOGIN_FAILED");
const cookie = login.headers.get("set-cookie")?.split(";")[0];
if (!cookie) throw new Error("SMOKE_NO_SESSION");
const form = new FormData();
form.set("file", new File([
  "point_id,timestamp,metric_key,value,unit,data_origin\n" +
  "SIMULATED-P,2026-10-01,wall_top_horizontal_displacement,0,mm,simulated\n" +
  "SIMULATED-P,2026-10-02,wall_top_horizontal_displacement,12,mm,simulated\n",
], "SIMULATED_container.csv"));
const uploaded = await json("/api/monitoring-files", { method: "POST", headers: { cookie }, body: form });
const generated = await json("/api/runs", {
  method: "POST", headers: { cookie, "Content-Type": "application/json" },
  body: JSON.stringify({
    project_id: process.env.EXCAVAGUARD_PROJECT_ID ?? "11111111-1111-4111-8111-111111111111",
    monitoring_file_id: uploaded.file.file_id, report_date: "2026-10-02",
    context: { safety_level: "一级", support_type: "地下连续墙", excavation_depth_m: 20 },
    options: { generate_report: true, report_mode: "template" },
  }),
});
if (!generated.record?.result?.agent_run?.state.audit_result?.valid ||
    generated.agent_run?.downloads?.length !== 3) throw new Error("SMOKE_REPORT_NOT_AUDITED");
for (const artifact of generated.agent_run.downloads) {
  const response = await fetch(base + artifact.url, { headers: { cookie } });
  if (!response.ok || !(await response.arrayBuffer()).byteLength) throw new Error("SMOKE_DOWNLOAD_FAILED");
}
console.log(JSON.stringify({ health: true, upload: true, python_engine: true, audited_report: true, downloads: 3 }));
