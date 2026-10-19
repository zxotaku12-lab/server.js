/**
 * XP store helpers — read side
 * ----------------------------
 * XP write bot.js karta hai (har message pe, 60s cooldown). Ye module sirf
 * padhne + leaderboard banane ke liye hai, taaki formula aur sorting ek jagah rahe.
 *
 * Store shape (data/xp.json):
 *   { "<guildId>:<userId>": { "xp": 1234, "username": "name" }, ... }
 */
const { load } = require('../store');
const { levelFromXp, progress } = require('./levels');

const keyOf = (guildId, userId) => `${guildId}:${userId}`;

/** Hamesha disk se fresh padho — bot.js likh raha hota hai */
function readAll() {
  return load('xp');
}

/** Ek member ki entry (na ho to null) */
function getEntry(guildId, userId) {
  const raw = readAll()[keyOf(guildId, userId)];
  if (!raw) return null;
  const xp = Number(raw.xp) || 0;
  return { userId, username: raw.username ?? null, xp, ...progress(xp) };
}

/** Ek guild ka pura board, XP ke hisaab se descending */
function guildBoard(guildId) {
  const all = readAll();
  const prefix = `${guildId}:`;
  return Object.entries(all)
    .filter(([k]) => k.startsWith(prefix))
    .map(([k, v]) => {
      const userId = k.slice(prefix.length);
      const xp = Number(v.xp) || 0;
      return { userId, username: v.username ?? null, xp, level: levelFromXp(xp) };
    })
    .sort((a, b) => b.xp - a.xp || a.userId.localeCompare(b.userId));
}

/** Kisi member ka rank (1-based) aur total tracked members */
function rankOf(guildId, userId) {
  const board = guildBoard(guildId);
  const index = board.findIndex((e) => e.userId === userId);
  return { rank: index === -1 ? null : index + 1, total: board.length };
}

/** Board ke top N */
function leaderboard(guildId, limit = 10) {
  return guildBoard(guildId).slice(0, Math.max(1, limit));
}

module.exports = { keyOf, readAll, getEntry, guildBoard, rankOf, leaderboard };
