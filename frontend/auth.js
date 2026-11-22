(() => {
  "use strict";

  const SUPABASE_URL = "https://qdvfjdcdrtczymggnhty.supabase.co";
  const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_x1CKQ6Vh4nlq9-nCNJ2vZA_xJmiD6vB";
  const RESEARCH_API_URL = "https://gold-ai-mtf-research.onrender.com";
  const supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true }
  });

  const loginScreen = document.getElementById("loginScreen");
  const appShell = document.getElementById("overview");
  const loginForm = document.getElementById("loginForm");
  const loginMessage = document.getElementById("loginMessage");
  const loginSubmit = document.getElementById("loginSubmit");
  const logoutButton = document.getElementById("logoutBtn");
  let activeSession = null;

  function setMessage(message, kind = "") {
    loginMessage.textContent = message;
    loginMessage.className = "login-message" + (kind ? " " + kind : "");
  }

  function showLogin(message) {
    activeSession = null;
    appShell.style.display = "none";
    loginScreen.style.display = "grid";
    if (message) setMessage(message, "error");
  }

  function showWorkspace(session) {
    activeSession = session;
    loginScreen.style.display = "none";
    appShell.style.display = "";
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const requestUrl = typeof input === "string" ? input : input.url;
    if (requestUrl.startsWith(RESEARCH_API_URL)) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      if (activeSession && activeSession.access_token) {
        headers.set("Authorization", "Bearer " + activeSession.access_token);
      }
      return originalFetch(input, { ...init, headers });
    }
    return originalFetch(input, init);
  };

  async function verifyOwnerAccess(session) {
    try {
      const response = await originalFetch(RESEARCH_API_URL + "/broker/mt5/status", {
        method: "GET",
        cache: "no-store",
        headers: { "Authorization": "Bearer " + session.access_token }
      });
      if (response.ok) return { ok: true };
      let detail = "";
      try { detail = (await response.json()).detail || ""; } catch (_) {}
      if (response.status === 403) return { ok: false, message: "This account is valid, but it is not authorised as the Gold AI owner." };
      if (response.status === 401) return { ok: false, message: "The research service did not accept this session. Please sign in again." };
      if (response.status === 503) return { ok: false, message: "Owner verification is temporarily unavailable. Please try again shortly." };
      return { ok: false, message: detail || "Gold AI could not verify owner access (HTTP " + response.status + ")." };
    } catch (_) {
      return { ok: false, message: "Gold AI research service is unreachable. Check your connection and try again." };
    }
  }

  async function acceptSession(session) {
    const check = await verifyOwnerAccess(session);
    if (!check.ok) {
      await supabaseClient.auth.signOut();
      showLogin(check.message);
      return null;
    }
    showWorkspace(session);
    return session;
  }

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;
    loginSubmit.disabled = true;
    loginSubmit.textContent = "Signing in...";
    setMessage("Checking your account...");
    try {
      const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
      if (error) throw error;
      const accepted = await acceptSession(data.session);
      if (accepted) setMessage("");
    } catch (error) {
      setMessage(error.message || "Sign-in failed. Check your email and password.", "error");
    } finally {
      loginSubmit.disabled = false;
      loginSubmit.innerHTML = 'Sign in <b>→</b>';
    }
  });

  logoutButton.addEventListener("click", async () => {
    await supabaseClient.auth.signOut();
    showLogin("You have signed out.");
  });

  window.GOLD_AI_AUTH_READY = supabaseClient.auth.getSession().then(async ({ data, error }) => {
    if (error) {
      showLogin("Could not restore your session. Please sign in.");
      return null;
    }
    if (!data.session) {
      showLogin();
      return null;
    }
    return await acceptSession(data.session);
  }).catch(() => {
    showLogin("Authentication could not be started. Refresh the page and try again.");
    return null;
  });

  supabaseClient.auth.onAuthStateChange((event, session) => {
    if (event === "SIGNED_OUT") showLogin("You have signed out.");
    if (event === "TOKEN_REFRESHED" && session) activeSession = session;
  });

  window.GOLD_AI_SUPABASE = supabaseClient;
})();