/**
 * End-to-end self-check — bina Discord token ke pura server test
 * --------------------------------------------------------------
 *   npm run check
 *
 * Server ko child process me start karta hai (isolated temp data dir), phir
 * login, dashboard APIs, permissions aur access keys — sab HTTP se check karta hai.
 * Exit 0 = sab pass, 1 = kuch fail.
 */
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const net = require('net');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'questbot-check-'));
const OWNER_PASS = 'owner-selfcheck-pass';

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

let base = '';

async function call(route, { method = 'GET', body, cookie } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (cookie) headers.Cookie = cookie;

  const res = await fetch(`${base}${route}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    /* html */
  }

  const setCookie = res.headers.get('set-cookie');
  return { status: res.status, text, json, cookie: setCookie ? setCookie.split(';')[0] : null };
}

async function main() {
  const port = await getFreePort();
  base = `http://127.0.0.1:${port}`;
  console.log(`\n🔧 Self-check — server :${port}\n   temp data: ${TMP}\n`);

  const child = spawn(process.execPath, [path.join(ROOT, 'src', 'index.js')], {
    cwd: ROOT,
    env: {
      ...process.env,
      PORT: String(port),
      QUEST_DATA_DIR: TMP,
      DASHBOARD_PASSWORD: OWNER_PASS,
      DISCORD_TOKEN: '',
      GUILD_ID: '',
      CLIENT_ID: '123456789012345678', // invite link test ke liye (bot offline bhi)
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let log = '';
  child.stdout.on('data', (d) => (log += d));
  child.stderr.on('data', (d) => (log += d));

  const ready = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), 15000);
    const poll = setInterval(() => {
      if (/Dashboard live/.test(log)) {
        clearTimeout(timer);
        clearInterval(poll);
        resolve(true);
      }
    }, 100);
    child.on('exit', () => {
      clearTimeout(timer);
      clearInterval(poll);
      resolve(false);
    });
  });

  if (!ready) {
    console.error('❌ Server start nahi hua. Log:\n' + log);
    child.kill('SIGKILL');
    fs.rmSync(TMP, { recursive: true, force: true });
    process.exit(1);
  }

  try {
    /* ---------- 1. boot + public ---------- */
    console.log('1) Boot + public routes');
    check('server booted', /Dashboard live/.test(log));
    check('token na ho to saaf message', /Token nahi hai/.test(log));

    const health = await call('/health');
    check('GET /health -> ok', health.status === 200 && health.json?.status === 'ok', JSON.stringify(health.json));
    check('/health bot off batata hai', health.json?.bot?.state === 'off', JSON.stringify(health.json?.bot));

    const home = await call('/');
    check('GET / -> dashboard HTML', home.status === 200 && /Quest Bot/.test(home.text));
    check('dashboard me login form hai', /login-form/.test(home.text));

    const css = await call('/style.css');
    const js = await call('/app.js');
    check('static assets serve hote hain', css.status === 200 && js.status === 200);

    /* ---------- 2. auth ---------- */
    console.log('\n2) Login + sessions');
    const anon = await call('/api/status');
    check('bina login /api/status -> 401', anon.status === 401, String(anon.status));

    const wrong = await call('/api/login', { method: 'POST', body: { key: 'galat-password' } });
    check('galat password -> 401', wrong.status === 401, String(wrong.status));

    const owner = await call('/api/login', { method: 'POST', body: { key: OWNER_PASS } });
    check('owner login -> role owner', owner.status === 200 && owner.json?.role === 'owner', JSON.stringify(owner.json));
    check('session cookie set hui', Boolean(owner.cookie) && /qb_session=/.test(owner.cookie));
    check('owner ke paas access manage permission', owner.json?.permissions?.manageAccess === true);

    const me = await call('/api/me', { cookie: owner.cookie });
    check('/api/me logged in', me.status === 200 && me.json?.role === 'owner');

    /* ---------- 3. dashboard data ---------- */
    console.log('\n3) Dashboard data');
    const status = await call('/api/status', { cookie: owner.cookie });
    check('/api/status -> 200', status.status === 200);
    check('commands list me /quest hai', Array.isArray(status.json?.commands) && status.json.commands.includes('quest'), JSON.stringify(status.json?.commands));
    check('premium free bataya jaata hai', status.json?.premium?.free === true);

    const quests = await call('/api/quests', { cookie: owner.cookie });
    check('/api/quests daily rotation deta hai', quests.json?.today?.length === 3, String(quests.json?.today?.length));
    check('/api/quests weekly deta hai', quests.json?.week?.length === 2);
    check('catalog me premium pool hai', Array.isArray(quests.json?.catalog?.premium) && quests.json.catalog.premium.length > 0);

    const stats = await call('/api/stats', { cookie: owner.cookie });
    check('/api/stats -> 200', stats.status === 200 && typeof stats.json?.totalPlayers === 'number');

    /* ---------- 4. bot control guards ---------- */
    console.log('\n4) Bot control');
    const noToken = await call('/api/bot/start', { method: 'POST', body: {}, cookie: owner.cookie });
    check('token ke bina start -> 400 saaf error', noToken.status === 400 && /Token nahi mila/.test(noToken.json?.error ?? ''), JSON.stringify(noToken.json));

    const stop = await call('/api/bot/stop', { method: 'POST', cookie: owner.cookie });
    check('offline bot ko stop karna safe hai', stop.status === 200 && stop.json?.ok === true);

    /* ---------- 4b. commands connect + invite ---------- */
    console.log('\n4b) Commands connect + invite link');
    const regOffline = await call('/api/bot/register', { method: 'POST', body: {}, cookie: owner.cookie });
    check('offline bot pe register -> 409 saaf error', regOffline.status === 409 && /online nahi/.test(regOffline.json?.error ?? ''), JSON.stringify(regOffline.json));

    const invite = await call('/api/bot/invite', { cookie: owner.cookie });
    check('CLIENT_ID se invite link banti hai', invite.status === 200 && /discord\.com\/oauth2\/authorize/.test(invite.json?.url ?? ''), JSON.stringify(invite.json));
    check('invite me applications.commands scope hai', /applications\.commands/.test(decodeURIComponent(invite.json?.url ?? '')), invite.json?.url);
    check('invite me bot permission hai', /permissions=\d+/.test(invite.json?.url ?? ''));

    const inviteAnon = await call('/api/bot/invite');
    check('bina login invite -> 401', inviteAnon.status === 401, String(inviteAnon.status));

    const statusWithCmds = await call('/api/status', { cookie: owner.cookie });
    check('status me register info hai', Boolean(statusWithCmds.json?.bot?.register) === true, JSON.stringify(statusWithCmds.json?.bot?.register));
    check('status me inviteUrl hai', /oauth2/.test(statusWithCmds.json?.bot?.inviteUrl ?? ''));

    /* ---------- 5. access keys ---------- */
    console.log('\n5) Access keys — kisko access de sakte ho');
    const viewerKey = await call('/api/access', {
      method: 'POST',
      body: { label: 'Rahul', role: 'viewer' },
      cookie: owner.cookie,
    });
    check('viewer key bani', viewerKey.status === 200 && /^vw_/.test(viewerKey.json?.key ?? ''), JSON.stringify(viewerKey.json?.key)?.slice(0, 20));

    const adminKey = await call('/api/access', { method: 'POST', body: { label: 'Mod', role: 'admin' }, cookie: owner.cookie });
    check('admin key bani', /^adm_/.test(adminKey.json?.key ?? ''));

    const list = await call('/api/access', { cookie: owner.cookie });
    check('keys list me dono hain', list.json?.keys?.length === 2, String(list.json?.keys?.length));
    check('list me poora key leak nahi hota', list.json.keys.every((k) => !k.key));

    const viewerLogin = await call('/api/login', { method: 'POST', body: { key: viewerKey.json.key } });
    check('viewer key se login', viewerLogin.status === 200 && viewerLogin.json?.role === 'viewer');
    check('viewer ko bot control nahi', viewerLogin.json?.permissions?.controlBot === false);

    const viewerStatus = await call('/api/status', { cookie: viewerLogin.cookie });
    check('viewer status dekh sakta hai', viewerStatus.status === 200);

    const viewerStop = await call('/api/bot/stop', { method: 'POST', cookie: viewerLogin.cookie });
    check('viewer bot stop nahi kar sakta -> 403', viewerStop.status === 403, String(viewerStop.status));

    const viewerKeys = await call('/api/access', { cookie: viewerLogin.cookie });
    check('viewer keys nahi dekh sakta -> 403', viewerKeys.status === 403, String(viewerKeys.status));

    const adminLogin = await call('/api/login', { method: 'POST', body: { key: adminKey.json.key } });
    check('admin key se login', adminLogin.status === 200 && adminLogin.json?.role === 'admin');

    const adminStop = await call('/api/bot/stop', { method: 'POST', cookie: adminLogin.cookie });
    check('admin bot control kar sakta hai', adminStop.status === 200);

    const adminKeys = await call('/api/access', { cookie: adminLogin.cookie });
    check('admin naye keys nahi bana sakta -> 403', adminKeys.status === 403, String(adminKeys.status));

    /* ---------- 6. premium (free) ---------- */
    console.log('\n6) Premium grant — free');
    const badPremium = await call('/api/premium', { method: 'POST', body: { guildId: 'g1', query: 'x' }, cookie: owner.cookie });
    check('invalid member -> 404', badPremium.status === 404, String(badPremium.status));

    const premium = await call('/api/premium', {
      method: 'POST',
      body: { guildId: '111111111111111111', query: '222222222222222222' },
      cookie: owner.cookie,
    });
    check('premium grant -> ok', premium.status === 200 && premium.json?.premium === true, JSON.stringify(premium.json));
    check('premium free hai (note)', /free/i.test(premium.json?.note ?? ''));

    const premiumStats = await call('/api/stats', { cookie: owner.cookie });
    check('premium player stats me dikhta hai', premiumStats.json?.premiumPlayers >= 1, String(premiumStats.json?.premiumPlayers));

    const revoke = await call('/api/premium/revoke', {
      method: 'POST',
      body: { guildId: '111111111111111111', userId: '222222222222222222' },
      cookie: owner.cookie,
    });
    check('premium revoke -> ok', revoke.status === 200 && revoke.json?.ok === true);

    /* ---------- 7. revoke key ---------- */
    console.log('\n7) Key revoke');
    const keyId = list.json.keys.find((k) => k.label === 'Rahul')?.id;
    const del = await call(`/api/access/${keyId}`, { method: 'DELETE', cookie: owner.cookie });
    check('key revoke -> ok', del.status === 200);

    const afterRevoke = await call('/api/login', { method: 'POST', body: { key: viewerKey.json.key } });
    check('revoked key se login fail', afterRevoke.status === 401, String(afterRevoke.status));

    const oldSession = await call('/api/status', { cookie: viewerLogin.cookie });
    check('revoked key ka session bhi band', oldSession.status === 401, String(oldSession.status));

    /* ---------- 8. logout ---------- */
    console.log('\n8) Logout');
    const out = await call('/api/logout', { method: 'POST', cookie: adminLogin.cookie });
    check('logout -> ok', out.status === 200);
    const afterLogout = await call('/api/me', { cookie: adminLogin.cookie });
    check('logout ke baad 401', afterLogout.status === 401);

    const stillUp = await call('/health');
    check('server abhi bhi zinda', stillUp.json?.status === 'ok');
  } finally {
    child.kill('SIGTERM');
    await new Promise((resolve) => setTimeout(resolve, 400));
    fs.rmSync(TMP, { recursive: true, force: true });
  }

  console.log(`\n${'─'.repeat(52)}`);
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
