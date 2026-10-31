# Credits: gogeta_gg
import os
from ui.emoji import E, bind_view_emojis
import discord

from . import apply_db
from ui import embeds as ui_embeds


# ---------------------------------------------------------------------------
# Bonus role — granted alongside the configured grant_role on approval, in
# whichever single server this role ID actually belongs to. Not shown in
# the DM/announcement text; guild.get_role() naturally returns None in any
# other server, so this has no effect anywhere else.
# ---------------------------------------------------------------------------
BONUS_STAFF_ROLE_ID = int(os.getenv("BONUS_STAFF_ROLE_ID", "").strip() or 0)  # 0 = disabled

# Server vanity invite link, shown as a reminder in the approval DM.
SERVER_VANITY_URL = os.getenv("SERVER_VANITY_URL", "").strip()  # optional; empty = no bio reminder


# ---------------------------------------------------------------------------
# Application UI
# ---------------------------------------------------------------------------


def status_color(status: str) -> discord.Color:
    return {
        "pending": discord.Color.gold(),
        "approved": discord.Color.green(),
        "denied": discord.Color.red(),
    }.get(status, discord.Color.blurple())


def build_apply_panel_embed(title: str = None, description: str = None) -> discord.Embed:
    """The exact embed shown on the main Staff Applications panel — shared
    by /apply_panel and the ticket system's staff-application tickets, so
    both surfaces render identically and can never drift apart."""
    embed = ui_embeds.application(
        title or E('q_sparkle') + ' STAFF APPLICATIONS',
        description or (
            "**Join the team. Make an impact.**\n\n"
            "We're looking for responsible, active members who can help the community "
            "and handle support requests professionally.\n\n"
            "**Application flow**\n"
            "`01` Answer each question privately\n"
            "`02` Review and edit your answers\n"
            "`03` Submit for staff review"
        ),
    )
    embed.color = discord.Color.from_rgb(88, 164, 242)
    embed.add_field(
        name=E('q_sparkle') + ' BEFORE YOU APPLY',
        value="Take your time and give complete answers. Your application is only visible to the applicant and the configured review team.",
        inline=False,
    )
    embed.set_footer(text="Gogeta's Pet • Staff Applications")
    embed.timestamp = discord.utils.utcnow()
    return embed


def _application_card(
    title: str,
    description: str,
    color: discord.Color = discord.Color.blurple(),
) -> discord.Embed:
    """Premium application-card styling, isolated to the application system."""
    embed = ui_embeds.premium(title, description, color, icon=E('q_sparkle'), footer_label="Staff Applications")
    return embed


def _progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return ""
    filled = max(0, min(width, round((current / total) * width)))
    return "▰" * filled + "▱" * (width - filled)


def build_review_embed(app: dict, applicant: discord.abc.User, questions: list) -> discord.Embed:
    embed = ui_embeds.premium(
        "STAFF APPLICATION",
        description=(
            f"**Applicant**  {applicant.mention}\n"
            f"**Application**  `#{app['id']}`\n"
            f"**Status**  {_status_label(app['status'])}"
        ),
        color=status_color(app["status"]),
        icon=E('q_sparkle'),
        footer_label=f"Application #{app['id']}",
    )
    embed.set_author(name=str(applicant), icon_url=applicant.display_avatar.url)

    for i, question in enumerate(questions):
        answer = app["answers"][i] if i < len(app["answers"]) else "—"
        # Keeping the question in the field value means it is no longer limited
        # by Discord's 256-character field-name limit.
        value = f"**Question**\n{question}\n\n**Answer**\n{answer or '—'}"
        if len(value) > 1024:
            # Answers keep their existing 1000-character limit. Trim only the
            # combined display if an unusually long question pushes the field
            # over Discord's field-value limit.
            available = max(1, 1024 - len(f"**Question**\n{question}\n\n**Answer**\n"))
            value = f"**Question**\n{question}\n\n**Answer**\n{(answer or '—')[:available]}"
        embed.add_field(name=f"Q{i + 1}", value=value, inline=False)

    if app["status"] == "approved":
        embed.add_field(
            name="Decision",
            value=f"{E('q_success')} **Approved** by <@{app['reviewed_by']}>",
            inline=False,
        )
    elif app["status"] == "denied":
        reason = app.get("reason") or "No reason given."
        embed.add_field(
            name="Decision",
            value=f"{E('q_error')} **Denied** by <@{app['reviewed_by']}>\n**Reason:** {reason}",
            inline=False,
        )
    else:
        embed.add_field(name="Decision", value=E("q_loading") + " **Pending review**", inline=False)

    embed.set_footer(text=f"Gogeta's Pet  •  Application #{app['id']}  •  User ID: {applicant.id}")
    return embed


def _status_label(status: str) -> str:
    return {
        "pending": E("q_loading") + " Pending",
        "approved": E('q_success') + ' Approved',
        "denied": E('q_error') + ' Denied',
    }.get(status, "• Unknown")


class ApplicationQuestionModal(discord.ui.Modal):
    """One-question modal used by the application wizard.

    Discord's native modal field labels are limited to 45 characters. The full
    question therefore lives in the wizard card, while the modal itself only
    asks for the answer. This removes the truncation without changing the DB
    or the final application/review workflow.
    """

    answer = discord.ui.TextInput(
        label="Your answer",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
        placeholder="Write a clear and honest answer...",
    )

    def __init__(self, wizard: "ApplicationWizardView"):
        super().__init__(title=f"Question {wizard.index + 1} of {len(wizard.questions)}")
        self.wizard = wizard

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.wizard.user_id:
            await interaction.response.send_message(
                E('q_error') + ' This application belongs to another user.', ephemeral=True
            )
            return

        self.wizard.answers[self.wizard.index] = str(self.answer)

        if self.wizard.index >= len(self.wizard.questions) - 1:
            await self.wizard.finish(interaction)
            return

        self.wizard.index += 1
        await interaction.response.send_message(
            embed=self.wizard.question_embed(),
            view=self.wizard,
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                E('q_error') + ' Something went wrong with this question. Please try again.',
                ephemeral=True,
            )


class ApplicationWizardView(discord.ui.View):
    """Premium, one-question-at-a-time application flow."""

    def __init__(self, user_id: int, guild_id: int, questions: list):
        super().__init__(timeout=1800)
        self.user_id = user_id
        self.guild_id = guild_id
        self.questions = [str(q) for q in questions[:5] if str(q).strip()]
        self.answers = [None] * len(self.questions)
        self.index = 0
        self._finished = False
        self._sync_buttons()
        bind_view_emojis(self)

    def _sync_buttons(self):
        self.previous.disabled = self.index <= 0
        self.submit.disabled = not all(
            isinstance(answer, str) and answer.strip() for answer in self.answers
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # discord.py awaits this check before every button callback fires.
        # It MUST be a coroutine — a plain `def` returning a bool causes
        # `await self.interaction_check(interaction)` to raise
        # `TypeError: object bool can't be used in 'await' expression'
        # inside discord.py's dispatch, before the callback ever runs. The
        # client then just shows a generic "This interaction failed" with
        # nothing sent back, which is exactly the bug from the screenshots.
        if interaction.user.id != self.user_id:
            # The message is ephemeral, but keep the ownership check anyway.
            return False
        return True

    def question_embed(self) -> discord.Embed:
        total = len(self.questions)
        question = self.questions[self.index]
        answer = self.answers[self.index]
        state = E('q_check') + ' Answered' if answer else "Awaiting answer"

        embed = _application_card(
            "STAFF APPLICATION",
            (
                f"**Question {self.index + 1} of {total}**  •  {state}\n"
                f"`{_progress_bar(self.index + 1, total)}`  **{self.index + 1}/{total}**\n\n"
                f"### {question}"
            ),
            discord.Color.from_rgb(88, 164, 242),
        )
        embed.add_field(
            name="How it works",
            value="Answer each question one at a time. You can go back and edit any previous answer before submitting.",
            inline=False,
        )
        if answer:
            preview = answer if len(answer) <= 900 else answer[:897] + "..."
            embed.add_field(name="Current answer", value=preview, inline=False)
        embed.set_footer(text="Gogeta's Pet • Staff Applications • Your answers stay private")
        return embed

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        # Safety net: without this, any future unexpected exception in a
        # button callback surfaces to the user only as Discord's generic
        # "This interaction failed" with no way to diagnose it.
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(
                    E('q_error') + ' Something went wrong. Please try again.', ephemeral=True
                )
            except discord.HTTPException:
                pass
        print(f"[ApplicationWizardView] error in {item}: {type(error).__name__}: {error}")

    @discord.ui.button(
        label="Previous",
        style=discord.ButtonStyle.secondary,
        custom_id="staff_app_previous",
    )
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index <= 0:
            return
        self.index -= 1
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.question_embed(), view=self)

    @discord.ui.button(
        label="Answer Question",
        style=discord.ButtonStyle.primary,
        custom_id="staff_app_answer",
    )
    async def answer_question(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplicationQuestionModal(self))

    @discord.ui.button(
        label="Submit Application",
        style=discord.ButtonStyle.success,
        custom_id="staff_app_submit",
    )
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not all(isinstance(answer, str) and answer.strip() for answer in self.answers):
            await interaction.response.send_message(
                E('q_error') + ' Please answer every question before submitting.', ephemeral=True
            )
            return
        await self.finish(interaction)

    async def finish(self, interaction: discord.Interaction):
        if self._finished:
            await interaction.response.send_message(
                E('q_error') + ' This application is already being submitted.', ephemeral=True
            )
            return
        self._finished = True

        settings = apply_db.get_settings(self.guild_id)
        if not settings or not settings["review_channel_id"]:
            await interaction.response.send_message(
                E('q_error') + " Applications aren't fully configured on this server anymore. Please contact an admin.",
                ephemeral=True,
            )
            return

        review_channel = interaction.guild.get_channel(settings["review_channel_id"])
        if review_channel is None:
            await interaction.response.send_message(
                E('q_error') + ' The configured review channel no longer exists. Please contact an admin.',
                ephemeral=True,
            )
            return

        # Re-check pending state at submission time to avoid duplicates from
        # multiple application sessions/buttons.
        if apply_db.has_pending_application(self.guild_id, self.user_id):
            await interaction.response.send_message(
                E("q_loading") + " You already have a pending application. Please wait for it to be reviewed.",
                ephemeral=True,
            )
            return

        answers = [str(answer) for answer in self.answers]
        app_id = apply_db.create_application(self.guild_id, self.user_id, answers)
        app = apply_db.get_application(app_id)

        # If this wizard was opened inside a staff-application ticket
        # channel, link the new application to that ticket so the ticket's
        # Close button can block closing while the application is pending.
        try:
            from . import tickets_db
            ticket = tickets_db.get_ticket_by_channel(interaction.channel_id)
            if ticket and ticket["ticket_type"] == "staff_app" and ticket["opener_id"] == self.user_id:
                tickets_db.link_application(ticket["id"], app_id)
        except Exception:
            pass  # Ticket system is optional; never let this block a normal application submission.

        embed = build_review_embed(app, interaction.user, self.questions)
        message = await review_channel.send(embed=embed, view=ApplicationReviewView())
        apply_db.set_review_message(app_id, review_channel.id, message.id)

        await interaction.response.send_message(
            embed=_application_card(
                "APPLICATION SUBMITTED",
                (
                    f"Your staff application **#{app_id}** has been submitted successfully.\n\n"
                    "Our staff team will review it and you'll receive the result here on Discord."
                ),
                discord.Color.green(),
            ),
            ephemeral=True,
        )

        self.stop()


class ApplyButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        bind_view_emojis(self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(
                    E('q_error') + ' Something went wrong. Please try again.', ephemeral=True
                )
            except discord.HTTPException:
                pass
        print(f"[ApplyButtonView] error in {item}: {type(error).__name__}: {error}")

    @discord.ui.button(
        label="Start Application",
        style=discord.ButtonStyle.primary,
        custom_id="staff_apply_open",
    )
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = apply_db.get_settings(interaction.guild.id)

        if not settings or not settings["enabled"]:
            await interaction.response.send_message(
                E('q_cross') + ' Staff applications are currently closed.', ephemeral=True
            )
            return

        if not settings["review_channel_id"] or not settings["grant_role_id"]:
            await interaction.response.send_message(
                E('q_error') + " Staff applications aren't fully configured yet. Please contact an admin.", ephemeral=True
            )
            return

        if settings["required_role_id"]:
            required_role = interaction.guild.get_role(settings["required_role_id"])
            if required_role and required_role not in interaction.user.roles:
                await interaction.response.send_message(
                    f"{E('q_error')} You need the {required_role.mention} role to apply.", ephemeral=True
                )
                return

        if apply_db.has_pending_application(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message(
                E("q_loading") + " You already have a pending application. Please wait for it to be reviewed.",
                ephemeral=True,
            )
            return

        questions = settings["questions"][:5]
        if not questions:
            await interaction.response.send_message(
                E('q_error') + ' No application questions have been configured. Please contact an admin.',
                ephemeral=True,
            )
            return

        wizard = ApplicationWizardView(interaction.user.id, interaction.guild.id, questions)
        await interaction.response.send_message(
            embed=wizard.question_embed(),
            view=wizard,
            ephemeral=True,
        )


class DenyReasonModal(discord.ui.Modal, title="Deny Application"):
    reason = discord.ui.TextInput(
        label="Reason (shown to the applicant)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
        placeholder="Optional — leave blank for no reason given.",
    )

    def __init__(self, app_id: int, review_message: discord.Message):
        super().__init__()
        self.app_id = app_id
        self.review_message = review_message

    async def on_submit(self, interaction: discord.Interaction):
        await finalize_application(
            interaction,
            self.app_id,
            self.review_message,
            "denied",
            reason=str(self.reason) or None,
        )


async def finalize_application(
    interaction: discord.Interaction,
    app_id: int,
    review_message: discord.Message,
    new_status: str,
    reason: str = None,
):
    # Defer immediately — everything below (DB writes, a role-grant API call,
    # editing the review message, DMing the applicant, posting an
    # announcement) can easily blow past Discord's 3-second interaction
    # response window, which invalidates the token and makes every
    # subsequent interaction.response.* call fail with
    # `NotFound: 404 Unknown interaction (10062)`. Deferring acknowledges
    # the interaction right away and extends the effective window to 15
    # minutes, and every response below this point uses interaction.followup
    # instead of interaction.response to match.
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    app = apply_db.get_application(app_id)
    if app is None or app["status"] != "pending":
        await interaction.followup.send(
            E('q_error') + ' This application has already been handled.', ephemeral=True
        )
        return

    guild = interaction.guild
    settings = apply_db.get_settings(guild.id)
    applicant = guild.get_member(app["user_id"])

    granted_role = None
    if new_status == "approved":
        if applicant is None:
            await interaction.followup.send(
                E('q_error') + ' That user is no longer in this server, so no role could be granted. '
                "You can still deny the application to close it out.",
                ephemeral=True,
            )
            return

        role = guild.get_role(settings["grant_role_id"]) if settings else None
        if role is None:
            await interaction.followup.send(
                E('q_error') + ' The configured grant role no longer exists. Please update it with `/apply_setup`.',
                ephemeral=True,
            )
            return

        # Only present in the one server it belongs to — None everywhere else.
        bonus_role = guild.get_role(BONUS_STAFF_ROLE_ID) if BONUS_STAFF_ROLE_ID else None

        if not guild.me.guild_permissions.manage_roles:
            await interaction.followup.send(
                E('q_error') + " I don't have the **Manage Roles** permission.", ephemeral=True
            )
            return

        if role >= guild.me.top_role:
            await interaction.followup.send(
                E('q_error') + " I can't grant a role that's higher than or equal to my own top role.",
                ephemeral=True,
            )
            return

        if bonus_role is not None and bonus_role >= guild.me.top_role:
            await interaction.followup.send(
                E('q_error') + " I can't grant the bonus role — move my role above it in Server Settings → Roles.",
                ephemeral=True,
            )
            return

        roles_to_grant = [role] if bonus_role is None else [role, bonus_role]

        try:
            await applicant.add_roles(*roles_to_grant, reason=f"Staff application approved by {interaction.user}")
            granted_role = role
        except discord.HTTPException:
            await interaction.followup.send(
                E('q_error') + ' Failed to grant the role — check my permissions and role position.', ephemeral=True
            )
            return

    apply_db.update_application_status(app_id, new_status, interaction.user.id, reason=reason)
    app = apply_db.get_application(app_id)

    questions = settings["questions"] if settings else []
    applicant_display = applicant if applicant else await interaction.client.fetch_user(app["user_id"])
    embed = build_review_embed(app, applicant_display, questions)

    try:
        await review_message.edit(embed=embed, view=None)
    except discord.HTTPException:
        pass

    if applicant is not None:
        try:
            if new_status == "approved":
                dm_text = (
                    f"{E('q_celebrate')} Your staff application in **{guild.name}** was **approved**! "
                    f"You've been granted the **{granted_role.name}** role."
                )
            else:
                dm_text = f"Your staff application in **{guild.name}** was **denied**."
                if reason:
                    dm_text += f"\n**Reason:** {reason}"
            await applicant.send(dm_text)
            if new_status == "approved" and SERVER_VANITY_URL:
                await applicant.send(
                    f"One more thing — please add **{SERVER_VANITY_URL}** to your Discord bio!"
                )
        except discord.HTTPException:
            pass

    if new_status == "approved" and settings and settings.get("approval_channel_id"):
        approval_channel = guild.get_channel(settings["approval_channel_id"])
        if approval_channel is not None:
            announce_embed = ui_embeds.application(
                E('q_sparkle') + ' NEW STAFF MEMBER APPROVED',
                description=f"{applicant.mention if applicant else app['user_id']} has been approved and granted {granted_role.mention}!",
            )
            if applicant is not None:
                announce_embed.set_thumbnail(url=applicant.display_avatar.url)
            announce_embed.set_footer(text=f"Gogeta's Pet • Application #{app_id} • Approved by {interaction.user}")
            try:
                await approval_channel.send(embed=announce_embed)
            except discord.HTTPException:
                pass

    confirm_text = (
        f"{E('q_success')} Application #{app_id} approved and role granted."
        if new_status == "approved"
        else f"{E('q_error')} Application #{app_id} denied."
    )
    await interaction.followup.send(confirm_text, ephemeral=True)


class ApplicationReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        bind_view_emojis(self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(
                    E('q_error') + ' Something went wrong. Please try again.', ephemeral=True
                )
            except discord.HTTPException:
                pass
        print(f"[ApplicationReviewView] error in {item}: {type(error).__name__}: {error}")

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        custom_id="staff_app_approve",
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                E('q_error') + ' You need the **Manage Server** permission to review applications.', ephemeral=True
            )
            return

        app = apply_db.get_application_by_message(interaction.message.id)
        if app is None:
            await interaction.response.send_message(
                E('q_error') + " Couldn't find this application in the database.", ephemeral=True
            )
            return

        await finalize_application(interaction, app["id"], interaction.message, "approved")

    @discord.ui.button(
        label="Deny",
        style=discord.ButtonStyle.danger,
        custom_id="staff_app_deny",
    )
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                E('q_error') + ' You need the **Manage Server** permission to review applications.', ephemeral=True
            )
            return

        app = apply_db.get_application_by_message(interaction.message.id)
        if app is None:
            await interaction.response.send_message(
                E('q_error') + " Couldn't find this application in the database.", ephemeral=True
            )
            return
        if app["status"] != "pending":
            await interaction.response.send_message(
                E('q_error') + ' This application has already been handled.', ephemeral=True
            )
            return

        await interaction.response.send_modal(DenyReasonModal(app["id"], interaction.message))
