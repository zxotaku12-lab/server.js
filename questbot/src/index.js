/**
 * Quest Bot — server + dashboard
 * ------------------------------
 * Ek hi process me:
 *   1. Discord bot (token paste karte ho dashboard se, ya DISCORD_TOKEN env se)
 *   2. Web dashboard (login karke control karo, access keys bana ke kisi ko bhi do)
 *
 * Routes:
 *   GET  /                     -> dashboard (login page bhi wahi)
 *   POST /api/login            -> password ya access key se login
 *   POST /api/logout
 *   GET  /api/me               -> session + permissions
 *   GET  /api/status           -> bot status
 *   POST /api/bot/start        -> admin: { token }
 *   POST /api/bot/stop         -> admin
 *   POST /api/bot/restart      -> admin: { token }
 *   GET  /api/guilds           -> bot ke servers
 *   GET  /api/quests           -> quest catalog
 *   GET  /api/stats            -> totals + leaderboard
 *   POST /api/premium          -> admin: { guildId, query }
 *   POST /api/premium/revoke   -> admin: { guildId, userId }
 *   GET  /api/access           -> owner: keys list
 *   POST /api/access           -> owner: naya key banao
 *   PATCH/DELETE /api/access/:id -> owner: on/off ya revoke
 */
require('../src/lib/env').loadEnv();

const path = require('path');
const express = require('express');

const access = require('./lib/access');
const bot = require('./lib/bot');
const users = require('./lib/users');
const quests = require('./lib/quests');
const periods = require('./lib/periods');
const settings = require('./lib/settings');

const app = express();
const PORT = Number(process.env.PORT) || 3000;
const PUBLIC_DIR = path.join(__dirname, '..', 'public');

app.disable('x-powered-by');
app.use(express.json({ limit: '32kb' }));

/* ------------------------------------------------------------------ */
/*  Session helpers                                                    */
/* ------------------------------------------------------------------ */
const COOKIE = 'qb_session';

function parseCookies(header = '') {
  const out = {};
  for (const part of String(header).split(';')) {
    const idx = part.indexOf('=');
    if (idx < 0) continue;
    const key = part.slice(0, idx).trim();
    const value = part.slice(idx + 1).trim();
    if (key) out[key] = decodeURIComponent(value);
  }
  return out;
}

function isHttps(req) {
  return req.secure || String(req.get('x-forwarded-proto') || '').split(',')[0].trim() === 'https';
}

function setSessionCookie(req, res, token) {
  const bits = [`${COOKIE}=${encodeURIComponent(token)}`, 'Path=/', 'HttpOnly', 'SameSite=Lax', `Max-Age=${Math.floor(access.SESSION_TTL_MS / 1000)}`];
  if (isHttps(req)) bits.push('Secure');
  res.setHeader('Set-Cookie', bits.join('; '));
}

function clearSessionCookie(req, res) {
  res.setHeader('Set-Cookie', `${COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`);
}

/** Har request par session resolve karo */
app.use((req, _res, next) => {
  const token = parseCookies(req.headers.cookie)[COOKIE];
  req.session = access.sessionFromToken(token);
  req.sessionToken = token ?? null;
  next();
});

/** Auth guard */
function requireAuth(req, res, next) {
  if (!req.session) return res.status(401).json({ error: 'Login karo pehle.' });
  next();
}

/** Role guard */
function requireRole(action) {
  return (req, res, next) => {
    if (!req.session) return res.status(401).json({ error: 'Login karo pehle.' });
    if (!access.can(req.session.role, action)) {
      return res.status(403).json({ error: `Iske liye "${req.session.role}" role kaafi nahi hai.` });
    }
    next();
  };
}

/* ------------------------------------------------------------------ */
/*  Login rate limit (brute-force se bachne ke liye)                   */
/* ------------------------------------------------------------------ */
const attempts = new Map(); // ip -> { count, since }
const MAX_ATTEMPTS = 12;
const ATTEMPT_WINDOW_MS = 10 * 60_000;

function tooManyAttempts(ip) {
  const entry = attempts.get(ip);
  if (!entry) return false;
  if (Date.now() - entry.since > ATTEMPT_WINDOW_MS) {
    attempts.delete(ip);
    return false;
  }
  return entry.count >= MAX_ATTEMPTS;
}

function noteAttempt(ip) {
  const entry = attempts.get(ip);
  if (!entry || Date.now() - entry.since > ATTEMPT_WINDOW_MS) attempts.set(ip, { count: 1, since: Date.now() });
  else entry.count += 1;
}

/* ------------------------------------------------------------------ */
/*  Auth routes                                                        */
/* ------------------------------------------------------------------ */
app.post('/api/login', (req, res) => {
  const ip = req.ip ?? 'unknown';
  if (tooManyAttempts(ip)) {
    return res.status(429).json({ error: 'Bahut zyada attempts — 10 minute baad try karo.' });
  }

  const session = access.authenticate(req.body?.key, { ip });
  if (!session) {
    noteAttempt(ip);
    return res.status(401).json({ error: 'Password/key galat hai.' });
  }

  attempts.delete(ip);
  setSessionCookie(req, res, session.token);
  return res.json({
    ok: true,
    role: session.role,
    label: session.label,
    permissions: {
      view: access.can(session.role, 'view'),
      controlBot: access.can(session.role, 'bot.control'),
      manageAccess: access.can(session.role, 'access.manage'),
      grantPremium: access.can(session.role, 'premium.grant'),
    },
  });
});

app.post('/api/logout', (req, res) => {
  if (req.sessionToken) access.logout(req.sessionToken);
  clearSessionCookie(req, res);
  res.json({ ok: true });
});

app.get('/api/me', (req, res) => {
  if (!req.session) return res.status(401).json({ loggedIn: false });
  res.json({
    loggedIn: true,
    role: req.session.role,
    label: req.session.label,
    expiresAt: req.session.createdAt + access.SESSION_TTL_MS,
    permissions: {
      view: access.can(req.session.role, 'view'),
      controlBot: access.can(req.session.role, 'bot.control'),
      manageAccess: access.can(req.session.role, 'access.manage'),
      grantPremium: access.can(req.session.role, 'premium.grant'),
    },
  });
});

/* ------------------------------------------------------------------ */
/*  Bot control                                                        */
/* ------------------------------------------------------------------ */
app.get('/api/status', requireAuth, (req, res) => {
  res.json({
    bot: bot.getStatus(),
    commands: require('./commands').names(),
    uptime: Math.floor(process.uptime()),
    now: Date.now(),
    resets: {
      daily: periods.nextReset(new Date(), 'daily'),
      weekly: periods.nextReset(new Date(), 'weekly'),
    },
    premium: { free: true, multiplier: quests.PREMIUM_MULTIPLIER, extraDaily: quests.PREMIUM_PER_DAY },
    settings: settings.get(),
  });
});

app.post('/api/bot/start', requireRole('bot.control'), (req, res) => {
  const result = bot.start(req.body?.token);
  res.status(result.ok ? 200 : 400).json(result);
});

app.post('/api/bot/stop', requireRole('bot.control'), (_req, res) => {
  res.json(bot.stop());
});

app.post('/api/bot/restart', requireRole('bot.control'), (req, res) => {
  res.json(bot.restart(req.body?.token));
});

app.get('/api/guilds', requireAuth, (_req, res) => {
  res.json({ guilds: bot.guildList(), bot: bot.getStatus() });
});

/* ------------------------------------------------------------------ */
/*  Settings — ⚡ Unlimited mode                                       */
/* ------------------------------------------------------------------ */
app.get('/api/settings', requireAuth, (_req, res) => {
  res.json(settings.get());
});

app.post('/api/settings', requireRole('settings.manage'), (req, res) => {
  const body = req.body ?? {};
  const patch = {};
  if ('unlimited' in body) patch.unlimited = Boolean(body.unlimited);

  const updated = settings.set(patch);
  res.json({ ok: true, ...updated });
});

/** Bot invite link — isme `applications.commands` scope hai (iske bina commands dikhti nahi) */
app.get('/api/bot/invite', requireAuth, (_req, res) => {
  const url = bot.inviteUrl();
  if (!url) {
    return res.status(400).json({
      error: 'Invite link nahi ban sakti — pehle bot ko token se link karo, ya CLIENT_ID env set karo.',
    });
  }
  res.json({ url, permissions: bot.INVITE_PERMISSIONS, clientId: bot.clientId() });
});

/** Commands ko bot se "connect" karo — slash commands register */
app.post('/api/bot/register', requireRole('bot.control'), async (_req, res) => {
  const result = await bot.reregister();
  if (!result.ok) return res.status(409).json(result);
  res.json({ ok: true, ...result, commands: bot.getStatus().commandNames });
});

/* ------------------------------------------------------------------ */
/*  Quests + stats (dashboard)                                         */
/* ------------------------------------------------------------------ */
app.get('/api/quests', requireAuth, (req, res) => {
  const guildId = String(req.query.guildId || '');
  const catalog = quests.catalog();

  const today = quests.dailyQuests();
  const week = quests.weeklyQuests();

  res.json({
    catalog,
    today,
    week,
    oneTime: quests.oneTimeQuests(),
    resets: {
      daily: periods.nextReset(new Date(), 'daily'),
      weekly: periods.nextReset(new Date(), 'weekly'),
    },
    guildId: guildId || null,
  });
});

app.get('/api/stats', requireAuth, (req, res) => {
  const all = users.all();
  const guildId = String(req.query.guildId || '');

  const rows = Object.entries(all)
    .filter(([key]) => !guildId || key.startsWith(`${guildId}:`))
    .map(([key, user]) => {
      const [gid, uid] = key.split(':');
      const lvl = users.levelOf(user);
      return {
        key,
        guildId: gid,
        userId: uid,
        coins: Number(user.coins) || 0,
        xp: Number(user.xp) || 0,
        level: lvl.level,
        premium: users.isPremium(user),
        questsDone: Number(user.stats?.questsDone) || 0,
        streak: Number(user.stats?.streak) || 0,
        messages: Number(user.stats?.messages) || 0,
        voiceMinutes: Number(user.stats?.voiceMinutes) || 0,
      };
    })
    .sort((a, b) => b.questsDone - a.questsDone || b.coins - a.coins);

  res.json({
    totalPlayers: rows.length,
    totalClaims: rows.reduce((sum, row) => sum + row.questsDone, 0),
    totalCoins: rows.reduce((sum, row) => sum + row.coins, 0),
    premiumPlayers: rows.filter((row) => row.premium).length,
    top: rows.slice(0, 25),
  });
});

/** Premium grant — bilkul free, koi payment nahi */
app.post('/api/premium', requireRole('premium.grant'), async (req, res) => {
  const guildId = String(req.body?.guildId || '');
  const query = String(req.body?.query || '').trim();
  if (!guildId || !query) return res.status(400).json({ error: 'guildId aur query (user id ya naam) chahiye.' });

  const found = await bot.findMember(guildId, query).catch(() => null);
  const userId = found?.id ?? query;
  if (!/^\d{17,20}$/.test(userId)) {
    return res.status(404).json({ error: 'Member nahi mila. User ID daalo (Discord me right-click → Copy ID).' });
  }

  const user = users.grantPremium(guildId, userId, Number(req.body?.days) || 0);
  users.commit();

  res.json({
    ok: true,
    userId,
    username: found?.username ?? null,
    premium: true,
    premiumUntil: user.premiumUntil ?? null,
    note: 'Premium free hai — koi payment nahi.',
  });
});

app.post('/api/premium/revoke', requireRole('premium.grant'), (req, res) => {
  const guildId = String(req.body?.guildId || '');
  const userId = String(req.body?.userId || '');
  if (!guildId || !userId) return res.status(400).json({ error: 'guildId aur userId chahiye.' });
  users.revokePremium(guildId, userId);
  users.commit();
  res.json({ ok: true });
});

/* ------------------------------------------------------------------ */
/*  Access keys — "kisko access du?"                                   */
/* ------------------------------------------------------------------ */
app.get('/api/access', requireRole('access.manage'), (_req, res) => {
  res.json({ keys: access.listKeys() });
});

app.post('/api/access', requireRole('access.manage'), (req, res) => {
  const entry = access.createKey({
    label: req.body?.label,
    role: req.body?.role,
  });
  // Key ka poora value sirf ek baar — copy kar lo
  res.json({ ok: true, key: entry.key, entry: { ...entry, key: undefined } });
});

app.patch('/api/access/:id', requireRole('access.manage'), (req, res) => {
  const ok = access.setKeyEnabled(req.params.id, req.body?.enabled);
  if (!ok) return res.status(404).json({ error: 'Key nahi mili.' });
  res.json({ ok: true });
});

app.delete('/api/access/:id', requireRole('access.manage'), (req, res) => {
  const ok = access.revokeKey(req.params.id);
  if (!ok) return res.status(404).json({ error: 'Key nahi mili.' });
  res.json({ ok: true });
});

/* ------------------------------------------------------------------ */
/*  Health + static dashboard                                          */
/* ------------------------------------------------------------------ */
app.get('/health', (_req, res) => {
  const status = bot.getStatus();
  res.json({
    status: 'ok',
    uptime: Math.floor(process.uptime()),
    bot: { state: status.state, ready: status.ready, guilds: status.guilds },
  });
});

app.use(express.static(PUBLIC_DIR, { extensions: ['html'] }));

app.use((err, _req, res, _next) => {
  console.error('[server] error:', err?.message ?? err);
  res.status(500).json({ error: 'Server error' });
});

/* ------------------------------------------------------------------ */
/*  Boot                                                               */
/* ------------------------------------------------------------------ */
const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`[server] Dashboard live: http://0.0.0.0:${PORT}`);
  access.ownerPassword(); // pehli baar password generate + log

  const status = bot.getStatus();
  if (status.hasToken) {
    console.log(`[server] Bot token mila (${status.tokenSource}) — start kar raha hoon…`);
    bot.start();
  } else {
    console.log('[server] Token nahi hai — dashboard kholo aur token paste karo.');
  }
});

module.exports = { app, server };
