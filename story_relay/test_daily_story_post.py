"""
Tests for daily_story_post.py -- run before and after every change:

    python3 story_relay/test_daily_story_post.py

Stdlib only, no network: Azure is replaced by a fake that returns the answers a test queues.
"""
import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daily_story_post as dsp  # noqa: E402


class FakeAzure(object):
    """Stands in for dsp.Azure: returns the queued answers in order (the last one repeats)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []
        self.calls = 0

    def chat(self, system, user, max_tokens=700, temperature=0.4):
        self.prompts.append(user)
        self.calls += 1
        answer = self.answers[min(self.calls, len(self.answers)) - 1]
        return answer if isinstance(answer, str) else json.dumps(answer)


def with_questions(questions):
    """SAMPLE_CHAPTERS with each chapter's question replaced (None keeps the sample's)."""
    answer = copy.deepcopy(dsp.SAMPLE_CHAPTERS)
    for chapter, question in zip(answer["chapters"], questions):
        if question is not None:
            chapter["question"] = question
    return answer


LIMIT = dsp.TEXT_LIMITS["question"]
# A question that is a real question, ends with "?", and is over the limit.
LONG_Q = ("Does Sharon dare to name the team's hidden fear out loud, or let them keep their old "
          "comfortable routine?")
SHORT_Q = "Does she speak up, or keep the peace?"


def story_input(**extra):
    fields = {"story_title": "The Window Seat", "kb_name": "Sample story collection",
              "theme": "empathy", "story_text": dsp.SAMPLE_STORY, "story_author": "",
              "why_it_resonates": "One small question changed a colleague's week.",
              "main_character": "Priya", "lesson": "Noticing someone is kind.",
              "testing": "yes", "week": "2026-11-16", "today": "2026-11-15"}
    fields.update(extra)
    return fields


def run_save(llm, **extra):
    result = dsp._blank_result("save", "")
    dsp.do_save(story_input(**extra), result, dsp.Table(""), llm)
    return result


class ParseChapters(unittest.TestCase):
    def setUp(self):
        self.sentences = dsp.split_sentences(dsp.SAMPLE_STORY)
        self.first_end = dsp.first_passage(self.sentences, 25, 40)

    def parse(self, answer):
        return dsp.parse_chapters(answer, self.sentences, self.first_end)

    def test_sample_chapters_are_accepted(self):
        chapters, errors, _ = self.parse(dsp.SAMPLE_CHAPTERS)
        self.assertEqual(errors, [])
        self.assertEqual(len(chapters), dsp.CHAPTERS)
        self.assertEqual(chapters[1]["question"], "How does Priya respond?")

    def test_long_question_is_reported_as_too_long(self):
        self.assertGreater(len(LONG_Q), LIMIT)
        chapters, errors, _ = self.parse(with_questions([None, LONG_Q, LONG_Q, LONG_Q]))
        self.assertEqual(chapters, [])
        self.assertEqual(len(errors), 3)
        for number, error in zip((2, 3, 4), errors):
            self.assertIn("chapter {}".format(number), error)
            self.assertIn("{} characters".format(len(LONG_Q)), error)
            self.assertIn("over the limit of {}".format(LIMIT), error)
            # The old message blamed a missing "?" the model never left out, so it could not fix it.
            self.assertNotIn("must end with a question mark", error)

    def test_question_without_a_question_mark_is_still_reported(self):
        _, errors, _ = self.parse(with_questions([None, "Priya decides what to do.", None, None]))
        self.assertEqual(len(errors), 1)
        self.assertIn("chapter 2", errors[0])
        self.assertIn("question mark", errors[0])

    def test_question_exactly_at_the_limit_is_kept_whole(self):
        question = ("Does she speak up " + "x" * LIMIT)[:LIMIT - 1] + "?"
        self.assertEqual(len(question), LIMIT)
        chapters, errors, _ = self.parse(with_questions([None, question, None, None]))
        self.assertEqual(errors, [])
        self.assertEqual(chapters[1]["question"], question)

    def test_question_one_over_the_limit_is_rejected(self):
        question = "x" * LIMIT + "?"
        _, errors, _ = self.parse(with_questions([None, question, None, None]))
        self.assertEqual(len(errors), 1)
        self.assertIn("{} characters".format(LIMIT + 1), errors[0])

    def test_why_question_is_still_rejected(self):
        _, errors, _ = self.parse(with_questions([None, "Why does she stay quiet?", None, None]))
        self.assertTrue(any("not why" in e for e in errors), errors)


class Chapterise(unittest.TestCase):
    def setUp(self):
        self.story = {"title": "The Window Seat", "theme": "empathy", "main": "Priya", "lesson": ""}
        self.sentences = dsp.split_sentences(dsp.SAMPLE_STORY)
        self.first_end = dsp.first_passage(self.sentences, 25, 40)

    def test_prompt_states_the_character_limit_the_code_enforces(self):
        self.assertIn("{} characters".format(LIMIT), dsp.CHAPTER_SYSTEM)

    def test_a_too_long_answer_is_fixed_on_the_second_round(self):
        llm = FakeAzure(with_questions([None, LONG_Q, LONG_Q, LONG_Q]), dsp.SAMPLE_CHAPTERS)
        chapters, errors, _ = dsp.chapterise(llm, self.story, self.sentences, self.first_end)
        self.assertEqual(errors, [])
        self.assertEqual(len(chapters), dsp.CHAPTERS)
        self.assertEqual(llm.calls, 2)
        # What Azure is told to fix names the real problem and its size.
        self.assertIn("{} characters".format(len(LONG_Q)), llm.prompts[1])
        self.assertNotIn("must end with a question mark", llm.prompts[1])

    def test_an_answer_that_never_improves_is_mended_not_lost(self):
        llm = FakeAzure(with_questions([None, LONG_Q, LONG_Q, LONG_Q]))
        notes = []
        chapters, errors, _ = dsp.chapterise(llm, self.story, self.sentences, self.first_end, notes)
        self.assertEqual(errors, [])
        self.assertEqual(len(chapters), dsp.CHAPTERS)
        self.assertEqual(llm.calls, 2)              # told once, then mended without another call
        for chapter in chapters:
            self.assertTrue(chapter["question"].endswith("?"))
            self.assertLessEqual(len(chapter["question"]), LIMIT)
        self.assertEqual(len(notes), 3)

    def test_garbage_replies_are_retried_and_then_reported(self):
        llm = FakeAzure("not json", "", "[]")
        chapters, errors, _ = dsp.chapterise(llm, self.story, self.sentences, self.first_end)
        self.assertEqual(chapters, [])
        self.assertTrue(errors)
        self.assertEqual(llm.calls, dsp.CHAPTER_ATTEMPTS)

    def test_an_earlier_usable_answer_survives_a_later_garbage_one(self):
        llm = FakeAzure(with_questions([None, LONG_Q, None, None]), "not json", "not json")
        chapters, errors, _ = dsp.chapterise(llm, self.story, self.sentences, self.first_end)
        self.assertEqual(errors, [])
        self.assertEqual(len(chapters), dsp.CHAPTERS)


class RepairQuestion(unittest.TestCase):
    def check(self, text, number=2, main="Sharon Drew Morgen"):
        question = dsp.repair_question(text, number, main)
        self.assertTrue(question.endswith("?"), question)
        self.assertLessEqual(len(question), LIMIT, question)
        self.assertNotIn("\u2026", question)
        return question

    def test_a_good_question_is_untouched(self):
        self.assertEqual(self.check(SHORT_Q), SHORT_Q)

    def test_the_reported_case_is_cut_at_the_clause(self):
        self.assertEqual(self.check(LONG_Q), "Does Sharon dare to name the team's hidden fear out loud?")

    def test_missing_question_mark_is_added(self):
        self.assertEqual(self.check("Does she speak up, or keep the peace."), SHORT_Q)

    def test_the_last_question_of_several_sentences_is_kept(self):
        self.assertEqual(self.check("The room goes quiet. Does she speak up?"), "Does she speak up?")

    def test_unusable_questions_get_the_plain_one(self):
        self.assertEqual(self.check("", 2, "Priya, a new hire"), "What does Priya do next?")
        self.assertEqual(self.check("Why does she stay quiet?", 3, ""), "What does the main character do next?")
        self.assertEqual(self.check("x" * 200, 4), "How does the story end?")
        self.assertEqual(self.check(None, 4), "How does the story end?")

    def test_whatever_it_is_given_the_result_is_a_sound_question(self):
        for text in (None, "", "?", "...", "Why?", "a, b, c, d, e " * 20, "Does she\n\nspeak up",
                     'Does she say "no?"', "word " * 100, 5, ["x"], {"a": 1}):
            self.check(text if isinstance(text, (str, type(None))) else str(text))


class RepairChapters(unittest.TestCase):
    def setUp(self):
        self.sentences = dsp.split_sentences(dsp.SAMPLE_STORY)
        self.first_end = dsp.first_passage(self.sentences, 25, 40)

    def repair(self, answer, notes=None):
        return dsp.repair_chapters(answer, self.sentences, self.first_end, "Priya", notes)

    def assert_sound(self, chapters):
        """What every chapter must be for the post to work, whatever was wrong before."""
        self.assertEqual(len(chapters), dsp.CHAPTERS)
        previous = self.first_end
        for number, chapter in enumerate(chapters, 1):
            for field in ("snippet", "setup", "question", "real", "twist"):
                self.assertTrue(chapter[field], (number, field))
            self.assertTrue(chapter["question"].endswith("?"))
            self.assertLessEqual(len(chapter["question"]), LIMIT)
            if number > 1:
                self.assertGreater(chapter["from"], previous)
                self.assertLessEqual(chapter["from"], chapter["to"])
            self.assertLess(chapter["to"], len(self.sentences) - 1)     # a sentence is left to follow
            previous = chapter["to"]

    def test_good_chapters_come_through_unchanged(self):
        notes = []
        chapters, _ = self.repair(dsp.SAMPLE_CHAPTERS, notes)
        self.assertEqual(notes, [])
        self.assertEqual(chapters[1]["question"], "How does Priya respond?")
        self.assert_sound(chapters)

    def test_bad_sentence_numbers_become_an_even_share(self):
        answer = copy.deepcopy(dsp.SAMPLE_CHAPTERS)
        for chapter, (a, b) in zip(answer["chapters"][1:], ((9, 2), ("x", None), (500, 600))):
            chapter["from"], chapter["to"] = a, b
        notes = []
        chapters, _ = self.repair(answer, notes)
        self.assert_sound(chapters)
        self.assertEqual(len(notes), 3)

    def test_empty_lines_are_filled_and_real_comes_from_the_story(self):
        answer = copy.deepcopy(dsp.SAMPLE_CHAPTERS)
        answer["chapters"][1].update({"setup": "", "real": None, "twist": "  "})
        chapters, _ = self.repair(answer)
        self.assert_sound(chapters)
        self.assertEqual(chapters[1]["real"], self.sentences[chapters[1]["to"] + 1])

    def test_a_twist_that_copies_the_real_option_is_replaced(self):
        answer = copy.deepcopy(dsp.SAMPLE_CHAPTERS)
        answer["chapters"][2]["twist"] = answer["chapters"][2]["real"]
        chapters, _ = self.repair(answer)
        self.assertNotEqual(chapters[2]["twist"], chapters[2]["real"])

    def test_chapters_that_are_not_objects_are_filled_in(self):
        answer = {"chapters": ["a", None, 3, []]}
        chapters, _ = self.repair(answer)
        self.assert_sound(chapters)

    def test_extra_chapters_are_dropped(self):
        answer = copy.deepcopy(dsp.SAMPLE_CHAPTERS)
        answer["chapters"].append(copy.deepcopy(answer["chapters"][0]))
        chapters, _ = self.repair(answer)
        self.assert_sound(chapters)

    def test_no_chapters_at_all_is_the_only_hopeless_answer(self):
        for answer in (None, [], {}, {"chapters": "x"}, {"chapters": [{}, {}, {}]}):
            self.assertEqual(self.repair(answer), ([], []))

    def test_every_kind_of_bad_answer_gives_a_sound_story(self):
        junk = [None, "", " ", 7, [], {}, "no?", "x" * 500, "Why?", {"a": 1}, float("nan"), float("inf")]
        for bad in junk:
            answer = {"chapters": [{"setup": bad, "question": bad, "real": bad, "twist": bad,
                                    "from": bad, "to": bad} for _ in range(dsp.CHAPTERS)]}
            chapters, _ = self.repair(answer)
            self.assert_sound(chapters)


class DoSave(unittest.TestCase):
    def test_good_chapters_make_a_ready_story(self):
        result = run_save(FakeAzure(dsp.SAMPLE_CHAPTERS))
        self.assertEqual(result["error"], "")
        self.assertEqual(result["status"], dsp.READY)
        self.assertIn("Chapter 4", result["chapters_preview"])

    def test_the_reported_failure_no_longer_fails(self):
        """Chapters 2-4 had questions over the limit and the week's story was lost ("must end with a
        question mark", twice). It is now saved, with a note saying what was mended."""
        result = run_save(FakeAzure(with_questions([None, LONG_Q, LONG_Q, LONG_Q])))
        self.assertEqual(result["error"], "")
        self.assertEqual(result["status"], dsp.READY)
        self.assertTrue(any("needed mending" in w for w in result["warnings"]), result["warnings"])
        self.assertIn("Does Sharon dare to name the team's hidden fear out loud?",
                      result["chapters_preview"])

    def test_azure_giving_nothing_usable_is_still_reported(self):
        result = run_save(FakeAzure("not json"))
        self.assertTrue(result["retry"])
        self.assertIn("could not be cut into four chapters", result["error"])

    def test_a_long_question_never_reaches_a_saved_story_clipped(self):
        """The first answer's long question is rejected and replaced by the second answer's: the
        story that is kept has no question cut short with an ellipsis."""
        result = run_save(FakeAzure(with_questions([None, LONG_Q, None, None]), dsp.SAMPLE_CHAPTERS))
        self.assertEqual(result["error"], "")
        self.assertNotIn("…", result["chapters_preview"])


# --------------------------------------------------------------------------
# Button clicks and the "write your own plot" box
# --------------------------------------------------------------------------

WEEK = "2026-11-16"


class FakeTable(object):
    """The data table in memory: a story row and the picks written to it."""

    def __init__(self, posted=(2,), settled=()):
        self.token = "t"
        self.errors = []
        self.written = 0
        pack = dsp.sample_pack()
        state = dsp.new_state()
        state["posts"] = {str(c): "170000000{}.0001".format(c) for c in posted}
        state["settled"] = list(settled)
        self.row = {"week_key": WEEK, "status": dsp.OPEN, "$record_id": "r1",
                    "content": dsp.dump_content(pack, state)}
        self.pick_rows = []

    def story(self, week):
        return self.row if week == WEEK else None

    def picks(self, week, chapter=None, user=None):
        return [r for r in self.pick_rows if r["week_key"] == week
                and (not chapter or str(r["grant_type"]) == str(chapter))
                and (not user or r["group_id"] == user)]

    def create(self, fields):
        self.pick_rows.append(dict(fields))
        self.written += 1
        return True

    def update(self, record_id, fields):
        self.written += 1
        return True


class ClickHelpers(unittest.TestCase):
    """setUp, tearDown and click(): Slack and the data table are fakes. No tests of its own."""

    def setUp(self):
        self.sent = {"notes": [], "updates": []}
        self.saved = {name: getattr(dsp, name) for name in
                      ("slack_ephemeral", "slack_user_name", "slack_update")}
        dsp.slack_ephemeral = lambda token, channel, user, text: self.sent["notes"].append((user, text)) or None
        dsp.slack_user_name = lambda token, user: "Asha Rao"
        dsp.slack_update = lambda token, channel, ts, text, blocks: self.sent["updates"].append(ts) or None

    def tearDown(self):
        for name, fn in self.saved.items():
            setattr(dsp, name, fn)

    def click(self, table, value, user="U1", **extra):
        result = dsp._blank_result("click", "C1")
        result["user_id"] = user
        fields = {"action_value": value, "slack_bot_token": "x", "action_ts": "1.{}".format(len(table.pick_rows))}
        fields.update(extra)
        dsp.do_click(fields, result, table)
        return result


class Clicks(ClickHelpers):
    def test_every_button_of_a_chapter_starts_with_the_prefix(self):
        view = dsp.chapter_view(dsp.sample_pack(), {}, 2, WEEK)
        buttons = [e for b in view["blocks"] if b["type"] == "actions" for e in b["elements"]]
        self.assertEqual([b["action_id"] for b in buttons], ["story_relay_plot_1", "story_relay_plot_2"])
        for b in buttons:
            self.assertTrue(b["action_id"].startswith(dsp.ACTION_PREFIX))
            self.assertIsNotNone(dsp.parse_value(b["value"]), b["value"])
        self.assertEqual(sorted(dsp.parse_value(b["value"])["choice"] for b in buttons), ["divert", "real"])

    def test_the_mode_is_guessed_from_the_input(self):
        self.assertEqual(dsp.guess_mode({"action_value": "story|pick|w|2|real"}), "click")
        self.assertEqual(dsp.guess_mode({"submission_json": "{}"}), "post")      # no box any more
        self.assertEqual(dsp.guess_mode({}), "post")

    def test_main_routes_a_click(self):
        result = dsp.main({"action_value": dsp.pick_value(WEEK, 2, "real")})    # no token: stops at the first check
        self.assertEqual(result["mode"], "click")
        self.assertIn("user_id, channel and slack_bot_token", result["error"])
        self.assertIn("mode is history, prepare, announce, post or click", dsp.main({"mode": "submit"})["error"])

    def test_a_plot_twist_click_records_the_pick_and_redraws_the_count(self):
        table = FakeTable()
        value = dsp.pick_value(WEEK, 2, "real")
        result = self.click(table, value)
        self.assertEqual(result["error"], "")
        self.assertTrue(result["recorded"])
        self.assertEqual(len(table.pick_rows), 1)
        row = table.pick_rows[0]
        self.assertEqual((row["group_id"], row["grant_type"], row["status"], row["name"]),
                         ("U1", "2", "real", "Asha Rao"))
        self.assertIn("Locked in", self.sent["notes"][0][1])
        self.assertEqual(result["picks_in"], 1)
        self.assertEqual(self.sent["updates"], ["1700000002.0001"])

    def test_a_second_click_by_the_same_person_is_not_counted(self):
        table = FakeTable()
        self.click(table, dsp.pick_value(WEEK, 2, "real"))
        result = self.click(table, dsp.pick_value(WEEK, 2, "divert"))
        self.assertFalse(result["recorded"])
        self.assertEqual(len(table.pick_rows), 1)
        self.assertIn("already", self.sent["notes"][-1][1])

    def test_two_people_both_count(self):
        table = FakeTable()
        self.click(table, dsp.pick_value(WEEK, 2, "real"), user="U1")
        self.click(table, dsp.pick_value(WEEK, 2, "divert"), user="U2")
        self.assertEqual(len(table.pick_rows), 2)

    def test_a_click_on_a_closed_chapter_is_refused_kindly(self):
        table = FakeTable(posted=(1, 2), settled=(1,))
        result = self.click(table, dsp.pick_value(WEEK, 1, "real"))
        self.assertFalse(result["recorded"])
        self.assertEqual(table.pick_rows, [])
        self.assertIn("closed", self.sent["notes"][-1][1])
        self.assertTrue(result["ok"])

    def test_there_is_no_write_your_own_plot_left(self):
        for name in ("modal_view", "do_submit", "clean_custom", "group_customs", "moderate", "plot_groups",
                     "slack_views_open", "find_plot_text", "custom_value", "split_credit", "echo_text"):
            self.assertFalse(hasattr(dsp, name), name)
        view = dsp.chapter_view(dsp.sample_pack(), {}, 2, WEEK)
        self.assertNotIn("custom", json.dumps(view["blocks"]))
        self.assertNotIn("own plot", json.dumps(view["blocks"]).lower())
        self.assertIsNone(dsp.parse_value("story|custom|2026-11-16|2"))
        self.assertIsNone(dsp.parse_value("story|pick|2026-11-16|2|custom"))
        blank = dsp._blank_result("post", "")
        self.assertNotIn("opened_modal", blank)
        self.assertNotIn("views_open_body", blank)

    def test_a_click_that_is_not_one_of_the_two_buttons_changes_nothing(self):
        table = FakeTable()
        result = self.click(table, "story|custom|{}|2".format(WEEK))
        self.assertIn("not a story relay button", result["error"])
        self.assertEqual(table.pick_rows, [])


class TheCount(ClickHelpers):
    def entry(self, *choices):
        return dsp.tally_picks([{"id": "U{}".format(i), "choice": c, "ts": str(i), "order": i}
                                for i, c in enumerate(choices)])

    def test_the_turn_with_the_most_picks_wins(self):
        self.assertEqual(self.entry("divert", "divert", "real")["choice"], "divert")
        self.assertEqual(self.entry("real", "real", "divert")["choice"], "real")

    def test_a_tie_keeps_the_story_as_it_happened(self):
        entry = self.entry("divert", "real")
        self.assertEqual((entry["choice"], entry["quiet"], entry["picks"]), ("real", False, 2))

    def test_a_chapter_nobody_picked_on_keeps_the_story(self):
        entry = self.entry()
        self.assertEqual((entry["choice"], entry["quiet"], entry["picks"]), ("real", True, 0))

    def test_old_rows_of_a_kind_that_no_longer_exists_count_for_nothing(self):
        entry = self.entry("custom", "custom", "divert")
        self.assertEqual((entry["choice"], entry["picks"]), ("divert", 1))

    def test_a_week_saved_before_with_a_written_plot_still_draws_and_publishes(self):
        pack = dsp.sample_pack()
        legacy = {"1": {"choice": "custom", "text": "ben goes to watch a movie", "author": "A", "group": 1,
                        "picks": 2, "quiet": False},
                  "2": {"choice": "real", "picks": 1, "quiet": False}}
        for chapter in (1, 2, 3):
            view = dsp.chapter_view(pack, legacy, chapter, WEEK,
                                    closed={"choice": "custom", "text": "x", "author": "A", "picks": 2})
            self.assertEqual(dsp.block_problems(view["blocks"]), [])
        post = dsp.publish_view(pack, legacy, ["A"], dsp.assembled_story(pack, legacy))
        self.assertEqual(dsp.block_problems(post["blocks"]), [])



# --------------------------------------------------------------------------
# The Workato schemas must match the code
# --------------------------------------------------------------------------

import ast  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
_REAL_NOW = dsp._utc_now


def schema(name):
    with open(os.path.join(HERE, name)) as handle:
        return json.load(handle)


class Schemas(unittest.TestCase):
    def inputs_read_by_the_code(self):
        """Every input.get("name") in the step. (`fields` is the story the prepare mode builds from
        the table itself, so those names are not recipe inputs.)"""
        with open(dsp.__file__.replace(".pyc", ".py")) as handle:
            tree = ast.parse(handle.read())
        names = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "input" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                names.add(node.args[0].value)
        return names

    def test_every_input_the_code_reads_is_in_the_input_schema(self):
        declared = {f["name"] for f in schema("story_relay_input_schema.json")}
        self.assertEqual(self.inputs_read_by_the_code() - declared, set())

    def test_no_input_in_the_schema_is_ignored_by_the_code(self):
        declared = {f["name"] for f in schema("story_relay_input_schema.json")}
        self.assertEqual(declared - self.inputs_read_by_the_code(), set())

    def test_the_output_schema_is_exactly_what_the_step_returns(self):
        declared = [f["name"] for f in schema("story_relay_output_schema.json")]
        self.assertEqual(declared, list(dsp._blank_result("post", "").keys()))

    def test_output_types_match_the_values(self):
        kinds = {str: "string", bool: "boolean", int: "integer", list: "array"}
        for field in schema("story_relay_output_schema.json"):
            value = dsp._blank_result("post", "")[field["name"]]
            self.assertEqual(field["type"], kinds[type(value)], field["name"])

    def test_every_field_has_the_keys_workato_needs(self):
        for name in ("story_relay_input_schema.json", "story_relay_output_schema.json"):
            names = []
            for field in schema(name):
                for key in ("control_type", "label", "name", "type", "optional"):
                    self.assertIn(key, field, (name, field.get("name")))
                names.append(field["name"])
            self.assertEqual(len(names), len(set(names)), name)

    def test_the_mode_choices_are_the_modes_main_accepts(self):
        mode = next(f for f in schema("story_relay_input_schema.json") if f["name"] == "mode")
        for _label, value in mode["pick_list"]:
            result = dsp.main({"mode": value})
            self.assertNotIn("mode is history", result["error"], value)

    def test_a_recipe_sending_checkboxes_and_numbers_as_text_still_works(self):
        # Workato sends a ticked checkbox as true and a number field as text.
        result = dsp.main({"mode": "post", "testing": True, "skip_post": True, "chapter": "2",
                           "passage_words": "40", "wrap_chars": "84", "tz_offset": "19800"})
        self.assertEqual(result["error"], "")
        self.assertEqual(result["chapter"], 2)
        self.assertEqual(result["passage_words"], 40)


# --------------------------------------------------------------------------
# The pick count and the closing time
# --------------------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402


def utc(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def footer_text(view):
    """The small status line under the buttons."""
    contexts = [b["elements"][0]["text"] for b in view["blocks"] if b["type"] == "context"]
    return contexts[-1]


class ClosingTime(unittest.TestCase):
    def test_the_next_noon_pacific_is_chosen(self):
        closes = dsp.picks_deadline(utc("2026-11-17 03:30"))          # Tuesday morning in India
        self.assertEqual(closes["at"], int(utc("2026-11-17 20:00").timestamp()))
        self.assertEqual(closes["label"], "Tue 12:00 PM PST")

    def test_a_post_close_to_the_time_gets_the_next_day(self):
        closes = dsp.picks_deadline(utc("2026-11-17 19:30"))          # 11:30 PST, 30 minutes away
        self.assertEqual(closes["at"], int(utc("2026-11-18 20:00").timestamp()))

    def test_other_times_and_zones(self):
        closes = dsp.picks_deadline(utc("2026-11-17 03:30"), "10:30", 19800)
        self.assertEqual(closes["at"], int(utc("2026-11-17 05:00").timestamp()))
        self.assertEqual(closes["label"], "Tue 10:30 AM IST")
        self.assertEqual(dsp.tz_label(-3 * 3600), "UTC-3")
        self.assertEqual(dsp.tz_label(5 * 3600 + 1800 + 900), "UTC+5:45")

    def test_a_bad_time_falls_back_to_noon(self):
        for bad in ("", "noon", "25:00", "12:75", None):
            self.assertEqual(dsp.picks_deadline(utc("2026-11-17 03:30"), bad)["label"],
                             "Tue 12:00 PM PST", bad)


class CountAndNotes(ClickHelpers):
    def view(self, picks, closes=None):
        return dsp.chapter_view(dsp.sample_pack(), {}, 2, WEEK, picks=picks, closes=closes)

    def test_the_post_says_how_many_picks_are_in(self):
        self.assertIn("No picks yet", footer_text(self.view(0)))
        self.assertIn("*1* pick in so far", footer_text(self.view(1)))
        self.assertIn("*5* picks in so far", footer_text(self.view(5)))

    def test_the_closing_time_is_shown_in_every_readers_own_zone(self):
        closes = dsp.picks_deadline(utc("2026-11-17 03:30"))
        line = footer_text(self.view(2, closes))
        self.assertIn("<!date^{}^{{date_short_pretty}} at {{time}}|Tue 12:00 PM PST>".format(closes["at"]), line)
        self.assertEqual(dsp.block_problems(self.view(2, closes)["blocks"]), [])

    def test_without_a_closing_time_the_old_wording_stays(self):
        self.assertIn("with tomorrow's chapter", footer_text(self.view(2)))

    def test_it_never_shows_how_each_option_is_doing(self):
        # Counts per option would sway the late pickers; only the total is shown.
        text = json.dumps(self.view(7)["blocks"])
        self.assertNotIn("Plot twist 1 (", text)
        self.assertNotRegex(text, r"Plot twist \d[^\"]*\d+ (pick|vote)")

    def test_a_click_redraws_the_count_and_the_note_repeats_it(self):
        table = FakeTable()
        self.drawn = []
        dsp.slack_update = lambda token, channel, ts, text, blocks: self.drawn.append(blocks) or None
        self.click(table, dsp.pick_value(WEEK, 2, "real"), user="U1")
        self.click(table, dsp.pick_value(WEEK, 2, "divert"), user="U2")
        self.assertIn("*1* pick in so far", footer_text({"blocks": self.drawn[0]}))
        self.assertIn("*2* picks in so far", footer_text({"blocks": self.drawn[1]}))
        self.assertIn("1 pick in so far.", self.sent["notes"][0][1])
        self.assertIn("2 picks in so far.", self.sent["notes"][1][1])

    def test_the_note_carries_the_closing_time_when_there_is_one(self):
        table = FakeTable()
        closes = dsp.picks_deadline(utc("2026-11-17 03:30"))
        state = dsp.load_row(table.row)[1]
        state["closes"] = {"2": closes}
        table.row["content"] = dsp.dump_content(dsp.sample_pack(), state)
        dsp._utc_now = lambda: utc("2026-11-17 10:00")
        try:
            self.click(table, dsp.pick_value(WEEK, 2, "real"))
        finally:
            dsp._utc_now = _REAL_NOW
        self.assertIn("Picks close <!date^{}".format(closes["at"]), self.sent["notes"][0][1])

    def test_a_pick_after_the_closing_time_is_refused(self):
        table = FakeTable()
        closes = dsp.picks_deadline(utc("2026-11-17 03:30"))
        state = dsp.load_row(table.row)[1]
        state["closes"] = {"2": closes}
        table.row["content"] = dsp.dump_content(dsp.sample_pack(), state)
        dsp._utc_now = lambda: utc("2026-11-17 20:01")               # a minute after 12:00 PST
        try:
            twist = self.click(table, dsp.pick_value(WEEK, 2, "real"))
        finally:
            dsp._utc_now = _REAL_NOW
        self.assertEqual(table.pick_rows, [])
        self.assertFalse(twist["recorded"])
        note = self.sent["notes"][0][1]
        self.assertIn("closed <!date^{}".format(closes["at"]), note)      # says WHEN, in the reader's own zone
        self.assertIn("could not be counted", note)

    def test_a_chapter_posted_before_closing_times_existed_never_expires(self):
        table = FakeTable()                                           # its state has no closes
        dsp._utc_now = lambda: utc("2030-01-01 00:00")
        try:
            result = self.click(table, dsp.pick_value(WEEK, 2, "real"))
        finally:
            dsp._utc_now = _REAL_NOW
        self.assertTrue(result["recorded"])

    def test_the_test_post_shows_the_closing_time_too(self):
        result = dsp.main({"mode": "post", "testing": True, "skip_post": True, "chapter": 2,
                           "picks_close_time": "09:00", "picks_close_tz": "19800"})
        self.assertEqual(result["error"], "")
        self.assertIn("9:00 AM IST", result["blocks_json"])


# --------------------------------------------------------------------------
# One pick on every chapter
# --------------------------------------------------------------------------

class PickOnEveryChapter(ClickHelpers):
    def test_a_person_can_pick_on_every_chapter(self):
        table = FakeTable(posted=(2, 3))
        a = self.click(table, dsp.pick_value(WEEK, 2, "real"))
        b = self.click(table, dsp.pick_value(WEEK, 3, "divert"))
        self.assertTrue(a["recorded"] and b["recorded"])
        self.assertEqual(sorted(r["grant_type"] for r in table.pick_rows), ["2", "3"])
        self.assertFalse(any("used your pick" in n[1] or "already used" in n[1] for n in self.sent["notes"]))

    def test_still_only_one_pick_on_the_same_chapter(self):
        table = FakeTable()
        self.click(table, dsp.pick_value(WEEK, 2, "real"))
        again = self.click(table, dsp.pick_value(WEEK, 2, "divert"))
        self.assertFalse(again["recorded"])
        self.assertEqual(len(table.pick_rows), 1)
        self.assertIn("already picked on chapter 2", self.sent["notes"][-1][1])
        self.assertIn("tomorrow's chapter", self.sent["notes"][-1][1])

    def test_a_week_saved_with_the_old_one_pick_limit_no_longer_blocks(self):
        table = FakeTable(posted=(2, 3))
        state = dsp.load_row(table.row)[1]
        state["picks_per_week"] = 1                 # what a week prepared before this change holds
        state.pop("picks_cap", None)
        table.row["content"] = dsp.dump_content(dsp.sample_pack(), state)
        self.click(table, dsp.pick_value(WEEK, 2, "real"))
        second = self.click(table, dsp.pick_value(WEEK, 3, "real"))
        self.assertTrue(second["recorded"])

    def test_a_weekly_cap_can_still_be_set(self):
        table = FakeTable(posted=(2, 3))
        state = dsp.load_row(table.row)[1]
        state["picks_cap"] = 1
        table.row["content"] = dsp.dump_content(dsp.sample_pack(), state)
        self.click(table, dsp.pick_value(WEEK, 2, "real"))
        second = self.click(table, dsp.pick_value(WEEK, 3, "real"))
        self.assertFalse(second["recorded"])
        self.assertIn("all 1 of your picks", self.sent["notes"][-1][1])

    def test_the_cap_input(self):
        for value, expected in ((None, 0), ("", 0), ("0", 0), ("1", 1), ("3", 3), ("4", 0), ("9", 0), ("x", 0)):
            self.assertEqual(dsp.picks_cap_input({"picks_per_week": value}), expected, value)

    def test_the_post_and_the_notes_say_one_pick_on_every_chapter(self):
        view = dsp.chapter_view(dsp.sample_pack(), {}, 2, WEEK)
        self.assertIn("One pick each, on every chapter", json.dumps(view["blocks"]))
        self.assertNotIn("this week", json.dumps(view["blocks"]))
        self.assertNotIn("this week", dsp.NOTE_LOCKED)


# --------------------------------------------------------------------------
# Every refusal says why, so the person can put it right
# --------------------------------------------------------------------------

class RefusalsSayWhy(ClickHelpers):
    def test_a_pick_on_a_chapter_that_was_already_counted_says_so(self):
        table = FakeTable(posted=(1, 2), settled=(1,))
        self.click(table, dsp.pick_value(WEEK, 1, "real"))
        self.assertIn("already been counted", self.sent["notes"][-1][1])
        self.assertIn("newest Story Relay post", self.sent["notes"][-1][1])

    def test_a_pick_on_a_chapter_not_posted_yet_says_so(self):
        table = FakeTable(posted=(2,))
        self.click(table, dsp.pick_value(WEEK, 4, "real"))
        self.assertIn("has not been posted", self.sent["notes"][-1][1])

    def test_each_closed_reason_is_its_own(self):
        pack_state = dsp.new_state()
        pack_state["posts"] = {"2": "1.1", "3": "1.2"}
        pack_state["settled"] = [2]
        pack_state["closes"] = {"3": {"at": 1, "label": "Mon 12:00 AM UTC"}}
        self.assertEqual(dsp.chapter_status(pack_state, 4)[0], "not_posted")
        self.assertEqual(dsp.chapter_status(pack_state, 2)[0], "settled")
        self.assertEqual(dsp.chapter_status(pack_state, 3)[0], "deadline")
        pack_state["closes"] = {}
        self.assertEqual(dsp.chapter_status(pack_state, 3)[0], "open")

    def test_a_failed_save_names_what_failed(self):
        table = FakeTable()
        table.create = lambda fields: False
        result = self.click(table, dsp.pick_value(WEEK, 2, "real"))
        self.assertEqual(result["error"], "the pick could not be saved")
        self.assertIn("the data table did not accept the pick", self.sent["notes"][-1][1])

    def test_no_note_is_left_with_an_unfilled_blank(self):
        for name in dir(dsp):
            if name.startswith("NOTE_") and name != "NOTE_ECHO":
                self.assertNotRegex(getattr(dsp, name).replace("{why}", "x").replace("{reason}", "x")
                                    .replace("{echo}", "").replace("{chapter}", "1").replace("{choice}", "x")
                                    .replace("{cap}", "1").replace("{when}", "x").replace("{count}", "1")
                                    .replace("{s}", ""), r"\{[a-z_]+\}", name)


# --------------------------------------------------------------------------
# The bridge: what the team chose, stitched into the story
# --------------------------------------------------------------------------

from datetime import date  # noqa: E402

GOOD_BRIDGE = ("Ben spent the whole day on the sofa, a film playing and the unpaid bill forgotten. By evening "
               "the bitterness had not gone, and the milk he had given away still sat in his mind.")


def diverged_canon():
    """Chapter 1 took the prepared twist, so the story has left the original path."""
    return {"1": {"choice": "divert", "picks": 2, "quiet": False}}


class TheBridge(ClickHelpers):
    def setUp(self):
        ClickHelpers.setUp(self)
        self.pack = dsp.sample_pack()
        self.posted = []
        self.saved_post = (dsp.slack_post, dsp.slack_delete)
        dsp.slack_post = lambda token, channel, text, blocks: self.posted.append(blocks) or ("1700000099.0001", None)
        dsp.slack_delete = lambda *a: None

    def tearDown(self):
        dsp.slack_post, dsp.slack_delete = self.saved_post
        ClickHelpers.tearDown(self)

    def run_post(self, llm, canon, chapter=2):
        table = FakeTable(posted=(1,), settled=(1,))
        pack, state = dsp.load_row(table.row)
        state["canon"] = canon
        result = dsp._blank_result("post", "C1")
        run = dsp.Run(table, llm, "x", "C1", result, date(2026, 11, 17), 84, "", False, 50)
        dsp.post_chapter(run, table.row, pack, state, chapter)
        return result, state

    def story_text(self, blocks):
        """The story's text as a person reads it: the hard wrap (and the style marks it closes and reopens
        at each cut) taken out."""
        text = " ".join(b["text"]["text"] for b in blocks if b["type"] == "section")
        return text.replace("_\n_", " ").replace("\n", " ")

    def test_the_model_is_given_the_choices_the_setting_and_the_next_question(self):
        prompt = dsp.bridge_prompt(self.pack, diverged_canon(), 2)
        self.assertIn(self.pack["chapters"][0]["twist"], prompt)      # what the team chose
        self.assertNotIn("written by", prompt)
        self.assertIn(self.pack["chapters"][1]["question"], prompt)
        self.assertIn(self.pack["chapters"][1]["snippet"], prompt)
        self.assertIn("do not bring back events", prompt)

    def test_the_instructions_make_the_choices_true_and_leave_room_to_steer_back(self):
        system = dsp.BRIDGE_SYSTEM
        self.assertIn("Treat every choice as true", system)
        self.assertIn("Never bring back events", system)
        self.assertIn("back on course", system)
        self.assertIn("without answering it", system)

    def test_a_chapter_on_a_different_turn_shows_the_bridge(self):
        llm = FakeAzure({"bridge": GOOD_BRIDGE})
        result, state = self.run_post(llm, diverged_canon())
        self.assertEqual(result["error"], "")
        self.assertEqual(llm.calls, 1)
        shown = self.story_text(self.posted[0])
        self.assertIn("Ben spent the whole day on the sofa", shown)
        self.assertNotIn(self.pack["chapters"][1]["setup"], shown)         # the one-liner stands down
        self.assertEqual(state["bridges"]["2"], GOOD_BRIDGE)               # kept for every later redraw

    def test_a_chapter_on_the_original_path_makes_no_model_call(self):
        llm = FakeAzure({"bridge": GOOD_BRIDGE})
        result, state = self.run_post(llm, {"1": {"choice": "real", "picks": 2, "quiet": False}})
        self.assertEqual(llm.calls, 0)
        self.assertEqual(state["bridges"], {})
        self.assertIn(self.pack["chapters"][1]["snippet"].split(".")[0], self.story_text(self.posted[0]))

    def test_a_bridge_that_fails_its_checks_is_tried_again_then_built_by_the_program(self):
        for bad in ({"bridge": "Too short."},
                    {"bridge": "<!channel> " + GOOD_BRIDGE},
                    {"bridge": GOOD_BRIDGE + " Then he said https://evil.example to everyone"},
                    {"bridge": "He went to fuck off for the day and he did so for a long and quiet while there"},
                    {"nothing": "here"}, "not json", ""):
            llm = FakeAzure(bad)
            result, state = self.run_post(llm, diverged_canon())
            self.assertEqual(result["error"], "", bad)
            self.assertEqual(llm.calls, 2, bad)                              # a second try first
            shown = self.story_text(self.posted[-1])
            self.assertIn(self.pack["chapters"][0]["twist"], shown, bad)                 # what the team chose
            self.assertIn(self.pack["chapters"][1]["setup"], shown, bad)                 # then the set-up
            self.assertEqual(state["bridges"]["2"], dsp.plain_bridge(self.pack, diverged_canon(), 2), bad)
            self.assertTrue(any("plain bridge was built" in w for w in result["warnings"]), bad)

    def test_a_second_try_that_works_is_used(self):
        llm = FakeAzure({"bridge": "Too short."}, {"bridge": GOOD_BRIDGE})
        result, state = self.run_post(llm, diverged_canon())
        self.assertEqual(llm.calls, 2)
        self.assertEqual(state["bridges"]["2"], GOOD_BRIDGE)
        self.assertFalse(any("plain bridge" in w for w in result["warnings"]))

    def test_no_model_key_still_gets_a_bridge(self):
        result, state = self.run_post(None, diverged_canon())
        self.assertEqual(result["error"], "")
        self.assertEqual(state["bridges"]["2"], dsp.plain_bridge(self.pack, diverged_canon(), 2))
        self.assertIn(self.pack["chapters"][0]["twist"], self.story_text(self.posted[-1]))
        self.assertTrue(any("azure_api_key" in w for w in result["warnings"]))

    def test_the_plain_bridge_follows_whatever_was_chosen(self):
        chapter3 = lambda canon: dsp.plain_bridge(self.pack, canon, 3)
        # a prepared twist, then a chapter nobody picked on: each still gets a bridge
        twisted = {"1": {"choice": "divert"}, "2": {"choice": "divert"}}
        missed = {"1": {"choice": "real", "missed": True}, "2": {"choice": "real", "quiet": True}}
        for canon in (twisted, missed):
            bridge = chapter3(canon)
            self.assertIn(self.pack["chapters"][2]["setup"], bridge)
            self.assertTrue(bridge.endswith("."))
        self.assertIn(self.pack["chapters"][1]["twist"], chapter3(twisted))

    def test_every_non_real_turn_gets_a_bridge_when_posted(self):
        canon = {"1": {"choice": "divert", "picks": 1, "quiet": False}}
        result, state = self.run_post(FakeAzure({"bridge": GOOD_BRIDGE}), canon)
        self.assertIn("2", state["bridges"])

    def test_a_click_redraws_the_chapter_with_the_same_bridge(self):
        table = FakeTable(posted=(1, 2), settled=(1,))
        pack, state = dsp.load_row(table.row)
        state["canon"] = diverged_canon()
        state["bridges"] = {"2": GOOD_BRIDGE}
        table.row["content"] = dsp.dump_content(pack, state)
        drawn = []
        dsp.slack_update = lambda token, channel, ts, text, blocks: drawn.append(blocks) or None
        self.click(table, dsp.pick_value(WEEK, 2, "real"))
        self.assertIn("Ben spent the whole day on the sofa", self.story_text(drawn[-1]))
        self.assertIn("*1* pick in so far", footer_text({"blocks": drawn[-1]}))

    def test_the_closed_chapter_keeps_the_bridge_too(self):
        view = dsp.chapter_view(self.pack, diverged_canon(), 2, WEEK,
                                closed={"choice": "real", "picks": 3, "quiet": False}, bridge=GOOD_BRIDGE)
        self.assertIn("Ben spent the whole day on the sofa", self.story_text(view["blocks"]))

    def test_a_new_week_starts_with_no_bridges(self):
        self.assertEqual(dsp.new_state()["bridges"], {})

    def test_the_week_restart_clears_them(self):
        table = FakeTable(posted=(1, 2), settled=(1,))
        pack, state = dsp.load_row(table.row)
        state["bridges"] = {"2": GOOD_BRIDGE}
        result = dsp._blank_result("post", "C1")
        run = dsp.Run(table, None, "x", "C1", result, date(2026, 11, 17), 84, "", False, 50)
        table.picks = lambda *a, **k: []
        self.assertTrue(dsp.restart_week(run, table.row, pack, state))
        self.assertEqual(state["bridges"], {})


# --------------------------------------------------------------------------
# Friday: where we split from the real story
# --------------------------------------------------------------------------

def friday_canon():
    """Chapters 1, 3 and 4 took the prepared twist; chapter 2 went as it happened."""
    return {"1": {"choice": "divert", "picks": 3, "quiet": False},
            "2": {"choice": "real", "picks": 2, "quiet": False},
            "3": {"choice": "divert", "picks": 2, "quiet": False},
            "4": {"choice": "divert", "picks": 2, "quiet": False}}


GOOD_SPLIT = {"lines": [
    {"chapter": 1, "line": "Really, Ben stayed stuck on the bill, but we sent him off for a movie-and-nap day instead."},
    {"chapter": 3, "line": "In the real story he held his ground, while ours had him soften with a much gentler idea."},
    {"chapter": 4, "line": "The real Ben kept his gift quiet, and ours spread the milk around the whole street."}]}


class FridaySplit(ClickHelpers):
    def setUp(self):
        ClickHelpers.setUp(self)
        self.pack = dsp.sample_pack()
        self.posted, self.threads = [], []
        self.saved_post = (dsp.slack_post, dsp.slack_delete)

        def fake_post(token, channel, text, blocks, thread_ts=None):
            self.posted.append(blocks)
            self.threads.append(thread_ts)
            return "1700000099.{:04d}".format(len(self.posted)), None
        dsp.slack_post = fake_post
        dsp.slack_delete = lambda *a: None

    def tearDown(self):
        dsp.slack_post, dsp.slack_delete = self.saved_post
        ClickHelpers.tearDown(self)

    def text_of(self, blocks):
        text = " ".join(b["text"]["text"] if b["type"] == "section" else
                        " ".join(e["text"] for e in b["elements"]) if b["type"] == "context" else ""
                        for b in blocks)
        return text.replace("_\n_", " ").replace("\n> ", " ").replace("\n", " ")

    def test_only_the_changed_chapters_are_given_to_the_model(self):
        prompt = dsp.split_prompt(self.pack, friday_canon())
        self.assertIn("Chapter 1:", prompt)
        self.assertIn("Chapter 3:", prompt)
        self.assertIn("Chapter 4:", prompt)
        self.assertNotIn("Chapter 2:", prompt)                       # as it happened: nothing to contrast
        self.assertIn(self.pack["chapters"][2]["real"], prompt)      # what really happened
        self.assertIn(self.pack["chapters"][0]["twist"], prompt)     # what the team did instead
        self.assertNotIn("written by", prompt)

    def test_the_instructions_ask_for_light_kind_humour(self):
        system = dsp.SPLIT_SYSTEM
        self.assertIn("light, warm and a little playful", system)
        self.assertIn("Never at the expense of any person", system)
        self.assertIn("real people's hardship", system)

    def test_a_good_answer_is_used_for_each_changed_chapter(self):
        warnings = []
        lines = dsp.split_lines(FakeAzure(GOOD_SPLIT), self.pack, friday_canon(), warnings)
        self.assertEqual(sorted(lines), [1, 3, 4])
        self.assertIn("movie-and-nap day", lines[1])
        self.assertEqual(warnings, [])

    def test_a_chapter_the_model_missed_or_got_wrong_gets_a_plain_line(self):
        partial = {"lines": [GOOD_SPLIT["lines"][0],
                             {"chapter": 3, "line": "<!channel> " + GOOD_SPLIT["lines"][1]["line"]},
                             {"chapter": 2, "line": "A line for a chapter that was not changed at all, so ignored."}]}
        warnings = []
        lines = dsp.split_lines(FakeAzure(partial), self.pack, friday_canon(), warnings)
        self.assertEqual(sorted(lines), [1, 3, 4])                    # 2 never appears, 3 and 4 are plain
        self.assertIn("movie-and-nap day", lines[1])
        self.assertTrue(lines[3].startswith("Really: "))
        self.assertTrue(lines[4].startswith("Really: "))
        self.assertIn(self.pack["chapters"][2]["real"].rstrip("."), lines[3])
        self.assertEqual(len(warnings), 2)

    def test_whatever_the_model_sends_every_changed_chapter_still_has_a_line(self):
        bad_answers = ("not json", "", {"lines": "x"}, {"nothing": 1}, {"lines": [{"chapter": "x"}]},
                       {"lines": [{"chapter": 1, "line": "too short"}]},
                       {"lines": [{"chapter": 1, "line": "Ben went to fuck off for the day and nobody minded at all"}]},
                       {"lines": [{"chapter": 1, "line": "See https://evil.example for what Ben did on that quiet day off"}]})
        for bad in bad_answers:
            lines = dsp.split_lines(FakeAzure(bad), self.pack, friday_canon(), [])
            self.assertEqual(sorted(lines), [1, 3, 4], bad)
            self.assertTrue(all(lines.values()), bad)

    def test_no_model_gives_plain_lines(self):
        warnings = []
        lines = dsp.split_lines(None, self.pack, friday_canon(), warnings)
        self.assertEqual(sorted(lines), [1, 3, 4])
        self.assertTrue(any("no model" in w for w in warnings))

    def test_nothing_changed_means_no_call_and_no_lines(self):
        llm = FakeAzure(GOOD_SPLIT)
        canon = {str(k): {"choice": "real", "picks": 1, "quiet": False} for k in range(1, 5)}
        self.assertEqual(dsp.split_lines(llm, self.pack, canon, []), {})
        self.assertEqual(llm.calls, 0)

    def view(self, split, canon=None):
        canon = canon or friday_canon()
        return dsp.publish_view(self.pack, canon, ["Asha Rao"], dsp.assembled_story(self.pack, canon), split=split)

    def test_the_thread_shows_the_lines_and_the_score(self):
        lines = dsp.split_lines(FakeAzure(GOOD_SPLIT), self.pack, friday_canon(), [])
        text = self.text_of(dsp.split_blocks(friday_canon(), lines))
        self.assertIn("Where we split from the real story", text)
        self.assertIn("we matched the real story in 1 of 4 chapters", text)
        self.assertIn("Ch 1", text)
        self.assertNotIn("'s plot", text)                              # nobody wrote a plot any more
        self.assertNotIn("Ch 2 ", text)                                # chapter 2 matched: no line
        self.assertEqual(dsp.block_problems(dsp.split_blocks(friday_canon(), lines)), [])

    def test_the_post_keeps_the_story_and_the_real_ending_and_points_to_the_thread(self):
        lines = dsp.split_lines(FakeAzure(GOOD_SPLIT), self.pack, friday_canon(), [])
        blocks = self.view(lines)["blocks"]
        text = self.text_of(blocks)
        self.assertNotIn("Ch 1", text)                                 # the lines are not in the post
        self.assertNotIn("we matched the real story", text)
        self.assertIn("the team's version", text)
        self.assertIn(self.pack["chapters"][-1]["real"], text)         # the real ending stays, sincere
        self.assertLess(text.index("How it really ended"), text.index("is in the thread"))
        self.assertIn("Where we split from the real story is in the thread", self.text_of(blocks[-1:]))
        self.assertIn("Next week's story arrives on Monday", self.text_of(blocks[-1:]))

    def test_score_wording_when_nothing_matched(self):
        canon = {str(k): {"choice": "divert", "picks": 1, "quiet": False} for k in range(1, 5)}
        text = self.text_of(dsp.split_blocks(canon, dsp.split_lines(None, self.pack, canon, [])))
        self.assertIn("none matched: this one is all ours", text)

    def test_no_section_when_the_team_kept_the_real_story(self):
        canon = {str(k): {"choice": "real", "picks": 1, "quiet": False} for k in range(1, 5)}
        view = self.view({}, canon)
        self.assertNotIn("Where we split", self.text_of(view["blocks"]))
        self.assertNotIn("in the thread", self.text_of(view["blocks"]))
        self.assertIn("Next week's story arrives on Monday", self.text_of(view["blocks"]))

    def test_long_lines_never_break_slacks_limit(self):
        long_lines = {k: "word " * 200 for k in (1, 3, 4)}              # a model that rambled past its checks
        view = self.view({k: dsp.clip(v, 320) for k, v in long_lines.items()})
        self.assertEqual(dsp.block_problems(view["blocks"]), [])
        lines = dsp.split_lines(None, self.pack, friday_canon(), [])
        self.assertEqual(dsp.block_problems(self.view(lines)["blocks"]), [])
        self.assertEqual(dsp.block_problems(dsp.split_blocks(friday_canon(), {k: "word " * 60 for k in (1, 3, 4)})), [])

    def test_a_name_that_holds_a_mention_never_pings_in_the_credits(self):
        evil = "<!channel> <@U123> & co"
        shown = "&lt;!channel&gt; &lt;@U123&gt; &amp; co"
        self.assertEqual(dsp.escape_name(evil), shown)
        canon = friday_canon()
        view = dsp.publish_view(self.pack, canon, [evil, "Asha Rao"], dsp.assembled_story(self.pack, canon),
                                split=dsp.split_lines(None, self.pack, canon, []))
        everything = json.dumps(view["blocks"])
        self.assertNotIn("<!channel>", everything)
        self.assertNotIn("<@U123>", everything)
        self.assertIn(shown, self.text_of(view["blocks"]))

    def publish(self, llm):
        table = FakeTable(posted=(1, 2, 3, 4), settled=(1, 2, 3, 4))
        pack, state = dsp.load_row(table.row)
        state["canon"] = friday_canon()
        table.row["content"] = dsp.dump_content(pack, state)
        pack, state = dsp.load_row(table.row)
        result = dsp._blank_result("post", "C1")
        run = dsp.Run(table, llm, "x", "C1", result, date(2026, 11, 20), 84, "", False, 50)
        return dsp.publish_week(run, table.row, pack, state), result, state

    def test_publishing_the_week_posts_the_story_and_then_the_thread(self):
        stitched = {"story": " ".join(["Ben spent a lazy day on the sofa and slowly let his grudge soften."] * 6)}
        llm = FakeAzure(stitched, GOOD_SPLIT)
        ok, result, state = self.publish(llm)
        self.assertTrue(ok)
        self.assertEqual(result["error"], "")
        self.assertEqual(len(self.posted), 2)
        main_post, thread = self.text_of(self.posted[0]), self.text_of(self.posted[1])
        self.assertEqual(self.threads, [None, result["message_ts"]])      # the second is a reply to the first
        self.assertEqual(result["thread_ts"], "1700000099.0002")
        self.assertNotIn("Where we split from the real story", main_post.replace("Where we split from the real story is in the thread", ""))
        self.assertIn("movie-and-nap day", thread)
        self.assertIn("Where we split from the real story", thread)
        self.assertEqual(llm.calls, 3)                                     # the story, the contrast lines, the ending
        self.assertTrue(state["published"])

    def test_a_thread_that_will_not_post_never_undoes_the_story(self):
        def post(token, channel, text, blocks, thread_ts=None):
            if thread_ts:
                return "", "slack chat.postMessage: thread_not_found"
            self.posted.append(blocks)
            return "1700000099.0001", None
        dsp.slack_post = post
        ok, result, state = self.publish(FakeAzure({"story": "x"}, GOOD_SPLIT))
        self.assertTrue(ok)
        self.assertEqual(result["error"], "")
        self.assertEqual(result["thread_ts"], "")
        self.assertTrue(any("where-we-split thread" in w for w in result["warnings"]), result["warnings"])
        self.assertTrue(state["published"])

    def test_a_week_the_team_kept_the_real_story_has_no_thread(self):
        table = FakeTable(posted=(1, 2, 3, 4), settled=(1, 2, 3, 4))
        pack, state = dsp.load_row(table.row)
        state["canon"] = {str(k): {"choice": "real", "picks": 1, "quiet": False} for k in range(1, 5)}
        result = dsp._blank_result("post", "C1")
        run = dsp.Run(table, None, "x", "C1", result, date(2026, 11, 20), 84, "", False, 50)
        self.assertTrue(dsp.publish_week(run, table.row, pack, state))
        self.assertEqual(len(self.posted), 1)
        self.assertEqual(self.threads, [None])
        self.assertEqual(result["thread_ts"], "")



# --------------------------------------------------------------------------
# A banner for each kind of post
# --------------------------------------------------------------------------

def banner_urls(blocks_json):
    return [b["image_url"] for b in json.loads(blocks_json) if b.get("type") == "image"]


class Banners(unittest.TestCase):
    NEW, DAILY, FINAL, ALL = ("https://x.example/new.png", "https://x.example/daily.png",
                              "https://x.example/final.png", "https://x.example/all.png")

    def preview(self, mode, **extra):
        fields = {"mode": mode, "skip_post": True, "banner_announce": self.NEW, "banner_daily": self.DAILY,
                  "banner_final": self.FINAL}
        fields.update(extra)
        return dsp.main(fields)

    def test_the_sunday_post_has_its_own_banner(self):
        self.assertEqual(banner_urls(self.preview("announce")["blocks_json"]), [self.NEW])

    def test_each_chapter_has_the_daily_banner(self):
        for chapter in (1, 2, 3, 4):
            self.assertEqual(banner_urls(self.preview("post", chapter=chapter)["blocks_json"]), [self.DAILY], chapter)

    def test_fridays_story_has_the_final_banner(self):
        self.assertEqual(banner_urls(self.preview("post", chapter=5)["blocks_json"]), [self.FINAL])

    def test_the_general_banner_fills_in_for_any_that_is_not_given(self):
        none = {"banner_announce": "", "banner_daily": "", "banner_final": "", "banner": self.ALL}
        self.assertEqual(banner_urls(self.preview("announce", **none)["blocks_json"]), [self.ALL])
        self.assertEqual(banner_urls(self.preview("post", chapter=2, **none)["blocks_json"]), [self.ALL])
        self.assertEqual(banner_urls(self.preview("post", chapter=5, **none)["blocks_json"]), [self.ALL])
        some = dict(none, banner_final=self.FINAL)
        self.assertEqual(banner_urls(self.preview("post", chapter=2, **some)["blocks_json"]), [self.ALL])
        self.assertEqual(banner_urls(self.preview("post", chapter=5, **some)["blocks_json"]), [self.FINAL])

    def test_no_banner_at_all_means_no_image(self):
        none = {"banner_announce": "", "banner_daily": "", "banner_final": "", "banner": ""}
        self.assertEqual(banner_urls(self.preview("post", chapter=2, **none)["blocks_json"]), [])

    def test_a_slack_file_id_works_too(self):
        blocks = json.loads(self.preview("post", chapter=2, banner_daily="F0ABCDEFGH")["blocks_json"])
        self.assertEqual(blocks[0]["slack_file"], {"id": "F0ABCDEFGH"})

    def test_a_real_chapter_is_drawn_with_the_daily_banner_and_keeps_it_for_every_redraw(self):
        pack, saved = dsp.sample_pack(), {}
        table = FakeTable(posted=(), settled=())
        pack, state = dsp.load_row(table.row)
        state["posts"] = {}
        result = dsp._blank_result("post", "C1")
        run = dsp.Run(table, None, "x", "C1", result, date(2026, 11, 17), 84, self.DAILY, False, 50)
        run.final_banner = self.FINAL
        posted = []
        real = dsp.slack_post
        dsp.slack_post = lambda token, channel, text, blocks, thread_ts=None: posted.append(blocks) or ("1.1", None)
        try:
            dsp.post_chapter(run, table.row, pack, state, 1)
        finally:
            dsp.slack_post = real
        self.assertEqual([b["image_url"] for b in posted[0] if b["type"] == "image"], [self.DAILY])
        self.assertEqual(state["look"]["banner"], self.DAILY)            # what a click redraws it with

    def test_the_banner_inputs_are_in_the_schema(self):
        names = {f["name"] for f in schema("story_relay_input_schema.json")}
        self.assertTrue({"banner", "banner_announce", "banner_daily", "banner_final"} <= names)

    def test_the_drawn_banners_are_1300_wide_and_80_or_200_tall(self):
        folder = os.path.join(HERE, "banners")
        for name, height in (("story_new.png", 80), ("story_daily.png", 80), ("story_final.png", 80),
                             ("story_new_200.png", 200), ("story_daily_200.png", 200),
                             ("story_final_200.png", 200)):
            path = os.path.join(folder, name)
            if not os.path.exists(path):
                self.skipTest(name + " is not in this folder")
            with open(path, "rb") as handle:
                head = handle.read(24)
            self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n", name)
            width, tall = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            self.assertEqual((width, tall), (1300, height), name)


# --------------------------------------------------------------------------
# The real ending carries its own context
# --------------------------------------------------------------------------

GOOD_ENDING = {"ending": "Ben had given milk, unpaid, to a struggling household with young children. In the end he "
                         "stood by that gift and felt glad thinking of those children."}


class TheRealEnding(FridaySplit):
    def test_the_model_is_given_the_whole_story_and_the_plain_ending(self):
        llm = FakeAzure(GOOD_ENDING)
        dsp.real_ending(llm, self.pack, "THE WHOLE TRUE STORY TEXT", [])
        prompt = llm.prompts[0]
        self.assertIn("THE WHOLE TRUE STORY TEXT", prompt)
        self.assertIn(self.pack["chapters"][-1]["real"], prompt)

    def test_the_instructions_ask_for_context_and_sincerity(self):
        system = dsp.ENDING_SYSTEM
        self.assertIn("who the people", system)
        self.assertIn("who 'the children' are", system)
        self.assertIn("no jokes", system)
        self.assertIn("Invent no person", system)

    def test_a_good_ending_replaces_the_plain_line(self):
        self.assertEqual(dsp.real_ending(FakeAzure(GOOD_ENDING), self.pack, "story", []),
                         GOOD_ENDING["ending"])

    def test_it_falls_back_to_the_plain_line_whatever_goes_wrong(self):
        plain = self.pack["chapters"][-1]["real"]
        for bad in ("not json", "", {"x": 1}, {"ending": "Too short."}, {"ending": "<!channel> " + GOOD_ENDING["ending"]},
                    {"ending": GOOD_ENDING["ending"] + " See https://evil.example now"},
                    {"ending": "Ben told them to fuck off and he was glad about every one of the many children"}):
            warnings = []
            self.assertEqual(dsp.real_ending(FakeAzure(bad), self.pack, "story", warnings), plain, bad)
            self.assertTrue(warnings, bad)
        self.assertEqual(dsp.real_ending(None, self.pack, "story", []), plain)

    def test_a_missing_story_text_uses_the_chapter_passages(self):
        llm = FakeAzure(GOOD_ENDING)
        dsp.real_ending(llm, self.pack, "", [])
        self.assertIn(self.pack["chapters"][0]["snippet"], llm.prompts[0])

    def test_the_post_shows_it_with_the_lesson_and_still_fits(self):
        canon = friday_canon()
        view = dsp.publish_view(self.pack, canon, ["A"], dsp.assembled_story(self.pack, canon),
                                ending=GOOD_ENDING["ending"])
        text = self.text_of(view["blocks"])
        self.assertIn("*How it really ended:* " + GOOD_ENDING["ending"].split(".")[0], text)
        self.assertIn(self.pack["lesson"], text)
        self.assertEqual(dsp.block_problems(view["blocks"]), [])

    def test_publishing_uses_it_when_the_team_changed_the_story(self):
        stitched = {"story": " ".join(["Ben spent a lazy day on the sofa and slowly let his grudge soften."] * 6)}
        ok, result, state = self.publish(FakeAzure(stitched, GOOD_SPLIT, GOOD_ENDING))
        self.assertTrue(ok)
        self.assertIn("young children", self.text_of(self.posted[0]))

    def test_no_call_for_the_ending_when_the_team_kept_the_real_story(self):
        table = FakeTable(posted=(1, 2, 3, 4), settled=(1, 2, 3, 4))
        pack, state = dsp.load_row(table.row)
        state["canon"] = {str(k): {"choice": "real", "picks": 1, "quiet": False} for k in range(1, 5)}
        llm = FakeAzure(GOOD_ENDING)
        result = dsp._blank_result("post", "C1")
        run = dsp.Run(table, llm, "x", "C1", result, date(2026, 11, 20), 84, "", False, 50)
        self.assertTrue(dsp.publish_week(run, table.row, pack, state))
        self.assertEqual(llm.calls, 0)                      # the team's version is the real story already
        self.assertIn(pack["chapters"][-1]["real"], self.text_of(self.posted[0]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
