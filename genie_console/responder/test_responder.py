"""
Tests for responder.py -- no network, stdlib unittest.

Run:  python3 test_responder.py        (from this folder)
Run it before and after every change to responder.py.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import responder as r                                          # noqa: E402
from testdata.samples import SAMPLES                            # noqa: E402

NARROW_TABLE = "| Name | Qty |\n|---|---|\n| apple | 3 |\n| fig | 12 |"

WIDE_TABLE = (
    "| Rocketlane Source | Gainsight Field | Notes |\n"
    "|---|---|---|\n"
    "| `Channel Id` | `ExternalId` | Deduplication key - used to check insert vs. update |\n"
    "| `Channel Name` | `Subject` | Formatted as: `[CHAT] {Channel Name} Channel Updates` |\n"
    "| *(hardcoded)* | `ContextName` | Always `\"Company\"` |\n"
    "| Workspace `author_email` | `Author` | **Resolved** via [Gainsight](https://x.io/a) lookup |"
)


def table_count(text):
    """How many markdown tables a text holds (their separator rows)."""
    return sum(1 for line in text.split("\n") if line.startswith("|--") or line.startswith("|:-"))


def table_block(attachments):
    blocks = [b for b in attachments[0]["blocks"] if b["type"] == "table"]
    return blocks[0] if blocks else None


class PlainMarkdown(unittest.TestCase):
    def test_heading_becomes_bold(self):
        self.assertEqual(r.to_mrkdwn("## Hello **there**"), "*Hello there*")

    def test_bold_bullets_links(self):
        out = r.to_mrkdwn("- **a** and [b](https://x.io)\n* c")
        self.assertEqual(out, "• *a* and <https://x.io|b>\n• c")

    def test_rule_becomes_divider_mark(self):
        self.assertIn(r.DIVIDER_MARK, r.to_mrkdwn("a\n\n---\n\nb"))

    def test_fenced_code_untouched(self):
        out = r.to_mrkdwn("```python\n**x** | y\n```")
        self.assertEqual(out, "```\n**x** | y\n```")


class NativeTable(unittest.TestCase):
    def setUp(self):
        self.card = r.answer_attachments("SNAP", "support", "Intro\n\n" + WIDE_TABLE + "\n\nOutro")
        self.block = table_block(self.card)

    def test_table_block_between_sections(self):
        types = [b["type"] for b in self.card[0]["blocks"]]
        self.assertEqual(types, ["context", "section", "table", "section", "context",
                                  "context_actions"])

    def test_rows_and_columns(self):
        self.assertEqual(len(self.block["rows"]), 5)                 # header + 4
        self.assertTrue(all(len(row) == 3 for row in self.block["rows"]))
        self.assertEqual(len(self.block["column_settings"]), 3)
        self.assertTrue(all(c["is_wrapped"] for c in self.block["column_settings"]))

    def test_header_cells_are_bold(self):
        cell = self.block["rows"][0][0]
        self.assertEqual(cell["type"], "rich_text")
        element = cell["elements"][0]["elements"][0]
        self.assertEqual(element["text"], "Rocketlane Source")
        self.assertTrue(element["style"]["bold"])

    def test_plain_cell_is_raw_text(self):
        t = r.answer_attachments("S", "", NARROW_TABLE)
        self.assertEqual(table_block(t)["rows"][1][0], {"type": "raw_text", "text": "apple"})

    def test_code_bold_italic_and_link_in_cells(self):
        def flat(cell):
            return cell["elements"][0]["elements"]
        row = self.block["rows"][4]
        self.assertEqual(flat(row[0])[1]["style"], {"code": True})            # `author_email`
        notes = flat(row[2])
        self.assertEqual(notes[0]["style"], {"bold": True})                    # **Resolved**
        self.assertEqual(notes[2], {"type": "link", "url": "https://x.io/a", "text": "Gainsight"})
        self.assertEqual(flat(self.block["rows"][3][0])[0]["style"], {"italic": True})

    def test_no_empty_text_elements(self):
        for row in self.block["rows"]:
            for cell in row:
                if cell["type"] == "raw_text":
                    self.assertTrue(cell["text"])
                else:
                    for el in cell["elements"][0]["elements"]:
                        self.assertTrue(el["text"])

    def test_a_table_is_never_drawn_as_text(self):
        for look in ("old", "new"):
            for text in (WIDE_TABLE, NARROW_TABLE, "x\n\n" + WIDE_TABLE + "\n\n" + NARROW_TABLE,
                         SAMPLES["rich"]):
                for page in r.split_tables(text):
                    card = r.build_answer(look, "S", "", page)
                    shown = json.dumps([b for b in card[0]["blocks"] if b["type"] != "table"])
                    for box in ("\u250c", "\u2502", "\u2550", "\u2514"):
                        self.assertNotIn(box, shown)
                    self.assertEqual(sum(b["type"] == "table" for b in card[0]["blocks"]),
                                     table_count(page))

    def test_header_only_table_is_still_a_table(self):
        card = r.answer_attachments("S", "", "| A | B |\n|---|---|")
        self.assertEqual(len(table_block(card)["rows"]), 1)

    def test_too_many_rows_is_cut_with_a_note(self):
        big = "| A | B |\n|--|--|\n" + "\n".join("| r{} | v |".format(i) for i in range(120))
        card = r.answer_attachments("S", "", big)
        self.assertEqual(len(table_block(card)["rows"]), r.NATIVE_TABLE_ROWS)
        self.assertIn("cut short", json.dumps(card[0]["blocks"]))
        self.assertIn("99 of 120", json.dumps(card[0]["blocks"]))

    def test_too_many_columns_and_characters_are_cut(self):
        wide = "| " + " | ".join("c%d" % i for i in range(30)) + " |\n|" + "--|" * 30 + "\n"
        wide += "| " + " | ".join("v" for _ in range(30)) + " |"
        card = r.answer_attachments("S", "", wide)
        self.assertEqual(len(table_block(card)["rows"][0]), r.NATIVE_TABLE_COLUMNS)
        heavy = "| A |\n|--|\n" + "\n".join("| " + "x" * 500 + " |" for _ in range(40))
        rows = table_block(r.answer_attachments("S", "", heavy))["rows"]
        self.assertLessEqual(json.dumps(rows).count("x"), r.NATIVE_TABLE_CHARS)


class SplitTables(unittest.TestCase):
    def test_no_or_one_table_is_one_piece(self):
        for text in ("Just text", "Intro\n\n" + WIDE_TABLE + "\n\nOutro", ""):
            self.assertEqual(len(r.split_tables(text)), 1)

    def test_two_tables_two_pieces_in_order(self):
        pieces = r.split_tables("Intro\n\n" + WIDE_TABLE + "\n\nNote on the first.\n\n"
                                "## Second\n\n" + NARROW_TABLE + "\n\nOutro")
        self.assertEqual(len(pieces), 2)
        self.assertTrue(pieces[0].startswith("Intro") and pieces[0].endswith("Note on the first."))
        self.assertEqual([table_count(p) for p in pieces], [1, 1])
        self.assertTrue(pieces[1].startswith("## Second") and pieces[1].endswith("Outro"))

    def test_tables_back_to_back_split_right_after_the_first(self):
        pieces = r.split_tables(WIDE_TABLE + "\n\n" + NARROW_TABLE)
        self.assertEqual(pieces, [WIDE_TABLE, NARROW_TABLE])

    def test_three_tables_and_nothing_lost(self):
        text = "A\n\n" + NARROW_TABLE + "\n\nB\n\n" + NARROW_TABLE + "\n\nC\n\n" + NARROW_TABLE
        pieces = r.split_tables(text)
        self.assertEqual(len(pieces), 3)
        self.assertEqual(sum(table_count(p) for p in pieces), 3)
        for word in "ABC":
            self.assertEqual(sum(("\n" + p + "\n").count("\n" + word + "\n") for p in pieces), 1)

    def test_a_heading_or_lead_in_goes_with_the_table_it_introduces(self):
        pieces = r.split_tables(WIDE_TABLE + "\n\nNote.\n\n## Two\n\nSome intro:\n\n" + NARROW_TABLE)
        self.assertTrue(pieces[0].endswith("Note."))
        self.assertTrue(pieces[1].startswith("## Two\n\nSome intro:"))

    def test_a_table_inside_a_code_block_is_not_a_table(self):
        text = "```\n" + NARROW_TABLE + "\n```\n\n" + NARROW_TABLE
        self.assertEqual(len(r.split_tables(text)), 1)

    def test_first_message_has_the_byline_last_has_the_footer_and_buttons(self):
        for look in ("old", "new"):
            first = r.build_answer(look, "S", "support", "a", "U1", first=True, last=False)[0]["blocks"]
            last = r.build_answer(look, "S", "support", "b", "U1", first=False, last=True)[0]["blocks"]
            self.assertEqual(first[0]["type"], "context")
            self.assertNotIn("context_actions", [b["type"] for b in first])
            self.assertNotIn("Reply in this thread", json.dumps(first))
            self.assertNotIn("*S*", json.dumps(last))
            self.assertEqual(last[-1]["type"], "context_actions")


class Matching(unittest.TestCase):
    def test_keyword_whole_word(self):
        rows = [{"invoke_keyword": "SNAP"}]
        self.assertIsNotNone(r.find_keyword("SNAP why", rows)[0])
        self.assertIsNone(r.find_keyword("snapshot", rows)[0])

    def test_question_from(self):
        row, match = r.find_keyword("SNAP: why?", [{"invoke_keyword": "SNAP"}])
        self.assertEqual(r.question_from("SNAP: why?", match), "why?")


class ReplyFallback(unittest.TestCase):
    """What happens when Slack rejects a card: old look, no buttons, never a text table."""

    class FakeSlack(r.Slack):
        def __init__(self, reject=()):
            r.Slack.__init__(self, "x", dry_run=False)
            self.reject = set(reject)
            self.sent = []

        def _get(self, method, params):          # reads never leave the machine
            return {"ok": True, "permalink": ""}

        def _call(self, method, payload):
            self.last = payload
            blocks = [b for a in payload.get("attachments", []) for b in a["blocks"]]
            if self.reject & {b["type"] for b in blocks}:
                self.errors.append("slack.{}: invalid_blocks".format(method))
                return None
            self.sent.append((method, payload))
            return {"ok": True, "ts": "1.2"}

    def run_reply(self, reject=(), answer=WIDE_TABLE):
        slack = self.FakeSlack(reject)
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "dm_sent": []}
        r.reply({"genie_response": answer, "genie_name": "SNAP", "thinking_ts": "1.1"},
                FakeTable(), slack, result)
        return slack, result

    def test_accepted(self):
        slack, result = self.run_reply()
        self.assertEqual(slack.errors, [])
        self.assertTrue(result["posted"])
        self.assertEqual(slack.sent[0][0], "chat.update")

    def test_a_rejected_table_is_never_swapped_for_a_text_table(self):
        slack, result = self.run_reply({"table"})
        self.assertFalse(result["posted"])
        self.assertTrue(slack.errors)                       # Slack's refusal is reported
        self.assertEqual(slack.sent, [])
        self.assertFalse(any("\u250c" in json.dumps(p) for _m, p in slack.sent))

    def test_rejected_feedback_buttons_are_dropped(self):
        slack, result = self.run_reply({"context_actions"}, answer="Just text")
        self.assertTrue(result["posted"])
        self.assertEqual(slack.errors, [])
        self.assertTrue(any("no feedback buttons" in w for w in result["warnings"]))
        blocks = slack.sent[0][1]["attachments"][0]["blocks"]
        self.assertFalse(any(b["type"] == "context_actions" for b in blocks))

    def test_everything_rejected_keeps_the_last_error(self):
        slack, result = self.run_reply({"table", "context_actions", "section", "context"})
        self.assertFalse(result["posted"])
        self.assertTrue(slack.errors)

    def test_blocked_answer_has_no_feedback_buttons(self):
        slack, _ = self.run_reply(answer="I can't help with that here. [[BLOCKED]]")
        blocks = slack.sent[0][1]["attachments"][0]["blocks"]
        self.assertFalse(any(b["type"] == "context_actions" for b in blocks))


class SeveralTables(unittest.TestCase):
    """Slack allows one table block per message: one message per table, in order."""

    TWO = "Intro\n\n" + WIDE_TABLE + "\n\n## Second\n\n" + NARROW_TABLE + "\n\nOutro"

    def run_reply(self, reject=(), look="", answer=TWO):
        slack = ReplyFallback.FakeSlack(reject)
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "dm_sent": []}
        r.reply({"genie_response": answer, "genie_name": "SNAP", "thinking_ts": "1.1",
                 "user_id": "U1", "look": look}, FakeTable(), slack, result)
        return slack, result

    def blocks(self, slack, n):
        return slack.sent[n][1]["attachments"][0]["blocks"]

    def test_one_message_per_table_first_edits_the_thinking_message(self):
        for look in ("new", "old"):
            slack, result = self.run_reply(look=look)
            self.assertEqual([m for m, _p in slack.sent], ["chat.update", "chat.postMessage"])
            self.assertEqual(slack.sent[0][1]["ts"], "1.1")
            self.assertEqual(slack.sent[1][1]["thread_ts"], "1.0")
            for n in (0, 1):
                self.assertEqual(types(self.blocks(slack, n)).count("table"), 1)
            self.assertTrue(result["posted"])
            self.assertEqual(slack.errors, [])

    def test_byline_first_footer_and_buttons_last(self):
        slack, _ = self.run_reply()
        first, second = self.blocks(slack, 0), self.blocks(slack, 1)
        self.assertIn("SNAP", json.dumps(first[0]))
        self.assertNotIn("context_actions", types(first))
        self.assertNotIn("SNAP", json.dumps(second[0]))
        self.assertEqual(types(second)[-2:], ["context", "context_actions"])

    def test_the_order_of_the_answer_is_kept(self):
        slack, _ = self.run_reply(look="old")
        flat = json.dumps([self.blocks(slack, 0), self.blocks(slack, 1)])
        self.assertLess(flat.index("Intro"), flat.index("Rocketlane Source"))
        self.assertLess(flat.index("Rocketlane Source"), flat.index("Second"))
        self.assertLess(flat.index("Second"), flat.index("apple"))
        self.assertLess(flat.index("apple"), flat.index("Outro"))

    def test_one_table_is_still_one_message(self):
        slack, _ = self.run_reply(answer="Intro\n\n" + WIDE_TABLE)
        self.assertEqual(len(slack.sent), 1)

    def test_rejected_buttons_are_dropped_on_the_last_message_only(self):
        slack, result = self.run_reply({"context_actions"})
        self.assertEqual(len(slack.sent), 2)
        self.assertFalse(any("context_actions" in types(self.blocks(slack, n)) for n in (0, 1)))
        self.assertEqual(slack.errors, [])

    def test_second_message_failing_is_reported_not_hidden(self):
        class SecondFails(ReplyFallback.FakeSlack):
            def _call(self, method, payload):
                if method == "chat.postMessage":
                    self.errors.append("slack.chat.postMessage: invalid_blocks")
                    return None
                return ReplyFallback.FakeSlack._call(self, method, payload)
        slack = SecondFails()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "dm_sent": []}
        r.reply({"genie_response": self.TWO, "genie_name": "SNAP", "thinking_ts": "1.1"},
                FakeTable(), slack, result)
        self.assertTrue(result["posted"])                    # the first part went out
        self.assertTrue(any("part 2 of 2" in w for w in result["warnings"]))
        self.assertTrue(slack.errors)


class FeedbackButtons(unittest.TestCase):
    def blocks(self, **kw):
        return r.answer_attachments("SNAP", "support", "Hello", "U1", **kw)[0]["blocks"]

    def test_buttons_are_the_last_block(self):
        last = self.blocks()[-1]
        self.assertEqual(last["type"], "context_actions")
        buttons = last["elements"][0]
        self.assertEqual(buttons["type"], "feedback_buttons")
        self.assertEqual(buttons["action_id"], r.FEEDBACK_ACTION_ID)
        self.assertEqual(buttons["positive_button"]["value"], "positive")
        self.assertEqual(buttons["negative_button"]["value"], "negative")
        self.assertEqual(buttons["positive_button"]["text"]["type"], "plain_text")

    def test_can_be_left_off(self):
        self.assertNotIn("context_actions", [b["type"] for b in self.blocks(feedback=False)])

    def test_error_card_has_none(self):
        card = r.error_attachments("SNAP", "support", "boom")
        self.assertNotIn("context_actions", [b["type"] for b in card[0]["blocks"]])


class plan_on(object):
    """SHOW_PLAN is off by default (Slack rejects a plan block in a normal message); these
    tests switch it on to check the plan code that is kept behind it."""

    def __enter__(self):
        self.old, r.SHOW_PLAN = r.SHOW_PLAN, True

    def __exit__(self, *exc):
        r.SHOW_PLAN = self.old


class PlanBlock(unittest.TestCase):
    """The plan block code is kept behind SHOW_PLAN, which is off."""

    def test_plan_is_off_by_default(self):
        self.assertFalse(r.SHOW_PLAN)
        card = r.thinking_attachments("rocket", "support", "q")
        self.assertEqual([b["type"] for b in card[0]["blocks"]], ["context"])

    def test_thinking_message_has_a_plan_when_switched_on(self):
        with plan_on():
            card = r.thinking_attachments("rocket", "support", "why <b>no</b> sync?")
        plan = [b for b in card[0]["blocks"] if b["type"] == "plan"][0]
        self.assertEqual([t["status"] for t in plan["tasks"]],
                         ["complete", "complete", "in_progress", "pending"])
        self.assertEqual(len({t["task_id"] for t in plan["tasks"]}), len(plan["tasks"]))
        self.assertIn("rocket", plan["title"])
        quoted = plan["tasks"][0]["details"]["elements"][0]["elements"][0]["text"]
        self.assertIn("why", quoted)
        self.assertNotIn("<", quoted)

    def test_plain_thinking_message_without_plan(self):
        with plan_on():
            card = r.thinking_attachments("rocket", "support", "q", plan=False)
        self.assertEqual([b["type"] for b in card[0]["blocks"]], ["context"])

    def run_post_thinking(self, reject, look="old"):
        slack = ReplyFallback.FakeSlack(reject)
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "genie_name": "SNAP",
                  "persona": "support"}
        r.post_thinking(slack, result, "why?", look)
        return slack, result

    def test_with_the_plan_off_nothing_is_rejected_and_no_warning(self):
        slack, result = self.run_post_thinking({"plan"})
        self.assertEqual(result["thinking_ts"], "1.2")
        self.assertEqual((slack.errors, result["warnings"]), ([], []))
        self.assertEqual(len(slack.sent), 1)                  # one call, no failed attempt

    def test_plan_on_falls_back_when_slack_rejects_it(self):
        with plan_on():
            slack, result = self.run_post_thinking({"plan"})
        self.assertEqual(result["thinking_ts"], "1.2")
        self.assertEqual(slack.errors, [])
        self.assertTrue(any("plan" in w for w in result["warnings"]))
        self.assertEqual([b["type"] for b in slack.sent[0][1]["attachments"][0]["blocks"]],
                         ["context"])


class ThinkingLine(unittest.TestCase):
    """The new look's waiting message: one plain line, no card."""

    def test_text(self):
        self.assertEqual(r.thinking_text("rocket"), "*rocket* is thinking\u2026 :loading-2:")

    def test_no_name_falls_back(self):
        self.assertEqual(r.thinking_text(""), "*The genie* is thinking\u2026 :loading-2:")

    def test_new_look_posts_blocks_only_no_text_and_no_attachment(self):
        # No `text`: the message trigger must see an empty message, or the app's own line
        # ("*rocket* is thinking...") would match the keyword ROCKET and start a second run.
        slack = ReplyFallback.FakeSlack()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "genie_name": "rocket",
                  "persona": "support"}
        r.post_thinking(slack, result, "why?", "new")
        payload = slack.sent[0][1]
        self.assertNotIn("attachments", payload)
        self.assertNotIn("text", payload)
        self.assertIn("rocket", json.dumps(payload["blocks"]))
        self.assertEqual((result["thinking_ts"], result["warnings"]), ("1.2", []))

    def test_own_waiting_line_never_starts_a_run(self):
        class OneGenie(FakeTable):
            def query(self, where, limit=200):
                if "$and" in where:
                    return [{"record_type": "channel_genie", "status": "active", "channel": "C1",
                             "invoke_keyword": "ROCKET", "genie_name": "rocket",
                             "persona": "support", "id": "gin-1"}], None
                return FakeTable.query(self, where, limit)

        for text in (r.thinking_text("rocket"), "*rocket* is thinking... :loading-2:"):
            slack = ReplyFallback.FakeSlack()
            result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "matched": False}
            r.ask({"text": text, "user_id": "U1"}, OneGenie(), slack, result)
            self.assertFalse(result.get("call_genie"))
            self.assertEqual(result["skipped"], "the app's own waiting message")
            self.assertEqual(slack.sent, [])
        # a real question that merely contains those words still gets answered
        slack = ReplyFallback.FakeSlack()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "matched": False}
        r.ask({"text": "ROCKET why is the sync thinking so long?", "user_id": "U1"},
              OneGenie(), slack, result)
        self.assertTrue(result["call_genie"])

    def test_old_look_still_posts_the_card(self):
        slack = ReplyFallback.FakeSlack()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "genie_name": "rocket",
                  "persona": "support"}
        r.post_thinking(slack, result, "why?", "old")
        self.assertEqual(slack.sent[0][1]["attachments"][0]["blocks"][0]["type"], "context")
        self.assertNotIn("text", slack.sent[0][1])

    def test_rejected_line_falls_back_to_the_old_card(self):
        class NoPlainText(ReplyFallback.FakeSlack):
            def _call(self, method, payload):
                if "attachments" not in payload:
                    self.errors.append("slack.chat.postMessage: invalid_blocks")
                    return None
                return ReplyFallback.FakeSlack._call(self, method, payload)
        slack = NoPlainText()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "genie_name": "rocket",
                  "persona": "support"}
        r.post_thinking(slack, result, "why?", "new")
        self.assertEqual(result["thinking_ts"], "1.2")
        self.assertEqual(slack.errors, [])
        self.assertTrue(any("thinking line rejected" in w for w in result["warnings"]))

    def test_the_answer_replaces_the_plain_line(self):
        slack = ReplyFallback.FakeSlack()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "dm_sent": []}
        r.reply({"genie_response": "Hi", "genie_name": "rocket", "thinking_ts": "1.1"},
                FakeTable(), slack, result)
        method, payload = slack.sent[0]
        self.assertEqual((method, payload["ts"], payload["text"]), ("chat.update", "1.1", ""))
        self.assertTrue(payload["attachments"])

    def test_ask_uses_the_look_input(self):
        class OneGenie(FakeTable):
            def query(self, where, limit=200):
                if "$and" in where:
                    return [{"record_type": "channel_genie", "status": "active", "channel": "C1",
                             "invoke_keyword": "ROCKET", "genie_name": "rocket",
                             "persona": "support", "id": "gin-1"}], None
                return FakeTable.query(self, where, limit)

        for look, plain_line in (("new", True), ("", True), ("old", False)):
            slack = ReplyFallback.FakeSlack()
            result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "matched": False}
            r.ask({"text": "ROCKET why no sync?", "user_id": "U1", "look": look},
                  OneGenie(), slack, result)
            self.assertTrue(result["call_genie"])
            payload = slack.sent[-1][1]
            self.assertEqual("blocks" in payload and "attachments" not in payload, plain_line, look)
            self.assertEqual(result["thinking_ts"], "1.2")
            self.assertEqual(result["warnings"], [])


class FakeTable(object):
    """The data table in memory: query by record_key, save as create or update."""

    def __init__(self, rows=()):
        self.rows = [dict(row) for row in rows]
        self.saved = []

    def query(self, where, limit=200):
        key = (where.get("record_key") or {}).get("$eq")
        return [dict(row) for row in self.rows if row.get("record_key") == key][:limit], None

    def save(self, row, fields):
        self.saved.append((row, dict(fields)))
        return None


BLOCK_ACTIONS = {
    "type": "block_actions", "user": {"id": "U9"},
    "channel": {"id": "C1"},
    "container": {"type": "message_attachment", "message_ts": "5.5", "channel_id": "C1"},
    "message": {"ts": "5.5", "thread_ts": "4.0"},
    "actions": [{"action_id": "genie_feedback", "value": "negative", "type": "feedback_buttons"}],
}


class FeedbackAction(unittest.TestCase):
    def run_main(self, table, **extra):
        data = {"action": "feedback", "workato_api_token": "t"}
        data.update(extra)
        real = r.Table
        r.Table = lambda token, dry_run=False: table
        try:
            return r.main(data)
        finally:
            r.Table = real

    def test_from_a_raw_payload_string(self):
        import json
        table = FakeTable([{"record_key": "conv:C1:4.0", "invoke_keyword": "ROCKET",
                            "genie_name": "rocket", "persona": "support"}])
        out = self.run_main(table, payload=json.dumps(BLOCK_ACTIONS))
        self.assertTrue(out["ok"], out["error"])
        self.assertTrue(out["feedback_saved"])
        self.assertEqual(out["feedback_value"], "negative")
        existing, fields = table.saved[0]
        self.assertIsNone(existing)
        self.assertEqual(fields["record_type"], r.FEEDBACK_TYPE)
        self.assertEqual(fields["record_key"], "fb:C1:5.5:U9")
        self.assertEqual((fields["status"], fields["id"], fields["creator_id"]),
                         ("negative", "5.5", "U9"))
        self.assertEqual((fields["invoke_keyword"], fields["genie_name"], fields["persona"],
                          fields["setup_thread_ts"]), ("ROCKET", "rocket", "support", "4.0"))

    def test_form_encoded_payload(self):
        import json
        import urllib.parse
        body = urllib.parse.urlencode({"payload": json.dumps(BLOCK_ACTIONS)})
        out = self.run_main(FakeTable(), payload=body)
        self.assertTrue(out["feedback_saved"], out["error"])

    def test_plain_inputs_without_a_payload(self):
        out = self.run_main(FakeTable(), user_id="U2", channel="C1", message_ts="7.7",
                            feedback_value="Positive")
        self.assertTrue(out["feedback_saved"], out["error"])
        self.assertEqual(out["feedback_value"], "positive")

    def test_voting_again_updates_the_same_row(self):
        table = FakeTable([{"record_key": "fb:C1:5.5:U9", "$record_id": "rec1", "status": "positive"}])
        self.run_main(table, user_id="U9", channel="C1", message_ts="5.5", feedback_value="negative")
        existing, fields = table.saved[0]
        self.assertEqual(existing["$record_id"], "rec1")
        self.assertNotIn("created_at", fields)

    def test_unknown_value_is_an_error_and_saves_nothing(self):
        table = FakeTable()
        out = self.run_main(table, user_id="U9", channel="C1", message_ts="5.5",
                            feedback_value="meh")
        self.assertFalse(out["ok"])
        self.assertEqual(table.saved, [])

    def test_missing_message_is_an_error(self):
        out = self.run_main(FakeTable(), user_id="U9", channel="C1", feedback_value="positive")
        self.assertFalse(out["ok"])
        self.assertIn("message_ts", out["error"])

    def test_feedback_rows_never_answer_questions(self):
        # ask() reads rows with record_type channel_genie; a feedback row must not look like one.
        self.assertNotEqual(r.FEEDBACK_TYPE, r.GENIE_TYPE)
        self.assertNotEqual(r.FEEDBACK_TYPE, r.CONVERSATION_TYPE)


def types(blocks):
    return [b["type"] for b in blocks]


class OldLookIsUnchanged(unittest.TestCase):
    """testdata/golden_old.json was made from responder.py before the new look existed."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata",
                               "golden_old.json")) as handle:
            cls.golden = json.load(handle)

    def same(self, name, built):
        self.assertEqual(json.loads(json.dumps(built, sort_keys=True)), self.golden[name])

    def test_answers(self):
        for name in ("plain", "long"):
            text = SAMPLES[name]
            self.same(name, r.answer_attachments("SNAP", "support", text, "U1"))
            self.same(name, r.build_answer("old", "SNAP", "support", text, "U1"))

    def test_answer_with_two_tables_is_one_message_per_table(self):
        # The one change to the old look: tables are native blocks, never box characters.
        pages = r.split_tables(SAMPLES["rich"])
        built = [r.build_answer("old", "SNAP", "support", page, "U1", first=i == 0,
                                last=i == len(pages) - 1) for i, page in enumerate(pages)]
        self.same("rich_pages", built)

    def test_hello_thinking_error(self):
        self.same("hello", r.hello_attachments("SNAP", "support", "SNAP", [{"name": "Proj"}]))
        self.same("thinking", r.thinking_attachments("SNAP", "support", "why?"))
        with plan_on():
            self.same("thinking_with_plan", r.thinking_attachments("SNAP", "support", "why?"))
        self.same("error", r.error_attachments("SNAP", "support", "boom"))

    def test_reply_with_look_old_sends_the_golden_card(self):
        slack = ReplyFallback.FakeSlack()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "dm_sent": []}
        r.reply({"genie_response": SAMPLES["rich"], "genie_name": "SNAP", "persona": "support",
                 "user_id": "U1", "thinking_ts": "1.1", "look": "old"},
                FakeTable(), slack, result)
        self.assertEqual(json.loads(json.dumps([p["attachments"] for _m, p in slack.sent],
                                               sort_keys=True)), self.golden["rich_pages"])


class NewLook(unittest.TestCase):
    def card(self, text, **kw):
        return r.build_answer("new", "SNAP", "support", text, "U1", **kw)[0]["blocks"]

    def test_look_input(self):
        self.assertEqual(r.look_of("OLD"), "old")
        self.assertEqual(r.look_of(" new "), "new")
        self.assertEqual(r.look_of(""), r.LOOK_DEFAULT)
        self.assertEqual(r.look_of("classic"), r.LOOK_DEFAULT)

    def test_title_becomes_a_header(self):
        blocks = self.card(SAMPLES["rich"])
        self.assertEqual(types(blocks)[:3], ["context", "header", "markdown"])
        self.assertEqual(blocks[1]["text"], {"type": "plain_text", "emoji": True,
                                             "text": "Why quote Q-123 did not sync"})
        self.assertNotIn("Why quote Q-123 did not sync", blocks[2]["text"])

    def test_header_is_cut_to_slacks_limit_and_has_no_markdown(self):
        blocks = self.card("## **{}**\n\nBody".format("x" * 400))
        self.assertEqual(len(blocks[1]["text"]["text"]), r.HEADER_LIMIT)
        self.assertNotIn("*", blocks[1]["text"]["text"])

    def test_no_header_when_the_answer_is_only_a_heading_or_has_none(self):
        self.assertNotIn("header", types(self.card("# Only a title")))
        self.assertNotIn("header", types(self.card("Just an answer\n\n# Later heading")))

    def test_body_keeps_markdown_as_written(self):
        text = "\n".join(b["text"] for b in self.card(SAMPLES["rich"]) if b["type"] == "markdown")
        for kept in ("## What happened", "**quote**", "[the recipe](https://app.workato.com/recipes/1)",
                     "  - nested detail", "> Retrying", "```python"):
            self.assertIn(kept, text)

    def test_table_is_native_and_rule_is_a_divider(self):
        first = r.split_tables(SAMPLES["rich"])[0]
        blocks = self.card(first)
        self.assertEqual(types(blocks).count("table"), 1)
        self.assertIn("divider", types(blocks))
        self.assertNotIn("\u250c", json.dumps(blocks))                       # no box table

    def test_footer_and_feedback_buttons_stay(self):
        blocks = self.card("Hello")
        self.assertEqual(types(blocks)[-2:], ["context", "context_actions"])
        self.assertNotIn("context_actions", types(self.card("Hello", feedback=False)))

    def test_markdown_total_stays_under_slacks_limit(self):
        blocks = self.card(SAMPLES["long"])            # 40 long paragraphs: too long for markdown
        self.assertNotIn("markdown", types(blocks))
        self.assertIn("section", types(blocks))
        medium = "\n\n".join("Paragraph " + "word " * 100 for _ in range(10))
        blocks = self.card(medium)
        self.assertLessEqual(sum(len(b["text"]) for b in blocks if b["type"] == "markdown"),
                             r.MARKDOWN_TOTAL)
        self.assertNotIn("section", types(blocks))

    def test_every_markdown_block_is_text_and_no_empty_ones(self):
        for text in SAMPLES.values():
            for block in self.card(text):
                if block["type"] == "markdown":
                    self.assertTrue(block["text"].strip())

    def test_hello_is_a_card(self):
        card = r.hello_attachments_new("SNAP", "support", "SNAP", [{"name": "Proj"}])[0]["blocks"][0]
        self.assertEqual(card["type"], "card")
        self.assertIn("SNAP", card["title"]["text"])
        self.assertIn("Proj", card["body"]["text"])


class NewLookFallback(unittest.TestCase):
    def run_reply(self, reject, look=""):
        slack = ReplyFallback.FakeSlack(reject)
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "dm_sent": []}
        r.reply({"genie_response": SAMPLES["rich"], "genie_name": "SNAP", "thinking_ts": "1.1",
                 "look": look}, FakeTable(), slack, result)
        return slack, result

    def test_new_look_is_sent_first(self):
        slack, result = self.run_reply(())
        self.assertIn("markdown", types(slack.sent[0][1]["attachments"][0]["blocks"]))
        self.assertFalse([w for w in result["warnings"] if "rejected" in w])

    def test_rejected_markdown_sends_the_old_look(self):
        slack, result = self.run_reply({"markdown", "header"})
        blocks = slack.sent[0][1]["attachments"][0]["blocks"]
        self.assertNotIn("markdown", types(blocks))
        self.assertIn("section", types(blocks))
        self.assertIn("table", types(blocks))                  # still the native table
        self.assertEqual(slack.errors, [])
        self.assertTrue(any("the old look" in w for w in result["warnings"]))

    def test_look_old_never_sends_a_markdown_block(self):
        slack, _ = self.run_reply((), look="old")
        self.assertNotIn("markdown", types(slack.sent[0][1]["attachments"][0]["blocks"]))

    def test_slacks_own_reason_is_in_the_warning(self):
        class Reasoned(ReplyFallback.FakeSlack):
            def _call(self, method, payload):
                blocks = [b for a in payload.get("attachments", []) for b in a["blocks"]]
                if any(b["type"] == "markdown" for b in blocks):
                    self.errors.append("slack.chat.update: invalid_blocks "
                                       "(unsupported block type: markdown)")
                    return None
                return ReplyFallback.FakeSlack._call(self, method, payload)
        slack = Reasoned()
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "dm_sent": []}
        r.reply({"genie_response": "Hi", "genie_name": "SNAP", "thinking_ts": "1.1"},
                FakeTable(), slack, result)
        self.assertTrue(any("unsupported block type: markdown" in w for w in result["warnings"]))

    def test_slack_call_puts_response_metadata_in_the_error(self):
        slack = r.Slack("x")
        original = r._request
        r._request = lambda *a, **k: ({"ok": False, "error": "invalid_blocks",
                                       "response_metadata": {"messages": ["[ERROR] bad card"]}},
                                      None)
        try:
            self.assertIsNone(slack._call("chat.postMessage", {}))
        finally:
            r._request = original
        self.assertIn("bad card", slack.errors[0])

    def test_hello_falls_back_to_the_old_look(self):
        slack = ReplyFallback.FakeSlack({"card"})
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "genie_name": "SNAP",
                  "persona": "support", "keyword": "SNAP"}
        r.post_hello(slack, result, [{"name": "Proj"}], "new")
        self.assertEqual(slack.errors, [])
        self.assertEqual(types(slack.sent[0][1]["attachments"][0]["blocks"]), ["context", "section"])
        self.assertTrue(any("hello" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
