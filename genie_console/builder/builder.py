"""
Genie Console -- configure a channel genie from Slack, one step per message.

THREE RECIPES, ONE PYTHON STEP
    1. Trigger recipe   someone types "recipeconfig" -> call the function
                        recipe (async) with action = "start".
    2. Function recipe  runs main(input) from this file. Nothing else.
    3. Click recipe     a Slack button click whose action_id contains
                        "gc_console" -> call the function recipe with
                        action_id + payload_json. Every button's id carries
                        it (see ACTION_* below), so a new button needs no
                        change to the recipe's filter.

THE STEPS (each one is a Slack message in the setup thread)
    1. persona   pick one persona from a list            -> Submit
    2. projects  pick Workato projects (multi select)    -> Submit
                 100 per page (Slack's limit for one select); "My project
                 isn't listed" / "Previous" page through the rest, and picks
                 are saved to the row as you go so none are lost between pages.
                 The assets of every chosen project folder are fetched here
                 and stored as JSON in recipes / lookup_tables / data_tables.
                 The same loop finds each project's owner (see project_owner)
                 and stores {name, mention} on the project, so the genie is
                 handed who to tag with every question and needs no skill
    3. details   genie name, keyword, channel, and what the genie should do
                                                         -> Next
    4. kb        attach a knowledge base? A name, a description and when the
                 genie should use it (the two texts are saved together as
                 the description, and Integra puts them in the genie's
                 instructions), then Create knowledge base or Skip. Create makes it through the
                 Workato API in the genie's folder and shows its name and ID;
                 it is attached to the genie on Confirm. Either button starts
                 Integra. An empty or refused Create re-renders the step with
                 the reason, and Skip still works.
                 Documents: when the kb_doc_detail input lists some, a dropdown
                 of them sits under the description. If any are picked, Create
                 doesn't start Integra: it returns call_kb_attach = true with
                 kb_id and selected_kb_file. The recipe attaches those documents
                 to the knowledge base itself (nothing here can), then calls this
                 step again with action = kb_attach_result, kb_attach_status =
                 success or failed and kb_attach_error. That is shown on the
                 knowledge base's line in Slack and Integra starts (call_forge). A
                 failure to attach never stops the build: the knowledge base is
                 just left empty.
                 The details step also asks which skills to create: "all actions" (every
                 skill Integra plans is built, up to MAX_SKILLS) or "let me choose": after the
                 plan the build pauses (call_forge stays false) and a dropdown of the planned
                 skills is posted; gc_console_skills_pick builds only the ticked ones.
    5. build     the step returns call_forge = true. The function recipe runs
                 "Assign task to genie" on Integra with forge_task_instructions,
                 then calls this step again with action = forge_result and
                 Integra's genie_id / skills_json / error. Integra reads the
                 projects, finds the objects they sync (quote, order, invoice)
                 and their IDs, builds read-only lookup skills and creates the
                 genie with them (forge_genie_job_description.md).
                 A skill that can't be built gets a red cross and the build
                 carries on with the next; a failure Integra can't get past (no
                 plan, no genie) shows Try again.
    6. confirm   summary incl. the new genie, its skills and its knowledge
                 base -> Confirm / Cancel
                 Confirm attaches the knowledge base, starts the skill recipes
                 and then the genie itself
                 through the Workato API (a genie is created stopped, and AIRO
                 MCP has no tool to start one). It also makes sure the Slack app
                 is in the genie's channel: the responder only sees a channel's
                 messages while the app is a member, so a genie in a new channel
                 answers with no change to any recipe. (An app joins public
                 channels itself; a private one has to invite it.)
MANAGING SKILLS LATER (the manage card)
    Add skills      copies the genie's row into a run row (key draft:add<timestamp>) and
                    starts the same Integra loop on it in mode add_skills: plan only what the
                    genie lacks, the person picks, build, attach (instructions untouched).
                    finish_add puts the new skills on the genie's own row and starts them.
    Remove skills   a dropdown of the genie's skills; the ticked ones are detached with
                    Workato's remove_skills API and their recipes stopped.
On Submit the step's message is edited into a one-line "done" and the next
step is posted beneath it. A bad answer re-renders the same step with the
reason, so the loop only moves forward on valid input.

STATE
    The data table row is the only state. While a setup is in progress the row's
    record_key is "draft:<thread_ts>"; every button carries that key in its
    value, so a click finds its row with nothing else to remember. Confirm
    rekeys the row to "<KEYWORD>:<CHANNEL_ID>" -- the key the router recipe
    looks up -- so an unfinished draft can never answer a question.
    Integra's work is kept in rows of their own (record_type forge_part, key
    "forge:<thread_ts>:s0".."s5" for the planned skills and ":notes" for the
    project notes): a full plan and the notes together pass the 10,000 characters
    one text column holds. The setup row's forge_state is only the outline --
    job, next, folder, card, each skill's name and state, and the knowledge
    base's id and name (put there by the kb step, before Integra starts).

DESIGN NOTES
    * Column UUIDs appear exactly once, in COLUMNS. None = not in the table yet.
    * Personas are data (PERSONAS); add one by adding an entry.
    * Asset lists are stored as compact JSON [{"id":..,"name":..}] so the master
      genie can be handed exact IDs. A text column holds 10,000 characters, so
      lists are capped at COLUMN_LIMIT and a warning says what was cut.
    * dry_run: reads still happen, but nothing is posted or written; the blocks
      that would have been posted come back in blocks_json.

WHO MAY CREATE A GENIE
    authorized_users   comma-separated email addresses. When set, only those people can start a
                       setup (recipeconfig) or make a new genie from the chooser; anyone else gets
                       a polite message only they can see, and nothing is saved. Matched against
                       the Slack profile email (needs users:read.email), ignoring case. Blank = no
                       limit. If the email can't be read, or the list holds no address, nobody
                       is let through. Managing an existing genie stays with its creator and the
                       owners of its projects.

OPTIONAL INPUTS FOR THE LOOK (add them to the function recipe's input schema; blank = default)
    persona_picker  list | carousel   the persona step: a dropdown (default) or one card per persona
    look            new | single | old   the confirm summary: a table per kind (default), one
                                      combined table, or the old text lists. old also gives the
                                      first version of the "channel already has a genie" screen.
                                      Slack refusing a look falls back to the next plainer one and
                                      says why in warnings. Persona carousel: refused -> dropdown.
    "No skills" is offered on the details step and again when the skills are listed to pick from.

Input and output schemas: genie_console_input_schema.json /
genie_console_output_schema.json
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

TABLE_ID = "6d53d2dd-c00d-4130-aa1c-b0cbfdcc484c"            # genie_console
TABLE_QUERY_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
TABLE_RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
TABLE_RECORD_URL = TABLE_RECORDS_URL + "/{}"
TABLE_SCHEMA_URL = "https://www.workato.com/api/data_tables/{}".format(TABLE_ID)

WORKATO_API = "https://www.workato.com/api"
PROJECTS_URL = WORKATO_API + "/projects?page={}&per_page=100"
FOLDER_ASSETS_URL = WORKATO_API + "/export_manifests/folder_assets?folder_id={}"
RECIPE_START_URL = WORKATO_API + "/recipes/{}/start"   # AIRO MCP has no start tool
RECIPE_STOP_URL = WORKATO_API + "/recipes/{}/stop"     # ...nor a stop tool
GENIE_API_URL = WORKATO_API + "/agentic/genies/{}"     # GET one genie (its "state")
GENIE_START_URL = GENIE_API_URL + "/start"             # POST, no body. A new genie is created
                                                       # stopped; genie_update can't start it
GENIE_REMOVE_SKILLS_URL = GENIE_API_URL + "/remove_skills"   # POST {"skill_ids": [..]}; answers
                                                       # with the skills still on the genie
KB_URL = WORKATO_API + "/agentic/knowledge_bases"      # POST creates one; AIRO has no such tool
KB_ASSIGN_URL = GENIE_API_URL + "/assign_knowledge_bases"   # POST {"knowledge_base_ids": [id]};
                                                       # genie_create has no field for one
# The two create-knowledge-base fields the docs mark required but give no values for. "recipe"
# is the docs' own example; data_sources is left out of the request while this is empty.
KB_SOURCE_TYPE = "recipe"
KB_DATA_SOURCES = ""
FOLDER_RECIPES_URL = WORKATO_API + "/recipes?folder_id={}&page={}&per_page=100"
FOLDERS_URL = WORKATO_API + "/folders"                 # ...nor a create-folder tool
RECIPE_URL = WORKATO_API + "/recipes/{}?exclude_code=yes"   # + &version_no=N for an older version
GENIE_FOLDER_NAME = "Genie - {}"                       # where Integra puts a genie + its skills
# The shared skill every genie gets: hands recipe / job / table questions to the
# master genie (which has AIRO MCP). Its handle comes in as analyst_skill_handle.
ANALYST_SKILL_NAME = "Workato · Ask integration analyst"
GENIE_URL = "https://app.workato.com/genies/{}/overview"
KB_PAGE_URL = "https://app.workato.com/knowledge/{}"
PROJECT_URL = "https://app.workato.com/recipes?fid={}#assets"

SLACK_API = "https://slack.com/api/"
# Added to every message the step posts or edits: links in them (the genie, its knowledge base,
# the projects) are for clicking, and Slack would otherwise unfold each into a big preview card.
NO_UNFURL = {"unfurl_links": False, "unfurl_media": False}

HTTP_TIMEOUT = 30
PROJECT_PAGES = 10
COLUMN_LIMIT = 9500              # 500 under the 10,000-character column limit
PART_TYPE = "forge_part"         # record_type of the rows holding Integra's plan, results, notes
SPEC_TEXT_MAX = 1500             # longest string kept in a planned skill's spec or result
SPEC_ITEMS_MAX = 40              # most entries kept of any list in them
NOTES_MAX = 8000                 # characters of project notes kept
SLACK_OPTIONS_MAX = 100          # a Slack select holds at most 100 options
SLACK_OPTION_TEXT = 75           # ...each with at most 75 characters of text
PLACEHOLDER_MAX = 150            # Slack's limit for a placeholder
SUMMARY_LIST_MAX = 10            # assets listed per type on the confirm step (text lists, one table)
SUMMARY_TABLE_ROWS = 100         # rows in one confirm table, header included; the rest is "… and N more"
SUMMARY_NAME_MAX = 55            # characters of each asset name shown there
SUMMARY_COLOR = "#2eb886"        # the confirm summary's attachment bar
OWNER_EMAIL_DOMAIN = "coursera.org"   # a project's owner: first recipe version written by this domain
OWNER_MAX_VERSIONS = 30          # one request per version walked, so this bounds the work

RECORD_TYPE = "channel_genie"
DRAFT_PREFIX = "draft:"
CANCELLED_PREFIX = "cancelled:"

# --------------------------------------------------------------------------
# Column map -- the only place a field UUID appears
# --------------------------------------------------------------------------

COLUMNS = {
    "record_type":     "f7253c35-2566-411e-9e60-c273e271d0db",
    "record_key":      "a68f2119-5168-4cca-b28c-f25b8d998ea3",
    "id":              "434caf4f-8243-42e3-8ec8-d0732829458e",   # master genie handle
    "channel":         "910af0ed-f992-4707-a509-be760593b203",   # channel ID
    "workato_projects": "bb65e886-001e-4c76-98e1-e39c30b0b7b5",  # JSON
    "recipes":         "68ffbdfa-b286-4821-81b2-e1115603d599",   # JSON
    "lookup_tables":   "517959b3-745c-4742-bf2a-a63002d85694",   # JSON
    "data_tables":     "15f782e5-ebcd-4ae4-a2f6-3126cf94d424",   # JSON
    "creator_name":    "bfe00319-33f9-457a-8e9c-2d4d743a3a5f",
    "creator_id":      "7791d979-e9ea-407b-9e19-dab7facce631",
    "creator_email":   "94fa5f94-ce4e-4d6e-944f-d4ec9a4621ee",
    "invoke_keyword":  "e11379fd-9f0e-4462-b591-628601c7acc3",
    "persona":         "6e2cf0fc-bbaf-47f4-8f69-4521d6a4e1f9",
    "created_at":      "1be76181-05f8-4134-b410-455fceebbb7f",
    "genie_name":      "c294a065-0718-4211-8b95-a07f8923881e",
    "status":          "6b76da26-90e4-42ef-a556-e376ed6fbd8f",   # see STATUS_*
    "setup_thread_ts": "00f5e6dc-d335-48b0-96bf-d19312aadad8",   # kept after rekeying
    "updated_at":      "8f9aa1b3-3674-40f6-81f9-b189fc04ebd7",   # stamped on every save
    "other_assets":    "906794d0-62ab-4830-a86b-b1f14e0ce84e",   # JSON: connections, ...
    # The persona's prompt, copied in at Confirm so the responder reads it with
    # the row. Edit the cell to tune one genie.
    "system_prompt":   "c9e4fc54-83f8-4cf6-917b-dd52dadb1878",
    "genie_purpose":   "911f1a86-857b-4675-a7dd-47d476b0b083",   # what this genie should do
    "skills":          "73e51201-9e67-41f5-aa89-0afc4b57d0db",   # JSON: skills Integra built
    # JSON: where the Integra loop is (job, plan, which skills built / failed, folder).
    # A None column ID is looked up by name at run time (resolve_columns).
    "forge_state":     "612b517c-6267-470f-a0d0-35d132c4172e",
    "project_owner":   "527df99b-1f3b-46b0-9d3c-1a3b9a4e9173",   # JSON: [{project, name, mention}]
}

# --------------------------------------------------------------------------
# Status -- written on every submit. The router answers only for STATUS_ACTIVE.
# --------------------------------------------------------------------------

STATUS_STARTED = "started"                 # recipeconfig typed, persona not chosen
STATUS_PERSONA = "persona_selected"        # persona saved, projects not chosen
STATUS_PROJECTS = "projects_selected"      # projects and their assets saved
STATUS_DETAILS = "details_entered"         # name, keyword, channel saved
STATUS_KB = "kb_selected"                  # knowledge base made or skipped; Integra not started
STATUS_KB_ATTACHING = "kb_attaching"       # knowledge base made; its documents being attached
STATUS_BUILDING = "building"               # Integra is creating the genie and its skills
STATUS_BUILT = "built"                     # Integra finished; waiting for Confirm
STATUS_BUILD_FAILED = "build_failed"       # Integra failed; Try again is offered
STATUS_ACTIVE = "active"                   # confirmed: live in its channel
STATUS_CANCELLED = "cancelled"

# --------------------------------------------------------------------------
# Personas
# --------------------------------------------------------------------------
# `instructions` is what the router hands the master genie with every question,
# so it is written for the genie, not for the person picking.

PERSONAS = [
    {"key": "support", "label": "Support",
     "about": "Troubleshoot failed jobs, missing or mismatched records",
     "instructions": "You are a support engineer for these integrations. Find why "
                     "a record did or did not sync: check recent jobs, read the "
                     "recipe conditions, compare source and target. Give the "
                     "likely cause and the fix."},
    {"key": "analyst", "label": "Analyst",
     "about": "Sync volumes, job trends, data in tables and lookups",
     "instructions": "You are a data analyst for these integrations. Answer with "
                     "numbers: job counts, success rates, volumes, what is in the "
                     "data and lookup tables. State the time range you used."},
    {"key": "business", "label": "Business guide",
     "about": "Explain what the integration does in business terms",
     "instructions": "You talk to business users about these integrations. Avoid "
                     "recipe jargon: say what happens to a quote, order or "
                     "account, when, and what the user should do next. Never say "
                     "that you are keeping it simple or plain; just talk that way."},
    {"key": "developer", "label": "Developer",
     "about": "Recipe logic, field mappings, change impact",
     "instructions": "You are a Workato developer on this project. Explain recipe "
                     "logic step by step, field mappings and conditions, and what "
                     "a proposed change would affect. Cite recipe names and IDs."},
    {"key": "auditor", "label": "Auditor",
     "about": "Who changed what, versions, connections and access",
     "instructions": "You review these integrations for control and change. Report "
                     "versions, last changes, connections used and who has access. "
                     "Flag anything that looks unreviewed or risky."},
]
PERSONA_BY_KEY = {p["key"]: p for p in PERSONAS}

# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------

STEPS = ("persona", "projects", "details", "kb", "build", "confirm")

# Every button's action_id contains "gc_console": the click recipe's trigger filters
# on that one word, so a new button only has to carry it. The selects and text inputs
# (gc_persona_select, gc_name_input, ...) must NOT: they fire as the person picks
# values, and the filter then keeps those from starting a job at all.
ACTION_PERSONA = "gc_console_persona_submit"
ACTION_PERSONA_PICK = "gc_console_persona_pick"   # a persona card's button (persona_picker = carousel)
ACTION_PROJECTS = "gc_console_projects_submit"
ACTION_PROJECTS_NEXT = "gc_console_projects_next"
ACTION_PROJECTS_PREV = "gc_console_projects_prev"
ACTION_DETAILS = "gc_console_details_submit"
ACTION_KB_CREATE = "gc_console_kb_create"
ACTION_KB_SKIP = "gc_console_kb_skip"
ACTION_INTEGRA_RETRY = "gc_console_forge_retry"
ACTION_CONFIRM = "gc_console_confirm"
ACTION_CANCEL = "gc_console_cancel"
# Manage a genie that exists (GENIECONFIG typed in a channel that already has one). Their
# value is the genie's row key (KEYWORD:CHANNEL), not a draft key.
ACTION_NEW = "gc_console_new"                   # "Create a new genie" on the chooser
ACTION_MANAGE = "gc_console_manage"             # open the manage card
ACTION_RESYNC = "gc_console_resync"             # re-send the knowledge base's documents
ACTION_DESC = "gc_console_desc"                 # open the edit-description form
ACTION_DESC_SAVE = "gc_console_desc_save"       # check the new text, ask to confirm
ACTION_DESC_APPLY = "gc_console_desc_apply"     # confirmed: write it
ACTION_MANAGE_DONE = "gc_console_manage_done"   # back to the manage card
ACTION_DOCS = "gc_console_docs"                 # open the add-documents picker (the Click recipe
                                                # fetches the Drive file list for this click too)
ACTION_DOCS_SAVE = "gc_console_docs_save"       # register the picked documents and sync
ACTION_SKILLS_ADD = "gc_console_skills_add"     # plan new skills for a live genie (Integra reads the project)
ACTION_SKILLS_REMOVE = "gc_console_skills_remove"   # open the remove-skills picker
ACTION_SKILLS_REMOVE_APPLY = "gc_console_skills_remove_apply"   # detach the picked skills
# Not a manage action: its value is a draft key (the setup's, or the clone row an "add skills" run
# works in), because it carries on a Integra loop. Picks which of the planned skills to build.
ACTION_SKILLS_PICK = "gc_console_skills_pick"
ACTION_SKILLS_NONE = "gc_console_skills_none"     # "No skills": build the genie with none
MANAGE_ACTIONS = (ACTION_MANAGE, ACTION_RESYNC, ACTION_DESC, ACTION_DESC_SAVE,
                  ACTION_DESC_APPLY, ACTION_MANAGE_DONE, ACTION_DOCS, ACTION_DOCS_SAVE,
                  ACTION_SKILLS_ADD, ACTION_SKILLS_REMOVE, ACTION_SKILLS_REMOVE_APPLY)
# Not buttons: the daily sync recipe asks for the genies to visit, then once per genie.
ACTION_KB_SYNC_LIST = "kb_sync_list"    # -> sync_keys: [{record_key}], the genies that have a knowledge base
ACTION_KB_RESYNC = "kb_resync"          # action_value = a genie's row key
KEY_FREE_ACTIONS = MANAGE_ACTIONS + (ACTION_KB_SYNC_LIST, ACTION_KB_RESYNC)
KB_DOC_TYPE = "kb_doc"                  # one row per document in a genie's knowledge base
AUDIT_TYPE = "audit_log"                # one row per change made from the manage card
# Not buttons: the function recipe's REPEAT loop calls these, once per Integra job
# and once after it attached the knowledge base's documents.
ACTION_INTEGRA_NEXT = "forge_next"        # top of the loop: the task for Integra's next job
ACTION_INTEGRA_RESULT = "forge_result"    # after Integra answers: record it, show progress
ACTION_KB_ATTACH_RESULT = "kb_attach_result"   # after the recipe attached the documents

PURPOSE_MIN, PURPOSE_MAX = 30, 2900   # the "what should it do" text, in characters
KB_DESCRIPTION_MIN, KB_DESCRIPTION_MAX = 20, 500   # the knowledge base's description, likewise
KB_WHEN_MIN, KB_WHEN_MAX = 10, 300   # "when should the genie use it", likewise
KB_DOCS_MAX = SLACK_OPTIONS_MAX   # documents offered: as many as one Slack select holds
KB_ATTACH_OK = ("success", "succeeded", "ok", "true")   # kb_attach_status values meaning it worked

# Integra works in small jobs, one Assign-task call each, because a genie task
# stops after a fixed number of steps: plan -> build_skill (once per skill) ->
# create_genie. The function recipe loops while call_forge is true.
JOB_PLAN, JOB_SKILL, JOB_GENIE, JOB_DONE = "plan", "build_skill", "create_genie", "done"
MAX_SKILLS = 20      # most skills one plan may hold (Integra is told this as max_skills)
SKILLS_ALL, SKILLS_PICK, SKILLS_NONE = "all", "pick", "none"   # details step: every planned skill / let me choose / none
STATUS_ADD_DONE = "add_done"     # an "add skills" run that finished (its clone row; not a live genie)
# A second run of the same Submit (a recipe retry) is ignored while the build
# is this fresh; after that the setup is treated as stuck and may start again.
BUILDING_FRESH_MINUTES = 30

# Shown in place of the buttons the moment a click is handled, before any slow
# call, so the person sees the click land. :loading-2: is this workspace's
# spinner emoji (the SNAP bot uses it too).
LOADING_TEXT = {
    ACTION_PERSONA: "Saving persona and loading projects…",
    ACTION_PERSONA_PICK: "Saving persona and loading projects…",
    ACTION_PROJECTS: "Loading recipes, lookup tables and data tables…",
    ACTION_PROJECTS_NEXT: "Loading more projects…",
    ACTION_PROJECTS_PREV: "Loading previous projects…",
    ACTION_DETAILS: "Checking name and keyword…",
    ACTION_KB_CREATE: "Creating the knowledge base…",
    ACTION_KB_SKIP: "Skipping the knowledge base…",
    ACTION_INTEGRA_RETRY: "Asking Integra to try again…",
    ACTION_CONFIRM: "Switching it on…",
    ACTION_CANCEL: "Cancelling…",
    ACTION_NEW: "Starting a new genie…",
    ACTION_MANAGE: "Opening…",
    ACTION_RESYNC: "Syncing the knowledge base…",
    ACTION_DESC: "Opening…",
    ACTION_DESC_SAVE: "Checking the new description…",
    ACTION_DESC_APPLY: "Saving the new description…",
    ACTION_MANAGE_DONE: "Opening…",
    ACTION_DOCS: "Loading the documents…",
    ACTION_DOCS_SAVE: "Adding the documents…",
    ACTION_SKILLS_ADD: "Asking Integra to look for skills to add…",
    ACTION_SKILLS_REMOVE: "Opening…",
    ACTION_SKILLS_REMOVE_APPLY: "Removing the skills…",
    ACTION_SKILLS_PICK: "Building the skills you picked…",
    ACTION_SKILLS_NONE: "Creating the genie without skills…",
}
LOADING_EMOJI = ":loading-2:"

RESERVED_KEYWORDS = {
    "THE", "AND", "FOR", "HELP", "HI", "HELLO", "OK", "YES", "NO", "STOP",
    "BOT", "NS", "IT", "ALL", "HERE", "CHANNEL", "THANKS", "PLEASE",
    "RECIPECONFIG",
}

# Folder-asset types and the column each one is stored in.
ASSET_COLUMNS = {
    "recipe": "recipes",
    "lookup_table": "lookup_tables",
    "data_table": "data_tables",
    "workato_db_table": "data_tables",
}


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


def _workato_headers(token):
    return {"Authorization": "Bearer {}".format(token),
            "Content-Type": "application/json"}


def to_column(value):
    """A list or dict as stored in a text column. Characters are counted as
    stored, so this keeps non-ASCII ones (· — …) as one character, not \\uXXXX."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


# --------------------------------------------------------------------------
# Data table
# --------------------------------------------------------------------------

def resolve_columns(token, warnings):
    """Fill in any COLUMNS entry left as None from the table's live schema, by
    column name -- so a column added to the table works without a code change."""
    missing = [name for name, uuid in COLUMNS.items() if not uuid]
    if not missing or not token:
        return
    body, error = _request(TABLE_SCHEMA_URL, _workato_headers(token))
    if error:
        warnings.append("table schema: " + error)
        return
    data = (body or {}).get("data") or body or {}
    by_name = {f.get("name"): f.get("field_id") for f in data.get("schema") or []}
    for name in missing:
        if by_name.get(name):
            COLUMNS[name] = by_name[name]


class Table(object):
    """genie_console data table access, by column name rather than UUID."""

    def __init__(self, token, dry_run=False):
        self.headers = _workato_headers(token)
        self.dry_run = dry_run
        self.errors = []
        self.written = []

    def find(self, record_key):
        """(row, error). row is None when there is no such record."""
        body, error = _request(TABLE_QUERY_URL, self.headers,
                               {"where": {"record_key": {"$eq": record_key}},
                                "limit": 1}, "POST")
        if error:
            return None, "table.query " + error
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        for row in body.get("data", []):
            return dict(zip(columns, [v for group in row for v in group])), None
        return None, None

    def search(self, where, limit=100):
        """(rows, error): every row matching `where`, keyed by column name."""
        body, error = _request(TABLE_QUERY_URL, self.headers,
                               {"where": where, "limit": limit}, "POST")
        if error:
            return [], "table.query " + error
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        return [dict(zip(columns, [v for group in row for v in group]))
                for row in body.get("data", [])], None

    def _document(self, fields):
        document = {}
        for name, value in fields.items():
            uuid = COLUMNS.get(name)
            if not uuid:
                continue                    # not a column in the table; see COLUMNS
            if isinstance(value, (list, dict)):
                value = to_column(value)
            document["$" + uuid] = value
        return document

    def save(self, row, fields):
        """Create when row is None, otherwise update it in place."""
        self.written.append({"action": "update" if row else "create",
                             "fields": sorted(fields)})
        if self.dry_run:
            return True
        if row:
            record_id = row.get("$record_id")
            if not record_id:
                self.errors.append("row has no $record_id")
                return False
            _body, error = _request(TABLE_RECORD_URL.format(record_id), self.headers,
                                    {"document": self._document(fields)}, "PUT")
        else:
            _body, error = _request(TABLE_RECORDS_URL, self.headers,
                                    {"document": self._document(fields)}, "POST")
        if error:
            self.errors.append("table.save " + error)
            return False
        return True


# --------------------------------------------------------------------------
# Workato API
# --------------------------------------------------------------------------

def _items(body, *keys):
    """The list in a response, whether it is the body or under a key."""
    if isinstance(body, list):
        return body
    for key in keys:
        value = (body or {}).get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            inner = _items(value, *keys)
            if inner:
                return inner
    return []


def list_projects(token):
    """(projects, error). Each project: {id, name, folder_id}, sorted by name."""
    projects = []
    for page in range(1, PROJECT_PAGES + 1):
        body, error = _request(PROJECTS_URL.format(page), _workato_headers(token))
        if error:
            return [], "projects " + error
        batch = _items(body, "items", "result", "data")
        projects.extend({"id": p.get("id"), "name": p.get("name") or "",
                         "folder_id": p.get("folder_id")}
                        for p in batch if p.get("folder_id"))
        if len(batch) < 100:
            break
    projects.sort(key=lambda p: p["name"].lower())
    return projects, None


def folder_assets(token, folder_id):
    """(assets, error). Each asset as the export manifest API returns it."""
    body, error = _request(FOLDER_ASSETS_URL.format(folder_id), _workato_headers(token))
    if error:
        return [], "folder_assets {} {}".format(folder_id, error)
    return _items(body, "result", "assets", "items"), None


def ensure_folder(token, parent_id, name):
    """(folder_id, error). The subfolder `name` under parent_id, created if it is
    not there yet -- so a retry reuses the folder the first attempt made."""
    headers = _workato_headers(token)
    for page in range(1, PROJECT_PAGES + 1):
        body, error = _request("{}?parent_id={}&page={}&per_page=100".format(
            FOLDERS_URL, parent_id, page), headers)
        if error:
            return None, "folders " + error
        batch = _items(body, "items", "result", "data")
        for folder in batch:
            if (folder.get("name") or "").strip().lower() == name.lower():
                return folder.get("id"), None
        if len(batch) < 100:
            break
    body, error = _request(FOLDERS_URL, headers, {"name": name, "parent_id": parent_id}, "POST")
    if error:
        return None, "create folder " + error
    folder_id = (body or {}).get("id") or ((body or {}).get("result") or {}).get("id")
    return (folder_id, None) if folder_id else (None, "create folder: no id in the response")


def recipe_version(token, recipe_id, version_no=None):
    """(recipe, error). version_no None is the newest version."""
    url = RECIPE_URL.format(recipe_id)
    if version_no:
        url += "&version_no={}".format(version_no)
    body, error = _request(url, _workato_headers(token))
    return (body if isinstance(body, dict) else None), error


def find_owner(token, recipe_id):
    """(owner, error). Workato has no project-owner field, so the owner is the author
    of the recipe's first version written by an OWNER_EMAIL_DOMAIN address; versions
    by contractors or service accounts are skipped. owner is {name, email}, or None
    when no version in the first OWNER_MAX_VERSIONS has such an author."""
    latest, error = recipe_version(token, recipe_id)
    if error:
        return None, "recipe {} {}".format(recipe_id, error)
    newest = int((latest or {}).get("version_no") or 1)
    for version_no in range(1, min(newest, OWNER_MAX_VERSIONS) + 1):
        if version_no == newest:
            recipe = latest
        else:
            recipe, error = recipe_version(token, recipe_id, version_no)
            if error and error.startswith("HTTP 404"):
                continue                      # a gap in the history: keep going
            if error:
                return None, "recipe {} version {} {}".format(recipe_id, version_no, error)
        email = str((recipe or {}).get("version_author_email") or "").strip().lower()
        if email.endswith("@" + OWNER_EMAIL_DOMAIN):
            return {"name": (recipe.get("version_author_name") or "").strip(),
                    "email": email}, None
    return None, None


def group_assets(assets):
    """{'recipes': [...], 'lookup_tables': [...], 'data_tables': [...],
        'other_assets': [...], 'types': {type: count}}"""
    grouped = {"recipes": [], "lookup_tables": [], "data_tables": [],
               "other_assets": [], "types": {}}
    seen = set()
    for asset in assets:
        kind = str(asset.get("type") or "").lower()
        key = (kind, asset.get("id"))
        if key in seen:
            continue
        seen.add(key)
        grouped["types"][kind] = grouped["types"].get(kind, 0) + 1
        entry = {"id": asset.get("id"), "name": asset.get("name") or ""}
        column = ASSET_COLUMNS.get(kind)
        if column:
            grouped[column].append(entry)
        else:
            entry["type"] = kind
            grouped["other_assets"].append(entry)
    return grouped


def fit_column(items, column, warnings):
    """Drop entries from the end until the JSON fits in one text column."""
    kept = list(items)
    while kept and len(to_column(kept)) > COLUMN_LIMIT:
        kept.pop()
    if len(kept) < len(items):
        warnings.append("{}: kept {} of {}; the rest did not fit in the column"
                        .format(column, len(kept), len(items)))
    return kept


# --------------------------------------------------------------------------
# Slack
# --------------------------------------------------------------------------

class Slack(object):
    def __init__(self, token, dry_run=False):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json; charset=utf-8"}
        self.dry_run = dry_run
        self.errors = []
        self.last_blocks = []

    def call(self, method, payload):
        body, error = _request(SLACK_API + method, self.headers, payload, "POST")
        if error:
            self.errors.append("slack.{} {}".format(method, error))
            return None
        if not body.get("ok"):
            # Slack says which block is wrong in response_metadata.messages: keep it
            detail = "; ".join(str(m) for m in (body.get("response_metadata") or {}).get("messages") or [])
            self.errors.append("slack.{}: {}{}".format(
                method, body.get("error"), " ({})".format(detail[:300]) if detail else ""))
            return None
        return body

    def post(self, channel, thread_ts, text, blocks, attachments=None):
        self.last_blocks = blocks
        if self.dry_run:
            return "dry-run"
        payload = {"channel": channel, "text": text, "blocks": blocks, **NO_UNFURL}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if attachments is not None:
            payload["attachments"] = attachments
        body = self.call("chat.postMessage", payload)
        return (body or {}).get("ts") or ""

    def dm(self, user_id, text):
        """A direct message from the app (the user's ID as the channel). True when sent."""
        return bool(self.post(user_id, "", text, done_blocks(text)))

    def update(self, channel, ts, text, blocks, attachments=None):
        """attachments=None leaves the message's attachments alone; [] removes them."""
        self.last_blocks = blocks
        if self.dry_run or not ts:
            return bool(ts)
        payload = {"channel": channel, "ts": ts, "text": text, "blocks": blocks, **NO_UNFURL}
        if attachments is not None:
            payload["attachments"] = attachments
        return bool(self.call("chat.update", payload))

    def _try(self, method, payload):
        """(body, error code), quietly: the caller decides whether a failure matters."""
        body, error = _request(SLACK_API + method, self.headers, payload, "POST")
        if error:
            return None, error
        if not body.get("ok"):
            return None, body.get("error") or "unknown_error"
        return body, ""

    def join(self, channel):
        """Make sure the app is in `channel`: it only receives a channel's messages
        while it is a member. "" when it is (already, or now); otherwise why not.
        An app joins a public channel itself (scope channels:join); a private one
        needs someone to invite it."""
        if self.dry_run:
            return ""
        info, info_code = self._try("conversations.info", {"channel": channel})
        if not info:
            # Can't tell (no channels:read / groups:read, or a private channel the app
            # can't see). Don't claim the app is missing: it usually is a member, and a
            # false warning on every Confirm is worse than a silent one.
            self.errors.append("slack.conversations.info: {} (membership not checked)".format(info_code))
            return ""
        found = info.get("channel") or {}
        if found.get("is_member") or found.get("is_private"):
            return ""                   # Slack only shows a private channel to its members
        if found.get("is_archived"):
            return "the channel is archived"
        joined, code = self._try("conversations.join", {"channel": channel})
        if joined:
            return ""
        return {"missing_scope": "the Slack app has no channels:join scope, so it can't "
                                 "join channels itself",
                "method_not_supported_for_channel_type": "a private channel can't be joined "
                                                         "by an app, only invited",
                "channel_not_found": "a private channel can't be joined by an app, only invited",
                "is_archived": "the channel is archived"}.get(code, code)

    def user_id_by_email(self, email):
        """(Slack user ID, error). "" for the ID, with a reason, when the email isn't
        in the workspace. Needs the users:read.email scope. The reason never holds the
        email: it goes to the job log."""
        body, error = _request(SLACK_API + "users.lookupByEmail?" +
                               urllib.parse.urlencode({"email": email}), self.headers)
        if error:
            return "", "slack.users.lookupByEmail " + error
        if body.get("ok"):
            return (body.get("user") or {}).get("id") or "", None
        code = body.get("error")
        if code == "users_not_found":
            return "", "no Slack user has the owner's email"
        return "", "slack.users.lookupByEmail: {}{}".format(
            code, " (the Slack app needs the users:read.email scope)"
            if code == "missing_scope" else "")

    def whisper(self, channel, user_id, thread_ts, text):
        """A message only `user_id` can see (chat.postEphemeral). False when Slack won't send one
        (the app isn't in the channel, say): the caller then posts it in the thread instead."""
        if self.dry_run:
            return True
        payload = {"channel": channel, "user": user_id, "text": text, "blocks": done_blocks(text)}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        body, _code = self._try("chat.postEphemeral", payload)
        return bool(body)

    def bot_user_id(self):
        body, _code = self._try("auth.test", {})
        return (body or {}).get("user_id") or ""

    def user(self, user_id):
        body = self.call("users.info", {"user": user_id}) if user_id else None
        user = (body or {}).get("user") or {}
        profile = user.get("profile") or {}
        name = (profile.get("real_name") or user.get("real_name")
                or profile.get("display_name") or user.get("name") or "")
        return {"name": name.strip(), "email": profile.get("email") or ""}


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------

def _text(value, limit=SLACK_OPTION_TEXT):
    value = str(value)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _option(text, value):
    return {"text": {"type": "plain_text", "text": _text(text)}, "value": value}


def _progress(step):
    number = STEPS.index(step) + 1
    left = len(STEPS) - number
    return {"type": "context", "elements": [{"type": "mrkdwn", "text":
            "Step {} of {}  ·  {} left after this".format(number, len(STEPS), left)}]}


def _error(error):
    return [{"type": "section", "text": {"type": "mrkdwn",
             "text": ":warning: " + error}}] if error else []


def _submit(action_id, key, label="Submit"):
    return {"type": "button", "action_id": action_id, "value": key, "style": "primary",
            "text": {"type": "plain_text", "text": label}}


def banner_blocks(banner_url):
    """The Genie Console banner as an image block, or nothing. Only an https URL
    is used: Slack must be able to fetch it, and a URL it can't load makes it
    reject the whole message."""
    url = str(banner_url or "").strip()
    if not url.lower().startswith("https://"):
        return []
    return [{"type": "image", "image_url": url, "alt_text": "Genie Console"}]


PERSONA_PICKERS = ("list", "carousel")      # the persona_picker input; blank = list


def persona_blocks(key, error="", banner_url="", picker="list"):
    """The persona step. picker = "list": a dropdown in an input block (full width: in an
    actions block it is squeezed narrow and the descriptions are cut off) and a Submit
    button. picker = "carousel": one card per persona, each with its own Choose button."""
    head = [
        *banner_blocks(banner_url),
        {"type": "section", "text": {"type": "mrkdwn",
         "text": "*What kind of genie do you want?*"}},
        _progress("persona"),
        *_error(error),
    ]
    if picker == "carousel":
        return head + [persona_carousel(key)]
    return head + [
        {"type": "input", "block_id": "gc_persona",
         "label": {"type": "plain_text", "text": "Persona"},
         "element": {"type": "static_select", "action_id": "gc_persona_select",
                     "placeholder": {"type": "plain_text", "text": "Pick a persona"},
                     "options": [_option("{} — {}".format(p["label"], p["about"]), p["key"])
                                 for p in PERSONAS]}},
        {"type": "actions", "elements": [_submit(ACTION_PERSONA, key)]},
    ]


def persona_carousel(key):
    """One card per persona. The button's value is "<draft key>|<persona>", so the click
    needs no dropdown state to know what was chosen."""
    return {"type": "carousel", "block_id": "gc_persona_cards", "elements": [
        {"type": "card", "block_id": "gc_persona_" + p["key"],
         "title": {"type": "mrkdwn", "text": "*{}*".format(p["label"])},
         "body": {"type": "mrkdwn", "text": p["about"]},
         "actions": [{"type": "button", "action_id": ACTION_PERSONA_PICK + "_" + p["key"],
                      "value": "{}|{}".format(key, p["key"]), "style": "primary",
                      "text": {"type": "plain_text", "text": "Choose " + p["label"]}}]}
        for p in PERSONAS[:10]]}


def _project_option(project):
    return _option(project["name"], json.dumps({"id": project["id"], "f": project["folder_id"]},
                                               separators=(",", ":")))


def project_page(projects, page):
    """(the projects on this page, the page actually shown, number of pages)."""
    pages = max(1, -(-len(projects) // SLACK_OPTIONS_MAX))
    page = min(max(0, page), pages - 1)
    start = page * SLACK_OPTIONS_MAX
    return projects[start:start + SLACK_OPTIONS_MAX], page, pages


def projects_blocks(key, projects, page=0, selected=(), error=""):
    """One page of at most 100 projects -- Slack's limit for one select -- with
    buttons to move between pages. Picks already saved from any page are listed
    under the select and pre-checked when their page is shown again.

    The select is in an input block: full width, where a section accessory is
    squeezed into a narrow column. A multi-select is never allowed in an actions
    block; Slack rejects that message as invalid_blocks."""
    shown, page, pages = project_page(projects, page)
    picked_ids = {s.get("id") for s in selected}
    select = {"type": "multi_static_select", "action_id": "gc_projects_select",
              "placeholder": {"type": "plain_text", "text": "Pick projects"},
              "options": [_project_option(p) for p in shown]}
    initial = [_project_option(p) for p in shown if p["id"] in picked_ids]
    if initial:
        select["initial_options"] = initial

    buttons = [_submit(ACTION_PROJECTS, "{}|{}".format(key, page))]
    if page + 1 < pages:
        buttons.append({"type": "button", "action_id": ACTION_PROJECTS_NEXT,
                        "value": "{}|{}".format(key, page + 1),
                        "text": {"type": "plain_text", "text": "My project isn't listed ›"}})
    if page > 0:
        buttons.append({"type": "button", "action_id": ACTION_PROJECTS_PREV,
                        "value": "{}|{}".format(key, page - 1),
                        "text": {"type": "plain_text", "text": "‹ Previous projects"}})

    # The dropdown's search only covers the 100 projects on this page, and Slack's own "Nothing
    # could be found." can't be changed: with more than one page, say so in the label and a hint.
    projects_input = {"type": "input", "block_id": "gc_projects", "optional": True,
                      "label": {"type": "plain_text",
                                "text": "Projects (this page only)" if pages > 1 else "Projects"},
                      "element": select}
    if pages > 1:
        projects_input["hint"] = {"type": "plain_text", "text": (
            "Search only covers the projects on this page. Can't find yours? Click "
            "\"My project isn't listed ›\" for the next page.") if page + 1 < pages else (
            "Search only covers the projects on this page. Can't find yours? Click "
            "\"‹ Previous projects\" to go back a page.")}

    start = page * SLACK_OPTIONS_MAX
    status = "Projects {}–{} of {}".format(start + 1, start + len(shown), len(projects))
    if selected:
        # Capped: a context line over 3,000 characters is invalid_blocks.
        names = [_text(s.get("name") or str(s.get("id")), 60) for s in selected[:10]]
        more = len(selected) - len(names)
        status += "  ·  *Selected so far ({}):* {}{}".format(
            len(selected), ", ".join(names), " and {} more".format(more) if more > 0 else "")
    return [
        {"type": "section", "text": {"type": "mrkdwn",
         "text": "*Which Workato projects should it know about?*\n"
                 "Recipes, lookup tables and data tables in each are loaded."}},
        _progress("projects"),
        *_error(error),
        projects_input,
        {"type": "context", "elements": [{"type": "mrkdwn", "text": status}]},
        {"type": "actions", "elements": buttons},
    ]


def _text_input(block_id, label, hint, initial, multiline=False, max_length=PURPOSE_MAX,
                optional=False):
    # Slack rejects the whole message (invalid_blocks) when a placeholder
    # is over 150 characters, so it is capped here.
    element = {"type": "plain_text_input", "action_id": block_id + "_input",
               "placeholder": {"type": "plain_text", "text": _text(hint, PLACEHOLDER_MAX)}}
    if multiline:
        element.update({"multiline": True, "max_length": max_length})
    if initial:
        element["initial_value"] = initial
    block = {"type": "input", "block_id": block_id, "label":
             {"type": "plain_text", "text": label}, "element": element}
    if optional:
        block["optional"] = True
    return block


SKILL_MODES = (
    (SKILLS_ALL, "Create skills for all actions",
     "A lookup skill for every object Integra finds in the project"),
    (SKILLS_PICK, "Let me choose from a list",
     "Integra lists the skills it found, then builds only the ones you pick"),
    (SKILLS_NONE, "No skills",
     "A genie with no skills: it answers from its instructions and knowledge base. "
     "Skills can be added later from Manage."),
)


def skill_mode_block(selected):
    options = [{"text": {"type": "plain_text", "text": label},
                "description": {"type": "plain_text", "text": about}, "value": value}
               for value, label, about in SKILL_MODES]
    initial = next((o for o in options if o["value"] == selected), options[0])
    return {"type": "input", "block_id": "gc_skill_mode",
            "label": {"type": "plain_text", "text": "Which skills should Integra create?"},
            "element": {"type": "radio_buttons", "action_id": "gc_skill_mode_select",
                        "options": options, "initial_option": initial}}


def details_blocks(key, values, error=""):
    channel = {"type": "conversations_select", "action_id": "gc_channel_select",
               "placeholder": {"type": "plain_text", "text": "Pick a channel"},
               "filter": {"include": ["public", "private"], "exclude_bot_users": True}}
    if values.get("channel"):
        channel["initial_conversation"] = values["channel"]
    # An input block, like the text fields: full width. As a section accessory
    # the picker is squeezed into a narrow column and the name is cut off.
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Name it and pick where it lives*"}},
        _progress("details"),
        *_error(error),
        _text_input("gc_name", "Genie name", "e.g. SFNS Troubleshooter", values.get("genie_name")),
        _text_input("gc_keyword", "Trigger keyword", "one word, e.g. SFNS",
                    values.get("invoke_keyword")),
        {"type": "input", "block_id": "gc_channel",
         "label": {"type": "plain_text", "text": "Channel"}, "element": channel},
        _text_input("gc_purpose", "What should this genie do?",
                    "Who it helps, which records it looks up, and what questions it answers",
                    values.get("genie_purpose"), multiline=True),
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
         "_Example: Help the finance team find out why a Salesforce quote didn't become a "
         "NetSuite sales order: look up the quote by ID or number, check its sales order in "
         "NetSuite, and read the failed job._\nIntegra reads this and the project's recipes, "
         "then builds the genie and the skills it needs to look up live records."}]},
        skill_mode_block(values.get("skill_mode")),
        {"type": "actions", "elements": [_submit(ACTION_DETAILS, key, "Next")]},
    ]


def _doc_blocks(docs, picked):
    """The documents dropdown, in an input block like the projects one: a multi-select
    is never allowed in an actions block. Nothing when there are no documents to offer."""
    if not docs:
        return []
    picked = set(picked)
    labels, options = [_text(d["file_name"]) for d in docs], []
    for doc, label in zip(docs, labels):
        text = label
        if labels.count(label) > 1:
            # the same name twice: the end of the ID tells them apart
            suffix = " (…{})".format(doc["file_id"][-4:])
            text = _text(doc["file_name"], SLACK_OPTION_TEXT - len(suffix)) + suffix
        options.append(_option(text, doc["file_id"]))
    select = {"type": "multi_static_select", "action_id": "gc_kb_files_select",
              "placeholder": {"type": "plain_text", "text": "Pick documents"},
              "options": options}
    initial = [o for o in options if o["value"] in picked]
    if initial:
        select["initial_options"] = initial
    return [{"type": "input", "block_id": "gc_kb_files", "optional": True,
             "label": {"type": "plain_text", "text": "Documents to add"}, "element": select}]


def kb_blocks(key, values, error="", docs=()):
    """The knowledge base question. All the inputs are optional as far as Slack is
    concerned, so Skip works with them empty; Create checks them itself and says
    what is missing. docs ([{file_name, file_id}]) puts a dropdown of them under the
    description, with the IDs in values["kb_files"] shown as picked."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "*Want to attach a knowledge base to this genie?*\n"
         "A knowledge base is reference material the genie can look things up in: FAQs, "
         "runbooks, how-to guides. Name it and say what it holds, then click *Create "
         "knowledge base*. Or click *Skip knowledge base* to carry on without one."}},
        _progress("kb"),
        *_error(error),
        _text_input("gc_kb_name", "Knowledge base name", "e.g. SFNS Support FAQs",
                    values.get("kb_name"), optional=True),
        _text_input("gc_kb_description", "Knowledge base description",
                    "What is in it and what it is for, e.g. How to resubmit a failed "
                    "quote and what each error code means",
                    values.get("kb_description"), multiline=True,
                    max_length=KB_DESCRIPTION_MAX, optional=True),
        _text_input("gc_kb_when", "When should the genie use it?",
                    "e.g. When someone asks how to resubmit a failed quote, or about a person "
                    "or rule this knowledge base covers",
                    values.get("kb_when"), multiline=True,
                    max_length=KB_WHEN_MAX, optional=True),
        *_doc_blocks(docs, values.get("kb_files") or []),
        {"type": "context", "elements": [{"type": "mrkdwn", "text": (
            "_The knowledge base is created in the genie's folder, then the documents you "
            "pick are added to it._" if docs else
            "_The knowledge base is created in the genie's folder; its content is added in "
            "Workato afterwards._")}]},
        {"type": "actions", "elements": [
            _submit(ACTION_KB_CREATE, key, "Create knowledge base"),
            {"type": "button", "action_id": ACTION_KB_SKIP, "value": key,
             "text": {"type": "plain_text", "text": "Skip knowledge base"}}]},
    ]


def integra_progress(state):
    """One line per Integra job, ticked off as the loop goes."""
    job, plan = state.get("job"), wanted(state)
    lines = [(":white_check_mark: Read the project: {} skill{} to build".format(
                 len(plan), "" if len(plan) == 1 else "s") if plan and job != JOB_PLAN
              else ":white_check_mark: No skills to build" if job != JOB_PLAN
              else "{} Reading the project and planning skills".format(LOADING_EMOJI))]
    for index, skill in enumerate(state.get("plan") or []):
        if skill.get("state") == "skipped":
            continue
        name = _text(skill.get("name") or "skill {}".format(index + 1), 60)
        if skill.get("state") == "built":
            lines.append(":white_check_mark: " + name)
        elif skill.get("state") == "failed":
            lines.append(":x: {} (not built: {})".format(name, _text(skill.get("reason") or "", 80)))
        elif job == JOB_SKILL and index == state.get("next", 0):
            lines.append("{} Building {}".format(LOADING_EMOJI, name))
        else:
            lines.append(":white_small_square: " + name)
    if plan or job in (JOB_GENIE, JOB_DONE):
        lines.append({JOB_GENIE: "{} Creating the genie and attaching the skills".format(LOADING_EMOJI),
                      JOB_DONE: ":white_check_mark: Genie created"}.get(
                          job, ":white_small_square: Create the genie and attach the skills"))
    return "\n".join(lines)


def building_blocks(row, state=None):
    """Posted when Integra starts and edited after every job, so the progress
    shows. Edited into a one-line result when the build finishes."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "*Integra is building {}*".format(row.get("genie_name"))}},
        _progress("build"),
        {"type": "section", "expand": True, "text": {"type": "mrkdwn",
         "text": integra_progress(state or {"job": JOB_PLAN})}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
         ":coffee: This takes a few minutes. Please carry on with your work: "
         "I'll mention you here as soon as it's done."}]},
    ]


def plan_entries(state):
    """The planned skills as (value, name, about) for a picker: the value is the position in the plan."""
    return [(str(index), entry.get("name") or "skill {}".format(index + 1), entry.get("about") or "")
            for index, entry in enumerate(state.get("plan") or [])]


def skills_pick_blocks(key, entries, heading, action, button, error="", cancel=False, back=False,
                       skip=False):
    """A multi-select of skills, (value, name, about) each, with one button. Nothing is
    ticked at the start, so what is built or removed is only what the person chose.
    Slack holds 100 options in one select; the skills of a genie are far fewer."""
    options = []
    for value, name, about in entries[:SLACK_OPTIONS_MAX]:
        option = _option(name, value)
        if about:
            option["description"] = {"type": "plain_text", "text": _text(about, 75)}
        options.append(option)
    buttons = [_submit(action, key, button)]
    if skip:        # build the genie with none of the planned skills
        buttons.append({"type": "button", "action_id": ACTION_SKILLS_NONE, "value": key,
                        "text": {"type": "plain_text", "text": "No skills"}})
    if cancel:
        buttons.append({"type": "button", "action_id": ACTION_CANCEL, "value": key, "style": "danger",
                        "text": {"type": "plain_text", "text": "Cancel"}})
    if back:
        buttons.append({"type": "button", "action_id": ACTION_MANAGE_DONE, "value": key,
                        "text": {"type": "plain_text", "text": "Back"}})
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*{}*".format(heading)}},
        *_error(error),
        {"type": "input", "block_id": "gc_skills_pick",
         "label": {"type": "plain_text", "text": "Skills"},
         "element": {"type": "multi_static_select", "action_id": "gc_skills_pick_select",
                     "placeholder": {"type": "plain_text", "text": "Pick one or more"},
                     "options": options}},
        {"type": "actions", "elements": buttons},
    ]


def picked_values(ctx):
    """The values ticked in the clicked message's skills select, as a sorted list of ints."""
    chosen = _state(ctx.click["state"], "gc_skills_pick", "gc_skills_pick_select"
                    ).get("selected_options") or []
    return sorted({int(o["value"]) for o in chosen if str(o.get("value")).isdigit()})


def build_failed_blocks(key, row, error, progress=""):
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text":
         ":warning: *Integra couldn't finish building {}*".format(row.get("genie_name"))}},
        _progress("build"),
        {"type": "section", "expand": True, "text": {"type": "mrkdwn", "text":
         "```{}```".format(_text(error or "Integra returned no genie.", 1500))}},
        *([{"type": "section", "expand": True, "text": {"type": "mrkdwn", "text": progress}}]
          if progress else []),
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
         "Try again carries on from the step that failed; finished steps are kept."}]},
        {"type": "actions", "elements": [
            _submit(ACTION_INTEGRA_RETRY, key, "Try again"),
            {"type": "button", "action_id": ACTION_CANCEL, "value": key, "style": "danger",
             "text": {"type": "plain_text", "text": "Cancel"}}]},
    ]


def _names(column_json, limit=6):
    items = _load_list(column_json)
    names = ", ".join(i.get("name") or str(i.get("id")) for i in items[:limit])
    more = len(items) - limit
    return (names + (" and {} more".format(more) if more > 0 else "")) or "none"


def code_list(items, limit=SUMMARY_LIST_MAX):
    """Assets as an aligned code block: IDs padded to one width, then the name.

        44594075  SFDC Quote To NetSuite Sales Order Sync
           43149  Genie Context Table
    """
    if not items:
        return "_none_"
    shown = items[:limit]
    width = max(len(str(i.get("id", ""))) for i in shown)
    lines = ["{}  {}".format(str(i.get("id", "")).rjust(width),
                             _text(i.get("name") or "", SUMMARY_NAME_MAX)) for i in shown]
    if len(items) > limit:
        lines.append("{}  … and {} more".format(" " * width, len(items) - limit))
    return "```" + "\n".join(lines) + "```"


def _mention(row):
    """'<@U123> ' for the person who started the setup, or '' if unknown."""
    creator = str(row.get("creator_id") or "").strip()
    return "<@{}> ".format(creator) if creator else ""


def confirm_message(key, row):
    """(blocks, attachments). The summary goes in a coloured attachment, split
    into small blocks: Slack folds one long section behind "Show more", so no
    single block here is allowed to get long."""
    persona = PERSONA_BY_KEY.get(row.get("persona"), {}).get("label", row.get("persona"))
    handle = row.get("id") or ""
    summary = [
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": "*Genie*\n<{}|{}>".format(GENIE_URL.format(handle),
                                                                 row.get("genie_name"))
             if handle else "*Genie*\n{}".format(row.get("genie_name"))},
            {"type": "mrkdwn", "text": "*Keyword*\n`{}`".format(row.get("invoke_keyword"))},
            {"type": "mrkdwn", "text": "*Channel*\n<#{}>".format(row.get("channel"))},
            {"type": "mrkdwn", "text": "*Persona*\n{}".format(persona)},
        ]},
    ]
    skills = [{"id": s.get("recipe_id") or s.get("handle"), "name": s.get("name")}
              for s in _load_list(row.get("skills"))]
    kb = integra_state(row).get("kb") or {}
    sections = [("Skills built by Integra", skills)]
    if kb.get("id"):
        name = kb.get("name") or ""
        if kb.get("attach") == "done":
            name += " · {} document{}".format(kb.get("files"), "" if kb.get("files") == 1 else "s")
        elif kb.get("attach") == "failed":
            name += " · documents not attached"
        sections.append(("Knowledge base", [{"id": kb["id"], "name": name}]))
    sections += [("Projects", _load_list(row.get("workato_projects"))),
                 ("Recipes", _load_list(row.get("recipes"))),
                 ("Lookup tables", _load_list(row.get("lookup_tables"))),
                 ("Data tables", _load_list(row.get("data_tables")))]
    for label, items in sections:
        summary.append({"type": "section", "expand": True, "text": {"type": "mrkdwn", "text":
                        "*{} ({})*\n{}".format(label, len(items), code_list(items))}})
    failed = [e for e in integra_state(row).get("plan") or [] if e.get("state") == "failed"]
    if failed:      # right after the built skills (summary[0] is the genie, [1] the skills)
        summary.insert(2, {"type": "section", "expand": True, "text": {"type": "mrkdwn", "text":
                           "*Not built ({})*\n{}".format(len(failed), "\n".join(
                               ":x: {} ({})".format(_text(e.get("name"), 60),
                                                    _text(e.get("reason") or "", 100))
                               for e in failed))}})
    summary.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                    "Confirm {}starts the genie and its skill recipes, adds this app to the "
                    "channel and switches it on there.".format(
                        "attaches the knowledge base, " if kb.get("id") else "")}]})

    blocks = [
        # The mention is what notifies the creator: Integra can take minutes,
        # and editing a message never notifies anyone, only a new post does.
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "{}*{} is ready.* Have a look, then switch it on.".format(
             _mention(row), row.get("genie_name"))}},
        _progress("confirm"),
        {"type": "actions", "elements": [
            _submit(ACTION_CONFIRM, key, "Confirm"),
            {"type": "button", "action_id": ACTION_CANCEL, "value": key, "style": "danger",
             "text": {"type": "plain_text", "text": "Cancel"}}]},
    ]
    attachments = [{"color": SUMMARY_COLOR, "fallback": "Genie summary", "blocks": summary}]
    return blocks, attachments


def _cell(text, bold=False, code=False):
    """One table cell: rich text, since that is what a table block takes."""
    style = {k: True for k, on in (("bold", bold), ("code", code)) if on}
    element = {"type": "text", "text": text or " "}
    if style:
        element["style"] = style
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [element]}]}


def summary_table(row):
    """The confirm summary as one table block (Slack allows one table per message): a row
    per skill, knowledge base, project, recipe, lookup table and data table."""
    kb = integra_state(row).get("kb") or {}
    groups = [("Skill", [(s.get("name"), s.get("recipe_id") or s.get("handle"))
                         for s in _load_list(row.get("skills"))])]
    groups.append(("Not built", [(e.get("name"), e.get("reason")) for e in
                                 integra_state(row).get("plan") or [] if e.get("state") == "failed"]))
    if kb.get("id"):
        note = {"done": "{} document{}".format(kb.get("files"), "" if kb.get("files") == 1 else "s"),
                "failed": "documents not attached"}.get(kb.get("attach"), "")
        groups.append(("Knowledge base", [(kb.get("name"), note or kb["id"])]))
    for label, column in (("Project", "workato_projects"), ("Recipe", "recipes"),
                          ("Lookup table", "lookup_tables"), ("Data table", "data_tables")):
        groups.append((label, [(i.get("name"), i.get("id")) for i in _load_list(row.get(column))]))
    rows = [[_cell("Type", bold=True), _cell("Name", bold=True), _cell("ID / note", bold=True)]]
    for label, items in groups:
        for name, ident in items[:SUMMARY_LIST_MAX]:
            rows.append([_cell(label), _cell(_text(name or "", SUMMARY_NAME_MAX)),
                         _cell(_text(str(ident or ""), 100), code=True)])
        if len(items) > SUMMARY_LIST_MAX:
            rows.append([_cell(label), _cell("… and {} more".format(len(items) - SUMMARY_LIST_MAX)),
                         _cell(" ")])
    return {"type": "table", "rows": rows}


def summary_groups(row):
    """What the confirm step lists, as (title, second column, [(name, id or note)]): skills, those
    not built, the knowledge base, then the project's assets. Empty groups are left out, except
    Projects."""
    kb = integra_state(row).get("kb") or {}
    groups = [("Skills", "ID", [(s.get("name"), s.get("recipe_id") or s.get("handle"))
                                for s in _load_list(row.get("skills"))]),
              ("Not built", "Reason", [(e.get("name"), e.get("reason")) for e in
                                       integra_state(row).get("plan") or []
                                       if e.get("state") == "failed"])]
    if kb.get("id"):
        note = {"done": "{} document{}".format(kb.get("files"), "" if kb.get("files") == 1 else "s"),
                "failed": "documents not attached"}.get(kb.get("attach"), "")
        groups.append(("Knowledge base", "ID / note", [(kb.get("name"), note or kb["id"])]))
    for title, column in (("Projects", "workato_projects"), ("Recipes", "recipes"),
                          ("Lookup tables", "lookup_tables"), ("Data tables", "data_tables")):
        groups.append((title, "ID", [(i.get("name"), i.get("id")) for i in _load_list(row.get(column))]))
    return [g for g in groups if g[2] or g[0] == "Projects"]


def _raw(text):
    return {"type": "raw_text", "text": str(text) if str(text or "").strip() else "—"}


def summary_tables(row):
    """One data_table block per kind of thing, captioned with its name and count, so a long list
    of recipes has a table of its own. Every item is shown up to SUMMARY_TABLE_ROWS rows; past
    that the last row says how many more."""
    tables = []
    for title, second, items in summary_groups(row):
        room = SUMMARY_TABLE_ROWS - 1               # the header row takes one
        shown = items if len(items) <= room else items[:room - 1]
        rows = [[_raw("Name"), _raw(second)]]
        rows += [[_raw(_text(name or "", 120)), _raw(_text(ident or "", 100))] for name, ident in shown]
        if len(shown) < len(items):
            rows.append([_raw("… and {} more".format(len(items) - len(shown))), _raw("")])
        tables.append({"type": "data_table", "caption": "{} ({})".format(title, len(items)),
                       "rows": rows})
    return tables


def confirm_message_sections(key, row):
    """(blocks, attachments) like confirm_message_table, but with a table of its own for each
    kind of thing instead of one combined table."""
    blocks, attachments = confirm_message_table(key, row)
    at = next(i for i, b in enumerate(blocks) if b.get("type") == "table")
    blocks[at:at + 1] = summary_tables(row)
    return blocks, attachments


def confirm_message_table(key, row):
    """(blocks, attachments) like confirm_message, with the summary as a table. A table
    block can't go in an attachment, so everything is in the message and attachments is None."""
    persona = PERSONA_BY_KEY.get(row.get("persona"), {}).get("label", row.get("persona"))
    handle = row.get("id") or ""
    kb = integra_state(row).get("kb") or {}
    blocks = [
        # The mention is what notifies the creator: Integra can take minutes,
        # and editing a message never notifies anyone, only a new post does.
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "{}*{} is ready.* Have a look, then switch it on.".format(
             _mention(row), row.get("genie_name"))}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": "*Genie*\n<{}|{}>".format(GENIE_URL.format(handle),
                                                                 row.get("genie_name"))
             if handle else "*Genie*\n{}".format(row.get("genie_name"))},
            {"type": "mrkdwn", "text": "*Keyword*\n`{}`".format(row.get("invoke_keyword"))},
            {"type": "mrkdwn", "text": "*Channel*\n<#{}>".format(row.get("channel"))},
            {"type": "mrkdwn", "text": "*Persona*\n{}".format(persona)},
        ]},
        summary_table(row),
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
         "Confirm {}starts the genie and its skill recipes, adds this app to the "
         "channel and switches it on there.".format(
             "attaches the knowledge base, " if kb.get("id") else "")}]},
        _progress("confirm"),
        {"type": "actions", "elements": [
            _submit(ACTION_CONFIRM, key, "Confirm"),
            {"type": "button", "action_id": ACTION_CANCEL, "value": key, "style": "danger",
             "text": {"type": "plain_text", "text": "Cancel"}}]},
    ]
    return blocks, None


def draft_skills(skills):
    """Skills Integra could only save as a draft (recipe_builder_push returned
    target_system DRAFT): unusable until someone clicks Save in the editor."""
    return [s for s in _load_list(skills)
            if str(s.get("save_status") or "").strip().upper() == "DRAFT"]


def done_blocks(text):
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def loading_blocks(blocks, text):
    """The clicked message with every input and button taken out and a loading
    line in their place: it shows the click landed and cannot be clicked twice."""
    kept = [b for b in blocks
            if b.get("type") in ("section", "context", "header", "divider")
            and "accessory" not in b]
    return kept + [{"type": "context", "elements": [
        {"type": "mrkdwn", "text": "{} {}".format(LOADING_EMOJI, text)}]}]


# --------------------------------------------------------------------------
# Managing a genie that exists
# --------------------------------------------------------------------------

def _owner_ids(row):
    """Slack IDs of the people who own the genie's projects (from the stored mentions)."""
    ids = []
    for project in _load_list(row.get("workato_projects")):
        mention = str((project.get("owner") or {}).get("mention") or "")
        if re.fullmatch(r"<@[UW][A-Z0-9]+>", mention) and mention[2:-1] not in ids:
            ids.append(mention[2:-1])
    return ids


def manager_ids(row):
    """Who may change a genie: whoever created it, and its project owners. Nobody else."""
    ids = [str(row.get("creator_id") or "").strip()] + _owner_ids(row)
    return [i for n, i in enumerate(ids) if i and i not in ids[:n]]


def chooser_blocks(key, genies):
    """GENIECONFIG typed where a genie already lives: manage one of them, or make another.
    Every Manage button is in an actions block of its own: Slack rejects a block (invalid_blocks)
    whose buttons share an action_id, and they all must carry the same one."""
    names = ", ".join("*{}* (`{}`)".format(g.get("genie_name"), g.get("invoke_keyword"))
                      for g in genies[:4])
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "*This channel already has {}: {}*\nManage one, or create a new one.".format(
             "a genie" if len(genies) == 1 else "{} genies".format(len(genies)), names)}},
    ]
    for g in genies[:4]:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "action_id": ACTION_MANAGE, "value": g.get("record_key"),
             "text": {"type": "plain_text", "text": _text("Manage {}".format(
                 g.get("genie_name") or g.get("invoke_keyword")), 70)}}]})
    blocks.append({"type": "actions", "elements": [_submit(ACTION_NEW, key, "Create a new genie")]})
    return blocks


CHOOSER_MAX = 8      # genies listed on the chooser: three blocks each, and a message holds 50


def genie_facts(genie):
    """One line about a genie for the chooser: persona, skills, knowledge base, who made it, when."""
    skills = _load_list(genie.get("skills"))
    kb = integra_state(genie).get("kb") or {}
    persona = PERSONA_BY_KEY.get(genie.get("persona"), {}).get("label") or genie.get("persona")
    made = str(genie.get("created_at") or "")[:10]
    facts = [persona,
             "{} skill{}".format(len(skills), "" if len(skills) == 1 else "s") if skills else "no skills",
             ("knowledge base: " + _text(kb.get("name") or kb["id"], 40)) if kb.get("id") else "",
             "made by {}{}".format(_text(genie["creator_name"], 40), " on " + made if made else "")
             if genie.get("creator_name") else ("made " + made if made else "")]
    return "  ·  ".join(f for f in facts if f)


def chooser_blocks_new(key, genies):
    """The screen for GENIECONFIG typed where a genie already lives. A heading, then a block per
    genie -- its name (linked), keyword and a line of facts, with its own Manage button beneath --
    and Create a new genie at the end. Manage buttons sit in separate actions blocks: Slack
    rejects (invalid_blocks) buttons that share an action_id inside one block."""
    shown = genies[:CHOOSER_MAX]
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*{}*\n{}".format(
            "This channel already has a genie" if len(genies) == 1 else
            "This channel already has {} genies".format(len(genies)),
            "Manage it, or set up another one." if len(genies) == 1 else
            "Manage one of them, or set up another.")}},
    ]
    for genie in shown:
        blocks += [
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*{}*  ·  keyword `{}`\n{}".format(
                genie_link(genie), genie.get("invoke_keyword"), genie_facts(genie))}},
            {"type": "actions", "elements": [
                {"type": "button", "action_id": ACTION_MANAGE, "value": genie.get("record_key"),
                 "text": {"type": "plain_text", "text": "Manage " + _text(
                     genie.get("genie_name") or genie.get("invoke_keyword"), 50)}}]},
        ]
    blocks.append({"type": "divider"})
    if len(genies) > len(shown):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                       "…and {} more not shown here.".format(len(genies) - len(shown))}]})
    blocks += [
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
         "Only the person who made a genie, or the owner of its projects, can manage it."}]},
        {"type": "actions", "elements": [_submit(ACTION_NEW, key, "Create a new genie")]},
    ]
    return blocks


def post_chooser(ctx, key, genies):
    """The chooser in the look asked for (look = old keeps the first version). If Slack refuses
    the new one, the old one is posted and the reason goes in warnings."""
    if str(ctx.input.get("look") or "").strip().lower() != "old":
        try:
            ctx.post("This channel already has a genie", chooser_blocks_new(key, genies))
            return
        except StepError as exc:
            ctx.warnings.append("the new chooser was refused, posted the old one: {}".format(exc))
            ctx.slack.errors = []
    ctx.post("This channel already has a genie", chooser_blocks(key, genies))


def doc_state(doc):
    return doc.get("synced_at") or "not synced yet"


def manage_blocks(key, row, docs, note=""):
    """The manage card: what the genie is, what its knowledge base holds and when it was last
    synced, with the things a person can do."""
    kb = integra_state(row).get("kb") or {}
    synced = [d["synced_at"] for d in docs if d.get("synced_at")]
    failed = [d for d in docs if d.get("status") == "failed"]
    if kb.get("id"):
        kb_line = "{} · {} document{} · last synced {}".format(
            kb_link(kb), len(docs), "" if len(docs) == 1 else "s",
            max(synced) if synced else "never")
        if failed:
            kb_line += "\n:warning: {} could not be synced: {}".format(
                len(failed), ", ".join(_text(d.get("file_name") or d.get("file_id"), 40)
                                       for d in failed[:3]))
        if not docs:
            kb_line += "\n_No documents are registered for it here, so there is nothing to sync._"
    else:
        kb_line = "_none_"
    purpose = _text(" ".join(str(row.get("genie_purpose") or "").split()), 500)
    buttons = []
    if kb.get("id") and docs:
        buttons.append({"type": "button", "action_id": ACTION_RESYNC, "value": key, "style": "primary",
                        "text": {"type": "plain_text", "text": "Resync knowledge base"}})
    if kb.get("id"):
        buttons.append({"type": "button", "action_id": ACTION_DOCS, "value": key,
                        "text": {"type": "plain_text", "text": "Add documents"}})
    buttons.append({"type": "button", "action_id": ACTION_DESC, "value": key,
                    "text": {"type": "plain_text", "text": "Edit description"}})
    skills = _load_list(row.get("skills"))
    buttons.append({"type": "button", "action_id": ACTION_SKILLS_ADD, "value": key,
                    "text": {"type": "plain_text", "text": "Add skills"}})
    if skills:
        buttons.append({"type": "button", "action_id": ACTION_SKILLS_REMOVE, "value": key,
                        "text": {"type": "plain_text", "text": "Remove skills"}})
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "*Manage {}*  ·  keyword `{}`  ·  <#{}>".format(
             genie_link(row), row.get("invoke_keyword"), row.get("channel"))}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
         "*Description*\n{}\n*Skills ({})*\n{}\n*Knowledge base*\n{}".format(
             purpose or "_none_", len(skills), _names(skills, 8), kb_line)}},
    ]
    if note:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
    blocks.append({"type": "actions", "elements": buttons})
    return blocks


def docs_form_blocks(key, offered, registered, error=""):
    """Pick documents to add to the knowledge base. Only files that are not in it yet are
    offered (`registered` = the IDs that are), so there is nothing to untick: a document
    already in the knowledge base stays until it is removed in Workato."""
    new = [d for d in offered if d["file_id"] not in registered]
    head = {"type": "section", "text": {"type": "mrkdwn", "text":
            "*Add documents to the knowledge base*\n{}".format(
                "Pick what to add, then *Save and sync*. Every document, old and new, is "
                "synced again." if new else
                "_No new documents were found in the Drive folder: everything in it is "
                "already in this knowledge base._")}}
    buttons = ([_submit(ACTION_DOCS_SAVE, key, "Save and sync")] if new else []) + [
        {"type": "button", "action_id": ACTION_MANAGE_DONE, "value": key,
         "text": {"type": "plain_text", "text": "Back"}}]
    return [head, *_error(error), *_doc_blocks(new, ()), {"type": "actions", "elements": buttons}]


def description_form_blocks(key, purpose, error=""):
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Edit the genie's description*"}},
        *_error(error),
        _text_input("gc_purpose", "What should this genie do?",
                    "Who it helps, which records it looks up, and what questions it answers",
                    purpose, multiline=True),
        {"type": "actions", "elements": [
            _submit(ACTION_DESC_SAVE, key, "Save"),
            {"type": "button", "action_id": ACTION_MANAGE_DONE, "value": key,
             "text": {"type": "plain_text", "text": "Back"}}]},
    ]


def description_confirm_blocks(key, old, new):
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Apply this description?*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*Now*\n{}\n*New*\n{}".format(
            _text(" ".join(str(old or "").split()), 700) or "_none_",
            _text(" ".join(new.split()), 700))}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
         "It is saved in the table, set as the genie's description in Workato, and sent to the "
         "genie with every question. The genie's instructions are not touched, so any change made "
         "to them in Workato stays."}]},
        {"type": "actions", "elements": [
            _submit(ACTION_DESC_APPLY, key, "Apply"),
            {"type": "button", "action_id": ACTION_MANAGE_DONE, "value": key,
             "text": {"type": "plain_text", "text": "Cancel"}}]},
    ]


# --------------------------------------------------------------------------
# Reading a click
# --------------------------------------------------------------------------

def _load_list(value):
    if isinstance(value, list):
        return value
    try:
        loaded = json.loads(value or "[]")
    except ValueError:
        return []
    return loaded if isinstance(loaded, list) else []


def ruby_hash_to_json(text):
    """A Workato object pill mapped into a text field arrives as a Ruby hash
    ({"a"=>1, "b"=>nil}), not JSON. Outside string literals, => becomes : and
    nil becomes null; string contents are left exactly as they are."""
    out, i, in_string = [], 0, False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < len(text):
                out.append(text[i + 1])
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("=>", i):
            out.append(":")
            i += 1
        elif text.startswith("nil", i) and not text[i - 1:i].isalnum() \
                and not text[i + 3:i + 4].isalnum():
            out.append("null")
            i += 2
        else:
            out.append(char)
        i += 1
    return "".join(out)


def parse_payload(raw, warnings, field="payload_json"):
    """The Slack payload (or any object input, named by `field`) as a dict, whether
    it came as a dict, JSON or a Ruby hash."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    for candidate in (text, ruby_hash_to_json(text)):
        try:
            payload = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    warnings.append("{} could not be parsed; map it with .to_json".format(field))
    return {}


def read_click(input, warnings):
    """Everything a click carries, from the raw Slack payload when there is one,
    with the recipe's own fields as fallback.

    The payload's action_id wins over the `action` input: a payload means this
    is a click, whatever `action` was left set to in the recipe."""
    payload = parse_payload(input.get("payload_json"), warnings)
    actions = payload.get("actions") or [{}]
    container = payload.get("container") or {}
    message = payload.get("message") or {}
    # A button value is "<draft key>" or "<draft key>|<page>" on the projects step,
    # "<draft key>|<persona>" on a persona card.
    value = actions[0].get("value") or input.get("action_value") or ""
    key, _, page = value.partition("|")
    return {
        "action_id": (actions[0].get("action_id") or input.get("action")
                      or input.get("action_id") or ""),
        "key": key,
        "page": int(page) if page.isdigit() else 0,
        "arg": page,                               # whatever follows the key, as text
        "state": (payload.get("state") or {}).get("values") or {},
        "blocks": message.get("blocks") or [],     # the clicked message, as Slack has it
        "user_id": (payload.get("user") or {}).get("id") or input.get("user_id") or "",
        "channel": ((payload.get("channel") or {}).get("id") or container.get("channel_id")
                    or input.get("channel") or ""),
        "message_ts": (container.get("message_ts") or message.get("ts")
                       or input.get("message_ts") or ""),
        "thread_ts": (container.get("thread_ts") or message.get("thread_ts")
                      or input.get("thread_ts") or input.get("message_ts") or ""),
    }


def _state(state, block_id, action_id):
    return (state.get(block_id) or {}).get(action_id) or {}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def check_keyword(raw):
    value = (raw or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,15}", value):
        return None, "Keyword must be one word, 3-15 letters or digits."
    if value in RESERVED_KEYWORDS:
        return None, "`{}` is too common and would fire on normal chat.".format(value)
    return value, None


def check_name(raw):
    value = " ".join((raw or "").split())
    if not 3 <= len(value) <= 60:
        return None, "Genie name must be 3-60 characters."
    return value, None


def check_purpose(raw):
    value = (raw or "").strip()
    if len(value) < PURPOSE_MIN:
        return None, ("Tell Integra what the genie should do in a sentence or two "
                      "(at least {} characters).".format(PURPOSE_MIN))
    return value[:PURPOSE_MAX], None


def parse_emails(raw):
    """The email addresses in `raw`, lowercased and without repeats. Commas, semicolons, spaces
    and new lines all separate them, so "a@x.com, B@x.com;c@x.com" is three."""
    found = []
    for item in re.split(r"[,;\s]+", str(raw or "")):
        item = item.strip().strip("<>").lower()
        if item.startswith("mailto:"):
            item = item[7:]
        if "@" in item and item not in found:
            found.append(item)
    return found


NOT_AUTHORIZED = ("Sorry, I can't set up a genie for you: this is limited to a small group of "
                  "people. If you think you should have access, please ask the owners of the "
                  "Genie Console to add you.")


def _link(url, text):
    """A Slack link that shows only `text` (escaped: & < > | would break it)."""
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
        .replace("|", "/")
    return "<{}|{}>".format(url, text) if url else text


def kb_link(kb):
    """The knowledge base's name, linked to its page."""
    return _link(KB_PAGE_URL.format(kb["id"]) if kb.get("id") else "",
                 kb.get("name") or kb.get("id") or "")


def genie_link(row):
    """The genie's name, linked to its page (plain name before the genie exists)."""
    return _link(GENIE_URL.format(row["id"]) if row.get("id") else "", row.get("genie_name") or "")


def project_links(projects, limit=6):
    """Project names, each linked to its folder's assets page in Workato."""
    projects = _load_list(projects)
    names = ", ".join(_link(PROJECT_URL.format(p["folder_id"]) if p.get("folder_id") else "",
                            p.get("name") or str(p.get("id"))) for p in projects[:limit])
    more = len(projects) - limit
    return (names + (" and {} more".format(more) if more > 0 else "")) or "none"


def check_kb_name(raw):
    value = " ".join((raw or "").split())
    if not 3 <= len(value) <= 60:
        return None, "Knowledge base name must be 3-60 characters."
    return value, None


def check_kb_description(raw):
    value = (raw or "").strip()
    if len(value) < KB_DESCRIPTION_MIN:
        return None, ("Describe what the knowledge base holds in a sentence or two (at least "
                      "{} characters).".format(KB_DESCRIPTION_MIN))
    return value[:KB_DESCRIPTION_MAX], None


def check_kb_when(raw):
    value = (raw or "").strip()
    if len(value) < KB_WHEN_MIN:
        return None, ("Say when the genie should look in the knowledge base, in a sentence "
                      "(at least {} characters).".format(KB_WHEN_MIN))
    return value[:KB_WHEN_MAX], None


def kb_description(about, when):
    """What Workato keeps as the knowledge base's description: what it holds, then
    when the genie should use it."""
    return "{}\n\nUse this knowledge base when: {}".format(about, when)


def _split(value):
    """A comma-separated string, or a list, as a list of stripped strings."""
    items = value if isinstance(value, list) else str(value if value is not None else "").split(",")
    return [str(item).strip() for item in items]


def parse_kb_docs(raw, warnings):
    """The documents on offer, [{file_name, file_id}], from the kb_doc_detail input:
    {"file_name": "Doc A,Doc B", "file_id": "id1,id2"}, the names and the IDs each
    comma-separated, in the same order. [] when there are none, or -- with a warning --
    when the two lists don't line up: guessing which name goes with which ID could put
    the wrong document in the knowledge base."""
    detail = parse_payload(raw, warnings, "kb_doc_detail")
    names, ids = _split(detail.get("file_name")), _split(detail.get("file_id"))
    if not any(ids):
        return []
    if not any(names):
        names = [""] * len(ids)                 # no names given: the IDs label the options
    if len(names) != len(ids):
        warnings.append("kb_doc_detail: {} names but {} ids (a name with a comma in it?): "
                        "no documents offered".format(len(names), len(ids)))
        return []
    docs, seen = [], set()
    for name, file_id in zip(names, ids):
        if not file_id or file_id in seen:
            continue
        if len(file_id) > SLACK_OPTION_TEXT:    # an option's value is 75 characters at most
            warnings.append("kb_doc_detail: the id of '{}' is over {} characters: left out"
                            .format(_text(name, 40), SLACK_OPTION_TEXT))
            continue
        seen.add(file_id)
        docs.append({"file_name": name or file_id, "file_id": file_id})
    if len(docs) > KB_DOCS_MAX:
        warnings.append("kb_doc_detail: {} documents, but one Slack select holds {}: the rest "
                        "are not offered".format(len(docs), KB_DOCS_MAX))
    return docs[:KB_DOCS_MAX]


# --------------------------------------------------------------------------
# Integra: the genie that builds genies
# --------------------------------------------------------------------------

def integra_task(row, key, state, shared_skills=(), spec=None, attach=(), notes=""):
    """The task for Integra's current job, in the shape its job description
    expects (forge_genie_job_description.md). Change one, change the other.

    spec (the skill to build), attach (the built skills) and notes (the project
    notes) come from Integra's part rows; the outline in `state` has only names.

    shared_skills are attached to every genie as they are -- today the one
    analyst skill that hands recipe / job / table questions to the master
    genie, since a genie Integra creates has no AIRO MCP connection of its own."""
    persona = PERSONA_BY_KEY.get(row.get("persona")) or {}
    compact = lambda value: json.dumps(value if isinstance(value, list) else _load_list(value),
                                       separators=(",", ":"), ensure_ascii=False)
    job = state.get("job")
    if job == JOB_PLAN:
        job_lines = ["job: plan", "max_skills: {}".format(MAX_SKILLS),
                     "plan_scope: every object and system the recipes read or write, not only "
                     "the ones the purpose names"]
        if state.get("add_to"):
            job_lines += ["mode: add_skills",
                          "existing_skills: " + json.dumps(state.get("existing") or [],
                                                           ensure_ascii=False)]
    elif job == JOB_SKILL:
        planned = state.get("plan") or []
        job_lines = ["job: build_skill",
                     "skill_number: {} of {}".format(
                         len([e for e in planned[:state.get("next", 0) + 1]
                              if e.get("state") != "skipped"]), len(wanted(state))),
                     "skill_spec: " + json.dumps(spec, ensure_ascii=False)]
    elif state.get("add_to"):
        # Skills added to a genie that is already live: attach them and nothing else.
        job_lines = ["job: create_genie", "mode: add_skills",
                     "genie_id: " + str(row.get("id") or ""),
                     "skills_to_attach: " + compact(list(attach))]
    else:
        kb = state.get("kb") or {}
        job_lines = ["job: create_genie",
                     "skills_to_attach: " + compact(list(attach)),
                     # The knowledge base made on the kb step: Integra writes when to use it
                     # into the genie's instructions.
                     *(["knowledge_base: " + json.dumps(
                         {k: kb.get(k) or "" for k in ("id", "name", "about", "use_when")},
                         ensure_ascii=False)] if kb.get("id") else []),
                     "project_knowledge: |",
                     *["  " + line for line in (notes or "").splitlines()]]
    return "\n".join([
        "<forge_request>",
        "setup_key: " + key,
        "session_id: forge-" + key[len(DRAFT_PREFIX):],
        "target_folder_id: " + str(state.get("folder_id")),
        "genie_name: " + (row.get("genie_name") or ""),
        "invoke_keyword: " + (row.get("invoke_keyword") or ""),
        "persona: " + (row.get("persona") or ""),
        "persona_instructions: " + persona.get("instructions", ""),
        "projects: " + compact(row.get("workato_projects")),
        "recipes: " + compact(row.get("recipes")),
        "lookup_tables: " + compact(row.get("lookup_tables")),
        "data_tables: " + compact(row.get("data_tables")),
        "shared_skills: " + compact(list(shared_skills)),
        "</forge_request>",
        "",
        "<purpose>",
        row.get("genie_purpose") or "",
        "</purpose>",
        "",
        "<forge_job>",
        *job_lines,
        "</forge_job>",
    ])


def integra_state(row):
    """Integra's saved outline: {job, folder_id, card_ts, next, plan: [{name, state,
    ...}]}. The details of each skill and the notes are in the part rows."""
    raw = row.get("forge_state")
    if isinstance(raw, dict):               # a save in this run already put the dict there
        return raw
    try:
        state = json.loads(raw or "{}")
    except (TypeError, ValueError):
        state = {}
    return state if isinstance(state, dict) else {}


def skill_mode(state):
    """What the person asked for on the details step: every planned skill, pick from a list,
    or none at all."""
    mode = state.get("skill_mode")
    return mode if mode in (SKILLS_PICK, SKILLS_NONE) else SKILLS_ALL


def wanted(state):
    """The planned skills still to build or built: everything the person didn't leave out."""
    return [e for e in state.get("plan") or [] if e.get("state") != "skipped"]


def integra_part_key(setup_key, name):
    """The record_key of one of Integra's part rows: forge:<thread_ts>:s0 .. s5, notes."""
    return "forge:{}:{}".format(setup_key[len(DRAFT_PREFIX):], name)


def cap_lines(text, limit):
    """Cut text to at most `limit` characters, at a line end where there is one."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return (cut.rsplit("\n", 1)[0] if "\n" in cut else cut).rstrip()


def bound(value):
    """Cut the long strings and lists inside a spec or result, so a part row
    always fits its column."""
    if isinstance(value, str):
        return _text(value, SPEC_TEXT_MAX)
    if isinstance(value, list):
        return [bound(item) for item in value[:SPEC_ITEMS_MAX]]
    if isinstance(value, dict):
        return {key: bound(item) for key, item in value.items()}
    return value


def built_skills(state):
    """The skills column: the planned skills Integra built, as the confirm step and
    the recipe start need them."""
    return [{key: entry[key] for key in ("handle", "name", "recipe_id", "save_status")
             if entry.get(key) not in (None, "")}
            for entry in state.get("plan") or [] if entry.get("state") == "built"]


def _integra_plan(raw):
    """Integra's plan_json: a list of skill specs (or {"skills": [...]})."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw.strip() or "[]")
        except ValueError:
            return []
    if isinstance(raw, dict):
        raw = raw.get("skills") or []
    return [s for s in raw if isinstance(s, dict) and s.get("name")][:MAX_SKILLS] \
        if isinstance(raw, list) else []


def _minutes_since(iso):
    try:
        then = datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 60


def _integra_skills(raw):
    """Integra's skills_json: a list of {handle, name, recipe_id, ...}. Accepts the
    list itself or JSON text; anything without a handle is dropped."""
    skills = raw if isinstance(raw, list) else _load_list(str(raw or "").strip())
    return [s for s in skills if isinstance(s, dict) and (s.get("handle") or s.get("skill_handle"))]


# --------------------------------------------------------------------------
# Step handlers. Each returns the step the setup is now on.
# --------------------------------------------------------------------------

def handle_start(ctx):
    root = ctx.click["thread_ts"] or ctx.click["message_ts"]
    if not root or not ctx.click["channel"]:
        raise StepError("start needs channel and message_ts from the Slack trigger")
    key = DRAFT_PREFIX + root
    row = ctx.load(key, required=False)
    user = ctx.person()
    ctx.save(row, {
        "record_type": RECORD_TYPE, "record_key": key, "status": STATUS_STARTED,
        "setup_thread_ts": root, "channel": ctx.click["channel"],
        "creator_id": ctx.click["user_id"], "creator_name": user["name"],
        "creator_email": user["email"], "id": ctx.master_genie,
        "created_at": (row or {}).get("created_at") or now_iso(),
    })
    ctx.key = key
    genies, error = ctx.table.search({"$and": [{"record_type": {"$eq": RECORD_TYPE}},
                                               {"status": {"$eq": STATUS_ACTIVE}},
                                               {"channel": {"$eq": ctx.click["channel"]}}]}, 20)
    if error:
        ctx.warnings.append(error)
    if genies:
        # A genie already lives here: manage it, or make another.
        post_chooser(ctx, key, genies)
        return "choose"
    post_persona(ctx, key)
    return "persona"


def post_persona(ctx, key):
    banner = ctx.input.get("banner_url")
    picker = str(ctx.input.get("persona_picker") or "").strip().lower()
    picker = picker if picker in PERSONA_PICKERS else "list"
    try:
        ctx.post("What kind of genie do you want?", persona_blocks(key, banner_url=banner,
                                                                  picker=picker))
    except StepError as exc:
        if picker == "carousel":
            # Slack refused the cards (a client or workspace without carousels): the
            # dropdown always works, so the setup is never blocked by the new look.
            ctx.warnings.append("persona_picker carousel was refused ({}); posted the list "
                                "instead".format(exc))
            ctx.slack.errors = []
            ctx.post("What kind of genie do you want?", persona_blocks(key, banner_url=banner))
            return
        if not banner_blocks(banner):
            raise
        # Most likely Slack couldn't fetch the image: never let the banner
        # block the setup. Post without it and say why.
        ctx.warnings.append("banner_url could not be shown (Slack must be able to fetch it "
                            "publicly over https); posted without it")
        ctx.slack.errors = []
        ctx.post("What kind of genie do you want?", persona_blocks(key))


def handle_new(ctx):
    """Create a new genie, from the chooser."""
    ctx.load(ctx.click["key"])
    post_persona(ctx, ctx.key)
    ctx.done(":white_check_mark: Creating a new genie")
    return "persona"


def handle_persona(ctx):
    row = ctx.load(ctx.click["key"])
    picked = _state(ctx.click["state"], "gc_persona", "gc_persona_select")
    persona = ((picked.get("selected_option") or {}).get("value") or "")
    if persona not in PERSONA_BY_KEY:
        ctx.rerender("Pick a persona first.", persona_blocks(ctx.key, "Pick a persona first."))
        return "persona"
    return save_persona(ctx, row, persona)


def handle_persona_pick(ctx):
    """A persona card's Choose button: the persona is in the button's value."""
    row = ctx.load(ctx.click["key"])
    persona = ctx.click.get("arg") or ""
    if persona not in PERSONA_BY_KEY:
        ctx.warnings.append("persona card carried an unknown persona: {!r}".format(persona))
        ctx.rerender("Pick a persona first.", persona_blocks(
            ctx.key, "Pick a persona first.", picker="carousel"))
        return "persona"
    return save_persona(ctx, row, persona)


def save_persona(ctx, row, persona):
    projects = ctx.projects()
    ctx.save(row, {"persona": persona, "status": STATUS_PERSONA})
    # Next step first, then mark this one done: if the post fails, this
    # message keeps its Submit button and the user can simply try again.
    ctx.post("Which Workato projects?",
             projects_blocks(ctx.key, projects, 0, _load_list(row.get("workato_projects"))))
    ctx.done(":white_check_mark: *Persona:* " + PERSONA_BY_KEY[persona]["label"])
    return "projects"


def merge_picks(ctx, row, projects, page):
    """Saved picks from every page, with the page the click came from replaced
    by what is selected on it now. A page Slack sent no state for (nothing was
    touched) keeps its saved picks."""
    saved = _load_list(row.get("workato_projects"))
    on_page = _state(ctx.click["state"], "gc_projects", "gc_projects_select")
    if "selected_options" not in on_page:
        return saved
    by_id = {p["id"]: p for p in projects}
    page_ids = {p["id"] for p in project_page(projects, page)[0]}
    picks = [s for s in saved if s.get("id") not in page_ids]
    for option in on_page.get("selected_options") or []:
        try:
            project_id = json.loads(option.get("value") or "{}").get("id")
        except ValueError:
            continue
        project = by_id.get(project_id)
        if project and all(p.get("id") != project_id for p in picks):
            picks.append({"id": project["id"], "folder_id": project["folder_id"],
                          "name": project["name"]})
    return picks


def handle_projects_page(ctx):
    """'My project isn't listed' / 'Previous': keep this page's picks, show the
    other page in the same message."""
    row = ctx.load(ctx.click["key"])
    projects = ctx.projects()
    # The button's page is the page to go TO; the picks belong to the page shown.
    step = 1 if ctx.click["action_id"] == ACTION_PROJECTS_NEXT else -1
    current = ctx.click["page"] - step
    picks = merge_picks(ctx, row, projects, current)
    ctx.save(row, {"workato_projects": picks})
    ctx.slack.update(ctx.click["channel"], ctx.click["message_ts"], "Which Workato projects?",
                     projects_blocks(ctx.key, projects, ctx.click["page"], picks))
    return "projects"


def handle_projects(ctx):
    row = ctx.load(ctx.click["key"])
    projects = ctx.projects()
    chosen = merge_picks(ctx, row, projects, ctx.click["page"])
    if not chosen:
        ctx.rerender("Pick at least one project.",
                     projects_blocks(ctx.key, projects, ctx.click["page"], chosen,
                                     "Pick at least one project."))
        return "projects"

    assets = []
    for project in chosen:
        found, error = folder_assets(ctx.workato_token, project["folder_id"])
        if error:
            ctx.warnings.append(error)
        assets.extend(found)
        owner = ctx.project_owner(project, found)
        if owner:
            project["owner"] = owner
        else:
            project.pop("owner", None)        # don't keep one from an earlier Submit
    grouped = group_assets(assets)
    ctx.asset_types = ["{}: {}".format(k, v) for k, v in sorted(grouped["types"].items())]

    fields = {"workato_projects": chosen, "status": STATUS_PROJECTS,
              # who owns each project, kept in a column of its own (no emails: name + Slack mention)
              "project_owner": fit_column(
                  [dict(project=p.get("name"), **p["owner"]) for p in chosen if p.get("owner")],
                  "project_owner", ctx.warnings)}
    for column in ("recipes", "lookup_tables", "data_tables", "other_assets"):
        fields[column] = fit_column(grouped[column], column, ctx.warnings)
    ctx.save(row, fields)
    ctx.counts = {c: len(fields[c]) for c in ("recipes", "lookup_tables", "data_tables")}

    ctx.post("Name it and pick a channel",
             details_blocks(ctx.key, {"channel": row.get("channel")}))
    ctx.done(":white_check_mark: *Projects:* {}\n{} recipes · {} lookup tables · "
             "{} data tables".format(project_links(chosen, len(chosen)),
                                     ctx.counts["recipes"], ctx.counts["lookup_tables"],
                                     ctx.counts["data_tables"]))
    return "details"


def already_running(ctx, row, running=(STATUS_BUILDING, STATUS_KB_ATTACHING)):
    """The step to report when this setup is already past the one just clicked, "" when
    it isn't: the same click run twice (a recipe retry) must not start it again. Past it
    means Integra is building, or the recipe is attaching the knowledge base's documents."""
    status = row.get("status")
    age = _minutes_since(row.get("updated_at"))
    if status in running and age is not None and age < BUILDING_FRESH_MINUTES:
        ctx.warnings.append("already {} (updated {:.0f} min ago): duplicate run ignored".format(
            "building" if status == STATUS_BUILDING else "attaching documents", age))
        return "build" if status == STATUS_BUILDING else "kb"
    return ""


LIVE_STATUSES = (STATUS_ACTIVE, STATUS_DETAILS, STATUS_KB, STATUS_KB_ATTACHING, STATUS_BUILDING,
                 STATUS_BUILT, STATUS_BUILD_FAILED)     # a genie that exists or is being built


def duplicate_errors(ctx, row, name, keyword):
    """Why this name or keyword can't be used: another genie already has it, in any channel.
    Cancelled and unfinished (not yet named) setups don't count, nor does this setup itself."""
    rows, error = ctx.table.search({"record_type": {"$eq": RECORD_TYPE}}, 500)
    if error:
        ctx.warnings.append(error)
    name_error = keyword_error = ""             # the first clash of each kind is enough to say
    for other in rows:
        if other.get("record_key") == row.get("record_key") or other.get("status") not in LIVE_STATUSES:
            continue
        where = "<#{}>".format(other.get("channel")) if other.get("channel") else "another channel"
        if not name_error and str(other.get("genie_name") or "").strip().lower() == name.lower():
            name_error = ("A genie named *{}* already exists in {}. Pick a different name."
                          .format(other.get("genie_name"), where))
        if not keyword_error and str(other.get("invoke_keyword") or "").strip().upper() == keyword:
            keyword_error = ("`{}` is already the keyword of *{}* in {}. Pick another keyword."
                             .format(keyword, other.get("genie_name") or "another genie", where))
    return [e for e in (name_error, keyword_error) if e]


def handle_details(ctx):
    row = ctx.load(ctx.click["key"])
    step = already_running(ctx, row)
    if step:
        return step
    state = ctx.click["state"]
    raw_name = _state(state, "gc_name", "gc_name_input").get("value")
    raw_keyword = _state(state, "gc_keyword", "gc_keyword_input").get("value")
    raw_purpose = _state(state, "gc_purpose", "gc_purpose_input").get("value")
    channel = (_state(state, "gc_channel", "gc_channel_select").get("selected_conversation")
               or row.get("channel") or "")
    mode = (_state(state, "gc_skill_mode", "gc_skill_mode_select").get("selected_option") or {}
            ).get("value") or skill_mode(integra_state(row))
    entered = {"genie_name": raw_name, "invoke_keyword": raw_keyword, "channel": channel,
               "genie_purpose": raw_purpose, "skill_mode": mode}

    name, name_error = check_name(raw_name)
    keyword, keyword_error = check_keyword(raw_keyword)
    purpose, purpose_error = check_purpose(raw_purpose)
    errors = [e for e in (name_error, keyword_error, purpose_error) if e]
    if not channel:
        errors.append("Pick a channel.")
    if not errors:
        errors.extend(duplicate_errors(ctx, row, name, keyword))
    if errors:
        message = " ".join(errors)
        ctx.rerender(message, details_blocks(ctx.key, entered, message))
        return "details"

    fields = {"genie_name": name, "invoke_keyword": keyword, "channel": channel,
              "genie_purpose": purpose, "status": STATUS_DETAILS,
              "forge_state": dict(integra_state(row), skill_mode=mode)}
    ctx.save(row, fields)
    ctx.post("Attach a knowledge base?", kb_blocks(ctx.key, {}, docs=ctx.kb_docs()))
    ctx.done(":white_check_mark: *{}* · keyword `{}` · <#{}>".format(name, keyword, channel))
    return "kb"


def handle_kb_create(ctx):
    """Create knowledge base: both fields must be filled in, then Workato makes it in
    the genie's folder. With no documents picked the build starts. With some, the recipe
    is asked to attach them first (call_kb_attach, selected_kb_file) and kb_attach_result
    starts the build. A bad answer, or a refusal by Workato, re-renders this step with
    the reason, what was typed and what was picked; Skip is still there."""
    row = ctx.load(ctx.click["key"])
    # Not while attaching: the same click run again re-asks for the attach below, so a
    # recipe retry of a run that never answered doesn't leave the build waiting.
    step = already_running(ctx, row, (STATUS_BUILDING,))
    if step:
        return step
    state = ctx.click["state"]
    raw_name = _state(state, "gc_kb_name", "gc_kb_name_input").get("value")
    raw_description = _state(state, "gc_kb_description", "gc_kb_description_input").get("value")
    raw_when = _state(state, "gc_kb_when", "gc_kb_when_input").get("value")
    docs = ctx.kb_docs()
    picked = ctx.picked_docs(docs)
    entered = {"kb_name": raw_name, "kb_description": raw_description, "kb_when": raw_when,
               "kb_files": [d["file_id"] for d in picked]}

    name, name_error = check_kb_name(raw_name)
    description, description_error = check_kb_description(raw_description)
    when, when_error = check_kb_when(raw_when)
    errors = [e for e in (name_error, description_error, when_error) if e]
    if errors and not any((v or "").strip() for v in (raw_name, raw_description, raw_when)):
        errors = ["Fill in a name, a description and when the genie should use it to create a "
                  "knowledge base, or click *Skip knowledge base* to carry on without one."]
    if errors:
        message = " ".join(errors)
        ctx.rerender(message, kb_blocks(ctx.key, entered, message, docs))
        return "kb"

    outline = integra_state(row)
    kb = outline.get("kb") or {}
    if kb.get("id"):
        # An earlier click made it (and then failed further on, or this click is run
        # again): never make a second.
        ctx.warnings.append("knowledge base {} was already made for this setup: reused"
                            .format(kb.get("name") or kb["id"]))
        if kb.get("attach") == "done":
            picked = []                 # its documents are in already: never attach twice
    else:
        try:
            kb = ctx.create_kb(row, name, kb_description(description, when))
            kb = dict(kb, about=description, use_when=when)     # Integra puts them in the genie
        except StepError as exc:
            message = str(exc)
            ctx.rerender(message, kb_blocks(ctx.key, entered, message, docs))
            return "kb"
    ctx.result.update({"kb_id": kb["id"], "kb_name": kb["name"]})
    if picked:
        # Nothing here can put documents in a knowledge base: hand them to the recipe
        # and wait for kb_attach_result. ts is this message, edited when that comes.
        kb = dict(kb, attach="pending", files=len(picked), ts=ctx.click["message_ts"])
        ctx.save_docs(row, picked)          # one row each: what a later resync re-sends
        ctx.save(row, {"forge_state": dict(outline, kb=kb), "status": STATUS_KB_ATTACHING})
        ctx.result.update({"call_kb_attach": True, "selected_kb_file": picked})
        ctx.done("{} *Knowledge base:* {} · attaching {} document{}: {}".format(
            LOADING_EMOJI, kb_link(kb), len(picked), "" if len(picked) == 1 else "s",
            _names([{"id": d["file_id"], "name": d["file_name"]} for d in picked], 5)))
        return "kb"
    ctx.save(row, {"forge_state": dict(outline, kb=kb), "status": STATUS_KB})
    ctx.start_integra(row, fresh=True)
    ctx.done(":white_check_mark: *Knowledge base:* {}".format(kb_link(kb)))
    return "build"


def handle_kb_attach_result(ctx):
    """The recipe has tried to attach the selected documents to the knowledge base.
    Called by the function recipe, not a button, with action_value = this step's
    record_key and channel / thread_ts from the step that asked (call_kb_attach):
    kb_attach_status = success, or failed with kb_attach_error. The outcome goes on the
    knowledge base's line in Slack and Integra starts. Documents that didn't go in never
    stop the build: the knowledge base exists, just empty."""
    row = ctx.load(ctx.click["key"])
    outline = integra_state(row)
    kb = dict(outline.get("kb") or {})
    if kb.get("attach") not in ("pending", "done", "failed"):
        raise StepError("No knowledge base is waiting for its documents. Type `recipeconfig` "
                        "to start again.")
    step = already_running(ctx, row, (STATUS_BUILDING,))
    if step:
        return step
    if kb.get("resync"):
        return finish_resync(ctx, row, outline, kb)
    if kb["attach"] == "pending":
        failure = attach_failure(ctx)
        ctx.mark_docs(row, ctx.kb_doc_rows(row), failure)
        kb["attach"] = "failed" if failure else "done"
        if failure:
            kb["reason"] = _text(failure, 200)
            text = (":warning: *Knowledge base:* {} · its documents weren't attached: {}. "
                    "It was created empty: add them in Workato.".format(
                        kb_link(kb), kb["reason"]))
        else:
            text = (":white_check_mark: *Knowledge base:* {} · {} document{} attached"
                    .format(kb_link(kb), kb.get("files"),
                            "" if kb.get("files") == 1 else "s"))
        ctx.slack.update(ctx.click["channel"], kb.get("ts"), text, done_blocks(text))
        ctx.save(row, {"forge_state": dict(outline, kb=kb), "status": STATUS_KB})
    else:
        # Recorded by an earlier run that then failed to start Integra: carry on from there.
        ctx.warnings.append("the documents' outcome ({}) was already recorded: carrying on "
                            "to Integra".format(kb["attach"]))
    ctx.result.update({"kb_id": kb["id"], "kb_name": kb.get("name", "")})
    ctx.start_integra(row, fresh=True)
    return "build"


def attach_failure(ctx):
    """Why the documents didn't go in, "" when they did (kb_attach_status / kb_attach_error)."""
    status = str(ctx.input.get("kb_attach_status") or "").strip().lower()
    failure = str(ctx.input.get("kb_attach_error") or "").strip()
    if not failure and status not in KB_ATTACH_OK:
        failure = ("the recipe reported {}".format(status) if status
                   else "the recipe sent no kb_attach_status")
    return failure


def begin_resync(ctx, row, docs):
    """Ask the recipe to put every registered document into the knowledge base again. The
    knowledge base's documents are upserted by their Drive ID, so this replaces their content
    and never duplicates one. Reuses the attach hand-off: call_kb_attach / selected_kb_file,
    then the recipe calls kb_attach_result, which finish_resync answers."""
    outline = integra_state(row)
    kb = dict(outline.get("kb") or {})
    picked = [{"file_name": d.get("file_name") or d["file_id"], "file_id": d["file_id"]}
              for d in docs]
    kb.update(attach="pending", resync=True, files=len(picked), ts=ctx.click["message_ts"])
    ctx.save(row, {"forge_state": dict(outline, kb=kb)})
    ctx.result.update({"call_kb_attach": True, "selected_kb_file": picked,
                       "kb_id": kb["id"], "kb_name": kb.get("name", "")})
    ctx.audit(row, "knowledge base resync started: {} document{}".format(
        len(picked), "" if len(picked) == 1 else "s"))
    return picked


def finish_resync(ctx, row, outline, kb):
    """The recipe has put the documents in again (or failed). Shows the manage card with the
    outcome when a person asked; a scheduled run is silent unless it failed, and then the
    genie's managers are told."""
    failure = attach_failure(ctx)
    ctx.mark_docs(row, ctx.kb_doc_rows(row), failure)
    ts = kb.pop("ts", "")
    kb.pop("resync", None)
    kb["attach"] = "failed" if failure else "done"
    if failure:
        kb["reason"] = _text(failure, 200)
    ctx.save(row, {"forge_state": dict(outline, kb=kb)})
    ctx.audit(row, "knowledge base resync " + ("failed: " + kb["reason"] if failure else "done"))
    ctx.result.update({"kb_id": kb["id"], "kb_name": kb.get("name", "")})
    note = (":warning: The sync failed: {}".format(kb["reason"]) if failure
            else ":white_check_mark: Knowledge base synced.")
    if ts:
        ctx.slack.update(ctx.click["channel"], ts, "Manage " + str(row.get("genie_name")),
                         manage_blocks(row.get("record_key"), row, ctx.kb_doc_rows(row), note))
    elif failure:
        ctx.notify_managers(row, ":warning: The daily knowledge base sync for *{}* failed: {}"
                            .format(row.get("genie_name"), kb["reason"]))
    return "manage"


def handle_choose_manage(ctx):
    """Manage on the chooser, and Back from any manage form: show the manage card."""
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    ctx.show("Manage " + str(row.get("genie_name")),
             manage_blocks(ctx.key, row, ctx.kb_doc_rows(row)))
    return "manage"


def handle_resync(ctx):
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    kb = integra_state(row).get("kb") or {}
    docs = ctx.kb_doc_rows(row)
    if not kb.get("id") or not docs:
        ctx.show("Manage " + str(row.get("genie_name")), manage_blocks(
            ctx.key, row, docs, ":warning: There is no knowledge base with documents to sync."))
        return "manage"
    picked = begin_resync(ctx, row, docs)
    ctx.done("{} *Knowledge base:* {} · syncing {} document{}: {}".format(
        LOADING_EMOJI, kb_link(kb), len(picked), "" if len(picked) == 1 else "s",
        _names([{"id": d["file_id"], "name": d["file_name"]} for d in picked], 5)))
    return "manage"


def handle_kb_resync(ctx):
    """The daily sync, once per genie (action_value = its row key). No person to answer: the
    result goes in the table and, if it failed, to the genie's managers. Only an active
    genie is synced: a draft, cancelled or half-built setup is left alone."""
    row = ctx.load(ctx.click["key"])
    kb = integra_state(row).get("kb") or {}
    docs = ctx.kb_doc_rows(row)
    ctx.click["channel"] = ctx.click["channel"] or str(row.get("channel") or "")
    if row.get("status") != STATUS_ACTIVE:
        ctx.warnings.append("{} is not active ({}): not synced".format(ctx.key, row.get("status")))
        return "manage"
    if not kb.get("id") or not docs:
        ctx.warnings.append("nothing to sync for {}".format(ctx.key))
        return "manage"
    begin_resync(ctx, row, docs)
    return "manage"


def handle_kb_sync_list(ctx):
    """The genies the daily sync should visit: active ones that have a knowledge base."""
    rows, error = ctx.table.search({"$and": [{"record_type": {"$eq": RECORD_TYPE}},
                                             {"status": {"$eq": STATUS_ACTIVE}}]}, 200)
    if error:
        raise StepError(error)
    ctx.result["sync_keys"] = [{"record_key": r["record_key"]} for r in rows
                               if (integra_state(r).get("kb") or {}).get("id")]
    return "manage"


def handle_docs(ctx):
    """Add documents: offer the Drive files that are not in the knowledge base yet. The list
    comes with this click (kb_doc_detail: the Click recipe fetches it for this button)."""
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    if not (integra_state(row).get("kb") or {}).get("id"):
        ctx.show("Manage " + str(row.get("genie_name")), manage_blocks(
            ctx.key, row, ctx.kb_doc_rows(row), ":warning: This genie has no knowledge base."))
        return "manage"
    offered = ctx.kb_docs()
    if not offered:
        ctx.warnings.append("no kb_doc_detail on this click: the Click recipe must fetch the "
                            "Drive file list for gc_console_docs")
    registered = {d["file_id"] for d in ctx.kb_doc_rows(row)}
    ctx.show("Add documents", docs_form_blocks(ctx.key, offered, registered))
    return "manage"


def handle_docs_save(ctx):
    """Register the picked documents (one row each) and sync the whole knowledge base."""
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    kb = integra_state(row).get("kb") or {}
    offered = ctx.kb_docs()                # recovered from the dropdown in the clicked message
    picked = ctx.picked_docs(offered)
    registered = {d["file_id"] for d in ctx.kb_doc_rows(row)}
    if not picked:
        ctx.show("Add documents", docs_form_blocks(ctx.key, offered, registered,
                                                   "Pick at least one document."))
        return "manage"
    ctx.save_docs(row, picked)
    ctx.audit(row, "documents added: {}".format(
        ", ".join(_text(d["file_name"], 40) for d in picked[:5])))
    docs = ctx.kb_doc_rows(row)
    shown = begin_resync(ctx, row, docs)
    ctx.done("{} *Knowledge base:* {} · adding {} and syncing {} document{}".format(
        LOADING_EMOJI, kb_link(kb), len(picked), len(shown), "" if len(shown) == 1 else "s"))
    return "manage"


def handle_desc(ctx):
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    ctx.show("Edit the description", description_form_blocks(ctx.key, row.get("genie_purpose")))
    return "manage"


def handle_desc_save(ctx):
    """Check the new text and ask to confirm. The text waits in the row's forge_state."""
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    raw = _state(ctx.click["state"], "gc_purpose", "gc_purpose_input").get("value")
    purpose, error = check_purpose(raw)
    if error:
        ctx.show(error, description_form_blocks(ctx.key, raw, error))
        return "manage"
    if purpose == str(row.get("genie_purpose") or "").strip():
        ctx.show("Manage " + str(row.get("genie_name")), manage_blocks(
            ctx.key, row, ctx.kb_doc_rows(row), "The description is unchanged."))
        return "manage"
    ctx.save(row, {"forge_state": dict(integra_state(row), pending_purpose=purpose)})
    ctx.show("Apply this description?",
             description_confirm_blocks(ctx.key, row.get("genie_purpose"), purpose))
    return "manage"


def handle_desc_apply(ctx):
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    outline = integra_state(row)
    purpose = outline.pop("pending_purpose", "")
    if not purpose:
        ctx.show("Manage " + str(row.get("genie_name")), manage_blocks(
            ctx.key, row, ctx.kb_doc_rows(row), ":warning: There was nothing waiting to apply."))
        return "manage"
    before = str(row.get("genie_purpose") or "")
    ctx.save(row, {"genie_purpose": purpose, "forge_state": outline})
    problem = ctx.update_genie_description(row.get("id"), purpose)
    ctx.audit(row, "description changed ({} -> {} characters){}".format(
        len(before), len(purpose), "; Workato refused the genie update: " + problem if problem else ""))
    note = ":white_check_mark: Description updated."
    if problem:
        note += " :warning: Saved here and sent with every question, but Workato didn't take it " \
                "on the genie itself: {}".format(problem)
    ctx.show("Manage " + str(row.get("genie_name")),
             manage_blocks(ctx.key, row, ctx.kb_doc_rows(row), note))
    return "manage"


def handle_skills_pick(ctx):
    """Build selected skills: leave out the planned skills that weren't ticked, then carry on
    with the build (a new building card, and the first skill's job for the recipe's loop)."""
    row = ctx.load(ctx.click["key"])
    state = integra_state(row)
    if not state.get("choosing"):
        ctx.warnings.append("no skills waiting to be picked: duplicate click ignored")
        return "build"
    chosen = [i for i in picked_values(ctx) if i < len(state.get("plan") or [])]
    if not chosen:
        ctx.rerender("Pick at least one skill.", skills_pick_blocks(
            ctx.key, plan_entries(state), "Which skills should Integra build?", ACTION_SKILLS_PICK,
            "Build selected skills", "Pick at least one skill, or choose No skills.", cancel=True,
            skip=not state.get("add_to")))
        return "build"
    for index, entry in enumerate(state["plan"]):
        if index not in chosen:
            entry["state"] = "skipped"
    state.pop("choosing", None)
    state.update({"job": JOB_SKILL, "next": chosen[0]})
    ctx.save(row, {"forge_state": state})
    ctx.done(":white_check_mark: Building {} skill{}: {}".format(
        len(chosen), "" if len(chosen) == 1 else "s",
        ", ".join(_text(state["plan"][i]["name"], 50) for i in chosen)))
    ctx.post_building_card(row, state)
    return "build"


def handle_skills_none(ctx):
    """No skills: every planned skill is left out and the build goes straight to creating the
    genie. (Only offered for a new genie: adding skills to a live one has Cancel.)"""
    row = ctx.load(ctx.click["key"])
    state = integra_state(row)
    if not state.get("choosing") or state.get("add_to"):
        ctx.warnings.append("no skills waiting to be picked: duplicate click ignored")
        return "build"
    for entry in state.get("plan") or []:
        entry["state"] = "skipped"
    state.pop("choosing", None)
    state.update({"job": JOB_GENIE, "next": len(state.get("plan") or []),
                  "skill_mode": SKILLS_NONE})       # also keeps the shared analyst skill off
    ctx.save(row, {"forge_state": state})
    ctx.done(":white_check_mark: No skills: creating the genie without any.")
    ctx.post_building_card(row, state)
    return "build"


def finish_add(ctx, row, state, built):
    """The last Integra job of an "add skills" run: the genie has them. Put them on the genie's own
    row, start their recipes, and close this run's row. (`row` is the run's own row.)"""
    genie = ctx.load(state["add_to"], required=False)
    if not genie:
        raise StepError("The genie these skills were for is no longer in the table.")
    outline = integra_state(genie)
    outline.pop("adding", None)
    ctx.save(genie, {"skills": _load_list(genie.get("skills")) + built, "forge_state": outline})
    started, failed = ctx.start_recipes(built)
    ctx.save(row, {"status": STATUS_ADD_DONE, "skills": built, "forge_state": state})
    ctx.audit(genie, "skills added: {}".format(", ".join(_text(s.get("name"), 40) for s in built)))
    missed = [e for e in wanted(state) if e.get("state") == "failed"]
    text = ":white_check_mark: Added {} skill{} to *{}*: {}.".format(
        len(built), "" if len(built) == 1 else "s", genie.get("genie_name"),
        ", ".join(_text(s.get("name"), 50) for s in built) or "none")
    if missed:
        text += "\n:x: Not built: " + ", ".join(
            "{} ({})".format(_text(e["name"], 50), _text(e.get("reason") or "", 80)) for e in missed)
    if failed:
        text += "\n:warning: Couldn't start the recipe of {}: start {} in Workato.".format(
            ", ".join(failed), "it" if len(failed) == 1 else "them")
    ctx.result.update({"genie_handle": row.get("id"), "skills_count": len(built),
                       "recipes_started": started})
    ctx.done(text)
    ctx.notify_creator(row, "Your new skills are on the genie and switched on.")


def handle_skills_add(ctx):
    """Add skills: Integra reads the project again, plans the skills this genie doesn't have, the
    person picks, Integra builds and attaches them. The run lives in a row of its own (a copy of
    the genie's setup) so the genie's row, and the answers it gives, are untouched meanwhile."""
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    outline = integra_state(row)
    # One run at a time. Asked of the run's own row, not of a timestamp kept here: a run that
    # finished, found nothing, failed or was cancelled no longer counts, whatever it left behind.
    run = ctx.load(outline.get("adding"), required=False) if outline.get("adding") else None
    age = _minutes_since((run or {}).get("updated_at"))
    if run and run.get("status") == STATUS_BUILDING and age is not None \
            and age < BUILDING_FRESH_MINUTES:
        waiting = integra_state(run).get("choosing")
        ctx.show("Manage " + str(row.get("genie_name")), manage_blocks(
            ctx.key, row, ctx.kb_doc_rows(row),
            ":point_up: Skills are waiting for you in the picker posted earlier in this thread. "
            "Pick from it, or press *Cancel* there, then try again." if waiting else
            ":hourglass: Integra is already looking for skills to add. Wait for it to finish, "
            "then try again."))
        return "manage"
    if row.get("status") != STATUS_ACTIVE or not str(row.get("id") or "").startswith("gin-"):
        ctx.show("Manage " + str(row.get("genie_name")), manage_blocks(
            ctx.key, row, ctx.kb_doc_rows(row), ":warning: Skills can only be added to a genie "
            "that is live."))
        return "manage"
    stamp = "add" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run_key = DRAFT_PREFIX + stamp
    copied = ("genie_name", "invoke_keyword", "channel", "workato_projects", "recipes",
              "lookup_tables", "data_tables", "persona", "genie_purpose", "id", "project_owner",
              "other_assets", "creator_name", "creator_email")
    fields = {name: row.get(name) for name in copied}
    fields.update({
        "record_type": RECORD_TYPE, "record_key": run_key, "setup_thread_ts": stamp,
        "creator_id": ctx.click["user_id"], "created_at": now_iso(), "status": STATUS_BUILDING,
        "forge_state": {"add_to": row.get("record_key"), "skill_mode": SKILLS_PICK,
                        "existing": [s.get("name") for s in _load_list(row.get("skills"))]}})
    ctx.save(None, fields)
    ctx.save(row, {"forge_state": dict(outline, adding=run_key, adding_at=now_iso())})
    ctx.key = run_key
    ctx.start_integra(ctx.load(run_key), fresh=False)
    # No spinner here: nothing edits this line again (the building card below carries the progress)
    ctx.done(":mag: *Skills:* asked Integra to look for new skills for *{}*. Progress is below."
             .format(row.get("genie_name")))
    return "build"


def handle_skills_remove(ctx):
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    skills = _load_list(row.get("skills"))
    if not skills:
        ctx.show("Manage " + str(row.get("genie_name")), manage_blocks(
            ctx.key, row, ctx.kb_doc_rows(row), ":warning: This genie has no skills built here."))
        return "manage"
    ctx.show("Remove skills", skills_pick_blocks(
        ctx.key, [(str(i), s.get("name") or s.get("handle") or "skill", "")
                  for i, s in enumerate(skills)],
        "Which skills should be removed from {}?".format(row.get("genie_name")),
        ACTION_SKILLS_REMOVE_APPLY, "Remove selected skills", back=True))
    return "manage"


def handle_skills_remove_apply(ctx):
    """Detach the ticked skills from the genie, stop their recipes and forget them here."""
    row = ctx.load(ctx.click["key"])
    ctx.require_manager(row)
    skills = _load_list(row.get("skills"))
    chosen = [i for i in picked_values(ctx) if i < len(skills)]
    if not chosen:
        ctx.show("Remove skills", skills_pick_blocks(
            ctx.key, [(str(i), s.get("name") or s.get("handle") or "skill", "")
                      for i, s in enumerate(skills)],
            "Which skills should be removed from {}?".format(row.get("genie_name")),
            ACTION_SKILLS_REMOVE_APPLY, "Remove selected skills", "Pick at least one skill.",
            back=True))
        return "manage"
    removed, failed = ctx.detach_skills(row.get("id"), [skills[i] for i in chosen])
    gone = {id(s) for s in removed}
    ctx.save(row, {"skills": [s for s in skills if id(s) not in gone]})
    ctx.stop_recipes(removed)
    names = ", ".join(_text(s.get("name"), 40) for s in removed)
    if removed:
        ctx.audit(row, "skills removed: " + names)
    note = ":white_check_mark: Removed {}.".format(names) if removed else ""
    if failed:
        note += " :warning: Couldn't remove {}.".format(
            ", ".join("{} ({})".format(_text(s.get("name"), 40), why) for s, why in failed))
    if removed:
        note += (" The genie's instructions still mention them by name; edit those in Workato if "
                 "you want the text to match.")
    ctx.show("Manage " + str(row.get("genie_name")),
             manage_blocks(ctx.key, row, ctx.kb_doc_rows(row), note.strip()))
    return "manage"


def handle_kb_skip(ctx):
    row = ctx.load(ctx.click["key"])
    step = already_running(ctx, row)
    if step:
        return step
    outline = integra_state(row)
    made = outline.pop("kb", None)
    if made:
        # Skip is the latest answer: don't attach one an earlier, failed click made.
        ctx.warnings.append("skipped, but an earlier click made knowledge base {}: it is "
                            "not attached".format(made.get("id")))
    ctx.save(row, {"forge_state": outline, "status": STATUS_KB})
    ctx.start_integra(row, fresh=True)
    ctx.done(":fast_forward: *Knowledge base:* skipped")
    return "build"


def handle_integra_retry(ctx):
    """Try again: resume at the job that failed; nothing done so far is redone."""
    row = ctx.load(ctx.click["key"])
    ctx.start_integra(row, fresh=False)
    ctx.done(":arrows_counterclockwise: Asked Integra to carry on from where it stopped.")
    return "build"


def handle_integra_next(ctx):
    """Top of the recipe's REPEAT loop: hand back the task for Integra's next job,
    read from the saved progress. Posts and changes nothing, so every step in the
    loop only uses outputs from steps above it in the same round."""
    row = ctx.load(ctx.click["key"])
    state = integra_state(row)
    if state.get("job") in (None, "", JOB_DONE) or row.get("status") != STATUS_BUILDING:
        ctx.warnings.append("nothing for Integra to do (status {}, job {})".format(
            row.get("status"), state.get("job")))
        return "build"
    ctx.next_integra_job(row, state, state.get("card_ts", ""))
    return "build"


def handle_integra_result(ctx):
    """One Integra job has finished. Called by the function recipe, not a button,
    with message_ts = the building card. Records the result, updates the card,
    and hands the recipe the next job (call_forge) until the genie exists.

    Integra's plan, each skill's result and the project notes go in part rows; the
    setup row keeps only the outline. A refused table write ends the loop with
    Try again, from what was saved before, instead of leaving the card hanging."""
    row = ctx.load(ctx.click["key"])
    state = integra_state(row)
    # The building card: saved with the progress, so the recipe needn't map it.
    ctx.click["message_ts"] = ctx.click["message_ts"] or state.get("card_ts", "")
    job = state.get("job") or JOB_PLAN
    error = str(ctx.input.get("forge_error") or "").strip()
    if str(ctx.input.get("forge_status") or "").strip().lower() == "failed" and not error:
        error = "Integra reported status failed without saying why."
    ctx.result["forge_job"] = job

    answered = any(str(ctx.input.get(name) or "").strip() for name in (
        "forge_status", "forge_error", "forge_genie_id", "forge_skills_json", "forge_plan_json"))
    if not answered and job != JOB_SKILL:
        # The Assign-task step itself failed or timed out (the recipe's monitor
        # around it caught the error and logged it). Without a plan or a genie
        # there is nothing to carry on with: stop, keep the progress, and offer
        # Try again for this same job. (A skill that gets no answer is handled
        # below: it fails alone.)
        return ctx.integra_failed(row, state, "Integra didn't answer: the Assign task step failed "
                                "or timed out. The error is in this run's job log in Workato.")

    try:
        if job == JOB_PLAN:
            plan = _integra_plan(ctx.input.get("forge_plan_json"))
            if state.get("add_to") and not error and not plan:
                state["job"] = JOB_DONE
                ctx.save(row, {"status": STATUS_ADD_DONE, "forge_state": state})
                ctx.done(":information_source: Integra found no skill that this genie doesn't "
                         "already have.")
                return "build"
            if error or not plan:
                return ctx.integra_failed(row, state, error or "Integra's plan had no skills in it.")
            notes = cap_lines(ctx.input.get("forge_project_knowledge"), NOTES_MAX)
            ctx.save_part("notes", {"status": "notes"}, {"text": notes})
            for index, spec in enumerate(plan):
                ctx.save_part("s{}".format(index),
                              {"status": "planned", "genie_name": spec["name"]},
                              {"spec": bound(spec)})
            state.update({"plan": [{"name": spec["name"],
                                    "about": _text(spec.get("description") or "", 75)}
                                   for spec in plan],
                          "next": 0, "job": JOB_SKILL})
            if state.get("add_to") or skill_mode(state) == SKILLS_PICK:
                # Stop here and let the person choose: nothing more is handed to the recipe's
                # loop (call_forge stays false) until the pick comes back as a click.
                state["choosing"] = True
                ctx.save(row, {"forge_state": state})
                ctx.done(":white_check_mark: Integra found {} skill{} {}".format(
                    len(plan), "" if len(plan) == 1 else "s",
                    "this genie doesn't have yet" if state.get("add_to") else "to choose from"))
                ctx.post("Pick the skills to build", skills_pick_blocks(
                    ctx.key, plan_entries(state), "Which skills should Integra build?",
                    ACTION_SKILLS_PICK, "Build selected skills", cancel=True,
                    skip=not state.get("add_to")))
                return "build"

        elif job == JOB_SKILL:
            index = state.get("next", 0)
            entry = state["plan"][index]
            spec = ctx.part("s{}".format(index)).get("spec") or {}
            built = _integra_skills(ctx.input.get("forge_skills_json"))
            skill = built[0] if built else None
            if skill:
                skill["handle"] = skill.get("handle") or skill.get("skill_handle")
                skill.setdefault("description", spec.get("description", ""))
            # One skill that can't be built never stops the build: it is marked failed
            # (a red cross on the card) and the next one is tried.
            if not answered:
                failure = "no answer from Integra (task failed or timed out; see the job log)"
            elif error:
                failure = error
            elif not skill:
                failure = "no skill returned"
            elif draft_skills([skill]):
                failure = "saved only as a draft"
            else:
                failure = ""
            if failure:
                reason = _text(failure, 200)
                entry.update({"state": "failed", "reason": reason})
                outcome, status = {"spec": spec, "error": reason}, "failed"
            else:
                entry.update({"state": "built", **{key: skill[key] for key in (
                    "handle", "recipe_id", "save_status") if skill.get(key) not in (None, "")}})
                outcome, status = {"spec": spec, "result": bound(skill)}, "built"
            ctx.save_part("s{}".format(index), {"status": status}, outcome)
            state["next"] = index + 1
            while state["next"] < len(state["plan"]) and \
                    state["plan"][state["next"]].get("state") == "skipped":
                state["next"] += 1                  # a skill the person left out
            if state["next"] >= len(state["plan"]):
                state["job"] = JOB_GENIE

        else:                                        # create_genie
            genie_id = str(ctx.input.get("forge_genie_id") or "").strip()
            if error or not genie_id.startswith("gin-"):
                return ctx.integra_failed(row, state, error or "Integra did not return a genie ID (gin-...).")
            state["job"] = JOB_DONE
            skills = built_skills(state)
            if state.get("add_to"):
                finish_add(ctx, row, state, skills)
                return "build"
            ctx.save(row, {"id": genie_id, "skills": skills, "status": STATUS_BUILT,
                           "forge_state": state})
            ctx.result.update({"genie_handle": genie_id, "skills_count": len(skills)})

        if job != JOB_GENIE:
            ctx.save(row, {"forge_state": state})
    except StepError as exc:
        return ctx.integra_failed(row, integra_state(row), str(exc))

    if job == JOB_GENIE:
        # The notification text carries the mention too: it is what the push shows.
        text = "{}{} is ready to switch on".format(_mention(row), row.get("genie_name"))
        post_confirm(ctx, text, row)
        failed = [s for s in state["plan"] if s.get("state") == "failed"]
        ctx.done(":hammer_and_wrench: Integra built *<{}|{}>* with {} skill{}.{}".format(
            GENIE_URL.format(genie_id), row.get("genie_name"), ctx.result["skills_count"],
            "" if ctx.result["skills_count"] == 1 else "s",
            "\n:x: Not built: " + ", ".join("{} ({})".format(s["name"], _text(s["reason"], 80))
                                            for s in failed) if failed else ""))
        return "confirm"

    # More to do: show where we are, and hand over the next job.
    ctx.slack.update(ctx.click["channel"], ctx.click["message_ts"],
                     "Integra is building {}".format(row.get("genie_name")),
                     building_blocks(row, state))
    ctx.next_integra_job(row, state, ctx.click["message_ts"])
    return "build"


CONFIRM_LOOKS = (("new", confirm_message_sections), ("single", confirm_message_table),
                 ("old", confirm_message))


def post_confirm(ctx, text, row):
    """Post the confirm summary in the look asked for (the look input: new = a table per kind,
    single = one table, old = text lists; blank = new). When Slack refuses a look
    (invalid_blocks), the next plainer one is posted and the reason goes in warnings."""
    wanted = str(ctx.input.get("look") or "").strip().lower()
    names = [name for name, _ in CONFIRM_LOOKS]
    for name, build in CONFIRM_LOOKS[names.index(wanted) if wanted in names else 0:]:
        try:
            ctx.post(text, *build(ctx.key, row))
            return
        except StepError as exc:
            if name == "old":
                raise
            ctx.warnings.append("confirm look '{}' was refused, trying a plainer one: {}".format(name, exc))
            ctx.slack.errors = []


def handle_confirm(ctx):
    row = ctx.load(ctx.click["key"])
    final_key = "{}:{}".format(row.get("invoke_keyword"), row.get("channel"))
    taken = ctx.load(final_key, required=False)
    if taken:
        raise StepError("`{}` was taken in <#{}> while you were setting up. Type "
                        "recipeconfig to start again with another keyword."
                        .format(row.get("invoke_keyword"), row.get("channel")))
    # Skills are recipes: a stopped one fails every call. Start them first.
    started, failed = ctx.start_recipes(_load_list(row.get("skills")))
    ctx.result["recipes_started"] = started
    # ...the knowledge base, if one was made, onto the genie before it starts...
    kb = integra_state(row).get("kb") or {}
    kb_error = ctx.attach_kb(row.get("id"), kb) if kb.get("id") else ""
    ctx.result.update({"kb_id": kb.get("id", ""), "kb_name": kb.get("name", "")})
    # ...then the genie. Not starting it must not lose the setup: say so and carry on.
    genie_error = ctx.start_genie(row.get("id"))
    # ...and the app into the genie's channel, so its messages reach the responder.
    member_error = ctx.slack.join(row.get("channel"))
    persona = PERSONA_BY_KEY.get(row.get("persona")) or {}
    ctx.save(row, {"record_key": final_key, "status": STATUS_ACTIVE,
                   "system_prompt": persona.get("instructions", "")})
    ctx.result["record_key"] = final_key
    note = ""
    if failed:
        note = ("\n:warning: Couldn't start {} skill recipe{}: {}. Start {} in Workato, or "
                "the genie can't use {}.".format(len(failed), "" if len(failed) == 1 else "s",
                                                ", ".join(failed),
                                                "it" if len(failed) == 1 else "them",
                                                "it" if len(failed) == 1 else "them"))
    if kb_error:
        note += ("\n:warning: Couldn't attach the knowledge base {}: {}. Open <{}|the "
                 "genie> and add it there.".format(kb_link(kb), kb_error,
                                                  GENIE_URL.format(row.get("id"))))
    elif kb.get("id"):
        note += "\n:books: Knowledge base {} is attached.".format(kb_link(kb))
    if member_error:
        bot = ctx.slack.bot_user_id()
        note += ("\n:warning: I'm not in <#{}> yet, so I can't see questions there: {}. Invite {} "
                 "to that channel (type `/invite` there and pick it), then ask `{}`.".format(
                     row.get("channel"), member_error, "<@{}>".format(bot) if bot else "this app",
                     row.get("invoke_keyword")))
    if genie_error:
        ctx.done(":warning: *{}* is set up, but its genie isn't running: {}\nOpen <{}|the genie> "
                 "and click Start (the API client's role needs the Genies Start/Stop privilege), "
                 "then type `{}` in <#{}>.{}".format(
                     genie_link(row), genie_error, GENIE_URL.format(row.get("id")),
                     row.get("invoke_keyword"), row.get("channel"), note))
        return "active"
    ctx.done(":tada: *{}* is live. Type `{}` in <#{}> to ask it anything about {}.{}"
             .format(genie_link(row), row.get("invoke_keyword"), row.get("channel"),
                     project_links(row.get("workato_projects")), note))
    return "active"


def handle_cancel(ctx):
    row = ctx.load(ctx.click["key"])
    ctx.save(row, {"record_key": CANCELLED_PREFIX + ctx.key[len(DRAFT_PREFIX):],
                   "status": STATUS_CANCELLED})
    ctx.done(":x: Setup cancelled. Type `recipeconfig` to start again.")
    return "cancelled"


HANDLERS = {
    "start": handle_start,
    ACTION_PERSONA: handle_persona,
    ACTION_PERSONA_PICK: handle_persona_pick,
    ACTION_PROJECTS: handle_projects,
    ACTION_PROJECTS_NEXT: handle_projects_page,
    ACTION_PROJECTS_PREV: handle_projects_page,
    ACTION_DETAILS: handle_details,
    ACTION_KB_CREATE: handle_kb_create,
    ACTION_KB_SKIP: handle_kb_skip,
    ACTION_INTEGRA_RETRY: handle_integra_retry,
    ACTION_INTEGRA_NEXT: handle_integra_next,
    ACTION_INTEGRA_RESULT: handle_integra_result,
    ACTION_KB_ATTACH_RESULT: handle_kb_attach_result,
    ACTION_CONFIRM: handle_confirm,
    ACTION_CANCEL: handle_cancel,
    ACTION_NEW: handle_new,
    ACTION_MANAGE: handle_choose_manage,
    ACTION_MANAGE_DONE: handle_choose_manage,
    ACTION_RESYNC: handle_resync,
    ACTION_DESC: handle_desc,
    ACTION_DESC_SAVE: handle_desc_save,
    ACTION_DESC_APPLY: handle_desc_apply,
    ACTION_DOCS: handle_docs,
    ACTION_DOCS_SAVE: handle_docs_save,
    ACTION_SKILLS_PICK: handle_skills_pick,
    ACTION_SKILLS_NONE: handle_skills_none,
    ACTION_SKILLS_ADD: handle_skills_add,
    ACTION_SKILLS_REMOVE: handle_skills_remove,
    ACTION_SKILLS_REMOVE_APPLY: handle_skills_remove_apply,
    ACTION_KB_RESYNC: handle_kb_resync,
    ACTION_KB_SYNC_LIST: handle_kb_sync_list,
}


# --------------------------------------------------------------------------
# Context: what every handler shares
# --------------------------------------------------------------------------

class StepError(Exception):
    pass


class Context(object):
    def __init__(self, input, click, result):
        dry_run = str(input.get("dry_run") or "").lower() in ("true", "1", "yes")
        self.input = input
        self.dry_run = dry_run
        self.workato_token = input.get("workato_api_token") or ""
        self.master_genie = (input.get("master_genie_handle") or "").strip()
        self.table = Table(self.workato_token, dry_run)
        self.slack = Slack(input.get("slack_bot_token") or "", dry_run)
        self.warnings = []
        resolve_columns(self.workato_token, self.warnings)
        self.click = click
        self.key = click["key"]
        self.result = result
        self.counts = {}
        self.asset_types = []
        self.slack_ids = {}                 # owner email -> Slack ID, one lookup per person
        self._person = None                 # the person who clicked: {name, email}, looked up once

    def person(self):
        """{name, email} of whoever made this call, from Slack. Looked up once per run."""
        if self._person is None:
            self._person = self.slack.user(self.click["user_id"])
        return self._person

    def refuse_if_unauthorized(self):
        """True (after telling the person, politely, and only them) when the authorized_users
        input is set and this person's Slack email isn't in it. Blank = anyone may. If the email
        can't be read the answer is no: a limit that lets people through when it can't check
        isn't one. The reason goes in the warnings, never the address."""
        allowed = parse_emails(self.input.get("authorized_users"))
        if not str(self.input.get("authorized_users") or "").strip():
            return False
        email = str(self.person().get("email") or "").strip().lower()
        if not allowed:
            self.warnings.append("authorized_users is set but holds no email address: nobody "
                                 "is authorized")
        elif not email:
            self.warnings.append("couldn't read the email of Slack user {}: the app needs the "
                                 "users:read and users:read.email scopes".format(
                                     self.click["user_id"]))
        elif email in allowed:
            return False
        else:
            self.warnings.append("Slack user {} is not in authorized_users: refused".format(
                self.click["user_id"]))
        thread = self.click["thread_ts"] or self.click["message_ts"]
        if not self.slack.whisper(self.click["channel"], self.click["user_id"], thread,
                                  NOT_AUTHORIZED):
            self.slack.post(self.click["channel"], thread, "<@{}> {}".format(
                self.click["user_id"], NOT_AUTHORIZED), done_blocks(
                    "<@{}> {}".format(self.click["user_id"], NOT_AUTHORIZED)))
        return True

    def load(self, key, required=True):
        row, error = self.table.find(key) if key else (None, None)
        if error:
            raise StepError(error)
        if row is None and required:
            raise StepError("This setup is already finished or cancelled. "
                            "Type `recipeconfig` to start a new one.")
        return row

    def save(self, row, fields):
        """Write the WHOLE row: every column as just read, with `fields` laid on
        top, so a save never depends on how the table treats columns left out of
        an update. The in-memory row is then brought up to date, so a second save
        in the same run can't put back a value the first one changed."""
        fields = dict(fields, updated_at=now_iso())
        whole = {name: row.get(name) for name, uuid in COLUMNS.items()
                 if uuid and row and name in row}
        whole.update(fields)
        if not self.table.save(row, whole):
            raise StepError("Could not save: " + "; ".join(self.table.errors))
        if row is not None:
            row.update(fields)

    def part(self, name):
        """What one of Integra's part rows holds (its forge_state JSON); {} if there is none."""
        row = self.load(integra_part_key(self.key, name), required=False)
        try:
            content = json.loads((row or {}).get("forge_state") or "{}")
        except ValueError:
            content = {}
        return content if isinstance(content, dict) else {}

    def save_part(self, name, fields, content):
        """Write one part row (created the first time), with `content` as JSON in
        its forge_state column and `fields` beside it."""
        text = to_column(content)
        if len(text) > COLUMN_LIMIT:
            raise StepError("Integra's {} is too big to keep in the table ({:,} characters, "
                            "a column holds 10,000).".format(name, len(text)))
        key = integra_part_key(self.key, name)
        self.save(self.load(key, required=False),
                  dict(fields, record_type=PART_TYPE, record_key=key, forge_state=text,
                       setup_thread_ts=self.key[len(DRAFT_PREFIX):]))

    def attach_list(self, state):
        """The built skills with the descriptions Integra gave them (in their part rows)."""
        attach = []
        for index, entry in enumerate(state.get("plan") or []):
            if entry.get("state") == "built":
                result = self.part("s{}".format(index)).get("result") or {}
                attach.append({"handle": entry.get("handle"), "name": entry.get("name"),
                               "description": result.get("description", "")})
        return attach

    def projects(self):
        """The project list for the dropdown. An empty list is an error: Slack
        rejects a select with no options, and the step would vanish silently."""
        if not self.workato_token:
            raise StepError("workato_api_token is empty in the function recipe.")
        projects, error = list_projects(self.workato_token)
        if error:
            raise StepError("Could not load Workato projects: " + error)
        if not projects:
            raise StepError("The Workato API returned no projects. Check that the API "
                            "client's role has access to Projects.")
        return projects

    def project_owner(self, project, assets):
        """{name, mention} of a project's owner, found from the version history of its
        first recipe. Done once here, while the project's assets are read, so the genie
        gets the owner inside every question's context instead of calling a skill.
        mention is "<@U...>" when the owner is in Slack, ready to put in a message.
        {} when there is no owner to be had: that is a warning, never a stop -- a version
        author never changes, so what is stored stays right."""
        recipes = [a for a in assets if str(a.get("type") or "").lower() == "recipe"]
        if not recipes:
            return {}
        owner, error = find_owner(self.workato_token, recipes[0].get("id"))
        if error or not owner:
            self.warnings.append("owner of {}: {}".format(project.get("name"), error or (
                "no @{} author in the first {} versions of recipe {}".format(
                    OWNER_EMAIL_DOMAIN, OWNER_MAX_VERSIONS, recipes[0].get("id")))))
            return {}
        email = owner["email"]
        if email not in self.slack_ids:
            self.slack_ids[email], error = self.slack.user_id_by_email(email)
            if error:
                self.warnings.append("owner of {}: {}".format(project.get("name"), error))
        slack_id = self.slack_ids[email]
        return {key: value for key, value in (
            ("name", owner["name"]),
            ("mention", "<@{}>".format(slack_id) if slack_id else "")) if value}

    def kb_docs(self):
        """The documents on offer: from kb_doc_detail or, when this call wasn't given it,
        from the dropdown already in the clicked message -- so a step re-rendered after a
        mistake keeps its list instead of losing what the person was choosing from."""
        docs = parse_kb_docs(self.input.get("kb_doc_detail"), self.warnings)
        if docs:
            return docs
        for block in self.click["blocks"]:
            if block.get("block_id") == "gc_kb_files":
                return [{"file_name": o["text"]["text"], "file_id": o["value"]}
                        for o in (block.get("element") or {}).get("options") or []]
        return []

    def picked_docs(self, docs):
        """The documents picked in the clicked message, in the order of `docs`, each
        {file_name, file_id}. A pick missing from `docs` keeps the name Slack sent. Slack
        sends no state for a select nobody touched: what the message was rendered with
        (its initial options) is the answer then."""
        on_page = _state(self.click["state"], "gc_kb_files", "gc_kb_files_select")
        if "selected_options" in on_page:
            options = on_page.get("selected_options") or []
        else:
            options = next(((b.get("element") or {}).get("initial_options") or []
                            for b in self.click["blocks"] if b.get("block_id") == "gc_kb_files"),
                           [])
        by_id = {d["file_id"]: d for d in docs}
        picked = {}
        for option in options:
            file_id = option.get("value")
            if file_id and file_id not in picked:
                picked[file_id] = by_id.get(file_id) or {
                    "file_name": (option.get("text") or {}).get("text") or file_id,
                    "file_id": file_id}
        order = {d["file_id"]: i for i, d in enumerate(docs)}
        return sorted(picked.values(), key=lambda d: order.get(d["file_id"], len(order)))

    def create_kb(self, row, name, description):
        """{id, name} of a new knowledge base in the genie's folder (the one Integra builds
        in). StepError, with Workato's reason, when it can't be made."""
        folder_id = self.genie_folder(row)
        if self.dry_run:
            return {"id": "kb-dry-run", "name": name}
        payload = {"name": name, "description": description, "folder_id": str(folder_id),
                   "source_type": KB_SOURCE_TYPE}
        if KB_DATA_SOURCES:
            payload["data_sources"] = KB_DATA_SOURCES
        body, error = _request(KB_URL, _workato_headers(self.workato_token), payload, "POST")
        if error:
            raise StepError("Couldn't create the knowledge base: {}".format(_text(error, 400)))
        body = body if isinstance(body, dict) else {}
        # The knowledge base is the body itself, or sits under "data" (what Workato sends) or "result".
        made = next((v for v in (body, body.get("data"), body.get("result"))
                     if isinstance(v, dict) and v.get("id")), {})
        if not made:
            raise StepError("Couldn't create the knowledge base: no id in the response: {}"
                            .format(_text(json.dumps(body), 200)))
        return {"id": str(made["id"]), "name": made.get("name") or name}

    def attach_kb(self, genie_handle, kb):
        """Put the knowledge base on the genie (Agent Studio API; genie_create has no
        field for one). "" when it is on, otherwise why not."""
        handle = str(genie_handle or "").strip()
        if not handle.startswith("gin-"):
            return "this setup has no genie ID"
        if self.dry_run:
            return ""
        body, error = _request(KB_ASSIGN_URL.format(handle), _workato_headers(self.workato_token),
                               {"knowledge_base_ids": [kb["id"]]}, "POST")
        if error:
            return _text(error, 220)
        listed = [str(k.get("id")) for k in _items(body, "knowledge_bases", "data")
                  if isinstance(k, dict)]
        if listed and kb["id"] not in listed:
            return "Workato did not list it on the genie"
        return ""

    def require_manager(self, row):
        """Only the person who created the genie, or an owner of its projects, may change it."""
        if self.click["user_id"] not in manager_ids(row):
            raise StepError("Only the person who created this genie, or the owner of its "
                            "projects, can change it.")

    def show(self, text, blocks):
        """Turn the clicked message into `blocks` (a manage card or form)."""
        self.slack.update(self.click["channel"], self.click["message_ts"], text, blocks)

    def doc_key(self, row, file_id):
        return "kbdoc:{}:{}".format(row.get("setup_thread_ts"), file_id)

    def kb_doc_rows(self, row):
        """The documents registered for the genie's knowledge base: [{file_id, file_name, status,
        synced_at, error, record_key}], by name."""
        ts = row.get("setup_thread_ts")
        if not ts:
            return []
        rows, error = self.table.search({"$and": [{"record_type": {"$eq": KB_DOC_TYPE}},
                                                  {"setup_thread_ts": {"$eq": str(ts)}}]}, 100)
        if error:
            self.warnings.append(error)
        docs = []
        for found in rows:
            try:
                content = json.loads(found.get("forge_state") or "{}")
            except ValueError:
                content = {}
            if isinstance(content, dict) and content.get("file_id"):
                docs.append(dict(content, record_key=found.get("record_key")))
        return sorted(docs, key=lambda d: str(d.get("file_name") or "").lower())

    def save_docs(self, row, picked):
        """One table row per picked document, so a resync (and a person, in the table) can see
        exactly what is in the knowledge base. Re-saving keeps an existing sync time."""
        for doc in picked:
            key = self.doc_key(row, doc["file_id"])
            existing = self.load(key, required=False)
            try:
                before = json.loads((existing or {}).get("forge_state") or "{}")
            except ValueError:
                before = {}
            content = {"file_id": doc["file_id"], "file_name": doc.get("file_name") or doc["file_id"],
                       "status": before.get("status") or "pending",
                       "synced_at": before.get("synced_at") or "", "error": ""}
            self.save(existing, {"record_type": KB_DOC_TYPE, "record_key": key,
                                 "setup_thread_ts": str(row.get("setup_thread_ts") or ""),
                                 "status": content["status"], "forge_state": content})

    def mark_docs(self, row, docs, failure):
        """Record the outcome of a sync on each document's row."""
        now = now_iso()
        for doc in docs:
            found = self.load(doc.get("record_key"), required=False)
            if not found:
                continue
            content = {"file_id": doc["file_id"], "file_name": doc.get("file_name"),
                       "status": "failed" if failure else "synced",
                       "synced_at": doc.get("synced_at") or "" if failure else now,
                       "error": _text(failure, 200) if failure else ""}
            self.save(found, {"status": content["status"], "forge_state": content})

    def audit(self, row, what):
        """A row in the table for every change made from the manage card: who, what, when."""
        self.save(None, {"record_type": AUDIT_TYPE,
                         "record_key": "audit:{}:{}".format(now_iso(), len(self.table.written)),
                         "setup_thread_ts": str(row.get("setup_thread_ts") or ""),
                         "creator_id": self.click["user_id"], "status": "logged",
                         "forge_state": {"genie": row.get("record_key"), "by": self.click["user_id"],
                                         "what": what, "at": now_iso()}})

    def notify_managers(self, row, text):
        """A direct message to whoever manages the genie. Best effort."""
        for user_id in manager_ids(row):
            self.slack.dm(user_id, text)

    def update_genie_description(self, handle, text):
        """Set the genie's description in Workato. "" when it took it, otherwise why not."""
        handle = str(handle or "").strip()
        if not handle.startswith("gin-"):
            return "this setup has no genie ID"
        if self.dry_run:
            return ""
        _body, error = _request(GENIE_API_URL.format(handle), _workato_headers(self.workato_token),
                                {"description": _text(" ".join(text.split()), 500)}, "PUT")
        return _text(error, 220) if error else ""

    def start_integra(self, row, fresh):
        """Post the building card and hand the recipe Integra's first job.
        fresh=True starts over at the plan; False resumes where it stopped."""
        if not COLUMNS.get("forge_state"):
            raise StepError("The genie_console data table needs a text column named "
                            "forge_state, where Integra's progress is kept. Add it, then "
                            "click the button again.")
        previous = integra_state(row)
        state = {} if fresh else previous
        if not state.get("job") or state.get("job") == JOB_DONE:
            state = {"job": JOB_PLAN}
        for kept in ("kb", "skill_mode", "add_to", "existing"):
            if previous.get(kept):      # set before Integra starts; a fresh start keeps them
                state[kept] = previous[kept]
        if (skill_mode(state) == SKILLS_NONE and not state.get("add_to")
                and state["job"] == JOB_PLAN):
            # No skills asked for on the details step: nothing to plan, go to the genie.
            state.update({"job": JOB_GENIE, "plan": [], "next": 0})
        state["folder_id"] = state.get("folder_id") or self.genie_folder(row)
        if not state.get("add_to"):
            # Integra's edits to a running recipe can only be saved as a draft, which
            # nobody would ever publish. Stop the folder's recipes first so every
            # push lands live; Confirm starts them again. (Skills added to a live genie
            # are new recipes, so its running ones are left alone.)
            self.stop_folder_recipes(state["folder_id"])
        self.save(row, {"status": STATUS_BUILDING, "forge_state": state})
        self.post_building_card(row, state)

    def post_building_card(self, row, state):
        """A fresh building card, then the first job (or the next one) for the recipe's loop."""
        self.post("Integra is building {}".format(row.get("genie_name")), building_blocks(row, state))
        state["card_ts"] = self.result["posted_ts"]     # forge_next / forge_result find it here
        self.save(row, {"forge_state": state})
        self.next_integra_job(row, state, self.result["posted_ts"])

    def next_integra_job(self, row, state, card_ts):
        shared = []
        handle = str(self.input.get("analyst_skill_handle") or "").strip()
        if skill_mode(state) == SKILLS_NONE and not state.get("add_to"):
            pass                # "No skills" means none, the shared analyst skill included
        elif handle.startswith("skl-"):
            shared.append({"handle": handle, "name": ANALYST_SKILL_NAME})
        else:
            self.warnings.append("analyst_skill_handle is empty: the new genie can look up "
                                 "records but can't ask about recipes, jobs or tables")
        job, spec, attach, notes = state.get("job"), None, [], ""
        if job == JOB_SKILL:
            spec = self.part("s{}".format(state.get("next", 0))).get("spec")
            if not spec:
                raise StepError("Integra's plan for skill {} is no longer in the table. Type "
                                "`recipeconfig` to start again.".format(state.get("next", 0) + 1))
        elif job == JOB_GENIE:
            attach = self.attach_list(state)
            notes = self.part("notes").get("text", "")
        self.result.update({
            "call_forge": True,
            "forge_job": state.get("job"),
            "forge_message_ts": card_ts,
            "genie_folder_id": str(state.get("folder_id") or ""),
            "forge_task_instructions": integra_task(row, self.key, state, shared, spec, attach, notes),
        })

    def integra_failed(self, row, state, error):
        """Stop the loop, keep the progress, and offer Try again (which resumes)."""
        self.save(row, {"status": STATUS_BUILD_FAILED, "forge_state": state})
        self.rerender(error, build_failed_blocks(self.key, row, error, integra_progress(state)))
        self.notify_creator(row, "Integra couldn't finish building *{}*. The reason and a "
                            "*Try again* button are just above.".format(row.get("genie_name")))
        return "build"

    def genie_folder(self, row):
        """The folder Integra builds in: "Genie - <name>" inside the first chosen
        project (forge_folder_id overrides it)."""
        override = str(self.input.get("forge_folder_id") or "").strip()
        if override:
            self.result["genie_folder_id"] = override
            return override
        projects = _load_list(row.get("workato_projects"))
        if not projects or not projects[0].get("folder_id"):
            raise StepError("No project folder to build the genie in. Pick a project again.")
        name = GENIE_FOLDER_NAME.format(row.get("genie_name"))
        if self.dry_run:
            folder_id = "dry-run-folder"
        else:
            folder_id, error = ensure_folder(self.workato_token, projects[0]["folder_id"], name)
            if error:
                raise StepError("Could not create the folder '{}' in {}: {}. The API client "
                                "needs the Folders privilege.".format(
                                    name, projects[0].get("name"), error))
        self.result["genie_folder_id"] = str(folder_id)
        return folder_id

    def stop_folder_recipes(self, folder_id):
        """Stop every running recipe in the genie's own folder (never anywhere
        else). A failure is a warning, not a stop: Integra rebuilds any skill that
        still comes back as a draft."""
        stopped = []
        if self.dry_run or not str(folder_id).isdigit():
            self.result["recipes_stopped"] = stopped
            return
        headers = _workato_headers(self.workato_token)
        for page in range(1, PROJECT_PAGES + 1):
            body, error = _request(FOLDER_RECIPES_URL.format(folder_id, page), headers)
            if error:
                self.warnings.append("list folder recipes: " + error)
                break
            batch = _items(body, "items", "result", "data")
            for recipe in batch:
                if recipe.get("running") and str(recipe.get("folder_id", folder_id)) == str(folder_id):
                    _body, error = _request(RECIPE_STOP_URL.format(recipe.get("id")), headers, {}, "PUT")
                    if error:
                        self.warnings.append("stop recipe {}: {}".format(recipe.get("id"), error))
                    else:
                        stopped.append(str(recipe.get("id")))
            if len(batch) < 100:
                break
        self.result["recipes_stopped"] = stopped

    def start_genie(self, handle):
        """Start the genie (Agent Studio API). "" when it was started, otherwise why
        not. A genie is created stopped and can't answer until it is started; the
        API client's role needs the Genies "Start/Stop" privilege on its project."""
        handle = str(handle or "").strip()
        if not handle.startswith("gin-"):
            return "this setup has no genie ID"
        if self.dry_run:
            return ""
        headers = _workato_headers(self.workato_token)
        body, error = _request(GENIE_START_URL.format(handle), headers, None, "POST")
        if error and "already started" in error.lower():
            # Workato answers 422 "<name> is already started" when the genie is running: that
            # is the state we want, not a failure (Integra, or Workato, may have started it).
            self.warnings.append("genie {} was already started: nothing to do".format(handle))
            return ""
        if error:
            return _text(error, 220)
        if isinstance(body, dict) and body.get("success") is False:
            return "Workato did not start it"
        # For the job log only: what Workato now says the genie's state is.
        after, _error = _request(GENIE_API_URL.format(handle), headers)
        self.warnings.append("started genie {}; Workato now reports its state as {!r}".format(
            handle, (after or {}).get("state") if isinstance(after, dict) else None))
        return ""

    def detach_skills(self, genie_handle, skills):
        """(removed, [(skill, reason)]). Workato's remove_skills takes skill IDs and answers with
        the skills still on the genie, so each is tried by its handle, then by its recipe ID,
        and counts as removed when its name is no longer in that answer."""
        handle = str(genie_handle or "").strip()
        removed, failed = [], []
        headers = _workato_headers(self.workato_token)
        for skill in skills:
            if self.dry_run:
                removed.append(skill)
                continue
            why = "this setup has no genie ID" if not handle.startswith("gin-") else ""
            for candidate in (skill.get("handle"), skill.get("recipe_id")) if not why else ():
                if not candidate:
                    continue
                body, error = _request(GENIE_REMOVE_SKILLS_URL.format(handle), headers,
                                       {"skill_ids": [str(candidate)]}, "POST")
                if error:
                    why = _text(error, 120)
                    continue
                left = [str(k.get("name") or "") for k in _items(body, "skills")
                        if isinstance(k, dict)]
                if skill.get("name") not in left:
                    removed.append(skill)
                    break
                why = "still on the genie after using {}".format(candidate)
            else:
                failed.append((skill, why or "no skill ID"))
        return removed, failed

    def stop_recipes(self, skills):
        """Stop the recipes of skills taken off a genie. Best effort."""
        for skill in skills:
            recipe_id = str(skill.get("recipe_id") or "").strip()
            if recipe_id.isdigit() and not self.dry_run:
                _body, error = _request(RECIPE_STOP_URL.format(recipe_id),
                                        _workato_headers(self.workato_token), {}, "PUT")
                if error:
                    self.warnings.append("stop recipe {}: {}".format(recipe_id, error))

    def start_recipes(self, skills):
        """(started recipe ids, failed recipe names). Starting a running recipe
        is harmless, so every skill is started on every Confirm."""
        started, failed = [], []
        drafts = {id(s) for s in draft_skills(skills)}
        for skill in skills:
            recipe_id = str(skill.get("recipe_id") or "").strip()
            if id(skill) in drafts:
                # Starting it would start the last saved version, not Integra's work.
                failed.append("{} (draft: click Save in the recipe first)".format(
                    skill.get("name") or recipe_id))
                continue
            if not recipe_id.isdigit():
                failed.append(skill.get("name") or skill.get("handle") or "?")
                continue
            if self.dry_run:
                started.append(recipe_id)
                continue
            _body, error = _request(RECIPE_START_URL.format(recipe_id),
                                    _workato_headers(self.workato_token), {}, "PUT")
            if error:
                self.warnings.append("start recipe {}: {}".format(recipe_id, error))
                failed.append(skill.get("name") or recipe_id)
            else:
                started.append(recipe_id)
        return started, failed

    def post(self, text, blocks, attachments=None):
        ts = self.slack.post(self.click["channel"],
                             self.click["thread_ts"] or self.click["message_ts"],
                             text, blocks, attachments)
        if not ts:
            raise StepError("Could not post the next step: " +
                            ("; ".join(self.slack.errors) or "no ts returned"))
        self.result["posted_ts"] = ts

    def notify_creator(self, row, text):
        """A new message mentioning whoever started the setup. Best effort: the
        card above already shows the outcome, so a failed post is only a warning."""
        text = _mention(row) + text
        self.slack.post(self.click["channel"],
                        self.click["thread_ts"] or self.click["message_ts"],
                        text, done_blocks(text))

    def done(self, text):
        """The clicked message becomes a one-line record of the answer; any
        attachment on it (the confirm summary) is removed with it."""
        self.result["updated_message"] = self.slack.update(
            self.click["channel"], self.click["message_ts"], text, done_blocks(text), [])

    def rerender(self, error, blocks):
        self.result["field_error"] = error
        self.slack.update(self.click["channel"], self.click["message_ts"], error, blocks)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    parse_warnings = []
    click = read_click(input, parse_warnings)
    action = click["action_id"]
    result = {"ok": False, "error": "", "action": action, "step": "",
              "total_steps": len(STEPS), "remaining": len(STEPS), "record_key": click["key"],
              "field_error": "", "posted_ts": "", "updated_message": False,
              "recipe_count": 0, "lookup_table_count": 0, "data_table_count": 0,
              "asset_types": [], "rows_written": 0, "warnings": [], "blocks_json": "",
              # Integra hand-off: when call_forge is true the function recipe runs
              # Assign task to genie (Integra) with forge_task_instructions, then
              # calls this step again with action = forge_result.
              "call_forge": False, "forge_task_instructions": "", "forge_message_ts": "",
              "forge_job": "", "genie_handle": "", "genie_folder_id": "", "skills_count": 0,
              "recipes_started": [], "recipes_stopped": [],
              # The knowledge base made on the kb step, and attached on Confirm.
              "kb_id": "", "kb_name": "",
              # Document hand-off: when call_kb_attach is true this pass is for attaching
              # the documents in selected_kb_file to kb_id. The function recipe does that,
              # then calls this step again with action = kb_attach_result.
              "call_kb_attach": False, "selected_kb_file": [],
              # The daily sync: the genies to visit (one kb_resync call each).
              "sync_keys": []}

    handler = HANDLERS.get(action)
    if handler is None:
        # Picking a value in a select fires a click too; only Submit matters.
        result.update({"ok": True, "step": "ignored"})
        return result
    if action != "start" and action not in KEY_FREE_ACTIONS \
            and action != ACTION_KB_ATTACH_RESULT and not click["key"].startswith(DRAFT_PREFIX):
        result["error"] = "button value is not a draft key: {!r}".format(click["key"])
        return result

    ctx = Context(input, click, result)
    if action in ("start", ACTION_NEW) and ctx.refuse_if_unauthorized():
        # Only the entrances to making a genie are guarded; nothing is saved or posted to the
        # thread for someone who isn't allowed. (Managing a genie has its own check.)
        result.update({"ok": True, "step": "refused", "warnings": parse_warnings + ctx.warnings
                       + ctx.slack.errors, "channel": click["channel"],
                       "thread_ts": click["thread_ts"] or click["message_ts"]})
        return result
    loading = LOADING_TEXT.get(action)
    if loading and click["blocks"] and click["message_ts"]:
        # First thing, before any slow call: the person sees their click land.
        ctx.slack.update(click["channel"], click["message_ts"], loading,
                         loading_blocks(click["blocks"], loading))
    try:
        step = handler(ctx)
        result["ok"] = True
    except StepError as exc:
        step = "error"
        result["error"] = str(exc)
        if loading and click["blocks"] and click["message_ts"]:
            # Put the step back as it was, buttons and all, so it can be retried.
            ctx.slack.update(click["channel"], click["message_ts"],
                             "Try again", click["blocks"])
        ctx.slack.post(click["channel"], click["thread_ts"] or click["message_ts"],
                       str(exc), done_blocks(":warning: " + str(exc)))

    done = len(STEPS) if step in ("active", "cancelled") else (
        STEPS.index(step) if step in STEPS else 0)
    result.update({
        "step": step,
        "remaining": len(STEPS) - done,
        "record_key": result["record_key"] if step == "active" else ctx.key or click["key"],
        "recipe_count": ctx.counts.get("recipes", 0),
        "lookup_table_count": ctx.counts.get("lookup_tables", 0),
        "data_table_count": ctx.counts.get("data_tables", 0),
        "asset_types": ctx.asset_types,
        "rows_written": len(ctx.table.written),
        "warnings": parse_warnings + ctx.warnings + ctx.table.errors + ctx.slack.errors,
        "blocks_json": json.dumps(ctx.slack.last_blocks),
        # Where the setup is happening, so the forge_result call can be mapped
        # entirely from this step's outputs.
        "channel": click["channel"],
        "thread_ts": click["thread_ts"] or click["message_ts"],
    })
    return result


if __name__ == "__main__":
    # Dry run of the first step against real APIs: nothing is posted or written.
    print(json.dumps(main({
        "action": sys.argv[1] if len(sys.argv) > 1 else "start",
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", ""),
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "channel": os.environ.get("SLACK_CHANNEL", "C0A3PGRT3EX"),
        "user_id": os.environ.get("SLACK_USER", "U038ZCDAY6P"),
        "message_ts": "1792082384.030959",
        "dry_run": "true",
    }), indent=2))
