/**
 * Bot manager — token se bot start/stop/restart
 * ---------------------------------------------
 * Dashboard se token paste karte ho -> yahan aata hai -> discord.js login.
 * Env DISCORD_TOKEN ho to wahi jeetta hai (dashboard token optional).
 *
 * Bot ready hone par slash commands register ho jaati hain (GUILD_ID ho to
 * turant, warna global — global me ~1 ghanta lagta hai).
 */
const { Client, GatewayIntentBits, Partials, Events, ActivityType } = require('discord.js');
const commands = require('../commands');
const access = require('./access');

let client = null;
let started = false;
let lastError = null;
let readyAt = null;
let registeredAt = null;
let loginStartedAt = null;

function tokenInUse() {
  return (process.env.DISCORD_TOKEN || '').trim() || access.savedToken() || '';
}

/** Commands register karo — GUILD_ID ho to instant */
async function registerCommands(c) {
  if (!c.application) return { mode: 'none', count: 0 };
  const json = commands.json();
  const guildId = (process.env.GUILD_ID || '').trim();

  try {
    if (guildId) {
      const guild = await c.guilds.fetch(guildId).catch(() => null);
      if (guild) {
        await guild.commands.set(json);
        registeredAt = Date.now();
        console.log(`[bot] ${json.length} commands guild "${guild.name}" me register ho gayi ✅`);
        return { mode: 'guild', count: json.length };
      }
      console.warn(`[bot] GUILD_ID "${guildId}" nahi mila — global register kar raha hoon`);
    }
    await c.application.commands.set(json);
    registeredAt = Date.now();
    console.log(`[bot] ${json.length} commands GLOBALLY register ho gayi (1 ghanta lag sakta hai)`);
    return { mode: 'global', count: json.length };
  } catch (err) {
    console.error('[bot] command register fail:', err.message);
    return { mode: 'error', count: 0, error: err.message };
  }
}

/** Bot start karo (token optional — na do to env/saved se) */
function start(token) {
  if (started) return { ok: true, already: true, state: getStatus() };

  const finalToken = (token || '').trim() || tokenInUse();
  if (!finalToken) {
    return { ok: false, error: 'Token nahi mila. Dashboard me paste karo ya DISCORD_TOKEN env set karo.' };
  }
  if (token) access.saveToken(finalToken);

  lastError = null;
  loginStartedAt = Date.now();

  client = new Client({
    intents: [
      GatewayIntentBits.Guilds,
      GatewayIntentBits.GuildMembers,
      GatewayIntentBits.GuildMessages,
      GatewayIntentBits.GuildMessageReactions,
      GatewayIntentBits.GuildVoiceStates,
    ],
    partials: [Partials.GuildMember, Partials.Message, Partials.Reaction, Partials.Channel],
  });

  require('../events')(client);
  started = true;

  client.once(Events.ClientReady, (c) => {
    readyAt = Date.now();
    c.user.setActivity('quests | /quest', { type: ActivityType.Watching });
    console.log(`[bot] ✅ ${c.user.tag} live — ${c.guilds.cache.size} servers`);
    registerCommands(c);
  });

  client.login(finalToken).catch((err) => {
    started = false;
    readyAt = null;
    lastError = err?.message ?? String(err);
    console.error('[bot] ❌ login fail:', lastError);

    const msg = lastError.toLowerCase();
    if (msg.includes('disallowed intents')) {
      console.error('[bot] 👉 FIX: Developer Portal → Bot → Privileged Gateway Intents ON karo (SERVER MEMBERS + MESSAGE CONTENT + GUILD MEMBERS).');
    } else if (msg.includes('token') || msg.includes('401') || msg.includes('unauthorized')) {
      console.error('[bot] 👉 Token galat/expired hai — Developer Portal → Bot → Reset Token se naya lo.');
    }
  });

  return { ok: true, state: getStatus() };
}

/** Bot band karo */
function stop() {
  if (!client) return { ok: true, already: true };
  try {
    client.destroy();
  } catch {
    /* ignore */
  }
  client = null;
  started = false;
  readyAt = null;
  loginStartedAt = null;
  return { ok: true, state: getStatus() };
}

/** Restart — naya token dene ke liye */
function restart(token) {
  stop();
  return start(token);
}

function getStatus() {
  const ready = Boolean(client?.isReady?.());
  return {
    started,
    ready,
    state: ready ? 'ready' : started ? (lastError ? 'error' : 'connecting') : lastError ? 'error' : 'off',
    error: lastError,
    tag: client?.user?.tag ?? null,
    guilds: client?.guilds?.cache?.size ?? 0,
    ping: client?.ws?.ping ?? null,
    commands: commands.names().length,
    readyAt,
    registeredAt,
    loginStartedAt,
    hasToken: Boolean(tokenInUse()),
    tokenSource: (process.env.DISCORD_TOKEN || '').trim() ? 'env' : access.savedToken() ? 'dashboard' : null,
  };
}

/** Dashboard se quests ke liye guild list */
function guildList() {
  if (!client?.isReady?.()) return [];
  return [...client.guilds.cache.values()].map((g) => ({
    id: g.id,
    name: g.name,
    members: g.memberCount ?? 0,
    icon: g.iconURL?.({ size: 64 }) ?? null,
  }));
}

/** Dashboard se member dhundho (premium grant ke liye) */
async function findMember(guildId, query) {
  if (!client?.isReady?.()) return null;
  const guild = client.guilds.cache.get(guildId) ?? (await client.guilds.fetch(guildId).catch(() => null));
  if (!guild) return null;

  const q = String(query ?? '').trim().replace(/[<@!>]/g, '');
  if (!q) return null;

  if (/^\d{17,20}$/.test(q)) {
    const member = await guild.members.fetch(q).catch(() => null);
    if (member) return { id: member.id, username: member.user.username, displayName: member.displayName };
  }

  const found = await guild.members.search({ query: q, limit: 1 }).catch(() => null);
  const member = found?.first?.() ?? null;
  return member ? { id: member.id, username: member.user.username, displayName: member.displayName } : null;
}

/** Commands dobara register karo */
function reregister() {
  if (!client?.isReady?.()) return Promise.resolve({ mode: 'offline', count: 0 });
  return registerCommands(client);
}

module.exports = { start, stop, restart, getStatus, guildList, findMember, reregister, client: () => client, tokenInUse };
