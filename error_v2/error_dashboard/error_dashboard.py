"""
error_dashboard.py -- the Workato Python step that builds the weekly integration health dashboard.

A scheduled recipe (weekly) runs this step and emails the `html` it returns. The step reads the error log
data table ("Error Notification - TBL", where error_notification.py and the old error recipe log every
failure) through the Workato data tables API: 200 rows a page, following the continuation token, one
period at a time with a few periods fetched in parallel. It needs one key:

    workato_api_token   reads the data table, and (optional) the state of the top recipes

and can use one more:

    azure_api_key       an AI-written executive summary above the built-in insights (Azure OpenAI)

Everything else is optional and has a default. Any setting can also be given in `config_json`; a filled-in
input wins over it.

THE PERIOD. By default the last 7 full days, ending yesterday in `timezone` (run it on Monday morning and it
covers Monday to Sunday). period = calendar takes the last complete week starting on `week_start`;
period_end fixes the last day; period_days changes the length. Every number is compared with the period
before, and with trend_periods periods of history (12 weeks by default).

WHAT THE DASHBOARD SHOWS. Each part is a section. `detail` (brief | standard | full) picks a set, `sections`
sets the exact order, `show_sections` / `hide_sections` add and take away.
    hero        title, period, health score and grade, a one-line headline
    kpis        tiles: errors, recipes affected, new patterns, records failed, reprocessed, backlog,
                busiest day, forecast; each with its change and a sparkline
    insights    what stands out, in plain words (an AI summary on top when azure_api_key is set)
    trend       errors per day for daily_days days, spikes marked, and the next period's forecast
    weekly      errors per period over trend_periods periods, with the forecast
    recipes     top failing recipes: errors, change, sparkline, share, main error, status, owner
    movers      rising, easing, new this period, gone quiet
    patterns    top error patterns (the message with ids and numbers taken out), new ones flagged
    categories  error categories, this period against the one before
    systems     target and source systems, source -> target routes as a heat grid, objects
    heatmap     weekday x hour of day
    calendar    every day of the trend window as a heat calendar
    records     batch runs: records processed and failed, by object
    recovery    what happened to the errors: notified, reprocessed, failed again, waiting
    backlog     deferred errors (Status Created) still waiting for the summary email
    noise       how concentrated the alerts are, alerts per recipient list
    forecast    the next period, overall and per top recipe, with at-risk recipes
    actions     buttons: error log, runbook, dashboard, your own (config_json "buttons")

NOTHING HERE WRITES. The step only reads the table and the recipes. A lookup that fails or runs out of time
only adds a line to `warnings` (and sets data_complete = false); an exception still returns a small html
saying what went wrong, with ok = false. A failing Azure call is not one of those: it is captured in `ai_error` and
`warnings`, and the dashboard is built and sent with the built-in insights only (the insights section says so).

Run it locally (no Workato needed):
    python3 error_dashboard.py --csv ../data_table_error_notification_tbl.csv \
        --set now=2026-11-20T08:00:00-08:00 --out /tmp/dashboard.html
    python3 error_dashboard.py --write-schemas      # rewrite the two schema files from SETTINGS
"""

import concurrent.futures
import hashlib
import html as htmllib
import json
import math
import re
import sys
import threading
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

VERSION = "1.0.0"

AZURE_URL = ("https://cour-servicenow-1.openai.azure.com/openai/deployments/"
             "gpt-4o/chat/completions?api-version=2024-10-21")
WORKATO_API = "https://www.workato.com/api"
APP_HOST = "https://app.workato.com"
DATA_TABLES_API = "https://data-tables.workato.com/api/v1/tables"
ERROR_TABLE_ID = "c1444a9a-03a7-4c82-8618-7796b7384b37"      # Error Notification - TBL
TEAM_CHARTER_URL = "https://coursera.atlassian.net/wiki/spaces/MUL/pages/2573336865/Team+Charter"

# The error log table's columns (config_json "table_columns" renames any of them).
TABLE_COLUMNS = {
    "date": "Date", "ts": "Error TimeStamp", "status": "Status", "reprocess_flag": "Reprocess_Flag",
    "reprocess_count": "Reprocess Count", "recipe_name": "Recipe Name", "message": "Error Message",
    "frequency": "Frequency", "error_limit": "Error Limit", "recipe_id": "Recipie Id", "job_url": "Job URL",
    "job_id": "Job Id", "email": "Email", "source": "Source System", "source_obj": "Source Object",
    "target": "Target System", "target_obj": "Target Object", "file_url": "Error File Sharable URL",
}
COLUMN_FALLBACKS = {"recipe_id": ("recipe_id",), "ts": ("error_time", "timestamp"),
                    "message": ("error_details", "error"), "source": ("sourcesystem",), "target": ("targetsystem",)}

SECTION_HELP = (
    ("hero", "title, period, health score and grade, one-line headline"),
    ("kpis", "number tiles: errors, recipes affected, new patterns, records failed, reprocessed, backlog, forecast"),
    ("insights", "what stands out, in plain words (an AI summary on top when azure_api_key is set)"),
    ("trend", "errors per day for daily_days days, spikes marked, next period's forecast"),
    ("weekly", "errors per period over trend_periods periods, with the forecast"),
    ("recipes", "top failing recipes: errors, change, sparkline, share, main error, status"),
    ("movers", "rising, easing, new this period, gone quiet"),
    ("patterns", "top error patterns (ids and numbers taken out), new ones flagged"),
    ("categories", "error categories, this period against the one before"),
    ("systems", "target and source systems, source > target routes as a heat grid, objects"),
    ("heatmap", "when errors happen: weekday x hour of day"),
    ("calendar", "every day of the trend window as a heat calendar"),
    ("records", "batch runs: records processed and failed, by object"),
    ("recovery", "what happened to the errors: notified, reprocessed, failed again, waiting"),
    ("backlog", "deferred errors (Status Created) still waiting for the summary email"),
    ("noise", "how concentrated the alerts are, alerts per recipient list"),
    ("forecast", "next period, overall and per top recipe, at-risk recipes"),
    ("actions", "buttons: error log, runbook, dashboard, your own"),
)
DEFAULT_SECTIONS = tuple(name for name, _ in SECTION_HELP)
DETAIL_PRESETS = {
    "brief": ("hero", "kpis", "insights", "trend", "recipes", "actions"),
    "standard": ("hero", "kpis", "insights", "trend", "recipes", "movers", "patterns", "systems", "heatmap",
                 "actions"),
    "full": tuple(n for n in DEFAULT_SECTIONS if n != "forecast"),
}
SECTION_ALIASES = {"header": "hero", "tiles": "kpis", "summary": "insights", "daily": "trend", "chart": "trend",
                   "weeks": "weekly", "top": "recipes", "pattern": "patterns", "errors": "patterns",
                   "category": "categories", "system": "systems", "hours": "heatmap", "days": "calendar",
                   "batch": "records", "reprocess": "recovery", "deferred": "backlog", "pareto": "noise",
                   "outlook": "forecast", "buttons": "actions", "links": "actions"}
# What goes, in this order, when the email is over html_limit_kb ("lists" = lists cut to 6 rows). html_full keeps all.
TRIM_ORDER = ("calendar", "noise", "recovery", "lists", "records", "categories", "weekly", "heatmap", "backlog", "movers")

# Every setting: (name, kind, default[, min, max]). Kinds: str, secret, bool, int, float, color. Each is an
# input of the step AND a key of config_json, except those in CONFIG_ONLY. Blank falls back to config_json,
# then to the default.
SETTINGS = (
    ("workato_api_token", "secret", ""),
    ("azure_api_key", "secret", ""),
    ("to_email", "str", ""),
    ("title", "str", "Workato Integrations Health"),
    ("subtitle", "str", ""),
    ("note", "str", ""),
    ("env", "str", "PROD"),
    ("detail", "str", "full"),
    ("sections", "str", ""),
    ("show_sections", "str", ""),
    ("hide_sections", "str", ""),
    ("timezone", "str", "America/Los_Angeles"),
    ("period", "str", "rolling"),
    ("period_days", "int", 7, 1, 31),
    ("period_end", "str", ""),
    ("include_today", "bool", False),
    ("week_start", "str", "monday"),
    ("trend_periods", "int", 13, 2, 52),
    ("daily_days", "int", 91, 7, 120),
    ("heatmap_periods", "int", 13, 1, 52),
    ("top_n", "int", 10, 3, 30),
    ("patterns_n", "int", 8, 3, 25),
    ("movers_n", "int", 5, 2, 15),
    ("systems_n", "int", 8, 3, 20),
    ("max_insights", "int", 8, 0, 15),
    ("include_recipes", "str", ""),
    ("exclude_recipes", "str", ""),
    ("include_systems", "str", ""),
    ("include_emails", "str", ""),
    ("exclude_statuses", "str", ""),
    ("merge_system_names", "bool", True),
    ("mask_emails", "bool", True),
    ("show_examples", "bool", True),
    ("forecast", "bool", False),
    ("forecast_method", "str", "holt"),
    ("spike_z", "float", 3.5, 1.5, 10.0),
    ("rising_pct", "int", 50, 10, 1000),
    ("min_change", "int", 5, 1, 1000),
    ("chronic_periods", "int", 6, 2, 52),
    ("health_score", "bool", True),
    ("recipe_status", "bool", True),
    ("ai", "bool", True),
    ("azure_url", "str", AZURE_URL),
    ("ai_temperature", "float", 0.2, 0.0, 1.0),
    ("ai_max_tokens", "int", 900, 200, 2000),
    ("ai_redact", "bool", True),
    ("ai_instructions", "str", ""),
    ("subject_format", "str", "{emoji} {title} · {period} · {errors} errors ({change})"),
    ("skip_if_empty", "bool", False),
    ("brand_color", "color", "#0056D2"),
    ("max_width", "int", 920, 600, 1400),
    ("hover_effects", "bool", True),
    ("hover_row_color", "color", "#EEF4FF"),
    ("logo_url", "str", ""),
    ("workato_logo_url", "str", ""),
    ("team_logo_url", "str", ""),
    ("team_name", "str", ""),
    ("alert_email", "str", ""),
    ("error_log_url", "str", ""),
    ("runbook_url", "str", ""),
    ("dashboard_url", "str", ""),
    ("servicenow_url", "str", ""),
    ("slack_url", "str", ""),
    ("charter_url", "str", TEAM_CHARTER_URL),
    ("data_table_id", "str", ERROR_TABLE_ID),
    ("workato_api_base", "str", WORKATO_API),
    ("page_size", "int", 200, 10, 1000),
    ("parallel_queries", "int", 4, 1, 8),
    ("max_rows", "int", 60000, 500, 300000),
    ("time_budget", "int", 80, 10, 85),
    ("http_timeout", "int", 20, 3, 60),
    ("html_limit_kb", "int", 100, 0, 5000),
    ("rows_json", "str", ""),
    ("config_json", "str", ""),
    ("now", "str", ""),
    ("data_tables_base", "str", DATA_TABLES_API),
    ("app_host", "str", APP_HOST),
)
CONFIG_ONLY = {"data_tables_base", "app_host"}
CHOICES = {"detail": ("brief", "standard", "full"), "period": ("rolling", "calendar"),
           "forecast_method": ("holt", "average", "naive"),
           "week_start": ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}
INPUT_NAMES = tuple(s[0] for s in SETTINGS if s[0] not in CONFIG_ONLY)

# Label and hint of each input, for the schema file (--write-schemas).
INPUT_HELP = {
    "workato_api_token": ("Workato API token", "Reads the error log data table and the state of the top recipes"),
    "azure_api_key": ("Azure OpenAI key", "Optional: an AI-written executive summary. Blank = the built-in insights only"),
    "to_email": ("To email", "Passed through to the to_email output (blank = alert_email)"),
    "title": ("Title", "Default: Workato Integrations Health"),
    "subtitle": ("Subtitle", "A line under the title"),
    "note": ("Note", "A message shown in a box under the header (simple HTML allowed), e.g. a maintenance window"),
    "env": ("Environment", "PROD, DEV, ... shown on the dashboard. Default PROD"),
    "detail": ("Detail", "brief, standard or full (default). Picks the set of sections"),
    "sections": ("Sections", "The exact sections, in order, comma separated. Blank = the detail set. Names: "),
    "show_sections": ("Show sections", "Sections to add to the detail set"),
    "hide_sections": ("Hide sections", "Sections to leave out"),
    "timezone": ("Timezone", "Decides what 'yesterday' and the hour of day are. Default America/Los_Angeles"),
    "period": ("Period", "rolling (default): the last period_days full days. calendar: the last complete week from week_start"),
    "period_days": ("Period length (days)", "Default 7"),
    "period_end": ("Period end", "YYYY-MM-DD: the last day of the period. Blank = yesterday"),
    "include_today": ("Include today", "Rolling period ends today instead of yesterday. Default no"),
    "week_start": ("Week starts on", "For period = calendar. Default monday"),
    "trend_periods": ("Trend length (periods)", "How many periods the trend and baselines use. Default 13 (91 days)"),
    "daily_days": ("Daily chart (days)", "Days in the daily chart. Default 91"),
    "heatmap_periods": ("Heatmap length (periods)", "Periods in the weekday x hour heatmap. Default 13 (91 days)"),
    "top_n": ("Top recipes", "Rows in the top failing recipes table. Default 10"),
    "patterns_n": ("Top patterns", "Rows in the error patterns table. Default 8"),
    "movers_n": ("Movers per list", "Default 5"),
    "systems_n": ("Systems per list", "Default 8"),
    "max_insights": ("Max insights", "Default 8. 0 = none"),
    "include_recipes": ("Only these recipes", "Recipe ids or parts of names, comma separated. Blank = all"),
    "exclude_recipes": ("Leave out recipes", "Recipe ids or parts of names, comma separated"),
    "include_systems": ("Only these systems", "Parts of source or target system names, comma separated"),
    "include_emails": ("Only these recipients", "Rows whose Email contains one of these, comma separated"),
    "exclude_statuses": ("Leave out statuses", "e.g. Reprocessed"),
    "merge_system_names": ("Merge system names", "SFDC_Services, SFDC Services -> Salesforce Services. Default yes"),
    "mask_emails": ("Mask emails", "Show only team addresses (alert_email, config public_emails). Default yes"),
    "show_examples": ("Show error examples", "The latest message of each pattern. Default yes"),
    "forecast": ("Forecast", "Predict the next period (forecast section, tile, chart bars). Default no"),
    "forecast_method": ("Forecast method", "holt (default: damped trend), average (last 4 periods) or naive (last period)"),
    "spike_z": ("Spike sensitivity", "A day is a spike above median + this many robust deviations. Default 3.5"),
    "rising_pct": ("Rising threshold (%)", "A recipe is rising when up this much on the period before. Default 50"),
    "min_change": ("Minimum change", "Ignore changes smaller than this many errors. Default 5"),
    "chronic_periods": ("Chronic after (periods)", "Failing in this many of the last 8 periods = chronic. Default 6"),
    "health_score": ("Health score", "Show the 0-100 score and grade. Default yes"),
    "recipe_status": ("Recipe status", "Ask Workato if the top recipes are running and when they changed. Default yes"),
    "ai": ("AI summary", "Use Azure when azure_api_key is set. Default yes"),
    "azure_url": ("Azure URL", "Chat completions URL of the deployment"),
    "ai_temperature": ("AI temperature", "Default 0.2"),
    "ai_max_tokens": ("AI max tokens", "Default 900"),
    "ai_redact": ("Redact for AI", "Take emails, URLs, ids and long numbers out before Azure sees them. Default yes"),
    "ai_instructions": ("AI instructions", "Extra notes for the AI, e.g. what the team cares about"),
    "subject_format": ("Subject format", "Placeholders: {emoji} {title} {env} {period} {errors} {previous} {change} "
                                         "{score} {grade} {recipes} {new_patterns} {forecast}"),
    "skip_if_empty": ("Skip if no errors", "send_email = false when the period has no errors. Default no"),
    "brand_color": ("Brand color", "Default #0056D2"),
    "max_width": ("Max width (px)", "Default 920"),
    "hover_effects": ("Hover effects", "Cards lift, rows tint, pills deepen, bars dim under the mouse. Default yes"),
    "hover_row_color": ("Hover row colour", "The colour a row turns under the mouse. Default #EEF4FF"),
    "logo_url": ("Logo URL", "The Coursera logo. Blank = the word coursera"),
    "workato_logo_url": ("Workato logo URL", "Shown next to the Coursera logo. Blank = no Workato logo"),
    "team_logo_url": ("Team logo URL", "Shown after the Coursera (and Workato) logo, and in the footer"),
    "team_name": ("Team name", ""),
    "alert_email": ("Alert email", "Team address: footer Email link, never masked"),
    "error_log_url": ("Error log URL", "Blank = the data table in Workato"),
    "runbook_url": ("Runbook URL", ""),
    "dashboard_url": ("Dashboard URL", "A live dashboard to link to"),
    "servicenow_url": ("ServiceNow URL", ""),
    "slack_url": ("Slack URL", ""),
    "charter_url": ("Team charter URL", ""),
    "data_table_id": ("Data table id", "Default: Error Notification - TBL"),
    "workato_api_base": ("Workato API base", "Default https://www.workato.com/api"),
    "page_size": ("Page size", "Rows per data table page. The API documents 200 (default); up to 1000 is tried, and 200 is used again if the API refuses it"),
    "parallel_queries": ("Parallel queries", "Periods fetched at the same time. Default 4"),
    "max_rows": ("Max rows", "Stop reading after this many rows. Default 60000"),
    "time_budget": ("Time budget (s)", "All lookups share it. Default 80"),
    "http_timeout": ("HTTP timeout (s)", "Default 20"),
    "html_limit_kb": ("HTML limit (KB)", "Gmail clips mail over ~102 KB: lists get shorter, then sections drop. 0 = no limit"),
    "rows_json": ("Rows JSON", "Testing: the table's rows as a JSON list, instead of reading the table"),
    "config_json": ("Config JSON", "Any setting above, plus table_columns, system_aliases, category_rules, titles, "
                                   "buttons, recipe_owners, known_issues, public_emails, score_weights, heat_colors"),
    "now": ("Now (testing)", "ISO time to build the dashboard as. Leave blank"),
}

OUTPUT_DEFAULTS = (
    ("ok", False), ("error", ""), ("warnings", []), ("version", VERSION),
    ("html", ""), ("html_full", ""), ("subject", ""), ("preheader", ""), ("text_body", ""), ("slack_text", ""),
    ("send_email", False), ("to_email", ""),
    ("period_label", ""), ("period_start", ""), ("period_end", ""), ("previous_start", ""), ("previous_end", ""),
    ("errors_total", 0), ("errors_previous", 0), ("change_pct", None), ("recipes_affected", 0),
    ("recipes_affected_previous", 0), ("new_patterns", 0), ("records_failed", 0), ("reprocessed", 0),
    ("backlog_open", 0), ("backlog_oldest_days", 0), ("spikes", 0),
    ("health_score", None), ("health_grade", ""),
    ("forecast_next", None), ("forecast_low", None), ("forecast_high", None), ("forecast_trend", ""),
    ("top_recipes", []), ("top_patterns", []), ("insights", []), ("ai_used", False), ("ai_error", ""),
    ("rows_read", 0), ("rows_used", 0), ("pages_read", 0), ("data_complete", True),
    ("sections_rendered", []), ("html_bytes", 0), ("elapsed_ms", 0), ("summary_json", ""),
)

# ------------------------------------------------------------------------------ look

FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"
INK, TEXT, MUTED, FAINT = "#0F172A", "#334155", "#64748B", "#94A3B8"
LINE, SOFT, PANEL = "#E2E8F0", "#F8FAFC", "#F1F5F9"
GOOD, GOOD_SOFT, BAD, BAD_SOFT = "#15803D", "#F0FDF4", "#B91C1C", "#FEF2F2"
WARN, WARN_SOFT, INFO, INFO_SOFT = "#B45309", "#FFFBEB", "#1D4ED8", "#EFF6FF"
SPIKE = "#DC2626"
HEAT = ("#FEF3C7", "#FDE68A", "#FDBA74", "#F97316", "#DC2626", "#991B1B")
HEAT_ZERO = "#F1F5F9"
GRADES = (("A", 90, "#15803D", "#F0FDF4", "🟢"), ("B", 75, "#4D7C0F", "#F7FEE7", "🟢"),
          ("C", 60, "#B45309", "#FFFBEB", "🟡"), ("D", 40, "#C2410C", "#FFF7ED", "🟠"),
          ("F", 0, "#B91C1C", "#FEF2F2", "🔴"))
ENVIRONMENTS = {"PROD": ("Production", "#EEF1F4"), "DEV": ("Development", "#D1FAE5")}
ENV_ALIASES = {"PRODUCTION": "PROD", "PRD": "PROD", "DEVELOPMENT": "DEV"}
STATUS_COLORS = {"notified": "#3B82F6", "reprocessed": "#22C55E", "failed again": "#EF4444",
                 "created": "#F59E0B"}
TREND_PILLS = {"new": ("New", INFO, INFO_SOFT), "spike": ("Spike", BAD, BAD_SOFT),
               "rising": ("Rising", BAD, BAD_SOFT), "easing": ("Easing", GOOD, GOOD_SOFT),
               "chronic": ("Chronic", WARN, WARN_SOFT), "steady": ("Steady", MUTED, PANEL)}
TITLES = {
    "eyebrow": "{label} report",
    "kpis": "", "insights": "What stands out", "trend": "Errors per day", "weekly": "Errors per {unit}",
    "recipes": "Top failing recipes", "movers": "Movers", "patterns": "Top error patterns",
    "categories": "Error categories", "systems": "Systems", "heatmap": "When errors happen",
    "calendar": "Error calendar", "records": "Records in batch runs", "recovery": "What happened to the errors",
    "backlog": "Deferred errors waiting", "noise": "Alert load", "forecast": "Next {unit}", "actions": "",
}
SYSTEM_WORDS = {"saleforce": "Salesforce", "salesforce": "Salesforce", "sfdc": "Salesforce", "netsuite": "NetSuite",
                "servicenow": "ServiceNow", "snow": "ServiceNow", "s3": "S3", "eds": "EDS", "aws": "AWS"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# ------------------------------------------------------------------- classification

# The same categories as error_notification.py (test_error_dashboard checks they stay the same), so a pattern
# has the same name in an alert and on the dashboard. EXTRA_RULES go in front: messages seen in the error log
# that those rules leave unclassified. config_json "category_rules" goes in front of both.
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
UNKNOWN = ("unknown", "Unclassified", "❓")
SYSTEMIC = {"auth", "permission", "rate_limit", "timeout", "network", "server_error", "stopped_recipe", "record_lock"}
SYSTEMIC_ADVICE = {"auth": "Check the connection and the integration user.",
                   "permission": "Check the integration user's access.",
                   "rate_limit": "Check the API usage and the recipe's concurrency.",
                   "timeout": "Check the slowest steps and the batch sizes.",
                   "network": "Check the provider's status and any on-prem agent.",
                   "server_error": "Check the provider's status.", "stopped_recipe": "Start the called recipe again.",
                   "record_lock": "Look for jobs that update the same records at the same time."}

AI_SYSTEM = (
    "You write the executive summary of a weekly integration health dashboard for Coursera's IT Integrations team. "
    "The readers are the engineers who keep the Workato integrations running and their managers. Use ONLY the facts "
    "in the JSON you are given: never invent numbers, recipe names, dates, causes or owners, and don't present a guess "
    "as certain. Plain, specific, calm language; no emoji, no hype. Wrap recipe names in **double asterisks**.\n"
    "Return a JSON object with exactly these keys:\n"
    "headline: one sentence, at most 18 words: the state of the integrations this period.\n"
    "summary: 2-4 sentences, at most 90 words: what changed against the period before, what drove it, and whether "
    "it looks like it is getting better or worse.\n"
    "risks: array of 1-3 short strings: what is most likely to hurt next period if nobody acts.\n"
    "actions: array of 2-4 short imperative steps, most valuable first, each naming the recipe or pattern it is "
    "about.\n"
    "confidence: low, medium or high: how well the facts support the summary."
)

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
        return default if math.isnan(value) or math.isinf(value) else int(value)
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
        return default if isinstance(value, float) and (math.isnan(value) or math.isinf(value)) else float(value)
    text = text_of(value).strip().replace(",", "")
    try:
        return float(text) if text else default
    except ValueError:
        return default


def esc(value):
    return htmllib.escape(text_of(value), quote=True)


def clip(value, limit):
    text = text_of(value)
    if limit and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def fmt_int(value):
    try:
        return "{:,}".format(int(round(value)))
    except (TypeError, ValueError):
        return text_of(value)


def fmt_compact(value):
    """1234 -> 1.2k, 1234567 -> 1.2M: for tiles."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return text_of(value)
    for size, unit, div in ((1e6, "M", 1e6), (1e4, "k", 1e3)):
        if abs(value) >= size:
            return "{:.1f}{}".format(value / div, unit).replace(".0" + unit, unit)
    return fmt_int(value)


def pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


def fmt_pct(value, digits=0):
    if value is None:
        return "—"
    if digits == 0 and 0 < abs(value) < 1:
        return "<1%"
    return ("{:." + str(digits) + "f}%").format(value)


def change_pct(cur, prev):
    if not prev:
        return None
    return 100.0 * (cur - prev) / prev


def plural(count, word, many=None):
    return "{} {}".format(fmt_int(count), word if count == 1 else (many or word + "s"))


def css_color(value):
    text = text_of(value).strip()
    if re.match(r"^#?[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$", text):
        return text if text.startswith("#") else "#" + text
    if re.match(r"^[A-Za-z]{3,20}$", text):
        return text
    return ""


def hex6(value):
    text = text_of(value).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return text.upper() if re.match(r"^[0-9A-Fa-f]{6}$", text) else ""


def mix(a, b, share):
    """Colour a moved `share` (0..1) of the way to colour b, as #RRGGBB (a named colour comes back as it is)."""
    one, two = hex6(a), hex6(b)
    if not one or not two:
        return a
    one, two = [int(one[i:i + 2], 16) for i in (0, 2, 4)], [int(two[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join("{:02X}".format(int(round(x + (y - x) * share))) for x, y in zip(one, two))


def safe_url(value):
    url = text_of(value).strip()
    return url if re.match(r"(?i)^(https?://|mailto:)", url) else ""


def norm_key(name):
    return re.sub(r"[^a-z0-9]+", "_", text_of(name).lower()).strip("_")


def split_list(value):
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = re.split(r"[,;\n]+", text_of(value))
    return [text_of(x).strip() for x in items if text_of(x).strip()]


class SafeDict(dict):
    def __missing__(self, key):
        return ""


def fill(template, values):
    try:
        return text_of(template).format_map(SafeDict(values))
    except (ValueError, IndexError, KeyError):
        return text_of(template)


def median(values):
    data = sorted(values)
    n = len(data)
    if not n:
        return 0.0
    mid = n // 2
    return float(data[mid]) if n % 2 else (data[mid - 1] + data[mid]) / 2.0


def mean(values):
    values = list(values)
    return sum(values) / float(len(values)) if values else 0.0


def robust_sd(values):
    """1.4826 x the median absolute deviation, never below a Poisson-like floor."""
    med = median(values)
    mad = median([abs(v - med) for v in values])
    return max(1.4826 * mad, math.sqrt(max(med, 1.0)))


# ----------------------------------------------------------------- html and text

_BREAKS = re.compile(r"(?i)<\s*(br|/p|/div|/li|/tr|/h[1-6]|/table|hr)\b[^>]*>")
_OPENERS = re.compile(r"(?i)<\s*(p|div|li|tr|h[1-6])\b[^>]*>")
_TAG = re.compile(r"<[^>]+>")


def html_to_lines(value):
    """The visible text of an HTML fragment, one entry per paragraph or line."""
    text = text_of(value)
    if "<" not in text and "&" not in text:
        lines = (re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n"))
        return [line for line in lines if line]
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
    """Keeps simple formatting (for the `note` input) and drops everything risky."""
    ALLOWED = {"p", "br", "b", "strong", "i", "em", "u", "a", "ul", "ol", "li", "span", "code", "small"}
    VOID = {"br"}
    DROP = {"script", "style", "head", "title", "iframe", "object", "embed", "noscript", "template", "svg",
            "math", "form", "textarea", "select", "button"}

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
        kept = ""
        if tag == "a":
            href = next((v for k, v in attrs if (k or "").lower() == "href" and safe_url(v)), "")
            kept = ' href="{}" target="_blank" style="color:#0056D2"'.format(esc(href)) if href else ""
        self.out.append("<{}{}>".format(tag, kept))
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
    except Exception:  # noqa: BLE001 - a broken fragment is shown as text
        return esc(plain(value))


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL_RE = re.compile(r"https?://[^\s<>\"']+")


def redact(text):
    """For anything sent to Azure: no emails, URLs, Salesforce ids or long numbers."""
    text = EMAIL_RE.sub("<email>", text_of(text))
    text = URL_RE.sub(lambda m: "<url:{}>".format(urllib_parse.urlsplit(m.group()).netloc), text)
    text = re.sub(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?\b", "<id>", text)
    return re.sub(r"\d{6,}", "<num>", text)


def mask_emails(text, keep=()):
    keep = {k.lower() for k in keep}

    def one(match):
        address = match.group()
        return address if address.lower() in keep else "•••@" + address.split("@", 1)[1]
    return EMAIL_RE.sub(one, text_of(text))


def fingerprint_plain(text):
    """The error with the variable parts taken out, so the same error matches across runs (as
    error_notification.fingerprint_text, from text that is already plain)."""
    t = text_of(text).lower()
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


def category_rules(extra):
    rules = []
    for rule in (extra.get("category_rules") or []):
        if isinstance(rule, dict) and rule.get("key") and rule.get("patterns"):
            patterns = rule["patterns"] if isinstance(rule["patterns"], (list, tuple)) else [rule["patterns"]]
            rules.append((text_of(rule["key"]), text_of(rule.get("label") or rule["key"]),
                          text_of(rule.get("icon") or "❓"), tuple(text_of(p) for p in patterns)))
    labels = {key: (label, icon) for key, label, icon, _ in CATEGORIES}
    labels.update({key: (label, icon) for key, label, icon, _ in EXTRA_RULES if label})
    labels.update({key: (label, icon) for key, label, icon, _ in rules})
    compiled = []
    for key, _, _, patterns in tuple(rules) + EXTRA_RULES + CATEGORIES:
        regs = []
        for pattern in patterns:
            try:
                regs.append(re.compile(pattern, re.I))
            except re.error:
                continue
        compiled.append((key, regs))
    return {"rules": compiled, "labels": labels}


def classify(text, rules):
    if not text:
        return "unknown"
    for key, regs in rules["rules"]:
        for reg in regs:
            if reg.search(text):
                return key
    return "unknown"


def category_info(key, rules):
    return rules["labels"].get(key) or (UNKNOWN[1], UNKNOWN[2])


BATCH_TOTAL = re.compile(r"(?i)(?:total records?|records? total)\s*:?\s*(\d[\d,]*)|retrieved\s+(\d[\d,]*)\s+\w+")
BATCH_FAILED = re.compile(r"(?i)(?:failed records?|records? failed|failed count)\s*:?\s*(\d[\d,]*)"
                          r"|failed to synchroni[sz]e\s+(\d[\d,]*)")
BATCH_OBJECT = re.compile(r"(?i)\bobject\s*:\s*([A-Za-z][\w.]*)")


def parse_batch(text):
    """(total, failed, object) from a batch summary such as 'Object:Lead Total Records: 120 Failed Records: 3'."""
    total = failed = None
    match = BATCH_TOTAL.search(text)
    if match:
        total = to_int(match.group(1) or match.group(2))
    match = BATCH_FAILED.search(text)
    if match:
        failed = to_int(match.group(1) or match.group(2))
    obj = BATCH_OBJECT.search(text)
    if total is not None and failed is not None and failed > total:
        total = None
    return total, failed, (obj.group(1) if obj else "")


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


_ISO_FRACTION = re.compile(r"^(.*\.)(\d{1,5})([+-]\d{2}:\d{2})?$")


def parse_dt(value, tz):
    """A datetime in tz from ISO text, 'YYYY-MM-DD HH:MM:SS.fff' (read as tz), epoch seconds or a datetime."""
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
        match = _ISO_FRACTION.match(text)
        if match:  # pad fractions to 6 digits for older fromisoformat
            text = match.group(1) + match.group(2).ljust(6, "0") + (match.group(3) or "")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        if isinstance(tz, _USPacific):
            dt = PACIFIC.fromutc((dt - PACIFIC.utcoffset(dt)).replace(tzinfo=PACIFIC))
        else:
            dt = dt.replace(tzinfo=tz)
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


def hour_label(hour):
    return "{} {}".format(hour % 12 or 12, "AM" if hour < 12 else "PM")


def short_day(d):
    return "{} {}".format(d.day, d.strftime("%b"))


def day_name(d):
    return "{} {}".format(d.strftime("%a"), short_day(d))


def range_label(start, end, year=True):
    """13–19 Nov 2026, 28 Oct – 3 Nov 2026, 28 Dec 2026 – 3 Jan 2027."""
    tail = " {}".format(end.year) if year else ""
    if start == end:
        return short_day(end) + tail
    if start.year != end.year:
        return "{} {} – {}{}".format(short_day(start), start.year, short_day(end), tail)
    if start.month == end.month:
        return "{}–{} {}{}".format(start.day, end.day, end.strftime("%b"), tail)
    return "{} – {}{}".format(short_day(start), short_day(end), tail)


def rel_age(days):
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return "{} days ago".format(days)


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
    for name, options in CHOICES.items():
        default = next(s[2] for s in SETTINGS if s[0] == name)
        cfg[name] = cfg[name].strip().lower()
        if cfg[name] not in options:
            warnings.append("{} '{}' is not one of {}, so {} was used".format(name, cfg[name], ", ".join(options), default))
            cfg[name] = default
    cfg["extra"] = extra
    return cfg, warnings


def resolve_sections(cfg, warnings):
    def names(text):
        out = []
        for part in re.split(r"[,\s;|]+", text_of(text).lower()):
            if part:
                out.append(SECTION_ALIASES.get(part, part))
        return out
    explicit, added, hidden = names(cfg["sections"]), names(cfg["show_sections"]), names(cfg["hide_sections"])
    if explicit:
        wanted = explicit + [n for n in added if n not in explicit]
    else:
        wanted = [n for n in DEFAULT_SECTIONS if n in DETAIL_PRESETS[cfg["detail"]] or n in added]
    unknown = [n for n in explicit + added + hidden if n not in DEFAULT_SECTIONS]
    if unknown:
        warnings.append("unknown sections ignored: {}".format(", ".join(sorted(set(unknown)))))
    order = []
    for name in wanted:
        if name in DEFAULT_SECTIONS and name not in hidden and name not in order:
            order.append(name)
    return order


def resolve_period(cfg, now, warnings):
    """The period being reported on, the one before it, and the trend buckets (oldest first, the period last)."""
    today = now.date()
    days = cfg["period_days"]
    end = None
    if cfg["period_end"]:
        end = parse_date(cfg["period_end"])
        if end is None:
            warnings.append("period_end '{}' is not YYYY-MM-DD, so it was ignored".format(cfg["period_end"]))
    if cfg["period"] == "calendar":
        if days != 7:
            warnings.append("period = calendar always covers 7 days, so period_days was ignored")
        days = 7
        if end is None:
            first_day = WEEKDAYS.index(cfg["week_start"].capitalize())
            week_began = today - timedelta(days=(today.weekday() - first_day) % 7)
            end = week_began - timedelta(days=1)
    elif end is None:
        end = today if cfg["include_today"] else today - timedelta(days=1)
    count = cfg["trend_periods"]
    buckets = []
    for i in range(count):
        b_end = end - timedelta(days=days * (count - 1 - i))
        buckets.append(SimpleNamespace(start=b_end - timedelta(days=days - 1), end=b_end))
    start = buckets[-1].start
    daily_start = end - timedelta(days=cfg["daily_days"] - 1)
    unit = "week" if days == 7 else ("day" if days == 1 else "period")
    return SimpleNamespace(
        start=start, end=end, days=days, count=count, buckets=buckets, unit=unit,
        prev_start=start - timedelta(days=days), prev_end=start - timedelta(days=1),
        label=range_label(start, end), prev_label=range_label(start - timedelta(days=days), start - timedelta(days=1)),
        daily_start=daily_start, window_start=min(buckets[0].start, daily_start), window_end=end,
        next_start=end + timedelta(days=1), next_end=end + timedelta(days=days))


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
        return None, "{}: {}: {}".format(urllib_parse.urlsplit(url).netloc, type(exc).__name__, clip(str(exc), 200))
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
    """Rows of a data table query as {column name: value}. The API sends `schema` (meta fields, then fields) and
    `data` as positional arrays in the same two groups; records as objects are read too."""
    if not isinstance(body, dict):
        return []
    data = body.get("data") or body.get("records") or []
    if not isinstance(data, list):
        return []
    if data and isinstance(data[0], dict):
        return [row.get("document") if isinstance(row.get("document"), dict) else row for row in data]
    columns = [f.get("name") for group in body.get("schema", []) or [] for f in
               (group if isinstance(group, list) else [group]) if isinstance(f, dict)]
    rows = []
    for row in data:
        values = [v for group in row for v in (group if isinstance(group, list) else [group])] \
            if isinstance(row, list) else []
        rows.append(dict(zip(columns, values)))
    return rows


def next_token(body):
    """The continuation token of a query response, wherever the API put it."""
    if not isinstance(body, dict):
        return ""
    for key in ("continuation_token", "next_continuation_token", "next_page_token", "next_token"):
        if body.get(key):
            return text_of(body[key])
    for key in ("meta", "pagination", "page"):
        inner = body.get(key)
        if isinstance(inner, dict):
            for name, value in inner.items():
                if "token" in name and value:
                    return text_of(value)
    return ""


def columns_map(cfg):
    cols = dict(TABLE_COLUMNS)
    for field, name in (cfg["extra"].get("table_columns") or {}).items():
        if field in cols and text_of(name).strip():
            cols[field] = text_of(name).strip()
    return cols


class TableReader:
    """Reads the data table page by page. Thread safe: the period chunks run in parallel."""

    def __init__(self, cfg, warnings):
        self.cfg, self.warnings = cfg, warnings
        self.lock = threading.Lock()
        self.pages = self.rows_read = 0
        self.capped = False
        self.page_size = cfg["page_size"]
        self.cols = columns_map(cfg)
        self.url = "{}/{}/query".format(cfg["data_tables_base"].rstrip("/"), urllib_parse.quote(cfg["data_table_id"]))
        self.headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Content-Type": "application/json",
                        "Accept": "application/json"}

    def query(self, where, deadline, cap=None):
        """(rows, complete). Raises FetchError when the first page fails."""
        cfg = self.cfg
        select = list(dict.fromkeys(self.cols.values()))
        rows, token = [], ""
        while True:
            if remaining(deadline) < 1:
                return rows, False
            size = self.page_size
            payload = {"select": select, "limit": size}
            if where:
                payload["where"] = where
            if token:
                payload["continuation_token"] = token
            body, err = http_json("POST", self.url, self.headers, payload, call_timeout(cfg, deadline))
            if err and size > 200 and re.search(r" 4(00|22): ", err):
                with self.lock:            # the documented maximum is 200 rows a page
                    if self.page_size > 200:
                        self.page_size = 200
                        self.warnings.append("the data table refused {} rows a page, so 200 were read a page".format(size))
                continue
            if err:
                if rows:
                    self.warnings.append("a data table page failed, so a chunk is incomplete: " + clip(err, 200))
                    return rows, False
                raise FetchError(err)
            page = decode_rows(body)
            rows.extend(page)
            with self.lock:
                self.pages += 1
                self.rows_read += len(page)
                over = self.rows_read >= cfg["max_rows"]
            token = next_token(body)
            if not token or not page:
                if page and len(page) >= size:
                    self.warnings.append("a full page came back without a continuation token, so a chunk may be cut")
                    return rows, False
                return rows, True
            if over or (cap and len(rows) >= cap):
                with self.lock:
                    if over and not self.capped:
                        self.capped = True
                        self.warnings.append("stopped reading at max_rows ({}), so older data is missing".format(
                            fmt_int(cfg["max_rows"])))
                return rows, False


def fetch_rows(ctx, deadline, warnings, want_backlog):
    """The rows of the whole window (one query per period, newest first, a few at a time) and the backlog rows."""
    cfg, per = ctx.cfg, ctx.period
    reader = TableReader(cfg, warnings)
    date_col, status_col = reader.cols["date"], reader.cols["status"]

    def between(a, b):
        return {"$and": [{date_col: {"$gte": a.isoformat()}}, {date_col: {"$lte": b.isoformat()}}]}
    chunks = [(b.start, b.end) for b in reversed(per.buckets)]
    if per.window_start < per.buckets[0].start:
        chunks.append((per.window_start, per.buckets[0].start - timedelta(days=1)))
    tasks = {"chunk:{}:{}".format(a, b): (between(a, b), None) for a, b in chunks}
    if want_backlog:
        tasks["backlog"] = ({status_col: {"$eq": "Created"}}, 5000)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(cfg["parallel_queries"], len(tasks))))
    futures = {name: pool.submit(reader.query, where, deadline, cap) for name, (where, cap) in tasks.items()}
    concurrent.futures.wait(list(futures.values()), timeout=max(0.5, remaining(deadline) + 1))
    rows, backlog, complete, refused, failed = [], None, True, 0, []
    for name, future in futures.items():
        if not future.done():
            complete = complete and name == "backlog"
            warnings.append("{} timed out".format(name.replace("chunk:", "rows ").replace(":", " to ")))
            continue
        try:
            got, done = future.result()
        except Exception as exc:  # noqa: BLE001
            if re.search(r" 4(00|22): ", str(exc)):
                refused += 1
            failed.append("{}: {}".format(name.replace("chunk:", "rows ").replace(":", " to "), clip(str(exc), 200)))
            if name != "backlog":
                complete = False
            continue
        if name == "backlog":
            backlog = got
        else:
            rows.extend(got)
            complete = complete and done
    pool.shutdown(wait=False)
    if refused and refused >= len(chunks):
        # The date filter was refused: read the table without a filter (newest pages are not guaranteed first)
        warnings.append("the data table refused the date filter, so the table was read without one")
        try:
            rows, done = reader.query(None, deadline)
            complete, failed = done, []
            backlog = backlog if backlog is not None else rows
        except FetchError as exc:
            failed.append("rows: " + clip(str(exc), 200))
    for line in failed[:4]:
        warnings.append("data table query failed: " + line)
    if failed and not rows:
        raise FetchError(failed[0])
    return rows, backlog, complete, reader


def load_rows_json(value):
    data = value
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except ValueError:
            return None
    if isinstance(data, dict):
        data = data.get("rows") or data.get("records") or data.get("data") or []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else None


def workato_get(cfg, path, deadline):
    url = cfg["workato_api_base"].rstrip("/") + path
    headers = {"Authorization": "Bearer " + cfg["workato_api_token"], "Accept": "application/json"}
    body, err = http_json("GET", url, headers, None, call_timeout(cfg, deadline))
    if err:
        raise FetchError(err)
    if isinstance(body, dict) and isinstance(body.get("result"), dict):
        return body["result"]
    return body if isinstance(body, dict) else {}


def fetch_recipe_status(ctx, keys, deadline, warnings):
    """running / stopped, last change and version of the recipes in `keys`, from the Workato API, in parallel."""
    cfg = ctx.cfg
    ids = [ctx.recipes[k]["rid"] for k in keys if ctx.recipes[k]["rid"]][:20]
    if not ids:
        return {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(ids)))
    futures = {rid: pool.submit(workato_get, cfg, "/recipes/{}?exclude_code=yes".format(urllib_parse.quote(rid)), deadline)
               for rid in ids}
    concurrent.futures.wait(list(futures.values()), timeout=max(0.5, remaining(deadline)))
    out, failures = {}, []
    for rid, future in futures.items():
        if not future.done():
            failures.append("{}: timed out".format(rid))
            continue
        try:
            body = future.result()
        except Exception as exc:  # noqa: BLE001
            failures.append("{}: {}".format(rid, clip(str(exc), 120)))
            continue
        running = body.get("running")
        out[rid] = {"running": running if isinstance(running, bool) else None,
                    "updated_at": parse_dt(body.get("updated_at"), ctx.tz),
                    "last_run_at": parse_dt(body.get("last_run_at"), ctx.tz),
                    "version": to_int(body.get("version_no")), "stop_cause": text_of(body.get("stop_cause")),
                    "name": text_of(body.get("name"))}
    pool.shutdown(wait=False)
    if failures:
        warnings.append("recipe status lookup failed for {}: {}".format(plural(len(failures), "recipe"),
                                                                       "; ".join(failures[:3])))
    return out


# ------------------------------------------------------------------- the rows


def canon_system(raw, ctx):
    text = text_of(raw).strip()
    if not text:
        return ""
    cache = ctx.system_cache
    if text in cache:
        return cache[text]
    name = ctx.system_aliases.get(text.lower())
    if not name:
        if ctx.cfg["merge_system_names"]:
            words = [w for w in re.split(r"[_\s]+", text) if w]
            name = " ".join(SYSTEM_WORDS.get(w.lower(), w[:1].upper() + w[1:] if w.islower() else w) for w in words)
        else:
            name = text
    cache[text] = name
    return name


def matches_any(tokens, *values):
    hay = [text_of(v).lower() for v in values if text_of(v)]
    for token in tokens:
        t = token.lower()
        if any(t == v or t in v for v in hay):
            return True
    return False


def normalize_rows(raw_rows, ctx, window=True):
    """The table's rows as small dicts, filtered (window, include/exclude), classified and put in a bucket."""
    cfg, per, tz = ctx.cfg, ctx.period, ctx.tz
    cols = columns_map(cfg)
    keys = {f: [norm_key(cols[f])] + list(COLUMN_FALLBACKS.get(f, ())) for f in TABLE_COLUMNS}
    inc_r, exc_r = split_list(cfg["include_recipes"]), split_list(cfg["exclude_recipes"])
    inc_s, inc_e = split_list(cfg["include_systems"]), split_list(cfg["include_emails"])
    exc_status = {s.lower() for s in split_list(cfg["exclude_statuses"])}
    out = []
    for raw in raw_rows or []:
        if not isinstance(raw, dict):
            continue
        row = {norm_key(k): v for k, v in raw.items()}

        def get(field):
            for key in keys[field]:
                value = row.get(key)
                if value not in (None, ""):
                    return value
            return ""
        day = parse_date(get("date"))
        ts = None
        if day is None:
            ts = parse_dt(get("ts"), tz)
            day = ts.date() if ts else None
        if day is None:
            continue
        if window and not (per.window_start <= day <= per.window_end):
            continue
        status = text_of(get("status")).strip()
        if status.lower() in exc_status:
            continue
        name = text_of(get("recipe_name")).strip()
        job_url = safe_url(get("job_url"))
        rid = re.sub(r"\D", "", text_of(get("recipe_id")))
        if not rid:
            match = re.search(r"/recipes/(\d+)", job_url)
            rid = match.group(1) if match else ""
        if inc_r and not matches_any(inc_r, rid, name):
            continue
        if exc_r and matches_any(exc_r, rid, name):
            continue
        source, target = canon_system(get("source"), ctx), canon_system(get("target"), ctx)
        if inc_s and not matches_any(inc_s, source, target, get("source"), get("target")):
            continue
        email = text_of(get("email")).strip()
        if inc_e and not matches_any(inc_e, email):
            continue
        if ts is None:
            ts = parse_dt(get("ts"), tz)
        message = text_of(get("message"))
        info = ctx.msg_cache.get(message)
        if info is None:
            text = plain(message)
            total, failed, obj = parse_batch(text)
            info = (text, classify(text, ctx.rules), fingerprint_plain(text), total, failed, obj)
            ctx.msg_cache[message] = info
        text, category, fp, b_total, b_failed, b_obj = info
        offset = (per.end - day).days
        bucket = None
        if offset >= 0 and offset // per.days < per.count:
            bucket = per.count - 1 - offset // per.days
        out.append({
            "date": day, "ts": ts, "status": status, "flag": truthy(get("reprocess_flag")),
            "rcount": to_int(get("reprocess_count"), 0) or 0, "freq": to_int(get("frequency")),
            "limit": to_int(get("error_limit")), "rid": rid, "name": name or ("Recipe " + rid if rid else "Unnamed recipe"),
            "key": rid or "name:" + name.lower(), "msg": text, "cat": category, "fp": fp, "job_url": job_url,
            "email": email, "source": source, "target": target,
            "sobj": text_of(get("source_obj")).strip(), "tobj": text_of(get("target_obj")).strip(),
            "file": bool(safe_url(get("file_url"))), "btotal": b_total, "bfailed": b_failed, "bobj": b_obj,
            "b": bucket})
    return out


# ---------------------------------------------------------------------- analysis


def stamp_of(row):
    return (row["date"], row["ts"].timestamp() if row["ts"] else 0.0)


def is_chronic(weekly, cfg):
    recent = weekly[-8:]
    if len(recent) < 4 or not weekly[-1]:
        return False
    return sum(1 for x in recent if x) >= min(cfg["chronic_periods"], len(recent))


def trend_status(weekly, cfg):
    """new | spike | rising | easing | chronic | steady for something failing now; quiet | none otherwise."""
    cur = weekly[-1]
    prev = weekly[-2] if len(weekly) > 1 else 0
    history = weekly[:-1]
    if not cur:
        return "quiet" if prev else "none"
    if not any(history):
        return "new"
    recent = history[-8:]
    if len(recent) >= 3:
        usual = median(recent)
        if (cur >= usual + cfg["spike_z"] * robust_sd(recent) and cur - usual >= 2 * cfg["min_change"]
                and cur - prev >= cfg["min_change"]):
            return "spike"
    if cur - prev >= cfg["min_change"] and cur >= prev * (1 + cfg["rising_pct"] / 100.0):
        return "rising"
    if prev - cur >= cfg["min_change"] and cur <= prev * 0.5:
        return "easing"
    if is_chronic(weekly, cfg):
        return "chronic"
    return "steady"


def email_list(value, keep):
    """A recipient list as a stable key: lower case, sorted, duplicates and blanks out."""
    addresses = sorted(set(a.lower() for a in EMAIL_RE.findall(text_of(value))))
    return ", ".join(addresses) if addresses else "(no address)"


def lookup_map(mapping, *values):
    """The value of the first key of `mapping` that equals or is part of one of `values` (ids or names)."""
    if not isinstance(mapping, dict):
        return ""
    hay = [text_of(v).lower() for v in values if text_of(v)]
    for key, value in mapping.items():
        k = text_of(key).strip().lower()
        if k and any(k == h or k in h for h in hay):
            return text_of(value)
    return ""


def known_issue(ctx, *texts):
    """config_json known_issues: [{"match": "text or re:regex", "note": "...", "url": "..."}] -> the first match."""
    for issue in ctx.extra.get("known_issues") or []:
        if not isinstance(issue, dict) or not issue.get("match"):
            continue
        pattern = text_of(issue["match"])
        for text in texts:
            text = text_of(text)
            try:
                hit = re.search(pattern[3:], text, re.I) if pattern.startswith("re:") else pattern.lower() in text.lower()
            except re.error:
                hit = False
            if hit:
                return {"note": text_of(issue.get("note") or "Known issue"), "url": safe_url(issue.get("url"))}
    return None


def analyze(ctx):
    """Every number the dashboard shows, from ctx.rows (the window) and ctx.backlog_rows."""
    cfg, per = ctx.cfg, ctx.period
    count, cur = per.count, per.count - 1
    m = SimpleNamespace()
    m.weekly = [0] * count
    m.weekly_recipes = [set() for _ in range(count)]
    m.weekly_records = [0] * count
    m.weekly_reprocessed = [0] * count
    m.daily = Counter()
    recipes, patterns = {}, {}
    m.cats_cur, m.cats_prev = Counter(), Counter()
    m.tgt_cur, m.tgt_prev, m.src_cur, m.src_prev = Counter(), Counter(), Counter(), Counter()
    m.routes, m.obj_cur, m.obj_prev = Counter(), Counter(), Counter()
    m.status_cur, m.rcount_cur, m.recipients = Counter(), Counter(), Counter()
    m.flag_cur = m.files_cur = 0
    m.heat = [[0] * 24 for _ in range(7)]
    heat_from = per.end - timedelta(days=per.days * cfg["heatmap_periods"] - 1)
    m.heat_from = max(heat_from, per.window_start)
    m.batches = {}
    m.rec_total_cur = m.rec_failed_cur = m.rec_failed_prev = m.batch_runs_cur = 0
    for r in ctx.rows:
        m.daily[r["date"]] += 1
        if r["ts"] and m.heat_from <= r["date"] <= per.end:
            m.heat[r["ts"].weekday()][r["ts"].hour] += 1
        b = r["b"]
        if b is None:
            continue
        m.weekly[b] += 1
        m.weekly_recipes[b].add(r["key"])
        m.weekly_records[b] += r["bfailed"] or 0
        if r["status"].lower() == "reprocessed":
            m.weekly_reprocessed[b] += 1
        e = recipes.get(r["key"])
        if e is None:
            e = recipes[r["key"]] = {"key": r["key"], "rid": r["rid"], "name": r["name"], "weekly": [0] * count,
                                     "cats": Counter(), "cats_all": Counter(), "routes": Counter(), "fps": Counter(),
                                     "stamp": (date.min, 0.0), "last": None, "last_url": "", "first": r["date"],
                                     "statuses": Counter(), "rec_failed": 0}
        e["weekly"][b] += 1
        e["cats_all"][r["cat"]] += 1
        e["first"] = min(e["first"], r["date"])
        stamp = stamp_of(r)
        if stamp >= e["stamp"]:
            e["stamp"], e["name"], e["last"] = stamp, r["name"], r["ts"] or r["date"]
            e["last_url"] = r["job_url"] or e["last_url"]
        p = patterns.get(r["fp"])
        if p is None:
            p = patterns[r["fp"]] = {"fp": r["fp"], "sig": signature(r["fp"]), "weekly": [0] * count, "cat": r["cat"],
                                     "recipes": Counter(), "recipes_cur": Counter(), "example": r["msg"],
                                     "url": r["job_url"], "stamp": (date.min, 0.0), "first": r["date"], "last": r["date"],
                                     "keys": set()}
        p["weekly"][b] += 1
        p["recipes"][r["name"]] += 1
        p["keys"].add(r["key"])
        p["first"], p["last"] = min(p["first"], r["date"]), max(p["last"], r["date"])
        if stamp >= p["stamp"]:
            p["stamp"], p["example"], p["url"] = stamp, r["msg"], r["job_url"] or p["url"]
        obj = r["bobj"] or r["tobj"] or r["sobj"]
        if b == cur:
            e["cats"][r["cat"]] += 1
            e["routes"][(r["source"], r["target"])] += 1
            e["fps"][r["fp"]] += 1
            e["statuses"][r["status"] or "—"] += 1
            p["recipes_cur"][r["name"]] += 1
            m.cats_cur[r["cat"]] += 1
            m.tgt_cur[r["target"] or "Unknown"] += 1
            m.src_cur[r["source"] or "Unknown"] += 1
            m.routes[(r["source"] or "Unknown", r["target"] or "Unknown")] += 1
            if obj:
                m.obj_cur[obj] += 1
            m.status_cur[r["status"] or "Unknown"] += 1
            m.flag_cur += 1 if r["flag"] else 0
            m.files_cur += 1 if r["file"] else 0
            if r["rcount"]:
                m.rcount_cur[min(r["rcount"], 3)] += 1
            m.recipients[email_list(r["email"], ctx.public_emails)] += 1
            if r["bfailed"] is not None or r["btotal"] is not None:
                key = r["bobj"] or r["tobj"] or "Unknown object"
                batch = m.batches.setdefault(key, {"object": key, "runs": 0, "total": 0, "failed": 0,
                                                   "recipes": Counter(), "has_total": False})
                batch["runs"] += 1
                batch["total"] += r["btotal"] or 0
                batch["failed"] += r["bfailed"] or 0
                batch["has_total"] = batch["has_total"] or r["btotal"] is not None
                batch["recipes"][r["name"]] += 1
                e["rec_failed"] += r["bfailed"] or 0
                m.batch_runs_cur += 1
                m.rec_total_cur += r["btotal"] or 0
                m.rec_failed_cur += r["bfailed"] or 0
        elif b == cur - 1:
            m.cats_prev[r["cat"]] += 1
            m.tgt_prev[r["target"] or "Unknown"] += 1
            m.src_prev[r["source"] or "Unknown"] += 1
            if obj:
                m.obj_prev[obj] += 1
            m.rec_failed_prev += r["bfailed"] or 0
    for e in recipes.values():
        w = e["weekly"]
        e["cur"], e["prev"] = w[-1], (w[-2] if count > 1 else 0)
        e["status"] = trend_status(w, cfg)
        e["chronic"] = is_chronic(w, cfg)
        e["active"] = sum(1 for x in w[-8:] if x)
        cats = e["cats"] or e["cats_all"]
        e["cat"] = cats.most_common(1)[0][0] if cats else "unknown"
        e["route"] = e["routes"].most_common(1)[0][0] if e["routes"] else ("", "")
        e["owner"] = lookup_map(ctx.extra.get("recipe_owners"), e["rid"], e["name"])
        e["known"] = known_issue(ctx, e["name"])
    for p in patterns.values():
        p["cur"], p["prev"] = p["weekly"][-1], (p["weekly"][-2] if count > 1 else 0)
        p["status"] = trend_status(p["weekly"], cfg)
        p["known"] = known_issue(ctx, p["example"])
    ctx.recipes, ctx.patterns = recipes, patterns
    m.cur_n, m.prev_n = m.weekly[-1], (m.weekly[-2] if count > 1 else 0)
    m.change = change_pct(m.cur_n, m.prev_n)
    m.history = m.weekly[:-1][-8:]
    m.usual = median(m.history) if m.history else 0.0
    m.recipes_cur = len(m.weekly_recipes[-1])
    m.recipes_prev = len(m.weekly_recipes[-2]) if count > 1 else 0
    m.top = sorted((e for e in recipes.values() if e["cur"]), key=lambda e: (-e["cur"], -e["prev"], e["name"]))
    m.patterns_top = sorted((p for p in patterns.values() if p["cur"]), key=lambda p: (-p["cur"], -sum(p["weekly"])))
    m.new_patterns = [p for p in m.patterns_top if p["status"] == "new"]
    has_history = lambda e: any(e["weekly"][:-1])  # noqa: E731
    m.rising = sorted((e for e in recipes.values() if e["cur"] - e["prev"] >= cfg["min_change"] and has_history(e)),
                      key=lambda e: (-(e["cur"] - e["prev"]), e["name"]))
    m.easing = sorted((e for e in recipes.values() if e["cur"] and e["prev"] - e["cur"] >= cfg["min_change"]),
                      key=lambda e: (-(e["prev"] - e["cur"]), e["name"]))
    m.new_recipes = sorted((e for e in recipes.values() if e["status"] == "new"), key=lambda e: (-e["cur"], e["name"]))
    m.quiet = sorted((e for e in recipes.values() if not e["cur"] and e["prev"]), key=lambda e: (-e["prev"], e["name"]))
    m.chronic = sorted((e for e in recipes.values() if e["chronic"]), key=lambda e: (-sum(e["weekly"]), e["name"]))
    m.spikes = find_spikes(ctx, m)
    m.spikes_in_period = [s for s in m.spikes if per.start <= s["date"] <= per.end]
    m.systemic = Counter()
    for p in m.patterns_top:
        if p["cat"] in SYSTEMIC:
            m.systemic[p["cat"]] += p["cur"]
    m.backlog = analyze_backlog(ctx)
    m.pareto = pareto(m.top, m.cur_n)
    m.heat_peak = heat_peak(m.heat)
    m.forecast = forecast_all(ctx, m) if cfg["forecast"] else None
    m.score = health(ctx, m) if cfg["health_score"] else None
    return m


def find_spikes(ctx, m):
    """Days of the daily chart far above the 28 days before them (median + spike_z robust deviations)."""
    cfg, per = ctx.cfg, ctx.period
    out, day = [], per.daily_start
    while day <= per.end:
        count = m.daily.get(day, 0)
        base = [m.daily.get(day - timedelta(days=k), 0) for k in range(1, 29)
                if day - timedelta(days=k) >= per.window_start]
        if len(base) >= 7 and count >= 10:
            usual = median(base)
            if count >= 2 * usual and count > usual + cfg["spike_z"] * robust_sd(base):
                out.append({"date": day, "count": count, "usual": usual})
        day += timedelta(days=1)
    if out:
        days = {s["date"]: Counter() for s in out}
        for r in ctx.rows:
            if r["date"] in days:
                days[r["date"]][r["key"]] += 1
        for s in out:
            key, n = days[s["date"]].most_common(1)[0]
            s["recipe"] = ctx.recipes[key]["name"] if key in ctx.recipes else key
            s["share"] = pct(n, s["count"])
    return out


def analyze_backlog(ctx):
    """Deferred errors (Status Created): how many, how old, which recipes, which are past their notify window."""
    rows = ctx.backlog_rows
    if rows is None:
        return None
    today = ctx.today
    groups, overdue, oldest = {}, 0, None
    for r in rows:
        if r["status"].lower() != "created":
            continue
        age = (today - r["date"]).days
        due = r["freq"] if r["freq"] is not None else 7
        late = age > due
        overdue += 1 if late else 0
        oldest = max(oldest or 0, age)
        g = groups.setdefault(r["key"], {"name": r["name"], "rid": r["rid"], "count": 0, "oldest": 0, "overdue": 0,
                                         "freq": Counter(), "limit": Counter()})
        g["count"] += 1
        g["oldest"] = max(g["oldest"], age)
        g["overdue"] += 1 if late else 0
        g["freq"][r["freq"] if r["freq"] is not None else 7] += 1
        g["limit"][r["limit"] if r["limit"] is not None else 20] += 1
    total = sum(g["count"] for g in groups.values())
    top = sorted(groups.values(), key=lambda g: (-g["overdue"], -g["count"], g["name"]))
    return {"total": total, "overdue": overdue, "oldest": oldest or 0, "groups": top}


def pareto(top, total):
    if not total:
        return {"top3": 0.0, "k80": 0, "n": 0}
    running, k80 = 0, 0
    for i, e in enumerate(top):
        running += e["cur"]
        if running >= 0.8 * total:
            k80 = i + 1
            break
    return {"top3": pct(sum(e["cur"] for e in top[:3]), total), "k80": k80 or len(top), "n": len(top)}


def heat_peak(heat):
    """(start hour, share) of the busiest 3-hour window of the day, and the busiest cell."""
    by_hour = [sum(heat[d][h] for d in range(7)) for h in range(24)]
    total = sum(by_hour)
    if not total:
        return None
    start = max(range(24), key=lambda h: by_hour[h] + by_hour[(h + 1) % 24] + by_hour[(h + 2) % 24])
    share = pct(by_hour[start] + by_hour[(start + 1) % 24] + by_hour[(start + 2) % 24], total)
    cell = max(((d, h) for d in range(7) for h in range(24)), key=lambda c: heat[c[0]][c[1]])
    return {"start": start, "share": share, "total": total, "cell": cell, "cell_n": heat[cell[0]][cell[1]]}


# ---------------------------------------------------------------------- forecast


def winsorize(series):
    """Clip one-off spikes of the past (above median + 4 robust deviations) so a single bad period does not steer the
    forecast. The latest period is kept as it is: a problem that starts now is not a one-off."""
    if len(series) < 4:
        return list(series)
    history = series[:-1]
    cap = median(history) + 4 * robust_sd(history)
    return [min(v, cap) for v in history] + [series[-1]]


def holt(series):
    """Damped-trend exponential smoothing, parameters picked by the smallest one-step-ahead error.
    Returns (next value, residual sd)."""
    n = len(series)
    best = None
    span = min(3, n - 1)
    for alpha in (0.2, 0.35, 0.5, 0.7, 0.9):
        for beta in (0.05, 0.15, 0.3):
            for phi in (0.8, 0.9, 0.98):
                level, trend = series[0], (series[span] - series[0]) / float(span)
                errors = []
                for value in series[1:]:
                    guess = level + phi * trend
                    errors.append(value - guess)
                    new_level = alpha * value + (1 - alpha) * guess
                    trend = beta * (new_level - level) + (1 - beta) * phi * trend
                    level = new_level
                sse = sum(e * e for e in errors[1:]) if len(errors) > 1 else sum(e * e for e in errors)
                if best is None or sse < best[0]:
                    best = (sse, level + phi * trend, errors)
    _, point, errors = best
    used = errors[1:] if len(errors) > 1 else errors
    rmse = math.sqrt(sum(e * e for e in used) / float(len(used))) if used else 0.0
    return point, rmse


def forecast_series(series, method, min_change=5):
    """{point, low, high, trend, method} for the next period of `series` (oldest first)."""
    if not series:
        return None
    clean = winsorize(series)
    recent = clean[-4:]
    if method == "naive" or len(clean) < 2:
        point, spread = float(clean[-1]), robust_sd(clean[-8:]) if len(clean) > 2 else 0.0
        used = "naive" if method == "naive" else "average"
    elif method == "average" or len(clean) < 4:
        point, spread = mean(recent), robust_sd(clean[-8:]) if len(clean) > 2 else 0.0
        used = "average"
    else:
        point, spread = holt(clean)
        used = "holt"
    point = max(0.0, point)
    sd = max(spread, math.sqrt(max(point, 1.0)))
    level = mean(recent)
    if point > level * 1.1 and point - level >= min_change / 2.0:
        trend = "rising"
    elif point < level * 0.9 and level - point >= min_change / 2.0:
        trend = "easing"
    else:
        trend = "flat"
    return {"point": point, "low": max(0.0, point - 1.28 * sd), "high": point + 1.28 * sd, "trend": trend,
            "method": used}


def forecast_all(ctx, m):
    cfg, per = ctx.cfg, ctx.period
    overall = forecast_series(m.weekly, cfg["forecast_method"], cfg["min_change"])
    if not overall:
        return None
    # How the next period splits over its days: the median of each weekday over the last 8 periods
    days = [per.next_start + timedelta(days=i) for i in range(per.days)]
    weights = [1.0] * len(days)
    if per.days == 7:
        start = max(per.window_start, per.end - timedelta(days=7 * min(8, per.count) - 1))
        by_weekday = {w: [] for w in range(7)}
        day = start
        while day <= per.end:
            by_weekday[day.weekday()].append(m.daily.get(day, 0))
            day += timedelta(days=1)
        weights = [median(by_weekday[d.weekday()]) + 0.5 for d in days]
    total = sum(weights) or 1.0
    overall["daily"] = [(d, overall["point"] * w / total) for d, w in zip(days, weights)]
    per_recipe = []
    candidates = list(dict.fromkeys([e["key"] for e in m.top[: cfg["top_n"]]] + [e["key"] for e in m.rising[:5]]))
    for key in candidates:
        e = ctx.recipes[key]
        f = forecast_series(e["weekly"], cfg["forecast_method"], cfg["min_change"])
        if not f:
            continue
        f["recipe"] = e
        f["at_risk"] = f["point"] >= max(cfg["min_change"], e["cur"] * 1.25) and f["point"] - e["cur"] >= cfg["min_change"]
        per_recipe.append(f)
    per_recipe.sort(key=lambda f: -f["point"])
    overall["recipes"] = per_recipe
    return overall


# --------------------------------------------------------------------- the score

SCORE_WEIGHTS = {"volume": 35, "breadth": 10, "new_patterns": 15, "systemic": 10, "spikes": 15, "chronic": 5,
                 "backlog": 10}


def health(ctx, m):
    """0-100, against this table's own usual period: it starts at 100 and each part takes off up to its weight
    (config_json score_weights). volume: errors against the usual period (2x the usual takes it all); breadth: recipes
    failing against the usual; new_patterns: new patterns with 3+ errors (5 take it all); systemic: kinds of shared-cause
    errors with 3+ errors (3); spikes: spike days in the period (2); chronic: recipes failing most periods (10);
    backlog: deferred rows past their notify window (100)."""
    weights = dict(SCORE_WEIGHTS)
    for key, value in (ctx.extra.get("score_weights") or {}).items():
        if key in weights and to_float(value) is not None:
            weights[key] = max(0.0, to_float(value))
    unit = ctx.period.unit

    def clamp(x):
        return max(0.0, min(1.0, x))
    usual_recipes = median([len(s) for s in m.weekly_recipes[:-1][-8:]]) if len(m.weekly_recipes) > 1 else 0
    ratio = (m.cur_n + 1.0) / (m.usual + 1.0)
    breadth = (m.recipes_cur + 1.0) / (usual_recipes + 1.0)
    new = len([p for p in m.new_patterns if p["cur"] >= 3])
    systemic = len([c for c, n in m.systemic.items() if n >= 3])
    chronic = len([e for e in m.chronic if e["cur"]])
    overdue = (m.backlog or {}).get("overdue", 0)
    parts = [
        ("volume", clamp(ratio - 1.0), "{:.1f}× the usual {}".format(ratio, unit)),
        ("breadth", clamp(breadth - 1.0), "{} recipes failing (usually {})".format(m.recipes_cur, fmt_int(usual_recipes))),
        ("new_patterns", clamp(new / 5.0), plural(new, "new pattern")),
        ("systemic", clamp(systemic / 3.0), plural(systemic, "shared-cause error type")),
        ("spikes", clamp(len(m.spikes_in_period) / 2.0), plural(len(m.spikes_in_period), "spike day")),
        ("chronic", clamp(chronic / 10.0), plural(chronic, "chronic recipe")),
        ("backlog", clamp(overdue / 100.0), "{} overdue deferred".format(fmt_int(overdue))),
    ]
    taken = [(key, weights[key] * share, why) for key, share, why in parts]
    score = 100 if not m.cur_n and not overdue else int(round(max(0.0, 100 - sum(t for _, t, _ in taken))))
    grade = next(g for g in GRADES if score >= g[1])
    reasons = [(int(round(t)), why) for key, t, why in sorted(taken, key=lambda x: -x[1]) if round(t) >= 1]
    return {"score": score, "grade": grade[0], "color": grade[2], "soft": grade[3], "emoji": grade[4],
            "reasons": reasons, "parts": {key: round(t, 1) for key, t, _ in taken}}


# ---------------------------------------------------------------------- insights


def recipe_url(ctx, rid):
    return "{}/recipes/{}".format(ctx.cfg["app_host"].rstrip("/"), urllib_parse.quote(rid)) if rid else ""


def build_insights(ctx, m):
    """What stands out this period, most important first: [{icon, tone, html}]."""
    cfg, per = ctx.cfg, ctx.period
    unit, out = per.unit, []

    def add(icon, tone, html):
        out.append({"icon": icon, "tone": tone, "html": html})

    def name(e):
        return "<b>{}</b>".format(esc(clip(e["name"], 80)))
    if not m.cur_n:
        add("✅", "good", "No errors were logged this {} ({}).".format(unit, per.label))
    elif not m.prev_n:
        add("📈", "bad", "<b>{}</b> this {}, and none the {} before.".format(plural(m.cur_n, "error"), unit, unit))
    else:
        usual = (" A usual {} has about {}.".format(unit, fmt_int(m.usual))
                 if len(m.history) >= 3 and abs(m.usual - m.prev_n) > 0.1 * max(m.prev_n, 1) else "")
        both = "({} against {})".format(fmt_int(m.cur_n), fmt_int(m.prev_n))
        if m.change >= 10:
            add("📈", "bad" if m.change >= 25 else "warn",
                "Errors are <b>up {}</b> on the {} before {}.{}".format(fmt_pct(m.change), unit, both, usual))
        elif m.change <= -10:
            add("📉", "good", "Errors are <b>down {}</b> on the {} before {}.{}".format(
                fmt_pct(-m.change), unit, both, usual))
        else:
            add("➖", "info", "About as many errors as the {} before {}.{}".format(unit, both, usual))
    for s in m.spikes_in_period[:2]:
        add("⚡", "bad", "Spike on <b>{}</b>: {} errors against a usual ~{} a day; {} of them from <b>{}</b>.".format(
            day_name(s["date"]), fmt_int(s["count"]), fmt_int(s["usual"]), fmt_pct(s["share"]),
            esc(clip(s["recipe"], 80))))
    if m.systemic:
        cat, n = m.systemic.most_common(1)[0]
        label, icon = category_info(cat, ctx.rules)
        names = Counter()
        for p in m.patterns_top:
            if p["cat"] == cat:
                names.update(p["recipes_cur"])
        if n >= 3 or len(names) >= 2:
            add(icon, "bad", "<b>{}</b> errors ({}) hit {}: {}. {}".format(
                esc(label), fmt_int(n), plural(len(names), "recipe"),
                esc(", ".join(clip(x, 60) for x, _ in names.most_common(3))),
                "A shared cause (a connection, a limit or an outage) is likely." if len(names) >= 2
                else SYSTEMIC_ADVICE.get(cat, "Check the provider's status.")))
    if m.top and m.cur_n >= 10:
        e = m.top[0]
        share = pct(e["cur"], m.cur_n)
        if share >= 25:
            add("🎯", "warn", "{} caused <b>{}</b> of all errors ({}), mostly <i>{}</i>.".format(
                name(e), fmt_pct(share), fmt_int(e["cur"]), esc(category_info(e["cat"], ctx.rules)[0].lower())))
    if m.new_patterns:
        p = m.new_patterns[0]
        add("🆕", "warn", "<b>{}</b> this {} (not seen in the {} before). The biggest: “{}” in <b>{}</b> ({}×).".format(
            plural(len(m.new_patterns), "new error pattern"), unit, plural(per.count - 1, unit),
            esc(clip(shown_message(ctx, p["example"]), 110)),
            esc(clip(p["recipes_cur"].most_common(1)[0][0], 70)), fmt_int(p["cur"])))
    mentioned = {m.top[0]["key"]} if m.top and m.cur_n >= 10 and pct(m.top[0]["cur"], m.cur_n) >= 25 else set()
    for e in [x for x in m.rising if x["key"] not in mentioned][:1]:
        add("🔺", "bad", "{} rose from {} to {} errors.".format(name(e), fmt_int(e["prev"]), fmt_int(e["cur"])))
    changed = 0
    for e in m.top[: cfg["top_n"]]:
        st = ctx.status.get(e["rid"])
        if not st:
            continue
        if st["running"] is False:
            add("⏹️", "bad", "{} is <b>stopped</b> now{}.".format(
                name(e), ": " + esc(clip(st["stop_cause"], 120)) if st["stop_cause"] else ""))
        elif changed < 2 and st["updated_at"] and st["updated_at"].date() >= per.prev_start and e["cur"] > e["prev"]:
            changed += 1
            add("🛠️", "warn", "{} was changed on {}{}, and its errors went from {} to {}.".format(
                name(e), day_name(st["updated_at"].date()), " (version {})".format(st["version"]) if st["version"] else "",
                fmt_int(e["prev"]), fmt_int(e["cur"])))
    if m.chronic:
        e = m.chronic[0]
        add("♾️", "warn", "{} failed in {} of the last {} {}s ({} errors). A permanent fix would pay off.".format(
            name(e), e["active"], min(8, per.count), unit, fmt_int(sum(e["weekly"]))))
    bl = m.backlog
    if bl and bl["overdue"]:
        add("📥", "warn", "<b>{}</b> deferred errors (Status Created) are waiting for the summary email; {} are past "
            "their notify window, the oldest {} days. The summary recipe may not be running.".format(
                fmt_int(bl["total"]), fmt_int(bl["overdue"]), fmt_int(bl["oldest"])))
    if m.rec_failed_cur:
        big = max(m.batches.values(), key=lambda x: x["failed"])
        rate = " ({} of {} processed)".format(fmt_pct(pct(m.rec_failed_cur, m.rec_total_cur), 1),
                                              fmt_int(m.rec_total_cur)) if m.rec_total_cur else ""
        add("📦", "info", "<b>{}</b> failed in {}{}; most in <b>{}</b> ({}).".format(
            plural(m.rec_failed_cur, "record"), plural(m.batch_runs_cur, "batch run"), rate, esc(big["object"]),
            fmt_int(big["failed"])))
    hp = m.heat_peak
    if hp and hp["total"] >= 30 and hp["share"] >= 40:
        add("🕑", "info", "{} of the errors in the last {} happened between {} and {} {}.".format(
            fmt_pct(hp["share"]), plural(ctx.cfg["heatmap_periods"], unit), hour_label(hp["start"]),
            hour_label((hp["start"] + 3) % 24), tz_label(ctx.now)))
    if m.quiet:
        e = m.quiet[0]
        add("✅", "good", "{} that failed last {} had no errors this {}, e.g. {} ({} → 0).".format(
            plural(len(m.quiet), "recipe"), unit, unit, name(e), fmt_int(e["prev"])))
    f = m.forecast
    if f:
        add("🔮", "info", "Expect about <b>{}</b> errors next {} (likely {}–{}); the trend is {}.".format(
            fmt_int(f["point"]), unit, fmt_int(f["low"]), fmt_int(f["high"]), f["trend"]))
    return out[: cfg["max_insights"]]


def shown_message(ctx, text):
    """An error message as shown on the dashboard: one line, emails masked when mask_emails is on."""
    text = re.sub(r"\s+", " ", text_of(text)).strip() or "(no message)"
    return mask_emails(text, ctx.public_emails) if ctx.cfg["mask_emails"] else text


def headline(ctx, m):
    unit = ctx.period.unit
    if not m.cur_n:
        return "No errors this {}.".format(unit)
    text = "{} this {}".format(plural(m.cur_n, "error"), unit)
    if m.change is not None:
        text += ", {} {} on the {} before".format("up" if m.change >= 0 else "down", fmt_pct(abs(m.change)), unit)
    elif not m.prev_n:
        text += ", none the {} before".format(unit)
    text += ", across {}".format(plural(m.recipes_cur, "recipe"))
    if m.top:
        text += ". {} led with {}".format(clip(m.top[0]["name"], 70), fmt_int(m.top[0]["cur"]))
    return text + "."


# ---------------------------------------------------------------------------- AI


def ai_facts(ctx, m):
    r = redact if ctx.cfg["ai_redact"] else text_of
    unit = ctx.period.unit

    def recipe(e):
        return {"recipe": e["name"], "errors": e["cur"], "previous": e["prev"], "trend": e["status"],
                "main_error": category_info(e["cat"], ctx.rules)[0],
                "route": " -> ".join(x for x in e["route"] if x),
                "running": (ctx.status.get(e["rid"]) or {}).get("running")}
    facts = {
        "period": ctx.period.label, "unit": unit, "previous_period": ctx.period.prev_label,
        "errors": m.cur_n, "errors_previous": m.prev_n,
        "change_percent": round(m.change, 1) if m.change is not None else None,
        "usual_errors_per_{}".format(unit): m.usual, "recipes_affected": m.recipes_cur,
        "recipes_affected_previous": m.recipes_prev,
        "top_recipes": [recipe(e) for e in m.top[:8]],
        "top_patterns": [{"pattern": r(clip(p["example"], 220)), "errors": p["cur"], "previous": p["prev"],
                          "category": category_info(p["cat"], ctx.rules)[0], "trend": p["status"],
                          "recipes": [n for n, _ in p["recipes_cur"].most_common(3)]} for p in m.patterns_top[:6]],
        "new_patterns": len(m.new_patterns),
        "rising": [recipe(e) for e in m.rising[:3]], "gone_quiet": [e["name"] for e in m.quiet[:5]],
        "chronic": [{"recipe": e["name"], "periods_failing_of_last_8": e["active"]} for e in m.chronic[:3]],
        "spikes": [{"day": day_name(s["date"]), "errors": s["count"], "usual": s["usual"], "top_recipe": s["recipe"],
                    "top_recipe_share_percent": round(s["share"])} for s in m.spikes_in_period],
        "categories": {category_info(k, ctx.rules)[0]: v for k, v in m.cats_cur.most_common(8)},
        "target_systems": dict(m.tgt_cur.most_common(5)),
        "records_failed_in_batches": m.rec_failed_cur, "records_processed_in_batches": m.rec_total_cur,
        "statuses": dict(m.status_cur),
    }
    if m.backlog:
        facts["deferred_backlog"] = {"waiting": m.backlog["total"], "overdue": m.backlog["overdue"],
                                     "oldest_days": m.backlog["oldest"]}
    if m.forecast:
        facts["forecast_next_{}".format(unit)] = {k: round(m.forecast[k]) for k in ("point", "low", "high")}
        facts["forecast_next_{}".format(unit)]["trend"] = m.forecast["trend"]
    if m.score:
        facts["health_score"] = {"score": m.score["score"], "grade": m.score["grade"]}
    facts["rule_based_insights"] = [plain(i["html"]) for i in ctx.insights]
    return facts


def parse_ai_json(content):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text_of(content).strip())
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


def ai_summary(ctx, m, deadline, warnings):
    """Azure's executive summary, or None. A failed call (no answer, an HTTP error, a timeout, an answer that is not the
    JSON asked for, or anything raised while building the request) never stops the dashboard: it is written to
    ctx.ai_error and to `warnings`, and the dashboard goes out with the built-in insights only."""
    def fail(text):
        ctx.ai_error = clip(text, 300)
        warnings.append(ctx.ai_error)
        return None
    try:
        return ai_summary_call(ctx, m, deadline, fail)
    except Exception as exc:  # noqa: BLE001 - Azure must never be the reason the dashboard is not sent
        return fail("azure: {}: {}".format(type(exc).__name__, clip(str(exc), 200)))


def ai_summary_call(ctx, m, deadline, fail):
    cfg = ctx.cfg
    left = remaining(deadline)
    if left < 4:
        return fail("AI summary skipped: time budget used up")
    system = AI_SYSTEM
    if cfg["ai_instructions"]:
        system += "\nTeam notes (follow them): " + clip(cfg["ai_instructions"], 1500)
    payload = {"messages": [{"role": "system", "content": system},
                            {"role": "user", "content": json.dumps(ai_facts(ctx, m), default=str, ensure_ascii=False)}],
               "temperature": cfg["ai_temperature"], "max_tokens": cfg["ai_max_tokens"],
               "response_format": {"type": "json_object"}}
    headers = {"api-key": cfg["azure_api_key"], "Content-Type": "application/json"}
    body, err = http_json("POST", cfg["azure_url"], headers, payload, max(3, min(40, left)))
    if err:
        return fail("azure: " + err)
    try:
        data = parse_ai_json(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        data = None
    if not data or not text_of(data.get("summary")).strip():
        return fail("azure: the answer was not the JSON asked for")

    def items(value, limit):
        if isinstance(value, str):
            value = [value]
        return [clip(text_of(v).strip(), 260) for v in (value or []) if text_of(v).strip()][:limit]
    confidence = text_of(data.get("confidence")).strip().lower()
    return {"headline": clip(text_of(data.get("headline")).strip(), 180),
            "summary": clip(text_of(data.get("summary")).strip(), 900),
            "risks": items(data.get("risks"), 3), "actions": items(data.get("actions"), 4),
            "confidence": confidence if confidence in ("low", "medium", "high") else ""}


# -------------------------------------------------------------------- rendering
#
# Email-safe html: tables for layout, no images (unless logo urls are given), no scripts, no SVG. Charts are table
# cells, divs and text bars, so they show in Gmail, Apple Mail and the Outlook apps. What repeats on every row lives
# in classes in <style> (Gmail keeps them for Google accounts) so a full dashboard stays near Gmail's 102 KB clip
# limit; the rest is inline. The hover rules go in the same <style> block as the layout (see render()).

CSS = """
body{margin:0;padding:0;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}
table{border-collapse:collapse;mso-table-lspace:0;mso-table-rspace:0}
img{border:0;outline:none;text-decoration:none}
td,th,div,span,a,p,b{font-family:__FONT__}
a{color:inherit}
.sec{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:14px;padding:20px 22px}
.hd td{padding-bottom:12px;border-bottom:1px solid #EEF2F6}
.st{font-size:17px;font-weight:800;line-height:1.3;color:#0F172A;letter-spacing:-.01em}
.ab{display:inline-block;width:4px;height:16px;border-radius:2px;background:__BRAND__;vertical-align:-2px;margin-right:10px}
.sh{font-size:15px;font-weight:800;line-height:1.3;color:#0F172A;margin:0 0 10px}
.gz{padding:0 24px 16px;background:#F3F5F9}
.hr{height:1px;background:#EEF2F6;margin:18px 0;font-size:0;line-height:0}
.sr{font-size:12px;color:#64748B}
.c{padding:10px 10px;font-size:14px;color:#334155;border-bottom:1px solid #EEF2F6;vertical-align:top}
.h{padding:8px 10px;background:#F1F5F9;font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#64748B;border-bottom:1px solid #E2E8F0;white-space:nowrap}
.g{border-collapse:separate;border:1px solid #E2E8F0;border-radius:10px;overflow:hidden}
.pl{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;line-height:1.5;white-space:nowrap}
.pb{background:#FEF2F2;color:#B91C1C}
.pg{background:#F0FDF4;color:#15803D}
.pi{background:#EFF6FF;color:#1D4ED8}
.pw{background:#FFFBEB;color:#B45309}
.pm{background:#F1F5F9;color:#64748B}
.mt{font-size:12px;line-height:1.5;color:#64748B;margin-top:2px}
.rl{color:#0F172A;text-decoration:none;font-weight:700}
.ln{color:__BRAND__;text-decoration:none;font-weight:600}
.n{font-size:15px;font-weight:800;color:#0F172A}
.rk{color:#94A3B8;font-weight:700}
.sl{font-size:0;line-height:0;white-space:nowrap}
.sl i{display:inline-block;width:6px;margin-right:2px;border-radius:1px;vertical-align:bottom}
.k0{background:#E2E8F0}
.k1{background:__LIGHT__}
.k2{background:__BRAND__}
.q0{height:2px}
.q1{height:3px}
.q2{height:6px}
.q3{height:9px}
.q4{height:12px}
.q5{height:15px}
.q6{height:18px}
.q7{height:21px}
.q8{height:24px}
.dl{font-size:9px;font-weight:600;color:#64748B;text-align:center;line-height:1;margin-bottom:2px;white-space:nowrap}
.bt{background:#F1F5F9;border-radius:4px;height:8px;font-size:0;line-height:0}
.bf{border-radius:4px;height:8px;font-size:0;line-height:0}
.vb{padding:0 1px}
.vb .b{border-radius:2px 2px 0 0;font-size:0;line-height:0}
.sb{width:4px;font-size:0;line-height:0}
.mr td{border-top:1px solid #F1F5F9}
.nw{font-weight:400;white-space:nowrap}
.lb{padding:7px 10px 7px 0;font-size:14px;line-height:1.35;color:#334155;word-break:break-word}
.lv{padding:7px 6px;font-size:14px;font-weight:800;color:#0F172A}
.ax{padding-top:5px;font-size:10px;color:#64748B;border-top:1px solid #E2E8F0;white-space:nowrap;overflow:hidden}
.d{width:13px;height:13px;border-radius:2px}
.ch{font-size:10px;color:#64748B;white-space:nowrap}
.rc{padding:8px 2px;font-size:12px;font-weight:700;color:#0F172A;border-radius:4px}
.rh{padding:4px 2px;font-size:11px;font-weight:700;color:#334155;word-break:break-word}
.wl{font-size:10px;font-weight:600;color:#64748B;text-align:center;line-height:1;margin-bottom:3px}
.msg{font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;font-size:13px;line-height:1.5;color:#0F172A;word-break:break-word}
.bb{padding:6px 8px}
.bd{padding:6px 0}
.it{padding:9px 12px 9px 6px;font-size:14px;line-height:1.55;color:#334155}
.tl{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:13px 14px 12px}
.tk{font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:#64748B;white-space:nowrap;overflow:hidden}
.tv{font-size:26px;font-weight:800;line-height:1.15;padding-top:6px;white-space:nowrap}
.ts{font-size:12px;line-height:1.5;color:#64748B;margin-top:5px}
.cd{background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:14px 16px}
.lg{font-size:11px;color:#64748B;margin-right:12px;white-space:nowrap}
.sq{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:-1px}
@media only screen and (max-width:640px){
 .px{padding-left:16px!important;padding-right:16px!important}
 .gz{padding-left:8px!important;padding-right:8px!important}
 .sec{padding:14px 12px!important}
 .outer{padding:10px 2px!important}
 .stack{display:block!important;width:100%!important;box-sizing:border-box}
 .hide-sm{display:none!important}
 .h1{font-size:22px!important}
 .ring{display:none!important}
}
"""
# Hover effects, the way error_notification.py has them. They live in the email's own <style>, in the same block as the
# layout (a separate block was not applied by the mail client). What a mail client reliably shows on hover is a change of colour or opacity,
# so every rule changes a background, a border or an opacity; the shadow and the lift are a bonus. Plain :hover rules,
# one selector per rule; only the motion sits in a media block for devices that hover, and it is off for people who
# ask for reduced motion.
#   hv-card   a tile or card tints light blue with a blue edge and lifts          hv-lift   a panel tints and lifts
#   hv-risk / hv-do   the AI Risks / Do next cards deepen in their own colour   hv-note   the note box deepens
#   hv-row    a list row tints                 hv-trow   a table row tints and gets a blue bar on its left
#   pl (pills) each tone deepens in its own colour (pill_hover_css)          hv-btn    a button tints and lifts
#   ln / rl   links underline     vb / hv-bar / seg   chart bars and bar segments dim
#   hm / rc   heat cells and route cells get an outline                       hv-ring   the health score grows a little
# __ROW__ and __BRAND__ are filled in by hover_css().
HOVER_CSS = """
.hv-card:hover{background:#F5F8FF!important;border-color:#93B4EE!important;box-shadow:0 12px 28px rgba(15,23,42,.11),0 2px 6px rgba(15,23,42,.06)!important}
.hv-lift:hover{background:__ROW__!important;box-shadow:0 12px 28px rgba(15,23,42,.11),0 2px 6px rgba(15,23,42,.06)!important}
.hv-risk:hover{background:#FEE2E2!important;border-color:#FCA5A5!important;box-shadow:0 12px 28px rgba(185,28,28,.12)!important}
.hv-do:hover{background:#DCFCE7!important;border-color:#86EFAC!important;box-shadow:0 12px 28px rgba(21,128,61,.12)!important}
.hv-note:hover{background:#FEF3C7!important;border-color:#FCD34D!important}
.hv-row:hover{background:__ROW__!important}
.hv-row:hover td{background-color:__ROW__!important}
.hv-trow:hover{background:__ROW__!important}
.hv-trow:hover td{background-color:__ROW__!important}
.hv-trow:hover td:first-child{box-shadow:inset 3px 0 0 __BRAND__!important}
.pl:hover{box-shadow:0 5px 12px rgba(15,23,42,.14)!important}
__PILLS__
.hv-btn:hover{background:#E1ECFF!important;border-color:#B5CCF5!important;box-shadow:0 8px 18px rgba(0,86,210,.18)!important}
.ln:hover{text-decoration:underline!important}
.rl:hover{text-decoration:underline!important}
.vb:hover .b{opacity:.65!important}
.hv-bar:hover{opacity:.65!important}
.seg td:hover{opacity:.7!important}
.hm td:hover{outline:2px solid #0F172A}
.rc:hover{outline:2px solid #0F172A;box-shadow:0 6px 14px rgba(15,23,42,.18)!important}
@media (hover:hover){
 .hv-card{transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s ease,background-color .22s ease,border-color .22s ease}
 .hv-card:hover{transform:translateY(-2px)}
 .hv-lift{transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s ease,background-color .22s ease}
 .hv-lift:hover{transform:translateY(-2px)}
 .hv-risk{transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s ease,background-color .22s ease,border-color .22s ease}
 .hv-risk:hover{transform:translateY(-2px)}
 .hv-do{transition:transform .22s cubic-bezier(.2,.7,.3,1),box-shadow .22s ease,background-color .22s ease,border-color .22s ease}
 .hv-do:hover{transform:translateY(-2px)}
 .hv-note{transition:background-color .2s ease,border-color .2s ease}
 .hv-row{transition:background-color .15s ease}
 .hv-trow{transition:background-color .15s ease}
 .pl{transition:transform .18s ease,background-color .18s ease,box-shadow .18s ease}
 .pl:hover{transform:translateY(-1px)}
 .hv-btn{transition:transform .18s ease,box-shadow .18s ease,background-color .18s ease,border-color .18s ease}
 .hv-btn:hover{transform:translateY(-1px)}
 .hv-bar{transition:opacity .15s ease}
 .hv-ring{transition:transform .25s cubic-bezier(.2,.7,.3,1)}
 .hv-ring:hover{transform:scale(1.05)}
}
@media (prefers-reduced-motion:reduce){
 .hv-card{transition:none!important}
 .hv-lift{transition:none!important}
 .hv-risk{transition:none!important}
 .hv-do{transition:none!important}
 .pl{transition:none!important}
 .hv-btn{transition:none!important}
 .hv-ring{transition:none!important}
}
"""
PILL_TONES = {"pb": (BAD_SOFT, BAD), "pg": (GOOD_SOFT, GOOD), "pi": (INFO_SOFT, INFO), "pw": (WARN_SOFT, WARN),
              "pm": (PANEL, MUTED)}


def pill_hover_css():
    """Each kind of pill turns a deeper shade of its own colour (its background moved towards its text colour), so a
    red pill stays red and a grey one grey."""
    return "\n".join(".{}:hover{{background:{}!important}}".format(name, mix(bg, fg, 0.16))
                      for name, (bg, fg) in sorted(PILL_TONES.items()))


def hover_css(cfg):
    return (HOVER_CSS.replace("__ROW__", cfg["hover_row_color"]).replace("__BRAND__", cfg["brand_color"])
            .replace("__PILLS__", pill_hover_css()))


SEGMENTS = ("#0056D2", "#7C3AED", "#DB2777", "#EA580C", "#0D9488", "#CA8A04")
TONE_CLASS = {"bad": "pb", "good": "pg", "info": "pi", "warn": "pw", "muted": "pm"}
PAGE = "#F3F5F9"          # the soft grey the section cards sit on
ALT = ' bgcolor="#FAFBFD"'


def table(inner, style="", attrs=""):
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"{}{}>{}</table>'.format(
        ' style="{}"'.format(style) if style else "", attrs, inner)


def section(body, top=0, bottom=16, card=True):
    """A row of the grey page: the section in a white card of its own (card=False for tiles, buttons, notes)."""
    if not body:
        return ""
    pad = "" if (top, bottom) == (0, 16) else ' style="padding-top:{}px;padding-bottom:{}px"'.format(top, bottom)
    return '<tr><td class="px gz" bgcolor="{}"{}>{}</td></tr>'.format(
        PAGE, pad, '<div class="sec">{}</div>'.format(body) if card else body)


def title_of(ctx, key):
    title = (ctx.extra.get("titles") or {}).get(key, TITLES.get(key, ""))
    return fill(title, {"unit": ctx.period.unit, "label": unit_label(ctx)})


def heading(ctx, key, right=""):
    title = title_of(ctx, key)
    if not title:
        return ""
    return table('<tr><td class="st"><span class="ab"></span>{}</td><td class="sr" align="right">{}</td></tr>'.format(
        esc(title), right), style="margin:0 0 16px", attrs=' class="hd"')


def subhead(text, color="", right=""):
    """A heading inside a section (Target systems, Objects, Rising, ...): bigger and bolder than the text under it."""
    return '<div class="sh"{}>{}{}</div>'.format(' style="color:{}"'.format(color) if color else "", text,
                                                 " " + right if right else "")


HR = '<div class="hr">&nbsp;</div>'


def pill(html, tone="muted"):
    return '<span class="pl {}">{}</span>'.format(TONE_CLASS.get(tone, "pm"), html)


def delta(cur, prev, up_bad=True):
    if not cur and not prev:
        return '<span style="color:{}">—</span>'.format(FAINT)
    if not prev:
        return pill("new", "info")
    ch = change_pct(cur, prev)
    if abs(ch) < 1:
        return pill("= 0%")
    up = ch > 0
    text = "{} {}".format("▲" if up else "▼", ">999%" if abs(ch) > 999 else fmt_pct(abs(ch)))
    return pill(text, "bad" if up == up_bad else "good")


def spark(values, color, height=22):
    """Bars for a KPI tile."""
    peak = max(values) if values else 0
    cells, last = [], len(values) - 1
    for i, v in enumerate(values):
        h = max(2, int(round(height * v / float(peak)))) if v and peak else 1
        c = LINE if not v else (color if i == last else mix(color, "#FFFFFF", 0.55))
        cells.append('<td valign="bottom"><div class="sb" style="height:{}px;background:{}"></div></td>'.format(h, c))
    return ('<table class="hv-bar" cellpadding="0" cellspacing="1" border="0" style="border-collapse:separate;height:{}px"><tr>{}</tr>'
            '</table>').format(height + 2, "".join(cells))


def spark_bars(values, unit="week"):
    """A small bar chart of the periods, bottom-aligned on one baseline, the latest bar in full colour (classes .sl,
    .k0-.k2 for colour and .q0-.q8 for height keep it a few bytes a bar). Hover shows the numbers."""
    peak = max(values) if values else 0
    last, cells = len(values) - 1, []
    for i, v in enumerate(values):
        if v and peak:
            cells.append('<i class="{} q{}"></i>'.format("k2" if i == last else "k1",
                                                         max(1, min(8, int(math.ceil(8.0 * v / peak))))))
        else:
            cells.append('<i class="k0 q0"></i>')
    return '<div class="sl hv-bar" title="{}">{}</div>'.format(
        esc("Per {}, oldest first: {}".format(unit, ", ".join(fmt_int(v) for v in values))), "".join(cells))


def hbar(fraction, color, height=8, track=True):
    width = 0 if fraction <= 0 else max(2, min(100, int(round(fraction * 100))))
    tall = "" if height == 8 else ";height:{}px".format(height)
    inner = '<div class="bf" style="width:{}%;background:{}{}"></div>'.format(width, color, tall) if width else ""
    style = tall.lstrip(";") + ("" if track else ";background:transparent")
    return '<div class="bt"{}>{}</div>'.format(' style="{}"'.format(style.strip(";")) if style.strip(";") else "", inner)


def link(label, url, cls="ln", color=""):
    url = safe_url(url)
    if not url:
        return esc(label)
    return '<a class="{}" href="{}" target="_blank"{}>{}</a>'.format(
        cls, esc(url), ' style="color:{}"'.format(color) if color else "", esc(label))


def recipe_link(ctx, e, limit=70):
    return link(clip(e["name"], limit), recipe_url(ctx, e["rid"]), "rl")


def rich(text):
    """Escaped text with **bold** and `code` turned into tags (for the AI summary and the headline)."""
    out = esc(text)
    out = re.sub(r"`([^`]{1,120})`", r'<code style="font-family:monospace;font-size:12px">\1</code>', out)
    return re.sub(r"\*\*([^*]{1,200})\*\*", r"<b>\1</b>", out)


def heat_color(ctx, n, peak):
    if not n or not peak:
        return HEAT_ZERO
    colors = ctx.heat_colors
    return colors[min(len(colors) - 1, int(math.sqrt(n / float(peak)) * len(colors) - 1e-9))]


def heat_legend(ctx):
    cells = "".join('<td width="12" height="10" bgcolor="{}"></td>'.format(c) for c in (HEAT_ZERO,) + tuple(ctx.heat_colors))
    return ('<table cellpadding="0" cellspacing="2" border="0" style="border-collapse:separate;display:inline-table;'
            'vertical-align:middle"><tr><td class="sr" style="padding-right:4px">Less</td>{}'
            '<td class="sr" style="padding-left:4px">More</td></tr></table>').format(cells)


def legend_item(color, label, dashed=False):
    return '<span class="lg"><span class="sq" style="background:{}{}"></span>&nbsp;{}</span>'.format(
        color, ";border:1px dashed #94A3B8;box-sizing:border-box" if dashed else "", label)


def vbar(value, peak, height, color, title, top="", dashed=False):
    h = int(round((height - 16) * value / float(peak))) if value and peak else 0
    if value and h < 2:
        h = 2
    if h:
        style = "height:{}px;background:{}".format(h, color)
        if dashed:
            style += ";border:1px dashed #94A3B8;border-bottom:0;box-sizing:border-box"
    else:
        style = "height:2px;background:{};border-radius:0".format(LINE)
    return '<td class="vb" valign="bottom" height="{}" title="{}">{}<div class="b" style="{}"></div></td>'.format(
        height, esc(title), top, style)


def card(body, accent=None, bg=""):
    style = ("border-top:3px solid {};".format(accent) if accent else "") + ("background:{};".format(bg) if bg else "")
    return '<div class="cd hv-card"{}>{}</div>'.format(' style="{}"'.format(style) if style else "", body)


def empty_note(text):
    return '<div style="font-size:13px;color:{};padding:4px 0">{}</div>'.format(MUTED, text)


def th(label, align="", cls="", width=""):
    return '<td class="h{}"{}{}>{}</td>'.format(" " + cls if cls else "", ' align="{}"'.format(align) if align else "",
                                               ' width="{}"'.format(width) if width else "", label)


def tdc(html, align="", cls="", style=""):
    return '<td class="c{}"{}{}>{}</td>'.format(" " + cls if cls else "", ' align="{}"'.format(align) if align else "",
                                               ' style="{}"'.format(style) if style else "", html)


def grid_table(head, rows):
    return ('<table role="presentation" class="g" width="100%" cellpadding="0" cellspacing="0" border="0">'
            '<tr>{}</tr>{}</table>').format("".join(head), "".join(rows))


def row(i, cells):
    """A row of a bordered table: it tints and gets a blue bar on its left under the mouse."""
    return '<tr class="hv-trow"{}>{}</tr>'.format(ALT if i % 2 else "", "".join(cells))


def status_pill(status):
    label, fg, _ = TREND_PILLS.get(status, TREND_PILLS["steady"])
    tone = {BAD: "bad", GOOD: "good", INFO: "info", WARN: "warn"}.get(fg, "muted")
    return pill(label, tone)


def unit_label(ctx):
    return {"week": "Weekly", "day": "Daily"}.get(ctx.period.unit, "{}-day".format(ctx.period.days))


def rank(i):
    return '<span class="rk">{}</span>'.format(i + 1)


def count(n):
    return '<span class="n">{}</span>'.format(fmt_int(n))


# ------------------------------------------------------------------- sections


def sec_hero(ctx, m, lim):
    cfg, per, brand = ctx.cfg, ctx.period, ctx.cfg["brand_color"]
    def image(url, alt):
        return '<img src="{}" alt="{}" height="30" style="height:30px;width:auto;display:block;border:0">'.format(
            esc(url), esc(alt))
    # Coursera, then Workato, then the team, with a thin line between them; a logo without a url is left out
    logos = [image(cfg["logo_url"], "Coursera") if safe_url(cfg["logo_url"]) else
             '<span style="font-size:22px;font-weight:800;line-height:1;color:{};letter-spacing:-.02em">coursera</span>'.format(brand)]
    if safe_url(cfg["workato_logo_url"]):
        logos.append(image(cfg["workato_logo_url"], "Workato"))
    if safe_url(cfg["team_logo_url"]):
        logos.append(image(cfg["team_logo_url"], cfg["team_name"] or "Team"))
    divider = ('<td valign="middle" style="padding:0 14px"><div style="width:1px;height:26px;background:{};font-size:0;'
               'line-height:0">&nbsp;</div></td>').format(LINE)
    logo = logos[0] if len(logos) == 1 else (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{}</tr></table>'.format(
            divider.join('<td valign="middle">{}</td>'.format(x) for x in logos)))
    env = ctx.env_label
    right = ('<span class="pl" style="background:{};color:#FFFFFF">{}</span>'.format(INK, esc(env.upper())) if env else "")
    head = ctx.ai["headline"] if ctx.ai and ctx.ai.get("headline") else headline(ctx, m)
    subtitle = ('<div style="font-size:14px;color:{};margin:0 0 4px">{}</div>'.format(TEXT, esc(cfg["subtitle"]))
                if cfg["subtitle"] else "")
    ring, reasons = "", ""
    s = m.score
    if s:
        ring = ('<td class="ring" width="132" align="right" valign="top" style="padding-left:12px">'
                '<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="right"><tr><td align="center">'
                '<div class="hv-ring" style="width:86px;height:86px;border-radius:50%;border:7px solid {c};background:{bg};'
                'text-align:center">'
                '<div style="font-size:32px;font-weight:800;color:{c};line-height:1;padding-top:20px">{n}</div>'
                '<div style="font-size:11px;font-weight:800;color:{c};letter-spacing:.1em;margin-top:4px">GRADE {g}</div>'
                '</div></td></tr><tr><td align="center" class="sr" style="padding-top:6px;font-size:11px">Health score</td>'
                '</tr></table></td>').format(c=s["color"], bg=s["soft"], n=s["score"], g=s["grade"])
        why = " · ".join("{} <b>−{}</b>".format(esc(w), t) for t, w in s["reasons"][:4]) or "nothing taking points off"
        reasons = '<div class="sr" style="margin-top:10px">Health {} / 100: {}</div>'.format(s["score"], why)
    notices = ""
    if cfg["note"]:
        notices += section('<div class="hv-note" style="background:{};border:1px solid #FDE68A;border-radius:10px;padding:12px 14px;'
                           'font-size:14px;line-height:1.55;color:{}">📌 {}</div>'.format(WARN_SOFT, TEXT,
                                                                                         sanitize_html(cfg["note"])),
                           bottom=14, card=False)
    if not ctx.data_complete:
        notices += section('<div style="background:#FFF7ED;border:1px solid #FED7AA;border-radius:10px;padding:12px 14px;'
                           'font-size:13px;line-height:1.55;color:#9A3412"><b>Some data could not be read</b>, so some '
                           'numbers may be low. The warnings output of the step says what.</div>', bottom=14, card=False)
    top = table('<tr><td valign="middle">{}</td><td align="right" valign="middle" class="sr">{}&nbsp; {}</td></tr>'.format(
        logo, right, esc(day_name(ctx.today))), style="margin:0 0 20px")
    body = table(
        '<tr><td valign="top">'
        '<div style="font-size:12px;font-weight:800;letter-spacing:.11em;text-transform:uppercase;color:{b}">{e}</div>'
        '<div class="h1" style="font-size:27px;font-weight:800;line-height:1.2;color:{ink};margin:6px 0 4px">{t}</div>{sub}'
        '<div style="font-size:14px;color:{m};margin:0 0 12px">{p} <span style="color:{f}">·</span> compared with {pp}</div>'
        '<div style="font-size:15px;line-height:1.55;color:{text};font-weight:500">{h}</div>{r}'
        '</td>{ring}</tr>'.format(b=brand, e=esc(title_of(ctx, "eyebrow")), ink=INK,
                                  t=esc(cfg["title"]), sub=subtitle, m=MUTED, p=esc(per.label), f=FAINT,
                                  pp=esc(per.prev_label), text=TEXT, h=rich(head), r=reasons, ring=ring))
    return ('<tr><td bgcolor="{b}" style="height:6px;line-height:6px;font-size:0;background:{b}">&nbsp;</td></tr>'
            '<tr><td class="px" style="padding:22px 32px 22px;border-bottom:1px solid {l}">{top}{body}</td></tr>'
            '{gap}{notices}').format(b=brand, top=top, body=body, l=LINE, gap=PAGE_GAP, notices=notices)


PAGE_GAP = '<tr><td class="gz" bgcolor="{0}" height="20" style="font-size:0;line-height:0;background:{0}">&nbsp;</td></tr>'.format(PAGE)


def tile(label, value, sub, color=INK, change="", chart=""):
    return ('<td class="stack" width="25%" valign="top" style="padding:0 5px 10px"><div class="tl hv-card">'
            '<div class="tk">{}</div>'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td class="tv" valign="bottom" style="color:{}">{}</td><td align="right" valign="bottom">{}</td></tr></table>'
            '<div class="ts">{}{}{}</div></div></td>').format(esc(label), color, esc(value), chart, change,
                                                             " " if change and sub else "", sub)


def top_recipe_tile(ctx, m):
    """The recipe behind most of this period's errors: who to look at first, with its share and change."""
    if not m.top:
        return tile("Top recipe", "—", "no recipe failed this {}".format(ctx.period.unit), GOOD)
    e = m.top[0]
    sub = '{}<div style="margin-top:2px">{} of errors{}</div>'.format(
        link(clip(e["name"], 34), recipe_url(ctx, e["rid"]), "rl"), fmt_pct(pct(e["cur"], m.cur_n)),
        " · was {}".format(fmt_int(e["prev"])) if e["prev"] != e["cur"] else "")
    return tile("Top recipe", fmt_int(e["cur"]), sub, BAD if e["status"] in ("spike", "rising", "new") else INK,
                status_pill(e["status"]))


def sec_kpis(ctx, m, lim):
    per, brand = ctx.period, ctx.cfg["brand_color"]
    unit = per.unit
    tiles = [tile("Errors", fmt_int(m.cur_n), "vs {} last {}".format(fmt_int(m.prev_n), unit), BAD if m.cur_n else GOOD,
                  delta(m.cur_n, m.prev_n), spark(m.weekly, brand)),
             tile("Recipes affected", fmt_int(m.recipes_cur), "vs {}".format(fmt_int(m.recipes_prev)), INK,
                  delta(m.recipes_cur, m.recipes_prev), spark([len(s) for s in m.weekly_recipes], brand)),
             top_recipe_tile(ctx, m),
             tile("New patterns", fmt_int(len(m.new_patterns)),
                  "of {} this {}".format(plural(len(m.patterns_top), "pattern"), unit),
                  WARN if m.new_patterns else INK)]
    if m.rec_failed_cur or m.rec_failed_prev:
        sub = ("{} of {}".format(fmt_pct(pct(m.rec_failed_cur, m.rec_total_cur), 1), fmt_compact(m.rec_total_cur))
               if m.rec_total_cur else "in batch runs")
        tiles.append(tile("Records failed", fmt_compact(m.rec_failed_cur), sub, INK,
                          delta(m.rec_failed_cur, m.rec_failed_prev), spark(m.weekly_records, brand)))
    reprocessed = sum(v for k, v in m.status_cur.items() if k.lower() == "reprocessed")
    again = sum(v for k, v in m.status_cur.items() if k.lower() == "failed again")
    tiles.append(tile("Reprocessed", fmt_int(reprocessed), "{} of errors{}".format(
        fmt_pct(pct(reprocessed, m.cur_n)), " · {} failed again".format(fmt_int(again)) if again else ""),
        GOOD if reprocessed else INK, "", spark(m.weekly_reprocessed, GOOD)))
    if m.backlog is not None:
        bl = m.backlog
        tiles.append(tile("Deferred waiting", fmt_int(bl["total"]),
                          "{} overdue · oldest {}d".format(fmt_int(bl["overdue"]), bl["oldest"]) if bl["total"]
                          else "nothing waiting", WARN if bl["overdue"] else INK))
    days = [per.start + timedelta(days=i) for i in range(per.days)]
    busiest = max(days, key=lambda d: (m.daily.get(d, 0), d))
    if per.days > 1 and m.daily.get(busiest, 0):
        spiked = any(s["date"] == busiest for s in m.spikes)
        tiles.append(tile("Busiest day", fmt_int(m.daily[busiest]), day_name(busiest) + (" · spike" if spiked else ""),
                          SPIKE if spiked else INK))
    f = m.forecast
    if f:
        arrow = {"rising": "↗ rising", "easing": "↘ easing", "flat": "→ flat"}[f["trend"]]
        tiles.append(tile("Next {}".format(unit), "~" + fmt_int(f["point"]),
                          "likely {}–{} · {}".format(fmt_int(f["low"]), fmt_int(f["high"]), arrow), INFO))
    rows = []
    for i in range(0, len(tiles), 4):
        chunk = tiles[i:i + 4]
        chunk += ['<td class="stack hide-sm" width="25%"></td>'] * (4 - len(chunk))
        rows.append("<tr>{}</tr>".format("".join(chunk)))
    return section(table("".join(rows), style="margin:0 -5px"), bottom=6, card=False)


def sec_insights(ctx, m, lim):
    if not ctx.insights and not ctx.ai:
        return ""
    body = ""
    a = ctx.ai
    if ctx.ai_error and not a:
        body += ('<div class="sr" style="margin:0 0 10px">✨ The AI summary could not be built this time, so only the built-in '
                 'insights are shown.</div>')
    if a:
        def ai_list(title, icon, items, fg, bg, line, numbered, pad, hover):
            """Risks / Do next as a tinted card of its own, so they don't read as one block with the summary."""
            if not items:
                return ""
            rows = []
            for n, item in enumerate(items):
                marker = ('<span style="display:inline-block;width:18px;height:18px;border-radius:9px;background:{};'
                          'color:#FFFFFF;font-size:10px;font-weight:800;line-height:18px;text-align:center">{}</span>'
                          .format(fg, n + 1) if numbered else
                          '<span style="color:{};font-size:15px;font-weight:800;line-height:1">•</span>'.format(fg))
                rows.append('<tr><td valign="top" width="26" style="padding:5px 0">{}</td><td valign="top" '
                            'style="padding:5px 0;font-size:13px;line-height:1.5;color:{}">{}</td></tr>'.format(
                                marker, TEXT, rich(item)))
            return ('<td class="stack" width="50%" valign="top" style="padding:{pad}">'
                    '<div class="{hover}" style="background:{bg};border:1px solid {line};border-left:4px solid {fg};'
                    'border-radius:10px;padding:12px 14px"><div style="font-size:12px;font-weight:800;letter-spacing:.06em;'
                    'text-transform:uppercase;color:{fg};margin-bottom:4px">{icon}&nbsp; {title}</div>{rows}</div>'
                    '</td>').format(pad=pad, hover=hover, bg=bg, line=line, fg=fg, icon=icon, title=title,
                                    rows=table("".join(rows)))
        lists = (ai_list("Risks", "⚠️", a["risks"], BAD, BAD_SOFT, "#FECACA", False, "14px 6px 0 0", "hv-risk") +
                 ai_list("Do next", "✅", a["actions"], GOOD, GOOD_SOFT, "#BBF7D0", True, "14px 0 0 6px", "hv-do"))
        body += ('<div class="cd" style="background:#F5F8FF;border-color:#D4E1FB;padding:16px 18px;margin:0 0 14px">'
                 '<div class="st" style="color:{b}">✨ Executive summary</div>'
                 '<div style="font-size:14px;line-height:1.65;color:{t};margin-top:8px">{s}</div>{l}'
                 '<div class="sr" style="font-size:11px;margin-top:10px">AI-assisted from the numbers in this report{c}. '
                 'Check it before acting.</div></div>').format(
            b=ctx.cfg["brand_color"], t=TEXT, s=rich(a["summary"]), l=table("<tr>{}</tr>".format(lists)) if lists else "",
            c=" · confidence: " + a["confidence"] if a["confidence"] else "")
    tones = {"bad": BAD, "warn": WARN, "good": GOOD, "info": INFO}
    rows = "".join(
        '<tr class="hv-row"><td valign="top" width="30" style="padding:9px 0 9px 12px;font-size:15px;line-height:1.4;'
        'border-left:3px solid {c}">{i}</td><td class="it" valign="top">{h}</td></tr><tr><td colspan="2" height="5" style="font-size:0;line-height:0">'
        '</td></tr>'.format(c=tones.get(i["tone"], INFO), i=i["icon"], h=i["html"]) for i in ctx.insights)
    if rows:
        body += table('<tr><td colspan="2" height="7" style="font-size:0;line-height:0"></td></tr>' + rows,
                      style="background:{};border-radius:12px".format(SOFT), attrs=' bgcolor="{}"'.format(SOFT))
    return section(heading(ctx, "insights") + body)


def day_label(n, color="", bold=False, prefix=""):
    """The number over a bar of the daily chart: short enough for a narrow bar (1.2k, not 1,234)."""
    n = int(round(n))
    text = prefix + (str(n) if n < 1000 else "{:.1f}k".format(n / 1000.0).replace(".0k", "k"))
    style = ";".join(x for x in ("color:" + color if color else "", "font-weight:800" if bold else "",
                                 "color:#CBD5E1" if not n else "") if x)
    return '<div class="dl"{}>{}</div>'.format(' style="{}"'.format(style) if style else "", text)


def sec_trend(ctx, m, lim):
    per, brand = ctx.period, ctx.cfg["brand_color"]
    days = [per.daily_start + timedelta(days=i) for i in range((per.end - per.daily_start).days + 1)]
    spikes = {s["date"]: s for s in m.spikes}
    fc = m.forecast["daily"] if m.forecast else []
    values = [m.daily.get(d, 0) for d in days] + [v for _, v in fc]
    peak = max(values) if values and max(values) else 1
    light = mix(brand, "#FFFFFF", 0.62)
    cells = []
    for d in days:
        n = m.daily.get(d, 0)
        s = spikes.get(d)
        title = "{} · {}".format(day_name(d), plural(n, "error"))
        if s:
            title += " · spike (usual ~{})".format(fmt_int(s["usual"]))
        show = len(days) <= 45 or s or d >= per.start
        top = day_label(n, SPIKE if s else (INK if d >= per.start else ""), bool(s or d >= per.start)) if show else ""
        cells.append(vbar(n, peak, 134, SPIKE if s else (brand if d >= per.start else light), title, top))
    for d, v in fc:
        cells.append(vbar(v, peak, 134, "#EEF2F6", "{} · forecast ~{}".format(day_name(d), fmt_int(v)),
                          day_label(v, INFO, False, "~"), dashed=True))
    groups, current = [], None
    for d in days:
        offset = (per.end - d).days // per.days
        if offset != current:
            groups.append([d, 0])
            current = offset
        groups[-1][1] += 1
    axis = "".join('<td class="ax" colspan="{}">{}</td>'.format(n, esc(short_day(d)) if n >= 3 else "") for d, n in groups)
    if fc:
        axis += '<td class="ax" colspan="{}" style="border-top-style:dashed">Next {}</td>'.format(len(fc), per.unit)
    chart = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed">'
             '<tr>{}</tr><tr>{}</tr></table>').format("".join(cells), axis)
    legend = (legend_item(brand, "this " + per.unit) + legend_item(light, "earlier") +
              (legend_item(SPIKE, "spike") if spikes else "") + (legend_item("#EEF2F6", "forecast", True) if fc else ""))
    top_day = max(days, key=lambda d: (m.daily.get(d, 0), d)) if days else None
    right = "{} in {} days".format(fmt_int(sum(m.daily.get(d, 0) for d in days)), len(days))
    if top_day and m.daily.get(top_day):
        right += " · peak {} ({})".format(day_name(top_day), fmt_int(m.daily[top_day]))
    return section(heading(ctx, "trend", esc(right)) + chart + '<div style="margin-top:8px">{}</div>'.format(legend))


def sec_weekly(ctx, m, lim):
    per, brand = ctx.period, ctx.cfg["brand_color"]
    f = m.forecast
    values = list(m.weekly) + ([f["point"]] if f else [])
    peak = max(values) if values and max(values) else 1
    light = mix(brand, "#FFFFFF", 0.62)
    cells = []
    for i, b in enumerate(per.buckets):
        n = m.weekly[i]
        last = i == len(per.buckets) - 1
        top = '<div class="wl"{}>{}</div>'.format(' style="font-weight:800;color:{}"'.format(INK) if last else "",
                                                fmt_compact(n))
        cells.append(vbar(n, peak, 120, brand if last else light, "{}: {}".format(range_label(b.start, b.end),
                                                                                 plural(n, "error")), top))
    if f:
        top = ('<div style="font-size:10px;font-weight:700;color:{};text-align:center;line-height:1;margin-bottom:3px">~{}'
               '</div>').format(INFO, fmt_compact(f["point"]))
        cells.append(vbar(f["point"], peak, 120, "#EEF2F6", "Next {}: ~{} (likely {}–{})".format(
            per.unit, fmt_int(f["point"]), fmt_int(f["low"]), fmt_int(f["high"])), top, dashed=True))
    every = 2 if len(per.buckets) > 16 else 1
    axis = "".join('<td class="ax" align="center">{}</td>'.format(
        esc(short_day(b.start)) if (len(per.buckets) - 1 - i) % every == 0 else "") for i, b in enumerate(per.buckets))
    if f:
        axis += '<td class="ax" align="center" style="border-top-style:dashed;color:{}">next</td>'.format(INFO)
    chart = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed">'
             '<tr>{}</tr><tr>{}</tr></table>').format("".join(cells), axis)
    history = m.weekly[:-1]
    right = "average {} · median {} a {}".format(fmt_int(mean(history)), fmt_int(median(history)), per.unit) if history else ""
    return section(heading(ctx, "weekly", esc(right)) + chart)


def recipe_meta(ctx, e):
    bits = []
    src, tgt = e["route"]
    if src or tgt:
        bits.append(esc("{} → {}".format(src or "?", tgt or "?")))
    label, icon = category_info(e["cat"], ctx.rules)
    bits.append("{} {}".format(icon, esc(label)))
    st = ctx.status.get(e["rid"])
    if st:
        if st["running"] is False:
            bits.append('<b style="color:{}">■ stopped</b>'.format(BAD))
        if st["updated_at"] and (ctx.today - st["updated_at"].date()).days <= 14:
            bits.append('<span style="color:{}">✎ changed {}</span>'.format(
                WARN, rel_age((ctx.today - st["updated_at"].date()).days)))
    if e["owner"]:
        bits.append("👤 " + esc(e["owner"]))
    if e["known"]:
        note = "📎 " + e["known"]["note"]
        bits.append(link(note, e["known"]["url"], "ln", WARN) if e["known"]["url"]
                    else '<span style="color:{}">{}</span>'.format(WARN, esc(note)))
    return '<div class="mt">{}</div>'.format(" · ".join(bits))


def sec_recipes(ctx, m, lim):
    rows = m.top[: lim["top_n"]]
    unit = ctx.period.unit
    if not rows:
        return section(heading(ctx, "recipes") + empty_note("No recipe failed this {}. 🎉".format(unit)))
    peak = rows[0]["cur"] or 1
    brand = ctx.cfg["brand_color"]
    head = [th("#", "", "", "24"), th("Recipe"), th("Errors", "right"), th("vs last", "", "hide-sm"),
            th("{} {}s".format(ctx.period.count, unit), "", "hide-sm"), th("Share", "", "hide-sm", "90"), th("Status")]
    body = []
    for i, e in enumerate(rows):
        body.append(row(i, [
            tdc(rank(i)), tdc(recipe_link(ctx, e) + recipe_meta(ctx, e), style="word-break:break-word"),
            tdc(count(e["cur"]), "right"),
            tdc(delta(e["cur"], e["prev"]) + '<div class="mt">was {}</div>'.format(fmt_int(e["prev"])), cls="hide-sm"),
            tdc(spark_bars(e["weekly"], unit), cls="hide-sm"),
            tdc(hbar(e["cur"] / float(peak), brand, 6) + '<div class="mt">{}</div>'.format(fmt_pct(pct(e["cur"], m.cur_n))),
                cls="hide-sm"),
            tdc(status_pill(e["status"]))]))
    more = len(m.top) - len(rows)
    note = ('<div class="sr" style="margin-top:8px">{} more failing this {} with {}.</div>'.format(
        plural(more, "recipe"), unit, plural(sum(e["cur"] for e in m.top[len(rows):]), "error")) if more > 0 else "")
    right = "{} of {} errors".format(fmt_pct(pct(sum(e["cur"] for e in rows), m.cur_n)), fmt_int(m.cur_n))
    return section(heading(ctx, "recipes", esc(right)) + grid_table(head, body) + note)


def sec_movers(ctx, m, lim):
    unit, n = ctx.period.unit, lim["movers_n"]
    boxes = (("Rising", "🔺", BAD, m.rising, lambda e: "{} → <b>{}</b>".format(fmt_int(e["prev"]), fmt_int(e["cur"]))),
             ("Easing", "🔻", GOOD, m.easing, lambda e: "{} → <b>{}</b>".format(fmt_int(e["prev"]), fmt_int(e["cur"]))),
             ("New this " + unit, "🆕", INFO, m.new_recipes, lambda e: "<b>{}</b>".format(fmt_int(e["cur"]))),
             ("Gone quiet", "🤫", MUTED, m.quiet, lambda e: "{} → <b>0</b>".format(fmt_int(e["prev"]))))
    cells = []
    for title, icon, color, items, value in boxes:
        lines = "".join('<tr class="hv-row"><td class="lb">{}</td><td class="lv nw" align="right">{}</td></tr>'
                        .format(recipe_link(ctx, e, 52), value(e)) for e in items[:n])
        more = '<div class="sr" style="font-size:11px;margin-top:4px">and {} more</div>'.format(len(items) - n) \
            if len(items) > n else ""
        body = (subhead("{} {}".format(icon, esc(title)), color, pill(fmt_int(len(items)))) +
                (table(lines, attrs=' class="mr"') if lines else empty_note("Nothing this " + unit + ".")) + more)
        cells.append('<td class="stack" width="50%" valign="top" style="padding:0 6px 12px">{}</td>'.format(card(body, color)))
    return section(heading(ctx, "movers") + table("<tr>{}{}</tr><tr>{}{}</tr>".format(*cells), style="margin:0 -6px"))


def sec_patterns(ctx, m, lim):
    rows = m.patterns_top[: lim["patterns_n"]]
    if not rows:
        return ""
    head = [th("#", "", "", "24"), th("Pattern"), th("Errors", "right"), th("vs last", "", "hide-sm"),
            th("Trend", "", "hide-sm")]
    body = []
    for i, p in enumerate(rows):
        label, icon = category_info(p["cat"], ctx.rules)
        text = shown_message(ctx, p["example"]) if ctx.cfg["show_examples"] else p["fp"]
        names = p["recipes_cur"]
        where = ("in " + esc(clip(names.most_common(1)[0][0], 60)) if len(names) == 1
                 else "in {}".format(plural(len(names), "recipe")))
        seen = ("first seen {}".format(esc(short_day(p["first"]))) if p["status"] == "new" else
                "in {} of {} {}s".format(sum(1 for x in p["weekly"] if x), ctx.period.count, ctx.period.unit))
        bits = ["{} {}".format(icon, esc(label)), where, seen]
        if p["status"] == "new":
            bits.insert(0, pill("NEW", "info"))
        if p["known"]:
            bits.append('<span style="color:{}">📎 {}</span>'.format(WARN, esc(p["known"]["note"])))
        if p["url"]:
            bits.append(link("latest job ↗", p["url"]))
        body.append(row(i, [
            tdc(rank(i)),
            tdc('<div class="msg">{}</div><div class="mt" style="margin-top:3px">{}</div>'.format(
                esc(clip(text, 180)), " · ".join(bits))),
            tdc(count(p["cur"]), "right"), tdc(delta(p["cur"], p["prev"]), cls="hide-sm"),
            tdc(spark_bars(p["weekly"], ctx.period.unit), cls="hide-sm")]))
    right = "{} new · {} patterns this {}".format(len(m.new_patterns), len(m.patterns_top), ctx.period.unit)
    return section(heading(ctx, "patterns", esc(right)) + grid_table(head, body))


def bar_rows(items, color, label_width="40%"):
    """[(label html, cur, prev)] as rows: label | bar | count | change."""
    if not items:
        return ""
    peak = max(c for _, c, _ in items) or 1
    return table("".join(
        '<tr class="hv-row"><td class="lb" width="{}">{}</td><td class="bb">{}</td>'
        '<td class="lv" width="44" align="right">{}</td><td class="bd" width="70" align="right">{}</td></tr>'.format(
            label_width, label, hbar(cur / float(peak), color), fmt_int(cur), delta(cur, prev))
        for label, cur, prev in items))


def sec_categories(ctx, m, lim):
    keys = [k for k, _ in (m.cats_cur + m.cats_prev).most_common()][: lim["systems_n"]]
    if not keys:
        return ""
    keys.sort(key=lambda k: (-m.cats_cur.get(k, 0), -m.cats_prev.get(k, 0)))
    peak = max([m.cats_cur.get(k, 0) for k in keys] + [m.cats_prev.get(k, 0) for k in keys]) or 1
    brand = ctx.cfg["brand_color"]
    rows = []
    for k in keys:
        label, icon = category_info(k, ctx.rules)
        cur, prev = m.cats_cur.get(k, 0), m.cats_prev.get(k, 0)
        bars = (hbar(cur / float(peak), brand, 8) + '<div style="height:3px;font-size:0;line-height:0"></div>' +
                hbar(prev / float(peak), "#CBD5E1", 4, track=False))
        rows.append('<tr class="hv-row"><td class="lb" width="38%">{} {}</td><td class="bb">{}</td>'
                    '<td class="lv" width="44" align="right">{}</td><td class="bd" width="70" align="right">{}'
                    '</td></tr>'.format(icon, esc(label), bars, fmt_int(cur), delta(cur, prev)))
    legend = legend_item(brand, "this " + ctx.period.unit) + legend_item("#CBD5E1", "the one before")
    return section(heading(ctx, "categories", legend) + table("".join(rows)))


def sec_systems(ctx, m, lim):
    n, brand = lim["systems_n"], ctx.cfg["brand_color"]
    if not m.tgt_cur and not m.src_cur:
        return ""

    def items(cur, prev):
        return [(esc(name), c, prev.get(name, 0)) for name, c in cur.most_common(n)]

    def column(title, rows, color):
        return ('<td class="stack" width="50%" valign="top" style="padding:0 12px 4px 0">{}{}</td>').format(
            subhead(title), bar_rows(rows, color, "44%") or empty_note("None"))
    top = table("<tr>{}{}</tr>".format(column("Target systems", items(m.tgt_cur, m.tgt_prev), "#DC2626"),
                                       column("Source systems", items(m.src_cur, m.src_prev), brand)))
    src_total, tgt_total = Counter(), Counter()
    for (s, t), c in m.routes.items():
        src_total[s] += c
        tgt_total[t] += c
    srcs = [s for s, _ in src_total.most_common(6)]
    tgts = [t for t, _ in tgt_total.most_common(6)]
    peak = max([m.routes.get((s, t), 0) for s in srcs for t in tgts] or [1]) or 1
    grid = ['<tr><td class="sr" style="padding:4px 8px 4px 0;font-size:10px;text-transform:uppercase;letter-spacing:.06em">'
            'source ↓ target →</td>{}</tr>'.format("".join(
                '<td class="rh" align="center">{}</td>'.format(esc(clip(t, 22))) for t in tgts))]
    for s in srcs:
        cells = []
        for t in tgts:
            c = m.routes.get((s, t), 0)
            bg = heat_color(ctx, c, peak)
            fg = "#FFFFFF" if bg in ctx.heat_colors[-2:] else INK
            cells.append('<td class="rc" align="center" bgcolor="{}"{}>{}</td>'.format(
                bg, ' style="color:#FFFFFF"' if fg != INK else "", fmt_int(c) if c else ""))
        grid.append('<tr><td class="rh" style="padding-right:8px;font-size:12px">{}</td>{}</tr>'.format(
            esc(clip(s, 26)), "".join(cells)))
    routes = HR + subhead("Routes: source → target") + (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="3" border="0" '
        'style="border-collapse:separate;table-layout:fixed">{}</table>').format("".join(grid))
    objects = ""
    if m.obj_cur:
        objects = HR + subhead("Objects") + bar_rows(items(m.obj_cur, m.obj_prev), "#7C3AED", "44%")
    return section(heading(ctx, "systems") + top + routes + objects)


def ordered_weekdays(ctx):
    first = WEEKDAYS.index(ctx.cfg["week_start"].capitalize())
    return [(first + i) % 7 for i in range(7)]


def sec_heatmap(ctx, m, lim):
    hp = m.heat_peak
    if not hp:
        return ""
    peak = hp["cell_n"] or 1
    labels = "".join('<td class="sr" colspan="3" style="font-size:10px;padding-bottom:3px">{}</td>'.format(
        hour_label(h).replace(" AM", "a").replace(" PM", "p")) for h in range(0, 24, 3))
    rows = ['<tr><td width="34"></td>{}</tr>'.format(labels)]
    for wd in ordered_weekdays(ctx):
        cells = "".join('<td bgcolor="{}" title="{} {}h: {}"></td>'.format(
            heat_color(ctx, m.heat[wd][h], peak), WEEKDAYS[wd][:3], h, m.heat[wd][h])
            if m.heat[wd][h] else "<td></td>" for h in range(24))
        rows.append('<tr height="17" bgcolor="{}"><td class="sr" bgcolor="#FFFFFF" style="font-size:11px;padding-right:6px">'
                    '{}</td>{}</tr>'.format(HEAT_ZERO, WEEKDAYS[wd][:3], cells))
    grid = ('<table class="hm" role="presentation" width="100%" cellpadding="0" cellspacing="2" border="0" '
            'style="border-collapse:separate;table-layout:fixed">{}</table>').format("".join(rows))
    d, h = hp["cell"]
    note = ('<div style="margin-top:8px">{} <span class="sr" style="margin-left:10px">Busiest hour: <b>{} {}</b> ({}) · '
            'busiest 3 hours: {}–{} ({} of errors) · {}</span></div>').format(
        heat_legend(ctx), WEEKDAYS[d][:3], hour_label(h), fmt_int(hp["cell_n"]), hour_label(hp["start"]),
        hour_label((hp["start"] + 3) % 24), fmt_pct(hp["share"]), esc(tz_label(ctx.now)))
    right = "{} · {} to {}".format(plural(ctx.cfg["heatmap_periods"], ctx.period.unit), short_day(m.heat_from),
                                   short_day(ctx.period.end))
    return section(heading(ctx, "heatmap", esc(right)) + grid + note)


def sec_calendar(ctx, m, lim):
    per = ctx.period
    first = WEEKDAYS.index(ctx.cfg["week_start"].capitalize())
    begin = per.buckets[0].start
    start = begin - timedelta(days=(begin.weekday() - first) % 7)
    weeks = ((per.end - start).days // 7) + 1
    values = [m.daily.get(begin + timedelta(days=i), 0) for i in range((per.end - begin).days + 1)]
    peak = max(values) if values else 0
    head, month = [], None
    for w in range(weeks):
        d = start + timedelta(days=7 * w)
        head.append('<td class="ch">{}</td>'.format(
            d.strftime("%b") if d.month != month else ""))
        month = d.month
    rows = ['<tr><td></td>{}</tr>'.format("".join(head))]
    for i, wd in enumerate(ordered_weekdays(ctx)):
        cells = []
        for w in range(weeks):
            d = start + timedelta(days=7 * w + i)
            if d < begin or d > per.end:
                cells.append('<td class="d"></td>')
                continue
            n = m.daily.get(d, 0)
            ring = ' style="outline:1px solid {}"'.format(ctx.cfg["brand_color"]) if d >= per.start else ""
            cells.append('<td class="d" bgcolor="{}" title="{} · {}"{}></td>'.format(heat_color(ctx, n, peak), day_name(d), n, ring))
        rows.append('<tr height="13"><td class="sr" style="font-size:10px;padding-right:5px">{}</td>{}</tr>'.format(
            WEEKDAYS[wd][:3] if i % 2 == 0 else "", "".join(cells)))
    cal = ('<table class="hm" role="presentation" cellpadding="0" cellspacing="3" border="0" style="border-collapse:separate">'
           '{}</table>').format("".join(rows))
    total_days = len(values)
    clean = sum(1 for v in values if not v)
    worst = max(range(total_days), key=lambda i: values[i]) if total_days else 0
    streak = best = 0
    for v in values:
        streak = streak + 1 if not v else 0
        best = max(best, streak)
    stats = [("Days", fmt_int(total_days)), ("Error-free days", "{} ({})".format(fmt_int(clean), fmt_pct(pct(clean, total_days)))),
             ("Average day", fmt_int(mean(values))), ("Median day", fmt_int(median(values))),
             ("Worst day", "{} ({})".format(day_name(begin + timedelta(days=worst)), fmt_int(values[worst])) if peak else "—"),
             ("Longest clean run", plural(best, "day"))]
    side = "".join('<tr class="hv-row"><td class="sr" style="padding:4px 10px 4px 0">{}</td><td class="lv" align="right" '
                   'style="padding:4px 0">{}</td></tr>'.format(k, v) for k, v in stats)
    body = table('<tr><td class="stack" valign="top" style="padding:0 18px 12px 0">{}<div style="margin-top:6px">{}</div>'
                 '</td><td class="stack" valign="top" width="260">{}</td></tr>'.format(cal, heat_legend(ctx), table(side)))
    return section(heading(ctx, "calendar", esc("{} to {}".format(short_day(begin), short_day(per.end)))) + body)


def sec_records(ctx, m, lim):
    if not m.batches:
        return ""
    unit = ctx.period.unit
    items = sorted(m.batches.values(), key=lambda b: (-b["failed"], -b["total"]))[: lim["systems_n"]]
    head = [th("Object"), th("Runs", "right", "hide-sm"), th("Processed", "right"), th("Failed", "right"),
            th("Failure rate", "", "", "30%")]
    rows = []
    for i, b in enumerate(items):
        rate = pct(b["failed"], b["total"]) if b["total"] else None
        color = BAD if rate is not None and rate >= 5 else (WARN if rate is not None and rate >= 1 else GOOD)
        bar = (hbar(min(1.0, rate / 10.0), color, 6) + '<div class="mt">{}</div>'.format(fmt_pct(rate, 2))
               if rate is not None else '<span class="mt">no total</span>')
        rows.append(row(i, [
            tdc('<b style="color:{}">{}</b><div class="mt">{}</div>'.format(INK, esc(b["object"]),
                                                                           esc(clip(b["recipes"].most_common(1)[0][0], 70)))),
            tdc(fmt_int(b["runs"]), "right", "hide-sm"), tdc(fmt_int(b["total"]) if b["has_total"] else "—", "right"),
            tdc(count(b["failed"]), "right"), tdc(bar)]))
    summary = "<b>{}</b> failed in {} this {}".format(plural(m.rec_failed_cur, "record"),
                                                     plural(m.batch_runs_cur, "batch run"), unit)
    if m.rec_total_cur:
        summary += " ({} of {} processed)".format(fmt_pct(pct(m.rec_failed_cur, m.rec_total_cur), 2),
                                                  fmt_int(m.rec_total_cur))
    summary += ". {} <span style=\"color:{}\">vs {} last {}</span>".format(
        delta(m.rec_failed_cur, m.rec_failed_prev), MUTED, fmt_int(m.rec_failed_prev), unit)
    return section(heading(ctx, "records", "bar: full = 10% failed") +
                   '<div style="font-size:14px;color:{};margin:0 0 10px">{}</div>'.format(TEXT, summary) +
                   grid_table(head, rows))


def sec_recovery(ctx, m, lim):
    if not m.cur_n:
        return ""
    known = ["notified", "reprocessed", "failed again", "created"]
    order = sorted(m.status_cur.items(), key=lambda kv: (known.index(kv[0].lower()) if kv[0].lower() in known else 9, -kv[1]))
    segments, legend = [], []
    for name, c in order:
        color = STATUS_COLORS.get(name.lower(), "#94A3B8")
        segments.append('<td width="{}%" height="14" bgcolor="{}" title="{}"></td>'.format(
            max(1, int(round(pct(c, m.cur_n)))), color, esc("{}: {}".format(name, c))))
        legend.append(legend_item(color, "{} <b style='color:{}'>{}</b> ({})".format(
            esc(name), INK, fmt_int(c), fmt_pct(pct(c, m.cur_n)))))
    bar = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
           'class="seg" style="border-radius:7px;overflow:hidden"><tr>{}</tr></table>').format("".join(segments))
    facts = ["Reprocess flag set on <b>{}</b>".format(fmt_int(m.flag_cur))]
    if m.rcount_cur:
        facts.append("reprocessed once {} · twice {} · 3+ {}".format(*(fmt_int(m.rcount_cur.get(i, 0)) for i in (1, 2, 3))))
    facts.append("error files attached to <b>{}</b>".format(fmt_int(m.files_cur)))
    return section(heading(ctx, "recovery") + bar + '<div style="margin-top:10px;line-height:2">{}</div>'.format(
        "".join(legend)) + '<div style="font-size:13px;color:{};margin-top:4px">{}</div>'.format(TEXT, " · ".join(facts)))


def sec_backlog(ctx, m, lim):
    bl = m.backlog
    if bl is None:
        return ""
    if not bl["total"]:
        return section(heading(ctx, "backlog") + empty_note("Nothing waiting: no row has Status Created."))
    head = [th("Recipe"), th("Waiting", "right"), th("Oldest", "right"), th("Notify after", "", "hide-sm"), th("")]
    rows = []
    for i, g in enumerate(bl["groups"][: lim["top_n"]]):
        freq = g["freq"].most_common(1)[0][0]
        limit = g["limit"].most_common(1)[0][0]
        late = pill("{} overdue".format(fmt_int(g["overdue"])), "bad") if g["overdue"] else pill("on time", "good")
        rows.append(row(i, [tdc(recipe_link(ctx, g, 70)), tdc(count(g["count"]), "right"),
                            tdc("{} d".format(g["oldest"]), "right"),
                            tdc("{} or {} errors".format(plural(freq, "day"), fmt_int(limit)), cls="hide-sm"), tdc(late)]))
    summary = ("<b>{}</b> deferred errors are waiting for the summary email; <b>{}</b> are past their notify window and "
               "the oldest is {} days old.".format(fmt_int(bl["total"]), fmt_int(bl["overdue"]), fmt_int(bl["oldest"])))
    if bl["overdue"]:
        summary += " Rows only leave this list when the summary recipe (Email Notification Summary) sends them."
    return section(heading(ctx, "backlog", "all time") +
                   '<div style="font-size:14px;line-height:1.55;color:{};margin:0 0 10px">{}</div>'.format(TEXT, summary) +
                   grid_table(head, rows))


def recipient_label(ctx, key):
    if key == "(no address)" or not ctx.cfg["mask_emails"]:
        return esc(key)
    keep = {a.lower() for a in ctx.public_emails}
    addresses = [a.strip() for a in key.split(",") if a.strip()]
    shown = [a for a in addresses if a in keep]
    hidden = len(addresses) - len(shown)
    parts = [esc(a) for a in shown]
    if hidden:
        parts.append("{}{} {}".format("+" if shown else "", hidden, "person" if hidden == 1 else "people"))
    return " ".join(parts) if parts else esc(key)


def sec_noise(ctx, m, lim):
    if not m.cur_n:
        return ""
    unit, par = ctx.period.unit, m.pareto
    top = m.top[:5]
    segments, legend = [], []

    def legend_row(color, label, share):
        return ('<tr><td width="14" valign="top" style="padding:3px 0"><span class="sq" style="background:{}"></span></td>'
                '<td class="lb" style="padding:2px 8px 2px 0;font-size:12px">{}</td><td class="lv" align="right" '
                'style="padding:2px 0;font-size:12px">{}</td></tr>').format(color, label, fmt_pct(share))
    for i, e in enumerate(top):
        color = SEGMENTS[i % len(SEGMENTS)]
        share = pct(e["cur"], m.cur_n)
        segments.append('<td width="{}%" height="16" bgcolor="{}" title="{}"></td>'.format(
            max(1, int(round(share))), color, esc("{}: {}".format(e["name"], e["cur"]))))
        legend.append(legend_row(color, esc(clip(e["name"], 70)), share))
    rest = m.cur_n - sum(e["cur"] for e in top)
    others = max(0, par["n"] - len(top))
    if rest > 0:
        segments.append('<td width="{}%" height="16" bgcolor="#E2E8F0" title="{}"></td>'.format(
            max(1, int(round(pct(rest, m.cur_n)))), esc("{} other recipes: {}".format(others, rest))))
        legend.append(legend_row("#E2E8F0", "the other {}".format(plural(others, "recipe")), pct(rest, m.cur_n)))
    bar = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
           'class="seg" style="border-radius:8px;overflow:hidden;margin:6px 0 8px"><tr>{}</tr></table>').format("".join(segments))
    text = ("The top 3 recipes caused <b>{}</b> of the errors this {}; <b>80%</b> came from {} of the {} failing "
            "recipes.").format(fmt_pct(par["top3"]), unit, par["k80"], par["n"])
    left = subhead("Errors by recipe") + '<div style="font-size:14px;line-height:1.55;color:{}">{}</div>{}{}'.format(
        TEXT, text, bar, table("".join(legend)))
    peak = m.recipients.most_common(1)[0][1] if m.recipients else 1
    lines = "".join('<tr class="hv-row"><td class="lb" style="font-size:12px">{}</td><td width="34%" style="padding:5px 8px">'
                    '{}</td><td class="lv" width="40" align="right">{}</td></tr>'.format(
                        recipient_label(ctx, k), hbar(c / float(peak), "#0D9488"), fmt_int(c))
                    for k, c in m.recipients.most_common(6))
    right = subhead("Alerts per recipient list") + table(lines)
    return section(heading(ctx, "noise") + table(
        '<tr><td class="stack" width="55%" valign="top" style="padding:0 16px 12px 0">{}</td>'
        '<td class="stack" width="45%" valign="top">{}</td></tr>'.format(left, right)))


def sec_forecast(ctx, m, lim):
    f = m.forecast
    if not f:
        return ""
    per = ctx.period
    method = {"holt": "damped trend (Holt) over {0} {1}s, one-off spikes clipped",
              "average": "average of the last 4 {1}s", "naive": "the last {1} carried forward"}[f["method"]].format(
        per.count, per.unit)
    trend = {"rising": pill("↗ rising", "bad"), "easing": pill("↘ easing", "good"), "flat": pill("→ flat")}[f["trend"]]
    peak = max([v for _, v in f["daily"]] or [1]) or 1
    bars = "".join(vbar(v, peak, 70, mix(INFO, "#FFFFFF", 0.35), "{} · ~{}".format(day_name(d), fmt_int(v)),
                        day_label(v)) for d, v in f["daily"])
    axis = "".join('<td class="ax" align="center">{}</td>'.format(d.strftime("%a")[:2] if per.days <= 14 else "")
                   for d, _ in f["daily"])
    mini = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed">'
            '<tr>{}</tr><tr>{}</tr></table>').format(bars, axis)
    big = ('<div class="sr">{n}</div>'
           '<div style="font-size:40px;font-weight:800;color:{i};line-height:1.1;margin:4px 0">~{p}</div>'
           '<div style="font-size:13px;color:{t}">errors expected · likely {lo}–{hi} {tr}</div>'
           '<div class="sr" style="font-size:11px;margin-top:6px">Method: {me}.</div>').format(
        n=esc("Next {}: {}".format(per.unit, range_label(per.next_start, per.next_end))), i=INFO,
        p=fmt_int(f["point"]), t=TEXT, lo=fmt_int(f["low"]), hi=fmt_int(f["high"]), tr=trend, me=esc(method))
    top = table('<tr><td class="stack" width="45%" valign="top" style="padding:0 16px 14px 0">{}</td>'
                '<td class="stack" valign="bottom" style="padding-bottom:14px">{}</td></tr>'.format(big, mini))
    rows = []
    for i, r in enumerate(f["recipes"][: lim["top_n"]]):
        e = r["recipe"]
        rows.append(row(i, [tdc(recipe_link(ctx, e, 70)), tdc(fmt_int(e["cur"]), "right"),
                            tdc('<b style="color:{}">~{}</b>'.format(INK, fmt_int(r["point"])), "right"),
                            tdc("{}–{}".format(fmt_int(r["low"]), fmt_int(r["high"])), "right", "hide-sm"),
                            tdc({"rising": "↗", "easing": "↘", "flat": "→"}[r["trend"]] +
                                (" " + pill("at risk", "bad") if r["at_risk"] else ""))]))
    table_html = grid_table([th("Recipe"), th("This " + per.unit, "right"), th("Next", "right"),
                             th("Likely", "right", "hide-sm"), th("Trend")], rows) if rows else ""
    return section(heading(ctx, "forecast", "a guide, not a promise") + top + table_html)


def button(label, url, primary=False, brand="#0056D2"):
    bg, fg, bd = ("#EEF4FF", brand, "#D4E1FB") if primary else (SOFT, TEXT, LINE)
    return ('<a class="hv-btn" href="{}" target="_blank" style="display:inline-block;margin:0 8px 8px 0;padding:9px 16px;'
            'background:{};border:1px solid {};border-radius:8px;font-size:13px;font-weight:600;line-height:1.2;color:{};'
            'text-decoration:none">{}</a>').format(esc(url), bg, bd, fg, label)


def sec_actions(ctx, m, lim):
    cfg = ctx.cfg
    log = safe_url(cfg["error_log_url"]) or "{}/data_tables/{}".format(cfg["app_host"].rstrip("/"),
                                                                       urllib_parse.quote(cfg["data_table_id"]))
    buttons = [button("Open the error log &#8594;", log, True, cfg["brand_color"])]
    for label, key in (("Live dashboard", "dashboard_url"), ("Runbook", "runbook_url")):
        if safe_url(cfg[key]):
            buttons.append(button(label, cfg[key]))
    for item in ctx.extra.get("buttons") or []:
        if isinstance(item, dict) and safe_url(item.get("url")) and item.get("label"):
            buttons.append(button(esc(item["label"]), item["url"]))
    return section('<div style="line-height:1;padding-top:4px">{}</div>'.format("".join(buttons)), bottom=14, card=False)


def footer(ctx, m, left_out=()):
    cfg = ctx.cfg
    logo = ('<img src="{}" alt="Team" height="32" style="height:32px;width:auto;border:0;display:inline-block">'.format(
        esc(cfg["team_logo_url"])) if safe_url(cfg["team_logo_url"]) else "")
    team = ('<div style="font-size:14px;font-weight:700;color:#4A154B;margin:8px 0 10px">{}</div>'.format(esc(cfg["team_name"]))
            if cfg["team_name"] else "")
    links = []
    if cfg["alert_email"]:
        links.append(link("Email", "mailto:{}?subject={}".format(cfg["alert_email"], urllib_parse.quote(
            "{} report {}".format(cfg["title"], ctx.period.label)))))
    for label, key in (("ServiceNow", "servicenow_url"), ("Slack", "slack_url"), ("Team Charter", "charter_url")):
        if safe_url(cfg[key]):
            links.append(link(label, cfg[key]))
    latest = max((r["ts"] for r in ctx.rows if r["ts"]), default=None)
    data = "Built from {} rows of the error log{}{}.".format(
        fmt_int(len(ctx.rows)), " read in {} pages".format(fmt_int(ctx.pages)) if ctx.pages else "",
        ", the latest {} {}".format(day_name(latest.date()), clock(latest)) if latest else "")
    if left_out:
        data += " Left out to keep this email small: {}.".format(", ".join(title_of(ctx, s) or s for s in left_out))
    return ('<tr><td class="px" bgcolor="{s}" style="background:{s};border-top:1px solid {l};padding:22px 32px;text-align:center">'
            '{logo}{team}<div class="sr">{links}</div>'
            '<div style="font-size:11px;line-height:1.6;color:{f};margin-top:10px">{data} Automated report from Workato '
            'integration monitoring · error_dashboard {v} · built {when}</div></td></tr>').format(
        s=SOFT, l=LINE, logo=logo, team=team, links=" &nbsp;·&nbsp; ".join(links), f=FAINT, data=esc(data),
        v=VERSION, when=esc("{} {} {}".format(day_name(ctx.today), clock(ctx.now), tz_label(ctx.now))))


BUILDERS = {"hero": sec_hero, "kpis": sec_kpis, "insights": sec_insights, "trend": sec_trend, "weekly": sec_weekly,
            "recipes": sec_recipes, "movers": sec_movers, "patterns": sec_patterns, "categories": sec_categories,
            "systems": sec_systems, "heatmap": sec_heatmap, "calendar": sec_calendar, "records": sec_records,
            "recovery": sec_recovery, "backlog": sec_backlog, "noise": sec_noise, "forecast": sec_forecast,
            "actions": sec_actions}


def render(ctx, m, sections, lim, left_out=()):
    cfg = ctx.cfg
    parts, rendered = [], []
    for name in sections:
        html = BUILDERS[name](ctx, m, lim)
        if html:
            parts.append(html)
            rendered.append(name)
    if "hero" not in rendered:
        parts.insert(0, '<tr><td bgcolor="{0}" style="height:6px;line-height:6px;font-size:0;background:{0}">&nbsp;</td></tr>'
                        '<tr><td class="px" style="padding:20px 32px 14px;font-size:20px;font-weight:800;color:{1}">{2} · {3}'
                        '</td></tr>{4}'.format(cfg["brand_color"], INK, esc(cfg["title"]), esc(ctx.period.label), PAGE_GAP))
    # One <style> block for the layout and the hover rules, as error_notification.py does: when the hover rules sat in a
    # second block of their own, the layout showed in the mail client but the hover did not.
    css = (CSS.replace("__FONT__", FONT).replace("__BRAND__", cfg["brand_color"])
           .replace("__LIGHT__", mix(cfg["brand_color"], "#FFFFFF", 0.55)))
    if cfg["hover_effects"]:
        css += hover_css(cfg)
    css = "<style>{}</style>".format(css)
    ribbon = ('<tr><td style="padding:0 8px 10px;font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;'
              'color:{}">● {} &nbsp;·&nbsp; Workato &nbsp;·&nbsp; {}</td></tr>').format(
        MUTED, esc(ctx.env_label or "Workato"), esc(unit_label(ctx) + " report"))
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        '<title>{title}</title>{css}</head>'
        '<body style="margin:0;padding:0;background:{frame}">'
        '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;opacity:0;color:transparent">{pre}{sp}</div>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{frame}" '
        'style="background:{frame}"><tr><td class="outer" align="center" style="padding:24px 10px;font-family:{font};color:{text}">'
        '<!--[if mso]><table role="presentation" width="{w}" align="center" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:{w}px">'
        '{ribbon}<tr><td bgcolor="#FFFFFF" style="background:#FFFFFF;border-radius:18px;overflow:hidden;'
        'box-shadow:0 1px 3px rgba(15,23,42,.08),0 10px 28px rgba(15,23,42,.07)">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{body}{foot}</table>'
        '</td></tr></table><!--[if mso]></td></tr></table><![endif]--></td></tr></table></body></html>'
    ).format(title=esc(ctx.subject), css=css, frame=ctx.frame, pre=esc(ctx.preheader), sp="&zwnj;&nbsp;" * 40,
             font=FONT, text=TEXT, w=cfg["max_width"], ribbon=ribbon, body="".join(parts),
             foot=footer(ctx, m, left_out))
    return html, rendered


# ------------------------------------------------------------- subject and text


def build_subject(ctx, m):
    s = m.score
    change = "—" if m.change is None else "{}{}".format("▲" if m.change >= 0 else "▼", fmt_pct(abs(m.change)))
    if m.change is None and m.cur_n and not m.prev_n:
        change = "new"
    emoji = s["emoji"] if s else ("🔴" if (m.change or 0) >= 25 else "🟢" if (m.change or 0) <= -10 else "🟡")
    values = {"emoji": emoji, "title": ctx.cfg["title"], "env": ctx.env_label, "ENV": ctx.env_label.upper(),
              "period": range_label(ctx.period.start, ctx.period.end, year=False), "errors": fmt_int(m.cur_n),
              "previous": fmt_int(m.prev_n), "change": change, "score": s["score"] if s else "",
              "grade": s["grade"] if s else "", "recipes": fmt_int(m.recipes_cur),
              "new_patterns": fmt_int(len(m.new_patterns)),
              "forecast": fmt_int(m.forecast["point"]) if m.forecast else ""}
    subject = fill(ctx.cfg["subject_format"], values)
    subject = re.sub(r"\(\s*\)", "", re.sub(r"\s{2,}", " ", subject)).strip(" ·|-")
    return subject or "{} · {}".format(ctx.cfg["title"], ctx.period.label)


def build_preheader(ctx, m):
    parts = [headline(ctx, m)]
    if m.score:
        parts.append("Health {} ({})".format(m.score["score"], m.score["grade"]))
    if m.new_patterns:
        parts.append(plural(len(m.new_patterns), "new pattern"))
    return clip(" · ".join(parts), 160)


def build_text(ctx, m):
    per, unit = ctx.period, ctx.period.unit
    lines = ["{} · {}".format(ctx.cfg["title"], per.label), headline(ctx, m)]
    if m.score:
        lines.append("Health score: {} ({})".format(m.score["score"], m.score["grade"]))
    lines += ["", "Errors: {} (last {}: {})".format(fmt_int(m.cur_n), unit, fmt_int(m.prev_n)),
              "Recipes affected: {} (last {}: {})".format(m.recipes_cur, unit, m.recipes_prev),
              "New patterns: {}".format(len(m.new_patterns))]
    if m.rec_failed_cur:
        lines.append("Records failed in batches: {}".format(fmt_int(m.rec_failed_cur)))
    if m.forecast:
        lines.append("Next {}: ~{} (likely {}-{})".format(unit, fmt_int(m.forecast["point"]), fmt_int(m.forecast["low"]),
                                                          fmt_int(m.forecast["high"])))
    if ctx.ai:
        lines += ["", "Summary: " + ctx.ai["summary"].replace("**", "")]
    if ctx.insights:
        lines += ["", "What stands out:"] + ["  - " + plain(i["html"]) for i in ctx.insights]
    if m.top:
        lines += ["", "Top failing recipes:"]
        lines += ["  {}. {} - {} (was {}){}".format(i + 1, e["name"], e["cur"], e["prev"],
                                                    " " + recipe_url(ctx, e["rid"]) if e["rid"] else "")
                  for i, e in enumerate(m.top[:10])]
    return "\n".join(lines)


def build_slack(ctx, m):
    unit = ctx.period.unit
    s = m.score
    change = "" if m.change is None else " ({}{} vs last {})".format("+" if m.change >= 0 else "", fmt_pct(m.change), unit)
    lines = ["*{} · {}*{}".format(ctx.cfg["title"], ctx.period.label,
                                  "  {} *{}* ({})".format(s["emoji"], s["score"], s["grade"]) if s else ""),
             "*{}* errors{} across *{}*".format(fmt_int(m.cur_n), change, plural(m.recipes_cur, "recipe"))]
    for e in m.top[:5]:
        name = e["name"].replace("<", "‹").replace(">", "›").replace("|", "¦")
        url = recipe_url(ctx, e["rid"])
        lines.append("• {} — {} (was {})".format("<{}|{}>".format(url, name) if url else name, e["cur"], e["prev"]))
    for i in ctx.insights[:3]:
        lines.append("{} {}".format(i["icon"], plain(i["html"])))
    return "\n".join(lines)


# -------------------------------------------------------------------------- main


def current_time(cfg, tz):
    if cfg["now"]:
        dt = parse_dt(cfg["now"], tz)
        if dt:
            return dt
    return datetime.now(timezone.utc).astimezone(tz)


def outputs(result, ctx, m):
    per = ctx.period
    result.update({
        "period_label": per.label, "period_start": per.start.isoformat(), "period_end": per.end.isoformat(),
        "previous_start": per.prev_start.isoformat(), "previous_end": per.prev_end.isoformat(),
        "errors_total": m.cur_n, "errors_previous": m.prev_n,
        "change_pct": round(m.change, 1) if m.change is not None else None,
        "recipes_affected": m.recipes_cur, "recipes_affected_previous": m.recipes_prev,
        "new_patterns": len(m.new_patterns), "records_failed": m.rec_failed_cur,
        "reprocessed": sum(v for k, v in m.status_cur.items() if k.lower() == "reprocessed"),
        "backlog_open": (m.backlog or {}).get("total", 0), "backlog_oldest_days": (m.backlog or {}).get("oldest", 0),
        "spikes": len(m.spikes_in_period), "insights": [plain(i["html"]) for i in ctx.insights], "ai_used": bool(ctx.ai), "ai_error": ctx.ai_error,
        "rows_used": len(ctx.rows),
    })
    if m.score:
        result.update({"health_score": m.score["score"], "health_grade": m.score["grade"]})
    if m.forecast:
        result.update({"forecast_next": int(round(m.forecast["point"])), "forecast_low": int(round(m.forecast["low"])),
                       "forecast_high": int(round(m.forecast["high"])), "forecast_trend": m.forecast["trend"]})
    result["top_recipes"] = [{
        "name": e["name"], "recipe_id": e["rid"], "url": recipe_url(ctx, e["rid"]), "errors": e["cur"],
        "previous": e["prev"], "change_pct": round(change_pct(e["cur"], e["prev"]), 1) if e["prev"] else None,
        "share_pct": round(pct(e["cur"], m.cur_n), 1), "status": e["status"],
        "category": category_info(e["cat"], ctx.rules)[0], "source": e["route"][0], "target": e["route"][1],
        "owner": e["owner"]} for e in m.top[: ctx.cfg["top_n"]]]
    result["top_patterns"] = [{
        "signature": p["sig"], "example": clip(shown_message(ctx, p["example"]), 300), "errors": p["cur"],
        "previous": p["prev"], "is_new": p["status"] == "new", "category": category_info(p["cat"], ctx.rules)[0],
        "recipes": [n for n, _ in p["recipes_cur"].most_common(5)], "first_seen": p["first"].isoformat()}
        for p in m.patterns_top[: ctx.cfg["patterns_n"]]]
    summary = {k: result[k] for k in ("period_start", "period_end", "errors_total", "errors_previous", "change_pct",
                                      "recipes_affected", "recipes_affected_previous", "new_patterns", "records_failed",
                                      "reprocessed", "backlog_open", "backlog_oldest_days", "spikes", "health_score",
                                      "health_grade", "forecast_next", "forecast_low", "forecast_high", "forecast_trend",
                                      "top_recipes", "top_patterns", "insights")}
    summary.update({"weekly": dict(zip([b.start.isoformat() for b in per.buckets], m.weekly)),
                    "categories": {category_info(k, ctx.rules)[0]: v for k, v in m.cats_cur.most_common()},
                    "target_systems": dict(m.tgt_cur.most_common()), "source_systems": dict(m.src_cur.most_common()),
                    "statuses": dict(m.status_cur), "version": VERSION})
    result["summary_json"] = json.dumps(summary, ensure_ascii=False, default=str)


def fit_size(ctx, m, warnings):
    """(html for the email, sections in it, full html). When the email is over html_limit_kb, the steps of TRIM_ORDER
    are taken until it fits: sections left out (the footer names them) and lists cut to 6 rows. The full html keeps
    everything, for an attachment or a file."""
    cfg = ctx.cfg
    lim = {k: cfg[k] for k in ("top_n", "patterns_n", "movers_n", "systems_n")}
    sections = list(ctx.sections)
    full, rendered = render(ctx, m, sections, lim)
    limit = cfg["html_limit_kb"] * 1024

    def size(text):
        return len(text.encode("utf-8"))
    if not limit or size(full) <= limit:
        return full, rendered, full
    html, dropped, shortened = full, [], False
    for step in TRIM_ORDER:
        if size(html) <= limit:
            break
        if step == "lists":
            if any(v > 6 for v in lim.values()):
                lim = {k: min(v, 6) for k, v in lim.items()}
                shortened = True
            else:
                continue
        elif step in rendered:
            sections.remove(step)
            dropped.append(step)
        else:
            continue
        html, rendered = render(ctx, m, sections, lim, dropped)
    if shortened:
        warnings.append("lists cut to 6 rows to keep the email under {} KB (html_full has them all)".format(
            cfg["html_limit_kb"]))
    if dropped:
        warnings.append("sections left out of the email to keep it under {} KB (html_full has them): {}".format(
            cfg["html_limit_kb"], ", ".join(dropped)))
    if size(html) > limit:
        warnings.append("html is {} KB, over html_limit_kb; Gmail may clip it".format(size(html) // 1024))
    return html, rendered, full


def error_html(title, message):
    return ('<!DOCTYPE html><html><body style="margin:0;padding:24px;background:#F8FAFC;font-family:Arial,sans-serif">'
            '<div style="max-width:640px;margin:0 auto;background:#FFFFFF;border:1px solid #FECACA;border-radius:12px;'
            'padding:20px 22px"><div style="font-size:18px;font-weight:800;color:#991B1B">{}</div>'
            '<p style="font-size:14px;color:#334155">The weekly dashboard could not be built:</p>'
            '<pre style="white-space:pre-wrap;font-size:12px;color:#0F172A;background:#F1F5F9;padding:10px;border-radius:8px">{}'
            '</pre></div></body></html>').format(esc(title), esc(message))


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    started = time.time()
    result = {k: (list(v) if isinstance(v, list) else v) for k, v in OUTPUT_DEFAULTS}
    warnings = []
    inp = input if isinstance(input, dict) else {}
    cfg = None
    try:
        cfg, more = settings(inp)
        warnings.extend(more)
        tz = get_tz(cfg["timezone"])
        now = current_time(cfg, tz)
        ctx = SimpleNamespace(cfg=cfg, extra=cfg["extra"], tz=tz, now=now, today=now.date(), status={}, ai=None, ai_error="",
                              insights=[], pages=0, msg_cache={}, system_cache={}, data_complete=True)
        ctx.period = resolve_period(cfg, now, warnings)
        ctx.sections = resolve_sections(cfg, warnings)
        ctx.rules = category_rules(ctx.extra)
        ctx.system_aliases = {text_of(k).strip().lower(): text_of(v) for k, v in
                              (ctx.extra.get("system_aliases") or {}).items() if text_of(v).strip()}
        ctx.public_emails = [a.lower() for a in EMAIL_RE.findall(" ".join(
            [cfg["alert_email"]] + split_list(ctx.extra.get("public_emails") or [])))]
        colors = [css_color(c) for c in (ctx.extra.get("heat_colors") or []) if css_color(c)]
        ctx.heat_colors = tuple(colors) if len(colors) >= 3 else HEAT
        env_key = ENV_ALIASES.get(cfg["env"].upper(), cfg["env"].upper())
        ctx.env_label, ctx.frame = ENVIRONMENTS.get(env_key, (cfg["env"].title() if cfg["env"] else "", "#FFF8E1"))
        result["to_email"] = cfg["to_email"] or cfg["alert_email"]
        deadline = started + cfg["time_budget"]
        ai_on = cfg["ai"] and bool(cfg["azure_api_key"]) and "insights" in ctx.sections
        reserve = (min(25, cfg["time_budget"] * 0.35) if ai_on else 0) + (6 if cfg["recipe_status"] else 0)
        want_backlog = bool({"backlog", "kpis", "insights", "hero"} & set(ctx.sections)) or cfg["health_score"]

        # 1. The rows: given (rows_json), or read from the data table
        if cfg["rows_json"]:
            raw = load_rows_json(cfg["rows_json"])
            if raw is None:
                raise ValueError("rows_json is not a JSON list of rows")
            raw_backlog = raw if want_backlog else None
        elif cfg["workato_api_token"]:
            raw, raw_backlog, ctx.data_complete, reader = fetch_rows(ctx, deadline - reserve, warnings, want_backlog)
            ctx.pages = reader.pages
            result["pages_read"] = reader.pages
        else:
            raise ValueError("workato_api_token is required to read the data table (or give rows_json)")
        result["rows_read"] = ctx.pages and reader.rows_read or len(raw)
        ctx.rows = normalize_rows(raw, ctx)
        ctx.backlog_rows = normalize_rows(raw_backlog, ctx, window=False) if raw_backlog is not None else None

        # 2. The numbers
        m = analyze(ctx)
        if cfg["recipe_status"] and cfg["workato_api_token"] and not cfg["rows_json"] and m.top:
            keys = [e["key"] for e in m.top[: cfg["top_n"]]] + [e["key"] for e in m.rising[:5]]
            ctx.status = fetch_recipe_status(ctx, list(dict.fromkeys(keys)), deadline - (reserve - 6), warnings)
        ctx.insights = build_insights(ctx, m)
        if ai_on and m.cur_n:
            ctx.ai = ai_summary(ctx, m, deadline, warnings)

        # 3. The dashboard
        ctx.subject = build_subject(ctx, m)
        ctx.preheader = build_preheader(ctx, m)
        html, rendered, full = fit_size(ctx, m, warnings)
        result.update({"html": html, "html_full": full, "subject": ctx.subject, "preheader": ctx.preheader, "sections_rendered": rendered,
                       "text_body": build_text(ctx, m), "slack_text": build_slack(ctx, m),
                       "data_complete": ctx.data_complete, "ok": True})
        result["send_email"] = not (cfg["skip_if_empty"] and not m.cur_n)
        outputs(result, ctx, m)
    except Exception as exc:  # noqa: BLE001 - the recipe gets an answer it can branch on
        result["ok"] = False
        result["error"] = "{}: {}".format(type(exc).__name__, clip(str(exc), 400))
        result["data_complete"] = False
        result["send_email"] = False
        title = (cfg or {}).get("title") or "Integration health"
        result["subject"] = "⚠️ {}: the dashboard could not be built".format(title)
        result["html"] = error_html(title, result["error"])
        result["text_body"] = result["error"]
    result["warnings"] = warnings
    result["html_bytes"] = len(result["html"].encode("utf-8"))
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    return result


# ------------------------------------------------------------- schemas and CLI


def input_schema():
    names = ", ".join(n for n, _ in SECTION_HELP)
    fields = []
    for spec in SETTINGS:
        name, kind = spec[0], spec[1]
        if name in CONFIG_ONLY:
            continue
        label, hint = INPUT_HELP.get(name, (name.replace("_", " ").capitalize(), ""))
        if name == "sections":
            hint += names
        field = {"control_type": "text", "label": label, "name": name, "type": "string", "optional": True}
        if kind == "secret":
            field["control_type"] = "password"
        if name in ("config_json", "rows_json", "note", "ai_instructions"):
            field["control_type"] = "text-area"
        if kind == "int" or kind == "float":
            conv = "integer_conversion" if kind == "int" else "float_conversion"
            field.update({"control_type": "integer" if kind == "int" else "number",
                          "type": "integer" if kind == "int" else "number", "parse_output": conv, "render_input": conv})
            field["hint"] = "{} ({} to {})".format(hint, spec[3], spec[4]) if hint else "{} to {}".format(spec[3], spec[4])
        elif hint:
            field["hint"] = hint
        options = None
        if kind == "bool":
            options = [["Yes", "yes"], ["No", "no"]]
        elif name in CHOICES:
            options = [[o.capitalize(), o] for o in CHOICES[name]]
        if options:
            field.update({"control_type": "select", "pick_list": options, "toggle_hint": "Select from list",
                          "toggle_field": {"control_type": "text", "label": label, "name": name, "type": "string",
                                           "optional": True, "toggle_hint": "Use custom value"}})
        if name == "workato_api_token":
            field["optional"] = False
        fields.append(field)
    return fields


def output_schema():
    def kind(name, value):
        if isinstance(value, bool):
            return {"control_type": "checkbox", "label": label(name), "name": name, "type": "boolean", "optional": True,
                    "render_input": "boolean_conversion", "parse_output": "boolean_conversion"}
        if name in ("errors_total", "errors_previous", "recipes_affected", "recipes_affected_previous", "new_patterns",
                    "records_failed", "reprocessed", "backlog_open", "backlog_oldest_days", "spikes", "health_score",
                    "forecast_next", "forecast_low", "forecast_high", "rows_read", "rows_used", "pages_read",
                    "html_bytes", "elapsed_ms"):
            return {"control_type": "integer", "label": label(name), "name": name, "type": "integer", "optional": True,
                    "parse_output": "integer_conversion"}
        if name == "change_pct":
            return {"control_type": "number", "label": label(name), "name": name, "type": "number", "optional": True,
                    "parse_output": "float_conversion"}
        if name in ("warnings", "insights", "sections_rendered"):
            return {"name": name, "label": label(name), "type": "array", "of": "string", "optional": True}
        if name == "top_recipes":
            props = [("name", "string"), ("recipe_id", "string"), ("url", "string"), ("errors", "integer"),
                     ("previous", "integer"), ("change_pct", "number"), ("share_pct", "number"), ("status", "string"),
                     ("category", "string"), ("source", "string"), ("target", "string"), ("owner", "string")]
        elif name == "top_patterns":
            props = [("signature", "string"), ("example", "string"), ("errors", "integer"), ("previous", "integer"),
                     ("is_new", "boolean"), ("category", "string"), ("first_seen", "string")]
        else:
            return {"control_type": "text", "label": label(name), "name": name, "type": "string", "optional": True}
        properties = [{"name": n, "label": label(n), "type": t, "optional": True} for n, t in props]
        if name == "top_patterns":
            properties.append({"name": "recipes", "label": "Recipes", "type": "array", "of": "string", "optional": True})
        return {"name": name, "label": label(name), "type": "array", "of": "object", "optional": True,
                "properties": properties}

    def label(name):
        return name.replace("_", " ").capitalize().replace("Html", "HTML").replace("Pct", "%").replace("Ai ", "AI ")
    return [kind(name, value) for name, value in OUTPUT_DEFAULTS]


def load_csv(path):
    """The data table's CSV export as rows (for local previews only)."""
    import csv
    csv.field_size_limit(10 ** 9)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Build the integration health dashboard locally.")
    parser.add_argument("input_json", nargs="?", help="a JSON file with the step's inputs")
    parser.add_argument("--csv", help="the error log data table exported as CSV (instead of reading the API)")
    parser.add_argument("--out", help="where to write the html")
    parser.add_argument("--set", action="append", default=[], help="override an input: name=value")
    parser.add_argument("--write-schemas", action="store_true", help="write the input and output schema files")
    args = parser.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    if args.write_schemas:
        for name, schema in (("error_dashboard_input_schema.json", input_schema()),
                             ("error_dashboard_output_schema.json", output_schema())):
            with open(os.path.join(here, name), "w", encoding="utf-8") as handle:
                json.dump(schema, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            print("wrote", name)
        sys.exit(0)
    data = {}
    if args.input_json:
        with open(args.input_json, encoding="utf-8") as handle:
            data = json.load(handle)
    if args.csv:
        data["rows_json"] = load_csv(args.csv)
    for item in args.set:
        key, _, value = item.partition("=")
        data[key] = value
    output = main(data)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output["html"])
    summary = {k: v for k, v in output.items() if k not in ("html", "text_body", "summary_json", "slack_text")}
    json.dump(summary, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
