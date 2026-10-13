document.addEventListener("DOMContentLoaded", async () => {
  try { await nimbusReady; } catch (e) { return; }
  const $ = id => document.getElementById(id);
  async function load() {
    try {
      const d = await api("/dashboard");
      $("totalInstances").textContent = d.total_instances; $("runningInstances").textContent = d.running_instances;
      $("storageUsed").textContent = fmtSize(d.storage_bytes); $("activeDatabases").textContent = d.databases;
      $("tsBadge").className = "badge " + (d.tailscale.connected ? "success" : "failed"); $("tsBadge").textContent = d.tailscale.connected ? "Connected" : (d.tailscale.installed ? "Disconnected" : "Not installed");
      $("tsIp").textContent = d.tailscale.ip || "—";
      $("dockerBadge").className = "badge " + (d.docker ? "success" : "failed"); $("dockerBadge").textContent = d.docker ? "Running" : "Unreachable";
      const ok = d.docker && d.tailscale.connected; $("healthBadge").className = "badge " + (ok ? "success" : "failed"); $("healthBadge").textContent = ok ? "Healthy" : "Degraded";
      $("recentActivity").innerHTML = d.recent.length ? d.recent.map(x => `<div class="activity-mini-item">${esc(x.action)} — ${esc(x.resource)} <span>${esc(fmtTime(x.created_at))}</span></div>`).join("") : '<div class="activity-mini-item">No activity yet</div>';
    } catch (e) { toast(e.message, "error"); }
  }
  load(); setInterval(load, 15000);
});
