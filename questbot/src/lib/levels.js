/**
 * Level maths — XP se level
 * -------------------------
 * Formula: level = floor(0.1 * sqrt(xp))
 *   L1 = 100 XP, L2 = 400, L3 = 900, L10 = 10000
 */
const levelFromXp = (xp) => Math.floor(0.1 * Math.sqrt(Math.max(0, Number(xp) || 0)));
const xpForLevel = (level) => 100 * Math.max(0, level) ** 2;

/** { level, xp, into, span, percent, next } */
function progress(xp) {
  const total = Math.max(0, Number(xp) || 0);
  const level = levelFromXp(total);
  const current = xpForLevel(level);
  const next = xpForLevel(level + 1);
  const span = next - current || 1;
  const into = total - current;
  return {
    level,
    xp: total,
    into,
    span,
    next,
    percent: Math.min(100, Math.round((into / span) * 100)),
  };
}

/** Text progress bar: ▰▰▰▱▱ */
function bar(percent, size = 8) {
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  const filled = Math.round((p / 100) * size);
  return '▰'.repeat(filled) + '▱'.repeat(size - filled);
}

module.exports = { levelFromXp, xpForLevel, progress, bar };
