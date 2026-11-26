"""
iBoxBreath -- a guided breathing session in a Slack thread, logged as Pranayama minutes.

One Python step serves both recipes. What it does is decided by the input:
    `continue_session` = yes  -> carry on a session already breathing (the loop, below)
    `action_value` / `selected_value` present -> a button or dropdown was used
                              (or just map `slack_payload`, the whole click event: every
                              click field is read from it -- see from_payload)
    otherwise                 -> someone typed a message (post the setup card)

THE KEYWORD
    iboxbreath (iboxbreathe works too), a word on its own, any case. Spotter does not
    react to it: none of its trigger words is a prefix of it.

THE SETUP CARD
    A short line from Azure OpenAI on why slow breathing calms you (a fixed line when
    the model is unavailable or says something it should not), then two dropdowns --
    the pattern (PATTERNS) and how long (MINUTES) -- and Start. Nothing is timed until
    Start is pressed.

THE SESSION
    After a three-second "GET READY", one message cycles through the pattern's phases:
        an image (inhale_image, hold_image, exhale_image), and under it the phase's
        word spelled out letter by letter -- B, BR, BRE ... BREATHE IN -- the letters
        spread evenly over the phase, so the word is complete as the phase ends.
    A phase of 0 seconds is skipped (coherent breathing has no holds). The session ends
    at the end of the breath in progress once the minutes are up, never mid-breath, and
    the closing card shows done_image. End session stops it early.

    TWO WAYS TO ANIMATE IT
      GIF (the one to use)   `breath_gifs` names a looping GIF for the pattern, made by
          make_breath_gifs.py: one breath of the pattern, the phase's word held still, a
          bar and a seconds count, playing in the viewer's own Slack. Nothing is edited
          while it plays, so there is no Slack rate limit to meet, however many people
          are breathing. The step only waits, watches for End, and closes the session.

          A GIF kept in Slack is POSTED INTO THE THREAD as a file at Start (downloaded
          with files.info, uploaded again with files.getUploadURLExternal /
          completeUploadExternal) and deleted at the end: Slack plays a GIF that is a
          file in the conversation, but shows only a still frame of one placed in an
          image block by its file id. The card above it becomes the session's line and
          End button. Bot scopes: files:read and files:write, and the source GIFs must
          be in a channel the bot is in. WITHOUT those scopes the GIF's Slack link is
          posted instead, as a message on its own, which Slack shows as the file; it is
          deleted at the end the same way. A GIF at any other public https URL is shown
          in an image block. If nothing can be posted, the frames below take over.
          `animation` says which was used: gif_file, gif_link, gif_block or frames.
      Frames (the fallback, for a pattern with no GIF)   each letter is an edit of the
          message. Slack allows an app about 50 chat.update calls a minute, shared by
          everybody breathing at once, so a phase gets at most one frame every
          `min_frame_seconds` (default 1.2) and short phases skip letters. Every frame is
          placed by the clock, so a refused edit is skipped, never pushes the rest late.

THE LOOP (why a session is several steps)
    A Workato Python step is stopped at 90 seconds. Each step runs for at most
    `segment_seconds` (default 75, never more than 80, so the closing writes still fit)
    and returns keep_going = true; the recipe then
    runs this same step again with continue_session = yes and run_id, for each item of
    `continue_list`, until keep_going comes back false. Everything is timed from the
    wall clock stored in the session row, so the next step picks up exactly where the
    last one stopped.

    The recipe that runs this step (a function recipe called async is ideal):
        1. Python step (all the inputs)
        2. IF keep_going is true
             Variable: keep_going = true
             Repeat while keep_going is true
               Python step: continue_session = yes, run_id = step 1's run_id, and
                            the tokens and breath_gifs as in step 1 (run_id carries the
                            person and the channel, so nothing else is needed)
               Update variable: keep_going = that step's keep_going
    Or, simplest, ONE Python step inside the loop, with the inputs of the call:
        REPEAT  Python step (all the inputs)  WHILE  its keep_going is true
    Every pass then gets the same Start press again; a Start press that already began
    the session now running carries it on (start_press in the session), exactly as
    continue_session would. Any other call returns keep_going = false: one pass.
    The loop always ends: a session closes at its end time, and no pass asks for another
    once MAX_RUN_SECONDS have passed since Start. (A "Repeat for each item in
    continue_list" loop with "IF keep_going is false -> Stop job" inside works as well.)
    The recipe must allow several jobs at once (Settings -> Concurrency, 10 or more): the
    End session press is a job of its own while the session's job is still breathing.

WHAT IS LOGGED
    The minutes go into the person's breathe_users row exactly as spotter writes a
    typed `iprayanam 10 minutes` -- streak, heatmap, session list, tier -- using spotter's own
    classify / next_row, copied here (test_ibreath.py fails if they drift). A finished
    session logs the minutes chosen; End session logs the whole minutes breathed, and
    nothing under one. `testing` = yes logs nothing. The closing card says what was
    logged; spotter's reply, milestone posts and badge posts are not made (the weekly
    summary and the monthly email still count the minutes, from the row).

BUTTONS (tell the Slack trigger to listen for action_id starting `ibreath_`)
    ibreath_pattern   dropdown   value  pattern|<user>|<pattern key>
    ibreath_minutes   dropdown   value  minutes|<user>|<minutes>
    ibreath_start     Start      value  start|<user>|0
    ibreath_end       End        value  end|<user>|<run id>
    ibreath_again     Again      value  again|<user>|<run id>
    ibreath_play      Play       value  play|anyone|0   (on the daily nudge; ANYONE may press
                                 it, and the presser's own card opens as a reply in a thread
                                 under the nudge, found by source_ts = the nudge's message ts)
    The dropdowns' block_id equals their action_id, so the current choices are at
    state.values.ibreath_pattern.ibreath_pattern.selected_option.value and
    state.values.ibreath_minutes.ibreath_minutes.selected_option.value -- map them to
    pattern_value and minutes_value. Slack sends both with every click on the card, so
    Start always plays what the dropdowns show.

ROWS (the governance table, by row_type)
    boxbreath_session   one per person: the card or session in progress, JSON in content
    breathe_users       spotter's Pranayama row, where the minutes are logged

Input / output schema: ibreath_input_schema.json / ibreath_output_schema.json
"""

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

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
SLACK_FILE_INFO_URL = "https://slack.com/api/files.info"
SLACK_UPLOAD_URL = "https://slack.com/api/files.getUploadURLExternal"
SLACK_COMPLETE_URL = "https://slack.com/api/files.completeUploadExternal"
SLACK_FILE_DELETE_URL = "https://slack.com/api/files.delete"
AZURE_URL = ("https://cour-servicenow-1.openai.azure.com/openai/deployments/"
             "gpt-4o/chat/completions?api-version=2024-10-21")

# Short: one slow call must not carry a step past Workato's 90 seconds.
HTTP_TIMEOUT = 10
AZURE_TIMEOUT = 20
DEFAULT_TZ_OFFSET = -7 * 3600     # used only when users.info fails

SKIP_SUBTYPES = {
    "bot_message", "message_changed", "message_deleted", "message_replied",
    "thread_broadcast", "channel_join", "channel_leave", "channel_topic",
    "channel_purpose", "channel_name", "channel_archive", "channel_unarchive",
    "file_share_reply", "tombstone", "reminder_add",
}

# --------------------------------------------------------------------------
# Column map -- the only place a field UUID appears. KEEP IN STEP with spotter.py.
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
}

# The API rejects the whole document on one type mismatch, so values are coerced first.
COLUMN_TYPES = {
    "record_key": "string", "row_type": "string", "id": "string", "name": "string",
    "current_value": "string", "content": "string", "status": "string",
    "slack_channel_id": "string", "plank_duration": "integer", "total": "string",
    "direct_grant_count": "integer", "max_of_this_set": "integer",
    "personal_best_single_set": "integer", "total_planks": "integer",
    "heatmap_dates": "string", "plank_tier": "string", "first_seen": "date",
    "current_streak": "integer", "updated_at": "date", "longest_streak": "integer",
    "daily_post_count": "integer", "leaderboard_optout": "boolean",
    "freeze_credits": "integer", "week_count": "integer", "last_processed_ts": "string",
    "golden_dates": "string", "plank_photo": "string", "current_weight": "string",
    "current_fat": "string", "current_muscle": "string", "last_golden_date": "date",
    "is_private": "boolean",
}

LOOKUP_FAILED = object()

# --------------------------------------------------------------------------
# The exercise
# --------------------------------------------------------------------------

KEYWORDS = re.compile(r"(?<![A-Za-z0-9_])iboxbreathe?(?![A-Za-z0-9_])", re.IGNORECASE)

SESSION_ROW = "boxbreath_session"
BREATHE_ROW = "breathe_users"          # spotter's IPRAYANAM row
BREATHE_KEYWORD = "IPRAYANAM"

SESSION_STARTING = "starting"
SESSION_READY = "ready"                # card posted, waiting for Start
SESSION_ACTIVE = "active"              # breathing
SESSION_BUSY = "busy"                  # a click (or the end) is being settled
SESSION_OVER = "over"
STARTING_STALE_SECONDS = 60

# (key, name, (in, hold, out, hold) in seconds, what it is for). Each is a pattern people
# are actually taught, in order from easiest to most demanding. Holds of 0 are skipped.
PATTERNS = (
    ("gentle_box", "Gentle box", (3, 3, 3, 3), "A short, even square. A good first try"),
    ("box", "Box breathing", (4, 4, 4, 4), "The classic square. Calm and steady focus"),
    ("triangle", "Triangle breathing", (4, 4, 4, 0), "Box breathing without the empty hold"),
    ("coherent", "Coherent breathing", (5, 0, 5, 0), "Six slow breaths a minute, no holds"),
    ("long_exhale", "Longer exhale", (4, 0, 6, 0), "Out for longer than in, to wind down"),
    ("two_to_one", "2:1 breathing", (4, 0, 8, 0), "The exhale twice as long as the inhale"),
    ("relax_478", "4-7-8 relaxing breath", (4, 7, 8, 0), "A deep wind-down, often used before sleep"),
    ("resonance", "Resonance breathing", (6, 0, 6, 0), "Five breaths a minute, slow and even"),
    ("long_short", "Long breath, short hold", (6, 2, 6, 2), "Long, smooth breaths with a light pause"),
    ("deep_box", "Deep box", (6, 6, 6, 6), "A long, even square, for the practised"),
    # The slow end: breaths of 8 to 10 seconds, for people at ease with the ones above.
    ("slow_breathing", "Slow breathing", (8, 0, 8, 0), "Under four breaths a minute, smooth and even"),
    ("slow_exhale", "Slow 2:1 breathing", (5, 0, 10, 0), "A ten-second exhale to settle deeply"),
    ("long_box", "Long box", (8, 8, 8, 8), "Box breathing at half speed. Advanced"),
    ("ten_breath", "Ten-second breath", (10, 3, 10, 3), "Ten in, ten out, short pauses. Advanced"),
)
PATTERN = {p[0]: p for p in PATTERNS}
DEFAULT_PATTERN = "box"
MINUTES = (3, 5, 10, 15, 20, 30)
DEFAULT_MINUTES = 5

# (kind, the word spelled out on screen, which image)
PHASES = (("inhale", "BREATHE IN", "inhale"), ("hold_in", "HOLD", "hold"),
          ("exhale", "BREATHE OUT", "exhale"), ("hold_out", "HOLD", "hold"))
READY_WORD = "GET READY"
LEAD_SECONDS = 3                       # "GET READY" before the first breath

MIN_FRAME_SECONDS = 1.2                # about 50 edits a minute: Slack's chat.update tier
SEGMENT_SECONDS = 75                   # the longest one step runs before handing on
SEGMENT_MAX = 80                       # Workato stops a Python step at 90 s
CHECK_EVERY = 3                        # most seconds between looks at the table for End
RATE_LIMIT_PAUSE = 3                   # seconds without edits after Slack says slow down
REASSERT_SECONDS = 1.3                 # see finish(): beats a frame that was in flight
CONTINUE_CAP = 80                      # items in continue_list, at most
# No session can run longer than this from Start: the longest length, plus the longest
# breath it may finish, plus the count-in and room for a slow upload. Past it, a pass of
# the loop never asks for another -- so a while loop always ends, even if the table
# cannot be read.
MAX_RUN_SECONDS = 2200                 # about 37 minutes; test_ibreath checks it is enough

# Stand-ins so a test can run a whole session in milliseconds.
_sleep = time.sleep
_now = time.time

# --------------------------------------------------------------------------
# The opening line (Azure)
# --------------------------------------------------------------------------

GREETING_SYSTEM = (
    "You write the opening line of a short guided breathing exercise in a workplace "
    "Slack channel. Write two short sentences, at most 40 words in all, that explain "
    "simply why slow breathing calms you: quick, shallow breathing is what the body does "
    "under stress, so it tells the brain something is wrong; slow breathing, a long "
    "exhale especially, sends the opposite signal and lets the body relax.\n"
    "Tone: warm, plain and professional. No emoji, no exclamation marks, no greeting, no "
    "sign-off, no numbers, no medical claims, no formatting. Vary your wording each time. "
    "Reply with the two sentences only."
)
GREETINGS = (
    "Fast, shallow breathing is what the body does under stress, so it tells the brain "
    "something is wrong. Slow breathing sends the opposite message, and the body follows.",
    "Your breath is one of the few signals to your nervous system you can steer. Breathe "
    "slowly, let the exhale run long, and the body takes it as a sign to settle.",
    "Quick breaths tell the brain to stay alert; slow ones tell it that all is well. A few "
    "minutes of slow, even breathing is a simple way to let the body relax.",
)
GREETING_LIMIT = 320


class Azure(object):
    def __init__(self, api_key, url=None):
        self.url = url or AZURE_URL
        self.api_key = str(api_key or "").strip()
        self.errors = []

    def chat(self, system, user, temperature=0.9, max_tokens=120):
        if not self.api_key:
            return None
        body, error = _send_json(self.url, {"api-key": self.api_key,
                                            "Content-Type": "application/json"}, {
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature, "max_tokens": max_tokens}, timeout=AZURE_TIMEOUT)
        if error:
            self.errors.append("azure " + error)
            return None
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.errors.append("azure: unexpected response shape")
            return None


def check_greeting(text):
    """'' when the model's line can go out, otherwise why not."""
    text = str(text or "").strip()
    if len(text) < 30:
        return "too short"
    if len(text) > GREETING_LIMIT:
        return "too long"
    if re.search(r"[<>*_`#~|\[\]]|https?://|\d|!", text):
        return "a number, markup, a link or an exclamation mark"
    if text.count(".") + text.count("?") > 3:
        return "more than two sentences"
    return ""


def make_greeting(llm, seed=""):
    """(line, written by the model). A fixed line when the model is off or misbehaves."""
    digits = re.sub(r"\D", "", str(seed or "")) or "0"
    fallback = GREETINGS[int(digits[-3:]) % len(GREETINGS)]
    if not llm or not llm.api_key:
        return fallback, False
    reply = llm.chat(GREETING_SYSTEM, "Write the line.")
    line = re.sub(r"\s+", " ", str(reply or "")).strip().strip('"').strip()
    reason = check_greeting(line)
    if reason:
        if reply is not None:
            llm.errors.append("greeting from the template (the model's had {})".format(reason))
        return fallback, False
    return line, True

# --------------------------------------------------------------------------
# PURE -- the timeline
# --------------------------------------------------------------------------

def phases_of(pattern_key):
    """[(kind, word, image key, seconds)] for the pattern, holds of 0 left out."""
    secs = PATTERN.get(pattern_key, PATTERN[DEFAULT_PATTERN])[2]
    return [(kind, word, image, s) for (kind, word, image), s in zip(PHASES, secs) if s > 0]


def cycle_seconds(pattern_key):
    return sum(p[3] for p in phases_of(pattern_key))


def pattern_figures(pattern_key):
    """'4-4-4-4', '5-5', '4-7-8': the pattern's seconds, holds of 0 left out."""
    return "-".join(str(p[3]) for p in phases_of(pattern_key))


def pattern_label(pattern_key):
    return "{} ({})".format(PATTERN[pattern_key][1], pattern_figures(pattern_key))


def pattern_steps(pattern_key):
    """'in 4s, hold 4s, out 4s, hold 4s'."""
    names = {"inhale": "in", "hold_in": "hold", "exhale": "out", "hold_out": "hold"}
    return ", ".join("{} {}s".format(names[p[0]], p[3]) for p in phases_of(pattern_key))


def phase_frames(word, seconds, min_gap=MIN_FRAME_SECONDS):
    """[(seconds into the phase, text)]: the word spelled out over the phase.

    One frame per letter when the phase is long enough, otherwise as many as Slack
    allows (one every `min_gap` seconds), with letters skipped evenly in between. The
    frames are evenly spaced; the first letter is on screen as the phase begins and the
    whole word by its last frame. A space never ends a frame: "BREATHE " looks like
    "BREATHE"."""
    prefixes = [word[:i + 1] for i, c in enumerate(word) if c != " "]
    count = max(1, min(len(prefixes), int(seconds / float(min_gap) + 1e-9)))
    if count == 1:
        return [(0.0, word)]
    last = len(prefixes) - 1
    picks = [prefixes[int(k * last / float(count - 1) + 0.5)] for k in range(count)]
    return [(seconds * k / float(count), text) for k, text in enumerate(picks)]


def total_cycles(pattern_key, minutes):
    return max(1, int(math.ceil(minutes * 60.0 / cycle_seconds(pattern_key))))


def frame_at(state, now, min_gap=MIN_FRAME_SECONDS):
    """What the screen should show at `now`, and when it next changes.

    {"key": unique per frame, "kind", "text", "image", "cycle", "next_at"}. Everything
    comes from the clock and the session's start, so any step can work it out."""
    began = float(state["began"])
    t = now - began
    if t < 0:
        left = int(math.ceil(-t - 1e-9))
        return {"key": ("ready", left), "kind": "ready", "text": READY_WORD,
                "word": READY_WORD, "image": "",
                "cycle": 0, "next_at": began - (left - 1), "lead": left}
    phases = phases_of(state["pattern"])
    length = float(sum(p[3] for p in phases))
    cycle = int(t // length)
    within_cycle = t - cycle * length
    start = 0.0
    for index, (kind, word, image, secs) in enumerate(phases):
        if within_cycle < start + secs or index == len(phases) - 1:
            frames = phase_frames(word, secs, min_gap)
            into = within_cycle - start
            k = max(j for j, (offset, _) in enumerate(frames) if offset <= into + 1e-9)
            upcoming = frames[k + 1][0] if k + 1 < len(frames) else secs
            return {"key": (cycle, index, k), "kind": kind, "text": frames[k][1],
                    "word": word, "image": image, "cycle": cycle,
                    "next_at": began + cycle * length + start + upcoming}
        start += secs


def clock_text(seconds):
    seconds = max(0, int(math.ceil(seconds - 1e-9)))
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


def parse_value(value):
    """'<kind>|<owner>|<extra>' -> (kind, owner, extra), or None."""
    parts = str(value or "").strip().split("|")
    if len(parts) != 3 or parts[0] not in ("pattern", "minutes", "start", "end", "again", "play"):
        return None
    return parts[0], parts[1], parts[2]


def chosen(value, owner, kind):
    """A dropdown's value, when it is a real choice made on this person's card."""
    parsed = parse_value(value)
    if not parsed or parsed[0] != kind or parsed[1] != owner:
        return None
    if kind == "pattern":
        return parsed[2] if parsed[2] in PATTERN else None
    try:
        minutes = int(parsed[2])
    except ValueError:
        return None
    return minutes if minutes in MINUTES else None


SLACK_FILE_LINK = re.compile(r"slack\.com/files/[A-Z0-9]+/(F[A-Z0-9]+)")


def slack_file_id(ref):
    """The Slack file id a reference names -- a file link or a bare F... id -- or ''
    for anything else (a GIF hosted elsewhere)."""
    ref = str(ref or "").strip()
    match = SLACK_FILE_LINK.search(ref)
    if match:
        return match.group(1)
    return ref if re.match(r"^F[A-Z0-9]{6,}$", ref) else ""


def image_block(ref, alt):
    """An image block for a URL, a Slack file id (F...), or a Slack file page link --
    a page link needs a Slack sign-in to fetch, so it is turned into its file id."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    match = re.search(r"slack\.com/files/[A-Z0-9]+/(F[A-Z0-9]+)", ref)
    if match:
        return {"type": "image", "slack_file": {"id": match.group(1)}, "alt_text": alt}
    if ref.startswith(("http://", "https://")):
        return {"type": "image", "image_url": ref, "alt_text": alt}
    return {"type": "image", "slack_file": {"id": ref}, "alt_text": alt}

def gifs_from_links(text):
    """({pattern key: link}, warning) from links pasted one after another, in any order.
    Each is matched to its pattern by the file name at its end -- box.gif is box,
    relax_478.gif is relax_478 -- which is what Slack keeps in a file's link."""
    gifs, unmatched = {}, []
    for link in re.split(r"[\s,;]+", text.strip()):
        if not link:
            continue
        name = link.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        key = re.sub(r"\.gif$", "", name.lower())
        if key in PATTERN:
            gifs[key] = link
        else:
            unmatched.append(name[:40])
    return gifs, ("breath_gifs: no pattern matches {}".format(", ".join(unmatched))
                  if unmatched else "")


def parse_gifs(value):
    """({pattern key: GIF reference}, warning) from the breath_gifs input, which may
    arrive as an object or as the JSON text Workato hands objects through as."""
    if value is None:
        return {}, ""
    if isinstance(value, str):
        if not value.strip():
            return {}, ""
        if not value.strip().startswith("{"):
            return gifs_from_links(value)
        try:
            value = json.loads(value)
        except ValueError:
            return {}, "breath_gifs is not valid JSON; letters drawn by editing instead"
    if not isinstance(value, dict):
        return {}, "breath_gifs is not a JSON object; letters drawn by editing instead"
    gifs = {str(k).strip(): str(v or "").strip() for k, v in value.items()}
    unknown = sorted(k for k in gifs if k not in PATTERN)
    return ({k: v for k, v in gifs.items() if k in PATTERN and v},
            "breath_gifs: no pattern called {}".format(", ".join(unknown)) if unknown else "")

# --------------------------------------------------------------------------
# PURE -- Block Kit
# --------------------------------------------------------------------------

def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _option(text, value, description=""):
    option = {"text": {"type": "plain_text", "text": text[:75]}, "value": value}
    if description:
        option["description"] = {"type": "plain_text", "text": description[:75]}
    return option


def pattern_picker(state, owner):
    options = [_option(pattern_label(key), "pattern|{}|{}".format(owner, key),
                       "{}. {}".format(pattern_steps(key).capitalize(), about))
               for key, _name, _secs, about in PATTERNS]
    current = [key for key, *_ in PATTERNS].index(state.get("pattern") or DEFAULT_PATTERN)
    return {"type": "section", "block_id": "ibreath_pattern",
            "text": {"type": "mrkdwn", "text": "*Pattern*"},
            "accessory": {"type": "static_select", "action_id": "ibreath_pattern",
                          "placeholder": {"type": "plain_text", "text": "Pattern"},
                          "initial_option": options[current], "options": options}}


def minutes_picker(state, owner):
    options = [_option("{} minutes".format(m), "minutes|{}|{}".format(owner, m))
               for m in MINUTES]
    current = MINUTES.index(state.get("minutes") or DEFAULT_MINUTES)
    return {"type": "section", "block_id": "ibreath_minutes",
            "text": {"type": "mrkdwn", "text": "*For how long*"},
            "accessory": {"type": "static_select", "action_id": "ibreath_minutes",
                          "placeholder": {"type": "plain_text", "text": "Minutes"},
                          "initial_option": options[current], "options": options}}


def card_blocks(state, owner):
    """The setup card: who it is for, the opening line, the two choices and Start."""
    title = ":wind_blowing_face: *Box breathing* for <@{}>".format(owner)
    if state.get("test"):
        title += "  ·  :test_tube: Test session: nothing is logged"
    return [
        _context(title),
        {"type": "section", "text": {"type": "mrkdwn", "text": state.get("greeting") or GREETINGS[0]}},
        pattern_picker(state, owner),
        minutes_picker(state, owner),
        {"type": "actions", "block_id": "ibreath_card", "elements": [
            {"type": "button", "action_id": "ibreath_start", "style": "primary",
             "text": {"type": "plain_text", "text": "Start breathing"},
             "value": "start|{}|0".format(owner)}]},
        _context("Breathe through your nose if you can. If you feel light-headed, stop "
                 "and breathe normally."),
    ]


def breathing_blocks(state, frame, now, images):
    """One frame: the phase's image, the word so far, where you are, and End."""
    blocks = []
    picture = image_block(images.get(frame["image"]), frame["word"].capitalize()) \
        if frame["image"] else None
    if picture:
        blocks.append(picture)
    blocks.append({"type": "header", "text": {"type": "plain_text", "text": frame["text"]}})
    if frame["kind"] == "ready":
        where = "{}  ·  starting in {}".format(pattern_label(state["pattern"]), frame["lead"])
    else:
        where = "{}  ·  breath {} of {}  ·  {} left".format(
            pattern_label(state["pattern"]), min(frame["cycle"] + 1, state["cycles"]),
            state["cycles"], clock_text(float(state["end_at"]) - now))
    blocks.append(_context(where))
    blocks.append({"type": "actions", "block_id": "ibreath_session", "elements": [
        {"type": "button", "action_id": "ibreath_end",
         "text": {"type": "plain_text", "text": "End session"},
         "value": "end|{}|{}".format(state["owner"], state["run"])}]})
    return blocks


def gif_blocks(state):
    """The whole session on one unchanging message: the pattern's GIF, when it ends (in
    each reader's own time), and End. Nothing here may change while it plays."""
    end_at = int(round(float(state["end_at"])))
    line = "{}  \u00b7  {}  \u00b7  ends at <!date^{}^{{time}}|in {}>".format(
        pattern_label(state["pattern"]), plural(int(state["minutes"]), "minute"),
        end_at, plural(int(state["minutes"]), "minute"))
    if state.get("gif_file") or state.get("gif_ts"):    # the GIF is its own message, below
        return [
            {"type": "section", "text": {"type": "mrkdwn", "text":
                ":wind_blowing_face: *Follow the guide below.* Breathe with the words "
                "and the bar."}},
            _context(line),
            {"type": "actions", "block_id": "ibreath_session", "elements": [
                {"type": "button", "action_id": "ibreath_end",
                 "text": {"type": "plain_text", "text": "End session"},
                 "value": "end|{}|{}".format(state["owner"], state["run"])}]},
        ]
    return [
        image_block(state["gif"], "Breathing guide: " + pattern_label(state["pattern"])),
        _context(line),
        {"type": "actions", "block_id": "ibreath_session", "elements": [
            {"type": "button", "action_id": "ibreath_end",
             "text": {"type": "plain_text", "text": "End session"},
             "value": "end|{}|{}".format(state["owner"], state["run"])}]},
    ]


def loading_blocks(state):
    return [{"type": "header", "text": {"type": "plain_text", "text": READY_WORD}},
            _context("{}  \u00b7  your breathing guide is on its way".format(
                pattern_label(state["pattern"])))]


def done_blocks(state, outcome, images, buttons=True):
    """The closing card. `outcome`: {"minutes", "breaths", "early", "logged", "total",
    "note"}."""
    blocks = []
    if outcome["minutes"] >= 1:
        picture = image_block(images.get("done"), "Well done")
        if picture:
            blocks.append(picture)
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "WELL DONE"}})
        line = "<@{}> breathed for *{}* with {}: *{}* slow breaths.".format(
            state["owner"], plural(outcome["minutes"], "minute"),
            pattern_label(state["pattern"]), outcome["breaths"])
        if outcome["early"]:
            line += " Ended early, and every minute counts."
    else:
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": "SESSION ENDED"}})
        line = ("Ended after {}. Sessions under a minute are not logged; type "
                "`iboxbreath` to start again whenever you like.").format(
                    clock_text(outcome["seconds"]))
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})
    if outcome.get("note"):
        blocks.append(_context(outcome["note"]))
    if buttons:
        blocks.append({"type": "actions", "block_id": "ibreath_done", "elements": [
            {"type": "button", "action_id": "ibreath_again", "style": "primary",
             "text": {"type": "plain_text", "text": "Breathe again"},
             "value": "again|{}|{}".format(state["owner"], state.get("run") or "0")}]})
    return blocks


def plural(count, one, many=None):
    return "{} {}".format(count, one if count == 1 else (many or one + "s"))

# --------------------------------------------------------------------------
# COPIED from spotter/spotter.py, so a session is logged exactly as a typed
# `iprayanam` is. test_ibreath.py fails if any of these drift from spotter's.
# --------------------------------------------------------------------------

TOTAL_COLUMNS = ("total", "plank_photo", "current_weight", "current_fat", "current_muscle")
COLUMN_CHUNK = 9500                  # 500 under the 10,000 limit, as the leaderboard keeps
HEATMAP_KEEP_DAYS = 371
STREAK_MILESTONES = (7, 14, 21, 30, 50, 100)
GOLDEN_TS_CUTOFF = 6
GOLDEN_COOLDOWN_DAYS = 7
NO_TIER = "none"          # activities with no ladder
UNRANKED = "Not Started"  # below the lowest rung
# Pranayama's tier ladder, cumulative minutes, highest first: spotter's IPRAYANAM "tiers".
BREATHE_TIERS = [
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
]
# Tiers that have been renamed, old name -> current name. A row keeps the tier it was last
# written with, and a different name reads as a tier change, so without this a rename would
# congratulate, and credit, everyone on a tier they already hold. The row is written back with
# the current name the next time it is logged.
RENAMED_TIERS = {
    "First Breath": "First Pause",
    "Steady Breath": "Steady Practice",
    "Breath Keeper": "Prana Keeper",
}
_SAT_EPOCH = date(2024, 1, 6)
_SUN_EPOCH = date(2024, 1, 7)


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


def append_day(existing, day):
    """Add today to a comma-separated date list, once, keeping the tail."""
    days = split_dates(existing)
    iso = day.isoformat()
    if iso in days:
        return ",".join(days)
    return ",".join((days + [iso])[-HEATMAP_KEEP_DAYS:])


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
        if kind == "boolean":
            if isinstance(value, str):
                return value.strip().lower() in ("true", "1", "yes")
            return bool(value)
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


def _http(url, headers, data=None, method="GET", timeout=HTTP_TIMEOUT):
    """(bytes, error) for a request whose body is not JSON: a file going up or down."""
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), None
    except urllib.error.HTTPError as error:
        return None, "HTTP {} {}".format(error.code, url.split("/")[2])
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


def slack_form(token, url, params, method="POST"):
    """(body, error) for a Slack method that wants a form rather than JSON."""
    encoded = urllib.parse.urlencode(params or {})
    headers = {"Authorization": "Bearer {}".format(token)}
    if method == "GET":
        raw, error = _http("{}?{}".format(url, encoded), headers)
    else:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        raw, error = _http(url, headers, encoded.encode("utf-8"), "POST")
    if error:
        return None, error
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None, "slack: not JSON"
    if not body.get("ok"):
        return None, "slack: " + str(body.get("error"))
    return body, None


def post_gif_file(token, channel, thread_ts, source_id, title):
    """Download the GIF the bot can see as `source_id` and post it into the thread as a
    file of its own. Returns (the new file's id, error)."""
    info, error = slack_form(token, SLACK_FILE_INFO_URL, {"file": source_id}, "GET")
    if error:
        hint = " (put the GIFs in a channel the bot is in; it needs files:read)" \
            if "not_found" in error or "missing_scope" in error else ""
        return "", "files.info {}{}".format(error, hint)
    meta = info.get("file") or {}
    url = meta.get("url_private_download") or meta.get("url_private") or ""
    data, error = _http(url, {"Authorization": "Bearer {}".format(token)}) if url \
        else (None, "the file has no download link")
    if error or not (data or b"").startswith(b"GIF8"):
        return "", "download: {}".format(error or "what came back is not a GIF")
    name = meta.get("name") or "breathing.gif"
    up, error = slack_form(token, SLACK_UPLOAD_URL, {"filename": name, "length": len(data)})
    if error:
        return "", "files.getUploadURLExternal " + error + \
            (" (it needs files:write)" if "missing_scope" in error else "")
    _, error = _http(up["upload_url"], {"Content-Type": "application/octet-stream"}, data, "POST")
    if error:
        return "", "upload: " + error
    params = {"files": json.dumps([{"id": up["file_id"], "title": title}]),
              "channel_id": channel}
    if thread_ts:
        params["thread_ts"] = str(thread_ts)
    _, error = slack_form(token, SLACK_COMPLETE_URL, params)
    if error:
        return "", "files.completeUploadExternal " + error
    return up["file_id"], ""


def delete_file(token, file_id):
    _, error = slack_form(token, SLACK_FILE_DELETE_URL, {"file": file_id})
    return error or ""


def _get_json(url, headers):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8")), None
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


class Table(object):
    """Workato data table access, by column name rather than UUID. Reads join a session
    list spread over TOTAL_COLUMNS and writes spread it again, as spotter's Table does."""

    def __init__(self, token):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.errors = []
        self.written = 0

    def _decode(self, body):
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        rows = []
        for row in body.get("data", []):
            decoded = dict(zip(columns, [v for group in row for v in group]))
            if "total" in decoded:
                decoded["total"], decoded["_total_parts"] = stored_sessions(decoded)
            rows.append(decoded)
        return rows

    def row_for(self, row_type, user_id):
        """The person's row with its $record_id; None when there is none yet, and
        LOOKUP_FAILED when the read failed -- never mistaken for "none yet", which would
        write a first-timer's row over somebody's history. One retry."""
        payload = {"where": {"$and": [{"row_type": {"$eq": row_type}},
                                      {"id": {"$eq": user_id}}]}, "limit": 1}
        for attempt in (1, 2):
            body, error = _send_json(TABLE_QUERY_URL, self.headers, payload)
            if not error:
                rows = self._decode(body)
                return rows[0] if rows else None
            if attempt == 2:
                self.errors.append("table.query " + error)
        return LOOKUP_FAILED

    def _document(self, fields, parts_before=1):
        document = {}
        for name, value in fields.items():
            if name == "total":
                pieces, dropped = split_sessions(value)
                if dropped:
                    self.errors.append("total: {} oldest session(s) dropped".format(dropped))
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

    def create(self, fields, find=None):
        """(written, record_id). The id is read back with `find` when the create call
        does not return it; "" means written but not addressable."""
        body, error = _send_json(TABLE_RECORDS_URL, self.headers,
                                 {"document": self._document(fields)}, "POST")
        if error:
            self.errors.append("table.create " + error)
            return False, ""
        self.written += 1
        body = body if isinstance(body, dict) else {}
        record_id = body.get("record_id") or body.get("$record_id") or body.get("id") or ""
        if not record_id and find:
            for attempt in (1, 2):
                row = find()
                if row and row is not LOOKUP_FAILED:
                    record_id = row.get("$record_id") or ""
                    break
                if attempt == 1:
                    _sleep(0.5)
        return True, str(record_id)

    def update(self, record_id, fields, parts_before=1):
        if not record_id:
            self.errors.append("table.update without a $record_id")
            return False
        _, error = _send_json(TABLE_RECORD_URL.format(record_id), self.headers,
                              {"document": self._document(fields, parts_before)}, "PUT")
        if error:
            self.errors.append("table.update " + error)
            return False
        self.written += 1
        return True

    def write(self, row, fields):
        if row:
            return self.update(row.get("$record_id"), fields,
                               parts_before=int(row.get("_total_parts") or 1))
        return self.create(fields)[0]


def _slack_call(token, url, payload):
    body, error = _send_json(url, {"Authorization": "Bearer {}".format(token),
                                   "Content-Type": "application/json; charset=utf-8"}, payload)
    if error:
        return None, error
    if not body.get("ok"):
        return None, "slack: " + str(body.get("error"))
    return body, None


def slack_post(token, channel, text, blocks, thread_ts=None, unfurl=False):
    payload = {"channel": channel, "text": text}
    if blocks is not None:
        payload["blocks"] = blocks
    if unfurl:                     # a bare link, which Slack turns into its preview
        payload.update({"unfurl_links": True, "unfurl_media": True})
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    body, error = _slack_call(token, SLACK_POST_URL, payload)
    return ((body or {}).get("ts") or ""), error


def slack_update(token, channel, ts, text, blocks):
    _, error = _slack_call(token, SLACK_UPDATE_URL, {
        "channel": channel, "ts": str(ts), "text": text, "blocks": blocks})
    return error


def slack_ephemeral(token, channel, user, text, thread_ts=None):
    payload = {"channel": channel, "user": user, "text": text}
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    _slack_call(token, SLACK_EPHEMERAL_URL, payload)


def is_rate_limited(error):
    return "ratelimited" in str(error or "") or "HTTP 429" in str(error or "")


def slack_user(token, user_id):
    """Real name and tz offset from users.info. Never raises."""
    fallback = {"real_name": "", "tz_offset": DEFAULT_TZ_OFFSET}
    if not token or not user_id:
        return fallback
    body, error = _get_json("{}?user={}".format(SLACK_USER_URL, user_id),
                            {"Authorization": "Bearer {}".format(token)})
    if error or not (body or {}).get("ok"):
        return fallback
    user = body.get("user") or {}
    profile = user.get("profile") or {}
    name = (profile.get("real_name") or user.get("real_name")
            or profile.get("display_name") or user.get("name") or "")
    return {"real_name": name.strip(), "tz_offset": user.get("tz_offset", DEFAULT_TZ_OFFSET)}


def should_process(event):
    """(ok, reason). The bot's own messages name the keyword, so they must be skipped."""
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

# --------------------------------------------------------------------------
# The session row
# --------------------------------------------------------------------------

def load_state(row):
    try:
        state = json.loads((row or {}).get("content") or "{}")
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


def session_fields(owner, name, channel, status, state, trigger_ts):
    return {"record_key": "{}_{}".format(SESSION_ROW, owner), "row_type": SESSION_ROW,
            "id": owner, "name": name, "status": status, "slack_channel_id": channel,
            "last_processed_ts": str(trigger_ts),
            "content": json.dumps(state, separators=(",", ":"))}


def local_today(tz_offset, now=None):
    try:
        offset = int(tz_offset)
    except (TypeError, ValueError):
        offset = DEFAULT_TZ_OFFSET
    return (datetime(1970, 1, 1)
            + timedelta(seconds=(_now() if now is None else now) + offset)).date()


def images_of(input):
    """{"inhale", "hold", "exhale", "done"}: each a URL, a Slack file id or ''."""
    return {key: str(input.get(key + "_image") or "").strip()
            for key in ("inhale", "hold", "exhale", "done")}


class Run(object):
    """What one step needs to move a session along."""

    def __init__(self, input, result, table, token, session, state):
        self.input = input
        self.result = result
        self.table = table
        self.token = token
        self.record_id = (session or {}).get("$record_id") or ""
        self.trigger_ts = (session or {}).get("last_processed_ts") or ""
        self.state = state
        self.images = images_of(input)
        try:
            self.min_gap = max(0.5, float(input.get("min_frame_seconds") or MIN_FRAME_SECONDS))
        except (TypeError, ValueError):
            self.min_gap = MIN_FRAME_SECONDS
        try:
            segment = float(input.get("segment_seconds") or SEGMENT_SECONDS)
        except (TypeError, ValueError):
            segment = SEGMENT_SECONDS
        self.segment = min(SEGMENT_MAX, max(20.0, segment))
        self.gifs, warning = parse_gifs(input.get("breath_gifs"))
        if warning:
            self.warn(warning)

    def warn(self, text):
        if text not in self.result["warnings"]:
            self.result["warnings"].append(text)

    def save(self, status):
        state = self.state
        return self.table.update(self.record_id, session_fields(
            state["owner"], state.get("name") or state["owner"], state["channel"], status,
            state, self.trigger_ts))

    def show(self, text, blocks):
        """Edit the session's message. Returns the error, or ''."""
        state = self.state
        return slack_update(self.token, state["channel"], state["ts"], text, blocks) or ""

    def live(self):
        """True while this run is still the session's live one; None when unreadable."""
        row = self.table.row_for(SESSION_ROW, self.state["owner"])
        if row is LOOKUP_FAILED:
            return None
        return bool(row) and row.get("status") == SESSION_ACTIVE \
            and load_state(row).get("run") == self.state["run"]

# --------------------------------------------------------------------------
# The setup card
# --------------------------------------------------------------------------

def open_card(input, result, table, token, thread_ts, trigger_ts, previous=None):
    """Post the setup card in the thread and wait for Start. `previous` is the state of
    the person's last session, whose choices the dropdowns start on."""
    owner, channel = result["user_id"], result["channel"]
    previous = previous or {}
    session = table.row_for(SESSION_ROW, owner)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the session table; nothing started"
        return
    old = load_state(session) if session else {}

    # One session at a time: a new card ends one still breathing, minutes logged.
    if session and session.get("status") == SESSION_ACTIVE and old.get("run"):
        if table.update(session["$record_id"], {"status": SESSION_BUSY}):
            finish(Run(input, result, table, token, session, old), "replaced")
        result["ok"] = False                  # this call is about the new card
        session = table.row_for(SESSION_ROW, owner)
        if session is LOOKUP_FAILED:
            result["error"] = "could not read the session table; nothing started"
            return

    who = slack_user(token, owner)
    name = who["real_name"] or (session or {}).get("name") or owner
    result["user_name"] = name
    llm = Azure(input.get("azure_api_key"), input.get("azure_url"))
    greeting, by_ai = make_greeting(llm, trigger_ts)
    result["warnings"] += llm.errors
    result["greeting"], result["greeting_by_ai"] = greeting, by_ai

    state = {"v": 1, "owner": owner, "name": name, "tz": who["tz_offset"], "channel": channel,
             "thread_ts": thread_ts, "ts": "", "greeting": greeting,
             "pattern": previous.get("pattern") or old.get("pattern") or DEFAULT_PATTERN,
             "minutes": previous.get("minutes") or old.get("minutes") or DEFAULT_MINUTES,
             "test": _flag(input.get("testing")), "run": "", "started": _now()}
    if state["pattern"] not in PATTERN:
        state["pattern"] = DEFAULT_PATTERN
    if state["minutes"] not in MINUTES:
        state["minutes"] = DEFAULT_MINUTES

    # Claim before posting: a Slack retry of the same message finds last_processed_ts.
    claim = session_fields(owner, name, channel, SESSION_STARTING, state, trigger_ts)
    record_id = (session or {}).get("$record_id") or ""
    if session:
        if not table.update(record_id, claim):
            result["error"] = "could not claim the session row"
            return
    else:
        created, record_id = table.create(claim, find=lambda: table.row_for(SESSION_ROW, owner))
        if not created or not record_id:
            result["error"] = "could not create the session row; nothing started"
            return

    ts, error = slack_post(token, channel, "Box breathing: choose a pattern and press Start",
                           card_blocks(state, owner), thread_ts=thread_ts)
    if error:
        table.update(record_id, {"status": SESSION_OVER})
        result["error"] = "could not post the card: " + error
        return
    state["ts"] = ts
    if not table.update(record_id, session_fields(owner, name, channel, SESSION_READY,
                                                  state, trigger_ts)):
        _slack_call(token, SLACK_DELETE_URL, {"channel": channel, "ts": ts})
        result["error"] = "could not save the session; nothing started"
        return
    result["ok"] = True
    result["posted_ts"] = ts
    result["pattern"], result["minutes"] = state["pattern"], state["minutes"]


def is_duplicate(session, message_ts):
    """Whether this message was already claimed by a card that actually went out."""
    if not session or str(session.get("last_processed_ts") or "") != message_ts:
        return False
    if session.get("status") != SESSION_STARTING:
        return True
    return _now() - float(load_state(session).get("started") or 0) < STARTING_STALE_SECONDS

# --------------------------------------------------------------------------
# Breathing
# --------------------------------------------------------------------------

def begin(run, pattern, minutes):
    """Start pressed: fix the timeline, save it, and breathe the first segment."""
    state, result = run.state, run.result
    result["mode"] = "start"
    now = _now()
    # The run id names the person and the channel too, so a pass of the loop needs
    # nothing but continue_session and run_id to find the session (see run_owner).
    run_id = "{}:{}:{:.3f}".format(state["owner"], state["channel"], now)
    state.update({"pattern": pattern, "minutes": minutes, "run": run_id,
                  "gif": run.gifs.get(pattern, ""), "gif_file": ""})
    state["gif_ts"] = ""
    source = slack_file_id(state["gif"])
    how = "block" if state["gif"] else "frames"
    if source:
        # Kept in Slack, where an image block shows only a still frame of it. First as
        # a file of its own in the thread (needs files:read and files:write) ...
        run.show("Box breathing: getting ready", loading_blocks(state))
        state["gif_file"], error = post_gif_file(
            run.token, state["channel"], state.get("thread_ts"), source,
            "Breathing guide: " + pattern_label(pattern))
        how = "file"
        if error:
            # ... and without those scopes, as its link, which Slack shows as the file.
            how, link = "link", state["gif"]
            if not SLACK_FILE_LINK.search(link):
                how = "frames"
            else:
                state["gif_ts"], post_error = slack_post(
                    run.token, state["channel"], link, None,
                    thread_ts=state.get("thread_ts"), unfurl=True)
                if post_error:
                    how = "frames"
            if how == "frames":
                run.warn("GIF not posted, letters drawn by editing instead: " + error)
                state["gif"] = ""
            else:
                run.warn("GIF posted as its link (the file upload said: {})".format(error))
    # A GIF starts on its first breath the moment it appears; the frames count one in.
    gif = state["gif"]
    state["began"] = _now() + (0 if gif else LEAD_SECONDS)
    state["cycles"] = total_cycles(pattern, minutes)
    state["end_at"] = state["began"] + state["cycles"] * cycle_seconds(pattern)
    if not run.save(SESSION_ACTIVE):
        if state["gif_file"]:
            delete_file(run.token, state["gif_file"])
        if state["gif_ts"]:
            _slack_call(run.token, SLACK_DELETE_URL, {"channel": state["channel"],
                                                      "ts": state["gif_ts"]})
        run.table.update(run.record_id, {"status": SESSION_READY})
        run.show("Box breathing: choose a pattern and press Start",
                 card_blocks(state, state["owner"]))
        result["error"] = "could not start the session; press Start again"
        return
    result["run_id"] = state["run"]
    result["pattern"], result["minutes"] = pattern, minutes
    result["posted_ts"] = state["ts"]
    result["animation"] = "gif_" + how if gif else "frames"
    if gif:
        error = run.show("Box breathing: " + pattern_label(pattern), gif_blocks(state))
        if error:
            run.save(SESSION_OVER)
            result["error"] = "could not show the session: " + error
            return
    result["ok"] = True
    breathe(run, now + run.segment)
    if result["keep_going"]:
        left = float(state["end_at"]) - _now()
        count = min(CONTINUE_CAP, int(math.ceil(left / run.segment)) + 2)
        result["continue_list"] = [{"n": i + 1} for i in range(count)]


def breathe(run, deadline, shown=None):
    """Show the session frame by frame until it ends, End is pressed, or this step's
    time is up -- in which case keep_going is set and the next step carries on.

    With a GIF nothing is drawn: the step only waits for the end, looking at the table
    every CHECK_EVERY seconds for End.

    The table is asked whether the session is still live before EVERY frame, so once End
    has closed it at most the one frame already on its way can land on the closing card
    (which finish() then puts back), and every CHECK_EVERY seconds while nothing moves.
    `shown` is the frame already on screen, which is not drawn a second time."""
    state, result = run.state, run.result
    checked, quiet_until = _now(), 0.0
    animate = not state.get("gif")
    while True:
        now = _now()
        if now >= float(state["end_at"]):
            live = run.live()
            if live is False:
                return                       # ended or replaced by a click meanwhile
            if run.table.update(run.record_id, {"status": SESSION_BUSY}):
                finish(run, "complete")
            return
        if now >= deadline:
            result["keep_going"] = True
            return
        frame = frame_at(state, now, run.min_gap)
        drawing = animate and frame["key"] != shown and now >= quiet_until
        if drawing or now - checked >= CHECK_EVERY:
            checked = now
            if run.live() is False:
                result["skipped"] = "the session was ended or replaced"
                return
        if drawing:
            error = run.show(frame["text"], breathing_blocks(state, frame, now, run.images))
            if not error:
                shown = frame["key"]
                result["frames"] += 1
            elif is_rate_limited(error):
                quiet_until = now + RATE_LIMIT_PAUSE
                result["frames_skipped"] += 1
                run.warn("Slack rate-limited some frames; they were skipped")
            else:
                quiet_until = now + 1
                result["frames_skipped"] += 1
                run.warn("frame: " + error)
        wake = min(frame["next_at"] if animate else float(state["end_at"]),
                   float(state["end_at"]), deadline, checked + CHECK_EVERY)
        if animate and frame["key"] != shown:
            wake = min(wake, max(quiet_until, now + 0.25))
        _sleep(max(0.05, wake - _now()))


def continue_session(input, result, table, token):
    """The loop's next pass: carry on the run named by run_id, if it is still live."""
    result["mode"] = "continue"
    run_id = str(input.get("run_id") or "").strip()
    session = table.row_for(SESSION_ROW, result["user_id"])
    if session is LOOKUP_FAILED:
        # Cannot tell: try again on the next pass rather than abandon the session -- but
        # never past the longest a session can last, or a while loop would not end.
        started = run_started(run_id)
        result["ok"] = True
        if started and _now() - started < MAX_RUN_SECONDS:
            result["keep_going"] = True
            result["warnings"].append("session unreadable; will try again")
        else:
            result["skipped"] = "session unreadable, and past its longest possible length"
        return
    state = load_state(session) if session else {}
    if not session or session.get("status") != SESSION_ACTIVE or not run_id \
            or state.get("run") != run_id:
        result["ok"] = True
        result["skipped"] = "session over"
        return
    result["ok"], result["run_id"] = True, run_id
    result["pattern"], result["minutes"] = state.get("pattern", ""), state.get("minutes", 0)
    result["posted_ts"] = state.get("ts", "")
    result["animation"] = ("gif_file" if state.get("gif_file") else "gif_link"
                           if state.get("gif_ts") else "gif_block" if state.get("gif")
                           else "frames")
    run = Run(input, result, table, token, session, state)
    # The step before drew the frame of this moment as it handed over: start on the next.
    breathe(run, _now() + run.segment, shown=frame_at(state, _now(), run.min_gap)["key"])


def breathe_tier(row, minutes):
    """The tier somebody's breathing total reaches with these minutes added: what spotter's
    tier_for says of tier_value (everything logged before, plus this), for IPRAYANAM."""
    total = int(sum(split_numbers((row or {}).get("total")))) + int(minutes)
    for threshold, name in BREATHE_TIERS:
        if total >= threshold:
            return name
    return UNRANKED


def log_minutes(run, minutes):
    """Log the minutes to the person's breathe_users row, as spotter would.
    Returns (logged, running total in minutes, note for the card)."""
    state, table = run.state, run.table
    if state.get("test"):
        return False, 0, "Test session: nothing was logged."
    row = table.row_for(BREATHE_ROW, state["owner"])
    if row is LOOKUP_FAILED:
        run.warn("breathe_users unreadable; minutes not logged")
        return False, 0, "Could not reach the log just now, so this session was not saved."
    # The closing card's ts: unique to the session, so finishing twice logs once.
    message_ts = str(state.get("ts") or "ibreath:" + state["run"])
    today = local_today(state.get("tz"))
    tier = breathe_tier(row, minutes)
    event = classify(row, minutes, message_ts, today, tier)
    if event["outcome"] == "duplicate":
        return True, int(sum(split_numbers(row.get("total")))), ""
    event["golden"] = False                     # a golden day is spotter's to announce
    fields = next_row(row, event, {
        "keyword": BREATHE_KEYWORD, "row_type": BREATHE_ROW, "user_id": state["owner"],
        "user_name": state.get("name") or state["owner"], "message_ts": message_ts,
        "source": "channel", "count": minutes, "max_of_this_set": minutes,
        "new_tier": tier, "today": today})
    if not table.write(row, fields):
        run.warn("breathe_users write failed; minutes not logged")
        return False, 0, "Could not save this session to the log just now."
    run.result["streak"] = int(fields.get("current_streak") or 0)
    return True, int(sum(split_numbers(fields.get("total")))), ""


def finish(run, how, from_click=False):
    """Close the session: log the minutes, show the closing card, mark it over.

    how: complete (the time ran out), early (End pressed), replaced (a new card)."""
    state, result = run.state, run.result
    now = _now()
    end_at = float(state["end_at"])
    seconds = max(0.0, min(now, end_at) - float(state["began"]))
    minutes = int(state["minutes"]) if how == "complete" else int(seconds // 60)
    breaths = state["cycles"] if how == "complete" \
        else int(seconds // cycle_seconds(state["pattern"]))
    outcome = {"minutes": minutes, "breaths": breaths, "early": how != "complete",
               "seconds": seconds, "note": ""}
    logged, total = False, 0
    if minutes >= 1:
        logged, total, outcome["note"] = log_minutes(run, minutes)
        if logged:
            outcome["note"] = "Logged to Pranayama: {} today. {} in all.".format(
                plural(minutes, "minute"), plural(total, "minute"))
    state["outcome"] = {k: outcome[k] for k in ("minutes", "breaths", "early", "seconds", "note")}
    if state.get("gif_file"):              # the guide goes; the closing card stays
        error = delete_file(run.token, state["gif_file"])
        if error:
            run.warn("the GIF could not be removed: " + error)
        state["gif_file"] = ""
    if state.get("gif_ts"):
        _, error = _slack_call(run.token, SLACK_DELETE_URL, {"channel": state["channel"],
                                                             "ts": state["gif_ts"]})
        if error:
            run.warn("the GIF could not be removed: " + error)
        state["gif_ts"] = ""
    run.save(SESSION_OVER)

    blocks = done_blocks(state, outcome, run.images, buttons=how != "replaced")
    text = "Box breathing: {}".format("well done" if minutes >= 1 else "session ended")
    error = run.show(text, blocks)
    if error:
        run.warn("closing card: " + error)
    if from_click:
        # The breathing step may have had a frame in flight when the click claimed the
        # session; one landing after the card would hide it. Show the card once more.
        _sleep(REASSERT_SECONDS)
        run.show(text, blocks)
    result.update({"ok": True, "keep_going": False, "minutes_breathed": minutes,
                   "breaths": breaths, "logged": logged, "total_minutes": total,
                   "finished": how})

# --------------------------------------------------------------------------
# Clicks
# --------------------------------------------------------------------------

def handle_click(input, result, table, token):
    value = str(input.get("action_value") or input.get("selected_value") or "").strip()
    parsed = parse_value(value)
    if not parsed:
        result["ok"] = True
        result["skipped"] = "not an iBoxBreath control"
        return
    kind, owner, extra = parsed
    result["mode"] = kind
    clicker, channel = result["user_id"], result["channel"]
    source_ts = str(input.get("source_ts") or "").strip()
    if kind == "play" and owner == "anyone":
        # The daily nudge's button: the same as typing `iboxbreath`, for whoever pressed it.
        # The card goes in a thread under the NUDGE (source_ts, the message that holds the
        # button). result["thread_ts"] is no use here: a post has no thread yet, so it falls
        # back to message_ts, which the click recipe maps to action_ts -- the moment of the
        # click, not a message -- and Slack accepts a reply to it without ever showing it.
        open_card(input, result, table, token, source_ts or result["thread_ts"],
                  "play:" + str(input.get("action_ts") or source_ts))
        return
    if owner != clicker:
        slack_ephemeral(token, channel, clicker,
                        "This is <@{}>'s session. Type `iboxbreath` to start your own.".format(owner),
                        thread_ts=result["thread_ts"] or None)
        result["ok"] = True
        result["skipped"] = "button belongs to another person"
        return

    session = table.row_for(SESSION_ROW, owner)
    if session is LOOKUP_FAILED:
        result["error"] = "could not read the session table"
        return
    state = load_state(session) if session else {}
    status = (session or {}).get("status")
    on_card = bool(state.get("ts")) and (not source_ts or source_ts == state["ts"])
    stale = {"ok": True, "skipped": "stale or repeated click"}

    if kind in ("pattern", "minutes"):
        # The dropdowns keep their own choice on screen; it is saved so a Start that
        # arrives without state.values still plays what was picked.
        pick = chosen(value, owner, kind)
        if status != SESSION_READY or not on_card or pick is None:
            result.update(stale)
            return
        state[kind] = pick
        Run(input, result, table, token, session, state).save(SESSION_READY)
        result.update({"ok": True, "pattern": state["pattern"], "minutes": state["minutes"]})
        return

    if kind == "start":
        press = "{}|{}".format(source_ts, str(input.get("action_ts") or "").strip())
        if status == SESSION_ACTIVE and state.get("start_press") == press:
            # The same Start press again: a recipe whose loop runs this one step for every
            # pass, with the inputs it began with. Carry the session on.
            continue_session(dict(input, run_id=state.get("run")), result, table, token)
            return
        if status != SESSION_READY or not on_card:
            result.update(stale)
            return
        if not table.update(session["$record_id"], {"status": SESSION_BUSY}):
            result["error"] = "could not claim the click; press Start again"
            return
        pattern = chosen(input.get("pattern_value"), owner, "pattern") or state.get("pattern")
        minutes = chosen(input.get("minutes_value"), owner, "minutes") or state.get("minutes")
        state["start_press"] = press
        run = Run(input, result, table, token, session, state)
        for name in ("pattern_value", "minutes_value"):
            if not str(input.get(name) or "").strip():
                # Slack always sends both choices with Start: blank means the recipe did not
                # pass them on, and the card's last saved choice is played instead.
                run.warn("{} was blank, so the saved choice was played ({}). Map it from "
                         "state.values in the click recipe, and pass it through every recipe "
                         "between the trigger and this step.".format(
                             name, pattern_label(pattern) if name == "pattern_value"
                             else plural(minutes, "minute")))
        begin(run, pattern if pattern in PATTERN else DEFAULT_PATTERN,
              minutes if minutes in MINUTES else DEFAULT_MINUTES)
        return

    if kind == "end":
        if status != SESSION_ACTIVE or state.get("run") != extra:
            result.update(stale)
            return
        if not table.update(session["$record_id"], {"status": SESSION_BUSY}):
            result["error"] = "could not claim the click; press End again"
            return
        finish(Run(input, result, table, token, session, state), "early", from_click=True)
        return

    if kind == "again":
        if status != SESSION_OVER or state.get("run") != extra or not on_card:
            result.update(stale)
            return
        # The old card keeps its result and loses its button.
        if state.get("outcome"):
            slack_update(token, channel, state["ts"], "Box breathing: well done",
                         done_blocks(state, state["outcome"], images_of(input),
                                     buttons=False))
        open_card(input, result, table, token, state.get("thread_ts") or result["thread_ts"],
                  "again:" + str(input.get("action_ts") or extra), previous=state)


def _flag(value):
    return str(value or "").strip().lower() in ("yes", "y", "true", "1", "on")

# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _dig(data, *path):
    """data[path[0]][path[1]]..., or None wherever a step is missing."""
    for key in path:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and isinstance(key, int) and -len(data) <= key < len(data):
            data = data[key]
        else:
            return None
        if data is None:
            return None
    return data


def from_payload(input):
    """The inputs, with every blank one a click needs filled from `slack_payload`: the
    whole block_actions event, as an object or as JSON text, bare or under its
    "block_actions:button" key as Workato's Slack trigger gives it. One mapping instead
    of a formula per field. A field the recipe did pass is kept as it is."""
    raw = input.get("slack_payload")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else None
        except ValueError:
            return dict(input), "slack_payload is not valid JSON; ignored"
    if not isinstance(raw, dict):
        return dict(input), ""
    if "actions" not in raw:                   # wrapped, e.g. {"block_actions:button": {...}}
        raw = next((v for v in raw.values() if isinstance(v, dict) and "actions" in v), raw)
    values = _dig(raw, "state", "values") or {}
    found = {
        "user_id": _dig(raw, "user", "id"),
        "channel": _dig(raw, "channel", "id") or _dig(raw, "container", "channel_id"),
        "action_value": _dig(raw, "actions", 0, "value"),
        "selected_value": _dig(raw, "actions", 0, "selected_option", "value"),
        "pattern_value": _dig(values, "ibreath_pattern", "ibreath_pattern",
                              "selected_option", "value"),
        "minutes_value": _dig(values, "ibreath_minutes", "ibreath_minutes",
                              "selected_option", "value"),
        "source_ts": _dig(raw, "container", "message_ts"),
        "action_ts": _dig(raw, "actions", 0, "action_ts"),
        "thread_ts": _dig(raw, "container", "thread_ts") or _dig(raw, "message", "thread_ts"),
    }
    merged = dict(input)
    for name, value in found.items():
        if value and not str(merged.get(name) or "").strip():
            merged[name] = str(value)
    return merged, ""


def run_started(run_id):
    """When the run began (epoch seconds) from its id, or 0."""
    try:
        return float(str(run_id or "").strip().split(":")[-1])
    except ValueError:
        return 0.0


def run_owner(run_id):
    """(user id, channel) from a run id made by begin(), or ('', '') for any other."""
    parts = str(run_id or "").strip().split(":")
    return (parts[0], parts[1]) if len(parts) == 3 and all(parts) else ("", "")


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    input, payload_warning = from_payload(input)
    if _flag(input.get("continue_session")):
        # A pass of the loop needs only run_id: the person and the channel are in it.
        user_id, channel = run_owner(input.get("run_id"))
        for name, value in (("user_id", user_id), ("channel", channel)):
            if value and not str(input.get(name) or "").strip():
                input[name] = value
    token = input.get("slack_bot_token") or ""
    message_ts = str(input.get("message_ts") or "").strip()
    result = {
        "ok": False, "error": "", "warnings": [], "skipped": "", "mode": "card",
        "user_id": (input.get("user_id") or "").strip(), "user_name": "",
        "channel": (input.get("channel") or "").strip(), "message_ts": message_ts,
        "thread_ts": str(input.get("thread_ts") or "").strip() or message_ts,
        "posted_ts": "", "greeting": "", "greeting_by_ai": False, "pattern": "",
        "minutes": 0, "run_id": "", "animation": "", "keep_going": False, "continue_list": [],

        "frames": 0, "frames_skipped": 0, "finished": "", "minutes_breathed": 0,
        "breaths": 0, "logged": False, "total_minutes": 0, "streak": 0, "rows_written": 0,
    }
    if payload_warning:
        result["warnings"].append(payload_warning)
    if not result["user_id"] or not result["channel"]:
        result["error"] = "user_id and channel are both required"
        return result
    if not token:
        result["error"] = "slack_bot_token is required"
        return result
    table = Table(input.get("workato_api_token") or "")

    if _flag(input.get("continue_session")):
        continue_session(input, result, table, token)
    elif str(input.get("action_value") or input.get("selected_value") or "").strip():
        handle_click(input, result, table, token)
    else:
        allowed, reason = should_process(input)
        if not allowed:
            result["ok"], result["skipped"] = True, reason
            return result
        if not KEYWORDS.search(input.get("text") or ""):
            result["ok"], result["skipped"] = True, "no iboxbreath keyword"
            return result
        if not message_ts:
            result["error"] = "message_ts is required to start"
            return result
        session = table.row_for(SESSION_ROW, result["user_id"])
        if session is not LOOKUP_FAILED and is_duplicate(session, message_ts):
            result["ok"], result["skipped"] = True, "duplicate delivery of this message"
            return result
        open_card(input, result, table, token, result["thread_ts"], message_ts)

    result["rows_written"] = table.written
    result["warnings"] += [e for e in table.errors if e not in result["warnings"]]
    return result


if __name__ == "__main__":
    print(json.dumps(main({
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", ""),
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "azure_api_key": os.environ.get("AZURE_API_KEY", ""),
        "text": sys.argv[1] if len(sys.argv) > 1 else "iboxbreath",
        "user_id": sys.argv[2] if len(sys.argv) > 2 else "U038ZCDAY6P",
        "channel": os.environ.get("SLACK_CHANNEL", ""),
        "message_ts": "{:.6f}".format(time.time()),
    }), indent=2))
