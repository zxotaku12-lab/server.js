const { SlashCommandBuilder, PermissionFlagsBits } = require('discord.js');
const { hasMemberPerm, hasBotPerm } = require('../lib/perms');

const perm = PermissionFlagsBits.ManageRoles;
const base = (name, description) => new SlashCommandBuilder().setName(name).setDescription(description)
  .setDMPermission(false).setDefaultMemberPermissions(perm);
const deny = (i, content) => i.reply({ content, ephemeral: true });
function check(i, role) {
  if (!i.guild || !i.guild.members.me) return 'Gateway bot online hona chahiye.';
  if (!hasMemberPerm(i, perm) || !hasBotPerm(i, perm)) return 'Tumhe aur bot ko Manage Roles permission chahiye.';
  if (role && (role.id === i.guild.id || role.managed || role.position >= i.guild.members.me.roles.highest.position)) return 'Ye role bot manage nahi kar sakta; role hierarchy check karo.';
  if (role && i.user.id !== i.guild.ownerId && (!i.member.roles?.highest || role.position >= i.member.roles.highest.position)) return 'Tum apne highest role ke barabar ya upar ka role manage nahi kar sakte.';
  return null;
}
const roleOption = o => o.setName('role').setDescription('Role').setRequired(true);
const userOption = o => o.setName('user').setDescription('Member').setRequired(true);
module.exports = [
  {
    guildOnly: true,
    data: base('role-create', 'Naya role banao').addStringOption(o => o.setName('name').setDescription('Role ka naam').setRequired(true).setMaxLength(100)),
    async execute(i) {
      const error = check(i); if (error) return deny(i, error);
      const role = await i.guild.roles.create({ name: i.options.getString('name'), permissions: [], reason: `Requested by ${i.user.id}` });
      return i.reply({ content: `✅ Role **${role.name}** ban gaya.`, allowedMentions: { parse: [] } });
    },
  },
  {
    guildOnly: true,
    data: base('role-delete', 'Role delete karo').addRoleOption(roleOption),
    async execute(i) {
      const role = i.options.getRole('role'); const error = check(i, role); if (error) return deny(i, error);
      await role.delete(`Requested by ${i.user.id}`);
      return i.reply({ content: `✅ Role **${role.name}** delete ho gaya.`, allowedMentions: { parse: [] } });
    },
  },
  ...['add', 'remove'].map(action => ({
    guildOnly: true,
    data: base(`role-${action}`, `Member se role ${action} karo`).addUserOption(userOption).addRoleOption(roleOption),
    async execute(i) {
      const role = i.options.getRole('role'); const error = check(i, role); if (error) return deny(i, error);
      const member = await i.guild.members.fetch(i.options.getUser('user').id).catch(() => null);
      if (!member) return deny(i, 'Member nahi mila.');
      if (member.id === i.guild.ownerId || (i.user.id !== i.guild.ownerId && member.id !== i.user.id && member.roles.highest.comparePositionTo(i.member.roles.highest) >= 0)) return deny(i, 'Is member ki role hierarchy ke kaaran action allowed nahi hai.');
      await member.roles[action](role, `Requested by ${i.user.id}`);
      return i.reply({ content: `✅ Role ${action} ho gaya.`, allowedMentions: { parse: [] } });
    },
  })),
];
