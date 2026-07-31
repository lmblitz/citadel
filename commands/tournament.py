import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

TOURNAMENT_CHANNEL_ID = 1532575772496363674

STAFF_ROLES = [
    1532569640318931015,
    1532569676901646346
]


class TournamentView(discord.ui.View):

    def __init__(self, games):
        super().__init__(timeout=None)

        self.games = games
        self.votes = {}

        for index, game in enumerate(games):
            self.add_item(
                TournamentButton(
                    game,
                    index
                )
            )


class TournamentButton(discord.ui.Button):

    def __init__(self, game, index):
        super().__init__(
            label=game,
            style=discord.ButtonStyle.primary,
            custom_id=f"tournament_{index}"
        )

        self.game = game


    async def callback(self, interaction: discord.Interaction):

        view = self.view


        # Remove previous vote
        if interaction.user.id in view.votes:
            del view.votes[interaction.user.id]


        # Add new vote
        view.votes[interaction.user.id] = self.game


        total_votes = len(view.votes)


        results = []


        for game in view.games:

            amount = list(
                view.votes.values()
            ).count(game)


            percentage = (
                round(
                    (amount / total_votes) * 100
                )
                if total_votes > 0
                else 0
            )


            results.append(
                f"**{game}**\n{amount} Votes • {percentage}%"
            )


        container = discord.ui.Container(

            discord.ui.TextDisplay(
                "# Tournament Voting"
            ),


            discord.ui.Separator(),


            discord.ui.TextDisplay(
                """
A tournament has been scheduled.

Select the game you would like to compete in.
Your vote can be changed at any time.
"""
            ),


            discord.ui.Separator(),


            discord.ui.TextDisplay(
                "# Game Options\n\n"
                +
                "\n\n".join(results)
            ),


            discord.ui.Separator(),


            discord.ui.TextDisplay(
                """
**Status**
Voting Open
"""
            )

        )


        await interaction.message.edit(
            components=[
                container,
                view
            ],
            flags=discord.MessageFlags.is_components_v2()
        )


        await interaction.response.send_message(
            f"Your vote has been recorded for **{self.game}**.",
            ephemeral=True
        )





class Tournament(commands.Cog):

    def __init__(self, bot):
        self.bot = bot



    @app_commands.command(
        name="tournament",
        description="Create a tournament vote."
    )

    @app_commands.describe(

        date="Tournament date",

        time="Tournament time",

        game1="First game",

        game2="Second game",

        game3="Third game",

        game4="Fourth game"

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


        # Staff Check

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
                "Tournament channel not found.",
                ephemeral=True
            )



        games = [

            game1,
            game2,
            game3,
            game4

        ]



        container = discord.ui.Container(

            discord.ui.TextDisplay(
                "# Tournament Voting"
            ),


            discord.ui.Separator(),


            discord.ui.TextDisplay(

f"""
A new tournament has been scheduled.

**Tournament Date**
{date}

**Tournament Time**
{time}
"""

            ),


            discord.ui.Separator(),


            discord.ui.TextDisplay(

f"""
# Game Options

**{game1}**
0 Votes • 0%

**{game2}**
0 Votes • 0%

**{game3}**
0 Votes • 0%

**{game4}**
0 Votes • 0%
"""

            ),


            discord.ui.Separator(),


            discord.ui.TextDisplay(

f"""
**Created By**
{interaction.user.mention}

**Status**
Voting Open
"""

            )

        )



        view = TournamentView(
            games
        )



        await channel.send(

            components=[

                container,

                view

            ],

            flags=discord.MessageFlags.is_components_v2()

        )



        await interaction.response.send_message(

            "Tournament voting has been created.",

            ephemeral=True

        )



async def setup(bot):

    await bot.add_cog(
        Tournament(bot)
    )
