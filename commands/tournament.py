import discord
from discord import app_commands
from discord.ext import commands


# ==========================
# CONFIGURATION
# ==========================

TOURNAMENT_CHANNEL_ID = 1532575772496363674

STAFF_ROLES = [
    1532569640318931015,  # Moderator
    1532569676901646346   # Administrator
]


# ==========================
# TOURNAMENT VIEW
# ==========================

class TournamentView(discord.ui.View):

    def __init__(self, games):
        super().__init__(timeout=None)

        self.games = games
        self.votes = {}

        for index, game in enumerate(games):
            self.add_item(
                TournamentButton(game, index)
            )


# ==========================
# TOURNAMENT BUTTON
# ==========================

class TournamentButton(discord.ui.Button):

    def __init__(self, game, index):
        super().__init__(
            label=game,
            style=discord.ButtonStyle.primary,
            custom_id=f"tournament_vote_{index}"
        )

        self.game = game


    async def callback(self, interaction: discord.Interaction):

        view = self.view


        # Remove old vote
        if interaction.user.id in view.votes:
            del view.votes[interaction.user.id]


        # Add new vote
        view.votes[interaction.user.id] = self.game


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



    @app_commands.command(
        name="tournament",
        description="Create a tournament voting panel."
    )

    @app_commands.describe(
        date="Tournament date",
        time="Tournament time",
        game1="First game option",
        game2="Second game option",
        game3="Third game option",
        game4="Fourth game option"
    )


    async def tournament(
        self,
        interaction: discord.Interaction,
        date: str,
        time: str,
        game1: str,
        game2: str,
        game3: str,
        game4: str
    ):


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
{date}

**Tournament Time**
{time}

Select the game you would like to compete in.
""",
            color=discord.Color.red()
        )


        embed.add_field(
            name="Game Options",
            value=f"""
**{game1}**
0 Votes • 0%

**{game2}**
0 Votes • 0%

**{game3}**
0 Votes • 0%

**{game4}**
0 Votes • 0%
""",
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


        embed.set_thumbnail(
            url=interaction.guild.icon.url
            if interaction.guild.icon
            else None
        )


        embed.set_footer(
            text=f"{interaction.guild.name} • Tournament"
        )


        view = TournamentView(games)


        await channel.send(
            embed=embed,
            view=view
        )


        await interaction.response.send_message(
            "Tournament voting has been created.",
            ephemeral=True
        )



async def setup(bot):

    await bot.add_cog(
        Tournament(bot)
    )
