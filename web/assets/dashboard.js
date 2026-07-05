/**
 * Mod dashboard — Discord OAuth (PKCE) + bot dashboard API.
 */
(function () {
  var TOKEN_KEY = "obsidian_dashboard_token";
  var cfg = function () {
    return window.OBSIDIAN_SITE || {};
  };

  function b64url(buffer) {
    var bytes = new Uint8Array(buffer);
    var s = "";
    bytes.forEach(function (b) {
      s += String.fromCharCode(b);
    });
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function randomVerifier() {
    var arr = new Uint8Array(32);
    crypto.getRandomValues(arr);
    return b64url(arr);
  }

  async function sha256(plain) {
    var data = new TextEncoder().encode(plain);
    return crypto.subtle.digest("SHA-256", data);
  }

  async function startLogin() {
    var c = cfg();
    if (!c.DISCORD_CLIENT_ID) {
      alert("Dashboard sign-in is not available right now. Please try again later.");
      return;
    }
    var verifier = randomVerifier();
    sessionStorage.setItem("pkce_verifier", verifier);
    var challenge = b64url(await sha256(verifier));
    var redirect = encodeURIComponent(window.location.origin + window.location.pathname);
    var url =
      "https://discord.com/api/oauth2/authorize?client_id=" +
      encodeURIComponent(c.DISCORD_CLIENT_ID) +
      "&redirect_uri=" +
      redirect +
      "&response_type=code&scope=" +
      encodeURIComponent("identify guilds") +
      "&code_challenge=" +
      challenge +
      "&code_challenge_method=S256";
    window.location.href = url;
  }

  async function exchangeCode(code) {
    var c = cfg();
    var verifier = sessionStorage.getItem("pkce_verifier") || "";
    var body = new URLSearchParams({
      client_id: c.DISCORD_CLIENT_ID,
      grant_type: "authorization_code",
      code: code,
      redirect_uri: window.location.origin + window.location.pathname,
      code_verifier: verifier,
    });
    var res = await fetch("https://discord.com/api/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
    if (!res.ok) throw new Error("OAuth token exchange failed");
    var data = await res.json();
    sessionStorage.removeItem("pkce_verifier");
    sessionStorage.setItem(TOKEN_KEY, data.access_token);
    window.history.replaceState({}, document.title, window.location.pathname);
    return data.access_token;
  }

  function token() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function logout() {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.reload();
  }

  async function apiFetch(path, options) {
    var url = window.ObsidianSite && window.ObsidianSite.apiUrl(path);
    if (!url) throw new Error("Dashboard is temporarily unavailable. Please try again later.");
    options = options || {};
    options.headers = options.headers || {};
    options.headers.Authorization = "Bearer " + token();
    if (options.body && !options.headers["Content-Type"]) {
      options.headers["Content-Type"] = "application/json";
    }
    var res = await fetch(url, options);
    var data = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) throw new Error(data.message || data.error || "API error " + res.status);
    return data;
  }

  function el(id) {
    return document.getElementById(id);
  }

  function show(id) {
    el(id).style.display = "";
  }
  function hide(id) {
    el(id).style.display = "none";
  }

  function renderOverview(data) {
    var s = data.summary || {};
    el("dash-stats").innerHTML =
      "<div class=\"stat\"><strong>" +
      (s.open_incidents || 0) +
      "</strong><span>Open incidents</span></div>" +
      "<div class=\"stat\"><strong>" +
      (s.tickets_awaiting_reply || 0) +
      "</strong><span>Tickets awaiting reply</span></div>" +
      "<div class=\"stat\"><strong>" +
      (s.open_lfg || 0) +
      "</strong><span>Open LFG</span></div>" +
      "<div class=\"stat\"><strong>" +
      (s.warns_today || 0) +
      "</strong><span>Warns today</span></div>";

    var tickets = data.tickets || [];
    el("dash-tickets").innerHTML = tickets.length
      ? tickets
          .map(function (t) {
            var jump = t.jump_url
              ? ' <a href="' + t.jump_url + '" target="_blank" rel="noopener">Open</a>'
              : "";
            return (
              "<li><strong>" +
              escapeHtml(t.ticket_id) +
              "</strong> — " +
              escapeHtml(t.subject || "") +
              " <em>(" +
              escapeHtml(t.user_name || "") +
              ")</em>" +
              jump +
              "</li>"
            );
          })
          .join("")
      : "<li>No open tickets.</li>";

    var apps = data.applications || [];
    el("dash-apps").innerHTML = apps.length
      ? apps
          .map(function (a) {
            return (
              "<li><strong>#" +
              a.id +
              "</strong> — " +
              escapeHtml(a.user_name || "") +
              "</li>"
            );
          })
          .join("")
      : "<li>No pending applications.</li>";
  }

  function renderFeatures(data) {
    var features = data.features || {};
    el("dash-features").innerHTML = Object.keys(features)
      .sort()
      .map(function (name) {
        var on = features[name];
        return (
          "<label class=\"feature-row\"><span>" +
          escapeHtml(name) +
          '</span><input type="checkbox" data-feature="' +
          escapeHtml(name) +
          '" ' +
          (on ? "checked" : "") +
          " /></label>"
        );
      })
      .join("");

    el("dash-features").querySelectorAll("input[data-feature]").forEach(function (input) {
      input.addEventListener("change", async function () {
        var guildId = el("guild-select").value;
        var feature = input.getAttribute("data-feature");
        try {
          await apiFetch("/api/guilds/" + guildId + "/features", {
            method: "PATCH",
            body: JSON.stringify({ feature: feature, enabled: input.checked }),
          });
        } catch (err) {
          alert(err.message || String(err));
          input.checked = !input.checked;
        }
      });
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showLogin(message) {
    hide("dash-panel");
    show("dash-login");
    el("dash-login-msg").textContent = message || "";
  }

  function showPanel(message) {
    hide("dash-login");
    show("dash-panel");
    if (message) el("dash-loading").textContent = message;
  }

  async function loadGuildData(guildId) {
    if (!guildId) return;
    showPanel("Loading…");
    try {
      var overview = await apiFetch("/api/guilds/" + guildId + "/overview");
      renderOverview(overview);
      var features = await apiFetch("/api/guilds/" + guildId + "/features");
      renderFeatures(features);
      el("dash-loading").textContent = "";
    } catch (err) {
      el("dash-loading").textContent = err.message || String(err);
    }
  }

  async function initDashboard() {
    showLogin("");

    var params = new URLSearchParams(window.location.search);
    var code = params.get("code");
    if (code) {
      try {
        await exchangeCode(code);
      } catch (err) {
        showLogin(err.message || String(err));
        return;
      }
    }

    if (!token()) {
      return;
    }

    showPanel("Loading your servers…");
    try {
      var me = await apiFetch("/api/me");
      el("dash-user").textContent = me.username ? "Signed in as " + me.username : "Signed in";
      var select = el("guild-select");
      select.innerHTML = "";
      (me.guilds || []).forEach(function (g) {
        var opt = document.createElement("option");
        opt.value = g.id;
        opt.textContent = g.name;
        select.appendChild(opt);
      });
      if (!me.guilds || !me.guilds.length) {
        el("dash-loading").textContent =
          "No servers found where you are an admin and the bot is installed.";
        return;
      }
      select.onchange = function () {
        loadGuildData(select.value);
      };
      await loadGuildData(select.value);
    } catch (err) {
      var msg = err.message || String(err);
      if (msg.indexOf("temporarily unavailable") >= 0) {
        sessionStorage.removeItem(TOKEN_KEY);
        showLogin(msg);
      } else {
        showPanel(msg);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var loginBtn = el("dash-login-btn");
    if (loginBtn) loginBtn.addEventListener("click", startLogin);
    var logoutBtn = el("dash-logout-btn");
    if (logoutBtn) logoutBtn.addEventListener("click", logout);
    initDashboard();
  });
})();
