import discord
from discord import app_commands
from discord.ext import commands

REPORT_CHANNEL = 1532603654618615900

RESOLVE_ID = "report_resolve"
DISMISS_ID = "report_dismiss"


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
                "You do not have permission to manage reports.",
                ephemeral=True
            )

        embed = interaction.message.embeds[0]

        fields = list(embed.fields)

        report_info = next(
            (f for f in fields if f.name == "**Report Information**"),
            None
        )

        if report_info is None:
            return await interaction.response.send_message(
                "This report embed is invalid.",
                ephemeral=True
            )

        reason = (
            report_info.value
            .split("**Status**")[0]
            .replace("**Reason**", "")
            .strip()
        )

        embed.clear_fields()

        for field in fields:
            value = field.value

            if field.name == "**Report Information**":
                value = (
                    f"**Reason**\n{reason}\n\n"
                    f"**Status**\n{self.status}\n\n"
                    f"**Handled By**\n{interaction.user.mention}\n\n"
                    f"**Handled At**\n<t:{int(discord.utils.utcnow().timestamp())}:F>"
                )

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
                "You cannot report yourself.",
                ephemeral=True
            )

        if user.bot:
            return await interaction.response.send_message(
                "You cannot report a bot.",
                ephemeral=True
            )

        report_channel = interaction.guild.get_channel(REPORT_CHANNEL)

        if report_channel is None:
            return await interaction.response.send_message(
                "The report channel could not be found.",
                ephemeral=True
            )

        reported_member = interaction.guild.get_member(user.id)

        embed = discord.Embed(
            color=0xF87171,
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
                f"**User**\n{user.mention}\n\n"
                f"**Username**\n"
                f"{reported_member.display_name if reported_member else user.name}\n\n"
                f"**User ID**\n`{user.id}`\n\n"
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
                f"**User**\n{interaction.user.mention}\n\n"
                f"**Username**\n{interaction.user.display_name}\n\n"
                f"**User ID**\n`{interaction.user.id}`\n\n"
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
            "Your report has been submitted to the moderation team.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Report(bot))
