import json
import os

import discord
from discord.ext import commands

from .logs import log_mod_action

HONEYPOT_CHANNEL_ID = 1532816296272597143

DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "honeypot.json",
)


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class ActionsView(discord.ui.View):

    def __init__(self, count):
        super().__init__()
        self.add_item(
            discord.ui.Button(
                label=f"Actions taken: {count}",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id="honeypot_actions_taken",
            )
        )


def warning_embed(bot):
    embed = discord.Embed(
        title="DO NOT SEND MESSAGES IN THIS CHANNEL",
        description=(
            "This channel is used to catch spam bots. Any messages sent "
            "here will result in a kick."
        ),
        color=discord.Color.red(),
    )
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    return embed


class Honeypot(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._ready = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self._ready:
            return
        self._ready = True

        channel = self.bot.get_channel(HONEYPOT_CHANNEL_ID)
        if channel is None:
            return

        data = load_data()
        warning_id = data.get("message_id")
        count = data.get("kicked", 0)

        if warning_id:
            try:
                warning = await channel.fetch_message(warning_id)
                await warning.edit(
                    embed=warning_embed(self.bot),
                    view=ActionsView(count),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                warning = await channel.send(
                    embed=warning_embed(self.bot),
                    view=ActionsView(count),
                    silent=True,
                )
                data["message_id"] = warning.id
        else:
            warning = await channel.send(
                embed=warning_embed(self.bot),
                view=ActionsView(count),
                silent=True,
            )
            data["message_id"] = warning.id

        data["kicked"] = count
        save_data(data)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.channel.id != HONEYPOT_CHANNEL_ID:
            return
        if message.author.bot:
            return

        member = message.author

        try:
            await message.guild.kick(
                member,
                reason="Sent a message in the honeypot channel.",
            )
        except (discord.Forbidden, discord.HTTPException):
            return

        data = load_data()
        warning_id = data.get("message_id")
        count = data.get("kicked", 0) + 1
        data["kicked"] = count
        save_data(data)

        if warning_id:
            try:
                warning = await message.channel.fetch_message(warning_id)
                await warning.edit(
                    embed=warning_embed(self.bot),
                    view=ActionsView(count),
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        await log_mod_action(
            self.bot,
            "Honeypot Kick",
            member,
            message.guild.me,
            "Sent a message in the honeypot channel.",
        )


async def setup(bot):
    await bot.add_cog(Honeypot(bot))
