import discord
from discord.ext import commands
import json
import os

DATA_FILE = "league.json"

# --------------------
# Data helpers
# --------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "season": 1,
            "playoff_mode": False,
            "players": {},
            "games": [],
            "playoffs": {"bracket": None, "results": []}
        }

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    data.setdefault("season", 1)
    data.setdefault("playoff_mode", False)
    data.setdefault("playoffs", {"bracket": None, "results": []})

    return data

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def is_admin(ctx):
    return (
        ctx.author.guild_permissions.administrator
        or ctx.author == ctx.guild.owner
    )

# --------------------
# Bot setup
# --------------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# --------------------
# Seeding & playoff logic
# --------------------

def get_seeds(data):
    return sorted(
        data["players"].items(),
        key=lambda x: (
            -x[1]["wins"],
            x[1]["losses"],
            -(x[1]["points_for"] - x[1]["points_against"]),
            x[0].lower()
        )
    )

def get_seed_map(data):
    seeds = get_seeds(data)
    return {team: idx + 1 for idx, (team, _) in enumerate(seeds)}

def generate_playoff_bracket(data):
    seeds = get_seeds(data)
    teams = [team for team, _ in seeds]
    n = len(teams)

    bracket = {
        "play_in": None,
        "byes": [],
        "round1": []
    }

    bracket["byes"] = teams[:2]
    remaining = teams[2:]

    if n % 2 == 1:
        bracket["play_in"] = (remaining[-2], remaining[-1])
        remaining = remaining[:-2]
        remaining.append("Play-In Winner")

    while len(remaining) >= 2:
        bracket["round1"].append(
            (remaining.pop(0), remaining.pop(-1))
        )

    return bracket

def label(team, seed_map):
    if team == "Play-In Winner":
        return "PI WIN"
    return f"#{seed_map[team]} {team}"

def render_ascii_bracket(bracket, seed_map):
    def fmt(team):
        if team == "Play-In Winner":
            return "PI WIN"
        return f"#{seed_map[team]} {team}"

    play_in = bracket["play_in"]
    r1 = bracket["round1"]
    byes = bracket["byes"]

    lines = []
    lines.append("```")
    lines.append("PLAY-IN        ROUND 1            ROUND 2            SUPER BOWL")
    lines.append("----------------------------------------------------------------")

    if play_in:
        lines.append(f"{fmt(play_in[0]):<14} ─┐")
        lines.append(" " * 15 + "│")
        lines.append(f"{fmt(play_in[1]):<14} ─┘")
    else:
        lines.append("")

    lines.append("")

    for high, low in r1:
        lines.append(" " * 10 + f"{fmt(high):<14} ────────────┐")
        lines.append(" " * 28 + "│")
        lines.append(" " * 10 + f"{fmt(low):<14} ────────────┘")
        lines.append("")

    lines.append(" " * 32 + f"{fmt(byes[0]):<14} ─────────┐")
    lines.append(" " * 32 + "(reseeds here)")
    lines.append("")

    lines.append(" " * 32 + f"{fmt(byes[1]):<14} ─────────┐")
    lines.append(" " * 32 + "(reseeds here)")
    lines.append("")

    lines.append(" " * 48 + "WIN ─────────── CHAMPION")
    lines.append("```")

    return "\n".join(lines)

# --------------------
# Core commands
# --------------------

@bot.command()
async def addplayer(ctx, name: str):
    data = load_data()
    if name in data["players"]:
        await ctx.send(f"{name} already exists.")
        return

    data["players"][name] = {
        "wins": 0,
        "losses": 0,
        "points_for": 0,
        "points_against": 0
    }

    save_data(data)
    await ctx.send(f"Added player: {name}")

@bot.command()
async def game(ctx, p1: str, s1: int, p2: str, s2: int):
    data = load_data()

    if data["playoff_mode"]:
        await handle_playoff_game(ctx, data, p1, s1, p2, s2)
        return

    if p1 not in data["players"] or p2 not in data["players"]:
        await ctx.send("Both players must exist.")
        return

    data["players"][p1]["points_for"] += s1
    data["players"][p1]["points_against"] += s2
    data["players"][p2]["points_for"] += s2
    data["players"][p2]["points_against"] += s1

    if s1 > s2:
        data["players"][p1]["wins"] += 1
        data["players"][p2]["losses"] += 1
    else:
        data["players"][p2]["wins"] += 1
        data["players"][p1]["losses"] += 1

    data["games"].append({
        "p1": p1, "s1": s1,
        "p2": p2, "s2": s2
    })

    save_data(data)
    await ctx.send(f"Final: {p1} {s1} – {p2} {s2}")

async def handle_playoff_game(ctx, data, p1, s1, p2, s2):
    bracket = data["playoffs"]["bracket"]
    valid_games = []

    if bracket["play_in"]:
        valid_games.append(bracket["play_in"])

    valid_games.extend(bracket["round1"])

    if not any({p1, p2} == {a, b} for a, b in valid_games):
        await ctx.send("❌ Invalid playoff matchup.")
        return

    winner = p1 if s1 > s2 else p2

    data["playoffs"]["results"].append({
        "p1": p1, "s1": s1,
        "p2": p2, "s2": s2,
        "winner": winner
    })

    save_data(data)
    await ctx.send(f"🏆 Playoff Final: {p1} {s1} – {p2} {s2}")

@bot.command()
async def standings(ctx):
    data = load_data()
    table = get_seeds(data)

    msg = "**Standings**\n"
    for p, s in table:
        msg += f"{p}: {s['wins']}-{s['losses']} | PF {s['points_for']} PA {s['points_against']}\n"

    await ctx.send(msg)

@bot.command()
async def resetseason(ctx):
    if not is_admin(ctx):
        await ctx.send("❌ Only admins can reset the season.")
        return

    data = load_data()

    if data["playoff_mode"]:
        await ctx.send("❌ Cannot reset season during playoffs.")
        return

    for p in data["players"].values():
        p.update({"wins": 0, "losses": 0, "points_for": 0, "points_against": 0})

    data["games"] = []
    data["season"] += 1

    save_data(data)
    await ctx.send(f"✅ Season reset. Now starting **Season {data['season']}**.")

@bot.command()
async def playoffmode(ctx):
    if not is_admin(ctx):
        await ctx.send("❌ Only admins can start playoff mode.")
        return

    data = load_data()

    if data["playoff_mode"]:
        await ctx.send("❌ Playoffs already started.")
        return

    data["playoff_mode"] = True
    data["playoffs"] = {
        "bracket": generate_playoff_bracket(data),
        "results": []
    }

    save_data(data)
    await ctx.send("🏈 **PLAYOFF MODE ACTIVATED**")

@bot.command()
async def currentplayoff(ctx):
@bot.command()
async def currentplayoff(ctx):
    data = load_data()

    if len(data["players"]) < 4:
        await ctx.send("❌ Need at least 4 players to generate a playoff bracket.")
        return

    bracket = data["playoffs"]["bracket"] or generate_playoff_bracket(data)
    seed_map = get_seed_map(data)

    msg = "**🏈 CURRENT PLAYOFF BRACKET**\n\n"
    msg += render_ascii_bracket(bracket, seed_map)

    await ctx.send(msg)


# --------------------
# Season archive
# --------------------

def archive_season(data):
    filename = f"SeasonRecord{data['season']}.json"
    archive = {
        "season": data["season"],
        "final_standings": get_seeds(data),
        "playoffs": data["playoffs"]
    }

    with open(filename, "w") as f:
        json.dump(archive, f, indent=2)

# --------------------
# RUN (must be last)
# --------------------

@bot.command()
async def removeplayer(ctx, name: str):
    data = load_data()

    if name not in data["players"]:
        await ctx.send(f"❌ Player `{name}` does not exist.")
        return

    player = data["players"][name]

    # Check stat-based games
    if (
        player["wins"] != 0
        or player["losses"] != 0
        or player["points_for"] != 0
        or player["points_against"] != 0
    ):
        await ctx.send(
            f"❌ Cannot remove `{name}` — they have recorded stats."
        )
        return

    # Check game history explicitly
    for g in data["games"]:
        if g["p1"] == name or g["p2"] == name:
            await ctx.send(
                f"❌ Cannot remove `{name}` — they appear in game history."
            )
            return

    # Safe to remove
    del data["players"][name]
    save_data(data)

    await ctx.send(f"✅ Player `{name}` has been removed.")


bot.run("Enter Discord Seed Here")
