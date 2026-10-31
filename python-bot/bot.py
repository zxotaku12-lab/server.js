# Credits: gogeta_gg
from ui.emoji import E
import ui.emoji as ui_emoji
import discord
from discord.ext import commands
from discord import app_commands
import os
import re
import asyncio
import ast
import random
import traceback
from pathlib import Path
import sys
from datetime import datetime, timezone
from env_loader import load_clean_dotenv
from command_collision_guard import make_cog_commands_unique
import activity
import inactivity
from cogs import giveaway_db, reaction_db, prefix_db, command_controls_db
from ui.emoji import bootstrap as bootstrap_emojis, start_refresh_task as start_emoji_refresh_task
from ui.pagination import Paginator
from banner import print_banner, CREDITS

# ==========================
# CONFIG
# ==========================
load_clean_dotenv()
print_banner("Gogeta")

TOKEN = os.getenv("TOKEN")

def _env_id(name: str) -> int:
    """Read one numeric Discord ID from .env (0 = unset/disabled)."""
    raw = os.getenv(name, "").strip()
    return int(raw) if raw.isdigit() else 0


def _env_id_list(name: str) -> list:
    """Read a comma/space separated list of numeric Discord IDs from .env."""
    return [int(x) for x in re.split(r"[,;\s]+", os.getenv(name, "")) if x.isdigit()]


# Bot owner(s): comma-separated Discord user IDs in .env (OWNER_IDS=1,2,3).
OWNER_IDS = _env_id_list("OWNER_IDS")

# The ONE person who bypasses every permission/role/staff requirement on
# every command in every server — even with zero roles or permissions.
# Deliberately separate from OWNER_IDS (which still only grants the normal
# bot-owner privileges discord.py itself understands, e.g. is_owner()).
# This constant is intentionally a single ID, not a list, so the bypass
# can never silently widen just by someone adding a second entry above.
DEVELOPER_BYPASS_ID = _env_id("DEVELOPER_BYPASS_ID")  # 0 = bypass disabled

# Only this user's mentions trigger the emoji reaction (separate from
# OWNER_IDS, which is still used for command permission checks below).
MENTION_REACT_USER_ID = _env_id("MENTION_REACT_USER_ID")  # 0 = disabled

MENTION_REACTION_EMOJIS = ("q_hype", "q_celebrate", "q_sparkle")

# Emojis used when the server's owner is mentioned (separate feature from
# the dev-mention reaction above). Only fires if dev-mention reaction did
# NOT already fire on this message — dev mentions take priority.
OWNER_REACTION_EMOJIS = ("q_time", "q_search", "q_heart")

# ==========================
# RANDOM MESSAGE REACTIONS
# (independent of the creator-mention reaction above — this reacts to
# ANY member's message, using emojis that belong to whichever server the
# message was sent in. Fully separate from MENTION_REACT_USER_ID/
# MENTION_REACTION_EMOJIS/reaction_db above, which are left untouched.)
# ==========================

# Chance (0.0-1.0) that any given non-bot guild message gets a random
# emoji reaction. Tune this to taste.
RANDOM_REACT_CHANCE = 0.07

# Used only if the server has no usable custom emojis of its own.
RANDOM_REACT_FALLBACK_EMOJIS = (
    "😀", "😂", "😍", "🔥", "🎉", "👍", "😎", "🤔", "💯",
    "😅", "🙌", "✨", "😱", "🥳", "😴", "👀", "🫡", "💀",
)

# ==========================
# INTENTS
# ==========================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
# Scheduled-event gateway events are non-privileged; enable them when the
# installed discord.py version exposes this flag so awareness can observe them.
if hasattr(intents, "guild_scheduled_events"):
    intents.guild_scheduled_events = True
if hasattr(intents, "moderation"):
    intents.moderation = True

async def _resolve_prefix(bot_instance: commands.Bot, message: discord.Message):
    # Per-guild prefix, configurable live via /prefix — falls back to the
    # global default (prefix_db.DEFAULT_PREFIX) in DMs or before a guild has
    # ever set one. Mentioning the bot always works too, regardless of
    # whatever custom prefix is set.
    base = prefix_db.get_prefix(message.guild.id) if message.guild is not None else prefix_db.DEFAULT_PREFIX
    return commands.when_mentioned_or(base)(bot_instance, message)


bot = commands.Bot(
    command_prefix=_resolve_prefix,
    intents=intents,
    help_command=None
)

# ==========================
# GLOBAL DEVELOPER BYPASS
# ==========================
# NOTE: this used to be registered with @bot.check, which is WRONG —
# discord.py ANDs every global check together (see Bot.can_run /
# discord.utils.async_all in discord/ext/commands/bot.py), so a global
# check returning False for anyone who isn't the developer blocks that
# person from EVERY command bot-wide, regardless of their permissions or
# any @commands.has_permissions decorator on the command. This was
# silently locking out every mod/admin — the "check functions for command
# X failed" errors were this, not a permissions problem.
#
# Fix: instead of a global check, prepend the bypass predicate directly to
# each individual command's own check list. discord.py's Command.can_run
# also uses async_all, but ONLY for that command's local `checks` list —
# and it's evaluated eagerly per-check with short-circuiting, so we exploit
# `or` semantics ourselves below instead of relying on discord.py's AND-only
# check composition. This makes it a true "skip everything else" bypass,
# scoped to hybrid/prefix commands only (slash-only commands still use the
# separate @bot.tree.error bypass further down).
def _install_developer_bypass(bot_instance: commands.Bot) -> None:
    for command in bot_instance.walk_commands():
        original_checks = list(command.checks)

        def make_wrapped(checks=original_checks, command_name=getattr(command, "qualified_name", command.name)):
            async def _wrapped(ctx: commands.Context) -> bool:
                if ctx.guild is not None and ctx.author.id != DEVELOPER_BYPASS_ID:
                    if not command_controls_db.is_enabled(ctx.guild.id, command_name):
                        raise commands.CheckFailure(f"The `{command_name}` command is disabled from the Gogeta Dashboard.")
                if ctx.author.id == DEVELOPER_BYPASS_ID:
                    return True
                for chk in checks:
                    result = chk(ctx)
                    if hasattr(result, "__await__"):
                        result = await result
                    if not result:
                        return False
                return True
            return _wrapped

        command.checks = [make_wrapped()]


# Same bypass, but for pure @app_commands.command slash commands (e.g.
# /gstart in giveaway.py). These never go through bot.process_commands()/
# _install_developer_bypass above (that only walks prefix/hybrid commands),
# and app_commands has no supported way to skip a
# @app_commands.checks.has_permissions(...) decorator that's already on a
# command. So instead: let the permission check fail normally, catch the
# resulting MissingPermissions error here, confirm it was the developer,
# and manually re-run the command with the permission check bypassed.
async def _dashboard_tree_command_control(interaction: discord.Interaction) -> bool:
    """Gate slash/hybrid app-command invocations using dashboard command state."""
    guild = interaction.guild
    command = interaction.command
    if guild is None or command is None or interaction.user.id == DEVELOPER_BYPASS_ID:
        return True
    name = getattr(command, "qualified_name", getattr(command, "name", ""))
    if command_controls_db.is_enabled(guild.id, name):
        return True
    message = f"{E('q_error')} The `/{name}` command is disabled from the Gogeta Dashboard."
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)
    except Exception:
        pass
    return False

# Defensive compatibility guard: if a host still has an older cogs/multi_ai.py,
# intercept its add_cog call and rename any legacy chatbot-command collision
# before discord.py can reject the entire extension. The MultiAI cog also runs
# this guard in its setup() for independent loading.
_original_add_cog = bot.add_cog

async def _guarded_add_cog(cog, *args, **kwargs):
    make_cog_commands_unique(bot, cog)
    return await _original_add_cog(cog, *args, **kwargs)

bot.add_cog = _guarded_add_cog
print("[StartupRepair v7] command-collision guard installed.")

bot.tree.interaction_check = _dashboard_tree_command_control

@bot.tree.error
async def _developer_tree_bypass_on_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if (
        isinstance(error, app_commands.MissingPermissions)
        and interaction.user.id == DEVELOPER_BYPASS_ID
        and interaction.command is not None
    ):
        try:
            # .callback is the raw underlying function, before any
            # @app_commands.checks decorator wraps it — calling it directly
            # is the documented way to invoke a command's logic while
            # skipping its checks. This is stable public API, unlike the
            # tree's internal invocation machinery.
            command = interaction.command
            if getattr(command, "binding", None) is not None:
                await command.callback(command.binding, interaction)
            else:
                await command.callback(interaction)
        except Exception as exc:
            print(f"[DeveloperBypass] Re-invoke failed for /{interaction.command.name}: {type(exc).__name__}: {exc}")
        return

    # Not a developer-bypass case. Log the full traceback exactly like
    # before (console visibility is unchanged), but ALSO actually tell
    # the Discord user something went wrong instead of leaving them
    # staring at a silent "did not respond" — this was the missing
    # piece: previously this just re-raised, which prints to console
    # but never touches the interaction at all.
    traceback.print_exception(type(error), error, error.__traceback__)

    safe_text = "⚠️ Something went wrong running that command. It's been logged — please try again in a moment."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(safe_text, ephemeral=True)
        else:
            await interaction.response.send_message(safe_text, ephemeral=True)
    except Exception:
        pass  # interaction is already dead/expired — nothing more we can do

# ==========================
# ONE-TIME STARTUP (setup_hook runs exactly once per process, before the
# gateway connection is even opened — unlike on_ready, which can fire again
# after every reconnect. DB setup, repairs, one-time migrations, and the
# slash-command sync all belong here so a network blip doesn't re-run them.)
# ==========================

async def _setup_hook():
    # A failure in one optional database must not prevent every extension from
    # being attempted. Keep each preflight independent and visible in the log.
    for label, initializer in (
        ("prefix database", prefix_db.setup_database),
        ("command-controls database", command_controls_db.setup_database),
    ):
        try:
            initializer()
        except Exception as exc:
            print(f"[Startup] {label} initialization failed: {type(exc).__name__}: {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    try:
        emoji_stats = await bootstrap_emojis(TOKEN)
        print(f"[Emoji] Startup registry: {emoji_stats.get('loaded', 0)}/{emoji_stats.get('allowed', 0)} approved names loaded.")
    except Exception as exc:
        print(f"[Startup] Emoji bootstrap failed; continuing with fallback emojis: {type(exc).__name__}: {exc}")
        traceback.print_exception(type(exc), exc, exc.__traceback__)

    global ui_embeds
    from ui import embeds as ui_embeds

    failed_cogs = []
    loaded_cogs = set()
    project_root = Path(__file__).resolve().parent
    cogs_dir = project_root / "cogs"
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    excluded = {
        "__init__.py", "giveaway_view.py", "giveaway_utils.py", "giveaway_db.py",
        "moderation_db.py", "antinuke_db.py", "apply_db.py", "apply_view.py",
        "spam_whitelist_db.py", "automod_db.py", "antibetray_db.py",
        "invite_tracker_db.py", "reaction_db.py", "security_ui.py",
        "security_ui_v2.py",
        "tickets_db.py", "tickets_view.py", "emoji_vault_db.py",
        "prefix_db.py", "ai_provider_pool.py", "embed_builder_view.py",
        "command_controls_db.py",
    }

    # Security cogs load first and are verified explicitly. This is independent
    # of the process working directory, which is important on hosted panels.
    critical_cogs = ("antinuke", "antibetray")

    # Do not depend solely on a hand-maintained helper-module exclusion list.
    # discord.py extensions require a module-level setup(bot) entry point.
    # Files without one are helpers/data modules and must never be load_extension'd.
    filenames = []
    enable_cv2_demo = os.getenv("ENABLE_CV2_TEST_COG", "").strip().lower() in ("1", "true", "yes", "on")
    for path in sorted(cogs_dir.glob("*.py")):
        if path.name in excluded or path.name == "__init__.py":
            continue
        # This is an interactive UI demo, not a production feature. Keep it
        # available for deliberate testing, but do not expose its test commands
        # in normal servers unless the operator explicitly opts in.
        if path.name == "cv2_test.py" and not enable_cv2_demo:
            print("[CogLoader] Skipping cv2_test.py demo cog (set ENABLE_CV2_TEST_COG=true to enable).")
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            print(f"[CogLoader] Skipping {path.name}: cannot parse source: {type(exc).__name__}: {exc}")
            continue
        has_setup = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "setup"
            for node in tree.body
        )
        if not has_setup:
            print(f"[CogLoader] Skipping helper module without setup(): {path.name}")
            continue
        filenames.append(path.name)
    ordered = list(critical_cogs) + [
        Path(name).stem for name in sorted(filenames)
        if Path(name).stem not in critical_cogs
    ]

    for cog_name in ordered:
        filename = f"{cog_name}.py"
        try:
            await bot.load_extension(f"cogs.{cog_name}")
            loaded_cogs.add(cog_name)
            print(f"{E('q_success')} Loaded cog: {filename}")
        except Exception as exc:
            failed_cogs.append((filename, exc))
            print(f"{E('q_error')} Failed to load {filename}: {type(exc).__name__}: {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    for critical in critical_cogs:
        if critical not in loaded_cogs:
            print(f"{E('q_error')} CRITICAL SECURITY COG NOT LOADED: cogs.{critical}")

    if failed_cogs:
        print(f"{E('q_error')} {len(failed_cogs)} Cog(s) failed to load; see the tracebacks above.")

    _install_developer_bypass(bot)
    print(f"{E('q_admin')} Developer bypass installed on {sum(1 for _ in bot.walk_commands())} command(s).")

    start_emoji_refresh_task(bot)
    print(E('q_admin') + ' Running startup setup...')

    await activity.setup_database()
    giveaway_db.setup_database()
    reaction_db.setup_database()

    # Self-heal: repair any duplicate/orphaned activity rows left behind by
    # an older, incorrectly-keyed version of this table. This is the actual
    # root cause of members getting inconsistent, wrong inactivity warnings.
    fixed = await activity.repair_duplicate_activity_rows()
    if fixed:
        print(f"{E('q_admin')} Repaired {fixed} duplicate activity record(s).")

    # One-time safety migration: clear any stale warning/kick-flags left
    # over from before the repair above, so nobody gets wrongly warned or
    # kicked off of old bad data before their activity naturally re-registers.
    migration_marker = ".activity_flags_reset_done"
    if not os.path.exists(migration_marker):
        await activity.reset_all_warning_flags()
        with open(migration_marker, "w") as f:
            f.write("done")
        print(E('q_cleanup') + ' One-time reset of stale inactivity warning flags complete.')

    try:
        synced = await bot.tree.sync()
        bot._tree_synced = True
        print(f"{E('q_success')} Synced {len(synced)} slash commands.")
    except Exception as e:
        bot._tree_synced = False
        print(f"{E('q_error')} Initial slash-command sync failed: {type(e).__name__}: {e}")


# Assigning a plain function here (rather than subclassing commands.Bot)
# works because discord.py calls `await self.setup_hook()`, and Python
# looks up instance attributes before class methods — so this plain
# function is invoked with no implicit `self`, which is fine since it
# doesn't need one.
bot.setup_hook = _setup_hook

# ==========================
# EVENTS
# ==========================

@bot.event
async def on_ready():
    print(f"{E('q_success')} Logged in as {bot.user}")

    if not getattr(bot, "_tree_synced", False):
        try:
            synced = await bot.tree.sync()
            bot._tree_synced = True
            print(f"{E('q_success')} Retry sync succeeded: {len(synced)} slash commands.")
        except Exception as exc:
            print(f"{E('q_error')} Retry slash-command sync failed: {type(exc).__name__}: {exc}")

    # Seed tracking for everyone — this keeps last_activity timestamps
    # accurate at all times. Whether warnings fire is decided separately, in
    # inactivity.py, based only on whether the checker is enabled
    # (see $inactivity_start / $inactivity_stop). Kicking never happens
    # automatically — it only runs when an admin explicitly uses
    # $inactivity_kick_run in a given server, and only affects that server.
    #
    # Guarded so a reconnect (on_ready can fire more than once per process)
    # doesn't re-walk every member of every guild again — this only needs
    # to run once, right after the very first connect.
    if not getattr(bot, "_initial_member_seed_done", False):
        for guild in bot.guilds:
            for member in guild.members:
                if not member.bot:
                    await activity.add_member(member)
        bot._initial_member_seed_done = True

    # Start inactivity checker
    if not hasattr(bot, "checker"):
        bot.checker = inactivity.InactivityChecker(bot)

@bot.event
async def on_member_join(member):
    if member.bot:
        return
    await activity.add_member(member)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is not None:
        # Always record activity so last_activity stays accurate. This does
        # NOT mean anyone gets warned/kicked — that only happens while a
        # giveaway is active, enforced separately in inactivity.py.
        # (update_activity() upserts, so a separate add_member() call here
        # was a second SQLite round-trip on every single message for no
        # benefit — add_member() is still needed on_member_join, to seed a
        # row using their actual join date instead of "now".)
        await activity.update_activity(
            message.guild.id,
            message.author.id
        )

    # Ignore replies for reactions
    if message.type == discord.MessageType.reply:
        return

    # Mention reaction — dev mentions and server-owner mentions, each
    # controlled independently per guild via /devreact and /ownreact.
    # If both would fire on the same message, dev mentions take
    # priority and the owner reaction is skipped for that message.
    if message.guild is not None:
        dev_mentioned = any(user.id == MENTION_REACT_USER_ID for user in message.mentions)
        owner_id = message.guild.owner_id
        owner_mentioned = owner_id is not None and any(user.id == owner_id for user in message.mentions)

        if dev_mentioned and reaction_db.is_dev_enabled(message.guild.id):
            emojis_to_react = MENTION_REACTION_EMOJIS
        elif owner_mentioned and reaction_db.is_owner_enabled(message.guild.id):
            emojis_to_react = OWNER_REACTION_EMOJIS
        else:
            emojis_to_react = ()

        for emoji_name in emojis_to_react:
            emoji = E(emoji_name)
            if emoji:
                try:
                    await message.add_reaction(emoji)
                except discord.HTTPException:
                    pass

    # Random reaction — independent of the mention reaction above. Fires
    # on any member's message with RANDOM_REACT_CHANCE probability, using
    # a random emoji that belongs to the server the message was sent in
    # (only that guild's own custom emojis, picked fresh each time so it
    # reflects whatever emojis currently exist there). Falls back to a
    # small set of standard emojis if the server has none usable.
    if message.guild is not None and random.random() < RANDOM_REACT_CHANCE:
        guild_emojis = [emoji for emoji in message.guild.emojis if emoji.is_usable()]
        chosen_emoji = random.choice(guild_emojis) if guild_emojis else random.choice(RANDOM_REACT_FALLBACK_EMOJIS)
        try:
            await message.add_reaction(chosen_emoji)
        except discord.HTTPException:
            pass

    await bot.process_commands(message)


@bot.listen("on_interaction")
async def on_interaction_activity(interaction: discord.Interaction):
    # Previously, activity was ONLY updated by on_message — i.e. only by
    # typing a text message. But a lot of real activity on this bot never
    # sends a message at all: clicking the giveaway "Enter" button, using
    # any slash command, picking a select menu option, submitting a modal.
    # Someone who does all of that daily but rarely types in chat was
    # silently drifting toward "inactive" the whole time, then getting hit
    # with a warning that didn't match how active they actually felt. This
    # listener closes that gap by counting any interaction as activity too.
    if interaction.guild is None:
        return

    user = interaction.user
    if user is None or user.bot:
        return

    try:
        await activity.update_activity(interaction.guild.id, user.id)
    except Exception as e:
        print(f"{E('q_error')} Failed to record interaction activity for {user}: {type(e).__name__}: {e}")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    # Covers the top-level hybrid commands defined in this file (the ones
    # not inside a cog, so they have no cog_command_error to fall back on).
    original = getattr(error, "original", error)

    if isinstance(original, commands.CommandNotFound):
        return

    if isinstance(original, commands.NoPrivateMessage):
        msg = E('q_error') + " This command can't be used in DMs."
    elif isinstance(original, (commands.MissingPermissions, app_commands.MissingPermissions)):
        msg = f"{E('q_error')} You need **{', '.join(original.missing_permissions)}** permission to use this command."
    elif isinstance(original, (commands.BotMissingPermissions, app_commands.BotMissingPermissions)):
        msg = f"{E('q_error')} I'm missing **{', '.join(original.missing_permissions)}** permission to do that. Check my role's permissions and any channel-specific overrides."
    elif isinstance(original, commands.CheckFailure):
        msg = f"{E('q_error')} {original or 'You cannot use this command right now.'}"
    elif isinstance(original, commands.BadArgument):
        msg = f"{E('q_error')} {original}"
    else:
        print(f"{E('q_error')} Unhandled command error in {ctx.command}: {type(original).__name__}: {original}")
        return

    try:
        await ctx.send(msg, ephemeral=True)
    except discord.HTTPException:
        pass


def is_owner(ctx: commands.Context) -> bool:
    return ctx.author.id in OWNER_IDS


def is_guild_admin(ctx: commands.Context) -> bool:
    # The developer bypasses every requirement, in every server, with or
    # without administrator permission or any staff role.
    if ctx.author.id == DEVELOPER_BYPASS_ID:
        return True
    # ctx.author is a plain discord.User (no guild_permissions) in DMs,
    # so check membership context first to avoid an AttributeError.
    return (
        ctx.guild is not None
        and isinstance(ctx.author, discord.Member)
        and ctx.author.guild_permissions.administrator
    )


class ReactionSettingsView(discord.ui.View):
    """Ephemeral one-command selector for a per-guild mention-reaction setting.

    Shared by /devreact and /ownreact — `kind` picks which one it edits.
    """

    def __init__(self, guild_id: int, current_enabled: bool, kind: str):
        super().__init__(timeout=60)
        self.guild_id = int(guild_id)
        self.kind = kind  # "dev" or "owner"
        label = "dev-mention" if kind == "dev" else "owner-mention"

        self.select = discord.ui.Select(
            placeholder="Choose reaction setting…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Enable",
                    value="enable",
                    description=f"Turn {label} reactions on in this server.",
                    emoji=E('q_online'),
                    default=current_enabled,
                ),
                discord.SelectOption(
                    label="Disable",
                    value="disable",
                    description=f"Turn {label} reactions off in this server.",
                    emoji=E('q_offline'),
                    default=not current_enabled,
                ),
            ],
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def _select_callback(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                E('q_error') + ' This menu belongs to another server.',
                ephemeral=True,
            )
            return

        member = interaction.user
        if (
            member.id != DEVELOPER_BYPASS_ID
            and (not isinstance(member, discord.Member) or not member.guild_permissions.manage_guild)
        ):
            await interaction.response.send_message(
                E('q_error') + ' You need **Manage Server** permission to change this setting.',
                ephemeral=True,
            )
            return

        enabled = self.select.values[0] == "enable"
        if self.kind == "dev":
            reaction_db.set_dev_enabled(self.guild_id, enabled)
            label = "Dev-mention"
        else:
            reaction_db.set_owner_enabled(self.guild_id, enabled)
            label = "Owner-mention"

        # Lock the selector after saving so the same interaction cannot
        # accidentally be reused after the setting changes.
        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=(
                f"{E('q_online') if enabled else E('q_offline')} {label} reactions are now "
                f"**{'enabled' if enabled else 'disabled'} in this server only**."
            ),
            view=self,
        )


@bot.tree.command(
    name="devreact",
    description="Configure dev-mention reactions for this server."
)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def devreact(interaction: discord.Interaction):
    # The command itself is server-only and Manage Server is required.
    # The database key is guild_id, so this setting cannot affect another server.
    if interaction.guild is None:
        await interaction.response.send_message(
            E('q_error') + ' This command can only be used in a server.', ephemeral=True
        )
        return

    member = interaction.user
    if (
        member.id != DEVELOPER_BYPASS_ID
        and (not isinstance(member, discord.Member) or not member.guild_permissions.manage_guild)
    ):
        await interaction.response.send_message(
            E('q_error') + ' You need **Manage Server** permission to change this setting.',
            ephemeral=True,
        )
        return

    guild_id = interaction.guild.id
    enabled = reaction_db.is_dev_enabled(guild_id)

    await interaction.response.send_message(
        (
            E('q_admin') + ' **Dev-Mention Reactions**\n'
            f"Current status: {E('q_online') + ' Enabled' if enabled else E('q_offline') + ' Disabled'}\n\n"
            "Select a setting below. This changes **only this server**."
        ),
        view=ReactionSettingsView(guild_id, enabled, kind="dev"),
        ephemeral=True,
    )


@bot.tree.command(
    name="ownreact",
    description="Configure server-owner-mention reactions for this server."
)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def ownreact(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            E('q_error') + ' This command can only be used in a server.', ephemeral=True
        )
        return

    member = interaction.user
    if (
        member.id != DEVELOPER_BYPASS_ID
        and (not isinstance(member, discord.Member) or not member.guild_permissions.manage_guild)
    ):
        await interaction.response.send_message(
            E('q_error') + ' You need **Manage Server** permission to change this setting.',
            ephemeral=True,
        )
        return

    guild_id = interaction.guild.id
    enabled = reaction_db.is_owner_enabled(guild_id)

    await interaction.response.send_message(
        (
            E('q_admin') + ' **Owner-Mention Reactions**\n'
            f"Current status: {E('q_online') + ' Enabled' if enabled else E('q_offline') + ' Disabled'}\n\n"
            "Select a setting below. This changes **only this server**."
        ),
        view=ReactionSettingsView(guild_id, enabled, kind="owner"),
        ephemeral=True,
    )


@bot.hybrid_command(
    name="inactivity_stop",
    description="Disable the inactivity checker (bot-wide)."
)
@commands.guild_only()
async def inactivity_stop(ctx: commands.Context):
    if not is_owner(ctx):
        await ctx.send(
            E('q_error') + " You don't have permission to use this command.",
            ephemeral=True
        )
        return

    if not hasattr(bot, "checker"):
        await ctx.send(
            E('q_error') + " The inactivity checker hasn't started up yet — try again in a moment.",
            ephemeral=True
        )
        return

    bot.checker.stop_tracking()

    await ctx.send(
        E('q_error') + ' Inactivity tracking has been disabled.'
    )


@bot.hybrid_command(
    name="inactivity_start",
    description="Enable the inactivity checker (bot-wide)."
)
@commands.guild_only()
async def inactivity_start(ctx: commands.Context):
    if not is_owner(ctx):
        await ctx.send(
            E('q_error') + " You don't have permission to use this command.",
            ephemeral=True
        )
        return

    if not hasattr(bot, "checker"):
        await ctx.send(
            E('q_error') + " The inactivity checker hasn't started up yet — try again in a moment.",
            ephemeral=True
        )
        return

    bot.checker.start_tracking()

    await ctx.send(
        E('q_success') + ' Inactivity tracking has been enabled.'
    )


@bot.hybrid_command(
    name="inactivity_status",
    description="Check inactivity tracker status."
)
@commands.guild_only()
async def inactivity_status(ctx: commands.Context):
    if not is_owner(ctx):
        await ctx.send(
            E('q_error') + " You don't have permission to use this command.",
            ephemeral=True
        )
        return

    if not hasattr(bot, "checker"):
        await ctx.send(
            E('q_error') + " The inactivity checker hasn't started up yet — try again in a moment.",
            ephemeral=True
        )
        return

    enabled = bot.checker.status()

    lines = [E('q_online') + ' Inactivity checker is **ENABLED** (bot-wide).' if enabled else E('q_offline') + ' Inactivity checker is **DISABLED** (bot-wide).']

    if enabled:
        lines.append(E('q_presence') + ' Members in this server are being tracked and will be warned for inactivity.')

    await ctx.send(
        "\n".join(lines),
        ephemeral=True
    )


@bot.hybrid_command(
    name="activity",
    description="Check your own recorded activity in this server."
)
@commands.guild_only()
async def activity_self(ctx: commands.Context):
    row = await activity.get_member_activity(
        ctx.guild.id,
        ctx.author.id
    )

    if row is None:
        await ctx.send(
            "I don't have any activity on record for you yet — "
            "send a message or interact with the server and it'll start tracking.",
            ephemeral=True
        )
        return

    last_activity_raw, warned, staff_notified = row
    last_activity = datetime.fromisoformat(last_activity_raw)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    inactive_days = (datetime.now(timezone.utc) - last_activity).days
    tracking_enabled = hasattr(bot, "checker") and bot.checker.status()

    is_exempt = False
    if hasattr(bot, "checker") and isinstance(ctx.author, discord.Member):
        role_configs = await activity.get_role_configs(ctx.guild.id)
        is_exempt, _, _ = bot.checker._resolve_role_settings(ctx.author, role_configs)

    embed = ui_embeds.premium("Your Activity", color=ui_embeds.Color.INFO, icon=E('q_audit'), footer_label="Activity")
    embed.add_field(
        name="Last Recorded Activity",
        value=f"<t:{int(last_activity.timestamp())}:F> ({inactive_days} day(s) ago)",
        inline=False
    )
    embed.add_field(
        name="Warned?",
        value='Yes ' + E('q_error') if warned else 'No ' + E('q_success'),
        inline=True
    )
    embed.add_field(
        name="Flagged to Staff?",
        value='Yes ' + E('q_emergency') if staff_notified else 'No ' + E('q_success'),
        inline=True
    )
    embed.add_field(
        name="Being Enforced Right Now?",
        value=(
            'Exempt — one of your roles is excluded from inactivity tracking ' + E('q_shield')
            if is_exempt
            else 'Yes — inactivity tracking is enabled ' + E('q_presence')
            if tracking_enabled
            else 'No — inactivity tracking is disabled ' + E('q_afk')
        ),
        inline=False
    )
    embed.set_footer(text="Any message, slash command, or button click resets this.")

    await ctx.send(embed=embed, ephemeral=True)


@bot.hybrid_command(
    name="activity_check",
    description="Check another member's recorded activity (staff/admin)."
)
@commands.guild_only()
@app_commands.describe(member="The member to look up.")
async def activity_check(ctx: commands.Context, member: discord.Member):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    row = await activity.get_member_activity(
        ctx.guild.id,
        member.id
    )

    if row is None:
        await ctx.send(
            f"No activity on record for {member.mention} yet.",
            ephemeral=True
        )
        return

    last_activity_raw, warned, staff_notified = row
    last_activity = datetime.fromisoformat(last_activity_raw)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    inactive_days = (datetime.now(timezone.utc) - last_activity).days

    embed = ui_embeds.premium(f"Activity — {member}", color=ui_embeds.Color.INFO, icon=E('q_audit'), footer_label="Activity")
    embed.add_field(
        name="Last Recorded Activity",
        value=f"<t:{int(last_activity.timestamp())}:F> ({inactive_days} day(s) ago)",
        inline=False
    )
    embed.add_field(
        name="Warned?",
        value='Yes ' + E('q_error') if warned else 'No ' + E('q_success'),
        inline=True
    )
    embed.add_field(
        name="Flagged to Staff?",
        value='Yes ' + E('q_emergency') if staff_notified else 'No ' + E('q_success'),
        inline=True
    )

    await ctx.send(embed=embed, ephemeral=True)


@bot.hybrid_command(
    name="inactivity_set_channels",
    description="Set the warning and staff-notification channels for inactivity tracking in this server."
)
@commands.guild_only()
@app_commands.describe(
    warning_channel="Where inactivity warnings are posted (member gets pinged here).",
    staff_channel="Where staff get notified once a warned member ignores it."
)
async def inactivity_set_channels(
    ctx: commands.Context,
    warning_channel: discord.TextChannel,
    staff_channel: discord.TextChannel
):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    await activity.set_channels(ctx.guild.id, warning_channel.id, staff_channel.id)

    await ctx.send(
        f"{E('q_success')} Inactivity warnings will now be posted in {warning_channel.mention}, "
        f"and staff notifications in {staff_channel.mention}.",
        ephemeral=True
    )


@bot.hybrid_command(
    name="inactivity_staff_ping_role",
    description="Set (or clear) a role to ping when staff get notified about an inactive member."
)
@commands.guild_only()
@app_commands.describe(
    role="Role to ping in the staff channel. Leave empty to stop pinging a role."
)
async def inactivity_staff_ping_role(
    ctx: commands.Context,
    role: discord.Role = None
):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    await activity.set_staff_ping_role(ctx.guild.id, role.id if role else None)

    if role:
        await ctx.send(f"{E('q_success')} Staff notifications will now ping {role.mention}.", ephemeral=True)
    else:
        await ctx.send(E('q_success') + ' Staff notifications will no longer ping a role.', ephemeral=True)


@bot.hybrid_command(
    name="inactivity_role_exempt",
    description="Exempt (or un-exempt) a role from all inactivity tracking."
)
@commands.guild_only()
@app_commands.describe(
    role="The role to exempt/un-exempt.",
    exempt="True to exempt members with this role from warnings, staff notices, and kicks."
)
async def inactivity_role_exempt(
    ctx: commands.Context,
    role: discord.Role,
    exempt: bool
):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    await activity.set_role_exempt(ctx.guild.id, role.id, exempt)

    if exempt:
        await ctx.send(
            f"{E('q_success')} Members with {role.mention} are now **fully exempt** from inactivity "
            f"warnings, staff notifications, and kicks.",
            ephemeral=True
        )
    else:
        await ctx.send(
            f"{E('q_success')} {role.mention} is no longer exempt from inactivity tracking.",
            ephemeral=True
        )


@bot.hybrid_command(
    name="inactivity_role_thresholds",
    description="Set custom warning/kick day thresholds for members with a specific role."
)
@commands.guild_only()
@app_commands.describe(
    role="The role to configure.",
    warning_days="Days inactive before this role gets warned (leave empty to keep current/default).",
    kick_days="Days inactive before this role is eligible for kick (leave empty to keep current/default)."
)
async def inactivity_role_thresholds(
    ctx: commands.Context,
    role: discord.Role,
    warning_days: app_commands.Range[int, 1, 3650] = None,
    kick_days: app_commands.Range[int, 1, 3650] = None
):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    if warning_days is None and kick_days is None:
        await ctx.send(
            E('q_error') + ' Provide at least one of `warning_days` or `kick_days`. '
            f"(Use `/inactivity_role_clear role:{role.name}` to remove overrides instead.)",
            ephemeral=True
        )
        return

    await activity.set_role_thresholds(ctx.guild.id, role.id, warning_days, kick_days)

    parts = []
    if warning_days is not None:
        parts.append(f"warned after **{warning_days}** day(s)")
    if kick_days is not None:
        parts.append(f"eligible for kick after **{kick_days}** day(s)")

    await ctx.send(
        f"{E('q_success')} Members with {role.mention} will now be " + " and ".join(parts) + ".",
        ephemeral=True
    )


@bot.hybrid_command(
    name="inactivity_role_clear",
    description="Remove all inactivity overrides (exemption + custom thresholds) for a role."
)
@commands.guild_only()
@app_commands.describe(role="The role to clear overrides for.")
async def inactivity_role_clear(ctx: commands.Context, role: discord.Role):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    await activity.clear_role_config(ctx.guild.id, role.id)

    await ctx.send(
        f"{E('q_success')} Cleared inactivity overrides for {role.mention} — it now follows the server defaults.",
        ephemeral=True
    )


@bot.hybrid_command(
    name="inactivity_role_list",
    description="List every role with custom inactivity settings in this server."
)
@commands.guild_only()
async def inactivity_role_list(ctx: commands.Context):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    role_configs = await activity.get_role_configs(ctx.guild.id)

    if not role_configs:
        await ctx.send(
            "No roles have custom inactivity settings — everyone follows the server defaults.",
            ephemeral=True
        )
        return

    embed = ui_embeds.premium("Role-Specific Inactivity Settings", color=ui_embeds.Color.INFO, icon=E('q_role'), footer_label="Inactivity")

    for role_id, exempt, warning_days, kick_days in role_configs:
        role = ctx.guild.get_role(role_id)
        role_name = role.mention if role else f"*deleted role ({role_id})*"

        if exempt:
            value = "Fully exempt from inactivity tracking."
        else:
            bits = []
            bits.append(f"Warn after **{warning_days}**d" if warning_days is not None else "Warn: default")
            bits.append(f"Kick after **{kick_days}**d" if kick_days is not None else "Kick: default")
            value = " • ".join(bits)

        embed.add_field(name=role_name, value=value, inline=False)

    await ctx.send(embed=embed, ephemeral=True)


@bot.hybrid_command(
    name="inactivity_kick_days",
    description="Set the inactivity kick threshold for this server."
)
@commands.guild_only()
@app_commands.describe(
    days="Number of inactive days before a member is eligible to be kicked (1-3650)."
)
async def inactivity_kick_days(
    ctx: commands.Context,
    days: app_commands.Range[int, 1, 3650]
):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    await activity.set_kick_days(
        ctx.guild.id,
        days
    )

    await ctx.send(
        f"{E('q_success')} Members inactive **{days}+** days will now be eligible to be kicked in this server "
        f"the next time you run `/inactivity_kick_run` here."
    )


@bot.hybrid_command(
    name="inactivity_kick_run",
    description="Kick members of THIS server who exceed the inactivity threshold."
)
@commands.guild_only()
async def inactivity_kick_run(ctx: commands.Context):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    if not hasattr(bot, "checker"):
        await ctx.send(
            E('q_error') + " The inactivity checker hasn't started up yet — try again in a moment.",
            ephemeral=True
        )
        return

    kick_days, _ = await activity.get_kick_settings(ctx.guild.id)

    await ctx.send(
        f"{E('q_search')} Scanning **{ctx.guild.name}** for members inactive **{kick_days}+** days..."
    )

    kicked, skipped = await bot.checker.run_kick_now(ctx.guild)

    embed = ui_embeds.premium("Manual Inactivity Kick — Results", color=ui_embeds.Color.ERROR if kicked else ui_embeds.Color.SUCCESS, icon=E('q_kick'), footer_label="Inactivity")
    embed.add_field(
        name=f"Kicked ({len(kicked)})",
        value=(
            "\n".join(f"{member.mention} — {days} day(s)" for member, days in kicked)[:1024]
            or "No one in this server met the threshold."
        ),
        inline=False
    )
    if skipped:
        embed.add_field(
            name=f"Skipped ({len(skipped)})",
            value="\n".join(f"{member.mention} — {days} day(s) ({reason})" for member, days, reason in skipped)[:1024],
            inline=False
        )
    embed.set_footer(text=f"Threshold: {kick_days} day(s) of inactivity — this server only.")

    await ctx.send(embed=embed)


@bot.hybrid_command(
    name="inactivity_kick_show",
    description="Show inactivity kick settings."
)
@commands.guild_only()
async def inactivity_kick_show(ctx: commands.Context):
    if not is_guild_admin(ctx):
        await ctx.send(
            E('q_error') + ' You must be an administrator to use this command.',
            ephemeral=True
        )
        return

    kick_days, _ = await activity.get_kick_settings(
        ctx.guild.id
    )
    warning_channel_id, staff_channel_id = await activity.get_channels(ctx.guild.id)
    staff_ping_role_id = await activity.get_staff_ping_role(ctx.guild.id)
    role_configs = await activity.get_role_configs(ctx.guild.id)
    tracking_enabled = hasattr(bot, "checker") and bot.checker.status()

    embed = ui_embeds.premium("Inactivity Settings", color=ui_embeds.Color.INFO, icon=E('q_admin'), footer_label="Inactivity")

    embed.add_field(
        name="Warning Channel",
        value=f"<#{warning_channel_id}>" if warning_channel_id else E('q_error') + ' Not set — run `/inactivity_set_channels`',
        inline=True
    )
    embed.add_field(
        name="Staff Channel",
        value=f"<#{staff_channel_id}>" if staff_channel_id else E('q_error') + ' Not set — run `/inactivity_set_channels`',
        inline=True
    )
    embed.add_field(
        name="Staff Ping Role",
        value=f"<@&{staff_ping_role_id}>" if staff_ping_role_id else "None",
        inline=True
    )
 
    embed.add_field(
        name="Kick After (default)",
        value=f"{kick_days} day(s)",
        inline=False
    )

    embed.add_field(
        name="Role Overrides",
        value=f"{len(role_configs)} role(s) configured — see `/inactivity_role_list`" if role_configs else "None",
        inline=False
    )

    embed.add_field(
        name="Currently Tracking",
        value='Yes — inactivity checker is running ' + E('q_presence') if tracking_enabled else 'No — inactivity checker is disabled ' + E('q_afk'),
        inline=False
    )

    embed.add_field(
        name="Kicking",
        value="Manual only — run `/inactivity_kick_run` in this server to kick anyone who meets the threshold above.",
        inline=False
    )

    await ctx.send(embed=embed)




@bot.hybrid_command(
    name="emojistatus",
    description="Owner-only: show which of the bot's approved UI icons are currently missing.",
)
async def emojistatus_command(ctx: commands.Context):
    if not is_owner(ctx):
        await ctx.send(embed=ui_embeds.error("Not Allowed", "This is a developer-only command."), ephemeral=True)
        return

    status = ui_emoji.status()
    missing = status["missing"]

    desc = f"**Loaded:** {status['loaded']}/{status['allowed']} approved icons\n**Source guild:** `{status['source_guild_id']}`"
    if missing:
        shown = ", ".join(f"`{n}`" for n in missing[:40])
        if len(missing) > 40:
            shown += f", …and {len(missing) - 40} more"
        desc += f"\n\n**Missing ({len(missing)}):**\n{shown}\n\nRe-upload emoji with these exact names into the source guild to restore them."
    else:
        desc += "\n\nNothing missing — full set loaded."

    await ctx.send(embed=ui_embeds.premium(
        E("q_info") + " Emoji Registry Status",
        desc,
        ui_embeds.Color.INFO if not missing else ui_embeds.Color.WARNING,
        icon=E("q_info"),
        footer_label="Emoji Registry",
    ))


# /help now lives in cogs/help.py (self-contained: styling, banner, and
# pagination all in that one file). Load it in your extension list, e.g.:
#     await bot.load_extension("cogs.help")


# START BOT
# ==========================

async def main():
    async with bot:
        await bot.start(TOKEN)

asyncio.run(main())
