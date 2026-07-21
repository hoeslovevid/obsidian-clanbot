/**
 * Site-wide config — update BOT_API_URL with your Railway public URL (required for contact form + dashboard).
 * Example: "https://obsidianoverseer.up.railway.app"
 */
window.OBSIDIAN_SITE = {
  BOT_API_URL: "https://obsidianoverseer.up.railway.app",
  // Optional: full dashboard URL. Defaults to BOT_API_URL + /dashboard.html
  DASHBOARD_PUBLIC_URL: "https://obsidianoverseer.up.railway.app/dashboard.html",
  // Live Market orders proxy (Deno Deploy *.deno.dev). See deploy/wfm-proxy/README.md
  // Example: "https://obsidian-wfm-xxxx.deno.dev"
  WFM_PROXY_URL: "",
  DISCORD_CLIENT_ID: "1460107752658440223",
  DISCORD_PERMISSIONS: "277025508160",
  DISCORD_SCOPE: "bot applications.commands",
  DISCORD_SERVER_INVITE: "https://discord.gg/bJscayQNK4",
  CONTACT_EMAIL: "",
  BOT_DEVELOPER: "Danger!",
  // When you point a custom domain at the dashboard (e.g. dash.obsidianoverseer.com),
  // set DASHBOARD_PUBLIC_URL to that origin + /dashboard.html
  // Optional manual override if live stats are unavailable: { guild_count: 12, user_count: 3400 }
  BOT_STATS: null,
};
