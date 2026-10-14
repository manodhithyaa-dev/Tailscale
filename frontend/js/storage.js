let nimbusFiles = [];
let nimbusCanWrite = false;

function fileActions(file) {
  const disabled = nimbusCanWrite ? "" : 'disabled style="opacity:.45"';
  const view =
    file.type === "Folder"
      ? ""
      : `<button class="action-btn" data-action="view" data-id="${file.id}" title="View"><i class="fa-solid fa-eye"></i></button>`;
  const download =
    file.type === "Folder"
      ? ""
      : `<button class="action-btn" data-action="download" data-id="${file.id}" title="Download"><i class="fa-solid fa-download"></i></button>`;
  return `<div class="action-row">${view}${download}
    <button class="action-btn" ${disabled} data-action="delete" data-id="${file.id}" title="Delete"><i class="fa-solid fa-trash"></i></button>
  </div>`;
}

function bindFileActions() {
  const body = document.getElementById("filesTableBody");
  if (!body || body.dataset.bound) return;
  body.dataset.bound = "1";
  body.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled) return;
    const id = Number(button.dataset.id);
    const action = button.dataset.action;
    if (action === "view") {
      viewFile(id);
    } else if (action === "download") {
      downloadFile(id);
    } else if (action === "delete") {
      const file = nimbusFiles.find((x) => x.id === id);
      removeFile(id, file ? file.name : String(id));
    }
  });
}

function renderFiles() {
  const body = document.getElementById("filesTableBody");
  if (!body) return;
  const query = (document.getElementById("fileSearch")?.value || "").toLowerCase();
  const filter = document.getElementById("fileTypeFilter")?.value || "";
  const rows = nimbusFiles.filter(
    (x) => x.name.toLowerCase().includes(query) && (!filter || x.type === filter)
  );
  body.innerHTML = rows.length
    ? rows
        .map(
          (x) => `<tr>
        <td><i class="fa-solid ${x.type === "Folder" ? "fa-folder" : "fa-file"}"></i> ${escapeHtml(x.name)}</td>
        <td>${escapeHtml(x.type)}</td>
        <td>${escapeHtml(x.size)}</td>
        <td>${escapeHtml(x.date)}</td>
        <td>${escapeHtml(x.owner)}</td>
        <td>${fileActions(x)}</td>
      </tr>`
        )
        .join("")
    : '<tr><td colspan="6" style="text-align:center;color:var(--muted)">No files found</td></tr>';
}

function viewFile(id) {
  window.open(`/api/files/${id}/view`, "_blank");
}

function downloadFile(id) {
  window.location.href = `/api/files/${id}/download`;
}

async function removeFile(id, name) {
  if (!nimbusCanWrite) return;
  if (!confirm(`Delete ${name}?`)) return;
  try {
    await NimbusAPI.del(`/files/${id}`);
    nimbusFiles = nimbusFiles.filter((x) => x.id !== id);
    renderFiles();
    await loadStorageSummary();
    toast("File deleted");
    addNotification(`File ${name} deleted`);
  } catch (err) {
    toast(err.message, "error");
  }
}

async function loadFiles() {
  try {
    const data = await NimbusAPI.get("/files");
    nimbusFiles = data.files;
    renderFiles();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function loadStorageSummary() {
  try {
    const data = await NimbusAPI.get("/storage/summary");
    const panel = document.querySelector(".storage-meter");
    if (!panel) return;
    const heading = panel.querySelector("strong");
    const available = panel.querySelector("span");
    const bar = panel.querySelector(".progress-bar");
    if (heading) heading.textContent = `${data.summary.usedLabel} of ${data.summary.quotaLabel} used`;
    if (available) available.textContent = `${100 - data.summary.percent > 0 ? Math.round(100 - data.summary.percent) : 0}% available`;
    if (bar) bar.style.width = `${Math.min(100, data.summary.percent)}%`;
  } catch (err) {
    /* non-fatal */
  }
}

async function uploadList(fileList) {
  if (!nimbusCanWrite) return;
  if (!fileList || !fileList.length) return;
  const form = new FormData();
  [...fileList].forEach((file) => form.append("files", file));
  try {
    const data = await NimbusAPI.post("/files", form);
    nimbusFiles = [...data.files, ...nimbusFiles];
    renderFiles();
    await loadStorageSummary();
    toast(`${data.files.length} file(s) uploaded`);
    addNotification(`${data.files.length} file(s) uploaded to Storage`);
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await window.nimbusReady;
  if (!user) return;
  nimbusCanWrite = canWrite(user);

  bindFileActions();
  await Promise.all([loadFiles(), loadStorageSummary()]);

  const input = document.getElementById("fileInput");
  const zone = document.getElementById("uploadZone");
  const browse = document.getElementById("browseUploadBtn");

  if (browse && input) browse.onclick = () => input.click();
  if (zone && input) {
    zone.onclick = () => input.click();
    ["dragenter", "dragover"].forEach((name) =>
      zone.addEventListener(name, (event) => {
        event.preventDefault();
        zone.classList.add("dragover");
      })
    );
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("dragover");
      uploadList(event.dataTransfer.files);
    });
  }
  if (input) input.onchange = () => uploadList(input.files);

  const search = document.getElementById("fileSearch");
  if (search) search.oninput = renderFiles;
  const filter = document.getElementById("fileTypeFilter");
  if (filter) filter.onchange = renderFiles;

  const folderBtn = document.getElementById("createFolderBtn");
  if (folderBtn) {
    folderBtn.onclick = async () => {
      if (!nimbusCanWrite) return;
      const name = prompt("Folder name");
      if (!name) return;
      try {
        const data = await NimbusAPI.post("/files/folder", { name });
        nimbusFiles.unshift(data.file);
        renderFiles();
        toast("Folder created");
      } catch (err) {
        toast(err.message, "error");
      }
    };
  }
});
