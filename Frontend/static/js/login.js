(() => {
  "use strict";

  // Updated API endpoints to match the Python backend
  const API = {
    LOGIN: "/login_user",
    SIGNUP: "/signup",
  };
  const API_BASE = "http://127.0.0.1:8000";
  const api = (path) => `${API_BASE}${path}`;

  const $  = (sel, root=document) => root.querySelector(sel);
  const sr = $("#sr-status");

  const toast = {
    el: $("#toast"),
    icon: $("#toastIcon"),
    msg: $("#toastMessage"),
    show(message, type="success") {
      if (!this.el) return alert(message);
      this.msg.textContent = message || "";
      if (type === "error") {
        this.icon.className = "fas fa-exclamation-circle";
        this.el.classList.add("error");
      } else {
        this.icon.className = "fas fa-check-circle";
        this.el.classList.remove("error");
      }
      this.el.classList.add("show");
      setTimeout(() => this.el.classList.remove("show"), 4000);
      sr.textContent = message;
    },
    hide(){ this.el?.classList.remove("show"); }
  };

  const loading = {
    el: $("#loadingOverlay"),
    show() { if (this.el) this.el.style.display = "flex"; },
    hide() { if (this.el) this.el.style.display = "none"; },
  };

  async function postJSON(url, body) {
    const res = await fetch(api(url), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    let data;
    try { data = await res.json(); } catch { data = {}; }
    return { ok: res.ok, status: res.status, data };
  }

  const emailRx = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  function mark(el, isValid) {
    el?.classList.toggle("error", !isValid);
    el?.classList.toggle("success", isValid);
  }

  function validateSignIn(emailEl, pwEl) {
    const ve = emailRx.test((emailEl.value || "").trim());
    const vp = (pwEl.value || "").length > 0;
    mark(emailEl, ve); mark(pwEl, vp);
    return ve && vp;
  }

  function validateSignUp(nameEl, emailEl, pwEl) {
    const n = (nameEl.value || "").trim().length >= 2;
    const e = emailRx.test((emailEl.value || "").trim());
    const p = (pwEl.value || "").length >= 8;
    mark(nameEl, n); mark(emailEl, e); mark(pwEl, p);
    return n && e && p;
  }

  class LoginManager {
    constructor() {
      // Views
      this.signInView = $("#signInView");
      this.signUpView = $("#signUpView");

      // Toggles
      this.showSignUpBtn = $("#showSignUp");
      this.showSignInBtn = $("#showSignIn");

      // Forms & Inputs
      this.signInForm = $("#signInForm");
      this.signUpForm = $("#signUpForm");
      this.signInEmail = $("#signInEmail");
      this.signInPassword = $("#signInPassword");
      this.signUpName = $("#signUpName");
      this.signUpEmail = $("#signUpEmail");
      this.signUpPassword = $("#signUpPassword");
      this.btnSignIn = $("#btnSignIn");
      this.btnSignUp = $("#btnSignUp");

      this.bindEvents();
      this.redirectIfAlreadyLoggedIn();
      toast.hide();
    }

    bindEvents() {
      this.showSignUpBtn?.addEventListener("click", (e) => {
        e.preventDefault();
        this.signInView.style.display = "none";
        this.signUpView.style.display = "block";
      });
      this.showSignInBtn?.addEventListener("click", (e) => {
        e.preventDefault();
        this.signUpView.style.display = "none";
        this.signInView.style.display = "block";
      });

      this.signInForm?.addEventListener("submit", (e) => this.handleSignIn(e));
      this.signUpForm?.addEventListener("submit", (e) => this.handleSignUp(e));
    }

    redirectIfAlreadyLoggedIn() {
      const token = sessionStorage.getItem("authToken");
      if (token) window.location.href = "index.html";
    }

    saveSession(user, token) {
      sessionStorage.setItem("user", JSON.stringify(user || {}));
      sessionStorage.setItem("authToken", token);
    }

    async handleSignIn(e) {
      e.preventDefault();
      if (!validateSignIn(this.signInEmail, this.signInPassword)) {
        toast.show("Please enter a valid email and password.", "error");
        return;
      }
      loading.show();
      const { ok, data } = await postJSON(API.LOGIN, {
        email: this.signInEmail.value.trim(),
        password: this.signInPassword.value,
      });
      loading.hide();
      
      // Handle the backend's success response: { "message": true, "User": "email" }
      if (ok && data?.message === true) {
        const user = { 
          email: data?.User,
          name: data?.User?.split("@")[0] // Create a name from the email as a fallback
        };
        // The backend doesn't provide a token, so we use a simple "loggedIn" flag
        // to make `redirectIfAlreadyLoggedIn` work.
        this.saveSession(user, "loggedIn");
        toast.show("Login successful! Redirecting…");
        setTimeout(() => (window.location.href = "index.html"), 600);
      } else {
        // Handle backend error messages from HTTPException (data.detail) or specific logic (data.message === false)
        const msg = data?.detail || (data?.message === false ? "Invalid email or password." : "Login failed.");
        toast.show(msg, "error");
      }
    }

    async handleSignUp(e) {
      e.preventDefault();
      if (!validateSignUp(this.signUpName, this.signUpEmail, this.signUpPassword)) {
        toast.show("Please fill all fields (password ≥ 8 chars).", "error");
        return;
      }
      loading.show();
      const { ok, data } = await postJSON(API.SIGNUP, {
        name: this.signUpName.value.trim(),
        email: this.signUpEmail.value.trim(),
        password: this.signUpPassword.value,
      });
      loading.hide();
      
      // Handle the backend's success response: { "message": true }
      if (ok && data?.message === true) {
        toast.show("Account created! Please sign in.");
        this.signUpView.style.display = "none";
        this.signInView.style.display = "block";
        this.signInEmail.value = this.signUpEmail.value;
      } else {
        // Handle backend error messages, which use the "detail" key from HTTPException
        toast.show(data?.detail || "Registration failed.", "error");
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => new LoginManager());
})();