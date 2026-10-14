document.addEventListener("DOMContentLoaded", async () => {
  const user = await window.nimbusReady;
  if (!user) return;

  try {
    const data = await NimbusAPI.get("/dashboard/summary");
    const setText = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    };
    setText("totalInstances", data.totalInstances);
    setText("runningInstances", data.runningInstances);
    setText("storageUsed", data.storage.usedLabel);
    setText("activeDatabases", data.activeDatabases);

    const list = document.getElementById("recentActivity");
    if (list) {
      list.innerHTML = data.recent.length
        ? data.recent
            .map(
              (item) =>
                `<div class="activity-mini-item">${item.action}${
                  item.resource ? " · " + item.resource : ""
                } <span>${item.time}</span></div>`
            )
            .join("")
        : '<div class="activity-mini-item">No activity yet <span>—</span></div>';
    }
  } catch (err) {
    if (typeof toast === "function") toast(err.message, "error");
  }
});
