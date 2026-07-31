import discord
from discord import app_commands
from discord.ext import commands


# IDs
REQUIRED_ROLE = 1532599944236503230

MODERATOR_ROLE = 1532569676901646346
ADMIN_ROLE = 1532569640318931015

EMERGENCY_CHANNEL = 1532605324803178687


class Emergency(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="emergency",
        description="Request immediate moderator assistance."
    )
    @app_commands.describe(
        reason="Explain what is happening."
    )
    async def emergency(
        self,
        interaction: discord.Interaction,
        reason: str
    ):

        # Permission Check
        if not any(
            role.id == REQUIRED_ROLE
            for role in interaction.user.roles
        ):
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True
            )
            return

        channel = interaction.guild.get_channel(
            EMERGENCY_CHANNEL
        )

        if channel is None:
            await interaction.response.send_message(
                "Emergency channel could not be found.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Emergency Alert",
            description=(
                f"{interaction.user.mention} has marked an emergency "
                "and is requesting immediate moderator assistance."
            ),
            colour=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="**User**",
            value=interaction.user.mention,
            inline=True
        )

        embed.add_field(
            name="**Channel**",
            value=interaction.channel.mention,
            inline=True
        )

        embed.add_field(
            name="**User ID**",
            value=f"`{interaction.user.id}`",
            inline=True
        )

        embed.add_field(
            name="**Reason**",
            value=reason,
            inline=False
        )

        embed.add_field(
            name="**Account Created**",
            value=f"<t:{int(interaction.user.created_at.timestamp())}:F>",
            inline=False
        )

        embed.set_thumbnail(
            url=interaction.user.display_avatar.url
        )

        embed.set_footer(
            text=f"Emergency • {interaction.guild.name}"
        )

        await channel.send(
            content=(
                f"<@&{MODERATOR_ROLE}> "
                f"<@&{ADMIN_ROLE}>"
            ),
            embed=embed,
            allowed_mentions=discord.AllowedMentions(
                roles=True
            )
        )

        await interaction.response.send_message(
            "Your emergency request has been sent to the moderation team.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Emergency(bot))
