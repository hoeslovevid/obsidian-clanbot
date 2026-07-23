/** Prime-part ducat versus platinum helper. */
(function () {
  var API = "https://api.warframestat.us", CACHE = "oo_wfm_items_v1";
  var form = document.getElementById("worth-form"), qEl = document.getElementById("worth-query"), root = document.getElementById("worth-root"), statusEl = document.getElementById("worth-status");
  var catalog = [], results = [];
  function esc(s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function status(s, err) { statusEl.className = "tool-status" + (err ? " err" : ""); statusEl.innerHTML = '<span class="dot"></span>' + esc(s); }
  function proxy(path) {
    if (window.ObsidianSite && window.ObsidianSite.wfmProxyUrl) return window.ObsidianSite.wfmProxyUrl(path);
    var b = ((window.OBSIDIAN_SITE || {}).WFM_PROXY_URL || "").replace(/\/$/, ""); return b ? b + path : "";
  }
  function loadCatalog() {
    try { var c = JSON.parse(sessionStorage.getItem(CACHE) || "{}"); if (c.items && c.items.length) { catalog = c.items; return Promise.resolve(catalog); } } catch (_) {}
    return fetch("/assets/wfm-items.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); }).then(function (d) { catalog = d.items || []; try { sessionStorage.setItem(CACHE, JSON.stringify({ at: Date.now(), items: catalog })); } catch (_) {} return catalog; }).catch(function () { return []; });
  }
  function slugFor(name) {
    var n = String(name).toLowerCase();
    for (var i = 0; i < catalog.length; i++) if (String(catalog[i].name).toLowerCase() === n) return catalog[i].slug;
    return n.replace(/['’]/g, "").replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  }
  function pick(item) {
    var name = item.name || "", ducats = Number(item.ducats || 0), slug = slugFor(name);
    root.setAttribute("aria-busy", "true"); status("Loading market orders…");
    var url = proxy("/api/wfm/items/" + encodeURIComponent(slug) + "?platform=pc");
    var request = url ? fetch(url, { mode: "cors", credentials: "omit" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }) : Promise.reject(new Error("No proxy"));
    request.then(function (d) { render(item, slug, d.summary && d.summary.lowestSell); }).catch(function () { render(item, slug, null); });
  }
  function render(item, slug, plat) {
    var ducats = Number(item.ducats || 0), has = plat != null && isFinite(Number(plat)), p = has ? Number(plat) : null;
    var verdict = has ? (p < ducats / 10 ? "Melt for ducats" : "Sell for platinum") : "Check the market";
    root.innerHTML = '<article class="tool-card"><h2>' + esc(item.name) + '</h2><div class="tool-grid-2"><div><p class="tool-meta">Ducat value</p><h3>' + esc(ducats) + ' ducats</h3></div><div><p class="tool-meta">Lowest sell</p><h3>' + (has ? esc(p) + " platinum" : "Unavailable") + '</h3></div></div><p class="tool-prose"><strong>' + esc(verdict) + "</strong> · " + (item.vaulted ? "Vaulted" : "Not marked vaulted") + '</p><div class="tool-actions"><a class="btn-primary" href="/market.html?q=' + encodeURIComponent(item.name) + '">Market</a><a class="btn-secondary" href="/farm.html?q=' + encodeURIComponent(item.name) + '">Farm</a><a class="btn-secondary" href="/relics.html?q=' + encodeURIComponent(item.name) + '">Relics</a><a class="btn-secondary" target="_blank" rel="noopener noreferrer" href="https://warframe.market/items/' + esc(slug) + '">warframe.market</a></div></article>';
    status(has ? "Comparison ready" : "Item loaded · live prices unavailable", !has); root.setAttribute("aria-busy", "false");
    try { var u = new URL(location.href); u.searchParams.set("q", item.name); history.replaceState(null, "", u.pathname + u.search); } catch (_) {}
  }
  function search(q) {
    q = String(q || "").trim(); if (!q) return;
    status("Searching items…"); root.setAttribute("aria-busy", "true");
    fetch(API + "/items/search/" + encodeURIComponent(q) + "?language=en", { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(); return r.json(); }).then(function (list) {
      results = (list || []).filter(function (x) { return x && x.name && (x.ducats != null || /prime/i.test(x.name)); }).slice(0, 20);
      if (!results.length) throw new Error("No Prime parts found");
      if (results.length === 1 || String(results[0].name).toLowerCase() === q.toLowerCase()) return pick(results[0]);
      root.innerHTML = '<section class="tool-card"><h2>Select an item</h2><div class="tool-pills">' + results.map(function (x, i) { return '<button type="button" class="tool-pill" data-index="' + i + '">' + esc(x.name) + "</button>"; }).join("") + "</div></section>"; root.setAttribute("aria-busy", "false"); status(results.length + " matching Prime items");
    }).catch(function (e) { status(e.message || "Search failed", true); root.innerHTML = '<div class="tool-card">No matching Prime parts found.</div>'; root.setAttribute("aria-busy", "false"); });
  }
  root.addEventListener("click", function (e) { var b = e.target.closest("[data-index]"); if (b) pick(results[Number(b.getAttribute("data-index"))]); });
  form.addEventListener("submit", function (e) { e.preventDefault(); search(qEl.value); });
  loadCatalog().then(function () { var q = new URLSearchParams(location.search).get("q"); if (q) { qEl.value = q; search(q); } });
})();
