import discord
from discord.ext import commands
import json
import os

DATA_FILE = "league.json"

# --------------------
# Data helpers
# --------------------

def normalize_team_name(name: str) -> str:
    # Allows case-insensitive matching and names with spaces if user quotes them.
    return name.strip()

def head_to_head(data, team_a: str, team_b: str):
    """
    Returns (a_wins, b_wins, ties, a_pf, a_pa, games_played)
    computed from data["games"] only (regular season history).
    """
    a = team_a
    b = team_b

    a_wins = b_wins = ties = 0
    a_pf = a_pa = 0
    played = 0

    for g in data.get("games", []):
        p1, s1, p2, s2 = g["p1"], g["s1"], g["p2"], g["s2"]

        # Match regardless of ordering in the saved game
        if {p1, p2} != {a, b}:
            continue

        played += 1

        if p1 == a and p2 == b:
            a_pf += s1
            a_pa += s2
            if s1 > s2:
                a_wins += 1
            elif s2 > s1:
                b_wins += 1
            else:
                ties += 1
        else:
            # p1 == b and p2 == a
            a_pf += s2
            a_pa += s1
            if s2 > s1:
                a_wins += 1
            elif s1 > s2:
                b_wins += 1
            else:
                ties += 1

    return a_wins, b_wins, ties, a_pf, a_pa, played

def win_pct(wins, losses):
    games = wins + losses
    if games == 0:
        return 0.000
    return wins / games

def point_diff(player):
    return player["points_for"] - player["points_against"]

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
            -win_pct(x[1]["wins"], x[1]["losses"]),   # win %
            -point_diff(x[1]),                        # point diff
            -x[1]["points_for"],                      # points for
            x[0].lower()                              # name tiebreak
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

@bot.command(name="top_h2h")
async def top_h2h(ctx):
    """
    Shows head-to-head matchups sorted by largest point differential.
    """
    data = load_data()
    teams = list(data["players"].keys())

    if len(teams) < 2:
        await ctx.send("❌ Not enough teams.")
        return

    results = []

    # Check every unique pair
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            team_a = teams[i]
            team_b = teams[j]

            a_wins, b_wins, ties, a_pf, a_pa, played = head_to_head(data, team_a, team_b)

            if played == 0:
                continue

            diff = a_pf - a_pa  # differential from team_a perspective

            results.append({
                "team_a": team_a,
                "team_b": team_b,
                "played": played,
                "a_wins": a_wins,
                "b_wins": b_wins,
                "ties": ties,
                "a_pf": a_pf,
                "a_pa": a_pa,
                "diff": diff
            })

    if not results:
        await ctx.send("No head-to-head games recorded.")
        return

    # Sort by largest absolute differential
    results.sort(key=lambda x: abs(x["diff"]), reverse=True)

    msg = "**Top Head-to-Head Point Differentials**\n"
    msg += "```\n"
    msg += f"{'MATCHUP':<28} {'GMS':<4} {'REC':<8} {'PF/PA':<12} {'DIFF':<6}\n"
    msg += "-" * 65 + "\n"

    for r in results[:10]:  # top 10 biggest differentials
        diff = r["diff"]
        diff_str = f"+{diff}" if diff > 0 else str(diff)

        rec = f"{r['a_wins']}-{r['b_wins']}"
        if r["ties"]:
            rec += f"-{r['ties']}"

        matchup = f"{r['team_a']} vs {r['team_b']}"

        msg += (
            f"{matchup:<28} "
            f"{r['played']:<4} "
            f"{rec:<8} "
            f"{r['a_pf']}/{r['a_pa']:<12} "
            f"{diff_str:<6}\n"
        )

    msg += "```"

    await ctx.send(msg)

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
    bracket = data["playoffs"].get("bracket")
    if not bracket:
        await ctx.send("❌ Playoff bracket not initialized.")
        return

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
    msg += "```\n"
    msg += f"{'RK':<3} {'TEAM':<12} {'REC':<7} {'PCT':<6} {'PF':<5} {'PA':<5} {'DIFF':<5}\n"
    msg += "-" * 50 + "\n"

    for idx, (team, s) in enumerate(table, start=1):
        pct = win_pct(s["wins"], s["losses"])
        diff = point_diff(s)
        diff_str = f"+{diff}" if diff > 0 else str(diff)

        msg += (
            f"{idx:<3} "
            f"{team:<12} "
            f"{s['wins']}-{s['losses']:<7} "
            f"{pct:.3f} "
            f"{s['points_for']:<5} "
            f"{s['points_against']:<5} "
            f"{diff_str:<5}\n"
        )

    msg += "```"
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
