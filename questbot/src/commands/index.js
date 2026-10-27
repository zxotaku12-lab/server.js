/**
 * Command registry — src/commands/*.js auto-load
 * ----------------------------------------------
 * Har file ek command object ya array export kare:
 *   { data: SlashCommandBuilder, execute(interaction) {} }
 */
const fs = require('fs');
const path = require('path');

let cache = null;

function load(opts = {}) {
  if (cache && !opts.force) return cache;

  const dir = __dirname;
  const map = new Map();
  const list = [];

  const files = fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.js') && f !== 'index.js')
    .sort();

  for (const file of files) {
    let mod;
    try {
      mod = require(path.join(dir, file));
    } catch (err) {
      console.error(`[commands] ❌ ${file} load fail: ${err.message}`);
      continue;
    }

    for (const cmd of Array.isArray(mod) ? mod : [mod]) {
      const name = cmd?.data?.name;
      if (!name) continue;
      if (typeof cmd.execute !== 'function') {
        console.warn(`[commands] ⚠️ /${name} me execute() nahi — skip`);
        continue;
      }
      if (map.has(name)) {
        console.warn(`[commands] ⚠️ /${name} duplicate — pehla rakha`);
        continue;
      }
      map.set(name, { ...cmd, source: file });
      list.push(cmd.data.toJSON());
    }
  }

  cache = { map, json: list, names: [...map.keys()], files };
  return cache;
}

const get = (name) => load().map.get(name);
const names = () => load().names;
const json = () => load().json;

module.exports = { get, names, json, load };
