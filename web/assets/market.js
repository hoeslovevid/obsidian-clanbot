/**
 * Public Warframe Market lookup — uses bot /api/wfm/* (CORS-safe proxy to WFM v2).
 */
(function () {
  var ITEMS_CACHE_KEY = "oo_wfm_items_v1";
  var ITEMS_CACHE_MS = 6 * 60 * 60 * 1000;
  var ASSET_FALLBACK = "/assets/logo.png";

  var form = document.getElementById("mk-form");
  var queryEl = document.getElementById("mk-query");
  var platformEl = document.getElementById("mk-platform");
  var suggestEl = document.getElementById("mk-suggest");
  var statusEl = document.getElementById("mk-status");
  var refreshBtn = document.getElementById("mk-refresh");
  var root = document.getElementById("mk-root");

  var items = [];
  var itemsReady = false;
  var activeSlug = null;
  var suggestIndex = -1;
  var debounceTimer = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function api(path) {
    if (!window.ObsidianSite || typeof window.ObsidianSite.apiUrl !== "function") return null;
    return window.ObsidianSite.apiUrl(path);
  }

  function setStatus(text, kind) {
    if (!statusEl) return;
    statusEl.className = "mk-status" + (kind ? " " + kind : "");
    statusEl.innerHTML = '<span class="dot" aria-hidden="true"></span>' + esc(text);
  }

  function plat(n) {
    if (n == null || n === "") return "—";
    return Number(n).toLocaleString("en-US") + " p";
  }

  function statusClass(st) {
    st = String(st || "offline").toLowerCase();
    if (st === "ingame" || st === "online" || st === "offline") return st;
    return "offline";
  }

  function loadCachedItems() {
    try {
      var raw = sessionStorage.getItem(ITEMS_CACHE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.items)) return null;
      if (Date.now() - (parsed.at || 0) > ITEMS_CACHE_MS) return null;
      return parsed.items;
    } catch (_) {
      return null;
    }
  }

  function saveCachedItems(list) {
    try {
      sessionStorage.setItem(
        ITEMS_CACHE_KEY,
        JSON.stringify({ at: Date.now(), items: list })
      );
    } catch (_) {}
  }

  function fetchItems() {
    var cached = loadCachedItems();
    if (cached && cached.length) {
      items = cached;
      itemsReady = true;
      setStatus(items.length.toLocaleString("en-US") + " items ready", "live");
      return Promise.resolve(items);
    }

    var url = api("/api/wfm/items");
    if (!url) {
      setStatus("Bot API URL not configured", "error");
      return Promise.reject(new Error("no api"));
    }

    setStatus("Loading item catalog…", "loading");
    return fetch(url, { mode: "cors", cache: "no-cache" })
      .then(function (res) {
        if (!res.ok) throw new Error("catalog " + res.status);
        return res.json();
      })
      .then(function (data) {
        items = (data && data.items) || [];
        itemsReady = true;
        saveCachedItems(items);
        setStatus(items.length.toLocaleString("en-US") + " items ready", "live");
        return items;
      })
      .catch(function (err) {
        setStatus("Could not load catalog — try again later", "error");
        throw err;
      });
  }

  function scoreItem(it, q) {
    var name = (it.name || "").toLowerCase();
    var slug = (it.slug || "").toLowerCase();
    if (!q) return 0;
    if (slug === q || name === q) return 100;
    if (name.startsWith(q) || slug.startsWith(q)) return 80;
    if (name.indexOf(q) >= 0 || slug.indexOf(q) >= 0) return 50;
    var parts = q.split(/\s+/).filter(Boolean);
    if (parts.length > 1 && parts.every(function (p) { return name.indexOf(p) >= 0; })) return 40;
    return 0;
  }

  function searchItems(q, limit) {
    q = String(q || "").trim().toLowerCase().replace(/\s+/g, " ");
    if (!q || q.length < 2) return [];
    var slugQ = q.replace(/\s+/g, "_");
    var scored = [];
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var s = Math.max(scoreItem(it, q), scoreItem(it, slugQ));
      if (s > 0) scored.push({ s: s, it: it });
    }
    scored.sort(function (a, b) {
      if (b.s !== a.s) return b.s - a.s;
      return (a.it.name || "").length - (b.it.name || "").length;
    });
    return scored.slice(0, limit || 10).map(function (row) { return row.it; });
  }

  function hideSuggest() {
    if (!suggestEl || !queryEl) return;
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
    queryEl.setAttribute("aria-expanded", "false");
    suggestIndex = -1;
  }

  function renderSuggest(list) {
    if (!suggestEl || !queryEl) return;
    if (!list.length) {
      hideSuggest();
      return;
    }
    suggestEl.innerHTML = list
      .map(function (it, i) {
        var tag = (it.tags && it.tags[0]) || "";
        return (
          '<li role="option" data-slug="' +
          esc(it.slug) +
          '" aria-selected="' +
          (i === suggestIndex ? "true" : "false") +
          '">' +
          (it.thumb
            ? '<img src="' + esc(it.thumb) + '" alt="" width="28" height="28" loading="lazy" />'
            : "") +
          "<span>" +
          esc(it.name) +
          "</span>" +
          (tag ? '<span class="mk-tag">' + esc(tag) + "</span>" : "") +
          "</li>"
        );
      })
      .join("");
    suggestEl.hidden = false;
    queryEl.setAttribute("aria-expanded", "true");
  }

  function updateSuggest() {
    if (!itemsReady) return;
    renderSuggest(searchItems(queryEl.value, 10));
  }

  function ordersTable(rows, emptyLabel) {
    if (!rows || !rows.length) {
      return '<p class="mk-empty-state" style="margin:12px;border:none">' + esc(emptyLabel) + "</p>";
    }
    var body = rows
      .map(function (o) {
        var u = o.user || {};
        var st = statusClass(u.status);
        return (
          "<tr>" +
          '<td class="mk-plat-cell">' +
          esc(plat(o.platinum)) +
          "</td>" +
          "<td>" +
          esc(o.quantity != null ? o.quantity : "—") +
          "</td>" +
          "<td>" +
          esc(u.ingameName || "?") +
          "</td>" +
          "<td><span class=\"mk-status-pill " +
          esc(st) +
          '">' +
          esc(st) +
          "</span></td>" +
          "</tr>"
        );
      })
      .join("");
    return (
      '<div class="mk-table-wrap"><table class="mk-table">' +
      "<thead><tr><th>Platinum</th><th>Qty</th><th>User</th><th>Status</th></tr></thead>" +
      "<tbody>" +
      body +
      "</tbody></table></div>"
    );
  }

  function renderItem(data) {
    var item = data.item || {};
    var sum = data.summary || {};
    var img = item.thumb || item.icon || ASSET_FALLBACK;
    var tags = (item.tags || [])
      .slice(0, 6)
      .map(function (t) {
        return '<span class="mk-chip">' + esc(t) + "</span>";
      })
      .join("");
    if (item.ducats != null) {
      tags += '<span class="mk-chip">' + esc(item.ducats) + " ducats</span>";
    }
    if (item.reqMasteryRank != null) {
      tags += '<span class="mk-chip">MR ' + esc(item.reqMasteryRank) + "</span>";
    }

    root.innerHTML =
      '<div class="mk-card">' +
      '<div class="mk-item">' +
      '<img class="mk-item-art" src="' +
      esc(img) +
      '" alt="" width="72" height="72" />' +
      '<div class="mk-item-body">' +
      "<h2>" +
      esc(item.name || activeSlug) +
      "</h2>" +
      '<div class="mk-meta">' +
      tags +
      "</div>" +
      '<div class="mk-actions">' +
      '<a class="btn-primary" href="' +
      esc(item.marketUrl || "https://warframe.market/items/" + (item.slug || "")) +
      '" target="_blank" rel="noopener noreferrer">Open on warframe.market</a>' +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="mk-stats">' +
      '<div class="mk-stat"><strong>Lowest sell</strong><div class="mk-plat">' +
      esc(plat(sum.lowestSell)) +
      "</div><span>" +
      esc(sum.onlineSell || 0) +
      " online / " +
      esc(sum.sellCount || 0) +
      " total</span></div>" +
      '<div class="mk-stat"><strong>Highest buy</strong><div class="mk-plat">' +
      esc(plat(sum.highestBuy)) +
      "</div><span>" +
      esc(sum.onlineBuy || 0) +
      " online / " +
      esc(sum.buyCount || 0) +
      " total</span></div>" +
      '<div class="mk-stat"><strong>Platform</strong><div class="mk-plat">' +
      esc((data.platform || "pc").toUpperCase()) +
      "</div><span>Live orders</span></div>" +
      "</div>" +
      '<div class="mk-orders">' +
      '<section class="mk-panel"><div class="mk-panel-head"><h3>Sell orders</h3><span>Cheapest first · online preferred</span></div>' +
      ordersTable(data.sellOrders, "No sell orders") +
      "</section>" +
      '<section class="mk-panel"><div class="mk-panel-head"><h3>Buy orders</h3><span>Highest first · online preferred</span></div>' +
      ordersTable(data.buyOrders, "No buy orders") +
      "</section>" +
      "</div>" +
      "</div>";
  }

  function lookup(slug, platform) {
    slug = String(slug || "").trim().toLowerCase().replace(/\s+/g, "_");
    if (!slug) {
      setStatus("Enter an item name", "error");
      return;
    }
    platform = platform || (platformEl && platformEl.value) || "pc";
    var url = api("/api/wfm/items/" + encodeURIComponent(slug) + "?platform=" + encodeURIComponent(platform));
    if (!url) {
      setStatus("Bot API URL not configured", "error");
      return;
    }

    activeSlug = slug;
    if (refreshBtn) refreshBtn.hidden = false;
    root.setAttribute("aria-busy", "true");
    setStatus("Fetching orders…", "loading");
    hideSuggest();

    fetch(url, { mode: "cors", cache: "no-cache" })
      .then(function (res) {
        if (res.status === 404) throw new Error("Item not found");
        if (!res.ok) throw new Error("lookup " + res.status);
        return res.json();
      })
      .then(function (data) {
        renderItem(data);
        setStatus("Live · " + ((data.item && data.item.name) || slug), "live");
        root.setAttribute("aria-busy", "false");
        try {
          var params = new URLSearchParams();
          params.set("item", slug);
          if (platform && platform !== "pc") params.set("platform", platform);
          history.replaceState(null, "", "?" + params.toString());
        } catch (_) {}
      })
      .catch(function (err) {
        root.setAttribute("aria-busy", "false");
        root.innerHTML =
          '<div class="mk-empty-state"><p>' +
          esc(err && err.message ? err.message : "Lookup failed") +
          ". Try another name or open warframe.market directly.</p></div>";
        setStatus("Lookup failed", "error");
      });
  }

  function resolveQueryToSlug(q) {
    q = String(q || "").trim();
    if (!q) return null;
    var matches = searchItems(q, 1);
    if (matches.length) return matches[0].slug;
    return q.toLowerCase().replace(/\s+/g, "_");
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var slug = resolveQueryToSlug(queryEl && queryEl.value);
      lookup(slug, platformEl && platformEl.value);
    });
  }

  if (queryEl) {
    queryEl.addEventListener("input", function () {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(updateSuggest, 120);
    });
    queryEl.addEventListener("keydown", function (e) {
      if (suggestEl.hidden) return;
      var opts = suggestEl.querySelectorAll("li");
      if (!opts.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        suggestIndex = Math.min(suggestIndex + 1, opts.length - 1);
        renderSuggest(searchItems(queryEl.value, 10));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        suggestIndex = Math.max(suggestIndex - 1, 0);
        renderSuggest(searchItems(queryEl.value, 10));
      } else if (e.key === "Enter" && suggestIndex >= 0) {
        e.preventDefault();
        var pick = opts[suggestIndex];
        if (pick) {
          queryEl.value = pick.querySelector("span") ? pick.querySelector("span").textContent : queryEl.value;
          lookup(pick.getAttribute("data-slug"), platformEl && platformEl.value);
        }
      } else if (e.key === "Escape") {
        hideSuggest();
      }
    });
  }

  if (suggestEl) {
    suggestEl.addEventListener("mousedown", function (e) {
      var li = e.target.closest("li[data-slug]");
      if (!li) return;
      e.preventDefault();
      var nameEl = li.querySelector("span");
      if (queryEl && nameEl) queryEl.value = nameEl.textContent;
      lookup(li.getAttribute("data-slug"), platformEl && platformEl.value);
    });
  }

  document.addEventListener("click", function (e) {
    if (!suggestEl || suggestEl.hidden) return;
    if (form && form.contains(e.target)) return;
    hideSuggest();
  });

  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () {
      if (activeSlug) lookup(activeSlug, platformEl && platformEl.value);
    });
  }

  if (platformEl) {
    platformEl.addEventListener("change", function () {
      if (activeSlug) lookup(activeSlug, platformEl.value);
    });
  }

  // Boot: load catalog, then deep-link ?item=
  fetchItems()
    .then(function () {
      try {
        var params = new URLSearchParams(window.location.search);
        var item = params.get("item") || params.get("q");
        var platform = params.get("platform");
        if (platform && platformEl) platformEl.value = platform;
        if (item) {
          if (queryEl) queryEl.value = item.replace(/_/g, " ");
          lookup(item, platformEl && platformEl.value);
        }
      } catch (_) {}
    })
    .catch(function () {});
})();
