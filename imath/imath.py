"""
iMath -- iadd, isub, imultiple, iaverage and idivide: mental-arithmetic games played in a
Slack thread.

One Python step serves all five games and both recipes. What it does is decided
by the input:
`action_value` present  -> a button was pressed (START GAME, or an answer)
otherwise               -> someone typed a keyword (post the rules card)

KEYWORDS (a word on its own, any case; add `daily` for today's shared set)
    iadd        addition            iadd daily
    isub        subtraction         isub daily
    imultiple   multiplication      imultiple daily      (imultiply works too)
    iaverage    averages            iaverage daily       "12, 18, 24 = ?" under "Average of"
    idivide     division            idivide daily        every answer is a whole number

THE GAME
    A sum appears as a big heading with a few near-miss answers as buttons --
    "47 + 38 = ?" with [85] [75] [84]. Tap the right one before the question's
    clock runs out. Each correct answer is +1; the next one is harder.

    HOW IT GETS HARD (see TIERS -- every number is data, not logic)
      * Bigger numbers: 2 + 11, then 38 + 47, then 361 + 478 + 125.
      * More terms: two, then three, then four.
      * More answers to choose from: 2, then 3, then 4.
      * Tighter than the sum deserves: the clock grows more slowly than the work.
      * Subtraction goes negative (23 - 47) from its fourth level on.
      * Wrong answers are near misses that differ from the right one in ONE digit, the
        tens digit, and are never more than three tens away -- 376 beside 366, 386 and
        356. They keep the last digit and everything in front of the tens, so neither
        the ending nor rounding the sum gives the answer away: it has to be worked out.
        The wrong ones are drawn at random from the nearest few, so the right answer is
        not always the middle number. Subtraction sometimes offers the sign flipped.
      * The ramp is gentle: many easy and medium questions before the hard ones.
      * It never stands still: from the fourth rung on, every right answer stretches the
        numbers a little (CREEP, 3% an answer) until the next rung takes over, and past
        the top rung the stretch goes on for ever, with a new Level every
        TOP_LEVEL_EVERY answers. A five-minute game is still climbing at minute five.

    DIFFICULTY (a dropdown on the rules card; Easy unless the player picks another)
      Easy       3 + 5 = ?       the ladder above, exactly as it always was
      Medium     34 + 56 = ?     starts further up the ladder: bigger numbers from the first question
      Hard       ? + 56 = 91     the same rung as Medium, with a number hidden inside the sum
      Very hard  ? + 84 + 61 = 230    a later rung still (more terms, bigger numbers), hidden number
      Every difficulty keeps climbing from where it began, and counts its levels from 1.
      Each has its own personal best and channel record (user rows below). A daily has
      no dropdown: it is one shared set, always Easy. Play again keeps the difficulty.
      Picking from the dropdown is its own click (imath_difficulty): the card is redrawn
      with that difficulty's example and targets; nothing is timed or spent.

    A shield (every SHIELD_EVERY correct answers) forgives one miss; with none, a
    wrong answer -- or running out of time -- ends the game.

    THE ANSWER CLOCK is the same mechanism as iMemory: the step that posted the
    question stays alive, counts down on screen once a second, and settles the
    question as a miss a moment after zero (CLICK_GRACE_SECONDS + CLICK_ARRIVAL_SECONDS
    later, so a click pressed in time but still on its way is not thrown away). The
    count starts when the question is on screen, not before the writes that put it
    there. Both recipes must therefore allow several jobs at once (Workato: recipe
    Settings -> Concurrency, 10 or more): with fewer, the click waits behind the
    countdown job and every answer arrives as Time's up.

    The clock is a MESSAGE OF ITS OWN, posted below the question ("7s", with the
    Correct / Level up note beside it) and removed when the game ends. The countdown
    edits only that message. The question message is changed only by the click that
    answers it or by the timeout, each of which claims the question first -- so a tick
    that is late can show a wrong number on the clock, but can never put the previous
    question back on screen.

WHAT TO BEAT (the rules card, and the line above every question)
    Three rungs, read once when a game starts, for the difficulty being played:
      your own best  ->  the person just above it  ->  the channel best
    The next person is the lowest score over yours (left out if they ARE the channel
    best, or if you have no best yet). The line above the question moves up a rung the
    moment one is passed, and passing each is marked once on the question. A daily has
    none. The rules card is kept short on purpose -- three rules, the targets in a
    section of their own -- so Slack never folds anything behind "Show more".

TEST GAMES (input `testing` = yes, on the recipe that starts the game)
    A game that plays normally but saves nothing: no personal best, no games-played count,
    no daily attempt, and no record post or daily nudge in the channel. A test may replay
    today's daily as often as it likes. The game remembers it, so clicks stay tests even
    if the click recipe does not map the input; Play again stays a test too. The one row
    it must write is the in-progress game (session): every click is a separate job and
    the game lives there, so it is overwritten by the player's next game.

WHAT HAPPENS ON EACH PATH
    START   detect the keyword -> claim the message (retry guard) -> post the rules
            card with a Start button and wait. Nothing is timed, and a daily
            attempt is not spent, until Start is pressed.
    BEGIN   Start pressed -> (daily: spend the attempt) -> first question in the
            same message -> count down, ending the game at zero.
    ANSWER  an answer pressed -> check it is the owner's, on the live message, for
            the live step -> CLAIM it (status busy, so a double click or the
            clock reaching zero cannot settle it twice) -> judge -> show the next
            question straight away (a one-line "Correct" rides along on it for a
            second) or end the game.

DAILY NUDGE
    When a daily game ends -- whatever the score, a 0 included -- a top-level post invites the channel
    to try it: who played, the score, level and time, the coloured squares (no
    questions) and a "Play today's daily" button. Anyone can press it: the bot posts a
    root message naming them and their daily rules card goes in that thread (nothing is
    spent until they press Start), so each person's game, and Play again, has a thread
    of its own. Switch the post off with announce_daily=false. It is separate from the
    record posts, which a daily game never triggers.

AFTER A GAME
    The result card carries Play again and (while today's daily is unplayed) Today's
    daily. Play again starts a new game at once in a new message in the same thread;
    Today's daily posts the daily rules card. Either one retires the old card: its
    result stays, its buttons go -- as does typing the keyword while it is the
    current card.

BUTTONS (tell your Slack trigger to listen for action_id starting `imath_`)
    imath_start                      Start game       value  <game>|<user>|0|start
    imath_difficulty                 the dropdown     value  <game>|<user>|0|<easy|medium|hard|very_hard>
                                     (a select, not a button: map the chosen option's
                                     value to the `selected_value` input -- from
                                     state.values.imath_difficulty.imath_difficulty
                                     .selected_option.value, which Slack sends with
                                     every click, or actions[0].selected_option.value.
                                     Start also applies it, so a pick that was never
                                     processed still plays the difficulty shown.)
    imath_opt_1 .. imath_opt_4       the answers      value  <game>|<user>|<step>|<number>
    imath_again                      Play again       value  <game>|<user>|<step>|again
    imath_daily                      Today's daily    value  <game>|<user>|<step>|daily
    imath_try                        Play today's daily (on a channel post; ANYONE may
                                     press it)        value  <game>|anyone|0|try
    imath_play                       Play a game (on the scheduled daily nudge; ANYONE may
                                     press it)        value  <game>|anyone|0|play
    imath_start (again)              Play iAdd (Hard), under a record post; ANYONE may press
                                     it. It shares Start's action_id so the trigger needs
                                     no change.       value  <game>|anyone|0|join:<difficulty>
                                     The presser's own rules card opens as a reply in the
                                     post's thread, its dropdown on the record's difficulty.
    block_id: imath_intro, imath_over, imath_q<step> (changes every question: do not filter on it)

ROWS (workato_governance_unified, tagged by row_type; <slug> is add | sub | mul | avg | div)
    math_<slug>_user       one per player: best score, the time of that run, games
                           played, last score. This is EASY. Each harder difficulty has
                           rows of its own: math_<slug>_medium_user, _hard_user,
                           _very_hard_user.
    math_<slug>_session    one per player: the game in progress
    math_<slug>_daily      one per player per day: score, time, share line. Written
                           when Start is pressed, so walking away does not give the
                           attempt back.

    Column re-use is the same as iMemory:
        personal_best_single_set  best score
        total                     time of the best run, seconds, as text "12.4"
        total_planks              games played
        current_value             last game's score
        content                   json: "pts" is every correct answer over all games
                                  (the leaderboard ranks on it), beside the weekly entries
        content (session)         the game state, JSON
        content (daily)           the share line

    "Time" is the sum of the player's thinking time, at most one question's clock
    each. A better run is a higher score, then a lower time; a run with no correct
    answer is never a personal best.

CHANNEL CELEBRATIONS, exactly as iMemory: a free game that beats the player's best
posts "New personal best" to the channel; one that beats everyone's posts "New
channel record". Both carry a Play button for anyone reading it (see BUTTONS). Withheld: a first scored game, channel records while one person
plays, scores of 0, and daily games.

Input / output schema: imath_input_schema.json / imath_output_schema.json
"""

import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

TABLE_ID = "0b863cb1-4712-416b-a9d5-7bf7f2f9b059"
TABLE_QUERY_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
TABLE_RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
TABLE_RECORD_URL = TABLE_RECORDS_URL + "/{}"

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
SLACK_UPDATE_URL = "https://slack.com/api/chat.update"
SLACK_DELETE_URL = "https://slack.com/api/chat.delete"
SLACK_EPHEMERAL_URL = "https://slack.com/api/chat.postEphemeral"
SLACK_USER_URL = "https://slack.com/api/users.info"

HTTP_TIMEOUT = 30
DEFAULT_TZ_OFFSET = -7 * 3600     # used only when users.info fails

SKIP_SUBTYPES = {
    "bot_message", "message_changed", "message_deleted", "message_replied",
    "thread_broadcast", "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "channel_archive", "channel_unarchive",
    "file_share_reply", "tombstone", "reminder_add",
}

# --------------------------------------------------------------------------
# Column map -- the only place a field UUID appears
# --------------------------------------------------------------------------

COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "current_value": "20b624b5-587c-4a2e-aa43-bdb8e21a5fe9",
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
    "status": "863a9d40-87a7-49ff-ba40-32858e62cd48",
    "slack_channel_id": "7101072d-867b-4104-a1e4-ef6611adaaa9",
    "total": "e96b5acc-4196-497e-a18b-7faf7016ec4c",
    "personal_best_single_set": "6198fe02-e888-44a8-bd01-b47d75ee896d",
    "total_planks": "ea80e176-5bfb-421d-bafe-dd4828d67916",
    "first_seen": "0e8058db-6de1-4bae-98eb-4e45fc506435",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
    "last_processed_ts": "5761a90c-832e-4bf5-aaee-5d6a4d43f045",
}

# The API rejects the whole document on one type mismatch, so values are
# coerced to these before sending.
COLUMN_TYPES = {
    "record_key": "string", "row_type": "string", "id": "string",
    "name": "string", "current_value": "string", "content": "string",
    "status": "string", "slack_channel_id": "string", "total": "string",
    "personal_best_single_set": "integer", "total_planks": "integer",
    "first_seen": "date", "updated_at": "date", "last_processed_ts": "string",
}

LOOKUP_FAILED = object()

# --------------------------------------------------------------------------
# Game tuning
# --------------------------------------------------------------------------

# A keyword on its own, optionally followed by `daily`. Word-bounded so
# "iaddress" and "my_iadd" start nothing.
KEYWORDS = re.compile(
    r"(?<![A-Za-z0-9_])(iadd|isub|imultiple|imultiply|iaverage|idivide)(?:\s+(daily))?(?![A-Za-z0-9_])",
    re.IGNORECASE)

# The daily set changes at midnight in ONE zone, so everyone in the channel is on
# the same set at the same moment.
DAILY_TZ_OFFSET = -7 * 3600      # America/Los_Angeles, the channel's zone

SESSION_ACTIVE = "active"
SESSION_BUSY = "busy"            # a click (or the clock) is being processed
SESSION_STARTING = "starting"
SESSION_READY = "ready"          # rules card posted, waiting for the Start button
SESSION_OVER = "over"
STARTING_STALE_SECONDS = 60      # a claim older than this with no game is a crashed run

DAILY_PLAYING = "playing"        # claimed; quitting does not give the attempt back
DAILY_DONE = "done"

# A click Slack stamps this long after the deadline is a miss too, so a step that
# was killed before it could count down cannot give extra time.
CLICK_GRACE_SECONDS = 2
# A click reaches its job a second or so after Slack stamps it. The countdown waits this
# long past the click deadline before it calls time, so an in-time click that is still on
# its way is never beaten to the question and thrown away as "stale".
CLICK_ARRIVAL_SECONDS = 1.5
# After a game-over from a click, the card is shown once more this long after: the
# countdown step may have had one edit in flight when the click was claimed, and a
# stale edit landing on top of the card would hide the result for good.
REASSERT_SECONDS = 1.3

SHIELD_EVERY = 5                 # correct answers per shield earned
SHIELD_CAP = 1                   # shields held at once

SHARE_MAX = 30                   # squares in the share line before it elides
SQUARES = {"g": "\U0001F7E9", "y": "\U0001F7E8", "r": "\U0001F7E5"}

# Banner above a CHANNEL-record announcement. A URL or a Slack file id
# (Fxxxxxxxx); overridable per run with the `record_banner` input.
RECORD_BANNER = ("https://coursera.enterprise.slack.com/files/U038ZCDAY6P/"
                 "F0BT1FETK4K/chatgpt_image_aug_28__2026__12_32_45_am.png")
RECORD_BANNER_ALT = "New channel record"

# Stand-ins so a test can run a whole game in milliseconds.
_sleep = time.sleep
_clock = time.monotonic
_now = time.time
_rng = random.Random()

# --------------------------------------------------------------------------
# The games
# --------------------------------------------------------------------------

GAMES = {
    "iadd": {
        "name": "iAdd", "slug": "add", "kind": "add", "icon": ":heavy_plus_sign:",
    },
    "isub": {
        "name": "iSub", "slug": "sub", "kind": "sub", "icon": ":heavy_minus_sign:",
    },
    "imultiple": {
        "name": "iMultiple", "slug": "mul", "kind": "mul",
        "icon": ":heavy_multiplication_x:",
    },
    "iaverage": {
        "name": "iAverage", "slug": "avg", "kind": "avg", "icon": ":bar_chart:",
    },
    "idivide": {
        "name": "iDivide", "slug": "div", "kind": "div", "icon": ":heavy_division_sign:",
    },
}
KEYWORD_GAME = {"iadd": "iadd", "isub": "isub", "imultiple": "imultiple",
                "imultiply": "imultiple", "iaverage": "iaverage", "idivide": "idivide"}

# Difficulty ladders. A tier applies from `from` correct answers upward. `seconds`
# is the clock for one question; `options` how many answers are offered.
# Retune here -- nothing else in the file encodes a difficulty.
TIERS = {
    "iadd": [
        {"from": 0,  "lo": 2,   "hi": 12,  "terms": 2, "options": 2, "seconds": 8},
        {"from": 6,  "lo": 6,   "hi": 40,  "terms": 2, "options": 3, "seconds": 9},
        {"from": 12, "lo": 20,  "hi": 99,  "terms": 2, "options": 3, "seconds": 11},
        {"from": 18, "lo": 10,  "hi": 40,  "terms": 3, "options": 3, "seconds": 13},
        {"from": 24, "lo": 30,  "hi": 120, "terms": 3, "options": 4, "seconds": 14},
        {"from": 31, "lo": 50,  "hi": 250, "terms": 3, "options": 4, "seconds": 15},
        {"from": 38, "lo": 40,  "hi": 300, "terms": 4, "options": 4, "seconds": 17},
        # past the old top: a long game keeps climbing instead of levelling off
        {"from": 46, "lo": 60,  "hi": 350, "terms": 4, "options": 4, "seconds": 18},
        {"from": 56, "lo": 40,  "hi": 250, "terms": 5, "options": 4, "seconds": 21},
        {"from": 68, "lo": 80,  "hi": 400, "terms": 5, "options": 4, "seconds": 23},
    ],
    "isub": [
        {"from": 0,  "lo": 2,   "hi": 20,  "terms": 2, "neg": False, "options": 2, "seconds": 8},
        {"from": 6,  "lo": 10,  "hi": 60,  "terms": 2, "neg": False, "options": 3, "seconds": 9},
        {"from": 12, "lo": 30,  "hi": 150, "terms": 2, "neg": False, "options": 3, "seconds": 11},
        {"from": 18, "lo": 20,  "hi": 99,  "terms": 2, "neg": True,  "options": 3, "seconds": 12},
        {"from": 24, "lo": 20,  "hi": 99,  "terms": 3, "neg": True,  "options": 4, "seconds": 14},
        {"from": 31, "lo": 50,  "hi": 300, "terms": 3, "neg": True,  "options": 4, "seconds": 15},
        {"from": 38, "lo": 100, "hi": 700, "terms": 3, "neg": True,  "options": 4, "seconds": 16},
        {"from": 46, "lo": 100, "hi": 600, "terms": 3, "neg": True,  "options": 4, "seconds": 17},
        {"from": 56, "lo": 60,  "hi": 400, "terms": 4, "neg": True,  "options": 4, "seconds": 20},
        {"from": 68, "lo": 100, "hi": 800, "terms": 4, "neg": True,  "options": 4, "seconds": 22},
    ],
    "imultiple": [
        {"from": 0,  "a": (2, 5),    "b": (2, 9),   "options": 2, "seconds": 8},
        {"from": 6,  "a": (2, 9),    "b": (2, 9),   "options": 3, "seconds": 9},
        {"from": 12, "a": (2, 12),   "b": (6, 12),  "options": 3, "seconds": 11},
        {"from": 18, "a": (11, 25),  "b": (2, 6),   "options": 3, "seconds": 12},
        {"from": 24, "a": (11, 30),  "b": (2, 9),   "options": 4, "seconds": 13},
        {"from": 31, "a": (21, 60),  "b": (3, 9),   "options": 4, "seconds": 15},
        {"from": 38, "a": (12, 29),  "b": (11, 19), "options": 4, "seconds": 18},
        {"from": 46, "a": (31, 99),  "b": (3, 9),   "options": 4, "seconds": 18},
        {"from": 56, "a": (12, 49),  "b": (12, 49), "options": 4, "seconds": 20},
        {"from": 66, "a": (101, 499), "b": (3, 9),  "options": 4, "seconds": 20},
        {"from": 78, "a": (13, 59),  "b": (13, 29), "options": 4, "seconds": 22},
        {"from": 92, "a": (101, 999), "b": (3, 9),  "options": 4, "seconds": 22},
    ],
    # `mean` is the answer's range, `spread` how far a number may sit from it.
    "iaverage": [
        {"from": 0,  "mean": (3, 15),   "spread": 4,  "terms": 2, "options": 2, "seconds": 9},
        {"from": 6,  "mean": (5, 30),   "spread": 8,  "terms": 3, "options": 3, "seconds": 11},
        {"from": 12, "mean": (10, 60),  "spread": 15, "terms": 3, "options": 3, "seconds": 13},
        {"from": 18, "mean": (20, 99),  "spread": 25, "terms": 4, "options": 4, "seconds": 15},
        {"from": 24, "mean": (30, 150), "spread": 40, "terms": 4, "options": 4, "seconds": 17},
        {"from": 31, "mean": (50, 300), "spread": 60, "terms": 5, "options": 4, "seconds": 19},
        {"from": 40, "mean": (80, 400), "spread": 48, "terms": 5, "options": 4, "seconds": 20},
        {"from": 50, "mean": (100, 600), "spread": 60, "terms": 6, "options": 4, "seconds": 24},
        {"from": 62, "mean": (150, 900), "spread": 90, "terms": 6, "options": 4, "seconds": 26},
    ],
    # `q` is the answer's range, `d` the divisor's; the dividend is their product.
    "idivide": [
        {"from": 0,  "q": (2, 9),     "d": (2, 5),   "options": 2, "seconds": 8},
        {"from": 6,  "q": (2, 9),     "d": (2, 9),   "options": 3, "seconds": 9},
        {"from": 12, "q": (6, 12),    "d": (3, 12),  "options": 3, "seconds": 11},
        {"from": 18, "q": (11, 25),   "d": (2, 6),   "options": 3, "seconds": 13},
        {"from": 24, "q": (11, 30),   "d": (3, 9),   "options": 4, "seconds": 14},
        {"from": 31, "q": (21, 60),   "d": (3, 9),   "options": 4, "seconds": 16},
        {"from": 38, "q": (12, 29),   "d": (11, 19), "options": 4, "seconds": 19},
        {"from": 46, "q": (31, 99),   "d": (3, 9),   "options": 4, "seconds": 20},
        {"from": 56, "q": (101, 299), "d": (3, 9),   "options": 4, "seconds": 22},
        {"from": 68, "q": (21, 60),   "d": (12, 29), "options": 4, "seconds": 24},
        {"from": 82, "q": (151, 499), "d": (3, 9),   "options": 4, "seconds": 24},
    ],
}

# Difficulty is where on a game's ladder a run begins, and what shape the questions take:
#   result    3 + 5 = ?          the usual: work out the answer
#   missing   ? + 56 = 91        the answer is a number inside the sum
# EASY is the ladder exactly as it always was. The others begin at a later rung of the
# same ladder (DIFFICULTY_START) and keep climbing from there; "Level" counts from 1
# within the difficulty. Each difficulty keeps its own personal best and channel record.
EASY = "easy"
DIFFICULTY = {
    "easy":      {"label": "Easy",      "form": "result"},
    "medium":    {"label": "Medium",    "form": "result"},
    "hard":      {"label": "Hard",      "form": "missing"},
    "very_hard": {"label": "Very hard", "form": "missing"},
}
# Index into TIERS[game] where each difficulty begins. Easy is always rung 0.
DIFFICULTY_START = {
    "iadd":      {"medium": 2, "hard": 2, "very_hard": 4},   # 20-99 / the same, blanked / 3 terms
    "isub":      {"medium": 2, "hard": 2, "very_hard": 4},
    "imultiple": {"medium": 3, "hard": 3, "very_hard": 5},   # 17 x 4 / ? x 4 = 68 / ? x 7 = 273
    "iaverage":  {"medium": 2, "hard": 2, "very_hard": 3},
    "idivide":   {"medium": 3, "hard": 3, "very_hard": 5},
}
# Inside a rung the game must not stand still: each right answer since the rung began
# stretches its number ranges by CREEP (3% an answer), from the fourth rung on -- the
# first three are the gentle start and stay exactly as written. Past the top rung the
# stretch never stops, and every TOP_LEVEL_EVERY answers there is a new Level.
CREEP = 0.03
CREEP_RUNG = 3
TOP_LEVEL_EVERY = 10
# What the dropdown shows under each option, drawn from the game itself so it cannot drift.
EXAMPLE_SEED = 11

NOTICE_QUICK = 1                 # ticks a plain "Correct" stays on the question
NOTICE_LONG = 3                  # ticks a level-up, shield or record line stays


def detect(text):
    """(game, 'play' | 'daily') for the first keyword in the message, else None."""
    match = KEYWORDS.search(text or "")
    if not match:
        return None
    return KEYWORD_GAME[match.group(1).lower()], ("daily" if match.group(2) else "play")


def row_type(game, kind):
    """kind is user | session | daily -> e.g. math_add_session."""
    return "math_{}_{}".format(GAMES[game]["slug"], kind)


def difficulty_of(state):
    """The difficulty a game state carries; a game from before difficulties is Easy."""
    diff = (state or {}).get("diff")
    return diff if diff in DIFFICULTY else EASY


def user_row_type(game, diff=EASY):
    """The player rows (best score, games played) for a game at a difficulty.

    Easy keeps the original name, so every existing best stays where it was; each harder
    difficulty has rows of its own -- math_add_hard_user -- because a 12 on Very hard and
    a 12 on Easy are not the same achievement. Sessions and dailies are not split."""
    if diff == EASY or diff not in DIFFICULTY:
        return row_type(game, "user")
    return "math_{}_{}_user".format(GAMES[game]["slug"], diff)


def tier_for(game, level, diff=EASY):
    """(index, tier) for a player with `level` correct answers, at difficulty `diff`.

    A harder difficulty begins further up the same ladder, as if the player had already
    earned that rung. `index` counts from where the difficulty began, so index + 1 is the
    "Level" the player sees: every difficulty starts at Level 1."""
    tiers = TIERS[game]
    first = DIFFICULTY_START.get(game, {}).get(diff, 0)
    progress = int(level) + tiers[first]["from"]
    index = first
    for i, tier in enumerate(tiers):
        if progress >= tier["from"]:
            index = i
    return index - first, tiers[index]


def _stretch(lo, hi, grow):
    """(lo, hi) grown by `grow`, both ends, so the easy draws thin out as the hard ones
    come in. A one-digit range is left alone: 7 x 8 must not turn into 7 x 11."""
    if hi < 10:
        return lo, hi
    return max(lo, int(round(lo * grow))), max(hi, int(round(hi * grow)))


def play_tier(game, level, diff=EASY):
    """(index, tier) as a question is actually played: the rung from tier_for, with its
    numbers stretched by CREEP for each right answer since the rung began, so no stretch of
    the game stands still. Rungs before CREEP_RUNG are played exactly as written.

    Past the top rung the stretch never stops, and every TOP_LEVEL_EVERY right answers
    counts as a level of its own, so a long game keeps hearing "Level up"."""
    index, tier = tier_for(game, level, diff)
    tiers = TIERS[game]
    first = DIFFICULTY_START.get(game, {}).get(diff, 0)
    rung = first + index
    extra = int(level) + tiers[first]["from"] - tier["from"]
    if rung == len(tiers) - 1:
        index += extra // TOP_LEVEL_EVERY
    if rung < CREEP_RUNG or extra <= 0:
        return index, tier
    grow = 1 + CREEP * extra
    tier = dict(tier)
    if "hi" in tier:
        tier["lo"], tier["hi"] = _stretch(tier["lo"], tier["hi"], grow)
    for key in ("a", "b", "q", "d", "mean"):
        if key in tier:
            tier[key] = _stretch(tier[key][0], tier[key][1], grow)
    if "spread" in tier:
        tier["spread"] = int(round(tier["spread"] * grow))
    return index, tier


def fmt(number):
    """A number as shown: a real minus sign, so -24 reads as a number, not a dash."""
    return str(number).replace("-", "−")


def question_text(state):
    """The question as the heading: 'a + b = ?', or the statement with its blank."""
    if state.get("form") == "missing":
        return state["expr"]
    return "{} = ?".format(state["expr"])


def solved_text(state):
    """The finished statement, answer in place: '47 + 38 = 85' or '35 + 56 = 91'. An
    average says what it is ('Average of 12, 18 = 15'): this line stands on its own."""
    answer = fmt(state["answer"])
    if state.get("form") == "missing":
        text = state["expr"].replace("?", answer)
    else:
        text = "{} = {}".format(state["expr"], answer)
    return ("Average of " + text) if is_average(state) else text


def is_average(state):
    return GAMES.get((state or {}).get("game"), {}).get("kind") == "avg"


def question_prompt(state):
    """The words above an average's numbers, which the heading leaves out so the eye goes
    straight to the numbers: 'Average of' -- or, with a blank, what the blank is."""
    if not is_average(state):
        return ""
    if state.get("form") == "missing":
        return "*Find the missing number*  ·  the average is after the ="
    return "*Average of*"


def difficulty_label(state):
    """'Hard' for a game on a harder difficulty; '' on Easy, which has always been unmarked."""
    diff = difficulty_of(state)
    return "" if diff == EASY else DIFFICULTY[diff]["label"]


def game_title(game, diff=EASY):
    """'iAdd (Hard)', 'iAdd (Easy)' -- a game and its difficulty, for the posts the whole
    channel reads. A record only means something at a difficulty, and from four levels in
    one channel an unmarked 'iAdd' would leave readers guessing which."""
    label = DIFFICULTY[diff]["label"] if diff in DIFFICULTY else DIFFICULTY[EASY]["label"]
    return "{} ({})".format(GAMES[game]["name"], label)


def example_question(game, diff):
    """A sample question at the start of `diff`, the same every time it is asked for. A
    dropdown has no line above it to say 'Average of', so an average's example says it."""
    text = question_text(make_problem(game, 0, random.Random(EXAMPLE_SEED), diff))
    return ("Average of " + text) if GAMES[game]["kind"] == "avg" else text


def swap_digits(number):
    """The number with its last two digits swapped (85 -> 58), or None."""
    digits = str(abs(number))
    if len(digits) < 2 or digits[-1] == digits[-2]:
        return None
    swapped = int(digits[:-2] + digits[-1] + digits[-2])
    swapped = -swapped if number < 0 else swapped
    return swapped if swapped != number else None


def sum_text(parts, signs, hide=None):
    """'47 + 38 - 9'; the part at index `hide`, if any, is shown as '?'."""
    text = ""
    for i, (sign, part) in enumerate(zip(signs, parts)):
        shown = "?" if i == hide else str(part)
        text += shown if i == 0 else " {} {}".format("+" if sign > 0 else "−", shown)
    return text


def make_problem(game, level, rng, diff=EASY):
    """One problem for a player who has `level` correct answers, at difficulty `diff`.

    In the usual form `expr` is the sum without its answer ("47 + 38") and `answer` what
    it comes to. In the missing form `expr` is the whole statement with one number
    blanked ("? + 38 = 85") and `answer` is the number that goes in the blank."""
    index, tier = play_tier(game, level, diff)
    kind = GAMES[game]["kind"]
    missing = DIFFICULTY[diff]["form"] == "missing"

    def done(parts, signs, answer, expr):
        return {"kind": kind, "form": "missing" if missing else "result", "parts": parts,
                "signs": signs, "answer": answer, "expr": expr}

    if kind == "mul":
        a, b = rng.randint(*tier["a"]), rng.randint(*tier["b"])
        if rng.random() < 0.5:
            a, b = b, a
        if missing:
            hide = rng.randrange(2)
            shown = ["?" if hide == i else str(n) for i, n in enumerate((a, b))]
            return done([a, b], [1, 1], (a, b)[hide],
                        "{} × {} = {}".format(shown[0], shown[1], a * b))
        return done([a, b], [1, 1], a * b, "{} × {}".format(a, b))

    if kind == "div":
        divisor, quotient = rng.randint(*tier["d"]), rng.randint(*tier["q"])
        dividend = divisor * quotient
        if missing:
            if rng.random() < 0.5:          # the divisor is the blank: 84 ÷ ? = 12
                return done([dividend, divisor], [1, 1], divisor,
                            "{} ÷ ? = {}".format(dividend, quotient))
            return done([dividend, divisor], [1, 1], dividend,       # ? ÷ 7 = 12
                        "? ÷ {} = {}".format(divisor, quotient))
        return done([dividend, divisor], [1, 1], quotient, "{} ÷ {}".format(dividend, divisor))

    if kind == "avg":
        count = tier["terms"]
        mean = rng.randint(*tier["mean"])
        spread = tier["spread"]
        parts = [mean] * count               # the fallback: dull, but always valid
        for _ in range(40):
            # pick all but one number freely and let the last one make the total come out
            # exact, so the average is always a whole number
            head = [mean + rng.randint(-spread, spread) for _ in range(count - 1)]
            last = mean * count - sum(head)
            if min(head) >= 1 and 1 <= last <= mean + 2 * spread:
                parts = head + [last]
                break
        rng.shuffle(parts)
        names = ", ".join(str(n) for n in parts)
        if missing:
            hide = rng.randrange(count)
            names = ", ".join("?" if i == hide else str(n) for i, n in enumerate(parts))
            return done(parts, [1] * count, parts[hide],
                        "{} = {}".format(names, mean))
        return done(parts, [1] * count, mean, names)

    count = tier["terms"]
    # Negatives only where the tier allows them, and never in a blank: a missing number
    # that is itself negative is a puzzle about signs, not about arithmetic.
    allow_neg = bool(tier.get("neg")) and not missing
    if kind == "add":
        parts = [rng.randint(tier["lo"], tier["hi"]) for _ in range(count)]
        signs = [1] * count
    else:
        for _ in range(40):
            parts = [rng.randint(tier["lo"], tier["hi"]) for _ in range(count)]
            if count == 2:
                # Where negatives are allowed, half the questions still come out
                # positive, so a negative answer is a surprise, not the rule.
                if not allow_neg or rng.random() < 0.5:
                    parts.sort(reverse=True)
                signs = [1, -1]
            else:
                signs = [1] + [rng.choice((1, -1)) for _ in parts[1:]]
                if -1 not in signs:
                    signs[-1] = -1
            total = sum(s * p for s, p in zip(signs, parts))
            # A zero answer is a freebie; a negative one is only for tiers that allow it.
            if total != 0 and (total > 0 or allow_neg):
                break

    total = sum(s * p for s, p in zip(signs, parts))
    if missing:
        hide = rng.randrange(count)
        return done(parts, signs, parts[hide],
                    "{} = {}".format(sum_text(parts, signs, hide), fmt(total)))
    return done(parts, signs, total, sum_text(parts, signs))


def build_options(problem, index, tier, rng):
    """The right answer and its near misses, shuffled. Always `tier['options']` long.

    A wrong answer differs from the right one in exactly ONE digit, and only a little:
    the tens digit (the units digit, for a one-digit answer). 376 sits beside 366, 386
    and 356 -- never 276 or 476, which a player could rule out by rounding the sum. The
    last digit is the answer's own, so it gives nothing away, and the digits in front are
    its own too, so the only way to choose is to work the tens out. Nothing is more than
    three steps away, and a step is never a carry into the next digit.

    The wrong answers are drawn at random from the nearest few, not always the two
    either side, so the right one is not always the middle number. `index` is kept for
    the call sites; every level plays by the same rule."""
    answer = problem["answer"]
    count = tier["options"]
    may_go_negative = (problem["kind"] == "sub" and bool(tier.get("neg"))
                       and problem.get("form") != "missing")
    size, sign = abs(answer), (-1 if answer < 0 else 1)
    unit = 1 if size < 10 else 10                  # the digit that moves

    def digits(n):
        return len(str(abs(n)))

    candidates = []
    for k in range(-9, 10):
        if k == 0:
            continue
        moved = (size // unit) % 10 + k            # that digit, after the move
        if not 0 <= moved <= 9:                    # a carry would change a second digit
            continue
        candidate = sign * (size + unit * k)
        if digits(candidate) != digits(answer):    # 17 -> 07 is a different sort of number
            continue
        if candidate < 0 and not may_go_negative:
            continue
        if answer < 0 and candidate >= 0:          # -1 beside 0: a near miss keeps its sign
            continue
        candidates.append((abs(k), candidate))
    if may_go_negative and size >= 10:
        candidates.append((2, -answer))            # the sign slip: -376 beside 376

    rng.shuffle(candidates)                        # ties in random order...
    candidates.sort(key=lambda item: item[0])      # ...the nearest first
    wanted = count - 1
    close = [c for k, c in candidates if k <= 3]   # three steps at most, where there are enough
    window = (close if len(close) >= wanted else [c for _, c in candidates])[:wanted + 2]
    wrong = rng.sample(window, min(wanted, len(window)))
    for _, candidate in candidates:                # a short list: take the next nearest
        if len(wrong) >= wanted:
            break
        if candidate not in wrong:
            wrong.append(candidate)
    reach = 1
    while len(wrong) < wanted:                     # cannot happen; never return a short list
        for candidate in (answer + reach, answer - reach):
            if len(wrong) < wanted and candidate != answer and candidate not in wrong \
                    and (candidate >= 0 or may_go_negative):
                wrong.append(candidate)
        reach += 1

    options = wrong + [answer]
    rng.shuffle(options)
    return options


def parse_action(value):
    """'<game>|<owner>|<step>|<number | start | again | daily | try | play | difficulty |
    join[:difficulty]>' -> (game, owner, step, choice), or None. A difficulty is the
    dropdown's option; join is the Play button on a record post."""
    parts = str(value or "").split("|")
    if len(parts) != 4 or parts[0] not in GAMES:
        return None
    try:
        words = ("start", "again", "daily", "try", "play") + tuple(DIFFICULTY)
        joins = ("join",) + tuple("join:" + d for d in DIFFICULTY)
        choice = parts[3] if parts[3] in words + joins else int(parts[3])
        return parts[0], parts[1], int(parts[2]), choice
    except ValueError:
        return None


def action_value(game, owner, step, choice):
    return "{}|{}|{}|{}".format(game, owner, step, choice)


def daily_rng(game, day, step):
    """The same generator for every player of this game on the same day and step."""
    return random.Random("{}:{}:{}".format(game, day, step))


def share_line(state):
    """The copy-and-paste result: green right, yellow shield-saved, red out."""
    trail = state.get("trail") or ""
    squares = "".join(SQUARES[c] for c in trail[-SHARE_MAX:])
    if len(trail) > SHARE_MAX:
        squares = "…" + squares
    return "{} Daily {} · {} correct · {}\n{}".format(
        GAMES[state["game"]]["name"], state.get("daily") or "",
        state.get("score", 0), seconds_text(state.get("secs")), squares)


# --------------------------------------------------------------------------
# PURE -- Block Kit
# --------------------------------------------------------------------------

def _header(state):
    game = GAMES[state["game"]]
    parts = ["{} *{}*{}".format(game["icon"], game["name"],
                                " Daily" if state.get("daily") else "")]
    if difficulty_label(state):
        parts.append(difficulty_label(state))
    parts += ["Level {}".format(state.get("level", 1)), "Score {}".format(state["score"])]
    if state.get("shields"):
        parts.append(":shield: Shield ready")
    note = target_text(state)
    if note:
        parts.append(note)
    return _context("  ·  ".join(parts))


def difficulty_picker(state, owner):
    """The difficulty dropdown, with just its label on the left.

    A section with an accessory, not part of the Start button's actions block: a press
    on Start then still arrives alone, and picking from the list is its own event
    (action_id imath_difficulty) that redraws this card. Its block_id is fixed so Slack's
    state.values has a stable path to the choice. The label says nothing about the level
    chosen: the dropdown shows that, and a line of text beside it would only go stale."""
    diff = difficulty_of(state)
    options = [{"text": {"type": "plain_text", "text": DIFFICULTY[name]["label"]},
                "description": {"type": "plain_text", "text": example_question(state["game"], name)},
                "value": action_value(state["game"], owner, 0, name)}
               for name in DIFFICULTY]
    return {"type": "section", "block_id": "imath_difficulty",
            "text": {"type": "mrkdwn", "text": "*Difficulty*"},
            "accessory": {"type": "static_select", "action_id": "imath_difficulty",
                          "placeholder": {"type": "plain_text", "text": "Difficulty"},
                          "initial_option": options[list(DIFFICULTY).index(diff)],
                          "options": options}}


def intro_blocks(state, owner):
    """The rules, what to beat, the difficulty and a Start button. Nothing is timed until
    Start is pressed.

    Everything must be on screen at once: Slack folds a long section behind "Show more",
    and what hides there is the targets. So the rules are three short lines, the targets
    are a section of their own, and nothing here runs past a few lines."""
    game = GAMES[state["game"]]
    daily = bool(state.get("daily"))
    rules = [
        "Tap the right answer before its clock runs out.",
        "Each correct answer makes the next one harder.",
        "A wrong answer ends it. Every *{}* correct earns a :shield: shield that forgives "
        "one miss.".format(SHIELD_EVERY),
    ]
    title = "{} *{}*{}".format(game["icon"], game["name"], " Daily" if daily else "")
    if state.get("test"):
        title += "  \u00b7  :test_tube: Test game: nothing is saved or posted"
    blocks = [
        _context(title),
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join("• " + r for r in rules)}},
    ]
    if daily:                      # today's set is the same for everyone: one difficulty
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
                       ":calendar: *Same set for everyone, one attempt.* It counts from the "
                       "moment you press Start."}})
    else:
        targets = target_intro(state)
        if targets:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": targets}})
        blocks.append(difficulty_picker(state, owner))
    blocks.append(
        {"type": "actions", "block_id": "imath_intro", "elements": [
            {"type": "button", "action_id": "imath_start", "style": "primary",
             "text": {"type": "plain_text", "text": "Start game"},
             "value": action_value(state["game"], owner, 0, "start")},
        ]})
    return blocks


def clock_blocks(remaining, notice=""):
    """The clock, and the one-line note (Correct, Level up, Shield) that rides on it.

    It is a message of its own, below the question. The countdown rewrites it every
    second, and a click replaces the question: were both the same message, a countdown
    tick that had already read the table could land after the next question and put the
    old one back, buttons and all. Kept apart, a late tick can only ever be a wrong
    number on the clock."""
    text = ":stopwatch: *{}s*".format(remaining)
    if notice:
        text += "   ·   " + notice
    return [_context(text)]


def question_blocks(state, owner):
    """The problem as a heading and the answers as buttons. The clock is not in it: see
    clock_blocks."""
    buttons = [
        {"type": "button", "action_id": "imath_opt_{}".format(i),
         "text": {"type": "plain_text", "text": fmt(value)},
         "value": action_value(state["game"], owner, state["step"], value)}
        for i, value in enumerate(state["options"], 1)]
    blocks = [_header(state)]
    prompt = question_prompt(state)
    if prompt:
        blocks.append(_context(prompt))
    return blocks + [
        {"type": "header", "text": {"type": "plain_text",
                                    "text": question_text(state), "emoji": True}},
        {"type": "actions", "block_id": "imath_q{}".format(state["step"]),
         "elements": buttons},
    ]


def play_again_actions(game, owner, step, daily_open):
    """Play again, and today's daily while it is still unplayed."""
    elements = [{"type": "button", "action_id": "imath_again", "style": "primary",
                 "text": {"type": "plain_text", "text": "Play again"},
                 "value": action_value(game, owner, step, "again")}]
    if daily_open:
        elements.append({"type": "button", "action_id": "imath_daily",
                         "text": {"type": "plain_text", "text": "Today's daily"},
                         "value": action_value(game, owner, step, "daily")})
    return {"type": "actions", "block_id": "imath_over", "elements": elements}


def over_blocks(state, best_score, best_secs, new_best, shared=False,
                daily_open=True, buttons=True):
    """The closing card: the sum and its answer, then the numbers.

    Kept short on purpose. It is read in a narrow thread pane, where every extra
    block adds a gap and a two-column grid collapses into a tall stack, so the body
    is ONE block and the numbers are ONE line.

    `buttons=False` is the same card after the player has moved on: the result
    stays, the buttons go.
    """
    game = GAMES[state["game"]]
    right = fmt(state["answer"])
    if state.get("form") == "missing":
        the_sum = "`{}`  →  *{}*".format(state["expr"], right)
    else:
        the_sum = "`{}`  =  *{}*".format(state["expr"], right)
    if state.get("choice") is None:
        headline = ":hourglass: *Time's up*"
    else:
        headline = ":x: *Game over*"
        the_sum += "     you chose *{}*".format(fmt(state["choice"]))

    stats = ["*Score* {}".format(state["score"]), "*Level* {}".format(state.get("level", 1)),
             "*Time* {}".format(seconds_text(state["secs"]))]
    # Buttons need the owner's id (they carry it); a game with none stored falls
    # back to the typed instruction.
    owner = state.get("owner")
    keyword = state["game"]
    if state.get("daily"):
        footer = [{"type": "section", "text": {"type": "mrkdwn", "text":
                   "*Share your result*\n```{}```".format(share_line(state))}},
                  _context(("Posted to the channel.  " if shared else "") +
                           "Everyone gets the same set today. A new one tomorrow.")]
        daily_open = False                      # the day's attempt is spent
    else:
        if new_best:
            stats.append(":trophy: *New personal best*")
        elif best_score:
            stats.append("*Best* {} in {}".format(best_score, seconds_text(best_secs)))
        else:
            stats.append("*Best* get one right to set one")
        footer = [_context(":tada: Shared with the channel.")] if shared else []

    if state.get("test"):
        footer.append(_context(":test_tube: Test game: this result was not saved."))
    if not buttons:
        footer.append(_context(":arrow_forward: A new game has started."))
    elif owner:
        footer.append(play_again_actions(state["game"], owner, state["step"], daily_open))
    else:
        footer.append(_context("Type `{}` to play again, or `{} daily` for today's shared set.".format(
            keyword, keyword)))
    return [
        _context("{} *{}*{}  \u00b7  {}Round {}".format(
            game["icon"], game["name"], " Daily" if state.get("daily") else "",
            difficulty_label(state) + "  \u00b7  " if difficulty_label(state) else "",
            state["step"])),
        {"type": "section", "text": {"type": "mrkdwn", "text": headline + "\n\n" + the_sum}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "   \u00b7   ".join(stats)}},
    ] + footer


def already_played_blocks(game, day, row):
    done = (row or {}).get("status") == DAILY_DONE
    text = ":brain: *{} Daily*  —  you have already played today's set ({}).".format(
        GAMES[game]["name"], day)
    if done:
        text += "\n```{}```".format((row or {}).get("content") or "")
    else:
        text += "\nThat attempt was started and not finished, so it counts. A new set tomorrow."
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def daily_ended_blocks(game):
    return [_context(":brain: This daily set has ended. Type `{} daily` for today's.".format(game))]


def expired_blocks(game):
    return [_context(":brain: This {} game has ended. Type `{}` to start a new one.".format(
        GAMES[game]["name"], game))]


def record_blocks(game, owner, rec, banner=""):
    channel = rec["kind"] == "channel"
    name = game_title(game, rec.get("diff") or EASY)
    prev_score, prev_secs = rec["previous"]
    title = ":crown:  *New channel record*" if channel else ":trophy:  *New personal best*"
    detail = ("<@{}> scored *{}* in *{}* — reaching *Level {}*, in *{}* of thinking time."
              ).format(owner, rec["score"], name, rec.get("level", 1), seconds_text(rec["secs"]))
    detail += "\nPrevious {} *{}* in {} — {}.".format(
        "record" if channel else "best", prev_score, seconds_text(prev_secs),
        margin_text(rec["score"], rec["secs"], prev_score, prev_secs))

    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": title}},
              {"type": "section", "text": {"type": "mrkdwn", "text": detail}}]
    notes = []
    if channel:
        if rec["holder_id"] == owner:
            notes.append("Their own record until now.")
        elif rec["holder_name"]:
            notes.append("Held by {} until now.".format(rec["holder_name"]))
        notes.append("{} people play {}.".format(rec["people"], name))
    if notes:
        blocks.append(_context(" ".join(notes)))
    blocks.append({"type": "actions", "block_id": "imath_record_join",
                   "elements": [play_button(game, rec.get("diff") or EASY)]})
    if channel and banner:
        ref = str(banner).strip()
        image = ({"type": "image", "image_url": ref, "alt_text": RECORD_BANNER_ALT}
                 if ref.startswith(("http://", "https://"))
                 else {"type": "image", "slack_file": {"id": ref},
                       "alt_text": RECORD_BANNER_ALT})
        blocks.insert(0, image)
    return blocks


def play_button(game, diff=EASY):
    """The Play button under a record post. ANYONE may press it, so its value names no
    one: the presser is who plays, at the difficulty the record was set on.

    Its action_id is the rules card's Start button's, on purpose (as iMemory's): the click
    recipe already lets that one through, so this needs no change to the trigger."""
    return {"type": "button", "action_id": "imath_start", "style": "primary",
            "text": {"type": "plain_text", "text": "Play " + game_title(game, diff)},
            "value": action_value(game, "anyone", 0, "join:" + diff)}


def record_summary(game, owner, rec):
    return "<@{}> set a new {} in {}".format(
        owner, "channel record" if rec["kind"] == "channel" else "personal best",
        game_title(game, rec.get("diff") or EASY))

# --------------------------------------------------------------------------
# Plumbing shared with iMemory (copied from imemory.py unchanged)
# --------------------------------------------------------------------------

def should_process(event):
    """Whether a Slack event deserves any work. Returns (ok, reason).

    The bot's own messages mention `imemory` ("type imemory to play again"),
    so without the bot guards it would start a game for itself.
    """
    if event.get("bot_id"):
        return False, "bot message"
    subtype = (event.get("subtype") or "").strip().lower()
    if subtype in SKIP_SUBTYPES:
        return False, "subtype " + subtype
    user_id = (event.get("user_id") or "").strip()
    if not user_id:
        return False, "no user id"
    if user_id == (event.get("bot_user_id") or "").strip():
        return False, "our own message"
    return True, ""


def seconds_text(seconds):
    return "{:.1f}s".format(float(seconds or 0))


def is_better(score, secs, best_score, best_secs):
    """A run beats the record on a higher score, or equal score and less time."""
    if best_score is None:
        return True
    if score != best_score:
        return score > best_score
    return secs < best_secs


def best_of(row, score, secs):
    """(best_score, best_secs, is_new_best) after this run, given the old row.

    A record needs at least one correct answer: with no row to beat, a run of
    zero would otherwise win by default. Among real runs the higher score wins,
    and at an equal score the lower time does.
    """
    old_score, old_secs = None, 0.0
    if row:
        old_score = int(row.get("personal_best_single_set") or 0) or None
        if old_score:
            try:
                old_secs = float(row.get("total") or 0)
            except (TypeError, ValueError):
                old_secs = 0.0
    if score > 0 and is_better(score, secs, old_score, old_secs):
        return score, secs, True
    return old_score or 0, old_secs if old_score else 0.0, False


def load_state(row):
    try:
        state = json.loads((row or {}).get("content") or "{}")
    except (TypeError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def local_today(tz_offset, now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    return (now + timedelta(seconds=tz_offset)).date()


def records_broken(own_row, board, owner, score, secs):
    """Which record a finished free game set, or None. Mirrors spotter's rules.

    `board` is every player's row as it stood BEFORE this game was saved, and
    `own_row` this player's. A record is a higher score, or the same score in
    less time (is_better).

      * Nothing under a score of 0.
      * A first scored game beats no personal best -- there was nothing to beat.
      * A channel record needs somebody to beat, so it is withheld while this is
        the only person who has ever played.
      * A channel record outranks a personal best; announcing both would say the
        same thing twice.
    """
    if score <= 0:
        return None

    def mark(row):
        try:
            return int(row.get("personal_best_single_set") or 0), float(row.get("total") or 0)
        except (TypeError, ValueError):
            return 0, 0.0

    own_score, own_secs = mark(own_row or {})
    others = [r for r in board if r.get("id") != owner and mark(r)[0] > 0]
    people = len(others) + 1

    # The standing best across everyone, this player's old best included.
    field = [(mark(r), r.get("name") or "", r.get("id") or "") for r in others]
    if own_score:
        field.append(((own_score, own_secs), (own_row or {}).get("name") or "", owner))
    holder = None
    for (best_score, best_secs), name, uid in field:
        if holder is None or is_better(best_score, best_secs, holder[0], holder[1]):
            holder = (best_score, best_secs, name, uid)

    personal = bool(own_score) and is_better(score, secs, own_score, own_secs)
    channel = people >= 2 and holder is not None \
        and is_better(score, secs, holder[0], holder[1])
    if not (personal or channel):
        return None
    return {
        "kind": "channel" if channel else "personal",
        "score": score, "secs": secs, "people": people,
        "previous": (holder[0], holder[1]) if channel else (own_score, own_secs),
        "holder_id": holder[3] if channel else owner,
        "holder_name": holder[2] if channel else "",
    }


def margin_text(score, secs, prev_score, prev_secs):
    """How far past the previous mark: more answers, or the same score faster."""
    if score > prev_score:
        gain = score - prev_score
        return "beaten by {} more correct answer{}".format(gain, "" if gain == 1 else "s")
    return "same score, {} faster".format(seconds_text(prev_secs - secs))


def divided(blocks):
    """The blocks of a game's message, with a horizontal line on top.

    Used only for a game that was started FROM A RESULT CARD (Play again, Today's
    daily), which lands in the same thread right under the card it follows. Every
    screen of such a game goes through this -- the message is edited in place, so a line
    only on its first screen would be gone a second later. A game that opens a thread
    (a typed keyword, or a joiner's own thread) has nothing above it and gets no line.
    """
    blocks = list(blocks)
    return blocks if blocks and blocks[0].get("type") == "divider" else [{"type": "divider"}] + blocks


def channel_best_of(board, owner):
    """The best score among everyone ELSE: {"score", "name"}, or {} when nobody else has one.

    The player's own best is their personal target; this is what lies beyond it. When the
    player already holds the top spot there is nobody to chase, which is also correct:
    passing their own best is then a channel record.
    """
    best = None
    for row in board:
        if row.get("id") == owner:
            continue
        try:
            score, secs = int(row.get("personal_best_single_set") or 0), float(row.get("total") or 0)
        except (TypeError, ValueError):
            continue
        if score > 0 and (best is None or is_better(score, secs, best[0], best[1])):
            best = (score, secs, row.get("name") or "")
    return {"score": best[0], "name": best[2]} if best else {}


def next_above(board, owner, best):
    """The player just above `best` on the board: {"score", "name"}, or {} when there is
    nobody (or the player has no best yet: then the only target is the channel's).

    "Just above" is the lowest score over `best`; among equal scores, the slower run,
    which is the one standing directly over the player on the leaderboard."""
    if not best:
        return {}
    nearest = None
    for row in board:
        if row.get("id") == owner:
            continue
        try:
            score, secs = int(row.get("personal_best_single_set") or 0), float(row.get("total") or 0)
        except (TypeError, ValueError):
            continue
        if score > best and (nearest is None or (score, -secs) < (nearest[0], -nearest[1])):
            nearest = (score, secs, row.get("name") or "")
    return {"score": nearest[0], "name": nearest[2]} if nearest else {}


def rival_targets(table, user_row_type, owner, best, warnings):
    """(next, channel): the person just above the player's best, and the channel's best.

    Read once when a game starts. Both are {} if unreadable or there is nobody. When the
    next person IS the channel best (one rung, not two) only the channel best is kept."""
    board = table.board(user_row_type)
    if board is LOOKUP_FAILED:
        warnings.append("channel best unreadable; no rival targets shown")
        return {}, {}
    chan = channel_best_of(board, owner)
    nxt = next_above(board, owner, best)
    if nxt and chan and nxt["score"] >= chan["score"]:
        nxt = {}
    return nxt, chan


def target_text(state):
    """What to beat right now: your own best, then the person above you, then the
    channel's, then nothing left.

    Worked out from the score every time a screen is drawn, so the target moves on by
    itself the moment the one before it is passed. A daily has no targets: it is the
    same set for everyone, one attempt.
    """
    if state.get("daily"):
        return ""
    score, best = int(state.get("score") or 0), int(state.get("best") or 0)
    nxt = state.get("next") or {}
    near = int(nxt.get("score") or 0)
    chan = state.get("chan") or {}
    ahead = int(chan.get("score") or 0)
    if best and score <= best:
        return "{} to beat your best ({})".format(best + 1 - score, best)
    if near and score <= near:
        return ":dart: {} to beat {} ({})".format(near + 1 - score, nxt.get("name") or "?", near)
    if ahead and score <= ahead:
        return ":crown: {} to beat the channel best ({} by {})".format(
            ahead + 1 - score, ahead, chan.get("name") or "?")
    if ahead:
        return ":crown: ahead of the channel best ({})".format(ahead)
    if best:
        return ":trophy: above your best ({})".format(best)
    return ""


def target_intro(state):
    """The same ladder, as lines for the rules card: your best, who is next, the channel's."""
    best = int(state.get("best") or 0)
    nxt, chan = state.get("next") or {}, state.get("chan") or {}
    label = difficulty_label(state)
    lines = []
    if best:
        lines.append(":trophy: Your best{}: *{}*".format(" on " + label if label else "", best))
    if nxt.get("score"):
        lines.append(":dart: Next to beat: *{}* with *{}*".format(nxt.get("name") or "?", nxt["score"]))
    if chan.get("score"):
        lines.append(":crown: Channel best: *{}* by *{}*".format(chan["score"], chan.get("name") or "?"))
    return "\n".join(lines)


def crossed(state):
    """(passed your best, passed the channel best) -- True only on the answer that does it."""
    if state.get("daily"):
        return False, False
    score, best = int(state.get("score") or 0), int(state.get("best") or 0)
    ahead = int((state.get("chan") or {}).get("score") or 0)
    return bool(best) and score == best + 1, bool(ahead) and score == ahead + 1


def passed_next(state):
    """True only on the answer that takes the player past the person just above their best."""
    if state.get("daily"):
        return False
    near = int((state.get("next") or {}).get("score") or 0)
    return bool(near) and int(state.get("score") or 0) == near + 1


def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def is_duplicate(session, message_ts):
    """Whether this message was already claimed by a game that actually ran.

    A row still "starting" a minute after its claim belongs to a run that died
    before posting anything; the message deserves another go, not a skip.
    """
    if str(session.get("last_processed_ts") or "") != message_ts:
        return False
    if session.get("status") != SESSION_STARTING:
        return True
    started = float(load_state(session).get("started") or 0)
    return (_now() - started) < STARTING_STALE_SECONDS


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0

# --------------------------------------------------------------------------
# Weekly challenges (weekly_challenge/weekly_challenge.py posts them; this game settles the ones
# about itself). A player who presses Accept on "Play iAdd 5 times" or "Reach 15 in iAdd" gets an
# entry in the `content` column of their EASY player row (math_add_user), and the first free Easy
# game that clears it says so. Both the entry and the news are written with the game's own save,
# so nothing is said twice. Daily games, test games and the harder difficulties do not count: a
# score on Very hard and one on Easy are not the same achievement, and each difficulty has a row
# of its own.
# --------------------------------------------------------------------------

WEEKLY_ACCEPT_ROW = "weekly_accept"


def as_date(value):
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def and_join(names):
    """'a', 'a and b', 'a, b and c'."""
    names = list(names)
    if len(names) < 3:
        return " and ".join(names)
    return "{} and {}".format(", ".join(names[:-1]), names[-1])


# >>> weekly challenge entries
# KEEP THIS SECTION, down to the matching "<<<", IDENTICAL in spotter/spotter.py,
# weekly_challenge/weekly_challenge.py, imath/imath.py and imemory/imemory.py (a Workato step is
# one file, so it is copied, and a test fails if the copies drift). It needs `json`, `timedelta`,
# `as_date` and `and_join` from the file it sits in. weekly_challenge.py writes an entry into a
# person's row when they press Accept on a challenge for the week; spotter settles an activity's
# on their later logs, and the games settle theirs when a game ends, each saying so when one is
# cleared -- with a bigger post (weekly_final_blocks) when it was the last of their week.
#
# The entries live in `content`, a long text column no activity row uses for anything else, as
# one json object. Any other key in that object is left exactly as it was found, and a column
# that holds something that is not a json object is left alone altogether.
#
#     {"wc": [{"post": "2026-10-19-1792400000", "from": "2026-10-19", "to": "2026-10-25",
#              "goal": 100, "text": "100 pushups", "base": 576, "state": "open"}],
#      "wc_counts": {"accepted": 7, "cleared": 5}}
#
#   kind   absent for an activity (a running total: below), or one of the two game kinds:
#            plays   "play the game N times": base is the row's games-played count (total_planks)
#                    at the moment they accepted, and a finished free game inside the week
#                    that takes the count N past it clears it
#            score   "reach a score of N": cleared by one finished free game inside the week
#                    that scores N or more (base is 0; nothing before counts)
#   base   the person's running total of the activity at the moment they accepted. What they
#          have done towards the goal is their running total now, less this: the table keeps
#          no date against a session, so a total at a moment is what can be compared later.
#   state  open, then done (with "done": the day it was cleared) or missed. Only an open
#          entry is ever looked at again.
#   wc_counts  how many weekly challenges this row has taken on, and cleared, EVER. Kept
#          apart from the entries because those are cut to the newest WEEKLY_KEEP. It goes up
#          by one in the same write that adds an entry (accepted) or marks one done (cleared),
#          so it cannot disagree with them. A person's total is the sum over their rows.
WEEKLY_COLUMN = "content"
WEEKLY_KEY = "wc"
WEEKLY_COUNTS_KEY = "wc_counts"
WEEKLY_KEEP = 12
WEEKLY_GAME_KINDS = ("plays", "score")


def weekly_document(raw):
    """The json object held in the column: {} when it is empty, None when it holds anything
    else (which is then never overwritten)."""
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def weekly_entries(raw):
    """The weekly entries in the column, oldest first. One that cannot be read is skipped."""
    out = []
    for entry in (weekly_document(raw) or {}).get(WEEKLY_KEY) or []:
        try:
            if (isinstance(entry, dict) and entry["post"] and as_date(entry["from"])
                    and as_date(entry["to"]) and int(entry["goal"]) > 0
                    and int(entry["base"]) >= 0):
                out.append(entry)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def weekly_entry_from(raw):
    """One entry held on its own as json (as a weekly_accept row holds it), or None."""
    try:
        found = weekly_entries(json.dumps({WEEKLY_KEY: [json.loads(raw or "")]}))
    except ValueError:
        return None
    return found[0] if found else None


def weekly_counts(raw):
    """(accepted, cleared): how many weekly challenges the row has taken on and cleared, ever."""
    counts = (weekly_document(raw) or {}).get(WEEKLY_COUNTS_KEY)
    counts = counts if isinstance(counts, dict) else {}

    def number(name):
        try:
            return max(0, int(counts.get(name) or 0))
        except (TypeError, ValueError):
            return 0
    return number("accepted"), number("cleared")


def weekly_text(raw, entries, accepted_add=0, cleared_add=0):
    """What the column should hold once its weekly entries are `entries` and its counts have
    gone up by the amounts given; None when it holds something that is not a json object,
    which must not be overwritten."""
    document = weekly_document(raw)
    if document is None:
        return None
    document[WEEKLY_KEY] = list(entries)[-WEEKLY_KEEP:]
    accepted, cleared = weekly_counts(raw)
    accepted, cleared = accepted + accepted_add, cleared + cleared_add
    if accepted or cleared:
        document[WEEKLY_COUNTS_KEY] = {"accepted": accepted, "cleared": cleared}
    return json.dumps(document, separators=(",", ":"))


def weekly_entry(post_id, monday, goal, text, base, kind=""):
    """A new, open entry for a goal accepted when the person's running total was `base`."""
    entry = {"post": post_id, "from": monday.isoformat(),
             "to": (monday + timedelta(days=6)).isoformat(), "goal": int(goal),
             "text": text, "base": int(base), "state": "open"}
    if kind in WEEKLY_GAME_KINDS:
        entry["kind"] = kind
    return entry


def weekly_got(entry, total_now):
    """What the person has done towards the goal: their running total now, less the total they
    had when they accepted."""
    return max(0, int(total_now) - int(entry["base"]))


def weekly_progress(entry, before_total, logs):
    """What the person has done towards the goal once the message being logged is counted.
    `before_total` is their running total before it and `logs` is the message as
    [(day, amount)]. Its amounts count only for days inside the entry's week, so a catch-up for
    a day last week does not count towards this week's goal."""
    start, end = as_date(entry["from"]), as_date(entry["to"])
    inside = sum(amount for day, amount in logs if start <= day <= end)
    return weekly_got(entry, before_total) + inside


def weekly_settle(entry, before_total, logs, today):
    """Where an open entry stands after a log: (entry, cleared).

    A message that arrives after the week has ended can still clear the goal with days from
    inside the week; when it cannot, the entry is closed as missed.
    """
    if entry.get("state") != "open" or entry.get("kind") in WEEKLY_GAME_KINDS:
        return entry, False
    if weekly_progress(entry, before_total, logs) >= int(entry["goal"]):
        return dict(entry, state="done", done=today.isoformat()), True
    if today > as_date(entry["to"]):
        return dict(entry, state="missed"), False
    return entry, False
def weekly_game_settle(entry, score, plays_now, today):
    """Where an open game entry stands after a finished free game: (entry, cleared).

    `score` is that game's score and `plays_now` the row's games-played count with it counted.
    Only a game finished inside the entry's week counts; the first one after the week closes
    the entry as missed."""
    if entry.get("state") != "open" or entry.get("kind") not in WEEKLY_GAME_KINDS:
        return entry, False
    start, end = as_date(entry["from"]), as_date(entry["to"])
    if start <= today <= end:
        if entry["kind"] == "plays":
            reached = weekly_got(entry, plays_now) >= int(entry["goal"])
        else:
            reached = int(score) >= int(entry["goal"])
        if reached:
            return dict(entry, state="done", done=today.isoformat()), True
        return entry, False
    if today > end:
        return dict(entry, state="missed"), False
    return entry, False


def weekly_game_update(raw, waiting, score, plays_now, today):
    """Set a game row's weekly entries against the free game that has just finished.

    `waiting` are entries accepted before the row existed. Returns (text, cleared): the
    column's new content when anything changed (else None) and the entries this game cleared.
    The caller adds `text` to the write that saves the game, so the news and the mark are one
    write and cannot be said twice."""
    mine = weekly_entries(raw)
    known = {entry["post"] for entry in mine}
    added = [entry for entry in waiting if entry["post"] not in known]
    settled, cleared, changed = [], [], bool(added)
    for entry in mine + added:
        new, done = weekly_game_settle(entry, score, plays_now, today)
        changed = changed or new is not entry
        settled.append(new)
        if done:
            cleared.append(new)
    if not changed:
        return None, []
    text = weekly_text(raw, settled, len(added), len(cleared))
    return (text, cleared) if text is not None else (None, [])


def weekly_place(value):
    """Where a cleared weekly challenge is told, from the announce_weekly input: "channel" (the
    default), "thread" (a reply under the log or game that cleared it) or "" for nowhere.
    Settings from when it was only on or off still mean what they did: true / yes / on is the
    channel, false / no / off is nowhere."""
    text = str(value if value is not None else "").strip().lower()
    if text in ("thread", "reply", "in thread", "in the thread"):
        return "thread"
    if text in ("false", "0", "no", "off", "none", "never", "nowhere"):
        return ""
    return "channel"


def weekly_dates(entry):
    """'Mon 12 Oct \u2013 Sun 18 Oct' for an entry's week."""
    first, last = as_date(entry.get("from")), as_date(entry.get("to"))
    if not (first and last):
        return ""
    return "{} {} {} \u2013 {} {} {}".format(
        first.strftime("%a"), first.day, first.strftime("%b"),
        last.strftime("%a"), last.day, last.strftime("%b"))


def weekly_cleared_text(user_id, entries):
    return "<@{}> cleared the weekly challenge: {}".format(
        user_id, and_join(e.get("text") or "the goal" for e in entries))


def weekly_cleared_blocks(user_id, entries, cleared_total=0):
    """The post for a weekly challenge cleared -- or several, when one message cleared them.
    Short: the challenge is the news. From a second one on it says how many they have cleared
    so far."""
    goals = and_join("*{}*".format(e.get("text") or "the goal") for e in entries)
    lead = ("<@{}> cleared the weekly challenge: {}. Congratulations!" if len(entries) == 1
            else "<@{}> cleared {} weekly challenges: {}. Congratulations!")
    detail = (lead.format(user_id, goals) if len(entries) == 1
              else lead.format(user_id, len(entries), goals))
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
               "text": ":tada:  *Weekly challenge cleared*"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": detail}}]
    bits = [weekly_dates(entries[0])]
    if cleared_total >= 2:
        bits.append("{} cleared so far".format(cleared_total))
    bits = [b for b in bits if b]
    if bits:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": ":calendar: " + "  \u00b7  ".join(bits)}]})
    return blocks


def weekly_all_done(rows, cleared, accepted, today):
    """Whether every weekly goal the person took on for the week in progress is cleared.

    `accepted` are the entries on their acceptance rows (weekly_challenge.py writes one per goal
    taken on, whether or not a row of theirs holds it too, and never changes it), or None when
    they could not be read; `rows` are their rows and `cleared` the entries just cleared, which
    the rows may not show yet. A goal is known by its post and its words, which every copy of it
    keeps."""
    if not accepted:
        return False
    done = {(e["post"], e.get("text")) for e in cleared or []}
    for row in rows or []:
        for entry in weekly_entries(row.get(WEEKLY_COLUMN)):
            if entry.get("state") == "done" and as_date(entry["to"]) >= today:
                done.add((entry["post"], entry.get("text")))
    return all((e["post"], e.get("text")) in done for e in accepted)


def weekly_week_goals(accepted):
    """The week's goals from the acceptance entries, once each, in the order taken on."""
    seen, goals = set(), []
    for entry in accepted or []:
        key = (entry["post"], entry.get("text"))
        if key not in seen:
            seen.add(key)
            goals.append(entry)
    return goals


def weekly_final_text(user_id, goals):
    return "<@{}> cleared every weekly challenge this week: {}".format(
        user_id, and_join(e.get("text") or "the goal" for e in goals))


def weekly_final_blocks(user_id, goals, cleared_total=0):
    """The post when a log or a game clears the last of somebody's goals for the week: bigger
    than the one for a single goal (weekly_cleared_blocks), with each goal of the week on a line
    of its own. `goals` are the week's goals, all of them done (weekly_week_goals)."""
    n = len(goals)
    blocks = [{"type": "header", "text": {"type": "plain_text", "emoji": True,
               "text": ":trophy:  Every weekly challenge cleared"}},
              {"type": "section", "text": {"type": "mrkdwn", "text":
               "<@{}> cleared every challenge they took on this week \u2014 *{} of {}*. "
               "Congratulations!".format(user_id, n, n)}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": "\n".join(
                  ":white_check_mark:  {}".format(e.get("text") or "the goal")
                  for e in goals)}]}]
    bits = [weekly_dates(goals[0])] if goals else []
    if cleared_total >= 2:
        bits.append("{} cleared so far".format(cleared_total))
    bits = [b for b in bits if b]
    if bits:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": ":calendar: " + "  \u00b7  ".join(bits)}]})
    return blocks
# <<< weekly challenge entries

# Every correct answer the player has given in this game and difficulty, over all their games:
# the leaderboard ranks on it. Kept in the same json as the weekly entries, under this key.
POINTS_KEY = "pts"


def points_text(raw, score, old_best=0):
    """What the column should hold once a game of `score` correct answers is counted.

    The running total goes up by the score. A player from before the tally was kept starts
    it from their old best score, the least they had earned (the leaderboard does the same).
    None when the column holds something that is not a json object, which must not be
    overwritten."""
    document = weekly_document(raw)
    if document is None:
        return None
    try:
        before = max(0, int(document.get(POINTS_KEY) or 0))
    except (TypeError, ValueError):
        before = 0
    document[POINTS_KEY] = max(before, int(old_best or 0)) + max(0, int(score))
    return json.dumps(document, separators=(",", ":"))


def weekly_apply(game, row, fields, score, day):
    """Set a finished free Easy game against the weekly challenges its player accepted.

    Adds `content` to `fields` (the write that saves the game) when anything changes, and
    returns the entries this game cleared. Never allowed to hold up the save itself."""
    keys = [game.key + "_plays", game.key + "_score"]
    try:
        waiting = [] if row else game.table.weekly_pending(game.owner, keys, day)
        text, cleared = weekly_game_update((row or {}).get(WEEKLY_COLUMN), waiting, score,
                                           int(fields["total_planks"]), day)
        if text is not None:
            fields[WEEKLY_COLUMN] = text
        return cleared
    except Exception as error:                                    # noqa: BLE001
        game.result["warnings"].append("weekly challenge: {}: {}".format(
            type(error).__name__, str(error)[:200]))
        return []


def weekly_post(game, cleared, day):
    """(text, blocks) for a weekly challenge a game has just cleared: the bigger post when it
    was the last of the player's goals for the week, the ordinary one otherwise -- including
    whenever that cannot be told, since saying less is the safe mistake."""
    try:
        week = game.table.weekly_week(game.owner, day)
        if week and weekly_all_done(week[0], cleared, week[1], day):
            goals = weekly_week_goals(week[1])
            so_far = sum(weekly_counts(row.get(WEEKLY_COLUMN))[1] for row in week[0])
            return (weekly_final_text(game.owner, goals),
                    weekly_final_blocks(game.owner, goals, so_far))
    except Exception as error:                                    # noqa: BLE001
        game.result["warnings"].append("weekly challenge: {}: {}".format(
            type(error).__name__, str(error)[:200]))
    return weekly_cleared_text(game.owner, cleared), weekly_cleared_blocks(game.owner, cleared)


def announce_weekly(game, state, cleared, day):
    """Tell the room a weekly challenge was cleared: the channel (the default), the game's own
    thread, or nobody (input announce_weekly). `day` is the player's today. Returns True only if
    it was posted."""
    game.result["weekly_cleared"] = [e.get("text") or "" for e in cleared]
    place = weekly_place(game.options.get("weekly"))
    if not place:
        return False
    text, blocks = weekly_post(game, cleared, day)
    ts, error = slack_post(game.token, game.channel, text, blocks,
                           thread_ts=(state.get("thread_ts") if place == "thread" else None))
    if error:
        game.result["warnings"].append("weekly challenge post: " + error)
        return False
    game.result["weekly_ts"] = ts
    return True

# --------------------------------------------------------------------------
# EDGES -- everything below talks to the network
# --------------------------------------------------------------------------

def coerce_value(name, value):
    kind = COLUMN_TYPES.get(name, "string")
    if value is None:
        return None
    try:
        if kind == "integer":
            return int(round(float(value)))
    except (TypeError, ValueError):
        return value
    return value if isinstance(value, str) else str(value)


def _send_json(url, headers, payload, method="POST", timeout=HTTP_TIMEOUT):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {} {}: {}".format(error.code, method,
                                                url.split("/")[2], detail)
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


class Table(object):
    """Workato data table access, by column name rather than UUID."""

    def __init__(self, token):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.errors = []
        self.written = 0

    def _decode(self, body):
        """The query endpoint returns schema and data as arrays-of-arrays."""
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        return [dict(zip(columns, [v for group in row for v in group]))
                for row in body.get("data", [])]

    def board(self, row_type):
        """Every player's row of this type, narrowed to what a record needs.

        Returns LOOKUP_FAILED on a failed read, and the caller then simply does
        not announce -- a missed celebration is cheaper than a wrong one.
        """
        rows = self._query({"where": {"row_type": {"$eq": row_type}},
                            "select": ["id", "name", "personal_best_single_set", "total"],
                            "limit": 200})
        return rows

    def _query(self, payload):
        for attempt in (1, 2):
            body, error = _send_json(TABLE_QUERY_URL, self.headers, payload)
            if not error:
                return self._decode(body)
            if attempt == 2:
                self.errors.append("table.query " + error)
        return LOOKUP_FAILED

    def weekly_pending(self, owner, keys, day):
        """Weekly-challenge entries this player accepted before they had a row to hold them
        (they had never finished an Easy game), still in their week. Read only when a first
        game is about to create that row; whatever cannot be read is simply not there."""
        out = []
        for key in keys:
            rows = self._query({"where": {"$and": [
                {"row_type": {"$eq": WEEKLY_ACCEPT_ROW}}, {"group_id": {"$eq": owner}},
                {"grant_type": {"$eq": key}}]}, "limit": 20})
            if rows is LOOKUP_FAILED:
                continue
            for row in rows:
                entry = weekly_entry_from(row.get("content"))
                if entry and entry.get("state") == "open" and as_date(entry["to"]) >= day:
                    out.append(entry)
        return out

    def _every(self, where):
        """Every row matching `where`, following the pages to the last; LOOKUP_FAILED if any
        page cannot be read, since half a list would answer the question wrongly."""
        payload, rows = {"where": where, "limit": 200}, []
        for _page in range(50):
            body, error = _send_json(TABLE_QUERY_URL, self.headers, payload)
            if error:
                self.errors.append("table.query " + error)
                return LOOKUP_FAILED
            rows.extend(self._decode(body))
            if not body.get("continuation_token"):
                return rows
            payload["continuation_token"] = body["continuation_token"]
        return rows

    def weekly_week(self, owner, day):
        """(rows, accepted) for deciding whether a game has cleared the last of the player's
        weekly goals: every row of theirs, and the entries on their acceptance rows whose week
        has not ended. None if either read failed."""
        rows = self._every({"id": {"$eq": owner}})
        accepts = (LOOKUP_FAILED if rows is LOOKUP_FAILED else self._every({"$and": [
            {"row_type": {"$eq": WEEKLY_ACCEPT_ROW}}, {"group_id": {"$eq": owner}}]}))
        if accepts is LOOKUP_FAILED:
            return None
        entries = [weekly_entry_from(row.get("content")) for row in accepts]
        return rows, [e for e in entries if e and as_date(e["to"]) >= day]

    def _first(self, where):
        """The first row matching `where`, with its $record_id.

        Returns LOOKUP_FAILED, not None, when the read itself failed. None means
        "no row yet" and leads to a create; mistaking a network blip for it
        would overwrite a player's record with a first-timer's. One retry,
        because a blip is the usual cause.
        """
        rows = self._query({"where": {"$and": where}, "limit": 1})
        if rows is LOOKUP_FAILED:
            return LOOKUP_FAILED
        return rows[0] if rows else None

    def row_for(self, row_type, user_id):
        return self._first([{"row_type": {"$eq": row_type}},
                            {"id": {"$eq": user_id}}])

    def row_by_key(self, row_type, record_key):
        return self._first([{"row_type": {"$eq": row_type}},
                            {"record_key": {"$eq": record_key}}])

    def _document(self, fields):
        document = {}
        for name, value in fields.items():
            uuid = COLUMNS.get(name)
            if uuid is None:
                self.errors.append("write: unknown column " + name)
                continue
            document["$" + uuid] = coerce_value(name, value)
        return document

    def create(self, fields, find=None):
        """Returns (ok, record_id).

        `ok` means the row was written. The record id is read from the response
        when it carries one; the table's create call does not reliably, so
        `find` -- a zero-argument lookup returning the new row -- is the
        fallback. record_id is "" only if both fail, which the caller must
        treat as "written but not addressable", never as "not written": a retry
        would create a second row.
        """
        body, error = _send_json(TABLE_RECORDS_URL, self.headers,
                                 {"document": self._document(fields)}, "POST")
        if error:
            self.errors.append("table.create " + error)
            return False, ""
        self.written += 1
        body = body if isinstance(body, dict) else {}
        record_id = (body.get("record_id") or body.get("$record_id")
                     or body.get("id") or "")
        if not record_id and find:
            for attempt in (1, 2):
                row = find()
                if row and row is not LOOKUP_FAILED:
                    record_id = row.get("$record_id") or ""
                    break
                if attempt == 1:
                    _sleep(0.5)       # let the new row become visible to queries
        return True, str(record_id)

    def update(self, record_id, fields):
        if not record_id:
            self.errors.append("table.update without a $record_id")
            return False
        body, error = _send_json(TABLE_RECORD_URL.format(record_id), self.headers,
                                 {"document": self._document(fields)}, "PUT")
        if error:
            self.errors.append("table.update " + error)
            return False
        self.written += 1
        return True


def _slack_headers(token):
    return {"Authorization": "Bearer {}".format(token),
            "Content-Type": "application/json; charset=utf-8"}


def _slack_call(token, url, payload):
    body, error = _send_json(url, _slack_headers(token), payload)
    if error:
        return None, error
    if not body.get("ok"):
        return None, "slack: " + str(body.get("error"))
    return body, None


def slack_post(token, channel, text, blocks, thread_ts=None):
    """Returns (ts, error)."""
    payload = {"channel": channel, "text": text, "blocks": blocks}
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    body, error = _slack_call(token, SLACK_POST_URL, payload)
    return ((body or {}).get("ts") or ""), error


def slack_update(token, channel, ts, text, blocks):
    _, error = _slack_call(token, SLACK_UPDATE_URL, {
        "channel": channel, "ts": str(ts), "text": text, "blocks": blocks})
    return error


def slack_delete(token, channel, ts):
    _slack_call(token, SLACK_DELETE_URL, {"channel": channel, "ts": str(ts)})


def slack_ephemeral(token, channel, user, text, thread_ts=None):
    payload = {"channel": channel, "user": user, "text": text}
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    _slack_call(token, SLACK_EPHEMERAL_URL, payload)


def slack_user(token, user_id):
    """Real name and tz offset from users.info. Never raises."""
    fallback = {"real_name": "", "tz_offset": DEFAULT_TZ_OFFSET}
    if not token or not user_id:
        return fallback
    request = urllib.request.Request(
        "{}?user={}".format(SLACK_USER_URL, user_id),
        headers={"Authorization": "Bearer {}".format(token)}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:                                              # noqa: BLE001
        return fallback
    if not body.get("ok"):
        return fallback
    user = body.get("user") or {}
    profile = user.get("profile") or {}
    # real_name first (display names carry pronoun suffixes); user["name"] is
    # the last resort so a Slack Connect guest is not stored as a raw U-id.
    name = (profile.get("real_name") or user.get("real_name")
            or profile.get("display_name") or user.get("name") or "")
    return {"real_name": name.strip(),
            "tz_offset": user.get("tz_offset", DEFAULT_TZ_OFFSET)}


class Screen(object):
    """The single Slack message a game lives in, edited from start to finish."""

    def __init__(self, token, channel, ts, thread_ts, warnings, lined=False):
        self.token = token
        self.channel = channel
        self.ts = ts
        self.thread_ts = thread_ts
        self.warnings = warnings
        self.lined = bool(lined)          # draw a line on top of every screen (see divided)

    def show(self, text, blocks, essential=False):
        """Put `blocks` on screen: edit the message, or post it the first time.

        An essential screen (the question) must land. If the edit fails it is
        posted fresh and the stale message removed -- a lost countdown tick is
        harmless, a lost question strands the player with no buttons.
        """
        if self.lined:
            blocks = divided(blocks)
        if not self.ts:
            ts, error = slack_post(self.token, self.channel, text, blocks,
                                   thread_ts=self.thread_ts)
            if error:
                raise RuntimeError("could not post the game: " + error)
            self.ts = ts
            return
        error = slack_update(self.token, self.channel, self.ts, text, blocks)
        if not error:
            return
        if not essential:
            self.warnings.append("update: " + error)
            return
        ts, post_error = slack_post(self.token, self.channel, text, blocks,
                                    thread_ts=self.thread_ts)
        if post_error:
            raise RuntimeError("could not show the question: {}; retry: {}".format(
                error, post_error))
        slack_delete(self.token, self.channel, self.ts)
        self.warnings.append("edit failed ({}); posted fresh".format(error))
        self.ts = ts

# --------------------------------------------------------------------------
# One question, on screen
# --------------------------------------------------------------------------

class Game(object):
    """What one running step needs to move a game along."""

    def __init__(self, key, table, token, result, channel, owner, name, record_id,
                 trigger_ts, screen, options=None):
        self.key = key
        self.table = table
        self.token = token
        self.result = result
        self.channel = channel
        self.owner = owner
        self.name = name
        self.record_id = record_id
        self.trigger_ts = trigger_ts
        self.screen = screen
        self.q_clock = 0.0       # _clock() once the live question and its clock were on screen
        self.q_deadline = 0.0    # _clock() at which the countdown calls time (see play_round)
        # Recipe switches that outlive a single click: whether to announce
        # records in the channel, and the banner image for a channel record.
        self.options = options or {"announce": True, "announce_daily": True,
                                    "banner": RECORD_BANNER}

    def write(self, status, state, ts):
        state["ts"] = ts
        self.table.update(self.record_id, _session_fields(
            self.key, self.owner, self.name, self.channel, status, state, self.trigger_ts))


def play_round(game, state):
    """Pick the problem, store it, and put the question on screen."""
    screen = game.screen
    state["step"] = int(state.get("step") or 0) + 1

    rng = daily_rng(game.key, state["daily"], state["step"]) if state.get("daily") else _rng
    diff = difficulty_of(state)
    problem = make_problem(game.key, state["score"], rng, diff)
    index, tier = play_tier(game.key, state["score"], diff)
    state.update({
        "expr": problem["expr"], "answer": problem["answer"], "form": problem["form"],
        "options": build_options(problem, index, tier, rng),
        "limit": tier["seconds"], "level": index + 1, "choice": None,
    })

    state["q_at"] = _now()
    stamped = _clock()
    notice = state.get("notice") or ""
    # The clock is a message of its own (see clock_blocks). On a game that already has a
    # card it is posted BEFORE the state is written, so the first click can never find a
    # question with no clock message to update.
    fresh_clock = False
    if screen.ts and not state.get("clock_ts"):
        state["clock_ts"] = post_clock(game, state["limit"], notice)
        fresh_clock = True

    # State is written BEFORE the buttons appear, so a click can never arrive
    # for a question the table does not know about.
    game.write(SESSION_ACTIVE, state, screen.ts)
    previous_ts = screen.ts
    screen.show("{}: {}".format(GAMES[game.key]["name"], question_text(state)),
                question_blocks(state, game.owner), essential=True)
    if screen.ts != previous_ts:           # the question went out as a new post...
        drop_clock(game, state)            # ...so the clock goes below it, not above
        state["clock_ts"] = post_clock(game, state["limit"], notice)
        game.write(SESSION_ACTIVE, state, screen.ts)
    elif state.get("clock_ts") and not fresh_clock:
        # the next question: the clock starts again, with the note that goes with it
        clock_screen(game, state).show("{}: clock".format(GAMES[game.key]["name"]),
                                       clock_blocks(state["limit"], notice))
    # The countdown runs from now, when the question and its clock are on screen: the
    # writes and posts above take a second or two in Workato, and counting from `stamped`
    # took that out of the player's time. A click is still judged against q_at (it is in
    # the table; this moment is not), and its grace covers the gap. Time is called only
    # once that click deadline has passed and a click stamped inside it could have landed.
    game.q_clock = _clock()
    game.q_deadline = max(stamped + state["limit"] + CLICK_GRACE_SECONDS,
                          game.q_clock + state["limit"]) + CLICK_ARRIVAL_SECONDS
    return state


def clock_screen(game, state):
    """The clock message, as something to edit."""
    return Screen(game.token, game.channel, state.get("clock_ts") or "", game.screen.thread_ts,
                  game.result["warnings"])


def post_clock(game, seconds, notice=""):
    """Post the clock as its own message, in the game's thread. Returns its ts, or '' --
    a clock that could not be posted costs the display, never the game: the deadline is
    kept by the countdown step and by the click's own timestamp."""
    ts, error = slack_post(game.token, game.channel,
                           "{}: clock".format(GAMES[game.key]["name"]),
                           clock_blocks(seconds, notice), thread_ts=game.screen.thread_ts)
    if error:
        game.result["warnings"].append("clock: " + error)
        return ""
    return ts


def drop_clock(game, state):
    """Take the clock message down (the game is over, or the question moved)."""
    ts = state.get("clock_ts")
    if ts:
        slack_delete(game.token, game.channel, ts)
    state["clock_ts"] = ""


def watch_question(game, state):
    """Count the question's clock down on screen, and settle it at zero.

    Runs in the step that posted the question, while the player's click runs in a
    different job. So each second it first asks the table whether this question is
    still the live one -- if the player answered, or the game moved on, there is
    nothing left to watch and it stops without touching the message. At zero it
    claims the question exactly the way a click does, so the two can never both
    settle it.

    A tick edits the CLOCK message and nothing else. The question message is changed
    only by the click that answers it, or by the timeout, and both claim it first.

    The clock reads 0s at zero, but time is called only at q_deadline: claiming at zero
    beat every click from the last second or two (still on its way from Slack), which
    then read "busy" and was dropped -- a right answer shown as Time's up.
    """
    limit = int(state["limit"])
    step, ts = state["step"], game.screen.ts
    for remaining in list(range(limit - 1, -1, -1)) + [None]:     # None: time is called
        due = game.q_deadline if remaining is None else game.q_clock + (limit - remaining)
        wait = due - _clock()
        if wait > 0:
            _sleep(wait)
        row = game.table.row_for(row_type(game.key, "session"), game.owner)
        if row is LOOKUP_FAILED:
            continue          # cannot tell; the click-time deadline still holds
        live = load_state(row) if row else {}
        if (not row or row.get("status") != SESSION_ACTIVE
                or live.get("step") != step or live.get("ts") != ts):
            return            # answered, replaced or over: not ours any more
        if remaining is not None:
            tick = limit - remaining
            notice = state.get("notice") if tick < int(state.get("notice_ticks") or 0) else ""
            if state.get("clock_ts"):
                clock_screen(game, state).show(
                    "{}: clock".format(GAMES[game.key]["name"]),
                    clock_blocks(remaining, notice))
            continue
        if not game.table.update(game.record_id, {"status": SESSION_BUSY}):
            return
        settle(game, state, None, float(limit))


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def _session_fields(key, owner, name, channel, status, state, trigger_ts):
    return {
        "record_key": "{}_{}".format(row_type(key, "session"), owner),
        "row_type": row_type(key, "session"),
        "id": owner,
        "name": name,
        "status": status,
        "slack_channel_id": channel,
        "last_processed_ts": str(trigger_ts),
        "content": json.dumps(state, separators=(",", ":")),
    }


def daily_key(key, owner, day):
    return "{}_{}_{}".format(row_type(key, "daily"), owner, day)


def _switch(value):
    """A recipe switch that is on unless it says otherwise."""
    return str(value or "").strip().lower() not in ("false", "0", "no")


def _flag(value):
    """A recipe switch that is off unless it says yes."""
    return str(value or "").strip().lower() in ("yes", "y", "true", "1", "on")


def is_testing(input, state=None):
    """A test game: the `testing` input says yes, or the game was started as one.

    The game remembers it (state["test"]), so only the recipe that starts a game has
    to map the input; a click on a test game stays a test even if its recipe does not."""
    return _flag(input.get("testing")) or bool((state or {}).get("test"))


def run_options(input, state=None):
    return {"announce": _switch(input.get("announce_records")),
            "announce_daily": _switch(input.get("announce_daily")),
            "banner": str(input.get("record_banner") or "").strip() or RECORD_BANNER,
            "weekly": input.get("announce_weekly"),
            "testing": is_testing(input, state)}


def report_round(result, state):
    result["round"] = state["step"]
    result["level"] = state["level"]
    result["difficulty"] = difficulty_of(state)
    result["expression"] = state["expr"]
    result["options"] = state["options"]
    result["correct_answer"] = state["answer"]
    result["shields"] = state["shields"]


def fresh_state(key, owner, name, tz_offset, channel, thread_ts, best, day, lined=False, chan=None,
                diff=EASY, test=False, nxt=None):
    return {"v": 2, "game": key, "owner": owner, "diff": diff, "test": test, "step": 0,
            "level": 1, "score": 0, "next": nxt or {}, "clock_ts": "",
            "secs": 0.0, "channel": channel, "thread_ts": thread_ts, "ts": "",
            "name": name, "tz": tz_offset, "started": _now(), "best": best,
            "shields": 0, "trail": "", "daily": day, "lined": lined, "chan": chan or {}}


def open_rules_card(key, result, table, token, record_id, state, name, trigger_ts):
    """Post the rules card and wait for Start. True when the game is ready."""
    owner, channel, thread_ts = state["owner"], state["channel"], state["thread_ts"]
    screen = Screen(token, channel, "", thread_ts, result["warnings"], lined=state.get("lined"))
    try:
        screen.show("{}: ready to start".format(GAMES[key]["name"]), intro_blocks(state, owner))
    except RuntimeError as error:
        result["error"] = str(error)
        return False
    state["ts"] = screen.ts
    if not table.update(record_id, _session_fields(
            key, owner, name, channel, SESSION_READY, state, trigger_ts)):
        # A card whose button the table would reject is worse than no card.
        slack_delete(token, channel, screen.ts)
        result["error"] = "could not save the game; nothing started"
        return False
    result["ok"] = True
    result["posted_ts"] = screen.ts
    return True


def retire_card(token, channel, state):
    """Redraw a finished game's result card without its buttons. Returns an error or ""."""
    card = state.get("card")
    if not card or not state.get("ts"):
        return ""
    blocks = over_blocks(state, card["b"], card["s"], card["n"], card["sh"],
                         card["d"], buttons=False)
    if state.get("lined"):                         # a card that had its line keeps it
        blocks = divided(blocks)
    return slack_update(token, channel, state["ts"],
                        "{}: game over".format(GAMES[state["game"]]["name"]), blocks) or ""


def start_game(input, result, table, token, origin="", diff=EASY):
    """Keyword typed (or a post's button): claim the message, then post the rules card.

    `origin` is the ts of the channel post whose button started this game, if any, and
    `diff` the difficulty the card's dropdown starts on (a record post's, for its button).
    """
    key = result["game"]
    user_id = result["user_id"]
    channel = result["channel"]
    message_ts = result["message_ts"]
    thread_ts = result["thread_ts"]
    daily = result["variant"] == "daily"
    day = local_today(DAILY_TZ_OFFSET).isoformat() if daily else ""
    testing = is_testing(input)
    result["testing"] = testing

    session = table.row_for(row_type(key, "session"), user_id)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the game table; nothing started"
        return
    if session and is_duplicate(session, message_ts):
        result["ok"] = True
        result["skipped"] = "duplicate delivery of this message"
        return

    if daily and not testing:         # a test game may replay today's set as often as it likes
        played = table.row_by_key(row_type(key, "daily"), daily_key(key, user_id, day))
        if played is LOOKUP_FAILED:
            result["error"] = "could not read the game table; nothing started"
            return
        if played:
            slack_post(token, channel, "{} Daily: already played today".format(GAMES[key]["name"]),
                       already_played_blocks(key, day, played), thread_ts=thread_ts)
            result["ok"] = True
            result["skipped"] = "today's daily set was already played"
            return

    who = slack_user(token, user_id)
    name = who["real_name"] or user_id
    result["user_name"] = name

    # The target to beat. A failed read just means no target is shown; it must
    # not stop the game.
    best = 0
    if not daily:
        row = table.row_for(user_row_type(key, diff), user_id)
        if row is LOOKUP_FAILED:
            result["warnings"].append("best score unreadable; no target shown")
        elif row:
            best = int(row.get("personal_best_single_set") or 0)
    nxt, chan = ({}, {}) if daily else rival_targets(
        table, user_row_type(key, diff), user_id, best, result["warnings"])

    state = fresh_state(key, user_id, name, who["tz_offset"], channel, thread_ts, best, day, chan=chan,
                        test=testing, nxt=nxt, diff=EASY if daily else diff)
    state["origin"] = origin

    # The last game's result card keeps its result but loses its buttons: there is
    # a new game now, and "Play again" on the old card would start a second one.
    if session and session.get("status") == SESSION_OVER:
        error = retire_card(token, channel, load_state(session))
        if error:
            result["warnings"].append("old card: " + error)

    # Claim before posting: a Slack retry of this same message now finds
    # last_processed_ts and stops, instead of starting a second game.
    claim = _session_fields(key, user_id, name, channel, SESSION_STARTING, state, message_ts)
    record_id = (session or {}).get("$record_id")
    if session:
        if not table.update(record_id, claim):
            result["error"] = "could not claim the game row"
            return
    else:
        created, record_id = table.create(
            claim, find=lambda: table.row_for(row_type(key, "session"), user_id))
        if not created:
            result["error"] = "could not create the game row"
            return
        if not record_id:
            result["error"] = ("the game row was created but its id could not be read "
                               "back; nothing started")
            return

    # The rules card. Nothing is timed and, for the daily set, no attempt is spent
    # until the player presses Start: reading the rules is not play.
    open_rules_card(key, result, table, token, record_id, state, name, message_ts)


def begin_game(game, state):
    """The Start button: spend the daily attempt if there is one, then ask question 1."""
    result, table, screen = game.result, game.table, game.screen
    result["mode"] = "begin"

    def give_the_button_back(message):
        table.update(game.record_id, {"status": SESSION_READY})
        result["error"] = message

    day = state.get("daily")
    if day:
        daily_type = row_type(game.key, "daily")
        testing = game.options.get("testing")
        played = None if testing else table.row_by_key(
            daily_type, daily_key(game.key, game.owner, day))
        if played is LOOKUP_FAILED:
            give_the_button_back("could not read the game table; press Start again")
            return
        if day != local_today(DAILY_TZ_OFFSET).isoformat() or played:
            # The set went stale overnight, or the attempt was already used from
            # another card. Say so on this card and close the session.
            screen.show("{} Daily: not available".format(GAMES[game.key]["name"]),
                        already_played_blocks(game.key, day, played) if played
                        else daily_ended_blocks(game.key))
            table.update(game.record_id, {"status": SESSION_OVER})
            result["ok"] = True
            result["skipped"] = ("today's daily set was already played" if played
                                 else "this daily set has ended")
            return
        # The attempt is spent the moment the first question is on screen -- unless this
        # is a test game, which spends nothing.
        state["daily_rid"] = ""
        if not testing:
            created, state["daily_rid"] = table.create({
                "record_key": daily_key(game.key, game.owner, day), "row_type": daily_type,
                "id": game.owner, "name": game.name, "status": DAILY_PLAYING,
                "current_value": 0, "updated_at": day, "slack_channel_id": game.channel,
                "last_processed_ts": game.trigger_ts},
                find=lambda: table.row_by_key(daily_type, daily_key(game.key, game.owner, day)))
            if not created or not state["daily_rid"]:
                give_the_button_back("could not record today's attempt; press Start again")
                return

    state["started"] = _now()
    state["notice"], state["notice_ticks"] = "", 0
    try:
        play_round(game, state)
    except RuntimeError as error:
        drop_clock(game, state)
        table.update(game.record_id, {"status": SESSION_OVER})
        result["error"] = str(error)
        return
    result["ok"] = True
    report_round(result, state)
    result["posted_ts"] = screen.ts
    watch_question(game, state)         # holds the step open until answered or timed out


def join_blocked(result, token, channel, clicker, session, source_ts, key):
    """Whether a record post's Play button should do nothing for this person (as iMemory's).
    If so the result says why, and a game in play is told so privately.

    Two cases: this same button was already pressed (their rules card from this post is
    up, or coming), and a game of theirs that is in play right now, which a button anyone
    can reach must not replace by accident (typing the keyword still does, on purpose).
    "In play" is a question answered or asked within the longest clock there is; past that
    the game is closed, or is a dead one that nothing is going to move.
    """
    state = load_state(session) if session else {}
    status = (session or {}).get("status")
    if state.get("origin") == source_ts and (
            status == SESSION_READY or (status == SESSION_STARTING and
                                        _now() - float(state.get("started") or 0)
                                        < STARTING_STALE_SECONDS)):
        result["ok"] = True
        result["skipped"] = "stale or repeated click"
        return True
    longest = max(t["seconds"] for t in TIERS[key])
    quiet = _now() - float(state.get("q_at") or state.get("started") or 0)
    if status in (SESSION_ACTIVE, SESSION_BUSY) and \
            quiet < longest + CLICK_GRACE_SECONDS + REASSERT_SECONDS + 1:
        slack_ephemeral(token, channel, clicker,
                        "You already have an {} game in play. Finish it first, or type `{}` "
                        "to start a fresh one.".format(GAMES[key]["name"], key),
                        thread_ts=source_ts)
        result["ok"] = True
        result["skipped"] = "a game of theirs is in play"
        return True
    return False


def join_in_thread(input, result, table, token, key, source_ts, diff=EASY):
    """A record post's Play button, which ANYONE may press: start the presser's own free
    game as a reply in that post's thread, on the difficulty the record was set at.

    The rules card lands under the post, so the channel gets no new top-level message,
    and Play again stays in the thread. Nothing is timed until Start is pressed, and the
    dropdown is there to pick another difficulty first.
    """
    result["mode"] = "join"
    result["variant"] = "play"
    if not source_ts:
        result["error"] = "source_ts is required for the record post's play button"
        return
    clicker = result["user_id"]
    session = table.row_for(row_type(key, "session"), clicker)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the game table; nothing started"
        return
    if join_blocked(result, token, result["channel"], clicker, session, source_ts, key):
        return
    # A message_ts that is unique to this press, so a Slack retry of the SAME press is
    # caught as a duplicate while a later press is not.
    result["message_ts"] = "join:{}".format(str(input.get("action_ts") or source_ts))
    result["thread_ts"] = source_ts
    start_game(input, result, table, token, origin=source_ts,
               diff=diff if diff in DIFFICULTY else EASY)


def join_from_post(input, result, table, token, key, source_ts, daily):
    """A button on a channel post that ANYONE may press: start the clicker's own game.

    The post is the daily nudge after someone finishes a daily, or the scheduled daily
    nudge for this game. `daily=True` (Play today's daily) is what typing `<game> daily`
    does; `daily=False` (Play a game) is what typing `<game>` does. Either way: a root
    message in the channel naming the player, the rules card as a reply in its thread,
    and nothing spent until Start -- so each person's game has a thread of its own.
    """
    result["mode"] = "join"
    result["variant"] = "daily" if daily else "play"
    channel = result["channel"]
    name = GAMES[key]["name"]
    if not source_ts:
        result["error"] = "source_ts is required for the post's play buttons"
        return
    clicker = result["user_id"]
    day = local_today(DAILY_TZ_OFFSET).isoformat() if daily else ""

    # Everything that can say "no" is checked BEFORE a root message is posted, so a
    # refused press leaves nothing behind.
    session = table.row_for(row_type(key, "session"), clicker)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the game table; nothing started"
        return
    state = load_state(session) if session else {}
    waiting = (session and state.get("daily") == day and state.get("origin") == source_ts
               and (session.get("status") == SESSION_READY
                    or (session.get("status") == SESSION_STARTING
                        and _now() - float(state.get("started") or 0) < STARTING_STALE_SECONDS)))
    if waiting:                                  # their card from this post is already up (or coming)
        result["ok"] = True
        result["skipped"] = "stale or repeated click"
        return
    if daily and not is_testing(input):    # `state` is the clicker's OLD game, not this one
        played = table.row_by_key(row_type(key, "daily"), daily_key(key, clicker, day))
        if played is LOOKUP_FAILED:
            result["error"] = "could not read the game table; nothing started"
            return
        if played:
            slack_ephemeral(token, channel, clicker,
                            "You have already played today's {} set. A new one tomorrow.".format(name))
            result["ok"] = True
            result["skipped"] = "today's daily set was already played"
            return

    root_ts, error = slack_post(
        token, channel, "<@{}> joined {}".format(clicker, "today's {} Daily".format(name) if daily else name),
        [{"type": "section", "text": {"type": "mrkdwn", "text": (
            ":calendar:  <@{}> joined today's *{} Daily*  \u2014  the game is in this thread.".format(clicker, name)
            if daily else
            "{}  <@{}> is playing *{}*  \u2014  the game is in this thread.".format(
                GAMES[key]["icon"], clicker, name))}}])
    if error:
        result["error"] = "could not open a thread for the game: " + error
        return

    # A message_ts that is unique to this press, so a Slack retry of the SAME press is
    # caught as a duplicate while a later press is not.
    result["message_ts"] = "{}:{}".format("try" if daily else "play",
                                          str(input.get("action_ts") or source_ts))
    result["thread_ts"] = root_ts
    start_game(input, result, table, token, origin=source_ts)
    if not result.get("ok") or result.get("skipped"):
        slack_delete(token, channel, root_ts)      # nothing started: do not leave an empty thread


def replay_game(input, result, table, token, key, owner, step_no, kind, session, state,
                source_ts):
    """The result card's buttons: Play again, or Today's daily -- in the same thread.

    Play again starts at once, in a new message under the same thread: the player
    already knows the rules. Today's daily posts its rules card instead, because
    the day's single attempt is spent at Start and should be a deliberate press.
    """
    channel = result["channel"]
    result["mode"] = "replay"
    result["variant"] = "daily" if kind == "daily" else "play"

    # Only the player's CURRENT result card replays, and only once.
    if (session.get("status") != SESSION_OVER or state.get("step") != step_no
            or (source_ts and state.get("ts") and source_ts != state["ts"])):
        result["ok"] = True
        result["skipped"] = "stale or repeated click"
        return

    record_id = session.get("$record_id")
    name = state.get("name") or owner
    thread_ts = state.get("thread_ts") or result["thread_ts"]
    day = ""
    testing = is_testing(input, state)
    result["testing"] = testing
    if kind == "daily":
        day = local_today(DAILY_TZ_OFFSET).isoformat()
        played = None if testing else table.row_by_key(
            row_type(key, "daily"), daily_key(key, owner, day))
        if played is LOOKUP_FAILED:
            result["error"] = "could not read the game table; the buttons are unchanged"
            return
        if played:
            slack_ephemeral(token, channel, owner,
                            "You have already played today's {} set. A new one tomorrow.".format(
                                GAMES[key]["name"]),
                            thread_ts=thread_ts or None)
            result["ok"] = True
            result["skipped"] = "today's daily set was already played"
            return

    # CLAIM: a second press now reads "busy" and backs off.
    if not table.update(record_id, {"status": SESSION_BUSY}):
        result["error"] = "could not claim the click; the buttons are unchanged"
        return
    error = retire_card(token, channel, state)
    if error:
        result["warnings"].append("old card: " + error)

    # Play again keeps the difficulty the last game was played at. A daily is always Easy.
    diff = EASY if day else difficulty_of(state)
    best = 0
    if not day:
        row = table.row_for(user_row_type(key, diff), owner)
        if row is LOOKUP_FAILED:
            result["warnings"].append("best score unreadable; no target shown")
        elif row:
            best = int(row.get("personal_best_single_set") or 0)
    nxt, chan = ({}, {}) if day else rival_targets(
        table, user_row_type(key, diff), owner, best, result["warnings"])
    new = fresh_state(key, owner, name, state.get("tz") or DEFAULT_TZ_OFFSET,
                      channel, thread_ts, best, day, lined=True, chan=chan, diff=diff, test=testing,
                      nxt=nxt)
    trigger_ts = session.get("last_processed_ts") or ""
    result["user_name"] = name

    if kind == "daily":
        open_rules_card(key, result, table, token, record_id, new, name, trigger_ts)
        return
    screen = Screen(token, channel, "", thread_ts, result["warnings"], lined=True)
    game = Game(key, table, token, result, channel, owner, name, record_id, trigger_ts,
                screen, options=run_options(input, new))
    begin_game(game, new)


def set_difficulty(state, diff, table, result):
    """Put the game on `diff`, with that difficulty's targets to beat: your best on it, and
    the channel's. A failed read just means no target is shown."""
    key, owner = state["game"], state["owner"]
    best = 0
    row = table.row_for(user_row_type(key, diff), owner)
    if row is LOOKUP_FAILED:
        result["warnings"].append("best score unreadable; no target shown")
    elif row:
        best = int(row.get("personal_best_single_set") or 0)
    nxt, chan = rival_targets(table, user_row_type(key, diff), owner, best, result["warnings"])
    state.update({"diff": diff, "best": best, "next": nxt, "chan": chan})


def picked_difficulty(input, state):
    """The difficulty the dropdown showed when this click was made, if it differs.

    Slack sends the current value of every control in the message (`state.values`) with
    every click from it. So a Start press arrives carrying the dropdown's choice, and the
    game plays it even if the pick itself was never processed -- the card must not say
    Very hard while the game starts on Easy."""
    picked = parse_action(str(input.get("selected_value") or "").strip())
    if not picked or state.get("daily"):
        return None
    game, owner, _, diff = picked
    if (game != state.get("game") or owner != state.get("owner")
            or diff not in DIFFICULTY or diff == difficulty_of(state)):
        return None
    return diff


def choose_difficulty(result, table, token, session, state, diff, source_ts):
    """The dropdown on the rules card: draw the same card again at the chosen difficulty.

    Only a card that is waiting for Start can change. The session is claimed (busy) for
    the moment this takes, so a Start pressed at the same time reads "busy" and backs
    off rather than starting a game this write then overwrites."""
    result["mode"] = "difficulty"
    key, owner = state["game"], state["owner"]
    if (session.get("status") != SESSION_READY or state.get("daily")
            or diff == difficulty_of(state)):
        result["ok"] = True
        result["skipped"] = "stale or repeated click"
        return
    record_id = session.get("$record_id")
    if not table.update(record_id, {"status": SESSION_BUSY}):
        result["error"] = "could not claim the click; the card is unchanged"
        return

    set_difficulty(state, diff, table, result)
    name = state.get("name") or owner
    if not table.update(record_id, _session_fields(
            key, owner, name, state["channel"], SESSION_READY, state,
            session.get("last_processed_ts") or "")):
        table.update(record_id, {"status": SESSION_READY})      # give the card back as it was
        result["error"] = "could not save the difficulty; the card is unchanged"
        return
    screen = Screen(token, result["channel"], state.get("ts") or source_ts,
                    state.get("thread_ts") or result["thread_ts"], result["warnings"],
                    lined=state.get("lined"))
    screen.show("{}: ready to start".format(GAMES[key]["name"]), intro_blocks(state, owner))
    result["ok"] = True
    result["user_name"] = name
    result["game"] = key
    result["difficulty"] = diff
    result["posted_ts"] = screen.ts


def click_value(input):
    """The pressed control's value: a button's, or the option picked in the dropdown."""
    return str(input.get("action_value") or input.get("selected_value") or "").strip()


def answer_game(input, result, table, token):
    """A button was pressed: Start, or an answer."""
    channel = result["channel"]
    clicker = result["user_id"]
    source_ts = str(input.get("source_ts") or "").strip()
    parsed = parse_action(click_value(input))
    if not parsed:
        result["error"] = ("action_value is not '<game>|<user>|<step>|"
                           "<number|start|again|daily|try|play|join|easy|medium|hard|very_hard>'")
        return
    key, owner, step_no, choice = parsed
    result["game"] = key

    if isinstance(choice, str) and choice.startswith("join"):
        join_in_thread(input, result, table, token, key, source_ts,
                       diff=choice.partition(":")[2] or EASY)
        return
    if choice in ("try", "play"):
        join_from_post(input, result, table, token, key, source_ts, daily=(choice == "try"))
        return

    if clicker != owner:
        slack_ephemeral(token, channel, clicker,
                        "This is someone else's {} game. Type `{}` to start your own.".format(
                            GAMES[key]["name"], key),
                        thread_ts=result["thread_ts"] or source_ts or None)
        result["ok"] = True
        result["skipped"] = "button belongs to another player"
        return

    session = table.row_for(row_type(key, "session"), owner)
    if session is LOOKUP_FAILED:
        # Nothing has been touched, so the buttons still work: press again.
        result["error"] = "could not read the game table; the buttons are unchanged"
        return
    state = load_state(session)
    if not session or not state:
        _expire(token, channel, source_ts, key)
        result["ok"] = True
        result["skipped"] = "no game found for this player"
        return
    result["testing"] = is_testing(input, state)
    if result["testing"]:
        state["test"] = True
    if choice in ("again", "daily"):
        replay_game(input, result, table, token, key, owner, step_no, choice, session,
                    state, source_ts)
        return
    if source_ts and state.get("ts") and source_ts != state["ts"]:
        _expire(token, channel, source_ts, key)         # an older game's message
        result["ok"] = True
        result["skipped"] = "message belongs to a replaced game"
        return
    if choice in DIFFICULTY:
        choose_difficulty(result, table, token, session, state, choice, source_ts)
        return
    # Start is only valid on a game that is waiting for it; an answer only on a
    # live question, and only one of the answers that question offered.
    waiting_for = SESSION_READY if choice == "start" else SESSION_ACTIVE
    offered = choice == "start" or choice in (state.get("options") or [])
    if session.get("status") != waiting_for or state.get("step") != step_no or not offered:
        result["ok"] = True
        result["skipped"] = "stale or repeated click"
        return

    # CLAIM. From here a second click -- or the clock reaching zero -- reads
    # "busy" and backs off, which is what stops one question settling twice.
    record_id = session.get("$record_id")
    name = state.get("name") or owner
    result["user_name"] = name
    result["variant"] = "daily" if state.get("daily") else "play"

    if not table.update(record_id, {"status": SESSION_BUSY}):
        result["error"] = "could not claim the click; the buttons are unchanged"
        return

    screen = Screen(token, channel, state.get("ts") or source_ts,
                    state.get("thread_ts") or result["thread_ts"], result["warnings"],
                    lined=state.get("lined"))
    game = Game(key, table, token, result, channel, owner, name, record_id,
                session.get("last_processed_ts") or "", screen,
                options=run_options(input, state))

    if choice == "start":
        diff = picked_difficulty(input, state)
        if diff:
            set_difficulty(state, diff, table, result)
        begin_game(game, state)
        return

    # Thinking time is measured to Slack's own click timestamp, so recipe and
    # Workato latency do not land on the player's clock.
    limit = float(state.get("limit") or 10)
    pressed = _float(input.get("action_ts")) or _now()
    thinking = max(0.0, pressed - float(state.get("q_at") or pressed))
    if thinking > limit + CLICK_GRACE_SECONDS:
        choice = None                      # too late, whatever the countdown did
    thinking = min(thinking, limit)

    settle(game, state, choice, thinking, from_click=True)


def settle(game, state, choice, thinking, from_click=False):
    """Judge an answer -- None means time ran out -- and move the game on.

    The caller has already claimed the question (status busy).
    """
    result, screen = game.result, game.screen
    timed_out = choice is None
    state["secs"] = round(float(state.get("secs") or 0) + thinking, 3)
    state["choice"] = choice

    correct = (not timed_out) and choice == state["answer"]
    result["correct"] = correct
    result["timed_out"] = timed_out
    result["answer_seconds"] = round(thinking, 3)

    try:
        if correct:
            diff = difficulty_of(state)
            before_index = play_tier(game.key, state["score"], diff)[0]
            state["score"] = int(state.get("score") or 0) + 1
            state["trail"] = (state.get("trail") or "") + "g"
            notes = [":white_check_mark: Correct"]
            after_index = play_tier(game.key, state["score"], diff)[0]
            if after_index > before_index:
                notes.append(":arrow_up: *Level {}*".format(after_index + 1))
            if (state["score"] % SHIELD_EVERY == 0
                    and int(state.get("shields") or 0) < SHIELD_CAP):
                state["shields"] = int(state.get("shields") or 0) + 1
                notes.append(":shield: Shield earned")
            # The one moment worth marking: the score that first beats the best.
            passed, passed_chan = crossed(state)
            if passed:
                notes.append(":trophy: New personal best")
            if passed_next(state):
                notes.append(":dart: Passed {}".format((state.get("next") or {}).get("name") or "them"))
            if passed_chan:
                notes.append(":crown: Channel best passed")
            state["notice"] = "  ·  ".join(notes)
            state["notice_ticks"] = NOTICE_QUICK if len(notes) == 1 else NOTICE_LONG
        elif int(state.get("shields") or 0) > 0:
            state["shields"] = int(state["shields"]) - 1
            state["trail"] = (state.get("trail") or "") + "y"
            state["notice"] = ":shield: Shield used  —  {}{}".format(
                solved_text(state), "  (time ran out)" if timed_out else "")
            state["notice_ticks"] = NOTICE_LONG
        else:
            state["trail"] = (state.get("trail") or "") + "r"
            card = finish_game(game, state)
            game.write(SESSION_OVER, state, screen.ts)
            if from_click:
                _sleep(REASSERT_SECONDS)
                screen.show("{}: game over".format(GAMES[game.key]["name"]), card)
            result["ok"] = True
            result["score"] = state["score"]
            result["round"] = state["step"]
            result["level"] = state["level"]
            result["trail"] = state["trail"]
            result["total_seconds"] = state["secs"]
            result["posted_ts"] = screen.ts
            return

        play_round(game, state)
    except RuntimeError as error:
        # Slack would not take the next screen. Close the game rather than leave a
        # session no button can move: the buttons on screen carry a step the table
        # no longer expects.
        drop_clock(game, state)
        game.table.update(game.record_id, {"status": SESSION_OVER})
        result["error"] = str(error)
        return

    result["ok"] = True
    report_round(result, state)
    result["score"] = state["score"]
    result["trail"] = state["trail"]
    result["total_seconds"] = state["secs"]
    result["posted_ts"] = screen.ts
    watch_question(game, state)


def daily_blocks(key, owner, state):
    """The channel nudge after a daily game: who played, how it went, how to join in.

    The squares show how the run went without revealing a single question.
    """
    name = GAMES[key]["name"]
    squares = share_line(state).split("\n", 1)[1]
    if state["score"] > 0:
        played = "<@{}> scored *{}* (level {}) in *{}*.\n{}".format(
            owner, state["score"], state.get("level", 1), seconds_text(state["secs"]), squares)
    else:
        played = "<@{}> had a go and was caught out on the first question.\n{}".format(owner, squares)
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text":
            ":calendar:  *{} Daily*  \u2014  today's set is live".format(name)}},
        {"type": "section", "text": {"type": "mrkdwn", "text": played}},
        _context("Same questions for everyone, one attempt each. *Think you can beat it?*"),
        {"type": "actions", "block_id": "imath_try", "elements": [
            {"type": "button", "action_id": "imath_try", "style": "primary",
             "text": {"type": "plain_text", "text": "Play today's daily"},
             # Anyone may press it, so the value names no one: the clicker is who plays.
             "value": action_value(key, "anyone", 0, "try")},
        ]},
    ]


def announce_daily(game, state):
    """Post the daily nudge to the channel, top level. True only if it was posted."""
    ts, error = slack_post(
        game.token, game.channel,
        "<@{}> played today's {} Daily and scored {}".format(
            game.owner, GAMES[game.key]["name"], state["score"]),
        daily_blocks(game.key, game.owner, state))
    if error:
        game.result["warnings"].append("daily announcement: " + error)
        return False
    game.result["daily_post_ts"] = ts
    return True


def announce_record(game, rec):
    """Post the record to the channel, top level. True only if it was posted."""
    if not rec:
        return False
    game.result["record"] = rec["kind"]
    ts, error = slack_post(game.token, game.channel,
                           record_summary(game.key, game.owner, rec),
                           record_blocks(game.key, game.owner, rec, game.options["banner"]))
    if error:
        game.result["warnings"].append("record announcement: " + error)
        return False
    game.result["record_ts"] = ts
    return True


def finish_game(game, state):
    """Save the run, then replace the question with the closing card."""
    result, table, screen = game.result, game.table, game.screen
    owner, name, channel = game.owner, game.name, game.channel
    score, secs = int(state["score"]), float(state["secs"])
    best_score, best_secs, new_best = score, secs, True
    shared = False
    # A test game saves nothing and tells the channel nothing: no best, no daily row, no
    # record post, no daily nudge. (Its session row is the one thing it must keep: every
    # click is a separate job, and the game lives there.)
    testing = bool(game.options.get("testing"))
    result["testing"] = testing

    if state.get("daily"):
        # Daily results live on their own row and never touch the free-play best.
        if not testing:
            result["saved"] = table.update(state.get("daily_rid"), {
                "status": DAILY_DONE, "current_value": score,
                "total": "{:.1f}".format(secs), "content": share_line(state),
                "updated_at": state["daily"]})
        result["share_line"] = share_line(state)
        new_best, best_score, best_secs = False, 0, 0.0
        # Every finished daily is posted, a 0 included: it tells the channel the set is live.
        if game.options["announce_daily"] and not testing:
            shared = announce_daily(game, state)
    elif testing:
        # Show the standing the player already has, so the card reads true; keep it as is.
        row = table.row_for(user_row_type(game.key, difficulty_of(state)), owner)
        if row and row is not LOOKUP_FAILED:
            best_score, best_secs, _ = best_of(row, 0, 0.0)
        else:
            best_score, best_secs = 0, 0.0
        new_best = False
    else:
        diff = difficulty_of(state)
        user_type = user_row_type(game.key, diff)
        row = table.row_for(user_type, owner)
        # Read the standings BEFORE saving: after the write, this player's new
        # score would be the channel best and there would be nothing to beat.
        board = table.board(user_type) if score > 0 and game.options["announce"] else []
        if row is LOOKUP_FAILED:
            # Writing now would treat a returning player as a first-timer and
            # overwrite their best. Tell them rather than guess.
            result["warnings"].append("player row unreadable; score not saved")
        else:
            best_score, best_secs, new_best = best_of(row, score, secs)
            today = local_today(int(state.get("tz") or DEFAULT_TZ_OFFSET)).isoformat()
            fields = {
                "record_key": "{}_{}".format(user_type, owner),
                "row_type": user_type,
                "id": owner,
                "name": name,
                "current_value": score,
                "personal_best_single_set": best_score,
                "total": "{:.1f}".format(best_secs),
                "total_planks": int((row or {}).get("total_planks") or 0) + 1,
                "slack_channel_id": channel,
                "updated_at": today,
            }
            # A weekly challenge about this game (Easy only), settled in the same write.
            day = local_today(int(state.get("tz") or DEFAULT_TZ_OFFSET))
            cleared = weekly_apply(game, row, fields, score, day) if diff == EASY else []
            # The running total of correct answers, which the leaderboard ranks on. Built on
            # what the weekly step just wrote, so one write carries both.
            points = points_text(fields.get(WEEKLY_COLUMN, (row or {}).get(WEEKLY_COLUMN)),
                                 score, int((row or {}).get("personal_best_single_set") or 0))
            if points is not None:
                fields[WEEKLY_COLUMN] = points
            if row:
                saved = table.update(row.get("$record_id"), fields)
            else:
                fields["first_seen"] = today
                saved, _ = table.create(fields)
            result["saved"] = saved
            if saved and cleared:
                announce_weekly(game, state, cleared, day)
            if saved and game.options["announce"] and board is not LOOKUP_FAILED:
                rec = records_broken(row, board, owner, score, secs)
                if rec:
                    rec["level"] = int(state.get("level") or 1)
                    rec["diff"] = diff
                shared = announce_record(game, rec)

    result["personal_best"] = new_best
    result["best_score"] = best_score
    result["best_seconds"] = best_secs
    # Whether today's daily is still there to offer. A failed read offers it anyway:
    # a button that turns out to be spent says so, a missing one says nothing.
    daily_open = True
    if not state.get("daily") and not testing:
        today = local_today(DAILY_TZ_OFFSET).isoformat()
        played = table.row_by_key(row_type(game.key, "daily"), daily_key(game.key, owner, today))
        daily_open = played is None or played is LOOKUP_FAILED
    # Kept on the session so the same card can be redrawn, buttons off, later.
    state["card"] = {"b": best_score, "s": best_secs, "n": new_best, "sh": shared,
                     "d": daily_open}
    card = over_blocks(state, best_score, best_secs, new_best, shared, daily_open)
    drop_clock(game, state)                  # the game is over: the clock goes, the result stays
    screen.show("{}: game over. Score {}".format(GAMES[game.key]["name"], score),
                card, essential=True)
    return card


def _expire(token, channel, ts, key):
    """Strip the buttons from a message whose game is gone."""
    if token and channel and ts:
        slack_update(token, channel, ts, "{}: game ended".format(GAMES[key]["name"]),
                     expired_blocks(key))


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    token = input.get("slack_bot_token") or ""
    is_click = bool(click_value(input))
    message_ts = str(input.get("message_ts") or "").strip()

    result = {
        "ok": False, "error": "", "warnings": [], "skipped": "",
        "mode": "answer" if is_click else "start",
        "game": "", "variant": "play", "difficulty": "easy", "testing": False,
        "user_id": (input.get("user_id") or "").strip(),
        "user_name": "",
        "channel": (input.get("channel") or "").strip(),
        "message_ts": message_ts,
        "thread_ts": str(input.get("thread_ts") or "").strip() or message_ts,
        "round": 0, "level": 0, "score": 0, "correct": False, "timed_out": False,
        "answer_seconds": 0, "total_seconds": 0, "expression": "", "options": [],
        "correct_answer": None, "shields": 0, "trail": "", "share_line": "",
        "record": "", "record_ts": "", "daily_post_ts": "", "personal_best": False, "best_score": 0,
        "weekly_cleared": [], "weekly_ts": "",
        "best_seconds": 0, "saved": False, "posted_ts": "", "rows_written": 0,
    }

    if not result["user_id"] or not result["channel"]:
        result["error"] = "user_id and channel are both required"
        return result
    if not token:
        result["error"] = "slack_bot_token is required"
        return result

    table = Table(input.get("workato_api_token") or "")

    if is_click:
        answer_game(input, result, table, token)
    else:
        allowed, reason = should_process(input)
        if not allowed:
            result["ok"] = True
            result["skipped"] = reason
            return result
        wanted = detect(input.get("text"))
        if not wanted:
            result["ok"] = True
            result["skipped"] = "no iadd / isub / imultiple / iaverage / idivide keyword"
            return result
        result["game"], result["variant"] = wanted
        if not message_ts:
            result["error"] = "message_ts is required to start a game"
            return result
        start_game(input, result, table, token)

    result["rows_written"] = table.written
    result["warnings"] += table.errors
    return result


if __name__ == "__main__":
    print(json.dumps(main({
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", ""),
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "text": sys.argv[1] if len(sys.argv) > 1 else "iadd",
        "user_id": sys.argv[2] if len(sys.argv) > 2 else "U038ZCDAY6P",
        "channel": os.environ.get("SLACK_CHANNEL", ""),
        "message_ts": "1787580914.789099",
    }), indent=2))
