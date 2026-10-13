let files = [];
const $ = id => document.getElementById(id);
let canWrite = false;
function render() {
  const q = ($("fileSearch").value || "").toLowerCase(), f = $("fileTypeFilter").value || "";
  const arr = files.filter(x => x.name.toLowerCase().includes(q) && (!f || x.type === f));
  $("filesTableBody").innerHTML = arr.map(x => `<tr><td><i class="fa-solid ${x.folder ? "fa-folder" : "fa-file"}"></i> ${esc(x.name)}</td><td>${esc(x.type)}</td><td>${x.folder ? "—" : esc(fmtSize(x.size))}</td><td>${esc(fmtDate(x.created))}</td><td>${esc(x.owner)}</td><td><div class="action-row">${x.folder ? "" : `<button class="action-btn" data-act="view" data-id="${x.id}"><i class="fa-solid fa-eye"></i></button><button class="action-btn" data-act="download" data-id="${x.id}"><i class="fa-solid fa-download"></i></button>`}${canWrite ? `<button class="action-btn" data-act="delete" data-id="${x.id}"><i class="fa-solid fa-trash"></i></button>` : ""}</div></td></tr>`).join("") || '<tr><td colspan="6" style="text-align:center;color:var(--muted)">No files found</td></tr>';
}
async function load() { try { files = (await api("/files")).files; render(); } catch (e) { toast(e.message, "error"); } }
async function upload(list) {
  if (!list.length) return;
  const fd = new FormData(); [...list].forEach(f => fd.append("files", f));
  try { const d = await api("/files", { method: "POST", body: fd }); toast(`${d.uploaded} file(s) uploaded`); load(); } catch (e) { toast(e.message, "error"); }
}
document.addEventListener("DOMContentLoaded", async () => {
  let user; try { user = await nimbusReady; } catch (e) { return; }
  canWrite = user.role !== "Viewer";
  load();
  const input = $("fileInput"), zone = $("uploadZone");
  if (canWrite) {
    $("browseUploadBtn").onclick = e => { e.stopPropagation(); input.click(); }; zone.onclick = () => input.click();
    input.onchange = () => { upload(input.files); input.value = ""; };
    ["dragenter", "dragover"].forEach(ev => zone.addEventListener(ev, x => { x.preventDefault(); zone.classList.add("dragover"); }));
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", e => { e.preventDefault(); zone.classList.remove("dragover"); upload(e.dataTransfer.files); });
    $("createFolderBtn").onclick = async () => { const n = prompt("Folder name"); if (n) try { await api("/folders", { method: "POST", body: { name: n } }); toast("Folder created"); load(); } catch (e) { toast(e.message, "error"); } };
  } else { $("browseUploadBtn").disabled = true; $("createFolderBtn").disabled = true; }
  $("fileSearch").oninput = render; $("fileTypeFilter").onchange = render;
  $("filesTableBody").addEventListener("click", async e => {
    const b = e.target.closest("[data-act]"); if (!b) return; const id = b.dataset.id, f = files.find(x => String(x.id) === id);
    if (b.dataset.act === "view") window.open(`/api/files/${id}/download?inline=1`, "_blank", "noopener");
    else if (b.dataset.act === "download") location.href = `/api/files/${id}/download`;
    else if (confirm(`Delete ${f.name}?`)) try { await api(`/files/${id}`, { method: "DELETE" }); toast("Deleted"); load(); } catch (err) { toast(err.message, "error"); }
  });
});
