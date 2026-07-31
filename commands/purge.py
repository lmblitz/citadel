import discord
from discord import app_commands
from discord.ext import commands


class Purge(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="purge",
        description="Bulk delete messages in the current channel."
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(
        amount="Number of messages to delete (max 100)."
    )
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: int
    ):

        if amount < 1 or amount > 100:
            await interaction.response.send_message(
                "Amount must be between 1 and 100.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        deleted = []

        try:
            result = await interaction.channel.purge(limit=amount)

            if isinstance(result, list):
                deleted = result
            else:
                async for message in result:
                    deleted.append(message)
        except discord.Forbidden:
            await interaction.followup.send(
                "I don't have permission to delete messages here.",
                ephemeral=True
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"Failed to purge messages: {e}",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"Deleted {len(deleted)} messages.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Purge(bot))
