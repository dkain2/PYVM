"""
Tests for error_slack.py. Run them before and after any change:

    python3 -B -m unittest test_error_slack          # from this folder
    python3 -B -m unittest test_error_slack -v

Nothing here touches the network: http_json is replaced by a fake world that answers like the error log data table, the Workato
API and Slack, and records every call. Standard library only. This step owns the contract with the step that posts the alert
(action ids, block ids, column names): TestContract pins it, and that step's own test compares with these.

THE GROUPS
    TestContract      the action ids, block ids and column names the alert step must use
    TestRouting       what is not ours is ignored; link and fact buttons are a no-op; the payload comes in any form
    TestJob           which job a click is about: the button value, the block id, the message, the error log
    TestReprocess     the confirmed click: the Workato call, the row, the message, the thread; the guards; a failure
    TestOtherActions  acknowledge, resolve, assign, feedback
    TestCheck         the thread's 'Check status' button: still running, completed, failed again, errors
    TestMessage       the status line is stacked, the used buttons go, an attachment (plain card) is patched too
    TestColumns       a table without the new columns still gets the old ones
    TestSignature     Slack's request signature
    TestNeverFails    odd input and failing services still give an answer
    TestColumnList    data_table_new_columns.md lists exactly the columns the steps write
    TestMode / TestPost / TestRouting   post mode: what mode runs, the post, the route (a retried or deferred error posts nothing)
    TestCompactMessage  short, business first, the carousel, folded panels, technicals then actions last
    TestFeatures / TestFallback   features on and off; a refused block takes one feature out, then the plain card, then text
    TestPostButtons / TestPostShowsEveryInput / TestContract   buttons, every input shown, the notifier's facts are what this step reads
    TestShortLook     the default: short, business only, a 2 x 2 grid of boxes (never a carousel); clicks on grid buttons
    TestSchemas       the schema files match what main() reads and returns
"""

import copy
import hashlib
import hmac
import json
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import error_slack as ec  # noqa: E402

NOW = "2026-11-20T15:41:00-08:00"
MASTER, RECIPE = "j-TestJob1-abcdef-CD", "70000001"
CHANNEL, TS = "C0123ABCD", "1700000000.000100"


class World(object):
    """The error log table, the Workato API and Slack, in one fake."""

    def __init__(self, stored=None, repeat_error=None, repeat=None, slack_fail=(), no_columns=False, no_user=False, fail_table=False,
                 refuse=None, post_error=None, job_status=None, job_status_error=None):
        self.refuse, self.post_error = refuse, post_error
        self.stored = dict(stored or {})
        self.repeat_error, self.repeat = repeat_error, repeat
        self.slack_fail, self.no_columns, self.no_user, self.fail_table = set(slack_fail), no_columns, no_user, fail_table
        self.job_status, self.job_status_error = job_status, job_status_error
        self.calls, self.writes, self.slack, self.repeats = [], [], [], []

    def __call__(self, method, url, headers, payload=None, timeout=12):
        self.calls.append((method, url, payload))
        if url.startswith(ec.SLACK_API):
            name = url[len(ec.SLACK_API):].split("?")[0]
            if name == "users.info":
                if self.no_user:
                    return {"ok": False, "error": "missing_scope"}, None
                uid = url.rsplit("user=", 1)[1]
                return {"ok": True, "user": {"id": uid, "name": uid.lower(), "profile": {
                    "real_name": "Ada Lovelace" if uid == "U0ADA0001" else "Grace Hopper",
                    "email": ("ada" if uid == "U0ADA0001" else "grace") + "@example.com"}}}, None
            if name == "chat.getPermalink":
                return {"ok": True, "permalink": "https://x.slack.com/archives/C0123ABCD/p1700000000000100"}, None
            self.slack.append((name, payload))
            if name == "chat.postMessage" and payload and "unfurl_media" in payload:      # an alert post (a click's reply has none)
                if self.post_error:
                    return {"ok": False, "error": self.post_error}, None
                pointers = self.refuse(payload) if self.refuse else None
                if pointers:
                    return {"ok": False, "error": "invalid_blocks", "response_metadata": {"messages": pointers}}, None
                return {"ok": True, "ts": TS, "channel": payload["channel"]}, None
            if name in self.slack_fail:
                return {"ok": False, "error": "invalid_blocks", "response_metadata": {"messages": ["bad [json-pointer:/blocks/2]"]}}, None
            return {"ok": True, "ts": TS}, None
        if "/jobs/" in url and method == "GET":
            if self.job_status_error:
                return None, self.job_status_error
            return (self.job_status if self.job_status is not None else {"status": "running"}), None
        if url.endswith("/repeat_jobs"):
            self.repeats.append((url, payload))
            if self.repeat_error:
                return None, "www.workato.com 500: " + self.repeat_error
            return self.repeat or {"results": [{"status": "enqueued", "job": {"id": "j-NewRun-9"}}],
                                   "summary": {"total_enqueued": 1}}, None
        if "data-tables" in url:
            if self.fail_table:
                return None, "data-tables.workato.com 500: down"
            if method == "POST" and url.endswith("/query"):
                where = payload["where"]
                column, cond = next(iter(where.items()))
                hits = [(rid, doc) for rid, doc in self.stored.items() if doc.get(column) == cond["$eq"]]
                names = sorted({k for _, doc in hits for k in doc})
                return {"schema": [[{"name": "$record_id"}, {"name": "$created_at"}], [{"name": n} for n in names]],
                        "data": [[[rid, "x"], [doc.get(n) for n in names]] for rid, doc in hits]}, None
            document = (payload or {}).get("document", {})
            if self.no_columns and set(document) & set(ec.TRACK_COLUMNS.values()):
                return None, "data-tables.workato.com 422: unknown column"
            if method == "POST" and url.endswith("/records"):
                rid = "rec-{}".format(len(self.stored) + 1)
                self.stored[rid] = dict(document)
                self.writes.append(("POST", rid, dict(document)))
                return {"data": {"record_id": rid, "document": []}}, None
            if method == "PUT":
                rid = url.rsplit("/", 1)[1]
                self.stored.setdefault(rid, {}).update(document)
                self.writes.append(("PUT", rid, dict(document)))
                return {"data": {"record_id": rid, "document": []}}, None
        return None, "unexpected url " + url

    def slack_calls(self, name):
        return [p for n, p in self.slack if n == name]


def button_value(**extra):
    value = {"v": 1, "m": MASTER, "r": RECIPE, "j": MASTER, "n": "Lead Sync - RealTime", "e": "Production", "p": "High", "s": "260e58db"}
    value.update(extra)
    return json.dumps(value, separators=(",", ":"))


def message_blocks(extra_status=None):
    """An alert as Slack hands it back in a click, trimmed to what a click needs to see."""
    return [
        {"type": "header", "block_id": "en_title_1", "text": {"type": "plain_text", "text": "High · Lead Sync - RealTime"}},
        {"type": "context", "block_id": ec.STATUS_BLOCK_ID, "elements": [{"type": "mrkdwn", "text": extra_status or "🆕 *Open*  ·  nobody has picked this up yet"}]},
        {"type": "actions", "block_id": "en_links_1", "elements": [
            {"type": "button", "action_id": "error_link_1", "text": {"type": "plain_text", "text": "View job"}, "url": "https://x"}]},
        {"type": "actions", "block_id": "{}|{}|{}".format(ec.ACTIONS_BLOCK_ID, MASTER, RECIPE), "elements": [
            {"type": "button", "action_id": ec.ACT_REPROCESS, "text": {"type": "plain_text", "text": "Reprocess"}, "value": button_value()},
            {"type": "button", "action_id": ec.ACT_ACK, "text": {"type": "plain_text", "text": "Acknowledge"}, "value": button_value()},
            {"type": "button", "action_id": ec.ACT_RESOLVE, "text": {"type": "plain_text", "text": "Resolve"}, "value": button_value()},
            {"type": "users_select", "action_id": ec.ACT_ASSIGN, "placeholder": {"type": "plain_text", "text": "Assign"}}]},
    ]


def payload(action_id=ec.ACT_REPROCESS, value=None, user="U0ADA0001", blocks=None, attachments=None, **action):
    act = {"action_id": action_id, "block_id": "{}|{}|{}".format(ec.ACTIONS_BLOCK_ID, MASTER, RECIPE), "type": "button",
           "value": button_value() if value is None else value}
    act.update(action)
    message = {"ts": TS, "text": "High | Failure in Lead Sync"}
    if attachments is not None:
        message["attachments"] = attachments
    else:
        message["blocks"] = blocks if blocks is not None else message_blocks()
    return {"type": "block_actions", "user": {"id": user, "name": user.lower()}, "channel": {"id": CHANNEL},
            "container": {"message_ts": TS, "channel_id": CHANNEL}, "message": message, "actions": [act]}


def stored_row(**extra):
    row = {"Master Job ID": MASTER, "Job Id": MASTER, "Recipie Id": RECIPE, "Recipe Name": "Lead Sync - RealTime",
           "Status": "Notified", "Reprocess Count": 0, "Reprocess_Flag": False, "Slack Message TS": TS}
    row.update(extra)
    return {"rec-1": row}


class Patched(unittest.TestCase):
    def click(self, pl=None, world=None, **extra):
        world = world or World(stored=stored_row())
        data = {"payload": json.dumps(pl if pl is not None else payload()), "workato_api_token": "wt", "slack_bot_token": "xoxb-t", "now": NOW}
        data.update(extra)
        original = ec.http_json
        ec.http_json = world
        try:
            out = ec.main(data)
        finally:
            ec.http_json = original
        return out, world


# The columns Error Notification - TBL had before the tracking columns (read from the live table on 2026-11-20).
OLD_COLUMNS = {"Date", "Reprocess_Flag", "Status", "Reprocess Count", "Error TimeStamp", "Recipe Name", "Error Message", "Frequency",
               "Error Limit", "Recipie Id", "Master Job ID", "Job URL", "Job Id", "Email", "Source System", "Source Object",
               "Target System", "Target Object", "Error File Path", "Error File Sharable URL", "Sharable Link Expires on"}
AUTO_ACTOR = "error_notification (auto)"


class TestContract(unittest.TestCase):
    def test_every_action_that_does_something_starts_with_the_one_prefix(self):
        self.assertEqual(ec.ACTION_PREFIX, "error_notification_")
        for action_id, name in ec.ACTIONS.items():
            self.assertEqual(action_id, ec.ACTION_PREFIX + name)

    def test_links_and_facts_do_not_start_with_it(self):
        # so the trigger filter (action_id starts with the prefix) never lets a click on them run the recipe
        self.assertFalse(ec.INFO_PREFIX.startswith(ec.ACTION_PREFIX))
        self.assertFalse(ec.LINK_PREFIX.startswith(ec.ACTION_PREFIX))
        self.assertFalse(ec.INFO_PREFIX.startswith(ec.LINK_PREFIX) or ec.LINK_PREFIX.startswith(ec.INFO_PREFIX))

    def test_the_block_ids_the_status_line_and_the_buttons_use(self):
        self.assertEqual((ec.STATUS_BLOCK_ID, ec.ACTIONS_BLOCK_ID), ("error_notification_status", "error_notification_actions"))
        self.assertEqual(ec.job_from_block_id("error_notification_actions|j-1|123"), ("j-1", "123"))
        self.assertEqual(ec.job_from_block_id("en_links_1"), ("", ""))

    def test_there_are_26_new_columns_none_of_them_old(self):
        self.assertEqual(len(ec.TRACK_COLUMNS), 26)
        self.assertEqual(len(set(ec.TRACK_COLUMNS.values())), 26)
        self.assertFalse(OLD_COLUMNS & set(ec.TRACK_COLUMNS.values()))

    def test_the_old_columns_this_step_uses_exist_in_the_table(self):
        self.assertTrue(set(ec.BASE_COLUMNS.values()) <= OLD_COLUMNS)

    def test_the_date_columns_are_columns(self):
        self.assertTrue(ec.TRACK_DATE_KEYS <= set(ec.TRACK_COLUMNS))

    def test_what_a_button_carries_is_read_back(self):
        value = json.dumps({"v": 1, "m": MASTER, "r": RECIPE, "j": MASTER, "n": "Lead Sync - RealTime", "e": "Production",
                            "p": "High", "s": "260e58db", "d": "tbl-1"})
        job = ec.job_context(ec.parse_click({"payload": json.dumps(payload(value=value))}))
        self.assertEqual((job["master"], job["recipe_id"], job["recipe_name"], job["table"]), (MASTER, RECIPE, "Lead Sync - RealTime", "tbl-1"))


class TestRouting(Patched):
    def test_a_link_button_is_a_no_op(self):
        out, world = self.click(payload(action_id="error_link_1", value=""))
        self.assertEqual((out["ok"], out["action"], out["handled"]), (True, "noop", False))
        self.assertFalse(world.calls)

    def test_a_fact_button_is_a_no_op(self):
        out, world = self.click(payload(action_id="error_info_3", value="info"))
        self.assertEqual(out["action"], "noop")
        self.assertFalse(world.calls)

    def test_an_action_that_is_not_ours_is_ignored(self):
        out, world = self.click(payload(action_id="genie_feedback"))
        self.assertEqual((out["ok"], out["action"]), (True, "ignored"))
        self.assertFalse(world.calls)

    def test_an_unknown_action_with_our_prefix(self):
        out, world = self.click(payload(action_id="error_notification_selfdestruct"))
        self.assertEqual((out["ok"], out["action"]), (True, "unknown"))
        self.assertFalse(world.calls)

    def test_the_payload_may_come_form_encoded(self):
        import urllib.parse
        raw = "payload=" + urllib.parse.quote(json.dumps(payload(action_id=ec.ACT_ACK)))
        out, _ = self.click(pl=None, **{"payload": raw})
        self.assertEqual(out["action"], "acknowledge")

    def test_the_payload_may_be_an_object(self):
        out, _ = self.click(pl=None, **{"payload": payload(action_id=ec.ACT_ACK)})
        self.assertEqual(out["action"], "acknowledge")

    def test_plain_inputs_win_over_the_payload(self):
        out, _ = self.click(payload(action_id=ec.ACT_ACK), action_id=ec.ACT_RESOLVE)
        self.assertEqual(out["action"], "resolve")

    def test_inputs_alone_are_enough(self):
        out, world = self.click(pl={}, **{"payload": "", "action_id": ec.ACT_ACK, "value": button_value(), "user_id": "U0ADA0001",
                                           "channel": CHANNEL, "message_ts": TS})
        self.assertEqual((out["ok"], out["action"], out["user_name"]), (True, "acknowledge", "Ada Lovelace"))

    def test_nothing_at_all(self):
        out, world = self.click(pl={}, **{"payload": ""})
        self.assertFalse(out["ok"])
        self.assertIn("nothing to do", out["error"])
        self.assertEqual((out["mode"], world.calls), ("", []))

    def test_an_empty_payload_with_an_action_is_still_a_click(self):
        out, _ = self.click(pl={}, **{"payload": "", "action_id": "genie_feedback"})
        self.assertEqual((out["mode"], out["action"], out["ok"]), ("click", "ignored", True))


class TestJob(Patched):
    def test_from_the_button_value(self):
        job = ec.job_context(ec.parse_click({"payload": json.dumps(payload())}))
        self.assertEqual((job["master"], job["recipe_id"], job["environment"], job["priority"]), (MASTER, RECIPE, "Production", "High"))

    def test_a_users_select_has_no_value_so_the_block_id_says(self):
        pl = payload(action_id=ec.ACT_ASSIGN, value="", type="users_select", selected_user="U0GRACE02")
        job = ec.job_context(ec.parse_click({"payload": json.dumps(pl)}))
        self.assertEqual((job["master"], job["recipe_id"]), (MASTER, RECIPE))

    def test_failing_both_the_message_is_searched(self):
        pl = payload(action_id=ec.ACT_FEEDBACK, value="positive", block_id="en_feedback_1")
        job = ec.job_context(ec.parse_click({"payload": json.dumps(pl)}))
        self.assertEqual(job["master"], MASTER)

    def test_failing_all_three_the_error_log_is_searched_by_message_ts(self):
        pl = payload(action_id=ec.ACT_FEEDBACK, value="positive", block_id="en_feedback_1", blocks=[
            {"type": "context", "block_id": "en_feedback_1", "elements": [{"type": "mrkdwn", "text": "x"}]}])
        out, world = self.click(pl)
        self.assertEqual((out["ok"], out["master_job_id"], out["feedback"]), (True, MASTER, "positive"))
        self.assertEqual(world.writes[0][1], "rec-1")

    def test_a_click_that_names_no_job_does_nothing(self):
        pl = payload(value="", block_id="x", blocks=[])
        out, world = self.click(pl, world=World())
        self.assertEqual((out["refused"], world.repeats), ("no job", []))
        self.assertTrue(out["ok"])


class TestReprocess(Patched):
    def test_a_confirmed_click_repeats_the_job(self):
        out, world = self.click()
        self.assertEqual(len(world.repeats), 1)
        url, body = world.repeats[0]
        self.assertTrue(url.endswith("/recipes/{}/repeat_jobs".format(RECIPE)))
        self.assertEqual(body, {"job_ids": [MASTER]})
        self.assertEqual((out["ok"], out["action"], out["reprocess_enqueued"], out["reprocess_job_id"], out["error"]),
                         (True, "reprocess", True, "j-NewRun-9", ""))
        self.assertEqual(out["result"], "Reprocess queued as job j-NewRun-9")

    def test_who_when_and_which_job_are_written_down(self):
        out, world = self.click()
        row = world.stored["rec-1"]
        self.assertEqual((row["Reprocessed By"], row["Reprocessed By Slack ID"], row["Reprocessed By Email"]),
                         ("Ada Lovelace", "U0ADA0001", "ada@example.com"))
        self.assertTrue(row["Reprocessed At"].startswith("2026-11-20T15:41"))
        self.assertEqual((row["Reprocess Job ID"], row["Reprocess Source"], row["Reprocess Result"]), ("j-NewRun-9", "Slack button", "enqueued"))
        self.assertEqual((row["Last Action"], row["Last Action By"], row["Last Action Result"]), ("Reprocess", "Ada Lovelace", "queued as job j-NewRun-9"))
        self.assertIn("Ada Lovelace (U0ADA0001) | Reprocess | queued as job j-NewRun-9", row["Action Log"])
        self.assertEqual(out["row_action"], "updated")

    def test_the_old_columns_the_old_recipes_use_are_kept_in_step(self):
        _, world = self.click()
        row = world.stored["rec-1"]
        self.assertEqual((row["Status"], row["Reprocess Count"], row["Reprocess_Flag"]), ("Reprocessed", 1, False))

    def test_the_count_goes_up_from_what_is_stored(self):
        _, world = self.click(world=World(stored=stored_row(**{"Reprocess Count": 1})))
        self.assertEqual(world.stored["rec-1"]["Reprocess Count"], 2)

    def test_the_status_line_and_the_buttons_change(self):
        out, world = self.click()
        update = world.slack_calls("chat.update")[0]
        self.assertEqual((update["channel"], update["ts"]), (CHANNEL, TS))
        status = [b for b in update["blocks"] if b.get("block_id") == ec.STATUS_BLOCK_ID][0]
        text = status["elements"][0]["text"]
        self.assertIn("♻️ *Reprocess queued* by <@U0ADA0001>", text)
        self.assertIn("job `j-NewRun-9`", text)
        self.assertIn("<!date^", text)
        self.assertNotIn("🆕", text)
        actions = [b for b in update["blocks"] if b.get("block_id", "").startswith(ec.ACTIONS_BLOCK_ID)][0]
        ids = [e["action_id"] for e in actions["elements"]]
        self.assertNotIn(ec.ACT_REPROCESS, ids)
        self.assertIn(ec.ACT_RESOLVE, ids)
        self.assertTrue(out["message_updated"])

    def test_the_link_buttons_are_left_alone(self):
        _, world = self.click()
        update = world.slack_calls("chat.update")[0]
        self.assertIn("error_link_1", [e["action_id"] for b in update["blocks"] if b["type"] == "actions" for e in b["elements"]])

    def test_a_reply_in_the_thread_carries_a_check_status_button(self):
        out, world = self.click()
        reply = world.slack_calls("chat.postMessage")[0]
        self.assertEqual((reply["channel"], reply["thread_ts"]), (CHANNEL, TS))
        self.assertIn("j-NewRun-9", reply["text"])
        block = reply["blocks"][0]
        self.assertEqual(block["block_id"], ec.CHECK_BLOCK_ID)
        self.assertIn("In progress", block["text"]["text"])
        self.assertIs(block["expand"], True)                 # never folded behind "Show more"
        button = block["accessory"]
        self.assertEqual((button["action_id"], button["text"]["text"]), (ec.ACT_CHECK, "🔄 Check status"))
        value = json.loads(button["value"])
        self.assertEqual((value["m"], value["r"], value["j"]), (MASTER, RECIPE, "j-NewRun-9"))
        self.assertTrue(out["thread_posted"])

    def test_without_a_new_job_id_the_thread_reply_is_plain_text(self):
        repeat = {"results": [{"status": "enqueued", "job": {}}], "summary": {"total_enqueued": 1}}
        out, world = self.click(world=World(stored=stored_row(), repeat=repeat))
        reply = world.slack_calls("chat.postMessage")[0]
        self.assertNotIn("blocks", reply)
        self.assertIn("Ada Lovelace reprocessed this job", reply["text"])

    def test_the_message_edit_and_the_reply_can_be_switched_off(self):
        out, world = self.click(update_message="no", thread_reply="no")
        self.assertFalse(world.slack)
        self.assertTrue(out["ok"] and out["reprocess_enqueued"])

    def test_a_second_click_within_the_cooldown_is_refused(self):
        when = (datetime.fromisoformat(NOW) - timedelta(minutes=3)).isoformat()
        world = World(stored=stored_row(**{"Reprocessed At": when, "Reprocessed By": "Grace Hopper", "Reprocess Job ID": "j-Old-1", "Reprocess Count": 1}))
        out, world = self.click(world=world)
        self.assertEqual((out["refused"], world.repeats), ("cooldown", []))
        self.assertIn("3 min ago by Grace Hopper (job j-Old-1)", out["result"])
        self.assertEqual(world.writes, [])
        whisper = world.slack_calls("chat.postEphemeral")[0]
        self.assertEqual((whisper["user"], whisper["channel"]), ("U0ADA0001", CHANNEL))
        self.assertTrue(out["private_message_sent"])
        self.assertFalse(world.slack_calls("chat.update"))                  # the message is not touched by a refusal

    def test_after_the_cooldown_it_goes_through(self):
        when = (datetime.fromisoformat(NOW) - timedelta(minutes=30)).isoformat()
        out, world = self.click(world=World(stored=stored_row(**{"Reprocessed At": when, "Reprocess Count": 1})))
        self.assertTrue(out["reprocess_enqueued"])

    def test_someone_else_just_reprocessed_it(self):
        when = (datetime.fromisoformat(NOW) - timedelta(minutes=2)).isoformat()
        out, world = self.click(world=World(stored=stored_row(**{"Reprocessed At": when, "Reprocessed By": AUTO_ACTOR})))
        self.assertEqual(out["refused"], "cooldown")
        self.assertIn(AUTO_ACTOR, out["result"])

    def test_the_cooldown_can_be_turned_off(self):
        when = (datetime.fromisoformat(NOW) - timedelta(minutes=1)).isoformat()
        out, _ = self.click(world=World(stored=stored_row(**{"Reprocessed At": when})), cooldown_minutes=0)
        self.assertTrue(out["reprocess_enqueued"])

    def test_the_limit_on_reprocesses(self):
        out, world = self.click(world=World(stored=stored_row(**{"Reprocess Count": 3})))
        self.assertEqual((out["refused"], world.repeats), ("max reprocess", []))
        out, world = self.click(world=World(stored=stored_row(**{"Reprocess Count": 3})), max_reprocess=5)
        self.assertTrue(out["reprocess_enqueued"])

    def test_only_the_listed_people_may_reprocess(self):
        out, world = self.click(allowed_user_ids="U0GRACE02, U0OTHER03")
        self.assertEqual((out["refused"], world.repeats), ("not allowed", []))
        out, world = self.click(allowed_user_ids="u0ada0001")
        self.assertTrue(out["reprocess_enqueued"])

    def test_without_a_workato_token_nothing_is_reprocessed(self):
        out, world = self.click(workato_api_token="")
        self.assertEqual((out["refused"], world.repeats), ("no workato_api_token", []))

    def test_a_failed_repeat_is_reported_and_leaves_the_old_columns_alone(self):
        out, world = self.click(world=World(stored=stored_row(), repeat_error="boom"))
        self.assertFalse(out["ok"])
        self.assertIn("boom", out["error"])
        self.assertEqual((out["reprocess_attempted"], out["reprocess_enqueued"]), (True, False))
        row = world.stored["rec-1"]
        self.assertEqual((row["Status"], row["Reprocess Count"]), ("Notified", 0))        # nothing was reprocessed
        self.assertEqual((row["Reprocess Result"], row["Last Action"]), ("failed", "Reprocess"))
        self.assertIn("boom", row["Reprocess Error"])
        self.assertIn("failed", row["Action Log"])
        self.assertNotIn("Reprocessed By", row)                                            # nobody reprocessed it
        update = world.slack_calls("chat.update")[0]
        actions = [b for b in update["blocks"] if b.get("block_id", "").startswith(ec.ACTIONS_BLOCK_ID)][0]
        self.assertIn(ec.ACT_REPROCESS, [e["action_id"] for e in actions["elements"]])      # the button stays: try again
        self.assertIn("Reprocess failed", update["blocks"][1]["elements"][0]["text"])
        self.assertTrue(out["private_message_sent"])

    def test_workato_saying_no_is_a_failure_too(self):
        refused = {"results": [{"status": "failed", "error": "job not repeatable"}], "summary": {"total_enqueued": 0, "total_failed": 1}}
        out, world = self.click(world=World(stored=stored_row(), repeat=refused))
        self.assertFalse(out["reprocess_enqueued"])
        self.assertIn("job not repeatable", out["reprocess_error"])

    def test_a_job_without_a_row_gets_one(self):
        out, world = self.click(world=World())
        self.assertEqual((out["row_action"], world.writes[0][0]), ("inserted", "POST"))
        row = world.stored["rec-1"]
        self.assertEqual((row["Master Job ID"], row["Recipie Id"], row["Recipe Name"], row["Status"]), (MASTER, RECIPE, "Lead Sync - RealTime", "Reprocessed"))
        self.assertEqual(row["Date"], "2026-11-20")

    def test_the_action_log_keeps_what_was_there(self):
        old = "2026-11-19T10:00:00-08:00 | Dev One (U1) | Acknowledge | acknowledged"
        _, world = self.click(world=World(stored=stored_row(**{"Action Log": old})))
        log = world.stored["rec-1"]["Action Log"].splitlines()
        self.assertEqual(log[0], old)
        self.assertIn("Reprocess", log[-1])

    def test_a_table_that_cannot_be_written_does_not_undo_the_reprocess(self):
        out, world = self.click(world=World(stored=stored_row(), fail_table=True))
        self.assertTrue(out["reprocess_enqueued"])
        self.assertTrue(any("error log" in w for w in out["warnings"]))
        self.assertTrue(world.repeats)

    def test_the_users_name_falls_back_to_the_payload(self):
        out, world = self.click(world=World(stored=stored_row(), no_user=True))
        self.assertEqual(out["user_name"], "u0ada0001")
        self.assertEqual(world.stored["rec-1"]["Reprocessed By Slack ID"], "U0ADA0001")
        self.assertTrue(any("user not looked up" in w for w in out["warnings"]))


def check_value(**extra):
    value = {"v": 1, "m": MASTER, "r": RECIPE, "j": "j-NewRun-9", "t": NOW}
    value.update(extra)
    return json.dumps(value, separators=(",", ":"))


def check_block(value=None, with_button=True, text="⏳ *In progress* · job `j-NewRun-9`"):
    block = {"type": "section", "block_id": ec.CHECK_BLOCK_ID, "text": {"type": "mrkdwn", "text": text}}
    if with_button:
        block["accessory"] = {"type": "button", "action_id": ec.ACT_CHECK,
                              "text": {"type": "plain_text", "text": "🔄 Check status"},
                              "value": value if value is not None else check_value()}
    return block


def check_payload(value=None, **extra):
    return payload(action_id=ec.ACT_CHECK, value=value if value is not None else check_value(),
                   blocks=[check_block(value if value is not None else check_value())], **extra)


class TestCheck(Patched):
    """The 'Check status' button a successful reprocess posts in the thread."""

    def check(self, world=None, value=None, **extra):
        return self.click(check_payload(value), world=world or World(stored=stored_row()), **extra)

    def test_still_running_relabels_the_button(self):
        out, world = self.check(world=World(stored=stored_row(), job_status={"status": "running"}))
        self.assertEqual((out["ok"], out["action"], out["check_result"], out["result"]), (True, "check", "running", "still running"))
        update = world.slack_calls("chat.update")[0]
        block = update["blocks"][0]
        self.assertEqual(block["block_id"], ec.CHECK_BLOCK_ID)
        self.assertIn("Still running", block["text"]["text"])
        self.assertEqual(block["accessory"]["text"]["text"], "🔄 Check again")
        self.assertEqual(json.loads(block["accessory"]["value"]), json.loads(check_value()))   # the same job, for the next click
        self.assertFalse(world.slack_calls("chat.postMessage"))                                 # nothing new in the thread yet

    def test_completed_closes_the_button_and_logs_it(self):
        out, world = self.check(world=World(stored=stored_row(), job_status={"status": "succeeded", "completed_at": "2026-11-20T16:00:00Z"}))
        self.assertEqual((out["check_result"], out["result"]), ("completed", "completed"))
        update = world.slack_calls("chat.update")[0]
        block = update["blocks"][0]
        self.assertIn("Completed", block["text"]["text"])
        self.assertNotIn("accessory", block)
        self.assertFalse(world.slack_calls("chat.postMessage"))
        row = world.stored["rec-1"]
        self.assertEqual((row["Reprocess Result"], row["Last Action"]), ("completed", "Check"))

    def test_failed_again_brings_the_error_back_and_closes_the_button(self):
        fake = World(stored=stored_row(Status="Failed Again", **{"Error TimeStamp": "2026-11-20T16:05:00-08:00",
                                                                  "Error Message": "INVALID_SESSION_ID: Salesforce sign-in failed"}),
                    job_status={"status": "failed", "completed_at": "2026-11-20T16:06:00Z"})
        out, world = self.check(world=fake)
        self.assertEqual((out["check_result"], out["result"]), ("failed_again", "failed again"))
        update = world.slack_calls("chat.update")[0]
        self.assertIn("Failed again", update["blocks"][0]["text"]["text"])
        self.assertNotIn("accessory", update["blocks"][0])
        reply = world.slack_calls("chat.postMessage")[0]
        self.assertEqual(reply["thread_ts"], TS)
        self.assertIn("failed again", reply["text"])
        self.assertIn("INVALID_SESSION_ID: Salesforce sign-in failed", reply["text"])
        row = world.stored["rec-1"]
        self.assertEqual(row["Reprocess Result"], "failed_again")

    def test_a_stale_failed_again_from_before_this_reprocess_reads_as_completed(self):
        fake = World(stored=stored_row(Status="Failed Again", **{"Error TimeStamp": "2026-11-19T10:00:00-08:00",
                                                                  "Error Message": "an older failure"}),
                    job_status={"status": "succeeded", "completed_at": "2026-11-20T16:00:00Z"})
        out, world = self.check(world=fake, value=check_value(t="2026-11-20T15:41:00-08:00"))
        self.assertEqual(out["check_result"], "completed")
        self.assertFalse(world.slack_calls("chat.postMessage"))

    def test_without_a_reprocessed_at_a_failed_again_row_is_still_trusted(self):
        fake = World(stored=stored_row(Status="Failed Again", **{"Error Message": "boom"}),
                    job_status={"status": "failed", "completed_at": "2026-11-20T16:00:00Z"})
        out, world = self.check(world=fake, value=check_value(t=""))
        self.assertEqual(out["check_result"], "failed_again")

    def test_without_a_job_id_in_the_button_it_is_refused(self):
        out, world = self.check(value=check_value(j=""))
        self.assertEqual((out["refused"], out["ok"]), ("no job", True))
        self.assertFalse([c for c in world.calls if "/jobs/" in c[1]])          # never asked Workato for a status

    def test_without_a_workato_token_it_is_refused(self):
        out, world = self.click(check_payload(), workato_api_token="")
        self.assertEqual(out["refused"], "no workato_api_token")

    def test_a_failed_check_call_is_only_a_warning_not_an_error(self):
        out, world = self.check(world=World(stored=stored_row(), job_status_error="www.workato.com 500: down"))
        self.assertTrue(out["ok"])
        self.assertIn("check failed", out["result"])
        self.assertFalse(world.slack_calls("chat.update"))
        self.assertTrue(world.slack_calls("chat.postEphemeral"))
        self.assertTrue(any("job status not read" in w for w in out["warnings"]))

    def test_the_action_id_is_wired_through_detect_mode_and_handlers(self):
        self.assertEqual(ec.ACTIONS[ec.ACT_CHECK], "check")
        self.assertIn("check", ec.HANDLERS)
        self.assertTrue(ec.ACT_CHECK.startswith(ec.ACTION_PREFIX))                 # the one trigger filter still catches it


class TestOtherActions(Patched):
    def test_acknowledge(self):
        out, world = self.click(payload(action_id=ec.ACT_ACK))
        row = world.stored["rec-1"]
        self.assertEqual((row["Acknowledged By"], row["Last Action"]), ("Ada Lovelace", "Acknowledge"))
        self.assertTrue(row["Acknowledged At"].startswith("2026-11-20T15:41"))
        text = world.slack_calls("chat.update")[0]["blocks"][1]["elements"][0]["text"]
        self.assertIn("🙋 <@U0ADA0001> *is looking into it*", text)
        self.assertEqual(row["Status"], "Notified")                                       # acknowledging does not change the old columns
        actions = [b for b in world.slack_calls("chat.update")[0]["blocks"] if b.get("block_id", "").startswith(ec.ACTIONS_BLOCK_ID)][0]
        self.assertNotIn(ec.ACT_ACK, [e["action_id"] for e in actions["elements"]])
        self.assertIn(ec.ACT_REPROCESS, [e["action_id"] for e in actions["elements"]])

    def test_resolve_closes_the_buttons(self):
        out, world = self.click(payload(action_id=ec.ACT_RESOLVE))
        row = world.stored["rec-1"]
        self.assertEqual((row["Resolved By"], row["Last Action"]), ("Ada Lovelace", "Resolve"))
        update = world.slack_calls("chat.update")[0]
        self.assertFalse([b for b in update["blocks"] if b.get("block_id", "").startswith(ec.ACTIONS_BLOCK_ID)])
        self.assertIn("✅ *Resolved*", update["blocks"][1]["elements"][0]["text"])

    def test_resolve_follows_the_allowed_list(self):
        out, world = self.click(payload(action_id=ec.ACT_RESOLVE), allowed_user_ids="U0GRACE02")
        self.assertEqual((out["refused"], world.writes), ("not allowed", []))

    def test_assign(self):
        pl = payload(action_id=ec.ACT_ASSIGN, value="", type="users_select", selected_user="U0GRACE02")
        out, world = self.click(pl)
        self.assertEqual(world.stored["rec-1"]["Assigned To"], "Grace Hopper (U0GRACE02)")
        reply = world.slack_calls("chat.postMessage")[0]["text"]
        self.assertIn("<@U0GRACE02>", reply)                                              # the assignee is tagged
        self.assertEqual(out["assigned_user_id"], "U0GRACE02")
        text = world.slack_calls("chat.update")[0]["blocks"][1]["elements"][0]["text"]
        self.assertIn("🙋 *Assigned to* <@U0GRACE02> by <@U0ADA0001>", text)

    def test_assign_without_a_person(self):
        out, world = self.click(payload(action_id=ec.ACT_ASSIGN, value="", type="users_select"))
        self.assertEqual(out["refused"], "no user")

    def test_feedback_is_logged_and_thanked_in_private(self):
        pl = payload(action_id=ec.ACT_FEEDBACK, value="negative", type="feedback_buttons")
        out, world = self.click(pl)
        row = world.stored["rec-1"]
        self.assertEqual(row["AI Feedback"], "negative")
        self.assertIn("AI feedback | negative", row["Action Log"])
        self.assertEqual(out["feedback"], "negative")
        self.assertTrue(world.slack_calls("chat.postEphemeral"))
        self.assertFalse(world.slack_calls("chat.update"))                                # the message is left alone
        self.assertNotIn("Last Action", row)                                              # feedback is not an action on the error

    def test_feedback_that_is_neither(self):
        out, _ = self.click(payload(action_id=ec.ACT_FEEDBACK, value="meh", type="feedback_buttons"))
        self.assertEqual(out["refused"], "bad feedback")


class TestMessage(unittest.TestCase):
    def blocks(self):
        return [dict(b) for b in message_blocks()]

    def test_lines_are_stacked_newest_first_without_the_open_line(self):
        self.assertEqual(ec.stacked("🆕 *Open*  ·  x", "new"), "new")
        self.assertEqual(ec.stacked("a\nb", "new"), "new\na\nb")
        self.assertEqual(len(ec.stacked("\n".join("l{}".format(i) for i in range(20)), "new").splitlines()), ec.STATUS_LINES)

    def test_patch_blocks(self):
        blocks = self.blocks()
        self.assertTrue(ec.patch_blocks(blocks, "line", {ec.ACT_REPROCESS}))
        self.assertEqual(ec.status_text(blocks), "line")
        actions = [b for b in blocks if b.get("block_id", "").startswith(ec.ACTIONS_BLOCK_ID)][0]
        self.assertNotIn(ec.ACT_REPROCESS, [e["action_id"] for e in actions["elements"]])

    def test_an_emptied_actions_block_goes(self):
        blocks = self.blocks()
        ec.patch_blocks(blocks, "x", {ec.ACT_REPROCESS, ec.ACT_ACK, ec.ACT_RESOLVE, ec.ACT_ASSIGN})
        self.assertFalse([b for b in blocks if b.get("block_id", "").startswith(ec.ACTIONS_BLOCK_ID)])

    def test_the_original_message_is_not_changed_in_place(self):
        message = payload()["message"]
        before = json.dumps(message)
        ec.edit_message(message, lambda blocks: ec.patch_blocks(blocks, "x", {ec.ACT_REPROCESS}))
        self.assertEqual(json.dumps(message), before)


class TestAttachmentMessage(Patched):
    def test_the_plain_card_is_patched_inside_its_attachment(self):
        attachments = [{"color": "#EA580C", "fallback": "x", "blocks": message_blocks()}]
        out, world = self.click(payload(attachments=attachments))
        update = world.slack_calls("chat.update")[0]
        self.assertNotIn("blocks", update)
        status = [b for b in update["attachments"][0]["blocks"] if b.get("block_id") == ec.STATUS_BLOCK_ID][0]
        self.assertIn("Reprocess queued", status["elements"][0]["text"])
        self.assertEqual(update["attachments"][0]["color"], "#EA580C")
        self.assertTrue(out["message_updated"])


class TestMessageFailures(Patched):
    def test_a_message_that_cannot_be_edited_is_only_a_warning(self):
        out, world = self.click(world=World(stored=stored_row(), slack_fail=("chat.update",)))
        self.assertTrue(out["ok"] and out["reprocess_enqueued"])
        self.assertFalse(out["message_updated"])
        self.assertTrue(any("message not updated" in w for w in out["warnings"]))
        self.assertTrue(out["thread_posted"])                                              # the thread reply still says it

    def test_a_click_without_the_message_still_works(self):
        pl = payload()
        pl["message"] = {}
        out, world = self.click(pl)
        self.assertTrue(out["reprocess_enqueued"])
        self.assertFalse(world.slack_calls("chat.update"))
        self.assertTrue(any("message" in w for w in out["warnings"]))

    def test_without_a_slack_token_the_job_is_still_reprocessed(self):
        out, world = self.click(slack_bot_token="")
        self.assertTrue(out["reprocess_enqueued"])
        self.assertFalse(world.slack)
        self.assertEqual(out["user_name"], "u0ada0001")


class TestColumns(Patched):
    def test_a_table_without_the_new_columns_still_gets_the_old_ones(self):
        out, world = self.click(world=World(stored=stored_row(), no_columns=True))
        row = world.stored["rec-1"]
        self.assertEqual((row["Status"], row["Reprocess Count"], row["Reprocess_Flag"]), ("Reprocessed", 1, False))
        self.assertNotIn("Reprocessed By", row)
        self.assertTrue(any("tracking columns are not in the error log table" in w for w in out["warnings"]))
        self.assertTrue(out["reprocess_enqueued"])

    def test_an_action_with_only_new_columns_is_skipped_not_failed(self):
        out, world = self.click(payload(action_id=ec.ACT_ACK), world=World(stored=stored_row(), no_columns=True))
        self.assertEqual(out["row_action"], "skipped")
        self.assertTrue(out["ok"])
        self.assertTrue(world.slack_calls("chat.update"))                                  # the message still says it


class TestSignature(Patched):
    SECRET = "s3cret"

    def signed(self, body, stamp=None, secret=None):
        stamp = stamp or str(int(datetime.fromisoformat(NOW).timestamp()))
        digest = hmac.new((secret or self.SECRET).encode(), "v0:{}:{}".format(stamp, body).encode(), hashlib.sha256).hexdigest()
        return {"raw_body": body, "slack_request_timestamp": stamp, "slack_signature": "v0=" + digest, "slack_signing_secret": self.SECRET}

    def test_a_good_signature_goes_through(self):
        body = "payload=whatever"
        out, world = self.click(**self.signed(body))
        self.assertTrue(out["signature_checked"])
        self.assertTrue(out["reprocess_enqueued"])

    def test_a_wrong_signature_does_nothing(self):
        out, world = self.click(**self.signed("payload=x", secret="other"))
        self.assertEqual((out["ok"], out["refused"], out["handled"]), (False, "bad signature", False))
        self.assertFalse(world.calls)

    def test_a_tampered_body_does_nothing(self):
        data = self.signed("payload=x")
        data["raw_body"] = "payload=y"
        out, world = self.click(**data)
        self.assertEqual(out["refused"], "bad signature")
        self.assertFalse(world.calls)

    def test_an_old_request_does_nothing(self):
        old = str(int(datetime.fromisoformat(NOW).timestamp()) - 3600)
        out, world = self.click(**self.signed("payload=x", stamp=old))
        self.assertIn("too old", out["error"])
        self.assertFalse(world.calls)

    def test_a_secret_with_no_signature_does_nothing(self):
        out, world = self.click(slack_signing_secret=self.SECRET)
        self.assertEqual(out["refused"], "bad signature")
        self.assertFalse(world.calls)

    def test_no_secret_no_check(self):
        out, _ = self.click()
        self.assertFalse(out["signature_checked"])


class TestNeverFails(Patched):
    def test_odd_inputs(self):
        for bad in (None, {}, {"payload": 5}, {"payload": "{not json"}, {"payload": json.dumps({"actions": "x"})},
                    {"payload": json.dumps({"actions": [None]})}, {"payload": json.dumps({"actions": [{"action_id": ec.ACT_REPROCESS}]})},
                    "a string", []):
            out = ec.main(bad)
            self.assertIn("ok", out)
            self.assertIsInstance(out["warnings"], list)

    def test_a_click_with_nothing_but_the_action(self):
        out, world = self.click({"actions": [{"action_id": ec.ACT_REPROCESS}]}, world=World())
        self.assertTrue(out["ok"])
        self.assertEqual((out["refused"], world.repeats), ("no job", []))

    def test_every_service_down(self):
        class Down(object):
            def __call__(self, *a, **k):
                return None, "everything is down"
        original = ec.http_json
        ec.http_json = Down()
        try:
            out = ec.main({"payload": json.dumps(payload()), "workato_api_token": "t", "slack_bot_token": "s", "now": NOW})
        finally:
            ec.http_json = original
        self.assertFalse(out["reprocess_enqueued"])
        self.assertIn("reprocess failed", out["error"])
        self.assertIsInstance(out["warnings"], list)

    def test_an_exception_inside_is_caught(self):
        original = ec.repeat_job
        ec.repeat_job = lambda *a: 1 / 0
        try:
            out, _ = self.click()
        finally:
            ec.repeat_job = original
        self.assertFalse(out["ok"])
        self.assertIn("ZeroDivisionError", out["error"])

    def test_the_time_budget_is_respected(self):
        out, world = self.click(time_budget=5, http_timeout=3)
        self.assertTrue(out["ok"])


class TestColumnList(unittest.TestCase):
    """data_table_new_columns.md is what the user adds to the table by hand: it must list exactly the columns the steps write."""

    def test_the_file_lists_every_tracking_column_once_with_its_type(self):
        with open(os.path.join(HERE, "data_table_new_columns.md"), encoding="utf-8") as handle:
            rows = [re.split(r"\s*\|\s*", line.strip().strip("|")) for line in handle if re.match(r"^\|\s*\d+\s*\|", line)]
        listed = [(r[1], r[2]) for r in rows]
        expected = [(column, "date_time" if key in ec.TRACK_DATE_KEYS else "string") for key, column in ec.TRACK_COLUMNS.items()]
        self.assertEqual(listed, expected)
        self.assertEqual(len(listed), 26)


# ================================================================================================ POST mode

NOTIFIER = os.path.join(os.path.dirname(HERE), "error_notification")


def notifier_facts(**extra):
    """The alert_json the real notifier produces for the sample input: the fixture, and the contract between the two steps."""
    sys.path.insert(0, NOTIFIER)
    import error_notification as en
    with open(os.path.join(NOTIFIER, "testdata", "sample_input.json"), encoding="utf-8") as handle:
        data = json.load(handle)
    data.update(ai="no", **extra)
    out = en.main(data)
    return json.loads(out["alert_json"])


def walk(blocks):
    """Every block, nested ones too (layout rows, container children, condition cases, carousel cards)."""
    for block in blocks:
        yield block
        kids = list(block.get("child_blocks") or []) + list(block.get("elements") or []) if block.get("type") in ("container", "carousel") else []
        for row in block.get("rows") or []:
            if block.get("type") == "layout":
                kids += [item["block"] for item in row["items"]]
        for case in block.get("cases") or []:
            kids += case["blocks"]
        kids += block.get("default") or []
        for kid in walk(kids):
            yield kid


def all_text(value):
    if isinstance(value, str):
        return value + "\n"
    if isinstance(value, dict):
        return "".join(all_text(v) for v in value.values())
    if isinstance(value, list):
        return "".join(all_text(v) for v in value)
    return ""


def slack_problems(blocks):
    """What Slack would refuse, from the limits it has told us about (friday_summary, the genie responder, the Block Kit docs)."""
    bad, ids, tables, markdown = [], set(), 0, 0
    if len(blocks) > ec.SL_MAX_BLOCKS:
        bad.append("{} blocks".format(len(blocks)))
    if len(json.dumps(blocks).encode("utf-8")) > ec.SL_MAX_BYTES + 5000:
        bad.append("message too big")
    for b in walk(blocks):
        kind = b.get("type")
        if b.get("block_id"):
            if b["block_id"] in ids:
                bad.append("duplicate block_id " + b["block_id"])
            ids.add(b["block_id"])
            if len(b["block_id"]) > 255:
                bad.append("block_id too long")
        if kind == "header" and len(b["text"]["text"]) > 150:
            bad.append("header over 150")
        if kind == "section":
            if len(b.get("text", {}).get("text", "")) > 3000:
                bad.append("section text over 3000")
            if len(b.get("fields", [])) > 10 or any(len(f["text"]) > 2000 for f in b.get("fields", [])):
                bad.append("fields over the limit")
            if not b.get("text") and not b.get("fields"):
                bad.append("empty section")
        if kind == "context" and len(b["elements"]) > 10:
            bad.append("context over 10")
        if kind == "actions":
            if len(b["elements"]) > 25:
                bad.append("actions over 25")
            action_ids = [e["action_id"] for e in b["elements"]]
            if len(set(action_ids)) != len(action_ids):
                bad.append("duplicate action_id in a block")
            for e in b["elements"]:
                if e["type"] == "button":
                    if len(e["text"]["text"]) > 75 or len(e.get("value", "")) > 2000 or e.get("style") not in (None, "primary", "danger"):
                        bad.append("bad button")
                    if e.get("confirm"):
                        c = e["confirm"]
                        if len(c["title"]["text"]) > 100 or len(c["text"]["text"]) > 300 or len(c["confirm"]["text"]) > 30 or len(c["deny"]["text"]) > 30:
                            bad.append("confirm too long")
        if kind == "carousel":
            if len(b["elements"]) > 10:
                bad.append("carousel over 10")
            for card in b["elements"]:
                if len(card.get("title", {}).get("text", "")) > 150 or len(card.get("subtitle", {}).get("text", "")) > 150:
                    bad.append("card title/subtitle over 150")
                if len(card.get("body", {}).get("text", "")) > 200:
                    bad.append("card body over 200")
                if len(card.get("actions", [])) > 3:
                    bad.append("card with more than three buttons")
        if kind == "table":
            tables += 1
        if kind in ("table", "data_table"):
            if len(b["rows"]) > 100 or any(len(r) > 20 for r in b["rows"]) or any(len(r) != len(b["rows"][0]) for r in b["rows"]):
                bad.append(kind + " rows or columns wrong")
            if sum(len(all_text(r)) for r in b["rows"]) > 12000:
                bad.append(kind + " too many characters")
            if kind == "table" and any(s is None for s in b.get("column_settings", [])):
                bad.append("a null column setting")
        if kind == "markdown":
            markdown += len(b["text"])
        if kind == "container" and b.get("has_header_divider") and b.get("is_collapsible"):
            bad.append("a container with both a divider and a fold")
        if kind in ("container", "layout"):
            for kid in ([i["block"] for r in b.get("rows", []) for i in r["items"]] + b.get("child_blocks", [])):
                if not kid.get("block_id"):
                    bad.append("a block inside {} without a block_id".format(kind))
        if kind == "data_visualization" and b["chart"]["type"] in ("bar", "line", "area"):
            cats = b["chart"]["axis_config"]["categories"]
            if any([d["label"] for d in s["data"]] != cats for s in b["chart"]["series"]):
                bad.append("series labels differ from the categories")
    if tables > 1:
        bad.append("more than one table block")
    if markdown > 12000:
        bad.append("markdown over 12000")
    return bad


def action_ids(blocks):
    """Every action id in a message: button rows, buttons in cards, a section's button (the Take it on the status line)."""
    ids = []
    for b in walk(blocks):
        if b.get("type") == "actions":
            ids += [e["action_id"] for e in b["elements"]]
        ids += [a["action_id"] for a in b.get("actions", [])] if b.get("type") == "card" else []
        if (b.get("accessory") or {}).get("action_id"):
            ids.append(b["accessory"]["action_id"])
    return ids


def sent_blocks(sent):
    """The blocks of a posted message: at the top level, or inside its one attachment (the short look's red bar)."""
    return sent.get("blocks") or (sent.get("attachments") or [{}])[0].get("blocks") or []


class PostCase(unittest.TestCase):
    def post(self, facts=None, world=None, **extra):
        world = world or World(stored=stored_row())
        data = {"slack_channel_id": CHANNEL, "slack_bot_token": "xoxb-t", "workato_api_token": "wt", "now": NOW, "slack_look": "full",
                "alert_json": json.dumps(notifier_facts() if facts is None else facts)}
        data.update(extra)
        original = ec.http_json
        ec.http_json = world
        try:
            out = ec.main(data)
        finally:
            ec.http_json = original
        return out, world

    def blocks(self, facts=None, **extra):
        out, world = self.post(facts, **extra)
        return sent_blocks(world.slack_calls("chat.postMessage")[0]), out, world


class TestMode(PostCase):
    def test_a_channel_means_post_and_a_payload_means_click(self):
        out, _ = self.post()
        self.assertEqual(out["mode"], "post")
        out, _ = self.click_like()
        self.assertEqual(out["mode"], "click")

    def click_like(self):
        original = ec.http_json
        ec.http_json = World(stored=stored_row())
        try:
            return ec.main({"payload": json.dumps(payload(action_id=ec.ACT_ACK)), "now": NOW}), None
        finally:
            ec.http_json = original

    def test_mode_can_be_forced(self):
        out, _ = self.post(mode="click")
        self.assertEqual((out["mode"], out["action"]), ("click", "ignored"))       # no action id: not one of ours

    def test_a_channel_wins_nothing_over_a_payload(self):
        original = ec.http_json
        ec.http_json = World(stored=stored_row())
        try:
            out = ec.main({"payload": json.dumps(payload(action_id=ec.ACT_ACK)), "slack_channel_id": CHANNEL, "now": NOW})
        finally:
            ec.http_json = original
        self.assertEqual(out["mode"], "click")

    def test_alert_json_without_a_channel_is_an_error_not_a_guess(self):
        out, world = self.post(slack_channel_id="")
        self.assertEqual((out["mode"], out["ok"]), ("post", False))
        self.assertIn("slack_channel_id", out["error"])
        self.assertFalse(world.slack)


class TestPost(PostCase):
    def test_the_message_is_posted_with_the_token(self):
        out, world = self.post()
        call = [c for c in world.calls if c[1].endswith("chat.postMessage")][0]
        self.assertEqual(call[0], "POST")
        payload_ = world.slack_calls("chat.postMessage")[0]
        self.assertEqual(payload_["channel"], CHANNEL)
        self.assertIs(payload_["unfurl_links"], False)
        self.assertTrue(payload_["text"] and payload_["blocks"])
        self.assertEqual((out["ok"], out["posted"], out["message_ts"], out["look_used"], out["alert_source"]), (True, True, TS, "new", "alert_json"))
        self.assertIn("p1700000000000100", out["permalink"])
        self.assertEqual(json.loads(out["blocks_json"]), payload_["blocks"])
        self.assertEqual(out["blocks"], len(payload_["blocks"]))

    def test_the_text_is_the_subject_headline_and_verdict(self):
        _, world = self.post()
        text = world.slack_calls("chat.postMessage")[0]["text"]
        self.assertIn("Failure in Salesforce", text)
        self.assertIn("Will not auto retry", text)
        self.assertIn("https://app.workato.com/recipes/70000001/job/", text)

    def test_a_thread_reply(self):
        _, world = self.post(slack_thread_ts="1699999999.000100")
        self.assertEqual(world.slack_calls("chat.postMessage")[0]["thread_ts"], "1699999999.000100")

    def test_the_mention_is_for_critical_and_high_only(self):
        facts = notifier_facts()
        blocks, _, world = self.blocks(facts, slack_mention="<!subteam^S01>")
        self.assertEqual(facts["sev"]["label"], "High")
        self.assertIn("<!subteam^S01>", all_text(blocks))
        self.assertIn("<!subteam^S01>", world.slack_calls("chat.postMessage")[0]["text"])
        facts["sev"] = {"label": "Medium", "emoji": "⚠️", "color": "#D97706"}
        blocks, _, _ = self.blocks(facts, slack_mention="<!subteam^S01>")
        self.assertNotIn("<!subteam^S01>", all_text(blocks))

    def test_where_the_message_is_goes_to_the_error_log_row(self):
        out, world = self.post()
        row = world.stored["rec-1"]
        self.assertEqual((row["Slack Channel"], row["Slack Message TS"], row["Notified Via"]), (CHANNEL, TS, "Email + Slack"))
        self.assertIn("p1700000000000100", row["Slack Message URL"])
        self.assertTrue(row["Notified At"].startswith("2026-11-20T15:41"))
        self.assertEqual(row["Status"], "Notified")                                    # the rest of the row is left alone
        self.assertEqual(out["row_action"], "updated")

    def test_a_table_without_the_columns_is_only_a_warning(self):
        out, world = self.post(world=World(stored=stored_row(), no_columns=True))
        self.assertTrue(out["posted"])
        self.assertEqual(out["row_action"], "skipped")
        self.assertTrue(any("tracking columns are not in the error log table" in w for w in out["warnings"]))

    def test_no_row_for_the_job_is_only_a_warning(self):
        out, _ = self.post(world=World())
        self.assertTrue(out["posted"])
        self.assertTrue(any("no row for this job yet" in w for w in out["warnings"]))

    def test_without_a_workato_token_the_post_still_goes(self):
        out, world = self.post(workato_api_token="")
        self.assertTrue(out["posted"])
        self.assertFalse(world.writes)

    def test_a_slack_error_is_final_and_never_raises(self):
        out, world = self.post(world=World(stored=stored_row(), post_error="not_in_channel"))
        self.assertFalse(out["ok"])
        self.assertIn("not_in_channel", out["error"])
        self.assertEqual(len(world.slack_calls("chat.postMessage")), 1)                # no other look would do better
        self.assertFalse(out["posted"])

    def test_without_a_token_nothing_is_posted(self):
        out, world = self.post(slack_bot_token="")
        self.assertEqual(out["error"], "no slack_bot_token")
        self.assertFalse(world.slack)

    def test_a_part_that_cannot_be_built_is_left_out_not_fatal(self):
        original = ec.b_technical
        ec.b_technical = lambda f, look, cfg: 1 / 0
        try:
            out, world = self.post()
        finally:
            ec.b_technical = original
        self.assertTrue(out["posted"])
        self.assertTrue(any("b_technical left out" in w for w in out["warnings"]))

    def test_an_exception_in_the_whole_build_falls_back_to_the_plain_card(self):
        original = ec.build_slack
        ec.build_slack = lambda *a: 1 / 0
        try:
            out, _ = self.post()
        finally:
            ec.build_slack = original
        self.assertEqual(out["look_used"], "old")
        self.assertTrue(any("building the Slack message failed" in w for w in out["warnings"]))


class TestRouting(PostCase):
    def test_a_retried_error_posts_nothing(self):
        facts = notifier_facts()
        facts["send_email"] = False
        out, world = self.post(facts)
        self.assertFalse(world.slack_calls("chat.postMessage"))
        self.assertIn("retried", out["skipped"])
        self.assertTrue(out["ok"])

    def test_a_deferred_call_posts_nothing(self):
        facts = notifier_facts()
        facts["deferred"] = True
        out, world = self.post(facts)
        self.assertFalse(world.slack_calls("chat.postMessage"))
        self.assertIn("deferral", out["skipped"])

    def test_no_alert_json_posts_a_short_alert_from_the_inputs(self):
        out, world = self.post(alert_json="", subject="Failure in Lead Sync", recipe_name="Lead Sync - RealTime", priority="Critical",
                               error_details="<p>Salesforce connection is broken</p>",
                               job_url="https://app.workato.com/recipes/70000001/job/j-TestJob1-abcdef-CD")
        self.assertEqual((out["posted"], out["alert_source"]), (True, "inputs"))
        text = all_text(world.slack_calls("chat.postMessage")[0]["blocks"])
        self.assertIn("Lead Sync - RealTime", text)
        self.assertIn("Salesforce connection is broken", text)
        self.assertIn("Critical", text)
        self.assertTrue(any("no alert_json" in w for w in out["warnings"]))

    def test_alert_json_that_is_not_json_is_a_warning_and_a_short_alert(self):
        out, _ = self.post(alert_json="{nope", recipe_name="x")
        self.assertTrue(out["posted"])
        self.assertTrue(any("not valid JSON" in w for w in out["warnings"]))

    def test_alert_json_may_be_an_object(self):
        out, _ = self.post(alert_json=notifier_facts())
        self.assertEqual(out["alert_source"], "alert_json")


class TestCompactMessage(PostCase):
    """The message is short, and reads business first, the technical part and the actions last."""

    def test_it_is_compact_and_within_slacks_limits(self):
        blocks, _, _ = self.blocks()
        self.assertLessEqual(len(blocks), 16)
        self.assertEqual(slack_problems(blocks), [])

    def test_the_default_is_one_carousel_two_folded_panels_and_no_charts(self):
        blocks, _, _ = self.blocks()
        kinds = [b["type"] for b in blocks]
        self.assertEqual(kinds.count("carousel"), 1)
        panels = [b for b in blocks if b["type"] == "container"]
        self.assertEqual(len(panels), 2)
        self.assertTrue(all(p["default_collapsed"] for p in panels))
        self.assertTrue({"data_visualization", "layout", "condition", "markdown"}.isdisjoint({b["type"] for b in walk(blocks)}))

    def test_the_order_is_business_then_the_carousel_then_technicals_then_actions(self):
        blocks, _, _ = self.blocks()
        kinds = [(b["type"], b.get("title", {}).get("text", "") if b["type"] == "container" else "") for b in blocks]
        index = lambda pred: [i for i, k in enumerate(kinds) if pred(k)]
        business = [i for i, b in enumerate(blocks) if b["type"] == "section" and "What" in all_text(b) or b.get("block_id", "").startswith("en_business")][0]
        carousel = index(lambda k: k[0] == "carousel")[0]
        records = index(lambda k: k[1].startswith("Failed records"))[0]
        tech = index(lambda k: k[1] == "Technical details")[0]
        actions = index(lambda k: k[0] == "actions")
        self.assertLess(business, carousel)
        self.assertLess(carousel, records)
        self.assertLess(records, tech)
        self.assertLess(tech, min(actions))                                          # the buttons come last
        self.assertEqual(blocks[-1]["type"], "context")                              # then only the footer

    def test_the_first_visible_text_after_the_title_is_the_business_message(self):
        blocks, _, _ = self.blocks()
        section = [b for b in blocks if b.get("block_id", "").startswith("en_business")][0]
        text = section["text"]["text"]
        self.assertIn("didn't reach SFDC Services", text)
        self.assertNotIn("DUPLICATE_VALUE:Duplicate external id", text)               # the raw error is not first

    def test_the_cards_run_from_business_to_developer(self):
        blocks, _, _ = self.blocks()
        cards = [b for b in blocks if b["type"] == "carousel"][0]["elements"]
        audiences = [c["subtitle"]["text"].split(" · ")[0] for c in cards]
        order = [ec.AUDIENCE[k] for k in ("business", "alert", "stats", "tech")]
        self.assertEqual(sorted(audiences, key=order.index), audiences)
        self.assertEqual(audiences[0], "For the business")
        self.assertEqual(audiences[-1], "For developers")
        self.assertLessEqual(len(cards), 10)

    def test_the_technical_cards_have_the_links(self):
        blocks, _, _ = self.blocks()
        cards = [b for b in blocks if b["type"] == "carousel"][0]["elements"]
        ids = [c for c in cards if "Where to look" in c["title"]["text"]][0]
        self.assertEqual([a["text"]["text"] for a in ids["actions"]], ["View job", "Open recipe"])
        self.assertTrue(all(a["action_id"].startswith(ec.LINK_PREFIX) for a in ids["actions"]))

    def test_no_card_is_empty_and_every_card_has_an_id(self):
        blocks, _, _ = self.blocks()
        for c in [b for b in blocks if b["type"] == "carousel"][0]["elements"]:
            self.assertTrue(c["body"]["text"].strip())
            self.assertTrue(c["block_id"])

    def test_the_failed_records_are_a_folded_table_with_page_navigation(self):
        blocks, _, _ = self.blocks()
        panel = [b for b in blocks if b["type"] == "container" and b["title"]["text"].startswith("Failed records")][0]
        table = [k for k in panel["child_blocks"] if k["type"] == "data_table"][0]
        self.assertEqual([c["text"] for c in table["rows"][0]], ["Application Id", "Application Primary Id", "Error Message"])
        self.assertEqual(len(table["rows"]), 5)

    def test_the_technical_panel_holds_the_details_and_the_full_error(self):
        blocks, _, _ = self.blocks()
        panel = [b for b in blocks if b["type"] == "container" and b["title"]["text"] == "Technical details"][0]
        text = all_text(panel)
        for needle in ("Full error message", "Error time", "Recipe ID", "70000001", "Systems", "Handling", "Notification",
                       "applications", "Application__c"):
            self.assertIn(needle, text, needle)

    def test_a_long_error_message_is_in_the_technical_panel_only(self):
        facts = notifier_facts(error_details="Boom: " + "x" * 6000, dataArray=[])
        facts["details"] = {"headline": "", "facts": [], "extra": []}
        blocks, _, _ = self.blocks(facts)
        text = all_text([b for b in blocks if b["type"] != "container"])
        self.assertNotIn("x" * 400, text)
        panel = [b for b in blocks if b["type"] == "container" and b["title"]["text"] == "Technical details"][0]
        self.assertIn("x" * 400, all_text(panel))
        pre = [e for b in walk(panel["child_blocks"]) if b["type"] == "rich_text" for e in b["elements"] if e["type"] == "rich_text_preformatted"]
        self.assertTrue(pre and len(pre[0]["elements"][0]["text"]) <= 2800)
        self.assertEqual(slack_problems(blocks), [])

    def test_the_card_texts_never_exceed_slacks_limits_even_with_huge_facts(self):
        facts = notifier_facts()
        facts["story"]["functional"] = facts["story"]["technical"] = "word " * 500
        facts["story"]["steps"] = ["step " * 100] * 6
        facts["signals"] = [{"icon": "💡", "text": "signal " * 80, "tone": "warn"}] * 8
        facts["details"]["facts"] = [["Label %d" % i, "value " * 50] for i in range(12)]
        blocks, _, _ = self.blocks(facts)
        self.assertEqual(slack_problems(blocks), [])

    def test_with_nothing_but_the_basics_there_are_few_cards(self):
        blocks, _, _ = self.blocks(ec.minimal_facts({"recipe_name": "R", "error_details": "boom", "priority": "High",
                                                      "job_url": "https://app.workato.com/recipes/1/job/j-1"}))
        self.assertEqual(slack_problems(blocks), [])
        self.assertLessEqual(len(blocks), 12)


class TestFeatures(PostCase):
    def kinds(self, **extra):
        blocks, _, _ = self.blocks(**extra)
        return {b["type"] for b in walk(blocks)}

    def test_what_is_off_by_default_can_be_added(self):
        facts = notifier_facts()
        facts["history"] = {"days": 90, "same": 3, "week_total": 2, "occurrence": 4, "trend": "rising", "reprocessed": 1, "failed_again": 1,
                            "first_seen": "Nov 1", "last_seen": "Nov 18", "top": [["Duplicate record", 5], ["Timeout", 2]],
                            "chart": [["Nov %d" % d, d % 3, d % 2] for d in range(1, 31)],
                            "recent": [{"when": "Nov 18", "status": "Notified", "job": "j-1"}]}
        blocks, _, _ = self.blocks(facts, slack_features="+charts,+tiles,+adaptive,+chips,+markdown")
        kinds = {b["type"] for b in walk(blocks)}
        for kind in ("data_visualization", "layout", "condition", "markdown"):
            self.assertIn(kind, kinds)
        chips = [b for b in blocks if b["type"] == "actions" and b["elements"][0]["action_id"].startswith(ec.INFO_PREFIX)]
        self.assertTrue(chips)
        for e in chips[0]["elements"]:
            self.assertNotIn("url", e)
            self.assertFalse(e["action_id"].startswith(ec.ACTION_PREFIX))
        self.assertEqual(slack_problems(blocks), [])

    def test_without_cards_the_same_words_come_as_sections(self):
        blocks, _, _ = self.blocks(slack_features="-cards")
        self.assertNotIn("carousel", {b["type"] for b in blocks})
        text = all_text(blocks)
        self.assertIn("For developers", text)
        self.assertIn("For the business", text)
        self.assertEqual(slack_problems(blocks), [])

    def test_without_panels_the_records_and_details_are_open(self):
        blocks, _, _ = self.blocks(slack_features="-panels")
        self.assertNotIn("container", {b["type"] for b in blocks})
        self.assertIn("data_table", {b["type"] for b in blocks})
        self.assertIn("Technical details", all_text(blocks))
        self.assertEqual(slack_problems(blocks), [])

    def test_the_table_degrades_to_the_native_table_then_text(self):
        kinds = self.kinds(slack_features="-datatables")
        self.assertIn("table", kinds)
        self.assertNotIn("data_table", kinds)
        blocks, _, _ = self.blocks(slack_features="-datatables,-tables")
        self.assertFalse({"table", "data_table"} & {b["type"] for b in walk(blocks)})
        self.assertIn("Application Id", all_text(blocks))

    def test_none_is_just_sections(self):
        blocks, _, _ = self.blocks(slack_features="none")
        self.assertTrue({"carousel", "container", "data_table", "table", "context_actions"}.isdisjoint({b["type"] for b in walk(blocks)}))
        self.assertNotIn("level", [b for b in blocks if b["type"] == "header"][0])
        self.assertEqual(slack_problems(blocks), [])

    def test_the_choice_grammar(self):
        U, D = ec.SLACK_FEATURES, ec.DEFAULT_FEATURES
        self.assertEqual(ec.slack_choice("", U, D), frozenset(D))
        self.assertEqual(ec.slack_choice("all", U, D), frozenset(U))
        self.assertEqual(ec.slack_choice("cards, panels", U, D), frozenset({"cards", "panels"}))
        self.assertEqual(ec.slack_choice("+charts -cards", U, D), (frozenset(D) | {"charts"}) - {"cards"})
        self.assertEqual(ec.slack_choice("all -charts", U, D), frozenset(U) - {"charts"})
        self.assertEqual(ec.slack_choice("none", U, D), frozenset())
        self.assertEqual(ec.slack_choice("nonsense", U, D), frozenset(D))

    def test_sl_section_defaults_to_expanded_so_slack_never_folds_it(self):
        self.assertIs(ec.sl_section("hello")["expand"], True)
        self.assertIs(ec.sl_section("hello", expand=False)["expand"], False)

    def test_the_old_look_is_one_plain_card_with_a_colour_bar(self):
        out, world = self.post(slack_look="old")
        sent = world.slack_calls("chat.postMessage")[0]
        self.assertNotIn("blocks", sent)
        card_ = sent["attachments"][0]
        self.assertEqual(card_["color"], "#EA580C")
        self.assertTrue({"layout", "container", "carousel", "card", "data_table", "data_visualization", "markdown", "header",
                         "condition", "rich_text", "context_actions"}.isdisjoint({b["type"] for b in walk(card_["blocks"])}))
        self.assertEqual(slack_problems(card_["blocks"]), [])
        self.assertEqual(out["look_used"], "old")
        self.assertIn(ec.STATUS_BLOCK_ID, [b.get("block_id") for b in card_["blocks"]])
        self.assertIn("Application Id", all_text(card_["blocks"]))

    def test_fit_blocks_drops_the_least_important_and_keeps_dividers_tidy(self):
        items = [(0, {"type": "section", "text": {"type": "mrkdwn", "text": "keep"}})] + \
                [(7, {"type": "section", "text": {"type": "mrkdwn", "text": "drop"}}) for _ in range(60)]
        kept = ec.fit_blocks(items)
        self.assertEqual((len(kept), kept[0]["text"]["text"]), (50, "keep"))
        div, sec = (9, {"type": "divider"}), (0, {"type": "section", "text": {"type": "mrkdwn", "text": "a"}})
        self.assertEqual([b["type"] for b in ec.fit_blocks([div, sec, div, div, sec, div])], ["section", "divider", "section"])


class TestFallback(PostCase):
    """Slack names the block it refused in an invalid_blocks answer: that feature goes, the rest stays."""

    @staticmethod
    def refuse_type(*kinds):
        def refuse(payload):
            blocks = payload.get("blocks") or []
            hits = ["unsupported type: {} [json-pointer:/blocks/{}/type]".format(b["type"], i) for i, b in enumerate(blocks) if b["type"] in kinds]
            return hits[:1]
        return refuse

    def test_a_refused_carousel_becomes_sections(self):
        out, world = self.post(world=World(stored=stored_row(), refuse=self.refuse_type("carousel")))
        posts = world.slack_calls("chat.postMessage")
        self.assertEqual(len(posts), 2)
        self.assertEqual(out["look_used"], "new (without cards)")
        self.assertNotIn("carousel", [b["type"] for b in posts[1]["blocks"]])
        self.assertIn("For developers", all_text(posts[1]["blocks"]))
        self.assertTrue(any("refused cards" in w for w in out["warnings"]))

    def test_a_refused_container_that_holds_the_table_keeps_the_table(self):
        def refuse(payload):
            blocks = payload.get("blocks") or []
            return ["bad [json-pointer:/blocks/{}/child_blocks/0/type]".format(i) for i, b in enumerate(blocks) if b["type"] == "container"][:1]
        out, world = self.post(world=World(stored=stored_row(), refuse=refuse))
        last = world.slack_calls("chat.postMessage")[-1]["blocks"]
        self.assertNotIn("container", [b["type"] for b in last])
        self.assertIn("data_table", [b["type"] for b in last])
        self.assertIn("carousel", [b["type"] for b in last])                          # the rest of the new look stayed

    def test_each_refusal_costs_one_feature(self):
        out, world = self.post(world=World(stored=stored_row(), refuse=self.refuse_type("data_table", "carousel")))
        self.assertTrue(out["posted"])
        self.assertLessEqual(len(world.slack_calls("chat.postMessage")), 4)
        self.assertIn("without", out["look_used"])

    def test_a_refusal_that_names_no_block_peels_the_likeliest_feature(self):
        state = {"n": 0}

        def refuse(payload):
            state["n"] += 1
            return ["something odd"] if state["n"] == 1 else None
        out, world = self.post(world=World(stored=stored_row(), refuse=refuse))
        self.assertEqual(len(world.slack_calls("chat.postMessage")), 2)
        self.assertEqual(out["look_used"], "new (without datatables)")

    def test_when_nothing_new_is_accepted_the_plain_card_goes(self):
        def refuse(payload):
            return ["bad [json-pointer:/blocks/0/type]"] if "blocks" in payload else None
        out, world = self.post(world=World(stored=stored_row(), refuse=refuse))
        self.assertEqual(out["look_used"], "old")
        self.assertIn("attachments", world.slack_calls("chat.postMessage")[-1])
        self.assertTrue(out["posted"])

    def test_when_even_the_card_is_refused_text_goes(self):
        def refuse(payload):
            return None if set(payload) <= {"channel", "unfurl_links", "unfurl_media", "text", "thread_ts"} else ["bad"]
        out, world = self.post(world=World(stored=stored_row(), refuse=refuse))
        self.assertEqual(out["look_used"], "text")
        self.assertNotIn("blocks", world.slack_calls("chat.postMessage")[-1])

    def test_the_warning_carries_slacks_own_words(self):
        out, _ = self.post(world=World(stored=stored_row(), refuse=lambda p: ["unsupported type: x [json-pointer:/blocks/99/type]"]))
        self.assertTrue(any("json-pointer" in w for w in out["warnings"]))


class TestPostButtons(PostCase):
    def elements(self, **extra):
        blocks, _, _ = self.blocks(**extra)
        return [e for b in blocks if b["type"] == "actions" for e in b["elements"]]

    def test_every_button_that_does_something_starts_with_the_one_prefix(self):
        for e in self.elements():
            if e["action_id"].startswith(ec.INFO_PREFIX):
                continue
            if "url" in e:
                self.assertTrue(e["action_id"].startswith(ec.LINK_PREFIX), e["action_id"])
            else:
                self.assertTrue(e["action_id"].startswith("error_notification_"), e["action_id"])
                self.assertIn(e["action_id"], ec.ACTIONS)

    def test_reprocess_asks_for_confirmation_and_carries_the_job(self):
        button = [e for e in self.elements() if e["action_id"] == ec.ACT_REPROCESS][0]
        self.assertEqual(button["confirm"]["confirm"]["text"], "Yes, reprocess")
        self.assertIn(MASTER, button["confirm"]["text"]["text"])
        value = json.loads(button["value"])
        self.assertEqual((value["v"], value["m"], value["r"]), (1, MASTER, RECIPE))
        self.assertLessEqual(len(button["value"]), 2000)

    def test_the_value_the_post_builds_is_what_the_click_reads(self):
        button = [e for e in self.elements() if e["action_id"] == ec.ACT_REPROCESS][0]
        job = ec.job_context(ec.parse_click({"payload": json.dumps(payload(value=button["value"]))}))
        self.assertEqual((job["master"], job["recipe_id"]), (MASTER, RECIPE))

    def test_a_message_the_post_built_can_be_clicked_and_updated(self):
        blocks, _, _ = self.blocks()
        button = [e for b in blocks if b["type"] == "actions" for e in b["elements"] if e["action_id"] == ec.ACT_REPROCESS][0]
        actions_block = [b for b in blocks if b["type"] == "actions" and b["block_id"].startswith(ec.ACTIONS_BLOCK_ID)][0]
        pl = payload(action_id=ec.ACT_REPROCESS, value=button["value"], blocks=blocks, block_id=actions_block["block_id"])
        out, world = self.click_with(pl)
        self.assertEqual((out["ok"], out["reprocess_enqueued"], out["message_updated"]), (True, True, True))
        update = world.slack_calls("chat.update")[0]
        self.assertIn("Reprocess queued", all_text([b for b in update["blocks"] if b.get("block_id") == ec.STATUS_BLOCK_ID]))
        remaining = action_ids(update["blocks"])
        self.assertNotIn(ec.ACT_REPROCESS, remaining)
        self.assertIn(ec.ACT_ACK, remaining)                                        # Take it, on the status line

    def click_with(self, pl):
        world = World(stored=stored_row())
        original = ec.http_json
        ec.http_json = world
        try:
            return ec.main({"payload": json.dumps(pl), "workato_api_token": "wt", "slack_bot_token": "xoxb-t", "now": NOW}), world
        finally:
            ec.http_json = original

    def test_the_status_block_and_the_actions_block_have_stable_ids(self):
        blocks, _, _ = self.blocks()
        ids = [b.get("block_id") for b in blocks]
        self.assertIn(ec.STATUS_BLOCK_ID, ids)
        self.assertIn("{}|{}|{}".format(ec.ACTIONS_BLOCK_ID, MASTER, RECIPE), ids)

    def test_buttons_can_be_switched_off_one_by_one_or_all(self):
        ids = set(action_ids(self.blocks(slack_buttons="-reprocess")[0]))
        self.assertNotIn(ec.ACT_REPROCESS, ids)
        self.assertIn(ec.ACT_ACK, ids)
        ids = {e["action_id"] for e in self.elements(slack_buttons="none")}
        self.assertFalse([i for i in ids if i.startswith("error_notification_")])
        self.assertTrue([i for i in ids if i.startswith(ec.LINK_PREFIX)])

    def test_a_retry_already_queued_has_no_reprocess_button(self):
        facts = notifier_facts()
        facts["repeat"] = dict(facts["repeat"], attempted=True, enqueued=True, job_id="j-9")
        ids = set(action_ids(self.blocks(facts)[0]))
        self.assertNotIn(ec.ACT_REPROCESS, ids)
        self.assertIn(ec.ACT_ACK, ids)

    def test_a_good_analysis_makes_reprocess_the_primary_button(self):
        facts = notifier_facts()
        facts["decision"] = {"reprocessable": True, "source": "ai", "confidence": "high", "reason": "x"}
        button = [e for e in self.elements(facts=facts) if e["action_id"] == ec.ACT_REPROCESS][0]
        self.assertEqual(button.get("style"), "primary")
        self.assertIn("should work", button["confirm"]["text"]["text"])

    def test_the_link_buttons_come_first_and_view_job_is_primary(self):
        links = [e for e in self.elements() if e.get("url")]
        self.assertEqual([e["text"]["text"] for e in links][:3], ["View job", "Open recipe", "Error file"])
        self.assertEqual(links[0]["style"], "primary")

    def test_no_job_means_no_buttons_that_need_one(self):
        facts = notifier_facts()
        facts["master"] = facts["job_handle"] = facts["recipe_id"] = ""
        ids = {e["action_id"] for e in self.elements(facts=facts)}
        self.assertFalse([i for i in ids if i.startswith("error_notification_")])

    def test_feedback_buttons_only_after_an_ai_explanation(self):
        self.assertNotIn("context_actions", {b["type"] for b in self.blocks()[0]})
        facts = notifier_facts()
        facts["story"]["source"] = "ai"
        feedback = [b for b in self.blocks(facts)[0] if b["type"] == "context_actions"][0]
        self.assertEqual(feedback["elements"][0]["action_id"], ec.ACT_FEEDBACK)


class TestPostShowsEveryInput(PostCase):
    """The point of a custom alert: what the caller passes is shown, not dropped."""

    def text(self, facts=None, **extra):
        blocks, _, world = self.blocks(facts, **extra)
        return all_text(blocks) + world.slack_calls("chat.postMessage")[0]["text"]

    def test_the_inputs_appear(self):
        facts = notifier_facts(mail_msg="Please look at this before the 9am sync", to_email_address="data.team@example.com",
                               error_file_path="/Error_Files/x.csv", error_file_expires_in=604800, file_name="applications.csv",
                               file_content="id,name\n1,Ada\n", retry_count=2, subject="Custom subject here", stepNumber="12",
                               ErroredApp="salesforce", ErroredAction="upsert_sobject")
        text = self.text(facts)
        for needle in ("Salesforce - AWS S3 UOL Application files Process - Function", "Please look at this before the 9am sync",
                       "Total Records", "35,909", "SFDC Services", "Amazon S3", "UOL Application files", "Application__c",
                       "Application Primary Id", "DUPLICATE_VALUE", "/Error_Files/x.csv", "applications.csv", "id,name",
                       "Custom subject here", "High", "https://example.com/error-file.csv", "upsert_sobject", "12",
                       "j-TestJob1-abcdef-CD", "70000001", "Production"):
            self.assertIn(needle, text, needle)

    def test_a_cells_link_bold_and_colour_are_kept(self):
        facts = notifier_facts(column1Name="Name", column2Name="Status", column3Name="", dataArray=[
            {"value1": "Ada", "url1": "https://crm.example/ada", "column1_bold": "Yes", "value2": "Failed", "column2_color": "#ff6347"}])
        blocks, _, _ = self.blocks(facts)
        table = [k for b in blocks if b["type"] == "container" for k in b["child_blocks"] if k["type"] == "data_table"][0]
        first, second = table["rows"][1]
        link = first["elements"][0]["elements"][0]
        self.assertEqual((link["type"], link["url"], link["text"], link["style"]), ("link", "https://crm.example/ada", "Ada", {"bold": True}))
        self.assertIn("🔴", all_text(second))

    def test_numeric_columns_are_numbers_so_the_table_can_sort_them(self):
        facts = notifier_facts(column1Name="Row", column2Name="Qty", column3Name="", dataArray=[{"value1": "a", "value2": "10"}, {"value1": "b", "value2": "2"}])
        blocks, _, _ = self.blocks(facts)
        table = [k for b in blocks if b["type"] == "container" for k in b["child_blocks"] if k["type"] == "data_table"][0]
        self.assertEqual(table["rows"][1][1], {"type": "raw_number", "value": 10, "text": "10"})
        self.assertEqual(table["rows"][1][0]["type"], "raw_text")

    def test_emails_are_masked_by_default_and_can_be_shown(self):
        facts = notifier_facts(error_details="Could not email jane.doe@example.com", to_email_address="data.team@example.com",
                               dataArray=[{"value1": "x@learner.org", "value2": "y", "value3": "BAD_THING:z"}], file_content="mail me at q@r.io")
        text = self.text(facts)
        for address in ("jane.doe@example.com", "x@learner.org", "q@r.io", "data.team@example.com"):
            self.assertNotIn(address, text)
        self.assertIn("•••@example.com", text)
        self.assertIn("jane.doe@example.com", self.text(facts, slack_mask_pii="no"))

    def test_mrkdwn_is_escaped(self):
        facts = notifier_facts()
        facts["recipe_name"] = "A <b>&</b> recipe"
        button = [e for b in self.blocks(facts)[0] if b["type"] == "actions" for e in b["elements"] if e["action_id"] == ec.ACT_REPROCESS][0]
        self.assertIn("A &lt;b&gt;&amp;&lt;/b&gt; recipe", button["confirm"]["text"]["text"])
        self.assertEqual(ec.sx("<@U1> & <!here>"), "&lt;@U1&gt; &amp; &lt;!here&gt;")

    def test_a_big_table_stays_within_slacks_character_limit(self):
        rows = [{"value1": "id{}".format(i), "value2": "v" * 270, "value3": "E_RROR:" + "m" * 270} for i in range(100)]
        blocks, _, _ = self.blocks(notifier_facts(dataArray=rows), max_table_rows=500)
        self.assertEqual(slack_problems(blocks), [])
        table = [k for b in blocks if b["type"] == "container" for k in b["child_blocks"] if k["type"] == "data_table"][0]
        self.assertLess(len(table["rows"]), 101)
        self.assertIn("Showing the first", all_text(blocks))


class TestContract(PostCase):
    """What the notifier hands over is what this step reads."""

    def test_the_facts_have_what_the_step_reads(self):
        facts = notifier_facts()
        for key in ("recipe_name", "recipe_id", "job_url", "master", "sev", "category", "headline", "details", "error_plain", "rows", "cols",
                    "rec", "retry", "decision", "repeat", "story", "tiles", "signals", "links", "team", "send_email", "deferred", "subject",
                    "signature", "error_time", "now_text", "version"):
            self.assertIn(key, facts, key)
        self.assertEqual(sorted(facts["sev"]), ["color", "emoji", "label"])
        self.assertEqual(sorted(facts["retry"]), ["detail", "head", "icon", "state"])
        self.assertEqual(len(facts["rows"][0]), 5)
        self.assertEqual(sorted(facts["rows"][0][0]), ["bold", "color", "url", "value"])

    def test_the_facts_are_plain_json(self):
        json.dumps(notifier_facts())

    def test_a_deferred_call_has_no_facts_so_nothing_is_posted(self):
        sys.path.insert(0, NOTIFIER)
        import error_notification as en
        with open(os.path.join(NOTIFIER, "testdata", "sample_input.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        out = en.main(dict(data, ai="no", frequency=7))
        self.assertEqual(out["alert_json"], "")
        post_out, world = self.post(alert_json=out["alert_json"], recipe_name="x")
        self.assertEqual(post_out["alert_source"], "inputs")                           # (the recipe only calls this step for an email)



class TestShortLook(PostCase):
    """The default: short, business only, a 2 x 2 grid of boxes with their buttons -- never a carousel. Nobody should have to scroll."""

    def short(self, facts=None, **extra):
        return self.blocks(facts, slack_look="new", **extra)

    def test_it_is_short_and_within_slacks_limits(self):
        blocks, out, _ = self.short()
        self.assertLessEqual(len(blocks), 8)
        self.assertEqual([b["type"] for b in blocks],
                         ["header", "section", "rich_text", "section", "layout", "data_table", "context", "context"])
        self.assertEqual(slack_problems(blocks), [])
        self.assertEqual(out["look_used"], "new")

    def test_the_error_is_outside_the_cards_in_a_code_block(self):
        blocks, _, _ = self.short()
        error = blocks[2]
        self.assertEqual(error["type"], "rich_text")
        label, code = error["elements"]
        self.assertEqual(code["type"], "rich_text_preformatted")
        self.assertIn("Error", all_text(label))
        text = code["elements"][0]["text"]
        self.assertTrue(text.startswith("Error Occred while processing UOL Application records"))
        self.assertRegex(text, r"\nTotal Records +: 35,909\n")                      # one fact a line, the labels lined up
        self.assertRegex(text, r"\nRecords Failed +: 4\n")
        cards = all_text([b for b in blocks if b["type"] == "carousel"])
        self.assertNotIn("Total Records", cards)

    def test_an_error_without_facts_is_shown_as_it_is(self):
        facts = notifier_facts(error_details="Salesforce connection is broken. Please refresh", dataArray=[])
        blocks, _, _ = self.short(facts)
        code = [b for b in blocks if b.get("block_id", "").startswith("en_error")][0]["elements"][1]
        self.assertEqual(code["elements"][0]["text"], "Salesforce connection is broken. Please refresh")

    def test_without_rich_text_the_error_is_a_code_fence(self):
        blocks, _, _ = self.short(slack_features="-rich")
        self.assertIn("```", blocks[2]["text"]["text"])
        self.assertIn("🚨 *Error*", blocks[2]["text"]["text"])

    def test_a_long_error_is_cut(self):
        blocks, _, _ = self.short(notifier_facts(error_details="Boom " + "x" * 5000, dataArray=[]))
        code = blocks[2]["elements"][1]["elements"][0]["text"]
        self.assertLessEqual(len(code), 900)
        self.assertEqual(slack_problems(blocks), [])

    def test_it_sits_in_one_red_attachment_with_no_text_above_it(self):
        _, world = self.post(slack_look="new")
        sent = world.slack_calls("chat.postMessage")[0]
        self.assertNotIn("blocks", sent)
        self.assertNotIn("text", sent)                                               # Slack would show it above the card
        self.assertEqual(len(sent["attachments"]), 1)
        self.assertEqual(sent["attachments"][0]["color"], ec.BAR_COLOR)
        self.assertIn("Failure in Salesforce", sent["attachments"][0]["fallback"])     # what a notification shows

    def test_without_the_bar_the_blocks_are_at_the_top_level(self):
        _, world = self.post(slack_look="new", slack_features="-bar")
        sent = world.slack_calls("chat.postMessage")[0]
        self.assertTrue(sent["blocks"] and sent["text"])
        self.assertNotIn("attachments", sent)

    def test_the_grid_is_two_by_two_small_boxes(self):
        blocks, _, _ = self.short()
        grid = [b for b in blocks if b["type"] == "layout"][0]
        titles = [[i["block"]["title"]["text"] for i in row["items"]] for row in grid["rows"]]
        self.assertEqual(titles, [["📣 What happened", "📉 Impact"], ["✅ What to do next", "🔗 Open"]])
        boxes = [i["block"] for row in grid["rows"] for i in row["items"]]
        self.assertTrue(all(b["type"] == "container" for b in boxes))
        self.assertTrue(all(len(k["text"]["text"]) <= 200 for b in boxes for k in b["child_blocks"] if k["type"] == "section"))
        self.assertIn("didn't reach SFDC Services", all_text(boxes[1]))

    def test_a_box_body_is_rich_text_so_slack_never_folds_it_behind_show_more(self):
        # a section's text folds behind "Show more" inside a container even with expand: true (confirmed live); rich_text does not
        blocks, _, _ = self.short()
        boxes = [i["block"] for b in blocks if b["type"] == "layout" for row in b["rows"] for i in row["items"]]
        bodies = [k for b in boxes for k in b["child_blocks"] if "_text_" in k["block_id"]]
        self.assertTrue(bodies)
        self.assertTrue(all(k["type"] == "rich_text" for k in bodies), bodies)
        self.assertIn("didn't reach SFDC Services", all_text(bodies))
        self.assertIn("Check the source for repeated keys", all_text(bodies))
        # no mrkdwn escaping leaks into a rich_text element: it takes the display string as is, unlike a section's text
        facts = notifier_facts()
        facts["recipe_name"] = facts["story"]["functional"] = "A <b>&</b> recipe"
        blocks, _, _ = self.short(facts)
        boxes = [i["block"] for b in blocks if b["type"] == "layout" for row in b["rows"] for i in row["items"]]
        body = [k for b in boxes for k in b["child_blocks"] if k["block_id"] == "en_what_text_1"][0]
        self.assertEqual(body["elements"][0]["elements"][0]["text"], "A <b>&</b> recipe")

    def test_without_rich_a_box_body_falls_back_to_an_expanded_section(self):
        blocks, _, _ = self.short(slack_features="-rich")
        boxes = [i["block"] for b in blocks if b["type"] == "layout" for row in b["rows"] for i in row["items"]]
        bodies = [k for b in boxes for k in b["child_blocks"] if "_text_" in k["block_id"]]
        self.assertTrue(bodies)
        self.assertTrue(all(k["type"] == "section" and k["expand"] is True for k in bodies), bodies)

    def test_no_section_anywhere_is_folded_behind_show_more(self):
        # Slack collapses a section's text unless expand is on; every section this step builds is meant to be read in full
        for variant in (self.short(), self.short(slack_features="-grid")):
            blocks, _, _ = variant
            sections = [b for b in walk(blocks) if b.get("type") == "section" and "text" in b]
            self.assertTrue(sections)
            self.assertTrue(all(b.get("expand") is True for b in sections), sections)

    def test_without_the_grid_the_same_come_as_plain_sections_never_a_carousel(self):
        blocks, _, _ = self.short(slack_features="-grid")
        self.assertNotIn("layout", [b["type"] for b in blocks])
        self.assertTrue({"carousel", "container"}.isdisjoint({b["type"] for b in walk(blocks)}))
        text = all_text(blocks)
        for title in ("What happened", "Impact", "What to do next"):
            self.assertIn(title, text, title)

    def test_blank_look_is_the_short_one(self):
        blocks, _, _ = self.blocks(slack_look="")
        self.assertIn("layout", [b["type"] for b in blocks])
        self.assertNotIn("container", [b["type"] for b in blocks])

    def test_three_sections_in_business_order(self):
        blocks, _, _ = self.short(slack_features="-grid")
        sections = [b for b in blocks if b["type"] == "section" and "*" in b["text"]["text"]][-3:]
        self.assertEqual([re.search(r"\*(.+?)\*", b["text"]["text"]).group(1) for b in sections],
                         ["What happened", "Impact", "What to do next"])
        self.assertIn("didn't reach SFDC Services", sections[1]["text"]["text"])

    def test_nothing_technical(self):
        blocks, _, _ = self.short()
        text = all_text(blocks)
        for word in ("Technical details", "Recipe ID", "Full error", "Under the hood", "DUPLICATE_VALUE:Duplicate external id"):
            self.assertNotIn(word, text, word)
        self.assertTrue({"table", "context_actions", "carousel"}.isdisjoint({b["type"] for b in walk(blocks)}))

    def test_the_failed_records_are_the_paged_table_under_the_cards(self):
        blocks, _, _ = self.short()
        kinds = [b["type"] for b in blocks]
        self.assertLess(kinds.index("layout"), kinds.index("data_table"))
        table = blocks[kinds.index("data_table")]
        self.assertEqual([c["text"] for c in table["rows"][0]], ["Application Id", "Application Primary Id", "Error Message"])
        self.assertEqual(len(table["rows"]), 5)
        blocks, _, _ = self.short(slack_features="-datatables")
        self.assertIn("table", [b["type"] for b in blocks])
        blocks, _, _ = self.short(slack_features="-datatables,-tables")
        self.assertFalse({"table", "data_table"} & {b["type"] for b in blocks})

    def test_no_records_no_table(self):
        blocks, _, _ = self.short(notifier_facts(dataArray=[]))
        self.assertNotIn("data_table", [b["type"] for b in blocks])

    def test_the_preview_file_is_blocks_only(self):
        with open(os.path.join(HERE, "testdata", "slack_preview.json"), encoding="utf-8") as handle:
            self.assertEqual(list(json.load(handle)), ["blocks"])               # Block Kit Builder refuses anything else

    def test_the_buttons_sit_in_the_boxes(self):
        blocks, _, _ = self.short()
        boxes = {i["block"]["title"]["text"]: i["block"] for b in blocks if b["type"] == "layout" for r in b["rows"] for i in r["items"]}
        nxt = [k for k in boxes["✅ What to do next"]["child_blocks"] if k["type"] == "actions"][0]
        self.assertEqual(nxt["block_id"], "{}|{}|{}".format(ec.ACTIONS_BLOCK_ID, MASTER, RECIPE))
        self.assertEqual([e["action_id"] for e in nxt["elements"]], [ec.ACT_REPROCESS, ec.ACT_RESOLVE])
        self.assertEqual(nxt["elements"][0]["confirm"]["confirm"]["text"], "Yes, reprocess")
        opened = [k for k in boxes["🔗 Open"]["child_blocks"] if k["type"] == "actions"][0]
        self.assertEqual([e["text"]["text"] for e in opened["elements"]], ["View job", "Error file", "Open recipe"])
        self.assertTrue(all(e["action_id"].startswith(ec.LINK_PREFIX) for e in opened["elements"]))

    def test_without_the_grid_the_buttons_are_one_row(self):
        blocks, _, _ = self.short(slack_features="-grid")
        rows = [b for b in blocks if b["type"] == "actions"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["block_id"], "{}|{}|{}".format(ec.ACTIONS_BLOCK_ID, MASTER, RECIPE))
        labels_and_ids = [(e["text"]["text"], e.get("action_id")) for e in row["elements"]]
        self.assertIn("View job", [label for label, _ in labels_and_ids])
        self.assertIn(ec.ACT_REPROCESS, [action_id for _, action_id in labels_and_ids])
        self.assertIn(ec.ACT_RESOLVE, [action_id for _, action_id in labels_and_ids])
        reprocess = next(e for e in row["elements"] if e["action_id"] == ec.ACT_REPROCESS)
        self.assertEqual(reprocess["confirm"]["confirm"]["text"], "Yes, reprocess")

    def test_a_click_in_a_grid_box_works_and_takes_the_button_away(self):
        blocks, _, _ = self.short()
        grid = [b for b in blocks if b["type"] == "layout"][0]
        nxt = [k for i in grid["rows"][1]["items"] for k in i["block"]["child_blocks"] if k.get("block_id", "").startswith(ec.ACTIONS_BLOCK_ID)][0]
        button = nxt["elements"][0]
        message = {"attachments": [{"color": ec.BAR_COLOR, "blocks": blocks}]}
        pl = payload(action_id=ec.ACT_REPROCESS, value=button["value"], attachments=message["attachments"], block_id=nxt["block_id"])
        world = World(stored=stored_row())
        original = ec.http_json
        ec.http_json = world
        try:
            out = ec.main({"payload": json.dumps(pl), "workato_api_token": "wt", "slack_bot_token": "xoxb-t", "now": NOW})
        finally:
            ec.http_json = original
        self.assertEqual((out["ok"], out["reprocess_enqueued"], out["message_updated"]), (True, True, True))
        update = world.slack_calls("chat.update")[0]
        self.assertEqual(update["attachments"][0]["color"], ec.BAR_COLOR)          # the red bar stays
        left = action_ids(update["attachments"][0]["blocks"])
        self.assertNotIn(ec.ACT_REPROCESS, left)
        self.assertIn(ec.ACT_RESOLVE, left)
        self.assertIn("Reprocess queued", all_text([b for b in update["attachments"][0]["blocks"] if b.get("block_id") == ec.STATUS_BLOCK_ID]))

    def test_a_click_finds_the_job_in_a_grid_box_without_a_value(self):
        blocks, _, _ = self.short()
        click = ec.parse_click({"payload": json.dumps(payload(action_id=ec.ACT_ACK, value="", block_id="x",
                                                              attachments=[{"blocks": blocks}]))})
        self.assertEqual(ec.job_context(click)["master"], MASTER)

    def test_a_click_on_the_button_row_works_and_takes_the_button_away(self):
        blocks, _, _ = self.short(slack_features="-grid")
        row = [b for b in blocks if b["type"] == "actions"][0]
        button = next(e for e in row["elements"] if e["action_id"] == ec.ACT_REPROCESS)
        pl = payload(action_id=ec.ACT_REPROCESS, value=button["value"], blocks=blocks, block_id=row["block_id"])
        world = World(stored=stored_row())
        original = ec.http_json
        ec.http_json = world
        try:
            out = ec.main({"payload": json.dumps(pl), "workato_api_token": "wt", "slack_bot_token": "xoxb-t", "now": NOW})
        finally:
            ec.http_json = original
        self.assertEqual((out["ok"], out["reprocess_enqueued"], out["message_updated"]), (True, True, True))
        update = world.slack_calls("chat.update")[0]
        left = action_ids(update["blocks"])
        self.assertNotIn(ec.ACT_REPROCESS, left)
        self.assertIn(ec.ACT_RESOLVE, left)
        self.assertIn(ec.ACT_ACK, left)                                             # nobody has taken it yet
        self.assertIn("Reprocess queued", all_text([b for b in update["blocks"] if b.get("block_id") == ec.STATUS_BLOCK_ID]))

    def test_the_status_line_has_a_take_it_button(self):
        blocks, _, _ = self.short()
        status = [b for b in blocks if b.get("block_id") == ec.STATUS_BLOCK_ID][0]
        self.assertEqual(status["type"], "section")
        self.assertIn("Open", status["text"]["text"])
        button = status["accessory"]
        self.assertEqual((button["text"]["text"], button["action_id"]), ("🙋 Take it", ec.ACT_ACK))
        self.assertEqual(json.loads(button["value"])["m"], MASTER)
        self.assertEqual(action_ids(blocks).count(ec.ACT_ACK), 1)                     # only there

    def test_taking_it_shows_who_and_takes_the_button_away(self):
        blocks, _, _ = self.short()
        status = [b for b in blocks if b.get("block_id") == ec.STATUS_BLOCK_ID][0]
        pl = payload(action_id=ec.ACT_ACK, value=status["accessory"]["value"], blocks=blocks, block_id=ec.STATUS_BLOCK_ID)
        world = World(stored=stored_row())
        original = ec.http_json
        ec.http_json = world
        try:
            out = ec.main({"payload": json.dumps(pl), "workato_api_token": "wt", "slack_bot_token": "xoxb-t", "now": NOW})
        finally:
            ec.http_json = original
        self.assertEqual((out["ok"], out["action"], out["result"]), (True, "acknowledge", "Taken by Ada Lovelace"))
        update = world.slack_calls("chat.update")[0]
        new = [b for b in update["blocks"] if b.get("block_id") == ec.STATUS_BLOCK_ID][0]
        self.assertEqual(new["type"], "section")
        self.assertTrue(new["text"]["text"].startswith("🙋 <@U0ADA0001> *is looking into it*"))
        self.assertNotIn("Open", new["text"]["text"])
        self.assertNotIn("accessory", new)                                         # nobody takes it twice
        self.assertIn(ec.ACT_REPROCESS, action_ids(update["blocks"]))               # the rest stays
        self.assertEqual(world.stored["rec-1"]["Acknowledged By"], "Ada Lovelace")

    def test_without_a_job_the_status_is_a_plain_line(self):
        facts = notifier_facts()
        facts["master"] = facts["job_handle"] = facts["recipe_id"] = ""
        blocks, _, _ = self.short(facts)
        status = [b for b in blocks if b.get("block_id") == ec.STATUS_BLOCK_ID][0]
        self.assertEqual(status["type"], "context")

    def test_the_plain_card_has_take_it_too(self):
        _, world = self.post(slack_look="old")
        card = world.slack_calls("chat.postMessage")[0]["attachments"][0]
        status = [b for b in card["blocks"] if b.get("block_id") == ec.STATUS_BLOCK_ID][0]
        self.assertEqual(status["accessory"]["action_id"], ec.ACT_ACK)

    def test_a_click_without_a_value_finds_the_job_in_the_card(self):
        blocks, _, _ = self.short(slack_features="-grid")
        click = ec.parse_click({"payload": json.dumps(payload(action_id=ec.ACT_ACK, value="", blocks=blocks, block_id="x"))})
        self.assertEqual(ec.job_context(click)["master"], MASTER)

    def test_a_retry_already_queued_has_no_reprocess_button(self):
        facts = notifier_facts()
        facts["repeat"] = dict(facts["repeat"], attempted=True, enqueued=True)
        blocks, _, _ = self.short(facts)
        ids = action_ids(blocks)
        self.assertNotIn(ec.ACT_REPROCESS, ids)
        self.assertIn(ec.ACT_ACK, ids)

    def test_without_buttons_the_row_is_links_only(self):
        blocks, _, _ = self.short(slack_buttons="none", slack_features="-grid")
        rows = [b for b in blocks if b["type"] == "actions"]
        self.assertEqual(len(rows), 1)
        self.assertTrue(all("url" in e for e in rows[0]["elements"]))
        self.assertFalse([e for e in rows[0]["elements"] if e["action_id"].startswith(ec.ACTION_PREFIX)])

    def test_a_refused_grid_goes_straight_to_plain_sections_in_one_retry_keeping_the_bar(self):
        # there is no carousel stage left to fall back to in between: a refused grid goes straight to sections
        def refuse(p):
            return ["unsupported type: layout [json-pointer:/attachments/0/blocks/{}/type]".format(i)
                    for i, b in enumerate(sent_blocks(p)) if b["type"] == "layout"][:1]
        out, world = self.post(world=World(stored=stored_row(), refuse=refuse), slack_look="new")
        posts = world.slack_calls("chat.postMessage")
        self.assertEqual(len(posts), 2)                                          # one refusal, one retry: no carousel in between
        last = sent_blocks(posts[-1])
        self.assertEqual(out["look_used"], "new (without grid)")
        self.assertTrue({"layout", "carousel", "container"}.isdisjoint({b["type"] for b in last}))
        self.assertIn("attachments", posts[-1])
        row = [b for b in last if b["type"] == "actions"][0]
        self.assertTrue(row["block_id"].startswith(ec.ACTIONS_BLOCK_ID))
        self.assertIn(ec.ACT_REPROCESS, [e["action_id"] for e in row["elements"]])
        self.assertLessEqual(len(last), 11)                                      # headline, error, status, three sections, the button row, the table, two context lines
        self.assertEqual(slack_problems(last), [])

    def test_emails_are_masked_and_the_mention_is_kept(self):
        facts = notifier_facts(error_details="Could not email jane.doe@example.com")
        facts["headline"] = "Could not email jane.doe@example.com"
        blocks, _, _ = self.short(facts, slack_mention="<!subteam^S01>")
        text = all_text(blocks)
        self.assertNotIn("jane.doe@example.com", text)
        self.assertIn("<!subteam^S01>", text)

    def test_huge_texts_still_fit(self):
        facts = notifier_facts()
        facts["story"]["functional"] = "word " * 400
        facts["story"]["steps"] = ["step " * 80] * 5
        facts["headline"] = "h" * 900
        blocks, _, _ = self.short(facts)
        self.assertEqual(slack_problems(blocks), [])

    def test_a_short_alert_from_the_inputs_alone(self):
        blocks, _, _ = self.short(ec.minimal_facts({"recipe_name": "R", "error_details": "boom", "priority": "Critical",
                                                    "job_url": "https://app.workato.com/recipes/1/job/j-1"}))
        self.assertEqual(slack_problems(blocks), [])
        self.assertIn("Critical", all_text(blocks))


class TestSchemas(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8") as handle:
            return json.load(handle)

    def test_input_schema(self):
        self.assertEqual([f["name"] for f in self.load("error_slack_input_schema.json")], list(ec.INPUT_NAMES))

    def test_output_schema(self):
        names = [f["name"] for f in self.load("error_slack_output_schema.json")]
        self.assertEqual(names, [k for k, _ in ec.OUTPUT_DEFAULTS])
        out = ec.main({})
        self.assertEqual(set(out), set(names))

    def test_the_sample_payload_runs(self):
        with open(os.path.join(HERE, "testdata", "click_reprocess.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        world = World(stored=stored_row())
        original = ec.http_json
        ec.http_json = world
        try:
            out = ec.main(dict(data, workato_api_token="t", slack_bot_token="s", now=NOW))
        finally:
            ec.http_json = original
        self.assertEqual((out["ok"], out["action"], out["reprocess_enqueued"]), (True, "reprocess", True))


if __name__ == "__main__":
    unittest.main()
