/**
 * Unit tests — bina Discord ke
 * ---------------------------
 *   npm test
 *
 * Isolated temp data dir use hoti hai (QUEST_DATA_DIR), repo ka real data
 * chhua nahi jaata.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'questbot-test-'));
process.env.QUEST_DATA_DIR = TMP;
process.env.DASHBOARD_PASSWORD = 'owner-test-pass';
delete process.env.DISCORD_TOKEN;

const SRC = path.join(__dirname, '..', 'src');
const periods = require(path.join(SRC, 'lib', 'periods.js'));
const store = require(path.join(SRC, 'lib', 'store.js'));
const users = require(path.join(SRC, 'lib', 'users.js'));
const quests = require(path.join(SRC, 'lib', 'quests.js'));
const access = require(path.join(SRC, 'lib', 'access.js'));
const registry = require(path.join(SRC, 'commands'));

let passed = 0;
let failed = 0;
const failures = [];

function check(name, ok, detail = '') {
  if (ok) {
    passed++;
    console.log(`  ✅ ${name}`);
  } else {
    failed++;
    failures.push(`${name}${detail ? ` — ${detail}` : ''}`);
    console.log(`  ❌ ${name}${detail ? ` — ${detail}` : ''}`);
  }
}

const G = '111111111111111111';
const U = '222222222222222222';

/* ---------------- 1. periods ---------------- */
function testPeriods() {
  console.log('\n1) Periods (daily/weekly keys)');
  const d = new Date('2026-10-27T10:00:00Z');

  check('dayKey -> YYYY-MM-DD', periods.dayKey(d) === '2026-10-27', periods.dayKey(d));
  check('isoWeek format', /^\d{4}-W\d{2}$/.test(periods.isoWeek(d)), periods.isoWeek(d));
  check('same day = same key', periods.dayKey(d) === periods.dayKey(new Date('2026-10-27T23:59:00Z')));
  check('next day = different key', periods.dayKey(d) !== periods.dayKey(new Date('2026-10-28T00:01:00Z')));

  const midnight = periods.nextReset(d, 'daily');
  check('daily reset next UTC midnight', new Date(midnight).toISOString() === '2026-10-28T00:00:00.000Z', new Date(midnight).toISOString());

  const weekReset = periods.nextReset(d, 'weekly');
  check('weekly reset = agla Monday', new Date(weekReset).getUTCDay() === 1, new Date(weekReset).toISOString());
  check('weekly reset future me hai', weekReset > d.getTime());
  check('discord relative format', /^<t:\d+:R>$/.test(periods.discordRelative(d)));
}

/* ---------------- 2. rotation ---------------- */
function testRotation() {
  console.log('\n2) Quest rotation');

  const a = quests.dailyQuests(new Date('2026-10-27T05:00:00Z'));
  const b = quests.dailyQuests(new Date('2026-10-27T05:00:00Z'));
  const c = quests.dailyQuests(new Date('2026-10-28T05:00:00Z'));

  check(`daily me ${quests.DAILY_PER_DAY} quests`, a.length === quests.DAILY_PER_DAY, String(a.length));
  check('daily deterministic (same din = same quests)', JSON.stringify(a.map((q) => q.id)) === JSON.stringify(b.map((q) => q.id)));
  check('agla din rotation badalti hai', JSON.stringify(a.map((q) => q.id)) !== JSON.stringify(c.map((q) => q.id)));
  check('daily quests unique hain', new Set(a.map((q) => q.id)).size === a.length);

  const prem = quests.dailyQuests(new Date('2026-10-27T05:00:00Z'), true);
  check('premium walon ko extra quests', prem.length === quests.DAILY_PER_DAY + quests.PREMIUM_PER_DAY, String(prem.length));
  check('premium quests flagged', prem.filter((q) => q.premiumOnly).length === quests.PREMIUM_PER_DAY);

  const week = quests.weeklyQuests(new Date('2026-10-27T05:00:00Z'));
  check('weekly me quests hain', week.length === quests.WEEKLY_PER_WEEK && week.every((q) => q.type === 'weekly'));

  const once = quests.oneTimeQuests();
  check('one-time quests available', once.length >= 3 && once.every((q) => q.type === 'once'));

  const poolIds = new Set([...quests.POOLS.daily, ...quests.POOLS.premium, ...quests.POOLS.weekly, ...quests.POOLS.once].map((q) => q.id));
  check('saare quest ids unique', poolIds.size === quests.POOLS.daily.length + quests.POOLS.premium.length + quests.POOLS.weekly.length + quests.POOLS.once.length);

  const rewardsOk = [...quests.POOLS.daily, ...quests.POOLS.premium, ...quests.POOLS.weekly, ...quests.POOLS.once].every(
    (q) => q.target > 0 && q.reward.coins > 0 && q.reward.xp > 0 && q.metric && q.title
  );
  check('har quest me target + reward valid', rewardsOk);
}

/* ---------------- 3. counters ---------------- */
function testCounters() {
  console.log('\n3) Progress counters');

  const user = users.ensure(G, U);
  check('naya user 0 coins/xp', user.coins === 0 && user.xp === 0);
  check('naya user premium OFF', users.isPremium(user) === false);

  users.bump(G, U, 'messages', 5);
  const after = users.peek(G, U);
  const dayScope = quests.scopeKey('daily', periods.dayKey());
  const weekScope = quests.scopeKey('weekly', periods.isoWeek());

  check('daily counter badha', after.counters[dayScope].messages === 5, JSON.stringify(after.counters[dayScope]));
  check('weekly counter bhi badha', after.counters[weekScope].messages === 5);
  check('lifetime counter bhi badha', after.counters.life.messages === 5);
  check('stats.messages track hua', after.stats.messages === 5);

  users.bump(G, U, 'messages', -3);
  check('negative amount ignore hota hai', users.peek(G, U).counters[dayScope].messages === 5);

  users.bump(G, U, 'voice', 7);
  check('alag metric alag counter', users.peek(G, U).counters.life.voice === 7);
}

/* ---------------- 4. claim ---------------- */
function testClaim() {
  console.log('\n4) Claim flow');

  // Fresh user — warna one-time quests (first message/react/voice) pehle se
  // complete hongi aur "kuch complete nahi" wali assumption fail ho jaayegi.
  const CG = '555555555555555555';
  const CU = '666666666666666666';

  const empty = quests.claimAll(CG, CU);
  check('kuch complete na ho to claim 0', empty.claimed.length === 0 && empty.coins === 0, String(empty.claimed.length));

  const today = quests.activeQuests(users.peek(CG, CU), new Date(), 'daily');
  const target = today[0];
  users.bump(CG, CU, target.metric, target.target);

  const result = quests.claimAll(CG, CU);
  check('complete quest claim hui', result.claimed.some((q) => q.id === target.id), JSON.stringify(result.claimed.map((q) => q.id)));
  check('coins mile', result.coins > 0 && result.coins === result.claimed.reduce((s, q) => s + q.rewardCoins, 0), String(result.coins));
  check('xp mila', result.xp > 0 && users.peek(CG, CU).xp > 0);
  check('questsDone badha', users.peek(CG, CU).stats.questsDone === result.claimed.length);

  const again = quests.claimAll(CG, CU);
  check('dobara claim nahi milti (no double reward)', again.claimed.length === 0, String(again.claimed.length));

  const decorated = quests.activeQuests(users.peek(CG, CU), new Date(), 'daily').find((q) => q.id === target.id);
  check('claimed flag embed me dikhta hai', decorated.claimed === true && decorated.claimable === false);

  // Streak: pehli daily claim par 1
  check('streak set hua', users.peek(CG, CU).stats.streak === 1, String(users.peek(CG, CU).stats.streak));
}

/* ---------------- 5. premium (FREE) ---------------- */
function testPremium() {
  console.log('\n5) Premium — free');

  const user = users.ensure(G, '333333333333333333');
  check('grant se pehle free premium OFF', users.isPremium(user) === false);

  users.grantPremium(G, '333333333333333333');
  check('grant ke baad ON', users.isPremium(users.peek(G, '333333333333333333')) === true);
  check('koi payment field nahi', users.peek(G, '333333333333333333').paid === undefined);

  const premiumUser = users.peek(G, '333333333333333333');
  const list = quests.activeQuests(premiumUser, new Date(), 'daily');
  check('premium ko extra quests milte hain', list.length === quests.DAILY_PER_DAY + quests.PREMIUM_PER_DAY, String(list.length));

  const anyQuest = list.find((q) => q.premiumOnly) ?? list[0];
  check(`reward ×${quests.PREMIUM_MULTIPLIER} hota hai`, anyQuest.multiplier === quests.PREMIUM_MULTIPLIER);

  const normal = quests.activeQuests(users.ensure(G, '444444444444444444'), new Date(), 'daily')[0];
  check('non-premium reward normal hota hai', normal.multiplier === 1);

  users.revokePremium(G, '333333333333333333');
  check('revoke ke baad OFF', users.isPremium(users.peek(G, '333333333333333333')) === false);
}

/* ---------------- 5b. unlimited mode ---------------- */
function testUnlimited() {
  console.log('\n5b) ⚡ Unlimited mode — sab ek saath, unlimited');

  const settings = require(path.join(SRC, 'lib', 'settings.js'));
  check('default OFF', settings.unlimited() === false);

  settings.set({ unlimited: true });
  check('ON ho gaya', settings.unlimited() === true);

  const daily = quests.dailyQuests(new Date());
  check(`daily me poora pool (${quests.POOLS.daily.length})`, daily.length === quests.POOLS.daily.length, String(daily.length));

  const prem = quests.dailyQuests(new Date(), true);
  check('premium ko premium pool bhi poora milta hai', prem.length === quests.POOLS.daily.length + quests.POOLS.premium.length, String(prem.length));

  const week = quests.weeklyQuests(new Date());
  check(`weekly me poora pool (${quests.POOLS.weekly.length})`, week.length === quests.POOLS.weekly.length, String(week.length));

  const UG = '777777777777777777';
  const UU = '888888888888888888';
  const user = users.ensure(UG, UU);

  const all = [
    ...quests.activeQuests(user, new Date(), 'daily'),
    ...quests.activeQuests(user, new Date(), 'weekly'),
    ...quests.activeQuests(user, new Date(), 'once'),
  ];
  check('har quest turant complete', all.every((q) => q.done && q.percent === 100), String(all.filter((q) => !q.done).length));
  check('bina ek bhi message bheje sab claimable', all.every((q) => q.claimable));
  check('total quests = saare pools', all.length === quests.POOLS.daily.length + quests.POOLS.weekly.length + quests.POOLS.once.length, String(all.length));

  const result = quests.claimAll(UG, UU);
  check('ek click me SAARE quests claim', result.claimed.length === all.length, `${result.claimed.length}/${all.length}`);
  check('poori reward mili', result.coins > 1000 && result.xp > 500, `coins ${result.coins}, xp ${result.xp}`);
  check('coins user me save hue', users.peek(UG, UU).coins === result.coins);

  const repeat = quests.claimAll(UG, UU);
  check('usi period me dobara claim nahi (no infinite farm)', repeat.claimed.length === 0, String(repeat.claimed.length));

  settings.set({ unlimited: false });
  check('OFF karne par normal rotation wapas', quests.dailyQuests(new Date()).length === quests.DAILY_PER_DAY);

  // Env override test
  const prev = process.env.QUEST_UNLIMITED;
  process.env.QUEST_UNLIMITED = '1';
  check('QUEST_UNLIMITED=1 env se ON', settings.unlimited() === true);
  settings.set({ unlimited: false });
  check('env override dashboard setting ko haraata hai', settings.unlimited() === true);
  if (prev === undefined) delete process.env.QUEST_UNLIMITED;
  else process.env.QUEST_UNLIMITED = prev;
  check('env hataane ke baad wapas OFF', settings.unlimited() === false);
}

/* ---------------- 6. access control ---------------- */
function testAccess() {
  console.log('\n6) Access control (kisko access de sakte ho)');

  const owner = access.authenticate('owner-test-pass');
  check('owner password se login', owner?.role === 'owner', JSON.stringify(owner));

  check('galat password reject', access.authenticate('nope') === null);

  const viewer = access.createKey({ label: 'Rahul', role: 'viewer' });
  check('key banti hai (vw_ prefix)', viewer.key.startsWith('vw_'), viewer.key.slice(0, 6));

  const viewerSession = access.authenticate(viewer.key);
  check('viewer key se login', viewerSession?.role === 'viewer' && viewerSession.label === 'Rahul');

  const admin = access.createKey({ label: 'Mod', role: 'admin' });
  const adminSession = access.authenticate(admin.key);
  check('admin key se login', adminSession?.role === 'admin');

  check('viewer sirf dekh sakta hai', access.can('viewer', 'view') && !access.can('viewer', 'bot.control'));
  check('viewer access manage nahi kar sakta', access.can('viewer', 'access.manage') === false);
  check('admin bot control kar sakta hai', access.can('admin', 'bot.control') && access.can('admin', 'premium.grant'));
  check('admin naye keys nahi bana sakta', access.can('admin', 'access.manage') === false);
  check('owner sab kar sakta hai', access.can('owner', 'access.manage') && access.can('owner', 'bot.control'));

  const listed = access.listKeys();
  check('keys list me masked key aati hai', listed.length === 2 && listed.every((k) => k.masked && !k.key));

  check('session token se session milta hai', access.sessionFromToken(viewerSession.token)?.role === 'viewer');
  check('bogus session null', access.sessionFromToken('fake') === null);

  access.revokeKey(viewer.id);
  check('revoke ke baad login fail', access.authenticate(viewer.key) === null);
  check('revoke se session bhi band', access.sessionFromToken(viewerSession.token) === null);
  check('admin key abhi bhi valid', access.authenticate(admin.key)?.role === 'admin');

  access.setKeyEnabled(admin.id, false);
  check('disable ke baad login fail', access.authenticate(admin.key) === null);

  check('rate-limit ke bina owner password env se aata hai', access.ownerPassword() === 'owner-test-pass');
}

/* ---------------- 7. persistence ---------------- */
function testPersistence() {
  console.log('\n7) Storage');

  const before = users.peek(G, U);
  store.flush();

  const file = path.join(TMP, 'quests.json');
  check('data file bani', fs.existsSync(file), file);

  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const key = users.keyOf(G, U);
  check('coins disk pe save hue', raw.users[key].coins === before.coins, String(raw.users[key]?.coins));
  check('premium flag save hua', typeof raw.users[key].premium === 'boolean');

  store.reset();
  const reloaded = users.peek(G, U);
  check('reload ke baad data wahi', reloaded.coins === before.coins && reloaded.stats.questsDone === before.stats.questsDone);
}

/* ---------------- 8. commands ---------------- */
function testCommands() {
  console.log('\n8) Commands');

  const names = registry.names();
  const expected = ['quest', 'questlist', 'questall', 'questtop', 'premium'];
  check('saari quest commands load hui', expected.every((n) => names.includes(n)), names.join(', '));
  check('koi duplicate nahi', new Set(names).size === names.length);

  const json = registry.json();
  check('Discord-shaped JSON', json.every((c) => c.name && c.description), JSON.stringify(json.map((c) => c.name)));

  for (const name of expected) {
    const cmd = registry.get(name);
    check(`/${name} me guildOnly + execute`, cmd?.guildOnly === true && typeof cmd.execute === 'function');
  }

  const listCmd = registry.get('questlist');
  check('/questlist me type option hai', listCmd.data.options.some((o) => o.name === 'type'));
}

/* ---------------- 9. command execution (mocked interaction) ---------------- */
async function testExecution() {
  console.log('\n9) Command execution (mock interaction)');

  function mockInteraction({ userId = U, options = {} } = {}) {
    const replies = [];
    return {
      replies,
      guildId: G,
      guild: { id: G, name: 'Test Server' },
      user: { id: userId, username: 'hero' },
      options: {
        getUser: (name) => options[name] ?? null,
        getString: (name) => options[name] ?? null,
        getInteger: (name) => options[name] ?? null,
      },
      async reply(payload) {
        replies.push(typeof payload === 'string' ? { content: payload } : payload);
      },
    };
  }

  const questCmd = registry.get('quest');

  // Progress bhardo taaki quests complete ho jaaye
  const active = quests.activeQuests(users.ensure(G, U), new Date(), 'daily');
  for (const q of active) users.bump(G, U, q.metric, q.target);

  const i1 = mockInteraction();
  await questCmd.execute(i1);
  const embed1 = i1.replies[0]?.embeds?.[0]?.toJSON?.() ?? i1.replies[0]?.embeds?.[0];
  check('/quest embed reply karta hai', Boolean(embed1));
  check('/quest me aaj ke quests dikhte hain', /quests/i.test(embed1.title ?? '') && embed1.description.length > 20);
  check('/quest me claim button hai', (i1.replies[0].components ?? []).length > 0);

  const i2 = mockInteraction();
  await registry.get('questall').execute(i2);
  const embed2 = i2.replies[0]?.embeds?.[0]?.toJSON?.() ?? i2.replies[0]?.embeds?.[0];
  check('/questall teeno sections dikhata hai', (embed2?.fields ?? []).some((f) => /Daily/.test(f.name)) && (embed2?.fields ?? []).some((f) => /Weekly/.test(f.name)));

  const i3 = mockInteraction();
  await registry.get('questlist').execute(i3);
  const embed3 = i3.replies[0]?.embeds?.[0]?.toJSON?.() ?? i3.replies[0]?.embeds?.[0];
  check('/questlist poora catalog dikhata hai', /Daily/.test(embed3.description) && /Weekly/.test(embed3.description) && /One-time/.test(embed3.description));
  check('/questlist premium free batata hai', /FREE/.test(JSON.stringify(embed3.fields)));

  const i4 = mockInteraction({ userId: '333333333333333333' });
  await registry.get('premium').execute(i4);
  const embed4 = i4.replies[0]?.embeds?.[0]?.toJSON?.() ?? i4.replies[0]?.embeds?.[0];
  check('/premium activate button deta hai', (i4.replies[0].components ?? []).length > 0 && /FREE/.test(embed4.title));

  // Leaderboard me aane ke liye kam se kam ek claim chahiye
  quests.claimAll(G, U);

  const i5 = mockInteraction();
  await registry.get('questtop').execute(i5);
  const embed5 = i5.replies[0]?.embeds?.[0]?.toJSON?.() ?? i5.replies[0]?.embeds?.[0];
  check('/questtop leaderboard dikhata hai', Boolean(embed5?.description));
}

/* ---------------- run ---------------- */
(async () => {
  console.log('\n🎯 Quest Bot tests');
  console.log(`   temp data: ${TMP}\n`);

  try {
    testPeriods();
    testRotation();
    testCounters();
    testClaim();
    testPremium();
    testUnlimited();
    testAccess();
    testPersistence();
    testCommands();
    await testExecution();
  } catch (err) {
    console.error('\n💥 Test crash:', err);
    failed++;
    failures.push(`crash: ${err.message}`);
  } finally {
    store.reset();
    fs.rmSync(TMP, { recursive: true, force: true });
  }

  console.log(`\n${'─'.repeat(50)}`);
  console.log(`Result: ${passed} passed, ${failed} failed`);
  if (failed) {
    console.log('\nFailed:');
    for (const f of failures) console.log(`  • ${f}`);
    process.exit(1);
  }
  console.log('🎉 Sab pass!');
  process.exit(0);
})();
