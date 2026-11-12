"""
Tambola (Housie) -- the classic numbers game, played in a Slack channel with buttons.

One Python step, two recipes (a Workato step is one file, so it routes on what it is given):

    `action_value` or `action_id` present  ->  a button (or the player menu) was used
    otherwise                               ->  someone typed itambola / ihousie

WHO SEES WHAT
    Everybody sees the grid: the BOARD, a message in the channel with no button on it. The one button a
    participant can see is Join, on the lobby of a game that anyone may join. Every CONTROL belongs to the
    organizer, whoever typed the word, and is a PRIVATE NOTE that only they see (Slack cannot show a button
    to one person inside a public message):

        the setup card    dropdowns for Game size, Board style, Ticket layout and Winners; Everyone in this channel /
                          I will pick the players / Anyone who wants to play
        lobby controls    Start game, Cancel; for "I will pick the players" also a menu of people
        game controls     Next number, Review, Show my card, End game, and what was last called
        while paused      Resume, Show my card, End game

    ONE NOTE FOR THE WHOLE GAME. Slack cannot edit a private note, but a press on it can replace it through
    the press's `response_url`, so the organizer's controls are one note that changes in place: the setup card
    becomes the lobby's controls, Start turns those into the game's, each Next number shows the number just
    called and how many are out, Review and Resume swap the buttons, and a button that has gone stale (Next
    number while paused) turns into the right controls with a line on top. A long game therefore does not
    bury the organizer in notes. Without `response_url` mapped it still works, but a new note is sent when the
    game moves on (never for Next number), and they pile up. Map it.

    The organizer PLAYS TOO: they are always one of the players and get a ticket of their own, even when
    nobody else is in the game, whichever of the three ways of joining was chosen. Like everyone's it is sent by
    private message at the start, but they need not leave the channel for it: Show my card opens it inside
    their note, under the controls, and Hide my card tucks it away again. Tapping a number there follows the
    same rules as a ticket in a private message (a number not called yet is refused, a called one turns green
    and can win a prize) and the ticket they were sent stays in step. The note says on every button whether the
    card is open, so the next press draws it the same way. Opening it redraws the note in place, so it needs
    `response_url` mapped; without it Show my card sends the ticket by private message, as before.
    Slack drops private notes when it reloads. Typing the word again sends the organizer a fresh note with
    their controls (for the game they run in this channel); for anybody else playing in one it sends their
    ticket again; for everyone else it starts a new game. A game older than ACTIVE_HOURS counts as abandoned, and
    a lobby that was never started after LOBBY_HOURS. The note says it is the controls of a game they already
    have, and that Cancel (or End game) there makes room for a fresh one.

HOW A GAME GOES
    1  Someone types `itambola` (or `ihousie`). Only they see the three ways to join.
    2  The channel gets a LOBBY: three short rules, the prizes, who is in and, for an open game, a Join
       button. The organizer gets the lobby controls. "I will pick the players" gives them a menu of people
       and the lobby follows it. Each player is a row in the data table, name included.
    3  Start (the organizer) posts the BOARD and sends every player a TICKET by private message. The lobby
       shrinks to one line and who is in (the board below it has the title and the prizes: nothing is said twice).
    4  The board is a grid of 90 white squares (in the default emoji style, see BOARD STYLE). Each Next number
       turns one into its number (two keycap digits) in the same message and says it in words, with the caller's
       name for it where there is one: "47: Forty-seven", "22: Twenty-two, two little ducks" (CALLS).
    5  A ticket is 3 rows of numbers, each a button, laid out like a printed ticket (see TICKET LAYOUT). When a
       number is called the
       player taps it on their ticket and it turns green. A number that has NOT been called is refused on the
       ticket ("47 has not been called yet"). Any number that HAS been called can be tapped later: nobody loses
       one by being slow.
    6  Prizes (PRIZES, or the `prizes` input): Early Five (the first five numbers marked), Top Line, Middle
       Line, Bottom Line, Full House. The press that finishes one wins it (the earliest, by Slack's own click
       time) and the channel hears about it (`announce`: channel, thread or off). Full House ends the game,
       as does the 90th number or End game. The board shows who holds each prize.

    Tickets are dealt as a printed one is: 9 columns (column 1 holds 1-9, column 2 10-19 ... column 9 80-90),
    1 to 3 numbers in each, 5 in every row, in ascending order down a column and along a row (a smaller game has
    fewer columns, see GAME SIZE).

TICKET LAYOUT  (printed, compact: LAYOUTS)
    How those numbers sit on the buttons, chosen on a third dropdown of the setup card:

        printed  every number in its own column, as on paper: a cell for each column (9 for a large game), the
                 numbers where their tens put them and a quiet blank button where the ticket has a blank, so a
                 number is found by its tens (the default; the ticket says which tens its columns are)
        compact  just the numbers, in rows of five (four, three), no blanks: the ticket this step dealt before

    A blank is a button that does nothing (Slack has no inert one). A row of printed cells is a row of buttons, 9 for a
    large game, and a long row may be folded by Slack on a narrow screen: if so, compact is one choice away. A small
    game's three columns are full either way, so its layouts look alike. The layout is chosen like the size (read from
    the press's `state`, the card redrawn when it is used), starts on the recipe's `ticket_layout` input (printed when
    blank) and is kept with the game. A game saved before layouts existed keeps compact tickets, as it was dealt them.

GAME SIZE  (small, medium, large: SIZES)
    One setting sets both how many numbers are called and how big a ticket is, so a quick game is quick:

        large   numbers 1 to 90, 15 on a ticket (3 rows of 5)    the classic game, and the default
        medium  numbers 1 to 60, 12 on a ticket (3 rows of 4)
        small   numbers 1 to 30,  9 on a ticket (3 rows of 3)    a quick game

    The organizer chooses it on a DROPDOWN of the setup card, above the three ways of joining ("Game size": small,
    medium, large, each with its numbers and ticket in its name). The size in the dropdown when a way of joining is
    pressed is the game's: Slack reports what every dropdown shows with each press (the interaction's `state`), and
    this reads it from there, so it holds even if the card was never redrawn for the choice. Choosing in a dropdown
    also redraws the card in place (the dropdown standing on it, each way of joining carrying it); without
    `response_url` a new card is sent instead. The card opens on the recipe's `size` input (large when it is blank),
    so a channel that mostly plays quick games can start there. The lobby (its rules and a note) says the size, and
    the board, the tickets and the review all follow it. The size is kept with the game. A game made before sizes
    existed is a large one and plays exactly as it did. The tickets keep the printed layout, one column for each ten
    numbers.

BOARD STYLE  (emoji, numbers, list: BOARD_STYLES)
    How the numbers called are shown on the board, chosen on a second dropdown of the setup card, beside the size's:

        emoji    a square for every number, a number emoji where it was called, the number just called in emoji
                 too (the original board, and the default)
        numbers  a plain grid in a code block, so the columns line up: ?? where a number has not been called, the
                 number itself in its place when it comes up (nothing moves); the number just called in bold.
                 board_columns sets how many to a row
        list     no grid: just the numbers called so far, smallest first, a line of fifteen at a time

    It is chosen the way the size is (read from the press's `state`, and the card redrawn when it is used), starts on
    the recipe's `board_style` input (emoji when blank) and is kept with the game. A game made before board styles
    existed has the emoji board.

WINNERS ON THE BOARD  (names, carousel, strip, none: WINNERS_STYLES)
    How the board shows who has won each prize, chosen on a fourth dropdown of the setup card:

        names     the prizes with who holds each, or "open" (the board's original list)
        carousel  a Slack carousel with a card for each winner: the prize, their name, what it took and their Slack
                  profile picture. The first winner is on the RIGHT and each new winner is added to the LEFT of the
                  others, so the newest is what you see first; a line under it names the prizes still to win
        strip     the same, as one line of small profile pictures with the prize and name beside each
        none      winners are not listed on the board (the announcements still tell the channel)

    A winner's picture is looked up once, when they win, and kept with the win (the win's row, in a real game), so
    redrawing the board on every number costs nothing; a test game keeps its state in a message with no room for
    addresses, so it looks them up again. A card without a picture is still a card. If Slack refuses the carousel (a
    workspace without it) the board is drawn with names instead and the warnings say so, so the game never stops
    updating. It starts on the recipe's `winners_style` input (names when blank), is read from the press's `state`
    like the other dropdowns and is kept with the game; a game saved before it existed shows names.

CELEBRATIONS  (PRIZE_TIER: the bigger the prize, the bigger the announcement)
    The channel hears of each prize the moment it is won (`announce`: channel, thread or off), and the announcement
    grows with the prize:

        Early Five         one line, one emoji
        a line (top, middle, bottom)   a header (Slack's big text), the winner and the numbers that made the line,
                                       and a few emojis around them
        Full House         a header, a long row of emojis above and below, and a divider

    Each prize can also have a BANNER, a picture above its announcement: set `banners` on the recipe that takes the
    presses (the click recipe, where the prizes are won) to a JSON object of public https image addresses,

        {"early5": "https://.../early-five.png", "top": "https://.../top-line.png",
         "middle": "https://.../middle-line.png", "bottom": "https://.../bottom-line.png",
         "full": "https://.../full-house.png"}

    naming only the prizes that have one. A prize can be named as in `prizes` (five, house ...), and "lines" gives all
    three lines one picture unless one is named on its own. A bad address or name is left out and said in the job's
    warnings. Banners are optional; without them the header and emojis are the celebration. The height of the picture
    is what makes the bigger prizes bigger, so give Full House the tallest.
    If Slack will not load a banner the announcement goes without it, and the job's warnings say so: a banner can
    never cost a win its announcement. A prize is announced once, however many times a click is handled.

REVIEW AND RESUME  (the organizer's controls)
    Review pauses the game and puts a summary in the board's place, for everyone: the numbers called (in
    brackets, how many players hold each), who holds each prize and who is closest to the ones still open,
    a short ranked table of the players with the most numbers marked, as the leaderboard shows its top rows (#, name,
    marked, a bar; equal counts share a rank, T2; top_n rows, ten by default, then a count of the rest, so a hundred
    players are still ten lines) and how many players have marked 0-3, 4-7, 8-11 and 12-15 numbers (the steps follow
    the ticket's size). While it is up Next number is refused,
    but players can still tap numbers already called (and win). Resume puts the board back, prizes and all,
    and the numbers carry on where they were. A test game has no player rows, so its review leaves the
    player figures out.

THE CARDS (kept short, as iMath's rules card is)
    Lobby      header (the one place the title and :tickets: are said, with the board's), host, 3 bullets,
               prizes, players, [ Join game ] on an open game and nothing else
    Board      header, the number just called, the grid in its style, the prizes, a line on getting a lost
               ticket back. No button.
    Review     header, counts, the numbers called, prizes, the top of the ranking as one table, the spread
    Ticket     a private message to each player: 3 rows of buttons in the game's layout and a line of progress

TWO PRESSES AT ONCE
    Next number is the organizer's alone, and what it reveals is fixed in advance: the order of the numbers
    is a shuffle made from a seed stored with the game. A second press within DEBOUNCE seconds of the last is
    taken as one press made twice and ignored, and two jobs that read the same count both write the same new
    one, so the board never skips a number. Start is claimed in the table before anything is posted, so a
    double press starts one game. Setting a game up is claimed the same way. Two players finishing the same
    prize in the same second are told apart by Slack's click time. A prize is a row that carries a token of its
    own, and only the press whose row is the earliest announces it, so one player's click handled twice (a double
    tap, a number tapped again, the click delivered twice) is announced once.

THE ROWS  (workato_governance_unified; none of the types ends in _users, and none uses a person as `id`,
    which spotter reads in one unpaged query; EVERY row carries `slack_channel_id`, because the same step
    runs in several channels, and every lookup is scoped by it)
    tambola_game    one per game: id = game id (tb_<channel>_<message ts>), record_key tambola_game_<id>,
                    slack_channel_id, group_id = host, member_name = host, grant_type = mode (all, pick,
                    open), status lobby / starting / running / paused / done / cancelled, day,
                    last_processed_ts = when it was set up, content = json (seed, how many numbers are
                    called, the players once it has started, message timestamps, the settings)
    tambola_player  one per player per game: id = game id, group_id = the person, member_name, status in,
                    content = json (ticket, numbers marked, where the ticket message is)
    tambola_win     one per prize press: id = game id, grant_type = prize, group_id = the winner,
                    member_name, last_processed_ts = Slack's click time (the earliest holds the prize)

TEST GAMES (input `testing` = yes, on the recipe that takes the typed word)
    The whole game plays for real in the channel but NOTHING is written to the data table. A test game's
    state is kept in the messages it posts, in their block ids (not shown anywhere), and read back from
    Slack when a button is pressed (so the bot needs channels:history, or groups:history in a private
    channel). The organizer's buttons carry only a pointer to that message; a ticket button carries the
    ticket, the numbers marked so far and the board it belongs to. The click recipe needs no `testing`
    mapped: a test game is recognised by its buttons. A test game holds up to TEST_PLAYERS people, typing
    the word always opens a fresh setup card (there is no table to find a test game in), two presses in
    the same second can overwrite each other (the real game, a row per player, cannot), and its review has
    no player figures.
    `skip_post` = yes goes further: nothing is posted either; the cards come back in `preview_json` (paste a
    "blocks" list into Slack's Block Kit Builder).

THE TWO RECIPES
    Typed    Slack Workbot trigger on new messages, condition: text matches /\b(itambola|ihousie)\b/i ->
             this step. Map text, user_id, channel, message_ts, thread_ts (and bot_id, subtype if you like)
             plus slack_bot_token and workato_api_token (the token lets the word find the game the person
             already runs or plays in). Optional settings: testing, skip_post, announce, prizes,
             board_columns, max_players, top_n, and size / board_style / ticket_layout / winners_style (what the
             setup card's four dropdowns open on).
    Click    Slack interactivity trigger, filtered to action_id CONTAINING `tambola_click_` -> this step.
             Simplest: map `payload`, the whole interaction as JSON (the trigger's block_actions object, in
             formula mode its `.to_json`; the trigger's own {"block_actions:button": {...}} wrapper is fine), plus
             slack_bot_token and workato_api_token. Everything below is read out of it, and the size dropdown's
             choice with it. Fields mapped by hand are kept and the payload only fills what is blank, so the old way
             still works, field by field:
                 action_value   <- actions[0].value
                 action_id      <- actions[0].action_id        (the player menu has no value)
                 selected_users <- actions[0].selected_users   (the player menu's pick, when it is the
                                                               people picker)
                 selected_options <- actions[0].selected_options  (the player menu's pick, when it is the
                                                               channel's list: map both, one stays empty)
                 state          <- state                       (every dropdown's current choice: without it
                                                               or `payload` the dropdowns' settings are the
                                                               ones the button was drawn with)
                 user_id        <- user.id
                 channel        <- container.channel_id
                 source_ts      <- container.message_ts
                 action_ts      <- actions[0].action_ts
                 response_url   <- response_url               (top level; keeps the organizer to ONE note)
             plus slack_bot_token and workato_api_token. Nothing else but the optional `banners` of CELEBRATIONS. A
             ticket press arrives from the player's private message, so `channel` there is that message's channel, not
             the game's.

SLACK SCOPES   chat:write, users:read; channels:read (groups:read) for "Everyone in this channel";
               channels:history (groups:history) only for test games; im:write is a fallback for DMs.

BUTTONS  (every action_id starts `tambola_click_`; a real game's value is tb|<kind>|<game>|<arg>)
    size | board | layout | winners  the setup card's dropdowns of game size, board style, ticket layout and
                                     winners display (selects: no value, the choice is the selected_option, and
                                     in `state` on every later press)
    set_all | set_pick | set_open    the three choices on the setup card (private)
    pick_<game>                      the organizer's menu of people (a select: no value): a list of the
                                     channel's members, the organizer in it, or Slack's people picker when
                                     the channel has more people than one menu holds (100)
    start | cancel                   the organizer's lobby controls (private)
    join                             the lobby of an open game (public, everybody)
    next | review | resume | end     the organizer's game controls (private)
    myticket                         Show my card / Hide my card, on the organizer's note (private)
    hmark_<number>                   a number on the organizer's card, in their note (private)
    mark_<number>                    a number on a ticket (private message to the player)
    blank_<row>_<column>             a blank square of a printed ticket: does nothing
    test games use  tbt|<kind>|<json>  for all of these.

Input / output schema: tambola_input_schema.json / tambola_output_schema.json
"""

import base64
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

TABLE_ID = "0b863cb1-4712-416b-a9d5-7bf7f2f9b059"
TABLE_QUERY_URL = "https://data-tables.workato.com/api/v1/tables/{}/query".format(TABLE_ID)
TABLE_RECORDS_URL = "https://data-tables.workato.com/api/v1/tables/{}/records".format(TABLE_ID)
TABLE_RECORD_URL = TABLE_RECORDS_URL + "/{}"

SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
SLACK_UPDATE_URL = "https://slack.com/api/chat.update"
SLACK_DELETE_URL = "https://slack.com/api/chat.delete"
SLACK_EPHEMERAL_URL = "https://slack.com/api/chat.postEphemeral"
SLACK_USER_URL = "https://slack.com/api/users.info"
SLACK_MEMBERS_URL = "https://slack.com/api/conversations.members"
SLACK_REPLIES_URL = "https://slack.com/api/conversations.replies"
SLACK_OPEN_URL = "https://slack.com/api/conversations.open"

# Short: a Workato Python step is stopped at 90 seconds, and one slow call must not carry it past that.
HTTP_TIMEOUT = 12

# Stand-ins so a test can run without waiting.
_sleep = time.sleep
_now = time.time

# --------------------------------------------------------------------------
# Rows and columns -- the only place a field UUID appears
# --------------------------------------------------------------------------

GAME_ROW = "tambola_game"
PLAYER_ROW = "tambola_player"
WIN_ROW = "tambola_win"

COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "grant_type": "355e769f-0aa3-46be-bea3-5c2b3442f658",
    "member_name": "bc214e7f-c007-4fd7-ac0e-6367b1e4098f",
    "status": "863a9d40-87a7-49ff-ba40-32858e62cd48",
    "last_processed_ts": "5761a90c-832e-4bf5-aaee-5d6a4d43f045",
    "source_ref": "e530be4a-68dc-4e9a-ad1f-2dbb8af3abf1",
    "slack_channel_id": "7101072d-867b-4104-a1e4-ef6611adaaa9",
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
    "day": "5cfe9bc1-cc32-4a5b-9cc6-4f6682cb7a4b",
}

LOOKUP_FAILED = object()          # a read that failed is not "no such row"
SKIPPED = object()                # a task that was not started because time ran out
QUERY_MAX_PAGES = 50              # a stop for the paging loop, far past any real game

# game statuses
LOBBY, STARTING, RUNNING, PAUSED, DONE, CANCELLED = "lobby", "starting", "running", "paused", "done", "cancelled"

# --------------------------------------------------------------------------
# Tuning -- every number that shapes the game is data, not logic
# --------------------------------------------------------------------------

NUMBERS = 90                      # the most numbers a game can have (the large size): 1 to 90
TICKET_ROWS = 3
EARLY_COUNT = 5                   # numbers marked for Early Five

# GAME SIZES. One setting shapes the whole game: how many numbers are called (1 to N) AND how many numbers a ticket
# holds (3 rows of `row`). Large is the full game and the default. A smaller one is a quick game: fewer numbers to
# call, a smaller ticket to fill. `row` is also the buttons in a row of a ticket (Slack folds past 5). The printed
# ticket's layout follows from N: one column for each ten numbers (1-9, 10-19 ... the last one up to N), holding 1 to
# 3 numbers, so a row needs no more numbers than there are columns. `tag` is a word or two in the dropdown. Add or
# change a size here; nothing else holds these figures. The first key is the default. The organizer chooses the size
# on a dropdown of the setup card, in the order of their numbers.
SIZES = {
    "large": {"label": "Large", "numbers": 90, "row": 5, "tag": "classic"},     # 15 numbers on a ticket
    "medium": {"label": "Medium", "numbers": 60, "row": 4, "tag": ""},          # 12 numbers on a ticket
    "small": {"label": "Small", "numbers": 30, "row": 3, "tag": "quick"},       # 9 numbers on a ticket
}
DEFAULT_SIZE = next(iter(SIZES))
SIZE_ALIASES = {"l": "large", "full": "large", "big": "large", "classic": "large", "normal": "large",
                "m": "medium", "med": "medium", "mid": "medium", "regular": "medium",
                "s": "small", "quick": "small", "mini": "small", "short": "small", "fast": "small"}
OPTION_VALUE_MAX = 150            # Slack's limit on the value of a menu's option

# BOARD STYLES: how the numbers called are shown on the board, chosen on a second dropdown of the setup card. Emoji
# is the original look (a square for every number, a number emoji where it was called); the others are plainer, for
# people who find that too much. The first key is the default. `text` finishes the dropdown's line.
BOARD_STYLES = {
    "emoji": {"label": "Emoji grid", "text": "squares fill in with number emojis"},
    "numbers": {"label": "Number grid", "text": "a ?? for each number until it is called"},
    "list": {"label": "Called list", "text": "just the numbers called so far"},
}
DEFAULT_BOARD_STYLE = next(iter(BOARD_STYLES))

# TICKET LAYOUTS: how the numbers sit on a player's ticket, chosen on a third dropdown of the setup card. Printed is the
# paper ticket: a cell for every column (1-9, 10s, 20s ... 80s), each number in its own column and the rest blank, so a
# number is found by its tens. Compact keeps just the numbers, in ascending rows (the ticket this step always dealt).
# A blank is a quiet button that does nothing. A row of cells is a row of buttons, and Slack may fold a long one on a
# narrow screen, which is why the plainer layout stays on offer. The first key is the default.
LAYOUTS = {
    "printed": {"label": "Printed ticket", "text": "numbers in their column (1-9, 10s, 20s ...), blanks between"},
    "compact": {"label": "Compact ticket", "text": "just the numbers, in short rows"},
}
# WINNERS: how the board shows who has won each prize, chosen on a fourth dropdown of the setup card. Names is the list
# of prizes with their holders (the board's original look); the photo styles show each winner's Slack profile picture,
# the first winner on the right and each new one added to the left of it (a carousel of cards, or a strip of small
# pictures in one line); none leaves winners off the board (the announcements still tell the channel). A photo style
# that Slack refuses falls back to names, never to a board that does not update. The first key is the default.
WINNERS_STYLES = {
    "names": {"label": "Names", "text": "who holds each prize, in a list"},
    "carousel": {"label": "Photo carousel", "text": "each winner's photo on a card, newest on the left"},
    "strip": {"label": "Photo strip", "text": "small profile photos in a row"},
    "none": {"label": "None", "text": "the board does not list winners"},
}
DEFAULT_WINNERS = next(iter(WINNERS_STYLES))
PHOTO_STYLES = ("carousel", "strip")
WINNERS_ALIASES = {"list": "names", "text": "names", "cards": "carousel", "photos": "carousel", "photo": "carousel",
                   "avatars": "strip", "faces": "strip", "off": "none", "hidden": "none", "no": "none"}
WINNER_BODY = {"early5": "First to mark five numbers", "top": "Completed the top row",
               "middle": "Completed the middle row", "bottom": "Completed the bottom row",
               "full": "Marked every number on the ticket"}
CARD_LIMIT = 150                  # Slack's limit on a card's title and subtitle (a body: 200)

DEFAULT_LAYOUT = next(iter(LAYOUTS))
LEGACY_LAYOUT = "compact"         # a game saved before layouts existed was dealt compact tickets, and keeps them
LAYOUT_ALIASES = {"paper": "printed", "physical": "printed", "columns": "printed", "real": "printed",
                  "short": "compact", "rows": "compact", "plain": "compact", "simple": "compact"}
BOARD_ALIASES = {"emojis": "emoji", "tiles": "emoji", "plain": "numbers", "number": "numbers", "normal": "numbers",
                 "text": "numbers", "called": "list", "calls": "list", "compact": "list"}

BOARD_COLUMNS = 10                # squares to a row of the board: 10 gives the traditional 9 rows
HIDDEN_CELL = "?"                 # what a number not yet called shows on the plain board, once for each of its digits
MAX_PLAYERS = 60                  # most players in a game: the step has 90 seconds to deal them all in
TEST_PLAYERS = 24                 # a test game keeps its state in the message it posts, so it holds fewer
ANNOUNCE = ("channel", "thread", "off")
ACTIVE_HOURS = 12                 # a game older than this is taken as abandoned when the word is typed again
LOBBY_HOURS = 2                   # and a lobby that was never started, after this
DEBOUNCE = 1.2                    # seconds: a second Next number this soon after the last is one press made twice

WORKERS = 6                       # tickets are sent on this many threads (1 = one after another)
START_SECONDS = 45                # past this many seconds a player who has not been dealt in yet waits for My ticket
VERIFY_DELAY = 0.5                # before re-reading what a press may have raced
CLAIM_STALE = 120                 # seconds before a Start that never finished may be claimed again
RECENT_CALLS = 8                  # earlier numbers named under the one just called
NAMES_SHOWN = 12                  # names in the lobby before "+N more"
REVIEW_PLAYERS = 10               # players the review ranks (top_n), as the leaderboard shows its top rows
REVIEW_PLAYERS_MAX = 50           # most the top_n input allows
REVIEW_LINE = 15                  # called numbers to a line of the review
REVIEW_SECTION_LIMIT = 2800       # characters of a table in one block, under Slack's 3000 (as the leaderboard keeps)
REVIEW_NAME_WIDTH = 18            # characters of a name in the review's table, as the leaderboard trims names
NAME_MAX = 18                     # characters of a name a test game keeps in its message
MENU_MAX = 100                    # people one menu can list (Slack's limit on a menu's options)
MENU_SECONDS = 20                 # longest spent looking up the names for the organizer's menu
BUTTON_MAX = 75                   # Slack's limit on a button's text
RATE_LIMIT_WAIT = 1.5             # seconds before the one retry of a call Slack rate-limited

# The prizes, in the order they are shown: key, name, icon, what it takes. `prizes` can keep fewer.
PRIZES = (
    ("early5", "Early Five", ":zap:", "the first five numbers marked"),
    ("top", "Top Line", ":arrow_up:", "all five numbers of the top row"),
    ("middle", "Middle Line", ":left_right_arrow:", "all five numbers of the middle row"),
    ("bottom", "Bottom Line", ":arrow_down:", "all five numbers of the bottom row"),
    ("full", "Full House", ":trophy:", "all fifteen numbers"),
)
PRIZE_KEYS = tuple(p[0] for p in PRIZES)
PRIZE_NAME = {p[0]: p[1] for p in PRIZES}
PRIZE_ICON = {p[0]: p[2] for p in PRIZES}
# the ways a prize can be named in `prizes` and in `banners`, lower case, without spaces, dashes or underscores
PRIZE_ALIASES = {"early": "early5", "early5": "early5", "earlyfive": "early5", "five": "early5",
                 "top": "top", "toprow": "top", "topline": "top", "middle": "middle", "midline": "middle",
                 "middleline": "middle", "middlerow": "middle", "bottom": "bottom", "bottomline": "bottom",
                 "bottomrow": "bottom", "full": "full", "fullhouse": "full", "house": "full", "housie": "full"}

# CELEBRATIONS grow with the prize. Tier 1, Early Five: one line and one emoji. Tier 2, a line: a header (Slack's big
# text) and more emojis around the line. Tier 3, Full House: a header, a long row of emojis above and below, and a
# divider: the biggest thing the channel sees. Each prize can also carry a BANNER, a picture above the announcement,
# from the `banners` input of the recipe that takes the presses (a public https image: its height is what makes the
# bigger prizes bigger, so give Full House the tallest). A banner Slack will not load is left out, never the win.
PRIZE_TIER = {"early5": 1, "top": 2, "middle": 2, "bottom": 2, "full": 3}
TIER_FLAIR = {1: ":zap:", 2: ":tada::sparkles::tada:",
              3: ":confetti_ball::tada::sparkles::trophy::sparkles::tada::confetti_ball:"}
BANNER_URL_MAX = 3000             # Slack's limit on an image's url
LINES = {"top": 0, "middle": 1, "bottom": 2}

# The traditional caller's names for a few numbers, as said in housie halls. Only the family-friendly
# ones are here; a number with no entry is simply read out. Add or drop any, nothing else uses them.
CALLS = {
    1: "Kelly's eye", 2: "One little duck", 3: "Cup of tea", 4: "Knock at the door", 5: "Man alive",
    6: "Half a dozen", 7: "Lucky seven", 8: "Garden gate", 9: "Doctor's orders", 11: "Legs eleven",
    12: "One dozen", 13: "Unlucky for some", 14: "Valentine's day", 15: "Young and keen",
    16: "Sweet sixteen", 17: "Dancing queen", 18: "Coming of age", 19: "Goodbye teens",
    20: "One score", 21: "Key of the door", 22: "Two little ducks", 24: "Two dozen",
    25: "Duck and dive", 26: "Pick and mix", 27: "Gateway to heaven", 28: "In a state",
    29: "Rise and shine", 31: "Get up and run", 32: "Buckle my shoe", 34: "Ask for more",
    35: "Jump and jive", 36: "Three dozen", 38: "Christmas cake", 39: "Those famous steps",
    40: "Life begins at forty", 41: "Time for fun", 42: "Winnie the Pooh", 45: "Halfway there",
    46: "Up to tricks", 47: "Four and seven", 48: "Four dozen", 50: "Half a century",
    51: "Tweak of the thumb", 52: "Weeks in a year", 53: "Here comes Herbie", 54: "Clean the floor",
    55: "Snakes alive", 57: "Heinz varieties", 58: "Make them wait", 59: "Brighton line",
    60: "Three score", 61: "Baker's bun", 62: "Tickety-boo", 65: "Old age pension",
    66: "Clickety click", 67: "Made in heaven", 68: "Saving grace", 70: "Three score and ten",
    71: "Bang on the drum", 72: "Six dozen", 73: "Queen bee", 74: "Candy store",
    75: "Strive and strive", 76: "Trombones", 77: "Sunset strip", 78: "Heaven's gate",
    79: "One more time", 81: "Stop and run", 82: "Straight on through", 83: "Time for tea",
    84: "Seven dozen", 85: "Staying alive", 86: "Between the sticks", 87: "Torquay in Devon",
    89: "Nearly there", 90: "Top of the shop",
}

# --------------------------------------------------------------------------
# Wording -- keep it plain and workplace-appropriate
# --------------------------------------------------------------------------

ANONYMOUS = "Someone"
MODE_BUTTONS = {
    "all": ":busts_in_silhouette: Everyone in this channel",
    "pick": ":clipboard: I will pick the players",
    "open": ":raised_hand: Anyone who wants to play",
}
MODES = tuple(MODE_BUTTONS)

SETUP_TEXT = ":tickets: *{word}*: set the game up below, then choose how people join. Only you can see this."
SETUP_NOTE = ("The lobby opens in the channel. Your controls, Start game included, stay here in a note only you "
              "can see. Tickets go out as private messages when you press Start.")
SETUP_SIZE = "*Game size*\nA smaller game has fewer numbers and a smaller ticket, so it is quicker."
SETUP_BOARD = "*Board style*\nHow the numbers called are shown on the board."
SETUP_LAYOUT = "*Ticket layout*\nHow the numbers sit on each player's ticket."
SETUP_WINNERS = "*Winners*\nHow the board shows who has won each prize."
SETUP_MENU = {"size": SETUP_SIZE, "board": SETUP_BOARD, "layout": SETUP_LAYOUT, "winners": SETUP_WINNERS}
MENU_PLACEHOLDER = {"size": "Game size", "board": "Board style", "layout": "Ticket layout", "winners": "Winners"}
WINNERS_OPTION = "{label}: {text}"
STILL_TO_WIN = "*Still to win:*  {prizes}"
SIZE_OPTION = "{label}{tag}: numbers 1 to {numbers}, {ticket} on a ticket"
BOARD_OPTION = "{label}: {text}"
LAYOUT_OPTION = "{label}: {text}"
BLANK_TEXT = "\u00b7"             # a blank square of a printed ticket: a button that does nothing
TICKET_COLUMNS = "Each number sits in its column, as on a printed ticket: {columns}."
RULES = ("• Every player gets a ticket in a private message: {ticket} numbers in 3 rows.\n"
         "• Numbers from 1 to {numbers} are called on the board in this channel. Tap yours on your ticket when "
         "they come up.\n"
         "• First to finish a line, or the whole ticket, wins that prize.")
SIZE_NOTE = " ({label} game: numbers 1 to {numbers})"
LOBBY_MODE_LINE = {
    "all": "Everyone in this channel is playing{count}, the host included.",
    "pick": "{host} is choosing the players.",
    "open": "Press *Join game* to play.",
}
LOBBY_HOST = "Hosted by *{host}*{size}"
LOBBY_PLAYERS = "*Players ({count}):* {names}"
LOBBY_STARTED = ":arrow_forward: *Game on* with {count} {players}. Numbers are called on the board below :point_down:"
LOBBY_CANCELLED = ":no_entry_sign: {host} cancelled this game."
PICK_PLACEHOLDER = "Choose players"
TEST_NOTE = ":test_tube: Test game: nothing is saved."

# The organizer's controls are a PRIVATE note: a button in a public message is seen by everybody, so none of
# these is on the lobby or the board (a participant sees the grid, and Join on an open lobby). Slack cannot edit
# a private note, but a press on it can REPLACE it (through the press's response_url), so there is ONE note for
# the whole game: the setup card becomes the lobby's controls, Start turns those into the game's, every Next
# number shows what was just called, Review and Resume swap the buttons, and a button that has gone stale turns
# into the right ones with a line on top. Without a response_url a new note is sent when the game moves on
# (never for Next number), and they pile up.
PANEL_HEAD = ":gear: *Your controls.* Only you can see this."
PANEL_LOBBY = (":gear: *Your controls for {word}.* Only you can see this. You are in the game too, with a "
               "ticket of your own, even if nobody else joins. Press *Start game* when everyone is in.")
PANEL_LOBBY_PICK = (":gear: *Your controls for {word}.* Only you can see this. Choose the players below: the "
                    "lobby follows your choices, and you are always in, with a ticket of your own. Press "
                    "*Start game* when everyone is in.")
PANEL_NO_MENU = (" The player menu could not be shown just now: type `{word}` in the channel to try again, or press "
                 "*Start game* to play with just yourself.")
PANEL_NO_NUMBER = ":game_die: No number called yet. Press *Next number* to call the first one."
PANEL_LAST = ":game_die: Last called *{number}*  ({said})  \u00b7  *{called}* of {numbers} called"
PANEL_PAUSED_LINE = ":pause_button: *Paused* at *{called}* of {numbers} called. The board shows the review."
PANEL_HINT_RUNNING = ("*Review* pauses the game and shows everyone where it stands. *Show my card* opens your own "
                      "card here, so you can tap your numbers without leaving the channel.")
PANEL_HINT_PAUSED = "*Resume* puts the board back and carries on."
CARD_HEAD = ":tickets: *Your card.* Tap a number when it is called."

# The review replaces the board for everyone while the game is paused.
REVIEW_HEAD = ":bar_chart: {word}: review"
REVIEW_PAUSED = ":pause_button: Paused while {host} shows where everyone stands. The game carries on shortly."
REVIEW_COUNTS = "*{called}* of {numbers} numbers called  ·  {players} {playerword}  ·  {won} of {total} prizes won"
REVIEW_CALLED = "*Numbers called*  (in brackets, how many players hold each)"
REVIEW_NONE_CALLED = "_No number has been called yet._"
REVIEW_PLAYERS_HEAD = "*Players by numbers marked*"
REVIEW_TOP_HEAD = "*Top {top} of {total} players by numbers marked*"
REVIEW_SPREAD = "Players by numbers marked:  {spread}"
REVIEW_MORE = "+{count} more {playerword}, none with more than {best} marked"
REVIEW_TEST = ":test_tube: Test game: each player's progress is only shown in a real game."

BOARD_READY = ":game_die: *Ready.* Press *Next number* to call the first one."
BOARD_CALLED = "*Called so far*\n"
BOARD_FOOT = "Hosted by {host}  ·  {count} {players}"
BOARD_FOOT_LOST = "  ·  Playing and lost your ticket? Type `{word}` here and it is sent to you again."
OVER_FULL = ":trophy: *Game over.* {name} completed the Full House."
OVER_NUMBERS = ":checkered_flag: *Game over.* All {numbers} numbers have been called."
OVER_ENDED = ":checkered_flag: *Game over.* {host} ended the game."
NEXT_TEXT = "Next number :game_die:"
REVIEW_TEXT = "Review :bar_chart:"
RESUME_TEXT = "Resume :arrow_forward:"
SHOW_CARD_TEXT = "Show my card :tickets:"
HIDE_CARD_TEXT = "Hide my card"
END_TEXT = "End game"
END_CONFIRM = "End the game for everyone? The board stays, the numbers stop."
JOIN_TEXT = "Join game :raised_hand:"
START_TEXT = "Start game :arrow_forward:"
CANCEL_TEXT = "Cancel"

TICKET_HEAD = ":tickets: *Your ticket*"
TICKET_WHERE = "Game in <#{channel}>  ·  hosted by {host}. Tap a number when it is called on the board."
TICKET_OVER = ":checkered_flag: This game has finished."

SAID_GONE = ":warning: That game is not available any more."
SAID_AGAIN = ":warning: Could not save that just now. Please press the button again."
SAID_NOT_HOST = ":lock: Only {host} can do that: they set this game up."
SAID_PAUSED = ":pause_button: The game is paused. Press *Resume* to carry on."
SAID_NOT_PAUSED = ":information_source: The game is not paused."
SAID_NOT_PLAYING = ":information_source: You are not playing in this game."
SAID_ALREADY_IN = ":information_source: You are already in. Your ticket arrives when the game starts."
SAID_JOINED = (":white_check_mark: You are in. Your ticket arrives in a private message when {host} "
               "starts the game.")
SAID_FULL = ":warning: This game already has {count} players, which is the most it holds."
SAID_OVER = ":checkered_flag: This game has finished."
SAID_NOT_STARTED = ":information_source: This game has not started yet."
SAID_STARTED = ":information_source: This game has already started."
SAID_HAVE_GAME = (":information_source: You already have a {word} game open in this channel, so these are its "
                  "controls. Press *{done}* here to start a fresh one.")
SAID_SET_UP = ":information_source: This game is already set up. Look for the lobby in the channel."
SAID_BUSY = ":hourglass: The game is being started. Give it a few seconds."
SAID_CANCELLED = ":no_entry_sign: This game was cancelled."
SAID_MEMBERS = (":warning: I could not read this channel's members ({error}). Pick the players yourself "
                "or let anyone join.")
SAID_TOO_MANY = (":warning: This channel has {count} people, and a game holds {max} players at most. Pick "
                 "the players yourself or let anyone join.")
SAID_NO_TICKET = (":warning: I could not message {names}. Typing `{word}` in the channel sends a ticket "
                  "again; for you, the host, there is the *My ticket* button.")
SAID_TICKET_SENT = ":tickets: Your ticket is in a private message."
SAID_TICKET_FAILED = ":warning: I could not message you just now. Please try again."
SAID_TEST_FULL = ":warning: A test game holds up to {count} players. Start a fresh test with fewer."
SAID_TEST_LOST = (":warning: I could not read this test game back from its message. The bot needs "
                  "channels:history (groups:history in a private channel), and the message must still be there.")

TICKET_WRONG = ":x: *{number}* has not been called yet."
TICKET_MARKED = ":white_check_mark: *{number}* marked."
TICKET_AGAIN = ":information_source: *{number}* is already marked."
TICKET_WON = ":tada: *{prize}* is yours!"
TICKET_LOST = ":information_source: {name} finished the *{prize}* a moment before you."


# --------------------------------------------------------------------------
# Pure helpers -- no I/O below this line until the EDGES section
# --------------------------------------------------------------------------

def _switch(value, default=False):
    text = str(value if value is not None else "").strip().lower()
    if not text:
        return default
    return text in ("yes", "true", "1", "y", "on")


def _int(value, default, low, high):
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def as_ts(value):
    """Slack's timestamp as a number; 0 when it is not one."""
    try:
        return float(str(value or "").strip())
    except ValueError:
        return 0.0


def esc(text):
    """Text for a mrkdwn block: Slack reads & < > as markup, so a name cannot carry them."""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unique(items):
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def ids_in(value):
    """Slack user ids found in a list, or in text of any shape (a list datapill may arrive as either). The picks of a
    menu can be people (the people picker) or options, {"value": id, "text": name} (the channel's list): from options
    only the value is read, so a name is never mistaken for an id."""
    if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    if isinstance(value, dict):
        value = [value]
    if isinstance(value, (list, tuple)):
        value = " ".join(str(v.get("value") or v.get("id") or "") if isinstance(v, dict) else str(v) for v in value)
    return unique(re.findall(r"\b[UW][A-Z0-9]{6,}\b", str(value or "")))


def plural(count, one, many=None):
    return one if count == 1 else (many or one + "s")


# ---- game sizes: how many numbers are called and how big a ticket is

def parse_size(value, default=DEFAULT_SIZE):
    """A size key from its name or an alias (small, quick, m ...); `default` when it is none of them."""
    word = re.sub(r"[^a-z]", "", str(value or "").lower())
    word = SIZE_ALIASES.get(word, word)
    return word if word in SIZES else default


def parse_board_style(value, default=DEFAULT_BOARD_STYLE):
    """A board style key from its name or an alias (plain, normal, called ...); `default` when it is none of them."""
    word = re.sub(r"[^a-z]", "", str(value or "").lower())
    word = BOARD_ALIASES.get(word, word)
    return word if word in BOARD_STYLES else default


def parse_layout(value, default=DEFAULT_LAYOUT):
    """A ticket layout key from its name or an alias (paper, rows ...); `default` when it is none of them."""
    word = re.sub(r"[^a-z]", "", str(value or "").lower())
    word = LAYOUT_ALIASES.get(word, word)
    return word if word in LAYOUTS else default


def parse_winners(value, default=DEFAULT_WINNERS):
    """A winners style key from its name or an alias (photos, list, off ...); `default` when it is none of them."""
    word = re.sub(r"[^a-z]", "", str(value or "").lower())
    word = WINNERS_ALIASES.get(word, word)
    return word if word in WINNERS_STYLES else default


def size_of(g):
    """The size figures of a game (SIZES). A game saved before sizes existed has none, and is a large one."""
    return SIZES[parse_size((g.get("cfg") or {}).get("size"))]


def numbers_of(g):
    return size_of(g)["numbers"]


def row_size_of(g):
    return size_of(g)["row"]


def ticket_size_of(g):
    return TICKET_ROWS * row_size_of(g)


def layout_columns(numbers):
    """Columns of a printed ticket: one for each ten numbers, the last one holding whatever is left."""
    return -(-numbers // 10)


def column_ranges(numbers):
    """The numbers each column of a ticket draws from: 1-9, then each ten, the last one running up to `numbers`
    (for 90: 1-9, 10-19 ... 70-79, 80-90)."""
    columns = layout_columns(numbers)
    return [(1, 9)] + [(c * 10, c * 10 + 9) for c in range(1, columns - 1)] + [((columns - 1) * 10, numbers)]


def size_label(size):
    return SIZES[parse_size(size)]["label"]


def size_note(g):
    """What the lobby says after the host's name when the game is not the usual one."""
    if parse_size(g["cfg"].get("size")) == DEFAULT_SIZE:
        return ""
    return SIZE_NOTE.format(label=size_of(g)["label"].lower(), numbers=numbers_of(g))


def rules_text(g):
    return RULES.format(ticket=ticket_size_of(g), numbers=numbers_of(g))


def spread_buckets(ticket_size):
    """Four steps from none marked to a full ticket, as the review counts players in: (0, 3) (4, 7) (8, 11) (12, 15)
    for 15 numbers on a ticket, (0, 2) (3, 5) (6, 8) (9, 9) for 9."""
    width = -(-(ticket_size + 1) // 4)
    return [(low, min(ticket_size, low + width - 1)) for low in range(0, ticket_size + 1, width)]


def names_text(names, shown=NAMES_SHOWN):
    names = [esc(n) for n in names]
    if len(names) <= shown:
        return ", ".join(names)
    return "{}, +{} more".format(", ".join(names[:shown]), len(names) - shown)


def today_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def game_channel(game_id):
    """The channel a game belongs to: it is part of the game's id (tb_<channel>_<message ts>)."""
    parts = str(game_id or "").split("_")
    return parts[1] if len(parts) >= 3 and parts[0] == "tb" else ""


ONES = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
        "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
DIGITS = (":zero:", ":one:", ":two:", ":three:", ":four:", ":five:", ":six:", ":seven:", ":eight:",
          ":nine:")
EMPTY_TILE = ":white_large_square:" * 2


def number_words(number):
    if number < 20:
        return ONES[number]
    tens, ones = divmod(number, 10)
    return TENS[tens] + ("-" + ONES[ones] if ones else "")


def tiles(number):
    """A number as two keycap digits: 7 is 07, so every square of the board is the same width."""
    return DIGITS[number // 10] + DIGITS[number % 10]


def call_lines(number, style=DEFAULT_BOARD_STYLE):
    """What the board says for the number just called: the number in words, then the caller's name for it. The emoji
    board says it with number emojis, the others in plain bold."""
    words = number_words(number)
    line = "{}  *{}*".format(tiles(number), words[0].upper() + words[1:]) if style == "emoji" else \
        "*{}*  \u00b7  {}".format(number, words[0].upper() + words[1:])
    if number in CALLS:
        line += "\n_{}_".format(CALLS[number])
    return line


def board_rows(called, columns=BOARD_COLUMNS, numbers=NUMBERS):
    """The grid as lines of text, a white square for each number not called and its digits for each that is."""
    called = set(called)
    rows = []
    for start in range(1, numbers + 1, columns):
        cells = [tiles(n) if n in called else EMPTY_TILE for n in range(start, min(start + columns, numbers + 1))]
        rows.append(" ".join(cells))
    return rows


def number_grid(called, columns=BOARD_COLUMNS, numbers=NUMBERS):
    """The plain board: a grid in a code block, so the columns line up. A number is not shown until it is called: its
    place holds ?? (as many characters as the number has digits), and the number takes that place when it comes up,
    so nothing moves. A row of ten is thirty-eight characters."""
    called = set(called)
    width = len(str(numbers))
    lines = []
    for start in range(1, numbers + 1, columns):
        cells = ["{:0{w}d}".format(n, w=width) if n in called else HIDDEN_CELL * width
                 for n in range(start, min(start + columns, numbers + 1))]
        lines.append("  ".join(cells))
    return "```\n" + "\n".join(lines) + "\n```"


def called_lines(called, per_line=15):
    """The numbers called, smallest first, a line of `per_line` at a time."""
    ordered = sorted(called)
    rows = [ordered[i:i + per_line] for i in range(0, len(ordered), per_line)]
    return "\n".join("  \u00b7  ".join(str(n) for n in row) for row in rows)


# ---- the numbers and the tickets: fixed by a seed, so the same game can always be worked out again

def _shuffle(rng, items):
    items = list(items)
    for i in range(len(items) - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        items[i], items[j] = items[j], items[i]
    return items


def draw_order(seed, numbers=NUMBERS):
    """The order the numbers come out in. Only random() is used, because Python promises that stays the
    same from one version to the next; a shuffle's own method is not promised. A game of 90 numbers (the large
    size, and every game made before sizes) comes out exactly as it always did."""
    return _shuffle(random.Random(int(seed)), range(1, numbers + 1))


def called_list(g):
    """The numbers called so far in this game, in the order they were called."""
    return draw_order(g["seed"], numbers_of(g))[:g["n"]]


def _ticket_rng(seed, user_id):
    digest = hashlib.sha256("{}:{}".format(seed, user_id).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def make_ticket(seed, user_id, size=DEFAULT_SIZE):
    """A ticket as 3 rows of numbers (5 each in a large game, 4 in a medium one, 3 in a small one), ascending,
    dealt as a printed one is.

    A printed ticket is 3 rows by one column for each ten numbers (9 for a large game): every column holds 1 to 3
    numbers from its own tens (the first 1-9, the last up to the game's highest), every row holds the same count,
    15 in all for a large game. That layout is made first; each row is then read off left to right. The same
    seed and person always give the same ticket, and a large ticket is the one this function has always dealt.
    """
    spec = SIZES[parse_size(size)]
    row_size = spec["row"]
    columns, ranges = layout_columns(spec["numbers"]), column_ranges(spec["numbers"])
    ticket_size = TICKET_ROWS * row_size
    rng = _ticket_rng(seed, user_id)
    for _attempt in range(100):
        counts = [1] * columns
        for _extra in range(ticket_size - columns):
            open_columns = [c for c in range(columns) if counts[c] < TICKET_ROWS]
            counts[open_columns[int(rng.random() * len(open_columns))]] += 1
        room = [row_size] * TICKET_ROWS
        layout = [[False] * columns for _ in range(TICKET_ROWS)]
        # the columns needing the most rows go first, each into the rows with the most room left; a
        # tie falls whichever way the dice say. This always fills every row to exactly its size.
        for column in sorted(range(columns), key=lambda c: (-counts[c], rng.random())):
            rows = sorted(range(TICKET_ROWS), key=lambda r: (-room[r], rng.random()))[:counts[column]]
            for row in rows:
                layout[row][column] = True
                room[row] -= 1
        if room == [0] * TICKET_ROWS:
            break
    else:                                                          # pragma: no cover
        raise RuntimeError("no ticket could be dealt")
    ticket = [[] for _ in range(TICKET_ROWS)]
    for column in range(columns):
        low, high = ranges[column]
        picked = sorted(_shuffle(rng, range(low, high + 1))[:counts[column]])
        for row, number in zip([r for r in range(TICKET_ROWS) if layout[r][column]], picked):
            ticket[row].append(number)
    return ticket


def deal_ticket(g, user_id):
    """The ticket this player holds in this game: its seed, its size."""
    return make_ticket(g["seed"], user_id, g["cfg"].get("size"))


def ticket_numbers(ticket):
    return [n for row in ticket for n in row]


def number_column(number, numbers):
    """The column of a printed ticket a number belongs to: 1-9 the first, then each ten, the last up to `numbers`."""
    return min(number // 10, layout_columns(numbers) - 1)


def ticket_cells(g, ticket):
    """The rows of a ticket as its layout draws them, [[number or None, ...], ...]: printed gives a cell for each column
    of the printed ticket, a number in its own column and the rest None (blank); compact gives just the numbers. A
    ticket that does not fit the printed layout (two numbers in one column: not one this step deals) is drawn compact
    rather than lose a number."""
    compact = [list(row) for row in ticket]
    if parse_layout(g["cfg"].get("layout")) == "compact":
        return compact
    columns, numbers = layout_columns(numbers_of(g)), numbers_of(g)
    rows = []
    for row in ticket:
        cells = [None] * columns
        for number in row:
            column = number_column(number, numbers)
            if cells[column] is not None:
                return compact
            cells[column] = number
        rows.append(cells)
    return rows


def column_names(numbers):
    """The tens a printed ticket's columns stand for, as a short line: 1-9, 10s, 20s ... 80s."""
    names = ["1-9"] + ["{}s".format(c * 10) for c in range(1, layout_columns(numbers))]
    return ", ".join(names) if len(names) <= 4 else "{}, {}, {} ... {}".format(*names[:3], names[-1])


def mask_of(ticket, marks):
    """The numbers marked as one integer, a bit for each place on the ticket (reading row by row)."""
    marks = set(marks)
    return sum(1 << i for i, n in enumerate(ticket_numbers(ticket)) if n in marks)


def marks_of(ticket, mask):
    try:
        mask = int(mask)
    except (TypeError, ValueError):
        return set()
    return {n for i, n in enumerate(ticket_numbers(ticket)) if mask >> i & 1}


def completed_prizes(ticket, marks, prizes):
    """Which of `prizes` this ticket has earned with these numbers marked, in prize order."""
    marked, every = set(marks), set(ticket_numbers(ticket))
    earned = []
    for key in PRIZE_KEYS:
        if key not in prizes:
            continue
        if key == "early5":
            done = len(marked & every) >= EARLY_COUNT
        elif key == "full":
            done = every <= marked
        else:
            done = set(ticket[LINES[key]]) <= marked
        if done:
            earned.append(key)
    return earned


def progress_line(ticket, marks):
    """Where a ticket stands: "Marked 6 of 15  ·  Top 3/5  ·  Middle 1/5  ·  Bottom 2/5"."""
    marked = set(marks)
    parts = ["Marked {} of {}".format(len(marked & set(ticket_numbers(ticket))), len(ticket_numbers(ticket)))]
    for key, label in (("top", "Top"), ("middle", "Middle"), ("bottom", "Bottom")):
        parts.append("{} {}/{}".format(label, len(set(ticket[LINES[key]]) & marked), len(ticket[LINES[key]])))
    return "  ·  ".join(parts)


def parse_prizes(value):
    """The prizes in play from a comma separated list; unknown names are ignored, blank means all."""
    wanted = [w.strip().lower() for w in re.split(r"[,\s]+", str(value or "")) if w.strip()]
    keys = unique(PRIZE_ALIASES.get(w.replace("_", "").replace("-", "")) for w in wanted)
    keys = [k for k in PRIZE_KEYS if k in keys]
    return keys or list(PRIZE_KEYS)


def new_seed():
    return random.SystemRandom().getrandbits(48)


# --------------------------------------------------------------------------
# The game as the step holds it, and how it travels in a button
# --------------------------------------------------------------------------

VALUE_PREFIX = "tb"               # tb|<kind>|<game>|<arg>      a real game: the state is in the table
TEST_PREFIX = "tbt"               # tbt|<kind>|<json>           a test game: points at the message that holds it
ACTION_PREFIX = "tambola_click_"
PICK_ACTION = ACTION_PREFIX + "pick_"
SIZE_ACTION = ACTION_PREFIX + "size"
BOARD_ACTION = ACTION_PREFIX + "board"
LAYOUT_ACTION = ACTION_PREFIX + "layout"
WINNERS_ACTION = ACTION_PREFIX + "winners"
BLANK_ACTION = ACTION_PREFIX + "blank_"
MENUS = ("size", "board", "layout", "winners")    # the setup card's dropdowns in the order they are drawn, named
MENU_ACTION = {"size": SIZE_ACTION, "board": BOARD_ACTION, "layout": LAYOUT_ACTION, "winners": WINNERS_ACTION}
MENU_OF_ACTION = {action: kind for kind, action in MENU_ACTION.items()}
MENU_PARSE = {"size": parse_size, "board": parse_board_style, "layout": parse_layout, "winners": parse_winners}
HARD_MAX_PLAYERS = 100
LOBBY_KINDS = ("join", "start", "cancel", "pick")      # these belong to the lobby message; the rest, to the board
LIVE = (RUNNING, PAUSED)          # numbers are being called: a ticket can be marked
ACTIVE = (LOBBY, STARTING, RUNNING, PAUSED)
CARRIER = "tb"                    # the block ids of a test game's messages start with this
CARRIER_CHUNK = 240               # characters of the game in one block id (Slack allows 255)


def game_config(input):
    """The settings a game keeps for its whole life, read from the typed-word recipe's inputs. `size` is only the
    size the setup card's dropdown starts on: the organizer chooses on the card."""
    announce = str(input.get("announce") or "").strip().lower()
    return {
        "prizes": parse_prizes(input.get("prizes")),
        "announce": announce if announce in ANNOUNCE else ANNOUNCE[0],
        "cols": _int(input.get("board_columns"), BOARD_COLUMNS, 3, 10),
        "max": _int(input.get("max_players"), MAX_PLAYERS, 1, HARD_MAX_PLAYERS),
        "size": parse_size(input.get("size")),
        "top": _int(input.get("top_n"), REVIEW_PLAYERS, 1, REVIEW_PLAYERS_MAX),
        "board": parse_board_style(input.get("board_style")),
        "layout": parse_layout(input.get("ticket_layout")),
        "winners": parse_winners(input.get("winners_style")),
    }


def cfg_list(cfg):
    """The settings as the short list a game saves and a button carries. Anything at its usual value is left blank (a
    blank reads as the usual value), which keeps what a dropdown's option carries inside Slack's 150 characters. The
    layout is always written: a game saved without one is read as compact, which is what it was dealt."""
    prizes, top = list(cfg["prizes"]), cfg.get("top", REVIEW_PLAYERS)
    return [",".join(prizes) if prizes != list(PRIZE_KEYS) else "",
            "" if cfg["announce"] == ANNOUNCE[0] else cfg["announce"],
            "" if cfg["cols"] == BOARD_COLUMNS else cfg["cols"],
            "" if cfg["max"] == MAX_PLAYERS else cfg["max"],
            parse_size(cfg.get("size")),
            "" if top == REVIEW_PLAYERS else top,
            parse_board_style(cfg.get("board")),
            parse_layout(cfg.get("layout")),
            parse_winners(cfg.get("winners"))]


def cfg_from(raw):
    """The settings back from what a game saved. A game saved before sizes, top_n, board styles, layouts or winners
    styles existed has fewer, and plays as it always did: a large game, ten players on the review, the emoji board,
    compact tickets (the layout of the tickets it has already dealt) and the names of the winners."""
    raw = list(raw) if isinstance(raw, (list, tuple)) else []
    raw += [""] * (9 - len(raw))
    return {"prizes": parse_prizes(raw[0]),
            "announce": raw[1] if raw[1] in ANNOUNCE else ANNOUNCE[0],
            "cols": _int(raw[2], BOARD_COLUMNS, 3, 10),
            "max": _int(raw[3], MAX_PLAYERS, 1, HARD_MAX_PLAYERS),
            "size": parse_size(raw[4]),
            "top": _int(raw[5], REVIEW_PLAYERS, 1, REVIEW_PLAYERS_MAX),
            "board": parse_board_style(raw[6]),
            "layout": parse_layout(raw[7], LEGACY_LAYOUT),
            "winners": parse_winners(raw[8])}


def game_id_for(channel, message_ts):
    """One typed word is one game: the same press twice finds the same game."""
    return "tb_{}_{}".format(channel, str(message_ts).replace(".", ""))


def new_game(game_id, channel, host, word, cfg, test):
    return {
        "id": game_id, "channel": channel, "host": host, "host_name": "", "mode": "", "word": word,
        "status": LOBBY, "seed": 0, "n": 0,
        "roster": [],                  # who is playing (in the lobby: who is in so far). The host is always in
        "names": {},                   # their names, while the lobby needs them
        "total": 0,                    # "Everyone in this channel": how many people that is
        "wins": {},                    # prize -> {uid, name, ts}
        "cfg": dict(cfg), "lobby_ts": "", "board_ts": "", "picked_ts": "", "test": bool(test),
        "claim": "",                   # the click time of the press that is starting the game
        "last_next": 0.0,              # the click time of the last Next number, to catch a press made twice
        "host_mask": None,             # [test game] the numbers marked on the organizer's card, as their note has them
    }


def state_dict(g, wins=True):
    """The game as a small dict: what a test game keeps in its message and a real one in its row."""
    state = {"g": g["id"], "c": g["channel"], "h": g["host"], "hn": g["host_name"][:NAME_MAX],
             "m": g["mode"], "w": g["word"], "s": g["status"], "d": g["seed"], "n": g["n"],
             "r": g["roster"], "t": g["total"], "l": g["lobby_ts"], "b": g["board_ts"],
             "k": g["picked_ts"], "f": cfg_list(g["cfg"])}
    if g["claim"]:
        state["q"] = g["claim"]
    if g["last_next"]:
        state["u"] = g["last_next"]
    names = {u: g["names"][u][:NAME_MAX] for u in g["roster"] if g["names"].get(u)}
    if names and g["status"] in (LOBBY, STARTING):
        state["p"] = names
    if wins and g["wins"]:
        state["x"] = [[k, w["uid"], w["name"][:NAME_MAX], w["ts"]] for k, w in g["wins"].items()]
    return state


def game_from_state(state, test):
    state = state if isinstance(state, dict) else {}
    g = new_game(str(state.get("g") or ""), str(state.get("c") or ""), str(state.get("h") or ""),
                 str(state.get("w") or "Tambola"), cfg_from(state.get("f")), test)
    g.update(host_name=str(state.get("hn") or ""), mode=str(state.get("m") or ""),
             status=str(state.get("s") or LOBBY), seed=_int(state.get("d"), 0, 0, 1 << 62),
             n=_int(state.get("n"), 0, 0, numbers_of(g)), total=_int(state.get("t"), 0, 0, 1 << 30),
             lobby_ts=str(state.get("l") or ""), board_ts=str(state.get("b") or ""),
             picked_ts=str(state.get("k") or ""), claim=str(state.get("q") or ""),
             last_next=as_ts(state.get("u")))
    g["roster"] = unique(str(u) for u in (state.get("r") or []))
    g["names"] = {str(u): str(n) for u, n in (state.get("p") or {}).items()}
    for item in state.get("x") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 4 and item[0] in PRIZE_KEYS:
            g["wins"][item[0]] = {"uid": str(item[1]), "name": str(item[2]), "ts": str(item[3])}
    return g


def carry(blocks, g):
    """A test game has no table, so the public message holds the game itself, in its block ids (which nobody
    sees). The controls are private notes, so they carry only a pointer to that message. Every block gets an
    id: the first few hold the game, packed small, and the rest are just numbered."""
    if not g["test"]:
        return blocks
    packed = base64.urlsafe_b64encode(zlib.compress(
        json.dumps(state_dict(g), separators=(",", ":")).encode("utf-8"))).decode("ascii")
    chunks = [packed[i:i + CARRIER_CHUNK] for i in range(0, len(packed), CARRIER_CHUNK)]
    if len(chunks) > len(blocks):
        raise ValueError("this test game is too big to keep in its message")
    for index, block in enumerate(blocks):
        block["block_id"] = ("{}{:02d}{}".format(CARRIER, index, chunks[index]) if index < len(chunks)
                             else "{}x{:02d}".format(CARRIER, index))
    return blocks


def carried_state(message):
    """The game a test game's message holds, or None."""
    parts = {}
    for block in (message or {}).get("blocks") or []:
        found = re.match(r"^" + CARRIER + r"(\d\d)([A-Za-z0-9_=-]+)$", str(block.get("block_id") or ""))
        if found:
            parts[int(found.group(1))] = found.group(2)
    if not parts:
        return None
    try:
        packed = "".join(parts[i] for i in sorted(parts))
        state = json.loads(zlib.decompress(base64.urlsafe_b64decode(packed.encode("ascii"))).decode("utf-8"))
    except Exception:                                              # noqa: BLE001
        return None
    return state if isinstance(state, dict) else None


def value_for(kind, g, arg="", mask=None):
    """The value of one of this game's buttons: a pointer into the table, or for a test game a pointer to the
    message that holds the game (the lobby for the lobby's buttons, the board for the rest). A test game has no row
    to keep the numbers marked on the organizer's card in, so the buttons of their note carry them (`mask`)."""
    if g["test"]:
        pointer = {"g": g["id"], "c": g["channel"], "a": str(arg)}
        mask = g["host_mask"] if mask is None else mask
        if mask is not None:
            pointer["k"] = mask
        ts = g["lobby_ts"] if kind in LOBBY_KINDS else g["board_ts"]
        if ts and kind != "join":                                  # Join is on the lobby: the press says which
            pointer["m"] = ts
        return "{}|{}|{}".format(TEST_PREFIX, kind, json.dumps(pointer, separators=(",", ":")))
    return "|".join((VALUE_PREFIX, kind, g["id"], str(arg)))


def set_value(g, mode):
    """A choice on the setup card. The game does not exist yet, so the choice carries its settings."""
    if g["test"]:
        state = state_dict(dict(g, mode=mode))
        state["a"] = mode
        return "{}|set|{}".format(TEST_PREFIX, json.dumps(state, separators=(",", ":")))
    return "|".join((VALUE_PREFIX, "set", g["id"], json.dumps(
        {"m": mode, "w": g["word"], "f": cfg_list(g["cfg"])}, separators=(",", ":"))))


def mark_value(g, ticket, marks, number):
    """A number on a ticket. A test ticket carries itself, the numbers marked so far and where the board is,
    so it can still be answered when the board cannot be read."""
    if g["test"]:
        return "{}|mark|{}".format(TEST_PREFIX, json.dumps(
            {"g": g["id"], "c": g["channel"], "m": g["board_ts"], "k": mask_of(ticket, marks),
             "a": str(number), "w": g["word"], "hn": g["host_name"][:NAME_MAX],
             "t": ticket_numbers(ticket)}, separators=(",", ":")))
    return value_for("mark", g, number)


def parse_value(value, action_id=""):
    """What a press is: {kind, test, game, arg, state}, or None when it is not this game's."""
    action_id = str(action_id or "").strip()
    if action_id in MENU_ACTION.values():                  # a setup dropdown: no value, its choice carries the rest
        return {"kind": "menu", "test": False, "game": "", "arg": action_id, "state": None}
    if action_id.startswith(PICK_ACTION):                  # the player menu has no value: the game is in its id
        rest = action_id[len(PICK_ACTION):]
        if rest.startswith("t:"):
            _t, channel, ts = (rest.split(":", 2) + ["", ""])[:3]
            return {"kind": "pick", "test": True, "game": "", "arg": "", "state": {"c": channel, "m": ts}}
        return {"kind": "pick", "test": False, "game": rest, "arg": "", "state": None}
    value = str(value or "").strip()
    if value.startswith(TEST_PREFIX + "|"):
        parts = value.split("|", 2)
        try:
            state = json.loads(parts[2]) if len(parts) == 3 else None
        except ValueError:
            state = None
        if not isinstance(state, dict):
            return None
        return {"kind": parts[1], "test": True, "game": str(state.get("g") or ""),
                "arg": str(state.get("a") or ""), "state": state}
    if value.startswith(VALUE_PREFIX + "|"):
        parts = value.split("|", 3)
        if len(parts) < 3 or not parts[2]:
            return None
        return {"kind": parts[1], "test": False, "game": parts[2],
                "arg": parts[3] if len(parts) > 3 else "", "state": None}
    return None


# --------------------------------------------------------------------------
# The cards
# --------------------------------------------------------------------------

def _mrkdwn(text):
    return {"type": "mrkdwn", "text": text}


def _section(text="", fields=None):
    block = {"type": "section"}
    if text:
        block["text"] = _mrkdwn(text)
    if fields:
        block["fields"] = [_mrkdwn(f) for f in fields]
    return block


def _context(text):
    return {"type": "context", "elements": [_mrkdwn(text)]}


def _header(text):
    return {"type": "header", "text": {"type": "plain_text", "text": text[:150], "emoji": True}}


def _button(text, action_id, value, style=None, confirm=None):
    button = {"type": "button", "text": {"type": "plain_text", "text": text[:BUTTON_MAX], "emoji": True},
              "action_id": action_id, "value": value}
    if style:
        button["style"] = style
    if confirm:
        button["confirm"] = {"title": {"type": "plain_text", "text": "Are you sure?"},
                             "text": {"type": "plain_text", "text": confirm},
                             "confirm": {"type": "plain_text", "text": "Yes"},
                             "deny": {"type": "plain_text", "text": "No"}}
    return button


def _actions(buttons):
    return {"type": "actions", "elements": buttons}


def blank_button(row, column):
    """A blank square of a printed ticket. Slack has no inert button, so it is a quiet one: its press is read as a test
    game's (no table, no game to look up) and does nothing."""
    return _button(BLANK_TEXT, "{}{}_{}".format(BLANK_ACTION, row, column), TEST_PREFIX + "|blank|{}")


def ticket_rows(g, ticket, marks, make):
    """A ticket as rows of buttons, in the game's layout: `make(number, marked)` is a number's button, a blank square
    is a quiet one."""
    marks = set(marks)
    return [_actions([make(number, number in marks) if number else blank_button(r, c)
                      for c, number in enumerate(cells)])
            for r, cells in enumerate(ticket_cells(g, ticket))]


def host_name_of(g):
    return esc(g["host_name"] or ANONYMOUS)


def typed_word(g):
    """The word that starts this game, as people type it: itambola, ihousie."""
    return "i" + g["word"].lower()


def prizes_line(g):
    return "*Prizes:*  " + "  ·  ".join(PRIZE_NAME[k] for k in PRIZE_KEYS if k in g["cfg"]["prizes"])


def choice_value(g, key):
    """What the option for `key` carries back when it is chosen on a setup dropdown. A dropdown has no button value,
    and nothing exists to look the setup up in yet (the card is a private note, and the game is only made when the
    organizer chooses how people join), so each option holds what is needed to draw the card again: the game's id (its
    channel is the press's), the settings, the word when it is not Tambola, and whether it is a test game. Kept short:
    Slack allows 150 characters."""
    value = {"s": key, "m": g["id"].rsplit("_", 1)[-1], "f": cfg_list(g["cfg"])}
    if g["word"] != "Tambola":
        value["w"] = g["word"]
    if g["test"]:
        value["t"] = 1
    return json.dumps(value, separators=(",", ":"))


def menu_choices(kind):
    """[(key, what its option says)] of the setup dropdown `kind`, in the order it lists them: sizes smallest first."""
    if kind == "size":
        return [(key, SIZE_OPTION.format(label=SIZES[key]["label"],
                                         tag=" ({})".format(SIZES[key]["tag"]) if SIZES[key]["tag"] else "",
                                         numbers=SIZES[key]["numbers"], ticket=TICKET_ROWS * SIZES[key]["row"]))
                for key in sorted(SIZES, key=lambda k: SIZES[k]["numbers"])]
    if kind == "board":
        return [(key, BOARD_OPTION.format(label=spec["label"], text=spec["text"]))
                for key, spec in BOARD_STYLES.items()]
    if kind == "layout":
        return [(key, LAYOUT_OPTION.format(label=spec["label"], text=spec["text"])) for key, spec in LAYOUTS.items()]
    return [(key, WINNERS_OPTION.format(label=spec["label"], text=spec["text"]))
            for key, spec in WINNERS_STYLES.items()]


def setting_menu(g, kind):
    """A dropdown of the setup card, standing on the game's current setting. Choosing one draws the card again with it
    (click_menu), and from then on every choice of how people join carries it."""
    choices = menu_choices(kind)
    keys = [key for key, _text in choices]
    options = [{"text": {"type": "plain_text", "text": text[:75]}, "value": choice_value(g, key)}
               for key, text in choices]
    current = MENU_PARSE[kind](g["cfg"].get(kind))
    return {"type": "static_select", "action_id": MENU_ACTION[kind],
            "placeholder": {"type": "plain_text", "text": MENU_PLACEHOLDER[kind]}, "options": options,
            "initial_option": options[keys.index(current)]}


def setup_blocks(g):
    """The card only the person who typed the word sees: the game's size, the board's style and the tickets' layout on
    dropdowns, then how people join."""
    blocks = [_section(SETUP_TEXT.format(word=g["word"]))]
    blocks += [dict(_section(SETUP_MENU[kind]), accessory=setting_menu(g, kind)) for kind in MENUS]
    blocks += [
        _actions([_button(MODE_BUTTONS[m], ACTION_PREFIX + "set_" + m, set_value(g, m),
                          "primary" if m == "all" else None) for m in MODES]),
        _context(SETUP_NOTE),
    ]
    if g["test"]:
        blocks.append(_context(TEST_NOTE))
    return blocks


def players_line(g):
    people = [g["names"].get(u) or ANONYMOUS for u in g["roster"]]
    return LOBBY_PLAYERS.format(count=len(people), names=names_text(people))


def lobby_blocks(g):
    """The lobby everyone sees: short rules, the prizes, who is in. The only button is Join, and only on a game
    anyone may join; Start and Cancel are the organizer's, in a private note."""
    host = host_name_of(g)
    count = ""
    if g["mode"] == "all" and g["total"]:
        count = " (about {} people)".format(g["total"]) if g["total"] > 1 else " (just {})".format(host)
    blocks = [
        _header(":tickets: " + g["word"]),
        _section(LOBBY_HOST.format(host=host, size=size_note(g)) + "\n"
                 + LOBBY_MODE_LINE[g["mode"]].format(host=host, count=count)),
        _section(rules_text(g)),
        _context(prizes_line(g)),
    ]
    if g["mode"] != "all":
        blocks.append(_context(players_line(g)))
    if g["mode"] == "open":
        blocks.append(_actions([_button(JOIN_TEXT, ACTION_PREFIX + "join", value_for("join", g), "primary")]))
    if g["test"]:
        blocks.append(_context(TEST_NOTE))
    return carry(blocks, g)


def lobby_closed_blocks(g, text, title=True):
    """The lobby once the game has started or been cancelled: no button, and nothing the board says again (the board
    below has the title and the prizes). A started game's lobby is just a line and who is in: the title, :tickets:
    and the word, belong to the board that follows it; a cancelled game has no board, so it keeps its own."""
    blocks = ([_header(":tickets: " + g["word"])] if title else []) + [_section(text)]
    if g["roster"]:
        blocks.append(_context(players_line(g)))
    if g["test"]:
        blocks.append(_context(TEST_NOTE))
    return carry(blocks, g)


def menu_element(g, options=None, bare=False, people=False):
    """The organizer's menu of people, as a Block Kit element. It names the game in its action id: a menu has no value.
    `options`, [(user id, name)], is the channel's own list of people (menu_options), the organizer among them and
    already chosen; without it, or with `people`, the menu is Slack's people picker, which searches everyone in the
    workspace. `bare` leaves off the optional settings (who is chosen to begin with), for when the full menu is turned
    down. There is no cap on how many can be chosen here: the game keeps at most max_players of them."""
    action_id = PICK_ACTION + ("t:{}:{}".format(g["channel"], g["lobby_ts"]) if g["test"] else g["id"])
    placeholder = {"type": "plain_text", "text": PICK_PLACEHOLDER}
    cap = g["cfg"]["max"]
    if options and not people:
        listed = [{"text": {"type": "plain_text", "text": (name or ANONYMOUS)[:75]}, "value": uid}
                  for uid, name in options]
        menu = {"type": "multi_static_select", "action_id": action_id, "placeholder": placeholder,
                "options": listed}
        chosen = [o for o in listed if o["value"] in g["roster"]]
        if chosen and not bare:
            menu["initial_options"] = chosen[:cap]
        return menu
    menu = {"type": "multi_users_select", "action_id": action_id, "placeholder": placeholder}
    initial = [u for u in g["roster"] if u != g["host"]]
    if initial and not bare:
        menu["initial_users"] = initial[:cap]
    return menu


def panel_status_line(g):
    """What the organizer's note says about the game: the number just called while it runs, the pause while it is
    paused. It is redrawn on every press, so it is the organizer's own small scoreboard."""
    called = called_list(g) if g["seed"] else []
    if g["status"] == PAUSED:
        return PANEL_PAUSED_LINE.format(called=len(called), numbers=numbers_of(g))
    if not called:
        return PANEL_NO_NUMBER
    last = called[-1]
    said = number_words(last) + (", " + CALLS[last].lower() if last in CALLS else "")
    return PANEL_LAST.format(number=last, said=said, called=len(called), numbers=numbers_of(g))


def card_blocks(g, ticket, marks):
    """The organizer's own card as part of their note: the same three rows of five as a ticket in a private message,
    but tapped here, so they need not leave the channel."""
    marks = set(marks)
    mask = mask_of(ticket, marks)
    blocks = [_context(CARD_HEAD)]
    blocks += ticket_rows(g, ticket, marks, lambda number, marked: _button(
        (":white_check_mark: " if marked else "") + str(number), ACTION_PREFIX + "hmark_{}".format(number),
        value_for("hmark", g, number, mask), "primary" if marked else None))
    blocks.append(_context(progress_line(ticket, marks)))
    return blocks


def plain_button(button):
    """A button without its style or its confirmation: the plainest form."""
    return {k: v for k, v in button.items() if k not in ("style", "confirm")}


def panel_blocks(g, note="", mine=None, menu=None, form="full"):
    """The organizer's controls. They are a private note, so nobody else sees a button. `note` goes on top when
    there is something to tell: a press that could not be done, tickets that could not be sent. `mine` is the
    organizer's own card, (ticket, marks), when they have opened it in the note; every button of the note then
    says so ("t"), so the next press draws it again. `form` is how plain to make it: full, or one of the forms
    panel_variants falls back on (bare, people and none for the player menu, minimal for the buttons)."""
    status = g["status"]
    blocks = [_section(note)] if note else []
    hint = ""
    arg = "t" if mine else ""
    mask = mask_of(*mine) if mine else None
    card_button = _button(HIDE_CARD_TEXT if mine else SHOW_CARD_TEXT, ACTION_PREFIX + "myticket",
                          value_for("ticket", g, arg, mask))
    if status in (LOBBY, STARTING):
        words = (PANEL_LOBBY_PICK if g["mode"] == "pick" else PANEL_LOBBY).format(word=g["word"])
        if g["mode"] == "pick" and form == "none":
            words += PANEL_NO_MENU.format(word=typed_word(g))
        head = _section(words)
        if g["mode"] == "pick" and form in ("bare", "people"):     # the menu beside the words, as Slack's examples
            head["accessory"] = menu_element(g, menu, bare=True, people=form == "people")
        blocks.append(head)
        if g["mode"] == "pick" and form == "full":
            blocks.append(_actions([menu_element(g, menu)]))
        buttons = [_button(START_TEXT, ACTION_PREFIX + "start", value_for("start", g), "primary"),
                   _button(CANCEL_TEXT, ACTION_PREFIX + "cancel", value_for("cancel", g))]
    elif status == PAUSED:
        blocks += [_section(PANEL_HEAD)] + ([] if form == "minimal" else [_section(panel_status_line(g))])
        buttons = [_button(RESUME_TEXT, ACTION_PREFIX + "resume", value_for("resume", g, arg, mask), "primary"),
                   card_button,
                   _button(END_TEXT, ACTION_PREFIX + "end", value_for("end", g, arg, mask), confirm=END_CONFIRM)]
        hint = PANEL_HINT_PAUSED
    else:
        blocks += [_section(PANEL_HEAD)] + ([] if form == "minimal" else [_section(panel_status_line(g))])
        buttons = [_button(NEXT_TEXT, ACTION_PREFIX + "next", value_for("next", g, arg, mask), "primary"),
                   _button(REVIEW_TEXT, ACTION_PREFIX + "review", value_for("review", g, arg, mask)),
                   card_button,
                   _button(END_TEXT, ACTION_PREFIX + "end", value_for("end", g, arg, mask), confirm=END_CONFIRM)]
        hint = PANEL_HINT_RUNNING
    if form == "minimal":
        buttons = [plain_button(b) for b in buttons]
        mine = hint = None
    blocks.append(_actions(buttons))
    if mine and status in LIVE:
        blocks += card_blocks(g, *mine)
    elif hint:
        blocks.append(_context(hint))
    if g["test"]:
        blocks.append(_context(TEST_NOTE))
    return blocks


def panel_variants(g, note="", mine=None, menu=None):
    """The organizer's controls as they are meant to look, then plainer forms to fall back on should Slack turn the
    first down (the reason is in the job's warnings, and in the note if nothing else goes): for a picked lobby the
    menu stripped to what Slack needs and set beside the words, then Slack's people picker, then no menu at all; for
    everything else, plain buttons."""
    forms = ["full"]
    if g["status"] in (LOBBY, STARTING) and g["mode"] == "pick":
        forms += ["bare", "people", "none"]
    else:
        forms.append("minimal")
    return [panel_blocks(g, note, mine, menu, form) for form in forms]


def prize_fields(g, closest=None):
    """The prizes as two columns: who holds each, or that it is open (and, on the review, who is closest)."""
    fields = []
    for key, name, icon, _how in PRIZES:
        if key not in g["cfg"]["prizes"]:
            continue
        win = g["wins"].get(key)
        if win:
            who = esc(win["name"] or ANONYMOUS)
        elif closest and closest.get(key) and closest[key][0]:
            best, need, names = closest[key]
            who = "_open  ·  closest: {} ({} of {})_".format(names_text(names, 2), best, need)
        elif closest and key in closest:
            who = "_open  ·  nobody yet_"
        else:
            who = "_open_"
        fields.append("*{} {}*\n{}".format(icon, name, who))
    return fields


def winner_card(key, win):
    """One winner as a card of the carousel: the prize, who won it, what it took, and their profile picture as the
    card's picture when there is one (a card without one is still a card)."""
    name = win["name"] or ANONYMOUS
    card = {"type": "card",
            "title": _mrkdwn("{} *{}*".format(PRIZE_ICON[key], PRIZE_NAME[key])[:CARD_LIMIT]),
            "subtitle": _mrkdwn(esc(name)[:CARD_LIMIT]),
            "body": _mrkdwn(WINNER_BODY[key])}
    if win.get("img"):
        card["hero_image"] = {"type": "image", "image_url": win["img"],
                              "alt_text": "{}, winner of the {}".format(name, PRIZE_NAME[key])}
    return card


def winners_strip(won):
    """The winners as one line of small pictures, each with the prize and the name beside it. A context block holds ten
    elements, which five winners with a picture each just fill."""
    elements = []
    for key, win in won:
        if win.get("img"):
            elements.append({"type": "image", "image_url": win["img"],
                             "alt_text": "{}, winner of the {}".format(win["name"] or ANONYMOUS, PRIZE_NAME[key])})
        elements.append(_mrkdwn("*{}* {}".format(PRIZE_NAME[key], esc(win["name"] or ANONYMOUS))))
    return {"type": "context", "elements": elements[:10]}


def winners_blocks(g):
    """Who has won what, in the board's winners style (see WINNERS_STYLES). The photo styles put the first winner on the
    right and each new one to the left of it, so the newest is the first thing seen; the prizes still to win are named
    in a line under them."""
    style = parse_winners(g["cfg"].get("winners"))
    if style == "none":
        return []
    if style == "names":
        fields = prize_fields(g)
        return [_section(fields=fields)] if fields else []
    held = [(key, g["wins"][key]) for key in PRIZE_KEYS if key in g["cfg"]["prizes"] and key in g["wins"]]
    won = sorted(held, key=lambda item: (as_ts(item[1]["ts"]), PRIZE_KEYS.index(item[0])), reverse=True)
    blocks = []
    if won and style == "carousel":
        blocks.append({"type": "carousel", "elements": [winner_card(key, win) for key, win in won]})
    elif won:
        blocks.append(winners_strip(won))
    open_prizes = [PRIZE_NAME[k] for k in PRIZE_KEYS if k in g["cfg"]["prizes"] and k not in g["wins"]]
    if open_prizes:
        blocks.append(_context(STILL_TO_WIN.format(prizes="  \u00b7  ".join(open_prizes))))
    return blocks


def board_foot(g, over=False):
    """The board's last line. While the game is on it says how a player gets a lost ticket back (typing the word
    sends it again to someone who is playing; to anyone else it opens a new game, which is why a game that is over
    does not say it)."""
    line = BOARD_FOOT.format(host=host_name_of(g), count=len(g["roster"]), players=plural(len(g["roster"]), "player"))
    if not over and g["status"] in LIVE:
        line += BOARD_FOOT_LOST.format(word=typed_word(g))
    return line


def board_blocks(g, over=""):
    """The board everyone sees: the number just called, the grid, the prizes. No button on it. `over` is the
    closing line of a game that has ended."""
    called = called_list(g)
    style = parse_board_style(g["cfg"].get("board"))
    blocks = [_header(":tickets: " + g["word"])]
    if over:
        blocks.append(_section(over))
    elif called:
        blocks.append(_section(call_lines(called[-1], style)))
    else:
        blocks.append(_section(BOARD_READY))
    earlier = (called if over else called[:-1])[-RECENT_CALLS:][::-1]
    bits = ["*{}* of {} called".format(len(called), numbers_of(g))]
    if earlier:
        bits.append("Earlier: " + "  ·  ".join(str(n) for n in earlier))
    blocks.append(_context("  ·  ".join(bits)))
    if style == "numbers":
        blocks.append(_section(number_grid(called, g["cfg"]["cols"], numbers_of(g))))
    elif style == "list":
        if called:
            blocks.append(_section(BOARD_CALLED + called_lines(called)))
    else:
        blocks += [_section(row) for row in board_rows(called, g["cfg"]["cols"], numbers_of(g))]
    blocks += winners_blocks(g)
    blocks.append(_context(board_foot(g, bool(over)) + ("  ·  " + TEST_NOTE if g["test"] else "")))
    return carry(blocks, g)


def prize_count(key, ticket, marks):
    """How far a ticket is towards a prize: the numbers it has marked that count for it."""
    marked = set(marks) & set(ticket_numbers(ticket))
    if key in LINES:
        return len(set(ticket[LINES[key]]) & marked)
    return len(marked)


def review_stats(g, players):
    """What the review shows, from the players who have a ticket: [{name, ticket, marks}]. None (a test game
    has no rows to read) leaves the player figures out."""
    called = sorted(called_list(g))
    stats = {"called": called, "players": None, "holders": {}, "closest": {}, "spread": [], "ranked": []}
    if players is None:
        return stats
    ticket_size, row_size = ticket_size_of(g), row_size_of(g)
    stats["players"] = len(players)
    stats["holders"] = {n: sum(1 for p in players if n in ticket_numbers(p["ticket"])) for n in called}
    stats["ranked"] = sorted(players, key=lambda p: (-len(p["marks"]), p["name"].lower()))
    for key in g["cfg"]["prizes"]:
        if key in g["wins"]:
            continue
        need = EARLY_COUNT if key == "early5" else (ticket_size if key == "full" else row_size)
        scored = [(prize_count(key, p["ticket"], p["marks"]), p["name"]) for p in players]
        best = max([s for s, _name in scored] or [0])
        stats["closest"][key] = (best, need, sorted(n for s, n in scored if s == best) if best else [])
    stats["spread"] = [sum(1 for p in players if lo <= len(p["marks"]) <= hi) for lo, hi in spread_buckets(ticket_size)]
    return stats


def text_bar(marked, width):
    """A player's progress as plain characters, which line up in a code block: one cell for each number on a ticket."""
    marked = max(0, min(width, marked))
    return "\u2588" * marked + "\u2591" * (width - marked)


def rank_texts(ranked):
    """The rank of each player in a list sorted by numbers marked, most first: competition ranking, 1, 2, 2, 4. Equal
    counts share a rank and are marked tied, T2, as the leaderboard does."""
    ranks, previous, rank = [], None, 0
    for place, player in enumerate(ranked, start=1):
        if len(player["marks"]) != previous:
            rank, previous = place, len(player["marks"])
        ranks.append(rank)
    return ["{}{}".format("T" if ranks.count(rank) > 1 else "", rank) for rank in ranks]


def review_table(g, ranked, top):
    """The top `top` players as a table in a code block, as the leaderboard shows its rows (#, name, numbers marked,
    a bar), however many people are playing. Returned as section blocks, split so none passes Slack's limit."""
    ticket_size = ticket_size_of(g)
    shown = list(zip(rank_texts(ranked)[:top], ranked[:top]))
    rank_width = max([2] + [len(rank) for rank, _player in shown])
    head = "{}  {}  {}  {}".format("#".rjust(rank_width), "name".ljust(REVIEW_NAME_WIDTH), "marked".rjust(6),
                                   "progress")
    lines = []
    for rank, player in shown:
        name = player["name"] or ANONYMOUS
        name = name if len(name) <= REVIEW_NAME_WIDTH else name[:REVIEW_NAME_WIDTH - 1] + "."
        marked = len(player["marks"])
        # padded first, escaped after: Slack decodes &amp; back to one character, so the columns still line up
        lines.append(esc("{}  {}  {}  {}".format(rank.rjust(rank_width), name.ljust(REVIEW_NAME_WIDTH),
                                                "{}/{}".format(marked, ticket_size).rjust(6),
                                                text_bar(marked, ticket_size))))
    chunks, current, size = [], [], len(head)
    for line in lines:
        if current and size + len(line) + 1 > REVIEW_SECTION_LIMIT:
            chunks.append(current)
            current, size = [], len(head)
        current.append(line)
        size += len(line) + 1
    chunks.append(current)
    return [_section("```\n" + "\n".join([head] + chunk) + "\n```") for chunk in chunks]


def review_blocks(g, stats):
    """The review, which takes the board's place for everyone while the game is paused: the numbers called (and
    how many players hold each), who holds or is closest to each prize, and the top of the ranking of players by
    numbers marked (top_n of them, ten by default, not every player: a hundred players is still one short table)."""
    called, total = stats["called"], len(g["roster"])
    won = len([k for k in g["cfg"]["prizes"] if k in g["wins"]])
    blocks = [_header(REVIEW_HEAD.format(word=g["word"])),
              _section(REVIEW_PAUSED.format(host=host_name_of(g))),
              _context(REVIEW_COUNTS.format(called=len(called), numbers=numbers_of(g), players=total,
                                            playerword=plural(total, "player"), won=won,
                                            total=len(g["cfg"]["prizes"]))),
              _section(REVIEW_CALLED)]
    if called:
        items = ["{} ({})".format(n, stats["holders"][n]) if stats["players"] is not None else str(n) for n in called]
        blocks += [_context("  ·  ".join(items[i:i + REVIEW_LINE])) for i in range(0, len(items), REVIEW_LINE)]
    else:
        blocks.append(_context(REVIEW_NONE_CALLED))
    fields = prize_fields(g, stats["closest"])
    if fields:
        blocks.append(_section(fields=fields))
    if stats["players"] is None:
        blocks.append(_context(REVIEW_TEST))
    elif stats["ranked"]:
        ranked, top = stats["ranked"], g["cfg"].get("top", REVIEW_PLAYERS)
        blocks.append(_section(REVIEW_TOP_HEAD.format(top=top, total=len(ranked)) if len(ranked) > top
                               else REVIEW_PLAYERS_HEAD))
        blocks += review_table(g, ranked, top)
        rest = ranked[top:]
        if rest:
            blocks.append(_context(REVIEW_MORE.format(count=len(rest), playerword=plural(len(rest), "player"),
                                                      best=len(rest[0]["marks"]))))
        blocks.append(_context(REVIEW_SPREAD.format(spread="  ·  ".join(
            "{}-{}: {}".format(lo, hi, n) if lo != hi else "{}: {}".format(lo, n)
            for (lo, hi), n in zip(spread_buckets(ticket_size_of(g)), stats["spread"])))))
    return carry(blocks, g)


def ticket_blocks(g, ticket, marks, note="", over=False):
    """A player's ticket: three rows, each number a button, laid out as the game's ticket layout says; a marked one is
    green with a tick."""
    marks = set(marks)
    where = TICKET_WHERE.format(channel=g["channel"], host=host_name_of(g))
    if parse_layout(g["cfg"].get("layout")) == "printed" and layout_columns(numbers_of(g)) > row_size_of(g):
        where += "\n" + TICKET_COLUMNS.format(columns=column_names(numbers_of(g)))
    blocks = [_section(TICKET_HEAD.format(word=g["word"])), _context(where)]
    blocks += ticket_rows(g, ticket, marks, lambda number, marked: _button(
        (":white_check_mark: " if marked else "") + str(number), ACTION_PREFIX + "mark_{}".format(number),
        mark_value(g, ticket, marks, number), "primary" if marked else None))
    lines = [note] if note else []
    lines.append(TICKET_OVER if over else progress_line(ticket, marks))
    blocks.append(_context("\n".join(lines)))
    if g["test"]:
        blocks.append(_context(TEST_NOTE))
    return blocks


def win_text(g, key, name, ticket):
    name = esc(name or ANONYMOUS)
    if key == "full":
        return ":trophy: *Full House!* *{}* has the whole ticket. That is the game.".format(name)
    if key == "early5":
        return ":zap: *Early Five* goes to *{}*!".format(name)
    numbers = "  ·  ".join(str(n) for n in ticket[LINES[key]]) if ticket else ""
    return ":tada: *{}* goes to *{}*!{}".format(PRIZE_NAME[key], name, "\n_{}_".format(numbers) if numbers else "")


def win_blocks(g, key, name, ticket, banner=""):
    """The announcement of a prize, bigger for a bigger prize (see PRIZE_TIER): Early Five a single line; a line a
    header and a line of emojis either side of the winner's name and the numbers that made it; Full House a header, two
    rows of emojis and a divider. `banner`, a public https image url, goes on top when there is one."""
    tier, who = PRIZE_TIER.get(key, 1), esc(name or ANONYMOUS)
    flair, icon, prize = TIER_FLAIR[tier], PRIZE_ICON.get(key, ":tada:"), PRIZE_NAME[key]
    blocks = [{"type": "image", "image_url": banner, "alt_text": "{} won".format(prize)}] if banner else []
    if tier == 1:
        return blocks + [_section("{} *{}* goes to *{}*!".format(icon, prize, who))]
    if tier == 2:
        numbers = "  ·  ".join(str(n) for n in ticket[LINES[key]]) if ticket else ""
        return blocks + [_header("{} {}!".format(icon, prize)),
                         _section("{0} *{1}* goes to *{2}*! {0}{3}".format(flair, prize, who,
                                                                       "\n_{}_".format(numbers) if numbers else ""))]
    return blocks + [_header(":trophy: FULL HOUSE! :trophy:"),
                     _section("{0}\n*Full House!* *{1}* has the whole ticket. That is the game.\n{0}".format(
                         flair, who)),
                     {"type": "divider"}]


def read_banners(value):
    """({prize: image url}, [problems]) from the `banners` input: a JSON object, as text or already an object, naming a
    public https image for each prize it has, like {"early5": "https://...", "top": "...", "middle": "...", "bottom":
    "...", "full": "..."}. A prize is named as in `prizes` (five, early5, house ...), and "lines" stands for all three
    lines unless one of them is named too. An address that is not https, has a space or is too long is left out, and so
    is a name that is no prize; each is said in `problems`, so a typo is seen and never reaches Slack."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return {}, []
    shape = ["banners could not be read: give a JSON object like {\"full\": \"https://...\", \"top\": \"https://...\"}"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}, shape
    if not isinstance(value, dict):
        return {}, shape
    found, problems = {}, []
    def squashed(name):
        return re.sub(r"[\s_-]", "", str(name).lower())
    ordered = sorted(value.items(), key=lambda item: squashed(item[0]) not in ("lines", "line"))
    for name, address in ordered:                 # "lines" first, so a line named on its own wins over it
        word = squashed(name)
        keys = list(LINES) if word in ("lines", "line") else [PRIZE_ALIASES.get(word)]
        if keys == [None]:
            problems.append("banners: {!r} is not a prize (early5, top, middle, bottom, full or lines)".format(name))
            continue
        url = str(address or "").strip()
        if not (url.startswith("https://") and " " not in url and len(url) <= BANNER_URL_MAX):
            problems.append("banners: the address for {!r} is not a public https address: left out".format(name))
            continue
        for key in keys:
            found[key] = url
    return found, problems


def fallback_text(g, what):
    return "{}: {}".format(g["word"], what)


# --------------------------------------------------------------------------
# EDGES -- everything below talks to the network
# --------------------------------------------------------------------------

def _send_json(url, headers, payload, method="POST", timeout=HTTP_TIMEOUT, raw_ok=False):
    """(body, error). A payload of None sends no body, for the GET calls. `raw_ok`: a response_url answers with the
    plain text "ok", which is a success, not an unreadable reply."""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply_text = response.read().decode("utf-8")
        try:
            return json.loads(reply_text), None
        except ValueError:
            if raw_ok:
                return {"ok": True, "raw": reply_text[:100]}, None
            raise
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {} {}: {}".format(error.code, method, url.split("/")[2], detail)
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


try:
    import threading
except ImportError:                                                # pragma: no cover
    threading = None


class Table(object):
    """Workato data table access, by column name rather than UUID. Every lookup is scoped to the game's
    channel, and every row written carries it."""

    def __init__(self, token):
        self.headers = {"Authorization": "Bearer {}".format(token), "Content-Type": "application/json"}
        self.errors = []
        self.written = 0
        self.read_failed = False
        self._lock = threading.Lock() if threading else None

    def _note(self, error=None, wrote=False):
        """Tickets are written from several threads at once, so the tallies are kept under a lock."""
        if self._lock:
            self._lock.acquire()
        try:
            if error:
                self.errors.append(error)
            if wrote:
                self.written += 1
        finally:
            if self._lock:
                self._lock.release()

    @staticmethod
    def _decode(body):
        """The query endpoint returns schema and data as arrays-of-arrays."""
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        return [dict(zip(columns, [v for group in row for v in group])) for row in body.get("data", [])]

    def query(self, where, select=None, limit=200, every=False):
        """Matching rows. `every` follows continuation tokens to the last page. A failed read gives []
        with read_failed set: half a game would deal out numbers that are not true."""
        payload = {"where": where, "limit": limit}
        if select:
            payload["select"] = select
        self.read_failed = False
        rows = []
        for _page in range(QUERY_MAX_PAGES):
            body, error = _send_json(TABLE_QUERY_URL, self.headers, payload)
            if error:
                _sleep(0.3)                                    # one retry: a blip is the usual cause
                body, error = _send_json(TABLE_QUERY_URL, self.headers, payload)
            if error:
                self._note(error="table.query " + error)
                self.read_failed = True
                return []
            rows.extend(self._decode(body))
            token = body.get("continuation_token") if every else None
            if not token:
                break
            payload["continuation_token"] = token
        return rows

    def _rows(self, row_type, game_id, channel, extra=None, limit=200, every=False, select=None):
        conditions = [{"row_type": {"$eq": row_type}}, {"id": {"$eq": game_id}},
                      {"slack_channel_id": {"$eq": channel}}] + (extra or [])
        return self.query({"$and": conditions}, select=select, limit=limit, every=every)

    def games(self, game_id, channel):
        """Every row of the game, which is one unless two presses set it up at the same moment."""
        rows = self._rows(GAME_ROW, game_id, channel, limit=10)
        return LOOKUP_FAILED if self.read_failed else rows

    def game(self, game_id, channel):
        """The game's row with its $record_id; None if there is none, LOOKUP_FAILED if the read failed.
        Of two rows made at once the earlier claim is the game, so everyone agrees which."""
        rows = self.games(game_id, channel)
        if rows is LOOKUP_FAILED or not rows:
            return rows if rows is LOOKUP_FAILED else None
        return min(rows, key=lambda r: (as_ts(r.get("last_processed_ts")), str(r.get("$record_id") or "")))

    def active_games(self, channel):
        """The games in this channel that are not over, whoever runs them."""
        rows = self.query({"$and": [{"row_type": {"$eq": GAME_ROW}}, {"slack_channel_id": {"$eq": channel}},
                                    {"status": {"$in": list(ACTIVE)}}]}, every=True)
        return LOOKUP_FAILED if self.read_failed else rows

    def players(self, game_id, channel):
        rows = self._rows(PLAYER_ROW, game_id, channel, every=True)
        return LOOKUP_FAILED if self.read_failed else rows

    def player(self, game_id, channel, user_id):
        rows = self._rows(PLAYER_ROW, game_id, channel, [{"group_id": {"$eq": user_id}}], limit=1)
        if self.read_failed:
            return LOOKUP_FAILED
        return rows[0] if rows else None

    def wins(self, game_id, channel):
        rows = self._rows(WIN_ROW, game_id, channel, every=True)
        return LOOKUP_FAILED if self.read_failed else rows

    def _document(self, fields):
        document = {}
        for name, value in fields.items():
            uuid = COLUMNS.get(name)
            if uuid is None:
                self._note(error="write: unknown column " + name)
            elif value is not None:
                document["$" + uuid] = value if isinstance(value, str) else str(value)
        return document

    def create(self, fields, find=None):
        """(ok, record_id). The create call does not reliably return the id, so `find` -- a zero-argument
        lookup of the new row -- is the fallback. record_id is "" only if both fail: written but not
        addressable, never "not written", for a retry would duplicate."""
        body, error = _send_json(TABLE_RECORDS_URL, self.headers, {"document": self._document(fields)}, "POST")
        if error:
            self._note(error="table.create " + error)
            return False, ""
        self._note(wrote=True)
        body = body if isinstance(body, dict) else {}
        record_id = body.get("record_id") or body.get("$record_id") or body.get("id") or ""
        if not record_id and find:
            for attempt in (1, 2):
                row = find()
                if row and row is not LOOKUP_FAILED:
                    record_id = row.get("$record_id") or ""
                    break
                if attempt == 1:
                    _sleep(0.5)                                # let the new row become visible
        return True, str(record_id)

    def update(self, record_id, fields):
        if not record_id:
            self._note(error="table.update without a $record_id")
            return False
        _body, error = _send_json(TABLE_RECORD_URL.format(record_id), self.headers,
                                  {"document": self._document(fields)}, "PUT")
        if error:
            self._note(error="table.update " + error)
            return False
        self._note(wrote=True)
        return True


def _slack_headers(token):
    return {"Authorization": "Bearer {}".format(token), "Content-Type": "application/json; charset=utf-8"}


def slack_detail(body):
    """What Slack says about WHY, when it turns something down (for invalid_blocks: which part), in brackets."""
    said = "; ".join(str(m) for m in ((body.get("response_metadata") or {}).get("messages") or [])[:3])
    return " [{}]".format(said[:300]) if said else ""


def _slack_call(token, url, payload, method="POST"):
    """(body, error). A call Slack rate-limits is tried once more after a pause."""
    for attempt in (1, 2):
        body, error = _send_json(url, _slack_headers(token), payload, method)
        problem = error or ("" if body.get("ok") else "slack: " + str(body.get("error")) + slack_detail(body))
        if not problem:
            return body, None
        if attempt == 2 or not ("429" in problem or "ratelimited" in problem):
            return None, problem
        _sleep(RATE_LIMIT_WAIT)


def slack_post(token, channel, text, blocks, thread_ts=None):
    """(ts, error)"""
    payload = {"channel": channel, "text": text, "blocks": blocks}
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    body, error = _slack_call(token, SLACK_POST_URL, payload)
    return ((body or {}).get("ts") or ""), error


def slack_update(token, channel, ts, text, blocks):
    _, error = _slack_call(token, SLACK_UPDATE_URL, {"channel": channel, "ts": str(ts), "text": text,
                                                     "blocks": blocks})
    return error


def slack_delete(token, channel, ts):
    _, error = _slack_call(token, SLACK_DELETE_URL, {"channel": channel, "ts": str(ts)})
    return error


def slack_ephemeral(token, channel, user, text, thread_ts=None, blocks=None):
    """A note only `user` sees. Returns the error, if any."""
    payload = {"channel": channel, "user": user, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = str(thread_ts)
    _, error = _slack_call(token, SLACK_EPHEMERAL_URL, payload)
    return error


def tell(result, token, channel, user, text, thread_ts=None, blocks=None, spare=()):
    """A private note. One that does not go is a warning: it must never undo a press. One whose blocks Slack turns
    down goes again in each of the simpler forms in `spare`, in turn, and last as its words alone with Slack's reason
    added, so the person is still answered and can see what went wrong. Returns "sent", "simplified" (a spare went),
    "text only" (the buttons were turned down) or "" (it did not go)."""
    error = slack_ephemeral(token, channel, user, text, thread_ts, blocks)
    if not error:
        return "sent"
    for other in spare:
        if not slack_ephemeral(token, channel, user, text, thread_ts, other):
            result["warnings"].append("note to {} went with simpler buttons: {}".format(user, error))
            return "simplified"
    if blocks:
        words = "{}\n:warning: Slack turned the buttons down ({}).".format(text, error.replace("slack: ", "", 1)[:240])
        if not slack_ephemeral(token, channel, user, words, thread_ts):
            result["warnings"].append("note to {} went without its buttons: {}".format(user, error))
            return "text only"
    result["warnings"].append("note to {}: {}".format(user, error))
    return ""


def slack_dm(token, user_id, text, blocks):
    """(dm channel, ts, error). A message to a user's id lands in their private message with the bot; where
    Slack will not do that, the conversation is opened first (needs im:write)."""
    body, error = _slack_call(token, SLACK_POST_URL, {"channel": user_id, "text": text, "blocks": blocks})
    if error and any(w in error for w in ("channel_not_found", "not_in_channel", "missing_scope")):
        opened, open_error = _slack_call(token, SLACK_OPEN_URL, {"users": user_id})
        dm = ((opened or {}).get("channel") or {}).get("id")
        if dm:
            body, error = _slack_call(token, SLACK_POST_URL, {"channel": dm, "text": text, "blocks": blocks})
        elif open_error:
            error = "{} / {}".format(error, open_error)
    body = body or {}
    return (body.get("channel") or ""), (body.get("ts") or ""), error


def slack_user_info(token, user_id):
    """{name, bot, deleted} from users.info; None when it cannot be had. Never raises."""
    if not token or not user_id:
        return None
    body, error = _slack_call(token, "{}?user={}".format(SLACK_USER_URL, user_id), None, "GET")
    if error:
        return None
    user = body.get("user") or {}
    profile = user.get("profile") or {}
    # real_name first: display names here carry pronoun suffixes
    name = (profile.get("real_name") or user.get("real_name") or profile.get("display_name")
            or user.get("name") or "").strip()
    image = profile.get("image_512") or profile.get("image_192") or profile.get("image_72") or ""
    return {"name": name, "bot": bool(user.get("is_bot")) or user_id == "USLACKBOT",
            "deleted": bool(user.get("deleted")), "image": image}


_PHOTOS = {}                      # user id -> profile picture address, for the length of one job


def user_photo(token, user_id):
    """A person's Slack profile picture address; "" when there is none to be had. Looked up once in a job."""
    if user_id not in _PHOTOS:
        _PHOTOS[user_id] = str((slack_user_info(token, user_id) or {}).get("image") or "")
    return _PHOTOS[user_id]


def wants_photos(g):
    return parse_winners(g["cfg"].get("winners")) in PHOTO_STYLES


def ensure_photos(token, g):
    """Put a picture on every winner of a photo-style board that has none yet. A real game keeps each winner's picture
    with the win; a test game keeps its state in a message, which has no room for addresses, so it looks them up."""
    if not wants_photos(g):
        return
    for win in g["wins"].values():
        if not win.get("img"):
            win["img"] = user_photo(token, win["uid"])


def channel_members(token, channel):
    """(ids, error) of everyone in the channel."""
    ids, cursor = [], ""
    for _page in range(10):
        url = "{}?channel={}&limit=200".format(SLACK_MEMBERS_URL, channel) + ("&cursor=" + cursor if cursor else "")
        body, error = _slack_call(token, url, None, "GET")
        if error:
            return [], error
        ids += body.get("members") or []
        cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return unique(ids), None


def slack_message(token, channel, ts):
    """(message, error): the message at `ts` as Slack has it. Needs the history scope."""
    url = "{}?channel={}&ts={}&limit=1&inclusive=true".format(SLACK_REPLIES_URL, channel, ts)
    body, error = _slack_call(token, url, None, "GET")
    messages = (body or {}).get("messages") or []
    return (messages[0] if messages else None), error


def run_parallel(function, items, deadline=None, workers=None):
    """[function(item)] in order. Several run at once when threads can be had, one after another when they
    cannot. An item not yet started at `deadline` (epoch seconds) is skipped and its place holds SKIPPED;
    one that raises holds {"error": ...}: a ticket that fails is a warning, never the end of the game."""
    items = list(items)
    workers = WORKERS if workers is None else workers

    def one(item):
        if deadline and _now() > deadline:
            return SKIPPED
        try:
            return function(item)
        except Exception as error:                                 # noqa: BLE001
            return {"error": "{}: {}".format(type(error).__name__, str(error)[:200])}

    pool = None
    if workers > 1 and len(items) > 1:
        try:
            from concurrent.futures import ThreadPoolExecutor
            pool = ThreadPoolExecutor(max_workers=min(workers, len(items)))
        except Exception:                                          # noqa: BLE001
            pool = None
    if pool is None:
        return [one(item) for item in items]
    with pool:
        return list(pool.map(one, items))


# --------------------------------------------------------------------------
# Rows: how a game, a player and a prize are written and read back
# --------------------------------------------------------------------------

def game_content(g):
    return json.dumps(state_dict(g, wins=False), separators=(",", ":"))


def game_fields(g):
    """What changes on the game's row. The channel and the claim time were written when it was made."""
    return {"status": g["status"], "grant_type": g["mode"], "member_name": g["host_name"],
            "source_ref": g["board_ts"] or g["lobby_ts"], "content": game_content(g)}


def game_from_row(row):
    try:
        state = json.loads(row.get("content") or "{}")
    except ValueError:
        state = {}
    g = game_from_state(state, False)
    # the columns are the truth for these
    g["id"] = str(row.get("id") or g["id"])
    g["channel"] = str(row.get("slack_channel_id") or g["channel"])
    g["host"] = str(row.get("group_id") or g["host"])
    g["host_name"] = str(row.get("member_name") or g["host_name"])
    g["mode"] = str(row.get("grant_type") or g["mode"])
    g["status"] = str(row.get("status") or g["status"])
    return g


def wins_from_rows(rows):
    """prize -> {uid, name, ts}. When two people finished a prize at once the earlier click holds it."""
    best = {}
    for row in rows:
        key = row.get("grant_type")
        if key not in PRIZE_KEYS or not row.get("group_id"):
            continue
        try:
            extra = json.loads(row.get("content") or "{}")
        except ValueError:
            extra = {}
        entry = {"uid": row["group_id"], "name": row.get("member_name") or "",
                 "ts": row.get("last_processed_ts") or "", "ref": str(row.get("source_ref") or ""),
                 "img": str(extra.get("img") or "") if isinstance(extra, dict) else ""}
        held = best.get(key)
        if held is None or (as_ts(entry["ts"]), entry["uid"], entry["ref"]) < \
                (as_ts(held["ts"]), held["uid"], held["ref"]):
            best[key] = entry
    return best


def load_game(table, game_id, with_wins=False):
    """(game, row): game is None when there is no such game and LOOKUP_FAILED when a read failed."""
    row = table.game(game_id, game_channel(game_id))
    if row is LOOKUP_FAILED:
        return LOOKUP_FAILED, None
    if not row:
        return None, None
    g = game_from_row(row)
    if with_wins:
        rows = table.wins(g["id"], g["channel"])
        if rows is LOOKUP_FAILED:
            return LOOKUP_FAILED, None
        g["wins"] = wins_from_rows(rows)
    return g, row


def save_game(table, row, g):
    return table.update((row or {}).get("$record_id"), game_fields(g))


def valid_ticket(ticket):
    """Three rows of numbers, each row the length of one of the sizes. (Which size is the game's is not known where a
    ticket is read back, so any is taken; a ticket is only ever dealt by make_ticket.)"""
    return (isinstance(ticket, list) and len(ticket) == TICKET_ROWS
            and all(isinstance(r, list) and len(r) == len(ticket[0]) and all(isinstance(n, int) for n in r)
                    for r in ticket)
            and len(ticket[0]) in {spec["row"] for spec in SIZES.values()})


def player_content(ticket, marks, dm_channel="", dm_ts=""):
    return json.dumps({"t": ticket, "m": sorted(marks), "dc": dm_channel, "dt": dm_ts}, separators=(",", ":"))


def player_from_row(row):
    """{ticket, marks, dm_channel, dm_ts, name, row} from a player's row; the ticket is None until dealt."""
    try:
        data = json.loads(row.get("content") or "{}")
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    ticket = data.get("t") if valid_ticket(data.get("t")) else None
    marks = {n for n in data.get("m") or [] if isinstance(n, int)}
    return {"ticket": ticket, "marks": marks, "dm_channel": str(data.get("dc") or ""),
            "dm_ts": str(data.get("dt") or ""), "name": row.get("member_name") or "", "row": row}


def save_player(table, g, user_id, name, ticket, marks, dm_channel, dm_ts, existing=None, stamp=""):
    """Write a player's row: the existing one is updated, a new one is made. True when it is written."""
    fields = {"member_name": name, "status": "in", "content": player_content(ticket, marks, dm_channel, dm_ts)}
    if existing and existing.get("$record_id"):
        return table.update(existing["$record_id"], fields)
    fields.update({"record_key": "tambola_player_{}_{}".format(g["id"], user_id), "row_type": PLAYER_ROW,
                   "id": g["id"], "slack_channel_id": g["channel"], "group_id": user_id,
                   "day": today_text(), "last_processed_ts": stamp})
    ok, _record_id = table.create(fields)
    return ok


def lobby_people(table, g):
    """Fill an open lobby's roster from the players' rows: the host, then whoever joined, in order.
    False when the read failed."""
    rows = table.players(g["id"], g["channel"])
    if rows is LOOKUP_FAILED:
        return False
    joined = sorted((r for r in rows if (r.get("status") or "in") == "in" and r.get("group_id")),
                    key=lambda r: (as_ts(r.get("last_processed_ts")), r["group_id"]))
    g["roster"] = unique([g["host"]] + [r["group_id"] for r in joined])
    for row in joined:
        g["names"][row["group_id"]] = row.get("member_name") or ANONYMOUS
    return True


def claim_prizes(table, g, keys, user_id, name, stamp, result, photo=""):
    """(won, lost): the prizes in `keys` that this press holds, and those another click had first as
    [(prize, their name)]. A prize is a row; the earliest click time holds it, whoever reads.

    Every attempt writes a token of its own in its row, and wins only if its own row is the earliest. Who holds a
    prize is not enough to say: when one player's click is handled twice (a double tap, a number tapped again, the
    interaction delivered twice) both attempts would find that player holding it and both announce it. Now only the
    attempt that holds it announces; the other is neither a winner nor a loser, for the player has it already."""
    if g["test"]:
        won = []
        for key in keys:
            if key not in g["wins"]:
                g["wins"][key] = {"uid": user_id, "name": name, "ts": stamp, "ref": "", "img": photo}
                won.append(key)
        return won, []
    # time first, so of two attempts at the same click the one made earlier is the earlier row (the later one cannot
    # win a tie against a prize already announced); a few random characters after it tell apart two in the same tick
    token = "{:019d}{}".format(time.time_ns(), uuid.uuid4().hex[:6])
    created = []
    for key in keys:
        ok, _record_id = table.create({
            "record_key": "tambola_win_{}_{}_{}".format(g["id"], key, user_id), "row_type": WIN_ROW,
            "id": g["id"], "slack_channel_id": g["channel"], "group_id": user_id, "grant_type": key,
            "member_name": name, "status": "won", "day": today_text(), "last_processed_ts": stamp,
            "source_ref": token, "content": json.dumps({"img": photo}) if photo else None})
        if ok:
            created.append(key)
        else:
            result["warnings"].append("could not record the {}".format(PRIZE_NAME[key]))
    if not created:
        return [], []
    _sleep(VERIFY_DELAY)                                           # let a press made at the same moment land
    rows = table.wins(g["id"], g["channel"])
    if rows is LOOKUP_FAILED:
        return created, []                                         # cannot compare: as far as is known, first
    kept = any(str(r.get("source_ref") or "") == token for r in rows)    # the table gave the token back
    g["wins"] = wins_from_rows(rows)
    won, lost = [], []
    for key in created:
        held = g["wins"].get(key)
        if held is None:
            continue
        if held["uid"] != user_id:
            lost.append((key, held["name"]))
        elif held["ref"] == token or not kept:
            won.append(key)
    return won, lost


def judge_mark(g, ticket, marks, number):
    """(kind, marks, earned): what a press on `number` does to a ticket. kind is over (the game has
    finished), wrong (not called yet), again (already marked) or marked. `earned` are the prizes the ticket
    now holds that nobody else does: pressing a number already marked retries that, so a prize that could
    not be recorded the first time is not lost."""
    marks = set(marks)
    if g["status"] not in LIVE:
        return "over", marks, []
    if number not in ticket_numbers(ticket):
        return "wrong", marks, []
    kind = "again"
    if number not in marks:
        if number not in set(called_list(g)):
            return "wrong", marks, []
        marks.add(number)
        kind = "marked"
    earned = [k for k in completed_prizes(ticket, marks, g["cfg"]["prizes"]) if k not in g["wins"]]
    return kind, marks, earned


# --------------------------------------------------------------------------
# The typed word, and the lobby
# --------------------------------------------------------------------------

KEYWORD = re.compile(r"\b(itambola|ihousie)\b", re.I)
SKIP_SUBTYPES = {
    "bot_message", "message_changed", "message_deleted", "message_replied", "thread_broadcast",
    "channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name",
    "channel_archive", "channel_unarchive", "file_share_reply", "tombstone", "reminder_add",
}
MEMBER_SLACK = 10                 # bots in a channel are not players: allow for them before counting heads


def click_stamp(input):
    """Slack's own click time: the order presses are settled in, so recipe latency is not held against anyone."""
    return str(input.get("action_ts") or "").strip() or "{:.6f}".format(_now())


def player_cap(g):
    return min(g["cfg"]["max"], TEST_PLAYERS) if g["test"] else g["cfg"]["max"]


def name_of(info):
    """The name out of a slack_user_info result (or a run_parallel slot holding one); ANONYMOUS when there is none."""
    return (info.get("name") if isinstance(info, dict) else "") or ANONYMOUS


def status_note(g):
    """What to tell someone who presses a control of a game that is not in a state for it."""
    return {LOBBY: SAID_NOT_STARTED, STARTING: SAID_NOT_STARTED, PAUSED: SAID_PAUSED, DONE: SAID_OVER,
            CANCELLED: SAID_CANCELLED}.get(g["status"], SAID_GONE)


def host_only(result, token, g, clicker):
    """True for the organizer. Anyone else is told, privately, that the control is not theirs."""
    if clicker == g["host"]:
        return True
    tell(result, token, result["channel"], clicker, SAID_NOT_HOST.format(host=host_name_of(g)))
    result["ok"], result["skipped"] = True, "only the host can do that"
    return False


def preview_cards(g):
    """Every card of a game with something on it, for Block Kit Builder (skip_post = yes)."""
    names = ["Priya Sharma", "Jack Lee", "Sam Okafor", "Ana Torres"]
    ids = ["UHOST0001", "UJACK0002", "USAM00003", "UANA00004"]
    base = dict(g, host=ids[0], host_name=names[0], roster=ids, names=dict(zip(ids, names)),
                lobby_ts="1700000000.000050", board_ts="1700000000.000100")
    lobby = dict(base, mode="open")
    play = dict(lobby, status=RUNNING, seed=20261109, n=23,
                wins={"early5": {"uid": ids[1], "name": names[1], "ts": "1700000100.000100"}})
    paused = dict(play, status=PAUSED)
    called = called_list(play)
    tickets = [deal_ticket(play, i) for i in ids]
    held = [n for n in ticket_numbers(tickets[2]) if n in called]
    sample = [{"name": names[i], "ticket": tickets[i],
               "marks": {n for n in ticket_numbers(tickets[i]) if n in called} if i < 2 else set(held[:i])}
              for i in range(4)]
    return {
        "setup": setup_blocks(g),
        "lobby": lobby_blocks(lobby),
        "organizer_lobby": panel_blocks(lobby),
        "organizer_pick": panel_blocks(dict(lobby, mode="pick", roster=ids[:1]), menu=list(zip(ids, names))),
        "board": board_blocks(play),
        "organizer_running": panel_blocks(play),
        "organizer_card": panel_blocks(play, mine=(tickets[0], {n for n in ticket_numbers(tickets[0]) if n in called})),
        "review": review_blocks(paused, review_stats(paused, sample)),
        "organizer_paused": panel_blocks(paused),
        "ticket": ticket_blocks(play, tickets[2], held[:3], TICKET_MARKED.format(number=held[0]) if held else ""),
        "board_over": board_blocks(dict(play, status=DONE), OVER_FULL.format(name=names[2])),
    }


def open_game(token, table, parsed, input, with_wins=False):
    """(game, row, problem): the game a press belongs to; when there is none, `problem` is the note to give the
    presser. A real game is read from the table. A test game is read from the public message that holds it."""
    if parsed["test"]:
        state = parsed["state"]
        if parsed["kind"] == "set":               # the setup card carries the whole game: no message holds it yet
            return game_from_state(state, True), None, ""
        channel = str(state.get("c") or input.get("channel") or "")
        ts = str(state.get("m") or input.get("source_ts") or "")
        message, _error = slack_message(token, channel, ts)
        carried = carried_state(message)
        if carried is None:
            return None, None, SAID_TEST_LOST
        g = game_from_state(carried, True)
        if parsed["kind"] in LOBBY_KINDS:
            g["lobby_ts"] = ts
        else:
            g["board_ts"] = ts
        if state.get("k") is not None:                    # the marks on the organizer's card, as their note had them
            g["host_mask"] = _int(state.get("k"), 0, 0, (1 << ticket_size_of(g)) - 1)
        return g, None, ""
    g, row = load_game(table, parsed["game"], with_wins)
    if g is LOOKUP_FAILED:
        return None, None, SAID_AGAIN
    if g is None:
        return None, None, SAID_GONE
    return g, row, ""


RESPONSE_HOSTS = ("https://hooks.slack.com/", "https://hooks.slack-gov.com/")


def usable_response_url(input):
    """The press's response_url when it is one of Slack's. Nothing else is ever posted to."""
    url = str(input.get("response_url") or "").strip()
    return url if url.startswith(RESPONSE_HOSTS) else ""


def respond(url, payload):
    """Replace the private note a button was pressed on. The error, if any. Slack answers with the plain text ok."""
    _body, error = _send_json(url, {"Content-Type": "application/json; charset=utf-8"}, payload, "POST",
                              raw_ok=True)
    return error


CONTROLS_AS = {"sent": "new note", "simplified": "new note (simpler buttons)", "text only": "new note without buttons",
               "": "not delivered"}


def put_in_place(result, url, text, variants):
    """Replace the private note a button was pressed on with the first of `variants` that Slack takes (each a list of
    blocks, or None for words only). True when one did. Slack's reason for each it turns down goes to the warnings."""
    first = ""
    for index, blocks in enumerate(variants[:3]):
        payload = {"replace_original": True, "text": text}
        if blocks:
            payload["blocks"] = blocks
        error = respond(url, payload)
        if not error:
            result["controls"] = "in place" if index == 0 else "in place (simpler buttons)"
            if index:
                result["warnings"].append("the note went in place with simpler buttons: " + first)
            return True
        first = first or error
        result["warnings"].append("could not update the note in place: " + error)
    return False


def reply(result, token, input, user, text, g=None, fresh=True, mine=None):
    """Answer a press of the organizer's controls. Through `response_url` the note that was pressed is REPLACED by
    this one, with the game's current controls under it while the game is on (so a stale button turns into the
    right ones). Without one it is a new private note, when `fresh`."""
    url = usable_response_url(input)
    if url and put_in_place(result, url, text, panel_variants(g, text, mine) if g is not None
                            and g["status"] in ACTIVE else [None]):
        return
    if fresh:
        result["controls"] = CONTROLS_AS[tell(result, token, result["channel"], user, text)]


def show_controls(result, token, input, g, user, note="", fresh=True, mine=None, menu=None):
    """Show the organizer the game's controls as they stand now. Through `response_url` the note they just pressed
    is REPLACED, so the controls stay in one place however long the game runs. Without one a new note is sent, when
    `fresh` (a Next number sends none): the controls are never missing, but they pile up. Once the game is over the
    controls go and a line says so."""
    if g["status"] not in ACTIVE:
        reply(result, token, input, user, note or status_note(g), fresh=fresh)
        return
    variants = panel_variants(g, note, mine, menu)
    text = note or fallback_text(g, "your controls")
    url = usable_response_url(input)
    if url and put_in_place(result, url, text, variants):
        return
    if fresh:
        result["controls"] = CONTROLS_AS[tell(result, token, g["channel"], user, text, blocks=variants[0],
                                              spare=variants[1:])]


def menu_options(token, g):
    """The organizer's menu of people as the channel's own list: [(user id, name)] of everyone in the channel who can
    play, the organizer included, so even a channel with only them in it has something to pick from. (None, why) when
    the channel's members cannot be read or are more than one menu holds: the menu is then Slack's people picker, which
    searches the whole workspace. The names are looked up here, a few at a time."""
    members, error = channel_members(token, g["channel"])
    if error:
        return None, error
    ids = unique([g["host"]] + members)
    if len(ids) > MENU_MAX + MEMBER_SLACK:
        return None, "this channel has more people than one menu can list"
    people = []
    for user_id, info in zip(ids, run_parallel(lambda u: slack_user_info(token, u), ids, _now() + MENU_SECONDS)):
        if isinstance(info, dict) and "bot" in info:
            if (info["bot"] or info["deleted"]) and user_id != g["host"]:
                continue                                           # an app or a deactivated account cannot play
            people.append((user_id, info["name"] or user_id))
        else:
            people.append((user_id, user_id))                      # no name to be had: the id at least tells them apart
    if len(people) > MENU_MAX:
        return None, "this channel has more people than one menu can list"
    people.sort(key=lambda p: (p[1].lower(), p[0]))
    return people, ""


def send_panel(result, token, g, user, note="", menu=None):
    """The organizer's controls as a new private note, for when no press is there to replace (the typed word)."""
    show_controls(result, token, {}, g, user, note=note, menu=menu)


def problem_note(result, token, input, user, problem):
    """Tell the organizer why their press found no game. A read that failed is a new note (the controls they pressed
    are still good); a game that is gone replaces them."""
    if problem == SAID_AGAIN:
        tell(result, token, result["channel"], user, problem)
    else:
        reply(result, token, input, user, problem)
    result["ok"], result["skipped"] = problem != SAID_AGAIN, "game not available"


def find_active(table, channel, user):
    """What this channel already has for this person: ("host", game, row) when they run a game that is not over,
    ("player", game, row) when they are playing in one, None when neither, LOOKUP_FAILED if the read failed. A
    game left over from before ACTIVE_HOURS ago is taken as abandoned."""
    rows = table.active_games(channel)
    if rows is LOOKUP_FAILED:
        return LOOKUP_FAILED
    fresh = [r for r in rows if _now() - as_ts(r.get("last_processed_ts")) <
             (LOBBY_HOURS if r.get("status") in (LOBBY, STARTING) else ACTIVE_HOURS) * 3600]
    fresh.sort(key=lambda r: -as_ts(r.get("last_processed_ts")))               # the newest first
    for row in fresh:
        if row.get("group_id") == user:
            return "host", game_from_row(row), row
    for row in fresh:
        game = game_from_row(row)
        if game["status"] in LIVE and user in game["roster"]:
            return "player", game, row
    return None


def resend_ticket(token, table, result, g, user, stamp, say):
    """Send a player their ticket again, with the numbers they had marked. `say(text)` gives them the private note
    that answers (a new note for the typed word, the organizer's own note replaced for My ticket). True when sent."""
    mine = ticket = None
    marks, name = set(), ""
    if not g["test"]:
        mine = table.player(g["id"], g["channel"], user)
        if mine is LOOKUP_FAILED:
            say(SAID_AGAIN)
            result["error"] = "could not read your row"
            return False
        if mine:
            kept = player_from_row(mine)
            ticket, marks, name = kept["ticket"], kept["marks"], kept["name"]
    if ticket is None:
        if user not in g["roster"]:
            say(SAID_NOT_PLAYING)
            result["ok"], result["skipped"] = True, "not a player"
            return False
        ticket = deal_ticket(g, user)         # dealt in, but the row was never written: the same ticket again
    name = name or g["names"].get(user) or name_of(slack_user_info(token, user))
    dm_channel, dm_ts, error = slack_dm(token, user, fallback_text(g, "your ticket"), ticket_blocks(g, ticket, marks))
    if error:
        say(SAID_TICKET_FAILED)
        result["warnings"].append("ticket for {}: {}".format(user, error))
        result["error"] = "could not send the ticket"
        return False
    if not g["test"] and not save_player(table, g, user, name, ticket, marks, dm_channel, dm_ts, mine, stamp):
        result["warnings"].append("the row of {} was not saved".format(user))
    say(SAID_TICKET_SENT)
    result["user_name"] = name
    return True


def start_setup(input, result, token, table, flags):
    """Someone typed the word. If they already run a game in this channel they get ITS controls back; if they are
    playing in one, their ticket again. Otherwise they get the card that asks how people can join, which only
    they see."""
    user, channel = result["user_id"], result["channel"]
    word = "Housie" if re.search(r"\bihousie\b", str(input.get("text") or ""), re.I) else "Tambola"
    message_ts = str(input.get("message_ts") or "").strip() or "{:.6f}".format(_now())
    g = new_game(game_id_for(channel, message_ts), channel, user, word, game_config(input), flags["testing"])
    result["game_id"], result["testing"], result["mode"] = g["id"], g["test"], "setup"
    if flags["skip_post"]:
        result["preview"], result["preview_json"], result["ok"] = True, json.dumps(preview_cards(g)), True
        return
    if not g["test"] and str(input.get("workato_api_token") or "").strip():
        found = find_active(table, channel, user)
        if found is LOOKUP_FAILED:
            result["warnings"].append("could not look for a game already running in this channel")
        elif found:
            role, game, _row = found
            result["game_id"], result["status"] = game["id"], game["status"]
            if role == "host":
                result["mode"] = "panel"
                menu = menu_options(token, game)[0] if game["mode"] == "pick" and game["status"] == LOBBY else None
                note = SAID_HAVE_GAME.format(word=game["word"], done=CANCEL_TEXT if game["status"] in (LOBBY, STARTING)
                                             else END_TEXT)
                send_panel(result, token, game, user, note=note, menu=menu)
                result["ok"] = True
            else:
                result["mode"] = "ticket"
                result["ok"] = resend_ticket(token, table, result, game, user, click_stamp(input),
                                             lambda text: tell(result, token, channel, user, text)) or result["ok"]
            return
    thread = str(input.get("thread_ts") or "").strip()
    thread = thread if thread and thread != message_ts else None       # a top-level word gets a card in the channel
    error = slack_ephemeral(token, channel, user, fallback_text(g, "how should people join?"), thread,
                            setup_blocks(g))
    if error:
        result["error"] = "could not show the setup card: " + error
        return
    result["ok"] = True


def create_game_row(table, g, stamp):
    """(outcome, row). created; exists (the lobby is already up); lost (another press set the game up at
    the same moment and the earlier click keeps it); failed."""
    rows = table.games(g["id"], g["channel"])
    if rows is LOOKUP_FAILED:
        return "failed", None
    if rows:
        row = min(rows, key=lambda r: (as_ts(r.get("last_processed_ts")), str(r.get("$record_id") or "")))
        if row.get("source_ref") or _now() - as_ts(row.get("last_processed_ts")) < CLAIM_STALE:
            return "exists", row
        table.update(row.get("$record_id"), {"last_processed_ts": stamp})   # a press that never got to post
        return "created", row
    fields = {"record_key": "tambola_game_" + g["id"], "row_type": GAME_ROW, "id": g["id"],
              "slack_channel_id": g["channel"], "group_id": g["host"], "day": today_text(),
              "last_processed_ts": stamp}
    fields.update(game_fields(g))
    ok, record_id = table.create(fields, find=lambda: table.game(g["id"], g["channel"]))
    if not ok:
        return "failed", None
    _sleep(VERIFY_DELAY)
    rows = table.games(g["id"], g["channel"])
    if rows is not LOOKUP_FAILED and len(rows) > 1 and record_id:
        first = min(rows, key=lambda r: (as_ts(r.get("last_processed_ts")), str(r.get("$record_id") or "")))
        if first.get("$record_id") != record_id:
            table.update(record_id, {"status": CANCELLED})
            return "lost", None
    return "created", {"$record_id": record_id}


def click_set(input, result, token, table, parsed):
    """A choice on the setup card: open the lobby in the channel and give the organizer their controls."""
    clicker, channel = result["user_id"], result["channel"]
    stamp = click_stamp(input)
    result["mode"], result["testing"] = "set", parsed["test"]
    if parsed["test"]:
        g = game_from_state(parsed["state"], True)
        mode = g["mode"]
    else:
        try:
            choice = json.loads(parsed["arg"])
        except ValueError:
            choice = {}
        choice = choice if isinstance(choice, dict) else {}
        mode = str(choice.get("m") or "")
        g = new_game(parsed["game"], game_channel(parsed["game"]) or channel, clicker,
                     str(choice.get("w") or "Tambola"), cfg_from(choice.get("f")), False)
        g["mode"] = mode
    result["game_id"] = g["id"]
    if mode not in MODES or not g["id"]:
        result["error"] = "that is not one of the choices on the setup card"
        return
    for kind in MENUS:                 # what each dropdown shows now, which the button may not have been drawn with
        shown = dropdown_choice(input.get("state"), kind)
        if shown:
            g["cfg"][kind] = shown
    if not host_only(result, token, g, clicker):
        return
    g["host_name"] = name_of(slack_user_info(token, g["host"]))
    g["names"][g["host"]] = g["host_name"]
    g["roster"] = [g["host"]] if mode != "all" else []            # the organizer plays too, however few join
    if mode == "all":
        members, error = channel_members(token, g["channel"])
        if error:
            tell(result, token, channel, clicker, SAID_MEMBERS.format(error=error))
            result["ok"], result["skipped"] = True, "could not read the channel's members"
            return
        if len(members) > player_cap(g) + MEMBER_SLACK:
            tell(result, token, channel, clicker, SAID_TOO_MANY.format(count=len(members), max=player_cap(g)))
            result["ok"], result["skipped"] = True, "too many people in the channel"
            return
        g["total"] = len(members)
    row = None
    if not g["test"]:
        outcome, row = create_game_row(table, g, stamp)
        if outcome == "exists":
            # a double press: the note now holds the lobby's controls, so it keeps them, with this line on top. A
            # picked game's controls hold the channel's list, which is not worth looking up again to say so: left alone
            already = game_from_row(row)
            if not (already["mode"] == "pick" and already["status"] == LOBBY):
                reply(result, token, input, clicker, SAID_SET_UP, already)
            result["ok"], result["skipped"] = True, "this game is already set up"
            return
        if outcome == "lost":
            result["ok"], result["skipped"] = True, "another press is setting this game up"
            return
        if outcome == "failed":
            tell(result, token, channel, clicker, SAID_AGAIN)
            result["error"] = "could not record the game; nothing was posted"
            return
    lobby_ts, error = slack_post(token, g["channel"], fallback_text(g, "a game is open"), lobby_blocks(g))
    if error:
        if row:
            table.update(row.get("$record_id"), {"last_processed_ts": "0"})   # so the choice can be pressed again
        tell(result, token, channel, clicker, SAID_AGAIN)
        result["error"] = "could not post the lobby: " + error
        return
    g["lobby_ts"] = lobby_ts
    result["message_ts"], result["players"], result["status"] = lobby_ts, len(g["roster"]), g["status"]
    if row and not save_game(table, row, g):
        result["warnings"].append("the lobby is up but its message time was not saved")
    menu = None
    if mode == "pick":                                              # the channel's own list of people
        menu, why = menu_options(token, g)
        if menu is None:
            result["warnings"].append("the player menu searches everyone in Slack, not the channel's list: " + why)
    show_controls(result, token, input, g, clicker, menu=menu)     # the setup card turns into the lobby's controls
    result["ok"] = True


def option_choice(value):
    """The choice a size option carried (size_choice_value), from what the step was given as selected_option: the option
    as Slack sends it, {"text": ..., "value": ...}, as JSON text, or just its value; a list of them (the picks of a
    menu that allows several) is read at its first. {} when it is none of these."""
    for _round in range(6):                                        # each pass peels one layer: text, list, option
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        elif isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return {}
        elif isinstance(value, dict) and "value" in value and "s" not in value:
            value = value["value"]
        else:
            break
    return value if isinstance(value, dict) else {}


def dropdown_choice(state, kind):
    """What the setup card's dropdown `kind` ("size", "board") shows at the moment a way of joining was pressed. Slack
    reports every dropdown's current choice with each press, in the interaction's `state`, under a block id it makes up
    (so it is found by the dropdown's action id): this is what the organizer sees chosen, whether or not the card was
    drawn again for it. `state` is the object or its JSON. None when there is none, or it is not one of the choices."""
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError:
            return None
    values = state.get("values") if isinstance(state, dict) else None
    for block in (values.values() if isinstance(values, dict) else []):
        element = block.get(MENU_ACTION[kind]) if isinstance(block, dict) else None
        if isinstance(element, dict):
            return MENU_PARSE[kind](option_choice(element.get("selected_option")).get("s"), "") or None
    return None


def read_payload(value):
    """The interaction payload Slack sent, as a dict: JSON text or an object, and possibly inside the trigger's own
    wrapper, {"block_actions:button": {...}}. {} when there is none, None when there is one that cannot be read."""
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict):
        return None
    while len(value) == 1 and str(next(iter(value))).startswith("block_actions") and \
            isinstance(next(iter(value.values())), dict):
        value = next(iter(value.values()))
    return value


def with_payload(input):
    """(inputs, problem): the click recipe's inputs filled in from `payload`, the whole interaction, so that is the only
    thing it needs to map besides the tokens. What was mapped by hand is kept: the payload only fills what is blank.
    `problem` says so when a payload was given and cannot be read."""
    payload = read_payload(input.get("payload"))
    if not payload:
        return input, ("" if payload == {} else "payload could not be read: map the whole interaction payload as JSON "
                                                "(or leave it empty and map the fields one by one)")
    action = payload.get("actions")
    action = action[0] if isinstance(action, list) and action and isinstance(action[0], dict) else {}
    container = payload.get("container") if isinstance(payload.get("container"), dict) else {}
    found = {
        "user_id": (payload.get("user") or {}).get("id") if isinstance(payload.get("user"), dict) else None,
        "channel": container.get("channel_id") or (payload.get("channel") or {}).get("id")
        if isinstance(payload.get("channel") or {}, dict) else container.get("channel_id"),
        "source_ts": container.get("message_ts"),
        "response_url": payload.get("response_url"),
        "action_value": action.get("value"),
        "action_id": action.get("action_id"),
        "action_ts": action.get("action_ts"),
        "selected_users": action.get("selected_users"),
        "selected_options": action.get("selected_options"),
        "selected_option": action.get("selected_option"),
        "state": payload.get("state"),
    }
    merged = dict(input)
    for name, value in found.items():
        if value not in (None, "", [], {}) and not str(merged.get(name) or "").strip():
            merged[name] = value
    return merged, ""


def click_menu(input, result, token, table, parsed):
    """A choice was made on one of the setup card's dropdowns (size, board style, ticket layout): the card is drawn
    again, in place, standing on it and on whatever the others show. Nothing is saved: the game is only made when the
    organizer chooses how people join, and those buttons now carry them all."""
    clicker, channel = result["user_id"], result["channel"]
    kind = MENU_OF_ACTION.get(parsed["arg"], "size")
    result["mode"] = kind
    given = input.get("selected_option") or input.get("selected_options")
    choice = option_choice(given)
    picked = MENU_PARSE[kind](choice.get("s"), "")
    if not picked or not str(choice.get("m") or "").strip():
        result["error"] = ("that is not one of the choices on the setup card's {} dropdown".format(kind) if given else
                           "the {} dropdown's choice did not arrive: map payload (the whole interaction), or "
                           "selected_option (actions[0].selected_option)".format(kind))
        return
    cfg = cfg_from(choice.get("f"))
    for other in MENUS:                       # another dropdown may have been used since the card was drawn
        shown = dropdown_choice(input.get("state"), other)
        if shown:
            cfg[other] = shown
    cfg[kind] = picked
    test = bool(choice.get("t"))
    g = new_game("tb_{}_{}".format(channel, str(choice["m"]).strip()), channel, clicker,
                 str(choice.get("w") or "Tambola"), cfg, test)
    result["game_id"], result["testing"] = g["id"], test
    text, blocks = fallback_text(g, "how should people join?"), setup_blocks(g)
    url = usable_response_url(input)
    if url and put_in_place(result, url, text, [blocks]):
        result["ok"] = True
        return
    if not url:
        result["warnings"].append("response_url is not mapped, so the setup card could not be redrawn in place: a new "
                                  "one was sent")
    error = slack_ephemeral(token, channel, clicker, text, None, blocks)
    if error:
        result["error"] = "could not show the setup card again: " + error
        return
    result["controls"], result["ok"] = CONTROLS_AS["sent"], True


def click_blank(input, result, token, table, parsed):
    """A blank square of a printed ticket was pressed. There is nothing on it: nothing changes, and nobody is told."""
    result["mode"], result["ok"], result["skipped"] = "blank", True, "a blank square"


def click_pick(input, result, token, table, parsed):
    """The organizer chose people on their menu: the lobby follows. They are always in."""
    clicker, stamp = result["user_id"], click_stamp(input)
    result["mode"], result["testing"] = "pick", parsed["test"]
    selected = unique(ids_in(input.get("selected_users")) + ids_in(input.get("selected_options")))
    if not selected and "selected_options" not in input:
        result["warnings"].append("selected_options is not mapped: the channel's list sends its picks there "
                                  "(actions[0].selected_options), so this pick was read as nobody chosen")
    g, row, problem = open_game(token, table, parsed, input)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"] = g["id"]
    if not host_only(result, token, g, clicker):
        return
    if g["mode"] != "pick" or g["status"] != LOBBY:
        reply(result, token, input, clicker, SAID_STARTED if g["status"] in LIVE else status_note(g), g)
        result["ok"], result["skipped"] = True, "the lobby is not taking picks"
        return
    if not g["test"] and as_ts(stamp) < as_ts(g["picked_ts"]):
        result["ok"], result["skipped"] = True, "an older pick, already replaced"
        return
    ids = unique([g["host"]] + selected)[:player_cap(g)]
    need = [u for u in ids if not g["names"].get(u)]
    for user_id, info in zip(need, run_parallel(lambda u: slack_user_info(token, u), need)):
        g["names"][user_id] = name_of(info)
    g["roster"], g["picked_ts"] = ids, stamp
    if not g["test"] and not save_game(table, row, g):
        tell(result, token, result["channel"], clicker, SAID_AGAIN)
        result["error"] = "could not save the picks"
        return
    error = slack_update(token, g["channel"], g["lobby_ts"], fallback_text(g, "a game is open"), lobby_blocks(g))
    if error:
        result["warnings"].append("lobby: " + error)
    result["players"], result["ok"] = len(ids), True


def click_join(input, result, token, table, parsed):
    """Join game, on an open lobby: the one button a participant sees. One row for the player, their name with it."""
    clicker, stamp = result["user_id"], click_stamp(input)
    source_ts = str(input.get("source_ts") or "").strip()
    result["mode"], result["testing"] = "join", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input)
    if problem:
        tell(result, token, result["channel"], clicker, problem)
        result["ok"], result["skipped"] = problem != SAID_AGAIN, "game not available"
        return
    result["game_id"] = g["id"]
    g["lobby_ts"] = source_ts or g["lobby_ts"]                  # the press is on the lobby itself
    if g["status"] != LOBBY:
        tell(result, token, result["channel"], clicker, SAID_STARTED if g["status"] in LIVE else status_note(g))
        result["ok"], result["skipped"] = True, "the lobby is closed"
        return
    if g["mode"] != "open":
        result["ok"], result["skipped"] = True, "this lobby has no Join button"
        return
    if not g["test"] and not lobby_people(table, g):
        tell(result, token, result["channel"], clicker, SAID_AGAIN)
        result["error"] = "could not read the players"
        return
    if clicker in g["roster"]:
        tell(result, token, result["channel"], clicker, SAID_ALREADY_IN)
        result["ok"], result["skipped"] = True, "already in"
        return
    if len(g["roster"]) >= player_cap(g):
        tell(result, token, result["channel"], clicker, SAID_FULL.format(count=player_cap(g)))
        result["ok"], result["skipped"] = True, "the game is full"
        return
    name = name_of(slack_user_info(token, clicker))
    if g["test"]:
        g["roster"].append(clicker)
        g["names"][clicker] = name
    else:
        existing = table.player(g["id"], g["channel"], clicker)
        if existing is LOOKUP_FAILED or not save_player(table, g, clicker, name, None, set(), "", "",
                                                        existing, stamp):
            tell(result, token, result["channel"], clicker, SAID_AGAIN)
            result["error"] = "could not record the player"
            return
        if not lobby_people(table, g):                  # the row is written; the list is just not re-read
            g["roster"].append(clicker)
            g["names"][clicker] = name
    result["user_name"] = name
    error = slack_update(token, g["channel"], g["lobby_ts"], fallback_text(g, "a game is open"), lobby_blocks(g))
    if error:
        result["warnings"].append("lobby: " + error)
    if not g["test"]:
        # a join made at the same moment may not have been in the list this redraw was made from: look again
        _sleep(VERIFY_DELAY)
        before = list(g["roster"])
        if lobby_people(table, g) and g["roster"] != before:
            slack_update(token, g["channel"], g["lobby_ts"], fallback_text(g, "a game is open"), lobby_blocks(g))
    tell(result, token, result["channel"], clicker, SAID_JOINED.format(host=host_name_of(g)))
    result["players"], result["ok"] = len(g["roster"]), True


def deal_tickets(token, table, g, ids, existing, stamp, deadline, result):
    """Send every player their ticket and write their row. (seated, no_ticket, waiting): the ones dealt in,
    the ones Slack would not message, and the ones not reached before `deadline`. The last two get theirs by
    typing the word again (the host, with My ticket)."""
    def deal(user_id):
        name = g["names"].get(user_id) or ANONYMOUS
        ticket = deal_ticket(g, user_id)
        dm_channel, dm_ts, dm_error = slack_dm(token, user_id, fallback_text(g, "your ticket"),
                                               ticket_blocks(g, ticket, set()))
        saved = True
        if not g["test"]:
            saved = save_player(table, g, user_id, name, ticket, set(), dm_channel, dm_ts,
                                existing.get(user_id), stamp)
        return {"dm_error": dm_error, "saved": saved}

    seated, no_ticket, waiting = [], [], []
    for user_id, out in zip(ids, run_parallel(deal, ids, deadline)):
        if out is SKIPPED:
            waiting.append(user_id)
        elif out.get("error"):
            no_ticket.append(user_id)
            result["warnings"].append("ticket for {}: {}".format(user_id, out["error"]))
        else:
            if out["dm_error"]:
                no_ticket.append(user_id)
                result["warnings"].append("ticket for {}: {}".format(user_id, out["dm_error"]))
            else:
                seated.append(user_id)
            if not out["saved"]:
                result["warnings"].append("the row of {} was not saved".format(user_id))
    return seated, no_ticket, waiting


def click_start(input, result, token, table, parsed):
    """Start game: the organizer only. Claims the start, posts the board, sends every player their ticket, and
    gives the organizer the controls for the game itself."""
    clicker, stamp = result["user_id"], click_stamp(input)
    deadline = _now() + START_SECONDS
    result["mode"], result["testing"] = "start", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"] = g["id"]
    if not host_only(result, token, g, clicker):
        return
    if g["status"] in LIVE + (DONE, CANCELLED):
        reply(result, token, input, clicker, SAID_CANCELLED if g["status"] == CANCELLED else SAID_STARTED, g)
        result["ok"], result["skipped"] = True, "the game is not in its lobby"
        return
    if g["status"] == STARTING and _now() - as_ts(g["claim"]) < CLAIM_STALE:
        tell(result, token, result["channel"], clicker, SAID_BUSY)
        result["ok"], result["skipped"] = True, "the game is being started"
        return

    def back_to_lobby(note, error=""):
        """Undo the claim, so Start can be pressed again; `note` is told to the organizer."""
        g["status"], g["claim"], g["seed"], g["n"] = LOBBY, "", 0, 0
        if row:
            save_game(table, row, g)
        tell(result, token, result["channel"], clicker, note)
        if error:
            result["error"] = error
        else:
            result["ok"], result["skipped"] = True, "the game was not started"

    # claim it: two presses at once start one game, the one whose claim is still there a moment later
    if not g["test"]:
        g["status"], g["claim"] = STARTING, stamp
        if not save_game(table, row, g):
            tell(result, token, result["channel"], clicker, SAID_AGAIN)
            result["error"] = "could not claim the start"
            return
        _sleep(VERIFY_DELAY)
        again = table.game(g["id"], g["channel"])
        if again is LOOKUP_FAILED:
            back_to_lobby(SAID_AGAIN, "could not check the start claim")
            return
        if game_from_row(again)["claim"] != stamp:
            result["ok"], result["skipped"] = True, "another press is starting this game"
            return

    # who is playing. The organizer always is, so a game with nobody else in it is theirs alone
    if g["mode"] == "open" and not g["test"]:
        if not lobby_people(table, g):
            back_to_lobby(SAID_AGAIN, "could not read the players")
            return
        ids = unique([g["host"]] + g["roster"])
    elif g["mode"] == "all":
        members, error = channel_members(token, g["channel"])
        if error:
            back_to_lobby(SAID_MEMBERS.format(error=error))
            return
        ids = unique([g["host"]] + members)
    else:
        ids = unique([g["host"]] + g["roster"])
    cap = player_cap(g)

    def too_many(count):
        return SAID_TEST_FULL.format(count=cap) if g["test"] else SAID_TOO_MANY.format(count=count, max=cap)
    if len(ids) > cap + MEMBER_SLACK:
        back_to_lobby(too_many(len(ids)))
        return
    need = [u for u in ids if g["mode"] == "all" or not g["names"].get(u)]
    left_out = set()
    for user_id, info in zip(need, run_parallel(lambda u: slack_user_info(token, u), need, deadline)):
        if isinstance(info, dict) and "bot" in info:
            if (info["bot"] or info["deleted"]) and user_id != g["host"]:
                left_out.add(user_id)                              # an app or a deactivated account cannot play
                continue
            g["names"][user_id] = info["name"] or g["names"].get(user_id) or ANONYMOUS
        else:
            g["names"].setdefault(user_id, ANONYMOUS)
    ids = [u for u in ids if u not in left_out]
    if len(ids) > cap:
        back_to_lobby(too_many(len(ids)))
        return

    # the board first, then the tickets
    g["seed"], g["n"], g["roster"], g["status"], g["claim"] = new_seed(), 0, ids, RUNNING, ""
    board_ts, error = slack_post(token, g["channel"], fallback_text(g, "the board"), board_blocks(g))
    if error:
        back_to_lobby(SAID_AGAIN, "could not post the board: " + error)
        return
    g["board_ts"] = board_ts
    result["message_ts"] = board_ts
    if not g["test"] and not save_game(table, row, g):
        slack_delete(token, g["channel"], board_ts)
        back_to_lobby(SAID_AGAIN, "could not save the game; the board was taken down")
        return
    existing = {}
    if not g["test"]:
        rows = table.players(g["id"], g["channel"])
        existing = {} if rows is LOOKUP_FAILED else {r.get("group_id"): r for r in rows}
    seated, no_ticket, waiting = deal_tickets(token, table, g, ids, existing, stamp, deadline, result)
    error = slack_update(token, g["channel"], g["lobby_ts"], fallback_text(g, "the game has started"),
                         lobby_closed_blocks(g, LOBBY_STARTED.format(count=len(ids),
                                                                     players=plural(len(ids), "player")), title=False))
    if error:
        result["warnings"].append("lobby: " + error)
    missing = no_ticket + waiting
    note = SAID_NO_TICKET.format(names=names_text([g["names"].get(u) or ANONYMOUS for u in missing]),
                                 word=typed_word(g)) if missing else ""
    show_controls(result, token, input, g, clicker, note=note)       # the lobby's controls turn into the game's
    result["players"], result["dm_sent"], result["status"] = len(ids), len(seated), g["status"]
    result["dm_failed"] = [g["names"].get(u) or u for u in missing]
    result["ok"] = True


def click_cancel(input, result, token, table, parsed):
    """Cancel, on the organizer's lobby controls."""
    clicker = result["user_id"]
    result["mode"], result["testing"] = "cancel", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"] = g["id"]
    if not host_only(result, token, g, clicker):
        return
    if g["status"] in LIVE + (DONE,):
        reply(result, token, input, clicker, SAID_STARTED, g)
        result["ok"], result["skipped"] = True, "the game has started"
        return
    g["status"] = CANCELLED
    if not g["test"] and not save_game(table, row, g):
        tell(result, token, result["channel"], clicker, SAID_AGAIN)
        result["error"] = "could not cancel the game"
        return
    error = slack_update(token, g["channel"], g["lobby_ts"], fallback_text(g, "cancelled"),
                         lobby_closed_blocks(g, LOBBY_CANCELLED.format(host=host_name_of(g))))
    if error:
        result["warnings"].append("lobby: " + error)
    reply(result, token, input, clicker, SAID_CANCELLED, fresh=False)    # the controls have nothing left to do
    result["status"], result["ok"] = g["status"], True


# --------------------------------------------------------------------------
# The board, the organizer's controls and the tickets
# --------------------------------------------------------------------------

def redraw_board(token, g, result, over=""):
    """Draw the board message again. While the game is paused it shows the review, which a real game leaves as it
    is (Resume draws the board again, with every prize); a test game redraws the review to keep its state."""
    if g["status"] == PAUSED and not over:
        if not g["test"]:
            return True
        blocks = review_blocks(g, review_stats(g, None))
    else:
        ensure_photos(token, g)
        blocks = board_blocks(g, over)
    error = slack_update(token, g["channel"], g["board_ts"], fallback_text(g, "the board"), blocks)
    if error and wants_photos(g) and g["wins"]:
        # Slack turned the carousel or the pictures down: the board must still be redrawn, so show the names
        result["warnings"].append("the winners' pictures were refused, so the board shows names: " + error)
        g = dict(g, cfg=dict(g["cfg"], winners="names"))
        error = slack_update(token, g["channel"], g["board_ts"], fallback_text(g, "the board"), board_blocks(g, over))
    if error:
        result["warnings"].append("board: " + error)
    return not error


def announce(token, g, key, name, ticket, result):
    """Tell the channel (or the board's thread, or nobody) about a prize, as big as the prize is (win_blocks), with its
    banner when the recipe gave one. If Slack will not take the banner the announcement goes without it."""
    how = g["cfg"]["announce"]
    if how == "off":
        return
    text, thread = win_text(g, key, name, ticket), g["board_ts"] if how == "thread" else None
    banner = (g.get("banners") or {}).get(key, "")
    _ts, error = slack_post(token, g["channel"], text, win_blocks(g, key, name, ticket, banner), thread)
    if error and banner:
        result["warnings"].append("the banner for the {} was not taken, so it went without: {}".format(
            PRIZE_NAME[key], error))
        _ts, error = slack_post(token, g["channel"], text, win_blocks(g, key, name, ticket), thread)
    if error:
        result["warnings"].append("announcement: " + error)


def click_next(input, result, token, table, parsed):
    """Next number, on the organizer's controls: one more square of the board turns over."""
    clicker, stamp = result["user_id"], click_stamp(input)
    result["mode"], result["testing"] = "next", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input, with_wins=True)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"], result["status"], result["called"] = g["id"], g["status"], g["n"]
    if not host_only(result, token, g, clicker):
        return
    mine = note_ticket(table, g, clicker, parsed)                   # their card, if the note they pressed had it open
    if g["status"] != RUNNING:
        reply(result, token, input, clicker, status_note(g), g, mine=mine)
        result["ok"], result["skipped"] = True, "the game is not running"
        return
    if not g["board_ts"]:
        result["error"] = "the board's message time is not known"
        return
    if g["last_next"] and 0 <= as_ts(stamp) - g["last_next"] < DEBOUNCE:
        result["ok"], result["skipped"] = True, "the same press made twice"
        return
    g["n"] += 1
    g["last_next"] = as_ts(stamp)
    number = draw_order(g["seed"], numbers_of(g))[g["n"] - 1]
    over = ""
    if g["n"] >= numbers_of(g):
        g["status"], over = DONE, OVER_NUMBERS.format(numbers=numbers_of(g))
    if not g["test"] and not save_game(table, row, g):
        tell(result, token, result["channel"], clicker, SAID_AGAIN)
        result["error"] = "could not save the number; the board was not changed"
        return
    redraw_board(token, g, result, over)
    show_controls(result, token, input, g, clicker, fresh=False, mine=mine)   # the note says what was just called
    result["number"], result["called"], result["finished"] = number, g["n"], bool(over)
    result["status"], result["ok"] = g["status"], True


def click_review(input, result, token, table, parsed):
    """Review, on the organizer's controls: pause the game and show everyone where it stands, in the board's place."""
    clicker = result["user_id"]
    result["mode"], result["testing"] = "review", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input, with_wins=True)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"], result["status"], result["called"] = g["id"], g["status"], g["n"]
    if not host_only(result, token, g, clicker):
        return
    mine = note_ticket(table, g, clicker, parsed)
    if g["status"] == PAUSED:                                # already on show: just bring the controls back
        show_controls(result, token, input, g, clicker, mine=mine)
        result["ok"] = True
        return
    if g["status"] != RUNNING:
        reply(result, token, input, clicker, status_note(g), g, mine=mine)
        result["ok"], result["skipped"] = True, "the game is not running"
        return
    players = None
    if not g["test"]:
        rows = table.players(g["id"], g["channel"])
        if rows is LOOKUP_FAILED:
            tell(result, token, result["channel"], clicker, SAID_AGAIN)
            result["error"] = "could not read the players; nothing changed"
            return
        players = []
        for player_row in rows:
            kept = player_from_row(player_row)
            if kept["ticket"] and (player_row.get("status") or "in") == "in":
                players.append({"name": kept["name"] or ANONYMOUS, "ticket": kept["ticket"], "marks": kept["marks"]})
    g["status"] = PAUSED
    if not g["test"] and not save_game(table, row, g):
        tell(result, token, result["channel"], clicker, SAID_AGAIN)
        result["error"] = "could not pause the game; nothing changed"
        return
    error = slack_update(token, g["channel"], g["board_ts"], fallback_text(g, "review"),
                         review_blocks(g, review_stats(g, players)))
    if error:
        result["warnings"].append("board: " + error)
    show_controls(result, token, input, g, clicker, mine=mine)
    result["status"], result["ok"] = g["status"], True


def click_resume(input, result, token, table, parsed):
    """Resume, on the organizer's controls: the board comes back in place of the review and the game carries on."""
    clicker = result["user_id"]
    result["mode"], result["testing"] = "resume", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input, with_wins=True)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"], result["status"], result["called"] = g["id"], g["status"], g["n"]
    if not host_only(result, token, g, clicker):
        return
    mine = note_ticket(table, g, clicker, parsed)
    if g["status"] != PAUSED:
        reply(result, token, input, clicker, SAID_NOT_PAUSED if g["status"] == RUNNING else status_note(g), g,
              mine=mine)
        result["ok"], result["skipped"] = True, "the game is not paused"
        return
    g["status"] = RUNNING
    if not g["test"] and not save_game(table, row, g):
        tell(result, token, result["channel"], clicker, SAID_AGAIN)
        result["error"] = "could not resume the game; it is still paused"
        return
    redraw_board(token, g, result)
    show_controls(result, token, input, g, clicker, mine=mine)
    result["status"], result["ok"] = g["status"], True


def click_end(input, result, token, table, parsed):
    """End game, on the organizer's controls. The board stays as it is, with its closing line."""
    clicker = result["user_id"]
    result["mode"], result["testing"] = "end", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input, with_wins=True)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"] = g["id"]
    if not host_only(result, token, g, clicker):
        return
    if g["status"] not in LIVE:
        reply(result, token, input, clicker, status_note(g), g)
        result["ok"], result["skipped"] = True, "the game is not running"
        return
    g["status"] = DONE
    if not g["test"] and not save_game(table, row, g):
        tell(result, token, result["channel"], clicker, SAID_AGAIN)
        result["error"] = "could not end the game"
        return
    redraw_board(token, g, result, OVER_ENDED.format(host=host_name_of(g)))
    reply(result, token, input, clicker, SAID_OVER, fresh=False)    # the controls have nothing left to do
    result["called"], result["status"], result["finished"], result["ok"] = g["n"], g["status"], True, True


def persist_marks(table, g, user_id, name, mine, ticket, marks, stamp):
    """(ok, marks): write the marks to the player's row. A press made a moment earlier may have been
    written over, so the row is read back once and any mark missing from it is put back."""
    kept = player_from_row(mine) if mine else {"dm_channel": "", "dm_ts": ""}
    if not save_player(table, g, user_id, name, ticket, marks, kept["dm_channel"], kept["dm_ts"], mine, stamp):
        return False, marks
    _sleep(VERIFY_DELAY)
    again = table.player(g["id"], g["channel"], user_id)
    if again and again is not LOOKUP_FAILED:
        seen = player_from_row(again)["marks"]
        if not marks <= seen:
            marks = marks | seen
            save_player(table, g, user_id, name, ticket, marks, kept["dm_channel"], kept["dm_ts"], again, stamp)
    return True, marks


def test_ticket(state):
    flat = state.get("t") if isinstance(state.get("t"), list) else []
    row_size = len(flat) // TICKET_ROWS                           # a test ticket carries itself: its size is its length
    ticket = [flat[i:i + row_size] for i in range(0, row_size * TICKET_ROWS, row_size)] if row_size else []
    return ticket if len(flat) == row_size * TICKET_ROWS and valid_ticket(ticket) else None


def settle_tap(result, token, table, g, row, ticket, marks, name, mine, number, stamp, user, show):
    """A tap on `number` of a player's ticket: judge it, save it, settle any prize and tell the channel. The same
    rules whether the ticket is a private message or the organizer's card in their note. `show(game, marks, lines,
    over)` gives the player their own view first, before anything is announced."""
    kind, marks_now, earned = judge_mark(g, ticket, marks, number)
    note = {"over": "", "again": TICKET_AGAIN.format(number=number),
            "wrong": TICKET_WRONG.format(number=number),
            "marked": TICKET_MARKED.format(number=number)}[kind]
    if kind == "marked" and not g["test"]:
        saved, marks_now = persist_marks(table, g, user, name, mine, ticket, marks_now, stamp)
        if not saved:
            note, marks_now, earned, kind = SAID_AGAIN, marks, [], "wrong"
            result["warnings"].append("could not save the mark")
    result["marked"] = number if kind == "marked" else 0
    won, lost, who = [], [], name
    if earned:
        who = name or name_of(slack_user_info(token, user))
        photo = user_photo(token, user) if wants_photos(g) else ""        # kept with the win, for every board after
        won, lost = claim_prizes(table, g, earned, user, who, stamp, result, photo)
    lines = ([note] if note else []) + [TICKET_WON.format(prize=PRIZE_NAME[k]) for k in won] \
        + [TICKET_LOST.format(name=esc(w or ANONYMOUS), prize=PRIZE_NAME[k]) for k, w in lost]
    show(g, marks_now, lines, g["status"] not in LIVE or "full" in won)
    result["prize"] = ", ".join(PRIZE_NAME[k] for k in won)
    for key in won:
        announce(token, g, key, who, ticket, result)
    if won:
        finished = "full" in won
        if not g["test"]:
            fresh, fresh_row = load_game(table, g["id"], with_wins=True)   # the numbers may have moved meanwhile
            if fresh is not LOOKUP_FAILED and fresh:
                g, row = fresh, fresh_row
        if finished:
            g["status"] = DONE
            if not g["test"] and not save_game(table, row, g):
                result["warnings"].append("could not close the game")
        redraw_board(token, g, result, OVER_FULL.format(name=esc(who or ANONYMOUS)) if finished else "")
        result["finished"], result["status"] = finished, g["status"]
    result["ok"] = True


def click_mark(input, result, token, table, parsed):
    """A number on a ticket was tapped. It arrives from the player's private message, so `channel` is that
    message's channel and everything said back is said on the ticket itself."""
    clicker, dm_channel = result["user_id"], result["channel"]
    ticket_ts = str(input.get("source_ts") or "").strip()
    stamp = click_stamp(input)
    result["mode"], result["testing"] = "mark", parsed["test"]
    number = _int(parsed["arg"], 0, 0, NUMBERS)
    if not number or not ticket_ts:
        result["error"] = "a ticket press needs its number and source_ts (the ticket message)"
        return
    result["marked"] = 0
    mine = None
    name = ""
    row = None
    if parsed["test"]:
        state = parsed["state"]
        ticket = test_ticket(state)
        if ticket is None:
            result["error"] = "this test ticket cannot be read"
            return
        board_channel, board_ts = str(state.get("c") or ""), str(state.get("m") or "")
        message, _error = slack_message(token, board_channel, board_ts)
        carried = carried_state(message)
        g = game_from_state(carried or {"g": state.get("g"), "c": board_channel, "w": state.get("w"),
                                        "hn": state.get("hn"), "s": RUNNING}, True)
        g["board_ts"] = board_ts
        marks = marks_of(ticket, state.get("k"))
        if carried is None:
            slack_update(token, dm_channel, ticket_ts, fallback_text(g, "your ticket"),
                         ticket_blocks(g, ticket, marks, SAID_TEST_LOST))
            result["ok"], result["skipped"] = True, "could not read the test board"
            return
    else:
        g, row = load_game(table, parsed["game"], with_wins=True)
        if g is LOOKUP_FAILED or g is None:
            tell(result, token, dm_channel, clicker, SAID_AGAIN if g is LOOKUP_FAILED else SAID_GONE)
            result["ok"], result["skipped"] = g is None, "game not available"
            return
        mine = table.player(g["id"], g["channel"], clicker)
        if mine is LOOKUP_FAILED:
            tell(result, token, dm_channel, clicker, SAID_AGAIN)
            result["error"] = "could not read your row; nothing changed"
            return
        kept = player_from_row(mine) if mine else None
        if kept and kept["ticket"]:
            ticket, marks, name = kept["ticket"], kept["marks"], kept["name"]
        elif clicker in g["roster"]:                  # dealt in, but the row was not written: deal it again
            ticket, marks, name = deal_ticket(g, clicker), set(), g["names"].get(clicker) or ""
        else:
            tell(result, token, dm_channel, clicker, SAID_NOT_PLAYING)
            result["ok"], result["skipped"] = True, "not a player"
            return
    result["game_id"], result["status"] = g["id"], g["status"]
    g["banners"], notes = read_banners(input.get("banners"))
    result["warnings"] += notes

    def show(game, marks_now, lines, over):
        error = slack_update(token, dm_channel, ticket_ts, fallback_text(game, "your ticket"),
                             ticket_blocks(game, ticket, marks_now, "\n".join(lines), over=over))
        if error:
            result["warnings"].append("ticket: " + error)
    settle_tap(result, token, table, g, row, ticket, marks, name, mine, number, stamp, clicker, show)


def organizer_ticket(table, g, user, mask=None):
    """The organizer's own ticket for their note: (ticket, marks), or None when it cannot be had (the table could
    not be read, or they are not playing). A test game has no row: the ticket is dealt again from the seed and the
    marks are the ones the note carries."""
    if g["test"]:
        ticket = deal_ticket(g, user)
        return ticket, marks_of(ticket, g["host_mask"] if mask is None else mask)
    row = table.player(g["id"], g["channel"], user)
    if row is LOOKUP_FAILED:
        return None
    kept = player_from_row(row) if row else None
    if kept and kept["ticket"]:
        return kept["ticket"], kept["marks"]
    if user in g["roster"]:
        return deal_ticket(g, user), set()         # the organizer always plays: dealt, no row was written
    return None


def note_ticket(table, g, user, parsed):
    """The organizer's card as the note they pressed showed it: while it is open every button of the note says so."""
    return organizer_ticket(table, g, user) if parsed["arg"] == "t" else None


def click_hmark(input, result, token, table, parsed):
    """A number on the organizer's own card was tapped, in their note. The same rules as a ticket in a private
    message (settle_tap); the note is drawn again in place, and the ticket they were sent privately is kept in step."""
    clicker, stamp = result["user_id"], click_stamp(input)
    result["mode"], result["testing"] = "mark", parsed["test"]
    number = _int(parsed["arg"], 0, 0, NUMBERS)
    if not number:
        result["error"] = "a card press needs its number"
        return
    result["marked"] = 0
    g, row, problem = open_game(token, table, parsed, input, with_wins=True)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"], result["status"] = g["id"], g["status"]
    g["banners"], notes = read_banners(input.get("banners"))
    result["warnings"] += notes
    if not host_only(result, token, g, clicker):
        return
    mine = kept = None
    name = g["host_name"]
    if g["test"]:
        ticket = deal_ticket(g, clicker)
        marks = marks_of(ticket, g["host_mask"])
    else:
        mine = table.player(g["id"], g["channel"], clicker)
        if mine is LOOKUP_FAILED:
            tell(result, token, result["channel"], clicker, SAID_AGAIN)
            result["error"] = "could not read your row; nothing changed"
            return
        kept = player_from_row(mine) if mine else None
        if kept and kept["ticket"]:
            ticket, marks, name = kept["ticket"], kept["marks"], kept["name"] or name
        else:                                          # the organizer always plays: dealt, though no row was written
            ticket, marks = deal_ticket(g, clicker), set()

    def show(game, marks_now, lines, over):
        if over:                                       # the game is over: the controls and card have nothing left to do
            reply(result, token, input, clicker, "\n".join(lines + [SAID_OVER]))
        else:
            show_controls(result, token, input, game, clicker, note="\n".join(lines), mine=(ticket, marks_now))
        if kept and kept["dm_channel"] and kept["dm_ts"]:      # the ticket they were sent stays in step
            error = slack_update(token, kept["dm_channel"], kept["dm_ts"], fallback_text(game, "your ticket"),
                                 ticket_blocks(game, ticket, marks_now, over=over))
            if error:
                result["warnings"].append("ticket: " + error)
    settle_tap(result, token, table, g, row, ticket, marks, name, mine, number, stamp, clicker, show)


def click_ticket(input, result, token, table, parsed):
    """Show my card / Hide my card, on the organizer's controls. Show opens their own ticket inside the same private
    note, under the controls, so they can tap their numbers without leaving the channel for a private message; Hide
    tucks it away. The note says which it is in on every button, so no state is kept anywhere. Opening it redraws
    the note in place, which needs response_url: without one the ticket is sent by private message, as before."""
    clicker, stamp = result["user_id"], click_stamp(input)
    result["mode"], result["testing"] = "ticket", parsed["test"]
    g, row, problem = open_game(token, table, parsed, input)
    if problem:
        problem_note(result, token, input, clicker, problem)
        return
    result["game_id"], result["status"] = g["id"], g["status"]
    if g["status"] not in LIVE:
        reply(result, token, input, clicker, status_note(g), g)
        result["ok"], result["skipped"] = True, "the game is not running"
        return
    if parsed["arg"] == "t":                                        # Hide my card
        show_controls(result, token, input, g, clicker)
        result["ok"] = True
        return
    if usable_response_url(input):                                  # Show my card
        mine = organizer_ticket(table, g, clicker)
        if mine:
            show_controls(result, token, input, g, clicker, mine=mine)
            result["ok"] = True
            return
    result["ok"] = resend_ticket(token, table, result, g, clicker, stamp,
                                 lambda text: reply(result, token, input, clicker, text, g)) or result["ok"]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

CLICKS = {"set": click_set, "menu": click_menu, "blank": click_blank, "pick": click_pick, "join": click_join,
          "start": click_start, "cancel": click_cancel, "next": click_next, "review": click_review,
          "resume": click_resume, "end": click_end, "mark": click_mark, "hmark": click_hmark, "ticket": click_ticket}
CLICK_INPUTS = ("payload", "action_value", "action_id", "selected_users", "selected_options", "selected_option",
                "source_ts", "action_ts", "response_url", "state")


def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    input, payload_problem = with_payload(input)
    _PHOTOS.clear()
    value = str(input.get("action_value") or "").strip()
    action_id = str(input.get("action_id") or "").strip()
    # anything only a press carries makes this a press, so a click recipe that is missing a mapping reports
    # that instead of opening a new setup card for every press
    is_click = bool(payload_problem) or any(str(input.get(name) or "").strip() for name in CLICK_INPUTS)
    result = {
        "ok": False, "error": "", "warnings": [], "skipped": "",
        "mode": "click" if is_click else "setup", "testing": False, "preview": False,
        "game_id": "", "status": "", "controls": "", "channel": str(input.get("channel") or "").strip(),
        "user_id": str(input.get("user_id") or "").strip(), "user_name": "", "message_ts": "",
        "players": 0, "called": 0, "number": 0, "marked": 0, "prize": "", "finished": False,
        "dm_sent": 0, "dm_failed": [], "rows_written": 0, "preview_json": "",
    }
    table = Table(input.get("workato_api_token") or "")
    try:
        if payload_problem:
            result["error"] = payload_problem
        else:
            _run(input, result, table, value, action_id, is_click)
    except Exception as error:                                     # noqa: BLE001
        result["ok"] = False
        result["error"] = "unexpected {}: {}".format(type(error).__name__, str(error)[:300])
    result["rows_written"] = table.written
    result["warnings"] += table.errors
    return result


def _run(input, result, table, value, action_id, is_click):
    token = str(input.get("slack_bot_token") or "").strip()
    if is_click:
        if not result["user_id"] or not result["channel"]:
            result["error"] = "user_id and channel are both required"
            return
        if not token:
            result["error"] = "slack_bot_token is required"
            return
        parsed = parse_value(value, action_id)
        if not parsed or parsed["kind"] not in CLICKS:
            result["error"] = ("this is not a tambola button: map action_value (actions[0].value) and, for "
                               "the player menu, action_id, selected_users and selected_options")
            return
        if not parsed["test"] and not str(input.get("workato_api_token") or "").strip():
            result["error"] = "workato_api_token is required"
            return
        if str(input.get("response_url") or "").strip() and not usable_response_url(input):
            result["warnings"].append("response_url is not one of Slack's: ignored")
            input = dict(input, response_url="")
        CLICKS[parsed["kind"]](input, result, token, table, parsed)
        return

    # the typed word
    flags = {"testing": _switch(input.get("testing")), "skip_post": _switch(input.get("skip_post"))}
    result["testing"] = flags["testing"]
    # the bot's own messages and Slack's housekeeping events are not people typing
    subtype = str(input.get("subtype") or "").strip().lower()
    if str(input.get("bot_id") or "").strip() or subtype in SKIP_SUBTYPES \
            or (result["user_id"] and result["user_id"] == str(input.get("bot_user_id") or "").strip()):
        result["ok"], result["skipped"] = True, "not a person typing"
        return
    text = str(input.get("text") or "")
    if text.strip() and not KEYWORD.search(text):
        result["ok"], result["skipped"] = True, "no itambola / ihousie keyword"
        return
    if not result["user_id"] or not result["channel"]:
        result["error"] = "user_id and channel are both required"
        return
    if not token and not flags["skip_post"]:
        result["error"] = "slack_bot_token is required"
        return
    start_setup(input, result, token, table, flags)


if __name__ == "__main__":
    # Looking at the cards from a laptop: python3 tambola.py [word]. Nothing is posted or written.
    print(json.dumps(main({
        "text": sys.argv[1] if len(sys.argv) > 1 else "itambola",
        "user_id": "UHOST0001", "channel": os.environ.get("SLACK_CHANNEL", "C0TAMBOLA"),
        "message_ts": "1700000000.000100", "skip_post": "yes", "testing": "yes",
    }), indent=2))
