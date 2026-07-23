/**
 * Ducat vs platinum helper — search WFM catalog, live orders via proxy.
 * (warframestat item search often omits Prime components, so Market is source of truth.)
 */
(function () {
  var CACHE = "oo_wfm_items_v1";
  var CACHE_MS = 6 * 60 * 60 * 1000;

  var form = document.getElementById("worth-form");
  var qEl = document.getElementById("worth-query");
  var root = document.getElementById("worth-root");
  var statusEl = document.getElementById("worth-status");
  var suggestEl = document.getElementById("worth-suggest");

  var catalog = [];
  var catalogReady = false;
  var results = [];
  var suggestTimer = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(text, err) {
    if (!statusEl) return;
    statusEl.className = "tool-status" + (err ? " err" : "");
    statusEl.innerHTML = '<span class="dot" aria-hidden="true"></span>' + esc(text);
  }

  function proxy(path) {
    if (window.ObsidianSite && typeof window.ObsidianSite.wfmProxyUrl === "function") {
      return window.ObsidianSite.wfmProxyUrl(path);
    }
    var base = ((window.OBSIDIAN_SITE || {}).WFM_PROXY_URL || "").replace(/\/$/, "");
    if (!base) return "";
    if (!/^https?:\/\//i.test(base)) base = "https://" + base;
    return base + (path.startsWith("/") ? path : "/" + path);
  }

  function loadCached() {
    try {
      var raw = sessionStorage.getItem(CACHE);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.items) || !parsed.items.length) return null;
      if (Date.now() - (parsed.at || 0) > CACHE_MS) return null;
      return parsed.items;
    } catch (_) {
      return null;
    }
  }

  function saveCached(list) {
    try {
      sessionStorage.setItem(CACHE, JSON.stringify({ at: Date.now(), items: list }));
    } catch (_) {}
  }

  function loadCatalog() {
    var cached = loadCached();
    if (cached) {
      catalog = cached;
      catalogReady = true;
      return Promise.resolve(catalog);
    }
    return fetch("/assets/wfm-items.json", { cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        var list = Array.isArray(d) ? d : d.items || [];
        catalog = list;
        catalogReady = true;
        saveCached(list);
        return list;
      })
      .catch(function () {
        var url = proxy("/api/wfm/items");
        if (!url) return [];
        return fetch(url, { mode: "cors", credentials: "omit" })
          .then(function (r) {
            if (!r.ok) throw new Error("HTTP " + r.status);
            return r.json();
          })
          .then(function (d) {
            catalog = (d && d.items) || [];
            catalogReady = true;
            saveCached(catalog);
            return catalog;
          })
          .catch(function () {
            return [];
          });
      });
  }

  function scoreItem(it, q) {
    var name = String(it.name || "").toLowerCase();
    var slug = String(it.slug || "").toLowerCase();
    if (!q) return 0;
    if (slug === q || name === q) return 100;
    if (name.startsWith(q) || slug.startsWith(q)) return 80;
    if (name.indexOf(q) >= 0 || slug.indexOf(q) >= 0) return 50;
    var parts = q.split(/\s+/).filter(Boolean);
    if (parts.length > 1 && parts.every(function (p) { return name.indexOf(p) >= 0; })) return 40;
    return 0;
  }

  function isPrimePart(it) {
    if (!it) return false;
    if (it.ducats != null && Number(it.ducats) > 0) return true;
    var tags = it.tags || [];
    var name = String(it.name || "").toLowerCase();
    if (/prime/i.test(name) && (tags.indexOf("component") >= 0 || tags.indexOf("set") >= 0 || /blueprint|chassis|neuro|systems|barrel|receiver|stock|blade|grip|string|hilt|link|gauntlet|chain|pouch|handle|ornament|boot|head|limb/i.test(name))) {
      return true;
    }
    return tags.indexOf("prime") >= 0 && tags.indexOf("component") >= 0;
  }

  function searchCatalog(q, limit) {
    q = String(q || "").trim().toLowerCase().replace(/\s+/g, " ");
    if (!q || q.length < 2) return [];
    var slugQ = q.replace(/\s+/g, "_");
    var scored = [];
    for (var i = 0; i < catalog.length; i++) {
      var it = catalog[i];
      if (!isPrimePart(it) && !/prime/i.test(it.name || "")) continue;
      var s = Math.max(scoreItem(it, q), scoreItem(it, slugQ));
      if (s > 0) scored.push({ s: s, it: it });
    }
    scored.sort(function (a, b) {
      if (b.s !== a.s) return b.s - a.s;
      var da = Number(a.it.ducats) || 0;
      var db = Number(b.it.ducats) || 0;
      if (db !== da) return db - da;
      return String(a.it.name || "").length - String(b.it.name || "").length;
    });
    return scored.slice(0, limit || 12).map(function (row) { return row.it; });
  }

  function hideSuggest() {
    if (!suggestEl || !qEl) return;
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
  }

  function renderSuggest(list) {
    if (!suggestEl) return;
    if (!list.length) {
      hideSuggest();
      return;
    }
    suggestEl.innerHTML = list
      .map(function (it) {
        return (
          '<li role="option" data-slug="' +
          esc(it.slug) +
          '"><span>' +
          esc(it.name) +
          "</span>" +
          (it.ducats != null
            ? '<span class="mk-tag">' + esc(it.ducats) + " ducats</span>"
            : "") +
          "</li>"
        );
      })
      .join("");
    suggestEl.hidden = false;
  }

  function verdictFor(plat, ducats) {
    if (plat == null || !isFinite(plat)) return { label: "Check the market", detail: "Live sell price unavailable." };
    if (!ducats || ducats <= 0) return { label: "Sell for platinum", detail: "No ducat value on this item." };
    // Rough community heuristic: melt when plat is very low vs ducats (~<0.1p per ducat).
    if (plat < ducats / 10) {
      return {
        label: "Melt for ducats",
        detail: plat.toFixed(0) + "p for " + ducats + " ducats is a weak trade — Maroo may be better.",
      };
    }
    return {
      label: "Sell for platinum",
      detail: plat.toFixed(0) + "p beats melting " + ducats + " ducats at current lowest sell.",
    };
  }

  function render(item, plat, meta) {
    meta = meta || {};
    var ducats = Number(item.ducats != null ? item.ducats : meta.ducats) || 0;
    var has = plat != null && isFinite(Number(plat));
    var p = has ? Number(plat) : null;
    var v = verdictFor(p, ducats);
    var slug = item.slug || "";
    var name = item.name || slug.replace(/_/g, " ");

    root.innerHTML =
      '<article class="tool-card">' +
      "<h2>" +
      esc(name) +
      "</h2>" +
      '<div class="tool-grid-2">' +
      "<div><p class=\"tool-meta\">Ducat value</p><h3>" +
      (ducats > 0 ? esc(ducats) + " ducats" : "—") +
      "</h3></div>" +
      "<div><p class=\"tool-meta\">Lowest sell</p><h3>" +
      (has ? esc(p) + " platinum" : "Unavailable") +
      "</h3></div>" +
      "</div>" +
      '<p class="tool-prose"><strong>' +
      esc(v.label) +
      "</strong> — " +
      esc(v.detail) +
      (meta.onlineSell != null
        ? " · " + esc(meta.onlineSell) + " online sells"
        : "") +
      "</p>" +
      '<div class="tool-actions">' +
      '<a class="btn-primary" href="/market.html?q=' +
      encodeURIComponent(name) +
      '">Market orders</a>' +
      '<a class="btn-secondary" href="/farm.html?q=' +
      encodeURIComponent(name) +
      '">Farm</a>' +
      '<a class="btn-secondary" href="/relics.html?q=' +
      encodeURIComponent(name) +
      '">Relics</a>' +
      '<a class="btn-secondary" href="/planner.html?want=' +
      encodeURIComponent(name) +
      '">Planner</a>' +
      '<a class="btn-secondary" target="_blank" rel="noopener noreferrer" href="https://warframe.market/items/' +
      encodeURIComponent(slug) +
      '">warframe.market</a>' +
      "</div></article>";

    setStatus(has ? "Comparison ready" : "Item loaded · live prices unavailable", !has);
    root.setAttribute("aria-busy", "false");
    try {
      var u = new URL(location.href);
      u.searchParams.set("q", name);
      history.replaceState(null, "", u.pathname + u.search);
    } catch (_) {}
  }

  function pickBySlug(slug) {
    slug = String(slug || "").trim().toLowerCase().replace(/\s+/g, "_");
    if (!slug) return;
    hideSuggest();
    root.setAttribute("aria-busy", "true");
    setStatus("Loading market orders…");

    var cat = null;
    for (var i = 0; i < catalog.length; i++) {
      if (String(catalog[i].slug || "").toLowerCase() === slug) {
        cat = catalog[i];
        break;
      }
    }

    var url = proxy("/api/wfm/items/" + encodeURIComponent(slug) + "?platform=pc");
    if (!url) {
      render(cat || { slug: slug, name: slug.replace(/_/g, " ") }, null, {});
      setStatus("Market proxy not configured", true);
      return;
    }

    fetch(url, { mode: "cors", credentials: "omit", cache: "no-store" })
      .then(function (r) {
        if (r.status === 404) throw new Error("Item not found");
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        var item = Object.assign({}, cat || {}, d.item || {});
        if (!item.slug) item.slug = slug;
        var sum = d.summary || {};
        var plat = sum.lowestSell;
        if (plat == null && d.sellOrders && d.sellOrders.length) {
          plat = d.sellOrders[0].platinum;
        }
        render(item, plat, {
          ducats: item.ducats,
          onlineSell: sum.onlineSell,
        });
      })
      .catch(function (err) {
        if (cat) {
          render(cat, null, { ducats: cat.ducats });
          setStatus((err && err.message) || "Live prices unavailable", true);
        } else {
          root.innerHTML =
            '<div class="tool-card"><p class="tool-prose">Could not load that item. Try another Prime part name.</p></div>';
          setStatus(err && err.message ? err.message : "Lookup failed", true);
          root.setAttribute("aria-busy", "false");
        }
      });
  }

  function search(q) {
    q = String(q || "").trim();
    if (!q) return;
    if (!catalogReady) {
      setStatus("Loading catalog…");
      loadCatalog().then(function () {
        search(q);
      });
      return;
    }
    hideSuggest();
    results = searchCatalog(q, 12);
    if (!results.length) {
      // Fallback: treat query as slug
      var slugGuess = q.toLowerCase().replace(/\s+/g, "_");
      setStatus("No catalog match — trying market slug…");
      pickBySlug(slugGuess);
      return;
    }
    if (
      results.length === 1 ||
      String(results[0].name || "").toLowerCase() === q.toLowerCase() ||
      String(results[0].slug || "").toLowerCase() === q.toLowerCase().replace(/\s+/g, "_")
    ) {
      pickBySlug(results[0].slug);
      return;
    }
    root.innerHTML =
      '<section class="tool-card"><h2>Select an item</h2><div class="tool-pills">' +
      results
        .map(function (x) {
          return (
            '<button type="button" class="tool-pill" data-slug="' +
            esc(x.slug) +
            '">' +
            esc(x.name) +
            (x.ducats != null ? " · " + esc(x.ducats) + "d" : "") +
            "</button>"
          );
        })
        .join("") +
      "</div></section>";
    root.setAttribute("aria-busy", "false");
    setStatus(results.length + " matching items");
  }

  if (root) {
    root.addEventListener("click", function (e) {
      var b = e.target.closest("[data-slug]");
      if (b) pickBySlug(b.getAttribute("data-slug"));
    });
  }

  if (suggestEl) {
    suggestEl.addEventListener("click", function (e) {
      var li = e.target.closest("[data-slug]");
      if (!li) return;
      if (qEl) qEl.value = li.querySelector("span") ? li.querySelector("span").textContent : li.getAttribute("data-slug");
      pickBySlug(li.getAttribute("data-slug"));
    });
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      search(qEl && qEl.value);
    });
  }

  if (qEl) {
    qEl.addEventListener("input", function () {
      clearTimeout(suggestTimer);
      suggestTimer = setTimeout(function () {
        if (!catalogReady) return;
        renderSuggest(searchCatalog(qEl.value, 8));
      }, 120);
    });
    qEl.addEventListener("keydown", function (e) {
      if (e.key === "Escape") hideSuggest();
    });
  }

  document.addEventListener("click", function (e) {
    if (!suggestEl || suggestEl.hidden) return;
    if (e.target === qEl || suggestEl.contains(e.target)) return;
    hideSuggest();
  });

  loadCatalog().then(function () {
    setStatus(catalog.length ? "Enter a Prime item" : "Catalog unavailable — try a market slug", !catalog.length);
    var q = new URLSearchParams(location.search).get("q");
    if (q && qEl) {
      qEl.value = q;
      search(q);
    }
  });
})();
