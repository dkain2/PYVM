"""
Tests for monthly_summary.py. Run them before and after any change, so a change that breaks the email is caught
here and not in two hundred inboxes:

    python3 test_monthly_summary.py                  # all of them
    python3 test_monthly_summary.py -v               # with the name of each
    python3 test_monthly_summary.py --write-preview  # write testdata/preview.html: the fixture month with every
                                                     # section, to open in a browser
    python3 test_monthly_summary.py --regen-golden   # rewrite testdata/golden_*.html (only after a change to the
                                                     # email you MEANT to make -- see TestGolden)

Nothing here touches the network, Slack, Azure or Workato: every run reads the fixture from a local file, with no
tokens, so the brief is the template and nobody is looked up.

THE GROUPS
    TestGolden        the email for a month with NO weekly challenges in it is pinned, byte for byte, to what the
                      step built before the Challengers section existed -- in the default order, in an explicit
                      order, and with names off. A month nobody took a challenge in must look exactly as it did.
    TestChallengeMath challengers_of(): which weeks belong to the month, who took on what, what was cleared, the
                      people who opted out, a replaced post, an acceptance someone left, names off
    TestChallengersSection  the section itself: its banner, the figures, the podium, the list, its order, aliases
    TestChallengersInMain   main() end to end with challenge rows in the local file: the section, the outputs,
                      section_order without it, a month with none

THE FIXTURE
    make_rows() is a small channel over September and October 2026: eight people logging steps, pushups, plank and
    yoga, one of them opted out of the leaderboards, two game players. challenge_rows() adds four weekly-challenge
    posts, their acceptance rows and the entries spotter would have written on each person's row.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import monthly_summary as ms  # noqa: E402

TESTDATA = os.path.join(HERE, "testdata")
TODAY = "2026-11-01"                     # the 1st: month = previous is October 2026, finished
PEOPLE = [
    ("U001", "Priya Sharma"), ("U002", "Jack Brown"), ("U003", "Sam Lee"),
    ("U004", "Ana Costa"), ("U005", "Ravi Kumar"), ("U006", "Mei Chen"),
    ("U007", "Tom Hill"), ("U008", "Opted Out"),
]


def _days(first, count, every=1):
    start = date.fromisoformat(first)
    return [(start + timedelta(days=i * every)).isoformat() for i in range(count)]


def activity_row(pid, name, activity, amounts, days, **more):
    row = {"row_type": activity + "_users", "id": pid, "name": name,
           "total": ",".join(str(a) for a in amounts), "heatmap_dates": ",".join(days),
           "first_seen": days[0] if days else "", "updated_at": days[-1] if days else "",
           "longest_streak": 3, "leaderboard_optout": False, "is_private": False,
           "personal_best_single_set": max(amounts) if amounts else 0, "golden_dates": ""}
    row.update(more)
    return row


def make_rows():
    """A small channel, deterministic: September and October 2026."""
    rows = []
    for n, (pid, name) in enumerate(PEOPLE):
        optout = pid == "U008"
        sept = _days("2026-09-{:02d}".format(2 + n), 8, 3)
        octo = _days("2026-10-{:02d}".format(1 + n), 10 - n % 3, 2)
        days = sept + octo
        rows.append(activity_row(pid, name, "step", [6000 + 500 * n + 37 * i for i in range(len(days))],
                                 days, leaderboard_optout=optout))
        if n % 2 == 0:
            rows.append(activity_row(pid, name, "pushup", [20 + n + i for i in range(len(octo))], octo,
                                     leaderboard_optout=optout))
        if n % 3 == 0:
            rows.append(activity_row(pid, name, "plank", [60 + 5 * i for i in range(len(octo))], octo,
                                     leaderboard_optout=optout))
        if n in (1, 4, 5):
            rows.append(activity_row(pid, name, "yoga", [30] * 6, _days("2026-10-03", 6, 4)))
    for row_type, pid, name, score, played in (
            ("math_add_user", "U001", "Priya Sharma", 14, 12),
            ("math_add_user", "U003", "Sam Lee", 11, 7),
            ("pairs_memory_user", "U002", "Jack Brown", 9, 1250),
            ("pairs_memory_user", "U004", "Ana Costa", 0, 3),        # played, never scored
            ("pairs_memory_user", "U008", "Opted Out", 20, 40)):     # left out
        rows.append({"row_type": row_type, "id": pid, "name": name, "total": 95,
                     "personal_best_single_set": score, "total_planks": played,
                     "updated_at": "2026-10-20", "leaderboard_optout": pid == "U008"})
    return rows


# ----------------------------------------------------------- the weekly challenges

def post_row(week, status="closed", channel="C0CHAN"):
    return {"row_type": "weekly_challenge", "id": "{}-1700000000".format(week), "week_key": week,
            "status": status, "slack_channel_id": channel}


def entry(post_id, week, goal, state, kind=""):
    monday = date.fromisoformat(week)
    out = {"post": post_id + (":" + kind if kind else ""), "from": week,
           "to": (monday + timedelta(days=6)).isoformat(), "goal": goal, "text": "goal", "base": 100,
           "state": state}
    if kind:
        out["kind"] = kind
    return out


def accept_row(post_id, key, pid, name, status="in", content=""):
    return {"row_type": "weekly_accept", "id": post_id, "grant_type": key, "group_id": pid,
            "member_name": name, "status": status, "content": content}


# (week, person, challenge, goal, state). Weeks of October 2026: the Mondays are 28 Sep (ends Sun 4 Oct,
# so it is October's), 5, 12 and 19 Oct; the week of 26 Oct ends Sun 1 Nov, so it is November's.
TAKEN = [
    ("2026-09-21", "U001", "pushup", 100, "done"),       # ends 27 Sep: September's, not counted
    ("2026-09-28", "U001", "pushup", 100, "done"),
    ("2026-09-28", "U002", "yoga", 120, "missed"),
    ("2026-09-28", "U003", "step", 40000, "done"),
    ("2026-10-05", "U001", "pushup", 120, "done"),
    ("2026-10-05", "U001", "plank", 600, "done"),
    ("2026-10-05", "U003", "pushup", 80, "missed"),
    ("2026-10-05", "U008", "pushup", 80, "done"),        # opted out: left out of every figure
    ("2026-10-12", "U001", "pushup", 140, "done"),
    ("2026-10-12", "U002", "yoga", 120, "done"),
    ("2026-10-12", "U003", "step", 45000, "done"),
    ("2026-10-12", "U005", "yoga", 90, "done"),
    ("2026-10-19", "U001", "pushup", 160, "missed"),
    ("2026-10-19", "U002", "yoga", 140, "done"),
    ("2026-10-19", "U003", "step", 50000, "done"),
    ("2026-10-19", "U005", "yoga", 100, "done"),
    ("2026-10-19", "U004", "iadd_score", 12, "done"),
    ("2026-10-26", "U001", "pushup", 160, "done"),       # ends 1 Nov: November's, not counted
]


def challenge_rows(rows, taken=TAKEN, extra_accepts=()):
    """Post rows, acceptance rows, and each person's entries written into `content` on their row of the
    activity (or game). Rows that do not exist yet are made, as a first log would make them."""
    rows = [dict(r) for r in rows]
    weeks = sorted({week for week, *_rest in taken})
    out = [post_row(week) for week in weeks]
    by_row = {}
    for week, pid, key, goal, state in taken:
        post_id = "{}-1700000000".format(week)
        kind = key.rsplit("_", 1)[1] if key.endswith(("_plays", "_score")) else ""
        row_type = ms.CHALLENGE_ROW_TYPE.get(key)
        made = entry(post_id, week, goal, state, kind)
        by_row.setdefault((row_type, pid), []).append(made)
        name = dict(PEOPLE).get(pid, pid)
        first = dict(made, state="open")
        out.append(accept_row(post_id, key, pid, name, content=json.dumps(first)))
    for (row_type, pid), entries in by_row.items():
        found = next((r for r in rows if r["row_type"] == row_type and r["id"] == pid), None)
        if found is None:
            found = {"row_type": row_type, "id": pid, "name": dict(PEOPLE).get(pid, pid),
                     "leaderboard_optout": pid == "U008"}
            rows.append(found)
        found["content"] = json.dumps({"wc": entries, "wc_counts": {"accepted": len(entries),
                                                                    "cleared": 1}})
    return rows + out + list(extra_accepts)


# ----------------------------------------------------------------- running the step

class Fixture(object):
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="monthly_summary_test_")

    def write(self, name, rows):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle)
        return path

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def run(path, **more):
    payload = {"local_data_file": path, "today": TODAY, "month": "previous",
               "skip_email_lookup": True, "dry_run": True, "channel_name": "plank-you-very-much"}
    payload.update(more)
    return ms.main(payload)


GOLDEN_CASES = {
    "default": {},
    "ordered": {"section_order": "tiles, brief, checkins, boards, records, games, join"},
    "no_names": {"show_names": False},
}


def golden_path(case):
    return os.path.join(TESTDATA, "golden_{}.html".format(case))


class TestGolden(unittest.TestCase):
    """A month with no weekly challenges reads exactly as the step built it before the section existed."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = Fixture()
        cls.path = cls.fixture.write("rows.json", make_rows())

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def test_unchanged(self):
        for case, more in GOLDEN_CASES.items():
            with self.subTest(case=case):
                result = run(self.path, **more)
                self.assertTrue(result["ok"], result["error"])
                with open(golden_path(case), "r", encoding="ascii") as handle:
                    golden = handle.read()
                self.assertEqual(result["html"], golden,
                                 "the {} email changed; if that was meant, --regen-golden".format(case))


class TestChallengeMath(unittest.TestCase):
    """challengers_of(): the month's weekly challenges, in figures."""

    def figures(self, taken=TAKEN, extra_accepts=(), show_names=True, start="2026-10-01",
                end="2026-10-31", finished=True):
        rows = challenge_rows(make_rows(), taken, extra_accepts)
        posts, accepts, entry_rows = ms.split_challenge_rows(rows)
        return ms.challengers_of(posts, accepts, entry_rows, rows, date.fromisoformat(start),
                                 date.fromisoformat(end), finished, show_names)

    def test_weeks_by_their_sunday(self):
        got = self.figures()
        # 28 Sep (ends 4 Oct), 5, 12 and 19 Oct: four weeks. 21 Sep and 26 Oct belong to other months.
        self.assertEqual(got["weeks"], 4)

    def test_counts_leave_out_the_opted_out(self):
        got = self.figures()
        # 17 October-month acceptances in TAKEN less the opted-out one's
        self.assertEqual(got["taken"], 15)
        self.assertEqual(got["cleared"], 12)
        self.assertEqual(got["people"], 5)
        self.assertNotIn("U008", [p["id"] for p in got["top"]])

    def test_top_challengers(self):
        got = self.figures()
        top = [(p["name"], p["cleared"], p["taken"]) for p in got["top"]]
        # Priya 4 of 5; Sam 3 of 4 and Jack 2 of 3 -- Ravi 2 of 2 is a clean sweep but fewer than Sam
        self.assertEqual(top[0], ("Priya Sharma", 4, 5))
        self.assertEqual(top[1], ("Sam Lee", 3, 4))
        # Ravi and Jack both cleared 2: fewer taken on (a better rate) goes first
        self.assertEqual(top[2], ("Ravi Kumar", 2, 2))

    def test_sweep(self):
        got = self.figures()
        self.assertEqual([p["name"] for p in got["sweep"]], ["Ravi Kumar", "Ana Costa"])

    def test_by_challenge(self):
        got = self.figures()
        lines = [(c["key"], c["taken"], c["cleared"]) for c in got["challenges"]]
        # yoga and pushups were both taken on 5 times; yoga was cleared more often
        self.assertEqual(lines[:2], [("yoga", 5, 4), ("pushup", 5, 3)])
        self.assertIn(("step", 3, 3), lines)
        self.assertIn(("iadd_score", 1, 1), lines)

    def test_left_the_challenge(self):
        # Someone who opted out of a challenge (status out) took nothing on
        extra = [accept_row("2026-10-12-1700000000", "plank", "U006", "Mei Chen", status="out")]
        got = self.figures(extra_accepts=extra)
        self.assertEqual(got["taken"], 15)
        self.assertNotIn("U006", [p["id"] for p in got["top"]])

    def test_waiting_acceptance_counts_as_taken(self):
        # Accepted an activity never logged: the entry waits on the acceptance row; taken, not cleared
        waiting = json.dumps(entry("2026-10-12-1700000000", "2026-10-12", 60, "open"))
        extra = [accept_row("2026-10-12-1700000000", "squat", "U007", "Tom Hill", content=waiting)]
        got = self.figures(extra_accepts=extra)
        self.assertEqual(got["taken"], 16)
        self.assertEqual(got["cleared"], 12)
        self.assertEqual(got["people"], 6)

    def test_replaced_post_is_not_counted(self):
        rows = challenge_rows(make_rows())
        for row in rows:
            if row.get("row_type") == "weekly_challenge" and row["week_key"] == "2026-10-19":
                row["status"] = "replaced"
        posts, accepts, entry_rows = ms.split_challenge_rows(rows)
        got = ms.challengers_of(posts, accepts, entry_rows, rows, date(2026, 10, 1), date(2026, 10, 31),
                                True, True)
        self.assertEqual(got["weeks"], 3)
        self.assertEqual(got["taken"], 10)

    def test_month_so_far_counts_the_week_in_progress(self):
        got = self.figures(start="2026-10-01", end="2026-10-14", finished=False)
        # 28 Sep, 5 Oct and the week of 12 Oct, which has begun; not 19 Oct
        self.assertEqual(got["weeks"], 3)
        self.assertEqual(got["taken"], 10)

    def test_no_names(self):
        got = self.figures(show_names=False)
        self.assertEqual(got["top"], [])
        self.assertEqual(got["sweep"], [])
        self.assertEqual(got["taken"], 15)

    def test_nothing_taken(self):
        got = self.figures(taken=[])
        self.assertEqual(got["taken"], 0)


class TestChallengersSection(unittest.TestCase):

    def ctx(self, show_names=True):
        rows = challenge_rows(make_rows())
        posts, accepts, entry_rows = ms.split_challenge_rows(rows)
        figures = ms.challengers_of(posts, accepts, entry_rows, rows, date(2026, 10, 1),
                                    date(2026, 10, 31), True, show_names)
        return {"challengers": figures, "photos": None, "show_names": show_names,
                "start": date(2026, 10, 1)}

    def test_band_without_a_banner(self):
        page = ms.challengers_html(self.ctx(), {})
        self.assertIn("Challengers", page)
        self.assertIn(ms.OTHER_SECTIONS["challengers"], page)
        self.assertIn("Priya Sharma", page)
        self.assertIn("4 of 5", page)

    def test_banner(self):
        url = "https://example.com/challengers.png"
        page = ms.challengers_html(self.ctx(), {"challengers": url})
        self.assertIn(url, page)

    def test_names_off(self):
        page = ms.challengers_html(self.ctx(show_names=False), {})
        self.assertNotIn("Priya", page)
        self.assertIn("15", page)

    def test_empty(self):
        self.assertEqual(ms.challengers_html({"challengers": None}, {}), "")
        self.assertEqual(ms.challengers_html({"challengers": {"taken": 0}}, {}), "")

    def test_order_and_aliases(self):
        self.assertIn("challengers", ms.DEFAULT_ORDER)
        for word in ("challenger", "Challengers", "weekly challenges", "challenges"):
            order, unknown, _left = ms.section_order("tiles, " + word)
            self.assertEqual(order, ["tiles", "challengers"], word)
            self.assertEqual(unknown, [])

    def test_banner_key(self):
        for key in ("challengers", "challenger", "weekly_challenge"):
            images, warnings = ms.resolve_images("", {key: "https://example.com/c.png"})
            self.assertEqual(images.get("challengers"), "https://example.com/c.png", key)
            self.assertEqual(warnings, [])


class TestChallengersInMain(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fixture = Fixture()
        cls.with_challenges = cls.fixture.write("challenges.json", challenge_rows(make_rows()))
        cls.without = cls.fixture.write("rows.json", make_rows())

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def test_section_and_outputs(self):
        result = run(self.with_challenges)
        self.assertTrue(result["ok"], result["error"])
        self.assertIn("Challengers", result["html"])
        self.assertEqual(result["challenges_taken"], 15)
        self.assertEqual(result["challenges_cleared"], 12)
        self.assertEqual(result["challengers"], 5)
        self.assertIn("challengers", result["sections"].split(","))
        # after the boards, before the records
        self.assertLess(result["html"].index("On the boards"), result["html"].index("Challengers"))
        self.assertLess(result["html"].index("Challengers"), result["html"].index("Channel records"))

    def test_left_out_of_the_order(self):
        result = run(self.with_challenges, section_order="tiles, boards, records")
        self.assertNotIn("Challengers", result["html"])
        self.assertIn("left out of the email: ", result["error"])

    def test_no_challenges(self):
        result = run(self.without)
        self.assertNotIn("Challengers", result["html"])
        self.assertEqual(result["challenges_taken"], 0)

    def test_channel_filter(self):
        result = run(self.with_challenges, channel_id="C0OTHER", recipients_from="active")
        self.assertNotIn("Challengers", result["html"])
        result = run(self.with_challenges, channel_id="C0CHAN", recipients_from="active")
        self.assertIn("Challengers", result["html"])

    def test_banner_from_inputs(self):
        url = "https://example.com/challengers.png"
        result = run(self.with_challenges, section_image_urls=json.dumps({"challengers": url}))
        self.assertIn(url, result["html"])
        self.assertNotIn("no section called", result["error"])


class TestUnits(unittest.TestCase):
    """A figure standing on its own says what it counts (a podium, the records, the milestones)."""

    def test_every_counted_activity_has_a_unit(self):
        counted = [a for a, info in ms.ACTIVITIES.items() if info[3] == "count"]
        self.assertEqual(sorted(a for a in counted if a not in ms.UNITS), [])

    def test_figures(self):
        self.assertEqual(ms.with_unit("read", 200), "200 pages")
        self.assertEqual(ms.with_unit("pushup", 245), "245 reps")
        self.assertEqual(ms.with_unit("squat", 1), "1 rep")
        self.assertEqual(ms.with_unit("step", 1240000, short=True), "1.24M steps")
        self.assertEqual(ms.with_unit("stairs", 30), "30 flights")
        self.assertEqual(ms.with_unit("yoga", 719), "11h 59m")          # time says what it is
        self.assertEqual(ms.with_unit("plank", 90), "1m 30s")

    def test_podium_and_records_carry_units(self):
        fixture = Fixture()
        try:
            # five logged days each: what a podium needs (MIN_BOARD_DAYS)
            rows = make_rows() + [
                activity_row("U001", "Priya Sharma", "read", [40] * 5, _days("2026-10-02", 5)),
                activity_row("U002", "Jack Brown", "read", [17, 17, 17, 18, 18], _days("2026-10-04", 5))]
            result = run(fixture.write("rows.json", rows), board_activities="read")
        finally:
            fixture.close()
        self.assertIn("200 pages", result["html"])
        self.assertIn("87 pages", result["html"])
        self.assertIn("305 reps", result["html"])


class TestSubjectIcon(unittest.TestCase):
    """The emoji at the front of the subject: on by default, off with none, and the page unchanged."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = Fixture()
        cls.path = cls.fixture.write("rows.json", make_rows())

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()

    def test_default(self):
        result = run(self.path)
        self.assertEqual(result["subject"], "\U0001F4AA Plank You Very Much: October 2026 in review")

    def test_none_is_the_old_subject(self):
        for word in ("none", "off", "No"):
            result = run(self.path, subject_icon=word)
            self.assertEqual(result["subject"], "Plank You Very Much: October 2026 in review", word)

    def test_own_icon(self):
        result = run(self.path, subject_icon="\U0001F3C6")
        self.assertTrue(result["subject"].startswith("\U0001F3C6 Plank You"))

    def test_shortcode_and_long_text_are_refused(self):
        result = run(self.path, subject_icon=":trophy:")
        self.assertTrue(result["subject"].startswith("\U0001F4AA "))
        self.assertIn("Slack shortcode", result["error"])
        result = run(self.path, subject_icon="This month in the channel")
        self.assertTrue(result["subject"].startswith("\U0001F4AA "))
        self.assertIn("too long", result["error"])

    def test_page_title_has_no_icon(self):
        # the <title> is the plain subject, so the email itself is what it was (see TestGolden)
        result = run(self.path)
        self.assertIn("<title>Plank You Very Much: October 2026 in review</title>", result["html"])


class TestGames(unittest.TestCase):
    """The brain games board: every game, and the games played."""

    def test_lines(self):
        lines = ms.game_lines(make_rows(), True)
        by_title = {line[1]: line for line in lines}
        # (emoji, title, players, games played, top score, holder, id)
        self.assertEqual(by_title["iAdd"][2:6], (2, 19, 14, "Priya Sharma"))
        # iMatch: Ana played without scoring (a player, not the holder); the opted-out are left out
        self.assertEqual(by_title["iMatch"][2:6], (2, 1253, 9, "Jack Brown"))
        self.assertNotIn("iSub", by_title)                  # nobody has scored in it

    def test_every_game_is_read(self):
        for row_type in ("object_memory_user", "pairs_memory_user", "image_memory_user",
                         "math_add_user", "math_sub_user", "math_mul_user", "math_avg_user",
                         "math_div_user"):
            self.assertIn(row_type, ms.GAMES)

    def test_column(self):
        fixture = Fixture()
        try:
            result = run(fixture.write("rows.json", make_rows()))
        finally:
            fixture.close()
        page = result["html"]
        games = page[page.index("Brain games"):]
        self.assertIn("Games played", games)
        self.assertIn("1,253", games)
        self.assertIn("iMatch", games)


def regen_golden():
    os.makedirs(TESTDATA, exist_ok=True)
    fixture = Fixture()
    try:
        path = fixture.write("rows.json", make_rows())
        for case, more in GOLDEN_CASES.items():
            result = run(path, **more)
            assert result["ok"], result["error"]
            with open(golden_path(case), "w", encoding="ascii") as handle:
                handle.write(result["html"])
            print("wrote", golden_path(case), len(result["html"]), "bytes")
    finally:
        fixture.close()


def write_preview():
    os.makedirs(TESTDATA, exist_ok=True)
    fixture = Fixture()
    try:
        path = fixture.write("challenges.json", challenge_rows(make_rows()))
        result = run(path)
        target = os.path.join(TESTDATA, "preview.html")
        with open(target, "w", encoding="ascii") as handle:
            handle.write(result["html"])
        print("wrote", target, "ok" if result["ok"] else result["error"])
    finally:
        fixture.close()


if __name__ == "__main__":
    if "--regen-golden" in sys.argv:
        regen_golden()
    elif "--write-preview" in sys.argv:
        write_preview()
    else:
        unittest.main()
