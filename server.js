/**
 * Discord HTTP Interactions Server
 * ---------------------------------
 * Routes:
 *   POST /interactions       -> Discord interactions endpoint (PING + slash commands)
 *   GET  /                   -> Status page
 *   GET  /health             -> Health check JSON
 *   GET  /terms-of-service   -> Terms of Service page
 *   GET  /privacy-policy     -> Privacy Policy page
 *
 * Required env (optional but recommended):
 *   DISCORD_PUBLIC_KEY - Discord Developer Portal -> General Information -> Public Key
 *                        (set karne par signature verification ON ho jayegi - recommended!)
 *   PORT               - Render khud set karta hai
 */

const express = require('express');
const nacl = require('tweetnacl');

const app = express();
const PORT = process.env.PORT || 3000;

const PUBLIC_KEY = (process.env.DISCORD_PUBLIC_KEY || '').trim();
if (!PUBLIC_KEY) {
  console.warn('[WARN] DISCORD_PUBLIC_KEY set nahi hai — signature verification skip ho rahi hai.');
  console.warn('       Render Dashboard -> Environment -> Discord Public Key add karo (recommended).');
}

// Raw body save karna hai signature verification ke liye
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

/* ------------------------------------------------------------------ */
/*  Discord Interactions endpoint                                      */
/* ------------------------------------------------------------------ */
app.post('/interactions', (req, res) => {
  if (!verifySignature(req)) {
    return res.status(401).json({ error: 'Invalid request signature' });
  }

  const interaction = req.body;

  // 1) Discord URL-verification PING -> PONG
  if (interaction.type === 1) {
    console.log('[INFO] Discord PING received — responding PONG');
    return res.json({ type: 1 });
  }

  // 2) Slash commands (type 2)
  if (interaction.type === 2) {
    const name = interaction.data?.name?.toLowerCase();

    switch (name) {
      case 'ping':
        return res.json({
          type: 4,
          data: { content: '🏓 Pong! Bot is alive ✅' },
        });

      case 'hello':
        return res.json({
          type: 4,
          data: {
            content: `👋 Namaste, <@${interaction.member?.user?.id || interaction.user?.id || 'dost'}>!`,
          },
        });

      case 'help':
        return res.json({
          type: 4,
          data: {
            embeds: [
              {
                title: '📖 Commands',
                description: '`/ping` — Bot alive check\n`/hello` — Bot greets you\n`/help` — Ye message',
                color: 0x5865f2,
              },
            ],
          },
        });

      default:
        return res.json({
          type: 4,
          data: { content: 'Ye command abhi handle nahi hui 😅' },
        });
    }
  }

  // 3) Message components (buttons etc.) -> simple ACK
  if (interaction.type === 3) {
    return res.json({ type: 6 });
  }

  // 4) Kuch aur — generic ACK
  return res.json({});
});

/* ------------------------------------------------------------------ */
/*  Simple pages                                                       */
/* ------------------------------------------------------------------ */
const page = (title, body) => `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>
  body{background:#1e1f22;color:#dbdee1;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;
       display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
  .card{background:#2b2d31;border-radius:12px;padding:40px;max-width:640px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
  h1{color:#fff;font-size:1.6rem;margin-top:0} a{color:#00a8fc}
  .ok{color:#23c55e;font-weight:600}
</style></head>
<body><div class="card">${body}</div></body></html>`;

app.get('/', (_req, res) => {
  res.send(
    page(
      'Bot Server — Online',
      `<h1>🤖 Discord Bot Server</h1>
       <p class="ok">● Server is running</p>
       <p>Interactions endpoint: <code>POST /interactions</code></p>
       <p><a href="/terms-of-service">Terms of Service</a> · <a href="/privacy-policy">Privacy Policy</a></p>`
    )
  );
});

app.get('/health', (_req, res) => res.json({ status: 'ok', uptime: process.uptime() }));

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
app.listen(PORT, '0.0.0.0', () => {
  console.log(`✅ Server live on port ${PORT}`);
});
