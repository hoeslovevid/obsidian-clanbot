/**
 * Riven grader — disposition ranges, roll quality, weekly trade averages.
 * Formula: value ≈ base × ω × configWeight × roll(0.9–1.1), scaled by rank.
 * Base tables: Warframe Wiki (community). Heuristic only.
 */
(function () {
  var API = "https://api.warframestat.us";
  var WEEKLY_URL = "https://www-static.warframe.com/repos/weeklyRivensPC.json";

  // Base values at max rank (rank 8) before disposition & config weight. Units: percent unless noted.
  // Classes: rifle, shotgun, pistol, archgun, melee
  var STATS = [
    { id: "ammo", label: "Ammo Maximum", unit: "%", bases: { rifle: 49.95, shotgun: 90, pistol: 90, archgun: 99.9 }, positiveOnly: false },
    { id: "cold", label: "Cold Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "heat", label: "Heat Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "elec", label: "Electricity Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "toxin", label: "Toxin Damage", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 119.7, melee: 90 }, positiveOnly: true },
    { id: "damage", label: "Damage", unit: "%", bases: { rifle: 165, shotgun: 164.7, pistol: 219.6, archgun: 99.9, melee: 164.7 }, positiveOnly: true },
    { id: "cc", label: "Critical Chance", unit: "%", bases: { rifle: 149.99, shotgun: 90, pistol: 149.99, archgun: 99.9, melee: 180 }, positiveOnly: false },
    { id: "cd", label: "Critical Damage", unit: "%", bases: { rifle: 120, shotgun: 90, pistol: 90, archgun: 80.1, melee: 90 }, positiveOnly: false },
    { id: "ms", label: "Multishot", unit: "%", bases: { rifle: 90, shotgun: 119.7, pistol: 119.7, archgun: 60.3 }, positiveOnly: false },
    { id: "sc", label: "Status Chance", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 60.3, melee: 90 }, positiveOnly: false },
    { id: "sd", label: "Status Duration", unit: "%", bases: { rifle: 99.99, shotgun: 99.99, pistol: 99.99, archgun: 99.99, melee: 99.99 }, positiveOnly: false },
    { id: "fr", label: "Fire Rate / Attack Speed", unit: "%", bases: { rifle: 60.03, shotgun: 90, pistol: 74.7, archgun: 60.03, melee: 54.9 }, positiveOnly: false, bowNote: true },
    { id: "reload", label: "Reload Speed", unit: "%", bases: { rifle: 50, shotgun: 50, pistol: 50, archgun: 99.9 }, positiveOnly: false },
    { id: "mag", label: "Magazine Capacity", unit: "%", bases: { rifle: 50, shotgun: 50, pistol: 50, archgun: 60.3 }, positiveOnly: false },
    { id: "projectile", label: "Projectile Speed", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90 }, positiveOnly: false },
    { id: "punch", label: "Punch Through", unit: "m", bases: { rifle: 2.7, shotgun: 2.7, pistol: 2.7, archgun: 2.7 }, positiveOnly: true },
    { id: "impact", label: "Impact Damage", unit: "%", bases: { rifle: 119.97, shotgun: 119.97, pistol: 119.97, archgun: 90, melee: 119.7 }, positiveOnly: false },
    { id: "puncture", label: "Puncture Damage", unit: "%", bases: { rifle: 119.97, shotgun: 119.97, pistol: 119.97, archgun: 90, melee: 119.7 }, positiveOnly: false },
    { id: "slash", label: "Slash Damage", unit: "%", bases: { rifle: 119.97, shotgun: 119.97, pistol: 119.97, archgun: 90, melee: 119.7 }, positiveOnly: false },
    { id: "recoil", label: "Weapon Recoil", unit: "%", bases: { rifle: 90, shotgun: 90, pistol: 90, archgun: 90 }, positiveOnly: false, goodNeg: true },
    { id: "zoom", label: "Zoom", unit: "%", bases: { rifle: 59.99, pistol: 80.1, archgun: 59.99 }, positiveOnly: false, goodNeg: true },
    { id: "d_corpus", label: "Damage vs Corpus", unit: "x", bases: { rifle: 0.45, shotgun: 0.45, pistol: 0.45, archgun: 0.45, melee: 0.45 }, positiveOnly: false, multiplier: true },
    { id: "d_grineer", label: "Damage vs Grineer", unit: "x", bases: { rifle: 0.45, shotgun: 0.45, pistol: 0.45, archgun: 0.45, melee: 0.45 }, positiveOnly: false, multiplier: true },
    { id: "d_infested", label: "Damage vs Infested", unit: "x", bases: { rifle: 0.45, shotgun: 0.45, pistol: 0.45, archgun: 0.45, melee: 0.45 }, positiveOnly: false, multiplier: true },
    { id: "range", label: "Range", unit: "m", bases: { melee: 1.94 }, positiveOnly: false },
    { id: "combo_dur", label: "Combo Duration", unit: "s", bases: { melee: 8.1 }, positiveOnly: false },
    { id: "initial_combo", label: "Initial Combo", unit: "", bases: { melee: 24.5 }, positiveOnly: false },
    { id: "finisher", label: "Finisher Damage", unit: "%", bases: { melee: 119.7 }, positiveOnly: false },
    { id: "slide_cc", label: "Slide Crit Chance", unit: "%", bases: { melee: 120 }, positiveOnly: false },
    { id: "heavy_eff", label: "Heavy Attack Efficiency", unit: "%", bases: { melee: 73.44 }, positiveOnly: false },
    { id: "combo_chance", label: "Combo Count Chance", unit: "%", bases: { melee: 58.77 }, positiveOnly: false },
  ];

  var WEIGHTS = {
    "2-0": { bonus: 0.99, malus: 0 },
    "2-1": { bonus: 1.2375, malus: -0.495 },
    "3-0": { bonus: 0.75, malus: 0 },
    "3-1": { bonus: 0.9375, malus: -0.75 },
  };

  var form = document.getElementById("rg-form");
  var weaponEl = document.getElementById("rg-weapon");
  var suggestEl = document.getElementById("rg-suggest");
  var metaEl = document.getElementById("rg-weapon-meta");
  var rankEl = document.getElementById("rg-rank");
  var posCountEl = document.getElementById("rg-pos-count");
  var hasNegEl = document.getElementById("rg-has-neg");
  var statsEl = document.getElementById("rg-stats");
  var statusEl = document.getElementById("rg-status");
  var resultEl = document.getElementById("rg-result");
  var clearBtn = document.getElementById("rg-clear");

  var weapons = [];
  var selected = null;
  var weekly = [];
  var suggestTimer = null;

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

  function omegaOf(w) {
    if (!w) return null;
    if (w.omegaAttenuation != null && !isNaN(w.omegaAttenuation)) return Number(w.omegaAttenuation);
    // Fallback map from 1–5 star disposition if ω missing
    var d = Number(w.disposition);
    if (!d || isNaN(d)) return null;
    var map = { 1: 0.5, 2: 0.7, 3: 0.9, 4: 1.1, 5: 1.3 };
    return map[Math.round(d)] || 1;
  }

  function rivenClass(w) {
    var t = String((w && (w.type || w.category || w.productCategory)) || "").toLowerCase();
    var n = String((w && w.name) || "").toLowerCase();
    if (/arch[- ]?gun|archgun|archwing gun/.test(t) || /archgun/.test(n)) return "archgun";
    if (/shotgun/.test(t)) return "shotgun";
    if (/pistol|secondary|kitgun/.test(t)) return "pistol";
    if (/melee|zaw|exalted/.test(t)) return "melee";
    if (/rifle|primary|sniper|bow|speargun|launcher|arm[- ]?cannon/.test(t)) return "rifle";
    if (/melee/.test(n)) return "melee";
    return "rifle";
  }

  function configKey(posCount, hasNeg) {
    return posCount + "-" + (hasNeg ? "1" : "0");
  }

  function rankScale(rank) {
    rank = Number(rank);
    if (isNaN(rank)) rank = 8;
    return (rank + 1) / 9;
  }

  function statsForClass(cls, forNeg) {
    return STATS.filter(function (s) {
      if (s.bases[cls] == null) return false;
      if (forNeg && s.positiveOnly) return false;
      return true;
    });
  }

  function rangeFor(stat, cls, omega, weight, rank, weapon) {
    var base = stat.bases[cls];
    if (base == null) return null;
    // Wiki: Fire Rate base is doubled for bows
    if (stat.bowNote && weapon) {
      var t = String(weapon.type || "").toLowerCase();
      var n = String(weapon.name || "").toLowerCase();
      if (/bow/.test(t) || /\bbow\b/.test(n)) base = base * 2;
    }
    var scale = rankScale(rank);
    var mid = base * omega * Math.abs(weight) * scale;
    return {
      min: mid * 0.9,
      max: mid * 1.1,
      mid: mid,
      unit: stat.unit,
    };
  }

  function rollFactor(value, mid) {
    if (!mid || !isFinite(mid) || mid === 0) return null;
    return Math.abs(Number(value)) / Math.abs(mid);
  }

  function gradeFromRoll(roll) {
    if (roll == null || !isFinite(roll)) return { letter: "?", pct: null, score: 0 };
    // Clamp slightly outside for user rounding
    var t = (roll - 0.9) / 0.2;
    t = Math.max(0, Math.min(1, t));
    var pct = Math.round(t * 100);
    var letter = "F";
    if (pct >= 95) letter = "S";
    else if (pct >= 85) letter = "A";
    else if (pct >= 70) letter = "B";
    else if (pct >= 50) letter = "C";
    else if (pct >= 30) letter = "D";
    return { letter: letter, pct: pct, score: t };
  }

  function letterFromAvg(scores) {
    if (!scores.length) return { letter: "?", pct: null };
    var avg = scores.reduce(function (a, b) { return a + b; }, 0) / scores.length;
    return gradeFromRoll(0.9 + avg * 0.2);
  }

  function advice(letter, hasGoodNeg, hasBadNeg) {
    if (letter === "S" || letter === "A") {
      return hasBadNeg
        ? "Strong positives — keep if the negative is tolerable; otherwise consider a safer roll."
        : "Excellent roll quality. Keep / price for trade.";
    }
    if (letter === "B") {
      return hasGoodNeg
        ? "Solid roll with a helpful negative. Keep for use or mid-tier trade."
        : "Decent — usable, but room to improve on a re-roll.";
    }
    if (letter === "C") return "Average. Fine as a budget riven; re-roll if you need endgame.";
    return "Weak roll quality. Re-roll unless the weapon is disposable.";
  }

  function parseWeekly(text) {
    try {
      return JSON.parse(text);
    } catch (_) {}
    try {
      // DE ships JS-like object literals (unquoted keys)
      // eslint-disable-next-line no-new-func
      return new Function("return (" + text + ");")();
    } catch (_) {
      return [];
    }
  }

  function weeklyFor(name) {
    if (!name || !weekly.length) return null;
    var n = String(name).toLowerCase();
    var rows = weekly.filter(function (r) {
      return r && r.compatibility && String(r.compatibility).toLowerCase() === n;
    });
    if (!rows.length) {
      rows = weekly.filter(function (r) {
        return r && r.compatibility && String(r.compatibility).toLowerCase().indexOf(n) >= 0;
      });
    }
    if (!rows.length) return null;
    var out = { unrolled: null, rerolled: null };
    rows.forEach(function (r) {
      if (r.rerolled) out.rerolled = r;
      else out.unrolled = r;
    });
    return out;
  }

  function searchWeapons(q, limit) {
    q = String(q || "").trim().toLowerCase();
    if (q.length < 2) return [];
    var scored = [];
    for (var i = 0; i < weapons.length; i++) {
      var w = weapons[i];
      var name = String(w.name || "").toLowerCase();
      var s = 0;
      if (name === q) s = 100;
      else if (name.startsWith(q)) s = 80;
      else if (name.indexOf(q) >= 0) s = 50;
      if (s > 0) scored.push({ s: s, w: w });
    }
    scored.sort(function (a, b) {
      if (b.s !== a.s) return b.s - a.s;
      return String(a.w.name).length - String(b.w.name).length;
    });
    return scored.slice(0, limit || 10).map(function (r) { return r.w; });
  }

  function hideSuggest() {
    if (!suggestEl) return;
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
      .map(function (w) {
        var o = omegaOf(w);
        return (
          '<li role="option" data-name="' +
          esc(w.name) +
          '"><span>' +
          esc(w.name) +
          "</span><span class=\"mk-tag\">ω " +
          (o != null ? o.toFixed(2) : "?") +
          "</span></li>"
        );
      })
      .join("");
    suggestEl.hidden = false;
  }

  function selectWeapon(w) {
    selected = w;
    hideSuggest();
    if (weaponEl) weaponEl.value = w.name || "";
    var o = omegaOf(w);
    var cls = rivenClass(w);
    if (metaEl) {
      metaEl.innerHTML =
        esc(w.type || "Weapon") +
        " · class <strong>" +
        esc(cls) +
        "</strong> · disposition " +
        esc(w.disposition != null ? w.disposition : "—") +
        " · ω <strong>" +
        (o != null ? o.toFixed(3) : "?") +
        "</strong>";
    }
    rebuildStatRows();
    try {
      var u = new URL(location.href);
      u.searchParams.set("weapon", w.name);
      history.replaceState(null, "", u.pathname + u.search);
    } catch (_) {}
  }

  function optionHtml(stats, selectedId) {
    return (
      '<option value="">Select…</option>' +
      stats
        .map(function (s) {
          return (
            '<option value="' +
            esc(s.id) +
            '"' +
            (s.id === selectedId ? " selected" : "") +
            ">" +
            esc(s.label) +
            "</option>"
          );
        })
        .join("")
    );
  }

  function rebuildStatRows() {
    if (!statsEl) return;
    var cls = selected ? rivenClass(selected) : "rifle";
    var posN = Number(posCountEl && posCountEl.value) || 3;
    var hasNeg = !!(hasNegEl && hasNegEl.checked);
    var posStats = statsForClass(cls, false);
    var negStats = statsForClass(cls, true);
    var html = "";
    for (var i = 0; i < posN; i++) {
      html +=
        '<div class="rg-row">' +
        '<label class="tool-field tool-field-grow"><span class="tool-label">Positive ' +
        (i + 1) +
        '</span><select class="tool-select rg-stat" data-role="pos" data-i="' +
        i +
        '">' +
        optionHtml(posStats) +
        "</select></label>" +
        '<label class="tool-field"><span class="tool-label">Value</span>' +
        '<input class="tool-input rg-val" data-role="pos" data-i="' +
        i +
        '" type="number" step="any" placeholder="e.g. 180.2" /></label>' +
        "</div>";
    }
    if (hasNeg) {
      html +=
        '<div class="rg-row">' +
        '<label class="tool-field tool-field-grow"><span class="tool-label">Negative</span><select class="tool-select rg-stat" data-role="neg">' +
        optionHtml(negStats) +
        "</select></label>" +
        '<label class="tool-field"><span class="tool-label">Value</span>' +
        '<input class="tool-input rg-val" data-role="neg" type="number" step="any" placeholder="e.g. -42.5" /></label>' +
        "</div>";
    }
    statsEl.innerHTML = html;
  }

  function findStat(id) {
    for (var i = 0; i < STATS.length; i++) if (STATS[i].id === id) return STATS[i];
    return null;
  }

  function readSlots() {
    var slots = [];
    if (!statsEl) return slots;
    statsEl.querySelectorAll(".rg-row").forEach(function (row) {
      var sel = row.querySelector(".rg-stat");
      var inp = row.querySelector(".rg-val");
      if (!sel || !inp) return;
      var id = sel.value;
      var raw = String(inp.value || "").trim();
      if (!id || !raw) return;
      var val = Number(raw);
      if (!isFinite(val)) return;
      slots.push({
        role: sel.getAttribute("data-role"),
        stat: findStat(id),
        value: val,
      });
    });
    return slots;
  }

  function formatRange(r) {
    if (!r) return "—";
    var u = r.unit || "";
    function fmt(n) {
      if (Math.abs(n) >= 10) return n.toFixed(1);
      return n.toFixed(2);
    }
    return fmt(r.min) + " – " + fmt(r.max) + (u ? " " + u : "");
  }

  function grade() {
    if (!selected) {
      setStatus(false, "Select a weapon first");
      return;
    }
    var omega = omegaOf(selected);
    if (omega == null) {
      setStatus(false, "No disposition data for this weapon");
      return;
    }
    var cls = rivenClass(selected);
    var posN = Number(posCountEl && posCountEl.value) || 3;
    var hasNeg = !!(hasNegEl && hasNegEl.checked);
    var weights = WEIGHTS[configKey(posN, hasNeg)];
    var rank = rankEl ? rankEl.value : 8;
    var slots = readSlots();
    var positives = slots.filter(function (s) { return s.role === "pos" && s.stat; });
    var negatives = slots.filter(function (s) { return s.role === "neg" && s.stat; });

    if (positives.length < 2) {
      setStatus(false, "Enter at least two positive stats with values");
      return;
    }

    var rows = [];
    var scores = [];
    var hasGoodNeg = false;
    var hasBadNeg = false;

    positives.forEach(function (slot) {
      var rng = rangeFor(slot.stat, cls, omega, weights.bonus, rank, selected);
      if (!rng) {
        rows.push({ label: slot.stat.label, note: "N/A for " + cls, grade: null });
        return;
      }
      var roll = rollFactor(slot.value, rng.mid);
      var g = gradeFromRoll(roll);
      scores.push(g.score);
      rows.push({
        label: slot.stat.label,
        value: slot.value,
        range: rng,
        roll: roll,
        grade: g,
        kind: "pos",
      });
    });

    negatives.forEach(function (slot) {
      var rng = rangeFor(slot.stat, cls, omega, weights.malus, rank, selected);
      if (!rng) return;
      var roll = rollFactor(slot.value, rng.mid);
      var g = gradeFromRoll(roll);
      if (slot.stat.goodNeg) hasGoodNeg = true;
      else hasBadNeg = true;
      rows.push({
        label: slot.stat.label + (slot.stat.goodNeg ? " (often good −)" : ""),
        value: slot.value,
        range: rng,
        roll: roll,
        grade: g,
        kind: "neg",
        goodNeg: !!slot.stat.goodNeg,
      });
    });

    var overall = letterFromAvg(scores);
    var tip = advice(overall.letter, hasGoodNeg, hasBadNeg);
    var market = weeklyFor(selected.name);

    var html =
      '<section class="tool-card rg-verdict">' +
      '<div class="rg-grade-hero">' +
      '<div class="rg-letter rg-letter-' +
      esc(overall.letter.toLowerCase()) +
      '">' +
      esc(overall.letter) +
      "</div>" +
      "<div><h2>" +
      esc(selected.name) +
      " riven</h2>" +
      '<p class="tool-meta">Overall ' +
      (overall.pct != null ? overall.pct + "% of max roll" : "—") +
      " · ω " +
      omega.toFixed(3) +
      " · " +
      esc(cls) +
      " · " +
      posN +
      "pos" +
      (hasNeg ? "+neg" : "") +
      " · rank " +
      esc(rank) +
      "</p>" +
      '<p class="tool-prose">' +
      esc(tip) +
      "</p></div></div>";

    html += '<ul class="tool-list rg-grade-list">';
    rows.forEach(function (r) {
      if (!r.grade) {
        html += "<li><strong>" + esc(r.label) + "</strong> — " + esc(r.note || "") + "</li>";
        return;
      }
      html +=
        "<li><div class=\"rg-line\"><strong>" +
        esc(r.label) +
        '</strong> <span class="rg-badge rg-letter-' +
        esc(r.grade.letter.toLowerCase()) +
        '">' +
        esc(r.grade.letter) +
        "</span></div>" +
        '<div class="tool-meta">Entered ' +
        esc(r.value) +
        (r.range.unit ? " " + esc(r.range.unit) : "") +
        " · range " +
        esc(formatRange(r.range)) +
        " · roll ×" +
        (r.roll != null ? r.roll.toFixed(3) : "?") +
        " (" +
        (r.grade.pct != null ? r.grade.pct + "%" : "?") +
        ")</div></li>";
    });
    html += "</ul>";

    if (market && (market.unrolled || market.rerolled)) {
      html += '<h3 class="tool-section-title" style="margin-top:16px;font-family:var(--font-display);font-size:1.05rem">Weekly trade snapshot (PC)</h3><ul class="tool-list">';
      if (market.unrolled) {
        html +=
          "<li><strong>Unrolled</strong> — avg " +
          esc(Math.round(market.unrolled.avg)) +
          "p · median " +
          esc(Math.round(market.unrolled.median || 0)) +
          "p · " +
          esc(market.unrolled.pop || 0) +
          " trades</li>";
      }
      if (market.rerolled) {
        html +=
          "<li><strong>Rerolled</strong> — avg " +
          esc(Math.round(market.rerolled.avg)) +
          "p · median " +
          esc(Math.round(market.rerolled.median || 0)) +
          "p · " +
          esc(market.rerolled.pop || 0) +
          " trades</li>";
      }
      html += "</ul><p class=\"tool-meta\">Source: DE weeklyRivensPC.json — averages across all rolls, not your grade.</p>";
    } else {
      html += '<p class="tool-meta" style="margin-top:12px">No weekly trade row for this weapon name (or feed unavailable).</p>';
    }

    html +=
      '<div class="tool-actions" style="margin-top:14px">' +
      '<a class="btn-secondary" href="/rivens.html">Disposition table</a>' +
      '<a class="btn-secondary" href="/market.html?q=' +
      encodeURIComponent(selected.name + " riven") +
      '">Market</a>' +
      "</div></section>";

    if (resultEl) {
      resultEl.innerHTML = html;
      resultEl.hidden = false;
      resultEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
    setStatus(true, "Graded " + selected.name + " · " + overall.letter);
  }

  function loadWeapons() {
    return fetch(API + "/weapons?language=en", { cache: "no-store", headers: { Accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (list) {
        weapons = (list || []).filter(function (w) {
          return w && w.name && (w.disposition != null || w.omegaAttenuation != null);
        });
      });
  }

  function loadWeekly() {
    return fetch(WEEKLY_URL, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.text();
      })
      .then(function (t) {
        weekly = parseWeekly(t) || [];
      })
      .catch(function () {
        weekly = [];
      });
  }

  if (weaponEl) {
    weaponEl.addEventListener("input", function () {
      clearTimeout(suggestTimer);
      suggestTimer = setTimeout(function () {
        renderSuggest(searchWeapons(weaponEl.value, 10));
      }, 100);
    });
    weaponEl.addEventListener("keydown", function (e) {
      if (e.key === "Escape") hideSuggest();
      if (e.key === "Enter") {
        e.preventDefault();
        var list = searchWeapons(weaponEl.value, 1);
        if (list.length) selectWeapon(list[0]);
      }
    });
  }

  if (suggestEl) {
    suggestEl.addEventListener("click", function (e) {
      var li = e.target.closest("[data-name]");
      if (!li) return;
      var name = li.getAttribute("data-name");
      var hit = weapons.filter(function (w) { return w.name === name; })[0];
      if (hit) selectWeapon(hit);
    });
  }

  document.addEventListener("click", function (e) {
    if (!suggestEl || suggestEl.hidden) return;
    if (e.target === weaponEl || suggestEl.contains(e.target)) return;
    hideSuggest();
  });

  if (posCountEl) posCountEl.addEventListener("change", rebuildStatRows);
  if (hasNegEl) hasNegEl.addEventListener("change", rebuildStatRows);

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      grade();
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      selected = null;
      if (weaponEl) weaponEl.value = "";
      if (metaEl) metaEl.textContent = "Search a weapon to load disposition.";
      if (resultEl) {
        resultEl.hidden = true;
        resultEl.innerHTML = "";
      }
      rebuildStatRows();
      setStatus(true, weapons.length + " weapons ready");
    });
  }

  rebuildStatRows();

  Promise.all([loadWeapons(), loadWeekly()]).then(function () {
    setStatus(true, weapons.length + " weapons" + (weekly.length ? " · weekly trades loaded" : " · weekly trades offline"));
    var q = new URLSearchParams(location.search).get("weapon");
    if (q) {
      if (weaponEl) weaponEl.value = q;
      var hits = searchWeapons(q, 1);
      if (hits.length) selectWeapon(hits[0]);
    }
  }).catch(function () {
    setStatus(false, "Could not load weapon list");
  });
})();
