(function () {
  const AUTH_PAGES = ["login.html", "signup.html", "index.html", ""];
  const page = location.pathname.split("/").pop();
  const isAuthPage = AUTH_PAGES.includes(page);
  window.esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  window.fmtTime = iso => iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "";
  window.fmtDate = iso => iso ? new Date(iso).toLocaleDateString([], { dateStyle: "medium" }) : "";
  window.fmtSize = b => b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(1) + " KB" : b < 1073741824 ? (b / 1048576).toFixed(1) + " MB" : (b / 1073741824).toFixed(2) + " GB";
  window.api = async function (path, opts = {}) {
    const o = { method: opts.method || "GET", credentials: "same-origin", headers: { "X-Requested-With": "nimbus" } };
    if (opts.body instanceof FormData) o.body = opts.body;
    else if (opts.body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(opts.body); }
    let r;
    try { r = await fetch("/api" + path, o); } catch (e) { throw new Error("Cannot reach the Nimbus server. Is app.py running?"); }
    let data = null;
    try { data = await r.json(); } catch (e) {}
    if (r.status === 401 && !isAuthPage) { location.href = "login.html"; throw new Error("Not signed in"); }
    if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
    return data;
  };
  window.nimbusReady = isAuthPage ? Promise.resolve(null) : api("/me").then(d => (window.NIMBUS_USER = d.user));
})();
