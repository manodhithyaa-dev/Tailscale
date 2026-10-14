function showAuthError(form, message) {
  let box = form.querySelector(".auth-error");
  if (!box) {
    box = document.createElement("div");
    box.className = "auth-error";
    box.style.cssText =
      "margin-top:14px;padding:10px 12px;border-radius:8px;font-size:13px;" +
      "background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4);color:#ef4444";
    form.appendChild(box);
  }
  box.textContent = message;
}

function clearAuthError(form) {
  const box = form.querySelector(".auth-error");
  if (box) box.remove();
}

function setFormBusy(form, busy, label) {
  const button = form.querySelector("button[type=submit]");
  if (!button) return;
  if (busy) {
    button.dataset.label = button.textContent;
    button.textContent = label || "Please wait…";
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".toggle-pass").forEach((button) => {
    button.onclick = () => {
      const input = button.parentElement.querySelector("input");
      input.type = input.type === "password" ? "text" : "password";
    };
  });

  document.querySelectorAll(".role-option").forEach((option) => {
    option.onclick = () => {
      document.querySelectorAll(".role-option").forEach((x) => x.classList.remove("selected"));
      option.classList.add("selected");
      option.querySelector("input").checked = true;
    };
  });

  const passwordField = document.getElementById("signupPassword");
  if (passwordField) {
    passwordField.addEventListener("input", () => {
      document.getElementById("strengthBar").style.width =
        Math.min(100, passwordField.value.length * 10) + "%";
    });
  }

  const loginForm = document.getElementById("loginForm");
  if (loginForm) {
    loginForm.onsubmit = async (event) => {
      event.preventDefault();
      clearAuthError(loginForm);
      setFormBusy(loginForm, true, "Signing in…");
      try {
        const data = await NimbusAPI.post("/auth/login", {
          identifier: document.getElementById("loginUser").value.trim(),
          password: document.getElementById("loginPassword").value,
        });
        localStorage.setItem("nimbusUser", JSON.stringify(data.user));
        window.location.href = "dashboard.html";
      } catch (err) {
        showAuthError(loginForm, err.message);
        setFormBusy(loginForm, false);
      }
    };
  }

  const signupForm = document.getElementById("signupForm");
  if (signupForm) {
    signupForm.onsubmit = async (event) => {
      event.preventDefault();
      clearAuthError(signupForm);
      const password = document.getElementById("signupPassword").value;
      if (password.length < 4) {
        showAuthError(signupForm, "Password must be at least 4 characters.");
        return;
      }
      if (password.length > 128) {
        showAuthError(signupForm, "Password must be at most 128 characters.");
        return;
      }
      if (password !== document.getElementById("signupConfirm").value) {
        showAuthError(signupForm, "Passwords do not match.");
        return;
      }
      const roleInput = document.querySelector('input[name="role"]:checked');
      setFormBusy(signupForm, true, "Creating account…");
      try {
        const data = await NimbusAPI.post("/auth/signup", {
          name: document.getElementById("signupName").value.trim(),
          username: document.getElementById("signupUsername").value.trim(),
          email: document.getElementById("signupEmail").value.trim(),
          password,
          role: roleInput ? roleInput.value : "Viewer",
        });
        localStorage.setItem("nimbusUser", JSON.stringify(data.user));
        window.location.href = "dashboard.html";
      } catch (err) {
        showAuthError(signupForm, err.message);
        setFormBusy(signupForm, false);
      }
    };
  }
});
