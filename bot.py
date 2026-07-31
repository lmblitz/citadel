import os
from glob import glob

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def setup_hook():
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


bot.setup_hook = setup_hook


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")


bot.run(os.getenv("TOKEN"))
