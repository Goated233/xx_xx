import discord
from discord.ext import commands
from discord.ui import View, Button
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

# -----------------------------
# GLOBAL STORAGE
# -----------------------------

ALLOWED_WINNERS = set()
LOG_CHANNEL_ID = None

current_giveaway = {
    "message_id": None,
    "channel_id": None,
    "prize": None,
    "entrants": [],
    "all_users": [],
    "host_id": None
}

# -----------------------------
# HOST DM SETTINGS (JSON)
# -----------------------------

HOST_DM_FILE = Path("host_dm_settings.json")
HOST_DM = {}  # {str(user_id): bool}


def load_host_dm():
    global HOST_DM
    if HOST_DM_FILE.exists():
        try:
            with open(HOST_DM_FILE, "r") as f:
                HOST_DM = json.load(f)
        except Exception:
            HOST_DM = {}
    else:
        HOST_DM = {}


def save_host_dm():
    try:
        with open(HOST_DM_FILE, "w") as f:
            json.dump(HOST_DM, f)
    except Exception:
        pass


def host_dm_enabled(uid: int) -> bool:
    return HOST_DM.get(str(uid), True)


def set_host_dm(uid: int, enabled: bool):
    HOST_DM[str(uid)] = enabled
    save_host_dm()


# -----------------------------
# WHITELIST (JSON)
# -----------------------------

WHITELIST_FILE = Path("whitelist.json")
WHITELIST = set()  # set of user IDs


def load_whitelist():
    global WHITELIST
    if WHITELIST_FILE.exists():
        try:
            with open(WHITELIST_FILE, "r") as f:
                data = json.load(f)
                WHITELIST = set(data)
        except Exception:
            WHITELIST = set()
    else:
        WHITELIST = set()


def save_whitelist():
    try:
        with open(WHITELIST_FILE, "w") as f:
            json.dump(list(WHITELIST), f)
    except Exception:
        pass


def is_whitelisted():
    async def predicate(ctx):
        # server owner always allowed
        if ctx.guild is not None and ctx.author.id == ctx.guild.owner_id:
            return True
        return ctx.author.id in WHITELIST
    return commands.check(predicate)


# -----------------------------
# LOGGING HELPERS
# -----------------------------

def get_log_channel():
    if LOG_CHANNEL_ID is None:
        return None
    return bot.get_channel(LOG_CHANNEL_ID)


async def log_event(embed: discord.Embed = None, content: str = None):
    ch = get_log_channel()
    if ch:
        try:
            await ch.send(content=content, embed=embed)
        except Exception:
            pass


async def dm_host(uid: int, embed: discord.Embed = None, content: str = None, important: bool = False):
    if not host_dm_enabled(uid):
        return
    user = bot.get_user(uid)
    if not user:
        return
    try:
        if important and embed is not None:
            await user.send(embed=embed)
        elif content is not None:
            await user.send(content)
    except Exception:
        err = discord.Embed(
            title="Host DM Failed",
            description=f"Could not DM <@{uid}>.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await log_event(embed=err)


# -----------------------------
# BOT READY
# -----------------------------

@bot.event
async def on_ready():
    load_host_dm()
    load_whitelist()
    print(f"Logged in as {bot.user}")
    embed = discord.Embed(
        title="Bot Started",
        description=f"Logged in as {bot.user} ({bot.user.id})",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    await log_event(embed=embed)


# -----------------------------
# WHITELIST COMMANDS
# -----------------------------

@bot.command()
@is_whitelisted()
async def addwl(ctx, user: discord.User):
    """Owner only: add user to whitelist."""
    if ctx.guild is None or ctx.author.id != ctx.guild.owner_id:
        return await ctx.send("Only the server owner can modify the whitelist.")
    WHITELIST.add(user.id)
    save_whitelist()
    await ctx.send(f"Added {user.mention} to the whitelist.")

    embed = discord.Embed(
        title="Whitelist Updated",
        description=f"Added {user.mention} to whitelist.",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    await log_event(embed=embed)


@bot.command()
@is_whitelisted()
async def delwl(ctx, user: discord.User):
    """Owner only: remove user from whitelist."""
    if ctx.guild is None or ctx.author.id != ctx.guild.owner_id:
        return await ctx.send("Only the server owner can modify the whitelist.")
    WHITELIST.discard(user.id)
    save_whitelist()
    await ctx.send(f"Removed {user.mention} from the whitelist.")

    embed = discord.Embed(
        title="Whitelist Updated",
        description=f"Removed {user.mention} from whitelist.",
        color=0xe67e22,
        timestamp=datetime.utcnow()
    )
    await log_event(embed=embed)


# -----------------------------
# ADMIN / CONTROL COMMANDS
# -----------------------------

@bot.command()
@is_whitelisted()
async def addwinner(ctx, user_id: int):
    """Add a user ID to allowed winners."""
    ALLOWED_WINNERS.add(user_id)
    embed = discord.Embed(
        title="Winner ID Added",
        description=f"Added <@{user_id}> (`{user_id}`) to allowed winners.",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)
    await log_event(embed=embed)


@bot.command()
@is_whitelisted()
async def setlog(ctx, channel_id: int):
    """Set log channel by ID."""
    global LOG_CHANNEL_ID
    ch = ctx.guild.get_channel(channel_id)
    if not ch:
        return await ctx.send("Invalid channel ID.")
    LOG_CHANNEL_ID = channel_id
    embed = discord.Embed(
        title="Log Channel Set",
        description=f"Logs will now go to {ch.mention}.",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)
    await log_event(embed=embed)


@bot.command()
@is_whitelisted()
async def togglehostdm(ctx):
    """Toggle your host DM notifications."""
    uid = ctx.author.id
    new_state = not host_dm_enabled(uid)
    set_host_dm(uid, new_state)
    status = "enabled" if new_state else "disabled"
    embed = discord.Embed(
        title="DM Preference Updated",
        description=f"Your giveaway DMs are now **{status}**.",
        color=0x9b59b6,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)
    await log_event(embed=embed)


# -----------------------------
# GIVEAWAY COMMAND
# -----------------------------

@bot.command()
@is_whitelisted()
async def gw(ctx, action=None, duration=None, *, prize=None):
    """Start a giveaway: .gw start <duration> <prize>"""
    if action != "start":
        return await ctx.send("Usage: `.gw start <duration> <prize>`")

    if not duration or not prize:
        return await ctx.send("You must provide a duration and a prize.")

    try:
        num = int(duration[:-1])
        unit = duration[-1]
    except Exception:
        return await ctx.send("Invalid duration format. Example: `1h`, `30m`")

    if unit == "h":
        delta = timedelta(hours=num)
    elif unit == "m":
        delta = timedelta(minutes=num)
    else:
        return await ctx.send("Invalid duration format. Use `h` or `m`.")

    end = datetime.utcnow() + delta
    ts = int(end.timestamp())

    # Old giveaway UI
    embed = discord.Embed(
        title=prize,
        description="React with 🎉 to enter the giveaway.",
        color=0x00ffcc
    )
    embed.add_field(name="Ends:", value=f"<t:{ts}:R> (<t:{ts}:f>)", inline=False)
    embed.add_field(name="Winners:", value="1", inline=True)
    embed.add_field(name="Hosted by:", value=ctx.author.mention, inline=True)

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    current_giveaway["message_id"] = msg.id
    current_giveaway["channel_id"] = msg.channel.id
    current_giveaway["prize"] = prize
    current_giveaway["host_id"] = ctx.author.id
    current_giveaway["entrants"] = []
    current_giveaway["all_users"] = []

    start_embed = discord.Embed(
        title="Giveaway Started",
        color=0x00ffcc,
        timestamp=datetime.utcnow()
    )
    start_embed.add_field(name="Prize", value=prize, inline=False)
    start_embed.add_field(name="Host", value=ctx.author.mention, inline=True)
    start_embed.add_field(name="Message", value=f"[Jump to giveaway]({msg.jump_url})", inline=False)

    await log_event(embed=start_embed)
    await dm_host(ctx.author.id, embed=start_embed, important=True)

    # 1-minute warning
    if delta.total_seconds() > 60:
        await asyncio.sleep(delta.total_seconds() - 60)
        warn = discord.Embed(
            title="Giveaway Ending Soon",
            description="Your giveaway ends in **1 minute**.",
            color=0xf1c40f,
            timestamp=datetime.utcnow()
        )
        warn.add_field(name="Prize", value=prize, inline=False)
        warn.add_field(name="Message", value=f"[Jump to giveaway]({msg.jump_url})", inline=False)
        await log_event(embed=warn)
        await dm_host(current_giveaway["host_id"], embed=warn, important=True)
        await asyncio.sleep(60)
    else:
        await asyncio.sleep(delta.total_seconds())

    # End of giveaway
    ch = bot.get_channel(current_giveaway["channel_id"])
    if not ch:
        err = discord.Embed(
            title="Giveaway Channel Deleted",
            description="The channel containing the giveaway was deleted.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await log_event(embed=err)
        await dm_host(current_giveaway["host_id"], embed=err, important=True)
        return

    try:
        msg = await ch.fetch_message(current_giveaway["message_id"])
    except discord.NotFound:
        err = discord.Embed(
            title="Giveaway Message Deleted",
            description="The giveaway message was deleted.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await log_event(embed=err)
        await dm_host(current_giveaway["host_id"], embed=err, important=True)
        return

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if not reaction:
        await ctx.send("No one entered the giveaway.")
        no_entry = discord.Embed(
            title="Giveaway Ended — No Entries",
            description="Nobody entered the giveaway.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        no_entry.add_field(name="Prize", value=prize, inline=False)
        no_entry.add_field(name="Host", value=f"<@{current_giveaway['host_id']}>", inline=True)
        await log_event(embed=no_entry)
        await dm_host(current_giveaway["host_id"], embed=no_entry, important=True)
        return

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await ctx.send("No valid users entered the giveaway.")
        no_valid = discord.Embed(
            title="Giveaway Ended — No Valid Users",
            description="No valid (non-bot) users entered.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        no_valid.add_field(name="Prize", value=prize, inline=False)
        await log_event(embed=no_valid)
        await dm_host(current_giveaway["host_id"], embed=no_valid, important=True)
        return

    current_giveaway["all_users"] = users
    eligible = [u for u in users if u.id in ALLOWED_WINNERS]
    current_giveaway["entrants"] = eligible

    if eligible:
        winner = random.choice(eligible)
        source = "Allowed Winner ID"
    else:
        winner = random.choice(users)
        source = "Random (no allowed IDs)"

    await ctx.send(f"🎉 {winner.mention} has won the giveaway: **{prize}**")

    joined_list = ", ".join(u.mention for u in users)
    allowed_list = ", ".join(u.mention for u in eligible) if eligible else "None"

    result = discord.Embed(
        title="Giveaway Result",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    result.add_field(name="Prize", value=prize, inline=False)
    result.add_field(name="Winner", value=winner.mention, inline=True)
    result.add_field(name="Winner Source", value=source, inline=True)
    result.add_field(name="Total Entrants", value=str(len(users)), inline=True)
    result.add_field(name="Allowed Entrants", value=str(len(eligible)), inline=True)
    result.add_field(name="Entrants", value=joined_list or "None", inline=False)
    result.add_field(name="Allowed Users", value=allowed_list, inline=False)

    await log_event(embed=result)
    await dm_host(current_giveaway["host_id"], embed=result, important=True)


# -----------------------------
# REROLL COMMAND
# -----------------------------

@bot.command()
@is_whitelisted()
async def reroll(ctx):
    """Reroll the giveaway winner."""
    prize = current_giveaway["prize"]
    users = current_giveaway["all_users"]
    eligible = current_giveaway["entrants"]
    host = current_giveaway["host_id"]

    if not prize or not users:
        return await ctx.send("There is no recent giveaway to reroll.")

    if eligible:
        winner = random.choice(eligible)
        source = "Allowed Winner ID (reroll)"
    else:
        winner = random.choice(users)
        source = "Random (no allowed IDs) (reroll)"

    await ctx.send(f"🔁 {winner.mention} has won the giveaway (reroll): **{prize}**")

    joined_list = ", ".join(u.mention for u in users)
    allowed_list = ", ".join(u.mention for u in eligible) if eligible else "None"

    embed = discord.Embed(
        title="Giveaway Rerolled",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="New Winner", value=winner.mention, inline=True)
    embed.add_field(name="Winner Source", value=source, inline=True)
    embed.add_field(name="Entrants", value=joined_list or "None", inline=False)
    embed.add_field(name="Allowed Users", value=allowed_list, inline=False)

    await log_event(embed=embed)
    await dm_host(host, embed=embed, important=True)


# -----------------------------
# REACTION LOGGING
# -----------------------------

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    if str(reaction.emoji) != "🎉":
        return

    if current_giveaway["message_id"] is None:
        return
    if reaction.message.id != current_giveaway["message_id"]:
        return

    status = "Allowed Winner ID" if user.id in ALLOWED_WINNERS else "Normal Entrant"

    embed = discord.Embed(
        title="🎉 Entry Added",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Message", value=f"[Jump]({reaction.message.jump_url})", inline=False)
    await log_event(embed=embed)

    host_id = current_giveaway["host_id"]
    text = f"🎉 Entry added: {user.mention} ({status})"
    await dm_host(host_id, content=text, important=False)


@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot:
        return

    if str(reaction.emoji) != "🎉":
        return

    if current_giveaway["message_id"] is None:
        return
    if reaction.message.id != current_giveaway["message_id"]:
        return

    status = "Allowed Winner ID" if user.id in ALLOWED_WINNERS else "Normal Entrant"

    embed = discord.Embed(
        title="❌ Entry Removed",
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Message", value=f"[Jump]({reaction.message.jump_url})", inline=False)
    await log_event(embed=embed)

    host_id = current_giveaway["host_id"]
    text = f"❌ Entry removed: {user.mention} ({status})"
    await dm_host(host_id, content=text, important=False)


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
    await log_event(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    embed = discord.Embed(
        title="Command Error",
        description=f"Error: `{error}`",
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=ctx.author.mention, inline=True)
    if ctx.command:
        embed.add_field(name="Command", value=ctx.command.qualified_name, inline=True)
    await log_event(embed=embed)
    await ctx.send("An error occurred while running that command.")


# -----------------------------
# HELP COMMAND WITH EMOJI BUTTONS
# -----------------------------

class HelpMenu(View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Giveaway", emoji="🎉", style=discord.ButtonStyle.primary)
    async def giveaway_cmds(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="🎉 Giveaway Commands",
            color=0x00ffcc
        )
        embed.add_field(
            name=".gw start <time> <prize>",
            value="Start a giveaway. Example: `.gw start 10m Nitro`",
            inline=False
        )
        embed.add_field(
            name=".reroll",
            value="Reroll the last giveaway winner.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Admin", emoji="🛠️", style=discord.ButtonStyle.secondary)
    async def admin_cmds(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="🛠️ Admin Commands",
            color=0x3498db
        )
        embed.add_field(
            name=".setlog <channel_id>",
            value="Set the log channel where all logs are sent.",
            inline=False
        )
        embed.add_field(
            name=".addwinner <user_id>",
            value="Add a user ID to the allowed winners list.",
            inline=False
        )
        embed.add_field(
            name=".togglehostdm",
            value="Toggle whether you receive DMs for giveaway events.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Whitelist", emoji="🔐", style=discord.ButtonStyle.success)
    async def whitelist_cmds(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="🔐 Whitelist Commands",
            color=0x2ecc71
        )
        embed.add_field(
            name=".addwl <user>",
            value="Owner only: add a user to the whitelist.",
            inline=False
        )
        embed.add_field(
            name=".delwl <user>",
            value="Owner only: remove a user from the whitelist.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="📘 Giveaway Bot Help",
        description="Use the buttons below to view command categories.",
        color=0x5865F2
    )
    embed.set_footer(text="Only whitelisted users (or server owner) can use commands.")
    view = HelpMenu()
    await ctx.send(embed=embed, view=view)


# -----------------------------
# RUN BOT
# -----------------------------

bot.run(os.getenv("TOKEN"))
