/**
 * Standalone Warframe Market proxy for obsidianoverseer.com.
 *
 * Deploy to Deno Deploy (free *.deno.dev URL — no Cloudflare DNS required):
 *   deployctl deploy --project=obsidian-wfm --entrypoint=main.ts
 *
 * Endpoints (same shape as the bot dashboard API):
 *   GET /api/ping
 *   GET /api/wfm/items/{slug}?platform=pc
 *
 * Catalog stays on GitHub Pages (/assets/wfm-items.json); this service is for live orders.
 */

const WFM_BASE = "https://api.warframe.market/v2";
const ASSET_BASE = "https://warframe.market/static/assets/";
const UA = "ObsidianOverseerWfmProxy/1.0 (+https://obsidianoverseer.com)";

const ALLOWED_ORIGINS = new Set([
  "https://obsidianoverseer.com",
  "https://www.obsidianoverseer.com",
  "http://localhost:5500",
  "http://127.0.0.1:5500",
  "http://localhost:8080",
  "http://127.0.0.1:8080",
]);

const PLATFORMS = new Set(["pc", "xbox", "ps4", "switch", "complete"]);

function corsHeaders(req: Request): HeadersInit {
  const origin = (req.headers.get("Origin") || "").replace(/\/$/, "");
  // Public read-only API — wildcard avoids brittle Origin matching / preflight failures.
  const allow =
    origin &&
    (ALLOWED_ORIGINS.has(origin) ||
      origin.endsWith(".obsidianoverseer.com") ||
      origin.endsWith(".github.io") ||
      origin.endsWith(".deno.net") ||
      origin.startsWith("http://localhost:") ||
      origin.startsWith("http://127.0.0.1:"))
      ? origin
      : "*";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Accept, Platform, Language, Cache-Control",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin, Platform",
  };
}

function json(req: Request, data: unknown, status = 200, cache = "public, max-age=45") {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cache,
      ...corsHeaders(req),
    },
  });
}

function platformOf(req: Request): string {
  const q = new URL(req.url).searchParams.get("platform") || "pc";
  const p = q.trim().toLowerCase();
  return PLATFORMS.has(p) ? p : "pc";
}

function assetUrl(path: unknown): string | null {
  if (!path || typeof path !== "string") return null;
  const p = path.replace(/^\/+/, "");
  if (p.startsWith("http://") || p.startsWith("https://")) return p;
  return ASSET_BASE + p;
}

function i18nEn(raw: Record<string, unknown>): Record<string, unknown> {
  const i18n = raw.i18n;
  if (i18n && typeof i18n === "object") {
    const en = (i18n as Record<string, unknown>).en;
    if (en && typeof en === "object") return en as Record<string, unknown>;
  }
  return {};
}

function orderType(o: Record<string, unknown>): string {
  const t = String(o.type || o.order_type || "").toLowerCase();
  return t === "buy" || t === "sell" ? t : "";
}

function userStatus(o: Record<string, unknown>): string {
  const user = o.user && typeof o.user === "object" ? (o.user as Record<string, unknown>) : {};
  return String(user.status || "").toLowerCase() || "offline";
}

function slimOrder(o: Record<string, unknown>) {
  const user = o.user && typeof o.user === "object" ? (o.user as Record<string, unknown>) : {};
  return {
    type: orderType(o),
    platinum: o.platinum,
    quantity: o.quantity,
    visible: o.visible !== false,
    user: {
      ingameName: user.ingameName || user.ingame_name || "?",
      reputation: user.reputation,
      status: userStatus(o),
      platform: user.platform,
    },
  };
}

async function wfmGet(path: string, platform: string): Promise<Record<string, unknown> | null> {
  const res = await fetch(`${WFM_BASE}/${path.replace(/^\//, "")}`, {
    headers: {
      Accept: "application/json",
      Language: "en",
      Platform: platform,
      "User-Agent": UA,
      Origin: "https://warframe.market",
      Referer: "https://warframe.market/",
    },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data && typeof data === "object" ? (data as Record<string, unknown>) : null;
}

function activeFirst(rows: Record<string, unknown>[], reverse: boolean) {
  return [...rows].sort((a, b) => {
    const rank = (o: Record<string, unknown>) => {
      const st = userStatus(o);
      const online = st === "ingame" ? 0 : st === "online" ? 1 : 2;
      const plat = Number(o.platinum) || 0;
      return [online, reverse ? -plat : plat] as const;
    };
    const ra = rank(a);
    const rb = rank(b);
    return ra[0] - rb[0] || ra[1] - rb[1];
  });
}

function headline(rows: Record<string, unknown>[], reverse: boolean): number | null {
  const preferred = rows.filter((o) => {
    const st = userStatus(o);
    return st === "ingame" || st === "online";
  });
  const pool = preferred.length ? preferred : rows;
  const prices = pool
    .map((o) => o.platinum)
    .filter((p): p is number => typeof p === "number");
  if (!prices.length) return null;
  return reverse ? Math.max(...prices) : Math.min(...prices);
}

async function handleItem(req: Request, slug: string): Promise<Response> {
  if (!/^[a-z0-9_]+$/.test(slug)) {
    return json(req, { error: "bad_slug", message: "Missing or invalid item slug." }, 400, "no-store");
  }
  const platform = platformOf(req);
  const [itemBody, ordersBody] = await Promise.all([
    wfmGet(`items/${slug}`, platform),
    wfmGet(`orders/item/${slug}`, platform),
  ]);
  const item = itemBody?.data;
  if (!item || typeof item !== "object") {
    return json(req, { error: "not_found", message: "Item not found." }, 404, "no-store");
  }
  const itemObj = item as Record<string, unknown>;
  const orders = Array.isArray(ordersBody?.data) ? (ordersBody!.data as Record<string, unknown>[]) : [];
  const visible = orders.filter((o) => o.visible !== false);
  const sells = visible.filter((o) => orderType(o) === "sell");
  const buys = visible.filter((o) => orderType(o) === "buy");
  const sellsSorted = activeFirst(sells, false);
  const buysSorted = activeFirst(buys, true);
  const en = i18nEn(itemObj);
  const name = String(en.name || slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()));
  const itemSlug = String(itemObj.slug || slug);

  return json(req, {
    ok: true,
    platform,
    item: {
      slug: itemSlug,
      name,
      thumb: assetUrl(en.thumb),
      icon: assetUrl(en.icon),
      tags: itemObj.tags || [],
      ducats: itemObj.ducats ?? null,
      tradingTax: itemObj.tradingTax ?? null,
      reqMasteryRank: itemObj.reqMasteryRank ?? null,
      tradable: itemObj.tradable !== false,
      setRoot: itemObj.setRoot ?? null,
      setParts: itemObj.setParts || [],
      marketUrl: `https://warframe.market/items/${itemSlug}`,
    },
    summary: {
      lowestSell: headline(sellsSorted, false),
      highestBuy: headline(buysSorted, true),
      sellCount: sells.length,
      buyCount: buys.length,
      onlineSell: sells.filter((o) => {
        const st = userStatus(o);
        return st === "ingame" || st === "online";
      }).length,
      onlineBuy: buys.filter((o) => {
        const st = userStatus(o);
        return st === "ingame" || st === "online";
      }).length,
    },
    sellOrders: sellsSorted.slice(0, 40).map(slimOrder),
    buyOrders: buysSorted.slice(0, 40).map(slimOrder),
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders(req) });
  }
  if (req.method !== "GET" && req.method !== "HEAD") {
    return json(req, { error: "method_not_allowed" }, 405, "no-store");
  }

  const url = new URL(req.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (path === "/" || path === "/api/ping") {
    return json(
      req,
      { ok: true, service: "wfm-proxy", version: "1.0.0" },
      200,
      "public, max-age=60",
    );
  }

  const itemMatch = path.match(/^\/api\/wfm\/items\/([a-z0-9_]+)$/i);
  if (itemMatch) {
    try {
      return await handleItem(req, itemMatch[1].toLowerCase());
    } catch (err) {
      console.error("wfm item error", err);
      return json(req, { error: "upstream_error", message: "Warframe Market request failed." }, 502, "no-store");
    }
  }

  // Catalog is served from GitHub Pages; keep a tiny hint here.
  if (path === "/api/wfm/items") {
    return json(
      req,
      {
        ok: false,
        error: "use_static_catalog",
        message: "Use https://obsidianoverseer.com/assets/wfm-items.json for the item catalog.",
      },
      404,
      "no-store",
    );
  }

  return json(req, { error: "not_found" }, 404, "no-store");
});
