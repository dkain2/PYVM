"""
error_slack.py -- the ONE Workato Python step for everything Slack in the error alert: it posts the alert, and it does what the
buttons on it ask. Which of the two is decided by what the recipe passes in.

POST   (slack_channel_id, and the notifier's alert_json)
    error_notification.py works out the alert (history, the job and recipe, the AI story, the retry decision) and returns the
    facts as one output, `alert_json`. This step turns them into a compact Slack message and posts it with `slack_bot_token`. The
    email is untouched: this step never sends or stops it. It posts when the alert would be emailed (a retried error, or a call
    with frequency / error_limit, posts nothing: `skipped` says why). If alert_json is empty (the notifier failed, or was not
    mapped) a short alert is posted from subject, recipe_name, error_details, priority and job_url.
    THE SHORT LOOK (the default, slack_look blank or new): business only, nobody has to scroll, all in ONE attachment with a red bar
    (feature bar), and no carousel: section blocks and containers only, so it never swipes. The title (priority and recipe), one
    line (the headline, the retry verdict, how often, when), the error itself in a code block under a red label (its facts lined up,
    the error codes beside the label), the status line with Take it, then a 2 x 2 grid of small containers (feature grid: a layout):
    What happened | Impact, What to do next | Open. Without the grid (refused, or switched off) the same four come as plain sections
    with one row of buttons, never as a carousel. The boxes carry the same words and buttons: What happened (View job), Impact (Error
    file or Open recipe), What to do next (Reprocess, Mark resolved), Open (the rest of the links), then the failed records as a
    table with page navigation (data_table; -datatables gives the plain table). A footer line points to the email for the details. No Assign person picker: it cannot sit in a box (it is in the full look).
    A box's body is rich_text, not a section: confirmed live, a section inside a container still folds behind "Show more" even
    with expand: true, which only holds for a section at the top level of the message (the headline, the status line). rich_text
    never folds. -rich falls back to a section there too, the best that can be done without it.
    THE FULL LOOK (slack_look = full) reads like the email for a wider and wider audience, the technical part and the actions last:
        1  a plain-language message for the business: the headline, what happened, the impact (the raw error comes later)
        2  one carousel, a card to a section: what to do next / the error, where it broke, the failed records / how often, run
           health, worth knowing / under the hood, ids, handling (the last three cards are for the developer)
        3  the failed records, folded, as a table with page navigation (data_table; each column, link, bold and colour kept)
        4  the technical details, folded: every id, system, file and setting, the job and recipe, the full error text
        5  the buttons: links, then Reprocess / Acknowledge / Mark resolved / Assign to, then thumbs on the AI analysis
    Each new block is a feature (slack_features) that Slack may refuse in a workspace: an invalid_blocks answer takes that one
    feature out and the message is sent again, down to a plain card (slack_look = old goes straight there), then to text.
    Off unless slack_features asks (+charts, +tiles, +adaptive, +chips, +markdown): trend charts, run-health tiles, fact chips (buttons
    that only show a fact), the recent-failures table. Emails in the message are masked (slack_mask_pii).
    After posting, the step writes where the message is (channel, ts, link, when) to the error log row the notifier wrote.

CLICK  (payload, or action_id with value / user_id / channel / message_ts)
    Slack sends a click to the app's Interactivity Request URL as a `block_actions` payload. One recipe sits behind that URL; its
    trigger passes only the clicks whose action id starts with

        error_notification_

    to this step, which does the work and writes down who did it. Every button that does something starts that way, so ONE filter
    catches them all; link buttons (error_link_*) and fact chips (error_info_*) do not, so a click on them never runs the recipe.

    error_notification_reprocess     "Reprocess". Slack has already asked "Reprocess this job?" (the button's confirm popup), so a
                                     click here is a confirmed one. The step repeats the master job through the Workato API
                                     (POST /recipes/:id/repeat_jobs), marks the error log row Reprocessed (count + 1), and records
                                     who, when and the new job id. Refused, with a private message to the person who clicked, when
                                     the job was reprocessed less than `cooldown_minutes` ago (a double click, or someone else
                                     just did it), when it has been reprocessed `max_reprocess` times already, or when the
                                     person is not in `allowed_user_ids`.
    error_notification_acknowledge   "Take it", the button on the status line: someone is looking into it. The line then says who.
    error_notification_resolve       "Mark resolved" (confirmed by a popup too). Closes the buttons.
    error_notification_assign        the "Assign to..." person picker: records the owner and tags them in the thread.
    error_notification_feedback      thumbs up / down on the AI analysis.
    error_notification_check         "🔄 Check status", on the thread reply a successful Reprocess posts (not on the alert itself).
                                     Reads the new job from the Workato API and the error log row (the error log is the one source
                                     that knows a handled error from a real success, same as everywhere else in these two steps):
                                     still running -> the button stays, relabelled "Check again"; finished and the row says Failed
                                     Again (and that row is newer than this reprocess) -> the button goes, the error is posted back
                                     into the thread as a new reply; finished and not Failed Again -> "Completed", button goes.
    A click on a link or fact button that does reach this step is answered with action = noop.

    WHAT A CLICK DOES TO THE MESSAGE. The status line under the title (block id error_notification_status) is replaced, newest first,
    with who did what and when ("♻️ Reprocess queued by Ada · Nov 20 at 3:41 PM · job j-..."): the time is drawn in each reader's
    own time zone. A reprocess takes its button away, a resolve all of them, so it cannot be done twice. A short reply goes in the
    thread as well. Both can be switched off (update_message, thread_reply). A failure to edit the message never undoes the action.

    WHICH JOB A CLICK IS ABOUT. Each button carries it as compact JSON in its value. A person picker has no value, so the job is also
    in the id of the block the buttons sit in (error_notification_actions|<master job>|<recipe id>), and failing both the message
    is searched for that block, and last the error log for the row with this message's ts (Slack Message TS).

    WHO CLICKED. The Slack user is looked up (users.info; needs users:read and users:read.email) for a name and an email. Without
    them the user id is what is written. A lookup that fails is only a warning.

    IS THE REQUEST REAL. Anyone who knows the webhook URL could post a forged payload. If the recipe passes `slack_signing_secret`
    together with `raw_body`, `slack_request_timestamp` and `slack_signature` (the X-Slack-* headers), the step checks Slack's
    signature (HMAC-SHA256 of v0:<timestamp>:<body>, at most 5 minutes old) and does nothing when it does not match. Slack's own
    Workato trigger does this check already; with a generic webhook, pass these. Blank secret = not checked.

A REPROCESS THAT IS CHECKED, NOT WATCHED. Nothing here polls on its own (no cron, no wait): the "check status" button only acts
when someone clicks it. The reprocessed job itself is never guaranteed to post its own alert back to this thread if it fails again
(a fresh failure is a brand-new call to the error recipe, a new top-level message, not a reply here) -- the check button is how the
thread finds out without waiting for that.

WHAT IT WRITES DOWN (the error log table, one row per master job; 26 new columns, see TRACK_COLUMNS and data_table_new_columns.md)
    Notified Via / Slack Channel / Slack Message TS / Slack Message URL / Notified At (when posting); Last Action, Last Action By /
    By Slack ID / By Email / At / Result, Action Log (every action, one line each, newest last), Reprocessed By / By Slack ID / By
    Email / At, Reprocess Job ID, Reprocess Source ("Slack button"), Reprocess Result, Reprocess Error, Acknowledged By / At, Resolved
    By / At, Assigned To, AI Feedback. A reprocess also sets the columns the old recipes use: Status = Reprocessed, Reprocess
    Count + 1, Reprocess_Flag = false. If the table does not have the new columns yet, the action is still done and the old columns
    are still written; the warnings say so.

`mode` = post or click forces one; blank decides: a payload or action_id means click, a slack_channel_id (or an alert_json) means post.
NOTHING HERE MAY BREAK THE RECIPE. Every call has a timeout; a failure goes into `error` / `warnings` and the step still returns.

Input schema: error_slack_input_schema.json   Output schema: error_slack_output_schema.json
Run it locally:   python3 error_slack.py testdata/click_reprocess.json      (reads SLACK_BOT_TOKEN and WORKATO_API_TOKEN)
                  python3 error_slack.py testdata/post_alert.json --slack-out /tmp/alert.json   (nothing is posted: {blocks} for Block Kit Builder)
"""

import hashlib
import hmac
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

VERSION = "1.0.0"

SLACK_API = "https://slack.com/api/"
WORKATO_API = "https://www.workato.com/api"
DATA_TABLES_API = "https://data-tables.workato.com/api/v1/tables"
ERROR_TABLE_ID = "c1444a9a-03a7-4c82-8618-7796b7384b37"      # Error Notification - TBL

# This step owns these names: they are the contract with the step that posts the alert (its test compares with these).
ACTION_PREFIX = "error_notification_"
ACT_REPROCESS = ACTION_PREFIX + "reprocess"
ACT_ACK = ACTION_PREFIX + "acknowledge"
ACT_RESOLVE = ACTION_PREFIX + "resolve"
ACT_ASSIGN = ACTION_PREFIX + "assign"
ACT_FEEDBACK = ACTION_PREFIX + "feedback"
ACT_CHECK = ACTION_PREFIX + "check"
INFO_PREFIX = "error_info_"
LINK_PREFIX = "error_link_"
STATUS_BLOCK_ID = "error_notification_status"
ACTIONS_BLOCK_ID = "error_notification_actions"
CHECK_BLOCK_ID = "error_notification_check"     # the thread reply that holds the "check status" button
ACTIONS = {ACT_REPROCESS: "reprocess", ACT_ACK: "acknowledge", ACT_RESOLVE: "resolve", ACT_ASSIGN: "assign",
           ACT_FEEDBACK: "feedback", ACT_CHECK: "check"}
JOB_FINISHED_STATUSES = {"succeeded", "success", "completed", "failed", "error", "errored", "stopped", "cancelled", "aborted"}

# The old columns this step reads and writes, and the new ones (data_table_new_columns.md lists them for adding by hand).
BASE_COLUMNS = {"master_job_id": "Master Job ID", "recipe_id": "Recipie Id", "recipe_name": "Recipe Name", "job_id": "Job Id",
                "status": "Status", "reprocess_count": "Reprocess Count", "reprocess_flag": "Reprocess_Flag"}
TRACK_COLUMNS = {
    "notified_via": "Notified Via", "slack_channel": "Slack Channel", "slack_ts": "Slack Message TS",
    "slack_url": "Slack Message URL", "notified_at": "Notified At",
    "last_action": "Last Action", "last_action_by": "Last Action By", "last_action_by_id": "Last Action By Slack ID",
    "last_action_by_email": "Last Action By Email", "last_action_at": "Last Action At",
    "last_action_result": "Last Action Result", "action_log": "Action Log",
    "reprocessed_by": "Reprocessed By", "reprocessed_by_id": "Reprocessed By Slack ID",
    "reprocessed_by_email": "Reprocessed By Email", "reprocessed_at": "Reprocessed At",
    "reprocess_job_id": "Reprocess Job ID", "reprocess_source": "Reprocess Source",
    "reprocess_result": "Reprocess Result", "reprocess_error": "Reprocess Error",
    "acknowledged_by": "Acknowledged By", "acknowledged_at": "Acknowledged At",
    "resolved_by": "Resolved By", "resolved_at": "Resolved At",
    "assigned_to": "Assigned To", "ai_feedback": "AI Feedback",
}
TRACK_DATE_KEYS = {"notified_at", "last_action_at", "reprocessed_at", "acknowledged_at", "resolved_at"}   # the date_time columns
ACTION_LOG_LIMIT = 8000
STATUS_LINES = 5                 # lines kept in the status block, newest first
SOURCE = "Slack button"

OUTPUT_DEFAULTS = (
    ("ok", False), ("error", ""), ("warnings", []), ("mode", ""),
    ("posted", False), ("skipped", ""), ("alert_source", ""), ("look_used", ""), ("text", ""), ("blocks", 0),
    ("blocks_json", ""), ("permalink", ""),
    ("channel", ""), ("message_ts", ""),
    ("action", ""), ("handled", False), ("refused", ""), ("result", ""),
    ("user_id", ""), ("user_name", ""), ("user_email", ""),
    ("master_job_id", ""), ("recipe_id", ""),
    ("reprocess_attempted", False), ("reprocess_enqueued", False), ("reprocess_job_id", ""), ("reprocess_error", ""),
    ("check_result", ""),
    ("row_action", ""), ("row_record_id", ""), ("row_error", ""),
    ("message_updated", False), ("thread_posted", False), ("private_message_sent", False),
    ("assigned_user_id", ""), ("feedback", ""), ("signature_checked", False),
    ("elapsed_ms", 0),
)
INPUT_NAMES = (
    "mode", "slack_channel_id", "alert_json", "slack_bot_token", "workato_api_token",
    "slack_look", "slack_features", "slack_buttons", "slack_mention", "slack_mask_pii", "slack_thread_ts", "max_table_rows",
    "subject", "recipe_name", "error_details", "priority", "job_url", "calling_master_job_id",
    "payload", "action_id", "value", "user_id", "channel", "message_ts", "selected_user", "feedback_value",
    "allowed_user_ids", "cooldown_minutes", "max_reprocess", "update_message", "thread_reply",
    "slack_signing_secret", "raw_body", "slack_request_timestamp", "slack_signature",
    "data_table_id", "workato_api_base", "timezone", "http_timeout", "time_budget", "now",
)


# ------------------------------------------------------------------------------------------------ small helpers


def text_of(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def clip(value, limit):
    value = text_of(value)
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


def truthy(value, default=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    return text_of(value).strip().lower() in ("1", "true", "yes", "y", "on")


def to_int(value, default=None):
    try:
        return int(float(text_of(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


def sx(text):
    return text_of(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class FetchError(Exception):
    pass


def http_json(method, url, headers, payload=None, timeout=12):
    """(body, error). Never raises on an HTTP or network failure."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib_request.Request(url, data=data, method=method, headers=headers or {})
    host = urllib_parse.urlsplit(url).netloc
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib_error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            detail = ""
        return None, "{} {}: {}".format(host, exc.code, clip(detail, 300))
    except Exception as exc:  # noqa: BLE001 - timeouts, DNS, TLS
        return None, "{}: {}: {}".format(host, type(exc).__name__, clip(str(exc), 200))
    if not raw.strip():
        return {}, None
    try:
        return json.loads(raw), None
    except ValueError:
        return None, "{}: response is not JSON".format(host)


def remaining(deadline):
    return deadline - time.time()


def call_timeout(cfg, deadline):
    left = remaining(deadline)
    if left < 1.5:
        raise FetchError("out of time")
    return max(1.5, min(cfg["http_timeout"], left))


# ------------------------------------------------------------------------------------------------ settings


def settings(inp):
    def pick(name, default=""):
        value = inp.get(name)
        return default if value is None or (isinstance(value, str) and not value.strip()) else value

    cfg = {
        "workato_api_token": text_of(pick("workato_api_token")).strip(),
        "slack_bot_token": text_of(pick("slack_bot_token")).strip(),
        "data_table_id": text_of(pick("data_table_id", ERROR_TABLE_ID)).strip(),
        "workato_api_base": text_of(pick("workato_api_base", WORKATO_API)).strip().rstrip("/"),
        "data_tables_base": DATA_TABLES_API,
        "allowed": {u for u in re.split(r"[\s,;]+", text_of(inp.get("allowed_user_ids")).upper()) if u},
        "cooldown_minutes": max(0, min(1440, to_int(inp.get("cooldown_minutes"), 10))),
        "max_reprocess": max(1, min(50, to_int(inp.get("max_reprocess"), 3))),
        "update_message": truthy(inp.get("update_message"), True),
        "thread_reply": truthy(inp.get("thread_reply"), True),
        "timezone": text_of(pick("timezone", "America/Los_Angeles")).strip(),
        "http_timeout": max(3, min(60, to_int(inp.get("http_timeout"), 12))),
        "time_budget": max(5, min(85, to_int(inp.get("time_budget"), 25))),
        "secret": text_of(inp.get("slack_signing_secret")).strip(),
        "slack_channel_id": text_of(pick("slack_channel_id")).strip(),
        "slack_look": {"old": "old", "full": "full"}.get(text_of(pick("slack_look", "new")).strip().lower(), "new"),
        "slack_features": text_of(inp.get("slack_features")), "slack_buttons": text_of(inp.get("slack_buttons")),
        "slack_mention": text_of(inp.get("slack_mention")).strip(), "slack_mask_pii": truthy(inp.get("slack_mask_pii"), True),
        "slack_thread_ts": text_of(inp.get("slack_thread_ts")).strip(),
        "max_table_rows": max(1, min(500, to_int(inp.get("max_table_rows"), 25))),
    }
    return cfg


def get_tz(name):
    if ZoneInfo:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001
            pass
    return timezone(timedelta(hours=-8), "PST")


def parse_when(value):
    """An ISO date-time as the table stores it ('2026-11-20T15:41:00.000-08:00', or with Z); None when it is not one."""
    raw = text_of(value).strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    raw = re.sub(r"(\.\d{1,6})\d*", r"\1", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def slack_when(dt):
    """A time that Slack draws in each reader's own time zone."""
    stamp = int(dt.timestamp())
    return "<!date^{}^{{date_short_pretty}} at {{time}}|{}>".format(stamp, dt.strftime("%b %d %H:%M %Z").strip())


# ------------------------------------------------------------------------------------------------ the request


def verify_signature(cfg, inp, now):
    """(checked, error). Slack signs v0:<timestamp>:<raw body> with the app's signing secret."""
    if not cfg["secret"]:
        return False, ""
    stamp = text_of(inp.get("slack_request_timestamp")).strip()
    given = text_of(inp.get("slack_signature")).strip()
    body = inp.get("raw_body")
    if not (stamp and given and body is not None):
        return True, "the request carries no signature (slack_request_timestamp, slack_signature and raw_body are needed)"
    seconds = to_int(stamp)
    if seconds is None or abs(now.timestamp() - seconds) > 300:
        return True, "the request is too old or its timestamp is not a time"
    expected = "v0=" + hmac.new(cfg["secret"].encode("utf-8"), "v0:{}:{}".format(stamp, text_of(body)).encode("utf-8"),
                                hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, given):
        return True, "the signature does not match"
    return True, ""


def read_payload(inp):
    """The block_actions payload as a dict: JSON, or still form-encoded as payload=..., or {} when there is none."""
    raw = inp.get("payload")
    if isinstance(raw, str) and raw.strip().startswith("payload="):
        raw = (urllib_parse.parse_qs(raw.strip()).get("payload") or [""])[0]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    return raw if isinstance(raw, dict) else {}


def as_dict(value):
    return value if isinstance(value, dict) else {}


def parse_click(inp):
    """What was clicked, by whom, on which message. The plain inputs win over the payload (a recipe may map the fields)."""
    payload = read_payload(inp)
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    action = as_dict(actions[0]) if actions else {}
    message, container = as_dict(payload.get("message")), as_dict(payload.get("container"))
    selected = action.get("selected_user") or as_dict(action.get("selected_option")).get("value")
    click = {
        "action_id": text_of(inp.get("action_id") or action.get("action_id")).strip(),
        "block_id": text_of(action.get("block_id")).strip(),
        "value": text_of(inp.get("value") if inp.get("value") not in (None, "") else action.get("value")),
        "selected_user": text_of(inp.get("selected_user") or selected).strip(),
        "user_id": text_of(inp.get("user_id") or as_dict(payload.get("user")).get("id")).strip(),
        "user_name": text_of(as_dict(payload.get("user")).get("name") or as_dict(payload.get("user")).get("username")).strip(),
        "channel": text_of(inp.get("channel") or as_dict(payload.get("channel")).get("id") or container.get("channel_id")).strip(),
        "message_ts": text_of(inp.get("message_ts") or message.get("ts") or container.get("message_ts")).strip(),
        "thread_ts": text_of(message.get("thread_ts")).strip(),
        "message": message,
    }
    if inp.get("feedback_value") not in (None, ""):
        click["value"] = text_of(inp.get("feedback_value"))
    return click


def job_from_block_id(block_id):
    """(master job id, recipe id) from error_notification_actions|<master>|<recipe>."""
    parts = text_of(block_id).split("|")
    if len(parts) >= 3 and parts[0] == ACTIONS_BLOCK_ID and parts[1]:
        return parts[1], parts[2]
    return "", ""


def blocks_of(message):
    """The lists of blocks of a message: the top level, then each attachment's."""
    lists = []
    if isinstance(message.get("blocks"), list):
        lists.append(message["blocks"])
    for attachment in message.get("attachments") or []:
        if isinstance(attachment, dict) and isinstance(attachment.get("blocks"), list):
            lists.append(attachment["blocks"])
    return lists


def nested(block):
    """A block and every block inside it: carousel cards, layout items, container children."""
    if not isinstance(block, dict):
        return
    yield block
    kids = []
    if block.get("type") == "carousel":
        kids = block.get("elements") or []
    elif block.get("type") == "layout":
        kids = [item.get("block") for row in block.get("rows") or [] for item in row.get("items") or []]
    elif block.get("type") == "container":
        kids = block.get("child_blocks") or []
    for kid in kids:
        for inner in nested(kid):
            yield inner


def job_context(click):
    """{master, recipe_id, recipe_name, job_id, environment, priority, signature, table} from the button value, the block id or
    the message. {} when the click does not say which job it is about."""
    ctx = {}
    try:
        value = json.loads(click["value"]) if click["value"].strip().startswith("{") else {}
    except ValueError:
        value = {}
    if isinstance(value, dict) and value.get("m"):
        ctx = {"master": text_of(value.get("m")), "recipe_id": text_of(value.get("r")), "job_id": text_of(value.get("j")),
               "recipe_name": text_of(value.get("n")), "environment": text_of(value.get("e")),
               "priority": text_of(value.get("p")), "signature": text_of(value.get("s")), "table": text_of(value.get("d"))}
        return ctx
    master, recipe = job_from_block_id(click["block_id"])
    if not master:
        for blocks in blocks_of(click["message"]):
            for block in blocks:
                for item in nested(block):
                    master, recipe = job_from_block_id(item.get("block_id")) if isinstance(item, dict) else ("", "")
                    if master:
                        break
                if master:
                    break
            if master:
                break
    if master:
        return {"master": master, "recipe_id": recipe, "job_id": master, "recipe_name": "", "environment": "",
                "priority": "", "signature": "", "table": ""}
    return {}


# ------------------------------------------------------------------------------------------------ Slack


def slack_call(cfg, method, payload, deadline):
    """(body, error)."""
    try:
        timeout = call_timeout(cfg, deadline)
    except FetchError as exc:
        return None, str(exc)
    headers = {"Authorization": "Bearer " + cfg["slack_bot_token"], "Content-Type": "application/json; charset=utf-8"}
    body, err = http_json("POST", SLACK_API + method, headers, payload, timeout)
    if err:
        return None, "slack.{}: {}".format(method, err)
    if not isinstance(body, dict) or not body.get("ok"):
        body = body if isinstance(body, dict) else {}
        notes = (body.get("response_metadata") or {}).get("messages") or []
        why = "; ".join(text_of(n) for n in notes[:3])
        return None, "slack.{}: {}{}".format(method, body.get("error") or "unknown", " ({})".format(clip(why, 300)) if why else "")
    return body, None


def slack_user(cfg, user_id, fallback_name, deadline):
    """{id, name, email, note}. users.info needs users:read (+ users:read.email); a miss falls back to what the payload had."""
    out = {"id": user_id, "name": fallback_name or user_id, "email": "", "note": ""}
    if not (user_id and cfg["slack_bot_token"]):
        return out
    try:
        timeout = call_timeout(cfg, deadline)
    except FetchError as exc:
        out["note"] = str(exc)
        return out
    url = SLACK_API + "users.info?" + urllib_parse.urlencode({"user": user_id})
    body, err = http_json("GET", url, {"Authorization": "Bearer " + cfg["slack_bot_token"]}, None, timeout)
    if err or not isinstance(body, dict) or not body.get("ok"):
        out["note"] = clip(err or text_of(as_dict(body).get("error")) or "unknown", 160)
        return out
    user = as_dict(body.get("user"))
    profile = as_dict(user.get("profile"))
    out["name"] = (profile.get("real_name") or user.get("real_name") or profile.get("display_name") or user.get("name")
                   or out["name"])
    out["email"] = text_of(profile.get("email"))
    return out


def edit_message(message, edit):
    """A copy of the message's block lists with `edit(blocks)` applied to each. -> (blocks, attachments)."""
    top = [dict(b) for b in message["blocks"]] if isinstance(message.get("blocks"), list) else None
    attachments = [dict(a, blocks=[dict(b) for b in a["blocks"]]) if isinstance(a, dict) and isinstance(a.get("blocks"), list)
                   else a for a in (message.get("attachments") or [])]
    if top is not None:
        edit(top)
    for attachment in attachments:
        if isinstance(attachment, dict) and isinstance(attachment.get("blocks"), list):
            edit(attachment["blocks"])
    return top, attachments


def status_text(blocks):
    for block in blocks:
        if block.get("block_id") == STATUS_BLOCK_ID:
            if block.get("type") == "section":
                return text_of((block.get("text") or {}).get("text"))
            elements = block.get("elements") or []
            return text_of(elements[0].get("text")) if elements else ""
    return ""


def stacked(old, line):
    """The new line first, then what was there before (the 'Open' line is dropped), at most STATUS_LINES."""
    lines = [l for l in text_of(old).split("\n") if l.strip() and not l.startswith("🆕")]
    return "\n".join(([line] + lines)[:STATUS_LINES])


def patch_blocks(blocks, line, remove):
    """Put `line` first in the status block, and take the buttons in `remove` (action ids) out of the actions block; a block
    left with no element goes. Returns whether the status block was there."""
    found = False
    for block in list(blocks):
        if block.get("block_id") == STATUS_BLOCK_ID:
            text = stacked(status_text(blocks), line)
            if block.get("type") == "section":                 # the status line with its Take it button
                block["text"] = {"type": "mrkdwn", "text": text}
                if (block.get("accessory") or {}).get("action_id") in remove:
                    block.pop("accessory")
            else:
                block["elements"] = [{"type": "mrkdwn", "text": text}]
            found = True
        elif block.get("type") == "actions" and text_of(block.get("block_id")).startswith(ACTIONS_BLOCK_ID):
            block["elements"] = [e for e in block.get("elements", []) if e.get("action_id") not in remove]
            if not block["elements"]:
                blocks.remove(block)
        elif block.get("type") == "layout":                  # the short look's grid: containers in rows
            for row in block.get("rows") or []:
                for item in row.get("items") or []:
                    inner = dict(item.get("block") or {})
                    if isinstance(inner.get("child_blocks"), list):
                        inner["child_blocks"] = [dict(k) for k in inner["child_blocks"]]
                        patch_blocks(inner["child_blocks"], line, remove)
                    item["block"] = inner
        elif block.get("type") == "container" and isinstance(block.get("child_blocks"), list):
            block["child_blocks"] = [dict(k) for k in block["child_blocks"]]
            found = patch_blocks(block["child_blocks"], line, remove) or found
        elif block.get("type") == "carousel":               # the short look keeps its buttons in the cards
            cards = []
            for card in block.get("elements") or []:
                card = dict(card)
                if card.get("actions"):
                    card["actions"] = [e for e in card["actions"] if e.get("action_id") not in remove]
                    if not card["actions"]:
                        card.pop("actions")
                cards.append(card)
            block["elements"] = cards
    return found


def update_message(cfg, click, line, remove, deadline):
    """chat.update with the status line and without the buttons in `remove`. -> (updated, error)."""
    message = click["message"]
    if not (click["channel"] and click["message_ts"] and blocks_of(message)):
        return False, "the click did not carry the message"
    seen = []
    top, attachments = edit_message(message, lambda blocks: seen.append(patch_blocks(blocks, line, remove)))
    if not any(seen):
        return False, "the message has no status block"
    payload = {"channel": click["channel"], "ts": click["message_ts"], "text": text_of(message.get("text")) or "Error alert"}
    if top is not None:
        payload["blocks"] = top
    if any(isinstance(a, dict) for a in attachments):
        payload["attachments"] = attachments
    body, err = slack_call(cfg, "chat.update", payload, deadline)
    return body is not None, err or ""


# ------------------------------------------------------------------------------------------------ the error log table


def decode_records(body):
    """[(record_id, fields)] from a data table answer (the query answers with arrays named in `schema`)."""
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, dict):
        data = [data]
    schema = body.get("schema")
    meta_names = field_names = []
    if isinstance(schema, list) and len(schema) == 2 and all(isinstance(g, list) for g in schema):
        meta_names = [f.get("name") for f in schema[0] if isinstance(f, dict)]
        field_names = [f.get("name") for f in schema[1] if isinstance(f, dict)]
    out = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            doc = item.get("document")
            if isinstance(doc, list):
                doc = {d.get("field_name"): d.get("value") for d in doc if isinstance(d, dict)}
            rid = text_of(item.get("record_id") or item.get("$record_id") or item.get("id")).strip()
            out.append((rid, doc if isinstance(doc, dict) else {}))
        elif isinstance(item, list) and len(item) == 2 and all(isinstance(g, list) for g in item):
            metas, values = item
            rid = next((text_of(v) for n, v in zip(meta_names, metas) if n == "$record_id"), "")
            out.append((rid.strip() or (text_of(metas[0]).strip() if metas else ""), dict(zip(field_names, values))))
    return out


def table_call(cfg, method, path, payload, deadline):
    """One call to the data table API. Tried twice when it was busy (429, 503); a PUT also after a timeout or a 5xx."""
    url = "{}/{}/{}".format(cfg["data_tables_base"].rstrip("/"), cfg["data_table_id"], path)
    headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Content-Type": "application/json"}
    for attempt in (1, 2):
        body, err = http_json(method, url, headers, payload, call_timeout(cfg, deadline))
        if not err:
            return body
        code = re.search(r" (\d{3}): ", err)
        busy = bool(code) and code.group(1) in ("429", "503")
        repeatable = method == "PUT" and (not code or code.group(1).startswith("5"))
        if attempt == 2 or not (busy or repeatable) or remaining(deadline) < 3:
            raise FetchError(err)
        time.sleep(0.5)


def find_row(cfg, field, value, deadline):
    """(record_id, fields) of the newest row whose column `field` equals value, or None."""
    payload = {"where": {field: {"$eq": value}}, "limit": 1, "order": {"by": "$created_at", "direction": "desc"}}
    try:
        body = table_call(cfg, "POST", "query", payload, deadline)
    except FetchError as exc:
        if not re.search(r" 4(00|22): ", str(exc)):
            raise
        payload.pop("order")
        body = table_call(cfg, "POST", "query", payload, deadline)
    records = decode_records(body)
    return records[0] if records else None


def merge_log(old, new):
    text = (text_of(old).rstrip("\n") + "\n" + new).strip("\n") if text_of(old).strip() else new
    if len(text) > ACTION_LOG_LIMIT:
        text = text[-ACTION_LOG_LIMIT:]
        text = text[text.find("\n") + 1:] if "\n" in text else text
    return text


def save_row(cfg, found, master, fields, base_fields, deadline):
    """Update the row (or add one if the job has none). `fields` are the new columns, `base_fields` the old ones: when the table
    does not have the new columns yet (a 400 / 422), only the old ones go. -> (action, record_id, note)."""
    def write(document):
        body = {"document": document}
        if found and found[0]:
            return table_call(cfg, "PUT", "records/" + urllib_parse.quote(found[0], safe=""), body, deadline), "updated"
        return table_call(cfg, "POST", "records", body, deadline), "inserted"

    note = ""
    both = dict(base_fields)
    both.update(fields)
    try:
        body, action = write(both)
    except FetchError as exc:
        if not (fields and re.search(r" 4(00|22): ", str(exc))):
            raise
        note = "the tracking columns are not in the error log table yet, so only the old columns were written"
        if not base_fields:
            return "skipped", "", note
        body, action = write(base_fields)
    saved = decode_records(body)
    return action, (saved[0][0] if saved else "") or (found[0] if found else ""), note


# ------------------------------------------------------------------------------------------------ the actions


def who_line(user):
    return "{} ({})".format(user["name"], user["id"]) if user["id"] and user["name"] != user["id"] else (user["name"] or user["id"])


def common_fields(user, now, action, result, stored, log_result=None):
    """The Last Action columns and the log line every action writes."""
    stamp = now.isoformat()
    line = " | ".join(x for x in (stamp, who_line(user), action, log_result if log_result is not None else result) if x)
    return {TRACK_COLUMNS["last_action"]: action, TRACK_COLUMNS["last_action_by"]: user["name"],
            TRACK_COLUMNS["last_action_by_id"]: user["id"], TRACK_COLUMNS["last_action_by_email"]: user["email"] or None,
            TRACK_COLUMNS["last_action_at"]: stamp, TRACK_COLUMNS["last_action_result"]: clip(result, 500),
            TRACK_COLUMNS["action_log"]: merge_log(stored.get(TRACK_COLUMNS["action_log"]), line)}


def repeat_job(cfg, recipe_id, master, deadline):
    """POST /api/recipes/:recipe_id/repeat_jobs with the master job id. -> {"enqueued", "job_id", "error"}."""
    out = {"enqueued": False, "job_id": "", "error": ""}
    try:
        timeout = call_timeout(cfg, deadline)
    except FetchError as exc:
        out["error"] = str(exc)
        return out
    url = "{}/recipes/{}/repeat_jobs".format(cfg["workato_api_base"], urllib_parse.quote(recipe_id))
    headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Content-Type": "application/json",
               "Accept": "application/json"}
    body, err = http_json("POST", url, headers, {"job_ids": [master]}, timeout)
    if err:
        out["error"] = err
        return out
    body = as_dict(body)
    results = body.get("results") if isinstance(body.get("results"), list) else []
    first = as_dict(results[0]) if results else {}
    job = as_dict(first.get("job"))
    summary = as_dict(body.get("summary"))
    status = text_of(first.get("status")).lower()
    out["job_id"] = text_of(job.get("id") or job.get("handle"))
    out["enqueued"] = (to_int(summary.get("total_enqueued"), 0) or 0) > 0 or status in (
        "enqueued", "queued", "success", "succeeded", "ok", "repeated")
    if not out["enqueued"]:
        out["error"] = clip(text_of(first.get("error") or status or "Workato did not enqueue the repeat"), 300)
    return out


def workato_get(cfg, path, deadline):
    """A plain GET against the Workato API (some answers wrap the body in a top-level "result")."""
    url = cfg["workato_api_base"] + path
    headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Accept": "application/json"}
    body, err = http_json("GET", url, headers, None, call_timeout(cfg, deadline))
    if err:
        raise FetchError(err)
    body = body if isinstance(body, dict) else {}
    return body["result"] if isinstance(body.get("result"), dict) else body


def job_finished(body):
    """Best guess at whether a Workato job has stopped running: a completed_at, or a status word that reads as terminal. Not
    verified against the live API (the same caveat as error_notification.py's parse_job); an unexpected shape just reads as
    still running, so a check never wrongly calls a live job finished."""
    if text_of(body.get("completed_at")).strip():
        return True
    return text_of(body.get("status")).strip().lower() in JOB_FINISHED_STATUSES


class Run(object):
    """Everything one click needs, and what it leaves behind."""

    def __init__(self, cfg, click, job, user, now, result, warnings, deadline):
        self.cfg, self.click, self.job, self.user, self.now = cfg, click, job, user, now
        self.result, self.warnings, self.deadline = result, warnings, deadline
        self.row = None
        self.stored = {}

    # -- Slack
    def tell(self, line, remove=(), thread=None):
        """The status line on the message (best effort), the reply in the thread, both optional. thread=False skips the thread
        reply entirely (do_reprocess posts its own, with a check-status button, instead); any other value (including the default,
        None) posts one, with `thread` as its text, or `line` when `thread` is blank."""
        cfg, click, result = self.cfg, self.click, self.result
        if cfg["slack_bot_token"] and cfg["update_message"]:
            ok, err = update_message(cfg, click, line, set(remove), self.deadline)
            result["message_updated"] = ok
            if not ok and err:
                self.warnings.append("message not updated: " + clip(err, 200))
        if cfg["slack_bot_token"] and cfg["thread_reply"] and thread is not False and click["channel"] and click["message_ts"]:
            body, err = slack_call(cfg, "chat.postMessage", {"channel": click["channel"], "thread_ts": click["thread_ts"] or click["message_ts"],
                                                            "text": thread or line, "unfurl_links": False}, self.deadline)
            result["thread_posted"] = body is not None
            if err:
                self.warnings.append("thread reply not posted: " + clip(err, 200))

    def whisper(self, text):
        """A private message to the person who clicked."""
        cfg, click = self.cfg, self.click
        if not (cfg["slack_bot_token"] and click["channel"] and self.user["id"]):
            return
        body, err = slack_call(cfg, "chat.postEphemeral", {"channel": click["channel"], "user": self.user["id"], "text": text}, self.deadline)
        self.result["private_message_sent"] = body is not None
        if err:
            self.warnings.append("private message not sent: " + clip(err, 200))

    def post_check_thread(self, master, recipe_id, job_id):
        """A reply with a 'Check status' button, in its own block (CHECK_BLOCK_ID) so a later click can find and edit just this
        message. The button carries master, recipe_id, the new job id and when this reprocess happened (so a check never reads a
        Failed Again left over from an earlier reprocess as this one's result)."""
        cfg, click = self.cfg, self.click
        if not (cfg["slack_bot_token"] and cfg["thread_reply"] and click["channel"] and click["message_ts"]):
            return
        text = "⏳ *In progress* · job `{}`".format(job_id)
        value = json.dumps({"v": 1, "m": master, "r": recipe_id, "j": job_id, "t": self.now.isoformat()},
                           separators=(",", ":"), ensure_ascii=False)[:1900]
        block = {"type": "section", "block_id": CHECK_BLOCK_ID, "text": mrk(text), "expand": True,
                "accessory": {"type": "button", "text": pt("🔄 Check status"), "action_id": ACT_CHECK, "value": value}}
        body, err = slack_call(cfg, "chat.postMessage", {"channel": click["channel"], "thread_ts": click["thread_ts"] or click["message_ts"],
                                                        "text": "♻️ Reprocess queued as job {}".format(job_id), "blocks": [block],
                                                        "unfurl_links": False}, self.deadline)
        self.result["thread_posted"] = body is not None
        if err:
            self.warnings.append("thread status button not posted: " + clip(err, 200))

    def update_check(self, text, button_label=None):
        """Edits the CHECK_BLOCK_ID message this click came from: new text, and either a relabelled button (still running) or
        none at all (finished)."""
        cfg, click, result = self.cfg, self.click, self.result
        if not (cfg["slack_bot_token"] and cfg["update_message"]):
            return
        blocks = [dict(b) for b in (click["message"].get("blocks") or [])]
        found = False
        for block in blocks:
            if block.get("block_id") == CHECK_BLOCK_ID:
                block["text"] = mrk(text)
                if button_label:
                    block["accessory"] = {"type": "button", "text": pt(button_label), "action_id": ACT_CHECK, "value": click["value"]}
                else:
                    block.pop("accessory", None)
                found = True
        if not found:
            self.warnings.append("check message not updated: the message has no check block")
            return
        body, err = slack_call(cfg, "chat.update", {"channel": click["channel"], "ts": click["message_ts"],
                                                    "text": text_of(click["message"].get("text")) or text, "blocks": blocks}, self.deadline)
        result["message_updated"] = body is not None
        if not body and err:
            self.warnings.append("check message not updated: " + clip(err, 200))

    def post_thread(self, text):
        """A plain reply in the thread (used to bring a failed-again error back)."""
        cfg, click = self.cfg, self.click
        if not (cfg["slack_bot_token"] and cfg["thread_reply"] and click["channel"] and click["message_ts"]):
            return
        body, err = slack_call(cfg, "chat.postMessage", {"channel": click["channel"], "thread_ts": click["thread_ts"] or click["message_ts"],
                                                        "text": text, "unfurl_links": False}, self.deadline)
        self.result["thread_posted"] = body is not None
        if err:
            self.warnings.append("thread reply not posted: " + clip(err, 200))

    # -- the table
    def load_row(self):
        cfg = self.cfg
        if not cfg["workato_api_token"]:
            self.warnings.append("no workato_api_token: the error log was not read or written")
            return
        try:
            found = find_row(cfg, BASE_COLUMNS["master_job_id"], self.job["master"], self.deadline) if self.job["master"] else None
            if not found and self.click["message_ts"]:
                found = find_row(cfg, TRACK_COLUMNS["slack_ts"], self.click["message_ts"], self.deadline)
        except Exception as exc:  # noqa: BLE001
            self.warnings.append("error log not read: " + clip(str(exc), 200))
            return
        self.row = found
        self.stored = found[1] if found else {}

    def write(self, fields, base_fields=None):
        cfg, result = self.cfg, self.result
        if not cfg["workato_api_token"]:
            return
        base = dict(base_fields or {})
        if not self.row and not self.job["master"]:
            self.warnings.append("no error log row for this click, and no job to make one for")
            return
        if not self.row:
            # The job has no row (its logging failed, or it is older than the log): make one. A status is
            # needed, or the old summary recipe would count the row as an error nobody was told about.
            base.setdefault(BASE_COLUMNS["status"], "Notified")
            base.setdefault(BASE_COLUMNS["master_job_id"], self.job["master"])
            base.setdefault(BASE_COLUMNS["recipe_id"], self.job["recipe_id"])
            base.setdefault(BASE_COLUMNS["recipe_name"], self.job["recipe_name"] or "Unknown recipe")
            base.setdefault(BASE_COLUMNS["job_id"], self.job["job_id"] or self.job["master"])
            base.setdefault("Date", self.now.date().isoformat())
        clean = {k: v for k, v in fields.items() if v is not None}
        try:
            action, rid, note = save_row(cfg, self.row, self.job["master"], clean, base, self.deadline)
        except Exception as exc:  # noqa: BLE001
            result.update({"row_action": "failed", "row_error": clip(str(exc), 300)})
            self.warnings.append("error log not written: " + clip(str(exc), 240))
            return
        result.update({"row_action": action, "row_record_id": rid})
        if note:
            self.warnings.append(note)


def refuse(run, why, line):
    run.result.update({"refused": why, "result": line, "handled": True})
    run.whisper(line)


def do_reprocess(run):
    cfg, job, user, now, result = run.cfg, run.job, run.user, run.now, run.result
    if not (job["master"] and job["recipe_id"]):
        return refuse(run, "no job", "This message does not say which job to reprocess.")
    if not cfg["workato_api_token"]:
        return refuse(run, "no workato_api_token", "Reprocess is not set up: the step has no Workato token.")
    if cfg["allowed"] and user["id"].upper() not in cfg["allowed"]:
        return refuse(run, "not allowed", "You are not on the list of people who may reprocess jobs.")
    stored = run.stored
    last = parse_when(stored.get(TRACK_COLUMNS["reprocessed_at"]))
    if last and cfg["cooldown_minutes"] and timedelta(0) <= now - last < timedelta(minutes=cfg["cooldown_minutes"]):
        who = text_of(stored.get(TRACK_COLUMNS["reprocessed_by"])) or "someone"
        ago = max(1, int((now - last).total_seconds() // 60))
        again = text_of(stored.get(TRACK_COLUMNS["reprocess_job_id"]))
        return refuse(run, "cooldown", "Already reprocessed {} min ago by {}{}. Give it a moment before trying again.".format(
            ago, who, " (job {})".format(again) if again else ""))
    count = to_int(stored.get(BASE_COLUMNS["reprocess_count"]), 0) or 0
    if count >= cfg["max_reprocess"]:
        return refuse(run, "max reprocess", "This job has been reprocessed {} times already (the limit is {}). "
                      "Look at the cause instead of running it again.".format(count, cfg["max_reprocess"]))
    out = repeat_job(cfg, job["recipe_id"], job["master"], run.deadline)
    result.update({"reprocess_attempted": True, "reprocess_enqueued": out["enqueued"], "reprocess_job_id": out["job_id"],
                   "reprocess_error": out["error"], "handled": True})
    if out["enqueued"]:
        said = "queued as job {}".format(out["job_id"]) if out["job_id"] else "queued"
        fields = common_fields(user, now, "Reprocess", said, run.stored)
        fields.update({TRACK_COLUMNS["reprocessed_by"]: user["name"], TRACK_COLUMNS["reprocessed_by_id"]: user["id"],
                       TRACK_COLUMNS["reprocessed_by_email"]: user["email"] or None, TRACK_COLUMNS["reprocessed_at"]: now.isoformat(),
                       TRACK_COLUMNS["reprocess_job_id"]: out["job_id"] or None, TRACK_COLUMNS["reprocess_source"]: SOURCE,
                       TRACK_COLUMNS["reprocess_result"]: "enqueued", TRACK_COLUMNS["reprocess_error"]: ""})
        run.write(fields, {BASE_COLUMNS["status"]: "Reprocessed", BASE_COLUMNS["reprocess_count"]: count + 1,
                           BASE_COLUMNS["reprocess_flag"]: False})
        result["result"] = "Reprocess {}".format(said)
        line = "♻️ *Reprocess queued* by <@{}> · {}{}".format(user["id"], slack_when(now),
                                                              " · job `{}`".format(out["job_id"]) if out["job_id"] else "")
        if out["job_id"]:
            # a thread message of its own, with a button to check on it later, instead of a plain line nobody can follow up on
            run.tell(line, remove={ACT_REPROCESS}, thread=False)   # resolving and acknowledging stay possible
            run.post_check_thread(job["master"], job["recipe_id"], out["job_id"])
        else:
            run.tell(line, remove={ACT_REPROCESS},
                     thread="♻️ {} reprocessed this job: {}.".format(sx(user["name"]), said))
        return
    said = "failed: " + clip(out["error"], 200)
    fields = common_fields(user, now, "Reprocess", said, run.stored)
    fields.update({TRACK_COLUMNS["reprocess_source"]: SOURCE, TRACK_COLUMNS["reprocess_result"]: "failed",
                   TRACK_COLUMNS["reprocess_error"]: clip(out["error"], 400)})
    run.write(fields)                                   # the old columns stay as they were: nothing was reprocessed
    result["result"] = "Reprocess " + said
    result["error"] = "reprocess failed: " + clip(out["error"], 300)
    line = "❌ *Reprocess failed* ({}) · {} · {}".format(sx(user["name"]), slack_when(now), sx(clip(out["error"], 160)))
    run.tell(line, remove=(), thread="❌ Reprocess by {} failed: {}".format(sx(user["name"]), sx(clip(out["error"], 200))))
    run.whisper("The reprocess did not start: {}".format(clip(out["error"], 300)))


def do_acknowledge(run):
    user, now = run.user, run.now
    already = text_of(run.stored.get(TRACK_COLUMNS["acknowledged_by"]))
    fields = common_fields(user, now, "Acknowledge", "acknowledged", run.stored)
    fields.update({TRACK_COLUMNS["acknowledged_by"]: user["name"], TRACK_COLUMNS["acknowledged_at"]: now.isoformat()})
    run.write(fields)
    run.result.update({"handled": True, "result": "Taken by " + user["name"]})
    run.tell("🙋 <@{}> *is looking into it* · {}".format(user["id"], slack_when(now)), remove={ACT_ACK},
             thread="👀 {} is looking at this{}.".format(sx(user["name"]), " (it was already acknowledged by {})".format(sx(already)) if already else ""))


def do_resolve(run):
    cfg, user, now = run.cfg, run.user, run.now
    if cfg["allowed"] and user["id"].upper() not in cfg["allowed"]:
        return refuse(run, "not allowed", "You are not on the list of people who may resolve errors.")
    fields = common_fields(user, now, "Resolve", "resolved", run.stored)
    fields.update({TRACK_COLUMNS["resolved_by"]: user["name"], TRACK_COLUMNS["resolved_at"]: now.isoformat()})
    run.write(fields)
    run.result.update({"handled": True, "result": "Resolved by " + user["name"]})
    run.tell("✅ *Resolved* by <@{}> · {}".format(user["id"], slack_when(now)), remove={ACT_REPROCESS, ACT_RESOLVE, ACT_ACK, ACT_ASSIGN},
             thread="✅ {} marked this error as resolved.".format(sx(user["name"])))


def do_assign(run):
    cfg, user, now, click = run.cfg, run.user, run.now, run.click
    target = click["selected_user"]
    if not target:
        return refuse(run, "no user", "Pick a person to assign this to.")
    other = slack_user(cfg, target, "", run.deadline) if target != user["id"] else dict(user)
    fields = common_fields(user, now, "Assign", "assigned to {}".format(who_line(other)), run.stored)
    fields[TRACK_COLUMNS["assigned_to"]] = who_line(other)
    run.write(fields)
    run.result.update({"handled": True, "assigned_user_id": target, "result": "Assigned to " + other["name"]})
    run.tell("🙋 *Assigned to* <@{}> by <@{}> · {}".format(target, user["id"], slack_when(now)), remove=(),
             thread="🙋 <@{}> this error was assigned to you by {}.".format(target, sx(user["name"])))


def do_feedback(run):
    user, now, click = run.user, run.now, run.click
    value = click["value"].strip().lower()
    if value not in ("positive", "negative"):
        return refuse(run, "bad feedback", "That feedback was not positive or negative.")
    stamp = now.isoformat()
    line = " | ".join((stamp, who_line(user), "AI feedback", value))
    run.write({TRACK_COLUMNS["ai_feedback"]: value, TRACK_COLUMNS["action_log"]: merge_log(run.stored.get(TRACK_COLUMNS["action_log"]), line)})
    run.result.update({"handled": True, "feedback": value, "result": "AI feedback: " + value})
    run.whisper("Thanks for the feedback: {}.".format("glad it helped" if value == "positive" else "noted, the analysis needs work"))


def do_check(run):
    """The 'Check status' button on a reprocess's thread reply. Workato's job status says whether the new job is still running;
    once it is finished, the error log row (keyed on the same master job, same as everywhere else in these two steps) is what says
    whether it actually went through: Workato calls a handled error a success, so the row's Status is the one to trust."""
    cfg, click, now, result = run.cfg, run.click, run.now, run.result
    job_id, recipe_id = run.job["job_id"], run.job["recipe_id"]
    if not (job_id and recipe_id):
        return refuse(run, "no job", "This button does not say which job to check.")
    if not cfg["workato_api_token"]:
        return refuse(run, "no workato_api_token", "Checking needs a Workato token.")
    result["handled"] = True
    try:
        value = json.loads(click["value"]) if click["value"].strip().startswith("{") else {}
    except ValueError:
        value = {}
    reprocessed_at = parse_when(value.get("t"))
    try:
        body = workato_get(cfg, "/recipes/{}/jobs/{}".format(urllib_parse.quote(recipe_id), urllib_parse.quote(job_id)), run.deadline)
    except Exception as exc:  # noqa: BLE001 - a failed check must never raise
        run.warnings.append("job status not read: " + clip(str(exc), 200))
        result["result"] = "check failed: " + clip(str(exc), 200)
        run.whisper("Could not check the job right now: {}".format(clip(str(exc), 200)))
        return
    if not job_finished(body):
        result["check_result"] = "running"
        result["result"] = "still running"
        run.update_check("⏳ *Still running* · last checked {}".format(slack_when(now)), "🔄 Check again")
        return
    status = text_of(run.stored.get(BASE_COLUMNS["status"])).strip().lower()
    error_ts = parse_when(run.stored.get("Error TimeStamp"))
    failed_again = status == "failed again" and (not reprocessed_at or not error_ts or error_ts >= reprocessed_at)
    log_fields = common_fields(run.user, now, "Check", "failed again" if failed_again else "completed", run.stored)
    if failed_again:
        message = text_of(run.stored.get("Error Message")).strip() or "(the error log row has no error message)"
        result.update({"check_result": "failed_again", "result": "failed again"})
        log_fields[TRACK_COLUMNS["reprocess_result"]] = "failed_again"
        run.write(log_fields)
        run.update_check("❌ *Failed again* · {}".format(slack_when(now)))
        shown = clip(message, 2800).replace('''```''', "'''")
        run.post_thread("🚨 *The reprocessed job failed again*\n```{}```".format(shown))
    else:
        result.update({"check_result": "completed", "result": "completed"})
        log_fields[TRACK_COLUMNS["reprocess_result"]] = "completed"
        run.write(log_fields)
        run.update_check("✅ *Completed* · {}".format(slack_when(now)))


HANDLERS = {"reprocess": do_reprocess, "acknowledge": do_acknowledge, "resolve": do_resolve, "assign": do_assign,
            "feedback": do_feedback, "check": do_check}


# ================================================================================================ POST: the alert
#
# The alert as a compact Slack message built from `alert_json`, the facts error_notification.py works out (history, job and
# recipe, the AI story, the retry decision) and hands on as one output. Top to bottom, the order of an email for a wider and
# wider audience, the technical part and the actions last:
#   1 a plain-language message for the business: the headline, what happened, the impact
#   2 one carousel, a card to a section: what to do next / the error, where it broke, the failed records / how often, run
#     health, worth knowing / under the hood, ids, handling (the last three are for the developer)
#   3 the failed records, folded, as a table with page navigation (data_table)
#   4 the technical details, folded (every id, system, file and setting)
#   5 the buttons: links, then Reprocess / Acknowledge / Mark resolved / Assign to, then thumbs on the AI analysis
# Every new block is a feature that Slack may refuse; an invalid_blocks answer takes that one feature out and the message goes
# again, down to a plain card, then to text. Charts, run-health tiles, fact chips and the recent-failures table are there but
# off unless slack_features asks for them (the message is meant to be short).
# NOT used, on purpose: plan and task_card (Slack refuses them in an ordinary message), input blocks (modals only) and
# fallback_canary (a test block for clients).

SLACK_FEATURES = ("headers", "bar", "grid", "cards", "panels", "datatables", "tables", "rich", "feedback",
                  "chips", "tiles", "adaptive", "charts", "markdown")
DEFAULT_FEATURES = ("headers", "bar", "grid", "cards", "panels", "datatables", "tables", "rich", "feedback")
BAR_COLOR = "#DC2626"         # the short look sits in one attachment with a red bar: it reads as an error at a glance
LAST_SENT = {}                # the last message posted (for the command line preview)
SLACK_BUTTONS = ("reprocess", "acknowledge", "resolve", "assign")
SL_HEADER, SL_SECTION, SL_FIELD, SL_BUTTON = 150, 2900, 1900, 75
SL_CARD_TEXT, SL_CARD_BODY, SL_CAROUSEL = 150, 200, 10
SL_TABLE_ROWS, SL_TABLE_COLS, SL_TABLE_CHARS, SL_CELL = 100, 20, 9000, 280
SL_MAX_BLOCKS, SL_MAX_BYTES = 50, 90000
SL_PEEL = ("adaptive", "charts", "grid", "bar", "datatables", "panels", "cards", "tiles", "markdown", "tables", "rich", "feedback",
           "headers", "chips")                          # when Slack does not say which block it refused: likeliest to be refused first
SL_FEATURE_OF = {"layout": "tiles", "data_visualization": "charts", "container": "panels", "carousel": "cards",
                 "card": "cards", "table": "tables", "data_table": "datatables", "markdown": "markdown",
                 "condition": "adaptive", "context_actions": "feedback", "rich_text": "rich"}
AUDIENCE = {"business": "For the business", "alert": "Alert details", "stats": "Statistics", "tech": "For developers"}
TONE_LABEL = {"good": "Good news", "warn": "Worth a look", "bad": "Needs attention", "info": "Good to know"}
DOT_EMOJI = {"red": "🔴", "orange": "🟠", "yellow": "🟡", "green": "🟢", "blue": "🔵", "purple": "🟣"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
NUMBER_RE = re.compile(r"^\s*(-?\d[\d,]*(?:\.\d+)?)\s*(%|records?|rows?|items?)?\s*$", re.I)


def slack_choice(value, universe, default):
    """The set a features / buttons input asks for. Blank = the default set. Names listed = exactly those. 'all' = every one.
    '+name' adds one to what is chosen, '-name' takes one away, 'none' = nothing."""
    tokens = [t for t in re.split(r"[\s,;]+", text_of(value).strip().lower()) if t]
    if "none" in tokens:
        return frozenset()
    named = [t for t in tokens if t in universe]
    base = set(universe) if "all" in tokens else set(named) if named else set(default)
    for token in tokens:
        if token[:1] == "+" and token[1:] in universe:
            base.add(token[1:])
        elif token[:1] == "-" and token[1:] in universe:
            base.discard(token[1:])
    return frozenset(base)


class SlackLook(object):
    """Which features and buttons a message uses. Hands out block ids (en_card_1, ...), the same on every run."""

    def __init__(self, features=DEFAULT_FEATURES, buttons=SLACK_BUTTONS, old=False):
        self.features, self.buttons, self.old = frozenset(features), frozenset(buttons), old
        self._n, self.notes = {}, []

    def on(self, feature):
        return feature in self.features

    def has(self, button):
        return button in self.buttons

    def bid(self, kind):
        self._n[kind] = self._n.get(kind, 0) + 1
        return "en_{}_{}".format(kind, self._n[kind])

    def without(self, features=(), buttons=()):
        return SlackLook(self.features - set(features), self.buttons - set(buttons), self.old)


# ---- small pieces


def g(data, key, default=""):
    value = data.get(key) if isinstance(data, dict) else None
    return default if value is None else value


def fmt_int(value):
    n = to_int(value)
    return "{:,}".format(n) if n is not None else text_of(value)


def plural(count, word, many=None):
    return "{} {}".format(fmt_int(count), word if count == 1 else (many or word + "s"))


def ordinal(n):
    n = int(n)
    return "{}{}".format(n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def safe_url(value):
    url = text_of(value).strip()
    return url if re.match(r"^(https?://|mailto:)[^\s<>\"']+$", url, re.I) else ""


def sl_url(url):
    u = safe_url(url)
    return re.sub(r"[ <>|]", lambda m: "%{:02X}".format(ord(m.group())), u) if u else ""


def sl_link(label, url):
    u = sl_url(url)
    return "<{}|{}>".format(u, sx(label).replace("|", "¦")) if u else sx(label)


def mrk(text):
    return {"type": "mrkdwn", "text": text}


def pt(text, limit=SL_BUTTON):
    return {"type": "plain_text", "text": clip(text_of(text), limit) or " ", "emoji": True}


def sl_section(text, limit=SL_SECTION, expand=True, **extra):
    """A section block. Slack folds a long one behind a 'Show more' unless expand is on; every section built here is meant to be
    read in full, so it defaults to on."""
    return dict({"type": "section", "text": mrk(clip(text, limit) or " "), "expand": expand}, **extra)


def sl_context(*texts):
    return {"type": "context", "elements": [mrk(clip(t, 2900)) for t in texts if t][:10]}


def mono_s(value):
    return "`{}`".format(text_of(value).replace("`", "'")) if text_of(value).strip() else ""


def mask(cfg, text):
    """Slack is wider than an inbox: emails are shown as •••@domain (slack_mask_pii)."""
    text = text_of(text)
    return EMAIL_RE.sub(lambda m: "•••@" + m.group().split("@", 1)[1], text) if cfg["slack_mask_pii"] else text


def color_dot(value):
    """A coloured dot for a cell's colour (the caller's column colours): Slack has no cell colours."""
    raw = text_of(value).strip()
    match = re.match(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$", raw)
    if not match:
        return ""
    h = match.group(1)
    h = "".join(c * 2 for c in h) if len(h) == 3 else h
    r, gr, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    top, low = max(r, gr, b), min(r, gr, b)
    if top - low < 0.12:
        return ""                                            # grey, black or white: no colour to show
    if top == r:
        hue = (60 * ((gr - b) / (top - low))) % 360
    elif top == gr:
        hue = 60 * ((b - r) / (top - low)) + 120
    else:
        hue = 60 * ((r - gr) / (top - low)) + 240
    for limit, name in ((15, "red"), (40, "orange"), (70, "yellow"), (170, "green"), (260, "blue"), (330, "purple"), (361, "red")):
        if hue < limit:
            return DOT_EMOJI[name]
    return DOT_EMOJI["red"]


def rich_inline(text, bold=False):
    elements = []
    for index, piece in enumerate(re.split(r"`([^`]+)`", text_of(text))):
        if not piece:
            continue
        style = {}
        if index % 2:
            style["code"] = True
        if bold:
            style["bold"] = True
        element = {"type": "text", "text": piece}
        if style:
            element["style"] = style
        elements.append(element)
    return elements or [{"type": "text", "text": " "}]


def rich_block(*elements):
    return {"type": "rich_text", "elements": list(elements)}


def rich_lines(title, text):
    return {"type": "rich_text_section", "elements": rich_inline(title + "\n", bold=True) + rich_inline(text)}


def rich_list(items, ordered=False):
    return {"type": "rich_text_list", "style": "ordered" if ordered else "bullet", "indent": 0,
            "elements": [{"type": "rich_text_section", "elements": rich_inline(clip(i, 400))} for i in items]}


def preformatted(text, limit=2800):
    return {"type": "rich_text_preformatted", "elements": [{"type": "text", "text": clip(text_of(text), limit) or " "}]}


def sl_fields(pairs, head=""):
    """Sections of up to ten fields (label in bold over the value); `head` is the first one's text."""
    pairs = [(k, v) for k, v in pairs if text_of(v).strip()]
    blocks = []
    for start in range(0, len(pairs), 10):
        fields = [mrk(clip("*{}*\n{}".format(sx(k), v), SL_FIELD)) for k, v in pairs[start:start + 10]]
        block = {"type": "section", "fields": fields}
        if head and not start:
            block["text"] = mrk(head)
        blocks.append(block)
    if head and not blocks:
        blocks.append(sl_section(head))
    return blocks


def with_ids(look, blocks, kind):
    out = []
    for block in blocks:
        block = dict(block)
        block.setdefault("block_id", look.bid(kind))
        out.append(block)
    return out


def sl_panel(look, title, children, subtitle="", collapsed=True, kind="panel"):
    """A titled, collapsible container, closed to begin with. Title and subtitle are plain text."""
    block = {"type": "container", "block_id": look.bid(kind), "title": pt(title, 150), "is_collapsible": True,
             "default_collapsed": bool(collapsed), "child_blocks": with_ids(look, children, kind + "_part")}
    if subtitle:
        block["subtitle"] = pt(subtitle, 150)
    return block


def button_context(f):
    """What a click needs to know, as compact JSON for a button's value (at most 2,000 characters)."""
    data = {"v": 1, "m": g(f, "master") or g(f, "job_handle"), "r": g(f, "recipe_id"), "j": g(f, "job_handle"),
            "n": clip(g(f, "recipe_name"), 90), "e": g(f, "env"), "p": g(g(f, "sev", {}), "label"), "s": g(f, "signature")}
    if g(f, "data_table_id") and f["data_table_id"] != ERROR_TABLE_ID:
        data["d"] = f["data_table_id"]
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)[:1900]


def link_list(f):
    """[(label, url, style)] for the buttons that open a page."""
    links, out = g(f, "links", {}), []
    for label, url, style in (("View job", g(f, "job_url"), "primary"), ("Open recipe", g(f, "recipe_url"), None),
                              ("Error file", g(links, "error_file"), None), ("Runbook", g(links, "runbook"), None),
                              ("Error log", g(links, "error_log"), None)):
        if safe_url(url):
            out.append((label, url, style))
    for item in g(links, "extra", []):
        if isinstance(item, dict) and safe_url(item.get("url")) and item.get("label"):
            out.append((text_of(item["label"]), item["url"], None))
    return out


def link_buttons(items, look, prefix_id):
    return [dict({"type": "button", "text": pt(label), "url": sl_url(url), "action_id": "{}{}_{}".format(LINK_PREFIX, prefix_id, n)},
                 **({"style": style} if style else {})) for n, (label, url, style) in enumerate(items, 1)]


# ---- the parts. Each returns [(priority, block)]: when the message is over Slack's limits the highest numbers go first.


def impact_line(f):
    total, failed, count = f.get("total"), f.get("failed"), g(g(f, "rec", {}), "count", 0)
    obj = (g(f, "target_obj") or g(f, "source_obj")) + " " if (g(f, "target_obj") or g(f, "source_obj")) else ""
    target = g(f, "target") or "the target system"
    if failed is not None and total:
        return "{} of {} {}records didn't reach {}; the other {} went through.".format(
            fmt_int(failed), fmt_int(total), obj, target, fmt_int(total - failed))
    if count:
        return "{} {}didn't reach {}.".format(plural(count, obj + "record"), "", target).replace("  ", " ")
    return "The recipe stopped with an error before it finished."


def b_top(f, look, cfg):
    sev, team = g(f, "sev", {}), g(f, "team", {})
    brand = []
    for url, alt in ((g(team, "logo_url"), "Coursera"), (g(team, "team_logo_url"), g(team, "name") or "Team")):
        if sl_url(url):
            brand.append({"type": "image", "image_url": sl_url(url), "alt_text": clip(alt, 100)})
    words = ["*{}*".format(sx(team["name"])) if g(team, "name") else "", "Workato error alert", g(f, "env").upper()]
    mention = cfg["slack_mention"] if g(sev, "label") in ("Critical", "High") else ""
    brand.append(mrk(" · ".join(w for w in words if w) + ("   " + mention if mention else "")))
    head = {"type": "header", "block_id": look.bid("title"),
            "text": {"type": "plain_text", "text": clip("{} {} · {}".format(g(sev, "emoji"), g(sev, "label"), g(f, "recipe_name")),
                                                         SL_HEADER), "emoji": True}}
    if look.on("headers"):
        head["level"] = 1
    status = status_block(f, look)
    return [(0, {"type": "context", "block_id": look.bid("brand"), "elements": brand[:10]}), (0, head), (0, status)]


def status_open():
    return "🆕 *Open*  ·  nobody has picked this up yet"


def status_block(f, look):
    """The status line under the title. With the job known and the button on, a section with a "Take it" button: a click puts
    "🙋 @name is looking into it" here instead (error_click), so everyone sees who has it. Otherwise a plain line."""
    master = g(f, "master") or g(f, "job_handle")
    if look.has("acknowledge") and master and g(f, "recipe_id"):
        return {"type": "section", "block_id": STATUS_BLOCK_ID, "text": mrk(status_open()), "expand": True,
                "accessory": {"type": "button", "text": pt("🙋 Take it"), "action_id": ACT_ACK, "value": button_context(f)}}
    return {"type": "context", "block_id": STATUS_BLOCK_ID, "elements": [mrk(status_open())]}


def pills_line(f, cfg, chips=False):
    cat, h = g(f, "category", {}), g(f, "history") or {}
    parts = []
    if not chips:
        parts.append("{} {}".format(g(cat, "icon"), sx(g(cat, "label"))))
        if h:
            if h.get("week_total", 0) >= 2:
                parts.append("🔁 {}× in 7 days".format(h["week_total"]))
            elif h.get("same"):
                parts.append("🔁 {} in {} days".format(ordinal(h["occurrence"]), h["days"]))
            else:
                parts.append("✨ First in {} days".format(h["days"]))
        count = g(g(f, "rec", {}), "count", 0)
        if f.get("failed") is not None and f.get("total"):
            parts.append("🧾 {} of {} failed".format(fmt_int(f["failed"]), fmt_int(f["total"])))
        elif count:
            parts.append("🧾 {}".format(plural(count, "failed record")))
    if g(f, "cross"):
        parts.append("🌐 +{} other {}".format(f["cross"], "recipe" if f["cross"] == 1 else "recipes"))
    parts.append("⏰ " + sx(g(f, "error_time")))
    parts.append(mono_s("#" + g(f, "signature")))
    return "  ·  ".join(parts)


def b_business(f, look, cfg):
    """1. The business message: what happened in plain words, then the impact. The raw error comes later."""
    story = g(f, "story", {})
    lines = []
    if g(f, "headline"):
        lines.append("*{}*".format(sx(clip(f["headline"], 300))))
    if g(story, "functional"):
        lines.append(sx(clip(story["functional"], 600)))
    lines.append("📉 " + sx(impact_line(f)))
    if g(f, "mail_msg"):
        lines.append("💬 _{}_".format(sx(clip(mask(cfg, f["mail_msg"]), 300))))
    out = [(0, sl_section("\n".join(lines), expand=True, block_id=look.bid("business")))]
    out.append((0, sl_context(pills_line(f, cfg, look.on("chips")))))
    retry = g(f, "retry", {})
    if retry:
        out.append((0, sl_context("{} *{}*  ·  {}".format(g(retry, "icon"), sx(g(retry, "head")), sx(clip(g(retry, "detail"), 200))))))
    return out


def card(look, title, audience, key, body, buttons=None):
    c = {"type": "card", "block_id": look.bid("card"), "title": mrk(clip(title, SL_CARD_TEXT)),
         "subtitle": mrk(clip("{}{}".format(AUDIENCE[audience], " · " + key if key else ""), SL_CARD_TEXT)),
         "body": mrk(clip(body, SL_CARD_BODY))}
    if buttons:
        c["actions"] = buttons[:3]
    return c


def numbered(items, n=3, each=70):
    return "\n".join("{}. {}".format(i + 1, sx(clip(s, each))) for i, s in enumerate(items[:n]))


def numbered_raw(items, n=3, each=70):
    """Same as numbered(), unescaped: for a rich_text element, which wants the plain string, not mrkdwn-escaped."""
    return "\n".join("{}. {}".format(i + 1, clip(s, each)) for i, s in enumerate(items[:n]))


def cards_for(f, look, cfg):
    """[(priority, section order, card)]: the order is business, alert, statistics, then the developer cards."""
    story, h, rec = g(f, "story", {}), g(f, "history") or {}, g(f, "rec", {})
    cat, retry, dec = g(f, "category", {}), g(f, "retry", {}), g(f, "decision", {})
    links, cards = g(f, "links", {}), []

    def add(prio, order, c):
        cards.append((prio, order, c))

    if g(story, "steps"):
        add(1, 10, card(look, "✅ What to do next", "business", "", numbered(story["steps"], 3, 80)))
    # alert details: the error, where it broke, the failed records
    d = g(f, "details", {})
    facts = ["{} {}".format(sx(k), "*{}*".format(fmt_int(to_int(NUMBER_RE.match(v).group(1)))) if NUMBER_RE.match(v) else sx(clip(mask(cfg, v), 40)))
             for k, v in g(d, "facts", [])[:4]]
    err_lines = []
    if g(d, "headline") and d.get("facts"):
        err_lines.append("*{}*".format(sx(clip(mask(cfg, d["headline"]), 80))))
    elif g(f, "error_plain"):
        err_lines.append(sx(clip(mask(cfg, f["error_plain"]), 150)))
    if facts:
        err_lines.append(" · ".join(facts))
    if g(f, "codes"):
        err_lines.append("  ".join("`{}`{}".format(c, " ×{}".format(n) if n > 1 else "") for c, n in f["codes"][:3]))
    add(0, 20, card(look, "🧯 The error", "alert", g(cat, "label"), "\n".join(err_lines) or "No error message was passed."))
    if g(f, "source") or g(f, "target"):
        failing = g(f, "failing")
        step = "Step " + f["step"] if g(f, "step") else "Recipe"
        action = " › ".join(x for x in (g(f, "errored_app"), g(f, "errored_action")) if x) or g(f, "step_title")
        nodes = (("🔴 " if failing == "source" else "") + "*{}*".format(sx(g(f, "source") or "—")),
                 ("🔴 " if failing == "workato" else "") + "*Workato* › {}".format(sx(step)),
                 ("🔴 " if failing == "target" else "") + "*{}*".format(sx(g(f, "target") or "—")))
        sub = "\n".join(x for x in (
            "{} ➜ {} ➜ {}".format(*nodes), sx(clip(action, 60)),
            " · ".join(x for x in (sx(g(f, "source_obj")), sx(g(f, "target_obj"))) if x)) if x)
        add(2, 21, card(look, "🧭 Where it broke", "alert", "failed at {}".format(failing or "?"), sub))
    if g(f, "rows"):
        codes = g(rec, "codes", [])
        body = "{}{}".format(plural(rec.get("count") or len(f["rows"]), "failed record"),
                             "\n" + "  ".join("`{}` ×{}".format(c, n) for c, n in codes[:3]) if codes else "")
        add(1, 22, card(look, "🧾 Failed records", "alert", "table below", body))
    # statistics
    if h:
        bits = []
        bits.append("{} of the same kind in {} days".format(h["same"], h["days"]) if h.get("same") else "Nothing of this kind in {} days".format(h["days"]))
        if h.get("week_total", 0) >= 2:
            bits.append("{}× in the last 7 days".format(h["week_total"]))
        if h.get("trend"):
            bits.append("trend: " + h["trend"])
        if h.get("last_seen"):
            bits.append("last seen " + h["last_seen"])
        if h.get("reprocessed") or h.get("failed_again"):
            bits.append("retried before: {} fixed, {} failed again".format(h["reprocessed"], h["failed_again"]))
        add(2, 30, card(look, "📊 How often", "stats", ordinal(h["occurrence"]) + " time" if h.get("occurrence") else "", " · ".join(sx(b) for b in bits)))
    tiles = g(f, "tiles", [])
    if tiles and not look.on("tiles"):
        add(3, 31, card(look, "📈 Run health", "stats", "", "\n".join("*{}* {}".format(sx(t["value"]), sx(t["label"])) for t in tiles[:4])))
    signals = g(f, "signals", [])
    if signals:
        add(4, 32, card(look, "💡 Worth knowing", "stats", TONE_LABEL.get(signals[0].get("tone"), "Good to know"),
                        "\n".join("{} {}".format(s["icon"], sx(clip(s["text"], 90))) for s in signals[:2])))
    # for the developer
    if g(story, "technical"):
        add(2, 40, card(look, "🛠 Under the hood", "tech", g(story, "source") == "ai" and "AI analysis" or "playbook",
                        sx(clip(story["technical"].replace("`", ""), 200))))
    ids = []
    if g(f, "recipe_id"):
        ids.append("Recipe {}".format(mono_s(f["recipe_id"])))
    if g(f, "master") and f["master"] != g(f, "job_handle"):
        ids.append("Master {}".format(mono_s(f["master"])))
    if g(f, "job_handle") or g(f, "master"):
        ids.append("Job {}".format(mono_s(g(f, "job_handle") or f["master"])))
    if g(f, "step"):
        ids.append("Step {}".format(sx(f["step"])))
    if g(f, "errored_app") or g(f, "errored_action"):
        ids.append(sx(" › ".join(x for x in (g(f, "errored_app"), g(f, "errored_action")) if x)))
    buttons = link_buttons([x for x in link_list(f) if x[0] in ("View job", "Open recipe")], look, "ids")
    add(1, 41, card(look, "🆔 Where to look", "tech", "ids and links", "\n".join(ids) or "No ids were passed.", buttons))
    handling = ["{} *{}*".format(g(retry, "icon"), sx(g(retry, "head")))] if g(retry, "head") else []
    if g(dec, "source") not in ("", "off", "none"):
        how = ", ".join(x for x in (DECISION_NAMES.get(dec["source"], dec["source"]), g(dec, "confidence") if dec["source"] != "input" else "") if x)
        handling.append("Reprocessable: *{}*{}".format("yes" if dec.get("reprocessable") else "no", " (" + sx(how) + ")" if how else ""))
    if g(f, "logged_status"):
        handling.append("Logged as {}".format(sx(f["logged_status"])))
    if f.get("frequency") is not None or f.get("error_limit") is not None:
        handling.append("Deferred: every {} days / over {}".format(f.get("frequency", "—"), f.get("error_limit", "—")))
    if handling:
        add(3, 42, card(look, "♻️ Handling", "tech", "retry and log", "\n".join(handling),
                    link_buttons([x for x in link_list(f) if x[0] == "Runbook"], look, "run")))
    if len(cards) > SL_CAROUSEL:                                    # over ten: the least important go
        keep = sorted(range(len(cards)), key=lambda i: (cards[i][0], i))[:SL_CAROUSEL]
        cards = [cards[i] for i in sorted(keep)]
    return [(order, c) for _, order, c in sorted(cards, key=lambda x: x[1])]


DECISION_NAMES = {"ai": "AI", "ai+rules": "AI + rules", "rules": "rules", "input": "caller"}


def b_cards(f, look, cfg):
    if look.on("cards"):
        cards = [c for _, c in cards_for(f, look, cfg)]
        return [(3, {"type": "carousel", "elements": cards})] if cards else []
    # without cards: the same words, in one section per audience
    out = []
    for _, c in cards_for(f, look, cfg):
        out.append((3, sl_section("*{}*  ·  _{}_\n{}".format(c["title"]["text"], c["subtitle"]["text"], c["body"]["text"]))))
    return out


def table_cells(f, cfg):
    """The failed records as rows of cell dicts: text (masked, clipped), bold, url, dot, code."""
    rec, cols = g(f, "rec", {}), g(f, "cols", [])
    rows = f.get("rows", [])[:min(cfg["max_table_rows"], SL_TABLE_ROWS)]
    out = []
    for row in rows:
        cells = []
        for col in cols[:SL_TABLE_COLS]:
            cell = row[col["i"] - 1]
            text = clip(mask(cfg, cell["value"]), SL_CELL).strip()
            code = ""
            if col["i"] == rec.get("err_col"):
                match = re.match(r"^\s*([A-Z][A-Z_]{3,})\s*:\s*(.*)$", text, re.S)
                if match:
                    code, text = match.group(1), match.group(2)
            bold = bool(cell["bold"]) and text_of(cell["bold"]).lower() not in ("no", "n", "false", "0")
            cells.append({"text": text, "code": code, "bold": bold, "url": sl_url(cell["url"]), "dot": color_dot(cell["color"]),
                          "id": col["i"] in g(rec, "id_cols", [])})
        out.append(cells)
    return out


def cell_label(cell):
    return ((cell["dot"] + " " if cell["dot"] else "") + (cell["code"] + ": " if cell["code"] else "") + cell["text"]).strip() or " "


def rich_cell_of(cell, bold=False):
    elements = []
    if cell["dot"]:
        elements.append({"type": "text", "text": cell["dot"] + " "})
    if cell["code"]:
        elements.append({"type": "text", "text": cell["code"], "style": {"bold": True, "code": True}})
        elements.append({"type": "text", "text": " "})
    element = ({"type": "link", "url": cell["url"], "text": cell["text"] or cell["url"]} if cell["url"]
               else {"type": "text", "text": cell["text"] or " "})
    if bold or cell["bold"]:
        element["style"] = {"bold": True}
    elements.append(element)
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": elements}]}


def b_records(f, look, cfg):
    """3. The failed records, folded, as a table with page navigation (data_table; then table; then a text grid)."""
    if not (g(f, "cols") and g(f, "rows")):
        return []
    cols = f["cols"][:SL_TABLE_COLS]
    headers = [clip(c["name"], 60) for c in cols]
    grid, used = [], sum(len(h) for h in headers)
    for row in table_cells(f, cfg):
        size = sum(len(cell_label(c)) + len(c["url"]) for c in row)
        if grid and used + size > SL_TABLE_CHARS:
            break
        grid.append(row)
        used += size
    count = g(g(f, "rec", {}), "count", len(f["rows"])) or len(f["rows"])
    numeric = []
    for n in range(len(cols)):
        values = [row[n]["text"].replace(",", "") for row in grid]
        numeric.append(bool(values) and not grid[0][n]["id"] and all(re.match(r"^-?\d{1,12}(\.\d+)?$", v) for v in values)
                       and not any(row[n]["url"] or row[n]["bold"] or row[n]["dot"] for row in grid))
    if look.on("datatables"):
        rows = [[{"type": "raw_text", "text": h or " "} for h in headers]]
        for row in grid:
            cells = []
            for n, cell in enumerate(row[:len(cols)]):
                if numeric[n]:
                    value = float(cell["text"].replace(",", ""))
                    cells.append({"type": "raw_number", "value": int(value) if value == int(value) else value, "text": cell["text"]})
                elif cell["url"] or cell["bold"] or cell["code"] or cell["dot"]:
                    cells.append(rich_cell_of(cell))
                else:
                    cells.append({"type": "raw_text", "text": cell_label(cell)})
            rows.append(cells)
        table = {"type": "data_table", "caption": "Failed records", "rows": rows}
    elif look.on("tables"):
        rows = [[rich_cell_of({"text": h or " ", "code": "", "bold": True, "url": "", "dot": ""}, bold=True) for h in headers]]
        rows += [[rich_cell_of(c) for c in row[:len(cols)]] for row in grid]
        table = {"type": "table", "rows": rows, "column_settings": [{"align": "left", "is_wrapped": True} for _ in cols]}
    else:
        widths = [min(34, max([len(headers[n])] + [len(cell_label(r[n])) for r in grid])) for n in range(len(cols))]
        lines = ["  ".join(headers[n].ljust(widths[n]) for n in range(len(cols))).rstrip()]
        lines += ["  ".join(clip(cell_label(r[n]), widths[n]).ljust(widths[n]) for n in range(len(cols))).rstrip() for r in grid]
        table = (rich_block(preformatted("\n".join(lines), 2800)) if look.on("rich")
                 else sl_section("```{}```".format("\n".join(lines).replace("```", "'''"))))
    notes = []
    if g(g(f, "rec", {}), "codes"):
        notes.append("  ".join("`{}` ×{}".format(c, n) for c, n in f["rec"]["codes"][:6]))
    if len(grid) < count:
        notes.append("Showing the first {} of {}{}".format(len(grid), fmt_int(count),
                     ": the full list is in the error file." if g(g(f, "links", {}), "error_file") else "."))
    kids = [table] + ([sl_context(*notes)] if notes else [])
    if look.on("panels"):
        return [(2, sl_panel(look, "Failed records · {}".format(plural(count, "row")), kids, subtitle="Open to page through them",
                             kind="records"))]
    return [(2, sl_section("🧾 *Failed records*  ·  {}".format(plural(count, "row"))))] + [(2, k) for k in kids]


def b_technical(f, look, cfg):
    """4. The technical details, folded: everything the email's technical details and job card say."""
    inp, d, rec = f, g(f, "decision", {}), g(f, "repeat", {})
    where = " · ".join(x for x in ("Line {}".format(f["step"]) if g(f, "step") else "",
                                   " › ".join(x for x in (g(f, "errored_app"), g(f, "errored_action")) if x)) if x)
    groups = [("Failure", [("Failed at", sx(where)), ("Error time", sx(g(f, "error_time"))),
                           ("Retries", fmt_int(f["retry_count"]) if f.get("retry_count") is not None else ""),
                           ("Priority", sx(g(f, "priority_raw")) + (" → " + g(g(f, "sev", {}), "label") if f.get("priority_changed") else "")
                            if g(f, "priority_raw") else sx(g(g(f, "sev", {}), "label"))),
                           ("Environment", sx(g(f, "env")))])]
    master, handle = g(f, "master"), g(f, "job_handle")
    ids = [("Recipe", sl_link(g(f, "recipe_name"), g(f, "recipe_url"))), ("Recipe ID", mono_s(g(f, "recipe_id")))]
    if master and handle and master != handle:
        ids += [("Child job", sl_link(handle, g(f, "job_url"))), ("Parent job", mono_s(master))]
    elif handle or master:
        ids.append(("Job", sl_link(handle or master, g(f, "job_url"))))
    if g(f, "developer"):
        ids.append(("Developer", sx(f["developer"])))
    groups.append(("Workato", ids))
    groups.append(("Systems", [(label, "*{}*{}".format(sx(system) or "—", " › " + sx(obj) if obj else ""))
                               for label, system, obj in (("Source", g(f, "source"), g(f, "source_obj")),
                                                          ("Target", g(f, "target"), g(f, "target_obj"))) if system or obj]))
    retry = g(f, "retry", {})
    handling = [("Logged as", sx(g(f, "logged_status"))), ("Retry", "*{}*".format(sx(g(retry, "head"))))]
    if f.get("frequency") is not None or f.get("error_limit") is not None:
        handling.append(("Notify", sx(" or ".join(x for x in ("every {}".format(plural(f["frequency"], "day")) if f.get("frequency") is not None else "",
                                                               "over {}".format(plural(f["error_limit"], "error")) if f.get("error_limit") is not None else "") if x))))
    if g(d, "source") not in ("", "off", "none"):
        how = ", ".join(x for x in (DECISION_NAMES.get(d["source"], d["source"]), g(d, "confidence") if d["source"] != "input" else "") if x)
        handling.append(("Reprocessable", "*{}*{}".format("Yes" if d.get("reprocessable") else "No", " · " + sx(how) if how else "")))
    if rec.get("enqueued"):
        handling.append(("Auto-retry", "Queued" + (" as " + mono_s(rec["job_id"]) if g(rec, "job_id") else "")))
    elif rec.get("attempted"):
        handling.append(("Auto-retry", "Failed: " + sx(clip(g(rec, "error"), 160))))
    flags = [n for n, on in (("Scheduled run", f.get("sch_run")), ("Repeated alert", f.get("is_repeated"))) if on]
    if flags:
        handling.append(("Run type", sx(", ".join(flags))))
    handling.append(("Reference", mono_s("#{} · {}".format(g(f, "signature"), g(g(f, "category", {}), "key")))))
    groups.append(("Handling", handling))
    job, recipe = g(f, "job") or {}, g(f, "recipe") or {}
    jobinfo = []
    if job:
        jobinfo += [("Status now", sx(g(job, "status") or "unknown")), ("Started", sx(g(job, "started"))), ("Ran for", sx(g(job, "duration"))),
                    ("Steps run", fmt_int(job["steps"]) if job.get("steps") is not None else ""), ("Failed at", sx(g(job, "failed_at"))),
                    ("Error type", sx(g(job, "error_type"))), ("Slowest step", sx(g(job, "slowest")))]
    if recipe:
        jobinfo += [("Recipe state", "🟢 Running" if recipe.get("running") is True else "🔴 Stopped" if recipe.get("running") is False else ""),
                    ("Version", sx(" · ".join(x for x in ("v{}".format(recipe["version"]) if recipe.get("version") else "",
                                                          "changed " + recipe["changed"] if g(recipe, "changed") else "") if x))),
                    ("Changed by", sx(g(recipe, "editor"))), ("Apps", sx(g(recipe, "apps")))]
    groups.append(("Job & recipe", jobinfo))
    files = [("File name", mono_s(g(f, "file_name"))), ("Error file path", mono_s(g(f, "error_file_path"))),
             ("Link expires", sx(g(f, "error_file_expires"))),
             ("Error file", sl_link("Open the file", g(g(f, "links", {}), "error_file")) if g(g(f, "links", {}), "error_file") else "")]
    groups.append(("Files", files))
    groups.append(("Notification", [("Subject", sx(clip(mask(cfg, g(f, "subject_in")), 200))), ("Alert address", sx(mask(cfg, g(f, "to_email")))),
                                    ("Time zone", sx(g(f, "timezone")))]))
    kids = []
    raw = mask(cfg, g(f, "error_plain"))
    if raw and (len(raw) > 150 or not g(g(f, "details", {}), "facts")):      # the message shows the start of it, or its facts
        text = clip(raw, min(g(f, "max_error_chars", 3000), 2800))
        kids.append(rich_block(rich_lines("Full error message", ""), preformatted(text)) if look.on("rich")
                    else sl_section("*Full error message*\n```{}```".format(text.replace("```", "'''"))))
    for title, pairs in groups:
        kids.extend(sl_fields([p for p in pairs if text_of(p[1]).strip()], head="*{}*".format(title))
                    if any(text_of(p[1]).strip() for p in pairs) else [])
    if g(f, "last_jobs"):
        squares = {"ok": "🟩", "fail": "🟥", "pending": "⬜"}
        kids.append(sl_context("*Last {} jobs* (newest first)  {}".format(len(f["last_jobs"]), "".join(squares.get(s, "⬜") for s in f["last_jobs"]))))
    content = text_of(g(f, "file_content"))
    if content.strip():
        shown = clip(mask(cfg, content), 1500)
        kids.append(rich_block(rich_lines("File content (preview)", ""), preformatted(shown, 1500)) if look.on("rich")
                    else sl_section("*File content (preview)*\n```{}```".format(shown.replace("```", "'''"))))
    if not kids:
        return []
    if look.on("panels"):
        return [(4, sl_panel(look, "Technical details", kids, subtitle="Ids, systems, handling, job, files, the full error", kind="tech"))]
    return [(4, sl_section("🛠️ *Technical details*"))] + [(4, k) for k in kids]


def b_actions(f, look, cfg):
    """5. Last: the buttons. Links first, then the ones that do something (they start with ACTION_PREFIX, so one trigger filter
    catches them all), then thumbs on the AI analysis."""
    out = []
    links = link_list(f)
    if links:
        out.append((0, {"type": "actions", "block_id": look.bid("links"), "elements": link_buttons(links[:6], look, "bar")}))
    master = g(f, "master") or g(f, "job_handle")
    if look.buttons and master and g(f, "recipe_id"):
        value = button_context(f)
        elements = []
        if look.has("reprocess") and not g(g(f, "repeat", {}), "enqueued", False):     # a retry already queued: a second would run the job twice
            dec = g(f, "decision", {})
            likely = bool(dec.get("reprocessable"))
            note = ("The analysis says a re-run should work." if likely else
                    "The AI advised against a re-run: fix the cause first." if g(dec, "source") in ("ai", "ai+rules") else
                    "It was not retried automatically: make sure the cause is fixed.")
            button = {"type": "button", "text": pt("♻️ Reprocess"), "action_id": ACT_REPROCESS, "value": value,
                      "confirm": {"title": pt("Reprocess this job?", 100),
                                  "text": mrk(clip("This repeats master job `{}` of *{}* through the Workato API. {}".format(
                                      sx(master), sx(clip(g(f, "recipe_name"), 80)), note), 300)),
                                  "confirm": pt("Yes, reprocess", 30), "deny": pt("Cancel", 30)}}
            if likely:
                button["style"] = "primary"
            elements.append(button)
        if look.has("resolve"):
            elements.append({"type": "button", "text": pt("✅ Mark resolved"), "action_id": ACT_RESOLVE, "value": value,
                             "confirm": {"title": pt("Mark as resolved?", 100), "text": mrk("This records that the error has been dealt with."),
                                         "confirm": pt("Yes, resolved", 30), "deny": pt("Cancel", 30)}})
        if look.has("assign"):
            elements.append({"type": "users_select", "action_id": ACT_ASSIGN, "placeholder": pt("🙋 Assign to…", 150)})
        if elements:      # the block id carries the job, because a users_select has no value to carry it
            out.append((0, {"type": "actions", "block_id": "{}|{}|{}".format(ACTIONS_BLOCK_ID, master, g(f, "recipe_id"))[:250],
                            "elements": elements}))
    story = g(f, "story", {})
    if look.on("feedback") and look.buttons and g(story, "source") == "ai":
        out.append((8, {"type": "context_actions", "block_id": look.bid("feedback"), "elements": [{
            "type": "feedback_buttons", "action_id": ACT_FEEDBACK,
            "positive_button": {"text": pt("Helpful analysis", 75), "value": "positive"},
            "negative_button": {"text": pt("Not helpful", 75), "value": "negative"}}]}))
    return out


def b_footer(f, look, cfg):
    team, links = g(f, "team", {}), []
    if g(team, "alert_email"):
        links.append(sl_link("Email the team", "mailto:" + team["alert_email"]))
    for label, key in (("ServiceNow", "servicenow_url"), ("Slack", "slack_url"), ("Team Charter", "charter_url")):
        if safe_url(g(team, key)):
            links.append(sl_link(label, team[key]))
    note = "Automated alert from Workato integration monitoring · error_v2 {} · #{} · {}".format(
        g(f, "version"), g(f, "signature"), g(f, "now_text"))
    return [(0, sl_context(*([" · ".join(links)] if links else []), sx(note)))]


# ---- parts you can switch on (slack_features): chips, tiles, charts, the recent-failures table


def b_chips(f, look, cfg):
    """Buttons that only show a fact. Their action ids are not ones the trigger passes, so a click does nothing."""
    h, chips, cat = g(f, "history") or {}, [], g(f, "category", {})
    chips.append(("{} {}".format(g(cat, "icon"), g(cat, "label")), "danger" if g(g(f, "sev", {}), "label") in ("Critical", "High") else None))
    if f.get("failed") is not None:
        chips.append(("🧾 {} failed".format(fmt_int(f["failed"])), "danger"))
    if g(f, "rate_text"):
        chips.append(("✅ {} ok".format(f["rate_text"]), "primary" if (f.get("rate") or 0) >= 99 else None))
    if h:
        chips.append(("🔁 {}× this week".format(h["week_total"]) if h.get("same") else "✨ New error", "danger" if h.get("trend") == "rising" else None))
    if f.get("retry_count") is not None:
        chips.append(("🔂 {} retries".format(f["retry_count"]), None))
    if g(f, "step"):
        chips.append(("📍 Step {}".format(clip(f["step"], 6)), None))
    elements = []
    for n, (text, style) in enumerate(chips[:5], 1):
        button = {"type": "button", "text": pt(text), "action_id": "{}{}".format(INFO_PREFIX, n), "value": "info"}
        if style:
            button["style"] = style
        elements.append(button)
    return [(4, {"type": "actions", "block_id": look.bid("chips"), "elements": elements})] if elements else []


def b_tiles(f, look, cfg):
    tiles = g(f, "tiles", [])
    if not tiles:
        return []

    def text(t):
        return "*{}*\n{}{}".format(sx(t["value"]), sx(t["label"]), " · " + sx(t["sub"]) if t.get("sub") else "")
    per_row = 4 if len(tiles) == 4 else 3
    rows = [{"items": [{"block": {"type": "section", "block_id": look.bid("tile"), "text": mrk(clip(text(t), 600)), "expand": True},
                        "width": "standard", "horizontal_alignment": "center"} for t in tiles[s:s + per_row]]}
            for s in range(0, len(tiles), per_row)]
    grid = {"type": "layout", "block_id": look.bid("tiles"), "label": "Run health", "is_label_visible": True, "grid_lines": "outer", "rows": rows}
    compact = {"type": "section", "block_id": look.bid("tilefields"), "fields": [mrk(clip(text(t), SL_FIELD)) for t in tiles[:10]]}
    if look.on("adaptive"):
        return [(4, {"type": "condition", "cases": [{"conditions": [{"type": "client", "op": "=", "value": "desktop"}], "blocks": [grid]}],
                     "default": [compact]})]
    return [(4, grid)]


def b_charts(f, look, cfg):
    h = g(f, "history") or {}
    if not h or not h.get("chart"):
        return []
    out, chart = [], h["chart"]
    labels = [c[0] for c in chart]
    if look.on("charts") and any(c[1] or c[2] for c in chart):
        series = [{"name": "Same error", "data": [{"label": c[0], "value": c[1]} for c in chart]}]
        if any(c[2] for c in chart):
            series.append({"name": "Other errors", "data": [{"label": c[0], "value": c[2]} for c in chart]})
        out.append((6, {"type": "data_visualization", "block_id": look.bid("trend"), "title": "Failures in the last {} days".format(len(chart)),
                        "chart": {"type": "bar", "series": series, "axis_config": {"categories": labels, "x_label": "Day", "y_label": "Errors"}}}))
        if len(h.get("top", [])) >= 2:
            out.append((7, {"type": "data_visualization", "block_id": look.bid("mix"), "title": "What else fails in this recipe",
                            "chart": {"type": "pie", "segments": [{"label": k, "value": n} for k, n in h["top"][:4]]}}))
    if look.on("markdown") and h.get("recent"):
        rows = ["| When | Status | Job |", "|---|---|---|"]
        rows += ["| {} | {} | `{}` |".format(r["when"], r["status"] or "—", clip(r["job"] or "—", 30)) for r in h["recent"]]
        out.append((6, {"type": "markdown", "text": "**Recent similar failures**\n\n" + "\n".join(rows)}))
    return out


def slack_text(f, cfg):
    """The text a notification shows (and what is posted when no block is accepted)."""
    retry, sev = g(f, "retry", {}), g(f, "sev", {})
    mention = cfg["slack_mention"] + " " if cfg["slack_mention"] and g(sev, "label") in ("Critical", "High") else ""
    parts = [mention + sx(clip(g(f, "subject") or "Error in " + g(f, "recipe_name"), 300)), sx(clip(g(f, "headline"), 300)),
             "{} {}".format(g(retry, "icon"), g(retry, "head")) if retry else ""]
    if safe_url(g(f, "job_url")):
        parts.append(sl_link("View job", f["job_url"]))
    return clip("\n".join(p for p in parts if p.strip()), 3000)


def fit_blocks(items, max_blocks=SL_MAX_BLOCKS, max_bytes=SL_MAX_BYTES):
    """Drop the least important blocks (the highest priority numbers, from the bottom) until the message fits."""
    def tidy(seq):
        out = []
        for prio, block in seq:
            if block.get("type") == "divider" and (not out or out[-1][1].get("type") == "divider"):
                continue
            out.append((prio, block))
        while out and out[-1][1].get("type") == "divider":
            out.pop()
        return out
    items = tidy(items)
    while len(items) > max_blocks or len(json.dumps([b for _, b in items]).encode("utf-8")) > max_bytes:
        worst = max(p for p, _ in items)
        if worst == 0:
            break
        del items[max(i for i, (p, _) in enumerate(items) if p == worst)]
        items = tidy(items)
    return [b for _, b in items]


def build_slack(f, look, cfg):
    """The new look: (blocks, text). A part that fails to build is left out, not fatal."""
    parts = []
    names = ["b_top", "b_business", "b_chips" if look.on("chips") else "", "b_cards", "b_tiles" if look.on("tiles") else "",
             "b_charts" if (look.on("charts") or look.on("markdown")) else "", "b_records", "b_technical", "b_actions", "b_footer"]
    for name in [n for n in names if n]:
        try:
            parts.extend(globals()[name](f, look, cfg))
        except Exception as exc:  # noqa: BLE001
            look.notes.append("{} left out: {}: {}".format(name, type(exc).__name__, clip(str(exc), 120)))
    return fit_blocks(parts), slack_text(f, cfg)


def short_cards(f, look, cfg):
    """The three cards of the short look: what happened, the impact, what to do next. Business words only; the buttons sit
    in the cards: View job, the error file (or the recipe), and on the last one the buttons that do something."""
    story, h, retry, cat = g(f, "story", {}), g(f, "history") or {}, g(f, "retry", {}), g(f, "category", {})
    links = {label: (url, style) for label, url, style in link_list(f)}

    def link(label, primary=False):
        if label not in links:
            return []
        button = {"type": "button", "text": pt(label), "url": sl_url(links[label][0]), "action_id": "{}card_{}".format(
            LINK_PREFIX, re.sub(r"\W+", "_", label.lower()))}
        if primary:
            button["style"] = "primary"
        return [button]

    def body_of(raw):
        """(escaped mrkdwn, raw) for a card body, each held to SL_CARD_BODY. Escaping (&, <, >) can only lengthen the text, so
        the mrkdwn copy is clipped again after it, to keep Slack's hard limit on a card's body."""
        raw = clip(raw, SL_CARD_BODY)
        return mrk(clip(sx(raw), SL_CARD_BODY)), raw

    what = g(story, "functional") or g(f, "headline") or clip(g(f, "error_plain"), 200)
    what_body, what_raw = body_of(mask(cfg, what) or "The recipe stopped with an error.")
    first = {"type": "card", "block_id": look.bid("card"), "title": mrk("📣 *What happened*"),
             "subtitle": mrk(clip("{} {}".format(g(cat, "icon"), g(cat, "label")).strip() or "Recipe error", SL_CARD_TEXT)),
             "body": what_body, "raw_body": what_raw, "actions": link("View job", True)}
    often = ("{}× in the last 7 days".format(h["week_total"]) if h.get("week_total", 0) >= 2 else
             "{} time in {} days".format(ordinal(h["occurrence"]), h["days"]) if h.get("same") else
             "First time in {} days".format(h["days"]) if h else "")
    impact_raw = impact_line(f)
    if g(f, "rate_text"):
        impact_raw += " {} of the run went through.".format(f["rate_text"])
    impact_body, impact_raw = body_of(impact_raw)
    second = {"type": "card", "block_id": look.bid("card"), "title": mrk("📉 *Impact*"),
              "subtitle": mrk(clip(often or (g(f, "target") and "Target: " + g(f, "target")) or "This run", SL_CARD_TEXT)),
              "body": impact_body, "raw_body": impact_raw, "actions": link("Error file") or link("Open recipe")}
    steps = g(story, "steps", [])
    next_body, next_raw = body_of(numbered_raw(steps, 2, 90) if steps else clip(g(retry, "detail"), 200) or "Look at the job in Workato.")
    third = {"type": "card", "title": mrk("✅ *What to do next*"),
             "subtitle": mrk(clip("{} {}".format(g(retry, "icon"), g(retry, "head")).strip() or "Needs a person", SL_CARD_TEXT)),
             "body": next_body, "raw_body": next_raw}
    buttons = [e for _, block in b_actions(f, look, cfg) if block.get("block_id", "").startswith(ACTIONS_BLOCK_ID)
               for e in block["elements"] if e["type"] == "button"][:3]
    master = g(f, "master") or g(f, "job_handle")
    if buttons:
        third["block_id"] = "{}|{}|{}".format(ACTIONS_BLOCK_ID, master, g(f, "recipe_id"))[:250]   # a click finds the job here too
        third["actions"] = buttons
    else:
        third["block_id"] = look.bid("card")
        third["actions"] = link("Runbook") or link("Open recipe")
    cards = [first, second, third]
    for card in cards:
        if not card.get("actions"):
            card.pop("actions", None)
    return cards


def error_text(f, cfg, limit=900):
    """The error as it reads in a code block: its first line, then each fact on a line of its own with the labels lined up
    (Total Records : 35,909), then what else it said. Without facts: the message itself."""
    d = g(f, "details", {})
    facts = [(text_of(k), text_of(v)) for k, v in g(d, "facts", [])]
    if facts:
        width = min(28, max(len(k) for k, _ in facts))
        lines = [text_of(g(d, "headline")).strip()] if text_of(g(d, "headline")).strip() else []
        for k, v in facts:
            match = NUMBER_RE.match(v)
            lines.append("{} : {}".format(k.ljust(width), fmt_int(to_int(match.group(1))) if match else v.strip()))
        lines += [text_of(x).strip() for x in g(d, "extra", [])[:3] if text_of(x).strip()]
        text = "\n".join(lines)
    else:
        text = text_of(g(f, "error_plain")).strip()
    return clip(mask(cfg, text), limit) if text else ""


def error_block(f, look, cfg):
    """The main error, outside the cards, in a code block under a red label, so it reads as the error at a glance."""
    text = error_text(f, cfg)
    if not text:
        return None
    codes = "  ".join("{}{}".format(c, " ×{}".format(n) if n > 1 else "") for c, n in g(f, "codes", [])[:3])
    if look.on("rich"):
        label = [{"type": "emoji", "name": "rotating_light"}, {"type": "text", "text": " Error", "style": {"bold": True}}]
        if codes:
            label += [{"type": "text", "text": "   "}, {"type": "text", "text": codes, "style": {"code": True}}]
        return {"type": "rich_text", "block_id": look.bid("error"), "elements": [
            {"type": "rich_text_section", "elements": label}, preformatted(text, 900)]}
    return sl_section("🚨 *Error*{}\n```{}```".format("   `" + codes + "`" if codes else "", text.replace("```", "\'\'\'")))


def grid_block(f, look, cfg):
    """The short look's 2 x 2 grid (a layout of small containers): What happened | Impact, then What to do next with Reprocess
    and Mark resolved | Open with the links. Packed and narrow: each box holds a few lines."""
    cards = short_cards(f, look, cfg)
    what, impact, nxt = cards
    links = [b for c in (what, impact) for b in c.get("actions", [])]
    links += [b for b in link_buttons([x for x in link_list(f) if x[0] in ("Open recipe", "Error file", "Runbook")], look, "grid")
              if b["url"] not in {x["url"] for x in links}]

    def box(card, kind, buttons=None, block_id=None):
        # a section's text folds behind "Show more" inside a container even with expand: true (confirmed live, 2026-11-21): a
        # rich_text body never does, so that is what a box uses by default; a plain section is the fallback once rich is off.
        raw = card.get("raw_body", card["body"]["text"])
        if look.on("rich"):
            body_block = {"type": "rich_text", "block_id": look.bid(kind + "_text"),
                         "elements": [{"type": "rich_text_section", "elements": rich_inline(raw)}]}
        else:
            body_block = {"type": "section", "block_id": look.bid(kind + "_text"), "text": mrk(card["body"]["text"]), "expand": True}
        kids = [body_block]
        if buttons:
            kids.append({"type": "actions", "block_id": block_id or look.bid(kind + "_buttons"), "elements": buttons[:4]})
        return {"type": "container", "block_id": look.bid(kind), "title": pt(re.sub(r"[*_]", "", card["title"]["text"]), 150),
                "subtitle": pt(re.sub(r"[*_`]", "", card["subtitle"]["text"]), 150), "child_blocks": kids}

    actions = [a for a in nxt.get("actions", []) if "url" not in a]
    first = [{"block": box(what, "what"), "width": "standard"}, {"block": box(impact, "impact"), "width": "standard"}]
    second = [{"block": box(nxt, "next", actions, nxt.get("block_id") if actions else None) if actions else
               box(dict(nxt), "next", nxt.get("actions")), "width": "standard"}]
    if links:
        open_card = {"title": {"text": "🔗 Open"}, "subtitle": {"text": "the job, the recipe, the file"},
                     "body": {"text": "Everything else is in the email."}}
        second.append({"block": box(open_card, "open", links), "width": "standard"})
    return {"type": "layout", "block_id": look.bid("grid"), "label": "Error summary", "is_label_visible": False,
            "rows": [{"items": first}, {"items": second}]}


def build_slack_short(f, look, cfg):
    """The short look (the default): the title, one business line, the 2 x 2 grid of boxes with their buttons, one footer line.
    Nothing technical: the email has it. No carousel anywhere: without the grid (refused, or switched off) the same four come as
    plain sections with one row of buttons."""
    sev, retry = g(f, "sev", {}), g(f, "retry", {})
    blocks = [b for _, b in b_top(f, look, cfg)]
    blocks.pop(0)                                                      # no logo row: every line counts
    team, env = g(f, "team", {}), g(f, "env").upper()
    mention = cfg["slack_mention"] if g(sev, "label") in ("Critical", "High") else ""
    h = g(f, "history") or {}
    often = "🔁 {}× in 7 days".format(h["week_total"]) if h.get("week_total", 0) >= 2 else ""
    line = "  ·  ".join(x for x in ("{} *{}*".format(g(retry, "icon"), sx(g(retry, "head"))) if retry else "", often,
                                     "⏰ " + sx(g(f, "error_time")) if g(f, "error_time") else "", env, mention) if x)
    headline = g(f, "headline") or clip(g(f, "error_plain"), 200)
    text = "*{}*".format(sx(clip(mask(cfg, headline), 280)))
    blocks.insert(1, sl_section(text + ("\n" + line if line else "")))
    error = error_block(f, look, cfg)
    if error:
        blocks.insert(2, error)                                         # the error itself, outside the cards
    cards = short_cards(f, look, cfg)
    if look.on("grid"):
        blocks.append(grid_block(f, look, cfg))
    else:                                                              # refused or switched off: plain sections, never a carousel
        for card in cards:
            blocks.append(sl_section("{}  ·  _{}_\n{}".format(card["title"]["text"], card["subtitle"]["text"], card["body"]["text"])))
        buttons = [e for c in cards for e in c.get("actions", [])][:6]
        if buttons:
            blocks.append({"type": "actions", "block_id": "{}|{}|{}".format(ACTIONS_BLOCK_ID, g(f, "master") or g(f, "job_handle"),
                                                                           g(f, "recipe_id"))[:250], "elements": buttons})
    if g(f, "cols") and g(f, "rows") and (look.on("datatables") or look.on("tables")):
        # the failed records as a table with page navigation: short however many rows there are
        table = [b for _, b in b_records(f, look.without(["panels"]), cfg) if b["type"] != "section"]
        blocks.extend(table)
    blocks.append(sl_context("Full details are in the email{}  ·  `#{}`".format(
        " to " + sx(g(team, "name")) if g(team, "name") else "", g(f, "signature"))))
    return blocks, slack_text(f, cfg)


def build_slack_old(f, look, cfg):
    """The plain card: sections, fields, context and buttons only, in one attachment with a bar in the priority's colour."""
    sev, retry = g(f, "sev", {}), g(f, "retry", {})
    blocks = [sl_section("{} *{} priority*  ·  {}{}".format(g(sev, "emoji"), g(sev, "label"), sx(g(f, "recipe_name")),
                                                            "  ·  " + g(f, "env").upper() if g(f, "env") else "")),
              status_block(f, look),
              sl_section("*{}*\n{}\n📉 {}".format(sx(clip(g(f, "headline"), 300)), sx(clip(g(g(f, "story", {}), "functional"), 500)), sx(impact_line(f)))),
              sl_context(pills_line(f, cfg)),
              sl_section("{} *{}*\n{}".format(g(retry, "icon"), sx(g(retry, "head")), sx(clip(g(retry, "detail"), 300))))]
    shown = clip(mask(cfg, g(f, "error_plain")) or "No error message was passed.", 1500)
    blocks.append(sl_section("```{}```".format(shown.replace("```", "'''"))))
    fields = [("Source", "*{}*{}".format(sx(g(f, "source")) or "—", " › " + sx(g(f, "source_obj")) if g(f, "source_obj") else "")),
              ("Target", "*{}*{}".format(sx(g(f, "target")) or "—", " › " + sx(g(f, "target_obj")) if g(f, "target_obj") else "")),
              ("Failed at", sx(" · ".join(x for x in ("Step " + f["step"] if g(f, "step") else "", g(f, "errored_action")) if x))),
              ("Retries", fmt_int(f["retry_count"]) if f.get("retry_count") is not None else "")]
    blocks.extend(sl_fields(fields))
    if g(f, "rows") and g(f, "cols"):
        lines = [" | ".join(cell_label(c) for c in row) for row in table_cells(f, cfg)[:5]]
        blocks.append(sl_section("*{}*\n```{}```".format(" | ".join(c["name"] for c in f["cols"]).replace("*", ""),
                                                          "\n".join(lines).replace("```", "'''")), limit=2800))
    for _, block in b_actions(f, look, cfg):
        if block["type"] == "actions":
            blocks.append(block)
    blocks.append(sl_context(sx("error_v2 {} · #{} · {}".format(g(f, "version"), g(f, "signature"), g(f, "now_text")))))
    return [{"color": g(sev, "color") or "#64748B", "fallback": clip(slack_text(f, cfg), 300), "blocks": blocks}]


def minimal_facts(inp):
    """When alert_json is missing (the notifier failed or was not mapped): enough to say that something broke."""
    sev = {"label": "High", "emoji": "❗", "color": "#EA580C"}
    raw = text_of(inp.get("priority")).strip().lower()
    for label, emoji, color in (("Critical", "🚨", "#DC2626"), ("High", "❗", "#EA580C"), ("Medium", "⚠️", "#D97706"), ("Low", "ℹ️", "#2563EB")):
        if raw.startswith(label.lower()):
            sev = {"label": label, "emoji": emoji, "color": color}
    job = text_of(inp.get("job_url")).strip()
    match = re.search(r"/recipes/(\d+)", job)
    handle = re.search(r"/job/([\w-]+)", job)
    error = re.sub(r"<[^>]+>", " ", text_of(inp.get("error_details")))
    return {"v": 0, "version": VERSION, "sev": sev, "recipe_name": text_of(inp.get("recipe_name")) or "Unnamed recipe",
            "recipe_id": match.group(1) if match else "", "job_url": job, "job_handle": handle.group(1) if handle else "",
            "master": text_of(inp.get("calling_master_job_id")).strip() or (handle.group(1) if handle else ""),
            "subject": text_of(inp.get("subject")), "headline": clip(re.sub(r"\s+", " ", error).strip(), 200),
            "error_plain": re.sub(r"[ \t]+", " ", error).strip(), "env": "", "signature": "", "now_text": "", "error_time": "",
            "category": {}, "story": {}, "retry": {}, "send_email": True, "details": {"facts": []}, "links": {}, "team": {}}


# ---- posting


def refused_features(error, blocks, look):
    """The features Slack named in an invalid_blocks error (json pointers like /blocks/15/..), else the next in SL_PEEL."""
    found = []
    for match in re.finditer(r"/blocks/(\d+)", error):
        index = int(match.group(1))
        if index >= len(blocks):
            continue
        block = blocks[index]
        kind = block.get("type")
        feature = "headers" if kind == "header" and "level" in block else SL_FEATURE_OF.get(kind)
        if kind == "layout" and look.on("grid"):
            feature = "grid"                                    # the short look's grid of containers
        if feature and look.on(feature) and feature not in found:
            found.append(feature)
    if found:
        return found
    for feature in SL_PEEL:
        if look.on(feature):
            return [feature]
    return []


def get_permalink(cfg, channel, ts, deadline):
    if not (channel and ts):
        return "", ""
    try:
        timeout = call_timeout(cfg, deadline)
    except FetchError as exc:
        return "", str(exc)
    url = SLACK_API + "chat.getPermalink?" + urllib_parse.urlencode({"channel": channel, "message_ts": ts})
    body, err = http_json("GET", url, {"Authorization": "Bearer " + cfg["slack_bot_token"]}, None, timeout)
    if err:
        return "", err
    if not isinstance(body, dict) or not body.get("ok"):
        return "", text_of(as_dict(body).get("error") or "unknown")
    return text_of(body.get("permalink")), ""


def read_facts(inp, warnings):
    raw = inp.get("alert_json")
    if isinstance(raw, dict):
        return raw
    if text_of(raw).strip():
        try:
            data = json.loads(text_of(raw))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
        warnings.append("alert_json is not valid JSON: a short alert was posted instead")
    return None


def post_alert(inp, cfg, result, warnings, deadline, now):
    """Post the alert to slack_channel_id. Never raises: a failure is in `error` and the warnings.

    Three stages, each one only when the one before was refused as invalid: the new look (a refused feature is taken out and the
    message sent again, one at a time), the plain card, then text only. Any other answer (not_in_channel, channel_not_found,
    invalid_auth, ratelimited) is final: it would be the same for every look."""
    f = read_facts(inp, warnings)
    if f is None:
        f = minimal_facts(inp)
        result["alert_source"] = "inputs"
        if not text_of(inp.get("alert_json")).strip():
            warnings.append("no alert_json: a short alert was posted from the recipe's own inputs")
    else:
        result["alert_source"] = "alert_json"
    if not f.get("send_email", True) or f.get("deferred"):
        result["skipped"] = "not notified: " + ("the call asked for deferral (frequency / error_limit)" if f.get("deferred")
                                                else "the error is being retried")
        return
    if not cfg["slack_bot_token"]:
        result["error"] = "no slack_bot_token"
        warnings.append("Slack skipped: no slack_bot_token")
        return
    asked = SlackLook(slack_choice(cfg["slack_features"], SLACK_FEATURES, DEFAULT_FEATURES),
                      slack_choice(cfg["slack_buttons"], SLACK_BUTTONS, SLACK_BUTTONS), cfg["slack_look"] == "old")
    if cfg["slack_look"] == "full":
        asked = asked.without(["grid", "bar"])          # the grid and the red bar belong to the short look
    stage = "old" if asked.old else "new"
    look, notes, blocks, body, error = asked, [], [], None, ""
    text = slack_text(f, cfg)
    payload = {"channel": cfg["slack_channel_id"], "unfurl_links": False, "unfurl_media": False}
    if cfg["slack_thread_ts"]:
        payload["thread_ts"] = cfg["slack_thread_ts"]
    for _ in range(24):
        sent = None
        try:
            if stage == "text":
                blocks, sent = [], dict(payload, text=text)
            elif stage == "old":
                attachments = build_slack_old(f, look, cfg)
                blocks, sent = attachments[0]["blocks"], dict(payload, attachments=attachments)
            else:
                blocks, text = (build_slack if cfg["slack_look"] == "full" else build_slack_short)(f, look, cfg)
                if cfg["slack_look"] != "full" and look.on("bar"):
                    # no top-level text with an attachment: Slack would show it above the card (the genie responder's lesson)
                    sent = dict(payload, attachments=[{"color": BAR_COLOR, "fallback": clip(text, 300), "blocks": blocks}])
                else:
                    sent = dict(payload, text=text, blocks=blocks)
        except Exception as exc:  # noqa: BLE001 - a building bug must not cost the alert
            error = "building the Slack message failed: {}: {}".format(type(exc).__name__, clip(str(exc), 200))
        if sent is not None:
            LAST_SENT.clear()
            LAST_SENT.update({k: v for k, v in sent.items() if k in ("blocks", "attachments")})
            body, error = slack_call(cfg, "chat.postMessage", sent, deadline)
            if body is not None:
                break
        refused = sent is None or "invalid_blocks" in error or "invalid_attachments" in error
        if stage == "new" and sent is not None and ("invalid_blocks" in error or "invalid_attachments" in error):
            features = [x for x in refused_features(error, blocks, look) if x]
            if features:
                notes.append("Slack refused {} ({}); sent again without it".format(", ".join(features), clip(error, 200)))
                look = look.without(features=features)
                continue
        if stage == "new" and refused:
            notes.append("the new Slack look was refused ({}); sent the plain card".format(clip(error, 200)))
            stage, look = "old", SlackLook((), asked.buttons, True)
            continue
        if stage == "old" and refused:
            notes.append("the plain Slack card was refused ({}); sent text only".format(clip(error, 200)))
            stage = "text"
            continue
        break
    warnings.extend(notes + look.notes)
    if body is None:
        result["error"] = clip(error, 400)
        warnings.append("Slack not posted: " + clip(error, 240))
        return
    dropped = [x for x in SLACK_FEATURES if x in asked.features and x not in look.features]
    used = {"text": "text", "old": "old"}.get(stage) or ("new" if not dropped else "new (without {})".format(", ".join(dropped)))
    channel, ts = text_of(body.get("channel") or cfg["slack_channel_id"]), text_of(body.get("ts"))
    result.update({"posted": True, "channel": channel, "message_ts": ts, "look_used": used, "text": text, "blocks": len(blocks),
                   "blocks_json": json.dumps(blocks, ensure_ascii=False) if blocks else ""})
    link, why = get_permalink(cfg, channel, ts, deadline)
    if link:
        result["permalink"] = link
    elif why:
        warnings.append("Slack link not read: " + clip(why, 160))
    # what only the post knows goes to the error log row the notifier wrote: where the message is, and when
    master = text_of(f.get("master"))
    if cfg["workato_api_token"] and master:
        try:
            found = find_row(cfg, BASE_COLUMNS["master_job_id"], master, deadline)
            if not found:
                warnings.append("Slack message not saved to the error log: there is no row for this job yet")
            else:
                fields = {TRACK_COLUMNS["notified_via"]: "Email + Slack" if f.get("send_email", True) else "Slack",
                          TRACK_COLUMNS["slack_channel"]: channel, TRACK_COLUMNS["slack_ts"]: ts,
                          TRACK_COLUMNS["slack_url"]: link or None, TRACK_COLUMNS["notified_at"]: now.isoformat()}
                action, rid, note = save_row(cfg, found, master, {k: v for k, v in fields.items() if v is not None}, {}, deadline)
                result.update({"row_action": action, "row_record_id": rid})
                if note:
                    warnings.append(note)
        except Exception as exc:  # noqa: BLE001
            result.update({"row_action": "failed", "row_error": clip(str(exc), 300)})
            warnings.append("Slack message not saved to the error log: " + clip(str(exc), 200))


# ------------------------------------------------------------------------------------------------ entry point


def click_flow(inp, cfg, result, warnings, now, deadline):
    """A click on a button: parse it, do the action, write it down, say it in Slack."""
    checked, bad = verify_signature(cfg, inp, now)
    result["signature_checked"] = checked
    if bad:
        result.update({"ok": False, "refused": "bad signature", "error": "request refused: " + bad})
        return

    click = parse_click(inp)
    result.update({"channel": click["channel"], "message_ts": click["message_ts"], "user_id": click["user_id"]})
    action_id = click["action_id"]
    if action_id.startswith((INFO_PREFIX, LINK_PREFIX)):
        result.update({"ok": True, "action": "noop", "result": "nothing to do: a link or a fact"})
        return
    if not action_id.startswith(ACTION_PREFIX):
        result.update({"ok": True, "action": "ignored", "result": "not an error alert action: {!r}".format(clip(action_id, 80))})
        return
    name = ACTIONS.get(action_id)
    if not name:
        result.update({"ok": True, "action": "unknown", "result": "no such action: {!r}".format(clip(action_id, 80))})
        return
    result["action"] = name

    job = job_context(click)
    if job.get("table"):
        cfg["data_table_id"] = job["table"]
    user = slack_user(cfg, click["user_id"], click["user_name"], deadline)
    if user["note"]:
        warnings.append("user not looked up: " + user["note"])
    result.update({"user_name": user["name"], "user_email": user["email"]})
    run = Run(cfg, click, job or {"master": "", "recipe_id": "", "job_id": "", "recipe_name": "", "environment": "",
                                   "priority": "", "signature": "", "table": ""}, user, now, result, warnings, deadline)
    run.load_row()
    if not job and run.row:                                   # the click did not say which job: the row for this message does
        fields = run.row[1]
        run.job = {"master": text_of(fields.get(BASE_COLUMNS["master_job_id"])), "recipe_id": text_of(fields.get(BASE_COLUMNS["recipe_id"])),
                   "job_id": text_of(fields.get(BASE_COLUMNS["job_id"])), "recipe_name": text_of(fields.get(BASE_COLUMNS["recipe_name"])),
                   "environment": "", "priority": "", "signature": "", "table": ""}
    result.update({"master_job_id": run.job["master"], "recipe_id": run.job["recipe_id"]})
    if not run.job["master"] and name != "feedback":
        refuse(run, "no job", "I could not tell which job this message is about, so nothing was done.")
    else:
        HANDLERS[name](run)
    result["ok"] = not result["error"]
    if result["refused"]:
        result["ok"] = True                                   # a refusal is an answer, not a failure


def detect_mode(inp, cfg):
    forced = text_of(inp.get("mode")).strip().lower()
    if forced in ("post", "click"):
        return forced
    if text_of(inp.get("payload")).strip() or text_of(inp.get("action_id")).strip():
        return "click"
    if cfg["slack_channel_id"] or text_of(inp.get("alert_json")).strip():
        return "post"
    return ""


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    started = time.time()
    result = {k: (list(v) if isinstance(v, list) else v) for k, v in OUTPUT_DEFAULTS}
    warnings = result["warnings"]
    inp = input if isinstance(input, dict) else {}
    try:
        cfg = settings(inp)
        now = datetime.now(timezone.utc)
        if text_of(inp.get("now")).strip():
            now = parse_when(inp.get("now")) or now
        now = now.astimezone(get_tz(cfg["timezone"]))
        deadline = started + cfg["time_budget"]
        result["mode"] = detect_mode(inp, cfg)
        if result["mode"] == "click":
            click_flow(inp, cfg, result, warnings, now, deadline)
        elif result["mode"] == "post":
            if not cfg["slack_channel_id"]:
                result["error"] = "slack_channel_id is required to post"
            else:
                post_alert(inp, cfg, result, warnings, deadline, now)
            result["ok"] = not result["error"]
        else:
            result["error"] = "nothing to do: pass slack_channel_id (to post the alert) or payload / action_id (for a click)"
    except Exception as exc:  # noqa: BLE001 - the recipe must still finish
        result["error"] = "{}: {}".format(type(exc).__name__, clip(str(exc), 300))
        result["ok"] = False
    return finish(result, started)


def finish(result, started):
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the Slack step on a JSON file of inputs.")
    parser.add_argument("input_json")
    parser.add_argument("--slack-out", help="post mode: write {blocks} here for Slack's Block Kit Builder; nothing is posted")
    args = parser.parse_args()
    with open(args.input_json, encoding="utf-8") as handle:
        data = json.load(handle)
    if args.slack_out:
        def preview(method, url, headers, payload=None, timeout=12):
            if url.startswith(SLACK_API):
                return {"ok": True, "ts": "1700000000.000100", "channel": "CPREVIEW",
                        "permalink": "https://example.slack.com/archives/CPREVIEW/p1700000000000100"}, None
            return None, "preview: no network"
        http_json = preview
        data.setdefault("slack_channel_id", "CPREVIEW")
        data["slack_bot_token"], data["workato_api_token"] = "preview", ""
    else:
        data.setdefault("slack_bot_token", os.environ.get("SLACK_BOT_TOKEN", ""))
        data.setdefault("workato_api_token", os.environ.get("WORKATO_API_TOKEN", ""))
    out = main(data)
    if args.slack_out:
        with open(args.slack_out, "w", encoding="utf-8") as handle:
            # Block Kit Builder takes blocks only (it does not show an attachment): the message's blocks, without the red bar
            sent = LAST_SENT.get("blocks") or (LAST_SENT.get("attachments") or [{}])[0].get("blocks") or []
            json.dump({"blocks": sent}, handle, indent=2, ensure_ascii=False)
    json.dump({k: v for k, v in out.items() if k != "blocks_json"}, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
