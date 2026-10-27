/* Quest Bot dashboard — vanilla JS, koi build step nahi */
(() => {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  let me = null;
  let state = { guilds: [], guildId: null, polling: null };

  /* ---------------- API helper ---------------- */
  async function api(path, { method = 'GET', body } = {}) {
    const res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });

    let data = null;
    try {
      data = await res.json();
    } catch {
      /* non-json */
    }

    if (res.status === 401 && path !== '/api/login') {
      showLogin();
      throw new Error(data?.error || 'Login karo.');
    }
    if (!res.ok) throw new Error(data?.error || `Request fail (${res.status})`);

    return data;
  }

  /* ---------------- Toast ---------------- */
  let toastTimer = null;
  function toast(message, kind = 'ok') {
    const el = $('#toast');
    el.textContent = message;
    el.className = `toast ${kind}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add('hidden'), 3800);
  }

  function fmt(number) {
    return Number(number || 0).toLocaleString('en-IN');
  }

  function relTime(ms) {
    if (!ms) return '—';
    return `<t:${Math.floor(ms / 1000)}:R>`;
  }

  function relText(ms) {
    if (!ms) return '—';
    const diff = Math.max(0, ms - Date.now());
    const mins = Math.round(diff / 60000);
    if (mins < 60) return `${mins} min me`;
    const hours = Math.round(mins / 60);
    if (hours < 48) return `${hours} ghante me`;
    return `${Math.round(hours / 24)} din me`;
  }

  /* ---------------- Login ---------------- */
  function showLogin() {
    $('#app').classList.add('hidden');
    $('#login').classList.remove('hidden');
    if (state.polling) clearInterval(state.polling);
    state.polling = null;
  }

  function showApp() {
    $('#login').classList.add('hidden');
    $('#app').classList.remove('hidden');

    const badge = $('#who-role');
    badge.textContent = me.role;
    badge.className = `badge ${me.role}`;
    $('#who-label').textContent = me.label || me.role;

    $$('.owner-only').forEach((el) => el.classList.toggle('hidden', me.role !== 'owner'));

    if (state.polling) clearInterval(state.polling);
    state.polling = setInterval(refreshStatus, 8000);
  }

  $('#login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const btn = $('#login-btn');
    const error = $('#login-error');
    error.textContent = '';
    btn.disabled = true;

    try {
      const key = $('#login-key').value;
      await api('/api/login', { method: 'POST', body: { key } });
      $('#login-key').value = '';
      await boot();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });

  $('#logout-btn').addEventListener('click', async () => {
    await api('/api/logout', { method: 'POST' }).catch(() => {});
    me = null;
    showLogin();
  });

  /* ---------------- Tabs ---------------- */
  $$('.nav-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      $$('.nav-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');

      $$('.tab').forEach((tab) => tab.classList.add('hidden'));
      $(`#tab-${btn.dataset.tab}`).classList.remove('hidden');

      if (btn.dataset.tab === 'board') loadBoard();
      if (btn.dataset.tab === 'access') loadKeys();
      if (btn.dataset.tab === 'quests') loadQuests();
    });
  });

  /* ---------------- Status ---------------- */
  async function refreshStatus() {
    try {
      const data = await api('/api/status');
      renderStatus(data.bot);
      $('#reset-daily').textContent = relText(data.resets.daily);
      $('#reset-weekly').textContent = relText(data.resets.weekly);
      $('#cmd-count').textContent = data.commands.length;

      const canControl = me?.permissions?.controlBot;
      $('#start-btn').disabled = !canControl;
      $('#stop-btn').disabled = !canControl;
      $('#restart-btn').disabled = !canControl;
      $('#token-form').classList.toggle('hidden', !canControl);
      $('#premium-form')
        .querySelectorAll('input, select, button')
        .forEach((el) => (el.disabled = !me?.permissions?.grantPremium));

      await loadGuilds();
      await loadStats();
    } catch (err) {
      /* login expire ho gaya to upar handle ho jaata hai */
    }
  }

  function renderStatus(bot) {
    const stateEl = $('#bot-state');
    stateEl.textContent = bot.state;
    stateEl.className = `pill ${bot.state}`;

    renderCommands(bot);

    $('#bot-tag').textContent = bot.tag || '—';
    $('#bot-guilds').textContent = fmt(bot.guilds);
    $('#bot-ping').textContent = bot.ping != null ? `${bot.ping} ms` : '—';
    $('#bot-token-source').textContent = bot.tokenSource === 'env' ? 'env variable' : bot.tokenSource === 'dashboard' ? 'dashboard' : 'nahi hai';

    const hint = $('#bot-hint');
    if (bot.state === 'ready') hint.textContent = '✅ Bot online hai — Discord me /quest chalao.';
    else if (bot.state === 'connecting') hint.textContent = '⏳ Login ho raha hai…';
    else if (bot.state === 'error') hint.textContent = `❌ ${bot.error || 'Login fail'} — token check karo.`;
    else hint.textContent = 'Token paste karke "Link bot" dabao. Token sirf data/config.json me save hota hai.';
  }

  /** Commands ka register status — "bot se connected" ya nahi */
  function renderCommands(bot) {
    const reg = bot.register || {};
    const pill = $('#cmd-state');
    const hint = $('#cmd-hint');
    const registerBtn = $('#register-btn');
    const inviteBtn = $('#invite-btn');
    const inviteHint = $('#invite-hint');

    const canControl = me?.permissions?.controlBot;

    if (reg.mode === 'guild') {
      pill.textContent = `${reg.count} registered`;
      pill.className = 'pill ready';
      hint.innerHTML = `✅ <b>${reg.count} commands</b> <code>${escapeHtml(reg.guild || 'server')}</code> me live hain — Discord me turant dikhengi.`;
    } else if (reg.mode === 'global') {
      pill.textContent = `${reg.count} global`;
      pill.className = 'pill ready';
      hint.innerHTML = `✅ <b>${reg.count} commands</b> globally register ho gayi — Discord me ~1 ghante me dikhengi.<br/>Turant chahiye? <code>GUILD_ID</code> set karo.`;
    } else if (reg.mode === 'error') {
      pill.textContent = 'error';
      pill.className = 'pill error';
      hint.innerHTML = `❌ Register fail: ${escapeHtml(reg.error || 'unknown')} — dobara try karo.`;
    } else if (reg.needsRegister) {
      pill.textContent = 'registering…';
      pill.className = 'pill connecting';
      hint.textContent = '⏳ Bot online hai — commands register ho rahi hain…';
    } else if (!bot.ready) {
      pill.textContent = 'bot offline';
      pill.className = 'pill off';
      hint.innerHTML = 'Pehle token se bot link karo — uske baad commands apne aap register ho jaayengi.';
    } else {
      pill.textContent = 'pending';
      pill.className = 'pill connecting';
    }

    registerBtn.disabled = !canControl || !bot.ready;
    inviteBtn.disabled = !bot.inviteUrl;

    inviteHint.innerHTML = bot.inviteUrl
      ? `🔗 <a href="${bot.inviteUrl}" target="_blank" rel="noopener">Invite link kholo</a> — isme <code>applications.commands</code> scope hai, isliye commands dikhengi.`
      : 'Invite link ke liye bot link karo (ya <code>CLIENT_ID</code> env set karo).';
  }

  async function loadGuilds() {
    const data = await api('/api/guilds');
    state.guilds = data.guilds || [];

    const select = $('#premium-guild');
    const previous = select.value;
    select.innerHTML = state.guilds.length
      ? state.guilds.map((g) => `<option value="${g.id}">${escapeHtml(g.name)} (${fmt(g.members)})</option>`).join('')
      : '<option value="">Bot online nahi / koi server nahi</option>';
    if (previous && state.guilds.some((g) => g.id === previous)) select.value = previous;
  }

  $('#token-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const token = $('#token-input').value.trim();
    if (!token) return toast('Token paste karo pehle.', 'err');

    try {
      await api('/api/bot/start', { method: 'POST', body: { token } });
      $('#token-input').value = '';
      toast('Bot link ho raha hai… 🚀');
      setTimeout(refreshStatus, 1200);
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  /* ---------------- Commands connect + invite ---------------- */
  $('#register-btn').addEventListener('click', async () => {
    const btn = $('#register-btn');
    btn.disabled = true;
    btn.textContent = '⏳ Register ho raha hai…';

    try {
      const data = await api('/api/bot/register', { method: 'POST', body: {} });
      toast(data.mode === 'guild' ? `✅ ${data.count} commands server me live!` : `✅ ${data.count} commands globally register ho gayi (1 ghanta tak lag sakta hai).`);
      refreshStatus();
    } catch (err) {
      toast(err.message, 'err');
    } finally {
      btn.disabled = false;
      btn.textContent = '⌨️ Commands connect karo';
    }
  });

  $('#invite-btn').addEventListener('click', async () => {
    try {
      const data = await api('/api/bot/invite');
      window.open(data.url, '_blank', 'noopener');
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  $('#stop-btn').addEventListener('click', async () => {
    try {
      await api('/api/bot/stop', { method: 'POST' });
      toast('Bot band kar diya.');
      refreshStatus();
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  $('#restart-btn').addEventListener('click', async () => {
    try {
      await api('/api/bot/restart', { method: 'POST', body: {} });
      toast('Restart ho raha hai…');
      setTimeout(refreshStatus, 1500);
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  /* ---------------- Premium ---------------- */
  $('#premium-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const guildId = $('#premium-guild').value;
    const query = $('#premium-user').value.trim();
    if (!guildId) return toast('Pehle bot online karo / server choose karo.', 'err');
    if (!query) return toast('Member ka ID ya naam daalo.', 'err');

    try {
      const data = await api('/api/premium', { method: 'POST', body: { guildId, query } });
      toast(`⭐ ${data.username || data.userId} ko premium mil gaya (free)!`);
      $('#premium-user').value = '';
      loadStats();
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  /* ---------------- Stats ---------------- */
  async function loadStats() {
    const data = await api('/api/stats');
    $('#stat-players').textContent = fmt(data.totalPlayers);
    $('#stat-claims').textContent = fmt(data.totalClaims);
    $('#stat-coins').textContent = fmt(data.totalCoins);
    $('#stat-premium').textContent = fmt(data.premiumPlayers);
  }

  /* ---------------- Quests ---------------- */
  function questCard(quest, type) {
    const tags = [];
    if (type === 'premium' || quest.premiumOnly) tags.push('<span class="tag premium">premium</span>');
    if (type === 'weekly') tags.push('<span class="tag weekly">weekly</span>');
    if (type === 'once') tags.push('<span class="tag once">one-time</span>');

    return `
      <div class="quest">
        <span class="emoji">${quest.emoji || '🎯'}</span>
        <div class="body">
          <div class="title">${escapeHtml(quest.title)} ${tags.join(' ')}</div>
          <div class="meta">${quest.target} ${escapeHtml(quest.metricLabel || quest.metric)}</div>
        </div>
        <span class="reward">${quest.reward.coins} 🪙 · ${quest.reward.xp} XP</span>
      </div>`;
  }

  async function loadQuests() {
    const data = await api('/api/quests');

    const catalog = data.catalog;
    const withLabel = (list) => list.map((q) => ({ ...q, metricLabel: q.metricLabel }));

    $('#today-quests').innerHTML = data.today.map((q) => questCard(q, 'daily')).join('');
    $('#week-quests').innerHTML = data.week.map((q) => questCard(q, 'weekly')).join('');
    $('#daily-count').textContent = data.today.length;
    $('#weekly-count').textContent = data.week.length;

    const groups = [
      ['📅 Daily pool', withLabel(catalog.daily), 'daily'],
      ['⭐ Premium daily (free)', withLabel(catalog.premium), 'premium'],
      ['🗓️ Weekly pool', withLabel(catalog.weekly), 'weekly'],
      ['🎖️ One-time', withLabel(catalog.once), 'once'],
    ];

    $('#catalog').innerHTML = groups
      .map(
        ([title, list, type]) =>
          `<div class="meta" style="margin:14px 0 8px;font-weight:700;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.6px">${title}</div>` +
          list.map((q) => questCard(q, type)).join('')
      )
      .join('');
  }

  /* ---------------- Leaderboard ---------------- */
  async function loadBoard() {
    const data = await api('/api/stats');
    const tbody = $('#board-body');

    if (!data.top.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="muted">Abhi koi data nahi — members /quest chala ke shuru karein.</td></tr>';
      return;
    }

    tbody.innerHTML = data.top
      .map(
        (row, i) => `
        <tr>
          <td class="pos">${i + 1}</td>
          <td><code>${row.userId}</code></td>
          <td>${fmt(row.questsDone)}</td>
          <td>${fmt(row.coins)} 🪙</td>
          <td>${row.level}</td>
          <td>🔥 ${row.streak}</td>
          <td>${row.premium ? '⭐' : '—'}</td>
        </tr>`
      )
      .join('');
  }

  /* ---------------- Access keys ---------------- */
  async function loadKeys() {
    if (me?.role !== 'owner') return;

    const data = await api('/api/access');
    $('#keys-count').textContent = data.keys.length;

    if (!data.keys.length) {
      $('#keys-list').innerHTML = '<p class="muted">Abhi koi key nahi — upar se banao.</p>';
      return;
    }

    $('#keys-list').innerHTML = data.keys
      .map(
        (key) => `
        <div class="key-row ${key.enabled ? '' : 'disabled'}">
          <div class="info">
            <b>${escapeHtml(key.label)}</b>
            <div><span class="badge ${key.role}">${key.role}</span> · <code>${key.masked}</code></div>
            <div>Banayi ${new Date(key.createdAt).toLocaleDateString('en-IN')}${
              key.lastUsedAt ? ` · last use ${new Date(key.lastUsedAt).toLocaleString('en-IN')}` : ' · kabhi use nahi hui'
            }</div>
          </div>
          <button class="btn ghost small" data-toggle="${key.id}" data-enabled="${key.enabled ? '0' : '1'}">
            ${key.enabled ? 'Disable' : 'Enable'}
          </button>
          <button class="btn danger small" data-revoke="${key.id}">Revoke</button>
        </div>`
      )
      .join('');

    $$('[data-toggle]').forEach((btn) =>
      btn.addEventListener('click', async () => {
        await api(`/api/access/${btn.dataset.toggle}`, {
          method: 'PATCH',
          body: { enabled: btn.dataset.enabled === '1' },
        }).catch((err) => toast(err.message, 'err'));
        loadKeys();
      })
    );

    $$('[data-revoke]').forEach((btn) =>
      btn.addEventListener('click', async () => {
        await api(`/api/access/${btn.dataset.revoke}`, { method: 'DELETE' }).catch((err) => toast(err.message, 'err'));
        toast('Key revoke ho gayi — us bande ka access band.');
        loadKeys();
      })
    );
  }

  $('#access-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const data = await api('/api/access', {
        method: 'POST',
        body: { label: $('#access-label').value || 'Guest', role: $('#access-role').value },
      });

      $('#new-key-box').classList.remove('hidden');
      $('#new-key-value').textContent = data.key;
      $('#access-label').value = '';
      toast('Key ban gayi — copy karke bhej do.');
      loadKeys();
    } catch (err) {
      toast(err.message, 'err');
    }
  });

  $('#copy-key').addEventListener('click', async () => {
    const value = $('#new-key-value').textContent;
    try {
      await navigator.clipboard.writeText(value);
      toast('Copy ho gayi ✅');
    } catch {
      toast('Copy nahi hui — manually select karo.', 'err');
    }
  });

  /* ---------------- Boot ---------------- */
  async function boot() {
    let data;
    try {
      data = await api('/api/me');
    } catch {
      showLogin();
      return;
    }

    me = data;
    showApp();
    await refreshStatus();
    await loadQuests();
  }

  function escapeHtml(text) {
    return String(text ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
  }

  boot();
})();
