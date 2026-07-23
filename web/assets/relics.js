/**
 * Void relic browser — api.warframestat.us
 */
(function () {
  var API = "https://api.warframestat.us";

  var form = document.getElementById("rl-form");
  var queryEl = document.getElementById("rl-query");
  var root = document.getElementById("rl-root");
  var statusEl = document.getElementById("rl-status");
  var hideVaultedEl = document.getElementById("rl-hide-vaulted");
  var tierBtns = document.querySelectorAll("#rl-tiers .tool-pill[data-tier]");

  var state = { tier: "", query: "", hideVaulted: true, rawRelics: [] };
  var searchTimer = null;

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

  function relicTier(name) {
    var m = String(name || "").match(/^(Lith|Meso|Neo|Axi|Requiem|Omnia)\b/i);
    return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase() : "";
  }

  function buildSearchQuery() {
    var q = (state.query || "").trim();
    var tier = state.tier || "";
    if (q && tier) {
      if (q.toLowerCase().indexOf(tier.toLowerCase()) === 0) return q;
      return tier + " " + q;
    }
    if (q) return q;
    if (tier) return tier;
    return "";
  }

  function parseRelics(list) {
    return (list || []).filter(function (it) {
      if (it.type !== "Relic") return false;
      if (String(it.name || "").indexOf("Intact") < 0) return false;
      if (state.tier && relicTier(it.name) !== state.tier) return false;
      return true;
    });
  }

  function filterVaulted(list) {
    if (!state.hideVaulted) return list;
    return list.filter(function (it) {
      return !it.vaulted;
    });
  }

  function visibleRelics() {
    return filterVaulted(state.rawRelics);
  }

  function sortRelics(list) {
    return list.slice().sort(function (a, b) {
      return String(a.name || "").localeCompare(String(b.name || ""));
    });
  }

  function farmUrl(name) {
    return "/farm.html?q=" + encodeURIComponent(name || "");
  }

  function marketUrl(name) {
    return "/market.html?q=" + encodeURIComponent(name || "");
  }

  function voidUrl(tier) {
    return "/warframe.html?section=void&tiers=" + encodeURIComponent(tier || "Lith");
  }

  function rarityClass(r) {
    var x = String(r || "").toLowerCase();
    if (x.indexOf("legend") >= 0) return "rl-rarity rl-r-legendary";
    if (x.indexOf("rare") >= 0) return "rl-rarity rl-r-rare";
    if (x.indexOf("uncommon") >= 0) return "rl-rarity rl-r-uncommon";
    if (x.indexOf("common") >= 0) return "rl-rarity rl-r-common";
    return "rl-rarity";
  }

  function renderRewards(rewards) {
    if (!rewards || !rewards.length) return '<p class="tool-meta">No reward data</p>';
    var html = '<ul class="rl-rewards">';
    rewards.forEach(function (rw) {
      var itemName = (rw.item && rw.item.name) || rw.itemName || "?";
      html +=
        "<li><span class=\"" +
        rarityClass(rw.rarity) +
        '">' +
        esc(rw.rarity || "?") +
        "</span> " +
        '<a href="' +
        esc(farmUrl(itemName)) +
        '">' +
        esc(itemName) +
        "</a>" +
        ' · <a href="/worth.html?q=' +
        encodeURIComponent(itemName) +
        '">Worth</a></li>';
    });
    return html + "</ul>";
  }

  function render() {
    if (!root) return;
    var list = sortRelics(visibleRelics());
    if (!list.length) {
      root.innerHTML =
        '<div class="tool-card"><p class="tool-prose">No intact relics matched. Try another tier or search term.</p></div>';
      root.setAttribute("aria-busy", "false");
      return;
    }
    var html = "";
    list.forEach(function (rel) {
      var tier = relicTier(rel.name);
      var baseName = String(rel.name || "").replace(/\s+Intact$/i, "");
      html += '<article class="tool-card rl-card">';
      html += "<h3>" + esc(baseName) + "</h3>";
      html += '<p class="tool-meta">';
      if (rel.vaulted) html += '<span class="rl-badge rl-badge-vault">Vaulted</span> ';
      html += esc(tier) + " · Intact</p>";
      html += renderRewards(rel.rewards);
      html += '<div class="tool-actions">';
      html += '<a class="btn-secondary" href="' + esc(voidUrl(tier)) + '">Live fissures</a>';
      html += '<a class="btn-secondary" href="' + esc(marketUrl(baseName)) + '">Market</a>';
      html += '<a class="btn-secondary" href="/planner.html?want=' + encodeURIComponent(baseName) + '">Planner</a>';
      html += "</div></article>";
    });
    root.innerHTML = html;
    root.setAttribute("aria-busy", "false");
  }

  function syncUrl() {
    try {
      var url = new URL(window.location.href);
      if (state.tier) url.searchParams.set("tier", state.tier);
      else url.searchParams.delete("tier");
      if (state.query) url.searchParams.set("q", state.query);
      else url.searchParams.delete("q");
      url.searchParams.set("vaulted", state.hideVaulted ? "0" : "1");
      history.replaceState(null, "", url.pathname + url.search);
    } catch (e) {}
  }

  function syncTierUi() {
    tierBtns.forEach(function (btn) {
      var t = btn.getAttribute("data-tier");
      btn.classList.toggle("on", t === state.tier);
    });
  }

  function load() {
    var searchQ = buildSearchQuery();
    if (!searchQ) {
      setStatus(true, "Select a tier or search");
      state.rawRelics = [];
      render();
      return;
    }

    setStatus(true, "Loading relics for “" + searchQ + "”…");
    if (root) {
      root.setAttribute("aria-busy", "true");
      root.innerHTML = "";
    }

    fetchJson("/items/search/" + encodeURIComponent(searchQ))
      .then(function (list) {
        state.rawRelics = parseRelics(list);
        var shown = visibleRelics().length;
        setStatus(true, shown + " intact relic" + (shown === 1 ? "" : "s"));
        render();
        syncUrl();
      })
      .catch(function () {
        setStatus(false, "Could not load relic data. Try again.");
        if (root) {
          root.innerHTML = '<div class="tool-card"><p class="tool-prose">API request failed.</p></div>';
          root.setAttribute("aria-busy", "false");
        }
      });
  }

  function scheduleLoad() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(load, 280);
  }

  tierBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var t = btn.getAttribute("data-tier") || "";
      state.tier = state.tier === t ? "" : t;
      syncTierUi();
      load();
    });
  });

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      state.query = queryEl ? (queryEl.value || "").trim() : "";
      load();
    });
  }

  if (queryEl) {
    queryEl.addEventListener("input", function () {
      state.query = (queryEl.value || "").trim();
      scheduleLoad();
    });
  }

  if (hideVaultedEl) {
    hideVaultedEl.addEventListener("change", function () {
      state.hideVaulted = hideVaultedEl.checked;
      if (state.rawRelics.length) {
        var shown = visibleRelics().length;
        setStatus(true, shown + " intact relic" + (shown === 1 ? "" : "s"));
        render();
      }
      syncUrl();
    });
  }

  try {
    var params = new URLSearchParams(window.location.search);
    state.tier = params.get("tier") || "";
    state.query = params.get("q") || "";
    var vaulted = params.get("vaulted");
    if (vaulted === "1") state.hideVaulted = false;
    else if (vaulted === "0") state.hideVaulted = true;
    if (hideVaultedEl) hideVaultedEl.checked = state.hideVaulted;
    if (queryEl && state.query) queryEl.value = state.query;
    syncTierUi();
    if (state.tier || state.query) load();
  } catch (e) {}
})();
