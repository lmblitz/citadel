import json
import os
import re

import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route

DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "automod.json",
)

NON_LATIN_RE = re.compile(
    "[\u0400-\u04FF"          # Cyrillic
    "\u0590-\u05FF"           # Hebrew
    "\u0600-\u06FF"           # Arabic
    "\u0750-\u077F"           # Arabic Supplement
    "\u0900-\u097F"           # Devanagari
    "\u0E00-\u0E7F"           # Thai
    "\u10A0-\u10FF"           # Georgian
    "\u3040-\u309F"           # Hiragana
    "\u30A0-\u30FF"           # Katakana
    "\u4E00-\u9FFF"           # CJK
    "\uAC00-\uD7AF"           # Hangul
    "]"
)

LATIN_RE = re.compile("[A-Za-z\u00C0-\u024F]")

DM_MESSAGE = (
    "Your message was removed by automated moderation. "
    "Please review the server rules before posting again."
)

PRESET_RULES = {
    "Profanity": [1],
    "Harassment": [4],
    "Slurs": [3],
    "Sexual Content": [2],
}

TRIGGER_TYPES = {
    1: "Keyword",
    2: "Harmful Link",
    3: "Spam",
    4: "Mention Spam",
    5: "Keyword Preset",
    6: "Member Profile",
    7: "Mention Raid Protection",
}


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Automod(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def get_config(self, guild_id):
        return load_data().get(str(guild_id), {})

    def set_config(self, guild_id, config):
        data = load_data()
        data[str(guild_id)] = config
        save_data(data)

    async def rule_request(self, method, guild_id, rule_id=None, **kwargs):
        path = "/guilds/{guild_id}/auto-moderation/rules"
        if rule_id is not None:
            path += "/{rule_id}"
            kwargs["rule_id"] = rule_id
        return await self.bot.http.request(
            Route(method, path, guild_id=guild_id),
            **kwargs,
        )

    @staticmethod
    def dm_embed(member, reason, content):
        embed = discord.Embed(
            title="Message Removed",
            description=reason,
            color=discord.Color.red(),
        )
        if content:
            embed.add_field(
                name="Your Message",
                value=content[:1024] if content else "*(empty)*",
                inline=False,
            )
        embed.set_footer(text=f"Automod • {member.guild.name}")
        return embed

    async def remove_and_notify(self, message, reason):
        embed = self.dm_embed(message.author, reason, message.content)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            await message.author.send(embed=embed)
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.author.bot:
            return

        config = self.get_config(message.guild.id)
        if not config.get("english_only", False):
            return

        author = message.author
        if isinstance(author, discord.Member) and (
            author.guild_permissions.manage_messages
            or author.guild_permissions.moderate_members
        ):
            return

        content = message.content
        if not content:
            return

        latin = len(LATIN_RE.findall(content))
        non_latin = len(NON_LATIN_RE.findall(content))

        if non_latin > 0 and non_latin > latin:
            await self.remove_and_notify(
                message,
                "This is an English-speaking community. "
                "Please keep your messages in English so everyone can participate.",
            )

    # ==========================
    # COMMANDS
    # ==========================

    automod = app_commands.Group(
        name="automod",
        description="Manage the server's auto moderation.",
    )

    @automod.command(
        name="setup",
        description="Create the default Discord AutoMod rules.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        config = self.get_config(interaction.guild_id)
        rules = config.setdefault("rules", {})
        created = []

        for name, presets in PRESET_RULES.items():
            if name in rules:
                continue

            payload = {
                "name": name,
                "event_type": 1,
                "trigger": {"type": 5, "presets": presets},
                "actions": [
                    {"type": 1, "metadata": {}},
                    {"type": 5, "metadata": {"custom_message": DM_MESSAGE}},
                ],
                "enabled": True,
            }

            try:
                data = await self.rule_request(
                    "POST", interaction.guild_id, json=payload
                )
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"Failed to create rule **{name}**: {e}",
                    ephemeral=True,
                )
                continue

            rules[name] = {"rule_id": data["id"], "type": "preset"}
            created.append(name)

        if "Mention Spam" not in rules:
            payload = {
                "name": "Mention Spam",
                "event_type": 1,
                "trigger": {"type": 4, "mention_limit": 5},
                "actions": [{"type": 1, "metadata": {}}],
                "enabled": True,
            }

            try:
                data = await self.rule_request(
                    "POST", interaction.guild_id, json=payload
                )
            except discord.HTTPException as e:
                await interaction.followup.send(
                    f"Failed to create rule **Mention Spam**: {e}",
                    ephemeral=True,
                )
            else:
                rules["Mention Spam"] = {"rule_id": data["id"], "type": "mention_spam"}
                created.append("Mention Spam")

        self.set_config(interaction.guild_id, config)

        await interaction.followup.send(
            f"Automod setup complete. Created {len(created)} new rule(s).",
            ephemeral=True,
        )

    @automod.command(
        name="addrule",
        description="Add a custom keyword rule to AutoMod.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        name="Name of the rule.",
        keywords="Words to filter, separated by commas or spaces.",
    )
    async def addrule(
        self,
        interaction: discord.Interaction,
        name: str,
        keywords: str,
    ):
        words = [w.strip().lower() for w in re.split(r"[,;|\s]+", keywords) if w.strip()]

        if not words:
            return await interaction.response.send_message(
                "You need to provide at least one keyword.",
                ephemeral=True,
            )

        payload = {
            "name": name,
            "event_type": 1,
            "trigger": {"type": 1, "keyword_filter": words[:1000]},
            "actions": [
                {"type": 1, "metadata": {}},
                {"type": 5, "metadata": {"custom_message": DM_MESSAGE}},
            ],
            "enabled": True,
        }

        try:
            data = await self.rule_request(
                "POST", interaction.guild_id, json=payload
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"Failed to create rule **{name}**: {e}",
                ephemeral=True,
            )

        config = self.get_config(interaction.guild_id)
        config.setdefault("rules", {})[name] = {
            "rule_id": data["id"],
            "type": "keyword",
            "keywords": words[:1000],
        }
        self.set_config(interaction.guild_id, config)

        await interaction.response.send_message(
            f"Rule **{name}** created with {len(words[:1000])} keyword(s).",
            ephemeral=True,
        )

    @automod.command(
        name="removerule",
        description="Remove one of the AutoMod rules created by this bot.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        name="Name of the rule to remove."
    )
    async def removerule(
        self,
        interaction: discord.Interaction,
        name: str,
    ):
        config = self.get_config(interaction.guild_id)
        rules = config.get("rules", {})

        if name not in rules:
            return await interaction.response.send_message(
                "No AutoMod rule with that name was created by this bot.",
                ephemeral=True,
            )

        try:
            await self.rule_request(
                "DELETE", interaction.guild_id, rule_id=rules[name]["rule_id"]
            )
        except discord.HTTPException as e:
            return await interaction.response.send_message(
                f"Failed to remove rule **{name}**: {e}",
                ephemeral=True,
            )

        del rules[name]
        self.set_config(interaction.guild_id, config)

        await interaction.response.send_message(
            f"Rule **{name}** has been removed.",
            ephemeral=True,
        )

    @automod.command(
        name="rules",
        description="List the server's active AutoMod rules.",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def rules(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            data = await self.rule_request(
                "GET", interaction.guild_id
            )
        except discord.HTTPException as e:
            return await interaction.followup.send(
                f"Failed to fetch rules: {e}",
                ephemeral=True,
            )

        config = self.get_config(interaction.guild_id)

        embed = discord.Embed(
            title="AutoMod Rules",
            description=f"{interaction.guild.name}",
            color=discord.Color.red(),
        )

        if not data:
            embed.add_field(
                name="No Rules",
                value="No AutoMod rules are active.",
                inline=False,
            )
        else:
            for rule in data:
                status = "Enabled" if rule.get("enabled") else "Disabled"
                trigger_type = TRIGGER_TYPES.get(rule.get("trigger_type"), "Unknown")
                embed.add_field(
                    name=rule.get("name", "Unknown"),
                    value=f"{status} • {trigger_type}",
                    inline=False,
                )

        embed.add_field(
            name="English-Only Filter",
            value="Enabled" if config.get("english_only") else "Disabled",
            inline=False,
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @automod.command(
        name="english",
        description="Toggle the English-only message filter.",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        enabled="True to enable, False to disable."
    )
    async def english(
        self,
        interaction: discord.Interaction,
        enabled: bool,
    ):
        config = self.get_config(interaction.guild_id)
        config["english_only"] = enabled
        self.set_config(interaction.guild_id, config)

        await interaction.response.send_message(
            f"English-only filter is now {'enabled' if enabled else 'disabled'}.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Automod(bot))
