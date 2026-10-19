/**
 * Self-check — bina Discord ke pura server test karta hai
 * ------------------------------------------------------
 *   npm run check
 *
 * Kya karta hai:
 *   1. ek ed25519 keypair banata hai (tweetnacl) aur usi ko DISCORD_PUBLIC_KEY bana ke
 *      server.js ko child process me start karta hai  -> signature verification REAL me ON hoti hai
 *   2. signed/unsigned/tampered requests bhejta hai
 *   3. har slash command ko HTTP interactions payload ke through chalata hai
 *   4. pages (/ , /health, /commands, /terms-of-service, /privacy-policy) check karta hai
 *
 * Exit code 0 = sab pass, 1 = kuch fail.
 */
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');
const nacl = require('tweetnacl');

const ROOT = path.join(__dirname, '..');
const kp = nacl.sign.keyPair();
const PUBLIC_KEY = Buffer.from(kp.publicKey).toString('hex');
const SECRET_KEY = kp.secretKey;

let passed = 0;
let failed = 0;
const failures = [];

function check(name, ok, detail = '') {
  if (ok) {
    passed++;
    console.log(`  ✅ ${name}`);
  } else {
    failed++;
    failures.push(`${name}${detail ? ` — ${detail}` : ''}`);
    console.log(`  ❌ ${name}${detail ? ` — ${detail}` : ''}`);
  }
}

const getFreePort = () =>
  new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });

function sign(body, timestamp = String(Date.now())) {
  const raw = Buffer.from(body, 'utf8');
  const sig = nacl.sign.detached(Buffer.concat([Buffer.from(timestamp, 'utf8'), raw]), SECRET_KEY);
  return { raw, signature: Buffer.from(sig).toString('hex'), timestamp };
}

async function send(port, route, { method = 'GET', body = null, signed = false, tamper = false } = {}) {
  const headers = {};
  let payload = null;
  if (body !== null) {
    const raw = typeof body === 'string' ? body : JSON.stringify(body);
    headers['Content-Type'] = 'application/json';
    if (signed) {
      const s = sign(raw);
      headers['X-Signature-Ed25519'] = tamper
        ? Buffer.from(nacl.sign.detached(Buffer.concat([Buffer.from(s.timestamp, 'utf8'), Buffer.from('x')]), SECRET_KEY)).toString('hex')
        : s.signature;
      headers['X-Signature-Timestamp'] = s.timestamp;
    }
    payload = raw;
  }
  const res = await fetch(`http://127.0.0.1:${port}${route}`, { method, headers, body: payload });
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* HTML page */
  }
  return { status: res.status, text, json };
}

const interaction = (name, options = [], user = { id: '111111111111111111', username: 'tester', avatar: null }) => ({
  id: '999999999999999999',
  application_id: '222222222222222222',
  type: 2,
  token: 'fake-token',
  version: 1,
  guild_id: '333333333333333333',
  channel_id: '444444444444444444',
  member: { user, roles: [], nick: null, joined_at: '2024-01-01T00:00:00.000Z' },
  data: { id: '555555555555555555', name, type: 1, version: 1, options },
});

async function main() {
  const port = await getFreePort();
  console.log(`\n🔧 Self-check — server :${port}  (public key ${PUBLIC_KEY.slice(0, 12)}…)\n`);

  const child = spawn(process.execPath, [path.join(ROOT, 'server.js')], {
    cwd: ROOT,
    env: { ...process.env, PORT: String(port), DISCORD_PUBLIC_KEY: PUBLIC_KEY },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let childLog = '';
  let crashed = null;
  child.stdout.on('data', (d) => (childLog += d));
  child.stderr.on('data', (d) => (childLog += d));
  child.on('exit', (code) => (crashed = code));

  // Server ke live hone ka wait
  const ready = await new Promise((resolve) => {
    const t = setTimeout(() => resolve(false), 15000);
    const poll = setInterval(() => {
      if (childLog.includes('Server live')) {
        clearTimeout(t);
        clearInterval(poll);
        resolve(true);
      } else if (crashed !== null) {
        clearTimeout(t);
        clearInterval(poll);
        resolve(false);
      }
    }, 100);
  });

  if (!ready) {
    console.error('❌ Server start hi nahi hua. Log:\n' + childLog);
    child.kill('SIGKILL');
    process.exit(1);
  }

  try {
    /* ---------- 1. Startup ---------- */
    console.log('1) Startup');
    check('server booted', childLog.includes('Server live'));
    check('commands registry loaded', /(\d+) slash commands loaded/.test(childLog));
    check('no uncaught error at boot', !/unhandled rejection|Cannot find module|TypeError/.test(childLog));

    /* ---------- 2. Signature verification ---------- */
    console.log('\n2) Signature verification (DISCORD_PUBLIC_KEY set hai)');
    const pingBody = JSON.stringify({ type: 1, id: '1', token: 't', application_id: '2', version: 1 });

    const unsigned = await send(port, '/interactions', { method: 'POST', body: pingBody, signed: false });
    check('unsigned request -> 401', unsigned.status === 401, `got ${unsigned.status}`);

    const signed = await send(port, '/interactions', { method: 'POST', body: pingBody, signed: true });
    check('valid signature -> PONG', signed.status === 200 && signed.json?.type === 1, JSON.stringify(signed.json));

    const tampered = await send(port, '/interactions', { method: 'POST', body: pingBody, signed: true, tamper: true });
    check('tampered signature -> 401', tampered.status === 401, `got ${tampered.status}`);

    const s = sign(pingBody);
    const missingTs = await fetch(`http://127.0.0.1:${port}/interactions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Signature-Ed25519': s.signature },
      body: pingBody,
    });
    check('missing timestamp header -> 401', missingTs.status === 401, `got ${missingTs.status}`);

    /* ---------- 3. Pages ---------- */
    console.log('\n3) Pages');
    const home = await send(port, '/');
    check('GET / -> 200', home.status === 200);
    check('GET / lists commands', home.text.includes('/8ball') && home.text.includes('/rps'));
    check('GET / shows signature ON', home.text.includes('signature verification ON'));

    const health = await send(port, '/health');
    check('GET /health -> ok', health.status === 200 && health.json?.status === 'ok');
    check('/health reports command count', (health.json?.commandCount ?? 0) >= 7, JSON.stringify(health.json?.commandCount));
    check('/health reports gateway off', health.json?.gateway?.state === 'off', JSON.stringify(health.json?.gateway));

    const cmds = await send(port, '/commands');
    check('GET /commands -> Discord-shaped array', Array.isArray(cmds.json) && cmds.json.every((c) => c.name && c.description));

    const tos = await send(port, '/terms-of-service');
    const pp = await send(port, '/privacy-policy');
    check('GET /terms-of-service -> 200', tos.status === 200 && tos.text.includes('Terms of Service'));
    check('GET /privacy-policy -> 200', pp.status === 200 && pp.text.includes('Privacy Policy'));

    /* ---------- 4. Slash commands over HTTP ---------- */
    console.log('\n4) Slash commands (HTTP interactions)');
    const run = async (label, payload, assert) => {
      const r = await send(port, '/interactions', { method: 'POST', body: payload, signed: true });
      let ok = false;
      let detail = '';
      try {
        ok = r.status === 200 && assert(r.json);
      } catch (e) {
        detail = e.message;
      }
      check(label, ok, detail || (ok ? '' : JSON.stringify(r.json)?.slice(0, 140)));
    };
    const content = (j) => j?.data?.content ?? '';
    const embedText = (j) => JSON.stringify(j?.data?.embeds ?? []);

    await run('/ping -> Pong', interaction('ping'), (j) => j.type === 4 && /Pong/i.test(content(j)));
    await run('/hello -> mention karta hai', interaction('hello'), (j) => j.type === 4 && content(j).includes('<@111111111111111111'));
    await run('/help -> embed with all commands', interaction('help'), (j) =>
      j.type === 4 && /8ball/.test(embedText(j)) && /rps/.test(embedText(j)) && /coinflip/.test(embedText(j))
    );

    await run('/help usage formatting (required <x>, optional [y], no nested backticks)', interaction('help'), (j) => {
      const desc = j?.data?.embeds?.[0]?.description ?? '';
      return desc.includes('`/8ball <question>`') && desc.includes('`/roll [max]`') && !desc.includes('``');
    });

    await run('/8ball question:... -> embed answer', interaction('8ball', [{ name: 'question', type: 3, value: 'Kya ye test pass hoga?' }]), (j) =>
      j.type === 4 && /Magic 8-Ball/.test(embedText(j)) && embedText(j).includes('Kya ye test pass hoga?')
    );
    await run('/coinflip -> heads ya tails', interaction('coinflip'), (j) => j.type === 4 && /HEADS|TAILS/.test(content(j)));
    await run('/coinflip mentions username', interaction('coinflip'), (j) => content(j).includes('tester'));
    await run('/roll -> 1..100', interaction('roll'), (j) => {
      const m = content(j).match(/\*\*(\d+)\*\* roll kiya/);
      return j.type === 4 && m && Number(m[1]) >= 1 && Number(m[1]) <= 100;
    });
    await run('/roll max:6 -> 1..6', interaction('roll', [{ name: 'max', type: 4, value: 6 }]), (j) => {
      const m = content(j).match(/\*\*(\d+)\*\* roll kiya/);
      return j.type === 4 && m && Number(m[1]) >= 1 && Number(m[1]) <= 6;
    });

    for (const choice of ['rock', 'paper', 'scissors']) {
      await run(`/rps choice:${choice}`, interaction('rps', [{ name: 'choice', type: 3, value: choice }]), (j) =>
        j.type === 4 && /Tie|jeet/i.test(content(j))
      );
    }

    await run('unknown command -> ephemeral hint', interaction('nopesuchcommand'), (j) => j.type === 4 && j.data?.flags === 64);

    /* ---------- 5. Components + edge cases ---------- */
    console.log('\n5) Components & edge cases');
    const comp = await send(port, '/interactions', {
      method: 'POST',
      signed: true,
      body: { id: '1', type: 3, token: 't', application_id: '2', data: { custom_id: 'x', component_type: 2 } },
    });
    check('button interaction -> ACK (type 6)', comp.json?.type === 6, JSON.stringify(comp.json));

    const badJson = await fetch(`http://127.0.0.1:${port}/interactions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{ not json',
    });
    check('malformed JSON -> 4xx (crash nahi)', badJson.status >= 400 && badJson.status < 500, `got ${badJson.status}`);

    const stillUp = await send(port, '/health');
    check('server still alive after bad input', stillUp.json?.status === 'ok');

    /* ---------- 6. register-commands.js guards ---------- */
    console.log('\n6) register-commands.js');
    const regNoEnv = spawn(process.execPath, [path.join(ROOT, 'register-commands.js')], {
      cwd: ROOT,
      env: { ...process.env, DISCORD_TOKEN: '', CLIENT_ID: '' },
    });
    const regOut = await new Promise((resolve) => {
      let out = '';
      regNoEnv.stdout.on('data', (d) => (out += d));
      regNoEnv.stderr.on('data', (d) => (out += d));
      regNoEnv.on('exit', (code) => resolve({ out, code }));
      setTimeout(() => { regNoEnv.kill(); resolve({ out, code: null }); }, 8000);
    });
    check('bina env ke clean error + exit 1 (top-level await SyntaxError nahi)', regOut.code === 1 && !/SyntaxError/.test(regOut.out), regOut.out.slice(0, 120));

    /* ---------- 7. bot.js without token ---------- */
    console.log('\n7) bot.js (Gateway)');
    const botNoToken = spawn(process.execPath, [path.join(ROOT, 'bot.js')], {
      cwd: ROOT,
      env: { ...process.env, DISCORD_TOKEN: '' },
    });
    const botOut = await new Promise((resolve) => {
      let out = '';
      botNoToken.stdout.on('data', (d) => (out += d));
      botNoToken.stderr.on('data', (d) => (out += d));
      botNoToken.on('exit', (code) => resolve({ out, code }));
      setTimeout(() => { botNoToken.kill(); resolve({ out, code: null }); }, 8000);
    });
    check('bot.js loads without crashing (discord.js present)', !/Cannot find module/.test(botOut.out), botOut.out.slice(0, 120));
    check('bot.js loads all commands', /commands loaded/.test(botOut.out), botOut.out.slice(0, 120));
    check('bot.js warns clearly when token missing', /DISCORD_TOKEN nahi mila/.test(botOut.out));
  } finally {
    child.kill('SIGTERM');
  }

  console.log(`\n${'─'.repeat(56)}`);
  console.log(`Result: ${passed} passed, ${failed} failed`);
  if (failed) {
    console.log('\nFailed checks:');
    for (const f of failures) console.log(`  • ${f}`);
    process.exit(1);
  }
  console.log('🎉 Sab kuch theek hai!');
  process.exit(0);
}

main().catch((err) => {
  console.error('Self-check crash:', err);
  process.exit(1);
});
