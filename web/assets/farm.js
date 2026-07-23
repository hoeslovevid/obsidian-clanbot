/**
 * Acquire / farm lookup — drops + items from api.warframestat.us
 */
(function () {
  var API = "https://api.warframestat.us";
  var CDN = "https://cdn.warframestat.us/img/";
  var JUNK_RE = /conclave|annihilation|lunaro|cephalon capture|variant\s+(cephalon|team|annihilation)/i;
  var RELIC_RE = /\b(Lith|Meso|Neo|Axi|Requiem|Omnia)\s+[A-Z0-9]+\b/i;
  var REFINE_RE = /\s*\((Intact|Exceptional|Flawless|Radiant)\)\s*$/i;

  var form = document.getElementById("fm-form");
  var queryEl = document.getElementById("fm-query");
  var suggestEl = document.getElementById("fm-suggest");
  var root = document.getElementById("fm-root");
  var statusEl = document.getElementById("fm-status");
  var hideJunkEl = document.getElementById("fm-hide-junk");
  var suggestTimer = null;
  var activeItem = null;
  var lastBundle = null;
  var suggestItems = [];
  var suggestIndex = -1;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setStatus(ok, text) {
    if (!statusEl) return;
    statusEl.className = "fm-status " + (ok ? "ok" : "err");
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

  function imgUrl(name) {
    if (!name) return "";
    return CDN + encodeURIComponent(name);
  }

  function marketUrl(name) {
    return "/market.html?q=" + encodeURIComponent(name || "");
  }

  function voidUrl(tiers) {
    var t = (tiers || []).filter(Boolean);
    var q = "section=void";
    if (t.length) q += "&tiers=" + encodeURIComponent(t.join(","));
    return "/warframe.html?" + q;
  }

  function isJunk(place) {
    return JUNK_RE.test(place || "");
  }

  function normalizeRelic(place) {
    var p = String(place || "").replace(REFINE_RE, "").trim();
    var m = p.match(RELIC_RE);
    return m ? m[0].replace(/\s+/g, " ") : null;
  }

  function relicTierFromPlaces(places) {
    var tiers = {};
    places.forEach(function (p) {
      var r = normalizeRelic(p);
      if (!r) return;
      var m = r.match(/^(Lith|Meso|Neo|Axi|Requiem|Omnia)/i);
      if (m) tiers[m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase()] = 1;
    });
    return Object.keys(tiers);
  }

  function sourceKind(place) {
    var p = String(place || "");
    if (/relic/i.test(p) || RELIC_RE.test(p)) return "relic";
    if (/bounty|cetus|vallis|cambion|zariman|holdfast|hex|entrati|cavia|kahl/i.test(p)) return "bounty";
    if (/caches|rot\s*[abc]|survival|defense|exterminate|spy|sabotage|rescue|interception|disruption|excavation|alchemy|void flood|assassination|mobile defense/i.test(p))
      return "mission";
    if (/vault|derelict/i.test(p)) return "vault";
    if (/\//.test(p)) return "mission";
    return "enemy";
  }

  function kindWeight(kind) {
    return { relic: 1.15, mission: 1.1, bounty: 1.05, vault: 1.0, enemy: 0.95 }[kind] || 1;
  }

  function normalizeDrop(d) {
    var place = d.place || d.location || "";
    var item = d.item || d.type || "";
    var chance = Number(d.chance);
    if (isNaN(chance)) chance = 0;
    var rarity = d.rarity || "";
    var kind = sourceKind(place);
    var relic = normalizeRelic(place);
    var refine = (String(place).match(REFINE_RE) || [])[1] || "";
    return {
      place: place,
      item: item,
      chance: chance,
      rarity: rarity,
      kind: kind,
      relic: relic,
      refine: refine,
      junk: isJunk(place),
      score: chance * kindWeight(kind) * (isJunk(place) ? 0.05 : 1),
    };
  }

  function mergeDrops(lists) {
    var map = {};
    lists.forEach(function (list) {
      (list || []).forEach(function (raw) {
        var d = normalizeDrop(raw);
        if (!d.place) return;
        var key = d.relic
          ? "relic:" + d.relic.toLowerCase() + "|" + (d.refine || "base")
          : d.kind + "|" + d.place.toLowerCase() + "|" + d.item.toLowerCase();
        var prev = map[key];
        if (!prev || d.chance > prev.chance) map[key] = d;
      });
    });
    return Object.keys(map).map(function (k) {
      return map[k];
    });
  }

  function rankDrops(drops, hideJunk) {
    return drops
      .filter(function (d) {
        return hideJunk ? !d.junk : true;
      })
      .slice()
      .sort(function (a, b) {
        return b.score - a.score || b.chance - a.chance;
      });
  }

  function bestRelics(drops) {
    var byRelic = {};
    drops.forEach(function (d) {
      if (!d.relic) return;
      var key = d.relic.toLowerCase();
      var cur = byRelic[key];
      if (!cur || d.chance > cur.chance) {
        byRelic[key] = {
          relic: d.relic,
          chance: d.chance,
          rarity: d.rarity,
          refine: d.refine || "Intact",
          item: d.item,
        };
      }
    });
    return Object.keys(byRelic)
      .map(function (k) {
        return byRelic[k];
      })
      .sort(function (a, b) {
        return b.chance - a.chance;
      });
  }

  function pickBestItem(results, query) {
    if (!results || !results.length) return null;
    var q = String(query || "").trim().toLowerCase();
    var preferred = ["Warframe", "Primary", "Secondary", "Melee", "Archwing", "Arch-Gun", "Archmelee", "Warframe Mod", "Shotgun Mod", "Rifle Mod", "Pistol Mod", "Melee Mod", "Resource", "Misc", "Relic"];
    var exact = null;
    results.forEach(function (it) {
      if (String(it.name || "").toLowerCase() === q) exact = it;
    });
    if (exact) return exact;
    var scored = results
      .map(function (it) {
        var name = String(it.name || "").toLowerCase();
        var type = it.type || "";
        var cat = it.category || "";
        var score = 0;
        if (name === q) score += 100;
        if (name.indexOf(q) === 0) score += 40;
        if (name.indexOf(q) >= 0) score += 20;
        var pi = preferred.indexOf(type);
        if (pi >= 0) score += 30 - pi;
        if (cat === "Warframes" || cat === "Mods" || cat === "Misc" || cat === "Relics") score += 10;
        if (/noggle|glyph|sigil|skin|sugatra|syandana|ephemera/i.test(type + " " + cat + " " + name)) score -= 50;
        return { it: it, score: score };
      })
      .sort(function (a, b) {
        return b.score - a.score;
      });
    return scored[0] ? scored[0].it : results[0];
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

  function hideSuggest() {
    if (!suggestEl) return;
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
    if (queryEl) queryEl.setAttribute("aria-expanded", "false");
    suggestIndex = -1;
  }

  function showSuggest(items) {
    suggestItems = items || [];
    suggestIndex = -1;
    if (!suggestEl || !suggestItems.length) {
      hideSuggest();
      return;
    }
    suggestEl.innerHTML = suggestItems
      .map(function (it, i) {
        return (
          '<li role="option" id="fm-opt-' +
          i +
          '" data-idx="' +
          i +
          '"><strong>' +
          esc(it.name) +
          "</strong><span>" +
          esc(it.type || it.category || "") +
          "</span></li>"
        );
      })
      .join("");
    suggestEl.hidden = false;
    if (queryEl) queryEl.setAttribute("aria-expanded", "true");
  }

  function searchSuggest(q) {
    if (!q || q.length < 2) {
      hideSuggest();
      return;
    }
    fetchJson("/items/search/" + encodeURIComponent(q))
      .then(function (list) {
        if ((queryEl.value || "").trim() !== q) return;
        var filtered = (list || [])
          .filter(function (it) {
            return !/noggle|glyph|sigil/i.test(it.type || "");
          })
          .slice(0, 8);
        showSuggest(filtered);
      })
      .catch(function () {
        hideSuggest();
      });
  }

  function fetchLiveFissures(tiers) {
    if (!tiers || !tiers.length) return Promise.resolve([]);
    return fetchJson("/pc/fissures")
      .then(function (list) {
        var set = {};
        tiers.forEach(function (t) {
          set[t.toLowerCase()] = 1;
        });
        return (list || [])
          .filter(function (f) {
            if (f.expired) return false;
            var tier = String(f.tier || "").toLowerCase();
            return Object.keys(set).some(function (t) {
              return tier.indexOf(t) >= 0;
            });
          })
          .slice(0, 12);
      })
      .catch(function () {
        return [];
      });
  }

  function loadItem(name) {
    setStatus(true, "Looking up “" + name + "”…");
    if (root) root.setAttribute("aria-busy", "true");
    hideSuggest();

    var itemP = fetchJson("/items/" + encodeURIComponent(name)).catch(function () {
      return fetchJson("/items/search/" + encodeURIComponent(name)).then(function (list) {
        return pickBestItem(list, name);
      });
    });

    var dropsP = fetchJson("/drops/search/" + encodeURIComponent(name)).catch(function () {
      return [];
    });

    return Promise.all([itemP, dropsP])
      .then(function (pair) {
        var item = pair[0];
        if (Array.isArray(item)) item = pickBestItem(item, name);
        if (!item || !item.name) throw new Error("not found");
        activeItem = item;

        var dropLists = [pair[1] || [], item.drops || [], componentDrops(item)];
        // Also search drops for each craftable component name (primes)
        var compNames = (item.components || [])
          .map(function (c) {
            return c.name;
          })
          .filter(function (n) {
            return n && !/orokin cell|neurodes|morphics|gallium|neural sensors|control module|alloy plate|salvage|ferrite|nano spores|polymer bundle|plastids|rubedo|cryotic|oxium|argon crystal/i.test(n);
          })
          .slice(0, 6);

        var extra = Promise.all(
          compNames.map(function (n) {
            var q = item.name + " " + n;
            return fetchJson("/drops/search/" + encodeURIComponent(q)).catch(function () {
              return [];
            });
          })
        );

        return extra.then(function (extraLists) {
          extraLists.forEach(function (l) {
            dropLists.push(l);
          });
          var merged = mergeDrops(dropLists);
          var hideJunk = hideJunkEl ? hideJunkEl.checked : true;
          var ranked = rankDrops(merged, hideJunk);
          var relics = bestRelics(merged);
          var tiers = relicTierFromPlaces(ranked.map(function (d) {
            return d.place;
          }));
          return fetchLiveFissures(tiers).then(function (fissures) {
            lastBundle = {
              item: item,
              ranked: ranked,
              all: merged,
              relics: relics,
              tiers: tiers,
              fissures: fissures,
              query: name,
            };
            render(lastBundle);
            setStatus(true, ranked.length + " sources · " + item.name);
            syncUrl(item.name);
          });
        });
      })
      .catch(function () {
        setStatus(false, "No drop data found for that name. Try another spelling.");
        if (root) {
          root.innerHTML =
            '<div class="fm-empty-state"><p>Nothing matched <strong>' +
            esc(name) +
            "</strong>. Try a resource, mod, or prime set name.</p></div>";
          root.setAttribute("aria-busy", "false");
        }
      });
  }

  function syncUrl(name) {
    try {
      var url = new URL(window.location.href);
      url.searchParams.set("q", name);
      history.replaceState(null, "", url.pathname + url.search);
    } catch (e) {}
  }

  function rarityClass(r) {
    var x = String(r || "").toLowerCase();
    if (x.indexOf("legend") >= 0) return "r-legendary";
    if (x.indexOf("rare") >= 0) return "r-rare";
    if (x.indexOf("uncommon") >= 0) return "r-uncommon";
    if (x.indexOf("common") >= 0) return "r-common";
    return "";
  }

  function kindLabel(k) {
    return { relic: "Relic", mission: "Mission", bounty: "Bounty", vault: "Vault", enemy: "Enemy" }[k] || "Source";
  }

  function renderItemHeader(item) {
    var thumb = item.imageName ? '<img class="fm-thumb" src="' + esc(imgUrl(item.imageName)) + '" alt="" loading="lazy" />' : "";
    var html =
      '<section class="fm-card fm-item-card">' +
      thumb +
      '<div class="fm-item-body"><h2>' +
      esc(item.name) +
      "</h2>" +
      '<p class="fm-meta">' +
      esc(item.type || "") +
      (item.category ? " · " + esc(item.category) : "") +
      (item.rarity ? " · " + esc(item.rarity) : "") +
      "</p>";
    if (item.description) html += '<p class="fm-desc">' + esc(item.description) + "</p>";
    html +=
      '<div class="fm-actions">' +
      '<a class="btn-secondary" href="' +
      esc(marketUrl(item.name)) +
      '">Market prices</a>';
    if (item.wikiaUrl) {
      html +=
        '<a class="btn-secondary" href="' +
        esc(item.wikiaUrl) +
        '" target="_blank" rel="noopener noreferrer">Wiki</a>';
    }
    html += "</div></div></section>";
    return html;
  }

  function renderComponents(item) {
    var comps = item.components || [];
    if (!comps.length) return "";
    var html = '<section class="fm-card"><h3>Components / craft</h3><ul class="fm-comp-list">';
    comps.forEach(function (c) {
      var drops = c.drops || [];
      var relics = bestRelics(
        drops.map(function (d) {
          return normalizeDrop({ place: d.location, item: d.type || c.name, chance: d.chance, rarity: d.rarity });
        })
      );
      html +=
        "<li><strong>" +
        esc(c.name) +
        "</strong>" +
        (c.itemCount > 1 ? " ×" + esc(c.itemCount) : "") +
        (drops.length
          ? ' <span class="fm-meta">' + drops.length + " sources</span>"
          : ' <span class="fm-meta">no drop table (resource/vendor)</span>');
      if (relics.length) {
        html += '<div class="fm-mini-relics">';
        relics.slice(0, 4).forEach(function (r) {
          html +=
            '<span class="fm-pill">' +
            esc(r.relic) +
            " · " +
            esc(r.chance) +
            "%</span>";
        });
        if (relics.length > 4) html += '<span class="fm-meta">+' + (relics.length - 4) + " more</span>";
        html += "</div>";
      }
      html += "</li>";
    });
    return html + "</ul></section>";
  }

  function renderBest(ranked) {
    if (!ranked.length) {
      return '<section class="fm-card"><h3>Best sources</h3><p class="fm-empty">No drop sources found (may be vendor-only, event, or craft-only).</p></section>';
    }
    var top = ranked.slice(0, 12);
    var html =
      '<section class="fm-card"><h3>Best sources</h3><p class="fm-meta">Ranked by drop chance with mission/relic bias. Hide Conclave filters PvP junk.</p><ol class="fm-source-list">';
    top.forEach(function (d, i) {
      html +=
        '<li class="' +
        rarityClass(d.rarity) +
        '"><span class="fm-rank">' +
        (i + 1) +
        '</span><div><strong>' +
        esc(d.relic || d.place) +
        "</strong>" +
        (d.refine ? ' <span class="fm-meta">(' + esc(d.refine) + ")</span>" : "") +
        '<div class="fm-meta">' +
        esc(kindLabel(d.kind)) +
        (d.rarity ? " · " + esc(d.rarity) : "") +
        (d.item && d.item !== (activeItem && activeItem.name) ? " · " + esc(d.item) : "") +
        "</div></div>" +
        '<span class="fm-chance">' +
        (d.chance ? Number(d.chance).toFixed(d.chance >= 10 ? 1 : 2) + "%" : "—") +
        "</span></li>";
    });
    return html + "</ol></section>";
  }

  function renderRelics(relics, tiers, fissures) {
    if (!relics.length) return "";
    var html =
      '<section class="fm-card"><h3>Relics</h3><p class="fm-meta">Best listed chance per relic (often Radiant). Open Void fissures for matching tiers when available.</p>';
    html +=
      '<div class="fm-actions" style="margin-bottom:12px"><a class="btn-secondary" href="' +
      esc(voidUrl(tiers)) +
      '">Live ' +
      esc(tiers.join(" / ") || "Void") +
      " fissures</a></div>";
    html += '<ul class="fm-relic-list">';
    relics.slice(0, 16).forEach(function (r) {
      html +=
        "<li><strong>" +
        esc(r.relic) +
        "</strong> · " +
        esc(r.chance) +
        "%" +
        (r.rarity ? " · " + esc(r.rarity) : "") +
        (r.refine ? ' <span class="fm-meta">best as ' + esc(r.refine) + "</span>" : "") +
        "</li>";
    });
    html += "</ul>";
    if (fissures && fissures.length) {
      html += '<h4 class="fm-sub">Live fissures (matching tiers)</h4><div class="fm-fissure-row">';
      fissures.forEach(function (f) {
        html +=
          '<span class="fm-pill">' +
          esc(f.tier || "?") +
          " · " +
          esc(f.node || "?") +
          " · " +
          esc(f.missionType || "") +
          (f.isHard ? " · SP" : "") +
          "</span>";
      });
      html += "</div>";
    }
    return html + "</section>";
  }

  function renderAllSources(ranked) {
    if (ranked.length <= 12) return "";
    var rest = ranked.slice(12, 40);
    var html = '<section class="fm-card fm-more"><details><summary>More sources (' + rest.length + ")</summary><ul class=\"fm-source-plain\">";
    rest.forEach(function (d) {
      html +=
        "<li><strong>" +
        esc(d.place) +
        "</strong> · " +
        esc(d.chance) +
        "%" +
        (d.rarity ? " · " + esc(d.rarity) : "") +
        "</li>";
    });
    return html + "</ul></details></section>";
  }

  function render(bundle) {
    if (!root) return;
    var item = bundle.item;
    var html = "";
    html += renderItemHeader(item);
    html += '<div class="fm-grid-2">';
    html += renderBest(bundle.ranked);
    html += renderRelics(bundle.relics, bundle.tiers, bundle.fissures);
    html += "</div>";
    html += renderComponents(item);
    html += renderAllSources(bundle.ranked);
    root.innerHTML = html;
    root.setAttribute("aria-busy", "false");
  }

  function submitQuery(raw) {
    var q = String(raw || "").trim();
    if (!q) return;
    if (queryEl) queryEl.value = q;
    loadItem(q);
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (suggestIndex >= 0 && suggestItems[suggestIndex]) {
        submitQuery(suggestItems[suggestIndex].name);
        return;
      }
      submitQuery(queryEl && queryEl.value);
    });
  }

  if (queryEl) {
    queryEl.addEventListener("input", function () {
      var q = (queryEl.value || "").trim();
      clearTimeout(suggestTimer);
      suggestTimer = setTimeout(function () {
        searchSuggest(q);
      }, 220);
    });
    queryEl.addEventListener("keydown", function (e) {
      if (suggestEl && !suggestEl.hidden && suggestItems.length) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          suggestIndex = Math.min(suggestIndex + 1, suggestItems.length - 1);
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          suggestIndex = Math.max(suggestIndex - 1, 0);
        } else if (e.key === "Escape") {
          hideSuggest();
          return;
        } else {
          return;
        }
        Array.prototype.forEach.call(suggestEl.children, function (li, i) {
          li.setAttribute("aria-selected", i === suggestIndex ? "true" : "false");
          li.classList.toggle("on", i === suggestIndex);
        });
      }
    });
  }

  if (suggestEl) {
    suggestEl.addEventListener("mousedown", function (e) {
      var li = e.target.closest("li[data-idx]");
      if (!li) return;
      e.preventDefault();
      var idx = Number(li.getAttribute("data-idx"));
      if (suggestItems[idx]) submitQuery(suggestItems[idx].name);
    });
  }

  document.addEventListener("click", function (e) {
    if (!suggestEl || suggestEl.hidden) return;
    if (e.target === queryEl || suggestEl.contains(e.target)) return;
    hideSuggest();
  });

  document.querySelectorAll(".fm-chip[data-q]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      submitQuery(btn.getAttribute("data-q"));
    });
  });

  if (hideJunkEl) {
    hideJunkEl.addEventListener("change", function () {
      if (!lastBundle) return;
      lastBundle.ranked = rankDrops(lastBundle.all, hideJunkEl.checked);
      render(lastBundle);
      setStatus(true, lastBundle.ranked.length + " sources · " + lastBundle.item.name);
    });
  }

  try {
    var params = new URLSearchParams(window.location.search);
    var q = params.get("q") || params.get("item");
    if (q) submitQuery(q);
  } catch (e) {}
})();
