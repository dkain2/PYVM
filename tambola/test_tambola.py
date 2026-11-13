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
    TestSizes                small / medium / large: names, aliases, the dropdown's options, the settings a game keeps
    TestDealing              the order the numbers come out in and the tickets, for every size
    TestPrizes               prizes, progress and the review's steps at every ticket size
    TestBoardStyles          the three board styles: emoji, plain number grid, called list
    TestPrintedTicket        the printed ticket: a number in its column, blanks between
    TestWinners              the board's winners: names, a carousel of profile pictures, a strip, or none
    TestClaims               a prize is won, and announced, once: even if one player's click is handled twice
    TestCelebrations         announcements that grow with the prize, and the banners that can top them
    TestCards                every card of every size, checked against Slack's Block Kit limits
    TestReview               the ranked table of the review: a hundred players, ties, top_n, odd names
    TestButtons              what a button carries and how it is read back, test games included
    TestPayload              the click recipe's whole-payload input, and the dropdown's live choice read from `state`
    TestGames                whole games played through main(), the way the two recipes call it, against a stand-in
                             for Slack and for the data table (see World)
    TestGamesByPayload       the same games again, every press sent as the one `payload` input instead of mapped fields

THE WORLD
    World replaces the network (tambola._send_json), the waiting (_sleep) and the clock (_now). It answers the Slack
    calls the step makes (post, update, delete, private notes, members, users, a message read back, the press's
    response_url) and the Workato data table (query, create, update), keeps every message, and refuses any message
    Slack would refuse (too many blocks, a text or a button value too long): a card that Slack would turn down is a
    failure here too. Presses are made from the buttons that were really posted, never built by hand.
"""

import copy
import hashlib
import html
import json
import os
import random
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
                if element["type"] == "image":
                    check_image(element)
                else:
                    assert len(element["text"]) <= 3000, "context text over 3000 characters"
        elif kind == "carousel":
            assert 1 <= len(block["elements"]) <= 10, "a carousel holds 1 to 10 cards, not {}".format(
                len(block["elements"]))
            for card in block["elements"]:
                check_card(card)
        elif kind == "actions":
            assert 1 <= len(block["elements"]) <= 25, "actions need 1 to 25 elements"
            for element in block["elements"]:
                check_element(element)
        elif kind == "divider":
            pass
        elif kind == "image":
            check_image(block)
        else:
            raise AssertionError("unexpected block type {!r}".format(kind))


def check_image(image):
    assert image["image_url"].startswith("https://") and len(image["image_url"]) <= 3000, "bad image url"
    assert 1 <= len(image["alt_text"]) <= 2000, "an image needs alt text"


def check_card(card):
    """A card of a carousel: Slack's limits are 150 characters for a title and a subtitle and 200 for a body."""
    assert card["type"] == "card"
    for part, limit in (("title", 150), ("subtitle", 150), ("body", 200)):
        if card.get(part):
            assert card[part]["type"] == "mrkdwn" and len(card[part]["text"]) <= limit, "card {} over {}".format(
                part, limit)
    for part in ("hero_image", "icon"):
        if card.get(part):
            assert card[part]["type"] == "image"
            check_image(card[part])
    assert len(card.get("actions") or []) <= 5


def check_element(element):
    if element["type"] == "button":
        assert len(element["text"]["text"]) <= 75, "button text over 75 characters"
        assert len(element["action_id"]) <= 255, "action_id over 255 characters"
        assert len(element.get("value", "")) <= 2000, "button value of {} characters".format(len(element["value"]))
    else:
        assert len(element["action_id"]) <= 255, "action_id over 255 characters"
        options = element.get("options") or []
        assert len(options) <= 100, "menu with more than 100 options"
        for option in options:
            assert len(option["text"]["text"]) <= 75, "option text over 75 characters"
            assert len(option["value"]) <= t.OPTION_VALUE_MAX, "option value of {} characters, Slack takes {}".format(
                len(option["value"]), t.OPTION_VALUE_MAX)
        if element.get("initial_option"):
            assert element["initial_option"] in options, "initial_option is not one of the options"


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
        for card in (block.get("elements") or []) if block.get("type") == "carousel" else []:
            parts += [card[part]["text"] for part in ("title", "subtitle", "body") if card.get(part)]
    return "\n".join(parts)


def menu_of(blocks, action):
    """A dropdown on a setup card (each sits beside a line of text, as a section's accessory)."""
    found = [b["accessory"] for b in blocks if b.get("accessory", {}).get("action_id") == action]
    assert len(found) == 1, "{} dropdowns {} on the card".format(len(found), action)
    return found[0]


def size_menu_of(blocks):
    return menu_of(blocks, t.SIZE_ACTION)


def board_menu_of(blocks):
    return menu_of(blocks, t.BOARD_ACTION)


def winners_menu_of(blocks):
    return menu_of(blocks, t.WINNERS_ACTION)


def chosen_winners(blocks):
    """The winners style a setup card's dropdown stands on."""
    return json.loads(winners_menu_of(blocks)["initial_option"]["value"])["s"]


def carousel_of(blocks):
    """The cards of the board's carousel, left to right; [] if it has none."""
    found = [b for b in blocks if b["type"] == "carousel"]
    return found[0]["elements"] if found else []


def chosen_size(blocks):
    """The size a setup card's dropdown stands on."""
    return json.loads(size_menu_of(blocks)["initial_option"]["value"])["s"]


def chosen_board(blocks):
    """The board style a setup card's dropdown stands on."""
    return json.loads(board_menu_of(blocks)["initial_option"]["value"])["s"]


def columns_of(size):
    """Cells in a row of a printed ticket of this size: one for each column."""
    return t.layout_columns(t.SIZES[size]["numbers"])


def row_widths(blocks):
    """The buttons in each row of a ticket, or of the organizer's card."""
    return [len(b["elements"]) for b in blocks if b["type"] == "actions" and any(
        e["action_id"].startswith((t.ACTION_PREFIX + "mark_", t.ACTION_PREFIX + "hmark_", t.BLANK_ACTION))
        for e in b["elements"])]


def dropdown_state(menu, key, block="SL9MT"):
    """What Slack reports for a dropdown when `key` is showing in it: under a block id of its own making. Two
    dropdowns' states are merged with dict.update, each under a block of its own."""
    option = [o for o in menu["options"] if json.loads(o["value"])["s"] == key][0]
    return {block: {menu["action_id"]: {"type": "static_select",
                                        "selected_option": {"text": option["text"], "value": option["value"]}}}}


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

    def test_settings_a_game_keeps(self):
        self.assertEqual(t.game_config({})["size"], "large")
        self.assertEqual(t.game_config({"size": "small"})["size"], "small")
        self.assertEqual(t.game_config({"size": "gibberish"})["size"], "large")
        self.assertEqual(t.game_config({"size": "small", "text": "itambola large"})["size"], "small",
                         "the size is not read from what is typed any more: the dropdown chooses it")
        self.assertEqual(t.game_config({})["top"], 10)
        for given, want in ((5, 5), ("7", 7), (0, 1), (-3, 1), (500, 50), ("abc", 10), (None, 10)):
            self.assertEqual(t.game_config({"top_n": given})["top"], want, repr(given))

    def test_settings_survive_being_saved_and_read_back(self):
        for size in t.SIZES:
            cfg = t.game_config({"size": size, "top_n": 7, "prizes": "top,full", "announce": "thread",
                                 "board_columns": 6, "max_players": 40, "board_style": "list"})
            self.assertEqual(t.cfg_from(json.loads(json.dumps(t.cfg_list(cfg)))), cfg)
        for junk in (None, "x", 5, [], {}, [1], ["", "", "", "", "?", "?", "?"]):
            cfg = t.cfg_from(junk)
            self.assertEqual((cfg["size"], cfg["top"], cfg["board"]), ("large", 10, "emoji"), repr(junk))
        # a game saved before board styles has six settings: it keeps its size and has the emoji board
        self.assertEqual(t.cfg_from(["full", "off", 10, 60, "small", 7]),
                         dict(t.cfg_from(["full", "off", 10, 60, "small", 7, "emoji"]), size="small", top=7))

    def test_a_game_keeps_its_size_in_its_state(self):
        for size, spec in t.SIZES.items():
            g = make_game(size, n=spec["numbers"])
            back = t.game_from_state(json.loads(json.dumps(t.state_dict(g))), False)
            self.assertEqual(back["cfg"], g["cfg"])
            self.assertEqual((t.numbers_of(back), back["n"]), (spec["numbers"], spec["numbers"]))
        small = t.game_from_state({"f": t.cfg_list(t.game_config({"size": "small"})), "n": 70}, False)
        self.assertEqual(small["n"], 30, "numbers called cannot pass the size's numbers")

    def test_the_setup_card_has_a_dropdown_standing_on_the_games_size(self):
        for size in t.SIZES:
            g = make_game(size)
            blocks = t.setup_blocks(g)
            check_blocks(blocks)
            menu = size_menu_of(blocks)
            self.assertEqual(menu["type"], "static_select")
            self.assertEqual(chosen_size(blocks), size)
            self.assertEqual([json.loads(o["value"])["s"] for o in menu["options"]], ["small", "medium", "large"])
            for option in menu["options"]:
                spec = t.SIZES[json.loads(option["value"])["s"]]
                text = option["text"]["text"]
                self.assertIn(spec["label"], text)
                self.assertIn("1 to {}".format(spec["numbers"]), text)
                self.assertIn("{} on a ticket".format(3 * spec["row"]), text)
            # the dropdown comes before the ways of joining, which are still the three they were
            kinds = [b["type"] for b in blocks]
            self.assertLess(blocks.index([b for b in blocks if b.get("accessory")][0]),
                            kinds.index("actions"))
            self.assertEqual([b["action_id"] for b in buttons_of(blocks)],
                             [t.ACTION_PREFIX + "set_" + m for m in t.MODES])

    def test_every_way_of_joining_carries_the_size_on_the_card(self):
        for size in t.SIZES:
            for test in (False, True):
                g = make_game(size, test=test)
                for button in buttons_of(t.setup_blocks(g)):
                    parsed = t.parse_value(button["value"])
                    if test:
                        self.assertEqual(t.game_from_state(parsed["state"], True)["cfg"]["size"], size)
                    else:
                        self.assertEqual(t.cfg_from(json.loads(parsed["arg"])["f"])["size"], size)

    def test_what_an_option_carries_fits_what_slack_allows(self):
        """The worst case: the longest channel id, every setting at its longest, a test game."""
        for word in ("Tambola", "Housie"):
            g = make_game("medium", test=True, prizes="early5,top,middle,bottom", announce="thread",
                          board_columns=9, max_players=100, top_n=50, board_style="numbers",
                          winners_style="carousel")
            g["id"] = "tb_C0123456789_1700000000000100"
            g["channel"], g["word"] = "C0123456789", word
            for key in list(t.SIZES) + list(t.BOARD_STYLES) + list(t.WINNERS_STYLES):
                value = t.choice_value(g, key)
                self.assertLessEqual(len(value), t.OPTION_VALUE_MAX, "{} {}: {}".format(word, len(value), value))
            check_blocks(t.setup_blocks(g))

    def test_an_option_comes_back_however_the_recipe_hands_it_over(self):
        g = make_game("small")
        value = t.choice_value(g, "medium")
        want = {"s": "medium", "m": "1700000000000100", "f": t.cfg_list(g["cfg"])}      # Tambola is the usual word
        slack_shape = {"text": {"type": "plain_text", "text": "Medium"}, "value": value}
        for given in (value, slack_shape, json.dumps(slack_shape), [slack_shape], json.dumps([slack_shape])):
            self.assertEqual(t.option_choice(given), want, repr(given)[:60])
        for nothing in (None, "", "x", "[]", [], {}, 5, "{\"value\": \"not json\"}"):
            self.assertEqual(t.option_choice(nothing), {}, repr(nothing))

    def test_the_lobby_says_what_the_size_is(self):
        for size in t.SIZES:
            g = make_game(size)
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
# Board styles
# --------------------------------------------------------------------------

class TestBoardStyles(unittest.TestCase):
    def test_names_and_aliases(self):
        for word, want in (("emoji", "emoji"), ("Emojis", "emoji"), ("numbers", "numbers"), ("plain", "numbers"),
                           ("Normal", "numbers"), ("list", "list"), ("called", "list"), ("", "emoji"), (None, "emoji"),
                           ("grid", "emoji"), (7, "emoji")):
            self.assertEqual(t.parse_board_style(word), want, repr(word))
        self.assertEqual(t.parse_board_style("nonsense", "list"), "list")
        self.assertEqual(t.DEFAULT_BOARD_STYLE, "emoji")

    def test_the_recipe_sets_where_the_dropdown_starts(self):
        self.assertEqual(t.game_config({})["board"], "emoji")
        self.assertEqual(t.game_config({"board_style": "plain"})["board"], "numbers")
        self.assertEqual(t.game_config({"board_style": "huh"})["board"], "emoji")

    def test_the_plain_grid_shows_a_number_only_once_it_is_called(self):
        for size, spec in t.SIZES.items():
            for columns in (10, 7, 5):
                grid = t.number_grid([], columns, spec["numbers"])
                lines = grid.strip("`\n").split("\n")
                self.assertEqual(len(lines), -(-spec["numbers"] // columns), (size, columns))
                self.assertEqual(grid.count("??"), spec["numbers"], "every number is hidden to begin with")
                self.assertEqual(re.findall(r"\d", grid), [], "no digit shows before a number is called")
                self.assertTrue(all(len(line) <= 4 * columns for line in lines))
        called = [4, 17, 90, 1]
        grid = t.number_grid(called, 10, 90)
        self.assertEqual(sorted(int(n) for n in re.findall(r"\d\d", grid)), [1, 4, 17, 90])
        self.assertEqual(grid.count("??"), 90 - 4)
        self.assertNotIn("[", grid, "no brackets: they would push the columns out of line")
        self.assertTrue(grid.startswith("```\n") and grid.endswith("\n```"))
        self.assertTrue(grid.startswith("```\n01  ??  ??  04"))
        # a number takes the place of the ?? it was, so nothing moves: every cell is two characters, every gap two
        for line in grid.strip("`\n").split("\n"):
            self.assertEqual(len(line), 10 * 2 + 9 * 2, line)
            self.assertEqual([m.start() % 4 for m in re.finditer(r"\?\?|\d\d", line)], [0] * 10, line)
        before, after = t.number_grid([1, 2], 10, 30), t.number_grid([1, 2, 3], 10, 30)
        self.assertEqual(before.replace("??", "03", 1), after, "calling 3 changes only the cell of 3")

    def test_the_called_list_is_smallest_first(self):
        self.assertEqual(t.called_lines([30, 4, 17, 1]), "1  \u00b7  4  \u00b7  17  \u00b7  30")
        lines = t.called_lines(list(range(90, 0, -1))).split("\n")
        self.assertEqual([len(line.split("\u00b7")) for line in lines], [15] * 6)
        self.assertEqual(t.called_lines([]), "")

    def test_the_number_just_called_is_said_in_the_style(self):
        self.assertIn(t.tiles(4), t.call_lines(4, "emoji"))
        for style in ("numbers", "list"):
            line = t.call_lines(4, style)
            self.assertNotIn(":four:", line)
            self.assertNotIn(":zero:", line)
            self.assertIn("*4*", line)
            self.assertIn("Four", line)
            self.assertIn("Knock at the door", line)
        self.assertEqual(t.call_lines(4), t.call_lines(4, "emoji"), "the emoji board is what it always was")

    def test_every_board_of_every_size_and_style_is_one_slack_takes(self):
        for size, spec in t.SIZES.items():
            for style in t.BOARD_STYLES:
                for n in (0, 1, 7, spec["numbers"] - 1, spec["numbers"]):
                    for over in ("", "game over"):
                        g = make_game(size, n=n, board_style=style, board_columns=7 if n == 7 else 10)
                        blocks = t.board_blocks(g, over)
                        try:
                            check_blocks(blocks)
                        except AssertionError as error:
                            self.fail("{} {} n={}: {}".format(size, style, n, error))

    def test_what_each_style_shows(self):
        size = "small"
        for style in t.BOARD_STYLES:
            g = make_game(size, n=9, board_style=style, seed=77)
            called = t.called_list(g)
            blocks = t.board_blocks(g)
            text = all_text(blocks)
            if style == "emoji":
                self.assertEqual(len(grid_sections(blocks)), 3)
                self.assertNotIn("[", text)
            elif style == "numbers":
                table = code_table(blocks)
                self.assertEqual(len(table), 3)
                self.assertEqual(sorted(int(n) for n in re.findall(r"\d+", "\n".join(table))), sorted(called))
                self.assertEqual("\n".join(table).count("??"), 30 - 9)
                self.assertEqual(grid_sections(blocks), [])
            else:
                self.assertEqual(grid_sections(blocks), [])
                self.assertEqual(code_table(blocks), [])
                self.assertIn("Called so far", text)
                self.assertIn(t.called_lines(called), text)
            self.assertEqual(text.count(":tickets:"), 1, style)           # the one title
            self.assertIn("9 of 30 called", text.replace("*", ""))

    def test_a_board_with_nothing_called_has_no_empty_list(self):
        blocks = t.board_blocks(make_game("small", n=0, board_style="list"))
        self.assertNotIn("Called so far", all_text(blocks))
        check_blocks(blocks)

    def test_the_review_does_not_depend_on_the_style(self):
        reviews = []
        for style in t.BOARD_STYLES:
            g = make_game("small", status=t.PAUSED, n=12, board_style=style, seed=3)
            reviews.append(all_text(t.review_blocks(g, t.review_stats(g, make_players(g, 8)))))
        self.assertEqual(len(set(reviews)), 1)

    def test_the_setup_card_has_all_three_dropdowns(self):
        for style in t.BOARD_STYLES:
            for size in t.SIZES:
                g = make_game(size, board_style=style)
                blocks = t.setup_blocks(g)
                check_blocks(blocks)
                self.assertEqual((chosen_size(blocks), chosen_board(blocks)), (size, style))
                menu = board_menu_of(blocks)
                self.assertEqual([json.loads(o["value"])["s"] for o in menu["options"]], list(t.BOARD_STYLES))
                for option in menu["options"]:
                    self.assertIn(t.BOARD_STYLES[json.loads(option["value"])["s"]]["label"], option["text"]["text"])
                kinds = [b["type"] for b in blocks]
                self.assertEqual([b["accessory"]["action_id"] for b in blocks if b.get("accessory")],
                                 [t.SIZE_ACTION, t.BOARD_ACTION, t.WINNERS_ACTION])
                self.assertLess(max(i for i, b in enumerate(blocks) if b.get("accessory")), kinds.index("actions"))
                for button in buttons_of(blocks):                       # every way of joining carries both
                    parsed = t.parse_value(button["value"])
                    cfg = (t.game_from_state(parsed["state"], False)["cfg"] if parsed["test"]
                           else t.cfg_from(json.loads(parsed["arg"])["f"]))
                    self.assertEqual((cfg["size"], cfg["board"]), (size, style))

    def test_a_test_games_state_fits_in_every_board_of_every_style(self):
        """The state of a test game is kept in the block ids of its messages, and a board with fewer blocks holds less:
        the list style with nothing called is the smallest board there is."""
        for size in t.SIZES:
            for style in t.BOARD_STYLES:
                ids = ["U" + "".join(random.Random(i).choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(10))
                       for i in range(t.TEST_PLAYERS)]
                g = make_game(size, test=True, n=0, players=2, status=t.RUNNING, board_style=style)
                g.update(roster=ids, host=ids[0], names={})
                g["wins"] = {k: {"uid": ids[1], "name": "A Long Name Here", "ts": "1700000100.000100"}
                             for k in t.PRIZE_KEYS}
                for blocks in (t.board_blocks(g), t.board_blocks(dict(g, n=9)),
                               t.lobby_closed_blocks(g, "x", title=False), t.lobby_closed_blocks(g, "x")):
                    self.assertEqual(t.carried_state({"blocks": blocks})["f"], t.cfg_list(g["cfg"]), (size, style))


# --------------------------------------------------------------------------
# Winners on the board
# --------------------------------------------------------------------------

def game_with_winners(style, keys=("early5", "top", "middle"), photos=True, **cfg):
    """A running game whose first prizes have been won one after another, a minute apart."""
    g = make_game("large", n=30, board_style="emoji", winners_style=style, **cfg)
    g["winners_open"] = True                        # the winners are on the board (Show winners, or the names style)
    for i, key in enumerate(keys):
        uid = "U%07d" % (i + 1)
        g["wins"][key] = {"uid": uid, "name": "Winner {}".format(i + 1), "ts": "{:.6f}".format(1700000100 + 60 * i),
                          "ref": "", "img": AVATAR.format(uid, 512) if photos else ""}
    return g


class TestWinners(unittest.TestCase):
    def test_names_and_aliases(self):
        for word, want in (("names", "names"), ("List", "names"), ("carousel", "carousel"), ("photos", "carousel"),
                           ("Cards", "carousel"), ("strip", "strip"), ("avatars", "strip"), ("none", "none"),
                           ("off", "none"), ("", "names"), (None, "names"), ("huh", "names")):
            self.assertEqual(t.parse_winners(word), want, repr(word))
        self.assertEqual(t.DEFAULT_WINNERS, "names")

    def test_settings(self):
        self.assertEqual(t.game_config({})["winners"], "names")
        self.assertEqual(t.game_config({"winners_style": "photos"})["winners"], "carousel")
        cfg = t.game_config({"winners_style": "strip", "size": "small"})
        self.assertEqual(t.cfg_from(json.loads(json.dumps(t.cfg_list(cfg)))), cfg)
        for old in ([], ["", "", "", "", "small", "", "list", "printed"], ["full", "off", 10, 60]):
            self.assertEqual(t.cfg_from(old)["winners"], "names", old)

    def test_a_setting_at_its_usual_value_is_written_blank_and_read_back(self):
        usual = t.game_config({})
        saved = t.cfg_list(usual)
        self.assertEqual(saved[:4] + saved[5:6], ["", "", "", "", ""])
        self.assertEqual(t.cfg_from(saved), usual)
        odd = t.game_config({"announce": "off", "board_columns": 6, "max_players": 30, "top_n": 3, "prizes": "top"})
        self.assertEqual(t.cfg_list(odd)[:6], ["top", "off", 6, 30, "large", 3])
        self.assertEqual(t.cfg_from(t.cfg_list(odd)), odd)

    def test_names_is_the_boards_original_list(self):
        g = game_with_winners("names")
        blocks = t.winners_blocks(g)
        self.assertEqual([b["type"] for b in blocks], ["section"])
        text = all_text(blocks)
        self.assertIn("Winner 1", text)
        self.assertIn("open", text)
        self.assertEqual(blocks, [t._section(fields=t.prize_fields(g))])

    def test_none_lists_no_winners_at_all(self):
        g = game_with_winners("none")
        self.assertEqual(t.winners_blocks(g), [])
        self.assertNotIn("Winner 1", all_text(t.board_blocks(g)))

    def test_the_carousel_has_the_newest_winner_on_the_left_and_the_first_on_the_right(self):
        g = game_with_winners("carousel", ("early5", "top", "middle"))
        blocks = t.winners_blocks(g)
        check_blocks(blocks)
        cards = carousel_of(blocks)
        self.assertEqual([c["subtitle"]["text"] for c in cards], ["Winner 3", "Winner 2", "Winner 1"])
        self.assertEqual([c["title"]["text"] for c in cards],
                         [":tada::sparkles: *Middle Line* :sparkles::tada:",
                          ":tada::sparkles: *Top Line* :sparkles::tada:", ":zap: *Early Five* :zap:"])
        self.assertEqual(cards[-1]["body"]["text"], t.WINNER_BODY["early5"] + " :clap:")
        for card, uid in zip(cards, ("U0000003", "U0000002", "U0000001")):
            self.assertEqual(card["hero_image"]["image_url"], AVATAR.format(uid, 512))
            self.assertIn("winner of the", card["hero_image"]["alt_text"])
        self.assertEqual(all_text(blocks).count("Still to win"), 1)
        self.assertIn("Bottom Line  ·  Full House", all_text(blocks))
        self.assertNotIn("Early Five  ·", all_text(blocks).split("Still to win")[1], "only what is still open")

    def test_the_order_is_the_order_they_were_won_not_the_prizes(self):
        g = game_with_winners("carousel", ("full", "early5"))
        g["wins"]["full"]["ts"] = "1700000500.000000"
        g["wins"]["early5"]["ts"] = "1700000100.000000"
        self.assertEqual([c["title"]["text"] for c in carousel_of(t.winners_blocks(g))],
                         [":trophy::tada::sparkles: *Full House* :sparkles::tada::trophy:", ":zap: *Early Five* :zap:"])
        g["wins"]["full"]["ts"] = "1700000050.000000"                            # Full House first this time
        self.assertEqual([c["title"]["text"] for c in carousel_of(t.winners_blocks(g))],
                         [":zap: *Early Five* :zap:",
                          ":trophy::tada::sparkles: *Full House* :sparkles::tada::trophy:"])

    def test_a_winner_without_a_picture_is_a_card_without_one(self):
        g = game_with_winners("carousel", ("early5", "top"), photos=False)
        cards = carousel_of(t.winners_blocks(g))
        self.assertEqual(len(cards), 2)
        self.assertTrue(all("hero_image" not in c for c in cards))
        check_blocks(t.winners_blocks(g))

    def test_every_prize_won_is_five_cards_and_no_still_to_win_line(self):
        g = game_with_winners("carousel", t.PRIZE_KEYS)
        blocks = t.winners_blocks(g)
        check_blocks(blocks)
        self.assertEqual(len(carousel_of(blocks)), 5)
        self.assertEqual([b["type"] for b in blocks], ["carousel"])

    def test_nobody_has_won_yet(self):
        for style in ("carousel", "strip"):
            blocks = t.winners_blocks(game_with_winners(style, ()))
            self.assertEqual([b["type"] for b in blocks], ["context"], style)
            self.assertIn("*Still to win:*  Early Five  ·  Top Line  ·  Middle Line  ·  Bottom Line  ·  Full House",
                          all_text(blocks))
            check_blocks(blocks)

    def test_only_prizes_in_play_are_listed(self):
        g = game_with_winners("carousel", ("top",), prizes="top,full")
        blocks = t.winners_blocks(g)
        self.assertEqual(len(carousel_of(blocks)), 1)
        self.assertIn("*Still to win:*  Full House", all_text(blocks))
        self.assertNotIn("Early Five", all_text(blocks))

    def test_the_strip_is_one_line_of_small_pictures_newest_first(self):
        g = game_with_winners("strip", t.PRIZE_KEYS)
        blocks = t.winners_blocks(g)
        check_blocks(blocks)
        strip = blocks[0]["elements"]
        self.assertEqual(len(strip), 10, "five pictures and five names fill a context block")
        self.assertEqual([e["type"] for e in strip], ["image", "mrkdwn"] * 5)
        self.assertEqual(strip[0]["image_url"], AVATAR.format("U0000005", 512))
        self.assertEqual(strip[-1]["text"], "*Early Five* Winner 1")
        g = game_with_winners("strip", ("top",), photos=False)
        self.assertEqual([e["type"] for e in t.winners_blocks(g)[0]["elements"]], ["mrkdwn"])

    def test_names_cannot_break_a_card(self):
        g = game_with_winners("carousel", ("top",))
        g["wins"]["top"]["name"] = "A & B <team> " + "x" * 400
        blocks = t.winners_blocks(g)
        check_blocks(blocks)
        card = carousel_of(blocks)[0]
        self.assertIn("A &amp; B &lt;team&gt;", card["subtitle"]["text"])
        self.assertLessEqual(len(card["subtitle"]["text"]), 150)
        g["wins"]["top"]["name"] = ""
        self.assertEqual(carousel_of(t.winners_blocks(g))[0]["subtitle"]["text"], "Someone")

    def test_the_board_carries_the_winners_in_every_style_and_size(self):
        for size in t.SIZES:
            for style in t.WINNERS_STYLES:
                for board in t.BOARD_STYLES:
                    g = make_game(size, n=7, board_style=board, winners_style=style)
                    g["winners_open"] = True
                    g["wins"] = game_with_winners(style, ("early5", "top", "full"))["wins"]
                    blocks = t.board_blocks(g)
                    try:
                        check_blocks(blocks)
                    except AssertionError as error:
                        self.fail("{} {} {}: {}".format(size, style, board, error))
                    kinds = [b["type"] for b in blocks]
                    self.assertEqual("carousel" in kinds, style == "carousel", (size, style, board))

    def test_a_test_games_state_still_fits_with_a_carousel(self):
        for size in t.SIZES:
            for style in t.WINNERS_STYLES:
                ids = ["U" + "".join(random.Random(i).choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789") for _ in range(10))
                       for i in range(t.TEST_PLAYERS)]
                g = make_game(size, test=True, n=9, players=2, status=t.RUNNING, winners_style=style,
                              board_style="list")
                g.update(roster=ids, host=ids[0], names={})
                g["wins"] = {k: {"uid": ids[1], "name": "A Long Name Here", "ts": "1700000100.000100",
                                 "img": AVATAR.format(ids[1], 512)} for k in t.PRIZE_KEYS}
                back = t.carried_state({"blocks": t.board_blocks(g)})
                self.assertEqual(back["f"], t.cfg_list(g["cfg"]), (size, style))
                self.assertNotIn("avatars.example.com", json.dumps(back), "no picture addresses in the message's state")

    def test_the_winners_are_shown_by_default_only_in_the_names_style(self):
        for style, shown in (("names", True), ("carousel", False), ("strip", False), ("none", False)):
            g = make_game("small", winners_style=style)
            self.assertEqual(t.winners_open(g), shown, style)
        g = game_with_winners("carousel")
        g["winners_open"] = False
        self.assertEqual(t.winners_blocks(g), [], "hidden: nothing of the winners on the board")
        g["winners_open"] = True
        self.assertTrue(carousel_of(t.winners_blocks(g)))
        g = game_with_winners("names")
        g["winners_open"] = False
        self.assertEqual(t.winners_blocks(g), [])
        g = game_with_winners("none")
        g["winners_open"] = True
        self.assertEqual(t.winners_blocks(g), [], "none never lists them, shown or not")

    def test_shown_or_hidden_is_kept_with_the_game(self):
        for opened in (None, True, False):
            g = make_game("small", winners_style="carousel")
            g["winners_open"] = opened
            back = t.game_from_state(json.loads(json.dumps(t.state_dict(g))), False)
            self.assertEqual(back["winners_open"], opened)
        self.assertNotIn("o", t.state_dict(make_game("small")), "a game never asked keeps nothing")
        self.assertIsNone(t.game_from_state({"f": []}, False)["winners_open"], "a game saved before it has none")

    def test_a_win_keeps_where_it_was_announced_and_the_numbers_of_its_line(self):
        g = make_game("small", test=True, n=9)
        g["wins"] = {"top": {"uid": "U0000001", "name": "Priya", "ts": "1700000100.000100", "ann": "1700000101.000200",
                             "nums": [3, 16, 23]},
                     "early5": {"uid": "U0000002", "name": "Sam", "ts": "1700000050.000100"}}
        back = t.game_from_state(json.loads(json.dumps(t.state_dict(g))), True)
        self.assertEqual(back["wins"]["top"]["ann"], "1700000101.000200")
        self.assertEqual(back["wins"]["top"]["nums"], [3, 16, 23])
        self.assertNotIn("ann", back["wins"]["early5"])
        self.assertNotIn("nums", back["wins"]["early5"])
        rows = [{"grant_type": "top", "group_id": "U0000001", "member_name": "Priya", "last_processed_ts": "1.5",
                 "source_ref": "a",
                 "content": json.dumps({"img": "https://x.com/a.png", "nums": [3, 16], "ann": "9.9"})}]
        win = t.wins_from_rows(rows)["top"]
        self.assertEqual((win["img"], win["nums"], win["ann"]), ("https://x.com/a.png", [3, 16], "9.9"))
        self.assertEqual(t.win_content({"img": "", "nums": [], "ann": ""}), None, "nothing to keep, nothing written")
        self.assertEqual(json.loads(t.win_content({"img": "u", "nums": [1], "ann": "t"})),
                         {"img": "u", "nums": [1], "ann": "t"})

    def test_the_setup_card_has_the_winners_dropdown(self):
        for style in t.WINNERS_STYLES:
            g = make_game("large", winners_style=style)
            blocks = t.setup_blocks(g)
            check_blocks(blocks)
            self.assertEqual(chosen_winners(blocks), style)
            menu = winners_menu_of(blocks)
            self.assertEqual([json.loads(o["value"])["s"] for o in menu["options"]], list(t.WINNERS_STYLES))
            for button in buttons_of(blocks):
                parsed = t.parse_value(button["value"])
                cfg = (t.game_from_state(parsed["state"], False)["cfg"] if parsed["test"]
                       else t.cfg_from(json.loads(parsed["arg"])["f"]))
                self.assertEqual(cfg["winners"], style)


# --------------------------------------------------------------------------
# The printed ticket
# --------------------------------------------------------------------------

class TestPrintedTicket(unittest.TestCase):
    USERS = ("UAAAAAAA1", "UBBBBBBB2", "UCCCCCCC3", "UDDDDDDD4", "UHOST0001")

    def test_there_is_no_layout_to_choose(self):
        for name in ("LAYOUTS", "LAYOUT_ACTION", "parse_layout", "DEFAULT_LAYOUT", "LEGACY_LAYOUT"):
            self.assertFalse(hasattr(t, name), name)
        self.assertEqual(t.MENUS, ("size", "board", "winners"))
        self.assertNotIn("layout", t.game_config({"ticket_layout": "compact"}), "an old input is simply not read")
        for test in (False, True):
            blocks = t.setup_blocks(make_game("large", test=test))
            check_blocks(blocks)
            self.assertEqual([b["accessory"]["action_id"] for b in blocks if b.get("accessory")],
                             [t.SIZE_ACTION, t.BOARD_ACTION, t.WINNERS_ACTION])
            self.assertNotIn("layout", all_text(blocks).lower())

    def test_settings_are_kept_and_read_back(self):
        cfg = t.game_config({"size": "medium", "board_style": "list", "top_n": 4, "prizes": "top,full",
                             "winners_style": "strip"})
        self.assertEqual(t.cfg_from(json.loads(json.dumps(t.cfg_list(cfg)))), cfg)
        self.assertNotIn("layout", cfg)

    def test_a_game_saved_with_a_ticket_layout_in_its_settings_reads_the_same(self):
        """The eighth place of the settings was the ticket layout. It is not a choice any more, but a game saved with it
        still has its winners style, which comes after it, and one saved here still reads in an earlier version."""
        saved = ["", "channel", 10, 60, "small", 10, "list", "compact", "carousel"]
        cfg = t.cfg_from(saved)
        self.assertEqual((cfg["announce"], cfg["cols"], cfg["max"], cfg["size"], cfg["board"], cfg["winners"]),
                         ("channel", 10, 60, "small", "list", "carousel"))
        written = t.cfg_list(cfg)
        self.assertEqual((len(written), written[7], written[8]), (9, "printed", "carousel"))
        for old in ([], ["", "channel", 10, 60], ["", "channel", 10, 60, "large", 10, "emoji"],
                    ["", "channel", 10, 60, "large", 10, "emoji", "printed"]):
            self.assertEqual(t.cfg_from(old)["winners"], "names", old)

    def test_all_five_prizes_are_left_blank_in_what_a_game_saves(self):
        every = t.game_config({})
        self.assertEqual(t.cfg_list(every)[0], "")
        self.assertEqual(t.cfg_from(t.cfg_list(every))["prizes"], list(t.PRIZE_KEYS))
        some = t.game_config({"prizes": "top,full"})
        self.assertEqual(t.cfg_list(some)[0], "top,full")
        self.assertEqual(t.cfg_from(t.cfg_list(some))["prizes"], ["top", "full"])
        self.assertEqual(t.cfg_from(["early5,top,middle,bottom,full"])["prizes"], list(t.PRIZE_KEYS),
                         "a game saved with the five spelled out reads the same")

    def test_printed_cells_put_every_number_in_its_column(self):
        for size, spec in t.SIZES.items():
            columns, ranges = columns_of(size), t.column_ranges(spec["numbers"])
            for seed in range(1, 30):
                for user in self.USERS:
                    g = make_game(size, seed=seed)
                    ticket = t.make_ticket(seed, user, size)
                    rows = t.ticket_cells(g, ticket)
                    where = (size, seed, user)
                    self.assertEqual([len(r) for r in rows], [columns] * 3, where)
                    self.assertEqual(sorted(n for r in rows for n in r if n), sorted(t.ticket_numbers(ticket)), where)
                    for cells, row in zip(rows, ticket):
                        self.assertEqual([n for n in cells if n], row, "a row reads left to right, ascending")
                        for column, number in enumerate(cells):
                            if number:
                                low, high = ranges[column]
                                self.assertTrue(low <= number <= high,
                                                "{} in column {} of {}".format(number, column, where))
                    for column in range(columns):                                      # and down a column, ascending
                        down = [r[column] for r in rows if r[column]]
                        self.assertEqual(down, sorted(down), where)
                        self.assertTrue(1 <= len(down) <= 3, where)

    def test_a_ticket_that_does_not_fit_the_columns_is_drawn_as_its_rows_not_cut(self):
        g = make_game("large")
        odd = [[11, 12, 30, 50, 75], [5, 28, 44, 60, 77], [47, 58, 63, 78, 89]]      # 11 and 12: both in column two
        self.assertEqual(t.ticket_cells(g, odd), odd)
        self.assertIsNot(t.ticket_cells(g, odd)[0], odd[0], "a copy, never the ticket's own rows")

    def test_how_the_columns_are_named(self):
        self.assertEqual(t.column_names(90), "1-9, 10s, 20s ... 80s")
        self.assertEqual(t.column_names(60), "1-9, 10s, 20s ... 50s")
        self.assertEqual(t.column_names(30), "1-9, 10s, 20s")

    def test_a_ticket_at_every_size(self):
        for size, spec in t.SIZES.items():
            for marked in (0, 1, 5):
                g = make_game(size)
                ticket = t.deal_ticket(g, HOST)
                marks = set(t.ticket_numbers(ticket)[:marked])
                for blocks in (t.ticket_blocks(g, ticket, marks), t.panel_blocks(g, mine=(ticket, marks))):
                    where = (size, marked)
                    try:
                        check_blocks(blocks)
                    except AssertionError as error:
                        self.fail("{}: {}".format(where, error))
                    self.assertEqual(row_widths(blocks), [columns_of(size)] * 3, where)
                    buttons = [b for b in buttons_of(blocks)
                               if b["action_id"].startswith((t.ACTION_PREFIX + "mark_", t.ACTION_PREFIX + "hmark_",
                                                             t.BLANK_ACTION))]
                    ids = [b["action_id"] for b in buttons]
                    self.assertEqual(len(ids), len(set(ids)), "every button needs an id of its own")
                    blanks = [b for b in buttons if b["action_id"].startswith(t.BLANK_ACTION)]
                    numbers = [b for b in buttons if not b["action_id"].startswith(t.BLANK_ACTION)]
                    self.assertEqual(len(numbers), 3 * spec["row"], where)
                    self.assertEqual(len(blanks), 3 * (columns_of(size) - spec["row"]), where)
                    for blank in blanks:
                        parsed = t.parse_value(blank["value"], blank["action_id"])
                        self.assertEqual((parsed["kind"], parsed["test"]), ("blank", True))
                    marked_buttons = [b for b in numbers if b.get("style") == "primary"]
                    self.assertEqual(len(marked_buttons), marked, where)
                    for b in marked_buttons:
                        self.assertIn(":white_check_mark:", b["text"]["text"])

    def test_the_ticket_names_its_columns_only_when_they_are_there_to_find(self):
        for size in t.SIZES:
            g = make_game(size)
            text = all_text(t.ticket_blocks(g, t.deal_ticket(g, HOST), set()))
            self.assertEqual("Each number sits in its column" in text, size != "small", size)
        g = make_game("large")
        self.assertIn("1-9, 10s, 20s ... 80s", all_text(t.ticket_blocks(g, t.deal_ticket(g, HOST), set())))

# --------------------------------------------------------------------------
# Every card, against Slack's limits
# --------------------------------------------------------------------------

class TestCards(unittest.TestCase):
    def cards(self, size, test):
        out = t.main({"text": "itambola", "size": size, "user_id": HOST, "channel": "C0TEST",
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
            self.assertEqual(row_widths(ticket), [columns_of(size)] * 3, size)
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

    def test_the_boards_last_line(self):
        for status, over, hint in ((t.RUNNING, "", True), (t.PAUSED, "", True), (t.RUNNING, "x", False),
                                   (t.DONE, "x", False), (t.DONE, "", False)):
            g = make_game("small", status=status, n=3)
            line = t.board_foot(g, bool(over))
            self.assertIn("Hosted by", line)
            self.assertEqual("lost your ticket" in line, hint, (status, over))
        self.assertEqual(t.board_foot(make_game(status=t.DONE)).count("itambola"), 0)

    def test_the_title_is_said_once(self):
        """:tickets: and the game's name are the header's, once: not again in the host line, the rules, or the line the
        lobby shrinks to when the game starts (the board below it has the title)."""
        for word in ("Tambola", "Housie"):
            g = make_game("large", n=3)
            g["word"] = word
            lobby = all_text(t.lobby_blocks(g))
            self.assertEqual((lobby.count(":tickets:"), lobby.count(word)), (1, 1), lobby)
            started = t.lobby_closed_blocks(g, t.LOBBY_STARTED.format(count=4, players="players"), title=False)
            text = all_text(started)
            self.assertEqual((text.count(":tickets:"), text.count(word), text.count(word.lower())), (0, 0, 0), text)
            self.assertNotIn("header", [b["type"] for b in started])
            self.assertNotIn("Prizes", text, "the board has them")
            self.assertIn("4 players", text)
            self.assertIn("Players (4)", text)
            board = all_text(t.board_blocks(g))
            self.assertEqual((board.count(":tickets:"), board.count(word)), (1, 1), board)
            cancelled = all_text(t.lobby_closed_blocks(g, t.LOBBY_CANCELLED.format(host="Priya")))
            self.assertEqual(cancelled.count(":tickets:"), 1, "a cancelled game has no board: it keeps its title")
            ticket = all_text(t.ticket_blocks(g, t.deal_ticket(g, HOST), set()))
            self.assertEqual(ticket.count(word), 0)

    def test_the_organizers_card_follows_the_size(self):
        for size, spec in t.SIZES.items():
            g = make_game(size, n=5)
            ticket = t.deal_ticket(g, HOST)
            blocks = t.panel_blocks(g, mine=(ticket, set()))
            check_blocks(blocks)
            self.assertEqual(row_widths(blocks), [columns_of(size)] * 3, size)           # laid out as a printed ticket
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

AVATAR = "https://avatars.example.com/{}_{}.png"          # a profile picture of a made-up person
HOOK = "https://hooks.slack.com/actions/T0TEST/1/"          # a response_url: the person it answers is the last part
CONTROLS = ("start", "cancel", "next", "review", "resume", "end", "myticket")


class World(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = 1700000000.0
        self.counter = 0
        self.messages = {}            # (channel, ts) -> {"ts", "text", "blocks"}
        self.private = []             # what only one person sees: {"user", "channel", "blocks", "text", "how"}
        self.updated = []             # (channel, ts) of every message edited, in order
        self.deleted = []             # (channel, ts) of every message deleted, in order
        self.posts = []               # every message ever posted, as it was posted (messages may be edited or deleted)
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
            if self.refuse_carousel and any(b.get("type") == "carousel" for b in payload.get("blocks") or []):
                return {"ok": False, "error": "invalid_blocks"}, None
            if any("bad.example" in b.get("image_url", "") for b in payload.get("blocks") or []):
                return {"ok": False, "error": "invalid_blocks",
                        "response_metadata": {"messages": ["downloading image failed"]}}, None
            channel = payload["channel"]
            if channel[0] in "UW":                       # a message to a person lands in their private message
                channel = "D" + channel
            blocks = self._checked(payload)
            ts = self.next_ts()
            self.messages[(channel, ts)] = {"ts": ts, "text": payload.get("text"), "blocks": blocks}
            self.posts.append({"channel": channel, "ts": ts, "text": payload.get("text"),
                               "blocks": copy.deepcopy(blocks)})
            return {"ok": True, "channel": channel, "ts": ts}, None
        if endpoint == "chat.update":
            key = (payload["channel"], payload["ts"])
            if key not in self.messages:
                return {"ok": False, "error": "message_not_found"}, None
            if self.refuse_carousel and any(b.get("type") == "carousel" for b in payload.get("blocks") or []):
                return {"ok": False, "error": "invalid_blocks"}, None
            self.messages[key].update(text=payload.get("text"), blocks=self._checked(payload))
            self.updated.append(key)
            return {"ok": True}, None
        if endpoint == "chat.delete":
            key = (payload["channel"], payload["ts"])
            if key not in self.messages:                  # as Slack says it of a message that is not there any more
                return {"ok": False, "error": "message_not_found"}, None
            del self.messages[key]
            self.deleted.append(key)
            return {"ok": True}, None
        if endpoint == "chat.postEphemeral":
            self.private.append({"user": payload["user"], "channel": payload["channel"], "text": payload.get("text"),
                                 "blocks": self._checked(payload), "how": "note"})
            return {"ok": True, "message_ts": self.next_ts()}, None
        if endpoint == "users.info":
            user = query["user"]
            return {"ok": True, "user": {"id": user, "is_bot": False, "deleted": False,
                                         "profile": {"real_name": self.names.get(user, ""),
                                                     "image_192": AVATAR.format(user, 192),
                                                     "image_512": AVATAR.format(user, 512)}}}, None
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

    def tickets_of(self, user):
        """[(channel, ts, blocks)] of the ticket messages in this person's private messages."""
        return [(c, ts, m["blocks"]) for (c, ts), m in self.messages.items()
                if c == "D" + user and any(b["action_id"].startswith(t.ACTION_PREFIX + "mark_")
                                           for b in buttons_of(m["blocks"]))]

    def ticket_of(self, user):
        """(channel, ts, blocks) of the ticket message in this person's private messages, the one with numbers on it."""
        found = self.tickets_of(user)
        assert len(found) == 1, "{} has {} tickets".format(user, len(found))
        return found[0]

    def host_card(self, user):
        """The organizer's own card as their controls note shows it, opened first if it is not open: the note's blocks.
        The organizer has no ticket message: it is sent to nobody but opens in the note."""
        blocks = self.panel(user)
        if not any(b["action_id"].startswith(t.ACTION_PREFIX + "hmark_") for b in buttons_of(blocks)):
            out = self.click(user, button_named(blocks, "myticket"), self.channel)
            assert out["ok"], out
            blocks = self.panel(user)
        return blocks

    def channel_messages(self, channel):
        return [m for (c, _ts), m in sorted(self.messages.items()) if c == channel]

    def rows_of(self, row_type):
        return [r for r in self.rows.values() if r.get("row_type") == row_type]

    # -- what people do
    via = "fields"                    # "fields": the recipe maps each field; "payload": it maps the whole interaction
    settings = {}                     # inputs the click recipe always has (its banners): added to every press
    refuse_carousel = False           # a workspace whose Slack turns the carousel block down
    channel = "C0GAME"                # the channel the word was last typed in (where the organizer's card is opened)

    def _press(self, user, action, channel, source_ts, response, state, extra):
        """Run a press through main(), the way the click recipe hands it over: field by field, or as `payload`, the
        interaction as Slack sends it (inside the trigger's own wrapper)."""
        tokens = {"slack_bot_token": "xoxb-test", "workato_api_token": "wk-test"}
        if self.via == "payload":
            payload = {"type": "block_actions", "user": {"id": user, "username": "someone", "team_id": "T0TEST"},
                       "container": {"type": "message", "message_ts": source_ts, "channel_id": channel,
                                     "is_ephemeral": True},
                       "channel": {"id": channel, "name": "games"}, "state": {"values": state or {}},
                       "actions": [dict(action, block_id="yR2vV", action_ts=self.tick())]}
            if response:
                payload["response_url"] = HOOK + user
            given = dict(tokens, payload=json.dumps({"block_actions:button": payload}))
        else:
            given = dict(tokens, action_id=action["action_id"], user_id=user, channel=channel, source_ts=source_ts,
                         action_ts=self.tick())
            if "value" in action:
                given["action_value"] = action["value"]
            if "selected_option" in action:
                given["selected_option"] = json.dumps(action["selected_option"])
            if response:
                given["response_url"] = HOOK + user
            if state is not None:
                given["state"] = {"values": state}
        given.update(self.settings)
        given.update(extra)
        return t.main(given)

    def click(self, user, button, channel, source_ts="", response=True, state=None, **extra):
        """A press on `button`. `state` is what the dropdowns on the message hold at that moment (Slack sends it)."""
        action = {"type": "button", "action_id": button["action_id"], "value": button.get("value") or ""}
        return self._press(user, action, channel, source_ts, response, state, extra)

    def type_word(self, user, channel, text, **extra):
        self.channel = channel
        given = {"text": text, "user_id": user, "channel": channel, "message_ts": self.next_ts(),
                 "slack_bot_token": "xoxb-test", "workato_api_token": "wk-test"}
        given.update(extra)
        return t.main(given)

    def select(self, user, menu, size, channel, source_ts="", response=True, state=None, **extra):
        """Choosing `size` on a dropdown, the way Slack sends it: no value, the option in selected_option."""
        option = [o for o in menu["options"] if json.loads(o["value"])["s"] == size][0]
        action = {"type": "static_select", "action_id": menu["action_id"],
                  "selected_option": {"text": option["text"], "value": option["value"]}}
        return self._press(user, action, channel, source_ts, response, state, extra)

    def tap(self, user, number):
        """The player taps `number` on their ticket, if it is there. The recipe's result, or None. The organizer has no
        ticket message: they tap on the card in their controls, opened if it is not."""
        if not self.tickets_of(user):
            found = [b for b in buttons_of(self.host_card(user))
                     if b["action_id"] == t.ACTION_PREFIX + "hmark_{}".format(number)]
            return self.click(user, found[0], self.channel) if found else None
        channel, ts, blocks = self.ticket_of(user)
        found = [b for b in buttons_of(blocks) if b["action_id"] == t.ACTION_PREFIX + "mark_{}".format(number)]
        if not found:
            return None
        return self.click(user, found[0], channel, source_ts=ts, response=False)


def ticket_numbers_on(blocks):
    """The numbers on a ticket's buttons: a player's ticket (mark_) or the organizer's card in their note (hmark_)."""
    return [int(b["action_id"].rsplit("_", 1)[1]) for b in buttons_of(blocks)
            if b["action_id"].startswith((t.ACTION_PREFIX + "mark_", t.ACTION_PREFIX + "hmark_"))]


# --------------------------------------------------------------------------
# Prizes are won once
# --------------------------------------------------------------------------

class TestClaims(unittest.TestCase):
    """What was seen in Slack: "Early Five goes to ..." twice in a row. When one player's click was handled twice, both
    attempts found that player holding the prize, and each took that as its own win."""

    def setUp(self):
        self.world = World()
        for name, new in (("_send_json", self.world.send), ("_now", lambda: self.world.clock),
                          ("_sleep", lambda seconds: None)):
            patcher = mock.patch.object(t, name, new)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.g = make_game("small", seed=5, n=10)
        self.table = t.Table("x")
        self.result = {"warnings": []}

    def claim(self, user="UHOST0001", name="Priya", stamp="1700000001.000100", keys=("early5",)):
        return t.claim_prizes(self.table, dict(self.g, wins={}), list(keys), user, name, stamp, self.result)

    def test_the_same_claim_handled_twice_is_won_once(self):
        for round_ in range(25):          # the second attempt must never win the tie, whatever its token looks like
            self.world.rows.clear()
            self.assertEqual(self.claim(), (["early5"], []), round_)
            self.assertEqual(self.claim(), ([], []), "the same click, handled again (round {})".format(round_))
            self.assertEqual(self.claim(stamp="1700000009.000100"), ([], []), "the number tapped again, later")
            self.assertEqual(len(self.world.rows_of(t.WIN_ROW)), 3, "every attempt is on record")

    def test_a_repeat_is_not_a_loss_either(self):
        self.claim()
        won, lost = self.claim(stamp="1700000009.000100")
        self.assertEqual((won, lost), ([], []), "the player holds it: nothing to tell them but that they do")

    def test_two_attempts_at_the_same_moment_have_one_winner(self):
        """The second attempt's row is written while the first is waiting to check, so both then read both rows."""
        for round_ in range(30):
            self.world.rows.clear()
            outs, state = {}, {"inside": False}

            def sleeper(seconds):
                if not state["inside"]:
                    state["inside"] = True
                    outs["second"] = self.claim()
            with mock.patch.object(t, "_sleep", sleeper):
                outs["first"] = self.claim()
            winners = len(outs["first"][0]) + len(outs["second"][0])
            self.assertEqual(winners, 1, "round {}: {}".format(round, outs))
            self.assertEqual(len(self.world.rows_of(t.WIN_ROW)), 2)

    def test_another_player_with_a_later_click_loses_and_with_an_earlier_one_wins(self):
        self.assertEqual(self.claim(), (["early5"], []))
        self.assertEqual(self.claim("UJACK0002", "Jack", "1700000005.000100"), ([], [("early5", "Priya")]))
        self.assertEqual(self.claim("USAM00003", "Sam", "1700000000.500000"), (["early5"], []))

    def test_every_prize_asked_for_is_settled_on_its_own(self):
        self.assertEqual(self.claim(keys=("early5", "top")), (["early5", "top"], []))
        self.assertEqual(self.claim("UJACK0002", "Jack", "1700000005.000100", ("top", "middle")),
                         (["middle"], [("top", "Priya")]))
        self.assertEqual(self.claim(keys=("top",), stamp="1700000009.000100"), ([], []), "held already, by this player")
        # an earlier click is the one that holds a prize, so a repeat that carries the earlier time takes it back
        self.assertEqual(self.claim(keys=("middle",)), (["middle"], []))

    def test_a_table_that_does_not_keep_the_token_still_names_a_winner(self):
        """If the data table dropped the token, nobody can be told apart: as before, the holder wins. Never silence."""
        real = World._table

        def without_token(world, url, payload, method):
            if method == "POST" and not url.endswith("/query"):
                payload = dict(payload, document={k: v for k, v in payload["document"].items()
                                                  if k != "$" + t.COLUMNS["source_ref"]})
            return real(world, url, payload, method)
        with mock.patch.object(World, "_table", without_token):
            self.assertEqual(self.claim(), (["early5"], []))
            self.assertEqual(self.claim("UJACK0002", "Jack", "1700000005.000100"), ([], [("early5", "Priya")]))

    def test_the_same_holder_is_picked_whatever_order_the_rows_come_in(self):
        rows = [{"grant_type": "early5", "group_id": "UHOST0001", "member_name": "Priya",
                 "last_processed_ts": "1700000001.000100", "source_ref": ref} for ref in ("bbb", "aaa", "ccc")]
        for order in (rows, rows[::-1], rows[1:] + rows[:1]):
            self.assertEqual(t.wins_from_rows(order)["early5"]["ref"], "aaa")

    def test_a_win_row_carries_its_attempts_token(self):
        self.claim()
        self.claim()
        refs = [r["source_ref"] for r in self.world.rows_of(t.WIN_ROW)]
        self.assertTrue(all(refs) and len(set(refs)) == 2, refs)

    def test_a_test_game_has_nothing_to_tell_apart_and_wins_once(self):
        g = make_game("small", test=True, seed=5, n=10)
        self.assertEqual(t.claim_prizes(self.table, g, ["early5"], "UHOST0001", "Priya", "1.5", self.result),
                         (["early5"], []))
        self.assertEqual(t.claim_prizes(self.table, g, ["early5"], "UHOST0001", "Priya", "1.6", self.result),
                         ([], []))


# --------------------------------------------------------------------------
# Celebrations
# --------------------------------------------------------------------------

def emoji_count(blocks):
    return len(re.findall(r":[a-z0-9_+-]+:", all_text(blocks)))


class TestCelebrations(unittest.TestCase):
    def blocks(self, key, banner=""):
        g = make_game("large", n=20)
        ticket = t.deal_ticket(g, HOST)
        return t.win_blocks(g, key, "Priya Sharma", ticket, banner), ticket

    def test_each_tier_is_bigger_than_the_one_before(self):
        self.assertEqual({k: t.PRIZE_TIER[k] for k in t.PRIZE_KEYS},
                         {"early5": 1, "top": 2, "middle": 2, "bottom": 2, "full": 3})
        early, _ = self.blocks("early5")
        line, _ = self.blocks("top")
        house, _ = self.blocks("full")
        self.assertEqual([b["type"] for b in early], ["section"], "Early Five is one quiet line")
        self.assertEqual([b["type"] for b in line], ["header", "section"], "a line gets a header, Slack's big text")
        self.assertEqual([b["type"] for b in house], ["header", "section", "divider"])
        self.assertLess(emoji_count(early), emoji_count(line))
        self.assertLess(emoji_count(line), emoji_count(house))
        self.assertLess(len(all_text(early)), len(all_text(line)))
        self.assertLess(len(all_text(line)), len(all_text(house)))
        self.assertEqual((emoji_count(early), emoji_count(line)), (1, 7), "one, then a header and a few more")
        self.assertGreaterEqual(emoji_count(house), 16)

    def test_what_each_announcement_says(self):
        for key in t.PRIZE_KEYS:
            blocks, ticket = self.blocks(key)
            check_blocks(blocks)
            text = all_text(blocks)
            self.assertIn("Priya Sharma", text)
            self.assertIn("goes to" if key != "full" else "Full House!", text)
            if key in t.LINES:
                made_it = "  ·  ".join(str(n) for n in ticket[t.LINES[key]])
                self.assertIn(made_it, text, "the numbers that made the line")
                self.assertIn(t.PRIZE_NAME[key], [b for b in blocks if b["type"] == "header"][0]["text"]["text"])
        full, _ = self.blocks("full")
        self.assertIn("FULL HOUSE", full[0]["text"]["text"])
        self.assertIn("That is the game", all_text(full))

    def test_a_banner_goes_on_top_and_is_not_needed(self):
        for key in t.PRIZE_KEYS:
            plain, _ = self.blocks(key)
            with_banner, _ = self.blocks(key, "https://img.example.com/{}.png".format(key))
            self.assertNotIn("image", [b["type"] for b in plain])
            url = "https://img.example.com/{}.png".format(key)
            self.assertEqual(with_banner[0],
                             {"type": "image", "image_url": url, "alt_text": t.PRIZE_NAME[key] + " won"})
            self.assertEqual(with_banner[1:], plain)
            check_blocks(with_banner)

    def test_the_banner_comes_first_then_the_winners_card(self):
        g = make_game("large", n=20)
        ticket = t.deal_ticket(g, HOST)
        picture, banner = AVATAR.format("U0000001", 512), "https://img.example.com/b.png"
        shapes = {1: ["image", "carousel"], 2: ["image", "header", "carousel"],
                  3: ["image", "header", "section", "carousel", "section", "divider"]}
        for key in t.PRIZE_KEYS:
            blocks = t.win_blocks(g, key, "Priya Sharma", ticket, banner, photo=picture)
            check_blocks(blocks)
            self.assertEqual(blocks[0]["image_url"], banner, "the banner first")
            self.assertEqual([b["type"] for b in blocks], shapes[t.PRIZE_TIER[key]], key)
            self.assertEqual(t.win_blocks(g, key, "Priya Sharma", ticket, photo=picture), blocks[1:],
                             "and without a banner the rest is just as it was")

    def test_the_winners_picture_is_on_one_card_with_the_words_not_a_block_of_its_own(self):
        g = make_game("large", n=20)
        ticket = t.deal_ticket(g, HOST)
        picture = AVATAR.format("U0000001", 512)
        for key in t.PRIZE_KEYS:
            blocks = t.win_blocks(g, key, "Priya Sharma", ticket, photo=picture)
            check_blocks(blocks)
            self.assertEqual([b for b in blocks if b["type"] == "image"], [], "a picture block is far bigger")
            cards = carousel_of(blocks)
            self.assertEqual(len(cards), 1, "one card: the winner who has just won, not every winner")
            card = cards[0]
            self.assertEqual(card["hero_image"], {"type": "image", "image_url": picture,
                                                  "alt_text": "Priya Sharma, winner of the " + t.PRIZE_NAME[key]})
            self.assertIn(t.PRIZE_NAME[key], card["title"]["text"])
            self.assertEqual(card["subtitle"]["text"], "Priya Sharma")
            if key in t.LINES:
                made_it = "  ·  ".join(str(n) for n in ticket[t.LINES[key]])
                self.assertIn(made_it, card["body"]["text"], "the numbers that made the line, on the card")
            self.assertEqual(card, t.winner_card(key, {"name": "Priya Sharma", "img": picture},
                                                 t.line_numbers(ticket, key)))

    def test_a_card_gives_the_numbers_of_a_line_only_when_it_is_asked_to(self):
        win = {"name": "Ana", "img": AVATAR.format("U0000001", 512)}
        self.assertEqual(t.winner_card("top", win)["body"]["text"], t.WINNER_BODY["top"] + " :clap::tada:",
                         "as the board's list has always shown it")
        self.assertIn("(3  ·  16  ·  23)", t.winner_card("top", win, [3, 16, 23])["body"]["text"])
        self.assertEqual(t.winner_card("full", win, [])["body"]["text"],
                         t.WINNER_BODY["full"] + " :clap::tada::fireworks:")

    def test_the_winners_picture_is_the_one_of_the_one_who_won(self):
        g = game_with_winners("carousel", ("early5", "top"))
        self.assertEqual(t.winner_picture(g, "top"), AVATAR.format("U0000002", 512))
        self.assertNotEqual(t.winner_picture(g, "top"), t.winner_picture(g, "early5"))
        self.assertTrue(t.winner_picture(game_with_winners("strip", ("top",)), "top"))
        for style in ("names", "none"):                            # no photos in these styles, so none is shown
            self.assertEqual(t.winner_picture(game_with_winners(style, ("top",)), "top"), "", style)
        self.assertEqual(t.winner_picture(game_with_winners("carousel", ("top",), photos=False), "top"), "",
                         "and none when there is no picture to be had")
        self.assertEqual(t.winner_picture(game_with_winners("carousel", ()), "top"), "")

    def test_names_cannot_break_the_announcement(self):
        g = make_game("small", n=5)
        blocks = t.win_blocks(g, "top", "A & B <everyone>", t.deal_ticket(g, HOST))
        self.assertIn("A &amp; B &lt;everyone&gt;", all_text(blocks))
        check_blocks(blocks)
        self.assertIn("Someone", all_text(t.win_blocks(g, "full", "", t.deal_ticket(g, HOST))))

    def test_the_banners_input_is_a_json_object_of_addresses(self):
        every = {"early5": "https://cdn.example.com/early-five.png", "top": "https://cdn.example.com/top-line.png",
                 "middle": "https://cdn.example.com/middle-line.png",
                 "bottom": "https://cdn.example.com/bottom-line.png",
                 "full": "https://cdn.example.com/full-house.png"}
        for given in (json.dumps(every), every, "  " + json.dumps(every, indent=2) + "\n"):
            self.assertEqual(t.read_banners(given), (every, []), repr(given)[:40])
        self.assertEqual(t.read_banners('{"full": "https://cdn.example.com/f.png"}'),
                         ({"full": "https://cdn.example.com/f.png"}, []), "name only the prizes that have one")
        for nothing in (None, "", "   ", "{}", {}):
            self.assertEqual(t.read_banners(nothing), ({}, []), repr(nothing))

    def test_a_prize_can_be_named_the_way_prizes_are(self):
        url = "https://cdn.example.com/a.png"
        for name, key in (("five", "early5"), ("Early Five", "early5"), ("early_five", "early5"), ("house", "full"),
                          ("Full-House", "full"), ("topline", "top"), ("Middle Line", "middle"),
                          ("bottomrow", "bottom")):
            self.assertEqual(t.read_banners({name: url}), ({key: url}, []), name)

    def test_lines_gives_all_three_lines_one_picture_unless_one_is_named(self):
        a, b = "https://cdn.example.com/lines.png", "https://cdn.example.com/middle.png"
        self.assertEqual(t.read_banners({"lines": a})[0], {"top": a, "middle": a, "bottom": a})
        for order in ({"lines": a, "middle": b}, {"middle": b, "lines": a}):
            self.assertEqual(t.read_banners(order)[0], {"top": a, "middle": b, "bottom": a}, order)

    def test_a_bad_address_or_name_is_left_out_and_said(self):
        good = "https://cdn.example.com/full.png"
        for bad in ("http://cdn.example.com/a.png", "ftp://x/a.png", "javascript:alert(1)", "cdn.example.com/a.png",
                    "https://x.com/a b.png", "https://x.com/" + "a" * 3000, "", None, 5):
            found, problems = t.read_banners({"full": good, "top": bad})
            self.assertEqual(found, {"full": good}, repr(bad)[:40])
            self.assertEqual(len(problems), 1, bad)
            self.assertIn("'top'", problems[0])
        found, problems = t.read_banners({"full": good, "jackpot": good})
        self.assertEqual((found, len(problems)), ({"full": good}, 1))
        self.assertIn("'jackpot' is not a prize", problems[0])

    def test_a_banners_input_that_cannot_be_read_is_said(self):
        for bad in ("not json", "{'full': 'https://x.com/a.png'}", '{"full": "https://x.com/a.png",}', "[1, 2]", "5",
                    '"https://x.com/a.png"', 5, ["https://x.com/a.png"]):
            found, problems = t.read_banners(bad)
            self.assertEqual(found, {}, repr(bad))
            self.assertEqual(len(problems), 1, repr(bad))
            self.assertIn("banners could not be read", problems[0])

    def test_the_text_that_goes_with_it_is_the_plain_line(self):
        g = make_game("small", n=5)
        for key in t.PRIZE_KEYS:
            text = t.win_text(g, key, "Priya", t.deal_ticket(g, HOST))
            self.assertIn("Priya", text)
            self.assertNotIn("\n:", text)


class TestTidyingUp(unittest.TestCase):
    """What happens to the screen when a game is over."""

    def setUp(self):
        self.deleted, self.edited = [], []
        for name, new in (("slack_delete", lambda token, channel, ts: self.deleted.append(ts)),
                          ("slack_update", lambda token, channel, ts, text, blocks: self.edited.append(ts))):
            patcher = mock.patch.object(t, name, new)
            patcher.start()
            self.addCleanup(patcher.stop)

    def game(self, style):
        g = make_game("small", n=30, status=t.DONE, winners_style=style)
        g["wins"] = {"early5": {"uid": "U1", "name": "Sam", "ts": "1700000100.0", "ann": "A1"},
                     "top": {"uid": "U2", "name": "Ana", "ts": "1700000200.0", "ann": "A2", "nums": [1, 2, 3]},
                     "middle": {"uid": "U3", "name": "Jo", "ts": "1700000250.0"},
                     "full": {"uid": "U4", "name": "Kim", "ts": "1700000300.0", "ann": "A4"}}
        return g

    def test_where_the_board_lists_winners_every_announcement_is_deleted(self):
        for style in ("names", "carousel", "strip"):
            self.deleted.clear()
            t.tidy_up("x", self.game(style), {"warnings": []})
            self.assertEqual(sorted(self.deleted), ["A1", "A2", "A4"], style)
            self.assertEqual(self.edited, [], style)

    def test_with_no_winners_list_the_announcements_are_kept_without_their_pictures(self):
        t.tidy_up("x", self.game("none"), {"warnings": []})
        self.assertEqual(self.deleted, [])
        self.assertEqual(sorted(self.edited), ["A1", "A2", "A4"], "Full House's too: the game is over")

    def test_a_message_that_cannot_be_deleted_is_a_warning(self):
        with mock.patch.object(t, "slack_delete", lambda *args: "slack: ratelimited"):
            result = {"warnings": []}
            t.tidy_up("x", self.game("names"), result)
        self.assertEqual(len(result["warnings"]), 3)
        self.assertIn("could not clear the", result["warnings"][0])

    def test_a_message_that_is_gone_already_is_no_warning(self):
        with mock.patch.object(t, "slack_delete", lambda *args: "slack: message_not_found"):
            result = {"warnings": []}
            t.tidy_up("x", self.game("names"), result)
        self.assertEqual(result["warnings"], [], "the next number may have taken it down before")

    def test_the_final_board_lists_the_winners_whatever_was_shown_before(self):
        for style, shown in (("names", True), ("carousel", True), ("strip", True), ("none", None)):
            g = make_game("small", winners_style=style)
            g["winners_open"] = False
            t.finish_winners(g)
            self.assertEqual(g["winners_open"], shown if shown else False, style)

    def test_a_prize_nobody_won_is_not_won_not_open_once_the_game_is_over(self):
        g = make_game("small", n=30, winners_style="names", status=t.DONE)
        g["wins"] = {"top": {"uid": "U2", "name": "Ana", "ts": "1.0"}}
        text = all_text(t.winners_blocks(g))
        self.assertIn("_not won_", text)
        self.assertNotIn("_open_", text)
        live = make_game("small", n=3, winners_style="names", status=t.RUNNING)
        self.assertIn("_open_", all_text(t.winners_blocks(live)))
        photos = game_with_winners("carousel", ("top",))
        photos["status"] = t.DONE
        self.assertIn("*Not won:*", all_text(t.winners_blocks(photos)))
        photos["status"] = t.RUNNING
        self.assertIn("*Still to win:*", all_text(t.winners_blocks(photos)))

    def test_retiring_with_final_takes_full_house_down_too(self):
        g = self.game("none")
        result = {"warnings": []}
        t.retire_celebrations("x", g, 0.0, result)
        self.assertNotIn("A4", self.edited, "not by default")
        self.edited.clear()
        t.retire_celebrations("x", g, 0.0, result, final=True)
        self.assertIn("A4", self.edited)


class TestTakingTheCelebrationDown(unittest.TestCase):
    """What the next number does to the announcements of prizes won since the number before."""

    def setUp(self):
        self.edits, self.deleted = [], []

        def update(token, channel, ts, text, blocks):
            self.edits.append((ts, text, blocks))
            return None

        def delete(token, channel, ts):
            self.deleted.append(ts)
            return None
        for name, new in (("slack_update", update), ("slack_delete", delete)):
            patcher = mock.patch.object(t, name, new)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.g = make_game("small", n=20, winners_style="carousel")
        self.g["wins"] = {
            "middle": {"uid": "U0000001", "name": "Ana", "ts": "1700000050.000000", "ann": "A1", "nums": [4, 17, 27]},
            "early5": {"uid": "U0000002", "name": "Sam", "ts": "1700000100.000000", "ann": "A2"},
            "top": {"uid": "U0000003", "name": "Priya", "ts": "1700000200.000000", "ann": "A3", "nums": [3, 16, 23]},
            "bottom": {"uid": "U0000004", "name": "Jo", "ts": "1700000250.000000"},                  # never announced
            "full": {"uid": "U0000005", "name": "Kim", "ts": "1700000300.000000", "ann": "A5"},
        }

    def retire(self, since, game=None):
        result = {"warnings": []}
        t.retire_celebrations("xoxb", game or self.g, since, result)
        return sorted(self.deleted), result["warnings"]

    def with_no_winners_list(self):
        """The same game with no winners list on its board: its announcements are all there is of who won."""
        game = make_game("small", n=20, winners_style="none")
        game["wins"] = self.g["wins"]
        return game

    def test_only_what_was_won_since_the_number_before_is_taken_down(self):
        self.assertEqual(self.retire(1700000150.0)[0], ["A3"], "only the top line came after the last number")

    def test_every_earlier_one_goes_when_none_has_been_taken_down_yet(self):
        self.assertEqual(self.retire(0.0)[0], ["A1", "A2", "A3"])

    def test_full_house_is_never_taken_down(self):
        self.assertNotIn("A5", self.retire(0.0)[0], "it ends the game: its celebration stays up")

    def test_a_prize_that_was_never_announced_has_nothing_to_take_down(self):
        self.assertEqual(self.retire(0.0)[0].count("A4"), 0)
        self.assertEqual(len(self.deleted), 3)

    def test_nothing_is_won_after_the_last_number_nothing_is_touched(self):
        self.assertEqual(self.retire(1700000400.0), ([], []))
        self.assertEqual(self.edits, [])

    def test_where_the_board_lists_the_winners_the_announcement_goes_altogether(self):
        for style in ("names", "carousel", "strip"):
            self.deleted.clear()
            game = make_game("small", n=20, winners_style=style)
            game["wins"] = self.g["wins"]
            self.assertEqual(self.retire(1700000150.0, game)[0], ["A3"], style)
            self.assertEqual(self.edits, [], "deleted, not drawn again: nothing of the celebration is left")

    def test_with_no_winners_list_what_is_left_is_the_plain_line_with_its_numbers(self):
        self.assertEqual(self.retire(1700000150.0, self.with_no_winners_list())[0], [],
                         "nothing is deleted: the announcement is the record")
        (ts, text, blocks), = self.edits
        self.assertEqual(ts, "A3")
        self.assertEqual([b["type"] for b in blocks], ["section"], "no header, no banner, no card")
        self.assertIn("3  ·  16  ·  23", all_text(blocks), "the numbers that made the line, kept with the win")
        self.assertIn("Priya", text)
        self.assertEqual(blocks, [t._section(t.win_text(self.g, "top", "Priya", None, [3, 16, 23]))])

    def test_a_failed_delete_is_a_warning_not_the_end(self):
        with mock.patch.object(t, "slack_delete", lambda *args: "slack: ratelimited"):
            result = {"warnings": []}
            t.retire_celebrations("xoxb", self.g, 0.0, result)
        self.assertEqual(len(result["warnings"]), 3)
        self.assertIn("could not clear the", result["warnings"][0])

    def test_one_that_is_gone_already_is_no_warning(self):
        with mock.patch.object(t, "slack_delete", lambda *args: "slack: message_not_found"):
            result = {"warnings": []}
            t.retire_celebrations("xoxb", self.g, 0.0, result)
        self.assertEqual(result["warnings"], [])

    def test_a_failed_edit_is_a_warning_not_the_end(self):
        with mock.patch.object(t, "slack_update", lambda *args: "slack: message_not_found"):
            result = {"warnings": []}
            t.retire_celebrations("xoxb", self.with_no_winners_list(), 0.0, result)
        self.assertEqual(len(result["warnings"]), 3)
        self.assertIn("could not take the", result["warnings"][0])

# --------------------------------------------------------------------------
# The payload
# --------------------------------------------------------------------------

def slack_press(**changes):
    """An interaction as the click trigger shows it: the join button pressed after Small was chosen on the dropdown,
    while the button itself was drawn for Large (names and ids made up)."""
    state = dropdown_state(size_menu_of(t.setup_blocks(make_game("small"))), "small")
    payload = {
        "type": "block_actions",
        "user": {"id": "U0HOST001", "username": "host", "name": "host", "team_id": "T0TEST001"},
        "api_app_id": "A0TEST001",
        "container": {"type": "message", "message_ts": "1794511081.000100", "channel_id": "C0GAME001",
                      "is_ephemeral": True},
        "trigger_id": "1.2.abc",
        "team": {"id": "T0TEST001", "domain": "example"},
        "channel": {"id": "C0GAME001", "name": "games"},
        "state": {"values": state},
        "response_url": "https://hooks.slack.com/actions/T0TEST001/1/abc",
        "actions": [{"type": "button", "block_id": "yR2vV", "action_id": "tambola_click_set_all",
                     "text": {"type": "plain_text", "text": "Everyone in this channel", "emoji": True},
                     "value": "tb|set|tb_C0GAME001_1794511079201789|" + json.dumps(
                         {"m": "all", "w": "Tambola", "f": ["early5,top,middle,bottom,full", "channel", 10, 60,
                                                             "large", 10]}, separators=(",", ":")),
                     "style": "primary", "action_ts": "1794511091.002829"}],
    }
    payload.update(changes)
    return payload


class TestPayload(unittest.TestCase):
    def test_every_field_is_read_out_of_the_payload(self):
        for given in (json.dumps({"block_actions:button": slack_press()}), json.dumps(slack_press()),
                      {"block_actions:button": slack_press()}, slack_press()):
            merged, problem = t.with_payload({"payload": given, "slack_bot_token": "x"})
            self.assertEqual(problem, "")
            self.assertEqual((merged["user_id"], merged["channel"], merged["source_ts"]),
                             ("U0HOST001", "C0GAME001", "1794511081.000100"))
            self.assertEqual((merged["action_id"], merged["action_ts"], merged["response_url"]),
                             ("tambola_click_set_all", "1794511091.002829",
                              "https://hooks.slack.com/actions/T0TEST001/1/abc"))
            self.assertTrue(merged["action_value"].startswith("tb|set|tb_C0GAME001_"))
            self.assertEqual(merged["slack_bot_token"], "x")
            self.assertEqual(t.dropdown_choice(merged["state"], "size"), "small")

    def test_what_was_mapped_by_hand_is_kept(self):
        merged, _ = t.with_payload({"payload": slack_press(), "user_id": "UMAPPED01", "channel": "CMAPPED01",
                                    "action_ts": "1.5"})
        self.assertEqual((merged["user_id"], merged["channel"], merged["action_ts"]), ("UMAPPED01", "CMAPPED01", "1.5"))
        self.assertEqual(merged["action_id"], "tambola_click_set_all")             # what was blank is filled

    def test_a_menus_picks_come_out_of_the_payload(self):
        press = slack_press(actions=[{"type": "multi_users_select", "action_id": "tambola_click_pick_tb_C_1",
                                      "selected_users": ["U0AAAAAAA", "U0BBBBBBB"], "action_ts": "1.5"}])
        merged, _ = t.with_payload({"payload": press})
        self.assertEqual(t.ids_in(merged["selected_users"]), ["U0AAAAAAA", "U0BBBBBBB"])
        self.assertEqual(t.parse_value("", merged["action_id"])["kind"], "pick")

    def test_no_payload_changes_nothing(self):
        given = {"user_id": "U1", "channel": "C1", "action_value": "tb|next|g|"}
        for empty in (None, "", "   ", {}):
            merged, problem = t.with_payload(dict(given, payload=empty))
            self.assertEqual((merged, problem), (dict(given, payload=empty), ""))

    def test_a_payload_that_cannot_be_read_is_reported(self):
        for bad in ("garbage", "[1, 2]", 5, [1], '"text"'):
            out = t.main({"payload": bad, "slack_bot_token": "x", "workato_api_token": "y"})
            self.assertFalse(out["ok"], bad)
            self.assertIn("payload could not be read", out["error"], bad)
            self.assertEqual(out["mode"], "click")

    def test_the_dropdowns_live_choice(self):
        small = dropdown_state(size_menu_of(t.setup_blocks(make_game("large"))), "small")
        self.assertEqual(t.dropdown_choice({"values": small}, "size"), "small")
        self.assertEqual(t.dropdown_choice(json.dumps({"values": small}), "size"), "small")
        # found by its action id, whatever block it is in, among other things Slack reports
        crowded = dict(small, XXXXX={"another_menu": {"selected_option": {"value": "{}"}}},
                       YYYYY={t.SIZE_ACTION: small["SL9MT"][t.SIZE_ACTION]})
        self.assertEqual(t.dropdown_choice({"values": crowded}, "size"), "small")
        huge = {"B": {t.SIZE_ACTION: {"selected_option": {"value": json.dumps({"s": "huge", "m": "1"})}}}}
        for nothing in (None, "", "garbage", {}, [], 5, {"values": None}, {"values": {}}, {"values": {"B": None}},
                        {"values": huge}, {"values": {"B": {t.SIZE_ACTION: {}}}},
                        {"values": {"B": {t.SIZE_ACTION: {"selected_option": None}}}}):
            self.assertIsNone(t.dropdown_choice(nothing, "size"), repr(nothing))

    def test_a_press_by_payload_is_answered_like_one_by_fields(self):
        """The same press both ways, with nothing else different, must say the same."""
        outs = []
        for via in ("fields", "payload"):
            world = World()
            world.via = via
            with mock.patch.object(t, "_send_json", world.send), mock.patch.object(t, "_now", lambda: world.clock), \
                    mock.patch.object(t, "_sleep", lambda seconds: None):
                world.members["C0GAME"] = [HOST, "U0000001"]
                world.names.update({HOST: "Priya Sharma", "U0000001": "Sam"})
                world.type_word(HOST, "C0GAME", "itambola")
                card = world.last_note(HOST)["blocks"]
                out = world.select(HOST, size_menu_of(card), "small", "C0GAME")
                outs.append((out["ok"], out["mode"], out["controls"], chosen_size(world.last_note(HOST)["blocks"]),
                             world.last_note(HOST)["how"]))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], (True, "size", "in place", "small", "in place"))


# --------------------------------------------------------------------------
# Whole games
# --------------------------------------------------------------------------

class TestGames(unittest.TestCase):
    CHANNEL = "C0GAME"

    KEY_OF = {name: key for key, name in t.PRIZE_NAME.items()}
    via = "fields"

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
        self.world.via = self.via
        self.world_patches = [mock.patch.object(t, "_send_json", self.world.send),
                              mock.patch.object(t, "_now", lambda: self.world.clock)]
        for patch in self.world_patches:
            patch.start()
        self.addCleanup(lambda: [p.stop() for p in self.world_patches])

    # -- helpers
    def ticket_blocks_of(self, user):
        """The ticket a person plays: their private message, or for the organizer (who is sent none) the card opened
        in their controls."""
        return self.world.host_card(user) if user == HOST else self.world.ticket_of(user)[2]

    def people(self, count):
        ids = [HOST] + ["U%07d" % i for i in range(1, count)]
        self.world.members[self.CHANNEL] = ids
        self.world.names.update({u: "Player {:03d}".format(i) for i, u in enumerate(ids)})
        self.world.names[HOST] = "Priya Sharma"
        return ids

    def open_game(self, ids, choose=None, test=False, board=None, winners=None, **extra):
        """Type the word, choose a size (`choose`) and a board style (`board`) on the dropdowns (none leaves it where
        the card opened), choose 'Everyone in this channel', press Start. The result of Start. `extra` are the recipe's
        other inputs."""
        w = self.world
        if test:
            extra["testing"] = "yes"
        out = w.type_word(HOST, self.CHANNEL, "itambola", **extra)
        self.assertTrue(out["ok"], out)
        setup = w.last_note(HOST)
        self.opened_on, self.opened_board = chosen_size(setup["blocks"]), chosen_board(setup["blocks"])
        self.opened_winners = chosen_winners(setup["blocks"])
        if winners:
            out = w.select(HOST, winners_menu_of(setup["blocks"]), winners, self.CHANNEL)
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["mode"], "winners")
            setup = w.last_note(HOST)
            self.assertEqual(setup["how"], "in place")
            self.assertEqual(chosen_winners(setup["blocks"]), winners)
        if board:
            out = w.select(HOST, board_menu_of(setup["blocks"]), board, self.CHANNEL)
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["mode"], "board")
            setup = w.last_note(HOST)
            self.assertEqual(setup["how"], "in place")
            self.assertEqual(chosen_board(setup["blocks"]), board)
        if choose:
            out = w.select(HOST, size_menu_of(setup["blocks"]), choose, self.CHANNEL)
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["mode"], "size")
            setup = w.last_note(HOST)
            self.assertEqual(setup["how"], "in place", "the card is drawn again where it was")
            self.assertEqual(chosen_size(setup["blocks"]), choose)
            if board:
                self.assertEqual(chosen_board(setup["blocks"]), board, "choosing a size must not undo the style")
        self.setup_blocks = setup["blocks"]
        out = w.click(HOST, button_named(setup["blocks"], "set_all"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        self.lobby_text = all_text(w.channel_messages(self.CHANNEL)[-1]["blocks"])
        out = w.click(HOST, button_named(w.panel(HOST), "start"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["players"], out["dm_sent"]), (len(ids), len(ids) - 1), "the organizer's is not sent")
        self.board_ts = out["message_ts"]
        self.game_id = out["game_id"]
        return out

    def board(self):
        return self.world.messages[(self.CHANNEL, self.board_ts)]["blocks"]

    def announcements(self):
        """Every prize announcement posted in the channel, as it was posted, whether or not it is still there."""
        return [p for p in self.world.posts if p["channel"] == self.CHANNEL and self.is_announcement(p)]

    def standing_announcements(self):
        """The prize announcements still on the screen."""
        return [m for m in self.world.channel_messages(self.CHANNEL) if self.is_announcement(m)]

    @staticmethod
    def is_announcement(message):
        """A prize announcement, known by the plain line it is posted with (its notification text): its words may be on
        a card, which the board's winners list uses as well."""
        return bool(re.search(r"goes to|Full House!", message.get("text") or ""))

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

    # -- a small game, from the dropdown to the Full House
    def test_a_small_game_from_the_dropdown_to_full_house(self):
        ids = self.people(6)
        self.open_game(ids, "small")
        self.assertEqual(self.opened_on, "large")
        self.assertEqual(chosen_size(self.setup_blocks), "small")
        self.assertIn("9 numbers in 3 rows", self.lobby_text)
        self.assertIn("(small game: numbers 1 to 30)", self.lobby_text)

        rows = self.world.rows_of(t.PLAYER_ROW)
        self.assertEqual(len(rows), 6)
        for row in rows:
            ticket = t.player_from_row(row)["ticket"]
            self.assertEqual([len(r) for r in ticket], [3, 3, 3])
            self.assertTrue(all(1 <= n <= 30 for n in t.ticket_numbers(ticket)))
        for user in ids:
            self.assertEqual(len(ticket_numbers_on(self.ticket_blocks_of(user))), 9)
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
        self.assertEqual(len(self.announcements()), 5, "each prize is announced once")
        self.assertEqual(self.standing_announcements(), [], "and the screen is cleared when the game ends")
        self.assertTrue([b for b in self.board() if b.get("fields")], "the winners stay, on the board")

    def test_a_small_game_ends_when_the_thirty_numbers_are_out(self):
        ids = self.people(2)
        self.open_game(ids, "small")
        for call in range(1, 31):
            out = self.next_number()                   # nobody marks anything, so nobody can win
        self.assertTrue(out["finished"], out)
        self.assertEqual(out["called"], 30)
        self.assertIn("All 30 numbers have been called", all_text(self.board()))
        self.assertEqual(self.world.rows_of(t.GAME_ROW)[0]["status"], t.DONE)

    def test_a_medium_game_deals_four_numbers_a_row(self):
        ids = self.people(5)
        self.open_game(ids, "medium")
        for user in ids:
            blocks = self.ticket_blocks_of(user)
            self.assertEqual(row_widths(blocks), [6, 6, 6], "a printed row has a cell for each of six columns")
            self.assertTrue(all(1 <= n <= 60 for n in ticket_numbers_on(blocks)))
            self.assertEqual(len(ticket_numbers_on(blocks)), 12)
        calls, won = self.play_out(ids, 60)
        self.assertLessEqual(calls, 60)
        self.assertEqual(sorted(won), sorted(t.PRIZE_KEYS))
        self.assertEqual(len(self.announcements()), 5)

    def test_the_recipes_size_input_is_where_the_dropdown_starts(self):
        ids = self.people(2)
        self.open_game(ids, size="small")                           # the recipe's input; nothing chosen on the card
        self.assertEqual(self.opened_on, "small")
        self.assertIn("(small game", self.lobby_text)
        self.use_world()                 # typing the word again would bring back the first game's controls
        ids = self.people(2)
        self.open_game(ids, "large", size="small")                  # the organizer's choice is what counts
        self.assertEqual((self.opened_on, chosen_size(self.setup_blocks)), ("small", "large"))
        self.assertNotIn("small game", self.lobby_text)
        self.assertIn("15 numbers in 3 rows", self.lobby_text)

    # -- the dropdown itself
    def test_choosing_a_size_redraws_the_card_and_creates_nothing(self):
        w, ids = self.world, self.people(3)
        self.assertTrue(w.type_word(HOST, self.CHANNEL, "itambola")["ok"])
        card = w.last_note(HOST)
        self.assertEqual(chosen_size(card["blocks"]), "large")
        before = len(w.events(HOST))
        for size in ("medium", "small", "medium", "large"):
            out = w.select(HOST, size_menu_of(w.last_note(HOST)["blocks"]), size, self.CHANNEL)
            self.assertTrue(out["ok"], out)
            self.assertEqual((out["mode"], out["controls"]), ("size", "in place"))
            blocks = w.last_note(HOST)["blocks"]
            self.assertEqual(chosen_size(blocks), size)
            for button in buttons_of(blocks):                       # every way of joining now carries it
                parsed = t.parse_value(button["value"])
                self.assertEqual(t.cfg_from(json.loads(parsed["arg"])["f"])["size"], size)
        self.assertEqual(len(w.events(HOST)), before + 4)
        self.assertEqual(w.rows, {}, "nothing is saved until the organizer chooses how people join")
        self.assertEqual(w.channel_messages(self.CHANNEL), [], "nothing is posted either")
        self.assertEqual(len(w.members[self.CHANNEL]) if self.CHANNEL in w.members else 0, len(ids))

    def test_the_game_is_made_with_the_size_that_was_chosen(self):
        for size in t.SIZES:
            self.use_world()
            ids = self.people(2)
            self.open_game(ids, size)
            game = t.game_from_row(self.world.rows_of(t.GAME_ROW)[0])
            self.assertEqual((game["cfg"]["size"], t.numbers_of(game)), (size, t.SIZES[size]["numbers"]))

    def test_without_a_response_url_a_new_card_is_sent(self):
        w = self.world
        w.type_word(HOST, self.CHANNEL, "itambola")
        out = w.select(HOST, size_menu_of(w.last_note(HOST)["blocks"]), "small", self.CHANNEL, response=False)
        self.assertTrue(out["ok"], out)
        self.assertEqual(w.last_note(HOST)["how"], "note")
        self.assertEqual(chosen_size(w.last_note(HOST)["blocks"]), "small")
        self.assertTrue(any("response_url" in warning for warning in out["warnings"]), out["warnings"])

    def test_an_unmapped_or_unreadable_choice_is_reported_not_guessed(self):
        w = self.world
        w.type_word(HOST, self.CHANNEL, "itambola")
        base = {"action_id": t.SIZE_ACTION, "user_id": HOST, "channel": self.CHANNEL, "action_ts": w.tick(),
                "slack_bot_token": "xoxb-test", "workato_api_token": "wk-test", "response_url": HOOK + HOST}
        out = t.main(dict(base))
        self.assertFalse(out["ok"])
        self.assertIn("did not arrive", out["error"])
        self.assertIn("payload", out["error"])
        for junk in ("garbage", '{"value": "{}"}', json.dumps({"value": json.dumps({"s": "huge", "m": "1"})}),
                     json.dumps({"value": json.dumps({"s": "small"})})):
            out = t.main(dict(base, selected_option=junk))
            self.assertFalse(out["ok"], junk)
            self.assertIn("not one of the choices", out["error"], junk)
        self.assertEqual(chosen_size(w.last_note(HOST)["blocks"]), "large", "the card was left as it was")

    def test_the_lobby_follows_the_dropdown_whatever_size_the_button_was_drawn_with(self):
        """What happened in Slack: the dropdown said Small, but its own click never redrew the card, so the button was
        still the one drawn for Large. The press reports what the dropdown shows, and that is the size."""
        for test in (False, True):
            for size, spec in t.SIZES.items():
                with self.subTest(size=size, test=test):
                    self.use_world()
                    ids = self.people(3)
                    w = self.world
                    w.type_word(HOST, self.CHANNEL, "itambola", **({"testing": "yes"} if test else {}))
                    card = w.last_note(HOST)["blocks"]
                    self.assertEqual(chosen_size(card), "large", "the card was drawn for large")
                    state = dropdown_state(size_menu_of(card), size)
                    out = w.click(HOST, button_named(card, "set_all"), self.CHANNEL, state=state)
                    self.assertTrue(out["ok"], out)
                    lobby = all_text(w.channel_messages(self.CHANNEL)[-1]["blocks"])
                    self.assertIn("{} numbers in 3 rows".format(3 * spec["row"]), lobby)
                    self.assertIn("from 1 to {}".format(spec["numbers"]), lobby)
                    if size == "large":
                        self.assertNotIn(" game: numbers", lobby)
                    else:
                        self.assertIn("({} game: numbers 1 to {})".format(size, spec["numbers"]), lobby)
                        self.assertNotIn("15 numbers", lobby)
                        self.assertNotIn("1 to 90", lobby)
                    out = w.click(HOST, button_named(w.panel(HOST), "start"), self.CHANNEL)
                    self.assertTrue(out["ok"], out)
                    for user in ids:
                        self.assertEqual(len(ticket_numbers_on(self.ticket_blocks_of(user))), 3 * spec["row"])
                    if not test:
                        game = t.game_from_row(w.rows_of(t.GAME_ROW)[0])
                        self.assertEqual((game["cfg"]["size"], t.numbers_of(game)), (size, spec["numbers"]))

    def test_a_press_with_nothing_on_the_dropdown_keeps_the_size_the_button_has(self):
        w = self.world
        self.people(2)
        w.type_word(HOST, self.CHANNEL, "itambola", size="medium")
        card = w.last_note(HOST)["blocks"]
        for state in (None, {}, {"SL9MT": {"some_other_menu": {"selected_option": {"value": "x"}}}},
                      {"SL9MT": {t.SIZE_ACTION: {"type": "static_select", "selected_option": None}}},
                      {"SL9MT": {t.SIZE_ACTION: {"selected_option": {"value": "not json"}}}}):
            self.use_world()
            self.people(2)
            w = self.world
            w.type_word(HOST, self.CHANNEL, "itambola", size="medium")
            out = w.click(HOST, button_named(w.last_note(HOST)["blocks"], "set_all"), self.CHANNEL, state=state)
            self.assertTrue(out["ok"], out)
            self.assertIn("(medium game", all_text(w.channel_messages(self.CHANNEL)[-1]["blocks"]), repr(state))

    def test_a_prize_is_announced_once_even_when_the_win_is_asked_for_again(self):
        """The production sequence: the winning number is tapped again before the table shows the first win, so the
        second press finds the prize open, claims it, and used to announce it a second time."""
        def early_five():
            return [m for m in self.announcements() if "Early Five" in all_text(m["blocks"])]
        ids = self.people(1)
        self.open_game(ids, "small")
        number = 0
        for _ in range(30):
            number = self.next_number()["number"]
            result = self.world.tap(HOST, number)
            if result and "Early Five" in result["prize"]:
                break
        else:
            self.fail("Early Five was never won")
        self.assertEqual(len(early_five()), 1)
        heard = len(self.announcements())
        real, reads = t.Table.wins, {"n": 0}

        def stale(table, game_id, channel):
            reads["n"] += 1
            return [] if reads["n"] == 1 else real(table, game_id, channel)       # the first read has not seen the win
        with mock.patch.object(t.Table, "wins", stale):
            again = self.world.tap(HOST, number)
        self.assertTrue(again["ok"], again)
        self.assertEqual(again["prize"], "", "it is theirs already: not a win to announce again")
        self.assertEqual(len(early_five()), 1, "the channel heard of it once")
        self.assertEqual(len(self.announcements()), heard)

    # -- winners on the board, and the celebration of a win
    def play_until(self, ids, prize_name, limit=30):
        """Call numbers with everybody tapping until `prize_name` is won (a name, "Early Five"), and stop there."""
        for _ in range(limit):
            out = self.next_number()
            for user in ids:
                result = self.world.tap(user, out["number"])
                if result and prize_name in result["prize"]:
                    return user
        self.fail("{} was never won".format(prize_name))

    def users_lookups(self):
        return len([c for c in self.world.calls if "users.info" in c[1]])

    def announcement_of(self, key):
        """A prize's announcement as it stands on the screen now."""
        return self.prize_messages(standing=True)[key]["blocks"]

    def winners_label(self):
        """The text on the organizer's Show / Hide winners button, "" if there is none."""
        found = [b["text"]["text"] for b in buttons_of(self.world.panel(HOST)) if b["action_id"] == t.WINNERS_BUTTON]
        return found[0] if found else ""

    def press_winners_button(self):
        out = self.world.click(HOST, button_named(self.world.panel(HOST), "showwinners"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        return out

    def test_a_win_is_announced_with_the_banner_then_the_winners_card_and_the_next_number_clears_it(self):
        banners = {"banners": json.dumps({"early5": "https://cdn.example.com/early.png",
                                          "top": "https://cdn.example.com/top.png",
                                          "full": "https://cdn.example.com/full.png"})}
        for test in (False, True):
            with self.subTest(test=test):
                self.use_world()
                self.world.settings = dict(banners)
                ids = self.people(4)
                self.open_game(ids, "small", winners="carousel", test=test)
                self.assertEqual(self.photo_blocks(self.board()), [], "the board does not list winners until asked")

                winner = self.play_until(ids, "Early Five")
                early = self.announcement_of("early5")
                self.assertEqual([b["type"] for b in early], ["image", "carousel"], "banner, then the winner's card")
                self.assertEqual(early[0]["image_url"], "https://cdn.example.com/early.png")
                cards = carousel_of(early)
                self.assertEqual(len(cards), 1, "only the one who has just won: not the board's list of winners")
                self.assertEqual(cards[0]["hero_image"]["image_url"], AVATAR.format(winner, 512), "their own picture")
                self.assertIn("Early Five", cards[0]["title"]["text"])
                self.assertEqual([b for b in early if b["type"] == "image" and "avatars" in b["image_url"]], [],
                                 "and no picture block of its own: that is far bigger than the words it goes with")

                early_ts = self.prize_messages()["early5"]["ts"]
                self.next_number()                                     # the next number clears the celebration
                self.assertNotIn("early5", self.prize_messages(standing=True))
                self.assertNotIn((self.CHANNEL, early_ts), self.world.messages)
                self.assertIn((self.CHANNEL, early_ts), self.world.deleted)

                top_winner = self.play_until(ids, "Top Line")
                top = self.announcement_of("top")
                self.assertEqual([b["type"] for b in top], ["image", "header", "carousel"])
                self.assertEqual([c["hero_image"]["image_url"] for c in carousel_of(top)],
                                 [AVATAR.format(top_winner, 512)], "only the current winner's")
                self.assertNotIn("early5", self.prize_messages(standing=True), "and the first stays gone")
                self.next_number()
                self.assertNotIn("top", self.prize_messages(standing=True))

                calls, won = self.play_out(ids, 30)
                heard = self.prize_messages()                # as they were posted
                for key, message in heard.items():           # never edited: each is deleted when its time comes
                    self.assertEqual(self.world.updated.count((self.CHANNEL, message["ts"])), 0, key)
                full = heard["full"]["blocks"]
                self.assertEqual([b["type"] for b in full],
                                 ["image", "header", "section", "carousel", "section", "divider"])
                self.assertEqual(full[0]["image_url"], "https://cdn.example.com/full.png")
                self.assertTrue(carousel_of(full)[0]["hero_image"]["image_url"].startswith(
                    "https://avatars.example.com/"))
                self.assertEqual(len(self.announcements()), 5)
                self.assertEqual(self.standing_announcements(), [], "and when the game ends they are all cleared away")

    def test_without_a_banner_the_winners_card_is_the_whole_announcement(self):
        ids = self.people(3)
        self.open_game(ids, "small", winners="strip")
        winner = self.play_until(ids, "Early Five")
        blocks = self.announcement_of("early5")
        self.assertEqual([b["type"] for b in blocks], ["carousel"])
        self.assertEqual(carousel_of(blocks)[0]["hero_image"]["image_url"], AVATAR.format(winner, 512))
        self.next_number()
        self.assertNotIn("early5", self.prize_messages(standing=True), "and the next number clears it")

    def test_the_names_and_none_styles_have_no_photo_to_open_with(self):
        for style in ("names", "none"):
            self.use_world()
            ids = self.people(3)
            self.open_game(ids, "small", winners=style)
            self.play_until(ids, "Early Five")
            self.assertEqual([b["type"] for b in self.announcement_of("early5")], ["section"], style)

    def test_a_winners_picture_is_looked_up_once_and_kept_with_the_win(self):
        ids = self.people(3)
        self.open_game(ids, "small", winners="carousel")
        winner = self.play_until(ids, "Early Five")
        rows = [r for r in self.world.rows_of(t.WIN_ROW) if r["grant_type"] == "early5"]
        kept = json.loads(rows[0]["content"])
        self.assertEqual(kept["img"], AVATAR.format(winner, 512))
        self.assertTrue(kept["ann"], "where the announcement is, so the next number can take its photo down")
        self.assertEqual(kept["ann"], self.prize_messages()["early5"]["ts"])
        self.assertEqual(carousel_of(self.announcement_of("early5"))[0]["hero_image"]["image_url"],
                         AVATAR.format(winner, 512))
        before = self.users_lookups()
        for _ in range(3):
            self.next_number()
        self.assertEqual(self.users_lookups(), before, "redrawing the board costs no lookups")
        self.assertNotIn("early5", self.prize_messages(standing=True), "cleared at the next number")

    def test_show_and_hide_winners_put_the_list_on_the_board_in_the_chosen_style(self):
        for style in ("carousel", "strip"):
            for test in (False, True):
                with self.subTest(style=style, test=test):
                    self.use_world()
                    ids = self.people(3)
                    self.open_game(ids, "small", winners=style, test=test)
                    self.assertEqual(self.winners_label(), "", "no button before there is a winner")
                    self.play_until(ids, "Early Five")
                    self.next_number()                                           # the controls are drawn again
                    self.assertIn("Show winners", self.winners_label())
                    self.assertEqual(self.photo_blocks(self.board()), [], "hidden to begin with")
                    self.press_winners_button()                                  # Show winners
                    shown = self.photo_blocks(self.board())
                    self.assertEqual(len(shown), 1, style)
                    self.assertIn("Still to win", all_text(self.board()))
                    self.assertEqual(self.winners_label(), "Hide winners")
                    for _ in range(2):                                           # it stays while numbers are called
                        self.next_number()
                        self.assertEqual(len(self.photo_blocks(self.board())), 1)
                    self.press_winners_button()                                  # Hide winners
                    self.assertEqual(self.photo_blocks(self.board()), [])
                    self.assertNotIn("Still to win", all_text(self.board()))
                    self.assertIn("Show winners", self.winners_label())
                    self.press_winners_button()
                    self.assertEqual(len(self.photo_blocks(self.board())), 1)

    def photo_blocks(self, blocks):
        return [b for b in blocks if b["type"] == "carousel" or (
            b["type"] == "context" and any(e["type"] == "image" for e in b["elements"]))]

    def test_there_is_no_winners_button_until_somebody_has_won(self):
        for style in ("names", "carousel", "strip"):
            for test in (False, True):
                with self.subTest(style=style, test=test):
                    self.use_world()
                    ids = self.people(3)
                    self.open_game(ids, "small", winners=style, test=test)
                    self.assertEqual(self.winners_label(), "", "the game starts without it")
                    self.assertNotIn("winners button", all_text(self.world.panel(HOST)), "and does not talk about it")
                    self.next_number()
                    self.assertEqual(self.winners_label(), "", "and goes on without it while nobody has won")
                    self.play_until(ids[1:], "Early Five")           # a player wins: the organizer's card stays shut
                    self.next_number()                    # the controls are drawn again: now there is something to show
                    self.assertEqual(self.winners_label(),
                                     "Hide winners" if style == "names" else "Show winners :trophy:")
                    self.assertIn("winners button", all_text(self.world.panel(HOST)), "and now the note mentions it")

    def test_the_names_list_is_there_from_the_start_and_can_be_hidden_once_there_is_a_winner(self):
        ids = self.people(2)
        self.open_game(ids, "small")
        self.assertTrue([b for b in self.board() if b.get("fields")], "the prizes are listed from the start")
        self.assertEqual(self.winners_label(), "", "but there is nothing to show or hide yet")
        self.play_until(ids, "Early Five")
        self.next_number()                                        # the controls are drawn again: now there is a winner
        self.assertEqual(self.winners_label(), "Hide winners")
        self.press_winners_button()
        self.assertFalse([b for b in self.board() if b.get("fields")])
        self.assertIn("Show winners", self.winners_label())
        self.press_winners_button()
        self.assertTrue([b for b in self.board() if b.get("fields")])
        self.assertEqual(self.winners_label(), "Hide winners")

    def test_the_organizer_winning_has_the_button_at_once(self):
        ids = self.people(1)
        self.open_game(ids, "small", winners="carousel")
        self.assertEqual(self.winners_label(), "")
        self.play_until(ids, "Early Five")                        # the organizer's own taps redraw their controls
        self.assertEqual(self.winners_label(), "Show winners :trophy:")

    def stale_winners_button(self):
        """A Show / Hide winners button as an older note had it: before the first win it was on every note, so one drawn
        then can still be pressed. It points at the game as the other buttons of its note do."""
        value = button_named(self.world.panel(HOST), "next")["value"]
        return {"action_id": t.WINNERS_BUTTON, "value": value.replace("|next|", "|winners|", 1)}

    def test_an_old_show_winners_button_with_nobody_to_show_warns_the_organizer_and_changes_nothing(self):
        for style in ("carousel", "strip"):
            for test in (False, True):
                with self.subTest(style=style, test=test):
                    self.use_world()
                    ids = self.people(2)
                    self.open_game(ids, "small", winners=style, test=test)
                    before = json.dumps(self.board(), sort_keys=True)
                    out = self.world.click(HOST, self.stale_winners_button(), self.CHANNEL)
                    self.assertEqual(out["skipped"], "nobody has won yet")
                    self.assertIn("Nobody has won a prize yet", all_text(self.world.panel(HOST)))
                    self.assertEqual(json.dumps(self.board(), sort_keys=True), before, "the board is untouched")
                    self.assertEqual(self.winners_label(), "", "and the note is still without the button")

    def test_an_old_hide_winners_button_still_hides_the_names_list(self):
        ids = self.people(2)
        self.open_game(ids, "small")                             # names: shown from the start, nobody has won
        out = self.world.click(HOST, self.stale_winners_button(), self.CHANNEL)
        self.assertEqual(out["skipped"], "")
        self.assertFalse([b for b in self.board() if b.get("fields")])

    def test_with_no_winners_style_there_is_no_button(self):
        ids = self.people(2)
        self.open_game(ids, "small", winners="none")
        self.assertEqual(self.winners_label(), "")
        self.assertNotIn("winners", all_text(self.world.panel(HOST)).lower(), "and nothing in the note talks about one")

    def test_only_the_host_can_show_or_hide_the_winners(self):
        ids = self.people(3)
        self.open_game(ids, "small", winners="carousel")
        self.play_until(ids, "Early Five")
        self.next_number()                                        # the controls now have the button
        button = button_named(self.world.panel(HOST), "showwinners")
        out = self.world.click(ids[1], button, self.CHANNEL)
        self.assertTrue(out["ok"])
        self.assertEqual(out["skipped"], "only the host can do that")
        self.assertEqual(self.photo_blocks(self.board()), [])

    def test_the_button_works_while_the_game_is_paused_and_is_remembered(self):
        ids = self.people(2)
        self.open_game(ids, "small", winners="carousel")
        self.play_until(ids, "Early Five")
        self.assertTrue(self.world.click(HOST, button_named(self.world.panel(HOST), "review"), self.CHANNEL)["ok"])
        self.assertIn("Show winners", self.winners_label())
        self.press_winners_button()                                             # while paused: it is only noted
        self.assertEqual(self.winners_label(), "Hide winners")
        self.assertIn("review", all_text(self.board()))
        self.assertTrue(self.world.click(HOST, button_named(self.world.panel(HOST), "resume"), self.CHANNEL)["ok"])
        self.assertEqual(len(self.photo_blocks(self.board())), 1, "the board is back with the winners asked for")

    def test_the_organizer_can_still_press_next_number_after_winners_are_shown(self):
        ids = self.people(2)
        self.open_game(ids, "small", winners="strip")
        self.play_until(ids[1:], "Early Five")
        self.next_number()                                        # the controls now have the button
        self.press_winners_button()
        out = self.next_number()
        self.assertTrue(out["ok"])
        self.assertEqual(len([b for b in buttons_of(self.world.panel(HOST))]), 5, "five buttons, no more")

    def test_one_tap_that_wins_two_prizes_puts_the_photo_on_the_last_announcement_only(self):
        w = self.world
        ids = self.people(2)
        self.open_game(ids, "small", winners="carousel")
        row = [r for r in w.rows_of(t.PLAYER_ROW) if r["group_id"] == ids[1]][0]
        player = t.player_from_row(row)
        top, others = player["ticket"][0], t.ticket_numbers(player["ticket"][1:])
        marks = set(top[:2]) | set(others[:2])                     # two of the top row and two more: four marked
        row["content"] = t.player_content(player["ticket"], marks, player["dm_channel"], player["dm_ts"])
        number = 0
        for _ in range(30):                                        # call numbers until the top row's last one is out
            number = self.next_number()["number"]
            if top[2] == number:
                break
        else:
            self.fail("the number was never called")
        for n in (set(top[:2]) | set(others[:2])) - set(t.called_list(t.game_from_row(w.rows_of(t.GAME_ROW)[0]))):
            self.skipTest("the seed did not call the marked numbers first")
        result = w.tap(ids[1], number)
        self.assertEqual(result["prize"], "Early Five, Top Line", result)
        heard = self.prize_messages()
        self.assertEqual([b["type"] for b in heard["early5"]["blocks"]], ["section"], "no photo on the first")
        self.assertEqual([b["type"] for b in heard["top"]["blocks"]], ["header", "carousel"],
                         "the photo, once, on the last announcement")
        self.assertEqual(carousel_of(heard["top"]["blocks"])[0]["hero_image"]["image_url"],
                         AVATAR.format(ids[1], 512))

    def test_every_winners_style_plays_through(self):
        for style in t.WINNERS_STYLES:
            for test in (False, True):
                with self.subTest(style=style, test=test):
                    self.use_world()
                    ids = self.people(3)
                    self.open_game(ids, "small", winners=style, test=test)
                    calls, won = self.play_out(ids, 30)
                    self.assertEqual(won[-1] if won else "", "full", won)
                    board, final = self.board(), self.prize_messages()["full"]["blocks"]
                    self.assertEqual(len(self.announcements()), 5, "announced whatever the board shows")
                    self.assertEqual(len(carousel_of(final)), 1 if style in t.PHOTO_STYLES else 0,
                                     "at most the one card of the winner: never the board's list of them all")
                    self.assertIn("Game over", all_text(board))
                    if style == "none":
                        self.assertFalse([b for b in board if b.get("fields")], "no list of prizes")
                        self.assertNotIn("Not won", all_text(board))
                        self.assertEqual(len(self.standing_announcements()), 5, "the lines are the only record")
                    else:
                        self.assertEqual(self.standing_announcements(), [], "cleared: the board's list is the record")
                    if style in t.PHOTO_STYLES:
                        self.assertEqual([b["type"] for b in final],
                                         ["header", "section", "carousel", "section", "divider"],
                                         "the winner's card between the cheers, while it was up")
                    if style == "carousel":
                        cards = carousel_of(board)
                        self.assertEqual(len(cards), 5, "the final board lists every winner as cards")
                        self.assertIn("Full House", cards[0]["title"]["text"], "newest on the left")
                        titles = " ".join(card["title"]["text"] for card in cards)
                        for name in t.PRIZE_NAME.values():
                            self.assertIn(name, titles)
                    elif style == "strip":
                        strip = self.photo_blocks(board)
                        self.assertEqual(len(strip), 1)
                        self.assertEqual(len(strip[0]["elements"]), 10)
                    elif style == "names":
                        fields = [b for b in board if b.get("fields")]
                        self.assertTrue(fields)
                        self.assertNotIn("open", all_text(fields), "every prize has its winner")

    def test_a_slack_without_carousels_still_announces_every_prize_without_the_card(self):
        """The winner's card is a carousel of one, so a workspace that refuses the carousel block loses the photo and
        nothing else: every prize is still announced, and the warnings say what was left out."""
        self.world.refuse_carousel = True
        ids = self.people(3)
        self.open_game(ids, "small", winners="carousel")
        warnings = []
        for _ in range(30):
            out = self.next_number()
            warnings += out["warnings"]
            results = [r for r in (self.world.tap(u, out["number"]) for u in ids) if r]
            for r in results:
                warnings += r["warnings"]
            if any(r["finished"] for r in results):
                break
        self.assertEqual(sorted(self.prize_messages()), sorted(t.PRIZE_KEYS), "every prize was announced")
        self.assertEqual(len(self.announcements()), 5, "each once")
        self.assertTrue([w for w in warnings if "announcement was refused" in w], "and the loss of the photo is said")
        for message in self.announcements():
            self.assertEqual(carousel_of(message["blocks"]), [], "the cards were left out")
        self.assertIn("Game over", all_text(self.board()))
        # the final board's winners list is a carousel too, and falls back to names
        self.assertTrue(any("pictures were refused" in w for w in warnings), warnings)
        self.assertTrue([b for b in self.board() if b.get("fields")], "names took its place")

    def test_a_photo_slack_will_not_take_goes_without_it_and_the_announcement_still_goes(self):
        ids = self.people(2)
        self.open_game(ids, "small", winners="carousel")
        real = t.slack_post

        def refuses_the_photo(token, channel, text, blocks, thread_ts=None):
            if any("avatars.example.com" in card.get("hero_image", {}).get("image_url", "")
                   for b in blocks if b.get("type") == "carousel" for card in b["elements"]):
                return "", "slack: invalid_blocks"
            return real(token, channel, text, blocks, thread_ts)
        with mock.patch.object(t, "slack_post", refuses_the_photo):
            self.play_until(ids, "Early Five")
        blocks = self.announcement_of("early5")
        self.assertEqual([b["type"] for b in blocks], ["section"], "it went, without the photo")
        for message in self.announcements():                       # and so did every other one that was refused
            self.assertEqual(carousel_of(message["blocks"]), [])

    def test_the_board_falls_back_to_names_when_shown_winners_are_refused(self):
        self.world.refuse_carousel = True
        ids = self.people(2)
        self.open_game(ids, "small", winners="carousel")
        self.play_until(ids, "Early Five")
        self.next_number()
        out = self.world.click(HOST, button_named(self.world.panel(HOST), "showwinners"), self.CHANNEL)
        self.assertTrue(out["ok"], out)
        self.assertTrue(any("pictures were refused" in w for w in out["warnings"]), out["warnings"])
        self.assertTrue([b for b in self.board() if b.get("fields")], "names took its place")

    def test_the_lobby_follows_the_winners_dropdown_whatever_the_buttons_were_drawn_with(self):
        w = self.world
        ids = self.people(3)
        w.type_word(HOST, self.CHANNEL, "itambola")
        card = w.last_note(HOST)["blocks"]
        state = dropdown_state(winners_menu_of(card), "carousel", "BLOCKW")
        out = w.click(HOST, button_named(card, "set_all"), self.CHANNEL, state=state)
        self.assertTrue(out["ok"], out)
        self.assertTrue(w.click(HOST, button_named(w.panel(HOST), "start"), self.CHANNEL)["ok"])
        game = t.game_from_row(w.rows_of(t.GAME_ROW)[0])
        self.assertEqual(game["cfg"]["winners"], "carousel")
        board = w.messages[(self.CHANNEL, game["board_ts"])]["blocks"]
        self.assertNotIn("Still to win", all_text(board), "the winners start hidden in a photo style")
        self.assertEqual(self.winners_label(), "", "and there is no button before the first winner")

    def prize_messages(self, standing=False):
        """The channel's announcements by the prize they are about: as posted, or (`standing`) as they are now."""
        found = {}
        for m in (self.standing_announcements() if standing else self.announcements()):
            text = m["text"]
            for key in t.PRIZE_KEYS:
                if (t.PRIZE_NAME[key] in text and "goes to" in text) or (key == "full" and "Full House!" in text):
                    found[key] = m
        return found

    def test_the_channel_hears_each_prize_bigger_than_the_one_before(self):
        ids = self.people(4)
        self.open_game(ids, "small")
        calls, won = self.play_out(ids, 30)
        self.assertEqual(sorted(won), sorted(t.PRIZE_KEYS))
        heard = self.prize_messages()
        self.assertEqual(sorted(heard), sorted(t.PRIZE_KEYS), "one announcement for each prize")
        shape = {key: [b["type"] for b in m["blocks"]] for key, m in heard.items()}
        self.assertEqual(shape["early5"], ["section"])
        for key in ("top", "middle", "bottom"):
            self.assertEqual(shape[key], ["header", "section"], key)
        self.assertEqual(shape["full"], ["header", "section", "divider"])
        counts = {key: emoji_count(m["blocks"]) for key, m in heard.items()}
        self.assertLess(counts["early5"], min(counts["top"], counts["middle"], counts["bottom"]))
        self.assertLess(max(counts["top"], counts["middle"], counts["bottom"]), counts["full"])

    def test_a_banner_is_up_when_the_prize_is_won_and_down_at_the_next_number(self):
        self.world.settings = {"banners": json.dumps(
            {k: "https://cdn.example.com/{}.png".format(k) for k in t.PRIZE_KEYS})}
        ids = self.people(4)
        self.open_game(ids, "small")
        self.play_until(ids, "Early Five")
        first = self.announcement_of("early5")
        self.assertEqual((first[0]["type"], first[0]["image_url"]), ("image", "https://cdn.example.com/early5.png"))
        self.next_number()
        self.assertNotIn("early5", self.prize_messages(standing=True), "down at the next number")
        calls, won = self.play_out(ids, 30)
        heard = self.prize_messages()
        self.assertEqual(sorted(heard), sorted(t.PRIZE_KEYS))
        self.assertEqual(heard["full"]["blocks"][0]["image_url"], "https://cdn.example.com/full.png",
                         "Full House went up with its banner")
        self.assertEqual(len(self.announcements()), 5)
        self.assertEqual(self.standing_announcements(), [], "and nothing of any banner is left when the game is over")

    def test_a_banner_slack_cannot_load_never_costs_the_announcement(self):
        self.world.settings = {"banners": json.dumps({"early5": "https://bad.example.com/early.png",
                                                      "full": "https://bad.example.com/full.png"})}
        ids = self.people(4)
        self.open_game(ids, "small")
        warnings = []
        for call in range(1, 31):
            out = self.next_number()
            if out["finished"]:
                break
            done = False
            for user in ids:
                result = self.world.tap(user, out["number"])
                if result:
                    warnings += result["warnings"]
                    done = done or result["finished"]
            if done:
                break
        heard = self.prize_messages()
        self.assertEqual(sorted(heard), sorted(t.PRIZE_KEYS), "every prize was still announced")
        self.assertNotIn("image", [b["type"] for b in heard["early5"]["blocks"]])
        self.assertNotIn("image", [b["type"] for b in heard["full"]["blocks"]])
        self.assertTrue(any("banner for the Early Five was not taken" in w for w in warnings), warnings)
        self.assertEqual(len(self.announcements()), 5, "and each only once")

    def test_a_mistake_in_banners_is_in_the_warnings_and_the_game_goes_on(self):
        self.world.settings = {"banners": json.dumps({"full": "http://not-secure.example.com/f.png",
                                                      "jackpot": "https://x.com/a.png"})}
        ids = self.people(2)
        self.open_game(ids, "small")
        warnings = []
        for _ in range(30):
            out = self.next_number()
            if out["finished"]:
                break
            results = [r for r in (self.world.tap(u, out["number"]) for u in ids) if r]
            for r in results:
                warnings += r["warnings"]
            if any(r["finished"] for r in results):
                break
        self.assertTrue(any("'full' is not a public https address" in w for w in warnings), warnings)
        self.assertTrue(any("'jackpot' is not a prize" in w for w in warnings), warnings)
        self.assertEqual(sorted(self.prize_messages()), sorted(t.PRIZE_KEYS), "every prize still announced, no banner")

    def test_the_organizers_own_card_celebrates_the_same_way(self):
        self.world.settings = {"banners": '{"five": "https://cdn.example.com/early.png"}'}
        ids = self.people(1)
        self.open_game(ids, "small", winners="carousel")
        for _ in range(30):
            out = self.next_number()
            self.world.click(HOST, button_named(self.world.panel(HOST), "myticket"), self.CHANNEL)
            card = self.world.panel(HOST)
            mine = [b for b in buttons_of(card) if b["action_id"] == t.ACTION_PREFIX + "hmark_{}".format(out["number"])]
            if mine:
                result = self.world.click(HOST, mine[0], self.CHANNEL)
                if "Early Five" in result["prize"]:
                    break
        heard = self.prize_messages()["early5"]["blocks"]
        self.assertEqual([b["type"] for b in heard], ["image", "carousel"])
        self.assertEqual(heard[0]["image_url"], "https://cdn.example.com/early.png")
        self.assertEqual(carousel_of(heard)[0]["hero_image"]["image_url"], AVATAR.format(HOST, 512),
                         "the organizer's own photo")

    # -- the end of a game: celebrate, then clear the screen
    def celebration_waits(self, **settings):
        """The waits for a celebration (two seconds or more) in a whole small game played with these click-recipe
        settings."""
        self.use_world()
        self.world.settings = dict(settings)
        slept = []
        with mock.patch.object(t, "_sleep", lambda seconds: slept.append(seconds)):
            ids = self.people(3)
            self.open_game(ids, "small")
            self.play_out(ids, 30)
        return [s for s in slept if s >= 2]

    def test_full_house_is_celebrated_for_a_while_and_then_the_screen_is_cleared(self):
        for test in (False, True):
            with self.subTest(test=test):
                self.use_world()
                self.world.settings = {"celebration_seconds": 7,
                                       "banners": json.dumps({"full": "https://cdn.example.com/full.png",
                                                              "top": "https://cdn.example.com/top.png"})}
                ids = self.people(3)
                self.open_game(ids, "small", winners="carousel", test=test)
                seen, slept = [], []

                def wait(seconds):
                    slept.append(seconds)
                    if seconds == 7:                               # the celebration: what is on the screen now
                        seen.append({"standing": [[b["type"] for b in m["blocks"]]
                                                  for m in self.standing_announcements()],
                                     "board": all_text(self.board())})
                with mock.patch.object(t, "_sleep", wait):
                    self.play_out(ids, 30)
                self.assertEqual(slept.count(7), 1, "one wait, at the end of the game")
                during = seen[0]
                self.assertIn("Game over", during["board"], "the board is already final while it is celebrated")
                house = [types for types in during["standing"] if "divider" in types]
                self.assertEqual(len(house), 1)
                self.assertEqual(house[0], ["image", "header", "section", "carousel", "section", "divider"],
                                 "the banner and the winner's card are up")
                self.assertEqual(self.standing_announcements(), [], "and then all of it is cleared away")
                self.assertIn("Game over", all_text(self.board()))
                self.assertEqual(len(carousel_of(self.board())), 5, "the winners stay, in the style chosen")

    def test_how_long_the_celebration_lasts(self):
        self.assertEqual(self.celebration_waits(), [20], "twenty seconds when nothing says otherwise")
        self.assertEqual(self.celebration_waits(celebration_seconds=0), [], "none at all if it is set to 0")
        self.assertEqual(self.celebration_waits(celebration_seconds=999), [60], "never more than a minute")
        self.assertEqual(self.celebration_waits(celebration_seconds=-5), [], "and never less than none")
        self.assertEqual(self.celebration_waits(celebration_seconds="abc"), [20], "an unreadable one is the default")
        self.assertEqual(self.celebration_waits(celebration_seconds="12"), [12])

    def test_with_no_celebration_wait_the_screen_is_cleared_straight_away(self):
        self.world.settings = {"celebration_seconds": 0}
        ids = self.people(2)
        self.open_game(ids, "small")
        self.play_out(ids, 30)
        self.assertEqual(self.standing_announcements(), [])

    def test_a_game_that_ends_without_announcements_has_nothing_to_wait_for(self):
        ids = self.people(2)
        self.open_game(ids, "small", announce="off")
        slept = []
        with mock.patch.object(t, "_sleep", lambda seconds: slept.append(seconds)):
            self.play_out(ids, 30)
        self.assertEqual([s for s in slept if s >= 2], [])
        self.assertEqual(self.announcements(), [])
        self.assertIn("Game over", all_text(self.board()))

    def test_the_screen_is_cleared_even_when_the_table_has_not_shown_the_last_announcements_yet(self):
        """The tap that ends the game writes where its announcements are to the table and reads the game straight back;
        if the read does not show that write yet, those announcements must not be left on the screen."""
        real = t.keep_announcement

        def late(table, g, key, ts, result):
            if "full" not in g["wins"]:
                real(table, g, key, ts, result)
        ids = self.people(3)
        self.open_game(ids, "small", winners="carousel")
        with mock.patch.object(t, "keep_announcement", late):
            self.play_out(ids, 30)
        self.assertEqual(self.standing_announcements(), [])
        self.assertEqual(len(self.announcements()), 5)

    def test_ending_the_game_clears_the_announcements_and_the_board_lists_the_winners(self):
        for style in ("names", "carousel", "strip"):
            for test in (False, True):
                with self.subTest(style=style, test=test):
                    self.use_world()
                    ids = self.people(3)
                    self.open_game(ids, "small", winners=style, test=test)
                    self.play_until(ids, "Early Five")
                    self.assertTrue(self.standing_announcements())
                    out = self.world.click(HOST, button_named(self.world.panel(HOST), "end"), self.CHANNEL)
                    self.assertTrue(out["ok"], out)
                    self.assertEqual(self.standing_announcements(), [])
                    board = self.board()
                    self.assertIn("ended the game", all_text(board))
                    if style == "carousel":
                        self.assertTrue(carousel_of(board))
                    elif style == "strip":
                        self.assertTrue(self.photo_blocks(board))
                    else:
                        self.assertTrue([b for b in board if b.get("fields")])
                    self.assertIn("not won" if style == "names" else "Not won", all_text(board),
                                  "what nobody won is said so, not left 'open'")

    def test_the_last_number_clears_the_announcements_too(self):
        ids = self.people(2)
        self.open_game(ids, "small", winners="strip")
        self.play_until(ids, "Early Five")
        for _ in range(30):
            out = self.next_number()
            if out["finished"]:
                break
        self.assertTrue(out["finished"])
        self.assertEqual(self.standing_announcements(), [])
        self.assertIn("All 30 numbers have been called", all_text(self.board()))
        self.assertTrue(self.photo_blocks(self.board()), "and the winners are on the board")

    def test_with_no_winners_list_the_announcements_stay_but_lose_their_pictures(self):
        self.world.settings = {"banners": json.dumps(
            {k: "https://cdn.example.com/{}.png".format(k) for k in t.PRIZE_KEYS})}
        ids = self.people(3)
        self.open_game(ids, "small", winners="none")
        self.play_out(ids, 30)
        standing = self.standing_announcements()
        self.assertEqual(len(standing), 5, "they are the only record of who won")
        for message in standing:
            self.assertEqual([b["type"] for b in message["blocks"]], ["section"], "just the plain line, no pictures")
        for key in t.LINES:                                         # a line keeps the numbers that made it
            self.assertRegex(all_text(self.prize_messages(standing=True)[key]["blocks"]),
                             r"\d+  ·  \d+  ·  \d+", key)
        self.assertFalse([b for b in self.board() if b.get("fields")])
        self.assertEqual([b["type"] for b in self.prize_messages()["full"]["blocks"]][:1], ["image"],
                         "Full House had its banner while it was up")

    def test_ending_the_game_with_no_winners_list_keeps_what_was_announced(self):
        ids = self.people(2)
        self.open_game(ids, "small", winners="none")
        self.play_until(ids, "Early Five")
        before = len(self.standing_announcements())
        self.assertTrue(self.world.click(HOST, button_named(self.world.panel(HOST), "end"), self.CHANNEL)["ok"])
        self.assertEqual(len(self.standing_announcements()), before)

    # -- the next number clears the celebration
    def test_the_next_number_deletes_the_announcements_the_board_already_lists(self):
        for style in ("names", "carousel", "strip"):
            for test in (False, True):
                with self.subTest(style=style, test=test):
                    self.use_world()
                    ids = self.people(3)
                    self.open_game(ids, "small", winners=style, test=test)
                    self.play_until(ids, "Early Five")
                    self.assertEqual(len(self.standing_announcements()), 1, "up while the number is still the one")
                    ts = self.prize_messages(standing=True)["early5"]["ts"]
                    self.next_number()
                    self.assertEqual(self.standing_announcements(), [], "nothing of the celebration is left")
                    self.assertIn((self.CHANNEL, ts), self.world.deleted, "deleted, not drawn again smaller")
                    self.assertNotIn((self.CHANNEL, ts), self.world.updated)

    def test_with_no_winners_list_the_next_number_leaves_the_plain_line(self):
        self.world.settings = {"banners": json.dumps({"early5": "https://cdn.example.com/early.png"})}
        ids = self.people(3)
        self.open_game(ids, "small", winners="none")
        self.play_until(ids, "Early Five")
        self.assertEqual([b["type"] for b in self.announcement_of("early5")], ["image", "section"])
        self.next_number()
        left = self.announcement_of("early5")
        self.assertEqual([b["type"] for b in left], ["section"], "the banner goes, the line stays: it is the record")
        self.assertIn("goes to", all_text(left))
        self.assertEqual(self.world.deleted, [], "nothing is deleted in a game with no winners list")

    def test_the_organizers_own_wins_are_cleared_by_the_next_number_too(self):
        """What was seen in Slack: the organizer the only player, tapping their own card, and the announcements of
        every prize they won staying at the bottom of the channel."""
        for winners in ("names", "carousel", "strip"):
            with self.subTest(winners=winners):
                self.use_world()
                ids = self.people(1)
                self.open_game(ids, "small", winners=winners)
                won = []
                for _ in range(30):
                    out = self.next_number()
                    self.assertEqual(self.standing_announcements(), [], "nothing is left of the last number's wins")
                    result = self.world.tap(HOST, out["number"])
                    if result:
                        won += [p for p in result["prize"].split(", ") if p]
                        if result["finished"]:
                            break
                self.assertIn("Early Five", won)
                self.assertGreater(len(won), 2, "several prizes were won along the way")
                self.assertEqual(len(self.announcements()), len(won), "each announced once")
                self.assertEqual(self.standing_announcements(), [], "and the end of the game clears the rest")

    def test_what_the_next_number_cleared_is_not_cleared_again_when_the_game_ends(self):
        for test in (False, True):
            with self.subTest(test=test):
                self.use_world()
                ids = self.people(3)
                self.open_game(ids, "small", test=test)
                warnings = []
                for _ in range(30):
                    out = self.next_number()
                    warnings += out["warnings"]
                    results = [r for r in (self.world.tap(u, out["number"]) for u in ids) if r]
                    for r in results:
                        warnings += r["warnings"]
                    if any(r["finished"] for r in results):
                        break
                self.assertEqual(len(self.announcements()), 5)
                self.assertEqual(self.standing_announcements(), [])
                self.assertEqual([w for w in warnings if "clear the" in w or "take the" in w], [],
                                 "an announcement that is gone already is no trouble")
                self.assertEqual(len(self.world.deleted), 5, "each was deleted once")

    # -- the printed ticket
    def test_a_printed_ticket_has_every_number_in_its_column(self):
        w = self.world
        ids = self.people(3)
        self.open_game(ids)                                           # large, printed: the defaults
        self.assertEqual(self.opened_on, "large")
        ranges = t.column_ranges(90)

        def in_their_columns(blocks, prefix):
            rows = [b["elements"] for b in blocks if b["type"] == "actions" and any(
                e["action_id"].startswith(prefix) for e in b["elements"])]
            self.assertEqual([len(cells) for cells in rows], [9, 9, 9])
            for cells in rows:
                self.assertEqual(sum(1 for e in cells if e["action_id"].startswith(prefix)), 5)
                for column, e in enumerate(cells):
                    if e["action_id"].startswith(prefix):
                        number = int(e["action_id"].rsplit("_", 1)[1])
                        self.assertTrue(ranges[column][0] <= number <= ranges[column][1], (column, number))
                    else:
                        self.assertEqual(e["text"]["text"], t.BLANK_TEXT)
            return rows
        in_their_columns(w.host_card(HOST), t.ACTION_PREFIX + "hmark_")             # the organizer's card
        for user in ids[1:]:
            channel, ts, blocks = w.ticket_of(user)
            rows = in_their_columns(blocks, t.ACTION_PREFIX + "mark_")
            self.assertIn("1-9, 10s, 20s ... 80s", all_text(blocks))
            before = [[e["action_id"] for e in cells] for cells in rows]
            # a tap marks a number and leaves every square where it was
            out = self.next_number()
            mine = ticket_numbers_on(blocks)
            number = out["number"]
            if number in mine:
                self.assertEqual(w.tap(user, number)["marked"], number)
                after = [b["elements"] for b in w.messages[(channel, ts)]["blocks"] if b["type"] == "actions"]
                self.assertEqual([[e["action_id"] for e in cells] for cells in after], before)
                self.assertTrue(any(":white_check_mark: {}".format(number) in e["text"]["text"]
                                    for cells in after for e in cells))

    def test_pressing_a_blank_square_does_nothing(self):
        w = self.world
        ids = self.people(2)
        self.open_game(ids)
        channel, ts, blocks = w.ticket_of(ids[1])
        blank = [b for b in buttons_of(blocks) if b["action_id"].startswith(t.BLANK_ACTION)][0]
        snapshot = json.dumps(w.messages[(channel, ts)]["blocks"], sort_keys=True)
        calls, private, rows = len(w.calls), len(w.private), json.dumps(w.rows, sort_keys=True)
        out = w.click(ids[1], blank, channel, source_ts=ts, response=False)
        self.assertEqual((out["ok"], out["mode"], out["skipped"], out["error"]), (True, "blank", "a blank square", ""))
        self.assertEqual(json.dumps(w.messages[(channel, ts)]["blocks"], sort_keys=True), snapshot)
        self.assertEqual((len(w.calls), len(w.private), json.dumps(w.rows, sort_keys=True)), (calls, private, rows),
                         "no message sent, no row touched, nothing asked of Slack or the table")
        # and it needs no table token, being nobody's game
        out = w.click(ids[1], blank, channel, source_ts=ts, response=False, workato_api_token="")
        self.assertTrue(out["ok"], out)

    def test_every_size_keeps_its_ticket_laid_out_the_same_all_game_long(self):
        for test in (False, True):
            for size in t.SIZES:
                with self.subTest(size=size, test=test):
                    self.use_world()
                    ids = self.people(3)
                    self.open_game(ids, size, test=test)
                    width = columns_of(size)
                    for user in ids:
                        self.assertEqual(row_widths(self.ticket_blocks_of(user)), [width] * 3)
                    calls, won = self.play_out(ids, t.SIZES[size]["numbers"])
                    self.assertEqual(won[-1] if won else "", "full", won)
                    for user in ids[1:]:                  # laid out the same after all the taps
                        self.assertEqual(row_widths(self.ticket_blocks_of(user)), [width] * 3)
                    self.assertIn("Game over", all_text(self.board()))

    def test_choosing_each_dropdown_keeps_what_the_others_show(self):
        w = self.world
        self.people(2)
        w.type_word(HOST, self.CHANNEL, "itambola")
        card = w.last_note(HOST)["blocks"]
        state = dropdown_state(size_menu_of(card), "small", "BLOCKA")
        state.update(dropdown_state(board_menu_of(card), "list", "BLOCKB"))
        out = w.select(HOST, winners_menu_of(card), "carousel", self.CHANNEL, state=state)
        self.assertEqual(out["mode"], "winners")
        now = w.last_note(HOST)["blocks"]
        self.assertEqual((chosen_size(now), chosen_board(now), chosen_winners(now)), ("small", "list", "carousel"))

    def test_a_game_saved_with_a_ticket_layout_in_its_settings_goes_on_with_printed_tickets(self):
        """A game saved by an earlier version has a ticket layout in its settings. It is not a choice any more: the game
        plays on, its winners style where it was, its tickets laid out as a printed one is."""
        w = self.world
        ids = self.people(2)
        self.open_game(ids, winners="carousel")
        row = w.rows_of(t.GAME_ROW)[0]
        state = json.loads(row["content"])
        state["f"][7] = "compact"                                      # what an earlier version could have saved there
        row["content"] = json.dumps(state)
        mine = ticket_numbers_on(w.ticket_of(ids[1])[2])
        number = 0
        while number not in mine:
            number = self.next_number()["number"]
        self.assertEqual(w.tap(ids[1], number)["marked"], number)
        self.assertEqual(row_widths(w.ticket_of(ids[1])[2]), [9, 9, 9], "redrawn as a printed ticket")
        self.assertEqual(t.game_from_row(row)["cfg"]["winners"], "carousel", "and the winners style is still read")

    # -- the organizer's own ticket is in their note, never in a private message
    def test_the_organizer_is_sent_no_ticket_by_private_message(self):
        for test in (False, True):
            with self.subTest(test=test):
                self.use_world()
                w = self.world
                ids = self.people(4)
                out = self.open_game(ids, "small", test=test)
                self.assertEqual(out["dm_sent"], 3, "the other three players")
                self.assertEqual([m for (c, _ts), m in w.messages.items() if c == "D" + HOST], [],
                                 "nothing at all in the organizer's private messages")
                for user in ids[1:]:
                    self.assertEqual(len(w.tickets_of(user)), 1, user)
                if not test:                                           # but they are a player: a row, with their ticket
                    row = [r for r in w.rows_of(t.PLAYER_ROW) if r["group_id"] == HOST]
                    self.assertEqual(len(row), 1)
                    kept = t.player_from_row(row[0])
                    self.assertTrue(kept["ticket"] and not kept["dm_channel"] and not kept["dm_ts"])
                    self.assertEqual(set(kept["marks"]), set())
                    self.assertEqual(len(w.rows_of(t.PLAYER_ROW)), 4)
                card = w.host_card(HOST)                               # their ticket opens in their note
                self.assertEqual(len(ticket_numbers_on(card)), 9)
                self.assertEqual(w.tickets_of(HOST), [], "and still nothing was sent")

    def test_show_my_card_without_a_response_url_is_a_new_private_note_not_a_message(self):
        w = self.world
        ids = self.people(2)
        self.open_game(ids, "small")
        before = len(w.events(HOST))
        out = w.click(HOST, button_named(w.panel(HOST), "myticket"), self.CHANNEL, response=False)
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(w.events(HOST)), before + 1)
        note = w.last_note(HOST)
        self.assertEqual(note["how"], "note", "a new private note, in the channel")
        self.assertEqual(len(ticket_numbers_on(note["blocks"])), 9, "with the card in it")
        self.assertEqual(w.tickets_of(HOST), [])
        self.assertEqual([m for (c, _ts), m in w.messages.items() if c == "D" + HOST], [])

    def test_a_card_that_cannot_be_read_is_said_and_nothing_is_sent(self):
        w = self.world
        ids = self.people(2)
        self.open_game(ids, "small")
        with mock.patch.object(t, "organizer_ticket", lambda *args, **kwargs: None):
            out = w.click(HOST, button_named(w.panel(HOST), "myticket"), self.CHANNEL)
        self.assertEqual(out["error"], "could not read your card")
        note = w.last_note(HOST)
        self.assertIn("Could not save that just now", (note["text"] or "") + all_text(note["blocks"]))
        self.assertEqual(w.tickets_of(HOST), [])

    def test_the_organizer_typing_the_word_again_gets_their_controls_not_a_ticket(self):
        w = self.world
        ids = self.people(3)
        self.open_game(ids, "small", winners="carousel")
        self.play_until(ids, "Early Five")
        out = w.type_word(HOST, self.CHANNEL, "itambola")
        self.assertEqual((out["mode"], out["ok"]), ("panel", True), out)
        self.assertIn("You already have a", all_text(w.last_note(HOST)["blocks"]))
        self.assertEqual(w.tickets_of(HOST), [])
        self.assertEqual(self.winners_label(), "Show winners :trophy:", "and the controls know somebody has won")

    # -- typing the word again, which the board's footer tells a player to do
    def test_typing_the_word_again_brings_a_player_their_ticket_not_a_new_game(self):
        w = self.world
        ids = self.people(3)
        self.open_game(ids, "small")
        w.members[self.CHANNEL] = ids + ["U0000009"]              # joins the channel after the game began: not dealt in
        w.names["U0000009"] = "Late Joiner"
        sam = ids[1]
        mine = ticket_numbers_on(w.ticket_of(sam)[2])
        number = 0
        while number not in mine:                                    # a number on Sam's ticket gets called and marked
            number = self.next_number()["number"]
        self.assertEqual(w.tap(sam, number)["marked"], number)
        games = len(w.rows_of(t.GAME_ROW))

        out = w.type_word(sam, self.CHANNEL, "itambola")                     # a player
        self.assertEqual((out["mode"], out["ok"]), ("ticket", True), out)
        dms = sorted((ts, m) for (c, ts), m in w.messages.items() if c == "D" + sam)
        newest = dms[-1][1]["blocks"]
        self.assertIn(":white_check_mark: {}".format(number), all_text(newest), "their marks come back with it")
        self.assertEqual(len(w.rows_of(t.GAME_ROW)), games, "no new game")
        self.assertNotIn(t.ACTION_PREFIX + "set_all", [b["action_id"] for b in buttons_of(w.last_note(sam)["blocks"])])

        out = w.type_word(HOST, self.CHANNEL, "itambola")                    # the host
        self.assertEqual((out["mode"], out["ok"]), ("panel", True), out)
        self.assertIn("You already have a Tambola game open", all_text(w.last_note(HOST)["blocks"]))
        self.assertEqual(len(w.rows_of(t.GAME_ROW)), games)

        out = w.type_word("U0000009", self.CHANNEL, "itambola")              # someone who is not playing: a new game
        self.assertEqual(out["mode"], "setup", out)
        late = [b["action_id"] for b in buttons_of(w.last_note("U0000009")["blocks"])]
        self.assertIn(t.ACTION_PREFIX + "set_all", late)

        out = w.type_word(sam, self.CHANNEL, "itambola", workato_api_token="")   # no table token on the typed recipe
        self.assertEqual(out["mode"], "setup", "without it the word cannot find the game, so it always opens the setup")

    def test_once_the_game_is_over_the_word_starts_a_new_one(self):
        w = self.world
        ids = self.people(2)
        self.open_game(ids, "small")
        self.assertTrue(w.click(HOST, button_named(w.panel(HOST), "end"), self.CHANNEL)["ok"])
        self.assertEqual(w.type_word(ids[1], self.CHANNEL, "itambola")["mode"], "setup")
        self.assertEqual(w.type_word(HOST, self.CHANNEL, "itambola")["mode"], "setup")

    def test_the_board_only_offers_a_lost_ticket_while_the_game_is_on(self):
        ids = self.people(2)
        self.open_game(ids, "small")
        running = all_text(self.board())
        self.assertIn("Playing and lost your ticket? Type `itambola` here and it is sent to you again", running)
        self.next_number()
        self.world.click(HOST, button_named(self.world.panel(HOST), "review"), self.CHANNEL)
        self.world.click(HOST, button_named(self.world.panel(HOST), "resume"), self.CHANNEL)
        self.assertIn("lost your ticket", all_text(self.board()))
        self.assertTrue(self.world.click(HOST, button_named(self.world.panel(HOST), "end"), self.CHANNEL)["ok"])
        over = all_text(self.board())
        self.assertIn("Game over", over)
        self.assertNotIn("lost your ticket", over)
        self.assertIn("Hosted by", over)

    def test_the_channel_sees_the_title_once(self):
        ids = self.people(3)
        self.open_game(ids, "small")
        lobby, board = self.world.channel_messages(self.CHANNEL)[:2]
        self.assertEqual(self.lobby_text.count(":tickets:"), 1, "the open lobby: its header, once")
        started = all_text(lobby["blocks"])
        self.assertNotIn("header", [b["type"] for b in lobby["blocks"]], "the started lobby is a line, not a title")
        self.assertIn("Game on with 3 players", started.replace("*", ""))
        self.assertIn("Players (3)", started.replace("*", ""))
        self.assertEqual(started.count("Tambola"), 0)
        self.assertEqual(started.count(":tickets:"), 0)
        self.assertNotIn("Prizes", started)
        self.assertEqual(all_text(board["blocks"]).count("Tambola"), 1)
        self.assertEqual(all_text(board["blocks"]).count(":tickets:"), 1)
        both = started + all_text(board["blocks"])
        self.assertEqual((both.count(":tickets:"), both.count("Tambola")), (1, 1), "once across what the channel shows")

    # -- board styles, on the second dropdown
    def test_every_board_style_plays_through_at_every_size_and_in_test_games(self):
        for test in (False, True):
            for style in t.BOARD_STYLES:
                with self.subTest(style=style, test=test):
                    self.use_world()
                    ids = self.people(3)
                    self.open_game(ids, "small", board=style, test=test)
                    self.assertEqual(chosen_board(self.setup_blocks), style)
                    self.assertEqual(self.opened_board, "emoji")
                    out = self.next_number()
                    text = all_text(self.board())
                    if style == "emoji":
                        self.assertEqual(len(grid_sections(self.board())), 3)
                    elif style == "numbers":
                        grid = "\n".join(code_table(self.board()))
                        self.assertEqual(re.findall(r"\d\d", grid), ["{:02d}".format(out["number"])])
                        self.assertEqual(grid.count("??"), 29)
                    else:
                        self.assertIn("Called so far", text)
                        self.assertIn(str(out["number"]), text)
                    if style != "emoji":
                        self.assertNotIn(":zero:", text)
                        self.assertNotIn(t.EMPTY_TILE, text)
                    calls, won = self.play_out(ids, 30)
                    self.assertEqual(won[-1] if won else "", "full", "{} {}".format(style, won))
                    self.assertIn("Game over", all_text(self.board()))

    def test_the_style_chosen_is_the_one_kept_with_the_game(self):
        for style in t.BOARD_STYLES:
            self.use_world()
            ids = self.people(2)
            self.open_game(ids, board=style)
            game = t.game_from_row(self.world.rows_of(t.GAME_ROW)[0])
            self.assertEqual(game["cfg"]["board"], style)
            self.assertEqual(game["cfg"]["size"], "large", "the size was not touched")

    def test_the_recipes_board_style_is_where_the_dropdown_starts(self):
        ids = self.people(2)
        self.open_game(ids, board_style="numbers")
        self.assertEqual(self.opened_board, "numbers")
        self.assertIn("[", code_table(self.world.messages[(self.CHANNEL, self.world.channel_messages(
            self.CHANNEL)[-1]["ts"])]["blocks"])[0] + "[", "the board opens in its style")
        self.next_number()
        self.assertEqual(len(code_table(self.board())), 9, "ninety numbers are nine rows of ten")

    def test_choosing_one_dropdown_keeps_what_the_other_shows(self):
        w = self.world
        self.people(2)
        w.type_word(HOST, self.CHANNEL, "itambola")
        card = w.last_note(HOST)["blocks"]
        # the size is chosen, but the card is not redrawn for it (the press only says what the dropdowns show)
        state = dropdown_state(size_menu_of(card), "small", "BLOCKA")
        out = w.select(HOST, board_menu_of(card), "list", self.CHANNEL, state=state)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["mode"], "board")
        now = w.last_note(HOST)["blocks"]
        self.assertEqual((chosen_size(now), chosen_board(now)), ("small", "list"))
        out = w.select(HOST, size_menu_of(now), "medium", self.CHANNEL,
                       state=dropdown_state(board_menu_of(now), "list", "BLOCKB"))
        self.assertEqual(out["mode"], "size")
        again = w.last_note(HOST)["blocks"]
        self.assertEqual((chosen_size(again), chosen_board(again)), ("medium", "list"))

    def test_the_lobby_and_board_follow_both_dropdowns_whatever_the_buttons_were_drawn_with(self):
        for test in (False, True):
            with self.subTest(test=test):
                self.use_world()
                ids = self.people(3)
                w = self.world
                w.type_word(HOST, self.CHANNEL, "itambola", **({"testing": "yes"} if test else {}))
                card = w.last_note(HOST)["blocks"]
                self.assertEqual((chosen_size(card), chosen_board(card)), ("large", "emoji"))
                state = dropdown_state(size_menu_of(card), "small", "BLOCKA")
                state.update(dropdown_state(board_menu_of(card), "numbers", "BLOCKB"))
                out = w.click(HOST, button_named(card, "set_all"), self.CHANNEL, state=state)
                self.assertTrue(out["ok"], out)
                self.assertIn("(small game: numbers 1 to 30)", all_text(w.channel_messages(self.CHANNEL)[-1]["blocks"]))
                out = w.click(HOST, button_named(w.panel(HOST), "start"), self.CHANNEL)
                self.assertTrue(out["ok"], out)
                board = w.messages[(self.CHANNEL, out["message_ts"])]["blocks"]
                self.assertEqual(len(code_table(board)), 3, "a plain number grid of thirty numbers")
                self.assertEqual(grid_sections(board), [])
                if not test:
                    game = t.game_from_row(w.rows_of(t.GAME_ROW)[0])
                    self.assertEqual((game["cfg"]["size"], game["cfg"]["board"]), ("small", "numbers"))

    def test_a_board_dropdown_that_did_not_arrive_is_reported(self):
        self.world.type_word(HOST, self.CHANNEL, "itambola")
        out = t.main({"action_id": t.BOARD_ACTION, "user_id": HOST, "channel": self.CHANNEL,
                      "action_ts": self.world.tick(), "slack_bot_token": "xoxb-test", "workato_api_token": "wk-test"})
        self.assertFalse(out["ok"])
        self.assertIn("board dropdown's choice did not arrive", out["error"])
        out = t.main({"action_id": t.BOARD_ACTION, "selected_option": "garbage", "user_id": HOST,
                      "channel": self.CHANNEL, "action_ts": self.world.tick(), "slack_bot_token": "xoxb-test",
                      "workato_api_token": "wk-test"})
        self.assertIn("not one of the choices on the setup card's board dropdown", out["error"])

    def test_the_choice_can_arrive_as_just_the_options_value(self):
        w = self.world
        w.type_word(HOST, self.CHANNEL, "itambola")
        menu = size_menu_of(w.last_note(HOST)["blocks"])
        value = [o["value"] for o in menu["options"] if json.loads(o["value"])["s"] == "small"][0]
        out = t.main({"action_id": t.SIZE_ACTION, "selected_option": value, "user_id": HOST, "channel": self.CHANNEL,
                      "action_ts": w.tick(), "slack_bot_token": "xoxb-test", "workato_api_token": "wk-test",
                      "response_url": HOOK + HOST})
        self.assertTrue(out["ok"], out)
        self.assertEqual(chosen_size(w.last_note(HOST)["blocks"]), "small")

    def test_a_large_game_is_what_it_always_was(self):
        ids = self.people(4)
        self.open_game(ids)
        self.assertEqual((self.opened_on, chosen_size(self.setup_blocks)), ("large", "large"))
        self.assertIn("15 numbers in 3 rows", self.lobby_text)
        self.assertNotIn(" game: numbers", self.lobby_text)
        for user in ids:
            blocks = self.ticket_blocks_of(user)
            self.assertEqual(row_widths(blocks), [9, 9, 9], "a printed row has a cell for each of nine columns")
            self.assertEqual(len(ticket_numbers_on(blocks)), 15)
        game = t.game_from_row(self.world.rows_of(t.GAME_ROW)[0])
        self.assertEqual((game["cfg"]["size"], t.numbers_of(game)), ("large", 90))
        out = self.next_number()
        self.assertEqual(out["number"], t.draw_order(game["seed"])[0])
        self.assertIn("1 of 90 called", all_text(self.board()).replace("*", ""))

    # -- the review, with a hundred players
    def test_the_review_of_a_hundred_players_is_a_short_table(self):
        ids = self.people(100)
        self.open_game(ids, max_players=100)
        self.assertEqual(len(self.world.rows_of(t.PLAYER_ROW)), 100)
        called = []
        for _ in range(14):
            called.append(self.next_number()["number"])
        for i, user in enumerate(ids[:40]):                      # some play more than others
            mine = [n for n in called if n in ticket_numbers_on(self.ticket_blocks_of(user))]
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
        self.open_game(ids, "small", top_n=4)
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
                self.open_game(ids, size, test=True)
                self.assertEqual(self.world.rows, {}, "a test game writes nothing to the table")
                for button in buttons_of(self.setup_blocks):             # a test game's card carries its whole state
                    self.assertTrue(button["value"].startswith(t.TEST_PREFIX + "|set|"))
                self.assertIn("{} numbers in 3 rows".format(3 * spec["row"]), self.lobby_text)
                out = self.next_number()
                self.assertIn("1 of {} called".format(spec["numbers"]), all_text(self.board()).replace("*", ""))
                for user in ids:
                    self.assertEqual(len(ticket_numbers_on(self.ticket_blocks_of(user))), 3 * spec["row"])
                # a number that has not been called is refused, one that has is marked
                player = ids[1]
                channel, ts, blocks = self.world.ticket_of(player)
                numbers = ticket_numbers_on(blocks)
                other = [n for n in numbers if n != out["number"]][0]
                self.assertEqual(self.world.tap(player, other)["marked"], 0)
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
                self.open_game(ids, size)
                self.assertFalse([b for b in buttons_of(self.world.panel(HOST))
                                  if b["action_id"].startswith(t.ACTION_PREFIX + "hmark_")], "closed to begin with")
                out = self.world.click(HOST, button_named(self.world.panel(HOST), "myticket"), self.CHANNEL)
                self.assertTrue(out["ok"], out)
                card = self.world.panel(HOST)
                rows = [b for b in card if b["type"] == "actions" and any(
                    e["action_id"].startswith(t.ACTION_PREFIX + "hmark_") for e in b["elements"])]
                self.assertEqual([len(r["elements"]) for r in rows], [columns_of(size)] * 3)
                mine = ticket_numbers_on(card)
                self.assertEqual(len(mine), 3 * spec["row"])
                number = 0
                while number not in mine:                         # call numbers until one is on the organizer's card
                    number = self.next_number()["number"]         # (the note keeps its card open as it is redrawn)
                press = [e for r in self.world.panel(HOST) if r["type"] == "actions" for e in r["elements"]
                         if e["action_id"] == t.ACTION_PREFIX + "hmark_{}".format(number)][0]
                out = self.world.click(HOST, press, self.CHANNEL)
                self.assertTrue(out["ok"], out)
                self.assertEqual(out["marked"], number)
                self.assertIn(":white_check_mark: {}".format(number), all_text(self.world.panel(HOST)))
                row = [t.player_from_row(r) for r in self.world.rows_of(t.PLAYER_ROW) if r["group_id"] == HOST][0]
                self.assertIn(number, row["marks"], "and it is kept, as anyone's marks are")


class TestGamesByPayload(TestGames):
    """Every game above again, with each press sent as one `payload` and nothing else mapped but the tokens."""
    via = "payload"


if __name__ == "__main__":
    unittest.main()
