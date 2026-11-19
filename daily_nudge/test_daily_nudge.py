"""
Tests for daily_nudge.py. Run them before and after any change:

    python3 test_daily_nudge.py            # all of them
    python3 test_daily_nudge.py -v         # with the name of each

Nothing here touches the network or Slack; the standard library only. The games' own steps
(imath, imemory, ibreath) are imported from their folders so a button value the nudge sends
is checked against the parser that will read the click.

THE GROUPS
    TestBreakSection   every nudge, activity or game, ends with a button for each of the nine games
    TestSuggestion     the one-line suggestion suits the activity and never suggests a game nudge's own game
    TestValues         each button's value is read back by that game step's own parser
    TestSpotter        every log command the nudge shows is a trigger spotter really has
    TestExisting       the original nudge is unchanged: the log command, the game's two buttons, limits
"""

import json
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for folder in ("", "../imath", "../imemory", "../ibreath", "../spotter"):
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, folder)))

import daily_nudge as dn  # noqa: E402
import ibreath  # noqa: E402
import imath  # noqa: E402
import imemory  # noqa: E402
import spotter  # noqa: E402

ALL_GAMES = ["iadd", "isub", "imultiple", "idivide", "iaverage",
             "imemory", "imemoryimage", "imatch", "iboxbreathe"]
ROWS = ("nudge_break_maths", "nudge_break_memory")


def nudge(activity, **extra):
    """main() as a dry run, with the blocks it would post."""
    out = dn.main(dict({"activity": activity, "channel_id": "C1", "dry_run": "yes"}, **extra))
    return out, json.loads(out["message_json"])


def break_buttons(blocks):
    """Every button of the break rows, in order."""
    return [e for b in blocks if b.get("block_id") in ROWS for e in b["elements"]]


class TestBreakSection(unittest.TestCase):
    def test_every_activity_and_game_has_a_button_for_every_game(self):
        for key in dn.ACTIVITIES:
            out, blocks = nudge(key)
            labels = [e["text"]["text"].split(" ", 1)[1].lower() for e in break_buttons(blocks)]
            self.assertEqual(labels, ALL_GAMES, key)
            self.assertTrue(out["ok"], key)

    def test_no_generic_imath_or_ibreath_button(self):
        _, blocks = nudge("plank")
        for e in break_buttons(blocks):
            self.assertNotIn(e["text"]["text"].split(" ", 1)[1], ("iMath", "iBreath"))

    def test_buttons_in_a_row_have_their_own_action_ids(self):
        _, blocks = nudge("plank")
        for block in blocks:
            if block["type"] == "actions":
                ids = [e["action_id"] for e in block["elements"]]
                self.assertEqual(len(ids), len(set(ids)), block["block_id"])

    def test_action_ids_keep_the_prefix_of_the_step_that_reads_them(self):
        _, blocks = nudge("plank")
        for e in break_buttons(blocks):
            self.assertRegex(e["action_id"], r"^(imath|imemory|ibreath)_")

    def test_two_rows_maths_then_memory_and_breathing(self):
        _, blocks = nudge("plank")
        rows = [b for b in blocks if b.get("block_id") in ROWS]
        self.assertEqual([b["block_id"] for b in rows], list(ROWS))
        self.assertEqual(len(rows[0]["elements"]), 5)
        self.assertEqual(len(rows[1]["elements"]), 4)

    def test_exactly_one_break_button_is_primary_and_it_is_the_suggested_one(self):
        for key in dn.ACTIVITIES:
            out, blocks = nudge(key)
            primary = [e for e in break_buttons(blocks) if e.get("style") == "primary"]
            self.assertEqual([e["action_id"] for e in primary],
                             [dn.click_id(dn.BREAKS[out["suggested_break"]]["action_id"])], key)

    def test_it_comes_after_the_log_command_or_the_game_buttons(self):
        _, blocks = nudge("plank")
        self.assertEqual([b["type"] for b in blocks],
                         ["section", "section", "context", "divider", "section", "actions", "actions"])
        _, blocks = nudge("imemory")
        self.assertEqual([b["type"] for b in blocks],
                         ["section", "section", "actions", "divider", "section", "actions", "actions"])

    def test_the_result_lists_the_buttons(self):
        out, _ = nudge("plank")
        self.assertEqual(out["buttons"], [dn.click_id(dn.BREAKS[k]["action_id"]) for k in ALL_GAMES])
        out, _ = nudge("iadd")
        self.assertEqual(out["buttons"][:2], ["imath_try", "imath_play"])
        self.assertEqual(len(out["buttons"]), 2 + len(ALL_GAMES))

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
    def test_calm_activities_suggest_box_breathing(self):
        for key in ("yoga", "meditate", "breathe", "read"):
            for seed in range(10):
                game, _ = dn.suggest_break(key, random.Random(seed))
                self.assertEqual(game, "iboxbreathe", key)

    def test_active_activities_suggest_a_maths_game(self):
        for key in ("plank", "pushup", "step", "workout"):
            for seed in range(10):
                game, _ = dn.suggest_break(key, random.Random(seed))
                self.assertEqual(dn.BREAKS[game]["row"], "maths", key)

    def test_writing_suggests_a_memory_game(self):
        for seed in range(10):
            game, _ = dn.suggest_break("write", random.Random(seed))
            self.assertIn(game, ("imemory", "imemoryimage", "imatch"))

    def test_a_game_nudge_never_suggests_itself(self):
        for key in dn.GAMES:
            for seed in range(30):
                game, _ = dn.suggest_break(key, random.Random(seed))
                self.assertNotEqual(game, key)

    def test_every_game_can_be_suggested_and_has_ideas(self):
        for key, game in dn.BREAKS.items():
            self.assertTrue(game["ideas"], key)
        seen = {dn.suggest_break(a, random.Random(i))[0]
                for a in ("plank", "write", "yoga") for i in range(40)}
        self.assertEqual(seen, set(ALL_GAMES))

    def test_the_idea_is_one_of_that_games_lines_and_is_shown(self):
        game, idea = dn.suggest_break("plank", random.Random(3))
        self.assertIn(idea, dn.BREAKS[game]["ideas"])
        blocks, suggested = dn.break_blocks("plank", random.Random(3))
        self.assertEqual(suggested, game)
        self.assertIn(idea, blocks[1]["text"]["text"])
        self.assertIn(dn.BREAKS[game]["label"].split(" ", 1)[1], blocks[1]["text"]["text"])

    def test_unknown_activity_still_gets_a_suggestion(self):
        out, blocks = nudge("juggling")
        self.assertEqual(len(break_buttons(blocks)), len(ALL_GAMES))
        self.assertIn(out["suggested_break"], dn.BREAKS)


class TestValues(unittest.TestCase):
    """Each button's value is read back by the parser of the step that will get the click."""

    def value(self, key):
        return dn.BREAKS[key]["value"]

    def test_the_five_imath_games_are_read_by_imath(self):
        for key in ("iadd", "isub", "imultiple", "idivide", "iaverage"):
            self.assertEqual(imath.parse_action(self.value(key)), (key, "anyone", 0, "play"), key)

    def test_imemory_words_is_read_by_imemory(self):
        value = self.value("imemory")
        self.assertEqual(imemory.parse_action(value), ("anyone", 0, "play"))
        self.assertEqual(imemory.value_flavour(value), imemory.WORDS_GAME)

    def test_imemoryimage_is_read_by_imemory_as_the_pictures_game(self):
        value = self.value("imemoryimage")
        self.assertEqual(imemory.parse_action(value), ("anyone", 0, "play"))
        self.assertEqual(imemory.value_flavour(value), imemory.PICTURES_GAME)

    def test_imatch_is_iMatchs_own_join_button(self):
        self.assertEqual(imemory.parse_match(self.value("imatch")), ("anyone", "0", "join", -1))
        self.assertEqual(dn.BREAKS["imatch"]["action_id"], imemory.match_join_button()["action_id"])
        self.assertEqual(self.value("imatch"), imemory.match_join_button()["value"])

    def test_iboxbreathe_is_read_by_ibreath(self):
        self.assertEqual(ibreath.parse_value(self.value("iboxbreathe")), ("play", "anyone", "0"))

    def test_the_values_match_the_buttons_the_games_post_themselves(self):
        self.assertEqual(self.value("imemory"), imemory.action_value("anyone", 0, "play"))
        self.assertEqual(self.value("imemoryimage"),
                         imemory.action_value("anyone", 0, "play", imemory.PICTURES_GAME))
        for key in ("iadd", "isub", "imultiple", "idivide", "iaverage"):
            self.assertEqual(self.value(key), imath.action_value(key, "anyone", 0, "play"), key)


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


# Spotter trackers left out of the nudge on purpose (see ENABLED_EXTRAS), plus a spotter quirk.
NOT_IN_THE_NUDGE = {"icycle", "isleep", "istairs", "ihydrate", "ilearn", "icoldshower", "eyepushups"}


class TestSpotter(unittest.TestCase):
    def setUp(self):
        self.triggers = {k.lower() for k in spotter.ACTIVITIES}

    def test_every_log_command_is_a_spotter_trigger(self):
        for key, (trigger, example) in dn.LOG_COMMANDS.items():
            self.assertIn(trigger, self.triggers, key)
            self.assertTrue(example.startswith(trigger + " "), key)

    def test_every_spotter_trigger_is_in_the_nudge_or_left_out_on_purpose(self):
        shown = {trigger for trigger, _ in dn.LOG_COMMANDS.values()}
        self.assertEqual(self.triggers - shown, NOT_IN_THE_NUDGE)


class TestClickIds(unittest.TestCase):
    """The memory buttons must carry action ids the memory click recipe lets through: the ones
    the memory step posts itself. Their values are unchanged, so the step reads them as before."""

    POSTED_BY_IMEMORY = {"imemory_start", "imemory_yes", "imemory_no", "imemory_again",
                         "imemory_daily", "imemory_try", "imemory_match_start"}

    def memory_ids(self, **extra):
        _, blocks = nudge("plank", **extra)
        row = next(b for b in blocks if b.get("block_id") == "nudge_break_memory")
        return {e["value"]: e["action_id"] for e in row["elements"]}

    def test_default_memory_buttons_use_ids_the_step_posts(self):
        ids = self.memory_ids()
        self.assertEqual(ids["anyone|0|play"], "imemory_start")
        self.assertEqual(ids["img|anyone|0|play"], "imemory_try")
        self.assertEqual(ids["imatch|anyone|0|join"], "imemory_match_start")
        for key in ("anyone|0|play", "img|anyone|0|play", "imatch|anyone|0|join"):
            self.assertIn(ids[key], self.POSTED_BY_IMEMORY)

    def test_values_are_unchanged_by_the_new_ids(self):
        self.assertEqual(set(self.memory_ids()),
                         set(self.memory_ids(button_ids="old")))

    def test_old_switch_keeps_the_previous_ids(self):
        ids = self.memory_ids(button_ids="old")
        self.assertEqual(ids["anyone|0|play"], "imemory_play")
        self.assertEqual(ids["img|anyone|0|play"], "imemory_play_img")

    def test_blank_or_unknown_switch_means_known(self):
        for value in ("", None, "nonsense"):
            self.assertEqual(self.memory_ids(button_ids=value)["anyone|0|play"], "imemory_start")

    def test_ids_in_a_row_stay_unique(self):
        for extra in ({}, {"button_ids": "old"}):
            _, blocks = nudge("plank", **extra)
            for block in blocks:
                if block["type"] == "actions":
                    ids = [e["action_id"] for e in block["elements"]]
                    self.assertEqual(len(ids), len(set(ids)))

    def test_imemory_game_nudge_play_button(self):
        _, blocks = nudge("imemory")
        self.assertEqual([e["action_id"] for e in blocks[2]["elements"]],
                         ["imemory_try", "imemory_start"])
        _, blocks = nudge("imemory", button_ids="old")
        self.assertEqual([e["action_id"] for e in blocks[2]["elements"]],
                         ["imemory_try", "imemory_play"])
        self.assertEqual(blocks[2]["elements"][1]["value"], "anyone|0|play")

    def test_maths_and_breathing_ids_untouched(self):
        _, blocks = nudge("isub")
        self.assertEqual([e["action_id"] for e in blocks[2]["elements"]], ["imath_try", "imath_play"])
        self.assertEqual(dn.click_id("ibreath_play"), "ibreath_play")
        self.assertEqual(dn.click_id("imath_play_iadd"), "imath_play_iadd")


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
