# Credits: gogeta_gg
import asyncio, os, sys, sqlite3, tempfile, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import harness_am as H
am = H.am
GID = H.GID
fails = []
def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond: fails.append(name)

async def fresh(**settings):
    # new DB per scenario
    am.DB_PATH = Path(tempfile.mkdtemp()) / "am.db"
    cog = H.make_cog()
    if settings: cog.db.update_settings(GID, **settings); cog.invalidate(GID)
    return cog

async def blocked(cog, text, **kw):
    m, sigs = await H.run(cog, text, **kw)
    return bool(sigs) and sigs != "EXEMPT", m, sigs

async def main():
    cog = await fresh()
    uid = [2000]
    def nu():
        uid[0] += 1; return uid[0]
    # ---- must be blocked (default policy block_all)
    for label, text in [
        ("scheme link", "see https://evil.example.com/x"),
        ("www link", "www.evil-site.com"),
        ("bare .com", "visit evil-site.com now"),
        ("bare .xyz path", "free stuff at promo.xyz/gift"),
        ("ip url", "http://192.168.4.4:8080/login"),
        ("masked markdown", "[click me](https://evil.example.com)"),
        ("hxxp", "hxxps://evil.example.com/a"),
        ("dot-word obfuscation", "evil-site dot com"),
        ("bracket dot", "evil-site[.]com/free"),
        ("invite", "join discord.gg/abcdef"),
        ("invite zero-width after slash", "join discord.gg/\u200babcdef"),
        ("invite zero-width in host", "join disc\u200bord.gg/abcdef"),
        ("invite spaced", "join discord . gg / abcdef"),
        ("invite dsc.gg", "join dsc.gg/abcdef"),
        ("invite discord.com/invite", "https://discord.com/invite/abcdef"),
        ("invite bracket dot", "discord[.]gg/abcdef"),
        ("invite fullwidth", "join ｄｉｓｃｏｒｄ.ｇｇ/abcdef"),
        ("invite dot-word", "discord dot gg slash abcdef"),
    ]:
        b, m, sigs = await blocked(cog, text, author_id=nu())
        check(f"blocks: {label}", b and m.delete.await_count == 1, sigs)
    # ---- must NOT be blocked
    for label, text in [
        ("plain chat", "hello everyone, how are you today?"),
        ("filename .py", "open main.py and check utils.py"),
        ("filename .sh", "run install.sh please"),
        ("filename .zip", "send me the backup.zip"),
        ("email", "mail me at bob@gmail.com"),
        ("version", "python 3.12.1 is out"),
        ("sentence no space", "I agree.So we go"),
        ("abbrev", "e.g. this and i.e. that"),
        ("discord word", "I love discord and gg wp"),
    ]:
        b, m, sigs = await blocked(cog, text, author_id=nu())
        check(f"allows: {label}", not b, sigs)
    # ---- allowed domain
    cog.db.add_value("am_allowed_domains", "domain", GID, "tenor.com"); cog.invalidate(GID)
    b, m, sigs = await blocked(cog, "https://tenor.com/view/cat-123", author_id=nu())
    check("allowed domain passes", not b, sigs)
    b, m, sigs = await blocked(cog, "https://sub.tenor.com/view/cat-123", author_id=nu())
    check("allowed domain subdomain passes", not b, sigs)
    b, m, sigs = await blocked(cog, "https://tenor.com.evil.io/x", author_id=nu())
    check("lookalike of allowed domain blocked", b, sigs)
    # ---- policies
    cog.db.update_settings(GID, link_policy="allow_all"); cog.invalidate(GID)
    b, m, sigs = await blocked(cog, "https://evil.example.com/x", author_id=nu())
    check("allow_all lets generic link through", not b, sigs)
    b, m, sigs = await blocked(cog, "join discord.gg/abcdef", author_id=nu())
    check("allow_all still blocks invites (separate rule)", b, sigs)
    cog.db.update_settings(GID, link_policy="block_configured"); cog.invalidate(GID)
    b, m, sigs = await blocked(cog, "https://evil.example.com/x", author_id=nu())
    check("block_configured: external class off -> passes", not b, sigs)
    cog.db.toggle_link(GID, "external", True); cog.invalidate(GID)
    b, m, sigs = await blocked(cog, "https://evil.example.com/x", author_id=nu())
    check("block_configured: external class on -> blocked", b, sigs)
    cog.db.update_settings(GID, link_policy="block_all"); cog.invalidate(GID)
    # ---- trust / exemptions
    cog.db.trust(GID, "user", 777, True); cog.db.trust(GID, "role", 888, True); cog.db.trust(GID, "channel", 999, True); cog.invalidate(GID)
    for label, kw in [("trusted user", dict(author_id=777)), ("trusted role", dict(author_id=nu(), roles=[888])), ("trusted channel", dict(author_id=nu(), channel_id=999))]:
        b, m, sigs = await blocked(cog, "https://evil.example.com/x", **kw)
        check(f"exempt: {label}", not b and sigs == "EXEMPT", sigs)
    b, m, sigs = await blocked(cog, "https://evil.example.com/x", author_id=nu(), bot=True)
    check("bot account ignored (ignore_bots on)", not b)
    b, m, sigs = await blocked(cog, "https://evil.example.com/x", author_id=nu(), bot=True, webhook_id=1234)
    check("WEBHOOK post is scanned even with ignore_bots", b, sigs)
    # ---- escalation: 'delete' action must reach ban at ban_after
    cog = await fresh(default_action="delete", ban_after=3, strike_decay=600)
    victim = 4242
    last = None
    for i in range(3):
        m, sigs = await H.run(cog, f"https://evil.example.com/{i}", author_id=victim)
        last = m
    check("delete-action user is banned at ban_after strikes", last.guild.ban.await_count == 1)
    inc = cog.db.incidents(GID, 10)
    check("incidents recorded for every violation", len(inc) == 3, len(inc))
    check("last incident action is ban", inc[0]["action"] == "ban", inc[0]["action"])
    # ---- delete_trigger off must not disable 'delete' action
    cog = await fresh(default_action="delete", delete_trigger=0)
    m, sigs = await H.run(cog, "https://evil.example.com/x", author_id=5151)
    check("action=delete deletes even when delete_trigger=0", m.delete.await_count == 1)
    # ---- log_only never deletes/punishes
    cog = await fresh(default_action="log_only")
    for r in list(am.RULES): cog.db.update_rule(GID, r, action="inherit")
    cog.invalidate(GID)
    m, sigs = await H.run(cog, "https://evil.example.com/x", author_id=5252)
    check("log_only: no delete, no ban", m.delete.await_count == 0 and m.guild.ban.await_count == 0)
    # ---- timeout failing is recorded, incident still written
    cog = await fresh(default_action="timeout")
    import discord
    from unittest.mock import AsyncMock, MagicMock
    m = H.make_message("hey @everyone buy", author_id=6161)
    m.mention_everyone = True
    resp = MagicMock(); resp.status = 403; resp.reason = "Forbidden"
    m.author.timeout = AsyncMock(side_effect=discord.Forbidden(resp, "Missing Permissions"))
    sigs = cog.detect(m); await cog.enforce(m, sigs)
    inc = cog.db.incidents(GID, 5)
    check("failed timeout still writes an incident (success=0)", len(inc) == 1 and inc[0]["success"] == 0, [dict(i) for i in inc])
    # ---- forwarded snapshot content is scanned
    cog = await fresh()
    m = H.make_message("", author_id=7171, snapshots=[type("S", (), {"content": "join discord.gg/abcdef"})()])
    sigs = cog.detect(m)
    check("forwarded (snapshot) invite is detected", "discord_invites" in sigs, sigs)

    # ---- legacy import is ONE-TIME (removed trust/words/rule edits must stick)
    am.DB_PATH = Path(tempfile.mkdtemp()) / "am.db"
    c = sqlite3.connect(am.DB_PATH)
    c.executescript("""
      CREATE TABLE settings(guild_id INTEGER PRIMARY KEY, enabled INTEGER, log_channel_id INTEGER, timeout_seconds INTEGER, ban_after INTEGER, trigger_after INTEGER, punishment_mode TEXT, decay_seconds INTEGER, delete_trigger INTEGER, ignore_bots INTEGER);
      CREATE TABLE rules(guild_id INTEGER, rule TEXT, enabled INTEGER, threshold INTEGER, window_seconds INTEGER, PRIMARY KEY(guild_id,rule));
      CREATE TABLE whitelist_users(guild_id INTEGER, user_id INTEGER, PRIMARY KEY(guild_id,user_id));
      CREATE TABLE whitelist_roles(guild_id INTEGER, role_id INTEGER, PRIMARY KEY(guild_id,role_id));
      CREATE TABLE blocked_words(guild_id INTEGER, word TEXT, PRIMARY KEY(guild_id,word));
    """)
    c.execute("INSERT INTO settings VALUES(?,1,NULL,300,5,1,'timeout',600,1,1)", (GID,))
    c.execute("INSERT INTO rules VALUES(?,?,?,?,?)", (GID, "spam", 1, 6, 8))
    c.execute("INSERT INTO whitelist_users VALUES(?,?)", (GID, 111)); c.execute("INSERT INTO whitelist_roles VALUES(?,?)", (GID, 222)); c.execute("INSERT INTO blocked_words VALUES(?,?)", (GID, "badword"))
    c.commit(); c.close()
    db = am.AMDB(); db.ensure(GID)
    check("legacy trust imported once", 111 in db.trust_sets(GID)["user"] and 222 in db.trust_sets(GID)["role"])
    check("legacy words imported once", "badword" in db.list_table("am_words", GID, "word"))
    db.trust(GID, "user", 111, False); db.trust(GID, "role", 222, False); db.remove_value("am_words", "word", GID, "badword")
    db.update_rule(GID, "rapid_spam", threshold=2, enabled=0)
    for _ in range(5): db.settings(GID); db.rules(GID)   # simulate the 5s cache refreshes
    check("removed trusted user stays removed", 111 not in db.trust_sets(GID)["user"])
    check("removed trusted role stays removed", 222 not in db.trust_sets(GID)["role"])
    check("removed word stays removed", "badword" not in db.list_table("am_words", GID, "word"))
    check("rule edit is not reverted", db.rules(GID)["rapid_spam"]["threshold"] == 2 and db.rules(GID)["rapid_spam"]["enabled"] == 0)
    # ---- link_policy migration for an existing DB on the old default
    am.DB_PATH = Path(tempfile.mkdtemp()) / "am2.db"
    c = sqlite3.connect(am.DB_PATH)
    c.executescript("""CREATE TABLE am_settings(guild_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, log_channel_id INTEGER, default_action TEXT NOT NULL DEFAULT 'delete', timeout_seconds INTEGER NOT NULL DEFAULT 300, trigger_after INTEGER NOT NULL DEFAULT 1, ban_after INTEGER NOT NULL DEFAULT 5, strike_decay INTEGER NOT NULL DEFAULT 900, delete_trigger INTEGER NOT NULL DEFAULT 1, ignore_bots INTEGER NOT NULL DEFAULT 1, mention_limit INTEGER NOT NULL DEFAULT 6, link_policy TEXT NOT NULL DEFAULT 'block_configured', max_content_length INTEGER NOT NULL DEFAULT 3000, quarantine_role_id INTEGER);""")
    c.execute("INSERT INTO am_settings(guild_id,enabled,log_channel_id) VALUES(1,1,5)"); c.execute("INSERT INTO am_settings(guild_id,link_policy) VALUES(2,'allow_all')"); c.commit(); c.close()
    db = am.AMDB()
    check("old-default guild upgraded to block_all", db.settings(1)["link_policy"] == "block_all")
    check("explicit admin choice (allow_all) preserved", db.settings(2)["link_policy"] == "allow_all")
    db.update_settings(1, link_policy="block_configured"); am.AMDB()
    check("migration does not re-run (admin choice sticks)", am.AMDB().settings(1)["link_policy"] == "block_configured")

    print("\n%d failure(s)" % len(fails))
    for f in fails: print(" -", f)
    return len(fails)

if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
