let nimbusActivity = [];

function withinDate(timestamp, range) {
  if (!range || range === "all") return true;
  const created = new Date(timestamp).getTime();
  if (Number.isNaN(created)) return true;
  const now = Date.now();
  const day = 86400000;
  if (range === "today") return now - created <= day;
  if (range === "week") return now - created <= 7 * day;
  if (range === "month") return now - created <= 30 * day;
  return true;
}

function renderActivity() {
  const body = document.getElementById("activityTableBody");
  const empty = document.getElementById("activityEmptyState");
  if (!body) return;

  const query = (document.getElementById("activitySearch")?.value || "").toLowerCase();
  const userFilter = document.getElementById("activityUserFilter")?.value || "";
  const actionFilter = document.getElementById("activityActionFilter")?.value || "";
  const statusFilter = document.getElementById("activityStatusFilter")?.value || "";
  const dateFilter = document.getElementById("activityDateFilter")?.value || "all";

  const rows = nimbusActivity.filter(
    (x) =>
      (!query || Object.values(x).join(" ").toLowerCase().includes(query)) &&
      (!userFilter || x.user === userFilter) &&
      (!actionFilter || x.action === actionFilter) &&
      (!statusFilter || x.status === statusFilter) &&
      withinDate(x.timestamp, dateFilter)
  );

  body.innerHTML = rows
    .map(
      (x) => `<tr>
      <td>${escapeHtml(x.user)}</td>
      <td>${escapeHtml(x.action)}</td>
      <td>${escapeHtml(x.resource)}</td>
      <td>${escapeHtml(x.time)}</td>
      <td><span class="badge ${String(x.status).toLowerCase()}">${escapeHtml(x.status)}</span></td>
    </tr>`
    )
    .join("");
  if (empty) empty.style.display = rows.length ? "none" : "block";
}

function populateFilters() {
  const users = [...new Set(nimbusActivity.map((x) => x.user))];
  const actions = [...new Set(nimbusActivity.map((x) => x.action))];
  const userSelect = document.getElementById("activityUserFilter");
  const actionSelect = document.getElementById("activityActionFilter");
  if (userSelect)
    userSelect.innerHTML =
      '<option value="">All users</option>' + users.map((x) => `<option>${escapeHtml(x)}</option>`).join("");
  if (actionSelect)
    actionSelect.innerHTML =
      '<option value="">All actions</option>' + actions.map((x) => `<option>${escapeHtml(x)}</option>`).join("");
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await window.nimbusReady;
  if (!user) return;

  try {
    const data = await NimbusAPI.get("/activity");
    nimbusActivity = data.activity;
  } catch (err) {
    toast(err.message, "error");
  }
  populateFilters();

  ["activitySearch", "activityUserFilter", "activityActionFilter", "activityStatusFilter", "activityDateFilter"].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener("input", renderActivity);
        el.addEventListener("change", renderActivity);
      }
    }
  );

  renderActivity();
});
