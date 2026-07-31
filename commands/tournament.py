import json
import os
import re

import discord
from discord import app_commands
from discord.ext import commands

TIMESTAMP_RE = re.compile(r"<t:(\d+):[a-zA-Z]>")


# ==========================
# CONFIGURATION
# ==========================

TOURNAMENT_CHANNEL_ID = 1532575772496363674

STAFF_ROLES = [
    1532569640318931015,  # Moderator
    1532569676901646346,  # Administrator
]

DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tournaments.json",
)


# ==========================
# HELPERS
# ==========================

def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ==========================
# TOURNAMENT VIEW
# ==========================

class TournamentView(discord.ui.View):

    def __init__(self, games, votes=None):
        super().__init__(timeout=None)

        self.games = games
        self.votes = {int(k): v for k, v in (votes or {}).items()}
        self.channel_id = None

        for index, game in enumerate(games):
            self.add_item(
                TournamentButton(game, index)
            )

    def persist(self, message_id):
        data = load_data()
        data[str(message_id)] = {
            "channel_id": self.channel_id,
            "games": self.games,
            "votes": {str(k): v for k, v in self.votes.items()},
        }
        save_data(data)


# ==========================
# TOURNAMENT BUTTON
# ==========================

class TournamentButton(discord.ui.Button):

    def __init__(self, game, index):
        super().__init__(
            label=game,
            style=discord.ButtonStyle.secondary,
            custom_id=f"tournament_vote_{index}"
        )

        self.game = game

    async def callback(self, interaction: discord.Interaction):

        view = self.view

        # Record / change vote
        view.votes[interaction.user.id] = self.game

        view.persist(interaction.message.id)

        total_votes = len(view.votes)

        results = []

        for game in view.games:

            votes = list(
                view.votes.values()
            ).count(game)

            percentage = 0

            if total_votes > 0:
                percentage = round(
                    (votes / total_votes) * 100
                )

            results.append(
                f"**{game}**\n{votes} Votes • {percentage}%"
            )

        embed = discord.Embed(
            title="Tournament Voting",
            description=(
                "A tournament has been scheduled.\n\n"
                "Select the game you would like to compete in.\n"
                "Your vote can be changed at any time."
            ),
            color=discord.Color.red()
        )

        embed.add_field(
            name="Game Options",
            value="\n\n".join(results),
            inline=False
        )

        embed.add_field(
            name="Status",
            value="Voting Open",
            inline=True
        )

        embed.set_footer(
            text=f"Total Votes: {total_votes}"
        )

        await interaction.message.edit(
            embed=embed,
            view=view
        )

        await interaction.response.send_message(
            f"Your vote has been recorded for **{self.game}**.",
            ephemeral=True
        )


# ==========================
# COMMAND
# ==========================

class Tournament(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        data = load_data()
        for message_id, panel in data.items():
            view = TournamentView(panel["games"], panel.get("votes", {}))
            view.channel_id = panel.get("channel_id")
            self.bot.add_view(view, message_id=int(message_id))

    @app_commands.command(
        name="tournament",
        description="Create a tournament voting panel."
    )
    @app_commands.describe(
        timestamp="Start time as a Discord timestamp like <t:1785474780:F> from hammertime.cyou",
        game1="First game option",
        game2="Second game option",
        game3="Third game option",
        game4="Fourth game option"
    )
    async def tournament(
        self,
        interaction: discord.Interaction,
        timestamp: str,
        game1: str,
        game2: str,
        game3: str,
        game4: str
    ):

        match = TIMESTAMP_RE.search(timestamp)

        if match:
            timestamp = match.group(1)
        elif not timestamp.strip().isdigit():
            return await interaction.response.send_message(
                "Timestamp must be a UNIX number or a Discord timestamp "
                "like `<t:1785474780:F>`.",
                ephemeral=True
            )

        ts = int(timestamp)

        # Permission Check

        if not any(
            role.id in STAFF_ROLES
            for role in interaction.user.roles
        ):
            return await interaction.response.send_message(
                "You do not have permission to create tournaments.",
                ephemeral=True
            )

        channel = interaction.guild.get_channel(
            TOURNAMENT_CHANNEL_ID
        )

        if channel is None:
            return await interaction.response.send_message(
                "Tournament channel could not be found.",
                ephemeral=True
            )

        games = [
            game1,
            game2,
            game3,
            game4
        ]

        embed = discord.Embed(
            title="Tournament Voting",
            description=f"""
A new tournament has been scheduled.

**Tournament Date**
<t:{ts}:F>

**Tournament Time**
<t:{ts}:t>

**Starts In**
<t:{ts}:R>

Select the game you would like to compete in.
""",
            color=discord.Color.red()
        )

        embed.add_field(
            name="Game Options",
            value="\n".join(
                f"**{game}**\n0 Votes • 0%"
                for game in games
            ),
            inline=False
        )

        embed.add_field(
            name="Created By",
            value=interaction.user.mention,
            inline=True
        )

        embed.add_field(
            name="Status",
            value="Voting Open",
            inline=True
        )

        if interaction.guild.icon:
            embed.set_thumbnail(
                url=interaction.guild.icon.url
            )

        embed.set_footer(
            text=f"{interaction.guild.name} • Tournament"
        )

        view = TournamentView(games)
        view.channel_id = channel.id

        message = await channel.send(
            embed=embed,
            view=view
        )

        view.persist(message.id)
        self.bot.add_view(view, message_id=message.id)

        await interaction.response.send_message(
            "Tournament voting has been created.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(
        Tournament(bot)
    )
