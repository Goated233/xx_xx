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
bot.remove_command("help")  # IMPORTANT FIX

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
            HOST_DM = json.load(open(HOST_DM_FILE, "r"))
        except:
            HOST_DM = {}
    else:
        HOST_DM = {}

def save_host_dm():
    json.dump(HOST_DM, open(HOST_DM_FILE, "w"))

def host_dm_enabled(uid: int) -> bool:
    return HOST_DM.get(str(uid), True)

def set_host_dm(uid: int, enabled: bool):
    HOST_DM[str(uid)] = enabled
    save_host_dm()

# -----------------------------
# WHITELIST (JSON)
# -----------------------------

WHITELIST_FILE = Path("whitelist.json")
WHITELIST = set()

def load_whitelist():
    global WHITELIST
    if WHITELIST_FILE.exists():
        try:
            WHITELIST = set(json.load(open(WHITELIST_FILE, "r")))
        except:
            WHITELIST = set()
    else:
        WHITELIST = set()

def save_whitelist():
    json.dump(list(WHITELIST), open(WHITELIST_FILE, "w"))

def is_whitelisted():
    async def predicate(ctx):
        if ctx.guild and ctx.author.id == ctx.guild.owner_id:
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

async def log_event(embed=None, content=None):
    ch = get_log_channel()
    if ch:
        try:
            await ch.send(content=content, embed=embed)
        except:
            pass

async def dm_host(uid: int, embed=None, content=None, important=False):
    if not host_dm_enabled(uid):
        return
    user = bot.get_user(uid)
    if not user:
        return
    try:
        if important and embed:
            await user.send(embed=embed)
        elif content:
            await user.send(content)
    except:
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
        description=f"Logged in as {bot.user}",
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
    if ctx.author.id != ctx.guild.owner_id:
        return await ctx.send("Only the server owner can modify the whitelist.")
    WHITELIST.add(user.id)
    save_whitelist()
    await ctx.send(f"Added {user.mention} to whitelist.")

@bot.command()
@is_whitelisted()
async def delwl(ctx, user: discord.User):
    if ctx.author.id != ctx.guild.owner_id:
        return await ctx.send("Only the server owner can modify the whitelist.")
    WHITELIST.discard(user.id)
    save_whitelist()
    await ctx.send(f"Removed {user.mention} from whitelist.")

# -----------------------------
# ADMIN COMMANDS
# -----------------------------

@bot.command()
@is_whitelisted()
async def addwinner(ctx, user_id: int):
    ALLOWED_WINNERS.add(user_id)
    embed = discord.Embed(
        title="Winner ID Added",
        description=f"Added <@{user_id}>",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)
    await log_event(embed=embed)

@bot.command()
@is_whitelisted()
async def setlog(ctx, channel_id: int):
    global LOG_CHANNEL_ID
    ch = ctx.guild.get_channel(channel_id)
    if not ch:
        return await ctx.send("Invalid channel ID.")
    LOG_CHANNEL_ID = channel_id
    embed = discord.Embed(
        title="Log Channel Set",
        description=f"Logs will go to {ch.mention}",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    await ctx.send(embed=embed)
    await log_event(embed=embed)

@bot.command()
@is_whitelisted()
async def togglehostdm(ctx):
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
    if action != "start":
        return await ctx.send("Usage: `.gw start <duration> <prize>`")

    if not duration or not prize:
        return await ctx.send("Missing duration or prize.")

    try:
        num = int(duration[:-1])
        unit = duration[-1]
    except:
        return await ctx.send("Invalid duration format.")

    if unit == "h":
        delta = timedelta(hours=num)
    elif unit == "m":
        delta = timedelta(minutes=num)
    else:
        return await ctx.send("Use `h` or `m`.")

    end = datetime.utcnow() + delta
    ts = int(end.timestamp())

    embed = discord.Embed(
        title=prize,
        description="React with 🎉 to enter.",
        color=0x00ffcc
    )
    embed.add_field(name="Ends:", value=f"<t:{ts}:R> (<t:{ts}:f>)", inline=False)
    embed.add_field(name="Winners:", value="1", inline=True)
    embed.add_field(name="Hosted by:", value=ctx.author.mention, inline=True)

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    current_giveaway.update({
        "message_id": msg.id,
        "channel_id": msg.channel.id,
        "prize": prize,
        "host_id": ctx.author.id,
        "entrants": [],
        "all_users": []
    })

    start_embed = discord.Embed(
        title="Giveaway Started",
        color=0x00ffcc,
        timestamp=datetime.utcnow()
    )
    start_embed.add_field(name="Prize", value=prize)
    start_embed.add_field(name="Host", value=ctx.author.mention)
    start_embed.add_field(name="Message", value=f"[Jump]({msg.jump_url})")

    await log_event(embed=start_embed)
    await dm_host(ctx.author.id, embed=start_embed, important=True)

    # 1-minute warning
    if delta.total_seconds() > 60:
        await asyncio.sleep(delta.total_seconds() - 60)
        warn = discord.Embed(
            title="Giveaway Ending Soon",
            description="Ends in **1 minute**.",
            color=0xf1c40f,
            timestamp=datetime.utcnow()
        )
        warn.add_field(name="Prize", value=prize)
        await log_event(embed=warn)
        await dm_host(current_giveaway["host_id"], embed=warn, important=True)
        await asyncio.sleep(60)
    else:
        await asyncio.sleep(delta.total_seconds())

    # END
    ch = bot.get_channel(current_giveaway["channel_id"])
    if not ch:
        err = discord.Embed(
            title="Giveaway Channel Deleted",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await log_event(embed=err)
        await dm_host(current_giveaway["host_id"], embed=err, important=True)
        return

    try:
        msg = await ch.fetch_message(current_giveaway["message_id"])
    except:
        err = discord.Embed(
            title="Giveaway Message Deleted",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await log_event(embed=err)
        await dm_host(current_giveaway["host_id"], embed=err, important=True)
        return

    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    if not reaction:
        await ctx.send("No one entered.")
        no_entry = discord.Embed(
            title="No Entries",
            description="Nobody entered the giveaway.",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await log_event(embed=no_entry)
        await dm_host(current_giveaway["host_id"], embed=no_entry, important=True)
        return

    users = [u async for u in reaction.users() if not u.bot]
    if not users:
        await ctx.send("No valid users.")
        no_valid = discord.Embed(
            title="No Valid Users",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
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
        source = "Random"

    await ctx.send(f"🎉 {winner.mention} won **{prize}**")

    result = discord.Embed(
        title="Giveaway Result",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    result.add_field(name="Prize", value=prize)
    result.add_field(name="Winner", value=winner.mention)
    result.add_field(name="Source", value=source)

    await log_event(embed=result)
    await dm_host(current_giveaway["host_id"], embed=result, important=True)

# -----------------------------
# REROLL
# -----------------------------

@bot.command()
@is_whitelisted()
async def reroll(ctx):
    prize = current_giveaway["prize"]
    users = current_giveaway["all_users"]
    eligible = current_giveaway["entrants"]
    host = current_giveaway["host_id"]

    if not prize or not users:
        return await ctx.send("No giveaway to reroll.")

    if eligible:
        winner = random.choice(eligible)
        source = "Allowed Winner ID (reroll)"
    else:
        winner = random.choice(users)
        source = "Random (reroll)"

    await ctx.send(f"🔁 {winner.mention} won **{prize}**")

    embed = discord.Embed(
        title="Giveaway Rerolled",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Prize", value=prize)
    embed.add_field(name="Winner", value=winner.mention)
    embed.add_field(name="Source", value=source)

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
    if reaction.message.id != current_giveaway["message_id"]:
        return

    status = "Allowed Winner ID" if user.id in ALLOWED_WINNERS else "Normal Entrant"

    embed = discord.Embed(
        title="🎉 Entry Added",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Status", value=status)
    await log_event(embed=embed)

    await dm_host(current_giveaway["host_id"], content=f"🎉 Entry added: {user.mention} ({status})")

@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot:
        return
    if str(reaction.emoji) != "🎉":
        return
    if reaction.message.id != current_giveaway["message_id"]:
        return

    status = "Allowed Winner ID" if user.id in ALLOWED_WINNERS else "Normal Entrant"

    embed = discord.Embed(
        title="❌ Entry Removed",
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention)
    embed.add_field(name="Status", value=status)
    await log_event(embed=embed)

    await dm_host(current_giveaway["host_id"], content=f"❌ Entry removed: {user.mention} ({status})")

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
        description=str(error),
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    await log_event(embed=embed)
    await ctx.send("An error occurred.")
# -----------------------------
# HELP MENU WITH EMOJI BUTTONS
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
        embed.add_field(name=".gw start <time> <prize>", value="Start a giveaway.", inline=False)
        embed.add_field(name=".reroll", value="Reroll the last giveaway.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Admin", emoji="🛠️", style=discord.ButtonStyle.secondary)
    async def admin_cmds(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="🛠️ Admin Commands",
            color=0x3498db
        )
        embed.add_field(name=".setlog <channel_id>", value="Set log channel.", inline=False)
        embed.add_field(name=".addwinner <user_id>", value="Add allowed winner ID.", inline=False)
        embed.add_field(name=".togglehostdm", value="Toggle host DM notifications.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Whitelist", emoji="🔐", style=discord.ButtonStyle.success)
    async def whitelist_cmds(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="🔐 Whitelist Commands",
            color=0x2ecc71
        )
        embed.add_field(name=".addwl <user>", value="Owner only: add user to whitelist.", inline=False)
        embed.add_field(name=".delwl <user>", value="Owner only: remove user from whitelist.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="📘 Giveaway Bot Help",
        description="Use the buttons below to view command categories.",
        color=0x5865F2
    )
    embed.set_footer(text="Only whitelisted users (or server owner) can use commands.")
    await ctx.send(embed=embed, view=HelpMenu())

# -----------------------------
# RUN BOT
# -----------------------------

bot.run(os.getenv("TOKEN"))
