/**
 * Access control — dashboard kisko de sakte ho
 * --------------------------------------------
 * Teen role hain:
 *   owner  - DASHBOARD_PASSWORD (env) ya pehli baar auto-generate hui password
 *            Sab kuch kar sakta hai + naye access keys bana/revoke kar sakta hai
 *   admin  - bot start/stop/restart, premium grant, quests dekho
 *   viewer - sirf padh sakta hai (stats, quests, leaderboard)
 *
 * Access keys data/config.json me jaati hain (gitignored). Owner dashboard ke
 * "Access" tab se jitne chahe utne keys bana sakta hai — har key ka apna label
 * aur role hota hai, aur kabhi bhi revoke ho sakti hai.
 */
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const DATA_DIR = process.env.QUEST_DATA_DIR || path.join(__dirname, '..', '..', 'data');
const CONFIG_FILE = path.join(DATA_DIR, 'config.json');

let config = null;
const sessions = new Map(); // token -> { role, label, keyId, createdAt, ip }
const SESSION_TTL_MS = 12 * 60 * 60 * 1000; // 12 ghante

function ensureDir() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

function load() {
  if (config) return config;
  try {
    config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8'));
  } catch {
    config = {};
  }
  if (!config || typeof config !== 'object') config = {};
  if (!Array.isArray(config.keys)) config.keys = [];
  if (!config.secret) config.secret = crypto.randomBytes(32).toString('hex');
  if (!config.ownerPassword) config.ownerPassword = null;
  return config;
}

function save() {
  ensureDir();
  const tmp = `${CONFIG_FILE}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(config, null, 2));
  fs.renameSync(tmp, CONFIG_FILE);
}

/** Bot token dashboard se save karo (env se aaye to env hi jeetta hai) */
function saveToken(token) {
  const cfg = load();
  cfg.botToken = token || null;
  save();
}

function savedToken() {
  return load().botToken || null;
}

/** Owner password — env > saved > pehli baar generate */
function ownerPassword() {
  const cfg = load();
  const envPass = (process.env.DASHBOARD_PASSWORD || '').trim();
  if (envPass) return envPass;

  if (!cfg.ownerPassword) {
    cfg.ownerPassword = crypto.randomBytes(9).toString('base64url');
    save();
    console.log('\n┌──────────────────────────────────────────────┐');
    console.log('│  DASHBOARD PASSWORD (pehli baar bani — save!) │');
    console.log(`│  ${cfg.ownerPassword.padEnd(42)}│`);
    console.log('└──────────────────────────────────────────────┘\n');
  }
  return cfg.ownerPassword;
}

/** Naya access key banao */
function createKey({ label = 'Guest', role = 'viewer' } = {}) {
  const cfg = load();
  const cleanRole = ['viewer', 'admin'].includes(role) ? role : 'viewer';
  const entry = {
    id: crypto.randomBytes(4).toString('hex'),
    label: String(label).slice(0, 40) || 'Guest',
    role: cleanRole,
    key: `${cleanRole === 'admin' ? 'adm' : 'vw'}_${crypto.randomBytes(12).toString('base64url')}`,
    createdAt: Date.now(),
    lastUsedAt: null,
    enabled: true,
  };
  cfg.keys.unshift(entry);
  save();
  return entry;
}

function listKeys() {
  return load().keys.map(({ key, ...rest }) => ({ ...rest, masked: `${key.slice(0, 6)}…${key.slice(-4)}` }));
}

/** Key ka poora value sirf ek baar dikhane ke liye (create ke waqt response me) */
function getKeyValue(id) {
  return load().keys.find((k) => k.id === id)?.key ?? null;
}

function revokeKey(id) {
  const cfg = load();
  const before = cfg.keys.length;
  cfg.keys = cfg.keys.filter((k) => k.id !== id);
  const removed = cfg.keys.length !== before;
  if (removed) {
    // Us key se bane saare sessions bhi band
    for (const [token, session] of sessions) if (session.keyId === id) sessions.delete(token);
    save();
  }
  return removed;
}

function setKeyEnabled(id, enabled) {
  const entry = load().keys.find((k) => k.id === id);
  if (!entry) return false;
  entry.enabled = Boolean(enabled);
  if (!entry.enabled) {
    for (const [token, session] of sessions) if (session.keyId === id) sessions.delete(token);
  }
  save();
  return true;
}

/** Login: password ya access key — role wapas */
function authenticate(input, meta = {}) {
  const value = String(input ?? '').trim();
  if (!value) return null;

  const cfg = load();

  // Owner password (timing-safe compare)
  const owner = ownerPassword();
  if (value.length === owner.length && crypto.timingSafeEqual(Buffer.from(value), Buffer.from(owner))) {
    return startSession({ role: 'owner', label: 'Owner', keyId: null }, meta);
  }

  const entry = cfg.keys.find((k) => k.enabled && k.key === value);
  if (!entry) return null;

  entry.lastUsedAt = Date.now();
  save();
  return startSession({ role: entry.role, label: entry.label, keyId: entry.id }, meta);
}

function startSession(base, meta = {}) {
  const token = crypto.randomBytes(24).toString('base64url');
  const session = { ...base, createdAt: Date.now(), ip: meta.ip ?? null, token };
  sessions.set(token, session);
  return session;
}

function sessionFromToken(token) {
  if (!token) return null;
  const session = sessions.get(token);
  if (!session) return null;
  if (Date.now() - session.createdAt > SESSION_TTL_MS) {
    sessions.delete(token);
    return null;
  }
  return session;
}

function logout(token) {
  return sessions.delete(token);
}

/** Role hierarchy check */
function can(role, action) {
  const order = { viewer: 1, admin: 2, owner: 3 };
  const need = {
    view: 1,
    'bot.control': 2,
    'premium.grant': 2,
    'settings.manage': 2,
    'access.manage': 3,
    'quests.reset': 2,
  }[action] ?? 99;
  return (order[role] ?? 0) >= need;
}

/** Saare sessions clear (restart par bhi kaam aata hai) */
function clearSessions() {
  sessions.clear();
}

module.exports = {
  load,
  save,
  saveToken,
  savedToken,
  ownerPassword,
  createKey,
  listKeys,
  getKeyValue,
  revokeKey,
  setKeyEnabled,
  authenticate,
  sessionFromToken,
  logout,
  can,
  clearSessions,
  SESSION_TTL_MS,
};
