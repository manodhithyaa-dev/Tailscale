let nimbusInstances = [];
let nimbusCanWrite = false;

function instanceActions(instance) {
  const disabled = nimbusCanWrite ? "" : 'disabled style="opacity:.45"';
  return `<div class="action-row">
    <button class="action-btn" ${disabled} data-action="start" data-id="${instance.id}" title="Start"><i class="fa-solid fa-play"></i></button>
    <button class="action-btn" ${disabled} data-action="stop" data-id="${instance.id}" title="Stop"><i class="fa-solid fa-stop"></i></button>
    <button class="action-btn" ${disabled} data-action="restart" data-id="${instance.id}" title="Restart"><i class="fa-solid fa-rotate"></i></button>
    <button class="action-btn" ${disabled} data-action="delete" data-id="${instance.id}" title="Delete"><i class="fa-solid fa-trash"></i></button>
  </div>`;
}

function bindInstanceActions() {
  const body = document.getElementById("ec2TableBody");
  if (!body || body.dataset.bound) return;
  body.dataset.bound = "1";
  body.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled) return;
    const id = Number(button.dataset.id);
    const action = button.dataset.action;
    if (action === "delete") {
      const instance = nimbusInstances.find((x) => x.id === id);
      deleteInstance(id, instance ? instance.name : String(id));
    } else {
      changeInstance(id, action);
    }
  });
}

function renderInstances() {
  const body = document.getElementById("ec2TableBody");
  if (!body) return;
  if (!nimbusInstances.length) {
    body.innerHTML =
      '<tr><td colspan="9" style="text-align:center;color:var(--muted)">No instances yet. Create one to get started.</td></tr>';
    return;
  }
  body.innerHTML = nimbusInstances
    .map(
      (x) => `<tr>
      <td><strong>${escapeHtml(x.name)}</strong></td>
      <td>${escapeHtml(x.instanceId)}</td>
      <td>${escapeHtml(x.os)}</td>
      <td>${escapeHtml(x.ip)}</td>
      <td><span class="badge ${String(x.status).toLowerCase()}">${escapeHtml(x.status)}</span></td>
      <td>${x.cpu} vCPU</td>
      <td>${x.ram} GB</td>
      <td>${escapeHtml(x.created)}</td>
      <td>${instanceActions(x)}</td>
    </tr>`
    )
    .join("");
}

async function loadInstances() {
  try {
    const data = await NimbusAPI.get("/instances");
    nimbusInstances = data.instances;
    renderInstances();
  } catch (err) {
    toast(err.message, "error");
  }
}

async function changeInstance(id, action) {
  if (!nimbusCanWrite) return;
  try {
    const data = await NimbusAPI.post(`/instances/${id}/${action}`);
    const index = nimbusInstances.findIndex((x) => x.id === id);
    if (index !== -1) nimbusInstances[index] = data.instance;
    renderInstances();
    toast(`${data.instance.name} ${action === "restart" ? "restarted" : action + "ed"}`);
    addNotification(`Instance ${data.instance.name} ${action}`);
  } catch (err) {
    toast(err.message, "error");
  }
}

async function deleteInstance(id, name) {
  if (!nimbusCanWrite) return;
  if (!confirm(`Delete instance ${name}?`)) return;
  const wipe = confirm("Also permanently delete its persistent data volume?\nOK = delete data, Cancel = keep data.");
  try {
    await NimbusAPI.del(`/instances/${id}?delete_data=${wipe ? "true" : "false"}`);
    nimbusInstances = nimbusInstances.filter((x) => x.id !== id);
    renderInstances();
    toast(`Instance ${name} deleted`);
    addNotification(`Instance ${name} deleted`);
  } catch (err) {
    toast(err.message, "error");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const user = await window.nimbusReady;
  if (!user) return;
  nimbusCanWrite = canWrite(user);

  bindInstanceActions();
  await loadInstances();

  const createBtn = document.getElementById("createInstanceBtn");
  if (createBtn) createBtn.onclick = () => openModal("createInstanceModal");

  const form = document.getElementById("createInstanceForm");
  if (form) {
    form.onsubmit = async (event) => {
      event.preventDefault();
      if (!nimbusCanWrite) return;
      const submit = form.querySelector('button[type="submit"]');
      if (submit) submit.disabled = true;
      try {
        const data = await NimbusAPI.post("/instances", {
          name: document.getElementById("instanceName").value.trim(),
          os: document.getElementById("instanceOS").value,
          cpu: Number(document.getElementById("instanceCPU").value),
          ram: Number(document.getElementById("instanceRAM").value),
          storage: Number(document.getElementById("instanceStorage").value),
        });
        nimbusInstances.unshift(data.instance);
        renderInstances();
        closeModal("createInstanceModal");
        form.reset();
        toast("Instance created successfully");
        addNotification(`Instance ${data.instance.name} created`);
      } catch (err) {
        toast(err.message, "error");
      } finally {
        if (submit) submit.disabled = false;
      }
    };
  }
});
