"""
Tests for tambola.py. Run them before and after any change, so a change that breaks the game is caught here and not
in a live channel:

    python3 test_tambola.py                       # all of them
    python3 test_tambola.py -v                    # with the name of each
    python3 -m unittest test_tambola.TestReview   # one group

Nothing here touches the network, Slack or Workato, and it needs nothing beyond the standard library.

THE GROUPS
    TestLargeGameUnchanged   the numbers and tickets of a large game are pinned to what the step dealt before game
                             sizes existed (a game in progress is re-dealt from its seed, so these must never move)
    TestSizes                small / medium / large: names, aliases, the typed word, the settings a game keeps
    TestDealing              the order the numbers come out in and the tickets, for every size
    TestPrizes               prizes, progress and the review's steps at every ticket size
    TestCards                every card of every size, checked against Slack's Block Kit limits
    TestReview               the ranked table of the review: a hundred players, ties, top_n, odd names
    TestButtons              what a button carries and how it is read back, test games included
    TestGames                whole games played through main(), the way the two recipes call it, against a stand-in
                             for Slack and for the data table (see World)

THE WORLD
    World replaces the network (tambola._send_json), the waiting (_sleep) and the clock (_now). It answers the Slack
    calls the step makes (post, update, delete, private notes, members, users, a message read back, the press's
    response_url) and the Workato data table (query, create, update), keeps every message, and refuses any message
    Slack would refuse (too many blocks, a text or a button value too long): a card that Slack would turn down is a
    failure here too. Presses are made from the buttons that were really posted, never built by hand.
"""

import hashlib
import html
import json
import os
import re
import sys
import threading
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tambola as t                                                       # noqa: E402


# --------------------------------------------------------------------------
# Slack's limits, and a few shortcuts
# --------------------------------------------------------------------------

def check_blocks(blocks):
    """Raise AssertionError if Slack would turn these blocks down."""
    assert isinstance(blocks, list), "blocks must be a list"
    assert len(blocks) <= 50, "{} blocks, Slack takes 50".format(len(blocks))
    for block in blocks:
        kind = block.get("type")
        if "block_id" in block:
            assert len(block["block_id"]) <= 255, "block_id of {} characters".format(len(block["block_id"]))
        if kind == "header":
            assert len(block["text"]["text"]) <= 150, "header over 150 characters"
        elif kind == "section":
            assert block.get("text") or block.get("fields"), "a section needs text or fields"
            if block.get("text"):
                assert len(block["text"]["text"]) <= 3000, "section text of {} characters".format(
                    len(block["text"]["text"]))
            assert len(block.get("fields") or []) <= 10, "more than 10 fields"
            for field in block.get("fields") or []:
                assert len(field["text"]) <= 2000, "field over 2000 characters"
            if block.get("accessory"):
                check_element(block["accessory"])
        elif kind == "context":
            assert 1 <= len(block["elements"]) <= 10, "context needs 1 to 10 elements"
            for element in block["elements"]:
                assert len(element["text"]) <= 3000, "context text over 3000 characters"
        elif kind == "actions":
            assert 1 <= len(block["elements"]) <= 25, "actions need 1 to 25 elements"
            for element in block["elements"]:
                check_element(element)
        else:
            raise AssertionError("unexpected block type {!r}".format(kind))


def check_element(element):
    if element["type"] == "button":
        assert len(element["text"]["text"]) <= 75, "button text over 75 characters"
        assert len(element["action_id"]) <= 255, "action_id over 255 characters"
        assert len(element.get("value", "")) <= 2000, "button value of {} characters".format(len(element["value"]))
    else:
        assert len(element["action_id"]) <= 255, "action_id over 255 characters"
        assert len(element.get("options") or []) <= 100, "menu with more than 100 options"


def buttons_of(blocks):
    return [e for b in blocks if b["type"] == "actions" for e in b["elements"] if e["type"] == "button"]


def button_named(blocks, suffix):
    found = [b for b in buttons_of(blocks) if b["action_id"] == t.ACTION_PREFIX + suffix]
    assert found, "no {} button among {}".format(suffix, [b["action_id"] for b in buttons_of(blocks)])
    return found[0]


def all_text(blocks):
    """Every piece of text in some blocks, for looking something up in a card."""
    parts = []
    for block in blocks:
        if block.get("text"):
            parts.append(block["text"]["text"])
        parts += [f["text"] for f in block.get("fields") or []]
        parts += [e.get("text") if isinstance(e.get("text"), str) else (e.get("text") or {}).get("text", "")
                  for e in block.get("elements") or []]
    return "\n".join(parts)


def grid_sections(blocks):
    """The rows of the board's grid: the sections made only of squares and keycap digits."""
    return [b for b in blocks if b["type"] == "section" and b.get("text")
            and re.fullmatch(r"(?::[a-z_]+:\s?)+", b["text"]["text"])]


def code_table(blocks):
    """The lines of the review's table (header first), or [] if the card has none."""
    for block in blocks:
        text = (block.get("text") or {}).get("text", "")
        if text.startswith("```"):
            return text.strip("`\n").split("\n")
    return []


HOST = "UHOST0001"


def make_game(size="large", test=False, n=0, seed=20261109, status=t.RUNNING, players=4, **settings):
    """A game as the step holds it, with a roster, for the pure tests."""
    config = t.game_config(dict({"size": size}, **settings))
    g = t.new_game("tb_C0TEST_1700000000000100", "C0TEST", HOST, "Tambola", config, test)
    ids = [HOST] + ["U%07d" % i for i in range(1, players)]
    g.update(host_name="Priya Sharma", mode="open", status=status, seed=seed, n=n, roster=ids,
             names={u: "Player {}".format(u) for u in ids}, lobby_ts="1700000000.000050",
             board_ts="1700000000.000100")
    return g


def make_players(g, count, marks=None):
    """`count` players of this game with a ticket each, [{name, ticket, marks}]; `marks[i]` numbers marked by player i
    (the first ones on their ticket), default a spread from none to all."""
    size = t.ticket_size_of(g)
    out = []
    for i in range(count):
        ticket = t.make_ticket(g["seed"], "U%07d" % i, g["cfg"]["size"])
        want = marks[i] if marks is not None else i % (size + 1)
        out.append({"name": "Player {:03d}".format(i), "ticket": ticket, "marks": set(t.ticket_numbers(ticket)[:want])})
    return out


# --------------------------------------------------------------------------
# The numbers and tickets of a large game must never change
# --------------------------------------------------------------------------

class TestLargeGameUnchanged(unittest.TestCase):
    """Pinned to what the step dealt before game sizes existed. A game that is running is re-dealt from its seed
    (a player whose row was never written gets the same ticket again), so if any of these moves, a game in progress
    would change under its players."""

    SEEDS = (1, 20261109, 281474976710655)
    USERS = ("UHOST0001", "UJACK0002", "U0123456789", "W9ZZZ9ZZZ9")

    @staticmethod
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]

    def test_the_order_of_the_numbers(self):
        golden = {1: "c4b2a32e5f8c2b34", 20261109: "256d595960f1b639", 281474976710655: "7a794820358d6fe4"}
        for seed in self.SEEDS:
            self.assertEqual(self.digest(t.draw_order(seed)), golden[seed], "seed {}".format(seed))
            self.assertEqual(t.draw_order(seed), t.draw_order(seed, 90))

    def test_the_tickets(self):
        tickets = {"%d:%s" % (s, u): t.make_ticket(s, u) for s in self.SEEDS for u in self.USERS}
        self.assertEqual(self.digest(tickets), "dd87e33bc6708af1")
        self.assertEqual(tickets["1:UHOST0001"], [[11, 42, 54, 71, 84], [6, 12, 34, 63, 73], [8, 19, 29, 77, 90]])
        # dealt through a game, a large one gives the same
        g = make_game("large", seed=1)
        self.assertEqual(t.deal_ticket(g, "UHOST0001"), tickets["1:UHOST0001"])

    def test_a_game_saved_before_sizes_is_large(self):
        old = t.cfg_from(["early5,top,middle,bottom,full", "channel", 10, 60])        # the four settings it had
        self.assertEqual(old["size"], "large")
        self.assertEqual(old["top"], t.REVIEW_PLAYERS)
        saved = {"g": "tb_C1_1", "c": "C1", "h": "U1", "f": ["full", "off", 10, 60], "d": 5, "n": 90}
        g = t.game_from_state(saved, False)
        self.assertEqual((t.numbers_of(g), t.ticket_size_of(g), g["n"]), (90, 15, 90))


# --------------------------------------------------------------------------
# Sizes
# --------------------------------------------------------------------------

class TestSizes(unittest.TestCase):
    def test_the_three_sizes(self):
        self.assertEqual({k: (v["numbers"], v["row"]) for k, v in t.SIZES.items()},
                         {"large": (90, 5), "medium": (60, 4), "small": (30, 3)})
        self.assertEqual(t.DEFAULT_SIZE, "large")
        self.assertEqual(t.NUMBERS, max(v["numbers"] for v in t.SIZES.values()))

    def test_every_size_can_make_a_ticket(self):
        """The layout needs one column for each ten numbers, a column to hold 1 to 3 numbers and a row to take as
        many numbers as it has columns at most: a size added to SIZES that breaks this is caught here."""
        for key, spec in t.SIZES.items():
            columns, total = t.layout_columns(spec["numbers"]), t.TICKET_ROWS * spec["row"]
            self.assertLessEqual(columns, total, key)
            self.assertLessEqual(total, 3 * columns, key)
            self.assertLessEqual(spec["row"], columns, key)
            self.assertLessEqual(spec["row"], 5, "{}: Slack folds a row of buttons past 5".format(key))
            self.assertGreaterEqual(total, t.EARLY_COUNT, "{}: Early Five needs five numbers on a ticket".format(key))

    def test_names_and_aliases(self):
        for word, want in (("small", "small"), ("SMALL", "small"), (" Quick ", "small"), ("mini", "small"),
                           ("s", "small"), ("medium", "medium"), ("M", "medium"), ("med", "medium"),
                           ("large", "large"), ("full", "large"), ("classic", "large"), ("L", "large"),
                           ("", "large"), (None, "large"), ("huge", "large"), (42, "large"), ("extra small", "large")):
            self.assertEqual(t.parse_size(word), want, repr(word))
        self.assertEqual(t.parse_size("nonsense", "small"), "small")

    def test_the_word_that_is_typed(self):
        for text, want in (("itambola small", "small"), ("ihousie quick", "small"), ("itambola", None),
                           ("itambola please", None), ("Hey all, itambola medium?", "medium"),
                           ("ITAMBOLA Large", "large"), ("itambola, small", "small"), ("small game anyone", None),
                           ("itambola s", "small"), ("", None), (None, None), ("itambolas small", None)):
            self.assertEqual(t.typed_size(text), want, repr(text))

    def test_settings_a_game_keeps(self):
        self.assertEqual(t.game_config({})["size"], "large")
        self.assertEqual(t.game_config({"size": "small"})["size"], "small")
        self.assertEqual(t.game_config({"size": "gibberish"})["size"], "large")
        # what is typed wins over the recipe's default, and a word that is not a size changes nothing
        self.assertEqual(t.game_config({"size": "large", "text": "itambola small"})["size"], "small")
        self.assertEqual(t.game_config({"size": "medium", "text": "itambola please"})["size"], "medium")
        self.assertEqual(t.game_config({})["top"], 10)
        for given, want in ((5, 5), ("7", 7), (0, 1), (-3, 1), (500, 50), ("abc", 10), (None, 10)):
            self.assertEqual(t.game_config({"top_n": given})["top"], want, repr(given))

    def test_settings_survive_being_saved_and_read_back(self):
        for size in t.SIZES:
            cfg = t.game_config({"size": size, "top_n": 7, "prizes": "top,full", "announce": "thread",
                                 "board_columns": 6, "max_players": 40})
            self.assertEqual(t.cfg_from(json.loads(json.dumps(t.cfg_list(cfg)))), cfg)
        for junk in (None, "x", 5, [], {}, [1], ["", "", "", "", "?", "?"]):
            cfg = t.cfg_from(junk)
            self.assertEqual((cfg["size"], cfg["top"]), ("large", 10), repr(junk))

    def test_a_game_keeps_its_size_in_its_state(self):
        for size, spec in t.SIZES.items():
            g = make_game(size, n=spec["numbers"])
            back = t.game_from_state(json.loads(json.dumps(t.state_dict(g))), False)
            self.assertEqual(back["cfg"], g["cfg"])
            self.assertEqual((t.numbers_of(back), back["n"]), (spec["numbers"], spec["numbers"]))
        small = t.game_from_state({"f": t.cfg_list(t.game_config({"size": "small"})), "n": 70}, False)
        self.assertEqual(small["n"], 30, "numbers called cannot pass the size's numbers")

    def test_the_setup_card_and_the_lobby_say_what_the_size_is(self):
        for size in t.SIZES:
            g = make_game(size)
            setup = all_text(t.setup_blocks(g))
            self.assertIn("Game size: *{}*".format(t.SIZES[size]["label"]), setup)
            self.assertIn("1 to {}".format(t.numbers_of(g)), setup)
            for other in t.SIZES:
                if other != size:
                    self.assertIn("`itambola {}`".format(other), setup)
                else:
                    self.assertNotIn("`itambola {}`".format(other), setup)
            lobby = all_text(t.lobby_blocks(g))
            self.assertIn("{} numbers in 3 rows".format(t.ticket_size_of(g)), lobby)
            self.assertIn("from 1 to {}".format(t.numbers_of(g)), lobby)
            if size == t.DEFAULT_SIZE:
                self.assertNotIn(" game: numbers", lobby)
            else:
                self.assertIn("({} game: numbers 1 to {})".format(size, t.numbers_of(g)), lobby)


# --------------------------------------------------------------------------
# Dealing
# --------------------------------------------------------------------------

class TestDealing(unittest.TestCase):
    USERS = ("UAAAAAAA1", "UBBBBBBB2", "UCCCCCCC3", "UDDDDDDD4", "UHOST0001")

    def test_the_numbers_come_out_in_a_fixed_order_with_none_missing(self):
        for size, spec in t.SIZES.items():
            order = t.draw_order(12345, spec["numbers"])
            self.assertEqual(sorted(order), list(range(1, spec["numbers"] + 1)), size)
            self.assertEqual(order, t.draw_order(12345, spec["numbers"]), size)
            self.assertNotEqual(order, t.draw_order(12346, spec["numbers"]), size)
            g = make_game(size, seed=12345, n=7)
            self.assertEqual(t.called_list(g), order[:7])

    def test_every_ticket_is_a_printed_ticket(self):
        for size, spec in t.SIZES.items():
            ranges = t.column_ranges(spec["numbers"])

            def column(number):
                return [i for i, (low, high) in enumerate(ranges) if low <= number <= high][0]
            for seed in range(1, 40):
                for user in self.USERS:
                    ticket = t.make_ticket(seed, user, size)
                    where = "{} seed {} {}".format(size, seed, user)
                    self.assertEqual(len(ticket), 3, where)
                    for row in ticket:
                        self.assertEqual(len(row), spec["row"], where)
                        self.assertEqual(row, sorted(row), where)
                        self.assertEqual(len({column(n) for n in row}), spec["row"],
                                         where + ": a column twice in a row")
                    flat = t.ticket_numbers(ticket)
                    self.assertEqual(len(set(flat)), 3 * spec["row"], where + ": a number twice")
                    self.assertTrue(all(1 <= n <= spec["numbers"] for n in flat), where)
                    per_column = [sum(1 for n in flat if column(n) == c) for c in range(len(ranges))]
                    self.assertTrue(all(1 <= count <= 3 for count in per_column), "{}: {}".format(where, per_column))
                    self.assertEqual(ticket, t.make_ticket(seed, user, size), where + ": not repeatable")

    def test_the_ranges_of_the_columns(self):
        self.assertEqual(t.column_ranges(90), [(1, 9)] + [(c, c + 9) for c in range(10, 80, 10)] + [(80, 90)])
        self.assertEqual(t.column_ranges(60), [(1, 9), (10, 19), (20, 29), (30, 39), (40, 49), (50, 60)])
        self.assertEqual(t.column_ranges(30), [(1, 9), (10, 19), (20, 30)])

    def test_each_player_gets_a_different_ticket(self):
        for size in t.SIZES:
            seen = {json.dumps(t.make_ticket(99, "U%07d" % i, size)) for i in range(200)}
            self.assertGreater(len(seen), 150, size)

    def test_a_game_deals_the_size_it_was_made_with(self):
        for size, spec in t.SIZES.items():
            ticket = t.deal_ticket(make_game(size), "U0000009")
            self.assertEqual([len(r) for r in ticket], [spec["row"]] * 3)
        self.assertEqual(t.deal_ticket({"seed": 5, "cfg": {}}, "U0000009"), t.make_ticket(5, "U0000009", "large"))

    def test_the_board_has_a_square_for_every_number(self):
        for size, spec in t.SIZES.items():
            rows = t.board_rows([], 10, spec["numbers"])
            self.assertEqual(len(rows), spec["numbers"] // 10, size)
            self.assertEqual(sum(row.count(t.EMPTY_TILE) for row in rows), spec["numbers"], size)
            called = t.draw_order(3, spec["numbers"])[:5]
            self.assertEqual(sum(row.count(t.EMPTY_TILE) for row in t.board_rows(called, 10, spec["numbers"])),
                             spec["numbers"] - 5)
        self.assertEqual(len(t.board_rows([], 7, 30)), 5)                  # 7 to a row: 4 full rows and a short one


# --------------------------------------------------------------------------
# Prizes and progress
# --------------------------------------------------------------------------

class TestPrizes(unittest.TestCase):
    def test_lines_and_full_house_at_every_size(self):
        for size in t.SIZES:
            ticket = t.make_ticket(7, "UAAAAAAA1", size)
            allp = list(t.PRIZE_KEYS)
            self.assertEqual(t.completed_prizes(ticket, set(), allp), [])
            self.assertEqual(t.completed_prizes(ticket, set(ticket[0]), allp),
                             ["early5", "top"] if len(ticket[0]) >= 5 else ["top"], size)
            self.assertIn("middle", t.completed_prizes(ticket, set(ticket[1]), allp))
            self.assertIn("bottom", t.completed_prizes(ticket, set(ticket[2]), allp))
            everything = set(t.ticket_numbers(ticket))
            self.assertEqual(t.completed_prizes(ticket, everything, allp), allp, size)
            one_short = set(t.ticket_numbers(ticket)[:-1])
            self.assertNotIn("full", t.completed_prizes(ticket, one_short, allp), size)

    def test_early_five_is_five_numbers_whatever_the_size(self):
        for size in t.SIZES:
            ticket = t.make_ticket(7, "UAAAAAAA1", size)
            flat = t.ticket_numbers(ticket)
            self.assertNotIn("early5", t.completed_prizes(ticket, set(flat[:4]), ["early5"]))
            self.assertEqual(t.completed_prizes(ticket, set(flat[:5]), ["early5"]), ["early5"])

    def test_progress_line_follows_the_ticket(self):
        for size, spec in t.SIZES.items():
            ticket = t.make_ticket(7, "UAAAAAAA1", size)
            line = t.progress_line(ticket, set(ticket[0]))
            self.assertIn("Marked {} of {}".format(spec["row"], 3 * spec["row"]), line)
            self.assertIn("Top {0}/{0}".format(spec["row"]), line)
            self.assertIn("Middle 0/{}".format(spec["row"]), line)

    def test_the_steps_of_the_review_cover_every_count_once(self):
        for size in t.SIZES.values():
            total = 3 * size["row"]
            buckets = t.spread_buckets(total)
            self.assertEqual(len(buckets), 4)
            covered = [n for low, high in buckets for n in range(low, high + 1)]
            self.assertEqual(covered, list(range(total + 1)), "{} on a ticket".format(total))
        self.assertEqual(t.spread_buckets(15), [(0, 3), (4, 7), (8, 11), (12, 15)])   # as the review always counted

    def test_a_ticket_read_back_must_be_three_even_rows(self):
        for size, spec in t.SIZES.items():
            self.assertTrue(t.valid_ticket(t.make_ticket(1, "UAAAAAAA1", size)), size)
        for bad in (None, "x", [], [[1, 2, 3]], [[1, 2], [3, 4], [5, 6]], [[1, 2, 3], [4, 5, 6], [7, 8]],
                    [[1, 2, 3], [4, 5, 6], [7, 8, "9"]], [[1, 2, 3]] * 4, [[1] * 6] * 3):
            self.assertFalse(t.valid_ticket(bad), repr(bad))


# --------------------------------------------------------------------------
# Every card, against Slack's limits
# --------------------------------------------------------------------------

class TestCards(unittest.TestCase):
    def cards(self, size, test):
        out = t.main({"text": "itambola " + size, "user_id": HOST, "channel": "C0TEST",
                      "message_ts": "1700000000.000100", "skip_post": "yes", "testing": "yes" if test else "no"})
        self.assertTrue(out["ok"], out)
        return json.loads(out["preview_json"])

    def test_every_card_of_every_size_is_one_slack_takes(self):
        for size in t.SIZES:
            for test in (True, False):
                cards = self.cards(size, test)
                self.assertEqual(len(cards), 11)
                for name, blocks in cards.items():
                    try:
                        check_blocks(blocks)
                    except AssertionError as error:
                        self.fail("{} card, size {}, test={}: {}".format(name, size, test, error))

    def test_the_ticket_card_is_three_rows_of_the_size(self):
        for size, spec in t.SIZES.items():
            ticket = self.cards(size, False)["ticket"]
            rows = [b for b in ticket if b["type"] == "actions"]
            self.assertEqual([len(r["elements"]) for r in rows], [spec["row"]] * 3, size)
            self.assertIn("of {}".format(3 * spec["row"]), all_text(ticket), size)

    def test_the_board_and_the_review_follow_the_size(self):
        for size, spec in t.SIZES.items():
            cards = self.cards(size, False)
            board = all_text(cards["board"])
            self.assertIn("of {} called".format(spec["numbers"]), board, size)
            self.assertEqual(len(grid_sections(cards["board"])), spec["numbers"] // 10, size)
            review = all_text(cards["review"])
            self.assertIn("of {} numbers called".format(spec["numbers"]), review, size)
            self.assertIn("/{}".format(3 * spec["row"]), review, size)

    def test_a_small_game_is_a_small_board(self):
        large, small = self.cards("large", False)["board"], self.cards("small", False)["board"]
        self.assertLess(len(json.dumps(small)), len(json.dumps(large)))
        self.assertEqual((len(grid_sections(large)), len(grid_sections(small))), (9, 3))

    def test_the_organizers_card_follows_the_size(self):
        for size, spec in t.SIZES.items():
            g = make_game(size, n=5)
            ticket = t.deal_ticket(g, HOST)
            blocks = t.panel_blocks(g, mine=(ticket, set()))
            check_blocks(blocks)
            card = [b for b in blocks if b["type"] == "actions"
                    and b["elements"][0]["action_id"].startswith(t.ACTION_PREFIX + "hmark_")]
            self.assertEqual([len(b["elements"]) for b in card], [spec["row"]] * 3, size)
            self.assertIn("of {} called".format(spec["numbers"]), all_text(blocks), size)


# --------------------------------------------------------------------------
# The review
# --------------------------------------------------------------------------

class TestReview(unittest.TestCase):
    def review(self, size="large", players=100, top=None, marks=None, n=25, **cfg):
        settings = dict(cfg, **({"top_n": top} if top else {}))
        g = make_game(size, status=t.PAUSED, n=n, players=max(players, 1), **settings)
        sample = make_players(g, players, marks)
        blocks = t.review_blocks(g, t.review_stats(g, sample))
        check_blocks(blocks)
        return g, sample, blocks

    def test_a_hundred_players_are_ten_lines(self):
        _g, _players, blocks = self.review(players=100)
        table = code_table(blocks)
        self.assertEqual(len(table), 1 + 10, "a header and ten players")
        text = all_text(blocks)
        self.assertIn("Top 10 of 100 players by numbers marked", text)
        self.assertIn("+90 more players", text)
        # no block for each player any more
        self.assertNotIn(":large_green_square:", text)
        self.assertLess(len(json.dumps(blocks)), 6000)

    def test_the_review_does_not_grow_with_the_players(self):
        sizes = [len(json.dumps(self.review(players=n)[2])) for n in (10, 30, 100)]
        self.assertLess(max(sizes) - min(sizes), 400, sizes)
        counts = [len(self.review(players=n)[2]) for n in (30, 60, 100)]     # past the top ten the card is the same
        self.assertEqual(len(set(counts)), 1, counts)

    def test_the_players_in_the_table_are_the_ones_ahead(self):
        g, players, blocks = self.review(players=60, marks=[(i * 7) % 16 for i in range(60)])
        best = sorted((len(p["marks"]) for p in players), reverse=True)[:10]
        shown = [int(line.split()[-2].split("/")[0]) for line in code_table(blocks)[1:]]
        self.assertEqual(shown, best)

    def test_top_n(self):
        for top, rows in ((1, 1), (3, 3), (25, 25), (50, 50)):
            _g, _p, blocks = self.review(players=80, top=top)
            self.assertEqual(len(code_table(blocks)) - 1, rows, top)
            self.assertIn("Top {} of 80".format(top), all_text(blocks))
            self.assertIn("+{} more".format(80 - rows), all_text(blocks))

    def test_a_small_game_has_no_extra_line(self):
        _g, _p, blocks = self.review(players=6, top=10)
        text = all_text(blocks)
        self.assertIn("*Players by numbers marked*", text)
        self.assertNotIn("more player", text)
        self.assertEqual(len(code_table(blocks)) - 1, 6)

    def test_nobody_has_a_ticket_yet(self):
        g = make_game(status=t.PAUSED, n=3)
        blocks = t.review_blocks(g, t.review_stats(g, []))
        check_blocks(blocks)
        self.assertEqual(code_table(blocks), [])

    def test_equal_counts_share_a_rank(self):
        players = [{"name": n, "marks": set(range(m))} for n, m in
                   (("A", 9), ("B", 9), ("C", 8), ("D", 7), ("E", 7), ("F", 7), ("G", 1))]
        self.assertEqual(t.rank_texts(players), ["T1", "T1", "3", "T4", "T4", "T4", "7"])
        self.assertEqual(t.rank_texts([{"name": "A", "marks": {1}}]), ["1"])
        self.assertEqual(t.rank_texts([]), [])
        # a tie that runs past the cut is still a tie
        g = make_game(status=t.PAUSED, n=3, top_n=5)
        sample = [dict(p, ticket=t.make_ticket(1, "U1", "large")) for p in players]
        rows = code_table(t.review_blocks(g, t.review_stats(g, sample)))[1:]
        self.assertEqual([r.split()[0] for r in rows], ["T1", "T1", "3", "T4", "T4"])

    def test_the_columns_line_up_and_odd_names_do_no_harm(self):
        g = make_game(status=t.PAUSED, n=10, top_n=6)
        names = ["Zoë Ünal", "A & B <team>", "x" * 60, "", "日本語の名前", "Ana"]
        sample = [{"name": name, "ticket": t.make_ticket(1, "U%07d" % i, "large"), "marks": set(range(1, 12 - i))}
                  for i, name in enumerate(names)]
        blocks = t.review_blocks(g, t.review_stats(g, sample))
        check_blocks(blocks)
        text = [b for b in blocks if b.get("text", {}).get("text", "").startswith("```")][0]["text"]["text"]
        self.assertNotIn("<team>", text)
        self.assertIn("A &amp; B &lt;team&gt;", text)
        lines = html.unescape(text).strip("`\n").split("\n")
        self.assertEqual(len({len(line) for line in lines[1:]}), 1, "every player's line is as wide: " + repr(lines))
        self.assertIn("x" * 17 + ".", lines[3])
        self.assertIn("Someone", text)

    def test_a_long_table_is_split_under_slacks_limit(self):
        g = make_game(status=t.PAUSED, n=10, top_n=50)
        names = ["&" * 18] * 50                                     # every character becomes &amp;
        sample = [{"name": name, "ticket": t.make_ticket(1, "U%07d" % i, "large"), "marks": {1}}
                  for i, name in enumerate(names)]
        blocks = t.review_blocks(g, t.review_stats(g, sample))
        check_blocks(blocks)
        tables = [b for b in blocks if b.get("text", {}).get("text", "").startswith("```")]
        self.assertGreater(len(tables), 1)
        self.assertEqual(sum(len(b["text"]["text"].strip("`\n").split("\n")) - 1 for b in tables), 50)

    def test_every_size_counts_players_in_four_steps_that_add_up(self):
        for size, spec in t.SIZES.items():
            g, players, blocks = self.review(size=size, players=50, n=20)
            stats = t.review_stats(g, players)
            self.assertEqual(sum(stats["spread"]), 50, size)
            spread = [b for b in blocks if "Players by numbers marked:" in all_text([b])]
            self.assertTrue(spread, size)
            self.assertIn("{}-".format(0), spread[0]["elements"][0]["text"])
            closest = stats["closest"]
            self.assertEqual(closest["top"][1], spec["row"], size)
            self.assertEqual(closest["full"][1], 3 * spec["row"], size)
            self.assertEqual(closest["early5"][1], 5, size)

    def test_the_figures_of_a_large_review_are_what_they_were(self):
        marks = list(range(16)) + [0, 0, 0, 0]
        _g, _p, blocks = self.review(players=20, marks=marks)
        spread = [b for b in blocks if "Players by numbers marked:" in all_text([b])][0]["elements"][0]["text"]
        self.assertIn("0-3: 8", spread)
        self.assertIn("4-7: 4", spread)
        self.assertIn("8-11: 4", spread)
        self.assertIn("12-15: 4", spread)

    def test_a_test_game_has_no_player_figures(self):
        g = make_game("medium", test=True, status=t.PAUSED, n=4)
        blocks = t.review_blocks(g, t.review_stats(g, None))
        check_blocks(blocks)
        self.assertIn("Test game: each player's progress is only shown in a real game.", all_text(blocks))
        self.assertEqual(code_table(blocks), [])
        self.assertEqual(t.carried_state({"blocks": blocks})["f"], t.cfg_list(g["cfg"]))


# --------------------------------------------------------------------------
# Buttons
# --------------------------------------------------------------------------

class TestButtons(unittest.TestCase):
    def test_a_test_ticket_carries_itself_whatever_its_size(self):
        for size in t.SIZES:
            g = make_game(size, test=True, n=6)
            ticket = t.deal_ticket(g, "U0000003")
            marks = set(t.ticket_numbers(ticket)[:4])
            number = t.ticket_numbers(ticket)[5]
            parsed = t.parse_value(t.mark_value(g, ticket, marks, number))
            self.assertEqual(parsed["kind"], "mark")
            self.assertEqual(t.test_ticket(parsed["state"]), ticket, size)
            self.assertEqual(t.marks_of(ticket, parsed["state"]["k"]), marks, size)

    def test_a_test_ticket_that_cannot_be_read(self):
        for flat in (None, [], [1, 2], list(range(10)), list(range(14)), list(range(30)), "abc"):
            self.assertIsNone(t.test_ticket({"t": flat}), repr(flat))

    def test_the_marks_on_the_organizers_card_fit_any_size(self):
        for size in t.SIZES:
            g = make_game(size, test=True)
            ticket = t.deal_ticket(g, HOST)
            everything = set(t.ticket_numbers(ticket))
            mask = t.mask_of(ticket, everything)
            self.assertEqual(mask, (1 << t.ticket_size_of(g)) - 1, size)
            self.assertEqual(t.marks_of(ticket, mask), everything, size)

    def test_a_real_game_button_points_at_its_game(self):
        g = make_game("small")
        for kind in ("next", "review", "resume", "end", "join", "start"):
            parsed = t.parse_value(t.value_for(kind, g))
            self.assertEqual((parsed["kind"], parsed["game"], parsed["test"]), (kind, g["id"], False))
        choice = json.loads(t.parse_value(t.set_value(g, "all"))["arg"])
        self.assertEqual(t.cfg_from(choice["f"])["size"], "small")

    def test_a_test_games_setup_choice_carries_the_size(self):
        g = make_game("medium", test=True)
        parsed = t.parse_value(t.set_value(g, "open"))
        self.assertTrue(parsed["test"])
        self.assertEqual(t.game_from_state(parsed["state"], True)["cfg"]["size"], "medium")

    def test_a_test_game_fits_in_its_own_message(self):
        """A test game's state lives in the block ids of the messages it posts: 24 players, five prizes and every
        size must fit in the blocks the message has."""
        for size in t.SIZES:
            g = make_game(size, test=True, n=9, players=t.TEST_PLAYERS, status=t.RUNNING)
            g["wins"] = {k: {"uid": "U0000001", "name": "A Long Name Here", "ts": "1700000100.000100"}
                         for k in t.PRIZE_KEYS}
            for blocks in (t.board_blocks(g), t.lobby_blocks(dict(g, status=t.LOBBY)), t.review_blocks(
                    dict(g, status=t.PAUSED), t.review_stats(dict(g, status=t.PAUSED), None))):
                back = t.carried_state({"blocks": blocks})
                self.assertIsNotNone(back, size)
                self.assertEqual(back["f"], t.cfg_list(g["cfg"]), size)
                self.assertEqual(back["n"], 9, size)


# --------------------------------------------------------------------------
# The world: Slack and the data table, as the step sees them
# --------------------------------------------------------------------------

HOOK = "https://hooks.slack.com/actions/T0TEST/1/"          # a response_url: the person it answers is the last part
CONTROLS = ("start", "cancel", "next", "review", "resume", "end", "myticket")


class World(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = 1700000000.0
        self.counter = 0
        self.messages = {}            # (channel, ts) -> {"ts", "text", "blocks"}
        self.private = []             # what only one person sees: {"user", "channel", "blocks", "text", "how"}
        self.members = {}             # channel -> ids
        self.names = {}               # id -> name
        self.rows = {}                # record id -> {column name: value, "$record_id": id}
        self.calls = []

    # -- time
    def next_ts(self):
        with self.lock:
            self.counter += 1
            return "{:.6f}".format(1700000000 + self.counter * 0.001)

    def tick(self, seconds=3.0):
        """A press's click time, a few seconds after the last so no Next number looks like a press made twice."""
        with self.lock:
            self.clock += seconds
            return "{:.6f}".format(self.clock)

    # -- the network
    def send(self, url, headers, payload, method="POST", timeout=None, raw_ok=False):
        with self.lock:
            self.calls.append((method, url))
            if url.startswith("https://hooks.slack.com/"):
                return self._response(url, payload)
            if url.startswith("https://slack.com/api/"):
                return self._slack(url, payload)
            if url.startswith("https://data-tables.workato.com/"):
                return self._table(url, payload, method)
        return None, "unexpected url " + url

    def _checked(self, payload):
        check_blocks(payload.get("blocks") or [])
        return payload.get("blocks") or []

    def _slack(self, url, payload):
        parsed = urlparse(url)
        endpoint = parsed.path.rsplit("/", 1)[1]
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if endpoint == "chat.postMessage":
            channel = payload["channel"]
            if channel[0] in "UW":                       # a message to a person lands in their private message
                channel = "D" + channel
            blocks = self._checked(payload)
            ts = self.next_ts()
            self.messages[(channel, ts)] = {"ts": ts, "text": payload.get("text"), "blocks": blocks}
            return {"ok": True, "channel": channel, "ts": ts}, None
        if endpoint == "chat.update":
            key = (payload["channel"], payload["ts"])
            if key not in self.messages:
                return {"ok": False, "error": "message_not_found"}, None
            self.messages[key].update(text=payload.get("text"), blocks=self._checked(payload))
            return {"ok": True}, None
        if endpoint == "chat.delete":
            self.messages.pop((payload["channel"], payload["ts"]), None)
            return {"ok": True}, None
        if endpoint == "chat.postEphemeral":
            self.private.append({"user": payload["user"], "channel": payload["channel"], "text": payload.get("text"),
                                 "blocks": self._checked(payload), "how": "note"})
            return {"ok": True, "message_ts": self.next_ts()}, None
        if endpoint == "users.info":
            user = query["user"]
            return {"ok": True, "user": {"id": user, "is_bot": False, "deleted": False,
                                         "profile": {"real_name": self.names.get(user, "")}}}, None
        if endpoint == "conversations.members":
            return {"ok": True, "members": list(self.members.get(query["channel"], [])),
                    "response_metadata": {"next_cursor": ""}}, None
        if endpoint == "conversations.replies":
            message = self.messages.get((query["channel"], query["ts"]))
            return {"ok": True, "messages": [message] if message else []}, None
        if endpoint == "conversations.open":
            return {"ok": True, "channel": {"id": "D" + (payload or {}).get("users", "")}}, None
        return {"ok": False, "error": "unknown_method " + endpoint}, None

    def _response(self, url, payload):
        self.private.append({"user": url.rsplit("/", 1)[1], "channel": "", "text": payload.get("text"),
                             "blocks": self._checked(payload), "how": "in place"})
        return {"ok": True, "raw": "ok"}, None

    @staticmethod
    def _match(row, where):
        if "$and" in where:
            return all(World._match(row, w) for w in where["$and"])
        for column, condition in where.items():
            for op, value in condition.items():
                have = row.get(column)
                if (op == "$eq" and have != value) or (op == "$in" and have not in value):
                    return False
        return True

    def _table(self, url, payload, method):
        names = list(t.COLUMNS)
        if url.endswith("/query"):
            rows = [r for r in self.rows.values() if self._match(r, payload.get("where") or {})]
            return {"schema": [[{"name": n} for n in names + ["$record_id"]]],
                    "data": [[[r.get(n) for n in names + ["$record_id"]]] for r in rows]}, None
        by_uuid = {uuid: name for name, uuid in t.COLUMNS.items()}
        document = {by_uuid[key[1:]]: value for key, value in payload["document"].items()}
        if method == "POST":
            record_id = "rec{:05d}".format(len(self.rows) + 1)
            self.rows[record_id] = dict(document, **{"$record_id": record_id})
            return {"record_id": record_id}, None
        record_id = url.rsplit("/", 1)[1]
        self.rows[record_id].update(document)
        return {"record_id": record_id}, None

    # -- what people see
    def events(self, user):
        return [e for e in self.private if e["user"] == user]

    def panel(self, user):
        """The organizer's controls as they are now: the last private note or in-place replacement with a control."""
        for event in reversed(self.events(user)):
            if any(b["action_id"].replace(t.ACTION_PREFIX, "") in CONTROLS for b in buttons_of(event["blocks"])):
                return event["blocks"]
        raise AssertionError("{} has no controls".format(user))

    def last_note(self, user):
        return self.events(user)[-1]

    def ticket_of(self, user):
        """(channel, ts, blocks) of the ticket message in this person's private messages, the one with numbers on it."""
        found = [(c, ts, m["blocks"]) for (c, ts), m in self.messages.items()
                 if c == "D" + user and any(b["action_id"].startswith(t.ACTION_PREFIX + "mark_")
                                            for b in buttons_of(m["blocks"]))]
        assert len(found) == 1, "{} has {} tickets".format(user, len(found))
        return found[0]

    def channel_messages(self, channel):
        return [m for (c, _ts), m in sorted(self.messages.items()) if c == channel]

    def rows_of(self, row_type):
        return [r for r in self.rows.values() if r.get("row_type") == row_type]

    # -- what people do
    def click(self, user, button, channel, source_ts="", response=True, **extra):
        """The click recipe's input for a press on `button`, run through main()."""
        given = {"action_value": button.get("value") or "", "action_id": button["action_id"], "user_id": user,
                 "channel": channel, "source_ts": source_ts, "action_ts": self.tick(),
                 "slack_bot_token": "xoxb-test", "workato_api_token": "wk-test"}
        if response:
            given["response_url"] = HOOK + user
        given.update(extra)
        return t.main(given)

    def type_word(self, user, channel, text, **extra):
        given = {"text": text, "user_id": user, "channel": channel, "message_ts": self.next_ts(),
                 "slack_bot_token": "xoxb-test", "workato_api_token": "wk-test"}
        given.update(extra)
        return t.main(given)

    def tap(self, user, number):
        """The player taps `number` on their ticket, if it is there. The recipe's result, or None."""
        channel, ts, blocks = self.ticket_of(user)
        found = [b for b in buttons_of(blocks) if b["action_id"] == t.ACTION_PREFIX + "mark_{}".format(number)]
        if not found:
            return None
        return self.click(user, found[0], channel, source_ts=ts, response=False)


def ticket_numbers_on(blocks):
    return [int(b["action_id"].rsplit("_", 1)[1]) for b in buttons_of(blocks)
            if b["action_id"].startswith(t.ACTION_PREFIX + "mark_")]


# --------------------------------------------------------------------------
# Whole games
# --------------------------------------------------------------------------

class TestGames(unittest.TestCase):
    CHANNEL = "C0GAME"

    KEY_OF = {name: key for key, name in t.PRIZE_NAME.items()}

    def setUp(self):
        self.patches = []
        self.use_world()
        # no waiting, and the same numbers every run: a game that is left to chance can fail once in a thousand
        for name, new in (("_sleep", lambda seconds: None), ("new_seed", lambda: 424242)):
            self.patches.append(mock.patch.object(t, name, new))
            self.patches[-1].start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def use_world(self):
        """A new, empty Slack and data table (the step is then talking to it)."""
        for patch in getattr(self, "world_patches", []):
            patch.stop()
        self.world = World()
        self.world_patches = [mock.patch.object(t, "_send_json", self.world.send),
                              mock.patch.object(t, "_now", lambda: self.world.clock)]
        for patch in self.world_patches:
            patch.start()
        self.addCleanup(lambda: [p.stop() for p in self.world_patches])

    # -- helpers
    def people(self, count):
        ids = [HOST] + ["U%07d" % i for i in range(1, count)]
        self.world.members[self.CHANNEL] = ids
        self.world.names.update({u: "Player {:03d}".format(i) for i, u in enumerate(ids)})
        self.world.names[HOST] = "Priya Sharma"
        return ids

    def open_game(self, ids, word="itambola", test=False, **extra):
        """Type the word, choose 'Everyone in this channel', press Start. The result of Start."""
        w = self.world
        if test:
            extra["testing"] = "yes"
        out = w.type_word(HOST, self.CHANNEL, word, **extra)
        self.assertTrue(out["ok"], out)
        setup = w.last_note(HOST)
        self.setup_text = all_text(setup["blocks"])
        out = w.click(HOST, button_named(setup["blocks"], "set_all"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        self.lobby_text = all_text(w.channel_messages(self.CHANNEL)[-1]["blocks"])
        out = w.click(HOST, button_named(w.panel(HOST), "start"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["players"], out["dm_sent"]), (len(ids), len(ids)), out)
        self.board_ts = out["message_ts"]
        self.game_id = out["game_id"]
        return out

    def board(self):
        return self.world.messages[(self.CHANNEL, self.board_ts)]["blocks"]

    def next_number(self):
        out = self.world.click(HOST, button_named(self.world.panel(HOST), "next"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        return out

    def play_out(self, players, limit):
        """Call numbers, every player tapping each as it comes, until a Full House or `limit` calls. (calls, [prizes
        won in the order they were won], who held the number that finished it)."""
        won = []
        for call in range(1, limit + 1):
            out = self.next_number()
            if out["finished"]:
                return call, won
            for user in players:
                result = self.world.tap(user, out["number"])
                if result is None:
                    continue
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["marked"], out["number"], result)
                won += [self.KEY_OF[p] for p in result["prize"].split(", ") if p]
                if result["finished"]:
                    return call, won
        return limit, won

    # -- a small game, from the typed word to the Full House
    def test_a_small_game_from_the_typed_word_to_full_house(self):
        ids = self.people(6)
        self.open_game(ids, "itambola small")
        self.assertIn("Game size: *Small*", self.setup_text)
        self.assertIn("9 numbers in 3 rows", self.lobby_text)
        self.assertIn("(small game: numbers 1 to 30)", self.lobby_text)

        rows = self.world.rows_of(t.PLAYER_ROW)
        self.assertEqual(len(rows), 6)
        for row in rows:
            ticket = t.player_from_row(row)["ticket"]
            self.assertEqual([len(r) for r in ticket], [3, 3, 3])
            self.assertTrue(all(1 <= n <= 30 for n in t.ticket_numbers(ticket)))
        for user in ids:
            self.assertEqual(len(ticket_numbers_on(self.world.ticket_of(user)[2])), 9)
        self.assertIn("0 of 30 called", all_text(self.board()).replace("*", ""))

        calls, won = self.play_out(ids, 30)
        self.assertLessEqual(calls, 30)
        self.assertEqual(sorted(won), sorted(t.PRIZE_KEYS), "every prize won once: {}".format(won))
        self.assertEqual(won[-1], "full")
        wins = self.world.rows_of(t.WIN_ROW)
        self.assertEqual(sorted(r["grant_type"] for r in wins), sorted(t.PRIZE_KEYS))
        self.assertEqual(self.world.rows_of(t.GAME_ROW)[0]["status"], t.DONE)
        board = all_text(self.board())
        self.assertIn("Game over", board)
        self.assertIn("Full House", board)
        self.assertEqual(len(grid_sections(self.board())), 3, "thirty numbers are three rows of ten")

    def test_a_small_game_ends_when_the_thirty_numbers_are_out(self):
        ids = self.people(2)
        self.open_game(ids, "itambola small")
        for call in range(1, 31):
            out = self.next_number()                   # nobody marks anything, so nobody can win
        self.assertTrue(out["finished"], out)
        self.assertEqual(out["called"], 30)
        self.assertIn("All 30 numbers have been called", all_text(self.board()))
        self.assertEqual(self.world.rows_of(t.GAME_ROW)[0]["status"], t.DONE)

    def test_a_medium_game_deals_four_numbers_a_row(self):
        ids = self.people(5)
        self.open_game(ids, "itambola medium")
        for user in ids:
            blocks = self.world.ticket_of(user)[2]
            self.assertEqual([len(b["elements"]) for b in blocks if b["type"] == "actions"], [4, 4, 4])
            self.assertTrue(all(1 <= n <= 60 for n in ticket_numbers_on(blocks)))
        calls, won = self.play_out(ids, 60)
        self.assertLessEqual(calls, 60)
        self.assertEqual(sorted(won), sorted(t.PRIZE_KEYS))

    def test_the_recipes_size_input_is_the_default_and_the_typed_word_wins(self):
        ids = self.people(2)
        self.open_game(ids, "itambola", size="small")
        self.assertIn("(small game", self.lobby_text)
        self.use_world()                 # typing the word again would bring back the first game's controls
        ids = self.people(2)
        self.open_game(ids, "itambola large", size="small")
        self.assertNotIn("small game", self.lobby_text)
        self.assertIn("15 numbers in 3 rows", self.lobby_text)

    def test_a_large_game_is_what_it_always_was(self):
        ids = self.people(4)
        self.open_game(ids)
        self.assertIn("Game size: *Large*", self.setup_text)
        self.assertIn("15 numbers in 3 rows", self.lobby_text)
        self.assertNotIn(" game: numbers", self.lobby_text)
        for user in ids:
            blocks = self.world.ticket_of(user)[2]
            self.assertEqual([len(b["elements"]) for b in blocks if b["type"] == "actions"], [5, 5, 5])
        game = t.game_from_row(self.world.rows_of(t.GAME_ROW)[0])
        self.assertEqual((game["cfg"]["size"], t.numbers_of(game)), ("large", 90))
        out = self.next_number()
        self.assertEqual(out["number"], t.draw_order(game["seed"])[0])
        self.assertIn("1 of 90 called", all_text(self.board()).replace("*", ""))

    # -- the review, with a hundred players
    def test_the_review_of_a_hundred_players_is_a_short_table(self):
        ids = self.people(100)
        self.open_game(ids, "itambola", max_players=100)
        self.assertEqual(len(self.world.rows_of(t.PLAYER_ROW)), 100)
        called = []
        for _ in range(14):
            called.append(self.next_number()["number"])
        for i, user in enumerate(ids[:40]):                      # some play more than others
            mine = [n for n in called if n in ticket_numbers_on(self.world.ticket_of(user)[2])]
            for number in mine[:i % 7]:
                self.assertTrue(self.world.tap(user, number)["ok"])

        out = self.world.click(HOST, button_named(self.world.panel(HOST), "review"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["status"], t.PAUSED)
        board = self.board()
        text = all_text(board)
        self.assertIn("review", text)
        self.assertIn("Top 10 of 100 players by numbers marked", text)
        self.assertIn("+90 more players", text)
        table = code_table(board)
        self.assertEqual(len(table), 11)
        self.assertEqual(table[0].split(), ["#", "name", "marked", "progress"])
        marks = [int(line.split()[-2].split("/")[0]) for line in table[1:]]
        self.assertEqual(marks, sorted(marks, reverse=True))
        rows = [t.player_from_row(r) for r in self.world.rows_of(t.PLAYER_ROW)]
        self.assertEqual(marks[0], max(len(r["marks"]) for r in rows))
        self.assertLess(len(board), 25)
        self.assertLess(len(json.dumps(board)), 6000)
        spread = [b for b in board if "Players by numbers marked:" in all_text([b])][0]["elements"][0]["text"]
        self.assertEqual(sum(int(x.split(": ")[1]) for x in spread.split(":  ", 1)[1].split("  ·  ")), 100)

        # Next number is refused while it is up, and Resume puts the board back
        panel = self.world.panel(HOST)
        self.assertEqual([b["action_id"].replace(t.ACTION_PREFIX, "") for b in buttons_of(panel)][:1], ["resume"])
        out = self.world.click(HOST, button_named(panel, "resume"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        back = all_text(self.board())
        self.assertNotIn("review", back)
        self.assertIn("14", back)
        self.assertEqual(code_table(self.board()), [])
        self.next_number()

    def test_top_n_from_the_recipe(self):
        ids = self.people(30)
        self.open_game(ids, "itambola small", top_n=4)
        self.next_number()
        self.world.click(HOST, button_named(self.world.panel(HOST), "review"), self.CHANNEL)
        self.assertEqual(len(code_table(self.board())) - 1, 4)
        self.assertIn("Top 4 of 30 players", all_text(self.board()))

    def test_only_the_host_can_review(self):
        ids = self.people(3)
        self.open_game(ids)
        self.next_number()
        button = button_named(self.world.panel(HOST), "review")
        out = self.world.click(ids[1], button, self.CHANNEL)
        self.assertTrue(out["ok"])
        self.assertEqual(out["skipped"], "only the host can do that")
        self.assertEqual(code_table(self.board()), [])
        self.assertNotIn("review", all_text(self.board()))

    # -- a game that began before sizes existed
    def test_a_game_saved_before_sizes_goes_on_as_a_large_one(self):
        ids = self.people(3)
        self.open_game(ids)
        row = self.world.rows_of(t.GAME_ROW)[0]
        state = json.loads(row["content"])
        state["f"] = state["f"][:4]                                      # what a game saved earlier holds
        row["content"] = json.dumps(state)
        for _ in range(3):
            out = self.next_number()
        self.assertEqual(out["called"], 3)
        self.assertEqual(t.called_list(t.game_from_row(row)), t.draw_order(state["d"])[:3])
        out = self.world.click(HOST, button_named(self.world.panel(HOST), "review"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        self.assertIn("of 90 numbers called", all_text(self.board()))
        self.assertEqual(len(code_table(self.board())) - 1, 3)

    # -- a test game keeps its state in its messages
    def test_a_test_game_plays_through_at_every_size(self):
        for size, spec in t.SIZES.items():
            with self.subTest(size=size):
                self.use_world()
                ids = self.people(4)
                self.open_game(ids, "itambola " + size, test=True)
                self.assertEqual(self.world.rows, {}, "a test game writes nothing to the table")
                self.assertIn("{} numbers in 3 rows".format(3 * spec["row"]), self.lobby_text)
                out = self.next_number()
                self.assertIn("1 of {} called".format(spec["numbers"]), all_text(self.board()).replace("*", ""))
                for user in ids:
                    self.assertEqual(len(ticket_numbers_on(self.world.ticket_of(user)[2])), 3 * spec["row"])
                # a number that has not been called is refused, one that has is marked
                channel, ts, blocks = self.world.ticket_of(HOST)
                numbers = ticket_numbers_on(blocks)
                other = [n for n in numbers if n != out["number"]][0]
                self.assertEqual(self.world.tap(HOST, other)["marked"], 0)
                self.assertIn("has not been called yet", all_text(self.world.messages[(channel, ts)]["blocks"]))
                # review: no player figures
                out = self.world.click(HOST, button_named(self.world.panel(HOST), "review"), self.CHANNEL)
                self.assertTrue(out["ok"], out)
                self.assertIn("only shown in a real game", all_text(self.board()))
                out = self.world.click(HOST, button_named(self.world.panel(HOST), "resume"), self.CHANNEL)
                self.assertTrue(out["ok"], out)
                calls, won = self.play_out(ids, spec["numbers"])
                self.assertEqual(won[-1] if won else "", "full", "{} {}".format(size, won))
                self.assertIn("Game over", all_text(self.board()))
                self.assertEqual(self.world.rows, {})

    def test_the_organizer_can_open_their_own_card_at_every_size(self):
        for size, spec in t.SIZES.items():
            with self.subTest(size=size):
                self.use_world()
                ids = self.people(3)
                self.open_game(ids, "itambola " + size)
                mine = ticket_numbers_on(self.world.ticket_of(HOST)[2])
                number = 0
                while number not in mine:                         # call numbers until one is on the organizer's ticket
                    number = self.next_number()["number"]
                out = self.world.click(HOST, button_named(self.world.panel(HOST), "myticket"), self.CHANNEL)
                self.assertTrue(out["ok"], out)
                card = self.world.panel(HOST)
                rows = [b for b in card if b["type"] == "actions" and any(
                    e["action_id"].startswith(t.ACTION_PREFIX + "hmark_") for e in b["elements"])]
                self.assertEqual([len(r["elements"]) for r in rows], [spec["row"]] * 3)
                self.assertEqual(sorted(int(e["action_id"].rsplit("_", 1)[1]) for r in rows for e in r["elements"]),
                                 sorted(mine))
                press = [e for r in rows for e in r["elements"] if e["action_id"].endswith("_{}".format(number))][0]
                out = self.world.click(HOST, press, self.CHANNEL)
                self.assertTrue(out["ok"], out)
                self.assertEqual(out["marked"], number)
                self.assertIn(":white_check_mark: {}".format(number), all_text(self.world.panel(HOST)))


if __name__ == "__main__":
    unittest.main()
