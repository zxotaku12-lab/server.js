/**
 * Shared command registry
 * -----------------------
 * commands/ folder ke saare .js files ko load karta hai aur ek hi jagah deta hai,
 * taaki teeno consumers same command set dekhein:
 *   - bot.js               (Gateway / discord.js client)
 *   - server.js            (HTTP Interactions endpoint)
 *   - register-commands.js (Discord API pe slash commands register karna)
 *
 * Har file ek command object export kare ya unka array:
 *   { data: SlashCommandBuilder, execute(interaction) {} }
 */
const fs = require('fs');
const path = require('path');

let cache = null;

/**
 * Commands load karo (pehli baar disk se, uske baad cached).
 * @param {{ force?: boolean }} [opts] force=true par dobara disk se padho
 * @returns {{ map: Map<string, object>, json: object[], names: string[], files: string[] }}
 */
function getCommands(opts = {}) {
  if (cache && !opts.force) return cache;

  const dir = __dirname;
  const map = new Map();
  const json = [];
  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.js') && f !== 'index.js')
    .sort();

  for (const f of files) {
    let mod;
    try {
      mod = require(path.join(dir, f));
    } catch (err) {
      console.error(`[commands] ❌ ${f} load nahi hua: ${err.message}`);
      continue;
    }

    const list = Array.isArray(mod) ? mod : [mod];
    for (const cmd of list) {
      const name = cmd?.data?.name;
      if (!name) {
        console.warn(`[commands] ⚠️  ${f}: ek entry me data.name nahi hai — skip`);
        continue;
      }
      if (typeof cmd.execute !== 'function') {
        console.warn(`[commands] ⚠️  /${name} (${f}): execute() function nahi hai — skip`);
        continue;
      }
      if (map.has(name)) {
        console.warn(`[commands] ⚠️  /${name} duplicate hai (${f}) — pehla version hi rakha`);
        continue;
      }
      map.set(name, { ...cmd, source: f });
      try {
        json.push(cmd.data.toJSON());
      } catch (err) {
        console.error(`[commands] ❌ /${name} ka JSON bana nahi: ${err.message}`);
      }
    }
  }

  cache = { map, json, names: [...map.keys()], files };
  return cache;
}

/**
 * Discord convention ke hisaab se command ka usage string.
 *   required option -> <name>     optional option -> [name]
 *   subcommands/groups skip hote hain (wo nested hote hain)
 * @param {{data:{name:string, options?:Array}}} cmd
 * @returns {string} e.g. "/8ball <question>", "/roll [max]"
 */
function commandUsage(cmd) {
  const name = cmd?.data?.name ?? '';
  const args = (cmd?.data?.options ?? [])
    .filter((o) => o && o.name && Number(o.type) !== 1 && Number(o.type) !== 2)
    .map((o) => (o.required ? `<${o.name}>` : `[${o.name}]`));
  return `/${name}${args.length ? ' ' + args.join(' ') : ''}`;
}

module.exports = { getCommands, commandUsage };
