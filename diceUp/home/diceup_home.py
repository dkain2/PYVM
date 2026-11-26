"""
DiceUp Home -- the app's Slack HOME TAB: which games there are, a button to start each one in a channel, and the stats of
every game, read from the DiceUp data table. One Python step, two recipes (a Workato step is one file, so it routes on what
it is given):

    `payload` or `action_id` present  ->  a button / menu on the home tab was used          (mode click)
    otherwise, a `user_id`            ->  someone opened the app's home tab (app_home_opened) (mode home)

WHAT THE HOME TAB SHOWS  (top to bottom)
    DiceUp, one line on what it is, and (after a press) a notice: the game is on its way, or what went wrong
    AVAILABLE GAMES   one channel picker ("Where do you want to play?") and a card for each game with its Start button.
                      A game marked coming_soon shows a card without a button. The picker remembers the last channel used.
    YOUR DICEUP       the person who opened the tab (user_id), in every game, ALL TIME (the period dropdown does not shrink
                      it): games played, prizes, grand prizes, games hosted, best place on a winners board, badges, and a
                      line for each game they played
    MY ACHIEVEMENTS   a badge card for every milestone they reached (Bronze, Silver, Gold ...), newest first, "Earned on"
    MY JOURNEYS       each game's milestones (play 1 / 5 / 25 games, win 1 / 5 / 20 prizes, 1 / 3 / 10 Full Houses, host
                      1 / 5 / 15 games) as cards: a progress bar, "2 / 3", a checklist, Completed / In progress / Not
                      started. JOURNEY_DEFAULTS, or a game's own `journeys` in games_json
    AT A GLANCE       every game together: games played, players, prizes won, live now (tiles), and the games live now
    ONE PART PER GAME its stats for the period chosen in the dropdown (last 7 / 30 / 90 days, all time):
                        tiles: games played, players, prizes won, Full Houses (the game's grand prize), average players
                        charts: games played over time, prizes by type
                        the winners board (rank, player, prizes, grand prizes, games played), top 10
                        more (folded): most games played, top hosts, top channels, the biggest game, the last game
                        you: your games, prizes, grand prizes, games hosted and your place on the winners board
    A person can opt out: a row of theirs with leaderboard_optout = true (any game) keeps them off every top list (they
    still count in the totals).

THE BLOCKS  (feature names; input `features` works like error_slack's slack_features)
    Slack's newer blocks make the page (slack_block_kit/ has the samples), and Slack may refuse any of them in a home tab
    or a workspace. So each one is a FEATURE, and a view Slack answers with invalid_blocks is published again without the
    feature it names (from the /blocks/N pointer in the error, else the next in PEEL), down to a plain view of headers,
    sections, context, actions and dividers, which always goes. `look_used` says what was left.
        headers     header levels (level 1 for DiceUp, 2 for the parts)
        cards       the games as a carousel of cards with their Start buttons       (off: a section per game)
        tiles       numbers as a grid (layout block)                                 (off: section fields)
        charts      data_visualization: games over time (bar), prizes by type (pie)  (off: left out)
        datatables  the winners board as a data_table                                (off: a table block)
        tables      ... as a table block                                             (off: a rich text list)
        rich        rich_text lists with real user mentions                          (off: mrkdwn lines)
        panels      a collapsible container for the secondary stats                  (off: plain sections)
        adaptive    condition block: tiles on desktop, fields on phones              (off by default)
    Blank = all but adaptive. "-charts" takes one away, "+adaptive" adds one, "none" is the plain view.

STARTING A GAME FROM THE HOME TAB
    1  The person picks a channel in the picker and presses Start <game> on the game's card. (Pressing Start without a
       channel puts a notice on the home tab: pick a channel first.)
    2  This step posts a short line in that channel ("@person is setting up a game of Tambola here"), which also proves the
       bot can post there. Not in the channel: a public channel is joined (channels:join) and the line posted again; a
       private one, or a join that fails, gives a notice telling the person to /invite the app. announce_start = no posts
       nothing (and checks nothing).
    3  It RETURNS the hand-off for the game's own step: start_game, start_text (the word, itambola), start_channel,
       start_user_id, start_message_ts (the line just posted). The recipe, IF start_game = tambola, runs the tambola step
       with text = start_text, user_id = start_user_id, channel = start_channel, message_ts = start_message_ts (thread_ts
       blank), plus its tokens and env. Tambola then shows its setup card, which only the person sees, in that channel,
       exactly as if they had typed the word there. This step never imports or runs tambola: a Workato step is one file.
    4  The home tab is published again with a notice and an Open channel button (a link to the line it posted).

THE TABLE  DiceUp, the generic table every Slack game writes to. Input `env` picks the workspace's table: dev for the dev
    one, anything else (blank too) prod's, so a recipe in production needs nothing mapped; the dev recipe maps env = dev
    (from the environment property). Only READ: this step writes nothing to it. Rows used (tambola's, see tambola.py):
        <game>_game    game_id, status (lobby starting running paused done cancelled), slack_user_id = host,
                       slack_channel_id, day_key, last_processed_ts = when it was set up
        <game>_player  game_id, slack_user_id: one per player per game (the organizer has one too)
        <game>_win     game_id, sub_type = prize, slack_user_id = winner, last_processed_ts = click time. One per press:
                       the EARLIEST row of a (game, prize) holds the prize, as in tambola's wins_from_rows
    A game counts once it has started (running, paused, done); lobbies and cancelled games count only as such. A live game
    older than live_hours (a lobby: lobby_hours) is taken as abandoned, as tambola does.

ADDING A GAME  (no code change needed for one that keeps the same row conventions)
    GAMES below holds tambola. `games_json` (a JSON list) changes or adds entries, matched on `key` (= record_type):
        [{"key": "trivia", "name": "Trivia", "emoji": ":brain:", "tagline": "Quick-fire questions",
          "word": "itrivia", "coming_soon": true}]
    Missing fields take defaults: rows <key>_game / <key>_player / <key>_win, tambola's statuses, no prizes list
    (prize keys are shown as they are), grand_prize blank (no grand-prize column). {"key": "tambola", "enabled": false}
    hides a game. A game's Start button hands off start_game = its key; the recipe needs an IF for it.

THE TWO RECIPES
    Home     Slack event app_home_opened -> this step. Map user_id <- event.user and tab <- event.tab (a "messages" tab is
             skipped), private_metadata <- event.view.private_metadata (keeps the period chosen; optional), plus
             slack_bot_token, workato_api_token and env.
    Click    Slack interactivity, filtered to action_id STARTING WITH `diceup_home_` -> this step. Map `payload`, the whole
             block_actions object as JSON text (formula mode .to_json), plus the two tokens and env. Then an IF on
             start_game for each game's hand-off (step 3 above). Link buttons are named diceup_link_* so the filter never
             passes them. Field-by-field still works: action_id, user_id, selected_channel, selected_period,
             private_metadata.
    Slack app: App Home > Home Tab on; event app_home_opened subscribed. Scopes: chat:write (the line in the channel),
    channels:join (optional, to join a public channel by itself). views.publish needs no scope of its own.

NOTHING HERE MAY BREAK THE RECIPE. Every call has a timeout; a failure goes into `error` / `warnings` and the step returns.
Input schema: diceup_home_input_schema.json   Output schema: diceup_home_output_schema.json
Run it locally:  python3 diceup_home.py [rows.json]   (no network: prints the home view for Block Kit Builder)
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

VERSION = "1.0.0"

# --------------------------------------------------------------------------------------------- endpoints and tables

SLACK_API = "https://slack.com/api/"
DATA_TABLES_API = "https://data-tables.workato.com/api/v1/tables/"
ENVS = ("dev", "prod")
DEFAULT_ENV = "prod"
# DiceUp, one table in each workspace (the same ids tambola.py uses in TABLES["diceup"]["ids"]).
TABLE_IDS = {"dev": "caf5f954-e916-4992-81ed-7c49e3181958", "prod": "a9305e93-50f6-4da3-9db7-ad968aceebb2"}
# The columns read (DiceUp's own names).
COLUMNS = ("record_type", "row_type", "game_id", "slack_user_id", "host_user_id", "winner_user_id", "sub_type", "status",
           "day_key", "slack_channel_id", "last_processed_ts", "source_ref")

HTTP_TIMEOUT = 12
PAGE_SIZE = 200
MAX_PAGES = 50                  # 50 x 200 = 10,000 rows; past that the stats say they are partial
TIME_BUDGET = 60                # seconds; a Workato Python step is stopped at 90

_now = time.time                # stand-ins so a test can fix the clock and skip the waiting
_sleep = time.sleep

# --------------------------------------------------------------------------------------------- action ids

ACTION_PREFIX = "diceup_home_"                 # the click recipe's filter: every action id that does something starts so
ACT_START = ACTION_PREFIX + "start_"           # + game key
ACT_CHANNEL = ACTION_PREFIX + "channel"        # the channel picker (a select: selecting alone does nothing)
ACT_PERIOD = ACTION_PREFIX + "period"
ACT_REFRESH = ACTION_PREFIX + "refresh"
LINK_PREFIX = "diceup_link_"                   # link buttons: not passed by the filter
WHERE_BLOCK = "diceup_home_where"

# --------------------------------------------------------------------------------------------- the games

STATUS_DONE, STATUS_PLAYING, STATUS_WAITING, STATUS_CANCELLED = ("done",), ("running", "paused"), ("lobby", "starting"), ("cancelled",)

GAMES = (
    {
        "key": "tambola", "name": "Tambola", "emoji": ":ticket:",
        "tagline": "The classic numbers game. Tickets, a board, five prizes.",
        "how": "Type `itambola` in a channel, or pick a channel above and press Start.",
        "word": "itambola",
        "prizes": [["early5", "Early Five"], ["top", "Top Line"], ["middle", "Middle Line"], ["bottom", "Bottom Line"],
                   ["full", "Full House"]],
        "grand_prize": "full",
        "live_hours": 12, "lobby_hours": 2,
    },
)
GAME_DEFAULTS = {"name": "", "emoji": ":game_die:", "tagline": "", "how": "", "word": "", "prizes": [], "grand_prize": "",
                 "live_hours": 12, "lobby_hours": 2, "enabled": True, "coming_soon": False, "image_url": "",
                 "done": list(STATUS_DONE), "playing": list(STATUS_PLAYING), "waiting": list(STATUS_WAITING),
                 "cancelled": list(STATUS_CANCELLED)}

PERIODS = (("7", "Last 7 days", 7), ("30", "Last 30 days", 30), ("90", "Last 90 days", 90), ("all", "All time", None))
PERIOD_DAYS = {k: d for k, _l, d in PERIODS}
PERIOD_LABEL = {k: l for k, l, _d in PERIODS}
DEFAULT_PERIOD = "all"

# --------------------------------------------------------------------------------------------- blocks and features

FEATURES = ("headers", "cards", "tiles", "charts", "datatables", "tables", "rich", "panels", "adaptive")
DEFAULT_FEATURES = ("headers", "cards", "tiles", "charts", "datatables", "tables", "rich", "panels")
PEEL = ("adaptive", "charts", "tiles", "panels", "cards", "datatables", "tables", "rich", "headers")   # likeliest refused first
FEATURE_OF = {"data_visualization": "charts", "layout": "tiles", "container": "panels", "carousel": "cards", "card": "cards",
              "data_table": "datatables", "table": "tables", "rich_text": "rich", "condition": "adaptive"}
MAX_BLOCKS = 100                # a home tab holds at most 100 blocks
TOP_N = 10
SECTION_MAX, FIELD_MAX, CARD_BODY, CARD_TEXT, BUTTON_MAX = 2900, 1900, 200, 150, 75
MEDALS = ("first_place_medal", "second_place_medal", "third_place_medal")
STATUS_WORDS = {"lobby": "lobby open, waiting for players", "starting": "dealing tickets", "running": "numbers being called",
                "paused": "paused"}


# ============================================================================================= small helpers


def text_of(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def clip(value, limit):
    value = text_of(value)
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


def truthy(value, default=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    return text_of(value).strip().lower() in ("1", "true", "yes", "y", "on")


def to_int(value, default):
    try:
        return int(float(text_of(value).strip()))
    except (TypeError, ValueError):
        return default


def as_ts(value):
    """A Slack ts / epoch seconds as a float; 0 when it is not one."""
    try:
        return float(text_of(value).strip())
    except ValueError:
        return 0.0


def sx(text):
    return text_of(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_int(n):
    return "{:,}".format(int(n))


def plural(n, one, many=None):
    return "{} {}".format(fmt_int(n), one if n == 1 else (many or one + "s"))


def env_named(word):
    word = text_of(word).strip().lower()
    return word if word in ENVS else DEFAULT_ENV


def mrk(text):
    return {"type": "mrkdwn", "text": text}


def pt(text, limit=BUTTON_MAX):
    return {"type": "plain_text", "text": clip(text, limit) or " ", "emoji": True}


def as_dict(value):
    return value if isinstance(value, dict) else {}


def parse_json(value, default):
    if isinstance(value, (dict, list)):
        return value
    text = text_of(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def choice(value, universe, default):
    """Blank = the default set; names = exactly those; 'all'; '+name' adds; '-name' takes away; 'none' = nothing."""
    tokens = [t for t in re.split(r"[\s,;]+", text_of(value).strip().lower()) if t]
    if "none" in tokens:
        return frozenset()
    named = [t for t in tokens if t in universe]
    base = set(universe) if "all" in tokens else set(named) if named else set(default)
    for token in tokens:
        if token[:1] == "+" and token[1:] in universe:
            base.add(token[1:])
        elif token[:1] == "-" and token[1:] in universe:
            base.discard(token[1:])
    return frozenset(base)


# ============================================================================================= the network


def _send_json(url, headers, payload=None, method="POST", timeout=HTTP_TIMEOUT):
    """(body, error). Never raises. A payload of None sends no body."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
        return (json.loads(raw) if raw.strip() else {}), None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {}: {}".format(error.code, url.split("/")[2], detail)
    except Exception as error:                                          # noqa: BLE001 - timeouts, DNS, TLS, bad JSON
        return None, "{}: {}".format(type(error).__name__, clip(str(error), 200))


def slack(token, method, payload):
    """(body, error) of a Slack Web API call; error is Slack's own word (not_in_channel, invalid_blocks ...) plus detail."""
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json; charset=utf-8"}
    body, error = _send_json(SLACK_API + method, headers, payload)
    if error:
        return None, "{}: {}".format(method, error)
    if not isinstance(body, dict) or not body.get("ok"):
        body = as_dict(body)
        notes = "; ".join(text_of(m) for m in (as_dict(body.get("response_metadata")).get("messages") or [])[:3])
        return None, "{}: {}{}".format(method, body.get("error") or "unknown", " [{}]".format(clip(notes, 400)) if notes else "")
    return body, None


class Table(object):
    """Reads DiceUp by column name. Never writes."""

    def __init__(self, token, env):
        self.env = env_named(env)
        self.headers = {"Authorization": "Bearer {}".format(token), "Content-Type": "application/json"}
        self.query_url = DATA_TABLES_API + TABLE_IDS[self.env] + "/query"
        self.errors, self.pages, self.capped = [], 0, False

    @staticmethod
    def decode(body):
        """The query answers with schema and data as arrays of arrays."""
        names = [f.get("name") for group in body.get("schema", []) for f in group if isinstance(f, dict)]
        return [dict(zip(names, [v for group in row for v in group])) for row in body.get("data", [])]

    def query(self, where, select=None, max_pages=MAX_PAGES, page_size=PAGE_SIZE, deadline=None):
        """(rows, ok). Follows continuation tokens up to max_pages (or the deadline): then `capped` is set."""
        payload = {"where": where, "limit": page_size}
        if select:
            payload["select"] = list(select)
        rows = []
        for page in range(max_pages):
            if deadline and _now() > deadline:
                self.capped = True
                break
            body, error = _send_json(self.query_url, self.headers, payload)
            if error:
                _sleep(0.3)                                             # one retry: a blip is the usual cause
                body, error = _send_json(self.query_url, self.headers, payload)
            if error:
                self.errors.append("table.query " + error)
                return rows, False
            self.pages += 1
            rows.extend(self.decode(as_dict(body)))
            token = as_dict(body).get("continuation_token")
            if not token:
                return rows, True
            payload["continuation_token"] = token
            if page == max_pages - 1:
                self.capped = True
        return rows, True


# ============================================================================================= games and periods


def game_list(raw, warnings):
    """GAMES with `games_json` laid over them (matched on key; new keys appended). Only enabled ones are returned."""
    games = [dict(GAME_DEFAULTS, **g) for g in GAMES]
    extra = parse_json(raw, None)
    if extra is None:
        if text_of(raw).strip():
            warnings.append("games_json is not valid JSON: ignored")
        extra = []
    if isinstance(extra, dict):
        extra = [extra]
    if not isinstance(extra, list):
        warnings.append("games_json is not a JSON list: ignored")
        extra = []
    for item in extra:
        if not isinstance(item, dict) or not re.match(r"^[a-z0-9_]{2,30}$", text_of(item.get("key")).strip().lower()):
            warnings.append("games_json: an entry without a usable key (a-z, 0-9, _) was ignored")
            continue
        key = item["key"].strip().lower()
        known = next((g for g in games if g["key"] == key), None)
        if known:
            known.update({k: v for k, v in item.items() if k != "key"})
        else:
            games.append(dict(GAME_DEFAULTS, key=key, name=text_of(item.get("name")) or key.title(),
                              **{k: v for k, v in item.items() if k not in ("key", "name")}))
    for g in games:
        rows = as_dict(g.get("rows"))
        g["rows"] = {kind: text_of(rows.get(kind)) or "{}_{}".format(g["key"], kind) for kind in ("game", "player", "win")}
        g["prize_names"] = {text_of(p[0]): text_of(p[1]) for p in g.get("prizes") or []
                            if isinstance(p, (list, tuple)) and len(p) >= 2}
    return [g for g in games if truthy(g.get("enabled"), True)]


def period_of(value):
    value = text_of(value).strip().lower().replace("days", "").replace("d", "").strip()
    return value if value in PERIOD_DAYS else ("all" if value in ("all time", "alltime", "ever") else DEFAULT_PERIOD)


def when_of(row):
    """When a row happened, as UTC epoch seconds: last_processed_ts, else noon of day_key; 0 when neither."""
    ts = as_ts(row.get("last_processed_ts"))
    if ts > 1e9:
        return ts
    day = text_of(row.get("day_key")).strip()[:10]
    try:
        return datetime.strptime(day, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def day_text(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%-d %b %Y") if ts else "an unknown day"


# ============================================================================================= the stats


def game_stats(rows, spec, period, now, viewer, hidden):
    """Everything the home tab says about one game, from its rows. Pure: no network."""
    days = PERIOD_DAYS.get(period)
    since = now - days * 86400 if days else None
    kinds = spec["rows"]
    mine = [r for r in rows if text_of(r.get("record_type")) == spec["key"]]
    done_s, playing_s = set(spec["done"]), set(spec["playing"])
    waiting_s, cancelled_s = set(spec["waiting"]), set(spec["cancelled"])

    games = {}
    for r in mine:
        if text_of(r.get("row_type")) != kinds["game"] or not text_of(r.get("game_id")):
            continue
        gid = text_of(r["game_id"])
        entry = {"id": gid, "status": text_of(r.get("status")).lower(), "when": when_of(r),
                 "host": text_of(r.get("host_user_id") or r.get("slack_user_id")), "channel": text_of(r.get("slack_channel_id")),
                 "winner": text_of(r.get("winner_user_id"))}
        held = games.get(gid)
        if held is None or (entry["when"] or 9e18) < (held["when"] or 9e18):   # two rows for a game: the earlier claim is it
            games[gid] = entry

    def fresh(g):
        limit = spec["lobby_hours"] if g["status"] in waiting_s else spec["live_hours"]
        return bool(g["when"]) and now - g["when"] <= float(limit) * 3600

    live = sorted([g for g in games.values() if g["status"] in (playing_s | waiting_s) and fresh(g)],
                  key=lambda g: -g["when"])
    counted = {gid: g for gid, g in games.items()
               if (g["status"] in done_s or (g["status"] in playing_s and fresh(g))) and (since is None or g["when"] >= since)}
    in_period = [g for g in games.values() if since is None or g["when"] >= since]

    seats = {}                                                          # game -> set of players
    for r in mine:
        if text_of(r.get("row_type")) == kinds["player"] and text_of(r.get("game_id")) in counted and r.get("slack_user_id"):
            seats.setdefault(text_of(r["game_id"]), set()).add(text_of(r["slack_user_id"]))
    for gid, g in counted.items():                                      # the organizer always plays
        if g["host"]:
            seats.setdefault(gid, set()).add(g["host"])

    best = {}                                                           # (game, prize) -> the earliest win row
    for r in mine:
        if text_of(r.get("row_type")) != kinds["win"] or text_of(r.get("game_id")) not in counted or not r.get("slack_user_id"):
            continue
        key = (text_of(r["game_id"]), text_of(r.get("sub_type")))
        order = (as_ts(r.get("last_processed_ts")) or 9e18, text_of(r.get("slack_user_id")), text_of(r.get("source_ref")))
        if key not in best or order < best[key][0]:
            best[key] = (order, text_of(r["slack_user_id"]))
    wins = [(gid, prize, uid) for (gid, prize), (_o, uid) in best.items()]
    for gid, g in counted.items():                                      # a game that names its winner on its own row
        if g["winner"] and not any(w[0] == gid for w in wins):
            wins.append((gid, "win", g["winner"]))

    grand = text_of(spec.get("grand_prize"))
    per_player = {}
    times = {"games": [], "prizes": [], "grand": [], "hosted": []}        # the viewer's own, for journeys and badges

    def person(uid):
        return per_player.setdefault(uid, {"games": 0, "prizes": 0, "grand": 0, "hosted": 0})

    win_when = {(text_of(r.get("game_id")), text_of(r.get("sub_type")), text_of(r.get("slack_user_id"))): when_of(r)
                for r in mine if text_of(r.get("row_type")) == kinds["win"]}
    for gid, players in seats.items():
        for uid in players:
            person(uid)["games"] += 1
            if uid == viewer:
                times["games"].append(counted[gid]["when"])
    for gid, prize, uid in wins:
        p = person(uid)
        p["prizes"] += 1
        p["grand"] += 1 if grand and prize == grand else 0
        if uid == viewer:
            stamp = win_when.get((gid, prize, uid)) or counted[gid]["when"]
            times["prizes"].append(stamp)
            if grand and prize == grand:
                times["grand"].append(stamp)
    for g in counted.values():
        if g["host"]:
            person(g["host"])["hosted"] += 1
            if g["host"] == viewer:
                times["hosted"].append(g["when"])
    times = {k: sorted(v) for k, v in times.items()}

    def ranked(metric, tie=None):
        people = [(uid, p) for uid, p in per_player.items() if p[metric] > 0 and uid not in hidden]
        people.sort(key=lambda x: (-x[1][metric], -(x[1][tie] if tie else 0), x[0]))
        out, last, rank = [], None, 0
        for n, (uid, p) in enumerate(people, 1):
            score = (p[metric], p[tie] if tie else 0)
            rank = rank if score == last else n
            last = score
            out.append(dict(p, uid=uid, rank=rank))
        return out

    winners = ranked("prizes", "grand")
    total_seats = sum(len(s) for s in seats.values())
    played_with_players = [gid for gid in counted if seats.get(gid)]
    biggest = max(counted.values(), key=lambda g: (len(seats.get(g["id"], ())), g["when"]), default=None)
    done_games = sorted([g for g in counted.values() if g["status"] in done_s], key=lambda g: -g["when"])
    last = done_games[0] if done_games else None
    last_grand = next((uid for gid, prize, uid in wins if last and gid == last["id"] and (prize == grand or prize == "win")), "")
    you = per_player.get(viewer, {"games": 0, "prizes": 0, "grand": 0, "hosted": 0})
    you_rank = next((w["rank"] for w in winners if w["uid"] == viewer), 0)

    return {
        "key": spec["key"], "period": period,
        "played": len([g for g in counted.values() if g["status"] in done_s]),
        "counted": len(counted),
        "cancelled": len([g for g in in_period if g["status"] in cancelled_s]),
        "live": live,
        "players": len({uid for s in seats.values() for uid in s}),
        "seats": total_seats,
        "avg_players": round(total_seats / len(played_with_players), 1) if played_with_players else 0,
        "prizes": len(wins),
        "grand": len([w for w in wins if grand and w[1] == grand]),
        "by_prize": Counter(w[1] for w in wins),
        "winners": winners,
        "active": ranked("games", "prizes"),
        "hosts": ranked("hosted"),
        "channels": Counter(g["channel"] for g in counted.values() if g["channel"]).most_common(),
        "biggest": {"players": len(seats.get(biggest["id"], ())), "channel": biggest["channel"], "when": biggest["when"]}
        if biggest and seats.get(biggest["id"]) else None,
        "last": {"when": last["when"], "channel": last["channel"], "winner": last_grand} if last else None,
        "timeline": timeline(counted.values(), period, now),
        "you": dict(you, rank=you_rank, of=len(winners), times=times,
                    last=max(times["games"]) if times["games"] else 0),
    }


def timeline(games, period, now):
    """[(label, games started)] for the chart: days for 7 / 30 days, weeks for 90, months for all time (the last 12)."""
    days = PERIOD_DAYS.get(period)
    today = datetime.fromtimestamp(now, timezone.utc).date()
    stamps = [datetime.fromtimestamp(g["when"], timezone.utc).date() for g in games if g["when"]]
    if days in (7, 30):
        buckets = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
        counts = Counter(stamps)
        return [(d.strftime("%-d %b"), counts.get(d, 0)) for d in buckets]
    if days == 90:
        start = today - timedelta(days=today.weekday())                 # Monday of this week
        weeks = [start - timedelta(weeks=i) for i in range(12, -1, -1)]
        counts = Counter(d - timedelta(days=d.weekday()) for d in stamps)
        return [(w.strftime("%-d %b"), counts.get(w, 0)) for w in weeks]
    if not stamps:
        return []
    back = today.year * 12 + today.month - 1 - 11                       # the month eleven months ago: at most 12 bars
    first = max(min(stamps).replace(day=1), date(back // 12, back % 12 + 1, 1))
    months, cursor = [], first
    while cursor <= today:
        months.append(cursor)
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    counts = Counter(d.replace(day=1) for d in stamps)
    return [(m.strftime("%b %Y"), counts.get(m, 0)) for m in months]


# ---- journeys and achievements (the viewer's, all time). A journey is a metric and its milestones; every milestone
# reached is an achievement with a tier (the first Bronze, the second Silver, the third Gold ...), earned on the day of the
# game or the press that reached it. A game's `journeys` in games_json replaces these; {grand} and {game} are filled in,
# and a journey on "grand" is skipped for a game without a grand prize.
JOURNEY_DEFAULTS = (
    {"key": "player", "name": "{game} Regular", "metric": "games", "emoji": ":game_die:", "steps": [1, 5, 25],
     "step": "Play {n} game|Play {n} games"},
    {"key": "winner", "name": "Prize Hunter", "metric": "prizes", "emoji": ":dart:", "steps": [1, 5, 20],
     "step": "Win {n} prize|Win {n} prizes"},
    {"key": "grand", "name": "{grand} Collector", "metric": "grand", "emoji": ":trophy:", "steps": [1, 3, 10],
     "step": "Win {n} {grand}|Win {n} {grand}s"},
    {"key": "host", "name": "Game Host", "metric": "hosted", "emoji": ":microphone:", "steps": [1, 5, 15],
     "step": "Host {n} game|Host {n} games"},
)
METRICS = ("games", "prizes", "grand", "hosted")
TIERS = (("Bronze", "third_place_medal"), ("Silver", "second_place_medal"), ("Gold", "first_place_medal"),
         ("Platinum", "gem"), ("Diamond", "crown"))
BAR_CELLS = 10


def journeys_of(spec):
    grand = spec["prize_names"].get(spec["grand_prize"], spec["grand_prize"].title()) if spec["grand_prize"] else ""
    out = []
    for j in spec.get("journeys") or JOURNEY_DEFAULTS:
        if not isinstance(j, dict) or j.get("metric") not in METRICS or (j["metric"] == "grand" and not grand):
            continue
        steps = sorted({n for n in (to_int(x, 0) for x in j.get("steps") or []) if n > 0})[:len(TIERS)]
        if not steps:
            continue
        fill = {"game": spec["name"], "grand": grand}
        one, _bar, many = text_of(j.get("step") or "Reach {n}").partition("|")
        out.append({"key": "{}_{}".format(spec["key"], text_of(j.get("key")) or j["metric"]), "game": spec["name"],
                    "name": text_of(j.get("name") or j["metric"].title()).format(**fill), "metric": j["metric"],
                    "emoji": text_of(j.get("emoji")) or spec["emoji"], "steps": steps,
                    "labels": [(one if n == 1 else (many or one)).format(n=n, **fill) for n in steps],
                    "image_url": text_of(j.get("image_url"))})
    return out


def progress(journey, you):
    """The viewer's place on a journey: count, milestones done, status, and the achievements it has given them."""
    count = you.get(journey["metric"], 0)
    stamps = you.get("times", {}).get(journey["metric"], [])
    done = [n for n in journey["steps"] if count >= n]
    badges = [{"journey": journey, "tier": TIERS[i][0], "medal": TIERS[i][1], "step": n, "label": journey["labels"][i],
               "when": stamps[n - 1] if len(stamps) >= n else 0} for i, n in enumerate(journey["steps"]) if count >= n]
    status = "done" if len(done) == len(journey["steps"]) else "live" if done or count else "new"
    return {"journey": journey, "count": count, "done": len(done), "status": status, "badges": badges}


def bar(done, total, cells=BAR_CELLS):
    full = int(round(cells * done / total)) if total else 0
    return "▰" * full + "▱" * (cells - full)


def profile(games, stats_all, viewer):
    """Everything about the viewer across the games: totals, a line per game, journeys and achievements (all time)."""
    per_game, journeys, badges = [], [], []
    for spec in games:
        s = stats_all.get(spec["key"])
        if not s:
            continue
        you = s["you"]
        per_game.append((spec, you))
        for j in journeys_of(spec):
            p = progress(j, you)
            journeys.append(p)
            badges += p["badges"]
    total = {m: sum(you.get(m, 0) for _s, you in per_game) for m in METRICS}
    ranked = [(you["rank"], spec) for spec, you in per_game if you.get("rank")]
    favourite = max(per_game, key=lambda x: x[1].get("games", 0), default=(None, {}))
    return {"viewer": viewer, "total": total, "per_game": per_game,
            "best": min(ranked, key=lambda x: x[0]) if ranked else None,
            "favourite": favourite[0] if favourite[1].get("games") else None,
            "last": max([you.get("last", 0) for _s, you in per_game] or [0]),
            "journeys": sorted(journeys, key=lambda p: ({"live": 0, "done": 1, "new": 2}[p["status"]], -p["done"])),
            "badges": sorted(badges, key=lambda b: -(b["when"] or 0))}


def all_stats(stats):
    """At a glance: every game together."""
    return {"played": sum(s["played"] for s in stats), "prizes": sum(s["prizes"] for s in stats),
            "live": sum(len(s["live"]) for s in stats), "seats": sum(s["seats"] for s in stats),
            "games": len(stats)}


# ============================================================================================= the view


class Look(object):
    """Which features the view uses; hands out block ids that are the same on every run."""

    def __init__(self, features):
        self.features = frozenset(features)
        self._n = Counter()

    def on(self, feature):
        return feature in self.features

    def bid(self, kind):
        self._n[kind] += 1
        return "dh_{}_{}".format(kind, self._n[kind])

    def without(self, features):
        return Look(self.features - set(features))


def header(look, text, level):
    block = {"type": "header", "block_id": look.bid("head"), "text": pt(text, 150)}
    if look.on("headers"):
        block["level"] = level
    return block


def section(text, **extra):
    return dict({"type": "section", "text": mrk(clip(text, SECTION_MAX) or " ")}, **extra)


def context(*texts):
    return {"type": "context", "elements": [mrk(clip(t, 2900)) for t in texts if t][:10]}


def tiles(look, label, pairs):
    """Numbers side by side: a grid (layout) when tiles is on, fields otherwise. pairs = [(label, value, note)]."""
    pairs = [p for p in pairs if p]
    texts = ["*{}*\n{}{}".format(v, sx(l), "\n_{}_".format(sx(n)) if n else "") for l, v, n in pairs]
    fields = {"type": "section", "block_id": look.bid("fields"), "fields": [mrk(clip(t, FIELD_MAX)) for t in texts[:10]]}
    if not look.on("tiles"):
        return [fields]
    per_row = 4 if len(texts) in (4, 8) else 3
    rows = [{"items": [{"block": {"type": "section", "block_id": look.bid("tile"), "text": mrk(clip(t, 600))},
                        "width": "standard", "horizontal_alignment": "center"} for t in texts[s:s + per_row]]}
            for s in range(0, len(texts), per_row)]
    grid = {"type": "layout", "block_id": look.bid("tiles"), "label": clip(label, 100), "is_label_visible": False,
            "grid_lines": "outer", "rows": rows}
    if look.on("adaptive"):
        return [{"type": "condition", "cases": [{"conditions": [{"type": "client", "op": "=", "value": "desktop"}],
                                                 "blocks": [grid]}], "default": [fields]}]
    return [grid]


def where_block(look, last_channel):
    """The one channel picker every Start button reads (from the view's state)."""
    picker = {"type": "conversations_select", "action_id": ACT_CHANNEL, "placeholder": pt("Pick a channel to play in", 150),
              "filter": {"include": ["public", "private"], "exclude_bot_users": True, "exclude_external_shared_channels": True}}
    if re.match(r"^[CG][A-Z0-9]{6,}$", text_of(last_channel)):
        picker["initial_conversation"] = last_channel
    return {"type": "actions", "block_id": WHERE_BLOCK, "elements": [picker]}


def start_button(spec):
    return {"type": "button", "text": pt("Start {}".format(spec["name"])), "style": "primary",
            "action_id": ACT_START + spec["key"], "value": spec["key"]}


def game_blocks(look, games, stats_by_key):
    """The available games: a carousel of cards, or a section per game."""
    blocks = []
    if look.on("cards"):
        cards = []
        for spec in games[:10]:
            s = stats_by_key.get(spec["key"])
            sub = "Coming soon" if spec["coming_soon"] else ("{} played".format(plural(s["played"], "game")) if s else "")
            card = {"type": "card", "block_id": look.bid("card"),
                    "title": mrk(clip("{} *{}*".format(spec["emoji"], sx(spec["name"])).strip(), CARD_TEXT)),
                    "subtitle": mrk(clip(sub or " ", CARD_TEXT)),
                    "body": mrk(clip(sx(spec["tagline"] or spec["how"] or spec["name"]), CARD_BODY))}
            if re.match(r"^https://\S+$", text_of(spec.get("image_url"))):
                card["hero_image"] = {"type": "image", "image_url": spec["image_url"], "alt_text": clip(spec["name"], 100)}
            if not spec["coming_soon"]:
                card["actions"] = [start_button(spec)]
            cards.append(card)
        blocks.append({"type": "carousel", "block_id": look.bid("games"), "elements": cards})
        hows = [spec["how"] for spec in games if spec["how"] and not spec["coming_soon"]]
        if hows:
            blocks.append(context(*[sx(h).replace("&lt;", "<").replace("&gt;", ">") for h in hows[:3]]))
        return blocks
    for spec in games:
        lines = ["{} *{}*{}".format(spec["emoji"], sx(spec["name"]), "  ·  _coming soon_" if spec["coming_soon"] else ""),
                 sx(spec["tagline"])]
        if spec["how"] and not spec["coming_soon"]:
            lines.append("_{}_".format(spec["how"]))
        block = section("\n".join(l for l in lines if l), block_id=look.bid("game"))
        if not spec["coming_soon"]:
            block["accessory"] = start_button(spec)
        blocks.append(block)
    return blocks


def live_lines(games, stats_by_key):
    lines = []
    for spec in games:
        s = stats_by_key.get(spec["key"])
        for g in (s["live"] if s else [])[:5]:
            lines.append("{} *{}* in <#{}>  ·  {}  ·  hosted by <@{}>".format(
                spec["emoji"], sx(spec["name"]), g["channel"], STATUS_WORDS.get(g["status"], g["status"]), g["host"])
                if g["host"] else "{} *{}* in <#{}>  ·  {}".format(spec["emoji"], sx(spec["name"]), g["channel"],
                                                                   STATUS_WORDS.get(g["status"], g["status"])))
    return lines


def rich_user(uid):
    return {"type": "user", "user_id": uid}


def board_rows(spec, s, top):
    grand_name = spec["prize_names"].get(spec["grand_prize"], spec["grand_prize"].title()) if spec["grand_prize"] else ""
    head = ["#", "Player", "Prizes"] + ([grand_name + "s"] if grand_name else []) + ["Games"]
    rows = [[w["rank"], w["uid"], w["prizes"]] + ([w["grand"]] if grand_name else []) + [w["games"]] for w in s["winners"][:top]]
    return head, rows


def winners_blocks(look, spec, s, top):
    """The winners board: a data_table, a table, a rich text list, or mrkdwn lines (in that order of preference)."""
    if not s["winners"]:
        return [context("No prizes won yet in this period.")]
    head, rows = board_rows(spec, s, top)
    title = "*Winners board*"

    def rank_cell(rank):
        if rank <= 3:
            return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [
                {"type": "emoji", "name": MEDALS[rank - 1]}]}]}
        return {"type": "raw_text", "text": str(rank)}

    def user_cell(uid):
        return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [rich_user(uid)]}]}

    if look.on("datatables"):
        table = [[{"type": "raw_text", "text": h} for h in head]]
        for row in rows:
            table.append([rank_cell(row[0]), user_cell(row[1])] +
                         [{"type": "raw_number", "value": v, "text": fmt_int(v)} for v in row[2:]])
        return [section(title, block_id=look.bid("board_title")),
                {"type": "data_table", "block_id": look.bid("board"), "caption": "Winners board", "rows": table}]
    if look.on("tables"):
        def text_cell(t, bold=False):
            el = {"type": "text", "text": text_of(t)}
            if bold:
                el["style"] = {"bold": True}
            return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [el]}]}
        table = [[text_cell(h, True) for h in head]]
        table += [[rank_cell(r[0]) if r[0] <= 3 else text_cell(r[0]), user_cell(r[1])] + [text_cell(fmt_int(v)) for v in r[2:]]
                  for r in rows]
        return [section(title, block_id=look.bid("board_title")),
                {"type": "table", "block_id": look.bid("board"), "rows": table,
                 "column_settings": [{"align": "left" if i < 2 else "right"} for i in range(len(head))]}]
    grand = len(head) == 5
    if look.on("rich"):
        items = []
        for r in rows:
            lead = [{"type": "emoji", "name": MEDALS[r[0] - 1]}, {"type": "text", "text": " "}] if r[0] <= 3 else \
                [{"type": "text", "text": "{}. ".format(r[0])}]
            tail = "  ·  {}{}  ·  {}".format(plural(r[2], "prize"), ", {} {}".format(r[3], head[3].lower() if r[3] != 1 else
                                                                                    head[3][:-1].lower()) if grand else "",
                                             plural(r[-1], "game"))
            items.append({"type": "rich_text_section", "elements": lead + [rich_user(r[1]), {"type": "text", "text": tail}]})
        return [section(title, block_id=look.bid("board_title")),
                {"type": "rich_text", "block_id": look.bid("board"), "elements": [
                    {"type": "rich_text_list", "style": "bullet", "indent": 0, "elements": items}]}]
    lines = []
    for r in rows:
        lead = ":{}:".format(MEDALS[r[0] - 1]) if r[0] <= 3 else "{}.".format(r[0])
        extra = ", {} {}".format(r[3], head[3].lower() if r[3] != 1 else head[3][:-1].lower()) if grand else ""
        lines.append("{} <@{}>  ·  {}{}  ·  {}".format(lead, r[1], plural(r[2], "prize"), extra, plural(r[-1], "game")))
    return [section(title + "\n" + "\n".join(lines), block_id=look.bid("board"))]


def top_list(people, metric, word, n=5):
    if not people:
        return "_nobody yet_"
    return "\n".join("{}. <@{}>  ·  {}".format(p["rank"], p["uid"], plural(p[metric], word)) for p in people[:n])


def chart_blocks(look, spec, s):
    if not look.on("charts"):
        return []
    out = []
    line = s["timeline"]
    if line and any(v for _l, v in line):
        out.append({"type": "data_visualization", "block_id": look.bid("chart"),
                    "title": "{} games started".format(spec["name"]),
                    "chart": {"type": "bar", "series": [{"name": "Games", "data": [{"label": l, "value": v} for l, v in line]}],
                              "axis_config": {"categories": [l for l, _v in line], "x_label": "When", "y_label": "Games"}}})
    if len(s["by_prize"]) >= 2:
        names = spec["prize_names"]
        order = list(names) + sorted(k for k in s["by_prize"] if k not in names)
        out.append({"type": "data_visualization", "block_id": look.bid("chart"), "title": "Prizes won by type",
                    "chart": {"type": "pie", "segments": [{"label": names.get(k, k.title()), "value": s["by_prize"][k]}
                                                          for k in order if s["by_prize"].get(k)]}})
    return out


def more_blocks(look, spec, s):
    """The secondary stats: most games, hosts, channels, the biggest and the last game. Folded when panels is on."""
    fields = [mrk("*Most games played*\n" + top_list(s["active"], "games", "game")),
              mrk("*Top hosts*\n" + top_list(s["hosts"], "hosted", "game"))]
    chans = "\n".join("{}. <#{}>  ·  {}".format(n, c, plural(k, "game")) for n, (c, k) in enumerate(s["channels"][:5], 1))
    fields.append(mrk("*Top channels*\n" + (chans or "_none yet_")))
    notes = []
    if s["biggest"]:
        b = s["biggest"]
        notes.append("*Biggest game*\n{} in <#{}> on {}".format(plural(b["players"], "player"), b["channel"], day_text(b["when"])))
    if s["last"]:
        l = s["last"]
        grand = spec["prize_names"].get(spec["grand_prize"], "winner") if spec["grand_prize"] else "winner"
        notes.append("*Last game*\n{} in <#{}>{}".format(day_text(l["when"]), l["channel"],
                                                         ", {} <@{}>".format(grand, l["winner"]) if l["winner"] else ""))
    if s["cancelled"]:
        notes.append("*Cancelled*\n{}".format(plural(s["cancelled"], "game")))
    fields += [mrk(clip(n, FIELD_MAX)) for n in notes]
    kids = [{"type": "section", "block_id": look.bid("more"), "fields": [dict(f, text=clip(f["text"], FIELD_MAX)) for f in fields[:10]]}]
    if look.on("panels"):
        return [{"type": "container", "block_id": look.bid("panel"), "title": pt("More {} stats".format(spec["name"]), 150),
                 "subtitle": pt("Most games, hosts, channels, the biggest and the last game", 150),
                 "is_collapsible": True, "default_collapsed": True, "child_blocks": kids}]
    return [section("*More {} stats*".format(sx(spec["name"])), block_id=look.bid("more_title"))] + kids


def you_blocks(look, spec, s, viewer):
    y = s["you"]
    if not viewer:
        return []
    if not (y["games"] or y["prizes"] or y["hosted"]):
        return [context("*You, {}:* no {} games yet. Pick a channel above and press Start.".format(
            PERIOD_LABEL[s["period"]].lower(), sx(spec["name"])))]
    grand = spec["prize_names"].get(spec["grand_prize"], "") if spec["grand_prize"] else ""
    bits = [plural(y["games"], "game"), plural(y["prizes"], "prize")]
    if grand:
        bits.append(plural(y["grand"], grand))
    if y["hosted"]:
        bits.append("hosted {}".format(y["hosted"]))
    if y["rank"]:
        bits.append("#{} on the winners board".format(y["rank"]))
    return [context("*You, {}:* ".format(PERIOD_LABEL[s["period"]].lower()) + "  ·  ".join(sx(b) for b in bits))]


def stats_blocks(look, spec, s, viewer, top):
    blocks = titled(look, "{} {} stats".format(spec["emoji"], spec["name"]),
                    "{}: games, players, winners and more.".format(PERIOD_LABEL[s["period"]]))
    if not (s["counted"] or s["live"] or s["cancelled"]):
        blocks.append(section("No {} games in this period yet. Be the first: pick a channel above and press *Start {}*.".format(
            sx(spec["name"]), sx(spec["name"])), block_id=look.bid("empty")))
        return blocks + you_blocks(look, spec, s, viewer)
    grand = spec["prize_names"].get(spec["grand_prize"], "") if spec["grand_prize"] else ""
    pairs = [("Games played", fmt_int(s["played"]), "{} live".format(len(s["live"])) if s["live"] else ""),
             ("Players", fmt_int(s["players"]), "{} seats taken".format(fmt_int(s["seats"])) if s["seats"] else ""),
             ("Prizes won", fmt_int(s["prizes"]), ""),
             ((grand + "s") if grand else None, fmt_int(s["grand"]), "") if grand else None,
             ("Avg players a game", "{:g}".format(s["avg_players"]), ""),
             ("Channels", fmt_int(len(s["channels"])), "")]
    blocks += tiles(look, "{} numbers".format(spec["name"]), [p for p in pairs if p and p[0]])
    blocks += chart_blocks(look, spec, s)
    blocks += winners_blocks(look, spec, s, top)
    blocks += more_blocks(look, spec, s)
    blocks += you_blocks(look, spec, s, viewer)
    return blocks


def titled(look, title, subtitle):
    """A part's title the way a community home tab draws it: a header with its emoji, a grey line under it."""
    return [{"type": "divider", "block_id": look.bid("divider")}, header(look, title, 2)] + ([context(subtitle)] if subtitle else [])


def you_overview_blocks(look, prof):
    """Your DiceUp: the viewer's totals across every game (all time), then a line for each game they have played."""
    blocks = titled(look, ":bust_in_silhouette: Your DiceUp", "You, in every game, all time.")
    t = prof["total"]
    if not (t["games"] or t["prizes"] or t["hosted"]):
        blocks.append(section("You have not played a game yet. Pick a channel above and press Start: your first "
                              "achievement is one game away.", block_id=look.bid("you_empty")))
        return blocks
    best = prof["best"]
    pairs = [("Games played", fmt_int(t["games"]), "last on {}".format(day_text(prof["last"])) if prof["last"] else ""),
             ("Prizes won", fmt_int(t["prizes"]), ""),
             ("Grand prizes", fmt_int(t["grand"]), ""),
             ("Games hosted", fmt_int(t["hosted"]), ""),
             ("Best place", "#{}".format(best[0]) if best else "-", "{} winners board".format(best[1]["name"]) if best else ""),
             ("Badges", fmt_int(len(prof["badges"])), "")]
    blocks += tiles(look, "Your numbers", pairs)
    lines = []
    for spec, you in prof["per_game"]:
        if not (you["games"] or you["prizes"] or you["hosted"]):
            continue
        grand = spec["prize_names"].get(spec["grand_prize"], "") if spec["grand_prize"] else ""
        bits = [plural(you["games"], "game"), plural(you["prizes"], "prize")]
        if grand:
            bits.append(plural(you["grand"], grand))
        if you["hosted"]:
            bits.append("hosted {}".format(you["hosted"]))
        if you["rank"]:
            bits.append("#{} of {}".format(you["rank"], you["of"]))
        lines.append("{} *{}*  ·  {}".format(spec["emoji"], sx(spec["name"]), "  ·  ".join(sx(b) for b in bits)))
    if prof["favourite"] and len(lines) > 1:
        lines.append("_Favourite: {}_".format(sx(prof["favourite"]["name"])))
    if lines:
        blocks.append(section("\n".join(lines), block_id=look.bid("you_games")))
    return blocks


def achievement_blocks(look, prof):
    """My achievements: a badge for every milestone reached, newest first (cards, else lines)."""
    blocks = titled(look, ":medal: My achievements", "Badges you earned by reaching a milestone in a game.")
    badges = prof["badges"]
    if not badges:
        blocks.append(context("No badges yet. Play your first game to earn one."))
        return blocks
    if look.on("cards"):
        cards = []
        for b in badges[:10]:
            j = b["journey"]
            card = {"type": "card", "block_id": look.bid("badge"),
                    "title": mrk(clip(":{}: *{}*".format(b["medal"], sx(j["name"])), CARD_TEXT)),
                    "subtitle": mrk(clip("{} · {}".format(sx(j["game"]), b["tier"]), CARD_TEXT)),
                    "body": mrk(clip("Earned on {}\n_Awarded for: {}_".format(day_text(b["when"]) if b["when"] else "an unknown day",
                                                                               sx(b["label"]).lower()), CARD_BODY))}
            if re.match(r"^https://\S+$", j["image_url"]):
                card["hero_image"] = {"type": "image", "image_url": j["image_url"], "alt_text": clip(j["name"], 100)}
            cards.append(card)
        blocks.append({"type": "carousel", "block_id": look.bid("badges"), "elements": cards})
    else:
        lines = [":{}: *{}* ({}, {})  ·  earned on {}".format(b["medal"], sx(b["journey"]["name"]), sx(b["journey"]["game"]),
                                                              b["tier"], day_text(b["when"]) if b["when"] else "an unknown day")
                 for b in badges[:10]]
        blocks.append(section("\n".join(lines), block_id=look.bid("badges")))
    if len(badges) > 10:
        blocks.append(context("and {} more".format(len(badges) - 10)))
    return blocks


STATUS_LINE = {"done": "🏅 Completed", "live": "🟢 In progress", "new": "⚪ Not started"}


def journey_text(p):
    j = p["journey"]
    marks = "\n".join("{} {}".format("✅" if p["count"] >= n else "⬜", sx(label)) for n, label in zip(j["steps"], j["labels"]))
    return "{} {} / {}\n{}".format(bar(p["done"], len(j["steps"])), p["done"], len(j["steps"]), marks)


def journey_blocks(look, prof):
    """My journeys: each game's milestones, a progress bar and a checklist (cards, else fields)."""
    blocks = titled(look, ":triangular_flag_on_post: My journeys", "Your milestones in each game. Every one you reach is a badge.")
    shown = prof["journeys"][:10]
    if not shown:
        return []
    if look.on("cards"):
        cards = []
        for p in shown:
            j = p["journey"]
            card = {"type": "card", "block_id": look.bid("journey"),
                    "title": mrk(clip("{} *{}*".format(j["emoji"], sx(j["name"])), CARD_TEXT)),
                    "subtitle": mrk(clip("{} · {}".format(sx(j["game"]), STATUS_LINE[p["status"]]), CARD_TEXT)),
                    "body": mrk(clip(journey_text(p), CARD_BODY))}
            if re.match(r"^https://\S+$", j["image_url"]):
                card["hero_image"] = {"type": "image", "image_url": j["image_url"], "alt_text": clip(j["name"], 100)}
            cards.append(card)
        blocks.append({"type": "carousel", "block_id": look.bid("journeys"), "elements": cards})
        return blocks
    fields = [mrk(clip("*{}* · {}\n_{}_\n{}".format(sx(p["journey"]["name"]), sx(p["journey"]["game"]), STATUS_LINE[p["status"]],
                                                    journey_text(p)), FIELD_MAX)) for p in shown]
    for start in range(0, len(fields), 10):
        blocks.append({"type": "section", "block_id": look.bid("journeys"), "fields": fields[start:start + 10]})
    return blocks


def period_select(period):
    options = [{"text": pt(label), "value": key} for key, label, _d in PERIODS]
    return {"type": "static_select", "action_id": ACT_PERIOD, "placeholder": pt("Period"), "options": options,
            "initial_option": next(o for o in options if o["value"] == period)}


def build_view(look, ctx):
    """The home tab: {type: home, private_metadata, blocks}."""
    games, stats_by_key, period = ctx["games"], ctx["stats"], ctx["period"]
    blocks = [header(look, ":game_die: DiceUp", 1),
              context("Games to play together in Slack. Start one in any channel, then come back for the scores."
                      + ("  ·  *DEV data*" if ctx["env"] == "dev" else ""))]
    notice = ctx.get("notice")
    if notice:
        block = section(notice["text"], block_id="dh_notice")
        if notice.get("url"):
            block["accessory"] = {"type": "button", "text": pt(notice.get("button") or "Open"), "url": notice["url"],
                                  "action_id": LINK_PREFIX + "notice"}
        blocks.append(block)
    blocks += titled(look, ":joystick: Available games", "Pick a channel, then press Start on a game. "
                                                          "Only you see the setup card it opens there.")
    blocks.append(where_block(look, ctx.get("last_channel")))
    blocks += game_blocks(look, games, stats_by_key)

    prof = ctx.get("profile")
    if prof and ctx["viewer"]:
        blocks += you_overview_blocks(look, prof)
        if prof["total"]["games"] or prof["total"]["hosted"]:
            blocks += achievement_blocks(look, prof)
        blocks += journey_blocks(look, prof)

    shown = [g for g in games if not g["coming_soon"] and g["key"] in stats_by_key]
    if shown:
        blocks += titled(look, ":bar_chart: At a glance", "Every game together. The period applies to everything below.")
        blocks.append({"type": "actions", "block_id": look.bid("controls"), "elements": [
            period_select(period), {"type": "button", "text": pt("Refresh"), "action_id": ACT_REFRESH, "value": "refresh"}]})
        total = all_stats([stats_by_key[g["key"]] for g in shown])
        blocks += tiles(look, "All games", [("Games played", fmt_int(total["played"]), PERIOD_LABEL[period].lower()),
                                            ("Seats taken", fmt_int(total["seats"]), ""),
                                            ("Prizes won", fmt_int(total["prizes"]), ""),
                                            ("Live now", fmt_int(total["live"]), "")])
        live = live_lines(shown, stats_by_key)
        if live:
            blocks.append(section("*Live now*\n" + "\n".join(live[:10]), block_id=look.bid("live")))
        for spec in shown:
            blocks += stats_blocks(look, spec, stats_by_key[spec["key"]], ctx["viewer"], ctx["top"])
    notes = []
    if ctx.get("partial"):
        notes.append("The stats cover the first {} rows read; there are more.".format(fmt_int(ctx["rows"])))
    if ctx.get("read_failed"):
        notes.append("The game table could not be read just now, so the numbers may be missing. Press Refresh to try again.")
    notes.append("Updated <!date^{}^{{date_short_pretty}} at {{time}}|just now>".format(int(ctx["now"])))
    blocks.append(context(*notes))
    blocks = fit(blocks)
    meta = json.dumps({"p": period, "c": ctx.get("last_channel") or ""}, separators=(",", ":"))
    return {"type": "home", "private_metadata": meta[:3000], "blocks": blocks}


def fit(blocks):
    """At most MAX_BLOCKS: the last game parts go first (the footer is kept)."""
    if len(blocks) <= MAX_BLOCKS:
        return blocks
    foot = blocks[-1]
    kept = blocks[:MAX_BLOCKS - 2]
    while kept and kept[-1].get("type") == "divider":
        kept.pop()
    return kept + [context("More games than one page holds: the rest are not shown."), foot]


def refused(error, blocks, look):
    """The features Slack named in an invalid_blocks error (json pointers like /blocks/7/...), else the next in PEEL."""
    found = []
    for match in re.finditer(r"/blocks/(\d+)", error):
        index = int(match.group(1))
        if index >= len(blocks):
            continue
        block = blocks[index]
        kind = block.get("type")
        feature = "headers" if kind == "header" and "level" in block else FEATURE_OF.get(kind)
        if kind == "section" and "fields" in block and look.on("adaptive"):
            feature = "adaptive"
        if feature and look.on(feature) and feature not in found:
            found.append(feature)
    if found:
        return found
    return next(([f] for f in PEEL if look.on(f)), [])


def publish(token, user_id, ctx, look, result, warnings):
    """views.publish, a refused feature taken out at a time, down to the plain view. True when published."""
    last_error = ""
    for _attempt in range(len(FEATURES) + 2):
        try:
            view = build_view(look, ctx)
        except Exception as error:                                      # noqa: BLE001 - a building bug must not cost the page
            warnings.append("building the view failed ({}: {}); the plain view was tried".format(type(error).__name__,
                                                                                               clip(str(error), 160)))
            if not look.features:
                result["error"] = "the home view could not be built"
                return False
            look = look.without(look.features)
            continue
        result["view_json"] = json.dumps(view, ensure_ascii=False)
        result["blocks"] = len(view["blocks"])
        result["look_used"] = ",".join(f for f in FEATURES if look.on(f)) or "plain"
        if ctx.get("preview"):
            return True
        body, error = slack(token, "views.publish", {"user_id": user_id, "view": view})
        if body is not None:
            result["published"] = True
            return True
        last_error = error
        if "invalid_blocks" not in error and "invalid_arguments" not in error:
            break
        drop = refused(error, view["blocks"], look)
        if not drop:
            break
        warnings.append("Slack refused {} on the home tab ({}); published without it".format(", ".join(drop), clip(error, 200)))
        look = look.without(drop)
    result["error"] = "the home tab was not published: " + clip(last_error, 300)
    return False


# ============================================================================================= the request


def read_payload(inp):
    raw = inp.get("payload")
    if isinstance(raw, str) and raw.strip().startswith("payload="):
        from urllib.parse import parse_qs
        raw = (parse_qs(raw.strip()).get("payload") or [""])[0]
    data = parse_json(raw, {})
    if isinstance(data, dict) and len(data) == 1 and isinstance(next(iter(data.values())), dict) \
            and "actions" in next(iter(data.values())):
        data = next(iter(data.values()))                                # Workato's {"block_actions:button": {...}} wrapper
    return data if isinstance(data, dict) else {}


def picked_channel(state):
    """The channel chosen in the home tab's picker, from view.state.values (any picker whose id starts ACT_CHANNEL)."""
    values = as_dict(as_dict(state).get("values"))
    for block in values.values():
        for action_id, element in as_dict(block).items():
            if action_id.startswith(ACT_CHANNEL):
                element = as_dict(element)
                chosen = element.get("selected_conversation") or element.get("selected_channel")
                if chosen:
                    return text_of(chosen)
    return ""


def parse_click(inp):
    payload = read_payload(inp)
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    action = as_dict(actions[0]) if actions else {}
    view = as_dict(payload.get("view"))
    period_choice = as_dict(action.get("selected_option")).get("value") if action.get("action_id") == ACT_PERIOD else ""
    return {
        "action_id": text_of(inp.get("action_id") or action.get("action_id")).strip(),
        "value": text_of(inp.get("value") or action.get("value")).strip(),
        "user_id": text_of(inp.get("user_id") or as_dict(payload.get("user")).get("id")).strip(),
        "channel": text_of(inp.get("selected_channel")).strip() or picked_channel(view.get("state"))
        or text_of(action.get("selected_conversation")).strip(),
        "period": text_of(inp.get("selected_period") or period_choice).strip(),
        "metadata": parse_json(inp.get("private_metadata") or view.get("private_metadata"), {}),
    }


def announce(token, channel, user, spec, warnings):
    """(ts, problem): the line in the channel that says a game is being set up. Joins a public channel it is not in."""
    text = "<@{}> is setting up a game of *{}* here {}".format(user, spec["name"], spec["emoji"]).strip()
    message = {"channel": channel, "text": text, "unfurl_links": False}
    body, error = slack(token, "chat.postMessage", message)
    if body is None and "not_in_channel" in error and channel.startswith("C"):
        joined, join_error = slack(token, "conversations.join", {"channel": channel})
        if joined is None:
            warnings.append("could not join the channel: " + clip(join_error, 200))
        else:
            body, error = slack(token, "chat.postMessage", message)
    if body is not None:
        return text_of(body.get("ts")), ""
    if "not_in_channel" in error or "channel_not_found" in error:
        return "", "invite"
    return "", error


def permalink(token, channel, ts):
    if not (channel and ts):
        return ""
    url = SLACK_API + "chat.getPermalink?channel={}&message_ts={}".format(channel, ts)
    body, error = _send_json(url, {"Authorization": "Bearer " + token}, None, "GET")
    return text_of(as_dict(body).get("permalink")) if not error and as_dict(body).get("ok") else ""


def do_start(token, click, games, result, warnings, announce_start):
    """The Start button. -> the notice for the home tab. Fills the start_* outputs when the game can be handed off."""
    key = click["action_id"][len(ACT_START):] or click["value"]
    spec = next((g for g in games if g["key"] == key), None)
    if not spec or spec["coming_soon"]:
        return {"text": ":warning: That game cannot be started yet."}
    channel = click["channel"]
    if not channel:
        return {"text": ":point_up: *Pick a channel first*, in the picker under Available games, then press *Start {}* "
                        "again.".format(sx(spec["name"]))}
    ts, problem = "", ""
    if announce_start:
        ts, problem = announce(token, channel, click["user_id"], spec, warnings)
    if problem == "invite":
        return {"text": ":wave: I am not in <#{}> yet. Type `/invite @DiceUp` there (or add the app from the channel's "
                        "settings), then press *Start {}* again.".format(channel, sx(spec["name"]))}
    if problem:
        result["error"] = "could not post in the channel: " + clip(problem, 300)
        return {"text": ":warning: I could not post in <#{}>: {}".format(channel, sx(clip(problem, 200)))}
    result.update({"start_game": spec["key"], "start_text": spec["word"], "start_channel": channel,
                   "start_user_id": click["user_id"], "start_message_ts": ts})
    link = permalink(token, channel, ts) if ts else ""
    result["start_permalink"] = link
    return {"text": ":white_check_mark: *{} is on its way to <#{}>.* Your setup card, which only you see, is waiting "
                    "there.".format(sx(spec["name"]), channel),
            "url": link or "https://slack.com/app_redirect?channel={}".format(channel), "button": "Open channel"}


# ============================================================================================= entry point

OUTPUT_DEFAULTS = (("ok", False), ("error", ""), ("warnings", []), ("mode", ""), ("action", ""), ("skipped", ""),
                   ("user_id", ""), ("env", ""), ("period", ""), ("published", False), ("look_used", ""), ("blocks", 0),
                   ("view_json", ""), ("rows_read", 0), ("partial", False), ("games_shown", 0), ("notice", ""),
                   ("start_game", ""), ("start_text", ""), ("start_channel", ""), ("start_user_id", ""),
                   ("start_message_ts", ""), ("start_permalink", ""),
                   ("your_games", 0), ("your_prizes", 0), ("your_grand_prizes", 0), ("your_hosted", 0), ("your_badges", 0),
                   ("your_stats_json", ""), ("elapsed_ms", 0))


def load_rows(inp, games, env, deadline, warnings):
    """(rows, hidden users, partial, failed). Every row of the shown games, and who opted out of the leaderboards."""
    token = text_of(inp.get("workato_api_token")).strip()
    if not token:
        warnings.append("no workato_api_token: the stats are empty")
        return [], set(), False, True
    table = Table(token, env)
    keys = sorted({g["key"] for g in games if not g["coming_soon"]})
    if not keys:
        return [], set(), False, False
    kinds = sorted({k for g in games for k in g["rows"].values()})
    max_pages = max(1, min(200, to_int(inp.get("max_pages"), MAX_PAGES)))
    rows, ok = table.query({"$and": [{"record_type": {"$in": keys}}, {"row_type": {"$in": kinds}}]}, COLUMNS,
                           max_pages=max_pages, deadline=deadline)
    hidden_rows, _ok = table.query({"leaderboard_optout": {"$eq": True}}, ["slack_user_id"], max_pages=5, deadline=deadline)
    warnings.extend(table.errors)
    return rows, {text_of(r.get("slack_user_id")) for r in hidden_rows if r.get("slack_user_id")}, table.capped, not ok


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    started = _now()
    result = {k: (list(v) if isinstance(v, list) else v) for k, v in OUTPUT_DEFAULTS}
    warnings = result["warnings"]
    inp = input if isinstance(input, dict) else {}
    try:
        run(inp, result, warnings, started)
    except Exception as error:                                          # noqa: BLE001 - the recipe must still finish
        result["ok"] = False
        result["error"] = "unexpected {}: {}".format(type(error).__name__, clip(str(error), 300))
    result["elapsed_ms"] = int((_now() - started) * 1000)
    return result


def run(inp, result, warnings, started):
    token = text_of(inp.get("slack_bot_token")).strip()
    env = env_named(inp.get("env"))
    preview = truthy(inp.get("preview"))
    result["env"] = env
    is_click = bool(text_of(inp.get("payload")).strip() or text_of(inp.get("action_id")).strip())
    result["mode"] = "click" if is_click else "home"
    games = game_list(inp.get("games_json"), warnings)

    notice, last_channel = None, ""
    if is_click:
        click = parse_click(inp)
        result["user_id"], result["action"] = click["user_id"], click["action_id"]
        meta = as_dict(click["metadata"])
        period = period_of(click["period"] or meta.get("p") or inp.get("period"))
        last_channel = text_of(meta.get("c"))
        if not click["action_id"].startswith(ACTION_PREFIX):
            result.update({"ok": True, "skipped": "not a DiceUp home action: {!r}".format(clip(click["action_id"], 80))})
            return
        if click["action_id"].startswith(ACT_CHANNEL):
            result.update({"ok": True, "action": "channel", "skipped": "a channel was picked: nothing to do until Start"})
            return
        if not click["user_id"]:
            result["error"] = "user_id is needed (map payload, or user_id)"
            return
        if not token and not preview:
            result["error"] = "slack_bot_token is required"
            return
        if click["action_id"].startswith(ACT_START):
            result["action"] = "start"
            notice = do_start(token, click, games, result, warnings, truthy(inp.get("announce_start"), True) and not preview)
            if click["channel"] and result["start_game"]:
                last_channel = click["channel"]
        elif click["action_id"] == ACT_PERIOD:
            result["action"] = "period"
        elif click["action_id"] == ACT_REFRESH:
            result["action"] = "refresh"
        else:
            result.update({"ok": True, "action": "unknown", "skipped": "no such action: {!r}".format(click["action_id"])})
            return
        user = click["user_id"]
    else:
        user = text_of(inp.get("user_id")).strip()
        result["user_id"] = user
        if text_of(inp.get("tab")).strip().lower() == "messages":
            result.update({"ok": True, "skipped": "the Messages tab was opened, not Home"})
            return
        if not user:
            result["error"] = "user_id is needed: map event.user of app_home_opened"
            return
        if not token and not preview:
            result["error"] = "slack_bot_token is required"
            return
        meta = as_dict(parse_json(inp.get("private_metadata"), {}))
        period = period_of(meta.get("p") or inp.get("period"))
        last_channel = text_of(meta.get("c"))
        result["action"] = "open"

    now = as_ts(inp.get("now")) or _now()
    budget = max(10, min(85, to_int(inp.get("time_budget"), TIME_BUDGET)))
    rows, hidden, partial, failed = load_rows(inp, games, env, started + budget - 8, warnings)
    playable = [g for g in games if not g["coming_soon"]]
    stats = {g["key"]: game_stats(rows, g, period, now, user, hidden) for g in playable}
    # the viewer's own history is all time, whatever the period dropdown says
    stats_all = stats if period == "all" else {g["key"]: game_stats(rows, g, "all", now, user, hidden) for g in playable}
    prof = profile(playable, stats_all, user)
    result.update({"your_games": prof["total"]["games"], "your_prizes": prof["total"]["prizes"],
                   "your_grand_prizes": prof["total"]["grand"], "your_hosted": prof["total"]["hosted"],
                   "your_badges": len(prof["badges"]), "your_stats_json": json.dumps({
                       "total": prof["total"], "badges": len(prof["badges"]),
                       "per_game": {spec["key"]: {k: you.get(k, 0) for k in ("games", "prizes", "grand", "hosted", "rank", "of")}
                                    for spec, you in prof["per_game"]}}, separators=(",", ":"))})
    top = max(1, min(25, to_int(inp.get("top_n"), TOP_N)))
    look = Look(choice(inp.get("features"), FEATURES, DEFAULT_FEATURES))
    ctx = {"games": games, "stats": stats, "period": period, "env": env, "viewer": user, "top": top, "now": now,
           "notice": notice, "last_channel": last_channel, "profile": prof, "rows": len(rows), "partial": partial,
           "read_failed": failed and bool(text_of(inp.get("workato_api_token")).strip()), "preview": preview}
    result.update({"period": period, "rows_read": len(rows), "partial": partial, "games_shown": len(games),
                   "notice": notice["text"] if notice else ""})
    published = publish(token, user, ctx, look, result, warnings)
    result["ok"] = published and not result["error"]


if __name__ == "__main__":
    # A look at the page without the network: python3 diceup_home.py [rows.json]  -> {"blocks": [...]} for Block Kit Builder.
    sample = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
    def _send_json(url, headers, payload=None, method="POST", timeout=HTTP_TIMEOUT):     # noqa: F811
        if "leaderboard_optout" in json.dumps(payload or {}):
            return {"schema": [[{"name": "slack_user_id"}]], "data": []}, None
        return {"schema": [[{"name": c} for c in COLUMNS]], "data": [[[r.get(c) for c in COLUMNS]] for r in sample]}, None
    out = main({"user_id": "UVIEWER", "workato_api_token": "local", "preview": "yes"})
    print(json.dumps({"blocks": json.loads(out["view_json"] or "{}").get("blocks", [])}, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items() if k != "view_json"}, indent=2), file=sys.stderr)
