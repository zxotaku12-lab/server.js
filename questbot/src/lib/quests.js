/**
 * Quest engine — definitions, rotation, progress, claim
 * ----------------------------------------------------
 * Quest pools (src/lib/quests.js me hi sab kuch, easily edit kar sakte ho):
 *   daily   : har din 3 rotate hoti hain (sabke liye same)
 *   premium : premium walon ko +2 extra daily (bilkul FREE premium)
 *   weekly  : har hafte 2 rotate hoti hain
 *   once    : one-time starter quests (kabhi bhi complete kar sakte ho)
 *
 * Progress bot.js/events se aata hai (messages, reactions, voice, commands,
 * invites) aur users.bump() usse daily + weekly + lifetime teeno me likh deta hai.
 */
const periods = require('./periods');
const users = require('./users');
const settings = require('./settings');

const DAILY_PER_DAY = 3;
const PREMIUM_PER_DAY = 2;
const WEEKLY_PER_WEEK = 2;
const PREMIUM_MULTIPLIER = 1.5;

const METRIC = {
  messages: { label: 'messages', emoji: '💬' },
  reactions: { label: 'reactions', emoji: '👍' },
  voice: { label: 'VC minutes', emoji: '🎙️' },
  commands: { label: 'commands', emoji: '⌨️' },
  invites: { label: 'invites', emoji: '📨' },
};

/** Chhota definition helper */
const q = (id, title, emoji, metric, target, coins, xp) => ({
  id,
  title,
  emoji,
  metric,
  target,
  reward: { coins, xp },
});

const POOLS = {
  daily: [
    q('d_chat_15', 'Chai-charcha', '💬', 'messages', 15, 40, 25),
    q('d_chat_30', 'Chatty', '🗨️', 'messages', 30, 70, 40),
    q('d_chat_50', 'Baaton ka baap', '📢', 'messages', 50, 100, 60),
    q('d_react_5', 'React karo', '👍', 'reactions', 5, 30, 20),
    q('d_react_10', 'Emoji lover', '😍', 'reactions', 10, 45, 25),
    q('d_voice_10', 'VC me time', '🎙️', 'voice', 10, 60, 35),
    q('d_voice_25', 'VC veteran', '🎧', 'voice', 25, 90, 50),
    q('d_cmd_3', 'Bot explore karo', '⌨️', 'commands', 3, 35, 20),
    q('d_cmd_5', 'Command master', '🤖', 'commands', 5, 50, 30),
    q('d_invite_1', 'Dost bulao', '📨', 'invites', 1, 120, 70),
  ],
  premium: [
    q('p_chat_75', 'Non-stop chatter', '🔥', 'messages', 75, 150, 90),
    q('p_voice_45', 'Voice marathon', '🎙️', 'voice', 45, 180, 100),
    q('p_invite_3', 'Squad laao', '🚀', 'invites', 3, 300, 180),
  ],
  weekly: [
    q('w_chat_250', 'Hafte ka chatter', '💬', 'messages', 250, 400, 250),
    q('w_voice_120', 'Voice marathon (weekly)', '🎧', 'voice', 120, 450, 260),
    q('w_react_50', 'Reaction king', '👑', 'reactions', 50, 300, 200),
    q('w_cmd_25', 'Bot ka boss', '🤖', 'commands', 25, 350, 220),
    q('w_invite_5', 'Community builder', '🌱', 'invites', 5, 700, 400),
  ],
  once: [
    q('o_first_msg', 'First step', '👋', 'messages', 1, 50, 20),
    q('o_first_react', 'Thumbs up', '👍', 'reactions', 1, 40, 20),
    q('o_first_cmd', 'Explorer', '🧭', 'commands', 1, 40, 20),
    q('o_first_voice', 'Hello VC', '🎙️', 'voice', 1, 60, 30),
    q('o_first_invite', 'Pehla dost', '🤝', 'invites', 1, 150, 80),
  ],
};

/**
 * Pool se `count` items rotate karo — deterministic seed se, taaki
 * din badalne par rotation badle par sabko same quests milein.
 */
function rotate(pool, seed, count, step = 7) {
  const out = [];
  const seen = new Set();
  const total = pool.length;

  for (let i = 0; out.length < count && i < total * 2; i++) {
    const idx = (((seed * 3 + i * step) % total) + total) % total;
    const item = pool[idx];
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    out.push(item);
  }

  return out;
}

/** Aaj ki daily quests (premium = extra 2).
 *  ⚡ Unlimited mode me POORA pool ek saath — koi rotation limit nahi. */
function dailyQuests(date = new Date(), premium = false) {
  const seed = periods.dayIndex(date) + 1;
  const periodKey = periods.dayKey(date);
  const unlimited = settings.unlimited();

  const base = unlimited ? [...POOLS.daily] : rotate(POOLS.daily, seed, DAILY_PER_DAY);
  const bonus = premium ? (unlimited ? [...POOLS.premium] : rotate(POOLS.premium, seed, PREMIUM_PER_DAY)) : [];

  return [...base, ...bonus].map((item) => ({
    ...item,
    type: 'daily',
    periodKey,
    premiumOnly: POOLS.premium.includes(item),
  }));
}

/** Is hafte ki weekly quests — unlimited mode me poora pool */
function weeklyQuests(date = new Date()) {
  const seed = periods.weekIndex(date) + 1;
  const periodKey = periods.isoWeek(date);
  const unlimited = settings.unlimited();

  const list = unlimited ? [...POOLS.weekly] : rotate(POOLS.weekly, seed, WEEKLY_PER_WEEK);

  return list.map((item) => ({
    ...item,
    type: 'weekly',
    periodKey,
  }));
}

/** One-time quests (hamesha available) */
function oneTimeQuests() {
  return POOLS.once.map((item) => ({ ...item, type: 'once', periodKey: 'once' }));
}

/** Counter scope key: daily -> "d:2026-10-27", weekly -> "w:2026-W44", once -> "life" */
function scopeKey(type, periodKey) {
  if (type === 'once') return 'life';
  return `${type === 'weekly' ? 'w' : 'd'}:${periodKey}`;
}

/** Claim key — "questId:periodKey" */
function claimKey(quest) {
  return `${quest.id}:${quest.periodKey}`;
}

/**
 * Quest ko live object banao: progress, claimed status, premium multiply kiya reward.
 */
function decorate(user, quest, date = new Date()) {
  const taken = users.isPremium(user);
  const unlimited = settings.unlimited();
  const bucket = user.counters[scopeKey(quest.type, quest.periodKey)] ?? {};
  const tracked = Number(bucket[quest.metric]) || 0;
  // ⚡ Unlimited mode: har quest turant complete — progress ki zaroorat nahi
  const raw = unlimited ? Math.max(tracked, quest.target) : tracked;
  const current = Math.min(quest.target, Math.floor(raw));
  const percent = quest.target > 0 ? Math.min(100, Math.round((raw / quest.target) * 100)) : 100;
  const key = claimKey(quest);
  const mult = taken ? PREMIUM_MULTIPLIER : 1;

  return {
    ...quest,
    current,
    raw,
    percent,
    done: raw >= quest.target,
    claimed: Boolean(user.claimed[key]),
    claimable: raw >= quest.target && !user.claimed[key],
    key,
    rewardCoins: Math.round(quest.reward.coins * mult),
    rewardXp: Math.round(quest.reward.xp * mult),
    multiplier: mult,
    resetAt: quest.type === 'daily' ? periods.nextReset(date, 'daily') : quest.type === 'weekly' ? periods.nextReset(date, 'weekly') : 0,
  };
}

/** User ke active quests — daily (with premium extras) + weekly + once */
function activeQuests(user, date = new Date(), period = 'daily') {
  if (period === 'weekly') return weeklyQuests(date).map((item) => decorate(user, item, date));
  if (period === 'once') return oneTimeQuests().map((item) => decorate(user, item, date));
  return dailyQuests(date, users.isPremium(user)).map((item) => decorate(user, item, date));
}

/** Streak update — sirf jab us din pehli daily claim ho */
function updateStreak(user, date = new Date()) {
  const today = periods.dayKey(date);
  if (user.stats.lastDailyDay === today) return;

  const yesterday = new Date(date);
  yesterday.setUTCDate(yesterday.getUTCDate() - 1);

  user.stats.streak = user.stats.lastDailyDay === periods.dayKey(yesterday) ? (Number(user.stats.streak) || 0) + 1 : 1;
  user.stats.lastDailyDay = today;
}

/**
 * Saare complete hue quests claim karo (daily + weekly + once, sab ek saath).
 * @returns {{claimed: object[], coins: number, xp: number, before: object, after: object}}
 */
function claimAll(guildId, userId, date = new Date()) {
  const user = users.ensure(guildId, userId);
  const all = [
    ...activeQuests(user, date, 'daily'),
    ...activeQuests(user, date, 'weekly'),
    ...activeQuests(user, date, 'once'),
  ];

  const claimable = all.filter((item) => item.claimable);
  const before = users.levelOf(user);
  const result = { claimed: [], coins: 0, xp: 0, before, after: before };

  for (const item of claimable) {
    user.claimed[item.key] = Date.now();
    user.coins = (Number(user.coins) || 0) + item.rewardCoins;
    user.xp = (Number(user.xp) || 0) + item.rewardXp;
    user.stats.questsDone = (Number(user.stats.questsDone) || 0) + 1;

    result.coins += item.rewardCoins;
    result.xp += item.rewardXp;
    result.claimed.push(item);
  }

  if (result.claimed.some((item) => item.type === 'daily')) updateStreak(user, date);

  result.after = users.levelOf(user);
  users.markDirty();
  if (result.claimed.length) users.commit(); // reward turant save — crash me na kho

  return result;
}

/** /questlist aur dashboard ke liye poora catalog */
function catalog() {
  const map = (list) =>
    list.map((item) => ({
      ...item,
      metricLabel: METRIC[item.metric]?.label ?? item.metric,
    }));

  return {
    daily: map(POOLS.daily),
    premium: map(POOLS.premium),
    weekly: map(POOLS.weekly),
    once: map(POOLS.once),
    rotation: { daily: DAILY_PER_DAY, premium: PREMIUM_PER_DAY, weekly: WEEKLY_PER_WEEK },
    premiumMultiplier: PREMIUM_MULTIPLIER,
    unlimited: settings.unlimited(),
  };
}

/** Metric ka readable target: "20 messages" */
function targetText(quest) {
  const meta = METRIC[quest.metric] ?? { label: quest.metric };
  return `${quest.target} ${meta.label}`;
}

module.exports = {
  POOLS,
  METRIC,
  PREMIUM_MULTIPLIER,
  DAILY_PER_DAY,
  PREMIUM_PER_DAY,
  WEEKLY_PER_WEEK,
  dailyQuests,
  weeklyQuests,
  oneTimeQuests,
  activeQuests,
  decorate,
  claimAll,
  catalog,
  targetText,
  claimKey,
  scopeKey,
  updateStreak,
};
