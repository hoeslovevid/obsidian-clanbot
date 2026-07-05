/**
 * Obsidian Overseer — Mod Dashboard
 */
(function () {
  "use strict";

  var TOKEN_KEY = "obsidian_dashboard_token";
  var GUILD_KEY = "obsidian_dashboard_guild";
  var REFRESH_MS = 60000;

  var FEATURE_META = {
    pets: { label: "Pets", group: "Economy", desc: "Pet collection and care" },
    gambling: { label: "Gambling", group: "Economy", desc: "Casino and betting" },
    economy_passive: { label: "Passive economy", group: "Economy", desc: "Background coin/XP gains" },
    lfg: { label: "LFG squads", group: "Community", desc: "Looking-for-group posts" },
    polls: { label: "Polls", group: "Community", desc: "Server polls and votes" },
    events: { label: "Events", group: "Community", desc: "RSVP events and reminders" },
    trade: { label: "Trading", group: "Warframe", desc: "Market price lookup" },
    notifications: { label: "WF notifications", group: "Warframe", desc: "Alert and feed pings" },
    music: { label: "Music", group: "Voice", desc: "Voice channel playback" },
  };

  var GROUP_ORDER = ["Community", "Warframe", "Economy", "Voice"];

  var state = {
    me: null,
    overview: null,
    inbox: null,
    features: null,
    setup: null,
    guildId: null,
    refreshTimer: null,
    loading: false,
  };

  function cfg() {
    return window.OBSIDIAN_SITE || {};
  }

  function el(id) {
    return document.getElementById(id);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function timeAgo(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var sec = Math.floor((Date.now() - d.getTime()) / 1000);
    if (sec < 60) return "just now";
    if (sec < 3600) return Math.floor(sec / 60) + "m ago";
    if (sec < 86400) return Math.floor(sec / 3600) + "h ago";
    return Math.floor(sec / 86400) + "d ago";
  }

  function toast(msg, type) {
    var wrap = el("dash-toasts");
    if (!wrap) return;
    var t = document.createElement("div");
    t.className = "dash-toast " + (type || "");
    t.textContent = msg;
    wrap.appendChild(t);
    setTimeout(function () {
      t.remove();
    }, 3200);
  }

  function show(id) {
    var node = el(id);
    if (node) node.style.display = "";
  }
  function hide(id) {
    var node = el(id);
    if (node) node.style.display = "none";
  }

  function token() {
    return sessionStorage.getItem(TOKEN_KEY);
  }

  function logout() {
    sessionStorage.removeItem(TOKEN_KEY);
    window.location.reload();
  }

  /* ——— OAuth ——— */
  function b64url(buffer) {
    var bytes = new Uint8Array(buffer);
    var s = "";
    bytes.forEach(function (b) {
      s += String.fromCharCode(b);
    });
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  async function sha256(plain) {
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(plain));
  }

  async function startLogin() {
    var c = cfg();
    if (!c.DISCORD_CLIENT_ID) {
      toast("Sign-in is not available right now.", "error");
      return;
    }
    var verifier = b64url(crypto.getRandomValues(new Uint8Array(32)));
    sessionStorage.setItem("pkce_verifier", verifier);
    var challenge = b64url(await sha256(verifier));
    var redirect = encodeURIComponent(window.location.origin + window.location.pathname);
    window.location.href =
      "https://discord.com/api/oauth2/authorize?client_id=" +
      encodeURIComponent(c.DISCORD_CLIENT_ID) +
      "&redirect_uri=" +
      redirect +
      "&response_type=code&scope=" +
      encodeURIComponent("identify guilds") +
      "&code_challenge=" +
      challenge +
      "&code_challenge_method=S256";
  }

  async function exchangeCode(code) {
    var c = cfg();
    var body = new URLSearchParams({
      client_id: c.DISCORD_CLIENT_ID,
      grant_type: "authorization_code",
      code: code,
      redirect_uri: window.location.origin + window.location.pathname,
      code_verifier: sessionStorage.getItem("pkce_verifier") || "",
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

  /* ——— Tabs ——— */
  function setTab(name) {
    document.querySelectorAll(".dash-tab").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === name);
    });
    document.querySelectorAll(".dash-tab-panel").forEach(function (panel) {
      panel.classList.toggle("active", panel.id === "tab-" + name);
    });
  }

  function bindTabs() {
    document.querySelectorAll(".dash-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setTab(btn.getAttribute("data-tab"));
      });
    });
    document.querySelectorAll(".dash-stat[data-goto]").forEach(function (stat) {
      stat.addEventListener("click", function () {
        setTab(stat.getAttribute("data-goto"));
      });
    });
  }

  /* ——— Guild header ——— */
  function updateGuildHeader(guildId) {
    var guild = (state.me && state.me.guilds || []).find(function (g) {
      return g.id === guildId;
    });
    var icon = el("dash-guild-icon");
    var ph = el("dash-guild-icon-ph");
    if (guild && guild.icon) {
      icon.src = guild.icon;
      icon.alt = guild.name;
      icon.hidden = false;
      ph.hidden = true;
    } else {
      icon.hidden = true;
      ph.hidden = false;
      ph.textContent = guild && guild.name ? guild.name.charAt(0).toUpperCase() : "S";
    }
  }

  function renderUserChip(me) {
    var avatar = el("dash-user-avatar");
    var name = el("dash-user-name");
    if (me.avatar_url) {
      avatar.src = me.avatar_url;
      avatar.hidden = false;
    }
    name.textContent = me.display_name || me.username || "Signed in";
  }

  /* ——— Renderers ——— */
  function renderAlerts() {
    var box = el("dash-alerts");
    if (!box) return;
    box.innerHTML = "";
    var s = (state.overview && state.overview.summary) || {};
    var inbox = state.inbox || {};

    if (s.incident_mode) {
      box.innerHTML +=
        '<div class="dash-alert dash-alert-danger"><span>🚨</span><div><strong>Incident mode is active</strong> — heightened moderation settings may apply.</div></div>';
    }
    var sla = (inbox.tickets && inbox.tickets.sla_breaches) || 0;
    if (sla > 0) {
      box.innerHTML +=
        '<div class="dash-alert dash-alert-warn"><span>⏱️</span><div><strong>' +
        sla +
        " ticket SLA breach" +
        (sla > 1 ? "es" : "") +
        '</strong> — review the inbox tab.</div></div>';
    }
    if ((s.tickets_awaiting_reply || 0) > 0) {
      box.innerHTML +=
        '<div class="dash-alert dash-alert-info"><span>💬</span><div><strong>' +
        s.tickets_awaiting_reply +
        " ticket(s) awaiting first reply</strong> (SLA: " +
        (s.ticket_sla_hours || 4) +
        "h).</div></div>";
    }
  }

  function renderStats() {
    var s = (state.overview && state.overview.summary) || {};
    var inbox = state.inbox || {};
    var tickets = inbox.tickets || {};

    var items = [
      { icon: "⚖️", label: "Open incidents", value: s.open_incidents || 0, cls: s.open_incidents ? "danger" : "", goto: "inbox" },
      { icon: "🎫", label: "Tickets awaiting reply", value: s.tickets_awaiting_reply || 0, cls: s.tickets_awaiting_reply ? "warn" : "", goto: "inbox" },
      { icon: "👥", label: "Open LFG", value: s.open_lfg || 0, cls: "", goto: "inbox" },
      { icon: "🛡️", label: "Warns today", value: s.warns_today || 0, cls: "", goto: "moderation" },
      { icon: "💡", label: "Open suggestions", value: inbox.suggestions_open || 0, cls: "", goto: "inbox" },
      { icon: "⏱️", label: "SLA breaches", value: tickets.sla_breaches || 0, cls: tickets.sla_breaches ? "danger" : "", goto: "inbox" },
    ];

    el("dash-stats").innerHTML = items
      .map(function (it) {
        return (
          '<div class="dash-stat ' +
          it.cls +
          '" data-goto="' +
          it.goto +
          '" title="View ' +
          escapeHtml(it.label) +
          '"><div class="dash-stat-icon">' +
          it.icon +
          '</div><span class="dash-stat-value">' +
          it.value +
          '</span><span class="dash-stat-label">' +
          escapeHtml(it.label) +
          "</span></div>"
        );
      })
      .join("");

    document.querySelectorAll(".dash-stat[data-goto]").forEach(function (stat) {
      stat.addEventListener("click", function () {
        setTab(stat.getAttribute("data-goto"));
      });
    });
  }

  function renderAttention() {
    var parts = [];
    var tickets = (state.overview && state.overview.tickets) || [];
    tickets.slice(0, 5).forEach(function (t) {
      if (t.escalated || t.priority === "urgent" || t.awaiting_first_reply) {
        var badges = "";
        if (t.priority === "urgent") badges += '<span class="dash-badge dash-badge-urgent">Urgent</span> ';
        if (t.escalated) badges += '<span class="dash-badge dash-badge-escalated">Escalated</span> ';
        if (t.awaiting_first_reply) badges += '<span class="dash-badge dash-badge-awaiting">Awaiting reply</span> ';
        parts.push(
          "<li>" +
            badges +
            "<strong>" +
            escapeHtml(t.ticket_id) +
            "</strong> — " +
            escapeHtml(t.subject || "") +
            (t.jump_url
              ? ' <a href="' + escapeHtml(t.jump_url) + '" target="_blank" rel="noopener" class="dash-btn dash-btn-sm dash-btn-discord" style="margin-left:8px;">Open</a>'
              : "") +
            "</li>"
        );
      }
    });
    var apps = (state.overview && state.overview.applications) || [];
    if (apps.length && parts.length < 5) {
      parts.push("<li>📋 <strong>" + apps.length + "</strong> pending application(s)</li>");
    }
    el("dash-attention").innerHTML = parts.length
      ? '<ul class="dash-setup-list">' + parts.join("") + "</ul>"
      : '<div class="dash-empty"><div class="dash-empty-icon">✨</div><p>All clear — nothing urgent right now.</p></div>';
  }

  function ticketBadges(t) {
    var b = "";
    if (t.priority === "urgent") b += '<span class="dash-badge dash-badge-urgent">Urgent</span> ';
    if (t.escalated) b += '<span class="dash-badge dash-badge-escalated">Escalated</span> ';
    if (t.awaiting_first_reply) b += '<span class="dash-badge dash-badge-awaiting">Awaiting</span> ';
    if (t.tag) b += '<span class="dash-badge dash-badge-ok">' + escapeHtml(t.tag) + "</span> ";
    return b;
  }

  function renderTickets() {
    var tickets = (state.overview && state.overview.tickets) || [];
    if (!tickets.length) {
      el("dash-tickets").innerHTML =
        '<div class="dash-empty"><div class="dash-empty-icon">🎫</div><p>No open tickets.</p></div>';
      return;
    }
    el("dash-tickets").innerHTML =
      '<div class="dash-table-wrap"><table class="dash-table"><thead><tr><th>Ticket</th><th>Subject</th><th>User</th><th>Status</th><th></th></tr></thead><tbody>' +
      tickets
        .map(function (t) {
          return (
            "<tr><td><strong>" +
            escapeHtml(t.ticket_id) +
            "</strong></td><td>" +
            escapeHtml(t.subject || "—") +
            "</td><td>" +
            escapeHtml(t.user_name || "") +
            '</td><td class="dash-badges">' +
            ticketBadges(t) +
            "</td><td>" +
            (t.jump_url
              ? '<a href="' + escapeHtml(t.jump_url) + '" target="_blank" rel="noopener" class="dash-btn dash-btn-sm dash-btn-discord">Open</a>'
              : "—") +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table></div>";
  }

  function renderApps() {
    var apps = (state.overview && state.overview.applications) || [];
    if (!apps.length) {
      el("dash-apps").innerHTML =
        '<div class="dash-empty"><div class="dash-empty-icon">📋</div><p>No pending applications.</p></div>';
      return;
    }
    el("dash-apps").innerHTML =
      '<div class="dash-table-wrap"><table class="dash-table"><thead><tr><th>ID</th><th>Applicant</th><th>Submitted</th></tr></thead><tbody>' +
      apps
        .map(function (a) {
          return (
            "<tr><td>#" +
            a.id +
            "</td><td>" +
            escapeHtml(a.user_name || "") +
            "</td><td>" +
            escapeHtml(timeAgo(a.created_at)) +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table></div>";
  }

  function renderModStatus() {
    var s = (state.overview && state.overview.summary) || {};
    el("dash-mod-status").innerHTML =
      '<ul class="dash-setup-list">' +
      "<li>" +
      (s.incident_mode ? "🚨 Incident mode: <strong>ON</strong>" : "✅ Incident mode: off") +
      "</li>" +
      "<li>" +
      (s.automod_enabled ? "🛡️ Automod: <strong>enabled</strong>" : "⚠️ Automod: disabled") +
      "</li>" +
      "<li>⏱️ Ticket SLA: <strong>" +
      (s.ticket_sla_hours || 4) +
      " hours</strong></li>" +
      "<li>📊 Warnings issued today: <strong>" +
      (s.warns_today || 0) +
      "</strong></li>" +
      "</ul>";
  }

  function renderWarnings() {
    var warns = (state.overview && state.overview.warnings) || [];
    if (!warns.length) {
      el("dash-warnings").innerHTML =
        '<div class="dash-empty"><div class="dash-empty-icon">✅</div><p>No recent warnings.</p></div>';
      return;
    }
    el("dash-warnings").innerHTML =
      '<div class="dash-table-wrap"><table class="dash-table"><thead><tr><th>User</th><th>Reason</th><th>Moderator</th><th>When</th></tr></thead><tbody>' +
      warns
        .map(function (w) {
          return (
            "<tr><td>" +
            escapeHtml(w.user_name || "") +
            "</td><td>" +
            escapeHtml(w.reason || "—") +
            "</td><td>" +
            escapeHtml(w.moderator_name || "") +
            "</td><td>" +
            escapeHtml(timeAgo(w.created_at)) +
            "</td></tr>"
          );
        })
        .join("") +
      "</tbody></table></div>";
  }

  function renderFeatures() {
    var features = (state.features && state.features.features) || {};
    var byGroup = {};
    Object.keys(features).forEach(function (key) {
      var meta = FEATURE_META[key] || { label: key, group: "Other", desc: "" };
      if (!byGroup[meta.group]) byGroup[meta.group] = [];
      byGroup[meta.group].push({ key: key, meta: meta, on: features[key] });
    });

    var html = "";
    GROUP_ORDER.concat(Object.keys(byGroup).filter(function (g) {
      return GROUP_ORDER.indexOf(g) < 0;
    })).forEach(function (group) {
      if (!byGroup[group] || !byGroup[group].length) return;
      html += '<div class="dash-feature-group"><h3>' + escapeHtml(group) + "</h3><div class=\"dash-feature-grid\">";
      byGroup[group].forEach(function (f) {
        html +=
          '<div class="dash-feature-card"><div class="dash-feature-info"><strong>' +
          escapeHtml(f.meta.label) +
          "</strong><span>" +
          escapeHtml(f.meta.desc) +
          '</span></div><label class="dash-switch" aria-label="Toggle ' +
          escapeHtml(f.meta.label) +
          '"><input type="checkbox" data-feature="' +
          escapeHtml(f.key) +
          '" ' +
          (f.on ? "checked" : "") +
          ' /><span class="dash-switch-slider"></span></label></div>';
      });
      html += "</div></div>";
    });

    el("dash-features").innerHTML = html || '<p class="dash-meta">No features configured.</p>';

    el("dash-features").querySelectorAll("input[data-feature]").forEach(function (input) {
      input.addEventListener("change", async function () {
        var feature = input.getAttribute("data-feature");
        try {
          await apiFetch("/api/guilds/" + state.guildId + "/features", {
            method: "PATCH",
            body: JSON.stringify({ feature: feature, enabled: input.checked }),
          });
          toast((FEATURE_META[feature] && FEATURE_META[feature].label) || feature + " saved", "success");
        } catch (err) {
          toast(err.message || "Could not save", "error");
          input.checked = !input.checked;
        }
      });
    });
  }

  function renderSetup() {
    var setup = state.setup;
    if (!setup || setup.error) {
      el("dash-setup").innerHTML = '<p class="dash-meta">Setup data unavailable.</p>';
      return;
    }
    var pct = setup.percent || 0;
    var html =
      '<div class="dash-setup-header">' +
      '<div style="flex:1"><strong>' +
      setup.configured +
      "/" +
      setup.total +
      '</strong> configured <span class="dash-meta">(' +
      pct +
      '%)</span></div>' +
      '<div class="dash-progress-bar"><div class="dash-progress-fill" style="width:' +
      pct +
      '%"></div></div></div>';

    (setup.sections || []).forEach(function (sec) {
      html += '<div class="dash-setup-section"><h3>' + escapeHtml(sec.title) + "</h3><ul class=\"dash-setup-list\">";
      (sec.items || []).forEach(function (item) {
        var badge =
          item.status === "ok"
            ? "dash-badge-ok"
            : item.status === "warn"
              ? "dash-badge-warn"
              : "dash-badge-missing";
        var icon = item.status === "ok" ? "✅" : item.status === "warn" ? "⚠️" : "❌";
        html +=
          "<li>" +
          icon +
          ' <span class="dash-badge ' +
          badge +
          '">' +
          (item.status === "ok" ? "OK" : item.status === "warn" ? "Warn" : "Missing") +
          "</span> " +
          escapeHtml(item.text) +
          "</li>";
      });
      html += "</ul></div>";
    });

    el("dash-setup").innerHTML = html;
  }

  function renderAll() {
    renderAlerts();
    renderStats();
    renderAttention();
    renderTickets();
    renderApps();
    renderModStatus();
    renderWarnings();
    renderFeatures();
    renderSetup();

    if (state.overview && state.overview.refreshed_at) {
      el("dash-refreshed").textContent = "Updated " + timeAgo(state.overview.refreshed_at);
    }
  }

  function setLoading(on) {
    state.loading = on;
    el("dash-loading").style.display = on ? "block" : "none";
    el("dash-skeleton").style.display = on ? "block" : "none";
    if (on) {
      ["dash-stats", "dash-attention", "dash-tickets", "dash-apps", "dash-mod-status", "dash-warnings", "dash-features", "dash-setup"].forEach(function (id) {
        var node = el(id);
        if (node) node.innerHTML = "";
      });
    }
  }

  function showError(msg) {
    var err = el("dash-error");
    err.textContent = msg;
    err.style.display = msg ? "flex" : "none";
  }

  async function loadGuildData(guildId, quiet) {
    if (!guildId) return;
    state.guildId = guildId;
    localStorage.setItem(GUILD_KEY, guildId);
    updateGuildHeader(guildId);
    if (!quiet) setLoading(true);
    showError("");
    try {
      var results = await Promise.all([
        apiFetch("/api/guilds/" + guildId + "/overview"),
        apiFetch("/api/guilds/" + guildId + "/inbox"),
        apiFetch("/api/guilds/" + guildId + "/features"),
        apiFetch("/api/guilds/" + guildId + "/setup"),
      ]);
      state.overview = results[0];
      state.inbox = results[1];
      state.features = results[2];
      state.setup = results[3];
      renderAll();
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }

  function startAutoRefresh() {
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    state.refreshTimer = setInterval(function () {
      if (state.guildId && !state.loading) loadGuildData(state.guildId, true);
    }, REFRESH_MS);
  }

  function showLogin(msg) {
    hide("dash-app");
    show("dash-login");
    el("dash-login-msg").textContent = msg || "";
  }

  function showApp() {
    hide("dash-login");
    show("dash-app");
  }

  async function initDashboard() {
    bindTabs();

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

    if (!token()) return;

    showApp();
    setLoading(true);
    try {
      state.me = await apiFetch("/api/me");
      renderUserChip(state.me);

      var select = el("guild-select");
      select.innerHTML = "";
      (state.me.guilds || []).forEach(function (g) {
        var opt = document.createElement("option");
        opt.value = g.id;
        opt.textContent = g.name;
        select.appendChild(opt);
      });

      if (!state.me.guilds || !state.me.guilds.length) {
        setLoading(false);
        showError("No servers found where you are an admin and the bot is installed.");
        return;
      }

      var saved = localStorage.getItem(GUILD_KEY);
      var initial =
        saved && state.me.guilds.some(function (g) {
          return g.id === saved;
        })
          ? saved
          : state.me.guilds[0].id;
      select.value = initial;
      select.onchange = function () {
        loadGuildData(select.value, false);
      };

      await loadGuildData(initial, false);
      startAutoRefresh();
    } catch (err) {
      setLoading(false);
      var msg = err.message || String(err);
      if (msg.indexOf("temporarily unavailable") >= 0) {
        sessionStorage.removeItem(TOKEN_KEY);
        showLogin(msg);
      } else {
        showError(msg);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    el("dash-login-btn").addEventListener("click", startLogin);
    el("dash-logout-btn").addEventListener("click", logout);
    el("dash-refresh-btn").addEventListener("click", function () {
      if (state.guildId) loadGuildData(state.guildId, false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "r" || e.key === "R") {
        if (document.activeElement && document.activeElement.tagName === "INPUT") return;
        if (state.guildId) loadGuildData(state.guildId, false);
      }
    });
    initDashboard();
  });
})();
