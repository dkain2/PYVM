"""
Tests for friday_summary.py. Run them before and after any change, so a change that breaks the post is caught here and
not in the channel:

    python3 test_friday_summary.py                # all of them
    python3 test_friday_summary.py -v             # with the name of each
    python3 test_friday_summary.py --write-preview # write testdata/preview_{new,old}_look.json and
                                                  # preview_classic_{new,old}_look.json: the fixture channel's
                                                  # posts, to paste into Slack's Block Kit Builder
    python3 test_friday_summary.py --regen-golden # rewrite testdata/golden_plain.json (only after a change to the OLD
                                                  # post that you meant to make -- see TestPlainUnchanged)
    python3 -m unittest test_friday_summary.TestRichBlocks    # one group

Nothing here touches the network, Slack or Workato, and it needs nothing beyond the standard library (if `requests` is
not installed a stand-in is used, because the step imports it; the tests never send anything).

THE GROUPS
    TestPlainUnchanged   the old post (look = old: header, sections, fields, context -- no newer block) is pinned,
                         block for block, to what the step posted before the new look existed. It is also what is
                         posted when Slack refuses the new blocks, so it must never drift.
    TestLook             look / new_features: which features are on, and that nothing unknown switches one on
    TestRichBlocks       the new post against Slack's rules: block ids, limits, one table, cards, layout, container,
                         charts -- and each feature switched off on its own
    TestRichContent      what the new blocks SAY is what the old ones say (same shout-outs, same names, same figures)
    TestEdgeWeeks        a quiet week, a first week, one activity, a crowd of badges, long names, mentions
    TestClassicNewLook   the classic all-time summary in the new look: Slack's rules, the same words as the old one,
                         each feature alone, a channel with little in it
    TestRefusedFeatures  which feature an invalid_blocks error is about (Slack's json-pointers, or the peel order)
    TestPosting          main() against a stand-in for Slack that enforces the rules it has taught this step and can
                         refuse block types: a new-look post, a refusal costing one feature (or several, or all
                         down to the old post), the error Slack gives back, the reaction, the snapshot

THE FIXTURE
    make_rows() is a small channel, deterministic: fourteen people over three months, with a newcomer, a comeback, a
    weekend logger, a personal best, someone who tried something new, an opted-out person, and a perfect-week regular.
    The same rows are used by every group.
"""

import atexit
import copy
import json
import os
import random
import re
import shutil
import sys
import tempfile
import types
import unittest
from datetime import date, timedelta
from unittest import mock

try:
    import requests  # noqa: F401
except ImportError:                                  # the step imports it; the tests never use the network
    _stub = types.ModuleType("requests")

    class _RequestException(Exception):
        pass

    def _no_network(*args, **kwargs):
        raise AssertionError("a test reached for the network")

    _stub.post = _no_network
    _stub.request = _no_network
    _stub.RequestException = _RequestException
    sys.modules["requests"] = _stub

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import friday_summary as fs                                              # noqa: E402

GOLDEN = os.path.join(HERE, "testdata", "golden_plain.json")
TODAY = date(2026, 11, 13)               # a Friday
SEED = 20261113


# --------------------------------------------------------------------------
# The fixture: a small channel
# --------------------------------------------------------------------------

def _days(start, end, rng, weekday_p, weekend_p, always_weekdays=False):
    out, day = [], start
    while day <= end:
        p = weekday_p if day.weekday() < 5 else weekend_p
        if (always_weekdays and day.weekday() < 5) or rng.random() < p:
            out.append(day)
        day += timedelta(days=1)
    return out


# id, name, first day, weekday p, weekend p, {activity: share of that person's days it is logged}
PEOPLE = [
    ("U01AAA001", "Asha Rao", date(2026, 8, 3), 1.0, 0.2, {"step": 1.0, "pushup": 0.7, "plank": 0.6, "yoga": 0.3}),
    ("U01BBB002", "Ben Carter", date(2026, 8, 3), 0.8, 0.1, {"step": 1.0, "pushup": 0.8, "plank": 0.5}),
    ("U01CCC003", "Chitra Iyer", date(2026, 8, 10), 0.7, 0.2, {"step": 0.9, "plank": 0.6, "meditate": 0.5}),
    ("U01DDD004", "Dev Patel", date(2026, 8, 17), 0.75, 0.1, {"step": 1.0, "pushup": 0.5, "read": 0.4}),
    ("U01EEE005", "Elena Rossi", date(2026, 8, 17), 0.7, 0.3, {"step": 1.0, "yoga": 0.5, "swim": 0.3}),
    ("U01FFF006", "Farid Khan", date(2026, 8, 24), 0.8, 0.1, {"step": 1.0, "pushup": 0.6, "plank": 0.5}),
    ("U01GGG007", "Grace Lee", date(2026, 11, 10), 1.0, 0.0, {"step": 1.0}),
    ("U01HHH008", "Hiro Tanaka", date(2026, 11, 12), 1.0, 0.0, {"step": 1.0, "pushup": 1.0}),
    ("U01III009", "Ines Alvarez", date(2026, 9, 1), 0.5, 0.9, {"step": 1.0, "yoga": 0.6, "read": 0.5}),
    ("U01JJJ010", "Jon Smith", date(2026, 9, 7), 0.35, 0.05, {"step": 1.0, "plank": 0.5}),
    ("U01KKK011", "Kavya Nair", date(2026, 8, 3), 0.85, 0.25,
     {"step": 1.0, "pushup": 0.5, "plank": 0.4, "yoga": 0.4, "swim": 0.2, "read": 0.4, "meditate": 0.4}),
    ("U01LLL012", "Liam O'Brien", date(2026, 9, 14), 0.7, 0.1, {"step": 1.0, "pushup": 0.6, "plank": 0.4}),
    ("U01MMM013", "Mei Wong", date(2026, 8, 3), 0.9, 0.2, {"step": 1.0, "pushup": 0.6}),      # opted out
    ("U01NNN014", "Noah Fischer", date(2026, 9, 21), 0.8, 0.1, {"step": 1.0, "pushup": 0.9, "plank": 0.5}),
]
VALUE_RANGE = {"step": (4000, 15000), "pushup": (10, 55), "plank": (30, 200), "yoga": (20, 60),
               "swim": (20, 50), "read": (8, 40), "meditate": (5, 25)}


def make_rows():
    """The activity rows of the data table: one per person per activity, the session list lined up with the
    days logged (the last entry of each is the latest)."""
    rows = []
    for index, (pid, name, first, wd, we, activities) in enumerate(PEOPLE):
        rng = random.Random("fixture-{}".format(pid))
        end = TODAY
        if name == "Farid Khan":                 # away from the 5th of October until Wednesday: a comeback
            days = _days(first, date(2026, 10, 5), rng, wd, we) + [date(2026, 11, 11), date(2026, 11, 12),
                                                                   date(2026, 11, 13)]
        elif name == "Asha Rao":                 # every working day since the 7th of September
            days = _days(first, date(2026, 9, 4), rng, 0.7, 0.1) + _days(
                date(2026, 9, 7), end, rng, 1.0, 0.2, always_weekdays=True)
        elif first >= date(2026, 11, 10):
            days = [d for d in _days(first, end, rng, 1.0, 0.0)]
        else:
            days = _days(first, end, rng, wd, we)
        days = sorted(set(days))
        for activity, share in activities.items():
            mine = [d for d in days if share >= 1.0 or rng.random() < share]
            if name == "Dev Patel" and activity == "step":
                pass
            if not mine:
                continue
            lo, hi = VALUE_RANGE[activity]
            values = [rng.randint(lo, hi) for _ in mine]
            if name == "Noah Fischer" and activity == "pushup":        # a personal best in the latest session
                values = [30, 35, 40, 45, 38] + values[5:]
                values[len(mine) - 1] = 80
                mine = mine if mine[-1] == TODAY else mine + [TODAY]
                values = (values + [80] * len(mine))[:len(mine)]
                values[-1] = 80
            rows.append({
                "id": pid, "name": name, "row_type": activity + "_users",
                "total": ",".join(str(v) for v in values),
                "heatmap_dates": ",".join(d.isoformat() for d in mine),
                "first_seen": mine[0].isoformat(),
                "personal_best_single_set": max(values) if activity in fs.SET_BASED else 0,
                "longest_streak": 5 if name == "Asha Rao" else 2,
                "leaderboard_optout": name == "Mei Wong",
            })
    # Dev tries swimming once this week: "first time trying something new".
    rows.append({"id": "U01DDD004", "name": "Dev Patel", "row_type": "swim_users", "total": "35",
                 "heatmap_dates": "2026-11-11", "first_seen": "2026-11-11", "personal_best_single_set": 0,
                 "longest_streak": 1, "leaderboard_optout": False})
    return rows


def write_json(directory, name, data):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return path


def earlier_run(rows, days_before, share=0.92, badges=None):
    """A saved snapshot run `days_before` days before TODAY, with every total a little lower than now."""
    facts = fs.summarize(rows)
    run = {"d": (TODAY - timedelta(days=days_before)).isoformat(),
           "t": {a: int(v * share) for a, v in facts["totals"].items()},
           "n": {a: max(1, int(v * share)) for a, v in facts["sessions"].items()},
           "p": max(1, facts["people"] - 2), "w": {"people": 5, "checkins": 20, "new": 0}}
    if badges is not None:
        run["b"] = badges
    return run


class Scenario(object):
    """The fixture on disk, and a way to run main() on it."""

    def __init__(self, rows=None, runs=None):
        self.dir = tempfile.mkdtemp(prefix="friday_summary_test_")
        atexit.register(shutil.rmtree, self.dir, True)
        self.rows = rows if rows is not None else make_rows()
        self.data = write_json(self.dir, "rows.json", self.rows)
        self.snapshot = os.path.join(self.dir, "snapshot.txt")
        if runs:
            with open(self.snapshot, "w", encoding="utf-8") as handle:
                handle.write(fs.seal(fs.snapshot_text(runs)))

    def run(self, **extra):
        random.seed(SEED)
        fields = {"local_data_file": self.data, "local_snapshot_file": self.snapshot, "dry_run": True,
                  "today": TODAY.isoformat(), "format": "weekly"}
        fields.update(extra)
        return fs.main(fields)


def scenarios():
    """The named runs the golden file pins: (name, Scenario, extra input)."""
    rows = make_rows()
    return [
        ("first_run", Scenario(rows), {}),
        ("second_run", Scenario(rows, [earlier_run(rows, 7)]), {}),
        ("second_run_mentions", Scenario(rows, [earlier_run(rows, 7)]), {"mention_people": True}),
        ("midweek", Scenario(rows, [earlier_run(rows, 7)]), {"today": "2026-11-11"}),
        ("quiet", Scenario(rows, [earlier_run(rows, 7)]), {"today": "2027-01-20"}),
        ("classic", Scenario(rows), {"format": "classic"}),
    ]


def regenerate_golden():
    golden = {}
    for name, scenario, extra in scenarios():
        out = scenario.run(**dict(extra, look="old"))     # the original step ignores `look`; the new one honours it
        golden[name] = {"message_json": out["message_json"], "message_text": out["message_text"],
                        "headline": out["headline"], "moments": out["moments"], "new_badges": out["new_badges"]}
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    with open(GOLDEN, "w", encoding="utf-8") as handle:
        json.dump(golden, handle, indent=1, sort_keys=True)
    print("wrote", GOLDEN, "({} scenarios)".format(len(golden)))


# --------------------------------------------------------------------------
# Slack's rules, and a few shortcuts
# --------------------------------------------------------------------------

REFERENCE_DIR = os.path.join(os.path.dirname(HERE), "slack_block_kit")
INSIDE_CONTAINER = {"section", "context", "divider", "rich_text", "image", "actions", "video"}


def walk(blocks):
    """Every block of a message, the ones inside a layout or a container too."""
    for block in blocks:
        yield block
        if block.get("type") == "layout":
            for row in block["rows"]:
                for item in row["items"]:
                    for inner in walk([item["block"]]):
                        yield inner
        for child in block.get("child_blocks") or []:
            for inner in walk([child]):
                yield inner


def strings(value):
    """Every string in some JSON, for looking something up in a post."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for part in value.values():
            for found in strings(part):
                yield found
    elif isinstance(value, list):
        for part in value:
            for found in strings(part):
                yield found


def all_text(blocks):
    return "\n".join(strings(blocks))


def of_type(blocks, kind):
    return [b for b in walk(blocks) if b.get("type") == kind]


def check_card(card):
    assert card["type"] == "card"
    for part, limit in (("title", 150), ("subtitle", 150), ("body", 200)):
        if card.get(part):
            assert card[part]["type"] == "mrkdwn" and len(card[part]["text"]) <= limit, \
                "card {} of {} characters".format(part, len(card[part]["text"]))


def check_blocks(blocks):
    """Raise AssertionError if Slack would turn these blocks down (the limits are the ones the other steps' tests use,
    and the table's the genie console's: one a message, 100 rows, 20 columns, 10,000 characters)."""
    assert isinstance(blocks, list) and blocks, "blocks must be a list"
    assert len(blocks) <= 50, "{} blocks, Slack takes 50".format(len(blocks))
    seen = set()
    tables = 0
    for block in walk(blocks):
        kind = block.get("type")
        if "block_id" in block:
            assert len(block["block_id"]) <= 255
            assert block["block_id"] not in seen, "block_id {} used twice".format(block["block_id"])
            seen.add(block["block_id"])
        if kind == "header":
            assert block["text"]["type"] == "plain_text" and len(block["text"]["text"]) <= 150, "header over 150"
        elif kind == "section":
            assert block.get("text") or block.get("fields"), "a section needs text or fields"
            if block.get("text"):
                assert len(block["text"]["text"]) <= 3000, "section text of {}".format(len(block["text"]["text"]))
            assert len(block.get("fields") or []) <= 10, "more than 10 fields"
            for field in block.get("fields") or []:
                assert 0 < len(field["text"]) <= 2000, "field of {} characters".format(len(field["text"]))
        elif kind == "context":
            assert 1 <= len(block["elements"]) <= 10, "context needs 1 to 10 elements"
        elif kind == "carousel":
            assert 1 <= len(block["elements"]) <= 10, "a carousel holds 1 to 10 cards"
            for card in block["elements"]:
                check_card(card)
        elif kind == "table":
            tables += 1
            assert tables == 1, "Slack takes one table block a message"
            rows, settings = block["rows"], block["column_settings"]
            assert 1 <= len(rows) <= 100 and 1 <= len(settings) <= 20
            assert all(isinstance(c, dict) for c in settings), "column_settings holds one object per column"
            for row in rows:
                assert len(row) == len(settings), "a row of {} cells in a table of {} columns".format(
                    len(row), len(settings))
                for cell in row:
                    assert cell["type"] in ("raw_text", "rich_text")
                    if cell["type"] == "raw_text":
                        assert cell["text"].strip(), "a table cell may not be empty"
            assert len(all_text(rows)) <= 10000
        elif kind == "layout":
            assert block["rows"], "a layout needs a row"
            assert block.get("grid_lines") in (None, "outer", "rows", "none")
            for row in block["rows"]:
                assert 1 <= len(row["items"]) <= fs.TILES_PER_ROW
                for item in row["items"]:
                    assert item["block"]["type"] in ("section", "context", "container", "actions")
                    assert item.get("width", "standard") in ("narrow", "standard", "wide")
                    assert item.get("horizontal_alignment", "start") in ("start", "center", "end")
        elif kind == "container":
            assert block["title"]["type"] == "plain_text" and block["title"]["text"]
            # Slack shows a :shortcode: in a container's title as typed; a header block draws it
            for part in (block["title"], block.get("subtitle", {"text": ""})):
                assert not fs.EMOJI_TOKEN.search(part["text"]), "an emoji shortcode in {!r}".format(part["text"])
            assert block.get("subtitle", {"type": "plain_text"})["type"] == "plain_text"
            assert block["child_blocks"], "a container needs something in it"
            for child in block["child_blocks"]:
                assert child["type"] in INSIDE_CONTAINER, "a {} inside a container".format(child["type"])
            if "default_collapsed" in block:
                assert block.get("is_collapsible") is True
            # Slack refused the first new-look post for this: "`has_header_divider` can only be set when
            # `is_collapsible` is false"
            assert not (block.get("has_header_divider") and block.get("is_collapsible")), \
                "a container with a header divider and a fold"
        elif kind == "data_visualization":
            assert block["title"]
            chart = block["chart"]
            if chart["type"] == "pie":
                assert chart["segments"] and all(seg["value"] > 0 and seg["label"] for seg in chart["segments"])
            else:
                assert chart["type"] in ("line", "bar", "area")
                labels = chart["axis_config"]["categories"]
                for series in chart["series"]:
                    assert [d["label"] for d in series["data"]] == labels, "series do not follow the categories"
                    assert all(isinstance(d["value"], (int, float)) for d in series["data"])
    return True


def reference_keys():
    """{block type: every key Slack's own samples (slack_block_kit/) give it}. {} without the folder."""
    found = {}
    if not os.path.isdir(REFERENCE_DIR):
        return found

    def visit(node):
        if isinstance(node, dict):
            if isinstance(node.get("type"), str):
                found.setdefault(node["type"], set()).update(node)
            for part in node.values():
                visit(part)
        elif isinstance(node, list):
            for part in node:
                visit(part)

    for name in sorted(os.listdir(REFERENCE_DIR)):
        if name.endswith(".json"):
            with open(os.path.join(REFERENCE_DIR, name), "r", encoding="utf-8") as handle:
                visit(json.load(handle))
    return found


def run_new(scenario_name="second_run", **extra):
    """One of the fixture's runs, in the new look: (output, blocks)."""
    spec = dict((n, (s, e)) for n, s, e in scenarios())[scenario_name]
    out = spec[0].run(**dict(spec[1], **extra))
    return out, json.loads(out["message_json"])


RUNS = ("first_run", "second_run", "second_run_mentions", "midweek", "quiet")


# --------------------------------------------------------------------------
# The old post is pinned
# --------------------------------------------------------------------------

class TestPlainUnchanged(unittest.TestCase):
    """What the step posted before there was a new look: every scenario, block for block."""

    @classmethod
    def setUpClass(cls):
        with open(GOLDEN, "r", encoding="utf-8") as handle:
            cls.golden = json.load(handle)
        cls.specs = dict((n, (s, e)) for n, s, e in scenarios())

    def check(self, name, **extra):
        scenario, own = self.specs[name]
        out = scenario.run(**dict(own, **extra))
        want = self.golden[name]
        self.assertEqual(json.loads(out["message_json"]), json.loads(want["message_json"]))
        self.assertEqual(out["message_text"], want["message_text"])
        self.assertEqual(out["headline"], want["headline"])
        self.assertEqual(out["moments"], want["moments"])
        self.assertEqual(out["new_badges"], want["new_badges"])
        return out

    def test_first_run(self):
        self.check("first_run", look="old")

    def test_second_run_with_a_snapshot(self):
        self.check("second_run", look="old")

    def test_second_run_with_mentions(self):
        self.check("second_run_mentions", look="old")

    def test_midweek(self):
        self.check("midweek", look="old")

    def test_a_quiet_week(self):
        self.check("quiet", look="old")

    def test_classic_in_the_old_look_is_untouched(self):
        # the classic (all-time) summary as it always was, by any of the old look's names
        for look in ("old", "OLD", " plain ", "original", "legacy", "previous"):
            self.check("classic", look=look)
        self.check("classic", look="new", new_features="none")

    def test_old_look_by_any_of_its_names(self):
        for word in ("old", "OLD", " plain ", "original", "legacy", "previous"):
            self.check("second_run", look=word)

    def test_new_features_none_is_the_old_post(self):
        self.check("second_run", look="new", new_features="none")

    def test_new_features_do_not_touch_the_old_look(self):
        self.check("second_run", look="old", new_features="charts,tiles")

    def test_the_old_look_uses_no_new_block(self):
        old = {"header", "section", "context", "divider", "image"}
        for name in RUNS:
            kinds = set(b["type"] for b in walk(json.loads(self.golden[name]["message_json"])))
            self.assertLessEqual(kinds, old, name)
            self.assertFalse(any("level" in b for b in json.loads(self.golden[name]["message_json"])))

    def test_every_golden_scenario_is_checked(self):
        self.assertEqual(sorted(self.golden), sorted(n for n, _, _ in scenarios()))

    def test_old_look_reports_itself(self):
        self.assertEqual(self.check("second_run", look="old")["look_used"], "old")


# --------------------------------------------------------------------------
# look and new_features
# --------------------------------------------------------------------------

class TestLook(unittest.TestCase):
    def features(self, look=None, new=None):
        return set(fs.parse_look(look, new).features)

    def test_new_is_the_default(self):
        for value in (None, "", "new", "NEW", "rich", "modern", "something unheard of"):
            self.assertEqual(self.features(value), set(fs.NEW_FEATURES), value)

    def test_old_in_every_spelling(self):
        for value in ("old", "Old", " plain", "original", "legacy", "previous"):
            self.assertFalse(fs.parse_look(value).new, value)
            self.assertIs(fs.parse_look(value), fs.OLD_LOOK)

    def test_all_features_by_default_blank_or_all(self):
        for value in (None, "", "  ", "all", "ALL"):
            self.assertEqual(self.features("new", value), set(fs.NEW_FEATURES), repr(value))

    def test_pick_some(self):
        self.assertEqual(self.features("new", "charts, tiles"), {"charts", "tiles"})
        self.assertEqual(self.features("new", "Cards;TABLES panels"), {"cards", "tables", "panels"})

    def test_take_one_away(self):
        self.assertEqual(self.features("new", "-charts"), set(fs.NEW_FEATURES) - {"charts"})
        self.assertEqual(self.features("new", "all,-charts,-tiles"), set(fs.NEW_FEATURES) - {"charts", "tiles"})
        self.assertEqual(self.features("new", "cards,tiles,-tiles"), {"cards"})

    def test_none_is_the_old_look(self):
        self.assertFalse(fs.parse_look("new", "none").new)
        self.assertFalse(fs.parse_look("new", "headers,none").new)

    def test_nothing_left_is_the_old_look(self):
        self.assertFalse(fs.parse_look("new", ",".join("-" + f for f in fs.NEW_FEATURES)).new)

    def test_unknown_words_switch_nothing_on(self):
        # a typo is ignored; with nothing recognisable left, the default (all) stands
        self.assertEqual(self.features("new", "chart"), set(fs.NEW_FEATURES))
        self.assertEqual(self.features("new", "charts,bogus"), {"charts"})
        self.assertEqual(self.features("new", "-bogus"), set(fs.NEW_FEATURES))

    def test_block_ids_count_up_per_kind(self):
        look = fs.parse_look("new")
        self.assertEqual([look.block_id("tile"), look.block_id("tile"), look.block_id("chart")],
                         ["fs_tile_1", "fs_tile_2", "fs_chart_1"])
        self.assertEqual(fs.parse_look("new").block_id("tile"), "fs_tile_1")      # each post starts again


# --------------------------------------------------------------------------
# The new post against Slack's rules
# --------------------------------------------------------------------------

class TestRichBlocks(unittest.TestCase):
    def test_every_run_is_valid(self):
        for name in RUNS:
            out, blocks = run_new(name)
            self.assertEqual(out["look_used"], "new", name)
            self.assertTrue(check_blocks(blocks), name)

    def test_every_run_is_valid_with_each_feature_alone(self):
        for feature in fs.NEW_FEATURES:
            for name in RUNS:
                _, blocks = run_new(name, new_features=feature)
                self.assertTrue(check_blocks(blocks), "{} / {}".format(feature, name))

    def test_every_run_is_valid_with_each_feature_taken_away(self):
        for feature in fs.NEW_FEATURES:
            for name in RUNS:
                _, blocks = run_new(name, new_features="-" + feature)
                self.assertTrue(check_blocks(blocks), "-{} / {}".format(feature, name))

    def test_the_new_blocks_are_all_there_in_a_full_week(self):
        _, blocks = run_new("second_run")
        kinds = set(b["type"] for b in walk(blocks))
        for kind in ("layout", "carousel", "table", "container", "data_visualization", "header"):
            self.assertIn(kind, kinds)

    def test_title_leads_and_sections_sit_under_it(self):
        _, blocks = run_new("second_run")
        headers = of_type(blocks, "header")
        self.assertEqual(headers[0]["level"], 1)
        self.assertEqual(blocks[0], headers[0])                     # no banner image: the title is first
        self.assertTrue(all(h["level"] == 2 for h in headers[1:]))

    def test_the_banner_stays_above_the_title(self):
        _, blocks = run_new("second_run", header_image_url="https://example.com/banner.png")
        self.assertEqual([b["type"] for b in blocks[:2]], ["image", "header"])
        self.assertEqual(blocks[0]["image_url"], "https://example.com/banner.png")

    def test_tiles_are_a_grid_of_cells(self):
        _, blocks = run_new("second_run")
        grid = of_type(blocks, "layout")[0]
        cells = [item for row in grid["rows"] for item in row["items"]]
        self.assertTrue(all(i["horizontal_alignment"] == "center" for i in cells))
        self.assertTrue(all(len(row["items"]) <= fs.TILES_PER_ROW for row in grid["rows"]))
        self.assertEqual(grid["grid_lines"], "outer")
        # the numbers of the old tiles, one cell each
        rows = make_rows()
        week = fs.week_facts(fs.gather_people(rows), TODAY)
        vol = fs.volume_changes(fs.summarize(rows), [earlier_run(rows, 7)], TODAY)
        self.assertEqual(len(cells), len(fs.stat_tile_parts(week, vol)))

    def test_the_one_chart_is_how_many_people_logged_each_activity(self):
        _, blocks = run_new("second_run")
        charts = of_type(blocks, "data_visualization")
        self.assertEqual([c["chart"]["type"] for c in charts], ["bar"])
        chart = charts[0]
        self.assertEqual(chart["title"], "People per activity this week")
        data = chart["chart"]["series"][0]["data"]
        self.assertEqual(chart["chart"]["series"][0]["name"], "People")
        self.assertEqual(chart["chart"]["axis_config"]["categories"], [d["label"] for d in data])
        self.assertEqual(chart["chart"]["axis_config"]["y_label"], "People")
        # the figures are the table's own: people who logged the activity in the last 7 days
        week = fs.week_facts(fs.gather_people(make_rows()), TODAY)
        want = dict((fs.TITLE[a], people) for a, (people, _days) in week["by_activity"].items())
        self.assertEqual(dict((d["label"], d["value"]) for d in data), {k: want[k] for k in
                                                                       [d["label"] for d in data]})
        self.assertEqual(data[0], {"label": "Steps", "value": want["Steps"]})   # the most-done first
        values = [d["value"] for d in data]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertGreater(len(set(values)), 2)                        # figures that differ: something to read

    def test_the_chart_keeps_the_ten_most_done_activities(self):
        look = fs.parse_look("new")
        activities = ["step", "pushup", "plank", "yoga", "swim", "read", "meditate", "run", "cycle", "dance",
                      "journal", "write", "sketch"]
        week = {"by_activity": {a: [20 - i, 40 - i] for i, a in enumerate(activities)}}
        chart = fs.activity_chart(look, week)
        labels = chart["chart"]["axis_config"]["categories"]
        self.assertEqual(len(labels), fs.CHART_ACTIVITIES)
        self.assertEqual(labels[0], "Steps")
        self.assertEqual(labels[-1], "Dancing")                       # the tenth
        self.assertNotIn("Journalling", labels)

    def test_equal_people_are_ordered_by_check_ins_then_name(self):
        look = fs.parse_look("new")
        week = {"by_activity": {"yoga": [3, 9], "swim": [3, 12], "read": [3, 9], "step": [5, 20]}}
        labels = fs.activity_chart(look, week)["chart"]["axis_config"]["categories"]
        self.assertEqual(labels, ["Steps", "Swimming", "Reading", "Yoga"])

    def test_an_activity_nobody_logged_is_not_a_bar(self):
        look = fs.parse_look("new")
        week = {"by_activity": {"step": [4, 12], "yoga": [0, 0], "swim": [2, 3]}}
        self.assertEqual(fs.activity_chart(look, week)["chart"]["axis_config"]["categories"],
                         ["Steps", "Swimming"])

    def test_there_is_no_pie_anywhere_and_no_header_over_the_one_chart(self):
        # a pie of the week's check-ins showed slices and no figures: nothing to read off it
        for name in RUNS:
            _, blocks = run_new(name)
            kinds = [c["chart"]["type"] for c in of_type(blocks, "data_visualization")]
            self.assertLessEqual(set(kinds), {"bar"}, name)                       # a bar, never a pie
            self.assertEqual(len(kinds), 0 if name == "quiet" else 1, name)
            self.assertNotIn("The week in charts", all_text(blocks), name)
            self.assertFalse(hasattr(fs, "mix_chart") or hasattr(fs, "pie_chart"))
        _, blocks = run_new("second_run")
        index = next(i for i, b in enumerate(blocks) if b["type"] == "data_visualization")
        self.assertEqual(blocks[index - 1], {"type": "divider"})               # the chart's own title heads it

    def test_the_top_contributors_come_straight_after_the_numbers(self):
        for name in ("first_run", "second_run", "midweek"):
            _, blocks = run_new(name)
            kinds = [b["type"] for b in blocks]
            grid = kinds.index("layout")
            after = blocks[grid + 1:]
            if after and after[0]["type"] == "context":                         # the week before, when there is one
                after = after[1:]
            self.assertEqual([b["type"] for b in after[:3]], ["divider", "header", "table"], name)
            self.assertIn("top contributors", after[1]["text"]["text"])
            # ... and the shout-outs come next
            self.assertEqual([b["type"] for b in after[3:5]], ["divider", "header"], name)
            self.assertIn("Shout-outs", after[4]["text"]["text"])

    def test_the_top_contributors_follow_the_numbers_without_the_table_too(self):
        _, blocks = run_new("second_run", new_features="-tables")
        grid = [b["type"] for b in blocks].index("layout")
        after = blocks[grid + 1:]
        if after[0]["type"] == "context":
            after = after[1:]
        self.assertEqual(after[0]["type"], "divider")
        self.assertIn(fs.WEEK_TOP_HEADING, after[1]["text"]["text"])
        self.assertTrue(after[1]["fields"])

    def test_the_old_look_keeps_the_top_contributors_where_they_were(self):
        _, blocks = run_new("second_run", look="old")
        top = next(i for i, b in enumerate(blocks) if fs.WEEK_TOP_HEADING in b.get("text", {}).get("text", ""))
        shout = next(i for i, b in enumerate(blocks) if b["type"] == "header"
                     and "Shout-outs" in b["text"]["text"])
        self.assertGreater(top, shout)

    def test_charts_wait_until_there_is_something_to_compare(self):
        look = fs.parse_look("new")
        self.assertIsNone(fs.activity_chart(look, {"by_activity": {}}))
        self.assertIsNone(fs.activity_chart(look, {"by_activity": {"step": [9, 40]}}))    # one bar has no neighbour
        self.assertIsNotNone(fs.activity_chart(look, {"by_activity": {"step": [9, 40], "yoga": [2, 5]}}))

    def test_badges_are_cards_in_a_carousel(self):
        _, blocks = run_new("second_run")
        cards = [c for b in of_type(blocks, "carousel") for c in b["elements"]]
        self.assertEqual(len(cards), 3)
        self.assertEqual([c["title"]["text"] for c in cards],
                         [":fire:  Unstoppable", ":repeat:  Eight-Week Rhythm",
                          ":white_check_mark:  Twelve Perfect Weeks"])      # kind by kind, as the old fields run
        text = all_text(cards)
        for who, badge in (("Asha Rao", "Unstoppable"), ("Asha Rao", "Twelve Perfect Weeks"),
                           ("Noah Fischer", "Eight-Week Rhythm")):
            self.assertIn(who, text)
            self.assertIn(badge, text)
        # what it took is on the card
        self.assertIn(fs.BADGES["streak_50"]["about"], text)

    def test_one_table_for_the_top_contributors(self):
        for name in ("first_run", "second_run", "midweek"):
            _, blocks = run_new(name)
            tables = of_type(blocks, "table")
            self.assertEqual(len(tables), 1, name)
            table = tables[0]
            self.assertEqual(len(table["column_settings"]), 3)
            day = date.fromisoformat(dict((n, e) for n, _, e in scenarios())[name].get("today", TODAY.isoformat()))
            people = fs.gather_people(make_rows())
            rows = fs.week_top_rows(people, fs.week_facts(people, day), day)
            self.assertTrue(rows)
            self.assertEqual(len(table["rows"]), 1 + len(rows))

    def test_panels_are_titled_and_the_records_are_folded(self):
        for name in ("first_run", "second_run", "midweek"):
            _, blocks = run_new(name)
            panels = of_type(blocks, "container")
            titles = [p["title"]["text"] for p in panels]
            self.assertIn("Who showed up, day by day", titles)
            self.assertIn("The Great Walk", titles)
            for p in panels:
                if "records" in p["block_id"]:
                    self.assertTrue(p["is_collapsible"] and p["default_collapsed"])
                    self.assertNotIn("has_header_divider", p)               # Slack: not on a collapsible one
                    self.assertNotIn("text", p["child_blocks"][0])          # the title says what it is
                else:
                    self.assertTrue(p["has_header_divider"])
                    self.assertNotIn("is_collapsible", p)
                    self.assertNotIn("default_collapsed", p)

    def test_a_panel_has_a_rule_or_a_fold_never_both(self):
        look = fs.parse_look("new")
        plain = fs.panel(look, "T", [fs.text_section("x")])
        self.assertTrue(plain["has_header_divider"])
        self.assertNotIn("is_collapsible", plain)
        for closed in (True, False):
            folded = fs.panel(look, "T", [fs.text_section("x")], collapsed=closed)
            self.assertTrue(folded["is_collapsible"])
            self.assertEqual(folded["default_collapsed"], closed)
            self.assertNotIn("has_header_divider", folded)
        with self.assertRaises(AssertionError):
            check_blocks([dict(plain, is_collapsible=True)])

    def test_records_panel_comes_on_the_alternate_weeks(self):
        have = {}
        for name, day in (("a", "2026-11-13"), ("b", "2026-11-20"), ("c", "2026-11-27"), ("d", "2026-12-04")):
            _, blocks = run_new("second_run", today=day)
            records = [b for b in of_type(blocks, "container") if "records" in b.get("block_id", "")]
            have[name] = bool(records)
            for panel in records:
                self.assertEqual(panel["title"]["text"], "Channel records to beat")
        self.assertIn(True, have.values())
        self.assertIn(False, have.values())

    def test_a_feature_switched_off_goes_back_to_the_old_block(self):
        cases = (("tiles", "layout"), ("charts", "data_visualization"), ("cards", "carousel"),
                 ("tables", "table"), ("panels", "container"))
        for feature, kind in cases:
            _, blocks = run_new("second_run", new_features="-" + feature)
            self.assertEqual(of_type(blocks, kind), [], feature)
            others = [k for f, k in cases if f != feature]
            for other in others:
                self.assertTrue(of_type(blocks, other), "{} lost when only {} was taken away".format(other, feature))
        _, blocks = run_new("second_run", new_features="-headers")
        self.assertFalse(any("level" in h for h in of_type(blocks, "header")))

    def test_with_no_feature_but_headers_the_post_is_the_old_one_with_levels_and_one_move(self):
        _, blocks = run_new("second_run", new_features="headers")
        old = json.loads(TestPlainUnchanged.golden_for("second_run")["message_json"])
        # the one thing the new look does whatever the features: the top contributors (a divider, then
        # their heading block and any block that carries on its rows) follow the numbers
        start = next(i for i, b in enumerate(old) if fs.WEEK_TOP_HEADING in b.get("text", {}).get("text", ""))
        end = start + 1
        while end < len(old) and old[end]["type"] == "section" and old[end].get("fields") and "text" not in old[end]:
            end += 1
        group, rest = old[start - 1:end], old[:start - 1] + old[end:]
        at = next(i for i, b in enumerate(rest) if b["type"] == "divider")     # the one before the shout-outs
        expected = rest[:at] + group + rest[at:]
        stripped = [dict((k, v) for k, v in b.items() if k != "level") for b in blocks]
        self.assertEqual(stripped, expected)
        self.assertEqual(len(stripped), len(old))

    def test_the_new_blocks_use_only_the_keys_slacks_samples_use(self):
        reference = reference_keys()
        if not reference:
            self.skipTest("slack_block_kit/ is not next to this step")
        checked = set()
        for name in RUNS:
            _, blocks = run_new(name)
            nested = list(walk(blocks)) + [c for b in of_type(blocks, "carousel") for c in b["elements"]]
            for block in nested:
                kind = block["type"]
                if kind in ("layout", "container", "data_visualization", "carousel", "card", "table", "header"):
                    # column_settings is not in Slack's samples; the genie console posts it, and Slack wants one
                    # object per column (see its _native_table)
                    extra = set(block) - reference[kind] - ({"column_settings"} if kind == "table" else set())
                    self.assertFalse(extra, "{} has {} which Slack's samples never give it".format(kind, extra))
                    checked.add(kind)
            for block in of_type(blocks, "layout"):
                for row in block["rows"]:
                    for item in row["items"]:
                        self.assertFalse(set(item) - {"block", "width", "horizontal_alignment"})
            for block in of_type(blocks, "data_visualization"):
                chart = block["chart"]
                self.assertFalse(set(chart) - reference[chart["type"]], name)
        self.assertEqual(checked, {"layout", "container", "data_visualization", "carousel", "card", "table",
                                   "header"})

    def test_block_ids_are_the_same_on_every_run(self):
        a = json.dumps(run_new("second_run")[1], sort_keys=True)
        b = json.dumps(run_new("second_run")[1], sort_keys=True)
        self.assertEqual(a, b)

    def test_few_enough_blocks(self):
        for name in RUNS:
            _, blocks = run_new(name)
            self.assertLessEqual(len(blocks), 50)
            _, old = run_new(name, look="old")
            self.assertLessEqual(len(blocks), len(old) + 3, name)             # shorter or about the same


def _golden_for(cls, name):
    with open(GOLDEN, "r", encoding="utf-8") as handle:
        return json.load(handle)[name]


TestPlainUnchanged.golden_for = classmethod(_golden_for)


# --------------------------------------------------------------------------
# The new post says what the old one says
# --------------------------------------------------------------------------

class TestRichContent(unittest.TestCase):
    def pair(self, name="second_run", **extra):
        _, new = run_new(name, **extra)
        _, old = run_new(name, look="old", **extra)
        return new, old

    def test_same_title_headline_and_notification(self):
        for name in RUNS:
            new_out, _ = run_new(name)
            old_out, _ = run_new(name, look="old")
            self.assertEqual(new_out["message_text"], old_out["message_text"], name)
            self.assertEqual(new_out["headline"], old_out["headline"], name)
            self.assertEqual(new_out["moments"], old_out["moments"], name)
            self.assertEqual(new_out["new_badges"], old_out["new_badges"], name)
            self.assertEqual(new_out["week_people"], old_out["week_people"], name)

    def test_same_title_and_opening_lines(self):
        for name in RUNS:
            new, old = self.pair(name)
            self.assertEqual(of_type(new, "header")[0]["text"], of_type(old, "header")[0]["text"])
            first_section = lambda blocks: next(b for b in blocks if b["type"] == "section")
            self.assertEqual(first_section(new), first_section(old))

    def test_every_shout_out_is_there(self):
        new, old = self.pair()
        out, _ = run_new("second_run")
        text = all_text(new)
        self.assertTrue(out["moments"])
        for line in out["moments"]:
            self.assertIn(line, text)

    def test_every_tile_figure_is_there(self):
        new, old = self.pair()
        old_cells = [f["text"] for b in old if b["type"] == "section" and b.get("fields")
                     for f in b["fields"]][:len(of_type(new, "layout")[0]["rows"]) * fs.TILES_PER_ROW]
        grid = all_text(of_type(new, "layout"))
        week = fs.week_facts(fs.gather_people(make_rows()), TODAY)
        for icon, figure, label in fs.stat_tile_parts(week, None):
            if figure:
                self.assertIn(str(figure), grid)
                self.assertIn(label, grid)

    def test_tiles_and_the_old_fields_are_the_same_tiles(self):
        rows = make_rows()
        week = fs.week_facts(fs.gather_people(rows), TODAY)
        vol = fs.volume_changes(fs.summarize(rows), [earlier_run(rows, 7)], TODAY)
        parts = fs.stat_tile_parts(week, vol, ":team:")
        self.assertEqual(fs.stat_tiles(week, vol, ":team:"),
                         ["{}  *{}* {}".format(i, f, l) for i, f, l in parts])
        self.assertGreater(len(parts), 3)

    def test_every_badge_and_every_name_is_there(self):
        new, old = self.pair()
        out, _ = run_new("second_run")
        text = all_text(new)
        for earned in out["new_badges"]:
            self.assertIn(earned["badge"], text)
            for name in earned["people"]:
                self.assertIn(name, text)

    def test_mentions_reach_the_cards(self):
        new, old = self.pair("second_run_mentions")
        cards = all_text([c for b in of_type(new, "carousel") for c in b["elements"]])
        self.assertIn("<@U01AAA001>", cards)
        self.assertIn("<@U01NNN014>", cards)
        self.assertNotIn("Asha Rao", cards)
        # the records and the top contributors never ping, as before
        self.assertNotIn("<@", all_text(of_type(new, "table")))

    def test_the_calendar_says_the_same(self):
        new, old = self.pair()
        grid = next(b for b in old if b["type"] == "section" and ":large_" in b.get("text", {}).get("text", ""))
        note = old[old.index(grid) + 1]
        panel = next(b for b in of_type(new, "container") if "calendar" in b["block_id"])
        self.assertEqual(panel["child_blocks"][0]["text"], grid["text"])
        self.assertEqual(panel["child_blocks"][1]["elements"], note["elements"])

    def test_the_top_contributors_are_the_same_people_and_figures(self):
        new, old = self.pair()
        people = fs.gather_people(make_rows())
        week = fs.week_facts(people, TODAY)
        rows = fs.week_top_rows(people, week, TODAY)
        self.assertEqual(fs.week_top(people, week, TODAY),
                         fs.record_blocks(rows, fs.WEEK_TOP_HEADING))
        table = of_type(new, "table")[0]
        body = table["rows"][1:]
        for (icon, what, figure, who), row in zip(rows, body):
            self.assertEqual(row[1]["text"], figure)
            self.assertEqual(row[2]["text"], who)
            self.assertIn(what.replace("*", ""), all_text(row[0]))
            if icon:
                self.assertIn({"type": "emoji", "name": icon.strip(":")}, row[0]["elements"][0]["elements"])
        self.assertEqual([c["text"] for c in table["rows"][0][0]["elements"][0]["elements"]], ["Activity"])

    def test_the_journey_says_the_same(self):
        new, old = self.pair()
        old_text = next(b for b in old if b["type"] == "section"
                        and "The Great Walk" in b.get("text", {}).get("text", ""))
        lines = old_text["text"]["text"].split("\n")
        walk_panel = next(b for b in of_type(new, "container") if "walk" in b["block_id"])
        self.assertEqual(walk_panel["child_blocks"][0]["text"]["text"], "\n".join(lines[1:]))
        self.assertIn(lines[0].split("*")[1], walk_panel["title"]["text"])
        self.assertTrue(walk_panel["subtitle"]["text"].startswith("Leg "))
        self.assertEqual(walk_panel["subtitle"]["text"].lower(),
                         " · ".join(lines[0].split("  ·  ")[1:]))               # "leg 3 of 20" (· "lap 2")

    def test_the_closing_ask_is_the_same(self):
        new, old = self.pair()
        ask = [b for b in old if b["type"] == "section" and "Who's closing it out" in b.get("text", {}).get("text", "")]
        self.assertEqual(len(ask), 1)
        self.assertIn(ask[0], new)

    def test_the_footer_is_the_same(self):
        new, old = self.pair()
        self.assertEqual(new[-1], old[-1])

    def test_records_when_they_come_say_the_same(self):
        for day in ("2026-11-13", "2026-11-20", "2026-11-27", "2026-12-04"):
            new, old = self.pair("second_run", today=day)
            panel = [b for b in of_type(new, "container") if "records" in b["block_id"]]
            old_records = [b for b in old if b["type"] == "section" and b.get("fields")
                           and ":trophy:" in b.get("text", {}).get("text", "")]
            if not panel:
                continue
            kids = panel[0]["child_blocks"]
            self.assertEqual(kids[0]["fields"], old_records[0]["fields"])
            self.assertEqual(old_records[0]["text"]["text"], fs.RECORDS_HEADING)


# --------------------------------------------------------------------------
# Quiet weeks, first weeks, crowds
# --------------------------------------------------------------------------

class TestEdgeWeeks(unittest.TestCase):
    def test_a_quiet_week_has_no_tiles_and_no_charts_but_is_valid(self):
        out, blocks = run_new("quiet")
        self.assertTrue(check_blocks(blocks))
        self.assertEqual(of_type(blocks, "layout"), [])
        self.assertEqual(of_type(blocks, "data_visualization"), [])
        self.assertIn("Nobody has logged", all_text(blocks))

    def test_a_first_week_without_history(self):
        rows = [r for r in make_rows() if r["name"] in ("Grace Lee", "Hiro Tanaka")]
        out = Scenario(rows).run()
        blocks = json.loads(out["message_json"])
        self.assertTrue(check_blocks(blocks))
        # steps and pushups: two activities to compare, even in a first week
        charts = of_type(blocks, "data_visualization")
        self.assertEqual([c["chart"]["type"] for c in charts], ["bar"])
        self.assertEqual([d["label"] for d in charts[0]["chart"]["series"][0]["data"]], ["Steps", "Pushups"])

    def test_one_activity_only_is_valid_and_has_no_chart(self):
        rows = [r for r in make_rows() if r["row_type"] == "step_users"]
        out = Scenario(rows, [earlier_run(rows, 7)]).run()
        blocks = json.loads(out["message_json"])
        self.assertTrue(check_blocks(blocks))
        self.assertEqual(of_type(blocks, "data_visualization"), [])               # one bar compares with nothing

    def test_a_crowd_of_badges_carries_on_in_more_carousels(self):
        people = fs.gather_people(make_rows())
        pids = sorted(people)
        earned = [(b, pids[:3]) for b in list(fs.BADGES.values())[:23] if b["family"] != "first"]
        carousels = fs.badge_carousels(people, earned)
        self.assertEqual([len(c["elements"]) for c in carousels][:-1], [10] * (len(carousels) - 1))
        self.assertEqual(sum(len(c["elements"]) for c in carousels), len(earned))
        for c in carousels:
            self.assertTrue(check_blocks([c]))

    def test_a_card_fits_however_many_people_earned_it(self):
        rows = make_rows()
        people = fs.gather_people(rows)
        for crowd in (1, 2, 5, 13):
            pids = sorted(people)[:crowd]
            for badge in fs.BADGES.values():
                card = fs.badge_card(people, badge, pids)
                check_card(card)
                self.assertTrue(card["body"]["text"].endswith("_{}_".format(badge["about"])), badge["id"])
        # a crowd is counted, not listed
        card = fs.badge_card(people, fs.BADGES["perfect_1"], sorted(people))
        self.assertIn(" more", card["body"]["text"])
        self.assertIn("{} people".format(len(people)), card["subtitle"]["text"])

    def test_long_names_never_overflow_a_card(self):
        people = {"U%08d" % i: {"name": "Maximilian-{}".format("X" * 60) + str(i)} for i in range(40)}
        card = fs.badge_card(people, fs.BADGES["streak_5"], sorted(people), mention=False)
        check_card(card)
        card = fs.badge_card(people, fs.BADGES["streak_5"], sorted(people), mention=True)
        check_card(card)
        self.assertIn("<@U", card["body"]["text"])

    def test_one_very_long_name_is_cut_not_refused(self):
        people = {"U00000001": {"name": "Z" * 400}}
        card = fs.badge_card(people, fs.BADGES["streak_5"], ["U00000001"])
        check_card(card)

    def test_a_card_has_the_kind_of_badge(self):
        people = fs.gather_people(make_rows())
        pid = sorted(people)[0]
        want = {"streak": "Daily streak", "steady": "Weekly streak", "perfect": "Attendance",
                "month": "Attendance", "explorer": "Variety", "allround": "Variety", "triple": "Variety",
                "weekend": "Variety", "founding": "Special"}
        for badge in fs.BADGES.values():
            if badge["family"] in want:
                self.assertTrue(fs.badge_card(people, badge, [pid])["subtitle"]["text"].startswith(
                    want[badge["family"]]), badge["id"])

    def test_emoji_in_a_table_cell_are_emoji(self):
        cell = fs.rich_cell(":plank-4: Plank", bold=True)
        self.assertEqual(cell["elements"][0]["elements"], [
            {"type": "emoji", "name": "plank-4"}, {"type": "text", "text": " Plank", "style": {"bold": True}}])
        cell = fs.rich_cell(":bicyclist::skin-tone-4: Cycling")
        self.assertEqual(cell["elements"][0]["elements"][0], {"type": "emoji", "name": "bicyclist::skin-tone-4"})
        self.assertEqual(fs.rich_cell("")["elements"][0]["elements"], [{"type": "text", "text": " "}])
        self.assertEqual(fs.raw_cell("   "), {"type": "raw_text", "text": " "})

    def test_every_emoji_the_step_uses_makes_a_valid_cell(self):
        for icon in fs.ICONS.values():
            cell = fs.rich_cell(icon + " Name")
            names = [e["name"] for e in cell["elements"][0]["elements"] if e["type"] == "emoji"]
            self.assertTrue(names, icon)
            self.assertEqual("".join(":{}:".format(n) for n in names), icon)

    def test_many_activities_stay_inside_the_tables_and_blocks_limits(self):
        rows = make_rows()
        extra = []
        for activity in ("run", "cycle", "dance", "journal", "write", "sketch", "paint", "chant", "hydrate"):
            for person in ("U01AAA001", "U01BBB002", "U01CCC003"):
                days = ["2026-11-0%d" % d for d in (9,)] + ["2026-11-10", "2026-11-12", "2026-11-13"]
                extra.append({"id": person, "name": dict((p[0], p[1]) for p in PEOPLE)[person],
                              "row_type": activity + "_users", "total": "30,40,35,50", "heatmap_dates": ",".join(days),
                              "first_seen": "2026-11-09", "personal_best_single_set": 0, "longest_streak": 1,
                              "leaderboard_optout": False})
        out = Scenario(rows + extra, [earlier_run(rows, 7)]).run()
        blocks = json.loads(out["message_json"])
        self.assertTrue(check_blocks(blocks))
        self.assertLessEqual(len(of_type(blocks, "table")[0]["rows"]), 1 + fs.WEEK_TOP_LINES)

    def test_tiles_in_rows_of_three(self):
        look = fs.parse_look("new")
        parts = [(":x:", i, "things") for i in range(8)]
        grid = fs.tile_layout(look, parts)
        self.assertEqual([len(r["items"]) for r in grid["rows"]], [3, 3, 2])
        check_blocks([grid])
        self.assertEqual(grid["rows"][0]["items"][0]["block"]["text"]["text"], ":x: *0*\nthings")
        self.assertEqual(fs.tile_layout(look, [("", 5, "people active")])["rows"][0]["items"][0]["block"]["text"]["text"],
                         "*5*\npeople active")


# --------------------------------------------------------------------------
# main() against a stand-in for Slack
# --------------------------------------------------------------------------

def slack_says(blocks, reject=()):
    """What Slack says about some blocks, as the messages of an invalid_blocks error (each fault with its
    json-pointer, from the top of the message, as Slack words them). Knows the rules Slack has taught this step:
      * a container may not set has_header_divider and be collapsible (it refused the first new-look post for that)
    and `reject`, the block types a stand-in workspace does not take: any block type, or "header_level" for a header
    with a level."""
    messages = []
    for index, block in enumerate(blocks):
        kind = block.get("type")
        if kind == "container" and block.get("has_header_divider") and block.get("is_collapsible"):
            messages.append("[ERROR] `has_header_divider` can only be set when `is_collapsible` is false "
                            "[json-pointer:/blocks/{}/has_header_divider]".format(index))
        elif kind in reject:
            messages.append("[ERROR] unsupported type: {} [json-pointer:/blocks/{}/type]".format(kind, index))
        elif kind == "header" and "level" in block and "header_level" in reject:
            messages.append("[ERROR] unknown property level [json-pointer:/blocks/{}/level]".format(index))
    return messages


class FakeSlack(object):
    """Stands in for requests.post: answers chat.postMessage and reactions.add, keeps every call.
    `refuse` is a list of answers for the first post calls (None is ok); after it, a post is judged by slack_says --
    so Slack's known rules are always enforced, and `reject` is a set of block types this workspace refuses."""

    def __init__(self, refuse=(), reject=()):
        self.calls = []
        self.refuse = list(refuse)
        self.reject = set(reject)

    def __call__(self, url, headers=None, json=None, timeout=None, **kwargs):          # noqa: A002
        self.calls.append({"url": url, "json": json, "headers": headers})
        answer = {"ok": True, "ts": "1700000000.000100"}
        if url.endswith("chat.postMessage"):
            refusal = self.refuse.pop(0) if self.refuse else None
            messages = slack_says(json["blocks"], self.reject)
            if refusal:
                answer = refusal
            elif messages:
                answer = {"ok": False, "error": "invalid_blocks", "response_metadata": {"messages": messages}}
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = answer
        return response

    def posts(self):
        return [c["json"] for c in self.calls if c["url"].endswith("chat.postMessage")]

    def reactions(self):
        return [c["json"] for c in self.calls if c["url"].endswith("reactions.add")]


# Slack refusing without saying which block (a pointer at a block no feature owns), and refusing for good
REFUSED = {"ok": False, "error": "invalid_blocks", "response_metadata": {
    "messages": ["[ERROR] unsupported type: layout [json-pointer:/blocks/3/type]"]}}
NEW_BLOCKS = {"layout", "data_visualization", "container", "carousel", "table", "header_level"}


def classic_rows(*activities):
    """The fixture channel's rows, kept to some activities."""
    return [r for r in make_rows() if r["row_type"].replace("_users", "") in activities]


class TestClassicNewLook(unittest.TestCase):
    """The classic all-time summary in the new look: Slack's rules, what it says, each feature
    alone, and a channel with little in it."""

    def classic(self, **extra):
        return run_new("classic", **extra)

    def old(self):
        return json.loads(TestPlainUnchanged.golden_for("classic")["message_json"])

    def test_valid_whole_and_with_each_feature_alone_or_taken_away(self):
        for extra in ({}, ) + tuple({"new_features": f} for f in fs.NEW_FEATURES) + \
                tuple({"new_features": "-" + f} for f in fs.NEW_FEATURES):
            out, blocks = self.classic(**extra)
            self.assertEqual(out["format_used"], "classic")
            self.assertTrue(check_blocks(blocks), extra)

    def test_every_new_block_is_there(self):
        out, blocks = self.classic()
        self.assertEqual(out["look_used"], "new")
        kinds = [b["type"] for b in blocks]
        for kind in ("header", "layout", "container", "carousel", "table"):
            self.assertIn(kind, kinds)
        self.assertNotIn("data_visualization", kinds)               # all-time: no week to draw
        self.assertEqual(kinds.count("table"), 1)
        self.assertEqual(blocks[0]["level"], 1)
        self.assertTrue(all(h["level"] == 2 for h in of_type(blocks, "header")[1:]))
        self.assertLessEqual(len(blocks), 50)

    def test_the_title_and_the_line_under_it_say_what_the_old_ones_say(self):
        _, new = self.classic()
        old = self.old()
        self.assertEqual(new[0]["text"]["text"], old[0]["text"]["text"].split("\n")[1].replace("*", ""))
        self.assertEqual(new[1], old[1])                                  # people, sessions, since

    def test_the_closing_is_the_same_two_blocks(self):
        _, new = self.classic()
        old = self.old()
        self.assertEqual(new[-3:], old[-3:])                              # divider, the weekend note, the ask

    def test_what_is_banked_is_the_same_lines(self):
        _, new = self.classic()
        panel = next(b for b in of_type(new, "container") if "banked" in b["block_id"])
        old_banked = next(b for b in self.old() if b["type"] == "section"
                          and b["text"]["text"].startswith("*Already banked*"))
        self.assertEqual(panel["title"]["text"], "Already banked")
        self.assertEqual(panel["child_blocks"][0]["text"]["text"],
                         old_banked["text"]["text"].split("\n", 1)[1])
        self.assertTrue(panel["has_header_divider"])
        self.assertNotIn("is_collapsible", panel)

    def test_up_next_is_a_card_for_each_headline_activity_nearest_first(self):
        _, new = self.classic()
        cards = of_type(new, "carousel")[0]["elements"]
        old_lines = [b["text"]["text"] for b in self.old() if b["type"] == "section"
                     and b["text"]["text"].count("\n") == 1 and "to go" in b["text"]["text"]]
        self.assertEqual(len(cards), len(old_lines))
        for card, line in zip(cards, old_lines):
            check_card(card)
            first, second = line.split("\n")
            # the bar and what is left: on two lines in a card, where ten squares and the words together
            # would wrap in a narrow one
            bar_part, rest = second.split("  *", 1)
            for code, char in fs.BAR_SQUARES.items():            # as characters: 200 allowed, shortcodes take 193
                bar_part = bar_part.replace(code, char)
            self.assertEqual(card["body"]["text"], bar_part + "\n*" + rest)
            self.assertIn("to go", card["body"]["text"])           # and nothing cut off
            self.assertIn(first.split("*")[1], card["title"]["text"])      # the activity
            self.assertIn(first.split("*")[-2], card["subtitle"]["text"])  # how far along, in per cent
        shares = [int(c["subtitle"]["text"].split("%")[0].split()[-1]) for c in cards]
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_the_other_activities_are_a_table_with_every_one_of_them(self):
        _, new = self.classic()
        table = of_type(new, "table")[0]
        rows = fs.summarize(make_rows())
        others = fs.classic_other_activities(rows)
        self.assertEqual(len(table["rows"]), 1 + len(others))
        self.assertEqual(table["rows"][0][0]["elements"][0]["elements"][0]["text"], "Activity")
        for activity, row in zip(others, table["rows"][1:]):
            self.assertIn(fs.TITLE[activity], all_text(row[0]))
            self.assertEqual(row[2]["text"], "{:,}".format(rows["sessions"][activity]))
            self.assertIn(fs.humanize(activity, rows["totals"][activity]), row[1]["text"])
        self.assertEqual(table["column_settings"][2]["align"], "right")
        self.assertIn(fs.CLASSIC_INVITE, all_text(new))

    def test_the_tiles_are_the_all_time_numbers(self):
        _, new = self.classic()
        grid = all_text(of_type(new, "layout"))
        facts = fs.summarize(make_rows())
        for needle in ("{:,}".format(facts["logs"]), str(facts["people"]),
                       "{:,}".format(facts["totals"]["step"]), "different activities", "km"):
            self.assertIn(needle, grid)
        cells = [i for row in of_type(new, "layout")[0]["rows"] for i in row["items"]]
        self.assertEqual(len(cells), len(fs.classic_tile_parts(facts, ":team:")))
        self.assertTrue(all(len(r["items"]) <= fs.TILES_PER_ROW for r in of_type(new, "layout")[0]["rows"]))

    def test_the_grid_is_labelled_for_what_it_holds(self):
        self.assertEqual(of_type(self.classic()[1], "layout")[0]["label"], "All time in numbers")
        self.assertEqual(of_type(run_new("second_run")[1], "layout")[0]["label"], "The week in numbers")

    def test_the_classic_summary_has_no_chart(self):
        # the pie of where the sessions went showed slices and no figures; the summary is all-time, so
        # there is no week to draw instead
        _, new = self.classic()
        self.assertEqual(of_type(new, "data_visualization"), [])
        self.assertNotIn("Where our sessions went", all_text(new))
        _, only_charts = self.classic(new_features="charts")
        self.assertEqual(of_type(only_charts, "data_visualization"), [])

    def test_charts_is_not_a_classic_feature_so_asking_for_only_that_is_the_old_summary(self):
        out, blocks = self.classic(new_features="charts")
        self.assertEqual(blocks, self.old())
        self.assertEqual(out["look_used"], "old")
        out, _ = self.classic(new_features="-charts")
        self.assertEqual(out["look_used"], "new")                       # the rest of the new look is there
        out, blocks = run_new("second_run", new_features="charts")      # but it is the weekly post's chart
        self.assertEqual(out["look_used"], "new")
        self.assertTrue(of_type(blocks, "data_visualization"))

    def test_each_feature_taken_away_goes_back_to_the_old_block(self):
        cases = (("tiles", "layout"), ("cards", "carousel"), ("tables", "table"), ("panels", "container"))
        for feature, kind in cases:
            _, blocks = self.classic(new_features="-" + feature)
            self.assertEqual(of_type(blocks, kind), [], feature)
            for other_feature, other in cases:
                if other_feature != feature:
                    self.assertTrue(of_type(blocks, other), "{} lost without {}".format(other, feature))
        _, blocks = self.classic(new_features="-headers")
        self.assertFalse(any("level" in h for h in of_type(blocks, "header")))

    def test_without_cards_and_tables_the_lines_are_the_old_lines(self):
        _, new = self.classic(new_features="headers,panels")
        old = self.old()
        text = all_text(new)
        for block in old:
            if block["type"] == "section" and ("to go" in block["text"]["text"]
                                               or block["text"]["text"].startswith(":seedling:")):
                body = block["text"]["text"]
                if body.startswith(":seedling:"):
                    body = body.split("\n", 1)[1]
                self.assertIn(body, text)

    def test_with_no_feature_but_headers_the_post_reads_as_the_old_one(self):
        _, new = self.classic(new_features="headers")
        texts = [b["text"]["text"] for b in new if b["type"] == "section"]
        old = [b["text"]["text"] for b in self.old() if b["type"] == "section"]
        for line in old[1:]:                                   # all but the title block
            if not line.startswith(("*Already banked*", ":dart:", ":seedling:")):
                self.assertIn(line, texts)

    def test_the_old_classic_is_still_the_old_classic(self):
        _, blocks = self.classic(look="old")
        self.assertEqual(blocks, self.old())

    def test_a_channel_with_only_the_headline_activities_has_no_table(self):
        out = Scenario(classic_rows("step", "pushup", "plank")).run(format="classic")
        blocks = json.loads(out["message_json"])
        self.assertTrue(check_blocks(blocks))
        self.assertEqual(of_type(blocks, "table"), [])
        self.assertEqual(of_type(blocks, "data_visualization"), [])
        self.assertNotIn(fs.CLASSIC_INVITE, all_text(blocks))

    def test_a_channel_that_has_only_walked(self):
        out = Scenario(classic_rows("step")).run(format="classic")
        blocks = json.loads(out["message_json"])
        self.assertTrue(check_blocks(blocks))
        self.assertEqual(of_type(blocks, "table"), [])
        self.assertEqual(len(of_type(blocks, "carousel")[0]["elements"]), 1)
        self.assertNotIn("different activities", all_text(blocks))

    def test_a_channel_with_no_headline_activity_has_no_cards_and_no_banked_panel(self):
        out = Scenario(classic_rows("yoga", "read", "swim", "meditate")).run(format="classic")
        blocks = json.loads(out["message_json"])
        self.assertTrue(check_blocks(blocks))
        self.assertEqual(of_type(blocks, "carousel"), [])
        self.assertEqual(of_type(blocks, "container"), [])
        self.assertEqual(len(of_type(blocks, "table")), 1)
        self.assertNotIn("Up next", all_text(blocks))
        self.assertNotIn("Already banked", all_text(blocks))
        # and the old look of the same channel is the old code's
        old = Scenario(classic_rows("yoga", "read", "swim", "meditate")).run(format="classic", look="old")
        self.assertNotIn("Up next", old["message_json"])

    def test_a_crowd_of_other_activities_stays_inside_the_tables_limits(self):
        rows = make_rows()
        for index, activity in enumerate(("run", "cycle", "dance", "journal", "write", "sketch", "paint",
                                          "chant", "hydrate", "stairs", "learn", "cardio", "workout")):
            rows.append({"id": "U01AAA001", "name": "Asha Rao", "row_type": activity + "_users",
                         "total": "10,20,30", "heatmap_dates": "2026-11-09,2026-11-10,2026-11-11",
                         "first_seen": "2026-11-09", "personal_best_single_set": 0, "longest_streak": 1,
                         "leaderboard_optout": False})
        out = Scenario(rows).run(format="classic")
        blocks = json.loads(out["message_json"])
        self.assertTrue(check_blocks(blocks))
        self.assertGreater(len(of_type(blocks, "table")[0]["rows"]), 15)

    def test_every_other_activity_the_step_knows_is_a_valid_table_row(self):
        facts = {"totals": {a: 1234 for a in fs.ICONS}, "sessions": {a: 7 for a in fs.ICONS},
                 "people": 3, "logs": 100, "since": "2026-08-03", "bests": {}}
        others = fs.classic_other_activities(facts)
        table = fs.others_table(facts, others)
        self.assertTrue(check_blocks([table]))
        self.assertEqual(len(table["rows"]), 1 + len(others))

    def test_a_card_fits_whatever_the_activity(self):
        facts = {"totals": {"step": 987654321}, "sessions": {"step": 5}, "people": 1, "logs": 5, "since": ""}
        for share, activity, value, spot in fs.classic_standing(facts):
            check_card(fs.milestone_card(facts, share, activity, value, spot))

    def test_a_cards_bar_leaves_room_for_the_words(self):
        for activity in ("step", "pushup", "plank"):
            for share in (0.0, 0.05, 0.5, 0.99, 1.0):
                text = fs.compact_bar(activity, share)
                self.assertEqual(len(text), fs.BAR_WIDTH)
                self.assertNotIn(":", text)
        facts = {"totals": {"step": 4999999, "pushup": 4999, "plank": 17999}, "sessions": {"step": 5},
                 "people": 1, "logs": 5, "since": ""}
        for share, activity, value, spot in fs.classic_standing(facts):
            card = fs.milestone_card(facts, share, activity, value, spot)
            self.assertIn("to go", card["body"]["text"])
            self.assertLess(len(card["body"]["text"]), 100)

    def test_the_card_says_almost_there_past_85_per_cent(self):
        facts = {"totals": {"step": 980000}, "sessions": {"step": 5}, "people": 1, "logs": 5, "since": ""}
        share, activity, value, spot = fs.classic_standing(facts)[0]
        self.assertGreaterEqual(share, 0.85)
        self.assertIn("almost there", fs.milestone_card(facts, share, activity, value, spot)["subtitle"]["text"])
        facts["totals"]["step"] = 760000
        share, activity, value, spot = fs.classic_standing(facts)[0]
        self.assertNotIn("almost there", fs.milestone_card(facts, share, activity, value, spot)["subtitle"]["text"])

    def test_the_team_emoji_is_the_one_in_the_title_and_the_first_tile(self):
        _, new = self.classic()
        team = [t for t in fs.TEAM_EMOJIS if t in new[0]["text"]["text"]]
        self.assertEqual(len(team), 1)
        self.assertIn(team[0], of_type(new, "layout")[0]["rows"][0]["items"][0]["block"]["text"]["text"])

    def test_block_ids_are_the_same_on_every_run_and_never_repeat(self):
        a = json.dumps(self.classic()[1], sort_keys=True)
        b = json.dumps(self.classic()[1], sort_keys=True)
        self.assertEqual(a, b)


class TestRefusedFeatures(unittest.TestCase):
    """Which feature Slack's error is about."""

    @classmethod
    def setUpClass(cls):
        cls.blocks = run_new("second_run")[1]
        cls.look = fs.parse_look("new")

    def where(self, kind):
        return next(i for i, b in enumerate(self.blocks) if b["type"] == kind)

    def error(self, *pointers):
        return "invalid_blocks: " + "; ".join("[ERROR] nope [json-pointer:{}]".format(p) for p in pointers)

    def test_the_block_at_the_pointer_says_the_feature(self):
        for kind, feature in (("layout", "tiles"), ("data_visualization", "charts"), ("container", "panels"),
                              ("carousel", "cards"), ("table", "tables")):
            error = self.error("/blocks/{}/type".format(self.where(kind)))
            self.assertEqual(fs.refused_features(error, self.blocks, self.look), [feature], kind)

    def test_a_header_with_a_level_is_the_headers_feature(self):
        self.assertEqual(fs.refused_features(self.error("/blocks/0/level"), self.blocks, self.look), ["headers"])

    def test_every_fault_slack_names_counts(self):
        error = self.error("/blocks/{}/has_header_divider".format(self.where("container")),
                           "/blocks/{}/type".format(self.where("layout")))
        self.assertEqual(fs.refused_features(error, self.blocks, self.look), ["panels", "tiles"])

    def test_the_exact_error_slack_gave(self):
        error = ("invalid_blocks: [ERROR] `has_header_divider` can only be set when `is_collapsible` is false "
                 "[json-pointer:/blocks/{0}/has_header_divider]; [ERROR] `has_header_divider` can only be set "
                 "when `is_collapsible` is false [json-pointer:/blocks/{0}/has_header_divider]"
                 .format(self.where("container")))
        self.assertEqual(fs.refused_features(error, self.blocks, self.look), ["panels"])

    def test_a_pointer_at_a_block_no_feature_owns_peels_in_order(self):
        for feature in fs.PEEL_ORDER:
            look = fs.parse_look("new", ",".join(f for f in fs.NEW_FEATURES
                                                 if f not in fs.PEEL_ORDER[:fs.PEEL_ORDER.index(feature)]))
            self.assertEqual(fs.refused_features(self.error("/blocks/1/text/text"), self.blocks, look), [feature])

    def test_no_pointer_at_all_peels_in_order(self):
        self.assertEqual(fs.refused_features("invalid_blocks", self.blocks, self.look), ["panels"])
        self.assertEqual(fs.refused_features("invalid_blocks", self.blocks, self.look.without(["panels"])), ["tiles"])

    def test_a_pointer_past_the_end_or_at_a_feature_already_off_is_ignored(self):
        error = self.error("/blocks/99/type", "/blocks/{}/type".format(self.where("layout")))
        self.assertEqual(fs.refused_features(error, self.blocks, self.look.without(["tiles"])), ["panels"])

    def test_peel_order_names_every_feature_once(self):
        self.assertEqual(sorted(fs.PEEL_ORDER), sorted(fs.NEW_FEATURES))

    def test_without_is_a_fresh_look(self):
        look = fs.parse_look("new")
        look.block_id("tile")
        smaller = look.without(["tiles", "charts"])
        self.assertEqual(set(smaller.features), set(fs.NEW_FEATURES) - {"tiles", "charts"})
        self.assertEqual(smaller.block_id("tile"), "fs_tile_1")
        self.assertTrue(look.on("tiles"))


class TestPosting(unittest.TestCase):
    def post(self, slack, scenario="second_run", **extra):
        spec = dict((n, (s, e)) for n, s, e in scenarios())[scenario]
        fields = dict(spec[1], dry_run=False, slack_bot_token="xoxb-test", channel_id="C123")
        fields.update(extra)
        with mock.patch.object(fs.requests, "post", side_effect=slack):
            return spec[0].run(**fields), spec[0]

    def old_golden(self, name="second_run"):
        return json.loads(TestPlainUnchanged.golden_for(name)["message_json"])

    def test_the_new_look_is_posted(self):
        slack = FakeSlack()
        out, _ = self.post(slack)
        self.assertTrue(out["ok"] and out["posted"])
        self.assertEqual(out["look_used"], "new")
        self.assertEqual(out["error"], "")
        self.assertEqual(len(slack.posts()), 1)
        sent = slack.posts()[0]
        self.assertEqual(sent["channel"], "C123")
        self.assertTrue(of_type(sent["blocks"], "layout"))
        self.assertEqual(sent["text"], out["message_text"])
        self.assertTrue(sent["text"])
        self.assertEqual(json.loads(out["message_json"]), sent["blocks"])

    def test_the_new_look_gets_past_the_rules_slack_has_taught_this_step(self):
        # the first live post was refused for a container that set has_header_divider and was collapsible
        for name in RUNS:
            slack = FakeSlack()
            out, _ = self.post(slack, scenario=name)
            self.assertEqual(len(slack.posts()), 1, name)
            self.assertEqual(out["look_used"], "new", name)
            self.assertEqual(out["error"], "", name)
            for block in of_type(slack.posts()[0]["blocks"], "container"):
                self.assertFalse(block.get("has_header_divider") and block.get("is_collapsible"), name)

    def test_the_old_look_is_posted_when_asked_for(self):
        slack = FakeSlack()
        out, _ = self.post(slack, look="old")
        self.assertEqual(out["look_used"], "old")
        self.assertEqual(len(slack.posts()), 1)
        self.assertEqual(slack.posts()[0]["blocks"], self.old_golden())

    def test_slack_refuses_one_feature_and_the_rest_of_the_new_look_is_posted(self):
        slack = FakeSlack(reject={"layout"})
        out, _ = self.post(slack)
        self.assertTrue(out["ok"] and out["posted"])
        self.assertEqual(len(slack.posts()), 2)
        first, second = slack.posts()
        self.assertTrue(of_type(first["blocks"], "layout"))
        self.assertFalse(of_type(second["blocks"], "layout"))
        for kept in ("carousel", "table", "container", "data_visualization"):
            self.assertTrue(of_type(second["blocks"], kept), kept)
        self.assertEqual(of_type(second["blocks"], "header")[0]["level"], 1)
        self.assertEqual(out["look_used"], "new (without tiles)")
        self.assertEqual(second["text"], first["text"])
        self.assertEqual(json.loads(out["message_json"]), second["blocks"])
        self.assertIn("new look refused by Slack", out["error"])
        self.assertIn("unsupported type: layout", out["error"])            # which block, from Slack itself
        self.assertIn("trying without tiles", out["error"])
        self.assertTrue(check_blocks(second["blocks"]))

    def test_every_block_slack_names_goes_in_one_go(self):
        slack = FakeSlack(reject={"layout", "data_visualization"})
        out, _ = self.post(slack)
        self.assertTrue(out["ok"])
        self.assertEqual(len(slack.posts()), 2)
        self.assertEqual(out["look_used"], "new (without tiles, charts)")
        self.assertIn("trying without tiles, charts", out["error"])

    def test_a_workspace_that_takes_no_new_block_ends_at_the_old_post_to_the_letter(self):
        slack = FakeSlack(reject=NEW_BLOCKS)
        out, _ = self.post(slack)
        self.assertTrue(out["ok"] and out["posted"])
        self.assertEqual(out["look_used"], "old")
        self.assertLessEqual(len(slack.posts()), len(fs.NEW_FEATURES) + 1)
        # the last post wore the team emoji the first one did, so it is the pinned old post
        self.assertEqual(slack.posts()[-1]["blocks"], self.old_golden())
        self.assertEqual(json.loads(out["message_json"]), self.old_golden())
        self.assertEqual(out["error"].count("new look refused by Slack"), len(slack.posts()) - 1)

    def test_each_feature_can_be_the_only_one_refused(self):
        for block, feature in (("layout", "tiles"), ("data_visualization", "charts"), ("container", "panels"),
                               ("carousel", "cards"), ("table", "tables"), ("header_level", "headers")):
            slack = FakeSlack(reject={block})
            out, _ = self.post(slack)
            self.assertTrue(out["ok"], block)
            self.assertEqual(out["look_used"], "new (without {})".format(feature), block)
            self.assertEqual(len(slack.posts()), 2, block)

    def test_the_refusal_costs_nothing_of_the_old_look_either(self):
        slack = FakeSlack(reject=NEW_BLOCKS)
        _, scenario = self.post(slack)
        runs, _ = fs.FileSnapshot(scenario.snapshot).load()
        self.assertEqual(runs[-1]["d"], TODAY.isoformat())

    def test_the_retry_keeps_the_team_emoji(self):
        slack = FakeSlack(reject={"layout"})
        self.post(slack)
        first, second = [all_text(p["blocks"]) for p in slack.posts()]
        team = [t for t in fs.TEAM_EMOJIS if t in first]
        self.assertEqual(len(team), 1)
        self.assertIn(team[0], second)

    def test_a_refusal_with_no_pointer_takes_the_features_off_one_at_a_time(self):
        slack = FakeSlack(refuse=[{"ok": False, "error": "invalid_blocks"}] * 2)
        out, _ = self.post(slack)
        self.assertTrue(out["ok"])
        self.assertEqual(len(slack.posts()), 3)
        self.assertEqual(out["look_used"], "new (without tiles, panels)")
        self.assertIn("new look refused by Slack (invalid_blocks); trying without panels", out["error"])
        self.assertIn("trying without tiles", out["error"])

    def test_slack_refusing_everything_is_an_error_after_the_old_post_is_tried(self):
        slack = FakeSlack(refuse=[REFUSED] * 20)
        out, _ = self.post(slack)
        self.assertFalse(out["ok"])
        self.assertFalse(out["posted"])
        self.assertEqual(len(slack.posts()), len(fs.NEW_FEATURES) + 1)       # the new look, each feature off, the old
        self.assertEqual(out["look_used"], "old")
        self.assertIn("invalid_blocks", out["error"])
        self.assertEqual(out["error"].count("trying without"), len(fs.NEW_FEATURES))
        self.assertFalse(out["snapshot_saved"])

    def test_the_old_look_refused_is_just_an_error(self):
        slack = FakeSlack(refuse=[REFUSED])
        out, _ = self.post(slack, look="old")
        self.assertFalse(out["ok"])
        self.assertEqual(len(slack.posts()), 1)
        self.assertIn("invalid_blocks", out["error"])

    def test_other_errors_are_not_retried(self):
        slack = FakeSlack(refuse=[{"ok": False, "error": "channel_not_found"}])
        out, _ = self.post(slack)
        self.assertFalse(out["ok"])
        self.assertEqual(len(slack.posts()), 1)
        self.assertEqual(out["error"], "channel_not_found")                 # as it always was: no extra words

    def test_the_reaction_goes_on_whichever_look_was_posted(self):
        for fake in (FakeSlack(), FakeSlack(reject={"layout"}), FakeSlack(reject=NEW_BLOCKS)):
            out, _ = self.post(fake)
            self.assertEqual(len(fake.reactions()), 1, out["look_used"])
            self.assertEqual(fake.reactions()[0]["timestamp"], "1700000000.000100")

    def test_the_snapshot_is_saved_after_a_post_and_not_after_a_failure(self):
        slack = FakeSlack()
        out, scenario = self.post(slack)
        self.assertTrue(out["snapshot_saved"])
        runs, error = fs.FileSnapshot(scenario.snapshot).load()
        self.assertIsNone(error)
        self.assertEqual(runs[-1]["d"], TODAY.isoformat())
        self.assertIn("b", runs[-1])
        slack = FakeSlack(refuse=[REFUSED] * 20)
        out, _ = self.post(slack)
        self.assertFalse(out["snapshot_saved"])

    def test_the_snapshot_is_the_same_whichever_look(self):
        saved = []
        for look in ("new", "old"):
            out, scenario = self.post(FakeSlack(), look=look)
            runs, _ = fs.FileSnapshot(scenario.snapshot).load()
            saved.append(runs[-1])
        self.assertEqual(saved[0], saved[1])

    def test_a_dry_run_posts_nothing_in_either_look_or_format(self):
        for name in ("second_run", "classic"):
            for look in ("new", "old"):
                slack = FakeSlack()
                spec = dict((n, (s, e)) for n, s, e in scenarios())[name]
                with mock.patch.object(fs.requests, "post", side_effect=slack):
                    out = spec[0].run(**dict(spec[1], look=look))
                self.assertTrue(out["ok"])
                self.assertEqual(slack.calls, [])
                self.assertEqual(out["look_used"], look)
                self.assertTrue(json.loads(out["message_json"]))

    def test_a_thread_reply_keeps_its_thread(self):
        slack = FakeSlack(reject={"layout", "table"})
        self.post(slack, thread_ts="1699999999.000200")
        self.assertGreaterEqual(len(slack.posts()), 2)
        self.assertEqual(set(p["thread_ts"] for p in slack.posts()), {"1699999999.000200"})

    def test_classic_is_posted_in_the_look_asked_for(self):
        slack = FakeSlack()
        out, _ = self.post(slack, scenario="classic", look="old")
        self.assertTrue(out["ok"])
        self.assertEqual(out["look_used"], "old")
        self.assertEqual(len(slack.posts()), 1)
        self.assertEqual(slack.posts()[0]["blocks"], self.old_golden("classic"))
        slack = FakeSlack()
        out, _ = self.post(slack, scenario="classic")                     # blank: the new look
        self.assertEqual(out["look_used"], "new")
        self.assertEqual(out["error"], "")
        self.assertEqual(len(slack.posts()), 1)
        self.assertTrue(of_type(slack.posts()[0]["blocks"], "layout"))
        self.assertEqual(json.loads(out["message_json"]), slack.posts()[0]["blocks"])

    def test_a_refused_feature_of_the_classic_summary_costs_only_that_feature(self):
        slack = FakeSlack(reject={"layout"})
        out, _ = self.post(slack, scenario="classic")
        self.assertTrue(out["ok"] and out["posted"])
        self.assertEqual(len(slack.posts()), 2)
        self.assertEqual(out["look_used"], "new (without tiles)")
        first, second = slack.posts()
        self.assertTrue(of_type(first["blocks"], "layout"))
        self.assertFalse(of_type(second["blocks"], "layout"))
        for kept in ("carousel", "table", "container"):
            self.assertTrue(of_type(second["blocks"], kept), kept)
        self.assertIn("trying without tiles", out["error"])
        first_text, second_text = all_text(first["blocks"]), all_text(second["blocks"])
        team = [t for t in fs.TEAM_EMOJIS if t in first_text]
        self.assertEqual(len(team), 1)
        self.assertIn(team[0], second_text)                                   # the retry keeps the team emoji

    def test_a_workspace_that_takes_no_new_block_gets_the_classic_summary_to_the_letter(self):
        slack = FakeSlack(reject=NEW_BLOCKS)
        out, _ = self.post(slack, scenario="classic")
        self.assertTrue(out["ok"])
        self.assertEqual(out["look_used"], "old")
        self.assertLessEqual(len(slack.posts()), len(fs.NEW_FEATURES) + 1)
        self.assertEqual(slack.posts()[-1]["blocks"], self.old_golden("classic"))
        self.assertEqual(json.loads(out["message_json"]), self.old_golden("classic"))

    def test_the_classic_summary_posts_once_with_the_notification_text_it_always_had(self):
        for look in ("new", "old"):
            slack = FakeSlack()
            out, _ = self.post(slack, scenario="classic", look=look)
            self.assertEqual(slack.posts()[0]["text"], TestPlainUnchanged.golden_for("classic")["message_text"])
            self.assertTrue(out["snapshot_saved"])

    def test_a_few_features_asked_for_and_one_refused_says_what_went(self):
        slack = FakeSlack(reject={"layout"})
        out, _ = self.post(slack, new_features="tiles,cards,tables")
        self.assertEqual(out["look_used"], "new (without tiles)")
        self.assertTrue(of_type(slack.posts()[-1]["blocks"], "carousel"))
        self.assertFalse(of_type(slack.posts()[-1]["blocks"], "container"))        # never asked for

    def test_post_reports_slacks_own_words(self):
        slack = FakeSlack(refuse=[REFUSED])
        with mock.patch.object(fs.requests, "post", side_effect=slack):
            sent, error, ts = fs.post("xoxb", "C1", "t", [{"type": "divider"}])
        self.assertFalse(sent)
        self.assertTrue(error.startswith("invalid_blocks: "))
        self.assertIn("[json-pointer:/blocks/3/type]", error)
        self.assertEqual(ts, "")
        slack = FakeSlack(refuse=[{"ok": False, "error": "not_in_channel"}])
        with mock.patch.object(fs.requests, "post", side_effect=slack):
            self.assertEqual(fs.post("xoxb", "C1", "t", [])[1], "not_in_channel")


def write_preview():
    """The fixture channel's weekly and classic posts in each look, as {"blocks": [...]} -- what Block Kit
    Builder takes."""
    for name, stem in (("second_run", "preview_{}_look.json"), ("classic", "preview_classic_{}_look.json")):
        spec = dict((n, (s, e)) for n, s, e in scenarios())[name]
        for look in ("new", "old"):
            out = spec[0].run(**dict(spec[1], look=look))
            path = os.path.join(HERE, "testdata", stem.format(look))
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"blocks": json.loads(out["message_json"])}, handle, indent=2, ensure_ascii=False)
            print("wrote", path)


if __name__ == "__main__":
    if "--regen-golden" in sys.argv:
        regenerate_golden()
    elif "--write-preview" in sys.argv:
        write_preview()
    else:
        unittest.main()
