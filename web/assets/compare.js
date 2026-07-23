/**
 * Side-by-side item comparison — api.warframestat.us
 */
(function () {
  var API = "https://api.warframestat.us";

  var form = document.getElementById("cp-form");
  var inputA = document.getElementById("cp-a");
  var inputB = document.getElementById("cp-b");
  var root = document.getElementById("cp-root");
  var statusEl = document.getElementById("cp-status");

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

  function pickBestItem(results, query) {
    if (!results || !results.length) return null;
    var q = String(query || "").trim().toLowerCase();
    var exact = null;
    results.forEach(function (it) {
      if (String(it.name || "").toLowerCase() === q) exact = it;
    });
    if (exact) return exact;
    return results[0];
  }

  function normalizeDrop(d) {
    return {
      place: d.place || d.location || "",
      item: d.item || d.type || "",
      chance: Number(d.chance) || 0,
      rarity: d.rarity || "",
    };
  }

  function mergeDrops(lists) {
    var map = {};
    lists.forEach(function (list) {
      (list || []).forEach(function (raw) {
        var d = normalizeDrop(raw);
        if (!d.place) return;
        var key = d.place.toLowerCase() + "|" + d.item.toLowerCase();
        var prev = map[key];
        if (!prev || d.chance > prev.chance) map[key] = d;
      });
    });
    return Object.keys(map).map(function (k) {
      return map[k];
    });
  }

  function topDrops(drops, limit) {
    return drops
      .slice()
      .sort(function (a, b) {
        return b.chance - a.chance;
      })
      .slice(0, limit || 8);
  }

  function componentDrops(item) {
    var out = [];
    (item.components || []).forEach(function (c) {
      (c.drops || []).forEach(function (d) {
        out.push({
          place: d.location || d.place,
          item: d.type || c.name,
          chance: d.chance,
          rarity: d.rarity,
        });
      });
    });
    return out;
  }

  function loadSide(name) {
    var itemP = fetchJson("/items/" + encodeURIComponent(name)).catch(function () {
      return fetchJson("/items/search/" + encodeURIComponent(name)).then(function (list) {
        return pickBestItem(list, name);
      });
    });

    var dropsP = fetchJson("/drops/search/" + encodeURIComponent(name)).catch(function () {
      return [];
    });

    return Promise.all([itemP, dropsP]).then(function (pair) {
      var item = pair[0];
      if (Array.isArray(item)) item = pickBestItem(item, name);
      if (!item || !item.name) throw new Error("not found");
      var dropLists = [pair[1] || [], item.drops || [], componentDrops(item)];
      var merged = mergeDrops(dropLists);
      return { item: item, drops: topDrops(merged, 8), query: name };
    });
  }

  function farmUrl(name) {
    return "/farm.html?q=" + encodeURIComponent(name || "");
  }

  function marketUrl(name) {
    return "/market.html?q=" + encodeURIComponent(name || "");
  }

  function renderCard(side) {
    var item = side.item;
    var html = '<div class="tool-card cp-card">';
    html += "<h2>" + esc(item.name) + "</h2>";
    html +=
      '<p class="tool-meta">' +
      esc(item.type || "") +
      (item.category ? " · " + esc(item.category) : "") +
      (item.rarity ? " · " + esc(item.rarity) : "") +
      "</p>";
    if (item.description) {
      html += '<p class="tool-prose" style="font-size:0.9rem;margin-bottom:12px">' + esc(item.description) + "</p>";
    }

    html += "<h3>Top drop sources</h3>";
    if (!side.drops.length) {
      html += '<p class="tool-meta">No drop sources found.</p>';
    } else {
      html += '<ol class="tool-list cp-drops">';
      side.drops.forEach(function (d) {
        html +=
          "<li><strong>" +
          esc(d.place) +
          "</strong>" +
          (d.chance ? " · " + esc(d.chance) + "%" : "") +
          (d.rarity ? " · " + esc(d.rarity) : "") +
          "</li>";
      });
      html += "</ol>";
    }

    var comps = item.components || [];
    if (comps.length) {
      html += "<h3>Components</h3><ul class=\"tool-list\">";
      comps.forEach(function (c) {
        html +=
          "<li><strong>" +
          esc(c.name) +
          "</strong>" +
          (c.itemCount > 1 ? " ×" + esc(c.itemCount) : "") +
          "</li>";
      });
      html += "</ul>";
    }

    html += '<div class="tool-actions">';
    html += '<a class="btn-secondary" href="' + esc(farmUrl(item.name)) + '">Farm</a>';
    html += '<a class="btn-secondary" href="' + esc(marketUrl(item.name)) + '">Market</a>';
    html += "</div></div>";
    return html;
  }

  function render(aSide, bSide) {
    if (!root) return;
    root.innerHTML = renderCard(aSide) + renderCard(bSide);
    root.setAttribute("aria-busy", "false");
  }

  function syncUrl(a, b) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("a", a);
      url.searchParams.set("b", b);
      history.replaceState(null, "", url.pathname + url.search);
    } catch (e) {}
  }

  function compare() {
    var a = inputA ? (inputA.value || "").trim() : "";
    var b = inputB ? (inputB.value || "").trim() : "";
    if (!a || !b) {
      setStatus(false, "Enter both item names.");
      return;
    }
    if (a.toLowerCase() === b.toLowerCase()) {
      setStatus(false, "Choose two different items.");
      return;
    }

    setStatus(true, "Comparing “" + a + "” vs “" + b + "”…");
    if (root) {
      root.setAttribute("aria-busy", "true");
      root.innerHTML = "";
    }

    Promise.all([loadSide(a), loadSide(b)])
      .then(function (pair) {
        render(pair[0], pair[1]);
        setStatus(true, pair[0].item.name + " vs " + pair[1].item.name);
        syncUrl(a, b);
      })
      .catch(function () {
        setStatus(false, "Could not load one or both items. Check spelling.");
        if (root) {
          root.innerHTML =
            '<div class="tool-card"><p class="tool-prose">Comparison failed — try full item names (e.g. <em>Soma Prime</em>).</p></div>';
          root.setAttribute("aria-busy", "false");
        }
      });
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      compare();
    });
  }

  try {
    var params = new URLSearchParams(window.location.search);
    var qa = params.get("a") || "";
    var qb = params.get("b") || "";
    if (inputA && qa) inputA.value = qa;
    if (inputB && qb) inputB.value = qb;
    if (qa && qb) compare();
  } catch (e) {}
})();
