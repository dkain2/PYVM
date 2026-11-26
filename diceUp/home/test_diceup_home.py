"""
Tests for diceup_home.py. Run them before and after any change:

    python3 test_diceup_home.py          # all of them
    python3 test_diceup_home.py -v       # with the name of each

Nothing here touches the network: World stands in for Slack (views.publish, chat.postMessage, conversations.join,
chat.getPermalink) and the DiceUp data table (query, with paging), and refuses a view Slack would refuse (too many blocks,
a text too long, a block id used twice).

THE GROUPS
    TestEnv        dev / prod pick the DiceUp table of their workspace
    TestStats      games played, live, cancelled; the earliest win holds a prize; the organizer plays; periods; opt-out
    TestProfile    the viewer across games, all time: totals, journeys, badges and the day each was earned
    TestView       the page against Slack's limits, every feature switched off in turn, the plain view, games_json
    TestPublish    a refused feature is taken out and the view published again, down to the plain view
    TestClicks     Start (no channel, a channel, not in it, a private one), the period, the picker, other presses
    TestPaging     continuation tokens are followed, and a cap says the stats are partial
"""

import copy
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diceup_home as h                                                    # noqa: E402

NOW = 1764158400.0          # 2026-11-26 12:00 UTC
DAY = 86400


# --------------------------------------------------------------------------------------------- Slack's limits

def every_block(blocks):
    for b in blocks:
        yield b
        if b.get("type") == "carousel":
            for card in b.get("elements", []):
                yield card
        elif b.get("type") == "layout":
            for row in b.get("rows", []):
                for item in row.get("items", []):
                    yield from every_block([item["block"]])
        elif b.get("type") == "container":
            yield from every_block(b.get("child_blocks", []))
        elif b.get("type") == "condition":
            for case in b.get("cases", []):
                yield from every_block(case.get("blocks", []))
            yield from every_block(b.get("default", []))


def check_view(view):
    """Raise AssertionError if Slack would turn this home view down."""
    assert view["type"] == "home"
    assert len(view["blocks"]) <= 100, "too many blocks: {}".format(len(view["blocks"]))
    assert len(view.get("private_metadata", "")) <= 3000
    ids = [b["block_id"] for b in every_block(view["blocks"]) if b.get("block_id")]
    assert len(ids) == len(set(ids)), "a block id is used twice: {}".format([i for i in ids if ids.count(i) > 1])
    for b in every_block(view["blocks"]):
        kind = b.get("type")
        if kind == "section":
            assert "text" in b or "fields" in b
            if "text" in b:
                assert 0 < len(b["text"]["text"]) <= 3000
            assert len(b.get("fields", [])) <= 10
            for f in b.get("fields", []):
                assert len(f["text"]) <= 2000
        if kind == "header":
            assert len(b["text"]["text"]) <= 150
        if kind == "context":
            assert 0 < len(b["elements"]) <= 10
        if kind == "card":
            assert len(b["body"]["text"]) <= 200, b["body"]["text"]
            assert len(b["title"]["text"]) <= 150
            assert len(b.get("actions", [])) <= 3
        if kind == "carousel":
            assert 0 < len(b["elements"]) <= 10
        if kind == "actions":
            assert 0 < len(b["elements"]) <= 25
        for el in b.get("elements", []) if kind in ("actions",) else []:
            if el.get("type") == "button":
                assert len(el["text"]["text"]) <= 75
                assert el.get("url") or el["action_id"].startswith(h.ACTION_PREFIX)
            if el.get("url"):
                assert el["action_id"].startswith(h.LINK_PREFIX)
        acc = b.get("accessory") or {}
        if acc.get("url"):
            assert acc["action_id"].startswith(h.LINK_PREFIX)


def types_in(view):
    return {b.get("type") for b in every_block(view["blocks"])}


# --------------------------------------------------------------------------------------------- the world

class World(object):
    """The network. rows: the table's rows (DiceUp column names). refuse: block types Slack answers invalid_blocks to
    (with the pointer when point is on). outside: channels the bot is not in; joinable: those it may join."""

    def __init__(self, rows=(), refuse=(), point=True, outside=(), joinable=(), page=None):
        self.rows = [dict(r) for r in rows]
        self.refuse, self.point = set(refuse), point
        self.outside, self.joinable = set(outside), set(joinable)
        self.page = page
        self.calls, self.views, self.posts, self.queries = [], [], [], []

    def __call__(self, url, headers, payload=None, method="POST", timeout=None):
        self.calls.append((url, payload))
        if url.startswith(h.DATA_TABLES_API):
            return self.query(url, payload)
        method_name = url[len(h.SLACK_API):].split("?")[0]
        return getattr(self, "slack_" + method_name.replace(".", "_"))(url, payload)

    # the table
    def query(self, url, payload):
        self.queries.append((url, payload))
        rows = [r for r in self.rows if self.matches(r, payload["where"])]
        start = int(payload.get("continuation_token") or 0)
        size = self.page or payload.get("limit", 200)
        chunk = rows[start:start + size]
        names = payload.get("select") or sorted({k for r in self.rows for k in r})
        body = {"schema": [[{"name": "$record_id"}], [{"name": n} for n in names]],
                "data": [[["r{}".format(start + i)], [r.get(n) for n in names]] for i, r in enumerate(chunk)]}
        if start + size < len(rows):
            body["continuation_token"] = str(start + size)
        return body, None

    def matches(self, row, where):
        if "$and" in where:
            return all(self.matches(row, w) for w in where["$and"])
        for column, cond in where.items():
            if "$eq" in cond and row.get(column) != cond["$eq"]:
                return False
            if "$in" in cond and row.get(column) not in cond["$in"]:
                return False
        return True

    # Slack
    def slack_views_publish(self, url, payload):
        view = payload["view"]
        check_view(view)
        for i, block in enumerate(view["blocks"]):
            kind = block.get("type")
            if (kind in self.refuse and kind != "header") or (kind == "header" and "level" in block and "header" in self.refuse):
                detail = {"ok": False, "error": "invalid_blocks"}
                if self.point:
                    detail["response_metadata"] = {"messages": ["[ERROR] unsupported type [json-pointer:/blocks/{}/type]".format(i)]}
                return detail, None
        self.views.append(payload)
        return {"ok": True, "view": {"id": "V1"}}, None

    def slack_chat_postMessage(self, url, payload):
        if payload["channel"] in self.outside:
            return {"ok": False, "error": "not_in_channel"}, None
        self.posts.append(payload)
        return {"ok": True, "ts": "1764158400.000200", "channel": payload["channel"]}, None

    def slack_conversations_join(self, url, payload):
        if payload["channel"] in self.joinable:
            self.outside.discard(payload["channel"])
            return {"ok": True}, None
        return {"ok": False, "error": "missing_scope"}, None

    def slack_chat_getPermalink(self, url, payload):
        return {"ok": True, "permalink": "https://example.slack.com/archives/X/p1"}, None


def game(gid, host, status="done", channel="C0000001", days_ago=1, hours_ago=None):
    ts = NOW - (hours_ago * 3600 if hours_ago is not None else days_ago * DAY)
    return {"record_type": "tambola", "row_type": "tambola_game", "game_id": gid, "slack_user_id": host, "status": status,
            "slack_channel_id": channel, "last_processed_ts": "{:.6f}".format(ts),
            "day_key": h.datetime.fromtimestamp(ts, h.timezone.utc).strftime("%Y-%m-%d")}


def player(gid, uid):
    return {"record_type": "tambola", "row_type": "tambola_player", "game_id": gid, "slack_user_id": uid}


def win(gid, uid, prize, ts_offset=0.0, days_ago=1):
    return {"record_type": "tambola", "row_type": "tambola_win", "game_id": gid, "slack_user_id": uid, "sub_type": prize,
            "last_processed_ts": "{:.6f}".format(NOW - days_ago * DAY + ts_offset), "source_ref": "t{}".format(ts_offset)}


def sample_rows():
    rows = []
    for n in range(6):                                   # six finished games, UA hosts four, UB two
        gid = "g{}".format(n)
        rows.append(game(gid, "UA" if n < 4 else "UB", days_ago=n * 10 + 1, channel="C000000{}".format(n % 2)))
        for uid in ("UA", "UB", "UC"):
            rows.append(player(gid, uid))
        rows.append(win(gid, "UB", "full", 50, days_ago=n * 10 + 1))
        rows.append(win(gid, "UA", "early5", 10, days_ago=n * 10 + 1))
        rows.append(win(gid, "UC", "early5", 20, days_ago=n * 10 + 1))     # later: UA holds Early Five
    rows.append(game("live1", "UC", status="running", hours_ago=1))
    rows.append(game("stale", "UC", status="running", hours_ago=30))      # past live_hours: abandoned
    rows.append(game("lob", "UD", status="lobby", hours_ago=3))           # past lobby_hours
    rows.append(game("cx", "UD", status="cancelled", days_ago=2))
    return rows


def run(world, **inp):
    base = {"user_id": "UA", "slack_bot_token": "xoxb", "workato_api_token": "wk", "now": str(NOW)}
    base.update(inp)
    saved = h._send_json, h._sleep
    h._send_json, h._sleep = world, (lambda s: None)
    try:
        return h.main(base)
    finally:
        h._send_json, h._sleep = saved


def published(world):
    return world.views[-1]["view"] if world.views else None


def view_text(view):
    return json.dumps(view, ensure_ascii=False)


def spec():
    return h.game_list("", [])[0]


# --------------------------------------------------------------------------------------------- the tests

class TestEnv(unittest.TestCase):
    def test_dev_reads_the_dev_table(self):
        w = World(sample_rows())
        run(w, env="dev")
        self.assertTrue(all(h.TABLE_IDS["dev"] in u for u, _p in w.queries))

    def test_prod_blank_or_anything_else_reads_prod(self):
        for env in ("prod", "", None, "PROD ", "staging"):
            w = World(sample_rows())
            out = run(w, env=env)
            self.assertEqual(out["env"], "prod")
            self.assertTrue(all(h.TABLE_IDS["prod"] in u for u, _p in w.queries), env)

    def test_dev_says_so_on_the_page(self):
        w = World(sample_rows())
        run(w, env="dev")
        self.assertIn("DEV data", view_text(published(w)))


class TestStats(unittest.TestCase):
    def stats(self, rows, period="all", viewer="UA", hidden=()):
        return h.game_stats(rows, spec(), period, NOW, viewer, set(hidden))

    def test_counts(self):
        s = self.stats(sample_rows())
        self.assertEqual(s["played"], 6)
        self.assertEqual([g["id"] for g in s["live"]], ["live1"])          # stale and the old lobby are not live
        self.assertEqual(s["counted"], 7)                                  # six done and the live one
        self.assertEqual(s["cancelled"], 1)
        self.assertEqual(s["players"], 3)                                  # the live game's host UC was already a player
        self.assertEqual(s["prizes"], 12)
        self.assertEqual(s["grand"], 6)

    def test_the_earliest_press_holds_a_prize(self):
        s = self.stats(sample_rows())
        board = {w["uid"]: w for w in s["winners"]}
        self.assertEqual(board["UA"]["prizes"], 6)                          # every Early Five
        self.assertNotIn("UC", board)                                       # pressed later every time
        self.assertEqual(board["UB"]["grand"], 6)

    def test_ties_share_a_rank_and_grand_prizes_break_them(self):
        s = self.stats(sample_rows())
        self.assertEqual([(w["uid"], w["rank"]) for w in s["winners"]], [("UB", 1), ("UA", 2)])   # 6 and 6: Full Houses
        rows = [game("t1", "UA"), game("t2", "UA", days_ago=2),
                win("t1", "UA", "early5", 1), win("t1", "UA", "top", 2), win("t1", "UB", "full", 3),
                win("t2", "UB", "middle", 1, days_ago=2), win("t2", "UC", "full", 2, days_ago=2), win("t2", "UC", "top", 3, days_ago=2)]
        s = self.stats(rows)
        self.assertEqual([(w["uid"], w["rank"]) for w in s["winners"]], [("UB", 1), ("UC", 1), ("UA", 3)])

    def test_the_organizer_always_plays(self):
        rows = [game("solo", "UZ")]
        s = self.stats(rows, viewer="UZ")
        self.assertEqual(s["players"], 1)
        self.assertEqual(s["you"]["games"], 1)
        self.assertEqual(s["you"]["hosted"], 1)

    def test_two_rows_for_a_game_count_once(self):
        rows = [game("dup", "UA"), dict(game("dup", "UA"), status="cancelled",
                                         last_processed_ts="{:.6f}".format(NOW - DAY + 5))]
        s = self.stats(rows)
        self.assertEqual(s["played"], 1)
        self.assertEqual(s["cancelled"], 0)

    def test_period(self):
        s = self.stats(sample_rows(), period="30")
        self.assertEqual(s["played"], 3)                                    # 1, 11 and 21 days ago
        s = self.stats(sample_rows(), period="7")
        self.assertEqual(s["played"], 1)
        self.assertEqual(len(s["timeline"]), 7)
        self.assertEqual(sum(v for _l, v in s["timeline"]), 2)              # yesterday's and the live one

    def test_opt_out_hides_from_lists_not_totals(self):
        s = self.stats(sample_rows(), hidden={"UB"})
        self.assertNotIn("UB", [w["uid"] for w in s["winners"]])
        self.assertEqual(s["prizes"], 12)
        self.assertEqual(s["players"], 3)

    def test_rows_of_other_games_are_ignored(self):
        rows = sample_rows() + [dict(game("x", "UA"), record_type="trivia")]
        self.assertEqual(self.stats(rows)["played"], 6)

    def test_period_names(self):
        for given, want in (("7", "7"), ("30 days", "30"), ("90d", "90"), ("all", "all"), ("", "all"), ("junk", "all")):
            self.assertEqual(h.period_of(given), want, given)


class TestProfile(unittest.TestCase):
    def profile(self, rows, viewer="UA"):
        games = h.game_list("", [])
        stats = {g["key"]: h.game_stats(rows, g, "all", NOW, viewer, set()) for g in games}
        return h.profile(games, stats, viewer)

    def test_totals_and_badges(self):
        p = self.profile(sample_rows())
        self.assertEqual(p["total"], {"games": 6, "prizes": 6, "grand": 0, "hosted": 4})
        names = {(b["journey"]["name"], b["tier"]) for b in p["badges"]}
        self.assertIn(("Tambola Regular", "Silver"), names)                 # 6 games: 1 and 5 reached
        self.assertNotIn(("Tambola Regular", "Gold"), names)
        self.assertIn(("Prize Hunter", "Silver"), names)
        self.assertIn(("Game Host", "Bronze"), names)
        self.assertNotIn("Full House Collector", {n for n, _t in names})

    def test_a_badge_is_earned_on_the_day_of_the_game_that_reached_it(self):
        p = self.profile(sample_rows())
        silver = next(b for b in p["badges"] if b["journey"]["name"] == "Tambola Regular" and b["tier"] == "Silver")
        stamps = sorted(g["when"] for g in [{"when": h.when_of(r)} for r in sample_rows()
                                            if r.get("row_type") == "tambola_game" and r["game_id"] not in ("stale", "lob", "cx")])
        self.assertEqual(silver["when"], stamps[4])                          # the fifth game

    def test_journey_status_and_text(self):
        p = self.profile(sample_rows(), viewer="UB")
        by = {j["journey"]["name"]: j for j in p["journeys"]}
        self.assertEqual(by["Full House Collector"]["status"], "live")        # 6: 1 and 3 reached, 10 not
        text = h.journey_text(by["Full House Collector"])
        self.assertIn("2 / 3", text)
        self.assertEqual(text.count("✅"), 2)
        self.assertEqual(text.count("⬜"), 1)

    def test_nobody_new_has_no_badges(self):
        p = self.profile(sample_rows(), viewer="UNEW")
        self.assertEqual(p["badges"], [])
        self.assertTrue(all(j["status"] == "new" for j in p["journeys"]))

    def test_profile_is_all_time_whatever_the_period(self):
        w = World(sample_rows())
        out = run(w, period="7")                                               # one of UA's games is in the last 7 days
        self.assertEqual(out["your_games"], 6)
        self.assertEqual(json.loads(out["your_stats_json"])["per_game"]["tambola"]["games"], 6)

    def test_a_game_without_a_grand_prize_has_no_grand_journey(self):
        games = h.game_list('[{"key": "trivia", "name": "Trivia"}]', [])
        trivia = next(g for g in games if g["key"] == "trivia")
        self.assertNotIn("grand", [j["metric"] for j in h.journeys_of(trivia)])

    def test_custom_journeys(self):
        games = h.game_list('[{"key": "tambola", "journeys": [{"key": "p", "name": "Marathon", "metric": "games", '
                            '"steps": [2, 4], "step": "Play {n} games"}]}]', [])
        js = h.journeys_of(games[0])
        self.assertEqual([j["name"] for j in js], ["Marathon"])
        self.assertEqual(js[0]["labels"], ["Play 2 games", "Play 4 games"])


class TestView(unittest.TestCase):
    def test_the_full_page_fits(self):
        w = World(sample_rows())
        out = run(w)
        self.assertTrue(out["ok"], out)
        view = published(w)
        check_view(view)
        for wanted in ("carousel", "layout", "data_visualization", "data_table", "container"):
            self.assertIn(wanted, types_in(view), wanted)
        text = view_text(view)
        self.assertIn('"conversations_select"', text)
        for part in ("Available games", "Your DiceUp", "My achievements", "My journeys", "At a glance", "Tambola stats",
                     "Live now", "Start Tambola"):
            self.assertIn(part, text, part)

    def test_each_feature_switched_off(self):
        gone = {"cards": "carousel", "tiles": "layout", "charts": "data_visualization", "panels": "container",
                "datatables": "data_table"}
        for feature, kind in gone.items():
            w = World(sample_rows())
            run(w, features="-" + feature)
            view = published(w)
            check_view(view)
            self.assertNotIn(kind, types_in(view), feature)
            self.assertIn("Start Tambola", view_text(view), feature)

    def test_the_plain_view(self):
        w = World(sample_rows())
        out = run(w, features="none")
        view = published(w)
        check_view(view)
        self.assertLessEqual(types_in(view), {"header", "section", "context", "actions", "divider"})
        self.assertEqual(out["look_used"], "plain")
        self.assertIn("Start Tambola", view_text(view))
        self.assertIn("<@UB>", view_text(view))                              # the winners board as lines

    def test_adaptive_is_off_unless_asked(self):
        w = World(sample_rows())
        run(w)
        self.assertNotIn("condition", types_in(published(w)))
        w = World(sample_rows())
        run(w, features="+adaptive")
        self.assertIn("condition", types_in(published(w)))

    def test_an_empty_table(self):
        w = World([])
        out = run(w)
        self.assertTrue(out["ok"])
        text = view_text(published(w))
        self.assertIn("No Tambola games in this period yet", text)
        self.assertIn("You have not played a game yet", text)

    def test_coming_soon_and_disabled_games(self):
        w = World(sample_rows())
        run(w, games_json='[{"key": "trivia", "name": "Trivia", "emoji": ":brain:", "coming_soon": true}]')
        view = published(w)
        cards = [b for b in every_block(view["blocks"]) if b.get("type") == "card" and "Trivia" in b["title"]["text"]]
        self.assertEqual(len(cards), 1)
        self.assertNotIn("actions", cards[0])
        self.assertNotIn("Trivia stats", view_text(view))
        w = World(sample_rows())
        out = run(w, games_json='{"key": "tambola", "enabled": false}')
        self.assertNotIn("Tambola", view_text(published(w)).replace("DiceUp", ""))
        self.assertEqual(out["games_shown"], 0)

    def test_bad_games_json_is_a_warning(self):
        w = World(sample_rows())
        out = run(w, games_json="not json")
        self.assertTrue(out["ok"])
        self.assertTrue(any("games_json" in x for x in out["warnings"]))

    def test_many_games_still_fit(self):
        extra = json.dumps([{"key": "game{}".format(n), "name": "Game {}".format(n)} for n in range(12)])
        rows = sample_rows() + [dict(r, record_type="game{}".format(n), row_type=r["row_type"].replace("tambola", "game{}".format(n)))
                                for n in range(12) for r in sample_rows()]
        w = World(rows)
        out = run(w, games_json=extra)
        self.assertTrue(out["ok"], out)
        check_view(published(w))

    def test_preview_publishes_nothing(self):
        w = World(sample_rows())
        out = run(w, preview="yes", slack_bot_token="")
        self.assertTrue(out["ok"])
        self.assertFalse(out["published"])
        self.assertEqual(w.views, [])
        check_view(json.loads(out["view_json"]))

    def test_the_messages_tab_is_skipped(self):
        w = World(sample_rows())
        out = run(w, tab="messages")
        self.assertTrue(out["ok"])
        self.assertTrue(out["skipped"])
        self.assertEqual(w.calls, [])

    def test_needs_a_user_and_a_token(self):
        self.assertIn("user_id", run(World(), user_id="")["error"])
        self.assertIn("slack_bot_token", run(World(), slack_bot_token="")["error"])

    def test_no_workato_token_still_shows_the_games(self):
        w = World(sample_rows())
        out = run(w, workato_api_token="")
        self.assertTrue(out["ok"])
        self.assertIn("Start Tambola", view_text(published(w)))
        self.assertEqual(w.queries, [])

    def test_the_period_is_kept_in_private_metadata(self):
        w = World(sample_rows())
        run(w, private_metadata='{"p": "30", "c": "C0000009"}')
        view = published(w)
        self.assertEqual(json.loads(view["private_metadata"]), {"p": "30", "c": "C0000009"})
        picker = next(b for b in view["blocks"] if b.get("block_id") == h.WHERE_BLOCK)["elements"][0]
        self.assertEqual(picker["initial_conversation"], "C0000009")


class TestPublish(unittest.TestCase):
    def test_a_named_refused_feature_is_taken_out(self):
        w = World(sample_rows(), refuse={"data_visualization"})
        out = run(w)
        self.assertTrue(out["ok"], out)
        self.assertNotIn("charts", out["look_used"])
        self.assertIn("layout", types_in(published(w)))                       # nothing else was dropped
        self.assertTrue(any("charts" in x for x in out["warnings"]))

    def test_without_a_pointer_the_likeliest_go_first(self):
        w = World(sample_rows(), refuse={"carousel"}, point=False)
        out = run(w)
        self.assertTrue(out["ok"], out)
        self.assertNotIn("cards", out["look_used"])
        self.assertNotIn("charts", out["look_used"])                          # peeled before cards

    def test_down_to_the_plain_view(self):
        w = World(sample_rows(), refuse={"carousel", "layout", "data_visualization", "container", "data_table", "table",
                                         "rich_text", "header"})
        out = run(w)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["look_used"], "plain")

    def test_another_error_is_final(self):
        def broken(url, payload):
            return {"ok": False, "error": "not_authed"}, None
        w = World(sample_rows())
        w.slack_views_publish = broken
        out = run(w)
        self.assertFalse(out["ok"])
        self.assertIn("not_authed", out["error"])


def click(action_id, channel="", user="UA", value="", period="", metadata=None):
    state = {"values": {h.WHERE_BLOCK: {h.ACT_CHANNEL: {"type": "conversations_select", "selected_conversation": channel or None}}}}
    action = {"action_id": action_id, "value": value}
    if period:
        action["selected_option"] = {"value": period}
    payload = {"type": "block_actions", "user": {"id": user}, "actions": [action],
               "view": {"type": "home", "state": state, "private_metadata": json.dumps(metadata or {"p": "all"})}}
    return json.dumps(payload)


class TestClicks(unittest.TestCase):
    def test_start_without_a_channel(self):
        w = World(sample_rows())
        out = run(w, payload=click(h.ACT_START + "tambola"))
        self.assertTrue(out["ok"])
        self.assertEqual(out["start_game"], "")
        self.assertEqual(w.posts, [])
        self.assertIn("Pick a channel first", view_text(published(w)))

    def test_start_in_a_channel(self):
        w = World(sample_rows())
        out = run(w, payload=click(h.ACT_START + "tambola", channel="C0000042"))
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["start_game"], out["start_text"], out["start_channel"], out["start_user_id"]),
                         ("tambola", "itambola", "C0000042", "UA"))
        self.assertEqual(out["start_message_ts"], "1764158400.000200")
        self.assertEqual(w.posts[0]["channel"], "C0000042")
        self.assertIn("<@UA>", w.posts[0]["text"])
        view = published(w)
        notice = next(b for b in view["blocks"] if b.get("block_id") == "dh_notice")
        self.assertIn("on its way", notice["text"]["text"])
        self.assertTrue(notice["accessory"]["url"].startswith("https://"))
        self.assertEqual(json.loads(view["private_metadata"])["c"], "C0000042")     # the picker remembers it

    def test_start_joins_a_public_channel_it_is_not_in(self):
        w = World(sample_rows(), outside={"C0000042"}, joinable={"C0000042"})
        out = run(w, payload=click(h.ACT_START + "tambola", channel="C0000042"))
        self.assertEqual(out["start_game"], "tambola")
        self.assertEqual(len(w.posts), 1)

    def test_start_in_a_channel_it_cannot_join(self):
        for channel in ("C0000042", "G0000042"):
            w = World(sample_rows(), outside={channel})
            out = run(w, payload=click(h.ACT_START + "tambola", channel=channel))
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["start_game"], "")
            self.assertIn("/invite", view_text(published(w)))

    def test_start_without_the_announcement(self):
        w = World(sample_rows())
        out = run(w, payload=click(h.ACT_START + "tambola", channel="C0000042"), announce_start="no")
        self.assertEqual(out["start_game"], "tambola")
        self.assertEqual(out["start_message_ts"], "")
        self.assertEqual(w.posts, [])

    def test_a_coming_soon_game_cannot_start(self):
        w = World(sample_rows())
        out = run(w, payload=click(h.ACT_START + "trivia", channel="C0000042"),
                  games_json='[{"key": "trivia", "coming_soon": true}]')
        self.assertEqual(out["start_game"], "")
        self.assertEqual(w.posts, [])

    def test_the_period_dropdown(self):
        w = World(sample_rows())
        out = run(w, payload=click(h.ACT_PERIOD, period="7"))
        self.assertEqual(out["period"], "7")
        self.assertEqual(json.loads(published(w)["private_metadata"])["p"], "7")
        self.assertIn("Last 7 days", view_text(published(w)))

    def test_refresh_keeps_the_period(self):
        w = World(sample_rows())
        out = run(w, payload=click(h.ACT_REFRESH, metadata={"p": "90"}))
        self.assertEqual(out["period"], "90")

    def test_picking_a_channel_does_nothing(self):
        w = World(sample_rows())
        out = run(w, payload=click(h.ACT_CHANNEL, channel="C0000042"))
        self.assertTrue(out["ok"])
        self.assertEqual(w.calls, [])

    def test_another_apps_press_is_skipped(self):
        w = World(sample_rows())
        out = run(w, payload=click("tambola_click_next"))
        self.assertTrue(out["ok"])
        self.assertTrue(out["skipped"])
        self.assertEqual(w.calls, [])

    def test_fields_mapped_by_hand(self):
        w = World(sample_rows())
        out = run(w, action_id=h.ACT_START + "tambola", selected_channel="C0000042")
        self.assertEqual(out["start_channel"], "C0000042")

    def test_workato_wrapper(self):
        w = World(sample_rows())
        wrapped = json.dumps({"block_actions:button": json.loads(click(h.ACT_START + "tambola", channel="C0000042"))})
        out = run(w, payload=wrapped)
        self.assertEqual(out["start_channel"], "C0000042")


class TestPaging(unittest.TestCase):
    def test_pages_are_followed(self):
        w = World(sample_rows(), page=5)
        out = run(w)
        self.assertEqual(out["rows_read"], len(sample_rows()))
        self.assertFalse(out["partial"])

    def test_a_cap_says_the_stats_are_partial(self):
        w = World(sample_rows(), page=5)
        out = run(w, max_pages="2")
        self.assertEqual(out["rows_read"], 10)
        self.assertTrue(out["partial"])
        self.assertIn("first 10 rows", view_text(published(w)))

    def test_a_failed_read_says_so(self):
        w = World(sample_rows())
        w.query = lambda url, payload: (None, "HTTP 500 data-tables: boom")
        out = run(w)
        self.assertTrue(out["ok"])
        self.assertIn("could not be read", view_text(published(w)))
        self.assertTrue(any("boom" in x for x in out["warnings"]))


if __name__ == "__main__":
    unittest.main()
