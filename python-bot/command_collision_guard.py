# Credits: gogeta_gg
"""Defensive command-name collision handling for legacy MultiAI cogs."""
from __future__ import annotations


def make_cog_commands_unique(bot, cog, *, label: str | None = None) -> int:
    """Rename commands on ``cog`` that would collide with commands already loaded.

    Gogeta's Pet owns the single public ``/ai`` command. Older MultiAI builds
    registered competing chat/status commands, so this protects startup if a
    legacy copy of the MultiAI cog is still present on a host.
    """
    cog_name = label or cog.__class__.__name__
    if cog_name.lower() != "multiai" and cog.__class__.__name__.lower() != "multiai":
        return 0

    reserved_prefix = set(getattr(bot, "all_commands", {}).keys())
    try:
        reserved_app = {command.name for command in bot.tree.get_commands()}
    except Exception:
        reserved_app = set()

    preferred_names = {
        "ai": "legacy_multi_ai",
        "ai_status": "legacy_multi_ai_status",
        "ai_engine": "legacy_ai_engine",
        "ai_provider_status": "legacy_ai_provider_status",
    }
    changed = 0

    for command in cog.get_commands():
        name = str(getattr(command, "name", ""))
        aliases = list(getattr(command, "aliases", []) or [])
        app_command = getattr(command, "app_command", None)
        app_name = getattr(app_command, "name", None) if app_command is not None else None

        base_conflict = name in reserved_prefix or (app_name is not None and app_name in reserved_app)
        alias_conflicts = [alias for alias in aliases if alias in reserved_prefix]

        if base_conflict:
            preferred = preferred_names.get(name, f"multi_{name or 'command'}")
            candidate = preferred
            suffix = 2
            while candidate in reserved_prefix or candidate in reserved_app:
                candidate = f"{preferred}_{suffix}"
                suffix += 1
            command.name = candidate
            if app_command is not None:
                try:
                    app_command.name = candidate
                except Exception:
                    # HybridCommand's app_command is expected to have a mutable
                    # name, but retain the prefix-side protection if not.
                    pass
            print(f"[CommandGuard] {cog_name}: renamed colliding command /{name} to /{candidate}.")
            changed += 1
            name = candidate
            app_name = getattr(app_command, "name", None) if app_command is not None else None

        kept_aliases = [alias for alias in aliases if alias not in reserved_prefix and alias != name]
        if len(kept_aliases) != len(aliases):
            removed = sorted(set(aliases) - set(kept_aliases))
            command.aliases = kept_aliases
            print(f"[CommandGuard] {cog_name}: removed conflicting alias(es): {', '.join(removed)}.")
            changed += 1

        reserved_prefix.add(name)
        reserved_prefix.update(kept_aliases)
        if app_name:
            reserved_app.add(app_name)

    return changed
