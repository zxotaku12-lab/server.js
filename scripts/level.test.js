/**
 * Leveling tests — lib/levels.js maths + /rank + /leaderboard
 * -----------------------------------------------------------
 *   npm run test:level
 *
 * XP data seedha data/xp.json me likha jaata hai (jaise bot.js likhta hai),
 * aur lib/xp.js hamesha disk se fresh padhta hai — isliye cache invalidation
 * ki zaroorat nahi. Baad me file restore ho jaati hai.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const { levelFromXp, xpForLevel, progress, bar } = require(path.join(ROOT, 'lib', 'levels.js'));
const xpLib = require(path.join(ROOT, 'lib', 'xp.js'));
const CMDS = require(path.join(ROOT, 'commands', 'level.js'));
const XP_FILE = path.join(ROOT, 'data', 'xp.json');

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

/* ---------------- mocks ---------------- */
function makeInteraction({ guildId = 'g1', guildName = 'Test Server', userId = 'u1', username = 'hero', targetUser = null, httpMode = false } = {}) {
  const calls = { reply: [] };
  return {
    calls,
    guildId,
    guild: httpMode ? null : { id: guildId, name: guildName },
    user: { id: userId, username, displayAvatarURL: () => `https://cdn.discordapp.com/avatars/${userId}/x.png?size=128` },
    client: null,
    options: { getUser: () => targetUser },
    async reply(p) {
      calls.reply.push(typeof p === 'string' ? { content: p } : p);
    },
  };
}

const byName = (n) => CMDS.find((c) => c.data.name === n);

function embedOf(i) {
  const raw = i.calls.reply[0]?.embeds?.[0];
  return raw ? (typeof raw.toJSON === 'function' ? raw.toJSON() : raw) : null;
}
const fieldText = (i) => JSON.stringify(embedOf(i)?.fields ?? []);
const content = (i) => i.calls.reply[0]?.content ?? '';

/** data/xp.json likho — { "g1:u1": {xp, username} } */
function seedXp(rows, guildId = 'g1') {
  const out = {};
  for (const [userId, xp, username] of rows) out[`${guildId}:${userId}`] = { xp, username };
  fs.writeFileSync(XP_FILE, JSON.stringify(out, null, 2));
}

async function main() {
  console.log('\n📊 Leveling tests\n');

  const backup = fs.existsSync(XP_FILE) ? fs.readFileSync(XP_FILE, 'utf8') : null;
  fs.mkdirSync(path.dirname(XP_FILE), { recursive: true });

  try {
    /* ---------- 1. pure maths ---------- */
    console.log('1) lib/levels.js maths');
    check('level 0 XP = 0', levelFromXp(0) === 0);
    check('level 99 XP = 0 (abhi level 1 nahi)', levelFromXp(99) === 0, String(levelFromXp(99)));
    check('level 100 XP = 1', levelFromXp(100) === 1);
    check('level 399 XP = 1', levelFromXp(399) === 1, String(levelFromXp(399)));
    check('level 400 XP = 2', levelFromXp(400) === 2);
    check('level 10000 XP = 10', levelFromXp(10000) === 10);
    check('xpForLevel: 0,1,2,3,10', [0, 1, 2, 3, 10].map(xpForLevel).join(',') === '0,100,400,900,10000', [0, 1, 2, 3, 10].map(xpForLevel).join(','));
    check('xpForLevel(levelFromXp(x)) <= x  (random sample)', [0, 50, 100, 350, 900, 1234, 9999, 10000, 54321].every((x) => xpForLevel(levelFromXp(x)) <= x));
    check('negative/NaN XP crash nahi karta', levelFromXp(-500) === 0 && levelFromXp(undefined) === 0 && levelFromXp(NaN) === 0);

    {
      const p = progress(1500);
      check('progress(1500): level 3', p.level === 3, String(p.level));
      check('progress(1500): current 900, next 1600', p.current === 900 && p.next === 1600, `${p.current}/${p.next}`);
      check('progress(1500): into 600 of 700', p.into === 600 && p.span === 700, `${p.into}/${p.span}`);
      check('progress(1500): 86%', p.percent === 86, String(p.percent));
    }
    check('progress(0) = 0%', progress(0).percent === 0);
    check('progress(exact level boundary) = 0%', progress(900).percent === 0 && progress(900).level === 3);
    check('progress percent kabhi 100 se upar nahi', progress(1599).percent <= 100 && progress(99999999).percent <= 100);

    check('bar(0) = sab khaali', bar(0) === '▱▱▱▱▱▱▱▱▱▱', bar(0));
    check('bar(100) = sab bhara', bar(100) === '▰▰▰▰▰▰▰▰▰▰', bar(100));
    check('bar(86) = 9 bhare (rounding)', bar(86) === '▰'.repeat(9) + '▱', bar(86));
    check('bar length hamesha 10', [0, 7, 33, 50, 86, 100, 150, -20].every((p) => [...bar(p)].length === 10));
    check('bar custom size', [...bar(50, 4)].length === 4);

    /* ---------- 2. lib/xp.js ---------- */
    console.log('\n2) lib/xp.js (store reads)');
    seedXp([['u1', 1500, 'hero'], ['u2', 10000, 'pro'], ['u3', 50, 'newbie']]);
    check('getEntry XP + level deta hai', xpLib.getEntry('g1', 'u1').level === 3 && xpLib.getEntry('g1', 'u1').xp === 1500);
    check('getEntry na milne par null', xpLib.getEntry('g1', 'nobody') === null);
    check('guildBoard XP descending sort karta hai', xpLib.guildBoard('g1').map((e) => e.userId).join(',') === 'u2,u1,u3');
    check('rankOf: u2 = #1, u1 = #2, u3 = #3', xpLib.rankOf('g1', 'u2').rank === 1 && xpLib.rankOf('g1', 'u1').rank === 2 && xpLib.rankOf('g1', 'u3').rank === 3);
    check('rankOf total sahi', xpLib.rankOf('g1', 'u1').total === 3);
    check('rankOf unknown user -> rank null', xpLib.rankOf('g1', 'ghost').rank === null);
    check('leaderboard limit respect karta hai', xpLib.leaderboard('g1', 2).length === 2);
    seedXp([['other1', 99999, 'intruder']], 'DIFFERENT_GUILD');
    {
      const both = JSON.parse(fs.readFileSync(XP_FILE, 'utf8'));
      both['g1:u1'] = { xp: 1500, username: 'hero' };
      fs.writeFileSync(XP_FILE, JSON.stringify(both));
    }
    check('doosre guild ka XP board me leak nahi hota', xpLib.guildBoard('g1').every((e) => e.userId !== 'other1') && xpLib.guildBoard('DIFFERENT_GUILD').length === 1);
    check('khaali store pe crash nahi', (() => { fs.writeFileSync(XP_FILE, '{}'); return xpLib.guildBoard('g1').length === 0; })());
    check('corrupt store pe crash nahi', (() => { fs.writeFileSync(XP_FILE, 'not json at all'); return xpLib.guildBoard('g1').length === 0 && xpLib.getEntry('g1', 'u1') === null; })());

    /* ---------- 3. /rank ---------- */
    console.log('\n3) /rank');
    seedXp([['u1', 1500, 'hero'], ['u2', 10000, 'pro'], ['u3', 50, 'newbie']]);
    {
      const i = makeInteraction({});
      await byName('rank').execute(i);
      check('apna rank dikha', fieldText(i).includes('"Level"') && fieldText(i).includes('**3**'), fieldText(i).slice(0, 140));
      check('total XP formatted', fieldText(i).includes('1,500'), fieldText(i).slice(0, 160));
      check('rank position + total', /#2\*\* \/ 3/.test(fieldText(i)), fieldText(i).slice(0, 200));
      check('progress bar + percent', fieldText(i).includes('▰') && fieldText(i).includes('86%'));
      check('XP remaining detail', fieldText(i).includes('600 / 700'));
      check('thumbnail set hua', !!embedOf(i)?.thumbnail?.url);
      check('title me username', embedOf(i)?.title?.includes('hero'));
    }
    {
      const i = makeInteraction({ targetUser: { id: 'u2', username: 'pro', displayAvatarURL: () => 'https://x/p.png' } });
      await byName('rank').execute(i);
      check('doosre user ka rank (level 10)', fieldText(i).includes('**10**') && fieldText(i).includes('#1** / 3'), fieldText(i).slice(0, 180));
      check('doosre user ka rank public hai (ephemeral nahi)', i.calls.reply[0]?.ephemeral !== true);
    }
    {
      const i = makeInteraction({ targetUser: { id: 'ghost', username: 'ghost' } });
      await byName('rank').execute(i);
      check('jiska XP nahi uske liye clear message', /koi XP record nahi/.test(content(i)), content(i).slice(0, 80));
      check('doosre user ka "no XP" message ephemeral', i.calls.reply[0]?.ephemeral === true);
    }
    {
      const i = makeInteraction({ guildId: null, httpMode: true });
      await byName('rank').execute(i);
      check('DM me /rank refuse', /DM me nahi/.test(content(i)), content(i).slice(0, 80));
    }
    {
      // HTTP mode: guild object null, sirf guildId — phir bhi chalna chahiye
      const i = makeInteraction({ httpMode: true, guildId: 'g1' });
      await byName('rank').execute(i);
      check('HTTP mode me /rank chalta hai (sirf guildId chahiye)', fieldText(i).includes('**3**'), fieldText(i).slice(0, 100));
    }
    {
      fs.writeFileSync(XP_FILE, '{}');
      const i = makeInteraction({});
      let threw = null;
      try {
        await byName('rank').execute(i);
      } catch (e) {
        threw = e;
      }
      check('khaali XP store pe /rank crash nahi karta', threw === null && /koi XP record nahi/.test(content(i)), threw?.message);
    }

    /* ---------- 4. /leaderboard ---------- */
    console.log('\n4) /leaderboard');
    seedXp([['u1', 1500, 'hero'], ['u2', 10000, 'pro'], ['u3', 50, 'newbie']]);
    {
      const i = makeInteraction({});
      await byName('leaderboard').execute(i);
      const desc = embedOf(i)?.description ?? '';
      check('descending order me list', desc.indexOf('pro') < desc.indexOf('hero') && desc.indexOf('hero') < desc.indexOf('newbie'), desc.slice(0, 120));
      check('medals 🥇🥈🥉', desc.includes('🥇') && desc.includes('🥈') && desc.includes('🥉'));
      check('level + XP dono dikhte hain', desc.includes('Level **10**') && desc.includes('10,000 XP'), desc.slice(0, 140));
      check('footer me total + mera rank', /3 members tracked/.test(embedOf(i)?.footer?.text ?? '') && /#2/.test(embedOf(i)?.footer?.text ?? ''), embedOf(i)?.footer?.text);
      check('title me guild name', embedOf(i)?.title?.includes('Test Server'));
    }
    {
      // HTTP mode: guild object null -> title fallback
      const i = makeInteraction({ httpMode: true, guildId: 'g1' });
      await byName('leaderboard').execute(i);
      check('HTTP mode me /leaderboard crash nahi, title fallback', (embedOf(i)?.title ?? '').includes('is server'));
    }
    {
      const rows = Array.from({ length: 14 }, (_, n) => [`u${n}`, (n + 1) * 1000, `user${n}`]);
      seedXp(rows);
      const i = makeInteraction({ userId: 'u13' }); // sabse top waala
      await byName('leaderboard').execute(i);
      const lines = (embedOf(i)?.description ?? '').split('\n');
      check('top 10 pe cap hai (14 me se 10)', lines.length === 10, String(lines.length));
      check('sabse zyada XP waala #1 pe', lines[0].includes('🥇') && lines[0].includes('user13'), lines[0]);
      check('footer me mera rank #1', /#1/.test(embedOf(i)?.footer?.text ?? ''), embedOf(i)?.footer?.text);
      check('footer me total 14', /14 members tracked/.test(embedOf(i)?.footer?.text ?? ''), embedOf(i)?.footer?.text);
    }
    {
      fs.writeFileSync(XP_FILE, '{}');
      const i = makeInteraction({});
      let threw = null;
      try {
        await byName('leaderboard').execute(i);
      } catch (e) {
        threw = e;
      }
      check('khaali board pe clean message (crash nahi)', threw === null && /Abhi tak kisi ka XP record nahi/.test(content(i)), threw?.message);
    }
    {
      const i = makeInteraction({ guildId: null, httpMode: true });
      await byName('leaderboard').execute(i);
      check('DM me /leaderboard refuse', /sirf server ke andar/.test(content(i)), content(i).slice(0, 80));
    }

    /* ---------- 5. shape ---------- */
    console.log('\n5) Command shape');
    check('2 leveling commands', CMDS.length === 2);
    check('rank + leaderboard present', ['rank', 'leaderboard'].every((n) => !!byName(n)));
    check('dono guildOnly', CMDS.every((c) => c.guildOnly === true));
    check('dono dm_permission false', CMDS.every((c) => c.data.toJSON().dm_permission === false));
    check('/rank ka user option optional hai', byName('rank').data.toJSON().options[0].required !== true);
    check('leveling read-only hai (koi permission gate nahi)', CMDS.every((c) => !c.data.toJSON().default_member_permissions));
  } finally {
    if (backup === null) fs.rmSync(XP_FILE, { force: true });
    else fs.writeFileSync(XP_FILE, backup);
  }

  console.log(`\n${'─'.repeat(56)}`);
  console.log(`Result: ${passed} passed, ${failed} failed`);
  if (failed) {
    console.log('\nFailed checks:');
    for (const f of failures) console.log(`  • ${f}`);
    process.exit(1);
  }
  console.log('🎉 Leveling sab theek hai!');
  process.exit(0);
}

main().catch((err) => {
  console.error('Test crash:', err);
  process.exit(1);
});
