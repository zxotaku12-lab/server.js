# Credits: gogeta_gg
import asyncio, os, sys, sqlite3, tempfile, time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, AsyncMock
ROOT = Path(os.environ.get("BOT_ROOT", Path(__file__).resolve().parents[1])); sys.path.insert(0, str(ROOT))
import discord
import cogs.antinuke as an
import cogs.antibetray as ab
import cogs.antibetray_db as abdb
import cogs.antinuke_db as andb

GID, OWNER, BOT_ID = 123456789012345678, 1, 99
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra != "" and not cond) else ""))
    if not cond: fails.append(name)

class Perms:
    def __init__(self, **kw):
        for k in ("view_audit_log","ban_members","kick_members","manage_roles","manage_channels","manage_guild","administrator","manage_messages","moderate_members"):
            setattr(self, k, kw.get(k, True if k != "administrator" else False))
def http403():
    r = MagicMock(); r.status = 403; r.reason = "Forbidden"; return discord.Forbidden(r, "Missing Permissions")

def make_guild(entries, perms=None):
    g = MagicMock(spec=discord.Guild); g.id = GID; g.owner_id = OWNER
    g.me = MagicMock(); g.me.id = BOT_ID; g.me.guild_permissions = perms or Perms()
    g.get_channel.return_value = None; g.get_role.return_value = None; g.get_member.return_value = None
    g.ban = AsyncMock(); g.kick = AsyncMock(); g.calls = []; g.roles = []; g.channels = []; g.create_role = AsyncMock(side_effect=http403())
    async def gen(limit=100, action=None, **kw):
        for e in sorted(entries(), key=lambda e: e.created_at, reverse=True):
            if action is not None and e.action != action: continue
            yield e
    g.audit_logs = gen
    return g

def make_member(uid, *, roles=(), bot=False, admin=False, guild=None):
    m = MagicMock(spec=discord.Member); m.id = uid; m.bot = bot; m.guild = guild
    rs = []
    for r in roles:
        role = MagicMock(); role.id = r; role.is_assignable.return_value = True; role.is_default.return_value = False; role.managed = False; role.name = f"r{r}"
        rs.append(role)
    m.roles = rs; m.mention = f"<@{uid}>"
    m.guild_permissions = Perms(administrator=admin, ban_members=admin, kick_members=admin, manage_roles=admin, manage_channels=admin, manage_guild=admin, manage_webhooks=admin) if admin else Perms(ban_members=False, kick_members=False, manage_roles=False, manage_channels=False, manage_guild=False)
    m.remove_roles = AsyncMock(); m.add_roles = AsyncMock(); m.kick = AsyncMock()
    return m

_eid = [1000]
def entry(action, user, target_id=None):
    _eid[0] += 1
    return NS(id=_eid[0], created_at=discord.utils.utcnow(), user=user, target=NS(id=target_id) if target_id is not None else None, action=action)

def fresh_nuke():
    an.DB_PATH = Path(tempfile.mkdtemp()) / "an.db"
    an.AUDIT_RETRIES = (0.0, 0.01); an.CACHE_TTL = 0.0
    bot = MagicMock(); bot.user = NS(id=BOT_ID)
    cog = an.Antinuke(bot)
    cog.db.ensure(GID); cog.db.update_settings(GID, enabled=1, default_action="ban", global_threshold=50)
    cog.invalidate(GID)
    return cog

async def main():
    A = discord.AuditLogAction
    # ============================ Anti-Nuke
    cog = fresh_nuke(); ents = []
    g = make_guild(lambda: ents)
    attacker = make_member(500, roles=[7], guild=g)

    # exempt logic
    cog.db.trust(GID, "user", 600, True); cog.db.trust(GID, "role", 61, True); cog.db.trust(GID, "bot", 700, True); cog.invalidate(GID)
    check("owner is exempt", cog.actor_exempt(g, NS(id=OWNER)))
    check("own bot is exempt", cog.actor_exempt(g, NS(id=BOT_ID)))
    check("trusted user exempt", cog.actor_exempt(g, make_member(600)))
    check("trusted role exempt", cog.actor_exempt(g, make_member(601, roles=[61])))
    check("random member NOT exempt", not cog.actor_exempt(g, make_member(602, roles=[9])))
    check("untrusted bot NOT exempt", not cog.actor_exempt(g, make_member(701, bot=True)))

    # threshold + ban
    ch = lambda i: NS(id=i, guild=g, delete=AsyncMock())
    for i in (1, 2):
        ents.append(entry(A.channel_delete, attacker, i))
        await cog.on_guild_channel_delete(ch(i))
    check("2 channel deletes (threshold 2/10) -> actor banned", g.ban.await_count == 1 and g.ban.await_args.args[0].id == 500)
    inc = cog.db.incidents(GID, 5)
    check("incident recorded success", len(inc) == 1 and inc[0]["success"] == 1 and inc[0]["action"] == "ban", [dict(i) for i in inc])

    # cooldown after success
    ents.append(entry(A.channel_delete, attacker, 3)); ents.append(entry(A.channel_delete, attacker, 4))
    await cog.on_guild_channel_delete(ch(3)); await cog.on_guild_channel_delete(ch(4))
    check("success cooldown suppresses duplicate containment", g.ban.await_count == 1)

    # fallback chain ban->kick
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents); attacker = make_member(501, roles=[7], guild=g)
    g.ban = AsyncMock(side_effect=http403())
    for i in (1, 2):
        ents.append(entry(A.channel_delete, attacker, i)); await cog.on_guild_channel_delete(NS(id=i, guild=g))
    check("ban Forbidden -> falls back to kick", g.kick.await_count == 1)
    inc = cog.db.incidents(GID, 5)
    check("fallback incident logged as kick + success", inc and inc[0]["action"] == "kick" and inc[0]["success"] == 1, [dict(i) for i in inc])

    # total failure -> failed incident and quick retry (not 30s cooldown)
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents); attacker = make_member(502, roles=[7], guild=g)
    stuck = MagicMock(); stuck.is_assignable.return_value = False; stuck.is_default.return_value = False; stuck.managed = False; stuck.name = "HighRole"
    attacker.roles = [stuck]; g.get_member.return_value = attacker
    g.ban = AsyncMock(side_effect=http403()); g.kick = AsyncMock(side_effect=http403())
    for i in (1, 2):
        ents.append(entry(A.channel_delete, attacker, i)); await cog.on_guild_channel_delete(NS(id=i, guild=g))
    inc = cog.db.incidents(GID, 5)
    check("all responses fail -> incident success=0 with reasons", inc and inc[0]["success"] == 0 and "HighRole" in inc[0]["detail"], [dict(i) for i in inc])
    cog._contained[(GID, 502)] = (time.monotonic() - 5, False)   # 5s later (> FAILED_RETRY_COOLDOWN)
    ents.append(entry(A.channel_delete, attacker, 3)); ents.append(entry(A.channel_delete, attacker, 4))
    n0 = g.ban.await_count
    await cog.on_guild_channel_delete(NS(id=3, guild=g)); await cog.on_guild_channel_delete(NS(id=4, guild=g))
    check("failed containment is retried after a few seconds (not the full cooldown)", g.ban.await_count > n0)

    # audit dedupe: two rapid emoji events must both be attributed
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents); actor = make_member(503, roles=[7], guild=g)
    cog.db.update_rule(GID, "emoji_change", threshold=2, window_seconds=15)
    e1 = entry(A.emoji_create, actor); await asyncio.sleep(0.01); e2 = entry(A.emoji_create, actor)
    ents.extend([e1, e2])
    await cog.on_guild_emojis_update(g, (), ()); await cog.on_guild_emojis_update(g, (), ())
    check("two rapid emoji changes both attributed -> threshold reached -> contained", g.ban.await_count == 1, g.ban.await_count)

    # unattributed event: no crash, no action
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents)
    await cog.on_guild_channel_delete(NS(id=1, guild=g)); await cog.on_guild_channel_delete(NS(id=2, guild=g))
    check("no audit entry -> no action, no crash", g.ban.await_count == 0)

    # bot add: kicked BEFORE audit lookup; actor punished
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents); adder = make_member(504, roles=[7], guild=g)
    order = []
    newbot = make_member(800, bot=True, guild=g); newbot.guild = g
    newbot.kick = AsyncMock(side_effect=lambda **kw: order.append("kick"))
    orig = g.audit_logs
    async def spy(limit=100, action=None, **kw):
        order.append("audit")
        async for x in orig(limit=limit, action=action): yield x
    g.audit_logs = spy
    ents.append(entry(A.bot_add, adder, 800))
    await cog.on_member_join(newbot)
    check("untrusted bot is kicked before the audit lookup", order[:1] == ["kick"], order)
    check("adder of untrusted bot is banned (threshold 1)", g.ban.await_count == 1 and g.ban.await_args.args[0].id == 504)
    # trusted bot stays
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents)
    cog.db.trust(GID, "bot", 801, True); cog.invalidate(GID)
    tb = make_member(801, bot=True, guild=g); tb.kick = AsyncMock()
    await cog.on_member_join(tb)
    check("trusted bot is not kicked", tb.kick.await_count == 0)
    # trusted user adds untrusted bot -> bot removed, user not punished
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents)
    cog.db.trust(GID, "user", 505, True); cog.invalidate(GID)
    adder = make_member(505, guild=g); ub = make_member(802, bot=True, guild=g); ub.kick = AsyncMock()
    ents.append(entry(A.bot_add, adder, 802)); await cog.on_member_join(ub)
    check("trusted user adding untrusted bot: bot removed, adder not banned", ub.kick.await_count == 1 and g.ban.await_count == 0)

    # rollback of ALL recent role creations
    cog = fresh_nuke(); ents = []; g = make_guild(lambda: ents); actor = make_member(506, roles=[7], guild=g)
    deleted = []
    for i in range(5):
        role = MagicMock(); role.id = 900 + i; role.guild = g; role.permissions = discord.Permissions.none()
        role.delete = AsyncMock(side_effect=(lambda i=i, **kw: deleted.append(i)))
        ents.append(entry(A.role_create, actor, role.id)); await cog.on_guild_role_create(role)
    check("role_create burst (5/10s) -> ALL 5 roles rolled back, not just the last", sorted(deleted) == [0, 1, 2, 3, 4], deleted)

    # legacy import is one-time
    an.DB_PATH = Path(tempfile.mkdtemp()) / "legacy.db"
    c = sqlite3.connect(an.DB_PATH)
    c.executescript("""CREATE TABLE security_settings(guild_id INTEGER PRIMARY KEY, enabled INTEGER, log_channel_id INTEGER, punishment TEXT, global_threshold INTEGER, global_window INTEGER, auto_deploy INTEGER);
    CREATE TABLE security_rules(guild_id INTEGER, category TEXT, enabled INTEGER, threshold INTEGER, window_seconds INTEGER, punishment TEXT, PRIMARY KEY(guild_id,category));
    CREATE TABLE whitelist_users(guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id,user_id));
    CREATE TABLE whitelist_bots(guild_id INTEGER, bot_id INTEGER, PRIMARY KEY(guild_id,bot_id));""")
    c.execute("INSERT INTO security_settings VALUES(?,1,NULL,'ban',3,10,0)", (GID,)); c.execute("INSERT INTO whitelist_users VALUES(?,?)", (GID, 111)); c.execute("INSERT INTO whitelist_bots VALUES(?,?)", (GID, 222)); c.commit(); c.close()
    db = an.ANDB(); db.ensure(GID)
    check("legacy whitelist imported once", 111 in db.trust_sets(GID)[0] and 222 in db.trust_sets(GID)[2])
    db.trust(GID, "user", 111, False); db.update_settings(GID, enabled=0)
    for _ in range(4): db.settings(GID); db.rules(GID); db.trust_sets(GID)
    check("removed trusted user stays removed", 111 not in db.trust_sets(GID)[0])
    check("manually disabled firewall stays disabled", db.settings(GID)["enabled"] == 0)
    # pre-existing install (tables exist, no meta): upgrade must not overwrite
    an.DB_PATH = Path(tempfile.mkdtemp()) / "pre.db"
    c = sqlite3.connect(an.DB_PATH)
    c.executescript("""CREATE TABLE an_settings(guild_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, log_channel_id INTEGER, default_action TEXT NOT NULL DEFAULT 'ban', global_threshold INTEGER NOT NULL DEFAULT 3, global_window INTEGER NOT NULL DEFAULT 10, actor_cooldown INTEGER NOT NULL DEFAULT 30, quarantine_role_id INTEGER, auto_rollback INTEGER NOT NULL DEFAULT 1, owner_immune INTEGER NOT NULL DEFAULT 1, bots_require_trust INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE security_settings(guild_id INTEGER PRIMARY KEY, enabled INTEGER, log_channel_id INTEGER, punishment TEXT, global_threshold INTEGER, global_window INTEGER, auto_deploy INTEGER);""")
    c.execute("INSERT INTO an_settings(guild_id,enabled,default_action) VALUES(?,0,'strip_roles')", (GID,)); c.execute("INSERT INTO security_settings VALUES(?,1,NULL,'ban',3,10,0)", (GID,)); c.commit(); c.close()
    db = an.ANDB(); db.ensure(GID)
    check("upgrading an existing install does not flip a disabled guild back on", db.settings(GID)["enabled"] == 0 and db.settings(GID)["default_action"] == "strip_roles", db.settings(GID))

    # ============================ Anti-Betray
    abdb.DB_NAME = Path(tempfile.mkdtemp()) / "ab.db"; andb.DB_NAME = Path(tempfile.mkdtemp()) / "anl.db"
    ab.AUDIT_RETRY_DELAYS = (0.0, 0.01); ab.CACHE_TTL = 0.0
    abdb.setup_database()
    bot = MagicMock(); bot.user = NS(id=BOT_ID)
    bcog = ab.Antibetray(bot)
    abdb.set_enabled(GID, True); abdb.set_punishment(GID, "ban"); bcog.invalidate(GID)
    ents = []; g = make_guild(lambda: ents)
    admin = make_member(510, admin=True, guild=g); g.get_member.return_value = admin
    check("admin is watched", bcog.watched(g, admin))
    check("owner is not watched", not bcog.watched(g, NS(id=OWNER)))
    check("bot is not watched", not bcog.watched(g, make_member(511, bot=True)))
    # dedupe + threshold (trusted_channel_delete 2/10)
    for i in (1, 2):
        ents.append(entry(A.channel_delete, admin, i)); await bcog.on_guild_channel_delete(NS(id=i, guild=g))
    check("admin deleting 2 channels is contained (ban)", g.ban.await_count == 1)
    # fallback
    abdb.reset_guild(GID); abdb.setup_database(); abdb.set_enabled(GID, True); abdb.set_punishment(GID, "ban"); bcog.invalidate(GID)
    ents = []; g = make_guild(lambda: ents); admin = make_member(512, admin=True, guild=g); g.get_member.return_value = admin
    g.ban = AsyncMock(side_effect=http403()); admin.kick = AsyncMock()
    for i in (1, 2):
        ents.append(entry(A.channel_delete, admin, i)); await bcog.on_guild_channel_delete(NS(id=i, guild=g))
    check("Anti-Betray ban Forbidden -> falls back to kick", admin.kick.await_count == 1)
    # rapid attribution
    abdb.reset_guild(GID); abdb.setup_database(); abdb.set_enabled(GID, True); abdb.set_punishment(GID, "ban"); abdb.set_rule(GID, "trusted_integration", threshold=2, window_seconds=15); bcog.invalidate(GID)
    ents = []; g = make_guild(lambda: ents); admin = make_member(513, admin=True, guild=g); g.get_member.return_value = admin
    ents.extend([entry(A.integration_create, admin, 1), entry(A.integration_create, admin, 2)])
    await bcog.on_integration_create(NS(guild=g, id=1)); await bcog.on_integration_create(NS(guild=g, id=2))
    check("Anti-Betray attributes two rapid integration events", g.ban.await_count == 1, g.ban.await_count)
    # shared bot whitelist: trusted in Anti-Nuke (v3 table) => Anti-Betray must not kick it
    abdb.reset_guild(GID); abdb.setup_database(); abdb.set_enabled(GID, True); bcog.invalidate(GID)
    andb.add_whitelisted_bot(GID, 820)
    ents = []; g = make_guild(lambda: ents); admin = make_member(514, admin=True, guild=g)
    tb = make_member(820, bot=True, guild=g); tb.kick = AsyncMock(); ents.append(entry(A.bot_add, admin, 820))
    await bcog.on_member_join(tb)
    check("bot trusted via shared whitelist is NOT kicked by Anti-Betray", tb.kick.await_count == 0)
    ub = make_member(821, bot=True, guild=g); ub.kick = AsyncMock(); ents.append(entry(A.bot_add, admin, 821))
    await bcog.on_member_join(ub)
    check("untrusted bot added by an admin IS removed by Anti-Betray", ub.kick.await_count == 1)
    # whitelist helpers are views of an_trust (what the engine reads)
    andb.add_whitelisted_user(GID, 55)
    c = sqlite3.connect(andb.DB_NAME); rows = c.execute("SELECT kind,target_id FROM an_trust WHERE guild_id=?", (GID,)).fetchall(); c.close()
    check("antinuke_db whitelist writes the table the engine reads (an_trust)", ("user", 55) in rows and ("bot", 820) in rows, rows)

    print("\n%d failure(s)" % len(fails))
    for f in fails: print(" -", f)
    return len(fails)

if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
