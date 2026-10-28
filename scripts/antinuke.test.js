const assert = require('assert');
const { AuditLogEvent, PermissionsBitField, PermissionFlagsBits } = require('discord.js');
const settings = require('../lib/settings');
const anti = require('../lib/antinuke');
(async () => {
  const id = 'anti-test-guild'; const old = { ...settings.get(id) }; let messages = [];
  const guild = { id, ownerId: 'owner', client: { user: { id: 'bot' } }, channels: { cache: new Map([['log', { isTextBased: () => true, send: async payload => messages.push(payload) }]]) } };
  try {
    settings.set(id, { antiNuke: true, antiNukeLimit: 3, antiNukeAction: 'alert', logChannelId: 'log' });
    const entry = (n, executorId = 'user') => ({ id: String(n), executorId, action: AuditLogEvent.ChannelDelete, createdTimestamp: 100000 });
    assert.strictEqual(await anti.handle(entry(1), guild, 100000), false);
    assert.strictEqual(await anti.handle(entry(1), guild, 100000), false);
    await anti.handle(entry(2, 'owner'), guild, 100000);
    await anti.handle(entry(3), guild, 100000);
    assert.strictEqual(await anti.handle(entry(4), guild, 100000), true);
    assert.strictEqual(messages.length, 1); assert.deepStrictEqual(messages[0].allowedMentions, { parse: [] });
    await anti.handle(entry(5), guild, 100000); assert.strictEqual(messages.length, 1);
    anti._reset(); messages = [];
    settings.set(id, { antiNukeLimit: 2, antiNukeAction: 'strip' });
    let removed = false;
    const role = { id: 'role', managed: false, position: 1, permissions: new PermissionsBitField(PermissionFlagsBits.BanMembers) };
    const roles = new (require('discord.js').Collection)([['role', role]]);
    guild.members = { me: { permissions: new PermissionsBitField(PermissionFlagsBits.ManageRoles), roles: { highest: { position: 10 } } }, fetch: async () => ({ roles: { highest: { comparePositionTo: () => -1 }, cache: roles, remove: async r => { removed = r.has('role'); } } }) };
    await anti.handle(entry(6), guild, 100000); await anti.handle(entry(7), guild, 100000); assert(removed); assert.strictEqual(messages.length, 1);
    console.log('Anti-nuke tests passed');
  } finally { settings.unset(id, Object.keys(settings.get(id))); settings.set(id, old); anti._reset(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
