document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".toggle-pass").forEach(b => b.onclick = () => { const i = b.parentElement.querySelector("input"); i.type = i.type === "password" ? "text" : "password"; });
  document.querySelectorAll(".role-option").forEach(o => o.onclick = () => { document.querySelectorAll(".role-option").forEach(x => x.classList.remove("selected")); o.classList.add("selected"); o.querySelector("input").checked = true; });
  const p = document.getElementById("signupPassword"); if (p) p.addEventListener("input", () => document.getElementById("strengthBar").style.width = Math.min(100, p.value.length * 10) + "%");
  const show = (form, msg) => { let e = form.querySelector(".form-error"); if (!e) { e = document.createElement("p"); e.className = "form-error"; e.style.cssText = "color:#DC2626;font-size:13px;margin-top:12px"; form.appendChild(e); } e.textContent = msg; };
  const login = document.getElementById("loginForm");
  if (login) login.onsubmit = async e => {
    e.preventDefault();
    try { await api("/login", { method: "POST", body: { user: document.getElementById("loginUser").value, password: document.getElementById("loginPassword").value } }); location.href = "dashboard.html"; }
    catch (err) { show(login, err.message); }
  };
  const signup = document.getElementById("signupForm");
  if (signup) signup.onsubmit = async e => {
    e.preventDefault();
    if (document.getElementById("signupPassword").value !== document.getElementById("signupConfirm").value) return show(signup, "Passwords do not match.");
    try {
      const d = await api("/signup", { method: "POST", body: { name: document.getElementById("signupName").value, username: document.getElementById("signupUsername").value, email: document.getElementById("signupEmail").value, password: document.getElementById("signupPassword").value, role: document.querySelector('input[name="role"]:checked').value } });
      if (d.notice) alert(d.notice);
      location.href = "dashboard.html";
    } catch (err) { show(signup, err.message); }
  };
});
