"""
Story Store -- keep the Story Relay genie's pick in the data table, exactly as it came, and nothing more.

The Sunday recipe runs this straight after the genie. It has Azure CLEAN the story (one call: a
shorter, professional, neutral version), then writes ONE story_week row for the week with status
`new`. It cuts no chapters. story_relay.py (mode prepare, or the daily post if prepare never ran)
reads the row back and does the rest.

THE SUNDAY POST  Straight after the story is kept, this step posts the short announcement of it
(title, why it matters, how the week goes: a chapter Mon-Thu, one pick each, the team's story on
Friday; no spoilers, no buttons), so the Sunday recipe is just: genie -> this step. It needs
slack_bot_token and channel; announce = no turns it off; testing = yes returns it in blocks_json
and preview_url without posting. It is recorded in the row's scheduled_time, so storing the same
story again does not post twice, and a different story replaces (and deletes) the earlier post.
A story is only announced after it passed every check below, including having enough sentences
to be cut into four chapters. If the post fails the story is still stored. The layout is copied
from story_relay.py (a test fails if it drifts).

THE LENGTH  `story_words` (150-700, default 400) is how long the cleaned story is. It is the room the
relay has: the daily post shows only part of each chapter (the relay's passage_words), so a longer
story lets a post be made longer later without cleaning the story again, and gives each turning
point more to stand on. It changes only what is stored: a post is as long as the relay says.

THE WORDING  Each week Azure writes the lines of the post for THAT story (curate = no keeps the
standard wording): the hook, the teaser, and the text after "Mon-Thu:", "Your pick:", "Fri:" and
"Our job:". The labels, the layout and the length stay. It is shown the story (to write FROM, never
to reveal) and the last three weeks' wording (to differ from). Each line is checked for its word
limit, for still saying what it must (a short chapter each morning Mon-Thu ending in a choice; one
pick a week with a button under each chapter; the team's story on Friday; finish the story or give
it a better ending), for the sense of the theme, for no emoji or markup, for the screened words, and
for repeating the story's own later words (a spoiler). Up to three rounds, each sent back with its
problems; if it cannot be made right, or would read over 30 seconds, the standard wording is used
and warnings says so. What was used is kept in the row (raw.post_lines) for next week to avoid.

THE CLEANING (azure_api_key; skip_clean = yes stores the genie's text as it came)
    Azure rewrites the story at roughly two thirds of its length in plain, neutral, global English:
    the people, the order of events, every turning point and the ending stay; religion and
    scripture, festivals, money amounts, years, place names, local customs and remarks about
    looks go, or become neutral wording. It adds no event and no person. Every answer is checked
    (150-1,500 words, shorter than the original, the main character still in it, none of the
    screened words left), with up to four rounds (clean_attempts): each failed round goes back with its problems and the
    version Azure wrote, to be revised. The story posts say
    The posts show only the title and the theme: readers do not know the author or the collection,
    so neither is shown (both are kept in the table).
    Stored: the clean version in `description`; the genie's own text, title and a note of what
    changed in `content` (the text only if it fits the column).

WHAT IS KEPT (the shared table, row_type story_week, one row a week)
    record_key   story_week_<monday>             id / week_key   the Monday of the week it is for
    name         story_title                     topic_name      theme
    kb_tag       kb_name                         description     story_text, whole
    group_name   the genie's name                group_id        the genie's conversation id
    status       new                             slack_channel_id  channel, when given
    content      {"raw": {"author", "why", "main", "lesson", "adapted", "changes",
                          "original_title", "original_text"}}
    created_at / updated_at   the day it was stored

    The genie name and conversation id are kept so that a story that cannot be used can be sent
    back to the SAME conversation ("That story cannot be used: ...") and the genie picks again.

BEFORE IT STORES, four checks (a story that fails one is NOT stored: retry = true and retry_reason
is a sentence to send the genie in the same conversation)
    * title, kb_name, theme and story_text are all there, and the story is 150 words or more;
    * it is not a story already stored for another week;
    * it has none of the words that do not belong in a global workplace story (violence, abuse,
      religion and the like), checked AFTER the cleaning -- approve = yes stores it anyway, after a
      person has read it;
    * the week is not already under way (open or published): it cannot be replaced.
    Money amounts and years only add a note to warnings, for a person to read before Monday.
    The word lists are copied from story_relay.py (a test fails if they drift).

WEEK  Saturday or Sunday -> the coming Monday; any other day -> that week's Monday. `week` overrides.
      The day is read on tz_offset seconds east of UTC (default 19800, India, as story_relay.py).

testing = yes checks everything and stores nothing.

Input / output schema: story_store_input_schema.json / story_store_output_schema.json
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

TABLE_ID = "0b863cb1-4712-416b-a9d5-7bf7f2f9b059"
TABLE_QUERY_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
TABLE_RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
TABLE_RECORD_URL = TABLE_RECORDS_URL + "/{}"
AZURE_URL = ("https://cour-servicenow-1.openai.azure.com/openai/deployments/"
             "gpt-4o/chat/completions?api-version=2024-10-21")
HTTP_TIMEOUT = 30
QUERY_MAX_PAGES = 50

COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "group_name": "5ca195e6-35e1-4ec9-8916-96dc612f4480",
    "status": "863a9d40-87a7-49ff-ba40-32858e62cd48",
    "week_key": "e9659bdd-c36c-486b-a531-e7b5a38252f6",
    "topic_name": "f4ec2556-bb08-49e0-8a7b-4fb608baf4f6",
    "kb_tag": "7addedee-88ea-400a-b74a-37a1c5ec843a",
    "description": "3d9e2f48-f2b0-457e-9666-5cada51a32b4",
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
    "slack_channel_id": "7101072d-867b-4104-a1e4-ef6611adaaa9",
    "scheduled_time": "8ebe17e6-05f3-4063-be9c-ed7b743c7b10",
    "created_at": "d0b48b75-2fbf-44db-a36a-cc0a1e46036c",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
}

STORY_ROW = "story_week"
NEW, READY, OPEN, DONE = "new", "ready", "open", "done"
DEFAULT_TZ_OFFSET = 19800
MIN_STORY_WORDS = 150
MAX_STORY_CHARS = 9500          # what one column keeps: the CLEANED story
MAX_ORIGINAL_CHARS = 20000      # what the genie may send; the cleaning shortens it
# How long the cleaned story is. The daily post shows only a part of each chapter (story_relay.py's
# passage_words), so the story itself can hold more than a post shows: that is the room the relay has
# to make a post longer later. `story_words` sets the target; the story may run from 55% to 130% of it.
STORY_WORDS_DEFAULT = 400
STORY_WORDS_BOUNDS = (150, 700)
MIN_SENTENCES = 8               # fewer cannot be cut into four chapters
CLEAN_ATTEMPTS = 4              # rounds of cleaning; `clean_attempts` overrides (1-6)
# A cleaned story that still names money or years is sent back once; if it comes back the same
# it is kept, with a note in warnings, rather than refused: it is a matter of taste, not of safety.
SOFT = "it still names money or years"
TEXT_LIMITS = {"title": 90, "kb": 80, "author": 60, "theme": 24, "why": 220, "lesson": 160,
               "main": 80, "genie": 80, "conversation": 120}

# Copied from story_relay.py.
FLAGGED = re.compile(
    r"\b(?:sex\w*|naked|nude\w*|porn\w*|rap(?:e|ed|es|ist|ists)|molest\w*|abus\w+|suicid\w*"
    r"|self[- ]harm\w*|murder\w*|kill\w*|terroris\w*|massacre\w*|genocide|nazi\w*|cocaine|heroin"
    r"|overdos\w*|fuck\w*|shit\w*|bitch\w*|slut\w*|whore\w*)\b", re.I)
RELIGIOUS = re.compile(
    r"\b(?:bible|biblical|scripture\w*|gospel|jesus|christ|christian\w*|church\w*|mosque\w*"
    r"|synagogue\w*|temple|allah|gabriel|prayer\w*|pray(?:s|ed|ing)?|christmas|easter|ramadan"
    r"|diwali|hanukkah|god|heaven|angels?)\b", re.I)
REGIONAL = re.compile(r"[$£€₹¥]\s?\d[\d,.]*|\b(?:1[89]|20)\d\d\b")


def tidy(text):
    """One line of plain text: whitespace collapsed, no Slack styling marks."""
    out = re.sub(r"[*`]", "", str(text or "").replace("\r", " "))
    out = re.sub(r"(?<![A-Za-z0-9])_+|_+(?![A-Za-z0-9])", "", out)
    return " ".join(out.split())


def clip(text, limit):
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"


def story_flags(*texts):
    found = set()
    for text in texts:
        found.update(w.lower() for w in FLAGGED.findall(str(text or "")))
        found.update(w.lower() for w in RELIGIOUS.findall(str(text or "")))
    return sorted(found)


def regional_notes(text):
    return list(dict.fromkeys(m.group(0).strip() for m in REGIONAL.finditer(str(text or""))))[:4]


def clean_theme(raw):
    words = re.findall(r"[a-z][a-z\-]*", str(raw or "").lower())
    return " ".join(words[:2])[:TEXT_LIMITS["theme"]]


def _utc_now():
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


def week_for_story(day):
    """This week's Monday, except at the weekend, when it is the Monday that is coming."""
    return day + timedelta(days=7 - day.weekday()) if day.weekday() >= 5 else monday_of(day)


# --------------------------------------------------------------------------
# Copied from story_relay.py, for the Sunday post (a Workato step is one file; a test fails
# if the copies drift).
# --------------------------------------------------------------------------

WRAP_MIN, WRAP_MAX = 20, 120
_EMOJI = ("[" + "".join("{}-{}".format(chr(a), chr(b)) for a, b in ((0x2190, 0x2BFF), (0x1F000, 0x1FAFF)))
          + "".join(chr(c) for c in (0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D, 0x3297, 0x3299))
          + "]")
_MODIFIER = "[" + "".join(chr(c) for c in (0xFE0F, 0x200D, 0x20E3)) + "]"
_SLACK_TOKEN = re.compile(r"(<(?:[@#!][^>\s]*|https?://[^>\s]+|mailto:[^>\s]+)>)")
_WORD = re.compile(r"(?:<[^>\n]*>|\S)+")
_ENTITY = re.compile(r"&(?:amp|lt|gt);")
LIMITS = {"blocks": 50, "section": 3000, "field": 2000, "alt_text": 2000,
          "image_url": 3000, "context_elements": 10,
          "actions_elements": 25, "button_text": 75, "action_id": 255, "value": 2000,
          "block_id": 255}
SERIES_NAME = "Story Relay"
GOAL_TEXT = "Finish this story, or give it a better ending."
ICON_GOAL = "\U0001F3AF"
ICON_WHY = "\U0001F4A1"
ICON_SERIES = "\U0001F4D6"
SEP = "  \u00b7  "
BANNER_ALT = "Story Relay"
WORDS_PER_SECOND = 3.3
WRAP_CHARS = 84
ANNOUNCE_HOOKS = (
    "This week we read a true story about {theme}, and decide how it goes.",
    "A true story about {theme} is coming, and the ending is up to us.",
    "One true story about {theme}, four short chapters, and you decide what happens next.",
    "We have a story about {theme} to finish this week.",
)
ANNOUNCE_STEPS = (
    "\u2022 *Mon\u2013Thu:* a short chapter each morning, with a choice at the end",
    "\u2022 *Your pick:* one a week, with a button under each chapter, so make it count",
    "\u2022 *Fri:* we publish the story the team built",
)
ANNOUNCE_LABEL = "Starts {when}"
ANNOUNCE_STEP_LABELS = ("*Mon\u2013Thu:*", "*Your pick:*", "*Fri:*")
ANNOUNCE_STEP_KEYS = ("mon_thu", "pick", "fri")
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
BLOCK_KIT_BUILDER = "https://app.slack.com/block-kit-builder#"
SLACK_API = "https://slack.com/api/"
SLACK_POST_URL = SLACK_API + "chat.postMessage"
SLACK_DELETE_URL = SLACK_API + "chat.delete"
_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc", "no", "inc", "ltd"}
_SENTENCE_END = re.compile(
    "[.!?]+[\"'\u201d\u2019)\\]]*(?=\\s+[\"'\u201c\u2018(\\[]?[A-Z0-9])")


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


def count_words(text):
    return len(re.findall(r"[A-Za-z0-9][\w'’%.\-]*", plain(text)))


def read_seconds(words):
    """How long it takes to read, to the nearest 5 seconds and never under 10."""
    return max(10, int(round(words / WORDS_PER_SECOND / 5.0)) * 5)


def theme_emoji(theme):
    text = str(theme or "").lower()
    for word, emoji in THEME_EMOJI:
        if word in text:
            return emoji
    return DEFAULT_THEME_EMOJI


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


def slack_delete(token, channel, ts):
    _, error = _slack(token, SLACK_DELETE_URL, {"channel": channel, "ts": str(ts)})
    return error


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


def raw_json(author, why, main_character, lesson, adapted, changes, original, teaser=None, post_lines=None):
    """What is kept beside the story. The genie's own text goes in only if it fits the column."""
    raw = {"author": author, "why": why, "main": main_character, "lesson": lesson,
           "adapted": adapted, "changes": changes, "original_title": original["title"]}
    if teaser is not None:
        raw["teaser"] = teaser
    if post_lines:
        raw["post_lines"] = post_lines
    text = json.dumps({"raw": raw}, ensure_ascii=False, separators=(",", ":"))
    if adapted:
        fuller = json.dumps({"raw": dict(raw, original_text=original["text"])}, ensure_ascii=False,
                            separators=(",", ":"))
        if len(fuller) <= MAX_STORY_CHARS:
            return fuller
    return text


def _flag(value):
    return str(value or "").strip().lower() in ("yes", "y", "true", "1", "on")


def _int(value, default, low, high):
    try:
        return min(high, max(low, int(float(str(value).strip()))))
    except (TypeError, ValueError):
        return default


def _send_json(url, headers, payload, method="POST", timeout=HTTP_TIMEOUT):
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {} {}: {}".format(error.code, method, url.split("/")[2], detail)
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


class Table(object):
    def __init__(self, token):
        self.token = token
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.errors, self.written, self.read_failed = [], 0, False

    def stories(self):
        """Every story_week row, None when the read failed."""
        payload = {"where": {"row_type": {"$eq": STORY_ROW}}, "limit": 200}
        rows = []
        for _page in range(QUERY_MAX_PAGES):
            body, error = _send_json(TABLE_QUERY_URL, self.headers, payload)
            if error:
                self.errors.append("table.query " + error)
                return None
            columns = [f.get("name") for group in body.get("schema", []) for f in group]
            rows += [dict(zip(columns, [v for group in row for v in group]))
                     for row in body.get("data", [])]
            if not body.get("continuation_token"):
                break
            payload["continuation_token"] = body["continuation_token"]
        return rows

    def write(self, row, fields):
        document = {"$" + COLUMNS[k]: (None if v is None else v if isinstance(v, str) else str(v))
                    for k, v in fields.items()}
        if row:
            record_id = row.get("$record_id")
            if not record_id:
                self.errors.append("table.update called without a $record_id")
                return False
            body, error = _send_json(TABLE_RECORD_URL.format(record_id), self.headers,
                                     {"document": document}, "PUT")
        else:
            body, error = _send_json(TABLE_RECORDS_URL, self.headers, {"document": document}, "POST")
        if error:
            self.errors.append("table.write " + error)
            return False
        self.written += 1
        return True


class Azure(object):
    """Never raises; a failure is noted and the caller falls back."""

    def __init__(self, api_key, url=None):
        self.url = url or AZURE_URL
        self.headers = {"api-key": api_key, "Content-Type": "application/json"}
        self.calls, self.errors = 0, []

    def chat(self, system, user, max_tokens=2600, temperature=0.3):
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


CLEAN_SYSTEM = (
    "You prepare a true story for a shared storytelling game in a workplace channel read by "
    "colleagues across companies and countries, senior people included. You rewrite it as a "
    "SHORT, professional, neutral version. You return JSON only.\n\n"
    "You are given the story's theme, main character, lesson and why it resonates, as the story's "
    "selector set them. Keep them intact: the rewrite must still be about that theme, keep the "
    "main character's name and role, and still lead to that lesson. Return the title, "
    "why_it_resonates and lesson exactly as given, unless one of them contains something under "
    "REMOVE, and then change only that.\n\n"
    "KEEP: the people and their first names, the order of events, every moment where someone "
    "chooses how to act, what each person says that matters to the story, and the ending.\n"
    "REMOVE or make neutral: religion, scripture, sayings that belong to a faith, prayers, "
    "angels and gods; festivals and holidays (say 'the end of the year' or leave them out); money "
    "amounts and currencies (say 'a large unpaid bill'); years and dates; country, state, city "
    "and street names and local customs; remarks about someone's looks, age or family situation; "
    "slang, insults and name-calling; anything sexual, violent or unkind.\n"
    "LENGTH: about TARGET_WORDS words in all, never over MAX_WORDS. The story is read in four daily "
    "chapters and each day's post shows only part of a chapter, so give each of the four turning "
    "points a full paragraph with room around it: the moment before the choice, the choice, and what "
    "follows. Short sentences, none over 18 words. Keep only what moves the story: who it is about, "
    "the choice made at each turning point, and the ending. Drop scene-setting that does not matter, "
    "side characters, backstory and repeated beats.\n"
    "STYLE: plain, warm global English, past tense, short paragraphs separated by one blank line, "
    "a little dialogue where it carries the story. No title line, no moral at the end, no "
    "commentary.\n"
    "NEVER add an event, a person, a name, a place or a number that the original does not have.\n\n"
    'Return JSON: {"title": "the title, changed only if it is religious or local", '
    '"story": "the whole rewritten story", "why_it_resonates": "one plain sentence, 25 words at '
    'most, neutral", "lesson": "one plain sentence, 20 words at most, neutral", '
    '"teaser": "one plain sentence, 20 words at most, for the announcement: who the story is about '
    'and what is at stake. It must NOT reveal any turning point, any choice or how it ends, and '
    'must not say what changes or what is unlocked", '
    '"changes": "one sentence saying what you removed or changed"}')


def clean_system(target):
    """The cleaning prompt for a story of about `target` words."""
    return (CLEAN_SYSTEM.replace("TARGET_WORDS", str(target))
            .replace("MAX_WORDS", str(int(target * 1.3))))


def clean_prompt(given, text, fixes=(), previous=""):
    """`given` is what the genie returned: title, theme, main, lesson, why."""
    lines = ["Title: " + given["title"], "Theme: " + (given["theme"] or "not given"),
             "Main character: " + (given["main"] or "not given"),
             "Lesson: " + (given["lesson"] or "not given"),
             "Why it resonates: " + (given["why"] or "not given"), "",
             "Original story ({} words):".format(count_words(text)), text]
    if fixes:
        if previous:
            lines += ["", "Your previous version of the story (revise THIS one, keep what is already "
                      "right, and return the whole story):", previous]
        lines += ["", "Your last answer had these problems. Fix every one:"] + ["- " + f for f in fixes]
    return "\n".join(lines)


def check_clean(answer, original_words, given, target=STORY_WORDS_DEFAULT):
    """(clean dict, problems) from Azure's answer. The genie's title, why and lesson stay exactly
    as given unless they hold a screened word (or are empty), whatever Azure sent back."""
    main_character = given["main"]
    if not isinstance(answer, dict):
        return None, ["the answer was not a JSON object"]
    story = re.sub(r"\n{3,}", "\n\n", str(answer.get("story") or "").replace("\r\n", "\n")).strip()
    def keep(key, answer_key, limit):
        mine = given[key]
        if mine and not story_flags(mine):
            return mine
        return clip(tidy(answer.get(answer_key)), limit) or mine

    clean = {"title": keep("title", "title", TEXT_LIMITS["title"]), "text": story,
             "why": keep("why", "why_it_resonates", TEXT_LIMITS["why"]),
             "lesson": keep("lesson", "lesson", TEXT_LIMITS["lesson"]),
             "teaser": clip(tidy(answer.get("teaser")), 140),
             "changes": clip(tidy(answer.get("changes")), 240)}
    problems, words = [], count_words(story)
    if not story:
        return None, ["the story is empty"]
    low, high = min(int(target * 0.55), int(original_words * 0.6)), min(int(target * 1.3), original_words)
    if words < low:
        problems.append("the story is only {} words; aim for about {}, with a full paragraph for each "
                        "turning point and the ending".format(words, target))
    if words > high:
        problems.append("the story is {} words; aim for about {}, never over {}, and shorter than the "
                        "original ({})".format(words, target, high, original_words))
    if len(story) > MAX_STORY_CHARS:
        problems.append("the story is {:,} characters; the limit is {:,}".format(len(story), MAX_STORY_CHARS))
    if len(split_sentences(story)) < MIN_SENTENCES:
        problems.append("the story has fewer than {} sentences; use short sentences, at least {} in "
                        "all, so it can be cut into four chapters".format(MIN_SENTENCES, MIN_SENTENCES))
    first = (main_character or "").split(",")[0].split(" ")[0].strip()
    if first and first.lower() not in story.lower():
        problems.append("the main character {} is missing".format(first))
    money = regional_notes(story)
    if money:
        problems.append(SOFT + " ({}): say it in words, for example 'a large unpaid bill', and "
                        "leave out years".format(", ".join(money)))
    left = story_flags(story, clean["title"], clean["why"], clean["lesson"], clean["teaser"])
    if left:
        problems.append("it still contains: " + ", ".join(left))
    return clean, problems


def clean_story(llm, given, text, attempts=CLEAN_ATTEMPTS, target=STORY_WORDS_DEFAULT):
    """(clean dict, problems): Azure's neutral, shorter version of the story. Each round that
    fails is sent back with its problems and the version it wrote, up to `attempts` rounds."""
    fixes, last, previous = [], None, ""
    for _ in range(max(1, attempts)):
        reply = llm.chat(clean_system(target), clean_prompt(given, text, fixes, previous))
        if not reply:
            fixes, last = [], (None, ["Azure gave no answer"])
            continue
        try:
            answer = json.loads(reply)
        except ValueError:
            fixes, last = ["the answer was not valid JSON"], (None, ["the answer was not valid JSON"])
            continue
        clean, problems = check_clean(answer, count_words(text), given, target)
        if clean and not problems:
            return clean, []
        fixes, last = problems, (clean, problems)
        previous = clean["text"] if clean else previous
    if last and last[0] and all(p.startswith(SOFT) for p in last[1]):
        return last[0], []
    return last


ANNOUNCE_SYSTEM = (
    "You write the Sunday announcement of a shared storytelling week for a workplace Slack channel "
    "read by colleagues across companies and countries, senior people included. Each week the "
    "channel reads one true story, in four short daily chapters, and decides what happens next. "
    "You are given this week's story. Write the lines of the announcement so that THIS week's "
    "post feels written for THIS story and its theme, and does not read like last week's. "
    "You return JSON only.\n\n"
    "Four of the lines follow a fixed bold label in the post: 'Mon\u2013Thu:', 'Your pick:', 'Fri:' and "
    "'Our job:'. Write only what comes AFTER the label, and never repeat the label, the days or the "
    "words 'our job' in it: start straight with the point.\n"
    "The lines, and what each must still say (the facts never change, the wording always does):\n"
    "- hook (at most 18 words): the opening line. It gives the sense of the theme, in the story's own "
    "world, not a slogan.\n"
    "- teaser (at most 22 words): who the story is about and what is at stake, as a reason to come "
    "back on Monday.\n"
    "- mon_thu (at most 16 words): a short chapter arrives each morning, and each ends with a choice.\n"
    "- pick (at most 16 words): everyone gets ONE pick a week, with a button under each chapter, so "
    "it is worth choosing well.\n"
    "- fri (at most 12 words): the team's finished story is published.\n"
    "- job (at most 14 words): the team's job is to finish the story, or give it a better ending.\n\n"
    "RULES: never reveal a turning point, a choice, what changes or how the story ends; do not "
    "quote the story; use only names that are in the story and only when it helps. Warm, plain, "
    "professional, a little curious. No emoji, no markdown, no hashtags, no exclamation marks, no "
    "digits. Never mention an author, a book, a collection or a source. Do not begin the hook "
    "with 'This week' or 'A true story' unless the recent lines below do not. Vary the shape of the "
    "sentences from the recent weeks given to you, and never reuse their phrases.\n"
    'Return JSON: {"hook": "...", "teaser": "...", "mon_thu": "...", "pick": "...", "fri": "...", '
    '"job": "..."}')
LINE_KEYS = ("hook", "teaser", "mon_thu", "pick", "fri", "job")
LINE_WORDS = {"hook": 18, "teaser": 22, "mon_thu": 16, "pick": 16, "fri": 12, "job": 14}
LINE_ECHOES = {                      # what a line must NOT repeat from its fixed label
    "mon_thu": r"\bmon(?:day)?\b|\bthu(?:rsday)?\b",
    "pick": r"^\s*your pick",
    "fri": r"\bfri(?:day)?\b",
    "job": r"^\s*our job",
}
LINE_NEEDS = {                      # what a line must still say, as one of each group of words
    "mon_thu": (("chapter",), ("choice", "choose", "decide", "decision", "pick", "what happens")),
    "pick": (("one", "single", "once"), ("button", "tap", "press", "click")),
    "fri": (("publish", "share", "post", "reveal", "unveil", "finished", "built"),),
    "job": (("finish", "complete", "write"), ("ending", "story", "end")),
}
ANNOUNCE_ATTEMPTS = 3
MAX_POST_SECONDS = 30


def announce_prompt(title, theme, story, teaser, recent, fixes=(), previous=None):
    lines = ["Title: " + title, "Theme: " + theme, "Spoiler-free teaser already written for it: " +
             (teaser or "none"), "", "The story (for you only, never to be revealed):", story, ""]
    if recent:
        lines.append("The announcements of recent weeks. Do not reuse their openings or phrases:")
        for number, said in enumerate(recent, 1):
            lines.append("{}. {}".format(number, " | ".join(said[k] for k in LINE_KEYS if said.get(k))))
        lines.append("")
    lines.append("Write this week's lines.")
    if fixes:
        if previous:
            lines += ["", "Your previous lines: " + json.dumps(previous, ensure_ascii=False)]
        lines += ["", "Those lines had these problems. Fix every one:"] + ["- " + f for f in fixes]
    return "\n".join(lines)


def _grams(text, size=3):
    words = re.findall(r"[a-z']+", str(text).lower())
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def check_lines(answer, theme, story):
    """(lines, problems) from Azure's answer: each line within its words, still saying what it
    must, in the theme's sense, with no emoji or markup, nothing screened, and no run of the
    story's own later words (a spoiler)."""
    if not isinstance(answer, dict):
        return None, ["the answer was not a JSON object"]
    lines, problems = {}, []
    for key in LINE_KEYS:
        said = re.sub(_EMOJI + "|" + _MODIFIER, "", tidy(answer.get(key)))
        said = " ".join(said.split())
        if not said:
            problems.append("{} is missing".format(key))
            continue
        if key in LINE_ECHOES and re.search(LINE_ECHOES[key], said, re.I):
            problems.append("{} repeats its label; write only what comes after it".format(key))
        if key in ("mon_thu", "pick", "fri") and not said[1:2].isupper():
            said = said[0].lower() + said[1:]               # it follows "Mon-Thu:" and the like
        if count_words(said) > LINE_WORDS[key]:
            problems.append("{} is {} words; at most {}".format(key, count_words(said), LINE_WORDS[key]))
        if re.search(r"[!#]|\d", said):
            problems.append("{} has an exclamation mark, a hashtag or a digit".format(key))
        for group in LINE_NEEDS.get(key, ()):
            if not any(word in said.lower() for word in group):
                problems.append("{} must still say it ({})".format(key, " / ".join(group[:3])))
        lines[key] = said
    if problems:
        return None, problems
    stem = (theme or "")[:5].lower()
    if stem and stem not in (lines["hook"] + " " + lines["teaser"]).lower():
        problems.append("the hook or the teaser must carry the sense of the theme ({})".format(theme))
    words = story.split()
    later = _grams(" ".join(words[len(words) // 2:]))
    for key in ("hook", "teaser"):
        copied = sorted(_grams(lines[key]) & later)
        if copied:
            problems.append("{} repeats the story's own later words ('{}'): do not reveal it".format(
                key, copied[0]))
    left = story_flags(*lines.values())
    if left:
        problems.append("it contains: " + ", ".join(left))
    return (None if problems else lines), problems


def curate_announcement(llm, title, theme, story, teaser, recent, attempts=ANNOUNCE_ATTEMPTS):
    """(lines, problems): this week's announcement written for this story, checked, with rounds
    that send the problems back. None when it could not be made right: the caller uses the
    standard wording."""
    fixes, previous, last = [], None, []
    for _ in range(max(1, attempts)):
        reply = llm.chat(ANNOUNCE_SYSTEM, announce_prompt(title, theme, story, teaser, recent, fixes,
                                                          previous), max_tokens=500, temperature=0.9)
        if not reply:
            last = ["Azure gave no answer"]
            continue
        try:
            answer = json.loads(reply)
        except ValueError:
            fixes, last = ["the answer was not valid JSON"], ["the answer was not valid JSON"]
            continue
        lines, problems = check_lines(answer, theme, story)
        if lines:
            return lines, []
        previous = answer if isinstance(answer, dict) else None
        fixes, last = problems, problems
    return None, last


def recent_announcements(rows, week, limit=3):
    """The wording of the last few weeks' Sunday posts, newest first, from the stored rows."""
    found = []
    for row in sorted((r for r in rows or [] if r.get("week_key") and r.get("week_key") != week),
                      key=lambda r: r.get("week_key"), reverse=True):
        try:
            said = json.loads(row.get("content") or "{}").get("raw", {}).get("post_lines")
        except (ValueError, AttributeError):
            said = None
        if isinstance(said, dict) and said:
            found.append(said)
        if len(found) >= limit:
            break
    return found


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    result = {"ok": False, "error": "", "warnings": [], "saved": False, "replaced": False,
              "week": "", "status": "", "story_title": "", "kb_name": "", "story_author": "",
              "theme": "", "genie_name": "", "conversation_id": "", "words": 0,
              "retry": False, "retry_reason": "", "problems": [], "flagged": [], "rows_written": 0,
              "cleaned": False, "story_title_original": "", "words_original": 0,
              "changes": "", "llm_calls": 0, "announced": False, "message_ts": "", "text": "",
              "read_seconds": 0, "blocks_json": "", "preview_url": "", "curated": False,
              "post_lines": ""}
    table = Table(str(input.get("workato_api_token") or "").strip())
    key = str(input.get("azure_api_key") or "").strip()
    llm = Azure(key, input.get("azure_url")) if key else None
    try:
        _run(input, result, table, llm)
    except Exception as error:                                     # noqa: BLE001
        result["error"] = "unexpected {}: {}".format(type(error).__name__, str(error)[:300])
    result["ok"] = not result["error"]
    result["rows_written"] = table.written
    result["llm_calls"] = llm.calls if llm else 0
    result["warnings"] += table.errors + (llm.errors if llm else [])
    return result


def _run(input, result, table, llm):
    testing, approve = _flag(input.get("testing")), _flag(input.get("approve"))
    title = clip(tidy(input.get("story_title")), TEXT_LIMITS["title"])
    kb = clip(tidy(input.get("kb_name")), TEXT_LIMITS["kb"])
    author = clip(tidy(input.get("story_author")), TEXT_LIMITS["author"])
    theme = clean_theme(input.get("theme"))
    why = clip(tidy(input.get("why_it_resonates")), TEXT_LIMITS["why"])
    main_character = clip(tidy(input.get("main_character")), TEXT_LIMITS["main"])
    lesson = clip(tidy(input.get("lesson")), TEXT_LIMITS["lesson"])
    text = re.sub(r"\n{3,}", "\n\n", str(input.get("story_text") or "").replace("\r\n", "\n")
                  .replace("\r", "\n")).strip()
    genie = clip(tidy(input.get("genie_name")), TEXT_LIMITS["genie"])
    conversation = clip(tidy(input.get("conversation_id")), TEXT_LIMITS["conversation"])
    result.update({"story_title": title, "story_title_original": title, "kb_name": kb,
                   "story_author": author, "theme": theme, "genie_name": genie,
                   "conversation_id": conversation, "words": count_words(text),
                   "words_original": count_words(text)})

    def refuse(reasons):
        result["problems"] = list(reasons)
        result["retry"], result["retry_reason"] = True, "; ".join(reasons)
        result["error"] = "the story cannot be used: " + result["retry_reason"]

    problems = ["{} is empty".format(name) for name, value in (
        ("story_title", title), ("kb_name", kb), ("theme", theme), ("story_text", text)) if not value]
    if text and result["words"] < MIN_STORY_WORDS:
        problems.append("the story is only {} words, too short (choose one of 400 to 1,500 "
                        "words)".format(result["words"]))
    if len(text) > MAX_ORIGINAL_CHARS:
        problems.append("the story is {:,} characters, too long (choose one of 400 to 1,500 "
                        "words)".format(len(text)))
    if problems:
        return refuse(problems)
    if not testing and not table.token:
        result["error"] = "workato_api_token is required (or set testing to yes)"
        return
    skip_clean = _flag(input.get("skip_clean"))
    if llm is None and not skip_clean:
        result["error"] = "azure_api_key is required: Azure cleans the story (or set skip_clean to yes)"
        return

    today = local_today(_int(input.get("tz_offset"), DEFAULT_TZ_OFFSET, -86400, 86400),
                        input.get("today"))
    asked = str(input.get("week") or "").strip()
    week = (monday_of(local_today(0, asked)) if asked else week_for_story(today)).isoformat()
    result["week"] = week

    existing, rows = None, None
    if table.token:
        rows = table.stories()
        if rows is None:
            result["error"] = "could not read the stories, so nothing was stored"
            return
        existing = next((r for r in rows if r.get("week_key") == week), None)
        used = [r for r in rows if (r.get("name") or "").strip().lower() == title.lower()
                and r.get("week_key") != week]
        if used and not approve:
            return refuse(["\"{}\" was already used (week of {})".format(title, used[0].get("week_key"))])
        if existing and existing.get("status") in (OPEN, DONE):
            if not testing:
                result["error"] = ("the story for the week of {} has already started ({}), so it cannot "
                                   "be replaced".format(week, existing.get("status")))
                return
            # A test writes nothing, so it may look at a week that has started; a real run may not.
            result["warnings"].append("the week of {} has already started ({}): a real run would be "
                                      "refused. Test on another week (week = ...) or restart this one "
                                      "first".format(week, existing.get("status")))
    else:
        result["warnings"].append("no table token: not checked against earlier stories")

    original = {"title": title, "text": text}
    adapted, changes, teaser = False, "", None
    if not skip_clean:
        given = {"title": title, "theme": theme, "main": main_character, "lesson": lesson, "why": why}
        clean, bad = clean_story(llm, given, text, _int(input.get("clean_attempts"), CLEAN_ATTEMPTS, 1, 6),
                                 _int(input.get("story_words"), STORY_WORDS_DEFAULT, *STORY_WORDS_BOUNDS))
        if bad == ["Azure gave no answer"]:
            result["error"] = "Azure did not answer, so the story was not cleaned or stored"
            return
        if bad and not (clean and approve):
            return refuse(["it could not be cleaned: " + "; ".join(bad[:3])])
        title, text, adapted, changes = clean["title"] or title, clean["text"], True, clean["changes"]
        why, lesson, teaser = clean["why"] or why, clean["lesson"] or lesson, clean["teaser"]
        result.update({"story_title": title, "words": count_words(text), "cleaned": True,
                       "changes": changes})
        again = [r for r in (rows or []) if (r.get("name") or "").strip().lower() == title.lower()
                 and r.get("week_key") != week] if table.token else []
        if again and not approve:
            return refuse(["\"{}\" was already used (week of {})".format(title, again[0].get("week_key"))])
    hits = story_flags(title, why, lesson, main_character, text)
    result["flagged"] = hits
    if hits and not approve:
        return refuse(["it contains words that do not belong in a global workplace story "
                       "(violence, religion, abuse and the like): " + ", ".join(hits)])
    local = regional_notes(text)
    if local:
        result["warnings"].append("worth a read before Monday: it names money or years ({}), so it "
                                  "may not read as global".format(", ".join(local)))

    # The Sunday post: built from what is stored, so it is the story as it will run.
    view, post_lines = None, None
    if str(input.get("announce") or "yes").strip().lower() not in ("no", "false", "0", "off"):
        # The teaser, never the genie's why: that one says how the story turns out.
        shown = {"title": title, "theme": theme, "kb": kb, "author": author, "adapted": adapted,
                 "why": teaser or ""}
        wrap, banner = _wrap_input(input, result), str(input.get("banner") or "").strip()
        if llm is not None and str(input.get("curate") or "yes").strip().lower() not in (
                "no", "false", "0", "off"):
            post_lines, why_not = curate_announcement(
                llm, title, theme, text, teaser, recent_announcements(rows, week))
            if post_lines:
                view = announce_view(shown, week, "Monday", wrap, banner, post_lines)
                if view["seconds"] > MAX_POST_SECONDS:
                    result["warnings"].append("the written Sunday post would read in {} seconds; the "
                                              "standard wording is used".format(view["seconds"]))
                    post_lines, view = None, None
            else:
                result["warnings"].append("the Sunday post uses the standard wording: " + "; ".join(why_not[:2]))
        view = view or announce_view(shown, week, "Monday", wrap, banner)
        result["curated"] = bool(post_lines)
        result["post_lines"] = json.dumps(post_lines, ensure_ascii=False) if post_lines else ""
        problems = block_problems(view["blocks"])
        if problems:
            result["warnings"].append("the Sunday post does not fit Slack's limits: " + "; ".join(problems))
            view = None
        else:
            result.update({"text": view["text"], "read_seconds": view["seconds"],
                           "blocks_json": json.dumps(view["blocks"], ensure_ascii=False),
                           "preview_url": preview_url(view["blocks"])})
    already = bool(existing and existing.get("scheduled_time")
                   and (existing.get("name") or "").strip().lower() == title.lower())

    fields = {"record_key": "{}_{}".format(STORY_ROW, week), "row_type": STORY_ROW, "id": week,
              "name": title, "topic_name": theme, "kb_tag": kb, "week_key": week, "status": NEW,
              "description": text, "group_name": genie, "group_id": conversation,
              "content": raw_json(author, why, main_character, lesson, adapted, changes, original, teaser,
                                  post_lines),
              "created_at": today.isoformat(), "updated_at": today.isoformat(),
              "slack_channel_id": str(input.get("channel") or "").strip(),
              # kept when the same story is stored again; a different story has not been announced
              "scheduled_time": existing.get("scheduled_time") if already else ""}
    result["status"] = NEW
    if testing:
        result["warnings"].append("testing: nothing was written or posted")
        return
    token, channel = str(input.get("slack_bot_token") or "").strip(), fields["slack_channel_id"]
    posted = ""
    if view and already:
        result["warnings"].append("this story was already announced; not posted again")
    elif view and token and channel:
        posted, error = slack_post(token, channel, view["text"], view["blocks"])
        if error:
            result["warnings"].append("the Sunday post did not go (the story is stored anyway): " + error)
        else:
            fields["scheduled_time"] = posted
    elif view:
        result["warnings"].append("the Sunday post was not sent: slack_bot_token and channel are needed")
    result["replaced"] = bool(existing)
    if not table.write(existing, fields):
        result["error"] = "the table refused the story"
        if posted:
            slack_delete(token, channel, posted)        # nothing is announced that was not kept
        return
    result["saved"] = True
    if posted:
        result.update({"announced": True, "message_ts": posted})
        old = (existing or {}).get("scheduled_time")
        if old and not already:
            slack_delete(token, channel, old)           # the post about the story it replaced


if __name__ == "__main__":
    print(json.dumps(main({
        "testing": "yes", "story_title": "Example", "kb_name": "Example KB", "theme": "kindness",
        "story_text": " ".join(["A sentence about a kind act."] * 40),
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", "")}), indent=2))
