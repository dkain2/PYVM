"""
Generic activity leaderboard for the shared Workato data table.

Use this as a Workato Python step, or run it locally for a dry run.

GAMES: activity = imemory, iadd, isub or imultiple (imultiply works too) posts that
game's board from the same step, with the same snapshot, rank-change and trend
machinery. Nothing but `activity` is needed to switch -- the row type, title and icon
are looked up (see GAMES below). A game row holds ONE best score per player (plus the
time of that run and the games played), not a log of sessions, so a game board ranks
on best score, with the faster run winning a tie. "min_days" then means minimum games
played, and defaults to 1.

THE GREAT WALK: activity = greatwalk (great_walk, "great walk" and walk work too) posts the
channel's walk round the world as a shared dashboard, not a board: nobody is ranked or
named. A banner; a one-line summary with the totals under it; a divider; the road along
this leg as a line of emoji (a walker on it between its two flags, the way walked since
the last board in yellow) and what changed since then (km added, how many people added
steps, any stops reached); and the route as a labelled strip (stops reached, the walkers,
the next stop and when it lands at the current pace, how many more, the finish). Slack's
native carousel tells the same story in cards. It reads the same step rows as the step
board; every step counts towards the walk, so min_days defaults to 0 here. There is no table and no thread. It
keeps its own snapshot row (greatwalk_leaderboard), which is where "since the last board"
and the pace come from. By default the post carries the storyboard as a one-line route
strip and the carousel goes in a thread reply (see walk_layout). If a workspace rejects the
carousel block, the strip alone tells the story. The route is the one in channel_summary.py (see "journey" below).

WEEKLY CHALLENGES: activity = challenge (challenges, weekly_challenge and wc work too) posts a
board of who has cleared the most weekly challenges (weekly_challenge.py), all time. Nothing
but `activity` is needed. The count is kept by the challenge steps on each person's rows of the
activities and games ("wc_counts": taken on and cleared, in the row's `content`); this adds it up
across all of a person's rows, so one person is one line however many activities they cleared.
Ranked on challenges cleared (equal counts share a rank); people who have cleared none are not
on it. It has the same snapshot, rank-change and trend machinery as the others ("added" is what
was cleared since the last board). Columns: name, cleared, added, taken, cats (how many different
categories they have cleared one in). Under the table a line names the crew's most cleared
categories, and a thread reply, "Who cleared what", lists each category with who cleared it and how
many. Optional columns, OFF by default: show_average (rate: cleared out of taken) and show_week
(week: cleared since Monday). show_categories = false drops the cats column and the line;
category_thread = false drops the thread reply. It reads every activity and game row, so it is a
wider read than the others.

Important input fields:
    workato_dev_api    Workato API token. Required unless local_data_file is set.
    channel_id         Slack channel to include in post_message_body.
    activity           Activity key, for example step, pushup, plank, swim, or a game:
                       imemory, iadd, isub, imultiple. greatwalk (or great_walk) for
                       the Great Walk dashboard.
    top_n              Number of rows to show. Default: 10.
    unit               Optional: count, seconds, or minutes.
    title              Optional board title. Default is activity.title().
    noun               Optional footer noun. Default is activity.
    icon               Optional Slack emoji shortcode.
    header_image_url   Optional image URL. When set, shows a Slack image block
                       just above the board instead of the text heading. On the Great
                       Walk this is the banner; it must be a public https URL.
    walk_layout        Optional, Great Walk only. thread (default): a one-line route
                       strip in the post and the carousel of cards (reached, on the
                       road, next, then, home) in a thread reply. strip: the strip
                       only. carousel: the carousel in the post, no strip.
    use_carousel       Optional boolean, Great Walk only. false is walk_layout = strip.
    set_based          Optional boolean. Shows both best day and best set.
    best_phrase        Optional footer phrase for best effort.
    min_days           Optional minimum logged days to appear. Default: 5.
    min_total_percent  Optional percent of qualified leader's total required.
    max_total_gap      Optional max absolute gap from qualified leader's total.
    slack_bot_token    Slack bot token. The script posts the message itself.
    thread_full_list   Optional boolean. Reply in the thread with everyone the channel
                       message does not show (ranks after top_n, then people still
                       getting started). Default: true.
    show_average       Optional boolean. Adds an avg/day column (total / days logged)
                       to an activity board; games and the Great Walk have none.
                       Default: true. On the challenge board it adds the clear-rate
                       column instead (cleared out of taken), and defaults to false.
    show_week          Optional boolean, challenge board only. Adds a "week" column: challenges
                       cleared since Monday (UTC). Default: false.
    show_categories    Optional boolean, challenge board only. The "cats" column (how many
                       categories each person has cleared) and the "most cleared" line under
                       the table. Default: true.
    category_thread    Optional boolean, challenge board only. A thread reply, "Who cleared
                       what": each category with who cleared it and how many. Default: true.
    average_min_days   Optional integer. The avg/day column shows "-" for anyone with fewer
                       logged days than this, so a few big days do not top the column.
                       Applies to every activity. Default: 14. 0 shows everyone.
    save_snapshot      Optional boolean. Default true. Set false to post to Slack
                       without writing the snapshot row, e.g. when testing. Changes
                       are still compared against the existing snapshot.
    snapshot_row_type  Optional override of the snapshot row_type. Use a test value
                       such as workout_leaderboard_test to try rank changes and
                       trend without touching the real snapshot.
    up_marker          Optional character for a rank gain. Default: \u25b2
    down_marker        Optional character for a rank drop. Default: red down triangle.
                       Use Unicode, not :shortcodes:, which do not render in a code block.
    history_runs       Optional integer. Past runs kept for the trend column.
                       Default: 12. Allowed 1 to 26.
    dry_run            Optional boolean. Posts the board to Slack as usual but stores
                       nothing: the snapshot row is not written, so the next real run
                       still compares against the last saved board. (save_snapshot =
                       false does the same.) The payloads come back in "preview".
    local_data_file    Optional exported Workato JSON file for local testing.
    local_snapshot_file  Optional JSON file used instead of the data table for the
                       snapshot, so rank changes can be tested offline.

Rank changes: every post saves the board as a snapshot row in the data table
(row_type <activity>_leaderboard). For each person it keeps, per run, the rank,
total, best day, best set and days logged, plus their name, for the last
history_runs runs. The next post compares against it: places moved, amount
added, the trend, and the "since the last board" lines. The thread carries the
rest of the ranked list, then people still under min_days. Equal totals share a
rank (shown T2).

Storage: a text column holds 10,000 characters, so the snapshot JSON is split
into 9,500 character pieces and written across STORE_COLUMNS in order (spare
columns on the leaderboard row; the _leaderboard row type is its own, and the
other scripts only read rows whose row_type ends in _users). If a board is too
big even for all of them, the oldest runs are dropped. A snapshot row that
cannot be read is reported and left alone, never overwritten.

Changing the snapshot later, without breaking what is saved:
    * A new column: append it to STORE_COLUMNS (never reorder or remove one).
    * A new per-person fact: add a series in pack_snapshot / parse_snapshot and
      bump SNAPSHOT_VERSION. Readers ignore series they do not know and treat a
      missing one as empty, and earlier versions (1 to 3) are still read.

Output: a short status dict. The Slack message is posted here, not returned.
"""

import argparse
import json
import math
import os
import re
import sys
import zlib
from datetime import datetime, timedelta, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request

TABLE_ID = "0b863cb1-4712-416b-a9d5-7bf7f2f9b059"
TABLE_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
HTTP_TIMEOUT = 30

TOP_N = 10
MIN_DAYS = 5
AVERAGE_MIN_DAYS = 14
STRIDE_M = 0.715
MARATHON_KM = 42.195
NAME_WIDTH = 18

SNAPSHOT_SUFFIX = "_leaderboard"
SNAPSHOT_VERSION = 4
# A Workato text column holds 10,000 characters. The snapshot JSON is split into
# pieces of COLUMN_CHUNK and written across these columns in order, so the
# capacity is the piece size times the number of columns. golden_dates stays
# first because earlier versions saved there; append new columns, never reorder.
STORE_COLUMNS = (
    "golden_dates", "heatmap_dates", "total", "plank_photo",
    "current_weight", "current_fat", "current_muscle",
)
COLUMN_LIMIT = 10000
COLUMN_CHUNK = 9500
SNAPSHOT_CAPACITY = COLUMN_CHUNK * len(STORE_COLUMNS)
# Room kept free for the integrity header written in front of the JSON.
SNAPSHOT_ROOM = SNAPSHOT_CAPACITY - 64
# What each run records per person, in this order: rank, total, best day, best set, days.
RANK, TOTAL, BEST, BEST_SET, DAYS = range(5)
SERIES = (("r", RANK), ("t", TOTAL), ("b", BEST), ("s", BEST_SET), ("d", DAYS))
HISTORY_RUNS = 12
# Trend column: latest run on the right, one bar per run gap.
TREND_WIDTH = 8
TREND_BARS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
TREND_IDLE = "\u00b7"
# Slack rejects a section whose text passes 3000 characters, so a long table is
# split across several code blocks.
SLACK_SECTION_LIMIT = 2800
# Rank-move markers, overridable with up_marker / down_marker. They sit inside a
# code block, where Slack does not convert :shortcodes:, so use Unicode.
UP_MARKER = "\u25b2"
DOWN_MARKER = "\U0001f53b"
FLAT = "-"

DEFAULT_UNITS = {
    "plank": "seconds",
    "swim": "minutes",
    "yoga": "minutes",
    "meditate": "minutes",
}
DEFAULT_ICONS = {
    "greatwalk": ":world_map:",
    "plank": ":plank-4:",
    "pushup": ":plank-3:",
    "step": ":athletic_shoe:",
    "swim": ":swimmer:",
    "yoga": ":person_in_lotus_position:",
    "meditate": ":brain:",
}
DEFAULT_NOUNS = {
    "greatwalk": "steps",
    "plank": "plank time",
    "pushup": "pushups",
    "step": "steps",
    "swim": "swim time",
    "yoga": "yoga time",
    "meditate": "meditation",
}
DEFAULT_TITLES = {
    "greatwalk": "The Great Walk",
    "plank": "Plank",
    "pushup": "Pushups",
    "step": "Steps",
    "swim": "Swim",
    "yoga": "Yoga",
    "meditate": "Meditation",
}
DEFAULT_SET_BASED = {"pushup"}
DEFAULT_BEST_PHRASES = {
    "greatwalk": "Biggest single day",
    "plank": "Longest single hold",
    "pushup": "Biggest single set",
    "step": "Biggest single day",
    "swim": "Longest single swim",
    "yoga": "Longest single session",
    "meditate": "Longest single sit",
}

# The memory and maths games. They keep one row per player -- best score in
# personal_best_single_set, the time of that run in total (as text, "12.4"), games
# played in total_planks -- so they rank on best score, not on a running total.
# `activity` is the only input a game board needs; the rest comes from here.
GAMES = {
    "imemory":   {"row_type": "object_memory_user", "title": "iMemory",   "icon": ":brain:"},
    "iadd":      {"row_type": "math_add_user",      "title": "iAdd",      "icon": ":heavy_plus_sign:"},
    "isub":      {"row_type": "math_sub_user",      "title": "iSub",      "icon": ":heavy_minus_sign:"},
    "imultiple": {"row_type": "math_mul_user",      "title": "iMultiple", "icon": ":heavy_multiplication_x:"},
}
GAME_ALIASES = {"imultiply": "imultiple"}
GAME_MIN_GAMES = 1

# The weekly challenge board. A person's challenges taken on and cleared are counted on each of
# their rows of an activity or a game (weekly_challenge.py: "wc_counts" in `content`), so the board
# reads all of those rows and adds them up per person. KEEP THESE ROW TYPES IN STEP WITH
# weekly_challenge.py (ACTIVITIES and GAMES): test_leaderboard_challenge.py fails if they drift.
CHALLENGE_KEY = "challenge"
CHALLENGE_ALIASES = ("challenges", "weekly_challenge", "weekly_challenges", "wc")
# row type -> (label, icon): the category a row's cleared count belongs to. Labels and icons are the
# ones weekly_challenge.py uses; a game's two challenges (play it, score in it) share one row, so a
# game is one category. Kept in step by the same test.
CHALLENGE_CATEGORIES = {
    "pushup_users": ("Pushups", ":plank-3:"), "pullup_users": ("Pullups", ":muscle:"),
    "squat_users": ("Squats", ":leg:"), "plank_users": ("Plank", ":plank-4:"),
    "workout_users": ("Workouts", ":weight_lifter:"), "run_users": ("Running", ":runner:"),
    "swim_users": ("Swimming", ":swimmer:"), "cycle_users": ("Cycling", ":bicyclist::skin-tone-4:"),
    "cardio_users": ("Cardio", ":heartpulse:"), "step_users": ("Steps", ":athletic_shoe:"),
    "stairs_users": ("Stairs", ":stairs:"), "dance_users": ("Dancing", ":dancer:"),
    "cold_shower_users": ("Cold showers", ":cold_face:"), "hydrate_users": ("Water", ":droplet:"),
    "yoga_users": ("Yoga", ":person_in_lotus_position:"), "meditate_users": ("Meditation", ":brain:"),
    "breathe_users": ("Pranayama", ":wind_blowing_face:"), "chant_users": ("Chanting", ":winter_singing:"),
    "solitude_users": ("Quiet time", ":crescent_moon:"), "journal_users": ("Journaling", ":writing_hand:"),
    "write_users": ("Writing", ":lower_left_fountain_pen:"), "read_users": ("Reading", ":books:"),
    "learn_users": ("Learning", ":bulb:"), "sketch_users": ("Sketching", ":pencil2:"),
    "paint_users": ("Painting", ":art:"), "eyepushups_users": ("Eye pushups", ":eye:"),
    "math_add_user": ("iAdd", ":heavy_plus_sign:"), "math_sub_user": ("iSub", ":heavy_minus_sign:"),
    "math_mul_user": ("iMultiple", ":heavy_multiplication_x:"), "math_avg_user": ("iAverage", ":bar_chart:"),
    "math_div_user": ("iDivide", ":heavy_division_sign:"), "object_memory_user": ("iMemory", ":brain:"),
    "pairs_memory_user": ("iMatch", ":mahjong:"), "image_memory_user": ("iMemoryImage", ":frame_with_picture:"),
}
CHALLENGE_ROW_TYPES = tuple(CHALLENGE_CATEGORIES)
CHALLENGE_TOP_CATEGORIES = 6      # categories named on the "most cleared" line
CHALLENGE_PEOPLE_PER_CATEGORY = 5 # names on a category's line in the thread, before "+N more"
CHALLENGE_SELECT = ["id", "name", "row_type", "content", "leaderboard_optout"]   # nothing else is needed
CHALLENGE_COUNTS_KEY = "wc_counts"
CHALLENGE_MIN_DAYS = 0
CHALLENGE_ICON = ":crossed_swords:"

# The Great Walk reads the step rows. Every step moves the walk, so nobody is held back by
# min_days (override it to rank fewer people; the walk still counts everyone).
WALK_KEY = "greatwalk"
WALK_ALIASES = ("great_walk", "the_great_walk", "thegreatwalk", "walk")
WALK_ROW_TYPE = "step_users"
WALK_MIN_DAYS = 0
WALK_BAR_CELLS = 15        # squares in the road along this leg
WALK_CROWD_MAX = 5         # walkers drawn on the route strip and the "on the road" card, at most
# Where the walk's storyboard goes. thread: a one-line route strip in the post and the
# carousel in a thread reply (the default -- the post stays short). strip: the strip only.
# carousel: the carousel in the post itself, no strip.
WALK_LAYOUTS = ("thread", "strip", "carousel")
CARD_BODY_LIMIT = 200      # Slack's limit on a card's body
WALK_ETA_MAX_DAYS = 120    # further out than this a pace says nothing, as channel_summary
# The road is a line of emoji squares, which line up and keep their colour in every client
# (a code block would not): the way walked before the last board, the way walked since, a
# marker where the walkers are, the way ahead.
WALK_LEG_TILE = "\U0001F7E9"      # green square: walked before the last board
WALK_RECENT_TILE = "\U0001F7E8"   # yellow square: walked since
WALK_EMPTY = "\u2B1C"             # white square
# The Unicode walker and runner face left in Slack's emoji set, so the walkers are these:
# the workspace's own walker on the leg, and right-facing ones beside the figures below.
WALK_WALKER = ":emoji-walking:"    # on the leg
WALK_FIGURE_WALKING = ":woman_walking_facing_right::skin-tone-4:"   # beside the walkers
WALK_FIGURE_RUNNING = ":woman_running_facing_right::skin-tone-4:"   # beside the marathons
WALK_GLOBE = "\U0001F30D"         # beside the share of the lap
WALK_HOME_ICON = ":coursera:"      # the finish card: back at the office
WALK_ARROW = ":arrow_right:"       # between the steps of the route strip
# Where the walk began, said in the summary so the distance has somewhere to be measured from.
WALK_START = "the Coursera office in Mountain View"
WALK_START_BOLD = "the :office: *Coursera office in Mountain View*"

# Where each maths game's difficulty levels begin, in correct answers. A player whose
# best is `n` is on the level of the last mark at or below n: the same "Level" the
# game's own result card shows. The player rows do not store it -- it follows from the
# best score -- so it is worked out here, for every existing player at once.
# iMemory has no levels (its score already is the round), so it is not listed.
# KEEP IN STEP WITH `TIERS` in imath/imath.py: test_leaderboard_games.py fails if they drift.
GAME_LEVELS = {
    "iadd":      (0, 6, 12, 18, 24, 31, 38, 46, 56, 68),
    "isub":      (0, 6, 12, 18, 24, 31, 38, 46, 56, 68),
    "imultiple": (0, 6, 12, 18, 24, 31, 38, 46, 56, 66, 78, 92),
    "iaverage":  (0, 6, 12, 18, 24, 31, 40, 50, 62),
    "idivide":   (0, 6, 12, 18, 24, 31, 38, 46, 56, 68, 82),
}


def game_points(row, best):
    """A maths player's running total of correct answers, over every game they have played.

    iMath keeps it as "pts" in the row's `content` json. Players whose games were saved
    before it was kept have no tally, so their best score is the least they have earned."""
    try:
        document = json.loads(row.get("content") or "{}")
        stored = int(document.get("pts") or 0) if isinstance(document, dict) else 0
    except (TypeError, ValueError):
        stored = 0
    return max(stored, best)


def game_level(activity, score):
    """The level a best score of `score` reached; 0 for a game with no levels."""
    marks = GAME_LEVELS.get(activity)
    return sum(1 for mark in marks if score >= mark) if marks else 0

COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "total": "e96b5acc-4196-497e-a18b-7faf7016ec4c",
    "personal_best_single_set": "6198fe02-e888-44a8-bd01-b47d75ee896d",
    "total_planks": "ea80e176-5bfb-421d-bafe-dd4828d67916",
    "heatmap_dates": "7f8871d1-1613-4faa-94e6-a7ef3649cc25",
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
    "plank_tier": "b346d073-149f-43c1-b38e-58c14c6358e8",
    "leaderboard_optout": "101f8dcb-f067-4045-af61-0799494651b8",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
    "golden_dates": "b9517b86-4175-4d78-80b1-dfbf832f803c",
    "plank_photo": "f801caa5-b3c2-4f07-a98c-7b2d24c66689",
    "current_weight": "08ec0542-79af-43a9-8d58-de30e14a6c51",
    "current_fat": "ce9c49a6-c1f9-4169-8833-a3721d6c38b5",
    "current_muscle": "ac156767-3d8e-42d1-bcd9-b78ca84b6d51",
}
# Columns only the snapshot row uses; the activity query never selects them.
# heatmap_dates and total are snapshot columns too, but activity rows need them. So are
# plank_photo and the current_* columns -- they are the rest of a person's session list
# (see TOTAL_COLUMNS), which the activity query must read to count a long history.
SNAPSHOT_ONLY_COLUMNS = ("updated_at", "golden_dates")
SELECT_COLUMNS = [name for name in COLUMNS if name not in SNAPSHOT_ONLY_COLUMNS]
LOCAL_COLUMN_KEYS = {name: uuid.replace("-", "_") for name, uuid in COLUMNS.items()}

MEDALS = {1: ":first_place_medal:", 2: ":second_place_medal:", 3: ":third_place_medal:"}


def truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def flag(value, default):
    """A boolean input that is unset (missing, null or blank) keeps its default."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    return truthy(value)


def int_input(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def float_input(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_activity(value):
    activity = str(value or "step").strip().lower().replace(" ", "_").replace("-", "_")
    if activity in WALK_ALIASES:
        return WALK_KEY
    if activity in CHALLENGE_ALIASES:
        return CHALLENGE_KEY
    return GAME_ALIASES.get(activity, activity)


def walk_layout(input_data):
    """thread, strip or carousel (see WALK_LAYOUTS). use_carousel = false is the strip."""
    if not flag(input_data.get("use_carousel"), True):
        return "strip"
    word = str(input_data.get("walk_layout") or "").strip().lower()
    return word if word in WALK_LAYOUTS else WALK_LAYOUTS[0]


def activity_config(input_data):
    activity = clean_activity(input_data.get("activity"))
    unit = (input_data.get("unit") or DEFAULT_UNITS.get(activity) or "").strip().lower()
    if unit in ("reps", "rep", "number", "integer"):
        unit = ""
    if unit == "count":
        unit = ""

    game = GAMES.get(activity)
    walk = activity == WALK_KEY
    challenge = activity == CHALLENGE_KEY
    if game or walk or challenge:
        unit = ""
    default_row_type = game["row_type"] if game else WALK_ROW_TYPE if walk else \
        "weekly_challenge_totals" if challenge else activity + "_users"
    return {
        "activity": activity,
        "game": bool(game),
        "challenge": challenge,
        "row_types": list(CHALLENGE_ROW_TYPES) if challenge else [],
        # The maths games rank on total points (every correct answer, in every game), not on
        # the best single game; iMemory has no running tally and keeps ranking on its best.
        "points": bool(game) and activity in GAME_LEVELS,
        "walk": walk,
        "walk_layout": walk_layout(input_data),
        "row_type": input_data.get("row_type") or default_row_type,
        "unit": unit,
        "title": input_data.get("title") or (game["title"] if game else "Challenges" if challenge else
                                              DEFAULT_TITLES.get(activity) or activity.title()),
        "noun": input_data.get("noun") or ("points" if game else "challenges cleared" if challenge else
                                           DEFAULT_NOUNS.get(activity) or activity.replace("_", " ")),
        "icon": input_data.get("icon") or (game["icon"] if game else CHALLENGE_ICON if challenge else
                                           DEFAULT_ICONS.get(activity) or ""),
        # What a "day" is on this board: logged days for an activity, games played for a game,
        # challenges taken on for the challenge board. `verb` goes with it ("ranked once they have ...").
        "day_noun": ("game", "games") if game else ("challenge", "challenges") if challenge else ("day", "days"),
        "verb": "played" if game else "taken on" if challenge else "logged",
        "gain_label": "biggest jump" if game and activity not in GAME_LEVELS else "most added",
        "roll_verb": "improved" if game and activity not in GAME_LEVELS else "added",
        "image_url": (input_data.get("header_image_url") or "").strip(),
        "set_based": not game and not challenge
                     and (truthy(input_data.get("set_based")) or activity in DEFAULT_SET_BASED),
        "best_phrase": input_data.get("best_phrase") or ("Top score" if game else
                                                         DEFAULT_BEST_PHRASES.get(activity) or ""),
        "stride_m": float_input(input_data.get("stride_m"), STRIDE_M),
        "min_days": max(0, int_input(input_data.get("min_days"),
                                     GAME_MIN_GAMES if game else WALK_MIN_DAYS if walk else
                                     CHALLENGE_MIN_DAYS if challenge else MIN_DAYS)),
        "min_total_percent": max(0.0, float_input(input_data.get("min_total_percent"), 0.0)),
        "max_total_gap": max(0, int_input(input_data.get("max_total_gap"), 0)),
        "snapshot_row_type": input_data.get("snapshot_row_type") or activity + SNAPSHOT_SUFFIX,
        "save_snapshot": flag(input_data.get("save_snapshot"), True),
        "thread_full_list": flag(input_data.get("thread_full_list"), True),
        # (the challenge board's only average is its clear rate, and it is off until asked for)
        "show_average": flag(input_data.get("show_average"), not challenge),
        # (challenge board only)
        "show_week": challenge and flag(input_data.get("show_week"), False),
        "show_categories": challenge and flag(input_data.get("show_categories"), True),
        "category_thread": challenge and flag(input_data.get("category_thread"), True),
        "average_min_days": max(0, int_input(input_data.get("average_min_days"), AVERAGE_MIN_DAYS)),
        "up_marker": input_data.get("up_marker") or UP_MARKER,
        "down_marker": input_data.get("down_marker") or DOWN_MARKER,
        "history_runs": max(1, min(int_input(input_data.get("history_runs"), HISTORY_RUNS), 26)),
    }


def send_json(url, headers, payload, method="POST"):
    """Returns (body, error). Never raises on an HTTP or network failure."""
    request = urllib_request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method=method
    )
    try:
        with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, "{} {}: {}".format(url.split("/")[2], exc.code, detail[:400])
    except Exception as exc:  # noqa: BLE001
        return None, "{}: {}".format(type(exc).__name__, str(exc)[:200])


def table_headers(token):
    return {"Authorization": "Bearer {}".format(token), "Content-Type": "application/json"}


def decode_rows(body):
    """The query endpoint returns schema and data as arrays-of-arrays."""
    columns = [f.get("name") for group in body.get("schema", []) for f in group]
    return [dict(zip(columns, [v for group in row for v in group])) for row in body.get("data", [])]


def fetch_rows(token, where, table_url=TABLE_URL, select=None):
    rows = []
    continuation_token = None

    while True:
        payload = {"where": where, "select": select or SELECT_COLUMNS, "limit": 200}
        if continuation_token:
            payload["continuation_token"] = continuation_token

        body, error = send_json(table_url, table_headers(token), payload)
        if error:
            raise ConnectionError("Workato {}".format(error))

        rows.extend(decode_rows(body))
        continuation_token = body.get("continuation_token")
        if not continuation_token:
            break

    return rows


def load_local_rows(path):
    with open(path, "r", encoding="utf-8") as handle:
        body = json.load(handle)

    rows = body.get("message", body) if isinstance(body, dict) else body
    if isinstance(rows, dict):
        rows = rows.get("data", rows.get("rows", []))
    if not isinstance(rows, list):
        raise ValueError("local_data_file must contain a list, message list, data list, or rows list")

    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({
            name: row.get(name, row.get(LOCAL_COLUMN_KEYS[name]))
            for name in SELECT_COLUMNS
        })
    return normalized


# Where a person's session list lives. `total` is the first column and, once it is full,
# the list carries on in the others, in this order (spotter.py writes it; see TOTAL_COLUMNS
# there). Anything that reads a person's sessions must join them or it sees only the first
# ~9,500 characters and under-counts. Keep this tuple identical to spotter.py's.
TOTAL_COLUMNS = ("total", "plank_photo", "current_weight", "current_fat", "current_muscle")


def session_list(row):
    """The whole comma-separated session list of an activity row."""
    return ",".join(str(row.get(c) or "") for c in TOTAL_COLUMNS if str(row.get(c) or "").strip())


def _numbers(value):
    out = []
    for part in str(value or "").split(","):
        try:
            out.append(float(part.strip()))
        except ValueError:
            pass
    return out


def _dates(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def humanize(value, config):
    unit = config["unit"]
    if not unit:
        return "{:,}".format(int(value))

    if unit == "minutes":
        hours, mins = divmod(int(value), 60)
        if hours:
            return "{}h {:02d}m".format(hours, mins) if mins else "{}h".format(hours)
        return "{}m".format(mins)

    if unit == "seconds":
        hours, rest = divmod(int(value), 3600)
        mins, secs = divmod(rest, 60)
        if hours:
            return "{}h {:02d}m".format(hours, mins) if mins else "{}h".format(hours)
        if mins:
            return "{}m {:02d}s".format(mins, secs) if secs else "{}m".format(mins)
        return "{}s".format(secs)

    return "{:,} {}".format(int(value), unit)


def run_time(entry):
    """The seconds of a game's best run, as shown on the card: 59.4s. "-" if unrecorded."""
    return "{:.1f}s".format(entry["time"]) if entry.get("time") else "-"


def trim(name, width=NAME_WIDTH):
    name = name or "?"
    return name if len(name) <= width else name[:width - 1] + "."


def build_game_board(rows, config):
    """One entry per player from a game's rows: ranked on best score, then the faster run.

    The entry reuses the activity fields so the snapshot, rank changes and trends work
    unchanged: total and best are the best score (so "added" is how much it improved),
    best_set and days are games played, and time is the seconds of the best run.
    """
    board = []
    for row in rows:
        if row.get("row_type") != config["row_type"] or truthy(row.get("leaderboard_optout")):
            continue
        score = int_input(row.get("personal_best_single_set"))
        if score <= 0:
            continue                      # played, but never got one right: nothing to rank
        games = max(1, int_input(row.get("total_planks"), 1))
        secs = max(0.0, float_input(row.get("total")))
        points = game_points(row, score) if config["points"] else score
        board.append({
            "id": row.get("id") or "",
            "name": row.get("name") or "",
            "tier": "",
            "total": points,
            "best": score,
            "best_set": games,
            "logs": games,
            "days": games,
            "last": "",
            "time": secs,
            "level": game_level(config["activity"], score),
            # Settles a tie in the ranked number: the top score, then the faster run.
            "rank_key": (score, -secs) if config["points"] else secs,
        })

    # A run with no recorded time sorts after any run with one.
    board.sort(key=lambda entry: (-entry["total"], -entry["best"] if config["points"] else 0,
                                  entry["time"] or float("inf"), entry["name"]))
    assign_ranks(board)
    return board


def challenge_counts(row):
    """(taken on, cleared) from a row's `content`, where weekly_challenge.py keeps them ("wc_counts"):
    (0, 0) for a row with none or whose content is not a json object."""
    try:
        document = json.loads(row.get("content") or "{}")
    except (TypeError, ValueError):
        return 0, 0
    counts = document.get(CHALLENGE_COUNTS_KEY) if isinstance(document, dict) else None
    if not isinstance(counts, dict):
        return 0, 0
    return max(0, int_input(counts.get("accepted"))), max(0, int_input(counts.get("cleared")))


def challenge_cleared_since(row, since):
    """How many of a row's weekly entries were cleared on or after `since` (a 'YYYY-MM-DD' day). The row
    keeps its newest few entries, so this is for a recent window, which a week is."""
    try:
        document = json.loads(row.get("content") or "{}")
    except (TypeError, ValueError):
        return 0
    entries = document.get("wc") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        return 0
    return sum(1 for entry in entries if isinstance(entry, dict) and entry.get("state") == "done"
               and str(entry.get("done") or "") >= since)


def build_challenge_board(rows, config, today=None):
    """One entry per person who has cleared a weekly challenge, ranked on challenges cleared.

    A person's counts are kept on each of their rows of an activity or a game, so they are added
    up over those rows: one line per person however many activities they cleared. Anyone who has
    opted out of the boards on any row of theirs is left out. The entry reuses the activity fields
    so the snapshot, rank changes and trends work unchanged: total and best are what was cleared,
    and best_set, logs and days are how many they have taken on. `cats` is how many each cleared in
    each category ({row type: cleared}) and `week` how many since Monday (`today`, UTC)."""
    wanted = set(config["row_types"])
    today = today or datetime.now(timezone.utc).date()
    since = (today - timedelta(days=today.weekday())).isoformat()
    people = {}
    for row in rows:
        if row.get("row_type") not in wanted or not row.get("id"):
            continue
        person = people.setdefault(row["id"], {"name": "", "taken": 0, "cleared": 0, "out": False,
                                               "cats": {}, "week": 0})
        taken, cleared = challenge_counts(row)
        person["taken"] += taken
        person["cleared"] += cleared
        if cleared:
            person["cats"][row["row_type"]] = person["cats"].get(row["row_type"], 0) + cleared
        person["week"] += challenge_cleared_since(row, since)
        person["name"] = person["name"] or row.get("name") or ""
        person["out"] = person["out"] or truthy(row.get("leaderboard_optout"))
    board = []
    for uid, person in people.items():
        if person["out"] or person["cleared"] <= 0:
            continue                      # nothing cleared yet: nothing to rank
        taken = max(person["taken"], person["cleared"])        # (cleared can never be more than taken on)
        board.append({
            "id": uid, "name": person["name"], "tier": "",
            "total": person["cleared"], "best": person["cleared"],
            "best_set": taken, "logs": taken, "days": taken, "last": "",
            "cats": person["cats"], "week": person["week"],
        })
    # Equal counts share a rank (assign_ranks); within one, whoever took on fewer to clear them, the
    # better clear rate, is listed first.
    board.sort(key=lambda entry: (-entry["total"], entry["days"], entry["name"]))
    assign_ranks(board)
    return board


def clear_rate(entry):
    """Percent of the challenges a person took on that they cleared, as text: '80%'."""
    return "{}%".format(int(round(100.0 * entry["total"] / max(1, entry["days"]))))


def category_label(row_type):
    return CHALLENGE_CATEGORIES.get(row_type, (row_type, ""))[0]


def category_icon(row_type):
    return CHALLENGE_CATEGORIES.get(row_type, ("", ""))[1]


def category_totals(board):
    """[(row type, cleared by everyone on the board, who)] biggest first: who is [(entry, cleared)],
    biggest first. Ties are listed by name, so a board reads the same each time."""
    totals = {}
    for entry in board:
        for row_type, cleared in (entry.get("cats") or {}).items():
            totals.setdefault(row_type, []).append((entry, cleared))
    out = []
    for row_type, who in totals.items():
        who.sort(key=lambda item: (-item[1], item[0]["name"]))
        out.append((row_type, sum(cleared for _, cleared in who), who))
    out.sort(key=lambda item: (-item[1], category_label(item[0])))
    return out


def most_cleared_line(board):
    """':books: Reading 6  .  :person_in_lotus_position: Yoga 5 ...': where the crew's wins are; '' if none."""
    parts = ["{} {} {}".format(category_icon(row_type), category_label(row_type), total).strip()
             for row_type, total, _ in category_totals(board)[:CHALLENGE_TOP_CATEGORIES]]
    return "Most cleared:  " + "  \u00b7  ".join(parts) if parts else ""


def first_names(entries):
    """First names for a line of text; two who share one get a last initial."""
    words = [(entry["name"] or "?").split() or ["?"] for entry in entries]
    firsts = [w[0] for w in words]
    return [("{} {}.".format(w[0], w[-1][0]) if firsts.count(w[0]) > 1 and len(w) > 1 else w[0])
            for w in words]


def build_category_thread(board, config):
    """The thread reply "Who cleared what": each category somebody cleared in, biggest first, with the
    people who cleared in it and how many each. Section blocks cut under Slack's text limit."""
    lines = []
    for row_type, total, who in category_totals(board):
        shown = who[:CHALLENGE_PEOPLE_PER_CATEGORY]
        names = ", ".join("{} {}".format(name, cleared)
                          for name, (_, cleared) in zip(first_names([e for e, _ in shown]), shown))
        if len(who) > len(shown):
            names += " +{} more".format(len(who) - len(shown))
        lines.append("{}  *{}*  \u00b7  {}  \u00b7  {}".format(category_icon(row_type), category_label(row_type),
                                                            total, names))
    if not lines:
        return []
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "{}  *Who cleared what*  -  by category, all time".format(
        config["icon"]).strip()}}]
    chunk, size = [], 0
    for line in lines:
        if chunk and size + len(line) + 1 > SLACK_SECTION_LIMIT:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(chunk)}})
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(chunk)}})
    return blocks


def build_board(rows, config):
    if config["challenge"]:
        return build_challenge_board(rows, config)
    if config["game"]:
        return build_game_board(rows, config)
    board = []
    for row in rows:
        if row.get("row_type") != config["row_type"] or truthy(row.get("leaderboard_optout")):
            continue

        sessions = _numbers(session_list(row))
        if not sessions:
            continue

        dates = _dates(row.get("heatmap_dates"))
        best_day = int(max(sessions))
        best_set = int(row.get("personal_best_single_set") or 0)
        if not 0 < best_set <= best_day:
            best_set = best_day

        tier = str(row.get("plank_tier") or "").strip()
        if tier.lower() in ("none", "not started"):
            tier = ""

        board.append({
            "id": row.get("id") or "",
            "name": row.get("name") or "",
            "tier": tier,
            "total": int(sum(sessions)),
            "best": best_day,
            "best_set": best_set,
            "logs": len(sessions),
            "days": len(set(dates)),
            "last": max(dates) if dates else "",
        })

    board.sort(key=lambda entry: (-entry["total"], entry["name"]))
    assign_ranks(board)
    return board


def assign_ranks(entries):
    """Competition ranking on a list sorted by total: 1, 2, 2, 4.

    Equal totals share a rank and are marked tied, so the table can show T2.
    """
    previous_total, rank = None, 0
    for place, entry in enumerate(entries, start=1):
        # Game entries also carry a time, which settles a tie in score; activity
        # entries have none, so for them this is the total alone.
        mark = (entry["total"], entry.get("rank_key", entry.get("time")))
        if mark != previous_total:
            rank, previous_total = place, mark
        entry["rank"] = rank
    shared = {}
    for entry in entries:
        shared[entry["rank"]] = shared.get(entry["rank"], 0) + 1
    for entry in entries:
        entry["tied"] = shared[entry["rank"]] > 1


def rank_text(entry):
    return "{}{}".format("T" if entry.get("tied") else "", entry["rank"])


def qualify(board, config):
    """Everyone with enough logged days, ranked. Opted-out people never get here."""
    qualified = [entry for entry in board if entry["days"] >= config["min_days"]]
    assign_ranks(qualified)
    return qualified


def filter_board(qualified, config):
    """The public board: qualified people, trimmed by the optional total filters.

    Both filters cut from the bottom, so ranks stay the same as in the full list.
    """
    if not qualified:
        return []

    eligible = list(qualified)
    leader_total = eligible[0]["total"]
    min_total_percent = config["min_total_percent"]
    max_total_gap = config["max_total_gap"]

    if min_total_percent:
        minimum_total = leader_total * min_total_percent / 100.0
        eligible = [entry for entry in eligible if entry["total"] >= minimum_total]

    if max_total_gap:
        eligible = [entry for entry in eligible if leader_total - entry["total"] <= max_total_gap]

    return eligible


def getting_started(full_board, qualified):
    """People logging but not yet ranked, closest to qualifying first."""
    ranked = {person_key(entry) for entry in qualified}
    return sorted(
        (entry for entry in full_board if person_key(entry) not in ranked),
        key=lambda entry: (-entry["days"], -entry["total"], entry["name"]),
    )


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "{}{}".format(n, suffix)


def distance(steps, config):
    return steps * config["stride_m"] / 1000.0


def flourish(total, config, record_pool=None):
    """record_pool is every participant, so the best effort can credit someone
    who is not on the visible board."""
    activity = config["activity"]
    if config["challenge"]:
        pool = record_pool or []
        taken = sum(entry["days"] for entry in pool)
        line = "*{:,}* {} between us".format(int(total), "challenge cleared" if total == 1 else "challenges cleared")
        if taken:
            line += ", out of *{:,}* taken on".format(taken)
        return line + "."
    if config["points"]:
        pool = record_pool or []
        if not pool:
            return ""
        top = max(pool, key=lambda entry: (entry["best"], -(entry.get("time") or float("inf"))))
        return "*{:,}* points between us over *{:,}* games. Top score: *{}* by *{}*{}{}.".format(
            int(total), sum(entry["days"] for entry in pool), humanize(top["best"], config),
            top["name"], " (level {})".format(top["level"]) if top.get("level") else "",
            " in {}".format(run_time(top)) if top.get("time") else "")
    if config["game"]:
        # Best scores are not additive, so no "between us" total. Nor a count of games
        # played: effort without a result ("40 games, best 7") discourages the people
        # who plateau and makes newcomers feel behind, so a game board shows scores only.
        pool = record_pool or []
        if not pool:
            return ""
        top = pool[0]
        return "Top score: *{}* by *{}*{}{}.".format(
            humanize(top["total"], config), top["name"],
            " (level {})".format(top["level"]) if top.get("level") else "",
            " in {}".format(run_time(top)) if top.get("time") else "")
    if activity == "step":
        km = distance(total, config)
        line = "*{:,}* steps between us - that's *{:,.0f} km*".format(int(total), km)
        if km >= MARATHON_KM:
            line += ", about *{:.1f} marathons*".format(km / MARATHON_KM)
        line += "."
        if record_pool and config["best_phrase"]:
            biggest = max(record_pool, key=lambda entry: entry["best"])
            line += " {}: *{}* by *{}*.".format(
                config["best_phrase"], humanize(biggest["best"], config), biggest["name"]
            )
        return line

    joiner = "of " if config["unit"] in ("seconds", "minutes") else ""
    line = "*{}* {}{} between us.".format(humanize(total, config), joiner, config["noun"])
    if record_pool and config["best_phrase"]:
        key = "best_set" if config["set_based"] else "best"
        biggest = max(record_pool, key=lambda entry: entry[key])
        line += " {}: *{}* by *{}*.".format(
            config["best_phrase"], humanize(biggest[key], config), biggest["name"]
        )
    return line


def person_key(entry):
    return entry["id"] or entry["name"]


def pack_snapshot(runs):
    """The stored form, version 4:

        {"v": 4, "at": [run times],
         "n": {person: name},
         "p": {person: {"r": [rank per run], "t": [total per run], "b": [...], "s": [...], "d": [...]}}}

    Each person appears once with one list per fact, null where they were not
    on that run, so the size grows with runs x people and a new fact is just a
    new list. Only people in the latest run are kept.
    """
    def fact(run, key, index):
        values = run["p"].get(key) or ()
        return values[index] if len(values) > index else None

    latest = runs[-1]
    people = {
        key: {name: [fact(run, key, index) for run in runs] for name, index in SERIES}
        for key in latest["p"]
    }
    return {
        "v": SNAPSHOT_VERSION,
        "at": [run["at"] for run in runs],
        "n": latest.get("n", {}),
        "p": people,
    }


def build_snapshot(qualified, starters, history, keep, now=None, budget=SNAPSHOT_ROOM):
    """The snapshot to save: this run added to `history`, at most `keep` runs.

    Starters are stored unranked (rank 0) so their trend starts from their first
    logs and they show as new on the run they join the board. If the result is
    over `budget` characters the oldest runs are dropped until it fits.
    """
    now = now or datetime.now(timezone.utc)
    ranked_keys = {person_key(entry) for entry in qualified}
    everyone = list(qualified) + list(starters)
    this_run = {
        "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n": {person_key(entry): entry["name"] for entry in everyone},
        "p": {
            person_key(entry): [
                entry["rank"] if person_key(entry) in ranked_keys else 0,
                entry["total"], entry["best"], entry["best_set"], entry["days"],
            ]
            for entry in everyone
        },
    }
    runs = (list(history) + [this_run])[-keep:]
    while True:
        snapshot = pack_snapshot(runs)
        if len(runs) == 1 or len(snapshot_text(snapshot)) <= budget:
            return snapshot
        runs = runs[1:]


def parse_snapshot(text):
    """{"people": {key: {"r", "t", ...}}, "history": [{"at", "p": {key: [rank, total, best, set, days]}}]}, or None.

    Reads the current layout and the earlier ones: version 3 (rank then one
    total per run), version 2 (people plus [rank, total] history) and version 1
    (people only, counted as one earlier run). Facts an old version never saved
    come back as None.
    """
    try:
        data = json.loads(text) if text else None
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    packed, stamps = data.get("p"), data.get("at")
    if isinstance(packed, dict) and isinstance(stamps, list):
        width = len(stamps)
        series_by_person = {}
        for key, value in packed.items():
            if isinstance(value, dict):                       # version 4
                series = {name: value.get(name) for name, _ in SERIES}
                if series["t"] is None or any(
                        isinstance(series[name], list) and len(series[name]) != width for name in series):
                    continue
                series_by_person[key] = {
                    name: (series[name] if isinstance(series[name], list) else [None] * width)
                    for name, _ in SERIES
                }
            elif isinstance(value, list) and len(value) == width + 1:   # version 3
                series_by_person[key] = {
                    "r": [None] * (width - 1) + [value[0]], "t": value[1:],
                    "b": [None] * width, "s": [None] * width, "d": [None] * width,
                }
        names = data.get("n") if isinstance(data.get("n"), dict) else {}
        people, history = {}, []
        for key, series in series_by_person.items():
            if series["t"][-1] is not None:
                people[key] = {"n": names.get(key, ""), **{name: series[name][-1] for name, _ in SERIES}}
        for index, stamp in enumerate(stamps):
            run = {}
            for key, series in series_by_person.items():
                if series["t"][index] is not None:
                    run[key] = [series[name][index] for name, _ in SERIES]
            history.append({"at": stamp, "p": run})
        return {"people": people, "history": history} if people else None

    people = data.get("people")
    if not isinstance(people, dict) or not people:
        return None
    history = data.get("history")
    if not isinstance(history, list):
        history = [{
            "at": data.get("at") or "",
            "p": {key: [info.get("r", 0), info.get("t", 0)] for key, info in people.items()},
        }]
    return {"people": people, "history": [run for run in history if isinstance(run, dict)]}


def compute_changes(entries, previous):
    """Per person: places moved (+ is up) and amount added since the last post.

    None when there is no earlier snapshot, so the first post carries no
    change columns instead of a column of "new".
    """
    if not previous:
        return None
    changes = {}
    for entry in entries:
        before = previous.get(person_key(entry))
        if not before:
            changes[person_key(entry)] = {"new": True, "move": 0, "gain": None}
            continue
        was_ranked = int(before.get("r") or 0) > 0
        changes[person_key(entry)] = {
            "new": not was_ranked,
            "move": int(before.get("r") or 0) - entry["rank"] if was_ranked else 0,
            "gain": entry["total"] - int(before.get("t") or 0),
        }
    return changes


def run_gains(totals):
    """What was added between consecutive runs; None marks a run they were not in."""
    return [
        None if before is None or after is None else max(0, after - before)
        for before, after in zip(totals, totals[1:])
    ]


def trend_scale(all_gains):
    """One yardstick for the whole board: the 90th percentile of non-zero gains.

    Bars are comparable across rows. The cap keeps a single huge week from
    flattening everyone else; with few data points it is simply the biggest gain.
    """
    positive = sorted(gain for gain in all_gains if gain)
    if not positive:
        return 0
    return positive[max(0, -(-len(positive) * 9 // 10) - 1)]


def sparkline(gains, scale):
    out = []
    for gain in gains:
        if gain is None:
            out.append(" ")
        elif gain == 0 or scale == 0:
            out.append(TREND_IDLE)
        else:
            level = int(min(gain, scale) * len(TREND_BARS) / scale - 1e-9)
            out.append(TREND_BARS[max(0, min(len(TREND_BARS) - 1, level))])
    return "".join(out).rjust(TREND_WIDTH)


def compute_trends(entries, history):
    """Per person sparkline over the last TREND_WIDTH run gaps, current run included.

    Every row shares one scale, so a tall bar means a big week for the channel,
    not just for that person. None until there are two earlier runs, since one
    bar says nothing.
    """
    if len(history) < 2:
        return None
    recent = history[-TREND_WIDTH:]
    gains = {}
    for entry in entries:
        key = person_key(entry)
        totals = [(run.get("p") or {}).get(key, [None, None])[1] for run in recent]
        gains[key] = run_gains(totals + [entry["total"]])
    scale = trend_scale([gain for series in gains.values() for gain in series if gain is not None])
    return {key: sparkline(series, scale) for key, series in gains.items()}


def move_text(change, config):
    if change["new"]:
        return "new"
    if change["move"] > 0:
        return "{}{}".format(config["up_marker"], change["move"])
    if change["move"] < 0:
        return "{}{}".format(config["down_marker"], -change["move"])
    return FLAT


def gain_text(change, config):
    if change["gain"] is None or change["gain"] == 0:
        return FLAT
    sign = "+" if change["gain"] > 0 else "-"
    return sign + humanize(abs(change["gain"]), config)


def table_lines(board, config, changes=None, trends=None):
    rank_width = max([2] + [len(rank_text(entry)) for entry in board])
    cols = [("#", rank_width, ">", rank_text)]
    if changes is not None:
        move_head = config["down_marker"] + config["up_marker"]
        cols.append((move_head, 4, "<", lambda entry: move_text(changes[person_key(entry)], config)))
    game = config["game"]
    cols.extend([
        ("name", NAME_WIDTH, "<", lambda entry: trim(entry["name"])),
        ("cleared" if config["challenge"] else "points" if config["points"] else "best" if game else "total",
         9, ">", lambda entry: humanize(entry["total"], config)),
    ])
    if changes is not None:
        cols.append(("gain" if game else "added", 8, ">",
                     lambda entry: gain_text(changes[person_key(entry)], config)))

    if config["challenge"]:
        cols.append(("taken", 6, ">", lambda entry: "{:,}".format(entry["days"])))
        if config.get("show_categories"):
            # How many different categories they have cleared one in: variety, not only volume.
            cols.append(("cats", 5, ">", lambda entry: str(len(entry.get("cats") or {}))))
        if config.get("show_week"):
            cols.append(("week", 5, ">", lambda entry: str(entry["week"]) if entry.get("week") else FLAT))
        if config.get("show_average"):
            # Cleared out of taken on: how often a challenge they take on gets done, which the
            # count (it favours whoever has taken on the most) cannot say.
            cols.append(("rate", 6, ">", clear_rate))
    elif game:
        if config["activity"] in GAME_LEVELS:
            cols.append(("level", 5, ">", lambda entry: str(entry["level"])))
        if config["points"]:
            cols.append(("top", 5, ">", lambda entry: humanize(entry["best"], config)))
            cols.append(("games", 6, ">", lambda entry: "{:,}".format(entry["days"])))
        else:
            cols.append(("time", 8, ">", run_time))
    elif config["activity"] == "step":
        cols.append(("distance", 9, ">", lambda entry: "{:,.1f} km".format(distance(entry["total"], config))))
    elif config["set_based"]:
        cols.append(("day", 8, ">", lambda entry: humanize(entry["best"], config)))
        cols.append(("set", 8, ">", lambda entry: humanize(entry["best_set"], config)))
    else:
        cols.append(("best", 8, ">", lambda entry: humanize(entry["best"], config)))
    if not game and not config["challenge"]:
        cols.append(("days", 5, ">", lambda entry: str(entry["days"])))
    if not game and not config["challenge"] and config.get("show_average", True):
        # Per day logged, not per calendar day: how big a typical day is when they show up,
        # which the all-time total (it favours whoever joined first) cannot say.
        # Under average_min_days it is a dash: a handful of days says more about luck than pace.
        cols.append(("avg/day", 8, ">", lambda entry: humanize(entry["total"] / max(1, entry["days"]), config)
                     if entry["days"] >= config.get("average_min_days", AVERAGE_MIN_DAYS) else FLAT))
    if trends is not None:
        cols.append(("trend", TREND_WIDTH, ">", lambda entry: trends[person_key(entry)]))

    header = format_row([(head, width, align) for head, width, align, _ in cols])
    body = [format_row([(get(entry), width, align) for _, width, align, get in cols]) for entry in board]
    return header, body


def cell_width(text):
    """Monospace cells: emoji take two, their variation selectors none."""
    cells = 0
    for char in text:
        if char in "\ufe0f\u200d":
            continue
        cells += 2 if ord(char) >= 0x1F000 else 1
    return cells


def pad(value, width, align):
    gap = " " * max(0, width - cell_width(value))
    return gap + value if align == ">" else value + gap


def format_row(values):
    return "  ".join(pad(value, width, align) for value, width, align in values).rstrip()


def code_blocks(header, body):
    """Lines as Slack section blocks, split so none passes the 3000 char limit."""
    chunks, current = [], []
    size = len(header)
    for line in body:
        if current and size + len(line) + 1 > SLACK_SECTION_LIMIT:
            chunks.append(current)
            current, size = [], len(header)
        current.append(line)
        size += len(line) + 1
    chunks.append(current)

    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "```\n" + "\n".join([header] + chunk) + "\n```"}}
        for chunk in chunks
    ]


def table_blocks(board, config, changes=None, trends=None):
    header, body = table_lines(board, config, changes, trends)
    return code_blocks(header, body)


def starter_blocks(starters, config):
    cols = [
        ("name", NAME_WIDTH, "<", lambda entry: trim(entry["name"])),
        ("cleared" if config["challenge"] else "points" if config["points"] else "best" if config["game"] else "total",
         9, ">", lambda entry: humanize(entry["total"], config)),
        ("taken" if config["challenge"] else config["day_noun"][1], 5, ">", lambda entry: str(entry["days"])),
        ("to rank", 9, ">", lambda entry: "{} more".format(config["min_days"] - entry["days"])),
    ]
    header = format_row([(head, width, align) for head, width, align, _ in cols])
    body = [format_row([(get(entry), width, align) for _, width, align, get in cols]) for entry in starters]
    return code_blocks(header, body)


def movers_line(entries, changes, config):
    """One line on what moved since the last board; empty when nothing did."""
    if changes is None:
        return ""
    rows = [(entry, changes[person_key(entry)]) for entry in entries]
    parts = []

    climbs = [(entry, change) for entry, change in rows if not change["new"] and change["move"] > 0]
    adds = [(entry, change) for entry, change in rows if change["gain"] and change["gain"] > 0]
    climber = max(climbs, key=lambda item: (item[1]["move"], item[1]["gain"] or 0)) if climbs else None
    adder = max(adds, key=lambda item: item[1]["gain"]) if adds else None

    if climber and adder and climber[0] is adder[0]:
        parts.append("biggest climb and {} *{}* {}{}, +{}".format(
            config["gain_label"], climber[0]["name"], config["up_marker"], climber[1]["move"],
            humanize(adder[1]["gain"], config)
        ))
    else:
        if climber:
            parts.append("biggest climb *{}* {}{}".format(climber[0]["name"], config["up_marker"], climber[1]["move"]))
        if adder:
            parts.append("{} *{}* +{}".format(config["gain_label"], adder[0]["name"], humanize(adder[1]["gain"], config)))

    newcomers = [entry["name"] for entry, change in rows if change["new"]]
    if newcomers:
        names = ", ".join("*{}*".format(name) for name in newcomers[:3])
        if len(newcomers) > 3:
            names += " +{} more".format(len(newcomers) - 3)
        parts.append("new on the board " + names)

    return "Since the last board: " + "  -  ".join(parts) if parts else ""


def extras_line(entries, changes, history, config):
    """A second "since the last board" line, from the richer history:
    what the crew added, new personal bests, and who is on a run of boards in a row."""
    if changes is None or not history:
        return ""
    parts = []

    added = sum(change["gain"] for change in changes.values() if change["gain"] and change["gain"] > 0)
    # Improvements to a best score do not add up to anything meaningful.
    if added > 0 and config["challenge"]:
        parts.append("Crew cleared {} more {}".format(added, "challenge" if added == 1 else "challenges"))
    elif added > 0 and (config["points"] or not config["game"]):
        joiner = "of " if config["unit"] in ("seconds", "minutes") else ""
        parts.append("Crew added {} {}{}".format(humanize(added, config), joiner, config["noun"]))

    last_run = history[-1]["p"]
    bests = []
    for entry in ([] if config["challenge"] else entries):     # (on the challenge board best IS the total)
        before = last_run.get(person_key(entry))
        if before and len(before) > BEST and before[BEST] is not None and entry["best"] > before[BEST]:
            bests.append(entry)
    if bests:
        bests.sort(key=lambda entry: -entry["best"])
        names = ", ".join("*{}* {}".format(entry["name"], humanize(entry["best"], config)) for entry in bests[:2])
        if len(bests) > 2:
            names += " +{} more".format(len(bests) - 2)
        parts.append("new personal best " + names)

    rolls = []
    for entry in entries:
        key = person_key(entry)
        totals = [(run["p"].get(key) or [None, None])[TOTAL] for run in history] + [entry["total"]]
        streak = 0
        for gain in reversed(run_gains(totals)):
            if gain and gain > 0:
                streak += 1
            else:
                break
        if streak >= 3:
            rolls.append((streak, entry["total"], entry["name"]))
    if rolls:
        streak, _, name = max(rolls)
        parts.append("on a roll *{}*, {} on {} boards in a row".format(name, config["roll_verb"], streak))

    return "  -  ".join(parts)


def build_message(board, config, top_n, full_board=None, changes=None, has_thread=False, trends=None, movers=""):
    shown = board[:top_n]
    total = sum(entry["total"] for entry in board)
    record_pool = full_board or board

    if config["image_url"]:
        blocks = [{
            "type": "image",
            "image_url": config["image_url"],
            "alt_text": "{} activity leaderboard".format(config["title"]),
        }]
    else:
        heading = "{}  *{} leaderboard*  -  {}".format(
            config["icon"], config["title"],
            "weekly challenges cleared" if config["challenge"] else "total points" if config["points"]
            else "best scores" if config["game"] else "all time").strip()
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": heading}}]

    blocks.extend(table_blocks(shown, config, changes, trends))

    podium = "  ".join(
        "{} *{}*".format(MEDALS[entry["rank"]], entry["name"])
        for entry in shown
        if entry["rank"] in MEDALS
    )
    if podium:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": podium}})
    if movers:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "\n".join(
            "_{}_".format(line) for line in movers.splitlines())}]})

    # When nobody is held back by the closest-to-the-board line, the thread pointer shares
    # the headcount line instead of taking a line of its own.
    thread_pointer = has_thread and len(board) <= len(shown)
    footer = [
        flourish(total, config, record_pool),
        "{} {} on the board{}".format(
            len(board), "person" if len(board) == 1 else "people",
            " - everyone else is in the thread." if thread_pointer else "."),
    ]

    # "Most consistent" is about days active, which suits an activity; a game board has no
    # equivalent that is not just a games count, so it gets no line.
    if not config["game"] and not config["challenge"]:
        steady = max(board, key=lambda entry: (entry["days"], entry["total"]))
        if steady["rank"] != 1:
            footer.append("Most consistent: *{}*, active on {} days.".format(steady["name"], steady["days"]))

    if config["challenge"] and config["show_categories"]:
        line = most_cleared_line(board)
        if line:
            footer.append(line)
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "\n".join(footer)}]})

    if config["challenge"]:
        not_listed = "Not listed? Clear a weekly challenge to get on the board."
    elif config["game"]:
        not_listed = "Not listed? Type `{}` to get on the board.".format(config["activity"])
    else:
        not_listed = "Not listed? `/iprofile` shows where you sit."
    pointer = "Everyone else is in the thread." if has_thread else not_listed
    if len(board) > len(shown):
        nearly = board[len(shown)]
        need = shown[-1]["total"] - nearly["total"] + 1
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": "_Closest to the board: *{}*, {} off {}. {}_".format(
                    nearly["name"], humanize(need, config), ordinal(len(shown)), pointer
                ),
            }],
        })

    return blocks


def build_thread(rest, starters, config, changes=None, trends=None):
    """What the channel message does not show: the remaining ranked people, then starters."""
    blocks = []
    if rest:
        heading = "{}  *{} leaderboard, the rest*  -  ranks {} to {}".format(
            config["icon"], config["title"], rest[0]["rank"], rest[-1]["rank"]
        ).strip()
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": heading}})
        blocks.extend(table_blocks(rest, config, changes, trends))

    if starters:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Getting started*  -  {} {}, ranked once they have {} {} {}".format(
                    len(starters), "person" if len(starters) == 1 else "people",
                    config["verb"], config["min_days"], config["day_noun"][1]
                ),
            },
        })
        blocks.extend(starter_blocks(starters, config))
    return blocks


# ---------------------------------------------------------------------------- journey
#
# The channel's steps, added together, walk a route around the world. COPIED from
# channel_summary/channel_summary.py (which spotter.py copies too); the route and the
# functions below are the same, and test_leaderboard_greatwalk.py fails if they drift.
# To change the route, change it there and copy it here.
JOURNEY_NAME = "The Great Walk"
JOURNEY_STRIDE_M = 0.715        # metres per step -- the figure channel_summary already uses
# (name, flag, latitude, longitude, a few words about it)
ROUTE = (
    ("Mountain View", ":flag-us:", 37.3861, -122.0839, "where we set off"),
    ("Las Vegas", ":flag-us:", 36.1699, -115.1398, "bright lights, long road"),
    ("the Grand Canyon", ":flag-us:", 36.1069, -112.1129, "nearly 450 km of canyon"),
    ("Denver", ":flag-us:", 39.7392, -104.9903, "the Mile High City"),
    ("Chicago", ":flag-us:", 41.8781, -87.6298, "on the shore of Lake Michigan"),
    ("New York", ":flag-us:", 40.7128, -74.0060, "the city that never sleeps"),
    ("Reykjavik", ":flag-is:", 64.1466, -21.9426, "the world's northernmost capital"),
    ("London", ":flag-gb:", 51.5074, -0.1278, "mind the gap"),
    ("Paris", ":flag-fr:", 48.8566, 2.3522, "under the Eiffel Tower"),
    ("Rome", ":flag-it:", 41.9028, 12.4964, "where every road leads"),
    ("Cairo", ":flag-eg:", 30.0444, 31.2357, "the pyramids of Giza next door"),
    ("Dubai", ":flag-ae:", 25.2048, 55.2708, "home of the world's tallest building"),
    ("Mumbai", ":flag-in:", 19.0760, 72.8777, "by the Gateway of India"),
    ("Delhi", ":flag-in:", 28.6139, 77.2090, "at India Gate"),
    ("Bengaluru", ":flag-in:", 12.9716, 77.5946, "India's Silicon Valley"),
    ("Bangkok", ":flag-th:", 13.7563, 100.5018, "temples and street food"),
    ("Singapore", ":flag-sg:", 1.3521, 103.8198, "the garden city"),
    ("Hong Kong", ":flag-hk:", 22.3193, 114.1694, "below Victoria Peak"),
    ("Tokyo", ":flag-jp:", 35.6762, 139.6503, "at Shibuya Crossing"),
    ("Honolulu", ":flag-us:", 21.3069, -157.8583, "aloha"),
    ("Mountain View", ":flag-us:", 37.3861, -122.0839, "full circle"),
)


def _great_circle_km(a, b):
    """Haversine distance between two ROUTE entries, in km (Earth radius 6,371 km)."""
    lat1, lon1, lat2, lon2 = [math.radians(v) for v in (a[2], a[3], b[2], b[3])]
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


LEG_KM = [_great_circle_km(ROUTE[i], ROUTE[i + 1]) for i in range(len(ROUTE) - 1)]
STOP_KM = [sum(LEG_KM[:i]) for i in range(len(ROUTE))]      # km from the start to each stop
LAP_KM = STOP_KM[-1]


def steps_to_km(steps):
    return int(steps or 0) * JOURNEY_STRIDE_M / 1000.0


def km_to_steps(km):
    return int(round(km * 1000.0 / JOURNEY_STRIDE_M))


def journey_position(steps):
    """Where the channel is on the route.

    {"km": all-time km, "lap": 1-based, "within": km into this lap, "leg": 1-based,
     "legs": how many legs, "behind": the stop just passed, "ahead": the next stop,
     "leg_km": that leg's length, "leg_done": km walked along it, "to_go": km to the next
     stop, "share": 0-1 along the leg, "around": 0-1 along the lap}
    """
    km = steps_to_km(steps)
    lap, within = divmod(km, LAP_KM)
    index = max(i for i in range(len(LEG_KM)) if STOP_KM[i] <= within)
    done = within - STOP_KM[index]
    return {"km": km, "lap": int(lap) + 1, "within": within, "leg": index + 1,
            "legs": len(LEG_KM), "behind": ROUTE[index], "ahead": ROUTE[index + 1],
            "leg_km": LEG_KM[index], "leg_done": done,
            "to_go": LEG_KM[index] - done, "share": done / LEG_KM[index],
            "around": within / LAP_KM}


def journey_arrivals(steps_before, steps_after):
    """The stops reached between two step totals, in order: [(lap, stop index, stop)].
    The last stop of a lap is the one that closes the loop."""
    before, after = steps_to_km(steps_before), steps_to_km(steps_after)
    found = []
    if after <= before:
        return found
    lap = int(before // LAP_KM)
    while lap * LAP_KM <= after:
        for index in range(1, len(ROUTE)):
            at = lap * LAP_KM + STOP_KM[index]
            if before < at <= after:
                found.append((lap + 1, index, ROUTE[index]))
        lap += 1
    return found


def journey_days_to_go(position, steps_per_day):
    """When the next stop lands at the current pace, as a number of days or None."""
    if not steps_per_day or steps_per_day <= 0:
        return None
    return max(1, int(-(-km_to_steps(position["to_go"]) // steps_per_day)))


def stop_name(stop):
    """A route stop as it starts a sentence: "the Grand Canyon" -> "The Grand Canyon"."""
    name = stop[0]
    return name[:1].upper() + name[1:]


def walk_road(share, tile, marker, cells=WALK_BAR_CELLS, since=None, recent=WALK_RECENT_TILE):
    """A line of emoji for a share from 0 to 1: `tile` for the way walked, `marker` in the
    square the walkers are in, empty squares for the road ahead. Always `cells` wide. With
    `since` (the share at the last board), the squares walked after it are `recent`."""
    here = min(cells - 1, int(max(0.0, share) * cells))
    start = here if since is None else min(here, int(max(0.0, since) * cells))
    return tile * start + recent * (here - start) + marker + WALK_EMPTY * (cells - 1 - here)


def leg_share_before(pos, added):
    """How far along this leg the walkers were at the last board, 0 to 1: 0 when they were
    still on an earlier leg (or lap) then."""
    before = pos["within"] - steps_to_km(added)
    return max(0.0, (before - STOP_KM[pos["leg"] - 1]) / pos["leg_km"])


def short_date(day):
    return "{} {}".format(day.day, day.strftime("%b"))


def walk_pace(added, history, now):
    """Steps a day the channel has walked since the last board, or None: nothing added,
    no earlier run, or less than a day between them (an hour's pace says nothing)."""
    if added <= 0 or not history:
        return None
    try:
        since = datetime.strptime(history[-1]["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None
    days = (now - since).total_seconds() / 86400.0
    return added / days if days >= 1 else None


def walk_eta(km, pace, now):
    """The date `km` more would land at `pace`, as '3 Nov'; '' when it is too far off."""
    days = journey_days_to_go({"to_go": km}, pace)
    if days is None or days > WALK_ETA_MAX_DAYS:
        return ""
    return short_date(now + timedelta(days=days))


def walk_status(full_board, qualified, previous, history, now):
    """Where the channel is on the route. Everyone's steps count, ranked or not.

    {"steps", "pos", "added" (steps since the last board, None on the first), "active"
     (how many people added some), "arrivals" (the stops reached since), "pace"}
    Nobody is named or ordered: the walk is one shared total.
    """
    steps = sum(entry["total"] for entry in full_board)
    added, active, arrivals = None, 0, []
    if previous:
        added = max(0, sum(entry["total"] for entry in qualified)
                    - sum(int(info.get("t") or 0) for info in previous.values()))
        active = sum(1 for entry in qualified
                     if entry["total"] > int((previous.get(person_key(entry)) or {}).get("t") or 0))
        arrivals = journey_arrivals(max(0, steps - added), steps)
    return {"steps": steps, "pos": journey_position(steps), "added": added, "active": active,
            "walkers": len(full_board), "arrivals": arrivals, "pace": walk_pace(added or 0, history, now),
            "boards": board_totals(history, sum(entry["total"] for entry in qualified), now)}


def board_totals(history, steps_now, now):
    """[(day, the channel's steps)] at each saved board, oldest first, and now."""
    totals = []
    for run in history:
        try:
            day = datetime.strptime(str(run.get("at") or "")[:10], "%Y-%m-%d")
        except ValueError:
            continue
        totals.append((day, sum(int(values[TOTAL] or 0) for values in (run.get("p") or {}).values()
                                if len(values) > TOTAL)))
    return totals + [(now, steps_now)]


def reached_on(km, boards):
    """The board on which the walk first passed `km` (from the start, all laps counted), as
    '15 Oct'; '' when it was passed before the first board saved, or not yet."""
    for (_, before), (day, after) in zip(boards, boards[1:]):
        if steps_to_km(before) < km <= steps_to_km(after):
            return short_date(day)
    return ""


def walk_arrival_text(arrivals):
    """One line for the stops reached since the last board; the finish of a lap says so."""
    lap, index, stop = arrivals[-1]
    if index == len(ROUTE) - 1:
        return (":tada:  We've walked all the way round the world: *{:,.0f} km*, together. "
                "Lap {} starts now.".format(LAP_KM, lap + 1))
    if len(arrivals) == 1:
        return ":round_pushpin:  We reached {} *{}* since the last board: {}.".format(
            stop[1], stop_name(stop), stop[4])
    return ":round_pushpin:  We passed *{}* stops since the last board, the latest {} *{}*.".format(
        len(arrivals), stop[1], stop_name(stop))


def walk_fallback_text(status):
    pos = status["pos"]
    return "{} - {:,.0f} km walked together, next stop {}".format(
        JOURNEY_NAME, pos["km"], pos["ahead"][0])


def walk_status_blocks(status, config, now):
    """The post, in three parts:

        the headline   the one-line summary, and the figures under it, small and grey
        ----------     a divider
        this leg       the road (a walker on it between its two flags, the way walked since
                       the last board in its own colour) and what that was; any stop reached
        the route      the route strip (or, in the carousel layout, the km to the next stop)
    """
    pos, steps = status["pos"], status["steps"]
    if config["image_url"]:
        blocks = [{"type": "image", "image_url": config["image_url"],
                   "alt_text": "{} dashboard".format(JOURNEY_NAME)}]
    else:
        blocks = [{"type": "header", "text": {
            "type": "plain_text", "text": "{} {}".format(config["icon"], JOURNEY_NAME), "emoji": True}}]

    behind, ahead = pos["behind"], pos["ahead"]
    km = pos["km"]
    where = ("on the way to {} *{}*".format(ahead[1], stop_name(ahead)) if pos["leg"] == 1 else
             "now between {} *{}* and {} *{}*".format(behind[1], stop_name(behind),
                                                      ahead[1], stop_name(ahead)))
    done = ""
    if pos["lap"] > 1:
        done = " ({} lap{} round the world)".format(pos["lap"] - 1, "" if pos["lap"] == 2 else "s")
    summary = "Together we set off from {} and have walked *{:,.0f} km*{} so far, {}.".format(
        WALK_START_BOLD, km, done, where)
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary}})

    walkers = "{:,}".format(config["walkers"])
    walkers_noun = "walker" if config["walkers"] == 1 else "walkers"
    figures = "\U0001F45F *{:,}* steps  \u00b7  {} *{}* {}".format(
        steps, WALK_FIGURE_WALKING, walkers, walkers_noun)
    if km >= MARATHON_KM:
        # "about", not "~": Slack will not bold a number that follows a tilde.
        marathons = int(round(km / MARATHON_KM))
        figures += "  \u00b7  {} about *{:,}* marathon{}".format(
            WALK_FIGURE_RUNNING, marathons, "" if marathons == 1 else "s")
    around = pos["around"] * 100
    figures += "  \u00b7  {} *{}%* round the world{}".format(
        WALK_GLOBE, "{:.1f}".format(around) if around < 10 else "{:.0f}".format(around),
        ", lap {}".format(pos["lap"]) if pos["lap"] > 1 else "")
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": figures}]})
    blocks.append({"type": "divider"})

    since = leg_share_before(pos, status["added"]) if status["added"] else None
    lines = ["{} {} {}  *{}%* of the way to *{}*".format(
        behind[1], walk_road(pos["share"], WALK_LEG_TILE, WALK_WALKER, since=since),
        ahead[1], int(pos["share"] * 100), stop_name(ahead))]
    if status["added"]:
        lines.append("{} *+{:,.0f} km* since the last board  \u00b7  *{:,} of {:,}* {} added steps".format(
            WALK_RECENT_TILE, steps_to_km(status["added"]), status["active"], config["walkers"],
            walkers_noun))
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})

    if status["arrivals"]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": walk_arrival_text(status["arrivals"])}})

    if config["walk_layout"] == "carousel":
        eta = walk_eta(pos["to_go"], status["pace"], now)
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "*{:,.0f} km* to *{}*  \u00b7  {}".format(
            pos["to_go"], stop_name(ahead), "at this pace around *{}*".format(eta) if eta else "_{}_".format(ahead[4]))}]})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": walk_strip(status, now)}})
    return blocks


def walk_card(title, subtitle, body, button=None, action=""):
    """One card of the carousel. `button` is (label, style): a button is the only part of a
    card Slack lets us colour, so "Reached" is a green one."""
    card = {"type": "card",
            "title": {"type": "mrkdwn", "text": title},
            "subtitle": {"type": "mrkdwn", "text": subtitle},
            "body": {"type": "mrkdwn", "text": body}}
    if button:
        label, style = button
        element = {"type": "button", "text": {"type": "plain_text", "text": label, "emoji": True},
                   "action_id": "greatwalk_" + action, "value": action}
        if style:
            element["style"] = style
        card["actions"] = [element]
    return card


def stop_label(stop):
    return "{} {}".format(stop[1], stop_name(stop))


def fit_list(labels, joiner, keep_last, limit=CARD_BODY_LIMIT):
    """Labels joined into at most `limit` characters. Those that do not fit are dropped from
    the front ("+3 earlier") when `keep_last`, else from the back (an ellipsis)."""
    labels = list(labels)
    for shown in range(len(labels), 0, -1):
        if keep_last:
            dropped = len(labels) - shown
            text = (("+{} earlier".format(dropped) + joiner) if dropped else "") + joiner.join(labels[-shown:])
        else:
            text = joiner.join(labels[:shown]) + (joiner + "\u2026" if shown < len(labels) else "")
        if len(text) <= limit:
            return text
    return "\u2026"


def sentence(text):
    return text[:1].upper() + text[1:] + ("" if text.endswith(".") else ".")


def walk_crowd(status, gap="  "):
    """The walkers on the road: one for each person who added steps since the last board
    (everyone, on the first), up to WALK_CROWD_MAX."""
    crowd = status["active"] if status["added"] else status.get("walkers", 1)
    return gap.join([WALK_WALKER] * max(1, min(WALK_CROWD_MAX, crowd)))


def walk_strip(status, now):
    """The carousel's story on one line, for the post itself, each step labelled so that it
    reads to someone who has never seen the walk before:

        stops reached > the walkers > the next stop (km, and when at this pace) > more > finish
    """
    pos = status["pos"]
    nxt, last = pos["leg"], len(ROUTE) - 1
    reached = nxt - 1                        # stops passed on this lap; the start is not one
    stops = len(ROUTE) - 2
    parts = ["\u2705 *{} of {} stops reached*".format(reached, stops) if reached else
             "\u2705 *Set off* from {}".format(stop_name(ROUTE[0]))]
    parts.append(walk_crowd(status, gap=""))
    eta = walk_eta(pos["to_go"], status["pace"], now)
    due = ", due *{}*".format(eta) if eta else ""
    if nxt == last:
        parts.append("\U0001F4CD *Next stop, the finish:* {} {} in {:,.0f} km{}".format(
            WALK_HOME_ICON, stop_name(pos["ahead"]), pos["to_go"], due))
    else:
        parts.append("\U0001F4CD *Next stop:* {} {} in {:,.0f} km{}".format(
            pos["ahead"][1], stop_name(pos["ahead"]), pos["to_go"], due))
        later = last - nxt - 1
        if later:
            parts.append("{} more stop{}".format(later, "" if later == 1 else "s"))
        parts.append("{} *Finish:* {}".format(WALK_HOME_ICON, stop_name(ROUTE[last])))
    return " {} ".format(WALK_ARROW).join(parts)


def walk_carousel(status, now):
    """Slack's native carousel as a storyboard of the walk, which fits on one screen:

        the stops reached | the walkers, on the road | the next stop | the stops after it | home

    The walkers card draws one walker for each person who added steps since the last board
    (all walkers on the first), up to WALK_CROWD_MAX. Cards carry text and buttons only."""
    pos = status["pos"]
    nxt = pos["leg"]                         # ROUTE index of the next stop
    last = len(ROUTE) - 1
    stops = len(ROUTE) - 2                   # stops between the start and the finish
    behind, ahead = pos["behind"], pos["ahead"]
    cards = []

    # 1. where we have been
    reached = ROUTE[1:nxt]
    if reached:
        day = reached_on((pos["lap"] - 1) * LAP_KM + STOP_KM[nxt - 1], status["boards"])
        cards.append(walk_card(
            "\u2705 *Reached*",
            "{} of {} stops{}".format(len(reached), stops, ", the latest on {}".format(day) if day else ""),
            fit_list([stop_label(stop) for stop in reached], "  \u00b7  ", keep_last=True),
            ("\u2705 Reached", "primary"), "reached"))
    else:
        cards.append(walk_card(
            "\u2705 *Set off*", "From {}".format(WALK_START),
            "{} {}, lap {}.".format(WALK_HOME_ICON, stop_name(ROUTE[0]), pos["lap"]),
            ("\u2705 Set off", "primary"), "reached"))

    # 2. us, on the road
    if status["added"]:
        body = "*+{:,.0f} km* since the last board, *{}%* of the way to {}.".format(
            steps_to_km(status["added"]), int(pos["share"] * 100), stop_name(ahead))
    else:
        body = "*{:,.0f} km* walked together, *{}%* of the way to {}.".format(
            pos["km"], int(pos["share"] * 100), stop_name(ahead))
    cards.append(walk_card(
        walk_crowd(status),
        "On the road: {} \u2192 {}".format(stop_name(behind), stop_name(ahead)), body))

    # 3. the next stop -- or, on the last leg, home
    eta = walk_eta(pos["to_go"], status["pace"], now)
    pace = " On pace for *{}*.".format(eta) if eta else ""
    if nxt == last:
        cards.append(walk_card(
            "{} *{}*".format(WALK_HOME_ICON, stop_name(ahead)),
            "Next stop, the finish \u00b7 {:,.0f} km to go".format(pos["to_go"]),
            "Back to the Coursera office: once round the world." + pace,
            ("\U0001F4CD Up next", None), "next"))
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "*On the road*"}},
                {"type": "carousel", "elements": cards}]
    cards.append(walk_card(
        "{} *{}*".format(ahead[1], stop_name(ahead)),
        "Next stop \u00b7 {:,.0f} km to go".format(pos["to_go"]),
        sentence(ahead[4]) + pace, ("\U0001F4CD Up next", None), "next"))

    # 4. the road after it
    later = ROUTE[nxt + 1:last]
    if later:
        cards.append(walk_card(
            "\u2022 \u2022 \u2022",
            "Then {} more stop{} before home".format(len(later), "" if len(later) == 1 else "s"),
            fit_list([stop_label(stop) for stop in later], "  \u2192  ", keep_last=False)))

    # 5. home
    cards.append(walk_card(
        "{} *{}*".format(WALK_HOME_ICON, stop_name(ROUTE[last])),
        "The finish \u00b7 {:,.0f} km to go".format(LAP_KM - pos["within"]),
        "Back to the Coursera office: once round the world." if pos["lap"] == 1 else
        "Back to the Coursera office: lap {} done.".format(pos["lap"])))
    return [{"type": "section", "text": {"type": "mrkdwn", "text": "*On the road*"}},
            {"type": "carousel", "elements": cards}]


def build_walk_message(full_board, status, config, now=None, carousel=True):
    """The Great Walk dashboard as Slack blocks: where the channel is, what changed since the
    last board, and the road ahead. Nobody is ranked or named. `carousel` False leaves the
    cards out: always so outside the carousel layout, and when a workspace refuses the block."""
    now = now or datetime.now(timezone.utc)
    config = dict(config, walkers=len(full_board))
    status = dict(status, walkers=len(full_board))
    blocks = walk_status_blocks(status, config, now)
    if carousel and config["walk_layout"] == "carousel":
        blocks.extend(walk_carousel(status, now))
    return blocks


def slack_post(token, channel, text, blocks, thread_ts=None):
    """Returns (ts, error)."""
    payload = {"channel": channel, "text": text, "blocks": blocks}
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json; charset=utf-8",
    }
    body, error = send_json(SLACK_POST_URL, headers, payload)
    if error:
        return "", error
    if not body.get("ok"):
        return "", "slack: {}".format(body.get("error"))
    return body.get("ts") or "", None


def snapshot_text(snapshot):
    return json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)


def split_text(text, size=COLUMN_CHUNK):
    return [text[i:i + size] for i in range(0, len(text), size)]


SEAL = re.compile(r"^~(\d+):([0-9a-f]{8})~")


def seal(text):
    """Prefix the snapshot with its length and checksum, so a cut-off, overwritten
    or half-edited column is caught on load instead of being read as a smaller board."""
    return "~{}:{:08x}~{}".format(len(text), zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF, text)


def unseal(stored):
    """(snapshot text, error). Text without a header is an earlier version, saved before sealing."""
    match = SEAL.match(stored)
    if not match:
        return stored, None
    body = stored[match.end():]
    if len(body) != int(match.group(1)) or "{:08x}".format(zlib.crc32(body.encode("utf-8")) & 0xFFFFFFFF) != match.group(2):
        return None, "failed its integrity check"
    return body, None


def read_snapshot(text):
    """(snapshot, error). Empty text is just no snapshot yet; text that is damaged
    or does not parse is an error, so it is never mistaken for a first run."""
    if not str(text or "").strip():
        return None, None
    body, error = unseal(text)
    snapshot = parse_snapshot(body) if body is not None else None
    if snapshot is None:
        return None, "snapshot row exists but is unreadable ({}); left as it is".format(
            error or "corrupt or cut off")
    return snapshot, None


class SnapshotStore(object):
    """Last posted board for one activity. load() then save().

    block_reason is set when a save would be unsafe: writing over a row we could
    not read, or creating a second row after a failed lookup.
    """

    def __init__(self):
        self.block_reason = ""

    def load(self):
        raise NotImplementedError

    def save(self, snapshot):
        raise NotImplementedError


class TableSnapshot(SnapshotStore):
    """One row per activity: row_type <activity>_leaderboard, board JSON spread over STORE_COLUMNS."""

    def __init__(self, token, row_type, table_url=TABLE_URL):
        super(TableSnapshot, self).__init__()
        self.headers = table_headers(token)
        self.row_type = row_type
        self.query_url = table_url
        self.records_url = table_url[:-len("/query")] + "/records" if table_url.endswith("/query") else RECORDS_URL
        self.record_id = ""

    def load(self):
        # No select: the update path needs the $record_id metafield.
        payload = {"where": {"row_type": {"$eq": self.row_type}}, "limit": 1}
        body, error = send_json(self.query_url, self.headers, payload)
        if error:
            self.block_reason = "the earlier read failed"
            return None, "snapshot read " + error
        rows = decode_rows(body)
        if not rows:
            return None, None
        self.record_id = rows[0].get("$record_id") or ""
        stored = "".join(str(rows[0].get(column) or "") for column in STORE_COLUMNS)
        snapshot, error = read_snapshot(stored)
        if error:
            self.block_reason = "the existing row is unreadable"
        return snapshot, error

    def save(self, snapshot):
        if self.block_reason:
            return "snapshot not saved: " + self.block_reason
        pieces = split_text(seal(snapshot_text(snapshot)))
        if len(pieces) > len(STORE_COLUMNS):
            return "snapshot not saved: too big for {} columns".format(len(STORE_COLUMNS))
        fields = {
            "record_key": self.row_type,
            "row_type": self.row_type,
            "id": "leaderboard",
            "name": self.row_type,
            "updated_at": snapshot["at"][-1][:10],
        }
        # Unused columns are cleared so a shrinking snapshot leaves nothing stale behind.
        for index, column in enumerate(STORE_COLUMNS):
            fields[column] = pieces[index] if index < len(pieces) else ""
        document = {"$" + COLUMNS[name]: value for name, value in fields.items()}
        if self.record_id:
            url, method = self.records_url + "/" + self.record_id, "PUT"
        else:
            url, method = self.records_url, "POST"
        _, error = send_json(url, self.headers, {"document": document}, method)
        return "snapshot save " + error if error else None


class FileSnapshot(SnapshotStore):
    """Offline stand-in for the table, for local testing."""

    def __init__(self, path):
        super(FileSnapshot, self).__init__()
        self.path = path

    def load(self):
        if not os.path.exists(self.path):
            return None, None
        with open(self.path, "r", encoding="utf-8") as handle:
            snapshot, error = read_snapshot(handle.read())
        if error:
            self.block_reason = "the existing file is unreadable"
        return snapshot, error

    def save(self, snapshot):
        if self.block_reason:
            return "snapshot not saved: " + self.block_reason
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(seal(snapshot_text(snapshot)))
        return None


def fallback_text(board, config):
    if not board:
        return "No weekly challenges cleared yet" if config["challenge"] else \
            "No {} played yet".format(config["title"]) if config["game"] else \
            "No {} logged yet".format(config["noun"])
    leader = board[0]
    if config["challenge"]:
        return "Challenges leaderboard - {} leads with {} cleared".format(
            leader["name"], humanize(leader["total"], config))
    if config["game"]:
        return "{} leaderboard - {} leads with {}".format(
            config["title"], leader["name"], humanize(leader["total"], config))
    return "{} leaderboard - {} leads with {}".format(
        config["noun"].title(), leader["name"], humanize(leader["total"], config)
    )


def main(input):
    config = activity_config(input)
    channel_id = (input.get("channel_id") or "").strip()
    slack_token = (input.get("slack_bot_token") or "").strip()
    dry_run = truthy(input.get("dry_run"))

    try:
        top_n = int(input.get("top_n") or TOP_N)
    except (TypeError, ValueError):
        top_n = TOP_N
    top_n = max(1, min(top_n, 50))

    result = {
        "today": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "activity": config["activity"],
        "row_type": config["row_type"],
        "snapshot_row_type": config["snapshot_row_type"],
        "channel_id": channel_id,
        "top_n": top_n,
        "min_days": config["min_days"],
        "min_total_percent": config["min_total_percent"],
        "max_total_gap": config["max_total_gap"],
        "leader": "",
        "leader_total": 0,
        "crew_total": 0,
        "participants": 0,
        "total_participants": 0,
        "hidden_participants": 0,
        "dry_run": dry_run,
        "message_ts": "",
        "thread_ts": "",
        "posted": False,
        "thread_posted": False,
        "had_previous_snapshot": False,
        "snapshot_saved": False,
        "snapshot_chars": 0,
        "history_runs_stored": 0,
        "journey_km": 0,
        "journey_lap": 0,
        "journey_leg": 0,
        "next_stop": "",
        "walkers_active": 0,
        "stops_passed": 0,
        "carousel_posted": False,
        "categories_posted": False,
        "ok": False,
        "error": "",
    }

    token = input.get("workato_dev_api") or input.get("workato_api_token")
    table_url = input.get("table_url") or TABLE_URL

    if input.get("local_data_file"):
        rows = load_local_rows(input["local_data_file"])
    else:
        if not token:
            result["error"] = "workato_dev_api is required unless local_data_file is set"
            return result
        if config["challenge"]:
            rows = fetch_rows(token, {"row_type": {"$in": config["row_types"]}}, table_url,
                              select=CHALLENGE_SELECT)
        else:
            rows = fetch_rows(token, {"row_type": {"$eq": config["row_type"]}}, table_url)

    full_board = build_board(rows, config)
    qualified = qualify(full_board, config)
    board = filter_board(qualified, config)
    starters = getting_started(full_board, qualified)

    result["participants"] = len(board)
    result["total_participants"] = len(full_board)
    result["hidden_participants"] = len(full_board) - len(board)
    result["crew_total"] = sum(entry["total"] for entry in board)
    if board:
        result["leader"] = board[0]["name"]
        result["leader_total"] = board[0]["total"]

    if not board:
        if full_board:
            result["error"] = "nobody qualifies for {} leaderboard yet".format(config["activity"])
        else:
            result["error"] = "nobody has cleared a weekly challenge yet" if config["challenge"] else \
                "nobody has {} {} yet".format("scored in" if config["game"] else "logged", config["activity"])
        return result
    if not channel_id:
        result["error"] = "no channel_id"
        return result
    if not slack_token:
        result["error"] = "slack_bot_token is required"
        return result

    if input.get("local_snapshot_file"):
        store = FileSnapshot(input["local_snapshot_file"])
    elif token:
        store = TableSnapshot(token, config["snapshot_row_type"], table_url)
    else:
        store = None

    errors = []
    previous = None
    if store:
        previous, error = store.load()
        if error:
            errors.append(error)
    previous_people = previous["people"] if previous else None
    history = previous["history"] if previous else []
    changes = compute_changes(qualified, previous_people)
    trends = compute_trends(qualified, history) if changes is not None else None
    result["had_previous_snapshot"] = changes is not None

    snapshot = build_snapshot(qualified, starters, history, config["history_runs"])
    snapshot_size = len(snapshot_text(snapshot))
    result["snapshot_chars"] = snapshot_size
    result["history_runs_stored"] = len(snapshot["at"])
    if result["history_runs_stored"] < min(config["history_runs"], len(history) + 1):
        errors.append("history trimmed to {} {} to fit {:,} characters".format(
            result["history_runs_stored"], "run" if result["history_runs_stored"] == 1 else "runs", SNAPSHOT_ROOM))

    text = fallback_text(board, config)
    movers = "\n".join(line for line in (
        movers_line(qualified, changes, config),
        extras_line(qualified, changes, history, config),
    ) if line)
    shown_count = min(top_n, len(board))
    has_thread = config["thread_full_list"] and (len(qualified) > shown_count or bool(starters))
    plain_blocks = None
    if config["walk"]:
        now = datetime.now(timezone.utc)
        status = walk_status(full_board, qualified, previous_people, history, now)
        result["journey_km"] = round(status["pos"]["km"], 1)
        result["journey_lap"] = status["pos"]["lap"]
        result["journey_leg"] = status["pos"]["leg"]
        result["next_stop"] = status["pos"]["ahead"][0]
        text = walk_fallback_text(status)
        result["walkers_active"] = status["active"]
        result["stops_passed"] = len(status["arrivals"])
        blocks = build_walk_message(full_board, status, config, now)
        if config["walk_layout"] == "carousel":
            plain_blocks = build_walk_message(full_board, status, config, now, carousel=False)
        has_thread = False
    else:
        blocks = build_message(board, config, top_n, full_board, changes, has_thread, trends, movers)
    rest = qualified[shown_count:]
    thread = build_thread(rest, starters, config, changes, trends) if has_thread else []
    if config["walk"] and config["walk_layout"] == "thread":
        thread = walk_carousel(status, now)          # the storyboard, under the post

    categories = build_category_thread(board, config) if config["challenge"] and config["category_thread"] else []
    if dry_run:
        # A dry run posts the board like any other; all it does not do is store anything. The
        # payloads come back in `preview` too, for looking at what was sent.
        result["preview"] = json.dumps({"message": blocks, "thread": thread,
                                        "categories": categories}, indent=2)

    ts, error = slack_post(slack_token, channel_id, text, blocks)
    if error and plain_blocks and "invalid_blocks" in error:
        # A workspace that does not take the carousel block: the board is still worth posting.
        errors.append("carousel refused by Slack ({}); posted without it".format(error[:80]))
        ts, error = slack_post(slack_token, channel_id, text, plain_blocks)
    elif not error and plain_blocks:
        result["carousel_posted"] = True
    if error:
        # Nothing saved: the next run still compares against the last board people saw.
        result["error"] = "; ".join(errors + ["post failed: " + error])
        return result
    result["posted"] = True
    result["message_ts"] = ts

    if thread:
        thread_text = ("{} - on the road".format(JOURNEY_NAME) if config["walk"] else
                       "{} leaderboard - the rest of the board".format(config["title"]))
        thread_message_ts, error = slack_post(slack_token, channel_id, thread_text, thread, thread_ts=ts)
        if error and config["walk"] and "invalid_blocks" in error:
            # The route strip in the post already tells the same story.
            errors.append("carousel refused by Slack ({}); the post has the route strip".format(error[:80]))
        elif error:
            errors.append("thread failed: " + error)
        else:
            result["thread_posted"] = True
            result["thread_ts"] = thread_message_ts
            result["carousel_posted"] = config["walk"]

    if categories:
        # a reply of its own, so the rest of the list (above) and this one are two things to open or skip
        _ts, error = slack_post(slack_token, channel_id, "{} leaderboard - who cleared what".format(config["title"]),
                                categories, thread_ts=ts)
        if error:
            errors.append("category thread failed: " + error)
        else:
            result["categories_posted"] = True

    keep = config["save_snapshot"] and not dry_run
    if store and keep and snapshot_size > SNAPSHOT_ROOM:
        errors.append("snapshot not saved: {:,} characters is over the {:,} character capacity".format(
            snapshot_size, SNAPSHOT_ROOM))
    elif store and keep:
        error = store.save(snapshot)
        if error:
            errors.append(error)
        else:
            result["snapshot_saved"] = True

    result["ok"] = True
    result["error"] = "; ".join(errors)
    return result


def cli():
    parser = argparse.ArgumentParser(description="Post an activity leaderboard to Slack.")
    parser.add_argument("activity", nargs="?", default="step",
                        help="step, pushup, plank, ... a game: imemory, iadd, isub, imultiple, "
                             "the walk dashboard: greatwalk, or the weekly challenges: challenge")
    parser.add_argument("--channel-id", default="C0ASWC1C11Q")
    parser.add_argument("--top-n", type=int, default=TOP_N)
    parser.add_argument("--local-data-file")
    parser.add_argument("--local-snapshot-file")
    parser.add_argument("--unit")
    parser.add_argument("--title")
    parser.add_argument("--noun")
    parser.add_argument("--icon")
    parser.add_argument("--header-image-url")
    parser.add_argument("--set-based", action="store_true")
    parser.add_argument("--best-phrase")
    parser.add_argument("--min-days", type=int)
    parser.add_argument("--show-average", choices=("true", "false"), help="avg/day column (challenge: the clear rate)")
    parser.add_argument("--min-total-percent", type=float)
    parser.add_argument("--max-total-gap", type=int)
    parser.add_argument("--history-runs", type=int)
    parser.add_argument("--snapshot-row-type")
    parser.add_argument("--no-save-snapshot", action="store_true", help="post, but do not write the snapshot row")
    parser.add_argument("--up-marker")
    parser.add_argument("--down-marker")
    parser.add_argument("--no-thread", action="store_true", help="skip the full list thread reply")
    parser.add_argument("--no-carousel", action="store_true", help="greatwalk: leave out the carousel")
    parser.add_argument("--walk-layout", choices=WALK_LAYOUTS, help="greatwalk: thread (default), strip or carousel")
    parser.add_argument("--dry-run", action="store_true", help="post the board but store nothing (no snapshot save)")
    args = parser.parse_args()

    payload = vars(args)
    payload["thread_full_list"] = False if payload.pop("no_thread") else None   # None: the default
    payload["save_snapshot"] = not payload.pop("no_save_snapshot")
    payload["use_carousel"] = not payload.pop("no_carousel")
    payload["workato_dev_api"] = os.environ.get("WORKATO_API_TOKEN")
    payload["slack_bot_token"] = os.environ.get("SLACK_BOT_TOKEN")
    result = main(payload)
    preview = result.pop("preview", "")
    print(json.dumps(result, indent=2))
    if preview:
        print(preview)


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:
        sys.exit(str(exc))
