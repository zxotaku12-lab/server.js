const assert = require('assert');
const { Collection, PermissionsBitField, PermissionFlagsBits, ChannelType } = require('discord.js');
const tickets = require('../lib/tickets');
const settings = require('../lib/settings');
const cmd = require('../commands/ticket');
(async () => {
  assert(cmd.data.toJSON().default_member_permissions);
  const uid = '123456789012345678', gid = '223456789012345678', bid = '323456789012345678', rid = '423456789012345678';
  let replied, created, deleted = false, sent;
  const channels = new Collection(); const perms = new PermissionsBitField(PermissionFlagsBits.ManageChannels);
  const guild = { id: gid, members: { me: { id: bid, permissions: perms } }, roles: { cache: new Collection([[rid, {}]]) }, channels: { cache: channels, create: async data => { created = data; return { id: '555', send: async msg => { sent = msg; }, delete: async () => {} }; } } };
  settings.set(gid, { ticketStaffRoleId: rid, ticketCategoryId: null });
  try {
    const i = { guild, user: { id: uid }, deferReply: async function () { this.deferred = true; }, editReply: async text => { replied = text; }, reply: async text => { replied = text; } };
    await tickets.open(i); assert.equal(created.type, ChannelType.GuildText); assert.equal(created.topic, `ticket-owner:${uid}`);
    assert(created.permissionOverwrites.some(x => x.id === gid && x.deny.includes(PermissionFlagsBits.ViewChannel)));
    assert(created.permissionOverwrites.some(x => x.id === rid)); assert.equal(sent.components[0].components[0].data.custom_id, 'ticket-close'); assert.match(replied, /Ticket khul/);
    channels.set('existing', { id: 'existing', topic: `ticket-owner:${uid}` }); created = null;
    await tickets.open(i); assert.equal(created, null); assert.match(replied, /pehle se/);
    const channel = { topic: `ticket-owner:${uid}`, delete: async () => { deleted = true; } };
    const c = { guild, channel, user: { id: 'other' }, member: { roles: { cache: new Collection() } }, memberPermissions: new PermissionsBitField(0n), reply: async p => { replied = p; }, deferReply: async () => {}, editReply: async () => {} };
    await tickets.close(c); assert.equal(deleted, false); assert.match(replied.content, /Sirf/);
    c.user.id = uid; await tickets.close(c); assert(deleted);
    console.log('Ticket tests passed');
  } finally { settings.unset(gid, ['ticketStaffRoleId', 'ticketCategoryId']); }
})().catch(err => { console.error(err); process.exitCode = 1; });
