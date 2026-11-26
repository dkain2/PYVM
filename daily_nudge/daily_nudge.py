"""
Daily nudge / daily motivator for Slack.

This Workato Python step picks one activity, asks Azure OpenAI for a short
motivating Slack message, and optionally posts it directly to Slack.

Minimum useful inputs:
    azure_api_key
    slack_bot_token
    channel_id

If slack_bot_token is blank, the script still returns post_message_body so a
separate Slack action can post it.

Two kinds of nudge, picked by the activity:

    activity   One of Spotter's 27 trackers (plank, pushup, yoga, ...). The post ends with
               the exact command to log it -- `iplanked 60` -- so nobody has to remember
               the keyword. The triggers are Spotter's own (see LOG_COMMANDS).
    game       imemory, iadd, isub or imultiple. The post ends with two BUTTONS instead of
               a command: Play today's daily and Play a game. They carry the game steps' own
               values, and action ids the click recipes already let through (imath_try /
               imath_play; for iMemory imemory_daily / imemory_start, see KNOWN_ID_FOR), so
               the existing button trigger and recipe handle the click, from anyone.

Every nudge, of either kind, also ends with a "Take a break" section: a one-line suggestion
(chosen to suit the day's activity) and a button for EACH game -- iAdd, iSub, iMultiple,
iDivide, iAverage, iMemory, iMemoryImage, iMatch and iBoxBreathe -- that opens that game for
whoever presses it (see BREAKS and break_blocks). The buttons are the games' own, so their
steps handle the clicks.

The Azure prompt is told which kind it is writing, so a game nudge invites people to play
and an activity nudge invites them to log, and neither repeats the command or the buttons.
"""

import argparse
import json
import os
import random
import re
import sys
from datetime import datetime, timezone
from urllib import error as urllib_error
from urllib import request as urllib_request

AZURE_URL = (
    "https://cour-servicenow-1.openai.azure.com/openai/deployments/"
    "gpt-4o/chat/completions?api-version=2024-10-21"
)
SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
HTTP_TIMEOUT = 30

# The random pool is NOT everything defined below. Spotter has 27 trackers, but the nudge
# has only ever picked from the nine that the channel actually uses day to day, and a
# nudge about sleep or cold showers out of nowhere surprises people. So:
#   - the pool starts as those nine plus the four games (DEFAULT_ACTIVITIES, built below);
#   - the other trackers are defined in full (OPTIONAL_ACTIVITIES) and stay OFF, until they
#     are named in the `activities` input (a pool) or `activity` (one day), or added to
#     ENABLED_EXTRAS right here.
ENABLED_EXTRAS = ()                  # e.g. ("hydrate", "sleep") to put those back in the pool
DEFAULT_ACTIVITIES = None            # filled in below, once ACTIVITIES exists

ACTIVITIES = {
    "step": {
        "title": "Step Outside",
        "name": "Steps",
        "unit": "steps",
        "icon": ":athletic_shoe:",
        "action": "take a short walk",
        "proof": "Drop the count below.",
        "tone": "Warm, practical, non-competitive. Make a tiny walk feel worth doing.",
    },
    "pushup": {
        "title": "A Few Pushups",
        "name": "Pushup",
        "unit": "reps",
        "icon": ":plank-3:",
        "action": "do a small set of pushups",
        "proof": "Post the reps.",
        "tone": "Punchy and light. Respect small sets as real effort.",
    },
    "plank": {
        "title": "Recharge and Plank",
        "name": "Plank",
        "unit": "seconds",
        "icon": ":plank-4:",
        "action": "hold one plank",
        "proof": "Snap it. Drop it.",
        "tone": "Light, slightly cheeky, motivating. No guilt or shaming.",
    },
    "yoga": {
        "title": "A Small Reset",
        "name": "Yoga",
        "unit": "minutes",
        "icon": ":person_in_lotus_position:",
        "action": "take a few minutes on the mat",
        "proof": "Share the minutes.",
        "tone": "Calm and grounding. Celebrate showing up, not flexibility.",
    },
    "meditate": {
        "title": "A Quiet Minute",
        "name": "Meditation",
        "unit": "minutes",
        "icon": ":brain:",
        "action": "sit quietly for a few minutes",
        "proof": "Post the minutes.",
        "tone": "Quiet, unhurried, almost hushed. No hype words.",
    },
    "swim": {
        "title": "Find the Water",
        "name": "Swim",
        "unit": "minutes",
        "icon": ":swimmer:",
        "action": "get in a simple swim",
        "proof": "Share minutes or laps.",
        "tone": "Fresh, steady, encouraging. Celebrate movement, not pace.",
    },
    "cardio": {
        "title": "Heart Rate Up",
        "name": "Cardio",
        "unit": "minutes",
        "icon": ":heart:",
        "action": "do a few minutes of cardio",
        "proof": "Drop the minutes.",
        "tone": "Warm endurance framing. Never compare intensity or pace.",
    },
    "read": {
        "title": "Read a Little",
        "name": "Reading",
        "unit": "pages",
        "icon": ":books:",
        "action": "read a few pages",
        "proof": "Post the pages.",
        "tone": "Calm and warm. Make a small reading session feel worthwhile.",
    },
    "workout": {
        "title": "Move Something",
        "name": "Workout",
        "unit": "minutes",
        "icon": ":muscle:",
        "action": "do a short workout",
        "proof": "Share the minutes.",
        "tone": "Energetic but not intense. Celebrate starting and finishing.",
    },
}


# More of Spotter's trackers, defined but kept OUT of the random pool (see OPTIONAL_ACTIVITIES).
# Spotter also has cycle, sleep, stairs, hydrate, learn and cold_shower; they were taken out of
# the nudge on purpose, so a post about them cannot go out. Add one back by writing its entry
# here and its command in LOG_COMMANDS (test_daily_nudge.py lists them as NOT_IN_THE_NUDGE).
ACTIVITIES.update({
    "pullup": {
        "title": "Pull Yourself Up", "name": "Pullup", "unit": "reps", "icon": ":muscle:",
        "action": "do a few pullups", "proof": "Post the reps.",
        "tone": "Plain and encouraging. One clean rep counts.",
    },
    "squat": {
        "title": "A Few Squats", "name": "Squat", "unit": "reps", "icon": ":leg:",
        "action": "do a quick set of squats", "proof": "Post the reps.",
        "tone": "Light and practical. Desk-break energy.",
    },
    "run": {
        "title": "Lace Up", "name": "Run", "unit": "minutes", "icon": ":runner:",
        "action": "go for a short run", "proof": "Share the minutes.",
        "tone": "Steady and upbeat. Never mention pace.",
    },
    "dance": {
        "title": "One Song", "name": "Dance", "unit": "minutes", "icon": ":dancer:",
        "action": "dance to one song", "proof": "Share the minutes.",
        "tone": "Fun and warm. No performance pressure.",
    },
    "solitude": {
        "title": "A Moment Alone", "name": "Solitude", "unit": "minutes", "icon": ":crescent_moon:",
        "action": "take a few quiet minutes alone", "proof": "Post the minutes.",
        "tone": "Gentle and unhurried. Quiet time is time well spent.",
    },
    "journal": {
        "title": "A Few Lines", "name": "Journaling", "unit": "minutes", "icon": ":writing_hand:",
        "action": "write a few lines in a journal", "proof": "Post the minutes.",
        "tone": "Calm and reflective. Any amount counts.",
    },
    "write": {
        "title": "Write a Page", "name": "Writing", "unit": "pages", "icon": ":lower_left_fountain_pen:",
        "action": "write a little", "proof": "Post the pages.",
        "tone": "Encouraging and practical. Progress over polish.",
    },
    "breathe": {
        "title": "A Little Pranayama", "name": "Pranayama", "unit": "minutes", "icon": ":wind_blowing_face:",
        "action": "spend a few minutes on pranayama", "proof": "Post the minutes.",
        "tone": "Soft and steady. No hype words.",
    },
    "chant": {
        "title": "A Little Chant", "name": "Chanting", "unit": "minutes", "icon": ":winter_singing:",
        "action": "chant for a few minutes", "proof": "Post the minutes.",
        "tone": "Warm, calm and respectful.",
    },
    "sketch": {
        "title": "Doodle Break", "name": "Sketching", "unit": "minutes", "icon": ":pencil2:",
        "action": "sketch for a few minutes", "proof": "Post the minutes.",
        "tone": "Playful and low-pressure. It does not have to be good.",
    },
    "paint": {
        "title": "Pick Up a Brush", "name": "Painting", "unit": "minutes", "icon": ":art:",
        "action": "paint for a little while", "proof": "Post the minutes.",
        "tone": "Relaxed and creative.",
    },
    "fast": {
        "title": "Mind the Window", "name": "Fasting", "unit": "hours", "icon": ":empty_battery:",
        "action": "keep to your eating window today", "proof": "Post the hours.",
        "tone": "Neutral and supportive. No medical claims, no pressure.",
    },
})

# The command that logs each tracker in Spotter, and a sample to copy. These are Spotter's
# own trigger keywords (the keys of ACTIVITIES in spotter.py, any case): a post that says
# `iplanked 60` is logged as 60 seconds of plank. test_daily_nudge.py checks every one
# of them against spotter.py, so a renamed or added keyword shows up as a failing test.
LOG_COMMANDS = {
    "step": ("isteps", "isteps 5000"),
    "pushup": ("ipushup", "ipushup 20"),
    "plank": ("iplanked", "iplanked 60"),
    "yoga": ("iyoga", "iyoga 15"),
    "meditate": ("imeditate", "imeditate 10"),
    "swim": ("iswam", "iswam 20"),
    "cardio": ("icardio", "icardio 20"),
    "read": ("iread", "iread 15"),
    "workout": ("iworkout", "iworkout 30"),
    "pullup": ("ipullup", "ipullup 5"),
    "squat": ("isquat", "isquat 30"),
    "run": ("irun", "irun 20"),
    "dance": ("idance", "idance 15"),
    "solitude": ("isolitude", "isolitude 10"),
    "journal": ("ijournal", "ijournal 10"),
    "write": ("iwrite", "iwrite 2"),
    "breathe": ("iprayanam", "iprayanam 5"),
    "chant": ("ichant", "ichant 10"),
    "sketch": ("isketch", "isketch 15"),
    "paint": ("ipaint", "ipaint 20"),
    "fast": ("ifast", "ifast 14"),
}
for _key, (_trigger, _example) in LOG_COMMANDS.items():
    ACTIVITIES[_key].update({"kind": "activity", "trigger": _trigger, "example": _example})

# The games. They are played with buttons, not a command, so there is no example to log.
# `buttons` is the action-id prefix of the game's step (imemory.py / imath.py), and `game`
# the key imath.py puts first in a button's value. Pressing one of the buttons is handled
# by the existing button trigger and recipe: same ids, nothing new to wire.
GAMES = {
    "imemory": {
        "title": "A Quick Memory Check", "name": "iMemory", "unit": "rounds", "icon": ":brain:",
        "action": "play a short memory game", "proof": "Pick a button below.",
        "tone": "Curious and friendly. A small challenge, not a test. No hype.",
        "pitch": "Words flash up, then vanish, and you answer what you saw. Each round adds one.",
        "buttons": "imemory", "game": "",
    },
    "iadd": {
        "title": "A Quick Sum", "name": "iAdd", "unit": "questions", "icon": ":heavy_plus_sign:",
        "action": "play a two-minute mental addition sprint", "proof": "Pick a button below.",
        "tone": "Brisk and encouraging. Make quick arithmetic feel like a warm-up.",
        "pitch": "Tap the right sum before the clock runs out. It gets harder as you go.",
        "buttons": "imath", "game": "iadd",
    },
    "isub": {
        "title": "Subtract in Your Head", "name": "iSub", "unit": "questions", "icon": ":heavy_minus_sign:",
        "action": "play a two-minute mental subtraction sprint", "proof": "Pick a button below.",
        "tone": "Brisk and encouraging. Make quick arithmetic feel like a warm-up.",
        "pitch": "Tap the right answer before the clock runs out. It gets harder as you go.",
        "buttons": "imath", "game": "isub",
    },
    "imultiple": {
        "title": "Times Tables, Warmed Up", "name": "iMultiple", "unit": "questions",
        "icon": ":heavy_multiplication_x:",
        "action": "play a two-minute mental multiplication sprint", "proof": "Pick a button below.",
        "tone": "Brisk and encouraging. Make quick arithmetic feel like a warm-up.",
        "pitch": "Tap the right product before the clock runs out. It gets harder as you go.",
        "buttons": "imath", "game": "imultiple",
    },
}
for _key, _game in GAMES.items():
    ACTIVITIES[_key] = dict(_game, kind="game", trigger=_key, example="")

# The nine the nudge always picked from, before the other trackers were defined.
CORE_ACTIVITIES = ("step", "pushup", "plank", "yoga", "meditate", "swim", "cardio", "read", "workout")
OPTIONAL_ACTIVITIES = tuple(k for k, d in ACTIVITIES.items()
                            if d["kind"] == "activity" and k not in CORE_ACTIVITIES)
DEFAULT_ACTIVITIES = list(CORE_ACTIVITIES) + list(GAMES) + [
    k for k in ENABLED_EXTRAS if k in ACTIVITIES and k not in CORE_ACTIVITIES]


# The click recipe for the memory games ("imemory - button click", recipe 82869158) lets
# through only a fixed list of action ids: imemory_yes, imemory_no, imemory_start,
# imemory_again, imemory_daily, imemory_speed_*, imemory_match_start, imemory_match_again and
# imemory_match_t0..t19. Anything else never reaches the step (no job at all), unlike imath's
# recipe, which listens for anything starting `imath_`, and ibreath's, which takes any id
# containing `ibreath_`. `imemory_play`, `imemory_play_img` and `imemory_try` are NOT on the
# list, so those buttons did nothing. The step reads the VALUE, never the id, so the nudge
# sends the same values under ids that are on the list:
#     imemory_play      -> imemory_start    (iMemory,       value anyone|0|play)
#     imemory_play_img  -> imemory_again    (iMemoryImage,  value img|anyone|0|play)
#     imemory_try       -> imemory_daily    (a game nudge's "Play today's daily", value ...|try)
# The `button_ids` input picks: "known" (default) uses those ids, "old" the previous ones.
BUTTON_IDS_MODES = ("known", "old")
BUTTON_IDS_DEFAULT = "known"
KNOWN_ID_FOR = {"imemory_play": "imemory_start", "imemory_play_img": "imemory_again",
                "imemory_try": "imemory_daily"}


def button_ids_mode(value):
    """"known" or "old": the `button_ids` input, blank = BUTTON_IDS_DEFAULT."""
    value = str(value or "").strip().lower()
    return value if value in BUTTON_IDS_MODES else BUTTON_IDS_DEFAULT


def click_id(action_id, ids=BUTTON_IDS_DEFAULT):
    """The action id to put on a button: one the click recipe lets through (see above)."""
    return KNOWN_ID_FOR.get(action_id, action_id) if ids == "known" else action_id


def game_buttons(details, ids=BUTTON_IDS_DEFAULT):
    """The two buttons on a game nudge.

    Same action ids and values the game steps already understand, so no recipe changes:
    `<prefix>_try` starts the clicker's own daily, `<prefix>_play` a free game. Anyone may
    press them, which is why the value names no player ("anyone").
    """
    prefix, key = details["buttons"], details["game"]

    def value(kind):
        head = "{}|".format(key) if key else ""
        return "{}anyone|0|{}".format(head, kind)

    return {"type": "actions", "block_id": prefix + "_nudge", "elements": [
        {"type": "button", "action_id": click_id(prefix + "_try", ids), "style": "primary",
         "text": {"type": "plain_text", "text": "Play today's daily"}, "value": value("try")},
        {"type": "button", "action_id": click_id(prefix + "_play", ids),
         "text": {"type": "plain_text", "text": "Play a game"}, "value": value("play")},
    ]}


# The "Take a break" section on every nudge: one button for EACH game, always all nine, in
# two rows (maths; memory and breathing). Every button is the game's own "anyone may press it"
# button, so the click is handled by the game's existing step, nothing new to wire:
#     imath      imath_play_<game>    value  <game>|anyone|0|play        (iadd .. idivide)
#     imemory    imemory_play         value  anyone|0|play                (words)
#                imemory_play_img     value  img|anyone|0|play            (iMemoryImage)
#                imemory_match_start  value  imatch|anyone|0|join         (iMatch's join button)
#     ibreath    ibreath_play         value  play|anyone|0                (iBoxBreathe)
# The imath ids end in the game because buttons in one row need ids of their own; the
# steps read the value, and the ids still start `imath_`, so the triggers already let them through.
#   row    which row of buttons it is in
#   mood   the kinds of day it suits best (see suggest_break)
#   ideas  one-line suggestions, one is picked per nudge
BREAKS = {
    "iadd": {
        "label": ":heavy_plus_sign: iAdd", "action_id": "imath_play_iadd",
        "value": "iadd|anyone|0|play", "row": "maths", "mood": ("move",),
        "ideas": ["Two minutes of mental addition. Faster than a coffee, and it wakes the brain up.",
                  "A quick sprint of sums. Beat yesterday's score, or just beat the clock."],
    },
    "isub": {
        "label": ":heavy_minus_sign: iSub", "action_id": "imath_play_isub",
        "value": "isub|anyone|0|play", "row": "maths", "mood": ("move",),
        "ideas": ["Subtract in your head, against the clock. Harder than it looks.",
                  "A two-minute subtraction sprint. Tap the right answer, fast."],
    },
    "imultiple": {
        "label": ":heavy_multiplication_x: iMultiple", "action_id": "imath_play_imultiple",
        "value": "imultiple|anyone|0|play", "row": "maths", "mood": ("move",),
        "ideas": ["Times tables, warmed up. How far up the ladder can you get?",
                  "Two minutes of products. Your school self would be proud."],
    },
    "idivide": {
        "label": ":heavy_division_sign: iDivide", "action_id": "imath_play_idivide",
        "value": "idivide|anyone|0|play", "row": "maths", "mood": ("move",),
        "ideas": ["Division, fast. Share it out before the clock runs out.",
                  "A quick divide sprint. It gets harder as you go."],
    },
    "iaverage": {
        "label": ":bar_chart: iAverage", "action_id": "imath_play_iaverage",
        "value": "iaverage|anyone|0|play", "row": "maths", "mood": ("move",),
        "ideas": ["Find the average in your head. Sharper than it sounds.",
                  "A quick averages sprint: tap the number that sits in the middle."],
    },
    "imemory": {
        "label": ":brain: iMemory", "action_id": "imemory_play",
        "value": "anyone|0|play", "row": "memory", "mood": ("learn",),
        "ideas": ["Words flash up, then vanish. How many rounds can you hold in your head?",
                  "Today's daily is the same for everyone, so you can compare notes after."],
    },
    "imemoryimage": {
        "label": ":frame_with_picture: iMemoryImage", "action_id": "imemory_play_img",
        "value": "img|anyone|0|play", "row": "memory", "mood": ("learn",),
        "ideas": ["Pictures flash up, then vanish. Do you remember what you saw?",
                  "A memory check with pictures instead of words."],
    },
    "imatch": {
        "label": ":mahjong: iMatch", "action_id": "imemory_match_start",
        "value": "imatch|anyone|0|join", "row": "memory", "mood": ("learn",),
        "ideas": ["Find the pairs. Memorise the board, then match every twin.",
                  "A pairs game that gets a bigger board every level."],
    },
    "iboxbreathe": {
        "label": ":wind_blowing_face: iBoxBreathe", "action_id": "ibreath_play",
        "value": "play|anyone|0", "row": "memory", "mood": ("calm",),
        "ideas": ["Two minutes of box breathing. In, hold, out, hold. Nothing else to do.",
                  "Shoulders down, screen away. Let the pattern do the counting."],
    },
}
BREAK_ROWS = ("maths", "memory")

# Which kind of break suits which activity: calm ones get breathing, writing and learning a
# memory game, the rest a maths sprint. A game nudge never suggests its own game.
CALM = ("yoga", "meditate", "solitude", "journal", "breathe", "chant", "read", "fast", "paint", "sketch")
LEARN = ("write", "learn")


def suggest_break(activity, rng=random):
    """(game key, idea) for the suggestion line: the game that suits today's activity."""
    mood = "calm" if activity in CALM else "learn" if activity in LEARN else "move"
    options = [k for k in BREAKS if k != activity]
    fits = [k for k in options if mood in BREAKS[k]["mood"]]
    key = rng.choice(fits or options)
    return key, rng.choice(BREAKS[key]["ideas"])


def break_blocks(activity, rng=random, ids=BUTTON_IDS_DEFAULT):
    """The "Take a break" section: a one-line suggestion, then a button for every game.

    The suggested game's button is the primary (green) one. Anyone may press any of them,
    so the values name no player.
    """
    suggested, idea = suggest_break(activity, rng)
    blocks = [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            "*Take a break.* Try *{}*: {}".format(
                BREAKS[suggested]["label"].split(" ", 1)[1], idea)}},
    ]
    for row in BREAK_ROWS:
        elements = []
        for key, game in BREAKS.items():
            if game["row"] != row:
                continue
            button = {"type": "button", "action_id": click_id(game["action_id"], ids),
                      "text": {"type": "plain_text", "text": game["label"], "emoji": True},
                      "value": game["value"]}
            if key == suggested:
                button["style"] = "primary"
            elements.append(button)
        blocks.append({"type": "actions", "block_id": "nudge_break_" + row, "elements": elements})
    return blocks, suggested


def _send_json(url, headers, payload, timeout=HTTP_TIMEOUT):
    data = json.dumps(payload).encode("utf-8")
    request = urllib_request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib_error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {}: {}".format(error.code, url.split("/")[2], detail)
    except Exception as error:  # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


def truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def clean_activity(value):
    return str(value or "").strip().lower().replace(" ", "_")


def split_activities(value):
    if not value:
        return []
    out = []
    for part in re.split(r"[,\\n|]+", str(value)):
        activity = clean_activity(part)
        if activity:
            out.append(activity)
    return out


def choose_activity(input_data):
    explicit = clean_activity(input_data.get("activity"))
    if explicit:
        return explicit

    candidates = split_activities(input_data.get("activities")) or list(DEFAULT_ACTIVITIES)
    known = [activity for activity in candidates if activity in ACTIVITIES]
    return random.choice(known or candidates)


def activity_details(activity, input_data):
    details = dict(ACTIVITIES.get(activity, {}))
    details.setdefault("title", activity.replace("_", " ").title())
    details.setdefault("name", activity.replace("_", " ").title())
    details.setdefault("unit", "count")
    details.setdefault("icon", "")
    details.setdefault("action", "do one small activity")
    details.setdefault("proof", "Post it below.")
    details.setdefault("tone", "Short, warm, motivating, and light.")
    details.setdefault("kind", "activity")
    details.setdefault("trigger", "")
    details.setdefault("example", "")
    details.setdefault("pitch", "")

    for field in ("title", "name", "unit", "icon", "action", "proof", "tone", "trigger", "example"):
        if input_data.get(field):
            details[field] = str(input_data[field]).strip()
    return details


def tidy_text(value, max_chars=900):
    text = str(value or "").strip()
    text = re.sub(r"^(here(?:'s| is)[^\n:]*:\s*)", "", text, flags=re.I)
    text = re.sub(r"<\/?(?:unk|invoke|antml)[^>]*>", "", text, flags=re.I)
    text = re.sub(r"\*\*([^*\n][^*]*?)\*\*", r"*\1*", text)
    text = re.sub(r"__([^_\n][^_]*?)__", r"*\1*", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars].strip()


def sentence_start(text):
    text = str(text or "").strip()
    return text[:1].upper() + text[1:] if text else text


def repeats_command(body, details):
    """True if the model wrote the log command, or told people to type something.

    The command (or the buttons) is added under the message, so a body that repeats it shows
    it twice. Only the command forms are caught: a game's name in a sentence ("try iAdd")
    is fine.
    """
    text = str(body or "").lower()
    trigger, example = details.get("trigger", "").lower(), details.get("example", "").lower()
    if example and example in text:
        return True
    if trigger and (("`" + trigger) in text or re.search(r"\btype\s+`?" + re.escape(trigger), text)):
        return True
    return False


def fallback_nudge(details, weekday):
    title = details["title"]
    if details["kind"] == "game":
        body = "*{} brain break.* {}. {}".format(
            weekday, sentence_start(details["action"]), details["pitch"] or details["proof"])
        return title, body
    body = (
        "*{} check-in.* {}.\n\n"
        "Tiny effort counts. {}"
    ).format(weekday, sentence_start(details["action"]), details["proof"])
    return title, body


class Azure(object):
    def __init__(self, api_key, url=None):
        self.api_key = api_key
        self.url = url or AZURE_URL
        self.errors = []
        self.calls = 0

    def chat(self, system, user, temperature=0.95, max_tokens=220):
        if not self.api_key:
            self.errors.append("azure_api_key is blank")
            return None

        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "presence_penalty": 0.6,
            "frequency_penalty": 0.3,
            "response_format": {"type": "json_object"},
        }
        headers = {"api-key": self.api_key, "Content-Type": "application/json"}
        body, error = _send_json(self.url, headers, payload)
        self.calls += 1
        if error:
            self.errors.append("azure " + error)
            return None
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.errors.append("azure: unexpected response shape")
            return None


def generate_nudge(llm, activity, details, weekday, channel_name=""):
    game = details["kind"] == "game"
    system = (
        "You write short daily nudges for a workplace Slack channel. "
        "Return JSON only with keys title and body. The body must be Slack mrkdwn. "
        "Slack bold uses single asterisks like *5 quick minutes*. Never use double asterisks. "
        "Be punchy, light, and motivating, and keep it workplace-appropriate: playful is fine, "
        "silly or childish is not. No setup explanation. No guilt, no shaming, "
        "no leaderboard talk, no medical claims, no hashtags, no more than one emoji. "
        "Maximum 28 words total in body. Prefer short sentences. Make every word earn its place. "
        "Never write a command, a keyword, a slash command or a button label in the body: "
        "what people tap or type is added under your message automatically."
    )
    if game:
        how = [
            "This is a quick brain game, played with two buttons that are attached below your message: "
            "one starts today's daily set (the same questions for everyone, one attempt each, so "
            "results are comparable) and one starts a free game.",
            "Invite people to try it. Do not ask them to post a number, a count or proof, and do not "
            "tell them to type anything. You may mention that today's daily is the same for everyone.",
            "What it is: {}".format(details["pitch"]),
        ]
    else:
        how = [
            "People log this by typing a short command, which is added under your message "
            "automatically. You may nod to logging (for example 'drop it below'), but do not write the "
            "command yourself.",
        ]
    user = "\n".join([
        "Kind: {}".format("game" if game else "activity"),
        "Activity key: {}".format(activity),
        "Activity name: {}".format(details["name"]),
        "Unit: {}".format(details["unit"]),
        "Today: {}".format(weekday),
        "Channel name: {}".format(channel_name or "not provided"),
        "Suggested title: {}".format(details["title"]),
        "Suggested action: {}".format(details["action"]),
        "Proof/logging line: {}".format(details["proof"]),
        "Tone: {}".format(details["tone"]),
        "",
    ] + how + [
        "",
        "Write one short title and a one- or two-line body. Bold exactly one short phrase using Slack single-star bold.",
        "Good style: 'It is Friday. *One plank.* No drama. Snap it and drop it.'",
        "Bad formatting: '**5 quick minutes**'. Correct formatting: '*5 quick minutes*'.",
        "Bad style: long explanations about benefits, fresh air, creativity, or self-care.",
        "Bad: 'Type iplanked 60 to log it.' (the command is added for you).",
    ])

    raw = llm.chat(system, user)
    if not raw:
        return fallback_nudge(details, weekday), False

    try:
        parsed = json.loads(raw)
    except ValueError:
        llm.errors.append("azure: reply was not JSON")
        return fallback_nudge(details, weekday), False

    title = tidy_text(parsed.get("title"), 90) or details["title"]
    body = tidy_text(parsed.get("body"), 900)
    if not body:
        return fallback_nudge(details, weekday), False
    if repeats_command(body, details):
        llm.errors.append("azure: body repeated the command; used the template instead")
        return fallback_nudge(details, weekday), False
    return (title, body), True


def build_blocks(details, title, body, extra=(), ids=BUTTON_IDS_DEFAULT):
    """The nudge: heading, the AI-written body, how to act on it, then "Take a break".

    An activity ends with the command that logs it. A game ends with its two buttons, which
    carry the same action ids as the game steps, so the existing button trigger takes the
    click. A custom activity with no known trigger just ends after the body. After that,
    on every nudge, come `extra`: the suggestion and the buttons for iMath, iMemory and
    iBreath (break_blocks).
    """
    heading = "{}  *{}*".format(details.get("icon") or "", title).strip()
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": heading}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
    ]
    if details["kind"] == "game":
        blocks.append(game_buttons(details, ids))
    elif details.get("example"):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
            "*Log it:* `{}`".format(details["example"])}]})
    return blocks + list(extra)


def slack_post(token, channel, text, blocks):
    body, error = _send_json(
        SLACK_POST_URL,
        {
            "Authorization": "Bearer {}".format(token),
            "Content-Type": "application/json; charset=utf-8",
        },
        {"channel": channel, "text": text, "blocks": blocks},
    )
    if error:
        return False, error, ""
    if not body.get("ok"):
        return False, "slack: " + str(body.get("error")), ""
    return True, "", body.get("ts") or ""


def main(input):
    activity = choose_activity(input)
    details = activity_details(activity, input)
    today = datetime.now(timezone.utc)
    weekday = input.get("weekday") or today.strftime("%A")
    channel_id = (input.get("channel_id") or input.get("channel") or "").strip()
    channel_name = (input.get("channel_name") or "").strip()
    skip_post = truthy(input.get("skip_post")) or truthy(input.get("dry_run"))

    result = {
        "today": today.strftime("%Y-%m-%d"),
        "weekday": weekday,
        "activity": activity,
        "activity_name": details["name"],
        "kind": details["kind"],
        "trigger": details["trigger"],
        "example": details["example"],
        "buttons": [],
        "suggested_break": "",
        "unit": details["unit"],
        "title": "",
        "message_text": "",
        "message_json": "",
        "post_message_body": "",
        "channel_id": channel_id,
        "posted": False,
        "slack_ts": "",
        "llm_used": False,
        "ok": False,
        "error": "",
        "warnings": [],
    }

    llm = Azure(input.get("azure_api_key") or "", input.get("azure_url"))
    (title, body), llm_used = generate_nudge(llm, activity, details, weekday, channel_name)
    ids = button_ids_mode(input.get("button_ids"))
    break_section, suggested = break_blocks(activity, ids=ids)
    blocks = build_blocks(details, title, body, break_section, ids)
    fallback_text = "{} - {}".format(details["name"], title)

    result.update({
        "buttons": [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]],
        "suggested_break": suggested,
        "title": title,
        "message_text": body,
        "message_json": json.dumps(blocks),
        "post_message_body": json.dumps({"channel": channel_id, "text": fallback_text, "blocks": blocks}),
        "llm_used": llm_used,
    })
    result["warnings"].extend(llm.errors)

    token = (input.get("slack_bot_token") or "").strip()
    if skip_post:
        result["ok"] = True
        return result
    if not channel_id:
        result["error"] = "channel_id is required to post"
        return result
    if not token:
        result["ok"] = True
        result["warnings"].append("slack_bot_token is blank; returning post_message_body only")
        return result

    posted, error, ts = slack_post(token, channel_id, fallback_text, blocks)
    result["posted"] = posted
    result["slack_ts"] = ts
    result["ok"] = posted
    result["error"] = error
    return result


def cli():
    parser = argparse.ArgumentParser(description="Generate and optionally post a daily activity nudge.")
    parser.add_argument("--activity")
    parser.add_argument("--activities")
    parser.add_argument("--channel-id")
    parser.add_argument("--channel-name")
    parser.add_argument("--skip-post", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--azure-url")
    parser.add_argument("--title")
    parser.add_argument("--name")
    parser.add_argument("--unit")
    parser.add_argument("--icon")
    parser.add_argument("--action")
    parser.add_argument("--proof")
    parser.add_argument("--tone")
    parser.add_argument("--trigger")
    parser.add_argument("--example")
    args = parser.parse_args()

    payload = vars(args)
    payload["azure_api_key"] = os.environ.get("AZURE_API_KEY", "")
    payload["slack_bot_token"] = os.environ.get("SLACK_BOT_TOKEN", "")
    print(json.dumps(main(payload), indent=2))


if __name__ == "__main__":
    try:
        cli()
    except Exception as exc:
        sys.exit(str(exc))
