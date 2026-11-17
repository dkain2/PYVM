"""
Tests for responder.py -- no network, stdlib unittest.

Run:  python3 test_responder.py        (from this folder)
Run it before and after every change to responder.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import responder as r                                          # noqa: E402

NARROW_TABLE = "| Name | Qty |\n|---|---|\n| apple | 3 |\n| fig | 12 |"

WIDE_TABLE = (
    "| Rocketlane Source | Gainsight Field | Notes |\n"
    "|---|---|---|\n"
    "| `Channel Id` | `ExternalId` | Deduplication key - used to check insert vs. update |\n"
    "| `Channel Name` | `Subject` | Formatted as: `[CHAT] {Channel Name} Channel Updates` |\n"
    "| *(hardcoded)* | `ContextName` | Always `\"Company\"` |\n"
    "| Workspace `author_email` | `Author` | **Resolved** via [Gainsight](https://x.io/a) lookup |"
)


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


class TextTable(unittest.TestCase):
    """No `tables` list given: a table is drawn with box characters in a code block."""

    def setUp(self):
        self.out = r.to_mrkdwn(WIDE_TABLE)
        self.lines = self.out.strip("`").split("\n")

    def test_is_a_code_block(self):
        self.assertTrue(self.out.startswith("```") and self.out.endswith("```"))

    def test_every_line_has_the_same_width_and_fits(self):
        widths = {len(line) for line in self.lines}
        self.assertEqual(len(widths), 1, widths)
        self.assertLessEqual(widths.pop(), r.BOX_WIDTH)

    def test_borders_and_header_rule(self):
        self.assertTrue(self.lines[0].startswith("┌") and self.lines[0].endswith("┐"))
        self.assertTrue(self.lines[-1].startswith("└") and self.lines[-1].endswith("┘"))
        self.assertTrue(any(line.startswith("╞") for line in self.lines))   # under header

    def test_markdown_noise_is_removed(self):
        for noise in ("`", "**", "(https://"):
            self.assertNotIn(noise, self.out.replace("```", ""))
        self.assertIn("(hardcoded)", self.out)
        self.assertNotIn("*(hardcoded)*", self.out)

    def test_long_cells_wrap_onto_extra_lines(self):
        self.assertIn("Deduplication", self.out)
        self.assertIn("update", self.out)
        self.assertGreater(len(self.lines), 2 + 2 * 5)

    def test_narrow_table_keeps_natural_widths(self):
        lines = r.to_mrkdwn(NARROW_TABLE).strip("`").split("\n")
        self.assertEqual(lines[0], "┌───────┬"
                         "─────┐")
        self.assertEqual(lines[1], "│ Name  │ Qty │")
        self.assertIn("│ apple │ 3   │", lines)

    def test_survives_splitting(self):
        for piece in r.split_sections(self.out):
            self.assertLessEqual(len(piece), r.SECTION_LIMIT)

    def test_text_around_table_kept(self):
        out = r.to_mrkdwn("Before\n\n" + WIDE_TABLE + "\n\nAfter")
        self.assertTrue(out.startswith("Before") and out.endswith("After"))


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

    def test_only_one_native_table_per_message(self):
        card = r.answer_attachments("S", "", WIDE_TABLE + "\n\ntext\n\n" + NARROW_TABLE)
        blocks = card[0]["blocks"]
        self.assertEqual(sum(b["type"] == "table" for b in blocks), 1)
        self.assertTrue(any("┌" in b.get("text", {}).get("text", "") for b in blocks))

    def test_text_fallback_when_native_is_off(self):
        card = r.answer_attachments("S", "", WIDE_TABLE, native=False)
        self.assertIsNone(table_block(card))
        self.assertIn("┌", card[0]["blocks"][1]["text"]["text"])

    def test_too_many_rows_falls_back_to_text(self):
        big = "| A | B |\n|--|--|\n" + "\n".join("| r{} | v |".format(i) for i in range(120))
        self.assertIsNone(table_block(r.answer_attachments("S", "", big)))


class Matching(unittest.TestCase):
    def test_keyword_whole_word(self):
        rows = [{"invoke_keyword": "SNAP"}]
        self.assertIsNotNone(r.find_keyword("SNAP why", rows)[0])
        self.assertIsNone(r.find_keyword("snapshot", rows)[0])

    def test_question_from(self):
        row, match = r.find_keyword("SNAP: why?", [{"invoke_keyword": "SNAP"}])
        self.assertEqual(r.question_from("SNAP: why?", match), "why?")


class ReplyFallback(unittest.TestCase):
    """Slack rejects the native table -> the same answer is sent again as a text table."""

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

    def test_rejected_then_text_table(self):
        slack, result = self.run_reply({"table"})
        self.assertTrue(result["posted"])
        self.assertEqual(slack.errors, [])
        self.assertTrue(any("text table" in w for w in result["warnings"]))
        blocks = slack.sent[0][1]["attachments"][0]["blocks"]
        self.assertFalse(any(b["type"] == "table" for b in blocks))
        self.assertTrue(any(b["type"] == "context_actions" for b in blocks))   # buttons kept

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


class PlanBlock(unittest.TestCase):
    def test_thinking_message_has_a_plan(self):
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
        card = r.thinking_attachments("rocket", "support", "q", plan=False)
        self.assertEqual([b["type"] for b in card[0]["blocks"]], ["context"])

    def test_plan_can_be_switched_off(self):
        old, r.SHOW_PLAN = r.SHOW_PLAN, False
        try:
            card = r.thinking_attachments("rocket", "support", "q")
        finally:
            r.SHOW_PLAN = old
        self.assertEqual([b["type"] for b in card[0]["blocks"]], ["context"])

    def test_ask_falls_back_when_slack_rejects_the_plan(self):
        slack = ReplyFallback.FakeSlack({"plan"})
        result = {"channel": "C1", "reply_thread_ts": "1.0", "warnings": [], "genie_name": "SNAP",
                  "persona": "support"}
        r.post_thinking(slack, result, "why?")
        self.assertEqual(result["thinking_ts"], "1.2")
        self.assertEqual(slack.errors, [])
        self.assertTrue(any("plan" in w for w in result["warnings"]))
        self.assertEqual([b["type"] for b in slack.sent[0][1]["attachments"][0]["blocks"]],
                         ["context"])


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


if __name__ == "__main__":
    unittest.main()
