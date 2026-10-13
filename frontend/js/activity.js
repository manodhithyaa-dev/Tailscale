let activities = [];
const $ = id => document.getElementById(id);
function fill(id, label, vals) { const el = $(id), cur = el.value; el.innerHTML = `<option value="">${label}</option>` + vals.map(v => `<option>${esc(v)}</option>`).join(""); el.value = cur; }
function render() {
  const q = ($("activitySearch").value || "").toLowerCase(), u = $("activityUserFilter").value, a = $("activityActionFilter").value, s = $("activityStatusFilter").value, d = $("activityDateFilter").value;
  const r = activities.filter(x => (!q || Object.values(x).join(" ").toLowerCase().includes(q)) && (!u || x.username === u) && (!a || x.action === a) && (!s || x.status === s) && (!d || new Date(x.created_at).toLocaleDateString("en-CA") === d));
  $("activityTableBody").innerHTML = r.map(x => `<tr><td>${esc(x.username)}</td><td>${esc(x.action)}</td><td>${esc(x.resource)}</td><td>${esc(fmtTime(x.created_at))}</td><td><span class="badge ${x.status === "Success" ? "success" : "failed"}">${esc(x.status)}</span></td></tr>`).join("");
  $("activityEmptyState").style.display = r.length ? "none" : "block";
}
document.addEventListener("DOMContentLoaded", async () => {
  try { await nimbusReady; } catch (e) { return; }
  ["activitySearch", "activityUserFilter", "activityActionFilter", "activityStatusFilter", "activityDateFilter"].forEach(id => $(id).addEventListener("input", render));
  try { activities = (await api("/activity?limit=500")).activity; } catch (e) { toast(e.message, "error"); }
  fill("activityUserFilter", "All users", [...new Set(activities.map(x => x.username))]); fill("activityActionFilter", "All actions", [...new Set(activities.map(x => x.action))]);
  render();
});
