import discord
from discord.ext import commands

WELCOME_CHANNEL_ID = 1532820961336754456

RULES_CHANNEL = 1532575202649575587
INFO_CHANNEL = 1532575693374881953
CLAN_CHANNEL = 1532575934085861457
HELP_CHANNEL = 1532601436809203862


class Welcome(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _welcome_embed(member, guild):
        embed = discord.Embed(
            title=f"Welcome to {guild.name}!",
            description=(
                f"Hey {member.mention}, welcome to **{guild.name}**!\n"
                "We're excited to have you here."
            ),
            color=0x2ECC71,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Getting Started",
            value=(
                f"**1.** Read the **Rules** — <#{RULES_CHANNEL}>\n"
                f"**2.** Check out the **Info** — <#{INFO_CHANNEL}>\n"
                f"**3.** **Join a Clan** — <#{CLAN_CHANNEL}>\n"
                f"**4.** Need help? Visit the **Help Desk** — <#{HELP_CHANNEL}>"
            ),
            inline=False,
        )
        embed.add_field(
            name="Account Created",
            value=discord.utils.format_dt(member.created_at, "R"),
            inline=True,
        )
        embed.add_field(
            name="Member Count",
            value=guild.member_count,
            inline=True,
        )
        embed.add_field(
            name="User ID",
            value=f"`{member.id}`",
            inline=True,
        )
        embed.set_thumbnail(
            url=guild.icon.url if guild.icon else member.display_avatar.url
        )
        embed.set_image(url="attachment://welcome.png")
        embed.set_footer(text=f"{guild.name} • {guild.member_count} members")
        return embed

    async def _send_welcome(self, channel, member, guild):
        try:
            await channel.send(
                content=f"{member.mention}",
                embed=self._welcome_embed(member, guild),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return

        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if channel is None:
            return

        await self._send_welcome(channel, member, member.guild)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
