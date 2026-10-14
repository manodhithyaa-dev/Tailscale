function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("show");
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("show");
}
function toast(message, type = "success") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const item = document.createElement("div");
  item.className = "toast " + type;
  item.textContent = message;
  container.appendChild(item);
  setTimeout(() => item.remove(), 3500);
}

function addNotification(message) {
  let items = JSON.parse(localStorage.getItem("nimbusNotifications") || "[]");
  items.unshift({ message, time: new Date().toLocaleString(), read: false });
  localStorage.setItem("nimbusNotifications", JSON.stringify(items.slice(0, 20)));
  renderNotifications();
}

function renderNotifications() {
  const items = JSON.parse(localStorage.getItem("nimbusNotifications") || "[]");
  const list = document.getElementById("notifList");
  const badge = document.getElementById("notifBadge");
  if (list) {
    list.innerHTML = items.length
      ? items
          .slice(0, 5)
          .map((x) => `<div class="notif-item">${x.message}<div class="notif-time">${x.time}</div></div>`)
          .join("")
      : '<div class="notif-item">No notifications yet</div>';
  }
  if (badge) badge.textContent = items.filter((x) => !x.read).length;
}

function initShell(user) {
  if (localStorage.getItem("nimbusTheme") === "dark") document.body.classList.add("dark");

  document.querySelectorAll(".theme-toggle-btn").forEach((button) => {
    button.onclick = () => {
      document.body.classList.toggle("dark");
      localStorage.setItem("nimbusTheme", document.body.classList.contains("dark") ? "dark" : "light");
    };
  });

  const collapse = document.getElementById("sidebarCollapseBtn");
  if (collapse) collapse.onclick = () => document.querySelector(".sidebar").classList.toggle("collapsed");

  const mobile = document.getElementById("mobileNavToggle");
  if (mobile) mobile.onclick = () => document.querySelector(".sidebar").classList.toggle("mobile-open");

  document.querySelectorAll("[data-dropdown-trigger]").forEach((trigger) => {
    trigger.onclick = (event) => {
      event.stopPropagation();
      document.getElementById(trigger.dataset.dropdownTrigger).classList.toggle("show");
    };
  });
  document.addEventListener("click", () =>
    document.querySelectorAll(".dropdown-panel").forEach((panel) => panel.classList.remove("show"))
  );

  document.querySelectorAll(".logout-btn").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      nimbusLogout();
    });
  });

  const markRead = document.getElementById("notifMarkRead");
  if (markRead) {
    markRead.onclick = () => {
      const items = JSON.parse(localStorage.getItem("nimbusNotifications") || "[]").map((x) => ({
        ...x,
        read: true,
      }));
      localStorage.setItem("nimbusNotifications", JSON.stringify(items));
      renderNotifications();
    };
  }

  renderNotifications();
}

window.nimbusReady = (async () => {
  const user = await loadCurrentUser();
  if (!user) {
    window.location.href = "login.html";
    return null;
  }
  applyUserToUI(user);
  initShell(user);
  return user;
})();
