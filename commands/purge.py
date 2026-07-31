import discord
from discord import app_commands
from discord.ext import commands

from .logs import log_mod_action


class Purge(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name="purge",
        description="Bulk delete messages in the current channel."
    )
    @commands.has_permissions(manage_messages=True)
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        amount="Number of messages to delete (max 100)."
    )
    async def purge(
        self,
        ctx: commands.Context,
        amount: int
    ):

        if amount < 1 or amount > 100:
            return await ctx.send(
                "Amount must be between 1 and 100.",
                ephemeral=True
            )

        await ctx.defer(ephemeral=True)

        deleted = []

        try:
            result = await ctx.channel.purge(limit=amount)

            if isinstance(result, list):
                deleted = result
            else:
                async for message in result:
                    deleted.append(message)
        except discord.Forbidden:
            return await ctx.send(
                "I don't have permission to delete messages here.",
                ephemeral=True
            )
        except discord.HTTPException as e:
            return await ctx.send(
                f"Failed to purge messages: {e}",
                ephemeral=True
            )

        await ctx.send(
            f"Deleted {len(deleted)} messages.",
            ephemeral=True
        )
        await log_mod_action(
            self.bot,
            "Purge",
            ctx.channel,
            ctx.author,
            f"{len(deleted)} messages deleted",
        )


async def setup(bot):
    await bot.add_cog(Purge(bot))
