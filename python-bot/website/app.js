/* Gogeta's Pet — command explorer + connect helper. Credits: gogeta_gg */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const state = { data: null, query: "", type: "all", cog: "all" };
  const STORE = { clientId: "gogetasPet.clientId", guildId: "gogetasPet.guildId" };

  /* ── toast ─────────────────────────────────────────────── */
  let toastTimer;
  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.add("is-on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove("is-on"), 1900);
  }

  async function copy(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label} copied`);
    } catch {
      toast("Copy nahi hua — manually select karo");
    }
  }

  /* ── command data ──────────────────────────────────────── */
  async function load() {
    try {
      const res = await fetch("commands.json", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      state.data = await res.json();
    } catch (err) {
      $("#result-count").textContent = `commands.json load nahi hui (${err.message}).`;
      return;
    }
    renderTotals();
    renderCogList();
    renderCommands();
  }

  function renderTotals() {
    const t = state.data.totals;
    $("#stat-commands").textContent = t.unique_commands;
    $("#stat-cogs").textContent = t.cogs_loaded;
    $("#stat-slash").textContent = t.slash_all;
    $("#cta-command-count").textContent = `${t.unique_commands} commands`;
    $("#generated").textContent = `Commands data generated ${state.data.generated_at} from the loaded cogs.`;
    $("#footer-generated").textContent = `commands.json · ${state.data.generated_at}`;
  }

  function renderCogList() {
    const list = $("#cog-list");
    list.innerHTML = "";

    const total = state.data.cogs.reduce((sum, cog) => sum + cog.commands.length, 0);
    list.append(cogButton("all", `All cogs`, total));

    for (const cog of state.data.cogs) {
      list.append(cogButton(cog.name, cog.name, cog.commands.length));
    }
  }

  function cogButton(value, label, count) {
    const li = el("li");
    const btn = el("button");
    btn.type = "button";
    btn.dataset.cog = value;
    btn.classList.toggle("is-active", state.cog === value);
    btn.append(el("span", null, label), el("span", "count", String(count)));
    btn.addEventListener("click", () => {
      state.cog = state.cog === value ? "all" : value;
      document.querySelectorAll("#cog-list button").forEach((b) => {
        b.classList.toggle("is-active", b.dataset.cog === state.cog);
      });
      renderCommands();
    });
    li.append(btn);
    return li;
  }

  /* ── filtering + rendering ─────────────────────────────── */
  function matches(cmd) {
    if (state.cog !== "all" && cmd.cog !== state.cog) return false;
    if (state.type === "slash" && !(cmd.type === "slash" || cmd.type === "group")) return false;
    if (state.type === "slash+prefix" && cmd.type !== "slash+prefix") return false;
    if (state.type === "group" && cmd.type !== "group") return false;
    if (!state.query) return true;
    const haystack = `${cmd.name} ${cmd.group || ""} ${cmd.description} ${cmd.cog}`.toLowerCase();
    return state.query
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean)
      .every((part) => haystack.includes(part));
  }

  function badgeClass(type) {
    if (type === "slash+prefix") return "hybrid";
    if (type === "group") return "group";
    if (type === "prefix") return "prefix";
    return "slash";
  }

  function badgeLabel(type) {
    if (type === "slash+prefix") return "slash + prefix";
    return type;
  }

  function commandCard(cmd) {
    const card = el("div", "cmd");
    if (cmd.group) card.classList.add("cmd-sub");

    const title = el("div", "cmd-name");
    title.textContent = cmd.group ? `${cmd.group} ${cmd.name.split(" ").pop()}` : cmd.name;

    const meta = el("div", "cmd-meta");
    meta.append(el("span", `badge ${badgeClass(cmd.type)}`, badgeLabel(cmd.type)));

    const copyBtn = el("button", "copy", "⧉");
    copyBtn.type = "button";
    copyBtn.title = "Copy command";
    copyBtn.setAttribute("aria-label", `Copy ${cmd.name}`);
    copyBtn.addEventListener("click", () => copy(`/${cmd.name}`, `/${cmd.name}`));
    meta.append(copyBtn);

    card.append(title, meta, el("p", "cmd-desc", cmd.description || "—"));
    return card;
  }

  function renderCommands() {
    const list = $("#command-list");
    const empty = $("#empty");
    list.innerHTML = "";

    let shown = 0;
    for (const cog of state.data.cogs) {
      const cmds = cog.commands.filter(matches);
      if (!cmds.length) continue;

      // Only show per-cog headers when we're browsing everything.
      if (state.cog === "all" && !state.query) {
        list.append(el("h3", "cmd-group-title", `${cog.name} · ${cmds.length}`));
      }
      for (const cmd of cmds) {
        list.append(commandCard(cmd));
        shown += 1;
      }
    }

    empty.hidden = shown > 0;
    const scope = state.cog === "all" ? "all cogs" : state.cog;
    $("#result-count").textContent = `${shown} command${shown === 1 ? "" : "s"} · ${scope}`;
  }

  /* ── connect (client id + guild id -> invite url) ──────── */
  const PERMISSIONS = "8"; // Administrator
  const SCOPES = "bot applications.commands";

  function buildInvite(clientId) {
    return `https://discord.com/api/oauth2/authorize?client_id=${encodeURIComponent(clientId)}` +
      `&permissions=${PERMISSIONS}&scope=${encodeURIComponent(SCOPES)}`;
  }

  function refreshInvite() {
    const clientId = $("#client-id").value.trim();
    const guildId = $("#guild-id").value.trim();
    const preview = $("#invite-preview");

    if (!/^\d{15,25}$/.test(clientId)) {
      preview.hidden = true;
      return;
    }

    const url = buildInvite(clientId);
    $("#invite-url").textContent = url;
    $("#open-invite").href = url;
    $("#invite-note").textContent = /^\d{15,25}$/.test(guildId)
      ? `Sync ke liye .env me DISCORD_GUILD_ID=${guildId} daalo, phir: python scripts/sync_commands.py`
      : "Guild ID optional hai — global sync ke liye sirf bot.py chalao.";
    preview.hidden = false;
  }

  function loadSaved() {
    $("#client-id").value = localStorage.getItem(STORE.clientId) || "";
    $("#guild-id").value = localStorage.getItem(STORE.guildId) || "";
    refreshInvite();
  }

  $("#connect-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const clientId = $("#client-id").value.trim();
    if (!/^\d{15,25}$/.test(clientId)) {
      toast("Client ID 15–25 digit ka numeric ID hona chahiye");
      return;
    }
    localStorage.setItem(STORE.clientId, clientId);
    localStorage.setItem(STORE.guildId, $("#guild-id").value.trim());
    refreshInvite();
    toast("Saved in this browser only");
  });

  ["#client-id", "#guild-id"].forEach((sel) =>
    $(sel).addEventListener("input", refreshInvite)
  );

  $("#connect-reset").addEventListener("click", () => {
    localStorage.removeItem(STORE.clientId);
    localStorage.removeItem(STORE.guildId);
    $("#client-id").value = "";
    $("#guild-id").value = "";
    refreshInvite();
    toast("Cleared");
  });

  $("#copy-invite").addEventListener("click", () =>
    copy($("#invite-url").textContent, "Invite link")
  );

  /* ── filters / search ──────────────────────────────────── */
  $("#search").addEventListener("input", (event) => {
    state.query = event.target.value.trim();
    renderCommands();
  });

  $("#type-filters").addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-type]");
    if (!btn) return;
    state.type = btn.dataset.type;
    document.querySelectorAll("#type-filters .chip").forEach((chip) => {
      chip.classList.toggle("is-active", chip === btn);
    });
    renderCommands();
  });

  $("#reset").addEventListener("click", () => {
    state.query = "";
    state.type = "all";
    state.cog = "all";
    $("#search").value = "";
    document.querySelectorAll("#type-filters .chip").forEach((chip) => {
      chip.classList.toggle("is-active", chip.dataset.type === "all");
    });
    document.querySelectorAll("#cog-list button").forEach((b) => {
      b.classList.toggle("is-active", b.dataset.cog === "all");
    });
    renderCommands();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && document.activeElement.tagName !== "INPUT") {
      event.preventDefault();
      $("#search").focus();
    }
    if (event.key === "Escape" && document.activeElement === $("#search")) {
      $("#search").value = "";
      state.query = "";
      renderCommands();
      $("#search").blur();
    }
  });

  loadSaved();
  load();
})();
