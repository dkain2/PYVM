"""
Spotter -- one Python step that replaces the whole activity pipeline.

Supersedes: entry_recipe's python step, ochestration_recipe (87 steps),
data_table_update (37 steps), the Health Activity Responder genie, and both
of its skills. The recipe now only needs to receive the Slack trigger and hand
the fields below to main().

WHAT IT DOES, in order:
    1. Detect every activity keyword in the message (one message may log several).
    2. One LLM call extracts the total and max-per-set for all of them at once.
    3. Per activity: read the row, classify the outcome, write the row back.
    4. One threaded reply covering everything logged.
    5. A channel announcement only when a record actually broke.

DESIGN NOTES
    * Two LLM calls per message, not six. Extraction is one structured call for
      all activities; composition is one call that returns prose only.
    * The model never produces structure. Python builds the Block Kit, so there
      is nothing to regex-scrub, and a deterministic template ships if the LLM
      fails. The post always goes out.
    * Tier ladders, tones and scenarios are data, not nested ternaries.
    * Column UUIDs appear exactly once, in COLUMNS.
    * Everything between parsing and posting is a pure function, so the streak
      state machine is testable without Slack or Workato.

Input and output schemas: spotter_input_schema.json / spotter_output_schema.json
"""

import json
import math
import os
import random
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

TABLE_ID = "0b863cb1-4712-416b-a9d5-7bf7f2f9b059"
TABLE_QUERY_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
TABLE_RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
# There is no upsert endpoint: POST /records creates, PUT /records/{record_id}
# updates, and the record_id comes from the $record_id metafield on a query.
TABLE_RECORD_URL = TABLE_RECORDS_URL + "/{}"

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
SLACK_UPDATE_URL = "https://slack.com/api/chat.update"
SLACK_DELETE_URL = "https://slack.com/api/chat.delete"
SLACK_REACT_URL = "https://slack.com/api/reactions.add"

# Posted the moment work starts, then edited into the real reply. Two LLM calls
# and several table reads take a few seconds; without this the thread sits empty
# and people repost. The words come from the activity (THINKING_WORDS, with the reply
# emoji); this is for a keyword that has none.
THINKING_TEXT = "Thinking\u2026 :loading-2:"
THINKING_SPINNER = ":loading-2:"
SLACK_USER_URL = "https://slack.com/api/users.info"
AZURE_URL = ("https://cour-servicenow-1.openai.azure.com/openai/deployments/"
             "gpt-4o/chat/completions?api-version=2024-10-21")

# Each person's day boundary is their own. A streak, a "same day" repeat and a
# heatmap square all mean "in the poster's local day", so every date is derived
# from the tz_offset Slack reports for that user. Slack has already resolved DST
# by the time it hands us the offset, so no timezone database is needed.
#
# Used only when the users.info lookup fails: the channel's original zone.
DEFAULT_TZ_OFFSET = -7 * 3600     # America/Los_Angeles
HTTP_TIMEOUT = 30

# Golden: ~6 in 100 posts, and never twice within this many days.
GOLDEN_TS_CUTOFF = 6
GOLDEN_COOLDOWN_DAYS = 7

STREAK_MILESTONES = (7, 14, 21, 30, 50, 100)

# Rough pedometer conversion, for a friendly km figure next to a step count.
# An average adult stride is ~0.76m, so ~1,312 steps cover one kilometre. An
# approximation, shown as "~", never stored and never treated as exact.
STEPS_PER_KM = 1312

# How close a chaser has to be, relative to the leader's own total, before
# they are worth a second mention. Relative rather than a fixed step/rep
# count, because "500 behind" is nothing on a 150,000-step board and huge on
# a 600-rep one -- each activity's own scale decides what "close" means.
CLOSE_CHASE_RATIO = 0.05

# Extraction retries. The model occasionally returns nothing for a message that
# plainly contains a count -- "imeditate for half an hour" came back empty in
# production. Retries only fire on that exact failure, so a normal message still
# costs one call.
EXTRACT_ATTEMPTS = 3

# A number that would take a channel record gets one confirmation call before it
# is believed. Wrong numbers are survivable; a wrong number enshrined as the
# channel record is not.
CONFIRM_RECORDS = True

# A coaching note fires only once there is enough history to read a real
# trend from -- fewer sessions than this and there is nothing yet to say that
# is not invented.
MIN_SESSIONS_FOR_COACHING = 3
COACH_HISTORY_WINDOW = 8   # most recent sessions shown to the coach
HEATMAP_KEEP_DAYS = 371

# --- Where a person's session list lives -------------------------------------------------
#
# `total` is a comma-separated list of every session a person has ever logged
# ("40,28,45,...") and, unlike the date lists (kept to a year, ~4,000 characters), it only
# ever grows. A Workato text column holds 10,000 characters, and a write over that is
# REFUSED by the table -- the person's log would be lost. A step count is five digits, so a
# person logging a few times a day gets there within a couple of years.
#
# So the list is spread over several columns, in order. `total` stays the first, which is
# why nothing that already reads or writes it has to move; once it is full the list carries
# on in the spare columns below. None of these four is used on an activity row (weight
# tracking keeps its own health_users rows; the leaderboard uses them on its own snapshot
# rows), and each already exists in the table. Capacity is 5 x 9,500 = 47,500 characters,
# some 8,000 five-digit sessions.
#
# To add room: create another text column, add its UUID to COLUMNS and its name to the END
# of this tuple. Never reorder or remove one -- the order IS the order of the data.
#
# Everything in this file works with the whole list as one string. It is cut up on the way
# into the table (Table._document) and joined on the way out (Table.query), at commas, so
# a number is never split in two. Anything else that reads `total` must join the columns
# the same way (see stored_sessions) or it will see only the first 9,500 characters.
TOTAL_COLUMNS = ("total", "plank_photo", "current_weight", "current_fat", "current_muscle")
COLUMN_CHUNK = 9500                  # 500 under the 10,000 limit, as the leaderboard keeps
TOTAL_CAPACITY = COLUMN_CHUNK * len(TOTAL_COLUMNS)


# --------------------------------------------------------------------------
# Column map -- the only place a field UUID appears
# --------------------------------------------------------------------------

COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "current_value": "20b624b5-587c-4a2e-aa43-bdb8e21a5fe9",
    "plank_duration": "7c46ae93-c5a9-410a-bd1d-27d4dbec30e5",
    "total": "e96b5acc-4196-497e-a18b-7faf7016ec4c",
    "direct_grant_count": "fb1a16ae-de15-4a5b-9772-cdd7ea78809b",
    "max_of_this_set": "9d21ef32-b766-4d83-a747-efda4ebe4102",
    "personal_best_single_set": "6198fe02-e888-44a8-bd01-b47d75ee896d",
    "total_planks": "ea80e176-5bfb-421d-bafe-dd4828d67916",
    "heatmap_dates": "7f8871d1-1613-4faa-94e6-a7ef3649cc25",
    "plank_tier": "b346d073-149f-43c1-b38e-58c14c6358e8",
    "first_seen": "0e8058db-6de1-4bae-98eb-4e45fc506435",
    "current_streak": "4d1c875f-fa4d-474d-9610-82e07f0a98b6",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
    "longest_streak": "f7da78dd-d5db-4e94-befa-7fc5c3ffc1dc",
    "daily_post_count": "cea486f4-455c-4fd0-b2a2-6e1a6618b751",
    "leaderboard_optout": "101f8dcb-f067-4045-af61-0799494651b8",
    "freeze_credits": "05190c05-4687-4ea2-9cbe-38985296ff20",
    "week_count": "78f82863-cd14-470b-9df7-15e4b9c2de95",
    "last_processed_ts": "5761a90c-832e-4bf5-aaee-5d6a4d43f045",
    "golden_dates": "b9517b86-4175-4d78-80b1-dfbf832f803c",
    "plank_photo": "f801caa5-b3c2-4f07-a98c-7b2d24c66689",
    "current_weight": "08ec0542-79af-43a9-8d58-de30e14a6c51",
    "current_fat": "ce9c49a6-c1f9-4169-8833-a3721d6c38b5",
    "current_muscle": "ac156767-3d8e-42d1-bcd9-b78ca84b6d51",
    "last_golden_date": "1dca704b-ecff-4935-9a9c-dc12151ed0e1",
    "is_private": "5b646ace-6026-4395-ae8e-1cb513b1e9b8",
    # events (see the events section): which event a row belongs to, and for which activity
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "grant_type": "355e769f-0aa3-46be-bea3-5c2b3442f658",
    # weekly challenges (see the weekly challenge section): where an accepted goal is kept
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
}


# Declared type of every column we write. The API rejects the whole
# document on a single mismatch -- current_value is a string field even
# though it holds a number -- so values are coerced before sending.
COLUMN_TYPES = {
    "record_key": "string",
    "row_type": "string",
    "id": "string",
    "name": "string",
    "current_value": "string",
    "plank_duration": "integer",
    "total": "string",
    "direct_grant_count": "integer",
    "max_of_this_set": "integer",
    "personal_best_single_set": "integer",
    "total_planks": "integer",
    "heatmap_dates": "string",
    "plank_tier": "string",
    "first_seen": "date",
    "current_streak": "integer",
    "updated_at": "date",
    "longest_streak": "integer",
    "daily_post_count": "integer",
    "leaderboard_optout": "boolean",
    "freeze_credits": "integer",
    "week_count": "integer",
    "last_processed_ts": "string",
    "golden_dates": "string",
    "plank_photo": "string",
    "current_weight": "string",
    "current_fat": "string",
    "current_muscle": "string",
    "last_golden_date": "date",
    "is_private": "boolean",
    "group_id": "string",
    "grant_type": "string",
    "content": "string",
}


# Columns read on every request. Asking for all 86 wastes payload.
READ_COLUMNS = [
    "record_key", "row_type", "id", "name", "current_value", "plank_duration",
    "total", "direct_grant_count", "max_of_this_set", "personal_best_single_set",
    "total_planks", "heatmap_dates", "plank_tier", "first_seen", "current_streak",
    "updated_at", "longest_streak", "daily_post_count", "freeze_credits",
    "week_count", "last_processed_ts", "golden_dates", "is_private",
]


# --------------------------------------------------------------------------
# Activity table -- name, units, synonyms, row_type, tone, tier ladder.
# Generated from the entry recipe's ACTIVITY_MAP, the orchestration recipe's
# current_tier ternary, and the Activity & Tone Decider skill, so the values
# match the live system exactly. Tones marked "added" did not exist before:
# those 12 activities fell through the skill to "cant decide".
# --------------------------------------------------------------------------

ACTIVITIES = {
    "IPUSHUP": {
        "name": 'Pushup',
        "unit_singular": 'rep',
        "unit_plural": 'reps',
        "row_type": 'pushup_users',
        "synonyms": 'pushup, push up, push-up, press up, press-up, pushups',
        "family": 'strength',
        "tone": (  # skill
            'High-energy, punchy, explosive. Energy scales with rep count — small sets '
            'get warm encouragement, big sets get full "ELITE, I need to sit down" hype. '
            'PR/tier language welcome when the data supports it. Every rep count gets '
            'full respect regardless of magnitude; 5 reps and 50 reps are both wins. '
        ),
        "tiers": [  # 10 rungs, highest first
            (5000, 'The Floor Fears You'),
            (3000, 'Obsidian Force'),
            (1500, 'The Feared'),
            (1000, 'The Unbroken'),
            (500, 'Chest of Steel'),
            (250, 'Steel Nerve'),
            (100, 'Iron Will'),
            (50, 'Ground Punisher'),
            (20, 'Building Force'),
            (1, 'First Push'),
        ],
    },
    "IPULLUP": {
        "name": 'Pullup',
        "unit_singular": 'rep',
        "unit_plural": 'reps',
        "row_type": 'pullup_users',
        "synonyms": 'pullup, pull up, pull-up, chin up, chinup',
        "family": 'strength',
        "tone": (  # skill
            'Check the input message again for words like ipullup, iswam,ipushup and '
            "call 'Activity & Tone Decider' Activity again "
        ),
        "tiers": [  # 10 rungs, highest first
            (1000, 'Gravity'),
            (750, 'Titan of the Bar'),
            (500, 'The Immovable'),
            (300, 'The Relentless'),
            (150, 'Bar Conqueror'),
            (75, 'Steel Grip'),
            (40, 'Iron Grip'),
            (20, 'Rising Force'),
            (5, 'Hang Tough'),
            (1, 'First Pull'),
        ],
    },
    "ISQUAT": {
        "name": 'Squat',
        "unit_singular": 'rep',
        "unit_plural": 'reps',
        "row_type": 'squat_users',
        "synonyms": 'squat, squats, air squat',
        "family": 'strength',
        "tone": (  # added
            'High-energy, punchy. Same performance family as pushups and pullups. PR and '
            'tier language welcome when the data supports it. 15 reps from someone '
            'starting out gets the same energy as 100 from a regular. '
        ),
        "tiers": [  # 10 rungs, highest first
            (3000, 'Earthquake'),
            (2000, 'Obsidian Stance'),
            (1500, 'Foundation Breaker'),
            (750, 'The Unshaken'),
            (400, 'Steel Quads'),
            (200, 'Iron Legs'),
            (100, 'Deep Dropper'),
            (50, 'Low & Loaded'),
            (15, 'Getting Low'),
            (1, 'First Drop'),
        ],
    },
    "IWORKOUT": {
        "name": 'Workout',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'workout_users',
        "synonyms": ('workout, worked out, working out, gym, gym session, lifting, weights, '
                     'training, pilates, bootcamp, boot camp, bootcamped'),
        "family": 'strength',
        "tone": (  # added
            'Energetic and encouraging without demanding detail -- this is the catch-all '
            'for a session that was not one single movement. Celebrate the minutes put '
            'in, never the exercises chosen or the weight moved. A 15-minute session '
            'gets the same respect as 90. '
        ),
        "tiers": [  # 10 rungs, highest first -- minutes
            (20000, 'Iron Immortal'),
            (10000, 'Training Legend'),
            (5000, 'The Relentless'),
            (2500, 'Forged in Reps'),
            (1500, 'Session Machine'),
            (500, 'Gym Regular'),
            (200, 'Building the Habit'),
            (100, 'Warmed Up'),
            (30, 'Getting Going'),
            (10, 'First Session'),
        ],
    },
    "IRUN": {
        "name": 'Run',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'run_users',
        "synonyms": 'run, running, ran, jog, jogging',
        "family": 'endurance',
        "tone": (  # added
            'Steady-effort endurance framing rather than explosive. Warm and '
            'encouraging. Celebrate distance covered and consistency, never pace. A slow '
            '10 minutes counts exactly as much as a fast 40. '
        ),
        "tiers": [  # 10 rungs, highest first
            (2000, 'Eternal Runner'),
            (1000, 'Marathon Legend'),
            (500, 'Ultra Relentless'),
            (250, 'Endurance Forged'),
            (100, 'Road Warrior'),
            (50, 'Distance Eater'),
            (25, 'Steady Strider'),
            (10, 'Trail Starter'),
            (3, 'Pace Finder'),
            (1, 'First Mile'),
        ],
    },
    "ISWAM": {
        "name": 'Swim',
        "unit_singular": 'minutes',
        "unit_plural": 'minutes',
        "row_type": 'swim_users',
        "synonyms": 'swim, swimming, swam, laps , swam for 1 hours',
        "family": 'endurance',
        "tone": (  # skill
            'Energetic, achievement-forward — same performance family as '
            'pushups/pullups/running. PR and record language welcome when the data '
            'supports it. Celebrate the whole range equally: 2 laps for someone building '
            'confidence in water gets the same energy as 40 laps from a regular. If '
            'duration is logged instead of laps, treat it the same as running — '
            'steady-effort endurance framing rather than single-rep explosiveness. '
        ),
        "tiers": [  # 10 rungs, highest first
            (50000, 'Poseidon'),
            (25000, 'Ocean Sovereign'),
            (10000, 'Leviathan'),
            (5000, 'Deep Current Master'),
            (2500, 'Tide Tamer'),
            (1000, 'Wave Rider'),
            (500, 'Current Breaker'),
            (200, 'Steady Swimmer'),
            (50, 'Finding Flow'),
            (1, 'First Splash'),
        ],
    },
    "ICARDIO": {
        "name": 'Cardio',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'cardio_users',
        "synonyms": 'cardio, cardio session, hiit, treadmill, elliptical, rowing machine, skipping',
        "family": 'endurance',
        "tone": (  # added
            'Steady-effort endurance framing, warm and encouraging. Celebrate minutes '
            'spent with the heart rate up and the consistency of coming back, never '
            'intensity or pace. A gentle 10 minutes counts exactly as much as a brutal '
            '45. '
        ),
        "tiers": [  # 10 rungs, highest first -- minutes
            (20000, 'Engine Eternal'),
            (10000, 'Heartbeat Legend'),
            (5000, 'Furnace'),
            (2500, 'Endurance Forged'),
            (1500, 'Steady Engine'),
            (500, 'Cardio Regular'),
            (200, 'Finding Rhythm'),
            (100, 'Warmed Up'),
            (30, 'Heart Rate Up'),
            (10, 'First Sweat'),
        ],
    },
    "ICYCLE": {
        "name": 'Cycling',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'cycle_users',
        "synonyms": 'cycle, cycling, cycled, bike, biking, biked, bike ride, spinning',
        "family": 'endurance',
        "tone": (  # added
            'Steady-effort endurance framing, warm and a little breezy. Celebrate time '
            'in the saddle and the habit of riding, never speed, distance or gear. A '
            'slow commute counts exactly as much as a long weekend ride. '
        ),
        "tiers": [  # 10 rungs, highest first -- minutes
            (20000, 'Eternal Rider'),
            (10000, 'Peloton Legend'),
            (5000, 'Mountain Conqueror'),
            (2500, 'Endless Saddle'),
            (1500, 'Road Regular'),
            (500, 'Steady Spinner'),
            (200, 'Finding Cadence'),
            (100, 'Wheels Rolling'),
            (30, 'Warming the Legs'),
            (10, 'First Ride'),
        ],
    },
    "ISTEPS": {
        "name": 'Steps',
        "unit_singular": 'step',
        "unit_plural": 'steps',
        "row_type": 'step_users',
        "synonyms": 'steps, walking, walked, step count',
        "family": 'habit',
        "tone": (  # skill
            'Modest, non-competitive, warm. Frame around building the habit of moving '
            'more instead of sitting for long hours — kitchen to bedroom, a short errand '
            'on foot, a small outdoor stroll all count equally. Never brag-framed, even '
            'with a record in the payload; acknowledge milestones gently rather than '
            'hyping them like a pushup PR. '
        ),
        "tiers": [  # 10 rungs, highest first
            (10000000, 'Crore Crusher'),
            (5000000, 'Half-Crore Hero'),
            (2000000, 'Two Million Titan'),
            (1000000, 'Millionaire Steps'),
            (500000, 'Five Lakh Legacy'),
            (250000, 'Quarter-Million Strider'),
            (100000, 'Lakh Club'),
            (50000, 'Fifty Thousand Strong'),
            (20000, 'Step Committed'),
            (5000, 'First Thousand'),
        ],
    },
    "ISTAIRS": {
        "name": 'Stairs',
        "unit_singular": 'flight',
        "unit_plural": 'flights',
        "row_type": 'stairs_users',
        "synonyms": 'stairs, staircase, flights, stair climbing',
        "family": 'habit',
        "tone": (  # added
            'Warm and lightly playful about the everyday nature of it. Frame around '
            'choosing the stairs over the lift, not athletic achievement. Milestones '
            'acknowledged gently. '
        ),
        "tiers": [  # 10 rungs, highest first
            (20000, 'Cloud Walker'),
            (10000, 'Summit Legend'),
            (5000, 'Skyline Climber'),
            (2500, 'Tower Conqueror'),
            (1500, 'Vertical Voyager'),
            (500, 'Elevator'),
            (200, 'Floor Crusher'),
            (100, 'Stair Regular'),
            (30, 'Step Up Starter'),
            (10, 'First Flight'),
        ],
    },
    "IDANCE": {
        "name": 'Dance',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'dance_users',
        "synonyms": 'dance, dancing, danced',
        "family": 'habit',
        "tone": (  # added
            'Joyful, loose, a bit silly. This is movement for fun, not performance. '
            'Never mention technique or skill. Celebrate that they moved at all. '
        ),
        "tiers": [  # 10 rungs, highest first
            (20000, 'Dance Immortal'),
            (10000, 'Legendary Mover'),
            (5000, 'Full-Body DJ'),
            (2500, 'Rhythm Royalty'),
            (1500, 'Dance Floor Royalty'),
            (500, 'Rhythm Regular'),
            (200, 'Groove Finder'),
            (100, 'Groove Starter'),
            (30, 'Beat Curious'),
            (10, 'First Move'),
        ],
    },
    "IPLANKED": {
        "name": 'Plank',
        "unit_singular": 'second',
        "unit_plural": 'seconds',
        "row_type": 'plank_users',
        "synonyms": 'plank, planking, planked, plank hold',
        "family": 'strength',
        "tone": (  # skill, with record language scoped
            'High-energy and celebratory. Every hold gets full respect '
            'regardless of duration -- 10 seconds and 3 minutes are both wins. '
            'PR language is welcome when the session numbers earn it. '
            'Theatrical record language -- thrones, rulers, coronations -- is '
            'for an ACTUAL channel record only and must never appear for an '
            'ordinary hold or for a tier crossing. No streak-shaming, ever. '
        ),
        "tiers": [  # 10 rungs, highest first
            (500, 'Time Stops For You'),
            (300, 'Dean'),
            (200, 'Core Faculty'),
            (150, 'Plank Professor'),
            (100, 'Plank 501'),
            (50, 'Plank 401'),
            (25, 'Plank 301'),
            (10, 'Plank 201'),
            (3, 'Plank 101'),
            (1, 'Enrolled'),
        ],
    },
    "IYOGA": {
        "name": 'Yoga',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'yoga_users',
        "synonyms": 'yoga, yoga session, asana',
        "family": 'stillness',
        "tone": (  # skill
            'Calm, grounding. Celebrate showing up on the mat, not flexibility or pose '
            'difficulty. No competitive language even with a longest-session record. '
        ),
        "tiers": [  # 10 rungs, highest first
            (20000, 'Transcendent'),
            (10000, 'The Grounded One'),
            (5000, 'Quiet Master'),
            (2500, 'Inner Architect'),
            (1500, 'Still Warrior'),
            (500, 'Rooted Flow'),
            (200, 'Steady Practice'),
            (100, 'Mat Regular'),
            (30, 'Finding Balance'),
            (10, 'First Pose'),
        ],
    },
    "IMEDITATE": {
        "name": 'Meditation',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'meditate_users',
        "synonyms": 'meditate, meditation, meditated, mindfulness',
        "family": 'stillness',
        "tone": (  # skill
            'Quiet, unhurried, almost hushed — should feel distinctly different from '
            'every other bot message. Celebrate the discipline of sitting, not duration. '
            'Never say "crushed" or "smashed. '
        ),
        "tiers": [  # 11 rungs, highest first
            (20000, 'The Void'),
            (10000, 'Silence Itself'),
            (5000, 'The Unshaken Mind'),
            (2500, 'Thought Transcender'),
            (1500, 'Deep Calm'),
            (500, 'Steady Stillness'),
            (200, 'Quiet Mind'),
            (100, 'Mindful Regular'),
            (30, 'Finding Stillness'),
            (10, 'First Long Sit'),
            (5, 'Eye Closed'),
        ],
    },
    "ISOLITUDE": {
        "name": 'Solitude',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'solitude_users',
        "synonyms": 'solitude, alone time, quiet time',
        "family": 'stillness',
        "tone": (  # skill
            'Reflective, respectful. No cheerleading energy — more a quiet nod of '
            'acknowledgment. Avoid making it feel observed or judged; this is someone '
            'choosing quiet on purpose. '
        ),
        "tiers": [],   # no ladder defined -- tier stays "none"
    },
    "IJOURNAL": {
        "name": 'Journaling',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'journal_users',
        "synonyms": 'journal, journaling, journaled, wrote',
        "family": 'stillness',
        "tone": (  # added
            'Quiet and thoughtful. Celebrate the act of sitting down to write, never the '
            'volume or quality of what was written. '
        ),
        "tiers": [  # 10 rungs, highest first -- minutes, same scale as yoga
            (20000, 'The Chronicler'),
            (10000, 'The Archivist'),
            (5000, 'Ink Unbroken'),
            (2500, 'Deep Reflection'),
            (1500, 'Steady Pen'),
            (500, 'Daily Ink'),
            (200, 'Finding Words'),
            (100, 'Journal Regular'),
            (30, 'Warming the Pen'),
            (10, 'First Entry'),
        ],
    },
    "IWRITE": {
        "name": 'Writing',
        "unit_singular": 'page',
        "unit_plural": 'pages',
        "row_type": 'write_users',
        "synonyms": 'write, writing, wrote, pages, draft, drafted',
        "family": 'stillness',
        "tone": (  # added
            'Quiet and thoughtful. Celebrate the pages written as evidence that they '
            'showed up to write, never as proof of quality. Keep the focus on the '
            'practice, not whether the writing was good. '
        ),
        "tiers": [  # 10 rungs, highest first -- pages
            (5000, 'The Manuscript'),
            (2500, 'The Scribe'),
            (1000, 'Ink River'),
            (500, 'Page Builder'),
            (250, 'Steady Draft'),
            (100, 'Writing Regular'),
            (50, 'Finding the Line'),
            (25, 'Pages Taking Shape'),
            (10, 'First Chapter'),
            (1, 'First Page'),
        ],
    },
    "IREAD": {
        "name": 'Reading',
        "unit_singular": 'page',
        "unit_plural": 'pages',
        "row_type": 'read_users',
        "synonyms": 'read, reading, book, pages',
        "family": 'habit',
        "tone": (  # added
            'Calm and warm. Celebrate the habit of reading, not the page count. Ten '
            'pages and a hundred are both a win. '
        ),
        "tiers": [  # 10 rungs, highest first -- pages
            (50000, 'The Library'),
            (25000, 'Shelf Conqueror'),
            (10000, 'Voracious'),
            (5000, 'Bookworm Ascendant'),
            (2500, 'Chapter Devourer'),
            (1000, 'Steady Reader'),
            (400, 'Page Regular'),
            (150, 'Getting Into It'),
            (50, 'First Chapters'),
            (10, 'First Pages'),
        ],
    },
    # The trigger word is `iprayanam`. Triggers are matched on their start, so `iprayanama`
    # logs here as well. The old `ibreath` words no longer do (RETIRED_TRIGGERS). `iboxbreath`,
    # the guided session (ibreath/ibreath.py), is a separate thing and does not begin with this.
    # `row_type` is what the table stores, so it keeps its old name: every existing row,
    # streak and record is filed under it.
    "IPRAYANAM": {
        "name": 'Pranayama',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'breathe_users',
        # Only the extractor reads these, to match a message to the activity. Nobody sees them.
        "synonyms": 'pranayama, pranayam, prayanama, prayanam, breathwork, breath work, breathing',
        "family": 'stillness',
        "tone": (  # added
            'Hushed and unhurried, close to the meditation voice. Celebrate the pause '
            "itself. Never say 'crushed' or 'smashed'. "
        ),
        # Cumulative minutes. Sized for about six minutes a day: the first rung is a couple
        # of days in, the next a week, and the top one is nine years of it. KEEP IN STEP
        # with BREATHE_TIERS in ibreath/ibreath.py, which logs a guided session the same way.
        "tiers": [  # 10 rungs, highest first -- minutes
            (20000, 'Unhurried'),
            (10000, 'The Quiet Between'),
            (5000, 'Prana Keeper'),
            (2500, 'Still Water'),
            (1500, 'Deep Exhale'),
            (500, 'Calm Anchor'),
            (200, 'Easy Rhythm'),
            (100, 'Steady Practice'),
            (30, 'Slowing Down'),
            (10, 'First Pause'),
        ],
    },
    "ICHANT": {
        "name": 'Chanting',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'chant_users',
        "synonyms": 'chant, chanting, chanted, mantra, mantras',
        "family": 'stillness',
        "tone": (  # added
            'Calm and devotional without being ornate. Celebrate the time spent in '
            'repetition and focus, not volume, skill or intensity. Keep it gentle, '
            'close to the meditation voice. '
        ),
        "tiers": [  # 10 rungs, highest first -- minutes
            (20000, 'Resonance'),
            (10000, 'The Steady Voice'),
            (5000, 'Mantra Keeper'),
            (2500, 'Deep Repetition'),
            (1500, 'Focused Sound'),
            (500, 'Chant Regular'),
            (200, 'Finding Rhythm'),
            (100, 'Voice Returning'),
            (30, 'First Repetition'),
            (10, 'First Chant'),
        ],
    },
    # The trigger word is `eyepushups`, with no leading `i`: the key is the word people type,
    # and detect() matches on it as it matches every other. It is a set of eye exercises --
    # moving the eyes left and right, focusing on something distant -- done for a few minutes,
    # so it is logged in minutes, unlike `ipushup`, which counts reps. The two are separate.
    "EYEPUSHUPS": {
        "name": 'Eye Pushups',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'eyepushups_users',
        # Only the extractor reads these, to match a message to the activity. Nobody sees them.
        "synonyms": ('eye pushups, eye pushup, eye push-ups, eye push ups, eyepushups, '
                     'eye exercise, eye exercises, eye yoga, eye movements'),
        "family": 'stillness',
        "tone": (  # added
            'Calm and unhurried, close to the yoga voice. Celebrate giving the eyes a few '
            'minutes of movement and rest, not volume or intensity. Keep it light and plain, '
            'never clinical and never medical advice. '
        ),
        # Cumulative minutes. Sized for about three minutes a day: the first rung is a week
        # or so in, and the top one is seven years of it.
        "tiers": [  # 10 rungs, highest first -- minutes
            (8000, 'Clear Sight'),
            (4000, 'The Long View'),
            (2000, 'Far Horizon'),
            (1000, 'Steady Gaze'),
            (600, 'Sharp Focus'),
            (300, 'Easy Focus'),
            (150, 'Soft Gaze'),
            (75, 'Near and Far'),
            (30, 'Left and Right'),
            (10, 'First Focus'),
        ],
    },
    "IHYDRATE": {
        "name": 'Hydration',
        "unit_singular": 'glass',
        "unit_plural": 'glasses',
        "row_type": 'hydrate_users',
        "synonyms": 'hydrate, water, drank water, glasses of water',
        "family": 'habit',
        "tone": (  # added
            'Light, warm, faintly amused at how mundane it is. Frame as basic '
            'self-maintenance done well. No hype, no records. '
        ),
        "tiers": [],   # no ladder defined -- tier stays "none"
    },
    "ISLEEP": {
        "name": 'Sleep',
        "unit_singular": 'hour',
        "unit_plural": 'hours',
        "row_type": 'sleep_users',
        "synonyms": 'sleep, slept, sleeping, hours of sleep',
        "family": 'habit',
        "tone": (  # added
            'Calm and reassuring. Celebrate rest as real recovery work, never as '
            'laziness or as a number to beat. Never imply more hours is better. '
        ),
        "tiers": [],   # no ladder defined -- tier stays "none"
    },
    "ILEARN": {
        "name": 'Learning',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'learn_users',
        "synonyms": 'learn, learning, learned, studied, studying',
        "family": 'habit',
        "tone": (  # added
            'Curious and encouraging. Celebrate showing up to learn, not the subject or '
            'the duration. '
        ),
        "tiers": [],   # no ladder defined -- tier stays "none"
    },
    "ISKETCH": {
        "name": 'Sketching',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'sketch_users',
        "synonyms": 'sketch, sketching, sketched, drawing, drew, doodle, doodling, doodled',
        "family": 'stillness',
        "tone": (  # added
            'Quiet and encouraging, focused on the practice of putting pencil to paper. '
            'Celebrate the minutes spent drawing, never the subject chosen or whether the '
            'sketch came out well. A rushed five minutes counts exactly as much as a '
            'careful hour. '
        ),
        "tiers": [  # 10 rungs, highest first -- minutes, same scale as journaling
            (20000, 'Master of Line'),
            (10000, 'The Illustrator'),
            (5000, 'Line Unbroken'),
            (2500, 'Deep Practice'),
            (1500, 'Steady Hand'),
            (500, 'Daily Lines'),
            (200, 'Finding the Line'),
            (100, 'Sketch Regular'),
            (30, 'Warming the Hand'),
            (10, 'First Lines'),
        ],
    },
    "IPAINT": {
        "name": 'Painting',
        "unit_singular": 'minute',
        "unit_plural": 'minutes',
        "row_type": 'paint_users',
        "synonyms": 'paint, painting, painted, watercolour, watercolor, acrylics, oils, gouache',
        "family": 'stillness',
        "tone": (  # added
            'Warm and unhurried. Celebrate the time spent painting as evidence they '
            'showed up to the easel, never the result on the canvas or the medium used. '
            'Ten minutes and two hours are both a win. '
        ),
        "tiers": [  # 10 rungs, highest first -- minutes, same scale as journaling
            (20000, 'The Master'),
            (10000, 'The Painter'),
            (5000, 'Canvas Unbroken'),
            (2500, 'Deep Colour'),
            (1500, 'Steady Brush'),
            (500, 'Daily Canvas'),
            (200, 'Finding the Palette'),
            (100, 'Studio Regular'),
            (30, 'Warming the Brush'),
            (10, 'First Strokes'),
        ],
    },
    "IFAST": {
        "name": 'Fasting',
        "unit_singular": 'hour',
        "unit_plural": 'hours',
        "row_type": 'fast_users',
        "synonyms": ('fast, fasting, fasted, intermittent fasting, '
                     'eating window, fasting window, 16:8, 18:6'),
        "family": 'habit',
        "tone": (  # non-competitive, same register as sleep
            'Calm and reassuring, never competitive. Celebrate keeping an eating '
            'window as real self-care, not as a number to beat. Every window gets '
            'the same calm respect regardless of length -- a 13-hour fast and an '
            '18-hour fast are both fine, ordinary wins. No PR or record language, '
            'no theatrical framing, even for a channel record or a tier crossing. '
            'Never frame it around hunger or willpower, never imply a longer '
            'window is better, never nudge anyone to fast longer, and never give '
            'dietary or medical advice. '
        ),
        "tiers": [  # 10 rungs, highest first -- hours, cumulative consistency
            (20000, 'Effortless Rhythm'),
            (10000, 'The Practiced'),
            (5000, 'Locked Rhythm'),
            (2500, 'Deep Routine'),
            (1500, 'Steady Window'),
            (500, 'Clockwork'),
            (200, 'Finding the Rhythm'),
            (100, 'Window Keeper'),
            (48, 'Settling In'),
            (12, 'First Window'),
        ],
    },
    "ICOLDSHOWER": {
        "name": 'Cold Shower',
        "unit_singular": 'shower',
        "unit_plural": 'showers',
        "row_type": 'cold_shower_users',
        "synonyms": ('cold shower, cold showers, icy shower, ice shower, '
                     'cold rinse, cold shower challenge'),
        "family": 'habit',
        "tone": (
            'Calm and matter-of-fact, never competitive. Celebrate stepping '
            'into the cold as a small act of discipline, not toughness or an '
            'extreme feat. This only tracks that they did it, never how long '
            'it lasted -- every shower gets the same steady respect. No PR or '
            'record language, no theatrical framing, even for a channel '
            'record or a tier crossing. Never dare anyone to go colder or '
            'longer, and never give health or medical advice about cold '
            'exposure. '
        ),
        "tiers": [  # 10 rungs, highest first -- a count of showers, not a duration
            (1000, 'Absolute Zero'),
            (500, 'Ice Discipline'),
            (250, 'Deep Freeze'),
            (100, 'Frost Forged'),
            (50, 'Steady Chill'),
            (25, 'Cold Regular'),
            (10, 'Finding the Cold'),
            (5, 'Warming to It'),
            (3, 'First Week'),
            (1, 'First Plunge'),
        ],
    },
}


# How a tier is decided.
#   "cumulative"  tier reflects lifetime total -- monotonic, only ever climbs.
#   "per_post"    tier reflects this single post -- what the recipe does today,
#                 which makes tiers bounce and re-fires tier-up celebrations.
TIER_BASIS = "cumulative"

NO_TIER = "none"          # activities with no ladder
UNRANKED = "Not Started"  # below the lowest rung

# outcome -> how the message should open. The composer turns this into prose;
# it replaces the 12-branch Response Types skill.
SCENARIOS = {
    "first_timer": {
        "lead": "welcome someone logging this for the very first time",
        "brief": "This is their first ever {name} log. Welcome them properly "
                 "and make them want to come back tomorrow. Use identity "
                 "language -- they are a {name} doer now -- and mention that "
                 "logging again tomorrow starts a streak. The number does not "
                 "matter at all here: one second and ten minutes get exactly "
                 "the same welcome. Never call it a record or a personal best; "
                 "there was nothing to beat yet.",
    },
    "milestone": {
        "lead": "celebrate a streak milestone",
        "brief": "Day {current_streak} in a row. Make it feel earned. "
                 "Loss-aversion language like 'protect it'.",
    },
    "tier_up": {
        "lead": "note a new tier reached",
        "brief": "Their running total crossed into {new_tier}, up from "
                 "{previous_tier}. This came from everything they have logged "
                 "adding up over time, NOT from today being exceptional. "
                 "Mention the tier warmly and briefly. Never call this session "
                 "heroic or record-breaking unless the session numbers say so.",
    },
    "tier_up_with_milestone": {
        "lead": "note a tier alongside a streak milestone",
        "brief": "One message, not two. The streak leads -- day "
                 "{current_streak} is the earned thing. {new_tier} is mentioned "
                 "inside as their running total crossing a line, not as a feat "
                 "of today.",
    },
    "freeze_used": {
        "lead": "a streak freeze was spent",
        "brief": "Their streak survived a missed day. Warm, a little dramatic, "
                 "make them feel clever for having the credit banked.",
    },
    "comeback": {
        "lead": "welcome someone back after a gap",
        "brief": "They were away {days_since_last_log} day(s) -- that is the "
                 "real, computed number; use it exactly or not at all, never "
                 "round it or estimate a different one. No shame about the "
                 "reset, none at all. Celebrate the return only.",
    },
    "double_down": {
        "lead": "react to a second log today",
        "brief": "Genuine shock and hype that someone is this committed. "
                 "Playful. One or two lines.",
    },
    "beast_mode": {
        "lead": "react to {daily_post_count} logs today",
        "brief": "Pure beast mode. Escalate the hype with the count.",
    },
    "continuing": {
        "lead": "acknowledge an extended streak",
        "brief": "Day {current_streak}. Short, encouraging, vary the phrasing.",
    },
    "golden": {
        "lead": "announce a rare Golden log",
        "brief": "Lands roughly 1 in 17 posts. Make it feel genuinely "
                 "surprising, like they won something real.",
    },
    "backfill": {
        "lead": "acknowledge a day filled in after the fact",
        "brief": "They caught up on a day they missed logging. Warm and "
                 "matter-of-fact. Their streak is untouched -- do not imply "
                 "otherwise.",
    },
    "duplicate": {"lead": "", "brief": ""},   # never posted
}

# Asked when the trigger is present but no number is. The reply is threaded so
# it does not clutter the channel. Nothing writes to the table until a number
# arrives.
ASK_TEMPLATES = {
    "strength": (
        "Hey <@{user}> — got the {name}. How many {unit}? "
        "Drop the number with `{keyword}` and I'll log it. :muscle:",
        "<@{user}> saw the {name}. Give me the {unit} and it's on the board — "
        "just repost with `{keyword}` and the count.",
        "Logged the intent, <@{user}> :memo: — how many {unit}? "
        "Say it with `{keyword}` and I'll get it down.",
    ),
    "endurance": (
        "Hey <@{user}> — got the {name}. How many {unit}? "
        "Repost with `{keyword}` and the number and I'll log it.",
        "<@{user}> saw the {name}. Send the {unit} with `{keyword}` and I'll "
        "put it down.",
        "Got the intent, <@{user}> — how many {unit} for the {name}? "
        "Use `{keyword}` with the count.",
    ),
    "habit": (
        "Hey <@{user}> — got the {name}. How many {unit}? "
        "Repost with `{keyword}` and the number and I'll log it.",
        "<@{user}> saw the {name}. Send the {unit} with `{keyword}` and I'll "
        "put it down.",
        "Got the intent, <@{user}> — how many {unit}? Use `{keyword}` with the "
        "count.",
    ),
    "stillness": (
        "Got the {name}, <@{user}>. How many {unit}? "
        "Repost with `{keyword}` and the number and I'll log it. :memo:",
        "<@{user}> I saw the {name}. Send the {unit} with `{keyword}` and I'll "
        "put it down quietly.",
        "Noted the intent, <@{user}> — how many {unit}? "
        "Use `{keyword}` with the count.",
    ),
}


# Activities done in bursts, where one unbroken effort is a separate feat from
# the day's volume. Planks belong here: people log "3 sets 50 seconds each", and
# a 200-second hold is harder than 200 seconds split four ways.
SET_BASED = {"IPUSHUP", "IPULLUP", "ISQUAT", "IPLANKED"}

# What one burst is called. A plank has holds, not sets.
SET_NOUN = {"IPLANKED": "hold"}

# Activities logged as a single occurrence rather than a counted amount -- the
# trigger itself is the whole log, so every post adds exactly one regardless of
# any number in the text. No count is ever asked for, and the extractor is
# never called for these keywords. Someone can still log more than once a
# day; each post still adds its own 1, the same as any other activity's
# same-day posts add together.
FIXED_COUNT = {"ICOLDSHOWER": 1}

# What is and is not a log. A log is a trigger word and a number, a line or two. Anything
# much longer is somebody pasting a document, or a conversation, that happens to contain a
# trigger word -- and the extractor will happily find a number in it and add it to their
# total, to the channel's total, and to the Great Walk. Such a message is left alone, with
# a short note saying why.
MAX_LOG_CHARS = 600

# ... except a list: somebody catching up on three weeks posts one short line per day, each
# with its date and a number. That is a log however many lines it runs to, so a message made
# only of such lines is allowed up to this many, and this many characters. A pasted document
# has long lines, or lines with no number in them, and still stops at MAX_LOG_CHARS.
MAX_LOG_LINES = 40
MAX_LOG_LIST_CHARS = 3000
MAX_LOG_LINE_CHARS = 80


def too_long_for_a_log(text):
    """Whether a message carrying a trigger word is too long to be read as a log."""
    text = str(text or "")
    if len(text) <= MAX_LOG_CHARS:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    is_list = (len(text) <= MAX_LOG_LIST_CHARS and len(lines) <= MAX_LOG_LINES
               and all(len(line) <= MAX_LOG_LINE_CHARS and re.search(r"\d", line)
                       for line in lines))
    return not is_list


# The most one day of an activity can plausibly add up to, in the activity's own unit
# (steps, reps, seconds of plank, minutes, pages, glasses, hours). It is not a target and
# nobody should meet it: it is the line past which a figure is a slip of the keyboard or
# a number read out of the wrong place, and is refused rather than written into a total
# that every record, ladder and milestone is then measured against. Unlisted timed
# activities get a full day of minutes; unlisted counted ones DEFAULT_MAX_PER_DAY.
MAX_PER_DAY = {
    "ISTEPS": 200000, "ISTAIRS": 1500,
    "IPUSHUP": 3000, "IPULLUP": 1500, "ISQUAT": 5000,
    "IPLANKED": 6 * 3600,                       # seconds
    "IREAD": 1000, "IWRITE": 300, "IHYDRATE": 50, "ISLEEP": 24, "IFAST": 168,
}
DEFAULT_MAX_PER_DAY = 100000

# Beating everyone necessarily beats your own previous best, so listing the
# personal record alongside the channel one says nothing.
IMPLIED_BY = {"channel_day": {"personal_day"}, "channel_set": {"personal_set"}}


# The four record types, in the order the old `heading` variable ranked them.
RECORD_KINDS = ("channel_day", "channel_set", "personal_day", "personal_set")

# For rep activities the single set leads. 200 pushups in one go is a harder
# thing than 200 spread over twenty sets, so when both fall the set is the
# headline and the day total follows it.
SET_FIRST_KINDS = ("channel_set", "channel_day", "personal_set", "personal_day")


def record_order(keyword):
    return SET_FIRST_KINDS if keyword in SET_BASED else RECORD_KINDS
def record_label(kind, keyword=None):
    """Wording for a record, in the activity's own vocabulary."""
    label = RECORD_LABEL[kind]
    if kind.endswith("set") and keyword in SET_NOUN:
        label = label.replace("single set", "single " + SET_NOUN[keyword])
    return label


RECORD_LABEL = {
    "channel_day": "channel record for a single day",
    "channel_set": "channel record for a single set",
    "personal_day": "personal best for a single day",
    "personal_set": "personal best for a single set",
}

# Stillness activities get their records noted, not announced. A trophy and a
# margin turn sitting quietly into a scoreboard, which is the opposite of the
# point. These use their own wording, their own icon, and no comparison.
QUIET_VERB = {
    "IMEDITATE": ("sat in silence for", "sit"),
    "IYOGA": ("was on the mat for", "practice"),
    "ISOLITUDE": ("took", "stretch of quiet"),
    "IPRAYANAM": ("did pranayama for", "session"),
    "ICHANT": ("chanted for", "chant"),
    "EYEPUSHUPS": ("did eye pushups for", "session"),
    "IJOURNAL": ("wrote for", "sitting"),
    "IWRITE": ("wrote", "draft"),
    "ISKETCH": ("sketched for", "sketch"),
    "IPAINT": ("painted for", "session"),
}
QUIET_ICON = ":lotus:"

# Banner shown above a channel-record announcement. Either a URL or a Slack
# file id (Fxxxxxxxx).
#
# A workspace file URL is fine here: image blocks render in the Slack client,
# where the viewer is already signed in, so channel members see it. Swap in the
# file id form, or a public URL, if it ever stops resolving.
RECORD_BANNER = ("https://coursera.enterprise.slack.com/files/U038ZCDAY6P/"
                 "F0BT1FETK4K/chatgpt_image_aug_28__2026__12_32_45_am.png")
RECORD_BANNER_ALT = "New channel record"

# Banner shown above a challenge-answered announcement -- a separate event
# from a channel record, so it gets its own image rather than borrowing the
# record one. Overridable per-run via the "challenge_banner" recipe input;
# this is only the fallback when that input is left blank. Same URL / Slack
# file id rules as RECORD_BANNER.
CHALLENGE_BANNER = RECORD_BANNER
CHALLENGE_BANNER_ALT = "Challenge answered"

# Every channel record gets the banner, stillness included -- the record is the
# same event whatever the activity. Only the wording changes: no trophy, no
# margin, no headcount for a sit or a practice.
BANNER_ON_QUIET = True



# --------------------------------------------------------------------------
# Pure helpers -- no I/O below this line until the EDGES section
# --------------------------------------------------------------------------

def local_now(tz_offset, now_utc=None):
    """The poster's wall-clock time, from Slack's tz_offset in seconds."""
    now_utc = now_utc or datetime.utcnow()
    try:
        offset = int(tz_offset)
    except (TypeError, ValueError):
        offset = DEFAULT_TZ_OFFSET
    return now_utc + timedelta(seconds=offset)


def local_today(tz_offset, now_utc=None):
    """The poster's local date -- the only date this code should ever store."""
    return local_now(tz_offset, now_utc).date()


def part_of_day(tz_offset, now_utc=None):
    """So the message never wishes someone good morning at 11pm."""
    hour = local_now(tz_offset, now_utc).hour
    if hour < 5:
        return "late night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "night"


def as_date(value):
    """Parse whatever the table hands back into a date, or None."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text[:len(fmt) + 6], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


MONTH_NAMES = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_ORDINAL = re.compile(r"\b(\d{1,2})(st|nd|rd|th)\b")
_MONTHS_PATTERN = "|".join(MONTH_NAMES)
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})\s+(?:of\s+)?(" + _MONTHS_PATTERN + r")\b(?:\s*,?\s*(\d{4}))?")
_MONTH_DAY = re.compile(
    r"\b(" + _MONTHS_PATTERN + r")\s+(\d{1,2})\b(?:\s*,?\s*(\d{4}))?")


def parse_written_date(text, today):
    """"31st August", "August 31", "Aug 31, 2026" -> a real date, or None.

    as_date() only reads ISO, because it also parses dates already stored in
    the table -- values we wrote ourselves and never need to guess about. This
    is for the other direction: a date a PERSON typed. The extraction prompt
    tells the model to hand back 'today', 'yesterday', a weekday, or an ISO
    date, but a written calendar date does not fit any of those, so the model
    reports it as seen and it lands here.

    No year given means find the one that does not put the date in the
    future: "December 31" said in January means last December, not next.
    """
    cleaned = _ORDINAL.sub(r"\1", str(text or "").strip().lower().replace(".", " "))
    match = _DAY_MONTH.search(cleaned) or _MONTH_DAY.search(cleaned)
    if not match:
        return None
    groups = match.groups()
    if groups[0].isdigit():
        day_num, month_name, year = groups
    else:
        month_name, day_num, year = groups
    month_num = MONTH_NAMES.get(month_name)
    if not month_num:
        return None
    try:
        day_num = int(day_num)
    except ValueError:
        return None

    if year:
        try:
            return date(int(year), month_num, day_num)
        except ValueError:
            return None
    for candidate_year in (today.year, today.year - 1):
        try:
            candidate = date(candidate_year, month_num, day_num)
        except ValueError:
            continue
        if candidate <= today:
            return candidate
    return None


# Reference Saturday and Sunday used to count weekends in a span. Any Saturday
# and any Sunday would do; these match the recipe so the arithmetic is identical.
_SAT_EPOCH = date(2024, 1, 6)
_SUN_EPOCH = date(2024, 1, 7)


def business_day_gap(last_updated, today):
    """Days since the last log, not counting weekends.

    Ported from the recipe's day_gap formula. Two rules matter and both are
    deliberate: a post made ON a weekend always reports 0, so weekends can
    neither break a streak nor advance one; and weekend days inside a span are
    subtracted, so Friday to Monday is 1, not 3.
    """
    if today.weekday() in (5, 6):          # Saturday or Sunday
        return 0
    last = as_date(last_updated)
    if last is None:
        return 0

    raw = (today - last).days
    saturdays = ((today - _SAT_EPOCH).days // 7) - ((last - _SAT_EPOCH).days // 7)
    sundays = ((today - _SUN_EPOCH).days // 7) - ((last - _SUN_EPOCH).days // 7)
    return raw - saturdays - sundays


# Words that clearly point forwards. Anything else unrecognised falls back to
# today, which is the friendly reading of "this morning" or "earlier" -- but
# "tomorrow" must not quietly become today.
# Values that mean "no day was mentioned", which is genuinely today. Anything
# else unparseable is refused instead of being assumed to be today.
NO_DAY_STATED = ("today", "now", "just now", "n/a", "na", "none", "null",
                 "unspecified", "unknown", "-")

FUTURE_WORDS = ("tomorrow", "tomorow", "tmrw", "tmr", "next week",
                "next month", "next monday", "next tuesday", "next wednesday",
                "next thursday", "next friday", "next saturday", "next sunday")

WEEKDAY_NAMES = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
                 "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thur": 3,
                 "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
                 "sunday": 6, "sun": 6}


# A part of the day people put on a day: "yesterday evening", "monday night", "this morning".
# Only the day is stored, so the part is dropped -- except where it changes the day itself:
# "last night" is yesterday, and "tonight" or "this morning" is today.
_PART_OF_DAY = r"(?:early |late )?(?:in the )?(?:morning|afternoon|evening|eve|night|nite|noon)"
_CLOCK_TIME = r"(?:at )?\d{1,2}(?::\d{2})?\s*(?:am|pm)|at \d{1,2}(?::\d{2})?"
_TODAY_PHRASES = re.compile(
    r"(?:early |late )?(?:tonight|tonite|earlier(?: today)?|today(?: " + _PART_OF_DAY
    + r")?|this (?:" + _PART_OF_DAY + r"|am|pm)|" + _PART_OF_DAY + r"|" + _CLOCK_TIME + r")")
_LAST_NIGHT = re.compile(r"(?:late |early )?(?:last|yesterday) ?(?:night|nite|evening|eve)")
_NIGHT_BEFORE_LAST = re.compile(r"(?:the )?(?:night|evening) before last")
_TRAILING_PART = re.compile(r"\s+(?:" + _PART_OF_DAY + r"|" + _CLOCK_TIME + r")$")


def day_words(text):
    """The day a phrase names, with any part of the day or clock time taken off.

    "last night" -> "yesterday", "this morning" -> "today", "yesterday evening" ->
    "yesterday", "last friday night" -> "last friday", "monday 7am" -> "monday".
    Anything else comes back as it was, for resolve_day to read.
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if _NIGHT_BEFORE_LAST.fullmatch(text):
        return "2 days ago"
    if _LAST_NIGHT.fullmatch(text):
        return "yesterday"
    for _ in range(3):                    # "this morning", then "yesterday late evening at 9pm"
        if _TODAY_PHRASES.fullmatch(text):
            return "today"
        text = _TRAILING_PART.sub("", text)
    return text


def resolve_day(word, today):
    """Turn whatever the extractor reported into a real date, or None.

    Accepts an ISO date, "today"/"yesterday", or a weekday name meaning the most
    recent one that has already happened, each with or without a part of the day
    ("last night", "yesterday morning", "monday evening" -- see day_words). Anything
    in the future is refused rather than guessed at -- resolving dates is
    arithmetic, not something to leave to the model.
    """
    text = str(word or "").strip().lower()
    if any(w in text for w in FUTURE_WORDS):
        return None
    text = day_words(text)
    if not text or text in NO_DAY_STATED:
        return today

    # "last friday", "this monday", "on tuesday" all mean the weekday. Without
    # this only a bare weekday matched, and everything else fell through to
    # today -- filing a back-dated log on the wrong day, silently.
    previous_one = False
    for prefix in ("last ", "this ", "past ", "on ", "since "):
        if text.startswith(prefix):
            previous_one = prefix in ("last ", "past ")
            text = text[len(prefix):].strip()
            break

    if text in ("yesterday", "yday"):
        candidate = today - timedelta(days=1)
    elif text in ("day before yesterday", "the day before yesterday",
                  "two days ago", "2 days ago"):
        candidate = today - timedelta(days=2)
    elif text in ("a week ago", "one week ago", "1 week ago"):
        candidate = today - timedelta(days=7)
    elif text.endswith(" days ago") or text.endswith(" day ago"):
        # "5 days ago" and "five days ago" both need reading: spelled_number
        # only tokenises letters, so a bare digit has to be tried first.
        stem = text.rsplit(" ", 2)[0]
        digits = re.search(r"\d+", stem)
        n_days = int(digits.group()) if digits else spelled_number(stem)
        if n_days > 0:
            candidate = today - timedelta(days=n_days)
        else:
            return None
    elif text in WEEKDAY_NAMES:
        target = WEEKDAY_NAMES[text]
        back = (today.weekday() - target) % 7
        # A bare weekday means the most recent one, which today satisfies. But
        # "last friday" said on a Friday means the Friday before this one.
        if back == 0 and previous_one:
            back = 7
        candidate = today - timedelta(days=back)
    else:
        candidate = as_date(text) or parse_written_date(text, today)
        if candidate is None:
            # Refuse rather than assume today. A day we cannot read is a day we
            # do not know, and quietly logging it as today writes wrong history.
            return None

    if candidate > today:
        return None
    return candidate


DATE_FALLBACK_SYSTEM = (
    "You convert a date a person wrote in a Slack message into an ISO date. "
    "You return JSON only, shaped {\"date\": \"YYYY-MM-DD\"}. The caller tells you "
    "today's date and weekday; use them for anything relative or missing a "
    "year. With no year given, pick the most recent such date that is not in "
    "the future. A part of the day only names its day: 'last night' is yesterday, "
    "'this morning' and 'tonight' are today, 'friday evening' is that Friday. "
    "If the text is not a single past-or-present calendar date, "
    "or you are not sure, return {\"date\": null}. Never guess."
)


def resolve_day_with_llm(llm, word, today):
    """Backup for resolve_day: ask the model to read a date the parser could not.

    The parser is exact but only knows the phrasings it was taught; people write
    "16th of October", "the 3rd of last month", "Oct. 16th". The model reads
    those, but its answer is only ever accepted as an ISO date that is not in
    the future -- the same bar every other date has to clear.
    """
    if llm is None or not str(word or "").strip():
        return None
    user = ("Today is {} ({}).\nDate as written: {}\n"
            "Return JSON: {{\"date\": \"YYYY-MM-DD\" or null}}".format(
                today.isoformat(), today.strftime("%A"), word))
    reply = llm.chat(DATE_FALLBACK_SYSTEM, user, json_mode=True,
                     temperature=0, max_tokens=60)
    if not reply:
        return None
    try:
        answer = json.loads(reply).get("date")
    except (ValueError, AttributeError):
        return None
    candidate = as_date(answer) if answer else None
    if candidate is None or candidate > today:
        return None
    return candidate


def tier_for(keyword, value):
    """Tier name for a value on this activity's ladder."""
    ladder = ACTIVITIES.get(keyword, {}).get("tiers") or []
    if not ladder:
        return NO_TIER
    for threshold, name in ladder:
        if int(value or 0) >= threshold:
            return name
    return UNRANKED


def stored_sessions(row):
    """The whole session list of a row, joined from every column it is spread over.

    Returns (text, parts): `parts` is how many columns held any of it, which the next write
    needs in order to clear a column it no longer fills. A row that only ever used `total`
    comes back exactly as it was stored.
    """
    pieces = [str(row.get(column) or "") for column in TOTAL_COLUMNS]
    held = [i for i, piece in enumerate(pieces) if piece.strip()]
    if not held:
        return str(row.get("total") or ""), 1
    return ",".join(pieces[i] for i in held), held[-1] + 1


def split_sessions(text, chunk=COLUMN_CHUNK, columns=len(TOTAL_COLUMNS)):
    """The session list cut for storage: (pieces, dropped).

    Cut only at commas, so a number is never split, and the separating comma is dropped
    from the pieces because stored_sessions puts it back: ",".join(pieces) == text exactly.
    If the list cannot fit even across every column, the OLDEST sessions are dropped (and
    counted) rather than the write being refused, which would lose the newest one.
    """
    text = str(text or "")
    dropped = 0
    while True:
        pieces, rest = [], text
        while len(rest) > chunk:
            cut = rest.rfind(",", 0, chunk + 1)
            if cut <= 0:
                cut = chunk                       # one token longer than a column: cannot happen
            pieces.append(rest[:cut])
            rest = rest[cut + 1:]
        pieces.append(rest)
        if len(pieces) <= columns:
            return pieces, dropped
        head, _, text = text.partition(",")       # too long even for every column: drop the oldest
        dropped += 1


def split_numbers(value):
    """'40,28,45' -> [40.0, 28.0, 45.0]"""
    out = []
    for part in str(value or "").split(","):
        try:
            out.append(float(part.strip()))
        except ValueError:
            pass
    return out


def split_dates(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def unique_days(blob):
    """The distinct dates in a heatmap column."""
    seen = []
    for part in str(blob or "").split(","):
        part = part.strip()
        if part and part not in seen:
            seen.append(part)
    return seen


def append_day(existing, day):
    """Add today to a comma-separated date list, once, keeping the tail."""
    days = split_dates(existing)
    iso = day.isoformat()
    if iso in days:
        return ",".join(days)
    return ",".join((days + [iso])[-HEATMAP_KEEP_DAYS:])


def tidy(number):
    return int(number) if float(number).is_integer() else round(float(number), 2)


def steps_km_text(steps):
    """'146,607 steps' worth of distance, as '~111.7 km'."""
    km = int(steps or 0) / STEPS_PER_KM
    return "~{:,.1f} km".format(km)


# --------------------------------------------------------------------------
# The state machine. classify() decides what happened; next_row() decides what
# to write. Both are pure, so every branch is testable without Slack or Workato.
# --------------------------------------------------------------------------

def is_golden(row, message_ts, today):
    """Rare recognition: roughly 6 posts in 100, never twice inside a week.

    The 6-in-100 comes from the last two digits of the Slack timestamp, which
    is effectively random. Ported unchanged.
    """
    try:
        if int(str(message_ts)[-2:]) >= GOLDEN_TS_CUTOFF:
            return False
    except (ValueError, TypeError):
        return False
    last = as_date((row or {}).get("last_golden_date"))
    if last is None:
        return True
    return (today - last).days >= GOLDEN_COOLDOWN_DAYS


# Tiers that have been renamed, old name -> current name. A row keeps the tier it was last
# written with, and a different name reads as a tier change, so without this a rename would
# congratulate, and credit, everyone on a tier they already hold. The row is written back with
# the current name the next time it is logged.
RENAMED_TIERS = {
    "First Breath": "First Pause",
    "Steady Breath": "Steady Practice",
    "Breath Keeper": "Prana Keeper",
}


def classify(row, count, message_ts, today, new_tier):
    """What kind of event is this post?

    Returns a dict, never raises. `row` is None or {} for a first-timer.
    """
    prior_tier = str((row or {}).get("plank_tier") or "")
    prior_tier = RENAMED_TIERS.get(prior_tier, prior_tier)
    tier_changed = bool(row) and prior_tier != str(new_tier)

    if row and str(row.get("last_processed_ts") or "") == str(message_ts):
        return {
            "outcome": "duplicate", "gap": None, "tier_changed": False,
            "golden": False, "streak": int(row.get("current_streak") or 0),
            "daily_count": int(row.get("daily_post_count") or 0),
            "previous_tier": prior_tier,
        }

    if not row:
        return {
            "outcome": "first_timer", "gap": None, "tier_changed": True,
            "golden": False, "streak": 1, "daily_count": 1, "previous_tier": "",
        }

    streak = int(row.get("current_streak") or 0)
    daily = int(row.get("daily_post_count") or 0)
    credits = int(row.get("freeze_credits") or 0)
    heatmap = split_dates(row.get("heatmap_dates"))
    # The most recent date actually posted -- NOT row["updated_at"], which is
    # deliberately left untouched by a weekend post (so weekends can't move a
    # streak) and would otherwise make a second Saturday post look like it
    # follows Friday instead of the Saturday post right before it.
    #
    # The LATEST date in the list, not its last entry: append_day adds a
    # back-filled day at the end, so after "today, then Monday" the last entry
    # is Monday -- and a second post today was then read as history being
    # filled in rather than a second log of the day.
    logged_days = [d for d in (as_date(x) for x in heatmap) if d]
    last_day = max(logged_days) if logged_days else None

    # "Posted again today" has to be judged on the calendar date itself, not
    # on business_day_gap -- that function deliberately reports 0 for ANY
    # weekend post, last update or no, purely so weekends can't move a
    # streak. Reusing it here mistook a person's first Saturday post of the
    # week for a second log, because their last update (Friday) made the raw
    # gap moot. today.isoformat() already lands in heatmap_dates from every
    # single post regardless of weekday, so it is the one honest signal for
    # "this exact date has been logged before".
    already_logged = today.isoformat() in heatmap

    if already_logged:
        if last_day is not None and today == last_day:
            # A genuine repeat of the day just posted. Streak does not move;
            # the count of posts does. Golden is never awarded on a repeat.
            nth = daily + 1
            outcome = ("double_down" if nth == 2 else
                       "beast_mode" if nth >= 3 else "continuing")
            return {"outcome": outcome, "gap": 0, "tier_changed": tier_changed,
                    "golden": False, "streak": streak, "daily_count": nth,
                    "previous_tier": prior_tier}
        # Logged before, but not the most recent day -- filling in history.
        # Earns the volume and the session credit but must not disturb a
        # streak that has already moved past it.
        return {"outcome": "backfill", "gap": -1, "tier_changed": tier_changed,
                "golden": False, "streak": streak, "daily_count": daily,
                "previous_tier": prior_tier}

    if last_day is not None and today < last_day:
        # An earlier day than the last update, never logged before -- also
        # history being filled in. Plain date comparison, not the
        # weekend-distorted gap, since a never-seen Saturday from three
        # weeks ago is still the past regardless of what day it falls on.
        return {"outcome": "backfill", "gap": -1, "tier_changed": tier_changed,
                "golden": False, "streak": streak, "daily_count": daily,
                "previous_tier": prior_tier}

    golden = is_golden(row, message_ts, today)
    gap = business_day_gap(row.get("updated_at"), today)

    if gap == 0:
        # A genuinely new day that happens to land on a weekend -- the
        # streak neither advances nor breaks, but it is still that day's
        # first post, not a repeat of the last one.
        return {"outcome": "continuing", "gap": 0, "tier_changed": tier_changed,
                "golden": golden, "streak": streak, "daily_count": 1,
                "previous_tier": prior_tier}

    if gap == 1:
        nxt = streak + 1
        outcome = "milestone" if nxt in STREAK_MILESTONES else "continuing"
        return {"outcome": outcome, "gap": 1, "tier_changed": tier_changed,
                "golden": golden, "streak": nxt, "daily_count": 1,
                "previous_tier": prior_tier}

    if gap == 2 and credits > 0:
        return {"outcome": "freeze_used", "gap": 2, "tier_changed": tier_changed,
                "golden": golden, "streak": streak + 1, "daily_count": 1,
                "previous_tier": prior_tier}

    return {"outcome": "comeback", "gap": gap, "tier_changed": tier_changed,
            "golden": golden, "streak": 1, "daily_count": 1,
            "previous_tier": prior_tier}


def next_row(row, event, ctx):
    """The fields to write back, keyed by column name.

    ctx carries: keyword, row_type, user_id, user_name, count, max_of_this_set,
    new_tier, message_ts, today, source.
    """
    today = ctx["today"]
    count = int(ctx["count"] or 0)
    set_max = int(ctx["max_of_this_set"] or 0)
    outcome = event["outcome"]

    # A freeze credit is granted on a tier change. Kept as the recipe had it:
    # this assigns rather than increments, so credits are a flag, not a bank.
    credits = 1 if event["tier_changed"] else 0

    fields = {
        "record_key": "{}_{}".format(ctx["row_type"], ctx["user_id"]),
        "row_type": ctx["row_type"],
        "id": ctx["user_id"],
        "name": ctx["user_name"],
        "last_processed_ts": str(ctx["message_ts"]),
        "plank_tier": ctx["new_tier"],
        "freeze_credits": credits,
        "current_value": count,
        "max_of_this_set": set_max,
        "daily_post_count": event["daily_count"],
        "current_streak": event["streak"],
    }

    if not row:                                    # first-timer
        fields.update({
            "first_seen": today.isoformat(),
            "updated_at": today.isoformat(),
            "longest_streak": 1,
            "total_planks": 1,
            "week_count": 1,
            "is_private": ctx.get("source") == "dm",
            "leaderboard_optout": False,
            "personal_best_single_set": set_max,
            "plank_duration": count,
            "heatmap_dates": today.isoformat(),
            "total": str(count),
            "direct_grant_count": count,
        })
        return fields

    prior_best_set = int(row.get("personal_best_single_set") or 0)
    prior_best_day = int(row.get("plank_duration") or 0)
    prior_total = row.get("total")
    prior_grant = int(row.get("direct_grant_count") or 0)

    # Multiple posts on the same calendar day are one day's effort, not
    # separate days -- 30 in the morning and 45 that evening is a 75 day, not
    # a fresh "best" of 45. current_value carries today's running total
    # forward between posts and resets the moment the date actually changes,
    # so plank_duration (the single-day record) is judged on the day's sum.
    same_day = as_date(row.get("updated_at")) == today
    day_total = (int(row.get("current_value") or 0) + count) if same_day else count

    fields.update({
        "total_planks": int(row.get("total_planks") or 0) + 1,
        "week_count": int(row.get("week_count") or 0) + 1,
        "personal_best_single_set": max(set_max, prior_best_set),
        "current_value": day_total,
        "plank_duration": max(day_total, prior_best_day),
        "heatmap_dates": append_day(row.get("heatmap_dates"), today),
        "total": ("{},{}".format(prior_total, count) if str(prior_total or "").strip()
                  else str(count)),
        "direct_grant_count": prior_grant + count,
    })

    if outcome == "backfill" or outcome in ("double_down", "beast_mode") \
            or event["gap"] == 0:
        # Same day, or an earlier one being filled in: the volume and the
        # session count move, the streak and updated_at do not.
        fields["longest_streak"] = int(row.get("longest_streak") or 0)
        fields["current_streak"] = int(row.get("current_streak") or 0)
        if outcome == "backfill":
            fields["daily_post_count"] = int(row.get("daily_post_count") or 0)
        return fields

    fields["updated_at"] = today.isoformat()
    fields["longest_streak"] = (int(row.get("longest_streak") or 0)
                                if outcome == "comeback"
                                else max(int(row.get("longest_streak") or 0), event["streak"]))

    if event["golden"]:
        fields["last_golden_date"] = today.isoformat()
        fields["golden_dates"] = append_day(row.get("golden_dates"), today)

    return fields


def fold_entries(row, entries, ctx):
    """Apply each day's entry in date order against an evolving row.

    A message can back-fill several days. Rather than special-casing that, each
    entry is run through the same pure state machine with its own date, and the
    row carries forward in memory. One write happens at the end, so the streak,
    the heatmap and the session count all land correctly.

    Returns (fields_to_write, events, working_row).
    """
    working = dict(row) if row else None
    fields, events = {}, []
    golden_spent = False

    for entry in sorted(entries, key=lambda e: e["day"]):
        day = entry["day"]
        count = int(entry["total"])
        set_max = int(entry["max_per_set"] or count)

        new_tier = tier_for(ctx["keyword"], tier_value(working, count))
        event = classify(working, count, ctx["message_ts"], day, new_tier)

        # Golden is a per-message reward, not a per-day one.
        if event["golden"] and golden_spent:
            event["golden"] = False
        golden_spent = golden_spent or event["golden"]

        step = dict(ctx)
        step.update({"count": count, "max_of_this_set": set_max,
                     "new_tier": new_tier, "today": day})
        written = next_row(working, event, step)

        fields.update(written)
        event["day"] = day.isoformat()
        event["count"] = count
        event["max_per_set"] = set_max
        event["new_tier"] = new_tier
        # written["current_value"] is that day's running total, this entry
        # combined with anything already logged for the same calendar date --
        # what a single-day record has to be judged against, not the raw
        # count from this one entry.
        event["day_total"] = int(written.get("current_value") or count)
        events.append(event)

        # Carry the row forward. last_processed_ts is cleared so the next entry
        # in the same message is not mistaken for a replay of this one.
        working = dict(working or {})
        working.update(written)
        working["last_processed_ts"] = ""

    return fields, events, working


def chase(standings, user_id, new_total):
    """The nearest person above them on volume, and the gap to pass them.

    For whoever is already on top there is nobody above, so the nearest person
    BELOW is reported instead -- being told who is closing in is the only thing
    left that can move a leader.

    When trailing someone, a second chaser closing in from below is also
    surfaced -- but only when they are genuinely close (see
    CLOSE_CHASE_RATIO), so a routine "X to pass" line doesn't turn into a full
    leaderboard every time someone happens to be behind.

    Returns None when nobody else plays or the standings are unavailable -- the
    caller then simply omits the nudge.
    """
    others = [e for e in (standings or []) if e["id"] != user_id]
    if not others:
        return None
    ahead = [e for e in others if e["total"] > new_total]
    if not ahead:
        behind = max(others, key=lambda e: e["total"])
        return {"leading": True, "name": behind["name"],
                "gap": new_total - behind["total"],
                "rank": 1, "people": len(others) + 1}
    target = min(ahead, key=lambda e: e["total"])
    result = {"leading": False, "name": target["name"],
              "gap": target["total"] - new_total + 1,
              "rank": len(ahead) + 1, "people": len(others) + 1}

    behind_rows = [e for e in others if e["total"] < new_total]
    if behind_rows and new_total > 0:
        chaser = max(behind_rows, key=lambda e: e["total"])
        chaser_gap = new_total - chaser["total"]
        if chaser_gap <= new_total * CLOSE_CHASE_RATIO:
            result["chaser_name"] = chaser["name"]
            result["chaser_gap"] = chaser_gap
    return result


def records_broken(own_row, channel_best, count, set_max, keyword=None, log=None):
    """Which records this post beat, and which of those are worth saying.

    Set records only apply to rep-based activities. A first log beats every
    record by definition, and a "channel record" among one participant is not a
    record; both are suppressed so the announcement stays meaningful.

    `count` is the day's total (everything logged that day) and is what a personal best
    is judged on. `log` is the biggest single log in the message and is what the channel
    day record is judged on, as on the leaderboard; it defaults to `count`.
    """
    own = own_row or {}
    log = count if log is None else log
    sets_apply = keyword in SET_BASED
    previous = {
        "channel_day": int(channel_best.get("day") or 0),
        "channel_set": int(channel_best.get("set") or 0),
        "personal_day": int(own.get("plank_duration") or 0),
        "personal_set": int(own.get("personal_best_single_set") or 0),
    }
    blank = {k: False for k in RECORD_KINDS}

    solo = int(channel_best.get("people") or 0) < 2

    if not own_row:
        # A first log beats every PERSONAL best by definition -- there was
        # nothing to beat -- so those are suppressed. Beating everyone else on
        # your first day is a different matter and still counts.
        first = {
            "channel_day": (not solo) and log > previous["channel_day"],
            "channel_set": (sets_apply and not solo
                            and set_max > previous["channel_set"]),
            "personal_day": False,
            "personal_set": False,
        }
        ordered = [k for k in record_order(keyword) if first[k]]
        return {"flags": first, "previous": previous,
                "headline": ordered[0] if ordered else None,
                "also": ordered[1:], "any": bool(ordered),
                "reason": "first log: personal bests withheld"}
    flags = {
        "channel_day": (not solo) and log > previous["channel_day"],
        "channel_set": sets_apply and (not solo) and set_max > previous["channel_set"],
        "personal_day": count > previous["personal_day"],
        "personal_set": sets_apply and set_max > previous["personal_set"],
    }

    broken = [k for k in record_order(keyword) if flags[k]]
    implied = set()
    for kind in broken:
        implied |= IMPLIED_BY.get(kind, set())
    notable = [k for k in broken if k not in implied]

    return {"flags": flags, "previous": previous,
            "headline": notable[0] if notable else None,
            "also": notable[1:], "any": bool(notable),
            "reason": "only participant, channel records withheld" if solo else ""}


# Slack subtypes that are not a person logging something. message_changed and
# message_deleted matter most: an edit re-fires the trigger with the same text,
# which would double-log if it were let through.
SKIP_SUBTYPES = {
    "bot_message", "message_changed", "message_deleted", "message_replied",
    "thread_broadcast", "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "channel_archive", "channel_unarchive",
    "file_share_reply", "tombstone", "reminder_add",
}


def should_process(event):
    """Whether this Slack event deserves any work at all.

    The trigger fires on every message in the channel, including Spotter's own.
    Spotter's replies mention trigger words on purpose -- "repost with
    `iplanked`" -- so without this guard it would answer itself in a loop.
    Returns (ok, reason).
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


# Other trigger words that log to an existing activity. Matched on their start, like the
# keys themselves.
TRIGGER_ALIASES = {
    "IPILATES": "IWORKOUT",
    "IBOOTCAMP": "IWORKOUT",  # ibootcamp, ibootcamped, ibootcamping
    "IPLANK": "IPLANKED",     # the key is the longer word, so "iplank" and "iplanking" miss it
    "IWALK": "ISTEPS",
}

# Trigger words that no longer log. Only a replay of old Slack history reads them
# (rebuild_from_slack.py), so a message sent while they still worked keeps its count.
RETIRED_TRIGGERS = {
    "IBREATH": "IPRAYANAM",
}


def detect(text, history=False):
    """Trigger keywords present in the message, in the order they appear.

    Tokenised rather than substring-matched, and matched on prefix, so
    "Iplanked" hits IPLANKED and "guidance" does not hit IDANCE. One entry per
    activity: a message naming the same activity twice is still one log, and
    the extractor is asked for the combined total. `history` also reads the
    retired trigger words, for a message that was sent when they still counted.
    """
    seen, found = set(), []
    triggers = {key: key for key in ACTIVITIES}
    triggers.update(TRIGGER_ALIASES)
    if history:
        triggers.update(RETIRED_TRIGGERS)
    words = sorted(triggers, key=len, reverse=True)
    for token in re.findall(r"[A-Za-z0-9]+", text or ""):
        upper = token.upper()
        for word in words:
            if upper.startswith(word):
                key = triggers[word]
                if key not in seen:
                    seen.add(key)
                    found.append(key)
                break
    return found


# --------------------------------------------------------------------------
# EDGES -- everything below talks to the network
# --------------------------------------------------------------------------

def coerce_value(name, value):
    """Cast a value to the column's declared type.

    The data table rejects the entire document if one field is the wrong type,
    so a single int in a string column loses the whole write.
    """
    kind = COLUMN_TYPES.get(name, "string")
    if value is None:
        return None
    try:
        if kind == "integer":
            return int(round(float(value)))
        if kind == "number":
            return float(value)
        if kind == "boolean":
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes")
            return bool(value)
    except (TypeError, ValueError):
        return value
    # string and date columns both travel as text
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


def _post_json(url, headers, payload, timeout=HTTP_TIMEOUT):
    return _send_json(url, headers, payload, "POST", timeout)


# --------------------------------------------------------------------------
# Channel milestones
#
# The same ladders channel_summary.py posts on a Friday. Kept here so a
# crossing can be called the moment it happens rather than days later; if you
# retune one, retune the other.
#
# No state is stored. channel_best() is read BEFORE the write, so its standings
# sum is the channel total before this log, and adding what was just logged
# gives the total after. A rung sitting between the two was crossed by this
# message -- and cannot be crossed again, because the next log starts past it.
CHANNEL_LADDERS = {
    "step_users":   {"cycle": 1000000,
                     "rungs": [250000, 500000, 750000, 1000000]},
    "pushup_users": {"cycle": 5000,
                     "rungs": [1000, 2000, 3000, 4000, 5000]},
    "plank_users":  {"cycle": 18000,
                     "rungs": [3600, 7200, 10800, 14400, 18000]},
}


# Every other activity climbs a plain run of round numbers instead: hours for anything
# timed, a count for anything counted. The channel only gets one once enough people are
# doing the activity for a "channel" total to mean something -- a milestone that is really
# one person's total is the personal kind below.
CHANNEL_HOUR_MARKS = (1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 300,
                      400, 500, 750, 1000)
CHANNEL_COUNT_MARKS = (10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000,
                       4000, 5000, 7500, 10000, 15000, 20000, 25000, 50000, 75000, 100000)
CHANNEL_MILESTONE_MIN_PEOPLE = 4

# More hours asleep or fasting is not something anybody is trying to reach.
NO_MILESTONE = {"ISLEEP", "IFAST"}

# ------------------------------------------------------------------ personal milestones
#
# The round numbers a person's own running total passes, one ladder per activity. KEEP
# THIS SECTION IDENTICAL in channel_summary.py and spotter/spotter.py (a Workato step is
# one file, so it is copied, and a test fails if the two drift) -- spotter celebrates a
# milestone the moment it happens, the Friday post names it.
#
# Each ladder is cut to how its activity is really done, because a milestone only means
# something if it had to be worked for:
#   * the FIRST one takes about a week of the activity -- five to seven ordinary sessions
#     -- so nobody is handed one for a first log;
#   * the next few come a month or two apart for a regular, and then further apart;
#   * it never runs out. Past the last figure listed, the ladder carries on for ever at
#     its LAST STRIDE -- (..., 15000, 20000) goes on to 25,000, 30,000 and so on -- and
#     that stride is set so an ordinary regular still passes one or two a year in their
#     tenth year. So the last two figures of a ladder are a decision, not an ending;
#   * the figures are the ones people would set themselves: 100 pushups, 5 hours in the
#     saddle, a week and then a month of cold showers.
# The note beside each ladder is the ordinary session, and how often, it was sized for.
#
# Keyed by activity (the row type without "_users"). A counted activity is in its own
# unit; a timed one is in MINUTES, whatever unit it is stored in.
def _hours(*hours):
    return tuple(h * 60 for h in hours)


PERSONAL_MARKS = {
    # strength
    "pushup": (100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000, 15000,
               20000),                                       # ~30 a day; then every 5,000
    "pullup": (25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, 4000,
               5000),                                        # ~8 a day; then every 1,000
    "squat": (100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000, 15000,
              20000),                                        # ~30 a day; then every 5,000
    "plank": (10, 30) + _hours(1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20,
                               25),                          # 1-2 min a day; then every 5h
    "workout": _hours(5, 10, 25, 50, 75, 100, 150, 200, 250, 300),   # ~45 min, 3 a week; 50h
    # endurance
    "run": _hours(3, 5, 10, 15, 25, 50, 75, 100, 125, 150),  # ~30 min, 3 a week; every 25h
    "cycle": _hours(5, 10, 25, 50, 75, 100, 150, 200, 250, 300),     # ~45 min, 3 a week; 50h
    "swim": _hours(3, 5, 10, 20, 30, 50, 75, 100),           # ~40 min, 2 a week; every 25h
    "cardio": _hours(3, 5, 10, 15, 25, 50, 75, 100),         # ~25 min, 3 a week; every 25h
    # everyday movement
    "step": (50000, 100000, 250000, 500000, 750000, 1000000, 1500000, 2000000, 3000000,
             4000000, 5000000),                              # ~8,000 a day; then every 1,000,000
    "stairs": (50, 100, 250, 500, 1000, 1500, 2000, 3000, 4000,
               5000),                                        # ~10 flights a day; every 1,000
    "dance": _hours(2, 5, 10, 20, 30, 50, 75, 100),          # ~30 min, 1-2 a week; every 25h
    # stillness -- short sittings, so the first stops are low
    "yoga": _hours(3, 5, 10, 20, 30, 50, 75, 100),           # ~30 min, 3 a week; every 25h
    "meditate": _hours(1, 3, 5, 10, 20, 30, 50, 75, 100),    # ~12 min a day; every 25h
    "breathe": (30,) + _hours(1, 2, 3, 5, 10, 15, 20, 30, 40, 50),   # ~6 min a day; every 10h
    "chant": _hours(1, 3, 5, 10, 20, 30, 50, 75, 100),       # ~15 min, most days; every 25h
    "eyepushups": (30,) + _hours(1, 2, 3, 5, 8, 12, 16, 20, 25),     # ~3 min a day; every 5h
    "solitude": _hours(2, 5, 10, 20, 30, 50, 75, 100),       # ~20 min, 3 a week; every 25h
    # mind and making
    "read": (100, 250, 500, 1000, 2000, 3000, 5000, 7500, 10000, 12500,
             15000),                                         # ~20 pages a day; every 2,500
    "write": (10, 25, 50, 100, 150, 250, 500, 750, 1000, 1250),      # ~2 pages; every 250
    "journal": _hours(1, 3, 5, 10, 20, 30, 50, 75, 100),     # ~10 min a day; every 25h
    "learn": _hours(3, 5, 10, 25, 50, 75, 100),              # ~30 min, 3 a week; every 25h
    "sketch": _hours(2, 5, 10, 20, 30, 50, 75, 100),         # ~25 min, 2 a week; every 25h
    "paint": _hours(3, 5, 10, 25, 50, 75, 100),              # ~45 min, weekly; every 25h
    # habits -- a week, a month and a year of them are the numbers that mean something
    "hydrate": (50, 100, 250, 500, 1000, 1500, 2000, 3000, 4000,
                5000),                                       # ~7 glasses a day; every 1,000
    "cold_shower": (7, 15, 30, 50, 75, 100, 150, 200, 250, 365, 500, 750,
                    1000),                                   # one a day; then every 250
}
# An activity added later, until it is given a ladder of its own above.
PERSONAL_DEFAULT_COUNT = (100, 250, 500, 1000, 2500, 5000, 7500, 10000)
PERSONAL_DEFAULT_MINUTES = _hours(3, 5, 10, 25, 50, 75, 100)


def personal_passed(marks, before, after):
    """Every milestone of a ladder in (before, after], lowest first: the figures listed,
    and past the last of them one more at every stride, for ever."""
    found = [m for m in marks if before < m <= after]
    if len(marks) > 1 and after > marks[-1]:
        last, stride = marks[-1], marks[-1] - marks[-2]
        value = last + stride * max(1, (int(before) - last) // stride + 1)
        while value <= after:
            found.append(value)
            value += stride
    return found
# ---------------------------------------------------------- end of personal milestones


def hour_size(keyword):
    """How many of this activity's own units make an hour; 0 when it is not a duration."""
    return {"seconds": 3600, "minutes": 60}.get(ACTIVITIES[keyword]["unit_plural"], 0)


def marks_between(marks, before, after):
    """Every mark in (before, after]. Past the end of `marks` the last figure repeats as
    the step, so a total of 140,000 still has 125,000 behind it."""
    found = [m for m in marks if before < m <= after]
    step = marks[-1]
    value = (int(before) // step + 1) * step
    while value <= after:
        if value > marks[-1] and value not in found:
            found.append(value)
        value += step
    return sorted(found)


def channel_crossing(row_type, before, after, keyword=None, people=0):
    """The highest channel milestone this log took us past, or 0.

    Steps, pushups and plank climb the ladders above, and laps repeat, so a rung is
    checked at its absolute value -- the 2h plank marker is 7,200 on the first lap and
    93,600 on the second. Any other activity climbs round numbers, but only once
    `people` have logged it (CHANNEL_MILESTONE_MIN_PEOPLE). Only the highest is
    returned: one log big enough to clear three rungs deserves one shout, not three.
    """
    if after <= before:
        return 0
    spec = CHANNEL_LADDERS.get(row_type)
    if not spec:
        if (not keyword or keyword in NO_MILESTONE
                or people < CHANNEL_MILESTONE_MIN_PEOPLE):
            return 0
        size = hour_size(keyword)
        marks = (tuple(h * size for h in CHANNEL_HOUR_MARKS) if size
                 else CHANNEL_COUNT_MARKS)
        hits = marks_between(marks, before, after)
        return max(hits) if hits else 0
    cycle, hits = spec["cycle"], []
    lap = (int(before) // cycle) * cycle
    while lap <= after:
        for rung in spec["rungs"]:
            value = lap + rung
            if before < value <= after:
                hits.append(value)
        lap += cycle
    return max(hits) if hits else 0


def personal_marks(keyword):
    """The round numbers a person's own total climbs, in the activity's own units."""
    if keyword in NO_MILESTONE:
        return ()
    activity = ACTIVITIES[keyword]["row_type"][:-len("_users")]
    size = hour_size(keyword)
    if not size:
        return PERSONAL_MARKS.get(activity, PERSONAL_DEFAULT_COUNT)
    per_minute = size // 60                   # 1 for an activity stored in minutes, 60 in seconds
    return tuple(m * per_minute for m in PERSONAL_MARKS.get(activity, PERSONAL_DEFAULT_MINUTES))


def personal_crossing(keyword, before, after):
    """The highest personal milestone this log took someone past, or 0."""
    marks = personal_marks(keyword)
    if not marks or after <= before:
        return 0
    hits = personal_passed(marks, before, after)
    return max(hits) if hits else 0


# How an activity follows "10 hours of": "10 hours of run" reads wrong, and so does
# "50 glasses of hydration".
MILESTONE_NAME = {"IRUN": "running", "ISWAM": "swimming", "IDANCE": "dancing",
                  "IWORKOUT": "working out", "ICYCLE": "cycling", "ICARDIO": "cardio",
                  "IJOURNAL": "journaling", "ICHANT": "chanting", "ISKETCH": "sketching",
                  "IPAINT": "painting", "ILEARN": "learning", "IHYDRATE": "water"}


def milestone_figure(keyword, value):
    """A milestone as people would say it: "1,000 pushups", "10 hours of yoga",
    "500 pages of reading", "350,000 steps". The unit alone ("1,000 reps") would not say
    of what, and "of Steps" after "steps" says it twice."""
    a = ACTIVITIES[keyword]
    name = str(a["name"]).lower()
    value = int(value or 0)
    size = hour_size(keyword)
    if size:
        what = MILESTONE_NAME.get(keyword, name)
        minutes = value * 60 // size
        if minutes < 60:
            return "{} minute{} of {}".format(minutes, "" if minutes == 1 else "s", what)
        hours, rest = divmod(minutes, 60)
        if rest:
            return "{}h {}m of {}".format(hours, rest, what)
        return "{} hour{} of {}".format(hours, "" if hours == 1 else "s", what)
    plural = str(a["unit_plural"]).lower()
    if plural == "reps":
        return "{:,} {}s".format(value, name)
    if plural.startswith(name) or name.startswith(plural.rstrip("s")):
        return "{:,} {}".format(value, plural)
    if str(a["unit_singular"]).lower() in name:
        return "{:,} {}s".format(value, name)
    return "{:,} {} of {}".format(value, plural, MILESTONE_NAME.get(keyword, name))


def crossing_blocks(keyword, user_id, value, after):
    """The shout when the channel clears a milestone together."""
    detail = ("<@{}>'s log just took us past *{}* — everyone in the channel, added "
              "together.").format(user_id, milestone_figure(keyword, value))
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
              "text": ":announcement:  *Channel milestone*"}},
             {"type": "section", "text": {"type": "mrkdwn", "text": detail}}]
    if keyword == "ISTEPS":
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
            "text": "That's {} together, as a channel.".format(
                steps_km_text(after))}]})
    return blocks


def wording_turn(message_ts):
    """A number to rotate wording on, from the message ts, so the same phrasing does not
    greet every post.

    The digits are added up. The last digit alone will not do: every ts this workspace
    sends ends in 9, so a rotation on it lands on the same line every single time.
    """
    return sum(int(c) for c in str(message_ts) if c.isdigit())


# How many logs of an activity before somebody has a history in it. Under this a milestone
# is a strong start, and nothing may be said about consistency: "steady dedication" told
# to somebody on their first ride is untrue, and reads as though nobody looked.
MILESTONE_REGULAR_SESSIONS = 5

# What is said when someone passes a round number of their own. Rotated on the message
# ts, as ask_for_count is, so the same words do not greet every milestone. Written to be
# warm and plain: a milestone is the person's, and the room is there to see it. These are
# true of anybody, a first log included.
PERSONAL_LINES = (
    "{who} just passed *{figure}*. :tada:",
    "{who} has now done *{figure}* — a milestone worth a round of applause. :clapping-all:",
    "That's *{figure}* for {who}. Well done. :raised_hands:",
    "*{figure}* — {who} just crossed it. :sparkles:",
    "A round of applause for {who}, who has just reached *{figure}*. :clapping-all:",
)
# ... and these only of somebody with a history in the activity (see milestone_history).
PERSONAL_LINES_OVER_TIME = (
    "{who} is now past *{figure}* — that is a lot of showing up. :muscle:",
    "*{figure}* and counting for {who}. Steady work, well earned. :clapping-all:",
    "{who} has reached *{figure}*, one day at a time. :tada:",
)

# The same line written afresh by the model, when there is a key, so that no two
# milestones need read alike. The model is told what is true of the person -- how many
# times they have logged this, since when, what they logged just now -- so that what it
# says fits them, and it supplies the words and nothing else: the person and the figure
# stay as {who} and {figure} and are filled in here, so it can get neither wrong. A reply
# that fails any check is dropped for one of the lines above.
MILESTONE_SYSTEM = (
    "You write one sentence for a workplace wellness Slack channel, marking the moment "
    "a colleague passes a round number of their own in an activity they log.\n\n"
    "You are told what is true of them: the milestone, what they logged just now, and "
    "how they got here. Write for THIS person. Somebody who reached it over months and "
    "somebody who reached it in a single session are different stories, and a sentence "
    "that would fit either is the wrong sentence.\n\n"
    "Write {who} where their name goes and {figure} where the milestone goes (it will "
    "read like '1,000 pushups' or '10 hours of yoga'). Use each exactly once, written "
    "exactly like that, braces included. Both are filled in afterwards.\n\n"
    "Rules:\n"
    "- One sentence, 20 words at most.\n"
    "- Say only what the facts support. If they have little or no history in the "
    "activity, never speak of consistency, dedication, steadiness, routine, habit or "
    "showing up: none of that has happened yet. Mark a strong start instead.\n"
    "- Their session count and start date are printed just under your sentence. Use "
    "them to judge what is true, not to repeat: no counts, dates or lengths of time, "
    "and no numbers of your own.\n"
    "- Warm, plain and professional, in the register you are given: how a colleague "
    "who noticed would say it in a channel that senior people read. No hype, no jokes, "
    "no slang, no exclamation marks.\n"
    "- No emoji, no hashtags, no quotation marks.\n"
    "- Do not use the phrases 'round of applause' or 'a milestone worth'.\n"
    "- Return the sentence only.")
MILESTONE_REGISTER = {"strength": "energetic, but measured", "endurance": "steady and warm",
                      "habit": "modest and warm", "stillness": "calm and quiet"}
# Something to lean on, so the model does not settle on one sentence. Which set depends
# on whether there is a history to speak of.
MILESTONE_ANGLES = (
    "the steady effort it took to get there",
    "the round number itself, stated simply",
    "the channel noticing and being glad",
    "how far they have come since they started",
    "showing up, again and again",
    "what comes next, lightly",
)
MILESTONE_ANGLES_NEW = (
    "a strong start",
    "the size of what they logged just now",
    "the round number itself, stated simply",
    "the channel noticing and being glad",
)
MILESTONE_EMOJI = (":clapping-all:", ":tada:", ":raised_hands:", ":sparkles:")
MILESTONE_LINE_MAX = 160
# What may not be said of somebody with no history, whatever the model was told.
MILESTONE_UNTRUE_OF_A_START = re.compile(
    r"\b(stead\w*|consisten\w*|dedicat\w*|disciplin\w*|persever\w*|persist\w*|commit\w*"
    r"|habit\w*|routine\w*|streak\w*|showing up|shows up|keeps?|kept|again and again"
    r"|day after day|week after week|over time|every (?:day|week|session|minute))\b", re.I)


def milestone_history(item):
    """What is known of somebody's history in the activity they just passed a milestone
    in: {"sessions", "days", "span" (days since their first log), "regular"}."""
    sessions = int(item.get("lifetime_sessions") or 0)
    first, now = as_date(item.get("first_seen")), as_date(item.get("logged_on"))
    return {"sessions": sessions, "days": int(item.get("active_days") or 0),
            "span": (now - first).days if first and now and now > first else 0,
            "regular": sessions >= MILESTONE_REGULAR_SESSIONS}


def span_text(days):
    """A length of time as people say it: "9 days", "about 3 weeks", "about 4 months"."""
    if days < 14:
        return "{} day{}".format(days, "" if days == 1 else "s")
    if days < 60:
        return "about {} weeks".format(int(round(days / 7.0)))
    return "about {} months".format(int(round(days / 30.4)))


def milestone_brief(item, turn):
    """What the model is told about one milestone: the facts, and what to lean on."""
    keyword = item["keyword"]
    name = str(ACTIVITIES[keyword]["name"]).lower()
    history = milestone_history(item)
    if history["sessions"] <= 1:
        how = ("this is their very first log of {} -- all of it came from this one "
               "session, and there is no history yet".format(name))
    elif not history["regular"]:
        how = "only their {} log of {} -- early days, little history yet".format(
            ordinal_number(history["sessions"]), name)
    else:
        how = "built up over {} sessions on {} different days".format(
            history["sessions"], max(history["days"], 1))
        if history["span"]:
            how += ", across {}".format(span_text(history["span"]))
    angles = MILESTONE_ANGLES if history["regular"] else MILESTONE_ANGLES_NEW
    lines = ["Activity: {}".format(ACTIVITIES[keyword]["name"]),
             "Register: {}".format(MILESTONE_REGISTER.get(
                 ACTIVITIES[keyword].get("family"), "warm and plain")),
             "The milestone that {{figure}} stands for: {}".format(
                 milestone_figure(keyword, item["personal_crossed"])),
             "What they logged just now: {}".format(
                 item.get("amount") or "not given"),
             "How they got here: {}".format(how)]
    if history["regular"] and int(item.get("streak") or 0) >= 3:
        lines.append("Current run: {} working days in a row".format(item["streak"]))
    lines.append("Lean on this: {}".format(angles[turn % len(angles)]))
    return "\n".join(lines)


def milestone_line(llm, item, turn):
    """One milestone's line as the model wrote it, still holding {who} and {figure}, or
    "" to use a template: no key, no reply, or a reply that fails its checks."""
    if not llm or not llm.headers.get("api-key"):
        return ""
    reply = llm.chat(MILESTONE_SYSTEM, milestone_brief(item, turn), temperature=1.0,
                     max_tokens=60)
    if not reply:
        return ""
    line = tidy_coach_note(reply).replace("*", "")
    line = re.sub(r":[a-z0-9_+\-]+:|[\u2600-\u27bf\ufe0f\U0001f000-\U0001faff]", "", line)
    line = re.sub(r"\s+([.,!?])", r"\1", re.sub(r"\s{2,}", " ", line)).strip()
    rest = line.replace("{who}", "").replace("{figure}", "")
    if (line.count("{who}") != 1 or line.count("{figure}") != 1
            or re.search(r"[{}\d#]|<@", rest) or len(line) > MILESTONE_LINE_MAX):
        llm.errors.append("milestone line: reply failed its checks, template used")
        return ""
    if not milestone_history(item)["regular"] and MILESTONE_UNTRUE_OF_A_START.search(rest):
        llm.errors.append("milestone line: spoke of consistency on an early log, template used")
        return ""
    if line[-1] not in ".!?":
        line += "."
    return "{} {}".format(line.replace("{figure}", "*{figure}*"),
                          MILESTONE_EMOJI[turn % len(MILESTONE_EMOJI)])


def personal_milestone_blocks(user_id, items, message_ts="", llm=None):
    """One post for everything somebody passed in a message. `items` are the logged
    entries carrying a `personal_crossed`."""
    turn = wording_turn(message_ts)
    who = "<@{}>".format(user_id)
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
               "text": ":trophy:  *Personal milestone*"}}]
    lines = []
    for index, item in enumerate(items):
        ready = PERSONAL_LINES + (PERSONAL_LINES_OVER_TIME
                                  if milestone_history(item)["regular"] else ())
        template = (milestone_line(llm, item, turn + index)
                    or ready[(turn + index) % len(ready)])
        line = template.format(
            who=who, figure=milestone_figure(item["keyword"], item["personal_crossed"]))
        lines.append(line)
    blocks.append({"type": "section", "text": {"type": "mrkdwn",
                   "text": "\n".join(lines)}})
    notes = []
    for item in items:
        bits = []
        if item.get("lifetime_sessions"):
            bits.append("{} session{}".format(
                item["lifetime_sessions"], "" if item["lifetime_sessions"] == 1 else "s"))
        first = as_date(item.get("first_seen"))
        if first:
            bits.append("since {} {}".format(first.day, first.strftime("%b")))
        if item["keyword"] == "ISTEPS":
            bits.append(steps_km_text(item["personal_crossed"]).replace("~", "about ")
                        + " on foot")
        if bits:
            notes.append("{}: {}".format(item["activity"], "  \u00b7  ".join(bits)))
    if notes:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": "\n".join(notes)}]})
    return blocks


def personal_milestone_text(user_id, items):
    return "<@{}> reached a milestone: {}".format(
        user_id, ", ".join(milestone_figure(i["keyword"], i["personal_crossed"])
                           for i in items))


# ---------------------------------------------------------------------------- journey
#
# The channel's steps, added together, walk a route around the world. Everyone's steps go
# into one total, so it is a shared goal with a story and a finish line, and nobody is
# ranked by it. KEEP THIS SECTION IDENTICAL in channel_summary.py and spotter/spotter.py
# (a Workato step is one file, so it is copied, and a test fails if the two drift) --
# spotter announces an arrival the moment it happens, the Friday post shows the road.
#
# Stops are real places and the distances are great-circle ("as the crow flies") between
# their coordinates, so every figure can be checked. Seas are crossed by ferry. To change
# the route, edit ROUTE: the legs, the lap length and every figure follow. The first stop
# is the start line and the last is the same place again, to close the loop; past it a
# new lap begins.
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


def journey_arrival_blocks(user_id, arrival, steps_after):
    """The shout when the channel's steps carry it to the next stop on The Great Walk."""
    lap, index, stop = arrival
    total_km = steps_to_km(steps_after)
    if index == len(ROUTE) - 1:
        detail = ("<@{}>'s steps just carried us all the way round the world \u2014 "
                  "*{:,.0f} km*, together. Lap {} starts now.").format(user_id, LAP_KM, lap + 1)
    else:
        detail = "<@{}>'s steps just took us to *{}* {} \u2014 {}.".format(
            user_id, stop[0], stop[1], stop[4])
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
               "text": ":world_map:  *{}*".format(JOURNEY_NAME)}},
              {"type": "section", "text": {"type": "mrkdwn", "text": detail}}]
    ahead = ROUTE[1] if index == len(ROUTE) - 1 else ROUTE[index + 1]
    leg = LEG_KM[0] if index == len(ROUTE) - 1 else LEG_KM[index]
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
        "text": "{:,.0f} km walked together  \u00b7  next stop {} {}, {:,.0f} km on".format(
            total_km, ahead[1], ahead[0], leg)}]})
    return blocks


# ----------------------------------------------------------------------------- badges
#
# Collectable recognition, worked out from the days a person logged and nothing else --
# no new input, no stored state. KEEP THIS SECTION IDENTICAL in channel_summary.py and
# iprofile/data_profile.py (a Workato step is one file, so it is copied, and a test fails
# if the two drift).
#
# What a badge is NOT: a volume or a rank. Every one is about showing up -- turning up
# day after day, week after week, trying more things -- so someone who walks 3,000 steps
# a day earns the same badges as someone who walks 30,000. (Round numbers of volume are
# the personal milestones, which spotter celebrates; they are deliberately not repeated
# here.) Tiers are separate badges in a family, and a person's profile shows the highest
# of each.
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


def badge_counts(person, today, channel_first=None):
    """{badge id: how many times it has been earned} for everything earned by `today`.

    A badge that can be won again counts each win: every run of 5 working days is a Five
    in a Row, every flawless week a Perfect Week, every month with 15 days a Month
    Strong. Cumulative tiers count how many times the bar was cleared (Four Perfect Weeks
    is 7 perfect weeks // 4 = once). One-off badges are always 1.
    """
    counts = {badge_id: 1 for badge_id in badge_dates(person, today, channel_first)}
    days = sorted(d for d in person["days"] if d <= today)
    if not counts:
        return counts

    def needs(family):
        return [need for need, _name, _about in
                next(t for f, _e, t in BADGE_FAMILIES if f == family)]

    def put(family, need, times):
        key = "{}_{}".format(family, need)
        if key in counts:
            counts[key] = max(1, times)

    logged = set(days)
    runs = {need: 0 for need in needs("streak")}
    run, day = 0, days[0]
    while day <= today:
        if day.weekday() < 5:
            if day in logged:
                run += 1
                if run in runs:
                    runs[run] += 1
            else:
                run = 0
        day += timedelta(days=1)
    for need, times in runs.items():
        put("streak", need, times)

    by_week = {}
    for day in days:
        by_week.setdefault(_monday(day), []).append(day)
    weeks = {need: 0 for need in needs("steady")}
    run, previous = 0, None
    for monday in sorted(by_week):
        run = run + 1 if previous is not None and monday - previous == timedelta(days=7) else 1
        if run in weeks:
            weeks[run] += 1
        previous = monday
    for need, times in weeks.items():
        put("steady", need, times)

    perfect = weekends = 0
    for monday, week_days in by_week.items():
        weekdays = {d.weekday() for d in week_days}
        if {0, 1, 2, 3, 4} <= weekdays and monday + timedelta(days=4) <= today:
            perfect += 1
        if {5, 6} <= weekdays:
            weekends += 1
    for need in needs("perfect"):
        put("perfect", need, perfect // need)
    for need in needs("weekend"):
        put("weekend", need, weekends // need)

    seen_in_week = {}
    for entry in person["rows"]:
        for day in entry["days"]:
            if day <= today:
                seen_in_week.setdefault(_monday(day), set()).add(entry["activity"])
    for need in needs("allround"):
        put("allround", need, sum(1 for seen in seen_in_week.values() if len(seen) >= need))
    put("triple", 1, sum(1 for seen in seen_in_week.values() if all(a in seen for a in TRIPLE)))

    by_month = {}
    for day in days:
        by_month[(day.year, day.month)] = by_month.get((day.year, day.month), 0) + 1
    for need in needs("month"):
        put("month", need, sum(1 for n in by_month.values() if n >= need))
    return counts


def top_badges(ids):
    """The highest tier of each family among `ids`, in display order."""
    best = {}
    for badge_id in ids:
        badge = BADGES.get(badge_id)
        if badge and (badge["family"] not in best or badge["tier"] > best[badge["family"]]["tier"]):
            best[badge["family"]] = badge
    return sorted(best.values(), key=lambda b: b["order"])


def badge_progress(person, today):
    """Where the families that can be chased stand right now:
    {"streak": live run of working days, "steady": live run of weeks,
     "explorer": activities tried, "month": days logged this calendar month}."""
    days = {d for d in person["days"] if d <= today}
    # a run is live until a working day passes without a log, so today not being
    # logged yet does not end it
    streak, day = 0, today
    while day >= today - timedelta(days=400):
        if day.weekday() < 5:
            if day in days:
                streak += 1
            elif day != today:
                break
        day -= timedelta(days=1)
    weeks, monday = 0, _monday(today)
    in_week = {_monday(d) for d in days}
    if monday not in in_week:
        monday -= timedelta(days=7)
    while monday in in_week:
        weeks += 1
        monday -= timedelta(days=7)
    tried = {e["activity"] for e in person["rows"] if any(d <= today for d in e["days"])}
    month = len([d for d in days if (d.year, d.month) == (today.year, today.month)])
    return {"streak": streak, "steady": weeks, "explorer": len(tried), "month": month}


BADGE_CHASE = {"streak": "more working days in a row", "steady": "more weeks in a row",
               "explorer": "more activities to try", "month": "more days this month"}


def next_badges(person, today, earned, limit=2):
    """[(badge, remaining, phrase)] -- the nearest badges that can be chased, nearest
    first. Only families somebody is partway through: nothing is shown for a run that
    is not going."""
    progress = badge_progress(person, today)
    held = {b["family"]: b["tier"] for b in top_badges(earned)}
    options = []
    for family in BADGE_CHASE:
        value = progress.get(family, 0)
        if value <= 0:
            continue
        ahead = [b for b in BADGES.values()
                 if b["family"] == family and b["need"] > value
                 and b["tier"] > held.get(family, -1)]
        if not ahead:
            continue
        badge = min(ahead, key=lambda b: b["need"])
        options.append((badge["need"] - value, -badge["need"], badge))
    options.sort(key=lambda o: (o[0], o[1]))
    return [(b, remaining, BADGE_CHASE[b["family"]]) for remaining, _n, b in options[:limit]]


# ------------------------------------------------------------------------- events
#
# /ievent (ievent/ievent.py) runs dated challenges: an organiser picks a window and some
# activities, people press Join, and every log in the window counts towards that event's own
# boards. Spotter's only part is the counting. It is cheap on purpose: a person's rows are
# already read for badges, and a person who has joined nothing costs no extra read at all.
#
# Three row types share the table (none ends in _users, so nothing else ever sees them):
#   event         the definition: id, name, description (activities), created_at (first day),
#                 day (last day), status (open / done / cancelled), content (json settings)
#   event_member  one per person per event: id = person, group_id = event
#   event_entry   one per person per activity per event: id = person, group_id = event,
#                 grant_type = activity; `total` the amount of each log and `heatmap_dates`
#                 the day of each, in step.
EVENT_ROW = "event"
EVENT_MEMBER_ROW = "event_member"
EVENT_ENTRY_ROW = "event_entry"
EVENT_REACTION = "dart"


def parse_event(row):
    """An open event as {"id", "name", "activities", "start", "end"}, or None."""
    start, end = as_date(row.get("created_at")), as_date(row.get("day"))
    if (row.get("status") or "") != "open" or not start or not end:
        return None
    return {"id": row.get("id") or "", "name": row.get("name") or "Event",
            "activities": {a.strip() for a in str(row.get("description") or "").split(",") if a.strip()},
            "start": start, "end": end}


def tidy_amount(value):
    value = float(value)
    return int(value) if value == int(value) else round(value, 2)


def count_for_events(table, joined, logged, user_id, user_name, today):
    """Add this message's logs to every open event the person has joined.

    `joined` is the set of event ids they are in. Only days inside an event's window count, and
    only for the activities it names. Returns (counted, warnings): what was added, for the
    result and the reaction, and anything that went wrong. A failure here never touches the log
    itself, which is already saved.
    """
    counted, warnings = [], []
    if not joined:
        return counted, warnings
    rows = table.query({"row_type": {"$eq": EVENT_ROW}}, limit=100, every=True)
    if table.read_failed:
        return counted, ["events: could not read the event list"]
    events = [e for e in (parse_event(r) for r in rows) if e and e["id"] in joined]
    for event in events:
        for item in logged:
            activity = ACTIVITIES[item["keyword"]]["row_type"][:-len("_users")]
            if activity not in event["activities"]:
                continue
            days = [(as_date(d["day"]), d["count"]) for d in item.get("per_day") or []]
            days = [(day, count) for day, count in days
                    if day and event["start"] <= day <= event["end"] and count]
            if not days:
                continue
            row = table.query({"$and": [
                {"row_type": {"$eq": EVENT_ENTRY_ROW}}, {"group_id": {"$eq": event["id"]}},
                {"grant_type": {"$eq": activity}}, {"id": {"$eq": user_id}}]}, limit=1)
            if table.read_failed:
                warnings.append("events: could not read {} for {}".format(activity, event["name"]))
                continue
            row = row[0] if row else None
            amounts = split_numbers((row or {}).get("total"))
            dates = split_dates((row or {}).get("heatmap_dates"))
            amounts = amounts[:len(dates)] if len(amounts) > len(dates) else amounts
            dates = dates[:len(amounts)]
            for day, count in days:
                amounts.append(count)
                dates.append(day.isoformat())
            fields = {"record_key": "{}_{}_{}_{}".format(EVENT_ENTRY_ROW, event["id"], activity, user_id),
                      "row_type": EVENT_ENTRY_ROW, "id": user_id, "name": user_name,
                      "group_id": event["id"], "grant_type": activity,
                      "total": ",".join(str(tidy_amount(a)) for a in amounts),
                      "heatmap_dates": ",".join(dates), "updated_at": today.isoformat()}
            if table.write(row, fields):
                counted.append({"event": event["id"], "event_name": event["name"],
                                "activity": activity,
                                "count": tidy_amount(sum(c for _d, c in days)), "days": len(days)})
            else:
                warnings.append("events: could not save {} for {}".format(activity, event["name"]))
    return counted, warnings


# ------------------------------------------------------ badges, announced as they happen

# Not announced live: the welcome already covers a first log, and "founding member" is
# measured against the channel's whole history, which spotter does not read. A weekend
# badge is won again every weekend somebody logs on both days, so announcing it meant a
# post most Sundays for something that is not an achievement; it stays on the profile.
LIVE_BADGE_SKIP = {"first", "founding", "weekend"}

# A badge that can be won again -- All-Rounder every week with three activities, Perfect
# Week every flawless week -- is announced the first time only. Announced every time, a
# regular got the same post week after week ("8th time"), which is noise, not recognition;
# the profile still counts each win. True brings the repeats, and their "(2nd time)", back.
BADGE_REPEATS_ANNOUNCED = False

# The button under a badge post. A click opens the profile of whoever clicked, so anyone
# reading the post can look at their own; that is done by a recipe listening for this
# action_id, not here. `value` carries the person the post is about, should it be wanted.
PROFILE_ACTION = "iprofile_open"
PROFILE_BUTTON = ":sparkles: View my profile"
# The line the button sits beside: the earner's count, then a nudge to whoever is reading.
PROFILE_NUDGE = (":star2: *{} badge{}* so far  \u00b7  Check your profile here "
                 ":point_right::skin-tone-4:")

BADGE_LINES = (
    "{who} just earned {emoji} *{name}* \u2014 {about}.",
    "{emoji} *{name}* is {who}'s \u2014 {about}. Well earned.",
    "New badge for {who}: {emoji} *{name}* \u2014 {about}.",
)


def badge_person(rows):
    """The badge engine's view of a person, from their activity rows."""
    person = {"days": set(), "rows": []}
    for row in rows:
        activity = str(row.get("row_type") or "").replace("_users", "")
        days = [d for d in (as_date(x) for x in split_dates(row.get("heatmap_dates"))) if d]
        if not activity or not days:
            continue
        person["days"].update(days)
        person["rows"].append({"activity": activity, "days": days})
    return person


def earned_by_this_message(before_rows, after_rows, today):
    """The badges a message earned: [badge], highest tier per family, in display order, each
    with `times` -- how many times it is now theirs.

    The person's badges are counted as they stood a moment ago and as they stand with this
    message's days added. A badge counts the first time it is theirs, at the log that earns
    it, and never again: winning it afresh (a second Perfect Week) is counted on the
    profile but is not news, unless BADGE_REPEATS_ANNOUNCED says otherwise.
    """
    before = badge_counts(badge_person(before_rows), today)
    now = badge_counts(badge_person(after_rows), today)
    new = [i for i, times in now.items()
           if BADGES[i]["family"] not in LIVE_BADGE_SKIP
           and (i not in before or (BADGE_REPEATS_ANNOUNCED and times > before[i]))]
    return [dict(b, times=now[b["id"]]) for b in top_badges(new)], len(now)


def with_new_days(rows, logged):
    """The person's rows as they will stand once this message is written: each logged
    activity's heatmap replaced by the one just computed (or added, if it is new)."""
    by_type = {r.get("row_type"): dict(r) for r in rows}
    for item in logged:
        row_type = ACTIVITIES[item["keyword"]]["row_type"]
        updated = by_type.get(row_type, {"row_type": row_type})
        updated["heatmap_dates"] = (item.get("fields") or {}).get("heatmap_dates", "")
        by_type[row_type] = updated
    return list(by_type.values())


def ordinal_number(n):
    """2 -> 2nd, 3 -> 3rd, 11 -> 11th, 22 -> 22nd."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "{}{}".format(n, suffix)


def badge_blocks(user_id, badges, total, message_ts=""):
    """One post for everything somebody earned in a message. It sits in the thread under
    the reply, so it opens with a divider to stand apart from it."""
    turn = wording_turn(message_ts)
    who = "<@{}>".format(user_id)
    lines = [BADGE_LINES[(turn + i) % len(BADGE_LINES)].format(
        who=who, emoji=b["emoji"], name=b["name"], about=b["about"])
        for i, b in enumerate(badges)]
    lines = [line + (" _({} time)_".format(ordinal_number(b["times"])) if b.get("times", 1) > 1 else "")
             for line, b in zip(lines, badges)]
    return [{"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": ":medal:  *New badge{}*".format("" if len(badges) == 1 else "s")}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
            {"type": "section", "block_id": "badge_profile",
             "text": {"type": "mrkdwn", "text": PROFILE_NUDGE.format(
                 total, "" if total == 1 else "s")},
             "accessory": {"type": "button", "action_id": PROFILE_ACTION, "value": user_id,
                           "text": {"type": "plain_text", "text": PROFILE_BUTTON,
                                    "emoji": True}}}]


def badge_text(user_id, badges):
    return "<@{}> earned {}".format(user_id, " and ".join(b["name"] for b in badges))


# --------------------------------------------------------------------------
# Challenges
#
# A challenge lives in its own row (written by challenge.py) and settles itself
# from the logs: nobody has to say "done". Only columns spotter never uses for
# activity rows are involved, so the two never collide.
CHALLENGE_ROW = "challenge"
CHALLENGE_COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "member_name": "bc214e7f-c007-4fd7-ac0e-6367b1e4098f",
    "description": "3d9e2f48-f2b0-457e-9666-5cada51a32b4",
    "grant_type": "355e769f-0aa3-46be-bea3-5c2b3442f658",
    "min_planks": "c44b962d-10d4-424d-b4a2-afb9cf5a9b8d",
    "group_grant_count": "02bf729f-8a19-4542-a8e4-a1b88405f3d5",
    "created_at": "d0b48b75-2fbf-44db-a36a-cc0a1e46036c",
    "day": "5cfe9bc1-cc32-4a5b-9cc6-4f6682cb7a4b",
    "status": "863a9d40-87a7-49ff-ba40-32858e62cd48",
    "source_ref": "e530be4a-68dc-4e9a-ad1f-2dbb8af3abf1",
    "slack_channel_id": "7101072d-867b-4104-a1e4-ef6611adaaa9",
}


def challenge_states(open_rows, row_type, session_best, keyword):
    """This activity's open challenges, each with where the log leaves it.

    session_best is the best SINGLE SESSION, matching what challenge.py means
    by "best" when it sets the bar -- max of the values in `total`, i.e. a
    day's logging. Comparing a per-set figure against it would refuse a
    challenge that was actually met: "beat 58" answered with three sets of 20
    is 60 for this purpose, not 20.

    Read only -- writing and announcing happen once the reply is being built,
    so a failure to post never leaves a challenge marked done with nobody told.
    """
    states = []
    for challenge in open_rows:
        if (challenge.get("description") or "") != row_type:
            continue
        standing = settle_challenge(challenge, session_best, 0)
        states.append({"challenge": challenge, "standing": standing,
                       "keyword": keyword,
                       "from_name": challenge.get("member_name") or "",
                       "from_id": challenge.get("group_id") or "",
                       "settled": standing["settled"],
                       "target": standing["target"],
                       "to_go": standing["to_go"]})
    return states


def settle_challenge(challenge, session_best, day_total):
    """Whether this log completes the challenge, and how it stands.

    A threshold challenge is settled by ONE session reaching the number -- that
    is what "beat my best" and "hit 100" mean. min_planks of 0 marks a
    challenge no single log can decide (a contest, a streak, free text); those
    are reported as open and left for the deadline or a person to judge.
    """
    try:
        target = int(challenge.get("min_planks") or 0)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        return {"settled": False, "judgeable": False, "target": 0,
                "best": session_best, "to_go": 0}
    return {"settled": session_best >= target, "judgeable": True,
            "target": target, "best": session_best,
            "to_go": max(0, target - session_best)}


def challenge_chip(challenge, standing, keyword):
    """The line that rides along in the thread reply."""
    who = challenge.get("member_name") or "someone"
    if not standing["judgeable"]:
        return ":crossed_swords: open challenge from *{}*".format(who)
    if standing["settled"]:
        return ":crossed_swords: *challenge from {} — done*".format(who)
    return ":crossed_swords: *{}* to go on {}'s challenge".format(
        amount_text(keyword, standing["to_go"]), who)


def challenge_blocks(challenge, keyword, user_id, standing,
                      banner_ref=CHALLENGE_BANNER,
                      banner_alt=CHALLENGE_BANNER_ALT):
    """The channel announcement when a challenge is answered.

    Reads like the record posts, because that is what it is -- somebody was
    called out in public and answered it in public. The banner image is its
    own thing, not the channel-record one: banner_ref/banner_alt default to
    CHALLENGE_BANNER/CHALLENGE_BANNER_ALT but the caller can pass the
    "challenge_banner" recipe input instead.
    """
    activity = ACTIVITIES[keyword]["name"]
    challenger = challenge.get("group_id") or ""
    detail = "<@{}> answered <@{}>'s challenge in *{}* — *{}*.".format(
        user_id, challenger, activity, amount_text(keyword, standing["best"]))
    if standing["target"]:
        margin = standing["best"] - standing["target"]
        detail += "\nThe bar was *{}*{}.".format(
            amount_text(keyword, standing["target"]),
            ", cleared by *{}*".format(amount_text(keyword, margin))
            if margin > 0 else ", met exactly")
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
               "text": ":crossed_swords:  *Challenge answered*"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": detail}}]
    banner = banner_block(banner_ref, banner_alt)
    if banner:
        blocks.insert(0, banner)
    return blocks


# --------------------------------------------------------------------------
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

# ------------------------------------------------------------------ weekly challenge: spotter's side
#
# weekly_challenge.py posts a set of weekly goals and, when somebody presses Accept, writes an
# entry into their row of that activity (the section above). Everything spotter does about it
# happens here, on the logs that person makes afterwards:
#
#   * each log is set against their open entries inside the SAME write that saves the log, so
#     there is no second row to keep in step and no way to say a goal is cleared without it
#     being recorded as cleared -- which is also what stops it being said twice. The write also
#     keeps their running counts of challenges accepted and cleared (wc_counts);
#   * the reply under the log says how much is left of each open goal in the activity just
#     logged (thread_blocks) -- and nothing about their goals in other activities;
#   * when one is cleared, it is told in the channel or in the thread under the log, as the
#     input announce_weekly says (channel / thread / off). Like a settled /ichallenge it is a
#     goal the whole room was invited to take on. Nothing is said for someone who has opted out;
#   * somebody who accepted a goal for an activity they had never logged has no row to hold it,
#     so weekly_challenge.py keeps it on the acceptance row, and their first log picks it up;
#   * an entry whose week has gone by is closed as missed on their next log, without a word.
#
# None of this can hold up a log: it runs inside a guard, and a log with no entry to settle
# writes exactly what it always did.
WEEKLY_ACCEPT_ROW = "weekly_accept"


def weekly_settle_row(row, entries, today, waiting=()):
    """Set one activity row's weekly entries against the message being logged.

    `entries` are the message's days ({"day", "total", ...}); `waiting` are entries accepted
    before the row existed. Returns a dict:

        text     the column's new content when anything changed, else None
        cleared  the entries this message cleared
        open     [{"entry", "got"}]: the entries still open after it, with what is done so far
        counts   (accepted, cleared): what the row now holds, ever
    """
    raw = (row or {}).get(WEEKLY_COLUMN)
    mine = weekly_entries(raw)
    known = {entry["post"] for entry in mine}
    added = [entry for entry in waiting if entry["post"] not in known]
    before = int(sum(split_numbers((row or {}).get("total"))))
    logs = [(entry["day"], entry["total"]) for entry in entries]
    settled, cleared, still_open, changed = [], [], [], bool(added)
    for entry in mine + added:
        new, done = weekly_settle(entry, before, logs, today)
        changed = changed or new is not entry
        settled.append(new)
        if done:
            cleared.append(new)
        elif new.get("state") == "open" and as_date(new["to"]) >= today:
            still_open.append({"entry": new, "got": weekly_progress(new, before, logs)})
    text = weekly_text(raw, settled, len(added), len(cleared)) if changed else None
    if changed and text is None:
        # the column holds something that is not ours: nothing is written, so nothing is said
        return {"text": None, "cleared": [], "open": [], "counts": (0, 0)}
    return {"text": text, "cleared": cleared, "open": still_open,
            "counts": weekly_counts(text if text is not None else raw)}


def weekly_totals(rows, now_held):
    """(accepted, cleared) over all of a person's rows, ever. `now_held` is {row_type: counts}
    for the rows this message has just written, which replace what was read before it. `rows`
    is every row of theirs, not just the activity rows: the games keep their goals in rows of
    their own (math_add_user, pairs_memory_user), and a row with no counts adds nothing."""
    accepted = sum(c[0] for c in now_held.values())
    cleared = sum(c[1] for c in now_held.values())
    for row in rows:
        if row.get("row_type") not in now_held:
            more = weekly_counts(row.get(WEEKLY_COLUMN))
            accepted, cleared = accepted + more[0], cleared + more[1]
    return accepted, cleared


def weekly_chips(item):
    """What rides on a logged activity's line in the reply: how much of each open goal is left."""
    bits = []
    for state in item.get("_open") or []:
        entry = state["entry"]
        left = max(1, int(entry["goal"]) - int(state["got"]))
        bits.append(":dart: *{} to go* on this week's *{}*".format(
            session_text(item["keyword"], left), entry.get("text") or "challenge"))
    return bits


# The button on the reply of anyone who has taken a weekly goal on, offering them their goals
# (the open count rides beside it when there is one). A click is answered by weekly_challenge.py (its click recipe
# listens for action_id starting `wchallenge_`), privately, with a progress bar for each of the
# clicker's goals. `value` carries the thread to answer in.
WEEKLY_PROGRESS_ACTION = "wchallenge_progress"
WEEKLY_PROGRESS_BUTTON = "Show my progress"
WEEKLY_REVIEW_BUTTON = "Review my week"     # once every goal of the week is cleared
WEEKLY_PROGRESS_VALUE = "wcp|{}"


def weekly_other_open(rows, logged, today):
    """How many weekly goals the person has open in activities this message did not touch.

    `rows` is everything read for them (activity and game rows alike), as it stood before the
    message; the rows of the logged activities are left out because their goals already ride
    on the reply as "N to go" chips. An entry counts while its week has not ended."""
    touched = {ACTIVITIES[item["keyword"]]["row_type"] for item in logged}
    count = 0
    for row in rows:
        if row.get("row_type") in touched:
            continue
        for entry in weekly_entries(row.get(WEEKLY_COLUMN)):
            if entry.get("state") == "open" and as_date(entry["to"]) >= today:
                count += 1
    return count


def weekly_took_this_week(rows, logged, accepted, today):
    """Whether the person has taken a weekly goal on in the week in progress: an entry of that week on
    one of their rows (open, cleared or missed, as it stood before the message), one this message
    just settled or opened, or one waiting on an acceptance row (`accepted`, this week's only).

    Last week's goals say nothing here. The button that offers the progress card is for someone with a
    goal this week; keyed on the running count of goals ever taken on, it came up on every log of
    anyone who had once taken one, from the Monday morning after the results to the next goal."""
    for row in rows:
        for entry in weekly_entries(row.get(WEEKLY_COLUMN)):
            if as_date(entry["to"]) >= today:
                return True
    for item in logged:
        # (an open goal is a state holding its entry; a cleared one is the entry itself)
        for held in list(item.get("_open") or []) + list(item.get("_weekly") or []):
            entry = held.get("entry", held)
            if as_date(entry.get("to")) and as_date(entry["to"]) >= today:
                return True
    return bool(accepted)


def weekly_progress_block(count, thread_ts, all_done=False):
    """The line and button that offer the clicker their progress on their weekly goals. With
    none open (all cleared, or none taken) the line says so without a count; with every goal of
    the week cleared it says well done, and the button offers the week's card to look back on."""
    if all_done:
        text = ":white_check_mark: *All weekly challenges completed* — well done!"
    elif count:
        text = ":dart: You have *{}* weekly challenge{} open".format(count, "" if count == 1 else "s")
    else:
        text = ":dart: See how your weekly challenges are going"
    return {"type": "section", "block_id": "wc_progress",
            "text": {"type": "mrkdwn", "text": text},
            "accessory": {"type": "button", "action_id": WEEKLY_PROGRESS_ACTION,
                          "value": WEEKLY_PROGRESS_VALUE.format(thread_ts),
                          "text": {"type": "plain_text", "emoji": True,
                                   "text": WEEKLY_REVIEW_BUTTON if all_done
                                   else WEEKLY_PROGRESS_BUTTON}}}


# Returned by row_for when the read failed, so a failed lookup can never be
# mistaken for "this person has no row yet".
LOOKUP_FAILED = object()
# A stop for the paging loop, far past any real channel (50 x 200 rows).
QUERY_MAX_PAGES = 50


class Table(object):
    """Workato data table access, by column name rather than UUID."""

    def __init__(self, token):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.errors = []
        self.written = 0
        self.read_failed = False

    def _decode(self, body):
        """The query endpoint returns schema and data as arrays-of-arrays."""
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        rows = []
        for row in body.get("data", []):
            decoded = dict(zip(columns, [v for group in row for v in group]))
            if "total" in decoded:
                # From here on `total` is the WHOLE list, wherever it is stored.
                decoded["total"], decoded["_total_parts"] = stored_sessions(decoded)
            rows.append(decoded)
        return rows

    def query(self, where, select=None, limit=200, every=False):
        """`every` follows continuation tokens to the last page; without it only the
        first `limit` rows come back, which is right for a lookup of one row and wrong
        for anything that sums or ranks a whole activity."""
        if select and "total" in select:
            # `total` is only the first part of the list: ask for the rest of it too.
            select = list(select) + [c for c in TOTAL_COLUMNS[1:] if c not in select]
        payload = {"where": where, "limit": limit}
        if select:
            payload["select"] = select
        self.read_failed = False
        rows = []
        for _page in range(QUERY_MAX_PAGES):
            body, error = _post_json(TABLE_QUERY_URL, self.headers, payload)
            if error:
                # A partial read is treated as a failed one: half a channel would
                # hand out records and rankings that are not true.
                self.errors.append("table.query " + error)
                self.read_failed = True
                return []
            rows.extend(self._decode(body))
            token = body.get("continuation_token") if every else None
            if not token:
                break
            payload["continuation_token"] = token
        return rows

    def row_for(self, row_type, user_id):
        """The person's row for this activity, including its $record_id.

        Deliberately no `select` here: the update path needs $record_id, and
        narrowing the projection is not worth risking losing it for one row.

        Returns LOOKUP_FAILED -- not None -- when the read itself failed. The
        two are not the same thing: None means "no row yet" and leads to a
        create, so a network blip returning None would enrol a five-year member
        as a first-timer and write a fresh row over their history.
        """
        rows = self.query({"$and": [{"row_type": {"$eq": row_type}},
                                    {"id": {"$eq": user_id}}]}, limit=1)
        if self.read_failed:
            return LOOKUP_FAILED
        return rows[0] if rows else None

    def open_challenges(self, user_id):
        """All of this person's open challenges, in one query.

        Fetched once per message and filtered per activity in memory -- a query
        per logged activity would triple the table reads on a message that logs
        three things, for no new information.

        Returns [] on a read failure, which is the safe direction: a missed
        challenge is a missed celebration, while a phantom one would announce
        something that did not happen.
        """
        rows = self.query({"$and": [{"row_type": {"$eq": CHALLENGE_ROW}},
                                    {"id": {"$eq": user_id}},
                                    {"status": {"$eq": "open"}}]},
                          limit=50)
        return [] if self.read_failed else rows

    def weekly_pending(self, user_id, row_type, today):
        """Weekly-challenge entries this person accepted for an activity they had not logged
        yet, so there was no row to hold them. Read only when a first log is about to create
        that row; whatever cannot be read is simply not there."""
        rows = self.query({"$and": [{"row_type": {"$eq": WEEKLY_ACCEPT_ROW}},
                                    {"group_id": {"$eq": user_id}},
                                    {"grant_type": {"$eq": row_type[:-len("_users")]}}]},
                          limit=50)
        if self.read_failed:
            return []
        waiting = [weekly_entry_from(row.get("content")) for row in rows]
        return [e for e in waiting if e and e.get("state") == "open"
                and as_date(e["to"]) >= today]

    def weekly_accepted(self, user_id, today):
        """Every weekly goal this person has taken on whose week has not ended, from their
        acceptance rows: weekly_challenge.py writes one per goal, whether or not a row of theirs
        holds it too. Its entry there is the copy as first made, so its state says nothing.
        None if the read failed."""
        rows = self.query({"$and": [{"row_type": {"$eq": WEEKLY_ACCEPT_ROW}},
                                    {"group_id": {"$eq": user_id}}]}, every=True)
        if self.read_failed:
            return None
        entries = [weekly_entry_from(row.get("content")) for row in rows]
        return [e for e in entries if e and as_date(e["to"]) >= today]

    def close_challenge(self, challenge, status="done"):
        """Mark it settled. Only the status column is touched."""
        record_id = challenge.get("$record_id")
        if not record_id:
            self.errors.append("challenge has no $record_id")
            return False
        body, error = _send_json(
            TABLE_RECORD_URL.format(record_id), self.headers,
            {"document": {"$" + CHALLENGE_COLUMNS["status"]: status}}, "PUT")
        if error:
            self.errors.append("challenge.close " + error)
            return False
        return True

    def channel_best(self, row_type):
        """Records and the volume standings, from one call.

        `total` costs nothing extra here and gives the leaderboard position
        needed for the "how far to the next person" nudge.
        """
        rows = self.query({"row_type": {"$eq": row_type}},
                          select=["id", "name", "plank_duration",
                                  "personal_best_single_set", "total",
                                  "leaderboard_optout"],
                          limit=200, every=True)
        # Anyone opted out is left out of everything here, as they are on the
        # leaderboard and in the channel summary: they hold no channel record,
        # are never named as the one who held it, and are not counted.
        rows = [r for r in rows if not r.get("leaderboard_optout")]
        # The channel's best day is its biggest single log -- the figure the leaderboard
        # and the records email show -- not a day's posts added together, which is what
        # plank_duration holds and what personal bests are judged on.
        biggest = {id(r): int(max(split_numbers(r.get("total")) or [0])) for r in rows}
        day = max(biggest.values() or [0])
        holder = next((r.get("name") for r in rows if biggest[id(r)] == day and day), "")
        day_holder_id = next((r.get("id") for r in rows
                              if biggest[id(r)] == day and day), "")
        best_set = max([int(r.get("personal_best_single_set") or 0) for r in rows] or [0])
        set_holder = next((r.get("name") for r in rows
                           if int(r.get("personal_best_single_set") or 0) == best_set
                           and best_set), "")

        # One entry per person. A duplicate row would otherwise put someone on
        # the board twice and split their total across both.
        by_person = {}
        for r in rows:
            uid = r.get("id") or ""
            entry = by_person.setdefault(
                uid, {"id": uid, "name": r.get("name") or "", "total": 0})
            entry["total"] += int(sum(split_numbers(r.get("total"))))
        standings = sorted(by_person.values(), key=lambda e: -e["total"])

        return {"day": day, "set": best_set, "holder": holder,
                "day_holder_id": day_holder_id, "set_holder": set_holder,
                "people": len(rows), "standings": standings}

    def _document(self, fields, parts_before=1):
        """Field UUIDs are addressed as $uuid; resolved here and nowhere else.

        `total` is the whole session list and is cut across TOTAL_COLUMNS here.
        `parts_before` is how many of those columns the row used until now, so a column the
        list no longer reaches is cleared instead of left holding stale sessions.
        """
        document = {}
        for name, value in fields.items():
            if name == "total":
                pieces, dropped = split_sessions(value)
                if dropped:
                    self.errors.append(
                        "total: {} oldest session(s) dropped, the list is past {:,} characters".format(
                            dropped, TOTAL_CAPACITY))
                for index in range(max(len(pieces), parts_before)):
                    document["$" + COLUMNS[TOTAL_COLUMNS[index]]] = (
                        pieces[index] if index < len(pieces) else "")
                continue
            uuid = COLUMNS.get(name)
            if uuid is None:
                self.errors.append("write: unknown column " + name)
                continue
            document["$" + uuid] = coerce_value(name, value)
        return document

    def create(self, fields):
        body, error = _send_json(TABLE_RECORDS_URL, self.headers,
                                 {"document": self._document(fields)}, "POST")
        if error:
            self.errors.append("table.create " + error)
            return False
        self.written += 1
        return True

    def update(self, record_id, fields, parts_before=1):
        if not record_id:
            self.errors.append("table.update called without a $record_id")
            return False
        body, error = _send_json(TABLE_RECORD_URL.format(record_id), self.headers,
                                 {"document": self._document(fields, parts_before)}, "PUT")
        if error:
            self.errors.append("table.update " + error)
            return False
        self.written += 1
        return True

    def write(self, row, fields):
        """Create when there is no row yet, otherwise update in place."""
        if row:
            return self.update(row.get("$record_id"), fields,
                               parts_before=int(row.get("_total_parts") or 1))
        return self.create(fields)


class Azure(object):
    """One extraction call and one composition call per message."""

    def __init__(self, api_key, url=None):
        self.url = url or AZURE_URL
        self.headers = {"api-key": api_key, "Content-Type": "application/json"}
        self.calls = 0
        self.errors = []

    def chat(self, system, user, json_mode=False, temperature=0.7, max_tokens=700):
        payload = {
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if temperature > 0.5:
            # Nudges repeat scenarios away from converging on one phrasing.
            payload["presence_penalty"] = 0.6
            payload["frequency_penalty"] = 0.3
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body, error = _post_json(self.url, self.headers, payload)
        self.calls += 1
        if error:
            self.errors.append("azure " + error)
            return None
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            self.errors.append("azure: unexpected response shape")
            return None


# --------------------------------------------------------------------------
# Extraction -- one call covers every activity in the message
# --------------------------------------------------------------------------

EXTRACT_SYSTEM = (
    "You extract activity counts from Slack messages in a workplace wellness "
    "channel. You return JSON only, no prose.\n\n"
    "A message may log one day or several. Return one entry per day mentioned, "
    "each with:\n"
    "  day          when it was done, exactly as the message says it: 'today', "
    "'yesterday', a weekday name like 'monday', or an ISO date. Use 'today' "
    "when no day is stated.\n"
    "  total        the total for that day\n"
    "  max_per_set  the largest single set or attempt within that day\n\n"
    "Rules:\n"
    "- One entry per day. Do not merge two days into one, and do not split one "
    "day into two.\n"
    "- If no count is given for an activity, return an empty entries list.\n"
    "- Convert words to digits: 'ten' -> 10.\n"
    "- Resolve arithmetic to the total: '5 sets of 10' -> total 50, "
    "max_per_set 10. '15 + 15 + 10' -> total 40, max_per_set 15.\n"
    "- A set breakdown gives BOTH numbers. '3 sets 12 reps' and '3 sets of 12' "
    "and '3x12' all mean total 36 with max_per_set 12 -- never max_per_set 36. "
    "max_per_set is the largest SINGLE set, not the day's total.\n"
    "- A RANGE is one uncertain amount, never two to be added. '40-50 reps', "
    "'40 to 50', 'somewhere between 40 and 50' all mean a single session of "
    "roughly that size: take the LOWER bound, so 40. Adding them to 90 is "
    "always wrong.\n"
    "- Convert obvious units: '1 hour' -> 60 when the unit is minutes. If a "
    "conversion is not obvious, ignore that number rather than guessing.\n"
    "- If only one figure is given for a day, max_per_set equals total.\n"
    "- If the activity word is used in a non-exercise sense ('pushed up a "
    "shelf', 'swam in paperwork', 'read the room'), return no entries.\n"
    "- A count written in words IS a count. Convert it: 'ninety seconds' -> "
    "90, 'half an hour' -> 30 minutes, 'an hour' -> 60 minutes, 'a couple of "
    "minutes' -> 2, 'twenty' -> 20. Never return empty just because the number "
    "was spelled out rather than typed as a digit.\n"
    "- Never invent a count that is not there at all. A bare trigger with only "
    "emoji or punctuation -- 'iplanked :muscle:', 'ipushup!' -- has NO count "
    "and no quantity word either. Return an empty entries list for those, and "
    "never fall back to a typical value for the activity.\n"
    "- Do not resolve dates yourself. Report the day as written; the caller "
    "turns it into a real date."
)


# Spelled-out quantities, so "iplanked for half an hour" still counts as
# carrying a number even though it has no digits.
NUMBER_WORDS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "dozen",
    "half", "quarter", "an hour", "a hour", "a minute", "a min", "a lap",
    "a mile", "a km", "a page", "a rep", "a set",
)


def carries_a_number(text):
    """Whether the message could possibly contain a count.

    A model asked to read "iplanked :muscle:" will happily supply 60, because
    that is the commonest plank. No digits and no number words means there is
    no count to find, and no amount of prompting makes that safe to infer.
    """
    lowered = str(text or "").lower()
    if re.search(r"\d", lowered):
        return True
    return any(word in lowered for word in NUMBER_WORDS)


def _extract_once(llm, text, keywords, insist=False):
    """One extraction call. Returns {keyword: [entry, ...]} or None on failure."""
    spec = []
    for key in keywords:
        a = ACTIVITIES[key]
        spec.append('  "{}": {} measured in {} (synonyms: {})'.format(
            key, a["name"], a["unit_plural"], a["synonyms"]))

    user = ("Message:\n{}\n\nActivities to extract:\n{}\n\n"
            "Return JSON shaped exactly like:\n"
            '{{"{}": {{"entries": [{{"day": "today", "total": 0, '
            '"max_per_set": 0}}]}}}}'.format(text, "\n".join(spec), keywords[0]))

    if insist:
        user += ("\n\nYour previous attempt returned nothing. This message DOES "
                 "contain a quantity -- it may be written in words rather than "
                 "digits, for example 'half an hour', 'ninety seconds', 'a "
                 "couple of minutes'. Read it and convert it to the unit above. "
                 "Only return empty if there is genuinely no amount of any kind.")

    # One entry per day, about 40 tokens each: a three-week catch-up is more than 700.
    lines = len([l for l in str(text).splitlines() if l.strip()])
    reply = llm.chat(EXTRACT_SYSTEM, user, json_mode=True, temperature=0,
                     max_tokens=min(3000, max(700, 200 + 50 * lines)))
    if not reply:
        return None
    try:
        parsed = json.loads(reply)
    except ValueError:
        llm.errors.append("extract: reply was not JSON")
        return None

    out = {}
    for key in keywords:
        node = parsed.get(key) or parsed.get(key.lower()) or {}
        raw = node.get("entries") if isinstance(node, dict) else node
        entries = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            total = correct_range_sum(text, _num(item.get("total")))
            per_set = _num(item.get("max_per_set")) or total
            total, per_set = correct_sets(text, total, per_set)
            if total <= 0:
                continue
            entries.append({"day": str(item.get("day") or "today"),
                            "total": total,
                            # A set can never exceed the day it belongs to.
                            "max_per_set": min(per_set, total)})
        out[key] = entries
    return out


def extract_counts(llm, text, keywords, attempts=EXTRACT_ATTEMPTS):
    """{keyword: [{"day": str, "total": n, "max_per_set": n}, ...]}

    Retries only when EVERY activity came back empty while the message plainly
    contains a number -- the one failure that silently refuses a real session.
    A message where some activities have counts and others do not is normal and
    is accepted first time.
    """
    blank = {k: [] for k in keywords}

    # Nothing numeric in the message, so nothing to extract. Skips the call too.
    if not carries_a_number(text):
        return blank, True

    seen, result = [], None
    for attempt in range(max(1, attempts)):
        parsed = _extract_once(llm, text, keywords, insist=attempt > 0)
        if parsed is None:
            continue
        seen.append(parsed)
        if any(parsed[k] for k in keywords):
            # Two attempts that agree are worth more than one that did not.
            result = parsed
            break
        if attempt + 1 < max(1, attempts):
            llm.errors.append(
                "extract: attempt {} found nothing in a message that has a "
                "number; retrying".format(attempt + 1))

    if result is None:
        result = seen[-1] if seen else dict(blank)

    # Last line of defence: read the words ourselves.
    for key in keywords:
        if not result.get(key):
            spelled = parse_spelled_amount(text, ACTIVITIES[key]["unit_plural"])
            if spelled > 0:
                result[key] = [{"day": "today", "total": spelled,
                                "max_per_set": spelled}]
                llm.errors.append(
                    "extract: {} attempts missed a spelled-out amount for {}; "
                    "read {} from the text".format(len(seen), key, spelled))

    return result, bool(seen)


def confirm_amount(llm, text, keyword, claimed):
    """Second opinion on a value that would take a channel record.

    Returns the confirmed number, or 0 if the second read disagrees. Only ever
    called for record-breaking claims, so it costs nothing on a normal day.
    """
    a = ACTIVITIES[keyword]
    system = ("You verify a single number extracted from a Slack message. "
              "Reply with JSON only: {\"total\": <number>}. Return the total "
              "for the named activity, in the named unit. If the message does "
              "not support the number, return your own reading. Never guess.")
    user = ("Message:\n{}\n\nActivity: {} measured in {}\n"
            "A first pass read the total as {}. Read it yourself and report "
            "the total.".format(text, a["name"], a["unit_plural"], claimed))
    reply = llm.chat(system, user, json_mode=True, temperature=0, max_tokens=80)
    if not reply:
        return claimed          # cannot verify; do not block the log
    try:
        second = _num((json.loads(reply) or {}).get("total"))
    except (ValueError, AttributeError):
        return claimed
    # No usable second reading is "cannot verify", not "disagrees". Only a real
    # competing number withholds the record; anything else lets it stand.
    if second <= 0 or second == claimed:
        return claimed
    llm.errors.append(
        "confirm: {} read as {} on the first pass and {} on the second; "
        "the record was not awarded".format(keyword, claimed, second))
    return 0


WORD_VALUES = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100, "couple": 2, "few": 3,
}
UNIT_SECONDS = {"hour": 3600, "hours": 3600, "minute": 60, "minutes": 60,
                "min": 60, "mins": 60, "second": 1, "seconds": 1, "sec": 1,
                "secs": 1}


SPELLED_ONES = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
                "couple": 2, "few": 3}
SPELLED_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
                "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SPELLED_SCALE = {"hundred": 100, "thousand": 1000, "dozen": 12}


def spelled_number(text):
    """The largest number written in words: "one hundred twenty" -> 120.

    Words accumulate the way they are said -- tens then units, scaled by hundred
    and thousand -- so "twenty five" is 25 rather than the 20 a single-word
    lookup returns. A bare "a" or "an" only counts when a scale word follows it,
    so "did a plank" is not read as one of something.
    """
    tokens = re.findall(r"[a-z]+", str(text or "").lower())
    best = total = current = 0
    live = False
    for index, token in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in ("a", "an"):
            if following in SPELLED_SCALE:
                current += 1
                live = True
                continue
        elif token in SPELLED_ONES:
            current += SPELLED_ONES[token]
            live = True
            continue
        elif token in SPELLED_TENS:
            current += SPELLED_TENS[token]
            live = True
            continue
        elif token in SPELLED_SCALE:
            scale = SPELLED_SCALE[token]
            if scale >= 1000:
                total += max(current, 1) * scale
                current = 0
            else:
                current = max(current, 1) * scale
            live = True
            continue
        if live:
            best = max(best, total + current)
        total = current = 0
        live = False
    if live:
        best = max(best, total + current)
    return best


def parse_spelled_amount(text, unit_plural):
    """A count written in words, converted to the activity's own unit.

    Insurance, not the main path: the model handles these most of the time, but
    "half an hour" coming back empty means someone's real session is refused,
    which is worse than the occasional over-read.
    """
    lowered = " " + re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower()) + " "

    if re.search(r"\bhalf(\s+an?)?\s+hour\b", lowered):
        seconds = 1800
    elif re.search(r"\bquarter(\s+of)?(\s+an?)?\s+hour\b", lowered):
        seconds = 900
    else:
        seconds = None
        tokens = lowered.split()
        for index, token in enumerate(tokens):
            if token not in UNIT_SECONDS:
                continue
            # The count is the run of number words just before the unit.
            window = tokens[max(0, index - 4):index]
            value = spelled_number(" ".join(window))
            # "for a minute", "an hour": the article is the count here.
            if not value and window and window[-1] in ("a", "an"):
                value = 1
            if value:
                seconds = value * UNIT_SECONDS[token]
                break
        if seconds is None:
            # No unit named, so the number is already in the activity's unit.
            return spelled_number(lowered)

    if unit_plural == "seconds":
        return seconds
    if unit_plural == "minutes":
        return int(round(seconds / 60.0))
    if unit_plural == "hours":
        return int(round(seconds / 3600.0))
    return 0


RANGE_PATTERN = re.compile(
    r"(\d+)\s*(?:-|–|—|to|or)\s*(\d+)", re.I)


def ranges_in(text):
    """Pairs that look like 'a range', so a sum of them can be spotted.

    "40-50 reps" is one session of roughly 40 to 50. A model that reads it as
    90 has invented half a workout, and the number goes straight into a record.
    """
    pairs = []
    for low, high in RANGE_PATTERN.findall(str(text or "")):
        low, high = int(low), int(high)
        if 0 < low < high:
            pairs.append((low, high))
    return pairs


# "3 sets of 12", "3 sets 12 reps", "3x12", "12 reps x 3 sets".
SETS_PATTERNS = (
    re.compile(r"(\d+)\s*(?:sets?|rounds?)\s*(?:of\s+)?(\d+)", re.I),
    re.compile(r"(\d+)\s*[x\u00d7]\s*(\d+)", re.I),
)
SETS_REVERSED = re.compile(
    r"(\d+)\s*(?:reps?|pushups?|pullups?|squats?)\s*(?:x|\u00d7|for|in|over)\s*"
    r"(\d+)\s*(?:sets?|rounds?)", re.I)


def parse_sets(text):
    """Every set breakdown in the message, as (sets, per_set) pairs.

    A message can carry more than one -- "ipushup 3 sets 10 reps" and
    "iplanked 3 sets 50 seconds" in the same post -- so all of them are
    returned and the caller picks the one that matches the activity's total.
    """
    found = []
    blob = str(text or "")
    for match in SETS_REVERSED.finditer(blob):
        per_set, sets = int(match.group(1)), int(match.group(2))
        if 0 < sets <= 100 and per_set > 0:
            found.append((sets, per_set))
    for pattern in SETS_PATTERNS:
        for match in pattern.finditer(blob):
            sets, per_set = int(match.group(1)), int(match.group(2))
            if 0 < sets <= 100 and per_set > 0:
                found.append((sets, per_set))
    return found


def correct_sets(text, total, per_set):
    """Trust an explicit set breakdown over whatever the model reported.

    Only a breakdown whose product matches this activity's total is used, so a
    pushup breakdown in the same message cannot rewrite the plank numbers.
    """
    for sets, each in parse_sets(text):
        if total in (sets * each, 0):
            return sets * each, each
    # A single breakdown that explains the per-set figure alone still helps.
    for sets, each in parse_sets(text):
        if per_set == sets * each:
            return total, each
    return total, min(per_set, total) if total else per_set


def correct_range_sum(text, total):
    """If the total is exactly a range added together, take the lower bound."""
    for low, high in ranges_in(text):
        if total == low + high:
            return low
    return total


def _num(value):
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------
# Composition -- the model writes prose and nothing else
# --------------------------------------------------------------------------

COACH_SYSTEM = (
    "You are Coach, the resident expert coach inside a workplace wellness Slack "
    "channel. You know plank, pushups, workouts, running, swimming, yoga, "
    "meditation and reading equally well, and you sound like whichever one "
    "you are coaching right now -- energetic for strength and endurance work, "
    "unhurried for yoga and meditation, warm and unhurried for reading.\n\n"
    "You are handed one person's real history for ONE activity: their recent "
    "sessions and personal bests, and -- for reading -- their actual message, "
    "which may or may not name a book. Look at what is actually in front of "
    "you and say ONE honest, specific thing a real coach who had just read "
    "these numbers would say. Do not reach for a stock phrase or a formula. "
    "If what you are about to write would fit almost anyone in a similar "
    "spot, that is the sign to look again at THIS person's actual numbers and "
    "find the thing that is true of them specifically.\n\n"
    "A few hard limits, not a script to follow:\n"
    "- Never invent a number, a book title, or a plot detail that was not "
    "given to you. A book's reputation or mood is safe to mention; what "
    "happens in it is not, unless you are certain and it reveals nothing.\n"
    "- Never mention their streak or days-in-a-row -- the bot's main reply "
    "already covers that, and you were not given it anyway.\n"
    "- Never treat 'more' as automatically good. Plenty of real coaching is "
    "'what you're doing is working, keep doing it' -- say that when it's true "
    "instead of manufacturing a reason to push further.\n"
    "- For yoga, meditation and reading, a bigger number is rarely the point "
    "-- only mention duration or page count if it genuinely serves what "
    "you're saying, never as the goal itself.\n\n"
    "Shape:\n"
    "- One short sentence only.\n"
    "- Aim for 14 words or fewer. Half a Slack line is better than a paragraph.\n"
    "- Do not use a two-part format or a 'Next session:' sentence.\n"
    "- Do not include a heading like Coach or Tip; the app adds that.\n"
    "- Slack mrkdwn only: *bold* is allowed, never **double asterisks**.\n\n"
    "Talk to them directly, in your own words, like a coach who actually "
    "looked at this one person's history -- not a fortune cookie, and not the "
    "same sentence you gave the last five people. No hype-stacking, no 'lock "
    "it in', no closing exclamation for its own sake, no more than one emoji."
)


def coach_digest(key, fields, session_amount=0):
    """The history a coach would actually want: recent form, not a data dump.

    Every field here is read straight off the row that was just written, so it
    is exactly the history the person themselves would see on /iprofile --
    nothing shown to the model that was not already true of their own record.
    session_amount is passed in separately because fields["current_value"] is
    the day's running total (today's posts combined), not just this one.
    """
    activity = ACTIVITIES[key]
    sessions = [int(v) for v in split_numbers(fields.get("total"))]
    recent = sessions[-COACH_HISTORY_WINDOW:]
    lines = [
        "Activity: {} (measured in {})".format(activity["name"], activity["unit_plural"]),
        "This log: {}".format(amount_text(key, int(session_amount or 0))),
        "Total sessions logged, all time: {}".format(len(sessions)),
        "Most recent sessions, oldest to newest: {}".format(
            ", ".join(amount_text(key, v) for v in recent)),
        "Best single day (a day can combine more than one log): {}".format(
            amount_text(key, int(fields.get("plank_duration") or 0))),
    ]
    # For a set-based activity the day total and the best single set are
    # different facts -- someone's best DAY of pushups can be five sets of 20,
    # while their best SINGLE set might be a lone 40. Telling the coach only
    # the day total, and calling it a "session", was exactly the conflation
    # the rest of the product went to some trouble to stop making elsewhere.
    if key in SET_BASED:
        noun = SET_NOUN.get(key, "set")
        lines.append("Largest single {} in this log: {}".format(
            noun, amount_text(key, int(fields.get("max_of_this_set") or 0))))
        lines.append("Best single {}, in one unbroken attempt: {}".format(
            noun, amount_text(key, int(fields.get("personal_best_single_set") or 0))))
    # Streak is deliberately withheld -- the bot's main reply already states
    # it, and the coach mentioning it too is the repetition that makes the
    # note feel scripted rather than looked-at.
    active_days = len(unique_days(fields.get("heatmap_dates")))
    lines.append("Distinct days active: {}".format(active_days))
    if fields.get("first_seen"):
        lines.append("Logging this since: {}".format(fields["first_seen"]))
    return "\n".join(lines)


def coach_advice(llm, key, fields, text="", session_amount=0):
    """One grounded, activity-specific note on what to do next time.

    text is the raw message, passed through so a reading log can be met with
    something about the actual book named in it -- without it the model has
    no way to know one was mentioned at all, let alone which.

    Skipped -- not asked and forced empty -- once there is not yet enough
    history to read a trend from, and silently dropped if the call itself
    fails. This is flavour on top of a working reply, never something its
    absence should break.
    """
    sessions = split_numbers(fields.get("total"))
    if len(sessions) < MIN_SESSIONS_FOR_COACHING:
        return ""
    user = ("{}\n\nTone for this activity:\n{}\n\nTheir message, for "
            "context only -- this is the only place a book title would "
            "appear: {}\n\nGive your one piece of advice for their next "
            "{} session. Focus only on {}, and ignore numbers from other "
            "activities in the same message. Keep it to one short sentence.".format(
                coach_digest(key, fields, session_amount), ACTIVITIES[key]["tone"],
                str(text or "")[:300], ACTIVITIES[key]["name"].lower(),
                ACTIVITIES[key]["name"]))
    reply = llm.chat(COACH_SYSTEM, user, temperature=0.8, max_tokens=55)
    return tidy_coach_note(reply)


COMPOSE_SYSTEM = """You are Spotter, the voice of a workplace wellness Slack channel.

A spotter is the person standing over you while you lift -- watching, counting,
ready if you need them, never doing the work for you. That is your whole
personality. You are a teammate leaning over someone's shoulder, not an app
confirming a transaction.

HOW YOU SOUND
Like a person typing quickly in Slack. Contractions. Sentence fragments are
fine. React to the specific number in front of you, not to "an activity being
logged". If something is genuinely impressive, be impressed. If it is someone's
tenth ordinary Tuesday, be warm about the ordinariness -- that is the real win.
When one Slack message logs multiple activities, acknowledge all of them in the
opening line. Do not make the second activity feel invisible just because one
activity supplied the lead scenario.

Do not open the same way twice in a row -- vary whether you lead with the
number, a reaction, or their name. A template that only swaps the number in
is the one thing you are here to not sound like.

READ WHAT THEY ACTUALLY TYPED
Their own message is handed to you below -- it is not filler, it is usually
the best material you have. A parenthetical, a joke, an excuse, "this one
nearly killed me", a kid or a pet interrupting a set -- these are specific
and human in a way no fact field is. If their message has a detail like
that, react to it directly and let it lead the line, ahead of generic tier
or streak language -- that is the single biggest tell that you actually read
what they wrote instead of just the number. If the message is just the bare
number with nothing else in it, that's fine too -- never invent a detail
that isn't there.

NEVER WRITE LIKE THIS -- these are the tells that make it sound like a machine:
  "Great job on logging your activity!"
  "Keep up the great work!"
  "You're making excellent progress."
  "Congratulations on your achievement."
  "That's a solid effort."
  "Way to go!"
  Any sentence that would fit equally well under any other number.
  Any sentence that begins by restating what they just did back at them.
  Exclamation marks stacked on nothing.

GOOD, for the feel of it:
  "60 seconds on a Monday. Respect."
  "40 reps + 2m 15s planked. You came back for more."
  "Day 7. You've got a streak worth protecting now."
  "Twice in one day?! I didn't even do that once. Unhinged, respectfully."
  "Plank 501. Reads like a real course code and you actually earned it."
  "202 seconds. The throne has a new ruler."
  "Back on the mat. No notes, no questions, glad you're here."
  "7 minutes of sitting still is harder than it sounds. Nicely done."
  "26, 25, and a 10 with a baby sitting on you for that last set -- that's
  the real personal best. *The Unbroken* indeed."

USE WHAT YOU KNOW ABOUT THEM
You are handed more than just the number: their name, the weekday, how many
distinct days they have shown up for this activity, their longest streak
ever, and how long ago they logged it for the first time. This is what
makes a reply feel like it came from someone who was actually paying
attention instead of a template with the blanks filled in. Reach for AT MOST
ONE of these, and only when it makes the line more specific to this exact
person on this exact day -- never stack two, never list them. A Friday
aside, "this is day 40 of showing up" instead of just the streak number,
their first name instead of the topic -- all fair game. Most messages still
don't need any of it; the number in front of you is often enough on its own.
This is extra texture, not extra length -- see HARD RULES below, which does
not change.

PROPORTION MATTERS MOST
Scale your reaction to THIS session's numbers, not to the label you were
handed. A tier crossing comes from a running total adding up over weeks; it
does not make an ordinary session extraordinary. If someone usually manages
200 and today did 60, that is a good steady day -- say so. Coronation
language, thrones and "legendary" are for an actual record only. You are told
how this session compares to their own best; use it.

HARD RULES
- One or two short lines. Never three.
- No emoji, ever. One is added after your last word, so any you write would double up.
- Slack mrkdwn only: *bold*, _italic_, <@USERID>. Never **double asterisks**.
- Always put a tier name in *bold* when you mention it. It is a label, and
  unbolded it reads as an ordinary phrase.
- Output the message and nothing else. No preamble, no quotes around it, no
  explanation of what you wrote or why.
- Use only the numbers you are given. Never invent a count, streak, record,
  tier, or number of days since their last log. A comeback is welcomed the
  same way whether or not you were given a specific day count -- if
  days_since_last_log is not in the facts, do not state one, estimate one,
  or round one. A vague "good to see you back" beats a specific, invented
  number every time; a made-up number is not more human, it is just wrong.
- Never shame a small number, a short session or a gap. Never imply bigger is
  more worthy. Never mention that a streak broke -- welcome the return instead.
- Never give medical or training advice.
- Match the energy you are told to use. A meditation log and a pushup PR do not
  get the same voice, and hype is not the default."""


def session_standing(count, personal_best, average, is_record):
    """How this session sits against their own history, in words.

    Without this the composer only sees a scenario label. Told a tier changed,
    it will crown someone for a routine 60 seconds -- because it has no idea
    their usual is 200.
    """
    if is_record:
        return "their best ever -- this one genuinely earns big language"
    best = int(personal_best or 0)
    if not best or not count:
        return "no history to compare against yet"
    ratio = float(count) / best
    if ratio >= 1.0:
        return "matches their best of {}".format(best)
    if ratio >= 0.85:
        return "close to their best of {} -- worth noting".format(best)
    if ratio >= 0.5:
        return ("a solid ordinary session; their best is {} -- keep the "
                "reaction proportionate".format(best))
    return ("well below their best of {} -- a steady day, not a big one. "
            "Warm and low-key, no hype".format(best))


def compose(llm, ctx):
    """The celebratory line. Falls back to a template if the model is unavailable."""
    scenario = SCENARIOS.get(ctx["outcome"], SCENARIOS["continuing"])
    brief = scenario["brief"].format(**ctx["facts"])

    facts = ctx["facts"]
    lines = ["Write the message for <@{}>.".format(ctx["user_id"]),
             "",
             "They just logged: {}.".format(
                 facts.get("logged_summary") or "{} of {}".format(
                     facts.get("logged", ""), facts.get("activity", ""))),
             "Occasion: {}".format(scenario["lead"].format(**ctx["facts"])),
             "How to handle it: {}".format(brief),
             "",
             "Tone for this activity, follow it exactly:",
             ctx["tone"],
             "",
             "Facts you may use (ignore any that are absent):"]
    for key, value in ctx["facts"].items():
        if value not in (None, "", 0, False):
            lines.append("  {} = {}".format(key, value))
    if ctx.get("records"):
        lines.append("  records broken = {}".format(", ".join(ctx["records"])))
    lines += ["", "Their own message, word for word -- look for a specific "
              "detail worth reacting to (see READ WHAT THEY ACTUALLY TYPED "
              "above): {}".format(ctx["text"][:300]),
              "",
              "It is currently {} where they are. If you greet them or refer to "
              "the time of day at all, match that -- never wish someone good "
              "morning in their evening.".format(ctx["facts"].get("their_part_of_day", "")),
              "", "Two lines maximum. No emoji."]

    reply = llm.chat(COMPOSE_SYSTEM, "\n".join(lines), temperature=1.0, max_tokens=180)
    if not reply:
        return with_response_emoji(fallback_line(ctx), ctx.get("keyword")), False

    facts = ctx["facts"]
    prose = emphasise(tidy_prose(reply), [facts.get("new_tier"), facts.get("previous_tier")])
    return with_response_emoji(prose, ctx.get("keyword")), True


def emphasise(text, terms):
    """Bold the terms that must stand out, whatever the model did.

    Asking for *bold* in the prompt works most of the time, which is not good
    enough for a tier name -- it is the one phrase in the message that means
    nothing unless it reads as a label.
    """
    out = str(text or "")
    for term in sorted({t for t in terms if t and len(t) > 2}, key=len, reverse=True):
        pattern = re.compile(r"(?<!\*)" + re.escape(term) + r"(?!\*)", re.I)
        out = pattern.sub(lambda m: "*" + m.group(0) + "*", out, count=1)
    return out


def tidy_prose(text):
    """Defensive cleanup. The model is told not to do any of this, but a stray
    preamble should never reach the channel."""
    out = str(text or "").strip()
    out = re.sub(r"^(here(?:'s| is)[^\n:]*:\s*)", "", out, flags=re.I)
    out = re.sub(r"<\/?(?:unk|invoke|antml)[^>]*>", "", out, flags=re.I)
    out = out.replace("**", "*")
    out = re.sub(r"^#{1,6}\s*", "", out, flags=re.M)
    out = re.sub(r"^[-*]\s+", "• ", out, flags=re.M)
    out = re.sub(r"<(U[A-Z0-9]{6,})>", r"<@\1>", out)
    return out.strip().strip('"').strip()


def tidy_coach_note(text):
    """Keep coach output to one compact Slack sentence."""
    out = tidy_prose(text)
    out = re.sub(r"^\s*(?:[:\w-]+\s*)?\*?(?:coach|tip)\*?\s*[-:—]\s*", "",
                 out, flags=re.I)
    out = out.replace("**", "*")
    line = " ".join(line.strip(" -") for line in out.splitlines() if line.strip())
    if not line:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", line)
    return (parts[0] if parts else line).strip()


def fallback_line(ctx):
    """Deterministic message so a post always goes out."""
    facts = ctx["facts"]
    who = "<@{}>".format(ctx["user_id"])
    name = facts.get("activity", "activity")
    amount = facts.get("logged", "")
    keyword = ctx.get("keyword") or facts.get("keyword", "")
    quiet = keyword in QUIET_VERB or ACTIVITIES.get(keyword, {}).get("family") == "stillness"
    templates = {
        "first_timer": "{who} logged their first {name} — {amount}. "
                       "You're a {name} doer now. :seedling:",
        "milestone": "{who} — day {streak} of {name}. That's a streak worth "
                     "protecting. :fire:",
        "tier_up": "{who} reached *{new_tier}* in {name}. :mortar_board:",
        "tier_up_with_milestone": "{who} reached *{new_tier}* — and that's day "
                                  "{streak} in a row. :mortar_board::fire:",
        "freeze_used": "{who} — streak freeze spent, streak intact. Clever. "
                       ":snowflake:",
        "comeback": "{who} is back on the {name}. Good to see you. :wave:",
        "double_down": "{who} logged {name} twice today. :eyes:",
        "beast_mode": "{who} — {daily_count} {name} logs today. :fire:",
        "golden": "{who} just hit a Golden {name}. Rare one. :sparkles:",
        "backfill": "{who} filled in {amount} of {name}. Streak's intact. :white_check_mark:",
        "continuing": "{who} logged {amount} of {name}. Day {streak}. :muscle:",
    }
    quiet_templates = {
        "first_timer": "{who} logged their first {name_lower} — {amount}. "
                       "Quiet start, properly counted. :seedling:",
        "milestone": "{who} — day {streak} of {name_lower}. A steady thread now. :lotus:",
        "tier_up": "{who} reached *{new_tier}* in {name_lower}. Quietly adding up. :lotus:",
        "tier_up_with_milestone": "{who} reached *{new_tier}* — and that's day "
                                  "{streak} in a row. :lotus:",
        "freeze_used": "{who} — streak freeze spent, streak intact. :snowflake:",
        "comeback": "{who} returned to {name_lower}. Good to see it. :wave:",
        "double_down": "{who} logged {name_lower} twice today. Showing up again counts.",
        "beast_mode": "{who} logged {name_lower} {daily_count} times today. Steady work.",
        "golden": "{who} just hit a Golden {name_lower}. Rare one. :sparkles:",
        "backfill": "{who} filled in {amount} of {name_lower}. Streak's intact. :white_check_mark:",
        "continuing": "{who} logged {amount} of {name_lower}. Day {streak}. :lotus:",
    }
    templates = quiet_templates if quiet else templates
    template = templates.get(ctx["outcome"], templates["continuing"])
    return template.format(who=who, name=name, amount=amount,
                           name_lower=str(name).lower(),
                           streak=facts.get("current_streak", ""),
                           new_tier=facts.get("new_tier", ""),
                           daily_count=facts.get("daily_post_count", ""))


# --------------------------------------------------------------------------
# Block Kit -- Python owns the structure, the model only supplies the prose
# --------------------------------------------------------------------------

ROW_TYPE_KEYWORD = {a["row_type"]: k for k, a in ACTIVITIES.items()}

ICONS = {
    "IPLANKED": ":plank-4:", "IPUSHUP": ":plank-3:", "ISTEPS": ":athletic_shoe:",
    "IPULLUP": ":muscle:", "ISQUAT": ":leg:", "IRUN": ":runner:",
    "ISWAM": ":swimmer:", "ISTAIRS": ":stairs:", "IDANCE": ":dancer:",
    "IYOGA": ":person_in_lotus_position:", "IMEDITATE": ":brain:",
    "ISOLITUDE": ":crescent_moon:", "IJOURNAL": ":writing_hand:",
    "IWRITE": ":lower_left_fountain_pen:",
    "IREAD": ":books:", "IPRAYANAM": ":wind_blowing_face:",
    "ICHANT": ":winter_singing:", "EYEPUSHUPS": ":eye:",
    "IHYDRATE": ":droplet:", "ISLEEP": ":sleeping:",
    "ILEARN": ":bulb:", "ICARDIO": ":heartpulse:", "IWORKOUT": ":weight_lifter:",
    "ICYCLE": ":bicyclist::skin-tone-4:",
    "ISKETCH": ":pencil2:", "IPAINT": ":art:", "IFAST": ":empty_battery:",
    "ICOLDSHOWER": ":cold_face:",
}

# The emoji that ends a reply, drawn once per post from the activity that led it. The model is
# told to write none (its own beside this one would make two), and with_response_emoji strips
# any that slip through, so a reply carries exactly one -- and a different one from day to day.
# The reaction on the person's own message is a separate thing and stays fixed: ICONS, above.
#
# Slack shortcodes without the colons: the workspace's own custom emoji where one fits the
# activity (plank-4, namaste, shiba-sleep, ...), plus Slack's standard set to bring each pool
# to 20-30. Every name was checked against the workspace emoji list and Slack's shortcode list;
# one that is in neither posts as plain ":text:", so check a new one before adding it.
RESPONSE_EMOJI = {
    "IPUSHUP": (
        "pushups", "dumbbell-lifting", "gorilla-strong", "lift_weights", "muscle-rocket",
        "coursera-muscle-rocket", "flex-right", "beast-mode", "panda_weightlift",
        "swole-pikachu", "fitness", "muscle", "fire", "boom", "zap", "rocket", "100", "trophy",
        "sports_medal", "first_place_medal", "star-struck", "raised_hands", "clap", "fist",
        "facepunch", "sweat_drops", "dash", "sunglasses", "crown", "tada",
    ),
    "IPULLUP": (
        "gorilla-strong", "flex-right", "muscle-rocket", "coursera-muscle-rocket", "beast-mode",
        "rock_climb", "mountains", "lift_weights", "panda_weightlift", "muscle", "fist",
        "facepunch", "fire", "boom", "zap", "rocket", "100", "trophy", "sports_medal",
        "first_place_medal", "star-struck", "clap", "raised_hands", "sunglasses", "mountain",
        "snow_capped_mountain", "gorilla", "eagle", "crown", "tada",
    ),
    "ISQUAT": (
        "lift_weights-1", "lift_weights-2", "dumbbells", "kettlebell", "gorilla-strong",
        "flex-right", "panda_weightlift", "beast-mode", "muscle-rocket", "swole-pikachu",
        "muscle", "leg", "fire", "boom", "zap", "100", "trophy", "sports_medal",
        "first_place_medal", "star-struck", "clap", "raised_hands", "sunglasses", "rocket",
        "chart_with_upwards_trend", "tada", "bear", "fist",
    ),
    "IWORKOUT": (
        "dumbbell", "dumbbells", "dumbbell-lifting", "kettlebell", "lift-weights",
        "lift_weights", "fitness", "pilates", "panda_weightlift", "beast-mode",
        "gorilla-strong", "flex-right", "muscle-rocket", "coach-practice", "weight_lifter",
        "muscle", "fire", "boom", "zap", "sweat_drops", "sweat_smile", "hot_face", "100",
        "trophy", "sports_medal", "clap", "raised_hands", "sunglasses", "rocket", "tada",
    ),
    "IRUN": (
        "roadrunner", "running_panda", "sonic_run", "running-homer-simpson", "coach-flash",
        "batman_running", "runner", "man-running", "woman-running", "running_shirt_with_sash",
        "athletic_shoe", "dash", "checkered_flag", "stopwatch", "sports_medal",
        "first_place_medal", "fire", "zap", "rocket", "sunrise", "leopard", "racehorse",
        "turtle", "sweat_drops", "100", "clap", "raised_hands", "tada", "sunglasses",
        "star-struck",
    ),
    "ISWAM": (
        "swim", "kirby_swim", "sea-otter", "rubberduck", "cute-duck", "waterfall", "swimmer",
        "man-swimming", "woman-swimming", "ocean", "droplet", "sweat_drops", "whale", "dolphin",
        "tropical_fish", "turtle", "octopus", "penguin", "otter", "seal", "surfer", "sailboat",
        "anchor", "sunglasses", "sunny", "sparkles", "100", "clap", "star-struck", "trophy",
    ),
    "ICARDIO": (
        "coach-sweat-smile", "blob-sweat", "heartpulse", "heartbeat", "heart", "fire", "zap",
        "dash", "sweat_drops", "sweat_smile", "hot_face", "boom", "rocket", "100", "muscle",
        "stopwatch", "runner", "rowboat", "athletic_shoe", "cyclone", "trophy", "tada", "clap",
        "raised_hands", "sunglasses", "star-struck", "droplet",
    ),
    "ICYCLE": (
        "bike", "bicyclist", "mountain_bicyclist", "man-biking", "woman-biking",
        "man-mountain-biking", "dash", "wind_blowing_face", "gear", "checkered_flag",
        "stopwatch", "sunny", "sunrise", "sunrise_over_mountains", "mountain", "national_park",
        "motorway", "world_map", "compass", "round_pushpin", "fire", "zap", "rocket", "100",
        "trophy", "sports_medal", "first_place_medal", "muscle", "clap", "raised_hands",
    ),
    "ISTEPS": (
        "emoji-walking", "woman-walk", "hiking", "shiba-walk", "walking-the-dog", "taco_walk",
        "athletic_shoe", "hiking_boot", "footprints", "walking", "man-walking", "woman-walking",
        "sunrise", "sunny", "partly_sunny", "deciduous_tree", "leaves", "fallen_leaf", "herb",
        "world_map", "compass", "round_pushpin", "mountain", "100", "tada", "clap",
        "star-struck", "rocket", "sparkles", "sunglasses",
    ),
    "ISTAIRS": (
        "rock_climb", "mountains", "hiking", "athletic_shoe", "muscle", "fire", "leg",
        "mountain", "snow_capped_mountain", "man_climbing", "woman_climbing", "arrow_up",
        "arrow_upper_right", "chart_with_upwards_trend", "top", "rocket", "100", "trophy",
        "sports_medal", "first_place_medal", "clap", "raised_hands", "star-struck",
        "sunglasses", "tada", "zap", "dash", "sweat_drops", "sweat_smile", "ladder",
    ),
    "IDANCE": (
        "dance", "dancing", "dance-bear", "dancing_penguin", "dancing_panda", "dancing_corgi",
        "dancing_dog", "dancing-hamster", "banana-dance", "blob-dance", "blob-dancer",
        "blob-salsa-dance", "disco", "disco-ball", "dancer", "man_dancing", "dancers", "tada",
        "sparkles", "musical_note", "notes", "headphones", "mirror_ball", "confetti_ball",
        "partying_face", "fire", "star-struck", "sunglasses", "guitar", "saxophone",
    ),
    "IPLANKED": (
        "plank-1", "plank-2", "plank-3", "plank-4", "plank-5", "plank-6", "plank-7", "plank-8",
        "plank-9", "plank-pose", "plank-side", "muscle", "fire", "boom", "zap", "stopwatch",
        "hourglass_flowing_sand", "timer_clock", "100", "trophy", "sports_medal",
        "first_place_medal", "clap", "raised_hands", "sunglasses", "rocket", "tada",
        "star-struck", "gorilla", "straight_ruler",
    ),
    "IYOGA": (
        "yoga-fire", "namaste", "namaste-2", "meditation-bear", "calm", "calm_pear",
        "creu-calm", "capybarachill", "chillax", "snail_slow_chill", "neutral_blob_chillin",
        "peace-gesture", "person_in_lotus_position", "woman_in_lotus_position",
        "man_in_lotus_position", "lotus", "cherry_blossom", "blossom", "hibiscus", "sunflower",
        "herb", "leaves", "seedling", "bamboo", "sunrise", "crescent_moon", "sparkles", "dizzy",
        "relieved", "relaxed",
    ),
    "IMEDITATE": (
        "meditation-bear", "namaste", "namaste-2", "calm", "calm_pear", "creu-calm",
        "capybarachill", "chillax", "think_yinyang", "gong", "snail_slow_chill",
        "neutral_blob_chillin", "person_in_lotus_position", "lotus", "relieved", "relaxed",
        "pray", "yin_yang", "dizzy", "sparkles", "crescent_moon", "new_moon_with_face",
        "night_with_stars", "candle", "bell", "herb", "leaves", "seedling", "cherry_blossom",
        "dove_of_peace",
    ),
    "ISOLITUDE": (
        "calm", "calm_pear", "capybarachill", "snail_slow_chill", "neutral_blob_chillin",
        "nightnight", "chillax", "creu-calm", "mountains", "crescent_moon",
        "new_moon_with_face", "night_with_stars", "stars", "milky_way", "tea", "coffee",
        "teapot", "candle", "books", "book", "headphones", "cloud", "ocean", "mountain",
        "snow_capped_mountain", "evergreen_tree", "deciduous_tree", "fallen_leaf", "leaves",
        "herb",
    ),
    "IJOURNAL": (
        "writing", "taking_notes", "noted", "noted-2", "cat-noted", "journal-app",
        "coach_thinks", "notebook", "notebook_with_decorative_cover", "memo", "pencil2",
        "lower_left_fountain_pen", "lower_left_ballpoint_pen", "black_nib", "book", "books",
        "open_book", "bookmark", "bookmark_tabs", "ledger", "closed_book", "orange_book",
        "blue_book", "page_with_curl", "scroll", "thought_balloon", "bulb", "sparkles",
        "seedling", "herb",
    ),
    "IWRITE": (
        "writing", "taking_notes", "noted", "giant_pencil", "coach-idea", "cat-noted",
        "noted-2", "memo", "pencil2", "lower_left_fountain_pen", "lower_left_ballpoint_pen",
        "black_nib", "notebook", "notebook_with_decorative_cover", "page_facing_up",
        "page_with_curl", "scroll", "book", "books", "closed_book", "bookmark", "writing_hand",
        "keyboard", "computer", "bulb", "thought_balloon", "sparkles", "coffee", "tea", "fire",
    ),
    "IREAD": (
        "reading", "reading-1", "library", "uki-study", "nerd-finger", "glasses", "books",
        "book", "open_book", "closed_book", "green_book", "blue_book", "orange_book",
        "notebook", "ledger", "bookmark", "bookmark_tabs", "page_facing_up", "newspaper",
        "nerd_face", "face_with_monocle", "bulb", "brain", "sparkles", "coffee", "tea",
        "candle", "star-struck", "clap", "raised_hands",
    ),
    "IPRAYANAM": (
        "calm", "calm_pear", "creu-calm", "namaste", "namaste-2", "chillax", "think_yinyang",
        "windmill", "meditation-bear", "capybarachill", "wind_blowing_face", "dash", "cloud",
        "leaves", "fallen_leaf", "herb", "seedling", "cherry_blossom", "lotus",
        "person_in_lotus_position", "relieved", "relaxed", "sparkles", "dizzy", "ocean",
        "sunrise", "crescent_moon", "butterfly", "dove_of_peace", "mountain",
    ),
    "ICHANT": (
        "winter_singing", "sing", "gong", "namaste", "namaste-2", "think_yinyang",
        "meditation-bear", "musical_note", "notes", "musical_score", "microphone", "singer",
        "headphones", "bell", "bellhop_bell", "loud_sound", "sound", "ear", "pray", "bow",
        "person_in_lotus_position", "lotus", "candle", "sparkles", "dizzy", "dove_of_peace",
        "sunrise", "crescent_moon", "stars", "cherry_blossom",
    ),
    "EYEPUSHUPS": (
        "eye", "eyes", "eyeglasses", "glasses", "eagle-eyed", "focus-time", "calm", "calm_pear",
        "chillax", "namaste", "telescope", "mag", "mag_right", "owl", "lotus", "sparkles",
        "relieved", "relaxed", "leaves", "herb", "seedling", "cherry_blossom", "sunrise",
        "sunrise_over_mountains", "mountain", "rainbow", "tea", "butterfly",
    ),
    "IHYDRATE": (
        "waterbottle", "waterfall", "waterfall-pretty", "shiba-drink", "stanley-cup",
        "meow_sip", "glass-half-full", "droplet", "sweat_drops", "potable_water",
        "cup_with_straw", "ocean", "blue_heart", "large_blue_circle", "ice_cube", "lemon",
        "cucumber", "tropical_drink", "tea", "whale", "dolphin", "fish", "turtle", "sparkles",
        "100", "clap", "raised_hands", "star-struck", "sunglasses", "tada",
    ),
    "ISLEEP": (
        "isleep", "shiba-sleep", "shiba-nap", "shiba-dreams", "axolotl-sleeping", "nightnight",
        "coach-asleep", "sleepingparrot", "yawn", "bedge", "sleeping", "zzz", "bed",
        "crescent_moon", "new_moon_with_face", "full_moon_with_face", "night_with_stars",
        "stars", "milky_way", "tea", "teapot", "couch_and_lamp", "candle", "cloud", "relieved",
        "relaxed", "sparkles", "dizzy", "sheep", "owl",
    ),
    "ILEARN": (
        "coursera-learn-and-grow", "learn-and-grow", "learners-first",
        "coursera-learners-first", "future-of-learning", "brain_gears", "galaxy_brain",
        "uki-study", "coach-idea", "coach-practice", "nerd-finger", "idea-2", "thinksmart",
        "learnathon", "bulb", "brain", "books", "book", "mortar_board", "nerd_face",
        "face_with_monocle", "mag", "microscope", "telescope", "rocket", "sparkles",
        "star-struck", "100", "clap", "raised_hands",
    ),
    "ISKETCH": (
        "meow_artist", "blob-art", "giant_pencil", "apple_pencil", "pencil2", "pencil",
        "lower_left_crayon", "lower_left_paintbrush", "lower_left_ballpoint_pen", "black_nib",
        "art", "frame_with_picture", "straight_ruler", "triangular_ruler", "memo", "notebook",
        "bulb", "sparkles", "dizzy", "star-struck", "clap", "raised_hands", "tada", "100",
        "rainbow", "cherry_blossom", "herb", "mountain", "coffee", "eyes",
    ),
    "IPAINT": (
        "paint", "bobrossparrot", "blob-art", "meow_artist", "art", "lower_left_paintbrush",
        "lower_left_crayon", "frame_with_picture", "rainbow", "sparkles", "dizzy",
        "star-struck", "clap", "raised_hands", "tada", "100", "sunflower", "rose", "tulip",
        "cherry_blossom", "hibiscus", "blossom", "ocean", "mountain", "sunrise", "city_sunset",
        "blue_heart", "heart", "yellow_heart", "orange_heart",
    ),
    "IFAST": (
        "clock", "hourglass_flowing_sand", "hourglass", "alarm_clock", "stopwatch",
        "timer_clock", "watch", "clock12", "clock6", "fork_and_knife", "herb", "leafy_green",
        "green_apple", "carrot", "cucumber", "broccoli", "avocado", "lemon", "cup_with_straw",
        "tea", "droplet", "sparkles", "100", "clap", "raised_hands", "muscle",
        "white_check_mark", "sunrise", "crescent_moon", "star-struck",
    ),
    "ICOLDSHOWER": (
        "cold-face", "cold", "freeze", "igloo", "snow", "snowman-lego-brrrrr", "shiba-shiver",
        "cold_face", "snowflake", "ice_cube", "snowman", "snowman_without_snow", "shower",
        "droplet", "sweat_drops", "cold_sweat", "zap", "boom", "muscle", "100", "clap",
        "raised_hands", "star-struck", "sunglasses", "tada", "rocket", "penguin", "polar_bear",
        "whale", "ocean",
    ),
}

_EMOJI_RUN = re.compile(
    r"[ \t]*(?:(?<!\w):[a-z0-9_+\-]+:(?!\w)"
    r"|[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u231A\u231B\u23E9-\u23F3"
    r"\uFE0F\u200D\u20E3])+", re.I)


def response_emoji(keyword, rng=random):
    """":name:" for one emoji picked at random from the activity's pool, "" if it has none."""
    pool = RESPONSE_EMOJI.get(keyword)
    return ":{}:".format(rng.choice(pool)) if pool else ""


def with_response_emoji(text, keyword, rng=random):
    """The reply with any emoji it came with taken out and exactly one put back at the end.

    Taken out, not kept: whatever the model or the fallback template reached for would sit
    beside the one chosen here, and two emoji is one more than the reply is meant to carry.
    """
    emoji = response_emoji(keyword, rng)
    if not emoji:
        return text
    bare = _EMOJI_RUN.sub("", str(text or ""))
    bare = re.sub(r"(?m)^[ \t]+|[ \t]+$", "", bare).strip()
    return "{} {}".format(bare, emoji) if bare else emoji


# What the placeholder says while the reply is being worked out, in place of a bare
# "Thinking...": a few words about the activity, drawn at random. A message logging several
# activities draws from all of their pools together. Plain words only; the ellipsis and the
# spinner are added in thinking_text.
THINKING_WORDS = {
    "IPUSHUP": ("Counting reps", "Dropping down", "Hitting the floor", "Chest to floor",
                "Pushing up", "Tallying pushups", "Locking out", "Checking form",
                "Floor time", "Arms ready"),
    "IPULLUP": ("Grabbing the bar", "Chin over bar", "Counting pullups", "Gripping tight",
                "Hanging on", "Pulling up", "Chalking hands", "Bar time", "Reaching up",
                "Tallying reps"),
    "ISQUAT": ("Sinking low", "Counting squats", "Going deep", "Driving up",
               "Below parallel", "Legs loading", "Dropping down", "Tallying squats",
               "Knees out", "Rising up"),
    "IWORKOUT": ("Lifting weights", "Racking plates", "Chalking up", "Grabbing dumbbells",
                 "Counting sets", "Loading the bar", "Hitting the gym", "Warming up",
                 "Squatting deep", "Pumping iron", "Spotting you", "Logging the session"),
    "IRUN": ("Lacing up", "Hitting the road", "Finding the pace", "Counting strides",
             "Logging the miles", "Catching breath", "Running the numbers",
             "Crossing the line", "Cooling down", "Stretching calves"),
    "ISWAM": ("Diving in", "Counting laps", "Pulling goggles on", "Making waves",
              "Touching the wall", "Drying off", "Treading water", "Kicking off",
              "Checking the lanes", "Swimming the numbers"),
    "ICARDIO": ("Heart rate up", "Catching breath", "Wiping the sweat", "Counting minutes",
                "Keeping the pace", "Finding the rhythm", "Feeling the burn", "Cooling down",
                "Checking the pulse", "Racing the clock"),
    "ICYCLE": ("Pedalling hard", "Shifting gears", "Clipping in", "Checking the tyres",
               "Counting the miles", "Riding the numbers", "Ringing the bell",
               "Coasting downhill", "Climbing the hill", "Locking the bike"),
    "ISTEPS": ("Walking it in", "Counting steps", "Tracking footprints", "Lacing up",
               "Pacing the hallway", "Taking a stroll", "Adding the steps",
               "Walking the numbers", "One step more", "Measuring strides"),
    "ISTAIRS": ("Climbing up", "Counting flights", "Taking the stairs", "Skipping the lift",
                "Step by step", "Reaching the top", "One flight more", "Heading upstairs",
                "Catching breath", "Floor by floor"),
    "IDANCE": ("Finding the beat", "Hitting the floor", "Busting a move", "Counting the beats",
               "Feeling the rhythm", "Spinning around", "Turning it up", "Grooving along",
               "Cueing the music", "Two-stepping over"),
    "IPLANKED": ("Holding steady", "Bracing the core", "Watching the clock",
                 "Counting seconds", "Staying still", "Locking in", "Holding the line",
                 "Core engaged", "Timing the hold", "Elbows down"),
    "IYOGA": ("Unrolling the mat", "Finding balance", "Breathing in", "Settling into pose",
              "Stretching out", "Holding the pose", "Grounding down", "Flowing through",
              "Easing in", "Rolling the mat"),
    "IMEDITATE": ("Sitting quietly", "Breathing slowly", "Settling in", "Finding stillness",
                  "Quieting the mind", "Letting go", "Noticing the breath", "Pausing gently",
                  "Taking a moment", "Sitting with it"),
    "ISOLITUDE": ("Taking a pause", "Enjoying the quiet", "Stepping away", "Finding quiet",
                  "Sitting with it", "Slowing down", "Taking it in", "Unplugging briefly",
                  "Breathing easy", "Noting the stillness"),
    "IJOURNAL": ("Opening the journal", "Turning a page", "Uncapping the pen",
                 "Writing it down", "Reading it back", "Noting the thoughts",
                 "Dating the entry", "Gathering thoughts", "Closing the notebook",
                 "Filling the page"),
    "IWRITE": ("Counting pages", "Turning pages", "Saving the draft", "Finding the words",
               "Sharpening the pencil", "Reading it over", "Inking the pages",
               "Polishing a sentence", "Typing it up", "Filing the draft"),
    "IREAD": ("Turning the page", "Bookmarking it", "Counting pages", "Finding the chapter",
              "Opening the book", "Reading along", "Dog-earing a page", "Shelving the book",
              "Marking the spot", "Flipping through"),
    # No "breath" here: the activity was called Breath before Pranayama, and the guards check
    # that the old name never shows anywhere in a Pranayama reply.
    "IPRAYANAM": ("Inhaling slowly", "Exhaling slowly", "Filling the lungs", "Counting the rounds",
                  "Finding the rhythm", "Pausing gently", "Holding the pause",
                  "Steadying the air", "Easing in", "Alternating nostrils"),
    "ICHANT": ("Finding the note", "Counting the mantras", "Tuning in", "Settling the voice",
               "Listening closely", "Holding the note", "Following the rhythm",
               "Counting the beads", "Humming along", "Letting it resonate"),
    "EYEPUSHUPS": ("Looking left", "Looking right", "Left and right", "Focusing near",
                   "Focusing far", "Finding the horizon", "Shifting the focus",
                   "Relaxing the gaze", "Softening the eyes", "Resting the eyes"),
    "IHYDRATE": ("Filling the glass", "Taking a sip", "Refilling the bottle",
                 "Counting glasses", "Pouring water", "Staying hydrated", "Topping up",
                 "Adding ice", "Raising a glass", "Checking the bottle"),
    "ISLEEP": ("Fluffing the pillow", "Counting sheep", "Dimming the lights",
               "Waking up slowly", "Logging the rest", "Pulling up covers",
               "Checking the alarm", "Stretching awake", "Opening the curtains",
               "Counting the hours"),
    "ILEARN": ("Opening the notes", "Taking notes", "Connecting the dots",
               "Reviewing the lesson", "Sharpening the pencil", "Raising a hand",
               "Checking the syllabus", "Highlighting key points", "Turning the page",
               "Thinking it through"),
    "ISKETCH": ("Sharpening the pencil", "Sketching lines", "Shading it in",
                "Smudging the edges", "Picking a pencil", "Finding the angle",
                "Turning the page", "Erasing a line", "Drawing it out", "Outlining shapes"),
    "IPAINT": ("Mixing colours", "Wetting the brush", "Picking a palette", "Adding a stroke",
               "Rinsing the brush", "Blending colours", "Stepping back", "Prepping the canvas",
               "Letting it dry", "Choosing a colour"),
    "IFAST": ("Watching the clock", "Counting the hours", "Closing the window",
              "Checking the timer", "Sipping water", "Tracking the window", "Brewing some tea",
              "Keeping time", "Setting the clock", "Breaking the fast"),
    "ICOLDSHOWER": ("Turning it cold", "Bracing for cold", "Stepping in", "Feeling the chill",
                    "Counting to ten", "Shaking it off", "Towelling off", "Turning the tap",
                    "Breathing through it", "Warming back up"),
}


def thinking_text(keywords, rng=random):
    """The placeholder for a message logging `keywords`: "Lacing up… :loading-2:"."""
    pool = [words for key in keywords for words in THINKING_WORDS.get(key, ())]
    if not pool:
        return THINKING_TEXT
    return "{}… {}".format(rng.choice(pool), THINKING_SPINNER)


# One reaction goes on the person's own message: the activity emoji, added the
# moment the trigger is recognised. It is a receipt -- "seen, logged" -- and it
# doubles as a health check, since a keyword post without one did not process.
# Names carry no colons; needs the reactions:write scope.
#
# A second reaction can follow the activity one, never more than one. It marks the single most
# notable thing the post did, and an ordinary log gets none: a record or a badge is worth a
# mark, a Tuesday's steps is not. Records used to get nothing, on the thinking that praise from
# a bot is worth less than a colleague's and takes the slot a teammate would have used. They
# do now; the one-reaction cap and the nothing-for-an-ordinary-log rule are what keep the
# message from filling up before anybody else has reacted.
#
# Each occasion has a small pool and one is drawn at random, skipping any name already on the
# message. Names carry no colons, as in ICONS, and were checked against the workspace emoji
# list and Slack's shortcode list.
OCCASION_REACTIONS = {
    "channel_record": ("crown", "trophy", "first_place_medal", "rocket", "boom", "star-struck"),
    "personal_record": ("trophy", "sports_medal", "chart_with_upwards_trend", "100", "tada",
                        "sparkles"),
    # Quiet activities have longest-held records, not louder ones.
    "quiet_record": ("lotus", "seedling", "cherry_blossom", "sparkles", "dizzy", "herb"),
    "badge": ("sparkles", "star2", "ribbon", "sports_medal", "gem", "tada"),
    "streak": ("fire", "zap", "100", "rocket", "boom", "star2"),
    "golden": ("star2", "dizzy", "stars", "gem", "sparkles"),
    "night": ("crescent_moon", "new_moon_with_face", "owl", "night_with_stars", "milky_way",
              "stars", "nightnight"),
    "early_morning": ("sunrise", "sunrise_over_mountains", "rooster", "alarm_clock", "coffee",
                      "sun_with_face", "city_sunrise", "goodmorning"),
}

# The poster's own clock. Narrow on purpose: a mark for every evening log would be a mark for
# most logs. Sleep and fasting are logged when they finish, so the hour says nothing about them.
NIGHT_HOURS = (23, 0, 1, 2, 3)
EARLY_HOURS = (4, 5, 6)
TIME_BLIND = {"ISLEEP", "IFAST"}


def occasion_of(logged, record_items, badge_won, hour):
    """The one thing about this post worth a reaction on the message, "" for an ordinary log.

    In order of how much it is worth: a record, a badge, a streak milestone, a golden log,
    then the hour. A first log never gets one on its own: its personal bests are withheld
    and a first_timer is not a streak milestone.
    """
    if record_items:
        lead = record_items[0]
        if str(lead["records"]["headline"]).startswith("channel"):
            return "channel_record"
        return "quiet_record" if lead["keyword"] in QUIET_VERB else "personal_record"
    if badge_won:
        return "badge"
    if any(i["scenario"] in ("milestone", "tier_up_with_milestone") for i in logged):
        return "streak"
    if any(i["golden"] for i in logged):
        return "golden"
    # A back-filled or multi-day log was not done at this hour, whatever the clock says.
    if any(i["keyword"] not in TIME_BLIND and i["scenario"] != "backfill"
           and int(i.get("days") or 1) == 1 for i in logged):
        if hour in NIGHT_HOURS:
            return "night"
        if hour in EARLY_HOURS:
            return "early_morning"
    return ""


def occasion_reaction(occasion, taken, rng=random):
    """A reaction name drawn at random from the occasion's pool, "" if there is nothing to add."""
    pool = [n for n in OCCASION_REACTIONS.get(occasion, ()) if n not in taken]
    return rng.choice(pool) if pool else ""


# Which outcome leads the message when one post logs several activities.
OUTCOME_PRIORITY = ("first_timer", "tier_up_with_milestone", "milestone",
                    "tier_up", "golden", "freeze_used", "comeback",
                    "beast_mode", "double_down", "continuing", "backfill")


def explain_unclear_date(user_id, keyword, rejected):
    """When the count was fine but the date could not be read.

    There is no limit on how far back a log can date -- someone catching up on
    a month they missed is as legitimate as someone logging yesterday. What
    still needs a human is a date written in a way nothing here recognises, or
    one that names something in the future -- those get their own, more
    accurate wording rather than sharing the "couldn't place the date" line,
    which is only true of the first kind. Asking "how many?" here is worse than
    saying nothing -- they told us how many, and being asked again reads as
    though nothing was read at all.
    """
    a = ACTIVITIES[keyword]
    days = ", ".join(str(d) for d in rejected[:3])
    if all(any(w in str(d).lower() for w in FUTURE_WORDS) for d in rejected):
        return ("Got the number, <@{}> — but {} hasn't happened yet, so there's "
                "nothing to log. Post it again once it has. :calendar:".format(
                    user_id, days))
    return ("Got the number, <@{}> — but I couldn't place the date on {}. "
            "Try a specific date like *2026-08-15*, or something like "
            "*yesterday* / *3 days ago* / *15 August*, and I'll log it for "
            "that day. :calendar:".format(user_id, days))


def explain_not_saved(user_id, keywords):
    """When the table refused the write. Saying "logged!" over a log that was
    not saved is the one thing worse than saying nothing: the streak they were
    told about is not there tomorrow."""
    names = ", ".join(str(ACTIVITIES[k]["name"]).lower() for k in keywords)
    return ("Sorry <@{}> — I read your {} but couldn't save it just now, so "
            "nothing has been logged. Post it again in a minute and I'll pick "
            "it up. :warning:".format(user_id, names))


def day_limit(keyword):
    """The most one day of this activity can plausibly add up to, in its own unit."""
    if keyword in MAX_PER_DAY:
        return MAX_PER_DAY[keyword]
    size = hour_size(keyword)                    # a duration: a day is 24 hours of it
    return 24 * size if size else DEFAULT_MAX_PER_DAY


def explain_too_long(user_id, keyword):
    """When a message is far too long to be a log, though it carries a trigger word."""
    return ("That's a long message, <@{}>, so I've taken it for a conversation and not "
            "a log, and left it alone. To log something, post just the activity and "
            "the number, like `{} 40`. :memo:".format(user_id, keyword.lower()))


def explain_too_big(user_id, keyword, amount):
    """When the number is past what one day can hold. Nothing was written."""
    return ("Hold on, <@{}> — {} in a single day is more than I can believe, so I've left "
            "it out rather than guess. If that was a slip, post it again with the right "
            "number. :thinking_face:".format(user_id, amount_text(keyword, int(amount))))


def ask_for_count(user_id, keyword, message_ts):
    """Rotate on the message ts so the same phrasing does not repeat."""
    a = ACTIVITIES[keyword]
    templates = ASK_TEMPLATES.get(a.get("family"), ASK_TEMPLATES["habit"])
    index = wording_turn(message_ts) % len(templates)
    return templates[index].format(
        user=user_id, name=str(a["name"]).lower(), unit=a["unit_plural"],
        keyword=keyword.lower())


def amount_text(keyword, count):
    a = ACTIVITIES[keyword]
    unit = a["unit_singular"] if count == 1 else a["unit_plural"]
    return "{:,} {}".format(count, unit)


def total_text(keyword, count):
    """A running total, in units a person can read.

    "2,404 seconds" is a number to decode; "40m 4s" is a fact. Only durations
    get this -- reps and steps are already legible at any size.
    """
    unit = ACTIVITIES[keyword]["unit_plural"]
    count = int(count or 0)
    if unit not in ("seconds", "minutes"):
        return amount_text(keyword, count)
    seconds = count if unit == "seconds" else count * 60
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "{}h {}m".format(hours, minutes) if minutes else "{}h".format(hours)
    if minutes:
        return "{}m {}s".format(minutes, secs) if secs else "{}m".format(minutes)
    return "{}s".format(secs)


def session_text(keyword, count):
    """A just-logged amount, compact for durations."""
    if ACTIVITIES[keyword]["unit_plural"] in ("seconds", "minutes"):
        return total_text(keyword, count)
    return amount_text(keyword, count)


def logged_phrase(item):
    """Short phrase for the top reply: '40 reps' or '2m 15s planked'."""
    key = item["keyword"]
    count = int(item["count"] or 0)
    amount = session_text(key, count)
    if key == "IPUSHUP":
        return "{:,} {}".format(count, "pushup" if count == 1 else "pushups")
    if key == "IPULLUP":
        return "{:,} {}".format(count, "pullup" if count == 1 else "pullups")
    if key == "ISQUAT":
        return "{:,} {}".format(count, "squat" if count == 1 else "squats")
    if key == "IPLANKED":
        return "{} planked".format(amount)
    if key == "ISWAM":
        return "{} swam".format(amount)
    if key == "IRUN":
        return "{} running".format(amount)
    if key == "ICYCLE":
        return "{} cycling".format(amount)
    if key == "IYOGA":
        return "{} yoga".format(amount)
    if key == "IMEDITATE":
        return "{} meditation".format(amount)
    if key == "ISKETCH":
        return "{} sketching".format(amount)
    if key == "IPAINT":
        return "{} painting".format(amount)
    if key == "IFAST":
        return "{} fasting".format(amount)
    return amount


def logged_summary(logged):
    phrases = [logged_phrase(item) for item in logged]
    if len(phrases) < 3:
        return " + ".join(phrases)
    return "{} + {}".format(", ".join(phrases[:-1]), phrases[-1])


def thread_blocks(prose, logged, thread_ts="", open_total=0, took_any=False, all_done=False):
    """One reply covering everything logged in the message.

    Tiers are deliberately absent: people do not track them and the name alone
    means nothing without the ladder. The space goes to something actionable --
    how far the next person up is.

    A weekly goal they have open is shown only on the line of the activity just logged ("70 reps
    to go on this week's 100 pushups"). Goals in activities the message did not touch are not
    mentioned: every log listing every open goal would be too much to read. Instead a button
    offers to show them, privately, on click. It is on every reply of someone who has taken a
    weekly goal on THIS WEEK (`took_any`) or has one open, whether or not any is open now: with all of
    them cleared the card still shows the week's bars, so the button is the way back to it.
    Someone who has not taken one this week -- never, or only in a week that has ended, so a new
    set starts with no button until they take one -- is not offered an empty card on every log. The line beside it says how many goals they have open in all
    (`open_total`: the ones just logged included), so it matches the card the button opens.
    Once every goal of the week is cleared (`all_done`) it says well done instead, and the
    button offers the same card to review.
    """
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": prose}}]

    lines = []
    for item in logged:
        key = item["keyword"]
        # Their running total, not what they just logged. The prose above
        # already says the session amount, and the message itself says it a
        # third time -- the space is better spent on where they now stand.
        bits = ["{}  *{}*  {}".format(
            ICONS.get(key, ""),
            ACTIVITIES[key]["name"],
            total_text(key, item["lifetime_total"]))]
        if key == "ISTEPS":
            bits.append(steps_km_text(item["lifetime_total"]))
        if item.get("days", 1) > 1:
            bits.append("{} days".format(item["days"]))
        if item.get("active_days", 0) > 0:
            bits.append("day {}".format(item["active_days"]))
        # A second log the same day is added to the first. Said, so the running figure is
        # not a surprise to somebody who typed their phone's count.
        if (int(item.get("earlier_that_day") or 0) > 0 and int(item.get("days") or 1) == 1
                and (item.get("per_day") or [{}])[0].get("day") == item.get("logged_on")):
            bits.append("{} today so far".format(total_text(key, item["best_day"])))
        # The record belongs in the thread too. It is announced separately in
        # the channel, but this reply is the one attached to their message --
        # leaving it out reads as though nothing was noticed.
        rec = item.get("records") or {}
        if rec.get("headline"):
            was = int((rec.get("previous") or {}).get(rec["headline"]) or 0)
            if key in QUIET_VERB:
                label = "{} longest {}".format(QUIET_ICON, QUIET_VERB[key][1])
            elif rec["headline"].startswith("channel"):
                label = "👑 channel record"
            else:
                label = ":trophy: personal best"
            if rec["headline"].endswith("set") and key not in QUIET_VERB:
                label += " for a " + SET_NOUN.get(key, "set")
            if was and key not in QUIET_VERB:
                label += " (was {})".format(amount_text(key, was))
            bits.append(label)

        if item["golden"]:
            bits.append(":sparkles: golden")

        # The crown already says they lead, so the words are spent on who is
        # closing in instead -- a leader has nothing to chase, only something
        # to lose. Falls back to the plain label when nobody else logs this yet.
        for state in item.get("challenges") or []:
            bits.append(challenge_chip(state["challenge"], state["standing"], key))
        # A weekly goal they accepted and have not cleared yet: how much of it is left.
        bits.extend(weekly_chips(item))

        nudge = item.get("chase")
        if nudge and nudge.get("leading"):
            if nudge.get("name") and nudge.get("gap") > 0:
                bits.append(":crown: *{}* {} behind you".format(
                    nudge["name"], amount_text(key, nudge["gap"])))
            else:
                bits.append(":crown: top of the board")
        elif nudge and nudge.get("name"):
            bits.append("{} to pass *{}*".format(
                amount_text(key, nudge["gap"]), nudge["name"]))
            # Only worth a second mention when they are genuinely close --
            # chase() already gates this to CLOSE_CHASE_RATIO. Same phrasing
            # as the "leading" chip above ("*name* X behind you") on purpose:
            # "closing in, X back" read as ambiguous next to "to pass NAME"
            # on the same line -- people couldn't tell if the second name was
            # also someone ahead. Stating "behind you" plainly removes that.
            if nudge.get("chaser_name"):
                bits.append(":eyes: *{}* {} behind you".format(
                    nudge["chaser_name"], amount_text(key, nudge["chaser_gap"])))
        lines.append("  ·  ".join(bits))

    if lines:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn", "text": "\n".join(lines)}]})
    if thread_ts and (open_total > 0 or took_any):
        blocks.append(weekly_progress_block(open_total, thread_ts, all_done=all_done))
    return blocks


def banner_block(ref=RECORD_BANNER, alt_text=RECORD_BANNER_ALT):
    """An image block for the given banner, or None if none is configured.

    Defaults to the channel-record banner; challenge_blocks() passes its own
    ref/alt_text so the two events -- a record and a challenge answered --
    can use different images.
    """
    ref = str(ref or "").strip()
    if not ref:
        return None
    if ref.startswith("http://") or ref.startswith("https://"):
        return {"type": "image", "image_url": ref, "alt_text": alt_text}
    return {"type": "image", "slack_file": {"id": ref}, "alt_text": alt_text}


def day_figure(item, kind):
    """The figure a day record was judged on: the channel's is the biggest single log, a
    personal best is the day's total."""
    if kind == "channel_day":
        return item.get("best_log", item.get("best_day"))
    return item.get("best_day")


def on_day(item, headline):
    """" on Tuesday" when the record came from a back-filled day, else "".

    Silence would imply it happened today, which is the sort of small untruth
    that makes people stop trusting the numbers.
    """
    if not headline.endswith("day"):
        return ""
    best = day_figure(item, headline)
    when = next((e["day"] for e in item.get("per_day") or []
                 if e["count"] == best), None)
    if not when or when == item.get("logged_on"):
        return ""
    try:
        parsed = datetime.strptime(when, "%Y-%m-%d")
    except ValueError:
        return ""
    return " on {}".format(parsed.strftime("%A"))


def and_join(names):
    """"a", "a and b", "a, b and c"."""
    names = list(names)
    if len(names) < 3:
        return " and ".join(names)
    return "{} and {}".format(", ".join(names[:-1]), names[-1])


def record_rank(item):
    """Strongest record first: channel over personal, then per-activity order."""
    headline = item["records"]["headline"]
    order = record_order(item["keyword"])
    return (0 if headline.startswith("channel") else 1,
            order.index(headline) if headline in order else len(order))


def same_day_note(item, headline):
    """["8,768 steps earlier today, plus 10,154 just now."] when a day record was made of
    more than one log, else []. A single day's total is the sum of everything logged that
    day; without this a record of 18,922 under a message that said 10,154 looks wrong."""
    earlier = int(item.get("earlier_that_day") or 0)
    if (not headline.endswith("day") or headline == "channel_day"
            or earlier <= 0 or int(item.get("days") or 1) != 1):
        return []
    key = item["keyword"]
    return ["The day's total adds up everything logged on it: {} earlier, plus {} just now."
            .format(amount_text(key, earlier), amount_text(key, int(item["best_day"]) - earlier))]


def record_detail(user_id, item, channel_best):
    """One activity's lines for the channel announcement, as (detail, notes)."""
    key = item["keyword"]
    headline = item["records"]["headline"]
    is_channel = headline.startswith("channel")
    # A day record is the best SINGLE day, never the message total. Back-filling
    # three days logs 41,416 steps but the best day was 16,712 -- announcing the
    # sum would credit a day that never happened.
    value = day_figure(item, headline) if headline.endswith("day") else item["max_per_set"]
    previous = int((item["records"].get("previous") or {}).get(headline) or 0)

    if key in QUIET_VERB:
        verb = QUIET_VERB[key][0]
        detail = "<@{}> {} *{}*{}.".format(
            user_id, verb, amount_text(key, value), on_day(item, headline))
        detail += (" Their longest yet — the last one was {}.".format(
            amount_text(key, previous)) if previous else " Their longest yet.")
        return detail, same_day_note(item, headline)

    detail = "<@{}> just set the {} in *{}* — *{}*{}.".format(
        user_id, record_label(headline, key), ACTIVITIES[key]["name"],
        amount_text(key, value), on_day(item, headline))
    if previous:
        detail += "\nPrevious best *{}*, beaten by *{}*.".format(
            amount_text(key, previous), amount_text(key, value - previous))

    notes = same_day_note(item, headline)
    if is_channel:
        holder = (channel_best.get("holder") if headline.endswith("day")
                  else channel_best.get("set_holder")) or ""
        if previous and holder:
            notes.append("Held by {} until now.".format(holder))
        notes.append("{} people log {}.".format(channel_best.get("people", 0),
                                                ACTIVITIES[key]["name"]))
    # Secondary records get their numbers too. "Also broke the channel record
    # for a single set" on its own says nothing about what was actually done.
    for kind in item["records"].get("also") or []:
        got = day_figure(item, kind) if kind.endswith("day") else item["max_per_set"]
        was = int((item["records"].get("previous") or {}).get(kind) or 0)
        line = "Also took the {} — *{}*".format(
            record_label(kind, key), amount_text(key, got))
        if was:
            holder = ""
            if kind.startswith("channel"):
                holder = (channel_best.get("holder") if kind.endswith("day")
                          else channel_best.get("set_holder")) or ""
            line += ", past {}{}".format(
                (holder + "'s ") if holder else "", amount_text(key, was))
        notes.append(line + ".")
    return detail, notes


def record_title(items):
    """Headline for the post. One record keeps its own voice; several share one."""
    channel = any(i["records"]["headline"].startswith("channel") for i in items)
    quiet = all(i["keyword"] in QUIET_VERB for i in items)

    if len(items) == 1:
        item = items[0]
        if quiet:
            noun = QUIET_VERB[item["keyword"]][1]
            return "{}  *{}*".format(QUIET_ICON, "The longest anyone has stayed"
                                     if channel else "A longer {}".format(noun))
        return (":crown:  *New channel record*" if channel
                else ":trophy:  *New personal best*")

    if quiet:
        return "{}  *{}*".format(QUIET_ICON, "The longest anyone has stayed"
                                 if channel else "Longer than before")
    return ":crown:  *New records*" if channel else ":trophy:  *New personal bests*"


def record_blocks(user_id, items):
    """Channel announcement covering every activity that broke a record.

    One post, not one per activity. A message that logs pushups and planks and
    beats a personal best in both is a single event and should read as one --
    announcing only the first would quietly drop the second.
    """
    items = sorted(items, key=record_rank)
    blocks = [{"type": "section",
               "text": {"type": "mrkdwn", "text": record_title(items)}}]
    for item in items:
        detail, notes = record_detail(user_id, item, item["channel_best"])
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": detail}})
        if notes:
            blocks.append({"type": "context",
                           "elements": [{"type": "mrkdwn",
                                         "text": " ".join(notes)}]})

    # The banner leads, so the record reads as an event before any words. A
    # quiet activity only earns it when BANNER_ON_QUIET says so.
    wants = any(i["records"]["headline"].startswith("channel")
                and (BANNER_ON_QUIET or i["keyword"] not in QUIET_VERB)
                for i in items)
    if wants:
        banner = banner_block()
        if banner:
            blocks.insert(0, banner)
    return blocks


def record_summary(user_id, items):
    """Notification text -- what shows before the blocks render."""
    items = sorted(items, key=record_rank)
    if len(items) == 1:
        return "<@{}> set a new {} in {}".format(
            user_id, record_label(items[0]["records"]["headline"],
                                  items[0]["keyword"]), items[0]["activity"])
    return "<@{}> set new records in {}".format(
        user_id, and_join([i["activity"] for i in items]))


def slack_user(token, user_id):
    """Timezone and real name from users.info.

    tz_offset is seconds east of UTC and already accounts for DST, so it is
    preferred over the tz name -- no timezone database needed. Falls back to the
    channel's zone if the call fails, so a Slack hiccup never blocks a log.
    """
    fallback = {"tz_offset": DEFAULT_TZ_OFFSET, "tz": "", "tz_label": "",
                "real_name": "", "ok": False}
    if not token or not user_id:
        return fallback

    url = "{}?user={}".format(SLACK_USER_URL, user_id)
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer {}".format(token)}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:                                              # noqa: BLE001
        return fallback
    if not body.get("ok"):
        return fallback

    user = body.get("user") or {}
    profile = user.get("profile") or {}
    # real_name over display_name: display names here carry pronoun suffixes
    # like "Jack Moran (He, him, and his)", which read badly on a leaderboard.
    #
    # user.get("name") is the last resort, not the first choice: for a
    # normal member it is just a short handle ("dkain"), worse than
    # real_name. But for a cross-org Slack Connect guest (is_stranger in the
    # raw payload, or a Team ID that is actually an Enterprise id -- a
    # different company's employee shared into this workspace), Slack can
    # withhold real_name/display_name from a bot token's users.info call
    # entirely, leaving both blank. Falling back to "name" there still beats
    # the alternative once this whole chain comes up empty: main() stores
    # the raw Slack ID as their name forever, which is what actually got
    # reported -- an external teammate's row permanently reading "U08A39..."
    # instead of any human-readable name at all.
    name = (profile.get("real_name") or user.get("real_name")
            or profile.get("display_name") or user.get("name") or "")
    return {
        "tz_offset": user.get("tz_offset", DEFAULT_TZ_OFFSET),
        "tz": user.get("tz") or "",
        "tz_label": user.get("tz_label") or "",
        "real_name": name.strip(),
        "ok": True,
    }


def can_post(token, channel, skip_post):
    """Whether a post is possible, and a stated reason when it is not.

    Posting used to fail silently when the channel datapill was unmapped:
    posted_thread came back false with no warning and nothing to chase.
    """
    if skip_post:
        return False, "skip_post is set"
    if not channel:
        return False, "no channel supplied -- map the trigger's channel datapill"
    if not token:
        return False, "no slack_bot_token supplied"
    return True, ""


def _slack_headers(token):
    return {"Authorization": "Bearer {}".format(token),
            "Content-Type": "application/json; charset=utf-8"}


def slack_post(token, channel, text, blocks, thread_ts=None):
    """Returns (ok, error, ts). The ts is what chat.update needs later."""
    payload = {"channel": channel, "text": text, "blocks": blocks}
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    body, error = _post_json(SLACK_POST_URL, _slack_headers(token), payload)
    if error:
        return False, error, ""
    if not body.get("ok"):
        return False, "slack: " + str(body.get("error")), ""
    return True, None, body.get("ts") or ""


def slack_update(token, channel, ts, text, blocks):
    """Edit a message in place, so the placeholder becomes the reply."""
    payload = {"channel": channel, "ts": str(ts), "text": text, "blocks": blocks}
    body, error = _send_json(SLACK_UPDATE_URL, _slack_headers(token), payload, "POST")
    if error:
        return False, error
    if not body.get("ok"):
        return False, "slack.update: " + str(body.get("error"))
    return True, None


def slack_delete(token, channel, ts):
    """Remove a placeholder that turned out to have nothing to say."""
    body, error = _send_json(SLACK_DELETE_URL, _slack_headers(token),
                             {"channel": channel, "ts": str(ts)}, "POST")
    return bool(body and body.get("ok")), error


def slack_react(token, channel, ts, name):
    """Add one reaction. An already-present reaction is not an error."""
    body, error = _send_json(SLACK_REACT_URL, _slack_headers(token),
                             {"channel": channel, "timestamp": str(ts),
                              "name": name}, "POST")
    if error:
        return False, error
    if not body.get("ok"):
        slip = str(body.get("error"))
        if slip == "already_reacted":
            return True, None
        return False, "reactions.add {}: {}".format(name, slip)
    return True, None


def react_all(token, channel, ts, names, seen, errors):
    """Add several reactions, skipping any already added this run."""
    added = []
    for name in names:
        if not name or name in seen:
            continue
        ok, error = slack_react(token, channel, ts, name)
        seen.add(name)
        if ok:
            added.append(name)
        elif error:
            errors.append(error)
    return added


def say(token, channel, ts, text, blocks, thread_ts=None):
    """Edit the placeholder if there is one, otherwise post fresh.

    If the edit fails the reply is posted as a new message instead. Returning
    the failure on its own would leave "Thinking..." sitting in the thread as
    the bot's last word -- worse than a duplicate, because it reads as the bot
    having hung.
    """
    if ts:
        ok, error = slack_update(token, channel, ts, text, blocks)
        if ok:
            return True, None, ts
        sent, post_error, new_ts = slack_post(token, channel, text, blocks,
                                              thread_ts=thread_ts)
        if sent:
            # The stale placeholder is now noise; remove it if we can.
            slack_delete(token, channel, ts)
            return True, "placeholder edit failed ({}); posted fresh".format(error), new_ts
        return False, "{}; retry also failed: {}".format(error, post_error), ts
    return slack_post(token, channel, text, blocks, thread_ts=thread_ts)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def tier_value(row, count):
    """The number the tier ladder is measured against.

    TIER_BASIS = "cumulative" reads the lifetime log, so a tier only ever
    climbs. "per_post" reproduces the recipe, where the tier reflects this
    single post and therefore moves both ways.
    """
    if TIER_BASIS == "per_post":
        return count
    prior = sum(split_numbers((row or {}).get("total"))) if row else 0
    return int(prior) + int(count)


def resolve_scenario(event):
    """Fold tier changes and golden into a single scenario name."""
    outcome = event["outcome"]
    if outcome in ("first_timer", "duplicate", "comeback", "freeze_used",
                   "double_down", "beast_mode", "backfill"):
        return outcome
    if event["tier_changed"] and outcome == "milestone":
        return "tier_up_with_milestone"
    if event["tier_changed"]:
        return "tier_up"
    if event["golden"] and outcome == "continuing":
        return "golden"
    return outcome


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    text = input.get("text") or ""
    user_id = (input.get("user_id") or "").strip()
    channel = (input.get("channel") or "").strip()
    message_ts = str(input.get("message_ts") or "").strip()
    # A reply inside a thread carries both: ts is this message, thread_ts is the
    # parent. Replies belong under the parent, so that is what we post against.
    thread_ts = str(input.get("thread_ts") or "").strip() or message_ts
    # dry_run stops table writes only -- the reply is still composed and posted,
    # so you can watch real messages land before letting it touch the data.
    dry_run = str(input.get("dry_run") or "").lower() in ("true", "1", "yes")
    skip_post = str(input.get("skip_post") or "").lower() in ("true", "1", "yes")
    enable_coach = str(input.get("enable_coach") or "").lower() in ("true", "1", "yes")
    # Badge announcements are on unless switched off: only an explicit false/0/no/off stops
    # them, so a recipe that never maps the field keeps announcing. Badges are still worked
    # out and reported (badges_earned); the channel just is not told.
    announce_badges = str(input.get("announce_badges")).strip().lower() not in (
        "false", "0", "no", "off")
    # Where a weekly challenge somebody has just cleared is told: "channel" (the default),
    # "thread" (a reply under the log that cleared it) or "off". Off is still settled, recorded
    # and reported (weekly_cleared); nobody is told.
    weekly_where = weekly_place(input.get("announce_weekly"))
    # Name and timezone always come from users.info -- one source of truth, and
    # the timezone stays correct across DST without anyone updating a field.
    user_name = user_id

    result = {
        "ok": False, "error": "", "detected": [], "logged": [], "needs_count": [],
        "outcome": "", "scenario": "", "records_broken": [],
        "thread_text": "", "channel_text": "",
        "posted_thread": False, "posted_channel": False,
        "llm_calls": 0, "llm_used": False, "skipped_duplicate": False,
        "tier_basis": TIER_BASIS, "warnings": [],
        "tz": "", "tz_offset": 0, "local_date": "", "local_time": "",
        "user_name": "", "user_id": "", "message": "", "skipped": "",
        "rows_written": 0, "would_write": [], "extract_attempts": 0,
        "channel": "", "thread_ts": "", "rejected_days": [], "stale_only": [],
        "challenges_settled": [], "challenges_open": 0, "challenges_expired": [],
        "channel_milestones": [], "personal_milestones": [], "journey_arrivals": [],
        "badges_earned": [], "badges_total": 0, "badges_announced": False,
        "weekly_cleared": [], "weekly_announced": False, "weekly_posted_in": "",
        "weekly_accepted_total": 0, "weekly_cleared_total": 0,
        "event_logs": [],
        "coach_note": "",
        "thinking_ts": "", "reactions": [],
        # Why the message got its extra reaction (see occasion_of), "" for none.
        "occasion": "",
        # chat.update / chat.delete need channel + ts. Both are returned so a
        # bad reply can be corrected without hunting for it in Slack.
        "thread_message_ts": "", "channel_message_ts": "",
        # ... and the same for the milestone posts, which are messages of their own in the
        # channel. A message that takes the channel past two milestones posts twice: the
        # first is here, and each entry of channel_milestones carries its own message_ts.
        "channel_milestone_message_ts": "", "personal_milestone_message_ts": "",
    }

    if not user_id or not message_ts:
        result["error"] = "user_id and message_ts are both required"
        return result

    allowed, reason = should_process(input)
    if not allowed:
        result["ok"] = True
        result["skipped"] = reason
        return result

    keywords = detect(text)
    result["detected"] = keywords
    if not keywords:
        result["ok"] = True
        result["warnings"].append("no activity keyword in the message")
        return result

    # Everything from here takes a few seconds. Claim the thread straight away
    # so the person can see they were heard; the reply edits this in place.
    thinking_ts = ""
    reacted = set()

    table = Table(input.get("workato_api_token") or "")
    llm = Azure(input.get("azure_api_key") or "", input.get("azure_url"))

    # Everything downstream is dated in the poster's own day, not the channel's.
    slack_token = input.get("slack_bot_token") or ""

    # A trigger word inside a long message is not a log. Said so, once, and nothing else
    # is done: no reaction, no placeholder, no read of the model, no write.
    if too_long_for_a_log(text):
        prose = explain_too_long(user_id, keywords[0])
        result.update({"ok": True, "user_id": user_id, "message": text, "channel": channel,
                       "thread_ts": thread_ts, "scenario": "too_long", "thread_text": prose,
                       "skipped": "message too long to be a log ({:,} characters)".format(
                           len(text))})
        can, why = can_post(slack_token, channel, skip_post)
        if can:
            sent, error, posted_ts = slack_post(
                slack_token, channel, prose,
                [{"type": "section", "text": {"type": "mrkdwn", "text": prose}}],
                thread_ts=thread_ts)
            result["posted_thread"], result["thread_message_ts"] = sent, posted_ts
            if error:
                result["warnings"].append(error)
        else:
            result["warnings"].append("not posting: " + why)
        return result

    who = slack_user(slack_token, user_id)
    if who["real_name"]:
        user_name = who["real_name"]
    if not who["ok"]:
        result["warnings"].append(
            "users.info unavailable; dated in the channel's zone instead")

    tz_offset = who["tz_offset"]
    today = local_today(tz_offset)
    result["user_name"] = user_name
    result["user_id"] = user_id
    result["message"] = text
    result["channel"] = channel
    result["thread_ts"] = thread_ts

    postable, why_not = can_post(slack_token, channel, skip_post)
    if not postable:
        result["warnings"].append("not posting: " + why_not)
    else:
        thinking = thinking_text(keywords)
        sent, error, thinking_ts = slack_post(
            slack_token, channel, thinking,
            [{"type": "section", "text": {"type": "mrkdwn", "text": thinking}}],
            thread_ts=thread_ts)
        result["thinking_ts"] = thinking_ts
        if error:
            result["warnings"].append("placeholder: " + error)

        # The activity reaction is instant acknowledgement -- it lands before
        # any extraction happens, so the message never looks unnoticed.
        result["reactions"] += react_all(
            slack_token, channel, message_ts,
            [ICONS.get(k, "").strip(":") for k in keywords],
            reacted, result["warnings"])
    result["tz"] = who["tz"]
    result["tz_offset"] = tz_offset
    result["local_date"] = today.isoformat()
    result["local_time"] = local_now(tz_offset).strftime("%H:%M")

    # Fixed-count keywords never need a number read out of the text, so they
    # are held back from the extractor entirely and given their count directly.
    countable_keywords = [k for k in keywords if k not in FIXED_COUNT]
    if countable_keywords:
        counts, extracted = extract_counts(llm, text, countable_keywords)
    else:
        counts, extracted = {}, True
    for key in keywords:
        if key in FIXED_COUNT:
            counts[key] = [{"day": "today", "total": FIXED_COUNT[key],
                            "max_per_set": FIXED_COUNT[key]}]
    result["llm_used"] = extracted
    if not extracted:
        result["warnings"].append("extraction failed; counts default to 0")

    # One challenge read for the whole message, filtered per activity below.
    open_challenges = table.open_challenges(user_id)

    # Everything this person has logged, in every activity, as it stands before this
    # message: the baseline a badge is measured against. A failed read just means no
    # badge is announced this time -- it never holds up the log.
    everything_of_mine = table.query({"id": {"$eq": user_id}})
    mine = [r for r in everything_of_mine if str(r.get("row_type") or "").endswith("_users")]
    joined_events = {r.get("group_id") for r in everything_of_mine
                     if r.get("row_type") == EVENT_MEMBER_ROW and r.get("group_id")
                     and (r.get("status") or "in") != "left"}
    badges_withheld = table.read_failed or any(r.get("leaderboard_optout") for r in mine)

    logged = []
    not_saved = []          # activities whose table write failed
    too_big = []            # activities whose amount is past what a day can hold
    for key in keywords:
        activity = ACTIVITIES[key]
        raw_entries = counts.get(key) or []

        # A trigger with no number is not a log. Ask, write nothing, and keep
        # the row clean rather than appending a 0 to the session history.
        if not raw_entries:
            result["needs_count"].append(key)
            continue

        row = table.row_for(activity["row_type"], user_id)
        if row is LOOKUP_FAILED:
            # Writing now would create a second row and reset their history.
            # Better to log nothing and say so than to corrupt the record.
            result["warnings"].append(
                "could not read the {} row for {} -- nothing written, ask them "
                "to repost".format(activity["name"], user_id))
            result["skipped"] = result["skipped"] or "table read failed"
            continue

        # Idempotency is checked once, up front. Inside the fold each day is
        # applied against the evolving row, so a per-entry check would misfire.
        if row and str(row.get("last_processed_ts") or "") == str(message_ts):
            result["skipped_duplicate"] = True
            continue

        entries, rejected, oversized = [], [], []
        limit = day_limit(key)
        for item in raw_entries:
            if item["total"] > limit:
                oversized.append(item["total"])
                continue
            day = resolve_day(item["day"], today)
            if day is None and not any(
                    w in str(item["day"]).lower() for w in FUTURE_WORDS):
                # The parser did not know this phrasing. Let the model read it,
                # then hold its answer to the same rules as any other date.
                day = resolve_day_with_llm(llm, item["day"], today)
            if day is None:
                rejected.append(item["day"])
                continue
            entries.append({"day": day, "total": item["total"],
                            "max_per_set": item["max_per_set"]})
        if rejected:
            result["rejected_days"].extend(
                "{}: {}".format(activity["name"], d) for d in rejected)
        if oversized:
            too_big.append({"keyword": key, "amount": max(oversized)})
            result["warnings"].append(
                "{}: {:,} in one day is past the limit of {:,}; not logged".format(
                    activity["name"], max(oversized), limit))
        if not entries:
            if oversized:
                continue                         # said below, with the amount
            # A rejected date is not a missing count. Saying "how many?" to
            # someone who told us how many is the worst of both.
            if rejected:
                result["stale_only"].append({"keyword": key, "days": rejected})
            else:
                result["needs_count"].append(key)
            continue

        ctx = {"keyword": key, "row_type": activity["row_type"],
               "user_id": user_id, "user_name": user_name,
               "message_ts": message_ts, "source": "channel"}
        fields, events, _ = fold_entries(row, entries, ctx)

        # A weekly challenge this person accepted is settled by this log, in the same write
        # that saves it. A first log has no row to have held one, so what they accepted
        # before it is looked up once. Never allowed to hold up the log itself.
        weekly = {"cleared": [], "open": [], "counts": weekly_counts((row or {}).get(WEEKLY_COLUMN))}
        try:
            waiting = (table.weekly_pending(user_id, activity["row_type"], today)
                       if not row else [])
            weekly = weekly_settle_row(row, entries, today, waiting)
            if weekly["text"] is not None:
                fields[WEEKLY_COLUMN] = weekly["text"]
        except Exception as error:                                    # noqa: BLE001
            weekly = {"cleared": [], "open": [],
                      "counts": weekly_counts((row or {}).get(WEEKLY_COLUMN))}
            result["warnings"].append("weekly challenge: {}: {}".format(
                type(error).__name__, str(error)[:200]))

        # Records are judged on the best single day, never the sum of several
        # -- three days added together is not a single-day record. day_total
        # already folds in anything logged earlier the same day (a morning
        # set plus an evening one), so a record is judged on the whole day's
        # effort, not whichever post happened to be read last.
        best = table.channel_best(activity["row_type"])
        best_day = max(e["day_total"] for e in events)
        best_log = max(e["count"] for e in events)
        best_set = max(e["max_per_set"] for e in entries)
        records = records_broken(row, best, best_day, best_set, key, best_log)

        # Someone who has opted out is not in channel_best, so measured against
        # it they would "break the channel record" on every strong day. Their
        # personal bests still count; the channel ones are not theirs to claim
        # while they are off the board.
        opted_out = bool((row or {}).get("leaderboard_optout"))
        if opted_out and (records["flags"]["channel_day"]
                          or records["flags"]["channel_set"]):
            for kind in ("channel_day", "channel_set"):
                records["flags"][kind] = False
            notable = [k for k in record_order(key) if records["flags"][k]]
            records["headline"] = notable[0] if notable else None
            records["also"] = notable[1:]
            records["any"] = bool(notable)

        # A claimed channel record gets a second read before it is believed.
        # The row still updates either way -- only the announcement is withheld.
        # Only the amount just typed in this message is checked against the
        # text -- day_total's arithmetic (this message plus whatever was
        # already logged today) is Python addition, not something the model
        # could have misread, so re-verifying it against the message would
        # fail on every accumulated day even when the extraction was right.
        if (CONFIRM_RECORDS and records["any"]
                and str(records["headline"]).startswith("channel")):
            raw_claim = max(e["total"] for e in entries)
            confirmed = confirm_amount(llm, text, key, raw_claim)
            if confirmed != raw_claim:
                result["warnings"].append(
                    "channel record for {} withheld: the two reads disagreed"
                    .format(activity["name"]))
                records = records_broken(row, best, best_day, best_set, key, best_log)
                for kind in ("channel_day", "channel_set"):
                    records["flags"][kind] = False
                notable = [k for k in RECORD_KINDS if records["flags"][k]]
                records["headline"] = notable[0] if notable else None
                records["also"] = notable[1:]
                records["any"] = bool(notable)

        if dry_run:
            result["would_write"].append(
                {"row_type": activity["row_type"],
                 "record_id": (row or {}).get("$record_id", ""),
                 "action": "update" if row else "create", "fields": fields})
        elif not table.write(row, fields):
            # Nothing was saved, so nothing was logged: no streak to celebrate,
            # no record to announce. last_processed_ts was not written either,
            # so the same message can simply be posted again.
            not_saved.append(key)
            result["skipped"] = result["skipped"] or "table write failed"
            continue

        new_total = int(sum(split_numbers(fields.get("total"))))
        nudge = chase(best.get("standings"), user_id, new_total)

        # channel_best was read before the write, so this is the channel total
        # before the log; adding what was logged gives after.
        channel_before = sum(int(e["total"]) for e in best.get("standings") or [])
        # ... unless they have opted out: their total is not in the standings,
        # so their log must not be what carries the channel past a milestone.
        channel_after = channel_before + (
            0 if opted_out else sum(e["total"] for e in entries))
        crossed = channel_crossing(
            activity["row_type"], channel_before, channel_after, keyword=key,
            people=len([e for e in best.get("standings") or [] if e["total"] > 0]))

        # The Great Walk: the channel's steps, added together, walking a route round the
        # world. Only steps count, and only the channel total -- the same before / after
        # figures the channel milestone uses, so an opted-out poster adds nothing.
        arrived = (journey_arrivals(channel_before, channel_after)
                   if key == "ISTEPS" else [])

        # Somebody's own round numbers. Their total before this message is what the row
        # held; after is what is being written. Left unannounced for anyone who has
        # opted out, as everything public about them is.
        before_total = int(sum(split_numbers((row or {}).get("total"))))
        personal = 0 if opted_out else personal_crossing(key, before_total, new_total)
        standing = session_standing(
            best_day, int((row or {}).get("plank_duration") or 0),
            None, records["any"])

        final = events[-1]
        scenario = min((resolve_scenario(e) for e in events),
                       key=lambda s: OUTCOME_PRIORITY.index(s)
                       if s in OUTCOME_PRIORITY else 99)
        total_logged = sum(e["total"] for e in entries)

        logged.append({
            "keyword": key, "activity": activity["name"],
            "count": total_logged,
            "unit": (activity["unit_singular"] if total_logged == 1
                     else activity["unit_plural"]),
            "amount": amount_text(key, total_logged),
            "days": len(entries),
            "per_day": [{"day": e["day"].isoformat(), "count": e["total"]}
                        for e in entries],
            "best_day": best_day, "best_log": best_log, "max_per_set": best_set,
            # How much of the best day's total was logged earlier that same day. A day is
            # the SUM of its logs, so a second post is added to the first, not set against
            # it -- and unless it is said, a total larger than the number just typed reads
            # as a mistake.
            "earlier_that_day": max(0, max(events, key=lambda e: e["day_total"])["day_total"]
                                    - max(events, key=lambda e: e["day_total"])["count"]),
            "outcome": final["outcome"], "scenario": scenario,
            "streak": final["streak"], "new_tier": final["new_tier"],
            "previous_tier": events[0]["previous_tier"],
            "tier_changed": any(e["tier_changed"] for e in events),
            "golden": any(e["golden"] for e in events),
            "daily_count": final["daily_count"], "gap": final["gap"],
            "chase": nudge, "lifetime_total": new_total, "standing": standing,
            "active_days": len(unique_days(fields.get("heatmap_dates"))),
            "logged_on": today.isoformat(),
            "records": records, "channel_best": best, "was_new": not row,
            "channel_total": channel_after, "channel_crossed": crossed,
            "journey_arrived": arrived[-1][2][0] if arrived else "",
            "_journey": arrived[-1] if arrived else None,
            "personal_crossed": personal,
            "lifetime_sessions": len(split_numbers(fields.get("total"))),
            "challenges": challenge_states(open_challenges, activity["row_type"],
                                           best_day, key),
            "fields": fields, "first_seen": (row or {}).get("first_seen"),
            "_weekly": weekly["cleared"], "_open": weekly["open"],
            "_counts": weekly["counts"],
        })

    # Events they have joined: this message's logs count towards each one that is open and
    # names the activity. Not on a dry run (it writes), and never allowed to hold up the reply.
    if logged and joined_events and not dry_run:
        counted, event_warnings = count_for_events(
            table, joined_events, logged, user_id, user_name, today)
        result["event_logs"] = counted
        result["warnings"].extend(event_warnings)
        if counted and postable:
            result["reactions"] += react_all(
                slack_token, channel, message_ts, [EVENT_REACTION], reacted, result["warnings"])

    if not logged:
        # Either every activity was missing its number, or the whole message
        # was a duplicate. Only the first case deserves a reply.
        if not_saved or too_big or result["needs_count"] or result["stale_only"]:
            if not_saved:
                prose = explain_not_saved(user_id, not_saved)
                result["scenario"] = "write_failed"
            elif too_big:
                prose = explain_too_big(user_id, too_big[0]["keyword"], too_big[0]["amount"])
                result["scenario"] = "implausible_amount"
            elif result["needs_count"]:
                prose = ask_for_count(user_id, result["needs_count"][0], message_ts)
                result["scenario"] = "needs_count"
            else:
                stale = result["stale_only"][0]
                prose = explain_unclear_date(user_id, stale["keyword"], stale["days"])
                result["scenario"] = "unclear_date"
            result["thread_text"] = prose
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": prose}}]
            if postable:
                sent, error, posted_ts = say(slack_token, channel, thinking_ts,
                                             prose, blocks, thread_ts=thread_ts)
                result["posted_thread"] = sent
                result["thread_message_ts"] = posted_ts
                if error:
                    result["warnings"].append(error)
        else:
            # Say why nothing was logged. "Duplicate" is only true when the
            # idempotency check actually fired; a failed read or a rejected
            # date reaches here too, and blaming a duplicate hides the cause.
            result["warnings"].append(
                "nothing to log ({})".format(
                    "duplicate message_ts" if result["skipped_duplicate"]
                    else result["skipped"] or "no usable entries"))
            # Nothing to say, so the placeholder should not linger.
            if thinking_ts and postable:
                slack_delete(slack_token, channel, thinking_ts)
                result["thinking_ts"] = ""
        result["llm_calls"] = llm.calls
        result["rows_written"] = table.written
        result["warnings"].extend(table.errors + llm.errors)
        result["ok"] = True
        return result

    # The most significant thing that happened leads the message.
    lead = min(logged, key=lambda i: OUTCOME_PRIORITY.index(i["scenario"])
               if i["scenario"] in OUTCOME_PRIORITY else 99)
    result["outcome"] = lead["outcome"]
    result["scenario"] = lead["scenario"]

    first_seen = as_date(lead.get("first_seen"))

    facts = {
        "activity": lead["activity"],
        "name": lead["activity"],
        "logged": amount_text(lead["keyword"], lead["count"]),
        "logged_summary": logged_summary(logged),
        "current_streak": lead["streak"],
        "streak": lead["streak"],
        "new_tier": lead["new_tier"],
        "previous_tier": lead["previous_tier"],
        "daily_post_count": lead["daily_count"],
        "personal_best_single_set": lead["max_per_set"],
        "days_logged": lead.get("days", 1),
        "this_session_vs_their_own_history": lead.get("standing", ""),
        "their_local_time": result["local_time"],
        "their_part_of_day": part_of_day(tz_offset),
        # Added so the composer has real texture to draw on instead of only a
        # scenario label -- a name, the weekday and some history read as a
        # person paying attention; a bare number does not.
        "their_name": user_name,
        "weekday": today.strftime("%A"),
        "longest_streak_ever": lead["fields"].get("longest_streak"),
        "total_sessions_alltime": len(split_numbers(lead["fields"].get("total"))),
        "distinct_days_active": lead.get("active_days"),
        "days_since_first_log": (today - first_seen).days if first_seen else None,
        # Only surfaced for comeback/freeze_used, where classify() has
        # already computed a real gap -- never for a routine day, where a
        # gap of 0 or 1 means nothing and would tempt the model into
        # narrating an "absence" that didn't happen.
        "days_since_last_log": (lead.get("gap")
            if lead["scenario"] in ("comeback", "freeze_used")
            and (lead.get("gap") or 0) > 0 else None),
    }
    # Qualified by activity, and only the records actually worth announcing --
    # the same list the channel post uses, so the two never disagree.
    broken = []
    for i in logged:
        rec = i["records"]
        for k in ([rec["headline"]] if rec["headline"] else []) + (rec.get("also") or []):
            broken.append("{} — {}".format(
                i["activity"], record_label(k, i["keyword"])))
    result["records_broken"] = broken

    prose, from_llm = compose(llm, {
        "outcome": lead["scenario"], "keyword": lead["keyword"],
        "user_id": user_id, "text": text,
        "tone": ACTIVITIES[lead["keyword"]]["tone"], "facts": facts,
        "records": broken,
    })
    result["thread_text"] = prose
    other_open = weekly_other_open(everything_of_mine, logged, today)
    # Their running counts of weekly challenges taken on and cleared, with what this message has
    # just written: the reply's button needs the first, the congratulation the second.
    held = {ACTIVITIES[i["keyword"]]["row_type"]: i["_counts"] for i in logged}
    (result["weekly_accepted_total"],
     result["weekly_cleared_total"]) = weekly_totals(everything_of_mine, held)
    open_total = other_open + sum(len(i.get("_open") or []) for i in logged)
    # Only someone with nothing open can have cleared the lot, so only they cost the extra read.
    accepted = (table.weekly_accepted(user_id, today)
                if open_total == 0 and result["weekly_accepted_total"] > 0 else None)
    all_done = weekly_all_done(
        everything_of_mine, [e for i in logged for e in i.get("_weekly") or []], accepted, today)
    blocks = thread_blocks(prose, logged, thread_ts=thread_ts, open_total=open_total,
                           took_any=weekly_took_this_week(everything_of_mine, logged, accepted, today),
                           all_done=bool(all_done))
    if result["rejected_days"]:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
            "_Skipped {} — couldn't place the date. Try *2026-08-15* or "
            "*3 days ago*._".format(", ".join(result["rejected_days"]))}]})
    if result["needs_count"]:
        missing = ", ".join(ACTIVITIES[k]["name"] for k in result["needs_count"])
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
            "_Saw {} too but no number — repost with the count and I'll add it._"
            .format(missing)}]})
    if not_saved:
        missing = ", ".join(ACTIVITIES[k]["name"] for k in not_saved)
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
            ":warning: _Couldn't save {} just now, so it is not logged — post it "
            "again and I'll pick it up._".format(missing)}]})
    if too_big:
        missing = ", ".join("{} ({})".format(ACTIVITIES[b["keyword"]]["name"],
                                             amount_text(b["keyword"], int(b["amount"])))
                            for b in too_big)
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
            ":thinking_face: _Left out {} — more than one day can hold. Post it again "
            "with the right number._".format(missing)}]})

    # Optional: Coach costs one extra LLM call per logged activity, so recipes
    # opt in explicitly when they want it in the Slack reply.
    if enable_coach:
        coach_lines = []
        for item in logged:
            note = coach_advice(llm, item["keyword"], item.get("fields") or {},
                                text, item["count"])
            if note:
                coach_lines.append("*{}* — {}".format(item["activity"], note))
        result["coach_note"] = "\n".join(coach_lines)
        if coach_lines:
            blocks.append({"type": "divider"})
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                "text": ":billed_cap: *Coach*\n{}".format("\n".join(coach_lines))}]})

    if postable:
        sent, error, posted_ts = say(slack_token, channel, thinking_ts,
                                     prose, blocks, thread_ts=thread_ts)
        result["posted_thread"] = sent
        result["thread_message_ts"] = posted_ts
        if error:
            result["warnings"].append(error)

    # Channel announcement only when a record actually broke -- one post
    # covering every activity that broke one.
    record_items = sorted([i for i in logged if i["records"]["any"]],
                          key=record_rank)
    if record_items:
        cblocks = record_blocks(user_id, record_items)
        ctext = record_summary(user_id, record_items)
        result["channel_text"] = ctext
        if postable:
            sent, error, posted_ts = slack_post(slack_token, channel, ctext, cblocks)
            result["posted_channel"] = sent
            result["channel_message_ts"] = posted_ts
            if error:
                result["warnings"].append(error)

    # A channel milestone crossed by this message. Posted the moment it
    # happens: the Friday summary reports where things stand, but nobody wants
    # to learn on Friday that they were the one who took us past two hours.
    for item in logged:
        if not item.get("channel_crossed"):
            continue
        blocks = crossing_blocks(item["keyword"], user_id,
                                 item["channel_crossed"], item["channel_total"])
        text = "The channel just passed {} of {}".format(
            total_text(item["keyword"], item["channel_crossed"]),
            item["activity"])
        entry = {"activity": item["activity"], "milestone": item["channel_crossed"],
                 "channel_total": item["channel_total"], "message_ts": ""}
        result["channel_milestones"].append(entry)
        if postable:
            sent, error, posted_ts = slack_post(slack_token, channel, text, blocks)
            entry["message_ts"] = posted_ts
            result["channel_milestone_message_ts"] = (
                result["channel_milestone_message_ts"] or posted_ts)
            if error:
                result["warnings"].append("milestone post: " + error)

    # An arrival on The Great Walk, the moment the channel's steps carry it there.
    for item in logged:
        if not item.get("_journey"):
            continue
        lap, index, stop = item["_journey"]
        result["journey_arrivals"].append({
            "stop": stop[0], "lap": lap, "km": round(steps_to_km(item["channel_total"]), 1)})
        if postable:
            sent, error, _ts = slack_post(
                slack_token, channel, "The channel just reached {} on {}".format(
                    stop[0], JOURNEY_NAME),
                journey_arrival_blocks(user_id, item["_journey"], item["channel_total"]))
            if error:
                result["warnings"].append("journey post: " + error)

    # Somebody's own round number -- 100, 500, 1,000 pushups, the first 10 hours of
    # yoga. One post for the message, however many they passed, and only when the
    # write went through: "logged" above already excludes a failed one.
    passed = [i for i in logged if i.get("personal_crossed")]
    if passed:
        for item in passed:
            result["personal_milestones"].append({
                "activity": item["activity"], "milestone": item["personal_crossed"],
                "lifetime_total": item["lifetime_total"]})
        if postable:
            sent, error, posted_ts = slack_post(
                slack_token, channel, personal_milestone_text(user_id, passed),
                personal_milestone_blocks(user_id, passed, message_ts, llm))
            result["personal_milestone_message_ts"] = posted_ts
            if error:
                result["warnings"].append("personal milestone post: " + error)

    # A badge this message earned. One post, however many; nothing for someone who has
    # opted out, and nothing when the read of their other rows failed. It goes in the
    # thread, under the reply posted above, not the channel: it is the person's own news,
    # and in the channel a busy day of them drowned everything else out.
    if logged and not badges_withheld:
        won, total_badges = earned_by_this_message(
            mine, with_new_days(mine, logged), today)
        result["badges_total"] = total_badges
        for badge in won:
            result["badges_earned"].append({
                "badge": badge["name"], "family": badge["family"], "about": badge["about"],
                "times": badge["times"]})
        if won and postable and announce_badges:
            sent, error, _ts = slack_post(
                slack_token, channel, badge_text(user_id, won),
                badge_blocks(user_id, won, total_badges, message_ts),
                thread_ts=thread_ts)
            if error:
                result["warnings"].append("badge post: " + error)
            else:
                result["badges_announced"] = True

    # The one reaction this post earned on the person's own message, after the badge is known
    # because a badge ranks below a record and above everything else.
    if logged and postable:
        occasion = occasion_of(logged, record_items, result["badges_announced"],
                               local_now(tz_offset).hour)
        result["occasion"] = occasion
        result["reactions"] += react_all(
            slack_token, channel, message_ts,
            [occasion_reaction(occasion, reacted)], reacted, result["warnings"])

    # Challenges settled by this message. Announced in the channel like any
    # other achievement -- a completed challenge is a result the room should
    # see, not a footnote buried in the thread it was issued from. Only marked
    # done once the post has actually gone out.
    closed_this_message = set()
    challenge_banner_ref = str(input.get("challenge_banner") or "").strip() \
        or CHALLENGE_BANNER
    for item in logged:
        for state in item.get("challenges") or []:
            if not state["settled"]:
                continue
            challenge = state["challenge"]
            blocks = challenge_blocks(challenge, item["keyword"], user_id,
                                      state["standing"],
                                      banner_ref=challenge_banner_ref)
            text = "<@{}> cleared a challenge in {}".format(
                user_id, item["activity"])
            where = challenge.get("slack_channel_id") or channel
            sent = False
            if postable and where:
                sent, error, _ts = slack_post(slack_token, where, text, blocks)
                if error:
                    result["warnings"].append("challenge post: " + error)
            if sent or dry_run:
                result["challenges_settled"].append({
                    "record_key": challenge.get("record_key") or "",
                    "activity": item["activity"],
                    "from_name": state["from_name"],
                    "target": state["target"],
                    "reached": state["standing"]["best"]})
            if sent and not dry_run:
                table.close_challenge(challenge)
                closed_this_message.add(challenge.get("record_key") or "")

    # Weekly challenges this message cleared. Told to the channel, as a settled challenge is: a
    # goal the whole room was invited to take on is a result the room should see. One post for
    # the message, however many it cleared, and nothing for someone who has opted out. The
    # entry was marked done in the same write as the log, so this is said once.
    cleared_now = [(item, entry) for item in logged for entry in item.get("_weekly") or []]
    if cleared_now:
        for item, entry in cleared_now:
            result["weekly_cleared"].append({
                "activity": item["activity"], "goal": entry.get("text") or "",
                "week": entry.get("from") or "", "announced": False})
        withheld = any(r.get("leaderboard_optout") for r in mine)
        if postable and weekly_where and not withheld:
            entries_now = [entry for _item, entry in cleared_now]
            # The last goal of their week gets the bigger post, listing the whole week.
            if all_done:
                goals = weekly_week_goals(accepted)
                text_now = weekly_final_text(user_id, goals)
                blocks_now = weekly_final_blocks(user_id, goals, result["weekly_cleared_total"])
            else:
                text_now = weekly_cleared_text(user_id, entries_now)
                blocks_now = weekly_cleared_blocks(user_id, entries_now,
                                                   result["weekly_cleared_total"])
            sent, error, _ts = slack_post(
                slack_token, channel, text_now, blocks_now,
                thread_ts=thread_ts if weekly_where == "thread" else None)
            if error:
                result["warnings"].append("weekly challenge post: " + error)
            else:
                result["weekly_announced"] = sent
                result["weekly_posted_in"] = weekly_where if sent else ""
                for done in result["weekly_cleared"]:
                    done["announced"] = bool(sent)

    # Challenges nobody could still be racing. Contest types (most_logs,
    # highest_total, daily_streak) and custom challenges have no other way to
    # close -- nothing ever compares totals or judges free text after the
    # deadline, so without this they would sit "open" forever. Checked here,
    # on whatever this person's next message happens to be, rather than on a
    # schedule: a challenge only matters to the person it is open against,
    # and they are already posting.
    #
    # A reply lands in the original announcement's own thread when source_ref
    # (the announcement's real ts, stored by challenge_announce.py at the
    # moment it posts) and slack_channel_id are both on the row -- so anyone
    # watching that thread sees it closed out, not just the two people
    # involved. Rows from before this existed have no ts to reply into, so
    # they just close silently.
    for challenge in open_challenges:
        record_key = challenge.get("record_key") or ""
        if record_key in closed_this_message:
            continue
        deadline = as_date(challenge.get("day"))
        if not (deadline and today > deadline):
            continue

        ts = challenge.get("source_ref") or ""
        where = challenge.get("slack_channel_id") or ""
        if postable and ts and where:
            _sent, error, _ts = slack_post(
                slack_token, where, "This challenge has expired.",
                [{"type": "section", "text": {"type": "mrkdwn", "text":
                  ":hourglass:  This challenge has expired."}}],
                thread_ts=ts)
            if error:
                result["warnings"].append("challenge expiry reply: " + error)

        if dry_run:
            result["challenges_expired"].append(record_key)
        elif table.close_challenge(challenge, status="expired"):
            result["challenges_expired"].append(record_key)

    result["challenges_open"] = sum(
        len(i.get("challenges") or []) for i in logged)
    result["logged"] = [{k: v for k, v in i.items()
                         if k not in ("channel_best", "challenges", "fields", "_journey",
                                      "_weekly", "_open", "_counts")}
                        for i in logged]
    result["llm_calls"] = llm.calls
    result["extract_attempts"] = max(0, llm.calls - 1)
    result["rows_written"] = table.written
    result["warnings"].extend(table.errors + llm.errors)
    result["ok"] = True
    return result


if __name__ == "__main__":
    print(json.dumps(main({
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", ""),
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "azure_api_key": os.environ.get("AZURE_API_KEY", ""),
        "text": sys.argv[1] if len(sys.argv) > 1 else "iplanked 90 and 40 ipushup",
        "user_id": sys.argv[2] if len(sys.argv) > 2 else "U038ZCDAY6P",
        "channel": os.environ.get("SLACK_CHANNEL", ""),
        "message_ts": "1787580914.789099",
        "dry_run": "true",
    }), indent=2))
