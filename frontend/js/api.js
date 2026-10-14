const NimbusAPI = (() => {
  const AUTH_PAGES = ["login.html", "signup.html", "index.html", ""];

  function currentPage() {
    return location.pathname.split("/").pop();
  }

  async function request(path, options = {}) {
    const opts = {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: {},
    };

    if (options.body instanceof FormData) {
      opts.body = options.body;
    } else if (options.body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(options.body);
    }

    let res;
    try {
      res = await fetch("/api" + path, opts);
    } catch (err) {
      throw new Error("Cannot reach the Nimbus API. Is the server running?");
    }

    if (res.status === 401) {
      if (!AUTH_PAGES.includes(currentPage())) {
        window.location.href = "login.html";
      }
      throw new Error("Your session has expired. Please sign in again.");
    }

    const contentType = res.headers.get("content-type") || "";
    let data = {};
    if (contentType.includes("application/json")) {
      try {
        data = await res.json();
      } catch (err) {
        data = {};
      }
    }

    if (!res.ok) {
      const message = data.detail || data.error || `Request failed (${res.status})`;
      const error = new Error(message);
      error.status = res.status;
      throw error;
    }
    return data;
  }

  return {
    request,
    get: (path) => request(path),
    post: (path, body) => request(path, { method: "POST", body }),
    put: (path, body) => request(path, { method: "PUT", body }),
    del: (path) => request(path, { method: "DELETE" }),
    currentPage,
  };
})();

function canWrite(user) {
  return !!user && (user.role === "Administrator" || user.role === "Developer");
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function applyUserToUI(user) {
  if (!user) return;
  document.querySelectorAll(".user-avatar").forEach((el) => {
    el.textContent = (user.name || user.username || "U").trim()[0].toUpperCase();
  });
  document.querySelectorAll(".sidebar-user-name").forEach((el) => {
    el.textContent = user.name || user.username || "User";
  });
  document.querySelectorAll(".sidebar-user-role").forEach((el) => {
    el.textContent = user.role || "";
  });

  if (!canWrite(user)) {
    document.querySelectorAll("[data-requires-permission]").forEach((el) => {
      el.disabled = true;
      el.title = "You do not have permission to perform this action.";
      el.style.opacity = ".45";
    });
    const banner = document.getElementById("roleBanner");
    if (banner) banner.style.display = "flex";
  }
}

async function loadCurrentUser() {
  try {
    const data = await NimbusAPI.get("/auth/me");
    localStorage.setItem("nimbusUser", JSON.stringify(data.user));
    return data.user;
  } catch (err) {
    return null;
  }
}

async function nimbusLogout() {
  try {
    await NimbusAPI.post("/auth/logout");
  } catch (err) {
    /* ignore */
  }
  localStorage.removeItem("nimbusUser");
  window.location.href = "login.html";
}
