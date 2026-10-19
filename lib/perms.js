/**
 * Permission helpers — Gateway aur HTTP dono mode me kaam karte hain
 * -----------------------------------------------------------------
 * Gateway (discord.js):  interaction.memberPermissions / interaction.appPermissions
 *                        -> PermissionsBitField objects
 *
 * HTTP interactions:     wo objects nahi hote, LEKIN Discord payload me
 *                        `member.permissions` (string) bhejta hai — member ki
 *                        channel+guild permissions ka computed bitfield.
 *                        Usse hum yahan PermissionsBitField bana lete hain, isliye
 *                        permission checks HTTP mode me bhi REAL hote hain
 *                        (sirf default_member_permissions pe bharosa nahi karna padta).
 */
const { PermissionsBitField } = require('discord.js');

/** Member (command chalane waale) ki permissions, ya null agar pata nahi */
function memberPermissions(interaction) {
  const direct = interaction?.memberPermissions;
  if (direct && typeof direct.has === 'function') return direct;

  const raw = interaction?.member?.permissions ?? interaction?.payload?.member?.permissions;
  if (raw === null || raw === undefined || raw === '') return null;
  try {
    return new PermissionsBitField(BigInt(raw));
  } catch {
    return null;
  }
}

/** Bot ki khud ki permissions, ya null agar pata nahi */
function botPermissions(interaction) {
  const direct = interaction?.appPermissions;
  if (direct && typeof direct.has === 'function') return direct;

  const me = interaction?.guild?.members?.me;
  if (me?.permissions && typeof me.permissions.has === 'function') return me.permissions;
  return null;
}

/**
 * Member ke paas permission hai? Pata na chale to `false` (safe side — action mat karo).
 */
function hasMemberPerm(interaction, flag) {
  const perms = memberPermissions(interaction);
  if (!perms) return false;
  try {
    return perms.has(flag);
  } catch {
    return false;
  }
}

/**
 * Bot ke paas permission hai? Pata na chale to `true` — warna HTTP mode me
 * har command falsely block ho jaayegi (Discord khud bhi ye check karta hai).
 */
function hasBotPerm(interaction, flag) {
  const perms = botPermissions(interaction);
  if (!perms) return true;
  try {
    return perms.has(flag);
  } catch {
    return true;
  }
}

/** Permission bitfield se readable naam (error messages ke liye) */
const PERM_NAMES = {
  ManageGuild: 'Manage Server',
  ManageRoles: 'Manage Roles',
  ManageMessages: 'Manage Messages',
  KickMembers: 'Kick Members',
  BanMembers: 'Ban Members',
  ModerateMembers: 'Moderate Members',
};

module.exports = {
  memberPermissions,
  botPermissions,
  hasMemberPerm,
  hasBotPerm,
  PERM_NAMES,
};
