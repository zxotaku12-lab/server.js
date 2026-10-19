/**
 * Shared settings store (guild-level config)
 * ------------------------------------------
 * Pehle ye cache bot.js ke andar tha. Problem: agar koi command seedha store.js se
 * likhti, to bot.js ka in-memory cache STALE reh jaata aur welcome/auto-role/logs
 * kabhi update na hote. Isliye ab cache YAHAN hai — bot.js aur commands dono isi ko
 * use karte hain, aur likhne par cache turant update hota hai.
 *
 * Keys jo abhi use hoti hain:
 *   welcomeChannelId  - naya member aane par message kahan jaaye
 *   memberRoleId      - join par automatically kaunsa role de
 *   logChannelId      - join/leave + moderation actions ka log
 */
const { load, save } = require('../store');

const KEY = 'settings';
let cache = null;

/** Pura settings object (saare guilds) */
function all() {
  if (!cache) cache = load(KEY);
  return cache;
}

/** Ek guild ki settings (na ho to khaali object) */
function get(guildId) {
  return all()[guildId] || {};
}

/** Ek ya zyada keys set karo */
function set(guildId, patch) {
  const data = all();
  data[guildId] = { ...(data[guildId] || {}), ...patch };
  save(KEY, data);
  return data[guildId];
}

/** Ek ya zyada keys hata do (setting "off" karne ke liye) */
function unset(guildId, keys) {
  const data = all();
  const current = { ...(data[guildId] || {}) };
  for (const k of [].concat(keys)) delete current[k];
  if (Object.keys(current).length) data[guildId] = current;
  else delete data[guildId];
  save(KEY, data);
  return data[guildId] || {};
}

/** Cache phenk do — bahar se file change ho gayi ho to */
function invalidate() {
  cache = null;
}

module.exports = { all, get, set, unset, invalidate };
