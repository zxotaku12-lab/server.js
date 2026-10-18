// Chhota JSON storage helper (data/ folder me files rakhta hai)
const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, 'data');
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

const file = (name) => path.join(DATA_DIR, `${name}.json`);

function load(name, fallback = {}) {
  try {
    return JSON.parse(fs.readFileSync(file(name), 'utf8'));
  } catch {
    return fallback;
  }
}

function save(name, data) {
  try {
    fs.writeFileSync(file(name), JSON.stringify(data, null, 2));
  } catch (e) {
    console.error('[store] save fail:', e.message);
  }
}

module.exports = { load, save };
