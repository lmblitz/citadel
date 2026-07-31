import discord
from discord import app_commands
from discord.ext import commands


class Utility(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name="slowmode",
        description="Set the slowmode for the current channel."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.describe(
        seconds="Seconds between messages (0-21600, 0 disables slowmode)."
    )
    async def slowmode(self, ctx: commands.Context, seconds: int):
        if ctx.guild is None:
            return await ctx.send("This command can only be used in a server.", ephemeral=True)

        seconds = max(0, min(seconds, 21600))

        try:
            await ctx.channel.edit(slowmode_delay=seconds)
        except discord.Forbidden:
            return await ctx.send("I don't have permission to edit this channel.", ephemeral=True)
        except discord.HTTPException as e:
            return await ctx.send(f"Failed to set slowmode: {e}", ephemeral=True)

        if seconds == 0:
            await ctx.send("Slowmode has been disabled.", ephemeral=True)
        else:
            await ctx.send(f"Slowmode set to **{seconds}** seconds.", ephemeral=True)

    @commands.hybrid_command(
        name="lock",
        description="Lock the current channel so members can't send messages."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.default_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send("This command can only be used in a server.", ephemeral=True)

        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        try:
            await ctx.channel.set_permissions(
                ctx.guild.default_role,
                overwrite=overwrite,
                reason=f"Locked by {ctx.author}",
            )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to edit this channel.", ephemeral=True)
        except discord.HTTPException as e:
            return await ctx.send(f"Failed to lock the channel: {e}", ephemeral=True)

        await ctx.send(f"{ctx.channel.mention} has been locked.", ephemeral=True)

    @commands.hybrid_command(
        name="unlock",
        description="Unlock the current channel."
    )
    @commands.has_permissions(manage_channels=True)
    @app_commands.default_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send("This command can only be used in a server.", ephemeral=True)

        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        try:
            await ctx.channel.set_permissions(
                ctx.guild.default_role,
                overwrite=overwrite,
                reason=f"Unlocked by {ctx.author}",
            )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to edit this channel.", ephemeral=True)
        except discord.HTTPException as e:
            return await ctx.send(f"Failed to unlock the channel: {e}", ephemeral=True)

        await ctx.send(f"{ctx.channel.mention} has been unlocked.", ephemeral=True)

    @commands.hybrid_command(
        name="steal",
        description="Steal a custom emoji from another server."
    )
    @commands.has_permissions(manage_emojis=True)
    @app_commands.default_permissions(manage_emojis=True)
    @app_commands.describe(
        emoji="The custom emoji to steal."
    )
    async def steal(self, ctx: commands.Context, emoji: discord.PartialEmoji):
        if ctx.guild is None:
            return await ctx.send("This command can only be used in a server.", ephemeral=True)

        if emoji.is_unicode_emoji() or emoji.id is None:
            return await ctx.send("That is not a custom emoji.", ephemeral=True)

        if len(ctx.guild.emojis) >= ctx.guild.emoji_limit:
            return await ctx.send("This server has reached its emoji limit.", ephemeral=True)

        image = await emoji.read()

        try:
            created = await ctx.guild.create_custom_emoji(
                name=emoji.name,
                image=image,
                reason=f"Stolen by {ctx.author}",
            )
        except discord.Forbidden:
            return await ctx.send("I don't have permission to add emojis.", ephemeral=True)
        except discord.HTTPException as e:
            return await ctx.send(f"Failed to steal the emoji: {e}", ephemeral=True)

        await ctx.send(f"Stolen `{created.name}` {created}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Utility(bot))
