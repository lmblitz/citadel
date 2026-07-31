import re

import discord
from discord import app_commands
from discord.ext import commands

REPORT_CHANNEL = 1532603654618615900

RESOLVE_ID = "report_resolve"
DISMISS_ID = "report_dismiss"

REPORTER_ID_RE = re.compile(r"`(\d+)`")


def response_embed(description, color):
    return discord.Embed(
        description=description,
        color=color,
    )


class ReportModal(discord.ui.Modal):

    def __init__(self, status, message, view, handled_by, client):
        super().__init__(title=f"Report {status}")

        self.status = status
        self.message = message
        self.view = view
        self.handled_by = handled_by
        self.client = client

        self.note_input = discord.ui.TextInput(
            label="Reason (optional)",
            placeholder="Optional note shown to the reporter...",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )

        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        note = self.note_input.value.strip() or None

        embed = self.message.embeds[0]
        fields = list(embed.fields)

        report_info = next(
            (f for f in fields if f.name == "**Report Information**"),
            None
        )

        if report_info is None:
            return await interaction.response.send_message(
                embed=response_embed(
                    "This report embed is invalid.",
                    discord.Color.red(),
                ),
                ephemeral=True
            )

        reason = (
            report_info.value
            .split("**Status**")[0]
            .replace("**Reason**", "")
            .strip()
        )

        new_info = (
            f"**Reason**\n{reason}\n\n"
            f"**Status**\n{self.status}\n\n"
            f"**Handled By**\n{self.handled_by.mention}\n\n"
            f"**Handled At**\n<t:{int(discord.utils.utcnow().timestamp())}:F>"
        )

        if note:
            new_info += f"\n\n**Staff Note**\n{note}"

        embed.clear_fields()

        for field in fields:
            value = field.value

            if field.name == "**Report Information**":
                value = new_info

            embed.add_field(
                name=field.name,
                value=value,
                inline=field.inline
            )

        for item in self.view.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=embed,
            view=self.view
        )

        await self.notify_reporter(reason, note)

    async def notify_reporter(self, reason, note):
        embed = self.message.embeds[0]

        reporter_field = next(
            (f for f in embed.fields if f.name == "**Reporter**"),
            None
        )

        if reporter_field is None:
            return

        match = REPORTER_ID_RE.search(reporter_field.value)
        if match is None:
            return

        user = self.client.get_user(int(match.group(1)))

        if user is None:
            try:
                user = await self.client.fetch_user(int(match.group(1)))
            except discord.HTTPException:
                return

        color = (
            discord.Color.green()
            if self.status == "Resolved"
            else discord.Color.red()
        )

        dm_embed = discord.Embed(
            title=f"Report {self.status}",
            description=(
                f"Your report has been **{self.status}** by "
                f"{self.handled_by.mention}."
            ),
            color=color,
        )

        dm_embed.add_field(
            name="Your Report",
            value=reason[:1024] or "*(empty)*",
            inline=False,
        )

        if note:
            dm_embed.add_field(
                name="Staff Note",
                value=note,
                inline=False,
            )

        try:
            await user.send(embed=dm_embed)
        except discord.HTTPException:
            pass


class ReportButton(discord.ui.Button):

    def __init__(self, status, label, style, custom_id):
        super().__init__(
            label=label,
            style=style,
            custom_id=custom_id
        )

        self.status = status

    async def callback(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message(
                embed=response_embed(
                    "You do not have permission to manage reports.",
                    discord.Color.red(),
                ),
                ephemeral=True
            )

        modal = ReportModal(
            self.status,
            interaction.message,
            self.view,
            interaction.user,
            interaction.client,
        )

        await interaction.response.send_modal(modal)


class ReportView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(
            ReportButton(
                "Resolved",
                "Mark as Resolved",
                discord.ButtonStyle.success,
                RESOLVE_ID
            )
        )

        self.add_item(
            ReportButton(
                "Dismissed",
                "Dismiss",
                discord.ButtonStyle.danger,
                DISMISS_ID
            )
        )


class Report(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ReportView())

    @app_commands.command(
        name="report",
        description="Report a member to the moderation team."
    )
    @app_commands.describe(
        user="The member you are reporting.",
        reason="Why are you reporting them?",
        attachment="Evidence (optional)."
    )
    async def report(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: app_commands.Range[str, 1, 1000],
        attachment: discord.Attachment = None
    ):

        if user.id == interaction.user.id:
            return await interaction.response.send_message(
                embed=response_embed(
                    "You cannot report yourself.",
                    discord.Color.red(),
                ),
                ephemeral=True
            )

        if user.bot:
            return await interaction.response.send_message(
                embed=response_embed(
                    "You cannot report a bot.",
                    discord.Color.red(),
                ),
                ephemeral=True
            )

        report_channel = interaction.guild.get_channel(REPORT_CHANNEL)

        if report_channel is None:
            return await interaction.response.send_message(
                embed=response_embed(
                    "The report channel could not be found.",
                    discord.Color.red(),
                ),
                ephemeral=True
            )

        reported_member = None
        try:
            reported_member = await interaction.guild.fetch_member(user.id)
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title="User Report",
            description=(
                "A member has submitted a report. "
                "Review the details below and take action."
            ),
            color=0xDC2626,
            timestamp=discord.utils.utcnow()
        )

        embed.set_author(
            name="New User Report",
            icon_url=interaction.guild.icon.url
            if interaction.guild.icon
            else None
        )

        embed.set_thumbnail(
            url=user.display_avatar.url
        )

        embed.add_field(
            name="**Report Information**",
            value=f"**Reason**\n{reason}\n\n**Status**\nPending",
            inline=False
        )

        embed.add_field(
            name="**Reported User**",
            value=(
                f"{user.mention}\n`{user.id}`\n\n"
                f"**Account Created**\n"
                f"<t:{int(user.created_at.timestamp())}:F>\n\n"
                f"**Joined Server**\n"
                f"{f'<t:{int(reported_member.joined_at.timestamp())}:F>' if reported_member else 'Unknown'}\n\n"
                f"**Highest Role**\n"
                f"{reported_member.top_role.mention if reported_member else 'Unknown'}"
            ),
            inline=True
        )

        embed.add_field(
            name="**Reporter**",
            value=(
                f"{interaction.user.mention}\n`{interaction.user.id}`\n\n"
                f"**Account Created**\n"
                f"<t:{int(interaction.user.created_at.timestamp())}:F>\n\n"
                f"**Joined Server**\n"
                f"<t:{int(interaction.user.joined_at.timestamp())}:F>"
            ),
            inline=True
        )

        if attachment:
            embed.add_field(
                name="**Attachment**",
                value=f"[Open Attachment]({attachment.url})",
                inline=False
            )

            if attachment.content_type and attachment.content_type.startswith("image"):
                embed.set_image(url=attachment.url)

        embed.set_footer(
            text=f"Report • {interaction.guild.name}"
        )

        await report_channel.send(
            embed=embed,
            view=ReportView()
        )

        await interaction.response.send_message(
            embed=response_embed(
                "Your report has been submitted to the moderation team.",
                discord.Color.green(),
            ),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Report(bot))
