document.addEventListener("DOMContentLoaded", async () => {
  if (localStorage.getItem("nimbusTheme") === "dark") document.body.classList.add("dark");
  document.querySelectorAll(".theme-toggle-btn").forEach(b => b.onclick = () => { document.body.classList.toggle("dark"); localStorage.setItem("nimbusTheme", document.body.classList.contains("dark") ? "dark" : "light"); });
  const collapse = document.getElementById("sidebarCollapseBtn"); if (collapse) collapse.onclick = () => document.querySelector(".sidebar").classList.toggle("collapsed");
  const mobile = document.getElementById("mobileNavToggle"); if (mobile) mobile.onclick = () => document.querySelector(".sidebar").classList.toggle("mobile-open");
  document.querySelectorAll("[data-dropdown-trigger]").forEach(t => t.onclick = e => { e.stopPropagation(); document.getElementById(t.dataset.dropdownTrigger).classList.toggle("show"); });
  document.addEventListener("click", () => document.querySelectorAll(".dropdown-panel").forEach(d => d.classList.remove("show")));
  document.querySelectorAll(".logout-btn").forEach(b => b.addEventListener("click", () => { api("/logout", { method: "POST" }).finally(() => location.href = "login.html"); }));
  let user; try { user = await nimbusReady; } catch (e) { return; }
  if (!user) return;
  document.querySelectorAll(".user-avatar").forEach(a => a.textContent = (user.name || "U").trim()[0].toUpperCase());
  document.querySelectorAll(".sidebar-user-name").forEach(e => e.textContent = user.name);
  document.querySelectorAll(".sidebar-user-role").forEach(e => e.textContent = user.role);
  if (user.role === "Viewer") {
    document.querySelectorAll("[data-requires-permission]").forEach(b => { b.disabled = true; b.title = "You do not have permission to perform this action."; b.style.opacity = ".45"; });
    const rb = document.getElementById("roleBanner"); if (rb) rb.style.display = "block";
  }
  const nb = document.getElementById("notifMarkRead");
  if (nb) nb.onclick = () => { localStorage.setItem("nimbusNotifRead", new Date().toISOString()); renderNotifications(); };
  renderNotifications();
  api("/health").then(h => {
    document.querySelectorAll(".pill-text").forEach(p => p.textContent = h.tailscale.connected ? `Tailscale: ${h.tailscale.ip}` : (h.tailscale.installed ? "Tailscale: Disconnected" : "Tailscale: not installed"));
    document.querySelectorAll(".network-pill .status-dot").forEach(d => d.style.background = h.tailscale.connected ? "" : "#F59E0B");
  }).catch(() => {});
});
function openModal(id) { document.getElementById(id).classList.add("show"); }
function closeModal(id) { document.getElementById(id).classList.remove("show"); }
function toast(message, type = "success") { const c = document.getElementById("toastContainer"); if (!c) return; const t = document.createElement("div"); t.className = "toast " + type; t.textContent = message; c.appendChild(t); setTimeout(() => t.remove(), 4500); }
function addNotification() { renderNotifications(); }   // events are logged server-side; the bell reads them back
async function renderNotifications() {
  const list = document.getElementById("notifList"), badge = document.getElementById("notifBadge");
  if (!list && !badge) return;
  try {
    const items = (await api("/activity?limit=5")).activity, seen = localStorage.getItem("nimbusNotifRead") || "";
    if (list) list.innerHTML = items.length ? items.map(x => `<div class="notif-item">${esc(x.action)} — ${esc(x.resource)}<div class="notif-time">${esc(fmtTime(x.created_at))}</div></div>`).join("") : '<div class="notif-item">No notifications yet</div>';
    if (badge) badge.textContent = items.filter(x => x.created_at > seen).length;
  } catch (e) {}
}
