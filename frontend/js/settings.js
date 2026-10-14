document.addEventListener("DOMContentLoaded", async () => {
  const user = await window.nimbusReady;
  if (!user) return;

  const nameField = document.getElementById("settingsName");
  const emailField = document.getElementById("settingsEmail");
  const roleField = document.getElementById("settingsRole");
  const notifyToggle = document.getElementById("notificationPreference");

  try {
    const data = await NimbusAPI.get("/profile");
    const profile = data.profile;
    if (nameField) nameField.value = profile.name || "";
    if (emailField) emailField.value = profile.email || "";
    if (roleField) roleField.value = profile.role || "";
    if (notifyToggle) notifyToggle.checked = !!profile.notifyEnabled;
  } catch (err) {
    toast(err.message, "error");
  }

  const saveBtn = document.getElementById("saveProfileBtn");
  if (saveBtn) {
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      try {
        const data = await NimbusAPI.put("/profile", {
          name: nameField.value.trim(),
          email: emailField.value.trim(),
          notifyEnabled: notifyToggle ? notifyToggle.checked : true,
        });
        localStorage.setItem("nimbusUser", JSON.stringify(data.profile));
        applyUserToUI(data.profile);
        toast("Profile updated");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        saveBtn.disabled = false;
      }
    };
  }

  const changeBtn = document.getElementById("changePasswordBtn");
  if (changeBtn) {
    changeBtn.onclick = async () => {
      const current = document.getElementById("settingsCurrentPassword");
      const next = document.getElementById("settingsNewPassword");
      if (!current.value || !next.value) {
        toast("Enter your current and new password.", "error");
        return;
      }
      if (next.value.length < 4 || next.value.length > 128) {
        toast("New password must be between 4 and 128 characters.", "error");
        return;
      }
      changeBtn.disabled = true;
      try {
        await NimbusAPI.post("/profile/password", {
          current: current.value,
          new: next.value,
        });
        current.value = "";
        next.value = "";
        toast("Password changed successfully");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        changeBtn.disabled = false;
      }
    };
  }
});
