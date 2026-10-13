document.addEventListener("DOMContentLoaded", async () => {
  let u; try { u = await nimbusReady; } catch (e) { return; }
  const $ = id => document.getElementById(id);
  $("settingsName").value = u.name; $("settingsEmail").value = u.email; $("settingsRole").value = u.role; $("settingsRole").disabled = true;
  $("saveProfileBtn").onclick = async () => {
    try { const d = await api("/me", { method: "POST", body: { name: $("settingsName").value, email: $("settingsEmail").value } }); toast("Profile updated"); document.querySelectorAll(".sidebar-user-name").forEach(e => e.textContent = d.user.name); }
    catch (e) { toast(e.message, "error"); }
  };
});
