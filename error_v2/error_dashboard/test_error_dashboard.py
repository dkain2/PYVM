"""
Tests for error_dashboard.py. Run them before and after any change:

    python3 test_error_dashboard.py            # all of them
    python3 test_error_dashboard.py -v         # with the name of each
    python3 -m unittest test_error_dashboard.TestFetch    # one group

Nothing here touches the network: http_json is replaced by a fake that answers like the data tables API (positional
rows, 200 a page, continuation tokens, the Date filter), the Workato recipes API and Azure, and records every call.
Standard library only. The test workspace (world()) is 12 weeks of a few recipes with known shapes: steady, spike,
rising, new, gone quiet, easing, a batch loader, and deferred rows.

THE GROUPS
    TestSettings     inputs over config_json over defaults, clamps, choices, sections and detail levels
    TestPeriod       rolling, calendar, period_end, include_today, the trend buckets
    TestFetch        one query per period with the Date filter, pages followed, positional rows read, parallel,
                     a refused filter, the page size fallback, max_rows, the backlog query, a failing table
    TestRows         column names, system names merged, filters, buckets, batch numbers
    TestMetrics      totals and change, recipes and their status, movers, patterns, categories, systems, records
    TestTrendStatus  new, spike, rising, easing, chronic, steady, quiet
    TestForecast     flat, linear and spiky series; never negative; the latest period kept; the daily split
    TestScoreAndInsights   the health score and the insights
    TestAI           Azure gets redacted facts, its summary is shown, a bad answer falls back
    TestRender       every section renders, escaping, the size guard and html_full, hover, detail levels
    TestOutputs      subject, text, slack, summary_json, top lists, skip_if_empty
    TestNeverFails   bad inputs give ok = false with an html, never an exception
    TestSchemas      the schema files match SETTINGS and OUTPUT_DEFAULTS; categories match error_notification.py
    TestRealExport   the exported data table (skipped when the CSV isn't there)
"""

import json
import os
import re
import sys
import unittest
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import error_dashboard as dash  # noqa: E402

NOW = "2026-11-20T08:00:00-08:00"          # a Friday: the period is Fri 13 - Thu 19 Nov 2026
END = date(2026, 11, 19)
TEAM = "integration-alerts@coursera.org"
AUTH = "Salesforce connection is broken. Please refresh"
DUP = "DUPLICATE_VALUE: duplicate value found: External_Id__c duplicates value on record with id: 0015g00000AbCdEFGH"
NIL = "Error calculating input for field 'email': undefined method `downcase' for nil:NilClass"
TIMEOUT = "Request timed out after 120 seconds"
BATCH = "Object:Account Total Records: 1000 Failed Records: 10"
COLUMNS = ("Date", "Reprocess_Flag", "Status", "Reprocess Count", "Error TimeStamp", "Recipe Name", "Error Message",
           "Frequency", "Error Limit", "Recipie Id", "Master Job ID", "Job URL", "Job Id", "Email", "Source System",
           "Source Object", "Target System", "Target Object", "Error File Path", "Error File Sharable URL",
           "Sharable Link Expires on")
_counter = [0]


def mk(days_back, recipe, rid, message, hour=4, status="Notified", source="NetSuite", target="SFDC_Services",
       email=TEAM, tobj="", freq="", limit=""):
    _counter[0] += 1
    d = END - timedelta(days=days_back)
    job = "j-T{:06d}".format(_counter[0])
    return {"Date": d.isoformat(), "Reprocess_Flag": "false", "Status": status, "Reprocess Count": "0",
            "Error TimeStamp": "{} {:02d}:{:02d}:00.000".format(d.isoformat(), hour, _counter[0] % 60),
            "Recipe Name": recipe, "Error Message": message, "Frequency": freq, "Error Limit": limit, "Recipie Id": rid,
            "Master Job ID": job, "Job URL": "https://app.workato.com/recipes/{}/job/{}".format(rid, job), "Job Id": job,
            "Email": email, "Source System": source, "Source Object": "", "Target System": target,
            "Target Object": tobj, "Error File Path": "", "Error File Sharable URL": "", "Sharable Link Expires on": ""}


def weekly(counts, recipe, rid, message, spread=True, day=0, **kw):
    """Rows for 12 weeks, oldest first; each week's errors spread over its days (or all on `day` of the week)."""
    rows = []
    for index, n in enumerate(counts):
        back = 11 - index
        for i in range(n):
            rows.append(mk(7 * back + ((i % 7) if spread else day), recipe, rid, message, **kw))
    return rows


def world():
    rows = []
    rows += weekly([5] * 12, "Lead Sync", "100", AUTH, hour=4)                                   # steady (chronic)
    rows += weekly([2] * 11 + [30], "Invoice Sync", "200", DUP, spread=False, day=2, target="NetSuite", hour=14)
    rows += weekly([4, 12, 4, 12, 4, 12, 4, 12, 4, 12, 8, 16], "Rising Sync", "300", TIMEOUT, target="Braze", hour=3)
    rows += weekly([0] * 11 + [3], "New Recipe", "400", NIL, source="EDS")                       # new
    rows += weekly([1] * 10 + [4, 0], "Quiet Recipe", "500", "404 Not Found", hour=22)           # gone quiet
    rows += weekly([15] * 10 + [20, 5], "Easing Recipe", "700", "Bad request: invalid field", hour=9)
    rows += weekly([7] * 12, "Batch Loader", "600", BATCH, source="EDS", target="SFDC_Enterprise", tobj="Account", hour=2)
    # deferred rows: three overdue (40 days), two recent
    for back in (40, 40, 40, 2, 1):
        rows.append(mk(back, "Deferred Recipe", "800", "Something odd", status="Created", freq="7", limit="20"))
    return rows


def matches(row, where):
    if not where:
        return True
    if "$and" in where:
        return all(matches(row, w) for w in where["$and"])
    for column, cond in where.items():
        value = row.get(column)
        for op, expected in cond.items():
            if op == "$eq" and value != expected:
                return False
            if op == "$gte" and not (value or "") >= expected:
                return False
            if op == "$lte" and not (value or "") <= expected:
                return False
    return True


class FakeAPI:
    """http_json stand-in: the data tables query API, the Workato recipes API and Azure."""

    def __init__(self, rows, refuse_filter=False, max_limit=200, recipes=None, azure=None, table_error=None,
                 page_error_at=None, no_token=False):
        self.rows, self.refuse_filter, self.max_limit = rows, refuse_filter, max_limit
        self.recipes, self.azure, self.table_error = recipes or {}, azure, table_error
        self.page_error_at, self.no_token = page_error_at, no_token
        self.calls = []

    def __call__(self, method, url, headers, payload=None, timeout=12):
        self.calls.append({"method": method, "url": url, "payload": payload, "headers": headers})
        if "data-tables" in url:
            return self.query(payload)
        if "openai" in url:
            if self.azure is None:
                return None, "azure 500: down"
            return {"choices": [{"message": {"content": self.azure}}]}, None
        match = re.search(r"/recipes/(\d+)", url)
        if match and method == "GET":
            rid = match.group(1)
            if rid in self.recipes:
                return self.recipes[rid], None
            return None, "www.workato.com 404: not found"
        return None, "unexpected call " + url

    def query(self, payload):
        if self.table_error:
            return None, self.table_error
        limit = payload.get("limit")
        if limit > self.max_limit:
            return None, "data-tables.workato.com 400: limit must be <= 200"
        where = payload.get("where")
        if where and self.refuse_filter and "Date" in json.dumps(where):
            return None, "data-tables.workato.com 400: unsupported filter"
        rows = [r for r in self.rows if matches(r, where)]
        start = int(payload.get("continuation_token") or 0)
        if self.page_error_at is not None and start >= self.page_error_at:
            return None, "data-tables.workato.com 500: boom"
        page = rows[start:start + limit]
        select = payload.get("select") or list(COLUMNS)
        body = {"schema": [[{"name": "$record_id"}, {"name": "$created_at"}], [{"name": c, "id": c} for c in select]],
                "data": [[["rec-{}".format(start + i), "2026-11-19T00:00:00Z"], [r.get(c) for c in select]]
                         for i, r in enumerate(page)], "count": len(page), "limit": limit}
        if start + limit < len(rows) and not self.no_token:
            body["continuation_token"] = str(start + limit)
        return body, None

    def table_calls(self):
        return [c for c in self.calls if "data-tables" in c["url"]]


# The fixture is a 12-week world with a forecast: these settings keep it so (the step's defaults are 13 weeks and 91 days,
# with no forecast; TestSettings.test_defaults pins those).
FIXTURE = {"trend_periods": "12", "daily_days": "28", "heatmap_periods": "4", "forecast": "yes",
           "sections": ",".join(dash.DEFAULT_SECTIONS)}


class Base(unittest.TestCase):
    def setUp(self):
        self._http = dash.http_json
        self.world = world()

    def tearDown(self):
        dash.http_json = self._http

    def run_api(self, fake=None, **extra):
        self.fake = fake or FakeAPI(self.world)
        dash.http_json = self.fake
        data = dict(FIXTURE, workato_api_token="tok", now=NOW, recipe_status="no")
        data.update(extra)
        return dash.main(data)

    def run_rows(self, rows=None, **extra):
        data = dict(FIXTURE, rows_json=json.dumps(self.world if rows is None else rows), now=NOW)
        data.update(extra)
        return dash.main(data)

    def context(self, **extra):
        """Settings, period and rows, as main() sets them up (for the analysis functions)."""
        data = dict(FIXTURE, now=NOW)
        data.update(extra)
        cfg, _ = dash.settings(data)
        tz = dash.get_tz(cfg["timezone"])
        now = dash.current_time(cfg, tz)
        ctx = dash.SimpleNamespace(cfg=cfg, extra=cfg["extra"], tz=tz, now=now, today=now.date(), status={}, ai=None,
                                   insights=[], pages=0, msg_cache={}, system_cache={}, data_complete=True)
        ctx.period = dash.resolve_period(cfg, now, [])
        ctx.sections = dash.resolve_sections(cfg, [])
        ctx.rules = dash.category_rules(ctx.extra)
        ctx.system_aliases = {k.lower(): v for k, v in (ctx.extra.get("system_aliases") or {}).items()}
        ctx.public_emails = [TEAM]
        ctx.heat_colors = dash.HEAT
        ctx.env_label, ctx.frame = "Production", "#EEF1F4"
        ctx.rows = dash.normalize_rows(self.world, ctx)
        ctx.backlog_rows = dash.normalize_rows(self.world, ctx, window=False)
        return ctx

    def analyzed(self, **extra):
        ctx = self.context(**extra)
        return ctx, dash.analyze(ctx)


# ------------------------------------------------------------------------------------------------ settings


class TestSettings(Base):
    def test_defaults(self):
        cfg, warnings = dash.settings({})
        self.assertEqual(warnings, [])
        self.assertEqual(cfg["detail"], "full")
        self.assertEqual(cfg["period_days"], 7)
        self.assertEqual(cfg["trend_periods"], 13)                 # 91 days of history
        self.assertEqual(cfg["daily_days"], 91)
        self.assertEqual(cfg["heatmap_periods"], 13)
        self.assertFalse(cfg["forecast"])                           # no predictions unless asked
        self.assertNotIn("forecast", dash.resolve_sections(cfg, []))
        self.assertEqual(cfg["page_size"], 200)
        self.assertEqual(cfg["data_table_id"], dash.ERROR_TABLE_ID)

    def test_input_wins_over_config_json(self):
        cfg, _ = dash.settings({"top_n": "7", "config_json": json.dumps({"top_n": 4, "title": "Ops"})})
        self.assertEqual(cfg["top_n"], 7)
        self.assertEqual(cfg["title"], "Ops")

    def test_clamped_and_bad_choices(self):
        cfg, warnings = dash.settings({"top_n": "999", "page_size": "5000", "period": "monthly", "detail": "huge"})
        self.assertEqual(cfg["top_n"], 30)
        self.assertEqual(cfg["page_size"], 1000)
        self.assertEqual(cfg["period"], "rolling")
        self.assertEqual(cfg["detail"], "full")
        self.assertEqual(len(warnings), 2)

    def test_bad_config_json(self):
        cfg, warnings = dash.settings({"config_json": "[1, 2]"})
        self.assertIn("config_json is not a JSON object", warnings[0])

    def test_sections(self):
        warnings = []
        cfg, _ = dash.settings({"detail": "brief", "show_sections": "patterns, pareto", "hide_sections": "trend"})
        self.assertEqual(dash.resolve_sections(cfg, warnings),
                         ["hero", "kpis", "insights", "recipes", "patterns", "noise", "actions"])
        cfg, _ = dash.settings({"sections": "recipes hero bogus"})
        self.assertEqual(dash.resolve_sections(cfg, warnings), ["recipes", "hero"])
        self.assertIn("bogus", warnings[-1])


# -------------------------------------------------------------------------------------------------- period


class TestPeriod(Base):
    def period(self, **extra):
        data = {"now": NOW}
        data.update(extra)
        cfg, _ = dash.settings(data)
        now = dash.current_time(cfg, dash.get_tz(cfg["timezone"]))
        return dash.resolve_period(cfg, now, [])

    def test_rolling_ends_yesterday(self):
        p = self.period()
        self.assertEqual((p.start, p.end), (date(2026, 11, 13), date(2026, 11, 19)))
        self.assertEqual((p.prev_start, p.prev_end), (date(2026, 11, 6), date(2026, 11, 12)))
        self.assertEqual(p.label, "13–19 Nov 2026")
        self.assertEqual(len(p.buckets), 13)                       # 13 weeks = 91 days
        self.assertEqual(p.buckets[0].start, date(2026, 8, 21))
        self.assertEqual(p.window_start, date(2026, 8, 21))
        self.assertEqual(p.unit, "week")

    def test_include_today_and_period_end(self):
        self.assertEqual(self.period(include_today="yes").end, date(2026, 11, 20))
        p = self.period(period_end="2026-10-31")
        self.assertEqual((p.start, p.end), (date(2026, 10, 25), date(2026, 10, 31)))

    def test_calendar_week(self):
        p = self.period(period="calendar")                          # Monday weeks: 9-15 Nov
        self.assertEqual((p.start, p.end), (date(2026, 11, 9), date(2026, 11, 15)))
        p = self.period(period="calendar", week_start="sunday")     # Sunday weeks: 8-14 Nov
        self.assertEqual((p.start, p.end), (date(2026, 11, 8), date(2026, 11, 14)))

    def test_other_lengths(self):
        p = self.period(period_days="1", trend_periods="14")
        self.assertEqual((p.start, p.end, p.unit), (date(2026, 11, 19), date(2026, 11, 19), "day"))
        self.assertEqual(p.label, "19 Nov 2026")
        p = self.period(period_days="14")
        self.assertEqual(p.unit, "period")
        self.assertEqual(p.start, date(2026, 11, 6))

    def test_window_covers_daily_chart(self):
        p = self.period(trend_periods="2", daily_days="28")
        self.assertEqual(p.window_start, date(2026, 10, 23))


# --------------------------------------------------------------------------------------------------- fetch


class TestFetch(Base):
    def test_one_filtered_query_per_period_and_pages_followed(self):
        out = self.run_api()
        self.assertTrue(out["ok"], out["error"])
        calls = self.fake.table_calls()
        wheres = [json.dumps(c["payload"].get("where")) for c in calls]
        periods = {w for w in wheres if "$gte" in w}
        self.assertEqual(len(periods), 12)                               # one per week of the trend
        self.assertTrue(any('"Status": {"$eq": "Created"}' in w for w in wheres))   # the backlog query
        for c in calls:
            self.assertEqual(c["payload"]["limit"], 200)
            self.assertIn("Error Message", c["payload"]["select"])
            self.assertEqual(c["headers"]["Authorization"], "Bearer tok")
            self.assertIn("/c1444a9a-03a7-4c82-8618-7796b7384b37/query", c["url"])
        self.assertEqual(out["errors_total"], 5 + 30 + 16 + 3 + 0 + 5 + 7 + 2)         # + 2 recent deferred rows
        self.assertEqual(out["errors_previous"], 5 + 2 + 8 + 0 + 4 + 20 + 7)
        self.assertTrue(out["data_complete"])

    def test_small_pages_are_followed(self):
        out = self.run_api(page_size="10")
        self.assertTrue(out["ok"], out["error"])
        tokens = [c["payload"].get("continuation_token") for c in self.fake.table_calls()]
        self.assertIn("10", tokens)
        self.assertIn("20", tokens)
        self.assertEqual(out["errors_total"], 68)
        self.assertGreater(out["pages_read"], 13)

    def test_positional_rows_decoded(self):
        fake = FakeAPI(self.world)
        body, _ = fake.query({"limit": 2, "select": ["Date", "Recipe Name"]})
        rows = dash.decode_rows(body)
        self.assertEqual(rows[0]["Recipe Name"], self.world[0]["Recipe Name"])
        self.assertEqual(rows[0]["$record_id"], "rec-0")
        self.assertEqual(dash.decode_rows({"records": [{"Date": "2026-11-01"}]}), [{"Date": "2026-11-01"}])
        self.assertEqual(dash.next_token({"continuation_token": "abc"}), "abc")
        self.assertEqual(dash.next_token({"meta": {"next_token": "x"}}), "x")
        self.assertEqual(dash.next_token({}), "")

    def test_bigger_page_refused_falls_back_to_200(self):
        out = self.run_api(page_size="1000")
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["errors_total"], 68)
        self.assertTrue(any("refused 1000 rows a page" in w for w in out["warnings"]))
        self.assertEqual(self.fake.table_calls()[-1]["payload"]["limit"], 200)

    def test_refused_date_filter_reads_without_one(self):
        out = self.run_api(FakeAPI(self.world, refuse_filter=True))
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["errors_total"], 68)
        self.assertTrue(any("refused the date filter" in w for w in out["warnings"]))

    def test_failing_table(self):
        out = self.run_api(FakeAPI(self.world, table_error="data-tables.workato.com 401: bad token"))
        self.assertFalse(out["ok"])
        self.assertIn("401", out["error"])
        self.assertFalse(out["send_email"])
        self.assertIn("could not be built", out["html"])

    def test_a_page_failing_midway_marks_data_incomplete(self):
        out = self.run_api(FakeAPI(self.world, page_error_at=10), page_size="10")
        self.assertTrue(out["ok"], out["error"])
        self.assertFalse(out["data_complete"])
        self.assertIn("Some data could not be read", out["html"])

    def test_missing_token_on_a_full_page_is_reported(self):
        out = self.run_api(FakeAPI(self.world, no_token=True), page_size="10")
        self.assertFalse(out["data_complete"])
        self.assertTrue(any("without a continuation token" in w for w in out["warnings"]))

    def test_max_rows(self):
        self.world = self.world * 3
        out = self.run_api(max_rows="500", page_size="10")
        self.assertFalse(out["data_complete"])
        self.assertTrue(any("max_rows" in w for w in out["warnings"]), out["warnings"])

    def test_no_token_no_rows(self):
        out = dash.main({"now": NOW})
        self.assertFalse(out["ok"])
        self.assertIn("workato_api_token is required", out["error"])

    def test_recipe_status_lookup(self):
        fake = FakeAPI(self.world, recipes={
            "200": {"running": False, "stop_cause": "Too many errors", "updated_at": "2026-11-18T10:00:00-08:00",
                    "version_no": 9},
            "300": {"running": True, "updated_at": "2026-11-17T10:00:00-08:00", "version_no": 4}})
        out = self.run_api(fake, recipe_status="yes")
        self.assertTrue(out["ok"], out["error"])
        gets = [c["url"] for c in fake.calls if c["method"] == "GET"]
        self.assertTrue(any(u.endswith("/recipes/200?exclude_code=yes") for u in gets))
        self.assertTrue(any("Invoice Sync is stopped now: Too many errors" in i for i in out["insights"]))
        self.assertTrue(any("Rising Sync was changed on Tue 17 Nov (version 4)" in i for i in out["insights"]))
        self.assertIn("■ stopped", out["html"])
        self.assertTrue(any("recipe status lookup failed" in w for w in out["warnings"]))   # the 404s


# ---------------------------------------------------------------------------------------------------- rows


class TestRows(Base):
    def test_columns_systems_and_buckets(self):
        ctx = self.context()
        row = next(r for r in ctx.rows if r["name"] == "Batch Loader" and r["date"] == END)
        self.assertEqual(row["target"], "Salesforce Enterprise")
        self.assertEqual(row["source"], "EDS")
        self.assertEqual(row["b"], 11)
        self.assertEqual((row["btotal"], row["bfailed"], row["bobj"]), (1000, 10, "Account"))
        self.assertEqual(row["ts"].hour, 2)
        self.assertEqual(row["cat"], "partial_batch")
        self.assertEqual(next(r for r in ctx.rows if r["rid"] == "100")["cat"], "auth")

    def test_system_names(self):
        ctx = self.context()
        for raw, want in (("SFDC_Services", "Salesforce Services"), ("SFDC Services", "Salesforce Services"),
                          ("Saleforce Enterprise", "Salesforce Enterprise"), ("netsuite", "NetSuite"),
                          ("Braze", "Braze"), ("", "")):
            self.assertEqual(dash.canon_system(raw, ctx), want)
        ctx = self.context(merge_system_names="no", config_json=json.dumps({"system_aliases": {"EDS": "Data warehouse"}}))
        self.assertEqual(dash.canon_system("SFDC_Services", ctx), "SFDC_Services")
        self.assertEqual(dash.canon_system("EDS", ctx), "Data warehouse")

    def test_filters(self):
        ctx = self.context(include_recipes="100, invoice")
        self.assertEqual({r["rid"] for r in ctx.rows}, {"100", "200"})
        ctx = self.context(exclude_recipes="Lead Sync,600")
        self.assertNotIn("100", {r["rid"] for r in ctx.rows})
        self.assertNotIn("600", {r["rid"] for r in ctx.rows})
        ctx = self.context(include_systems="braze")
        self.assertEqual({r["rid"] for r in ctx.rows}, {"300"})
        ctx = self.context(exclude_statuses="Created")
        self.assertNotIn("800", {r["rid"] for r in ctx.rows})

    def test_window_and_custom_columns(self):
        rows = [{"When": "2026-11-18", "Recipe": "X", "Msg": "boom", "Status": "Notified"},
                {"When": "2025-01-01", "Recipe": "Old", "Msg": "boom", "Status": "Notified"}]
        self.world = rows
        ctx = self.context(config_json=json.dumps({"table_columns": {"date": "When", "recipe_name": "Recipe",
                                                                     "message": "Msg"}}))
        self.assertEqual([r["name"] for r in ctx.rows], ["X"])
        self.assertEqual(ctx.rows[0]["msg"], "boom")

    def test_parse_batch(self):
        self.assertEqual(dash.parse_batch("Object:Lead Total Records: 2,630 Failed Records: 14"), (2630, 14, "Lead"))
        self.assertEqual(dash.parse_batch("The recipe retrieved 32 records, however, it failed to synchronize 3 of them")[:2],
                         (32, 3))
        self.assertEqual(dash.parse_batch("Total Records : 120 Records Failed: 4 Sf")[:2], (120, 4))
        self.assertEqual(dash.parse_batch("Salesforce connection is broken"), (None, None, ""))


# ------------------------------------------------------------------------------------------------- metrics


class TestMetrics(Base):
    def test_totals_and_recipes(self):
        ctx, m = self.analyzed()
        self.assertEqual((m.cur_n, m.prev_n), (68, 46))
        self.assertAlmostEqual(m.change, 100.0 * 22 / 46)
        self.assertEqual(m.recipes_cur, 7)
        self.assertEqual(m.top[0]["name"], "Invoice Sync")
        statuses = {e["name"]: e["status"] for e in ctx.recipes.values()}
        self.assertEqual(statuses["Invoice Sync"], "spike")
        self.assertEqual(statuses["Rising Sync"], "rising")
        self.assertEqual(statuses["New Recipe"], "new")
        self.assertEqual(statuses["Quiet Recipe"], "quiet")
        self.assertEqual(statuses["Easing Recipe"], "easing")
        self.assertEqual(statuses["Lead Sync"], "chronic")

    def test_movers(self):
        _, m = self.analyzed()
        self.assertEqual([e["name"] for e in m.rising][:2], ["Invoice Sync", "Rising Sync"])
        self.assertEqual([e["name"] for e in m.easing], ["Easing Recipe"])
        self.assertEqual([e["name"] for e in m.new_recipes], ["New Recipe"])
        self.assertEqual([e["name"] for e in m.quiet], ["Quiet Recipe"])

    def test_patterns(self):
        _, m = self.analyzed()
        new = [p for p in m.patterns_top if p["status"] == "new"]
        self.assertEqual(len(new), 1)
        self.assertIn("undefined method", new[0]["example"])
        top = m.patterns_top[0]
        self.assertEqual((top["cur"], top["cat"]), (30, "duplicate"))
        self.assertEqual(len(top["sig"]), 8)

    def test_categories_systems_records_heat(self):
        _, m = self.analyzed()
        self.assertEqual(m.cats_cur["duplicate"], 30)
        self.assertEqual(m.cats_cur["auth"], 5)
        self.assertEqual(m.tgt_cur["NetSuite"], 30)
        self.assertEqual(m.routes[("NetSuite", "Braze")], 16)
        self.assertEqual((m.rec_failed_cur, m.rec_total_cur, m.batch_runs_cur), (70, 7000, 7))
        self.assertEqual(m.batches["Account"]["failed"], 70)
        self.assertEqual(sum(map(sum, m.heat)), sum(1 for r in self.context().rows if r["date"] >= date(2026, 10, 23)))
        self.assertEqual(m.pareto["n"], 7)

    def test_backlog(self):
        _, m = self.analyzed()
        self.assertEqual((m.backlog["total"], m.backlog["overdue"], m.backlog["oldest"]), (5, 3, 41))
        self.assertEqual(m.backlog["groups"][0]["name"], "Deferred Recipe")

    def test_spike_day(self):
        _, m = self.analyzed()
        self.assertEqual([s["date"] for s in m.spikes_in_period], [date(2026, 11, 17)])
        self.assertEqual(m.spikes_in_period[0]["recipe"], "Invoice Sync")

    def test_owners_and_known_issues(self):
        ctx, m = self.analyzed(config_json=json.dumps({
            "recipe_owners": {"200": "Finance squad"},
            "known_issues": [{"match": "re:duplicate value found", "note": "INT-42", "url": "https://jira/INT-42"}]}))
        self.assertEqual(ctx.recipes["200"]["owner"], "Finance squad")
        self.assertEqual(m.patterns_top[0]["known"]["note"], "INT-42")


class TestTrendStatus(unittest.TestCase):
    cfg = {"spike_z": 3.5, "rising_pct": 50, "min_change": 5, "chronic_periods": 6}

    def status(self, weekly):
        return dash.trend_status(weekly, self.cfg)

    def test_shapes(self):
        self.assertEqual(self.status([0, 0, 0, 0, 3]), "new")
        self.assertEqual(self.status([2, 2, 2, 2, 2, 30]), "spike")
        self.assertEqual(self.status([4, 12, 4, 12, 8, 16]), "rising")
        self.assertEqual(self.status([15, 15, 15, 20, 5]), "easing")
        self.assertEqual(self.status([5] * 8), "chronic")
        self.assertEqual(self.status([0, 3, 0, 0, 4, 3]), "steady")
        self.assertEqual(self.status([1, 1, 4, 0]), "quiet")
        self.assertEqual(self.status([0, 0, 0]), "none")

    def test_no_spike_without_a_jump(self):
        self.assertNotEqual(self.status([0, 0, 0, 0, 0, 20, 21]), "spike")      # high two weeks running


# ------------------------------------------------------------------------------------------------ forecast


class TestForecast(unittest.TestCase):
    def test_flat(self):
        f = dash.forecast_series([100] * 12, "holt")
        self.assertAlmostEqual(f["point"], 100, delta=1)
        self.assertEqual(f["trend"], "flat")
        self.assertLess(f["low"], 100)
        self.assertGreater(f["high"], 100)

    def test_linear_goes_on(self):
        f = dash.forecast_series([10 * i for i in range(1, 13)], "holt")
        self.assertGreater(f["point"], 110)
        self.assertEqual(f["trend"], "rising")

    def test_old_spike_clipped_latest_kept(self):
        f = dash.forecast_series([50, 50, 5000, 50, 50, 50, 50, 50], "holt")
        self.assertLess(f["point"], 120)
        g = dash.forecast_series([0] * 11 + [90], "holt")
        self.assertGreater(g["point"], 10)

    def test_never_negative_and_methods(self):
        f = dash.forecast_series([50, 40, 30, 20, 10, 0, 0, 0], "holt")
        self.assertGreaterEqual(f["point"], 0)
        self.assertGreaterEqual(f["low"], 0)
        self.assertEqual(dash.forecast_series([1, 2, 3, 4, 9], "naive")["point"], 9)
        self.assertEqual(dash.forecast_series([1, 2, 3, 4, 8], "average")["point"], 4.25)
        self.assertEqual(dash.forecast_series([7], "holt")["method"], "average")
        self.assertIsNone(dash.forecast_series([], "holt"))

    def test_daily_split_adds_up(self):
        base = Base("setUp")
        base.setUp()
        ctx, m = base.analyzed()
        f = m.forecast
        self.assertEqual(len(f["daily"]), 7)
        self.assertEqual(f["daily"][0][0], date(2026, 11, 20))
        self.assertAlmostEqual(sum(v for _, v in f["daily"]), f["point"])
        self.assertTrue(f["recipes"])


# ------------------------------------------------------------------------------------------ score, insights


class TestScoreAndInsights(Base):
    def test_quiet_week_scores_100(self):
        rows = [r for r in self.world if r["Date"] < "2026-11-13" and r["Status"] != "Created"]
        out = self.run_rows(rows)
        self.assertEqual(out["errors_total"], 0)
        self.assertEqual((out["health_score"], out["health_grade"]), (100, "A"))
        self.assertTrue(any("No errors were logged" in i for i in out["insights"]))

    def test_bad_week_scores_lower_and_weights_apply(self):
        out = self.run_rows()
        self.assertLess(out["health_score"], 90)
        heavy = self.run_rows(config_json=json.dumps({"score_weights": {"volume": 100, "spikes": 100}}))
        self.assertLess(heavy["health_score"], out["health_score"])
        off = self.run_rows(health_score="no")
        self.assertIsNone(off["health_score"])
        self.assertNotIn("GRADE", off["html"])

    def test_insights(self):
        out = self.run_rows()
        text = "\n".join(out["insights"])
        self.assertIn("Errors are up 48% on the week before (68 against 46)", text)
        self.assertIn("Spike on Tue 17 Nov: 37 errors", text)
        self.assertIn("1 new error pattern this week", text)
        self.assertIn("3 are past their notify window", text)
        self.assertIn("Timeout errors (16) hit 1 recipe: Rising Sync. Check the slowest steps", text)
        few = self.run_rows(max_insights="2")
        self.assertEqual(len(few["insights"]), 2)


# ------------------------------------------------------------------------------------------------------ AI


class TestAI(Base):
    ANSWER = json.dumps({"headline": "Duplicates in **Invoice Sync** drove a 43% rise",
                         "summary": "Errors rose to 66, mostly **Invoice Sync** duplicates on Tue 17 Nov.",
                         "risks": ["Invoice Sync keeps rejecting records"], "actions": ["De-duplicate Invoice Sync input"],
                         "confidence": "medium"})

    def test_summary_shown_and_facts_redacted(self):
        world_rows = self.world + [mk(1, "Lead Sync", "100", "Login failed for jane.doe@coursera.org at https://x.y/z 123456789")]
        fake = FakeAPI(world_rows, azure=self.ANSWER)
        self.world = world_rows
        out = self.run_api(fake, azure_api_key="key")
        self.assertTrue(out["ok"], out["error"])
        self.assertTrue(out["ai_used"])
        self.assertIn("Executive summary", out["html"])
        self.assertIn("<b>Invoice Sync</b> duplicates", out["html"])
        self.assertIn("Duplicates in <b>Invoice Sync</b> drove", out["html"])      # the AI headline in the hero
        risks = out["html"].index("Risks</div>")                                   # each list in its own tinted card
        self.assertIn("background:{};border:1px solid #FECACA".format(dash.BAD_SOFT), out["html"][risks - 400:risks])
        actions = out["html"].index("Do next</div>")
        self.assertIn("background:{};border:1px solid #BBF7D0".format(dash.GOOD_SOFT), out["html"][actions - 400:actions])
        self.assertIn(">1</span>", out["html"][actions:actions + 600])               # the steps are numbered
        call = next(c for c in fake.calls if "openai" in c["url"])
        sent = call["payload"]["messages"][1]["content"]
        self.assertNotIn("jane.doe@coursera.org", sent)
        self.assertNotIn("123456789", sent)
        self.assertEqual(call["headers"]["api-key"], "key")

    def test_bad_answer_falls_back(self):
        out = self.run_api(FakeAPI(self.world, azure="not json at all"), azure_api_key="key")
        self.assertTrue(out["ok"])
        self.assertFalse(out["ai_used"])
        self.assertTrue(any("azure" in w for w in out["warnings"]))
        self.assertNotIn("Executive summary", out["html"])

    def test_azure_down_and_ai_off(self):
        out = self.run_api(FakeAPI(self.world, azure=None), azure_api_key="key")
        self.assertTrue(out["ok"])
        self.assertTrue(any("azure: azure 500" in w for w in out["warnings"]))
        fake = FakeAPI(self.world, azure=self.ANSWER)
        self.run_api(fake, azure_api_key="key", ai="no")
        self.assertFalse(any("openai" in c["url"] for c in fake.calls))


    def test_azure_failures_are_captured_and_the_dashboard_still_goes_out(self):
        cases = (("down", FakeAPI(self.world, azure=None), "azure 500"),
                 ("not json", FakeAPI(self.world, azure="sorry, no"), "not the JSON asked for"),
                 ("no summary", FakeAPI(self.world, azure=json.dumps({"headline": "x"})), "not the JSON asked for"))
        for label, fake, expected in cases:
            out = self.run_api(fake, azure_api_key="key")
            self.assertTrue(out["ok"], label)
            self.assertTrue(out["send_email"], label)
            self.assertFalse(out["ai_used"], label)
            self.assertIn(expected, out["ai_error"], label)
            self.assertIn(out["ai_error"], out["warnings"], label)
            self.assertIn("The AI summary could not be built this time", out["html"], label)   # said once, quietly
            self.assertIn("What stands out", out["html"], label)                               # the built-in insights stay
            self.assertNotIn("Executive summary", out["html"], label)

    def test_an_exception_while_building_the_ai_request_is_captured(self):
        original = dash.ai_facts

        def boom(ctx, m):
            raise ValueError("boom")
        dash.ai_facts = boom
        try:
            out = self.run_api(FakeAPI(self.world, azure=self.ANSWER), azure_api_key="key")
        finally:
            dash.ai_facts = original
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["error"], "")
        self.assertTrue(out["send_email"])
        self.assertIn("ValueError: boom", out["ai_error"])
        self.assertIn("What stands out", out["html"])

    def test_a_working_azure_or_no_key_leaves_ai_error_empty(self):
        self.assertEqual(self.run_api(FakeAPI(self.world, azure=self.ANSWER), azure_api_key="key")["ai_error"], "")
        out = self.run_api(FakeAPI(self.world, azure=None))                    # no key: AI was never asked for
        self.assertEqual(out["ai_error"], "")
        self.assertNotIn("could not be built this time", out["html"])


# -------------------------------------------------------------------------------------------------- render


class TestRender(Base):
    def test_every_section_renders(self):
        out = self.run_rows(html_limit_kb="0")
        self.assertEqual(out["sections_rendered"], list(dash.DEFAULT_SECTIONS))
        html = out["html"]
        for text in ("Workato Integrations Health", "Weekly report", "Top failing recipes", "Top error patterns", "Errors per day",
                     "When errors happen", "Error calendar", "Records in batch runs", "Deferred errors waiting",
                     "Alert load", "Next week", "Open the error log", "Routes: source → target",
                     "https://app.workato.com/recipes/200", "https://app.workato.com/data_tables/" + dash.ERROR_TABLE_ID):
            self.assertIn(text, html)
        self.assertEqual(html.count("<script"), 0)
        self.assertEqual(html, out["html_full"])

    def test_escaping(self):
        rows = self.world + [mk(0, '<script>alert(1)</script> Evil "recipe"', "999", "<img src=x onerror=alert(1)> boom")]
        out = self.run_rows(rows)
        self.assertNotIn("<script>alert", out["html"])
        self.assertNotIn("<img src=x", out["html"])
        self.assertIn("&lt;script&gt;", out["html"])

    def test_note_is_sanitized(self):
        out = self.run_rows(note='Maintenance <b>Sat</b><script>x()</script> <a href="javascript:x">y</a>')
        self.assertIn("Maintenance <b>Sat</b>", out["html"])
        self.assertNotIn("x()", out["html"])
        self.assertNotIn("javascript:", out["html"])

    def test_size_guard(self):
        out = self.run_rows(html_limit_kb="60")
        self.assertLessEqual(out["html_bytes"], 60 * 1024)
        self.assertGreater(len(out["html_full"]), len(out["html"]))
        self.assertNotIn("calendar", out["sections_rendered"])
        self.assertIn("Left out to keep this email small", out["html"])
        self.assertTrue(any("html_full has them" in w for w in out["warnings"]))

    def test_hover_switch_and_detail(self):
        self.assertIn(".hv-row:hover", self.run_rows()["html"])
        self.assertNotIn(".hv-row:hover", self.run_rows(hover_effects="no")["html"])
        self.assertNotIn('class="hv-', self.run_rows(hover_effects="no")["html"].split("</style>")[0])

    def test_hover_effects_like_error_notification(self):
        html = self.run_rows(hover_row_color="#FFF7ED")["html"]
        css = html.split("</head>")[0]
        for rule in (".hv-card:hover", ".hv-trow:hover td:first-child{box-shadow:inset 3px 0 0 #0056D2",
                     ".hv-trow:hover td{background-color:#FFF7ED", ".hv-btn:hover", ".hv-risk:hover", ".hv-do:hover",
                     ".pl:hover", ".pb:hover{background:", ".pg:hover{background:", ".hv-ring:hover{transform:scale",
                     "@media (hover:hover)", "@media (prefers-reduced-motion:reduce)", ".hm td:hover", ".rc:hover"):
            self.assertIn(rule, css)
        self.assertEqual(css.count("<style>"), 1)                       # one block, as error_notification.py
        self.assertLess(css.index(".sec{"), css.index(".hv-card:hover"))  # the hover rules after the layout
        body = html.split("</head>")[1]
        self.assertIn('<tr class="hv-trow"', body)                       # table rows
        self.assertIn('class="tl hv-card"', body)                        # KPI tiles
        self.assertIn('class="hv-ring"', body)                           # the health score
        self.assertIn('class="hv-btn"', body)
        self.assertIn('class="seg"', body)

    def test_team_logo_next_to_coursera_logo(self):
        html = self.run_rows(logo_url="https://example.com/coursera.png", team_logo_url="https://example.com/team.png",
                             team_name="IIS Team")["html"]
        head = html[html.index("<body"):html.index('class="h1"')]
        coursera, team = head.index("https://example.com/coursera.png"), head.index("https://example.com/team.png")
        self.assertLess(coursera, team)
        self.assertIn("width:1px;height:26px", head[coursera:team])     # the thin divider between them
        self.assertIn('alt="IIS Team" height="30"', head)
        self.assertNotIn("team.png", self.run_rows(logo_url="https://example.com/coursera.png")["html"])
        brief = self.run_rows(detail="brief", sections="")
        self.assertEqual(brief["sections_rendered"], list(dash.DETAIL_PRESETS["brief"]))
        self.assertLess(brief["html_bytes"], self.run_rows(detail="standard", sections="")["html_bytes"])

    def test_email_masking(self):
        rows = self.world + [mk(0, "Lead Sync", "100", AUTH, email=TEAM + ",jane.doe@coursera.org")]
        out = self.run_rows(rows, alert_email=TEAM)
        self.assertNotIn("jane.doe", out["html"])
        self.assertIn(TEAM + " +1 person", out["html"])
        plain_out = self.run_rows(rows, alert_email=TEAM, mask_emails="no")
        self.assertIn("jane.doe@coursera.org", plain_out["html"])

    def test_workato_logo_between_coursera_and_team(self):
        html = self.run_rows(logo_url="https://example.com/coursera.png", workato_logo_url="https://example.com/workato.png",
                             team_logo_url="https://example.com/team.png")["html"]
        head = html[html.index("<body"):html.index('class="h1"')]
        a, b, c = (head.index("https://example.com/{}.png".format(x)) for x in ("coursera", "workato", "team"))
        self.assertLess(a, b)
        self.assertLess(b, c)
        self.assertEqual(head.count("width:1px;height:26px"), 2)        # a divider between each pair
        self.assertIn('alt="Workato"', head)
        only = self.run_rows(workato_logo_url="https://example.com/workato.png")["html"]
        self.assertIn(">coursera</span>", only)                          # the word, then the Workato logo
        self.assertIn("workato.png", only)

    def test_daily_chart_numbers(self):
        html = self.run_rows()["html"]
        trend = html[html.index("Errors per day"):html.index("Errors per week")]
        self.assertIn('<div class="dl" style="color:#DC2626;font-weight:800">37</div>', trend)    # the spike day
        self.assertRegex(trend, r'<div class="dl" style="color:#1D4ED8">~\d+</div>')              # forecast days
        self.assertEqual(dash.day_label(1234), '<div class="dl">1.2k</div>')
        self.assertIn("color:#CBD5E1", dash.day_label(0))

    def test_sparkline_bars_and_cards(self):
        html = self.run_rows()["html"]
        self.assertIn('<div class="sl hv-bar"', html)
        self.assertIn('title="Per week, oldest first: 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 30"', html)
        self.assertIn('<i class="k2 q8"></i>', html)        # the latest week, full height
        self.assertNotIn('class="sk"', html)
        self.assertGreaterEqual(html.count('<div class="sec">'), 10)    # every section in a card of its own
        self.assertIn('<span class="ab"></span>Top failing recipes', html)
        self.assertIn('<div class="sh">Objects</div>', html)
        self.assertIn('<div class="hr">', html)
        bar = dash.spark_bars([0, 4, 8])
        self.assertIn('<i class="k0 q0">', bar)
        self.assertIn('<i class="k1 q4">', bar)

    def test_top_recipe_tile(self):
        html = self.run_rows()["html"]
        tile = html[html.index(">Top recipe<"):html.index(">New patterns<")]
        self.assertIn(">30<", tile)                                      # Invoice Sync, this week
        self.assertIn("Invoice Sync", tile)
        self.assertIn("44% of errors", tile)
        self.assertIn("Spike", tile)
        empty = self.run_rows([r for r in self.world if r["Date"] < "2026-11-13" and r["Status"] != "Created"])["html"]
        self.assertIn("no recipe failed this week", empty)

    def test_titles_and_theme(self):
        out = self.run_rows(title="BizInt health", brand_color="#7C3AED",
                            config_json=json.dumps({"titles": {"recipes": "Noisiest recipes"},
                                                    "buttons": [{"label": "Jira board", "url": "https://jira/x"}]}))
        self.assertIn("BizInt health", out["html"])
        self.assertIn("Noisiest recipes", out["html"])
        self.assertIn("#7C3AED", out["html"])
        self.assertIn("Jira board", out["html"])

    def test_daily_period(self):
        out = self.run_rows(period_days="1", trend_periods="14", daily_days="14")
        self.assertTrue(out["ok"], out["error"])
        self.assertEqual(out["period_label"], "19 Nov 2026")
        self.assertIn("Daily report", out["html"])


# ------------------------------------------------------------------------------------------------- outputs


class TestOutputs(Base):
    def test_subject_and_text(self):
        out = self.run_rows()
        self.assertRegex(out["subject"], r"^\S+ Workato Integrations Health · 13–19 Nov · 68 errors \(▲48%\)$")
        custom = self.run_rows(subject_format="[{ENV}] {errors} errors, grade {grade}, next ~{forecast}")
        self.assertRegex(custom["subject"], r"^\[PRODUCTION\] 68 errors, grade [A-F], next ~\d+$")
        self.assertIn("Top failing recipes:", out["text_body"])
        self.assertIn("<https://app.workato.com/recipes/200|Invoice Sync>", out["slack_text"])

    def test_structured_outputs(self):
        out = self.run_rows()
        self.assertEqual(out["top_recipes"][0]["name"], "Invoice Sync")
        self.assertEqual(out["top_recipes"][0]["errors"], 30)
        self.assertEqual(out["top_recipes"][0]["status"], "spike")
        self.assertTrue(out["top_patterns"][0]["signature"])
        self.assertEqual((out["records_failed"], out["backlog_open"], out["spikes"]), (70, 5, 1))
        summary = json.loads(out["summary_json"])
        self.assertEqual(summary["errors_total"], 68)
        self.assertEqual(len(summary["weekly"]), 12)
        for key, _ in dash.OUTPUT_DEFAULTS:
            self.assertIn(key, out)

    def test_skip_if_empty(self):
        rows = [r for r in self.world if r["Date"] < "2026-11-13"]
        self.assertTrue(self.run_rows(rows)["send_email"])
        self.assertFalse(self.run_rows(rows, skip_if_empty="yes")["send_email"])


class TestNeverFails(Base):
    def test_bad_inputs(self):
        for data in ({"rows_json": "not json", "now": NOW}, {"rows_json": "[]", "now": NOW},
                     {"rows_json": json.dumps([{"Date": "garbage"}, 5, None]), "now": NOW},
                     {"rows_json": "[]", "now": "garbage", "timezone": "Mars/Base"},
                     {"rows_json": json.dumps(self.world), "now": NOW, "period_end": "31/12/2026", "trend_periods": "x"}):
            out = dash.main(data)
            self.assertIn("html", out)
            self.assertTrue(out["html"].startswith("<!DOCTYPE html>"), data)
        self.assertFalse(dash.main({"rows_json": "not json", "now": NOW})["ok"])
        self.assertTrue(dash.main({"rows_json": "[]", "now": NOW})["ok"])
        self.assertTrue(dash.main(None)["html"])

    def test_exception_inside_is_caught(self):
        original = dash.analyze
        dash.analyze = lambda ctx: 1 / 0
        try:
            out = self.run_rows()
        finally:
            dash.analyze = original
        self.assertFalse(out["ok"])
        self.assertIn("ZeroDivisionError", out["error"])
        self.assertIn("could not be built", out["html"])


# ------------------------------------------------------------------------------------------------- schemas


class TestSchemas(unittest.TestCase):
    def test_input_schema_file(self):
        with open(os.path.join(HERE, "error_dashboard_input_schema.json"), encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertEqual([f["name"] for f in schema], list(dash.INPUT_NAMES))
        self.assertEqual(schema, dash.input_schema(), "run: python3 error_dashboard.py --write-schemas")
        names = next(f for f in schema if f["name"] == "sections")["hint"]
        for section in dash.DEFAULT_SECTIONS:
            self.assertIn(section, names)

    def test_output_schema_file(self):
        with open(os.path.join(HERE, "error_dashboard_output_schema.json"), encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertEqual([f["name"] for f in schema], [k for k, _ in dash.OUTPUT_DEFAULTS])
        self.assertEqual(schema, dash.output_schema(), "run: python3 error_dashboard.py --write-schemas")

    def test_categories_match_error_notification(self):
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(HERE), "error_notification"))
            import error_notification as en
        except ImportError:
            self.skipTest("error_notification.py is not in the ../error_notification folder")
        self.assertEqual(dash.CATEGORIES, en.CATEGORIES)
        self.assertEqual(dash.EXTRA_RULES, en.EXTRA_RULES)                  # the extra rules too: same category in alert and dashboard

    def test_every_setting_has_help(self):
        for name in dash.INPUT_NAMES:
            self.assertIn(name, dash.INPUT_HELP)


class TestRealExport(unittest.TestCase):
    CSV = os.path.join(os.path.dirname(HERE), "data_table_error_notification_tbl.csv")

    @unittest.skipUnless(os.path.exists(CSV), "the data table export is not here")
    def test_dashboard_from_the_export(self):
        rows = dash.load_csv(self.CSV)
        out = dash.main({"rows_json": rows, "now": NOW})
        self.assertTrue(out["ok"], out["error"])
        self.assertGreater(out["errors_total"], 0)
        self.assertLessEqual(out["html_bytes"], 100 * 1024)
        self.assertTrue(out["top_recipes"])
        self.assertLess(out["elapsed_ms"], 30000)


if __name__ == "__main__":
    unittest.main()
