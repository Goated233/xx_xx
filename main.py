import discord
from discord.ext import commands
import asyncio
import random
from datetime import datetime, timedelta
import os
import json
from pathlib import Path

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=".", intents=intents)

# Dynamic IDs allowed to win (managed via .addwinner)
ALLOWED_WINNERS = set()

# Log channel ID (set via .setlog)
LOG_CHANNEL_ID = None

# Store giveaway data for rerolls and reaction tracking
current_giveaway = {
    "message_id": None,
    "channel_id": None,
    "prize": None,
    "entrants": [],
    "all_users": [],
    "host_id": None
}

# Host DM settings persistence
HOST_DM_SETTINGS_FILE = Path("host_dm_settings.json")
HOST_DM_SETTINGS = {}  # {host_id: {"dm_enabled": bool}}


def load_host_dm_settings():
    global HOST_DM_SETTINGS
    if HOST_DM_SETTINGS_FILE.exists():
        try:
            with open(HOST_DM_SETTINGS_FILE, "r") as f:
                HOST_DM_SETTINGS = json.load(f)
        except Exception:
            HOST_DM_SETTINGS = {}
    else:
        HOST_DM_SETTINGS = {}


def save_host_dm_settings():
    try:
        with open(HOST_DM_SETTINGS_FILE, "w") as f:
            json.dump(HOST_DM_SETTINGS, f)
    except Exception:
        pass


def is_host_dm_enabled(host_id: int) -> bool:
    data = HOST_DM_SETTINGS.get(str(host_id))
    if data is None:
        return True  # default: enabled
    return data.get("dm_enabled", True)


def set_host_dm_enabled(host_id: int, enabled: bool):
    HOST_DM_SETTINGS[str(host_id)] = {"dm_enabled": enabled}
    save_host_dm_settings()


def get_log_channel():
    if LOG_CHANNEL_ID is None:
        return None
    return bot.get_channel(LOG_CHANNEL_ID)


async def send_log(embed: discord.Embed = None, content: str = None):
    log_channel = get_log_channel()
    if log_channel:
        try:
            await log_channel.send(content=content, embed=embed)
        except Exception:
            pass


async def send_host_dm(host_id: int, embed: discord.Embed = None, content: str = None, important: bool = False):
    if not is_host_dm_enabled(host_id):
        return
    host = bot.get_user(host_id)
    if host is None:
        return
    try:
        if important and embed is not None:
            await host.send(embed=embed)
        elif content is not None:
            await host.send(content)
    except Exception:
        # Can't DM host, log it
        err_embed = discord.Embed(
            title="Host DM Failed",
            description=f"Could not DM host `<@{host_id}>`.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await send_log(embed=err_embed)


@bot.event
async def on_ready():
    load_host_dm_settings()
    print(f"Logged in as {bot.user}")
    embed = discord.Embed(
        title="Bot Started",
        description=f"Logged in as {bot.user} ({bot.user.id})",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    await send_log(embed=embed)


# -----------------------------
# ADMIN / CONTROL COMMANDS
# -----------------------------

@bot.command()
async def addwinner(ctx, user_id: int):
    """Add a user ID to the allowed winners list."""
    ALLOWED_WINNERS.add(user_id)

    embed = discord.Embed(
        title="Winner ID Added",
        description=f"Added <@{user_id}> (`{user_id}`) to the allowed winners list.",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)

    log_embed = discord.Embed(
        title="Allowed Winner ID Added",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    log_embed.add_field(name="Added By", value=ctx.author.mention, inline=True)
    log_embed.add_field(name="User", value=f"<@{user_id}> (`{user_id}`)", inline=True)
    await send_log(embed=log_embed)


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
    embed = discord.Embed(
        title="Log Channel Set",
        description=f"Logs will now be sent to {channel.mention}.",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)

    log_embed = discord.Embed(
        title="Log Channel Updated",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    log_embed.add_field(name="Set By", value=ctx.author.mention, inline=True)
    log_embed.add_field(name="Channel", value=channel.mention, inline=True)
    await send_log(embed=log_embed)


@bot.command()
async def togglehostdm(ctx):
    """Toggle whether you (as host) receive DMs for giveaway events."""
    host_id = ctx.author.id
    current = is_host_dm_enabled(host_id)
    new_state = not current
    set_host_dm_enabled(host_id, new_state)

    status = "enabled" if new_state else "disabled"
    embed = discord.Embed(
        title="Host DM Preference Updated",
        description=f"Your giveaway DMs are now **{status}**.",
        color=0x9b59b6,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)

    log_embed = discord.Embed(
        title="Host DM Toggled",
        color=0x9b59b6,
        timestamp=datetime.utcnow()
    )
    log_embed.add_field(name="Host", value=ctx.author.mention, inline=True)
    log_embed.add_field(name="New State", value=status, inline=True)
    await send_log(embed=log_embed)


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
    except Exception:
        return await ctx.send("Invalid duration format. Example: `1h`, `30m`")

    if unit == "h":
        delta = timedelta(hours=time_amount)
    elif unit == "m":
        delta = timedelta(minutes=time_amount)
    else:
        return await ctx.send("Invalid duration format. Use `h` or `m`.")

    end_time = datetime.utcnow() + delta
    end_ts = int(end_time.timestamp())

    # OLD GIVEAWAY UI
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
    current_giveaway["channel_id"] = msg.channel.id
    current_giveaway["prize"] = prize
    current_giveaway["host_id"] = ctx.author.id
    current_giveaway["entrants"] = []
    current_giveaway["all_users"] = []

    # Log giveaway start
    start_embed = discord.Embed(
        title="Giveaway Started",
        color=0x00ffcc,
        timestamp=datetime.utcnow()
    )
    start_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
    start_embed.add_field(name="Host", value=ctx.author.mention, inline=True)
    start_embed.add_field(name="Duration", value=f"`{duration}`", inline=True)
    start_embed.add_field(name="Message", value=f"[Jump to giveaway]({msg.jump_url})", inline=False)
    await send_log(embed=start_embed)
    await send_host_dm(ctx.author.id, embed=start_embed, important=True)

    # 1-MINUTE HOST WARNING
    if delta.total_seconds() > 60:
        await asyncio.sleep(delta.total_seconds() - 60)

        warn_embed = discord.Embed(
            title="Giveaway Ending Soon",
            description="Your giveaway ends in **1 minute**.",
            color=0xf1c40f,
            timestamp=datetime.utcnow()
        )
        warn_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        warn_embed.add_field(name="Message", value=f"[Jump to giveaway]({msg.jump_url})", inline=False)

        await send_log(embed=warn_embed)
        await send_host_dm(current_giveaway["host_id"], embed=warn_embed, important=True)

        await asyncio.sleep(60)
    else:
        await asyncio.sleep(delta.total_seconds())

    # END OF GIVEAWAY
    # Check if message or channel still exists
    channel = bot.get_channel(current_giveaway["channel_id"])
    if channel is None:
        deleted_embed = discord.Embed(
            title="Giveaway Channel Deleted",
            description="The channel containing the giveaway was deleted before it ended.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        deleted_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        await send_log(embed=deleted_embed)
        await send_host_dm(current_giveaway["host_id"], embed=deleted_embed, important=True)
        return

    try:
        msg = await channel.fetch_message(current_giveaway["message_id"])
    except discord.NotFound:
        deleted_embed = discord.Embed(
            title="Giveaway Message Deleted",
            description="The giveaway message was deleted before it ended.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        deleted_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        await send_log(embed=deleted_embed)
        await send_host_dm(current_giveaway["host_id"], embed=deleted_embed, important=True)
        return

    reaction = discord.utils.get(msg.reactions, emoji="🎉")

    # Nobody reacted at all
    if not reaction:
        await ctx.send("No one entered the giveaway.")

        no_entry_embed = discord.Embed(
            title="Giveaway Ended — No Entries",
            description="Nobody entered the giveaway.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        no_entry_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        no_entry_embed.add_field(name="Host", value=f"<@{current_giveaway['host_id']}>", inline=True)
        await send_log(embed=no_entry_embed)
        await send_host_dm(current_giveaway["host_id"], embed=no_entry_embed, important=True)
        return

    # Fetch users properly
    users = [u async for u in reaction.users() if not u.bot]

    # No valid users
    if not users:
        await ctx.send("No valid users entered the giveaway.")

        no_valid_embed = discord.Embed(
            title="Giveaway Ended — No Valid Users",
            description="No valid users entered.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        no_valid_embed.add_field(name="Prize", value=f"`{prize}`", inline=False)
        await send_log(embed=no_valid_embed)
        await send_host_dm(current_giveaway["host_id"], embed=no_valid_embed, important=True)
        return

    # Save all users
    current_giveaway["all_users"] = users

    # Allowed ID filtering
    eligible = [u for u in users if u.id in ALLOWED_WINNERS]
    current_giveaway["entrants"] = eligible

    # Winner logic
    if eligible:
        winner = random.choice(eligible)
        winner_source = "Allowed Winner ID"
    else:
        winner = random.choice(users)
        winner_source = "Random (no allowed IDs)"

    await ctx.send(f"🎉 {winner.mention} has won the giveaway: **{prize}**")

    # Log result
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
    result_embed.add_field(name="Entrants", value=joined_list or "None", inline=False)
    result_embed.add_field(name="Allowed Users", value=allowed_list, inline=False)

    await send_log(embed=result_embed)
    await send_host_dm(current_giveaway["host_id"], embed=result_embed, important=True)


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
    embed.add_field(name="Entrants", value=joined_list or "None", inline=False)
    embed.add_field(name="Allowed Users", value=allowed_list, inline=False)

    await send_log(embed=embed)
    await send_host_dm(host_id, embed=embed, important=True)


# -----------------------------
# REACTION LOGGING
# -----------------------------

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        # Log bot reactions too (ignored for giveaway, but logged)
        embed = discord.Embed(
            title="Bot Reaction Detected",
            color=0x95a5a6,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Bot", value=user.mention, inline=True)
        embed.add_field(name="Emoji", value=str(reaction.emoji), inline=True)
        embed.add_field(name="Message", value=f"[Jump]({reaction.message.jump_url})", inline=False)
        await send_log(embed=embed)
        return

    if str(reaction.emoji) != "🎉":
        return

    # Only care about current giveaway message
    if current_giveaway["message_id"] is None:
        return
    if reaction.message.id != current_giveaway["message_id"]:
        return

    # Log to channel
    embed = discord.Embed(
        title="🎉 Entry Added",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Message", value=f"[Jump]({reaction.message.jump_url})", inline=True)
    status = "Allowed Winner ID" if user.id in ALLOWED_WINNERS else "Normal Entrant"
    embed.add_field(name="Status", value=status, inline=False)
    await send_log(embed=embed)

    # DM host (spam events = text)
    host_id = current_giveaway["host_id"]
    text = f"🎉 Entry added: {user.mention} ({status})"
    await send_host_dm(host_id, content=text, important=False)


@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot:
        embed = discord.Embed(
            title="Bot Reaction Removed",
            color=0x95a5a6,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Bot", value=user.mention, inline=True)
        embed.add_field(name="Emoji", value=str(reaction.emoji), inline=True)
        embed.add_field(name="Message", value=f"[Jump]({reaction.message.jump_url})", inline=False)
        await send_log(embed=embed)
        return

    if str(reaction.emoji) != "🎉":
        return

    if current_giveaway["message_id"] is None:
        return
    if reaction.message.id != current_giveaway["message_id"]:
        return

    embed = discord.Embed(
        title="❌ Entry Removed",
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Message", value=f"[Jump]({reaction.message.jump_url})", inline=True)
    status = "Allowed Winner ID" if user.id in ALLOWED_WINNERS else "Normal Entrant"
    embed.add_field(name="Status", value=status, inline=False)
    await send_log(embed=embed)

    host_id = current_giveaway["host_id"]
    text = f"❌ Entry removed: {user.mention} ({status})"
    await send_host_dm(host_id, content=text, important=False)


# -----------------------------
# ERROR LOGGING
# -----------------------------

@bot.event
async def on_error(event, *args, **kwargs):
    embed = discord.Embed(
        title="Unhandled Error",
        description=f"Event: `{event}`",
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    await send_log(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(
        title="Command Error",
        description=f"Error: `{error}`",
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=ctx.author.mention, inline=True)
    embed.add_field(name="Command", value=ctx.command.qualified_name if ctx.command else "Unknown", inline=True)
    await send_log(embed=embed)
    await ctx.send("An error occurred while running that command.")


# Run bot
bot.run(os.getenv("TOKEN"))
