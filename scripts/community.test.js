const assert = require('assert');
const { Collection, PermissionsBitField, PermissionFlagsBits } = require('discord.js');
const moderation = require('../commands/community-mod');
const fun = require('../commands/community-fun');
const { load, save } = require('../store');
const mod = name => moderation.find(c => c.data.name === name);
const f = name => fun.find(c => c.data.name === name);
(async () => {
  for (const c of [...moderation, ...fun]) assert(c.data.toJSON().name);
  let reply;
  const i = { guild: null, reply: async p => { reply = p; } };
  await mod('unban').execute(i); assert.match(reply.content, /Gateway/);
  await f('choose').execute({ options: { getString: () => 'one' }, reply: async p => { reply = p; } }); assert.match(reply.content, /do comma/);
  await f('reverse').execute({ options: { getString: () => '@everyone' }, reply: async p => { reply = p; } }); assert.deepStrictEqual(reply.allowedMentions, { parse: [] });
  const old = load('warnings', {});
  try {
    const highest = { comparePositionTo: () => -1 }; const target = { id: 'target', roles: { highest } };
    const perms = new PermissionsBitField(PermissionFlagsBits.ModerateMembers);
    const x = { guild: { id: 'test-community', ownerId: 'owner', members: { me: { roles: { highest: {} }, permissions: perms }, fetch: async () => target } },
      member: { roles: { highest: {} } }, memberPermissions: perms, appPermissions: perms, user: { id: 'mod' }, client: { user: { id: 'bot' } },
      options: { getUser: () => ({ id: 'target' }), getString: () => 'test reason' }, reply: async p => { reply = p; } };
    await mod('warn').execute(x); assert.match(reply.content, /Warning saved/);
    const entry = load('warnings')['test-community:target'][0]; assert.equal(entry.reason, 'test reason');
    await mod('warnings').execute(x); assert.match(reply.content, /test reason/); assert(reply.ephemeral);
    x.options.getString = () => entry.id; await mod('unwarn').execute(x); assert.match(reply.content, /delete/);
    assert.equal(load('warnings')['test-community:target'].length, 0);
    x.memberPermissions = new PermissionsBitField(0n); await mod('warn').execute(x); assert.match(reply.content, /permission/);
  } finally { save('warnings', old); }
  console.log('Community commands tests passed');
})().catch(err => { console.error(err); process.exitCode = 1; });
