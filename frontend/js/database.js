let databases = [], currentTables = [];
const $ = id => document.getElementById(id);
function render() {
  $("databasesTableBody").innerHTML = databases.length ? databases.map(x => `<tr><td><strong>${esc(x.name)}</strong><div style="font-size:12px;color:var(--muted)">${esc(x.owner)}</div></td><td>${esc(x.type)}</td><td>${esc(x.host)}</td><td>${esc(x.port ?? "—")}</td><td><span class="badge success">Running</span></td><td>${esc(fmtDate(x.created))}</td><td><div class="action-row">${x.can_manage ? `<button class="action-btn" data-del="${x.id}"><i class="fa-solid fa-trash"></i></button>` : ""}</div></td></tr>`).join("") : '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No databases yet - create one</td></tr>';
  const s = $("sqlDbSelect"), cur = s.value; s.innerHTML = databases.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join(""); if (cur) s.value = cur; loadTables();
}
async function load() { try { databases = (await api("/databases")).databases; render(); } catch (e) { toast(e.message, "error"); } }
async function loadTables() {
  const nav = document.querySelector(".db-side-nav"), id = $("sqlDbSelect").value; if (!nav) return;
  if (!id) { nav.innerHTML = ""; return; }
  try { currentTables = (await api(`/databases/${id}/tables`)).tables; nav.innerHTML = currentTables.length ? currentTables.map(t => `<div class="db-side-item" data-table="${esc(t)}">${esc(t)}</div>`).join("") : '<div class="db-side-item">No tables yet</div>'; }
  catch (e) { nav.innerHTML = '<div class="db-side-item">Tables unavailable</div>'; }
}
function toggleEngine() {
  const my = $("dbType").value === "mysql";
  document.querySelectorAll(".mysql-only").forEach(e => e.style.display = my ? "" : "none");
  ["dbHost", "dbUsername", "dbPassword", "dbSchema"].forEach(id => $(id).required = my);
  if (my && $("dbPort").value === "") $("dbPort").value = 3306;
}
document.addEventListener("DOMContentLoaded", async () => {
  let user; try { user = await nimbusReady; } catch (e) { return; }
  const viewer = user.role === "Viewer";
  document.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { document.querySelectorAll("[data-tab]").forEach(x => x.classList.remove("active")); document.querySelectorAll(".tab-panel").forEach(x => x.classList.remove("active")); b.classList.add("active"); $(b.dataset.tab).classList.add("active"); });
  load(); $("dbType").onchange = toggleEngine; toggleEngine(); $("sqlDbSelect").onchange = loadTables;
  $("databasesTableBody").addEventListener("click", async e => { const b = e.target.closest("[data-del]"); if (!b) return; const d = databases.find(x => String(x.id) === b.dataset.del); if (confirm(`Delete ${d.name}? Managed SQLite data is permanently removed.`)) try { await api(`/databases/${d.id}`, { method: "DELETE" }); toast("Database deleted"); load(); } catch (err) { toast(err.message, "error"); } });
  $("createDatabaseBtn").onclick = () => openModal("createDatabaseModal");
  $("createDatabaseForm").onsubmit = async e => {
    e.preventDefault(); const btn = e.target.querySelector(".btn-primary"); btn.disabled = true;
    try { await api("/databases", { method: "POST", body: { name: $("dbName").value.trim(), engine: $("dbType").value, host: $("dbHost").value, port: $("dbPort").value, username: $("dbUsername").value, password: $("dbPassword").value, dbname: $("dbSchema").value } }); closeModal("createDatabaseModal"); e.target.reset(); toggleEngine(); toast("Database created"); load(); }
    catch (err) { toast(err.message, "error"); } btn.disabled = false;
  };
  const ta = $("sqlTextarea"), ln = $("sqlLineNumbers"); const lines = () => ln.textContent = ta.value.split("\n").map((_, i) => i + 1).join("\n"); ta.addEventListener("input", lines); lines();
  document.querySelector(".db-side-nav").addEventListener("click", e => { const t = e.target.closest("[data-table]"); if (t) { ta.value = `SELECT * FROM "${t.dataset.table.replaceAll('"', '""')}" LIMIT 100;`; lines(); } });
  $("clearQueryBtn").onclick = () => { ta.value = ""; lines(); };
  $("saveQueryBtn").onclick = () => { try { const a = JSON.parse(localStorage.getItem("nimbusQueries") || "[]"); a.push(ta.value); localStorage.setItem("nimbusQueries", JSON.stringify(a.slice(-50))); toast("Query saved locally"); } catch (e) {} };
  $("runQueryBtn").onclick = async () => {
    const q = ta.value.trim(), err = $("sqlErrorBox"), id = $("sqlDbSelect").value;
    if (!id) { err.style.display = "block"; err.textContent = "Create a database first."; return; }
    if (!q) { err.style.display = "block"; err.textContent = "Please enter a SQL query."; return; }
    err.style.display = "none"; $("sqlStatusMsg").textContent = "Running…";
    try {
      const d = await api("/query", { method: "POST", body: { database_id: id, query: q } });
      $("sqlStatusMsg").textContent = "Executed successfully"; $("sqlExecTime").textContent = d.ms + " ms";
      $("sqlResultsMeta").textContent = d.columns.length ? `${d.rows.length} row(s)${d.truncated ? " (truncated at 1000)" : ""}` : d.message;
      $("sqlResultsHead").innerHTML = d.columns.length ? "<tr>" + d.columns.map(c => `<th>${esc(c)}</th>`).join("") + "</tr>" : "";
      $("sqlResultsBody").innerHTML = d.rows.map(r => "<tr>" + r.map(v => `<td>${v === null ? "NULL" : esc(v)}</td>`).join("") + "</tr>").join("");
      if (!d.columns.length) loadTables();
    } catch (e) { $("sqlStatusMsg").textContent = "Failed"; err.style.display = "block"; err.textContent = e.message; }
  };
});
