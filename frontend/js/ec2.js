let instances = [];
const $ = id => document.getElementById(id);
function render() {
  const b = $("ec2TableBody"); if (!b) return;
  b.innerHTML = instances.length ? instances.map(x => `<tr><td><strong>${esc(x.name)}</strong><div style="font-size:12px;color:var(--muted)">${esc(x.owner)}</div></td><td>${esc(x.id)}</td><td>${esc(x.os)}</td><td>${esc(x.ip || "—")}</td><td><span class="badge ${x.status === "Running" ? "success" : x.status === "Missing" ? "failed" : "stopped"}">${esc(x.status)}</span></td><td>${esc(x.cpu)} vCPU</td><td>${esc(x.ram_gb)} GB</td><td>${esc(fmtDate(x.created))}</td><td>${x.can_manage ? `<div class="action-row"><button class="action-btn" data-act="start" data-id="${esc(x.id)}" title="Start"><i class="fa-solid fa-play"></i></button><button class="action-btn" data-act="stop" data-id="${esc(x.id)}" title="Stop"><i class="fa-solid fa-stop"></i></button><button class="action-btn" data-act="restart" data-id="${esc(x.id)}" title="Restart"><i class="fa-solid fa-rotate"></i></button><button class="action-btn" data-act="delete" data-id="${esc(x.id)}" title="Delete"><i class="fa-solid fa-trash"></i></button></div>` : "—"}</td></tr>`).join("") : '<tr><td colspan="9" style="text-align:center;color:var(--muted)">No instances yet</td></tr>';
}
async function load(quiet) {
  try { const d = await api("/instances"); instances = d.instances; render(); if (!d.docker && !quiet) toast("Docker is not reachable - start Docker Desktop / the docker service.", "error"); }
  catch (e) { if (!quiet) toast(e.message, "error"); }
}
document.addEventListener("DOMContentLoaded", async () => {
  let user; try { user = await nimbusReady; } catch (e) { return; }
  if (user.role === "Viewer") $("createInstanceBtn").disabled = true;
  load(); setInterval(() => load(true), 8000);
  $("ec2TableBody").addEventListener("click", async e => {
    const btn = e.target.closest("[data-act]"); if (!btn) return;
    const { act, id } = btn.dataset, inst = instances.find(i => i.id === id);
    if (act === "delete" && !confirm(`Delete ${inst.name}? Its container and data volume will be permanently removed.`)) return;
    btn.disabled = true;
    try {
      if (act === "delete") await api(`/instances/${id}`, { method: "DELETE" }); else await api(`/instances/${id}/action`, { method: "POST", body: { action: act } });
      toast(`${inst.name}: ${act} OK`);
    } catch (err) { toast(err.message, "error"); }
    load(true);
  });
  $("createInstanceBtn").onclick = () => openModal("createInstanceModal");
  $("createInstanceForm").onsubmit = async e => {
    e.preventDefault();
    const btn = e.target.querySelector(".btn-primary"), label = btn.textContent; btn.disabled = true; btn.textContent = "Creating… (first use downloads the image)";
    try {
      await api("/instances", { method: "POST", body: { name: $("instanceName").value.trim(), os: $("instanceOS").value, cpu: $("instanceCPU").value, ram_gb: $("instanceRAM").value, storage_gb: $("instanceStorage").value } });
      closeModal("createInstanceModal"); e.target.reset(); toast("Instance created successfully"); load(true);
    } catch (err) { toast(err.message, "error"); }
    btn.disabled = false; btn.textContent = label;
  };
});
