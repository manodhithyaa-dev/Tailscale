let nimbusDatabases = [];
let nimbusCanWrite = false;
let nimbusUserRole = "Viewer";

function renderDB() {
  const body = document.getElementById("databasesTableBody");
  if (!body) return;
  body.innerHTML = nimbusDatabases.length
    ? nimbusDatabases
        .map(
          (x) => `<tr>
        <td><strong>${escapeHtml(x.name)}</strong></td>
        <td>${escapeHtml(x.type)}</td>
        <td>${escapeHtml(x.host)}</td>
        <td>${escapeHtml(x.port)}</td>
        <td><span class="badge success">${escapeHtml(x.status)}</span></td>
        <td>${escapeHtml(x.created)}</td>
        <td><div class="action-row">
          <button class="action-btn" ${nimbusCanWrite ? "" : 'disabled style="opacity:.45"'} data-action="delete-db" data-id="${x.id}" title="Delete"><i class="fa-solid fa-trash"></i></button>
        </div></td>
      </tr>`
        )
        .join("")
    : '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No databases yet</td></tr>';

  const select = document.getElementById("sqlDbSelect");
  if (select) {
    const previous = select.value;
    select.innerHTML =
      nimbusDatabases.map((x) => `<option value="${escapeHtml(x.name)}">${escapeHtml(x.name)}</option>`).join("") ||
      '<option value="">default</option>';
    if (previous) select.value = previous;
  }
}

async function loadDatabases() {
  try {
    const data = await NimbusAPI.get("/databases");
    nimbusDatabases = data.databases;
    renderDB();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteDB(id, name) {
  if (!nimbusCanWrite) return;
  if (!confirm(`Delete ${name}?`)) return;
  try {
    await NimbusAPI.del(`/databases/${id}`);
    nimbusDatabases = nimbusDatabases.filter((x) => x.id !== id);
    renderDB();
    toast("Database deleted");
    addNotification(`Database ${name} deleted`);
  } catch (err) {
    toast(err.message, "error");
  }
}

function bindDatabaseActions() {
  const body = document.getElementById("databasesTableBody");
  if (body && !body.dataset.bound) {
    body.dataset.bound = "1";
    body.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action='delete-db']");
      if (!button || button.disabled) return;
      const id = Number(button.dataset.id);
      const database = nimbusDatabases.find((x) => x.id === id);
      deleteDB(id, database ? database.name : String(id));
    });
  }

  const nav = document.querySelector(".db-side-nav");
  if (nav && !nav.dataset.bound) {
    nav.dataset.bound = "1";
    nav.addEventListener("click", (event) => {
      const item = event.target.closest(".db-side-item[data-table]");
      if (item) pickTable(item.dataset.table);
    });
  }
}

function renderSqlResults(data) {
  const head = document.getElementById("sqlResultsHead");
  const body = document.getElementById("sqlResultsBody");
  const meta = document.getElementById("sqlResultsMeta");
  head.innerHTML = "";
  body.innerHTML = "";
  if (!data.columns || !data.columns.length) {
    if (meta) meta.textContent = data.message || "Query completed.";
    body.innerHTML = `<tr><td colspan="1" style="text-align:center;color:var(--muted)">${escapeHtml(
      data.message || "No rows returned."
    )}</td></tr>`;
    return;
  }
  const headRow = document.createElement("tr");
  data.columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column;
    headRow.appendChild(th);
  });
  head.appendChild(headRow);
  data.rows.forEach((row) => {
    const tr = document.createElement("tr");
    data.columns.forEach((column) => {
      const td = document.createElement("td");
      const value = row[column];
      td.textContent = value == null ? "NULL" : String(value);
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  if (meta) meta.textContent = `${data.row_count} row(s) returned · ${data.duration_ms} ms`;
}

async function runSqlQuery() {
  const textarea = document.getElementById("sqlTextarea");
  const errorBox = document.getElementById("sqlErrorBox");
  const status = document.getElementById("sqlStatusMsg");
  const execTime = document.getElementById("sqlExecTime");
  const query = textarea.value.trim();
  if (!query) {
    if (errorBox) {
      errorBox.style.display = "block";
      errorBox.textContent = "Please enter a SQL query.";
    }
    return;
  }
  if (errorBox) errorBox.style.display = "none";
  if (status) status.textContent = "Running…";
  const database = document.getElementById("sqlDbSelect")?.value || null;
  try {
    const data = await NimbusAPI.post("/query", { database, query });
    renderSqlResults(data);
    if (status) status.textContent = "Executed successfully";
    if (execTime) execTime.textContent = `${data.duration_ms} ms`;
    toast("SQL query executed");
    addNotification("SQL query executed successfully");
    refreshTableNav(database);
  } catch (err) {
    if (status) status.textContent = "Query failed";
    if (errorBox) {
      errorBox.style.display = "block";
      errorBox.textContent = err.message;
    }
    toast(err.message, "error");
  }
}

async function refreshTableNav(database) {
  const nav = document.querySelector(".db-side-nav");
  if (!nav || !database) return;
  try {
    const data = await NimbusAPI.post("/query", { database, query: "SHOW TABLES" });
    const names = data.rows.map((row) => Object.values(row)[0]);
    nav.innerHTML = names.length
      ? names
          .map(
            (name, index) =>
              `<div class="db-side-item ${index === 0 ? "active" : ""}" data-table="${escapeHtml(
                name
              )}">${escapeHtml(name)}</div>`
          )
          .join("")
      : '<div class="db-side-item">No tables</div>';
  } catch (err) {
    /* non-fatal */
  }
}

function pickTable(name) {
  const textarea = document.getElementById("sqlTextarea");
  if (textarea) {
    const identifier = String(name).replace(/`/g, "``");
    textarea.value = `SELECT *\nFROM \`${identifier}\`\nLIMIT 100;`;
    updateLineNumbers();
  }
  document.querySelectorAll(".db-side-item").forEach((el) =>
    el.classList.toggle("active", el.textContent === name)
  );
}

function updateLineNumbers() {
  const textarea = document.getElementById("sqlTextarea");
  const gutter = document.getElementById("sqlLineNumbers");
  if (!textarea || !gutter) return;
  const lines = textarea.value.split("\n").length;
  gutter.innerHTML = Array.from({ length: lines }, (_, i) => i + 1).join("<br>");
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await window.nimbusReady;
  if (!user) return;
  nimbusCanWrite = canWrite(user);
  nimbusUserRole = user.role;

  bindDatabaseActions();
  await loadDatabases();
  updateLineNumbers();
  refreshTableNav(document.getElementById("sqlDbSelect")?.value);

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.onclick = () => {
      document.querySelectorAll("[data-tab]").forEach((x) => x.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((x) => x.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(button.dataset.tab).classList.add("active");
    };
  });

  const createBtn = document.getElementById("createDatabaseBtn");
  if (createBtn) createBtn.onclick = () => openModal("createDatabaseModal");

  const form = document.getElementById("createDatabaseForm");
  if (form) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      if (!nimbusCanWrite) return;
      const submit = form.querySelector('button[type="submit"]');
      if (submit) submit.disabled = true;
      try {
        const data = await NimbusAPI.post("/databases", {
          name: document.getElementById("dbName").value.trim(),
          type: document.getElementById("dbType").value,
          port: Number(document.getElementById("dbPort").value),
          username: document.getElementById("dbUsername").value,
          password: document.getElementById("dbPassword").value,
        });
        nimbusDatabases.unshift(data.database);
        renderDB();
        closeModal("createDatabaseModal");
        form.reset();
        toast("Database created");
        addNotification(`Database ${data.database.name} created`);
      } catch (err) {
        toast(err.message, "error");
      } finally {
        if (submit) submit.disabled = false;
      }
    };
  }

  const clearBtn = document.getElementById("clearQueryBtn");
  if (clearBtn) clearBtn.onclick = () => {
    document.getElementById("sqlTextarea").value = "";
    updateLineNumbers();
  };

  const saveBtn = document.getElementById("saveQueryBtn");
  if (saveBtn)
    saveBtn.onclick = () => {
      const saved = JSON.parse(localStorage.getItem("nimbusQueries") || "[]");
      saved.push(document.getElementById("sqlTextarea").value);
      localStorage.setItem("nimbusQueries", JSON.stringify(saved));
      toast("Query saved");
    };

  const runBtn = document.getElementById("runQueryBtn");
  if (runBtn) runBtn.onclick = runSqlQuery;

  const textarea = document.getElementById("sqlTextarea");
  if (textarea)
    textarea.addEventListener("input", updateLineNumbers);

  const select = document.getElementById("sqlDbSelect");
  if (select) select.onchange = () => refreshTableNav(select.value);
});
