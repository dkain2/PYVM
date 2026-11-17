"""
Genie Responder -- answer Slack questions with the master genie.

ONE PYTHON STEP, TWO CALLS PER QUESTION (plus one when someone rates the answer)
    action = "ask"    (the Slack message trigger)
        Is this message for a genie? If so, post a "thinking" message in the
        thread (with a plan block: read your question, picked the genie, looking
        into it, write the answer) and return everything "Assign task to genie"
        needs: the genie handle, the task text, and the thread's conversation_id
        if the genie has already been talking in this thread.
    -- the recipe runs "Assign task to genie" and waits for the answer --
    action = "reply"  (right after the genie answers)
        Turn the answer into a Slack attachment, edit the thinking message
        into it, and save the conversation_id against the thread so the next
        question in the thread continues the same conversation.
    action = "feedback"  (the app's Interactivity URL, when someone clicks Good / Bad)
        Every answer ends with Good response / Bad response buttons. Slack sends a
        click to the app's Interactivity Request URL as a block_actions payload; the
        recipe behind that URL calls this step with `payload` (the payload JSON, or
        just user_id / channel / message_ts / thread_ts / feedback_value) and the
        rating is saved as a genie_feedback row in the genie_console table:
            record_key = fb:<channel>:<message_ts>:<user>   (a changed vote updates it)
            id = the answer's message_ts, status = positive | negative,
            creator_id = who clicked, invoke_keyword / genie_name / persona = the
            genie of that thread.
        Outputs: feedback_saved, feedback_value.

HOW A MESSAGE IS MATCHED (ask)
    1. Messages from bots, edits and deletes are skipped -- a genie's own reply
       that mentions its keyword must never trigger it again.
    2. One query: every row with status = active in THIS channel. Keywords are
       per channel, and a draft or cancelled setup can never answer.
    3. Each keyword is matched as a whole word, case-insensitive: "SNAP why..."
       matches, "snapshot" and "genieconfig" do not. When several keywords
       appear, the one that comes first wins.
    4. Inside a thread the genie is already answering, a follow-up needs no
       keyword (FOLLOWUP_WITHOUT_KEYWORD).
    5. The keyword is cut out; what is left is the question.

CONVERSATIONS
    Stored in the genie_console table as their own rows:
        record_type = genie_conversation
        record_key  = conv:<channel>:<thread_ts>
        id          = the genie's conversation_id
        invoke_keyword / genie_name / persona: which genie the thread belongs to
        setup_thread_ts = the thread, creator_id = who started it

THE ANSWER CARD (reply)
    Everything is an attachment with a calm colour per persona. The genie's
    markdown is converted to Slack mrkdwn (headings, bold, bullets, links) and split
    into sections of under 3,000 characters at paragraph breaks, never inside a code
    block. The first table in an answer is a native Slack table block (TABLE_STYLE);
    further tables, a table over Slack's limits, or a message Slack rejects use a text
    table drawn with box characters in a code block, wrapped to BOX_WIDTH.

WHAT THE GENIE IS FOR
    The row's genie_purpose (edited from the console's Manage card) is sent in the genie_context
    as genie_purpose on every question, so changing it needs no change to the genie itself.

WHO IS ASKING
    The Slack user who wrote the message is looked up (users.info) and sent in the
    genie_context as asker_slack_id / asker_name / asker_email, with a note telling
    the genie to check its knowledge base for any rule about that person. A rule
    such as "don't answer <name or email>" in a knowledge base can then be applied.
    It is advice to the model, not a block: nothing here stops the genie answering.

WHEN THE GENIE CAN'T ANSWER
    Every task carries a note (ESCALATE_NOTE): if the genie cannot answer from its skills,
    its analyst skill or its knowledge base, it ends its reply with [[NEEDS_HUMAN]] (or
    [[NEEDS_HUMAN: <project name>]]). reply() removes the marker from the card and then
    posts a plain message in the thread that tags the project owner(s) stored on the
    genie's row (workato_projects[].owner.mention): "can you help?". Python does the
    tagging, not the model, so the tag is exactly the stored Slack mention. The same
    message is posted when the genie itself failed or sent nothing back. Each owner also
    gets a direct message from the app with the same facts and a link to the thread
    (owner_dm_text), so they hear about it even if they aren't watching the channel.

WHEN SOMEONE IS NOT ALLOWED TO TALK TO THE GENIE
    When a rule in the genie's knowledge base says not to answer the asker, the genie
    replies "I can't help with that here." followed by [[BLOCKED]] (see ASKER_NOTE). A reply
    that is just that sentence counts too, since the marker is often left off.
    reply() removes the marker and shows only the short refusal: nothing more is posted in
    the thread. The project owner(s) are told by direct message who tried to use the genie
    and what they asked.

The task text format (<genie_context> / <question>) is the one the master
genie's job description expects (master_genie_job_description.md).

Input and output schemas: genie_responder_input_schema.json /
genie_responder_output_schema.json
"""

import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Endpoints and limits
# --------------------------------------------------------------------------

TABLE_ID = "6d53d2dd-c00d-4130-aa1c-b0cbfdcc484c"            # genie_console
TABLE_QUERY_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
TABLE_RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
TABLE_RECORD_URL = TABLE_RECORDS_URL + "/{}"
SLACK_API = "https://slack.com/api/"
HTTP_TIMEOUT = 30

SECTION_LIMIT = 2900             # Slack rejects section text over 3,000 characters
MAX_SECTIONS = 40                # an attachment holds at most 50 blocks
FOLLOWUP_WITHOUT_KEYWORD = True  # a reply in the genie's thread needs no keyword

# Tables. "native" sends a real Slack table block (bold header, wrapping cells, code and
# links inside cells); "text" always draws the box-character table in a code block. Slack
# allows one table block per message and 10,000 characters in it: anything beyond that, or
# a message Slack rejects, falls back to the text table by itself.
TABLE_STYLE = "native"
MAX_NATIVE_TABLES = 1
NATIVE_TABLE_ROWS = 100
NATIVE_TABLE_COLUMNS = 20
NATIVE_TABLE_CHARS = 9000
BOX_WIDTH = 60                   # text table: widest line, in characters (a code block wraps past ~62)
BOX_MIN_COLUMN = 8               # text table: a column is never squeezed narrower than this

# Thinking plan and feedback buttons. Both are newer Slack blocks: if Slack rejects the
# message the responder sends it again without them (see post_thinking and reply).
SHOW_PLAN = True                 # the "thinking" message shows a plan: what is done, what is next
FEEDBACK_BUTTONS = True          # good / bad response buttons under every answer
FEEDBACK_ACTION_ID = "genie_feedback"
FEEDBACK_VALUES = ("positive", "negative")

GENIE_TYPE = "channel_genie"
CONVERSATION_TYPE = "genie_conversation"
FEEDBACK_TYPE = "genie_feedback"
STATUS_ACTIVE = "active"

# Slack message subtypes that are never a question to answer.
IGNORED_SUBTYPES = {"bot_message", "message_changed", "message_deleted",
                    "channel_join", "channel_leave", "thread_broadcast"}

# Used only when a row has no system_prompt (set up before that column existed).
FALLBACK_PROMPT = ("Answer as a helpful assistant for these integrations, in the "
                   "style of the {} persona.")

# Writes go to columns by field UUID. These are the columns a conversation row
# uses; they must match genie_console.py's COLUMNS.
COLUMNS = {
    "record_type":     "f7253c35-2566-411e-9e60-c273e271d0db",
    "record_key":      "a68f2119-5168-4cca-b28c-f25b8d998ea3",
    "id":              "434caf4f-8243-42e3-8ec8-d0732829458e",
    "status":          "6b76da26-90e4-42ef-a556-e376ed6fbd8f",
    "channel":         "910af0ed-f992-4707-a509-be760593b203",
    "genie_name":      "c294a065-0718-4211-8b95-a07f8923881e",
    "persona":         "6e2cf0fc-bbaf-47f4-8f69-4521d6a4e1f9",
    "invoke_keyword":  "e11379fd-9f0e-4462-b591-628601c7acc3",
    "creator_id":      "7791d979-e9ea-407b-9e19-dab7facce631",
    "created_at":      "1be76181-05f8-4134-b410-455fceebbb7f",
    "setup_thread_ts": "00f5e6dc-d335-48b0-96bf-d19312aadad8",
    "updated_at":      "8f9aa1b3-3674-40f6-81f9-b189fc04ebd7",
}

# --------------------------------------------------------------------------
# Look and feel: calm colours, one per persona, so long answers stay easy to read
# --------------------------------------------------------------------------

PERSONA_COLORS = {
    "support":   "#6B8FB3",   # steel blue
    "analyst":   "#6FA3A0",   # muted teal
    "business":  "#8DAA91",   # sage
    "developer": "#7D8BA6",   # slate
    "auditor":   "#B8A47E",   # soft sand
}
COLOR_DEFAULT = "#7D8BA6"
COLOR_THINKING = "#A0AEC0"     # soft grey
COLOR_ERROR = "#C48B8B"        # muted rose
COLOR_HELLO = "#9DB4A3"        # pale sage

PERSONA_LABELS = {"support": "Support", "analyst": "Analyst", "business": "Business guide",
                  "developer": "Developer", "auditor": "Auditor"}
LOADING_EMOJI = ":loading-2:"
DIVIDER_MARK = "\x00divider\x00"   # stands in for a markdown rule until blocks are built
TABLE_MARK = "\x00table:{}\x00"    # stands in for a native table until blocks are built
TABLE_MARK_RE = re.compile(r"\x00table:(\d+)\x00")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _request(url, headers, payload=None, method="GET"):
    """Returns (body, error). Never raises."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            return (json.loads(raw) if raw else {}), None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {} {}: {}".format(error.code, method,
                                                url.split("/")[2], detail)
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


# --------------------------------------------------------------------------
# Data table
# --------------------------------------------------------------------------

class Table(object):
    def __init__(self, token, dry_run=False):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.dry_run = dry_run

    def query(self, where, limit=200):
        """(rows, error). Rows are keyed by column name, with $record_id."""
        body, error = _request(TABLE_QUERY_URL, self.headers,
                               {"where": where, "limit": limit}, "POST")
        if error:
            return [], "table.query " + error
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        return [dict(zip(columns, [v for group in row for v in group]))
                for row in body.get("data", [])], None

    def save(self, row, fields):
        """Create when row is None, otherwise update it. Returns an error or None."""
        if self.dry_run:
            return None
        document = {"$" + COLUMNS[k]: v for k, v in fields.items() if COLUMNS.get(k)}
        if row and row.get("$record_id"):
            _body, error = _request(TABLE_RECORD_URL.format(row["$record_id"]),
                                    self.headers, {"document": document}, "PUT")
        else:
            _body, error = _request(TABLE_RECORDS_URL, self.headers,
                                    {"document": document}, "POST")
        return ("table.save " + error) if error else None


def conversation_key(channel, thread_ts):
    return "conv:{}:{}".format(channel, thread_ts)


# --------------------------------------------------------------------------
# Slack
# --------------------------------------------------------------------------

class Slack(object):
    def __init__(self, token, dry_run=False):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json; charset=utf-8"}
        self.token = token
        self.dry_run = dry_run
        self.errors = []
        self.last = {}

    def _call(self, method, payload):
        self.last = payload
        if self.dry_run:
            return {"ok": True, "ts": "dry-run"}
        if not self.token:
            self.errors.append("slack_bot_token is empty")
            return None
        body, error = _request(SLACK_API + method, self.headers, payload, "POST")
        if error:
            self.errors.append("slack.{} {}".format(method, error))
            return None
        if not body.get("ok"):
            self.errors.append("slack.{}: {}".format(method, body.get("error")))
            return None
        return body

    def _get(self, method, params):
        """A Slack read method. These take their arguments in the query string (or as
        form fields), not as a JSON body: sent as JSON, users.info says user_not_found."""
        self.last = params
        if self.dry_run:
            return {"ok": True}
        if not self.token:
            self.errors.append("slack_bot_token is empty")
            return None
        body, error = _request(SLACK_API + method + "?" + urllib.parse.urlencode(params),
                               self.headers)
        if error:
            self.errors.append("slack.{} {}".format(method, error))
            return None
        if not body.get("ok"):
            self.errors.append("slack.{}: {}".format(method, body.get("error")))
            return None
        return body

    # No top-level `text` is sent with an attachment: Slack shows it above the
    # card as a plain line ("SNAP is thinking...", or the answer twice). The
    # attachment's `fallback` is what notifications use instead.

    def post(self, channel, thread_ts, attachments):
        body = self._call("chat.postMessage", {"channel": channel, "thread_ts": thread_ts,
                                               "attachments": attachments})
        return (body or {}).get("ts") or ""

    def update(self, channel, ts, attachments):
        """Replaces the whole message: text and blocks cleared, attachments set."""
        return bool(self._call("chat.update", {"channel": channel, "ts": ts, "text": "",
                                               "blocks": [], "attachments": attachments}))

    def say(self, channel, thread_ts, text):
        """A plain text message in the thread (not an attachment): the one that notifies
        the people tagged in it."""
        body = self._call("chat.postMessage", {"channel": channel, "thread_ts": thread_ts,
                                               "text": text})
        return (body or {}).get("ts") or ""

    def dm(self, user_id, text):
        """A direct message from the app to a user (chat.postMessage with the user's ID as
        the channel opens the app's DM with them). True when it was sent."""
        return bool(self._call("chat.postMessage", {"channel": user_id, "text": text}))

    def permalink(self, channel, message_ts):
        """The link to one message ("" when Slack won't give it)."""
        if not (channel and message_ts):
            return ""
        body = self._get("chat.getPermalink", {"channel": channel, "message_ts": message_ts})
        return (body or {}).get("permalink") or ""

    def user(self, user_id):
        """{id, name, email} of a Slack user, "" for what Slack doesn't give (it needs the
        users:read and users:read.email scopes). A failure is only a warning: the question
        is still answered, without the asker."""
        body = self._get("users.info", {"user": user_id}) if user_id else None
        user = (body or {}).get("user") or {}
        profile = user.get("profile") or {}
        name = (profile.get("real_name") or user.get("real_name")
                or profile.get("display_name") or user.get("name") or "")
        return {"id": user_id, "name": name, "email": profile.get("email") or ""}


# --------------------------------------------------------------------------
# Markdown -> Slack mrkdwn
# --------------------------------------------------------------------------

def _inline(text):
    """Bold, strike and links, outside `inline code` only."""
    parts = text.split("`")
    for i in range(0, len(parts), 2):
        part = parts[i]
        part = re.sub(r"\*\*(.+?)\*\*", r"*\1*", part)
        part = re.sub(r"__(.+?)__", r"*\1*", part)
        part = re.sub(r"~~(.+?)~~", r"~\1~", part)
        # Link text may itself hold brackets: recipe names like "[FIN] - ...".
        part = re.sub(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\((https?://[^)\s]+)\)",
                      lambda m: "<{}|{}>".format(m.group(2), m.group(1).replace("|", "/")),
                      part)
        parts[i] = part
    return "`".join(parts)


# --- tables ---------------------------------------------------------------

CELL_TOKEN = re.compile(r"`[^`]+`|\*\*[^*]+?\*\*|\[[^\]]+\]\(https?://[^)\s]+\)|\*[^*\s][^*]*\*")
CELL_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _rich_elements(text, bold=False):
    """A cell's markdown (`code`, **bold**, *italic*, [link](url)) as rich_text elements."""
    elements = []

    def add(piece, **style):
        if bold:
            style["bold"] = True
        element = {"type": "text", "text": piece}
        if style:
            element["style"] = style
        elements.append(element)

    position = 0
    for match in CELL_TOKEN.finditer(text):
        if match.start() > position:
            add(text[position:match.start()])
        token = match.group(0)
        if token.startswith("`"):
            add(token[1:-1], code=True)
        elif token.startswith("**"):
            add(token[2:-2], bold=True)
        elif token.startswith("["):
            label, url = CELL_LINK.match(token).groups()
            element = {"type": "link", "url": url, "text": label}
            if bold:
                element["style"] = {"bold": True}
            elements.append(element)
        else:
            add(token[1:-1], italic=True)
        position = match.end()
    if position < len(text):
        add(text[position:])
    return elements


def _native_cell(text, header=False):
    text = text.strip()
    if not text:
        return {"type": "raw_text", "text": " "}           # a cell may not be empty
    if not header and not CELL_TOKEN.search(text):
        return {"type": "raw_text", "text": text}
    return {"type": "rich_text", "elements": [
        {"type": "rich_text_section", "elements": _rich_elements(text, bold=header)}]}


def _native_table(rows):
    """A Slack table block: bold header row, cells that wrap instead of being cut off.
    column_settings has one real object per column (null entries make Slack reject it)."""
    columns = len(rows[0])
    body = [[_native_cell(row[i] if i < len(row) else "", header=(n == 0))
             for i in range(columns)] for n, row in enumerate(rows)]
    return {"type": "table", "rows": body,
            "column_settings": [{"align": "left", "is_wrapped": True} for _ in range(columns)]}


def _plain_cell(text):
    """A cell as plain text for the code block, where markdown marks would show as is."""
    text = CELL_LINK.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("~~", "").replace("`", "")
    return re.sub(r"^\*(\S.*?)\*$", r"\1", text.strip())


def _text_table(rows):
    """A table drawn with box characters, for a code block: every line the same width,
    never wider than BOX_WIDTH (long cells wrap onto extra lines), a double rule under the
    header and a rule between rows."""
    columns = max(len(row) for row in rows)
    cells = [[_plain_cell(row[i]) if i < len(row) else "" for i in range(columns)]
             for row in rows]
    widths = [max(len(row[i]) for row in cells) or 1 for i in range(columns)]
    room = BOX_WIDTH - (3 * columns + 1)                    # borders and one space each side
    while sum(widths) > room:
        widest = max(range(columns), key=lambda i: widths[i])
        if widths[widest] <= BOX_MIN_COLUMN:
            break
        widths[widest] -= 1

    def rule(left, middle, right, fill="\u2500"):
        return left + middle.join(fill * (w + 2) for w in widths) + right

    lines = [rule("\u250c", "\u252c", "\u2510")]
    for n, row in enumerate(cells):
        wrapped = [textwrap.wrap(c, widths[i], break_long_words=True,
                                 break_on_hyphens=False) or [""] for i, c in enumerate(row)]
        for k in range(max(len(w) for w in wrapped)):
            lines.append("\u2502" + "\u2502".join(
                " " + (w[k] if k < len(w) else "").ljust(widths[i]) + " "
                for i, w in enumerate(wrapped)) + "\u2502")
        if n == len(cells) - 1:
            lines.append(rule("\u2514", "\u2534", "\u2518"))
        elif n == 0:
            lines.append(rule("\u255e", "\u256a", "\u2561", "\u2550"))
        else:
            lines.append(rule("\u251c", "\u253c", "\u2524"))
    return "```" + "\n".join(lines) + "```"


def to_mrkdwn(markdown, tables=None):
    """What a model writes -> what Slack renders. Code blocks are left alone.
    Markdown tables become a text table in a code block, or, when `tables` is a list, a
    native Slack table: its block is appended to `tables` and a marker (TABLE_MARK) is left
    in the text for answer_attachments to swap for the block."""
    out, table, in_fence = [], [], False

    def flush_table():
        if not table:
            return
        rows = [[cell.strip() for cell in r.strip().strip("|").split("|")]
                for r in table if not re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", r)]
        del table[:]
        if not rows:
            return
        columns = max(len(row) for row in rows)
        size = sum(len(cell) for row in rows for cell in row)
        if (tables is not None and TABLE_STYLE == "native" and len(rows) > 1
                and len(tables) < MAX_NATIVE_TABLES and len(rows) <= NATIVE_TABLE_ROWS
                and columns <= NATIVE_TABLE_COLUMNS and size <= NATIVE_TABLE_CHARS):
            out.append(TABLE_MARK.format(len(tables)))
            tables.append(_native_table([row + [""] * (columns - len(row)) for row in rows]))
        else:
            out.append(_text_table(rows))

    for line in (markdown or "").replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            flush_table()
            in_fence = not in_fence
            out.append("```")                    # Slack ignores a language tag
            continue
        if in_fence:
            out.append(line)
            continue
        if re.match(r"^\s*\|.*\|\s*$", line):
            table.append(line)
            continue
        flush_table()
        if re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):    # ---, ***, ___
            out.append(DIVIDER_MARK)
            continue
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
        if heading:
            out.append("*{}*".format(heading.group(1).replace("**", "").replace("*", "")))
            continue
        line = re.sub(r"^(\s*)[-*+]\s+", "\\1\u2022 ", line)
        out.append(_inline(line))
    flush_table()
    if in_fence:
        out.append("```")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def split_sections(text, limit=SECTION_LIMIT):
    """Pieces under `limit`, cut at blank lines and never inside a code block.
    A single paragraph that is still too long is cut at line breaks; a cut
    code block is closed and reopened so each piece renders on its own."""
    units, current, in_fence = [], [], False
    for line in text.split("\n"):
        if line.count("```") % 2:                # an odd count opens or closes a block
            in_fence = not in_fence
        current.append(line)
        if not line.strip() and not in_fence:
            units.append("\n".join(current).strip())
            current = []
    if current:
        units.append("\n".join(current).strip())

    pieces = []
    for unit in filter(None, units):
        if len(unit) <= limit:
            pieces.append(unit)
            continue
        fenced = unit.startswith("```") and unit.endswith("```")
        body = unit[3:-3] if fenced else unit
        chunk = ""
        for line in body.split("\n"):
            while len(line) > limit - 10:                 # one enormous line
                pieces.append(("```{}```" if fenced else "{}").format(line[:limit - 10]))
                line = line[limit - 10:]
            if len(chunk) + len(line) + 1 > limit - 10:
                pieces.append(("```{}```" if fenced else "{}").format(chunk.strip("\n")))
                chunk = ""
            chunk += line + "\n"
        if chunk.strip():
            pieces.append(("```{}```" if fenced else "{}").format(chunk.strip("\n")))

    merged = []
    for piece in pieces:                                   # pack small pieces together
        if merged and len(merged[-1]) + len(piece) + 2 <= limit:
            merged[-1] += "\n\n" + piece
        else:
            merged.append(piece)
    return merged


# --------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------

def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _section(text):
    # expand: without it Slack folds a long section behind "Show more".
    return {"type": "section", "expand": True, "text": {"type": "mrkdwn", "text": text}}


def _who(genie_name, persona):
    label = PERSONA_LABELS.get(persona, persona or "")
    return "*{}*{}".format(genie_name or "Genie", "  \u00b7  " + label if label else "")


def _rich_text(text):
    return {"type": "rich_text", "elements": [
        {"type": "rich_text_section", "elements": [{"type": "text", "text": text}]}]}


def plan_block(genie_name, persona, question=""):
    """The plan shown while the genie works. Only steps that really happen: the message was
    read and the genie picked before this is posted, then the genie works, then the answer
    replaces this message."""
    label = PERSONA_LABELS.get(persona, persona or "")
    asked = _one_line(question, 140)
    read = {"task_id": "read", "title": "Read your question", "status": "complete"}
    if asked:
        read["details"] = _rich_text("“{}”".format(asked))
    picked = {"task_id": "pick", "title": "Picked {}".format(genie_name or "a genie"),
              "status": "complete"}
    if label:
        picked["details"] = _rich_text(label)
    return {"type": "plan", "title": "{} is working on it".format(genie_name or "The genie"),
            "tasks": [read, picked,
                      {"task_id": "work", "title": "Looking into it", "status": "in_progress"},
                      {"task_id": "write", "title": "Write the answer", "status": "pending"}]}


def feedback_block():
    """Good / bad response buttons. A click is sent to the app's Interactivity URL as a
    block_actions payload; the recipe for it calls this step with action = feedback."""
    return {"type": "context_actions", "elements": [{
        "type": "feedback_buttons", "action_id": FEEDBACK_ACTION_ID,
        "positive_button": {"text": {"type": "plain_text", "text": "Good response"},
                            "value": FEEDBACK_VALUES[0]},
        "negative_button": {"text": {"type": "plain_text", "text": "Bad response"},
                            "value": FEEDBACK_VALUES[1]}}]}


def thinking_attachments(genie_name, persona, question="", plan=True):
    blocks = [_context("{}  is looking into it {}".format(
        _who(genie_name, persona), LOADING_EMOJI))]
    if plan and SHOW_PLAN:
        blocks.append(plan_block(genie_name, persona, question))
    return [{"color": COLOR_THINKING, "fallback": "{} is thinking".format(genie_name),
             "blocks": blocks}]


def post_thinking(slack, result, question):
    """Posts the thinking message (with its plan) in the thread and puts its ts in
    result["thinking_ts"]. If Slack rejects the plan, posts the plain message instead."""
    name, persona = result["genie_name"], result["persona"]
    errors_before = len(slack.errors)
    ts = slack.post(result["channel"], result["reply_thread_ts"],
                    thinking_attachments(name, persona, question))
    if not ts and SHOW_PLAN:
        del slack.errors[errors_before:]
        result["warnings"].append("plan block rejected by Slack: posted the plain thinking message")
        ts = slack.post(result["channel"], result["reply_thread_ts"],
                        thinking_attachments(name, persona, plan=False))
    result["thinking_ts"] = ts


def hello_attachments(genie_name, persona, keyword, projects):
    names = ", ".join(p.get("name") or str(p.get("id")) for p in projects) or "this project"
    return [{"color": COLOR_HELLO, "fallback": "Ask {} a question".format(genie_name),
             "blocks": [_context(_who(genie_name, persona)),
                        _section("Hi! Ask me anything about *{}*.\nFor example: `{} why did "
                                 "quote Q-123 not sync to NetSuite?`".format(names, keyword))]}]


def has_table_block(attachments):
    return any(b.get("type") == "table" for a in attachments for b in a.get("blocks", []))


def answer_attachments(genie_name, persona, answer, asked_by="", native=True, feedback=True):
    # A markdown rule (---) becomes a real divider between sections; a markdown table
    # becomes a native table block (native=False: a text table in a code block).
    body, used, cut = [], 0, False
    tables = [] if native and TABLE_STYLE == "native" else None
    for part in to_mrkdwn(answer, tables).split(DIVIDER_MARK):
        pieces = TABLE_MARK_RE.split(part)           # text, table number, text, ...
        for n, piece in enumerate(pieces):
            if n % 2:
                body.append(tables[int(piece)])
                continue
            for section in split_sections(piece.strip()):
                if used >= MAX_SECTIONS:
                    cut = True
                    break
                body.append(_section(section))
                used += 1
        body.append({"type": "divider"})
    while body and body[-1]["type"] == "divider":
        body.pop()
    while body and body[0]["type"] == "divider":
        body.pop(0)
    blocks = [_context(_who(genie_name, persona))] + body
    if cut:
        blocks.append(_context("_The answer was too long for one message and was cut "
                               "short. Ask a narrower question for the rest._"))
    footer = "Reply in this thread to follow up"
    if asked_by:
        footer = "Asked by <@{}>  \u00b7  {}".format(asked_by, footer)
    blocks.append(_context(footer))
    if feedback and FEEDBACK_BUTTONS:
        blocks.append(feedback_block())
    return [{"color": PERSONA_COLORS.get(persona, COLOR_DEFAULT),
             "fallback": (answer or "")[:150], "blocks": blocks}]


def error_attachments(genie_name, persona, error):
    return [{"color": COLOR_ERROR, "fallback": "{} could not answer".format(genie_name),
             "blocks": [_context(_who(genie_name, persona)),
                        _section("Sorry, I couldn't answer that one. Please try again in a "
                                 "minute, or ask the IT Integrations team.\n"
                                 "```{}```".format((error or "no answer came back")[:500]))]}]


# --------------------------------------------------------------------------
# ask: match the message, post thinking
# --------------------------------------------------------------------------

def find_keyword(text, rows):
    """(row, match) for the keyword that appears first in the text, as a whole
    word. Longest keyword wins a tie, so "SNAP2" is not read as "SNAP"."""
    best = None
    for row in rows:
        keyword = (row.get("invoke_keyword") or "").strip()
        if not keyword:
            continue
        match = re.search(r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])".format(re.escape(keyword)),
                          text, re.IGNORECASE)
        if match and (best is None or (match.start(), -len(keyword))
                      < (best[1].start(), -len(best[1].group(0)))):
            best = (row, match)
    return best or (None, None)


def question_from(text, match):
    """The message with the keyword cut out, and the punctuation that usually
    follows it ("SNAP: ...", "hey snap, ...") tidied away."""
    if match is None:
        return re.sub(r"\s{2,}", " ", text).strip()
    rest = re.sub(r"^\s*[:,\-\u2013\u2014]+", "", text[match.end():])
    question = text[:match.start()].rstrip() + " " + rest.lstrip()
    return re.sub(r"\s{2,}", " ", question).strip()


def _json_list(value):
    try:
        loaded = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []


ESCALATE_NOTE = ("If you cannot answer this from your skills, your analyst skill or your knowledge "
                 "base, say briefly what you could not find, then end your reply with the marker "
                 "[[NEEDS_HUMAN]] on its own line (add the project's name, as [[NEEDS_HUMAN: "
                 "project name]], when you know which project it is about). A person who owns the "
                 "project will be brought into the thread for you. Never guess an answer instead, "
                 "and do not tag anyone yourself.")

NEEDS_HUMAN = re.compile(r"\[\[\s*NEEDS_HUMAN\s*(?::\s*([^\]]*?))?\s*\]\]", re.IGNORECASE)
BLOCKED = re.compile(r"\[\[\s*BLOCKED\s*\]\]", re.IGNORECASE)
BLOCKED_ANSWER = "I can't help with that here."
SLACK_MENTION = re.compile(r"<@[UW][A-Z0-9]{2,}>")

ASKER_NOTE = ("This is the person who sent the question. If you have a knowledge base, look in "
              "it for a rule that names THIS person (their name, email or Slack ID above must be "
              "the same person the rule names). Rules about anyone else do not apply: ignore them "
              "and answer normally. Never refuse just because some rule exists. Only if a rule "
              "names this very person and says not to answer them, reply only: "
              "I can't help with that here. [[BLOCKED]]")

TONE_NOTE = ("Write like a person in a first conversation: natural, warm and direct, in your own "
             "words. Start with the answer. Never announce how you are going to explain it: no "
             "'in plain English', 'in plain terms', 'in simple terms', 'to put it simply', 'great "
             "question', 'I've looked into this' and no mention of your persona, instructions or "
             "configuration. Just say it.")


def _plain(text):
    """Letters and digits only, lower case: 'I can\u2019t help with that here.' == 'i cant help ...'"""
    return re.sub(r"[^a-z0-9]", "", str(text or "").replace("\u2019", "'").lower())


def _one_line(value, limit=120):
    """Text from a person's Slack profile as one plain line: it goes into the genie's
    configuration, so it must not be able to open a tag or start a new line of instructions."""
    text = " ".join(str(value or "").replace("<", " ").replace(">", " ").split())
    return text[:limit]


def task_instructions(row, question, asker=None):
    """The task for the master genie, in the shape its job description expects. asker
    ({id, name, email}, from Slack) says who is asking, so a rule in the genie's knowledge
    base about a person can be applied."""
    persona = row.get("persona") or ""
    lines = [
        "<genie_context>",
        "persona: " + persona,
        "persona_instructions: " + ((row.get("system_prompt") or "").strip()
                                    or FALLBACK_PROMPT.format(persona)),
        "genie_name: " + (row.get("genie_name") or ""),
        "channel: " + (row.get("channel") or ""),
    ]
    # What the team says this genie is for. It lives in the table (the Manage card edits it), so
    # a change takes effect on the next question without touching the genie's instructions.
    purpose = _one_line(row.get("genie_purpose"), 1500)
    if purpose:
        lines.append("genie_purpose: " + purpose)
    asker = asker or {}
    if asker.get("id"):
        lines += ["asker_{}: {}".format(label, _one_line(asker.get(key)))
                  for label, key in (("slack_id", "id"), ("name", "name"), ("email", "email"))
                  if _one_line(asker.get(key))]
        lines.append("asker_note: " + ASKER_NOTE)
    lines.append("tone_note: " + TONE_NOTE)
    lines.append("escalation_note: " + ESCALATE_NOTE)
    for column in ("workato_projects", "recipes", "lookup_tables", "data_tables"):
        label = "projects" if column == "workato_projects" else column
        lines.append("{}: {}".format(label, json.dumps(_json_list(row.get(column)),
                                                       separators=(",", ":"))))
    lines += ["</genie_context>", "", "<question>", question, "</question>"]
    return "\n".join(lines)


def ask(input, table, slack, result):
    text = str(input.get("text") or "")
    channel = result["channel"]
    thread_ts = str(input.get("thread_ts") or "").strip()

    subtype = str(input.get("subtype") or "").strip()
    if input.get("bot_id") or subtype in IGNORED_SUBTYPES:
        result["skipped"] = "bot message, edit or delete"
        return
    if not text.strip() or not channel:
        result["skipped"] = "no text or no channel"
        return

    rows, error = table.query({"$and": [{"record_type": {"$eq": GENIE_TYPE}},
                                        {"status": {"$eq": STATUS_ACTIVE}},
                                        {"channel": {"$eq": channel}}]})
    if error:
        raise RuntimeError(error)
    result["genies_in_channel"] = len(rows)
    if not rows:
        result["skipped"] = "no active genie in this channel"
        return

    # The thread's existing conversation, if a genie is already answering here.
    # Looked up by channel + thread, so it is found whether or not the
    # follow-up repeats the keyword.
    conversation = None
    if thread_ts:
        result["conversation_key"] = conversation_key(channel, thread_ts)
        found, error = table.query({"record_key": {"$eq": result["conversation_key"]}}, limit=1)
        if error:
            raise RuntimeError(error)
        conversation = found[0] if found else None
    result["conversation_found"] = bool(conversation)
    conv_keyword = ((conversation or {}).get("invoke_keyword") or "").upper()

    row, match = find_keyword(text, rows)
    if row is None and conversation and FOLLOWUP_WITHOUT_KEYWORD:
        # No keyword: the genie that owns this thread answers. A conversation
        # saved without its keyword belongs to the channel's only genie.
        row = next((r for r in rows if (r.get("invoke_keyword") or "").upper() == conv_keyword),
                   rows[0] if len(rows) == 1 else None)
    if row is None:
        result["skipped"] = "no active genie keyword in this message"
        return

    keyword = row.get("invoke_keyword") or ""
    # The thread's conversation continues unless the message names a different
    # genie than the one that has been answering here.
    same_genie = bool(conversation) and conv_keyword in ("", keyword.upper())
    question = question_from(text, match)
    projects = _json_list(row.get("workato_projects"))
    # Who is asking goes to the genie with the question (not for a bare keyword: that
    # only says hello).
    asker = slack.user(str(input.get("user_id") or "").strip()) if question else None
    result.update({
        "matched": True,
        "is_followup": bool(same_genie),
        "conversation_id": (conversation.get("id") or "") if same_genie else "",
        "keyword": keyword,
        "record_key": row.get("record_key") or "",
        "genie_name": row.get("genie_name") or "",
        "genie_handle": row.get("id") or "",
        "persona": row.get("persona") or "",
        "system_prompt": row.get("system_prompt") or "",
        "question": question,
        "empty_question": not question,
        "task_instructions": task_instructions(row, question, asker),
        "projects_json": json.dumps(projects),
        "recipes_json": json.dumps(_json_list(row.get("recipes"))),
        "lookup_tables_json": json.dumps(_json_list(row.get("lookup_tables"))),
        "data_tables_json": json.dumps(_json_list(row.get("data_tables"))),
    })

    if not question:
        # Only the keyword was sent: say hello instead of asking the genie nothing.
        slack.post(channel, result["reply_thread_ts"],
                   hello_attachments(result["genie_name"], result["persona"], keyword, projects))
        return

    result["call_genie"] = True
    post_thinking(slack, result, question)


# --------------------------------------------------------------------------
# reply: show the answer, remember the conversation
# --------------------------------------------------------------------------

def project_owners(table, channel, keyword, hint=""):
    """[{name, mention, project}] of the owners to bring in, from the genie's row. The
    row is the one confirmed for this keyword and channel (record_key KEYWORD:CHANNEL),
    or the channel's only active genie when no keyword came through. A project named in
    `hint` narrows it to that project; otherwise every project's owner, once each."""
    if keyword:
        where = {"record_key": {"$eq": "{}:{}".format(keyword.upper(), channel)}}
    else:
        where = {"$and": [{"record_type": {"$eq": GENIE_TYPE}}, {"status": {"$eq": STATUS_ACTIVE}},
                          {"channel": {"$eq": channel}}]}
    rows, error = table.query(where, limit=2)
    if error or len(rows) != 1:
        return [], error or "no single genie row to read project owners from"
    projects = [p for p in _json_list(rows[0].get("workato_projects")) if isinstance(p, dict)]
    named = [p for p in projects if hint and (p.get("name") or "").strip().lower()
             == hint.strip().lower()]
    owners, seen = [], set()
    for project in named or projects:
        owner = project.get("owner") or {}
        mention = str(owner.get("mention") or "").strip()
        mention = mention if SLACK_MENTION.fullmatch(mention) else ""
        who = mention or _one_line(owner.get("name"))
        if who and who not in seen:
            seen.add(who)
            owners.append({"name": _one_line(owner.get("name")), "mention": mention,
                           "project": _one_line(project.get("name"))})
    return owners, None


def escalation_text(owners, asker_id, question, genie_name, blocked=False):
    """The message that brings the owner(s) in. Mentions come only from the stored owner
    mentions and the asker's Slack ID; the question is flattened to one plain line."""
    if not owners:
        return ("I couldn't find a project owner to bring in. Please ask the IT Integrations "
                "team to take a look.")
    who = ", ".join(o["mention"] or "*{}*".format(o["name"]) for o in owners)
    asker = "<@{}>".format(asker_id) if SLACK_MENTION.fullmatch("<@{}>".format(asker_id)) \
        else "someone"
    if blocked:
        text = (":no_entry: {} FYI: {} tried to use {}, but a rule in its knowledge base says "
                "it should not answer them. They were told it can't help".format(
                    who, asker, genie_name))
    else:
        text = ":raising_hand: {} could you help? {} asked {} a question it couldn't answer".format(
            who, asker, genie_name)
    quoted = _one_line(question, 300)
    return text + (":\n> " + quoted if quoted else ".")


def owner_dm_text(asker_id, question, genie_name, link, blocked=False):
    """The direct message an owner gets. Same rules as escalation_text: the asker is a
    mention built from their Slack ID, the question one plain line."""
    asker = "<@{}>".format(asker_id) if SLACK_MENTION.fullmatch("<@{}>".format(asker_id)) \
        else "Someone"
    if blocked:
        text = (":no_entry: {} tried to use *{}*, but a rule in its knowledge base says it should "
                "not answer them. They were told it can't help.".format(asker, genie_name))
    else:
        text = (":raising_hand: *{}* couldn't answer a question from {} and needs a person. "
                "Could you take a look?".format(genie_name, asker))
    quoted = _one_line(question, 300)
    if quoted:
        text += "\n> " + quoted
    return text + ("\n<{}|Open the thread>".format(link) if link else "")


def reply(input, table, slack, result):
    channel = result["channel"]
    thread_ts = result["reply_thread_ts"]
    genie_name = str(input.get("genie_name") or "Genie")
    persona = str(input.get("persona") or "")
    answer = str(input.get("genie_response") or "").strip()
    genie_error = str(input.get("genie_error") or "").strip()
    thinking_ts = str(input.get("thinking_ts") or "").strip()

    # The genie says it can't answer with a marker; take it out of what people read.
    # The marker, or the refusal sentence on its own: models often leave the marker off.
    blocked = bool(BLOCKED.search(answer)) or _plain(answer) == _plain(BLOCKED_ANSWER)
    if blocked:                     # a knowledge base rule says not to answer this person
        answer = BLOCKED.sub("", answer).strip() or BLOCKED_ANSWER
    marker = None if blocked else NEEDS_HUMAN.search(answer)
    hint = (marker.group(1) or "").strip() if marker else ""
    if marker:
        answer = NEEDS_HUMAN.sub("", answer).strip() or "I couldn't find an answer to that one."
    escalate = blocked or bool(marker) or bool(genie_error) or not answer
    result["needs_human"] = escalate
    result["blocked"] = blocked

    asker_id = str(input.get("user_id") or "").strip()
    answered = bool(answer) and not genie_error
    wants_feedback = FEEDBACK_BUTTONS and answered and not blocked   # a refusal needs no rating

    def build(native, feedback):
        if answered:
            return answer_attachments(genie_name, persona, answer, asker_id,
                                      native=native, feedback=feedback)
        return error_attachments(genie_name, persona, genie_error)

    def deliver(cards):
        """Edit the thinking message into the answer; post fresh if there is none."""
        if thinking_ts and slack.update(channel, thinking_ts, cards):
            return thinking_ts
        return slack.post(channel, thread_ts, cards)

    # The card with every newer block first. If Slack rejects it, the same answer is sent
    # again with a text table, then also without the feedback buttons. A step that would
    # build the same card as one already sent is skipped.
    errors_before = len(slack.errors)
    sent, attachments = [], None
    for native, feedback in ((True, wants_feedback), (False, wants_feedback), (False, False)):
        cards = build(native, feedback)
        if cards in sent:
            continue
        if sent:
            del slack.errors[errors_before:]
            result["warnings"].append("answer card rejected by Slack: retried with {}".format(
                " and ".join(([] if native else ["a text table"])
                             + ([] if feedback or not wants_feedback else ["no feedback buttons"]))))
        sent.append(cards)
        attachments = cards
        result["message_ts"] = deliver(cards)
        if result["message_ts"]:
            break
    result["posted"] = bool(result["message_ts"])
    result["answer_sections"] = len([b for b in attachments[0]["blocks"]
                                     if b["type"] not in ("context", "context_actions")])

    if escalate:
        owners, problem = project_owners(table, channel, str(input.get("keyword") or "").strip(),
                                         hint)
        if problem:
            result["warnings"].append("owners: " + problem)
        result["escalated_to"] = [o["mention"] or o["name"] for o in owners]
        if not blocked:             # a blocked person only sees the refusal; the owner gets the DM
            slack.say(channel, thread_ts, escalation_text(
                owners, asker_id, input.get("question"), genie_name, blocked))
        # ...and straight to each owner, with a link back to the thread.
        link = slack.permalink(channel, result["message_ts"])
        text = owner_dm_text(asker_id, input.get("question"), genie_name, link, blocked)
        for owner in owners:
            if owner["mention"] and slack.dm(owner["mention"][2:-1], text):
                result["dm_sent"].append(owner["mention"])

    # Remember the conversation against the thread. Each missing input is
    # reported: a silent skip here is a follow-up that forgets everything.
    conversation_id = str(input.get("conversation_id") or "").strip()
    missing = [name for name, value in (("conversation_id", conversation_id),
                                        ("channel", channel),
                                        ("reply_thread_ts", thread_ts)) if not value]
    if missing:
        result["warnings"].append("conversation not saved: {} empty -- map the ask step's / "
                                  "Assign task to genie's output".format(", ".join(missing)))
        return
    if not input.get("keyword"):
        result["warnings"].append("keyword empty: map the ask step's keyword output, so the "
                                  "thread is tied to its genie")
    key = conversation_key(channel, thread_ts)
    result["conversation_key"] = key
    found, error = table.query({"record_key": {"$eq": key}}, limit=1)
    if error:
        result["warnings"].append(error)
        return
    existing = found[0] if found else None
    fields = {"record_type": CONVERSATION_TYPE, "record_key": key, "id": conversation_id,
              "status": STATUS_ACTIVE, "channel": channel, "setup_thread_ts": thread_ts,
              "updated_at": now_iso()}
    # Only what was actually passed: a blank input never wipes a saved value.
    for column, name in (("invoke_keyword", "keyword"), ("genie_name", "genie_name"),
                         ("persona", "persona")):
        if str(input.get(name) or "").strip():
            fields[column] = str(input.get(name)).strip()
    if not existing:
        fields.update({"creator_id": str(input.get("user_id") or ""), "created_at": now_iso()})
    error = table.save(existing, fields)
    if error:
        result["warnings"].append(error)
    else:
        result["conversation_saved"] = True


# --------------------------------------------------------------------------
# feedback: someone clicked Good / Bad response
# --------------------------------------------------------------------------

def feedback_from_payload(input):
    """{user_id, channel, message_ts, thread_ts, value} of a click. Read from `payload`, the
    block_actions payload Slack sends (as JSON, or still form-encoded as payload=...), and
    from the plain inputs user_id / channel / message_ts / thread_ts / feedback_value, which
    win when both are given."""
    raw = input.get("payload")
    if isinstance(raw, str) and raw.strip().startswith("payload="):
        raw = (urllib.parse.parse_qs(raw.strip()).get("payload") or [""])[0]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    payload = raw if isinstance(raw, dict) else {}

    def pick(value):
        return value if isinstance(value, dict) else {}

    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    action = pick(actions[0]) if actions else {}
    message, container = pick(payload.get("message")), pick(payload.get("container"))
    found = {
        "user_id": pick(payload.get("user")).get("id"),
        "channel": pick(payload.get("channel")).get("id") or container.get("channel_id"),
        "message_ts": message.get("ts") or container.get("message_ts"),
        "thread_ts": message.get("thread_ts") or container.get("thread_ts"),
        "value": action.get("value"),
    }
    plain = {"user_id": input.get("user_id"), "channel": input.get("channel"),
             "message_ts": input.get("message_ts"), "thread_ts": input.get("thread_ts"),
             "value": input.get("feedback_value")}
    return {key: str(plain[key] or found[key] or "").strip() for key in found}


def feedback(fb, table, result):
    """Saves one rating as a row in the genie_console table: record_type genie_feedback,
    record_key fb:<channel>:<message_ts>:<user> (one row per person per answer, so a changed
    vote updates it), id = the answer's message_ts, status = positive or negative,
    creator_id = who clicked, and the genie's keyword / name / persona from the thread's
    conversation row."""
    value = fb["value"].lower()
    if value not in FEEDBACK_VALUES:
        raise RuntimeError("feedback value must be positive or negative, not {!r}".format(
            fb["value"]))
    missing = [name for name in ("user_id", "channel", "message_ts") if not fb[name]]
    if missing:
        raise RuntimeError("feedback needs {} (map them, or pass the block_actions payload)"
                           .format(", ".join(missing)))
    channel, message_ts = fb["channel"], fb["message_ts"]
    thread_ts = fb["thread_ts"] or message_ts
    result["feedback_value"] = value

    key = "fb:{}:{}:{}".format(channel, message_ts, fb["user_id"])
    found, error = table.query({"record_key": {"$eq": key}}, limit=1)
    if error:
        raise RuntimeError(error)
    existing = found[0] if found else None
    conversation, error = table.query({"record_key": {"$eq": conversation_key(channel, thread_ts)}},
                                      limit=1)
    if error:
        result["warnings"].append(error)           # the rating is still saved, without the genie
    conversation = conversation[0] if conversation else {}

    fields = {"record_type": FEEDBACK_TYPE, "record_key": key, "id": message_ts,
              "status": value, "channel": channel, "setup_thread_ts": thread_ts,
              "updated_at": now_iso()}
    for column in ("invoke_keyword", "genie_name", "persona"):
        if conversation.get(column):
            fields[column] = conversation[column]
    if not existing:
        fields.update({"creator_id": fb["user_id"], "created_at": now_iso()})
    error = table.save(existing, fields)
    if error:
        raise RuntimeError(error)
    result["feedback_saved"] = True


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    action = str(input.get("action") or "ask").strip().lower()
    fb = feedback_from_payload(input) if action == "feedback" else {}
    channel = str(input.get("channel") or fb.get("channel") or "").strip()
    thread_ts = str(input.get("thread_ts") or "").strip()
    message_ts = str(input.get("message_ts") or "").strip()
    reply_thread = str(input.get("reply_thread_ts") or "").strip() or thread_ts or message_ts
    dry_run = str(input.get("dry_run") or "").lower() in ("true", "1", "yes")

    result = {"ok": False, "error": "", "action": action, "matched": False, "skipped": "",
              "call_genie": False, "is_followup": False, "conversation_id": "",
              "keyword": "", "record_key": "", "genie_name": "", "genie_handle": "",
              "persona": "", "system_prompt": "", "question": "", "empty_question": False,
              "task_instructions": "", "projects_json": "[]", "recipes_json": "[]",
              "lookup_tables_json": "[]", "data_tables_json": "[]",
              "channel": channel, "reply_thread_ts": reply_thread, "thinking_ts": "",
              "genies_in_channel": 0, "posted": False, "message_ts": "",
              "answer_sections": 0, "conversation_saved": False,
              "conversation_key": "", "conversation_found": False, "warnings": [],
              "needs_human": False, "blocked": False, "escalated_to": [], "dm_sent": [],
              "feedback_saved": False, "feedback_value": "",
              "slack_payload_json": ""}

    token = input.get("workato_api_token") or ""
    if not token and not dry_run:
        result["error"] = "workato_api_token is empty"
        return result
    table = Table(token, dry_run)
    slack = Slack(input.get("slack_bot_token") or "", dry_run)
    try:
        if action == "reply":
            reply(input, table, slack, result)
        elif action == "ask":
            ask(input, table, slack, result)
        elif action == "feedback":
            feedback(fb, table, result)
        else:
            raise RuntimeError("action must be ask, reply or feedback, not {!r}".format(action))
        result["ok"] = True
    except RuntimeError as exc:
        result["error"] = str(exc)
    result["warnings"].extend(slack.errors)
    result["slack_payload_json"] = json.dumps(slack.last)
    return result


if __name__ == "__main__":
    # python3 genie_responder.py "SNAP why did quote Q-123 not sync?" C0ASWC1C11Q
    print(json.dumps(main({
        "action": "ask",
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", ""),
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "text": sys.argv[1] if len(sys.argv) > 1 else "SNAP why did quote Q-123 not sync?",
        "channel": sys.argv[2] if len(sys.argv) > 2 else os.environ.get("SLACK_CHANNEL", ""),
        "message_ts": "1792082384.030959",
        "dry_run": "true",
    }), indent=2))
