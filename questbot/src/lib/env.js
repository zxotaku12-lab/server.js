/**
 * Chhota .env loader — koi extra dependency nahi.
 * Sirf un keys ko set karta hai jo pehle se process.env me nahi hain.
 */
const fs = require('fs');
const path = require('path');

function loadEnv(file = path.join(__dirname, '..', '..', '.env')) {
  let text = '';
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    return false;
  }

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;

    const eq = line.indexOf('=');
    if (eq <= 0) continue;

    const key = line.slice(0, eq).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;

    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    if (process.env[key] === undefined) process.env[key] = value;
  }

  return true;
}

module.exports = { loadEnv };
