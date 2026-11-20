"""
Tests for error_notification.py. Run them before and after any change:

    python3 test_error_notification.py            # all of them
    python3 test_error_notification.py -v         # with the name of each

Nothing here touches the network: http_json is replaced by a fake that answers like the
data table, the Workato API and Azure, and records every call. Standard library only.

THE GROUPS
    TestClassify       error messages from the error log table land in the right category
    TestParse          error_details facts and batch numbers; the failed-records table
    TestHistory        same-type history, trend, the current job left out, other recipes, newest rows first, the row cap
    TestOldRecipe      parity with Notify Via Email - Callable v2: route, Status, flags, master job id
    TestReprocess      Azure's reprocess decision, the guards, and the repeat_jobs call
    TestRender         sections, escaping, size guard, the old look pinned to a golden file
    TestHeader         team logo, solid priority badge, pills at the top; hero_layout=classic keeps the old header
    TestTechnicalDetails  grouped blocks, the id links (recipe, child job, parent job)
    TestHover          hover effects on every section; hover_effects switches them
    TestErrorBanner    the red 'Error alert' strip on top, error_banner switches it
    TestDeveloper      show_developer: the first company author of the recipe, found through its versions
    TestSectionNames   hiding sub-sections, unknown names, every name in the hints
    TestDeferred       frequency / error_limit: logged, never emailed, and nothing done that only an email needs
    TestTableReading   which column of a failed-records table is the error text, which hold ids
    TestExtraRules     the extra rules for messages the main rules missed (rate limit wording, ambiguous match, ...)
    TestAutoRetry      Azure decides, auto_reprocess (yes by default) reruns; what nobody retries is emailed
    TestAzureFailure   a failing Azure call is captured (ai_error) and the email is built from the playbook
    TestFailingNode    which box of 'Where it broke' fails: REST / HTTP and unnamed apps are read from the evidence
    TestJobCard        the job & recipe card has the titled, underlined blocks of the technical details
    TestKeyValueRows   the label | value rows: the label column fits its labels
    TestLogRow         the step upserts the error log row (key: Master Job ID) before the email is built
    TestNeverFails     bad inputs still give an email
    TestCardWidth      the email card widens with the columns of the records table
    TestSchemas        the schema files match what main() reads and returns
    TestRealExport     the exported data table (skipped when the CSV isn't there)
"""

import copy
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import error_notification as en  # noqa: E402

with open(os.path.join(HERE, "testdata", "sample_input.json"), encoding="utf-8") as handle:
    SAMPLE = json.load(handle)

NOW = "2026-11-19T09:11:00-08:00"
RECIPE_ID = "70000001"
JOB = "j-TestJob1-abcdef-CD"


def sample(**extra):
    data = copy.deepcopy(SAMPLE)
    data.update(extra)
    return data


def simple(**extra):
    """A one-line error, no batch: the common case."""
    data = {"subject": "Failure in Lead Sync", "recipe_name": "Lead Sync - RealTime",
            "job_url": "https://app.workato.com/recipes/{}/job/{}".format(RECIPE_ID, JOB),
            "error_details": "Salesforce connection is broken. Please refresh", "priority": "High",
            "sourceSystem": "WES Backend Service", "targetSystem": "SFDC Enterprise",
            "ErroredApp": "salesforce", "ErroredAction": "upsert_sobject", "stepNumber": "12",
            "env": "prod", "now": NOW}
    data.update(extra)
    return data


def row(days_ago=1, message="Salesforce connection is broken. Please refresh", recipe_id=RECIPE_ID,
        recipe="Lead Sync - RealTime", status="Notified", job="j-old", master="", count=0, target="SFDC Enterprise",
        hour=2):
    day = 19 - days_ago
    month = 11
    while day < 1:
        day += 31
        month -= 1
    stamp = "2026-{:02d}-{:02d}".format(month, day)
    return {"Date": stamp, "Error TimeStamp": "{} {:02d}:05:00.000".format(stamp, hour), "Recipe Name": recipe,
            "Recipie Id": recipe_id, "Error Message": message, "Status": status, "Job Id": job,
            "Master Job ID": master or job, "Job URL": "https://app.workato.com/recipes/{}/job/{}".format(recipe_id, job),
            "Reprocess Count": str(count), "Target System": target}


class FakeHttp(object):
    """Answers like the data table, the Workato API and Azure, and records each call."""

    def __init__(self, rows=None, azure=None, job=None, recipe=None, jobs=None, repeat=None, fail=(), stored=None):
        self.rows = rows or []
        self.stored = dict(stored or {})        # record id -> {column: value}: the rows the error log already has
        self.writes = []                        # (method, record id, document) of every create and update
        self.azure = azure
        self.job = job if job is not None else {"status": "pending", "master_job_id": JOB, "is_repeat": False,
                                                "started_at": "2026-11-19T09:10:00-08:00", "lines": []}
        self.recipe = recipe if recipe is not None else {"name": "x", "running": True, "version_no": 7,
                                                         "updated_at": "2026-10-01T00:00:00Z",
                                                         "job_succeeded_count": 990, "job_failed_count": 10}
        self.jobs = jobs if jobs is not None else {"items": [{"status": "succeeded"}] * 9 + [{"status": "failed"}]}
        self.repeat = repeat if repeat is not None else {
            "results": [{"requested_job_id": JOB, "status": "enqueued", "job": {"id": "j-NewRun-1"}}],
            "summary": {"total_requested": 1, "total_enqueued": 1, "total_failed": 0}}
        self.fail = set(fail)
        self.calls = []

    def __call__(self, method, url, headers, payload=None, timeout=12):
        self.calls.append((method, url, payload, dict(headers or {})))
        for key in self.fail:
            if key in url:
                return None, "{} 500: boom".format(key)
        if "data-tables" in url:
            if method == "POST" and url.endswith("/records"):
                rid = "rec-{}".format(len(self.stored) + 1)
                self.stored[rid] = dict(payload["document"])
                self.writes.append(("POST", rid, dict(payload["document"])))
                return {"data": {"record_id": rid, "created_at": "x", "updated_at": "x", "document": []}}, None
            if method == "PUT" and "/records/" in url:
                rid = url.rsplit("/", 1)[1]
                self.stored.setdefault(rid, {}).update(payload["document"])
                self.writes.append(("PUT", rid, dict(payload["document"])))
                return {"data": {"record_id": rid, "document": []}}, None
            where = (payload or {}).get("where") or {}
            if "Master Job ID" in where:                          # the lookup before an upsert: arrays, like the real API
                master = where["Master Job ID"]["$eq"]
                hits = [(rid, doc) for rid, doc in self.stored.items() if doc.get("Master Job ID") == master]
                names = sorted({k for _, doc in hits for k in doc})
                return {"schema": [[{"name": "$record_id"}, {"name": "$created_at"}, {"name": "$updated_at"}],
                                   [{"name": n} for n in names]],
                        "data": [[[rid, "x", "x"], [doc.get(n) for n in names]] for rid, doc in hits],
                        "count": len(hits), "limit": 1}, None
            return {"data": list(self.rows)}, None
        if "openai.azure.com" in url:
            if self.azure is None:
                return None, "azure down"
            return {"choices": [{"message": {"content": json.dumps(self.azure)}}]}, None
        if url.endswith("/repeat_jobs"):
            return self.repeat, None
        if "/jobs/" in url:
            return self.job, None
        if url.endswith("/jobs"):
            return self.jobs, None
        if "/recipes/" in url:
            return self.recipe, None
        return None, "unexpected url " + url

    def urls(self, part):
        return [c for c in self.calls if part in c[1]]


def history_queries(fake):
    """The queries for this recipe's history (not the cross-recipe one, the master job lookup or a write)."""
    return [c for c in fake.urls("data-tables") if c[2] and "$and" in (c[2].get("where") or {})]


class OrderRefusingHttp(FakeHttp):
    """A data table API that answers 422 to a query that has an `order`."""

    def __call__(self, method, url, headers, payload=None, timeout=12):
        if "data-tables" in url and payload and "order" in payload:
            self.calls.append((method, url, payload, dict(headers or {})))
            return None, "data-tables.workato.com 422: order is not supported"
        return FakeHttp.__call__(self, method, url, headers, payload, timeout)


class BadAzureHttp(FakeHttp):
    """Azure answers, but not with what was asked for."""

    def __init__(self, answer, **kw):
        FakeHttp.__init__(self, **kw)
        self.answer = answer

    def __call__(self, method, url, headers, payload=None, timeout=12):
        if "openai.azure.com" in url:
            self.calls.append((method, url, payload, dict(headers or {})))
            return self.answer, None
        return FakeHttp.__call__(self, method, url, headers, payload, timeout)


class BusyOnceHttp(FakeHttp):
    """A data table API that answers 429 to the first create, then works."""
    busy = True

    def __call__(self, method, url, headers, payload=None, timeout=12):
        if method == "POST" and url.endswith("/records") and self.busy:
            self.busy = False
            self.calls.append((method, url, payload, dict(headers or {})))
            return None, "data-tables.workato.com 429: slow down"
        return FakeHttp.__call__(self, method, url, headers, payload, timeout)


class EndlessHttp(FakeHttp):
    """A table with more rows than the step reads: every page comes with a continuation token."""

    def __call__(self, method, url, headers, payload=None, timeout=12):
        body, err = FakeHttp.__call__(self, method, url, headers, payload, timeout)
        if "data-tables" in url and body is not None:
            body = dict(body, continuation_token="more")
        return body, err


AZURE_YES = {"headline": "Salesforce sign-in failed for Lead Sync", "functional_summary": "Leads did not sync.",
             "technical_summary": "`INVALID_SESSION_ID` from Salesforce.", "likely_causes": ["Token expired"],
             "next_steps": ["Reconnect", "Rerun"], "confidence": "high", "reprocessable": "yes",
             "reprocess_reason": "The connection was refreshed; a re-run should work."}


class Patched(unittest.TestCase):
    """Swap http_json for a fake for one test."""

    def run_main(self, data, fake=None, **extra):
        fake = fake or FakeHttp()
        original = en.http_json
        en.http_json = fake
        try:
            out = en.main(dict(data, **extra))
        finally:
            en.http_json = original
        return out, fake


# ------------------------------------------------------------------------------------


class TestClassify(unittest.TestCase):
    CASES = [
        ('[{"message":"cannot reference converted lead","errorCode":"CANNOT_UPDATE_CONVERTED_LEAD","fields":[]}]', "converted_lead"),
        ("404 Not Found", "not_found"),
        ("Invalid value for the resource or sub-resource field 'salesRep'. Provide a valid value.", "invalid_reference"),
        ("Unable to create/update fields: Audience_Type__c. Please check the security settings", "field_access"),
        ("Timeout: code execution exceeded 90 seconds", "timeout"),
        ("Job failed with timeout error", "timeout"),
        ("Internal error", "server_error"),
        ("Async callable jobs limit exceeded", "rate_limit"),
        ("Salesforce connection is broken. Please refresh", "auth"),
        ("Can't call a stopped recipe (id: 12345678)", "stopped_recipe"),
        ('[{"message":"invalid cross reference id","errorCode":"INVALID_CROSS_REFERENCE_KEY"}]', "invalid_reference"),
        ("Either 'Channel name/DM' or 'Reply channel' must be present", "missing_input"),
        ("No activity within 300 seconds", "timeout"),
        ("Error calculating input for field 'condition': (missing field value) greater than 0", "formula"),
        ("429 Too Many Requests: Access key API calls limit exceeded", "rate_limit"),
        ("Incorrect format for double", "validation"),
        ("Database bridge error: Error while receiving response from Thrift server.", "server_error"),
        ("403 Forbidden", "permission"),
        ('401 Unauthorized: {"error_description":"access_denied"}', "auth"),
        ("recipe_creation_payload is not valid JSON", "validation"),
        ("Concurrent request limit exceeded. Request blocked.", "rate_limit"),
        ("DUPLICATE_VALUE:Duplicate external id specified: x: Application_Primary_Key__c --", "duplicate"),
        ("Recipe retrieved <b> 5 </b> invoices from Netsuite, however, it failed to synchronize <a>2</a>", "partial_batch"),
        ("No Content Management Record Found in Salesforce For SFDC CMO Id: a0k", "not_found"),
        ("UNABLE_TO_LOCK_ROW: unable to obtain exclusive access to this record", "record_lock"),
        # seen in the error log, and not matched by the rules above (EXTRA_RULES)
        ("You have exceeded your limit of 12000 requests per three seconds. Please contact your account executive to "
         "increase your limit. If you do not have their info, you may contact Braze directly at https://www.braze.com/contact/.",
         "rate_limit"),
        ("431 Request Header Fields Too Large", "bad_request"),
        ("More than 1 record matched the given criteria and could not be updated. Make sure the condition matches exactly one record", "multi_match"),
        ("APP_SUBMIT - Failed due to Data validation error. Please verify the attachment for more information", "validation"),
        ('"UpSkill Digital" is not a valid Salesforce ID', "invalid_reference"),
        ("<p>Error Occred while processing <b>Account</b> records from EDS to <b>Salesforce Services</b> </p>", "partial_batch"),
        ('Input data too big; fields: "Production_Notes_Log__c"', "validation"),
        ("Error while accessing a resource. Please enter value(s) for: Company Name.", "missing_input"),
        ("", "unknown"),
    ]

    def test_messages_from_the_error_log(self):
        rules = en.category_rules({})
        for message, expected in self.CASES:
            self.assertEqual(en.classify(message, rules), expected, message)

    def test_total_records_number_is_not_an_http_code(self):
        rules = en.category_rules({})
        self.assertEqual(en.classify("<p>Done</p><p>Total Records : 400</p><p>Records Failed: 4</p>", rules),
                         "partial_batch")

    def test_config_rules_come_first(self):
        rules = en.category_rules({"category_rules": [{"key": "bing", "label": "Bing report", "patterns": ["bing ads"]}]})
        self.assertEqual(en.classify("Bing Ads Report file not created. 404 Not Found", rules), "bing")

    def test_fingerprint_ignores_ids_and_numbers(self):
        a = en.fingerprint_text("Record a0kPJ00000QcBWXYA3 failed at 2026-11-19T02:02:00Z for 35909 rows j-AbC123-xyz")
        b = en.fingerprint_text("Record a0kPJ00000ZZZZZYA3 failed at 2026-11-18T05:00:00Z for 12 rows j-ZZZ999-abc")
        self.assertEqual(a, b)

    def test_stop_step_with_no_known_pattern(self):
        out = en.main(simple(error_details="Business rule says no", ErroredApp="misc_dsl", ErroredAction="stop",
                             ai="no", history="no"))
        self.assertEqual(out["error_category"], "stop_job")


class TestParse(unittest.TestCase):
    def test_uol_message(self):
        details = en.parse_details(SAMPLE["error_details"])
        self.assertTrue(details["headline"].startswith("Error Occred while processing UOL Application records"))
        self.assertEqual(details["metrics"], {"total": 35909, "failed": 4})
        self.assertIn(("SFDC Job Id", "750VN000018VrEFYA0"), details["facts"])
        key = dict(details["facts"])["The Processed File Key"]
        self.assertTrue(key.endswith(".csv"), key)
        self.assertEqual(details["processing"]["object"], "UOL Application")
        self.assertEqual(details["processing"]["target"], "Salesforce Services")

    def test_netsuite_sentence(self):
        details = en.parse_details('Recipe retrieved <b> 12 </b> invoices from Netsuite, however, it failed to '
                                   'synchronize <a style="color:#ff0000">3</a> of them.')
        self.assertEqual(details["metrics"]["total"], 12)
        self.assertEqual(details["metrics"]["failed"], 3)

    def test_one_line_message_has_no_facts(self):
        details = en.parse_details("Timeout: code execution exceeded 90 seconds")
        self.assertEqual(details["facts"], [])
        self.assertEqual(details["headline"], "Timeout: code execution exceeded 90 seconds")

    def test_records_and_duplicates(self):
        cols, rows = en.read_records(SAMPLE)
        rec = en.analyze_records(cols, rows, en.category_rules({}))
        self.assertEqual(rec["count"], 4)
        self.assertEqual(rec["err_col"], 3)
        self.assertEqual(rec["codes"]["DUPLICATE_VALUE"], 4)
        self.assertEqual(len(rec["duplicates"][1]), 2)
        self.assertEqual(rec["dup_rows"], 4)

    def test_rows_without_value1_are_skipped_like_the_template(self):
        cols, rows = en.read_records({"column1Name": "Id", "dataArray": [{"value1": ""}, {"value1": "a"}, "junk"]})
        self.assertEqual(len(rows), 1)

    def test_batch_numbers_reach_the_outputs(self):
        out = en.main(sample(ai="no"))
        self.assertEqual((out["records_total"], out["records_failed"], out["success_rate"]), (35909, 4, "99.99%"))
        self.assertEqual(out["error_category"], "duplicate")
        self.assertTrue(out["is_batch"])


class TestHistory(Patched):
    def test_same_type_trend_and_current_job_left_out(self):
        rows = [row(1), row(2), row(3), row(0, job=JOB),                     # the current job: left out
                row(20, message="Timeout: code execution exceeded 90 seconds"),
                row(200)]                                                    # outside 90 days
        out, _ = self.run_main(simple(workato_api_token="t", ai="no"), FakeHttp(rows=rows))
        self.assertTrue(out["history_used"])
        self.assertEqual(out["history_total"], 4)
        self.assertEqual(out["history_same_type"], 3)
        self.assertEqual(out["history_7d"], 4)
        self.assertEqual(out["history_trend"], "rising")
        self.assertTrue(out["is_recurring"])
        self.assertIn("4×</b> in the last 7 days counting this one", out["html"])

    def test_first_occurrence(self):
        out, _ = self.run_main(simple(workato_api_token="t", ai="no"), FakeHttp(rows=[]))
        self.assertEqual(out["history_trend"], "new")
        self.assertFalse(out["is_recurring"])
        self.assertIn("This is the first one", out["html"])

    def test_other_recipes_with_the_same_systemic_error(self):
        rows = [row(1), row(1, recipe="Account Sync", recipe_id="2"), row(2, recipe="Contact Sync", recipe_id="3"),
                row(1, recipe="Other target", recipe_id="4", target="NetSuite",   # same kind, other system
                    message='401 Unauthorized: {"error":"invalid_client"}')]
        out, _ = self.run_main(simple(workato_api_token="t", ai="no"), FakeHttp(rows=rows))
        self.assertEqual(out["other_recipes_affected"], 2)
        self.assertTrue(any("other recipe" in s for s in out["signals"]))

    def test_history_rows_json_needs_no_token(self):
        out = en.main(simple(ai="no", history_rows_json=json.dumps([row(1), row(2)])))
        self.assertEqual(out["history_same_type"], 2)

    def test_the_query_filters_on_recipe_and_date(self):
        _, fake = self.run_main(simple(workato_api_token="t", ai="no"))
        where = fake.urls("data-tables")[0][2]["where"]
        self.assertEqual(where["$and"][0], {"Recipie Id": {"$eq": RECIPE_ID}})
        self.assertEqual(where["$and"][1], {"Date": {"$gte": "2026-08-22"}})

    def test_the_query_asks_for_the_newest_rows_first(self):
        _, fake = self.run_main(simple(workato_api_token="t", ai="no"))
        self.assertEqual(fake.urls("data-tables")[0][2]["order"], {"by": "$created_at", "direction": "desc"})

    def test_an_order_the_table_refuses_is_dropped_and_the_history_still_reads(self):
        rows = [row(1), row(2), row(3)]
        out, fake = self.run_main(simple(workato_api_token="t", ai="no"), OrderRefusingHttp(rows=rows))
        calls = history_queries(fake)
        self.assertEqual(len(calls), 2)
        self.assertIn("order", calls[0][2])
        self.assertNotIn("order", calls[1][2])
        self.assertEqual(out["history_same_type"], 3)
        self.assertFalse([w for w in out["warnings"] if "history" in w])

    def test_a_list_cut_by_the_row_cap_says_so(self):
        rows = [row(1 + i % 5) for i in range(200)]
        out, fake = self.run_main(simple(workato_api_token="t", ai="no"), EndlessHttp(rows=rows))
        history = history_queries(fake)
        self.assertEqual(len(history), 12)                                   # 12 pages of 200 = the 2,400-row cap
        self.assertTrue([w for w in out["warnings"] if w.startswith("history:") and "repeat counts can be low" in w],
                        out["warnings"])

    def test_a_list_that_fits_gives_no_cap_warning(self):
        out, _ = self.run_main(simple(workato_api_token="t", ai="no"), FakeHttp(rows=[row(1), row(2)]))
        self.assertFalse([w for w in out["warnings"] if "repeat counts" in w])

    def test_array_of_arrays_response(self):
        body = {"schema": [[{"name": "Date"}, {"name": "Recipie Id"}, {"name": "Error Message"}]],
                "data": [[["2026-11-18", RECIPE_ID, "Salesforce connection is broken"]]]}
        rows = en.decode_rows(body)
        self.assertEqual(rows, [{"Date": "2026-11-18", "Recipie Id": RECIPE_ID,
                                 "Error Message": "Salesforce connection is broken"}])

    def test_history_failure_is_only_a_warning(self):
        out, _ = self.run_main(simple(workato_api_token="t", ai="no"), FakeHttp(fail=["data-tables"]))
        self.assertTrue(out["ok"])
        self.assertFalse(out["history_used"])
        self.assertTrue(any("history lookup failed" in w for w in out["warnings"]))


class TestOldRecipe(Patched):
    """Notify Via Email - Callable v2, step by step."""

    def test_plain_error_is_emailed_and_logged_as_notified(self):
        out = en.main(simple(ai="no", history="no"))
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))
        r = out["table_row"]
        self.assertEqual((r["status"], r["reprocess_count"], r["reprocess_flag"]), ("Notified", 0, False))
        self.assertEqual(r["master_job_id"], JOB)
        self.assertEqual(r["recipe_id"], RECIPE_ID)
        self.assertEqual(r["date"], "2026-11-19")

    def test_frequency_or_error_limit_only_logs(self):
        for extra in ({"frequency": 6}, {"error_limit": "20"}):
            out = en.main(simple(ai="no", history="no", **extra))
            self.assertEqual((out["action"], out["send_email"]), ("log_only", False), extra)
            self.assertEqual(out["table_row"]["status"], "Created")

    def test_the_callers_reprocess_input_is_ignored(self):
        for value in (True, False, "true", "false", "no", ""):
            out = en.main(simple(ai="no", history="no", reprocess=value))
            self.assertEqual((out["action"], out["send_email"]), ("notify", True), value)
            self.assertEqual(out["reprocess_source"], "none", value)                     # no Azure: nothing is retried
            self.assertFalse(out["table_row"]["reprocess_flag"], value)

    def test_repeated_run_is_failed_again(self):
        out = en.main(simple(ai="no", history="no", is_Repeated=True, reprocess=True))
        r = out["table_row"]
        self.assertEqual(r["status"], "Failed Again")
        self.assertIsNone(r["reprocess_count"])
        self.assertFalse(r["reprocess_flag"])

    def test_child_job_url_is_failed_again_with_the_master_from_the_url(self):
        url = "https://app.workato.com/recipes/{}/job/j-Master-1?child_job_id=j-Child-2".format(RECIPE_ID)
        out = en.main(simple(ai="no", history="no", job_url=url))
        self.assertEqual(out["table_row"]["status"], "Failed Again")
        self.assertEqual(out["master_job_id"], "j-Master-1")
        self.assertEqual(out["table_row"]["job_id"], "j-Child-2")

    def test_master_job_id_order(self):
        out = en.main(simple(ai="no", history="no", calling_master_job_id="j-Given"))
        self.assertEqual(out["master_job_id"], "j-Given")
        fake = FakeHttp(job={"master_job_id": "j-FromApi", "lines": []})
        out, _ = self.run_main(simple(ai="no", history="no", workato_api_token="t"), fake)
        self.assertEqual(out["master_job_id"], "j-FromApi")

    def test_trigger_context_wins_over_the_url(self):
        out = en.main(simple(ai="no", history="no", calling_recipe_id="555", calling_job_id="j-Ctx"))
        self.assertEqual((out["table_row"]["recipe_id"], out["table_row"]["job_id"]), ("555", "j-Ctx"))

    def test_file_link_expiry(self):
        out = en.main(simple(ai="no", history="no", error_file_url="https://f.example/x", error_file_path="/Error_Files/2026_11/x.csv",
                             error_file_expires_in=604800))
        r = out["table_row"]
        now = int(en.parse_dt(NOW, en.get_tz("America/Los_Angeles")).timestamp())
        self.assertEqual(r["sharable_link_expires_on"], now + 604800)
        self.assertEqual(r["error_file_path"], "/Error_Files/2026_11/x.csv")
        columns = json.loads(out["table_row_json"])
        self.assertEqual(set(columns), {c for _, c in en.TABLE_ROW_KEYS})

    def test_recipient_falls_back_to_alert_email(self):
        out = en.main(simple(ai="no", history="no", alert_email="alerts@example.com"))
        self.assertEqual(out["to_email"], "alerts@example.com")

    def test_subject_is_the_old_formula_by_default(self):
        for priority, emoji in (("Critical", "🚨"), ("high", "❗"), ("Medium", "⚠️"), ("", "⚠️")):
            out = en.main(simple(ai="no", history="no", priority=priority))
            self.assertEqual(out["subject"], "{} Prod | Failure in Lead Sync".format(emoji), priority)
        old = en.main(simple(look="old", priority="CRITICAL"))
        self.assertEqual(old["subject"], "🚨 Prod | Failure in Lead Sync")

    def test_custom_subject(self):
        out = en.main(simple(ai="no", history_rows_json=json.dumps([row(1)]),
                             subject_format="[{ENV}] {category}: {recipe}{recurring}"))
        self.assertEqual(out["subject"], "[PROD] Authentication / connection: Lead Sync - RealTime · 🔁 2× in 7d")


class TestReprocess(Patched):
    def test_azure_yes_and_auto_reprocess_repeats_the_master_job(self):
        fake = FakeHttp(azure=AZURE_YES)
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes"), fake)
        calls = fake.urls("/repeat_jobs")
        self.assertEqual(len(calls), 1)
        method, url, payload, headers = calls[0]
        self.assertEqual((method, url), ("POST", "https://www.workato.com/api/recipes/{}/repeat_jobs".format(RECIPE_ID)))
        self.assertEqual(payload, {"job_ids": [JOB]})
        self.assertEqual(headers["Authorization"], "Bearer t")
        self.assertTrue(out["reprocess_enqueued"])
        self.assertEqual(out["reprocess_job_id"], "j-NewRun-1")
        self.assertEqual((out["action"], out["send_email"]), ("log_only", False))
        self.assertEqual((out["table_row"]["status"], out["table_row"]["reprocess_count"]), ("Reprocessed", 1))
        self.assertIn("Auto-retry queued", out["html"])

    def test_azure_decides_by_default_and_the_step_reruns_what_azure_says_yes_to(self):
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k", detail="full"), FakeHttp(azure=AZURE_YES))
        self.assertEqual((out["reprocessable"], out["reprocess_source"]), (True, "ai"))
        self.assertEqual((out["action"], out["send_email"]), ("log_only", False))        # retried: logged, not emailed
        self.assertTrue(out["reprocess_enqueued"])
        self.assertEqual((out["table_row"]["status"], out["table_row"]["reprocess_flag"]), ("Reprocessed", True))
        self.assertEqual(len(fake.urls("/repeat_jobs")), 1)

    def test_azure_saying_no_means_no_retry_and_an_email(self):
        no = dict(AZURE_YES, reprocessable="no", reprocess_reason="A re-run would fail the same way.")
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k"), FakeHttp(azure=no))
        self.assertEqual((out["reprocessable"], out["reprocess_source"]), (False, "ai"))
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))
        self.assertEqual((out["table_row"]["status"], out["table_row"]["reprocess_flag"]), ("Notified", False))
        self.assertEqual(fake.urls("/repeat_jobs"), [])

    def test_a_blank_reprocess_is_not_an_answer(self):
        for value in (None, "", "  "):
            out, _ = self.run_main(simple(workato_api_token="t", azure_api_key="k", reprocess_check="yes", reprocess=value),
                                   FakeHttp(azure=AZURE_YES))
            self.assertEqual((out["reprocessable"], out["reprocess_source"]), (True, "ai"), value)

    def test_azure_is_asked_for_the_decision_unless_auto_reprocess_is_off(self):
        data = dict(workato_api_token="t", azure_api_key="k", sections="error", history="no", job_context="no")
        _, fake = self.run_main(simple(**data), FakeHttp(azure=AZURE_YES))
        self.assertEqual(len(fake.urls("openai")), 1)                          # the decision, even with no story in the email
        _, fake = self.run_main(simple(auto_reprocess="no", **data), FakeHttp(azure=AZURE_YES))
        self.assertEqual(len(fake.urls("openai")), 0)                          # switched off: nothing to decide
        _, fake = self.run_main(simple(reprocess=False, **data), FakeHttp(azure=AZURE_YES))
        self.assertEqual(len(fake.urls("openai")), 1)                          # the caller's input changes nothing

    def test_no_repeat_and_no_decision_when_auto_reprocess_is_off(self):
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="no"),
                                  FakeHttp(azure=AZURE_YES))
        self.assertEqual(fake.urls("/repeat_jobs"), [])
        self.assertEqual((out["reprocessable"], out["reprocess_source"]), (False, "off"))
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))
        self.assertFalse(out["table_row"]["reprocess_flag"])

    def test_low_confidence_blocks_the_repeat(self):
        azure = dict(AZURE_YES, confidence="low")
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes"),
                                  FakeHttp(azure=azure))
        self.assertEqual(fake.urls("/repeat_jobs"), [])
        self.assertIn("confidence", out["reprocess_error"])

    def test_a_repeat_is_never_repeated_again(self):
        for extra, job in (({"is_Repeated": True}, None),
                           ({}, {"master_job_id": JOB, "is_repeat": True, "lines": []})):
            fake = FakeHttp(azure=AZURE_YES, job=job)
            _, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes", **extra), fake)
            self.assertEqual(fake.urls("/repeat_jobs"), [], extra)

    def test_prior_repeats_in_the_log_block_the_repeat(self):
        rows = [row(0, job="j-Other", master=JOB, count=1, status="Reprocessed")]
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes"),
                                  FakeHttp(azure=AZURE_YES, rows=rows))
        self.assertEqual(fake.urls("/repeat_jobs"), [])
        self.assertIn("already repeated", out["reprocess_error"])

    def test_a_failed_repeat_sends_the_email(self):
        fake = FakeHttp(azure=AZURE_YES, fail=["/repeat_jobs"])
        out, _ = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes"), fake)
        self.assertTrue(out["reprocess_attempted"])
        self.assertFalse(out["reprocess_enqueued"])
        self.assertTrue(out["send_email"])
        self.assertEqual(out["table_row"]["status"], "Notified")
        self.assertIn("Auto-retry failed", out["html"])

    def test_workato_refusing_the_repeat(self):
        refused = {"results": [{"requested_job_id": JOB, "status": "failed", "error": "Job is outside retention"}],
                   "summary": {"total_requested": 1, "total_enqueued": 0, "total_failed": 1}}
        out, _ = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes"),
                               FakeHttp(azure=AZURE_YES, repeat=refused))
        self.assertFalse(out["reprocess_enqueued"])
        self.assertIn("retention", out["reprocess_error"])

    def test_both_policy_needs_the_rules_to_agree(self):
        out, _ = self.run_main(sample(workato_api_token="t", azure_api_key="k", reprocess_policy="both", reprocess_check="yes"),
                               FakeHttp(azure=AZURE_YES))
        self.assertFalse(out["reprocessable"])          # duplicates aren't temporary
        self.assertEqual(out["reprocess_source"], "ai+rules")

    def test_azure_giving_no_answer_means_no_retry_and_an_email(self):
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k",
                                         error_details="Timeout: code execution exceeded 90 seconds"), FakeHttp(azure=None))
        self.assertEqual((out["reprocessable"], out["reprocess_source"]), (False, "none"))
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))
        self.assertEqual(fake.urls("/repeat_jobs"), [])
        self.assertTrue(any("not retried" in w for w in out["warnings"]))

    def test_the_rules_alone_can_be_chosen(self):
        out, fake = self.run_main(simple(workato_api_token="t", azure_api_key="k", reprocess_policy="rules",
                                         error_details="Timeout: code execution exceeded 90 seconds"), FakeHttp(azure=None))
        self.assertEqual((out["reprocessable"], out["reprocess_source"]), (True, "rules"))
        self.assertTrue(out["reprocess_enqueued"])

    def test_azure_gets_redacted_facts(self):
        data = sample(workato_api_token="t", azure_api_key="k", file_content="id,email\n240697817,someone@example.com")
        _, fake = self.run_main(data, FakeHttp(azure=AZURE_YES))
        sent = fake.urls("openai.azure.com")[0][2]["messages"][1]["content"]
        self.assertNotIn("someone@example.com", sent)
        self.assertNotIn("240697817", sent)
        self.assertNotIn("100000001", sent)
        self.assertIn("reprocess_context", sent)

    def test_ai_text_is_escaped(self):
        azure = dict(AZURE_YES, functional_summary="<script>alert(1)</script> leads")
        out, _ = self.run_main(simple(azure_api_key="k"), FakeHttp(azure=azure))
        self.assertNotIn("<script>alert", out["html"])
        self.assertIn("&lt;script&gt;", out["html"])
        self.assertIn("<code", out["html"])                # `INVALID_SESSION_ID` became code


class TestRender(Patched):
    def test_new_look_sections(self):
        out = en.main(sample(ai="no"))                       # standard is the default level
        self.assertEqual(out["look_used"], "new")
        self.assertEqual(out["sections_rendered"], ["hero", "error", "records", "story", "signals", "actions"])
        self.assertNotIn("FAILED HERE", out["html"])
        self.assertIn("×2", out["html"])
        full = en.main(sample(ai="no", detail="full"))
        self.assertEqual(full["sections_rendered"],
                         ["hero", "error", "records", "flow", "kpis", "story", "signals", "details", "actions"])
        self.assertIn("FAILED HERE", full["html"])

    def test_detail_levels_and_adding_or_hiding_sections(self):
        brief = en.main(sample(ai="no", detail="brief"))
        self.assertEqual(brief["sections_rendered"], ["hero", "error", "records", "actions"])
        more = en.main(sample(ai="no", detail="brief", show_sections="kpis, details"))
        self.assertEqual(more["sections_rendered"], ["hero", "error", "records", "kpis", "details", "actions"])
        less = en.main(sample(ai="no", hide_sections="signals,story"))
        self.assertEqual(less["sections_rendered"], ["hero", "error", "records", "actions"])
        picked = en.main(sample(ai="no", detail="full", sections="actions,error,hero"))      # sections replaces the level
        self.assertEqual(picked["sections_rendered"], ["actions", "error", "hero"])
        odd = en.main(sample(ai="no", detail="huge"))
        self.assertEqual(odd["sections_rendered"], ["hero", "error", "records", "story", "signals", "actions"])
        self.assertTrue(any("detail 'huge'" in w for w in odd["warnings"]))

    def test_the_email_never_names_the_vendor(self):
        data = sample(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes", detail="full", reprocess_policy="both")
        out, _ = self.run_main(data, FakeHttp(azure=AZURE_YES, rows=[row(1), row(2)]))
        self.assertNotIn("azure", out["html"].lower())
        self.assertNotIn("azure", out["text_body"].lower())
        self.assertIn("AI", out["html"])

    def test_a_fact_is_said_once(self):
        rows = [row(1), row(2), row(3)]
        std, _ = self.run_main(simple(workato_api_token="t", ai="no", hero_layout="classic"), FakeHttp(rows=rows))
        self.assertIn("in the last 7 days counting this one", std["html"])                          # classic: history says it
        self.assertEqual(std["html"].count("in 7 days"), 0)                                         # no pill, no tile, no signal
        self.assertNotIn("Seen before", std["html"])
        new, _ = self.run_main(simple(workato_api_token="t", ai="no"), FakeHttp(rows=rows))         # new header: pills at the top
        self.assertIn("× in 7 days", new["html"])
        self.assertNotIn("Seen before", new["html"])
        brief, _ = self.run_main(simple(workato_api_token="t", ai="no", detail="brief", hero_layout="classic"), FakeHttp(rows=rows))
        self.assertIn("in 7 days", brief["html"])                                                   # no history section: the pill says it
        full = en.main(sample(ai="no", detail="full", hero_layout="classic"))
        self.assertEqual(full["html"].count("99.99%"), 1)                                           # the tile, not the pill and signal too

    def test_history_and_job_sit_on_a_light_panel(self):
        out, _ = self.run_main(simple(workato_api_token="t", ai="no", detail="full"), FakeHttp(rows=[row(1)]))
        html = out["html"]
        panel = "background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;padding:14px 16px"
        for title in ("Failure history", "Workato job &amp; recipe"):
            at = html.index(title)
            self.assertIn(panel, html[at:at + 1500], title)

    def test_the_email_opens_on_the_error_and_the_table_follows_it(self):
        html = en.main(sample(ai="no", detail="full"))["html"]
        error, table = html.index("Error message"), html.index("Failed records")
        self.assertNotIn("Hi Team,", html)
        self.assertNotIn("We caught an error", html)
        self.assertLess(html.index("Production"), error)
        self.assertLess(error, table)
        self.assertLess(table, html.index("Records processed"))
        self.assertLess(table, html.index("Where it broke"))

    def test_the_intro_is_opt_in_and_a_custom_message_still_shows(self):
        with_intro = en.main(sample(ai="no", show_intro="yes"))["html"]
        self.assertLess(with_intro.index("Hi Team,"), with_intro.index("Error message"))
        self.assertIn("We caught an error in the", with_intro)
        custom = en.main(sample(ai="no", mail_msg="Planned maintenance tonight."))["html"]
        self.assertIn("Planned maintenance tonight.", custom)
        self.assertNotIn("Hi Team,", custom)
        body = en.main(sample(ai="no"))["html"].split("<body", 1)[1]
        self.assertEqual(body.count("Salesforce - AWS S3 UOL Application files Process - Function"), 1)   # the recipe name once

    def test_the_old_order_is_one_input_away(self):
        out = en.main(sample(ai="no", sections="hero,kpis,flow,story,signals,error,records,history,job,details,actions"))
        self.assertEqual(out["sections_rendered"],
                         ["hero", "kpis", "flow", "story", "signals", "error", "records", "details", "actions"])

    def test_order_and_hiding(self):
        out = en.main(sample(ai="no", sections="error, records, hero, nonsense", hide_sections="records"))
        self.assertEqual(out["sections_rendered"], ["error", "hero"])
        self.assertTrue(any("nonsense" in w for w in out["warnings"]))

    def test_unsafe_error_html_is_cleaned(self):
        evil = ('<p onclick="x()">Bad <b>thing</b></p><script>alert(1)</script><a href="javascript:x()">a</a>'
                '<a href="https://ok.example/">b</a><style>body{display:none}</style>')
        out = en.main(simple(ai="no", history="no", error_details=evil, recipe_name="<img src=x onerror=y>"))
        for bad in ("<script", "onclick", "javascript:", "display:none}", "<img src=x"):
            self.assertNotIn(bad, out["html"], bad)
        self.assertIn('href="https://ok.example/"', out["html"])

    def test_big_tables_are_cut_to_stay_under_the_limit(self):
        many = [{"value1": "id-{}".format(i), "value2": "x" * 60, "value3": "DUPLICATE_VALUE: " + "y" * 300}
                for i in range(400)]
        out = en.main(sample(ai="no", dataArray=many, max_table_rows=400, html_limit_kb=100))
        self.assertLessEqual(out["html_bytes"], 100 * 1024)
        self.assertTrue(any("cut to" in w for w in out["warnings"]))

    def test_mobile_classes(self):
        html = en.main(sample(ai="no"))["html"]
        for cls in ('class="px"', 'class="stack"', 'class="rc"', 'class="outer"', "@media only screen"):
            self.assertIn(cls, html)

    def test_job_section_from_the_api(self):
        job = {"status": "failed", "master_job_id": JOB, "started_at": "2026-11-19T09:10:00-08:00",
               "lines": [{"recipe_line_number": 3, "adapter_name": "salesforce", "adapter_operation": "search_sobjects",
                          "line_stat": {"total": 0.24}},
                         {"recipe_line_number": 8, "adapter_name": "misc", "adapter_operation": "catch",
                          "output": {"error": {"type": "Stop processing", "message": "No record", "line_number": 8,
                                               "retry_count": 0, "error_at": "2026-11-19T09:10:30-08:00"}}}]}
        out, _ = self.run_main(simple(workato_api_token="t", ai="no", show_sections="job"), FakeHttp(job=job))
        self.assertIn("job", out["sections_rendered"])
        self.assertIn("Stop processing", out["html"])
        self.assertIn("Ran for", out["html"])
        self.assertEqual((out["recent_jobs_checked"], out["recent_jobs_failed"]), (10, 1))
        self.assertEqual(out["recipe_running"], "yes")

    def test_old_look_is_pinned(self):
        out = en.main(sample(look="old"))
        self.assertEqual(out["look_used"], "old")
        golden = os.path.join(HERE, "testdata", "golden_old.html")
        if os.environ.get("UPDATE_GOLDEN"):
            with open(golden, "w", encoding="utf-8") as handle:
                handle.write(out["html"])
        with open(golden, encoding="utf-8") as handle:
            self.assertEqual(out["html"], handle.read())

    def test_old_look_keeps_the_old_colours_and_titleized_headers(self):
        html = en.main(sample(look="old", priority="Critical", env="dev"))["html"]
        self.assertIn("background-color: #ff5c33", html)
        self.assertIn("background-color: #D1FAE5", html)
        self.assertEqual(en.titleize("application_primary_id"), "Application Primary")
        self.assertEqual(en.titleize("Error Message"), "Error Message")


class TestHeader(Patched):
    TEAM = "https://example.com/team-logo.png"

    def hero(self, **extra):
        html = en.main(sample(ai="no", **extra))["html"]
        return html.split("<body", 1)[1]

    # ---- the retry verdict: a small pill next to the priority (green = will be retried, red = will not, blue = flagged)
    def retry(self, fake=None, **extra):
        out, _ = self.run_main(simple(**extra), fake or FakeHttp())
        return out

    def retry_ctx(self, **extra):
        inp = simple(**extra)
        cfg, _ = en.settings(inp)
        return en.build_context(inp, cfg, en.current_time(cfg, en.get_tz(cfg["timezone"])))

    def test_without_an_azure_answer_the_pill_says_it_will_not_auto_retry(self):
        out = self.retry(ai="no")
        self.assertIn("⛔ Will not auto retry</span>", out["html"])
        self.assertIn("Azure is not set up", out["html"])                           # in the pill's hover text
        self.assertIn("Retry: Will not auto retry", out["text_body"])
        self.assertNotIn("Reprocess from the calling recipe", out["html"])         # the caller's input plays no part

    def test_the_pill_colours(self):
        ctx = self.retry_ctx()
        self.assertIn("background:" + en.BAD_SOFT, en.retry_pill(ctx))                     # will not: red
        self.assertIn("color:" + en.BAD, en.retry_pill(ctx))
        ctx.repeat["enqueued"] = True
        self.assertIn("♻️ Will be auto retried", en.retry_pill(ctx))
        self.assertIn("background:" + en.GOOD_SOFT, en.retry_pill(ctx))                    # will: green

    def test_auto_reprocess_off_says_so(self):
        out = self.retry(ai="no", auto_reprocess="no")
        self.assertIn("⛔ Will not auto retry</span>", out["html"])
        self.assertIn("Auto retry is switched off (auto_reprocess = no)", out["html"])

    def test_a_queued_retry_says_it_will_be_retried(self):
        out = self.retry(FakeHttp(azure=AZURE_YES), workato_api_token="t", azure_api_key="k", reprocess_check="yes",
                         auto_reprocess="yes")
        self.assertTrue(out["reprocess_enqueued"])
        self.assertIn("♻️ Will be auto retried</span>", out["html"])
        self.assertIn("A retry was queued automatically (job j-NewRun-1)", out["html"])

    def test_a_failed_auto_retry_says_so(self):
        out = self.retry(FakeHttp(azure=AZURE_YES, fail=["/repeat_jobs"]), workato_api_token="t", azure_api_key="k",
                         reprocess_check="yes", auto_reprocess="yes")
        self.assertIn("❌ Auto retry failed</span>", out["html"])
        self.assertIn("It needs a person", out["html"])

    def test_a_run_that_is_already_a_retry_is_not_retried_again(self):
        out = self.retry(ai="no", is_Repeated=True)
        self.assertIn("🔁 Retry failed again</span>", out["html"])
        self.assertIn("will not be retried again", out["html"])

    def test_an_auto_retry_the_guards_stopped_says_why(self):
        out = self.retry(FakeHttp(azure=AZURE_YES), workato_api_token="t", azure_api_key="k", reprocess_check="yes",
                         auto_reprocess="yes", max_auto_repeats=0)
        self.assertIn("⛔ Will not auto retry</span>", out["html"])                 # the pill is short ...
        self.assertIn("max_auto_repeats is 0.", out["html"])                        # ... the reason is in its hover text

    def test_a_no_from_azure_says_it_needs_a_fix(self):
        out = self.retry(FakeHttp(azure=dict(AZURE_YES, reprocessable="no", reprocess_reason="A re-run would fail the same way.")), workato_api_token="t", azure_api_key="k")
        self.assertIn("Will not auto retry</span>", out["html"])
        self.assertIn("Needs a fix. A re-run would fail the same way.", out["html"])

    def test_the_pill_sits_right_after_the_priority_pill_before_the_category(self):
        html = self.retry(ai="no", priority="High")["html"].split("<body", 1)[1]
        priority, retry, category = html.index("High priority"), html.index("Will not auto retry"), html.index("🔑 Authentication")
        self.assertLess(priority, retry)
        self.assertLess(retry, category)

    def test_the_technical_details_have_a_retry_row(self):
        html = en.main(sample(ai="no", detail="full"))["html"]
        self.assertIn(">Retry<", html)
        self.assertIn("Will not auto retry", html)
        self.assertNotIn("Reprocess input", html)

    def test_the_classic_header_keeps_its_old_retry_pill(self):
        html = self.retry(FakeHttp(azure=AZURE_YES), workato_api_token="t", azure_api_key="k", reprocess_check="yes",
                          auto_reprocess="yes", hero_layout="classic", hide_sections="signals")["html"]
        self.assertIn("Retry queued", html)
        self.assertNotIn("Will be auto retried", html)

    def test_the_time_pill_has_no_weekday_so_the_row_of_pills_fits_on_one_line(self):
        html = en.main(simple(ai="no"))["html"]
        self.assertIn(">19 Nov · 9:11 AM PST</span>", html)
        self.assertNotIn(">Thu 19 Nov", html)

    def test_pill_when_is_the_shortest_label(self):
        when = en.datetime(2026, 11, 19, 23, 42, tzinfo=en.timezone(en.timedelta(hours=-8), "PST"))
        self.assertEqual(en.pill_when(when), "19 Nov · 11:42 PM PST")
        self.assertEqual(en.short_when(when), "Thu 19 Nov · 11:42 PM PST")        # the footer and tiles keep the weekday

    def test_pills_are_tight_enough_for_five_to_share_a_row(self):
        self.assertIn("padding:4px 8px", en.pill("x", "#000000", "#FFFFFF"))
        self.assertIn("margin:0 4px 6px 0", en.pill("x", "#000000", "#FFFFFF"))

    def test_team_logo_follows_the_coursera_logo(self):
        html = self.hero(logo_url="https://example.com/c.png", team_logo_url=self.TEAM, team_name="IIS")
        self.assertLess(html.index("https://example.com/c.png"), html.index(self.TEAM))
        self.assertLess(html.index(self.TEAM), html.index("High priority"))     # in the header, not only the footer
        self.assertIn('alt="IIS"', html)

    def test_no_team_logo_means_no_divider_or_extra_image(self):
        html = self.hero(logo_url="https://example.com/c.png")
        self.assertNotIn("width:1px;height:26px", html)

    def test_priority_is_a_soft_pill_with_a_coloured_dot_not_a_dark_block(self):
        html = self.hero(priority="High")
        at = html.index("High priority")
        before = html[max(0, at - 520):at]
        sev = en.SEVERITY["HIGH"]
        self.assertIn("background:" + sev["soft"], before)
        self.assertIn("color:" + sev["color"], before)                     # the dot
        self.assertNotIn("background:" + sev["ink"], before)
        self.assertNotIn("color:#FFFFFF", before)
        self.assertNotIn(sev["emoji"], before)

    def test_the_facts_sit_beside_the_priority_and_category_even_with_their_sections_in_the_email(self):
        rows = [row(1), row(2)]
        out, _ = self.run_main(sample(workato_api_token="t", ai="no", detail="full", priority="High", reprocess_check="yes"),
                               FakeHttp(rows=rows))
        html = out["html"].split("<body", 1)[1]
        top = html[:html.index("Salesforce - AWS S3 UOL Application files Process - Function")]
        for fact in ("High priority", "Duplicate record", "in 90 days", "99.99% succeeded", "Will not auto retry", " PST"):
            self.assertIn(fact, top, fact)

    def test_pills_come_before_the_recipe_name(self):
        html = self.hero(priority="High")
        recipe = html.index("Salesforce - AWS S3 UOL Application files Process - Function")
        self.assertLess(html.index("High priority"), html.index(">19 Nov · 9:11 AM PST</span>"))      # the time pill
        self.assertLess(html.index(">19 Nov · 9:11 AM PST</span>"), recipe)

    def test_classic_header_is_the_previous_one(self):
        html = self.hero(priority="High", hero_layout="classic", team_logo_url=self.TEAM)
        self.assertIn("High priority · Recipe error alert", html)
        recipe = html.index("Salesforce - AWS S3 UOL Application files Process - Function")
        self.assertLess(recipe, html.index(">19 Nov · 9:11 AM PST</span>"))
        self.assertNotIn("width:1px;height:26px", html)

    def test_a_bad_layout_falls_back_to_new_with_a_warning(self):
        out = en.main(sample(ai="no", hero_layout="fancy"))
        self.assertTrue(any("hero_layout" in w for w in out["warnings"]))
        self.assertNotIn("High priority · Recipe error alert", out["html"])


class TestTechnicalDetails(Patched):
    CHILD = "https://app.workato.com/recipes/70000001/job/j-Master-1?child_job_id=j-Child-2"

    def details(self, **extra):
        """Just the technical details section of an email that has only that section."""
        html = self.run_main(simple(ai="no", history="no", sections="details", **extra))[0]["html"]
        return html[html.index("Technical details"):html.index("Automated alert")]

    def test_parent_child_and_recipe_ids_are_links(self):
        det = self.details(job_url=self.CHILD, calling_job_id="j-Child-2", calling_recipe_id=RECIPE_ID)
        self.assertIn('href="https://app.workato.com/recipes/70000001/job/j-Master-1"', det)      # parent (master)
        self.assertIn('href="{}"'.format(self.CHILD), det)                                         # the failing child job
        self.assertIn('href="https://app.workato.com/recipes/70000001"', det)                      # the recipe
        self.assertIn(">Parent job</td>", det)
        self.assertIn(">Child job</td>", det)

    def test_same_job_and_master_is_shown_once(self):
        det = self.details()
        self.assertNotIn("Parent job", det)
        self.assertNotIn("Child job", det)
        self.assertEqual(det.count('href="https://app.workato.com/recipes/70000001/job/{}"'.format(JOB)), 1)

    def test_two_short_blocks_not_one_tall_list(self):
        det = self.details()
        self.assertEqual(det.count('class="stack dcol"'), 2)       # side by side, stacked on a phone
        for title in (">Failure<", ">Workato<", ">Handling<"):
            self.assertIn(title.replace(">", "").replace("<", ""), det)
        self.assertNotIn("width:150px", det)

    def test_systems_are_skipped_when_where_it_broke_shows_them(self):
        full = en.main(simple(ai="no", history="no", detail="full"))["html"]
        det = full[full.index("Technical details"):full.index("Automated alert")]
        self.assertNotIn(">Source</td>", det)
        self.assertNotIn(">Target</td>", det)
        hidden = en.main(simple(ai="no", history="no", detail="full", hide_sections="flow"))["html"]
        det = hidden[hidden.index("Technical details"):hidden.index("Automated alert")]
        self.assertIn(">Source</td>", det)
        self.assertIn("WES Backend Service", det)

    def test_a_queued_retry_links_to_the_new_job(self):
        out, _ = self.run_main(simple(workato_api_token="t", azure_api_key="k", auto_reprocess="yes", reprocess_check="yes", sections="details"),
                               FakeHttp(azure=AZURE_YES))
        html = out["html"]
        det = html[html.index("Technical details"):html.index("Automated alert")]
        self.assertIn("Queued as", det)
        self.assertIn('href="https://app.workato.com/recipes/70000001/job/{}?child_job_id=j-NewRun-1"'.format(JOB), det)

    def test_values_are_escaped(self):
        det = self.details(file_name="<b>x</b>.csv", ErroredAction="<i>stop</i>")
        self.assertNotIn("<b>x</b>.csv", det)
        self.assertNotIn("<i>stop</i>", det)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;.csv", det)


class TestDeferred(Patched):
    """frequency / error_limit: the error is logged and nothing is emailed; the daily summary recipe decides when to email."""

    def run_deferred(self, fake=None, **extra):
        return self.run_main(simple(workato_api_token="t", azure_api_key="k", **extra),
                             fake or FakeHttp(azure=AZURE_YES))

    def test_logged_not_emailed(self):
        for extra in ({"frequency": 7}, {"error_limit": 20}, {"frequency": 7, "error_limit": 20}, {"frequency": 0}):
            out, _ = self.run_deferred(**extra)
            row = out["table_row"]
            self.assertEqual((out["action"], out["send_email"]), ("log_only", False), extra)
            self.assertEqual(row["status"], "Reprocessed", extra)        # Azure said yes and the retry was queued
            self.assertEqual((row["frequency"], row["error_limit"]),
                             (extra.get("frequency"), extra.get("error_limit")), extra)
            self.assertTrue(row["reprocess_flag"], extra)
        out, _ = self.run_deferred(frequency=7, auto_reprocess="no")      # no retry: just Created
        self.assertEqual((out["action"], out["send_email"], out["table_row"]["status"]), ("log_only", False, "Created"))

    def test_the_optional_email_switches_never_override_a_deferral(self):
        out, _ = self.run_deferred(frequency=7, email_when_reprocessable="yes")
        self.assertEqual((out["send_email"], out["table_row"]["status"]), (False, "Reprocessed"))
        out, _ = self.run_deferred(FakeHttp(azure=AZURE_YES, fail=["/repeat_jobs"]), frequency=7)
        self.assertTrue(out["reprocess_attempted"])
        self.assertFalse(out["reprocess_enqueued"])
        self.assertEqual((out["send_email"], out["table_row"]["status"]), (False, "Created"))

    def test_a_deferred_call_does_only_what_the_row_needs(self):
        out, fake = self.run_deferred(frequency=7)
        urls = [c[1] for c in fake.calls]
        # the job (master job id, is it a repeat), Azure (the decision), this master job's history (the retry guard), the
        # retry, and the row itself (a lookup by master job + the write): nothing the email needs
        self.assertEqual(len(urls), 6, urls)
        self.assertEqual(len(history_queries(fake)), 1)
        self.assertEqual(len(fake.urls("openai.azure.com")), 1)
        self.assertEqual(len(fake.urls("/repeat_jobs")), 1)
        self.assertEqual([c for c in fake.urls("data-tables") if c[2] and "$and" not in (c[2].get("where") or {})
                          and "Master Job ID" not in (c[2].get("where") or {}) and "document" not in c[2]], [])   # no cross-recipe view
        self.assertEqual((out["row_action"], out["row_logged"]), ("inserted", True))
        self.assertEqual((out["html"], out["look_used"], out["sections_rendered"]), ("", "log_only", []))
        self.assertTrue(out["subject"])
        self.assertEqual(out["master_job_id"], JOB)

    def test_always_render_builds_the_email_anyway(self):
        out, fake = self.run_deferred(frequency=7, always_render="yes", detail="full")
        self.assertGreater(len(fake.calls), 2)
        self.assertIn("Technical details", out["html"])
        self.assertEqual((out["action"], out["send_email"]), ("log_only", False))

    def test_the_repeat_guard_still_reads_the_log(self):
        rows = [row(0, job="j-Other", master=JOB, count=1, status="Reprocessed")]
        out, fake = self.run_deferred(FakeHttp(azure=AZURE_YES, rows=rows), frequency=7, auto_reprocess="yes", reprocess_check="yes")
        self.assertTrue(fake.urls("data-tables"))
        self.assertEqual(fake.urls("/repeat_jobs"), [])
        self.assertIn("already repeated", out["reprocess_error"])

    def test_the_details_say_when_it_would_notify(self):
        out, _ = self.run_deferred(frequency=7, error_limit=20, always_render="yes", sections="details")
        html = out["html"]
        self.assertIn("every 7 days or over 20 errors", html[html.index("Technical details"):html.index("Automated alert")])

    def test_a_crash_still_only_logs_a_deferred_call(self):
        original = en.build_email
        en.build_email = lambda *args: 1 / 0
        try:
            out, _ = self.run_deferred(frequency=7, always_render="yes", auto_reprocess="no")
        finally:
            en.build_email = original
        self.assertEqual((out["action"], out["send_email"], out["table_row"]["status"]), ("log_only", False, "Created"))
        self.assertIn("ZeroDivisionError", out["error"])


class TestTableReading(unittest.TestCase):
    """Which column of a failed-records table is the error text, and which columns hold ids."""

    def analyse(self, names, values):
        cols = [{"i": i + 1, "name": n, "width": None} for i, n in enumerate(names)]
        rows = [{i + 1: {"value": v, "url": "", "bold": "", "color": ""} for i, v in enumerate(vals)} for vals in values]
        return en.analyze_records(cols, rows, en.category_rules({}))

    def test_a_message_column_beats_an_error_date(self):
        rec = self.analyse(["Error Date ", "Error Message", "Job Details"],
                           [["2026-11-19 02:02:09", "404 Not Found", "view job"]] * 3)
        self.assertEqual(rec["err_col"], 2)
        self.assertEqual(rec["categories"]["not_found"], 3)

    def test_longer_text_wins_between_two_error_columns(self):
        rec = self.analyse(["Recipe", "Errors", "Most common error", "Last seen"],
                           [["A sync", "12", "Timeout: code execution exceeded 90 seconds", "2026-07-30"]] * 2)
        self.assertEqual(rec["err_col"], 3)

    def test_only_id_like_columns_are_checked_for_repeats(self):
        rec = self.analyse(["Error Date", "Error Message", "Job Details"],
                           [["2026-11-19 02:0%d" % i, "Internal error", "view job"] for i in range(4)])
        self.assertEqual(rec["duplicates"], {})                  # the message and 'view job' repeat, but they are not ids
        rec = self.analyse(["Application Id", "Error Message"],
                           [["240697817_X", "Duplicate"]] * 2 + [["240709969_X", "Duplicate"]])
        self.assertEqual(len(rec["duplicates"][1]), 1)

    def test_a_column_of_id_looking_values_counts_even_without_an_id_name(self):
        rec = self.analyse(["Record", "Reason"], [["a0kPJ00000QcBWXYA3", "Duplicate"]] * 2 + [["a0kPJ00000ZZZZZYA3", "x"]])
        self.assertIn(1, rec["id_cols"])


class DevFake(FakeHttp):
    """Version 1 was written by a contractor, version 2 by the developer, version 3 by a later editor."""
    AUTHORS = {1: ("Contractor", "c@agency.com"), 2: ("Dev One", "dev.one@coursera.org"), 3: ("Later Editor", "ed@coursera.org")}

    def __call__(self, method, url, headers, payload=None, timeout=12):
        if "exclude_code=yes" in url:
            self.calls.append((method, url, payload, dict(headers or {})))
            version = int(url.split("version_no=")[1]) if "version_no=" in url else 3
            name, email = self.AUTHORS[version]
            return {"version_no": 3, "version_author_name": name, "version_author_email": email}, None
        return FakeHttp.__call__(self, method, url, headers, payload, timeout)


class TestDeveloper(Patched):
    def details(self, fake=None, **extra):
        data = simple(workato_api_token="t", ai="no", history="no", sections="details", **extra)
        out, fake = self.run_main(data, fake or DevFake())
        html = out["html"]
        return out, fake, html[html.index("Technical details"):html.index("Automated alert")]

    def test_off_by_default_and_no_calls(self):
        out, fake, det = self.details()
        self.assertEqual(fake.urls("exclude_code"), [])
        self.assertNotIn(">Developer</td>", det)
        self.assertEqual(out["developer_name"], "")

    def test_the_first_company_author_is_the_developer(self):
        out, fake, det = self.details(show_developer="yes")
        self.assertEqual(len(fake.urls("exclude_code")), 3)                # latest, version 1 (contractor), version 2
        self.assertIn(">Developer</td>", det)
        self.assertIn("Dev One", det)
        self.assertIn('href="mailto:dev.one@coursera.org"', det)
        self.assertNotIn("Contractor", det)
        self.assertEqual((out["developer_name"], out["developer_email"]), ("Dev One", "dev.one@coursera.org"))

    def test_no_token_or_no_company_author_is_only_a_warning(self):
        out = en.main(simple(ai="no", history="no", sections="details", show_developer="yes"))
        self.assertTrue(out["ok"])
        self.assertTrue(any("developer skipped" in w for w in out["warnings"]))

        class Nobody(DevFake):
            AUTHORS = {1: ("A", "a@agency.com"), 2: ("B", "b@agency.com"), 3: ("C", "c@agency.com")}
        out, _, det = self.details(Nobody(), show_developer="yes")
        self.assertNotIn(">Developer</td>", det)
        self.assertTrue(any("no version of the recipe" in w for w in out["warnings"]))

    def test_not_looked_up_when_technical_details_are_not_in_the_email(self):
        data = simple(workato_api_token="t", ai="no", history="no", show_developer="yes", detail="brief")
        _, fake = self.run_main(data, DevFake())
        self.assertEqual(fake.urls("exclude_code"), [])


class TestSectionNames(Patched):
    def test_sub_sections_can_be_hidden(self):
        rows = [row(1), row(2)]
        out, _ = self.run_main(simple(workato_api_token="t", ai="no", show_sections="job,details"), FakeHttp(rows=rows))
        html = out["html"]
        self.assertIn("Recent similar failures", html)
        self.assertIn("Likely cause", html)
        out, _ = self.run_main(simple(workato_api_token="t", ai="no", show_sections="job,details",
                                      hide_sections="history.recent, story.causes, job.recent, details.handling"),
                               FakeHttp(rows=rows))
        html = out["html"]
        for gone in ("Recent similar failures", "Likely cause", "Last 10 jobs", ">Logged as</td>"):
            self.assertNotIn(gone, html)
        self.assertIn("Most common errors in this recipe", html)             # the other parts stay
        self.assertIn("Next steps", html)

    def test_unknown_names_are_reported(self):
        out = en.main(simple(ai="no", history="no", hide_sections="history.nonsense,bogus"))
        self.assertTrue(any("unknown names in hide_sections" in w for w in out["warnings"]))

    def test_the_hints_list_every_name(self):
        with open(os.path.join(HERE, "error_notification_input_schema.json"), encoding="utf-8") as handle:
            hints = {f["name"]: f.get("hint", "") for f in json.load(handle)}
        for field in ("sections", "show_sections", "hide_sections"):
            for name, _ in en.SECTION_HELP:
                self.assertIn(name, hints[field], (field, name))
        for sub in en.SUBSECTIONS:
            self.assertIn(sub, hints["hide_sections"], sub)
        for level in en.DETAIL_PRESETS:
            self.assertIn(level, hints["detail"])
        self.assertEqual({n for n, _ in en.SECTION_HELP}, set(en.DEFAULT_SECTIONS))


class TestButtons(Patched):
    def test_buttons_are_light_and_carry_their_own_border(self):
        out = en.main(sample(ai="no", error_file_url="https://example.com/f.csv", workato_api_token="t"))
        html = out["html"]
        row = html[html.index("View job details"):html.index("Automated alert")]
        for label in ("View job details", "Open recipe", "Error file"):
            self.assertIn(label, html)
        self.assertNotIn("background:#0056D2", row)                  # no solid brand-blue button
        self.assertNotIn("color:#FFFFFF", row)
        start = html.rindex("<a ", 0, html.index("View job details"))
        self.assertIn("background:#EEF4FF;border:1px solid #D4E1FB;border-radius:8px", html[start:start + 400])
        self.assertNotIn("display:inline-table", html)               # no table cell around a button: it showed a square outline


class TestReference(Patched):
    def test_the_reference_is_in_the_footer_and_the_details_not_the_header(self):
        out = en.main(sample(ai="no", detail="full"))
        html = out["html"].split("<body", 1)[1]
        ref = "#" + out["error_signature"]
        self.assertEqual(html.count(ref), 2)                                  # the Reference row and the footer line
        self.assertGreater(html.index(ref), html.index("Salesforce - AWS S3 UOL Application files Process - Function"))
        for layout in ("new", "classic"):
            top = en.main(sample(ai="no", hero_layout=layout))["html"].split("Error message", 1)[0]
            self.assertNotIn(ref, top, layout)


class TestErrorBanner(Patched):
    def body(self, **extra):
        return en.main(sample(ai="no", **extra))["html"].split("<body", 1)[1]

    def test_a_red_error_alert_strip_is_on_top_by_default(self):
        for layout in ("new", "classic"):
            html = self.body(hero_layout=layout)
            self.assertIn("Error alert", html, layout)
            self.assertIn("&#10005;", html, layout)                           # the cross
            self.assertLess(html.index("Error alert"), html.index("coursera"), layout)       # above the logos
            self.assertLess(html.index("Error alert"), html.index("Error message"), layout)

    def test_it_can_be_switched_off(self):
        for layout in ("new", "classic"):
            html = self.body(error_banner="no", hero_layout=layout)
            self.assertNotIn("Error alert", html, layout)
            self.assertNotIn("&#10005;", html, layout)

    def test_it_stays_when_the_header_section_is_hidden_and_never_in_the_old_look(self):
        self.assertIn("Error alert", self.body(hide_sections="hero"))
        self.assertNotIn("Error alert", self.body(hide_sections="hero", error_banner="no"))
        self.assertNotIn("&#10005;", en.main(sample(look="old"))["html"])


class TestHover(Patched):
    def html(self, **extra):
        data = sample(workato_api_token="t", ai="no", detail="full", show_sections="job,details,kpis,flow", **extra)
        rows = [row(1, message="Duplicate external id", recipe_id="70000001"), row(2, message="Duplicate external id", recipe_id="70000001")]
        return self.run_main(data, FakeHttp(rows=rows))[0]["html"]

    def test_every_section_has_a_hover_class_and_the_rules_are_in_the_email(self):
        html = self.html()
        body = html.split("<body", 1)[1]
        for cls in ("hv-err", "hv-banner", "hv-pill", "hv-lift", "hv-trow", "hv-row", "hv-card", "hv-cell", "hv-bar",
                    "hv-link", "hv-btn"):
            self.assertIn(cls, body, cls)
        style = html.split("<style>", 1)[1].split("</style>", 1)[0]
        plain_rules = style.split("@media (hover:hover)")[0]          # before any media block
        for rule in (".hv-err:hover", ".hv-card:hover", ".hv-lift:hover", ".hv-trow:hover", ".hv-trow:hover td",
                     ".hv-btn:hover", ".hv-bar:hover", ".hv-banner:hover"):
            self.assertIn(rule, plain_rules, rule)                       # the effects do not depend on a media query
        for rule in ("@media (hover:hover)", "prefers-reduced-motion", "translateY"):
            self.assertIn(rule, style, rule)
        self.assertNotIn(":hover,", style)                               # one selector per rule

    def test_the_error_box_has_no_coloured_left_edge(self):
        html = self.html()
        box = html[html.index('class="hv-err"'):]
        box = box[:box.index(">")]
        self.assertNotIn("border-left", box)

    def test_every_hover_changes_a_colour_or_an_opacity_not_only_a_shadow(self):
        # Gmail showed the tinted rows and cells but not the shadow-only effects (the header and the error box), so each
        # hover class has to change a background, an opacity or a text decoration; the shadow is only extra.
        style = self.html().split("<style>", 1)[1].split("</style>", 1)[0]
        plain_rules = style.split("@media (hover:hover)")[0]
        seen = set()
        for selector, body in re.findall(r"(\.hv-[a-z]+:hover[^{]*)\{([^}]*)\}", plain_rules):
            if selector.endswith("td:first-child"):
                continue                                   # the blue bar on a row: the row itself is tinted too
            seen.add(selector.split(":")[0])
            self.assertTrue(re.search(r"background|opacity|text-decoration", body), selector)
        for cls in (".hv-err", ".hv-card", ".hv-lift", ".hv-cell", ".hv-row", ".hv-trow", ".hv-pill", ".hv-btn",
                    ".hv-bar", ".hv-link", ".hv-banner"):
            self.assertIn(cls, seen, cls)

    def test_the_error_box_hovers_in_its_own_severity_colour(self):
        html = self.html(priority="Critical")
        self.assertNotIn("__", html.split("<style>", 1)[1].split("</style>", 1)[0])    # no placeholder is left
        crit = re.search(r"\.hv-err:hover\{background:(#[0-9A-F]{6})", html).group(1)
        low = re.search(r"\.hv-err:hover\{background:(#[0-9A-F]{6})", self.html(priority="Low")).group(1)
        self.assertNotEqual(crit, low)                     # the tint follows the severity
        self.assertNotEqual(crit, en.SEVERITY["CRITICAL"]["soft"])       # and is deeper than the resting colour

    def test_the_big_white_header_area_does_not_react_only_its_pills_do(self):
        html = self.html()
        self.assertNotIn("hv-hero", html)
        style = html.split("<style>", 1)[1].split("</style>", 1)[0]
        header = html[html.index("coursera"):]
        header = header[:header.index('<tr><td class="px" style="padding:10px 32px')]   # up to the intro row
        pills = re.findall(r'class="hv-pill( hvp-[0-9A-F]{6}-[0-9A-F]{6})?"', header)
        self.assertGreaterEqual(len(pills), 4)             # priority, category, records / repeats, time ...
        self.assertTrue(all(pills))                        # every pill carries its own hover colour

    def test_each_pill_turns_a_deeper_shade_of_its_own_colour(self):
        html = self.html(priority="High")
        style = html.split("<style>", 1)[1].split("</style>", 1)[0]
        plain_rules = style.split("@media (hover:hover)")[0]
        used = set(re.findall(r"hvp-([0-9A-F]{6})-([0-9A-F]{6})", html.split("<body", 1)[1]))
        self.assertGreaterEqual(len(used), 3)              # several colours of pill in one email
        for bg, fg in used:
            rule = re.search(r"\.hvp-%s-%s:hover\{background:(#[0-9A-F]{6})!important;border-color:(#[0-9A-F]{6})" % (bg, fg), plain_rules)
            self.assertTrue(rule, (bg, fg))
            self.assertNotEqual(rule.group(1), "#" + bg)   # the colour really changes
            self.assertEqual(rule.group(1), en.mix_color("#" + bg, "#" + fg, 0.14))     # towards its own text colour
        # the soft priority pill stays orange-ish for High, it does not become the blue row colour
        sev = en.SEVERITY["HIGH"]
        got = re.search(r"\.hvp-%s-%s:hover\{background:(#[0-9A-F]{6})" % (sev["soft"][1:].upper(), sev["ink"][1:].upper()), plain_rules).group(1)
        self.assertGreater(int(got[1:3], 16), int(got[5:7], 16))          # more red than blue

    def test_a_pill_with_a_colour_name_still_gets_a_hover(self):
        pill = en.pill("x", "red", "pink")
        self.assertIn('class="hv-pill"', pill)
        self.assertEqual(en.pill_hover_css(pill), "")
        self.assertIn(".hv-pill:hover{background:#EEF4FF", en.hover_css({"hover_row_color": "#EEF4FF"}, en.SEVERITY["HIGH"]))

    def test_mixing_colours(self):
        self.assertEqual(en.mix_color("#FFFFFF", "#000000", 0.5), "#808080")
        self.assertEqual(en.mix_color("#fff", "#000", 0), "#FFFFFF")
        self.assertEqual(en.mix_color("red", "#000000", 0.5), "red")       # a colour name can't be blended

    def test_the_row_colour_can_match_the_health_check_mail(self):
        blue = self.html()
        self.assertIn(".hv-trow:hover{background:#EEF4FF!important}", blue)
        green = self.html(hover_row_color="#ddffdd")
        self.assertIn(".hv-trow:hover{background:#ddffdd!important}", green)
        self.assertIn(".hv-trow:hover td{background-color:#ddffdd!important}", green)
        self.assertNotIn("#EEF4FF!important", green)
        self.assertIn("#EEF4FF!important", self.html(hover_row_color="not a colour!"))      # a bad value falls back

    def test_no_external_stylesheet(self):
        self.assertNotIn("<link", self.html())
        self.assertNotIn("w3.css", self.html())

    def test_it_can_be_switched_off(self):
        html = self.html(hover_effects="no")
        self.assertNotIn(":hover", html)
        self.assertIn("@media only screen and (max-width:640px)", html)       # the phone rules stay

    def test_the_old_look_has_no_hover_rules(self):
        self.assertNotIn(".hv-card:hover", en.main(sample(look="old"))["html"])


class TestExtraRules(unittest.TestCase):
    def test_every_extra_rule_has_a_label_through_its_category(self):
        rules = en.category_rules({})
        for key, _, _, _ in en.EXTRA_RULES:
            label, icon = en.category_info(key, rules)
            self.assertTrue(label and icon, key)
            self.assertNotEqual(label, en.UNKNOWN[1], key)

    def test_the_rate_limit_of_the_screenshot_is_not_unclassified_and_the_playbook_knows_the_new_kind(self):
        out = en.main({"to_email_address": "a@example.com", "subject": "x", "recipe_name": "Sync", "priority": "Medium",
                       "job_url": "https://app.workato.com/recipes/1/job/j-X", "sourceSystem": "SFDC_Services",
                       "targetSystem": "Braze", "ai": "no", "now": NOW,
                       "error_details": "You have exceeded your limit of 12000 requests per three seconds."})
        self.assertEqual((out["error_category"], out["error_category_label"]), ("rate_limit", "Rate / concurrency limit"))
        self.assertNotIn("Unclassified", out["html"])
        multi = en.main({"to_email_address": "a@example.com", "subject": "x", "recipe_name": "Sync", "priority": "Medium",
                         "job_url": "https://app.workato.com/recipes/1/job/j-X", "targetSystem": "Salesforce", "ai": "no",
                         "now": NOW, "error_details": "More than 1 record matched the given criteria and could not be updated."})
        self.assertEqual(multi["error_category"], "multi_match")
        self.assertIn("more than one record", multi["functional_summary"].lower())     # its own playbook text, not the generic one

    def test_the_categories_themselves_are_untouched(self):
        self.assertEqual([k for k, _, _, _ in en.CATEGORIES][:3], ["duplicate", "converted_lead", "record_lock"])


class TestFailingNode(Patched):
    """Which box of 'Where it broke' is marked failed: a REST / HTTP step is a call to a third-party system, not Workato."""
    RATE = ("You have exceeded your limit of 12000 requests per three seconds. Please contact your account executive "
            "to increase your limit. If you do not have their info, you may contact Braze directly.")

    def node(self, **extra):
        inp = {"to_email_address": "a@example.com", "subject": "x", "recipe_name": "Marketing-SalesforceService To Braze User Sync",
               "job_url": "https://app.workato.com/recipes/43345417/job/j-X-CD", "priority": "Medium",
               "sourceSystem": "SFDC_Services", "targetSystem": "Braze", "error_details": self.RATE}
        inp.update(extra)
        cfg, _ = en.settings(inp)
        ctx = en.build_context(inp, cfg, en.current_time(cfg, en.get_tz(cfg["timezone"])))
        return en.failing_node(ctx)

    def test_no_errored_app_but_the_error_names_the_target(self):
        self.assertEqual(self.node(), "target")                              # the Braze rate limit of the screenshot

    def test_a_rest_step_is_the_target_not_workato(self):
        for app in ("rest", "REST", "http", "HTTP client", "rest_api"):
            self.assertEqual(self.node(ErroredApp=app, ErroredAction="make_request_v2", stepNumber="7"), "target", app)

    def test_a_rest_step_with_no_name_in_the_error_still_points_at_the_target(self):
        self.assertEqual(self.node(ErroredApp="rest", error_details="429 Too Many Requests"), "target")
        self.assertEqual(self.node(ErroredApp="rest", error_details="Something odd happened"), "target")

    def test_a_rest_step_whose_error_only_names_the_source_is_the_source(self):
        self.assertEqual(self.node(ErroredApp="rest", error_details="Salesforce answered 401 Unauthorized"), "source")
        self.assertEqual(self.node(ErroredApp="rest", error_details="SFDC session expired"), "source")

    def test_both_named_means_the_target(self):
        self.assertEqual(self.node(ErroredApp="rest", error_details="Failed to sync Salesforce leads to Braze"), "target")

    def test_a_named_connector_is_still_matched_to_its_system(self):
        self.assertEqual(self.node(ErroredApp="braze"), "target")
        self.assertEqual(self.node(ErroredApp="salesforce", error_details="boom"), "source")

    def test_workato_own_apps_stay_workato_even_if_the_text_names_a_system(self):
        self.assertEqual(self.node(ErroredApp="python"), "workato")
        self.assertEqual(self.node(ErroredApp="workato_variable"), "workato")

    def test_a_formula_error_without_an_app_is_workato_even_if_it_names_the_target(self):
        self.assertEqual(self.node(error_details="undefined method 'id' for nil: Braze field mapping"), "workato")
        self.assertEqual(self.node(error_details="Braze external id must be present"), "workato")

    def test_a_remote_kind_of_error_with_no_name_points_at_the_target(self):
        self.assertEqual(self.node(error_details="rate limit exceeded"), "target")
        self.assertEqual(self.node(error_details="401 Unauthorized"), "target")

    def test_nothing_to_go_on_stays_workato(self):
        self.assertEqual(self.node(error_details="Something odd happened"), "workato")
        self.assertEqual(self.node(error_details="Something odd happened", targetSystem=""), "workato")

    def test_the_step_title_can_name_the_system(self):
        inp = {"error_details": "boom", "ErroredApp": "rest", "sourceSystem": "SFDC_Services", "targetSystem": "Braze",
               "recipe_name": "x", "job_url": "https://app.workato.com/recipes/1/job/j-X"}
        cfg, _ = en.settings(inp)
        ctx = en.build_context(inp, cfg, en.current_time(cfg, en.get_tz(cfg["timezone"])))
        ctx.recipe_info = {"step": {"title": "Get leads from Salesforce", "comment": ""}}
        self.assertEqual(en.failing_node(ctx), "source")

    def test_system_in_text(self):
        self.assertTrue(en.system_in_text("SFDC_Services", "Salesforce says no"))
        self.assertTrue(en.system_in_text("SFDC_Services", "the SFDC org"))
        self.assertTrue(en.system_in_text("SalesforceService", "Salesforce says no"))
        self.assertTrue(en.system_in_text("NS", "NetSuite is down"))
        self.assertFalse(en.system_in_text("SFDC_Services", "some services failed"))      # 'Services' alone says nothing
        self.assertFalse(en.system_in_text("Braze", "Brazen behaviour"))                  # whole words only
        self.assertTrue(en.system_in_text("Braze", "Braze's API said no"))
        self.assertTrue(en.system_in_text("Braze", "SalesforceService and Braze"))
        self.assertFalse(en.system_in_text("", "anything"))

    def test_the_failed_here_tag_lands_in_the_target_box(self):
        out = en.main({"to_email_address": "a@example.com", "subject": "x", "recipe_name": "Sync", "priority": "Medium",
                       "job_url": "https://app.workato.com/recipes/1/job/j-X", "sourceSystem": "SFDC_Services",
                       "targetSystem": "Braze", "error_details": self.RATE, "ai": "no", "detail": "full", "now": NOW})
        html = out["html"]
        self.assertEqual(html.count("FAILED HERE"), 1)
        self.assertGreater(html.index("FAILED HERE"), html.index(">Target<"))      # after the Target label, in its box


class TestAutoRetry(Patched):
    """auto_reprocess (yes by default) is the one switch: only Azure decides which errors a re-run would fix, and the step
    reruns those. What nobody is retrying goes to a person by email."""
    RATE = "You have exceeded your limit of 12000 requests per three seconds."            # a retryable kind
    AUTH = "Salesforce connection is broken. Please refresh"                              # not a retryable kind

    def go(self, message=None, fake=None, **extra):
        data = simple(workato_api_token="t", ai="no", reprocess_policy="rules", error_details=message or self.RATE)
        data.update(extra)
        return self.run_main(data, fake or FakeHttp())

    def test_it_decides_and_reruns_by_default(self):
        out, fake = self.go()
        self.assertEqual((out["reprocessable"], out["reprocess_source"]), (True, "rules"))
        self.assertTrue(out["reprocess_enqueued"])
        self.assertEqual((out["action"], out["send_email"], out["table_row"]["status"]), ("log_only", False, "Reprocessed"))
        self.assertEqual(len(fake.urls("/repeat_jobs")), 1)

    def test_a_not_retryable_error_is_left_to_a_person(self):
        out, fake = self.go(message=self.AUTH)
        self.assertEqual((out["reprocessable"], out["send_email"], out["action"]), (False, True, "notify"))
        self.assertEqual(fake.urls("/repeat_jobs"), [])

    def test_a_retry_a_guard_stopped_is_emailed_not_dropped(self):
        out, fake = self.go(max_auto_repeats=0)
        self.assertTrue(out["reprocessable"])
        self.assertFalse(out["reprocess_enqueued"])
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))
        self.assertEqual(fake.urls("/repeat_jobs"), [])

    def test_a_retry_that_failed_again_is_emailed_and_not_retried_again(self):
        out, fake = self.go(is_Repeated=True)
        self.assertEqual((out["action"], out["send_email"], out["table_row"]["status"]), ("notify", True, "Failed Again"))
        self.assertIn("Retry failed again", out["html"])
        self.assertEqual(fake.urls("/repeat_jobs"), [])

    def test_a_failed_repeat_call_is_still_emailed(self):
        out, _ = self.go(fake=FakeHttp(fail=["/repeat_jobs"]))
        self.assertTrue(out["reprocess_attempted"])
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))

    def test_auto_reprocess_no_stops_everything(self):
        out, fake = self.go(auto_reprocess="no")
        self.assertEqual((out["reprocessable"], out["reprocess_source"], out["action"], out["send_email"]),
                         (False, "off", "notify", True))
        self.assertEqual(fake.urls("/repeat_jobs"), [])

    def test_a_job_is_repeated_at_most_max_auto_repeats_times(self):
        rows = [row(1, master=JOB, status="Reprocessed", count=1)]          # this master job was already reprocessed once
        out, fake = self.go(fake=FakeHttp(rows=rows))
        self.assertFalse(out["reprocess_enqueued"])
        self.assertEqual(fake.urls("/repeat_jobs"), [])
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))

    def test_a_deferred_call_is_still_only_logged(self):
        out, _ = self.go(is_Repeated=True, frequency=7)
        self.assertEqual((out["action"], out["send_email"]), ("log_only", False))

    def test_the_callers_reprocess_input_changes_nothing(self):
        for value in (True, False, "false", ""):
            out, fake = self.go(reprocess=value)
            self.assertTrue(out["reprocess_enqueued"], value)
            self.assertEqual(len(fake.urls("/repeat_jobs")), 1, value)


class TestAzureFailure(Patched):
    """A failing Azure call never stops the email: it is captured, and the alert is built from the playbook."""
    RATE = "Concurrent request limit exceeded. Request blocked."

    def run_azure(self, fake, **extra):
        data = simple(workato_api_token="t", azure_api_key="k", ai="yes")
        data.update(extra)
        return self.run_main(data, fake)

    def assert_email_went_out(self, out):
        self.assertTrue(out["ok"])
        self.assertEqual((out["send_email"], out["action"], out["look_used"]), (True, "notify", "new"))
        self.assertIn("Lead Sync - RealTime", out["html"])
        self.assertEqual(out["explanation_source"], "playbook")
        self.assertTrue(out["ai_error"].startswith("azure"), out["ai_error"])
        self.assertIn(out["ai_error"], out["warnings"])
        self.assertIn("AI analysis unavailable", out["html"])               # the story section says so, quietly
        self.assertFalse([w for w in out["warnings"] if "building the email failed" in w])

    def test_azure_down(self):
        out, _ = self.run_azure(FakeHttp(azure=None))
        self.assert_email_went_out(out)

    def test_azure_answering_with_an_http_error(self):
        out, _ = self.run_azure(FakeHttp(fail=["openai"]))
        self.assert_email_went_out(out)
        self.assertIn("500", out["ai_error"])

    def test_azure_answering_with_something_that_is_not_json(self):
        out, _ = self.run_azure(BadAzureHttp({"choices": [{"message": {"content": "sorry, I cannot help with that"}}]}))
        self.assert_email_went_out(out)
        self.assertIn("not JSON", out["ai_error"])

    def test_azure_answering_with_an_unexpected_shape(self):
        out, _ = self.run_azure(BadAzureHttp({"unexpected": True}))
        self.assert_email_went_out(out)
        self.assertIn("unexpected response shape", out["ai_error"])

    def test_an_exception_while_building_the_request_is_captured_too(self):
        original = en.ai_facts

        def boom(ctx):
            raise ValueError("boom")
        en.ai_facts = boom
        try:
            out, _ = self.run_azure(FakeHttp(azure=AZURE_YES))
        finally:
            en.ai_facts = original
        self.assert_email_went_out(out)
        self.assertIn("ValueError: boom", out["ai_error"])

    def test_the_data_table_row_is_still_logged(self):
        out, fake = self.run_azure(FakeHttp(azure=None))
        self.assertEqual((out["row_action"], len(fake.writes)), ("inserted", 1))

    def test_the_reprocess_decision_is_no_and_the_error_is_emailed(self):
        out, fake = self.run_azure(FakeHttp(azure=None), error_details=self.RATE)
        self.assertEqual((out["reprocessable"], out["reprocess_source"]), (False, "none"))
        self.assertEqual((out["action"], out["send_email"]), ("notify", True))
        self.assertEqual(fake.urls("/repeat_jobs"), [])
        self.assertTrue([w for w in out["warnings"] if "not retried" in w])

    def test_a_working_azure_leaves_no_trace(self):
        out, _ = self.run_azure(FakeHttp(azure=AZURE_YES))
        self.assertEqual((out["ai_error"], out["explanation_source"]), ("", "ai"))
        self.assertNotIn("AI analysis unavailable", out["html"])

    def test_no_key_is_not_a_failure(self):
        out = en.main(simple(ai="yes"))
        self.assertEqual(out["ai_error"], "")
        self.assertNotIn("AI analysis unavailable", out["html"])


class TestJobCard(Patched):
    """'Workato job & recipe' has the look of the technical details: titled blocks with a line under the title, two columns."""

    def job_section(self):
        fake = FakeHttp(jobs={"items": [{"status": "succeeded"}] * 4},
                        job={"status": "succeeded", "master_job_id": JOB, "is_repeat": False, "started_at": "2026-11-19T09:10:00-08:00",
                             "completed_at": "2026-11-19T09:10:01-08:00", "lines": [{"recipe_line_number": 1, "adapter_name": "http",
                                                                                        "adapter_operation": "x", "line_stat": {"total": 0.2}}]})
        out, _ = self.run_main(simple(workato_api_token="t", ai="no", detail="full", show_editor="yes", log_row="no"), fake)
        html = out["html"]
        return html[html.index("Workato job &amp; recipe"):html.index("Technical details")], html

    def test_job_and_recipe_are_titled_blocks_with_a_line_under_the_title(self):
        section, _ = self.job_section()
        for title in ("Job", "Recipe"):
            at = section.index(">{}</div>".format(title))
            self.assertIn("text-transform:uppercase", section[at - 260:at])
            self.assertIn("border-bottom:1px solid " + en.LINE, section[at - 260:at])
        self.assertEqual(section.count("border-bottom:1px solid " + en.LINE), 3)        # Job, Recipe and "Last N jobs"
        self.assertIn('class="stack dcol"', section)                                    # the same two columns as the details

    def test_the_key_column_is_still_only_as_wide_as_its_keys(self):
        section, _ = self.job_section()
        self.assertIn('width="1%"', section)
        self.assertIn("white-space:nowrap", section)
        self.assertNotIn('width="36%"', section)

    def test_the_technical_details_keep_their_own_block_style(self):
        _, html = self.job_section()
        details = html[html.index("Technical details"):]
        self.assertIn('width="36%"', details)
        self.assertIn("border-bottom:1px solid " + en.LINE, details)


class TestKeyValueRows(unittest.TestCase):
    def test_the_label_column_is_only_as_wide_as_its_labels(self):
        html = en.kv_rows([("Started", "Fri 20 Nov"), ("Slowest step", "Line 3")])
        self.assertEqual(html.count('width="1%"'), 2)
        self.assertEqual(html.count("white-space:nowrap"), 2)
        self.assertNotIn("width:110px", html)
        self.assertIn("padding:6px 10px 6px 0", html)                       # the whole gap between a label and its value

    def test_a_very_long_label_keeps_a_fixed_column_that_wraps(self):
        html = en.kv_rows([("A label that is far too long to sit on one line", "x")], label_width=150)
        self.assertIn('width="150"', html)
        self.assertNotIn("white-space:nowrap", html)

    def test_empty_values_are_left_out(self):
        self.assertEqual(en.kv_rows([("A", ""), ("B", None)]), "")
        self.assertEqual(en.kv_rows([("A", ""), ("B", "x")]).count("<tr"), 1)


class TestRunHealth(Patched):
    """The recipes catch their errors with an error handler, so Workato calls every job succeeded. The error log (job ids)
    says which recent runs really hit an error; the tiles, the signal and the job card use that."""

    def items(self, n=10, started=None, **status):
        out = [{"id": JOB, "status": "pending"}] + [{"id": "j-r{}".format(i), "status": status.get("api", "succeeded")} for i in range(1, n)]
        for item in out:
            if started:
                item["started_at"] = started
        return {"items": out}

    def run_full(self, rows=None, jobs=None, **extra):
        fake = FakeHttp(rows=rows or [], jobs=jobs if jobs is not None else self.items())
        return self.run_main(simple(workato_api_token="t", ai="no", detail="full", log_row="no", **extra), fake)[0]

    def test_a_job_with_a_logged_error_is_marked_although_workato_says_succeeded(self):
        out = self.run_full([row(2, job="j-r2"), row(4, job="j-r5")])
        self.assertEqual((out["recent_jobs_checked"], out["recent_jobs_failed"]), (10, 3))      # j-r2, j-r5 and this run
        self.assertIn("Runs with errors", out["html"])
        self.assertIn(">3/10<", out["html"])
        self.assertIn("an error was logged for this run", out["html"])                          # the square's hover text
        self.assertIn("3 with an error · 7 clean", out["html"])

    def test_the_original_job_of_a_retry_counts_too(self):
        out = self.run_full([row(2, job="j-retry", master="j-r3")])
        self.assertEqual(out["recent_jobs_failed"], 2)                                          # j-r3 (the master) and this run

    def test_a_clean_recipe_says_only_this_run_failed(self):
        out = self.run_full([])
        self.assertIn(">1/10<", out["html"])
        self.assertIn("only this one", out["html"])
        self.assertTrue(any("Otherwise healthy: 9 of the last 10 runs ran clean" in sig for sig in out["signals"]), out["signals"])

    def test_many_runs_with_errors_is_a_warning_signal(self):
        out = self.run_full([row(d, job="j-r{}".format(d)) for d in range(1, 5)])
        self.assertEqual(out["recent_jobs_failed"], 5)
        self.assertTrue(any("5 of the last 10 runs" in sig and "error handler" in sig for sig in out["signals"]), out["signals"])
        self.assertFalse(any("Otherwise healthy" in sig for sig in out["signals"]))

    def test_no_job_ids_means_nothing_is_marked_and_there_is_no_tile(self):
        out = self.run_full([row(2, job="j-r2")], jobs={"items": [{"status": "succeeded"}] * 9 + [{"status": "failed"}]})
        self.assertEqual((out["recent_jobs_checked"], out["recent_jobs_failed"]), (10, 1))      # Workato's own status
        self.assertNotIn("Runs with errors", out["html"])
        self.assertIn("counts handled errors as successes", out["html"])                        # said on the job card
        self.assertFalse(any("Otherwise healthy" in sig for sig in out["signals"]))

    def test_without_the_error_log_there_is_no_tile(self):
        out = self.run_full([row(2, job="j-r2")], history="no")
        self.assertNotIn("Runs with errors", out["html"])

    def test_jobs_older_than_the_log_window_are_not_judged(self):
        old = {"items": [{"id": JOB, "status": "pending"}, {"id": "j-r1", "status": "succeeded"},
                         {"id": "j-old", "status": "succeeded", "started_at": "2026-05-01T10:00:00-08:00"}]}
        out = self.run_full([row(2, job="j-r1")], jobs=old)
        self.assertIn(">2/2<", out["html"])                                                      # j-old is left out of both numbers
        self.assertIn("older than the 90 days of the error log", out["html"])

    def test_workato_failed_jobs_still_count(self):
        out = self.run_full([], jobs=self.items(api="failed"))
        self.assertEqual(out["recent_jobs_failed"], 10)
        self.assertIn("failed in Workato", out["html"])

    def test_retries_is_always_shown_even_when_zero(self):
        out = self.run_full([], retry_count="0")
        self.assertIn("Retries", out["html"])
        at = out["html"].index(">Retries<")
        self.assertIn(">0<", out["html"][at:at + 400])
        self.assertIn("before this alert", out["html"][at:at + 500])

    def test_retries_come_from_the_job_when_the_caller_did_not_pass_them(self):
        job = {"status": "pending", "master_job_id": JOB, "is_repeat": False, "started_at": "2026-11-19T09:10:00-08:00",
               "lines": [{"recipe_line_number": 12, "adapter_name": "salesforce", "adapter_operation": "upsert_sobject",
                          "output": {"error": {"type": "RequestError", "message": "boom", "retry_count": 4}}}]}
        fake = FakeHttp(job=job, jobs=self.items())
        out = self.run_main(simple(workato_api_token="t", ai="no", detail="full", log_row="no"), fake)[0]
        at = out["html"].index(">Retries<")
        self.assertIn(">4<", out["html"][at:at + 400])

    def test_failed_at_is_left_out_while_where_it_broke_shows_it_and_back_when_it_does_not(self):
        with_flow = self.run_full([])
        self.assertNotIn(">Failed at<", with_flow["html"].split("Technical details")[0])        # the details still list it
        no_flow = self.run_full([], hide_sections="flow")
        self.assertIn(">Failed at<", no_flow["html"].split("Technical details")[0])

    def test_retry_success_is_how_often_a_retry_held(self):
        rows = [row(d, job="j-a{}".format(d), status="Reprocessed") for d in (2, 3, 4)] + [row(5, job="j-b", status="Failed Again")]
        out = self.run_full(rows)
        self.assertIn(">Retry success<", out["html"])
        self.assertIn(">75%<", out["html"])
        self.assertIn("3 of 4 retried", out["html"])

    def test_no_retry_history_means_no_retry_success_tile(self):
        self.assertNotIn("Retry success", self.run_full([row(2, job="j-r2")])["html"])

    def test_the_job_card_says_why_a_succeeded_job_had_an_error(self):
        fake = FakeHttp(job={"status": "succeeded", "master_job_id": JOB, "is_repeat": False,
                             "started_at": "2026-11-19T09:10:00-08:00", "lines": []}, jobs=self.items())
        html = self.run_main(simple(workato_api_token="t", ai="no", detail="full", log_row="no"), fake)[0]["html"]
        self.assertIn("the error handler caught the error, so Workato counts it a success", html)

    def test_four_tiles_at_most_and_the_run_health_ones_win_over_the_rest(self):
        rows = [row(d, job="j-r{}".format(d)) for d in range(2, 5)]
        out = self.run_main(sample(workato_api_token="t", ai="no", detail="full", hide_sections="history", log_row="no", retry_count="1"),
                            FakeHttp(rows=rows, jobs=self.items()))[0]
        labels = re.findall(r"text-transform:uppercase;color:[^>]*>([A-Za-z ]+)</div><div style=\"margin-top:1px\">", out["html"])
        self.assertLessEqual(len(labels), en.TILE_LIMIT)
        self.assertIn("Retries", labels)
        self.assertIn("Runs with errors", labels)


class TestLogRow(Patched):
    """The step writes the error log row itself: an upsert keyed on Master Job ID, like the old recipe's two upserts."""

    def call(self, fake=None, **extra):
        return self.run_main(simple(workato_api_token="t", ai="no", **extra), fake or FakeHttp())

    def lookups(self, fake):
        return [c for c in fake.urls("data-tables") if c[2] and "Master Job ID" in (c[2].get("where") or {})]

    def test_a_new_error_is_inserted(self):
        out, fake = self.call()
        self.assertEqual((out["row_logged"], out["row_action"], out["row_record_id"], out["row_error"]),
                         (True, "inserted", "rec-1", ""))
        method, _, doc = fake.writes[0]
        self.assertEqual(method, "POST")
        self.assertEqual((doc["Master Job ID"], doc["Job Id"], doc["Recipie Id"], doc["Status"], doc["Date"]),
                         (JOB, JOB, RECIPE_ID, "Notified", "2026-11-19"))
        self.assertEqual((doc["Reprocess_Flag"], doc["Reprocess Count"], doc["Recipe Name"]),
                         (False, 0, "Lead Sync - RealTime"))
        post = [c for c in fake.urls("data-tables") if c[0] == "POST" and c[1].endswith("/records")][0]
        self.assertEqual(post[2], {"document": doc})                       # the body is {"document": {...}}
        self.assertEqual(post[3]["Authorization"], "Bearer t")

    def test_only_columns_that_have_a_value_are_written(self):
        _, fake = self.call()
        doc = fake.writes[0][2]
        self.assertNotIn("Frequency", doc)                                  # no frequency, no error limit, no file
        self.assertNotIn("Error Limit", doc)
        self.assertNotIn("Error File Path", doc)
        self.assertLessEqual(set(doc), {column for _, column in en.TABLE_ROW_KEYS})

    def test_the_lookup_is_by_master_job_id(self):
        _, fake = self.call()
        found = self.lookups(fake)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][2]["where"], {"Master Job ID": {"$eq": JOB}})
        self.assertEqual(found[0][2]["limit"], 1)

    def test_a_deferred_call_is_logged_as_created_although_no_email_is_built(self):
        out, fake = self.call(frequency=7)
        self.assertEqual((out["html"], out["send_email"], out["row_action"]), ("", False, "inserted"))
        doc = fake.writes[0][2]
        self.assertEqual((doc["Status"], doc["Frequency"]), ("Created", 7))

    def test_a_job_that_fails_again_updates_its_row_and_keeps_its_count(self):
        stored = {"rec-9": {"Master Job ID": JOB, "Status": "Notified", "Reprocess Count": 1, "Job Id": "j-old"}}
        out, fake = self.call(FakeHttp(stored=stored), is_Repeated=True)
        method, rid, doc = fake.writes[0]
        self.assertEqual((method, rid), ("PUT", "rec-9"))
        self.assertEqual((out["row_action"], out["row_record_id"]), ("updated", "rec-9"))
        self.assertEqual(doc["Status"], "Failed Again")
        self.assertNotIn("Reprocess Count", doc)                            # skip: the stored count stays
        self.assertEqual(fake.stored["rec-9"]["Reprocess Count"], 1)
        put = [c for c in fake.urls("data-tables") if c[0] == "PUT"][0]
        self.assertTrue(put[1].endswith("/records/rec-9"), put[1])
        self.assertEqual(len(fake.stored), 1)                               # no second row

    def test_a_new_master_job_adds_a_row_next_to_the_others(self):
        stored = {"rec-9": {"Master Job ID": "j-another-job", "Status": "Notified"}}
        out, fake = self.call(FakeHttp(stored=stored))
        self.assertEqual(out["row_action"], "inserted")
        self.assertEqual(len(fake.stored), 2)

    def test_a_failed_write_never_stops_the_email(self):
        out, fake = self.call(FakeHttp(fail=["/records"]))
        self.assertEqual((out["row_logged"], out["row_action"]), (False, "failed"))
        self.assertIn("boom", out["row_error"])
        self.assertTrue([w for w in out["warnings"] if w.startswith("row not logged")])
        self.assertTrue(out["ok"])
        self.assertIn("Lead Sync - RealTime", out["html"])
        posts = [c for c in fake.urls("data-tables") if c[0] == "POST" and c[1].endswith("/records")]
        self.assertEqual(len(posts), 1)                                     # a 500 on a create is not repeated: no double rows

    def test_a_busy_table_is_asked_once_more(self):
        out, fake = self.call(BusyOnceHttp())
        self.assertEqual(out["row_action"], "inserted")
        posts = [c for c in fake.urls("data-tables") if c[0] == "POST" and c[1].endswith("/records")]
        self.assertEqual(len(posts), 2)
        self.assertEqual(len(fake.writes), 1)

    def test_log_row_no_writes_nothing(self):
        out, fake = self.call(log_row="no")
        self.assertEqual((fake.writes, self.lookups(fake)), ([], []))
        self.assertEqual((out["row_logged"], out["row_action"], out["row_error"]), (False, "", ""))
        self.assertTrue(out["table_row"])                                   # the row is still returned

    def test_nothing_is_written_without_a_token(self):
        out = en.main(simple(ai="no"))
        self.assertEqual(out["row_action"], "")
        self.assertIn("row not logged: no workato_api_token", out["warnings"])

    def test_a_test_run_with_history_rows_json_writes_nothing(self):
        out, fake = self.call(history_rows_json=json.dumps([row(1)]))
        self.assertEqual((fake.writes, out["row_action"]), ([], ""))
        self.assertTrue([w for w in out["warnings"] if "test run" in w])

    def test_the_row_is_written_before_the_email_is_built(self):
        fake = FakeHttp()
        seen = []
        original = en.render_new

        def spy(ctx, max_rows):
            seen.append(len(fake.writes))
            return original(ctx, max_rows)
        en.render_new = spy
        try:
            self.call(fake)
        finally:
            en.render_new = original
        self.assertEqual(seen, [1])

    def test_a_crash_while_building_the_email_still_leaves_one_logged_row(self):
        fake = FakeHttp()
        original = en.render_new

        def boom(ctx, max_rows):
            raise RuntimeError("render broke")
        en.render_new = boom
        try:
            out, _ = self.call(fake)
        finally:
            en.render_new = original
        self.assertEqual(out["look_used"], "old")                           # the fallback email
        self.assertEqual((out["row_action"], len(fake.writes)), ("inserted", 1))   # logged once, not twice

    def test_configured_column_names_are_used(self):
        _, fake = self.call(config_json=json.dumps({"table_columns": {"recipe_id": "Recipe ID"}}))
        doc = fake.writes[0][2]
        self.assertEqual(doc["Recipe ID"], RECIPE_ID)
        self.assertNotIn("Recipie Id", doc)

    def test_decode_records_reads_the_arrays_of_a_query_and_the_object_of_a_write(self):
        query = {"schema": [[{"name": "$record_id"}, {"name": "$created_at"}], [{"name": "Status"}, {"name": "Job Id"}]],
                 "data": [[["abc-1", "t"], ["Created", "j-1"]]]}
        self.assertEqual(en.decode_records(query), [("abc-1", {"Status": "Created", "Job Id": "j-1"})])
        write = {"data": {"record_id": "abc-2", "document": [{"field_name": "Status", "value": "Notified"}]}}
        self.assertEqual(en.decode_records(write), [("abc-2", {"Status": "Notified"})])
        self.assertEqual(en.decode_records({"data": []}), [])
        self.assertEqual(en.decode_records(None), [])

    def test_the_schemas_know_the_switch_and_the_outputs(self):
        def names(file):
            with open(os.path.join(HERE, file), encoding="utf-8") as handle:
                return {f["name"] for f in json.load(handle)}
        inputs, outputs = names("error_notification_input_schema.json"), names("error_notification_output_schema.json")
        self.assertIn("log_row", inputs)
        self.assertLessEqual({"row_logged", "row_action", "row_record_id", "row_error"}, outputs)


class TestNeverFails(unittest.TestCase):
    def test_bad_inputs_still_give_an_email(self):
        for bad in ({}, None, {"dataArray": "not json", "column1Width": "wide", "priority": 7, "error_details": {"a": 1}},
                    {"config_json": "{not json", "look": "fancy", "timezone": "Mars/Base", "now": "yesterday"},
                    {"error_details": "x" * 50000, "max_error_chars": 200}):
            out = en.main(bad)
            self.assertTrue(out["ok"], bad)
            self.assertTrue(out["html"].strip(), bad)
            self.assertTrue(out["send_email"], bad)

    def test_a_crash_falls_back_to_the_old_look(self):
        original = en.render_new
        en.render_new = lambda ctx, rows: 1 / 0
        try:
            out = en.main(sample())
        finally:
            en.render_new = original
        self.assertEqual(out["look_used"], "old")
        self.assertIn("ZeroDivisionError", out["error"])
        self.assertTrue(out["table_row"])

    def test_pacific_time_without_zoneinfo(self):
        tz = en.PACIFIC
        summer = en.parse_dt("2026-07-01T12:00:00Z", tz)
        winter = en.parse_dt("2026-11-19T17:11:00Z", tz)
        self.assertEqual((summer.hour, summer.tzname()), (5, "PDT"))
        self.assertEqual((winter.hour, winter.tzname()), (9, "PST"))


class TestCardWidth(Patched):
    def html(self, **extra):
        out, _ = self.run_main(sample(ai="no", **extra), FakeHttp())
        return out["html"]

    def five(self):
        return dict(column1Name="A", column2Name="B", column3Name="C", column4Name="D", column5Name="E",
                    dataArray=[{"value1": "1", "value2": "2", "value3": "3", "value4": "4", "value5": "5"}])

    def test_three_columns_keep_the_usual_width(self):
        self.assertIn("max-width:800px", self.html())

    def test_more_columns_widen_the_card(self):
        self.assertIn("max-width:1040px", self.html(**self.five()))
        four = self.five()
        for k in ("column5Name",):
            four.pop(k)
        self.assertIn("max-width:920px", self.html(**four))

    def test_an_explicit_width_wins(self):
        self.assertIn("max-width:700px", self.html(max_width=700, **self.five()))
        self.assertIn("max-width:480px", self.html(max_width=300))          # never narrower than 480

    def test_no_table_no_extra_width(self):
        self.assertIn("max-width:800px", self.html(dataArray=[], column4Name="D", column5Name="E"))

    def test_the_columns_keep_a_minimum_width_and_the_table_scrolls(self):
        html = self.html(**self.five())
        self.assertIn("overflow-x:auto", html)
        self.assertRegex(html, r"min-width:(90|150|220)px")
        data = sample(ai="no")
        out, _ = self.run_main(data, FakeHttp())
        self.assertIn("min-width:150px", out["html"])                       # an id column
        self.assertIn("min-width:220px", out["html"])                       # the error text column


class TestAlertJson(Patched):
    """alert_json: the facts the error_slack step turns into a Slack message. Plain data; never in the way of the email."""

    def test_it_is_plain_json_with_what_the_slack_step_reads(self):
        out, _ = self.run_main(sample(ai="no"))
        facts = json.loads(out["alert_json"])
        self.assertEqual((facts["recipe_name"], facts["sev"]["label"], facts["failing"]), (SAMPLE["recipe_name"], "High", "target"))
        self.assertEqual(len(facts["rows"]), 4)
        self.assertEqual(facts["retry"]["head"], "Will not auto retry")
        self.assertNotIn("<", facts["headline"])

    def test_a_deferred_call_has_none(self):
        out, _ = self.run_main(sample(ai="no", frequency=7))
        self.assertEqual(out["alert_json"], "")

    def test_a_failure_building_it_never_touches_the_email(self):
        original = en.alert_facts
        en.alert_facts = lambda ctx: 1 / 0
        try:
            out, _ = self.run_main(sample(ai="no"))
        finally:
            en.alert_facts = original
        self.assertTrue(out["ok"] and out["html"])
        self.assertEqual(out["alert_json"], "")
        self.assertTrue(any("alert_json not built" in w for w in out["warnings"]))

    def test_the_email_is_the_same_as_before(self):
        out, _ = self.run_main(sample(ai="no"))
        self.assertIn("max-width:800px", out["html"])


class TestSchemas(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(HERE, name), encoding="utf-8") as handle:
            return json.load(handle)

    def test_input_schema_is_what_main_reads(self):
        names = [f["name"] for f in self.load("error_notification_input_schema.json")]
        self.assertEqual(names, list(en.INPUT_NAMES))

    def test_the_old_parameters_are_unchanged(self):
        old = self.load("email_input_schema.json")
        new = self.load("error_notification_input_schema.json")[: len(old)]
        self.assertEqual(old, new)

    def test_output_schema_is_what_main_returns(self):
        names = [f["name"] for f in self.load("error_notification_output_schema.json")]
        out = en.main(sample(ai="no"))
        self.assertEqual(names, [k for k, _ in en.OUTPUT_DEFAULTS])
        self.assertEqual(set(out), set(names))
        row = next(f for f in self.load("error_notification_output_schema.json") if f["name"] == "table_row")
        self.assertEqual([p["name"] for p in row["properties"]], [k for k, _ in en.TABLE_ROW_KEYS])


CSV = os.path.join(os.path.dirname(HERE), "data_table_error_notification_tbl.csv")   # the shared export is one folder up


@unittest.skipUnless(os.path.exists(CSV), "the data table export isn't here")
class TestRealExport(unittest.TestCase):
    def test_most_errors_get_a_category(self):
        rows = en.load_history_csv(CSV)
        rules = en.category_rules({})
        messages = [r["Error Message"] for r in rows if r["Error Message"].strip()]
        unknown = sum(1 for m in messages if en.classify(m, rules) == "unknown")
        self.assertLess(unknown / float(len(messages)), 0.15, unknown)

    def test_every_row_reads(self):
        rows = en.load_history_csv(CSV)
        cfg, _ = en.settings({})
        ctx = en.build_context({}, cfg, en.parse_dt(NOW, en.get_tz("America/Los_Angeles")))
        self.assertEqual(len(en.normalize_history(rows, ctx)), len(rows))


if __name__ == "__main__":
    unittest.main()
