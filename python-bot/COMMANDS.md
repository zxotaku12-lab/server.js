# Commands — Gogeta's Pet

Auto-generated from the cogs that actually load (`20` extensions). Regenerate with `python scripts/gen_commands.py` after adding a cog.

**Totals:** 56 top-level slash commands (89 including subcommands) · 57 prefix/hybrid commands.

`slash+prefix` = hybrid command (dono tarah se chalta hai).

## Antibetray (1)

| Command | Type | Description |
|---|---|---|
| `antibetray-incidents` | slash+prefix | View recent Anti-Betray incidents. |

## Antinuke (1)

| Command | Type | Description |
|---|---|---|
| `antinuke-incidents` | slash+prefix | View Anti-Nuke incidents. |

## Apply (7)

| Command | Type | Description |
|---|---|---|
| `apply_approval_channel` | slash+prefix | Set or clear the channel where approval announcements are posted. |
| `apply_panel` | slash+prefix | Post the Apply button panel in a channel. |
| `apply_questions` | slash+prefix | Set the questions applicants are asked (up to 5). |
| `apply_settings` | slash+prefix | View the current staff application configuration. |
| `apply_setup` | slash+prefix | Configure the staff application system. |
| `apply_status` | slash+prefix | Check the status of your most recent staff application. |
| `apply_toggle` | slash+prefix | Open or close staff applications. |

## Automod (1)

| Command | Type | Description |
|---|---|---|
| `automod-incidents` | slash+prefix | View recent AutoMod incidents. |

## AutoRole (2)

| Command | Type | Description |
|---|---|---|
| `autorole` | slash+prefix | Set, view, or disable the role automatically given to new members. |
| `autorole_off` | slash+prefix | Disable automatic role assignment for new members. |

## bot.py (root) (29)

| Command | Type | Description |
|---|---|---|
| `antibetray config` | slash | Open the Anti-Betray control center. |
| `antibetray setup` | slash | Run Anti-Betray preflight and deploy the trust guard. |
| `antibetray whitelist` | slash | Add or remove an explicitly watched user or role. |
| `antinuke config` | slash | Open the Anti-Nuke control center without running setup. |
| `antinuke disable` | slash | Disable the Anti-Nuke firewall. |
| `antinuke setup` | slash | Run the animated Anti-Nuke deployment wizard. |
| `antinuke whitelist` | slash | Manage Anti-Nuke trust exemptions. |
| `automod config` | slash | Open the AutoMod control center without running setup. |
| `automod disable` | slash | Disable AutoMod. |
| `automod links` | slash | Set the link policy: block every link, only configured classes, or allow all. |
| `automod setup` | slash | Run the animated AutoMod deployment wizard. |
| `automod whitelist` | slash | Trust a user, role, or channel. |
| `automod words` | slash | Manage blocked words and phrases. |
| `emojivault status` | slash | Configure the server that receives copied-in emoji. |
| `invites check` | slash | Show a member's invite stats. |
| `invites leaderboard` | slash | Show the top inviters in this server. |
| `invites-config add` | slash | Manually grant bonus invites to a member. |
| `invites-config disable` | slash | Disable invite tracking for this server. |
| `invites-config enable` | slash | Enable invite tracking for this server. |
| `invites-config fake-age` | slash | Set how new (in days) an account must be to get flagged as fake. |
| `invites-config logchannel` | slash | Set the channel invite tracking posts join/leave logs to. |
| `invites-config remove` | slash | Remove bonus invites from a member. |
| `invites-config reset` | slash | Wipe a member's invite stats. |
| `lockconfig status` | slash | Configure the hierarchy cutoff used by /lock. |
| `antibetray` | slash group | Gogeta privileged-identity monitor |
| `antinuke` | slash group | Gogeta Anti-Nuke security control center |
| `automod` | slash group | Gogeta AutoMod control center |
| `invites` | slash group | Check invite stats. |
| `invites-config` | slash group | Configure invite tracking. |

## DMAnnounce (1)

| Command | Type | Description |
|---|---|---|
| `dmannounce` | slash+prefix | Send a confirmed announcement by DM to members of this server. |

## EmbedBuilder (1)

| Command | Type | Description |
|---|---|---|
| `embed` | slash+prefix | Build and send a custom embed with an interactive panel. |

## EmojiVault (3)

| Command | Type | Description |
|---|---|---|
| `emojivault` | prefix | Configure the server that receives copied-in emoji. |
| `emojivault clear` | slash+prefix | Unset the emoji vault (must be run in the current vault server). |
| `emojivault set` | slash+prefix | Make this server the emoji vault target. |

## GhostPing (1)

| Command | Type | Description |
|---|---|---|
| `ghostping` | slash+prefix | Ghost-ping new members into the channels you pick. Leave empty to see the current list. |

## Giveaway (6)

| Command | Type | Description |
|---|---|---|
| `gbonusrole` | prefix | Manage giveaway bonus entry roles. |
| `gstart` | prefix |  |
| `gbonusrole add` | slash+prefix | Give a role bonus giveaway entries. |
| `gbonusrole list` | slash+prefix | View all giveaway bonus roles. |
| `gbonusrole remove` | slash+prefix | Remove a giveaway bonus role. |
| `greroll` | slash+prefix | Reroll a giveaway winner. |

## GogetasPet (1)

| Command | Type | Description |
|---|---|---|
| `ai` | slash+prefix | Talk to Gogeta's Pet. |

## Help (1)

| Command | Type | Description |
|---|---|---|
| `help` | slash+prefix | List every command Gogeta offers, grouped by category. |

## Moderation (23)

| Command | Type | Description |
|---|---|---|
| `lockconfig` | prefix | Configure the hierarchy cutoff used by /lock. |
| `addrole` | slash+prefix | Add a role to a member. |
| `ban` | slash+prefix | Ban a member from the server. |
| `clearwarnings` | slash+prefix | Clear all warnings for a member. |
| `delwarn` | slash+prefix | Remove a single warning by its ID. |
| `kick` | slash+prefix | Kick a member from the server. |
| `lock` | slash+prefix | Lock a channel for everyone at or below your configured cutoff role — including Administrators. |
| `lockconfig set-role` | slash+prefix | Set the role that /lock uses as its cutoff. |
| `modlogs` | slash+prefix | View a member's recent moderation history. |
| `nickname` | slash+prefix | Change a member's nickname. |
| `prefix` | slash+prefix | View or change this server's command prefix. |
| `purge` | slash+prefix | Bulk delete messages in this channel. |
| `removerole` | slash+prefix | Remove a role from a member. |
| `roleall` | slash+prefix | Give a role to every member who has another specific role. |
| `rolerall` | slash+prefix | Remove a role from every member in the server. |
| `slowmode` | slash+prefix | Set this channel's slowmode delay. |
| `softban` | slash+prefix | Ban then immediately unban a member, purging their recent messages. |
| `timeout` | slash+prefix | Timeout (mute) a member for a duration. |
| `unban` | slash+prefix | Unban a user by their ID. |
| `unlock` | slash+prefix | Unlock this (or a given) channel, restoring exactly what /lock changed. |
| `untimeout` | slash+prefix | Remove a member's timeout. |
| `warn` | slash+prefix | Warn a member. |
| `warnings` | slash+prefix | View a member's warnings. |

## SecurityDashboard (3)

| Command | Type | Description |
|---|---|---|
| `security-center` | slash+prefix | Open Gogeta's premium Discord security command center. |
| `security-check` | slash+prefix | Run a permissions and hierarchy diagnostic. |
| `security-status` | slash+prefix | Show a compact live security status. |

## ServerLogs (3)

| Command | Type | Description |
|---|---|---|
| `log` | slash | Set one channel for comprehensive premium server logging |
| `logoff` | slash | Disable centralized server logging |
| `logstatus` | slash | View the current logging status |

## Tickets (5)

| Command | Type | Description |
|---|---|---|
| `ticket` | prefix | Configure and deploy the ticket system. |
| `close` | slash+prefix | Close the current ticket. |
| `ticket panel` | slash+prefix | Post the 3-button ticket panel (Support / Reward / Staff Application) in a channel. |
| `ticket settings` | slash+prefix | View the current ticket configuration. |
| `ticket setup` | slash+prefix | Configure the category and staff role for one ticket type. |

