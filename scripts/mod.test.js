/**
 * Moderation unit tests — mock guild ke saath
 * -------------------------------------------
 *   npm run test:mod
 *
 * Moderation commands ko asli `guild` object chahiye, jo is sandbox se Discord ke bina
 * nahi mil sakta. Isliye yahan guild/member/channel/permissions ke MOCKS banaye gaye hain
 * aur command ke execute() ko directly call kiya jaata hai — taaki asli logic
 * (permission checks, role hierarchy, clamp, audit reason, log channel) test ho.
 *
 * Exit code 0 = sab pass, 1 = kuch fail.
 */
const fs = require('fs');
const path = require('path');
const { PermissionFlagsBits } = require('discord.js');

const ROOT = path.join(__dirname, '..');
const MOD = require(path.join(ROOT, 'commands', 'mod.js'));
const settingsLib = require(path.join(ROOT, 'lib', 'settings.js'));
const SETTINGS_FILE = path.join(ROOT, 'data', 'settings.json');

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

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

class FakeCollection extends Map {
  filter(fn) {
    const out = new FakeCollection();
    for (const [k, v] of this) if (fn(v, k)) out.set(k, v);
    return out;
  }
}

const perms = (...allowed) => ({ has: (flag) => allowed.some((a) => a === flag) });
const ALL_PERMS = perms(
  PermissionFlagsBits.KickMembers,
  PermissionFlagsBits.BanMembers,
  PermissionFlagsBits.ModerateMembers,
  PermissionFlagsBits.ManageMessages
);

function makeTarget({ id = '900', username = 'baduser', bot = false } = {}) {
  return { id, username, bot, tag: username, toString: () => `<@${id}>` };
}

/** Guild member jo kick/ban/timeout ho sakta hai */
function makeMember({ target, hierarchy = -1, timeoutThrows = null } = {}) {
  const calls = { timeout: [] };
  return {
    id: target.id,
    user: target,
    calls,
    roles: { highest: { comparePositionTo: () => hierarchy } },
    kickable: true,
    bannable: true,
    async timeout(ms, reason) {
      if (timeoutThrows) throw new Error(timeoutThrows);
      calls.timeout.push({ ms, reason });
    },
  };
}

function makeChannel({ bulkDeleteThrows = null, messages = [] } = {}) {
  const calls = { bulkDelete: [], fetch: [] };
  const collection = new FakeCollection(messages.map((m, i) => [String(i), m]));
  return {
    calls,
    id: 'chan1',
    toString: () => '<#chan1>',
    isTextBased: () => true,
    messages: {
      async fetch(opts) {
        calls.fetch.push(opts);
        return collection;
      },
    },
    async bulkDelete(target, filterOld) {
      if (bulkDeleteThrows) throw new Error(bulkDeleteThrows);
      calls.bulkDelete.push({ target, filterOld });
      if (typeof target === 'number') {
        const out = new Map();
        for (let i = 0; i < target; i++) out.set(String(i), { id: String(i) });
        return out;
      }
      return new Map(target);
    },
  };
}

function makeGuild({
  id = 'guild1',
  ownerId = 'owner1',
  member = null,
  fetchThrows = false,
  botPerms = ALL_PERMS,
  logChannel = null,
} = {}) {
  const calls = { kick: [], ban: [], logSends: [] };
  const channels = new Map();
  if (logChannel) channels.set('logchan', { isTextBased: () => true, send: async (p) => { calls.logSends.push(p); } });

  return {
    id,
    name: 'Test Server',
    ownerId,
    calls,
    members: {
      me: { id: 'bot1', permissions: botPerms, roles: { highest: { comparePositionTo: () => 1 } } },
      async fetch(userId) {
        if (fetchThrows) throw new Error('Unknown Member');
        if (!member || member.id !== userId) throw new Error('Unknown Member');
        return member;
      },
      async kick(m, reason) {
        calls.kick.push({ id: m.id, reason });
      },
      async ban(m, opts) {
        calls.ban.push({ id: m.id, ...opts });
      },
    },
    channels: { cache: channels },
  };
}

function makeInteraction({
  commandName,
  options = {},
  guild = null,
  channel = null,
  memberPermissions = ALL_PERMS,
  appPermissions = ALL_PERMS,
  user = { id: '500', username: 'moderator', tag: 'moderator' },
  httpMode = false,
} = {}) {
  const calls = { reply: [], defer: [], edit: [] };
  return {
    calls,
    commandName,
    user,
    member: { user, id: user.id },
    guild: httpMode ? null : guild,
    channel: httpMode ? null : channel,
    memberPermissions: httpMode ? null : memberPermissions,
    appPermissions: httpMode ? null : appPermissions,
    inGuild: () => !httpMode && !!guild,
    options: {
      getUser: (n, req) => {
        const v = options[n] ?? null;
        if (!v && req) throw new Error(`missing required option ${n}`);
        return v;
      },
      getString: (n) => options[n] ?? null,
      getInteger: (n, req) => {
        const v = options[n] ?? null;
        if (v === null && req) throw new Error(`missing required option ${n}`);
        return v;
      },
    },
    async reply(payload) {
      calls.reply.push(typeof payload === 'string' ? { content: payload } : payload);
    },
    async deferReply(opts) {
      calls.defer.push(opts ?? {});
    },
    async editReply(payload) {
      calls.edit.push(typeof payload === 'string' ? { content: payload } : payload);
    },
  };
}

const byName = (name) => MOD.find((c) => c.data.name === name);
const content = (i) => (i.calls.reply[0]?.content ?? '') + (i.calls.edit[0]?.content ?? '');

/* ------------------------------------------------------------------ */

async function main() {
  console.log('\n🛡️  Moderation unit tests (mock guild)\n');

  // settings.json ko temporarily control karo (log-channel test ke liye), baad me restore.
  // lib/settings.js in-memory cache rakhta hai (bot.js har event pe disk na padhe),
  // isliye bahar se likhne ke baad invalidate() zaroori hai.
  const backup = fs.existsSync(SETTINGS_FILE) ? fs.readFileSync(SETTINGS_FILE, 'utf8') : null;
  fs.mkdirSync(path.dirname(SETTINGS_FILE), { recursive: true });
  const writeSettings = (obj) => {
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(obj));
    settingsLib.invalidate();
  };

  try {
    /* ---------- 0. shape ---------- */
    console.log('0) Command shape');
    check('4 mod commands exported', MOD.length === 4, `got ${MOD.length}`);
    check('sab guildOnly: true', MOD.every((c) => c.guildOnly === true));
    check('kick/ban/purge/timeout present', ['kick', 'ban', 'purge', 'timeout'].every((n) => !!byName(n)));
    const json = MOD.map((c) => c.data.toJSON());
    check('sab commands valid Discord JSON', json.every((j) => j.name && j.description && Array.isArray(j.options)));
    check('default_member_permissions set (Discord UI me hi restrict honge)', json.every((j) => j.default_member_permissions));
    check('dm_permission false', json.every((j) => j.dm_permission === false));

    /* ---------- 1. kick ---------- */
    console.log('\n1) /kick');
    {
      const target = makeTarget();
      const member = makeMember({ target });
      const guild = makeGuild({ member });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target, reason: 'spam' } });
      await byName('kick').execute(i);
      check('kick actually hua', guild.calls.kick.length === 1, JSON.stringify(guild.calls.kick));
      check('audit reason me moderator ka id hai', /moderator \(500\): spam/.test(guild.calls.kick[0]?.reason ?? ''), guild.calls.kick[0]?.reason);
      check('reply ephemeral hai', i.calls.reply[0]?.ephemeral === true);
      check('reply me confirm message', /kick kar diya/.test(content(i)) && content(i).includes('spam'));
    }
    {
      const target = makeTarget();
      const guild = makeGuild({ member: makeMember({ target }) });
      const i = makeInteraction({
        commandName: 'kick',
        guild,
        options: { user: target },
        memberPermissions: perms(PermissionFlagsBits.BanMembers), // kick perm nahi
      });
      await byName('kick').execute(i);
      check('bina Kick Members perm ke kick NAHI hota', guild.calls.kick.length === 0);
      check('permission denial message', /Kick Members/.test(content(i)), content(i).slice(0, 80));
    }
    {
      const target = makeTarget({ bot: true });
      const guild = makeGuild({ member: makeMember({ target }) });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target } });
      await byName('kick').execute(i);
      check('bot target pe kick refuse', guild.calls.kick.length === 0 && /Bot pe/.test(content(i)));
    }
    {
      const target = makeTarget({ id: '500', username: 'moderator' }); // khud
      const guild = makeGuild({ member: makeMember({ target }) });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target } });
      await byName('kick').execute(i);
      check('self-kick refuse', guild.calls.kick.length === 0 && /khud ko/.test(content(i)));
    }
    {
      const target = makeTarget({ id: '777', username: 'ghost' });
      const guild = makeGuild({ member: makeMember({ target: makeTarget({ id: 'other' }) }) });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target } });
      await byName('kick').execute(i);
      check('guild me na hone waale user pe kick refuse', guild.calls.kick.length === 0 && /server me nahi hai/.test(content(i)));
    }
    {
      const target = makeTarget();
      const guild = makeGuild({ member: makeMember({ target, hierarchy: 1 }), ownerId: 'owner1' });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target } });
      await byName('kick').execute(i);
      check('higher-role target pe kick refuse (hierarchy)', guild.calls.kick.length === 0 && /upar/.test(content(i)), content(i).slice(0, 90));
    }
    {
      const target = makeTarget({ id: 'owner1', username: 'serverowner' });
      const guild = makeGuild({ member: makeMember({ target }), ownerId: 'owner1' });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target } });
      await byName('kick').execute(i);
      check('server owner pe kick refuse', guild.calls.kick.length === 0);
    }
    {
      const target = makeTarget();
      const guild = makeGuild({ member: makeMember({ target }), botPerms: perms(PermissionFlagsBits.KickMembers) });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target } });
      // bot ke paas KickMembers hai -> allowed
      await byName('kick').execute(i);
      check('bot ke paas perm ho to kick hota hai', guild.calls.kick.length === 1);
    }
    {
      const target = makeTarget();
      const guild = makeGuild({ member: makeMember({ target }), botPerms: perms() }); // bot ke paas kuch nahi
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target }, appPermissions: perms() });
      await byName('kick').execute(i);
      check('bot ke paas perm na ho to refuse (aage badh ke API error nahi)', guild.calls.kick.length === 0 && /Mere paas/.test(content(i)));
    }

    /* ---------- 2. ban ---------- */
    console.log('\n2) /ban');
    {
      const target = makeTarget({ id: '901', username: 'spammer' });
      const guild = makeGuild({ member: makeMember({ target }) });
      const i = makeInteraction({ commandName: 'ban', guild, options: { user: target, reason: 'raid', delete_days: 3 } });
      await byName('ban').execute(i);
      check('ban hua', guild.calls.ban.length === 1);
      check('delete_days -> deleteMessageSeconds (3 din = 259200)', guild.calls.ban[0]?.deleteMessageSeconds === 259200, String(guild.calls.ban[0]?.deleteMessageSeconds));
      check('ban audit reason', /moderator \(500\): raid/.test(guild.calls.ban[0]?.reason ?? ''));
    }
    {
      const target = makeTarget({ id: '902' });
      const guild = makeGuild({ member: makeMember({ target }) });
      const i = makeInteraction({ commandName: 'ban', guild, options: { user: target } }); // delete_days default
      await byName('ban').execute(i);
      check('delete_days default 0', guild.calls.ban[0]?.deleteMessageSeconds === 0, String(guild.calls.ban[0]?.deleteMessageSeconds));
    }
    {
      const target = makeTarget({ id: '903' });
      const guild = makeGuild({ member: makeMember({ target }) });
      const i = makeInteraction({ commandName: 'ban', guild, options: { user: target }, memberPermissions: perms() });
      await byName('ban').execute(i);
      check('bina Ban Members perm ke ban nahi', guild.calls.ban.length === 0 && /Ban Members/.test(content(i)));
    }

    /* ---------- 3. timeout ---------- */
    console.log('\n3) /timeout');
    {
      const target = makeTarget({ id: '904' });
      const member = makeMember({ target });
      const guild = makeGuild({ member });
      const i = makeInteraction({ commandName: 'timeout', guild, options: { user: target, minutes: 10, reason: 'toxic' } });
      await byName('timeout').execute(i);
      check('timeout 10 min = 600000 ms', member.calls.timeout[0]?.ms === 600000, String(member.calls.timeout[0]?.ms));
      check('timeout reason me actor', /moderator \(500\): toxic/.test(member.calls.timeout[0]?.reason ?? ''));
    }
    {
      const target = makeTarget({ id: '905' });
      const member = makeMember({ target });
      const guild = makeGuild({ member });
      const i = makeInteraction({ commandName: 'timeout', guild, options: { user: target, minutes: 0 } });
      await byName('timeout').execute(i);
      check('minutes:0 -> timeout hata diya (null)', member.calls.timeout[0]?.ms === null, String(member.calls.timeout[0]?.ms));
      check('removal message', /hata diya/.test(content(i)), content(i).slice(0, 80));
    }
    {
      const target = makeTarget({ id: '906' });
      const member = makeMember({ target });
      const guild = makeGuild({ member });
      const i = makeInteraction({ commandName: 'timeout', guild, options: { user: target, minutes: 5 }, memberPermissions: perms(PermissionFlagsBits.KickMembers) });
      await byName('timeout').execute(i);
      check('bina ModerateMembers perm ke timeout nahi', member.calls.timeout.length === 0 && /Moderate Members/.test(content(i)));
    }

    /* ---------- 4. purge ---------- */
    console.log('\n4) /purge');
    {
      const guild = makeGuild({});
      const channel = makeChannel();
      const i = makeInteraction({ commandName: 'purge', guild, channel, options: { count: 25 } });
      await byName('purge').execute(i);
      check('bulkDelete 25 ke saath call hua', channel.calls.bulkDelete[0]?.target === 25, String(channel.calls.bulkDelete[0]?.target));
      check('filterOld=true (14 din se purane skip)', channel.calls.bulkDelete[0]?.filterOld === true);
      check('deferReply hua (bulkDelete me time lagta hai)', i.calls.defer.length === 1);
      check('result message me count', /\*\*25\*\* messages delete/.test(content(i)), content(i).slice(0, 80));
    }
    {
      const guild = makeGuild({});
      const channel = makeChannel();
      const i = makeInteraction({ commandName: 'purge', guild, channel, options: { count: 5000 } }); // API limit se zyada
      await byName('purge').execute(i);
      check('count 100 pe CLAMP hota hai (Discord hard limit)', channel.calls.bulkDelete[0]?.target === 100, String(channel.calls.bulkDelete[0]?.target));
    }
    {
      const author = { id: 'u1' };
      const other = { id: 'u2' };
      const msgs = [{ id: '1', author }, { id: '2', author: other }, { id: '3', author }, { id: '4', author: other }];
      const guild = makeGuild({});
      const channel = makeChannel({ messages: msgs });
      const i = makeInteraction({ commandName: 'purge', guild, channel, options: { count: 4, user: { id: 'u1', username: 'u1' } } });
      await byName('purge').execute(i);
      check('user filter: messages.fetch call hua', channel.calls.fetch.length === 1);
      check('user filter: sirf us user ke 2 messages delete hue', channel.calls.bulkDelete[0]?.target?.size === 2, String(channel.calls.bulkDelete[0]?.target?.size));
      check('result me filtered count', /\*\*2\*\*/.test(content(i)), content(i).slice(0, 90));
    }
    {
      const guild = makeGuild({});
      const channel = makeChannel({ bulkDeleteThrows: 'You can only bulk delete messages between 14 days old and less than 14 days old.' });
      const i = makeInteraction({ commandName: 'purge', guild, channel, options: { count: 10 } });
      let threw = null;
      try {
        await byName('purge').execute(i);
      } catch (e) {
        threw = e;
      }
      check('bulkDelete fail hone pe command crash NAHI karta', threw === null, threw?.message);
      check('error user tak pahunchta hai (editReply)', /Purge fail hua/.test(i.calls.edit[0]?.content ?? ''), i.calls.edit[0]?.content?.slice(0, 60));
    }
    {
      const guild = makeGuild({});
      const channel = makeChannel();
      const i = makeInteraction({ commandName: 'purge', guild, channel, options: { count: 10 }, memberPermissions: perms() });
      await byName('purge').execute(i);
      check('bina ManageMessages ke purge nahi', channel.calls.bulkDelete.length === 0 && /Manage Messages/.test(content(i)));
    }
    {
      const guild = makeGuild({});
      const i = makeInteraction({ commandName: 'purge', guild, channel: { id: 'voice', isTextBased: () => false }, options: { count: 10 } });
      let threw = null;
      try {
        await byName('purge').execute(i);
      } catch (e) {
        threw = e;
      }
      check('non-text channel pe clean refuse (no crash)', threw === null && /text-based nahi/.test(content(i)));
    }

    /* ---------- 5. HTTP mode (guild null) ---------- */
    console.log('\n5) HTTP interactions mode (guild = null)');
    for (const name of ['kick', 'ban', 'timeout']) {
      const i = makeInteraction({ commandName: name, httpMode: true, options: { user: makeTarget(), minutes: 5 } });
      let threw = null;
      try {
        await byName(name).execute(i);
      } catch (e) {
        threw = e;
      }
      check(`/${name} HTTP mode pe crash nahi, clear Gateway message`, threw === null && /Gateway bot/.test(content(i)), threw?.message ?? content(i).slice(0, 60));
    }
    {
      const i = makeInteraction({ commandName: 'purge', httpMode: true, options: { count: 5 } });
      let threw = null;
      try {
        await byName('purge').execute(i);
      } catch (e) {
        threw = e;
      }
      check('/purge HTTP mode pe crash nahi, clear Gateway message', threw === null && /Gateway bot/.test(content(i)), threw?.message ?? content(i).slice(0, 60));
    }

    /* ---------- 6. log channel ---------- */
    console.log('\n6) Log channel integration');
    {
      writeSettings({ guild1: { logChannelId: 'nope-not-in-cache' } });
      const target = makeTarget({ id: '910' });
      const guild = makeGuild({ member: makeMember({ target }), logChannel: true });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target, reason: 'test' } });
      let threw = null;
      try {
        await byName('kick').execute(i);
      } catch (e) {
        threw = e;
      }
      check('settings me galat logChannelId ho to crash nahi hota', threw === null && guild.calls.kick.length === 1, threw?.message);
    }
    {
      writeSettings({ guild1: { logChannelId: 'logchan' } });
      const target = makeTarget({ id: '911', username: 'logged' });
      const guild = makeGuild({ member: makeMember({ target }), logChannel: true });
      const i = makeInteraction({ commandName: 'kick', guild, options: { user: target, reason: 'log test' } });
      await byName('kick').execute(i);
      check('log channel pe embed gaya', guild.calls.logSends.length === 1, String(guild.calls.logSends.length));
      // EmbedBuilder ka raw data .toJSON()/.data me hota hai, direct .fields par nahi
      const raw = guild.calls.logSends[0]?.embeds?.[0];
      const embed = typeof raw?.toJSON === 'function' ? raw.toJSON() : raw?.data ?? raw;
      const fieldsJson = JSON.stringify(embed?.fields ?? []);
      check('log embed me user + reason + moderator hai',
        fieldsJson.includes('logged') && fieldsJson.includes('log test') && fieldsJson.includes('moderator'),
        fieldsJson.slice(0, 160));
    }
    {
      writeSettings({});
      const target = makeTarget({ id: '912' });
      const guild = makeGuild({ member: makeMember({ target }), logChannel: true });
      const i = makeInteraction({ commandName: 'ban', guild, options: { user: target } });
      let threw = null;
      try {
        await byName('ban').execute(i);
      } catch (e) {
        threw = e;
      }
      check('log channel set na ho to bhi ban kaam karta hai', threw === null && guild.calls.ban.length === 1 && guild.calls.logSends.length === 0);
    }
  } finally {
    if (backup === null) fs.rmSync(SETTINGS_FILE, { force: true });
    else fs.writeFileSync(SETTINGS_FILE, backup);
    settingsLib.invalidate();
  }

  console.log(`\n${'─'.repeat(56)}`);
  console.log(`Result: ${passed} passed, ${failed} failed`);
  if (failed) {
    console.log('\nFailed checks:');
    for (const f of failures) console.log(`  • ${f}`);
    process.exit(1);
  }
  console.log('🎉 Moderation logic sab theek hai!');
  process.exit(0);
}

main().catch((err) => {
  console.error('Test crash:', err);
  process.exit(1);
});
