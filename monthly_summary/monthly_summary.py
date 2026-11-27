"""
Email summary -- the channel's month as one HTML email, and the list of who to send it to.

Workato Python step. It reads the data table and Slack and returns an email; it posts
nothing and sends nothing. The one thing it writes is a row of its own holding the
channel's totals on the day it ran (see "this step's own snapshot"), so that next month's
email can say exactly what was added. Map `html` to the body of the email connector
(HTML format), `subject` to the subject and `recipients` to To / Bcc.

WHAT THE EMAIL SAYS, top to bottom (the default order; see section_order)
    hero        the month, and its three numbers -- always first
    tiles       people active, check-ins, activities, new members, volume: the numbers,
                straight after the hero
    brief       a headline and two or three sentences written by Azure OpenAI from the
                month's figures, the activities it names picked out in a dark shade of
                their bar's colour in the check-ins chart -- or a plain template when the
                model is unavailable or says something the figures do not support (see
                month_brief)
    trend       people active month by month, as a small column chart
    checkins    where the month's check-ins went: a bar per activity, busiest first, each
                in a calm colour of its own
    together    The Great Walk, under that title -- a map of the route, its stops as dots, a walker on the
                line, the start and finish named
    milestones  the channel's totals in steps, pushups and plank (and milestone_activities),
                each with a bar to the next round number it is climbing towards
    move, strength, mind, habits
                the four families of activities, each under its own banner, with the
                activities logged this month beneath it: the month's people and
                check-ins, and the all-time line. One nobody logged this month is left
                out, and so is one that only a single person has ever logged (see
                section_min_people); a family with nothing to list is skipped
    highlights  welcomes, comebacks, personal bests, a round number passed in somebody's
                own all-time total ("passed 1,000 pushups") or days logged; and, when
                show_badges is on, the badges earned (off by default)
    calendar    who showed up, day by day
    boards      the all-time podium for steps, pushups and plank, for the activities named
                in board_activities, and for every other activity board_min_people or
                more people logged this month (never sleep, fasting or hydration); then,
                under it, the month's own top three in those same activities
    challengers the weekly challenges (weekly_challenge.py) of the month: how many people
                took one on, how many were taken on and cleared, the top three challengers,
                who cleared every one they took on, and the challenges taken on most. Left
                out when nobody took one on (see "the weekly challenges")
    records    the channel record of every activity that records_min_people people have
                logged, and three records about showing up
    games       each brain game anybody has scored in (iMemory, iMatch, iMemoryImage and
                iMath's five, at Easy): its players, games played all time, the top score
                and who holds it
    join        three steps and a button
    footer      why you got it, and that it is automated -- always last

SECTION ORDER. `section_order` is a comma separated list of the names above, and the
email comes out in exactly that sequence: "tiles, brief, trend, checkins, together,
milestones, activities, highlights, join". `activities` stands for move, strength, mind and habits in that order.
A section left out of the list is left out of the email; a name that is not a section is
said in `error`, and so is anything the default order had that the list did not. Blank is
the default order. The hero and the footer are fixed.

THE MONTH is the calendar month the step runs in, in the channel's own time zone. Run on
the last day of the month it is the month-end recap: the whole month, in review,
compared with the whole month before. Run on any earlier day it covers the 1st to today
and says "so far". `month` = "previous" (or "2026-09") sends a finished month after the
fact.

WHEN TO SCHEDULE IT. Spotter dates every log in the poster's own day, so the month's last
day ends at different moments around the world -- last of all in California, at 07:00
UTC on the 1st. A run on the last day misses whatever is logged after it. The schedule
that counts everything is the 1st of each month at 08:00 UTC (13:30 in India, 01:00 in
California), with month = previous and tz_offset left blank. That run's own snapshot is
then the exact starting point for the next month's "added" figures.

WHO GETS IT is `recipients_from`:
    members   everyone in the channel (`channel_id`), listed with Slack's
              conversations.members. The default whenever channel_id is given. If the
              list cannot be read there is NO recipient list and `ok` is false, with the
              reason first in `error` -- never a quiet fall back to the active few, which
              looks like it worked. `members_listed` is how many it found.
    ever      everyone who has ever logged anything, or played a game
    active    everyone with a log dated inside the month -- the default with no channel_id
Each person is then looked up one by one with Slack's users.info for their email address
(the bot token needs users:read.email, and channels:read -- groups:read for a private
channel -- to list members). Deactivated accounts and bots are dropped;
`allowed_email_domains` keeps it to your own company. Anyone whose address could not be
found is listed in `missing_emails` with the reason, never silently skipped.

WHAT IS EXACT AND WHAT IS NOT. Who logged on which day is dated in the table, so people,
check-ins, the calendar, badges and welcomes are exact for the month. The amount of each
log is not dated, so "added this month" is the difference between the totals now and the
totals saved as the month began: by this step itself when it ran on the last day of the
month before (exact from the second month-end email on), or failing that by
channel_summary.py's weekly snapshot nearest the 1st, in which case the email says which
date it counted from. With nothing saved near the 1st it shows all-time totals instead
of guessing.

PRIVACY. This goes far wider than the channel, so it is stricter than the Slack posts:
    * anyone with leaderboard_optout set is left out of every figure and never named;
    * an activity someone logs by DM (is_private) counts in the totals but is never
      credited to them by name;
    * the AI paragraph is given totals only -- no names -- and is told to name nobody;
    * `show_names` = false removes every name and keeps the counts.
    A weekly challenge is taken on in the channel, under the person's name, so is_private
    does not hide it; leaderboard_optout does, as everywhere else.

THE WEEKLY CHALLENGES (the challengers section). weekly_challenge.py keeps a row per post
(row_type weekly_challenge), a row per person per goal taken on (weekly_accept), and the
goal itself on the person's row of the activity or game, in `content`, where spotter (or the
game) marks it done the moment it is cleared. A week belongs to the month its Sunday falls
in, so the last days of a week that ends next month are next month's; a post that was
replaced or failed is not counted, nor is a goal its taker opted out of (status out). Taken
on is an acceptance row; cleared is its entry marked done. Only read when the section is in
section_order, and only for posts in `channel_id` when one is given.

IMAGES. An email client is not signed in to Slack, so a Slack file URL
(coursera.enterprise.slack.com/files/...) shows as a broken image. Banners must be public
https URLs; a Slack one is ignored with a warning and that section falls back to its
coloured band, which is how the email looks with no images at all.

Input schema:
    workato_dev_api       Workato API token                              (required)
    slack_bot_token       xoxb- token with users:read and users:read.email (for recipients)
    azure_api_key         Azure OpenAI key, for the "in brief" paragraph  (optional)
    azure_url             override the deployment URL                     (optional)
    channel_name          shown in the email, without the #  (default plank-you-very-much)
    channel_url           link behind the "Join" button                   (optional)
    month                 blank = this month so far | previous | YYYY-MM  (optional)
    subject_icon          an emoji at the front of the subject (default 💪; "none" for
                          the subject as it was, with no icon)
    hero_image_url        public banner above the title                   (optional)
    section_image_urls    JSON object of public banner URLs, keyed by section:
                          checkins, move, strength, mind, habits, highlights, calendar,
                          together, milestones, boards, challengers, records, games
                                                                          (optional)
    channel_id            the channel's Slack id (C...), to list its members      (optional)
    recipients_from       members | ever | active   (default members with a channel_id)
    section_order         comma separated sections, in the order they should appear
                          (default: tiles, brief, trend, checkins, together, milestones,
                          activities, highlights, calendar, boards, challengers, records,
                          games, join)
    show_names            name people in highlights and boards (default true)
    show_leaderboard      include the all-time podium and the month's top three
                                                               (default true)
    board_activities      more activities to give a podium, comma separated, added after
                          steps, pushups and plank, e.g. workout, read, yoga
                                                               (default none)
    board_min_people      any other activity gets a podium by itself once this many people
                          logged it this month                 (default 5)
    show_badges           include "Badges earned" under the highlights (default false)
    show_photos           a small Slack profile photo beside each name on the boards (the
                          all-time podium and the month's), in the records and in the
                          games; initials for anyone without one
                          (default true; needs slack_bot_token, and show_names on)
    use_saved_profiles    keep each person's Slack name, address and photo in a row of the
                          table (row_type plank_you_very_much_user) and ask Slack only
                          about people with no row yet. Delete a row to have that person
                          asked about again. Nothing is written on a dry run (default true)
    records_min_people    an activity's record is listed once this many people have ever
                          logged it                            (default 4)
    section_min_people    an activity is listed in its section once this many people have
                          ever logged it                       (default 2)
    always_show_activities  listed in their section whatever the count, comma separated
                                                               (default swim)
    trend_months          columns in the month-by-month chart, 2 to 12 (default 12)
    dry_run               testing: build and return the email exactly as it would go
                          out, and store nothing in the table  (default false)
    save_snapshot         save today's totals for next month's email (default true;
                          never on a dry run, or when run from a local file)
    milestone_activities  more activities for the milestones section, comma separated, added
                          after steps, pushups and plank, e.g. workout, meditate
                                                               (default none)
    allowed_email_domains comma separated, e.g. coursera.org   (optional, default any)
    tz_offset             seconds east of UTC that decide "today" (default -25200)
    today, local_data_file, local_snapshot_file, local_email_snapshot_file,
    local_profiles_file, snapshot_row_type, profile_row_type, skip_email_lookup :
    testing aids

Output: see email_summary_output_schema.json. The ones a recipe needs are `subject`,
`html`, `recipients` (comma separated) and `recipient_list` (one object per person).
"""

import argparse
import calendar
import json
import math
import os
import re
import sys
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from html import escape
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

TABLE_ID = "0b863cb1-4712-416b-a9d5-7bf7f2f9b059"
TABLE_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
SLACK_USER_URL = "https://slack.com/api/users.info"
SLACK_MEMBERS_URL = "https://slack.com/api/conversations.members"
MEMBER_PAGES = 50           # 200 a page: a channel of ten thousand, far past any here
AZURE_URL = ("https://cour-servicenow-1.openai.azure.com/openai/deployments/"
             "gpt-4o/chat/completions?api-version=2024-10-21")
HTTP_TIMEOUT = 30
DEFAULT_TZ_OFFSET = -7 * 3600          # as spotter.py: the channel's local date
DEFAULT_CHANNEL_NAME = "plank-you-very-much"

# A Workato Python step is cut off after a while, and the email is worth more than the
# last few addresses: lookups stop here and whoever is left is reported in missing_emails.
LOOKUP_BUDGET_SECONDS = 50
# Gmail cuts a message off at about 102 KB and hides the rest behind "View entire message".
GMAIL_CLIP_BYTES = 100000

SLACK_USER_ID = re.compile(r"^[UW][A-Z0-9]{6,}$")

# The only columns read. KEEP IN STEP with COLUMNS in spotter/spotter.py: the names are
# what the query selects, the ids are what a local export is keyed by.
COLUMNS = {
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "total": "e96b5acc-4196-497e-a18b-7faf7016ec4c",
    "personal_best_single_set": "6198fe02-e888-44a8-bd01-b47d75ee896d",
    "total_planks": "ea80e176-5bfb-421d-bafe-dd4828d67916",
    "heatmap_dates": "7f8871d1-1613-4faa-94e6-a7ef3649cc25",
    "first_seen": "0e8058db-6de1-4bae-98eb-4e45fc506435",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
    "longest_streak": "f7da78dd-d5db-4e94-befa-7fc5c3ffc1dc",
    "leaderboard_optout": "101f8dcb-f067-4045-af61-0799494651b8",
    "is_private": "5b646ace-6026-4395-ae8e-1cb513b1e9b8",
    "golden_dates": "b9517b86-4175-4d78-80b1-dfbf832f803c",
    # the rest of a person's session list, once `total` is full (see session_list)
    "plank_photo": "f801caa5-b3c2-4f07-a98c-7b2d24c66689",
    "current_weight": "08ec0542-79af-43a9-8d58-de30e14a6c51",
    "current_fat": "ce9c49a6-c1f9-4169-8833-a3721d6c38b5",
    "current_muscle": "ac156767-3d8e-42d1-bcd9-b78ca84b6d51",
}
SELECT_COLUMNS = list(COLUMNS)
# Read only for the weekly challenges, in queries of their own (see read_challenges). KEEP
# IN STEP with COLUMNS in weekly_challenge/weekly_challenge.py.
CHALLENGE_COLUMNS = {
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
    "status": "863a9d40-87a7-49ff-ba40-32858e62cd48",
    "week_key": "e9659bdd-c36c-486b-a531-e7b5a38252f6",
    "grant_type": "355e769f-0aa3-46be-bea3-5c2b3442f658",
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "member_name": "bc214e7f-c007-4fd7-ac0e-6367b1e4098f",
    "slack_channel_id": "7101072d-867b-4104-a1e4-ef6611adaaa9",
}

# Where a person's session list lives. Keep this tuple identical to spotter.py's.
TOTAL_COLUMNS = ("total", "plank_photo", "current_weight", "current_fat", "current_muscle")


# ----------------------------------------------------------------- the activities
#
# Every activity spotter logs, as the email shows it. KEEP IN STEP with ACTIVITIES in
# spotter/spotter.py -- a row type missing here is never fetched, so a person who logged
# only that would be missing from the month and from the recipients.
#
# key (the row_type without _users): (title, emoji, section, how a total is counted, noun)
# "minutes" and "seconds" totals read as a duration ("6h 40m"); "count" totals name their
# noun ("412 pages read"). Emoji are Unicode: a Slack :shortcode: means nothing in email.
ACTIVITIES = {
    "step":        ("Steps", "\U0001F45F", "move", "count", "steps"),
    "run":         ("Running", "\U0001F3C3", "move", "minutes", "running"),
    "swim":        ("Swimming", "\U0001F3CA", "move", "minutes", "in the pool"),
    "cardio":      ("Cardio", "\U0001F493", "move", "minutes", "of cardio"),
    "cycle":       ("Cycling", "\U0001F6B4", "move", "minutes", "cycling"),
    "stairs":      ("Stairs", "\U0001F3E2", "move", "count", "flights of stairs"),
    "dance":       ("Dancing", "\U0001F483", "move", "minutes", "dancing"),
    "pushup":      ("Pushups", "\U0001F4AA", "strength", "count", "pushups"),
    "pullup":      ("Pullups", "\U0001F938", "strength", "count", "pullups"),
    "squat":       ("Squats", "\U0001F9B5", "strength", "count", "squats"),
    "plank":       ("Plank", "⏱️", "strength", "seconds", "of plank"),
    "workout":     ("Workouts", "\U0001F3CB️", "strength", "minutes", "working out"),
    "yoga":        ("Yoga", "\U0001F9D8", "mind", "minutes", "on the mat"),
    "meditate":    ("Meditation", "\U0001F9E0", "mind", "minutes", "of meditation"),
    "solitude":    ("Solitude", "\U0001F319", "mind", "minutes", "of quiet"),
    "breathe":     ("Pranayama", "\U0001F32C️", "mind", "minutes", "of pranayama"),
    "chant":       ("Chanting", "\U0001F3B6", "mind", "minutes", "of chanting"),
    "journal":     ("Journalling", "✍️", "mind", "minutes", "journalling"),
    "read":        ("Reading", "\U0001F4DA", "habits", "count", "pages read"),
    "write":       ("Writing", "\U0001F58B️", "habits", "count", "pages written"),
    "learn":       ("Learning", "\U0001F4A1", "habits", "minutes", "learning"),
    "sketch":      ("Sketching", "✏️", "habits", "minutes", "sketching"),
    "paint":       ("Painting", "\U0001F3A8", "habits", "minutes", "painting"),
    "hydrate":     ("Hydration", "\U0001F4A7", "habits", "count", "glasses of water"),
    "sleep":       ("Sleep", "\U0001F634", "habits", "count", "hours slept"),
    "fast":        ("Fasting", "⏳", "habits", "count", "hours fasted"),
    "cold_shower": ("Cold showers", "\U0001F6BF", "habits", "count", "cold showers"),
}

# (key, title, one line about it, colour, emoji) -- the order is the order in the email.
SECTIONS = (
    ("move", "Movement & cardio",
     "Steps, runs, rides and swims: time spent on the move.", "#0056D2", "\U0001F3C3"),
    ("strength", "Strength",
     "Pushups, planks and gym sessions, one set at a time.", "#C2410C", "\U0001F4AA"),
    ("mind", "Mind & stillness",
     "Yoga, meditation and a few quiet minutes in the day.", "#6D28D9", "\U0001F9D8"),
    ("habits", "Learning & everyday habits",
     "Reading, writing, creating, and the small routines that add up.", "#047857",
     "\U0001F4DA"),
)
# The order of the email after the hero, and the names `section_order` takes. "activities"
# is not a section but shorthand for the four families, in that order.
DEFAULT_ORDER = ("tiles", "brief", "trend", "checkins", "together", "milestones", "move",
                 "strength", "mind", "habits", "highlights", "calendar", "boards",
                 "challengers", "records", "games", "join")
SECTION_GROUPS = {"activities": ("move", "strength", "mind", "habits")}
SECTION_ALIASES = {
    "summary": "brief", "in_brief": "brief", "month_in_brief": "brief", "the_month_in_brief": "brief",
    "numbers": "tiles", "stats": "tiles", "figures": "tiles",
    "chart": "trend", "month_by_month": "trend", "people_active": "trend",
    "checkin": "checkins", "check_ins": "checkins", "check_in": "checkins", "mix": "checkins",
    "where_the_check_ins_went": "checkins", "activity_chart": "checkins",
    "walk": "together", "great_walk": "together", "greatwalk": "together",
    "the_great_walk": "together", "steps": "together", "adds_up": "together",
    "what_it_adds_up_to": "together",
    "milestone": "milestones", "next_milestones": "milestones", "next_milestone": "milestones",
    "goals": "milestones",
    "movement": "move", "cardio": "move", "movement_cardio": "move",
    "mind_stillness": "mind", "stillness": "mind",
    "learning": "habits", "habit": "habits", "learning_everyday_habits": "habits",
    "highlight": "highlights", "highlights_of_the_month": "highlights",
    "who_showed_up": "calendar",
    "on_the_boards": "boards", "podium": "boards", "leaderboard": "boards",
    "challenger": "challengers", "challenge": "challengers", "challenges": "challengers",
    "weekly_challenge": "challengers", "weekly_challenges": "challengers",
    "channel_records": "records", "channel_records_to_beat": "records",
    "records_to_beat": "records",
    "brain_games": "games", "game": "games",
    "how_to_join": "join", "want_to_join": "join",
}
# Sections that are not a family of activities but can carry a banner all the same.
OTHER_SECTIONS = {"checkins": "#0E7490", "highlights": "#B45309", "calendar": "#0056D2",
                  "together": "#0F766E",
                  "milestones": "#0369A1", "boards": "#1F2937", "challengers": "#9D174D",
                  "records": "#BE123C", "games": "#4338CA"}

HEADLINE = ("step", "pushup", "plank")
SET_BASED = {"plank", "pushup", "pullup", "squat"}

# Bests that mean something. A "personal best" in glasses of water does not, and nobody
# should be credited company-wide with their longest sleep. As channel_summary.py.
BEST_PHRASE = {"step": "biggest day", "pushup": "biggest set", "plank": "longest hold",
               "swim": "longest swim", "yoga": "longest session",
               "meditate": "longest sit", "pullup": "biggest set",
               "squat": "biggest set", "run": "longest run", "cycle": "longest ride",
               "workout": "longest workout", "cardio": "longest session",
               "dance": "longest session", "stairs": "most flights in a day",
               "read": "most pages in a day", "write": "most pages in a day",
               "learn": "longest study session", "journal": "longest session",
               "sketch": "longest session", "paint": "longest session",
               "breathe": "longest session"}
# A second record for the activities done in sets: everything logged in one day.
DAY_PHRASE = {"pushup": "most in a day", "pullup": "most in a day", "squat": "most in a day",
              "plank": "most in a day"}

# The channel's repeating milestone ladders. KEEP IN STEP with LADDERS in
# channel_summary/channel_summary.py, which posts the same progress every Friday.
LADDERS = {
    "step":   {"cycle": 1000000, "rungs": [250000, 500000, 750000, 1000000]},
    "pushup": {"cycle": 5000, "rungs": [1000, 2000, 3000, 4000, 5000]},
    "plank":  {"cycle": 18000, "rungs": [3600, 7200, 10800, 14400, 18000]},
}

# Milestones for an activity with no ladder of its own: a plain run of round numbers --
# hours for anything timed, a count for anything counted. Past the end, the last figure
# repeats as the step. KEEP IN STEP with HOUR_MARKS / COUNT_MARKS / NO_MILESTONE in
# channel_summary/channel_summary.py, so the email and the Friday post name the same stop.
HOUR_MARKS = (1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 300, 400,
              500, 750, 1000)
COUNT_MARKS = (10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000, 4000,
               5000, 7500, 10000, 15000, 20000, 25000, 50000, 75000, 100000)
# Totals nobody is trying to push up: more hours asleep or fasting is not a goal.
NO_MILESTONE = {"sleep", "fast"}

# The games, in the order the email lists them. One row per player: best score in
# personal_best_single_set (higher is better in every game, iMatch's pairs found included),
# the seconds of that run in total, games played in total_planks, and the day last played
# in updated_at. iMath's rows are its Easy game: a harder level keeps rows of its own
# (math_add_hard_user ...), which are not read. KEEP IN STEP with the games in
# leaderboard/leaderboard.py, imath/imath.py and imemory/imemory.py.
GAMES = {
    "object_memory_user": ("iMemory", "\U0001F9E0"),
    "pairs_memory_user": ("iMatch", "\U0001F004"),
    "image_memory_user": ("iMemoryImage", "\U0001F5BC️"),
    "math_add_user": ("iAdd", "➕"),
    "math_sub_user": ("iSub", "➖"),
    "math_mul_user": ("iMultiple", "✖️"),
    "math_avg_user": ("iAverage", "\U0001F4CA"),
    "math_div_user": ("iDivide", "➗"),
}

# The weekly challenges (see "the weekly challenges" above). KEEP IN STEP with ACTIVITIES,
# GAMES and CHALLENGES in weekly_challenge/weekly_challenge.py: a key missing here is never
# read. An activity's goal is on its _users row; a game has two, plays and score, on the
# player row, told apart by the `post` of the entry ("<post id>:plays").
WC_POST_ROW = "weekly_challenge"
WC_ACCEPT_ROW = "weekly_accept"
WC_COUNTED = ("open", "closed", "posting")    # replaced / failed: their acceptances started over
WC_GAMES = {
    "iadd": ("iAdd", "math_add_user", "➕"),
    "isub": ("iSub", "math_sub_user", "➖"),
    "imultiple": ("iMultiple", "math_mul_user", "✖️"),
    "iaverage": ("iAverage", "math_avg_user", "\U0001F4CA"),
    "idivide": ("iDivide", "math_div_user", "➗"),
    "imemory": ("iMemory", "object_memory_user", "\U0001F9E0"),
    "imatch": ("iMatch", "pairs_memory_user", "\U0001F004"),
    "imemoryimage": ("iMemoryImage", "image_memory_user", "\U0001F5BC️"),
}
# key: (title, emoji) and key: row_type, for every challenge there can be
CHALLENGE_NAME = {key: (info[0], info[1]) for key, info in ACTIVITIES.items()}
CHALLENGE_NAME["eyepushups"] = ("Eye pushups", "\U0001F441️")
CHALLENGE_ROW_TYPE = {key: key + "_users" for key in CHALLENGE_NAME}
for _game, (_title, _row, _emoji) in WC_GAMES.items():
    CHALLENGE_NAME[_game + "_plays"] = (_title + " · games played", _emoji)
    CHALLENGE_NAME[_game + "_score"] = (_title + " · best score", _emoji)
    CHALLENGE_ROW_TYPE[_game + "_plays"] = _row
    CHALLENGE_ROW_TYPE[_game + "_score"] = _row
CHALLENGERS_SHOWN = 3       # on the podium
CHALLENGE_LINES = 6         # challenges listed, most taken on first

MIN_BOARD_DAYS = 5          # as leaderboard.py: logged days needed to be ranked
# ... and on the month's own board: three days of showing up, so one big day is not a lead.
MIN_MONTH_BOARD_DAYS = 3
# Besides the headline three, an activity gets a podium once this many people logged it in
# the month: fewer, and a "top three" is most of the people doing it.
BOARD_MIN_ACTIVE = 5
# Never ranked, however many people log them. More hours asleep or fasting is not a goal
# (spotter's own tone for these: "never a number to beat"), and nobody should be placed
# company-wide by how much water they drink.
NO_BOARD = {"sleep", "fast", "hydrate"}
MAX_RECORDS = 14            # activity records listed; the three about showing up follow
# How many people must have logged an activity -- ever, opted-out people aside -- before
# it is shown. Both are recipe inputs; these are the defaults. A record needs a field to
# take it from, or "the channel record" is one or two people's private tally; and a
# section row for an activity one person tried once is noise beside the busy ones.
RECORD_MIN_PEOPLE = 4
SECTION_MIN_PEOPLE = 2
# ... except these, which earn their row on volume: one swimmer, many hours in the pool.
ALWAYS_SHOWN = ("swim",)
COMEBACK_DAYS = 21          # away at least this long before the month
NEW_BEST_MIN_SESSIONS = 3   # a "best" needs something to beat
NEW_BEST_MIN_GAIN = 1.05    # ... and beating it by 43 -> 44 is not worth a line
MAX_HIGHLIGHTS = 8
# The most highlight lines that may name one person. Somebody who does everything would
# otherwise fill the section on their own; past this their lines go to the next person.
MAX_MENTIONS = 2
DAY_MARKS = (10, 25, 50, 75, 100, 150, 200, 250, 300, 365)
# The round numbers one person's own running total can pass in an activity: "passed 1,000
# pushups". Few and far apart on purpose -- a first hundred is everybody's first fortnight,
# and a line for each would bury the ones worth saying. By how the activity is counted,
# with steps on a scale of their own; never for the activities nobody is ranked in.
PERSONAL_MARKS = {
    "count": (1000, 2500, 5000, 10000, 25000, 50000, 100000),
    "minutes": tuple(h * 60 for h in (10, 25, 50, 100, 250, 500, 1000)),
    "seconds": tuple(h * 3600 for h in (1, 2, 5, 10, 25, 50, 100)),
}
PERSONAL_STEP_MARKS = (250000, 500000, 1000000, 2000000, 3000000, 5000000, 10000000)
STEADY_MIN_WORKING_DAYS = 5
# How far from the 1st a saved snapshot may be and still stand for "the start of the
# month". Further than this and "added this month" would be a different stretch of time.
BASELINE_SLACK_DAYS = 4
MARATHON_KM = 42.195
# Columns in the month-by-month chart, this month included. Twelve is both the default and
# the most there can be: the chart is counted from the days each person logged, and
# spotter.py keeps the last 371 of those per activity (HEATMAP_KEEP_DAYS) -- a year for
# somebody who logs daily. A thirteenth column would quietly under-count them.
TREND_MONTHS = 12
CONSISTENT_MIN_DAYS = 5     # "most consistent" needs at least this many days logged


# ------------------------------------------------------------------------- small things

def truthy(value, default=False):
    """A recipe boolean, which may arrive as a bool or as text. Blank keeps the default."""
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return default
    return text in ("true", "yes", "1", "y", "on")


def whole_number(value, default, least=1):
    """A recipe number, which may arrive as text. Blank or nonsense keeps the default."""
    try:
        return max(least, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return default


def activity_list(value):
    """(keys, unknown) from a recipe input naming activities -- by key ("swim"), by
    title ("Swimming") or by trigger word ("iswam" is not known; "imeditate" is, as the
    key behind it) -- in the order given, each once."""
    by_title = {spec[0].lower(): key for key, spec in ACTIVITIES.items()}
    keys, unknown = [], []
    for word in re.split(r"[,;]+", str(value if value is not None else "").lower()):
        word = word.strip()
        if not word:
            continue
        plain_word = word.replace("_", " ")
        key = (word.replace(" ", "_") if word.replace(" ", "_") in ACTIVITIES
               else by_title.get(plain_word)
               or (word[1:] if word.startswith("i") and word[1:] in ACTIVITIES else None)
               or (word[:-1] if word.endswith("s") and word[:-1] in ACTIVITIES else None))
        if key is None:
            unknown.append(word)
        elif key not in keys:
            keys.append(key)
    return keys, unknown


def section_order(value):
    """(order, unknown, left_out) from the section_order input.

    Names are read loosely -- case, spaces, hyphens and "&" do not matter, and a few
    obvious aliases work ("walk" is "together"). "activities" expands to the four
    families. Blank is DEFAULT_ORDER. `unknown` are names that are no section; `left_out`
    are default sections the list did not mention, said so that a forgotten name does not
    quietly remove a section from the email.
    """
    text = str(value if value is not None else "").strip()
    if not text:
        return list(DEFAULT_ORDER), [], []
    order, unknown = [], []
    for word in re.split(r"[,;\n|]+", text.lower()):
        key = re.sub(r"[^a-z0-9]+", "_", word).strip("_")
        if not key or key in ("hero", "footer"):          # fixed: never reordered
            continue
        key = SECTION_ALIASES.get(key, key)
        for one in SECTION_GROUPS.get(key, (key,)):
            if one not in DEFAULT_ORDER:
                if word.strip() not in unknown:
                    unknown.append(word.strip())
            elif one not in order:
                order.append(one)
    if not order:
        return list(DEFAULT_ORDER), unknown, []
    return order, unknown, [s for s in DEFAULT_ORDER if s not in order]


SUBJECT_ICON = "\U0001F4AA"         # 💪: the channel is planks and pushups
SUBJECT_ICON_MAX = 16               # characters: one emoji, with its modifiers and joiners


def subject_icon(value):
    """(icon, warning) from the subject_icon input. Blank is SUBJECT_ICON; none / off / no is
    no icon, which is the subject as it was before it had one. A Slack :shortcode: means
    nothing in an inbox, so it is refused for the default, and so is anything long enough to
    be a sentence rather than an icon."""
    text = str(value if value is not None else "").strip()
    if not text:
        return SUBJECT_ICON, ""
    if text.lower() in ("none", "off", "no", "false", "0", "-"):
        return "", ""
    if re.match(r"^:[a-z0-9_+\-]+:$", text.lower()):
        return SUBJECT_ICON, ("subject_icon {} is a Slack shortcode, which shows as text in "
                              "email; used {} (paste the emoji itself)".format(text[:30],
                                                                                SUBJECT_ICON))
    if len(text) > SUBJECT_ICON_MAX:
        return SUBJECT_ICON, "subject_icon is too long for an icon; used {}".format(SUBJECT_ICON)
    return text, ""


def recipient_source(value, channel_id):
    """(source, warning): members, ever or active. The channel's members are the default
    when there is a channel to ask; without one the people active this month are."""
    word = re.sub(r"[^a-z]+", "_", str(value or "").strip().lower()).strip("_")
    if word in ("", "members", "member", "all", "everyone", "channel", "channel_members"):
        wanted = "members"
    elif word in ("ever", "ever_logged", "everyone_who_logged", "all_time"):
        wanted = "ever"
    elif word in ("active", "this_month", "month"):
        wanted = "active"
    else:
        return ("members" if channel_id else "active",
                "recipients_from '{}' is not members, ever or active; used the default".format(
                    str(value).strip()[:30]))
    if wanted == "members" and not channel_id:
        explicit = bool(word)
        return "active", ("recipients_from is members but channel_id is blank; sent to the "
                          "people active this month" if explicit else "")
    return wanted, ""


def activity_keys(value, default=ALWAYS_SHOWN):
    """Activities named in a recipe input, as a set of keys. Blank keeps the default;
    "none" is nobody."""
    if not str(value if value is not None else "").strip():
        return set(default)
    return set(activity_list(value)[0])


def parse_day(text):
    try:
        return datetime.strptime(str(text or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _numbers(value):
    out = []
    for part in str(value or "").split(","):
        try:
            out.append(int(float(part.strip())))
        except ValueError:
            pass
    return out


def _dates(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def session_list(row):
    """The whole comma-separated session list of an activity row."""
    return ",".join(str(row.get(c) or "") for c in TOTAL_COLUMNS if str(row.get(c) or "").strip())


def humanize(activity, value):
    """A number in units a person reads without decoding."""
    value = int(value or 0)
    kind = ACTIVITIES.get(activity, ("", "", "", "count", ""))[3]
    if kind == "count":
        return "{:,}".format(value)
    seconds = value if kind == "seconds" else value * 60
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "{:,}h {}m".format(hours, minutes) if minutes else "{:,}h".format(hours)
    if minutes:
        return "{}m {}s".format(minutes, secs) if secs else "{}m".format(minutes)
    return "{}s".format(secs)


def compact(value):
    """A figure short enough for a tile a third of a phone wide: 2,341,000 -> 2.34M."""
    value = int(value or 0)
    if value >= 1000000:
        return "{:.2f}".format(value / 1000000.0).rstrip("0").rstrip(".") + "M"
    if value >= 100000:
        return "{:.0f}K".format(value / 1000.0)
    return "{:,}".format(value)


def amount(activity, value):
    """The figure with what it counts: '412 pages read', '6h 40m of plank'."""
    return "{} {}".format(humanize(activity, value), ACTIVITIES[activity][4])


# The short unit of every activity counted in numbers, for a figure that stands on its own --
# a podium, the records, the milestones -- where "200" under Reading could be pages or
# minutes. Time needs none: "11h 59m" says what it is. (one, many)
UNITS = {"step": ("step", "steps"), "pushup": ("rep", "reps"), "pullup": ("rep", "reps"),
         "squat": ("rep", "reps"), "stairs": ("flight", "flights"), "read": ("page", "pages"),
         "write": ("page", "pages"), "hydrate": ("glass", "glasses"),
         "sleep": ("hour", "hours"), "fast": ("hour", "hours"),
         "cold_shower": ("shower", "showers")}


def with_unit(activity, value, short=False):
    """A figure with its unit and no more: '200 pages', '245 reps', '1.24M steps' (short:
    compact, for a narrow cell), '11h 59m'. See amount() for the phrase in a sentence."""
    number = compact(value) if short else humanize(activity, value)
    unit = UNITS.get(activity)
    if not unit:
        return number
    return "{} {}".format(number, unit[0] if int(value or 0) == 1 else unit[1])


def plural(count, one, many=None):
    return "{:,} {}".format(count, one if count == 1 else (many or one + "s"))


def day_span(start, end):
    """'1 to 11 October 2026', or 'October 2026' for a whole month."""
    last = calendar.monthrange(start.year, start.month)[1]
    if start.day == 1 and end.day == last:
        return start.strftime("%B %Y")
    if start == end:
        return "{} {}".format(start.day, start.strftime("%B %Y"))
    return "{} to {} {}".format(start.day, end.day, start.strftime("%B %Y"))


def short_day(day):
    return "{} {}".format(day.day, day.strftime("%b"))


# -------------------------------------------------------------------------------- http

def http_json(url, headers, payload=None, method="POST"):
    """(body, error, status). Never raises on an HTTP or network failure."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8")), None, response.getcode()
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, "{} {}: {}".format(url.split("/")[2], exc.code, detail[:300]), exc.code
    except Exception as exc:  # noqa: BLE001
        return None, "{}: {}".format(type(exc).__name__, str(exc)[:200]), 0


def decode_rows(body):
    """The query endpoint returns schema and data as arrays-of-arrays."""
    columns = [f.get("name") for group in body.get("schema", []) for f in group]
    return [dict(zip(columns, [v for group in row for v in group])) for row in body.get("data", [])]


def fetch_rows(token, where, select=None):
    """POST to the query endpoint, following continuation tokens."""
    headers = {"Authorization": "Bearer {}".format(token), "Content-Type": "application/json"}
    rows, continuation_token = [], None
    while True:
        payload = {"where": where, "select": select or SELECT_COLUMNS, "limit": 200}
        if continuation_token:
            payload["continuation_token"] = continuation_token
        body, error, _ = http_json(TABLE_URL, headers, payload)
        if error:
            raise ConnectionError("Workato {}".format(error))
        rows.extend(decode_rows(body))
        continuation_token = body.get("continuation_token")
        if not continuation_token:
            return rows


def load_local_rows(path):
    """Rows from a file, for testing: a plain list of rows keyed by column name, or a
    Workato export ({"message": [...]}) keyed by column id."""
    with open(path, "r", encoding="utf-8") as handle:
        body = json.load(handle)
    rows = body.get("message", body) if isinstance(body, dict) else body
    if isinstance(rows, dict):
        rows = rows.get("data", rows.get("rows", []))
    wanted = dict(COLUMNS, **CHALLENGE_COLUMNS)
    by_id = {name: uuid.replace("-", "_") for name, uuid in wanted.items()}
    return [{name: row.get(name, row.get(by_id[name])) for name in wanted}
            for row in rows if isinstance(row, dict)]


# ---------------------------------------------------------------- the month, and people

def channel_today(tz_offset, override=""):
    day = parse_day(override)
    if day:
        return day
    try:
        offset = int(tz_offset)
    except (TypeError, ValueError):
        offset = DEFAULT_TZ_OFFSET
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).date()


def month_window(today, wanted=""):
    """(first day, last day counted, whether that is the whole month), or None when the
    month asked for has not begun. Blank is this month: whole when today is its last day
    -- the day the email is meant to go out -- and "so far" on any day before."""
    word = str(wanted or "").strip().lower()
    year, month = today.year, today.month
    if word in ("previous", "last", "prev"):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    elif word and word not in ("current", "this"):
        match = re.match(r"^(\d{4})-(\d{1,2})$", word)
        if not match or not 1 <= int(match.group(2)) <= 12:
            return None
        year, month = int(match.group(1)), int(match.group(2))
    start = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    if start > today:
        return None
    end = min(last, today)
    return start, end, end == last


def gather(rows, start, end):
    """(people, active) from the activity and game rows.

    people  one entry per person who has NOT opted out: the days they logged, their first
            day, and each activity's sessions and days. `public` is false for someone
            whose every activity is logged by DM; they count, and are never named.
    active  {person id: name} for everyone with a log inside the month -- opted out or
            not, activity or game. It is the list the email is sent to, and nothing else.
    """
    people, active = {}, {}
    for row in rows:
        row_type = str(row.get("row_type") or "")
        pid = str(row.get("id") or "").strip()
        if not pid:
            continue
        if row_type in GAMES:
            played = parse_day(row.get("updated_at"))
            if played and start <= played <= end:
                active.setdefault(pid, str(row.get("name") or ""))
            continue
        activity = row_type[:-len("_users")] if row_type.endswith("_users") else ""
        values = _numbers(session_list(row))
        if activity not in ACTIVITIES or not values:
            continue
        days = [d for d in (parse_day(x) for x in _dates(row.get("heatmap_dates"))) if d]
        if any(start <= d <= end for d in days):
            active[pid] = active.get(pid) or str(row.get("name") or "")
        if truthy(row.get("leaderboard_optout")):
            continue
        person = people.setdefault(pid, {"name": "", "days": set(), "first": None,
                                         "rows": [], "streak": 0, "public": False})
        person["name"] = person["name"] or str(row.get("name") or "").strip()
        private = truthy(row.get("is_private"))
        person["public"] = person["public"] or not private
        try:
            person["streak"] = max(person["streak"], int(row.get("longest_streak") or 0))
        except (TypeError, ValueError):
            pass
        person["days"].update(days)
        first = parse_day(row.get("first_seen")) or (min(days) if days else None)
        if first and (person["first"] is None or first < person["first"]):
            person["first"] = first
        try:
            best_set = int(row.get("personal_best_single_set") or 0)
        except (TypeError, ValueError):
            best_set = 0
        person["rows"].append({"activity": activity, "values": values, "days": days,
                               "private": private, "best_set": best_set})
    return people, active


def window_stats(by_day, start, end):
    """(people ids, check-ins) from `start` to `end`. A check-in is one person on one day."""
    ids, checkins = set(), 0
    day = start
    while day <= end:
        day_ids = by_day.get(day)
        if day_ids:
            ids |= day_ids
            checkins += len(day_ids)
        day += timedelta(days=1)
    return ids, checkins


def month_facts(people, start, end, finished, today=None):
    """Everything about the month that the dated days alone can say. `today` says whether
    the last day counted is still being logged (it is, when the email goes out on it)."""
    by_day = {}
    for pid, person in people.items():
        for day in person["days"]:
            by_day.setdefault(day, set()).add(pid)
    ids, checkins = window_stats(by_day, start, end)

    # The same stretch of the month before: the 1st to the 11th against the 1st to the
    # 11th. A whole month is compared with a whole month.
    before_end = start - timedelta(days=1)
    before_start = before_end.replace(day=1)
    if not finished:
        before_end = min(before_end, before_start + (end - start))
    before_ids, before_checkins = window_stats(by_day, before_start, before_end)

    activities = {}
    for pid, person in people.items():
        for entry in person["rows"]:
            inside = len({d for d in entry["days"] if start <= d <= end})
            if inside:
                spot = activities.setdefault(entry["activity"], {"people": set(), "checkins": 0})
                spot["people"].add(pid)
                spot["checkins"] += inside

    # Logged on every working day -- up to yesterday when the email goes out on a day
    # that is still being logged, which the month-end email does: asking for today as
    # well would drop everybody who has not posted yet.
    open_day = (end >= today) if today else not finished
    last_counted = end - timedelta(days=1) if open_day else end
    working = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    working = [d for d in working if d.weekday() < 5 and d <= last_counted]
    steady = 0
    if len(working) >= STEADY_MIN_WORKING_DAYS:
        steady = sum(1 for p in people.values() if all(d in p["days"] for d in working))

    # In the channel's own first month everybody is new, which is not news.
    newcomers = sorted((p["first"], p["name"], pid) for pid, p in people.items()
                       if p["first"] and start <= p["first"] <= end)
    if len(newcomers) >= len(ids):
        newcomers = []
    counts = {d: len(v) for d, v in by_day.items() if start <= d <= end}
    return {"by_day": by_day, "ids": ids, "checkins": checkins, "activities": activities,
            "before_people": len(before_ids), "before_checkins": before_checkins,
            "before_label": before_start.strftime("%B"), "steady": steady,
            "working_days": len(working), "new_people": [pid for _, _, pid in newcomers],
            "days_active": len(counts), "counts": counts}


def month_history(month, start, end, first_day, months=TREND_MONTHS):
    """[(first day of the month, people active, check-ins)] for the last `months` months,
    oldest first and this one last -- only months the channel existed in. Exact: it is
    counted from the dated days, like everything else about who showed up."""
    history, cursor = [], start
    for _ in range(months):
        last = cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1])
        if first_day and last < first_day:
            break
        ids, checkins = window_stats(month["by_day"], cursor, min(last, end))
        history.append((cursor, len(ids), checkins))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return history[::-1]


def most_consistent(people, start, end):
    """(days, [person ids]) -- the most days anybody logged on in the month, and
    everybody who logged on that many. Everybody, because a tie is the usual case (the
    people who log daily all have the same number) and naming one of them would be a
    coin toss. (0, []) under CONSISTENT_MIN_DAYS."""
    counts = {pid: len([d for d in person["days"] if start <= d <= end])
              for pid, person in people.items()}
    top = max(counts.values() or [0])
    if top < CONSISTENT_MIN_DAYS:
        return 0, []
    return top, sorted((pid for pid, n in counts.items() if n == top),
                       key=lambda pid: people[pid]["name"])


def all_time(people):
    """Totals, sessions and bests over everything ever logged, from the session lists.

    As channel_summary.summarize: a best single day is the biggest session; a best single
    set comes from its column, and is ignored when it is larger than any session (a
    back-filled post once wrote a three-day sum there). A DM-logged activity adds to the
    totals and is skipped for the bests, which carry a name.
    """
    totals, sessions, bests, starts, doers = {}, {}, {}, [], {}
    for pid, person in people.items():
        if person["first"]:
            starts.append(person["first"])
        for entry in person["rows"]:
            activity, values = entry["activity"], entry["values"]
            doers.setdefault(activity, set()).add(pid)
            totals[activity] = totals.get(activity, 0) + sum(values)
            sessions[activity] = sessions.get(activity, 0) + len(values)
            if entry["private"] or not nameable(person):
                continue
            best = bests.setdefault(activity, {"day": 0, "day_by": "", "day_id": "",
                                               "set": 0, "set_by": "", "set_id": ""})
            if max(values) > best["day"]:
                best["day"], best["day_by"], best["day_id"] = max(values), person["name"], pid
            if 0 < entry["best_set"] <= max(values) and entry["best_set"] > best["set"]:
                best["set"], best["set_by"], best["set_id"] = \
                    entry["best_set"], person["name"], pid
    return {"totals": totals, "sessions": sessions, "bests": bests, "people": len(people),
            "doers": {a: len(ids) for a, ids in doers.items()},
            "logs": sum(sessions.values()), "since": min(starts) if starts else None}


def nameable(person):
    """Whether this person may be named at all: a real name, and at least one activity
    logged in the channel rather than by DM."""
    name = person.get("name") or ""
    return bool(name) and person.get("public", False) and not SLACK_USER_ID.match(name)


# ------------------------------------------------------- added this month (the snapshot)
#
# channel_summary.py saves the channel's totals every time it posts, in one row of the
# table, as JSON cut across three text columns and sealed with its length and a checksum.
# It is only READ here. The run nearest the 1st of the month is the baseline, and what
# has been added since is the difference. See "last time (snapshot)" in that file.

SNAPSHOT_ROW_TYPE = "channel_summary_snapshot"
STORE_COLUMNS = ("golden_dates", "heatmap_dates", "total")
SEAL = re.compile(r"^~(\d+):([0-9a-f]{8})~")


def parse_runs(text):
    """The saved runs, oldest first; [] for anything missing, damaged or unreadable."""
    text = str(text or "")
    match = SEAL.match(text)
    if match:
        body = text[match.end():]
        if (len(body) != int(match.group(1)) or
                "{:08x}".format(zlib.crc32(body.encode("utf-8")) & 0xFFFFFFFF) != match.group(2)):
            return []
        text = body
    try:
        data = json.loads(text) if text.strip() else None
    except ValueError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        return []
    runs = [r for r in data["runs"]
            if isinstance(r, dict) and isinstance(r.get("t"), dict) and parse_day(r.get("d"))]
    return sorted(runs, key=lambda r: r["d"])


def load_runs(token, local_file=""):
    """(runs, warning). A snapshot that cannot be read costs the month's volume figures,
    never the email."""
    if local_file:
        try:
            with open(local_file, "r", encoding="utf-8") as handle:
                return parse_runs(handle.read()), ""
        except IOError:
            return [], ""
    if not token:
        return [], ""
    try:
        rows = fetch_rows(token, {"row_type": {"$eq": SNAPSHOT_ROW_TYPE}}, list(STORE_COLUMNS))
    except ConnectionError as exc:
        return [], "snapshot not read ({}); volume shown all-time".format(str(exc)[:120])
    if not rows:
        return [], ""
    return parse_runs("".join(str(rows[0].get(c) or "") for c in STORE_COLUMNS)), ""


# ------------------------------------------------------ this step's own snapshot
#
# The weekly snapshot lands on a Friday, which is only by luck the 1st. So this step keeps
# one of its own: each run saves the channel's totals under today's date, and a run on the
# last day of a month is exactly "the totals as the next month began". Same storage as
# channel_summary.py's -- one row, a row_type of its own, JSON sealed with its length and a
# checksum and cut across STORE_COLUMNS -- and the same care: a row that cannot be read is
# reported and left alone, never written over.
#
# What is stored, per run:  {"d": date, "t": {activity: total}}

OWN_ROW_TYPE = "email_summary_snapshot"
OWN_RUNS_KEPT = 24
COLUMN_CHUNK = 9500                 # a Workato text column holds 10,000 characters
RECORD_KEY_ID = "81f48f77-2849-428a-b84d-1f11ff301b83"


def read_runs(text):
    """(runs, readable). Blank text is no history yet and readable; damaged text is not."""
    if not str(text or "").strip():
        return [], True
    runs = parse_runs(text)
    return runs, bool(runs) or '"runs":[]' in str(text).replace(" ", "")


def seal(text):
    return "~{}:{:08x}~{}".format(
        len(text), zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF, text)


def with_run(runs, run, keep=OWN_RUNS_KEPT):
    """History plus this run, oldest first. A second run on the same day replaces the
    first; the oldest go when there are too many or the row would overflow."""
    merged = sorted([r for r in runs if r.get("d") != run["d"]] + [run], key=lambda r: r["d"])
    merged = merged[-keep:]
    room = COLUMN_CHUNK * len(STORE_COLUMNS) - 64
    while len(merged) > 1 and len(json.dumps({"v": 1, "runs": merged},
                                             separators=(",", ":"))) > room:
        merged = merged[1:]
    return merged


class OwnSnapshot(object):
    """This step's row in the table. load() then save(); a save is refused when the row
    could not be read, rather than writing over it."""

    def __init__(self, token, row_type=OWN_ROW_TYPE):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.row_type = row_type
        self.record_id = ""
        self.block_reason = ""

    def load(self):
        # No select: the update path needs the $record_id metafield.
        body, error, _ = http_json(TABLE_URL, self.headers, {
            "where": {"row_type": {"$eq": self.row_type}}, "limit": 1})
        if error:
            self.block_reason = "the earlier read failed"
            return [], "own snapshot not read ({})".format(error[:120])
        rows = decode_rows(body)
        if not rows:
            return [], ""
        self.record_id = rows[0].get("$record_id") or ""
        runs, readable = read_runs("".join(str(rows[0].get(c) or "") for c in STORE_COLUMNS))
        if not readable:
            self.block_reason = "the existing row is unreadable"
            return [], "own snapshot row is unreadable; left as it is"
        return runs, ""

    def save(self, runs):
        if self.block_reason:
            return "snapshot not saved: " + self.block_reason
        text = seal(json.dumps({"v": 1, "runs": runs}, separators=(",", ":")))
        pieces = [text[i:i + COLUMN_CHUNK] for i in range(0, len(text), COLUMN_CHUNK)]
        if len(pieces) > len(STORE_COLUMNS):
            return "snapshot not saved: too big for {} columns".format(len(STORE_COLUMNS))
        fields = {RECORD_KEY_ID: self.row_type, COLUMNS["row_type"]: self.row_type,
                  COLUMNS["id"]: "email_summary", COLUMNS["name"]: self.row_type,
                  COLUMNS["updated_at"]: runs[-1]["d"]}
        # Unused columns are cleared so a shrinking snapshot leaves nothing stale.
        for index, column in enumerate(STORE_COLUMNS):
            fields[COLUMNS[column]] = pieces[index] if index < len(pieces) else ""
        document = {"$" + uuid: value for uuid, value in fields.items()}
        if self.record_id:
            url, method = RECORDS_URL + "/" + self.record_id, "PUT"
        else:
            url, method = RECORDS_URL, "POST"
        _, error, _ = http_json(url, self.headers, {"document": document}, method)
        return "snapshot save " + error if error else ""


class FileOwnSnapshot(object):
    """Offline stand-in for the row, for local testing."""

    def __init__(self, path):
        self.path = path
        self.block_reason = ""

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                runs, readable = read_runs(handle.read())
        except IOError:
            return [], ""
        if not readable:
            self.block_reason = "the existing file is unreadable"
            return [], "own snapshot file is unreadable; left as it is"
        return runs, ""

    def save(self, runs):
        if self.block_reason:
            return "snapshot not saved: " + self.block_reason
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(seal(json.dumps({"v": 1, "runs": runs}, separators=(",", ":"))))
        return ""


def month_volume(runs, facts, start, end, own=()):
    """What was added since the totals saved as the month began: {"since": that date,
    "exact": whether it was the eve of the 1st, "gain": {activity: added}, "base": those
    totals}, or None with nothing saved near enough.

    `own` are this step's runs and `runs` the weekly summary's. The one nearest the eve
    of the 1st is the baseline, this step's own winning a tie. A total that went DOWN
    (someone opted out) is unknown, not a negative month.

    "Exact" is a baseline taken as the month turned: one saved on the eve of the 1st, or
    this step's own run on the 1st itself -- the recipe scheduled early on the 1st with
    month = previous, which is the recommended schedule, saves its totals there.
    """
    target = start - timedelta(days=1)          # the totals as the month began
    near = []
    for rank, group in ((0, own), (1, runs)):
        for run in group:
            day = parse_day(run.get("d"))
            if day and abs((day - target).days) <= BASELINE_SLACK_DAYS and day < end \
                    and isinstance(run.get("t"), dict):
                near.append((abs((day - target).days), rank, run["d"], run))
    if not near:
        return None
    _distance, rank, _day, run = min(near, key=lambda item: item[:3])
    gain = {}
    for activity, now in facts["totals"].items():
        added = int(now) - int(run["t"].get(activity, 0) or 0)
        if added > 0:
            gain[activity] = added
    since = parse_day(run["d"])
    exact = since == target or (since == start and rank == 0)
    return {"since": since, "exact": exact, "gain": gain,
            "base": run["t"]} if gain else None


def ladder_position(activity, total):
    """Where a headline activity stands: laps banked, and the rung either side. Progress
    is measured from the last rung crossed to the next. As channel_summary.py."""
    spec = LADDERS[activity]
    total = int(total or 0)
    laps, within = divmod(total, spec["cycle"])
    reached = max([r for r in spec["rungs"] if r <= within] or [0])
    ahead = [r for r in spec["rungs"] if r > within]
    nxt = ahead[0] if ahead else spec["cycle"]
    return {"reached": laps * spec["cycle"] + reached,
            "target": laps * spec["cycle"] + nxt,
            "to_go": max(0, nxt - within),
            "share": (within - reached) / float(nxt - reached) if nxt > reached else 1.0}


def stop_for(activity, total):
    """Where a channel total stands between two milestones, whichever kind the activity
    climbs: its own ladder, or the round numbers. As channel_summary.stop_for.
    {"reached", "target", "to_go", "share"}, all as running totals."""
    if activity in LADDERS:
        return ladder_position(activity, total)
    total = int(total or 0)
    kind = ACTIVITIES[activity][3]
    per_hour = 3600 if kind == "seconds" else 60
    marks = COUNT_MARKS if kind == "count" else tuple(h * per_hour for h in HOUR_MARKS)
    ahead = [m for m in marks if m > total]
    if ahead:
        reached, target = max([m for m in marks if m <= total] or [0]), ahead[0]
    else:
        reached = (total // marks[-1]) * marks[-1]
        target = reached + marks[-1]
    return {"reached": reached, "target": target, "to_go": target - total,
            "share": (total - reached) / float(target - reached)}


# ----------------------------------------------------------------------------- badges
#
# Recognition worked out from the days a person logged and nothing else. Every badge is
# about showing up, never volume. COPIED from channel_summary/channel_summary.py (a
# Workato step is one file); test_email_summary.py fails if the two drift. Only the
# parts the email needs are here: the definitions, the day each was earned, and the
# highest tier of a family.
#
#   person = {"days": set of dates logged (any activity),
#             "rows": [{"activity": name, "days": [dates logged]}, ...]}
#
# (family, emoji, [(threshold, name, what it takes), ...]) -- order is the display order.
BADGE_FAMILIES = (
    ("streak", ":fire:", (
        (5, "Five in a Row", "logged on 5 working days in a row"),
        (10, "Two Weeks Strong", "logged on 10 working days in a row"),
        (20, "Month of Momentum", "logged on 20 working days in a row"),
        (50, "Unstoppable", "logged on 50 working days in a row"))),
    ("steady", ":repeat:", (
        (4, "Habit Forming", "logged in 4 weeks in a row"),
        (8, "Eight-Week Rhythm", "logged in 8 weeks in a row"),
        (12, "Quarter Strong", "logged in 12 weeks in a row"),
        (26, "Half-Year Regular", "logged in 26 weeks in a row"))),
    ("perfect", ":white_check_mark:", (
        (1, "Perfect Week", "logged on every working day of a week"),
        (4, "Four Perfect Weeks", "four weeks with every working day logged"),
        (12, "Twelve Perfect Weeks", "twelve weeks with every working day logged"))),
    ("weekend", ":sunny:", (
        (1, "Weekend Warrior", "logged on both Saturday and Sunday"),
        (5, "Weekend Regular", "five weekends logged on both days"))),
    ("allround", ":jigsaw:", (
        (3, "All-Rounder", "3 different activities in one week"),
        (5, "Renaissance", "5 different activities in one week"))),
    ("triple", ":trident:", (
        (1, "Triple Threat", "steps, pushups and plank all in one week"),)),
    ("explorer", ":compass:", (
        (5, "Explorer", "tried 5 different activities"),
        (10, "Adventurer", "tried 10 different activities"),
        (15, "Trailblazer", "tried 15 different activities"))),
    ("month", ":calendar:", (
        (15, "Month Strong", "logged on 15 days in one month"),
        (20, "Full Month", "logged on 20 days in one month"))),
    ("first", ":seedling:", (
        (1, "First Step", "logged for the very first time"),)),
    ("founding", ":star:", (
        (1, "Founding Member", "joined in the channel's first four weeks"),)),
)
FOUNDING_DAYS = 28
TRIPLE = ("step", "pushup", "plank")

BADGES = {}
for _order, (_family, _emoji, _tiers) in enumerate(BADGE_FAMILIES):
    for _tier, (_need, _name, _about) in enumerate(_tiers):
        BADGES["{}_{}".format(_family, _need)] = {
            "id": "{}_{}".format(_family, _need), "family": _family, "emoji": _emoji,
            "need": _need, "name": _name, "about": _about, "tier": _tier,
            "order": _order, "prestige": _tier * 100 + (100 - _order)}


def _monday(day):
    return day - timedelta(days=day.weekday())


def badge_dates(person, today, channel_first=None):
    """{badge id: the day it was earned} for everything this person has earned by `today`.

    A badge is dated to the day the last thing it needed happened -- the Friday that
    completes a Perfect Week, the Sunday that completes a Weekend Warrior -- so it can be
    announced the moment that log is made. "New since last time" is answered from the
    badges the last post stored, not from these dates, so a log made after the last post
    is never missed.
    """
    days = sorted(d for d in person["days"] if d <= today)
    if not days:
        return {}
    earned = {}

    def award(family, need, when):
        key = "{}_{}".format(family, need)
        if key in BADGES and (key not in earned or when < earned[key]):
            earned[key] = when

    def needs(family):
        return [need for need, _name, _about in
                next(t for f, _e, t in BADGE_FAMILIES if f == family)]

    logged = set(days)
    award("first", 1, days[0])
    if channel_first is not None and days[0] <= channel_first + timedelta(days=FOUNDING_DAYS - 1):
        award("founding", 1, days[0])

    # Working days in a row. Weekends are neutral: they neither extend a run nor break it.
    run, day = 0, days[0]
    while day <= today:
        if day.weekday() < 5:
            if day in logged:
                run += 1
                for need in needs("streak"):
                    if run == need:
                        award("streak", need, day)
            else:
                run = 0
        day += timedelta(days=1)

    by_week = {}
    for day in days:
        by_week.setdefault(_monday(day), []).append(day)

    # Weeks in a row with at least one log; a week is a Monday-to-Sunday calendar week.
    run, previous = 0, None
    for monday in sorted(by_week):
        run = run + 1 if previous is not None and monday - previous == timedelta(days=7) else 1
        for need in needs("steady"):
            if run == need:
                award("steady", need, min(by_week[monday]))
        previous = monday

    perfect, weekends = [], []
    for monday in sorted(by_week):
        weekdays = {d.weekday() for d in by_week[monday]}
        if {0, 1, 2, 3, 4} <= weekdays and monday + timedelta(days=4) <= today:
            perfect.append(monday + timedelta(days=4))
        if {5, 6} <= weekdays:
            weekends.append(monday + timedelta(days=6))
    for count, when in enumerate(perfect, start=1):
        for need in needs("perfect"):
            if count == need:
                award("perfect", need, when)
    for count, when in enumerate(weekends, start=1):
        for need in needs("weekend"):
            if count == need:
                award("weekend", need, when)

    # Variety inside one week: how many different activities, and the three that are the
    # channel's headline.
    first_in_week = {}
    first_ever = {}
    for entry in person["rows"]:
        for day in entry["days"]:
            if day > today:
                continue
            seen = first_in_week.setdefault(_monday(day), {})
            if entry["activity"] not in seen or day < seen[entry["activity"]]:
                seen[entry["activity"]] = day
            if entry["activity"] not in first_ever or day < first_ever[entry["activity"]]:
                first_ever[entry["activity"]] = day
    for firsts in first_in_week.values():
        ordered = sorted(firsts.values())
        for need in needs("allround"):
            if len(ordered) >= need:
                award("allround", need, ordered[need - 1])
        if all(a in firsts for a in TRIPLE):
            award("triple", 1, max(firsts[a] for a in TRIPLE))

    ordered = sorted(first_ever.values())
    for need in needs("explorer"):
        if len(ordered) >= need:
            award("explorer", need, ordered[need - 1])

    by_month = {}
    for day in days:
        by_month.setdefault((day.year, day.month), []).append(day)
    for month_days in by_month.values():
        for need in needs("month"):
            if len(month_days) >= need:
                award("month", need, month_days[need - 1])
    return earned


def top_badges(ids):
    """The highest tier of each family among `ids`, in display order."""
    best = {}
    for badge_id in ids:
        badge = BADGES.get(badge_id)
        if badge and (badge["family"] not in best or badge["tier"] > best[badge["family"]]["tier"]):
            best[badge["family"]] = badge
    return sorted(best.values(), key=lambda b: b["order"])


# Unicode for each badge family; the :shortcode: in BADGE_FAMILIES is Slack's.
BADGE_EMOJI = {"streak": "\U0001F525", "steady": "\U0001F501", "perfect": "✅",
               "weekend": "☀️", "allround": "\U0001F9E9", "triple": "\U0001F531",
               "explorer": "\U0001F9ED", "month": "\U0001F4C5", "first": "\U0001F331",
               "founding": "⭐"}
# Said by the welcome line and by the channel's age; not news in a monthly email.
BADGE_SKIP = {"first", "founding"}


def badges_this_month(people, start, end):
    """[(badge, [person ids])], most prestigious first: badges earned inside the month.
    The highest new tier in a family is the one named, as in the Friday post."""
    firsts = [p["first"] for p in people.values() if p["first"]]
    channel_first = min(firsts) if firsts else None
    found = {}
    for pid, person in people.items():
        if not nameable(person):
            continue
        dates = badge_dates(person, end, channel_first)
        fresh = [i for i, day in dates.items()
                 if start <= day <= end and BADGES[i]["family"] not in BADGE_SKIP]
        for badge in top_badges(fresh):
            found.setdefault(badge["id"], []).append(pid)
    ranked = sorted(found, key=lambda i: (-BADGES[i]["prestige"], BADGES[i]["name"]))
    return [(BADGES[i], sorted(found[i], key=lambda p: people[p]["name"])) for i in ranked]


# ---------------------------------------------------------------------------- journey
#
# The channel's steps, added together, walk a route around the world. COPIED from
# channel_summary/channel_summary.py (and spotter.py); test_email_summary.py fails if
# they drift. The flags are Slack shortcodes and are not shown in the email.
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


def stop_name(stop):
    """A route stop as it starts a sentence: "the Grand Canyon" -> "The Grand Canyon"."""
    return stop[0][:1].upper() + stop[0][1:]


# ------------------------------------------------------------------------- highlights

def names_html(names, limit=4, unnamed=0):
    """<b>A</b>, <b>B</b> and <b>C</b> -- or ... and 2 more. `unnamed` is how many others
    there are who cannot be named; they are counted in the "more"."""
    shown = ["<b>{}</b>".format(escape(n)) for n in names[:limit]]
    more = max(0, len(names) - limit) + unnamed
    if more:
        shown.append("{} more".format(more))
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def highlights(people, month, facts, volume, start, end, show_names):
    """[(emoji, html)] -- what happened this month, most worth saying first. People are
    named for what they did, never ranked, and only when show_names allows it; with it
    off the same lines are said as counts. A line names a person once, and nobody is named
    in more than MAX_MENTIONS lines: the lists of people (bests, round numbers, days
    logged) go to those named least so far, and the rest are counted in the "and N more"."""
    found = []
    mentions = {}               # person id -> lines so far that name them

    def nameables(pids):
        return [p for p in pids if show_names and nameable(people[p])]

    def named(pids):
        return [people[p]["name"] for p in nameables(pids)]

    def mention(pids):
        for pid in pids:
            mentions[pid] = mentions.get(pid, 0) + 1

    def spread(pids):
        """`pids`, best first, each once and without anybody already named MAX_MENTIONS
        times; those named least so far come first, and a tie keeps the order given."""
        fresh = []
        for pid in pids:
            if pid not in fresh and mentions.get(pid, 0) < MAX_MENTIONS:
                fresh.append(pid)
        return sorted(fresh, key=lambda pid: mentions.get(pid, 0))

    def who(pids, noun="person", nouns="people", limit=4):
        names = named(pids)
        if not names:
            return "<b>{}</b>".format(plural(len(pids), noun, nouns))
        mention(nameables(pids)[:limit])
        return names_html(names, limit, unnamed=len(pids) - len(names))

    new = month["new_people"]
    if new:
        found.append((90, "\U0001F44B", "{} logged for the first time this month.".format(
            who(new))))

    # Channel milestones crossed since the month's baseline, and stops on the walk.
    if volume:
        for activity in HEADLINE:
            now = ladder_position(activity, facts["totals"].get(activity, 0))["reached"]
            was = ladder_position(activity, volume["base"].get(activity, 0))["reached"]
            if now > was:
                found.append((86, "\U0001F389", "Together we passed <b>{}</b>.".format(
                    amount(activity, now))))
        arrived = journey_arrivals(volume["base"].get("step", 0), facts["totals"].get("step", 0))
        if arrived:
            lap, index, stop = arrived[-1]
            if index == len(ROUTE) - 1:
                text = ("{} completed a lap of the world on foot: <b>{:,.0f} km</b>, "
                        "together.".format(JOURNEY_NAME, LAP_KM))
            else:
                text = "{} reached <b>{}</b> ({}).".format(
                    JOURNEY_NAME, escape(stop_name(stop)), escape(stop[4]))
            found.append((88, "\U0001F30D", text))

    back = []
    for pid, person in people.items():
        inside = [d for d in person["days"] if start <= d <= end]
        before = [d for d in person["days"] if d < start]
        if inside and before and (min(inside) - max(before)).days >= COMEBACK_DAYS \
                and pid not in new:
            back.append(((min(inside) - max(before)).days, person["name"], pid))
    if back:
        back.sort(key=lambda item: (-item[0], item[1]))
        found.append((70, "\U0001F64C", "Welcome back, {}: logging again after {} away.".format(
            who([pid for _, _, pid in back]),
            "a few weeks" if back[0][0] < 60 else "a couple of months")))

    top, leaders = most_consistent(people, start, end)
    if leaders:
        span = (end - start).days + 1
        names = named(leaders)
        if names and len(names) == len(leaders):
            mention(leaders[:4])            # names_html shows the first four
            text = "Most consistent this month: {}, who logged on <b>{} of {} days</b>.".format(
                names_html(names), top, span)
        else:
            text = "Most consistent this month: <b>{}</b> logged on <b>{} of {} days</b>.".format(
                plural(len(leaders), "person", "people"), top, span)
        found.append((68, "\U0001F4C6", text))

    if month["steady"]:
        found.append((66, "\U0001F525", "<b>{}</b> logged on every working day of the month{}."
                      .format(plural(month["steady"], "person", "people"),
                              "" if month["finished"] else " so far")))

    # A personal best set this month. A person who logged an activity on k days of the
    # month made at least k sessions in it, and they are the last k in the list -- so the
    # best of those against the best before them is a best set this month. It can miss
    # one; it cannot invent one.
    bests = []
    for pid, person in people.items():
        if not nameable(person):
            continue
        for entry in person["rows"]:
            recent = len({d for d in entry["days"] if start <= d <= end})
            values, activity = entry["values"], entry["activity"]
            if entry["private"] or activity not in BEST_PHRASE or not recent:
                continue
            earlier, latest = values[:-recent], values[-recent:]
            if len(earlier) >= NEW_BEST_MIN_SESSIONS and \
                    max(latest) >= max(earlier) * NEW_BEST_MIN_GAIN:
                bests.append((max(latest) / float(max(earlier)), person["name"], pid, activity,
                              max(latest), max(earlier)))
    bests.sort(key=lambda item: (-item[0], item[1]))
    # Two lines, two people: each one's biggest jump. Everybody else's is in the count.
    biggest = {}
    for best in bests:
        biggest.setdefault(best[2], best)
    chosen = spread(list(biggest))[:2] if show_names else []
    if chosen:
        mention(chosen)
        for place, pid in enumerate(chosen):
            _, name, _, activity, now, was = biggest[pid]
            text = "<b>{}</b> set a new personal best, {}: <b>{}</b> (was {})".format(
                escape(name), BEST_PHRASE[activity], amount(activity, now),
                humanize(activity, was))
            if place == len(chosen) - 1 and len(bests) > len(chosen):
                text += ", and {} more this month".format(len(bests) - len(chosen))
            found.append((64 - place * 0.1, "\U0001F3C5", text + "."))
    elif bests:
        found.append((64, "\U0001F3C5", "<b>{}</b> set this month.".format(
            plural(len(bests), "new personal best", "new personal bests"))))

    # A round number passed in somebody's own all-time total: "passed 1,000 pushups". The
    # amounts are not dated, so the total as the month began is not known exactly; but the
    # k days logged this month are at least the last k sessions, so everything before
    # those is the most it can have been. A mark above that and at or below the total now
    # was passed this month. Like the bests: it can miss one, it cannot invent one. A row
    # with logs dated after the month (an email sent late) is left alone, because those
    # sessions cannot be told from the month's.
    passed = []
    for pid, person in people.items():
        if not nameable(person):
            continue
        for entry in person["rows"]:
            activity, values = entry["activity"], entry["values"]
            recent = len({d for d in entry["days"] if start <= d <= end})
            if entry["private"] or activity in NO_BOARD or not 0 < recent <= len(values) \
                    or any(d > end for d in entry["days"]):
                continue
            ladder = PERSONAL_STEP_MARKS if activity == "step" \
                else PERSONAL_MARKS[ACTIVITIES[activity][3]]
            crossed = [m for m in ladder if sum(values[:-recent]) < m <= sum(values)]
            if crossed:
                passed.append((-ladder.index(crossed[-1]), person["name"], pid, activity,
                               crossed[-1]))
    passed.sort()
    # One line per person: their biggest mark. Somebody who passed two is one of the people
    # in "and N more", not two of the three named.
    biggest = {}
    for item in passed:
        biggest.setdefault(item[2], item)
    chosen = spread(list(biggest))[:3] if show_names else []
    if chosen:
        mention(chosen)
        text = "; ".join("<b>{}</b> passed <b>{}</b>".format(
            escape(biggest[pid][1]), amount(biggest[pid][3], biggest[pid][4])) for pid in chosen)
        if len(biggest) > len(chosen):
            text += "; and {} more".format(len(biggest) - len(chosen))
        found.append((65, "\U0001F3AF", text + (", all time." if len(biggest) == 1
                                                 else ". All-time totals.")))
    elif passed:
        found.append((65, "\U0001F3AF", "<b>{}</b> passed this month.".format(
            plural(len(passed), "personal all-time milestone"))))

    marks = []
    for pid, person in people.items():
        before = len([d for d in person["days"] if d < start])
        now = len([d for d in person["days"] if d <= end])
        crossed = [m for m in DAY_MARKS if before < m <= now]
        if crossed and pid not in new:
            marks.append((-max(crossed), person["name"], pid, max(crossed)))
    marks.sort()
    by_id = {pid: (name, mark) for _, name, pid, mark in marks}
    chosen = spread([pid for _, _, pid, _ in marks])[:3] if show_names else []
    if chosen and all(nameable(people[pid]) for pid in chosen):
        mention(chosen)
        text = "; ".join("<b>{}</b> passed <b>{} days</b> logged".format(
            escape(by_id[pid][0]), by_id[pid][1]) for pid in chosen)
        if len(marks) > len(chosen):
            text += "; and {} more".format(len(marks) - len(chosen))
        found.append((60, "\U0001F31F", text + "."))
    elif marks:
        found.append((60, "\U0001F31F", "<b>{}</b> passed a round number of days logged."
                      .format(plural(len(marks), "person", "people"))))

    if month["counts"]:
        top = max(month["counts"].values())
        leaders = [d for d, c in month["counts"].items() if c == top]
        if top >= 3 and len(leaders) == 1:
            found.append((40, "⚡", "{} was the most active day: <b>{} people</b> logged.".format(
                leaders[0].strftime("%A {} %B").format(leaders[0].day), top)))

    found.sort(key=lambda item: -item[0])
    return [(icon, text) for _, icon, text in found[:MAX_HIGHLIGHTS]]


def board_order(month, extra=(), min_active=BOARD_MIN_ACTIVE):
    """The activities that get a podium, in the order they are shown: the headline
    activities; then the ones the recipe asked for (`extra`, in the order given); then
    every other activity that `min_active` or more people logged this month, busiest
    first. Never one of NO_BOARD, asked for or not."""
    def field(activity):
        return len(month["activities"].get(activity, {}).get("people", ()))

    asked = [a for a in extra if a not in HEADLINE and a not in NO_BOARD]
    others = sorted((a for a in month["activities"]
                     if a not in HEADLINE and a not in NO_BOARD and a not in asked
                     and field(a) >= min_active), key=lambda a: (-field(a), a))
    return list(HEADLINE) + asked + others


def podium(people, month, show_names, extra=(), min_active=BOARD_MIN_ACTIVE):
    """[(activity, [(name, total, person id)])] -- the all-time top three of the
    activities in board_order. Ranked as the weekly leaderboard ranks them: on the running
    total, among people with MIN_BOARD_DAYS logged days. An activity logged by DM is never
    placed, and one with nobody to place gets no board."""
    if not show_names:
        return []
    boards = []
    for activity in board_order(month, extra, min_active):
        entries = []
        for pid, person in people.items():
            for entry in person["rows"]:
                if (entry["activity"] == activity and not entry["private"] and nameable(person)
                        and len(set(entry["days"])) >= MIN_BOARD_DAYS):
                    entries.append((sum(entry["values"]), person["name"], pid))
        entries.sort(key=lambda item: (-item[0], item[1]))
        if entries:
            boards.append((activity, [(name, total, pid) for total, name, pid in entries[:3]]))
    return boards


def month_amount(entry, start, end):
    """(amount, days logged) of one person's activity from `start` to `end`, or None when
    the row cannot be lined up. The amounts are not dated, so the two lists spotter keeps are
    paired from their recent end, as weekly_challenge.day_amounts pairs them: with as many
    sessions as days every one has its day; with more (a second log in a day) the latest
    sessions take the days and the sum can only come out a little low; with fewer there is
    nothing to pair."""
    values, days = entry["values"], entry["days"]
    if not days or len(values) < len(days):
        return None
    inside = [(d, v) for d, v in zip(days, values[len(values) - len(days):])
              if start <= d <= end]
    return sum(v for _, v in inside), len({d for d, _ in inside})


def month_podium(people, month, show_names, start, end, extra=(), min_active=BOARD_MIN_ACTIVE):
    """[(activity, [(name, amount this month, person id)])] -- the month's top three, in the
    same activities as podium(), on what each person logged from `start` to `end` (see
    month_amount), among people with MIN_MONTH_BOARD_DAYS logged days in it. An activity
    logged by DM is never placed, and one with nobody to place gets no board."""
    if not show_names:
        return []
    boards = []
    for activity in board_order(month, extra, min_active):
        entries = []
        for pid, person in people.items():
            if not nameable(person):
                continue
            for entry in person["rows"]:
                got = month_amount(entry, start, end) \
                    if entry["activity"] == activity and not entry["private"] else None
                if got and got[0] > 0 and got[1] >= MIN_MONTH_BOARD_DAYS:
                    entries.append((got[0], person["name"], pid))
        entries.sort(key=lambda item: (-item[0], item[1]))
        if entries:
            boards.append((activity, [(name, total, pid) for total, name, pid in entries[:3]]))
    return boards


def records(people, facts, show_names, min_people=RECORD_MIN_PEOPLE):
    """(rows, unclaimed) -- the channel records there are to beat.

    rows       [(emoji, what, value, holder, holder's id)]: the best of each activity that at least
               `min_people` people have ever logged, the headline three first and then
               the most widely done; for an activity done in sets, the best single set
               and the most in a day. Then three that are about showing up rather than
               volume: the longest streak, the most days logged and the most activities
               tried.
    unclaimed  titles of activities nobody holds a record in yet -- an open door.

    With show_names off the holder and the id are left blank and the figure stands alone.
    """
    def holder(name, pid):
        return (name, pid) if show_names else ("", "")

    rows = []
    order = [a for a in HEADLINE if a in facts["bests"]] + sorted(
        (a for a in facts["bests"] if a not in HEADLINE),
        key=lambda a: (-facts["doers"].get(a, 0), -facts["sessions"].get(a, 0), a))
    for activity in order:
        best = facts["bests"][activity]
        if activity not in BEST_PHRASE or facts["doers"].get(activity, 0) < min_people:
            continue
        title, icon = ACTIVITIES[activity][0], ACTIVITIES[activity][1]
        if activity in SET_BASED and best["set"]:
            rows.append((icon, "{}: {}".format(title, BEST_PHRASE[activity]),
                         with_unit(activity, best["set"]))
                        + holder(best["set_by"], best.get("set_id", "")))
            if best["day"] > best["set"]:
                rows.append((icon, "{}: {}".format(title, DAY_PHRASE[activity]),
                             with_unit(activity, best["day"]))
                            + holder(best["day_by"], best.get("day_id", "")))
        elif best["day"]:
            phrase = "biggest session" if activity in SET_BASED else BEST_PHRASE[activity]
            rows.append((icon, "{}: {}".format(title, phrase),
                         with_unit(activity, best["day"]))
                        + holder(best["day_by"], best.get("day_id", "")))
    rows = rows[:MAX_RECORDS]

    named = sorted(((pid, p) for pid, p in people.items() if nameable(p)),
                   key=lambda item: item[1]["name"])
    if named:
        pid, streak = max(named, key=lambda item: item[1]["streak"])
        if streak["streak"] >= 3:
            rows.append(("\U0001F525", "Longest streak", "{} days".format(streak["streak"]))
                        + holder(streak["name"], pid))
        pid, steady = max(named, key=lambda item: len(item[1]["days"]))
        if len(steady["days"]) >= 5:
            rows.append(("\U0001F4C5", "Most days logged", "{} days".format(len(steady["days"])))
                        + holder(steady["name"], pid))

        def variety(item):
            return len({e["activity"] for e in item[1]["rows"] if not e["private"]})
        pid, tried = max(named, key=variety)
        if variety((pid, tried)) >= 3:
            rows.append(("\U0001F9ED", "Most activities tried",
                         plural(variety((pid, tried)), "activity", "activities"))
                        + holder(tried["name"], pid))

    unclaimed = [ACTIVITIES[a][0] for a in ACTIVITIES
                 if a in BEST_PHRASE and not (facts["bests"].get(a) or {}).get("day")]
    return rows, unclaimed


def game_lines(rows, show_names):
    """[(emoji, title, players, games played, top score, holder, holder's id)] for each game
    somebody has scored in. A player is anybody with a game played or a score; games played
    is everybody's total_planks added up, all time (a game is not dated, so it cannot be
    counted by month). Opted-out players are left out, as on the game boards."""
    lines = []
    for row_type, (title, emoji) in GAMES.items():
        scored, players, played = [], 0, 0
        for row in rows:
            if row.get("row_type") != row_type or truthy(row.get("leaderboard_optout")):
                continue
            try:
                score = int(row.get("personal_best_single_set") or 0)
                secs = float(row.get("total") or 0)
            except (TypeError, ValueError):
                continue
            try:
                games = max(0, int(float(row.get("total_planks") or 0)))
            except (TypeError, ValueError):
                games = 0
            if score > 0 or games > 0:
                players += 1
                played += games
            if score > 0:
                scored.append((-score, secs or float("inf"), str(row.get("name") or ""),
                               str(row.get("id") or "").strip()))
        if scored:
            scored.sort()
            name = scored[0][2]
            holder = name if show_names and name and not SLACK_USER_ID.match(name) else ""
            lines.append((emoji, title, players, played, -scored[0][0], holder,
                          scored[0][3] if holder else ""))
    return lines


# ------------------------------------------------------------- the weekly challenges

def challenge_entries(raw):
    """The weekly entries a row's `content` holds ({"wc": [...]}), or [] when it holds
    anything else. As weekly_entries in weekly_challenge.py, less strict: only `post` and
    `state` are needed here."""
    try:
        data = json.loads(str(raw or "").strip() or "{}")
    except ValueError:
        return []
    found = data.get("wc") if isinstance(data, dict) else None
    return [e for e in found or [] if isinstance(e, dict) and e.get("post")]


def challenge_entry(raw):
    """One entry held on its own as json (as a weekly_accept row holds it), or None."""
    try:
        entry = json.loads(str(raw or "").strip() or "null")
    except ValueError:
        return None
    return entry if isinstance(entry, dict) and entry.get("post") else None


def challenge_week(post):
    """The Monday a post's week starts on: week_key, or failing that the start of its id
    ("2026-10-19-1729...")."""
    return parse_day(post.get("week_key")) or parse_day(str(post.get("id") or "")[:10])


def month_posts(posts, start, end):
    """The posts whose week belongs to the month: its Sunday falls in it, and it has begun by
    `end` (so a month "so far" counts the week in progress). A replaced or failed post is
    left out: its acceptances started over on the post that replaced it."""
    last = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    out = []
    for post in posts:
        monday = challenge_week(post)
        status = str(post.get("status") or "").strip().lower()
        if monday and status in WC_COUNTED and str(post.get("id") or "").strip() \
                and start <= monday + timedelta(days=6) <= last and monday <= end:
            out.append(post)
    return out


def split_challenge_rows(rows):
    """(posts, acceptances, rows holding entries) out of one list of rows, as a local file
    has them all together."""
    posts, accepts, holders = [], [], []
    kinds = set(CHALLENGE_ROW_TYPE.values())
    for row in rows:
        row_type = str(row.get("row_type") or "")
        if row_type == WC_POST_ROW:
            posts.append(row)
        elif row_type == WC_ACCEPT_ROW:
            accepts.append(row)
        elif row_type in kinds and challenge_entries(row.get("content")):
            holders.append(row)
    return posts, accepts, holders


def read_challenges(token, channel_id, start, end):
    """(posts, acceptances, rows holding entries, warning) from the table: the month's posts,
    their acceptance rows, and the takers' rows of those challenges. Three small queries; one
    that fails costs the section, never the email."""
    try:
        where = {"row_type": {"$eq": WC_POST_ROW}}
        if channel_id:
            where = {"$and": [where, {"slack_channel_id": {"$eq": channel_id}}]}
        posts = month_posts(fetch_rows(token, where, ["id", "week_key", "status",
                                                      "slack_channel_id"]), start, end)
        if not posts:
            return [], [], [], ""
        accepts = fetch_rows(
            token, {"$and": [{"row_type": {"$eq": WC_ACCEPT_ROW}},
                             {"id": {"$in": sorted({str(p["id"]) for p in posts})}}]},
            ["id", "grant_type", "group_id", "member_name", "status", "content"])
        takers = sorted({str(a.get("group_id") or "").strip() for a in accepts} - {""})
        kinds = sorted({CHALLENGE_ROW_TYPE[str(a.get("grant_type"))] for a in accepts
                        if str(a.get("grant_type")) in CHALLENGE_ROW_TYPE})
        holders = []
        if takers and kinds:
            holders = fetch_rows(
                token, {"$and": [{"row_type": {"$in": kinds}}, {"id": {"$in": takers}}]},
                ["id", "row_type", "name", "content", "leaderboard_optout"])
    except ConnectionError as exc:
        return [], [], [], "challengers left out: the weekly challenges could not be read ({})" \
            .format(str(exc)[:120])
    return posts, accepts, holders, ""


def challengers_of(posts, accepts, holders, rows, start, end, finished, show_names):
    """The month's weekly challenges, in figures.

    posts      weekly_challenge rows (any month: the month's are picked here)
    accepts    weekly_accept rows: one per person per goal taken on
    holders    the takers' rows of the activities and games, whose `content` holds each
               goal as spotter (or the game) left it: state done once it was cleared
    rows       the activity and game rows read for the rest of the email: anybody with
               leaderboard_optout on any row of theirs is left out of every figure here

    Returns {weeks, people, taken, cleared, finished, top, sweep, challenges}: top the best
    CHALLENGERS_SHOWN by goals cleared (fewer taken on breaks a tie: the better rate), sweep
    everyone who cleared every goal they took on; both [] with show_names off. challenges is
    one {key, taken, people, cleared} per challenge, most taken on first.
    """
    posts = {str(p["id"]): p for p in month_posts(posts, start, end)}
    hidden, names = set(), {}
    for row in list(rows) + list(holders):
        pid = str(row.get("id") or "").strip()
        if truthy(row.get("leaderboard_optout")):
            hidden.add(pid)
        name = str(row.get("name") or "").strip()
        if pid and name and not names.get(pid):
            names[pid] = name
    goals = {}                                      # (post id, key, person) -> entry state
    for row in holders:
        for entry in challenge_entries(row.get("content")):
            goals[(str(row.get("row_type")), str(row.get("id") or "").strip(),
                   str(entry["post"]))] = str(entry.get("state") or "")
    seen, people, per_key = set(), {}, {}
    for accept in accepts:
        post_id = str(accept.get("id") or "")
        key = str(accept.get("grant_type") or "")
        pid = str(accept.get("group_id") or "").strip()
        if post_id not in posts or key not in CHALLENGE_ROW_TYPE or not pid or pid in hidden \
                or (str(accept.get("status") or "in").strip().lower() or "in") != "in" \
                or (post_id, key, pid) in seen:
            continue
        seen.add((post_id, key, pid))
        game_kind = key.rsplit("_", 1)[1] if key.endswith(("_plays", "_score")) else ""
        entry_post = post_id + (":" + game_kind if game_kind else "")
        state = goals.get((CHALLENGE_ROW_TYPE[key], pid, entry_post))
        if state is None:                           # never logged it: the goal waits here
            state = str((challenge_entry(accept.get("content")) or {}).get("state") or "")
        done = state == "done"
        name = str(accept.get("member_name") or "").strip() or names.get(pid, "")
        person = people.setdefault(pid, {"id": pid, "name": name, "taken": 0, "cleared": 0})
        person["name"] = person["name"] or name
        person["taken"] += 1
        person["cleared"] += done
        line = per_key.setdefault(key, {"key": key, "taken": 0, "cleared": 0, "who": set()})
        line["taken"] += 1
        line["cleared"] += done
        line["who"].add(pid)

    def named(person):
        return show_names and person["name"] and not SLACK_USER_ID.match(person["name"])

    ranked = sorted((p for p in people.values() if p["cleared"] and named(p)),
                    key=lambda p: (-p["cleared"], p["taken"], p["name"].lower()))
    sweep = sorted((p for p in people.values()
                    if p["cleared"] and p["cleared"] == p["taken"] and named(p)),
                   key=lambda p: (-p["cleared"], p["name"].lower()))
    order = {key: i for i, key in enumerate(CHALLENGE_ROW_TYPE)}
    challenges = sorted(({"key": k, "taken": v["taken"], "people": len(v["who"]),
                          "cleared": v["cleared"]} for k, v in per_key.items()),
                        key=lambda c: (-c["taken"], -c["cleared"], order[c["key"]]))
    return {"weeks": len(posts), "people": len(people),
            "taken": sum(p["taken"] for p in people.values()),
            "cleared": sum(p["cleared"] for p in people.values()), "finished": finished,
            "top": ranked[:CHALLENGERS_SHOWN], "sweep": sweep, "challenges": challenges}


# --------------------------------------------------------------- "in brief" (Azure)

BRIEF_SYSTEM = (
    "You write the opening paragraph of a monthly company-wide email about an internal "
    "Slack channel where colleagues log what they did that day. The readers are every "
    "employee, senior leadership included, and most of them are not in the channel.\n"
    "It is the month-end recap, sent on the last day of the month: look back over the "
    "month as a whole, in the past tense. Only if the period is marked as still in "
    "progress, write about the month so far instead.\n"
    "Tone: warm, vivid and professional -- the register of a well-edited internal "
    "newsletter, written with some craft: concrete verbs, a fresh image or turn of phrase, "
    "sentences of different lengths. It should read as if a person who enjoyed the month "
    "wrote it, not as a list of totals in a sentence. No slang, no hype, no puns, no "
    "exclamation marks, no emoji, no \"Hi all\" and no sign-off.\n"
    "Rules:\n"
    "- Keep it short: it is a welcome at the top of the email, and every figure and detail "
    "follows below it. Never open with \"So far this month\" or \"In October\".\n"
    "- Do not name, describe or single out any individual.\n"
    "- Use only the figures you are given, written exactly as given. Never estimate, "
    "round, combine or invent a number, and do not spell a figure out in words.\n"
    "- Make no health, medical or productivity claims.\n"
    "- Never label or describe the channel by its purpose or kind. Say \"the channel\" or "
    "\"the group\", or use the channel's name exactly as given in the facts.\n"
    "- If you name an activity, use the word the facts use (steps, plank, workouts): the "
    "email picks it out in colour. Use such a word only for the activity itself, never in "
    "an idiom (not \"first steps\").\n"
    "- Write only about the period you are given. Do not mention all-time totals, distances "
    "or a virtual walk; the email covers those separately.\n"
    "Reply with a JSON object with exactly these two keys:\n"
    '- "headline": a short, lively title for the month, 4 to 8 words, in sentence case, no '
    "figures, no full stop -- a newsletter headline, not a label (not \"October progress\").\n"
    '- "body": 1 or 2 short sentences, at most 30 words in all: a warm welcome to the '
    "month's recap with one or two of its highlights (the busiest activity, how many took "
    "part), ending by saying the details are below. Wrap at most 2 figures in double "
    "asterisks, each with only the word it counts and never an "
    "activity's name, like **63 check-ins** or **9 activities** (not **63 check-ins for "
    "steps**). Use no other formatting."
)
BRIEF_ATTEMPTS = 2
# (key, the longest it may be). The email shows them as a title and a paragraph.
BRIEF_PARTS = (("headline", 80), ("body", 260))
WELLBEING = re.compile(r"well[\s-]*being|wellness", re.IGNORECASE)
# Bold figures in the paragraph. The tiles beside it already show the month's numbers;
# past two, with the activities in colour as well, nothing in it stands out.
MAX_EMPHASIS = 2
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
EMPHASIS = re.compile(r"\*\*(.+?)\*\*")
# With no marks from the model, the figures it used are emphasised for it: a number and
# what it counts, never a date ("1 and 11 October" stays plain).
FIGURE = re.compile(
    r"\b\d[\d,]*(?:\.\d+)?\s(?:colleagues?|people|person|check-ins?|activities|activity|"
    r"km|steps|pushups|marathons?|sessions?)\b")


def numbers_in(text):
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text)}


def plain(text):
    """The text without its emphasis marks."""
    return str(text or "").replace("**", "")


def first_emphasis(text, keep=MAX_EMPHASIS):
    """The text with only its first `keep` **marks**; the rest are made plain."""
    seen = []

    def one(match):
        seen.append(match)
        return match.group(0) if len(seen) <= keep else match.group(1)
    return EMPHASIS.sub(one, text)


def tidy_emphasis(text):
    """The text with emphasis marks that can be trusted: whole pairs and short spans, and
    no more than MAX_EMPHASIS of them (the first ones are kept). Anything else and the marks
    are dropped rather than guessed at; a paragraph with none has its first figures marked
    instead."""
    spans = EMPHASIS.findall(text)
    if text.count("**") % 2 or any(len(s) > 48 for s in spans):
        text = plain(text)
    if "**" not in text:
        text = FIGURE.sub(lambda m: "**{}**".format(m.group(0)), text)
    return first_emphasis(text)


def emphasis_html(text, colour, mark=None):
    """Escaped text, with **marked** spans in bold. The marks are the only formatting a
    model's words are ever given; everything else it writes is escaped. `mark`, when given,
    is a step of our own that runs on the escaped text before the bold goes in (see
    activity_marks): it is never handed the model's words unescaped."""
    escaped = escape(str(text or ""))
    return EMPHASIS.sub(r'<b style="color:{};">\1</b>'.format(colour),
                        mark(escaped) if mark else escaped)


def brief_facts(ctx):
    """The month as plain lines for the model: totals only, no names."""
    month, facts, volume = ctx["month"], ctx["facts"], ctx["volume"]
    lines = ["channel: #{}".format(ctx["channel_name"]),
             "period: {}{}".format(ctx["span"], " (the whole month, now ending)"
                                   if ctx["finished"] else " (month still in progress)"),
             "people who logged at least once: {}".format(len(month["ids"])),
             "check-ins (one person on one day): {:,}".format(month["checkins"]),
             "different activities logged: {}".format(len(month["activities"]))]
    if month["new_people"]:
        lines.append("people who logged for the first time: {}".format(len(month["new_people"])))
    busiest = sorted(month["activities"], key=lambda a: -len(month["activities"][a]["people"]))
    lines.append("most widely logged activities: {}".format(
        ", ".join(ACTIVITIES[a][0].lower() for a in busiest[:5])))
    # What each did, so the paragraph can be specific about the leaders. Names of activities
    # only; nobody is named.
    lines.append("check-ins by activity, busiest first: {}".format(", ".join(
        "{} {:,}".format(ACTIVITIES[a][0].lower(), month["activities"][a]["checkins"])
        for a in busiest_first(month["activities"])[:5])))
    if month["counts"]:
        day = max(month["counts"], key=lambda d: (month["counts"][d], d))
        lines.append("busiest day: {} {} {}, with {} people logging".format(
            day.strftime("%A"), day.day, day.strftime("%B"), month["counts"][day]))
    if volume:
        for activity in HEADLINE:
            if volume["gain"].get(activity):
                lines.append("added since {}: {}".format(
                    short_day(volume["since"]), amount(activity, volume["gain"][activity])))
    # The walk is not handed to the model: it turned "1,576 km, all time" into a flat
    # sentence with no idea what the walk is. It has a section of its own (together).
    return "\n".join(lines)


def template_brief(ctx):
    """The same summary without a model: always true, always available."""
    month, volume = ctx["month"], ctx["volume"]
    name = ctx["start"].strftime("%B")
    busiest = sorted(month["activities"], key=lambda a: (-len(month["activities"][a]["people"]), a))
    kinds = [ACTIVITIES[a][0].lower() for a in busiest[:3]]
    # A welcome and a pointer, not a summary: the tiles and sections under it are the summary.
    body = "{} **{}** {} in, with **{}** between them{}.".format(
        "In {},".format(name) if ctx["finished"] else "So far in {},".format(name),
        plural(len(month["ids"]), "colleague"),
        "checked" if ctx["finished"] else "have checked",
        plural(month["checkins"], "check-in"),
        " and {} out in front".format(kinds[0]) if kinds else "")
    body += " The details, and who led the way, are below."
    return {"headline": "{} at a glance".format(name if ctx["finished"] else name + " so far"),
            "body": first_emphasis(body)}


class Azure(object):
    def __init__(self, api_key, url=None):
        self.url = url or AZURE_URL
        self.api_key = str(api_key or "").strip()
        self.error = ""

    def chat(self, system, user, temperature=0.7, max_tokens=400):
        if not self.api_key:
            self.error = "azure_api_key is blank"
            return None
        payload = {"messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                   "temperature": temperature, "max_tokens": max_tokens,
                   "response_format": {"type": "json_object"}}
        body, error, _ = http_json(
            self.url, {"api-key": self.api_key, "Content-Type": "application/json"}, payload)
        if error:
            self.error = "azure " + error
            return None
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.error = "azure: unexpected response shape"
            return None


def check_brief(text, facts_text, limit=600):
    """'' when the text can go out, otherwise why not. The model writes for the whole
    company, so it is held to the figures: every number it uses must be one it was given,
    and it may not bring markup, links or a wall of text. Emphasis marks are not markup
    here; they are checked and turned into bold separately (see tidy_emphasis)."""
    text = plain(text)
    if not text.strip():
        return "nothing in it"
    if len(text) > limit:
        return "too many words"
    if re.search(r"[<>*`]|https?://|\n\s*- ", text):
        return "markup or a link"
    # The channel is not a "wellbeing channel" to the people who run it, and a model told
    # not to says it anyway now and then ("Highlights from the Wellbeing Channel"): the
    # rule is held here, not only asked for, and a reply that breaks it is tried again
    # and then written from the template. (Unless the channel is itself called that, which
    # the facts say: its own name is not a label.)
    if WELLBEING.search(text) and not WELLBEING.search(facts_text):
        return "a label for the channel"
    stray = numbers_in(text) - numbers_in(facts_text)
    if stray:
        return "a figure it was not given ({})".format(", ".join(sorted(stray)[:3]))
    return ""


# Words a headline keeps capitalised in sentence case, and the small ones title case leaves
# alone (so they say nothing about whether a headline is in it).
PROPER = {d.lower() for d in calendar.month_name[1:] + calendar.day_name[:]}
SMALL_WORDS = {"a", "an", "the", "and", "or", "but", "of", "in", "on", "to", "for", "with",
               "at", "by", "as", "from", "into"}


def sentence_case(headline):
    """'A Month of Movement and Mindfulness' -> 'A month of movement and mindfulness'. Only
    a headline in title case is changed (most of its words capitalised); the first word,
    months and days, a #channel and an acronym keep their capitals."""
    words = headline.split()
    telling = [w for w in words[1:] if w.lower() not in SMALL_WORDS and not w.startswith("#")
               and w.lower().strip(",:;") not in PROPER]
    if len(words) < 3 or not telling or \
            sum(1 for w in telling if w[:1].isupper()) * 2 <= len(telling):
        return headline
    return " ".join([words[0]] + [
        w if w.startswith("#") or w.lower().strip(",:;") in PROPER or (w.isupper() and len(w) > 1)
        else w.lower() for w in words[1:]])


def read_brief(reply, facts_text):
    """(brief, why not) from the model's reply: the two parts, each checked."""
    try:
        data = json.loads(reply)
    except (TypeError, ValueError):
        return None, "a reply that was not JSON"
    if not isinstance(data, dict):
        return None, "a reply that was not a JSON object"
    brief = {}
    for key, limit in BRIEF_PARTS:
        text = re.sub(r"\s+", " ", str(data.get(key) or "")).strip().strip('"').strip()
        reason = check_brief(text, facts_text, limit)
        if reason:
            return None, "{} in its {}".format(reason, key)
        brief[key] = text
    brief["headline"] = sentence_case(plain(brief["headline"]).rstrip("."))
    brief["body"] = tidy_emphasis(brief["body"])
    return brief, ""


def month_brief(llm, ctx):
    """(brief, whether the model wrote it, warning). The brief is
    {"headline", "body"}; only the body carries **emphasis** marks."""
    fallback = template_brief(ctx)
    if not llm or not llm.api_key:
        return fallback, False, ""
    facts_text = brief_facts(ctx)
    reason = ""
    for _ in range(BRIEF_ATTEMPTS):
        reply = llm.chat(BRIEF_SYSTEM, facts_text)
        if reply is None:
            return fallback, False, "summary written from the template ({})".format(llm.error)
        brief, reason = read_brief(reply, facts_text)
        if brief:
            return brief, True, ""
    return fallback, False, "summary written from the template (the model's had {})".format(reason)


def brief_text(brief):
    """The brief as one plain paragraph, for the step's output."""
    return "{}. {}".format(brief["headline"], plain(brief["body"]))


# ------------------------------------------------------------------------- recipients

def slack_profile(token, user_id):
    """(profile dict, error) from users.info. One retry when Slack asks us to slow down."""
    url = "{}?{}".format(SLACK_USER_URL, urllib_parse.urlencode({"user": user_id}))
    headers = {"Authorization": "Bearer {}".format(token)}
    for attempt in range(2):
        request = urllib_request.Request(url, headers=headers, method="GET")
        try:
            with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            if exc.code == 429 and attempt == 0:
                try:
                    wait = float(exc.headers.get("Retry-After") or 1)
                except (TypeError, ValueError):
                    wait = 1.0
                time.sleep(min(max(wait, 0.5), 5.0))
                continue
            return None, "http {}".format(exc.code)
        except Exception as exc:  # noqa: BLE001
            return None, type(exc).__name__
        if not body.get("ok"):
            return None, str(body.get("error") or "unknown")
        return body.get("user") or {}, None
    return None, "rate limited"


CHANNEL_ID = re.compile(r"^[CGD][A-Z0-9]{8,}$")


def channel_members(token, channel_id):
    """(ids, error) -- everyone in the channel, from conversations.members, page by page.
    `error` is '' on success; on any failure the ids so far are returned with it, and the
    caller decides (the email never goes out to half a channel without saying so)."""
    if not token:
        return [], "slack_bot_token is blank"
    if not CHANNEL_ID.match(channel_id or ""):
        return [], ("channel_id must be the channel's id, which starts with C (open the "
                    "channel, then About, at the bottom) -- not its name")
    ids, cursor = [], ""
    headers = {"Authorization": "Bearer {}".format(token)}
    for _page in range(MEMBER_PAGES):
        params = {"channel": channel_id, "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        url = "{}?{}".format(SLACK_MEMBERS_URL, urllib_parse.urlencode(params))
        body = None
        for attempt in range(2):
            request = urllib_request.Request(url, headers=headers, method="GET")
            try:
                with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib_error.HTTPError as exc:
                if exc.code == 429 and attempt == 0:
                    try:
                        wait = float(exc.headers.get("Retry-After") or 1)
                    except (TypeError, ValueError):
                        wait = 1.0
                    time.sleep(min(max(wait, 0.5), 5.0))
                    continue
                return ids, "http {}".format(exc.code)
            except Exception as exc:  # noqa: BLE001
                return ids, type(exc).__name__
        if body is None:
            return ids, "rate limited"
        if not body.get("ok"):
            return ids, str(body.get("error") or "unknown")
        ids.extend(str(m) for m in body.get("members") or [])
        cursor = str((body.get("response_metadata") or {}).get("next_cursor") or "")
        if not cursor:
            return ids, ""
    return ids, ""


# Errors that will be the same for every user, so there is no point asking again.
FATAL_SLACK_ERRORS = ("missing_scope", "invalid_auth", "not_authed", "account_inactive",
                      "token_revoked", "token_expired", "not_allowed_token_type")


def find_recipients(token, active, domains=(), lookup=None):
    """(recipients, missing, warning).

    recipients  [{"slack_id", "name", "email"}], by name, one per address.
    missing     [{"slack_id", "name", "reason"}] for everyone active with no address to
                send to -- a guest, a deactivated account, a failed lookup.
    """
    lookup = lookup or slack_profile
    recipients, missing, seen, warning = [], [], set(), ""
    if not token:
        return [], [{"slack_id": pid, "name": name, "reason": "no slack_bot_token"}
                    for pid, name in sorted(active.items())], \
            "slack_bot_token is blank, so no email addresses were looked up"
    started = time.time()
    stop_reason = ""
    for pid, name in sorted(active.items(), key=lambda item: (item[1].lower(), item[0])):
        reason = ""
        if stop_reason:
            reason = stop_reason
        elif not SLACK_USER_ID.match(pid):
            reason = "not a Slack user id"
        elif time.time() - started > LOOKUP_BUDGET_SECONDS:
            stop_reason = reason = "lookup time budget reached"
            warning = "stopped looking up addresses after {}s".format(LOOKUP_BUDGET_SECONDS)
        else:
            user, error = lookup(token, pid)
            profile = (user or {}).get("profile") or {}
            email = str(profile.get("email") or "").strip().lower()
            if error in FATAL_SLACK_ERRORS:
                stop_reason = reason = "slack: " + error
                warning = "users.info failed with {}{}".format(
                    error, " (the bot token needs users:read.email)"
                    if error == "missing_scope" else "")
            elif error:
                reason = "slack: " + error
            elif user.get("deleted"):
                reason = "deactivated account"
            elif user.get("is_bot"):
                reason = "a bot"
            elif not email:
                reason = "no email on the Slack profile (guest, or users:read.email missing)"
            elif domains and email.split("@")[-1] not in domains:
                reason = "outside the allowed domains"
            elif email not in seen:
                seen.add(email)
                recipients.append({"slack_id": pid, "email": email,
                                   "name": name or str(profile.get("real_name") or "")})
        if reason:
            missing.append({"slack_id": pid, "name": name, "reason": reason})
    return recipients, missing, warning


# ------------------------------------------------------- saved Slack profiles
#
# Asking Slack for each person, one call each, is fine for sixty people and not for three
# hundred: the calls are rate limited and this step has a clock. So what Slack said is
# kept: one row per person, row_type plank_you_very_much_user, holding their name, email
# address and profile photo. A run reads those rows in one query, asks Slack only about
# the people it has no row for, and appends a row for each of them.
#
# Nothing here goes stale by itself and nothing is refreshed: a changed photo or address,
# or somebody who has left, is corrected by deleting their row, after which the next run
# asks Slack again. Who is IN the channel is not kept -- that is asked every run -- so a
# row for somebody who has left the channel is simply never used.
#
#   id            the person's Slack id          name    their name
#   total         their email address            plank_photo   their photo URL ('' = none)
#   updated_at    the day Slack was asked

PROFILE_ROW_TYPE = "plank_you_very_much_user"
PROFILE_COLUMNS = ("id", "name", "total", "plank_photo", "updated_at")
PROFILE_SAVE_SECONDS = 20       # a row is one call to write; the rest wait for the next run


def saved_profile(row):
    """A saved row as users.info would have answered, so everything downstream reads a
    saved person and a freshly asked one the same way."""
    photo = str(row.get("plank_photo") or "").strip()
    return {"saved": True,
            "profile": {"email": str(row.get("total") or "").strip().lower(),
                        "real_name": str(row.get("name") or "").strip(),
                        "image_72": photo, "is_custom_image": bool(photo)}}


class ProfileStore(object):
    """The saved profiles in the table. load() then add(); nothing is added when the rows
    could not be read, because a person already there would be written a second time."""

    def __init__(self, token, row_type=PROFILE_ROW_TYPE):
        self.token = token
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.row_type = row_type
        self.block_reason = ""

    def load(self):
        """({person id: profile}, warning)."""
        try:
            rows = fetch_rows(self.token, {"row_type": {"$eq": self.row_type}},
                              list(PROFILE_COLUMNS))
        except ConnectionError as exc:
            self.block_reason = "the saved profiles could not be read"
            return {}, "saved profiles not read ({}); asked Slack instead".format(str(exc)[:120])
        return {str(r.get("id") or "").strip(): saved_profile(r)
                for r in rows if str(r.get("id") or "").strip()}, ""

    def add(self, pid, name, email, photo, day):
        """'' when the row was written, otherwise why not."""
        if self.block_reason:
            return self.block_reason
        fields = {RECORD_KEY_ID: "{}_{}".format(self.row_type, pid),
                  COLUMNS["row_type"]: self.row_type, COLUMNS["id"]: pid, COLUMNS["name"]: name,
                  COLUMNS["total"]: email, COLUMNS["plank_photo"]: photo,
                  COLUMNS["updated_at"]: day}
        _, error, _ = http_json(RECORDS_URL, self.headers, {
            "document": {"$" + uuid: value for uuid, value in fields.items()}}, "POST")
        return error or ""


class FileProfileStore(object):
    """Offline stand-in for the rows, for local testing: a JSON list of them."""

    def __init__(self, path):
        self.path = path
        self.rows = []

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                self.rows = json.load(handle)
        except (IOError, ValueError):
            self.rows = []
        return {str(r.get("id")): saved_profile(r) for r in self.rows if r.get("id")}, ""

    def add(self, pid, name, email, photo, day):
        self.rows.append({"id": pid, "name": name, "total": email, "plank_photo": photo,
                          "updated_at": day})
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.rows, handle)
        return ""


class Profiles(object):
    """Who everybody is, asked at most once: from the saved rows when there is one, from
    users.info when not. The photos beside the names and the addresses the email is sent
    to come from the same answer. `fresh` are the people Slack was asked about this run,
    which are the ones worth saving. A lookup that failed is not kept: the next ask tries
    again, so a blip while fetching a photo cannot cost somebody their email."""

    def __init__(self, saved=None):
        self.found = dict(saved or {})
        self.fresh = {}
        self.asked = 0

    def __call__(self, token, pid):
        if pid not in self.found:
            self.asked += 1
            user, error = slack_profile(token, pid)
            if error:
                return user, error
            self.found[pid] = self.fresh[pid] = user
        return self.found[pid], None


def save_profiles(store, profiles, names, day):
    """(rows written, warning). A row for everybody Slack was asked about this run who can
    be written to: a bot, a deactivated account or somebody with no address is not kept,
    so they are asked about again rather than remembered wrongly."""
    started, saved, waiting = time.time(), 0, 0
    for pid, user in sorted(profiles.fresh.items()):
        profile = (user or {}).get("profile") or {}
        email = str(profile.get("email") or "").strip().lower()
        if user.get("deleted") or user.get("is_bot") or not email:
            continue
        if time.time() - started > PROFILE_SAVE_SECONDS:
            waiting += 1
            continue
        name = str(profile.get("real_name") or user.get("real_name") or names.get(pid) or "")
        error = store.add(pid, name.strip(), email, profile_photo(user), day)
        if error:
            return saved, "profiles not saved ({})".format(str(error)[:120])
        saved += 1
    return saved, ("{} left to save on the next run".format(plural(waiting, "profile"))
                   if waiting else "")


PHOTO_BUDGET_SECONDS = 12   # photos are decoration: never hold the email up for them


def profile_photo(user):
    """The person's own profile photo as a small public https URL, or '' when they have
    not set one (Slack's stand-in is a grey silhouette; initials look better) or the URL
    is not one an email should carry."""
    profile = (user or {}).get("profile") or {}
    # 72px: the largest it is shown is 36, and a phone draws that with twice the dots.
    url = str(profile.get("image_72") or profile.get("image_48") or "").strip()
    stand_in = profile.get("is_custom_image") is False or \
        (profile.get("is_custom_image") is None
         and ("gravatar.com" in url or "/img/avatars/" in url))
    if stand_in or not url.startswith("https://") or len(url) > 500 or \
            re.search(r'["<>\s]', url):
        return ""
    return url


def holder_photos(token, pids, profiles):
    """({person id: photo URL, or '' for initials}, warning) for the people named on the
    boards and in the records. Somebody whose lookup failed is simply absent, and gets
    initials too; an error that will be the same for everyone stops the asking."""
    photos, started = {}, time.time()
    for pid in pids:
        if pid in photos or not SLACK_USER_ID.match(pid):
            continue
        if time.time() - started > PHOTO_BUDGET_SECONDS:
            return photos, "some photos not fetched (took over {}s); initials shown".format(
                PHOTO_BUDGET_SECONDS)
        user, error = profiles(token, pid)
        if error in FATAL_SLACK_ERRORS:
            return photos, "photos not shown (slack: {})".format(error)
        if not error:
            photos[pid] = profile_photo(user)
    return photos, ""


# ------------------------------------------------------------------------------- html
#
# Email is not the web. Outlook lays out with Word's engine and Gmail strips <style>, so
# everything here is tables, inline styles and system fonts: no flexbox, no grid, no web
# fonts, no background images, no JavaScript. Rounded corners and the hero's gradient are
# the only things a client may drop, and both degrade to the plain version of the same
# design. The only images are the banners the recipe passes in.

# Short on purpose: it is repeated in every cell (Outlook does not inherit a font into a
# nested table), and Gmail clips a message at about 102 KB.
FONT = "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
INK, MUTED, FAINT, LINE = "#1F2937", "#5B6472", "#8A93A2", "#E5E7EB"
PAGE, CARD, TINT, BRAND = "#F3F5F9", "#FFFFFF", "#F8FAFC", "#0056D2"
WIDTH = 640
PAD = 32
# The calendar's heat scale, quiet to very active ("busy" read as busy at work, the
# opposite of what the colours mean -- the same lesson channel_summary.py learned). Each
# square carries two numbers, so each level pairs its fill with two inks: a strong one for
# the count of people, which is the news, and a soft one for the date, which only says
# where you are. (fill, count, date)
HEAT = (("#F1F5F9", FAINT, "#A7B0BE"), ("#DBEAFE", "#1E3A8A", "#7088B8"),
        ("#93C5FD", "#1E3A8A", "#3E64A8"), ("#2563EB", "#FFFFFF", "#B9CEF8"))
MEDALS = ("\U0001F947", "\U0001F948", "\U0001F949")

TABLE = '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'


def font(size=15, color=INK, weight=400, line=1.5, more=""):
    """A text style. No font family: that is set once, on the body and on each section,
    and inherited -- written into every paragraph it was an eighth of the email, and Gmail
    hides everything past about 102 KB behind "View entire message"."""
    return "font-size:{}px;line-height:{};{}color:{};{}".format(
        size, line, "" if weight == 400 else "font-weight:{};".format(weight), color, more)


def para(text, size=15, color=INK, weight=400, top=0, line=1.5, more=""):
    return '<p style="margin:{};{}">{}</p>'.format(
        "{}px 0 0".format(top) if top else 0, font(size, color, weight, line, more), text)


def band(inner, top=28, bottom=0, side=PAD, background=""):
    """One full-width row of the email."""
    return ('<tr><td class="px" {}style="padding:{}px {}px {}px {}px;font-family:{};">{}'
            '</td></tr>').format('bgcolor="{}" '.format(background) if background else "",
                                 top, side, bottom, side, FONT, inner)


def image_url_ok(url):
    """(url, warning). Only a public https image can be shown by an email client."""
    url = str(url or "").strip()
    if not url:
        return "", ""
    host = urllib_parse.urlparse(url).netloc.lower()
    if not url.startswith("https://") or len(url) > 2000 or '"' in url:
        return "", "image ignored (not an https URL): {}".format(url[:60])
    if host.endswith("slack.com") or host.endswith("slack-files.com") or host.endswith("slack-edge.com"):
        return "", ("image ignored: a Slack file URL needs a Slack sign-in and shows as a "
                    "broken image in email ({})".format(url[:60]))
    return url, ""


def resolve_images(hero, raw):
    """({section: url}, [warnings]) from hero_image_url and section_image_urls, which may
    arrive as a dict or as the JSON text Workato hands objects through as."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return resolve_images(hero, {})[0], ["section_image_urls is not valid JSON; ignored"]
    images, warnings = {}, []
    wanted = dict(raw) if isinstance(raw, dict) else {}
    wanted["hero"] = hero or wanted.get("hero") or ""
    known = {"hero"} | {s[0] for s in SECTIONS} | set(OTHER_SECTIONS)
    for key, url in wanted.items():
        key = str(key).strip().lower()
        if key not in known:                # "challenger", "weekly challenges" ...: as section_order
            key = SECTION_ALIASES.get(re.sub(r"[^a-z0-9]+", "_", key).strip("_"), key)
        if key not in known:
            if str(url or "").strip():
                warnings.append("section_image_urls: no section called '{}'".format(key))
            continue
        url, warning = image_url_ok(url)
        if warning:
            warnings.append("{}: {}".format(key, warning))
        if url:
            images[key] = url
    return images, warnings


def picture(url, alt):
    return ('<img src="{}" alt="{}" width="{}" style="display:block;width:100%;'
            'max-width:{}px;height:auto;border:0;outline:none;border-radius:10px;">'
            .format(escape(url, quote=True), escape(alt, quote=True), WIDTH - 2 * PAD,
                    WIDTH - 2 * PAD))


def section_head(key, title, about, colour, emoji, images):
    """A section's banner: the image when one is set, the coloured band when not."""
    if images.get(key):
        head = picture(images[key], title)
    else:
        head = ('{} bgcolor="{}" style="background-color:{};border-radius:10px;"><tr>'
                '<td style="padding:14px 18px;{}">'
                '<span style="font-size:20px;line-height:1;">{}</span>&nbsp;&nbsp;{}</td>'
                '</tr></table>').format(
                    TABLE, colour, colour, font(18, "#FFFFFF", 700, 1.3), emoji, escape(title))
    return head + (para(escape(about), 14, MUTED, top=10) if about else "")


def bar(share, colour, height=10):
    """A progress bar as a two-cell table, which every client draws."""
    filled = int(round(max(0.0, min(1.0, float(share))) * 100))
    cells = ""
    if filled > 0:
        cells += ('<td width="{}%" bgcolor="{}" height="{}" style="background-color:{};'
                  'font-size:0;line-height:0;border-radius:{};">&nbsp;</td>').format(
                      filled, colour, height, colour,
                      "5px" if filled == 100 else "5px 0 0 5px")
    if filled < 100:
        cells += ('<td width="{}%" bgcolor="{}" height="{}" style="background-color:{};'
                  'font-size:0;line-height:0;border-radius:{};">&nbsp;</td>').format(
                      100 - filled, LINE, height, LINE,
                      "5px" if filled == 0 else "0 5px 5px 0")
    return "{}><tr>{}</tr></table>".format(TABLE, cells)


def hero_html(ctx, images):
    """The banner picture, when there is one, and the month. The channel's name sits above
    the month only without a picture: a banner says it already, and saying it twice was a
    third heading before anything happened. Mid-month the days counted share the month's
    line ("October 2026 · 1-27 Oct, so far") instead of taking a second one."""
    out = ""
    if images.get("hero"):
        out += ('<tr><td style="padding:0;"><img src="{}" alt="{}" width="{}" style="display:'
                'block;width:100%;max-width:{}px;height:auto;border:0;outline:none;"></td></tr>'
                .format(escape(images["hero"], quote=True),
                        escape("#" + ctx["channel_name"], quote=True), WIDTH, WIDTH))
    eyebrow = "" if images.get("hero") else para(
        "#{} &nbsp;&middot;&nbsp; Monthly recap".format(escape(ctx["channel_name"])), 12,
        "#C7DBFF", 700, line=1.4, more="letter-spacing:1.4px;text-transform:uppercase;padding-bottom:6px;")
    month = ctx["start"].strftime("%B %Y")
    if ctx["finished"]:
        title = escape(month + " in review")
    else:
        days = ("{} {}".format(ctx["start"].day, ctx["start"].strftime("%b"))
                if ctx["start"] == ctx["end"] else
                "{}\u2013{} {}".format(ctx["start"].day, ctx["end"].day, ctx["end"].strftime("%b")))
        title = '{}<span style="{}">&nbsp;&nbsp;&middot;&nbsp; {}, so far</span>'.format(
            escape(month), font(16, "#DCE7FF", 400, 1.2, "font-weight:400;"), days)
    out += ('<tr><td class="px" bgcolor="{b}" style="background-color:{b};background-image:'
            'linear-gradient(135deg,#0056D2 0%,#1D4ED8 55%,#3730A3 100%);'
            'padding:{v}px {p}px {v}px {p}px;font-family:{f};">{eyebrow}{title}</td></tr>').format(
                f=FONT, b=BRAND, p=PAD, v=18 if images.get("hero") else 22, eyebrow=eyebrow,
                title=para(title, 26, "#FFFFFF", 700, line=1.25))
    return out


MAX_GLOBES = 8              # past this the laps are written as a figure, not drawn


def laps_html(pos, size=14):
    """The laps of the Earth already walked, as a globe for each and the count in words:
    what a finished lap leaves behind once the route has started again from the beginning.
    '' on the first lap."""
    done = pos["lap"] - 1
    if done < 1:
        return ""
    globes = "\U0001F30D" * done if done <= MAX_GLOBES else "\U0001F30D &times; {:,}".format(done)
    return para("{}&nbsp; <b>Round the Earth {}</b>, and now on lap {:,}.".format(
        globes, "once" if done == 1 else "twice" if done == 2 else "{:,} times".format(done),
        pos["lap"]), size, INK, line=1.5)


BRIEF_TINT, BRIEF_FIGURE = "#EEF4FF", "#0A3D91"      # the panel, and the bold figures on it


def brief_html(ctx):
    """The opening as a panel: a title and a line or two of welcome, its figures in bold and
    any activity it names picked out in colour (see activity_marks). The walk has its own
    section (together); said here as well it was the same thing twice at the top of the
    email, ahead of the numbers."""
    brief = ctx["brief"]
    tint, edge, deep = BRIEF_TINT, "#CFDDFB", BRIEF_FIGURE
    label = para("\u2728&nbsp; The month in brief", 12, BRAND, 700,
                 more="letter-spacing:1.2px;text-transform:uppercase;")
    inner = ('{} bgcolor="{}" style="background-color:{};border:1px solid {};border-left:4px '
             'solid {};border-radius:0 12px 12px 0;"><tr><td style="padding:18px 20px;">'
             '{}{}{}</td></tr></table>').format(
                 TABLE, tint, tint, edge, BRAND, label,
                 para(escape(brief["headline"]), 22, INK, 700, top=8, line=1.3),
                 para(emphasis_html(brief["body"], deep, activity_marks(ctx["month"])), 16,
                      "#334155", top=8, line=1.65))
    return band(inner)


# A figure, then its label with the icon in front, then a note: the icon shares the label's
# line rather than taking one of its own, which keeps the grid short.
TILE_HEIGHT = 78
# One colour family per tile -- the figure and its top edge in the deep shade, the box a tint
# fading to white, a hairline in between -- so the grid reads as a row of different things
# rather than six copies of one grey box. A client with no gradients shows the plain tint.
# (deep, tint, edge, icon)
TILE_LOOK = {
    "people": ("#1D4ED8", "#E8F0FF", "#BFDBFE", "\U0001F465"),
    "checkins": ("#047857", "#E3F8EF", "#A7F3D0", "\u2705"),
    "activities": ("#6D28D9", "#F1ECFF", "#DDD6FE", "\U0001F9E9"),
    "new": ("#B45309", "#FFF5DB", "#FDE68A", "\U0001F44B"),
    "step": ("#0E7490", "#E2F8FC", "#A5F3FC", "\U0001F45F"),
    "pushup": ("#C2410C", "#FFF0E3", "#FED7AA", "\U0001F4AA"),
    "plank": ("#BE185D", "#FDEBF4", "#FBCFE8", "\u23F1\uFE0F"),
    "sessions": ("#475569", "#F1F5F9", "#E2E8F0", "\U0001F4C8"),
}
UP = "#047857"


def figure_size(figure):
    """A tile is a third of a phone wide, about 90px of text: "68" can be large, "4h 59m"
    cannot, and a figure that wraps is two figures."""
    length = len(str(figure))
    return 30 if length <= 5 else 24 if length == 6 else 21


def versus(now, before, label):
    """The note under a count that has a number to be compared with. Said warmly or not at
    all: a rise is marked and named, level is said, and a fall is just the earlier figure --
    no red arrow, because a month with fewer people is not a failing."""
    if not before:
        return ""
    if now > before:
        return '<span style="color:{};font-weight:700;">&#9650; up from {:,}</span> in {}'.format(
            UP, before, escape(label))
    if now == before:
        return "level with {}".format(escape(label))
    return "{:,} in {}".format(before, escape(label))


def tiles_html(ctx):
    """The month's numbers: a coloured tile each, with an icon, the figure, what it
    counts, and a line that gives it some size -- how it compares with last month, how many
    marathons the steps came to, how many of the activities were logged."""
    month, facts, volume = ctx["month"], ctx["facts"], ctx["volume"]
    label_before = month["before_label"]
    tiles = [("people", len(month["ids"]), "people active",
              versus(len(month["ids"]), month["before_people"], label_before)),
             ("checkins", "{:,}".format(month["checkins"]), "check-ins",
              versus(month["checkins"], month["before_checkins"], label_before)),
             ("activities", len(month["activities"]), "activities logged",
              "of {} you can log".format(len(ACTIVITIES)))]
    if month["new_people"]:
        tiles.append(("new", len(month["new_people"]), "first-time loggers", "welcome aboard"))
    for activity in HEADLINE:
        gain = volume["gain"].get(activity) if volume else 0
        total = facts["totals"].get(activity, 0)
        noun = ACTIVITIES[activity][0].lower()      # "plank", not the phrase's "of plank"
        figure = compact if activity == "step" else (lambda v, a=activity: humanize(a, v))
        value = gain or total
        if not value:
            continue
        note = "added since {}".format(short_day(volume["since"])) if gain else "all time"
        if activity == "step":
            marathons = int(round(steps_to_km(value) / MARATHON_KM))
            if marathons >= 1:
                note = "about {}{}".format(plural(marathons, "marathon"),
                                           "" if gain else ", all time")
        tiles.append((activity, figure(value), noun + (" added" if gain else ""), escape(note)))
    tiles.append(("sessions", "{:,}".format(facts["logs"]), "sessions logged", "all time"))
    tiles = tiles[:6] if len(tiles) >= 6 else tiles[:3]

    rows = ""
    for start in range(0, len(tiles), 3):
        cells = ""
        for key, figure, label, note in tiles[start:start + 3]:
            deep, tint, edge, icon = TILE_LOOK[key]
            # A fixed height, with the text centred in it: a tile with a note under its
            # label and one without are then the same box, on a phone as on a desktop.
            cells += ('<td width="33%" valign="top" style="padding:5px;">{} bgcolor="{}" '
                      'style="background-color:{};background-image:linear-gradient(180deg,{} 0%,'
                      '#FFFFFF 100%);border:1px solid {};border-top:3px solid {};'
                      'border-radius:12px;"><tr><td align="center" valign="middle" height="{}" '
                      'style="height:{}px;padding:6px 6px;">{}{}{}</td></tr></table></td>'
                      ).format(
                          TABLE, tint, tint, tint, edge, deep, TILE_HEIGHT, TILE_HEIGHT,
                          para(figure, figure_size(figure) - 2, deep, 700, line=1.1,
                               more="white-space:nowrap;"),
                          para('<span style="font-size:14px;">{}</span>&nbsp;{}'.format(
                              icon, escape(label)), 12, INK, 600, top=3, line=1.3),
                          para(note, 11, MUTED, top=2, line=1.35) if note else "")
        rows += "<tr>{}</tr>".format(cells)
    note = ""
    if month["before_people"] and not ctx["finished"]:
        note = "Compared with the same days of {}.".format(month["before_label"])
    if volume and not volume["exact"]:
        note = (note + " " if note else "") + \
            "Amounts added are counted from {}.".format(short_day(volume["since"]))
    return band("{}>{}</table>{}".format(TABLE, rows, para(
        escape(note), 12, FAINT, top=8, more="text-align:center;") if note else ""),
        top=22, side=PAD - 5)


TREND_HEIGHT = 96           # px of the tallest column
TREND_PAST = "#A8C3EF"      # earlier months: a lighter step of the same blue


def short_count(value):
    """A count that fits under a column a twelfth of a phone wide: 1,240 -> 1.2K."""
    value = int(value or 0)
    if value < 1000:
        return str(value)
    return "{:.1f}".format(value / 1000.0).rstrip("0").rstrip(".") + "K"


def trend_html(ctx):
    """People active, month by month, as a column chart drawn with table cells -- no
    image, so it shows in clients that block images and sends nobody's numbers to a
    chart service.

    One series, so one hue and no legend: the title says what a column is. This month is
    the full brand blue and the months before a lighter step of it, so the eye lands on
    the month the email is about. Columns grow from a zero baseline (a count has no other
    honest one), every column wears its value on its cap, and the check-ins are written
    under each month, so nothing depends on reading a height or a colour. An email has no
    hover, which is why every figure is printed.

    It holds up to twelve months, and twelve columns have to fit a phone: past six the
    columns thin and the figures shrink, and the words "check-ins" move from under every
    month into the caption.
    """
    history = ctx["history"]
    if len(history) < 2:
        return ""
    many = len(history) > 6
    bar_width = 24 if not many else (16 if len(history) <= 9 else 12)
    top = max(people for _, people, _ in history) or 1
    width = "{}%".format(100 // len(history))
    bars = labels = ""
    for index, (first, people, checkins) in enumerate(history):
        current = index == len(history) - 1
        colour = BRAND if current else TREND_PAST
        height = max(2, int(round(TREND_HEIGHT * people / float(top)))) if people else 0
        column = ""
        if height:
            column = ('<table role="presentation" align="center" width="{w}" cellpadding="0" '
                      'cellspacing="0" border="0"><tr><td width="{w}" height="{h}" bgcolor="{c}" '
                      'style="height:{h}px;background-color:{c};border-radius:{r}px {r}px 0 0;'
                      'font-size:0;line-height:0;">&nbsp;</td></tr></table>').format(
                          w=bar_width, h=height, c=colour, r=4 if not many else 3)
        bars += '<td width="{}" align="center" valign="bottom" style="padding:0 1px;">{}{}</td>'.format(
            width, para(str(people), 12 if many else 14, INK, 700, line=1.2,
                        more="padding-bottom:4px;"), column)
        name = first.strftime("%b") + ("" if not current or ctx["finished"] else "*")
        below = short_count(checkins) if many else "{:,} check-ins".format(checkins)
        labels += ('<td width="{}" align="center" valign="top" style="padding:6px 1px 0 1px;'
                   'border-top:1px solid {};">{}{}</td>').format(
                       width, "#C5CBD5",
                       para(name, 11 if many else 12, INK if current else MUTED,
                            700 if current else 400, line=1.3),
                       para(below, 10 if many else 11, FAINT, top=1, line=1.3))
    # One short line at most: the title already says what a column is.
    foot = []
    if many:
        foot.append("Small figures are check-ins")
    if not ctx["finished"]:
        foot.append("*{} is the month so far".format(ctx["start"].strftime("%B")))
    inner = (para("People active, month by month", 16, INK, 700, line=1.4) +
             '<div style="height:12px;line-height:12px;font-size:12px;">&nbsp;</div>' +
             "{}><tr>{}</tr><tr>{}</tr></table>".format(TABLE, bars, labels) +
             (para(". ".join(foot) + ".", 12, FAINT, top=10) if foot else ""))
    return band(card(inner), top=14)


MIX_SHOWN = 8              # activities given a bar of their own; the rest share one line
MIX_BAR = 12               # px, the height of a bar
# px for the activity's name: wide enough for the longest one ("Cold showers") with its
# emoji, and no wider, so the bars start right after the names on any screen.
MIX_NAME = 132
# A calm colour for each bar, in order down the chart: soft, light and all different, so
# every bar is its own, with nothing to look up. Mid-tones rather than pastels, so a bar
# still stands clear of the white page.
MIX_COLOURS = ("#6FA8DC", "#7CC6A4", "#A99BDB", "#F2B27E", "#EE9FB4", "#7FC8D6",
               "#B9CF7E", "#E3C27A", "#9DB0D8")


def busiest_first(spots):
    """The activities logged this month, busiest first: the order of the check-ins chart,
    and so the order its colours are given out in."""
    return sorted(spots, key=lambda a: (-spots[a]["checkins"], -len(spots[a]["people"]),
                                        ACTIVITIES[a][0]))


# Other ways of writing an activity's title, which the model is given as "pushups".
NAME_VARIANTS = {"pushup": ("push-ups", "push ups"), "pullup": ("pull-ups", "pull ups")}
# The nine hues of MIX_COLOURS, in the same order, made dark enough to be read as text: 5:1
# or better on the brief's tint, and far enough from the slate of the paragraph and the navy
# of its figures to stand out from both. A bar's own colour is a pastel -- fine for a bar, too
# faint for a word.
MIX_INK = ("#1468A3", "#216945", "#6643A3", "#974B11", "#A12B4E", "#0A707F", "#556D1D",
           "#895F0B", "#58619D")


def activity_marks(month):
    """A function that picks out, in a paragraph that is already escaped, the activities it
    names: each in the dark shade of its bar's colour in the check-ins chart, so the sentence
    and the chart read together and no two activities in a sentence share a colour.

    Colour alone -- no fill, no icon, no underline (which reads as a link), and no bold, which
    the figures in the same paragraph already are. A medium weight where the font has one;
    where it has not the colour does the work. An activity past the chart's colours is left
    as it is.

    Only activities logged this month, found by the title the model is given (Steps, Plank,
    Workouts), as whole words in any case."""
    names = {}
    for place, activity in enumerate(busiest_first(month["activities"])[:len(MIX_INK)]):
        for name in (ACTIVITIES[activity][0].lower(),) + NAME_VARIANTS.get(activity, ()):
            names[name] = MIX_INK[place]
    if not names:
        return lambda text: text
    pattern = re.compile(r"(?<![\w-])(" + "|".join(
        re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")(?![\w-])", re.IGNORECASE)

    def mark(match):
        return '<span style="color:{};font-weight:500;white-space:nowrap;">{}</span>'.format(
            names[match.group(1).lower()], match.group(1))

    def outside_bold(text):
        # A word inside **a figure** stays as the figure is: coloured there, its medium
        # weight broke the bold in two ("91 check-ins for" bold, "steps" not).
        parts = re.split(r"(\*\*.+?\*\*)", text)
        return "".join(part if part.startswith("**") else pattern.sub(mark, part)
                       for part in parts)
    return outside_bold


def checkins_html(ctx, images):
    """Where the month's check-ins went: a bar per activity, busiest first, its figure
    printed at the end so nothing depends on judging a length.

    Sideways, because activity names are long and a phone is narrow. Each bar has a calm
    colour of its own (MIX_COLOURS), taken in order down the chart, so no two match and
    there is no key to read. The busiest MIX_SHOWN get a bar and the rest are summed in a
    line underneath. A check-in here is one person logging that
    activity on one day, so somebody who walked and did pushups on a Monday counts in
    both bars."""
    month = ctx["month"]
    spots = month["activities"]
    if not spots:
        return ""
    ranked = busiest_first(spots)
    # One left over is given its bar: "+ 1 more activity" hides as much as it saves.
    cut = MIX_SHOWN if len(ranked) > MIX_SHOWN + 1 else len(ranked)
    shown, rest = ranked[:cut], ranked[cut:]
    top = float(spots[shown[0]]["checkins"]) or 1.0
    rows = ""
    for place, activity in enumerate(shown):
        spot = spots[activity]
        colour = MIX_COLOURS[place % len(MIX_COLOURS)]
        filled = max(2, int(round(100 * spot["checkins"] / top)))
        track = ('<td width="{w}%" height="{h}" bgcolor="{c}" style="height:{h}px;'
                 'background-color:{c};border-radius:0 6px 6px 0;font-size:0;line-height:0;">'
                 '&nbsp;</td>').format(w=filled, h=MIX_BAR, c=colour)
        if filled < 100:
            track += '<td width="{}%" style="font-size:0;line-height:0;">&nbsp;</td>'.format(
                100 - filled)
        rows += ('<tr><td width="{nw}" valign="middle" style="width:{nw}px;padding:7px 10px 7px 0;'
                 '{line}">{name}{who}'
                 '</td><td valign="middle" style="padding:7px 0;{line}">{t}><tr>{track}</tr>'
                 '</table></td><td width="44" align="right" valign="middle" style="padding:7px 0 '
                 '7px 8px;{line}{f}">{n:,}</td></tr>').format(
                     line=ROW_LINE, t=TABLE, track=track, nw=MIX_NAME,
                     name=para("{}&nbsp; <b>{}</b>".format(ACTIVITIES[activity][1],
                                                          escape(ACTIVITIES[activity][0])),
                               14, INK, line=1.3),
                     who=para(plural(len(spot["people"]), "person", "people"), 12, FAINT,
                              line=1.3),
                     f=font(15, INK, 700, 1.3), n=spot["checkins"])
    more = ""
    if rest:
        more = para("+ {:,} more {}, with {}.".format(
            len(rest), "activity" if len(rest) == 1 else "activities",
            plural(sum(spots[a]["checkins"] for a in rest), "check-in")), 13, MUTED, top=10)
    return band(section_head("checkins", "Where the check-ins went",
                             "What the channel logged this month, busiest first.",
                             OTHER_SECTIONS["checkins"], "\U0001F4CA", images) +
                SPACER.format(8) + "{}>{}</table>".format(TABLE, rows) + more, top=30)


def activities_html(ctx, images, only=None):
    """Each family of activities under its banner (just those named in `only`, when it is
    given), with the activities the channel logged this month beneath it: the month's
    people and check-ins, and the all-time line.

    An activity nobody logged this month is left out -- a row of dashes says nothing in a
    month's recap -- and so is one that fewer than section_min_people people have ever
    logged, unless it is one of always_show. Both still count in every total. A family
    with nothing left to list is skipped, banner and all."""
    month, facts, volume = ctx["month"], ctx["facts"], ctx["volume"]

    def this_month(activity):
        return month["activities"].get(activity, {"people": (), "checkins": 0})

    out = ""
    for key, title, about, colour, emoji in SECTIONS:
        if only and key not in only:
            continue
        inside = [a for a in facts["totals"] if ACTIVITIES[a][2] == key
                  and this_month(a)["people"]
                  and (facts["doers"].get(a, 0) >= ctx["section_min_people"]
                       or a in ctx["always_show"])]
        if not inside:
            continue
        inside.sort(key=lambda a: (-len(this_month(a)["people"]), -this_month(a)["checkins"],
                                   -facts["doers"].get(a, 0), a))
        head = ('<tr><td style="padding:0 0 6px 0;{}">Activity</td>'
                '<td align="right" style="padding:0 0 6px 8px;{}">People</td>'
                '<td align="right" style="padding:0 0 6px 8px;{}">Check-ins</td></tr>').format(
                    *[font(11, FAINT, 700, 1.3, "letter-spacing:0.8px;text-transform:uppercase;"
                           "border-bottom:1px solid {};".format(LINE))] * 3)
        rows = ""
        for activity in inside:
            spot = this_month(activity)
            name, icon = ACTIVITIES[activity][0], ACTIVITIES[activity][1]
            gain = volume["gain"].get(activity) if volume else 0
            detail = "{} all time, by {}".format(
                amount(activity, facts["totals"].get(activity, 0)),
                plural(facts["doers"].get(activity, 0), "person", "people"))
            if gain:
                detail = '<span style="color:{};font-weight:600;">+{}</span> &nbsp;&middot;&nbsp; {}' \
                    .format(colour, amount(activity, gain), detail)
            cell = "padding:11px 0 11px {}px;border-bottom:1px solid {};"
            rows += ('<tr><td valign="top" style="{}">{}{}</td>'
                     '<td align="right" valign="top" style="{}{}">{}</td>'
                     '<td align="right" valign="top" style="{}{}">{:,}</td></tr>').format(
                         cell.format(0, LINE),
                         para("{}&nbsp; <b>{}</b>".format(icon, escape(name)), 15, INK, line=1.35),
                         para(detail, 13, MUTED, top=3, line=1.4),
                         cell.format(8, LINE), font(15, INK, 700, 1.35), len(spot["people"]),
                         cell.format(8, LINE), font(15, INK, 400, 1.35), spot["checkins"])
        note = "People and check-ins are for {}.".format(
            ctx["start"].strftime("%B") if ctx["finished"] else ctx["start"].strftime("%B") + " so far")
        out += band(section_head(key, title, about, colour, emoji, images) +
                    '<div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>' +
                    "{}>{}{}</table>".format(TABLE, head, rows) +
                    para(note, 12, FAINT, top=6), top=30)
    return out


# The badges come in four kinds, each with a colour of its own: (families, tint, edge, deep).
# The cards are laid out kind by kind, so the colours run in blocks and say which badges
# belong together without a heading for each. A family not listed is never shown
# (BADGE_SKIP).
BADGE_KINDS = (
    (("streak",), "#FFF3EB", "#FED7BF", "#C2410C"),                         # daily streaks
    (("steady",), "#EEF4FF", "#C9DAFB", "#1D4ED8"),                         # weekly streaks
    (("perfect", "month"), "#ECFBF3", "#B7EBCF", "#047857"),                # attendance
    (("explorer", "allround", "triple", "weekend"), "#F4F0FF", "#DACFFB", "#6D28D9"),
)
BADGE_FACE = 20             # px, the face or initials beside an earner's name
BADGE_NAMES = 3             # earners named on a card; the rest are counted


def badge_kind(badge):
    """(order, tint, edge, deep) of the kind a badge belongs to."""
    for order, (families, tint, edge, deep) in enumerate(BADGE_KINDS):
        if badge["family"] in families:
            return order, tint, edge, deep
    return len(BADGE_KINDS), TINT, LINE, INK


def badge_card(ctx, badge, earners):
    """One badge: its icon on a white disc, its name in the kind's colour with what it took
    under it ("logged on" and "logged in" left off: every badge is about logging), and the
    people who earned it, each with a face -- their photo, or their initials -- so the card is
    about them as much as the badge."""
    _order, _tint, edge, deep = badge_kind(badge)
    about = re.sub(r"^logged (on|in) ", "", badge["about"])
    if ctx["show_names"]:
        faces = dict(ctx, photos=ctx.get("photos") or {})    # initials when there is no photo
        # Each earner on a chip of their own -- a white pill, their face, their name in bold --
        # so the people stand out from the card as the thing being celebrated, not as a line
        # of text under it.
        who = "".join('<span style="display:inline-block;white-space:nowrap;margin:7px 6px 0 0;'
                      'padding:2px 10px 2px 2px;background-color:#FFFFFF;border:1px solid {};'
                      'border-radius:14px;"><b>{}&nbsp; {}</b></span>'.format(
                          edge, avatar(faces, pid, name, BADGE_FACE), escape(name))
                      for name, pid in earners[:BADGE_NAMES])
        if len(earners) > BADGE_NAMES:
            who += '<span style="display:inline-block;margin-top:6px;color:{};">+{} more</span>' \
                .format(MUTED, len(earners) - BADGE_NAMES)
    else:
        who = plural(len(earners), "person", "people")
    return ('<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td width="32" height="32" align="center" valign="middle" bgcolor="#FFFFFF" '
            'style="width:32px;height:32px;background-color:#FFFFFF;border:1px solid {e};'
            'border-radius:16px;font-size:16px;line-height:1;">{i}</td>'
            '<td valign="middle" style="padding-left:10px;">{n}{a}</td></tr></table>'
            '{w}').format(e=edge, i=BADGE_EMOJI.get(badge["family"], "\U0001F3C5"),
                          n=para("<b>{}</b>".format(escape(badge["name"])), 14, deep, line=1.3),
                          a=para(escape(about), 12, MUTED, line=1.35),
                          w=para(who, 13, INK, top=2, line=1.4))


def badges_html(ctx, badges):
    """The badges earned, two cards to a row, kind by kind (see BADGE_KINDS) and the most
    prestigious first within a kind. A card is drawn on its table cell, so the two in a row
    are always the same height; on a phone they stack (see .badge in build_html)."""
    ordered = sorted(badges, key=lambda item: (badge_kind(item[0])[0], -item[0]["prestige"]))

    def cell(item):
        if item is None:
            return '<td class="badge" width="49%">&nbsp;</td>'
        _order, tint, edge, _deep = badge_kind(item[0])
        return ('<td class="badge" width="49%" valign="top" bgcolor="{t}" style="background-color:'
                '{t};border:1px solid {e};border-radius:10px;padding:10px 12px 11px 12px;">{c}'
                '</td>').format(t=tint, e=edge, c=badge_card(ctx, *item))

    if len(ordered) % 2:
        ordered.append(None)
    rows = ""
    for i in range(0, len(ordered), 2):
        rows += ('<tr>{}<td class="gap" width="2%" style="font-size:0;">&nbsp;</td>{}</tr>'
                 '<tr><td colspan="3" style="height:8px;line-height:8px;font-size:8px;">&nbsp;'
                 '</td></tr>').format(cell(ordered[i]), cell(ordered[i + 1]))
    return SPACER.format(6) + "{}>{}</table>".format(TABLE, rows)


def highlights_html(ctx, images):
    items, badges = ctx["highlights"], ctx["badges"]
    if not items and not badges:
        return ""
    rows = ""
    for icon, text in items:
        rows += ('<tr><td width="34" valign="top" style="padding:8px 0;{}">{}</td>'
                 '<td valign="top" style="padding:8px 0;{}">{}</td></tr>').format(
                     font(18, INK, 400, 1.3), icon, font(15, INK, 400, 1.5), text)
    inner = section_head("highlights", "Highlights of the month", "", OTHER_SECTIONS["highlights"],
                         "✨", images)
    if rows:
        inner += '<div style="height:6px;line-height:6px;font-size:6px;">&nbsp;</div>' + \
            "{}>{}</table>".format(TABLE, rows)
    if badges:
        inner += para("\U0001F3C5&nbsp; Badges earned", 12, MUTED, 700, top=18,
                      more="letter-spacing:1.2px;text-transform:uppercase;") + \
            badges_html(ctx, badges) + \
            para("Badges are earned by showing up, never by volume.", 12, FAINT, top=10)
    return band(inner, top=30)


def heat_bands(counts):
    """{people on a day: level 1-3} for the days anyone logged, cut so the three colours
    are used about equally rather than at thirds of the busiest day. As channel_summary."""
    values = sorted(c for c in counts if c)
    distinct = sorted(set(values))
    if not distinct:
        return {}
    if len(distinct) == 1:
        return {distinct[0]: 2}
    if len(distinct) == 2:
        return {distinct[0]: 1, distinct[1]: 3}
    third = len(values) / 3.0
    best = None
    for i in range(1, len(distinct) - 1):
        for j in range(i + 1, len(distinct)):
            sizes = (sum(1 for v in values if v < distinct[i]),
                     sum(1 for v in values if distinct[i] <= v < distinct[j]),
                     sum(1 for v in values if v >= distinct[j]))
            spread = max(abs(size - third) for size in sizes)
            if best is None or spread < best[0]:
                best = (spread, i, j)
    _, i, j = best
    return {v: (1 if n < i else 2 if n < j else 3) for n, v in enumerate(distinct)}


def calendar_html(ctx, images):
    """The month as a calendar: a square per day, darker the more people logged, the number of people
    who logged written in it."""
    month, start, end = ctx["month"], ctx["start"], ctx["end"]
    if not month["counts"]:
        return ""
    levels = heat_bands(month["counts"].values())
    head = "".join('<td align="center" width="14%" style="{}">{}</td>'.format(
        font(11, FAINT, 700, 1.3), d) for d in "MTWTFSS")
    rows = ""
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(start.year, start.month):
        cells = ""
        for day in week:
            if day.month != start.month:
                cells += "<td>&nbsp;</td>"
                continue
            count = month["counts"].get(day, 0)
            ahead = day > end
            fill, ink, dim = (("#FFFFFF", "#C5CBD5", "#C5CBD5") if ahead
                              else HEAT[levels.get(count, 0)])
            # The date small and soft in the corner, as a wall calendar has it; the count of
            # people large in the middle, so the two numbers are never read as one another.
            cells += ('<td valign="top" bgcolor="{}" style="background-color:{};padding:4px 0 6px 0;'
                      'border-radius:6px;{}">{}{}</td>').format(
                          fill, fill, "border:1px dashed {};".format(LINE) if ahead else "",
                          para(day.day, 10, dim, line=1.2, more="padding-left:6px;"),
                          para("&nbsp;" if ahead else (count if count else "&middot;"),
                               16, ink, 700, line=1.2, more="text-align:center;"))
        rows += "<tr>{}</tr>".format(cells)
    key = "".join('<td width="16" height="12" bgcolor="{}" style="background-color:{};font-size:0;'
                  'line-height:0;">&nbsp;</td>'.format(c, c) for c, _ink, _dim in HEAT)
    legend = ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
              'align="center"><tr><td style="padding-right:8px;{f}">quiet</td>{k}'
              '<td style="padding-left:8px;{f}">very active</td></tr></table>').format(
                  f=font(12, FAINT, 400, 1.2), k=key)
    about = "Each square is a day: the date in the corner, and in the middle how many people logged."
    return band(section_head("calendar", "Who showed up, day by day", about,
                             OTHER_SECTIONS["calendar"], "\U0001F4C5", images) +
                '<div style="height:12px;line-height:12px;font-size:12px;">&nbsp;</div>' +
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="4" '
                'border="0"><tr>{}</tr>{}</table>'.format(head, rows) +
                '<div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>' + legend,
                top=30)


def card(inner):
    return ('{} style="border:1px solid {};border-radius:10px;"><tr><td style="padding:16px 18px;">'
            '{}</td></tr></table>').format(TABLE, LINE, inner)


ROUTE_DOT = 8               # px: a stop on the route
ROUTE_END = 12              # px: the start and the finish
ROUTE_AHEAD = "#C5CBD5"     # the road not yet walked
# A man walking facing right, medium skin tone (Slack's :man_walking_facing_right: with
# :skin-tone-4:): person walking + skin tone + male sign + right arrow, joined by ZWJs. The
# plain U+1F6B6 faces left on some systems, which looks like walking backwards along a
# line that runs left to right. A client too old for the sequence (before Emoji 15.1, 2023)
# shows its parts side by side -- a walker, a male sign and an arrow -- not a broken image.
WALKER = "\U0001F6B6\U0001F3FD\u200D\u2642\uFE0F\u200D\u27A1\uFE0F"


def flag_emoji(shortcode):
    """':flag-us:' -> the flag of the US, as the two regional-indicator letters it is
    written with. '' for anything that is not a two-letter flag."""
    code = str(shortcode or "").replace(":", "").split("-")[-1].upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code)


def route_html(pos, steps, colour):
    """The Great Walk as a map: one line, a dot for every stop, a person walking where the
    channel has got to, and the start, the place reached and the finish named underneath.

    Drawn with table cells, like the month-by-month chart, so it shows in clients that
    block images. The walker stands ON the line, at the point where the road walked turns
    into the road still to go, so its place is exact however wide the screen is. Stops are
    evenly spaced -- twenty stops with distances from 600 km to 8,000 km cannot all be
    drawn to scale in a phone's width; the figures above carry the real distances.

    Reached stops are the section's colour, the next stop is blue, the road ahead is a
    dotted grey line, and the finish (the start again: the route is a loop) is dark.
    """
    legs = len(LEG_KM)
    here = pos["leg"] - 1                   # the stop just passed
    share = max(0.0, min(1.0, pos["share"]))

    def dot(index):
        size = ROUTE_END if index in (0, legs) else ROUTE_DOT
        if index == legs:
            fill = INK
        elif index <= here:
            fill = colour
        elif index == here + 1:
            fill = BRAND
        else:
            fill = ROUTE_AHEAD
        return ('<td width="{s}" valign="middle"><div title="{n}" style="width:{s}px;'
                'height:{s}px;border-radius:{r}px;background-color:{c};font-size:0;">'
                '</div></td>').format(
                    s=size, c=fill, r=size // 2, n=escape(ROUTE[index][0], quote=True))

    def road(walked, width=""):
        """A piece of the line: a thin box in the middle of its cell, so beside the walker,
        where the row is as tall as the figure, it stays a line."""
        line = ("height:3px;background-color:{}".format(colour) if walked
                else "border-top:2px dotted {}".format(ROUTE_AHEAD))
        return '<td {}valign="middle"><div style="{};font-size:0;"></div></td>'.format(
            'width="{}%" '.format(width) if width else "", line)

    track = ""
    for index in range(legs + 1):
        track += dot(index)
        if index == legs:
            break
        width = "{:.2f}".format(100.0 / legs)
        if index != here:                   # a leg wholly walked, or wholly to come
            track += road(index < here, width)
            continue
        # the leg being walked: the road behind, the walker, the road ahead
        cells = ""
        if share >= 0.03:
            cells += road(True, "{:.1f}".format(share * 100))
        cells += ('<td align="center" valign="middle" style="padding:0 2px;font-size:20px;'
                  'line-height:20px;">{}</td>').format(WALKER)
        if share <= 0.97:
            cells += road(False, "{:.1f}".format((1 - share) * 100))
        track += '<td width="{}%" valign="middle">{}><tr>{}</tr></table></td>'.format(
            width, TABLE, cells)

    start, behind, nxt, finish = ROUTE[0], pos["behind"], pos["ahead"], ROUTE[-1]
    place = "{} {} &rarr; {}".format(flag_emoji(behind[1]), escape(stop_name(behind)),
                                    escape(stop_name(nxt))).strip()
    labels = ('<tr><td width="30%" valign="top" align="left">{start}</td>'
              '<td width="40%" valign="top" align="center">{now}</td>'
              '<td width="30%" valign="top" align="right">{end}</td></tr>').format(
                  start=para("\U0001F6A9&nbsp;<b>Start</b>", 12, MUTED, line=1.4) +
                  para("{} {}".format(flag_emoji(start[1]), escape(stop_name(start))).strip(),
                       12, INK, top=1, line=1.4),
                  now=para("{}&nbsp;<b>We are here</b>".format(WALKER), 12, MUTED,
                           line=1.4, more="text-align:center;") +
                  para(place, 12, INK, top=1, line=1.4, more="text-align:center;"),
                  end=para("\U0001F3C1&nbsp;<b>Finish</b>", 12, MUTED, line=1.4,
                           more="text-align:right;") +
                  para("{} {}".format(flag_emoji(finish[1]), escape(stop_name(finish))).strip(),
                       12, INK, top=1, line=1.4, more="text-align:right;"))
    summary = "Route progress: {} of {} stops reached, {} {}{}.".format(
        here, legs, "on the way from" if here else "setting off from",
        stop_name(behind), " towards " + stop_name(nxt) if here else "")
    return ('<div role="img" aria-label="{a}">{t}>{track}</tr></table>'
            '<div style="height:10px;line-height:10px;font-size:10px;">&nbsp;</div>'
            '{t}>{labels}</table></div>').format(
                a=escape(summary, quote=True), t=TABLE, track="<tr>" + track,
                labels=labels)


def in_marathons(km):
    """'38 marathons' for a distance, or '' under one. The one comparison the walk is
    given: nearly everybody knows a marathon is a very long way, runner or not, and one
    yardstick said once is easier to hold than three. One decimal while it is small
    (1.5), whole numbers after."""
    count = km / MARATHON_KM
    if count < 1:
        return ""
    if count < 10:
        figure = "{:.1f}".format(count).rstrip("0").rstrip(".")
        return "{} marathon{}".format(figure, "" if figure == "1" else "s")
    return plural(int(round(count)), "marathon")


def together_html(ctx, images):
    """What everybody's steps add up to: the walk round the world."""
    facts, volume = ctx["facts"], ctx["volume"]
    colour = OTHER_SECTIONS["together"]
    steps = facts["totals"].get("step", 0)
    if not steps:
        return ""
    pos = journey_position(steps)
    around = pos["around"] * 100
    # The banner above already says "The Great Walk"; the card starts with where it is.
    text = para("\U0001F4CD&nbsp; <b>Leg {} of {}</b>{}".format(
        pos["leg"], pos["legs"], " &nbsp;<span style=\"color:{};\">lap {}</span>".format(
            MUTED, pos["lap"]) if pos["lap"] > 1 else ""), 16, INK, line=1.4)
    if pos["lap"] > 1:
        text += SPACER.format(8) + laps_html(pos, 15)
    text += para("{} &nbsp;&rarr;&nbsp; <b>{}</b>".format(
        escape(stop_name(pos["behind"])), escape(stop_name(pos["ahead"]))), 15, INK, top=8)
    text += '<div style="height:8px;line-height:8px;font-size:8px;">&nbsp;</div>' + \
        bar(pos["share"], colour)
    text += para("<b>{:.0f}%</b> of this leg &nbsp;&middot;&nbsp; <b>{:,.0f} km</b> to go"
                 " &nbsp;&middot;&nbsp; {}".format(pos["share"] * 100, pos["to_go"],
                                                   escape(pos["ahead"][4])), 13, MUTED, top=8)
    line = "To date: <b>{:,.0f} km</b>".format(pos["km"])
    if in_marathons(pos["km"]):
        line += ", about <b>{}</b>".format(in_marathons(pos["km"]))
    if pos["lap"] > 1:
        line += ", and {} round the world".format(plural(pos["lap"] - 1, "full lap"))
    else:
        line += ", and <b>{}%</b> of the way round the world".format(
            "{:.1f}".format(around) if around < 10 else "{:.0f}".format(around))
    text += para(line + ".", 14, INK, top=10)
    # What the month added, as a line of its own: it is the news in a monthly email.
    added = steps_to_km(volume["gain"].get("step", 0)) if volume else 0
    if added >= 1:
        month_line = "<b>+{:,.0f} km</b> since {}".format(added, short_day(volume["since"]))
        if in_marathons(added):
            month_line += ", about <b>{}</b>".format(in_marathons(added))
        text += para(month_line + ".", 14, colour, 600, top=4)
    text += '<div style="height:18px;line-height:18px;font-size:18px;">&nbsp;</div>'
    text += route_html(pos, steps, colour)
    return band(section_head("together", JOURNEY_NAME, "", colour, "\U0001F91D", images) +
                SPACER.format(12) + card(text),
                top=30)


def milestones_html(ctx, images):
    """The channel's totals, each with a bar to the next round number it is climbing
    towards. The bar is measured from the last mark passed, so it moves visibly from one
    month to the next; the line under it names both marks, so "30%" is never read as 30%
    of the whole total."""
    facts = ctx["facts"]
    colour = OTHER_SECTIONS["milestones"]
    rungs = ""
    for activity in ctx["milestones"]:
        total = facts["totals"].get(activity, 0)
        if not total:
            continue
        spot = stop_for(activity, total)
        rungs += ('<tr><td style="padding:9px 0 0 0;">{}'
                  '<div style="height:6px;line-height:6px;font-size:6px;">&nbsp;</div>{}{}'
                  '</td></tr>').format(
                      para("{}&nbsp; <b>{}</b> &nbsp;<span style=\"color:{};\">{} all time</span>"
                           .format(ACTIVITIES[activity][1], ACTIVITIES[activity][0], MUTED,
                                   with_unit(activity, total)), 15, INK, line=1.4),
                      bar(spot["share"], colour, 8),
                      para("<b>{:.0f}%</b> of the way {}to <b>{}</b> &nbsp;&middot;&nbsp; "
                           "{} to go".format(spot["share"] * 100,
                                             "from {} ".format(humanize(activity, spot["reached"]))
                                             if spot["reached"] else "",
                                             with_unit(activity, spot["target"]),
                                             with_unit(activity, spot["to_go"])),
                           13, MUTED, top=6))
    if not rungs:
        return ""
    return band(section_head("milestones", "Next milestones",
                             "All-time totals, and the next round number each is heading for.",
                             colour, "\U0001F3AF", images) +
                SPACER.format(4) + "{}>{}</table>".format(TABLE, rungs), top=30)


HEAD_STYLE = "letter-spacing:0.8px;text-transform:uppercase;border-bottom:1px solid {};".format(LINE)
ROW_LINE = "border-bottom:1px solid #F1F5F9;"
SPACER = '<div style="height:{0}px;line-height:{0}px;font-size:{0}px;">&nbsp;</div>'


AVATAR_COLOURS = ("#1D4ED8", "#047857", "#6D28D9", "#B45309", "#0E7490", "#BE185D")


def initials(name):
    """'Rohit Kumar Rathore' -> 'RR': the first letter of the first and last names."""
    words = re.findall(r"[^\W\d_]+", str(name or ""), re.UNICODE)
    if not words:
        return "?"
    return (words[0][0] + (words[-1][0] if len(words) > 1 else "")).upper()


def avatar(ctx, pid, name, size):
    """A person's face as a small round picture, or their initials on a colour of their
    own when they have no photo of their own. '' when photos are switched off.

    Inline, so it sits in a line of text and in a table cell alike. The picture has no
    alt text on purpose: the name is written right beside it, and a screen reader should
    not say it twice. A client that blocks images shows the name alone; one that draws
    no rounded corners (Outlook) shows a small square."""
    photos = ctx.get("photos")
    if photos is None:
        return ""
    url = photos.get(pid) or ""
    if url:
        return ('<img src="{u}" alt="" width="{s}" height="{s}" style="width:{s}px;height:{s}px;'
                'border-radius:{r}px;border:0;vertical-align:middle;">').format(
                    u=escape(url, quote=True), s=size, r=size // 2)
    colour = AVATAR_COLOURS[zlib.crc32(str(pid or name).encode("utf-8")) % len(AVATAR_COLOURS)]
    return ('<span style="display:inline-block;width:{s}px;height:{s}px;line-height:{s}px;'
            'border-radius:{r}px;background-color:{c};color:#FFFFFF;font-family:{f};'
            'font-size:{t}px;font-weight:700;text-align:center;vertical-align:middle;">{i}'
            '</span>').format(s=size, r=size // 2, c=colour, f=FONT, t=max(8, size * 2 // 5),
                              i=escape(initials(name)))


BOARD_PHOTO = 30            # px, beside a name on a podium
RECORD_PHOTO = 24           # px, before a record holder's name


def board_rows(ctx, boards):
    """The rows of a podium, for the all-time one and the month's alike: the activity as a
    short heading, and its top three side by side in three equal columns -- each a face (or,
    with photos off, the medal) with the name beside it and the medal and figure under the
    name.

    Face beside name rather than above it keeps a podium to about half the height, and the
    columns keep each place in its own space, lined up from one activity to the next. A
    podium with fewer than three keeps its empty columns, so first place is always in the
    same spot."""
    lines = ""
    for activity, placed in boards:
        shown = [(name, with_unit(activity, total, short=activity == "step"), pid)
                 for name, total, pid in placed]
        lines += podium_line(ctx, "{}&nbsp; <b>{}</b>".format(
            ACTIVITIES[activity][1], ACTIVITIES[activity][0]), shown)
    return "{}>{}</table>".format(TABLE, lines)


def podium_line(ctx, heading, placed):
    """One podium of board_rows: `heading` (html) over up to three (name, figure, id), side
    by side in three equal columns. The challengers' podium is drawn the same way."""
    faces = ctx.get("photos") is not None
    cells = ""
    for i in range(3):
        if i >= len(placed):
            cells += '<td width="33%">&nbsp;</td>'
            continue
        name, figure, pid = placed[i]
        mark = avatar(ctx, pid, name, BOARD_PHOTO) if faces \
            else '<span style="font-size:20px;line-height:24px;">{}</span>'.format(MEDALS[i])
        cells += ('<td width="33%" valign="top" style="padding:0 6px 0 0;">'
                  '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
                  '<td width="{s}" valign="middle" style="width:{s}px;padding-right:7px;'
                  'font-size:0;line-height:0;">{mark}</td><td valign="middle">{name}{fig}'
                  '</td></tr></table></td>').format(
                      s=BOARD_PHOTO, mark=mark,
                      name=para(escape(name), 13, "#374151", 600, line=1.25),
                      fig=para("{}{}".format(MEDALS[i] + "&nbsp;" if faces else "",
                                             escape(figure)), 12, MUTED, top=1, line=1.3))
    return ('<tr><td style="padding:10px 0 11px 0;border-bottom:1px solid {};">{}{}'
            '{}><tr>{}</tr></table></td></tr>').format(
                LINE, para(heading, 15, INK, line=1.3), SPACER.format(7), TABLE, cells)


def all_time_boards_html(ctx, images):
    """The all-time podium (see board_rows). The section's line says "all time" once, for
    every podium."""
    if not ctx["podium"]:
        return ""
    return band(section_head("boards", "On the boards",
                             "The all-time top three in each activity.",
                             OTHER_SECTIONS["boards"], "\U0001F3C6", images) +
                SPACER.format(2) + board_rows(ctx, ctx["podium"]), top=30)


def month_boards_head(ctx=None):
    """The banner over the month's podium, in one line like the other banners: the title,
    and the question the boards answer after it in a lighter weight (on a phone it wraps
    rather than shrinks). The blue of the hero rather than the all-time podium's slate, so
    the two do not read as one header said twice. The month is not repeated here: the hero
    above has said it."""
    colour = "#1D4ED8"
    return ('{} bgcolor="{c}" style="background-color:{c};background-image:linear-gradient('
            '135deg,#0056D2 0%,#1D4ED8 55%,#3730A3 100%);border-radius:10px;"><tr>'
            '<td style="padding:14px 18px;{f}">This month’s top three'
            '<span style="{s}">&nbsp;&nbsp;&middot;&nbsp; Who logged the most in each '
            'activity.</span></td></tr></table>').format(
                TABLE, c=colour, f=font(18, "#FFFFFF", 700, 1.3),
                s=font(13, "#E3EDFF", 400, 1.3, "font-weight:400;"))     # font() leaves 400 to inherit


def month_boards_html(ctx):
    """The month's top three, under the all-time podium, in the same activities and laid out
    the same way (see board_rows), with a banner of its own (see month_boards_head)."""
    if not ctx["month_podium"]:
        return ""
    return band(month_boards_head(ctx) + SPACER.format(2) +
                board_rows(ctx, ctx["month_podium"]), top=30)


def boards_html(ctx, images):
    """The all-time podium, then the month's top three under it."""
    return all_time_boards_html(ctx, images) + month_boards_html(ctx)


CHALLENGE_STAT = ("#FDF2F8", "#FBCFE8")      # the three figures' tint and edge


def challengers_html(ctx, images):
    """The month's weekly challenges (see challengers_of): three figures, the top three
    challengers on a podium like the boards', who cleared every one they took on, and the
    challenges taken on most, as a board with a column each for taken on and cleared."""
    got = ctx.get("challengers")
    if not got or not got.get("taken"):
        return ""
    colour = OTHER_SECTIONS["challengers"]
    tint, edge = CHALLENGE_STAT
    share = int(round(100.0 * got["cleared"] / got["taken"]))
    stats = (("{:,}".format(got["people"]), "challengers" if got["people"] != 1 else "challenger"),
             ("{:,}".format(got["taken"]), "taken on"),
             ("{:,}".format(got["cleared"]), "cleared &middot; {}%".format(share)))
    cells = "".join(
        ('<td width="33%" valign="top" style="padding:4px;">{t} bgcolor="{bg}" '
         'style="background-color:{bg};border:1px solid {e};border-radius:10px;"><tr>'
         '<td align="center" style="padding:10px 6px;">{n}{l}</td></tr></table></td>').format(
             t=TABLE, bg=tint, e=edge, n=para(figure, 24, colour, 700, line=1.1),
             l=para(label, 12, MUTED, 600, top=3, line=1.3))
        for figure, label in stats)
    inner = section_head("challengers", "Challengers",
                         "The weekly challenges: who took them on, and who cleared them.",
                         colour, "⚔️", images)
    inner += SPACER.format(8) + "{}><tr>{}</tr></table>".format(TABLE, cells)
    inner += para("Across {} of challenges{}.".format(
        plural(got["weeks"], "week"), "" if got["finished"] else " so far"),
        13, MUTED, top=8, more="text-align:center;")
    if got["top"]:
        placed = [(p["name"], "{} of {} cleared".format(p["cleared"], p["taken"]), p["id"])
                  for p in got["top"]]
        inner += SPACER.format(6) + "{}>{}</table>".format(
            TABLE, podium_line(ctx, "\U0001F3C5&nbsp; <b>Top challengers</b>", placed))
    if got["sweep"]:
        inner += para("\U0001F31F&nbsp; Cleared every challenge they took on: {}.".format(
            names_html([p["name"] for p in got["sweep"]], limit=5)), 14, INK, top=12)
    if got["challenges"]:
        head = font(11, FAINT, 700, 1.3, HEAD_STYLE)
        lines = ('<tr><td style="padding:0 0 6px 0;{h}">Most taken on</td>'
                 '<td align="right" width="76" style="padding:0 0 6px 8px;{h}">Taken on</td>'
                 '<td align="right" width="76" style="padding:0 0 6px 8px;{h}">Cleared</td>'
                 '</tr>').format(h=head)
        cell = "padding:9px 0 9px {}px;" + ROW_LINE
        for line in got["challenges"][:CHALLENGE_LINES]:
            title, emoji = CHALLENGE_NAME[line["key"]]
            lines += ('<tr><td valign="top" style="{}{}">{}&nbsp; <b>{}</b>{}</td>'
                      '<td align="right" valign="top" style="{}{}">{}</td>'
                      '<td align="right" valign="top" style="{}{}">{}</td></tr>').format(
                          cell.format(0), font(14, INK, 400, 1.4), emoji, escape(title),
                          para(plural(line["people"], "person", "people"), 12, FAINT, line=1.3),
                          cell.format(8), font(14, MUTED, 400, 1.4), line["taken"],
                          cell.format(8), font(14, INK, 700, 1.4), line["cleared"])
        inner += SPACER.format(16) + "{}>{}</table>".format(TABLE, lines)
    return band(inner, top=30)


def held_by(ctx, holder, pid, faces):
    """The "Held by" cell of a board: the holder's face and name.

    With photos on, the face comes before the name, on every row: each record was earned
    on its own, so each one shows who earned it, however many in a row are theirs."""
    if not faces or not holder:
        return '<td valign="top" style="padding:9px 0 9px 18px;{}{}">{}</td>'.format(
            ROW_LINE, font(14, INK, 400, 1.4), escape(holder) if holder else "&ndash;")
    # The photo is taller than a line of text, so this cell is padded a little less: the
    # name then sits level with what is written in the other columns.
    face = avatar(ctx, pid, holder, RECORD_PHOTO)
    return ('<td valign="top" style="padding:7px 0 7px 18px;{line}">'
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td width="{s}" height="{s}" valign="middle" style="width:{s}px;height:{s}px;'
            'padding-right:8px;font-size:0;line-height:0;">{face}</td>'
            '<td valign="middle" style="{f}">{name}</td></tr></table></td>').format(
                line=ROW_LINE, s=RECORD_PHOTO, face=face or "&nbsp;",
                f=font(14, INK, 400, 1.4), name=escape(holder))


def records_html(ctx, images):
    """The channel records, as a board of their own: what the record is, the figure to
    beat, and who holds it (see held_by) -- each in its own column, so the figures line
    up."""
    rows = ctx["records"]
    if not rows:
        return ""
    named = any(holder for _i, _w, _v, holder, _p in rows)
    faces = named and ctx.get("photos") is not None
    head = font(11, FAINT, 700, 1.3, HEAD_STYLE)
    lines = ('<tr><td style="padding:0 0 6px 0;{h}">Record</td>'
             '<td align="right" width="92" style="padding:0 0 6px 8px;{h}">To beat</td>{by}</tr>'
             ).format(h=head, by='<td width="{}" style="padding:0 0 6px 18px;{}">Held by</td>'
                      .format("42%" if faces else "36%", head) if named else "")
    cell = "padding:9px 0 9px {}px;" + ROW_LINE
    for icon, what, value, holder, pid in rows:
        who = held_by(ctx, holder, pid, faces) if named else ""
        lines += ('<tr><td valign="top" style="{}{}">{}&nbsp; {}</td>'
                  '<td align="right" valign="top" style="{}{}white-space:nowrap;">{}</td>{}</tr>'
                  ).format(cell.format(0), font(14, INK, 400, 1.4), icon, escape(what),
                           cell.format(8), font(14, INK, 700, 1.4), escape(value), who)
    return band(section_head("records", "Channel records to beat",
                             "The best single effort in each activity, and three for showing up.",
                             OTHER_SECTIONS["records"], "\U0001F396\uFE0F", images) +
                SPACER.format(10) + "{}>{}</table>".format(TABLE, lines), top=30)


def games_html(ctx, images):
    """The games, as a board of their own, with a column each for players, games played,
    the top score and who holds it (see held_by). The headings sit at the bottom of their
    cells, so one that wraps on a phone ("Games / played") stays on the same line as the
    rest. A game's icon and name are joined by non-breaking spaces, so the longest name
    (iMemoryImage) never drops below its icon; the columns to its right are sized to leave
    it room on a desktop."""
    games = ctx["games"]
    if not games:
        return ""
    named = any(holder for _e, _t, _p, _g, _s, holder, _i in games)
    faces = named and ctx.get("photos") is not None
    head = font(11, FAINT, 700, 1.3, HEAD_STYLE)
    lines = ('<tr><td valign="bottom" style="padding:0 0 6px 0;{h}">Game</td>'
             '<td align="right" valign="bottom" width="56" style="padding:0 0 6px 8px;{h}">'
             'Players</td>'
             '<td align="right" valign="bottom" width="104" style="padding:0 0 6px 8px;{h}">'
             'Games played</td>'
             '<td align="right" valign="bottom" width="76" style="padding:0 0 6px 8px;{h}">'
             'Top score</td>{by}</tr>').format(
                 h=head, by='<td valign="bottom" width="{}" style="padding:0 0 6px 18px;{}">'
                 'Held by</td>'.format("31%" if faces else "28%", head) if named else "")
    cell = "padding:9px 0 9px {}px;" + ROW_LINE
    for emoji, title, players, played, top, holder, pid in games:
        who = held_by(ctx, holder, pid, faces) if named else ""
        lines += ('<tr><td valign="top" style="{}{}">{}&nbsp;&nbsp;<b>{}</b></td>'
                  '<td align="right" valign="top" style="{}{}">{}</td>'
                  '<td align="right" valign="top" style="{}{}">{:,}</td>'
                  '<td align="right" valign="top" style="{}{}">{}</td>{}</tr>').format(
                      cell.format(0), font(14, INK, 400, 1.4), emoji, escape(title),
                      cell.format(8), font(14, MUTED, 400, 1.4), players,
                      cell.format(8), font(14, MUTED, 400, 1.4), played,
                      cell.format(8), font(14, INK, 700, 1.4), top, who)
    return band(section_head("games", "Brain games",
                             "Short memory and maths games, played in the channel.",
                             OTHER_SECTIONS["games"], "\U0001F9E9", images) +
                SPACER.format(10) + "{}>{}</table>".format(TABLE, lines), top=30)


# The slash commands named at the very end, each with what it is for in a handful of words
# -- a reminder of what else the channel does, not a manual. /iweight is the weight check-in
# and progress graph (ihealth.py opens it; iweight_*.py handle the rest); /igratitude shares
# what somebody is grateful for, posted without a name.
SLASH_COMMANDS = (
    ("/iprofile", "Your own numbers, streak and rank"),
    ("/ichallenge", "Challenge a colleague to beat you"),
    ("/igratitude", "Share what you're grateful for, anonymously"),
    ("/iweight", "Track your weight, see your progress"),
)


def commands_html():
    """The slash commands as a short table: the command, then what it is for."""
    rows = ""
    for command, about in SLASH_COMMANDS:
        rows += ('<tr><td width="124" valign="top" style="padding:7px 0;{}{}"><b>{}</b></td>'
                 '<td valign="top" style="padding:7px 0;{}{}">{}</td></tr>').format(
                     font(14, BRAND, 700, 1.4), ROW_LINE, escape(command),
                     font(14, MUTED, 400, 1.4), ROW_LINE, escape(about))
    return (para("Also in the channel", 12, MUTED, 700, top=18,
                 more="letter-spacing:1.2px;text-transform:uppercase;") +
            SPACER.format(4) + "{}>{}</table>".format(TABLE, rows))


def fresh_start(ctx):
    """A line pointing at the month ahead, for the month-end email; '' mid-month."""
    if not ctx["finished"]:
        return ""
    ahead = (ctx["end"] + timedelta(days=1)).strftime("%B")
    if ctx["today"] <= ctx["end"]:
        return "{} starts tomorrow, which makes it a good day to begin.".format(ahead)
    return "{} has only just begun, so it is a good time to start.".format(ahead)


def join_html(ctx):
    """How it works, and the way in."""
    steps = (("1", "Do the thing", "A walk, ten pushups, five quiet minutes. Anything counts."),
             ("2", "Log it in the channel",
              "Post a trigger word and a number, such as <b>isteps 8000</b> or "
              "<b>iplanked 60 seconds</b>."),
             ("3", "Come back tomorrow", "Streaks, badges and shared milestones build from there."))
    cells = ""
    for number, title, text in steps:
        cells += ('<tr><td width="40" valign="top" style="padding:8px 0;">'
                  '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
                  '<td width="28" height="28" align="center" bgcolor="{b}" style="background-color:'
                  '{b};border-radius:14px;{f}">{n}</td></tr></table></td>'
                  '<td valign="top" style="padding:8px 0;">{t}{d}</td></tr>').format(
                      b=BRAND, f=font(14, "#FFFFFF", 700, 1), n=number,
                      t=para("<b>{}</b>".format(title), 15, INK, line=1.4),
                      d=para(text, 14, MUTED, top=2))
    channel = "#" + escape(ctx["channel_name"])
    if ctx["channel_url"]:
        button = ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                  'align="center"><tr><td align="center" bgcolor="{b}" style="background-color:{b};'
                  'border-radius:8px;"><a href="{u}" target="_blank" style="display:inline-block;'
                  'padding:13px 30px;{f}text-decoration:none;">Join {c} in Slack</a></td></tr>'
                  '</table>').format(b=BRAND, u=escape(ctx["channel_url"], quote=True),
                                     f=font(16, "#FFFFFF", 700, 1.2), c=channel)
    else:
        button = para("Find us in Slack: <b>{}</b>".format(channel), 16, BRAND, 700,
                      more="text-align:center;")
    inner = ('{} bgcolor="{}" style="background-color:{};border-radius:12px;"><tr>'
             '<td style="padding:22px 22px 24px 22px;">{}{}'
             '<div style="height:6px;line-height:6px;font-size:6px;">&nbsp;</div>'
             '{}>{}</table>'
             '<div style="height:16px;line-height:16px;font-size:16px;">&nbsp;</div>{}{}'
             '</td></tr></table>').format(
                 TABLE, TINT, TINT,
                 para("Want to join in?", 20, INK, 700, line=1.3),
                 para("{} It takes about ten seconds a day, and there is no minimum.".format(
                     fresh_start(ctx)), 14, MUTED, top=4),
                 TABLE, cells, button, commands_html())
    return band(inner, top=32)


def footer_html(ctx):
    facts = ctx["facts"]
    line = "All time: {} &nbsp;&middot;&nbsp; {} sessions".format(
        plural(facts["people"], "person", "people"), "{:,}".format(facts["logs"]))
    if facts["since"]:
        line += " since {} {}".format(facts["since"].day, facts["since"].strftime("%B %Y"))
    channel = escape(ctx["channel_name"])
    audience = ctx.get("audience", "active")
    if audience == "members":
        why = ("You are receiving this because you are a member of #{}. Leaving the "
               "channel stops these emails.").format(channel)
    elif audience == "ever":
        why = "You are receiving this because you have taken part in #{}.".format(channel)
    else:
        why = "You are receiving this because you logged an activity in #{} in {}.".format(
            channel, ctx["start"].strftime("%B"))
    # Replies to a recipe's mailbox are read by nobody; say so, and say where to ask.
    auto = ("This is an automated email, so please do not reply to it. "
            "Questions are welcome in #{} on Slack.".format(escape(ctx["channel_name"])))
    return ('<tr><td class="px" style="padding:26px {p}px 30px {p}px;font-family:{f};">'
            '<div style="height:1px;line-height:1px;font-size:1px;background-color:{l};">&nbsp;'
            '</div>{a}{b}{c}</td></tr>').format(
                p=PAD, f=FONT, l=LINE, a=para(line, 13, MUTED, top=18, more="text-align:center;"),
                b=para(why, 12, FAINT, top=8, more="text-align:center;"),
                c=para(auto, 12, FAINT, top=4, more="text-align:center;"))


def build_html(ctx, images, order=DEFAULT_ORDER):
    """The email: the hero, the sections in `order`, the footer."""
    def activities(key):
        return lambda: activities_html(ctx, images, (key,))

    makers = {
        "brief": lambda: brief_html(ctx),
        "tiles": lambda: tiles_html(ctx),
        "trend": lambda: trend_html(ctx),
        "checkins": lambda: checkins_html(ctx, images),
        "together": lambda: together_html(ctx, images),
        "milestones": lambda: milestones_html(ctx, images),
        "move": activities("move"), "strength": activities("strength"),
        "mind": activities("mind"), "habits": activities("habits"),
        "highlights": lambda: highlights_html(ctx, images),
        "calendar": lambda: calendar_html(ctx, images),
        "boards": lambda: boards_html(ctx, images),
        "challengers": lambda: challengers_html(ctx, images),
        "records": lambda: records_html(ctx, images),
        "games": lambda: games_html(ctx, images),
        "join": lambda: join_html(ctx),
    }
    body = hero_html(ctx, images) + "".join(makers[key]() for key in order if key in makers) \
        + footer_html(ctx)
    document = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light only">'
        '<meta name="supported-color-schemes" content="light only">'
        '<title>{title}</title>'
        '<style>body{{margin:0;padding:0;}}table{{border-collapse:separate;}}'
        '@media only screen and (max-width:480px){{.px{{padding-left:16px !important;'
        'padding-right:16px !important;}}.shell{{padding:0 !important;}}'
        '.badge{{display:block !important;width:auto !important;margin-bottom:8px !important;}}'
        '.gap{{display:none !important;}}}}</style></head>'
        '<body style="margin:0;padding:0;background-color:{page};font-family:{font};">'
        '<div style="display:none;max-height:0;max-width:0;overflow:hidden;opacity:0;'
        'font-size:1px;line-height:1px;color:{page};mso-hide:all;">{pre}</div>'
        '{table} bgcolor="{page}" style="background-color:{page};"><tr>'
        '<td class="shell" align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="{w}" cellpadding="0" cellspacing="0" border="0" '
        'bgcolor="{card}" style="width:100%;max-width:{w}px;background-color:{card};'
        'border-radius:14px;overflow:hidden;font-family:{font};">{body}</table></td></tr>'
        '</table></body></html>'
    ).format(title=escape(ctx["subject"]), page=PAGE, pre=escape(ctx["preheader"]),
             table=TABLE, w=WIDTH, card=CARD, body=body, font=FONT)
    # Every non-ASCII character (emoji, an accented name) as a numeric entity, so the
    # message is plain ASCII and survives whatever charset the connector sends it in.
    return document.encode("ascii", "xmlcharrefreplace").decode("ascii")


# -------------------------------------------------------------------- entry

def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    result = {
        "ok": False, "error": "", "subject": "", "preheader": "", "html": "",
        "html_bytes": 0, "recipients": "", "recipient_count": 0, "recipient_list": [],
        "missing_emails": [], "month": "", "period": "", "month_finished": False,
        "people_active": 0, "checkins": 0, "activities": 0, "new_people": 0,
        "summary": "", "summary_by_ai": False, "volume_since": "", "snapshot_saved": False,
        "recipients_source": "", "sections": "", "members_listed": 0,
        "slack_lookups": 0, "profiles_saved": 0,
        "challengers": 0, "challenges_taken": 0, "challenges_cleared": 0,
    }
    token = (input.get("workato_dev_api") or input.get("workato_api_token") or "").strip()
    slack_token = (input.get("slack_bot_token") or "").strip()
    channel_name = (input.get("channel_name") or DEFAULT_CHANNEL_NAME).strip().lstrip("#")
    show_names = truthy(input.get("show_names"), default=True)
    today = channel_today(input.get("tz_offset"), input.get("today"))
    channel_id = (input.get("channel_id") or "").strip()

    window = month_window(today, input.get("month"))
    if not window:
        result["error"] = "month must be blank, 'previous' or YYYY-MM, and not in the future"
        return result
    start, end, finished = window
    result["month"] = start.strftime("%Y-%m")
    result["period"] = day_span(start, end)
    result["month_finished"] = finished

    local_rows = []
    if input.get("local_data_file"):
        local_rows = load_local_rows(input["local_data_file"])
        # Only the rows the table query below would bring: a local file may also hold the
        # weekly challenges' rows, which are read on their own (see read_challenges).
        wanted_types = {a + "_users" for a in ACTIVITIES} | set(GAMES)
        rows = [r for r in local_rows if str(r.get("row_type") or "") in wanted_types]
    else:
        if not token:
            result["error"] = "workato_dev_api is required"
            return result
        row_types = [a + "_users" for a in ACTIVITIES] + list(GAMES)
        rows = fetch_rows(token, {"row_type": {"$in": row_types}})

    warnings, fatal = [], ""
    source, warning = recipient_source(input.get("recipients_from"), channel_id)
    if warning:
        warnings.append(warning)
    order, unknown_sections, left_out = section_order(input.get("section_order"))
    if unknown_sections:
        warnings.append("section_order: not a section: {}".format(", ".join(unknown_sections)))
    if left_out:
        warnings.append("section_order: left out of the email: {}".format(", ".join(left_out)))
    result["sections"] = ",".join(order)
    people, active = gather(rows, start, end)
    month = month_facts(people, start, end, finished, today)
    month["finished"] = finished
    facts = all_time(people)
    result["people_active"] = len(month["ids"])
    result["checkins"] = month["checkins"]
    result["activities"] = len(month["activities"])
    result["new_people"] = len(month["new_people"])
    if not month["ids"]:
        result["error"] = "nobody has logged in {} yet; no email built".format(
            start.strftime("%B %Y"))
        return result

    runs, warning = load_runs(token, input.get("local_snapshot_file") or "")
    if warning:
        warnings.append(warning)
    # This step's own totals from earlier runs. From a local file it only keeps one when
    # told where (local_email_snapshot_file), so a test never writes to the table.
    if input.get("local_email_snapshot_file"):
        store = FileOwnSnapshot(input["local_email_snapshot_file"])
    elif token and not input.get("local_data_file"):
        store = OwnSnapshot(token, (input.get("snapshot_row_type") or "").strip() or OWN_ROW_TYPE)
    else:
        store = None
    own_runs = []
    if store:
        own_runs, warning = store.load()
        if warning:
            warnings.append(warning)
    volume = month_volume(runs, facts, start, end, own_runs)
    result["volume_since"] = volume["since"].isoformat() if volume else ""

    channel_url = (input.get("channel_url") or "").strip()
    if channel_url and not re.match(r"^(https://|slack://)[^\s\"<>]+$", channel_url):
        warnings.append("channel_url ignored (not an https:// or slack:// link)")
        channel_url = ""

    ctx = {"channel_name": channel_name, "channel_url": channel_url, "today": today,
           "start": start, "end": end, "finished": finished, "span": day_span(start, end),
           "month": month, "facts": facts, "volume": volume, "show_names": show_names,
           "audience": source,
           "history": month_history(
               month, start, end, facts["since"],
               min(TREND_MONTHS, whole_number(input.get("trend_months"), TREND_MONTHS, 2))),
           "section_min_people": whole_number(input.get("section_min_people"),
                                              SECTION_MIN_PEOPLE),
           "always_show": activity_keys(input.get("always_show_activities"))}
    # The headline three, then whatever the recipe adds. A name that is not an activity,
    # or one with no milestone to climb, is said rather than silently dropped.
    extra, unknown = activity_list(input.get("milestone_activities"))
    refused = [a for a in extra if a in NO_MILESTONE]
    ctx["milestones"] = list(HEADLINE) + [a for a in extra
                                          if a not in HEADLINE and a not in NO_MILESTONE]
    if unknown:
        warnings.append("milestone_activities: not an activity: {}".format(", ".join(unknown)))
    if refused:
        warnings.append("milestone_activities: no milestone is kept for {}".format(
            ", ".join(refused)))
    ctx["brief"], result["summary_by_ai"], warning = month_brief(
        Azure(input.get("azure_api_key"), input.get("azure_url")), ctx)
    if warning:
        warnings.append(warning)
    result["summary"] = brief_text(ctx["brief"])

    ctx["highlights"] = highlights(people, month, facts, volume, start, end, show_names)
    # Hidden unless asked for: people are not yet familiar with badges, so the section is
    # left out of the email -- and not computed at all.
    ctx["badges"] = ([(badge, [(people[p]["name"], p) for p in pids])
                      for badge, pids in badges_this_month(people, start, end)]
                     if truthy(input.get("show_badges")) else [])
    with_board = show_names and truthy(input.get("show_leaderboard"), default=True)
    # More podiums than the automatic ones, when the recipe names them. As with the
    # milestones: a name that is no activity, or one that is never ranked, is said.
    board_extra, unknown = activity_list(input.get("board_activities"))
    if unknown:
        warnings.append("board_activities: not an activity: {}".format(", ".join(unknown)))
    unranked = [a for a in board_extra if a in NO_BOARD]
    if unranked:
        warnings.append("board_activities: {} never ranked".format(
            " and ".join(unranked) + (" is" if len(unranked) == 1 else " are")))
    board_min = whole_number(input.get("board_min_people"), BOARD_MIN_ACTIVE)
    ctx["podium"] = podium(people, month, with_board, board_extra, board_min)
    ctx["month_podium"] = month_podium(people, month, with_board, start, end, board_extra,
                                       board_min)
    if with_board:
        shown = {activity for activity, _placed in ctx["podium"]}
        empty = [a for a in board_extra if a not in NO_BOARD and a not in shown]
        if empty:
            warnings.append("board_activities: no board for {} (nobody has {} logged days "
                            "in it yet)".format(", ".join(empty), MIN_BOARD_DAYS))
    ctx["records"], ctx["unclaimed"] = records(
        people, facts, show_names,
        whole_number(input.get("records_min_people"), RECORD_MIN_PEOPLE))
    ctx["games"] = game_lines(rows, show_names)
    # The weekly challenges: read only when the section is in the email.
    ctx["challengers"] = None
    if "challengers" in order:
        if input.get("local_data_file"):
            posts, accepts, holders = split_challenge_rows(local_rows)
            if channel_id:
                posts = [p for p in posts if str(p.get("slack_channel_id") or "") == channel_id]
            warning = ""
        else:
            posts, accepts, holders, warning = read_challenges(token, channel_id, start, end)
        if warning:
            warnings.append(warning)
        else:
            ctx["challengers"] = challengers_of(posts, accepts, holders, rows, start, end,
                                                finished, show_names)
            result["challengers"] = ctx["challengers"]["people"]
            result["challenges_taken"] = ctx["challengers"]["taken"]
            result["challenges_cleared"] = ctx["challengers"]["cleared"]

    # Who everybody is: from the rows saved by earlier runs, and from Slack for anybody
    # with no row yet (see "saved Slack profiles"). Read only when Slack would be asked.
    asking = bool(slack_token) and not truthy(input.get("skip_email_lookup"))
    profile_store, saved_profiles = None, {}
    if asking and truthy(input.get("use_saved_profiles"), default=True):
        if input.get("local_profiles_file"):
            profile_store = FileProfileStore(input["local_profiles_file"])
        elif token and not input.get("local_data_file"):
            profile_store = ProfileStore(
                token, (input.get("profile_row_type") or "").strip() or PROFILE_ROW_TYPE)
        if profile_store:
            saved_profiles, warning = profile_store.load()
            if warning:
                warnings.append(warning)
    profiles = Profiles(saved_profiles)

    # Faces beside the names on the boards, in the records and in the games. Found before
    # the page is built; the same answers give the recipients' addresses further down.
    # None means "no photos": those sections are then laid out exactly as without them.
    ctx["photos"] = None
    if show_names and truthy(input.get("show_photos"), default=True) and asking:
        # The month's podium last: its winners are mostly the all-time ones, already asked
        # about, and what is left of the time budget goes to the people who are new here.
        wanted = [pid for _i, _w, _v, _h, pid in ctx["records"] if pid] + \
                 [pid for _a, placed in ctx["podium"] for _n, _t, pid in placed] + \
                 [pid for _e, _t, _p, _g, _s, _h, pid in ctx["games"] if pid] + \
                 [pid for _a, placed in ctx["month_podium"] for _n, _t, pid in placed] + \
                 [p["id"] for p in (ctx["challengers"] or {}).get("top", [])] + \
                 [pid for _b, earners in ctx["badges"] for _n, pid in earners[:BADGE_NAMES]]
        photos, warning = holder_photos(slack_token, wanted, profiles)
        if warning:
            warnings.append(warning)
        if photos:
            ctx["photos"] = photos

    title = " ".join(w.capitalize() for w in re.split(r"[-_\s]+", channel_name) if w)
    ctx["subject"] = "{}: {} {}".format(title, start.strftime("%B %Y"),
                                        "in review" if finished else "so far")
    ctx["preheader"] = "{}, {} and {} in {}.".format(
        plural(len(month["ids"]), "person", "people"), plural(month["checkins"], "check-in"),
        plural(len(month["activities"]), "activity", "activities"), day_span(start, end))
    # The icon goes on the subject the recipe sends, not on the page's <title>, which no
    # inbox shows: the email itself is the same with or without it.
    icon, warning = subject_icon(input.get("subject_icon"))
    if warning:
        warnings.append(warning)
    result["subject"] = "{} {}".format(icon, ctx["subject"]) if icon else ctx["subject"]
    result["preheader"] = ctx["preheader"]

    images, image_warnings = resolve_images(input.get("hero_image_url"),
                                            input.get("section_image_urls"))
    warnings.extend(image_warnings)
    result["html"] = build_html(ctx, images, order)
    result["html_bytes"] = len(result["html"])
    if result["html_bytes"] > GMAIL_CLIP_BYTES:
        warnings.append("the email is {:,} bytes; Gmail clips a message at about 102,000"
                        .format(result["html_bytes"]))

    # Today's totals, for next month's email to count from. Saved once the email is built,
    # so a run that fails before this point leaves the history as it was. A dry run is the
    # same email with this one write left out -- it is the only thing this step stores.
    if truthy(input.get("dry_run")):
        warnings.append("dry run: nothing stored in the table")
    elif store and truthy(input.get("save_snapshot"), default=True):
        error = store.save(with_run(own_runs, {"d": today.isoformat(),
                                               "t": dict(facts["totals"])}))
        if error:
            warnings.append(error)
        else:
            result["snapshot_saved"] = True

    if truthy(input.get("skip_email_lookup")):
        warnings.append("email lookup skipped; {} active this month".format(len(active)))
    else:
        domains = tuple(d.strip().lower().lstrip("@") for d in
                        re.split(r"[,\s;]+", str(input.get("allowed_email_domains") or ""))
                        if d.strip())
        # Who to write to. Names come from the table where it has them; the rest are
        # filled in from the Slack profile.
        names = {}
        for row in rows:
            pid, name = str(row.get("id") or "").strip(), str(row.get("name") or "").strip()
            if pid and (name or pid not in names):
                names[pid] = name or names.get(pid, "")
        pool, used = active, source
        if source == "members":
            ids, error = channel_members(slack_token, channel_id)
            result["members_listed"] = len(ids)
            if error or not ids:
                # Not a quiet fall back to the active few: that went out looking like it
                # had worked. No list, and the step says so.
                fatal = "could not list the members of {} ({}); no recipients".format(
                    channel_id, error or "the channel has no members")
                used, pool = "members_unavailable", {}
            else:
                pool = {pid: names.get(pid, "") for pid in ids}
        elif source == "ever":
            pool = dict(names)
        result["recipients_source"] = used
        found, missing, warning = find_recipients(slack_token, pool, domains, profiles)
        if warning:
            warnings.append(warning)
        result["recipient_list"] = found
        result["missing_emails"] = missing
        result["recipients"] = ", ".join(r["email"] for r in found)
        result["recipient_count"] = len(found)
        if missing:
            warnings.append("{} active {} could not be given an address (see missing_emails)"
                            .format(len(missing), "person" if len(missing) == 1 else "people"))
        # A row for everybody Slack was asked about, so the next run need not ask. Last,
        # and on a budget: the email is built and its recipients found before any of it.
        if profile_store and not truthy(input.get("dry_run")):
            result["profiles_saved"], warning = save_profiles(
                profile_store, profiles, names, today.isoformat())
            if warning:
                warnings.append(warning)
    result["slack_lookups"] = profiles.asked

    result["ok"] = not fatal
    result["error"] = "; ".join(([fatal] if fatal else []) + warnings)
    return result


def cli():
    parser = argparse.ArgumentParser(description="Build the monthly channel email.")
    parser.add_argument("--month", help="blank for this month so far, 'previous', or YYYY-MM")
    parser.add_argument("--today", help="YYYY-MM-DD, to build it as of another day")
    parser.add_argument("--channel-name")
    parser.add_argument("--channel-url")
    parser.add_argument("--subject-icon", help="emoji before the subject; 'none' for no icon")
    parser.add_argument("--hero-image-url")
    parser.add_argument("--section-image-urls", help="JSON object keyed by section")
    parser.add_argument("--allowed-email-domains")
    parser.add_argument("--channel-id")
    parser.add_argument("--recipients-from", help="members, ever or active")
    parser.add_argument("--section-order", help="comma separated sections, in order")
    parser.add_argument("--no-names", action="store_true", help="counts only, nobody named")
    parser.add_argument("--no-leaderboard", action="store_true")
    parser.add_argument("--board-activities", help="more podiums, comma separated")
    parser.add_argument("--board-min-people", type=int)
    parser.add_argument("--show-badges", action="store_true", help="include Badges earned")
    parser.add_argument("--no-photos", action="store_true", help="names only, no profile photos")
    parser.add_argument("--records-min-people", type=int)
    parser.add_argument("--section-min-people", type=int)
    parser.add_argument("--always-show-activities")
    parser.add_argument("--milestone-activities")
    parser.add_argument("--trend-months", type=int)
    parser.add_argument("--local-data-file")
    parser.add_argument("--local-snapshot-file")
    parser.add_argument("--local-email-snapshot-file")
    parser.add_argument("--local-profiles-file")
    parser.add_argument("--skip-email-lookup", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="build only: store nothing")
    parser.add_argument("--out", help="write the email to this file, to open in a browser")
    args = parser.parse_args()

    payload = vars(args)
    out = payload.pop("out")
    payload["show_names"] = not payload.pop("no_names")
    payload["show_leaderboard"] = not payload.pop("no_leaderboard")
    payload["show_photos"] = not payload.pop("no_photos")
    payload["workato_dev_api"] = os.environ.get("WORKATO_API_TOKEN", "")
    payload["slack_bot_token"] = os.environ.get("SLACK_BOT_TOKEN", "")
    payload["azure_api_key"] = os.environ.get("AZURE_API_KEY", "")
    result = main(payload)
    page = result.pop("html", "")
    if out and page:
        with open(out, "w", encoding="ascii") as handle:
            handle.write(page)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:  # noqa: BLE001
        sys.exit(str(exc))
