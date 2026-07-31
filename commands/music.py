import asyncio

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands


class MusicPlayerView(discord.ui.View):

    def __init__(self, cog, guild_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="Pause/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc is None:
            return await interaction.response.send_message(
                "I'm not in a voice channel.", ephemeral=True
            )
        if vc.is_playing():
            vc.pause()
        elif vc.is_paused():
            vc.resume()
        else:
            return await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True
            )
        await interaction.response.defer()

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc is None or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True
            )
        vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc is None:
            return await interaction.response.send_message(
                "I'm not in a voice channel.", ephemeral=True
            )
        await self.cog.stop_playback(interaction.guild, vc)
        await interaction.response.send_message("Stopped.", ephemeral=True)

    @discord.ui.button(label="Volume -", style=discord.ButtonStyle.secondary)
    async def vol_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc is None:
            return await interaction.response.send_message(
                "I'm not in a voice channel.", ephemeral=True
            )
        await self.cog.adjust_volume(interaction.guild, -10)
        await interaction.response.defer()

    @discord.ui.button(label="Volume +", style=discord.ButtonStyle.secondary)
    async def vol_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc is None:
            return await interaction.response.send_message(
                "I'm not in a voice channel.", ephemeral=True
            )
        await self.cog.adjust_volume(interaction.guild, 10)
        await interaction.response.defer()


class Music(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._queues = {}
        self._np = {}
        self._volumes = {}
        self._panels = {}
        self._panel_locs = {}

    @staticmethod
    def _ffmpeg():
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return "ffmpeg"

    @staticmethod
    def _format_duration(seconds):
        if not seconds:
            return "Unknown"
        seconds = int(seconds)
        hours, rem = divmod(seconds, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _queue(self, guild_id):
        return self._queues.setdefault(guild_id, [])

    def _cleanup(self, guild_id):
        self._queues.pop(guild_id, None)
        self._np.pop(guild_id, None)

    def _extract(self, query):
        url = query if query.startswith("http") else f"ytsearch1:{query}"
        options = {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": True,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                return {
                    "url": info.get("url"),
                    "title": info.get("title") or "Unknown",
                    "duration": info.get("duration"),
                    "uploader": info.get("uploader"),
                    "thumbnail": info.get("thumbnail"),
                    "webpage_url": info.get("webpage_url"),
                }
        except Exception:
            return None

    def _track_embed(self, track, volume=None):
        embed = discord.Embed(
            title=track["title"],
            url=track.get("webpage_url"),
            color=0x1DB954,
        )
        if track.get("thumbnail"):
            embed.set_thumbnail(url=track["thumbnail"])
        if track.get("uploader"):
            embed.add_field(name="Uploader", value=track["uploader"], inline=True)
        if track.get("duration"):
            embed.add_field(
                name="Duration",
                value=self._format_duration(track["duration"]),
                inline=True,
            )
        if volume is not None:
            embed.add_field(
                name="Volume",
                value=f"{int(volume * 100)}%",
                inline=True,
            )
        return embed

    def _after(self, guild, error):
        if error:
            print(f"Music playback error in {guild.id}: {error}")
        asyncio.run_coroutine_threadsafe(self._next(guild), self.bot.loop)

    async def _update_panel(self, guild, track):
        message = self._panels.get(guild.id)
        embed = self._track_embed(track, self._volumes.get(guild.id, 0.5))

        if message is not None:
            try:
                await message.edit(embed=embed)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        channel_id = self._panel_locs.get(guild.id)
        channel = self.bot.get_channel(channel_id) if channel_id else None
        if channel is None:
            return

        try:
            message = await channel.send(
                embed=embed,
                view=MusicPlayerView(self, guild.id),
            )
            self._panels[guild.id] = message
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _remove_panel(self, guild_id):
        message = self._panels.pop(guild_id, None)
        self._panel_locs.pop(guild_id, None)
        if message is not None:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    async def _play_next(self, guild, vc):
        queue = self._queue(guild.id)
        if not queue:
            self._np.pop(guild.id, None)
            return

        track = queue.pop(0)
        self._np[guild.id] = track

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                track["url"],
                executable=self._ffmpeg(),
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                options="-vn",
            ),
            volume=self._volumes.get(guild.id, 0.5),
        )

        vc.play(source, after=lambda err: self._after(guild, err))
        await self._update_panel(guild, track)

    async def _next(self, guild):
        vc = guild.voice_client
        if vc is None:
            await self._remove_panel(guild.id)
            self._cleanup(guild.id)
            return

        if self._queue(guild.id):
            await self._play_next(guild, vc)
        else:
            self._np.pop(guild.id, None)
            await asyncio.sleep(60)
            if (
                vc is not None
                and vc.is_connected()
                and not vc.is_playing()
                and not self._queue(guild.id)
            ):
                await vc.disconnect()
                await self._remove_panel(guild.id)
                self._cleanup(guild.id)

    async def stop_playback(self, guild, vc):
        self._queue(guild.id).clear()
        self._np.pop(guild.id, None)
        vc.stop()
        await vc.disconnect()
        await self._remove_panel(guild.id)
        self._cleanup(guild.id)

    async def adjust_volume(self, guild, delta):
        current = int(self._volumes.get(guild.id, 0.5) * 100)
        new = max(0, min(100, current + delta)) / 100
        self._volumes[guild.id] = new
        vc = guild.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = new
        track = self._np.get(guild.id)
        message = self._panels.get(guild.id)
        if track is not None and message is not None:
            try:
                await message.edit(embed=self._track_embed(track, new))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.id != self.bot.user.id:
            return
        if after.channel is None:
            await self._remove_panel(member.guild.id)
            self._cleanup(member.guild.id)

    @commands.hybrid_command(
        name="play",
        description="Play a song from YouTube by name or URL."
    )
    @commands.guild_only()
    @app_commands.describe(query="Song name or YouTube URL.")
    async def play(self, ctx: commands.Context, query: str):
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            return await ctx.send(
                "You need to be in a voice channel first.",
                ephemeral=True,
            )

        self._panel_locs[ctx.guild.id] = ctx.channel.id

        async with ctx.typing():
            track = await asyncio.to_thread(self._extract, query)
            if track is None:
                return await ctx.send(
                    "Couldn't find that track.",
                    ephemeral=True,
                )
            self._queue(ctx.guild.id).append(track)
            self._volumes.setdefault(ctx.guild.id, 0.5)

        vc = ctx.voice_client
        if vc is None:
            try:
                vc = await ctx.author.voice.channel.connect()
            except discord.Forbidden:
                return await ctx.send(
                    "I don't have permission to join that channel.",
                    ephemeral=True,
                )
            except discord.HTTPException:
                return await ctx.send(
                    "Couldn't connect to the voice channel.",
                    ephemeral=True,
                )

        if vc.is_playing() or vc.is_paused():
            position = len(self._queue(ctx.guild.id))
            await ctx.send(
                f"Added **{track['title']}** to the queue (position {position}).",
                ephemeral=True,
            )
        else:
            await self._play_next(ctx.guild, vc)
            await ctx.send(
                f"Now playing **{track['title']}**.",
                ephemeral=True,
            )

    @commands.hybrid_command(
        name="skip",
        description="Skip the current track."
    )
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc is None or not (vc.is_playing() or vc.is_paused()):
            return await ctx.send(
                "Nothing is playing right now.",
                ephemeral=True,
            )
        track = self._np.get(ctx.guild.id)
        vc.stop()
        if track:
            await ctx.send(
                f"Skipped **{track['title']}**.",
                ephemeral=True,
            )
        else:
            await ctx.send("Skipped.", ephemeral=True)

    @commands.hybrid_command(
        name="pause",
        description="Pause the current track."
    )
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc is None or not vc.is_playing():
            return await ctx.send(
                "Nothing is playing right now.",
                ephemeral=True,
            )
        vc.pause()
        await ctx.send("Paused.", ephemeral=True)

    @commands.hybrid_command(
        name="resume",
        description="Resume the current track."
    )
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc is None or not vc.is_paused():
            return await ctx.send(
                "The player isn't paused.",
                ephemeral=True,
            )
        vc.resume()
        await ctx.send("Resumed.", ephemeral=True)

    @commands.hybrid_command(
        name="stop",
        description="Stop playback and clear the queue."
    )
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc is None:
            return await ctx.send(
                "I'm not in a voice channel.",
                ephemeral=True,
            )
        await self.stop_playback(ctx.guild, vc)
        await ctx.send("Stopped and left the voice channel.", ephemeral=True)

    @commands.hybrid_command(
        name="now",
        description="Show the currently playing track."
    )
    @commands.guild_only()
    async def now(self, ctx: commands.Context):
        track = self._np.get(ctx.guild.id)
        vc = ctx.voice_client
        if track is None or vc is None:
            return await ctx.send(
                "Nothing is playing right now.",
                ephemeral=True,
            )
        await ctx.send(
            embed=self._track_embed(track, self._volumes.get(ctx.guild.id, 0.5)),
            ephemeral=True,
        )

    @commands.hybrid_command(
        name="queue",
        description="Show the current queue."
    )
    @commands.guild_only()
    async def queue(self, ctx: commands.Context):
        queue = self._queue(ctx.guild.id)
        np_track = self._np.get(ctx.guild.id)
        if not queue and np_track is None:
            return await ctx.send(
                "The queue is empty.",
                ephemeral=True,
            )
        lines = []
        if np_track:
            lines.append(f"**Now Playing:** {np_track['title']}")
        for index, track in enumerate(queue[:10], start=1):
            lines.append(
                f"`{index}.` {track['title']} "
                f"({self._format_duration(track['duration'])})"
            )
        if len(queue) > 10:
            lines.append(f"...and {len(queue) - 10} more")
        await ctx.send("\n".join(lines), ephemeral=True)

    @commands.hybrid_command(
        name="volume",
        description="Set the player volume (0-100)."
    )
    @commands.guild_only()
    @app_commands.describe(percent="Volume percentage (0-100).")
    async def volume(self, ctx: commands.Context, percent: int):
        vc = ctx.voice_client
        if vc is None:
            return await ctx.send(
                "I'm not in a voice channel.",
                ephemeral=True,
            )
        current = int(self._volumes.get(ctx.guild.id, 0.5) * 100)
        delta = max(0, min(percent, 100)) - current
        await self.adjust_volume(ctx.guild, delta)
        await ctx.send(f"Volume set to **{min(max(percent, 0), 100)}%**.", ephemeral=True)

    @commands.hybrid_command(
        name="leave",
        description="Disconnect the bot from voice."
    )
    @commands.guild_only()
    async def leave(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc is None:
            return await ctx.send(
                "I'm not in a voice channel.",
                ephemeral=True,
            )
        await self.stop_playback(ctx.guild, vc)
        await ctx.send("Left the voice channel.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Music(bot))
