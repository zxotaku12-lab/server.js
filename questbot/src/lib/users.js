/**
 * User records — coins, XP, premium, counters
 * -------------------------------------------
 * Store shape (data/quests.json):
 *   {
 *     "users": {
 *       "<guildId>:<userId>": {
 *         coins, xp, premium, premiumSince,
 *         counters: { "d:2026-10-27": {...}, "w:2026-W44": {...}, "life": {...} },
 *         claimed:  { "<questId>:<periodKey>": timestamp },
 *         stats:    { questsDone, streak, lastDailyDay, messages, voiceMinutes }
 *       }
 *     },
 *     "meta": { createdAt }
 *   }
 *
 * Counters teen scope me simultaneously badhte hain, taaki ek hi event se
 * daily, weekly aur one-time quests — sabki progress update ho.
 */
const store = require('./store');
const periods = require('./periods');
const { progress } = require('./levels');

const KEY = 'users';
const MAX_DAY_SCOPES = 14; // 2 hafte ka history — usse purana prune ho jaata hai
const MAX_WEEK_SCOPES = 8;

const keyOf = (guildId, userId) => `${guildId}:${userId}`;

function all() {
  const data = store.load();
  if (!data[KEY] || typeof data[KEY] !== 'object') data[KEY] = {};
  if (!data.meta) data.meta = { createdAt: new Date().toISOString() };
  return data[KEY];
}

function fresh() {
  return {
    coins: 0,
    xp: 0,
    premium: false,
    premiumSince: null,
    counters: {},
    claimed: {},
    stats: {
      questsDone: 0,
      streak: 0,
      lastDailyDay: null,
      messages: 0,
      reactions: 0,
      commands: 0,
      voiceMinutes: 0,
      invites: 0,
      createdAt: new Date().toISOString(),
    },
  };
}

/** Purani counters hatao — warna file saal bhar me bahut badi ho jaayegi */
function prune(user) {
  const dayScopes = Object.keys(user.counters).filter((k) => k.startsWith('d:')).sort();
  while (dayScopes.length > MAX_DAY_SCOPES) delete user.counters[dayScopes.shift()];

  const weekScopes = Object.keys(user.counters).filter((k) => k.startsWith('w:')).sort();
  while (weekScopes.length > MAX_WEEK_SCOPES) delete user.counters[weekScopes.shift()];
}

/** Ek user ka record — na ho to bana do (aur mutate karo, save debounced hai) */
function ensure(guildId, userId) {
  const users = all();
  const key = keyOf(guildId, userId);
  let user = users[key];
  if (!user) user = users[key] = fresh();

  // Purane / adhure records ko normalize karo
  if (!user.counters || typeof user.counters !== 'object') user.counters = {};
  if (!user.claimed || typeof user.claimed !== 'object') user.claimed = {};
  if (!user.stats || typeof user.stats !== 'object') user.stats = fresh().stats;
  if (typeof user.coins !== 'number') user.coins = 0;
  if (typeof user.xp !== 'number') user.xp = 0;
  if (typeof user.premium !== 'boolean') user.premium = false;

  return user;
}

/** Sirf padho — record na bane */
function peek(guildId, userId) {
  return all()[keyOf(guildId, userId)] ?? null;
}

function markDirty() {
  store.markDirty();
}

/** Ek metric bump karo — daily + weekly + lifetime, teeno */
function bump(guildId, userId, metric, amount = 1) {
  if (!guildId || !userId) return null;
  const value = Number(amount);
  if (!Number.isFinite(value) || value <= 0) return null;

  const user = ensure(guildId, userId);
  const dayScope = `d:${periods.dayKey()}`;
  const weekScope = `w:${periods.isoWeek()}`;

  for (const scope of [dayScope, weekScope, 'life']) {
    if (!user.counters[scope]) user.counters[scope] = {};
    user.counters[scope][metric] = (Number(user.counters[scope][metric]) || 0) + value;
  }

  const statKey = metric === 'voice' ? 'voiceMinutes' : metric;
  user.stats[statKey] = (Number(user.stats[statKey]) || 0) + value;

  prune(user);
  markDirty();
  return user;
}

/** Claim/reward ke baad turant save — warna reward kho sakta hai */
function commit() {
  store.flush();
}

/** Premium FREE activate karo (koi payment nahi) */
function grantPremium(guildId, userId, days = 0) {
  const user = ensure(guildId, userId);
  user.premium = true;
  user.premiumSince = user.premiumSince || new Date().toISOString();
  if (days > 0) {
    const base = user.premiumUntil && Date.parse(user.premiumUntil) > Date.now() ? Date.parse(user.premiumUntil) : Date.now();
    user.premiumUntil = new Date(base + days * periods.DAY_MS).toISOString();
  }
  markDirty();
  return user;
}

/** Premium band (admin/testing) */
function revokePremium(guildId, userId) {
  const user = ensure(guildId, userId);
  user.premium = false;
  user.premiumSince = null;
  user.premiumUntil = null;
  markDirty();
  return user;
}

/** Premium abhi valid hai? (expiry support ke saath) */
function isPremium(user) {
  if (!user?.premium) return false;
  if (user.premiumUntil && Date.parse(user.premiumUntil) < Date.now()) return false;
  return true;
}

/** Level info */
function levelOf(user) {
  return progress(user?.xp ?? 0);
}

/** Claimed keys ka set (fast lookup) */
function hasClaimed(user, key) {
  return Boolean(user?.claimed?.[key]);
}

module.exports = {
  keyOf,
  all,
  ensure,
  peek,
  bump,
  commit,
  markDirty,
  grantPremium,
  revokePremium,
  isPremium,
  levelOf,
  hasClaimed,
  fresh,
};
