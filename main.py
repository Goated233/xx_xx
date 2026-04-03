import discord
from discord.ext import commands
import asyncio
import random
from datetime import datetime, timedelta
import os

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True

bot = commands.Bot(command_prefix=".", intents=intents)

# IDs allowed to win
ALLOWED_WINNERS = {
    123456789012345678,
    987654321098765432,
    112233445566778899
}

# Store giveaway data for rerolls
current_giveaway = {
    "message_id": None,
    "prize": None,
    "entrants": []
}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def gw(ctx, action=None, duration=None, *, prize=None):
    if action != "start":
        return await ctx.send("Usage: `.gw start <duration> <prize>`")

    # Parse duration like 1h, 30m
    try:
        time_amount = int(duration[:-1])
        unit = duration[-1]
    except:
        return await ctx.send("Invalid duration format.")

    if unit == "h":
        delta = timedelta(hours=time_amount)
    elif unit == "m":
        delta = timedelta(minutes=time_amount)
    else:
        return await ctx.send("Invalid duration format. Use h or m.")

    end_time = datetime.utcnow() + delta
    end_ts = int(end_time.timestamp())

    embed = discord.Embed(
        title=f"{prize}",
        description="React with 🎉 to enter the giveaway.",
        color=0x00ffcc
    )

    embed.add_field(name="Ends:", value=f"<t:{end_ts}:R> (<t:{end_ts}:f>)", inline=False)
    embed.add_field(name="Winners:", value="1", inline=True)
    embed.add_field(name="Hosted by:", value=ctx.author.mention, inline=True)

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    # Save giveaway info
    current_giveaway["message_id"] = msg.id
    current_giveaway["prize"] = prize

    # Wait for giveaway to end
    await asyncio.sleep(delta.total_seconds())

    # Fetch updated message
    msg = await ctx.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")

    if not reaction:
        return await ctx.send("No one entered the giveaway.")

    users = await reaction.users().flatten()
    users = [u for u in users if not u.bot]

    # Filter ONLY allowed IDs
    eligible = [u for u in users if u.id in ALLOWED_WINNERS]

    # Save entrants for reroll
    current_giveaway["entrants"] = eligible

    if not eligible:
        return await ctx.send("No eligible users entered the giveaway.")

    winner = random.choice(eligible)

    await ctx.send(f"{winner.mention} has won the giveaway: **{prize}**")


@bot.command()
async def reroll(ctx):
    """Reroll the giveaway winner (only from allowed IDs)."""
    if not current_giveaway["entrants"]:
        return await ctx.send("No eligible entrants to reroll from.")

    winner = random.choice(current_giveaway["entrants"])
    prize = current_giveaway["prize"]

    await ctx.send(f"{winner.mention} has won the giveaway: **{prize}**")


# Run bot
bot.run(os.getenv("TOKEN"))
