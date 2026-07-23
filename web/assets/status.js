/**
 * Bot status page — live API with static JSON fallback
 */
(function () {
  var els = {};

  function fmtTime(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString();
    } catch (_) {
      return String(iso);
    }
  }

  function apiFetch(path) {
    var Site = window.ObsidianSite;
    if (!Site || !Site.apiUrl) return Promise.resolve(null);
    var url = Site.apiUrl(path);
    if (!url) return Promise.resolve(null);
    return fetch(url + (url.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now(), {
      cache: "no-store",
      mode: "cors",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .catch(function () {
        return null;
      });
  }

  function staticFetch(path) {
    return fetch(path, { cache: "no-cache" })
      .then(function (res) {
        if (!res.ok) throw new Error("missing");
        return res.json();
      })
      .catch(function () {
        return null;
      });
  }

  function setCard(id, value, sub, state) {
    var card = els[id];
    if (!card) return;
    var val = card.querySelector(".value");
    var subEl = card.querySelector(".sub");
    if (val) val.innerHTML = value;
    if (subEl) subEl.textContent = sub || "";
    card.classList.remove("ok", "warn", "err");
    if (state) card.classList.add(state);
  }

  function formatCount(n) {
    if (window.ObsidianSite && window.ObsidianSite.formatCount) {
      return window.ObsidianSite.formatCount(n);
    }
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString("en-US");
  }

  function render(ping, stats, statusFb, statsFb) {
    var online = false;
    var version = null;
    var statusUpdated = null;
    var statsUpdated = null;
    var guilds = null;
    var users = null;
    var source = "static";

    if (ping && ping.ok !== false) {
      online = true;
      version = ping.version || ping.bot_version || null;
      source = "live";
    } else if (statusFb && statusFb.ok !== false) {
      online = true;
      version = statusFb.version || null;
      statusUpdated = statusFb.updated_at || null;
    }

    if (!version && statusFb) version = statusFb.version || null;
    if (!statusUpdated && statusFb) statusUpdated = statusFb.updated_at || null;

    if (stats) {
      if (stats.guild_count != null) guilds = stats.guild_count;
      if (stats.user_count != null) users = stats.user_count;
      statsUpdated = stats.updated_at || null;
      source = "live";
    } else if (statsFb) {
      if (statsFb.guild_count != null) guilds = statsFb.guild_count;
      if (statsFb.user_count != null) users = statsFb.user_count;
      statsUpdated = statsFb.updated_at || null;
    }

    var apiLabel;
    if (online) {
      apiLabel =
        '<span class="status-dot" aria-hidden="true"></span>Online' +
        (version ? " · v" + version : "");
      setCard("status-api", apiLabel, source === "live" ? "Live API" : "Published snapshot", "ok");
    } else if (version) {
      apiLabel = "v" + version;
      setCard("status-api", apiLabel, "Published snapshot", "warn");
    } else {
      setCard("status-api", "Unavailable", "Could not reach API or static files", "err");
    }

    setCard("status-guilds", formatCount(guilds), guilds != null ? "Discord servers" : "", guilds != null ? "ok" : "");
    setCard("status-users", formatCount(users), users != null ? "Users reached" : "", users != null ? "ok" : "");

    var updatedParts = [];
    if (statusUpdated) updatedParts.push("Status: " + fmtTime(statusUpdated));
    if (statsUpdated) updatedParts.push("Stats: " + fmtTime(statsUpdated));
    setCard(
      "status-updated",
      updatedParts.length ? "Recent" : "—",
      updatedParts.join(" · ") || "No timestamp available",
      ""
    );

    var meta = document.getElementById("status-meta");
    if (meta) {
      meta.textContent = "Last checked " + fmtTime(new Date().toISOString());
    }
  }

  function load() {
    var btn = document.getElementById("status-refresh");
    if (btn) btn.disabled = true;
    return Promise.all([
      apiFetch("/api/ping"),
      apiFetch("/api/stats"),
      staticFetch("/assets/bot-status.json"),
      staticFetch("/assets/bot-stats.json"),
    ])
      .then(function (pair) {
        render(pair[0], pair[1], pair[2], pair[3]);
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  function init() {
    ["status-api", "status-guilds", "status-users", "status-updated"].forEach(function (id) {
      els[id] = document.getElementById(id);
    });
    var btn = document.getElementById("status-refresh");
    if (btn) btn.addEventListener("click", load);
    load();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
