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

bot = commands.Bot(command_prefix="-", intents=intents)
bot.remove_command("help")

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
    "host_id": None,
    "start_time": None,
    "winners": [],
    "winner_count": 1,
}

# -----------------------------
# FILE PATHS
# -----------------------------

BASE = Path(".")
HOST_DM_FILE = BASE / "host_dm_settings.json"
WHITELIST_FILE = BASE / "whitelist.json"
PROFILES_FILE = BASE / "profiles.json"
HISTORY_FILE = BASE / "history.json"
SEASONS_FILE = BASE / "seasons.json"
HOST_STATS_FILE = BASE / "host_stats.json"
REQUIREMENTS_FILE = BASE / "requirements.json"

# -----------------------------
# IN-MEMORY DATA
# -----------------------------

HOST_DM = {}
WHITELIST = set()
PROFILES = {}
HISTORY = []
SEASONS = {}
HOST_STATS = {}
REQUIREMENTS = {}

# -----------------------------
# JSON HELPERS
# -----------------------------

def load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path: Path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# -----------------------------
# HOST DM SETTINGS
# -----------------------------

def load_host_dm():
    global HOST_DM
    HOST_DM = load_json(HOST_DM_FILE, {})

def save_host_dm():
    save_json(HOST_DM_FILE, HOST_DM)

def host_dm_enabled(uid: int) -> bool:
    return HOST_DM.get(str(uid), True)

def set_host_dm(uid: int, enabled: bool):
    HOST_DM[str(uid)] = enabled
    save_host_dm()

# -----------------------------
# WHITELIST
# -----------------------------

def load_whitelist():
    global WHITELIST
    data = load_json(WHITELIST_FILE, [])
    WHITELIST = set(data)

def save_whitelist():
    save_json(WHITELIST_FILE, list(WHITELIST))

def is_whitelisted():
    async def predicate(ctx):
        if ctx.guild and ctx.author.id == ctx.guild.owner_id:
            return True
        return ctx.author.id in WHITELIST
    return commands.check(predicate)

# -----------------------------
# PROFILES / HISTORY / SEASONS / HOST STATS / REQUIREMENTS
# -----------------------------

def load_profiles():
    global PROFILES
    PROFILES = load_json(PROFILES_FILE, {})

def save_profiles():
    save_json(PROFILES_FILE, PROFILES)

def load_history():
    global HISTORY
    HISTORY = load_json(HISTORY_FILE, [])

def save_history():
    save_json(HISTORY_FILE, HISTORY)

def load_seasons():
    global SEASONS
    SEASONS = load_json(SEASONS_FILE, {"current_season": 1, "seasons": {}})

def save_seasons():
    save_json(SEASONS_FILE, SEASONS)

def load_host_stats():
    global HOST_STATS
    HOST_STATS = load_json(HOST_STATS_FILE, {})

def save_host_stats():
    save_json(HOST_STATS_FILE, HOST_STATS)

def load_requirements():
    global REQUIREMENTS
    REQUIREMENTS = load_json(REQUIREMENTS_FILE, {
        "min_account_days": None,
        "min_join_days": None,
        "required_role_id": None,
        "forbidden_role_id": None,
    })

def save_requirements():
    save_json(REQUIREMENTS_FILE, REQUIREMENTS)

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
# FORENSIC / COSMIC LOG HELPERS
# -----------------------------

def get_member_from_reaction(reaction, user):
    guild = reaction.message.guild
    if not guild:
        return None
    return guild.get_member(user.id)

def compute_suspicion_score(user: discord.User, member: discord.Member | None, reaction_time: float | None):
    score = 0
    reasons = []
    now = datetime.utcnow()

    account_age_days = (now - user.created_at.replace(tzinfo=None)).days
    if account_age_days < 7:
        score += 30
        reasons.append("New account (<7 days)")
    elif account_age_days < 30:
        score += 15
        reasons.append("Young account (<30 days)")

    if member and member.joined_at:
        join_age_days = (now - member.joined_at.replace(tzinfo=None)).days
        if join_age_days < 3:
            score += 25
            reasons.append("Recently joined server (<3 days)")
        elif join_age_days < 14:
            score += 10
            reasons.append("New member (<14 days)")

    if reaction_time is not None:
        if reaction_time < 0.5:
            score += 25
            reasons.append(f"Very fast reaction ({reaction_time:.2f}s)")
        elif reaction_time < 2:
            score += 10
            reasons.append(f"Fast reaction ({reaction_time:.2f}s)")

    uid = str(user.id)
    profile = PROFILES.get(uid, {})
    entries = profile.get("entries", 0)
    wins = profile.get("wins", 0)

    if entries > 50 and wins == 0:
        score += 5
        reasons.append("Many entries, no wins")
    if wins > 5:
        score += 10
        reasons.append("Multiple wins")

    score = min(score, 100)
    return score, reasons

def update_profile_on_entry(user: discord.User, reaction_time: float | None):
    uid = str(user.id)
    profile = PROFILES.get(uid, {
        "entries": 0,
        "wins": 0,
        "avg_reaction": None,
        "fastest_reaction": None,
        "last_entry": None,
        "last_suspicion_score": None,
        "last_suspicion_reasons": [],
    })
    profile["entries"] += 1
    profile["last_entry"] = datetime.utcnow().isoformat()

    if reaction_time is not None:
        if profile["avg_reaction"] is None:
            profile["avg_reaction"] = reaction_time
        else:
            profile["avg_reaction"] = (profile["avg_reaction"] + reaction_time) / 2

        if profile["fastest_reaction"] is None or reaction_time < profile["fastest_reaction"]:
            profile["fastest_reaction"] = reaction_time

    PROFILES[uid] = profile
    save_profiles()

def update_profile_on_win(user: discord.User):
    uid = str(user.id)
    profile = PROFILES.get(uid, {
        "entries": 0,
        "wins": 0,
        "avg_reaction": None,
        "fastest_reaction": None,
        "last_entry": None,
        "last_suspicion_score": None,
        "last_suspicion_reasons": [],
    })
    profile["wins"] += 1
    PROFILES[uid] = profile
    save_profiles()

def record_giveaway_history(data: dict):
    HISTORY.append(data)
    if len(HISTORY) > 50:
        HISTORY.pop(0)
    save_history()

def get_current_season():
    return SEASONS.get("current_season", 1)

def update_season_on_win(user: discord.User):
    season = str(get_current_season())
    seasons = SEASONS.setdefault("seasons", {})
    sdata = seasons.setdefault(season, {"wins": {}})
    wins = sdata["wins"]
    wins[str(user.id)] = wins.get(str(user.id), 0) + 1
    save_seasons()

def update_host_stats_on_giveaway(host_id: int, entrants_count: int):
    uid = str(host_id)
    stats = HOST_STATS.get(uid, {
        "giveaways_hosted": 0,
        "total_entrants": 0,
    })
    stats["giveaways_hosted"] += 1
    stats["total_entrants"] += entrants_count
    HOST_STATS[uid] = stats
    save_host_stats()

async def log_chaos_index(user: discord.User, suspicion: int, reaction_time: float | None):
    chaos = suspicion
    if reaction_time is not None:
        if reaction_time < 1:
            chaos += 10
        elif reaction_time > 5:
            chaos += 3
    chaos = min(100, chaos)
    embed = discord.Embed(
        title="🌪️ Chaos Index Spike",
        color=0x9b59b6,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Chaos Added", value=f"+{chaos}", inline=True)
    await log_event(embed=embed)

async def log_probability_distortion(user: discord.User, profile_entries: int):
    shift = min(30, max(1, profile_entries // 5))
    embed = discord.Embed(
        title="🧲 Probability Distortion",
        color=0x1abc9c,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Field Shift", value=f"+{shift:.1f} units", inline=True)
    await log_event(embed=embed)

async def log_pattern_break(user: discord.User, reaction_time: float | None):
    if reaction_time is None:
        return
    profile = PROFILES.get(str(user.id), {})
    avg = profile.get("avg_reaction")
    if avg is None:
        return
    if abs(reaction_time - avg) > 3:
        embed = discord.Embed(
            title="🧩 Pattern Break Detected",
            color=0xe67e22,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="New Reaction", value=f"{reaction_time:.2f}s", inline=True)
        embed.add_field(name="Usual Avg", value=f"{avg:.2f}s", inline=True)
        await log_event(embed=embed)

async def log_giveaway_temperature():
    users = current_giveaway.get("all_users", [])
    count = len(users)
    if count <= 5:
        temp = "COLD"
    elif count <= 20:
        temp = "WARM"
    elif count <= 60:
        temp = "HOT"
    else:
        temp = "OVERHEATED"
    embed = discord.Embed(
        title="🔥 Giveaway Temperature",
        color=0xe74c3c,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Temperature", value=temp, inline=True)
    embed.add_field(name="Entrants", value=str(count), inline=True)
    await log_event(embed=embed)

async def log_shadow_influence():
    users = current_giveaway.get("all_users", [])
    high_risk = 0
    for u in users:
        p = PROFILES.get(str(u.id), {})
        s = p.get("last_suspicion_score", 0)
        if s >= 70:
            high_risk += 1
    if high_risk == 0:
        return
    level = min(100, high_risk * 10)
    embed = discord.Embed(
        title="🌑 Shadow Influence Rising",
        color=0x2c3e50,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="High-Risk Entrants", value=str(high_risk), inline=True)
    embed.add_field(name="Shadow Level", value=f"{level}%", inline=True)
    await log_event(embed=embed)

async def log_surge():
    users = current_giveaway.get("all_users", [])
    if len(users) < 5:
        return
    embed = discord.Embed(
        title="⚡ Entry Surge",
        color=0xf1c40f,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Entrants So Far", value=str(len(users)), inline=True)
    await log_event(embed=embed)

async def log_cognitive_load():
    users = current_giveaway.get("all_users", [])
    if not users:
        return
    scores = []
    for u in users:
        p = PROFILES.get(str(u.id), {})
        s = p.get("last_suspicion_score", 0)
        scores.append(s)
    if not scores:
        return
    variance = max(scores) - min(scores)
    if variance < 20:
        level = "LOW"
    elif variance < 40:
        level = "MEDIUM"
    else:
        level = "HIGH"
    embed = discord.Embed(
        title="🧠 Cognitive Load",
        color=0x8e44ad,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Level", value=level, inline=True)
    embed.add_field(name="Suspicion Spread", value=f"{variance}", inline=True)
    await log_event(embed=embed)

async def log_reality_shift(predicted_top, winner):
    if not predicted_top:
        return
    top_user, _ = predicted_top
    shift = 0 if top_user.id == winner.id else random.randint(20, 60)
    embed = discord.Embed(
        title="🪐 Reality Shift",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Predicted Path", value=top_user.mention, inline=True)
    embed.add_field(name="Actual Winner", value=winner.mention, inline=True)
    embed.add_field(name="Deviation", value=f"{shift}%", inline=True)
    await log_event(embed=embed)

async def log_freeze_break(user: discord.User):
    p = PROFILES.get(str(user.id), {})
    last = p.get("last_entry")
    if not last:
        return
    try:
        last_dt = datetime.fromisoformat(last)
    except Exception:
        return
    days = (datetime.utcnow() - last_dt).days
    if days >= 30:
        embed = discord.Embed(
            title="🧊 Freeze Break",
            color=0x5dade2,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Days Since Last Entry", value=str(days), inline=True)
        await log_event(embed=embed)

async def log_instability():
    users = current_giveaway.get("all_users", [])
    if len(users) < 3:
        return
    scores = []
    for u in users:
        p = PROFILES.get(str(u.id), {})
        s = p.get("last_suspicion_score", 0)
        scores.append(s)
    if not scores:
        return
    variance = max(scores) - min(scores)
    if variance < 30:
        return
    embed = discord.Embed(
        title="🧨 Instability Rising",
        color=0xc0392b,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Suspicion Variance", value=str(variance), inline=True)
    await log_event(embed=embed)

async def log_fate_echo(user: discord.User):
    p = PROFILES.get(str(user.id), {})
    entries = p.get("entries", 0)
    wins = p.get("wins", 0)
    if entries >= 10 and wins == 0:
        strength = min(100, entries * 3)
        embed = discord.Embed(
            title="🧿 Fate Echo",
            color=0x16a085,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Echo Strength", value=f"{strength}%", inline=True)
        await log_event(embed=embed)

# -----------------------------
# REQUIREMENTS CHECK
# -----------------------------

def passes_requirements(member: discord.Member | None, user: discord.User):
    if not any(REQUIREMENTS.values()):
        return True, None

    now = datetime.utcnow()

    min_acc = REQUIREMENTS.get("min_account_days")
    if min_acc is not None:
        age_days = (now - user.created_at.replace(tzinfo=None)).days
        if age_days < min_acc:
            return False, f"Account too new (<{min_acc} days)"

    min_join = REQUIREMENTS.get("min_join_days")
    if min_join is not None and member and member.joined_at:
        join_days = (now - member.joined_at.replace(tzinfo=None)).days
        if join_days < min_join:
            return False, f"Joined server too recently (<{min_join} days)"

    req_role_id = REQUIREMENTS.get("required_role_id")
    if req_role_id is not None and member:
        if not any(r.id == req_role_id for r in member.roles):
            return False, "Missing required role"

    forb_role_id = REQUIREMENTS.get("forbidden_role_id")
    if forb_role_id is not None and member:
        if any(r.id == forb_role_id for r in member.roles):
            return False, "Has forbidden role"

    return True, None

# -----------------------------
# BOT READY
# -----------------------------

@bot.event
async def on_ready():
    load_host_dm()
    load_whitelist()
    load_profiles()
    load_history()
    load_seasons()
    load_host_stats()
    load_requirements()
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
    if ctx.guild is None or ctx.author.id != ctx.guild.owner_id:
        return await ctx.send("Only the server owner can modify the whitelist.")
    WHITELIST.add(user.id)
    save_whitelist()
    await ctx.send(f"Added {user.mention} to the whitelist.")

@bot.command()
@is_whitelisted()
async def delwl(ctx, user: discord.User):
    if ctx.guild is None or ctx.author.id != ctx.guild.owner_id:
        return await ctx.send("Only the server owner can modify the whitelist.")
    WHITELIST.discard(user.id)
    save_whitelist()
    await ctx.send(f"Removed {user.mention} from the whitelist.")

# -----------------------------
# ADMIN / CONTROL COMMANDS
# -----------------------------

@bot.command()
@is_whitelisted()
async def addwinner(ctx, user_id: int):
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
async def winnerlist(ctx):
    if not ALLOWED_WINNERS:
        return await ctx.send("No allowed winners set.")
    embed = discord.Embed(
        title="Allowed Winners",
        color=0x1abc9c,
        timestamp=datetime.utcnow()
    )
    lines = []
    for uid in ALLOWED_WINNERS:
        lines.append(f"<@{uid}> (`{uid}`)")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Total: {len(ALLOWED_WINNERS)}")
    await ctx.send(embed=embed)

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
        description=f"Logs will now go to {ch.mention}.",
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
# REQUIREMENT COMMANDS
# -----------------------------

@bot.command()
@is_whitelisted()
async def setminaccount(ctx, days: int | None = None):
    REQUIREMENTS["min_account_days"] = days
    save_requirements()
    await ctx.send(f"Minimum account age set to: {days} days" if days is not None else "Minimum account age requirement cleared.")

@bot.command()
@is_whitelisted()
async def setminjoin(ctx, days: int | None = None):
    REQUIREMENTS["min_join_days"] = days
    save_requirements()
    await ctx.send(f"Minimum server join age set to: {days} days" if days is not None else "Minimum join age requirement cleared.")

@bot.command()
@is_whitelisted()
async def setreqrole(ctx, role: discord.Role | None = None):
    REQUIREMENTS["required_role_id"] = role.id if role else None
    save_requirements()
    await ctx.send(f"Required role set to: {role.mention}" if role else "Required role cleared.")

@bot.command()
@is_whitelisted()
async def setforbidrole(ctx, role: discord.Role | None = None):
    REQUIREMENTS["forbidden_role_id"] = role.id if role else None
    save_requirements()
    await ctx.send(f"Forbidden role set to: {role.mention}" if role else "Forbidden role cleared.")

# -----------------------------
# MULTI-GIVEAWAY START (FIXED)
# -----------------------------

@bot.command(name="start")
@is_whitelisted()
async def start_multi(ctx, amount: int, duration: str, *, prize: str):
    if amount < 1 or amount > 10:
        return await ctx.send("Amount must be between 1 and 10.")
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

    for _ in range(amount):
        await gw(ctx, "start", duration, prize_and_winners=prize)
        await asyncio.sleep(1)

# -----------------------------
# GIVEAWAY COMMAND (MULTI-WINNER)
# -----------------------------

@bot.command()
@is_whitelisted()
async def gw(ctx, action=None, duration=None, *, prize_and_winners=None):
    if action != "start":
        return await ctx.send("Usage: `-gw start <duration> <prize> [winners]`")

    if not duration or not prize_and_winners:
        return await ctx.send("You must provide a duration and a prize.")

    parts = prize_and_winners.split()
    winner_count = 1
    if parts[-1].isdigit():
        winner_count = max(1, min(10, int(parts[-1])))
        prize = " ".join(parts[:-1])
    else:
        prize = prize_and_winners

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

    embed = discord.Embed(
        title=prize,
        description="React with 🎉 to enter the giveaway.",
        color=0x00ffcc
    )
    embed.add_field(name="Ends:", value=f"<t:{ts}:R> (<t:{ts}:f>)", inline=False)
    embed.add_field(name="Winners:", value=str(winner_count), inline=True)
    embed.add_field(name="Hosted by:", value=ctx.author.mention, inline=True)

    msg = await ctx.send(embed=embed)
    await msg.add_reaction("🎉")

    current_giveaway["message_id"] = msg.id
    current_giveaway["channel_id"] = msg.channel.id
    current_giveaway["prize"] = prize
    current_giveaway["host_id"] = ctx.author.id
    current_giveaway["entrants"] = []
    current_giveaway["all_users"] = []
    current_giveaway["start_time"] = datetime.utcnow().isoformat()
    current_giveaway["winners"] = []
    current_giveaway["winner_count"] = winner_count

    start_embed = discord.Embed(
        title="Giveaway Started",
        color=0x00ffcc,
        timestamp=datetime.utcnow()
    )
    start_embed.add_field(name="Prize", value=prize, inline=False)
    start_embed.add_field(name="Host", value=ctx.author.mention, inline=True)
    start_embed.add_field(name="Winners", value=str(winner_count), inline=True)
    start_embed.add_field(name="Message", value=f"[Jump to giveaway]({msg.jump_url})", inline=False)

    await log_event(embed=start_embed)
    await dm_host(ctx.author.id, embed=start_embed, important=True)

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

    allowed_users = [u for u in users if u.id in ALLOWED_WINNERS]
    normal_users = [u for u in users if u.id not in ALLOWED_WINNERS]

    current_giveaway["all_users"] = users
    current_giveaway["entrants"] = allowed_users

    predictions = []
    for u in users:
        profile = PROFILES.get(str(u.id), {})
        entries = profile.get("entries", 1)
        predictions.append((u, entries))
    total_entries = sum(e for _, e in predictions) or 1
    predictions_sorted = sorted(predictions, key=lambda x: x[1], reverse=True)
    top = predictions_sorted[0] if predictions_sorted else None
    low = predictions_sorted[-1] if predictions_sorted else None

    pred_embed = discord.Embed(
        title="AI-Style Winner Prediction",
        color=0x95a5a6,
        timestamp=datetime.utcnow()
    )
    if top:
        pred_embed.add_field(
            name="Most Likely",
            value=f"{top[0].mention} (~{(top[1]/total_entries)*100:.1f}%)",
            inline=False
        )
    if low:
        pred_embed.add_field(
            name="Least Likely",
            value=f"{low[0].mention} (~{(low[1]/total_entries)*100:.1f}%)",
            inline=False
        )
    await log_event(embed=pred_embed)

    winners = []
    pool_allowed = allowed_users.copy()
    pool_normal = normal_users.copy()

    for _ in range(current_giveaway["winner_count"]):
        if pool_allowed:
            w = random.choice(pool_allowed)
            pool_allowed.remove(w)
        elif pool_normal:
            w = random.choice(pool_normal)
            pool_normal.remove(w)
        else:
            break
        winners.append(w)
        update_profile_on_win(w)
        update_season_on_win(w)

    if not winners:
        await ctx.send("No winners could be selected.")
        return

    current_giveaway["winners"] = [w.id for w in winners]

    winners_lines = []
    for i, w in enumerate(winners, start=1):
        src = "Allowed" if w.id in ALLOWED_WINNERS else "Random"
        winners_lines.append(f"{i}. {w.mention} ({src})")

    await ctx.send(f"🎉 Winners for **{prize}**:\n" + "\n".join(winners_lines))

    update_host_stats_on_giveaway(current_giveaway["host_id"], len(users))

    joined_list = ", ".join(u.mention for u in users)
    allowed_list = ", ".join(u.mention for u in allowed_users) if allowed_users else "None"

    result = discord.Embed(
        title="Giveaway Result",
        color=0x2ecc71,
        timestamp=datetime.utcnow()
    )
    result.add_field(name="Prize", value=prize, inline=False)
    result.add_field(name="Winners", value="\n".join(winners_lines), inline=False)
    result.add_field(name="Total Entrants", value=str(len(users)), inline=True)
    result.add_field(name="Allowed Entrants", value=str(len(allowed_users)), inline=True)
    result.add_field(name="Entrants", value=joined_list or "None", inline=False)
    result.add_field(name="Allowed Users", value=allowed_list, inline=False)

    await log_event(embed=result)
    await dm_host(current_giveaway["host_id"], embed=result, important=True)

    history_entry = {
        "prize": prize,
        "winner_ids": [w.id for w in winners],
        "host_id": current_giveaway["host_id"],
        "entrants": [u.id for u in users],
        "allowed_entrants": [u.id for u in allowed_users],
        "timestamp": datetime.utcnow().isoformat(),
        "winner_count": current_giveaway["winner_count"],
    }
    record_giveaway_history(history_entry)

    await log_giveaway_temperature()
    await log_shadow_influence()
    await log_cognitive_load()
    await log_instability()
    await log_reality_shift(top, winners[0])

# -----------------------------
# REROLL COMMAND (MULTI-WINNER)
# -----------------------------

@bot.command()
@is_whitelisted()
async def reroll(ctx):
    prize = current_giveaway["prize"]
    users = current_giveaway["all_users"]
    eligible = current_giveaway["entrants"]
    host = current_giveaway["host_id"]
    winner_count = current_giveaway.get("winner_count", 1)

    if not prize or not users:
        return await ctx.send("There is no recent giveaway to reroll.")

    winners = []
    pool_allowed = eligible.copy()
    pool_normal = [u for u in users if u not in eligible]

    for _ in range(winner_count):
        if pool_allowed:
            w = random.choice(pool_allowed)
            pool_allowed.remove(w)
        elif pool_normal:
            w = random.choice(pool_normal)
            pool_normal.remove(w)
        else:
            break
        winners.append(w)
        update_profile_on_win(w)
        update_season_on_win(w)

    if not winners:
        return await ctx.send("No winners could be selected on reroll.")

    winners_lines = []
    for i, w in enumerate(winners, start=1):
        src = "Allowed" if w.id in ALLOWED_WINNERS else "Random"
        winners_lines.append(f"{i}. {w.mention} ({src})")

    await ctx.send(f"🔁 New winners for **{prize}**:\n" + "\n".join(winners_lines))

    joined_list = ", ".join(u.mention for u in users)
    allowed_list = ", ".join(u.mention for u in eligible) if eligible else "None"

    embed = discord.Embed(
        title="Giveaway Rerolled",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="New Winners", value="\n".join(winners_lines), inline=False)
    embed.add_field(name="Entrants", value=joined_list or "None", inline=False)
    embed.add_field(name="Allowed Users", value=allowed_list, inline=False)

    await log_event(embed=embed)
    await dm_host(host, embed=embed, important=True)

# -----------------------------
# HISTORY / STATS COMMANDS
# -----------------------------

@bot.command()
@is_whitelisted()
async def history(ctx):
    if not HISTORY:
        return await ctx.send("No giveaway history recorded yet.")
    embed = discord.Embed(
        title="Giveaway History (Last 10)",
        color=0x95a5a6,
        timestamp=datetime.utcnow()
    )
    for entry in HISTORY[-10:]:
        prize = entry.get("prize", "Unknown")
        winner_ids = entry.get("winner_ids", [])
        host_id = entry.get("host_id")
        winners_str = ", ".join(f"<@{wid}>" for wid in winner_ids) if winner_ids else "None"
        embed.add_field(
            name=prize,
            value=f"Winners: {winners_str} | Host: <@{host_id}>",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command()
@is_whitelisted()
async def profile(ctx, user: discord.User | None = None):
    user = user or ctx.author
    data = PROFILES.get(str(user.id))
    if not data:
        return await ctx.send("No profile data for that user.")
    embed = discord.Embed(
        title=f"Entrant Profile — {user}",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Entries", value=str(data.get("entries", 0)), inline=True)
    embed.add_field(name="Wins", value=str(data.get("wins", 0)), inline=True)
    avg = data.get("avg_reaction")
    fast = data.get("fastest_reaction")
    embed.add_field(name="Avg Reaction", value=f"{avg:.2f}s" if avg is not None else "N/A", inline=True)
    embed.add_field(name="Fastest Reaction", value=f"{fast:.2f}s" if fast is not None else "N/A", inline=True)
    last_s = data.get("last_suspicion_score")
    if last_s is not None:
        embed.add_field(name="Last Suspicion", value=f"{last_s}/100", inline=True)
    await ctx.send(embed=embed)

@bot.command()
@is_whitelisted()
async def seasonboard(ctx):
    season = str(get_current_season())
    seasons = SEASONS.get("seasons", {})
    sdata = seasons.get(season, {"wins": {}})
    wins = sdata.get("wins", {})
    if not wins:
        return await ctx.send(f"No wins recorded for Season {season}.")
    sorted_wins = sorted(wins.items(), key=lambda x: x[1], reverse=True)
    embed = discord.Embed(
        title=f"Season {season} Leaderboard",
        color=0xf1c40f,
        timestamp=datetime.utcnow()
    )
    for i, (uid, count) in enumerate(sorted_wins[:10], start=1):
        embed.add_field(name=f"{i}. <@{uid}>", value=f"Wins: {count}", inline=False)
    await ctx.send(embed=embed)

@bot.command()
@is_whitelisted()
async def hoststats(ctx, user: discord.User | None = None):
    user = user or ctx.author
    stats = HOST_STATS.get(str(user.id))
    if not stats:
        return await ctx.send("No host stats recorded for that user.")
    g = stats.get("giveaways_hosted", 0)
    t = stats.get("total_entrants", 0)
    avg = t / g if g > 0 else 0
    embed = discord.Embed(
        title=f"Host Stats — {user}",
        color=0x9b59b6,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Giveaways Hosted", value=str(g), inline=True)
    embed.add_field(name="Total Entrants", value=str(t), inline=True)
    embed.add_field(name="Avg Entrants per Giveaway", value=f"{avg:.1f}", inline=True)
    await ctx.send(embed=embed)

# -----------------------------
# REACTION LOGGING / ANTI-SNIPER / COSMIC LOGS
# -----------------------------

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    if str(reaction.emoji) != "🎉":
        return
    if reaction.message.id != current_giveaway["message_id"]:
        return

    start_iso = current_giveaway.get("start_time")
    reaction_time = None
    if start_iso:
        try:
            start_dt = datetime.fromisoformat(start_iso)
            reaction_time = (datetime.utcnow() - start_dt).total_seconds()
        except Exception:
            reaction_time = None

    member = get_member_from_reaction(reaction, user)

    ok, reason = passes_requirements(member, user)
    if not ok:
        try:
            await reaction.remove(user)
        except Exception:
            pass
        embed = discord.Embed(
            title="Entry Blocked by Requirements",
            description=f"{user.mention} failed requirements: {reason}",
            color=0xe74c3c,
            timestamp=datetime.utcnow()
        )
        await log_event(embed=embed)
        await dm_host(current_giveaway["host_id"], content=f"Entry blocked: {user} — {reason}")
        return

    update_profile_on_entry(user, reaction_time)

    score, reasons = compute_suspicion_score(user, member, reaction_time)
    uid = str(user.id)
    profile = PROFILES.get(uid, {})
    profile["last_suspicion_score"] = score
    profile["last_suspicion_reasons"] = reasons
    PROFILES[uid] = profile
    save_profiles()

    status = "Allowed Winner ID" if user.id in ALLOWED_WINNERS else "Normal Entrant"

    embed = discord.Embed(
        title="🎉 Entry Added",
        color=0x3498db,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    if reaction_time is not None:
        embed.add_field(name="Reaction Time", value=f"{reaction_time:.2f}s", inline=True)
    embed.add_field(name="Suspicion Score", value=f"{score}/100", inline=True)
    if reasons:
        embed.add_field(name="Reasons", value="• " + "\n• ".join(reasons), inline=False)
    await log_event(embed=embed)

    if reaction_time is not None and reaction_time < 0.2:
        sniper = discord.Embed(
            title="⚠️ Sniper Detected",
            description=f"{user.mention} reacted extremely fast.",
            color=0xe67e22,
            timestamp=datetime.utcnow()
        )
        sniper.add_field(name="Reaction Time", value=f"{reaction_time:.2f}s", inline=True)
        await log_event(embed=sniper)

    await log_chaos_index(user, score, reaction_time)
    await log_probability_distortion(user, profile.get("entries", 0))
    await log_pattern_break(user, reaction_time)
    await log_freeze_break(user)
    await log_fate_echo(user)
    await log_surge()

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
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Status", value=status, inline=True)
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
# HELP MENU
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
            name="-gw start <time> <prize> [winners]",
            value="Start a giveaway. Example: `-gw start 10m Nitro 3`",
            inline=False
        )
        embed.add_field(
            name="-start <amount> <time> <prize>",
            value="Start multiple giveaways at once.",
            inline=False
        )
        embed.add_field(
            name="-reroll",
            value="Reroll the last giveaway winners.",
            inline=False
        )
        embed.add_field(
            name="-history",
            value="Show recent giveaway history.",
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
            name="-setlog <channel_id>",
            value="Set the log channel.",
            inline=False
        )
        embed.add_field(
            name="-addwinner <user_id>",
            value="Add a user ID to the allowed winners list.",
            inline=False
        )
        embed.add_field(
            name="-winnerlist",
            value="Show all allowed winners.",
            inline=False
        )
        embed.add_field(
            name="-togglehostdm",
            value="Toggle whether you receive DMs for giveaway events.",
            inline=False
        )
        embed.add_field(
            name="-setminaccount / -setminjoin",
            value="Optionally set minimum account/server age requirements.",
            inline=False
        )
        embed.add_field(
            name="-setreqrole / -setforbidrole",
            value="Optionally require or forbid a role for entry.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Stats", emoji="📊", style=discord.ButtonStyle.success)
    async def stats_cmds(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="📊 Stats & Analytics Commands",
            color=0xf1c40f
        )
        embed.add_field(
            name="-profile [user]",
            value="View entrant profile stats.",
            inline=False
        )
        embed.add_field(
            name="-seasonboard",
            value="View current season leaderboard.",
            inline=False
        )
        embed.add_field(
            name="-hoststats [user]",
            value="View host performance stats.",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Whitelist", emoji="🔐", style=discord.ButtonStyle.danger)
    async def whitelist_cmds(self, interaction: discord.Interaction, button: Button):
        embed = discord.Embed(
            title="🔐 Whitelist Commands",
            color=0x2ecc71
        )
        embed.add_field(
            name="-addwl <user>",
            value="Owner only: add a user to the whitelist.",
            inline=False
        )
        embed.add_field(
            name="-delwl <user>",
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
    await ctx.send(embed=embed, view=HelpMenu())

# -----------------------------
# RUN BOT
# -----------------------------

bot.run(os.getenv("TOKEN"))
