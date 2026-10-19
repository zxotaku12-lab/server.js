/**
 * Discord Bot Server
 * ------------------
 * Ek hi process me do cheezein chalti hain:
 *   1. HTTP Interactions server  (POST /interactions) — hamesha chalta hai
 *   2. Gateway bot (bot.js)      — sirf jab DISCORD_TOKEN set ho
 *
 * Routes:
 *   POST /interactions       -> Discord interactions endpoint (PING + slash commands + components)
 *   GET  /                   -> Status page (live command list ke saath)
 *   GET  /health             -> Health check JSON
 *   GET  /commands           -> Loaded slash commands (JSON, debug ke liye)
 *   GET  /terms-of-service   -> Terms of Service page
 *   GET  /privacy-policy     -> Privacy Policy page
 *
 * Env:
 *   PORT                - Render khud set karta hai (default 3000)
 *   DISCORD_PUBLIC_KEY  - Developer Portal -> General Information -> Public Key
 *                         (set karne par signature verification ON — recommended)
 *   DISCORD_TOKEN       - Developer Portal -> Bot -> Reset Token (Gateway bot ke liye)
 *   GUILD_ID            - (optional) commands sirf us guild me INSTANT register karo
 */

const express = require('express');
const nacl = require('tweetnacl');

const { getCommands, commandUsage } = require('./commands');
const { HttpInteraction } = require('./lib/http-interaction');

const app = express();
const PORT = process.env.PORT || 3000;

const PUBLIC_KEY = (process.env.DISCORD_PUBLIC_KEY || '').trim();
if (!PUBLIC_KEY) {
  console.warn('[WARN] DISCORD_PUBLIC_KEY set nahi hai — signature verification skip ho rahi hai.');
  console.warn('       Render Dashboard -> Environment -> Discord Public Key add karo (recommended).');
}

// Commands ek hi registry se aati hain — bot.js aur register-commands.js bhi yahi use karte hain.
const registry = getCommands();
console.log(`[server] ${registry.names.length} slash commands loaded: ${registry.names.map((n) => `/${n}`).join(', ')}`);

/* ------------------------------------------------------------------ */
/*  Gateway bot (optional)                                             */
/* ------------------------------------------------------------------ */
let gateway = null;

function bootGateway() {
  if (!process.env.DISCORD_TOKEN) {
    console.log('[server] DISCORD_TOKEN nahi mila — Gateway bot OFF. Sirf HTTP interactions chalenge.');
    console.log('         Welcome / leveling / role-based commands ke liye token set karo.');
    return null;
  }
  try {
    gateway = require('./bot');
    gateway.start();
    return gateway;
  } catch (err) {
    console.error('[server] ❌ Gateway bot start nahi ho paya:', err.message);
    gateway = null;
    return null;
  }
}

bootGateway();

/* ------------------------------------------------------------------ */
/*  Body parsing (raw body signature verification ke liye chahiye)      */
/* ------------------------------------------------------------------ */
app.use(
  express.json({
    verify: (req, _res, buf) => {
      req.rawBody = buf;
    },
  })
);

/* ------------------------------------------------------------------ */
/*  Signature verification                                             */
/* ------------------------------------------------------------------ */
function verifySignature(req) {
  if (!PUBLIC_KEY) return true; // dev mode: key set nahi hai to skip

  const signature = req.get('X-Signature-Ed25519');
  const timestamp = req.get('X-Signature-Timestamp');
  if (!signature || !timestamp || !req.rawBody) return false;

  try {
    return nacl.sign.detached.verify(
      Buffer.concat([Buffer.from(timestamp, 'utf8'), req.rawBody]),
      Buffer.from(signature, 'hex'),
      Buffer.from(PUBLIC_KEY, 'hex')
    );
  } catch (err) {
    console.error('[ERROR] Signature verify failed:', err.message);
    return false;
  }
}

const ephemeral = (content) => ({ type: 4, data: { content, flags: 64 } });

/* ------------------------------------------------------------------ */
/*  Discord Interactions endpoint                                      */
/* ------------------------------------------------------------------ */
app.post('/interactions', async (req, res) => {
  if (!verifySignature(req)) {
    return res.status(401).json({ error: 'Invalid request signature' });
  }

  const body = req.body || {};

  // 1) Discord URL-verification PING -> PONG
  if (body.type === 1) {
    console.log('[INFO] Discord PING received — responding PONG');
    return res.json({ type: 1 });
  }

  // 2) Application commands (slash commands)
  if (body.type === 2) {
    const interaction = new HttpInteraction(body);
    const command = registry.map.get(interaction.commandName);

    if (!command) {
      console.warn(`[server] Unknown command "/${interaction.commandName}" — Discord pe register nahi hai?`);
      return res.json(ephemeral(`❓ \`/${interaction.commandName ?? ''}\` ye command mujhe nahi pata. \`/help\` dekho.`));
    }

    if (command.guildOnly && !interaction.guildId) {
      return res.json(ephemeral('⚠️ Ye command sirf server (guild) ke andar chalti hai — DM me nahi.'));
    }

    try {
      await command.execute(interaction);
    } catch (err) {
      console.error(`[server] /${interaction.commandName} error:`, err);
      return res.json(ephemeral(`❌ \`/${interaction.commandName}\` me error aayi: ${err.message}`));
    }

    if (!interaction.response) {
      console.warn(`[server] /${interaction.commandName} ne koi reply nahi bheja — empty ACK ja raha hai`);
      return res.json({ type: 4, data: { content: '✅ Ho gaya.' } });
    }

    return res.json(interaction.response);
  }

  // 3) Message components (buttons / select menus) -> ACK
  if (body.type === 3) {
    return res.json({ type: 6 }); // DEFERRED_UPDATE_MESSAGE
  }

  // 4) Modal submit
  if (body.type === 5) {
    return res.json(ephemeral('📝 Modals abhi is bot me enable nahi hain.'));
  }

  // 5) Kuch aur — generic ACK
  return res.json({});
});

/* ------------------------------------------------------------------ */
/*  Simple pages                                                       */
/* ------------------------------------------------------------------ */
const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const page = (title, body) => `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>
  body{background:#1e1f22;color:#dbdee1;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px}
  .card{background:#2b2d31;border-radius:12px;padding:40px;max-width:640px;box-shadow:0 8px 24px rgba(0,0,.4);width:100%}
  h1{color:#fff;font-size:1.6rem;margin-top:0} a{color:#00a8fc} code{background:#1e1f22;padding:2px 6px;border-radius:4px}
  .ok{color:#23c55e;font-weight:600} .warn{color:#f0b232;font-weight:600} .bad{color:#f23f43;font-weight:600}
  ul{padding-left:20px;line-height:1.9} li code{color:#fff}
  .pill{display:inline-block;background:#1e1f22;border-radius:999px;padding:4px 12px;font-size:.85rem;margin:2px 4px 2px 0}
</style></head>
<body><div class="card">${body}</div></body></html>`;

function gatewayStatus() {
  if (!gateway) return { running: false, ready: false, state: 'off', detail: 'DISCORD_TOKEN set nahi hai' };
  const s = typeof gateway.getStatus === 'function' ? gateway.getStatus() : {};
  return { running: true, ...s };
}

app.get('/', (_req, res) => {
  const gw = gatewayStatus();
  const gwLine = gw.ready
    ? `<p class="ok">● Gateway bot ONLINE — ${escapeHtml(gw.user ?? '')} · ${gw.guilds ?? 0} servers</p>`
    : gw.running
      ? `<p class="warn">● Gateway bot ${escapeHtml(gw.state ?? 'starting')} — ${escapeHtml(gw.detail ?? '')}</p>`
      : `<p class="warn">● Gateway bot OFF — ${escapeHtml(gw.detail ?? '')}</p>`;

  const list = [...registry.map.values()]
    .sort((a, b) => a.data.name.localeCompare(b.data.name))
    .map((c) => `<li><code>${escapeHtml(commandUsage(c))}</code> — ${escapeHtml(c.data.description || '')}</li>`)
    .join('');

  res.send(
    page(
      'Bot Server — Online',
      `<h1>🤖 Discord Bot Server</h1>
       <p class="ok">● HTTP interactions server running</p>
       ${gwLine}
       <p>Interactions endpoint: <code>POST /interactions</code></p>
       <p class="pill">${registry.names.length} commands</p>
       <p class="pill">${PUBLIC_KEY ? '🔐 signature verification ON' : '🔓 signature verification OFF'}</p>
       <h2 style="color:#fff;font-size:1.05rem">Slash commands</h2>
       <ul>${list || '<li>Koi command load nahi hui</li>'}</ul>
       <p><a href="/health">/health</a> · <a href="/commands">/commands</a> ·
          <a href="/terms-of-service">Terms of Service</a> · <a href="/privacy-policy">Privacy Policy</a></p>`
    )
  );
});

app.get('/health', (_req, res) => {
  const gw = gatewayStatus();
  res.json({
    status: 'ok',
    uptime: process.uptime(),
    commands: registry.names,
    commandCount: registry.names.length,
    signatureVerification: !!PUBLIC_KEY,
    gateway: gw,
  });
});

app.get('/commands', (_req, res) => res.json(registry.json));

app.get('/terms-of-service', (_req, res) => {
  res.send(
    page(
      'Terms of Service',
      `<h1>Terms of Service</h1>
       <p>By inviting and using this Discord bot ("the Bot") you agree to these terms.</p>
       <p><strong>1. Usage.</strong> The Bot is provided for community and entertainment purposes. Do not use it to break Discord's Terms of Service or Community Guidelines, or any applicable law.</p>
       <p><strong>2. Availability.</strong> The Bot is provided "as is" without warranty. Features may change or be discontinued at any time.</p>
       <p><strong>3. Liability.</strong> We are not liable for any damages arising from use of the Bot.</p>
       <p><strong>4. Termination.</strong> Access may be revoked for abuse of the Bot.</p>
       <p>Last updated: October 2026</p>`
    )
  );
});

app.get('/privacy-policy', (_req, res) => {
  res.send(
    page(
      'Privacy Policy',
      `<h1>Privacy Policy</h1>
       <p>This Privacy Policy describes how the Discord bot ("the Bot") handles data.</p>
       <p><strong>What we store.</strong> The Bot may temporarily process Discord-provided data such as user IDs, server IDs, usernames and command input, strictly to respond to your commands. No sensitive personal data is collected.</p>
       <p><strong>What we do NOT do.</strong> We do not sell your data, and we do not share it with third parties.</p>
       <p><strong>Retention.</strong> Processed data is kept only as long as needed to operate the Bot's features.</p>
       <p><strong>Contact.</strong> Questions? Reach out via the support server for the Bot.</p>
       <p>Last updated: October 2026</p>`
    )
  );
});

/* ------------------------------------------------------------------ */
process.on('unhandledRejection', (err) => console.error('[server] unhandled rejection:', err?.message ?? err));

const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`✅ Server live on port ${PORT}`);
});

module.exports = { app, server };
