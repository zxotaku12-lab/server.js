const assert = require('assert');
const { PermissionFlagsBits } = require('discord.js');
const roles = require('../commands/roles');
const giveawayCommands = require('../commands/giveaway');
const giveaways = require('../lib/giveaways');
const { load, save } = require('../store');
(async () => {
  for (const c of [...roles, ...giveawayCommands]) {
    const json = c.data.toJSON(); assert(json.default_member_permissions); assert.strictEqual(json.dm_permission, false);
  }
  let reply;
  const interaction = { guild: null, reply: async x => { reply = x; } };
  await roles[0].execute(interaction); assert.match(reply.content, /Gateway/);
  let created = false;
  const denied = { guild: { members: { me: {} } }, memberPermissions: { has: () => false }, reply: async x => { reply = x; }, options: { getString: () => 'test' } };
  denied.guild.roles = { create: () => { created = true; } };
  await roles[0].execute(denied); assert(!created); assert.match(reply.content, /Manage Roles/);
  const original = load('giveaways', {});
  try {
    const id = 'test-giveaway-id';
    giveaways.create({ id, guildId: 'g', channelId: 'c' }, 'prize', Date.now() + 60000, 1);
    const i = { message: { id }, guildId: 'g', user: { id: 'u', bot: false }, reply: async x => { reply = x; } };
    await giveaways.enter(i); assert.deepStrictEqual(giveaways.read()[id].entrants, ['u']);
    await giveaways.enter(i); assert.deepStrictEqual(giveaways.read()[id].entrants, []);
    i.guildId = 'other'; await giveaways.enter(i); assert.deepStrictEqual(giveaways.read()[id].entrants, []);
    let sent = 0;
    const client = { channels: { fetch: async () => ({ messages: { fetch: async () => ({ edit: async () => {} }) }, send: async () => { sent++; } }) } };
    assert.strictEqual(await giveaways.finish(client, id), true); assert.strictEqual(await giveaways.finish(client, id), false); assert.strictEqual(sent, 1);
  } finally { save('giveaways', original); }
  console.log('Role and giveaway tests passed');
})().catch(err => { console.error(err); process.exitCode = 1; });
