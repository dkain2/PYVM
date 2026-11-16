"""
Tests for leaderboard.py. Run them before and after any change:

    python3 test_leaderboard.py          # all of them
    python3 test_leaderboard.py -v       # with the name of each

Nothing here touches the network, Slack or Workato; only the standard library is needed.

THE GROUPS
    TestWeeklyBaseline   which saved run the week is measured from
    TestComputeWeekly    the week's top three, newcomers, starters, the crew's total, which boards get one
    TestSections         weekly_sections (parse, add, remove), share / pb / streak / climbers, nobody active
    TestMessage          the channel post: podium, weekly banner + medal lines, shoutout, the shorter footer
    TestMainEndToEnd     main() against a stand-in for Slack and a snapshot file: a real second board
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import leaderboard as lb                                                  # noqa: E402

NOW = datetime(2026, 11, 16, 11, 0, 0, tzinfo=timezone.utc)


def stamp(days_ago, hours_ago=0):
    return (NOW - timedelta(days=days_ago, hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry(pid, name, total, days=30, rank=None, best=1000):
    return {"id": pid, "name": name, "total": total, "days": days, "best": best, "best_set": best,
            "rank": rank or 0, "tied": False}


def ranked(entries):
    for place, item in enumerate(entries, start=1):
        item["rank"] = place
    return entries


def run(at, totals):
    """A saved run: {person: [rank, total, best, best_set, days]}."""
    return {"at": at, "p": {pid: [0, total, 0, 0, 0] for pid, total in totals.items()}}


def config(activity="step", **extra):
    return lb.activity_config(dict({"activity": activity}, **extra))


class TestWeeklyBaseline(unittest.TestCase):
    def test_latest_run_at_least_a_week_old(self):
        history = [run(stamp(20), {}), run(stamp(8), {}), run(stamp(3), {})]
        since, _ = lb.weekly_baseline(history, NOW)
        self.assertEqual(since, NOW - timedelta(days=8))

    def test_a_weekly_post_a_few_minutes_early_still_counts(self):
        history = [run(stamp(7, hours_ago=0), {}), run(stamp(0, hours_ago=1), {})]
        since, _ = lb.weekly_baseline(history, NOW)
        self.assertEqual(since, NOW - timedelta(days=7))

    def test_first_week_uses_the_oldest_run(self):
        history = [run(stamp(4), {}), run(stamp(2), {})]
        since, _ = lb.weekly_baseline(history, NOW)
        self.assertEqual(since, NOW - timedelta(days=4))

    def test_unreadable_times_give_nothing(self):
        self.assertIsNone(lb.weekly_baseline([{"at": "", "p": {}}], NOW))
        self.assertIsNone(lb.weekly_baseline([], NOW))


class TestComputeWeekly(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.people = ranked([
            entry("a", "Jack", 1000), entry("b", "Dheeraj", 900),
            entry("c", "Somya", 800), entry("d", "Claire", 700),
            entry("e", "Idil", 600),
        ])
        self.keys = {p["id"] for p in self.people}
        # a week ago everyone was at a lower total
        self.history = [run(stamp(7), {"a": 950, "b": 850, "c": 700, "d": 300, "e": 590})]

    def weekly(self, people=None, history=None, cfg=None):
        people = self.people if people is None else people
        return lb.compute_weekly(people, {p["id"] for p in people}, self.history if history is None else history,
                                 cfg or self.cfg, NOW)

    def test_top_three_by_gain(self):
        week = self.weekly()
        self.assertEqual([item["entry"]["name"] for item in week["top"]], ["Claire", "Somya", "Jack"])    # Jack and Dheeraj tie on 50
        self.assertEqual([item["gain"] for item in week["top"]], [400, 100, 50])
        self.assertEqual(week["crew"], 50 + 50 + 100 + 400 + 10)
        self.assertEqual(week["label"], "this week")

    def test_nobody_added_means_no_board_rows(self):
        flat = [run(stamp(7), {p["id"]: p["total"] for p in self.people})]
        self.assertIsNone(self.weekly(history=flat))

    def test_newcomer_is_credited_with_their_whole_total_and_welcomed(self):
        people = ranked(self.people + [entry("n", "Bharath", 5000, days=3)])
        week = self.weekly(people=people)
        top = week["top"][0]
        self.assertEqual((top["entry"]["name"], top["gain"], top["new"]), ("Bharath", 5000, True))
        self.assertEqual([e["name"] for e, _ in week["newcomers"]], ["Bharath"])

    def test_someone_with_a_long_history_missing_from_the_snapshot_is_not_a_newcomer(self):
        people = ranked(self.people + [entry("n", "Old hand", 90000, days=60)])
        week = self.weekly(people=people)
        self.assertNotIn("Old hand", [item["entry"]["name"] for item in week["top"]])
        self.assertEqual(week["newcomers"], [])

    def test_a_starter_can_make_the_top_three_and_shows_as_new(self):
        starter = entry("s", "Starter", 2000, days=2)
        board = ranked(list(self.people))
        week = lb.compute_weekly(board + [starter], {p["id"] for p in board}, self.history, self.cfg, NOW)
        first = week["top"][0]
        self.assertEqual((first["entry"]["name"], first["new"]), ("Starter", True))

    def test_ranked_person_is_not_marked_new(self):
        self.assertFalse(any(item["new"] for item in self.weekly()["top"]))

    def test_ties_break_on_total_then_name(self):
        history = [run(stamp(7), {"a": 900, "b": 800, "c": 700, "d": 600, "e": 500})]
        names = [item["entry"]["name"] for item in self.weekly(history=history)["top"]]
        self.assertEqual(names, ["Jack", "Dheeraj", "Somya"])

    def test_no_history_means_no_week(self):
        self.assertIsNone(self.weekly(history=[]))

    def test_old_baseline_is_labelled_by_date(self):
        week = self.weekly(history=[run(stamp(20), {"a": 1})])
        self.assertEqual(week["label"], "since Oct 27")

    def test_boards_where_gains_do_not_add_up_have_no_week(self):
        for activity in ("imemory", "greatwalk"):
            self.assertFalse(lb.weekly_applies(config(activity)), activity)
        for activity in ("step", "pushup", "iadd", "challenge"):
            self.assertTrue(lb.weekly_applies(config(activity)), activity)
        self.assertIsNone(lb.compute_weekly(self.people, self.keys, self.history, config("imemory"), NOW))

    def test_days_active_is_the_days_logged_since_the_baseline(self):
        history = [{"at": stamp(7), "p": {"a": [1, 950, 0, 0, 25], "b": [2, 850, 0, 0, 30], "c": [3, 700, 0, 0, 40],
                                          "d": [4, 300, 0, 0, 3], "e": [5, 590, 0, 0, 10]}}]
        week = self.weekly(history=history)
        by_name = {item["entry"]["name"]: item["active"] for item in week["top"]}
        self.assertEqual(by_name["Claire"], 27)       # 30 days now, 3 then
        self.assertEqual(by_name["Somya"], 0)
        lines = table_lines(week, self.cfg)
        self.assertIn("7/7", lines[1])                # capped at the week
        self.assertIn("0/7", lines[2])

    def test_days_are_a_dash_when_the_old_run_did_not_keep_them(self):
        history = [{"at": stamp(7), "p": {"a": [1, 950], "b": [2, 850], "c": [3, 700], "d": [4, 300], "e": [5, 590]}}]
        week = self.weekly(history=history)
        self.assertTrue(all(item["active"] is None for item in week["top"]))
        cfg = config(weekly_sections="table,active,overall")
        line = table_lines(week, cfg)[1]
        self.assertRegex(line, r"\+[\d,]+\s+-\s+#4$")

    def test_games_and_challenges_show_counts_not_a_fraction(self):
        cfg = config("challenge", weekly_sections="table,active")
        people = ranked([entry("a", "A", 10, days=12), entry("b", "B", 5, days=6)])
        history = [{"at": stamp(7), "p": {"a": [1, 8, 0, 0, 9], "b": [2, 5, 0, 0, 6]}}]
        week = lb.compute_weekly(people, {"a", "b"}, history, cfg, NOW)
        table = table_lines(week, cfg)
        self.assertIn("taken", table[0])
        self.assertEqual(table[1].split()[-1], "3")          # 12 taken now, 9 then

    def test_time_units_are_humanized(self):
        cfg = config("plank")
        history = [run(stamp(7), {"a": 100, "b": 100, "c": 100, "d": 100, "e": 100})]
        week = self.weekly(cfg=cfg, history=history)
        line = table_lines(week, cfg)[1]
        self.assertRegex(line, r"\+\d+[ms]")


def table_lines(week, cfg):
    """The weekly table as [the two header lines joined with a newline] + one string per row."""
    lines = lb.weekly_blocks(week, cfg)[-1]["text"]["text"].strip("`\n").splitlines()
    return ["\n".join(lines[:2])] + lines[2:]


def saved_run(days_ago, people):
    """A saved run with every fact: people = {id: (rank, total, best, days)}."""
    return {"at": stamp(days_ago), "p": {pid: [r, total, best, best, d] for pid, (r, total, best, d) in people.items()}}


class TestSections(unittest.TestCase):
    """weekly_sections: which parts of the post show, and the extras (share, streak, pb, climbers)."""

    def setUp(self):
        self.people = ranked([entry("a", "Jack", 1000, best=300), entry("b", "Dheeraj", 900, best=200),
                              entry("c", "Somya", 800, best=100), entry("d", "Claire", 700, best=100)])
        self.keys = {p["id"] for p in self.people}
        # a week ago: Claire was 6th (now 4th), Jack's best day was lower than now
        self.history = [
            saved_run(14, {"a": (1, 800, 250, 20), "b": (2, 700, 200, 20), "c": (3, 600, 100, 20), "d": (6, 100, 100, 10)}),
            saved_run(7, {"a": (1, 900, 250, 25), "b": (2, 850, 200, 27), "c": (3, 800, 100, 28), "d": (6, 300, 100, 12)}),
        ]

    def week(self, **cfg):
        return lb.compute_weekly(self.people, self.keys, self.history, config(**cfg), NOW)

    def table(self, week, cfg):
        return table_lines(week, cfg)

    # --- parsing
    def test_blank_and_all_mean_everything(self):
        for value in (None, "", "  ", "all"):
            self.assertEqual(lb.parse_sections(value), (set(lb.WEEKLY_SECTIONS), []), repr(value))

    def test_a_list_shows_only_those(self):
        on, unknown = lb.parse_sections("podium, table ,overall")
        self.assertEqual(on, {"podium", "table", "overall"})
        self.assertEqual(unknown, [])

    def test_minus_takes_one_away_from_everything(self):
        self.assertEqual(lb.parse_sections("-streak,-share")[0], set(lb.WEEKLY_SECTIONS) - {"streak", "share"})
        self.assertEqual(lb.parse_sections("all,-footer")[0], set(lb.WEEKLY_SECTIONS) - {"footer"})
        self.assertEqual(lb.parse_sections("table,active,-active")[0], {"table"})

    def test_case_spaces_and_lists(self):
        self.assertEqual(lb.parse_sections(["Podium", " TABLE "])[0], {"podium", "table"})
        self.assertEqual(lb.parse_sections("podium;table")[0], {"podium", "table"})

    def test_unknown_words_are_reported_and_ignored(self):
        on, unknown = lb.parse_sections("table,confetti,-sparkles")
        self.assertEqual(on, {"table"})
        self.assertEqual(unknown, ["confetti", "sparkles"])
        self.assertEqual(config(weekly_sections="table,confetti")["sections_unknown"], ["confetti"])

    # --- the extras
    def test_share_is_a_slice_of_the_crews_week(self):
        week = self.week()
        shares = {item["entry"]["name"]: item["share"] for item in week["top"]}
        self.assertEqual(week["crew"], 400 + 100 + 50)             # Somya added nothing
        self.assertAlmostEqual(sum(shares.values()), 100.0, 5)      # all three are everyone who added
        self.assertAlmostEqual(shares["Claire"], 100.0 * 400 / 550, 5)
        cfg = config(weekly_sections="table,share")
        self.assertIn("73%", self.table(week, cfg)[1])

    def test_a_personal_best_gets_a_star(self):
        week = self.week()
        stars = {item["entry"]["name"]: item["pb"] for item in week["top"]}
        self.assertTrue(stars["Jack"])                    # 300 now, 250 a week ago
        self.assertFalse(stars["Dheeraj"])                # 200 both times
        cfg = config(weekly_sections="table,pb")
        rows = {line.split()[1]: line for line in self.table(week, cfg)[1:]}
        self.assertIn("\u2605", rows["Jack"])
        self.assertNotIn("\u2605", rows["Dheeraj"])

    def test_no_star_for_someone_new_or_on_a_board_where_best_is_the_total(self):
        people = ranked(self.people + [entry("n", "Newbie", 5000, days=2, best=5000)])
        week = lb.compute_weekly(people, self.keys, self.history, config(), NOW)
        self.assertFalse(next(i for i in week["top"] if i["entry"]["name"] == "Newbie")["pb"])
        cfg = config("challenge", weekly_sections="table,pb")
        challenge = lb.compute_weekly(ranked([entry("a", "A", 10, days=12, best=10)]), {"a"},
                                      [saved_run(7, {"a": (1, 8, 8, 9)})], cfg, NOW)
        self.assertNotIn("best", self.table(challenge, cfg)[0].split())

    def test_streak_counts_boards_in_a_row_with_something_added(self):
        week = self.week()
        streaks = {item["entry"]["name"]: item["streak"] for item in week["top"]}
        self.assertEqual(streaks["Jack"], 2)              # 800 > 900 > 1000: added on this board and the one before
        cfg = config(weekly_sections="table,streak")
        rows = {line.split()[1]: line for line in self.table(week, cfg)[1:]}
        self.assertIn("2x", rows["Jack"])
        self.assertTrue(rows["Dheeraj"].rstrip().endswith("2x"))

    def test_a_streak_of_one_is_a_dash_and_a_gap_breaks_it(self):
        self.history[0]["p"]["b"][TOTAL_INDEX] = 850      # Dheeraj added nothing between the two earlier boards
        week = self.week()
        streak = {item["entry"]["name"]: item["streak"] for item in week["top"]}["Dheeraj"]
        self.assertEqual(streak, 1)
        row = {line.split()[1]: line for line in self.table(week, config(weekly_sections="table,streak"))[1:]}["Dheeraj"]
        self.assertTrue(row.rstrip().endswith("-"))

    def test_biggest_climber(self):
        week = self.week()
        self.assertEqual(week["climber"]["entry"]["name"], "Claire")
        self.assertEqual(week["climber"]["move"], 2)       # 6th a week ago, 4th now
        lines = lb.shoutout_lines(week, config(weekly_sections="climbers"))
        self.assertEqual(lines, ["Biggest climb: *Claire* \u25b22, now #4."])

    def test_no_climber_when_nobody_moved_up(self):
        for past in self.history:
            for pid, p in zip("abcd", (1, 2, 3, 4)):
                past["p"][pid][0] = p
        self.assertIsNone(self.week()["climber"])
        self.assertEqual(lb.shoutout_lines(self.week(), config(weekly_sections="climbers")), [])

    # --- switching parts on and off
    def message(self, **cfg):
        cfg = config(**cfg)
        week = lb.compute_weekly(self.people, self.keys, self.history, cfg, NOW)
        blocks = lb.build_message(self.people, cfg, 10, self.people, weekly=week)
        return "\n".join(b["text"]["text"] if b["type"] == "section" else
                         "\n".join(e["text"] for e in b["elements"]) if b["type"] == "context" else b["type"]
                         for b in blocks)

    def test_everything_by_default(self):
        text = self.message()
        for part in (":first_place_medal: *Jack*", "*Weekly leaders*", "share", "active", "streak on", "best", "rank",
                     "Shoutout to", "Crew added", "Biggest climb", "steps between us"):
            self.assertIn(part, text)

    def test_each_part_can_be_left_out(self):
        expect_gone = {"podium": ":first_place_medal: *Jack*", "banner": "*Weekly leaders*", "shoutout": "Shoutout to",
                       "crew": "Crew added", "climbers": "Biggest climb", "footer": "steps between us",
                       "welcome": None}
        for section, phrase in expect_gone.items():
            text = self.message(weekly_sections="-" + section)
            if phrase:
                self.assertNotIn(phrase, text, section)
        header = lambda **cfg: self.table(lb.compute_weekly(self.people, self.keys, self.history, config(**cfg), NOW),
                                          config(**cfg))[0].split()
        words = {"share": "share", "active": "active", "streak": "streak", "pb": "best", "overall": "rank"}
        for column, word in words.items():
            self.assertNotIn(word, header(weekly_sections="-" + column), column)
            self.assertIn(word, header(), column)

    def test_without_the_table_there_is_no_table(self):
        text = self.message(weekly_sections="banner,shoutout")
        self.assertNotIn("this week                  ", text)
        self.assertNotIn("rank", text)
        self.assertIn("Shoutout to", text)
        self.assertIn("*Weekly leaders*", text)

    def test_only_what_is_named_shows(self):
        text = self.message(weekly_sections="table,overall")
        self.assertIn("all-time", text)
        self.assertNotIn("share", text)
        self.assertNotIn(":first_place_medal:", text)
        self.assertNotIn("Shoutout", text)
        self.assertNotIn("steps between us", text)
        self.assertNotIn("people on the board", text)

    def test_shoutout_and_crew_share_a_line_or_stand_alone(self):
        week = self.week()
        both = lb.shoutout_lines(week, config(weekly_sections="shoutout,crew"))
        self.assertEqual(len(both), 1)
        self.assertEqual(len(lb.shoutout_lines(week, config(weekly_sections="crew"))), 1)
        self.assertTrue(lb.shoutout_lines(week, config(weekly_sections="crew"))[0].startswith("Crew added"))

    # --- nobody active
    def test_no_weekly_board_when_nobody_was_active(self):
        flat = [saved_run(7, {"a": (1, 1000, 300, 30), "b": (2, 900, 200, 30), "c": (3, 800, 100, 30), "d": (4, 700, 100, 30)})]
        self.assertIsNone(lb.compute_weekly(self.people, self.keys, flat, config(), NOW))
        blocks = lb.build_message(self.people, config(), 10, self.people, weekly=None, movers="")
        text = json.dumps(blocks)
        self.assertNotIn("Weekly leaders", text)
        self.assertNotIn("Shoutout", text)
        self.assertNotIn("this week", text)


TOTAL_INDEX = lb.TOTAL


class TestMessage(unittest.TestCase):
    def setUp(self):
        self.cfg = config()
        self.people = ranked([entry("a", "Jack Moran", 1299122), entry("b", "Dheeraj Kain", 692655),
                              entry("c", "Somya Aggarwal", 569207), entry("d", "Claire Lintingre", 73855)])
        history = [run(stamp(7), {"a": 1242405, "b": 642680, "c": 504843, "d": 8110})]
        self.weekly = lb.compute_weekly(self.people, {p["id"] for p in self.people}, history, self.cfg, NOW)

    def texts(self, blocks):
        out = []
        for block in blocks:
            if block["type"] == "section":
                out.append(block["text"]["text"])
            elif block["type"] == "context":
                out.extend(element["text"] for element in block["elements"])
        return out

    def test_podium_then_weekly_board_follow_the_main_table(self):
        texts = self.texts(lb.build_message(self.people, self.cfg, 10, self.people, weekly=self.weekly))
        table = next(i for i, t in enumerate(texts) if "total" in t and "distance" in t)
        self.assertEqual(texts[table + 1],
                         ":first_place_medal: *Jack Moran*  :second_place_medal: *Dheeraj Kain*  "
                         ":third_place_medal: *Somya Aggarwal*")
        self.assertIn("*Weekly leaders*", texts[table + 2])
        self.assertIn("most added this week", texts[table + 2])
        self.assertTrue(texts[table + 3].startswith("```"))
        self.assertTrue(texts[table + 4].startswith("_Shoutout"))

    def table(self, weekly, cfg=None):
        return table_lines(weekly, cfg or self.cfg)

    def test_weekly_table_in_the_main_boards_style(self):
        lines = self.table(self.weekly)
        self.assertEqual(len(lines), 1 + 3)                        # header + top three
        header = lb.weekly_blocks(self.weekly, self.cfg)[-1]["text"]["text"].strip("`\n").splitlines()[:2]
        self.assertEqual(header[0].split(), ["this", "week", "crew", "days", "streak", "on", "new", "all-time"])
        self.assertEqual(header[1].split(), ["#", "name", "added", "share", "active", "boards", "best", "rank"])
        self.assertIn("Claire Lintingre", lines[1])
        self.assertIn("+65,745", lines[1])
        self.assertTrue(lines[1].endswith("#4"))
        self.assertTrue(lines[2].lstrip().startswith("2"))
        self.assertTrue(lines[3].lstrip().startswith("3"))
        self.assertTrue(lb.weekly_blocks(self.weekly, self.cfg)[-1]["text"]["text"].startswith("```"))
        # every row is as wide as the header, so the columns line up in a monospace block
        raw = lb.weekly_blocks(self.weekly, self.cfg)[-1]["text"]["text"].strip("`\n").splitlines()
        self.assertEqual(len(raw), 2 + 3)                          # two header lines and three rows
        self.assertEqual(len({len(line) for line in raw}), 1)

    def test_banner_replaces_the_text_heading(self):
        cfg = config(weekly_image_url="https://example.com/weekly.png")
        blocks = lb.weekly_blocks(self.weekly, cfg)
        self.assertEqual(blocks[0]["type"], "image")
        self.assertEqual(blocks[0]["image_url"], "https://example.com/weekly.png")
        self.assertNotIn("Weekly leaders", json.dumps(blocks[1:]))
        self.assertTrue(blocks[1]["text"]["text"].startswith("```"))
        text_heading = lb.weekly_blocks(self.weekly, self.cfg)[0]
        self.assertEqual(text_heading["type"], "section")

    def test_a_newcomer_row_says_new(self):
        people = ranked(self.people + [entry("n", "Bharath Ramesh", 90000, days=2)])
        history = [run(stamp(7), {"a": 1242405, "b": 642680, "c": 504843, "d": 8110})]
        weekly = lb.compute_weekly(people, {p["id"] for p in people[:-1]}, history, self.cfg, NOW)
        row = self.table(weekly)[1]
        self.assertIn("Bharath Ramesh", row)
        self.assertTrue(row.endswith("new"))
        self.assertIn("2/7", row)                                  # showed up on both days they have

    def test_shoutout_names_the_top_three_and_the_crew(self):
        text = "\n".join(self.texts(lb.build_message(self.people, self.cfg, 10, self.people, weekly=self.weekly)))
        self.assertIn("Shoutout to *Claire Lintingre*, *Somya Aggarwal* and *Jack Moran*", text)
        self.assertIn("Crew added", text)

    def test_the_text_nobody_reads_is_gone(self):
        text = "\n".join(self.texts(lb.build_message(self.people, self.cfg, 10, self.people, weekly=self.weekly)))
        for gone in ("Most consistent", "Longest single session", "personal best", "on a roll",
                     "Closest to the board", "Since the last board"):
            self.assertNotIn(gone, text)

    def test_footer_keeps_the_total_and_the_headcount(self):
        footer = self.texts(lb.build_message(self.people, self.cfg, 10, self.people, weekly=self.weekly))[-1]
        self.assertIn("steps between us", footer)
        self.assertIn("4 people on the board.", footer)

    def test_thread_pointer_in_the_footer(self):
        footer = self.texts(lb.build_message(self.people, self.cfg, 3, self.people, has_thread=True,
                                             weekly=self.weekly))[-1]
        self.assertIn("everyone else is in the thread", footer)

    def test_newcomers_are_welcomed(self):
        people = ranked(self.people + [entry("n", "Bharath Ramesh", 4000, days=2)])
        history = [run(stamp(7), {"a": 1242405, "b": 642680, "c": 504843, "d": 8110})]
        weekly = lb.compute_weekly(people, {p["id"] for p in people}, history, self.cfg, NOW)
        text = "\n".join(self.texts(lb.build_message(people, self.cfg, 10, people, weekly=weekly)))
        self.assertIn("Welcome *Bharath Ramesh*, new this week.", text)

    def test_without_a_week_the_movers_line_replaces_the_weekly_board(self):
        blocks = lb.build_message(self.people, self.cfg, 10, self.people, movers="Since the last board: x")
        text = "\n".join(self.texts(blocks))
        self.assertIn(":first_place_medal: *Jack Moran*", text)
        self.assertIn("Since the last board: x", text)
        self.assertNotIn("Shoutout", text)
        self.assertNotIn("Weekly leaders", text)

    def test_challenge_board_wording(self):
        cfg = config("challenge")
        people = ranked([entry("a", "A", 10, days=12), entry("b", "B", 5, days=6)])
        week = lb.compute_weekly(people, {"a", "b"}, [run(stamp(7), {"a": 8, "b": 5})], cfg, NOW)
        text = "\n".join(lb.shoutout_lines(week, cfg))
        self.assertIn("Crew cleared 2 more challenges.", text)


class TestMainEndToEnd(unittest.TestCase):
    """main() twice, a week apart, against a snapshot file and a stand-in for Slack."""

    def board(self, totals):
        people = [entry(pid, name, total, days=2 if pid == "n" else 30) for pid, name, total in totals]
        people.sort(key=lambda p: (-p["total"], p["name"]))
        return ranked(people)

    def post(self, totals, now):
        posts = []

        def fake_slack(token, channel, text, blocks, thread_ts=None):
            posts.append({"text": text, "blocks": blocks, "thread_ts": thread_ts})
            return "1.%d" % len(posts), None

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        people = self.board(totals)
        with mock.patch.object(lb, "build_board", return_value=people), \
                mock.patch.object(lb, "slack_post", fake_slack), \
                mock.patch.object(lb, "datetime", Clock), \
                mock.patch.object(lb, "fetch_rows", return_value=[]):
            result = lb.main({"activity": "step", "channel_id": "C1", "slack_bot_token": "x",
                              "local_data_file": os.devnull, "local_snapshot_file": self.path})
        return result, posts

    def test_second_board_carries_the_weekly_mini_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.path = os.path.join(tmp, "snap.json")
            with mock.patch.object(lb, "load_local_rows", return_value=[]):
                first, first_posts = self.post([("a", "Jack", 1000), ("b", "Dheeraj", 900), ("c", "Somya", 800)],
                                               NOW - timedelta(days=7))
                self.assertTrue(first["ok"], first["error"])
                self.assertTrue(first["snapshot_saved"])
                first_text = json.dumps(first_posts[0]["blocks"])
                self.assertNotIn("Shoutout", first_text)              # no history yet: the podium, as before

                second, posts = self.post([("a", "Jack", 1100), ("b", "Dheeraj", 1500), ("c", "Somya", 850),
                                           ("n", "Newbie", 400)], NOW)
        self.assertTrue(second["ok"], second["error"])
        text = json.dumps(posts[0]["blocks"], ensure_ascii=False)
        self.assertIn("Shoutout to *Dheeraj*, *Newbie* and *Jack*", text)
        self.assertIn("Welcome *Newbie*", text)
        heading = [b for b in posts[0]["blocks"] if b["type"] == "section" and "*Weekly leaders*" in b["text"]["text"]]
        self.assertEqual(len(heading), 1)
        self.assertIn(":first_place_medal: *Dheeraj*", text)          # the all-time podium is still there


if __name__ == "__main__":
    unittest.main()
