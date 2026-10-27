#!/usr/bin/env node
/**
 * Slash commands ko Discord pe register karo — BINA bot online kiye
 * ---------------------------------------------------------------
 * Developer Portal me commands "add" karne ka koi option nahi hota.
 * Discord me commands sirf API se register hoti hain. Normally bot khud
 * register karta hai, par agar bot abhi chal nahi raha to ye script kaafi hai.
 *
 * Usage:
 *   DISCORD_TOKEN=xxxx node scripts/register.js            # global (~1 ghanta)
 *   DISCORD_TOKEN=xxxx GUILD_ID=1234 node scripts/register.js   # us server me turant
 *
 * Token dashboard se save kiya ho to sirf `node scripts/register.js` bhi chalta hai.
 */
const commands = require('../src/commands');

const API = 'https://discord.com/api/v10';

/** Bot token ke pehle hisse me application ID hoti hai (base64url) */
function appIdFromToken(token) {
  try {
    const first = String(token).split('.')[0];
    const decoded = Buffer.from(first.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
    return /^\d{17,20}$/.test(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

/** Command definitions — Discord ko yahi chahiye */
function buildPayload() {
  const json = commands.json();
  if (!Array.isArray(json) || !json.length) throw new Error('Koi command load nahi hui.');
  for (const cmd of json) {
    if (!cmd.name || !cmd.description) throw new Error(`Command invalid: ${JSON.stringify(cmd).slice(0, 80)}`);
    if (cmd.name !== cmd.name.toLowerCase()) throw new Error(`Command name lowercase hona chahiye: ${cmd.name}`);
    if (cmd.description.length > 100) throw new Error(`/${cmd.name} ki description 100 chars se badi hai.`);
  }
  return json;
}

/** Register call (global ya guild) */
function endpoint(appId, guildId) {
  return guildId
    ? `${API}/applications/${appId}/guilds/${guildId}/commands`
    : `${API}/applications/${appId}/commands`;
}

async function fetchAppId(token) {
  const fromToken = appIdFromToken(token);
  if (fromToken) return fromToken;

  const res = await fetch(`${API}/applications/@me`, {
    headers: { Authorization: `Bot ${token}` },
  });
  if (!res.ok) return null;
  const data = await res.json().catch(() => null);
  return data?.id ?? null;
}

function friendlyError(status, body) {
  if (status === 401) return '❌ Token galat/expired hai — Developer Portal → Bot → Reset Token se naya lo.';
  if (status === 403) {
    return (
      '❌ 403 — bot ke paas `applications.commands` scope nahi hai.\n' +
      '   Dashboard ke invite link se bot ko dobara add karo (usme ye scope hota hai).'
    );
  }
  if (status === 429) return '⏳ Rate limited — 1-2 minute baad dobara try karo.';
  return `❌ Register fail (HTTP ${status}): ${typeof body === 'string' ? body : JSON.stringify(body)}`;
}

async function register({ token, guildId, json = buildPayload(), log = console.log } = {}) {
  if (!token) throw new Error('Token nahi mila — DISCORD_TOKEN env set karo ya dashboard se bot link karo.');

  const appId = await fetchAppId(token);
  if (!appId) throw new Error('Application ID nahi mili — token check karo.');

  const url = endpoint(appId, guildId);
  log(`📡 ${json.length} commands register ho rahi hain → ${guildId ? `guild ${guildId}` : 'GLOBAL'} (app ${appId})`);

  const res = await fetch(url, {
    method: 'PUT',
    headers: { Authorization: `Bot ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(json),
  });

  const text = await res.text();
  let data = null;
  try {
    data = JSON.parse(text);
  } catch {
    /* non-json */
  }

  if (!res.ok) throw new Error(friendlyError(res.status, text.slice(0, 200)));

  const names = (Array.isArray(data) ? data : []).map((c) => `/${c.name}`);
  return { appId, guildId: guildId || null, count: names.length, names, mode: guildId ? 'guild' : 'global' };
}

/* ---------------- CLI ---------------- */
async function main() {
  process.env.QUEST_DATA_DIR = process.env.QUEST_DATA_DIR || undefined;

  let token = (process.env.DISCORD_TOKEN || '').trim();
  if (!token) {
    try {
      token = require('../src/lib/access').savedToken() || '';
    } catch {
      token = '';
    }
  }

  const guildId = (process.env.GUILD_ID || '').trim() || null;

  try {
    const result = await register({ token, guildId });
    console.log(`\n✅ ${result.count} commands register ho gayi (${result.mode}):`);
    console.log('   ' + result.names.join(' · '));
    if (result.mode === 'global') {
      console.log('\n⏳ Global commands Discord me ~1 ghante me dikhti hain.');
      console.log('   Turant chahiye? GUILD_ID set karke dobara chalao.');
    } else {
      console.log('\n⚡ Ye commands us server me TURANT dikhengi (Discord app restart karna).');
    }
    process.exit(0);
  } catch (err) {
    console.error(`\n${err.message}`);
    process.exit(1);
  }
}

module.exports = { appIdFromToken, buildPayload, endpoint, register, friendlyError };

if (require.main === module) main();
