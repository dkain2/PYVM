"""
Story Relay -- one true story a week, read a chapter a day and finished by the channel.

THE WEEK
    Sun   The Story Relay genie chooses ONE true, uplifting story from its knowledge base and
          returns it whole. A recipe hands that to this step, which has Azure cut it into four
          chapters, checks it, and keeps the week's story in the data table, ready.
    Mon   Chapter 1: the opening of the story, word for word, and the first turning point.
    Tue   Chapter 2      (the run settles Monday's picks first)
    Wed   Chapter 3
    Thu   Chapter 4: the ending. "Finish this story, or give it a better ending."
    Fri   The story we built: what the team chose, who picked, and how it really ended (sincere, with the
          lesson). Where it split from the real story (one light, playful line for each chapter the team
          changed, and a score) is a reply in the post's thread, for whoever wants the detail.

    Every chapter asks what happens next, with two buttons:
        Plot twist 1      two plot twists, neither labelled: one is what the story really did at
        Plot twist 2      this turning point, the other another way a decent person might have gone.
                          Which number is the real one moves about (real_slot), and is only
                          revealed on Friday
    Each person has ONE pick on EVERY chapter, so everyone can take part in each daily post (a weekly
    limit is optional: picks_per_week 1-3). The next morning's run counts the picks: the turn with
    the most picks wins, a tie keeps the story as it happened, and so does a chapter nobody picked
    on. The winner is what the story is from then on.

THE SUNDAY POST (mode announce) -- short, like the daily health post, and no spoilers
    context   📖 STORY RELAY  ·  🫂 FORGIVENESS  ·  Starts Monday  ·  ~15 sec read
    section   *The Window Seat*
              A true story about forgiveness is coming, and the ending is up to us.
              💡 _why the story stays with readers_
              • Mon–Thu: a short chapter each morning, with a choice at the end
              • Your pick: two buttons under each chapter: choose the turn the story takes
              • Fri: we publish the story the team built
              🎯 Our job: Finish this story, or give it a better ending.
    context   📖 Chapter 1 arrives Monday
    No buttons and no chapter text. It needs a story that is ready, and is recorded in the story's
    scheduled_time so a re-run does not post twice. The hook line turns with the week.

THE LAYOUT -- the story is the highlight; all the plotting is small text (context blocks)
    image     the banner, when there is one: banner_daily above each chapter, banner_announce on Sunday, banner_final
              on Friday (`banner` alone puts the same one on all three)
    context   📖 STORY RELAY  ·  🫂 EMPATHY  ·  Chapter 2 of 4  ·  ~25 sec read
    context   _So far:_ She made him a cup of tea and sat nearby.                (chapters 2-4)
    section   *The Window Seat*                                                  (the large text)

              > "I moved here alone three weeks ago," he said quietly. ...       (the story, verbatim)
    context   *What does Priya do next?*
              *Plot twist 1* — She offers no advice, pulls up a chair and listens.
              *Plot twist 2* — She suggests places and clubs where he could meet people.
    actions   [ Plot twist 1 ]  [ Plot twist 2 ]
    context   🎯 Finish this story, or give it a better ending.  ·  🗳️ One pick each, on every chapter
    context   👥 3 picks in so far  ·  ⏳ Picks close tomorrow at 8:30 AM        (in each reader's own time zone)

    A settled chapter's message loses its buttons and says what the team chose ("the team chose Plot
    twist 2", never which one was real).
    The passage in the quote is cut out of the story text by sentence number, never typed by a
    model, so it is always word for word. If the team has already taken a different turn, the passage
    would no longer follow, so the post shows a short bridge instead: two or three sentences the model
    writes that carry the story from what the team chose to this chapter's decision. (Without a model,
    or if its bridge fails the checks twice, the program builds one from the team's last choice and
    the chapter's set-up: a chapter on a different turn always has a bridge.)
    The text is hard-wrapped (wrap_chars, default 84) exactly as health_post.py does, with the same
    style repair across a cut.

MODES (the `mode` input; blank = guessed from what was given)
    history   Sunday, before the genie. Returns recent_stories ("title | theme | week", newest
              first) for the genie's prompt, so it does not repeat a story or a theme.
    announce  Sunday, once the story is ready: a short post about it and how the week will go (see
              THE SUNDAY POST). Posts once; force = yes posts again.
    prepare   Sunday, after story_store.py has stored the genie's story (status new): reads the story
              back FROM THE TABLE, has Azure cut it into four chapters (see AI), screens it for
              words that do not belong in a workplace, and makes it `ready`. Never posts. Not usable?
              ok = false with retry = true and retry_reason (and the stored genie conversation_id):
              send that to the genie in the same conversation. `post` also does it on the day if it
              was never done.
    post      The daily run (Mon-Fri). Settles the picks of the chapters already posted, then posts
              today's chapter (Mon-Thu) or publishes the finished story (Fri). A weekend run does
              nothing. A story left open from an earlier week is published first.
    click     A button was pressed (`action_value` present). Records the pick.

STORAGE -- the shared table, two row types of their own
    story_week   record_key story_week_<monday> · id / week_key the Monday · name the title ·
                 topic_name the theme · kb_tag the knowledge base · status ready | open | done ·
                 description the full story text · content {"pack": ..., "state": ...} ·
                 source_ref the latest chapter's ts · slack_channel_id
                   pack   title, author, kb, theme, why, lesson, main, and the four chapters
                          (snippet, setup, question, real, twist) -- fixed when it was saved
                   state  posts {chapter: ts}, settled [chapter], canon {chapter: what won},
                          picks_cap, closes {chapter: closing time}, bridges {chapter: text},
                          published ts
    story_pick   one per person per chapter · id / week_key the week · group_id the person (never
                 `id`: spotter reads every row with a person's id on each log, as it does not
                 weekly_accept's) · name their name · grant_type the chapter ·
                 status real | divert
    Only the daily run writes a story_week row, so clicks never race it. Nothing here collides with
    another feature: a row's type decides what its columns mean.

AI (Azure, optional except for `prepare`)
    prepare  ONE call: points at the sentences that make each chapter's passage and writes the
             set-up, the question, what really happened and one different turn. It never types the
             passage; Python cuts it out of the story. Every answer is checked, with one retry.
    post     a chapter that follows a different turn: one call writes the bridge (see THE LAYOUT).
             Friday: one call joins the team's chosen turns into a short story (150 words), kept
             to what they chose, one call writes the "where we split" lines (a plain line is used
             for any it does not write well), and one writes the real ending with its own context (who "the
             children" are), so it still connects to a team version that never mentioned them. Without a key the chosen lines are simply set out in order.
    Azure never writes the daily chapter, never changes the story text, and never sees anyone's name.

SAFETY
    The genie is told what a workplace story is. This step checks again: a deterministic screen of
    every word that is stored or shown (a hit means the story is not saved without `approve`), and the
    checks on what the model writes (no pings or links, no flagged words). Nothing a person types is
    ever posted: the only choices are the two prepared turns.

THE RECIPES (Slack: tell the click trigger to listen for an action_id that STARTS WITH
`story_relay_plot_` (story_relay_plot_1, story_relay_plot_2)).
    1. Sunday     schedule -> this step (mode history) -> genie -> story_store.py -> this step
                  (mode prepare) -> if retry: genie, same conversation -> story_store.py ->
                  prepare, up to twice -> this step (mode announce)
    2. Daily      schedule Mon-Fri -> this step (mode post)
    3. Click      Slack button -> this step (action_value, user_id, channel, action_ts)

RESTART  restart = yes (a testing aid; never leave it mapped on the scheduled recipe) starts this week's
story over: every pick of the week is set aside (renamed, not deleted), the week's own messages are
removed from the channel, and the story goes back to ready, so the daily run posts the chapter again
and picks, settling and Friday can be tried again the same day. force = yes, by comparison, only posts
a chapter again and keeps the picks.

TESTING  testing = yes posts a real sample chapter (chapter / today choose which) with working
buttons and writes NOTHING: its buttons carry `storyt|...`, so the click recipe needs nothing extra
and answers "test" without touching the table. skip_post = yes posts nothing and returns blocks_json
and a Block Kit Builder preview_url. With no story in the table a built-in sample story is used, and
the output says so.

Input / output schema: story_relay_input_schema.json / story_relay_output_schema.json
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Endpoints and limits
# --------------------------------------------------------------------------

TABLE_ID = "0b863cb1-4712-416b-a9d5-7bf7f2f9b059"
TABLE_QUERY_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
TABLE_RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
# There is no upsert: POST /records creates, PUT /records/{record_id} updates, and the
# record_id comes from the $record_id metafield on a query.
TABLE_RECORD_URL = TABLE_RECORDS_URL + "/{}"

SLACK_API = "https://slack.com/api/"
SLACK_POST_URL = SLACK_API + "chat.postMessage"
SLACK_UPDATE_URL = SLACK_API + "chat.update"
SLACK_DELETE_URL = SLACK_API + "chat.delete"
SLACK_EPHEMERAL_URL = SLACK_API + "chat.postEphemeral"
SLACK_USER_URL = SLACK_API + "users.info"
AZURE_URL = ("https://cour-servicenow-1.openai.azure.com/openai/deployments/"
             "gpt-4o/chat/completions?api-version=2024-10-21")
BLOCK_KIT_BUILDER = "https://app.slack.com/block-kit-builder#"
HTTP_TIMEOUT = 30

# Slack's own limits for the blocks used here (as health_post.py).
LIMITS = {"blocks": 50, "section": 3000, "field": 2000, "alt_text": 2000,
          "image_url": 3000, "context_elements": 10,
          "actions_elements": 25, "button_text": 75, "action_id": 255, "value": 2000,
          "block_id": 255}

# --------------------------------------------------------------------------
# The table: one UUID per column, in one place
# --------------------------------------------------------------------------

COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "group_name": "5ca195e6-35e1-4ec9-8916-96dc612f4480",
    "grant_type": "355e769f-0aa3-46be-bea3-5c2b3442f658",
    "status": "863a9d40-87a7-49ff-ba40-32858e62cd48",
    "week_key": "e9659bdd-c36c-486b-a531-e7b5a38252f6",
    "topic_name": "f4ec2556-bb08-49e0-8a7b-4fb608baf4f6",
    "kb_tag": "7addedee-88ea-400a-b74a-37a1c5ec843a",
    "description": "3d9e2f48-f2b0-457e-9666-5cada51a32b4",
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
    "source_ref": "e530be4a-68dc-4e9a-ad1f-2dbb8af3abf1",
    "slack_channel_id": "7101072d-867b-4104-a1e4-ef6611adaaa9",
    "last_processed_ts": "5761a90c-832e-4bf5-aaee-5d6a4d43f045",
    "scheduled_time": "8ebe17e6-05f3-4063-be9c-ed7b743c7b10",
    "created_at": "d0b48b75-2fbf-44db-a36a-cc0a1e46036c",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
}
COLUMN_TYPES = {name: "string" for name in COLUMNS}
COLUMN_TYPES.update({"created_at": "date", "updated_at": "date"})

STORY_ROW = "story_week"
PICK_ROW = "story_pick"
# new: stored by story_store.py, not yet cut into chapters. ready: cut, waiting for Monday.
NEW, READY, OPEN, DONE = "new", "ready", "open", "done"

# A text column holds 10,000 characters and a write over that is refused, so every column stays
# well under it (the same margin spotter.py keeps).
COLUMN_CHUNK = 9500
QUERY_MAX_PAGES = 50

# --------------------------------------------------------------------------
# The week
# --------------------------------------------------------------------------

CHAPTERS = 4                    # chapters 1-4 are posted Mon-Thu
PUBLISH_CHAPTER = CHAPTERS + 1  # "chapter 5" is the Friday story
# A person has one pick on each chapter. 0 = no limit across the week; picks_per_week (1 to CHAPTERS-1) on a
# run limits how many chapters one person may pick on.
DEFAULT_PICKS_CAP = 0
# The clock "today" is read on, in seconds east of UTC. India, like health_post.py: a
# schedule set for a morning in India reads as Sunday evening on the channel's old UTC-7
# clock, and the chapter would be a day out. Pass tz_offset for any other zone.
DEFAULT_TZ_OFFSET = 19800
# When a chapter's picks close, for readers in every time zone: this time of day (HH:MM) on the clock
# CLOSE_TZ_OFFSET seconds east of UTC (default 12:00 Pacific standard time). Each reader is shown it
# in their own time zone (Slack's <!date^...> token), and a pick after it is refused. Set the daily
# run for after this time, because the run is what counts the picks.
DEFAULT_CLOSE_TIME = "12:00"
DEFAULT_CLOSE_TZ = -28800
MIN_OPEN_HOURS = 1             # a chapter posted just before the time still stays open this long
TZ_NAMES = {-28800: "PST", -25200: "PDT", -21600: "CST", -18000: "EST", -14400: "EDT", 0: "UTC",
            3600: "CET", 19800: "IST", 28800: "SGT", 32400: "JST"}

# The story and what is cut from it.
MIN_STORY_WORDS = 100          # a cleaned story is short on purpose (about 220 words)
MAX_STORY_CHARS = COLUMN_CHUNK
MIN_SENTENCES = 8
# The passage of each chapter is KEPT long (up to 80 words) when the story is prepared, and the daily
# post shows as much of it as `passage_words` says, so the length of a post can be changed on any run
# with no model call. Showing less drops the earliest sentences; chapter 1 keeps the story's opening.
PASSAGE_WORDS = (60, 80)        # chapter 1's kept passage: at least / at most
MAX_PASSAGE_WORDS = 80          # the longest passage kept
DEFAULT_PASSAGE_WORDS = 50      # how much of it a post shows, unless passage_words says otherwise
PASSAGE_SHOWN_MIN, PASSAGE_SHOWN_MAX = 20, MAX_PASSAGE_WORDS
RECAP_WORDS = 12
TEXT_LIMITS = {"title": 90, "kb": 80, "author": 60, "theme": 24, "why": 120, "lesson": 160,
               "main": 80, "setup": 140, "question": 80, "real": 120, "twist": 120}
CREDITS_SHOWN = 8               # names in "Shaped by" before "and N others"
CHAPTER_ATTEMPTS = 3             # rounds with Azure; the answer is mended in code after the second if it is still not right
QUESTION_WORDS = 10             # a chapter's question: at most this many words (and TEXT_LIMITS["question"] characters)

# Visible characters per line (see health_post.py's TEXT_WIDTH: the banner is 1300 px wide).
# Context text is set smaller, so a line of it holds more.
CONTEXT_WRAP = 1.2
WRAP_CHARS = 84
WRAP_MIN, WRAP_MAX = 20, 120
WORDS_PER_SECOND = 3.3

# --------------------------------------------------------------------------
# Wording and design -- data, not logic
# --------------------------------------------------------------------------

SERIES_NAME = "Story Relay"
GOAL_TEXT = "Finish this story, or give it a better ending."
LABEL_REAL = "As it happened"
LABEL_TWIST = "A different turn"
TWIST_LABEL = "Plot twist {n}"
ICON_REAL = "\u2705"
ICON_TWIST = "\U0001F500"
ICON_GOAL = "\U0001F3AF"
ICON_PICKS = "\U0001F5F3\uFE0F"
ICON_COUNT = "\U0001F465"
ICON_CLOSE = "\u23F3"
ICON_THREAD = "\U0001F9F5"
ICON_WHY = "\U0001F4A1"
ICON_SERIES = "\U0001F4D6"
SEP = "  \u00b7  "
BANNER_ALT = "Story Relay"

# The Sunday post: short, no spoilers, and how the week will go. The hook turns with the week.
ANNOUNCE_HOOKS = (
    "This week we read a true story about {theme}, and decide how it goes.",
    "A true story about {theme} is coming, and the ending is up to us.",
    "One true story about {theme}, four short chapters, and you decide what happens next.",
    "We have a story about {theme} to finish this week.",
)
ANNOUNCE_STEPS = (
    "\u2022 *Mon\u2013Thu:* a short chapter each morning, with a choice at the end",
    "\u2022 *Your pick:* two buttons under each chapter: choose the turn the story takes",
    "\u2022 *Fri:* we publish the story the team built",
)
ANNOUNCE_LABEL = "Starts {when}"
ANNOUNCE_STEP_LABELS = ("*Mon\u2013Thu:*", "*Your pick:*", "*Fri:*")
ANNOUNCE_STEP_KEYS = ("mon_thu", "pick", "fri")

# Every button of a chapter has an action_id starting with ACTION_PREFIX, so ONE Slack click trigger
# ("action_id starts with story_relay_plot_") sends them all to this step, as imath_ and imemory_ do.
ACTION_PREFIX = "story_relay_plot_"
ACTION_BLOCK = "story_relay_plot"


# The note each person sees, privately, after pressing.
NOTE_LOCKED = (":white_check_mark: Locked in: *{choice}* for chapter {chapter}. That is your pick "
               "for this chapter, so it is yours alone.")
NOTE_USED = ("You have already used all {cap} of your picks for this week, the last on chapter "
             "{chapter} ({choice}). Fresh ones arrive with next week's story.")
NOTE_THIS_CHAPTER = "You have already picked on chapter {chapter}, one pick each on every chapter."
NOTE_NEXT = " You get another with tomorrow's chapter."
NOTE_CLOSED_DEADLINE = ("Picks for chapter {chapter} closed {when}, so yours could not be counted. "
                        "The newest Story Relay post is the one open for picks.")
NOTE_CLOSED_SETTLED = ("Chapter {chapter} has already been counted and closed, so it takes no more "
                       "picks. Pick on the newest Story Relay post instead.")
NOTE_CLOSED_NOT_POSTED = "Chapter {chapter} has not been posted this week, so there is nothing to pick on yet."
NOTE_COUNT = " {count} pick{s} in so far."
NOTE_FINISHED = "That story has finished. Next week's starts on Monday."
NOTE_TEST = (":test_tube: This is a test post, so nothing was saved. A real pick would have been "
             "*{choice}* for chapter {chapter}.")
NOTE_TRY_AGAIN = "Something went wrong on my side ({why}). Please try again in a minute."


THEME_EMOJI = (
    ("empath", "\U0001FAC2"), ("compassion", "\U0001FAC2"), ("kind", "\U0001F49B"),
    ("love", "\u2764\uFE0F"), ("gratitude", "\U0001F64F"), ("thank", "\U0001F64F"),
    ("courage", "\U0001F981"), ("brave", "\U0001F981"), ("persever", "\U0001F9D7"),
    ("resilien", "\U0001F333"), ("motivat", "\U0001F680"), ("forgiv", "\U0001F54A\uFE0F"),
    ("humil", "\U0001F331"), ("generos", "\U0001F381"), ("mentor", "\U0001F9ED"),
    ("team", "\U0001F91D"), ("friend", "\U0001F91D"), ("family", "\U0001F3E1"),
    ("hope", "\U0001F305"), ("health", "\U0001F33F"), ("diet", "\U0001F957"),
    ("food", "\U0001F957"), ("sleep", "\U0001F634"), ("patien", "\u23F3"),
    ("listen", "\U0001F442"),
)
DEFAULT_THEME_EMOJI = ICON_SERIES

# Words that do not belong in a workplace story. A hit never silently passes: a story is not
# saved until a person says so (approve = yes).
FLAGGED = re.compile(
    r"\b(?:sex\w*|naked|nude\w*|porn\w*|rap(?:e|ed|es|ist|ists)|molest\w*|abus\w+|suicid\w*"
    r"|self[- ]harm\w*|murder\w*|kill\w*|terroris\w*|massacre\w*|genocide|nazi\w*|cocaine|heroin"
    r"|overdos\w*|fuck\w*|shit\w*|bitch\w*|slut\w*|whore\w*)\b", re.I)

# A story for a global workplace has no religion in it and does not hang on one festival. Checked
# on stories only, and like FLAGGED it holds a story back until a
# person says so (approve = yes).
RELIGIOUS = re.compile(
    r"\b(?:bible|biblical|scripture\w*|gospel|jesus|christ|christian\w*|church\w*|mosque\w*"
    r"|synagogue\w*|temple|allah|gabriel|prayer\w*|pray(?:s|ed|ing)?|christmas|easter|ramadan"
    r"|diwali|hanukkah|god|heaven|angels?)\b", re.I)
# Not wrong, but a story that only works in one country. A note for the person who reads it.
REGIONAL = re.compile(r"[$\u00a3\u20ac\u20b9\u00a5]\s?\d[\d,.]*|\b(?:1[89]|20)\d\d\b")

# Topics the genie is told to avoid because the team will be changing the story. A hit is only a
# note in the save step's warnings, for a person to read before Monday.
HEAVY = re.compile(
    r"\b(?:die[ds]?|dying|death|dead|funeral|cancer|hospice|terminal|war|soldiers?|gun|shot|bomb"
    r"|disaster|accident|crash|abandon\w*|orphan\w*|divorc\w*|bankrupt\w*|homeless|addict\w*"
    r"|alcohol\w*|drunk|drug\w*)\b", re.I)

# --------------------------------------------------------------------------
# Text -- copied from health_post.py (a Workato step is one file, so it is copied; a test fails
# if the two drift). Slack's own <...> tokens reach it untouched.
# --------------------------------------------------------------------------

_EMOJI = ("[" + "".join("{}-{}".format(chr(a), chr(b)) for a, b in ((0x2190, 0x2BFF), (0x1F000, 0x1FAFF)))
          + "".join(chr(c) for c in (0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299))
          + "]")
_MODIFIER = "[" + "".join(chr(c) for c in (0xFE0F, 0x200D, 0x20E3)) + "]"
_SLACK_TOKEN = re.compile(r"(<(?:[@#!][^>\s]*|https?://[^>\s]+|mailto:[^>\s]+)>)")


def plain(text):
    """Text with its mrkdwn taken out: for a button label and the notification."""
    out = re.sub(r"<[^>|]+\|([^>]+)>", r"\1", str(text or ""))
    out = out.replace("*", "").replace("`", "")
    out = re.sub(r"(?<![\w])_([^_\n]+)_(?![\w])", r"\1", out)
    return re.sub(r"\s+", " ", out).strip()


def escape(text):
    """Slack's three escapes (&, <, >), leaving its own <...> tokens and the > of a quote
    at the start of a line as they are."""
    out = []
    for index, piece in enumerate(_SLACK_TOKEN.split(text)):
        if index % 2:
            out.append(piece)
            continue
        piece = re.sub(r"&(?!(?:amp|lt|gt);)", "&amp;", piece).replace("<", "&lt;")
        lines = piece.split("\n")
        for number, line in enumerate(lines):
            head = ""
            quote = re.match(r"\s*>+", line) if (number or not index) else None
            if quote:
                head, line = quote.group(0), line[quote.end():]
            lines[number] = head + line.replace(">", "&gt;")
        out.append("\n".join(lines))
    return "".join(out)


def escape_name(text):
    """A person's name, safe to show: &, < and > all escaped, so a name that contains a Slack mention or
    @channel is shown as text and can never ping anyone (escape() leaves Slack's own tokens alone, which is
    right for our own text and wrong for a name somebody else typed)."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_WORD = re.compile(r"(?:<[^>\n]*>|\S)+")
_ENTITY = re.compile(r"&(?:amp|lt|gt);")


def _boundary(char):
    return not char.isalnum()


def _span_states(words):
    """For each word, the style spans (* bold, _ italic, ` code) open where it starts and where
    it ends, as strings in the order they were opened. A * or _ counts as a mark only at the
    edge of a word, as Slack reads it, so snake_case and 5 * 3 are left alone."""
    open_spans, states = [], []
    for word in words:
        before = "".join(open_spans)
        for index, char in enumerate(word):
            if char not in "*_`":
                continue
            prev = word[index - 1] if index else " "
            nxt = word[index + 1] if index + 1 < len(word) else " "
            if char in open_spans:
                if not prev.isspace() and (_boundary(nxt) or nxt in "*_`"):
                    open_spans.remove(char)
            elif _boundary(prev) and not nxt.isspace():
                open_spans.append(char)
        states.append((before, "".join(open_spans)))
    return states


def _visible(word):
    """How wide a word is on screen: no style marks, an emoji two characters wide, a mention
    about ten, a link as its label."""
    text = re.sub(r"<@[^>]*>", "x" * 10, word)
    text = re.sub(r"<[^>|]*\|([^>]*)>", r"\1", text)
    text = _ENTITY.sub("x", text)
    # a style mark is the edge of a word: * and ` next to something, _ at the start or end of
    # the word (not snake_case, not a lone *)
    text = re.sub(r"(?<=\S)[*`]|[*`](?=\S)", "", text)
    text = re.sub(r"(?<![A-Za-z0-9])_(?=\S)|(?<=\S)_(?![A-Za-z0-9])", "", text)
    width = 0
    for char in text:
        if re.match(_MODIFIER, char):
            continue
        width += 2 if re.match(_EMOJI, char) else 1
    return width


def wrap_line(line, limit):
    """One line cut into lines of at most `limit` visible characters, at spaces. A style open
    across a cut is closed at the end of its line and reopened at the start of the next; a
    word wider than the limit stays whole."""
    words = _WORD.findall(line)
    if not words or limit <= 0:
        return [line]
    states = _span_states(words)
    rows, row, used = [], [], 0
    for index, word in enumerate(words):
        width = _visible(word)
        if row and used + 1 + width > limit:
            rows.append(row)
            row, used = [], 0
        used += (1 if row else 0) + width
        row.append(index)
    rows.append(row)
    out = []
    for number, row in enumerate(rows):
        text = " ".join(words[i] for i in row)
        if number:
            text = states[row[0]][0] + text
        if number < len(rows) - 1:
            text += "".join(reversed(states[row[-1]][1]))
        out.append(text)
    return out


def banner_block(ref, alt_text=BANNER_ALT):
    """An image block for a URL or a Slack file id (Fxxxxxxxx), or None when none is given."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    if ref.startswith(("http://", "https://")):
        return {"type": "image", "image_url": ref, "alt_text": alt_text}
    return {"type": "image", "slack_file": {"id": ref}, "alt_text": alt_text}


def section(text, block_id=None, accessory=None):
    block = {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    if block_id:
        block["block_id"] = block_id
    if accessory:
        block["accessory"] = accessory
    return block


def context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def button(label, action_id, value, style=""):
    out = {"type": "button", "action_id": action_id, "value": value,
           "text": {"type": "plain_text", "text": label, "emoji": True}}
    if style:
        out["style"] = style
    return out


def block_problems(blocks):
    """Every way a block list breaks one of Slack's limits. Empty means Slack takes it."""
    problems = []
    if len(blocks) > LIMITS["blocks"]:
        problems.append("{} blocks (limit {})".format(len(blocks), LIMITS["blocks"]))
    seen = set()

    def check_button(item, where):
        if len(item["text"]["text"]) > LIMITS["button_text"]:
            problems.append("{}: button text over {}".format(where, LIMITS["button_text"]))
        if len(item["action_id"]) > LIMITS["action_id"]:
            problems.append("{}: action_id too long".format(where))
        if len(item.get("value", "")) > LIMITS["value"]:
            problems.append("{}: button value over {}".format(where, LIMITS["value"]))

    for number, block in enumerate(blocks):
        where = "block {} ({})".format(number, block.get("type"))
        block_id = block.get("block_id")
        if block_id:
            if block_id in seen:
                problems.append("{}: block_id {} repeated".format(where, block_id))
            seen.add(block_id)
            if len(block_id) > LIMITS["block_id"]:
                problems.append("{}: block_id too long".format(where))
        kind = block.get("type")
        if kind == "section":
            if block.get("fields"):
                if len(block["fields"]) > 10 or not all(
                        0 < len(f["text"]) <= LIMITS["field"] for f in block["fields"]):
                    problems.append("{}: fields need 1-{} characters each, 10 at most".format(
                        where, LIMITS["field"]))
            elif not 0 < len(block["text"]["text"]) <= LIMITS["section"]:
                problems.append("{}: section text must be 1-{} characters".format(
                    where, LIMITS["section"]))
            if block.get("accessory", {}).get("type") == "button":
                check_button(block["accessory"], where)
        elif kind == "image":
            if len(block.get("image_url", "")) > LIMITS["image_url"]:
                problems.append("{}: image_url over {}".format(where, LIMITS["image_url"]))
            if not 0 < len(block.get("alt_text", "")) <= LIMITS["alt_text"]:
                problems.append("{}: alt_text must be 1-{} characters".format(
                    where, LIMITS["alt_text"]))
        elif kind == "context":
            if len(block["elements"]) > LIMITS["context_elements"]:
                problems.append("{}: more than {} elements".format(
                    where, LIMITS["context_elements"]))
        elif kind == "actions":
            if not 0 < len(block["elements"]) <= LIMITS["actions_elements"]:
                problems.append("{}: needs 1-{} elements".format(
                    where, LIMITS["actions_elements"]))
            for element in block["elements"]:
                if element.get("type") == "button":
                    check_button(element, where)
    return problems


def preview_url(blocks):
    """Slack's Block Kit Builder with this message loaded, to look at before posting."""
    return BLOCK_KIT_BUILDER + urllib.parse.quote(
        json.dumps({"blocks": blocks}, separators=(",", ":"), ensure_ascii=False))


# --------------------------------------------------------------------------
# Text -- this step's own
# --------------------------------------------------------------------------

def count_words(text):
    return len(re.findall(r"[A-Za-z0-9][\w'’%.\-]*", plain(text)))


def read_seconds(words):
    """How long it takes to read, to the nearest 5 seconds and never under 10."""
    return max(10, int(round(words / WORDS_PER_SECOND / 5.0)) * 5)


def banner_pick(own, general):
    """The banner of one kind of post: its own input when given, otherwise the general `banner`."""
    return str(own or general or "").strip()


def tidy(text):
    """One line of plain text: whitespace collapsed, no Slack styling marks."""
    out = str(text or "").replace("\r", " ")
    out = re.sub(r"[*`]", "", out)
    out = re.sub(r"(?<![A-Za-z0-9])_+|_+(?![A-Za-z0-9])", "", out)
    return " ".join(out.split())


def clip(text, limit):
    """`text` cut to `limit` characters: at the last sentence end if one is past the halfway
    mark, otherwise at a word, with an ellipsis."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if cut >= limit * 0.5:
        return window[:cut + 1]
    return window[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"


def shorten_words(text, count):
    words = str(text or "").split()
    if len(words) <= count:
        return " ".join(words)
    return " ".join(words[:count]).rstrip(",;:-") + "…"


def sentence_end(text):
    text = str(text or "").strip()
    return text if text.endswith((".", "!", "?", "…", '"', "”")) else text + "."


def flagged_words(*texts):
    """The words in `texts` that do not belong in a workplace story, lowercase, once each."""
    found = set()
    for text in texts:
        found.update(word.lower() for word in FLAGGED.findall(str(text or "")))
    return sorted(found)


def story_flags(*texts):
    """flagged_words, plus religion: what keeps a STORY from being saved."""
    found = set(flagged_words(*texts))
    for text in texts:
        found.update(word.lower() for word in RELIGIOUS.findall(str(text or "")))
    return sorted(found)


def regional_notes(*texts):
    """The money amounts and years in the texts, as people would spot them."""
    found = []
    for text in texts:
        found += [m.group(0).strip() for m in REGIONAL.finditer(str(text or ""))]
    return list(dict.fromkeys(found))[:4]


def heavy_words(*texts):
    """Words that are not wrong but make a heavy story, for a person to look at."""
    found = set()
    for text in texts:
        found.update(word.lower() for word in HEAVY.findall(str(text or "")))
    return sorted(found)


def and_join(items):
    items = [str(i) for i in items]
    if len(items) < 3:
        return " and ".join(items)
    return "{} and {}".format(", ".join(items[:-1]), items[-1])


def theme_emoji(theme):
    text = str(theme or "").lower()
    for word, emoji in THEME_EMOJI:
        if word in text:
            return emoji
    return DEFAULT_THEME_EMOJI


def clean_theme(raw):
    """One or two lowercase words, letters and hyphens only."""
    words = re.findall(r"[a-z][a-z\-]*", str(raw or "").lower())
    return " ".join(words[:2])[:TEXT_LIMITS["theme"]]


_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc", "no", "inc", "ltd"}
_SENTENCE_END = re.compile(
    "[.!?]+[\"'\u201d\u2019)\\]]*(?=\\s+[\"'\u201c\u2018(\\[]?[A-Z0-9])")


def split_sentences(text):
    """The story as sentences, in order. A blank line always ends one. A full stop after Mr,
    Dr, an initial and the like does not."""
    sentences = []
    for paragraph in re.split(r"\n\s*\n", str(text or "").replace("\r\n", "\n")):
        paragraph = " ".join(paragraph.split())
        start = 0
        for found in _SENTENCE_END.finditer(paragraph):
            before = paragraph[start:found.start()]
            word = re.search(r"([A-Za-z]+)$", before)
            if found.group(0).startswith("."):
                if word and word.group(1).lower() in _ABBREVIATIONS:
                    continue
                if re.search(r"(?:^|\s)[A-Z]$", before):
                    continue
            sentences.append(paragraph[start:found.end()].strip())
            start = found.end()
        tail = paragraph[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def passage_text(sentences, first, last, high=MAX_PASSAGE_WORDS):
    """Sentences first..last as one passage of at most `high` words. Too long, it loses its
    EARLIEST sentences, because the decision comes straight after the last one; a single
    sentence that is itself too long is cut at a word."""
    chosen = list(sentences[first:last + 1])
    while len(chosen) > 1 and count_words(" ".join(chosen)) > high:
        chosen.pop(0)
    text = " ".join(chosen)
    if count_words(text) > high:
        text = shorten_words(text, high)
    return text


def first_passage(sentences, low=PASSAGE_WORDS[0], high=PASSAGE_WORDS[1]):
    """Index of the last sentence of chapter 1's passage: the story's opening, taken sentence by
    sentence until it is at least `low` words and before it would pass `high`."""
    end, words = 0, 0
    for index, sentence in enumerate(sentences):
        size = count_words(sentence)
        if index and words + size > high:
            break
        end, words = index, words + size
        if words >= low:
            break
    return end


def fit_passage(snippet, words, keep_opening=False):
    """The kept passage cut down to about `words` words, whole sentences only.

    The decision comes straight after the last sentence, so the LAST sentences are the ones kept and
    the earliest go. Chapter 1 (`keep_opening`) also keeps the story's own first sentence, with an
    ellipsis where the middle was left out. A passage already short enough is returned as it is."""
    sentences = split_sentences(snippet)
    if count_words(snippet) <= words or len(sentences) < 2:
        return snippet
    head = sentences[0] if keep_opening else ""
    pool = sentences[1:] if keep_opening else sentences
    budget = words - (count_words(head) if head else 0)
    kept = []
    for sentence in reversed(pool):
        if kept and count_words(" ".join([sentence] + kept)) > budget:
            break
        kept.insert(0, sentence)
    if not head:
        return " ".join(kept)
    return head if not kept else (" ".join([head] + kept) if len(kept) == len(pool)
                                  else head + " \u2026 " + " ".join(kept))


def similar(a, b):
    """How alike two short texts are, 0-1, by the words they share."""
    one = set(re.findall(r"[a-z']+", str(a).lower()))
    two = set(re.findall(r"[a-z']+", str(b).lower()))
    return len(one & two) / float(len(one | two)) if one and two else 0.0


# --------------------------------------------------------------------------
# Dates -- the week is Monday to Friday, read on the channel's clock
# --------------------------------------------------------------------------

def _utc_now():
    """Its own function so the tests can fix the day."""
    return datetime.now(timezone.utc)


def local_today(offset_seconds, override=""):
    asked = str(override or "").strip()
    if asked:
        try:
            return datetime.strptime(asked[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return (_utc_now() + timedelta(seconds=offset_seconds)).date()


def monday_of(day):
    return day - timedelta(days=day.weekday())


def week_for_save(day):
    """The week a saved story is for: this one, except on a Saturday or Sunday, when the story is
    for the Monday that is coming."""
    if day.weekday() >= 5:
        return day + timedelta(days=7 - day.weekday())
    return monday_of(day)


def target_for(day):
    """What today's run does: chapter 1-4 on Monday to Thursday, 5 (publish) on Friday, 0 at the
    weekend."""
    weekday = day.weekday()
    return weekday + 1 if weekday <= CHAPTERS - 1 else (PUBLISH_CHAPTER if weekday == CHAPTERS else 0)


# --------------------------------------------------------------------------
# The story, cut into chapters
# --------------------------------------------------------------------------

def read_story(fields):
    """The genie's fields, tidied: (story, problems). A problem is something to tell the genie."""
    story = {
        "title": clip(tidy(fields.get("story_title")), TEXT_LIMITS["title"]),
        "kb": clip(tidy(fields.get("kb_name")), TEXT_LIMITS["kb"]),
        "author": clip(tidy(fields.get("story_author")), TEXT_LIMITS["author"]),
        "theme": clean_theme(fields.get("theme")),
        "why": clip(tidy(fields.get("why_it_resonates")), TEXT_LIMITS["why"]),
        "main": clip(tidy(fields.get("main_character")), TEXT_LIMITS["main"]),
        "adapted": _flag(fields.get("adapted")),
        "lesson": clip(tidy(fields.get("lesson")), TEXT_LIMITS["lesson"]),
        "text": re.sub(r"\n{3,}", "\n\n", str(fields.get("story_text") or "").replace("\r\n", "\n")
                       .replace("\r", "\n")).strip(),
    }
    problems = []
    for key, name in (("title", "story_title"), ("kb", "kb_name"), ("theme", "theme"),
                      ("text", "story_text")):
        if not story[key]:
            problems.append("{} is empty".format(name))
    if story["text"]:
        words = count_words(story["text"])
        if words < MIN_STORY_WORDS:
            problems.append("the story is only {} words, too short to cut into four chapters".format(words))
        if len(story["text"]) > MAX_STORY_CHARS:
            problems.append("the story is {:,} characters, too long to keep (choose one of 400 to "
                            "1,500 words)".format(len(story["text"])))
    return story, problems


CHAPTER_SYSTEM = (
    "You prepare a true story for a shared storytelling game in a workplace Slack channel read by "
    "colleagues across companies and countries, senior people included. The team reads the story in "
    "four short chapters and, at the end of each, decides what happens next.\n\n"
    "You are given the story as numbered sentences. You never invent what happened in the story "
    "and you never quote it: you point at sentences by number and write short lines about them. "
    "You return JSON only.\n\n"
    "For each of the four chapters return:\n"
    "- from, to: the numbers of the first and last sentence of the passage the team reads in that "
    "chapter. Not for chapter 1: its passage is given.\n"
    "- setup: one sentence of at most 18 words that sets the scene in neutral words for a reader "
    "who has NOT read the passage and may have taken a different path in earlier chapters. Name "
    "the person and the situation, never the details of earlier events.\n"
    "- question: what the team decides, at most " + str(QUESTION_WORDS) + " words and "
    + str(TEXT_LIMITS["question"]) + " characters in all (spaces and punctuation count; a longer "
    "one is rejected), ending with a question mark, about what a person does, says or chooses "
    "next. It must not reveal what happens.\n"
    "- real: what the story says happens right after the passage, one plain sentence of at most 15 "
    "words, using only what the story says.\n"
    "- twist: a different turn the story could have taken from the same moment, one plain sentence "
    "of at most 15 words. It must be as believable and as decent as the real one, in the same "
    "theme, with no villain, no harm and nothing silly: another way a good person might have "
    "gone, not a worse one.\n\n"
    "Passages: in story order, never overlapping, each at most 80 words, each followed by at least "
    "one more sentence of the story. Chapters 2 and 3 end at turning points where someone chooses "
    "how to act. Chapter 4's passage leads into the ending: its real is how the story ends and its "
    "twist is a kinder, braver or wiser ending the team could choose instead.\n\n"
    "THEME. You are given the story's theme. Every chapter's question and both options must put "
    "that theme to the reader, so the team thinks about it as it chooses. Each option is a "
    "different answer to what the theme asks of a person at that moment (courage: speak up or "
    "stay quiet, try the new thing or hold back, say the hard thing or keep the peace; kindness: "
    "help or hurry past; forgiveness: let it go or hold on). Where it fits, use the theme's own "
    "words or close ones (courage: brave, afraid, risk, dare, speak up) inside the question or an "
    "option, never as a slogan and never the bare theme word as a label. Both options are "
    "defensible ways a decent person might act: neither is the villain's choice or the obviously "
    "wrong one, so the team has to weigh it.\n\n"
    "CHOICES, NOT REASONS. The question asks what a person DOES, SAYS or CHOOSES next and never why "
    "something happened: never begin it with Why. Both options are things a person does or says. "
    "Bad: 'Why does the team hesitate?' with 'An employee reveals she is afraid.' Good: 'Does "
    "Sharon press on, or let the team stay comfortable?' with 'She asks the team to name their fear "
    "out loud.' and 'She drops the exercise and lets them keep their old routine.'\n\n"
    "Plain global English, no slang, no emoji, no markdown, no names that are not in the story, "
    "nothing about knowledge bases, games, votes or how you chose.")

CHAPTER_SHAPE = (
    '{"chapters": [{"setup": "...", "question": "...?", "real": "...", "twist": "..."}, '
    '{"from": 0, "to": 0, "setup": "...", "question": "...?", "real": "...", "twist": "..."}, '
    '{"from": 0, "to": 0, ...}, {"from": 0, "to": 0, ...}]}  (four chapters)')


def chapter_prompt(story, sentences, first_end, fixes=()):
    lines = ["Title: {}".format(story["title"]), "Theme: {}".format(story["theme"]),
             "Main character: {}".format(story["main"] or "not given"),
             "Lesson: {}".format(story["lesson"] or "not given"), "",
             "Chapter 1's passage is sentences 0 to {}.".format(first_end), "",
             "The story, one numbered sentence per line:"]
    lines += ["[{}] {}".format(i, s) for i, s in enumerate(sentences)]
    lines += ["", "Return JSON shaped like: " + CHAPTER_SHAPE]
    if fixes:
        lines += ["", "Your last answer had these problems. Fix every one:"]
        lines += ["- " + f for f in fixes]
    return "\n".join(lines)


def parse_chapters(answer, sentences, first_end):
    """The four chapters from Azure's answer: (chapters, errors, flagged). Each chapter is
    {"snippet", "setup", "question", "real", "twist", "from", "to"}, the snippet cut from the story
    by sentence number. `errors` are things to tell Azure to fix."""
    errors, flagged = [], set()
    items = answer.get("chapters") if isinstance(answer, dict) else None
    if not isinstance(items, list) or len(items) != CHAPTERS:
        return [], ["return exactly {} chapters".format(CHAPTERS)], []
    chapters, previous = [], first_end
    for number, item in enumerate(items, 1):
        if not isinstance(item, dict):
            errors.append("chapter {} is not an object".format(number))
            continue
        if number == 1:
            first, last = 0, first_end
        else:
            try:
                first, last = int(item.get("from")), int(item.get("to"))
            except (TypeError, ValueError):
                errors.append("chapter {}: from and to must be sentence numbers".format(number))
                continue
            if not previous < first <= last < len(sentences) - 1:
                errors.append(
                    "chapter {}: the passage must start after sentence {} (chapter {}'s), and "
                    "leave at least one sentence of the story after it (the story has sentences "
                    "0 to {})".format(number, previous, number - 1, len(sentences) - 1))
                continue
        row = {"snippet": passage_text(sentences, first, last), "from": first, "to": last}
        asked = tidy(item.get("question"))      # as Azure wrote it, before clip() can cut it short
        for field in ("setup", "question", "real", "twist"):
            row[field] = clip(tidy(item.get(field)), TEXT_LIMITS[field])
            if not row[field]:
                errors.append("chapter {}: {} is empty".format(number, field))
        if len(asked) > TEXT_LIMITS["question"]:
            # clip() would end it with "…" in place of its "?", and "must end with a question mark"
            # tells Azure nothing about a question that does end with one: say what is wrong.
            errors.append("chapter {}: the question is {} characters, over the limit of {}: shorten "
                          "it to at most {} words and {} characters, still ending with a question "
                          "mark (yours: \"{}\")".format(
                              number, len(asked), TEXT_LIMITS["question"], QUESTION_WORDS,
                              TEXT_LIMITS["question"], clip(asked, 120)))
        elif row["question"] and not row["question"].endswith("?"):
            errors.append("chapter {}: the question must end with a question mark (yours ends: "
                          "\"{}\")".format(number, row["question"][-25:]))
        if re.match(r"\s*why\b", row["question"], re.I):
            errors.append("chapter {}: ask what a person does or chooses next, not why ('Does she ... or "
                          "...?', 'What does she do about ...?')".format(number))
        if row["real"] and row["twist"] and similar(row["real"], row["twist"]) > 0.7:
            errors.append("chapter {}: the twist is too close to what really happened".format(number))
        flagged.update(story_flags(row["setup"], row["question"], row["real"], row["twist"]))
        chapters.append(row)
        previous = last
    return (chapters if not errors else []), errors, sorted(flagged)


def generic_question(number, main):
    """A plain question that is always sound, for when Azure's own cannot be used."""
    if number == CHAPTERS:
        return "How does the story end?"
    name = " ".join(re.split(r"[,(]", str(main or ""))[0].split()[:3])
    return "What does {} do next?".format(name or "the main character")


def repair_question(text, number, main):
    """A usable question made of what Azure wrote: the last sentence that asks something, with a
    question mark, cut at a comma / 'or' / 'and' if it is over the limit. When nothing of it can be
    kept (empty, begins with Why, no clause that fits), the plain question for the chapter."""
    text = tidy(text)
    limit = TEXT_LIMITS["question"]
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text) if p]
    asking = [p for p in parts if p.endswith("?")]
    body = (asking or parts or [""])[-1].rstrip(" \"'”’.!?…,;:-")
    if not body or re.match(r"\s*why\b", body, re.I):
        return generic_question(number, main)
    if len(body) + 1 <= limit:
        return body + "?"
    for found in reversed(list(re.finditer(r",\s|\sor\s|\sand\s|;\s", body))):
        head = body[:found.start()].rstrip(" ,;")
        if len(head.split()) >= 3 and len(head) + 1 <= limit:
            return head + "?"
    return generic_question(number, main)


def default_span(previous, number, count):
    """Where chapter `number`'s passage goes when Azure's numbers cannot be used: an even share of
    the sentences left. None when too few are left for the chapters still to come."""
    available = count - 2 - previous            # sentences previous+1 .. count-2 can be passages
    remaining = CHAPTERS - number + 1
    if available < remaining:
        return None
    first = previous + 1
    return first, min(first + max(1, available // remaining) - 1, count - 2)


def repair_chapters(answer, sentences, first_end, main="", notes=None):
    """The four chapters from Azure's answer, whatever is wrong with it: (chapters, flagged).

    Every problem that parse_chapters reports back to Azure is mended here instead, so a week's story
    is never lost to wording: a question over the limit or without a question mark is cut to a clause
    that fits (or replaced by a plain one); bad sentence numbers become an even share of the story; an
    empty line becomes a plain one, the real option from the story's next sentence. What was changed is
    added to `notes`. Only an answer with no chapters in it, or a story with no room left for them,
    gives ([], [])."""
    notes = notes if notes is not None else []
    items = answer.get("chapters") if isinstance(answer, dict) else None
    if not isinstance(items, list) or len(items) < CHAPTERS:
        return [], []
    count = len(sentences)
    who = " ".join(re.split(r"[,(]", str(main or ""))[0].split()[:3]) or "The main character"
    chapters, flagged, previous = [], set(), first_end
    for number, item in enumerate(items[:CHAPTERS], 1):
        item = item if isinstance(item, dict) else {}
        if number == 1:
            first, last = 0, first_end
        else:
            try:
                first, last = int(item.get("from")), int(item.get("to"))
            except (TypeError, ValueError, OverflowError):
                first, last = -1, -2
            if not previous < first <= last <= count - 2 - (CHAPTERS - number):
                span = default_span(previous, number, count)
                if span is None:
                    return [], []
                first, last = span
                notes.append("chapter {}: its passage was set by the program".format(number))
        row = {"snippet": passage_text(sentences, first, last), "from": first, "to": last}
        asked = tidy(item.get("question"))
        row["question"] = repair_question(asked, number, main)
        if row["question"] != asked:
            notes.append("chapter {}: the question was changed to \"{}\" (Azure wrote \"{}\")".format(
                number, row["question"], clip(asked, 120)))
        for field in ("setup", "real", "twist"):
            row[field] = clip(tidy(item.get(field)), TEXT_LIMITS[field])
        fallback = {
            "setup": "{} reaches a turning point.".format(who),
            "real": clip(sentences[last + 1] if last + 1 < count else "", TEXT_LIMITS["real"]),
            "twist": ("The story ends in another thoughtful way." if number == CHAPTERS
                      else "Another thoughtful choice is made at this moment.")}
        for field in ("setup", "real", "twist"):
            if not row[field]:
                row[field] = fallback[field] or fallback["twist"]
                notes.append("chapter {}: {} was empty, so a plain one was used".format(number, field))
        if similar(row["real"], row["twist"]) > 0.7:
            row["twist"] = fallback["twist"]
            notes.append("chapter {}: the twist was the same as what really happened, so a plain "
                         "one was used".format(number))
        flagged.update(story_flags(row["setup"], row["question"], row["real"], row["twist"]))
        chapters.append(row)
        previous = last
    return chapters, sorted(flagged)


# Words that make a reader think of a theme, besides the theme's own stem: a chapter "carries" the
# theme when its question or options use one.
THEME_WORDS = {
    "courage": ("brave", "bold", "afraid", "fear", "risk", "dare", "speak up", "stand", "step forward", "try"),
    "kindness": ("kind", "care", "help", "gentle", "generous", "thoughtful"),
    "empathy": ("listen", "understand", "feel", "notice", "care", "hear", "alone", "lonely"),
    "forgiveness": ("forgiv", "let go", "grudge", "debt", "apolog", "mercy", "amends", "hold on"),
    "gratitude": ("grateful", "thank", "appreciat"),
    "perseverance": ("keep going", "again", "persist", "stay with", "push on", "give up"),
    "humility": ("humble", "admit", "ask for help", "learn", "pride"),
    "hope": ("believe", "trust", "possible", "chance"),
    "teamwork": ("team", "together", "share", "support"),
    "generosity": ("give", "share", "generous"),
    "mentorship": ("teach", "guide", "coach", "learn"),
    "love": ("care", "family", "together"),
    "health": ("rest", "habit", "body", "healthy"),
    "motivation": ("drive", "goal", "inspire", "start"),
}


def theme_problems(chapters, theme):
    """Notes (not failures) when fewer than two chapters put the theme to the reader."""
    theme = str(theme or "").lower().strip()
    if not theme:
        return []
    words = (theme[:5],) + THEME_WORDS.get(theme.split()[0], ())
    missing = [n for n, c in enumerate(chapters, 1)
               if not any(w in " ".join([c["question"], c["real"], c["twist"]]).lower() for w in words)]
    if len(chapters) - len(missing) >= 2:
        return []
    return ["chapters {} do not put the theme ({}) to the reader: frame the question and both options "
            "as different answers to what {} asks of a person at that moment, in words that bring it "
            "to mind".format(and_join(missing), theme, theme)]


def chapterise(llm, story, sentences, first_end, notes=None):
    """Azure's four chapters for the story: (chapters, errors, flagged). Rounds that quote the
    problems back. A chapter set that is sound but weak on the theme is sent back once; if the
    second answer is worse, the first is used.

    A week's story is not lost to the wording of Azure's answer: when the problems are still there
    after a second round, the answer is mended in code (repair_chapters) and what was changed is
    added to `notes`. Only when Azure gave nothing usable at all are there no chapters."""
    notes = notes if notes is not None else []
    fixes, errors, spare, kept = [], [], None, None
    for attempt in range(CHAPTER_ATTEMPTS):
        reply = llm.chat(CHAPTER_SYSTEM, chapter_prompt(story, sentences, first_end, fixes),
                         max_tokens=1600, temperature=0.5)
        if not reply:
            errors = ["Azure gave no answer"]
            continue
        try:
            answer = json.loads(reply)
        except ValueError:
            fixes, errors = ["the answer was not valid JSON"], ["the answer was not valid JSON"]
            continue
        chapters, errors, flagged = parse_chapters(answer, sentences, first_end)
        if chapters:
            soft = theme_problems(chapters, story["theme"])
            if soft and attempt == 0:
                spare, fixes = (chapters, [], flagged), soft
                continue
            return chapters, [], flagged
        fixes = errors
        if isinstance(answer, dict) and isinstance(answer.get("chapters"), list) \
                and len(answer["chapters"]) >= CHAPTERS:
            kept = answer
            if attempt >= 1:
                break           # told once what was wrong and still not right: mend it instead
    if spare:
        return spare
    if kept is not None:
        chapters, flagged = repair_chapters(kept, sentences, first_end, story.get("main"), notes)
        if chapters:
            return chapters, [], flagged
    return [], errors, []


# Which rules cut a pack's chapters: 2 = long passages, theme-driven choices (never "Why ...?"). A story
# prepared before that is posted as it was cut, and the post says so.
PACK_VERSION = 2


def make_pack(story, chapters):
    return {"v": PACK_VERSION, "title": story["title"], "author": story["author"], "kb": story["kb"],
            "theme": story["theme"], "why": story["why"], "lesson": story["lesson"],
            "main": story["main"], "adapted": story.get("adapted", False),
            "chapters": [{k: c[k] for k in ("snippet", "setup", "question", "real", "twist")}
                         for c in chapters]}


def pack_ok(pack):
    """Whether what was read back from the table is a pack this step can post."""
    try:
        chapters = pack["chapters"]
        return (len(chapters) == CHAPTERS and pack["title"] and pack["kb"]
                and all(c[k] for c in chapters
                        for k in ("snippet", "setup", "question", "real", "twist")))
    except (KeyError, TypeError):
        return False


def chapters_preview(pack):
    """The four chapters as plain text, for a person to read before Monday."""
    out = []
    for number, chapter in enumerate(pack["chapters"], 1):
        out.append("Chapter {}\n  passage:  {}\n  asks:     {}\n  {}:  {}\n  {}:  {}".format(
            number, chapter["snippet"], chapter["question"], LABEL_REAL, chapter["real"],
            LABEL_TWIST, chapter["twist"]))
    return "\n\n".join(out)


# --------------------------------------------------------------------------
# Picks -> what the story is
# --------------------------------------------------------------------------

def pick_from_row(row, order=0):
    try:
        chapter = int(row.get("grant_type") or 0)
    except (TypeError, ValueError):
        chapter = 0
    return {"id": row.get("group_id") or "", "name": row.get("name") or "A colleague",
            "choice": row.get("status") or "", "chapter": chapter,
            "ts": row.get("last_processed_ts") or "", "order": order}


def unique_picks(picks):
    """One pick per person: the earliest. A button pressed twice in the same instant can write two
    rows before either is seen, and one person must not count twice."""
    seen, out = set(), []
    for pick in sorted(picks, key=lambda p: (str(p.get("ts") or ""), p.get("order", 0))):
        if pick["id"] and pick["id"] in seen:
            continue
        seen.add(pick["id"])
        out.append(pick)
    return out


def tally_picks(picks):
    """What a chapter's picks decide: the entry the story keeps. The turn with the most picks wins. A tie
    keeps the story as it happened, and so does a chapter nobody picked on."""
    counts = {"real": 0, "divert": 0}
    for pick in picks:
        if pick["choice"] in counts:
            counts[pick["choice"]] += 1
    total = counts["real"] + counts["divert"]
    entry = {"picks": total, "votes": counts}
    if counts["divert"] > counts["real"]:
        entry.update({"choice": "divert", "quiet": False})
    else:
        entry.update({"choice": "real", "quiet": total == 0})
    return entry


def canon_line(pack, chapter, entry):
    """The line the story holds for a settled chapter."""
    chap = pack["chapters"][chapter - 1]
    return chap["twist"] if entry.get("choice") == "divert" else chap["real"]


def on_path(canon, chapter):
    """Whether every chapter before this one went as it happened."""
    return all((canon.get(str(k)) or {}).get("choice", "real") == "real" for k in range(1, chapter))


def recap_for(pack, canon, chapter, last_only=False):
    """The story so far, one short sentence per settled chapter."""
    chapters = [chapter - 1] if last_only else range(1, chapter)
    parts = []
    for k in chapters:
        entry = canon.get(str(k)) or {"choice": "real"}
        parts.append(sentence_end(shorten_words(canon_line(pack, k, entry), RECAP_WORDS)))
    return " ".join(parts)


# --------------------------------------------------------------------------
# Block Kit -- Python owns the structure
# --------------------------------------------------------------------------

def tz_label(offset):
    """PST, UTC-8, UTC+5:30 ... for a clock `offset` seconds east of UTC."""
    if offset in TZ_NAMES:
        return TZ_NAMES[offset]
    sign, minutes = ("-" if offset < 0 else "+"), abs(offset) // 60
    return "UTC{}{}{}".format(sign, minutes // 60, ":{:02d}".format(minutes % 60) if minutes % 60 else "")


def picks_deadline(now, close_time=DEFAULT_CLOSE_TIME, offset=DEFAULT_CLOSE_TZ):
    """When a chapter posted at `now` (aware, UTC) stops taking picks: {"at": unix seconds, "label":
    "Tue 12:00 PM PST"}, the next close_time on the clock `offset` seconds east of UTC that is at least
    MIN_OPEN_HOURS away. A close_time that is not HH:MM is 12:00."""
    found = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*$", str(close_time or ""))
    hour, minute = (int(found.group(1)), int(found.group(2) or 0)) if found else (12, 0)
    if hour > 23 or minute > 59:
        hour, minute = 12, 0
    zone = timezone(timedelta(seconds=offset))
    target = now.astimezone(zone).replace(hour=hour, minute=minute, second=0, microsecond=0)
    while target <= now + timedelta(hours=MIN_OPEN_HOURS):
        target += timedelta(days=1)
    label = "{} {} {}".format(target.strftime("%a"), target.strftime("%I:%M %p").lstrip("0"),
                              tz_label(offset))
    return {"at": int(target.timestamp()), "label": label}


def close_token(closes):
    """The closing time as Slack shows it: in each reader's own time zone (the label is for a client
    that cannot)."""
    return "<!date^{}^{{date_short_pretty}} at {{time}}|{}>".format(closes["at"], closes["label"])


def status_bits(picks, closes, chapter):
    """The line under a chapter's buttons: how many picks are in, and when they close."""
    count = ("{} *{}* pick{} in so far".format(ICON_COUNT, picks, "" if picks == 1 else "s") if picks
             else "{} No picks yet, be the first".format(ICON_COUNT))
    close = ("{} Picks close {}".format(ICON_CLOSE, close_token(closes)) if closes else
             "{} Picks close with tomorrow's {}".format(ICON_CLOSE, "story" if chapter == CHAPTERS
                                                       else "chapter"))
    return [count, close]


def pick_value(week, chapter, choice, test=False):
    return "{}|pick|{}|{}|{}".format("storyt" if test else "story", week or "test", chapter, choice)


def parse_value(value):
    """What a button carries back, or None if it is not one of this step's:
    story|pick|<week>|<chapter>|<real|divert>  (storyt| for a test post)."""
    cells = str(value or "").strip().split("|")
    if len(cells) < 5 or cells[0] not in ("story", "storyt") or cells[1] != "pick":
        return None
    try:
        chapter = int(cells[3])
    except ValueError:
        return None
    if cells[4] not in ("real", "divert") or not 1 <= chapter <= CHAPTERS:
        return None
    return {"test": cells[0] == "storyt", "week": cells[2], "chapter": chapter, "choice": cells[4]}


def render(items, wrap):
    """The post's one text block from (kind, text) lines: a quote line gets its own > on every
    cut, as in health_post.py."""
    out = []
    for kind, text in items:
        if kind == "quote":
            out.extend("> " + part for part in (wrap_line(text, wrap - 3) if wrap else [text]))
        else:
            out.extend(wrap_line(text, wrap) if wrap else [text])
    return "\n".join(out)


def title_line(pack):
    # Only the title: readers do not know the author or the collection, so neither is shown
    # (both are kept in the table).
    return "*{}*".format(escape(pack["title"]))


def eyebrow(pack, label, seconds):
    return SEP.join(["{} *{}*".format(ICON_SERIES, SERIES_NAME.upper()),
                     "{} {}".format(theme_emoji(pack["theme"]), escape(pack["theme"].upper())),
                     label, "~{} sec read".format(seconds)])


def real_slot(week, chapter):
    """Which plot twist (1 or 2) is what the story really did. It moves about from chapter to
    chapter and week to week, so nobody can learn that it is always the first."""
    digits = re.sub(r"\D", "", str(week))
    return 1 + ((int(digits) if digits else 0) + 3 * int(chapter)) % 2


def twist_choices(week, chapter):
    """{1: "real" or "divert", 2: ...}: what each numbered plot twist stands for."""
    real = real_slot(week, chapter)
    return {real: "real", 3 - real: "divert"}


def choice_label(choice, week, chapter):
    """What a person sees for their choice: "Plot twist 2"."""
    for number, kind in twist_choices(week, chapter).items():
        if kind == choice:
            return TWIST_LABEL.format(n=number)
    return ""


def closed_note(entry, week="", chapter=1):
    """The footer of a chapter that has been settled. It never says which twist was the real one:
    that is for Friday."""
    picks = int(entry.get("picks") or 0)
    count = "{} pick{}".format(picks, "" if picks == 1 else "s")
    if entry.get("missed"):
        return "Closed" + SEP + "this chapter was not posted, so the story carried on"
    if entry.get("quiet"):
        return "Closed" + SEP + "nobody picked, so the story carried on"
    return "{} Closed{}the team chose {}{}{}".format(
        ICON_PICKS, SEP, choice_label(entry["choice"], week, chapter), SEP, count)


def chapter_view(pack, canon, chapter, week, picks=0, closed=None, test=False,
                 wrap=WRAP_CHARS, banner="", passage_words=DEFAULT_PASSAGE_WORDS, closes=None, bridge=""):
    """One chapter's whole message: {"blocks", "text", "words", "seconds"}.

    The story is the only large text. The small text around it (where the story stands, the
    question, the two plot twists, the goal) sits in context blocks, which Slack sets smaller
    and greyer, with a block's gap above and below."""
    chap = pack["chapters"][chapter - 1]
    small = int(wrap * CONTEXT_WRAP) if wrap else 0
    story = [("plain", title_line(pack)), ("plain", "")]
    shown = 0
    if on_path(canon, chapter):
        passage = fit_passage(chap["snippet"], passage_words, keep_opening=chapter == 1)
        shown = count_words(passage)
        story.append(("quote", escape(passage)))
        so_far = recap_for(pack, canon, chapter, True) if chapter > 1 else ""
    else:
        # The story has left the original path, so the original passage no longer follows. The model's bridge
        # (the team's choices stitched into the story) stands in for it; without one, the one-line set-up.
        story.append(("plain", "_{}_".format(escape(bridge or chap["setup"]))))
        so_far = recap_for(pack, canon, chapter)
    twists = twist_choices(week, chapter)
    said = {"real": chap["real"], "divert": chap["twist"]}
    plot = [("plain", "*{}*".format(escape(chap["question"])))]
    for number in (1, 2):
        plot.append(("plain", "*{}* \u2014 {}".format(TWIST_LABEL.format(n=number),
                                                    escape(said[twists[number]]))))
    story_text = render(story, wrap)
    plot_text = render(plot, small)
    so_far_text = render([("plain", "_So far:_ " + escape(so_far))], small) if so_far else ""
    words = count_words(" ".join([story_text, plot_text, so_far_text]))
    seconds = read_seconds(words)

    blocks = []
    top = banner_block(banner)
    if top:
        blocks.append(top)
    blocks.append(context(eyebrow(pack, "Chapter {} of {}".format(chapter, CHAPTERS), seconds)))
    if so_far_text:
        blocks.append(context(so_far_text))
    blocks.append(section(story_text))
    blocks.append(context(plot_text))
    if closed:
        blocks.append(context(closed_note(closed, week, chapter)))
    else:
        blocks.append({"type": "actions", "block_id": ACTION_BLOCK, "elements": [
            button(TWIST_LABEL.format(n=1), ACTION_PREFIX + "1",
                   pick_value(week, chapter, twists[1], test)),
            button(TWIST_LABEL.format(n=2), ACTION_PREFIX + "2",
                   pick_value(week, chapter, twists[2], test))]})
        blocks.append(context(SEP.join(["{} {}".format(ICON_GOAL, GOAL_TEXT),
                                        "{} One pick each, on every chapter".format(ICON_PICKS)])))
        blocks.append(context(SEP.join(status_bits(picks, closes, chapter))))
    notification = "{} \u2014 Chapter {}: {}".format(pack["title"], chapter, plain(chap["question"]))
    return {"blocks": blocks, "text": notification, "words": words, "seconds": seconds,
            "shown": shown}


BRIDGE_SYSTEM = (
    "You carry on a true workplace story that a team is writing together, in a Slack channel read by "
    "colleagues across companies and countries. The story has taken a different turn from what really "
    "happened, because of what the team chose. Those choices are now what happened.\n\n"
    "Write a short bridge of two or three sentences, at most 70 words in all, in the past tense and in "
    "plain, warm, global English, that carries the story from the team's choices to the moment of the "
    "next decision. Rules:\n"
    "- Treat every choice as true: it is what happened now. Never undo it or explain it away.\n"
    "- Never bring back events that the team's choices replaced. You are given the original story at this "
    "moment only for its people and setting.\n"
    "- Show the natural consequence of the choices, so that the next decision has real room to turn the "
    "story back on course or somewhere new. That is the point of the game.\n"
    "- Use only the people and places of the story. Invent no new named person, place or number.\n"
    "- End at the moment the next decision is asked, without answering it.\n"
    "- Do not mention the team, a game, chapters, choices, picks or votes. No emoji, no markdown, no quotation "
    "marks around the whole bridge.\n"
    "- Nothing sexual, violent, political, religious or unkind about any real person.\n"
    'Return JSON only: {"bridge": "..."}')


def bridge_prompt(pack, canon, chapter):
    """What the model is given to stitch the team's choices into the story up to `chapter`."""
    chap = pack["chapters"][chapter - 1]
    lines = ["Title: {}".format(pack["title"]), "Theme: {}".format(pack["theme"]),
             "Main character: {}".format(pack.get("main") or "not given"), "",
             "The original story at this moment (for its people and setting only; do not bring back events "
             "the choices replaced):", chap["snippet"], "",
             "What the team chose, in order, and is now what happened:"]
    for k in range(1, chapter):
        entry = canon.get(str(k)) or {"choice": "real"}
        lines.append("{}. {}".format(k, canon_line(pack, k, entry)))
    lines += ["", "The next decision, to lead up to and not answer: {}".format(chap["question"])]
    return "\n".join(lines)


def make_bridge(llm, pack, canon, chapter, warnings, attempts=2):
    """Two or three sentences that stitch the team's choices into the story up to `chapter`, or "" when
    there is no model or none of its `attempts` passes the checks (plain_bridge is used then, so a chapter
    on a different turn always has a bridge)."""
    if llm is None:
        return ""
    for _ in range(attempts):
        reply = llm.chat(BRIDGE_SYSTEM, bridge_prompt(pack, canon, chapter), max_tokens=300, temperature=0.7)
        try:
            bridge = tidy(str(json.loads(reply or "{}").get("bridge") or ""))
        except (ValueError, AttributeError):
            bridge = ""
        bridge = bridge.strip("\"\u201c\u201d ")
        words = count_words(bridge)
        if (12 <= words <= 110 and not re.search(r"<[@!#]|@channel|@here|https?://", bridge)
                and not story_flags(bridge)):
            return clip(sentence_end(bridge), 600)
    warnings.append("chapter {}: the bridge the model wrote failed its checks".format(chapter))
    return ""


def plain_bridge(pack, canon, chapter):
    """A bridge built without a model, so the story always carries on: what the team last chose, then this
    chapter's set-up (which leads to its decision). Always something, whatever was chosen."""
    chap = pack["chapters"][chapter - 1]
    last = canon.get(str(chapter - 1)) or {"choice": "real"}
    said = clip(canon_line(pack, chapter - 1, last), 300).strip()
    said = said[:1].upper() + said[1:]
    return " ".join(part for part in (sentence_end(said) if said else "", sentence_end(chap["setup"])) if part)


def assembled_story(pack, canon):
    """The team's version with no model: the chosen line of each chapter, a paragraph each."""
    return "\n".join(sentence_end(canon_line(pack, k, canon.get(str(k)) or {"choice": "real"}))
                     for k in range(1, CHAPTERS + 1))


STITCH_SYSTEM = (
    "You write the finished version of a story that a workplace team shaped together during the "
    "week, for a Slack channel read by colleagues across companies and countries, senior people "
    "included.\n\n"
    "You are given the title, the theme and the four turning points as the team chose them, in "
    "order. Keep the events of each.\n\n"
    "Write the story in four short paragraphs, one per turning point, in the past tense, in "
    "plain, warm, global English, 150 words at most in all. Connect the turning points so it reads "
    "as one story, adding only the smallest bridging words and never a new event, person, name, "
    "place or number. Do not mention the team, a game, chapters, choices or votes. No title, no "
    "emoji, no markdown, no moral at the end. Nothing sexual, violent, political, religious or "
    'unkind about any real person. Return JSON only: {"story": "paragraph one\\n\\nparagraph two'
    '\\n\\nparagraph three\\n\\nparagraph four"}')


def stitch_story(llm, pack, canon, warnings):
    """The team's version in prose from one Azure call, or "" if the call or its checks fail."""
    lines = ["Title: {}".format(pack["title"]), "Theme: {}".format(pack["theme"]),
             "Main character: {}".format(pack.get("main") or "not given"), "",
             "The four turning points, in order:"]
    for k in range(1, CHAPTERS + 1):
        entry = canon.get(str(k)) or {"choice": "real"}
        lines.append("{}. {}".format(k, canon_line(pack, k, entry)))
    reply = llm.chat(STITCH_SYSTEM, "\n".join(lines), max_tokens=500, temperature=0.6)
    try:
        story = str(json.loads(reply or "{}").get("story") or "")
    except (ValueError, AttributeError):
        story = ""
    story = "\n".join(p.strip() for p in re.split(r"\n\s*\n|\n", story.replace("\r", "")) if p.strip())
    words = count_words(story)
    if (not 40 <= words <= 220 or re.search(r"<[@!#]|@channel|@here|https?://", story)
            or flagged_words(story)):
        warnings.append("the written version failed its checks; the chosen lines are used instead")
        return ""
    return tidy_paragraphs(story)


def tidy_paragraphs(story):
    return "\n".join(sentence_end(tidy(p)) for p in story.split("\n") if tidy(p))


SPLIT_SYSTEM = (
    "You write the 'where we split from the real story' lines for the Friday post of a TRUE workplace story "
    "that a team rewrote together during the week, in a Slack channel read by colleagues across companies "
    "and countries.\n\n"
    "For each chapter you are given what really happened and what the team did instead. Write ONE sentence "
    "per chapter, at most 30 words, past tense, saying what really happened and what the team did instead.\n"
    "- Tone: light, warm and a little playful, with gentle wit about how the story swerved. Never at the "
    "expense of any person and never about the real people's hardship.\n"
    "- Plain global English. No emoji, no markdown, no quotation marks, no names that are not in the story, "
    "no mention of a game, votes, picks or chapters.\n"
    'Return JSON only: {"lines": [{"chapter": 1, "line": "..."}]} with one entry for each chapter given.')


def changed_chapters(canon):
    """The chapters the team took away from what really happened, in order."""
    return [k for k in range(1, CHAPTERS + 1) if (canon.get(str(k)) or {}).get("choice", "real") != "real"]


def split_prompt(pack, canon):
    lines = ["Title: {}".format(pack["title"]), "Theme: {}".format(pack["theme"]),
             "Main character: {}".format(pack.get("main") or "not given"), "",
             "The chapters the team changed:"]
    for k in changed_chapters(canon):
        lines.append("Chapter {}: really, {} | the team instead: {}".format(
            k, pack["chapters"][k - 1]["real"], canon_line(pack, k, canon[str(k)])))
    return "\n".join(lines)


def plain_split_line(pack, canon, chapter):
    """A contrast line built without a model: what really happened, then what the team did."""
    entry = canon.get(str(chapter)) or {"choice": "real"}
    return "Really: {}  \u00b7  Ours: {}".format(
        sentence_end(pack["chapters"][chapter - 1]["real"]).rstrip("."),
        sentence_end(canon_line(pack, chapter, entry)))


def split_lines(llm, pack, canon, warnings):
    """{chapter: line} for every chapter the team changed: one playful sentence from the model where it
    passes its checks, otherwise the plain contrast line, so a changed chapter always has one."""
    changed = changed_chapters(canon)
    wrote = {}
    if llm is not None and changed:
        reply = llm.chat(SPLIT_SYSTEM, split_prompt(pack, canon), max_tokens=120 * len(changed) + 100,
                         temperature=0.8)
        try:
            for item in (json.loads(reply or "{}").get("lines") or []):
                number, line = int(item["chapter"]), tidy(str(item["line"])).strip("\"\u201c\u201d ")
                if (number in changed and 6 <= count_words(line) <= 45
                        and not re.search(r"<[@!#]|@channel|@here|https?://", line) and not story_flags(line)):
                    wrote[number] = clip(sentence_end(line), 320)
        except (ValueError, KeyError, TypeError, AttributeError):
            wrote = {}
    out = {}
    for k in changed:
        if k in wrote:
            out[k] = wrote[k]
        else:
            out[k] = plain_split_line(pack, canon, k)
            warnings.append("chapter {}: the contrast line for Friday was {}, so a plain one was used".format(
                k, "not written (no model)" if llm is None else "not usable"))
    return out


def credit_names(names, shown=CREDITS_SHOWN):
    """"A, B and C", or the first few and "N others" when a lot of people took part."""
    names = [escape_name(n) for n in names]
    if len(names) <= shown:
        return and_join(names)
    rest = len(names) - shown
    return "{} and {} other{}".format(", ".join(names[:shown]), rest, "" if rest == 1 else "s")


ENDING_SYSTEM = (
    "You write the real ending of a TRUE workplace story for the Friday post of a Slack channel read by colleagues "
    "across companies and countries. The readers have just read a version of the story that their team rewrote, "
    "so it may not mention people or details that the real ending depends on.\n\n"
    "You are given the true story and the line that says how it really ended. Write the real ending as a short, "
    "self-contained passage of two or three sentences, at most 50 words. First say, in a few words, who the people "
    "in it are and what their situation was (for example who 'the children' are), using only what the story says, "
    "then how it really ended, so that someone who has not read the real story understands every word.\n"
    "- Plain, warm and sincere: this is the true ending, so no jokes and no irony.\n"
    "- Use only facts in the story. Invent no person, name, place or number.\n"
    "- Do not mention a team, a game, a rewritten version, chapters or picks. No emoji, no markdown.\n"
    'Return JSON only: {"ending": "..."}')


def real_ending(llm, pack, story_text, warnings):
    """How the story really ended, as a short passage that carries its own context (who 'the children' are), so the
    real ending still connects to a team version that never mentioned them. The model writes it from the full story;
    its own plain line (the last chapter's real) is used when there is no model or what it writes fails its checks."""
    plain_line = pack["chapters"][-1]["real"]
    if llm is None:
        return plain_line
    story = str(story_text or "").strip() or " ".join(c["snippet"] for c in pack["chapters"])
    reply = llm.chat(ENDING_SYSTEM, "Title: {}\nTheme: {}\nMain character: {}\n\nThe true story:\n{}\n\n"
                                    "How it really ended: {}".format(pack["title"], pack["theme"],
                                                                     pack.get("main") or "not given", story, plain_line),
                     max_tokens=220, temperature=0.4)
    try:
        ending = tidy(str(json.loads(reply or "{}").get("ending") or "")).strip("\"\u201c\u201d ")
    except (ValueError, AttributeError):
        ending = ""
    if (15 <= count_words(ending) <= 70 and not re.search(r"<[@!#]|@channel|@here|https?://", ending)
            and not flagged_words(ending)):
        return clip(sentence_end(ending), 600)
    warnings.append("the real ending the model wrote failed its checks, so the plain line is used")
    return plain_line


def split_blocks(canon, split, wrap=WRAP_CHARS):
    """The "where we split from the real story" lines, for the thread under the Friday post: a score and one line
    for each chapter the team changed. `split` is {chapter: line} (split_lines). They are kept off the post itself,
    which has the team's story and the real ending; whoever wants the detail opens the thread."""
    matched = CHAPTERS - len(changed_chapters(canon))
    score = ("we matched the real story in {} of {} chapters".format(matched, CHAPTERS) if matched
             else "none matched: this one is all ours")
    items = [("plain", "*Where we split from the real story*{}{}".format(SEP, score))]
    items += [("plain", "*Ch {}* \u2014 {}".format(k, escape(split[k]))) for k in sorted(split)]
    return [section(render(items, wrap))]


def publish_view(pack, canon, shapers, narrative, wrap=WRAP_CHARS, banner="", split=None, ending=""):
    """The Friday message: the team's version, who shaped it, and how it really ended. When there is a "where we
    split" thread under it (`split`, see split_blocks) a line says so."""
    changed = [k for k in range(1, CHAPTERS + 1)
               if (canon.get(str(k)) or {}).get("choice", "real") != "real"]
    kept = [k for k in range(1, CHAPTERS + 1) if k not in changed]
    items = [("plain", "*{} \u2014 the team's version*".format(escape(pack["title"])))]
    items += [("plain", escape(p)) for p in narrative.split("\n") if p.strip()]
    text = render(items, wrap)
    real = [("quote", "*How it really ended:* " + escape(ending or pack["chapters"][-1]["real"]))]
    if pack.get("lesson"):
        real.append(("quote", "_{}_".format(escape(pack["lesson"]))))
    real_text = render(real, wrap)
    seconds = read_seconds(count_words(text + " " + real_text))

    blocks = []
    top = banner_block(banner)
    if top:
        blocks.append(top)
    blocks.append(context(eyebrow(pack, "The story we built", seconds)))
    blocks.append(section(text))
    if changed:
        shaped = ICON_PICKS + " *Shaped by* {}".format(credit_names(shapers)) if shapers else ""
        blocks.append(context(SEP.join(b for b in [
            shaped,
            "changed in chapter{} {}".format("" if len(changed) == 1 else "s", and_join(changed)),
            ("as it happened in {}".format(and_join(kept)) if kept else "")] if b)))
    else:
        blocks.append(context("Nobody stepped in this week, so the story stayed as it happened."
                              if not shapers else
                              "{} *Shaped by* {}{}everyone kept the story as it happened".format(
                                  ICON_PICKS, credit_names(shapers), SEP)))
    blocks.append(section(real_text))
    closing = "{} Next week's story arrives on Monday".format(ICON_GOAL)
    if split:
        closing = "{} Where we split from the real story is in the thread{}{}".format(ICON_THREAD, SEP, closing)
    blocks.append(context(closing))
    return {"blocks": blocks, "text": "{} \u2014 the story we built".format(pack["title"]),
            "words": count_words(text), "seconds": seconds}


def announce_view(pack, week, when, wrap=WRAP_CHARS, banner="", lines=None):
    """The Sunday post: which story, why it is worth the week, how the week goes. No chapter text,
    no buttons -- Monday's post is the first thing to press. `lines` (hook, teaser, mon_thu, pick,
    fri, job) are the week's own wording, written for this story; whatever is missing falls back
    to the standard wording, so the layout is the same either way."""
    lines = lines or {}
    digits = str(week).replace("-", "")
    turn = int(digits) if digits.isdigit() else 0
    hook = lines.get("hook") or ANNOUNCE_HOOKS[turn % len(ANNOUNCE_HOOKS)].format(
        theme=str(pack.get("theme") or "life").lower())
    teaser = lines.get("teaser") or pack.get("why")
    items = [("plain", title_line(pack)), ("plain", escape(hook))]
    if teaser:
        items.append(("plain", "{} _{}_".format(ICON_WHY, escape(teaser))))
    for number, (label, key) in enumerate(zip(ANNOUNCE_STEP_LABELS, ANNOUNCE_STEP_KEYS)):
        said = lines.get(key)
        items.append(("plain", "\u2022 {} {}".format(label, escape(said)) if said
                      else ANNOUNCE_STEPS[number]))
    items.append(("plain", "{} *Our job:* {}".format(ICON_GOAL, escape(lines.get("job") or GOAL_TEXT))))
    text = render(items, wrap)
    seconds = read_seconds(count_words(text))
    blocks = []
    top = banner_block(banner)
    if top:
        blocks.append(top)
    blocks.append(context(eyebrow(pack, ANNOUNCE_LABEL.format(when=when), seconds)))
    blocks.append(section(text))
    blocks.append(context("{} Chapter 1 arrives {}".format(ICON_SERIES, when)))
    return {"blocks": blocks, "text": "New story this week: {}".format(pack["title"]),
            "words": count_words(text), "seconds": seconds}


# --------------------------------------------------------------------------
# EDGES -- everything below talks to the network
# --------------------------------------------------------------------------

def _send_json(url, headers, payload, method="POST", timeout=HTTP_TIMEOUT):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {} {}: {}".format(error.code, method, url.split("/")[2], detail)
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


def _get_json(url, headers, timeout=HTTP_TIMEOUT):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


def _slack(token, url, payload):
    """(body, error) for one Slack call; Slack's own refusal is an error too."""
    headers = {"Authorization": "Bearer {}".format(token),
               "Content-Type": "application/json; charset=utf-8"}
    body, error = _send_json(url, headers, payload)
    if error:
        return None, error
    if not body.get("ok"):
        return body, "slack {}: {}".format(url.rsplit("/", 1)[1], body.get("error"))
    return body, None


def slack_post(token, channel, text, blocks):
    """(ts, error)."""
    body, error = _slack(token, SLACK_POST_URL, {
        "channel": channel, "text": text, "blocks": blocks,
        "unfurl_links": False, "unfurl_media": False})
    return ((body or {}).get("ts") or "") if not error else "", error


def slack_update(token, channel, ts, text, blocks):
    _, error = _slack(token, SLACK_UPDATE_URL, {
        "channel": channel, "ts": str(ts), "text": text, "blocks": blocks})
    return error


def slack_delete(token, channel, ts):
    _, error = _slack(token, SLACK_DELETE_URL, {"channel": channel, "ts": str(ts)})
    return error


def slack_ephemeral(token, channel, user, text):
    """A note only `user` sees. Returns the error, if any."""
    _, error = _slack(token, SLACK_EPHEMERAL_URL, {"channel": channel, "user": user, "text": text})
    return error


def slack_user_name(token, user_id):
    """The person's real name, or "" when Slack will not say."""
    body, error = _get_json("{}?user={}".format(SLACK_USER_URL, urllib.parse.quote(user_id)),
                            {"Authorization": "Bearer {}".format(token)})
    if error or not (body or {}).get("ok"):
        return ""
    user = body.get("user") or {}
    profile = user.get("profile") or {}
    return (profile.get("real_name") or user.get("real_name") or profile.get("display_name")
            or user.get("name") or "").strip()


# Returned by Table.story when the read failed, so a failed lookup is never mistaken for "no story".
LOOKUP_FAILED = object()


class Table(object):
    """The data table, by column name rather than UUID."""

    def __init__(self, token):
        self.token = token
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.errors = []
        self.written = 0
        self.read_failed = False

    @staticmethod
    def _decode(body):
        """The query endpoint returns schema and data as arrays-of-arrays."""
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        return [dict(zip(columns, [v for group in row for v in group]))
                for row in body.get("data", [])]

    def query(self, where, limit=200, every=False):
        """`every` follows continuation tokens to the last page. A failed page fails the whole
        read (read_failed): half a week of picks would settle the wrong chapter."""
        payload = {"where": where, "limit": limit}
        self.read_failed = False
        rows = []
        for _page in range(QUERY_MAX_PAGES):
            body, error = _send_json(TABLE_QUERY_URL, self.headers, payload)
            if error:
                self.errors.append("table.query " + error)
                self.read_failed = True
                return []
            rows.extend(self._decode(body))
            token = body.get("continuation_token") if every else None
            if not token:
                break
            payload["continuation_token"] = token
        return rows

    def story(self, week):
        """The week's story_week row, None when there is none, LOOKUP_FAILED when the read failed."""
        rows = self.query({"$and": [{"row_type": {"$eq": STORY_ROW}},
                                    {"week_key": {"$eq": week}}]}, limit=5)
        if self.read_failed:
            return LOOKUP_FAILED
        return rows[0] if rows else None

    def stories(self, status=None):
        """Every story_week row (or those of one status), None when the read failed."""
        where = {"row_type": {"$eq": STORY_ROW}}
        if status:
            where = {"$and": [where, {"status": {"$eq": status}}]}
        rows = self.query(where, limit=200, every=True)
        return None if self.read_failed else rows

    def picks(self, week, chapter=None, user=None):
        """The pick rows of a week (a chapter, a person), None when the read failed."""
        conditions = [{"row_type": {"$eq": PICK_ROW}}, {"week_key": {"$eq": week}}]
        if chapter:
            conditions.append({"grant_type": {"$eq": str(chapter)}})
        if user:
            conditions.append({"group_id": {"$eq": user}})
        rows = self.query({"$and": conditions}, limit=200, every=True)
        return None if self.read_failed else rows

    def _document(self, fields):
        """Field UUIDs are addressed as $uuid; resolved here and nowhere else."""
        document = {}
        for name, value in fields.items():
            uuid = COLUMNS.get(name)
            if uuid is None:
                self.errors.append("write: unknown column " + name)
                continue
            if value is None:
                document["$" + uuid] = None
            else:
                # string and date columns both travel as text
                document["$" + uuid] = value if isinstance(value, str) else str(value)
        return document

    def create(self, fields):
        body, error = _send_json(TABLE_RECORDS_URL, self.headers,
                                 {"document": self._document(fields)}, "POST")
        if error:
            self.errors.append("table.create " + error)
            return False
        self.written += 1
        return True

    def update(self, record_id, fields):
        if not record_id:
            self.errors.append("table.update called without a $record_id")
            return False
        body, error = _send_json(TABLE_RECORD_URL.format(record_id), self.headers,
                                 {"document": self._document(fields)}, "PUT")
        if error:
            self.errors.append("table.update " + error)
            return False
        self.written += 1
        return True

    def write(self, row, fields):
        """Create when there is no row yet, otherwise update in place."""
        return self.update(row.get("$record_id"), fields) if row else self.create(fields)


class Azure(object):
    """Never raises; a failure is noted and the caller falls back."""

    def __init__(self, api_key, url=None):
        self.url = url or AZURE_URL
        self.headers = {"api-key": api_key, "Content-Type": "application/json"}
        self.calls = 0
        self.errors = []

    def chat(self, system, user, max_tokens=700, temperature=0.4):
        payload = {"messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                   "temperature": temperature, "max_tokens": max_tokens,
                   "response_format": {"type": "json_object"}}
        body, error = _send_json(self.url, self.headers, payload)
        self.calls += 1
        if error:
            self.errors.append("azure " + error)
            return None
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            self.errors.append("azure: unexpected response shape")
            return None


# --------------------------------------------------------------------------
# The sample story: used to look at a post before there is a real one, and by the tests. Written
# for this file; it is not from any collection.
# --------------------------------------------------------------------------

SAMPLE_STORY = (
    "Priya had been at the company for eleven days when she noticed that the man at the next desk "
    "never ate lunch. Every day at noon he put on his headphones and worked straight through. She "
    "told herself it was none of her business. On day twelve she made two cups of tea and set one "
    "on his desk without a word. He looked at it for a long moment. \"I moved here alone three "
    "weeks ago,\" he said quietly. \"You are the first person who has asked how I am.\" Priya did "
    "not offer advice. She pulled up a chair and listened for the rest of her lunch break.\n\n"
    "The next morning there was a note on her monitor that said, \"Thank you for asking without "
    "asking.\" A week later he mentioned that his team was short-handed before a big launch. Priya "
    "knew nothing about the project, but she offered to proofread the release notes in the "
    "evenings. Nobody had asked her to. Months later, Priya was trying to be heard in a crowded "
    "planning meeting. Her idea kept being talked over.\n\n"
    "The man she had once brought tea to waited for a pause. \"Before we move on,\" he said, \"I "
    "would like to hear Priya's idea.\" The room went quiet, and then it listened. Afterwards he "
    "stopped at her desk and said only one thing. \"Tea is on me tomorrow.\"")

SAMPLE_CHAPTERS = {"chapters": [
    {"setup": "A new hire notices that a colleague skips lunch every day and works alone with his "
              "headphones on.",
     "question": "What does Priya do next?",
     "real": "She makes two cups of tea and sets one on his desk without a word.",
     "twist": "She leaves him a friendly note and keeps her distance for now."},
    {"from": 4, "to": 6,
     "setup": "A quiet colleague tells a new hire he has moved to the city alone.",
     "question": "How does Priya respond?",
     "real": "She offers no advice, pulls up a chair and listens for the rest of her break.",
     "twist": "She suggests a few places and clubs where he could meet people."},
    {"from": 10, "to": 14,
     "setup": "Months on, a newer colleague's idea keeps being talked over in a planning meeting.",
     "question": "What does he do when her idea is talked over?",
     "real": "He waits for a pause and asks the room to hear her idea.",
     "twist": "He sends her a message afterwards telling her the idea was a good one."},
    {"from": 15, "to": 16,
     "setup": "A colleague has just asked the room to hear a newer teammate's idea.",
     "question": "How does the story end?",
     "real": "The room listens, and afterwards he tells her the tea is on him tomorrow.",
     "twist": "He invites the whole team to lunch so everyone's ideas are heard."}]}


def sample_pack():
    """The sample story cut into chapters by the same code that cuts a real one."""
    sentences = split_sentences(SAMPLE_STORY)
    story = {"title": "The Window Seat", "kb": "Sample story collection", "author": "",
             "theme": "empathy", "why": "It shows how one small question, asked at the right "
             "moment, changed a colleague's whole week.", "main": "Priya, a new hire",
             "lesson": "Noticing someone is often the kindest thing you can do at work."}
    chapters, errors, _flagged = parse_chapters(SAMPLE_CHAPTERS, sentences, first_passage(sentences, 25, 40))
    assert not errors, errors
    return make_pack(story, chapters)


# --------------------------------------------------------------------------
# Workflows
# --------------------------------------------------------------------------

def _flag(value):
    """A recipe switch that is off unless it says yes."""
    return str(value or "").strip().lower() in ("yes", "y", "true", "1", "on")


def _int(value, default, low, high):
    try:
        return min(high, max(low, int(float(str(value).strip()))))
    except (TypeError, ValueError):
        return default


def picks_cap_input(input):
    """picks_per_week: the most chapters one person may pick on in a week, 1 to CHAPTERS-1. Blank, 0 or
    CHAPTERS or more = no limit (one pick on every chapter)."""
    cap = _int(input.get("picks_per_week"), DEFAULT_PICKS_CAP, 0, CHAPTERS)
    return cap if 1 <= cap < CHAPTERS else 0


def load_json(value):
    """A dict from a dict or a JSON string, {} when it is neither."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, (str, bytes)):
        return {}
    try:
        out = json.loads(value) if str(value or "").strip() else {}
        if isinstance(out, str) and out.strip()[:1] in ("{", "["):
            out = json.loads(out)               # JSON that was turned into JSON again (.to_json on a string)
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def new_state(picks_cap=DEFAULT_PICKS_CAP):
    # `look` is how the chapters were drawn (banner, wrap). The click and box steps redraw a
    # message with the pick count, and must draw it as it was, without being given the inputs.
    return {"picks_cap": picks_cap, "posts": {}, "settled": [], "canon": {},
            "published": "", "look": {}, "closes": {}, "bridges": {}}


def load_row(row):
    """(pack, state) from a story_week row; (None, None) when its content is not usable."""
    doc = load_json((row or {}).get("content"))
    pack, state = doc.get("pack"), doc.get("state")
    if not isinstance(state, dict):
        state = new_state()
    for key, empty in new_state().items():
        state.setdefault(key, empty)
    state["settled"] = [int(k) for k in state["settled"]]
    return (pack, state) if pack_ok(pack) else (None, None)


def dump_content(pack, state):
    """The column's text."""
    return json.dumps({"pack": pack, "state": state}, ensure_ascii=False, separators=(",", ":"))


class Run(object):
    """What the daily run shares between its steps."""

    def __init__(self, table, llm, token, channel, result, today, wrap, banner, force,
                 passage=DEFAULT_PASSAGE_WORDS):
        self.table, self.llm, self.token, self.channel = table, llm, token, channel
        self.result, self.today, self.wrap, self.banner, self.force = result, today, wrap, banner, force
        self.passage = passage
        self.closes = None          # when this run's chapter stops taking picks (picks_deadline)
        self.final_banner = banner  # the banner of Friday's story (the daily one unless banner_final is given)

    def warn(self, message):
        self.result["warnings"].append(message)


def save_state(run, row, pack, state, extra=None):
    """Write the story row's content (and `extra` columns). False, with the reason in the
    warnings, when the table refuses: the caller must not go on as if it was kept."""
    fields = {"content": dump_content(pack, state), "updated_at": run.today.isoformat()}
    fields.update(extra or {})
    return run.table.update(row.get("$record_id"), fields)


def settle(run, row, pack, state, upto):
    """Count the picks of every posted chapter before `upto` that is not yet settled, record what
    won, and close each chapter's message. False when the table could not be read or written."""
    week = row.get("week_key") or ""
    fresh, reported = [], len(run.result["settled"])
    for chapter in range(1, upto):
        if chapter in state["settled"]:
            continue
        ts = state["posts"].get(str(chapter))
        if not ts:
            entry = {"choice": "real", "picks": 0, "quiet": True, "missed": True,
                     "votes": {"real": 0, "divert": 0}}
        else:
            rows = run.table.picks(week, chapter)
            if rows is None:
                run.warn("could not read the picks for chapter {}; nothing was settled".format(chapter))
                return False
            entry = tally_picks(unique_picks([pick_from_row(r, i) for i, r in enumerate(rows)]))
        state["canon"][str(chapter)] = entry
        state["settled"].append(chapter)
        fresh.append((chapter, ts, entry))
        run.result["settled"].append({"chapter": chapter, "choice": entry["choice"],
                                      "picks": int(entry["picks"]), "quiet": bool(entry["quiet"])})
    if not fresh:
        return True
    if not save_state(run, row, pack, state):
        del run.result["settled"][reported:]                # none of it was kept
        run.warn("could not save the settled chapters; nothing more was posted")
        return False
    for chapter, ts, entry in fresh:
        if not ts:
            continue
        view = chapter_view(pack, state["canon"], chapter, week, closed=entry,
                            wrap=run.wrap, banner=run.banner, passage_words=run.passage,
                            bridge=(state.get("bridges") or {}).get(str(chapter), ""))
        error = slack_update(run.token, run.channel, ts, view["text"], view["blocks"])
        if error:
            run.warn("could not close chapter {}'s message: {}".format(chapter, error))
    return True


def post_chapter(run, row, pack, state, chapter):
    result, week = run.result, row.get("week_key") or ""
    key = str(chapter)
    if key in state["posts"] and not run.force:
        result["skipped"] = "chapter {} was already posted".format(chapter)
        return
    bridge = ""
    if not on_path(state["canon"], chapter):
        bridge = make_bridge(run.llm, pack, state["canon"], chapter, result["warnings"])
        if not bridge:
            # Whatever was chosen, the story carries on: a bridge is built from the team's last choice and
            # this chapter's set-up.
            bridge = plain_bridge(pack, state["canon"], chapter)
            run.warn("chapter {} follows a different turn from the story and {}, so a plain bridge was built "
                     "from the team's last choice and the chapter's set-up".format(
                         chapter, "there is no azure_api_key to stitch it in" if run.llm is None
                         else "the model's bridge was not usable"))
    view = chapter_view(pack, state["canon"], chapter, week, wrap=run.wrap, banner=run.banner,
                        passage_words=run.passage, closes=run.closes, bridge=bridge)
    blocks = view["blocks"]
    problems = block_problems(blocks)
    if problems:
        run.warn("layout broke Slack's limits: " + "; ".join(problems))
        result["error"] = "the chapter does not fit Slack's limits"
        return
    stored = count_words(pack["chapters"][chapter - 1]["snippet"])
    result["passage_words"], result["passage_shown"] = run.passage, view["shown"]
    if int(pack.get("v") or 1) < PACK_VERSION:
        run.warn("this story's chapters were cut by an older version (short passages, plainer questions); "
                 "the post shows them as they were cut. Run prepare with force = yes to cut them again")
    if view["shown"] and view["shown"] >= stored and stored < PASSAGE_WORDS[0] and stored + 10 < run.passage:
        run.warn("chapter {} holds only {} words of the story, so that is all it can show (passage_words "
                 "{}): the passages are cut when the story is prepared; prepare it again with force = yes "
                 "for longer ones".format(chapter, stored, run.passage))
    ts, error = slack_post(run.token, run.channel, view["text"], blocks)
    if error:
        result["error"] = error
        return
    old = state["posts"].get(key)
    state["posts"][key] = ts
    if run.closes:
        state["closes"][key] = run.closes
    if bridge:
        state["bridges"][key] = bridge
    else:
        state["bridges"].pop(key, None)
    state["look"] = {"banner": run.banner, "wrap": run.wrap, "passage": run.passage}
    if not save_state(run, row, pack, state, {"status": OPEN, "source_ref": ts,
                                              "slack_channel_id": run.channel}):
        slack_delete(run.token, run.channel, ts)
        result["error"] = "the chapter went out but could not be recorded, so it was removed"
        return
    if old:
        slack_delete(run.token, run.channel, old)
    result.update({"posted": True, "message_ts": ts, "text": view["text"],
                   "words": view["words"], "read_seconds": view["seconds"],
                   "blocks_json": json.dumps(blocks, ensure_ascii=False)})


def publish_week(run, row, pack, state):
    """Settle what is left, write the team's version and post it. False when nothing was posted."""
    result, week = run.result, row.get("week_key") or ""
    if state.get("published") and not run.force:
        result["skipped"] = "this week's story is already published"
        return False
    if not settle(run, row, pack, state, PUBLISH_CHAPTER):
        result["error"] = result["error"] or "the week could not be settled, so nothing was published"
        return False
    rows = run.table.picks(week)
    shapers = []
    for pick in (pick_from_row(r, i) for i, r in enumerate(rows or [])):
        if pick["name"] not in shapers:
            shapers.append(pick["name"])
    if rows is None:
        run.warn("could not read who picked, so the credits are left out")
    canon = state["canon"]
    changed = any((canon.get(str(k)) or {}).get("choice") != "real" for k in range(1, CHAPTERS + 1))
    narrative = stitch_story(run.llm, pack, canon, result["warnings"]) if run.llm and changed else ""
    narrative = narrative or assembled_story(pack, canon)
    split = split_lines(run.llm, pack, canon, result["warnings"]) if changed else {}
    ending = real_ending(run.llm, pack, row.get("description"), result["warnings"]) if changed else ""
    view = publish_view(pack, canon, shapers, narrative, run.wrap, run.final_banner, split=split, ending=ending)
    problems = block_problems(view["blocks"])
    if problems:
        run.warn("layout broke Slack's limits: " + "; ".join(problems))
        result["error"] = "the story does not fit Slack's limits"
        return False
    ts, error = slack_post(run.token, run.channel, view["text"], view["blocks"])
    if error:
        result["error"] = error
        return False
    state["published"] = ts
    if not save_state(run, row, pack, state, {"status": DONE, "source_ref": ts}):
        slack_delete(run.token, run.channel, ts)
        result["error"] = "the story went out but could not be recorded, so it was removed"
        return False
    result.update({"posted": True, "published": True, "message_ts": ts, "text": view["text"],
                   "words": view["words"], "read_seconds": view["seconds"],
                   "blocks_json": json.dumps(view["blocks"], ensure_ascii=False)})
    if split:                       # the detail goes in the thread: a failure here never undoes the post
        thread_ts, error = slack_post(run.token, run.channel, "Where we split from the real story",
                                      split_blocks(canon, split, run.wrap), thread_ts=ts)
        if error:
            run.warn("could not post the where-we-split thread: " + error)
        else:
            result["thread_ts"] = thread_ts
    return True


def do_history(input, result, table):
    if not table.token:
        result["error"] = "workato_api_token is required"
        return
    rows = table.stories()
    if rows is None:
        result["error"] = "could not read the stories"
        return
    rows = sorted(rows, key=lambda r: r.get("week_key") or "", reverse=True)[:26]
    result["stories_found"] = len(rows)
    result["recent_stories"] = "\n".join(
        "{} | {} | week of {}".format(r.get("name") or "", r.get("topic_name") or "",
                                      r.get("week_key") or "") for r in rows) or "none yet"
    result["recent_themes"] = ", ".join(
        [t for t in dict.fromkeys(r.get("topic_name") or "" for r in rows) if t][:4])


def do_save(input, result, table, llm):
    testing = _flag(input.get("testing")) or _flag(input.get("skip_post"))
    approve = _flag(input.get("approve"))
    result["testing"] = testing

    def refuse(reasons, retry=True):
        result["problems"] = list(reasons)
        result["retry"], result["retry_reason"] = retry, "; ".join(reasons)
        result["error"] = "the story cannot be used: " + result["retry_reason"]

    story, problems = read_story(input)
    result.update({"story_title": story["title"], "kb_name": story["kb"], "theme": story["theme"],
                   "author": story["author"], "words": count_words(story["text"])})
    if problems:
        return refuse(problems)
    if not testing and not table.token:
        result["error"] = "workato_api_token is required (or set testing to yes)"
        return
    if llm is None:
        result["error"] = "azure_api_key is required: Azure cuts the story into chapters"
        return

    today = local_today(_int(input.get("tz_offset"), DEFAULT_TZ_OFFSET, -86400, 86400),
                        input.get("today"))
    week = str(input.get("week") or "").strip()
    week = (monday_of(local_today(0, week)).isoformat() if week
            else week_for_save(today).isoformat())
    result["week"] = week

    existing, stories = None, None
    if table.token:
        stories = table.stories()
        if stories is None:
            result["error"] = "could not read the stories, so nothing was saved"
            return
        existing = next((r for r in stories if r.get("week_key") == week), None)
        used = [r for r in stories if (r.get("name") or "").strip().lower() == story["title"].lower()
                and r.get("week_key") != week]
        if used and not approve:
            return refuse(["\"{}\" was already used (week of {})".format(
                story["title"], used[0].get("week_key"))])
    else:
        result["warnings"].append("no table token: not checked against earlier stories")
    if existing and existing.get("status") in (OPEN, DONE) and not testing:
        # (a preview writes nothing, so it may look at a week that has started)
        # Its picks are in the table under this week, so a different story must not take the week
        # over: they would count towards it.
        result["error"] = ("the story for the week of {} has already started ({}), so it cannot be "
                           "replaced".format(week, existing.get("status")))
        return

    hits = story_flags(story["title"], story["why"], story["lesson"], story["main"], story["text"])
    if hits and not approve:
        result["flagged"] = hits
        return refuse(["it contains words that do not belong in a global workplace story (violence, religion, abuse and the like): " + ", ".join(hits)])

    sentences = split_sentences(story["text"])
    if len(sentences) < MIN_SENTENCES:
        return refuse(["the story has only {} sentences, too few to cut into four chapters".format(
            len(sentences))])
    first_end = first_passage(sentences)
    repairs = []
    chapters, errors, generated_hits = chapterise(llm, story, sentences, first_end, repairs)
    if not chapters:
        return refuse(["it could not be cut into four chapters: " + "; ".join(errors[:3])])
    if repairs:
        result["warnings"].append("worth a read before Monday: Azure's chapters needed mending: "
                                  + "; ".join(repairs))
    if generated_hits and not approve:
        result["flagged"] = sorted(set(hits) | set(generated_hits))
        return refuse(["its chapters contain words that do not belong in a workplace story: "
                       + ", ".join(generated_hits)])
    result["flagged"] = sorted(set(hits) | set(generated_hits))
    heavy = heavy_words(story["title"], story["why"], story["lesson"], story["text"])
    if heavy:
        # Not a reason to refuse, but a reason for a person to read it before Monday.
        result["warnings"].append("worth a read before Monday: the story mentions " + ", ".join(heavy))
    local = regional_notes(story["text"])
    if local:
        result["warnings"].append("worth a read before Monday: it names money or years ({}), so it "
                                  "may not read as global".format(", ".join(local)))

    pack = make_pack(story, chapters)
    state = new_state(picks_cap_input(input))
    content = dump_content(pack, state)
    if len(content) > COLUMN_CHUNK:
        return refuse(["the chapters are too long to keep ({:,} characters)".format(len(content))])
    result["chapters_preview"] = chapters_preview(pack)
    first = chapter_view(pack, {}, 1, week, wrap=_wrap_input(input, result),
                         banner=banner_pick(input.get("banner_daily"), input.get("banner")))
    result["blocks_json"] = json.dumps(first["blocks"], ensure_ascii=False)
    result["preview_url"] = preview_url(first["blocks"])
    result["status"] = READY

    story_text = story["text"]
    if len(story_text) > MAX_STORY_CHARS:
        story_text = clip(story_text, MAX_STORY_CHARS)
    fields = {"record_key": "{}_{}".format(STORY_ROW, week), "row_type": STORY_ROW, "id": week,
              "name": story["title"], "topic_name": story["theme"], "kb_tag": story["kb"],
              "week_key": week, "status": READY, "description": story_text, "content": content,
              "created_at": today.isoformat(), "updated_at": today.isoformat(),
              "slack_channel_id": str(input.get("channel") or "").strip()}
    if testing:
        result["warnings"].append("testing: nothing was written to the table")
        result["ok"] = True
        return
    if table.write(existing, fields):
        result["saved"] = True
    else:
        result["error"] = "the table refused the story"


def recut_story(input, result, table, llm, row):
    """force = yes: cut a story that is already cut (ready, open or published) again, from the story
    text kept in the table, so a change in how chapters are cut (longer passages, say) reaches a story
    that was prepared before it. A testing aid. A week that has started is restarted first: its
    chapters are about to change, so its picks are set aside and its messages removed."""
    pack, state = load_row(row)
    if not pack:
        result["error"] = "this story is not readable, so it cannot be cut again"
        return
    result["conversation_id"] = row.get("group_id") or ""
    result["genie_name"] = row.get("group_name") or ""
    preview = _flag(input.get("testing")) or _flag(input.get("skip_post"))
    if row.get("status") in (OPEN, DONE) and not preview:
        today = local_today(_int(input.get("tz_offset"), DEFAULT_TZ_OFFSET, -86400, 86400),
                            input.get("today"))
        run = Run(table, llm, str(input.get("slack_bot_token") or "").strip(), result["channel"],
                  result, today, WRAP_CHARS, "", False)
        if not restart_week(run, row, pack, state):
            return
    fields = dict(input)
    fields.update({
        "story_title": pack["title"], "kb_name": pack["kb"], "theme": pack["theme"],
        "story_text": row.get("description") or "", "story_author": pack.get("author") or "",
        "why_it_resonates": pack.get("why") or "", "main_character": pack.get("main") or "",
        "lesson": pack.get("lesson") or "", "week": row.get("week_key") or "",
        "adapted": "yes" if pack.get("adapted") else ""})
    do_save(fields, result, table, llm)
    if preview:
        result["warnings"].append("preview only: the week was not restarted and nothing was written; "
                                  "run again without testing to cut the chapters for real")


def do_prepare(input, result, table, llm, week=""):
    """Cut a story stored by story_store.py (status new) into chapters and make it ready.

    The story is read back from the table, so the genie's values are the ones that were stored,
    and the work is do_save's. `week` names the row; blank = the newest story still new."""
    if not table.token:
        result["error"] = "workato_api_token is required"
        return
    week = week or str(input.get("week") or "").strip()
    forced = _flag(input.get("force"))
    if week:
        row = table.story(monday_of(local_today(0, week)).isoformat())
        if row is LOOKUP_FAILED:
            result["error"] = "could not read the story"
            return
    else:
        rows = table.stories(None if forced else NEW)
        if rows is None:
            result["error"] = "could not read the stories"
            return
        row = max(rows, key=lambda r: r.get("week_key") or "") if rows else None
    if not row or (row.get("status") != NEW and not forced):
        result["skipped"] = "no stored story is waiting to be prepared"
        return
    if row.get("status") != NEW:
        return recut_story(input, result, table, llm, row)
    raw = load_json(row.get("content")).get("raw") or {}
    result["conversation_id"] = row.get("group_id") or ""
    result["genie_name"] = row.get("group_name") or ""
    fields = dict(input)
    fields.update({
        "story_title": row.get("name") or "", "kb_name": row.get("kb_tag") or "",
        "theme": row.get("topic_name") or "", "story_text": row.get("description") or "",
        "story_author": raw.get("author") or "", "why_it_resonates": raw.get("why") or "",
        "main_character": raw.get("main") or "", "lesson": raw.get("lesson") or "",
        "week": row.get("week_key") or "", "adapted": "yes" if raw.get("adapted") else ""})
    # The genie's "why" says how it turns out, so a story stored by story_store.py shows only the
    # spoiler-free teaser Azure wrote (none, if it was stored without cleaning).
    fields["why_it_resonates"] = raw.get("teaser") or ""
    do_save(fields, result, table, llm)


def _wrap_input(input, result):
    asked = str(input.get("wrap_chars") or "").strip()
    if not asked:
        return WRAP_CHARS
    try:
        wrap = int(float(asked))
    except ValueError:
        result["warnings"].append("wrap_chars '{}' is not a number; used {}".format(asked, WRAP_CHARS))
        return WRAP_CHARS
    if wrap != min(WRAP_MAX, max(WRAP_MIN, wrap)):
        result["warnings"].append("wrap_chars {} is outside {}-{}; used {}".format(
            wrap, WRAP_MIN, WRAP_MAX, min(WRAP_MAX, max(WRAP_MIN, wrap))))
    return min(WRAP_MAX, max(WRAP_MIN, wrap))


def preview_pack(table, monday):
    """(pack, where it came from): this week's story, else the latest one, else the sample."""
    if table.token:
        row = table.story(monday.isoformat())
        if row is None or row is LOOKUP_FAILED:
            rows = table.stories() or []
            row = max(rows, key=lambda r: r.get("week_key") or "") if rows else None
        if row and row is not LOOKUP_FAILED:
            pack, _state = load_row(row)
            if pack:
                return pack, "table"
    return sample_pack(), "sample"


def do_announce(input, result, table):
    """The Sunday post about the week's story. Needs a story that is ready (cut into chapters)."""
    token = str(input.get("slack_bot_token") or "").strip()
    channel = result["channel"]
    testing, skip = _flag(input.get("testing")), _flag(input.get("skip_post"))
    force = _flag(input.get("force"))
    result["testing"], result["preview"] = testing, skip
    today = local_today(_int(input.get("tz_offset"), DEFAULT_TZ_OFFSET, -86400, 86400),
                        input.get("today"))
    week = week_for_save(today)
    result["week"] = week.isoformat()
    when = "Monday"                  # the Sunday post: chapter 1 always arrives on Monday
    wrap, banner = _wrap_input(input, result), banner_pick(input.get("banner_announce"), input.get("banner"))
    row = None
    if testing or skip:
        pack, source = preview_pack(table, week)
        if source == "sample":
            result["warnings"].append("no story in the table: the built-in sample story is shown")
    else:
        if not (token and channel):
            result["error"] = "channel and slack_bot_token are required"
            return
        if not table.token:
            result["error"] = "workato_api_token is required"
            return
        row = table.story(week.isoformat())
        if row is LOOKUP_FAILED:
            result["error"] = "could not read this week's story"
            return
        if not row:
            result["skipped"] = "no story is saved for the week of {}".format(week.isoformat())
            return
        if row.get("status") != READY:
            result["skipped"] = ("the story is not ready ({}): it must be cut into chapters first"
                                 if row.get("status") == NEW else
                                 "the story has already started ({})").format(row.get("status"))
            return
        if row.get("scheduled_time") and not force:
            result["skipped"] = "this week's story was already announced"
            return
        pack, _state = load_row(row)
        if not pack:
            result["error"] = "this week's story is not readable; prepare it again"
            return
    result.update({"story_title": pack["title"], "theme": pack["theme"], "kb_name": pack["kb"]})
    view = announce_view(pack, week.isoformat(), when, wrap, banner)
    problems = block_problems(view["blocks"])
    if problems:
        result["error"] = "the post does not fit Slack's limits: " + "; ".join(problems)
        return
    result.update({"text": view["text"], "words": view["words"], "read_seconds": view["seconds"],
                   "blocks_json": json.dumps(view["blocks"], ensure_ascii=False),
                   "preview_url": preview_url(view["blocks"])})
    if skip:
        return
    if not (token and channel):
        result["error"] = "channel and slack_bot_token are required (or set skip_post to yes)"
        return
    ts, error = slack_post(token, channel, view["text"], view["blocks"])
    if error:
        result["error"] = error
        return
    if row and not table.update(row.get("$record_id"), {"scheduled_time": ts,
                                                        "updated_at": today.isoformat()}):
        slack_delete(token, channel, ts)
        result["error"] = "the post went out but could not be recorded, so it was removed"
        return
    result.update({"posted": True, "message_ts": ts})


RESET_PREFIX = "reset_"


def restart_week(run, row, pack, state):
    """A testing aid: start this week's story over, so the real flow (picks, settling, Friday) can be
    tried again the same day. Nothing is deleted: every pick of the week is set aside under another
    week key, the week's own messages are removed from the channel, and the story goes back to
    `ready`. False, with the reason in result["error"], when it could not be done."""
    result, week = run.result, row.get("week_key") or ""
    rows = run.table.picks(week)
    if rows is None:
        result["error"] = "could not read the picks, so the week was not restarted"
        return False
    for pick in rows:
        if not run.table.update(pick.get("$record_id"), {"week_key": RESET_PREFIX + week,
                                                          "updated_at": run.today.isoformat()}):
            result["error"] = "could not set a pick aside, so the week was not restarted"
            return False
    seen = [ts for ts in list(state["posts"].values()) + [state.get("published")] if ts]
    for ts in seen:
        slack_delete(run.token, run.channel, ts)
    state.clear()
    state.update(new_state())
    if not save_state(run, row, pack, state, {"status": READY, "source_ref": ""}):
        result["error"] = "could not save the restarted week"
        return False
    row["status"] = READY
    result["restarted"] = True
    run.warn("restarted the week of {}: {} pick{} set aside, {} message{} removed".format(
        week, len(rows), "" if len(rows) == 1 else "s", len(seen), "" if len(seen) == 1 else "s"))
    return True


def do_post(input, result, table, llm):
    token = str(input.get("slack_bot_token") or "").strip()
    channel = result["channel"]
    testing, skip = _flag(input.get("testing")), _flag(input.get("skip_post"))
    result["testing"], result["preview"] = testing, skip
    today = local_today(_int(input.get("tz_offset"), DEFAULT_TZ_OFFSET, -86400, 86400),
                        input.get("today"))
    monday = monday_of(today)
    result["week"] = monday.isoformat()
    forced = _int(input.get("chapter"), 0, 0, PUBLISH_CHAPTER)
    target = forced or target_for(today)
    wrap = _wrap_input(input, result)
    banner = banner_pick(input.get("banner_daily"), input.get("banner"))          # above each chapter
    final_banner = banner_pick(input.get("banner_final"), input.get("banner"))    # above Friday's story
    force = _flag(input.get("force"))
    # How much of each chapter's story is shown: change it on any run, no model call.
    passage = _int(input.get("passage_words"), DEFAULT_PASSAGE_WORDS, PASSAGE_SHOWN_MIN, PASSAGE_SHOWN_MAX)
    # When this chapter's picks close, shown to each reader in their own time zone.
    closes = picks_deadline(_utc_now(), input.get("picks_close_time") or DEFAULT_CLOSE_TIME,
                            _int(input.get("picks_close_tz"), DEFAULT_CLOSE_TZ, -86400, 86400))

    if testing or skip:
        pack, source = preview_pack(table, monday)
        if source == "sample":
            result["warnings"].append("no story in the table: the built-in sample story is shown")
        chapter = target or 1
        result["chapter"] = chapter
        result.update({"story_title": pack["title"], "theme": pack["theme"], "kb_name": pack["kb"]})
        if chapter == PUBLISH_CHAPTER:
            canon = {}
            view = publish_view(pack, canon, [], assembled_story(pack, canon), wrap, final_banner)
        else:
            view = chapter_view(pack, {}, chapter, "test", test=True, wrap=wrap, banner=banner,
                                passage_words=passage, closes=closes)
        problems = block_problems(view["blocks"])
        if problems:
            result["warnings"].append("layout broke Slack's limits: " + "; ".join(problems))
        result.update({"text": view["text"], "words": view["words"], "read_seconds": view["seconds"],
                       "blocks_json": json.dumps(view["blocks"], ensure_ascii=False),
                       "preview_url": preview_url(view["blocks"]), "passage_words": passage,
                       "passage_shown": view.get("shown", 0)})
        if skip:
            result["ok"] = True
            return
        if not (token and channel):
            result["error"] = "channel and slack_bot_token are required (or set skip_post to yes)"
            return
        ts, error = slack_post(token, channel, view["text"], view["blocks"])
        if error:
            result["error"] = error
            return
        result.update({"posted": True, "message_ts": ts, "ok": True})
        return

    if not (token and channel):
        result["error"] = "channel and slack_bot_token are required"
        return
    if not table.token:
        result["error"] = "workato_api_token is required"
        return
    run = Run(table, llm, token, channel, result, today, wrap, banner, force, passage)
    run.closes, run.final_banner = closes, final_banner

    # A story left open from an earlier week is finished first, so a missed Friday never strands it.
    older = table.stories(OPEN)
    if older is None:
        result["error"] = "could not read the stories"
        return
    for row in sorted((r for r in older if (r.get("week_key") or "") < monday.isoformat()),
                      key=lambda r: r.get("week_key") or ""):
        pack, state = load_row(row)
        if not pack:
            run.warn("the open story of the week of {} could not be read".format(row.get("week_key")))
            continue
        if publish_week(run, row, pack, state):
            run.warn("published the story left open from the week of {}".format(row.get("week_key")))
        else:
            # Today's chapter still goes out: a story that cannot be finished must not hold up
            # the new week. It is tried again on the next run.
            run.warn("could not publish the story left open from the week of {}: {}".format(
                row.get("week_key"), result["error"] or result["skipped"] or "unknown"))
        result["error"], result["skipped"] = "", ""
        result["posted"], result["published"], result["message_ts"] = False, False, ""
        result["text"], result["blocks_json"], result["words"], result["read_seconds"] = "", "", 0, 0

    if not target:
        result["skipped"] = "weekend: nothing to post"
        result["ok"] = True
        return
    result["chapter"] = target
    row = table.story(monday.isoformat())
    if row is LOOKUP_FAILED:
        result["error"] = "could not read this week's story"
        return
    if not row:
        result["skipped"] = "no story is saved for the week of {}".format(monday.isoformat())
        result["ok"] = True
        return
    if row.get("status") == NEW and target != PUBLISH_CHAPTER:
        # Stored on Sunday but never cut into chapters: do it now rather than miss the day.
        do_prepare(input, result, table, llm, monday.isoformat())
        if result["error"]:
            result["error"] = "this week's story could not be prepared: " + result["error"]
            return
        row = table.story(monday.isoformat())
        if row is LOOKUP_FAILED or not row:
            result["error"] = "could not read this week's story"
            return
    pack, state = load_row(row)
    if not pack:
        result["error"] = "this week's story is not readable; save it again"
        return
    result.update({"story_title": pack["title"], "theme": pack["theme"], "kb_name": pack["kb"]})
    if _flag(input.get("restart")) and not restart_week(run, row, pack, state):
        return
    if row.get("status") == DONE and not force:
        result["skipped"] = "this week's story is already published"
        result["ok"] = True
        return
    if target != PUBLISH_CHAPTER:
        state["picks_cap"] = picks_cap_input(input)
    if target == PUBLISH_CHAPTER:
        if not state["posts"] and not state["settled"]:
            result["skipped"] = "no chapter was posted this week, so there is nothing to publish"
            result["ok"] = True
            return
        publish_week(run, row, pack, state)
    else:
        if settle(run, row, pack, state, target):
            post_chapter(run, row, pack, state, target)
        else:
            result["error"] = result["error"] or "the earlier chapters could not be settled"
    result["ok"] = not result["error"]


def story_run(input, result, table, token, channel, state):
    """The Run a click works in: drawn the way the chapter was drawn."""
    today = local_today(_int(input.get("tz_offset"), DEFAULT_TZ_OFFSET, -86400, 86400),
                        input.get("today"))
    look = state.get("look") or {}
    return Run(table, None, token, channel, result, today,
               _int(look.get("wrap"), WRAP_CHARS, WRAP_MIN, WRAP_MAX), str(look.get("banner") or ""),
               False, _int(look.get("passage"), DEFAULT_PASSAGE_WORDS, PASSAGE_SHOWN_MIN,
                           PASSAGE_SHOWN_MAX))


def tell(result, token, channel, user, text):
    """A private note. One that does not go is a warning: it must never undo a pick."""
    error = slack_ephemeral(token, channel, user, text)
    if error:
        result["warnings"].append("note to {}: {}".format(user, error))


def refresh_count(run, pack, state, chapter, week):
    """Redraw the chapter's message with how many picks are in. Best effort."""
    ts = state["posts"].get(str(chapter))
    rows = run.table.picks(week, chapter)
    if not ts or rows is None:
        return None
    view = chapter_view(pack, state["canon"], chapter, week, picks=len(rows),
                        wrap=run.wrap, banner=run.banner, passage_words=run.passage,
                        closes=(state.get("closes") or {}).get(str(chapter)),
                        bridge=(state.get("bridges") or {}).get(str(chapter), ""))
    error = slack_update(run.token, run.channel, ts, view["text"], view["blocks"])
    run.result["picks_in"] = len(rows)
    if error:
        run.warn("could not update the count: " + error)
    return len(rows)


def count_note(count, state, chapter):
    """What a private note adds: how many picks are in, and when the chapter closes."""
    note = NOTE_COUNT.format(count=count, s="" if count == 1 else "s") if count else ""
    closes = (state.get("closes") or {}).get(str(chapter))
    return note + (" Picks close {}.".format(close_token(closes)) if closes else "")


def pick_rule(state, mine, chapter, stamp=""):
    """Whether someone may pick on this chapter, given their picks so far this week: (why, note).
    `why` is "" when they may, otherwise dupe (the same press delivered twice, so no note),
    same_chapter or used."""
    if stamp and any((r.get("last_processed_ts") or "") == stamp for r in mine):
        return "dupe", ""
    if any(str(r.get("grant_type")) == str(chapter) for r in mine):
        return "same_chapter", (NOTE_THIS_CHAPTER.format(chapter=chapter)
                                + (NOTE_NEXT if int(chapter) < CHAPTERS else ""))
    cap = int(state.get("picks_cap") or 0)          # (a week saved before this had picks_per_week: ignored)
    if cap and len(mine) >= cap:
        last = pick_from_row(mine[-1])
        return "used", NOTE_USED.format(cap=cap, chapter=last["chapter"], choice=choice_label(
            last["choice"], mine[-1].get("week_key") or "", last["chapter"]))
    return "", ""


def record_pick(run, state, week, chapter, user_id, user_name, choice, text, stamp):
    """Check the rules and write the pick: (kept, why, note). `note` is what to tell the person
    when the pick was not kept (empty when there is nothing to say)."""
    mine = run.table.picks(week, user=user_id)
    if mine is None:
        return False, "error", NOTE_TRY_AGAIN.format(why="your earlier picks could not be read from the data table")
    why, note = pick_rule(state, mine, chapter, stamp)
    if why:
        return False, why, note
    # The person is in group_id, as weekly_challenge.py keeps its acceptances: a row with their id
    # on it would be read by spotter on every one of their logs, and this one has no business there.
    fields = {"record_key": "{}_{}_{}_{}".format(PICK_ROW, week, chapter, user_id),
              "row_type": PICK_ROW, "id": week, "name": user_name, "group_id": user_id,
              "week_key": week, "grant_type": str(chapter), "status": choice, "description": text,
              "last_processed_ts": stamp, "created_at": run.today.isoformat(),
              "updated_at": run.today.isoformat()}
    if not run.table.create(fields):
        return False, "error", NOTE_TRY_AGAIN.format(why="the data table did not accept the pick")
    return True, "", ""


def chapter_status(state, chapter):
    """("open" | "deadline" | "settled" | "not_posted", closes): whether a chapter takes picks and, if not,
    why. A chapter posted before closing times existed has no deadline."""
    closes = (state.get("closes") or {}).get(str(chapter))
    if str(chapter) not in state["posts"]:
        return "not_posted", closes
    if chapter in state["settled"]:
        return "settled", closes
    if closes and _utc_now().timestamp() > closes["at"]:
        return "deadline", closes
    return "open", closes


def open_chapter(state, chapter):
    """Whether a chapter is the one picks are open on."""
    return chapter_status(state, chapter)[0] == "open"


def closed_reason(state, chapter):
    """What to tell someone whose pick came too late, and why."""
    why, closes = chapter_status(state, chapter)
    if why == "deadline":
        return NOTE_CLOSED_DEADLINE.format(chapter=chapter, when=close_token(closes))
    if why == "settled":
        return NOTE_CLOSED_SETTLED.format(chapter=chapter)
    return NOTE_CLOSED_NOT_POSTED.format(chapter=chapter)


def do_click(input, result, table):
    token = str(input.get("slack_bot_token") or "").strip()
    user_id, channel = result["user_id"], result["channel"]
    parsed = parse_value(input.get("action_value"))
    if not parsed:
        result["error"] = "action_value is not a story relay button"
        return
    if not (user_id and channel and token):
        result["error"] = "user_id, channel and slack_bot_token are required"
        return
    chapter, week = parsed["chapter"], parsed["week"]
    result.update({"week": week, "chapter": chapter, "testing": parsed["test"], "pick": parsed["choice"]})

    if parsed["test"]:
        tell(result, token, channel, user_id, NOTE_TEST.format(
            choice=choice_label(parsed["choice"], week, chapter), chapter=chapter))
        result["ok"] = True
        return

    if not table.token:
        result["error"] = "workato_api_token is required"
        return
    row = table.story(week)
    if row is LOOKUP_FAILED:
        tell(result, token, channel, user_id, NOTE_TRY_AGAIN.format(why="the story could not be read from the data table"))
        result["error"] = "could not read the story"
        return
    pack, state = load_row(row) if row else (None, None)
    if not pack or row.get("status") == DONE:
        tell(result, token, channel, user_id, NOTE_FINISHED)
        result["skipped"] = "the story has finished"
        result["ok"] = True
        return
    if not open_chapter(state, chapter):
        tell(result, token, channel, user_id, closed_reason(state, chapter))
        result["skipped"] = "chapter {} is closed".format(chapter)
        result["ok"] = True
        return

    run = story_run(input, result, table, token, channel, state)
    name = slack_user_name(token, user_id) or user_id
    result["user_name"] = name
    kept, why, note = record_pick(run, state, week, chapter, user_id, name, parsed["choice"], "",
                                  str(input.get("action_ts") or "").strip())
    result["recorded"], result["already"] = kept, why in ("same_chapter", "used")
    if kept:
        count = refresh_count(run, pack, state, chapter, week)
        tell(result, token, channel, user_id, NOTE_LOCKED.format(
            choice=choice_label(parsed["choice"], week, chapter), chapter=chapter)
            + count_note(count, state, chapter))
    elif note:
        tell(result, token, channel, user_id, note)
    if why == "error":
        result["error"] = "the pick could not be saved"
    result["ok"] = not result["error"]


def _blank_result(mode, channel):
    return {
        "ok": False, "error": "", "warnings": [], "mode": mode, "testing": False, "preview": False,
        "skipped": "", "week": "", "chapter": 0, "channel": channel,
        "recent_stories": "", "recent_themes": "", "stories_found": 0,
        "saved": False, "status": "", "story_title": "", "kb_name": "", "theme": "", "author": "",
        "words": 0, "retry": False, "retry_reason": "", "problems": [], "flagged": [],
        "chapters_preview": "", "conversation_id": "", "genie_name": "",
        "posted": False, "published": False, "message_ts": "", "text": "", "read_seconds": 0,
        "blocks_json": "", "preview_url": "", "thread_ts": "", "settled": [],
        "user_id": "", "user_name": "", "pick": "", "recorded": False, "already": False,
        "picks_in": 0, "rows_written": 0,
        "llm_calls": 0, "restarted": False, "passage_words": 0, "passage_shown": 0,
    }


def guess_mode(input):
    asked = str(input.get("mode") or "").strip().lower()
    if asked:
        return asked
    if str(input.get("action_value") or "").strip():
        return "click"
    return "post"


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    mode = guess_mode(input)
    channel = str(input.get("channel") or "").strip()
    result = _blank_result(mode, channel)
    result["user_id"] = str(input.get("user_id") or "").strip()
    table = Table(str(input.get("workato_api_token") or "").strip())
    key = str(input.get("azure_api_key") or "").strip()
    llm = Azure(key, input.get("azure_url")) if key else None
    try:
        if mode == "history":
            do_history(input, result, table)
        elif mode == "prepare":
            do_prepare(input, result, table, llm)
        elif mode == "announce":
            do_announce(input, result, table)
        elif mode == "post":
            do_post(input, result, table, llm)
        elif mode == "click":
            do_click(input, result, table)
        else:
            result["error"] = "mode is history, prepare, announce, post or click"
    except Exception as error:                                     # noqa: BLE001
        result["error"] = "unexpected {}: {}".format(type(error).__name__, str(error)[:300])
    result["ok"] = not result["error"]
    result["rows_written"] = table.written
    result["llm_calls"] = llm.calls if llm else 0
    result["warnings"] += table.errors + (llm.errors if llm else [])
    return result


if __name__ == "__main__":
    print(json.dumps(main({
        "mode": "post", "testing": "yes", "skip_post": "" if os.environ.get("SLACK_CHANNEL") else "yes",
        "chapter": sys.argv[1] if len(sys.argv) > 1 else "1",
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "channel": os.environ.get("SLACK_CHANNEL", "")}), indent=2, ensure_ascii=False))
