import discord
from discord.ext import commands

LOG_CHANNELS = {
    "channel_logs": 1532615499765252327,
    "role_logs": 1532615484715831337,
    "message_logs": 1532615454294671411,
    "server_logs": 1532615439291646134,
    "mod_logs": 1532615426146697316,
}

COLORS = {
    "channel_logs": 0x3498DB,
    "role_logs": 0x9B59B6,
    "message_logs": 0xF1C40F,
    "server_logs": 0x2ECC71,
    "mod_logs": 0xE67E22,
}

MOD_ACTION_COLORS = {
    "Kick": 0xE67E22,
    "Ban": 0xE74C3C,
    "Unban": 0x2ECC71,
    "Timeout": 0xE67E22,
    "Warn": 0xF1C40F,
    "Purge": 0x3498DB,
    "Honeypot Kick": 0xE74C3C,
}


def truncate(text, limit):
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def dt(timestamp, style):
    if timestamp is None:
        return "Unknown"
    return discord.utils.format_dt(timestamp, style)


async def log_mod_action(bot, action, target, moderator, reason=None):
    channel_id = LOG_CHANNELS.get("mod_logs")
    if not channel_id:
        return

    channel = bot.get_channel(channel_id)
    if channel is None:
        return

    embed = discord.Embed(
        title=action,
        color=MOD_ACTION_COLORS.get(action, COLORS["mod_logs"]),
        timestamp=discord.utils.utcnow(),
    )
    avatar = getattr(moderator, "display_avatar", None)
    embed.set_author(name=moderator, icon_url=avatar.url if avatar else None)
    embed.add_field(name="Target", value=f"{target} (`{target.id}`)", inline=True)
    if reason:
        embed.add_field(name="Reason", value=truncate(reason, 1024), inline=False)
    embed.set_footer(text=f"ID: {target.id}")

    try:
        await channel.send(embed=embed, silent=True)
    except (discord.Forbidden, discord.HTTPException):
        pass


class Logs(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def _send(self, log_type, embed):
        channel_id = LOG_CHANNELS.get(log_type)
        if not channel_id:
            return

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return

        try:
            await channel.send(embed=embed, silent=True)
        except (discord.Forbidden, discord.HTTPException):
            pass

    def _embed(self, log_type, title, description=None):
        embed = discord.Embed(
            title=title,
            description=truncate(description, 4000) if description else None,
            color=COLORS[log_type],
            timestamp=discord.utils.utcnow(),
        )
        return embed

    @staticmethod
    def _diff(before, after, attr, label):
        before_value = getattr(before, attr, None)
        after_value = getattr(after, attr, None)
        if before_value != after_value:
            return f"{label}: `{truncate(before_value, 200)}` → `{truncate(after_value, 200)}`"
        return None

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if channel.guild is None:
            return
        embed = self._embed(
            "channel_logs",
            "Channel Created",
            description=f"{channel.mention}\n`{channel.name}`",
        )
        embed.add_field(name="Type", value=str(channel.type), inline=True)
        embed.add_field(
            name="Category",
            value=channel.category.name if channel.category else "None",
            inline=True,
        )
        embed.add_field(name="Position", value=getattr(channel, "position", 0), inline=True)
        embed.set_footer(text=f"Channel ID: {channel.id}")
        await self._send("channel_logs", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if channel.guild is None:
            return
        embed = self._embed(
            "channel_logs",
            "Channel Deleted",
            description=f"`{channel.name}`",
        )
        embed.add_field(name="Type", value=str(channel.type), inline=True)
        embed.add_field(
            name="Category",
            value=channel.category.name if channel.category else "None",
            inline=True,
        )
        embed.set_footer(text=f"Channel ID: {channel.id}")
        await self._send("channel_logs", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if after.guild is None:
            return
        changes = []
        for attr, label in (
            ("name", "Name"),
            ("topic", "Topic"),
            ("slowmode_delay", "Slowmode"),
            ("nsfw", "NSFW"),
            ("category", "Category"),
            ("position", "Position"),
        ):
            diff = self._diff(before, after, attr, label)
            if diff:
                changes.append(diff)
        if not changes:
            return
        embed = self._embed(
            "channel_logs",
            "Channel Updated",
            description=f"{after.mention}\n" + "\n".join(changes),
        )
        embed.set_footer(text=f"Channel ID: {after.id}")
        await self._send("channel_logs", embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        embed = self._embed(
            "role_logs",
            "Role Created",
            description=f"{role.mention} (`{role.name}`)",
        )
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Hoisted", value=str(role.hoist), inline=True)
        embed.add_field(name="Mentionable", value=str(role.mentionable), inline=True)
        embed.add_field(name="Position", value=role.position, inline=True)
        embed.set_footer(text=f"Role ID: {role.id}")
        await self._send("role_logs", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        embed = self._embed(
            "role_logs",
            "Role Deleted",
            description=f"`{role.name}`",
        )
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Hoisted", value=str(role.hoist), inline=True)
        embed.add_field(name="Mentionable", value=str(role.mentionable), inline=True)
        embed.set_footer(text=f"Role ID: {role.id}")
        await self._send("role_logs", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = []
        for attr, label in (
            ("name", "Name"),
            ("color", "Color"),
            ("hoist", "Display separately"),
            ("mentionable", "Mentionable"),
            ("permissions", "Permissions"),
        ):
            diff = self._diff(before, after, attr, label)
            if diff:
                changes.append(diff)
        if not changes:
            return
        embed = self._embed(
            "role_logs",
            "Role Updated",
            description=f"{after.mention}\n" + "\n".join(changes),
        )
        embed.set_footer(text=f"Role ID: {after.id}")
        await self._send("role_logs", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles == after.roles:
            return
        lines = []
        added = [role.mention for role in after.roles if role not in before.roles]
        if added:
            lines.append(f"**Added:** {', '.join(added)}")
        removed = [role.mention for role in before.roles if role not in after.roles]
        if removed:
            lines.append(f"**Removed:** {', '.join(removed)}")
        embed = self._embed(
            "role_logs",
            "Member Roles Updated",
            description=f"{after.mention}\n" + "\n".join(lines),
        )
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.set_footer(text=f"ID: {after.id}")
        await self._send("role_logs", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.guild is None:
            return
        if not message.content and not message.attachments:
            return
        embed = self._embed(
            "message_logs",
            "Message Deleted",
            description=f"It was sent at {dt(message.created_at, 'f')}",
        )
        embed.set_author(
            name=f"Message from {message.author.display_name} deleted in #{message.channel.name}",
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(
            name="Message Content",
            value=truncate(message.content or "*no text content*", 1024),
            inline=False,
        )
        embed.add_field(name="Message ID", value=message.id, inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        if message.attachments:
            embed.add_field(name="Attachments", value=len(message.attachments), inline=True)
        embed.set_footer(text=f"User ID: {message.author.id}")
        await self._send("message_logs", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.guild is None:
            return
        if before.content == after.content:
            return
        if not before.content or not after.content:
            return
        edited = after.edited_at or discord.utils.utcnow()
        embed = self._embed(
            "message_logs",
            "Message Edited",
            description=f"View the message in {after.channel.mention}",
        )
        embed.set_author(
            name=f"Message from @{after.author.display_name} edited {dt(edited, 'R')}",
            icon_url=after.author.display_avatar.url,
        )
        embed.add_field(name="Before", value=truncate(before.content, 1024), inline=False)
        embed.add_field(name="After", value=truncate(after.content, 1024), inline=False)
        embed.add_field(name="Message ID", value=after.id, inline=True)
        embed.set_footer(text=f"User ID: {after.author.id}")
        await self._send("message_logs", embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        if guild is None:
            return
        embed = self._embed(
            "message_logs",
            "Bulk Messages Deleted",
            description=f"**{len(messages)}** messages in {channel.mention}",
        )
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Channel ID", value=channel.id, inline=True)
        embed.set_footer(text=f"Messages: {len(messages)}")
        await self._send("message_logs", embed)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = self._embed(
            "server_logs",
            "Member Joined",
            description=f"{member.mention}",
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Account Created", value=dt(member.created_at, "R"), inline=True)
        embed.add_field(name="Joined", value=dt(member.joined_at, "R"), inline=True)
        embed.set_footer(text=f"ID: {member.id}")
        await self._send("server_logs", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        roles = [r for r in member.roles if not r.is_default()]
        embed = self._embed(
            "server_logs",
            "Member Left",
            description=f"{member.mention} (`{member.name}`)",
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Joined", value=dt(member.joined_at, "R"), inline=True)
        embed.add_field(name="Roles", value=len(roles), inline=True)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=True)
        embed.set_footer(text=f"ID: {member.id}")
        await self._send("server_logs", embed)

    @staticmethod
    async def _audit_reason(guild, action, user):
        try:
            async for entry in guild.audit_logs(limit=1, action=action):
                if entry.target and entry.target.id == user.id:
                    return entry.reason
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        reason = await self._audit_reason(guild, discord.AuditLogAction.ban, user)
        embed = self._embed(
            "server_logs",
            "Member Banned",
            description=f"{user.mention} (`{user.id}`)",
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
        if reason:
            embed.add_field(name="Reason", value=truncate(reason, 1024), inline=False)
        embed.set_footer(text=f"ID: {user.id}")
        await self._send("server_logs", embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        reason = await self._audit_reason(guild, discord.AuditLogAction.unban, user)
        embed = self._embed(
            "server_logs",
            "Member Unbanned",
            description=f"{user.mention} (`{user.id}`)",
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
        if reason:
            embed.add_field(name="Reason", value=truncate(reason, 1024), inline=False)
        embed.set_footer(text=f"ID: {user.id}")
        await self._send("server_logs", embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changes = []
        for attr, label in (
            ("name", "Name"),
            ("description", "Description"),
        ):
            diff = self._diff(before, after, attr, label)
            if diff:
                changes.append(diff)
        if not changes:
            return
        embed = self._embed(
            "server_logs",
            "Server Updated",
            description="\n".join(changes),
        )
        embed.set_footer(text=f"Server ID: {after.id}")
        await self._send("server_logs", embed)


async def setup(bot):
    await bot.add_cog(Logs(bot))
