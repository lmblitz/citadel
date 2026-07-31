import json
import os

import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route
from dotenv import load_dotenv

load_dotenv()

bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.tree.command(name="ping", description="Check the bot's latency.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"Pong! {round(bot.latency * 1000)}ms")


@bot.tree.command(
    name="send",
    description="Send a message payload (content, embeds, components) to a channel.",
)
@app_commands.default_permissions(manage_messages=True)
@app_commands.describe(
    channel="The channel to send the message to.",
    code="The JSON message payload. Supports content, embeds, and components (v1 and v2).",
)
async def send(interaction: discord.Interaction, channel: discord.TextChannel, code: str):
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
        await bot.http.request(
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


bot.run(os.getenv("TOKEN"))
