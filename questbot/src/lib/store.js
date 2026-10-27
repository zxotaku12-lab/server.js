/**
 * JSON store — ek hi file me sab kuch, debounced writes ke saath
 * --------------------------------------------------------------
 * Quest bot ko har message pe likhna padta hai, isliye har bump pe disk pe
 * write karna bewakoofi hoti. Yahan in-memory cache rakha jaata hai aur
 * ~1.5s me ek baar flush hota hai (plus process exit par).
 *
 * File: questbot/data/quests.json   (gitignored)
 * QUEST_DATA_DIR env se path badal sakta hai (tests isi ka use karte hain).
 */
const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.QUEST_DATA_DIR || path.join(__dirname, '..', '..', 'data');
const FILE = path.join(DATA_DIR, 'quests.json');

let cache = null;
let dirty = false;
let timer = null;

function ensureDir() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

/** Pura data object (cached) */
function load() {
  if (cache) return cache;
  try {
    cache = JSON.parse(fs.readFileSync(FILE, 'utf8'));
    if (!cache || typeof cache !== 'object') cache = {};
  } catch {
    cache = {};
  }
  return cache;
}

/** Disk pe likho (atomic: tmp file + rename) */
function flush() {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  if (!dirty || !cache) return;
  ensureDir();
  const tmp = `${FILE}.${process.pid}.tmp`;
  try {
    fs.writeFileSync(tmp, JSON.stringify(cache, null, 2));
    fs.renameSync(tmp, FILE);
    dirty = false;
  } catch (err) {
    console.error('[store] flush fail:', err.message);
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* ignore */
    }
  }
}

/** Data change hua — thodi der baad auto-flush */
function markDirty() {
  dirty = true;
  if (!timer) timer = setTimeout(flush, 1500);
  if (typeof timer.unref === 'function') timer.unref();
}

/** Test / shutdown ke liye */
function reset() {
  if (timer) clearTimeout(timer);
  timer = null;
  cache = null;
  dirty = false;
}

module.exports = { load, flush, markDirty, reset, FILE, DATA_DIR };

// Process band hone se pehle save — warna aakhri kuch seconds ka progress ud jaata hai.
process.on('exit', flush);
process.on('SIGINT', () => {
  flush();
  process.exit(0);
});
process.on('SIGTERM', () => {
  flush();
  process.exit(0);
});
