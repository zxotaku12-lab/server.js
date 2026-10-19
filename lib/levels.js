/**
 * Leveling maths — ek hi jagah, taaki bot.js (level-up announce) aur
 * commands/level.js (/rank, /leaderboard) kabhi aapas me disagree na karein.
 *
 * Formula:  level = floor(0.1 * sqrt(xp))
 *   -> level L ke liye zaroori XP = (10 * L)^2 = 100 * L^2
 *      L0 = 0, L1 = 100, L2 = 400, L3 = 900, L10 = 10000
 */

/** XP se level */
const levelFromXp = (xp) => Math.floor(0.1 * Math.sqrt(Math.max(0, Number(xp) || 0)));

/** Kisi level tak pahunchne ke liye chahiye total XP */
const xpForLevel = (level) => 100 * Math.max(0, level) ** 2;

/**
 * Progress detail — /rank ke progress bar ke liye.
 * @param {number} xp
 * @returns {{level:number, current:number, next:number, into:number, span:number, percent:number}}
 */
function progress(xp) {
  const total = Math.max(0, Number(xp) || 0);
  const level = levelFromXp(total);
  const current = xpForLevel(level);
  const next = xpForLevel(level + 1);
  const into = total - current;
  const span = next - current || 1;
  return { level, current, next, into, span, percent: Math.min(100, Math.round((into / span) * 100)) };
}

/** Text progress bar: ▰▰▰▰▱▱▱▱▱▱ */
function bar(percent, size = 10) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  const filled = Math.round((p / 100) * size);
  return '▰'.repeat(filled) + '▱'.repeat(size - filled);
}

module.exports = { levelFromXp, xpForLevel, progress, bar };
