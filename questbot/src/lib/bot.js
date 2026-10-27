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
let lastRegister = { at: null, mode: 'none', count: 0, error: null };

/** Bot ko invite karne ke liye permissions: ViewChannel + SendMessages + EmbedLinks
 *  + ReadMessageHistory + AddReactions (+ UseExternalEmojis) */
const INVITE_PERMISSIONS = String(1024 + 2048 + 16384 + 65536 + 64 + 262144);

function tokenInUse() {
  return (process.env.DISCORD_TOKEN || '').trim() || access.savedToken() || '';
}

/** Application (client) ID — invite link banane ke liye */
function clientId() {
  return client?.application?.id ?? client?.user?.id ?? ((process.env.CLIENT_ID || '').trim() || null);
}

/**
 * Bot invite link — Discord me bot ko add karne ke liye.
 * Isme `applications.commands` scope hai; iske bina slash commands kabhi
 * register ho jaati hain par server me DIKHTI nahi hain.
 */
function inviteUrl() {
  const id = clientId();
  if (!id) return null;
  const params = new URLSearchParams({
    client_id: id,
    scope: 'bot applications.commands',
    permissions: INVITE_PERMISSIONS,
  });
  return `https://discord.com/oauth2/authorize?${params.toString()}`;
}


/** Commands register karo — GUILD_ID ho to instant, warna global.
 *  Ek baar fail ho to 1.5s baad ek retry (transient network errors ke liye). */
async function registerCommands(c, attempt = 1) {
  if (!c?.application) {
    lastRegister = { at: Date.now(), mode: 'none', count: 0, error: 'Application available nahi hai' };
    return lastRegister;
  }
  const json = commands.json();
  const guildId = (process.env.GUILD_ID || '').trim();

  try {
    if (guildId) {
      const guild = await c.guilds.fetch(guildId).catch(() => null);
      if (guild) {
        await guild.commands.set(json);
        registeredAt = Date.now();
        lastRegister = { at: registeredAt, mode: 'guild', count: json.length, guild: guild.name, error: null };
        console.log(`[bot] ${json.length} commands guild "${guild.name}" me register ho gayi ✅`);
        return lastRegister;
      }
      console.warn(`[bot] GUILD_ID "${guildId}" nahi mila — global register kar raha hoon`);
    }
    await c.application.commands.set(json);
    registeredAt = Date.now();
    lastRegister = { at: registeredAt, mode: 'global', count: json.length, error: null };
    console.log(`[bot] ${json.length} commands GLOBALLY register ho gayi (1 ghanta lag sakta hai)`);
    return lastRegister;
  } catch (err) {
    if (attempt < 2) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      return registerCommands(c, attempt + 1);
    }
    console.error('[bot] command register fail:', err.message);
    lastRegister = { at: Date.now(), mode: 'error', count: 0, error: err.message };
    return lastRegister;
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
    clientId: clientId(),
    guilds: client?.guilds?.cache?.size ?? 0,
    ping: client?.ws?.ping ?? null,
    commands: commands.names().length,
    commandNames: commands.names(),
    register: {
      ...lastRegister,
      // ready hone ke baad register automatic chalta hai — UI ko pata rahe
      needsRegister: Boolean(ready && !lastRegister.at),
    },
    inviteUrl: inviteUrl(),
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

/** Commands dobara register karo (dashboard ke button se) */
async function reregister() {
  if (!client?.isReady?.()) {
    return { ok: false, mode: 'offline', count: 0, error: 'Bot online nahi hai — pehle token se link karo.' };
  }
  const result = await registerCommands(client);
  return { ok: result.mode !== 'error' && result.mode !== 'none', ...result };
}

module.exports = {
  start,
  stop,
  restart,
  getStatus,
  guildList,
  findMember,
  reregister,
  inviteUrl,
  clientId,
  INVITE_PERMISSIONS,
  client: () => client,
  tokenInUse,
};
