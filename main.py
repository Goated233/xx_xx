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
    1435635557035278377,
    987654321098765432,
    112233445566778899
}

# Store giveaway data for rerolls
current_giveaway = {
    "message_id": None,
    "prize": None,
    "entrants": [],
    "all_users": []
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

    # NEW: Correct way to fetch users (no flatten)
    users = [u async for u in reaction.users() if not u.bot]

    # Save all users for fallback + reroll
    current_giveaway["all_users"] = users

    # Filter ONLY allowed IDs
    eligible = [u for u in users if u.id in ALLOWED_WINNERS]

    # Save eligible entrants for reroll
    current_giveaway["entrants"] = eligible

    # Winner selection logic
    if eligible:
        winner = random.choice(eligible)
    else:
        winner = random.choice(users)

    await ctx.send(f"{winner.mention} has won the giveaway: **{prize}**")


@bot.command()
async def reroll(ctx):
    """Reroll the giveaway winner with same logic."""
    prize = current_giveaway["prize"]
    users = current_giveaway["all_users"]
    eligible = current_giveaway["entrants"]

    if not users:
        return await ctx.send("No one entered the giveaway.")

    # Same logic as original draw
    if eligible:
        winner = random.choice(eligible)
    else:
        winner = random.choice(users)

    await ctx.send(f"{winner.mention} has won the giveaway: **{prize}**")


# Run bot
bot.run(os.getenv("TOKEN"))
