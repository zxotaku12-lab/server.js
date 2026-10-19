/**
 * Settings commands unit tests — /setwelcome /setlogs /setautorole /settings
 * --------------------------------------------------------------------------
 *   npm run test:settings
 *
 * Ye specially isliye zaroori hain kyunki inme do tricky cheezein hain:
 *   1. Gateway mode me channel/role OBJECTS ki validation
 *   2. HTTP mode me object nahi milta, par Discord ke `member.permissions` STRING se
 *      permission check REAL rehna chahiye (lib/perms.js) — warna koi bhi settings
 *      badal sakta, ya command hamesha block ho jaati
 *   3. Cache coherence — command likhe to bot.js ko turant dikhe
 */
const fs = require('fs');
const path = require('path');
const { PermissionFlagsBits } = require('discord.js');

const ROOT = path.join(__dirname, '..');
const CMDS = require(path.join(ROOT, 'commands', 'settings.js'));
const settings = require(path.join(ROOT, 'lib', 'settings.js'));
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

/* ---------------- mocks ---------------- */

const FULL =
  PermissionFlagsBits.ManageGuild |
  PermissionFlagsBits.ManageRoles |
  PermissionFlagsBits.ViewChannel |
  PermissionFlagsBits.SendMessages;

/** Discord HTTP payload jaisa permissions string (decimal bitfield) */
const permsString = (bits) => String(bits);

const textChannel = ({ id = 'ch1', name = 'general', guildId = 'guild1', voice = false } = {}) => ({
  id,
  name,
  guildId,
  type: voice ? 2 : 0,
  toString: () => `<#${id}>`,
  isTextBased: () => !voice,
});

/** HTTP mode me Discord jo `resolved.channels` bhejta hai — object nahi, plain data */
const httpChannel = ({ id = 'ch9', name = 'logs', type = 0 } = {}) => ({ id, name, type });

const role = ({ id = 'r1', name = 'Member', higher = false, everyone = false } = {}) => ({
  id: everyone ? 'guild1' : id,
  name: everyone ? '@everyone' : name,
  toString: () => `<@&${everyone ? 'guild1' : id}>`,
  comparePositionTo: () => (higher ? 1 : -1),
});

const httpRole = ({ id = 'r9', name = 'Member', position = 1 } = {}) => ({ id, name, position });

function makeGuild({ channels = [], roles = [], botHighest = { comparePositionTo: () => 1 } } = {}) {
  return {
    id: 'guild1',
    name: 'Test Server',
    ownerId: 'owner1',
    channels: { cache: new Map(channels.map((c) => [c.id, c])) },
    roles: { cache: new Map(roles.map((r) => [r.id, r])) },
    members: { me: { id: 'bot1', roles: { highest: botHighest }, permissions: { has: () => true } } },
  };
}

function makeInteraction({
  commandName,
  options = {},
  guild = null,
  guildId = 'guild1',
  httpMode = false,
  memberPermsBits = FULL,
  appPermissions = null,
  client = null,
} = {}) {
  const calls = { reply: [], defer: [], edit: [] };
  const member = httpMode
    ? { user: { id: '500', username: 'mod' }, permissions: permsString(memberPermsBits) } // HTTP: string
    : { user: { id: '500', username: 'mod' } };

  return {
    calls,
    commandName,
    guildId: httpMode ? guildId : guild?.id ?? guildId,
    guild: httpMode ? null : guild,
    client,
    user: { id: '500', username: 'mod', tag: 'mod' },
    member,
    memberPermissions: httpMode ? null : { has: (f) => (memberPermsBits & f) === f },
    appPermissions: appPermissions ?? (httpMode ? null : { has: (f) => (FULL & f) === f }),
    inGuild: () => true,
    options: {
      getChannel: (n) => options[n] ?? null,
      getRole: (n) => options[n] ?? null,
      getString: (n) => options[n] ?? null,
      getUser: (n) => options[n] ?? null,
      getInteger: (n) => options[n] ?? null,
    },
    async reply(p) {
      const norm = typeof p === 'string' ? { content: p } : p;
      calls.reply.push(norm);
      seenReplies.push(JSON.stringify(norm));
    },
    async deferReply(o) {
      calls.defer.push(o ?? {});
    },
    async editReply(p) {
      calls.edit.push(typeof p === 'string' ? { content: p } : p);
    },
  };
}

/** Regression sweep ke liye: har reply ka text yahan collect hota hai */
const seenReplies = [];

const byName = (n) => CMDS.find((c) => c.data.name === n);
const text = (i) => i.calls.reply.map((r) => r.content ?? JSON.stringify(r.embeds ?? [])).join(' | ');

async function main() {
  console.log('\n⚙️  Settings commands unit tests\n');

  const backup = fs.existsSync(SETTINGS_FILE) ? fs.readFileSync(SETTINGS_FILE, 'utf8') : null;
  fs.mkdirSync(path.dirname(SETTINGS_FILE), { recursive: true });
  const reset = (obj = {}) => {
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(obj));
    settings.invalidate();
  };

  try {
    /* ---------- 0. shape ---------- */
    console.log('0) Command shape');
    check('4 settings commands', CMDS.length === 4, `got ${CMDS.length}`);
    check('setwelcome/setlogs/setautorole/settings present', ['setwelcome', 'setlogs', 'setautorole', 'settings'].every((n) => !!byName(n)));
    check('sab guildOnly', CMDS.every((c) => c.guildOnly === true));
    const json = CMDS.map((c) => c.data.toJSON());
    check('sab dm_permission false', json.every((j) => j.dm_permission === false));
    const setters = ['setwelcome', 'setlogs', 'setautorole'].map((n) => json.find((j) => j.name === n));
    check('setters pe ManageGuild/ManageRoles permission gate', setters.every((j) => !!j.default_member_permissions), JSON.stringify(setters.map((j) => j.default_member_permissions)));
    check('setwelcome/setlogs = ManageGuild, setautorole = ManageRoles', (() => {
      const [w, l, a] = setters.map((j) => j.default_member_permissions);
      return w === l && w !== a && BigInt(w) === PermissionFlagsBits.ManageGuild && BigInt(a) === PermissionFlagsBits.ManageRoles;
    })(), setters.map((j) => j.default_member_permissions).join(','));
    check('/settings read-only hai (koi permission gate nahi)', !byName('settings').data.toJSON().default_member_permissions);
    check('channel options text/announcement pe restricted', (() => {
      const opt = byName('setwelcome').data.toJSON().options[0];
      return Array.isArray(opt.channel_types) && opt.channel_types.length > 0 && !opt.channel_types.includes(2);
    })());

    /* ---------- 1. /setwelcome (Gateway) ---------- */
    console.log('\n1) /setwelcome — Gateway mode');
    reset();
    {
      const ch = textChannel({ id: 'welcome1' });
      const i = makeInteraction({ commandName: 'setwelcome', guild: makeGuild({ channels: [ch] }), options: { channel: ch } });
      await byName('setwelcome').execute(i);
      check('channel set hua', settings.get('guild1').welcomeChannelId === 'welcome1', JSON.stringify(settings.get('guild1')));
      check('confirm message', /Welcome channel ab <#welcome1> pe set hai/.test(text(i)), text(i).slice(0, 90));
      check('reply ephemeral', i.calls.reply[0]?.ephemeral === true);
    }
    {
      // CACHE COHERENCE — command ke likhne ke baad bot.js wala shared cache fresh hona chahiye
      check('likhne ke baad cache stale NAHI (bot.js ko turant dikhega)', settings.get('guild1').welcomeChannelId === 'welcome1');
      const ch2 = textChannel({ id: 'welcome2' });
      const i = makeInteraction({ commandName: 'setwelcome', guild: makeGuild({ channels: [ch2] }), options: { channel: ch2 } });
      await byName('setwelcome').execute(i);
      check('dobara set karne par overwrite hota hai', settings.get('guild1').welcomeChannelId === 'welcome2');
    }
    {
      // option khaali -> OFF
      const i = makeInteraction({ commandName: 'setwelcome', guild: makeGuild(), options: {} });
      await byName('setwelcome').execute(i);
      check('khaali option -> setting clear', !('welcomeChannelId' in settings.get('guild1')), JSON.stringify(settings.get('guild1')));
      check('OFF confirm message', /\*\*band\*\* kar diya/.test(text(i)), text(i).slice(0, 80));
    }
    {
      reset({ guild1: { welcomeChannelId: 'keepme' } });
      const voice = textChannel({ id: 'voice1', voice: true });
      const i = makeInteraction({ commandName: 'setwelcome', guild: makeGuild({ channels: [voice] }), options: { channel: voice } });
      await byName('setwelcome').execute(i);
      check('voice channel refuse', settings.get('guild1').welcomeChannelId === 'keepme' && /text channel nahi/.test(text(i)), text(i).slice(0, 80));
    }
    {
      reset();
      const ch = textChannel({ id: 'c1' });
      const i = makeInteraction({
        commandName: 'setwelcome',
        guild: makeGuild({ channels: [ch] }),
        options: { channel: ch },
        memberPermsBits: PermissionFlagsBits.ViewChannel, // ManageGuild NAHI
      });
      await byName('setwelcome').execute(i);
      check('bina ManageGuild ke refuse (Gateway)', !settings.get('guild1').welcomeChannelId && /Manage Server/.test(text(i)), text(i).slice(0, 80));
    }
    {
      reset();
      const ch = textChannel({ id: 'c1' });
      const i = makeInteraction({
        commandName: 'setwelcome',
        guild: makeGuild({ channels: [ch] }),
        options: { channel: ch },
        appPermissions: { has: (f) => f === PermissionFlagsBits.ViewChannel }, // SendMessages nahi
      });
      await byName('setwelcome').execute(i);
      check('bot ke paas SendMessages na ho to refuse', !settings.get('guild1').welcomeChannelId && /Send Messages/.test(text(i)), text(i).slice(0, 90));
    }
    {
      reset();
      const otherGuildChannel = textChannel({ id: 'c1', guildId: 'SOME_OTHER_GUILD' });
      const i = makeInteraction({ commandName: 'setwelcome', guild: makeGuild({ channels: [otherGuildChannel] }), options: { channel: otherGuildChannel } });
      await byName('setwelcome').execute(i);
      check('doosre server ka channel refuse', !settings.get('guild1').welcomeChannelId && /doosre server/.test(text(i)));
    }

    /* ---------- 2. /setlogs ---------- */
    console.log('\n2) /setlogs');
    reset();
    {
      const ch = textChannel({ id: 'logs1', name: 'mod-logs' });
      const i = makeInteraction({ commandName: 'setlogs', guild: makeGuild({ channels: [ch] }), options: { channel: ch } });
      await byName('setlogs').execute(i);
      check('log channel set hua', settings.get('guild1').logChannelId === 'logs1');
      check('setwelcome se alag key me gaya (welcome overwrite nahi hua)', !settings.get('guild1').welcomeChannelId);
    }
    {
      const i = makeInteraction({ commandName: 'setlogs', guild: makeGuild(), options: {} });
      await byName('setlogs').execute(i);
      check('khaali option -> logs clear', !settings.get('guild1').logChannelId);
    }

    /* ---------- 3. /setautorole ---------- */
    console.log('\n3) /setautorole');
    reset();
    {
      const r = role({ id: 'role1' });
      const i = makeInteraction({ commandName: 'setautorole', guild: makeGuild({ roles: [r] }), options: { role: r } });
      await byName('setautorole').execute(i);
      check('role set hua', settings.get('guild1').memberRoleId === 'role1');
      check('confirm message', /Auto-role ab <@&role1>/.test(text(i)), text(i).slice(0, 80));
    }
    {
      const everyone = role({ everyone: true });
      const i = makeInteraction({ commandName: 'setautorole', guild: makeGuild(), options: { role: everyone } });
      await byName('setautorole').execute(i);
      check('@everyone refuse', settings.get('guild1').memberRoleId === 'role1' && /@everyone/.test(text(i)), text(i).slice(0, 80));
    }
    {
      const high = role({ id: 'admin1', higher: true });
      const i = makeInteraction({ commandName: 'setautorole', guild: makeGuild(), options: { role: high } });
      await byName('setautorole').execute(i);
      check('bot se upar waala role refuse (hierarchy)', settings.get('guild1').memberRoleId === 'role1' && /upar/.test(text(i)), text(i).slice(0, 90));
    }
    {
      const i = makeInteraction({ commandName: 'setautorole', guild: makeGuild(), options: {} });
      await byName('setautorole').execute(i);
      check('khaali option -> auto-role clear', !settings.get('guild1').memberRoleId);
    }
    {
      reset();
      const r = role({ id: 'role1' });
      const i = makeInteraction({
        commandName: 'setautorole',
        guild: makeGuild({ roles: [r] }),
        options: { role: r },
        memberPermsBits: PermissionFlagsBits.ManageGuild, // ManageRoles NAHI
      });
      await byName('setautorole').execute(i);
      check('bina ManageRoles ke refuse', !settings.get('guild1').memberRoleId && /Manage Roles/.test(text(i)), text(i).slice(0, 80));
    }

    /* ---------- 4. HTTP mode — permission string se REAL enforcement ---------- */
    console.log('\n4) HTTP interactions mode (guild object null)');
    reset();
    {
      const ch = httpChannel({ id: 'http-ch', name: 'welcome' });
      const i = makeInteraction({ commandName: 'setwelcome', httpMode: true, options: { channel: ch } });
      await byName('setwelcome').execute(i);
      check('HTTP mode me bhi setting likhi gayi (graceful degradation)', settings.get('guild1').welcomeChannelId === 'http-ch', JSON.stringify(settings.get('guild1')));
      check('HTTP mode me validation-skip ki note di', /HTTP mode/.test(text(i)), text(i).slice(0, 100));
      // resolved plain object ka toString Object.prototype se aata hai -> "[object Object]" leak na ho
      check('HTTP: channel mention sahi bana (<#id>), "[object Object]" nahi', text(i).includes('<#http-ch>') && !text(i).includes('[object Object]'), text(i).slice(0, 120));
    }
    {
      // member.permissions STRING se permission check — ye lib/perms.js ka core hai
      reset();
      const ch = httpChannel({ id: 'nope' });
      const i = makeInteraction({ commandName: 'setwelcome', httpMode: true, options: { channel: ch }, memberPermsBits: 0n });
      await byName('setwelcome').execute(i);
      check('HTTP: member.permissions=0 -> refuse (koi bhi settings na badal sake)', !settings.get('guild1').welcomeChannelId && /Manage Server/.test(text(i)), text(i).slice(0, 90));
    }
    {
      reset();
      const ch = httpChannel({ id: 'ok-ch' });
      const i = makeInteraction({ commandName: 'setwelcome', httpMode: true, options: { channel: ch }, memberPermsBits: PermissionFlagsBits.ManageGuild });
      await byName('setwelcome').execute(i);
      check('HTTP: sirf ManageGuild bit set -> allow', settings.get('guild1').welcomeChannelId === 'ok-ch');
    }
    {
      reset();
      const r = httpRole({ id: 'http-role' });
      const i = makeInteraction({ commandName: 'setautorole', httpMode: true, options: { role: r }, memberPermsBits: PermissionFlagsBits.ManageRoles });
      await byName('setautorole').execute(i);
      check('HTTP: auto-role set ho gaya', settings.get('guild1').memberRoleId === 'http-role');
      check('HTTP: role mention sahi bana (<@&id>), "[object Object]" nahi', text(i).includes('<@&http-role>') && !text(i).includes('[object Object]'), text(i).slice(0, 120));
    }
    {
      // guildId hi na ho (DM) -> refuse
      const i = makeInteraction({ commandName: 'setwelcome', httpMode: true, guildId: null, options: {} });
      await byName('setwelcome').execute(i);
      check('DM (guildId null) -> clean refuse', /DM me nahi/.test(text(i)), text(i).slice(0, 80));
    }

    /* ---------- 5. /settings viewer ---------- */
    console.log('\n5) /settings');
    {
      const ch = textChannel({ id: 'w1' });
      const logs = textChannel({ id: 'l1' });
      const r = role({ id: 'rr1' });
      reset({ guild1: { welcomeChannelId: 'w1', logChannelId: 'l1', memberRoleId: 'rr1' } });
      const guild = makeGuild({ channels: [ch, logs], roles: [r] });
      const i = makeInteraction({ commandName: 'settings', guild, client: { isReady: () => true } });
      await byName('settings').execute(i);
      const embed = i.calls.reply[0]?.embeds?.[0];
      const raw = typeof embed?.toJSON === 'function' ? embed.toJSON() : embed;
      const fields = JSON.stringify(raw?.fields ?? []);
      check('embed me teeno settings dikhti hain', fields.includes('w1') && fields.includes('l1') && fields.includes('rr1'), fields.slice(0, 150));
      check('Gateway online dikhaya', fields.includes('online'));
      check('/settings kisi ko bhi dikhta hai (ephemeral nahi)', i.calls.reply[0]?.ephemeral !== true);
    }
    {
      reset({ guild1: { welcomeChannelId: 'deleted-channel', memberRoleId: 'deleted-role' } });
      const i = makeInteraction({ commandName: 'settings', guild: makeGuild(), client: { isReady: () => false } });
      await byName('settings').execute(i);
      const embed = i.calls.reply[0]?.embeds?.[0];
      const raw = typeof embed?.toJSON === 'function' ? embed.toJSON() : embed;
      const fields = JSON.stringify(raw?.fields ?? []);
      check('delete ho chuka channel/role pe warning dikhti hai', fields.includes('nahi mila'), fields.slice(0, 160));
      check('Gateway offline warning', fields.includes('offline'));
    }
    {
      reset();
      const i = makeInteraction({ commandName: 'settings', guild: makeGuild(), client: null });
      await byName('settings').execute(i);
      const embed = i.calls.reply[0]?.embeds?.[0];
      const raw = typeof embed?.toJSON === 'function' ? embed.toJSON() : embed;
      check('khaali settings pe crash nahi, "set nahi" dikhta hai', JSON.stringify(raw?.fields ?? []).includes('set nahi'));
    }

    {
      // HTTP mode: guild object null -> "channel nahi mila" warning JHOOTHI hogi
      reset({ guild1: { welcomeChannelId: 'http-ch', logChannelId: 'http-logs', memberRoleId: 'http-role' } });
      const i = makeInteraction({ commandName: 'settings', httpMode: true, guildId: 'guild1', client: null });
      await byName('settings').execute(i);
      const embed = i.calls.reply[0]?.embeds?.[0];
      const raw = typeof embed?.toJSON === 'function' ? embed.toJSON() : embed;
      const fields = JSON.stringify(raw?.fields ?? []);
      check('HTTP /settings: mentions dikhte hain', fields.includes('<#http-ch>') && fields.includes('<@&http-role>'), fields.slice(0, 160));
      check('HTTP /settings: jhoothi "nahi mila" warning NAHI aati', !fields.includes('nahi mila'), fields.slice(0, 160));
      check('HTTP /settings: Gateway offline batata hai', fields.includes('offline'));
    }

    /* ---------- 6. multi-guild isolation ---------- */
    console.log('\n6) Multi-guild isolation');
    {
      reset({ guildA: { welcomeChannelId: 'a-ch' }, guildB: { welcomeChannelId: 'b-ch' } });
      check('guild A ki settings alag', settings.get('guildA').welcomeChannelId === 'a-ch');
      check('guild B ki settings alag', settings.get('guildB').welcomeChannelId === 'b-ch');
      const ch = textChannel({ id: 'new-a', guildId: 'guildA' });
      const i = makeInteraction({ commandName: 'setwelcome', guild: { ...makeGuild({ channels: [ch] }), id: 'guildA' }, guildId: 'guildA', options: { channel: ch } });
      await byName('setwelcome').execute(i);
      check('A change karne se B affect nahi hua', settings.get('guildA').welcomeChannelId === 'new-a' && settings.get('guildB').welcomeChannelId === 'b-ch');
      const foreign = textChannel({ id: 'b-ch', guildId: 'guildB' });
      const i2 = makeInteraction({ commandName: 'setwelcome', guild: { ...makeGuild({ channels: [foreign] }), id: 'guildA' }, guildId: 'guildA', options: { channel: foreign } });
      await byName('setwelcome').execute(i2);
      check('guildA ki command me guildB ka channel refuse', settings.get('guildA').welcomeChannelId === 'new-a' && /doosre server/.test(text(i2)));
    }
    /* ---------- 7. regression sweep ---------- */
    console.log('\n7) Regression sweep');
    check('kisi bhi reply me "[object Object]" leak nahi hua', !seenReplies.some((t) => t.includes('[object Object]')),
      (seenReplies.find((t) => t.includes('[object Object]')) ?? '').slice(0, 120));
    check('kisi bhi reply me "undefined"/"NaN" leak nahi hua', !seenReplies.some((t) => /undefined|NaN/.test(t)),
      (seenReplies.find((t) => /undefined|NaN/.test(t)) ?? '').slice(0, 120));
  } finally {
    if (backup === null) fs.rmSync(SETTINGS_FILE, { force: true });
    else fs.writeFileSync(SETTINGS_FILE, backup);
    settings.invalidate();
  }

  console.log(`\n${'─'.repeat(56)}`);
  console.log(`Result: ${passed} passed, ${failed} failed`);
  if (failed) {
    console.log('\nFailed checks:');
    for (const f of failures) console.log(`  • ${f}`);
    process.exit(1);
  }
  console.log('🎉 Settings commands sab theek hain!');
  process.exit(0);
}

main().catch((err) => {
  console.error('Test crash:', err);
  process.exit(1);
});
