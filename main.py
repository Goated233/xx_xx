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

# Dynamic IDs allowed to win (managed via .addwinner)
ALLOWED_WINNERS = set()

# Log channel ID (set via .setlog)
LOG_CHANNEL_ID = None

# Store giveaway data for rerolls
current_giveaway = {
    "message_id": None,
    "prize": None,
    "entrants": [],
    "all_users": [],
    "host_id": None
}


def get_log_channel():
    if LOG_CHANNEL_ID is None:
        return None
    return bot.get_channel(LOG_CHANNEL_ID)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


# -----------------------------
# ADMIN COMMANDS
# -----------------------------

@bot.command()
async def addwinner(ctx, user_id: int):
    """Add a user ID to the allowed winners list."""
    ALLOWED_WINNERS.add(user_id)
    await ctx.send(
        embed=discord.Embed(
            title="Winner ID Added",
            description=f"Added <@{user_id}> (`{user_id}`) to the allowed winners list.",
            color=0x2ecc71
        )
    )


@bot.command()
async def setlog(ctx, channel_id: int):
    """Set the log channel by ID."""
    global LOG_CHANNEL_ID
    channel = ctx.guild.get_channel(channel_id)
    if channel is None:
        return await ctx.send(
            embed=discord.Embed(
                title="Invalid Channel",
                description="I can't find that channel. Make sure the ID is correct.",
                color=0xe74c3c
            )
        )
    LOG_CHANNEL_ID = channel_id
    await ctx.send(
        embed=discord.Embed(
            title="Log Channel Set",
            description=f"Logs will now be sent to {channel.mention}.",
            color=0x3498db
        )
    )


# -----------------------------
# GIVEAWAY COMMAND
# -----------------------------

@bot.command()
async def gw(ctx, action=None, duration=None, *, prize=None):
    if action != "start":
        return await ctx.send("Usage: `.gw start <duration> <prize>`")

    if duration is None or prize is None:
        return await ctx.send("You must provide a duration and a prize.")

    # Parse duration like 1h, 30m
    try:
        time_amount = int(duration[:-1])
        unit = duration[-1]
    except:
        return await ctx.send("Invalid duration format. Example: `1h`, `30m`")

    if unit == "h":
        delta = timedelta(hours=time_amount)
    elif unit == "m":
        delta = timedelta(minutes=time_amount)
    else:
        return await ctx.send("Invalid duration format. Use `h` or `m`.")

    end_time = datetime.utcnow() + delta
    end_ts = int(end_time.timestamp())

    # CLEAN GIVEAWAY UI
    embed = discord.Embed(
        title="🎉 Giveaway",
        description=f"React with 🎉 to enter!\n\n**Prize:** `{prize}`",
        color=0x5865F2  # Discord blurple
    )
    embed.add_field(name="Ends", value=f"<t:{end_ts}:R> (`<t:{end_ts}:f>`)", inline=False)
    embed.add_field(name="Winners", value="1", inline=True)
    embed.add_field(name="Hosted by", value=ctx.author.mention, inline=True)
    embed.set_footer(text="Good luck!")

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    # Save giveaway info
    current_giveaway["message_id"] = msg.id
    current_giveaway["prize"] = prize
    current_giveaway["host_id"] = ctx.author.id
    current_giveaway["entrants"] = []
    current_giveaway["all_users"] = []

    # Log giveaway start
    log_channel = get_log_channel()
    if log_channel:
        start_embed = discord.Embed(
            title="Giveaway Started",
            color=0x5865F2,
            timestamp=datetime.utcnow()
        )
        start_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        start_embed.add_field(name="Host", value=ctx.author.mention, inline=True)
        start_embed.add_field(name="Duration", value=f"`{duration}`", inline=True)
        start_embed.add_field(name="Message", value=f"[Jump to giveaway]({msg.jump_url})", inline=False)
        await log_channel.send(embed=start_embed)

    # Wait for giveaway to end
    await asyncio.sleep(delta.total_seconds())

    # Fetch updated message
    msg = await ctx.channel.fetch_message(msg.id)
    reaction = discord.utils.get(msg.reactions, emoji="🎉")

    if not reaction:
        await ctx.send("No one entered the giveaway.")
        if log_channel:
            embed = discord.Embed(
                title="Giveaway Ended — No Entries",
                color=0xe74c3c,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
            await log_channel.send(
                content=f"<@{current_giveaway['host_id']}> No one joined your giveaway.",
                embed=embed
            )
        return

    # Correct way to fetch users (no flatten)
    users = [u async for u in reaction.users() if not u.bot]

    if not users:
        await ctx.send("No valid users entered the giveaway.")
        if log_channel:
            embed = discord.Embed(
                title="Giveaway Ended — No Valid Users",
                color=0xe74c3c,
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
            await log_channel.send(
                content=f"<@{current_giveaway['host_id']}> No valid users joined.",
                embed=embed
            )
        return

    # Save all users for fallback + reroll
    current_giveaway["all_users"] = users

    # Filter ONLY allowed IDs
    eligible = [u for u in users if u.id in ALLOWED_WINNERS]
    current_giveaway["entrants"] = eligible

    # Winner selection logic
    if eligible:
        winner = random.choice(eligible)
        winner_source = "Allowed Winner ID"
    else:
        winner = random.choice(users)
        winner_source = "Random (no allowed IDs)"

    # Announce winner publicly
    await ctx.send(f"🎉 {winner.mention} has won the giveaway: **{prize}**")

    # Log result
    if log_channel:
        joined_list = ", ".join(u.mention for u in users)
        allowed_list = ", ".join(u.mention for u in eligible) if eligible else "None"

        result_embed = discord.Embed(
            title="Giveaway Result",
            color=0x2ecc71,
            timestamp=datetime.utcnow()
        )
        result_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        result_embed.add_field(name="Winner", value=winner.mention, inline=True)
        result_embed.add_field(name="Winner Source", value=winner_source, inline=True)
        result_embed.add_field(name="Total Entrants", value=str(len(users)), inline=True)
        result_embed.add_field(name="Allowed Entrants", value=str(len(eligible)), inline=True)
        result_embed.add_field(name="Entrants", value=joined_list, inline=False)
        result_embed.add_field(name="Allowed Users", value=allowed_list, inline=False)

        if not eligible:
            await log_channel.send(
                content=f"<@{current_giveaway['host_id']}> No allowed winner IDs reacted.",
                embed=result_embed
            )
        else:
            await log_channel.send(embed=result_embed)


# -----------------------------
# REROLL COMMAND
# -----------------------------

@bot.command()
async def reroll(ctx):
    """Reroll the giveaway winner with same logic."""
    prize = current_giveaway["prize"]
    users = current_giveaway["all_users"]
    eligible = current_giveaway["entrants"]
    host_id = current_giveaway["host_id"]

    if not prize or not users:
        return await ctx.send("There is no recent giveaway to reroll.")

    if eligible:
        winner = random.choice(eligible)
        winner_source = "Allowed Winner ID (reroll)"
    else:
        winner = random.choice(users)
        winner_source = "Random (no allowed IDs) (reroll)"

    await ctx.send(f"🔁 {winner.mention} has won the giveaway (reroll): **{prize}**")

    log_channel = get_log_channel()
    if log_channel:
        joined_list = ", ".join(u.mention for u in users)
        allowed_list = ", ".join(u.mention for u in eligible) if eligible else "None"

        embed = discord.Embed(
            title="Giveaway Rerolled",
            color=0x3498db,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        embed.add_field(name="New Winner", value=winner.mention, inline=True)
        embed.add_field(name="Winner Source", value=winner_source, inline=True)
        embed.add_field(name="Entrants", value=joined_list, inline=False)
        embed.add_field(name="Allowed Users", value=allowed_list, inline=False)

        if not eligible:
            await log_channel.send(
                content=f"<@{host_id}> No allowed winner IDs reacted (reroll).",
                embed=embed
            )
        else:
            await log_channel.send(embed=embed)


# Run bot
bot.run(os.getenv("TOKEN"))
