/**
 * Time helpers — din aur hafte ke keys
 * ------------------------------------
 * Sab kuch UTC pe chalta hai (Discord ke saath consistent):
 *   dayKey(date)   -> "2026-10-27"
 *   isoWeek(date)  -> "2026-W44"
 *
 * Daily quests UTC midnight pe reset hoti hain (India me subah 5:30 baje),
 * weekly quests Monday UTC midnight pe (India me Monday 5:30 AM).
 */
const DAY_MS = 86_400_000;

function toDate(date) {
  return date instanceof Date ? date : new Date(date ?? Date.now());
}

/** "YYYY-MM-DD" */
function dayKey(date = new Date()) {
  return toDate(date).toISOString().slice(0, 10);
}

/** Day number since epoch — rotation seed ke liye */
function dayIndex(date = new Date()) {
  const d = toDate(date);
  const midnight = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  return Math.floor(midnight / DAY_MS);
}

/** ISO week string "YYYY-Www" */
function isoWeek(date = new Date()) {
  const d = toDate(date);
  const utc = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dayNum = utc.getUTCDay() || 7; // Monday = 1 ... Sunday = 7
  utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);

  const yearStart = Date.UTC(utc.getUTCFullYear(), 0, 1);
  const week = Math.ceil(((utc.getTime() - yearStart) / DAY_MS + 1) / 7);
  return `${utc.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
}

/** Week number since epoch — weekly rotation seed ke liye */
function weekIndex(date = new Date()) {
  const d = toDate(date);
  const jan1 = Date.UTC(d.getUTCFullYear(), 0, 1);
  return Math.floor((dayIndex(d) * DAY_MS - jan1) / (7 * DAY_MS));
}

/** Agla reset kab (ms epoch) — daily ya weekly */
function nextReset(date = new Date(), type = 'daily') {
  const d = toDate(date);
  if (type === 'weekly') {
    const utc = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
    const dayNum = new Date(utc).getUTCDay() || 7;
    return utc + (8 - dayNum) * DAY_MS;
  }
  const midnight = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
  return midnight + DAY_MS;
}

/** Discord relative timestamp: "<t:1234:R>" */
function discordRelative(ms) {
  return `<t:${Math.floor(ms / 1000)}:R>`;
}

/** "27 Oct 2026" */
function prettyDate(date = new Date()) {
  const d = toDate(date);
  return d.toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

module.exports = {
  DAY_MS,
  dayKey,
  dayIndex,
  isoWeek,
  weekIndex,
  nextReset,
  discordRelative,
  prettyDate,
};
