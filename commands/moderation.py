import json
import os
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "warnings.json",
)


def load_warnings():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_warnings(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Moderation(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def can_act_on(interaction, member):
        if member == interaction.user:
            return False, "You can't do that to yourself."
        if member.id == interaction.guild.owner_id:
            return False, "You can't do that to the server owner."
        if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
            return False, "You can't do that to a member with a higher or equal role."
        if member.bot:
            return False, "You can't do that to a bot."
        return True, None

    @app_commands.command(
        name="kick",
        description="Kick a member from the server."
    )
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(
        member="Member to kick.",
        reason="Reason for the kick."
    )
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided."
    ):
        allowed, error = self.can_act_on(interaction, member)
        if not allowed:
            return await interaction.response.send_message(error, ephemeral=True)

        try:
            await member.kick(reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to kick that member.",
                ephemeral=True
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"Failed to kick: {e}",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"**{member}** has been kicked.\nReason: {reason}"
        )

    @app_commands.command(
        name="ban",
        description="Ban a member from the server."
    )
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        member="Member to ban.",
        reason="Reason for the ban."
    )
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided."
    ):
        allowed, error = self.can_act_on(interaction, member)
        if not allowed:
            return await interaction.response.send_message(error, ephemeral=True)

        try:
            await member.ban(reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to ban that member.",
                ephemeral=True
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"Failed to ban: {e}",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"**{member}** has been banned.\nReason: {reason}"
        )

    @app_commands.command(
        name="unban",
        description="Unban a user from the server."
    )
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(
        user="The user to unban.",
        reason="Reason for the unban."
    )
    async def unban(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        reason: str = "No reason provided."
    ):
        try:
            await interaction.guild.unban(user, reason=reason)
        except discord.NotFound:
            return await interaction.response.send_message(
                "That user is not banned.",
                ephemeral=True
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to unban that user.",
                ephemeral=True
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"Failed to unban: {e}",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"**{user}** has been unbanned.\nReason: {reason}"
        )

    @app_commands.command(
        name="timeout",
        description="Timeout (mute) a member."
    )
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(
        member="Member to timeout.",
        duration="Duration in minutes.",
        reason="Reason for the timeout."
    )
    async def timeout(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: int,
        reason: str = "No reason provided."
    ):
        if duration < 1:
            return await interaction.response.send_message(
                "Duration must be at least 1 minute.",
                ephemeral=True
            )

        allowed, error = self.can_act_on(interaction, member)
        if not allowed:
            return await interaction.response.send_message(error, ephemeral=True)

        try:
            await member.timeout(timedelta(minutes=duration), reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "I don't have permission to timeout that member.",
                ephemeral=True
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"Failed to timeout: {e}",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"**{member}** has been timed out for **{duration}** minute(s).\nReason: {reason}"
        )

    @app_commands.command(
        name="warn",
        description="Warn a member."
    )
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(
        member="Member to warn.",
        reason="Reason for the warning."
    )
    async def warn(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "No reason provided."
    ):
        allowed, error = self.can_act_on(interaction, member)
        if not allowed:
            return await interaction.response.send_message(error, ephemeral=True)

        data = load_warnings()
        guild_key = str(interaction.guild_id)
        member_key = str(member.id)

        warning = {
            "reason": reason,
            "moderator": str(interaction.user.id),
            "timestamp": str(discord.utils.utcnow()),
        }

        data.setdefault(guild_key, {}).setdefault(member_key, []).append(warning)
        save_warnings(data)

        count = len(data[guild_key][member_key])

        await interaction.response.send_message(
            f"**{member}** has been warned.\nReason: {reason}\nWarnings: {count}"
        )

    @app_commands.command(
        name="warnings",
        description="View a member's warnings."
    )
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(
        member="Member to check."
    )
    async def warnings(
        self,
        interaction: discord.Interaction,
        member: discord.Member
    ):
        data = load_warnings()
        warns = data.get(str(interaction.guild_id), {}).get(str(member.id), [])

        if not warns:
            return await interaction.response.send_message(
                f"**{member}** has no warnings.",
                ephemeral=True
            )

        lines = [
            f"{index + 1}. {warning['reason']} — <@{warning['moderator']}>"
            for index, warning in enumerate(warns)
        ]

        await interaction.response.send_message(
            f"**{member}** has {len(warns)} warning(s):\n" + "\n".join(lines),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Moderation(bot))
