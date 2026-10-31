# Credits: gogeta_gg
"""
Shared giveaway logic.

This used to live only inside cogs/giveaway.py's Giveaway cog
(build_weighted_entries / pick_weighted_winners), which meant only the
manual /greroll command could ever call it. The automatic end-of-giveaway
task in giveaway_tasks.py had no way to reach a Cog method on a different
cog, so it never picked a winner at all when a giveaway's timer ran out —
it just fetched the message and marked the row ended in the DB. Pulling
the logic out here lets both call the exact same code.
"""

import random

import discord

from . import giveaway_db


def build_weighted_entries(guild: discord.Guild, giveaway) -> list[int]:
    weighted = []

    entries = giveaway_db.get_entries(giveaway["message_id"])

    for user_id in entries:
        member = guild.get_member(user_id)

        if member is None:
            continue

        multiplier = giveaway_db.get_bonus_entries(
            guild.id,
            [role.id for role in member.roles],
        )

        weighted.extend([user_id] * multiplier)

    return weighted


def pick_weighted_winners(guild: discord.Guild, giveaway) -> list[int]:
    weighted = build_weighted_entries(guild, giveaway)

    if not weighted:
        return []

    winners = []

    while weighted and len(winners) < giveaway["winners"]:
        winner = random.choice(weighted)

        if winner not in winners:
            winners.append(winner)

        weighted = [user for user in weighted if user != winner]

    return winners
