"""
Channel summary -- what the channel has done, posted in one of two formats.

Workato Python step. Two formats, chosen by the `format` input:

    weekly   (the default) A dashboard of the last 7 days. A headline that changes
             every week, the week's numbers as tiles, the moments worth naming (first
             logs, comebacks, personal bests and round numbers, milestones), every
             badge earned grouped by kind, a who-showed-up-when calendar, this week's
             top contributor in each activity, a spotlight on a smaller activity and
             the next milestone with what it takes to reach it. On alternate weeks the
             channel records to beat close the post instead of the spotlight.
    classic  The original all-time summary: totals, milestones banked, progress
             bars towards the next rung. Nothing in it is tied to a date.
    random   Picks one of the two at each run (`format_used` says which).

The weekly format also carries two things that build over time: new BADGES (earned by
showing up -- streaks, steady weeks, perfect weeks, variety; never by volume) and THE
GREAT WALK, the channel's steps added together as a walk round the world, with an
arrival named the week it happens.

Both formats are deliberately without a leaderboard. The cumulative boards already
rank people, and the same names sit on top every week -- which is exactly the
message you do not want in a post meant to bring the quiet half back. The weekly
top contributors are the one exception, and only because they start from zero every
week: one name per activity, and only for someone who logged on more than one day.

Every activity with a real week behind it -- two or more people, or three or more
check-ins (see WEEK_ACTIVITY_MIN_PEOPLE) -- gets its own tile, a place in the week-before
line and a top contributor, not only steps, pushups and plank.

Comparing with last time: every real post saves a small snapshot of the channel's
totals, in a row of its own (row_type channel_summary_snapshot), spread across long
text columns the way weekly/leaderboard.py stores its board. The next post reads it
back to say what changed. Everything that can be worked out from the table alone
(who logged on which day, first logs, comebacks, personal bests) does not need it, so
the first weekly post is already useful; volume added, milestones crossed and the
"biggest week yet" headline fill in as snapshots accumulate. `save_snapshot` = false posts without
saving; a dry run never saves.

Input schema:
    workato_dev_api : Workato API token           (required)
    slack_bot_token : xoxb- token, chat:write     (required to post)
    channel_id      : channel to post in          (required to post)
    format          : weekly | classic | random   (optional, default weekly)
    thread_ts       : post as a thread reply      (optional)
    dry_run         : build the message, post nothing, save nothing (optional)
    save_snapshot   : save this run for next time (optional, default true)
    tz_offset       : seconds east of UTC, to decide what "today" is (optional,
                      default -25200, the same default spotter.py uses)
    header_image_url: a banner image above the weekly post (optional, as leaderboard.py)
    mention_people  : name people in the weekly "moments" with a real @mention, which
                      notifies them (optional, default false -- names are bold instead)
    seed_reaction   : put the reaction the closing line asks for on the post itself
                      (optional, default true; needs reactions:write, and is skipped
                      with a warning without it)
    look            : new | old   (optional, default new) how the post is built, in either
                      format. old is the post exactly as it always was: header, sections,
                      fields, context. new uses Slack's newer blocks -- a tile grid (layout),
                      a native chart (data_visualization), cards in a carousel, a native table
                      and titled panels (container) -- with the same words and figures: in the
                      weekly post the badges are the cards and the top contributors the table;
                      in the classic summary the next milestones are the cards and the other
                      activities the table. If Slack refuses a new block (invalid_blocks) that
                      feature is left out and the post sent again, one feature at a time, down
                      to the old post if need be; the error says which block Slack did not
                      like, and `look_used` what went out: new, "new (without tiles)" or old.
    new_features    : which parts of the new look to use (optional, default all): any of
                      headers, tiles, charts, cards, tables, panels, separated by commas.
                      "-charts" takes one away from the full set; "none" is the old post.
                      Only read when look is new. (charts is the weekly post's chart; the
                      classic summary has none, so for it that word changes nothing.)
    snapshot_row_type, today, local_data_file, local_snapshot_file : testing aids

Output: see OUTPUT SCHEMA at the foot of this file.

Anyone with leaderboard_optout set is left out of every figure.
"""

import json
import math
import random
import re
import zlib
from datetime import date, datetime, timedelta, timezone

import requests

TABLE_URL = ("https://data-tables.workato.com/api/v1/tables/"
             "0b863cb1-4712-416b-a9d5-7bf7f2f9b059/query")
SLACK_POST_URL = "https://slack.com/api/chat.postMessage"

COLUMNS = ["id", "name", "row_type", "total", "heatmap_dates", "first_seen",
           "personal_best_single_set", "longest_streak", "leaderboard_optout",
           # the rest of a person's session list, once `total` is full (see session_list)
           "plank_photo", "current_weight", "current_fat", "current_muscle"]

# The activities the summary counts. Others are logged but would clutter the
# headline; they still appear in the participation line.
HEADLINE = ("step", "pushup", "plank")

ICONS = {"plank": ":plank-4:", "pushup": ":plank-3:", "step": ":athletic_shoe:",
         "pullup": ":muscle:", "squat": ":leg:", "run": ":runner:",
         "swim": ":swimmer:", "stairs": ":stairs:", "dance": ":dancer:",
         "yoga": ":person_in_lotus_position:", "meditate": ":brain:",
         "solitude": ":crescent_moon:", "journal": ":writing_hand:",
         "read": ":books:", "breathe": ":wind_blowing_face:",
         "gratitude": ":pray:", "hydrate": ":droplet:", "sleep": ":sleeping:",
         "learn": ":bulb:",
         # Added to spotter.py after this file was written. A row type missing here is
         # never fetched, so a day someone logged only one of these looked like a day
         # they missed. KEEP IN STEP with ACTIVITIES in spotter/spotter.py.
         "workout": ":weight_lifter:", "cardio": ":heartpulse:",
         "cycle": ":bicyclist::skin-tone-4:", "write": ":lower_left_fountain_pen:",
         "chant": ":winter_singing:", "sketch": ":pencil2:", "paint": ":art:",
         "eyepushups": ":eye:",
         "fast": ":empty_battery:", "cold_shower": ":cold_face:"}

# How each activity's headline number reads. Plank is counted in holds rather
# than summed seconds: the sum of everyone's planks is a couple of hours, which
# reads as less than it is, while "86 planks held" is plainly a lot of planks.
COUNT_BY_SESSIONS = set()

# One unbroken effort is a record here; a day total is a sum of several.
SET_BASED = {"plank", "pushup", "pullup", "squat"}
TITLE = {"step": "Steps", "pushup": "Pushups", "plank": "Plank",
         "swim": "Swimming", "yoga": "Yoga", "meditate": "Meditation",
         "pullup": "Pullups", "squat": "Squats", "run": "Running",
         "stairs": "Stairs", "dance": "Dancing", "solitude": "Solitude",
         "journal": "Journalling", "read": "Reading", "breathe": "Pranayama",
         "gratitude": "Gratitude", "hydrate": "Hydration", "sleep": "Sleep",
         "learn": "Learning", "workout": "Workouts", "cardio": "Cardio",
         "cycle": "Cycling", "write": "Writing", "chant": "Chanting",
         "eyepushups": "Eye pushups", "sketch": "Sketching", "paint": "Painting", "fast": "Fasting",
         "cold_shower": "Cold showers"}
NOUN = {"step": "steps", "pushup": "pushups", "plank": "planks held",
        "swim": "swim sessions", "yoga": "yoga sessions",
        "meditate": "meditation sessions"}

# What a single-session record is called.
# How the smaller activities read in the "also happening" list.
# What the number is. Durations read as "6h 40m in the pool" and need no unit;
# counts must name theirs, or "40 reading" leaves people guessing what 40 is.
SECONDARY_NOUN = {"swim": "in the pool", "yoga": "on the mat",
                  "meditate": "sitting", "solitude": "in quiet",
                  "run": "running", "dance": "dancing",
                  "breathe": "of pranayama", "journal": "journalling",
                  "learn": "learning", "sleep": "hours slept",
                  "read": "pages read", "pullup": "pullups",
                  "squat": "squats", "stairs": "flights of stairs",
                  "gratitude": "entries noted", "hydrate": "glasses of water",
                  "workout": "working out", "cardio": "of cardio",
                  "cycle": "cycling", "write": "pages written",
                  "chant": "chanting", "eyepushups": "of eye pushups",
                  "sketch": "sketching",
                  "paint": "painting", "fast": "hours fasted",
                  "cold_shower": "cold showers"}

BEST_LABEL = {"plank": "single hold", "pushup": "single set", "step": "in one day",
              "swim": "longest swim", "yoga": "longest session",
              "meditate": "longest sit"}

# Everything spotter logs in minutes reads as a duration -- "6h 40m running", not
# "400 running", which is what the six after meditate used to say.
DURATION = {"plank": "seconds", "swim": "minutes", "yoga": "minutes",
            "meditate": "minutes", "run": "minutes", "dance": "minutes",
            "solitude": "minutes", "journal": "minutes", "breathe": "minutes",
            "learn": "minutes", "workout": "minutes", "cardio": "minutes",
            "cycle": "minutes", "chant": "minutes", "sketch": "minutes",
            "paint": "minutes", "eyepushups": "minutes"}

# The channel's own team emoji. One is picked at random each run, so the post wears a
# different one every week.
TEAM_EMOJIS = (":extreme-teamwork:", ":teamwork2:", ":teamwork-2:", ":team:",
               ":teamwork-high-five:", ":teamwork-:", ":teamwork-1:", ":team_parrot:")


def team_emoji():
    return random.choice(TEAM_EMOJIS)


STRIDE_M = 0.715          # see weekly_steps.py for why this figure

# A repeating ladder per activity, plus a permanent tier that never resets.
#
# A single ever-receding target ("350,000 steps") gets further away as the
# channel grows and is crossed once, quietly. A ladder that repeats gives a
# near milestone every week or two -- something to look forward to and to
# celebrate -- while the completed-tier count carries the long-term pride.
LADDERS = {
    "step":   {"cycle": 1000000,
               "rungs": [250000, 500000, 750000, 1000000],
               "tier": "\u00d7 1,000,000 steps",
               "unit": "steps"},
    "pushup": {"cycle": 5000,
               "rungs": [1000, 2000, 3000, 4000, 5000],
               "tier": "\u00d7 5,000 pushups",
               "unit": "pushups"},
    "plank":  {"cycle": 18000,
               "rungs": [3600, 7200, 10800, 14400, 18000],
               "tier": "\u00d7 5 hours of plank",
               "unit": "of plank"},
}


def milestone_banner(activity, count, amount):
    """"3 x 1,000 pushups, done" -- one already-finished chunk of an activity,
    whether that's a full lap (amount = the lap's cycle) or a rung cleared
    inside the lap still in progress (amount = one rung's worth).

    Plank spells its amount out in hours ("1 hour") rather than the "1h"
    used everywhere else in the message -- this is the one place the number
    is read as a unit being multiplied, and "3 x 1h" reads like a typo where
    "3 x 1 hour" reads like arithmetic.
    """
    if activity == "plank":
        hours = amount // 3600
        return "{} \u00d7 {} hour{} of plank, done".format(
            count, hours, "" if hours == 1 else "s")
    spec = LADDERS.get(activity) or {}
    return "{} \u00d7 {} {}, done".format(
        count, humanize(activity, amount), spec.get("unit", activity))


def ladder_position(activity, total):
    """Where this activity stands: tiers banked, and the rung either side.

    Progress is measured from the last rung crossed to the next one, not from
    zero -- so the bar always shows movement people can feel, however large the
    running total gets.
    """
    spec = LADDERS.get(activity)
    if not spec:
        return None
    total = int(total or 0)
    tiers, within = divmod(total, spec["cycle"])
    reached = [r for r in spec["rungs"] if r <= within]
    current = max(reached) if reached else 0
    upcoming = [r for r in spec["rungs"] if r > within]
    nxt = upcoming[0] if upcoming else spec["cycle"]
    span = nxt - current
    rung_step = spec["rungs"][0] if spec["rungs"] else 0
    return {"tiers": tiers, "within": within, "current": current, "next": nxt,
            "to_go": max(0, nxt - within), "tier_noun": spec["tier"],
            "rung_step": rung_step,
            "rung_count": (current // rung_step) if rung_step else 0,
            "share": (float(within - current) / span) if span > 0 else 1.0}


# --------------------------------------------------------------------- data

def decode_rows(body):
    """The query endpoint returns schema and data as arrays-of-arrays."""
    columns = [f.get("name") for group in body.get("schema", []) for f in group]
    return [dict(zip(columns, [v for group in row for v in group]))
            for row in body.get("data", [])]


def fetch_rows(token, where):
    """POST to the query endpoint, following continuation tokens."""
    rows, continuation_token = [], None
    while True:
        payload = {"where": where, "select": COLUMNS, "limit": 200}
        if continuation_token:
            payload["continuation_token"] = continuation_token
        response = requests.post(
            TABLE_URL,
            headers={"Authorization": "Bearer {}".format(token),
                     "Content-Type": "application/json"},
            json=payload, timeout=30)
        if response.status_code >= 400:
            raise ConnectionError("Workato {}: {}".format(
                response.status_code, response.text[:400]))
        body = response.json()
        rows.extend(decode_rows(body))
        continuation_token = body.get("continuation_token")
        if not continuation_token:
            return rows


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
            out.append(int(float(part.strip())))
        except ValueError:
            pass
    return out


def _dates(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


# ------------------------------------------------------------------ shaping

def humanize(activity, value):
    """A number in units a person reads without decoding."""
    value = int(value or 0)
    if activity not in DURATION:
        return "{:,}".format(value)
    seconds = value if DURATION[activity] == "seconds" else value * 60
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "{}h {}m".format(hours, minutes) if minutes else "{}h".format(hours)
    if minutes:
        return "{}m {}s".format(minutes, secs) if secs else "{}m".format(minutes)
    return "{}s".format(secs)


def summarize(rows):
    """Totals, bests and participation, computed from the session lists.

    The per-row "best" columns are not trusted here: a back-filled post once
    wrote a three-day sum into one of them, and a summary post is the last place
    you want a number nobody can reproduce. Sessions are the source of truth.
    """
    totals, sessions, bests, people, starts = {}, {}, {}, set(), []
    for row in rows:
        if row.get("leaderboard_optout"):
            continue
        activity = str(row.get("row_type") or "").replace("_users", "")
        values = _numbers(session_list(row))
        if not activity or not values:
            continue
        people.add(row.get("id"))
        totals[activity] = totals.get(activity, 0) + sum(values)
        sessions[activity] = sessions.get(activity, 0) + len(values)
        if row.get("first_seen"):
            starts.append(str(row["first_seen"]))

        # Best single day is the biggest session; best single set comes from the
        # column, which only ever holds one set by definition.
        best = bests.setdefault(activity, {"day": 0, "day_by": "",
                                           "set": 0, "set_by": ""})
        if max(values) > best["day"]:
            best["day"], best["day_by"] = max(values), row.get("name") or ""
        try:
            single = int(row.get("personal_best_single_set") or 0)
        except (TypeError, ValueError):
            single = 0
        if 0 < single <= max(values) and single > best["set"]:
            best["set"], best["set_by"] = single, row.get("name") or ""

    return {"totals": totals, "sessions": sessions, "bests": bests,
            "people": len(people), "since": min(starts) if starts else "",
            "logs": sum(sessions.values())}


def headline_value(activity, facts):
    """What this activity's big number is, and what to call it."""
    if activity in COUNT_BY_SESSIONS:
        return facts["sessions"].get(activity, 0), NOUN.get(activity, activity)
    return facts["totals"].get(activity, 0), NOUN.get(activity, activity)


def pretty_date(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%-d %B")
    except ValueError:
        return str(value)


# ------------------------------------------------------------------ message

BAR_WIDTH = 10

# One hue per activity, so a reader learns which bar is which at a glance.
# Deliberately blue / orange / purple: red-green is the pair the most common
# colour blindness cannot separate, and these three stay distinct for every
# common type. Colour is only ever reinforcement here -- the emoji and the
# activity name carry the identity, so nothing is lost if the hues all read
# the same.
BAR_FILL = {"step": ":large_blue_square:",
            "pushup": ":large_yellow_square:",
            "plank": ":large_green_square:",
            "swim": ":large_blue_square:",
            "yoga": ":large_green_square:",
            "meditate": ":large_yellow_square:"}
BAR_DEFAULT = ":large_blue_square:"
BAR_EMPTY = ":white_large_square:"


def bar(activity, share):
    """An emoji bar, for use outside a code block."""
    share = max(0.0, min(1.0, float(share)))
    filled = int(round(share * BAR_WIDTH))
    fill = BAR_FILL.get(activity, BAR_DEFAULT)
    return fill * filled + BAR_EMPTY * (BAR_WIDTH - filled)


# The same squares as characters. A card's body takes 200 characters, and ten :shortcodes:
# are 193 of them before a word is said; as characters they are ten.
BAR_SQUARES = {":large_blue_square:": "\U0001F7E6", ":large_yellow_square:": "\U0001F7E8",
               ":large_green_square:": "\U0001F7E9", ":white_large_square:": "\u2B1C"}


def compact_bar(activity, share):
    """bar(), in emoji characters rather than :shortcodes:, for where length is limited."""
    text = bar(activity, share)
    for code, char in BAR_SQUARES.items():
        text = text.replace(code, char)
    return text


BLOCK_FULL, BLOCK_EMPTY = "\u2588", "\u2591"


def text_bar(share, width=12):
    """A bar for inside a ``` block, where emoji do not render.

    A fenced block is monospace and neutral-coloured, which is what makes the
    columns line up. Single backticks are the thing to avoid -- Slack paints
    inline code red, and a red progress bar reads as an error.
    """
    share = max(0.0, min(1.0, float(share)))
    filled = int(round(share * width))
    return BLOCK_FULL * filled + BLOCK_EMPTY * (width - filled)


COLUMN_GAP = "    "      # four spaces; two ran the columns together


def fence(rows, headers, align=None):
    """Rows of equal-length tuples as one aligned ``` block.

    align is one character per column, "l" or "r". Numbers read right-aligned
    so the digits stack; words read left-aligned. Getting that backwards is
    what makes a text table look broken.
    """
    if not rows:
        return ""
    align = align or ("l" + "r" * (len(headers) - 1))
    widths = [max(len(str(r[i])) for r in list(rows) + [headers])
              for i in range(len(headers))]

    def cell(value, index):
        value = str(value)
        return (value.rjust(widths[index]) if align[index] == "r"
                else value.ljust(widths[index]))

    out = [COLUMN_GAP.join(cell(c, i) for i, c in enumerate(headers)).rstrip()]
    for row in rows:
        out.append(COLUMN_GAP.join(
            cell(c, i) for i, c in enumerate(row)).rstrip())
    return "```\n" + "\n".join(out) + "\n```"


def progress_table(facts):
    """The three headline activities as one aligned block."""
    rows = []
    for activity in HEADLINE:
        value, _noun = headline_value(activity, facts)
        spot = ladder_position(activity, value)
        if not value or not spot:
            continue
        rows.append((TITLE.get(activity, activity.title()),
                     humanize(activity, value),
                     humanize(activity, spot["to_go"]),
                     humanize(activity, spot["next"]),
                     "{}   {:>3.0f}%".format(text_bar(spot["share"]),
                                             spot["share"] * 100)))
    return fence(rows, ("", "total", "to go", "next", "progress"),
                 align="lrrrl")


def progress_bars(facts):
    """The same three, as emoji bars.

    These live outside the fence on purpose: a fenced block is the only way to
    line the numbers up, and emoji do not render inside one. So the numbers get
    the fence and the colour goes underneath it.
    """
    lines = []
    for activity in HEADLINE:
        value, _noun = headline_value(activity, facts)
        spot = ladder_position(activity, value)
        if not value or not spot:
            continue
        # No numbers here -- the fence above already carries them, and saying
        # them twice is what made the first draft read as a wall of figures.
        lines.append("{}  {}  *{:.0f}%*  {}".format(
            ICONS.get(activity, ""), bar(activity, spot["share"]),
            spot["share"] * 100, TITLE.get(activity, activity.title())))
    return "\n".join(lines)


def classic_line(facts):
    """The line under the title: how many people, how many sessions, since when."""
    line = "*{}* people  ·  *{:,}* sessions".format(facts["people"], facts["logs"])
    if facts["since"]:
        line += "  ·  since {}".format(pretty_date(facts["since"]))
    return line


def classic_banked(facts):
    """The milestones the channel has already finished, one line each: a full lap (steps'
    "1 x 1,000,000, done") and, just as prominently, every rung cleared inside a
    lap still in progress (pushups' "3 x 1,000", plank's "3 x 1 hour"). All
    of it leads, because it is the part that never resets -- the bars below
    start from zero again after a lap, and without this the reset would
    read as losing ground. Everything here gets equal, bold billing -- a
    rung is as real a milestone as a lap, just a smaller one, and burying it
    in a dim context line under only steps' banner made it look like steps
    was the only activity with anything worth banking."""
    banked = []
    for activity in HEADLINE:
        value, _noun = headline_value(activity, facts)
        spot = ladder_position(activity, value)
        if not spot:
            continue
        if spot["tiers"]:
            banked.append("{}  *{}*".format(
                ICONS.get(activity, ""),
                milestone_banner(activity, spot["tiers"], LADDERS[activity]["cycle"])))
        # A rung inside the lap in progress only earns its own line while no
        # lap has been finished yet -- once one has, that lap banner is the
        # headline and a rung of the next lap under the same icon reads as
        # the activity being listed twice, not as two different milestones.
        elif spot["rung_count"]:
            banked.append("{}  *{}*".format(
                ICONS.get(activity, ""),
                milestone_banner(activity, spot["rung_count"], spot["rung_step"])))
    return banked


def classic_standing(facts):
    """[(share, activity, value, where it stands)] for the headline activities, the closest
    to its milestone first. Leading with "4 minutes from two hours"
    is an invitation; leading with the goal 80% away buries the one thing
    somebody could actually finish tonight."""
    standing = []
    for activity in HEADLINE:
        value, _noun = headline_value(activity, facts)
        spot = ladder_position(activity, value)
        if value and spot:
            standing.append((spot["share"], activity, value, spot))
    standing.sort(reverse=True)
    return standing


def classic_standing_line(facts, share, activity, value, spot):
    """One activity's progress as two lines of text: where it stands, then the bar."""
    line = "{}  *{}*  ·  {}".format(
        ICONS.get(activity, ""), TITLE.get(activity, activity.title()),
        humanize(activity, value))
    if activity == "step":
        line += "  ·  {:,.0f} km".format(
            facts["totals"]["step"] * STRIDE_M / 1000.0)
    # The percentage says how far along; the gap says what is left. They
    # answer different questions, so the line carries both.
    line += "  ·  *{:.0f}%*".format(share * 100)
    if share >= 0.85:
        line += " — almost there"
    # "117 to 500" reads as "117 out of 500". It means 117 remaining.
    line += "\n{}  *{}* to go → *{}*".format(
        bar(activity, share), humanize(activity, spot["to_go"]),
        humanize(activity, spot["next"]))
    return line


def classic_other_activities(facts):
    """The activities outside the headline three, the most logged first.

    For plank and pushup the record people care about is the single hold or
    single set -- one unbroken effort. A day total is a sum of several, and
    for steps it is the only thing there is, so steps alone uses the day.
    Everything else people log. Deliberately compact and without bars: these
    are small numbers, and a half-empty progress bar next to a 92% one reads
    as failure rather than variety. Shown as an opening instead -- the people
    doing them see their work counted, and newcomers see there is more here
    than planks, with room to be first at something."""
    return [a for a in sorted(facts["totals"], key=lambda a: -facts["sessions"][a])
            if a not in HEADLINE]


def classic_other_line(facts, activity):
    """One of the other activities as a line. Named: "6h 40m in the pool" leaves people
    working out which trigger that was."""
    count = facts["sessions"][activity]
    return "{}  *{}*  ·  {} {}  ·  {} session{}".format(
        ICONS.get(activity, ""), TITLE.get(activity, activity.title()),
        humanize(activity, facts["totals"][activity]),
        SECONDARY_NOUN.get(activity, activity), count,
        "" if count == 1 else "s")


# An open invitation, not a ranking and not a nudge towards whichever is "easiest" -- people
# pick up an activity because it suits them, not because it is unclaimed.
CLASSIC_INVITE = "Pick whichever one suits you — it all counts here."


def classic_closing_blocks(standing):
    """The last two words of the post: that the streak holds over the weekend, then an
    invitation that names whatever is genuinely closest rather than a fixed activity -- so
    it stays true every week."""
    blocks = [{"type": "divider"},
              {"type": "section", "text": {"type": "mrkdwn",
               "text": ">That's the week. *Your streak holds over the weekend* "
                       "— Monday picks up where Friday left off, so rest "
                       "properly if you need it.\n>_Anything you log Saturday or "
                       "Sunday is a bonus._ :wave:"}}]
    if standing:
        share, activity, _value, spot = standing[0]
        name = TITLE.get(activity, activity.title()).lower()
        if share >= 0.85:
            call = ("*{}* of {} and we clear *{}*. Who's closing it out? :dart:"
                    .format(humanize(activity, spot["to_go"]), name,
                            humanize(activity, spot["next"])))
        else:
            call = ("Nearest one up is *{}* — *{}* to go. Every log counts "
                    "toward it. :dart:".format(
                        name, humanize(activity, spot["to_go"])))
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": call}})
    return blocks


def old_classic_blocks(facts, team):
    """The classic all-time summary as it always was: sections, a divider, one context line."""
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
               # A zero-width space on its own line. A bare "\n" gets trimmed
               # by Slack; this survives and keeps the title off the app name.
               "text": "​\n{}  *How far we've come*".format(team)}}]
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": classic_line(facts)}})

    banked = classic_banked(facts)
    if banked:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": "*Already banked*\n" + "\n".join(banked)}})

    standing = classic_standing(facts)

    # A heading, or the bars just start after "Already banked" with nothing
    # saying what they are counting towards.
    if standing:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": ":dart:  *Up next*"}})

    for share, activity, value, spot in standing:
        blocks.append({"type": "section", "text": {
            "type": "mrkdwn",
            "text": classic_standing_line(facts, share, activity, value, spot)}})

    others = [classic_other_line(facts, a) for a in classic_other_activities(facts)]
    if others:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn",
                       "text": ":seedling:  *Also happening here*\n"
                               + "\n".join(others)}})
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": CLASSIC_INVITE}]})

    blocks.extend(classic_closing_blocks(standing))
    return blocks


def build_classic_blocks(facts, look=None, team=""):
    """The classic all-time summary: totals, milestones banked, progress towards the next
    rung. `look` is a Look (parse_look), as for the weekly post: the new look's features, or
    OLD_LOOK / None for the summary as it always was. `team` is the team emoji it wears; one
    is picked when it is blank."""
    team = team or team_emoji()
    if look is not None and look.new:
        return new_classic_blocks(look, facts, team)
    return old_classic_blocks(facts, team)


def fallback_text(facts):
    parts = []
    for activity in HEADLINE:
        value, noun = headline_value(activity, facts)
        if value:
            parts.append("{:,} {}".format(value, noun))
    return "Where we've got to — " + " · ".join(parts)


def post(token, channel, text, blocks, thread_ts=""):
    payload = {"channel": channel, "text": text, "blocks": blocks}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    response = requests.post(
        SLACK_POST_URL,
        headers={"Authorization": "Bearer {}".format(token),
                 "Content-Type": "application/json; charset=utf-8"},
        json=payload, timeout=30)
    body = response.json()
    if not body.get("ok"):
        error = str(body.get("error") or "unknown")
        # For invalid_blocks Slack says which block and why ("unsupported type: layout
        # [json-pointer:/blocks/4/type]"). Kept, so the error names the one to switch off.
        notes = (body.get("response_metadata") or {}).get("messages") or []
        if notes:
            error += ": " + "; ".join(str(note) for note in notes[:2])[:300]
        return False, error, ""
    return True, "", body.get("ts") or ""


def react(token, channel, ts, emoji):
    """Put a reaction on the post. Returns an error string, or '' when it is on."""
    name = str(emoji or "").strip(":").split("::")[0]
    if not name:
        return ""
    try:
        response = requests.post(
            "https://slack.com/api/reactions.add",
            headers={"Authorization": "Bearer {}".format(token),
                     "Content-Type": "application/json; charset=utf-8"},
            json={"channel": channel, "timestamp": ts, "name": name}, timeout=30)
        body = response.json()
    except Exception as exc:  # noqa: BLE001 -- a reaction must never cost the post
        return "{}: {}".format(type(exc).__name__, str(exc)[:120])
    if body.get("ok") or body.get("error") == "already_reacted":
        return ""
    return str(body.get("error") or "unknown")


# ------------------------------------------------------------ last time (snapshot)
#
# Every real post saves what the channel looked like, so the next one can say what
# changed. It lives in one row of the data table (row_type SNAPSHOT_ROW_TYPE), as JSON cut
# into pieces across long text columns -- the same trick weekly/leaderboard.py uses for its
# board, because one Workato text column holds 10,000 characters. The JSON is sealed with
# its length and a checksum, so a cut-off or half-edited column is reported instead of
# being read as a smaller history.
#
# What is stored, per run:  {"d": date, "t": {activity: total}, "n": {activity: sessions},
#                           "p": people, "w": {"people", "checkins", "new"},
#                           "b": {person: [highest badge of each family]}}
# t / n / p are what the next run diffs against; w is the week as the post announced it;
# b (kept for the latest runs only) is what tells the next run which badges are new.
#
# Never reorder or remove a column in STORE_COLUMNS -- the order is the order of the data.
# To add room, append one. These three are the leaderboard's own snapshot columns and are
# unused on an activity row, and this row has a row_type of its own.

SNAPSHOT_ROW_TYPE = "channel_summary_snapshot"
SNAPSHOT_VERSION = 1
SNAPSHOT_RUNS = 26
BADGE_RUNS_KEPT = 2
STORE_COLUMNS = ("golden_dates", "heatmap_dates", "total")
COLUMN_CHUNK = 9500
SNAPSHOT_ROOM = COLUMN_CHUNK * len(STORE_COLUMNS) - 64      # room for the seal
RECORDS_URL = ("https://data-tables.workato.com/api/v1/tables/"
               "0b863cb1-4712-416b-a9d5-7bf7f2f9b059/records")
WRITE_COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "total": "e96b5acc-4196-497e-a18b-7faf7016ec4c",
    "heatmap_dates": "7f8871d1-1613-4faa-94e6-a7ef3649cc25",
    "golden_dates": "b9517b86-4175-4d78-80b1-dfbf832f803c",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
}

# A run counts as "last time" only if it is at least this old. A second post the same
# week must still be compared with last week, not with the post an hour ago.
MIN_BASELINE_DAYS = 4

SEAL = re.compile(r"^~(\d+):([0-9a-f]{8})~")


def send_json(url, headers, payload, method="POST"):
    """(body, error). Never raises on an HTTP or network failure."""
    try:
        response = requests.request(method, url, headers=headers, json=payload,
                                    timeout=30)
    except requests.RequestException as exc:
        return None, "{}: {}".format(type(exc).__name__, str(exc)[:200])
    if response.status_code >= 400:
        return None, "{} {}: {}".format(
            url.split("/")[2], response.status_code, response.text[:400])
    try:
        return response.json(), None
    except ValueError:
        return {}, None


def seal(text):
    return "~{}:{:08x}~{}".format(
        len(text), zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF, text)


def unseal(stored):
    """(text, error). Text with no header is taken as it is."""
    match = SEAL.match(stored)
    if not match:
        return stored, None
    body = stored[match.end():]
    ok = (len(body) == int(match.group(1)) and
          "{:08x}".format(zlib.crc32(body.encode("utf-8")) & 0xFFFFFFFF) == match.group(2))
    return (body, None) if ok else (None, "failed its integrity check")


def run_date(run):
    try:
        return datetime.strptime(str(run.get("d")), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_runs(text):
    """(runs, error). Empty text is no history yet; damaged text is an error, so it is
    never mistaken for a first run (and never overwritten)."""
    if not str(text or "").strip():
        return [], None
    body, error = unseal(text)
    try:
        data = json.loads(body) if body is not None else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("runs"), list):
        return [], "snapshot row exists but is unreadable ({}); left as it is".format(
            error or "corrupt or cut off")
    runs = [r for r in data["runs"]
            if isinstance(r, dict) and isinstance(r.get("t"), dict) and run_date(r)]
    return runs, None


def snapshot_text(runs):
    return json.dumps({"v": SNAPSHOT_VERSION, "runs": runs},
                      separators=(",", ":"), ensure_ascii=False)


def with_run(runs, run, keep=SNAPSHOT_RUNS):
    """History plus this run. A second run on the same day replaces the first."""
    merged = [r for r in runs if r.get("d") != run["d"]] + [run]
    merged.sort(key=lambda r: r["d"])
    merged = merged[-keep:]
    # Badges are only ever compared with the latest run or two, so older ones are shed:
    # kept for every run they would crowd out the totals the volume trend needs.
    for older in merged[:-BADGE_RUNS_KEPT]:
        older.pop("b", None)
    while len(merged) > 1 and len(snapshot_text(merged)) > SNAPSHOT_ROOM:
        merged = merged[1:]
    return merged


class TableSnapshot(object):
    """One row, row_type SNAPSHOT_ROW_TYPE. load() then save(); a save is refused when
    the row could not be read, rather than writing over it."""

    def __init__(self, token, row_type):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.row_type = row_type
        self.record_id = ""
        self.block_reason = ""

    def load(self):
        # No select: the update path needs the $record_id metafield.
        body, error = send_json(
            TABLE_URL, self.headers,
            {"where": {"row_type": {"$eq": self.row_type}}, "limit": 1})
        if error:
            self.block_reason = "the earlier read failed"
            return [], "snapshot read " + error
        rows = decode_rows(body)
        if not rows:
            return [], None
        self.record_id = rows[0].get("$record_id") or ""
        stored = "".join(str(rows[0].get(c) or "") for c in STORE_COLUMNS)
        runs, error = parse_runs(stored)
        if error:
            self.block_reason = "the existing row is unreadable"
        return runs, error

    def save(self, runs):
        if self.block_reason:
            return "snapshot not saved: " + self.block_reason
        text = seal(snapshot_text(runs))
        pieces = [text[i:i + COLUMN_CHUNK] for i in range(0, len(text), COLUMN_CHUNK)]
        if len(pieces) > len(STORE_COLUMNS):
            return "snapshot not saved: too big for {} columns".format(len(STORE_COLUMNS))
        fields = {"record_key": self.row_type, "row_type": self.row_type,
                  "id": "channel_summary", "name": self.row_type,
                  "updated_at": runs[-1]["d"]}
        # Unused columns are cleared so a shrinking snapshot leaves nothing stale.
        for index, column in enumerate(STORE_COLUMNS):
            fields[column] = pieces[index] if index < len(pieces) else ""
        document = {"$" + WRITE_COLUMNS[k]: v for k, v in fields.items()}
        if self.record_id:
            url, method = RECORDS_URL + "/" + self.record_id, "PUT"
        else:
            url, method = RECORDS_URL, "POST"
        _, error = send_json(url, self.headers, {"document": document}, method)
        return "snapshot save " + error if error else None


class FileSnapshot(object):
    """Offline stand-in for the table, for local testing."""

    def __init__(self, path):
        self.path = path
        self.block_reason = ""

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                stored = handle.read()
        except IOError:
            return [], None
        runs, error = parse_runs(stored)
        if error:
            self.block_reason = "the existing file is unreadable"
        return runs, error

    def save(self, runs):
        if self.block_reason:
            return "snapshot not saved: " + self.block_reason
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(seal(snapshot_text(runs)))
        return None


# ------------------------------------------------------------ the week, from the table
#
# Everything here is worked out from the activity rows alone. heatmap_dates is one entry
# per DAY a person logged (not per session), kept for a year, so who was active on which
# day is reliable history. The session list is not dated, so volume added needs the
# snapshot (see volume_changes).

WEEK_DAYS = 7
TREND_WEEKS = 8
COMEBACK_DAYS = 14          # away at least this long before the week
NEW_BEST_MIN_SESSIONS = 4   # a "best" needs something to beat
NEW_BEST_MIN_GAIN = 1.05    # ... and beating it by 43 -> 44 is not worth a line
MAX_MOMENTS = 7             # shout-out lines; the lowest-scoring are the ones dropped
DEFAULT_TZ_OFFSET = -7 * 3600          # as spotter.py: the channel's local date
PEOPLE_MILESTONES = (10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 300, 400,
                     500, 750, 1000)

# Bests that mean something. A "personal best" in glasses of water does not.
BEST_PHRASE = {"step": "biggest day", "pushup": "biggest set", "plank": "longest hold",
               "swim": "longest swim", "yoga": "longest session",
               "meditate": "longest sit", "pullup": "biggest set",
               "squat": "biggest set", "run": "longest run", "cycle": "longest ride",
               "workout": "longest workout", "cardio": "longest session",
               "dance": "longest session", "stairs": "most flights in a day",
               "read": "most pages in a day", "write": "most pages in a day",
               "breathe": "longest session"}
BEST_ACTIVITIES = set(BEST_PHRASE)
RECORD_LINES = 8            # the records spotlight stops here. Five fit one block; a sixth
                            # row starts another, which Slack sets a little further down
# A record is only listed where there is a field to take it from: this many people
# active in the activity over the last RECORD_ACTIVE_DAYS. Under that it is one or two
# people's private tally, and "the channel record" overstates it.
RECORD_MIN_PEOPLE = 4
RECORD_ACTIVE_DAYS = 28

# Which activities get a line of their own in the week's tiles, the week-before line and
# the top contributors: the headline three always, and any other that WEEK_ACTIVITY_MIN_PEOPLE
# or more logged this week, or that was logged on WEEK_ACTIVITY_MIN_CHECKINS or more
# person-days -- so one person's steady week of yoga is counted, not only a crowd's.
WEEK_ACTIVITY_MIN_PEOPLE = 2
WEEK_ACTIVITY_MIN_CHECKINS = 3

# This week's top contributor in each of those activities: who put the most into it over
# the last 7 days -- and only someone who logged it on WEEK_TOP_MIN_DAYS days or more, so
# it is earned by showing up, not by a single log. When the biggest week belongs to someone
# with one log, the activity is left out rather than handed to the runner-up.
WEEK_TOP_MIN_DAYS = 2
WEEK_TOP_LINES = 8          # five rows to a block (see record_blocks), so two blocks at most

# Milestones for every activity, not only the three with a ladder of their own. Steps,
# pushups and plank keep LADDERS (and spotter.py announces those the moment they are
# crossed); everything else climbs a plain run of round numbers -- hours for anything
# timed, a count for anything counted -- once it has a field of people doing it (see
# RECORD_MIN_PEOPLE). Past the end of a run, the last figure repeats as the step.
HOUR_MARKS = (1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 300, 400,
              500, 750, 1000)
COUNT_MARKS = (10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 2500, 3000, 4000,
               5000, 7500, 10000, 15000, 20000, 25000, 50000, 75000, 100000)
# Totals nobody is trying to push up: more hours asleep or fasting is not a goal.
NO_MILESTONE = {"sleep", "fast"}

# Personal round numbers, named the week somebody passes one.
DAY_MARKS = (10, 25, 50, 75, 100, 150, 200, 250, 300, 365)
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
SLACK_USER_ID = re.compile(r"^[UW][A-Z0-9]{6,}$")

# The calendar's heat scale, quiet to very active. Colour is texture here, not the message: the
# count beside each row carries the number, so nothing is lost if the hues read alike.
GRID_LEVELS = (":white_large_square:", ":large_yellow_square:", ":large_orange_square:",
               ":large_red_square:")
GRID_WEEKS = 5
ALSO_CLIMBING = 4           # how many other milestones the closing line lists
# A milestone this close leads the post when nothing bigger happened.
REACH_SHARE = 0.7


def parse_day(text):
    try:
        return datetime.strptime(str(text or "").strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def short_date(day):
    return "{} {} {}".format(day.strftime("%a"), day.day, day.strftime("%b"))


def names_text(labels, limit=3):
    """A, B and C, or A, B, C and 2 more. Labels come ready-made from person_label."""
    shown = list(labels[:limit])
    if len(labels) > limit:
        shown.append("{} more".format(len(labels) - limit))
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def person_label(people, pid, mention=False):
    """How a person is named: bold, or -- when the recipe asks for it -- a real Slack
    mention, which notifies them. Only for an id that is plainly a Slack user id."""
    if mention and SLACK_USER_ID.match(str(pid or "")):
        return "<@{}>".format(pid)
    return "*{}*".format(people[pid]["name"])


def gather_people(rows):
    """One entry per person (opted-out people left out): the days they logged, the day
    of their first log, and each activity's sessions with the days logged."""
    people = {}
    for row in rows:
        if row.get("leaderboard_optout"):
            continue
        activity = str(row.get("row_type") or "").replace("_users", "")
        values = _numbers(session_list(row))
        if not activity or not values:
            continue
        pid = row.get("id") or row.get("name")
        person = people.setdefault(pid, {"name": "", "days": set(), "first": None,
                                         "rows": [], "streak": 0})
        person["name"] = person["name"] or str(row.get("name") or "")
        try:
            person["streak"] = max(person["streak"], int(row.get("longest_streak") or 0))
        except (TypeError, ValueError):
            pass
        days = [d for d in (parse_day(x) for x in _dates(row.get("heatmap_dates"))) if d]
        person["days"].update(days)
        first = parse_day(row.get("first_seen")) or (min(days) if days else None)
        if first and (person["first"] is None or first < person["first"]):
            person["first"] = first
        person["rows"].append({"activity": activity, "values": values, "days": days})
    return people


def window_stats(by_day, end, span=WEEK_DAYS):
    """(people ids, check-ins) over the `span` days ending on `end`. A check-in is one
    person on one day."""
    ids, checkins = set(), 0
    for back in range(span):
        day_ids = by_day.get(end - timedelta(days=back))
        if day_ids:
            ids |= day_ids
            checkins += len(day_ids)
    return ids, checkins


def week_facts(people, today):
    """The last 7 days against the 7 before, from the table alone."""
    by_day = {}
    for pid, person in people.items():
        for day in person["days"]:
            by_day.setdefault(day, set()).add(pid)
    start = today - timedelta(days=WEEK_DAYS - 1)
    firsts = [p["first"] for p in people.values() if p["first"]]
    first_day = min(firsts) if firsts else None

    ids, checkins = window_stats(by_day, today)
    prev_ids, prev_checkins = window_stats(by_day, today - timedelta(days=WEEK_DAYS))

    # Weekly history, oldest first, from the week the channel began.
    weeks = []
    for back in range(TREND_WEEKS - 1, -1, -1):
        end = today - timedelta(days=WEEK_DAYS * back)
        if first_day and end >= first_day:
            w_ids, w_checkins = window_stats(by_day, end)
            weeks.append((len(w_ids), w_checkins))
    older = []
    for back in range(1, 53):
        end = today - timedelta(days=WEEK_DAYS * back)
        if first_day and end >= first_day:
            older.append(len(window_stats(by_day, end)[0]))
    record_week = (len(ids) >= 3 and len(older) >= 3 and len(ids) > max(older))

    # Busiest weekday, over the four weeks up to YESTERDAY. Today is still being logged
    # when this posts, and half a day counted as a whole one made the posting day look
    # like the quietest of the week.
    weekday = [0] * 7
    for back in range(1, 29):
        day = today - timedelta(days=back)
        weekday[day.weekday()] += len(by_day.get(day, ()))

    # The calendar: one row per 7 days, each ending on today's weekday, so every row is
    # whole and the newest row is exactly the week the post is about.
    grid = []
    for back in range(GRID_WEEKS - 1, -1, -1):
        end = today - timedelta(days=WEEK_DAYS * back)
        if first_day and end < first_day:
            continue
        days = [end - timedelta(days=WEEK_DAYS - 1 - i) for i in range(WEEK_DAYS)]
        grid.append((end, [len(by_day.get(d, ())) for d in days],
                     len(window_stats(by_day, end)[0])))

    # Showed up on every working day of the week -- up to YESTERDAY. The post goes out
    # while today is still being logged, and requiring today dropped everyone who had
    # not posted yet: on a Friday afternoon that is most of the people who qualify.
    working = [start + timedelta(days=i) for i in range(WEEK_DAYS)]
    working = [d for d in working if d.weekday() < 5 and d < today]
    steady = sum(1 for p in people.values()
                 if working and all(d in p["days"] for d in working))

    # Each activity's week: [people who logged it, person-days logged] (see week_activities).
    by_activity = {}
    for p in people.values():
        for entry in p["rows"]:
            logged = len([d for d in entry["days"] if start <= d <= today])
            if logged:
                counts = by_activity.setdefault(entry["activity"], [0, 0])
                counts[0] += 1
                counts[1] += logged
    activities = set(by_activity)

    newcomers = sorted((p["first"], pid) for pid, p in people.items()
                       if p["first"] and p["first"] >= start and p["name"])
    return {"by_day": by_day, "start": start, "ids": ids, "checkins": checkins,
            "prev_people": len(prev_ids), "prev_checkins": prev_checkins,
            "weeks": weeks, "record_week": record_week, "weekday": weekday,
            "grid": grid, "first_day": first_day, "steady": steady,
            "working_days": len(working), "activities": len(activities),
            "by_activity": by_activity, "new_people": [pid for _, pid in newcomers]}


def week_activities(week):
    """The activities with a line of their own this week (see WEEK_ACTIVITY_MIN_PEOPLE):
    the headline three, then the rest, the most check-ins first."""
    counts = week.get("by_activity") or {}
    others = [a for a, (logged_by, checkins) in counts.items() if a not in HEADLINE and (
        logged_by >= WEEK_ACTIVITY_MIN_PEOPLE or checkins >= WEEK_ACTIVITY_MIN_CHECKINS)]
    others.sort(key=lambda a: (-counts[a][1], -counts[a][0], a))
    return list(HEADLINE) + others


def weekday_pace(week):
    """(busiest weekday name, quietest weekday name) or ('', '') when too thin to say."""
    counts = week["weekday"]
    if sum(counts) < 7 or max(counts) == min(counts):
        return "", ""
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return (names[counts.index(max(counts))], names[counts.index(min(counts))])


# ---------------------------------------------------------- volume against last time

def thin_runs(runs, today):
    """Past runs at least MIN_BASELINE_DAYS apart, oldest first, so daily test posts do
    not turn the history into noise."""
    dated = sorted(((run_date(r), r) for r in runs if run_date(r)), key=lambda x: x[0])
    kept, last = [], today
    for day, run in reversed(dated):
        if day < today and (last - day).days >= MIN_BASELINE_DAYS:
            kept.append((day, run))
            last = day
    kept.reverse()
    return kept


def per_week(gain, days):
    return None if gain is None or days <= 0 else gain * WEEK_DAYS / float(days)


def volume_changes(facts, runs, today):
    """What was added since the last snapshot. None when there is no usable one.

    {"days": N since the baseline, "gain": {activity: added or None},
     "prev": {activity: added the stretch before, or None}, "prev_days": M,
     "series": {activity: per-week gains, oldest first, None for a gap},
     "record": {activity: True if this stretch beat every earlier one},
     "base": the baseline run}
    A total that went DOWN (someone opted out) is unknown, not a negative week.
    """
    kept = thin_runs(runs, today)
    if not kept:
        return None
    base_day, base = kept[-1]
    days = (today - base_day).days
    totals = facts["totals"]
    out = {"days": days, "gain": {}, "prev": {}, "prev_days": 0, "series": {},
           "record": {}, "base": base}
    points = [(d, r["t"]) for d, r in kept] + [(today, totals)]
    out["prev_days"] = (base_day - kept[-2][0]).days if len(kept) > 1 else 0
    for activity in totals:
        gaps = []
        for (d1, t1), (d2, t2) in zip(points, points[1:]):
            raw = int(t2.get(activity, 0) or 0) - int(t1.get(activity, 0) or 0)
            gaps.append((raw if raw >= 0 else None, (d2 - d1).days))
        out["gain"][activity] = gaps[-1][0]
        out["prev"][activity] = gaps[-2][0] if len(gaps) > 1 else None
        rates = [per_week(g, n) for g, n in gaps][-TREND_WEEKS:]
        out["series"][activity] = rates
        earlier = [r for r in rates[:-1] if r is not None]
        out["record"][activity] = bool(
            rates and rates[-1] and len(earlier) >= 3 and rates[-1] > max(earlier))
    return out


def span_label(days):
    """'this week' for a stretch that is about a week; otherwise say how long."""
    return "this week" if 5 <= days <= 9 else "in the last {} days".format(days)


# ------------------------------------------------------------------------ milestones

def unit_of(activity):
    """What a total of this activity is a total OF, to follow a figure: "750,000
    steps", "15 hours of yoga", "500 pages read"."""
    if activity in LADDERS:
        return LADDERS[activity]["unit"]
    if activity in DURATION:
        return "of " + TITLE.get(activity, activity).lower()
    return SECONDARY_NOUN.get(activity, activity.replace("_", " "))


def per_hour(activity):
    """How many of the activity's own units make an hour (it is logged in seconds or
    minutes)."""
    return 3600 if DURATION.get(activity) == "seconds" else 60


def personal_marks(activity):
    """The round numbers a person's own total climbs, in the activity's own units."""
    if activity in NO_MILESTONE:
        return ()
    if activity not in DURATION:
        return PERSONAL_MARKS.get(activity, PERSONAL_DEFAULT_COUNT)
    per_minute = per_hour(activity) // 60              # 1 for minutes, 60 for seconds
    return tuple(m * per_minute for m in PERSONAL_MARKS.get(activity, PERSONAL_DEFAULT_MINUTES))


def stop_for(activity, total):
    """Where a channel total stands between two milestones:
    {"reached": the last one passed, "target": the next, "to_go", "share"} -- all as
    running totals, whichever kind of ladder the activity climbs."""
    total = int(total or 0)
    if activity in LADDERS:
        spot = ladder_position(activity, total)
        return {"reached": spot["tiers"] * LADDERS[activity]["cycle"] + spot["current"],
                "target": total + spot["to_go"], "to_go": spot["to_go"],
                "share": spot["share"]}
    marks = (tuple(h * per_hour(activity) for h in HOUR_MARKS)
             if activity in DURATION else COUNT_MARKS)
    ahead = [m for m in marks if m > total]
    if ahead:
        reached = max([m for m in marks if m <= total] or [0])
        target = ahead[0]
    else:
        reached = (total // marks[-1]) * marks[-1]
        target = reached + marks[-1]
    return {"reached": reached, "target": target, "to_go": target - total,
            "share": (total - reached) / float(target - reached)}


def active_fields(people, today):
    """{activity: ids of the people who logged it in the last RECORD_ACTIVE_DAYS}."""
    since = today - timedelta(days=RECORD_ACTIVE_DAYS - 1)
    doing = {}
    for pid, person in people.items():
        for entry in person["rows"]:
            if any(since <= d <= today for d in entry["days"]):
                doing.setdefault(entry["activity"], set()).add(pid)
    return doing


def milestone_activities(facts, doing):
    """The activities with a milestone to climb: the headline three always, then any
    other with a field of people active in it, most-logged first."""
    others = [a for a in facts["totals"]
              if a not in HEADLINE and a not in NO_MILESTONE
              and len(doing.get(a, ())) >= RECORD_MIN_PEOPLE]
    others.sort(key=lambda a: (-facts["sessions"].get(a, 0), a))
    return [a for a in HEADLINE if facts["totals"].get(a)] + others


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


# ----------------------------------------------------- badges and the journey, in the post

BADGE_RECENT_DAYS = 14     # with a snapshot to compare against, ignore anything older

# Every badge earned is listed, as a two-column grid of cards like the email summary's: one
# cell per badge, its emoji and name over everyone who earned it. Laid out kind by kind --
# the four kinds of BADGE_KINDS in email_summary/email_summary.py -- so the emoji run in
# blocks and say which badges belong together without a heading for each. A family not
# listed here comes last, so nothing earned is left off.
BADGE_KINDS = (
    ("streak",),                                        # daily streaks
    ("steady",),                                        # weekly streaks
    ("perfect", "month"),                               # attendance
    ("explorer", "allround", "triple", "weekend"),      # variety
)
BADGE_NAMES_ROOM = 1900    # a cell's names; past it they are counted. Slack takes 2,000 a field


def stop_name(stop):
    """A route stop as it starts a sentence: "the Grand Canyon" -> "The Grand Canyon"."""
    name = stop[0]
    return name[:1].upper() + name[1:]


def badge_state(people, today):
    """{person id: {badge id: day earned}} for everyone with a name."""
    firsts = [p["first"] for p in people.values() if p["first"]]
    channel_first = min(firsts) if firsts else None
    return {pid: badge_dates(person, today, channel_first)
            for pid, person in people.items() if person["name"]}


def badge_snapshot(state):
    """What a run stores about badges: each person's highest badge in every family. That
    is all the next run needs to tell what is new, and it is small."""
    return {pid: sorted(b["id"] for b in top_badges(dates))
            for pid, dates in state.items() if dates}


def previous_badges(runs, today):
    """The badges stored by the run this one is compared with, or None when there is
    none (the first run, or history from before badges existed)."""
    for _day, run in reversed(thin_runs(runs, today)):
        if "b" in run:
            return run["b"]
    return None


def new_badges(state, today, previous):
    """[(badge, [person ids])], most prestigious first: what was earned since last time.

    Compared with the badges the last post stored when there is one, so nobody is missed
    (a log made after the last post still counts) and nobody is named twice. Without one
    -- the first post -- the last seven days stand in. The highest new tier in a family is
    the one named: somebody who reaches Month of Momentum is not also told about Five in
    a Row. First Step is left to the welcome line, which already says it.
    """
    start = today - timedelta(days=WEEK_DAYS - 1)
    recent = today - timedelta(days=BADGE_RECENT_DAYS - 1)
    found = {}
    for pid, dates in state.items():
        if previous is None:
            ids = [i for i, day in dates.items() if day >= start]
        else:
            held = {}
            for old in previous.get(pid, ()):
                if old in BADGES:
                    held[BADGES[old]["family"]] = max(
                        held.get(BADGES[old]["family"], -1), BADGES[old]["tier"])
            ids = [i for i, day in dates.items()
                   if day >= recent and BADGES[i]["tier"] > held.get(BADGES[i]["family"], -1)]
        for badge in top_badges([i for i in ids if BADGES[i]["family"] != "first"]):
            found.setdefault(badge["id"], []).append(pid)
    ranked = sorted(found, key=lambda i: (-BADGES[i]["prestige"], BADGES[i]["name"]))
    return [(BADGES[i], sorted(found[i])) for i in ranked]


def badge_kind(badge):
    """Where a badge's kind comes in BADGE_KINDS; a family not listed comes after them."""
    for order, families in enumerate(BADGE_KINDS):
        if badge["family"] in families:
            return order
    return len(BADGE_KINDS)


def badge_cell(people, badge, pids, mention=False):
    """One badge's card: the emoji and name, and under them everyone who earned it. Every
    name is said, unless a crowd would pass BADGE_NAMES_ROOM -- then as many as fit, and
    the rest are counted."""
    labels = [person_label(people, pid, mention) for pid in pids]
    shown = len(labels)
    while len(names_text(labels, limit=shown)) > BADGE_NAMES_ROOM and shown > 1:
        shown -= 1
    return "{}  *{}*\n{}".format(badge["emoji"], badge["name"], names_text(labels, limit=shown))


def badge_order(earned):
    """What was earned, kind by kind and the highest tiers of a kind first."""
    return sorted(earned, key=lambda item: (badge_kind(item[0]), -item[0]["prestige"]))


def badge_fields(people, earned, mention=False):
    """Every badge as a cell in a two-column grid (a section's fields). Ten cells fill a
    block; more carry on in the next."""
    cells = [{"type": "mrkdwn", "text": badge_cell(people, badge, pids, mention)}
             for badge, pids in badge_order(earned)]
    return [{"type": "section", "fields": cells[start:start + FIELDS_PER_BLOCK]}
            for start in range(0, len(cells), FIELDS_PER_BLOCK)]


def badge_blocks(people, earned, mention=False):
    """The "Badges this week" section as Slack blocks, [] when nobody earned one: a header,
    then every badge as a card in a two-column grid (a section's fields), kind by kind and
    the highest tiers of a kind first. Ten cards fill a block; more carry on in the next.
    Spotter has already announced each of these as it happened; this is the week's recap."""
    if not earned:
        return []
    return [header_block(":medal:  Badges this week")] + badge_fields(people, earned, mention)


def current_badges(rows, today):
    """The snapshot form of everyone's badges, from the activity rows."""
    return badge_snapshot(badge_state(gather_people(rows), today))


def journey_arrived(facts, vol):
    """The stops the channel reached since last time: [(lap, index, stop)]."""
    if not vol:
        return []
    return journey_arrivals(vol["base"]["t"].get("step", 0), facts["totals"].get("step", 0))


def journey_arrival_text(arrival, vol, facts):
    """One sentence for the latest stop reached; the finish of a lap says so."""
    lap, index, stop = arrival
    if index == len(ROUTE) - 1:
        return ("{} We've walked all the way round the world — *{:,.0f} km*, "
                "together. Lap {} starts now.".format(":tada:", LAP_KM, lap + 1))
    return "We've arrived in *{}* {} — {}, {:,.0f} km along the way.".format(
        stop[0], stop[1], stop[4], STOP_KM[index] + (lap - 1) * LAP_KM)


def journey_parts(facts, vol, today):
    """The journey as (where it is, the lines about it, the line under them), or None
    before anyone has walked: where the channel is, how far to the next stop, and -- with
    a pace to go on -- roughly when it lands. `where` reads "leg 3 of 20  ·  lap 2"."""
    steps = facts["totals"].get("step", 0)
    if not steps:
        return None
    pos = journey_position(steps)
    behind, ahead = pos["behind"], pos["ahead"]
    where = "leg {} of {}".format(pos["leg"], pos["legs"])
    if pos["lap"] > 1:
        where += "  ·  lap {}".format(pos["lap"])
    lines = ["{} {}  →  {} {}".format(behind[1], stop_name(behind), ahead[1], stop_name(ahead)),
             "{}  *{:.0f}%*  ·  *{:,.0f} km* to go".format(
                 bar("step", pos["share"]), pos["share"] * 100, pos["to_go"])]
    pace = None
    if vol and vol["gain"].get("step") and vol["days"]:
        pace = journey_days_to_go(pos, vol["gain"]["step"] / float(vol["days"]))
    if pace is not None and pace <= 120:
        lines.append("At this pace we reach *{}* around *{}*.".format(
            stop_name(ahead), short_date(today + timedelta(days=pace))))
    else:
        lines.append("_{}: {}_".format(stop_name(ahead), ahead[4]))
    around = pos["around"] * 100
    together = "Together we've walked *{:,.0f} km*  ·  *{}%* of the way round the world".format(
        pos["km"], "{:.1f}".format(around) if around < 10 else "{:.0f}".format(around))
    if pos["lap"] > 1:
        together = "Together we've walked *{:,.0f} km*  ·  *{} lap{} done*".format(
            pos["km"], pos["lap"] - 1, "" if pos["lap"] == 2 else "s")
    if vol and vol["gain"].get("step"):
        together += "  ·  *+{:,.0f} km* {}".format(
            steps_to_km(vol["gain"]["step"]), span_label(vol["days"]))
    return where, lines, together


def journey_blocks(facts, vol, today):
    """The journey as Slack blocks (see journey_parts): a section, then a line under it."""
    parts = journey_parts(facts, vol, today)
    if not parts:
        return []
    where, lines, together = parts
    head = ":world_map:  *{}*  ·  {}".format(JOURNEY_NAME, where)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": "\n".join([head] + lines)}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": together}]}]


# --------------------------------------------------------------------------- moments

def personal_milestones(people, week, today):
    """[(person id, what they passed)] for round numbers crossed this week.

    Days logged are dated, so that count is exact. Sessions are not dated, so a total
    is only called when it is certain: a person with k days in the week posted at least
    k sessions in it, and those are the last k in their list -- so a mark above the
    total without them was passed this week. It can miss one; it cannot invent one.
    """
    start = week["start"]
    found = []
    for pid, person in people.items():
        if not person["name"] or (person["first"] and person["first"] >= start):
            continue                      # a first week is a welcome, not a milestone
        before = len([d for d in person["days"] if d < start])
        now = len([d for d in person["days"] if d <= today])
        marks = [m for m in DAY_MARKS if before < m <= now]
        if marks:
            found.append((pid, "*{}* days logged".format(max(marks))))
        for entry in person["rows"]:
            ladder = personal_marks(entry["activity"])
            recent = len([d for d in entry["days"] if start <= d <= today])
            if not ladder or not recent:
                continue
            total = sum(entry["values"])
            floor = total - sum(entry["values"][-recent:])
            marks = personal_passed(ladder, floor, total)
            if marks:
                found.append((pid, "*{}* {} all time".format(
                    spoken(entry["activity"], max(marks)), unit_of(entry["activity"]))))
    return found


def moments_from_table(people, week, facts, today, team="", mention=False):
    """(score, icon, text) for what happened in the last 7 days, from the table alone.
    Named for what people did -- no ordering, nothing that ranks."""
    start = week["start"]
    found = []
    newcomer_ids = set(week["new_people"])

    def who(pid):
        return person_label(people, pid, mention)

    new = week["new_people"]
    if new:
        found.append((75 + min(len(new), 5), ":wave:",
                      "Welcome {} — first log{} this week".format(
                          names_text([who(p) for p in new]), "" if len(new) == 1 else "s")))

    # Back after a long gap.
    back = []
    for pid, person in people.items():
        if pid in newcomer_ids or not person["name"]:
            continue
        inside = [d for d in person["days"] if start <= d <= today]
        before = [d for d in person["days"] if d < start]
        if inside and before and (min(inside) - max(before)).days >= COMEBACK_DAYS:
            back.append(((min(inside) - max(before)).days, person["name"], pid))
    if back:
        back.sort(key=lambda item: (-item[0], item[1]))      # longest away first, then by name
        gap = back[0][0]
        away = ("{} weeks".format(max(2, int(round(gap / 7.0)))) if gap < 60
                else "{} months".format(max(2, int(round(gap / 30.0)))))
        found.append((70 + min(len(back), 5), ":raised_hands:",
                      "Welcome back {} — {}".format(
                          names_text([who(pid) for _, _, pid in back]),
                          "first log in {}".format(away) if len(back) == 1
                          else "first logs after {} away".format(away))))

    # A first go at something.
    tries = []
    for pid, person in sorted(people.items(), key=lambda item: item[1]["name"]):
        if pid in newcomer_ids or not person["name"]:
            continue
        for entry in person["rows"]:
            if len(entry["values"]) == 1 and entry["days"] and max(entry["days"]) >= start:
                tries.append((pid, entry["activity"]))
    if tries:
        text = ", ".join("{} ({})".format(who(pid), TITLE.get(a, a.title()).lower())
                         for pid, a in tries[:2])
        if len(tries) > 2:
            text += " and {} more".format(len(tries) - 2)
        found.append((55, ":seedling:", "First time trying something new: " + text))

    # A personal best in the latest session. Needs history to beat.
    bests = []
    for pid, person in people.items():
        if not person["name"]:
            continue
        for entry in person["rows"]:
            values, activity = entry["values"], entry["activity"]
            if (activity in BEST_ACTIVITIES and len(values) >= NEW_BEST_MIN_SESSIONS
                    and entry["days"] and max(entry["days"]) >= start
                    and values[-1] >= max(values[:-1]) * NEW_BEST_MIN_GAIN):
                prior = max(values[:-1])
                bests.append((values[-1] / float(prior) if prior else 1.0, person["name"],
                              pid, activity, values[-1], prior))
    bests.sort(reverse=True)
    for place, (_, _, pid, a, now, was) in enumerate(bests[:2]):
        text = "{} set a new {} personal best: *{}* (was {})".format(
            who(pid), TITLE.get(a, a.title()).lower(), humanize(a, now), humanize(a, was))
        if place == 1 and len(bests) > 2:
            text += " \u2014 and {} more this week".format(len(bests) - 2)
        found.append((65 - place * 0.1, ":sports_medal:", text))

    # Personal round numbers passed this week.
    marks = {}
    for pid, what in personal_milestones(people, week, today):
        marks.setdefault(pid, []).append(what)
    order = sorted(marks, key=lambda pid: people[pid]["name"])
    for place, pid in enumerate(order[:3]):
        text = "{} passed {}".format(who(pid), " and ".join(marks[pid][:2]))
        if place == 2 and len(order) > 3:
            text += " \u2014 and {} more".format(len(order) - 3)
        # One line each, kept together and in name order by the falling score.
        found.append((62 - place * 0.1, ":star2:", text))

    # The busiest day.
    counts = {d: len(ids) for d, ids in week["by_day"].items()
              if start <= d <= today}
    if counts:
        top = max(counts.values())
        leaders = [d for d, c in counts.items() if c == top]
        if top >= 3 and len(leaders) == 1:
            found.append((40, ":zap:", "{} was the busiest day — *{}* people logged".format(
                leaders[0].strftime("%A"), top)))

    # The channel passed a round number of people.
    def count_on(day):
        return sum(1 for p in people.values() if p["first"] and p["first"] <= day)
    before, now = count_on(start - timedelta(days=1)), count_on(today)
    crossed = [m for m in PEOPLE_MILESTONES if before < m <= now]
    if crossed:
        found.append((80, team or team_emoji(),
                      "The channel is now *{}* people strong".format(now)))
    return found


def moments_from_snapshot(facts, vol, said="", doing=None):
    """What the snapshot can add: milestones crossed since last time. `said` is the
    story the opener told; a milestone it announced is not announced again here."""
    if not vol:
        return []
    found = []
    when = span_label(vol["days"])
    arrived = journey_arrived(facts, vol)
    if arrived and said != "arrived":
        found.append((88, ":world_map:", journey_arrival_text(arrived[-1], vol, facts)))
    for place, (activity, mark) in enumerate(rungs_passed(facts, vol, doing)):
        if said == "passed" and place == 0:
            continue
        found.append((85 - place * 0.1, ICONS.get(activity, ":tada:"),
                      "We passed *{}* {} {}".format(
                          spoken(activity, mark), unit_of(activity), when)))
    sessions_before = sum(int(v or 0) for v in vol["base"].get("n", {}).values())
    sessions_now = facts["logs"]

    def session_mark(n):
        return (n // 500) * 500 if n >= 500 else (n // 100) * 100

    if sessions_before and session_mark(sessions_now) > session_mark(sessions_before) \
            and session_mark(sessions_now) > 0:
        found.append((70, ":memo:", "The channel has now logged *{:,}* sessions".format(
            session_mark(sessions_now))))
    return found


# ---------------------------------------------------------------------- the headline

def nearest_stop(facts, doing=None):
    """The activities with a milestone ahead, nearest first:
    [(share, activity, where it stands)] -- see stop_for. `doing` is active_fields();
    without it only the headline three are considered."""
    standing = [(spot["share"], activity, spot)
                for activity, spot in ((a, stop_for(a, facts["totals"].get(a, 0)))
                                       for a in milestone_activities(facts, doing or {}))]
    standing.sort(key=lambda item: (-item[0], item[1]))
    return standing


def days_to_stop(spot, activity, vol):
    """Days until the next rung at the pace since last time, or None without a pace."""
    gain = vol["gain"].get(activity) if vol else None
    if not gain or not vol["days"]:
        return None
    return max(1, int(-(-spot["to_go"] * vol["days"] // gain)))


def change_percent(vol, activity):
    """This stretch against the one before, as a percentage of its daily rate. None
    when either is unknown."""
    gain, before = vol["gain"].get(activity), vol["prev"].get(activity)
    if not gain or not before or not vol["prev_days"]:
        return None
    return (gain / float(vol["days"]) / (before / float(vol["prev_days"])) - 1) * 100


def change_text(vol, activity):
    """The same comparison in a few words, for a stat tile. '' when unknown."""
    change = change_percent(vol, activity)
    if change is None:
        return ""
    if change >= 3:
        return "\u25b2 {:.0f}% on the week before".format(change)
    if change > -3:
        return "level with the week before"
    return "{} the week before".format(humanize(activity, int(round(
        vol["prev"][activity] * vol["days"] / float(vol["prev_days"])))))


def spoken(activity, value):
    """humanize, except that a whole number of hours is said in full. "5 hours" reads
    as somewhere to get to; "5h" reads as a figure off a dial."""
    if activity in DURATION:
        seconds = int(value or 0) * (1 if DURATION[activity] == "seconds" else 60)
        if seconds and seconds % 3600 == 0:
            return "{} hour{}".format(seconds // 3600, "" if seconds == 3600 else "s")
    return humanize(activity, value)


def week_number(facts, today):
    """Which week of the channel this is, counted from its first log. 0 if unknown."""
    first = parse_day(facts.get("since"))
    return (today - first).days // WEEK_DAYS + 1 if first and first <= today else 0


# The top line of the post. A greeting, not a date: everyone knows what day it is, and
# the week number says something the date cannot -- how long this has been going.
#
# A pool, rotated (see pick_line): the same few words opening every post is how a header
# stops being read. Every line says "team" and names the week, and stays plainly
# workplace-friendly. Add to a pool freely -- nothing depends on its length.
TITLES_FRIDAY = (
    "Happy Friday, team! Week {n} is in the books :raised_hands:",
    "Week {n} is a wrap, team! :tada:",
    "That's week {n} done, team :clap:",
    "Friday roundup: week {n}, team :rocket:",
    "Week {n}, done and dusted \u2014 here's how we did, team :sparkles:",
    "Friday's here, team \u2014 week {n} by the numbers :bar_chart:",
    "Another week in the bag! Week {n} recap, team :muscle:",
    "Week {n} wrapped up \u2014 thanks for showing up, team :blue_heart:",
    "Look what we did in week {n}, team :eyes:",
    "Friday check-in, team: week {n} is complete :white_check_mark:",
    "It's official, team \u2014 week {n} is in the books :books:",
    "Time for the week {n} wrap-up, team! :drum_with_drumsticks:",
    "It's Friday! Let's see how week {n} went, team :sunglasses:",
    "Week {n} complete \u2014 enjoy the weekend, team :sunny:",
    "Cheers to week {n}, team! :star2:",
)
TITLES_OTHER = (
    "Week {n} check-in, team :wave:",
    "Here's week {n} so far, team :eyes:",
    "Week {n} so far \u2014 here's the picture, team :mag:",
    "A look at week {n}, team :bar_chart:",
    "How week {n} is going, team :sparkles:",
    "Week {n} in progress \u2014 here's where we are, team :rocket:",
)
# Used while the channel's first week has no number to say yet.
TITLES_UNNUMBERED = (
    "That's the week, team! :tada:",
    "Happy Friday, team! :raised_hands:",
    "Here's the week, team :bar_chart:",
    "Friday roundup, team :rocket:",
    "Another week in the bag, team :muscle:",
    "Week's wrapped up \u2014 here's how we did, team :sparkles:",
)
TITLES_QUIET = (
    "A quiet week, team :seedling:",
    "A gentle week, team :seedling:",
    "Quiet one this week, team :leaves:",
)
TITLE_QUIET = TITLES_QUIET[0]


def pick_line(pool, index):
    """The `index`-th line of a rotation through `pool`.

    Every line is used once per cycle before any is used again, in an order that is
    scrambled (so it does not read as a list being recited) but fixed (the same index
    always gives the same line, so re-running a post does not change it). The start of
    each cycle is arranged so that it avoids the last lines of the one before: a line is
    never used again within a third of the pool of its last use -- five posts, for a pool
    of fifteen -- and consecutive posts never repeat.
    """
    size = len(pool)
    if size == 1:
        return pool[0]
    cycle, place = divmod(max(0, int(index)), size)
    keep_apart = max(1, size // 3)

    previous = None
    for number in range(cycle + 1):
        order = list(range(size))
        random.Random("title-{}".format(number)).shuffle(order)
        if previous is not None:
            recent = set(previous[-keep_apart:])
            for slot in range(keep_apart):
                if order[slot] in recent:
                    # swap in the first later line that was not used lately
                    for other in range(keep_apart, size):
                        if order[other] not in recent:
                            order[slot], order[other] = order[other], order[slot]
                            break
        previous = order
    return pool[previous[place]]


def week_title(facts, week, today):
    number = week_number(facts, today)
    # The channel's own week count, so consecutive posts walk the rotation in step; the
    # calendar week stands in until there is one.
    index = number or today.isocalendar()[1]
    if not week["ids"]:
        return pick_line(TITLES_QUIET, index)
    if not number:
        return pick_line(TITLES_UNNUMBERED, index)
    pool = TITLES_FRIDAY if today.weekday() == 4 else TITLES_OTHER
    return pick_line(pool, number).format(n=number)


def rungs_passed(facts, vol, doing=None):
    """[(activity, running total at the milestone)] for milestones crossed since last
    time, in any activity with one to climb."""
    passed = []
    for activity in milestone_activities(facts, doing or {}) if vol else ():
        before = stop_for(activity, vol["base"]["t"].get(activity, 0))["reached"]
        after = stop_for(activity, facts["totals"].get(activity, 0))["reached"]
        if after > before:
            passed.append((activity, after))
    return passed


def lede(facts, week, vol, today, doing=None):
    """(sentence, story) -- the one thing worth saying first about this week, said
    with some warmth. `story` names which it was, so the rest of the post does not say
    it a second time.

    In order: a record; a milestone passed; what was added since last time; a milestone
    within reach; who showed up. The week's counts are in the tiles underneath, so
    this never restates them.
    """
    people, prev = len(week["ids"]), week["prev_people"]
    if not people:
        return ("Nobody has logged in the last 7 days — which makes the next log "
                "the one that gets us going again. :seedling:", "quiet")

    lead = next((a for a in HEADLINE if vol and vol["gain"].get(a)), None)
    standing = nearest_stop(facts, doing)
    reach = ""
    if standing:
        share, activity, spot = standing[0]
        days = days_to_stop(spot, activity, vol)
        if share >= REACH_SHARE or (days is not None and days <= WEEK_DAYS):
            reach = "just *{}* {} away from *{}*".format(
                humanize(activity, spot["to_go"]), unit_of(activity),
                spoken(activity, spot["target"]))

    if lead and vol["record"].get(lead):
        return (":trophy:  Our biggest week yet — *{} {}* {}!".format(
            humanize(lead, vol["gain"][lead]), LADDERS[lead]["unit"],
            span_label(vol["days"])), "record")
    if week["record_week"]:
        return (":trophy:  Our busiest week yet — more of us logged than in any "
                "week before!", "record")
    arrived = journey_arrived(facts, vol)
    if arrived:
        return (":world_map:  " + journey_arrival_text(arrived[-1], vol, facts), "arrived")
    passed = rungs_passed(facts, vol, doing)
    if passed:
        activity, mark = passed[0]
        return ("We did it — we passed *{} {}* {}! :tada:".format(
            spoken(activity, mark), unit_of(activity),
            span_label(vol["days"])), "passed")
    if lead:
        text = "We put in *{} {}* {}".format(
            humanize(lead, vol["gain"][lead]), LADDERS[lead]["unit"],
            span_label(vol["days"]))
        change = change_percent(vol, lead)
        if change is not None and change >= 3:
            text += ", up *{:.0f}%* on the week before".format(change)
        elif change is not None and change > -3:
            text += ", level with the week before"
        text += "."
        if reach:
            text += " And we're {}. :dart:".format(reach)
        return text, "volume"
    if reach:
        return ("We're {} — one more push and it's ours. :dart:".format(reach),
                "reach")
    if prev and people > prev:
        return ("More of us logged this week than last — that's the direction we "
                "like. :chart_with_upwards_trend:", "people")
    return "Another week of showing up — and every log counted. :muscle:", "people"


def stat_tile_parts(week, vol, team=""):
    """The week's numbers as (icon, figure, what it counts) -- the old look sets each as a
    line of a two-column fields block (stat_tiles), the new one as a cell of a grid."""
    def tile(icon, figure, label):
        return (icon, figure, label)

    people = len(week["ids"])
    if not people:
        return []
    tiles = [tile(team or team_emoji(), people,
                  "person active" if people == 1 else "people active"),
             tile(":white_check_mark:", week["checkins"],
                  "check-in" if week["checkins"] == 1 else "check-ins")]
    if vol:
        for activity in week_activities(week):
            if vol["gain"].get(activity):
                tiles.append(tile(ICONS.get(activity, ""),
                                  humanize(activity, vol["gain"][activity]),
                                  unit_of(activity)))
    if week["steady"]:
        # Counted, not named: it is a habit, not a contest. "People", spelled out --
        # "2 logged every working day" was read as two logs a day.
        tiles.append(tile(":fire:", week["steady"], "{} logged every working day".format(
            "person" if week["steady"] == 1 else "people")))
    if week["activities"] > 1:
        tiles.append(tile(":jigsaw:", week["activities"], "different activities"))
    new = len(week["new_people"])
    if new:
        tiles.append(tile(":wave:", new, "new face" if new == 1 else "new faces"))
    return tiles


def stat_tiles(week, vol, team=""):
    """The week's numbers as tiles for a two-column fields block: the figure, bold, and
    what it counts. Nothing else -- what they are compared with is one quiet line
    underneath (last_week_text), not a second row of text under every tile."""
    return ["{}  *{}* {}".format(icon, figure, label)
            for icon, figure, label in stat_tile_parts(week, vol, team)]


def last_week_text(week, vol):
    """What the tiles are up against, as one context line. '' with nothing to compare."""
    parts = []
    if week["prev_people"]:
        parts.append("*{}* {} active".format(
            week["prev_people"], "person" if week["prev_people"] == 1 else "people"))
        parts.append("*{}* check-in{}".format(
            week["prev_checkins"], "" if week["prev_checkins"] == 1 else "s"))
    if vol and vol["prev_days"]:
        for activity in week_activities(week):
            before = vol["prev"].get(activity)
            if before and vol["gain"].get(activity):
                parts.append("*{}* {}".format(
                    humanize(activity, int(round(
                        before * vol["days"] / float(vol["prev_days"])))),
                    unit_of(activity)))
    return "The week before:  " + "  ·  ".join(parts) if parts else ""


# ----------------------------------------------------------- spotlight, next stop

def spotlight_turn(facts, people, week, today):
    """(which, blocks) -- one rotating section, so the post is not the same shape every
    week. Rotates by ISO week; a spotlight with nothing to say passes to the next. `which`
    is the function that spoke, or None: the records go at the foot of the post, not here."""
    order = [spotlight_activity, spotlight_records]
    turn = today.isocalendar()[1]
    for step in range(len(order)):
        which = order[(turn + step) % len(order)]
        blocks = which(facts, people, week, today)
        if blocks:
            return which, blocks
    return None, []


def spotlight(facts, people, week, today):
    """The rotating section's blocks (see spotlight_turn)."""
    return spotlight_turn(facts, people, week, today)[1]


def text_section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def header_block(text):
    """A section title set as Slack's header block: large and bold, so it stands out from
    the lines under it, which a bold first line of the same size did not."""
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def spotlight_activity(facts, people, week, today):
    """A smaller activity, with the people who did it in the last four weeks."""
    since = today - timedelta(days=27)
    active = {}
    for pid, person in people.items():
        for entry in person["rows"]:
            if entry["activity"] not in HEADLINE and any(d >= since for d in entry["days"]):
                active.setdefault(entry["activity"], set()).add(pid)
    if not active:
        return []
    names = sorted(active)
    activity = names[(today.isocalendar()[1] // 2) % len(names)]
    return [text_section("{}  *Spotlight: {}*\n*{}* {} in the last four weeks  ·  "
            "{} {} all time\n_Pick whichever one suits you — it all counts here._".format(
                ICONS.get(activity, ":seedling:"),
                TITLE.get(activity, activity.title()), len(active[activity]),
                "person" if len(active[activity]) == 1 else "people",
                humanize(activity, facts["totals"][activity]),
                SECONDARY_NOUN.get(activity, activity)))]


FIELDS_PER_BLOCK = 10        # Slack's limit on one section block's fields: five rows


RECORDS_HEADING = ":trophy:  *Channel records to beat*"
WEEK_TOP_HEADING = ":first_place_medal:  *This week's top contributors*"


def record_blocks(rows, heading=RECORDS_HEADING):
    """(icon, what, value, who) rows as Slack blocks laid out in two columns.

    Emoji do not render inside a ``` block, and a proportional font cannot be lined up
    with spaces, but a section's `fields` are set in two columns of equal width. The left
    column holds the emoji and what the record is -- both start at the same place on every
    row. In the right column, only the FIRST thing can start at the same place: a figure
    placed before the name pushed each name along by however wide that figure was
    ("32,672" against "58"), so the name leads and the figure follows it. A block takes
    five rows, so a longer list continues in the next one, with a little more space above.
    """
    blocks = []
    per_block = FIELDS_PER_BLOCK // 2
    for start in range(0, len(rows), per_block):
        fields = []
        for icon, what, value, who in rows[start:start + per_block]:
            fields.append({"type": "mrkdwn", "text": "{}  {}".format(icon, what).strip()})
            fields.append({"type": "mrkdwn", "text": "{}  \u2014  *{}*".format(who, value)})
        block = {"type": "section", "fields": fields}
        if start == 0 and heading:
            block["text"] = {"type": "mrkdwn", "text": heading}
        blocks.append(block)
    return blocks


def spotlight_records(facts, people, week, today):
    """The records worth chasing: every activity with RECORD_MIN_PEOPLE or more people
    active in it lately -- the headline three included -- then the two that belong to a
    person rather than an activity, the longest streak and the most days logged, on the
    same condition for the channel as a whole. Names are plain here, never a mention:
    a standing record should not ping its holder every time it is listed. Returns Slack
    blocks (see record_blocks)."""
    doing = active_fields(people, today)
    anyone = set().union(*doing.values()) if doing else set()

    order = list(HEADLINE) + sorted(
        (a for a in facts["bests"] if a not in HEADLINE),
        key=lambda a: -facts["sessions"].get(a, 0))
    rows = []
    for activity in order:
        best = facts["bests"].get(activity) or {}
        if activity not in BEST_PHRASE:
            continue
        if len(doing.get(activity, ())) < RECORD_MIN_PEOPLE:
            continue
        key = "set" if activity in SET_BASED and best.get("set") else "day"
        value, holder = best.get(key, 0), best.get(key + "_by", "")
        if value and holder:
            phrase = BEST_PHRASE[activity] if key == "set" or activity not in SET_BASED \
                else "biggest session"
            rows.append((ICONS.get(activity, ""),
                         "*{}* \u00b7 {}".format(TITLE.get(activity, activity.title()), phrase),
                         humanize(activity, value), holder))

    named = [p for p in people.values() if p["name"]]
    if len(anyone) >= RECORD_MIN_PEOPLE:
        streak = max(named, key=lambda p: (p["streak"], p["name"]))
        if streak["streak"] >= 3:
            rows.append((":fire:", "*Longest streak*", "{} days".format(streak["streak"]),
                         streak["name"]))
        steady = max(named, key=lambda p: (len(p["days"]), p["name"]))
        if len(steady["days"]) >= 5:
            rows.append((":spiral_calendar_pad:", "*Most days logged*",
                         "{} days".format(len(steady["days"])), steady["name"]))
    return record_blocks(rows[:RECORD_LINES]) if rows else []


def week_amount(entry, start, today):
    """(amount, days logged) one person put into one activity from `start` to `today`.

    The session list is not dated, so it is lined up with heatmap_dates from the recent
    end, as weekly_challenge does. After a second log on one day the two lists differ for
    good, and a week holding such a day can only come out a little low -- never high. A row
    with more days than sessions cannot be lined up and gives (0, 0)."""
    values, days = entry["values"], entry["days"]
    if len(values) < len(days):
        return 0, 0
    inside = [amount for day, amount in zip(days, values[len(values) - len(days):])
              if start <= day <= today]
    return sum(inside), len(inside)


def week_top_rows(people, week, today):
    """This week's top contributor in each of the week's activities (week_activities), as
    (icon, "*Activity*", figure, who) rows: the week's own figures, so the names move as
    the weeks do. A tie names everyone in it. Names are plain, as in the records: a list
    should not ping."""
    start = week["start"]
    fields = {}
    for person in people.values():
        if not person["name"]:
            continue
        for entry in person["rows"]:
            if entry["activity"] in NO_MILESTONE:          # more sleep is not a contest
                continue
            amount, days = week_amount(entry, start, today)
            if amount > 0:
                fields.setdefault(entry["activity"], []).append((amount, days, person["name"]))

    rows = []
    for activity in week_activities(week):
        field = fields.get(activity)
        if not field:
            continue
        top = max(amount for amount, _, _ in field)
        leaders = [(name, days) for amount, days, name in field if amount == top]
        if any(days < WEEK_TOP_MIN_DAYS for _, days in leaders):
            continue
        figure = humanize(activity, top)
        if activity not in DURATION:
            figure += " " + unit_of(activity)
        rows.append((ICONS.get(activity, ""), "*{}*".format(TITLE.get(activity, activity.title())),
                     figure, names_text(sorted(name for name, _ in leaders), limit=len(leaders))))
    return rows[:WEEK_TOP_LINES]


def week_top(people, week, today):
    """The week's top contributors as Slack blocks laid out like the records (see
    week_top_rows and record_blocks)."""
    rows = week_top_rows(people, week, today)
    return record_blocks(rows, WEEK_TOP_HEADING) if rows else []


def next_stop(facts, vol, today, active=0, doing=None):
    """The nearest milestone -- in whichever activity it is -- as a progress bar, what
    it takes to get there shared out between the people who logged this week, so it
    reads as something one person can do, and, with a pace, roughly when it lands."""
    standing = nearest_stop(facts, doing)
    if not standing:
        return ""
    share, activity, spot = standing[0]
    text = ":dart:  *Next stop: {} \u2192 {}*\n{}  *{:.0f}%*\n*{}* to go".format(
        TITLE.get(activity, activity.title()), spoken(activity, spot["target"]),
        bar(activity, share), share * 100, humanize(activity, spot["to_go"]))
    if active >= 2:
        text += " \u2014 about *{}* each from the {} of us who logged this week.".format(
            humanize(activity, -(-spot["to_go"] // active)), active)
    else:
        text += "."
    reach = days_to_stop(spot, activity, vol)
    if reach is not None and reach <= 120:
        text += " At this pace, around *{}*.".format(
            short_date(today + timedelta(days=reach)))
    # A reaction is the smallest way to say "I'm in", and everyone can see who has.
    text += " Who's closing it out? React {} if you're in.".format(
        ICONS.get(activity, ":raised_hand:"))
    rest = ["{} {:.0f}%".format(TITLE.get(a, a.title()), s["share"] * 100)
            for _, a, s in standing[1:1 + ALSO_CLIMBING]]
    if rest:
        text += "\n_Also climbing: " + " \u00b7 ".join(rest) + "_"
    return text


# ------------------------------------------------------------------ weekly message

def heat_bands(counts):
    """{people on a day: level 1-3}, quiet to very active, for the days anyone logged.

    The scale is cut so the three colours are used about equally, not at thirds of the
    busiest day: a channel where most days draw 4 to 6 people and one drew 9 put every
    day in the middle band that way, and the whole grid came out one colour. Days with
    the same count always share a colour, so the cuts fall between distinct counts --
    every pair of cuts is tried, which is a handful with numbers this small.
    """
    values = sorted(c for c in counts if c)
    distinct = sorted(set(values))
    if not distinct:
        return {}
    if len(distinct) == 1:
        return {distinct[0]: 2}       # every day alike: the middle of the scale
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


def calendar_text(week):
    """One row per week, a square per day, hotter for busier; the week's people after
    it. Squares come first so the rows line up whatever the date reads."""
    grid = week["grid"]
    bands = heat_bands([c for _, counts, _ in grid for c in counts])
    if not bands:
        return ""
    lines = []
    for index, (end, counts, people) in enumerate(grid):
        squares = "".join(GRID_LEVELS[bands.get(c, 0)] for c in counts)
        label = "{} {}  \u00b7  {} {}".format(end.day, end.strftime("%b"), people,
                                         "person" if people == 1 else "people")
        lines.append("{}   {}".format(
            squares, "*{}*".format(label) if index == len(grid) - 1 else label))
    return "\n".join(lines)


def all_time_text(facts):
    """Everything the channel has ever done, as one quiet footer line."""
    text = "All time  ·  *{}* people  ·  *{:,}* sessions".format(
        facts["people"], facts["logs"])
    if facts["since"]:
        text += " since {}".format(pretty_date(facts["since"]))
    steps = facts["totals"].get("step", 0)
    if steps:
        km = steps * STRIDE_M / 1000.0
        text += "  ·  *{:,.0f} km* walked".format(km)
        if km >= 42.195:
            marathons = int(round(km / 42.195))
            text += " ({} marathon{})".format(marathons, "" if marathons == 1 else "s")
    for activity, phrase in (("pushup", "pushups"), ("plank", "of plank")):
        total = facts["totals"].get(activity, 0)
        if total:
            text += "  ·  *{}* {}".format(humanize(activity, total), phrase)
    return text


# ------------------------------------------------------------------------- the new look
#
# Both formats, the weekly post and the classic all-time summary, can be built two ways,
# chosen by the `look` input:
#
#   old   header, section, fields, context -- the blocks every Slack workspace takes. This is
#         the post as it was before the new look existed, and it is what is posted when Slack
#         refuses a new block (see main).
#   new   the same words and figures, set with Slack's newer blocks:
#           headers  header blocks with a level, so the title leads and the sections sit under it
#           tiles    the week's numbers as a grid (a `layout` block), one cell each
#           charts   a native bar chart (`data_visualization`): how many people logged each
#                    activity this week -- what is being tried, most-done first
#           cards    every badge as a card in a swipeable `carousel`, with what it took
#           tables   the week's top contributors as a native `table` (Slack takes one a message)
#           panels   titled `container` blocks for the calendar and the Great Walk, and for the
#                    channel records -- folded away, since the same few names hold them week
#                    on week -- so the post is shorter to scroll
#
#         The classic summary takes the same features, bar the chart (it is all-time, so there
#         is no week to draw): a header, a grid of the all-time totals, the milestones banked
#         as a panel, the next milestones as cards (each with its bar) and the other
#         activities as a table.
#
#         In the new look the week's top contributors come straight after the numbers -- who
#         did what is what people look for first -- where the old look keeps them lower down.
#
# `new_features` takes features away (or picks a few) without going back to the old post: a
# workspace that refuses one block can still have the rest -- and the step does that by itself:
# Slack names the block it refused in its error, that feature is left out and the post sent
# again, so one refused block costs one feature. The error the step reports is Slack's own.
#
# The carousel and the table are blocks other steps here already post; the layout, container,
# data_visualization blocks and the header level follow Slack's Block Kit Builder samples
# (slack_block_kit/). Slack has taken them from this step, but a workspace may differ; a rule
# it has taught us is in panel() (a container has a rule under its title OR folds, not both).

NEW_FEATURES = ("headers", "tiles", "charts", "cards", "tables", "panels")
OLD_WORDS = ("old", "plain", "original", "legacy", "previous")
TILES_PER_ROW = 3
CHART_ACTIVITIES = 10       # bars in the chart of activities; the most-done ones
CAROUSEL_MAX = 10           # Slack's limit on the cards of a carousel
CARD_TEXT_LIMIT = 150       # ... on a card's title and subtitle
CARD_BODY_LIMIT = 200       # ... and on its body
BADGE_KIND_LABELS = ("Daily streak", "Weekly streak", "Attendance", "Variety", "Special")
EMOJI_TOKEN = re.compile(r":([a-z0-9_+\-]+(?:::skin-tone-[2-6])?):")


class Look(object):
    """Which features of the new look a post uses. None at all is the old look.

    It also hands out block ids -- fs_tile_1, fs_tile_2, ... -- for the blocks that sit inside
    a layout or a container, which Slack's samples always give one; they are the same on every
    run, so a re-run changes nothing."""

    def __init__(self, features=()):
        self.features = frozenset(features)
        self._counts = {}

    @property
    def new(self):
        return bool(self.features)

    def on(self, feature):
        return feature in self.features

    def block_id(self, kind):
        self._counts[kind] = self._counts.get(kind, 0) + 1
        return "fs_{}_{}".format(kind, self._counts[kind])

    def without(self, features):
        """The same look with some features taken away (a fresh one, so ids start again)."""
        return Look(self.features - set(features))


OLD_LOOK = Look()
# The classic all-time summary has no chart (there is no week to draw), so that feature is not
# one of its features: asked for, it changes nothing, and a refusal never has to name it.
CLASSIC_UNUSED = ("charts",)
FEATURE_OF_BLOCK = {"layout": "tiles", "data_visualization": "charts", "container": "panels",
                    "carousel": "cards", "card": "cards", "table": "tables"}
# When Slack does not say which block it refused, the features go in this order: the ones
# least likely to be accepted first, so the likeliest ones are the last to go.
PEEL_ORDER = ("panels", "tiles", "charts", "headers", "tables", "cards")


def refused_features(error, blocks, look):
    """The features of `look` whose blocks Slack named in an invalid_blocks error.

    Slack's error carries a json-pointer for each fault, "/blocks/15/has_header_divider",
    counted from the top of the message; the block at that place says which feature it was.
    With no pointer that points at a feature in use, the next feature in PEEL_ORDER goes, so
    a refusal costs one feature at a time and never the whole new look in one go."""
    found = []
    for match in re.finditer(r"/blocks/(\d+)", error):
        index = int(match.group(1))
        if index >= len(blocks):
            continue
        kind = blocks[index].get("type")
        feature = "headers" if kind == "header" and "level" in blocks[index] \
            else FEATURE_OF_BLOCK.get(kind)
        if feature and look.on(feature) and feature not in found:
            found.append(feature)
    if found:
        return found
    for feature in PEEL_ORDER:
        if look.on(feature):
            return [feature]
    return sorted(look.features)


def parse_look(value, features=None):
    """The Look the `look` and `new_features` inputs ask for. new is the default; anything
    unrecognised is new rather than a failure, as with choose_format. Features: blank or
    "all" is every one; a list picks those; "-charts" takes one off; "none" is the old look."""
    if str(value or "").strip().lower() in OLD_WORDS:
        return OLD_LOOK
    tokens = [t for t in re.split(r"[\s,;]+", str(features or "").strip().lower()) if t]
    if "none" in tokens:
        return OLD_LOOK
    picked = [t for t in tokens if t in NEW_FEATURES or t == "all"]
    dropped = set(t[1:] for t in tokens if t[:1] == "-" and t[1:] in NEW_FEATURES)
    chosen = set(NEW_FEATURES) if not picked or "all" in picked else set(picked)
    return Look(chosen - dropped)


def heading(look, text, level=2):
    """A header block; with the `headers` feature it carries its level (1 is the largest)."""
    block = header_block(text)
    if look.on("headers"):
        block["level"] = level
    return block


def with_ids(look, blocks, kind):
    """Copies of blocks, each with a block id: for blocks that go inside a container."""
    out = []
    for block in blocks:
        block = dict(block)
        block.setdefault("block_id", look.block_id(kind))
        out.append(block)
    return out


def context_block(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def tile_layout(look, parts, caption="The week in numbers"):
    """Numbers as a grid: a `layout` block, TILES_PER_ROW cells to a row, each cell centred --
    the figure in bold with its icon, what it counts under it -- under a visible `caption`."""
    rows = []
    for start in range(0, len(parts), TILES_PER_ROW):
        items = []
        for icon, figure, label in parts[start:start + TILES_PER_ROW]:
            items.append({"block": {
                "type": "section", "block_id": look.block_id("tile"),
                "text": {"type": "mrkdwn",
                         "text": "{} *{}*\n{}".format(icon, figure, label).strip()}},
                "width": "standard", "horizontal_alignment": "center"})
        rows.append({"items": items})
    return {"type": "layout", "block_id": look.block_id("tiles"), "label": caption,
            "is_label_visible": True, "grid_lines": "outer", "rows": rows}


def activity_chart(look, week):
    """What is being tried this week: a bar chart of how many people logged each activity, the
    most-done first (ties by check-ins, then name), at most CHART_ACTIVITIES bars. A bar chart,
    not a pie: its axis puts a figure on every bar. None under two activities -- one bar has
    nothing to be compared with."""
    counts = week.get("by_activity") or {}
    ranked = sorted(((people, days, TITLE.get(a, a.replace("_", " ").title()))
                     for a, (people, days) in counts.items() if people),
                    key=lambda item: (-item[0], -item[1], item[2]))
    if len(ranked) < 2:
        return None
    data = [{"label": name, "value": people} for people, _days, name in ranked[:CHART_ACTIVITIES]]
    return {"type": "data_visualization", "block_id": look.block_id("chart"),
            "title": "People per activity this week",
            "chart": {"type": "bar", "series": [{"name": "People", "data": data}],
                      "axis_config": {"categories": [d["label"] for d in data],
                                      "x_label": "Activity", "y_label": "People"}}}


def badge_card(people, badge, pids, mention=False):
    """One badge as a card: its emoji and name, the kind and how many earned it, then who --
    as many names as fit a card's body, the rest counted -- and what it takes."""
    labels = [person_label(people, pid, mention) for pid in pids]
    about = "_{}_".format(badge["about"])
    room = CARD_BODY_LIMIT - len(about) - 1
    shown = len(labels)
    while shown > 1 and len(names_text(labels, limit=shown)) > room:
        shown -= 1
    kind = BADGE_KIND_LABELS[min(badge_kind(badge), len(BADGE_KIND_LABELS) - 1)]
    return {"type": "card",
            "title": {"type": "mrkdwn",
                      "text": "{}  {}".format(badge["emoji"], badge["name"])[:CARD_TEXT_LIMIT]},
            "subtitle": {"type": "mrkdwn", "text": "{}  ·  {} {}".format(
                kind, len(pids), "person" if len(pids) == 1 else "people")[:CARD_TEXT_LIMIT]},
            "body": {"type": "mrkdwn",
                     "text": (names_text(labels, limit=shown) + "\n" + about)[:CARD_BODY_LIMIT]}}


def badge_carousels(people, earned, mention=False):
    """Every badge as a card, in carousels of CAROUSEL_MAX: kind by kind, highest tier first."""
    cards = [badge_card(people, badge, pids, mention) for badge, pids in badge_order(earned)]
    return [{"type": "carousel", "elements": cards[start:start + CAROUSEL_MAX]}
            for start in range(0, len(cards), CAROUSEL_MAX)]


def rich_cell(text, bold=False):
    """A table cell as rich text, so a custom emoji in it is drawn rather than spelled out."""
    elements, position = [], 0

    def add(piece):
        if piece:
            element = {"type": "text", "text": piece}
            if bold:
                element["style"] = {"bold": True}
            elements.append(element)

    for match in EMOJI_TOKEN.finditer(text):
        add(text[position:match.start()])
        elements.append({"type": "emoji", "name": match.group(1)})
        position = match.end()
    add(text[position:])
    return {"type": "rich_text", "elements": [
        {"type": "rich_text_section", "elements": elements or [{"type": "text", "text": " "}]}]}


def raw_cell(text):
    return {"type": "raw_text", "text": str(text).strip() or " "}      # a cell may not be empty


def native_table(head, body, aligns):
    """A native Slack table: a bold header row over `body` (rows of cells), one column per
    entry of `aligns` ("left", "right", "center"). One real settings object per column -- a
    null there makes Slack refuse the table. Slack takes one table a message."""
    return {"type": "table", "rows": [[rich_cell(text, bold=True) for text in head]] + body,
            "column_settings": [{"align": align, "is_wrapped": True} for align in aligns]}


def top_table(rows):
    """The week's top contributors (week_top_rows) as a native Slack table: the activity with
    its emoji, the figure and the name."""
    body = [[rich_cell("{} {}".format(icon, what.replace("*", "")).strip(), bold=True),
             raw_cell(figure), raw_cell(who)] for icon, what, figure, who in rows]
    return native_table(("Activity", "This week", "Top contributor"), body,
                        ("left", "right", "left"))


def panel(look, title, children, subtitle="", collapsed=None, kind="panel"):
    """A titled `container` block. `collapsed` None is an ordinary panel, with a rule under
    its title; True or False makes it collapsible instead, closed or open to begin with.
    Slack takes one or the other, never both: has_header_divider "can only be set when
    is_collapsible is false" -- it refused the post that set both. The title and subtitle
    are plain text and carry no emoji: Slack does not draw a :shortcode: there, it shows it
    as typed (a header block does draw them)."""
    block = {"type": "container", "block_id": look.block_id(kind),
             "title": {"type": "plain_text", "text": title, "emoji": True},
             "child_blocks": with_ids(look, children, kind + "_part")}
    if subtitle:
        block["subtitle"] = {"type": "plain_text", "text": subtitle, "emoji": True}
    if collapsed is None:
        block["has_header_divider"] = True
    else:
        block["is_collapsible"] = True
        block["default_collapsed"] = bool(collapsed)
    return block


def calendar_parts(week, today):
    """(the grid, the line about the busiest day, the legend) of the who-showed-up calendar,
    or None when there is nothing to draw."""
    grid = calendar_text(week)
    if not grid:
        return None
    busiest, quietest = weekday_pace(week)
    insight = ""
    if busiest:
        insight = "{}s are our busiest day, {}s our quietest.".format(busiest, quietest)
    if today.weekday() >= 4:
        insight = (insight + " " if insight else "") + \
            "Streaks hold over the weekend, so rest is free."
    first = today + timedelta(days=1)
    # "busy" read as people being too busy to log -- the opposite of what the colours
    # mean. Quiet to very active says it: more people logging that day.
    legend = "Each row is the 7 days to that date, {} → {}  ·  {}  quiet → very active".format(
        first.strftime("%a"), today.strftime("%a"), "".join(GRID_LEVELS))
    return grid, insight, legend


def old_look_blocks(facts, people, week, vol, today, doing, image_url, title, opening, team,
                    moments, earned, stop, mention):
    """The weekly dashboard as it always was: header, sections, fields and context only."""
    blocks = []
    if image_url:
        blocks.append({"type": "image", "image_url": image_url,
                       "alt_text": "Weekly channel summary"})
    blocks.append({"type": "header", "text": {
        "type": "plain_text", "text": title, "emoji": True}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": opening}})

    tiles = stat_tiles(week, vol, team)
    if tiles:
        # Ten fields fill a block; a busy week of activities carries on in the next.
        for start in range(0, len(tiles), FIELDS_PER_BLOCK):
            blocks.append({"type": "section", "fields": [
                {"type": "mrkdwn", "text": t} for t in tiles[start:start + FIELDS_PER_BLOCK]]})
        before = last_week_text(week, vol)
        if before:
            blocks.append({"type": "context",
                           "elements": [{"type": "mrkdwn", "text": before}]})

    badges = badge_blocks(people, earned, mention)

    if moments:
        blocks.append({"type": "divider"})
        blocks.append(header_block(":sparkles:  Shout-outs"))
        blocks.append(text_section("\n".join(
            "{}  {}".format(icon, text) for _, icon, text in moments)))
    if badges:
        blocks.append({"type": "divider"})
        blocks.extend(badges)

    calendar = calendar_parts(week, today)
    if calendar:
        grid, insight, legend = calendar
        blocks.append({"type": "divider"})
        blocks.append(header_block(":calendar:  Who showed up, day by day"))
        blocks.append(text_section(grid))
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": (insight + "\n" if insight else "") + legend}]})

    # Who led each activity this week, where the all-time records used to stand: those
    # are held by the same few people week after week, so they go to the foot of the post.
    top = week_top(people, week, today)
    if top:
        blocks.append({"type": "divider"})
        blocks.extend(top)

    which, spot = spotlight_turn(facts, people, week, today)
    records = spot if which is spotlight_records else []
    if spot and not records:
        blocks.append({"type": "divider"})
        blocks.extend(spot)

    road = journey_blocks(facts, vol, today)
    if road:
        blocks.append({"type": "divider"})
        blocks.extend(road)

    if stop:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": stop}})

    if records:
        blocks.append({"type": "divider"})
        blocks.extend(records)

    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": all_time_text(facts)}]})
    return blocks


def new_look_blocks(look, facts, people, week, vol, today, doing, image_url, title, opening,
                    team, moments, earned, stop, mention):
    """The weekly dashboard in the new look (see the notes above): the same sections in the
    same order as old_look_blocks, each in the newest block that suits it, and the old one
    wherever its feature is switched off."""
    blocks = []
    if image_url:
        blocks.append({"type": "image", "image_url": image_url,
                       "alt_text": "Weekly channel summary"})
    blocks.append(heading(look, title, 1))
    blocks.append(text_section(opening))

    parts = stat_tile_parts(week, vol, team)
    if parts:
        if look.on("tiles"):
            blocks.append(tile_layout(look, parts))
        else:
            tiles = stat_tiles(week, vol, team)
            for start in range(0, len(tiles), FIELDS_PER_BLOCK):
                blocks.append({"type": "section", "fields": [
                    {"type": "mrkdwn", "text": t} for t in tiles[start:start + FIELDS_PER_BLOCK]]})
        before = last_week_text(week, vol)
        if before:
            blocks.append(context_block(before))

    # Who did what is what people look for first, so the week's top contributors follow the
    # numbers (the old look keeps them lower down).
    if look.on("tables"):
        rows = week_top_rows(people, week, today)
        if rows:
            blocks.append({"type": "divider"})
            blocks.append(heading(look, ":first_place_medal:  This week's top contributors"))
            blocks.append(top_table(rows))
    else:
        top = week_top(people, week, today)
        if top:
            blocks.append({"type": "divider"})
            blocks.extend(top)

    if moments:
        blocks.append({"type": "divider"})
        blocks.append(heading(look, ":sparkles:  Shout-outs"))
        blocks.append(text_section("\n".join(
            "{}  {}".format(icon, text) for _, icon, text in moments)))

    if earned:
        blocks.append({"type": "divider"})
        blocks.append(heading(look, ":medal:  Badges this week"))
        if look.on("cards"):
            blocks.extend(badge_carousels(people, earned, mention))
        else:
            blocks.extend(badge_fields(people, earned, mention))

    # Like the tiles, left out when nobody logged: a chart of nothing is not worth posting on
    # the week that most needs to be gentle.
    if look.on("charts") and week["ids"]:
        chart = activity_chart(look, week)
        if chart:                                   # it has a title of its own
            blocks.append({"type": "divider"})
            blocks.append(chart)

    calendar = calendar_parts(week, today)
    if calendar:
        grid, insight, legend = calendar
        children = [text_section(grid), context_block((insight + "\n" if insight else "") + legend)]
        if look.on("panels"):
            blocks.append(panel(look, "Who showed up, day by day", children,
                                subtitle="{} weeks, a square a day".format(len(week["grid"])),
                                kind="calendar"))
        else:
            blocks.append({"type": "divider"})
            blocks.append(heading(look, ":calendar:  Who showed up, day by day"))
            blocks.extend(children)

    which, spot = spotlight_turn(facts, people, week, today)
    records = spot if which is spotlight_records else []
    if spot and not records:
        blocks.append({"type": "divider"})
        blocks.extend(spot)

    road = journey_parts(facts, vol, today)
    if road and look.on("panels"):
        where, lines, together = road
        blocks.append(panel(look, JOURNEY_NAME,
                            [text_section("\n".join(lines)), context_block(together)],
                            subtitle=where.replace("  ·  ", " · ").capitalize(),
                            kind="walk"))
    elif road:
        blocks.append({"type": "divider"})
        blocks.extend(journey_blocks(facts, vol, today))

    if stop:
        blocks.append({"type": "divider"})
        blocks.append(text_section(stop))

    if records:
        if look.on("panels"):
            # The same few names hold the records week after week, so they are folded away.
            kids = [dict(block) for block in records]
            kids[0].pop("text", None)                    # the panel's title says it
            blocks.append(panel(look, "Channel records to beat", kids,
                                subtitle="Tap to see who holds what", collapsed=True,
                                kind="records"))
        else:
            blocks.append({"type": "divider"})
            blocks.extend(records)

    blocks.append(context_block(all_time_text(facts)))
    return blocks


def classic_tile_parts(facts, team):
    """The channel's all-time numbers as (icon, figure, what it counts), for the tile grid."""
    totals = facts["totals"]
    tiles = [(team, facts["people"], "person" if facts["people"] == 1 else "people"),
             (":white_check_mark:", "{:,}".format(facts["logs"]),
              "session" if facts["logs"] == 1 else "sessions")]
    if len(totals) > 1:
        tiles.append((":jigsaw:", len(totals), "different activities"))
    steps = totals.get("step", 0)
    if steps:
        tiles.append((ICONS.get("step", ""), "{:,}".format(steps),
                      "steps  \u00b7  {:,.0f} km".format(steps * STRIDE_M / 1000.0)))
    for activity, label in (("pushup", "pushups"), ("plank", "of plank")):
        if totals.get(activity):
            tiles.append((ICONS.get(activity, ""), humanize(activity, totals[activity]), label))
    return tiles


def milestone_card(facts, share, activity, value, spot):
    """One headline activity's progress as a card: its name, where it stands and how far along,
    then the bar and what is left to the next rung."""
    subtitle = humanize(activity, value)
    if activity == "step":
        subtitle += "  \u00b7  {:,.0f} km".format(facts["totals"]["step"] * STRIDE_M / 1000.0)
    subtitle += "  \u00b7  {:.0f}%".format(share * 100)
    if share >= 0.85:
        subtitle += " \u2014 almost there"
    body = "{}\n*{}* to go \u2192 *{}*".format(
        compact_bar(activity, share), humanize(activity, spot["to_go"]),
        humanize(activity, spot["next"]))
    return {"type": "card",
            "title": {"type": "mrkdwn", "text": "{}  {}".format(
                ICONS.get(activity, ""), TITLE.get(activity, activity.title())).strip()[:CARD_TEXT_LIMIT]},
            "subtitle": {"type": "mrkdwn", "text": subtitle[:CARD_TEXT_LIMIT]},
            "body": {"type": "mrkdwn", "text": body[:CARD_BODY_LIMIT]}}


def others_table(facts, activities):
    """The other activities as a native table: each with its emoji, what it has added up to
    and how many sessions that was."""
    body = [[rich_cell("{} {}".format(ICONS.get(a, ""), TITLE.get(a, a.title())).strip(), bold=True),
             raw_cell("{} {}".format(humanize(a, facts["totals"][a]), SECONDARY_NOUN.get(a, a))),
             raw_cell("{:,}".format(facts["sessions"][a]))] for a in activities[:99]]
    return native_table(("Activity", "All time", "Sessions"), body, ("left", "left", "right"))


def new_classic_blocks(look, facts, team):
    """The classic all-time summary in the new look: the same words in the same order as
    old_classic_blocks, each part in the newest block that suits it, and the old one wherever
    its feature is switched off."""
    blocks = [heading(look, "{}  How far we've come".format(team), 1),
              text_section(classic_line(facts))]
    if look.on("tiles"):
        blocks.append(tile_layout(look, classic_tile_parts(facts, team), "All time in numbers"))

    banked = classic_banked(facts)
    if banked:
        text = "\n".join(banked)
        if look.on("panels"):
            blocks.append(panel(look, "Already banked", [text_section(text)],
                                subtitle="Milestones that never reset", kind="banked"))
        else:
            blocks.append({"type": "divider"})
            blocks.append(heading(look, ":star2:  Already banked"))
            blocks.append(text_section(text))

    standing = classic_standing(facts)
    if standing:
        blocks.append({"type": "divider"})
        blocks.append(heading(look, ":dart:  Up next"))
        if look.on("cards"):
            blocks.append({"type": "carousel", "elements": [
                milestone_card(facts, share, activity, value, spot)
                for share, activity, value, spot in standing]})
        else:
            for share, activity, value, spot in standing:
                blocks.append(text_section(classic_standing_line(facts, share, activity, value, spot)))

    others = classic_other_activities(facts)
    if others:
        blocks.append({"type": "divider"})
        blocks.append(heading(look, ":seedling:  Also happening here"))
        if look.on("tables"):
            blocks.append(others_table(facts, others))
        else:
            blocks.append(text_section("\n".join(classic_other_line(facts, a) for a in others)))
        blocks.append(context_block(CLASSIC_INVITE))

    blocks.extend(classic_closing_blocks(standing))
    return blocks


def build_weekly_blocks(facts, rows, today, runs, image_url="", mention=False, look=None, team=""):
    """The weekly dashboard. Returns (blocks, summary) -- summary is what the post said,
    for the output and for the snapshot.

    Top to bottom: what happened (headline, numbers, moments), when (the calendar), then
    what is next (the milestone and the ask). All-time totals are one footer line.

    `look` is a Look (parse_look): the new look's features, or OLD_LOOK -- the post as it was
    before there was a choice. `team` is the team emoji the post wears; one is picked when
    it is blank, and the same one is passed back when the post is rebuilt as the old look.
    """
    look = look or OLD_LOOK
    people = gather_people(rows)
    week = week_facts(people, today)
    vol = volume_changes(facts, runs, today)

    doing = active_fields(people, today)
    opening, story = lede(facts, week, vol, today, doing)
    title = week_title(facts, week, today)
    team = team or team_emoji()               # one per post, so it reads as a choice
    moments = moments_from_table(people, week, facts, today, team, mention) + \
        moments_from_snapshot(facts, vol, story, doing)
    moments.sort(key=lambda m: -m[0])
    moments = moments[:MAX_MOMENTS]

    state = badge_state(people, today)
    earned = new_badges(state, today, previous_badges(runs, today))
    stop = next_stop(facts, vol, today, len(week["ids"]), doing)

    compose = new_look_blocks if look.new else old_look_blocks
    args = (facts, people, week, vol, today, doing, image_url, title, opening, team,
            moments, earned, stop, mention)
    blocks = compose(look, *args) if look.new else compose(*args)

    standing = nearest_stop(facts, doing)
    summary = {"people": len(week["ids"]), "checkins": week["checkins"],
               "new": len(week["new_people"]), "headline": opening, "title": title,
               "moments": [text for _, _, text in moments],
               "badges": badge_snapshot(state),
               "new_badges": [{"badge": b["name"], "people": [people[p]["name"] for p in pids]}
                              for b, pids in earned],
               "journey_km": round(steps_to_km(facts["totals"].get("step", 0)), 1),
               # the emoji the closing line asks for, so the post can wear it first
               "react": ICONS.get(standing[0][1], "") if stop and standing else "",
               "team": team}
    return blocks, summary


def weekly_fallback(summary):
    """The notification text: the greeting, then the story, without the markup."""
    parts = [re.sub(r":[a-z0-9_+-]+:", "", str(part or "").replace("*", "")).strip()
             for part in (summary.get("title"), summary["headline"])]
    return "  \u00b7  ".join(part for part in parts if part).replace("   ", " ")


# --------------------------------------------------------------------------- format

FORMATS = ("weekly", "classic")
DEFAULT_FORMAT = "weekly"
FORMAT_ALIASES = {"new": "weekly", "week": "weekly", "dashboard": "weekly",
                  "old": "classic", "original": "classic", "current": "classic",
                  "alltime": "classic", "all-time": "classic"}


def choose_format(value):
    """weekly (the default), classic, or random for one of the two. Anything unrecognised
    is weekly rather than a failure."""
    word = str(value or "").strip().lower()
    if word in ("random", "both", "mix", "either"):
        return random.choice(FORMATS)
    word = FORMAT_ALIASES.get(word, word)
    return word if word in FORMATS else DEFAULT_FORMAT


def truthy(value, default=False):
    """A recipe boolean, which may arrive as a bool or as text. Blank keeps the default."""
    if isinstance(value, bool):
        return value
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return default
    return text in ("true", "yes", "1", "y", "on")


def channel_today(tz_offset, override=""):
    day = parse_day(override)
    if day:
        return day
    try:
        offset = int(tz_offset)
    except (TypeError, ValueError):
        offset = DEFAULT_TZ_OFFSET
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).date()


# -------------------------------------------------------------------- entry

def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    result = {
        "ok": False, "error": "", "posted": False, "message_ts": "",
        "channel_id": (input.get("channel_id") or "").strip(),
        "format_used": "", "snapshot_saved": False,
        "message_text": "", "message_json": "",
        "people": 0, "sessions": 0, "since": "",
        "week_people": 0, "week_checkins": 0, "week_new_people": 0,
        "headline": "", "moments": [],
        "new_badges": [], "journey_km": 0, "journey_next_stop": "",
        "totals": [], "bests": [], "next_stops": [],
        "look_used": "",
    }

    token = (input.get("workato_dev_api") or "").strip()
    slack_token = (input.get("slack_bot_token") or "").strip()
    dry_run = truthy(input.get("dry_run"))
    save_snapshot = truthy(input.get("save_snapshot"), default=True)
    snapshot_row_type = (input.get("snapshot_row_type") or "").strip() or SNAPSHOT_ROW_TYPE
    today = channel_today(input.get("tz_offset"), input.get("today"))
    look = parse_look(input.get("look"), input.get("new_features"))

    if input.get("local_data_file"):
        with open(input["local_data_file"], "r", encoding="utf-8") as handle:
            rows = json.load(handle)
    else:
        if not token:
            result["error"] = "workato_dev_api is required"
            return result
        rows = fetch_rows(token, {"row_type": {"$in": [a + "_users" for a in ICONS]}})
    facts = summarize(rows)
    if not facts["logs"]:
        result["error"] = "nothing logged yet"
        return result

    result["people"] = facts["people"]
    result["sessions"] = facts["logs"]
    result["since"] = facts["since"]
    for activity in sorted(facts["totals"], key=lambda a: -facts["totals"][a]):
        value, noun = headline_value(activity, facts)
        result["totals"].append({
            "activity": activity, "headline": value, "noun": noun,
            "total": facts["totals"][activity],
            "sessions": facts["sessions"][activity]})
    for activity, best in sorted(facts["bests"].items()):
        result["bests"].append({
            "activity": activity, "best_day": best["day"],
            "best_day_by": best["day_by"], "best_set": best["set"],
            "best_set_by": best["set_by"]})
    for activity in HEADLINE:
        value, noun = headline_value(activity, facts)
        spot = ladder_position(activity, value)
        if value and spot:
            result["next_stops"].append({
                "activity": activity, "current": value,
                "target": spot["next"], "to_go": spot["to_go"],
                "tiers_completed": spot["tiers"], "tier_noun": spot["tier_noun"],
                "percent": int(round(spot["share"] * 100)), "noun": noun})

    # Last time's numbers. A snapshot that cannot be read costs the comparisons, never
    # the post -- and is left alone rather than overwritten.
    warnings = []
    if input.get("local_snapshot_file"):
        store = FileSnapshot(input["local_snapshot_file"])
    elif token:
        store = TableSnapshot(token, snapshot_row_type)
    else:
        store = None
    runs = []
    if store:
        runs, error = store.load()
        if error:
            warnings.append(error)

    fmt = choose_format(input.get("format"))
    result["format_used"] = fmt
    if fmt == "classic":
        look = look.without(CLASSIC_UNUSED)
    result["look_used"] = "new" if look.new else "old"
    summary, classic_team = None, ""
    if fmt == "weekly":
        blocks, summary = build_weekly_blocks(
            facts, rows, today, runs, (input.get("header_image_url") or "").strip(),
            mention=truthy(input.get("mention_people")), look=look)
        text = weekly_fallback(summary)
        result["week_people"] = summary["people"]
        result["week_checkins"] = summary["checkins"]
        result["week_new_people"] = summary["new"]
        result["headline"] = summary["headline"]
        result["moments"] = summary["moments"]
        result["new_badges"] = summary["new_badges"]
    else:
        classic_team = team_emoji()
        blocks = build_classic_blocks(facts, look=look, team=classic_team)
        text = fallback_text(facts)
    result["message_json"] = json.dumps(blocks)
    result["message_text"] = text
    steps_now = facts["totals"].get("step", 0)
    if steps_now:
        result["journey_km"] = round(steps_to_km(steps_now), 1)
        result["journey_next_stop"] = journey_position(steps_now)["ahead"][0]

    if dry_run:
        result["ok"] = True
        result["error"] = "; ".join(["dry run -- nothing posted"] + warnings)
        return result
    if not slack_token or not result["channel_id"]:
        result["error"] = "slack_bot_token and channel_id are required to post"
        return result

    thread_ts = (input.get("thread_ts") or "").strip()
    sent, error, ts = post(slack_token, result["channel_id"], text, blocks, thread_ts)
    asked, notes = look, []
    while not sent and look.new and "invalid_blocks" in error:
        # A workspace that does not take one of the newer blocks: the week is still worth
        # posting. The feature Slack named is taken out and the post built again, so the
        # rest of the new look stays; with nothing left it is the old post, which only uses
        # blocks every workspace takes. Slack's own words go in the error, to see which.
        refused = refused_features(error, json.loads(result["message_json"]), look)
        notes.append("new look refused by Slack ({}); trying without {}".format(
            error[:300], ", ".join(refused)))
        look = look.without(refused)
        if fmt == "weekly":
            blocks, summary = build_weekly_blocks(
                facts, rows, today, runs, (input.get("header_image_url") or "").strip(),
                mention=truthy(input.get("mention_people")), look=look, team=summary["team"])
            text = weekly_fallback(summary)
        else:
            blocks = build_classic_blocks(facts, look=look, team=classic_team)
        result["message_json"] = json.dumps(blocks)
        sent, error, ts = post(slack_token, result["channel_id"], text, blocks, thread_ts)
    dropped = [f for f in NEW_FEATURES if f in asked.features and f not in look.features]
    result["look_used"] = ("old" if not look.new else "new" if not dropped
                           else "new (without {})".format(", ".join(dropped)))
    warnings.extend(notes)
    result["posted"] = sent
    result["message_ts"] = ts
    result["ok"] = sent
    if not sent:
        result["error"] = "; ".join(notes + [error])
        return result

    # The closing line asks people to react; the post wears that reaction first, so
    # joining in is one tap rather than a search through the emoji picker.
    if summary and summary.get("react") and truthy(input.get("seed_reaction"), default=True):
        error = react(slack_token, result["channel_id"], ts, summary["react"])
        if error:
            warnings.append("reaction not added: " + error)

    # Saved after the post, whichever format went out, so the history keeps growing
    # even when the two formats are mixed. Failing to save never undoes the post.
    if store and save_snapshot:
        week = summary or {}
        # The week as announced. The classic format does not work it out, so it is
        # computed here -- the next weekly post compares against it either way.
        if not summary:
            current = week_facts(gather_people(rows), today)
            week = {"people": len(current["ids"]), "checkins": current["checkins"],
                    "new": len(current["new_people"])}
        run = {"d": today.isoformat(), "t": dict(facts["totals"]),
               "n": dict(facts["sessions"]), "p": facts["people"],
               "w": {"people": week["people"], "checkins": week["checkins"],
                     "new": week["new"]},
               # whichever format went out, so the next weekly post knows what is new
               "b": summary["badges"] if summary else current_badges(rows, today)}
        error = store.save(with_run(runs, run))
        if error:
            warnings.append(error)
        else:
            result["snapshot_saved"] = True
    result["error"] = "; ".join(warnings)
    return result
