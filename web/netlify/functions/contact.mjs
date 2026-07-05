/**
 * Contact form serverless function.
 * POST body: { name, email, preferred, message }
 * Requires env: CONTACT_WEBHOOK_URL (Discord webhook). Never commit the webhook to the repo.
 */
export default async (req, context) => {
  const origin = req.headers.get('origin') || '';
  const allowOrigin = origin || '*';

  const cors = {
    'Access-Control-Allow-Origin': allowOrigin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: cors });
  }

  if (req.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'Method not allowed' }), {
      status: 405,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  }

  const webhookUrl = process.env.CONTACT_WEBHOOK_URL && process.env.CONTACT_WEBHOOK_URL.trim();
  if (!webhookUrl) {
    return new Response(
      JSON.stringify({ error: 'Contact form is not configured.' }),
      { status: 503, headers: { 'Content-Type': 'application/json', ...cors } }
    );
  }

  let body;
  try {
    body = await req.json();
  } catch (_) {
    return new Response(
      JSON.stringify({ error: 'Invalid JSON' }),
      { status: 400, headers: { 'Content-Type': 'application/json', ...cors } }
    );
  }

  const name = (body.name || '').trim().slice(0, 100) || '—';
  const email = (body.email || '').trim().slice(0, 200) || '—';
  const preferred = (body.preferred || 'Either').trim().slice(0, 50);
  const discordUsername = (body.discordUsername || '').trim().slice(0, 100) || '—';
  const rawMessage = (body.message || '').trim();
  if (!rawMessage) {
    return new Response(
      JSON.stringify({ error: 'Message is required' }),
      { status: 400, headers: { 'Content-Type': 'application/json', ...cors } }
    );
  }
  const message = rawMessage.slice(0, 2000);

  const embed = {
    title: '📩 New message from website',
    color: 0x8b7cf8,
    fields: [
      { name: 'From', value: name, inline: true },
      { name: 'Email', value: email, inline: true },
      { name: 'Preferred response', value: preferred, inline: true },
      { name: 'Discord username', value: discordUsername, inline: true },
      { name: 'Message', value: message.slice(0, 1024), inline: false },
    ],
    footer: { text: 'Obsidian Overseer contact form' },
    timestamp: new Date().toISOString(),
  };
  if (message.length > 1024) {
    embed.fields.push({ name: '(continued)', value: message.slice(1024, 2048), inline: false });
  }

  try {
    const res = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ embeds: [embed] }),
    });
    if (!res.ok) {
      const text = await res.text();
      console.error('Discord webhook error', res.status, text);
      return new Response(
        JSON.stringify({ error: 'Failed to send message' }),
        { status: 502, headers: { 'Content-Type': 'application/json', ...cors } }
      );
    }
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', ...cors },
    });
  } catch (err) {
    console.error('Contact function error', err);
    return new Response(
      JSON.stringify({ error: 'Failed to send message' }),
      { status: 502, headers: { 'Content-Type': 'application/json', ...cors } }
    );
  }
};
