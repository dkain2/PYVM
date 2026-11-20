"""
error_notification.py -- the Workato Python step that builds the recipe error alert email.

Every recipe that fails calls the error recipe with the parameters in email_input_schema.json.
This step takes those same parameters, plus two keys:

    workato_api_token   reads the error log data table ("Error Notification - TBL") and the
                        failing job and recipe through the Workato API
    azure_api_key       writes the plain-language and technical explanation (Azure OpenAI)

and returns `html` (the email body) and `subject`. Everything else is optional and has a
default. Any setting can also be given in `config_json`; a filled-in input wins over it.

WHAT THE EMAIL SHOWS. Each part is a section; `sections` sets the order, `hide_sections`
drops some.
    hero      severity, recipe, a one-line headline, pills for category, recurrence, impact
    error     the error message, right under the greeting; "Label : value" lines become a fact grid
    records   the failed records table (dataArray), right under the error, with error-code counts
    flow      source -> Workato step -> target, with the hop that failed marked (from ErroredApp; a REST / HTTP
              step, or no ErroredApp, is read from the error text: a call to a third-party system is never Workato's)
    kpis      up to four thin tiles right under it: records processed, failed, then how the recipe is doing:
              retries, runs with errors (from the error log: the error handler makes Workato call a handled
              error a success), retry success; if there is room: times seen before, success rate, and failed at
              (only when `flow` is not shown)
    story     "In plain words" (for the business) and "Under the hood" (for engineers),
              likely causes and next steps. From Azure OpenAI, or the built-in playbook.
    signals   things worth knowing: repeated IDs in the failed rows, recurrence, the same
              error in other recipes, recipe edited recently, recent runs with errors, past fixes
    history   this recipe's failures in the error log table: same type vs other errors,
              trend, a 30-day bar chart, recent similar failures, the most common errors
    job       the Workato job and recipe from the API: failing line, error type, duration,
              recipe state and version, the last N jobs as coloured squares
    details   the technical key/value table (the old "Technical Details")
    actions   buttons: View job, Open recipe, Error file, Runbook, Error log

    look = old  renders the current email (current_email.html + moustache_template.md).
    max_width blank = the card is 800 px, and wider (920, 1,040) when the failed-records table has four or five columns, whose
    cells keep a minimum width; a number fixes it. The card is fluid, so a phone shows it at full width.
    error_banner = yes (the default) puts a red strip, a cross and "Error alert", at the very top of the email.
    hero_layout = classic  keeps the previous header (priority as plain text, pills under the headline, one logo).
    The new header: logos, then one row of pills (priority, retry verdict, category, repeats, records, time), then the title.

FREQUENCY AND ERROR LIMIT. A caller that sets `frequency` (in days) and/or `error_limit` is saying "don't email me
for every error": the step only LOGS it (Status Created, the two numbers stored in the row) and sends nothing, whatever
the other switches say. It does not count errors or watch the calendar; the daily 'Email Notification Summary- SCH'
recipe does, and emails one summary when more than `error_limit` errors have piled up (default 20) or the oldest is
older than `frequency` days (default 7). Because these are the recipes that fail most, such a call also skips the
lookups and the html only the email needs: html is then empty and look_used is 'log_only' (always_render=yes
builds them anyway). The reprocess decision and the master job id are still worked out for the logged row.

AZURE DECIDES WHAT IS RETRIED. For every error Azure says whether a re-run would help (a timeout, a rate limit, a network
error, a 5xx, a record lock: yes; data, mapping, access or configuration problems, a stop on purpose, an ambiguous
match: no). Only Azure decides: the caller's `reprocess` input is ignored (callers do not have to pass anything), and if
Azure gives no answer (no key, AI off, the call failed) the job is NOT retried and the error is emailed. When Azure says
yes the step repeats the master job through the Workato API (auto_reprocess, YES by default; set it to no to stop all
retries and the decision with them). The loop guards: a job is repeated at most max_auto_repeats times (default 1), never
when the run is itself a retry, and only when Azure is at least reprocess_min_confidence sure (default medium). A retried
error is only logged (Status Reprocessed); an error that is NOT retried is emailed: Azure said no, a guard stopped it, the
repeat call failed, or the retry itself failed again.

THE STEP WRITES THE ERROR LOG ROW. As soon as the row is known (after the reprocess decision and the master job id, before
the email is built) the step upserts it into "Error Notification - TBL", keyed on Master Job ID like the old recipe's two
upserts: a job that is run again and fails again updates its row, a new master job adds one. It is done for every call,
also for a deferred one (frequency / error_limit), whose html is empty. The recipe needs no data table step. It needs the
workato_api_token and a token that may write data table records. `row_logged`, `row_action` (inserted, updated or
failed) and `row_error` say what happened; a failed write never stops the email. log_row = no turns it off (the row is
still returned in `table_row`). Nothing is written without a token, or when history_rows_json is set (a test run).

NOTHING HERE MAY FAIL THE ERROR RECIPE. Every lookup is optional, has a timeout and shares
one time budget, and a failure only adds a line to `warnings`. That includes Azure: if the call fails for any reason the
email is still built and sent from the built-in playbook, `ai_error` says why and the story section says the AI analysis
was unavailable (the reprocess decision falls back to the rules). If building the new email
throws, the old look is returned and `error` says why.

Run it locally (no Workato needed):
    python3 error_notification.py testdata/sample_input.json --out /tmp/alert.html
    python3 error_notification.py testdata/sample_input.json \
        --history-csv ../data_table_error_notification_tbl.csv --out /tmp/alert.html
"""

import concurrent.futures
import difflib
import hashlib
import html as htmllib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone, tzinfo
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

VERSION = "2.0.0"

AZURE_URL = ("https://cour-servicenow-1.openai.azure.com/openai/deployments/"
             "gpt-4o/chat/completions?api-version=2024-10-21")
WORKATO_API = "https://www.workato.com/api"
DATA_TABLES_API = "https://data-tables.workato.com/api/v1/tables"
ERROR_TABLE_ID = "c1444a9a-03a7-4c82-8618-7796b7384b37"      # Error Notification - TBL
TEAM_CHARTER_URL = "https://coursera.atlassian.net/wiki/spaces/MUL/pages/2573336865/Team+Charter"

DEFAULT_SECTIONS = ("hero", "error", "records", "flow", "kpis", "story", "signals",
                    "history", "job", "details", "actions")
# How much each email shows (input `detail`). `sections` replaces the list, `show_sections` adds to it, `hide_sections`
# takes away from it. The recipe can pick a level per call, for example full for Critical and brief for Medium.
DETAIL_PRESETS = {
    "brief": ("hero", "error", "records", "actions"),
    "standard": ("hero", "error", "records", "story", "signals", "history", "actions"),
    "full": DEFAULT_SECTIONS,
}
# Every section name, what it shows, and the parts of it that can be hidden on their own (hide_sections takes
# "section.part"). The hints of the sections / show_sections / hide_sections inputs are written from these.
SECTION_HELP = (
    ("hero", "header: priority, recipe name, one-line headline, pills, greeting"),
    ("error", "the error message (facts such as Total Records are laid out as a small table)"),
    ("records", "the failed records table, with error-code counts"),
    ("flow", "Source > Workato step > Target, with the failing hop marked"),
    ("kpis", "thin number tiles under it: records processed, failed, success rate, retries, runs with errors, retry success"),
    ("story", "what happened: in plain words, under the hood, likely cause, next steps"),
    ("signals", "things worth knowing: reprocessable?, retry result, recipe changed recently, same error elsewhere"),
    ("history", "failure history of this recipe: trend, 30-day chart, recent similar failures, most common errors"),
    ("job", "Workato job and recipe: status, duration, slowest step, recipe state, last jobs"),
    ("details", "technical details: failure, Workato ids (links), systems, handling"),
    ("actions", "buttons: view job, open recipe, error file, runbook, error log"),
)
SUBSECTIONS = ("story.causes", "story.steps", "history.chart", "history.recent", "history.common", "job.recent",
               "details.failure", "details.workato", "details.systems", "details.handling")
SECTION_ALIASES = {"header": "hero", "tiles": "kpis", "pipeline": "flow", "summary": "story",
                   "explanation": "story", "insights": "signals", "message": "error",
                   "table": "records", "rows": "records", "trend": "history",
                   "workato": "job", "technical": "details", "tech": "details",
                   "buttons": "actions", "links": "actions"}

# The parameters the error recipe already passes (email_input_schema.json).
BASE_INPUTS = (
    "to_email_address", "subject", "mail_msg", "job_url", "recipe_name", "error_details",
    "priority", "sourceSystem", "targetSystem", "sourceObject", "targetObject", "ErroredApp",
    "ErroredAction", "stepNumber", "retry_count", "file_name", "file_content",
    "column1Name", "column1Width", "column2Name", "column2Width", "column3Name",
    "column3Width", "column4Name", "column4Width", "column5Name", "column5Width",
    "frequency", "error_limit", "dataArray", "sch_run", "reprocess",      # `reprocess` is kept for the callers that pass it, and ignored
    "calling_master_job_id", "is_Repeated",
)

# Every setting: (name, kind, default[, min, max]). Kinds: str, secret, bool, int, float,
# color. Each one is an input of the step AND a key of config_json, except those in
# CONFIG_ONLY. A blank input falls back to config_json, then to the default.
SETTINGS = (
    ("workato_api_token", "secret", ""),
    ("azure_api_key", "secret", ""),
    ("look", "str", "new"),
    ("hero_layout", "str", "new"),
    ("error_banner", "bool", True),
    ("hover_effects", "bool", True),
    ("hover_row_color", "color", "#EEF4FF"),
    ("detail", "str", "standard"),
    ("env", "str", ""),
    ("sections", "str", ""),
    ("show_sections", "str", ""),
    ("hide_sections", "str", ""),
    ("subject_format", "str", "{emoji} {env} | {subject}"),
    ("show_intro", "bool", False),
    ("greeting", "str", "Hi Team,"),
    ("timezone", "str", "America/Los_Angeles"),
    ("brand_color", "color", "#0056D2"),
    ("max_width", "int", 0, 0, 1200),            # 0 = auto, see card_width
    ("logo_url", "str", ""),
    ("team_logo_url", "str", ""),
    ("team_name", "str", ""),
    ("alert_email", "str", ""),
    ("servicenow_url", "str", ""),
    ("slack_url", "str", ""),
    ("charter_url", "str", TEAM_CHARTER_URL),
    ("runbook_url", "str", ""),
    ("error_file_url", "str", ""),
    ("error_time", "str", ""),
    ("recipe_id", "str", ""),
    ("history", "bool", True),
    ("history_days", "int", 90, 1, 400),
    ("chart_days", "int", 30, 7, 60),
    ("similar_limit", "int", 5, 0, 20),
    ("cross_recipe_days", "int", 7, 0, 60),
    ("similarity", "float", 0.6, 0.3, 1.0),
    ("data_table_id", "str", ERROR_TABLE_ID),
    ("history_rows_json", "str", ""),
    ("mask_history_pii", "bool", True),
    ("job_context", "bool", True),
    ("recent_jobs", "int", 20, 0, 100),
    ("workato_api_base", "str", WORKATO_API),
    ("show_editor", "bool", False),
    ("show_developer", "bool", False),
    ("ai", "bool", True),
    ("azure_url", "str", AZURE_URL),
    ("ai_temperature", "float", 0.2, 0.0, 1.0),
    ("ai_max_tokens", "int", 900, 200, 2000),
    ("ai_redact", "bool", True),
    ("ai_instructions", "str", ""),
    ("auto_escalate", "bool", False),
    ("escalate_after", "int", 5, 2, 100),
    ("log_row", "bool", True),
    ("reprocess_policy", "str", "ai"),
    ("reprocess_min_confidence", "str", "medium"),
    ("auto_reprocess", "bool", True),
    ("max_auto_repeats", "int", 1, 0, 10),
    ("email_when_reprocessable", "bool", False),
    ("notify_on_repeat_failure", "bool", True),
    ("max_table_rows", "int", 25, 1, 500),
    ("max_error_chars", "int", 3000, 200, 20000),
    ("max_signals", "int", 6, 0, 12),
    ("time_budget", "int", 45, 5, 85),
    ("http_timeout", "int", 12, 3, 60),
    ("html_limit_kb", "int", 100, 20, 2000),
    ("always_render", "bool", False),
    ("config_json", "str", ""),
    ("now", "str", ""),
    ("data_tables_base", "str", DATA_TABLES_API),
)
CONFIG_ONLY = {"data_tables_base"}
# What the old recipe read from its trigger's context and from its file steps. The new
# recipe maps them in: the callable trigger's calling recipe / job, and the outputs of
# "Create file" and "Generate shareable file link" (Python can't use Workato file storage).
EXTRA_INPUTS = ("calling_recipe_id", "calling_job_id", "error_file_path", "error_file_expires_in")
INPUT_NAMES = tuple(BASE_INPUTS) + EXTRA_INPUTS + tuple(s[0] for s in SETTINGS if s[0] not in CONFIG_ONLY)

# Errors that usually clear up when the same job simply runs again.
TRANSIENT = {"timeout", "rate_limit", "network", "server_error", "record_lock"}
# How the reprocess decision is named in the email.
# The developer of a recipe: Workato has no owner field, so it is the author of the recipe's first version written by an
# address at this domain (versions by contractors or service accounts are skipped). The same rule as the genie console's
# responder; at most this many versions are walked.
DEVELOPER_EMAIL_DOMAIN = "coursera.org"
DEVELOPER_MAX_VERSIONS = 30
DECISION_SOURCES = {"ai": "AI", "ai+rules": "AI + rules", "rules": "rules", "input": "caller"}
CONFIDENCE = {"": 0, "low": 1, "medium": 2, "high": 3}

# The error log row, in the data table's own column names (the old recipe's two upserts).
TABLE_ROW_KEYS = (
    ("job_url", "Job URL"), ("date", "Date"), ("error_message", "Error Message"),
    ("frequency", "Frequency"), ("recipe_name", "Recipe Name"), ("error_limit", "Error Limit"),
    ("error_timestamp", "Error TimeStamp"), ("email", "Email"), ("source_system", "Source System"),
    ("target_system", "Target System"), ("source_object", "Source Object"),
    ("target_object", "Target Object"), ("status", "Status"), ("recipe_id", "Recipie Id"),
    ("job_id", "Job Id"), ("master_job_id", "Master Job ID"), ("reprocess_count", "Reprocess Count"),
    ("reprocess_flag", "Reprocess_Flag"), ("error_file_path", "Error File Path"),
    ("error_file_sharable_url", "Error File Sharable URL"),
    ("sharable_link_expires_on", "Sharable Link Expires on"),
)

OUTPUT_DEFAULTS = (
    ("ok", False), ("error", ""), ("warnings", []),
    ("action", "notify"), ("send_email", True), ("to_email", ""),
    ("html", ""), ("subject", ""), ("preheader", ""), ("text_body", ""),
    ("reprocessable", False), ("reprocess_source", ""), ("reprocess_reason", ""),
    ("reprocess_confidence", ""), ("reprocess_attempted", False), ("reprocess_enqueued", False),
    ("reprocess_job_id", ""), ("reprocess_error", ""), ("master_job_id", ""),
    ("table_row", {}), ("table_row_json", ""),
    ("row_logged", False), ("row_action", ""), ("row_record_id", ""), ("row_error", ""),
    ("look_used", ""), ("sections_rendered", []),
    ("priority", ""), ("priority_escalated", False), ("severity_color", ""), ("env", ""),
    ("error_category", ""), ("error_category_label", ""), ("error_signature", ""),
    ("headline", ""), ("is_batch", False), ("records_total", 0), ("records_failed", 0),
    ("success_rate", ""),
    ("explanation_source", ""), ("ai_error", ""), ("functional_summary", ""), ("technical_summary", ""),
    ("likely_causes", []), ("next_steps", []),
    ("history_used", False), ("history_total", 0), ("history_same_type", 0),
    ("history_7d", 0), ("history_trend", ""), ("first_seen", ""), ("last_seen", ""),
    ("is_recurring", False), ("other_recipes_affected", 0),
    ("job_context_used", False), ("recipe_running", ""), ("developer_name", ""), ("developer_email", ""),
    ("recent_jobs_checked", 0),
    ("recent_jobs_failed", 0),
    ("signals", []), ("html_bytes", 0), ("elapsed_ms", 0),
    ("alert_json", ""),
)

# ------------------------------------------------------------------------------ look

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"
INK, TEXT, MUTED, FAINT = "#0F172A", "#334155", "#64748B", "#94A3B8"
LINE, SOFT, PANEL = "#E2E8F0", "#F8FAFC", "#F1F5F9"
GOOD, GOOD_SOFT, BAD, BAD_SOFT = "#15803D", "#F0FDF4", "#B91C1C", "#FEF2F2"
WARN, WARN_SOFT, INFO, INFO_SOFT = "#B45309", "#FFFBEB", "#1D4ED8", "#EFF6FF"

SEVERITY = {
    "CRITICAL": {"label": "Critical", "emoji": "🚨", "color": "#DC2626", "soft": "#FEF2F2",
                 "ink": "#991B1B", "line": "#FECACA"},
    "HIGH": {"label": "High", "emoji": "❗", "color": "#EA580C", "soft": "#FFF7ED",
             "ink": "#9A3412", "line": "#FED7AA"},
    "MEDIUM": {"label": "Medium", "emoji": "⚠️", "color": "#D97706", "soft": "#FFFBEB",
               "ink": "#92400E", "line": "#FDE68A"},
    "LOW": {"label": "Low", "emoji": "ℹ️", "color": "#2563EB", "soft": "#EFF6FF",
            "ink": "#1E40AF", "line": "#BFDBFE"},
}
PRIORITY_ALIASES = {"P1": "CRITICAL", "SEV1": "CRITICAL", "URGENT": "CRITICAL", "BLOCKER": "CRITICAL",
                    "P2": "HIGH", "SEV2": "HIGH", "MAJOR": "HIGH", "P3": "MEDIUM", "SEV3": "MEDIUM",
                    "NORMAL": "MEDIUM", "MODERATE": "MEDIUM", "P4": "LOW", "SEV4": "LOW",
                    "MINOR": "LOW", "INFO": "LOW"}
PRIORITY_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# The frame colours are the current email's env_color values, so both looks match.
ENVIRONMENTS = {
    "PROD": {"label": "Production", "frame": "#EEF1F4", "chip": "#0F172A", "chip_text": "#FFFFFF"},
    "DEV": {"label": "Development", "frame": "#D1FAE5", "chip": "#047857", "chip_text": "#FFFFFF"},
    "_": {"label": "", "frame": "#FFF8E1", "chip": "#B45309", "chip_text": "#FFFFFF"},
}
ENV_ALIASES = {"PRODUCTION": "PROD", "PRD": "PROD", "DEVELOPMENT": "DEV"}

TITLES = {
    "kpis": "", "flow": "Where it broke", "story": "What happened", "signals": "Signals worth knowing",
    "error": "Error message", "records": "Failed records", "history": "Failure history",
    "job": "Workato job & recipe", "details": "Technical details", "actions": "",
    "functional": "In plain words", "technical": "Under the hood", "causes": "Likely cause",
    "steps": "Next steps",
}
ICONS = {"flow": "🧭", "story": "🧠", "signals": "💡", "error": "🧯", "records": "🧾",
         "history": "📈", "job": "⚙️", "details": "🔧", "functional": "👥", "technical": "🛠️",
         "causes": "🎯", "steps": "✅"}

APP_NAMES = {"salesforce": "Salesforce", "netsuite": "NetSuite", "misc": "Workato",
             "misc_dsl": "Workato", "workato_recipe_function": "Workato",
             "workato_variable": "Workato", "workato_webhooks": "Workato webhooks",
             "workato_data_table": "Data tables", "workato_template": "Templates",
             "python": "Python", "ruby": "Ruby", "rest": "HTTP", "http": "HTTP",
             "slack": "Slack", "slack_bot": "Slack", "airtable": "Airtable",
             "service_now": "ServiceNow", "servicenow": "ServiceNow",
             "google_sheets": "Google Sheets", "aws_s3": "Amazon S3", "s3": "Amazon S3",
             "databricks": "Databricks", "snowflake": "Snowflake", "open_ai": "OpenAI",
             "openai": "OpenAI", "jira": "Jira", "email": "Email", "logger": "Logger",
             "lookup_table": "Lookup tables", "variables": "Variables", "list": "Lists"}
# Errors raised by these apps happen inside Workato itself, not at the source or target.
INTERNAL_APPS = {"misc", "miscdsl", "workatorecipefunction", "workatovariable", "python",
                 "ruby", "logger", "variables", "list", "lookuptable", "workatotemplate",
                 "workatodatatable", "workato", "utility", "jsonparser", "csvparser",
                 "workatofiles"}
SYSTEM_SYNONYMS = (("saleforce", "salesforce"), ("sfdc", "salesforce"), ("ns", "netsuite"),
                   ("snow", "servicenow"), ("amazons3", "s3"), ("awss3", "s3"))
# Connectors that only call some third-party system over HTTP. An error from one of them is that system's answer, so it is
# never Workato's own (see failing_node).
GENERIC_CALL_APPS = {"rest", "http", "httpclient", "restapi", "restclient", "soap", "graphql", "openapi"}
# Kinds of error that only another system can give, whichever connector made the call.
REMOTE_CATEGORIES = {"duplicate", "converted_lead", "record_lock", "rate_limit", "auth", "permission", "field_access",
                     "invalid_reference", "server_error", "bad_request", "network"}
# Kinds that come from Workato's own logic or formulas.
INTERNAL_CATEGORIES = {"formula", "missing_input", "stopped_recipe", "stop_job"}
# Words in a system name that say nothing about which system it is.
GENERIC_NAME_WORDS = {"service", "services", "system", "systems", "api", "app", "application", "prod", "production",
                      "sandbox", "sb", "uat", "dev", "test", "the"}

# ------------------------------------------------------------------- classification

# (key, label, icon, patterns). The first category with a matching pattern wins, so the
# specific ones come first. config_json "category_rules" adds rules in front of these.
CATEGORIES = (
    ("duplicate", "Duplicate record", "👯",
     (r"DUPLICATE_VALUE", r"duplicate (external )?id", r"duplicate value", r"DUPLICATES_DETECTED",
      r"duplicate key", r"already exists", r"duplicate record")),
    ("converted_lead", "Converted lead", "🔒", (r"CANNOT_UPDATE_CONVERTED_LEAD", r"converted lead")),
    ("record_lock", "Record locked", "⏳", (r"UNABLE_TO_LOCK_ROW", r"record currently unavailable")),
    ("stopped_recipe", "Called recipe is stopped", "⏹️",
     (r"call a stopped recipe", r"recipe is stopped", r"recipe is not running")),
    ("rate_limit", "Rate / concurrency limit", "🚦",
     (r"too many requests", r"rate.?limit", r"limit exceeded", r"REQUEST_LIMIT_EXCEEDED",
      r"concurren(t|cy) (request )?limit", r"throttl", r"quota exceeded", r"status\W{0,3}429")),
    ("auth", "Authentication / connection", "🔑",
     (r"unauthori[sz]ed", r"invalid_grant", r"access_denied", r"INVALID_SESSION_ID",
      r"connection is broken", r"please (re)?connect", r"token (has )?expired", r"expired token",
      r"authentication (failed|failure|error)", r"invalid (api )?key", r"invalid_client",
      r"invalid credentials", r"status\W{0,3}401")),
    ("permission", "Permission denied", "🚫",
     (r"forbidden", r"INSUFFICIENT_ACCESS", r"insufficient (access|privileges)",
      r"not authori[sz]ed to", r"permission denied", r"status\W{0,3}403")),
    ("timeout", "Timeout", "⏱️",
     (r"time(d)?[ -]?out", r"no activity within", r"exceeded \d+ seconds", r"execution expired",
      r"deadline exceeded")),
    ("field_access", "Field access / mapping", "🧩",
     (r"unable to create/update fields", r"INVALID_FIELD_FOR_INSERT_UPDATE", r"INVALID_FIELD\b",
      r"no such column", r"not (writeable|editable|insertable|updateable)")),
    ("invalid_reference", "Invalid reference value", "🔗",
     (r"INVALID_CROSS_REFERENCE_KEY", r"invalid cross reference", r"INVALID_ID_FIELD",
      r"invalid value for the resource or sub-resource field", r"ENTITY_IS_DELETED", r"MALFORMED_ID",
      r"invalid reference")),
    ("validation", "Data validation", "📋",
     (r"FIELD_CUSTOM_VALIDATION_EXCEPTION", r"REQUIRED_FIELD_MISSING", r"STRING_TOO_LONG",
      r"INVALID_EMAIL_ADDRESS", r"restricted picklist", r"incorrect format", r"invalid format",
      r"not valid json", r"FIELD_INTEGRITY_EXCEPTION", r"INVALID_TYPE_ON_FIELD",
      r"NUMBER_OUTSIDE_VALID_RANGE", r"invalid (date|number|email)", r"data value too large")),
    ("missing_input", "Missing required input", "❔",
     (r"must be present", r"is required", r"missing required", r"can'?t be blank",
      r"cannot be blank")),
    ("formula", "Formula / data shape", "🧮",
     (r"error calculating input", r"no method", r"undefined method", r"for nil\b", r"nil:NilClass",
      r"missing field value", r"NoMethodError", r"TypeError", r"KeyError")),
    ("not_found", "Not found", "🔍",
     (r"not found", r"\bno \w[\w ]{0,60}? found", r"does not exist", r"NOT_FOUND", r"failed to retrieve",
      r"status\W{0,3}404")),
    ("network", "Network / connectivity", "📡",
     (r"connectionerror", r"connection (refused|reset)", r"failed to open tcp", r"getaddrinfo",
      r"\bssl\b", r"econnreset", r"httpsconnectionpool", r"could not connect",
      r"name or service not known")),
    ("server_error", "Upstream service error", "🔥",
     (r"internal (server )?error", r"service unavailable", r"bad gateway", r"thrift server",
      r"unexpected error", r"server error", r"status\W{0,3}5\d\d")),
    ("bad_request", "Request rejected", "⛔",
     (r"bad request", r"invalid request", r"malformed", r"unprocessable", r"status\W{0,3}4\d\d")),
    ("partial_batch", "Partial batch failure", "📦",
     (r"records? failed", r"failed to synchroni[sz]e", r"total records", r"however,? it failed",
      r"partially (failed|processed)")),
)
# Messages seen in the error log that the rules above leave unclassified. They go in FRONT of CATEGORIES; a rule with no label
# takes the label and icon of the category of the same key. error_dashboard.py has the same list (test_error_dashboard checks
# they stay equal), so an error has the same category in the alert and on the dashboard.
EXTRA_RULES = (
    ("multi_match", "Ambiguous match", "🎯",
     (r"more than \d+ records? matched", r"matched more than one record", r"multiple records? (matched|found)")),
    ("rate_limit", "", "", (r"exceeded your limit of", r"requests per (second|minute|three seconds)")),
    ("missing_input", "", "", (r"please enter value\(?s?\)? for",)),
    ("invalid_reference", "", "", (r"invalid [\w ]{0,30}reference key", r"is not a valid salesforce id")),
    ("partial_batch", "", "", (r"error occ?u?r+ed while processing [\w ]{1,60} records",)),
    ("validation", "", "", (r"input data too big", r"not a valid email", r"more than the maximum number",
                            r"data validation error", r"maximum (length|number of characters)")),
    ("bad_request", "", "", (r"request header fields too large", r"bad uri")),
)
UNKNOWN = ("unknown", "Unclassified error", "❓")
STOP_JOB = ("stop_job", "Stopped by recipe logic", "🛑")
# Categories where the same error in other recipes points at one shared cause.
SYSTEMIC = {"auth", "permission", "rate_limit", "timeout", "network", "server_error",
            "stopped_recipe", "record_lock"}

# What each category means, in plain words and for an engineer, with likely causes and
# steps. {target} {source} {object} {app} {step} are filled in. config_json "playbook"
# overrides any field of any category, and "runbooks" maps a category to a link.
PLAYBOOK = {
    "duplicate": {
        "functional": "{target} refused them because another record already uses the same unique key, or the same record appears more than once in the load.",
        "technical": "{target} rejected the write with a duplicate-key error (such as `DUPLICATE_VALUE`) on an external ID or unique field. In a bulk upsert, two rows with the same external ID in one batch cause this too.",
        "causes": ["The same key appears more than once in the source file or batch",
                   "A record with this key already exists, created by another process",
                   "The key is formatted differently (case, padding, suffix), so the upsert found no match and tried to insert"],
        "steps": ["Check the source for repeated keys and de-duplicate before the upsert",
                  "Search {target} for the key to see which record already holds it",
                  "Merge or skip true duplicates, then reprocess only the failed rows"]},
    "converted_lead": {
        "functional": "Those leads were already converted into contacts or accounts, and converted leads can't be changed.",
        "technical": "Salesforce returned `CANNOT_UPDATE_CONVERTED_LEAD`: the Lead has `IsConverted = true` and is read-only through the API.",
        "causes": ["The lead was converted after the source event was created",
                   "The lookup matches leads without filtering out converted ones"],
        "steps": ["Filter on `IsConverted = false` in the lead lookup, or update the converted Contact/Account instead",
                  "If no business data is lost, treat this error as expected and stop alerting on it"]},
    "record_lock": {
        "functional": "{target} was busy updating the same record for another process, so this update was refused. A retry usually works.",
        "technical": "Row lock contention (`UNABLE_TO_LOCK_ROW`): another transaction holds a lock on the record or its parent.",
        "causes": ["Several jobs updating the same parent record at once",
                   "A bulk load running at the same time as the recipe"],
        "steps": ["Retry with back-off", "Lower the recipe's concurrency or group updates by parent record",
                  "Look for other integrations or bulk jobs running at the same time"]},
    "stopped_recipe": {
        "functional": "This recipe hands work to another recipe that is switched off, so that part of the work didn't happen.",
        "technical": "A callable recipe or function was called while stopped (\"Can't call a stopped recipe\").",
        "causes": ["The called recipe was stopped for maintenance or after an error",
                   "A deployment stopped it and it wasn't started again"],
        "steps": ["Find out why the called recipe stopped, then start it",
                  "Rerun the failed jobs once it is running"]},
    "rate_limit": {
        "functional": "{app} asked Workato to slow down because too many requests arrived at once. The data is delayed, not lost, if the job is retried.",
        "technical": "A rate or concurrency limit was hit (HTTP 429, \"limit exceeded\", or a concurrent request limit), so the platform throttled the call.",
        "causes": ["Many jobs ran at the same time", "The daily API allowance is nearly used up",
                   "Another integration uses the same quota"],
        "steps": ["Retry with exponential back-off", "Lower recipe concurrency or send more records per call",
                  "Check API usage in {app}"]},
    "auth": {
        "functional": "Workato couldn't sign in to {app}, so nothing moved in this step. Anything else that uses this connection is probably affected until it's fixed.",
        "technical": "Authentication failed (401, invalid session, or a broken connection): the connection's token or credentials are expired, revoked or wrong.",
        "causes": ["The OAuth token expired or was revoked", "The password, API key or integration user changed",
                   "The integration user was frozen or lost its licence"],
        "steps": ["Reconnect the {app} connection in Workato", "Check that the integration user is active and its credentials are current",
                  "Rerun the failed jobs after reconnecting"]},
    "permission": {
        "functional": "Workato reached {app}, but the integration account isn't allowed to do this, so the change wasn't made.",
        "technical": "Access was denied (403 or insufficient access): the connection's user lacks permission on the object, field or record.",
        "causes": ["The integration user is missing an object or field permission",
                   "Sharing rules hide the target record", "A permission set was removed in a recent change"],
        "steps": ["Check the integration user's profile and permission sets", "Confirm it can see the specific record",
                  "Rerun the job once access is granted"]},
    "timeout": {
        "functional": "A step took too long and was stopped, so this run didn't finish. It may work if retried when systems are less busy.",
        "technical": "The step went over its time limit (connector timeout, code step timeout, or no activity within the window).",
        "causes": ["Too much data handled in one call", "The external system answered slowly",
                   "A slow loop or query in the recipe"],
        "steps": ["Find the slowest step in the job and check how much data it handled",
                  "Split the work into smaller batches or pages", "Retry; if it repeats, optimise the query or raise the timeout"]},
    "field_access": {
        "functional": "{target} wouldn't accept values for some fields, so those records weren't fully updated.",
        "technical": "The integration user can't write the listed fields: field-level security, a read-only or formula field, or a field missing from the object.",
        "causes": ["Field-level security doesn't give the integration profile edit access",
                   "A field was renamed, deleted or made read-only", "The mapping writes to a field on the wrong object"],
        "steps": ["Check field-level security for the fields named in the error",
                  "Confirm the fields exist and can be edited", "Fix or remove the mapping, then reprocess"]},
    "invalid_reference": {
        "functional": "Some records point to something that doesn't exist or isn't allowed in {target}, such as an owner, account or picklist value, so they weren't saved.",
        "technical": "A lookup or reference field holds an ID or value {target} doesn't accept (`INVALID_CROSS_REFERENCE_KEY`, or an invalid sub-resource value).",
        "causes": ["The referenced record was deleted or never synced",
                   "An ID from another environment (sandbox vs production)", "The value isn't a valid option for that field"],
        "steps": ["Look up the value named in the error in {target}",
                  "Sync the referenced record first, or map a valid default", "Reprocess the failed records"]},
    "validation": {
        "functional": "Some data didn't meet {target}'s rules (format, required value or allowed list), so it was rejected.",
        "technical": "A validation rule, data type or format check failed when writing to {target}.",
        "causes": ["Source data is empty or in an unexpected format", "A validation rule was added or changed in {target}",
                   "A picklist or allowed value changed"],
        "steps": ["Compare the failing value with the field's rules in {target}",
                  "Add a clean-up or formatting step to the recipe", "Reprocess once the data or the rule is fixed"]},
    "missing_input": {
        "functional": "The recipe was missing a value it needs, so this run stopped.",
        "technical": "A required input was blank at run time (\"must be present\" or \"is required\").",
        "causes": ["An earlier step returned an empty value", "A datapill mapped here is optional and wasn't filled"],
        "steps": ["Open the job and check the input of step {step}", "Add a default value or a condition that skips blanks"]},
    "formula": {
        "functional": "The recipe met data it didn't expect, such as an empty or differently shaped value, so a calculation failed and the run stopped.",
        "technical": "A formula failed at run time: a nil value, a missing field or the wrong type (for example \"no method ... for nil\").",
        "causes": ["An optional field was empty for this record", "The upstream response changed shape",
                   "Text, number and list types were mixed"],
        "steps": ["Open the job and check the inputs of step {step}", "Guard the formula with `.present?` or a default",
                  "Add a test case with empty values"]},
    "not_found": {
        "functional": "Workato looked for a record or resource that wasn't there, so this item couldn't be processed.",
        "technical": "A lookup came back empty or the API answered 404 Not Found.",
        "causes": ["The record was deleted or hasn't been created yet", "The wrong ID or key is mapped",
                   "The step points at the wrong environment or endpoint"],
        "steps": ["Search for the key in the system named in the error", "Check the ID mapping in step {step}",
                  "Decide whether missing records should be created or skipped"]},
    "network": {
        "functional": "Workato couldn't reach {app} because of a network problem. This is usually temporary.",
        "technical": "The connection failed before any answer came back (DNS, TLS, connection refused or reset).",
        "causes": ["A temporary network or DNS problem", "The service or on-prem agent is down",
                   "A certificate or firewall change"],
        "steps": ["Check the system's status page or the on-prem agent", "Retry the job",
                  "If it continues, check certificates and allow-lists"]},
    "server_error": {
        "functional": "{app} had an internal problem while handling the request. The problem is on their side and often clears up by itself.",
        "technical": "The upstream service answered with a 5xx or internal error.",
        "causes": ["An outage or slowdown at the provider", "A request that hits a bug or limit at the provider"],
        "steps": ["Check the provider's status page", "Retry the job",
                  "If the same record keeps failing, capture the request and raise it with the provider"]},
    "bad_request": {
        "functional": "{app} refused the request as invalid, so the data wasn't sent.",
        "technical": "The API answered 4xx (Bad Request): the payload or parameters don't match what it expects.",
        "causes": ["A required parameter is missing or empty", "The payload format or API version changed"],
        "steps": ["Inspect the request in step {step}", "Compare it with the API documentation", "Fix the mapping and rerun"]},
    "multi_match": {
        "functional": "{target} found more than one record that fits, so it could not tell which one to change and left the change undone.",
        "technical": "A lookup or update matched several records (\"More than 1 record matched the given criteria\"): the condition does not identify a single record.",
        "causes": ["Duplicate records in {target} share the value the recipe searches on",
                   "The search condition is too loose (a name or a partial key instead of a unique id)"],
        "steps": ["Find the records that match in {target} and merge or remove the duplicates",
                  "Make the lookup unique: search on an external id or add another condition",
                  "Reprocess once the match is unique"]},
    "partial_batch": {
        "functional": "Most records went through, but some didn't. The failed ones are listed in this email.",
        "technical": "A batch or bulk operation finished with record-level failures.",
        "causes": ["Data problems in the failed rows (see the error column of each)"],
        "steps": ["Group the failed rows by error message", "Fix the data for each group",
                  "Reprocess only the failed rows"]},
    "stop_job": {
        "functional": "The recipe stopped this run on purpose because a business check failed, usually missing or unexpected data.",
        "technical": "A Stop job step ended the job with an error.",
        "causes": ["The record didn't meet a condition the recipe requires"],
        "steps": ["Read the stop reason in the error message", "Fix the source data or adjust the condition"]},
    "unknown": {
        "functional": "Something went wrong in this run. The details in this email show where and what.",
        "technical": "The error didn't match a known pattern; check the failing step and the raw message.",
        "causes": ["See the raw error message in this email"],
        "steps": ["Open the job and check the failing step's input and output",
                  "Search earlier alerts for the same message"]},
}

AI_SYSTEM = (
    "You explain Workato integration failures for Coursera's IT Integrations team inside an "
    "alert email. Readers are the engineers who will fix it and the business owners who need "
    "to know the impact. Use ONLY the facts in the JSON you are given. Never invent record "
    "counts, names, IDs, dates, or system behaviour the facts don't support, and don't present "
    "a guess as certain: when unsure, say what to check. Plain, specific, calm language; no "
    "emoji, no hype, no apologies. Wrap field names, identifiers and error codes in backticks.\n"
    "Return a JSON object with exactly these keys:\n"
    "headline: one sentence, at most 16 words: what failed and the impact.\n"
    "functional_summary: 1-3 sentences, at most 60 words, for a non-technical reader: which "
    "data or process was affected and what it means for the business. No error codes.\n"
    "technical_summary: 1-3 sentences, at most 70 words, for an engineer: where it failed "
    "(system, step), the error code or mechanism, and the most likely reason.\n"
    "likely_causes: array of 1-3 short strings, most likely first.\n"
    "next_steps: array of 2-4 short imperative steps an engineer can take now, most useful "
    "first. Suggest reprocessing only after the fix.\n"
    "confidence: low, medium or high: how well the facts support your explanation.\n"
    "reprocessable: yes or no. Workato may re-run this whole job unchanged, with the same "
    "trigger data, if you say yes. Say yes ONLY when the cause is transient and a re-run is both "
    "likely to succeed and safe: a timeout, a rate or concurrency limit, a network error, a 5xx "
    "from the provider, a record lock, or an outage that has cleared. Say no when data, mapping, "
    "configuration, permissions or credentials must be fixed first, when the recipe stopped the "
    "job on purpose, when the same error has already come back after a reprocess, or when a "
    "re-run could create duplicates or write the same records twice. When unsure, say no.\n"
    "reprocess_reason: one sentence, at most 30 words, explaining the reprocessable answer."
)

HISTORY_COLUMNS = ("Date", "Status", "Reprocess Count", "Error TimeStamp", "Recipe Name",
                   "Error Message", "Recipie Id", "Job URL", "Job Id", "Master Job ID",
                   "Source System", "Target System")
HISTORY_FIELDS = {  # normalised column name(s) for each field a history row needs
    "date": ("date",), "ts": ("error_timestamp", "error_time", "timestamp"),
    "recipe_id": ("recipie_id", "recipe_id"), "recipe_name": ("recipe_name",),
    "message": ("error_message", "message", "error_details"), "status": ("status",),
    "job_id": ("job_id",), "master_job_id": ("master_job_id",), "job_url": ("job_url",),
    "reprocess_count": ("reprocess_count",), "target": ("target_system", "targetsystem"),
    "source": ("source_system", "sourcesystem"),
}

# ------------------------------------------------------------------- small helpers


def text_of(value):
    """Any input as text: None is '', lists and dicts are JSON."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def truthy(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if not text:
        return default
    return text in ("1", "true", "yes", "y", "on", "t")


def to_int(value, default=None):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return default if math.isnan(value) else int(value)
    text = text_of(value).strip().replace(",", "")
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def to_float(value, default=None):
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return default if isinstance(value, float) and math.isnan(value) else float(value)
    text = text_of(value).strip().replace(",", "")
    try:
        return float(text) if text else default
    except ValueError:
        return default


def first(mapping, *keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def esc(value):
    return htmllib.escape(text_of(value), quote=True)


def clip(value, limit):
    text = text_of(value)
    if limit and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def fmt_int(value):
    try:
        return "{:,}".format(int(value))
    except (TypeError, ValueError):
        return text_of(value)


def fmt_pct(rate, failed=0):
    if rate is None:
        return ""
    if failed and rate >= 99.995:                      # never round a failure up to 100%
        return "{:.2f}%".format(math.floor(rate * 100) / 100.0)
    if rate >= 99:
        return "{:.2f}%".format(rate)
    return "{:.1f}%".format(rate)


def plural(count, word, many=None):
    return "{} {}".format(fmt_int(count), word if count == 1 else (many or word + "s"))


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "{}{}".format(n, suffix)


def css_color(value):
    text = text_of(value).strip()
    if re.match(r"^#?[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$", text):
        return text if text.startswith("#") else "#" + text
    if re.match(r"^[A-Za-z]{3,20}$", text):
        return text
    return ""


def safe_url(value):
    url = text_of(value).strip()
    return url if re.match(r"(?i)^(https?://|mailto:)", url) else ""


def pretty_name(value):
    """'SFDC_Services' -> 'SFDC Services'; app ids through APP_NAMES."""
    text = text_of(value).strip()
    if not text:
        return ""
    key = text.lower()
    if key in APP_NAMES:
        return APP_NAMES[key]
    return re.sub(r"[_]+", " ", text).strip()


def app_label(value, app_names=None):
    key = text_of(value).strip().lower()
    names = dict(APP_NAMES)
    names.update(app_names or {})
    if key in names:
        return names[key]
    return " ".join(w.capitalize() for w in re.split(r"[_\s]+", key) if w)


def norm_system(value):
    text = re.sub(r"[^a-z0-9]+", "", text_of(value).lower())
    for old, new in SYSTEM_SYNONYMS:
        if text.startswith(old):
            text = new + text[len(old):]
    return text


def norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", text_of(name).lower()).strip("_")


class SafeDict(dict):
    def __missing__(self, key):
        return ""


def fill(template, values):
    try:
        return text_of(template).format_map(SafeDict(values))
    except (ValueError, IndexError, KeyError):
        return text_of(template)


# ----------------------------------------------------------------- html and text

_BREAKS = re.compile(r"(?i)<\s*(br|/p|/div|/li|/tr|/h[1-6]|/table|hr)\b[^>]*>")
_OPENERS = re.compile(r"(?i)<\s*(p|div|li|tr|h[1-6])\b[^>]*>")
_TAG = re.compile(r"<[^>]+>")


def html_to_lines(value):
    """The visible text of an HTML fragment, one entry per paragraph or line."""
    text = text_of(value)
    text = re.sub(r"(?is)<(script|style|head|title)\b[^>]*>.*?</\1\s*>", " ", text)
    text = re.sub(r"(?s)<!--.*?-->", " ", text)
    text = _BREAKS.sub("\n", text)
    text = _OPENERS.sub("\n", text)
    text = _TAG.sub("", text)
    text = htmllib.unescape(text).replace("\xa0", " ")
    lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
    return [line for line in lines if line]


def plain(value):
    return " ".join(html_to_lines(value))


class _Sanitizer(HTMLParser):
    """Keeps simple formatting from error messages and drops everything risky."""
    ALLOWED = {"p", "br", "b", "strong", "i", "em", "u", "a", "ul", "ol", "li", "span", "code",
               "pre", "div", "small", "sub", "sup", "hr", "table", "thead", "tbody", "tr", "td",
               "th", "h4", "h5", "h6"}
    VOID = {"br", "hr"}
    DROP = {"script", "style", "head", "title", "iframe", "object", "embed", "noscript",
            "template", "svg", "math", "form", "textarea", "select", "button"}
    STYLE_PROPS = {"color", "font-weight", "font-style", "text-decoration", "background-color"}

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.out, self.stack, self.dropping = [], [], 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.DROP:
            self.dropping += 1
            return
        if self.dropping or tag not in self.ALLOWED:
            return
        kept = []
        for name, value in attrs:
            name, value = (name or "").lower(), (value or "").strip()
            if tag == "a" and name == "href" and safe_url(value):
                kept.append('href="{}"'.format(esc(value)))
            elif name == "style":
                good = []
                for decl in value.split(";"):
                    prop, _, val = decl.partition(":")
                    prop, val = prop.strip().lower(), val.strip()
                    if (prop in self.STYLE_PROPS and re.match(r"^[#\w\s.,%()-]{1,40}$", val)
                            and not re.search(r"(?i)url|expression|javascript", val)):
                        good.append("{}:{}".format(prop, val))
                if good:
                    kept.append('style="{}"'.format(esc(";".join(good))))
        if tag == "a":
            kept.append('target="_blank"')
        self.out.append("<{}{}>".format(tag, "".join(" " + a for a in kept)))
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.DROP:
            self.dropping = max(0, self.dropping - 1)
            return
        if self.dropping or tag not in self.ALLOWED or tag in self.VOID or tag not in self.stack:
            return
        while self.stack:
            top = self.stack.pop()
            self.out.append("</{}>".format(top))
            if top == tag:
                break

    def handle_data(self, data):
        if not self.dropping:
            self.out.append(esc(data))

    def result(self):
        while self.stack:
            self.out.append("</{}>".format(self.stack.pop()))
        return "".join(self.out)


def sanitize_html(value):
    parser = _Sanitizer()
    try:
        parser.feed(text_of(value))
        parser.close()
        return parser.result()
    except Exception:  # noqa: BLE001 - a broken fragment still gets shown, as text
        return esc(plain(value))


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"https?://[^\s<>\"']+")


def redact(text):
    """For anything sent to Azure: no emails, URLs, Salesforce ids or long numbers."""
    text = EMAIL_RE.sub("<email>", text_of(text))
    text = URL_RE.sub(lambda m: "<url:{}>".format(urllib_parse.urlsplit(m.group()).netloc), text)
    text = re.sub(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?\b",
                  "<id>", text)
    return re.sub(r"\d{6,}", "<num>", text)


def mask_emails(text):
    return EMAIL_RE.sub(lambda m: "•••@" + m.group().split("@", 1)[1], text_of(text))


def fingerprint_text(value):
    """The error with the variable parts taken out, so the same error matches across runs."""
    t = plain(value).lower()
    t = EMAIL_RE.sub("<email>", t)
    t = URL_RE.sub("<url>", t)
    t = re.sub(r"\bj-[a-z0-9-]{6,}", "<job>", t)
    t = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", t)
    t = re.sub(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(z|[+-]\d{2}:?\d{2})?", "<ts>", t)
    t = re.sub(r"\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{15,18}\b", "<id>", t)
    t = re.sub(r"\d+(\.\d+)?", "#", t)
    return re.sub(r"\s+", " ", t).strip()[:300]


def signature(fingerprint):
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:8]


def similar(a, b, threshold):
    if not a or not b:
        return False
    if a == b:
        return True
    matcher = difflib.SequenceMatcher(None, a[:200], b[:200], autojunk=False)
    return (matcher.real_quick_ratio() >= threshold and matcher.quick_ratio() >= threshold
            and matcher.ratio() >= threshold)


CODE_RE = re.compile(r"\b[A-Z][A-Z]{2,}(?:_[A-Z]{2,})+\b")
HTTP_RE = re.compile(r"\b([45]\d\d)\s+(Bad Request|Unauthorized|Forbidden|Not Found|Conflict|"
                     r"Too Many Requests|Internal Server Error|Bad Gateway|Service Unavailable|"
                     r"Gateway Time-?out|Unprocessable Entity|Request Timeout|Method Not Allowed)\b",
                     re.I)


def error_codes(value):
    text = plain(value)
    codes = CODE_RE.findall(text)
    codes += ["HTTP {}".format(m.group(1)) for m in HTTP_RE.finditer(text)]
    seen, out = set(), []
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def category_rules(extra):
    rules = []
    for rule in (extra.get("category_rules") or []):
        if isinstance(rule, dict) and rule.get("key") and rule.get("patterns"):
            rules.append((text_of(rule["key"]), text_of(rule.get("label") or rule["key"]),
                          text_of(rule.get("icon") or "❓"), tuple(rule["patterns"])))
    labels = {key: (label, icon) for key, label, icon, _ in CATEGORIES}
    labels.update({key: (label, icon) for key, label, icon, _ in EXTRA_RULES if label})
    extras = tuple((key, labels[key][0], labels[key][1], patterns) for key, _, _, patterns in EXTRA_RULES)
    compiled = []
    for key, label, icon, patterns in tuple(rules) + extras + CATEGORIES:
        regs = []
        for pattern in patterns:
            try:
                regs.append(re.compile(pattern, re.I))
            except re.error:
                continue
        compiled.append((key, label, icon, regs))
    return compiled


def classify(value, rules):
    text = plain(value)
    if not text:
        return "unknown"
    for key, _, _, regs in rules:
        for reg in regs:
            if reg.search(text):
                return key
    return "unknown"


def category_info(key, rules):
    for k, label, icon, _ in rules:
        if k == key:
            return label, icon
    if key == STOP_JOB[0]:
        return STOP_JOB[1], STOP_JOB[2]
    return UNKNOWN[1], UNKNOWN[2]


# ------------------------------------------------------------------ time and dates


class _USPacific(tzinfo):
    """America/Los_Angeles for a Python without zoneinfo data."""

    @staticmethod
    def _window(year):
        march8 = datetime(year, 3, 8, 2)
        nov1 = datetime(year, 11, 1, 2)
        return (march8 + timedelta(days=(6 - march8.weekday()) % 7),
                nov1 + timedelta(days=(6 - nov1.weekday()) % 7))

    def dst(self, dt):
        if dt is None:
            return timedelta(0)
        start, end = self._window(dt.year)
        return timedelta(hours=1) if start <= dt.replace(tzinfo=None) < end else timedelta(0)

    def utcoffset(self, dt):
        return timedelta(hours=-8) + self.dst(dt)

    def tzname(self, dt):
        return "PDT" if self.dst(dt) else "PST"

    def fromutc(self, dt):
        std = dt.replace(tzinfo=None) - timedelta(hours=8)
        start, end = self._window(std.year)
        if start <= std < end - timedelta(hours=1):
            std += timedelta(hours=1)
        return std.replace(tzinfo=self)


PACIFIC = _USPacific()


def get_tz(name):
    name = text_of(name).strip() or "America/Los_Angeles"
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - no tz data, or an unknown name
            pass
    if name in ("America/Los_Angeles", "US/Pacific", "PST8PDT", "PST", "PDT"):
        return PACIFIC
    match = re.match(r"^(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?$", name)
    if match:
        minutes = int(match.group(2)) * 60 + int(match.group(3) or 0)
        return timezone(timedelta(minutes=minutes if match.group(1) == "+" else -minutes))
    return timezone.utc


def parse_dt(value, tz):
    """A datetime from ISO text, 'YYYY-MM-DD HH:MM:SS.fff', epoch seconds or a datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        stamp = float(value) / (1000.0 if value > 1e11 else 1.0)
        dt = datetime.fromtimestamp(stamp, timezone.utc)
    else:
        text = text_of(value).strip().replace("Z", "+00:00")
        text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
        text = re.sub(r"(\.\d{6})\d+", r"\1", text)
        match = re.match(r"^(.*\.)(\d{1,5})([+-]\d{2}:\d{2})?$", text)
        if match:  # pad fractions to 6 digits for older fromisoformat
            text = match.group(1) + match.group(2).ljust(6, "0") + (match.group(3) or "")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz) if not isinstance(tz, _USPacific) else PACIFIC.fromutc(
            (dt - PACIFIC.utcoffset(dt)).replace(tzinfo=PACIFIC))
    return dt.astimezone(tz)


def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})", text_of(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def tz_label(dt):
    name = dt.tzname() or ""
    if re.match(r"^[A-Z]{2,5}$", name):
        return name
    offset = dt.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    return "UTC{}{:02d}:{:02d}".format("+" if minutes >= 0 else "-", abs(minutes) // 60, abs(minutes) % 60)


def clock(dt):
    hour = dt.hour % 12 or 12
    return "{}:{:02d} {}".format(hour, dt.minute, "AM" if dt.hour < 12 else "PM")


def long_when(dt):
    return "{}, {} {} {} {} {}".format(dt.strftime("%A"), dt.day, dt.strftime("%B"), dt.year,
                                       clock(dt), tz_label(dt))


def short_when(dt):
    return "{} {} {} · {} {}".format(dt.strftime("%a"), dt.day, dt.strftime("%b"), clock(dt), tz_label(dt))


def pill_when(dt):
    """19 Nov · 11:42 PM PST: the shortest label, so the time pill fits on the row of pills with the others."""
    return "{} {} · {} {}".format(dt.day, dt.strftime("%b"), clock(dt), tz_label(dt))


def compact_when(dt):
    """19 Nov 2026 · 11:10 AM PST: short enough for one line in a tile."""
    return "{} {} {} · {} {}".format(dt.day, dt.strftime("%b"), dt.year, clock(dt), tz_label(dt))


def short_day(d):
    return "{} {}".format(d.day, d.strftime("%b"))


def rel_day(d, today):
    days = (today - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return "{} days ago".format(days)
    return "on {}".format(short_day(d) + ("" if d.year == today.year else " {}".format(d.year)))


def rel_age(then, now):
    seconds = (now - then).total_seconds()
    if seconds < 3600:
        return "{} min ago".format(max(1, int(seconds // 60)))
    if seconds < 48 * 3600:
        return "{} h ago".format(int(seconds // 3600))
    return "{} days ago".format(int(seconds // 86400))


def duration(seconds):
    if seconds is None:
        return ""
    if seconds < 1:
        return "{:.2f} s".format(seconds)
    if seconds < 90:
        return "{:.1f} s".format(seconds)
    if seconds < 5400:
        return "{} min {} s".format(int(seconds // 60), int(seconds % 60))
    return "{:.1f} h".format(seconds / 3600.0)


# ---------------------------------------------------------------------- settings


def settings(inp):
    """Inputs over config_json over defaults. Returns (cfg, warnings)."""
    warnings, extra = [], {}
    raw = inp.get("config_json")
    if isinstance(raw, dict):
        extra = raw
    elif text_of(raw).strip():
        try:
            extra = json.loads(text_of(raw))
        except ValueError:
            extra = None
        if not isinstance(extra, dict):
            warnings.append("config_json is not a JSON object, so it was ignored")
            extra = {}
    cfg = {}
    for spec in SETTINGS:
        name, kind, default = spec[0], spec[1], spec[2]
        value = inp.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = extra.get(name)
        if kind in ("str", "secret"):
            text = text_of(value).strip()
            cfg[name] = text if text else default
        elif kind == "bool":
            cfg[name] = truthy(value, default)
        elif kind == "color":
            cfg[name] = css_color(value) or default
        else:
            number = (to_int if kind == "int" else to_float)(value, None)
            if number is None:
                number = default
            cfg[name] = max(spec[3], min(spec[4], number))
    cfg["look"] = cfg["look"].lower()
    if cfg["look"] not in ("new", "old"):
        warnings.append("look '{}' is not new or old, so the new look was used".format(cfg["look"]))
        cfg["look"] = "new"
    if 0 < cfg["max_width"] < 480:                      # an explicit width is at least 480; 0 means "fit the table"
        cfg["max_width"] = 480
    cfg["hero_layout"] = cfg["hero_layout"].lower()
    if cfg["hero_layout"] not in ("new", "classic"):
        warnings.append("hero_layout '{}' is not new or classic, so the new header was used".format(cfg["hero_layout"]))
        cfg["hero_layout"] = "new"
    cfg["extra"] = extra
    return cfg, warnings


def resolve_sections(cfg, warnings):
    def names(text):
        out = []
        for part in re.split(r"[,\s;|]+", text_of(text).lower()):
            if part:
                head, dot, tail = part.partition(".")
                out.append(SECTION_ALIASES.get(head, head) + dot + tail)
        return out
    detail = cfg["detail"].lower()
    if detail not in DETAIL_PRESETS:
        warnings.append("detail '{}' is not brief, standard or full, so standard was used".format(detail))
        detail = "standard"
    explicit, added = names(cfg["sections"]), names(cfg["show_sections"])
    if explicit:
        wanted = explicit + [n for n in added if n not in explicit]
    else:
        wanted = [n for n in DEFAULT_SECTIONS if n in DETAIL_PRESETS[detail] or n in added]
    unknown = [n for n in explicit + added if n not in DEFAULT_SECTIONS]
    if unknown:
        warnings.append("unknown sections ignored: {}".format(", ".join(unknown)))
    hide_all = names(cfg["hide_sections"])
    cfg["hide_subs"] = {h for h in hide_all if h in SUBSECTIONS}
    bad = [h for h in hide_all if h not in DEFAULT_SECTIONS and h not in SUBSECTIONS]
    if bad:
        warnings.append("unknown names in hide_sections ignored: {}".format(", ".join(bad)))
    hidden = set(hide_all)
    seen, order = set(), []
    for name in wanted:
        if name in DEFAULT_SECTIONS and name not in hidden and name not in seen:
            seen.add(name)
            order.append(name)
    return order


# ---------------------------------------------------------------------- the inputs

FACT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9 ._()/#'&-]{1,48}?)\s*:\s*(.+)$")
NUMBER_RE = re.compile(r"^\s*(-?\d[\d,]*(?:\.\d+)?)\s*(%|records?|rows?|items?)?\s*$", re.I)


def parse_details(value):
    """Split an error message into a headline, 'Label : value' facts and batch numbers."""
    lines = html_to_lines(value)
    out = {"headline": lines[0] if lines else "", "facts": [], "extra": [], "metrics": {},
           "processing": {}}
    for line in lines[1:]:
        match = FACT_RE.match(line)
        if match and not CODE_RE.match(match.group(1).strip()):
            label = match.group(1).strip()
            val = re.sub(r"\s+\.$", "", match.group(2).strip()) or match.group(2).strip()
            out["facts"].append((label, val))
        else:
            out["extra"].append(line)
    metrics = out["metrics"]
    for label, val in out["facts"]:
        number = NUMBER_RE.match(val)
        if not number:
            continue
        amount = to_int(number.group(1))
        low = label.lower()
        if "total" in low and "total" not in metrics:
            metrics["total"] = amount
        elif re.search(r"fail|error|reject|skip", low) and "failed" not in metrics:
            metrics["failed"] = amount
        elif re.search(r"succe|processed|synced|created|updated|inserted|upserted|passed", low) \
                and "succeeded" not in metrics:
            metrics["succeeded"] = amount
    whole = " ".join(lines)
    sync = re.search(r"retrieved\s+(\d[\d,]*)\s+([A-Za-z]\w*)\b.*?failed\s+to\s+synchroni[sz]e"
                     r"(?:\s+(\d[\d,]*))?", whole, re.I)
    if sync:
        metrics.setdefault("total", to_int(sync.group(1)))
        if sync.group(3):
            metrics.setdefault("failed", to_int(sync.group(3)))
        out["processing"].setdefault("object", sync.group(2))
    if lines:
        proc = re.search(r"processing\s+(.+?)\s+records?\s+from\s+(.+?)\s+to\s+(.+?)\s*[.!]?$",
                         lines[0], re.I)
        if proc:
            out["processing"].update({"object": proc.group(1).strip(), "source": proc.group(2).strip(),
                                      "target": proc.group(3).strip()})
    if "total" in metrics and "failed" not in metrics and "succeeded" in metrics:
        metrics["failed"] = max(0, metrics["total"] - metrics["succeeded"])
    return out


def read_records(inp):
    """The failed-records table: the column headers and the rows of dataArray."""
    cols = []
    for i in range(1, 6):
        name = text_of(inp.get("column{}Name".format(i))).strip()
        if name:
            cols.append({"i": i, "name": name, "width": to_int(inp.get("column{}Width".format(i)))})
    raw = inp.get("dataArray")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = []
    if isinstance(raw, dict):
        raw = [raw]
    rows = []
    for item in raw if isinstance(raw, (list, tuple)) else []:
        if not isinstance(item, dict) or not text_of(item.get("value1")).strip():
            continue  # the moustache template shows a row only when value1 is there
        row = {}
        for i in range(1, 6):
            row[i] = {"value": text_of(item.get("value{}".format(i))),
                      "url": text_of(item.get("url{}".format(i))).strip(),
                      "bold": text_of(first(item, "column{}_bold".format(i), "column{}Bold".format(i))).strip(),
                      "color": text_of(first(item, "column{}_color".format(i), "column{}Color".format(i))).strip()}
        rows.append(row)
    return cols, rows


MESSAGE_WORDS = re.compile(r"message|description|detail|reason|exception|cause|failure", re.I)
ERROR_WORDS = re.compile(r"error|fail|issue|problem", re.I)
ID_NAME = re.compile(r"(^|[\s_-])(id|ids|key|keys|number|no|ref|reference|uuid|guid|sku|external|primary)($|[\s_-])", re.I)


def avg_len(rows, i):
    values = [r[i]["value"] for r in rows[:200] if r[i]["value"]]
    return sum(len(v) for v in values) / float(len(values)) if values else 0.0


def pick_error_column(cols, rows):
    """The column that holds the error text. A name that says message / reason / detail beats one that only says
    'error' (so an 'Error Date' or an 'Errors' count is not taken for it); the longer text wins a tie."""
    scored = []
    for c in cols:
        score = 2 if MESSAGE_WORDS.search(c["name"]) else (1 if ERROR_WORDS.search(c["name"]) else 0)
        if score:
            scored.append((score, avg_len(rows, c["i"]), -c["i"], c["i"]))
    if scored:
        return max(scored)[3]
    return cols[-1]["i"] if len(cols) > 1 else None


def looks_like_id(col, rows):
    """A column of ids or keys: named like one, or values that are single tokens with digits (not dates)."""
    if ID_NAME.search(col["name"]):
        return True
    values = [r[col["i"]]["value"].strip() for r in rows[:200] if r[col["i"]]["value"].strip()]
    if len(values) < 2:
        return False
    tokens = sum(1 for v in values if " " not in v and re.search(r"\d", v) and len(v) >= 6
                 and not re.match(r"^\d{4}-\d{2}-\d{2}", v))
    return tokens >= 0.8 * len(values)


def analyze_records(cols, rows, rules):
    out = {"count": len(rows), "err_col": None, "id_cols": [], "codes": Counter(),
           "categories": Counter(), "distinct_errors": 0, "duplicates": {}, "dup_rows": 0}
    if not cols or not rows:
        return out
    err_col = pick_error_column(cols, rows)
    out["err_col"] = err_col
    out["id_cols"] = [c["i"] for c in cols if c["i"] != err_col and looks_like_id(c, rows)][:2]
    distinct = set()
    for row in rows:
        message = row[err_col]["value"] if err_col else ""
        if message.strip():
            out["codes"].update(error_codes(message))
            out["categories"][classify(message, rules)] += 1
            distinct.add(fingerprint_text(message))
    out["distinct_errors"] = len(distinct)
    for i in out["id_cols"]:
        counts = Counter(r[i]["value"].strip() for r in rows if r[i]["value"].strip())
        dups = {v: n for v, n in counts.items() if n > 1}
        if dups:
            out["duplicates"][i] = dups
    if out["duplicates"]:
        first_col = sorted(out["duplicates"])[0]
        out["dup_rows"] = sum(out["duplicates"][first_col].values())
    return out


def parse_job_url(url):
    text = text_of(url).strip()
    match = re.search(r"/recipes/(\d+)[^/]*/job/([^/?#]+)", text)
    query = urllib_parse.parse_qs(urllib_parse.urlsplit(text).query) if text else {}
    child = (query.get("child_job_id") or [""])[0]
    host = ""
    if text:
        parts = urllib_parse.urlsplit(text)
        if parts.scheme and parts.netloc:
            host = "{}://{}".format(parts.scheme, parts.netloc)
    return (match.group(1) if match else "", match.group(2) if match else "", child, host)


def normalize_priority(value):
    key = re.sub(r"[^A-Z0-9]", "", text_of(value).upper())
    key = PRIORITY_ALIASES.get(key, key)
    return key if key in SEVERITY else "MEDIUM"


def severity_for(key, extra):
    sev = dict(SEVERITY[key])
    custom = (extra.get("severity") or {}).get(key) or (extra.get("severity") or {}).get(key.lower())
    if isinstance(custom, dict):
        for k, v in custom.items():
            if k in ("color", "soft", "ink", "line"):
                v = css_color(v)
            if v:
                sev[k] = v
    sev["key"] = key
    return sev


def env_for(value, extra):
    raw = text_of(value).strip()
    key = ENV_ALIASES.get(raw.upper(), raw.upper())
    base = dict(ENVIRONMENTS.get(key, ENVIRONMENTS["_"]))
    if not base["label"]:
        base["label"] = raw.title() if raw else ""
    custom = (extra.get("env_colors") or {}).get(key) or (extra.get("env_colors") or {}).get(raw.lower())
    if isinstance(custom, dict):
        for k in ("frame", "chip", "chip_text"):
            if css_color(custom.get(k)):
                base[k] = css_color(custom[k])
        if custom.get("label"):
            base["label"] = text_of(custom["label"])
    base["key"], base["raw"] = key, raw
    return base


def build_context(inp, cfg, now):
    extra = cfg["extra"]
    rules = category_rules(extra)
    rid, handle, child, host = parse_job_url(inp.get("job_url"))
    ctx = SimpleNamespace()
    ctx.inp, ctx.cfg, ctx.rules, ctx.extra = inp, cfg, rules, extra
    ctx.tz, ctx.now, ctx.today = now.tzinfo, now, now.date()
    ctx.recipe_name = text_of(inp.get("recipe_name")).strip() or "Unnamed recipe"
    ctx.subject_in = text_of(inp.get("subject")).strip() or "Error in " + ctx.recipe_name
    ctx.mail_msg = text_of(inp.get("mail_msg")).strip()
    ctx.job_url = safe_url(inp.get("job_url"))
    ctx.job_url_base = ctx.job_url.split("?", 1)[0]
    # The old recipe took these from its trigger's context; the job URL is the fallback.
    ctx.recipe_id = (re.sub(r"\D", "", cfg["recipe_id"]) or re.sub(r"\D", "", text_of(inp.get("calling_recipe_id")))
                     or rid)
    ctx.url_job_handle, ctx.child_job_id = handle, child
    ctx.job_handle = text_of(inp.get("calling_job_id")).strip() or child or handle
    ctx.to_email = text_of(inp.get("to_email_address")).strip() or cfg["alert_email"]
    ctx.error_file_path = text_of(inp.get("error_file_path")).strip()
    ctx.error_file_expires_in = to_int(inp.get("error_file_expires_in"))
    ctx.app_host = host if "workato" in host else "https://app.workato.com"
    ctx.recipe_url = "{}/recipes/{}".format(ctx.app_host, ctx.recipe_id) if ctx.recipe_id else ""
    ctx.error_raw = text_of(inp.get("error_details"))
    ctx.error_plain = plain(ctx.error_raw)
    ctx.details = parse_details(ctx.error_raw)
    ctx.priority_raw = text_of(inp.get("priority")).strip()
    ctx.priority = normalize_priority(ctx.priority_raw)
    ctx.priority_in = ctx.priority
    ctx.escalation = ""
    ctx.sev = severity_for(ctx.priority, extra)
    ctx.env = env_for(cfg["env"], extra)
    ctx.source = text_of(inp.get("sourceSystem")).strip()
    ctx.target = text_of(inp.get("targetSystem")).strip()
    ctx.source_obj = text_of(inp.get("sourceObject")).strip()
    ctx.target_obj = text_of(inp.get("targetObject")).strip()
    ctx.errored_app = text_of(inp.get("ErroredApp")).strip()
    ctx.errored_action = text_of(inp.get("ErroredAction")).strip()
    ctx.step = text_of(inp.get("stepNumber")).strip()
    ctx.retry_count = to_int(inp.get("retry_count"))
    ctx.file_name = text_of(inp.get("file_name")).strip()
    ctx.error_file_url = safe_url(cfg["error_file_url"])
    ctx.frequency = to_int(inp.get("frequency"))
    ctx.error_limit = to_int(inp.get("error_limit"))
    ctx.sch_run = truthy(inp.get("sch_run"))
    ctx.is_repeated = truthy(inp.get("is_Repeated"))
    ctx.master_job_id = text_of(inp.get("calling_master_job_id")).strip()
    ctx.error_time = cfg["error_time"] or compact_when(now)

    ctx.cols, ctx.rows = read_records(inp)
    ctx.rec = analyze_records(ctx.cols, ctx.rows, rules)

    proc = ctx.details["processing"]
    ctx.source_label = pretty_name(ctx.source) or proc.get("source", "")
    ctx.target_label = pretty_name(ctx.target) or proc.get("target", "")
    ctx.object_label = proc.get("object") or ctx.target_obj or ctx.source_obj
    ctx.app_label = (app_label(ctx.errored_app, extra.get("app_names"))
                     if ctx.errored_app and norm_system(ctx.errored_app) not in INTERNAL_APPS
                     else "") or ctx.target_label or "the connected app"

    metrics = dict(ctx.details["metrics"])
    if "failed" not in metrics and ctx.rec["count"] and "total" in metrics:
        metrics["failed"] = ctx.rec["count"]
    ctx.total, ctx.failed = metrics.get("total"), metrics.get("failed")
    ctx.rate = None
    if ctx.total and ctx.failed is not None and ctx.total >= ctx.failed:
        ctx.rate = 100.0 * (ctx.total - ctx.failed) / ctx.total
    ctx.is_batch = bool(ctx.total is not None or ctx.failed is not None or ctx.rec["count"])

    ctx.message_category = classify(ctx.error_raw, rules)
    row_cat = ""
    if ctx.rec["categories"]:
        row_cat = ctx.rec["categories"].most_common(1)[0][0]
    category = ctx.message_category
    if row_cat and row_cat != "unknown" and category in ("partial_batch", "unknown"):
        category = row_cat
    if category == "unknown" and ctx.errored_action.lower() in ("stop", "stop_job"):
        category = STOP_JOB[0]
    ctx.category = category
    ctx.match_categories = {category, ctx.message_category} - {"unknown"}
    ctx.fp = fingerprint_text(ctx.error_raw or " ".join(r[ctx.rec["err_col"]]["value"]
                                                       for r in ctx.rows[:1] if ctx.rec["err_col"]))
    ctx.signature = signature(ctx.fp or ctx.recipe_name)
    ctx.codes = Counter(error_codes(ctx.error_raw))
    ctx.codes.update(ctx.rec["codes"])

    ctx.history = None
    ctx.cross = None
    ctx.recipe_info = ctx.job_info = ctx.jobs_info = None
    ctx.developer = None
    ctx.hide_subs = set()
    ctx.history_rows = None
    ctx.cross_rows = None
    ctx.decision = {"reprocessable": False, "source": "", "reason": "", "confidence": ""}
    ctx.repeat = {"attempted": False, "enqueued": False, "job_id": "", "error": "", "skipped": ""}
    ctx.master = ""
    ctx.action, ctx.send_email = "notify", True
    ctx.table_row = {}
    ctx.ai_error = ""                     # why Azure gave no answer, when it was asked (see ai_story)
    ctx.row_tried = False
    ctx.signals, ctx.tiles = [], []
    return ctx


# ------------------------------------------------------------------------- http


class FetchError(Exception):
    pass


def http_json(method, url, headers, payload=None, timeout=12):
    """(body, error). Never raises on an HTTP or network failure."""
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib_request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib_error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            detail = ""
        return None, "{} {}: {}".format(urllib_parse.urlsplit(url).netloc, exc.code, clip(detail, 300))
    except Exception as exc:  # noqa: BLE001 - timeouts, DNS, TLS
        return None, "{}: {}: {}".format(urllib_parse.urlsplit(url).netloc, type(exc).__name__,
                                         clip(str(exc), 200))
    if not raw.strip():
        return {}, None
    try:
        return json.loads(raw), None
    except ValueError:
        return None, "{}: response is not JSON".format(urllib_parse.urlsplit(url).netloc)


def remaining(deadline):
    return deadline - time.time()


def call_timeout(cfg, deadline):
    left = remaining(deadline)
    if left < 1:
        raise FetchError("time budget used up")
    return max(1, min(cfg["http_timeout"], left))


def decode_rows(body):
    """The data table query endpoint returns schema and data as arrays of arrays."""
    if not isinstance(body, dict):
        return []
    data = body.get("data") or body.get("records") or []
    if data and isinstance(data[0], dict):
        return [row.get("document") if isinstance(row.get("document"), dict) else row for row in data]
    columns = [f.get("name") for group in body.get("schema", []) for f in
               (group if isinstance(group, list) else [group]) if isinstance(f, dict)]
    rows = []
    for row in data:
        values = [v for group in row for v in (group if isinstance(group, list) else [group])] \
            if isinstance(row, list) else []
        rows.append(dict(zip(columns, values)))
    return rows


class Rows(list):
    """The rows read from the data table. `cut` is True when the row cap stopped the reading before the end."""
    cut = False


def fetch_table(cfg, where, deadline, max_rows=2400):
    """Newest rows first, so that if the cap cuts the list it cuts the oldest rows, not today's. If the table API
    refuses the `order` the rows are read without it (and the warning about a cut list says they may be any rows)."""
    url = "{}/{}/query".format(cfg["data_tables_base"].rstrip("/"), cfg["data_table_id"])
    headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Content-Type": "application/json"}
    columns = list((cfg["extra"].get("table_columns") or {}).values()) or list(HISTORY_COLUMNS)
    rows, token = Rows(), None
    order = {"by": "$created_at", "direction": "desc"}
    pages_left = max_rows // 200 + 1
    while pages_left > 0:
        payload = {"select": columns, "where": where, "limit": 200}
        if order:
            payload["order"] = order
        if token:
            payload["continuation_token"] = token
        body, err = http_json("POST", url, headers, payload, call_timeout(cfg, deadline))
        if err and order and not token and re.search(r" 4(00|22): ", err):     # the order was refused: ask again without
            order = None
            continue
        if err:
            raise FetchError(err)
        pages_left -= 1
        rows.extend(decode_rows(body))
        token = body.get("continuation_token") if isinstance(body, dict) else None
        if not token or len(rows) >= max_rows:
            break
    rows.cut = bool(token)
    return rows


def table_column(cfg, field, default):
    return (cfg["extra"].get("table_columns") or {}).get(field) or default


def fetch_history(cfg, ctx, deadline):
    since = (ctx.today - timedelta(days=cfg["history_days"] - 1)).isoformat()
    if ctx.recipe_id:
        who = {table_column(cfg, "recipe_id", "Recipie Id"): {"$eq": ctx.recipe_id}}
    else:
        who = {table_column(cfg, "recipe_name", "Recipe Name"): {"$eq": ctx.recipe_name}}
    when = {table_column(cfg, "date", "Date"): {"$gte": since}}
    try:
        return fetch_table(cfg, {"$and": [who, when]}, deadline)
    except FetchError as exc:
        if re.search(r" 4(00|22): ", str(exc)):     # the date filter was refused: filter here
            return fetch_table(cfg, who, deadline)
        raise


def fetch_cross(cfg, ctx, deadline):
    since = (ctx.today - timedelta(days=cfg["cross_recipe_days"] - 1)).isoformat()
    return fetch_table(cfg, {table_column(cfg, "date", "Date"): {"$gte": since}}, deadline, max_rows=1000)


def workato_get(cfg, path, deadline):
    url = cfg["workato_api_base"].rstrip("/") + path
    headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Accept": "application/json"}
    body, err = http_json("GET", url, headers, None, call_timeout(cfg, deadline))
    if err:
        raise FetchError(err)
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        return body["result"]
    return body if isinstance(body, dict) else {}


def find_developer(cfg, ctx, deadline):
    """{name, email} or None: who wrote the recipe (see DEVELOPER_EMAIL_DOMAIN). Usually one or two calls: the first
    version is the developer's own."""
    rid = urllib_parse.quote(ctx.recipe_id)
    latest = workato_get(cfg, "/recipes/{}?exclude_code=yes".format(rid), deadline)
    newest = to_int(latest.get("version_no"), 1) or 1
    for version_no in range(1, min(newest, DEVELOPER_MAX_VERSIONS) + 1):
        if version_no == newest:
            recipe = latest
        else:
            try:
                recipe = workato_get(cfg, "/recipes/{}?exclude_code=yes&version_no={}".format(rid, version_no), deadline)
            except FetchError as exc:
                if " 404:" in str(exc):          # a gap in the version history
                    continue
                raise
        email = text_of(recipe.get("version_author_email")).strip().lower()
        if email.endswith("@" + DEVELOPER_EMAIL_DOMAIN):
            return {"name": text_of(recipe.get("version_author_name")).strip(), "email": email}
    return None


def find_step(code, number):
    """The step with this line number in the recipe's code."""
    wanted = to_int(number)
    if wanted is None or not code:
        return None
    if isinstance(code, str):
        try:
            code = json.loads(code)
        except ValueError:
            return None
    stack = [code]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if to_int(node.get("number")) == wanted and ("provider" in node or "keyword" in node):
                return {"provider": text_of(node.get("provider")), "name": text_of(node.get("name")),
                        "keyword": text_of(node.get("keyword")),
                        "title": clip(plain(node.get("title") or node.get("description") or ""), 120),
                        "comment": clip(plain(node.get("comment") or ""), 200)}
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
        elif isinstance(node, list):
            stack.extend(node)
    return None


def parse_recipe(body, ctx):
    apps = body.get("action_applications")
    return {"name": text_of(body.get("name")), "running": body.get("running"),
            "version": to_int(body.get("version_no")),
            "updated_at": parse_dt(body.get("updated_at"), ctx.tz),
            "last_run_at": parse_dt(body.get("last_run_at"), ctx.tz),
            "succeeded": to_int(body.get("job_succeeded_count")),
            "failed": to_int(body.get("job_failed_count")),
            "trigger": text_of(body.get("trigger_application")),
            "apps": [text_of(a) for a in apps] if isinstance(apps, list) else [],
            "stop_cause": text_of(body.get("stop_cause")),
            "editor": text_of(body.get("version_author_name")) if ctx.cfg["show_editor"] else "",
            "step": find_step(body.get("code"), ctx.step)}


def parse_job(body, ctx):
    lines = body.get("lines") if isinstance(body.get("lines"), list) else []
    info = {"status": text_of(body.get("status")).lower() or ("failed" if body.get("is_error") else ""),
            "started_at": parse_dt(body.get("started_at"), ctx.tz),
            "completed_at": parse_dt(body.get("completed_at"), ctx.tz),
            "error": clip(plain(body.get("error")), 300), "lines": len(lines),
            "failed_line": None, "slowest": None, "error_type": "", "error_message": "",
            "retry_count": None, "error_at": None, "duration": None,
            "is_repeat": truthy(body.get("is_repeat")),
            "master_job_id": text_of(body.get("master_job_id") or body.get("master_job_handle")).strip()}
    for line in lines:
        if not isinstance(line, dict):
            continue
        number = to_int(first(line, "recipe_line_number", "line_number", "number"))
        adapter = text_of(first(line, "adapter_name", "adapter", "provider"))
        operation = text_of(first(line, "adapter_operation", "operation", "name"))
        stat = line.get("line_stat") if isinstance(line.get("line_stat"), dict) else {}
        seconds = to_float(stat.get("total"))
        if seconds is not None and (info["slowest"] is None or seconds > info["slowest"]["seconds"]):
            info["slowest"] = {"number": number, "adapter": adapter, "action": operation, "seconds": seconds}
        err = None
        output = line.get("output")
        if isinstance(output, dict) and isinstance(output.get("error"), dict) \
                and (output["error"].get("message") or output["error"].get("type")):
            err = output["error"]
        elif line.get("error"):
            err = line["error"] if isinstance(line["error"], dict) else {"message": line["error"]}
        if err:
            info["failed_line"] = {"number": to_int(err.get("line_number"), number),
                                   "adapter": text_of(err.get("adapter") or adapter),
                                   "action": text_of(err.get("action") or operation)}
            info["error_type"] = text_of(err.get("type"))
            info["error_message"] = clip(plain(err.get("message")), 300)
            info["retry_count"] = to_int(err.get("retry_count"))
            info["error_at"] = parse_dt(err.get("error_at"), ctx.tz)
    end = info["error_at"] or info["completed_at"]
    if info["started_at"] and end and end >= info["started_at"]:
        info["duration"] = (end - info["started_at"]).total_seconds()
    return info


def parse_jobs(body, ctx):
    items = body.get("jobs") or body.get("items") or body.get("data") or []
    jobs = []
    for job in items[: ctx.cfg["recent_jobs"]] if isinstance(items, list) else []:
        if not isinstance(job, dict):
            continue
        status = text_of(job.get("status")).lower()
        if status in ("succeeded", "success", "completed", "ok"):
            state = "ok"
        elif status in ("failed", "error", "errored") or job.get("is_error") is True:
            state = "fail"
        else:
            state = "pending"
        jobs.append({"state": state, "started_at": parse_dt(job.get("started_at") or job.get("created_at"), ctx.tz),
                     "id": text_of(first(job, "id", "handle", "job_id")).strip(), "why": ""})
    counts = Counter(j["state"] for j in jobs)
    return {"jobs": jobs, "ok": counts["ok"], "fail": counts["fail"], "pending": counts["pending"],
            "known": False, "errors": counts["fail"], "clean": counts["ok"], "others": counts["fail"],
            "counted": counts["ok"] + counts["fail"]}


def mark_failed_runs(ctx):
    """Which of the recent jobs really hit an error.

    These recipes catch their errors with an error handler that sends this alert, so Workato calls the job succeeded and
    its own status can never show a failure. The error log table can: it holds the job id of every error. A recent job
    whose id is in the log (or is this very run) is marked as having an error. Without the log, or without job ids in
    the jobs list, nothing is marked and `known` stays False (the tile and the signal then keep out of it)."""
    jobs, h = ctx.jobs_info, ctx.history
    if not (jobs and jobs["jobs"]):
        return
    here = {j.lower() for j in (ctx.job_handle, ctx.url_job_handle, ctx.child_job_id, ctx.master_job_id) if j}
    logged = set(h["logged_jobs"]) if h else set()
    if not (h and any(j["id"] for j in jobs["jobs"])):
        return
    since = h["since"]
    errors = clean = running = others = 0
    for job in jobs["jobs"]:
        ident = job["id"].lower()
        if job["started_at"] and job["started_at"].date() < since:
            job["why"] = "older than the {} days of the error log, so its result is not known".format(h["days"])
            continue
        mine = bool(ident) and ident in here
        if bool(ident) and (ident in logged or mine):
            job["state"], job["why"] = "fail", ("this run: error alert sent" if mine else "an error was logged for this run")
            errors += 1
            others += 0 if mine else 1
        elif job["state"] == "fail":
            job["why"] = "failed in Workato"
            errors += 1
            others += 1
        elif job["state"] == "ok":
            job["why"] = "ran clean: no error logged"
            clean += 1
        else:
            job["why"] = "still running"
            running += 1
    jobs.update({"known": True, "errors": errors, "clean": clean, "pending": running, "others": others,
                 "counted": errors + clean, "fail": errors, "ok": clean})


def load_rows_json(text):
    data = text
    if isinstance(text, str):
        try:
            data = json.loads(text)
        except ValueError:
            return None
    if isinstance(data, dict):
        data = data.get("rows") or data.get("records") or data.get("data") or []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else None


def gather(ctx, deadline, warnings, need_history, need_job=False):
    """History rows, other recipes' rows, the recipe, the job and recent jobs, in parallel.

    need_job: the job is needed for its master job id or its is_repeat flag, even when no
    section shows job details."""
    cfg = ctx.cfg
    token = cfg["workato_api_token"]
    tasks = {}
    if need_history:
        given = cfg["history_rows_json"]
        if given:
            rows = load_rows_json(given)
            if rows is None:
                warnings.append("history_rows_json is not a JSON list of rows, so history was skipped")
            else:
                ctx.history_rows = ctx.cross_rows = rows
        elif token:
            tasks["history"] = lambda: fetch_history(cfg, ctx, deadline)
            if cfg["cross_recipe_days"] and {"signals", "hero"} & ctx.sections_wanted:     # a logged-only call needs no cross-recipe view
                tasks["cross"] = lambda: fetch_cross(cfg, ctx, deadline)
        else:
            warnings.append("history skipped: no workato_api_token")
    want_context = cfg["job_context"] and bool({"job", "signals", "kpis", "flow"} & ctx.sections_wanted)
    if want_context or need_job:
        if not token:
            warnings.append("job context skipped: no workato_api_token")
        elif not ctx.recipe_id:
            warnings.append("job context skipped: no recipe id in job_url or calling_recipe_id")
        else:
            rid = urllib_parse.quote(ctx.recipe_id)
            if want_context:
                tasks["recipe"] = lambda: workato_get(cfg, "/recipes/{}".format(rid), deadline)
            if ctx.job_handle:
                handle = urllib_parse.quote(ctx.job_handle)
                tasks["job"] = lambda: workato_get(cfg, "/recipes/{}/jobs/{}".format(rid, handle), deadline)
            if want_context and cfg["recent_jobs"]:
                tasks["jobs"] = lambda: workato_get(cfg, "/recipes/{}/jobs".format(rid), deadline)
    if cfg["show_developer"] and "details" in ctx.sections_wanted:
        if not token:
            warnings.append("developer skipped: no workato_api_token")
        elif not ctx.recipe_id:
            warnings.append("developer skipped: no recipe id")
        else:
            tasks["developer"] = lambda: find_developer(cfg, ctx, deadline)
    if not tasks:
        return
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks))
    futures = {name: pool.submit(fn) for name, fn in tasks.items()}
    concurrent.futures.wait(list(futures.values()), timeout=max(0.5, remaining(deadline)))
    for name, future in futures.items():
        if not future.done():
            warnings.append("{} lookup timed out".format(name))
            continue
        try:
            body = future.result()
        except Exception as exc:  # noqa: BLE001
            warnings.append("{} lookup failed: {}".format(name, clip(str(exc), 240)))
            continue
        try:
            if name == "history":
                ctx.history_rows = body
                if getattr(body, "cut", False):
                    warnings.append("history: this recipe has more rows in the last {} days than the {} the step reads, "
                                    "so the repeat counts can be low".format(cfg["history_days"], len(body)))
            elif name == "cross":
                ctx.cross_rows = body
            elif name == "recipe":
                ctx.recipe_info = parse_recipe(body, ctx)
            elif name == "job":
                ctx.job_info = parse_job(body, ctx)
            elif name == "jobs":
                ctx.jobs_info = parse_jobs(body, ctx)
            elif name == "developer":
                ctx.developer = body
                if not body:
                    warnings.append("developer: no version of the recipe was written by a @{} address".format(
                        DEVELOPER_EMAIL_DOMAIN))
        except Exception as exc:  # noqa: BLE001
            warnings.append("{} response not understood: {}".format(name, clip(str(exc), 200)))
    pool.shutdown(wait=False)


# ---------------------------------------------------------------------- history


def normalize_history(raw_rows, ctx):
    columns = {k: norm_key(v) for k, v in (ctx.extra.get("table_columns") or {}).items()}
    out = []
    for raw in raw_rows or []:
        if not isinstance(raw, dict):
            continue
        row = {norm_key(k): v for k, v in raw.items()}

        def get(field):
            keys = ((columns[field],) if field in columns else ()) + HISTORY_FIELDS[field]
            for key in keys:
                if row.get(key) not in (None, ""):
                    return row[key]
            return ""
        ts = parse_dt(get("ts"), ctx.tz)
        day = parse_date(get("date")) or (ts.date() if ts else None)
        if day is None:
            continue
        message = text_of(get("message"))
        out.append({"date": day, "ts": ts, "recipe_id": text_of(get("recipe_id")).strip(),
                    "recipe_name": text_of(get("recipe_name")).strip(), "message": message,
                    "status": text_of(get("status")).strip(), "job_id": text_of(get("job_id")).strip(),
                    "master_job_id": text_of(get("master_job_id")).strip(),
                    "job_url": safe_url(get("job_url")),
                    "reprocess_count": to_int(get("reprocess_count"), 0),
                    "target": text_of(get("target")).strip(),
                    "category": classify(message, ctx.rules), "fp": fingerprint_text(message)})
    return out


def same_recipe(row, ctx):
    if ctx.recipe_id and row["recipe_id"]:
        return row["recipe_id"] == ctx.recipe_id
    return row["recipe_name"].lower() == ctx.recipe_name.lower()


def is_current(row, ctx):
    if ctx.job_handle and row["job_id"] == ctx.job_handle:
        return True
    return bool(ctx.job_url_base and row["job_url"] and row["job_url"].split("?", 1)[0] == ctx.job_url_base)


def is_same_type(row, ctx, threshold):
    if row["category"] in ctx.match_categories:
        return True
    return similar(row["fp"], ctx.fp, threshold)


def analyze_history(ctx):
    cfg = ctx.cfg
    rows = normalize_history(ctx.history_rows, ctx)
    today, days = ctx.today, cfg["history_days"]
    since = today - timedelta(days=days - 1)
    mine = [r for r in rows if same_recipe(r, ctx) and since <= r["date"] <= today and not is_current(r, ctx)]
    same = [r for r in mine if is_same_type(r, ctx, cfg["similarity"])]
    exact = sum(1 for r in same if r["fp"] == ctx.fp)
    week = sum(1 for r in same if r["date"] >= today - timedelta(days=6))
    prev_week = sum(1 for r in same if today - timedelta(days=13) <= r["date"] <= today - timedelta(days=7))
    month = sum(1 for r in same if r["date"] >= today - timedelta(days=29))
    week_total = week + 1                                      # this alert counts too
    first_seen = min((r["date"] for r in same), default=None)
    last_seen = max((r["date"] for r in same), default=None)
    gap = (today - last_seen).days if last_seen else None
    if not same:
        trend = "new"
    elif gap is not None and gap >= 30:
        trend = "returning"
    elif week_total >= 3 and week_total > 1.5 * prev_week:
        trend = "rising"
    elif week_total < prev_week:
        trend = "easing"
    else:
        trend = "steady"
    statuses = Counter(r["status"] for r in same if r["status"])
    reprocessed = [r for r in same if r["status"].lower() == "reprocessed"]
    chart = []
    for offset in range(cfg["chart_days"] - 1, -1, -1):
        day = today - timedelta(days=offset)
        s = sum(1 for r in same if r["date"] == day) + (1 if offset == 0 else 0)
        o = sum(1 for r in mine if r["date"] == day) - (s - (1 if offset == 0 else 0))
        chart.append((day, s, max(0, o), offset == 0))
    top = Counter(r["category"] for r in mine).most_common(4)
    # Every job this recipe logged an error for (the job itself, and the original when this one was a retry). The error
    # handler hides these failures from Workato, which marks the job succeeded, so the log is the only record of them.
    logged_jobs = set()
    for r in rows:
        if same_recipe(r, ctx) and since <= r["date"] <= today:
            logged_jobs.update(j.lower() for j in (r["job_id"], r["master_job_id"]) if j)

    def when(r):
        return r["ts"] or datetime(r["date"].year, r["date"].month, r["date"].day, tzinfo=ctx.tz)
    recent = sorted(same, key=when, reverse=True)[: cfg["similar_limit"]]
    hours = [r["ts"].hour for r in same if r["ts"]]
    hour_window = None
    if len(hours) >= 4:
        best = max(range(24), key=lambda h: hours.count(h) + hours.count((h + 1) % 24))
        share = (hours.count(best) + hours.count((best + 1) % 24)) / float(len(hours))
        if share >= 0.6:
            hour_window = (best, share)
    return {"days": days, "total": len(mine), "same": len(same), "exact": exact, "week": week,
            "week_total": week_total, "prev_week": prev_week, "month": month,
            "first_seen": first_seen, "last_seen": last_seen, "gap": gap, "trend": trend,
            "statuses": statuses, "reprocessed": len(reprocessed),
            "last_reprocessed": max((r["date"] for r in reprocessed), default=None),
            "failed_again": statuses.get("Failed Again", 0) + statuses.get("Failed again", 0),
            "chart": chart, "top": top, "recent": recent, "hour_window": hour_window,
            "occurrence": len(same) + 1, "logged_jobs": logged_jobs, "since": since}


def analyze_cross(ctx):
    cfg = ctx.cfg
    rows = normalize_history(ctx.cross_rows, ctx)
    since = ctx.today - timedelta(days=max(1, cfg["cross_recipe_days"]) - 1)
    cats = ctx.match_categories - {"partial_batch", STOP_JOB[0]}
    target = norm_system(ctx.target)
    hits = Counter()
    for row in rows:
        if row["date"] < since or row["date"] > ctx.today or same_recipe(row, ctx):
            continue
        same_target = target and norm_system(row["target"]) == target
        if row["category"] in cats and (same_target or (row["category"] in SYSTEMIC and not
                                                        (target and row["target"]))):
            hits[row["recipe_name"] or row["recipe_id"]] += 1
        elif similar(row["fp"], ctx.fp, max(0.8, cfg["similarity"])):
            hits[row["recipe_name"] or row["recipe_id"]] += 1
    return hits


# ------------------------------------------------------------------- the reading


def system_in_text(system, text):
    """Does the text name this system? 'SFDC_Services' is found as 'Salesforce' or 'SFDC', 'SalesforceService' as
    'Salesforce', 'Braze' as 'Braze'. Words like 'Services' alone never count."""
    def split(value):         # SalesforceService -> salesforce service
        return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text_of(value)).lower()
    # the text as written ('NetSuite') and with camelCase words apart ('SalesforceService' -> 'salesforce service')
    haystacks = [h for h in (text_of(text).lower(), split(text)) if h.strip()]
    for token in re.split(r"[^a-z0-9]+", split(system)):
        if not token or token in GENERIC_NAME_WORDS:
            continue
        candidates = {token} if len(token) >= 3 else set()
        candidates.update(new for old, new in SYSTEM_SYNONYMS if token == old)
        # a whole word, with an optional plural or 's: 'Braze' is in "Braze's API" but not in "Brazen"
        if any(re.search(r"(?<![a-z0-9])" + re.escape(c) + r"(?:'s|s)?(?![a-z0-9])", h)
               for c in candidates for h in haystacks):
            return True
    return False


def failing_node(ctx):
    """Which box of 'Where it broke' failed: source, workato or target.
    - ErroredApp that belongs to Workato itself (Python, variables, ...): workato.
    - ErroredApp that is the target or the source system: that one.
    - No ErroredApp, or a generic REST / HTTP connector (a call to some third-party system, never Workato's own): the
      evidence decides. The error text, the action or the step's title names the target (then target) or only the source
      (then source). Without a name, a REST step, a batch error or a kind of error only another system gives
      (rate limit, authentication, permission, 5xx, ...) points at the target when there is one.
    - Anything else stays workato."""
    app = norm_system(ctx.errored_app)
    if app in INTERNAL_APPS:
        return "workato"
    if app and app not in GENERIC_CALL_APPS:
        if ctx.target and (app in norm_system(ctx.target) or norm_system(ctx.target) in app):
            return "target"
        if ctx.source and (app in norm_system(ctx.source) or norm_system(ctx.source) in app):
            return "source"
        return "workato"
    if not app and ctx.category in INTERNAL_CATEGORIES:
        return "workato"
    step = ctx.recipe_info["step"] if ctx.recipe_info and ctx.recipe_info.get("step") else {}
    evidence = " ".join(x for x in (clip(ctx.error_plain, 4000), ctx.errored_action, step.get("title", ""),
                                    step.get("comment", ""),
                                    ctx.job_info["error_message"] if ctx.job_info else "") if x)
    if ctx.target and system_in_text(ctx.target, evidence):
        return "target"
    if ctx.source and system_in_text(ctx.source, evidence):
        return "source"
    if app in GENERIC_CALL_APPS or ctx.is_batch or ctx.category in REMOTE_CATEGORIES:
        if ctx.target_label:
            return "target"
        if app in GENERIC_CALL_APPS and ctx.source_label:
            return "source"
    return "workato"


def rule_headline(ctx):
    label, _ = category_info(ctx.category, ctx.rules)
    obj = (ctx.object_label + " ") if ctx.object_label else ""
    target = ctx.target_label or "the target system"
    if ctx.failed is not None and ctx.total:
        text = "{} of {} {}records failed to reach {}".format(fmt_int(ctx.failed), fmt_int(ctx.total), obj, target)
    elif ctx.rec["count"]:
        text = "{} {}{} failed to reach {}".format(fmt_int(ctx.rec["count"]), obj,
                                                    "record" if ctx.rec["count"] == 1 else "records", target)
    else:
        first_line = ctx.details["headline"] or "The recipe stopped with an error"
        sentence = re.split(r"(?<=[.!?])\s", first_line, maxsplit=1)[0]
        return clip(sentence, 140)
    if ctx.category not in ("unknown", "partial_batch"):
        text += " · " + label.lower()
    return text


def build_signals(ctx):
    cfg, out = ctx.cfg, []
    h, rec = ctx.history, ctx.rec
    shown = set(ctx.sections)

    def add(icon, html, tone="info"):
        out.append({"icon": icon, "html": html, "tone": tone})

    if ctx.escalation:
        add("⬆️", ctx.escalation, "bad")
    d, rep = ctx.decision, ctx.repeat
    who = DECISION_SOURCES.get(d["source"], "")
    why = esc(d["reason"]) if d["reason"] else ""
    if rep["enqueued"]:
        add("♻️", "<b>Auto-retry queued.</b> Workato is repeating master job {}{}. {}".format(
            mono(ctx.master), " as job " + mono(rep["job_id"]) if rep["job_id"] else "", why), "good")
    elif rep["attempted"]:
        add("❌", "<b>Auto-retry failed</b>: {}. Re-run the job by hand once the cause is fixed.".format(
            esc(rep["error"])), "bad")
    elif d["reprocessable"]:
        note = ""
        if rep["skipped"] and rep["skipped"] not in ("auto_reprocess is off", "not reprocessable"):
            note = " Not repeated automatically: {}.".format(esc(rep["skipped"]))
        add("♻️", "<b>Reprocessable</b> ({}{}): {}{}".format(
            who, ", " + d["confidence"] if d["confidence"] and d["source"] != "input" else "", why, note), "info")
    elif d["source"] not in NO_DECISION:
        add("✋", "<b>Fix before re-running</b> ({}): {}".format(who, why), "warn")
    if rec["duplicates"]:
        col = sorted(rec["duplicates"])[0]
        name = next((c["name"] for c in ctx.cols if c["i"] == col), "ID")
        dups = rec["duplicates"][col]
        text = "<b>{}</b> {} more than once in the failed records ({} rows).".format(
            plural(len(dups), esc(name) + " value"), "appears" if len(dups) == 1 else "appear",
            fmt_int(sum(dups.values())))
        if ctx.category == "duplicate":
            text += " If the source file repeats them too, that alone triggers a duplicate error in a bulk upsert."
        add("👯", text, "warn")
    if h:
        label, _ = category_info(ctx.category, ctx.rules)
        if "history" in shown:
            pass                              # the history section says it
        elif h["trend"] == "new":
            add("✨", "First time this kind of error ({}) has hit this recipe in {} days. Look at what changed: "
                "the data, a deployment, or the connected app.".format(esc(label.lower()), h["days"]), "info")
        elif h["trend"] == "returning":
            add("↩️", "Back after <b>{} days</b>: last seen {}.".format(h["gap"], short_day(h["last_seen"])), "warn")
        elif h["trend"] == "rising":
            add("📈", "<b>{} times in the last 7 days</b>, up from {} the week before.".format(
                h["week_total"], h["prev_week"]), "bad")
        else:
            add("🔁", "The <b>{}</b> time in {} days (first seen {}).".format(
                ordinal(h["occurrence"]), h["days"], short_day(h["first_seen"])), "warn")
        if h["reprocessed"] and "history" not in shown:
            add("🩹", "{} fixed by reprocessing (last on {}).".format(
                plural(h["reprocessed"], "earlier occurrence was", "earlier occurrences were"),
                short_day(h["last_reprocessed"])), "good")
        if h["failed_again"] and "history" not in shown:
            add("⚠️", "Reprocessing didn't help {} before. Fix the data before retrying.".format(
                plural(h["failed_again"], "time")), "warn")
        if h["hour_window"]:
            start = h["hour_window"][0]
            add("🕑", "Tends to happen between {} and {} {} ({}% of similar failures).".format(
                clock(datetime(2000, 1, 1, start)), clock(datetime(2000, 1, 1, (start + 2) % 24)),
                tz_label(ctx.now), int(round(h["hour_window"][1] * 100))), "info")
    if ctx.cross:
        names = ", ".join("{} ({})".format(esc(clip(n, 60)), c) for n, c in ctx.cross.most_common(3))
        more = len(ctx.cross) - 3
        systemic = ctx.category in SYSTEMIC
        add("🌐", "The same error hit <b>{}</b> in the last {} days: {}{}.{}".format(
            plural(len(ctx.cross), "other recipe"), cfg["cross_recipe_days"], names,
            " and {} more".format(more) if more > 0 else "",
            " Likely a shared cause (connection, limit or outage) rather than this recipe." if systemic else ""),
            "bad" if systemic else "warn")
    recipe = ctx.recipe_info
    if recipe:
        if recipe["running"] is False:
            add("⏹️", "The recipe is <b>stopped</b> right now{}.".format(
                ": " + esc(recipe["stop_cause"]) if recipe["stop_cause"] else ""), "bad")
        updated = recipe["updated_at"]
        if updated and timedelta(0) <= ctx.now - updated <= timedelta(hours=72):
            add("🛠️", "The recipe was changed <b>{}</b>{}. A new error right after a change is often caused by it.".format(
                rel_age(updated, ctx.now), " (version {})".format(recipe["version"]) if recipe["version"] else ""),
                "warn")
    jobs = ctx.jobs_info
    if jobs and jobs["jobs"]:
        done = jobs["counted"]
        if jobs["known"]:
            # The error handler makes Workato call a handled error a success, so the error log decides (mark_failed_runs).
            if jobs["errors"] >= 2 and done and jobs["errors"] / float(done) >= 0.2:
                add("📉", "<b>{} of the last {} runs</b> hit an error ({} besides this one). Workato counts those as "
                          "successful because the recipe's error handler catches them.".format(
                              jobs["errors"], done, jobs["others"]), "bad")
            elif done >= 5 and jobs["errors"] <= 1:
                add("🟢", "Otherwise healthy: {} of the last {} runs ran clean (no error logged).".format(
                    jobs["clean"], done), "good")
        elif jobs["fail"] >= 2 and done and jobs["fail"] / float(done) >= 0.2:
            add("📉", "<b>Workato shows {} of the last {} finished jobs</b> as failed.".format(jobs["fail"], done), "bad")
    if ctx.retry_count and ctx.retry_count >= 3:
        add("🔂", "Already retried {} before this alert.".format(plural(ctx.retry_count, "time")), "warn")
    job = ctx.job_info
    if job and job["slowest"] and ctx.category == "timeout":
        slow = job["slowest"]
        add("🐢", "Slowest step: line {} ({} › {}) took {}.".format(
            slow["number"], esc(app_label(slow["adapter"])), esc(slow["action"]), duration(slow["seconds"])), "warn")
    if ctx.is_repeated:
        add("🔔", "Repeated alert: this error was already reported for this job.", "info")
    return out[: cfg["max_signals"]]


def maybe_escalate(ctx):
    cfg, h = ctx.cfg, ctx.history
    if not cfg["auto_escalate"] or ctx.priority == "CRITICAL":
        return
    reasons = []
    if h and h["week_total"] >= cfg["escalate_after"]:
        reasons.append("{} times in 7 days".format(h["week_total"]))
    if ctx.cross and len(ctx.cross) >= 3 and ctx.category in SYSTEMIC:
        reasons.append("the same error in {} other recipes".format(len(ctx.cross)))
    if reasons:
        before = ctx.priority
        ctx.priority = PRIORITY_ORDER[min(3, PRIORITY_ORDER.index(before) + 1)]
        ctx.sev = severity_for(ctx.priority, ctx.extra)
        ctx.escalation = "Priority raised from {} to <b>{}</b>: {}.".format(
            SEVERITY[before]["label"], ctx.sev["label"], " and ".join(reasons))


TILE_LIMIT = 4


def build_tiles(ctx):
    tiles, sev = [], ctx.sev
    if ctx.total is not None:
        tiles.append({"label": "Records processed", "value": fmt_int(ctx.total), "sub": "in this run"})
    if ctx.failed is not None:
        tiles.append({"label": "Failed", "value": fmt_int(ctx.failed), "color": sev["color"],
                      "sub": "{} listed".format(plural(ctx.rec["count"], "row")) if ctx.rec["count"] else "records"})
    elif ctx.rec["count"]:
        tiles.append({"label": "Failed records", "value": fmt_int(ctx.rec["count"]), "color": sev["color"],
                      "sub": plural(max(1, ctx.rec["distinct_errors"]), "distinct error")})
    h = ctx.history
    # What tells the reader how this recipe is doing. Workato's own job status is no help (the error handler makes a
    # handled error a success), so: how often this alert's job was retried, how many recent runs logged an error, and
    # how often an automatic retry has worked before.
    retries = ctx.retry_count if ctx.retry_count is not None else (ctx.job_info or {}).get("retry_count")
    if retries is not None:
        tiles.append({"label": "Retries", "value": fmt_int(retries), "color": WARN if retries >= 3 else None,
                      "sub": "before this alert"})
    jobs = ctx.jobs_info
    if jobs and jobs["jobs"] and jobs["known"] and jobs["counted"]:
        others = jobs["others"]
        color = BAD if others / float(jobs["counted"]) >= 0.3 else (WARN if others else GOOD)
        only_this = jobs["errors"] == 1 and not others
        tiles.append({"label": "Runs with errors", "value": "{}/{}".format(jobs["errors"], jobs["counted"]),
                      "sub": "only this one" if only_this else "of the last {}".format(jobs["counted"]), "color": color})
    if h and h["reprocessed"] + h["failed_again"]:
        tried = h["reprocessed"] + h["failed_again"]
        pct = 100.0 * h["reprocessed"] / tried
        tiles.append({"label": "Retry success", "value": "{}%".format(int(round(pct))),
                      "sub": "{} of {} retried".format(h["reprocessed"], tried),
                      "color": GOOD if pct >= 80 else (WARN if pct >= 50 else BAD)})
    if h and "history" not in set(ctx.sections):
        if h["same"]:
            tiles.append({"label": "Seen before", "value": fmt_int(h["same"]),
                          "sub": "{} this week · {} days".format(h["week"], h["days"])})
        else:
            tiles.append({"label": "Seen before", "value": "New", "color": INFO,
                          "sub": "nothing similar in {} days".format(h["days"])})
    # the header already shows the success rate and how often this was seen, so those two give way
    if ctx.rate is not None:
        color = GOOD if ctx.rate >= 99 else (WARN if ctx.rate >= 90 else BAD)
        tiles.append({"label": "Success rate", "value": fmt_pct(ctx.rate, ctx.failed), "color": color,
                      "sub": "{} OK".format(fmt_int(ctx.total - ctx.failed))})
    if ctx.step and "flow" not in set(ctx.sections):          # "Where it broke" already names the app and the action
        tiles.append({"label": "Failed at", "value": "Step " + clip(ctx.step, 6),
                      "sub": " › ".join(x for x in (app_label(ctx.errored_app) if ctx.errored_app else "",
                                                     ctx.errored_action) if x) or "see details"})
    return tiles[:TILE_LIMIT]


# --------------------------------------------------------------------------- AI


def playbook_entry(ctx):
    base = dict(PLAYBOOK.get(ctx.category) or PLAYBOOK["unknown"])
    custom = (ctx.extra.get("playbook") or {}).get(ctx.category)
    if isinstance(custom, dict):
        for key in ("functional", "technical", "causes", "steps"):
            if custom.get(key):
                base[key] = custom[key]
    return base


def fill_values(ctx):
    return {"target": ctx.target_label or "the target system", "source": ctx.source_label or "the source",
            "object": ctx.object_label or "records", "app": ctx.app_label, "step": ctx.step or "?",
            "recipe": ctx.recipe_name}


def impact_sentence(ctx):
    obj = (ctx.object_label + " ") if ctx.object_label else ""
    target = ctx.target_label or "the target system"
    if ctx.failed is not None and ctx.total:
        return "{} of {} {}records didn't reach {}; the other {} went through.".format(
            fmt_int(ctx.failed), fmt_int(ctx.total), obj, target, fmt_int(ctx.total - ctx.failed))
    if ctx.rec["count"]:
        return "{} {}didn't reach {}.".format(plural(ctx.rec["count"], obj + "record"), "", target).replace("  ", " ")
    return ""


def playbook_story(ctx):
    entry, values = playbook_entry(ctx), fill_values(ctx)
    functional = fill(entry["functional"], values)
    functional = functional[:1].upper() + functional[1:]
    return {"source": "playbook", "headline": rule_headline(ctx), "functional": functional,
            "technical": fill(entry["technical"], values),
            "causes": [fill(c, values) for c in entry["causes"]][:3],
            "steps": [fill(s, values) for s in entry["steps"]][:4], "confidence": ""}


def ai_facts(ctx):
    r = redact if ctx.cfg["ai_redact"] else text_of
    label, _ = category_info(ctx.category, ctx.rules)
    facts = {
        "recipe": ctx.recipe_name, "environment": ctx.env["label"], "priority": ctx.sev["label"],
        "source": {"system": ctx.source_label, "object": ctx.source_obj},
        "target": {"system": ctx.target_label, "object": ctx.target_obj},
        "failed_step": {"line": ctx.step, "app": ctx.errored_app, "action": ctx.errored_action},
        "error_message": r(clip(ctx.error_plain, 2000)),
        "rule_based_category": label,
        "retry_count": ctx.retry_count,
    }
    if ctx.is_batch:
        facts["batch"] = {"total_records": ctx.total, "failed_records": ctx.failed,
                          "success_rate_percent": round(ctx.rate, 3) if ctx.rate is not None else None}
    if ctx.rec["count"]:
        err_col = ctx.rec["err_col"]
        samples = []
        for row in ctx.rows:
            message = row[err_col]["value"] if err_col else ""
            if message and r(clip(message, 240)) not in samples:
                samples.append(r(clip(message, 240)))
            if len(samples) >= 5:
                break
        facts["failed_rows"] = {"count": ctx.rec["count"], "error_codes": dict(ctx.rec["codes"].most_common(8)),
                                "distinct_errors": ctx.rec["distinct_errors"], "sample_errors": samples,
                                "ids_repeated_in_failed_rows": sum(len(d) for d in ctx.rec["duplicates"].values())}
    h = ctx.history
    if h:
        facts["history"] = {"window_days": h["days"], "failures_of_this_recipe": h["total"],
                            "same_type_failures": h["same"], "identical_message": h["exact"],
                            "same_type_last_7_days_including_now": h["week_total"],
                            "first_seen": h["first_seen"].isoformat() if h["first_seen"] else None,
                            "last_seen": h["last_seen"].isoformat() if h["last_seen"] else None,
                            "trend": h["trend"], "outcomes": dict(h["statuses"])}
    if ctx.cross:
        facts["same_error_in_other_recipes"] = [{"recipe": n, "count": c} for n, c in ctx.cross.most_common(5)]
    if ctx.job_info:
        j = ctx.job_info
        facts["job"] = {"error_type": j["error_type"], "failed_line": j["failed_line"],
                        "duration_seconds": j["duration"], "lines_run": j["lines"]}
    if ctx.recipe_info:
        rec = ctx.recipe_info
        facts["recipe_info"] = {"running": rec["running"], "version": rec["version"],
                                "hours_since_last_change": round((ctx.now - rec["updated_at"]).total_seconds() / 3600, 1)
                                if rec["updated_at"] else None,
                                "failing_step": rec["step"]}
    if ctx.jobs_info and ctx.jobs_info["jobs"]:
        facts["recent_jobs"] = {"checked": len(ctx.jobs_info["jobs"]), "failed": ctx.jobs_info["fail"]}
    entry = playbook_entry(ctx)
    facts["playbook_hints"] = {"causes": entry["causes"], "steps": entry["steps"]}
    facts["reprocess_context"] = {
        "this_run_is_already_a_repeat": bool(ctx.is_repeated or ctx.child_job_id or
                                             (ctx.job_info and ctx.job_info["is_repeat"])),
        "rule_based_answer": "yes" if ctx.category in TRANSIENT else "no",
        "frequency": ctx.frequency, "error_limit": ctx.error_limit,
    }
    file_text = text_of(ctx.inp.get("file_content")).strip()
    if file_text:   # Genie got the error file too; Azure gets the start of it
        facts["error_file_excerpt"] = r(clip(file_text, 1500))
    return facts


def parse_ai_json(content):
    text = text_of(content).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


def ai_story(ctx, deadline, warnings):
    """Azure's explanation, or None. A failed call (no answer, an HTTP error, a timeout, an answer that is not the JSON
    asked for, or anything raised while building the request) never stops the email: it is written to ctx.ai_error and to
    `warnings`, and explain() falls back to the built-in playbook. The email goes out either way."""
    def fail(text):
        ctx.ai_error = clip(text, 300)
        warnings.append(ctx.ai_error)
        return None
    try:
        return ai_story_call(ctx, deadline, fail)
    except Exception as exc:  # noqa: BLE001 - Azure must never be the reason an alert is not sent
        return fail("azure: {}: {}".format(type(exc).__name__, clip(str(exc), 200)))


def ai_story_call(ctx, deadline, fail):
    cfg = ctx.cfg
    left = remaining(deadline)
    if left < 4:
        return fail("azure skipped: time budget used up")
    system = AI_SYSTEM
    if cfg["ai_instructions"]:
        system += "\nTeam notes (follow them): " + clip(cfg["ai_instructions"], 1500)
    payload = {"messages": [{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(ai_facts(ctx), default=str, ensure_ascii=False)}],
               "temperature": cfg["ai_temperature"], "max_tokens": cfg["ai_max_tokens"],
               "response_format": {"type": "json_object"}}
    headers = {"api-key": cfg["azure_api_key"], "Content-Type": "application/json"}
    body, err = http_json("POST", cfg["azure_url"], headers, payload, max(3, min(30, left)))
    if err:
        return fail("azure: " + err)
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return fail("azure: unexpected response shape")
    data = parse_ai_json(content)
    if not data:
        return fail("azure: the answer was not JSON")

    def items(value, limit):
        if isinstance(value, str):
            value = [value]
        return [clip(text_of(v).strip(), 240) for v in (value or []) if text_of(v).strip()][:limit]
    story = {"source": "ai", "headline": clip(text_of(data.get("headline")).strip(), 160),
             "functional": clip(text_of(data.get("functional_summary")).strip(), 700),
             "technical": clip(text_of(data.get("technical_summary")).strip(), 800),
             "causes": items(data.get("likely_causes"), 3), "steps": items(data.get("next_steps"), 4),
             "confidence": text_of(data.get("confidence")).strip().lower()}
    if story["confidence"] not in ("low", "medium", "high"):
        story["confidence"] = ""
    answer = text_of(data.get("reprocessable")).strip().lower()
    if answer in ("yes", "true", "y", "no", "false", "n"):
        story["reprocess"] = {"reprocessable": answer in ("yes", "true", "y"),
                              "reason": clip(text_of(data.get("reprocess_reason")).strip(), 300)}
    return story


def explain(ctx, deadline, warnings):
    base = playbook_story(ctx)
    cfg = ctx.cfg
    if not cfg["ai"] or not cfg["azure_api_key"]:
        return base
    story = ai_story(ctx, deadline, warnings)
    if not story:
        return base
    for key in ("headline", "functional", "technical", "causes", "steps"):
        if not story.get(key):
            story[key] = base[key]
    return story


# ------------------------------------------------- the old recipe's logic, in Python
#
# Notify Via Email - Callable v2 (recipe 44908641) did this after its file steps:
#   1. reprocess blank -> ask Workato Genie "reprocessable? + explanation"   (now: Azure)
#   2. frequency or error_limit present, or reprocess true, or reprocessable
#          -> upsert the error log row with Status "Created" and send NO email
#      else -> build and send the email, upsert the row with Status "Notified"
#   3. Status is "Failed Again" when is_Repeated is true or the job URL has child_job_id
#   4. Master Job ID: calling_master_job_id, else the job API's master_job_id, else the
#      job handle in the job URL
#   5. a reprocess branch after the email, switched off (skip), that only fetched the
#      master job id. This step can now really repeat the job (auto_reprocess).


def rules_decision(ctx):
    label, _ = category_info(ctx.category, ctx.rules)
    if ctx.category in TRANSIENT:
        reason = "{} errors are usually temporary, so running the same job again is likely to work.".format(label)
        return {"reprocessable": True, "source": "rules", "reason": reason, "confidence": "medium"}
    if ctx.category == "unknown":
        reason = "The error didn't match a known temporary cause, so it isn't retried automatically."
    else:
        reason = "{} errors need a fix (data, mapping, access or configuration) before a re-run can work.".format(label)
    return {"reprocessable": False, "source": "rules", "reason": reason, "confidence": "medium"}


NO_DECISION = ("", "off", "none")          # decision sources that are not an answer to "would a re-run help?"


def decide_reprocess(ctx, warnings):
    """Would a re-run help? Only Azure says. auto_reprocess off: nothing is retried and nobody is asked. On: Azure's
    answer (reprocessable yes or no, with its confidence) is the answer; no answer (no key, AI off, the call failed, an
    answer that is neither yes nor no) means No, so the error is emailed. reprocess_policy rules / both are advanced
    alternatives: the rules alone, or Azure and the rules must agree."""
    cfg = ctx.cfg
    if not cfg["auto_reprocess"]:
        return {"reprocessable": False, "source": "off", "reason": "", "confidence": ""}
    rules = rules_decision(ctx)
    policy = cfg["reprocess_policy"].lower()
    if policy == "rules":
        return rules
    ai = ctx.story.get("reprocess") if ctx.story.get("source") == "ai" else None
    if ai is None:
        if not (cfg["ai"] and cfg["azure_api_key"]):
            why = "Azure is not set up (no key, or AI is off), so nothing is retried automatically."
        else:
            why = "Azure gave no answer, so nothing is retried automatically."
            warnings.append("reprocess decision: Azure gave no yes or no, so the job is not retried")
        return {"reprocessable": False, "source": "none", "reason": why, "confidence": ""}
    decision = {"reprocessable": ai["reprocessable"], "source": "ai",
                "reason": ai["reason"] or rules["reason"], "confidence": ctx.story.get("confidence", "")}
    if policy in ("both", "ai_and_rules", "ai+rules"):
        decision["source"] = "ai+rules"
        if ai["reprocessable"] and not rules["reprocessable"]:
            decision.update({"reprocessable": False,
                             "reason": "The AI said yes, but the rules don't treat this error as temporary. " + rules["reason"]})
    return decision


def resolve_master(ctx):
    """The old recipe's Master Job ID formula."""
    if ctx.master_job_id:
        return ctx.master_job_id
    if ctx.job_info and ctx.job_info["master_job_id"]:
        return ctx.job_info["master_job_id"]
    return ctx.url_job_handle


def prior_repeats(ctx):
    """How often this master job was already reprocessed, from the error log rows."""
    count = 0
    for row in normalize_history(ctx.history_rows, ctx) if ctx.history_rows else []:
        if ctx.master and row.get("master_job_id") == ctx.master:
            count = max(count, row["reprocess_count"] or 0,
                        1 if row["status"].lower() in ("reprocessed", "failed again") else 0)
    return count


def repeat_blocker(ctx):
    """Why the job must not be repeated now, or '' when it may be."""
    cfg, d = ctx.cfg, ctx.decision
    if not cfg["auto_reprocess"]:
        return "auto_reprocess is off"
    if not d["reprocessable"]:
        return "not reprocessable"
    if d["source"] in ("ai", "ai+rules") and CONFIDENCE.get(d["confidence"], 0) < \
            CONFIDENCE.get(cfg["reprocess_min_confidence"].lower(), 2):
        return "AI confidence ({}) is below reprocess_min_confidence".format(d["confidence"] or "none")
    if ctx.is_repeated or ctx.child_job_id or (ctx.job_info and ctx.job_info["is_repeat"]):
        return "this run is already a repeat, so it isn't repeated again"
    if cfg["max_auto_repeats"] < 1:
        return "max_auto_repeats is 0"
    done = prior_repeats(ctx)
    if done >= cfg["max_auto_repeats"]:
        return "already repeated {} before (max_auto_repeats is {})".format(plural(done, "time"), cfg["max_auto_repeats"])
    if not cfg["workato_api_token"]:
        return "no workato_api_token"
    if not ctx.recipe_id or not ctx.master:
        return "no recipe id or master job id"
    return ""


def repeat_job(ctx, deadline):
    """POST /api/recipes/:recipe_id/repeat_jobs with the master job id."""
    cfg = ctx.cfg
    out = {"attempted": True, "enqueued": False, "job_id": "", "error": "", "skipped": ""}
    try:
        timeout = call_timeout(cfg, deadline)
    except FetchError as exc:
        out.update({"attempted": False, "skipped": str(exc)})
        return out
    url = "{}/recipes/{}/repeat_jobs".format(cfg["workato_api_base"].rstrip("/"), urllib_parse.quote(ctx.recipe_id))
    headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Content-Type": "application/json",
               "Accept": "application/json"}
    body, err = http_json("POST", url, headers, {"job_ids": [ctx.master]}, timeout)
    if err:
        out["error"] = err
        return out
    body = body if isinstance(body, dict) else {}
    results = body.get("results") if isinstance(body.get("results"), list) else []
    first_result = results[0] if results and isinstance(results[0], dict) else {}
    job = first_result.get("job") if isinstance(first_result.get("job"), dict) else {}
    summary = body.get("summary") if isinstance(body.get("summary"), dict) else {}
    status = text_of(first_result.get("status")).lower()
    out["job_id"] = text_of(job.get("id") or job.get("handle"))
    out["enqueued"] = (to_int(summary.get("total_enqueued"), 0) or 0) > 0 or status in (
        "enqueued", "queued", "success", "succeeded", "ok", "repeated")
    if not out["enqueued"]:
        out["error"] = clip(text_of(first_result.get("error") or status or "Workato did not enqueue the repeat"), 300)
    return out


def is_deferred(ctx):
    """The caller set frequency and/or error_limit. It does not want an email for every error: the error is logged,
    and the daily summary recipe emails once every `frequency` days or when more than `error_limit` have piled up
    (that rule lives in 'Email Notification Summary- SCH', not in this step)."""
    return ctx.frequency is not None or ctx.error_limit is not None


def route(ctx):
    """Notify now, or only log the error (the old recipe's step 12).
    A retryable error is only logged while it is being taken care of: flagged for the scheduled repeater, or rerun by this
    step (auto_reprocess). It is emailed as soon as nobody is taking care of it: auto_reprocess is on but the step did not
    rerun it (a guard stopped it, or the repeat call failed), or this run is already a retry that failed again."""
    cfg = ctx.cfg
    if is_deferred(ctx):        # never an email from here, whatever the optional switches below say
        return "log_only", False
    log_only = ctx.decision["reprocessable"]
    send = not log_only
    if ctx.decision["reprocessable"] and cfg["email_when_reprocessable"]:
        send = True
    if ctx.repeat["attempted"] and not ctx.repeat["enqueued"] and cfg["notify_on_repeat_failure"]:
        send = True
    if cfg["auto_reprocess"] and ctx.decision["reprocessable"] and not ctx.repeat["enqueued"]:
        send = True                                     # the step was to rerun it and did not: a person has to look
    if ctx.is_repeated or ctx.child_job_id:
        send = True                                     # already a retry, and it failed again
    return ("notify" if send else "log_only"), send


def build_table_row(ctx):
    """The error log row, exactly as the old recipe's upserts filled it."""
    repeated = ctx.is_repeated or bool(ctx.child_job_id)
    if repeated:
        status = "Failed Again"
    elif ctx.repeat["enqueued"]:
        status = "Reprocessed"
    else:
        status = "Notified" if ctx.send_email else "Created"
    if repeated:
        count = None                                   # skip: keep the count already stored
    elif ctx.repeat["enqueued"]:
        count = prior_repeats(ctx) + 1
    else:
        count = 0
    flag = False if ctx.is_repeated else bool(ctx.decision["reprocessable"])
    expires = None
    if ctx.error_file_expires_in:
        expires = int(ctx.now.timestamp()) + ctx.error_file_expires_in
    inp = ctx.inp
    return {
        "job_url": text_of(inp.get("job_url")), "date": ctx.today.isoformat(),
        "error_message": ctx.error_raw, "frequency": ctx.frequency, "recipe_name": text_of(inp.get("recipe_name")),
        "error_limit": ctx.error_limit, "error_timestamp": ctx.now.isoformat(),
        "email": text_of(inp.get("to_email_address")), "source_system": ctx.source, "target_system": ctx.target,
        "source_object": ctx.source_obj, "target_object": ctx.target_obj, "status": status,
        "recipe_id": ctx.recipe_id, "job_id": ctx.job_handle, "master_job_id": ctx.master,
        "reprocess_count": count, "reprocess_flag": flag, "error_file_path": ctx.error_file_path or None,
        "error_file_sharable_url": ctx.error_file_url or None, "sharable_link_expires_on": expires,
    }


# ------------------------------------------------------------- writing the error log row


def decode_records(body):
    """[(record_id, fields)] from a data table answer. The query endpoint answers with arrays (the metafields, then
    the fields, both named in `schema`); create and update answer with one object that has a record_id."""
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
            out.append((text_of(first(item, "record_id", "$record_id", "id")).strip(),
                        doc if isinstance(doc, dict) else {}))
        elif isinstance(item, list) and len(item) == 2 and all(isinstance(g, list) for g in item):
            metas, values = item
            rid = next((text_of(v) for n, v in zip(meta_names, metas) if n == "$record_id"), "")
            out.append((rid.strip() or (text_of(metas[0]).strip() if metas else ""), dict(zip(field_names, values))))
    return out


def row_document(cfg, row):
    """The row in the data table's own column names. A number, flag or date that is empty is left out, so an update
    keeps what is stored (the old recipe's `skip` on Reprocess Count)."""
    doc = {}
    for key, default in TABLE_ROW_KEYS:
        value = row.get(key)
        if value is not None:
            doc[table_column(cfg, key, default)] = value
    return doc


def table_call(cfg, method, path, payload, deadline):
    """One call to the data table API. Tried twice when it was refused for being busy (429, 503), and a PUT (which is
    safe to repeat) also after a timeout or a 5xx. A POST that may have been done is never repeated: no double rows."""
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


def find_record(cfg, master, deadline):
    """(record_id, fields) of the row for this master job, or None. Master Job ID is the key of the old recipe's upserts:
    a job that is run again and fails again updates its row instead of adding one. Newest first if there are two."""
    payload = {"where": {table_column(cfg, "master_job_id", "Master Job ID"): {"$eq": master}}, "limit": 1,
               "order": {"by": "$created_at", "direction": "desc"}}
    try:
        body = table_call(cfg, "POST", "query", payload, deadline)
    except FetchError as exc:
        if not re.search(r" 4(00|22): ", str(exc)):
            raise
        payload.pop("order")                                  # the order was refused: ask again without it
        body = table_call(cfg, "POST", "query", payload, deadline)
    records = decode_records(body)
    return records[0] if records else None


def log_row(ctx, deadline):
    """Upsert the error log row into the data table, the way the old recipe's two upserts did (key: Master Job ID).
    -> {"action": "inserted" | "updated", "record_id": str, "note": str}. Raises FetchError when the table refuses."""
    cfg, row = ctx.cfg, ctx.table_row
    document = {"document": row_document(cfg, row)}
    master = text_of(row.get("master_job_id")).strip()
    found = find_record(cfg, master, deadline) if master else None
    note = ""
    if found and found[0]:
        body = table_call(cfg, "PUT", "records/" + urllib_parse.quote(found[0], safe=""), document, deadline)
        action, rid = "updated", found[0]
    else:
        if found:
            note = "the row for this master job was found without a record id, so a new row was added"
        body = table_call(cfg, "POST", "records", document, deadline)
        action, rid = "inserted", ""
    saved = decode_records(body)
    return {"action": action, "record_id": (saved[0][0] if saved else "") or rid, "note": note}


def write_row(ctx, result, warnings, deadline):
    """Log the row and say what happened in the result. Never raises (the alert must still go out) and never runs
    twice for one call, so it can be called again from the fallback path."""
    if ctx.row_tried:
        return
    ctx.row_tried = True
    cfg = ctx.cfg
    if not cfg["log_row"]:
        return
    if not cfg["workato_api_token"]:
        warnings.append("row not logged: no workato_api_token")
        return
    if cfg["history_rows_json"]:
        warnings.append("row not logged: history_rows_json is set, so this is a test run")
        return
    try:
        done = log_row(ctx, deadline)
    except Exception as exc:  # noqa: BLE001
        result.update({"row_action": "failed", "row_error": clip(str(exc), 300)})
        warnings.append("row not logged: " + clip(str(exc), 240))
        return
    result.update({"row_logged": True, "row_action": done["action"], "row_record_id": done["record_id"]})
    if done["note"]:
        warnings.append(done["note"])


# -------------------------------------------------------------------- rendering

CSS = """
body{margin:0;padding:0;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}
table{border-collapse:collapse;mso-table-lspace:0;mso-table-rspace:0}
img{border:0;outline:none;text-decoration:none}
a{color:inherit}
@media only screen and (max-width:640px){
 .px{padding-left:18px!important;padding-right:18px!important}
 .outer{padding:12px 4px!important}
 .rc{padding:8px 6px!important;font-size:12px!important}
 .stack{display:block!important;width:100%!important;box-sizing:border-box}
 .flowcell{font-size:11px!important;padding:8px 4px!important}
 .hide-sm{display:none!important}
 .dcol{padding:0 0 16px!important}
 .h1{font-size:20px!important}
}
"""


# Hover effects. They live in the email's own <style>, so the email needs no external stylesheet (the old health
# check mail got its hover from w3.css; this is the same idea built in).
# What a mail client shows on hover is a change of colour or opacity: a row or cell that changes background, an
# element that dims (the way w3.css writes w3-hover-pale-green and w3-hover-opacity). A shadow on its own is not
# reliably drawn, so every hover class below changes a background or an opacity, and the shadow is only a bonus.
# Plain `:hover` rules, one selector per rule and no media query, because a mail client may drop a whole rule or
# block it does not understand. Only the motion (the lift and the easing) is in a media block for devices that hover.
# The big white header area does not react: only the small pills in it do. hv-err: the error box deepens in its own severity colour. hv-card: a panel or tile
# turns white with a blue edge (its rows then stand out). hv-lift: a white card tints. hv-cell: glows. hv-row / hv-trow:
# the row and its cells are tinted (hv-trow also gets a blue bar). hv-pill: every pill turns a deeper shade of its own
# colour (the .hvp-<background>-<text> rules are written for the pills in this email by pill_hover_css(); a pill
# without one turns the row colour). hv-btn deepens. hv-bar: a chart bar or
# a job square dims. hv-link: underlines. hv-banner: the alert strip deepens.
# __ERR_BG__, __ERR_LINE__ and __PILLS__ are filled in by hover_css() (they depend on the severity and the pills used).
HOVER_CSS = """
.hv-err:hover{background:__ERR_BG__!important;border-color:__ERR_LINE__!important;box-shadow:0 12px 28px rgba(15,23,42,.11)!important}
.hv-card:hover{background:#FFFFFF!important;border-color:#BFD3F7!important;box-shadow:0 12px 28px rgba(15,23,42,.11),0 2px 6px rgba(15,23,42,.06)!important}
.hv-lift:hover{background:#EEF4FF!important;box-shadow:0 12px 28px rgba(15,23,42,.11),0 2px 6px rgba(15,23,42,.06)!important}
.hv-cell:hover{box-shadow:0 8px 20px rgba(15,23,42,.12)!important;background-color:#FFFFFF!important}
.hv-row:hover{background:#EEF4FF!important}
.hv-row:hover td{background-color:#EEF4FF!important}
.hv-trow:hover{background:#EEF4FF!important}
.hv-trow:hover td{background-color:#EEF4FF!important}
.hv-trow:hover td:first-child{box-shadow:inset 3px 0 0 #0056D2!important}
.hv-pill:hover{background:#EEF4FF!important;border-color:#BFD3F7!important;box-shadow:0 5px 12px rgba(15,23,42,.14)!important}
__PILLS__
.hv-btn:hover{background:#E1ECFF!important;border-color:#B5CCF5!important;box-shadow:0 8px 18px rgba(0,86,210,.18)!important}
.hv-link:hover{text-decoration:underline!important}
.hv-bar:hover{opacity:.65!important}
.hv-banner:hover{background:#FEE2E2!important}
@media (hover:hover){
 .hv-err{transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s ease,background-color .22s ease,border-color .22s ease}
 .hv-err:hover{transform:translateY(-2px)}
 .hv-card{transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s ease,border-color .22s ease,background-color .22s ease}
 .hv-card:hover{transform:translateY(-2px)}
 .hv-lift{transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s ease,background-color .22s ease}
 .hv-lift:hover{transform:translateY(-2px)}
 .hv-cell{transition:box-shadow .22s ease,background-color .22s ease}
 .hv-row{transition:background-color .15s ease}
 .hv-trow{transition:background-color .15s ease}
 .hv-pill{transition:transform .18s ease,background-color .18s ease,border-color .18s ease,box-shadow .18s ease}
 .hv-pill:hover{transform:translateY(-1px)}
 .hv-btn{transition:transform .18s ease,box-shadow .18s ease,background-color .18s ease,border-color .18s ease}
 .hv-btn:hover{transform:translateY(-1px)}
 .hv-bar{transition:opacity .15s ease}
 .hv-banner{transition:background-color .2s ease}
}
@media (prefers-reduced-motion:reduce){
 .hv-err{transition:none!important}
 .hv-card{transition:none!important}
 .hv-lift{transition:none!important}
 .hv-pill{transition:none!important}
 .hv-btn{transition:none!important}
}
"""


def hex6(value):
    """'#abc' or 'ABCDEF' as 'AABBCC' (no #, upper case); '' when it is not a hex colour (a name, say)."""
    text = text_of(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return text.upper() if re.match(r"^[0-9A-Fa-f]{6}$", text) else ""


def mix_color(a, b, share):
    """Colour a moved `share` (0..1) of the way to colour b, as #RRGGBB. A colour that is not a hex code (a name) can't
    be blended, so a comes back unchanged."""
    one, two = hex6(a), hex6(b)
    if not one or not two:
        return a
    one, two = [int(one[i:i + 2], 16) for i in (0, 2, 4)], [int(two[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join("{:02X}".format(int(round(x + (y - x) * share))) for x, y in zip(one, two))


def pill_hover_css(body):
    """One hover rule for each kind of pill in `body`: the pill turns a deeper shade of its own colour (its background
    moved towards its text colour) with a matching edge, so a red pill stays red and a grey one stays grey."""
    rules = []
    for bg, fg in sorted(set(re.findall(r"hvp-([0-9A-F]{6})-([0-9A-F]{6})", body))):
        rules.append(".hvp-{b}-{f}:hover{{background:{bg}!important;border-color:{bd}!important}}".format(
            b=bg, f=fg, bg=mix_color("#" + bg, "#" + fg, 0.14), bd=mix_color("#" + bg, "#" + fg, 0.45)))
    return "\n".join(rules)


def hover_css(cfg, sev, pills=""):
    """The hover rules for this email: the row colour from hover_row_color, the error box in its severity colour and one
    rule for each kind of pill (pills: what pill_hover_css() made for this email)."""
    row = cfg["hover_row_color"]
    return (HOVER_CSS.replace("#EEF4FF", row)
            .replace("__ERR_BG__", mix_color(sev["soft"], sev["line"], 0.45))
            .replace("__ERR_LINE__", mix_color(sev["line"], sev["color"], 0.5))
            .replace("__PILLS__", pills))


def rich(text):
    """Escaped text with `code` and **bold** turned into tags."""
    out = esc(text)
    out = re.sub(r"`([^`]{1,120})`", lambda m: '<code style="font-family:{};font-size:12px;background:{};'
                 'border:1px solid {};border-radius:5px;padding:1px 5px;color:{}">{}</code>'.format(
                     MONO, PANEL, LINE, INK, m.group(1)), out)
    return re.sub(r"\*\*([^*]{1,200})\*\*", r"<b>\1</b>", out)


def pill(html, fg, bg, border=None, title=""):
    one, two = hex6(bg), hex6(fg)
    tone = " hvp-{}-{}".format(one, two) if one and two else ""      # its own hover colour, see pill_hover_css()
    return ('<span class="hv-pill{tone}"{title} style="display:inline-block;margin:0 4px 6px 0;padding:4px 8px;border-radius:999px;'
            'background:{bg};color:{fg};border:1px solid {bd};font:600 12px/1.45 {font};white-space:nowrap">'
            '{html}</span>').format(tone=tone, title=' title="{}"'.format(esc(title)) if title else "", bg=bg, fg=fg,
                                    bd=border or bg, font=FONT, html=html)


def chip(text, fg=INK, bg=PANEL, border=LINE):
    return ('<span style="display:inline-block;margin:0 6px 6px 0;padding:2px 8px;border-radius:6px;'
            'background:{};color:{};border:1px solid {};font:600 11px/1.6 {};white-space:nowrap">{}</span>'
            ).format(bg, fg, border, MONO, text)


def heading(ctx, key, right=""):
    title = (ctx.extra.get("titles") or {}).get(key, TITLES.get(key, ""))
    if not title:
        return ""
    icon = ""
    left = ('<td style="font:800 12px/1.4 {};letter-spacing:.09em;text-transform:uppercase;color:{}">'
            '{}{}</td>').format(FONT, MUTED, (icon + "&nbsp; ") if icon else "", esc(title))
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:0 0 12px"><tr>{}<td align="right" style="font:12px/1.4 {};color:{}">{}</td>'
            '</tr></table>').format(left, FONT, MUTED, right)


def section(body, top=6, bottom=24):
    if not body:
        return ""
    return '<tr><td class="px" style="padding:{}px 32px {}px">{}</td></tr>'.format(top, bottom, body)


def button(label, url, bg, fg, border):
    """A light button. The fill, the border and the rounding are all on the link itself: a border on a table cell
    around it shows as a square outline in Gmail."""
    return ('<a class="hv-btn" href="{url}" target="_blank" style="display:inline-block;margin:0 8px 8px 0;padding:9px 16px;'
            'background:{bg};border:1px solid {bd};border-radius:8px;font:600 13px/1.2 {font};color:{fg};'
            'text-decoration:none">{label}</a>').format(url=esc(url), bg=bg, bd=border, font=FONT, fg=fg, label=label)


def kv_rows(pairs, label_width=150, gap=10):
    """label | value rows. The label column is only as wide as its longest label (width 1% and no wrapping make the
    table shrink it), then `gap` px, then the value, so the value sits next to its label. A very long label (over 26
    characters) falls back to a fixed column of label_width px that wraps."""
    pairs = [(label, html) for label, html in pairs if html not in (None, "")]
    if not pairs:
        return ""
    fit = max(len(text_of(label)) for label, _ in pairs) <= 26
    rows = []
    for label, value_html in pairs:
        if fit:
            cell = ('<td valign="top" width="1%" style="width:1%;padding:6px {g}px 6px 0;white-space:nowrap;font:600 13px/1.5 {f};'
                    'color:{m}">{l}</td>')
        else:
            cell = ('<td valign="top" width="{w}" style="width:{w}px;padding:6px {g}px 6px 0;font:600 13px/1.5 {f};'
                    'color:{m}">{l}</td>')
        rows.append(('<tr class="hv-row">' + cell + '<td valign="top" style="padding:6px 0;font:13px/1.5 {f};color:{i};'
                     'word-break:break-word">{v}</td></tr>').format(w=label_width, g=gap, f=FONT, m=MUTED, l=esc(label),
                                                                    i=INK, v=value_html))
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{}</table>'.format(
        "".join(rows))


def mono(text):
    return '<span style="font-family:{};font-size:12px">{}</span>'.format(MONO, esc(text))


def link(label, url):
    url = safe_url(url)
    if not url:
        return esc(label)
    return '<a class="hv-link" href="{}" target="_blank" style="color:{};text-decoration:none;font-weight:600">{}</a>'.format(
        esc(url), "#0056D2", esc(label))


def panel(body):
    """A light, subtle background that sets one section apart from the next."""
    return ('<div class="hv-card" style="background:{};border:1px solid {};border-radius:12px;padding:14px 16px">{}</div>'
            .format(SOFT, LINE, body))


def error_banner(ctx):
    """A red strip at the very top of the email: a cross in a red circle and "Error alert", so it reads as an error before
    anything else is read. Switched by error_banner."""
    return ('<tr><td style="padding:0"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'bgcolor="#FEF2F2" style="background:#FEF2F2;border-bottom:1px solid #FECACA"><tr>'
            '<td class="px hv-banner" bgcolor="#FEF2F2" style="padding:11px 32px;background:#FEF2F2">'
            '<span style="display:inline-block;width:22px;height:22px;border-radius:11px;background:#DC2626;color:#FFFFFF;'
            'font:800 13px/22px {f};text-align:center;vertical-align:middle">&#10005;</span>'
            '<span style="display:inline-block;vertical-align:middle;margin-left:10px;font:800 13px/1.3 {f};letter-spacing:.12em;'
            'text-transform:uppercase;color:#991B1B">Error alert</span>'
            '<span class="hide-sm" style="display:inline-block;vertical-align:middle;margin-left:10px;font:500 13px/1.3 {f};'
            'color:#991B1B">A recipe run failed and needs attention</span>'
            '</td></tr></table></td></tr>').format(f=FONT)


RETRY_TONES = {"will": (GOOD, GOOD_SOFT, "#BBF7D0"), "failed": (BAD, BAD_SOFT, "#FECACA"),
               "no": (BAD, BAD_SOFT, "#FECACA")}


def retry_status(ctx):
    """Will this job be retried? -> (state, icon, headline, detail); state is will | failed | no.
    Shown as a small pill next to the priority (retry_pill) and in the technical details."""
    cfg, d, rep = ctx.cfg, ctx.decision, ctx.repeat
    if rep["enqueued"]:
        return ("will", "♻️", "Will be auto retried",
                "A retry was queued automatically{}.".format(" (job {})".format(rep["job_id"]) if rep["job_id"] else ""))
    if rep["attempted"]:
        return ("failed", "❌", "Auto retry failed",
                "{} It needs a person.".format(clip(plain(rep["error"]) or "The Workato API refused the repeat.", 160)))
    if ctx.is_repeated or ctx.child_job_id or (ctx.job_info and ctx.job_info["is_repeat"]):
        return ("no", "🔁", "Retry failed again",
                "This run was already a retry, so it will not be retried again. It needs a person.")
    if d["reprocessable"]:                                         # retryable, and a guard stopped the retry
        why = rep["skipped"] or "the retry was not started"
        if "_" not in why.split(" ", 1)[0]:                        # not for a setting name such as max_auto_repeats
            why = why[:1].upper() + why[1:]
        return ("no", "⛔", "Will not auto retry", why + ".")
    if d["source"] == "off":
        return ("no", "⛔", "Will not auto retry", "Auto retry is switched off (auto_reprocess = no). This needs a person.")
    if d["source"] == "none":
        return ("no", "⛔", "Will not auto retry", d["reason"] + " This needs a person.")
    reason = clip(plain(d["reason"]), 200)
    return ("no", "⛔", "Will not auto retry", "Needs a fix. {}".format(reason or "A re-run would fail the same way."))


def retry_pill(ctx):
    """The retry verdict as a small pill next to the priority: green = will be auto retried, red = will not auto retry.
    Why is in its hover text and in the technical details."""
    state, icon, head, detail = retry_status(ctx)
    fg, bg, line = RETRY_TONES[state]
    return pill("{} {}".format(icon, esc(head)), fg, bg, line, title=detail)


def sec_hero(ctx):
    sev, env, cfg = ctx.sev, ctx.env, ctx.cfg
    banner_row = error_banner(ctx) if cfg["error_banner"] else ""
    label, icon = category_info(ctx.category, ctx.rules)
    if cfg["logo_url"] and safe_url(cfg["logo_url"]):
        logo = '<img src="{}" alt="Coursera" height="30" style="height:30px;width:auto;display:block;border:0">'.format(
            esc(cfg["logo_url"]))
    else:
        logo = '<span style="font:800 22px/1 {};color:{};letter-spacing:-.02em">coursera</span>'.format(
            FONT, cfg["brand_color"])
    right = ""
    if env["label"]:
        right += pill(esc(env["label"].upper()), env["chip_text"], env["chip"])
    # the error reference (#signature) is not in the header: it is in the footer and in the technical details
    new_layout = cfg["hero_layout"] != "classic"
    if new_layout:
        # The row at the top: priority first (soft tint, coloured dot), then the category in a neutral pill so the two
        # do not compete, then the facts below. Every pill shows here even when its section is also in the email.
        pills = [
            pill('<span style="color:{c};font-size:14px;line-height:1">&#9679;</span>&nbsp;<b>{sevl} priority</b>'.format(
                c=sev["color"], sevl=esc(sev["label"])), sev["ink"], sev["soft"], sev["line"]),
            retry_pill(ctx),
            pill("{} {}".format(icon, esc(label)), TEXT, PANEL, LINE)]
    else:
        pills = [pill("{} {}".format(icon, esc(label)), sev["ink"], sev["soft"], sev["line"])]
    h = ctx.history
    # classic keeps the "said once" rule: a pill only when its own section is not in the email
    shown = set() if new_layout else set(ctx.sections)
    if h and "history" not in shown:
        if h["week_total"] >= 2:
            pills.append(pill("🔁 {}× in 7 days".format(h["week_total"]), BAD, BAD_SOFT, "#FECACA"))
        elif h["same"]:
            pills.append(pill("🔁 {} in {} days".format(ordinal(h["occurrence"]), h["days"]), WARN, WARN_SOFT, "#FDE68A"))
        else:
            pills.append(pill("✨ First in {} days".format(h["days"]), INFO, INFO_SOFT, "#BFDBFE"))
    if ctx.rate is not None:
        if "kpis" not in shown:
            pills.append(pill("📦 {} succeeded".format(fmt_pct(ctx.rate, ctx.failed)), GOOD, GOOD_SOFT, "#BBF7D0"))
    elif ctx.rec["count"] and "records" not in shown:
        pills.append(pill("📦 {}".format(plural(ctx.rec["count"], "failed record")), TEXT, PANEL, LINE))
    if ctx.cross and "signals" not in shown:
        pills.append(pill("🌐 +{} other {}".format(len(ctx.cross), "recipe" if len(ctx.cross) == 1 else "recipes"),
                          WARN, WARN_SOFT, "#FDE68A"))
    if new_layout or "signals" in shown:
        pass                                  # the new header has the retry pill next to the priority
    elif ctx.repeat["enqueued"]:
        pills.append(pill("♻️ Retry queued", GOOD, GOOD_SOFT, "#BBF7D0"))
    elif ctx.repeat["attempted"]:
        pills.append(pill("❌ Retry failed", BAD, BAD_SOFT, "#FECACA"))
    elif ctx.decision["reprocessable"]:
        pills.append(pill("♻️ Reprocessable", INFO, INFO_SOFT, "#BFDBFE"))
    elif ctx.decision["source"] not in NO_DECISION:
        pills.append(pill("✋ Needs a fix", WARN, WARN_SOFT, "#FDE68A"))
    if "details" not in shown:
        pills.append(pill(esc(pill_when(ctx.now) if not cfg["error_time"] else cfg["error_time"]),
                          TEXT, PANEL, LINE))              # no clock emoji: the row of pills has to fit one line
    headline = plain(ctx.story["headline"])
    repeats_error = "error" in shown and headline.rstrip("…").strip().lower() in ctx.error_plain.lower()
    headline_div = "" if repeats_error else (        # a one-line error is already in the error box right below
        '<div style="font:500 15px/1.55 {};color:{};margin:0 0 16px">{}</div>'.format(FONT, TEXT, rich(ctx.story["headline"])))
    lede = sanitize_html(ctx.mail_msg) if ctx.mail_msg else (
        "We caught an error in the <b>{}</b> recipe. Here's what happened, why it most likely happened "
        "and what to do next.".format(esc(ctx.recipe_name)))
    # The email opens on the error, not on a greeting: the intro (greeting + "we caught an error in…") is off unless
    # show_intro is on, and a message the caller passed in mail_msg still shows, as one plain line.
    if cfg["show_intro"]:
        intro = '<b style="color:{}">{}</b><br>{}'.format(INK, esc(cfg["greeting"]), lede)
    elif ctx.mail_msg:
        intro = sanitize_html(ctx.mail_msg)
    else:
        intro = ""
    intro_row = ('<tr><td class="px" style="padding:10px 32px {pb}px"><div style="border-top:1px solid {l};padding-top:{pt}px;'
                 'font:15px/1.65 {f};color:{t}">{i}</div></td></tr>').format(
        pb=24 if intro else 4, pt=18 if intro else 0, l=LINE, f=FONT, t=TEXT, i=intro)
    if cfg["hero_layout"] != "classic":
        # Coursera logo, then the team logo after a thin divider (only when team_logo_url is set).
        logos = logo
        if safe_url(cfg["team_logo_url"]):
            logos = ('<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
                     '<td valign="middle">{logo}</td>'
                     '<td valign="middle" style="padding:0 14px"><div style="width:1px;height:26px;background:{line};'
                     'font-size:0;line-height:0">&nbsp;</div></td>'
                     '<td valign="middle"><img src="{team}" alt="{alt}" height="30" '
                     'style="height:30px;width:auto;display:block;border:0"></td></tr></table>').format(
                logo=logo, line=LINE, team=esc(cfg["team_logo_url"]), alt=esc(cfg["team_name"] or "Team"))
        return (
            '<tr><td bgcolor="{c}" style="height:6px;line-height:6px;font-size:0;background:{c}">&nbsp;</td></tr>'
            '{banner}'
            '<tr><td class="px" style="padding:24px 32px 4px">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td align="left" valign="middle">{logos}</td>'
            '<td align="right" valign="middle" style="line-height:1">{right}</td>'
            '</tr></table>'
            '<div style="line-height:1;margin:18px 0 10px">{pills}</div>'
            '<div class="h1" style="font:800 21px/1.3 {f};color:{ink};margin:0 0 8px;word-break:break-word">{recipe}</div>'
            '{headline_div}'
            '</td></tr>'
            '{intro_row}'
        ).format(c=sev["color"], banner=banner_row, logos=logos, right=right, pills="".join(pills), f=FONT, ink=INK,
                 recipe=esc(ctx.recipe_name), headline_div=headline_div, intro_row=intro_row)
    return (
        '<tr><td bgcolor="{c}" style="height:6px;line-height:6px;font-size:0;background:{c}">&nbsp;</td></tr>'
        '{banner}'
        '<tr><td class="px" style="padding:24px 32px 4px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td align="left" valign="middle">{logo}</td><td align="right" valign="middle" style="line-height:1">{right}</td>'
        '</tr></table>'
        '<div style="margin:22px 0 8px;font:800 12px/1.4 {f};letter-spacing:.11em;text-transform:uppercase;color:{c}">'
        '{emoji}&nbsp; {sevl} priority · Recipe error alert</div>'
        '<div class="h1" style="font:800 21px/1.3 {f};color:{ink};margin:0 0 8px;word-break:break-word">{recipe}</div>'
        '{headline_div}'
        '<div style="line-height:1">{pills}</div>'
        '</td></tr>'
        '{intro_row}'
    ).format(c=sev["color"], banner=banner_row, logo=logo, right=right, f=FONT, emoji=sev["emoji"], sevl=esc(sev["label"]),
             ink=INK, recipe=esc(ctx.recipe_name), text=TEXT, headline_div=headline_div,
             pills="".join(pills), intro_row=intro_row)


def sec_kpis(ctx):
    """Up to four thin tiles: a small label, then the value and its note on one line. They are background facts, so they
    take little room (about 50 px high)."""
    tiles = ctx.tiles
    if not tiles:
        return ""
    width = 100 // max(len(tiles), 2 if len(tiles) == 2 else 3)        # one tile does not stretch across the whole email
    cells = []
    for tile in tiles:
        cells.append(
            '<td class="stack" width="{w}%" valign="top" style="padding:0 4px 6px">'
            '<div class="hv-card" style="background:{soft};border:1px solid {line};border-radius:10px;padding:7px 12px 8px">'
            '<div style="font:700 10px/1.3 {f};letter-spacing:.07em;text-transform:uppercase;color:{m}">{label}</div>'
            '<div style="margin-top:1px"><span style="font:800 18px/1.3 {f};color:{color};white-space:nowrap">{value}</span>'
            '<span style="font:11px/1.4 {f};color:{m};margin-left:8px">{sub}</span></div>'
            '</div></td>'.format(w=width, soft=SOFT, line=LINE, f=FONT, m=MUTED, label=esc(tile["label"]),
                                 color=tile.get("color") or INK, value=esc(tile["value"]), sub=esc(tile.get("sub", ""))))
    if len(tiles) == 1:                                                   # an empty cell takes the rest of the row
        cells.append('<td class="stack" style="padding:0;font-size:0;line-height:0">&nbsp;</td>')
    return section('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{}</tr>'
                   '</table>'.format("".join(cells)), top=0, bottom=18)


def sec_flow(ctx):
    if not (ctx.source_label or ctx.target_label):
        return ""
    sev, failing = ctx.sev, failing_node(ctx)
    step = ctx.recipe_info["step"] if ctx.recipe_info and ctx.recipe_info.get("step") else None
    action = " › ".join(x for x in (app_label(ctx.errored_app, ctx.extra.get("app_names")) if ctx.errored_app else "",
                                    ctx.errored_action) if x)
    middle_sub = action or (step["title"] if step else "") or clip(ctx.recipe_name, 48)

    def node(role, title, sub, name):
        failed = failing == name
        bg, border = (sev["soft"], sev["color"]) if failed else (SOFT, LINE)
        badge = ('<div style="margin-top:6px;font:800 11px/1.3 {};color:{};letter-spacing:.04em">✖ FAILED HERE</div>'
                 .format(FONT, sev["color"]) if failed else "")
        return ('<td class="flowcell hv-cell" width="30%" valign="middle" bgcolor="{bg}" style="background:{bg};'
                'border:{bw}px solid {bd};border-radius:12px;padding:12px 10px;text-align:center">'
                '<div style="font:700 10px/1.3 {f};letter-spacing:.1em;text-transform:uppercase;color:{m}">{role}</div>'
                '<div style="font:700 14px/1.35 {f};color:{ink};margin-top:4px;word-break:break-word">{title}</div>'
                '<div style="font:12px/1.4 {f};color:{m};margin-top:2px;word-break:break-word">{sub}</div>{badge}</td>'
                ).format(bg=bg, bw=2 if failed else 1, bd=border, f=FONT, m=MUTED, role=role, ink=INK,
                         title=esc(title or "—"), sub=esc(sub), badge=badge)

    def arrow(into):
        color = sev["color"] if failing == into else FAINT
        return ('<td width="5%" align="center" valign="middle" style="font:700 18px/1 {};color:{}">&#8594;</td>'
                .format(FONT, color))
    middle_title = "Step " + ctx.step if ctx.step else "Recipe"
    body = heading(ctx, "flow") + (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="border-collapse:separate"><tr>{}{}{}{}{}</tr></table>').format(
        node("Source", ctx.source_label, ctx.source_obj, "source"), arrow("workato"),
        node("Workato", middle_title, middle_sub, "workato"), arrow("target"),
        node("Target", ctx.target_label, ctx.target_obj, "target"))
    return section(body)


def sec_story(ctx):
    story, cfg = ctx.story, ctx.cfg
    titles = ctx.extra.get("titles") or {}

    def card(key, text):
        return ('<td class="stack" width="50%" valign="top" style="padding:0 6px 10px">'
                '<div class="hv-lift" style="background:#FFFFFF;border:1px solid {line};border-top:3px solid {accent};'
                'border-radius:12px;padding:14px 16px">'
                '<div style="font:800 13px/1.4 {f};color:{ink};margin:0 0 6px">{title}</div>'
                '<div style="font:14px/1.6 {f};color:{text}">{body}</div></div></td>').format(
            line=LINE, accent=cfg["brand_color"] if key == "functional" else INK, f=FONT, ink=INK,
            title=esc(titles.get(key, TITLES[key])), text=TEXT, body=rich(text))

    cards = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
             'style="border-collapse:separate"><tr>{}{}</tr></table>').format(
        card("functional", story["functional"]), card("technical", story["technical"]))
    causes = "".join('<tr><td valign="top" width="18" style="padding:3px 0;color:{};font:700 14px/1.5 {}">•</td>'
                     '<td style="padding:3px 0;font:14px/1.55 {};color:{}">{}</td></tr>'.format(
                         ctx.sev["color"], FONT, FONT, TEXT, rich(c)) for c in story["causes"])
    steps = "".join(
        '<tr><td valign="top" width="30" style="padding:4px 0"><span style="display:inline-block;width:20px;height:20px;'
        'border-radius:10px;background:{b};color:#FFFFFF;font:800 11px/20px {f};text-align:center">{n}</span></td>'
        '<td style="padding:4px 0;font:14px/1.55 {f};color:{t}">{s}</td></tr>'.format(
            b=cfg["brand_color"], f=FONT, n=i + 1, t=TEXT, s=rich(s)) for i, s in enumerate(story["steps"]))

    def block(key, rows):
        if not rows:
            return ""
        return ('<td class="stack" width="50%" valign="top" style="padding:4px 6px 0">'
                '<div style="font:800 13px/1.4 {};color:{};margin:0 0 6px">{}</div>'
                '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{}</table></td>'
                ).format(FONT, INK, esc(titles.get(key, TITLES[key])), rows)
    lists = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
             'style="margin-top:6px"><tr>{}{}</tr></table>').format(block("causes", "" if "story.causes" in ctx.hide_subs else causes),
        block("steps", "" if "story.steps" in ctx.hide_subs else steps))
    if story["source"] == "ai":
        note = "✨ AI-assisted analysis{} · check it before acting".format(
            " · confidence: " + story["confidence"] if story["confidence"] else "")
    else:
        note = "📘 From the playbook for “{}”{}".format(category_info(ctx.category, ctx.rules)[0],
                                                          " · AI analysis unavailable" if ctx.ai_error else "")
    runbook = safe_url((ctx.extra.get("runbooks") or {}).get(ctx.category)) or safe_url(cfg["runbook_url"])
    right = esc(note) + ((" · " + link("Runbook", runbook)) if runbook else "")
    return section(heading(ctx, "story", right) + cards + lists)


def sec_signals(ctx):
    if not ctx.signals:
        return ""
    tones = {"bad": BAD, "warn": WARN, "good": GOOD, "info": INFO}
    rows = "".join(
        '<tr class="hv-row"><td valign="top" width="30" style="padding:9px 0 9px 14px;font:16px/1.4 {f};border-left:3px solid {c}">{i}</td>'
        '<td valign="top" style="padding:9px 14px 9px 8px;font:14px/1.55 {f};color:{t}">{h}</td></tr>'
        '<tr><td colspan="2" style="height:6px;line-height:6px;font-size:0">&nbsp;</td></tr>'.format(
            f=FONT, c=tones.get(s["tone"], INFO), i=s["icon"], t=TEXT, h=s["html"]) for s in ctx.signals)
    return section(heading(ctx, "signals") + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                   'border="0" bgcolor="{s}" style="background:{s};border-radius:12px">'
                   '<tr><td colspan="2" style="height:8px;line-height:8px;font-size:0">&nbsp;</td></tr>{r}</table>'
                   .format(s=SOFT, r=rows))


def sec_error(ctx):
    sev, cfg = ctx.sev, ctx.cfg
    details = ctx.details
    codes = "".join(chip(esc(code), sev["ink"], "#FFFFFF", sev["line"]) for code, _ in ctx.codes.most_common(4))
    if not ctx.error_plain:
        body = '<div style="font:14px/1.6 {};color:{}">No error message was passed to the error recipe.</div>'.format(
            FONT, MUTED)
    elif details["facts"]:
        facts = kv_rows([(label, mono(clip(value, 400)) if not NUMBER_RE.match(value)
                          else '<b>{}</b>'.format(esc(fmt_int(to_int(NUMBER_RE.match(value).group(1))))))
                         for label, value in details["facts"]], label_width=170)
        extra = "".join('<div style="font:13px/1.6 {};color:{};margin-top:6px">{}</div>'.format(FONT, TEXT, esc(clip(x, 500)))
                        for x in details["extra"][:6])
        body = ('<div style="font:600 15px/1.55 {f};color:{ink};margin:0 0 10px">{h}</div>{facts}{extra}').format(
            f=FONT, ink=INK, h=esc(clip(details["headline"], 600)), facts=facts, extra=extra)
    else:
        raw = ctx.error_raw
        truncated = len(raw) > cfg["max_error_chars"]
        shown = sanitize_html(raw[: cfg["max_error_chars"]]) if "<" in raw else esc(raw[: cfg["max_error_chars"]])
        body = ('<div style="font:13px/1.6 {m};color:{ink};white-space:pre-wrap;word-break:break-word">{s}</div>{t}').format(
            m=MONO, ink=INK, s=shown, t='<div style="font:12px {};color:{};margin-top:8px">… truncated, full text in the job.</div>'
            .format(FONT, MUTED) if truncated else "")
    box = ('<div class="hv-err" style="background:{soft};border:1px solid {line};'
           'border-radius:10px;padding:16px 18px">{codes}{body}</div>').format(
        soft=sev["soft"], line=sev["line"], c=sev["color"],
        codes='<div style="margin:0 0 6px;line-height:1">{}</div>'.format(codes) if codes else "", body=body)
    return section(heading(ctx, "error") + box)


def cell_html(cell, col_index, ctx, is_id, is_err, dup_values):
    value = cell["value"]
    if is_err:
        match = re.match(r"^\s*([A-Z][A-Z_]{3,})\s*:\s*(.*)$", value, re.S)
        if match:
            content = chip(esc(match.group(1)), ctx.sev["ink"], ctx.sev["soft"], ctx.sev["line"]) + "<br>" + esc(match.group(2))
        else:
            content = esc(value)
    elif is_id:
        content = '<span style="font-family:{};font-size:12px;word-break:break-all">{}</span>'.format(MONO, esc(value))
    else:
        content = esc(value)
    url = safe_url(cell["url"])
    if url:
        content = '<a href="{}" target="_blank" style="color:#0056D2;text-decoration:none">{}</a>'.format(esc(url), content)
    if dup_values and value.strip() in dup_values:
        content += (' <span style="display:inline-block;padding:0 6px;border-radius:999px;background:{};color:{};'
                    'font:700 10px/1.7 {}">×{}</span>').format(WARN_SOFT, WARN, FONT, dup_values[value.strip()])
    style = ""
    if cell["bold"] and cell["bold"].lower() not in ("no", "n", "false", "0"):
        style += "font-weight:700;"
    color = css_color(cell["color"])
    if color:
        style += "color:{};".format(color)
    return content, style


def sec_records(ctx, max_rows):
    if not ctx.cols or not ctx.rows:
        return ""
    rec, sev = ctx.rec, ctx.sev
    shown = ctx.rows[:max_rows]
    count = rec["count"]
    right = pill("{} of {}".format(len(shown), fmt_int(count)) if len(shown) < count else plural(count, "record"),
                 sev["ink"], sev["soft"], sev["line"])
    codes = "".join(chip("{} ×{}".format(esc(code), n), sev["ink"], "#FFFFFF", sev["line"])
                    for code, n in rec["codes"].most_common(6))
    def room(c):
        """The least a column may shrink to: an id keeps room for its start, the error text for a few words."""
        if c["i"] == rec["err_col"]:
            return 220
        return 150 if c["i"] in rec["id_cols"] else 90
    head = "".join('<th class="rc" align="left" {w}style="min-width:{m}px;padding:10px 12px;background:{p};font:700 12px/1.4 {f};'
                   'color:{i};border-bottom:1px solid {l};text-align:left">{n}</th>'.format(
                       w='width="{}%" '.format(c["width"]) if c["width"] else "", m=room(c), p=PANEL, f=FONT, i=INK, l=LINE,
                       n=esc(c["name"])) for c in ctx.cols)
    body = []
    for index, row in enumerate(shown):
        bg = "#FFFFFF" if index % 2 == 0 else "#FAFBFD"
        cells = []
        for c in ctx.cols:
            i = c["i"]
            content, extra_style = cell_html(row[i], i, ctx, i in rec["id_cols"], i == rec["err_col"],
                                             rec["duplicates"].get(i))
            cells.append('<td class="rc" valign="top" style="padding:10px 12px;font:13px/1.5 {f};color:{t};border-bottom:1px solid '
                         '#EEF2F6;word-break:break-word;{x}">{c}</td>'.format(f=FONT, t=TEXT, x=extra_style, c=content))
        body.append('<tr class="hv-trow" bgcolor="{}" style="background:{}">{}</tr>'.format(bg, bg, "".join(cells)))
    table = ('<div style="overflow-x:auto;-webkit-overflow-scrolling:touch">'
             '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
             'style="border-collapse:separate;border:1px solid {};border-radius:10px;overflow:hidden">'
             '<tr>{}</tr>{}</table></div>').format(LINE, head, "".join(body))
    more = ""
    if len(shown) < count:
        more = '<div style="font:12px/1.5 {};color:{};margin-top:8px">Showing the first {} of {} records{}.</div>'.format(
            FONT, MUTED, len(shown), fmt_int(count), ": the full list is in the error file" if ctx.error_file_url else "")
    return section(heading(ctx, "records", right) +
                   ('<div style="margin:0 0 8px;line-height:1">{}</div>'.format(codes) if codes else "") + table + more)


STATUS_COLORS = {"notified": (INFO, INFO_SOFT), "reprocessed": (GOOD, GOOD_SOFT),
                 "failed again": (BAD, BAD_SOFT), "created": (MUTED, PANEL)}


def bar_chart(ctx):
    chart = ctx.history["chart"]
    peak = max((s + o) for _, s, o, _ in chart) or 1
    height = 48
    width = "{:.2f}".format(100.0 / len(chart))
    cells = []
    for day, same, other, today in chart:
        hs = max(4, int(round(height * same / float(peak)))) if same else 0
        ho = max(4, int(round(height * other / float(peak)))) if other else 0
        if hs + ho > height:
            ho = max(0, height - hs)
        parts = []
        blank = height - hs - ho - (0 if (same or other) else 2)
        if blank > 0:
            parts.append('<tr><td height="{0}" style="height:{0}px;line-height:{0}px;font-size:0">&nbsp;</td></tr>'.format(blank))
        if hs:
            color = ctx.sev["ink"] if today else ctx.sev["color"]
            parts.append('<tr><td height="{0}" bgcolor="{1}" style="height:{0}px;line-height:{0}px;font-size:0;'
                         'background:{1};border-radius:3px 3px 0 0">&nbsp;</td></tr>'.format(hs, color))
        if ho:
            parts.append('<tr><td height="{0}" bgcolor="#CBD5E1" style="height:{0}px;line-height:{0}px;font-size:0;'
                         'background:#CBD5E1">&nbsp;</td></tr>'.format(ho))
        if not same and not other:
            parts.append('<tr><td height="2" bgcolor="{0}" style="height:2px;line-height:2px;font-size:0;background:{0}">'
                         '&nbsp;</td></tr>'.format(LINE))
        cells.append('<td class="hv-bar" width="{w}%" valign="bottom" title="{t}" style="padding:0 1px">'
                     '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{p}</table></td>'
                     .format(w=width, t=esc("{}: {} same, {} other".format(short_day(day), same, other)), p="".join(parts)))
    axis = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td style="font:11px/1.6 {f};color:{m};padding-top:4px">{a}</td>'
            '<td align="center" style="font:11px/1.6 {f};color:{m};padding-top:4px">{b}</td>'
            '<td align="right" style="font:11px/1.6 {f};color:{m};padding-top:4px">Today</td></tr></table>').format(
        f=FONT, m=MUTED, a=short_day(chart[0][0]), b=short_day(chart[len(chart) // 2][0]))
    legend = ('<div style="font:11px/1.6 {f};color:{m};margin-top:4px">'
              '<span style="display:inline-block;width:9px;height:9px;background:{c};border-radius:2px"></span> same kind of error'
              '&nbsp;&nbsp;<span style="display:inline-block;width:9px;height:9px;background:#CBD5E1;border-radius:2px"></span>'
              ' other errors in this recipe</div>').format(f=FONT, m=MUTED, c=ctx.sev["color"])
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
            'style="border-bottom:1px solid {}"><tr>{}</tr></table>'.format(LINE, "".join(cells)) + axis + legend)


def sec_history(ctx):
    h = ctx.history
    if not h:
        return ""
    label, _ = category_info(ctx.category, ctx.rules)
    trend = {"new": ("✨ New", INFO, INFO_SOFT), "rising": ("📈 Rising", BAD, BAD_SOFT),
             "easing": ("📉 Easing", GOOD, GOOD_SOFT), "steady": ("➖ Steady", MUTED, PANEL),
             "returning": ("↩️ Returning", WARN, WARN_SOFT)}[h["trend"]]
    title_right = pill(esc(trend[0]), trend[1], trend[2], LINE) + '<span style="font:12px {};color:{}">last {} days</span>'.format(
        FONT, MUTED, h["days"])
    if not h["total"]:
        summary = "No earlier failures logged for this recipe in the last {} days. This is the first one.".format(h["days"])
    else:
        summary = ("This recipe failed <b>{}</b> in the last {} days, and <b>{}</b> {} the same kind of error "
                   "(<i>{}</i>).".format(plural(h["total"], "time"), h["days"], fmt_int(h["same"]),
                                         "was" if h["same"] == 1 else "were", esc(label.lower())))
        if h["same"]:
            summary += " First seen {}, last seen {}.".format(rel_day(h["first_seen"], ctx.today),
                                                              rel_day(h["last_seen"], ctx.today))
            summary += " <b>{}×</b> in the last 7 days counting this one.".format(h["week_total"])
            if h["exact"]:
                summary += " {} had exactly the same message.".format(plural(h["exact"], "occurrence"))
            if h["reprocessed"]:
                summary += " {} fixed by reprocessing.".format(plural(h["reprocessed"], "was", "were"))
            if h["failed_again"]:
                summary += " Reprocessing didn't help {}.".format(plural(h["failed_again"], "time"))
    recent = ""
    if h["recent"]:
        rows = []
        for row in h["recent"]:
            when = row["ts"].strftime("%d %b · ") + clock(row["ts"]) if row["ts"] else short_day(row["date"])
            fg, bg = STATUS_COLORS.get(row["status"].lower(), (MUTED, PANEL))
            status = pill(esc(row["status"] or "—"), fg, bg, LINE) if row["status"] else ""
            message = plain(row["message"]) or "(no message)"
            if ctx.cfg["mask_history_pii"]:
                message = mask_emails(message)
            job = (" " + link("job ↗", row["job_url"])) if row["job_url"] else ""
            rows.append('<tr class="hv-trow"><td valign="top" style="padding:8px 10px 8px 0;font:12px/1.5 {mo};color:{m};white-space:nowrap;'
                        'border-bottom:1px solid {l}">{w}</td><td valign="top" class="hide-sm" style="padding:6px 10px 2px 0;'
                        'border-bottom:1px solid {l};white-space:nowrap">{s}</td><td valign="top" style="padding:8px 0;'
                        'font:13px/1.5 {f};color:{t};border-bottom:1px solid {l};word-break:break-word">{msg}{j}</td></tr>'.format(
                            mo=MONO, m=MUTED, l=LINE, w=esc(when), s=status, f=FONT, t=TEXT, msg=esc(clip(message, 150)), j=job))
        recent = ('<div style="font:800 13px/1.4 {};color:{};margin:18px 0 4px">Recent similar failures</div>'
                  '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{}</table>').format(
            FONT, INK, "".join(rows))
    top = ""
    if h["top"] and h["total"]:
        peak = h["top"][0][1]
        rows = []
        for key, n in h["top"]:
            name, icon = category_info(key, ctx.rules)
            pct = max(4, int(round(100.0 * n / peak)))
            color = ctx.sev["color"] if key in ctx.match_categories else "#CBD5E1"
            rest = '<td width="{0}%" style="font-size:0;line-height:8px">&nbsp;</td>'.format(100 - pct) if pct < 100 else ""
            rows.append('<tr class="hv-row"><td width="42%" style="padding:4px 8px 4px 0;font:13px/1.4 {f};color:{t}">{i} {n}</td>'
                        '<td style="padding:4px 8px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                        'border="0"><tr><td width="{p}%" height="8" bgcolor="{c}" style="height:8px;font-size:0;line-height:8px;'
                        'background:{c};border-radius:4px">&nbsp;</td>{r}</tr></table></td>'
                        '<td width="40" align="right" style="padding:4px 0;font:700 13px/1.4 {f};color:{ink}">{k}</td></tr>'.format(
                            f=FONT, t=TEXT, i=icon, n=esc(name), p=pct, c=color, r=rest, ink=INK, k=fmt_int(n)))
        top = ('<div style="font:800 13px/1.4 {};color:{};margin:18px 0 4px">Most common errors in this recipe</div>'
               '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{}</table>').format(
            FONT, INK, "".join(rows))
    body = heading(ctx, "history", title_right) + panel(
        '<div style="font:14px/1.6 {};color:{};margin:0 0 12px">{}</div>'.format(FONT, TEXT, summary)
        + ("" if "history.chart" in ctx.hide_subs else bar_chart(ctx))
        + ("" if "history.recent" in ctx.hide_subs else recent)
        + ("" if "history.common" in ctx.hide_subs else top))
    return section(body)


def sec_job(ctx):
    job, recipe, jobs = ctx.job_info, ctx.recipe_info, ctx.jobs_info
    if not (job or recipe or (jobs and jobs["jobs"])):
        return ""
    left, right = [], []
    if job:
        status = job["status"] or "unknown"
        note = ("the error handler caught the error, so Workato counts it a success"
                if status in ("succeeded", "success", "completed") else "when this alert was built")
        left.append(("Status now", "{} <span style='color:{}'>({})</span>".format(esc(status), MUTED, note)))
        if job["started_at"]:
            left.append(("Started", esc(short_when(job["started_at"]))))
        if job["duration"] is not None:
            left.append(("Ran for", esc(duration(job["duration"])) + (" before failing" if job["error_at"] else "")))
        left.append(("Steps run", fmt_int(job["lines"])))
        if job["failed_line"]:
            fl = job["failed_line"]
            left.append(("Failed at", esc("Line {} · {} › {}".format(fl["number"], app_label(fl["adapter"]), fl["action"]))))
        if job["error_type"]:
            left.append(("Error type", esc(job["error_type"])))
        if job["retry_count"] is not None:
            left.append(("Retries", fmt_int(job["retry_count"])))
        if job["slowest"]:
            s = job["slowest"]
            left.append(("Slowest step", esc("Line {} · {} › {} · {}".format(s["number"], app_label(s["adapter"]),
                                                                            s["action"], duration(s["seconds"])))))
    if recipe:
        running = recipe["running"]
        state = ("<span style='color:{}'>● Running</span>".format(GOOD) if running is True else
                 "<span style='color:{}'>■ Stopped</span>".format(BAD) if running is False else "—")
        right.append(("State", state))
        if recipe["version"] or recipe["updated_at"]:
            right.append(("Version", esc(" · ".join(x for x in (
                "v{}".format(recipe["version"]) if recipe["version"] else "",
                "changed " + rel_age(recipe["updated_at"], ctx.now) if recipe["updated_at"] else "") if x))))
        if recipe["editor"]:
            right.append(("Changed by", esc(recipe["editor"])))
        ok, bad = recipe["succeeded"], recipe["failed"]
        if ok is not None and bad is not None and ok + bad:
            right.append(("Lifetime", "{} success <span style='color:{}'>({} ✓ · {} ✗ · Workato's count)</span>".format(
                esc(fmt_pct(100.0 * ok / (ok + bad), bad)), MUTED, fmt_int(ok), fmt_int(bad))))
        if recipe["step"]:
            st = recipe["step"]
            right.append(("Step {}".format(ctx.step), esc(st["title"] or "{} › {}".format(app_label(st["provider"]), st["name"])) +
                          ("<br><span style='color:{}'>“{}”</span>".format(MUTED, esc(st["comment"])) if st["comment"] else "")))
        apps = [app_label(a) for a in ([recipe["trigger"]] if recipe["trigger"] else []) + recipe["apps"]]
        if apps:
            right.append(("Apps", esc(" → ".join(dict.fromkeys(apps)))))

    def column(title, pairs, first):
        if not pairs:
            return ""
        return '<td class="stack dcol" width="50%" valign="top" style="padding:{}">{}</td>'.format(
            "0 16px 0 0" if first else "0 0 0 16px", dl(title, pairs, tight=True))
    body = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '{}{}</tr></table>').format(column("Job", left, True), column("Recipe", right, False))
    if jobs and jobs["jobs"] and "job.recent" not in ctx.hide_subs:
        colors = {"ok": "#22C55E", "fail": "#EF4444", "pending": "#CBD5E1"}
        dots = "".join('<td class="hv-bar" width="14" style="padding:0 3px 0 0"><table role="presentation" cellpadding="0" cellspacing="0" '
                       'border="0"><tr><td width="12" height="12" bgcolor="{0}" title="{1}" style="width:12px;height:12px;'
                       'line-height:12px;font-size:0;background:{0};border-radius:3px">&nbsp;</td></tr></table></td>'.format(
                           colors[j["state"]], esc(j["why"] or {"ok": "succeeded in Workato", "fail": "failed in Workato",
                                                                   "pending": "still running"}[j["state"]])) for j in reversed(jobs["jobs"]))
        if jobs["known"]:
            counts = "{} with an error · {} clean".format(jobs["errors"], jobs["clean"])
        else:
            counts = "Workato's own status, which counts handled errors as successes"
        meta = ('<span style="font-weight:400;letter-spacing:0;text-transform:none;color:{m}"> · {c}{p} · '
                'oldest → newest</span>').format(m=MUTED, c=counts, p=" · {} running".format(jobs["pending"]) if jobs["pending"] else "")
        body += ('<div style="margin-top:16px">{}<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                 'style="margin-top:8px"><tr>{}</tr></table></div>').format(
            block_title("Last {} jobs".format(len(jobs["jobs"])), meta), dots)
    return section(heading(ctx, "job") + panel(body))


def block_title(text, right=""):
    """The small uppercase title with a line under it that heads every block of the technical details and of the job &
    recipe card."""
    return ('<div style="font:700 11px/1.4 {f};letter-spacing:.08em;text-transform:uppercase;color:{i};margin:0 0 4px;'
            'padding-bottom:6px;border-bottom:1px solid {l}">{t}{r}</div>').format(f=FONT, i=INK, l=LINE, t=esc(text), r=right)


def dl(title, pairs, tight=False):
    """One block of the technical details: a small title with a line under it, then label | value rows. tight: the label
    column is only as wide as its longest label (the job & recipe card), not 36% of the block."""
    pairs = [(label, html) for label, html in pairs if html not in (None, "")]
    if not pairs:
        return ""
    if tight:
        label = ('<td valign="top" width="1%" style="width:1%;white-space:nowrap;padding:4px 12px 4px 0;font:12px/1.5 {f};'
                 'color:{m}">{l}</td>')
    else:
        label = '<td valign="top" width="36%" style="padding:4px 12px 4px 0;font:12px/1.5 {f};color:{m}">{l}</td>'
    rows = "".join(
        ('<tr class="hv-row">' + label + '<td valign="top" style="padding:4px 0;font:13px/1.5 {f};color:{i};'
         'word-break:break-word">{v}</td></tr>').format(f=FONT, m=MUTED, i=INK, l=esc(label_text), v=html)
        for label_text, html in pairs)
    return block_title(title) + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{}</table>'.format(rows)


def job_page(ctx, handle, child=""):
    """The Workato page of a job of the failing recipe; a child job opens under its parent."""
    if not (ctx.recipe_id and handle):
        return ""
    url = "{}/recipes/{}/job/{}".format(ctx.app_host, urllib_parse.quote(ctx.recipe_id),
                                         urllib_parse.quote(handle, safe="-_"))
    return url + ("?child_job_id=" + urllib_parse.quote(child, safe="-_") if child else "")


def id_link(text, url):
    """A recipe or job id in monospace, a link when there is a page to open."""
    style = "font-family:{};font-size:12px;font-weight:600".format(MONO)
    url = safe_url(url)
    if not url:
        return '<span style="{}">{}</span>'.format(style, esc(text))
    return '<a class="hv-link" href="{}" target="_blank" style="{};color:#0056D2;text-decoration:none">{}&nbsp;&#8599;</a>'.format(
        esc(url), style, esc(text))


def sec_details(ctx):
    d, rep = ctx.decision, ctx.repeat
    shown = set(ctx.sections)
    muted = lambda html: '<span style="color:{}">{}</span>'.format(MUTED, html)

    app = app_label(ctx.errored_app, ctx.extra.get("app_names")) if ctx.errored_app else ""
    action = " › ".join(x for x in (app, ctx.errored_action) if x)
    where = " · ".join(x for x in ("Line {}".format(ctx.step) if ctx.step else "", action) if x)
    failure = [("Failed at", esc(where)), ("Error time", esc(ctx.error_time)),
               ("Retries", fmt_int(ctx.retry_count) if ctx.retry_count is not None else "")]

    def side(system, obj):
        return "<b>{}</b>{}".format(esc(system) or "&mdash;", muted(" › " + esc(obj)) if obj else "")
    flow_shown = "flow" in ctx.sections and bool(ctx.source_label or ctx.target_label)
    systems = [] if flow_shown else [
        (label, side(system, obj)) for label, system, obj in
        (("Source", ctx.source_label, ctx.source_obj), ("Target", ctx.target_label, ctx.target_obj)) if system or obj]

    master, handle = ctx.master, ctx.job_handle
    ids = [("Recipe", id_link(ctx.recipe_id, ctx.recipe_url) if ctx.recipe_id else "")]
    if ctx.developer:
        ids.append(("Developer", link(ctx.developer["name"] or ctx.developer["email"], "mailto:" + ctx.developer["email"])))
    if master and handle and master != handle:
        ids.append(("Child job", id_link(handle, ctx.job_url or job_page(ctx, master, handle))))
        ids.append(("Parent job", id_link(master, job_page(ctx, master))))
    elif handle or master:
        ids.append(("Job", id_link(handle or master, ctx.job_url or job_page(ctx, handle or master))))

    handling = []
    status = ctx.table_row.get("status", "") if ctx.table_row else ""
    if status:
        fg, bg = STATUS_COLORS.get(status.lower(), (MUTED, PANEL))
        handling.append(("Logged as", '<span style="display:inline-block;padding:1px 9px;border-radius:999px;'
                         'background:{};color:{};border:1px solid {};font:600 12px/1.6 {}">{}</span>'.format(
                             bg, fg, LINE, FONT, esc(status))))
    state, _, head, detail = retry_status(ctx)
    handling.append(("Retry", "<b>{}</b>{}".format(esc(head), muted(" · " + esc(detail)))))
    if is_deferred(ctx):
        when = []
        if ctx.frequency is not None:
            when.append("every {}".format(plural(ctx.frequency, "day")))
        if ctx.error_limit is not None:
            when.append("over {}".format(plural(ctx.error_limit, "error")))
        handling.append(("Notify", esc(" or ".join(when))))
    if "signals" not in shown:       # the signals already say it when they are in the email
        if d["source"] not in NO_DECISION:
            how = ", ".join(x for x in (DECISION_SOURCES.get(d["source"], d["source"]),
                                        d["confidence"] if d["source"] != "input" else "") if x)
            handling.append(("Reprocessable", "<b>{}</b>{}".format("Yes" if d["reprocessable"] else "No",
                                                                    muted(" · " + esc(how)) if how else "")))
        if rep["enqueued"]:
            new = rep["job_id"]
            handling.append(("Auto-retry", "Queued" + (" as " + id_link(new, job_page(ctx, ctx.master, new)) if new else "")))
        elif rep["attempted"]:
            handling.append(("Auto-retry", "Failed: " + esc(clip(rep["error"], 160))))
        elif rep["skipped"] and d["reprocessable"]:
            handling.append(("Auto-retry", "Not tried: " + esc(clip(rep["skipped"], 160))))
    flags = [name for name, on in (("Scheduled run", ctx.sch_run), ("Repeated alert", ctx.is_repeated)) if on]
    if flags:
        handling.append(("Run type", esc(", ".join(flags))))
    if ctx.file_name:
        handling.append(("File name", mono(ctx.file_name)))
    if ctx.error_file_url:
        handling.append(("Error file", link("View error file", ctx.error_file_url)))
    handling.append(("Reference", muted(mono("#" + ctx.signature + " · " + ctx.category))))

    left, right, rows_left, rows_right = [], [], 0, 0      # each block goes to the shorter column
    for title, pairs in (("Failure", failure), ("Workato", ids), ("Systems", systems), ("Handling", handling)):
        pairs = [(label, html) for label, html in pairs if html not in (None, "")]
        if not pairs or "details." + title.lower() in ctx.hide_subs:
            continue
        if rows_left <= rows_right:
            left.append(dl(title, pairs))
            rows_left += len(pairs) + 1
        else:
            right.append(dl(title, pairs))
            rows_right += len(pairs) + 1
    gap = '<div style="height:16px;line-height:16px;font-size:0">&nbsp;</div>'
    cells = ""
    if left:
        cells += '<td class="stack dcol" width="50%" valign="top" style="padding:0 16px 0 0">{}</td>'.format(gap.join(left))
    if right:
        cells += '<td class="stack dcol" width="50%" valign="top" style="padding:0 0 0 16px">{}</td>'.format(gap.join(right))
    if not cells:
        return ""
    return section(heading(ctx, "details") + panel(
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>{}</tr></table>'.format(cells)))


def sec_actions(ctx):
    cfg = ctx.cfg
    buttons = []
    if ctx.job_url:
        buttons.append(button("View job details &#8594;", ctx.job_url, "#EEF4FF", cfg["brand_color"], "#D4E1FB"))
    if ctx.recipe_url:
        buttons.append(button("Open recipe", ctx.recipe_url, SOFT, TEXT, LINE))
    if ctx.error_file_url:
        buttons.append(button("Error file", ctx.error_file_url, SOFT, TEXT, LINE))
    runbook = safe_url((ctx.extra.get("runbooks") or {}).get(ctx.category)) or safe_url(cfg["runbook_url"])
    if runbook:
        buttons.append(button("Runbook", runbook, SOFT, TEXT, LINE))
    if ctx.history is not None and cfg["data_table_id"]:
        buttons.append(button("Error log", "{}/data_tables/{}".format(ctx.app_host, urllib_parse.quote(cfg["data_table_id"])),
                              SOFT, TEXT, LINE))
    for item in (ctx.extra.get("buttons") or []):
        if isinstance(item, dict) and safe_url(item.get("url")) and item.get("label"):
            buttons.append(button(esc(item["label"]), item["url"], SOFT, TEXT, LINE))
    if not buttons:
        return ""
    return section('<div style="line-height:1">{}</div>'.format("".join(buttons)), top=4, bottom=28)


def footer(ctx):
    cfg = ctx.cfg
    logo = ('<img src="{}" alt="Team" height="34" style="height:34px;width:auto;border:0;display:inline-block">'
            .format(esc(cfg["team_logo_url"])) if safe_url(cfg["team_logo_url"]) else "")
    team = ('<div style="font:700 14px/1.4 {};color:#4A154B;margin:8px 0 10px">{}</div>'.format(FONT, esc(cfg["team_name"]))
            if cfg["team_name"] else "")
    links = []
    if cfg["alert_email"]:
        mail = "mailto:{}?subject={}&body={}".format(
            cfg["alert_email"], urllib_parse.quote("Error in recipe " + ctx.recipe_name),
            urllib_parse.quote("Hi IT Integrations Team,"))
        links.append(link("Email", mail))
    for label, key in (("ServiceNow", "servicenow_url"), ("Slack", "slack_url"), ("Team Charter", "charter_url")):
        if safe_url(cfg[key]):
            links.append(link(label, cfg[key]))
    return ('<tr><td class="px" bgcolor="{s}" style="background:{s};border-top:1px solid {l};padding:24px 32px;text-align:center">'
            '{logo}{team}<div style="font:12px/1.6 {f};color:{m}">{links}</div>'
            '<div style="font:11px/1.6 {f};color:{fa};margin-top:12px">Automated alert from Workato integration monitoring · '
            'error_v2 {v} · #{sig} · built {when}</div></td></tr>').format(
        s=SOFT, l=LINE, logo=logo, team=team, f=FONT, m=MUTED, links=" &nbsp;·&nbsp; ".join(links), fa=FAINT,
        v=VERSION, sig=esc(ctx.signature), when=esc(short_when(ctx.now)))


CARD_WIDTH = 800           # the card's width when the failed-records table has up to three columns
CARD_WIDTH_PER_COLUMN = 120   # ... and what each column after the third adds, so a five-column table is 1,040 px


def card_width(ctx):
    """How wide the card may grow (it is always fluid below that, so a phone shows it at full width). max_width wins when
    it is set. Otherwise the card is 800 px, and wider when the failed-records table has four or five columns, so the
    columns keep room for an id or an error text instead of shrinking into a column of broken words."""
    if ctx.cfg["max_width"]:
        return ctx.cfg["max_width"]
    shown = len(ctx.cols) if (ctx.cols and ctx.rows and "records" in ctx.sections) else 0
    return CARD_WIDTH + CARD_WIDTH_PER_COLUMN * max(0, shown - 3)


def render_new(ctx, max_rows):
    cfg, env = ctx.cfg, ctx.env
    builders = {"hero": sec_hero, "kpis": sec_kpis, "flow": sec_flow, "story": sec_story, "signals": sec_signals,
                "error": sec_error, "records": lambda c: sec_records(c, max_rows), "history": sec_history,
                "job": sec_job, "details": sec_details, "actions": sec_actions}
    parts, rendered = [], []
    for name in ctx.sections:
        html = builders[name](ctx)
        if html:
            parts.append(html)
            rendered.append(name)
    if "hero" not in rendered:   # keep the coloured bar and the recipe name on top
        parts.insert(0, '<tr><td bgcolor="{0}" style="height:6px;line-height:6px;font-size:0;background:{0}">&nbsp;</td></tr>'
                     '{4}'
                     '<tr><td class="px" style="padding:20px 32px 12px;font:800 20px/1.3 {1};color:{2}">{3}</td></tr>'.format(
                         ctx.sev["color"], FONT, INK, esc(ctx.recipe_name), error_banner(ctx) if cfg["error_banner"] else ""))
    width = card_width(ctx)
    ribbon = ""
    if env["label"]:
        ribbon = ('<tr><td style="padding:0 8px 10px;font:700 11px/1.4 {f};letter-spacing:.1em;text-transform:uppercase;'
                  'color:{m}">● {e} &nbsp;·&nbsp; Workato</td></tr>').format(f=FONT, m=MUTED, e=esc(env["label"]))
    spacer = "&zwnj;&nbsp;" * 60
    body = "".join(parts)
    hover = hover_css(cfg, ctx.sev, pill_hover_css(body)) if cfg["hover_effects"] else ""
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        '<title>{title}</title><style>{css}{hover}</style></head>'
        '<body style="margin:0;padding:0;background:{frame}">'
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;opacity:0;color:transparent">{pre}{sp}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{frame}" '
        'style="background:{frame}"><tr><td class="outer" align="center" style="padding:24px 10px">'
        '<!--[if mso]><table role="presentation" width="{w}" align="center" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:{w}px">'
        '{ribbon}<tr><td bgcolor="#FFFFFF" style="background:#FFFFFF;border-radius:18px;overflow:hidden;'
        'box-shadow:0 1px 3px rgba(15,23,42,.08),0 10px 28px rgba(15,23,42,.07)">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{body}{foot}</table>'
        '</td></tr></table><!--[if mso]></td></tr></table><![endif]--></td></tr></table></body></html>'
    ).format(title=esc(ctx.subject), css=CSS, hover=hover, frame=env["frame"], pre=esc(ctx.preheader), sp=spacer, w=width,
             ribbon=ribbon, body=body, foot=footer(ctx))
    return html, rendered


# --------------------------------------------------------------------- old look

OLD_HTML = """<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8" />
    <title>Workato Alerts</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="color-scheme" content="light" />
    <meta name="supported-color-schemes" content="light" />
    <style>
        body {
            margin: 0;
            padding: 24px 16px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
            background-color: #ffffff;
            color: #1f2933;
        }

        .frame {
            box-sizing: border-box;
            width: 100%;
            max-width: 956px;
            margin: 0 auto;
            background-color: __ENV_COLOR__;
            border-radius: 20px;
            padding: 18px;
        }

        .container {
            width: 100%;
            max-width: 920px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
        }

        .accent-bar {
            height: 6px;
            line-height: 6px;
            font-size: 0;
            background-color: #__COLOR__;
        }

        .content {
            padding: 32px 32px 8px;
        }

        .logo-row td {
            padding-bottom: 24px;
        }

        .eyebrow {
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #6b7280;
            margin: 0 0 6px;
        }

        .recipe-name {
            font-size: 18px;
            font-weight: 700;
            color: #111827;
            margin: 0 0 20px;
            line-height: 1.35;
            padding-bottom: 16px;
            border-bottom: 1px solid #eef0f2;
            word-wrap: break-word;
        }

        .greeting {
            font-size: 15px;
            margin: 0 0 12px;
        }

        .lede {
            font-size: 15px;
            line-height: 1.6;
            color: #374151;
            margin: 0 0 20px;
            word-wrap: break-word;
        }

        .alert-box {
            background-color: #__COLOR__;
            border-left: 4px solid #b91c1c;
            border-radius: 6px;
            padding: 16px 18px;
            margin: 0 0 24px;
            word-wrap: break-word;
        }

        .alert-label {
            display: block;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #1f2933;
            margin: 0 0 8px;
        }

        .alert-message {
            font-size: 14px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
            color: #1f2933;
            line-height: 1.5;
            margin: 0;
            word-wrap: break-word;
        }

        .table-scroll {
            width: 100%;
            overflow-x: auto;
            margin: 0 0 8px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            table-layout: auto;
        }

        th,
        td {
            text-align: left;
            word-wrap: break-word;
            padding: 8px 10px;
            font-size: 13px;
        }

        th {
            width: 140px;
            background-color: #f3f4f6;
            color: #374151;
            font-weight: 600;
            border-bottom: 1px solid #e5e7eb;
        }

        td {
            border-bottom: 1px solid #eef0f2;
            color: #1f2933;
        }

        .error-details2,
        .tech-error-details {
            background-color: #f9fafb;
            border: 1px solid #eef0f2;
            border-left: 3px solid __ENV_COLOR__;
            border-radius: 6px;
            padding: 16px 18px;
            margin: 0;
            word-wrap: break-word;
            font-size: 13px;
            line-height: 1.6;
            max-width: 100%;
        }

        .tech-error-details table,
        .error-details2 table {
            width: auto;
        }

        .tech-error-details th,
        .error-details2 th {
            background-color: transparent;
            border-bottom: none;
            padding: 4px 10px 4px 0;
        }

        .tech-error-details td,
        .error-details2 td {
            border-bottom: none;
            padding: 4px 0;
        }

        .btn-row {
            margin: 0 0 2px;
        }

        .btn-table {
            width: auto;
        }

        .btn {
            display: inline-block;
            background-color: #eef2ff;
            color: #000 !important;
            padding: 1px 1px;
            text-decoration: none;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 700;
        }

        .footer {
            background-color: #f9fafb;
            padding: 24px;
            text-align: center;
        }

        .footer-team {
            font-size: 14px;
            font-weight: 700;
            color: #4A154B;
            margin: 10px 0 14px;
        }

        .footer-links {
            font-size: 12px;
            margin: 0;
        }

        .footer-links a {
            color: rgba(20, 20, 20, 0.55);
            text-decoration: none;
            margin: 0 4px;
        }

        .footer-bottom {
            font-size: 11px;
            color: #9ca3af;
            margin: 16px 0 0;
        }

        .preheader {
            display: none;
            visibility: hidden;
            opacity: 0;
            color: transparent;
            height: 0;
            width: 0;
            overflow: hidden;
            mso-hide: all;
        }

        @media only screen and (max-width: 480px) {
            body {
                padding: 12px;
            }

            .frame {
                border-radius: 14px;
                padding: 10px;
            }

            .container {
                border-radius: 14px;
            }

            .content {
                padding: 20px 20px 4px;
            }

            .btn-row td {
                text-align: center !important;
            }
        }
    </style>
</head>

<body>
    <div class="preheader">
        Error in __RECIPE__: __PREHEADER_ERROR__
        &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
    </div>
    <div class="frame">
    <div class="container">
        <div class="accent-bar">&nbsp;</div>

        <div class="content">

            <table role="presentation" class="logo-row" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                    <td align="left">
                        <img src="__LOGO_URL__" alt="Coursera" height="40" style="height: 40px; width: auto; display: inline-block; border: 0;">
                    </td>
                </tr>
            </table>

            <p class="eyebrow">Recipe error alert</p>
            <p class="recipe-name">__RECIPE__</p>

            <p class="greeting">Hi Team,</p>
            <p class="lede">__MAIL_MSG__</p>

            <div class="alert-box">
                <span class="alert-label">Error message</span>
                <p class="alert-message">__ERROR__</p>
            </div>

            <div class="table-scroll">
                __DOCUMENT__
            </div>

            <table role="presentation" class="btn-row" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                    <td align="left" style="text-align: left;">
                        <table role="presentation" class="btn-table" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td align="center" style="border-radius: 6px; background-color: #eef2ff;">
                                    <a href="__JOB_URL__" target="_blank" class="btn">View Job Details &rarr;</a>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </div>

        <div class="footer">
            <img src="__TEAM_LOGO_URL__" alt="IIS Team" height="36" style="height: 36px; width: auto; border: 0;">
            <p class="footer-team">__TEAM_NAME__</p>
            <p class="footer-links">
                <a href="mailto:__ALERT_EMAIL__?subject=Error%20in%20recipe%20__RECIPE_Q__&amp;body=Hi%20IT%20Integrations%20Team,">Email</a>
                &middot;
                <a href="__SERVICE_NOW_URL__">Service Now</a>
                &middot;
                <a href="__SLACK_URL__">Slack</a>
                &middot;
                <a href="https://coursera.atlassian.net/wiki/spaces/MUL/pages/2573336865/Team+Charter">Team Charter</a>
            </p>
            <p class="footer-bottom">This is an automated alert from Workato integration monitoring.</p>
        </div>
    </div>
    </div>
</body>

</html>
"""

OLD_TABLE_STYLE = """<style>
.table {width:100%; border:1px solid #CCCCCC; border-collapse:collapse; font-size:11px; border-radius:5px; overflow:hidden;}
.header {background-color:#F2F2F2; color:black; border: 0.1px solid #CCCCCC; text-align:center; border-collapse:collapse;}
.cell {text-align:center;  border: 0.1px solid #CCCCCC; border-collapse:collapse;}
.technical-details-table {width:100%; font-size:14px;}
</style>
"""


def old_colors(priority_raw, env_raw):
    """The current recipe's priority / color / env_color formulas."""
    p = text_of(priority_raw).strip().upper()
    if p == "CRITICAL":
        emoji, color = "🚨 ", "ff5c33"
    elif p == "HIGH":
        emoji, color = "❗ ", "ffc299"
    else:
        emoji, color = "⚠️ ", "E6F0FA"
    e = text_of(env_raw).strip().upper()
    env_color = "#D1FAE5" if e == "DEV" else ("#EEF1F4" if e == "PROD" else "#FFF8E1")
    return emoji, color, env_color


def titleize(text):
    """Ruby's String#titleize, as the old recipe applied it to the column names."""
    words = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text_of(text)))
    words = words.replace("-", "_").lower()
    words = re.sub(r"_id$", "", words)
    words = re.sub(r"[_\s]+", " ", words).strip()
    return re.sub(r"\b('?[a-z])", lambda m: m.group(1).upper(), words)


def old_document(ctx):
    """moustache_template.md, filled in the way Workato's moustache step fills it."""
    out = [OLD_TABLE_STYLE]
    present = {c["i"]: c for c in ctx.cols}
    if 1 in present:
        out.append('<table class="table">\n  <tr>\n')
        for i in range(1, 6):
            if i in present:
                width = present[i]["width"]
                style = ' style="width:{}%"'.format(width) if width else ""
                out.append('    <th class="header" {}>{}</th>\n'.format(style.strip(), esc(titleize(present[i]["name"]))))
        out.append("  </tr>\n")
        for row in ctx.rows:
            out.append("  <tr>\n")
            for i in range(1, 6):
                if i not in present:
                    continue
                cell = row[i]
                style = ("font-weight:bold;" if cell["bold"] else "") + (
                    "color: {};".format(esc(cell["color"])) if cell["color"] else "")
                value = esc(cell["value"])
                if cell["url"]:
                    value = '<a href="{}">{}</a>'.format(esc(cell["url"]), value)
                out.append('    <td class="cell" style="{}">{}</td>\n'.format(style, value))
            out.append("  </tr>\n")
        out.append("</table>\n")
    rows = []
    for label, value in (("Source System", ctx.source), ("Target System", ctx.target),
                         ("Source Object", ctx.source_obj), ("Target Object", ctx.target_obj),
                         ("Errored App", ctx.errored_app)):
        if value:
            rows.append("<tr><th>{}</th><td>: {}</td></tr>".format(label, esc(value)))
    if ctx.errored_action:
        rows.append("<tr><th>Errored Action</th><td>: {}{}</td></tr>".format(
            "Line {}: ".format(esc(ctx.step)) if ctx.step else "", esc(ctx.errored_action)))
    rows.append("<tr><th>Error Time</th><td>: {}</td></tr>".format(esc(ctx.old_error_time)))
    if ctx.retry_count is not None and text_of(ctx.inp.get("retry_count")).strip():
        rows.append("<tr><th>Retry Count</th><td>: {}</td></tr>".format(esc(text_of(ctx.inp.get("retry_count")).strip())))
    if ctx.error_file_url:
        rows.append('<tr><th>Error File</th><td>: <a href="{}" target="_blank">View Error File</a></td></tr>'.format(
            esc(ctx.error_file_url)))
    out.append('\n<div class="tech-error-details">\n  <h4 style="text-align:left;">Technical Details</h4>\n'
               '  <table class="technical-details-table">\n    {}\n  </table>\n</div>'.format("\n    ".join(rows)))
    return "".join(out)


def old_error_time(now, given):
    if given:
        return given
    hour = now.hour % 12 or 12
    return "{}, {:02d} {} {} {}:{:02d}{} {}".format(now.strftime("%A"), now.day, now.strftime("%B"), now.year, hour,
                                                    now.minute, "AM" if now.hour < 12 else "PM", tz_label(now))


def render_old(ctx):
    cfg = ctx.cfg
    _, color, env_color = old_colors(ctx.priority_raw, cfg["env"])
    mail_msg = sanitize_html(ctx.mail_msg) if ctx.mail_msg else (
        "We've identified some exceptions occurring in the <b>{}</b> recipe. Kindly review the details provided below."
        .format(esc(ctx.recipe_name)))
    replacements = (
        ("__ENV_COLOR__", env_color), ("__COLOR__", color),
        ("__PREHEADER_ERROR__", esc(clip(ctx.error_plain, 200))),
        ("__RECIPE_Q__", urllib_parse.quote(ctx.recipe_name)), ("__RECIPE__", esc(ctx.recipe_name)),
        ("__MAIL_MSG__", mail_msg), ("__ERROR__", sanitize_html(ctx.error_raw)),
        ("__DOCUMENT__", old_document(ctx)), ("__JOB_URL__", esc(ctx.job_url)),
        ("__LOGO_URL__", esc(cfg["logo_url"])), ("__TEAM_LOGO_URL__", esc(cfg["team_logo_url"])),
        ("__TEAM_NAME__", esc(cfg["team_name"])), ("__ALERT_EMAIL__", esc(cfg["alert_email"])),
        ("__SERVICE_NOW_URL__", esc(cfg["servicenow_url"])), ("__SLACK_URL__", esc(cfg["slack_url"])),
    )
    html = OLD_HTML
    for token, value in replacements:
        html = html.replace(token, value)
    return html


# ------------------------------------------------------------- subject and text


def build_subject(ctx, look):
    if look == "old":
        emoji, _, _ = old_colors(ctx.priority_raw, ctx.cfg["env"])
        env = " ".join(w.capitalize() for w in re.split(r"[_\s]+", ctx.cfg["env"]) if w)
        return re.sub(r"\s{2,}", " ", "{}{} | {}".format(emoji, env, ctx.subject_in)).strip()
    label, icon = category_info(ctx.category, ctx.rules)
    h = ctx.history
    occurrence, recurring = "", ""
    if h and h["same"]:
        occurrence = "{}× in 7d".format(h["week_total"]) if h["week_total"] >= 2 else ordinal(h["occurrence"]) + " in {}d".format(h["days"])
        recurring = " · 🔁 " + occurrence
    env = " ".join(w.capitalize() for w in re.split(r"[_\s]+", ctx.cfg["env"]) if w)
    values = {"emoji": ctx.sev["emoji"], "env": env, "ENV": env.upper(), "subject": ctx.subject_in,
              "recipe": ctx.recipe_name, "priority": ctx.sev["label"], "PRIORITY": ctx.sev["label"].upper(),
              "category": label, "category_icon": icon, "occurrence": occurrence, "recurring": recurring,
              "failed": fmt_int(ctx.failed) if ctx.failed is not None else "",
              "total": fmt_int(ctx.total) if ctx.total is not None else "", "signature": ctx.signature}
    subject = fill(ctx.cfg["subject_format"], values)
    subject = re.sub(r"\s{2,}", " ", subject).strip()
    subject = re.sub(r"^\|\s*|\s*\|\s*\|", " | ", subject).strip(" |")
    return subject or ctx.subject_in


def build_preheader(ctx):
    label, _ = category_info(ctx.category, ctx.rules)
    headline = plain(ctx.story["headline"])
    parts = [headline] + ([] if label.lower() in headline.lower() else [label])
    h = ctx.history
    if h:
        parts.append("{}× this week".format(h["week_total"]) if h["same"] else "first in {} days".format(h["days"]))
    return clip(" · ".join(p for p in parts if p), 150)


def build_text(ctx):
    s, lines = ctx.story, []
    lines.append("[{}] Recipe error alert{}".format(ctx.sev["label"].upper(),
                                                    " ({})".format(ctx.env["label"]) if ctx.env["label"] else ""))
    lines.append(ctx.recipe_name)
    lines.append(plain(s["headline"]))
    state, _, head, detail = retry_status(ctx)
    lines.append("Retry: {} - {}".format(head, detail))
    lines.append("")
    lines.append("In plain words: " + s["functional"].replace("`", ""))
    lines.append("Under the hood: " + s["technical"].replace("`", ""))
    d = ctx.decision
    if d["source"] not in NO_DECISION:
        lines.append("Reprocessable: {} ({}){}".format("yes" if d["reprocessable"] else "no", d["source"],
                                                       " - " + d["reason"] if d["reason"] else ""))
    if ctx.repeat["enqueued"]:
        lines.append("Auto-retry: queued{}".format(" as " + ctx.repeat["job_id"] if ctx.repeat["job_id"] else ""))
    elif ctx.repeat["attempted"]:
        lines.append("Auto-retry: failed - " + ctx.repeat["error"])
    if s["causes"]:
        lines.append("")
        lines.append("Likely cause:")
        lines.extend("  - " + c.replace("`", "") for c in s["causes"])
    if s["steps"]:
        lines.append("")
        lines.append("Next steps:")
        lines.extend("  {}. {}".format(i + 1, x.replace("`", "")) for i, x in enumerate(s["steps"]))
    if ctx.signals:
        lines.append("")
        lines.append("Signals:")
        lines.extend("  - " + plain(x["html"]) for x in ctx.signals)
    lines.append("")
    lines.append("Error message:")
    lines.append(clip(ctx.error_plain, 1500) or "(none)")
    if ctx.rows:
        lines.append("")
        lines.append("Failed records: {}".format(ctx.rec["count"]))
    lines.append("")
    if ctx.job_url:
        lines.append("View job: " + ctx.job_url)
    if ctx.recipe_url:
        lines.append("Open recipe: " + ctx.recipe_url)
    if ctx.error_file_url:
        lines.append("Error file: " + ctx.error_file_url)
    return "\n".join(lines)


# -------------------------------------------------------------------------- main


def current_time(cfg, tz):
    if cfg["now"]:
        dt = parse_dt(cfg["now"], tz)
        if dt:
            return dt
    return datetime.now(timezone.utc).astimezone(tz)


def fill_outputs(result, ctx):
    label, _ = category_info(ctx.category, ctx.rules)
    h = ctx.history
    result.update({
        "priority": ctx.sev["label"], "priority_escalated": ctx.priority != ctx.priority_in,
        "severity_color": ctx.sev["color"], "env": ctx.env["label"],
        "error_category": ctx.category, "error_category_label": label, "error_signature": ctx.signature,
        "is_batch": ctx.is_batch, "records_total": ctx.total or 0,
        "records_failed": ctx.failed if ctx.failed is not None else ctx.rec["count"],
        "success_rate": fmt_pct(ctx.rate, ctx.failed) if ctx.rate is not None else "",
        "signals": [plain(s["html"]) for s in ctx.signals],
        "job_context_used": bool(ctx.job_info or ctx.recipe_info or ctx.jobs_info),
    })
    if getattr(ctx, "story", None):
        s = ctx.story
        result.update({"headline": plain(s["headline"]), "explanation_source": s["source"], "ai_error": ctx.ai_error,
                       "functional_summary": s["functional"], "technical_summary": s["technical"],
                       "likely_causes": list(s["causes"]), "next_steps": list(s["steps"])})
    if h:
        result.update({"history_used": True, "history_total": h["total"], "history_same_type": h["same"],
                       "history_7d": h["week_total"], "history_trend": h["trend"],
                       "first_seen": h["first_seen"].isoformat() if h["first_seen"] else "",
                       "last_seen": h["last_seen"].isoformat() if h["last_seen"] else "",
                       "is_recurring": h["same"] > 0})
    if ctx.cross:
        result["other_recipes_affected"] = len(ctx.cross)
    if ctx.recipe_info and ctx.recipe_info["running"] is not None:
        result["recipe_running"] = "yes" if ctx.recipe_info["running"] else "no"
    if ctx.developer:
        result["developer_name"], result["developer_email"] = ctx.developer["name"], ctx.developer["email"]
    if ctx.jobs_info:
        result["recent_jobs_checked"] = len(ctx.jobs_info["jobs"])
        result["recent_jobs_failed"] = ctx.jobs_info["fail"]
    d, rep = ctx.decision, ctx.repeat
    result.update({
        "action": ctx.action, "send_email": ctx.send_email, "to_email": ctx.to_email,
        "reprocessable": bool(d["reprocessable"]), "reprocess_source": d["source"],
        "reprocess_reason": d["reason"], "reprocess_confidence": d["confidence"],
        "reprocess_attempted": rep["attempted"], "reprocess_enqueued": rep["enqueued"],
        "reprocess_job_id": rep["job_id"], "reprocess_error": rep["error"] or rep["skipped"],
        "master_job_id": ctx.master, "table_row": dict(ctx.table_row),
        "table_row_json": json.dumps({column: ctx.table_row.get(key) for key, column in TABLE_ROW_KEYS},
                                     ensure_ascii=False) if ctx.table_row else "",
    })


ALERT_ROWS = 100          # failed records handed on in alert_json
ALERT_CELL = 400          # characters of one cell


def alert_facts(ctx):
    """What the alert says, as plain data (no HTML, no Slack): the error_slack step turns it into a Slack message. It is the
    one thing that step takes from this one, so the history, the job and recipe lookups, the Azure story and the retry decision
    are worked out once and never twice. Texts are plain; times are already written out."""
    cfg, sev, h = ctx.cfg, ctx.sev, ctx.history
    label, icon = category_info(ctx.category, ctx.rules)
    story = getattr(ctx, "story", None) or playbook_story(ctx)
    state, ricon, head, detail = retry_status(ctx)
    step = ctx.recipe_info["step"] if ctx.recipe_info and ctx.recipe_info.get("step") else None
    runbook = safe_url((ctx.extra.get("runbooks") or {}).get(ctx.category)) or safe_url(cfg["runbook_url"])
    rows = [[{"value": clip(text_of(row[i]["value"]), ALERT_CELL), "url": row[i]["url"], "bold": row[i]["bold"],
              "color": row[i]["color"]} for i in range(1, 6)] for row in ctx.rows[:ALERT_ROWS]]
    facts = {
        "v": 1, "version": VERSION, "subject": getattr(ctx, "subject", "") or build_subject(ctx, "new"),
        "send_email": ctx.send_email, "action": ctx.action, "deferred": is_deferred(ctx),
        "recipe_name": ctx.recipe_name, "recipe_id": ctx.recipe_id, "recipe_url": ctx.recipe_url, "job_url": ctx.job_url,
        "job_handle": ctx.job_handle, "master": ctx.master, "child_job": ctx.child_job_id, "app_host": ctx.app_host,
        "mail_msg": plain(ctx.mail_msg) if ctx.mail_msg else "", "to_email": ctx.to_email, "subject_in": ctx.subject_in,
        "sev": {"label": sev["label"], "emoji": sev["emoji"], "color": sev["color"]},
        "priority_raw": ctx.priority_raw, "priority_changed": ctx.priority != ctx.priority_in,
        "env": ctx.env["label"], "category": {"key": ctx.category, "label": label, "icon": icon},
        "signature": ctx.signature, "error_time": cfg["error_time"] or pill_when(ctx.now), "now": ctx.now.isoformat(),
        "now_text": short_when(ctx.now), "timezone": cfg["timezone"], "headline": plain(story["headline"]),
        "details": {"headline": ctx.details["headline"], "facts": [list(p) for p in ctx.details["facts"]],
                    "extra": list(ctx.details["extra"])},
        "error_plain": ctx.error_plain, "max_error_chars": cfg["max_error_chars"],
        "codes": [[c, n] for c, n in ctx.codes.most_common(8)],
        "total": ctx.total, "failed": ctx.failed, "rate": ctx.rate,
        "rate_text": fmt_pct(ctx.rate, ctx.failed) if ctx.rate is not None else "",
        "cols": [{"i": c["i"], "name": c["name"], "width": c["width"]} for c in ctx.cols], "rows": rows,
        "rec": {"count": ctx.rec["count"], "err_col": ctx.rec["err_col"], "id_cols": sorted(ctx.rec["id_cols"]),
                "codes": [[c, n] for c, n in ctx.rec["codes"].most_common(8)]},
        "source": ctx.source_label, "target": ctx.target_label, "source_obj": ctx.source_obj, "target_obj": ctx.target_obj,
        "errored_app": app_label(ctx.errored_app, ctx.extra.get("app_names")) if ctx.errored_app else "",
        "errored_action": ctx.errored_action, "step": ctx.step, "step_title": step["title"] if step else "",
        "failing": failing_node(ctx), "retry_count": ctx.retry_count if ctx.retry_count is not None
        else (ctx.job_info or {}).get("retry_count"),
        "retry": {"state": state, "icon": ricon, "head": head, "detail": detail},
        "decision": dict(ctx.decision), "repeat": dict(ctx.repeat),
        "story": {"source": story["source"], "functional": story["functional"], "technical": story["technical"],
                  "causes": list(story["causes"]), "steps": list(story["steps"])}, "ai_error": ctx.ai_error,
        "tiles": [{"label": t["label"], "value": t["value"], "sub": t.get("sub", "")} for t in ctx.tiles],
        "signals": [{"icon": x["icon"], "text": plain(x["html"]), "tone": x["tone"]} for x in ctx.signals],
        "cross": len(ctx.cross) if ctx.cross else 0,
        "history": None, "job": None, "recipe": None, "last_jobs": [],
        "links": {"runbook": runbook, "error_file": ctx.error_file_url,
                  "error_log": "{}/data_tables/{}".format(ctx.app_host, urllib_parse.quote(cfg["data_table_id"]))
                  if (h is not None and cfg["data_table_id"]) else "",
                  "extra": [{"label": text_of(b["label"]), "url": safe_url(b["url"])} for b in (ctx.extra.get("buttons") or [])
                            if isinstance(b, dict) and safe_url(b.get("url")) and b.get("label")]},
        "team": {"name": cfg["team_name"], "logo_url": safe_url(cfg["logo_url"]), "team_logo_url": safe_url(cfg["team_logo_url"]),
                 "alert_email": cfg["alert_email"], "servicenow_url": safe_url(cfg["servicenow_url"]),
                 "slack_url": safe_url(cfg["slack_url"]), "charter_url": safe_url(cfg["charter_url"])},
        "data_table_id": cfg["data_table_id"], "sch_run": ctx.sch_run, "is_repeated": ctx.is_repeated,
        "frequency": ctx.frequency, "error_limit": ctx.error_limit, "file_name": ctx.file_name,
        "file_content": clip(plain(text_of(ctx.inp.get("file_content"))), 1500),
        "error_file_path": ctx.error_file_path,
        "error_file_expires": short_when(ctx.now + timedelta(seconds=ctx.error_file_expires_in))
        if ctx.error_file_expires_in else "",
        "logged_status": ctx.table_row.get("status", "") if ctx.table_row else "",
        "developer": (ctx.developer["name"] or ctx.developer["email"]) if ctx.developer else "",
    }
    if h:
        facts["history"] = {
            "days": h["days"], "same": h["same"], "week_total": h["week_total"], "occurrence": h["occurrence"],
            "trend": h["trend"], "reprocessed": h["reprocessed"], "failed_again": h["failed_again"],
            "first_seen": short_day(h["first_seen"]) if h["first_seen"] else "",
            "last_seen": short_day(h["last_seen"]) if h["last_seen"] else "",
            "chart": [["{} {}".format(day.strftime("%b"), day.day), same, other] for day, same, other, _ in h["chart"]],
            "top": [[category_info(key, ctx.rules)[0], n] for key, n in h["top"]],
            "recent": [{"when": short_day(r["date"]), "status": r["status"], "job": r["job_id"]} for r in h["recent"]]}
    job, recipe, jobs = ctx.job_info, ctx.recipe_info, ctx.jobs_info
    if job:
        fl, sl = job["failed_line"], job["slowest"]
        facts["job"] = {
            "status": job["status"], "started": short_when(job["started_at"]) if job["started_at"] else "",
            "duration": duration(job["duration"]) if job["duration"] is not None else "", "steps": job["lines"],
            "failed_at": "Line {} · {} › {}".format(fl["number"], app_label(fl["adapter"]), fl["action"]) if fl else "",
            "error_type": job["error_type"],
            "slowest": "Line {} · {} · {}".format(sl["number"], sl["action"], duration(sl["seconds"])) if sl else ""}
    if recipe:
        apps = [app_label(a) for a in ([recipe["trigger"]] if recipe["trigger"] else []) + recipe["apps"]]
        facts["recipe"] = {
            "running": recipe["running"], "version": recipe["version"],
            "changed": rel_age(recipe["updated_at"], ctx.now) if recipe["updated_at"] else "", "editor": recipe["editor"],
            "apps": " → ".join(dict.fromkeys(apps))}
    if jobs and jobs["jobs"]:
        facts["last_jobs"] = [j["state"] for j in jobs["jobs"]]
    return facts


def build_email(ctx, result, warnings, new_look):
    """Everything only an email needs: the signals, the tiles and the html in the chosen look."""
    cfg = ctx.cfg
    ctx.signals = build_signals(ctx)
    ctx.tiles = build_tiles(ctx)
    if new_look:
        ctx.subject = build_subject(ctx, "new")
        ctx.preheader = build_preheader(ctx)
        max_rows = cfg["max_table_rows"]
        html, rendered = render_new(ctx, max_rows)
        limit = cfg["html_limit_kb"] * 1024
        while len(html.encode("utf-8")) > limit and max_rows > 5:
            max_rows = max(5, max_rows // 2)
            html, rendered = render_new(ctx, max_rows)
        if len(html.encode("utf-8")) > limit:
            warnings.append("html is {} KB, over html_limit_kb; Gmail may clip it".format(
                len(html.encode("utf-8")) // 1024))
        elif max_rows < cfg["max_table_rows"] and ctx.rec["count"] > max_rows:
            warnings.append("records table cut to {} rows to stay under {} KB".format(max_rows, cfg["html_limit_kb"]))
        result.update({"html": html, "look_used": "new", "sections_rendered": rendered,
                       "subject": ctx.subject, "preheader": ctx.preheader})
    else:
        result.update({"html": render_old(ctx), "look_used": "old", "sections_rendered": [],
                       "subject": build_subject(ctx, "old"),
                       "preheader": clip("Error in {}: {}".format(ctx.recipe_name, ctx.error_plain), 150)})
    result.update({"text_body": build_text(ctx), "ok": True})
    fill_outputs(result, ctx)
    try:                                     # for the error_slack step; a failure here never touches the email
        result["alert_json"] = json.dumps(alert_facts(ctx), ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001
        warnings.append("alert_json not built: {}: {}".format(type(exc).__name__, clip(str(exc), 160)))


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    started = time.time()
    result = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
              for k, v in OUTPUT_DEFAULTS}
    warnings = []
    inp = input if isinstance(input, dict) else {}
    ctx = None
    try:
        cfg, more = settings(inp)
        warnings.extend(more)
        tz = get_tz(cfg["timezone"])
        now = current_time(cfg, tz)
        ctx = build_context(inp, cfg, now)
        ctx.old_error_time = old_error_time(now, cfg["error_time"])
        new_look = cfg["look"] == "new"
        ctx.sections = resolve_sections(cfg, warnings) if new_look else []
        ctx.hide_subs = cfg.get("hide_subs", set())
        ctx.sections_wanted = set(ctx.sections)
        # A call that asked for deferral (frequency / error_limit) is only logged: no email goes out from here, so skip
        # what only the email needs (history, job and recipe lookups, the html). The reprocess decision and the master
        # job id are still worked out, because the logged row needs them.
        light = is_deferred(ctx) and not cfg["always_render"]
        if light:
            ctx.sections, ctx.sections_wanted = [], set()

        # What this run needs, and how the time budget is shared out.
        write_reserve = min(10, cfg["http_timeout"] * 2) if cfg["log_row"] and cfg["workato_api_token"] else 0
        hard_deadline = started + cfg["time_budget"]
        deadline = hard_deadline - write_reserve          # the lookups and Azure stop here; the row write has the rest
        need_decision = cfg["auto_reprocess"]
        need_story = new_look and bool({"story", "hero"} & ctx.sections_wanted)
        ai_on = cfg["ai"] and bool(cfg["azure_api_key"]) and (
            need_story or (need_decision and cfg["reprocess_policy"].lower() != "rules"))
        if cfg["ai"] and not cfg["azure_api_key"] and (need_story or need_decision):
            warnings.append("AI explanation skipped: no azure_api_key")
        repeat_reserve = min(8, cfg["http_timeout"]) if cfg["auto_reprocess"] else 0
        ai_reserve = min(20, cfg["time_budget"] * 0.45) if ai_on else 0
        need_history = cfg["history"] and (bool({"history", "signals", "kpis", "hero"} & ctx.sections_wanted)
                                           or cfg["auto_reprocess"])
        need_job = not ctx.master_job_id or cfg["auto_reprocess"]
        gather(ctx, deadline - ai_reserve - repeat_reserve, warnings, need_history, need_job)

        if ctx.history_rows is not None and cfg["history"]:
            ctx.history = analyze_history(ctx)
            if ctx.cross_rows is not None and cfg["cross_recipe_days"]:
                ctx.cross = analyze_cross(ctx) or None
        mark_failed_runs(ctx)
        if ctx.category == "unknown" and ctx.job_info and "stop" in ctx.job_info["error_type"].lower():
            ctx.category = STOP_JOB[0]
        maybe_escalate(ctx)
        ctx.story = explain(ctx, deadline - repeat_reserve, warnings) if ai_on else playbook_story(ctx)

        # The old recipe's logic: decide, (repeat), route, log row.
        ctx.decision = decide_reprocess(ctx, warnings)
        ctx.master = resolve_master(ctx)
        blocker = repeat_blocker(ctx)
        if blocker:
            ctx.repeat["skipped"] = blocker
        else:
            ctx.repeat = repeat_job(ctx, deadline)
            if ctx.repeat["error"]:
                warnings.append("auto-retry failed: " + ctx.repeat["error"])
        ctx.action, ctx.send_email = route(ctx)
        ctx.table_row = build_table_row(ctx)
        write_row(ctx, result, warnings, hard_deadline)    # first, before the email is built: the log must not depend on it

        if light:
            ctx.subject = build_subject(ctx, "new" if new_look else "old")
            result.update({"html": "", "subject": ctx.subject, "look_used": "log_only", "sections_rendered": [], "ok": True})
            fill_outputs(result, ctx)
        else:
            build_email(ctx, result, warnings, new_look)
    except Exception as exc:  # noqa: BLE001 - the alert must still go out
        result["error"] = "{}: {}".format(type(exc).__name__, clip(str(exc), 300))
        try:
            if ctx is None:
                cfg, _ = settings({})
                tz = get_tz(cfg["timezone"])
                ctx = build_context(inp, cfg, current_time(cfg, tz))
                ctx.old_error_time = old_error_time(ctx.now, "")
            result["html"] = render_old(ctx)
            result["subject"] = build_subject(ctx, "old")
            result["look_used"] = "old"
            result["ok"] = True
            deferred = is_deferred(ctx)       # a deferred call is still only logged if building the email failed
            result["send_email"], result["action"] = (False, "log_only") if deferred else (True, "notify")
            result["to_email"] = ctx.to_email
            if not ctx.table_row:
                ctx.master = ctx.master or resolve_master(ctx)
                ctx.send_email = not deferred
                ctx.table_row = build_table_row(ctx)
            result["table_row"] = dict(ctx.table_row)
            result["table_row_json"] = json.dumps({c: ctx.table_row.get(k) for k, c in TABLE_ROW_KEYS},
                                                  ensure_ascii=False)
            result["master_job_id"] = ctx.master
            write_row(ctx, result, warnings, started + ctx.cfg["time_budget"])    # a no-op if it was already tried
            warnings.append("building the email failed, so the old look was sent")
        except Exception as again:  # noqa: BLE001
            name = esc(text_of(inp.get("recipe_name")) or "a recipe")
            result["html"] = ("<html><body><p><b>Recipe error alert:</b> {}</p><p>{}</p><p><a href=\"{}\">View job</a></p>"
                              "</body></html>").format(name, esc(plain(inp.get("error_details"))),
                                                       esc(safe_url(inp.get("job_url"))))
            result["subject"] = "⚠️ Error in " + text_of(inp.get("recipe_name") or "a recipe")
            result["look_used"] = "plain"
            result["ok"] = True
            warnings.append("old look failed too: {}".format(clip(str(again), 200)))
    result["warnings"] = warnings
    result["html_bytes"] = len(result["html"].encode("utf-8"))
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    return result


# ---------------------------------------------------------------- local preview


def load_history_csv(path):
    """The data table's CSV export as rows (for local previews only)."""
    import csv
    csv.field_size_limit(10 ** 9)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render the error alert email locally.")
    parser.add_argument("input_json", help="a JSON file with the step's inputs")
    parser.add_argument("--out", help="where to write the html (default: print a summary only)")
    parser.add_argument("--history-csv", help="the error log data table exported as CSV")
    parser.add_argument("--set", action="append", default=[], help="override an input: name=value")
    args = parser.parse_args()
    with open(args.input_json, encoding="utf-8") as handle:
        data = json.load(handle)
    if args.history_csv:
        data["history_rows_json"] = json.dumps(load_history_csv(args.history_csv))
    for item in args.set:
        key, _, value = item.partition("=")
        data[key] = value
    output = main(data)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output["html"])
    summary = {k: v for k, v in output.items() if k not in ("html", "text_body")}
    json.dump(summary, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
