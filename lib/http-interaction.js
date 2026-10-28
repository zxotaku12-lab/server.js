/**
 * HTTP interaction adapter
 * ------------------------
 * Discord jab interaction HTTP endpoint pe bhejta hai (Interactions Endpoint URL set ho),
 * tab humein raw JSON payload milta hai — discord.js ka Interaction object nahi.
 *
 * Ye module us raw payload ko ek aise object me badalta hai jiska shape discord.js jaisa hai,
 * taaki commands/ ke SAME commands bina duplicate logic ke dono tarah chal jaayein:
 *   - Gateway (bot.js)      -> asli discord.js Interaction
 *   - HTTP    (server.js)   -> ye shim
 *
 * Jo cheezein sirf Gateway pe possible hain (roles dena, kick/ban, followUp, editReply)
 * wo yahan clearly error deti hain — chupchap fail nahi hoti.
 */

const EPHEMERAL_FLAG = 1 << 6; // 64

const CDN_AVATAR = (id, hash, size = 128) =>
  `https://cdn.discordapp.com/avatars/${id}/${hash}.${hash.startsWith('a_') ? 'gif' : 'png'}?size=${size}`;

const DEFAULT_AVATAR = (id) => {
  let index = 0;
  try {
    index = Number((BigInt(id) >> 22n) % 5n);
  } catch {
    index = 0;
  }
  return `https://cdn.discordapp.com/embed/avatars/${index}.png`;
};

/** Raw user object -> halka User-jaisa shim */
function makeUser(raw = {}) {
  const id = raw.id ?? null;
  const username = raw.username ?? raw.global_name ?? 'user';
  return {
    id,
    username,
    globalName: raw.global_name ?? null,
    bot: !!raw.bot,
    system: !!raw.system,
    tag: raw.username ? `${raw.username}` : 'user',
    toString: () => (id ? `<@${id}>` : username),
    displayAvatarURL: ({ size = 128 } = {}) =>
      id && raw.avatar ? CDN_AVATAR(id, raw.avatar, size) : DEFAULT_AVATAR(id ?? 0),
  };
}

/** Raw member object -> halka GuildMember-jaisa shim */
function makeMember(raw, fallbackUser) {
  if (!raw) return null;
  return {
    user: makeUser(raw.user ?? fallbackUser ?? {}),
    nick: raw.nick ?? null,
    roles: raw.roles ?? [],
    joinedAt: raw.joined_at ? new Date(raw.joined_at) : null,
    permissions: raw.permissions ?? null,
    toString: () => (raw.user?.id ? `<@${raw.user.id}>` : 'member'),
  };
}

/** payload.data.options -> discord.js jaisa CommandInteractionOptions */
class OptionsShim {
  constructor(options = [], resolved = {}) {
    this.raw = options;
    this.resolved = resolved;
  }

  #find(name) {
    const direct = this.raw.find((o) => o.name === name);
    if (direct) return direct;
    const sub = this.raw.find((o) => o.type === 1);
    return sub?.options?.find((o) => o.name === name) ?? null;
  }

  #value(name, required, cast) {
    const opt = this.#find(name);
    if (!opt) {
      if (required) throw new Error(`Required option "${name}" payload me nahi mila`);
      return null;
    }
    return cast(opt.value);
  }

  getString(name, required = false) {
    return this.#value(name, required, (v) => String(v));
  }
  getInteger(name, required = false) {
    return this.#value(name, required, (v) => Math.trunc(Number(v)));
  }
  getNumber(name, required = false) {
    return this.#value(name, required, (v) => Number(v));
  }
  getBoolean(name, required = false) {
    return this.#value(name, required, (v) => !!v);
  }

  /** Resolved object wale options — HTTP pe sirf halka shim milta hai (full discord.js object nahi). */
  getUser(name, required = false) {
    const id = this.#value(name, required, (v) => v);
    if (!id) return null;
    return makeUser(this.resolved.users?.[id] ?? { id });
  }
  getMember(name, required = false) {
    const id = this.#value(name, required, (v) => v);
    if (!id) return null;
    const member = this.resolved.members?.[id];
    return makeMember(member ?? {}, this.resolved.users?.[id] ?? { id });
  }
  getRole(name, required = false) {
    const id = this.#value(name, required, (v) => v);
    return id ? this.resolved.roles?.[id] ?? { id } : null;
  }
  getChannel(name, required = false) {
    const id = this.#value(name, required, (v) => v);
    return id ? this.resolved.channels?.[id] ?? { id } : null;
  }
  getMentionable(name, required = false) {
    return this.getRole(name, required) ?? this.getUser(name, false);
  }

  /** Selected subcommand aur uske options ko resolve karo. */
  getSubcommand() {
    const sub = this.raw.find((o) => o.type === 1 || o.type === 2);
    return sub?.name ?? null;
  }
  getSubcommandGroup() {
    return null;
  }
}

/** reply({ content, embeds, ephemeral }) / reply('text') -> Discord ko bhejne layak data */
function normalizePayload(data) {
  const payload = typeof data === 'string' ? { content: data } : { ...(data ?? {}) };

  if (payload.embeds) payload.embeds = payload.embeds.map((e) => (typeof e?.toJSON === 'function' ? e.toJSON() : e));
  if (payload.files) delete payload.files; // HTTP response me attachment bhejna webhook maangta hai

  let flags = payload.flags ?? 0;
  if (payload.ephemeral) flags |= EPHEMERAL_FLAG;
  delete payload.ephemeral;
  if (flags) payload.flags = flags;

  for (const key of Object.keys(payload)) if (payload[key] === undefined) delete payload[key];
  return payload;
}

class HttpInteraction {
  constructor(payload = {}) {
    this.payload = payload;

    this.id = payload.id ?? null;
    this.type = payload.type ?? 0;
    this.token = payload.token ?? null;
    this.applicationId = payload.application_id ?? null;
    this.version = payload.version ?? 1;

    this.guildId = payload.guild_id ?? null;
    this.channelId = payload.channel_id ?? null;

    const rawUser = payload.member?.user ?? payload.user ?? {};
    this.user = makeUser(rawUser);
    this.member = makeMember(payload.member, rawUser);

    // Gateway-only handles — HTTP pe ye features available nahi hote.
    this.guild = null;
    this.channel = null;
    this.client = null;

    this.commandName = payload.data?.name ?? null;
    this.commandId = payload.data?.id ?? null;
    this.commandType = payload.data?.type ?? 1;
    this.options = new OptionsShim(payload.data?.options ?? [], payload.data?.resolved ?? {});

    this.replied = false;
    this.deferred = false;

    /** server.js isi ko HTTP response body ki tarah bhejta hai */
    this.response = null;
    /** Extra responses (followUp/editReply) HTTP mode me possible nahi — sirf error ke liye track hota hai */
    this.source = 'http';
  }

  /* ---------------- type guards (discord.js jaisa API) ---------------- */
  isChatInputCommand() {
    return this.type === 2 && this.commandType === 1;
  }
  isButton() {
    return this.type === 3 && this.payload.data?.component_type === 2;
  }
  isStringSelectMenu() {
    return this.type === 3 && this.payload.data?.component_type === 3;
  }
  isAnySelectMenu() {
    return this.type === 3;
  }
  isModalSubmit() {
    return this.type === 5;
  }
  isMessageComponent() {
    return this.type === 3;
  }

  /* ---------------- responses ---------------- */
  #assertNotSent(method) {
    if (this.replied || this.deferred) {
      throw new Error(`${method}(): interaction ka response pehle hi bhej diya gaya hai`);
    }
  }

  async reply(data) {
    this.#assertNotSent('reply');
    this.response = { type: 4, data: normalizePayload(data) };
    this.replied = true;
    return this;
  }

  async deferReply(options = {}) {
    this.#assertNotSent('deferReply');
    this.response = { type: 5, data: normalizePayload(options) };
    this.deferred = true;
    return this;
  }

  async editReply() {
    throw new Error('editReply() HTTP mode pe support nahi hai — is command ke liye Gateway bot (DISCORD_TOKEN) chahiye.');
  }

  async followUp() {
    throw new Error('followUp() HTTP mode pe support nahi hai — is command ke liye Gateway bot (DISCORD_TOKEN) chahiye.');
  }

  async deleteReply() {
    throw new Error('deleteReply() HTTP mode pe support nahi hai.');
  }
}

module.exports = { HttpInteraction, makeUser, normalizePayload, EPHEMERAL_FLAG };
