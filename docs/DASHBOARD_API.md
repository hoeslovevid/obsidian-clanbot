# Web dashboard API

Optional HTTP API so the site in [`web/`](../web/) (or any backend) can show a mod dashboard powered by live bot data.

The API runs **inside the bot process** on the same Railway service (uses the `PORT` env var). Your website calls it from a **server-side route** or backend — never expose `DASHBOARD_API_SECRET` in browser JavaScript.

## Enable

Set these environment variables on Railway (or in `config/.env` locally):

| Variable | Required | Description |
|----------|----------|-------------|
| `DASHBOARD_API_ENABLED` | yes | `true` to start the HTTP server |
| `DASHBOARD_API_SECRET` | recommended | Long random string for website backend auth |
| `DISCORD_CLIENT_ID` | for OAuth | Your Discord application client id |
| `DASHBOARD_CORS_ORIGINS` | optional | Comma-separated site origins (defaults to `BOT_WEBSITE`) |
| `PORT` | Railway | Set automatically by Railway |

Redeploy after enabling. Logs should show:

```text
[dashboard-api] Listening on 0.0.0.0:8080
```

## Architecture

```text
Browser  →  Your website (OAuth login)  →  Website backend  →  Bot dashboard API
                                              Bearer secret      Same DB + bot cache
                                              X-Discord-User-Id
```

## Authentication

### Recommended: service auth (website backend)

After the user logs in with Discord OAuth on your site, your **server** calls the bot API:

```http
GET /api/guilds/{guild_id}/overview
Authorization: Bearer <DASHBOARD_API_SECRET>
X-Discord-User-Id: <discord_user_id>
```

The API verifies that user is an **Administrator** in that guild (via the bot’s member cache).

### Alternative: Discord OAuth token

Pass the user’s Discord access token directly (useful for prototypes):

```http
GET /api/me
Authorization: Bearer <discord_oauth_access_token>
```

Requires scopes: `identify`, `guilds`.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/health` | none | Bot version, latency, DB ping, optional `?guild_id=` inbox snippet |
| GET | `/api/auth/info` | none | OAuth URLs and integration hints (no secrets) |
| GET | `/api/me` | yes | Current user + guilds they can manage |
| GET | `/api/guilds` | yes | Same guild list |
| GET | `/api/guilds/{id}/inbox` | yes + admin | Ticket/app/LFG/suggestion counts |
| GET | `/api/guilds/{id}/overview` | yes + admin | Full mod dashboard JSON |
| GET | `/api/guilds/{id}/setup` | yes + admin | Setup health checklist (channels, roles, features) |
| GET | `/api/guilds/{id}/features` | yes + admin | Feature toggle states |
| PATCH | `/api/guilds/{id}/features` | yes + admin | `{"feature":"music","enabled":true}` |
| GET | `/api/guilds/{id}/warframe` | yes + admin | Baro Ki'Teer status + open-world cycles |
| GET | `/api/guilds/{id}/analytics` | yes + admin | Activity stats, daily command chart, economy volume |
| GET | `/api/guilds/{id}/audit` | yes + admin | Moderation audit timeline; optional `?q=` filter, `?limit=` (max 100) |
| GET | `/api/guilds/{id}/search` | yes + admin | Search open tickets, applications, warnings; `?q=` (min 2 chars) |
| POST | `/api/contact` | none (rate-limited) | Public contact form → `CONTACT_WEBHOOK_URL` |

## Example: Next.js API route

```typescript
// app/api/dashboard/[guildId]/overview/route.ts
export async function GET(
  req: Request,
  { params }: { params: { guildId: string } }
) {
  const session = await getServerSession(); // your Discord OAuth session
  if (!session?.user?.id) return Response.json({ error: "unauthorized" }, { status: 401 });

  const res = await fetch(
    `${process.env.BOT_API_URL}/api/guilds/${params.guildId}/overview`,
    {
      headers: {
        Authorization: `Bearer ${process.env.DASHBOARD_API_SECRET}`,
        "X-Discord-User-Id": session.user.id,
      },
      next: { revalidate: 30 },
    }
  );
  return Response.json(await res.json(), { status: res.status });
}
```

Env on your **website** host:

```env
BOT_API_URL=https://your-bot-service.up.railway.app
DASHBOARD_API_SECRET=same_value_as_on_railway_bot_service
```

## Railway networking

1. Enable `DASHBOARD_API_ENABLED=true` on the bot service.
2. Generate a public domain for the bot service (Railway → Settings → Networking).
3. Point `BOT_API_URL` on your website to that domain.
4. Set `DASHBOARD_CORS_ORIGINS` if the browser calls the API directly (not recommended for secret auth).

## Response shape (overview)

```json
{
  "guild_id": 123,
  "guild_name": "Obsidian Clan",
  "summary": {
    "open_incidents": 0,
    "open_lfg": 2,
    "warns_today": 1,
    "incident_mode": false,
    "automod_enabled": true
  },
  "tickets": [{ "ticket_id": "T-001", "subject": "...", "jump_url": "https://discord.com/channels/..." }],
  "applications": [],
  "warnings": []
}
```

## Response shape (warframe)

```json
{
  "baro": {
    "active": true,
    "available": true,
    "location": "Larunda Relay",
    "expiry": "2026-07-06T18:00:00.000Z",
    "inventory_count": 12,
    "inventory_preview": [{ "name": "Primed Flow", "ducats": 350, "credits": 110000 }]
  },
  "cycles": [
    { "id": "cetus", "name": "Cetus (Plains)", "state": "day", "label": "Day", "expiry": "..." }
  ]
}
```

## Response shape (analytics)

```json
{
  "guild_id": 123,
  "member_count": 450,
  "active_users_7d": 42,
  "commands_7d": 1280,
  "economy_volume_7d": 95000,
  "top_members": [{ "user_id": "...", "user_name": "Player", "weekly_score": 120 }],
  "daily_activity": [{ "date": "2026-07-01", "commands": 95 }],
  "counts": { "open_tickets": 3, "pending_apps": 1, "open_lfg": 2 }
}
```

## Response shape (audit / search)

Audit entries use a unified timeline:

```json
{
  "guild_id": 123,
  "entries": [
    {
      "id": "warn-123-2026-07-01T12:00:00",
      "type": "warning",
      "timestamp": "2026-07-01T12:00:00",
      "actor_name": "ModName",
      "target_name": "UserName",
      "summary": "Spam in general"
    }
  ],
  "total": 1
}
```

Search returns cross-type hits:

```json
{
  "query": "T-001",
  "results": [
    { "kind": "ticket", "id": "T-001", "title": "Help request", "subtitle": "UserName", "jump_url": "https://discord.com/channels/..." }
  ]
}
```

## Security notes

- Treat `DASHBOARD_API_SECRET` like a password.
- Only administrators in a guild can read/write that guild’s data.
- Write access is currently limited to **feature toggles**; extend `core/dashboard_data.py` for more actions later.
- For multi-service setups later, migrate to shared Postgres (`DB_BACKEND=postgres`) so a standalone API service can read the same data.

## Local testing

```bash
# config/.env
DASHBOARD_API_ENABLED=true
DASHBOARD_API_SECRET=dev-secret-change-me
DASHBOARD_API_PORT=8080

curl http://localhost:8080/api/health
curl -H "Authorization: Bearer dev-secret-change-me" -H "X-Discord-User-Id: YOUR_ID" \
  http://localhost:8080/api/guilds/GUILD_ID/overview
```
