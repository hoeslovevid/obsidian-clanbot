/**
 * Prime Vault — vaulted warframes + Varzia inventory
 */
(function () {
  var API = "https://api.warframestat.us";

  var statusEl = document.getElementById("vt-status");
  var traderMeta = document.getElementById("vt-trader-meta");
  var inventoryEl = document.getElementById("vt-inventory");
  var warframesEl = document.getElementById("vt-warframes");
  var searchEl = document.getElementById("vt-search");

  var vaultedFrames = [];

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(ok, text) {
    if (!statusEl) return;
    statusEl.className = "tool-status" + (ok ? "" : " err");
    statusEl.innerHTML = '<span class="dot" aria-hidden="true"></span>' + esc(text);
  }

  function fetchJson(path) {
    return fetch(API + path + (path.indexOf("?") >= 0 ? "&" : "?") + "language=en", {
      cache: "no-store",
      headers: { Accept: "application/json" },
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  function marketUrl(name) {
    return "/market.html?q=" + encodeURIComponent(name || "");
  }

  function formatExpiry(iso) {
    if (!iso) return "—";
    try {
      var d = new Date(iso);
      if (isNaN(d.getTime())) return iso;
      var now = Date.now();
      var diff = d.getTime() - now;
      var rel = d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
      if (diff <= 0) return rel + " (expired)";
      var hrs = Math.floor(diff / 3600000);
      var days = Math.floor(hrs / 24);
      if (days > 0) return rel + " · " + days + "d left";
      return rel + " · " + hrs + "h left";
    } catch (e) {
      return iso;
    }
  }

  function ayaLabel(entry) {
    var name = String(entry.item || "");
    var path = String(entry.uniqueName || "");
    var isRegal =
      /Pack|MPV|MegaPrimeVault/i.test(name) || /Pack|MegaPrimeVault|MPV/i.test(path);
    if (entry.ducats != null) {
      return isRegal ? entry.ducats + " Regal Aya" : entry.ducats + " Aya";
    }
    if (entry.credits != null) return entry.credits + " credits";
    return "—";
  }

  function renderTrader(data) {
    if (!data) {
      if (traderMeta) traderMeta.textContent = "Vault trader data unavailable.";
      if (inventoryEl) inventoryEl.innerHTML = "";
      return;
    }
    var who = data.character || "Varzia";
    var loc = data.location || "Unknown";
    if (traderMeta) {
      traderMeta.textContent =
        who + " · " + loc + " · expires " + formatExpiry(data.expiry);
    }
    if (!inventoryEl) return;
    var items = data.inventory || [];
    if (!items.length) {
      inventoryEl.innerHTML = "<li>No inventory listed.</li>";
      return;
    }
    var html = "";
    items.forEach(function (entry) {
      var name = entry.item || "Unknown";
      html +=
        "<li><strong><a href=\"" +
        esc(marketUrl(name)) +
        '">' +
        esc(name) +
        "</a></strong> · " +
        esc(ayaLabel(entry)) +
        "</li>";
    });
    inventoryEl.innerHTML = html;
  }

  function renderWarframes(filter) {
    if (!warframesEl) return;
    var q = String(filter || "")
      .trim()
      .toLowerCase();
    var list = vaultedFrames.filter(function (wf) {
      if (!q) return true;
      return String(wf.name || "")
        .toLowerCase()
        .indexOf(q) >= 0;
    });
    if (!list.length) {
      warframesEl.innerHTML = "<li>No vaulted warframes match.</li>";
      return;
    }
    var html = "";
    list.forEach(function (wf) {
      html +=
        "<li><strong><a href=\"" +
        esc(marketUrl(wf.name)) +
        '">' +
        esc(wf.name) +
        "</a></strong> <span class=\"vt-badge\">Vaulted</span></li>";
    });
    warframesEl.innerHTML = html;
  }

  function load() {
    setStatus(true, "Loading vault data…");

    var framesP = fetchJson("/warframes").then(function (list) {
      vaultedFrames = (list || []).filter(function (wf) {
        return wf.vaulted === true;
      });
      vaultedFrames.sort(function (a, b) {
        return String(a.name || "").localeCompare(String(b.name || ""));
      });
      renderWarframes(searchEl ? searchEl.value : "");
      return vaultedFrames.length;
    });

    var traderP = fetchJson("/pc/vaultTrader")
      .then(function (data) {
        renderTrader(data);
        return data;
      })
      .catch(function () {
        renderTrader(null);
        return null;
      });

    Promise.all([framesP, traderP])
      .then(function (pair) {
        setStatus(true, pair[0] + " vaulted frames · Varzia rotation loaded");
      })
      .catch(function () {
        setStatus(false, "Could not load vault data.");
      });
  }

  if (searchEl) {
    searchEl.addEventListener("input", function () {
      renderWarframes(searchEl.value);
    });
  }

  load();
})();
