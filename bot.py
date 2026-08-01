import os
from glob import glob

import discord
from discord.ext import commands
from dotenv import load_dotenv

import archive
import dashboard
from dashboard import GUILD_ID

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="?", intents=intents)


async def setup_hook():
    archive.init()
    for path in glob("commands/*"):
        if not os.path.isfile(path):
            continue
        if os.path.basename(path) == "__init__.py":
            continue
        if not path.endswith(".py"):
            os.rename(path, path + ".py")
            path += ".py"
        name = os.path.splitext(os.path.basename(path))[0]
        await bot.load_extension(f"commands.{name}")
        print(f"Loaded commands.{name}")
    await dashboard.start(bot)
    bot.loop.create_task(backfill_on_start())


async def backfill_on_start():
    await bot.wait_until_ready()
    try:
        limit = int(os.getenv("ARCHIVE_BACKFILL_LIMIT", "1000"))
    except ValueError:
        limit = 1000
    count = await archive.backfill(bot, GUILD_ID, limit)
    print(f"Backfill complete: {count} message(s) recorded")


bot.setup_hook = setup_hook


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.event
async def on_message(message):
    archive.record_message(message)
    await bot.process_commands(message)


@bot.event
async def on_message_delete(message):
    archive.mark_deleted(message.id)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        missing = ", ".join(error.missing_permissions)
        return await ctx.send(
            f"You need the `{missing}` permission to use this command.",
            ephemeral=True,
        )
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(
            f"Missing required argument: `{error.param.name}`.",
            ephemeral=True,
        )
    print(f"Command error in {ctx.command}: {error}")


bot.run(os.getenv("TOKEN"))
