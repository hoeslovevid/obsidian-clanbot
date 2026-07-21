/**
 * Obsidian Overseer — Mod Dashboard
 */
(function () {
  "use strict";

  var TOKEN_KEY = "obsidian_dashboard_token";
  var GUILD_KEY = "obsidian_dashboard_guild";
  var REFRESH_MS = 60000;

  var FEATURE_META = {};

  var GROUP_ORDER = [];

  var SETUP_SECTION_LABELS = {
    core: "Core channels",
    warframe: "Warframe feeds",
    moderation: "Moderation logs",
  };

  function channelSelectOptions(field, options) {
    var list =
      field.channel_type === "category"
        ? (options && options.categories) || []
        : (options && options.text_channels) || [];
    var html = '<option value="">— Not set —</option>';
    list.forEach(function (c) {
      html +=
        '<option value="' +
        escapeHtml(c.id) +
        '"' +
        (String(field.channel_id) === String(c.id) ? " selected" : "") +
        ">#" +
        escapeHtml(c.name) +
        "</option>";
    });
    return html;
  }

  async function saveSetupFields() {
    if (!state.guildId) return;
    var updates = [];
    el("dash-setup")
      .querySelectorAll("select[data-setup-key]")
      .forEach(function (sel) {
        updates.push({
          key: sel.getAttribute("data-setup-key"),
          channel_id: sel.value || null,
        });
      });
    try {
      var data = await apiFetch("/api/guilds/" + state.guildId + "/setup", {
        method: "PATCH",
        body: JSON.stringify({ updates: updates }),
      });
      state.setup = data;
      renderSetup();
      if (data.errors && data.errors.length) {
        toast(data.errors.join("; "), "error");
      } else {
        toast("Setup saved", "success");
      }
    } catch (err) {
      toast(err.message || "Could not save setup", "error");
    }
  }

  async function createGiveawayFromForm(form) {
    if (!state.guildId) return;
    var channelId = form.channel_id.value;
    var prize = form.prize.value.trim();
    var endLocal = form.end_time.value;
    if (!channelId || !prize || !endLocal) {
      toast("Channel, prize, and end time are required", "error");
      return;
    }
    var payload = {
      channel_id: channelId,
      prize: prize,
      end_time: new Date(endLocal).toISOString(),
      winner_count: parseInt(form.winner_count.value, 10) || 1,
      title: form.title.value.trim() || null,
      description: form.description.value.trim() || null,
      required_role_id: form.required_role_id.value || null,
      min_level: form.min_level.value ? parseInt(form.min_level.value, 10) : null,
    };
    try {
      var result = await apiFetch("/api/guilds/" + state.guildId + "/giveaways", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!result.ok) {
        toast(result.error || "Could not create giveaway", "error");
        return;
      }
      toast("Giveaway created", "success");
      form.reset();
      state.giveaways = await apiFetch("/api/guilds/" + state.guildId + "/giveaways");
      renderGiveaways();
    } catch (err) {
      toast(err.message || "Could not create giveaway", "error");
    }
  }

  async function endGiveawayById(id) {
    if (!state.guildId || !window.confirm("End this giveaway now and pick winners?")) return;
    try {
      var result = await apiFetch(
        "/api/guilds/" + state.guildId + "/giveaways/" + id + "/end",
        { method: "POST" }
      );
      if (!result.ok) {
        toast(result.error || result.message || "Could not end giveaway", "error");
        return;
      }
      toast(result.message || "Giveaway ended", "success");
      state.giveaways = await apiFetch("/api/guilds/" + state.guildId + "/giveaways");
      renderGiveaways();
    } catch (err) {
      toast(err.message || "Could not end giveaway", "error");
    }
  }

  var state = {
    me: null,
    overview: null,
    inbox: null,
    features: null,
    setup: null,
    warframe: null,
    analytics: null,
    audit: null,
    giveaways: null,
    guildId: null,
    activeTab: "overview",
    refreshTimer: null,
    loading: false,
    searchTimer: null,
  };

  var TAB_FETCHERS = {
    features: function (gid) {
      return apiFetch("/api/guilds/" + gid + "/features");
    },
    setup: function (gid) {
      return apiFetch("/api/guilds/" + gid + "/setup");
    },
    analytics: function (gid) {
      return apiFetch("/api/guilds/" + gid + "/analytics");
    },
    audit: function (gid) {
      return apiFetch("/api/guilds/" + gid + "/audit?limit=50");
    },
    giveaways: function (gid) {
      return apiFetch("/api/guilds/" + gid + "/giveaways");
    },
  };

  function clearGuildData() {
    state.overview = null;
    state.inbox = null;
    state.features = null;
    state.setup = null;
    state.warframe = null;
    state.analytics = null;
    state.audit = null;
    state.giveaways = null;
  }

  async function fetchCoreData(guildId) {
    var results = await Promise.all([
      apiFetch("/api/guilds/" + guildId + "/overview"),
      apiFetch("/api/guilds/" + guildId + "/inbox"),
      apiFetch("/api/guilds/" + guildId + "/warframe"),
    ]);
    state.overview = results[0];
    state.inbox = results[1];
    state.warframe = results[2];
  }

  async function fetchTabData(guildId, tab) {
    if (!TAB_FETCHERS[tab]) return;
    if (tab === "giveaways" && !state.setup) {
      state.setup = await TAB_FETCHERS.setup(guildId);
    }
    var data = await TAB_FETCHERS[tab](guildId);
    state[tab] = data;
  }

  async function ensureTabData(tab) {
    if (!state.guildId || !tab) return;
    if (["overview", "inbox", "moderation"].indexOf(tab) >= 0) {
      if (!state.overview) await fetchCoreData(state.guildId);
      return;
    }
    if (state[tab]) return;
    await fetchTabData(state.guildId, tab);
  }

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
    var redirectUri = window.location.origin + window.location.pathname;
    var verifier = sessionStorage.getItem("pkce_verifier") || "";
    var data = null;

    // Prefer server-side exchange (keeps Discord client secret on Railway).
    var botExchange = window.ObsidianSite && window.ObsidianSite.apiUrl("/api/auth/token");
    if (botExchange) {
      try {
        var botRes = await fetch(botExchange, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code: code,
            redirect_uri: redirectUri,
            code_verifier: verifier,
          }),
        });
        var botData = await botRes.json().catch(function () {
          return {};
        });
        if (botRes.ok && botData.access_token) {
          data = botData;
        } else if (botRes.status === 429) {
          throw new Error(
            "The bot API is temporarily rate-limited. Wait a minute and try logging in again."
          );
        }
      } catch (err) {
        if (err && String(err.message || "").indexOf("rate-limited") >= 0) throw err;
      }
    }

    // Fallback: public-client PKCE directly with Discord (requires Public Client flag).
    if (!data) {
      var body = new URLSearchParams({
        client_id: c.DISCORD_CLIENT_ID,
        grant_type: "authorization_code",
        code: code,
        redirect_uri: redirectUri,
        code_verifier: verifier,
      });
      var res = await fetch("https://discord.com/api/oauth2/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });
      if (!res.ok) {
        throw new Error(
          "Discord login failed. Add DISCORD_CLIENT_SECRET on Railway, or enable Public Client in the Discord Developer Portal."
        );
      }
      data = await res.json();
    }

    if (!data.access_token) throw new Error("Discord login failed — no access token returned.");
    sessionStorage.removeItem("pkce_verifier");
    sessionStorage.setItem(TOKEN_KEY, data.access_token);
    window.history.replaceState({}, document.title, window.location.pathname);
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  async function probeBotApi() {
    var base = window.ObsidianSite && window.ObsidianSite.apiUrl("/api/ping");
    if (!base) return { status: "unconfigured" };
    // Cache-bust so Railway/CDN cannot reuse a no-Origin cached response.
    var url = base + (base.indexOf("?") >= 0 ? "&" : "?") + "_cb=" + Date.now();
    try {
      var res = await fetch(url, {
        cache: "no-store",
        mode: "cors",
        headers: { Accept: "application/json" },
      });
      var acao = res.headers.get("Access-Control-Allow-Origin");
      var data = await res.json().catch(function () {
        return null;
      });
      if (res.status === 429) return { status: "rate_limited", acao: acao };
      if (res.ok && data && data.ok) return { status: "ok", acao: acao, data: data };
      if (res.ok && !data) return { status: "bad_json", acao: acao };
      return { status: "http_" + res.status, acao: acao };
    } catch (err) {
      return { status: "cors_blocked", detail: String((err && err.message) || err) };
    }
  }

  function apiUnreachableMessage(probe) {
    var status = typeof probe === "string" ? probe : (probe && probe.status) || "unreachable";
    if (status === "rate_limited") {
      return "Railway is rate-limiting the bot API (HTTP 429). Wait a minute and press Refresh.";
    }
    if (status === "unconfigured") {
      return "BOT_API_URL is missing in web/assets/config.js.";
    }
    if (status === "cors_blocked") {
      var fallback =
        ((window.OBSIDIAN_SITE && window.OBSIDIAN_SITE.BOT_API_URL) || "").replace(/\/$/, "") +
        "/dashboard.html";
      return (
        "Browser blocked the API (CORS) from the main website. " +
        "Use the same-origin dashboard instead: " +
        fallback +
        " — then log in there. (Also redeploy Railway so CDN cache/CORS headers refresh.)"
      );
    }
    if (status === "bad_json") {
      return "Bot API returned a non-JSON response. Confirm the Railway service is the Discord bot with DASHBOARD_API_ENABLED=true.";
    }
    if (status.indexOf("http_") === 0) {
      return "Bot API returned " + status.replace("http_", "") + ". Confirm DASHBOARD_API_ENABLED=true and redeploy on Railway.";
    }
    return "Could not reach the bot API from the browser. Redeploy Railway from latest main, then hard-refresh.";
  }

  async function apiFetch(path, options) {
    var url = window.ObsidianSite && window.ObsidianSite.apiUrl(path);
    if (!url) throw new Error("Dashboard is temporarily unavailable. Please try again later.");
    options = options || {};
    var method = String(options.method || "GET").toUpperCase();
    if (method === "GET" || method === "HEAD") {
      url += (url.indexOf("?") >= 0 ? "&" : "?") + "_cb=" + Date.now();
    }
    options.headers = options.headers || {};
    options.headers.Authorization = "Bearer " + token();
    options.headers.Accept = options.headers.Accept || "application/json";
    options.cache = "no-store";
    options.mode = "cors";
    if (options.body && !options.headers["Content-Type"]) {
      options.headers["Content-Type"] = "application/json";
    }

    var attempts = 0;
    var lastErr = null;
    while (attempts < 3) {
      attempts += 1;
      var res;
      try {
        res = await fetch(url, options);
      } catch (err) {
        var probe = await probeBotApi();
        lastErr = new Error(apiUnreachableMessage(probe));
        await sleep(500 * attempts);
        continue;
      }

      var raw = await res.text();
      var data = {};
      try {
        data = raw ? JSON.parse(raw) : {};
      } catch (_) {
        data = { message: raw && raw.slice(0, 160) };
      }

      if (res.status === 429) {
        lastErr = new Error(apiUnreachableMessage("rate_limited"));
        await sleep(1200 * attempts);
        continue;
      }
      if (res.status === 401) {
        sessionStorage.removeItem(TOKEN_KEY);
        throw new Error(data.message || "Session expired — please log in again.");
      }
      if (!res.ok) {
        throw new Error(data.message || data.error || "API error " + res.status);
      }
      return data;
    }
    throw lastErr || new Error("API request failed");
  }

  /* ——— Tabs ——— */
  function setTab(name) {
    state.activeTab = name;
    document.querySelectorAll(".dash-tab").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-tab") === name);
    });
    document.querySelectorAll(".dash-tab-panel").forEach(function (panel) {
      panel.classList.toggle("active", panel.id === "tab-" + name);
    });
    if (!state.guildId || state.loading) return;
    ensureTabData(name)
      .then(function () {
        renderAll();
      })
      .catch(function (err) {
        toast(err.message || String(err), "error");
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
    var data = state.features || {};
    var catalog = data.catalog || [];
    var groups = data.groups || [];
    if (!catalog.length && data.features) {
      Object.keys(data.features).forEach(function (key) {
        catalog.push({
          id: key,
          group: "Other",
          label: key,
          desc: "",
          toggleable: true,
          enabled: data.features[key],
        });
      });
    }

    catalog.forEach(function (item) {
      FEATURE_META[item.id] = { label: item.label, group: item.group, desc: item.desc };
    });
    if (groups.length) GROUP_ORDER = groups;

    var byGroup = {};
    catalog.forEach(function (item) {
      var group = item.group || "Other";
      if (!byGroup[group]) byGroup[group] = [];
      byGroup[group].push(item);
    });

    var html = "";
    GROUP_ORDER.concat(
      Object.keys(byGroup).filter(function (g) {
        return GROUP_ORDER.indexOf(g) < 0;
      })
    ).forEach(function (group) {
      if (!byGroup[group] || !byGroup[group].length) return;
      html +=
        '<div class="dash-feature-group"><h3>' +
        escapeHtml(group) +
        '</h3><div class="dash-feature-grid">';
      byGroup[group].forEach(function (item) {
        html +=
          '<div class="dash-feature-card' +
          (item.toggleable ? "" : " dash-feature-card-static") +
          '"><div class="dash-feature-info"><strong>' +
          escapeHtml(item.label) +
          "</strong><span>" +
          escapeHtml(item.desc || "") +
          "</span>";
        if (item.hint) {
          html += '<span class="dash-feature-hint">' + escapeHtml(item.hint) + "</span>";
        }
        html += "</div>";
        if (item.toggleable) {
          html +=
            '<label class="dash-switch" aria-label="Toggle ' +
            escapeHtml(item.label) +
            '"><input type="checkbox" data-feature="' +
            escapeHtml(item.id) +
            '" ' +
            (item.enabled ? "checked" : "") +
            ' /><span class="dash-switch-slider"></span></label>';
        } else {
          html += '<span class="dash-badge dash-badge-ok">Included</span>';
        }
        html += "</div>";
      });
      html += "</div></div>";
    });

    el("dash-features").innerHTML =
      html || '<p class="dash-meta">No features configured.</p>';

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

    var fields = setup.fields || [];
    var options = setup.options || {};
    if (fields.length) {
      html += '<div class="dash-setup-editor"><h3>Edit channels</h3>';
      ["core", "warframe", "moderation"].forEach(function (sectionId) {
        var sectionFields = fields.filter(function (f) {
          return f.section === sectionId;
        });
        if (!sectionFields.length) return;
        html += '<div class="dash-setup-section"><h4>' + escapeHtml(SETUP_SECTION_LABELS[sectionId] || sectionId) + "</h4>";
        sectionFields.forEach(function (field) {
          html +=
            '<label class="dash-field-row"><span class="dash-field-label">' +
            escapeHtml(field.label) +
            '</span><select class="dash-select" data-setup-key="' +
            escapeHtml(field.key) +
            '">' +
            channelSelectOptions(field, options) +
            "</select></label>";
        });
        html += "</div>";
      });
      html +=
        '<div class="dash-field-actions"><button type="button" class="dash-btn dash-btn-primary" id="dash-setup-save">Save setup</button></div></div>';
    }

    el("dash-setup").innerHTML = html;

    var saveBtn = el("dash-setup-save");
    if (saveBtn) {
      saveBtn.addEventListener("click", saveSetupFields);
    }
  }

  function renderGiveaways() {
    var node = el("dash-giveaways");
    if (!node) return;
    var data = state.giveaways;
    var options = (state.setup && state.setup.options) || {};
    var channels = options.text_channels || [];
    var roles = options.roles || [];

    if (!data) {
      node.innerHTML = '<p class="dash-meta">Loading giveaways…</p>';
      return;
    }

    var channelOpts = '<option value="">Select channel…</option>';
    channels.forEach(function (c) {
      channelOpts += '<option value="' + escapeHtml(c.id) + '">#' + escapeHtml(c.name) + "</option>";
    });
    var roleOpts = '<option value="">Any role</option>';
    roles.forEach(function (r) {
      roleOpts += '<option value="' + escapeHtml(r.id) + '">' + escapeHtml(r.name) + "</option>";
    });

    var html =
      '<div class="dash-panel"><h2>🎁 Create giveaway</h2>' +
      '<form id="dash-giveaway-form" class="dash-form-grid">' +
      '<label class="dash-field-row"><span class="dash-field-label">Channel</span><select class="dash-select" name="channel_id" required>' +
      channelOpts +
      '</select></label>' +
      '<label class="dash-field-row"><span class="dash-field-label">Prize</span><input class="dash-input" name="prize" required placeholder="e.g. 1000 platinum" /></label>' +
      '<label class="dash-field-row"><span class="dash-field-label">Ends</span><input class="dash-input" type="datetime-local" name="end_time" required /></label>' +
      '<label class="dash-field-row"><span class="dash-field-label">Winners</span><input class="dash-input" type="number" name="winner_count" min="1" max="20" value="1" /></label>' +
      '<label class="dash-field-row"><span class="dash-field-label">Title</span><input class="dash-input" name="title" placeholder="Optional title" /></label>' +
      '<label class="dash-field-row dash-field-wide"><span class="dash-field-label">Description</span><textarea class="dash-input" name="description" rows="2" placeholder="Optional details"></textarea></label>' +
      '<label class="dash-field-row"><span class="dash-field-label">Required role</span><select class="dash-select" name="required_role_id">' +
      roleOpts +
      '</select></label>' +
      '<label class="dash-field-row"><span class="dash-field-label">Min level</span><input class="dash-input" type="number" name="min_level" min="1" placeholder="Optional" /></label>' +
      '<div class="dash-field-actions dash-field-wide"><button type="submit" class="dash-btn dash-btn-primary">Create giveaway</button></div>' +
      "</form></div>";

    html += '<div class="dash-panel" style="margin-top:16px"><h2>Active giveaways</h2>';
    if (!(data.active && data.active.length)) {
      html += '<div class="dash-empty"><p>No active giveaways.</p></div>';
    } else {
      html += '<div class="dash-table-wrap"><table class="dash-table"><thead><tr><th>Prize</th><th>Channel</th><th>Entries</th><th>Ends</th><th></th></tr></thead><tbody>';
      data.active.forEach(function (g) {
        html +=
          "<tr><td><strong>" +
          escapeHtml(g.prize) +
          '</strong><div class="dash-meta">' +
          escapeHtml(g.title || "") +
          '</div></td><td>#' +
          escapeHtml(g.channel_name || g.channel_id) +
          "</td><td>" +
          (g.entry_count || 0) +
          '</td><td><span class="dash-meta">' +
          escapeHtml(timeUntil(g.end_time)) +
          ' left</span></td><td class="dash-table-actions">' +
          (g.jump_url
            ? '<a href="' + escapeHtml(g.jump_url) + '" target="_blank" rel="noopener" class="dash-btn dash-btn-sm dash-btn-ghost">Open</a> '
            : "") +
          '<button type="button" class="dash-btn dash-btn-sm dash-btn-danger" data-end-giveaway="' +
          g.id +
          '">End</button></td></tr>';
      });
      html += "</tbody></table></div>";
    }
    html += "</div>";

    node.innerHTML = html;

    var form = el("dash-giveaway-form");
    if (form) {
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        createGiveawayFromForm(form);
      });
    }
    node.querySelectorAll("[data-end-giveaway]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        endGiveawayById(parseInt(btn.getAttribute("data-end-giveaway"), 10));
      });
    });
  }

  function timeUntil(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var sec = Math.floor((d.getTime() - Date.now()) / 1000);
    if (sec <= 0) return "soon";
    if (sec < 60) return sec + "s";
    if (sec < 3600) return Math.floor(sec / 60) + "m";
    if (sec < 86400) return Math.floor(sec / 3600) + "h";
    return Math.floor(sec / 86400) + "d";
  }

  function renderBaroMini() {
    var wf = state.warframe;
    var node = el("dash-baro-mini");
    if (!node || !wf || !wf.baro) {
      if (node) node.innerHTML = "";
      return;
    }
    var b = wf.baro;
    if (!b.available) {
      node.innerHTML =
        '<div class="dash-baro-status"><h3>🛸 Baro Ki\'Teer</h3><p class="dash-meta">Warframe API unavailable — try Refresh.</p></div>';
      return;
    }
    var status = b.active
      ? "At <strong>" + escapeHtml(b.location) + "</strong> · leaves in " + escapeHtml(timeUntil(b.expiry))
      : "Not at a relay right now";
    var chips = (b.inventory_preview || [])
      .slice(0, 4)
      .map(function (i) {
        return '<span class="dash-baro-chip">' + escapeHtml(i.name) + "</span>";
      })
      .join("");
    node.innerHTML =
      '<div class="dash-baro-status"><h3>🛸 Baro Ki\'Teer</h3><p class="dash-meta">' +
      status +
      (b.inventory_count ? " · <strong>" + b.inventory_count + "</strong> items" : "") +
      '</p></div><div class="dash-baro-items">' +
      (chips || '<span class="dash-meta">No stock listed</span>') +
      '</div><a class="dash-btn dash-btn-ghost dash-btn-sm" href="' +
      escapeHtml(publicWorldStateUrl()) +
      '">Open World state →</a>';
  }

  function publicWorldStateUrl() {
    try {
      var api = (cfg().BOT_API_URL || "").replace(/\/$/, "");
      if (api) {
        if (!/^https?:\/\//i.test(api)) api = "https://" + api;
        if (window.location.host === new URL(api).host) {
          return "https://obsidianoverseer.com/warframe.html";
        }
      }
    } catch (_) {}
    return "/warframe.html";
  }

  function renderBarChart(rows, labelKey, valueKey, maxBars) {
    if (!rows || !rows.length) {
      return '<div class="dash-empty"><p>No data yet.</p></div>';
    }
    var max = Math.max.apply(
      null,
      rows.map(function (r) {
        return r[valueKey] || 0;
      }).concat([1])
    );
    return (
      '<div class="dash-bar-chart">' +
      rows.slice(0, maxBars || 8).map(function (r) {
        var v = r[valueKey] || 0;
        var pct = Math.round((v / max) * 100);
        return (
          '<div class="dash-bar-row"><span class="dash-bar-label" title="' +
          escapeHtml(r[labelKey] || "") +
          '">' +
          escapeHtml(String(r[labelKey] || "").slice(0, 14)) +
          '</span><div class="dash-bar-track"><div class="dash-bar-fill" style="width:' +
          pct +
          '%"></div></div><span class="dash-bar-value">' +
          v +
          "</span></div>"
        );
      }).join("") +
      "</div>"
    );
  }

  function renderAnalytics() {
    var a = state.analytics;
    var node = el("dash-analytics");
    if (!node) return;
    if (!a) {
      node.innerHTML = '<p class="dash-meta">Loading analytics…</p>';
      return;
    }
    var html =
      '<div class="dash-metric-row">' +
      '<div class="dash-metric"><strong>' +
      (a.member_count != null ? a.member_count : "—") +
      '</strong><span>Members</span></div>' +
      '<div class="dash-metric"><strong>' +
      (a.active_users_7d || 0) +
      '</strong><span>Active (7d)</span></div>' +
      '<div class="dash-metric"><strong>' +
      (a.commands_7d || 0) +
      '</strong><span>Commands (7d)</span></div>' +
      '<div class="dash-metric"><strong>' +
      (a.economy_volume_7d || 0).toLocaleString() +
      '</strong><span>Coins earned (7d)</span></div>' +
      "</div>";

    html += '<div class="dash-chart-grid">';
    html +=
      '<div class="dash-panel"><div class="dash-chart-title">Daily commands (14d)</div>' +
      renderBarChart(
        (a.daily_activity || []).map(function (d) {
          return { label: d.date.slice(5), value: d.commands };
        }),
        "label",
        "value",
        14
      ) +
      "</div>";
    html +=
      '<div class="dash-panel"><div class="dash-chart-title">Top members (weekly score)</div>' +
      renderBarChart(
        (a.top_members || []).map(function (m) {
          return { label: m.user_name, value: m.weekly_score };
        }),
        "label",
        "value",
        8
      ) +
      "</div>";
    html += "</div>";

    var c = a.counts || {};
    html +=
      '<div class="dash-panel" style="margin-top:16px"><h2>Live counts</h2><ul class="dash-setup-list">' +
      "<li>🎫 Open tickets: <strong>" +
      (c.open_tickets || 0) +
      "</strong></li>" +
      "<li>📋 Pending applications: <strong>" +
      (c.pending_apps || 0) +
      "</strong></li>" +
      "<li>👥 Open LFG: <strong>" +
      (c.open_lfg || 0) +
      "</strong></li></ul></div>";

    node.innerHTML = html;
  }

  var AUDIT_ICONS = { warning: "⚠️", complaint: "⚖️", ticket_closed: "🎫" };

  function renderAudit() {
    var data = state.audit;
    var node = el("dash-audit");
    if (!node) return;
    var entries = (data && data.entries) || [];
    if (!entries.length) {
      node.innerHTML = '<div class="dash-empty"><div class="dash-empty-icon">📜</div><p>No audit entries found.</p></div>';
      return;
    }
    node.innerHTML =
      '<ul class="dash-audit-list">' +
      entries
        .map(function (e) {
          return (
            '<li class="dash-audit-item"><div class="dash-audit-icon">' +
            (AUDIT_ICONS[e.type] || "•") +
            '</div><div class="dash-audit-body"><strong>' +
            escapeHtml(e.summary || e.type) +
            '</strong><div class="dash-audit-meta">' +
            escapeHtml(e.actor_name || "System") +
            (e.target_name ? " → " + escapeHtml(e.target_name) : "") +
            " · " +
            escapeHtml(timeAgo(e.timestamp)) +
            "</div></div></li>"
          );
        })
        .join("") +
      "</ul>";
  }

  async function loadAudit(filter) {
    if (!state.guildId) return;
    try {
      var q = filter ? "?q=" + encodeURIComponent(filter) + "&limit=50" : "?limit=50";
      state.audit = await apiFetch("/api/guilds/" + state.guildId + "/audit" + q);
      renderAudit();
    } catch (err) {
      el("dash-audit").innerHTML = '<p class="dash-meta">' + escapeHtml(err.message || "Failed to load audit") + "</p>";
    }
  }

  function renderSearchResults(data) {
    var box = el("dash-search-results");
    if (!box) return;
    var results = (data && data.results) || [];
    if (!results.length) {
      box.innerHTML = '<div class="dash-search-hit"><span>No results</span></div>';
      box.hidden = false;
      return;
    }
    box.innerHTML = results
      .map(function (r, idx) {
        return (
          '<div class="dash-search-hit" data-idx="' +
          idx +
          '"><strong>' +
          escapeHtml(r.title) +
          '</strong><span>' +
          escapeHtml(r.kind) +
          " · " +
          escapeHtml(r.subtitle || "") +
          "</span></div>"
        );
      })
      .join("");
    box.hidden = false;
    box.querySelectorAll(".dash-search-hit").forEach(function (hit) {
      hit.addEventListener("click", function () {
        var r = results[parseInt(hit.getAttribute("data-idx"), 10)];
        if (r.jump_url) window.open(r.jump_url, "_blank", "noopener");
        else if (r.kind === "ticket") setTab("inbox");
        else if (r.kind === "application") setTab("inbox");
        else if (r.kind === "warning") setTab("audit");
        box.hidden = true;
        el("dash-search").value = "";
      });
    });
  }

  async function runSearch(q) {
    if (!state.guildId || q.length < 2) {
      el("dash-search-results").hidden = true;
      return;
    }
    try {
      var data = await apiFetch("/api/guilds/" + state.guildId + "/search?q=" + encodeURIComponent(q));
      renderSearchResults(data);
    } catch (_) {
      el("dash-search-results").hidden = true;
    }
  }

  function renderAll() {
    renderAlerts();
    renderBaroMini();
    renderStats();
    renderAttention();
    renderTickets();
    renderApps();
    renderModStatus();
    renderWarnings();
    renderFeatures();
    renderSetup();
    renderAnalytics();
    renderAudit();
    renderGiveaways();

    if (state.overview && state.overview.refreshed_at) {
      el("dash-refreshed").textContent = "Updated " + timeAgo(state.overview.refreshed_at);
    }
  }

  function setLoading(on) {
    state.loading = on;
    el("dash-loading").style.display = on ? "block" : "none";
    el("dash-skeleton").style.display = on ? "block" : "none";
    if (on) {
      ["dash-baro-mini", "dash-stats", "dash-attention", "dash-tickets", "dash-apps", "dash-mod-status", "dash-warnings", "dash-features", "dash-setup", "dash-analytics", "dash-audit", "dash-giveaways"].forEach(function (id) {
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
      clearGuildData();
      await fetchCoreData(guildId);
      var tab = state.activeTab || "overview";
      if (TAB_FETCHERS[tab]) await fetchTabData(guildId, tab);
      renderAll();
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }

  async function refreshGuildData(quiet) {
    if (!state.guildId) return;
    if (!quiet) setLoading(true);
    showError("");
    try {
      await fetchCoreData(state.guildId);
      var tab = state.activeTab || "overview";
      if (TAB_FETCHERS[tab]) await fetchTabData(state.guildId, tab);
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
      if (state.guildId && !state.loading) refreshGuildData(true);
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
      // Confirm cross-origin API access before loading guild data.
      var probe = await probeBotApi();
      if (!probe || probe.status !== "ok") {
        throw new Error(apiUnreachableMessage(probe));
      }

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
        showError(
          "No servers found where you have Administrator/Manage Server and Obsidian Overseer is installed. Invite the bot, then log out and back in."
        );
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
      if (state.guildId) refreshGuildData(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "r" || e.key === "R") {
        if (document.activeElement && document.activeElement.tagName === "INPUT") return;
        if (state.guildId) refreshGuildData(false);
      }
    });

    var searchInput = el("dash-search");
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        clearTimeout(state.searchTimer);
        var q = searchInput.value.trim();
        state.searchTimer = setTimeout(function () {
          runSearch(q);
        }, 350);
      });
      searchInput.addEventListener("blur", function () {
        setTimeout(function () {
          var box = el("dash-search-results");
          if (box) box.hidden = true;
        }, 200);
      });
    }

    var auditFilter = el("dash-audit-filter");
    if (auditFilter) {
      auditFilter.addEventListener("input", function () {
        clearTimeout(state.searchTimer);
        var q = auditFilter.value.trim();
        state.searchTimer = setTimeout(function () {
          loadAudit(q || null);
        }, 400);
      });
    }

    initDashboard();
  });
})();
