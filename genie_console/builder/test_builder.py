"""
Checks for builder.py. Run:  python3 test_builder.py

Covers the Forge -> Integra rename: what people and the genie read says
"Integra", while the names shared with the function recipe, the Integra genie's
job description and rows already saved keep their old spelling (renaming those
means changing the recipe / genie / table at the same time).
"""

import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("builder", os.path.join(HERE, "builder.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else "  -> " + str(detail)))
    if not ok:
        failures.append(name)


STATE = {"job": builder.JOB_SKILL, "next": 1,
         "plan": [{"name": "Look up orders", "state": "built"},
                  {"name": "Refund order", "state": "failed", "reason": "no access"},
                  {"name": "List invoices", "state": "pending"}]}
ROW = {"genie_name": "Support genie", "creator_id": "U123", "record_key": "draft:1.2",
       "forge_state": json.dumps(STATE), "skills": "[]", "persona": "support"}

# 1. Everything a person reads says Integra.
rendered = {
    "progress": builder.integra_progress(STATE),
    "building": json.dumps(builder.building_blocks(ROW, STATE)),
    "failed": json.dumps(builder.build_failed_blocks("draft:1.2", ROW, "boom", "progress")),
    "confirm": json.dumps(builder.confirm_message("draft:1.2", ROW)),
    "kb form": json.dumps(builder.kb_blocks("draft:1.2", {})),
    "details form": json.dumps(builder.details_blocks("draft:1.2", {})),
}
for label, text in rendered.items():
    check("no 'Forge' in " + label, "Forge" not in text, re.findall(r".{20}Forge.{20}", text)[:2])
check("building card names Integra", "Integra is building Support genie" in rendered["building"])
check("failed card names Integra", "Integra couldn" in rendered["failed"])
check("confirm summary names Integra", "Skills built by Integra" in rendered["confirm"])

# 2. The task sent to the Integra genie keeps the tags its job description reads.
task = builder.integra_task(ROW, "draft:1.2", STATE)
check("task keeps <forge_request> tag", "<forge_request>" in task and "</forge_request>" in task)
check("task keeps <forge_job> tag", "<forge_job>" in task and "</forge_job>" in task)

# 3. Names shared with the recipe and saved rows are unchanged.
check("button action_id unchanged", builder.ACTION_INTEGRA_RETRY == "gc_console_forge_retry")
check("loop action ids unchanged",
      (builder.ACTION_INTEGRA_NEXT, builder.ACTION_INTEGRA_RESULT) == ("forge_next", "forge_result"))
check("part rows unchanged", builder.PART_TYPE == "forge_part"
      and builder.integra_part_key("draft:1.2", "s0") == "forge:1.2:s0")
check("forge_state column unchanged", "forge_state" in builder.COLUMNS)
check("handlers registered", all(a in builder.HANDLERS for a in (
    builder.ACTION_INTEGRA_RETRY, builder.ACTION_INTEGRA_NEXT, builder.ACTION_INTEGRA_RESULT))
    if hasattr(builder, "HANDLERS") else True)

# ---------------------------------------------------------------------------
# Persona step: wider dropdown, or a carousel
# ---------------------------------------------------------------------------
listing = builder.persona_blocks("draft:1.2")
select = next(b for b in listing if b.get("block_id") == "gc_persona")
check("persona dropdown is an input block (full width)", select["type"] == "input"
      and select["element"]["action_id"] == "gc_persona_select")
check("persona dropdown still has its Submit button", any(
    b["type"] == "actions" and b["elements"][0]["action_id"] == builder.ACTION_PERSONA
    for b in listing))
cards = builder.persona_blocks("draft:1.2", picker="carousel")
carousel = next(b for b in cards if b["type"] == "carousel")
check("carousel has a card per persona", len(carousel["elements"]) == len(builder.PERSONAS))
buttons = [c["actions"][0] for c in carousel["elements"]]
check("card buttons carry key|persona and a gc_console id", all(
    b["value"] == "draft:1.2|" + p["key"] and "gc_console" in b["action_id"]
    for b, p in zip(buttons, builder.PERSONAS)))
check("card action ids are unique", len({b["action_id"] for b in buttons}) == len(buttons))
check("card click is read back", builder.read_click({"payload_json": json.dumps({"actions": [
    {"action_id": buttons[0]["action_id"], "value": buttons[0]["value"]}]})}, [])["arg"]
      == builder.PERSONAS[0]["key"])
check("old click parsing unchanged", builder.read_click({"payload_json": json.dumps({"actions": [
    {"action_id": "x", "value": "draft:1.2|3"}]})}, [])["page"] == 3)


class Stub(object):
    """Just enough of Context to run a handler without Slack or Workato."""
    def __init__(self, row, click):
        self.row, self.click, self.key = row, click, click["key"]
        self.saved, self.said, self.cards, self.warnings = {}, [], [], []
    def load(self, key, required=True): return self.row
    def save(self, row, fields): self.saved.update(fields)
    def done(self, text): self.said.append(text)
    def post_building_card(self, row, state): self.cards.append(dict(state))
    def rerender(self, error, blocks): self.said.append(error)


# ---------------------------------------------------------------------------
# No skills
# ---------------------------------------------------------------------------
check("details step offers No skills", builder.SKILLS_NONE in [m[0] for m in builder.SKILL_MODES])
check("skill_mode reads none", builder.skill_mode({"skill_mode": "none"}) == builder.SKILLS_NONE
      and builder.skill_mode({}) == builder.SKILLS_ALL
      and builder.skill_mode({"skill_mode": "pick"}) == builder.SKILLS_PICK)
entries = [("0", "A", ""), ("1", "B", "")]
ids = lambda blocks: [e["action_id"] for b in blocks if b["type"] == "actions" for e in b["elements"]]
check("pick step has a No skills button for a new genie", builder.ACTION_SKILLS_NONE in ids(
    builder.skills_pick_blocks("draft:1.2", entries, "h", builder.ACTION_SKILLS_PICK, "Go",
                               cancel=True, skip=True)))
check("pick step without skip is as before", builder.ACTION_SKILLS_NONE not in ids(
    builder.skills_pick_blocks("draft:1.2", entries, "h", builder.ACTION_SKILLS_PICK, "Go",
                               cancel=True)))
pending = dict(STATE, choosing=True, plan=[{"name": "A"}, {"name": "B"}], next=0)
stub = Stub(dict(ROW, forge_state=json.dumps(pending)), {"key": "draft:1.2"})
builder.handle_skills_none(stub)
after = stub.cards[0]
check("No skills leaves every planned skill out and goes to create_genie",
      after["job"] == builder.JOB_GENIE and all(e["state"] == "skipped" for e in after["plan"])
      and not after.get("choosing") and builder.built_skills(after) == [])
check("progress says no skills", "No skills to build" in builder.integra_progress(after))
stub = Stub(dict(ROW, forge_state=json.dumps(dict(pending, add_to="x:C1"))), {"key": "draft:1.2"})
builder.handle_skills_none(stub)
check("No skills is ignored on an add-skills run", not stub.cards and stub.warnings)

# ---------------------------------------------------------------------------
# Projects step: the dropdown only searches its own page, and says so
# ---------------------------------------------------------------------------
def projects_input(count, page=0):
    projects = [{"id": i, "name": "Project %d" % i, "folder_id": 1000 + i} for i in range(count)]
    blocks = builder.projects_blocks("draft:1.2", projects, page)
    return next(b for b in blocks if b.get("block_id") == "gc_projects"), blocks


one, _ = projects_input(40)
check("one page: label and no hint, as before", one["label"]["text"] == "Projects" and "hint" not in one)
first, blocks = projects_input(250, 0)
check("several pages: label says this page only", first["label"]["text"] == "Projects (this page only)")
check("first page hint points to the next page", "My project isn't listed" in first["hint"]["text"])
last, _ = projects_input(250, 2)
check("last page hint points back", "Previous projects" in last["hint"]["text"])
check("projects input keeps its ids", first["element"]["action_id"] == "gc_projects_select"
      and first["type"] == "input" and first["optional"] is True)

# ---------------------------------------------------------------------------
# Confirm: a genie that is already running is not a failure
# ---------------------------------------------------------------------------
_real_request = builder._request


class Starting(object):
    dry_run, workato_token = False, "t"
    def __init__(self): self.warnings = []


def start_with(reply):
    builder._request = lambda url, headers, payload=None, method="GET": reply(method)
    try:
        return builder.Context.start_genie(Starting(), "gin-1")
    finally:
        builder._request = _real_request


already = 'HTTP 422 POST www.workato.com: {"errors":[{"code":422,"title":"Start genie failed","detail":"snap is already started"}]}'
check("already-started genie counts as started", start_with(lambda m: (None, already)) == "")
check("another 422 is still reported", "HTTP 403" in start_with(lambda m: (None, "HTTP 403 POST www.workato.com: forbidden")))
check("a normal start still works", start_with(
    lambda m: ({"success": True}, None) if m == "POST" else ({"state": "running"}, None)) == "")

class Starter(object):
    """Just enough of Context for start_integra / next_integra_job."""
    input = {"analyst_skill_handle": "skl-1"}
    key = "draft:1.2"
    def __init__(self): self.warnings, self.result = [], {}
    def genie_folder(self, row): return 7
    def stop_folder_recipes(self, folder): pass
    def save(self, row, fields): pass
    def post_building_card(self, row, state): self.state = state
    def part(self, name): return {}
    def attach_list(self, state): return []


for mode, job in (("none", builder.JOB_GENIE), ("all", builder.JOB_PLAN)):
    starter = Starter()
    builder.Context.start_integra(starter, {"forge_state": json.dumps({"skill_mode": mode})}, True)
    check("first-ask mode '{}' starts at {}".format(mode, job), starter.state["job"] == job)
for mode, shared in (("none", "shared_skills: []"), ("all", "skl-1")):
    starter = Starter()
    builder.Context.next_integra_job(starter, {"genie_name": "G", "persona": "support"},
                                     {"job": builder.JOB_GENIE, "plan": [], "skill_mode": mode,
                                      "folder_id": 7}, "1.1")
    check("mode '{}' hands the genie the right shared skills".format(mode),
          shared in starter.result["forge_task_instructions"])

# ---------------------------------------------------------------------------
# Confirm summary as a table; the old summary is untouched
# ---------------------------------------------------------------------------
golden = json.load(open(os.path.join(HERE, "testdata", "golden_confirm_old.json")))
fixture = golden["row"]
expected = json.loads(json.dumps(golden["blocks_attachments"]).replace("Forge", "Integra"))
check("old confirm summary is unchanged", json.loads(json.dumps(builder.confirm_message(
    "draft:1.2", fixture))) == expected)
blocks, attachments = builder.confirm_message_table("draft:1.2", fixture)
table = [b for b in blocks if b["type"] == "table"]
check("exactly one table block, no attachment", len(table) == 1 and attachments is None)
cell_text = lambda cell: cell["elements"][0]["elements"][0]["text"]
grid = [[cell_text(c) for c in r] for r in table[0]["rows"]]
check("table has a header and equal-width rows", grid[0] == ["Type", "Name", "ID / note"]
      and len({len(r) for r in grid}) == 1)
check("table lists skill, not built, knowledge base, project and recipes",
      ["Skill", "Look up orders", "11"] in grid and ["Not built", "Refund order", "no access"] in grid
      and ["Knowledge base", "Docs KB", "2 documents"] in grid and ["Project", "Orders", "1"] in grid)
check("table caps recipes at 10 and says how many more",
      sum(1 for r in grid if r[0] == "Recipe") == builder.SUMMARY_LIST_MAX + 1
      and ["Recipe", "… and 3 more", " "] in grid)
check("table message keeps Confirm and Cancel", {builder.ACTION_CONFIRM, builder.ACTION_CANCEL}
      <= set(ids(blocks)))
check("table stays under Slack's 100 rows", len(grid) <= 100)
check("table message has no 'Forge'", "Forge" not in json.dumps(blocks))

# ---------------------------------------------------------------------------
# Confirm summary: a data table per kind of thing, every item shown
# ---------------------------------------------------------------------------
many = dict(fixture, recipes=json.dumps([{"id": 1000 + i, "name": "Recipe %d" % i} for i in range(250)]))
sec_blocks, sec_att = builder.confirm_message_sections("draft:1.2", many)
tables = [b for b in sec_blocks if b["type"] == "data_table"]
captions = [t["caption"] for t in tables]
check("a table per kind, captioned with its count", captions == [
    "Skills (1)", "Not built (1)", "Knowledge base (1)", "Projects (1)", "Recipes (250)",
    "Lookup tables (1)"], captions)
recipes_table = next(t for t in tables if t["caption"].startswith("Recipes"))
check("a long list fills the table up to the row cap, then says how many more",
      len(recipes_table["rows"]) == builder.SUMMARY_TABLE_ROWS
      and recipes_table["rows"][-1][0]["text"] == "… and 152 more", len(recipes_table["rows"]))
few = next(t for t in builder.summary_tables(fixture) if t["caption"].startswith("Recipes"))
check("a short list shows every recipe", len(few["rows"]) == 1 + 13 and few["rows"][1][0]["text"] == "Recipe 0")
check("every cell is a non-empty raw_text", all(c["type"] == "raw_text" and c["text"].strip()
      for t in tables for r in t["rows"] for c in r))
check("sections message keeps text, Confirm, Cancel and no table block", sec_att is None
      and not any(b["type"] == "table" for b in sec_blocks)
      and {builder.ACTION_CONFIRM, builder.ACTION_CANCEL} <= set(ids(sec_blocks)))
check("sections message stays under 50 blocks", len(sec_blocks) <= 50)


class Poster(object):
    """Context.post that Slack refuses for chosen looks."""
    def __init__(self, refuse): self.refuse, self.looks, self.warnings = refuse, [], []
    key, input = "draft:1.2", {}
    class slack: errors = []
    def post(self, text, blocks, attachments=None):
        kind = ("sections" if any(b["type"] == "data_table" for b in blocks) else
                "single" if any(b["type"] == "table" for b in blocks) else "old")
        self.looks.append(kind)
        if kind in self.refuse:
            raise builder.StepError("invalid_blocks")


for refuse, want in (((), ["sections"]), (("sections",), ["sections", "single"]),
                     (("sections", "single"), ["sections", "single", "old"])):
    poster = Poster(refuse)
    builder.post_confirm(poster, "t", fixture)
    check("refused {} -> tried {}".format(list(refuse), want), poster.looks == want, poster.looks)
poster = Poster(())
poster.input = {"look": "old"}
builder.post_confirm(poster, "t", fixture)
check("look=old posts only the old summary", poster.looks == ["old"])
poster = Poster(("single",))
poster.input = {"look": "single"}
builder.post_confirm(poster, "t", fixture)
check("look=single falls back to old, never to sections", poster.looks == ["single", "old"])

# ---------------------------------------------------------------------------
# authorized_users: only the listed people may start a genie
# ---------------------------------------------------------------------------
check("emails split on commas, semicolons, spaces; lowercased; no repeats",
      builder.parse_emails(" A@x.com, b@X.com;c@x.com\nA@x.com <mailto:d@x.com> junk") ==
      ["a@x.com", "b@x.com", "c@x.com", "d@x.com"], builder.parse_emails(" A@x.com, b@X.com;c@x.com\nA@x.com <mailto:d@x.com> junk"))


class Gate(object):
    """Just enough of Context for refuse_if_unauthorized."""
    def __init__(self, allowed, email, user_id="U9"):
        self.input = {"authorized_users": allowed}
        self.click = {"user_id": user_id, "channel": "C1", "thread_ts": "1.2", "message_ts": "1.2"}
        self.warnings, self.whispered, self.posted, self._person = [], [], [], None
        gate = self
        class Slack(object):
            errors = []
            def user(self, uid): return {"name": "N", "email": email}
            def whisper(self, channel, uid, thread, text): gate.whispered.append((uid, text)); return True
            def post(self, *args): gate.posted.append(args); return "1"
        self.slack = Slack()
    person = builder.Context.person
    refuse_if_unauthorized = builder.Context.refuse_if_unauthorized


def gate(allowed, email, **kw):
    g = Gate(allowed, email, **kw)
    return g.refuse_if_unauthorized(), g


refused, g = gate("boss@x.com, Dev@X.com", "dev@x.com")
check("a listed email (any case) is let through, silently", refused is False and not g.whispered)
refused, g = gate("boss@x.com", "other@x.com")
check("someone else is refused, politely, and only they see it",
      refused is True and g.whispered and g.whispered[0][0] == "U9"
      and g.whispered[0][1] == builder.NOT_AUTHORIZED and not g.posted)
check("the refusal never shows the list or the person's email",
      "boss@x.com" not in g.whispered[0][1] and "other@x.com" not in g.whispered[0][1]
      and not any("@x.com" in w for w in g.warnings))
check("blank authorized_users means no limit", gate("", "other@x.com")[0] is False
      and gate("  ", "")[0] is False)
refused, g = gate("boss@x.com", "")
check("an unreadable email is refused, with the reason in warnings",
      refused is True and any("users:read.email" in w for w in g.warnings))
refused, g = gate("not an email", "other@x.com")
check("a list with no address lets nobody in", refused is True and any("no email" in w for w in g.warnings))


class NoWhisper(Gate):
    def __init__(self, *a):
        super().__init__(*a)
        self.slack.whisper = lambda *args: False
refused, g = (lambda gg: (gg.refuse_if_unauthorized(), gg))(NoWhisper("boss@x.com", "other@x.com"))
check("if Slack won't whisper, it is posted in the thread with a mention",
      refused is True and g.posted and "<@U9>" in g.posted[0][2])

# main(): a refused start saves and posts nothing else, and a listed person gets through the gate
_Context_init, _Context_refuse = builder.Context.__init__, builder.Context.refuse_if_unauthorized
builder.Context.refuse_if_unauthorized = lambda self: True
builder.Context.__init__ = lambda self, input, click, result: setattr(self, "warnings", []) or setattr(self, "slack", type("S", (), {"errors": []})())
out = builder.main({"action": "start", "authorized_users": "a@x.com", "channel": "C1", "user_id": "U9", "message_ts": "1.2"})
check("main answers a refused start with step 'refused' and ok", out["step"] == "refused" and out["ok"] is True)
out = builder.main({"payload_json": json.dumps({"actions": [{"action_id": builder.ACTION_NEW, "value": "draft:1.2"}],
                                                "user": {"id": "U9"}, "channel": {"id": "C1"}}),
                    "authorized_users": "a@x.com"})
check("the chooser's Create a new genie is guarded too", out["step"] == "refused")
builder.Context.__init__, builder.Context.refuse_if_unauthorized = _Context_init, _Context_refuse

# ---------------------------------------------------------------------------
# "This channel already has a genie" screen
# ---------------------------------------------------------------------------
gold = json.load(open(os.path.join(HERE, "testdata", "golden_chooser_old.json")))
check("old chooser is unchanged", builder.chooser_blocks("draft:1.2", gold["genies"]) == gold["blocks"])
new_blocks = builder.chooser_blocks_new("draft:1.2", gold["genies"])
heading = new_blocks[0]["text"]["text"]
check("heading is one bold line, no stray asterisks",
      heading.startswith("*This channel already has 2 genies*") and heading.count("*") == 2, heading)
info = [b["text"]["text"] for b in new_blocks if b["type"] == "section"][1:]
check("each genie shows its linked name, keyword and facts", len(info) == 2
      and "<https://app.workato.com/genies/gin-1/overview|snap>" in info[0] and "`SNAP`" in info[0]
      and "Support  ·  2 skills  ·  knowledge base: Docs KB  ·  made by Dev K on 2026-11-17" in info[0], info[0])
check("a bare genie still reads cleanly", info[1].endswith("Analyst  ·  no skills"), info[1])
manage = [e for b in new_blocks if b["type"] == "actions" for e in b["elements"] if e["action_id"] == builder.ACTION_MANAGE]
check("one Manage button per genie, in its own block, carrying the row key",
      [m["value"] for m in manage] == ["SNAP:C1", "OPS:C1"]
      and all(sum(1 for e in b["elements"] if e["action_id"] == builder.ACTION_MANAGE) <= 1
              for b in new_blocks if b["type"] == "actions"))
check("Create a new genie is last and carries the draft key", new_blocks[-1]["elements"][0]["action_id"]
      == builder.ACTION_NEW and new_blocks[-1]["elements"][0]["value"] == "draft:1.2")
one = builder.chooser_blocks_new("draft:1.2", gold["genies"][:1])[0]["text"]["text"]
check("singular heading", one.startswith("*This channel already has a genie*"), one)
twenty = builder.chooser_blocks_new("draft:1.2", [dict(gold["genies"][0], record_key="K%d" % i) for i in range(20)])
check("many genies: capped, says how many are hidden, under 50 blocks", len(twenty) < 50
      and any("and 12 more" in json.dumps(b) for b in twenty))


class Chooser(object):
    key, input = "draft:1.2", {}
    class slack: errors = []
    def __init__(self, refuse_new=False): self.refuse_new, self.posted, self.warnings = refuse_new, [], []
    def post(self, text, blocks):
        new = any(b["type"] == "divider" for b in blocks)
        self.posted.append("new" if new else "old")
        if new and self.refuse_new:
            raise builder.StepError("invalid_blocks")


c = Chooser(); builder.post_chooser(c, "draft:1.2", gold["genies"])
check("chooser: new look by default", c.posted == ["new"])
c = Chooser(); c.input = {"look": "old"}; builder.post_chooser(c, "draft:1.2", gold["genies"])
check("chooser: look=old posts the first version", c.posted == ["old"])
c = Chooser(refuse_new=True); builder.post_chooser(c, "draft:1.2", gold["genies"])
check("chooser: refused new look falls back to old, with a warning", c.posted == ["new", "old"] and c.warnings)
check("chooser info survives the loading view (sections are kept, buttons dropped)",
      sum(1 for b in builder.loading_blocks(new_blocks, "x") if b["type"] == "section") == 3
      and not any(b["type"] == "actions" for b in builder.loading_blocks(new_blocks, "x")))

# ---------------------------------------------------------------------------
# No link preview cards
# ---------------------------------------------------------------------------
sent = []
_keep_request = builder._request
builder._request = lambda url, headers, payload=None, method="GET": (sent.append((url, payload)) or ({"ok": True, "ts": "1.1"}, None))
slack = builder.Slack("xoxb-test")
slack.post("C1", "1.2", "t", [{"type": "section", "text": {"type": "mrkdwn", "text": "<https://x|y>"}}])
slack.update("C1", "1.1", "t", [{"type": "section", "text": {"type": "mrkdwn", "text": "<https://x|y>"}}], [])
slack.dm("U1", "hi")
builder._request = _keep_request
check("every post and edit turns link previews off", len(sent) == 3 and all(
    p["unfurl_links"] is False and p["unfurl_media"] is False for _, p in sent), sent)
check("the message content is untouched", sent[0][1]["channel"] == "C1" and sent[0][1]["thread_ts"] == "1.2"
      and sent[1][1]["ts"] == "1.1" and sent[1][1]["attachments"] == [])

print("\n{} failed".format(len(failures)) if failures else "\nall passed")
sys.exit(1 if failures else 0)
