"""
iMemory -- a short-term memory game played in a Slack thread.

One Python step serves both recipes. Which job it does is decided by the input:
`action_value` present  -> a button was pressed           (ANSWER)
otherwise               -> someone typed the keyword      (START)

The same step also runs iMatch, a pairs game on the keyword `imatch` (see IMATCH below),
and iMemoryImage, iMemory played with emoji pictures, on `imemoryimage` (see IMEMORYIMAGE).

THE GAME
    Round 1 shows one object name, round 2 shows two, and so on up to
    MAX_WORDS. The words stay on screen for SECONDS_PER_WORD each (10 words =
    5 seconds) with a visible countdown, then the message is overwritten with a
    question and Yes/No buttons. Right answer -> score +1 and one more word.

    HOW IT GETS HARD
      * Look-alike extras. A "no" question holds words that never appeared, and
        those are usually in the same CATEGORY as a word that did: the list had
        potato, so the question says cucumber. Recognising "pencil" as new is
        easy; rejecting "cucumber" is not. The share of look-alikes rises each
        round.
      * "Two rounds ago" -- OFF by default, switched on by the recipe input
        look_back=true. From round NBACK_FROM some questions then ask about the
        list from TWO lists back, and their wrong options are words from the
        lists in between. The player has to hold earlier rounds, not just the
        latest one (the n-back task from working-memory research). It is hard
        to meet on a first game, so the game is easier unless it is asked for.
        The setting is saved with the game when it starts and carried into Play
        again, so every screen of a game agrees with the one before.

    THE ANSWER CLOCK
      * Every question has ANSWER_SECONDS to answer, counted down on screen once
        a second. The step that posted the question stays alive for it, checking
        each second whether the player has answered; at zero it settles the
        question as a miss (a shield forgives it, otherwise the game ends).
      * Because that step is still running, the recipe's concurrency must allow
        several jobs at once -- see ANSWER_SECONDS. A click that arrives after
        the deadline is a miss too, even if the step was killed before zero.

    CHANNEL CELEBRATIONS (the way spotter does it)
      * A finished free game that beats the player's own best -- a higher
        score, or the same score in less time -- posts "New personal best" to
        the channel, top level, not in the game thread.
      * One that beats EVERYONE's best posts "New channel record" instead, with
        the banner, who held it before and by how much.
      * Withheld: a player's first scored game (nothing to beat), channel records
        while only one person plays, scores of 0, and daily games.

      * It gets harder as you go. The question grows from 4 words toward 8, a
        wrong option is more often a single impostor among real words, and past
        10 words each word is shown for less time.

    HOW IT KEEPS YOU COMING BACK
      * A visible target. The header says how many answers are needed to beat
        the player's own best, and the moment they pass it the screen says so.
      * A shield. Every SHIELD_EVERY correct answers earns one (held at most
        SHIELD_CAP). A wrong answer burns the shield and the game goes on;
        with no shield, a wrong answer ends the game.
      * `imemory daily`. Everyone gets the SAME words in the same order for the
        day (seeded by the date), one attempt each, and the end card carries a
        copy-and-paste result line of coloured squares, Wordle-style. Daily
        results are kept apart from the free-play best.

RECORD POSTS
    The personal-best and channel-record posts carry a Play iMemory button that ANYONE may
    press (join_in_thread): their rules card lands as a reply in the post's thread, and
    Play again stays there. It does not replace a game of theirs in play. iMatch's posts
    do the same with their own button.

DAILY NUDGE
    When a daily game ends -- whatever the score, a 0 included -- a top-level post invites
    the channel to try it: who played, the score and time, the coloured squares (no words) and a
    "Play today's daily" button. Anyone can press it: they get their own daily rules
    card in a thread of their own (nothing is spent until they press Start): the bot posts
    a root message naming them and the game lives in that thread, as does Play again. Switch the post off with
    announce_daily=false. It is separate from the record posts, which a daily game
    never triggers.

AFTER A GAME
    The result card carries Play again and (while today's daily is unplayed) Today's
    daily. Play again starts a new game at once in a new message in the same thread;
    Today's daily posts the daily rules card. Either one retires the old card: its
    result stays, its buttons go -- as does typing the keyword while it is the
    current card.

WHAT HAPPENS ON EACH PATH
    START   detect `imemory` -> claim the message (retry guard) -> post the
            rules card with a Start button and wait. Nothing is timed, and a
            daily attempt is not spent, until Start is pressed.
    BEGIN   the Start button -> (daily: spend the attempt) -> round 1 in the
            same message: count down, editing it each second -> swap in the
            question + buttons -> save the game state.
    ANSWER  read the game state -> check the click is the owner's, on the live
            message, for the live step -> CLAIM it (status busy, so a double
            click cannot score twice) -> judge it -> flash the result and play
            the next round in the same message, or end the game.

    Buttons are removed the instant a click is accepted, because the message is
    overwritten before anything slow happens. A click that is stale, a repeat,
    or from someone else changes nothing.

    A "step" counts every question asked, including ones a shield forgave, and
    is what a button carries. The round number cannot do that job: after a
    shield saves a miss, the next question is the same round again.

ROWS (workato_governance_unified, tagged by row_type)
    object_memory_user     one per player. Best score, the time of that run,
                           games played, last score. This is the row other
                           memory games will copy: object_memory_user,
                           <something>_memory_user, ...
    object_memory_session  one per player. The game in progress: step, score,
                           the words on screen, the expected answer.
    object_memory_daily    one per player per day (record_key ends in the
                           date). Written when the attempt STARTS, so quitting
                           early to try again with foreknowledge is not an
                           option. Holds the score, time and share line.
    pairs_memory_user      iMatch's copy of object_memory_user.
    pairs_memory_session   iMatch's copy of object_memory_session.

    Column re-use (the table is shared, so these are the nearest fits):
        personal_best_single_set  best score
        total                     time of the best run, seconds, as text "12.4"
        total_planks              games played
        current_value             last game's score
        content (session)         the game state, JSON
        content (daily)           the share line

    "Time" is the sum of the player's thinking time -- from the question
    appearing to the button press, at most MAX_THINK_SECONDS per question --
    not the study countdown, which is fixed by the word count. A better run is
    a higher score, then a lower time. A run with no correct answer is never a
    personal best.

TEST GAMES (input `testing` = yes, on the recipe that starts the game)
    A game that plays normally but saves nothing: no personal best, no games-played count,
    no daily attempt, and no record post or daily nudge in the channel. A test may replay
    today's daily as often as it likes. The game remembers it, so clicks stay tests even if
    the click recipe does not map the input; Play again stays a test too. The one row it
    must write is the in-progress game (session): every click is a separate job and the
    game lives there, so it is overwritten by the player's next game.

IMATCH (the keyword `imatch`) -- a second game in the same step, on the same two recipes
    A pairs game. A board of emoji tiles is shown for a few seconds, then every tile is
    turned over. The player picks a tile, which opens it, then picks its twin. A matched
    pair turns green and scores 1; a wrong pair ends the game (a shield forgives one, and
    one is earned every SHIELD_EVERY pairs, as in iMemory). When one pair is left it fills
    itself in, the board is cleared, and a bigger one is dealt: MATCH_LEVELS runs from
    2x3 to 4x5, and from MATCH_ALIKE_FROM the faces come from one shelf (all fruit, all
    vehicles) so they are harder to tell apart. Score is pairs found; a better run is a
    higher score, then less thinking time. It has the rules card, Start, Play again, the
    targets in the header, personal bests, channel record posts and test games of
    iMemory. It has no daily list and no look-back. The board is shown briefly -- 2
    seconds on the first level, one more on each level after it -- and a game left alone
    for IDLE_SECONDS is closed (see watch_idle).

    EVERY PICK IS ITS OWN JOB, and two picks can be running at once. The rules that keep
    a slow or doubled click from costing the player a game (see match_click, play_pick):
      * Every button carries a fingerprint of the board it was drawn from (match_sig).
        A pick counts only if the table still holds that board. Otherwise it is dropped
        and the board is redrawn from the table, so the screen can never stay wrong.
      * One exception: a pick made one tile early -- both tiles of a pair pressed before
        the first has opened on screen -- counts if it completes the pair. It can only
        help; if it would be a wrong pair it is dropped like any other late pick.
      * A wrong pair is never judged at once. The step waits MISS_SETTLE_SECONDS and reads
        the table again; if the board has moved on (the real twin's click was simply
        slower to arrive), the pick is dropped instead of ending the game.
      * A step that must happen once -- Start, a cleared board, game over, Play again --
        takes the row with a token of its own and reads it back (claim_turn).
      * A board is dealt from the game and the level, not from chance at that moment, so
        two steps that deal the same level deal the same board.

    A record post (personal best or channel record) carries a Play iMatch button that
    ANYONE may press (join_match): their rules card lands as a reply in the post's
    thread, and Play again stays there. It does not replace a game of theirs in play.

    Rows: pairs_memory_user and pairs_memory_session, the same columns as the two
    object_memory rows above. Its bests are its own, and an iMatch game and an iMemory
    game can be in progress for the same player at once.

    DEPLOY: no new inputs. The keyword recipe must let messages containing `imatch`
    reach this step. Every button's action_id starts with `imemory_match_` and its value
    with `imatch|`; a click recipe that filters on action_id must let them through. The
    step that deals a board stays alive while it is shown, and every step that leaves a
    board waiting stays alive too, looking every IDLE_CHECK_SECONDS to see whether the
    player has picked again (IDLE_SECONDS at most). The concurrency note under
    ANSWER_SECONDS applies, and about two such steps per active player overlap.

IMEMORYIMAGE (the keyword `imemoryimage`, or `imemoryimage daily`)
    iMemory exactly -- the same rounds, clock, shields, look-backs, daily, targets, record
    posts and test games -- with emoji pictures in place of words, drawn large (a Slack
    header block). The pictures are iMatch's MATCH_FACES, shelf for shelf, so a "no"
    question's odd one out is usually from the same shelf as one that was shown: a pear
    for an apple. Everything that differs between the two games is in FLAVOURS.

    Rows of its own, so its bests, daily attempt and game in progress never touch
    iMemory's: image_memory_user, image_memory_session, image_memory_daily (the same
    columns as the object_memory rows). A player can have one of each game going at once.

    DEPLOY: no new inputs, and the buttons keep iMemory's action_ids (imemory_start,
    imemory_yes, ...), so the click recipe needs no change: the value says which game, as
    `img|<user>|<step>|<answer>`. The keyword recipe must let messages containing
    `imemoryimage` reach this step (a filter on "imemory" already does). The output's
    `objects` is "words" or "pictures".

Input / output schema: imemory_input_schema.json / imemory_output_schema.json
"""

import copy
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import zlib
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

# --------------------------------------------------------------------------
# Game tuning
# --------------------------------------------------------------------------

TRIGGER = re.compile(r"(?<![A-Za-z0-9_])imemory(?![A-Za-z0-9_])", re.IGNORECASE)
DAILY_TRIGGER = re.compile(
    r"(?<![A-Za-z0-9_])imemory\s+daily(?![A-Za-z0-9_])", re.IGNORECASE)
MATCH_TRIGGER = re.compile(r"(?<![A-Za-z0-9_])imatch(?![A-Za-z0-9_])", re.IGNORECASE)
PICTURES_TRIGGER = re.compile(
    r"(?<![A-Za-z0-9_])imemoryimage(?:\s+(daily))?(?![A-Za-z0-9_])", re.IGNORECASE)

# Said on the rules card of a test game (input `testing` = yes): nothing is saved or posted.
TEST_NOTE = "  \u00b7  :test_tube: Test game: nothing is saved or posted"

ROW_USER = "object_memory_user"
ROW_SESSION = "object_memory_session"
ROW_DAILY = "object_memory_daily"
ROW_MATCH_USER = "pairs_memory_user"
ROW_MATCH_SESSION = "pairs_memory_session"
ROW_IMAGE_USER = "image_memory_user"
ROW_IMAGE_SESSION = "image_memory_session"
ROW_IMAGE_DAILY = "image_memory_daily"

# The daily list changes at midnight in ONE zone, so everyone in the channel
# is on the same list at the same moment. Each player's own timezone is used
# for their personal dates, never for this.
DAILY_TZ_OFFSET = -7 * 3600      # America/Los_Angeles, the channel's zone

# Study time is 0.5s per word, so 10 words = 5 seconds. The floor exists
# because one word at 0.5s would be gone before the message finished loading.
SECONDS_PER_WORD = 0.5
MIN_STUDY_SECONDS = 2
# Past this many words the time per word shrinks, TAPER_PER_WORD a word, down to
# MIN_SECONDS_PER_WORD. Up to here the rule is exactly 0.5s a word.
TAPER_AFTER_WORDS = 10
TAPER_PER_WORD = 0.02
MIN_SECONDS_PER_WORD = 0.25
MAX_WORDS = 20               # the list stops growing here; the game goes on

# How many words a question asks about. It starts at PROBE_START and gains one
# every PROBE_EVERY steps once the game is past PROBE_GROWS_AFTER, up to
# MAX_PROBE. A longer question is harder both ways: a "yes" means checking
# every word, and a "no" hides its odd one out among more real ones. It never
# exceeds the list asked about -- testing every word of a long list is a recital.
PROBE_START = 4
PROBE_GROWS_AFTER = 5
PROBE_EVERY = 2
MAX_PROBE = 8

# A "no" question has some words that were never shown. With many of them the
# question is trivial -- one unfamiliar word is enough to say no -- so they are
# capped at half the question, and the chance of exactly ONE impostor among all
# real words climbs each step until it is certain.
IMPOSTOR_BASE = 0.3
IMPOSTOR_STEP = 0.1

# The live answer clock. After the question appears the SAME Python step stays
# alive, counting down on screen once a second; if nobody has answered by zero
# it settles the question as a miss. 0 turns the live clock off (answers are
# then only timed, never timed out).
#
# DEPLOY NOTE: the step that posts a question now runs for the whole study
# countdown plus this clock -- about 20 seconds at most -- and the click recipe's
# step does the same for the NEXT question. Both recipes must therefore allow
# several jobs at once (Workato: recipe Settings -> Concurrency, 10 or more).
# At concurrency 1 a click queues behind the countdown step that is waiting for
# it, and every question times out.
ANSWER_SECONDS = 10
# A click that Slack stamps this long after the deadline is also a miss, so a
# step that was killed before it could count down cannot give extra time.
CLICK_GRACE_SECONDS = 2
# After a game-over from a click, the card is shown once more this long after.
# The countdown step may have had one edit in flight when the click was claimed,
# and a stale edit landing on top of the card would hide the result for good.
REASSERT_SECONDS = 1.3

# Thinking time counted per question is capped when the live clock is off. The clock runs from the question
# appearing to the click, so a coffee break between rounds would otherwise bury
# a good run under minutes of idle time. At the cap the player is no faster
# than a slow answer, so walking away is never an advantage.
MAX_THINK_SECONDS = 30

FLASH_SECONDS = 1.0          # how long "Correct" stays up before the next list
SHIELD_FLASH_SECONDS = 2.5   # longer: the player needs to read what they got wrong
ZERO_HOLD_SECONDS = 0.6      # how long the countdown rests on 0

# Difficulty. A "no" question's extra word is, in order of preference:
#   a LURE        a word from a list the player has just seen but which is NOT
#                 the list being asked about -- the cruellest wrong answer
#   a LOOK-ALIKE  a word of the same category as a word that WAS in the list
#   a stranger    any other word
LURE_CHANCE = 0.35
LOOKALIKE_BASE = 0.5         # chance an extra is a look-alike in step 1 ...
LOOKALIKE_STEP = 0.1         # ... and how much it grows every step, to 1.0

NBACK_FROM = 4               # first step that may ask about two lists ago
NBACK_CHANCE = 0.3

# Banner shown above a CHANNEL-record announcement (not a personal best).
# Either a URL or a Slack file id (Fxxxxxxxx); overridable per run with the
# `record_banner` input. The same image spotter uses for its channel records.
RECORD_BANNER = ("https://coursera.enterprise.slack.com/files/U038ZCDAY6P/"
                 "F0BT1FETK4K/chatgpt_image_aug_28__2026__12_32_45_am.png")
RECORD_BANNER_ALT = "New channel record"

SHIELD_EVERY = 5             # correct answers per shield earned
SHIELD_CAP = 1               # shields held at once

# iMatch. The boards, one per level: (rows, columns). A row is one Slack actions
# block, so its width is ours to choose. Every board has an even number of
# tiles, which is why there is no 3x3 or 5x3: one tile would have no twin. The
# first board is small on purpose -- a wrong pair ends the game, so a 4x4
# opener would end most first games on the first board.
MATCH_BOARDS = ((2, 3), (2, 4), (2, 5), (3, 4), (4, 4), (4, 5))
# How long a board is shown: this many seconds on level 1, and this many more on
# each level after it. The time stops growing with the last board, because the
# board does.
MATCH_SHOW_FIRST_SECONDS = 2
MATCH_SHOW_STEP_SECONDS = 1
# (rows, columns, seconds shown) for each level.
MATCH_LEVELS = tuple(
    (rows, cols, MATCH_SHOW_FIRST_SECONDS + MATCH_SHOW_STEP_SECONDS * level)
    for level, (rows, cols) in enumerate(MATCH_BOARDS))
# From this level the faces on a board come from as few shelves as possible (all
# fruit, all vehicles), so they are harder to tell apart. Before it, every pair
# on a board is from a different shelf.
MATCH_ALIKE_FROM = 4
MATCH_HIDDEN = "\u2754"           # the face of a tile that is turned over
MATCH_CLEAR_SECONDS = 1.5         # how long "Board cleared" stays up
# A wrong pair is judged only after this pause and a second read of the table.
# The click for the real twin may simply have been slower to arrive; if it has
# landed by then, the board has moved on and the wrong pair is dropped.
MISS_SETTLE_SECONDS = 1.0
# A step that must happen once (Start, a cleared board, game over, Play again)
# writes a token of its own on the row, waits this long and reads it back. Two
# clicks that both found the game free both write; only the later token is still
# there, so only one of them goes on.
CLAIM_SETTLE_SECONDS = 0.3
# A game nobody has pressed a tile in for this long is closed, so it is not left
# open for no one (0 turns it off). The step that left the board waiting looks
# every IDLE_CHECK_SECONDS whether the player has picked again, and stops at the
# first look that finds they have. A pick that still arrives after the deadline
# (that step was cut short) closes the game instead of counting. A rules card is
# not a game in play and is not closed.
IDLE_SECONDS = 20
IDLE_CHECK_SECONDS = 5

SHARE_MAX = 30               # squares shown in the share line before it elides
SQUARES = {"g": "\U0001F7E9", "y": "\U0001F7E8", "r": "\U0001F7E5"}

SESSION_ACTIVE = "active"
SESSION_BUSY = "busy"        # a click is being processed
SESSION_STARTING = "starting"
SESSION_READY = "ready"      # rules card posted, waiting for the Start button
SESSION_OVER = "over"
STARTING_STALE_SECONDS = 60  # a claim older than this with no game is a crashed run

DAILY_PLAYING = "playing"    # claimed; quitting does not give the attempt back
DAILY_DONE = "done"

# Stand-ins so a test can run the whole game in milliseconds.
_sleep = time.sleep
_clock = time.monotonic
_now = time.time
_rng = random.Random()

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
    # read, never written, to find the weekly challenges a player accepted before their first game
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "grant_type": "355e769f-0aa3-46be-bea3-5c2b3442f658",
}

# The API rejects the whole document on one type mismatch, so values are
# coerced to these before sending.
COLUMN_TYPES = {
    "record_key": "string", "row_type": "string", "id": "string",
    "name": "string", "current_value": "string", "content": "string",
    "status": "string", "slack_channel_id": "string", "total": "string",
    "personal_best_single_set": "integer", "total_planks": "integer",
    "first_seen": "date", "updated_at": "date", "last_processed_ts": "string",
    "group_id": "string", "grant_type": "string",
}

LOOKUP_FAILED = object()

# --------------------------------------------------------------------------
# Words -- concrete, common objects, grouped by category. The grouping is what
# makes a wrong answer believable: a "no" can be a word from the same shelf as
# one that was shown. No word appears in two categories and none is a plural
# or synonym of another, so "was it in the list?" always has one answer.
# --------------------------------------------------------------------------

CATEGORIES = {
    "fruit": ("apple", "banana", "lemon", "orange", "pineapple", "pear",
              "cherry", "grape", "peach", "mango", "melon", "plum"),
    "vegetables": ("tomato", "potato", "cucumber", "carrot", "onion", "pepper",
                   "pumpkin", "cabbage", "broccoli", "garlic", "celery",
                   "lettuce", "mushroom"),
    "snacks": ("pizza", "sandwich", "cookie", "peanut", "pretzel", "doughnut"),
    "kitchen": ("spoon", "fork", "kettle", "teapot", "toaster", "plate", "bowl",
                "saucer", "whisk", "ladle", "blender", "colander", "mug", "pan",
                "oven"),
    "tools": ("hammer", "shovel", "ladder", "axe", "saw", "wrench", "drill",
              "pliers", "chisel", "rake", "screwdriver", "needle"),
    "office": ("pencil", "stapler", "eraser", "ruler", "notebook", "scissors",
               "envelope", "marker", "calculator", "folder", "clipboard",
               "stamp"),
    "furniture": ("chair", "table", "sofa", "desk", "stool", "bookshelf",
                  "bench", "wardrobe", "cabinet", "mirror", "bed", "shelf"),
    "lighting": ("lamp", "candle", "lantern", "flashlight", "chandelier",
                 "torch", "bulb"),
    "instruments": ("guitar", "piano", "violin", "flute", "drum", "trumpet",
                    "harp", "cello", "saxophone", "clarinet", "banjo", "tuba"),
    "clothing": ("scarf", "glove", "mitten", "boot", "sweater", "hat", "jacket",
                 "sock", "belt", "coat", "apron", "slipper"),
    "vehicles": ("bicycle", "sailboat", "tractor", "rocket", "canoe", "wagon",
                 "skateboard", "bus", "train", "helicopter", "scooter", "tram"),
    "nature": ("mountain", "cloud", "rainbow", "acorn", "feather", "pebble",
               "cactus", "sunflower", "shell", "volcano", "glacier",
               "waterfall"),
    "buildings": ("castle", "lighthouse", "bridge", "windmill", "pyramid",
                  "igloo", "cabin", "tunnel", "fence", "chimney", "tower",
                  "barn"),
    "soft furnishings": ("pillow", "blanket", "quilt", "curtain", "carpet",
                         "cushion", "hammock", "towel", "rug"),
    "science and navigation": ("compass", "map", "globe", "telescope",
                               "microscope", "magnet", "binoculars",
                               "thermometer", "clock"),
    "toys and sport": ("kite", "balloon", "marble", "puzzle", "trophy",
                       "dumbbell", "racket", "football", "crayon", "whistle",
                       "helmet"),
    "containers": ("bucket", "basket", "bottle", "jar", "backpack", "suitcase",
                   "barrel", "wallet", "thermos", "box", "vase"),
    "accessories": ("glasses", "ring", "crown", "necklace", "bracelet", "watch",
                    "pendant", "lock", "key", "umbrella", "diamond"),
    "household": ("anchor", "bell", "button", "door", "flag", "radio", "rope",
                  "saddle", "window", "wheel", "zipper", "statue", "ticket",
                  "comb", "sponge", "toothbrush", "fountain", "broom"),
}

WORDS = tuple(word for group in CATEGORIES.values() for word in group)
CATEGORY_OF = {word: name for name, group in CATEGORIES.items() for word in group}

# iMatch's tiles, by shelf, for the same reason the words are grouped: faces from
# one shelf are easy to confuse. Every shelf holds at least 10, enough to fill
# the largest board on its own, and no face is on two shelves. They are written
# as escapes so the file stays plain ASCII; Slack draws them as emoji.
MATCH_FACES = {
    # apple, pear, tangerine, lemon, banana, watermelon, grapes, strawberry,
    # cherries, peach, pineapple
    "fruit": ("\U0001F34E", "\U0001F350", "\U0001F34A", "\U0001F34B", "\U0001F34C",
              "\U0001F349", "\U0001F347", "\U0001F353", "\U0001F352", "\U0001F351",
              "\U0001F34D"),
    # dog, cat, mouse, hamster, rabbit, bear, panda, koala, tiger, cow, pig,
    # frog, monkey
    "animals": ("\U0001F436", "\U0001F431", "\U0001F42D", "\U0001F439", "\U0001F430",
                "\U0001F43B", "\U0001F43C", "\U0001F428", "\U0001F42F", "\U0001F42E",
                "\U0001F437", "\U0001F438", "\U0001F435"),
    # car, taxi, bus, ambulance, fire engine, tractor, bicycle, rocket,
    # helicopter, locomotive, truck, sailboat
    "vehicles": ("\U0001F697", "\U0001F695", "\U0001F68C", "\U0001F691", "\U0001F692",
                 "\U0001F69C", "\U0001F6B2", "\U0001F680", "\U0001F681", "\U0001F682",
                 "\U0001F69A", "\u26F5"),
    # football, basketball, american football, baseball, tennis, pool ball,
    # volleyball, rugby ball, bowling, table tennis, dartboard
    "sport": ("\u26BD", "\U0001F3C0", "\U0001F3C8", "\u26BE", "\U0001F3BE",
              "\U0001F3B1", "\U0001F3D0", "\U0001F3C9", "\U0001F3B3", "\U0001F3D3",
              "\U0001F3AF"),
    # pizza, burger, fries, hot dog, taco, doughnut, cookie, birthday cake,
    # ice cream, chocolate, popcorn, cake slice
    "food": ("\U0001F355", "\U0001F354", "\U0001F35F", "\U0001F32D", "\U0001F32E",
             "\U0001F369", "\U0001F36A", "\U0001F382", "\U0001F366", "\U0001F36B",
             "\U0001F37F", "\U0001F370"),
    # sun, moon, star, rainbow, fire, wave, cactus, clover, sunflower,
    # mushroom, fir tree, palm tree
    "nature": ("\U0001F31E", "\U0001F319", "\u2B50", "\U0001F308", "\U0001F525",
               "\U0001F30A", "\U0001F335", "\U0001F340", "\U0001F33B", "\U0001F344",
               "\U0001F332", "\U0001F334"),
    # guitar, keyboard, trumpet, violin, microphone, headphones, saxophone,
    # bell, radio, note
    "music": ("\U0001F3B8", "\U0001F3B9", "\U0001F3BA", "\U0001F3BB", "\U0001F3A4",
              "\U0001F3A7", "\U0001F3B7", "\U0001F514", "\U0001F4FB", "\U0001F3B5"),
    # key, padlock, light bulb, camera, alarm clock, gift, balloon, gem,
    # pushpin, hammer, books, crown, die, torch
    "things": ("\U0001F511", "\U0001F512", "\U0001F4A1", "\U0001F4F7", "\u23F0",
               "\U0001F381", "\U0001F388", "\U0001F48E", "\U0001F4CC", "\U0001F528",
               "\U0001F4DA", "\U0001F451", "\U0001F3B2", "\U0001F526"),
}

# What a memory game is made of: its shelves, each item's shelf, and every item. iMemory
# plays the words; iMemoryImage plays iMatch's emoji, shelf for shelf, so a "no" can be
# a look-alike from the same shelf (a pear for an apple) just as a word can.
WORD_SHELF = (CATEGORIES, CATEGORY_OF, WORDS)
PICTURES = tuple(face for group in MATCH_FACES.values() for face in group)
PICTURE_SHELF = (MATCH_FACES, {face: name for name, group in MATCH_FACES.items()
                               for face in group}, PICTURES)

# The two memory games one step serves on the same buttons: iMemory (words) and
# iMemoryImage (emoji pictures). Everything that differs between them is here. Each has
# rows of its own, so its bests, daily attempt and game in progress are its own; its
# buttons carry `tag` in front of their value, so a click finds the right game.
WORDS_GAME, PICTURES_GAME = "words", "pictures"
FLAVOURS = {
    WORDS_GAME: {"name": "iMemory", "keyword": "imemory", "icon": ":brain:",
                 "user": ROW_USER, "session": ROW_SESSION, "daily": ROW_DAILY,
                 "one": "word", "many": "words", "seed": "imemory", "tag": "",
                 "shelf": WORD_SHELF},
    PICTURES_GAME: {"name": "iMemoryImage", "keyword": "imemoryimage",
                    "icon": ":frame_with_picture:",
                    "user": ROW_IMAGE_USER, "session": ROW_IMAGE_SESSION,
                    "daily": ROW_IMAGE_DAILY,
                    "one": "picture", "many": "pictures", "seed": "imemoryimage",
                    "tag": "img", "shelf": PICTURE_SHELF},
}


def flavour(state_or_name=None):
    """The game a state (or a flavour name) belongs to; a state without one is iMemory."""
    if isinstance(state_or_name, dict):
        state_or_name = PICTURES_GAME if state_or_name.get("pics") else WORDS_GAME
    return FLAVOURS.get(state_or_name or WORDS_GAME, FLAVOURS[WORDS_GAME])



# --------------------------------------------------------------------------
# PURE -- everything between the words and the Slack blocks. No network.
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


def detect(text):
    """'daily', 'play', 'match', or '' -- which game the message is asking for.

    The keyword must stand alone as a word, so "imemorylane" and "my_imemory"
    do not start anything. `imemory daily` wins over a bare `imemory`, and
    `imatch` (the pairs game) is read only when neither is there.
    """
    text = text or ""
    if DAILY_TRIGGER.search(text):
        return "daily"
    if TRIGGER.search(text):
        return "play"
    return "match" if MATCH_TRIGGER.search(text) else ""


def detect_pictures(text):
    """'daily', 'play' or '' for iMemoryImage's keyword: `imemoryimage`, or with `daily`."""
    match = PICTURES_TRIGGER.search(text or "")
    if not match:
        return ""
    return "daily" if match.group(1) else "play"


def word_count_for(round_no):
    return min(max(int(round_no), 1), MAX_WORDS)


def seconds_per_word(word_count):
    over = max(0, int(word_count) - TAPER_AFTER_WORDS)
    return max(MIN_SECONDS_PER_WORD, SECONDS_PER_WORD - TAPER_PER_WORD * over)


def study_seconds(word_count):
    """Whole seconds the list stays up: 0.5s a word up to 10 words, then faster."""
    return max(MIN_STUDY_SECONDS,
               int(math.ceil(word_count * seconds_per_word(word_count))))


def probe_size(step):
    """How many words the question at this step asks about, before the list limit."""
    grown = max(0, step - PROBE_GROWS_AFTER)
    return min(MAX_PROBE, PROBE_START + (grown + PROBE_EVERY - 1) // PROBE_EVERY)


def impostor_chance(step):
    return min(1.0, IMPOSTOR_BASE + IMPOSTOR_STEP * (step - 1))


def lookalike(anchors, taken, rng, shelf=WORD_SHELF):
    """A word that shares a category with one of `anchors`, or None."""
    categories, category_of, _ = shelf
    for anchor in rng.sample(list(anchors), len(anchors)):
        mates = [w for w in categories[category_of[anchor]] if w not in taken]
        if mates:
            return rng.choice(mates)
    return None


def pick_extras(count, target, lures, step, rng, shelf=WORD_SHELF):
    """`count` words that are NOT in `target`, as hard to reject as the step allows."""
    chance = min(1.0, LOOKALIKE_BASE + LOOKALIKE_STEP * (step - 1))
    chosen = []
    for _ in range(count):
        taken = set(target) | set(chosen)
        word = None
        pool = [w for w in lures if w not in taken]
        if pool and rng.random() < LURE_CHANCE:
            word = rng.choice(pool)
        if word is None and rng.random() < chance:
            word = lookalike(target, taken, rng, shelf)
        if word is None:
            word = rng.choice([w for w in shelf[2] if w not in taken])
        chosen.append(word)
    return chosen


def build_round(score, step, history, rng=None, lookback=False, shelf=WORD_SHELF):
    """Pick the list and the question for the next step.

    `history` is the lists shown before this one, newest first. The question is
    about the list just shown; with `lookback` on, from NBACK_FROM it is
    sometimes about the list from two steps back. Either way it is answered "yes" when every
    word in it belongs to the list asked about, and otherwise holds at least
    one that does not -- see pick_extras for how believable that word is.
    """
    rng = rng or _rng
    shown = rng.sample(shelf[2], word_count_for(score + 1))

    kind, target = "recall", shown
    if lookback and step >= NBACK_FROM and len(history) >= 2 and rng.random() < NBACK_CHANCE:
        kind, target = "back", history[1]
    size = min(len(target), probe_size(step))

    if rng.random() < 0.5:
        probe, expect = rng.sample(target, size), "yes"
    else:
        # Words from the lists in between are the lures: the player SAW them,
        # just not in the list being asked about.
        recent = (history[:1] if kind == "recall" else history[:1] + [shown])
        lures = list(dict.fromkeys(w for lst in recent for w in lst
                                   if w not in target))
        if rng.random() < impostor_chance(step):
            extras = 1
        else:
            extras = rng.randint(1, max(1, size // 2))
        probe = rng.sample(target, size - extras) + \
            pick_extras(extras, target, lures, step, rng, shelf)
        rng.shuffle(probe)
        expect = "no"
    return {"shown": shown, "probe": probe, "expect": expect, "kind": kind}


def target_of(state):
    """The list the current question is about."""
    if state.get("kind") == "back":
        return (state.get("history") or [[], []])[1]
    return state["shown"]


def value_flavour(value):
    """Which memory game a button belongs to: iMemoryImage's values start `img|`."""
    tag = FLAVOURS[PICTURES_GAME]["tag"] + "|"
    return PICTURES_GAME if str(value or "").startswith(tag) else WORDS_GAME


def parse_action(value):
    """'[img|]<owner>|<step>|<yes|no|start|again|daily|try|play|join>' -> (owner, step,
    answer), or None. The `img|` in front (iMemoryImage's) is read by value_flavour."""
    value = str(value or "")
    if value_flavour(value) == PICTURES_GAME:
        value = value[len(FLAVOURS[PICTURES_GAME]["tag"]) + 1:]
    parts = value.split("|")
    if len(parts) != 3 or parts[2] not in ("yes", "no", "start", "again", "daily", "try", "play",
                                           "join"):
        return None
    try:
        return parts[0], int(parts[1]), parts[2]
    except ValueError:
        return None


def action_value(owner, step, answer, flav=None):
    tag = flavour(flav)["tag"] if flav else ""
    return "{}{}|{}|{}".format(tag + "|" if tag else "", owner, step, answer)


def share_line(state):
    """The copy-and-paste result: green right, yellow shield-saved, red out."""
    trail = state.get("trail") or ""
    squares = "".join(SQUARES[c] for c in trail[-SHARE_MAX:])
    if len(trail) > SHARE_MAX:
        squares = "\u2026" + squares
    return "{} Daily {} \u00b7 {} correct \u00b7 {}\n{}".format(
        flavour(state)["name"], state.get("daily") or "", state.get("score", 0),
        seconds_text(state.get("secs")), squares)


def daily_rng(day, step, flav=None):
    """The same generator for every player on the same day and step."""
    return random.Random("{}:{}:{}".format(flavour(flav)["seed"], day, step))


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


def margin_text(score, secs, prev_score, prev_secs, unit="correct answer"):
    """How far past the previous mark: more answers, or the same score faster."""
    if score > prev_score:
        gain = score - prev_score
        return "beaten by {} more {}{}".format(gain, unit, "" if gain == 1 else "s")
    return "same score, {} faster".format(seconds_text(prev_secs - secs))


def memory_record_detail(owner, rec, flav=None):
    """What a memory record says it was: "lists of up to 7 words" (or pictures)."""
    game = flavour(flav)
    return ("<@{}> scored *{}* in *{}* \u2014 lists of up to *{}* {}, "
            "in *{}* of thinking time.").format(
        owner, rec["score"], game["name"], word_count_for(rec["score"]), game["many"],
        seconds_text(rec["secs"]))


def record_blocks(owner, rec, banner="", game_name="iMemory", detail="",
                  unit="correct answer", join=None):
    """The channel post for a record. `game_name`, `detail`, `unit` and `join` are for
    iMatch, which says what was scored in its own words and puts a play button under
    it (`join` is that button's element); iMemory passes none of them."""
    channel = rec["kind"] == "channel"
    prev_score, prev_secs = rec["previous"]
    title = ":crown:  *New channel record*" if channel else ":trophy:  *New personal best*"
    detail = detail or memory_record_detail(owner, rec)
    detail += "\nPrevious {} *{}* in {} \u2014 {}.".format(
        "record" if channel else "best", prev_score, seconds_text(prev_secs),
        margin_text(rec["score"], rec["secs"], prev_score, prev_secs, unit))

    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": title}},
              {"type": "section", "text": {"type": "mrkdwn", "text": detail}}]
    notes = []
    if channel:
        if rec["holder_id"] == owner:
            notes.append("Their own record until now.")
        elif rec["holder_name"]:
            notes.append("Held by {} until now.".format(rec["holder_name"]))
        notes.append("{} people play {}.".format(rec["people"], game_name))
    if notes:
        blocks.append(_context(" ".join(notes)))
    if join:
        blocks.append({"type": "actions", "block_id": "imemory_record_join",
                       "elements": [join]})
    if channel and banner:
        ref = str(banner).strip()
        image = ({"type": "image", "image_url": ref, "alt_text": RECORD_BANNER_ALT}
                 if ref.startswith(("http://", "https://"))
                 else {"type": "image", "slack_file": {"id": ref},
                       "alt_text": RECORD_BANNER_ALT})
        blocks.insert(0, image)
    return blocks


def record_summary(owner, rec, game_name="iMemory"):
    return "<@{}> set a new {} in {}".format(
        owner, "channel record" if rec["kind"] == "channel" else "personal best", game_name)


def judge(expect, answer):
    return expect == answer


def load_state(row):
    try:
        state = json.loads((row or {}).get("content") or "{}")
    except (TypeError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def local_today(tz_offset, now_utc=None):
    now = now_utc or datetime.now(timezone.utc)
    return (now + timedelta(seconds=tz_offset)).date()


# --------------------------------------------------------------------------
# PURE -- Block Kit
# --------------------------------------------------------------------------

def _words_line(words):
    return "   ".join("*{}*".format(w) for w in words)


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


def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


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


def channel_target(table, user_row_type, owner, warnings):
    """The channel best to chase, read once when a game starts. {} if unreadable or no rivals."""
    board = table.board(user_row_type)
    if board is LOOKUP_FAILED:
        warnings.append("channel best unreadable; no channel target shown")
        return {}
    return channel_best_of(board, owner)


def next_above(board, owner, best):
    """The player just above `best` on the board: {"score", "name"}, or {} when there is
    nobody (or the player has no best yet: then the only target is the channel's).

    "Just above" is the lowest score over `best`; among equal scores, the slower run,
    which is the one standing directly over the player on the leaderboard. iMatch only:
    iMemory keeps no "next" on its game, so nothing below changes for it."""
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
    """What to beat right now: your own best, then (iMatch) the person above you, then
    the channel's, then nothing left.

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
    """The same ladder, as lines for the rules card -- iMath's: your best, the channel's."""
    best, chan = int(state.get("best") or 0), state.get("chan") or {}
    lines = []
    if best:
        lines.append(":trophy: Your best: *{}*".format(best))
    if chan.get("score"):
        lines.append(":crown: Channel best: *{}* by *{}*".format(
            chan["score"], chan.get("name") or "?"))
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


def _title(state):
    """':brain: *iMemory*', ':frame_with_picture: *iMemoryImage* Daily' -- the game's name."""
    game = flavour(state)
    return "{} *{}*{}".format(game["icon"], game["name"], " Daily" if state.get("daily") else "")


def _header(state):
    title = _title(state)
    parts = [title, "Round {}".format(state["step"]), "Score {}".format(state["score"])]
    if state.get("shields"):
        parts.append(":shield: Shield ready")
    note = target_text(state)
    if note:
        parts.append(note)
    return _context("  \u00b7  ".join(parts))


def intro_blocks(state, owner):
    """The rules and a Start button. Nothing is timed until it is pressed.

    Short, as iMath's is: three lines of rules, then the targets (or the daily's one
    attempt) in a section of their own, so Slack never folds anything behind "Show more"."""
    game = flavour(state)
    clock = " within *{}s*".format(ANSWER_SECONDS) if ANSWER_SECONDS else ""
    grows = "Each correct answer adds one more {}.".format(game["one"])
    if state.get("lookback"):
        grows += " Some questions ask about the list from *two rounds ago* (:rewind:)."
    rules = [
        "A list of {} shows for a few seconds. Then answer Yes or No about it{}.".format(
            game["many"], clock),
        grows,
        "A wrong answer ends it. Every *{}* correct earns a :shield: shield that forgives "
        "one miss.".format(SHIELD_EVERY),
    ]
    blocks = [
        _context(_title(state) + TEST_NOTE * bool(state.get("test"))),
        _section("\n".join("\u2022 " + r for r in rules)),
    ]
    if state.get("daily"):
        blocks.append(_section(":calendar: *Same list for everyone, one attempt.* It counts "
                               "from the moment you press Start."))
    elif target_intro(state):
        blocks.append(_section(target_intro(state)))
    blocks.append(
        {"type": "actions", "block_id": "imemory_intro", "elements": [
            {"type": "button", "action_id": "imemory_start", "style": "primary",
             "text": {"type": "plain_text", "text": "Start game"},
             "value": action_value(owner, 0, "start", flavour_name(state))},
        ]})
    return blocks


def flavour_name(state):
    return PICTURES_GAME if (state or {}).get("pics") else WORDS_GAME


def _items(state, items):
    """Words in bold on one line; pictures as a large heading of their own, where the
    emoji are big enough to tell apart at a glance."""
    if state.get("pics"):
        return {"type": "header", "text": {"type": "plain_text", "emoji": True,
                                           "text": "   ".join(items)}}
    return None


def study_blocks(state, remaining):
    words, game = state["shown"], flavour(state)
    plural = game["one"] if len(words) == 1 else game["many"]
    big = _items(state, words)
    if big:
        body = [_section("*Memorise {} {}*".format(len(words), plural)), big]
    else:
        body = [_section("*Memorise {} {}*\n\n{}".format(len(words), plural, _words_line(words)))]
    return [_header(state)] + body + [
        _context(":hourglass_flowing_sand: Hiding in *{}*".format(remaining))]


def question_text(state):
    probe = state["probe"]
    if state.get("pics"):
        # The pictures go in a heading of their own (see question_blocks): this is the ask.
        where = "that list" if state.get("kind") == "back" else "the list"
        lead = (":rewind: *Look back \u2014 the list from two rounds ago* (round {})\n".format(
            state["step"] - 2) if state.get("kind") == "back" else "")
        if len(probe) == 1:
            return lead + "Was this in {}?".format(where)
        return lead + "Were *all* of these in {}?".format(where)
    if state.get("kind") == "back":
        # A look-back is NOT about the list just shown, so it says so first, on a line
        # of its own, with the round number to find it by.
        lead = ":rewind: *Look back \u2014 the list from two rounds ago* (round {})\n".format(
            state["step"] - 2)
        if len(probe) == 1:
            return lead + "Was *{}* in that list?".format(probe[0])
        return lead + "Were *all* of these in that list?\n\n{}".format(_words_line(probe))
    if len(probe) == 1:
        return "Was *{}* in the list?".format(probe[0])
    return "Were *all* of these in the list?\n\n{}".format(_words_line(probe))


def question_blocks(state, owner, remaining=None):
    clock = [_context(":stopwatch: *{}s* to answer".format(remaining))] \
        if remaining is not None else []
    big = _items(state, state["probe"])
    flav = flavour_name(state)
    return [
        _header(state),
        {"type": "section", "text": {"type": "mrkdwn", "text": question_text(state)}}
    ] + ([big] if big else []) + clock + [
        {"type": "actions", "block_id": "imemory_q{}".format(state["step"]), "elements": [
            {"type": "button", "action_id": "imemory_yes", "style": "primary",
             "text": {"type": "plain_text", "text": "Yes"},
             "value": action_value(owner, state["step"], "yes", flav)},
            {"type": "button", "action_id": "imemory_no",
             "text": {"type": "plain_text", "text": "No"},
             "value": action_value(owner, state["step"], "no", flav)},
        ]},
    ]


def flash_blocks(state, lines):
    return [_header(state),
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}}]


def correct_lines(state, new_shield, passed_best, passed_channel=False):
    return [":white_check_mark: *Correct*  \u2014  the next list has one more {}.".format(
        flavour(state)["one"])] + \
        bonus_lines(state, new_shield, passed_best, passed_channel)


def bonus_lines(state, new_shield, passed_best, passed_channel=False, passed_near=False):
    """What a right answer brought with it, if anything: a best passed, a shield earned."""
    lines = []
    if passed_best:
        lines.append(":trophy: *New personal best* \u2014 you have passed your record. Keep going.")
    if passed_near:
        lines.append(":dart: *Passed {}* \u2014 keep going.".format(
            (state.get("next") or {}).get("name") or "them"))
    if passed_channel:
        lines.append(":crown: *Channel best passed* \u2014 {}'s {}. Keep going.".format(
            (state.get("chan") or {}).get("name") or "the leader", (state.get("chan") or {}).get("score")))
    if new_shield:
        lines.append(":shield: *Shield earned* \u2014 it will forgive your next miss.")
    return lines


def shield_lines(state):
    why = "time ran out" if not state.get("answered") else "that answer was wrong"
    return [":shield: *Shield used*  \u2014  {} (it was {}). You are still in.".format(
        why, state["expect"].upper())]


def play_again_actions(owner, step, daily_open, flav=None):
    """Play again, and today's daily while it is still unplayed."""
    elements = [{"type": "button", "action_id": "imemory_again", "style": "primary",
                 "text": {"type": "plain_text", "text": "Play again"},
                 "value": action_value(owner, step, "again", flav)}]
    if daily_open:
        elements.append({"type": "button", "action_id": "imemory_daily",
                         "text": {"type": "plain_text", "text": "Today's daily"},
                         "value": action_value(owner, step, "daily", flav)})
    return {"type": "actions", "block_id": "imemory_over", "elements": elements}


def _chips(words):
    """Words as inline code, which Slack draws as tidy, evenly spaced chips."""
    return "  ".join("`{}`".format(w) for w in words)


def over_blocks(state, best_score, best_secs, new_best, shared=False,
                daily_open=True, buttons=True):
    """The closing card: what happened, which words were right, the list, the numbers.

    Three groups of lines with a blank line between them -- the headline, the verdict
    with a mark against each word asked about, and the list -- then the numbers.

    `buttons=False` is the same card after the player has moved on: the result
    stays, the buttons go.
    """
    back = state.get("kind") == "back"
    target = set(target_of(state))
    marked = "   ".join(
        "{} {}".format(":white_check_mark:" if w in target else ":x:", w)
        for w in state["probe"])

    if state.get("answered"):
        headline = ":x: *Game over*  \u2014  you answered {}, the answer was {}.".format(
            state["answered"].upper(), state["expect"].upper())
    else:
        headline = ":hourglass: *Time's up*  \u2014  the answer was {}.".format(state["expect"].upper())

    words = target_of(state)
    if back:
        # A look-back asks about an OLDER list than the one just shown, so the card says
        # so, names the round, and shows both lists.
        ago = state["step"] - 2
        said = ("_This was a look-back question: it asked about the list from two rounds "
                "ago (round {}), not the list you had just seen._".format(ago))
        verdict = ("_Every {} was in that list._".format(flavour(state)["one"])
                   if state["expect"] == "yes"
                   else "_At least one of those was not in that list._")
        verdict_group = "\n".join([said, verdict, marked])
        list_group = "\n".join([
            "*The list from two rounds ago (round {}) was:* {}".format(ago, ", ".join(words)),
            "*The list you had just seen (round {}) was:* {}".format(
                state["step"], ", ".join(state["shown"]))])
    else:
        verdict = ("Every {} was in the list.".format(flavour(state)["one"])
                   if state["expect"] == "yes"
                   else "At least one of those was not in the list.")
        verdict_group = "\n".join(["_{}_".format(verdict), marked])
        list_group = "*The list was:* {}".format(", ".join(words))

    result = "*Score:* {}   \u00b7   *Time:* {}".format(
        state["score"], seconds_text(state["secs"]))
    # Buttons need the owner's id (they carry it). A game started before the
    # buttons existed has none stored, and falls back to the typed instruction.
    owner = state.get("owner")
    if state.get("daily"):
        footer = [{"type": "section", "text": {"type": "mrkdwn", "text":
                   "*Share your result*\n```{}```".format(share_line(state))}},
                  _context(("Posted to the channel.  " if shared else "") +
                           "Everyone gets the same list today. A new one tomorrow.")]
        daily_open = False                      # the day's attempt is spent
    else:
        if new_best:
            result += "   \u00b7   :trophy: *New personal best*"
        elif best_score:
            result += "   \u00b7   Best: {} in {}".format(best_score, seconds_text(best_secs))
        else:
            result += "   \u00b7   Get one right to set a personal best"
        footer = [_context(":tada: Shared with the channel.")] if shared else []

    if state.get("test"):
        footer.append(_context(":test_tube: Test game: this result was not saved."))
    if not buttons:
        footer.append(_context(":arrow_forward: A new game has started."))
    elif owner:
        footer.append(play_again_actions(owner, state["step"], daily_open, flavour_name(state)))
    else:
        footer.append(_context("Type `{0}` to play again, or `{0} daily` for today's shared "
                               "list.".format(flavour(state)["keyword"])))
    return [
        _context("{}  \u00b7  Round {}".format(_title(state), state["step"])),
        {"type": "section", "text": {"type": "mrkdwn", "text":
            "\n\n".join([headline, verdict_group, list_group])}},
        {"type": "section", "text": {"type": "mrkdwn", "text": result}},
    ] + footer


def already_played_blocks(day, row, flav=None):
    done = (row or {}).get("status") == DAILY_DONE
    text = "{}  \u2014  you have already played today's list ({}).".format(
        _title({"pics": flav == PICTURES_GAME, "daily": day}), day)
    if done:
        text += "\n```{}```".format((row or {}).get("content") or "")
    else:
        text += "\nThat attempt was started and not finished, so it counts. A new list tomorrow."
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def daily_ended_blocks(flav=None):
    game = flavour(flav)
    return [_context("{} This daily list has ended. Type `{} daily` for today's.".format(
        game["icon"], game["keyword"]))]


def expired_blocks(flav=None):
    game = flavour(flav)
    return [{"type": "context", "elements": [{"type": "mrkdwn", "text":
        "{} This {} game has ended. Type `{}` to start a new one.".format(
            game["icon"], game["name"], game["keyword"])}]}]


# --------------------------------------------------------------------------
# Weekly challenges (weekly_challenge/weekly_challenge.py posts them; these games settle the ones
# about themselves). A player who presses Accept on "Play iMemory 5 times" or "Reach 8 in iMemory"
# gets an entry in the `content` column of their player row (object_memory_user for iMemory,
# pairs_memory_user for iMatch, image_memory_user for iMemoryImage), and the first free game that
# clears it says so. The entry and the news are written with the game's own save (save_run), so
# nothing is said twice. Daily games and test games do not count.
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


# the weekly challenge key of each player row (the key is also the prefix of its two challenges)
WEEKLY_GAME_OF_ROW = {ROW_USER: "imemory", ROW_MATCH_USER: "imatch", ROW_IMAGE_USER: "imemoryimage"}


def weekly_apply(game, user_type, row, fields, score, day):
    """Set a finished free game against the weekly challenges its player accepted.

    Adds `content` to `fields` (the write that saves the game) when anything changes, and
    returns the entries this game cleared. Never allowed to hold up the save itself."""
    name = WEEKLY_GAME_OF_ROW.get(user_type)
    if not name:
        return []
    try:
        waiting = [] if row else game.table.weekly_pending(
            game.owner, [name + "_plays", name + "_score"], day)
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


def announce_weekly(game, cleared, day):
    """Tell the room a weekly challenge was cleared: the channel (the default), the game's own
    thread, or nobody (input announce_weekly). `day` is the player's today. Returns True only if
    it was posted."""
    game.result["weekly_cleared"] = [e.get("text") or "" for e in cleared]
    place = weekly_place(game.options.get("weekly"))
    if not place:
        return False
    text, blocks = weekly_post(game, cleared, day)
    ts, error = slack_post(game.token, game.channel, text, blocks,
                           thread_ts=(getattr(game.screen, "thread_ts", None)
                                      if place == "thread" else None))
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
        (they had never finished a game of this kind), still in their week. Read only when a
        first game is about to create that row; whatever cannot be read is simply not there."""
        out = []
        rows = self._query({"where": {"$and": [
            {"row_type": {"$eq": WEEKLY_ACCEPT_ROW}}, {"group_id": {"$eq": owner}}]},
            "limit": 50})
        if rows is LOOKUP_FAILED:
            return out
        for row in rows:
            if row.get("grant_type") not in keys:
                continue
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


# --------------------------------------------------------------------------
# One round, on screen
# --------------------------------------------------------------------------

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


class Game(object):
    """What one running step needs to move a game along."""

    def __init__(self, table, token, result, channel, owner, name, record_id,
                 trigger_ts, screen, options=None, session_type=ROW_SESSION):
        self.table = table
        self.token = token
        self.result = result
        self.channel = channel
        self.owner = owner
        self.name = name
        self.record_id = record_id
        self.trigger_ts = trigger_ts
        self.screen = screen
        self.session_type = session_type     # iMatch keeps its game on a row of its own
        self.q_clock = 0.0       # _clock() at the moment the live question was stamped
        # Recipe switches that outlive a single click: whether to announce
        # records in the channel, and the banner image for a channel record.
        self.options = options or {"announce": True, "announce_daily": True,
                                    "banner": RECORD_BANNER, "testing": False}

    def write(self, status, state, ts):
        state["ts"] = ts
        return self.table.update(self.record_id, _session_fields(
            self.owner, self.name, self.channel, status, state, self.trigger_ts,
            self.session_type))


def play_round(game, state):
    """Show the list, count down, then ask. Mutates and returns `state`.

    The countdown ticks on a fixed schedule from the first render -- sleeping a
    flat second per tick would stretch every tick by the Slack round-trip, and
    10 words would take 7 seconds instead of 5.
    """
    screen = game.screen
    # The list that was on screen is now history, newest first, two deep.
    if state.get("shown"):
        state["history"] = ([state["shown"]] + (state.get("history") or []))[:2]
    state["step"] = int(state.get("step") or 0) + 1

    game_kind = flavour(state)
    rng = daily_rng(state["daily"], state["step"], flavour_name(state)) if state.get("daily") else _rng
    plan = build_round(state["score"], state["step"], state.get("history") or [], rng,
                       lookback=bool(state.get("lookback")), shelf=game_kind["shelf"])
    state.update(plan)
    state["answered"] = ""

    seconds = study_seconds(len(plan["shown"]))
    started = _clock()
    screen.show("{}: memorise {}".format(game_kind["name"], ", ".join(plan["shown"])),
                study_blocks(state, seconds))

    for remaining in range(seconds - 1, -1, -1):
        wait = started + (seconds - remaining) - _clock()
        if wait > 0:
            _sleep(wait)
        screen.show("{}: hiding in {}".format(game_kind["name"], remaining),
                    study_blocks(state, remaining))
    _sleep(ZERO_HOLD_SECONDS)

    # State is written BEFORE the buttons appear, so a click can never arrive
    # for a question the table does not know about.
    state["q_at"] = _now()
    game.q_clock = _clock()
    game.write(SESSION_ACTIVE, state, screen.ts)
    previous_ts = screen.ts
    screen.show("{}: a memory question".format(game_kind["name"]),
                question_blocks(state, game.owner, ANSWER_SECONDS or None),
                essential=True)
    if screen.ts != previous_ts:           # the question went out as a new post
        game.write(SESSION_ACTIVE, state, screen.ts)
    return state


def watch_question(game, state):
    """Count the answer clock down on screen, and settle the question at zero.

    Runs in the step that posted the question, while the player's click runs in
    a different job. So each second it first asks the table whether this
    question is still the live one -- if the player answered, or the game moved
    on, there is nothing left to watch and it stops without touching the
    message. At zero it claims the question exactly the way a click does, so
    the two can never both settle it.
    """
    if not ANSWER_SECONDS:
        return
    step, ts = state["step"], game.screen.ts
    for remaining in range(ANSWER_SECONDS - 1, -1, -1):
        wait = game.q_clock + (ANSWER_SECONDS - remaining) - _clock()
        if wait > 0:
            _sleep(wait)
        row = game.table.row_for(game.session_type, game.owner)
        if row is LOOKUP_FAILED:
            continue          # cannot tell; the click-time deadline still holds
        live = load_state(row) if row else {}
        if (not row or row.get("status") != SESSION_ACTIVE
                or live.get("step") != step or live.get("ts") != ts):
            return            # answered, replaced or over: not ours any more
        if remaining:
            game.screen.show("{}: a memory question".format(flavour(state)["name"]),
                             question_blocks(state, game.owner, remaining))
            continue
        if not game.table.update(game.record_id, {"status": SESSION_BUSY}):
            return
        settle(game, state, "", float(ANSWER_SECONDS))


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def _session_fields(owner, name, channel, status, state, trigger_ts, row_type=ROW_SESSION):
    return {
        "record_key": "{}_{}".format(row_type, owner),
        "row_type": row_type,
        "id": owner,
        "name": name,
        "status": status,
        "slack_channel_id": channel,
        "last_processed_ts": str(trigger_ts),
        "content": json.dumps(state, separators=(",", ":")),
    }


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


def daily_key(owner, day, row_type=ROW_DAILY):
    return "{}_{}_{}".format(row_type, owner, day)


def fresh_state(owner, name, tz_offset, channel, thread_ts, best, day, lined=False, chan=None,
                lookback=False, test=False, pics=False):
    return {"v": 2, "owner": owner, "step": 0, "score": 0, "secs": 0.0, "pics": bool(pics),
            "channel": channel, "thread_ts": thread_ts, "ts": "", "name": name,
            "tz": tz_offset, "started": _now(), "best": best,
            "shields": 0, "trail": "", "history": [], "daily": day, "lined": lined,
            "chan": chan or {}, "lookback": bool(lookback), "test": bool(test)}


def open_rules_card(result, table, token, record_id, state, name, trigger_ts,
                    blocks=None, row_type=ROW_SESSION):
    """Post the rules card and wait for Start. True when the game is ready.

    `blocks` and `row_type` are iMatch's: its own card, saved on its own row.
    """
    owner, channel, thread_ts = state["owner"], state["channel"], state["thread_ts"]
    screen = Screen(token, channel, "", thread_ts, result["warnings"], lined=state.get("lined"))
    try:
        screen.show("{}: ready to start".format(flavour(state)["name"]) if blocks is None
                    else "iMatch: ready to start",
                    intro_blocks(state, owner) if blocks is None else blocks)
    except RuntimeError as error:
        result["error"] = str(error)
        return False
    state["ts"] = screen.ts
    if not table.update(record_id, _session_fields(
            owner, name, channel, SESSION_READY, state, trigger_ts, row_type)):
        # A card whose button the table would reject is worse than no card.
        slack_delete(token, channel, screen.ts)
        result["error"] = "could not save the game; nothing started"
        return False
    result["ok"] = True
    result["posted_ts"] = screen.ts
    return True


def claim_row(result, table, session, claim):
    """Write the claim for a typed keyword on the player's session row. Its record id, or "".

    Claim before posting: a Slack retry of this same message now finds
    last_processed_ts and stops, instead of starting a second game.
    """
    if session:
        record_id = session.get("$record_id")
        if not table.update(record_id, claim):
            result["error"] = "could not claim the game row"
            return ""
        return record_id
    created, record_id = table.create(
        claim, find=lambda: table.row_for(claim["row_type"], claim["id"]))
    if not created:
        result["error"] = "could not create the game row"
    elif not record_id:
        result["error"] = ("the game row was created but its id could not be read "
                           "back; nothing started")
    return record_id


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
                        "{}: game over".format(flavour(state)["name"]), blocks) or ""


def start_game(input, result, table, token, origin="", flav=WORDS_GAME):
    """Keyword typed (or the nudge's button): claim the message, then post the rules card.

    `origin` is the ts of the channel post whose button started this game, if any.
    `flav` is which memory game: iMemory's words or iMemoryImage's pictures.
    """
    game = flavour(flav)
    result["objects"] = flav
    user_id = result["user_id"]
    channel = result["channel"]
    message_ts = result["message_ts"]
    thread_ts = result["thread_ts"]
    daily = result["game"] == "daily"
    day = local_today(DAILY_TZ_OFFSET).isoformat() if daily else ""
    testing = is_testing(input)
    result["testing"] = testing

    session = table.row_for(game["session"], user_id)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the game table; nothing started"
        return
    if session and is_duplicate(session, message_ts):
        result["ok"] = True
        result["skipped"] = "duplicate delivery of this message"
        return

    if daily and not testing:         # a test game may replay today's list as often as it likes
        played = table.row_by_key(game["daily"], daily_key(user_id, day, game["daily"]))
        if played is LOOKUP_FAILED:
            result["error"] = "could not read the game table; nothing started"
            return
        if played:
            slack_post(token, channel, "{} Daily: already played today".format(game["name"]),
                       already_played_blocks(day, played, flav), thread_ts=thread_ts)
            result["ok"] = True
            result["skipped"] = "today's daily list was already played"
            return

    who = slack_user(token, user_id)
    name = who["real_name"] or user_id
    result["user_name"] = name

    # The target to beat. A failed read just means no target is shown; it must
    # not stop the game.
    best = 0
    if not daily:
        row = table.row_for(game["user"], user_id)
        if row is LOOKUP_FAILED:
            result["warnings"].append("best score unreadable; no target shown")
        elif row:
            best = int(row.get("personal_best_single_set") or 0)
    chan = {} if daily else channel_target(table, game["user"], user_id, result["warnings"])

    state = fresh_state(user_id, name, who["tz_offset"], channel, thread_ts, best, day, chan=chan,
                        lookback=_enabled(input.get("look_back")), test=testing,
                        pics=flav == PICTURES_GAME)
    state["origin"] = origin

    # The last game's result card keeps its result but loses its buttons: there is
    # a new game now, and "Play again" on the old card would start a second one.
    if session and session.get("status") == SESSION_OVER:
        error = retire_card(token, channel, load_state(session))
        if error:
            result["warnings"].append("old card: " + error)

    record_id = claim_row(result, table, session, _session_fields(
        user_id, name, channel, SESSION_STARTING, state, message_ts, game["session"]))
    if not record_id:
        return

    # The rules card. Nothing is timed and, for the daily list, no attempt is
    # spent until the player presses Start: reading the rules is not play.
    open_rules_card(result, table, token, record_id, state, name, message_ts,
                    row_type=game["session"])


def begin_game(game, state):
    """The Start button: spend the daily attempt if there is one, then play round 1."""
    result, table, screen = game.result, game.table, game.screen
    result["mode"] = "begin"

    def give_the_button_back(message):
        table.update(game.record_id, {"status": SESSION_READY})
        result["error"] = message

    day = state.get("daily")
    kind = flavour(state)
    if day:
        testing = game.options.get("testing")
        played = None if testing else table.row_by_key(
            kind["daily"], daily_key(game.owner, day, kind["daily"]))
        if played is LOOKUP_FAILED:
            give_the_button_back("could not read the game table; press Start again")
            return
        if day != local_today(DAILY_TZ_OFFSET).isoformat() or played:
            # The list went stale overnight, or the attempt was already used from
            # another card. Say so on this card and close the session.
            screen.show("{} Daily: not available".format(kind["name"]),
                        already_played_blocks(day, played, flavour_name(state)) if played
                        else daily_ended_blocks(flavour_name(state)))
            table.update(game.record_id, {"status": SESSION_OVER})
            result["ok"] = True
            result["skipped"] = ("today's daily list was already played" if played
                                 else "this daily list has ended")
            return
        # The attempt is spent the moment the list is on screen -- unless this is a test
        # game, which spends nothing.
        state["daily_rid"] = ""
        if not testing:
            created, state["daily_rid"] = table.create({
                "record_key": daily_key(game.owner, day, kind["daily"]),
                "row_type": kind["daily"],
                "id": game.owner, "name": game.name, "status": DAILY_PLAYING,
                "current_value": 0, "updated_at": day, "slack_channel_id": game.channel,
                "last_processed_ts": game.trigger_ts},
                find=lambda: table.row_by_key(kind["daily"],
                                              daily_key(game.owner, day, kind["daily"])))
            if not created or not state["daily_rid"]:
                give_the_button_back("could not record today's attempt; press Start again")
                return

    state["started"] = _now()
    try:
        play_round(game, state)
    except RuntimeError as error:
        table.update(game.record_id, {"status": SESSION_OVER})
        result["error"] = str(error)
        return
    result["ok"] = True
    report_round(result, state)
    result["posted_ts"] = screen.ts
    watch_question(game, state)         # holds the step open until answered or timed out


def _enabled(value):
    """A recipe switch that is OFF unless it says so (the opposite default to _switch)."""
    return str(value or "").strip().lower() in ("true", "1", "yes", "on")


def _switch(value):
    """A recipe switch that is on unless it says otherwise."""
    return str(value or "").strip().lower() not in ("false", "0", "no")


def is_testing(input, state=None):
    """A test game: the `testing` input says yes, or the game was started as one.

    The game remembers it (state["test"]), so only the recipe that starts a game has to
    map the input; a click on a test game stays a test even if its recipe does not."""
    return _enabled(input.get("testing")) or bool((state or {}).get("test"))


def run_options(input, state=None):
    return {"announce": _switch(input.get("announce_records")),
            "announce_daily": _switch(input.get("announce_daily")),
            "banner": str(input.get("record_banner") or "").strip() or RECORD_BANNER,
            "weekly": input.get("announce_weekly"),
            "testing": is_testing(input, state)}


def report_round(result, state):
    result["objects"] = flavour_name(state)
    result["round"] = state["step"]
    result["words_shown"] = state["shown"]
    result["probe"] = state["probe"]
    result["expected"] = state["expect"]
    result["question_kind"] = state["kind"]
    result["shields"] = state["shields"]


def join_blocked(result, token, channel, clicker, session, source_ts, quiet_limit,
                 name, keyword):
    """Whether a record post's Play button should do nothing for this person. If so the
    result says why, and a game in play is told so privately.

    Two cases: this same button was already pressed (their rules card from this post is
    up, or coming), and a game of theirs that is in play right now, which a button anyone
    can reach must not replace by accident (typing the keyword still does, on purpose).
    "In play" is a move within `quiet_limit` seconds; past that the game is closed, or is
    a dead one that nothing is going to move.
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
    quiet = _now() - float(state.get("q_at") or state.get("started") or 0)
    if status in (SESSION_ACTIVE, SESSION_BUSY) and quiet < quiet_limit:
        slack_ephemeral(token, channel, clicker,
                        "You already have an {} game in play. Finish it first, or type "
                        "`{}` to start a fresh one.".format(name, keyword),
                        thread_ts=source_ts)
        result["ok"] = True
        result["skipped"] = "a game of theirs is in play"
        return True
    return False


def play_button(flav=WORDS_GAME):
    """The play button under an iMemory (or iMemoryImage) record post. ANYONE may press
    it, so its value names no one: the presser is who plays.

    Its action_id is the rules card's Start button's, on purpose: the click recipe
    already lets that one through, so this needs no change to the trigger."""
    return {"type": "button", "action_id": "imemory_start", "style": "primary",
            "text": {"type": "plain_text", "text": "Play " + flavour(flav)["name"]},
            "value": action_value("anyone", 0, "join", flav)}


def join_in_thread(input, result, table, token, source_ts, flav=WORDS_GAME):
    """A record post's Play button, which ANYONE may press: start the presser's own free
    game as a reply in that post's thread.

    The rules card lands under the post, so the channel gets no new top-level message,
    and Play again stays in the thread. (The nudge's buttons, join_from_post, open a
    thread of their own instead.) Nothing is spent or timed until Start is pressed.
    """
    result["mode"] = "join"
    result["game"] = "play"
    if not source_ts:
        result["error"] = "source_ts is required for the record post's play button"
        return
    clicker = result["user_id"]
    game = flavour(flav)
    session = table.row_for(game["session"], clicker)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the game table; nothing started"
        return
    # A question on screen, or the study and flash screens between two questions.
    in_play = ((ANSWER_SECONDS or MAX_THINK_SECONDS) + CLICK_GRACE_SECONDS + SHIELD_FLASH_SECONDS
               + study_seconds(MAX_WORDS) + 1)
    if join_blocked(result, token, result["channel"], clicker, session, source_ts, in_play,
                    game["name"], game["keyword"]):
        return
    # A message_ts that is unique to this press, so a Slack retry of the SAME press is
    # caught as a duplicate while a later press is not.
    result["message_ts"] = "join:{}".format(str(input.get("action_ts") or source_ts))
    result["thread_ts"] = source_ts
    start_game(input, result, table, token, origin=source_ts, flav=flav)


def join_from_post(input, result, table, token, source_ts, daily, flav=WORDS_GAME):
    """A button on a channel post that ANYONE may press: start the clicker's own game.

    The post is the daily nudge after someone finishes a daily, or the scheduled daily
    nudge for this game. `daily=True` (Play today's daily) is what typing `imemory daily`
    does; `daily=False` (Play a game) is what typing `imemory` does. Either way: a root
    message in the channel naming the player, the rules card as a reply in its thread, and
    nothing spent until Start -- so each person's game has a thread of its own.
    """
    result["mode"] = "join"
    result["game"] = "daily" if daily else "play"
    channel = result["channel"]
    if not source_ts:
        result["error"] = "source_ts is required for the post's play buttons"
        return
    clicker = result["user_id"]
    day = local_today(DAILY_TZ_OFFSET).isoformat() if daily else ""
    game = flavour(flav)

    # Everything that can say "no" is checked BEFORE a root message is posted, so a
    # refused press leaves nothing behind.
    session = table.row_for(game["session"], clicker)
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
        played = table.row_by_key(game["daily"], daily_key(clicker, day, game["daily"]))
        if played is LOOKUP_FAILED:
            result["error"] = "could not read the game table; nothing started"
            return
        if played:
            slack_ephemeral(token, channel, clicker,
                            "You have already played today's {} Daily list. A new one "
                            "tomorrow.".format(game["name"]))
            result["ok"] = True
            result["skipped"] = "today's daily list was already played"
            return

    root_ts, error = slack_post(
        token, channel, "<@{}> joined {}".format(
            clicker, "today's {} Daily".format(game["name"]) if daily else game["name"]),
        [{"type": "section", "text": {"type": "mrkdwn", "text": (
            ":calendar:  <@{}> joined today's *{} Daily*  \u2014  the game is in this "
            "thread.".format(clicker, game["name"])
            if daily else
            "{}  <@{}> is playing *{}*  \u2014  the game is in this thread.".format(
                game["icon"], clicker, game["name"]))}}])
    if error:
        result["error"] = "could not open a thread for the game: " + error
        return

    # A message_ts that is unique to this press, so a Slack retry of the SAME press is
    # caught as a duplicate while a later press is not.
    result["message_ts"] = "{}:{}".format("try" if daily else "play",
                                          str(input.get("action_ts") or source_ts))
    result["thread_ts"] = root_ts
    start_game(input, result, table, token, origin=source_ts, flav=flav)
    if not result.get("ok") or result.get("skipped"):
        slack_delete(token, channel, root_ts)      # nothing started: do not leave an empty thread


def replay_game(input, result, table, token, owner, step_no, kind, session, state, source_ts):
    """The result card's buttons: Play again, or Today's daily -- in the same thread.

    Play again starts at once, in a new message under the same thread: the player
    already knows the rules. Today's daily posts its rules card instead, because
    the day's single attempt is spent at Start and should be a deliberate press.
    """
    channel = result["channel"]
    result["mode"] = "replay"
    result["game"] = "daily" if kind == "daily" else "play"

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
    flav, game_kind = flavour_name(state), flavour(state)
    if kind == "daily":
        day = local_today(DAILY_TZ_OFFSET).isoformat()
        played = None if testing else table.row_by_key(
            game_kind["daily"], daily_key(owner, day, game_kind["daily"]))
        if played is LOOKUP_FAILED:
            result["error"] = "could not read the game table; the buttons are unchanged"
            return
        if played:
            slack_ephemeral(token, channel, owner,
                            "You have already played today's daily list. A new one tomorrow.",
                            thread_ts=thread_ts or None)
            result["ok"] = True
            result["skipped"] = "today's daily list was already played"
            return

    # CLAIM: a second press now reads "busy" and backs off.
    if not table.update(record_id, {"status": SESSION_BUSY}):
        result["error"] = "could not claim the click; the buttons are unchanged"
        return
    error = retire_card(token, channel, state)
    if error:
        result["warnings"].append("old card: " + error)

    best = 0
    if not day:
        row = table.row_for(game_kind["user"], owner)
        if row is LOOKUP_FAILED:
            result["warnings"].append("best score unreadable; no target shown")
        elif row:
            best = int(row.get("personal_best_single_set") or 0)
    chan = {} if day else channel_target(table, game_kind["user"], owner, result["warnings"])
    # Play again keeps the game's setting unless this recipe says otherwise.
    given = str(input.get("look_back") or "").strip()
    lookback = _enabled(given) if given else bool(state.get("lookback"))
    new = fresh_state(owner, name, state.get("tz") or DEFAULT_TZ_OFFSET,
                      channel, thread_ts, best, day, lined=True, chan=chan, lookback=lookback,
                      test=testing, pics=flav == PICTURES_GAME)
    trigger_ts = session.get("last_processed_ts") or ""
    result["user_name"] = name

    if kind == "daily":
        open_rules_card(result, table, token, record_id, new, name, trigger_ts,
                        row_type=game_kind["session"])
        return
    screen = Screen(token, channel, "", thread_ts, result["warnings"], lined=True)
    game = Game(table, token, result, channel, owner, name, record_id, trigger_ts,
                screen, options=run_options(input, new), session_type=game_kind["session"])
    begin_game(game, new)


def answer_game(input, result, table, token):
    """A button was pressed."""
    channel = result["channel"]
    clicker = result["user_id"]
    source_ts = str(input.get("source_ts") or "").strip()
    parsed = parse_action(input.get("action_value"))
    if not parsed:
        result["error"] = ("action_value is not "
                           "'[img|]<user>|<step>|<yes|no|start|again|daily|try|play|join>'")
        return
    owner, step_no, answer = parsed
    flav = value_flavour(input.get("action_value"))
    game_kind = flavour(flav)
    result["objects"] = flav

    if answer == "join":
        join_in_thread(input, result, table, token, source_ts, flav)
        return
    if answer in ("try", "play"):
        join_from_post(input, result, table, token, source_ts, daily=(answer == "try"),
                       flav=flav)
        return

    if clicker != owner:
        slack_ephemeral(token, channel, clicker,
                        "This is someone else's {} game. Type `{}` to start your own.".format(
                            game_kind["name"], game_kind["keyword"]),
                        thread_ts=result["thread_ts"] or source_ts or None)
        result["ok"] = True
        result["skipped"] = "button belongs to another player"
        return

    session = table.row_for(game_kind["session"], owner)
    if session is LOOKUP_FAILED:
        # Nothing has been touched, so the buttons still work: press again.
        result["error"] = "could not read the game table; the buttons are unchanged"
        return
    state = load_state(session)
    if not session or not state:
        _expire(token, channel, source_ts, expired_blocks(flav))
        result["ok"] = True
        result["skipped"] = "no game found for this player"
        return
    result["testing"] = is_testing(input, state)
    if result["testing"]:
        state["test"] = True                        # remembered from here on
    if answer in ("again", "daily"):
        replay_game(input, result, table, token, owner, step_no, answer, session,
                    state, source_ts)
        return
    if source_ts and state.get("ts") and source_ts != state["ts"]:
        _expire(token, channel, source_ts, expired_blocks(flav))   # an older game's message
        result["ok"] = True
        result["skipped"] = "message belongs to a replaced game"
        return
    # Start is only valid on a game that is waiting for it; yes/no only on a live question.
    waiting_for = SESSION_READY if answer == "start" else SESSION_ACTIVE
    if session.get("status") != waiting_for or state.get("step") != step_no:
        result["ok"] = True
        result["skipped"] = "stale or repeated click"
        return

    # CLAIM. From here a second click -- or the countdown step reaching zero --
    # reads "busy" and backs off, which is what stops one question settling twice.
    record_id = session.get("$record_id")
    name = state.get("name") or owner
    result["user_name"] = name
    result["game"] = "daily" if state.get("daily") else "play"

    if not table.update(record_id, {"status": SESSION_BUSY}):
        result["error"] = "could not claim the click; the buttons are unchanged"
        return

    screen = Screen(token, channel, state.get("ts") or source_ts,
                    state.get("thread_ts") or result["thread_ts"], result["warnings"],
                    lined=state.get("lined"))
    game = Game(table, token, result, channel, owner, name, record_id,
                session.get("last_processed_ts") or "", screen,
                options=run_options(input, state), session_type=game_kind["session"])

    if answer == "start":
        begin_game(game, state)
        return

    # Thinking time is measured to Slack's own click timestamp, so recipe and
    # Workato latency do not land on the player's clock.
    pressed = _float(input.get("action_ts")) or _now()
    thinking = max(0.0, pressed - float(state.get("q_at") or pressed))
    if ANSWER_SECONDS:
        if thinking > ANSWER_SECONDS + CLICK_GRACE_SECONDS:
            answer = ""                    # too late, whatever the countdown did
        thinking = min(thinking, float(ANSWER_SECONDS))
    else:
        thinking = min(thinking, float(MAX_THINK_SECONDS))

    settle(game, state, answer, thinking, from_click=True)


def hold_flash(screen, text, blocks, seconds):
    """Keep a flash ("Correct", "Shield earned", "Shield used") up for `seconds`.

    The question's countdown is in the same message, and a tick that had already read the
    table before the click was claimed can land just after the flash, painting the old
    question back over it -- the flash and the question then take turns on screen. So the
    flash is drawn twice: once at once, and again once such a tick has had time to land
    (REASSERT_SECONDS, or part way through a shorter flash)."""
    screen.show(text, blocks)
    again = min(REASSERT_SECONDS, seconds * 0.6)
    _sleep(again)
    screen.show(text, blocks)
    _sleep(max(0.0, seconds - again))


def settle(game, state, answer, thinking, from_click=False):
    """Judge an answer -- "" means time ran out -- and move the game on.

    The caller has already claimed the question (status busy).
    """
    result, screen = game.result, game.screen
    timed_out = not answer
    state["secs"] = round(float(state.get("secs") or 0) + thinking, 3)
    state["answered"] = answer

    correct = (not timed_out) and judge(state["expect"], answer)
    result["correct"] = correct
    result["timed_out"] = timed_out
    result["answer_seconds"] = round(thinking, 3)

    try:
        if correct:
            state["score"] = int(state.get("score") or 0) + 1
            state["trail"] = (state.get("trail") or "") + "g"
            earned = (state["score"] % SHIELD_EVERY == 0
                      and int(state.get("shields") or 0) < SHIELD_CAP)
            if earned:
                state["shields"] = int(state.get("shields") or 0) + 1
            # The one moment worth marking: the score that first beats the best.
            passed, passed_chan = crossed(state)
            hold_flash(screen, "{}: correct".format(flavour(state)["name"]),
                       flash_blocks(state, correct_lines(state, earned, passed, passed_chan)),
                       FLASH_SECONDS + (1.0 if earned or passed or passed_chan else 0))
        elif int(state.get("shields") or 0) > 0:
            state["shields"] = int(state["shields"]) - 1
            state["trail"] = (state.get("trail") or "") + "y"
            hold_flash(screen, "{}: shield used".format(flavour(state)["name"]),
                       flash_blocks(state, shield_lines(state)), SHIELD_FLASH_SECONDS)
        else:
            state["trail"] = (state.get("trail") or "") + "r"
            card = finish_game(game, state)
            game.write(SESSION_OVER, state, screen.ts)
            if from_click and ANSWER_SECONDS:
                _sleep(REASSERT_SECONDS)
                screen.show("{}: game over".format(flavour(state)["name"]), card)
            result["ok"] = True
            result["score"] = state["score"]
            result["round"] = state["step"]
            result["trail"] = state["trail"]
            result["total_seconds"] = state["secs"]
            result["posted_ts"] = screen.ts
            return

        play_round(game, state)
    except RuntimeError as error:
        # Slack would not take the next screen. Close the game rather than
        # leave a session no button can move: the buttons on screen carry a
        # step the table no longer expects.
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


def daily_blocks(owner, state):
    """The channel nudge after a daily game: who played, how it went, how to join in.

    The squares show how the run went without revealing a single word.
    """
    squares = share_line(state).split("\n", 1)[1]
    if state["score"] > 0:
        played = "<@{}> scored *{}* in *{}*.\n{}".format(
            owner, state["score"], seconds_text(state["secs"]), squares)
    else:
        played = "<@{}> had a go and was caught out on the first question.\n{}".format(owner, squares)
    game = flavour(state)
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text":
            ":calendar:  *{} Daily*  \u2014  today's list is live".format(game["name"])}},
        {"type": "section", "text": {"type": "mrkdwn", "text": played}},
        _context("Same {} for everyone, one attempt each. *Think you can beat it?*".format(
            game["many"])),
        {"type": "actions", "block_id": "imemory_try", "elements": [
            {"type": "button", "action_id": "imemory_try", "style": "primary",
             "text": {"type": "plain_text", "text": "Play today's daily"},
             # Anyone may press it, so the value names no one: the clicker is who plays.
             "value": action_value("anyone", 0, "try", flavour_name(state))},
        ]},
    ]


def announce_daily(game, state):
    """Post the daily nudge to the channel, top level. True only if it was posted."""
    ts, error = slack_post(
        game.token, game.channel,
        "<@{}> played today's {} Daily and scored {}".format(
            game.owner, flavour(state)["name"], state["score"]),
        daily_blocks(game.owner, state))
    if error:
        game.result["warnings"].append("daily announcement: " + error)
        return False
    game.result["daily_post_ts"] = ts
    return True


def announce_record(game, rec, **wording):
    """Post the record to the channel, top level. True only if it was posted.

    `wording` is passed to record_blocks: iMatch's name, sentence and unit.
    """
    if not rec:
        return False
    game.result["record"] = rec["kind"]
    ts, error = slack_post(game.token, game.channel,
                           record_summary(game.owner, rec, wording.get("game_name", "iMemory")),
                           record_blocks(game.owner, rec, game.options["banner"], **wording))
    if error:
        game.result["warnings"].append("record announcement: " + error)
        return False
    game.result["record_ts"] = ts
    return True


def standing(table, user_type, owner):
    """(best score, its time) the player already holds: (0, 0.0) if none, or unreadable.

    For a test game's card, which shows the standing as it is and changes nothing.
    """
    row = table.row_for(user_type, owner)
    if row and row is not LOOKUP_FAILED:
        best_score, best_secs, _ = best_of(row, 0, 0.0)
        return best_score, best_secs
    return 0, 0.0


def save_run(game, user_type, score, secs, tz_offset, announce):
    """Save a finished free game on the player's row, and post a record if it set one.

    `user_type` is the row to save on (each game has its own) and `announce(rec)`
    posts the record in that game's words. Returns
    (best_score, best_secs, new_best, shared).
    """
    result, table, owner = game.result, game.table, game.owner
    row = table.row_for(user_type, owner)
    # Read the standings BEFORE saving: after the write, this player's new
    # score would be the channel best and there would be nothing to beat.
    board = table.board(user_type) if score > 0 and game.options["announce"] else []
    if row is LOOKUP_FAILED:
        # Writing now would treat a returning player as a first-timer and
        # overwrite their best. Tell them rather than guess.
        result["warnings"].append("player row unreadable; score not saved")
        return score, secs, True, False
    best_score, best_secs, new_best = best_of(row, score, secs)
    today = local_today(tz_offset).isoformat()
    fields = {
        "record_key": "{}_{}".format(user_type, owner),
        "row_type": user_type,
        "id": owner,
        "name": game.name,
        "current_value": score,
        "personal_best_single_set": best_score,
        "total": "{:.1f}".format(best_secs),
        "total_planks": int((row or {}).get("total_planks") or 0) + 1,
        "slack_channel_id": game.channel,
        "updated_at": today,
    }
    # A weekly challenge about this game, settled in the same write.
    day = local_today(tz_offset)
    cleared = weekly_apply(game, user_type, row, fields, score, day)
    if row:
        saved = table.update(row.get("$record_id"), fields)
    else:
        fields["first_seen"] = today
        saved, _ = table.create(fields)
    result["saved"] = saved
    if saved and cleared:
        announce_weekly(game, cleared, day)
    shared = False
    if saved and game.options["announce"] and board is not LOOKUP_FAILED:
        shared = announce(records_broken(row, board, owner, score, secs))
    return best_score, best_secs, new_best, shared


def finish_game(game, state):
    """Save the run, then replace the question with the closing card."""
    result, table, screen = game.result, game.table, game.screen
    owner = game.owner
    score, secs = int(state["score"]), float(state["secs"])
    best_score, best_secs, new_best = score, secs, True
    shared = False
    # A test game saves nothing and tells the channel nothing: no best, no daily row, no
    # record post, no daily nudge. (Its session row is the one thing it must keep: every
    # click is a separate job, and the game lives there.)
    testing = bool(game.options.get("testing"))
    result["testing"] = testing
    flav, kind = flavour_name(state), flavour(state)

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
        best_score, best_secs = standing(table, kind["user"], owner)
        new_best = False
    else:
        best_score, best_secs, new_best, shared = save_run(
            game, kind["user"], score, secs, int(state.get("tz") or DEFAULT_TZ_OFFSET),
            lambda rec: bool(rec) and announce_record(
                game, rec, game_name=kind["name"], join=play_button(flav),
                detail=memory_record_detail(owner, rec, flav)))

    result["personal_best"] = new_best
    result["best_score"] = best_score
    result["best_seconds"] = best_secs
    # Whether today's daily is still there to offer. A failed read offers it anyway:
    # a button that turns out to be spent says so, a missing one says nothing.
    daily_open = True
    if not state.get("daily") and not testing:
        played = table.row_by_key(
            kind["daily"], daily_key(owner, local_today(DAILY_TZ_OFFSET).isoformat(), kind["daily"]))
        daily_open = played is None or played is LOOKUP_FAILED
    # Kept on the session so the same card can be redrawn, buttons off, later.
    state["card"] = {"b": best_score, "s": best_secs, "n": new_best, "sh": shared,
                     "d": daily_open}
    card = over_blocks(state, best_score, best_secs, new_best, shared, daily_open)
    screen.show("{}: game over. Score {}".format(kind["name"], score), card, essential=True)
    return card


def _expire(token, channel, ts, blocks=None):
    """Strip the buttons from a message whose game is gone."""
    if token and channel and ts:
        slack_update(token, channel, ts, "iMemory: game ended",
                     expired_blocks() if blocks is None else blocks)


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# iMatch -- the pairs game. Its rules first (no network), then its screens, then
# the steps that run it. What it shares with iMemory is above: the table, the
# Screen, the Game, shields, targets, bests and record posts.
# --------------------------------------------------------------------------

MATCH_PROMPT = "*Find the pairs.* Pick a tile to open it, then pick its twin."

def match_level(level):
    """(rows, columns, seconds shown) for a level, counted from 1."""
    level = max(int(level), 1)
    if level <= len(MATCH_LEVELS):
        return MATCH_LEVELS[level - 1]
    return MATCH_LEVELS[-1]            # the board and its time stop growing together


def pick_faces(pairs, level, rng):
    """`pairs` different faces, as easy to confuse as the level allows."""
    shelves = rng.sample(list(MATCH_FACES), len(MATCH_FACES))
    if level < MATCH_ALIKE_FROM and pairs <= len(shelves):
        return [rng.choice(MATCH_FACES[shelf]) for shelf in shelves[:pairs]]
    pool = []
    for shelf in shelves:
        pool += MATCH_FACES[shelf]
        if len(pool) >= pairs:
            break
    return rng.sample(pool, pairs)


def build_board(level, rng):
    """The tiles of a level, shuffled: every face twice. Tile i is board[i], row by row."""
    rows, cols, _ = match_level(level)
    tiles = pick_faces(rows * cols // 2, level, rng) * 2
    rng.shuffle(tiles)
    return {"board": tiles, "cols": cols}


def match_rng(state):
    """The generator for this game's current level.

    Seeded by the game and the level, so a level dealt twice -- two steps that
    both got past claim_turn -- is the same board both times.
    """
    return random.Random("imatch:{}:{}:{}".format(
        state.get("owner"), state.get("started"), state.get("level")))


def match_sig(state):
    """A fingerprint of the board as it stands, carried by every button drawn from it.

    It changes with every pick, so a click can be checked against the table:
    made on the board the table holds, or on an older drawing of it.
    """
    key = (state.get("started"), state.get("level"), state.get("step"), state.get("open"),
           sorted(state.get("found") or []), state.get("shields"), state.get("score"))
    return "{:08x}".format(zlib.crc32(repr(key).encode("utf-8")) & 0xFFFFFFFF)


def match_value(owner, sig, verb):
    return "imatch|{}|{}|{}".format(owner, sig, verb)


def parse_match(value):
    """'imatch|<owner>|<sig>|<start|again|look|join|t<n>>' -> (owner, sig, verb, tile), or None.

    `verb` comes back as "tile" for t<n>, with the tile's number; otherwise the
    tile is -1. `join` is the play button on a record post: its owner is "anyone".
    """
    parts = str(value or "").split("|")
    if len(parts) != 4 or parts[0] != "imatch":
        return None
    owner, sig, verb = parts[1:]
    if verb in ("start", "again", "look", "join"):
        return owner, sig, verb, -1
    numbered = re.match(r"^t(\d{1,2})$", verb)
    return (owner, sig, "tile", int(numbered.group(1))) if numbered else None


def apply_pick(state, tile):
    """Turn one tile over. Mutates `state` and returns (outcome, shield earned).

      "none"    the tile cannot be picked: open already, matched already, off the board
      "open"    the first tile of a pair is now open
      "pair"    its twin: the pair is found
      "clear"   its twin, and that left one pair, which fills itself in: board cleared
      "shield"  not its twin; a shield forgave it and both tiles are turned back over
      "miss"    not its twin, and no shield: the game is over
    """
    board = state["board"]
    found = list(state.get("found") or [])
    first = state.get("open")
    if not 0 <= tile < len(board) or tile in found or tile == first:
        return "none", False
    state["step"] = int(state.get("step") or 0) + 1
    if first is None:
        state["open"], state["last"] = tile, [tile]
        return "open", False

    state["open"], state["last"] = None, [first, tile]
    shields = int(state.get("shields") or 0)
    if board[first] != board[tile]:
        if shields > 0:
            state["shields"] = shields - 1
            state["trail"] = (state.get("trail") or "") + "y"
            return "shield", False
        state["trail"] = (state.get("trail") or "") + "r"
        state["miss"] = [first, tile]
        return "miss", False

    found += [first, tile]
    state["score"] = int(state.get("score") or 0) + 1
    state["trail"] = (state.get("trail") or "") + "g"
    earned = state["score"] % SHIELD_EVERY == 0 and shields < SHIELD_CAP
    if earned:
        state["shields"] = shields + 1
    # The last pair needs no finding: two tiles are left and they must match.
    left = [i for i in range(len(board)) if i not in found]
    cleared = len(left) <= 2
    state["found"] = found + left if cleared else found
    return ("clear" if cleared else "pair"), earned


def pick_line(state, outcome):
    """The line under the header after a pick that leaves the board in play."""
    board = state["board"]
    faces = [board[i] for i in state.get("last") or []]
    if outcome == "open":
        return "{} is open. Now pick its twin.".format(faces[0])
    if outcome == "shield":
        return (":shield: *Shield used*  \u2014  {} and {} are not a pair. "
                "Both are turned back over. You are still in.").format(*faces)
    to_find = (len(board) - len(state.get("found") or [])) // 2 - 1
    return ":white_check_mark: *Pair found* {}  \u2014  {} more to find.".format(
        faces[0], to_find)


def clear_line(state):
    rows, cols, _ = match_level(int(state["level"]) + 1)
    return (":white_check_mark: *Board cleared*  \u2014  the last pair filled itself in. "
            "Next: a {}\u00D7{} board.").format(rows, cols)


def fresh_match(owner, name, tz_offset, channel, thread_ts, best, chan, lined=False,
                test=False, nxt=None):
    return {"v": 1, "owner": owner, "level": 0, "step": 0, "score": 0, "secs": 0.0,
            "channel": channel, "thread_ts": thread_ts, "ts": "", "name": name,
            "tz": tz_offset, "started": _now(), "best": best, "chan": chan or {},
            "next": nxt or {},
            "shields": 0, "trail": "", "board": [], "cols": 0, "found": [],
            "open": None, "prev": "", "last": [], "line": "",
            "lined": lined, "test": bool(test)}


def match_record_detail(owner, rec, level):
    rows, cols, _ = match_level(level)
    return ("<@{}> found *{}* pair{} in *iMatch* \u2014 as far as level *{}*, a "
            "{}\u00D7{} board, in *{}* of thinking time.").format(
        owner, rec["score"], "" if rec["score"] == 1 else "s", level, rows, cols,
        seconds_text(rec["secs"]))


# ---- iMatch screens -------------------------------------------------------

def _section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _match_header(state):
    parts = [":mahjong: *iMatch*", "Level {}".format(state["level"]),
             "Score {}".format(state["score"])]
    if state.get("shields"):
        parts.append(":shield: Shield ready")
    note = target_text(state)
    if note:
        parts.append(note)
    return _context("  \u00B7  ".join(parts))


def match_grid(state, owner, mode):
    """The board as rows of buttons, one actions block a row.

      "show"  every face up: the study screen, and a cleared board
      "play"  faces down, except the open tile and the pairs found
      "over"  every face up, the two tiles of the losing pick in red

    A pair that has been found is green in every mode. A tile that can be picked
    carries its number; every other button carries "look", which the click step
    drops without reading the table.
    """
    board, cols = state["board"], int(state.get("cols") or 5)
    found = set(state.get("found") or [])
    miss = set(state.get("miss") or []) if mode == "over" else set()
    sig = match_sig(state)
    rows = []
    for start in range(0, len(board), cols):
        elements = []
        for i in range(start, min(start + cols, len(board))):
            up = mode != "play" or i in found or i == state.get("open")
            button = {"type": "button", "action_id": "imemory_match_t{}".format(i),
                      "text": {"type": "plain_text", "emoji": True,
                               "text": board[i] if up else MATCH_HIDDEN},
                      "value": match_value(owner, sig, "look" if up else "t{}".format(i))}
            if i in miss:
                button["style"] = "danger"
            elif i in found:
                button["style"] = "primary"
            elements.append(button)
        rows.append({"type": "actions", "block_id": "imemory_match_r{}".format(start // cols),
                     "elements": elements})
    return rows


def match_target_intro(state):
    """The ladder as iMath's rules card shows it: your best, who is next, the channel's."""
    best = int(state.get("best") or 0)
    nxt, chan = state.get("next") or {}, state.get("chan") or {}
    lines = []
    if best:
        lines.append(":trophy: Your best: *{}*".format(best))
    if nxt.get("score"):
        lines.append(":dart: Next to beat: *{}* with *{}*".format(
            nxt.get("name") or "?", nxt["score"]))
    if chan.get("score"):
        lines.append(":crown: Channel best: *{}* by *{}*".format(
            chan["score"], chan.get("name") or "?"))
    return "\n".join(lines)


def match_intro_blocks(state, owner):
    """The rules and a Start button. Nothing is dealt until it is pressed.

    Short, as iMath's is: three lines of rules, then the targets in a section of
    their own so Slack does not fold them behind "Show more"."""
    rules = [
        "Memorise the board, then find each tile's twin.",
        "A wrong pair ends the game. Every *{}* pairs earns a :shield: shield that "
        "forgives one.".format(SHIELD_EVERY),
    ]
    if IDLE_SECONDS:
        rules.append("No pick for *{}s* closes the game.".format(IDLE_SECONDS))
    blocks = [
        _context(":mahjong: *iMatch*" + TEST_NOTE * bool(state.get("test"))),
        _section("\n".join("\u2022 " + r for r in rules)),
    ]
    targets = match_target_intro(state)
    if targets:
        blocks.append(_section(targets))
    blocks.append(
        {"type": "actions", "block_id": "imemory_match_intro", "elements": [
            {"type": "button", "action_id": "imemory_match_start", "style": "primary",
             "text": {"type": "plain_text", "text": "Start game"},
             "value": match_value(owner, match_sig(state), "start")},
        ]})
    return blocks


def match_study_blocks(state, owner, remaining):
    return [
        _match_header(state),
        _section("*Memorise the board*  \u2014  {} pairs. Remember where each one is.".format(
            len(state["board"]) // 2)),
    ] + match_grid(state, owner, "show") + [
        _context(":hourglass_flowing_sand: Hiding in *{}*".format(remaining))]


def match_play_blocks(state, owner):
    return [_match_header(state), _section(state.get("line") or MATCH_PROMPT)] + \
        match_grid(state, owner, "play")


def match_clear_blocks(state, owner, lines):
    return [_match_header(state), _section("\n".join(lines))] + \
        match_grid(state, owner, "show")


def match_over_blocks(state, best_score, best_secs, new_best, shared=False, buttons=True):
    """The closing card: the wrong pair, the whole board face up, the numbers.

    `buttons=False` is the same card after the player has moved on: the result
    and the board stay, Play again goes.
    """
    board, owner = state["board"], state["owner"]
    wrong = [board[i] for i in state.get("miss") or []]
    if state.get("idle"):
        headline = (":hourglass: *Time's up*  \u2014  no pick for {}s, so the game was "
                    "closed.").format(IDLE_SECONDS)
        key = "_The whole board is below: the pairs you found in green._"
    else:
        headline = ":x: *Game over*" + (
            "  \u2014  {} and {} are not a pair.".format(*wrong) if len(wrong) == 2 else "")
        key = ("_The whole board is below: the pairs you found in green, the two tiles "
               "you picked in red._")
    result = "*Score:* {}   \u00B7   *Level:* {}   \u00B7   *Time:* {}".format(
        state["score"], state["level"], seconds_text(state["secs"]))
    if new_best:
        result += "   \u00B7   :trophy: *New personal best*"
    elif best_score:
        result += "   \u00B7   Best: {} in {}".format(best_score, seconds_text(best_secs))
    else:
        result += "   \u00B7   Find one pair to set a personal best"

    footer = [_context(":tada: Shared with the channel.")] if shared else []
    if state.get("test"):
        footer.append(_context(":test_tube: Test game: this result was not saved."))
    if not buttons:
        footer.append(_context(":arrow_forward: A new game has started."))
    else:
        footer.append({"type": "actions", "block_id": "imemory_match_over", "elements": [
            {"type": "button", "action_id": "imemory_match_again", "style": "primary",
             "text": {"type": "plain_text", "text": "Play again"},
             "value": match_value(owner, match_sig(state), "again")}]})
    return [
        _context(":mahjong: *iMatch*  \u00B7  Level {}".format(state["level"])),
        _section(headline + "\n" + key),
    ] + match_grid(state, owner, "over") + [_section(result)] + footer


def match_join_button():
    """The play button under an iMatch record post. ANYONE may press it, so its value
    names no one: the presser is who plays.

    Its action_id is the Start button's, on purpose: the click recipe already lets that
    one through, so this needs no change to the trigger. The step routes on the value."""
    return {"type": "button", "action_id": "imemory_match_start", "style": "primary",
            "text": {"type": "plain_text", "text": "Play iMatch"},
            "value": match_value("anyone", "0", "join")}


def match_expired_blocks():
    return [_context(":mahjong: This iMatch game has ended. Type `imatch` to start a new one.")]


# ---- iMatch steps ---------------------------------------------------------

def match_targets(table, owner, warnings):
    """(the player's best, the person just above it, the channel best). A failed read
    shows no target."""
    best = 0
    row = table.row_for(ROW_MATCH_USER, owner)
    if row is LOOKUP_FAILED:
        warnings.append("best score unreadable; no target shown")
    elif row:
        best = int(row.get("personal_best_single_set") or 0)
    nxt, chan = rival_targets(table, ROW_MATCH_USER, owner, best, warnings)
    return best, nxt, chan


def claim_turn(table, record_id, row_type, owner):
    """Take the game for a step that must happen once. True if it is ours.

    Reading "free" and then writing "busy" is two calls, and two clicks a moment
    apart can both read "free". So each writes a token of its own, lets the
    other's write land, and reads the row back: the later token is the one still
    there, and whoever does not find its own stands down.
    """
    token = "{:.3f}:{}".format(_now(), random.getrandbits(40))
    if not table.update(record_id, {"status": SESSION_BUSY, "current_value": token}):
        return False
    _sleep(CLAIM_SETTLE_SECONDS)
    row = table.row_for(row_type, owner)
    if row is LOOKUP_FAILED:
        return True           # cannot tell; the write went through, so carry on
    return bool(row) and row.get("current_value") == token


def retire_match_card(token, channel, state):
    """Redraw a finished game's card without Play again. Returns an error or ""."""
    card = state.get("card")
    if not card or not state.get("ts"):
        return ""
    blocks = match_over_blocks(state, card["b"], card["s"], card["n"], card["sh"],
                               buttons=False)
    if state.get("lined"):
        blocks = divided(blocks)
    return slack_update(token, channel, state["ts"], "iMatch: game over", blocks) or ""


def redraw_match(token, channel, row, state, warnings):
    """Put the board the table holds back on screen, after a pick that did not count.

    Two steps can each draw the board and land in the wrong order, leaving an
    older drawing on screen. Its buttons carry an old fingerprint, so the next
    pick on it is dropped -- and comes here, which is what puts the screen right.
    """
    status = row.get("status")
    if not state.get("ts") or not state.get("board"):
        return
    if status == SESSION_ACTIVE:
        text, blocks = "iMatch: find the pairs", match_play_blocks(state, state["owner"])
    elif status == SESSION_OVER and state.get("card"):
        card = state["card"]
        text, blocks = "iMatch: game over", match_over_blocks(
            state, card["b"], card["s"], card["n"], card["sh"])
    else:
        return                # a step has the game; it will draw the board itself
    Screen(token, channel, state["ts"], state.get("thread_ts"), warnings,
           lined=state.get("lined")).show(text, blocks)


def report_match(result, state):
    result["round"] = state["level"]
    result["score"] = state["score"]
    result["shields"] = state["shields"]
    result["trail"] = state["trail"]
    result["total_seconds"] = state["secs"]
    result["words_shown"] = state["board"]


def start_match(input, result, table, token, origin=""):
    """`imatch` typed (or a record post's button): claim the message, then post the rules card.

    `origin` is the ts of the record post whose button started this game, if any."""
    user_id, channel = result["user_id"], result["channel"]
    message_ts, thread_ts = result["message_ts"], result["thread_ts"]
    testing = is_testing(input)
    result["testing"] = testing

    session = table.row_for(ROW_MATCH_SESSION, user_id)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the game table; nothing started"
        return
    if session and is_duplicate(session, message_ts):
        result["ok"] = True
        result["skipped"] = "duplicate delivery of this message"
        return

    who = slack_user(token, user_id)
    name = who["real_name"] or user_id
    result["user_name"] = name
    best, nxt, chan = match_targets(table, user_id, result["warnings"])
    state = fresh_match(user_id, name, who["tz_offset"], channel, thread_ts, best, chan,
                        test=testing, nxt=nxt)
    state["origin"] = origin

    # The last game's card keeps its result and loses Play again: there is a new
    # game now.
    if session and session.get("status") == SESSION_OVER:
        error = retire_match_card(token, channel, load_state(session))
        if error:
            result["warnings"].append("old card: " + error)

    record_id = claim_row(result, table, session, _session_fields(
        user_id, name, channel, SESSION_STARTING, state, message_ts, ROW_MATCH_SESSION))
    if not record_id:
        return
    open_rules_card(result, table, token, record_id, state, name, message_ts,
                    blocks=match_intro_blocks(state, user_id), row_type=ROW_MATCH_SESSION)


def deal_board(game, state):
    """Deal the next level, show it for its few seconds, then turn every tile over.

    Mutates and returns `state`. The countdown ticks on a fixed schedule from the
    first render, as play_round's does.
    """
    screen, owner = game.screen, game.owner
    state["level"] = int(state.get("level") or 0) + 1
    state["step"] = int(state.get("step") or 0) + 1
    seconds = match_level(state["level"])[2]
    state.update(build_board(state["level"], match_rng(state)))
    state.update({"found": [], "open": None, "prev": "", "last": [], "line": ""})

    screen.show("iMatch: memorise the board", match_study_blocks(state, owner, seconds))
    # Counted from when the board is on screen: with only a couple of seconds to
    # study, the time Slack takes to draw it would otherwise be a large part of it.
    started = _clock()
    for remaining in range(seconds - 1, -1, -1):
        wait = started + (seconds - remaining) - _clock()
        if wait > 0:
            _sleep(wait)
        screen.show("iMatch: hiding in {}".format(remaining),
                    match_study_blocks(state, owner, remaining))
    _sleep(ZERO_HOLD_SECONDS)

    # State is written BEFORE the tiles can be picked, so a pick can never arrive
    # for a board the table does not know about.
    state["q_at"] = _now()
    if not game.write(SESSION_ACTIVE, state, screen.ts):
        # Tiles the table has never heard of could not be picked. Say the game is
        # over rather than leave a board that ignores every press.
        screen.show("iMatch: game ended", match_expired_blocks())
        raise RuntimeError("could not save the board; the game was closed")
    shown = screen.ts
    screen.show("iMatch: find the pairs", match_play_blocks(state, owner), essential=True)
    if screen.ts != shown:                 # the board went out as a new post
        game.write(SESSION_ACTIVE, state, screen.ts)
    return state


def begin_match(game, state):
    """Deal level 1. The caller has already taken the game (claim_turn)."""
    result = game.result
    state["started"] = _now()
    try:
        deal_board(game, state)
    except RuntimeError as error:
        game.table.update(game.record_id, {"status": SESSION_OVER})
        result["error"] = str(error)
        return
    result["ok"] = True
    report_match(result, state)
    result["posted_ts"] = game.screen.ts
    watch_idle(game, state)


def finish_match(game, state):
    """Save the run and put the closing card up. The caller has taken the game."""
    result, screen = game.result, game.screen
    score, secs = int(state["score"]), float(state["secs"])
    testing = bool(game.options.get("testing"))
    result["testing"] = testing
    if testing:
        best_score, best_secs = standing(game.table, ROW_MATCH_USER, game.owner)
        new_best, shared = False, False
    else:
        level = int(state["level"])

        def announce(rec):                 # rec is None when no record was set
            return bool(rec) and announce_record(
                game, rec, game_name="iMatch", unit="pair", join=match_join_button(),
                detail=match_record_detail(game.owner, rec, level))
        best_score, best_secs, new_best, shared = save_run(
            game, ROW_MATCH_USER, score, secs, int(state.get("tz") or DEFAULT_TZ_OFFSET),
            announce)
    result["personal_best"] = new_best
    result["best_score"] = best_score
    result["best_seconds"] = best_secs
    # Kept on the session so the same card can be redrawn later.
    state["card"] = {"b": best_score, "s": best_secs, "n": new_best, "sh": shared}
    screen.show("iMatch: game over. Score {}".format(score),
                match_over_blocks(state, best_score, best_secs, new_best, shared),
                essential=True)
    game.write(SESSION_OVER, state, screen.ts)
    result["ok"] = True
    report_match(result, state)
    result["posted_ts"] = screen.ts


def close_idle(game, state, sig):
    """Close a game nobody has pressed in for IDLE_SECONDS, as a miss. True if it closed.

    `sig` is the board the caller saw idle. The game is claimed the way a pair or a
    wrong pick claims it, then the table is read once more: a pick that landed
    between the caller's look and the claim means the player is still here, and the
    game is handed back untouched.
    """
    table = game.table
    if not claim_turn(table, game.record_id, game.session_type, game.owner):
        return False
    row = table.row_for(game.session_type, game.owner)
    if row is not LOOKUP_FAILED:
        live = load_state(row) if row else {}
        if not row or live.get("ts") != state.get("ts") or match_sig(live) != sig:
            if row:
                table.update(game.record_id, {"status": SESSION_ACTIVE})
            return False
        state = live
    # Walking away must not be a way to a better time: the wait counts against it.
    state["secs"] = round(float(state.get("secs") or 0) + IDLE_SECONDS, 3)
    state["trail"] = (state.get("trail") or "") + "r"
    state.update({"idle": True, "miss": [], "open": None})
    game.result["timed_out"] = True
    finish_match(game, state)
    return True


def watch_idle(game, state):
    """Hold the step open and close the game if no tile is pressed for IDLE_SECONDS.

    Runs in the step that has just left the board waiting. Every IDLE_CHECK_SECONDS
    it asks the table whether this is still the board in play; the first look that
    finds it moved on -- the player picked again, a later step has the game, it is
    over -- ends this step without touching the message. So a game being played keeps
    only a step or two of this alive. At the deadline it closes the game.
    """
    if not IDLE_SECONDS:
        return
    sig, ts, started = match_sig(state), game.screen.ts, _clock()
    looks = max(1, int(math.ceil(IDLE_SECONDS / float(IDLE_CHECK_SECONDS))))
    for look in range(1, looks + 1):
        wait = started + min(IDLE_SECONDS, look * IDLE_CHECK_SECONDS) - _clock()
        if wait > 0:
            _sleep(wait)
        row = game.table.row_for(game.session_type, game.owner)
        if row is LOOKUP_FAILED:
            continue              # cannot tell; the click-time deadline still holds
        live = load_state(row) if row else {}
        if (not row or row.get("status") != SESSION_ACTIVE
                or live.get("ts") != ts or match_sig(live) != sig):
            return
    close_idle(game, state, sig)


def play_pick(game, state, tile, pressed, ahead=False):
    """One tile picked on a board in play: turn it over and move the game on.

    `ahead` marks a pick made one tile early (see match_click); it is played
    only if it completes a pair.
    """
    result, screen, table = game.result, game.screen, game.table
    before = match_sig(state)
    if IDLE_SECONDS and pressed - float(state.get("q_at") or pressed) > \
            IDLE_SECONDS + CLICK_GRACE_SECONDS:
        # Past the deadline, and the step that should have closed the game was cut
        # short. This press closes it; it does not count as a pick.
        if not close_idle(game, state, before):
            result["ok"] = True
            result["skipped"] = "another click got there first"
        return
    after = copy.deepcopy(state)
    outcome, earned = apply_pick(after, tile)
    if outcome == "none":
        result["ok"] = True
        result["skipped"] = "that tile is already open"
        return
    if ahead and outcome not in ("pair", "clear"):
        redraw_match(game.token, game.channel, {"status": SESSION_ACTIVE}, state,
                     result["warnings"])
        result["ok"] = True
        result["skipped"] = "picked before the board had caught up; not counted"
        return

    if outcome in ("shield", "miss"):
        # A wrong pair costs a shield or the game, so it is not judged on one
        # reading. If this click overtook the click for the real twin, that one
        # lands during the pause, the board moves on, and this pick is dropped.
        _sleep(MISS_SETTLE_SECONDS)
        row = table.row_for(game.session_type, game.owner)
        if row is LOOKUP_FAILED:
            result["error"] = "could not confirm the board; the pick was not counted"
            return
        live = load_state(row) if row else {}
        if (not row or row.get("status") != SESSION_ACTIVE
                or live.get("ts") != state.get("ts") or match_sig(live) != before):
            if row:
                redraw_match(game.token, game.channel, row, live, result["warnings"])
            result["ok"] = True
            result["skipped"] = "the board moved on before this pick was judged"
            return

    # Thinking time is measured to Slack's own click time and capped, as in
    # iMemory with the live clock off: waiting on the step is not the player's.
    thinking = min(max(0.0, pressed - float(state.get("q_at") or pressed)),
                   float(IDLE_SECONDS or MAX_THINK_SECONDS))
    after["secs"] = round(float(after.get("secs") or 0) + thinking, 3)
    # Only a first pick can be followed by one made a tile early.
    after["prev"] = before if outcome == "open" else ""
    result["answer_seconds"] = round(thinking, 3)
    result["correct"] = outcome in ("pair", "clear")
    passed, passed_chan = crossed(after) if result["correct"] else (False, False)
    extras = bonus_lines(after, earned, passed, passed_chan,
                         result["correct"] and passed_next(after))

    try:
        if outcome in ("clear", "miss"):
            if not claim_turn(table, game.record_id, game.session_type, game.owner):
                result["ok"] = True
                result["skipped"] = "another click got there first"
                return
            if outcome == "miss":
                finish_match(game, after)
                return
            screen.show("iMatch: board cleared",
                        match_clear_blocks(after, game.owner, [clear_line(after)] + extras))
            _sleep(MATCH_CLEAR_SECONDS + (1.0 if extras else 0))
            deal_board(game, after)
        else:
            # Saved first, drawn second: by the time a tile on the new drawing can
            # be pressed, the table already holds the board it was drawn from.
            after["line"] = "\n".join([pick_line(after, outcome)] + extras)
            after["q_at"] = _now()
            if not game.write(SESSION_ACTIVE, after, screen.ts):
                result["error"] = "could not save the pick; the board is unchanged"
                return
            shown = screen.ts
            screen.show("iMatch: find the pairs", match_play_blocks(after, game.owner),
                        essential=True)
            if screen.ts != shown:
                game.write(SESSION_ACTIVE, after, screen.ts)
    except RuntimeError as error:
        # Slack would not take the next screen. Close the game rather than leave
        # a board no button can move.
        table.update(game.record_id, {"status": SESSION_OVER})
        result["error"] = str(error)
        return
    result["ok"] = True
    report_match(result, after)
    result["posted_ts"] = screen.ts
    watch_idle(game, after)               # holds the step open until picked again or closed


def join_match(input, result, table, token, source_ts):
    """A record post's Play button, which ANYONE may press: start the presser's own game
    as a reply in that post's thread.

    The rules card lands under the post, so the channel gets no new top-level message,
    and Play again stays in the thread. Nothing is dealt until the presser presses Start.
    See join_blocked for what is checked before anything is posted.
    """
    channel, clicker = result["channel"], result["user_id"]
    result["game"] = "match"
    if not source_ts:
        result["error"] = "source_ts is required for the record post's play button"
        return
    session = table.row_for(ROW_MATCH_SESSION, clicker)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the game table; nothing started"
        return
    if join_blocked(result, token, channel, clicker, session, source_ts,
                    (IDLE_SECONDS or MAX_THINK_SECONDS) + CLICK_GRACE_SECONDS,
                    "iMatch", "imatch"):
        return
    # A message_ts that is unique to this press, so a Slack retry of the SAME press is
    # caught as a duplicate while a later press is not.
    result["message_ts"] = "join:{}".format(str(input.get("action_ts") or source_ts))
    result["thread_ts"] = source_ts
    start_match(input, result, table, token, origin=source_ts)


def match_click(input, result, table, token):
    """A button on an iMatch message was pressed."""
    channel, clicker = result["channel"], result["user_id"]
    source_ts = str(input.get("source_ts") or "").strip()
    result["game"] = "match"
    parsed = parse_match(input.get("action_value"))
    if not parsed:
        result["error"] = "action_value is not 'imatch|<user>|<board>|<start|again|look|join|t<n>>'"
        return
    owner, sig, verb, tile = parsed
    result["mode"] = {"start": "begin", "again": "replay", "join": "join"}.get(verb, "pick")
    if verb == "join":
        join_match(input, result, table, token, source_ts)
        return
    if verb == "look":
        # A face-up tile, or the board while it is being shown. Nothing to do, and
        # not worth a table read.
        result["ok"] = True
        result["skipped"] = "not a tile that can be picked"
        return
    if clicker != owner:
        slack_ephemeral(token, channel, clicker,
                        "This is someone else's iMatch game. Type `imatch` to start your own.",
                        thread_ts=result["thread_ts"] or source_ts or None)
        result["ok"] = True
        result["skipped"] = "button belongs to another player"
        return

    session = table.row_for(ROW_MATCH_SESSION, owner)
    if session is LOOKUP_FAILED:
        # Nothing has been touched, so the buttons still work: press again.
        result["error"] = "could not read the game table; the buttons are unchanged"
        return
    state = load_state(session)
    if not session or not state:
        _expire(token, channel, source_ts, match_expired_blocks())
        result["ok"] = True
        result["skipped"] = "no game found for this player"
        return
    testing = is_testing(input, state)
    result["testing"] = testing
    if testing:
        state["test"] = True                        # remembered from here on
    name = state.get("name") or owner
    result["user_name"] = name

    if source_ts and state.get("ts") and source_ts != state["ts"]:
        # An older game's message. Its board or rules card is dead; an old result
        # card is left as it is.
        if verb != "again":
            _expire(token, channel, source_ts, match_expired_blocks())
        result["ok"] = True
        result["skipped"] = "message belongs to a replaced game"
        return

    # Start waits on a rules card, Play again on a result card, a tile on a board
    # in play -- and each only on the drawing the table holds. The one exception:
    # a tile pressed one pick early, before the first tile of its pair had opened
    # on screen. play_pick counts that only if it completes the pair.
    status = session.get("status")
    waiting_for = {"start": SESSION_READY, "again": SESSION_OVER}.get(verb, SESSION_ACTIVE)
    current = match_sig(state)
    ahead = (verb == "tile" and sig != current and sig == state.get("prev")
             and state.get("open") is not None)
    if status != waiting_for or (sig != current and not ahead):
        if verb == "tile":
            redraw_match(token, channel, session, state, result["warnings"])
        result["ok"] = True
        result["skipped"] = "stale or repeated click"
        return

    record_id = session.get("$record_id")
    thread_ts = state.get("thread_ts") or result["thread_ts"]
    trigger_ts = session.get("last_processed_ts") or ""
    if verb == "tile":
        screen = Screen(token, channel, state.get("ts") or source_ts, thread_ts,
                        result["warnings"], lined=state.get("lined"))
        game = Game(table, token, result, channel, owner, name, record_id, trigger_ts,
                    screen, options=run_options(input, state),
                    session_type=ROW_MATCH_SESSION)
        play_pick(game, state, tile, _float(input.get("action_ts")) or _now(), ahead)
        return

    # Start and Play again each happen once.
    if not claim_turn(table, record_id, ROW_MATCH_SESSION, owner):
        result["ok"] = True
        result["skipped"] = "another click got there first"
        return
    if verb == "again":
        # A new game at once, in a new message under the same thread: the player
        # already knows the rules. The old card keeps its result, not its button.
        error = retire_match_card(token, channel, state)
        if error:
            result["warnings"].append("old card: " + error)
        best, nxt, chan = match_targets(table, owner, result["warnings"])
        state = fresh_match(owner, name, state.get("tz") or DEFAULT_TZ_OFFSET, channel,
                            thread_ts, best, chan, lined=True, test=testing, nxt=nxt)
    screen = Screen(token, channel, "" if verb == "again" else (state.get("ts") or source_ts),
                    thread_ts, result["warnings"], lined=state.get("lined"))
    game = Game(table, token, result, channel, owner, name, record_id, trigger_ts,
                screen, options=run_options(input, state), session_type=ROW_MATCH_SESSION)
    begin_match(game, state)


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    token = input.get("slack_bot_token") or ""
    is_click = bool(str(input.get("action_value") or "").strip())
    message_ts = str(input.get("message_ts") or "").strip()

    result = {
        "ok": False, "error": "", "warnings": [], "skipped": "",
        "mode": "answer" if is_click else "start",
        "user_id": (input.get("user_id") or "").strip(),
        "user_name": "",
        "channel": (input.get("channel") or "").strip(),
        "message_ts": message_ts,
        "thread_ts": str(input.get("thread_ts") or "").strip() or message_ts,
        "game": "play", "round": 0, "score": 0, "correct": False, "timed_out": False,
        "answer_seconds": 0, "total_seconds": 0, "words_shown": [], "probe": [],
        "expected": "", "question_kind": "", "shields": 0, "trail": "",
        "share_line": "", "record": "", "record_ts": "", "daily_post_ts": "", "personal_best": False, "best_score": 0,
        "weekly_cleared": [], "weekly_ts": "",
        "best_seconds": 0, "saved": False, "posted_ts": "", "rows_written": 0,
        "testing": False, "objects": WORDS_GAME,
    }

    if not result["user_id"] or not result["channel"]:
        result["error"] = "user_id and channel are both required"
        return result
    if not token:
        result["error"] = "slack_bot_token is required"
        return result

    table = Table(input.get("workato_api_token") or "")

    if is_click:
        if str(input.get("action_value") or "").strip().startswith("imatch|"):
            match_click(input, result, table, token)
        else:
            answer_game(input, result, table, token)
    else:
        allowed, reason = should_process(input)
        if not allowed:
            result["ok"] = True
            result["skipped"] = reason
            return result
        wanted, flav = detect(input.get("text")), WORDS_GAME
        if not wanted:
            wanted, flav = detect_pictures(input.get("text")), PICTURES_GAME
        if not wanted:
            result["ok"] = True
            result["skipped"] = "no imemory keyword"
            return result
        result["game"] = wanted
        if not message_ts:
            result["error"] = "message_ts is required to start a game"
            return result
        if wanted == "match":
            start_match(input, result, table, token)
        else:
            start_game(input, result, table, token, flav=flav)

    result["rows_written"] = table.written
    result["warnings"] += table.errors
    return result


if __name__ == "__main__":
    print(json.dumps(main({
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", ""),
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "text": sys.argv[1] if len(sys.argv) > 1 else "imemory",
        "user_id": sys.argv[2] if len(sys.argv) > 2 else "U038ZCDAY6P",
        "channel": os.environ.get("SLACK_CHANNEL", ""),
        "message_ts": "1787580914.789099",
    }), indent=2))
