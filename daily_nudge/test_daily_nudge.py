"""
Tests for daily_nudge.py. Run them before and after any change:

    python3 test_daily_nudge.py            # all of them
    python3 test_daily_nudge.py -v         # with the name of each

Nothing here touches the network or Slack; the standard library only. The games' own steps
(imath, imemory, ibreath) are imported from their folders so a button value the nudge sends
is checked against the parser that will read the click.

THE GROUPS
    TestBreakSection   every nudge, activity or game, ends with iMath, iMemory and iBreath buttons
    TestSuggestion     the one-line suggestion suits the activity and never repeats a game nudge's own game
    TestValues         each button's value is read back by that game step's own parser
    TestExisting       the original nudge is unchanged: the log command, the game's two buttons, limits
"""

import json
import os
import random
import sys
import unittest
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
for folder in ("", "../imath", "../imemory", "../ibreath"):
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, folder)))

import daily_nudge as dn  # noqa: E402
import ibreath  # noqa: E402
import imath  # noqa: E402
import imemory  # noqa: E402

DAY = date(2026, 11, 16)
THREE = ["imath_play", "imemory_play", "ibreath_play"]


def nudge(activity, **extra):
    """main() as a dry run, with the blocks it would post."""
    out = dn.main(dict({"activity": activity, "channel_id": "C1", "dry_run": "yes"}, **extra))
    return out, json.loads(out["message_json"])


def break_row(blocks):
    return [b for b in blocks if b.get("block_id") == "nudge_break"][0]


class TestBreakSection(unittest.TestCase):
    def test_every_activity_and_game_has_all_three_buttons(self):
        for key in dn.ACTIVITIES:
            out, blocks = nudge(key)
            ids = [e["action_id"] for e in break_row(blocks)["elements"]]
            self.assertEqual(ids, THREE, key)
            self.assertTrue(out["ok"], key)

    def test_exactly_one_button_is_primary_and_it_is_the_suggested_one(self):
        for key in dn.ACTIVITIES:
            out, blocks = nudge(key)
            primary = [e["action_id"] for e in break_row(blocks)["elements"] if e.get("style") == "primary"]
            self.assertEqual(primary, [out["suggested_break"] + "_play"], key)

    def test_it_comes_after_the_log_command_or_the_game_buttons(self):
        _, blocks = nudge("plank")
        kinds = [b["type"] for b in blocks]
        self.assertEqual(kinds, ["section", "section", "context", "divider", "section", "actions"])
        _, blocks = nudge("imemory")
        self.assertEqual([b["type"] for b in blocks],
                         ["section", "section", "actions", "divider", "section", "actions"])

    def test_the_result_lists_the_buttons(self):
        out, _ = nudge("plank")
        self.assertEqual(out["buttons"], THREE)
        out, _ = nudge("iadd")
        self.assertEqual(out["buttons"], ["imath_try", "imath_play"] + THREE)

    def test_post_body_carries_the_same_blocks(self):
        out, blocks = nudge("yoga")
        self.assertEqual(json.loads(out["post_message_body"])["blocks"], blocks)

    def test_fits_slack_limits(self):
        for key in dn.ACTIVITIES:
            _, blocks = nudge(key)
            self.assertLessEqual(len(blocks), 50)
            ids = [b["block_id"] for b in blocks if "block_id" in b]
            self.assertEqual(len(ids), len(set(ids)), "block ids are unique: " + key)
            for block in blocks:
                for element in block.get("elements", []) if block["type"] == "actions" else []:
                    self.assertLessEqual(len(element["text"]["text"]), 75)
                    self.assertLessEqual(len(element["value"]), 2000)
                    self.assertLessEqual(len(element["action_id"]), 255)


class TestSuggestion(unittest.TestCase):
    def test_calm_activities_suggest_breathing(self):
        for key in ("yoga", "meditate", "breathe", "read"):
            for seed in range(10):
                game, _ = dn.suggest_break(key, dn.ACTIVITIES[key], random.Random(seed))
                self.assertEqual(game, "ibreath", key)

    def test_active_activities_suggest_maths_or_memory(self):
        for key in ("plank", "pushup", "step", "workout"):
            game, _ = dn.suggest_break(key, dn.ACTIVITIES[key], random.Random(1))
            self.assertIn(game, ("imath", "imemory"), key)

    def test_a_game_nudge_never_suggests_its_own_game(self):
        for key, details in dn.GAMES.items():
            for seed in range(20):
                game, _ = dn.suggest_break(key, dn.ACTIVITIES[key], random.Random(seed))
                self.assertNotEqual(game, details["buttons"], key)

    def test_the_idea_is_one_of_that_games_lines_and_is_shown(self):
        game, idea = dn.suggest_break("plank", dn.ACTIVITIES["plank"], random.Random(3))
        self.assertIn(idea, dn.BREAKS[game]["ideas"])
        blocks, _ = dn.break_blocks("plank", dn.ACTIVITIES["plank"], DAY, random.Random(3))
        self.assertIn(idea, blocks[1]["text"]["text"])

    def test_unknown_activity_still_gets_a_suggestion(self):
        out, blocks = nudge("juggling")
        self.assertEqual([e["action_id"] for e in break_row(blocks)["elements"]], THREE)
        self.assertIn(out["suggested_break"], dn.BREAKS)


class TestValues(unittest.TestCase):
    def values(self, day=DAY):
        blocks, _ = dn.break_blocks("plank", dn.ACTIVITIES["plank"], day, random.Random(0))
        return {e["action_id"]: e["value"] for e in blocks[2]["elements"]}

    def test_imath_value_is_read_by_imath(self):
        game, owner, step, choice = imath.parse_action(self.values()["imath_play"])
        self.assertIn(game, dn.MATH_ROTATION)
        self.assertEqual((owner, step, choice), ("anyone", 0, "play"))

    def test_imemory_value_is_read_by_imemory(self):
        self.assertEqual(imemory.parse_action(self.values()["imemory_play"]), ("anyone", 0, "play"))

    def test_ibreath_value_is_read_by_ibreath(self):
        self.assertEqual(ibreath.parse_value(self.values()["ibreath_play"]), ("play", "anyone", "0"))

    def test_the_maths_game_rotates_by_date(self):
        seen = [dn.math_game_for(date(2026, 11, d)) for d in range(1, 7)]
        self.assertEqual(set(seen), set(dn.MATH_ROTATION))
        self.assertEqual(seen[:3], seen[3:])

    def test_the_rotation_games_exist_in_imath(self):
        for game in dn.MATH_ROTATION:
            self.assertIn(game, imath.GAMES)


class TestIBreathPlay(unittest.TestCase):
    """The ibreath click the nudge's button sends opens the presser's own card."""

    def click(self, value, clicker="U2"):
        calls = []
        real = ibreath.open_card
        ibreath.open_card = lambda *a, **k: calls.append((a, k))
        try:
            result = {"user_id": clicker, "channel": "C1", "thread_ts": "111.1"}
            ibreath.handle_click({"action_value": value, "action_ts": "9.9"}, result, None, "tok")
        finally:
            ibreath.open_card = real
        return result, calls

    def test_anyone_can_open_a_card(self):
        result, calls = self.click("play|anyone|0")
        self.assertEqual(len(calls), 1)
        args = calls[0][0]
        self.assertEqual(args[4], "111.1", "in the thread of the nudge")
        self.assertEqual(args[5], "play:9.9")

    def test_another_persons_start_is_still_refused(self):
        sent = []
        real = ibreath.slack_ephemeral
        ibreath.slack_ephemeral = lambda *a, **k: sent.append(a)
        try:
            result = {"user_id": "U2", "channel": "C1", "thread_ts": ""}
            ibreath.handle_click({"action_value": "start|U1|0"}, result, None, "tok")
        finally:
            ibreath.slack_ephemeral = real
        self.assertEqual(result["skipped"], "button belongs to another person")
        self.assertEqual(len(sent), 1)


class TestExisting(unittest.TestCase):
    def test_an_activity_still_ends_its_own_part_with_the_log_command(self):
        _, blocks = nudge("plank")
        self.assertIn("iplanked 60", blocks[2]["elements"][0]["text"])

    def test_a_game_still_has_its_daily_and_play_buttons(self):
        _, blocks = nudge("isub")
        row = blocks[2]
        self.assertEqual(row["block_id"], "imath_nudge")
        self.assertEqual([e["action_id"] for e in row["elements"]], ["imath_try", "imath_play"])
        self.assertEqual(row["elements"][0]["value"], "isub|anyone|0|try")

    def test_build_blocks_without_a_break_section_is_the_old_nudge(self):
        blocks = dn.build_blocks(dn.activity_details("plank", {}), "T", "B")
        self.assertEqual([b["type"] for b in blocks], ["section", "section", "context"])

    def test_default_pool_unchanged(self):
        self.assertEqual(dn.DEFAULT_ACTIVITIES, list(dn.CORE_ACTIVITIES) + list(dn.GAMES))

    def test_choose_activity_explicit_and_pool(self):
        self.assertEqual(dn.choose_activity({"activity": "Plank"}), "plank")
        self.assertIn(dn.choose_activity({}), dn.DEFAULT_ACTIVITIES)

    def test_blank_token_returns_the_body_without_posting(self):
        out = dn.main({"activity": "plank", "channel_id": "C1"})
        self.assertTrue(out["ok"])
        self.assertFalse(out["posted"])
        self.assertTrue(out["post_message_body"])


if __name__ == "__main__":
    unittest.main()
