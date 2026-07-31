import json

import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route


class Send(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="send",
        description="Send a message payload (content, embeds, components) to a channel.",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        channel="The channel to send the message to.",
        code="The JSON message payload. Supports content, embeds, and components (v1 and v2).",
    )
    async def send(
        self, interaction: discord.Interaction, channel: discord.TextChannel, code: str
    ):
        await interaction.response.defer(ephemeral=True)

        try:
            payload = json.loads(code)
        except json.JSONDecodeError as e:
            await interaction.followup.send(f"Invalid JSON: {e}", ephemeral=True)
            return

        if not isinstance(payload, dict):
            await interaction.followup.send("Payload must be a JSON object.", ephemeral=True)
            return

        if not any(key in payload for key in ("content", "embeds", "components")):
            await interaction.followup.send(
                "Payload must contain at least one of `content`, `embeds`, or `components`.",
                ephemeral=True,
            )
            return

        try:
            await self.bot.http.request(
                Route("POST", "/channels/{channel_id}/messages", channel_id=channel.id),
                json=payload,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"I don't have permission to send messages in {channel.mention}.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Discord rejected the message: {e}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"Message sent to {channel.mention}.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Send(bot))
