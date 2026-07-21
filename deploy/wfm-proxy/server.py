"""
Standalone Warframe Market live-order proxy.

Deploy as a *separate* Railway service (not the Discord bot) so TLS works and
the bot's edge rate-limit does not apply.

  Root Directory: deploy/wfm-proxy
  Start Command:  python server.py

Endpoints:
  GET /api/ping
  GET /api/wfm/items/{slug}?platform=pc
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

WFM_BASE = "https://api.warframe.market/v2"
ASSET_BASE = "https://warframe.market/static/assets/"
UA = "ObsidianOverseerWfmProxy/1.0 (+https://obsidianoverseer.com)"
PLATFORMS = frozenset({"pc", "xbox", "ps4", "switch", "complete"})
SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def _cors(request: web.Request, resp: web.StreamResponse) -> web.StreamResponse:
    origin = (request.headers.get("Origin") or "").rstrip("/")
    allow = "*"
    if origin and (
        origin in {
            "https://obsidianoverseer.com",
            "https://www.obsidianoverseer.com",
        }
        or origin.endswith(".obsidianoverseer.com")
        or origin.endswith(".github.io")
        or origin.startswith("http://localhost:")
        or origin.startswith("http://127.0.0.1:")
    ):
        allow = origin
    resp.headers["Access-Control-Allow-Origin"] = allow
    resp.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Accept, Platform, Language, Cache-Control"
    )
    resp.headers["Access-Control-Max-Age"] = "86400"
    resp.headers["Vary"] = "Origin, Platform"
    return resp


def _json(request: web.Request, data: Any, *, status: int = 200, cache: str = "public, max-age=45") -> web.Response:
    resp = web.Response(
        text=json.dumps(data, default=str),
        status=status,
        content_type="application/json",
    )
    resp.headers["Cache-Control"] = cache
    return _cors(request, resp)  # type: ignore[return-value]


async def handle_options(request: web.Request) -> web.Response:
    return _cors(request, web.Response(status=204))  # type: ignore[return-value]


def _platform(request: web.Request) -> str:
    p = (request.query.get("platform") or "pc").strip().lower()
    return p if p in PLATFORMS else "pc"


def _asset(path: Any) -> str | None:
    if not path or not isinstance(path, str):
        return None
    path = path.lstrip("/")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return ASSET_BASE + path


def _i18n_en(raw: dict) -> dict:
    i18n = raw.get("i18n")
    if isinstance(i18n, dict):
        en = i18n.get("en")
        if isinstance(en, dict):
            return en
    return {}


def _order_type(o: dict) -> str:
    t = str(o.get("type") or o.get("order_type") or "").lower()
    return t if t in {"buy", "sell"} else ""


def _user_status(o: dict) -> str:
    user = o.get("user") if isinstance(o.get("user"), dict) else {}
    return str(user.get("status") or "offline").lower()


def _slim_order(o: dict) -> dict:
    user = o.get("user") if isinstance(o.get("user"), dict) else {}
    return {
        "type": _order_type(o),
        "platinum": o.get("platinum"),
        "quantity": o.get("quantity"),
        "visible": o.get("visible", True),
        "user": {
            "ingameName": user.get("ingameName") or user.get("ingame_name") or "?",
            "reputation": user.get("reputation"),
            "status": _user_status(o),
            "platform": user.get("platform"),
        },
    }


async def _wfm_get(session: ClientSession, path: str, platform: str) -> dict | None:
    async with session.get(
        f"{WFM_BASE}/{path.lstrip('/')}",
        headers={
            "Accept": "application/json",
            "Language": "en",
            "Platform": platform,
            "User-Agent": UA,
            "Origin": "https://warframe.market",
            "Referer": "https://warframe.market/",
        },
        timeout=ClientTimeout(total=25),
    ) as resp:
        if resp.status != 200:
            return None
        data = await resp.json(content_type=None)
        return data if isinstance(data, dict) else None


def _active_first(rows: list[dict], *, reverse: bool) -> list[dict]:
    def key(o: dict) -> tuple:
        st = _user_status(o)
        online = 0 if st == "ingame" else (1 if st == "online" else 2)
        plat = o.get("platinum") or 0
        return (online, -plat if reverse else plat)

    return sorted(rows, key=key)


def _headline(rows: list[dict], *, reverse: bool) -> int | None:
    preferred = [o for o in rows if _user_status(o) in {"ingame", "online"}]
    pool = preferred or rows
    prices = [o.get("platinum") for o in pool if isinstance(o.get("platinum"), (int, float))]
    if not prices:
        return None
    return int(max(prices) if reverse else min(prices))


async def handle_ping(request: web.Request) -> web.Response:
    return _json(request, {"ok": True, "service": "wfm-proxy", "version": "1.0.0"}, cache="public, max-age=60")


async def handle_item(request: web.Request) -> web.Response:
    slug = (request.match_info.get("slug") or "").strip().lower()
    if not slug or not SLUG_RE.match(slug):
        return _json(
            request,
            {"error": "bad_slug", "message": "Missing or invalid item slug."},
            status=400,
            cache="no-store",
        )
    platform = _platform(request)
    async with ClientSession() as session:
        item_body, orders_body = await asyncio.gather(
            _wfm_get(session, f"items/{slug}", platform),
            _wfm_get(session, f"orders/item/{slug}", platform),
        )

    item = item_body.get("data") if item_body else None
    if not isinstance(item, dict):
        return _json(
            request,
            {"error": "not_found", "message": "Item not found."},
            status=404,
            cache="no-store",
        )

    orders = orders_body.get("data") if orders_body else []
    if not isinstance(orders, list):
        orders = []
    visible = [o for o in orders if isinstance(o, dict) and o.get("visible") is not False]
    sells = [o for o in visible if _order_type(o) == "sell"]
    buys = [o for o in visible if _order_type(o) == "buy"]
    sells_sorted = _active_first(sells, reverse=False)
    buys_sorted = _active_first(buys, reverse=True)
    en = _i18n_en(item)
    item_slug = str(item.get("slug") or slug)
    name = str(en.get("name") or item_slug.replace("_", " ").title())

    return _json(
        request,
        {
            "ok": True,
            "platform": platform,
            "item": {
                "slug": item_slug,
                "name": name,
                "thumb": _asset(en.get("thumb")),
                "icon": _asset(en.get("icon")),
                "tags": item.get("tags") or [],
                "ducats": item.get("ducats"),
                "tradingTax": item.get("tradingTax"),
                "reqMasteryRank": item.get("reqMasteryRank"),
                "tradable": item.get("tradable", True),
                "setRoot": item.get("setRoot"),
                "setParts": item.get("setParts") or [],
                "marketUrl": f"https://warframe.market/items/{item_slug}",
            },
            "summary": {
                "lowestSell": _headline(sells_sorted, reverse=False),
                "highestBuy": _headline(buys_sorted, reverse=True),
                "sellCount": len(sells),
                "buyCount": len(buys),
                "onlineSell": sum(1 for o in sells if _user_status(o) in {"ingame", "online"}),
                "onlineBuy": sum(1 for o in buys if _user_status(o) in {"ingame", "online"}),
            },
            "sellOrders": [_slim_order(o) for o in sells_sorted[:40]],
            "buyOrders": [_slim_order(o) for o in buys_sorted[:40]],
        },
    )


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_route("OPTIONS", "/{tail:.*}", handle_options)
    app.router.add_get("/", handle_ping)
    app.router.add_get("/api/ping", handle_ping)
    app.router.add_get("/api/wfm/items/{slug}", handle_item)
    return app


def main() -> None:
    port = int(os.environ.get("PORT") or os.environ.get("WFM_PROXY_PORT") or "8080")
    web.run_app(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
