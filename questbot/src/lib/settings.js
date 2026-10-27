/**
 * Bot settings — dashboard se on/off hone waale switches
 * ------------------------------------------------------
 * Abhi ek hi switch hai:
 *   unlimited  - "⚡ Unlimited mode": saare quests ek saath available hote hain
 *                aur turant complete maane jaate hain — member bas claim karta hai.
 *                Koi grind nahi, koi limit nahi.
 *
 * Env override: QUEST_UNLIMITED=1 (deploy pe hamesha ON rakhne ke liye)
 * Data: data/quests.json -> "settings" key (gitignored)
 */
const store = require('./store');

const KEY = 'settings';
const DEFAULTS = { unlimited: false };

function envOverride() {
  const raw = String(process.env.QUEST_UNLIMITED ?? '').trim().toLowerCase();
  if (!raw) return undefined;
  return ['1', 'true', 'on', 'yes', 'haan'].includes(raw);
}

function all() {
  const data = store.load();
  if (!data[KEY] || typeof data[KEY] !== 'object') data[KEY] = {};
  return data[KEY];
}

/** Effective settings (env > saved > default) */
function get() {
  const saved = { ...DEFAULTS, ...all() };
  const env = envOverride();
  return {
    ...saved,
    unlimited: env === undefined ? Boolean(saved.unlimited) : env,
    unlimitedSource: env === undefined ? 'dashboard' : 'env',
  };
}

const unlimited = () => get().unlimited;

/** Patch karo aur turant save (toggle ke baad restart me na kho) */
function set(patch) {
  const data = all();
  if ('unlimited' in (patch ?? {})) data.unlimited = Boolean(patch.unlimited);
  store.markDirty();
  store.flush();
  return get();
}

module.exports = { get, set, unlimited, envOverride, DEFAULTS };
