"""
Weekly challenges -- one goal for each activity the crew logs, and two for each game they play,
posted on Monday with an Accept button on each; the people who accept are counted on the post itself, tracked on their own row
of the activity, congratulated by spotter when they clear it, and named again when the week closes.

One Python step, three recipes (a Workato step is one file, so it routes on what it is given):

    `action_value` present  ->  a button was pressed: count the person in, track their goal
    `mode` = recap          ->  the week's end: who cleared what, and the week is closed
    otherwise               ->  Monday: read the table, set the goals, post them

WHAT IS POSTED  (as it reads with `personal` = no; with it on, each line names the category and
    hints that the target is revealed on a press, and no figure is shown: see PERSONAL CHALLENGES)
    One message in the channel -- a short explanation, then the busiest activities as a line
    of text with an Accept button -- and, in its thread, the rest of them in the same form.
    Each message is edited on its own as people accept:

        :plank-3:  *100 pushups*
        Accepted by *3*  ·  Priya, Jack and Sam                              [ Accept ]

    Under the explanation, a small line counts the whole post -- "3 challenges accepted by 2
    people so far" -- and is redrawn on every press, including one in a reply in the thread
    (the channel message is then edited too). In a test post it counts what is on the message
    pressed, since a test post keeps its state in its buttons and the messages cannot see each
    other.

    Names are plain text rather than @mentions, so an edit does not ping anyone. Someone who
    has opted out of the leaderboards shows as "Someone". Pressing Accept a second time changes
    nothing; a private note says so.

HOW A GOAL IS SET (the table only has what spotter writes, so this is all it can know)
    A goal is a WEEKLY TOTAL, Monday to Sunday. For each activity the step lines up every
    person's session list (`total`) with their `heatmap_dates`, adds the amounts up by
    calendar week, and keeps the weeks that are over:

        typical week   the median, across the people who logged it in the last 4 weeks, of
                       what each of them logs in a week when they log at all
        best week      the biggest week anyone has had (anyone with leaderboard_optout left out)

    goal = typical week x the level's share, rounded DOWN to a round figure (75, 100 pushups;
    45 minutes, 2 hours), and never more than 90% of the best week. A level whose figure
    would pass that line stays on it, so no goal asks for more than someone in the channel has
    actually done. The input `level` picks the share (SHARE below):

        level 1   70% of a typical week    comfortably within reach (the default)
        level 2   a typical week
        level 3   130%     level 4   170%     level 5   220%     then 50 points more a level

    Retune the shares, the 90%, the round figures and the smallest worthwhile goal for each
    activity at the top of the file -- nothing else encodes them.

    HOW HIGH A GOAL CAN GO. Whatever the level, the crew's best week, or how far someone has
    climbed in a year or two, no goal for a category passes its entry in LIMITS: a workout 6 hours
    a week, a plank an hour, steps 140,000, pushups 700, a cold shower a day, and so on -- ordinary
    healthy effort, one category at a time, in one table to retune. It holds for the team figure,
    for every personal target and for the Stretch / Summit sizes, and it limits what is ASKED,
    never what somebody logs. A target climbs toward its limit and halts there; someone who
    already logs more is asked for the limit and told it goes no higher. The run reports each
    category's `limit`. (A judgment of ordinary effort, not medical advice, and per category: there
    is no cap on a total across categories.)

    An activity gets a goal only if at least `min_people` (default 2) logged it in the last 4
    weeks, and sleep and fasting never do (more is not better). The run reports, per activity,
    the typical week, the best week and the goal at levels 1-5, so a level can be chosen by
    looking (run with skip_post = yes first).

    Lining the two lists up: when a row's `total` and `heatmap_dates` have the same length
    every session has its day, and the row is exact. When `total` is longer they are lined up
    from the recent end and only the last 4 weeks are used; what such a row adds up to can
    only come out a little low. A row with more dates than sessions is left out. These rows
    are counted in `rows_loose`. Rows written while spotter was being built are like this, and
    so is any row where someone has logged twice in one day: spotter adds each log to
    `total` but a day to `heatmap_dates` only once, so the lists then differ by one for good.
    Giving every log its own date, as the event_entry rows do, makes every row exact.

PERSONAL CHALLENGES (input `personal`, on by default)
    One figure on a button fits few people. A crew can hold someone who logs 1 hour of workouts a
    week and someone who logs 4, and "3 hours" is out of reach for the first and nothing for the
    second. So the post names each CATEGORY and shows no figure: every button reads "Workouts",
    "Yoga" and so on, with a line under the grid saying that targets are personal. Pressing one
    reveals, in a note only that person sees, a target worked out from THEIR OWN weeks
    (personal_challenge). It is the goal their entry is kept at, that spotter settles against and
    that "Show my progress" shows:

        logs 1 hour a week  ->  40 min      2 hours  ->  1 h 15 min      4 hours  ->  2 h 45 min

    It is read from their own row (personal_flow): their typical week (the median of the weeks they
    logged in the last 4), their average, their best week, and how steady they have been. A first
    challenge starts at 70% of their typical week (the `level` input's share, as the team figure
    did). After that it moves along their own ladder of round figures by how they did the last
    time they took the same challenge on (personal_step): two steps up when they beat it by 30% or
    cleared three in a row, one when they cleared it, none when they came close (80%), back one
    when they fell short, and one step up at most unless they logged in two of the last four
    weeks. The ladder runs from that 70% to 130% of their typical week and never past their best
    week with a quarter to spare (PERSONAL_ROOM), so nothing is asked beyond what they have shown
    they can do. The note says where the target comes from ("You usually log about 1 hour a
    week, so this starts a little under that"), and carries sizes to pick (below): bigger ones
    for someone who has taken the same challenge on before, lighter ones for someone new to it.
    The team figure is still worked out and returned (`target`), but it is posted nowhere, and a
    post saved before this keeps working as it did. What each person took on is told where the
    category alone says too little: the "Challenges accepted" list and the lines under each goal carry
    every name's own figure ("Yoga  ·  2  ·  Dheeraj (3 hours), Priya (45 min)"), redrawn when someone
    picks another size, and the Sunday recap names each person that cleared it with theirs ("cleared by
    Cal (Summit: 5 hours) and Ben (1 h 15 min)  (2 of 4)"). Only Stretch and Summit are named as sizes,
    never Gentle or Easy.
    `personal` = no gives back the team figure on every button, which `adaptive` then moves from
    week to week, as in the next section.

FROM ONE WEEK TO THE NEXT (the team figure: `personal` = no; input `adaptive`, on by default)
    A goal worked out from the last 4 weeks alone comes out the same every Monday while the crew
    keeps its habits, so each challenge moves a step from last week's figure instead. A step is
    the next round figure on the activity's grid (60, 70, 75, 80, 90 pushups: about 10%), and UP
    is the default; how last week went, for the people who took the challenge on (counted as the
    recap counts them, from the previous post), only decides how far:

        3 in 4 or more did the posted goal    two steps up
        a third or fewer did                  one step back
        in between, or fewer than 2 took it on   one step up (a small crew often has one
                                              acceptance, or none, and still gets a new figure)

    A challenge moves between the figure the `level` input gives (the lowest it can be) and the
    one level 3 gives, 130% of a typical week (ADAPT_TOP). The ceiling is there because the clear
    rate is read among the people who took it on, who are the ones it suits, so left alone it
    would keep rising past what the rest of the crew can do. A higher `level` input still sets a
    higher goal, and the best-week line still holds every goal down. A figure at the top (or
    bottom) of its range stays there until the crew's own weeks move the range, which is the only
    time a goal repeats; the run says so in `why`. A challenge that was not set last week starts
    at the `level` figure. The run reports, for each challenge, how big it is in levels, last
    week's goal, how many took it on and did the posted goal, the move, and `why`; `adapted_from`
    is the week of the post it went from, and a warning says so when none was found (no
    `channel`, no earlier post, or one that cannot be read). The post shows "up from 75" or "down
    from 100" beside a goal that moved. `adaptive` = no sets every challenge at `level`, as
    before.

ALWAYS THREE SIZES (a personal post: personal_offer, three_sizes)
    Whoever presses a challenge, and whatever they have done, the note carries exactly three sizes
    to pick between, so it behaves the same every time. They are built round the size that suits the
    person, which is Steady: their own target when they have taken the challenge on before or have
    weeks of their own to size one from (70% of their typical week for a first one), and the pace of
    the active crew -- the team figure, what the other people logging it do -- when they have
    neither (someone pressing Journaling who has never logged it). The other two are its nearest
    neighbours, as round figures of the activity's grid, never past the weekly limit. Which side
    they come from first depends on who it is:

        has taken it on before     bigger first    Steady · Stretch · Summit
        new, with weeks of theirs  lighter first   Gentle · Easy · Steady
        new, no weeks of theirs    lighter first   Gentle · Easy · Steady, starting on the LIGHTEST

    The lighter ones are about 40% and 70% of Steady (starter_sizes), never under the round figure
    at or below half the smallest worthwhile goal; the bigger ones are what their own weeks support
    (stretch_goals). When the preferred side has fewer than two -- a first target at the bottom of
    the grid, or a veteran at the weekly limit or whose weeks support nothing more -- the other side
    fills in, so it can read Easy · Steady · Stretch (a line over the buttons says which: climb,
    size or ease in), and only when both sides are short do the bigger ones go on past what their
    weeks support, up to the limit. Someone with no weeks of their own starts on the lightest of the
    three, because the crew's pace is the least safe thing to hand someone who has not begun.

    The minutes grid starts at 15 and the seconds grid at a minute, so for someone whose recent
    weeks are small (their first target is that smallest figure) the lighter figures are taken from
    under it, 10 minutes or 30 seconds (STARTER_FIGURES); they are only ever sizes to pick, never a
    target a person is set. A lighter size is never named in the channel: the recap names only
    Stretch and Summit. How many of the three sit under Steady is kept on the acceptance with the
    sizes (`below`), which is how a later press knows what each was called. (The team figure,
    `personal` = no, is unchanged: bigger sizes for someone who has taken the challenge on before,
    none for anyone else.)

PICKING IS ACCEPTING (a personal post: click_live, join_at_size)
    Pressing a category only SHOWS the three sizes, in a private note that is just a small grey line
    ("Reading. Pick a size to take it on: ... Nothing is counted until you do.") over the buttons:
    nothing is written, nobody is added to the post's list or its counts, and the post is not redrawn.
    The size button is what accepts: it takes the person on at that size (their acceptance row and the
    entry on their row of the activity, with the sizes they were offered), redraws the post with them on
    it, and tells them "You are in. <the size's line>". A later press on a size just changes the goal.
    (A size pressed from an old note by someone who has opted out takes them on again at that size. Only
    when there are fewer than two sizes -- never for a real challenge -- does a press accept directly.)
    A test post does the same: the press shows the sizes, the pick (wcgt|..., which carries the message
    to redraw) puts the person on that message's list and saves nothing. A post with a team figure
    (`personal` = no) still accepts on the press.

PICKING YOUR OWN CLIMB (the private note once they are in)
    The note that says "You are in: 100 pushups this week" carries three buttons (on a personal
    post always three: see ALWAYS THREE SIZES; this is the team figure's, and a veteran's):

        :seedling: Steady · 100    :muscle: Stretch · 150    :snow_capped_mountain: Summit · 200

    Steady is the goal as posted; Stretch and Summit are the next two figures up the ladder
    (stretch_goals: each from a higher level than the last, none past the best week anyone has
    had, so someone in the channel has done it). Pressing one sets THAT PERSON'S goal to it --
    the post, its counts and everyone else's goal do not change. It is written to the entry on
    their row of the activity (what spotter settles against, so it is spotter that says "cleared
    the weekly challenge: 150 pushups"), then to the copy on their acceptance row; only a goal
    still open can change. The one in force is the highlighted button, and pressing Accept again
    brings the note back. The names, icons and the line said for each are PICKS at the top of the
    file; PICK_COUNT is how many sizes there are above the posted one.
    The Sunday recap still lists each goal by what was posted, with a name's own size beside it
    ("Jack (Summit: 200)"); whether the posted goal was the right size is judged on who did AT
    LEAST that much, so stretching and landing in between never counts against it.
    A test post's note has the same buttons (value wcgt|...) and saves nothing. On a personal
    post it shows the person who pressed their OWN figures and sizes -- worked out from their
    own row of the activity, which is only read -- when the click recipe passes
    `workato_api_token` (as it does for a real press), so a test looks like the real thing and
    not like the team figure. Without the token, or if the row cannot be read, it says so and
    shows no figure.

OPTING OUT (the "Opt out of this challenge" button)
    Pressing a challenge you are already in brings the note back with its sizes and, under them, one
    more button: "Opt out of this challenge" (it asks "Opt out?" first). It is not on a first
    press. It takes the person out of that challenge for the week (click_optout):

        - their entry comes off their row of the activity (what spotter settles against and
          announces) and the row's count of challenges taken on goes down by one;
        - their acceptance row is marked `status` out and its copy of the entry is CLEARED, because
          spotter and the game steps pick up an acceptance's entry without looking at status, so
          without that a first log would still be tracked;
        - the post is redrawn without them (and the channel message too when it was a reply), and
          they are told, privately, they can press the challenge again until Sunday.

    Pressing the challenge again takes them on again, on the row they already have, from a fresh
    starting total. A goal already cleared, one that has closed, and a week that has ended cannot
    be left; a press that failed part way is finished by pressing again. The recap, the progress
    card and spotter leave anyone who is out alone. Action id `wchallenge_optout_<activity>`,
    values `wco|<post id>|<activity>` (a test post: `wcot|<activity>|<ts>|<channel ts>`, which reads
    the test message back, takes the person off its list and redraws it, writing nothing). No new
    recipe or mapping: the click recipe already passes `wchallenge_` presses to this step.

THE GAMES (iAdd, iSub, iMultiple, iAverage, iDivide, iMemory, iMatch, iMemoryImage)
    Each game with at least `min_people` players who finished a game in the last 28 days gets two
    challenges, both sized from its player rows (personal_best_single_set = best score,
    total_planks = games played, first_seen, updated_at):

        Play iAdd 6 times (Easy)             typical = the median, over the active players, of the
                                             games a week they have played since they began;
                                             best = the highest of those
        Reach a score of 14 in iAdd (Easy)   typical = the median of the active players' best
                                             scores; best = the highest score anyone has had

    The same level shares, round figures and 90%-of-best cap as the activities (the smallest
    are play 2 times and reach 3). They are posted after the activities, in replies of their
    own titled "Brain games", up to 8 buttons each. The cut falls only between games, so a game's
    challenges stay together (some games have just the score, so the total is often odd), and a
    last reply of one or two buttons is folded into the one before it instead of getting a
    title and notes of its own; fewer than 3 game challenges ride in the channel message.
    iMath's are about the Easy game, the free one everybody can play; the iMemory family has no
    difficulty. Only a FREE game finished after pressing Accept and inside the
    week counts -- not a daily, not a test game, not a harder iMath level. `max_games` (default
    8, all of them) keeps the busiest games; `only` / `skip` take a game name for both of its
    challenges (iadd) or one of them (iadd_plays, iadd_score).

    The entry is written to the player's row of the GAME (math_add_user, object_memory_user,
    pairs_memory_user, image_memory_user) with a `kind`: plays (base = total_planks at the
    moment of accepting) or score (base 0). The game step settles it when a game ends, inside
    the same write that saves the game, and says so in the channel (or the game's thread, or
    nowhere: the game steps' announce_weekly input, as spotter's). Someone who has never
    played the game has no row; their entry waits on their acceptance row and their first game
    picks it up. The Sunday recap names who cleared a game challenge from the entries the game
    settled -- a game cannot be judged afterwards from its row, which keeps no date against a
    game -- so an unfinished one is only ever closed as missed.

KEEPING COUNT, AND THE CONGRATULATIONS (the "weekly challenge entries" section)
    When somebody presses Accept the step reads their running total of that activity (the sum
    of their `total` list) and writes an entry into THEIR ROW OF THE ACTIVITY, in `content`, a
    long text column nothing else uses on those rows:

        {"wc": [{"post": ..., "from": "2026-10-19", "to": "2026-10-25",
                 "goal": 100, "text": "100 pushups", "base": 576, "state": "open"}]}

    `base` is that running total at the moment of accepting. What they have done towards the
    goal is their total now less this, which is why only what is logged AFTER pressing Accept
    counts, and why nothing about dates in the lists matters here. Spotter settles the entry on
    every later log, inside the same write that saves the log: when the total has grown by the
    goal it marks the entry done and tells the room ("Weekly challenge cleared ...
    Congratulations!") -- once, because the news and the mark are one write. Spotter's input
    announce_weekly says where: channel (the default), thread (a reply under the log that
    cleared it) or off; nothing is ever said for someone who has opted out. Days outside the
    week do not count; a log that arrives after the week closes the entry as missed, silently.

    The reply spotter already posts under every log also says how much is left, for the
    activity just logged only: "70 reps to go on this week's 100 pushups". Goals in activities
    the log did not touch are not mentioned, so a reply never turns into a list.

    Each row also keeps how many weekly challenges it has taken on and cleared, ever
    ("wc_counts"). They go up in the same write that adds an entry (accepted) or marks one
    done (cleared), so they cannot disagree with the entries, and they outlive them -- only the
    newest 12 entries are kept. A person's total is the sum over their rows; spotter returns
    it (weekly_accepted_total, weekly_cleared_total) and says "N cleared so far" on the
    congratulation from the second one on.

    Someone who accepts an activity they have never logged has no row to hold the entry, and
    none is made up for them (spotter would take a stub for a returning member and lose their
    welcome). The entry waits on their acceptance row instead, and their first log picks it up.

    Only the `content` column is touched, any other key in it is kept, and a column holding
    something that is not a json object is left alone altogether (the press is still counted;
    `tracking` says it was not tracked).

THE SUNDAY RECAP (mode = recap)
    Posts, in the channel, each goal somebody took on and who cleared it ("cleared by Priya,
    Jack and Sam (3 of 5)"), then takes the buttons off the week's messages (the counts stay),
    marks the post closed, and writes how each person's entry ended (done or missed, and the
    row's count of cleared goals goes up for each it settles itself) so a late log next week
    cannot reopen it. It needs nothing from spotter: an entry spotter marked done
    stands, and one still open is judged from the running totals, up to the day after the week
    ends. Run it on MONDAY, in the same recipe and just before the new set goes up (Monday
    morning IST is fine). Logs are dated in each person's own day, so for someone far west
    Sunday may still have hours to run: a goal not cleared yet is therefore LEFT OPEN by the
    recap (not marked missed) until the day after the week ends, a late log can still clear it
    and be congratulated, and the first log after that closes it as missed. It picks the open
    post whose week is over or ends today.
    `week` (a Monday) recaps a post a later Monday has already closed. Anyone who has opted out
    is counted, never named. A run that cannot post leaves everything open to be run again.

TEST MODE (input `testing` = yes)
    The goals are the real ones and the post is real -- it goes to `channel` -- but NOTHING is
    written to the data table: no post row, no acceptance rows, nothing on anyone's row of an
    activity, last week's post is left alone and a repeat run is not blocked. The buttons on a
    test post still work. They carry the post's state in their own `value`, so a press edits
    that message and counts the person in without the table. The click recipe needs no
    `testing` mapped: a test post is recognised by its buttons. A test press counts in that
    message only and is not tracked, and two people pressing in the same second can overwrite
    each other -- which the real thing, a row per acceptance, does not. With mode = recap it
    posts the recap marked as a test and closes nothing (it recaps the real post, so it needs
    real acceptances to show).

    skip_post = yes goes one step further: nothing is posted either. The messages come back
    in `preview_json` (paste a "blocks" list into Slack's Block Kit Builder to look at it).

SHOWING PROGRESS (the "Show my progress" button on spotter's reply)
    When somebody logs an activity and has weekly goals open in OTHER activities or games,
    spotter adds a line to its reply with a button (action_id `wchallenge_progress`, value
    `wcp|<thread ts>`). Pressing it shows the PRESSER -- whoever they are -- a private note in
    that thread, laid out as a card: a header, the week and how many are cleared, then each goal
    they took on this week as its title with a bar of ten squares under it (blue while the goal is
    open, green once cleared) and how far on they are,

        :dart: Your weekly challenges
        Mon 19 Oct - Sun 25 Oct  ·  1 of 3 cleared
        :plank-3:  *100 pushups*
        [3 of 10 squares blue]  30%  ·  70 to go  ·  5 days left

    taken from their own rows (what they have done since accepting is their running total now
    less the total when they accepted). A goal cleared shows as done, a goal that is "reach a
    score of N" has no partial figure and says whether it is cleared yet. Goals whose activity
    they have never logged show as not started. Every goal is a block of its own, so Slack does
    not fold the note behind "Show more". Nothing is written. It is a click like any other here,
    so the Click recipe below already covers it.

THE THREE RECIPES
    Monday   Scheduler (weekly, Monday morning) -> this step. Inputs: workato_api_token,
             slack_bot_token, channel, level, and any of the optional ones below.
    Recap    First step of the same Monday recipe, before the post: this step with mode = recap,
             channel, both tokens. Then the Monday step below, in that order, so the old set is
             recapped and closed before the new one goes up.
    Click    Slack interactivity trigger, filtered to action_id starting `wchallenge_` ->
             this step, mapped exactly as iMath's click recipe:
                 action_value  <- actions[0].value
                 user_id       <- user.id
                 channel       <- container.channel_id
                 source_ts     <- container.message_ts
                 action_ts     <- actions[0].action_ts
             plus slack_bot_token and workato_api_token. Nothing else.
    Spotter itself needs only to be redeployed: it finds the entries on its own. So do the game
    steps (imath.py, imemory.py): map the new input announce_weekly on BOTH recipes of each.

INPUTS (all optional unless marked)
    workato_api_token  data table token (required, except for a click on a test post)
    slack_bot_token    chat:write and users:read (required to post or to answer a click)
    channel            channel id to post in, or whose post to recap (required)
    mode               post (default) or recap
    level              1, 2, 3 ... how big the goals are. Default 1. With `adaptive` it is the lowest
                       level any challenge is set at
    personal           no = the team figure on every button, the same for everyone. Default yes: each
                       button carries a category, and the target is worked out for whoever presses it
                       from their own weeks (above)
    adaptive           (for `personal` = no) no = every challenge is set at `level`, with no memory of
                       last week. Default yes: each moves up or down from last week, as above (needs
                       `channel`)
    testing            yes = test mode, above
    skip_post          yes = compute and return the messages, post nothing, write nothing
    force              yes = post again for a week that already has a post: the old messages
                       are deleted and their acceptances start over
    week               recap: the Monday of the week to recap
    top_count          post_style 1 and 2: activities shown in the channel message itself. Default 5.
                       A grid post (3) is sized by the next two inputs instead
    buttons_per_row    post_style 3: buttons in a row of the grid, 1 to 5 (Slack folds a row past 5).
                       Default 5
    button_rows        post_style 3: rows of buttons in the channel message, 1 to 5. Default 4. The
                       channel message holds buttons_per_row x button_rows challenges (20 by
                       default, 8 with two to a row); the rest go to the thread
    post_style         1, 2 or 3: how each challenge is drawn. 1 = a line of text, its button, and a
                       small status line under it (the default); 2 = the status folded into the
                       same block as the text, button alongside (about half the height); 3 = a
                       grid of buttons, `buttons_per_row` to a row (icon and goal on each) with a short list of only the
                       challenges somebody has accepted. Kept with the post, so every redraw on a
                       press uses it, and carried in a test post's buttons
    max_challenges     most activity goals. Default 20
    max_games          most games to set challenges for (two each). Default 8; 0 = none
    min_people         active people an activity needs. Default 2
    only / skip        comma separated activities and games to keep / drop, e.g.
                       "pushup,plank,yoga,iadd" (spotter keywords such as ipushup work too)
    intro_text         replaces the one-line explanation under the title
    banner_url         https image shown at the very top (a wide banner, e.g. 1280x300). On the
                       Monday step it tops the channel message and is kept with the post, so every
                       redraw keeps it; on the recap step it tops the results post. Map a
                       different image on each step. Blank = none
    close_previous     no = leave last week's messages as they are. Default yes
    tz_offset          seconds east of UTC that decide what "today" is. Default -25200. A button
                       press needs none: the presser's own offset is asked of Slack (users.info),
                       and this is used only when it is mapped on the step
    today              YYYY-MM-DD, to run as if it were that day (testing aid)
    local_data_file    JSON list of table rows (column names as keys) to read instead of the
                       table, for looking at the goals offline (needs testing or skip_post)

ROWS (workato_governance_unified; neither type ends in _users, so no other step reads them)
    weekly_challenge  one per post: id = post id, week_key = the Monday, slack_channel_id,
                      source_ref = ts of the channel message, status posting / open / closed /
                      replaced / failed, content = json (level, the goals, which goal is in
                      which message and that message's ts)
    weekly_accept     one per person per goal: id = post id, grant_type = activity or game
                      challenge key (pushup, iadd_plays ...),
                      group_id = person, member_name, last_processed_ts = Slack's click time,
                      content = their entry as first made.
                      Deliberately NOT id = person: spotter reads everything with a person's
                      id in one unpaged query, and a row a week per goal would crowd their
                      activity rows out of it.
    A count is read back by listing a post's acceptance rows and counting distinct people, so
    two people pressing at once cannot lose each other, and a double click counts once.
    And, on each person's row of an activity, the entry above in `content`.

BUTTONS (tell the Slack trigger to listen for action_id starting `wchallenge_`)
    wchallenge_accept_<key>        value  wc|<post id>|<key>|accept           (real posts; with
                                   `personal` on the button reads "Reveal my challenge")
                                   value  wct|<json state>                    (test posts)
    block_id: wc_<key>   (key: an activity, or <game>_plays / <game>_score)
    wchallenge_progress            value  wcp|<thread ts>                     (spotter's reply)
    wchallenge_goal_<key>_<n>      value  wcg|<post id>|<key>|<goal>          (real posts)
                                   value  wcgt|<key>|<goal>|<n>               (test posts)
                                   the Steady / Stretch / Summit buttons in the private note. The
                                   Click recipe already covers them: same trigger, same mapping.

Input / output schema: weekly_challenge_input_schema.json / weekly_challenge_output_schema.json
"""

import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

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
SLACK_REPLIES_URL = "https://slack.com/api/conversations.replies"

HTTP_TIMEOUT = 30
DEFAULT_TZ_OFFSET = -7 * 3600     # the channel's original zone, as in spotter.py

# Stand-ins so a test can run without waiting.
_sleep = time.sleep
_now = time.time

# --------------------------------------------------------------------------
# Rows and columns -- the only place a field UUID appears
# --------------------------------------------------------------------------

POST_ROW = "weekly_challenge"
ACCEPT_ROW = "weekly_accept"

# Where a person's session list lives: `total` and, once it is full, the spare columns spotter
# carries it on in. Keep identical to TOTAL_COLUMNS in spotter/spotter.py.
TOTAL_COLUMNS = ("total", "plank_photo", "current_weight", "current_fat", "current_muscle")

COLUMNS = {
    "record_key": "81f48f77-2849-428a-b84d-1f11ff301b83",
    "row_type": "61b928b9-46b7-430c-a40f-873b187591e2",
    "id": "3edd5f8c-137d-46fd-966e-b067f2772838",
    "name": "aa7e6bf6-4cf7-4830-bade-38a1ccc710cd",
    "total": "e96b5acc-4196-497e-a18b-7faf7016ec4c",
    "heatmap_dates": "7f8871d1-1613-4faa-94e6-a7ef3649cc25",
    "leaderboard_optout": "101f8dcb-f067-4045-af61-0799494651b8",
    "last_processed_ts": "5761a90c-832e-4bf5-aaee-5d6a4d43f045",
    "updated_at": "387a94cf-91df-43ca-a341-b574de95ac9d",
    "group_id": "4c96f075-78db-41ac-bfc2-6ac195b8df2c",
    "grant_type": "355e769f-0aa3-46be-bea3-5c2b3442f658",
    "member_name": "bc214e7f-c007-4fd7-ac0e-6367b1e4098f",
    "created_at": "d0b48b75-2fbf-44db-a36a-cc0a1e46036c",
    "day": "5cfe9bc1-cc32-4a5b-9cc6-4f6682cb7a4b",
    "status": "863a9d40-87a7-49ff-ba40-32858e62cd48",
    "source_ref": "e530be4a-68dc-4e9a-ad1f-2dbb8af3abf1",
    "slack_channel_id": "7101072d-867b-4104-a1e4-ef6611adaaa9",
    "content": "3c42b96c-a909-423b-8545-f438366b5702",
    "week_key": "e9659bdd-c36c-486b-a531-e7b5a38252f6",
    "plank_photo": "f801caa5-b3c2-4f07-a98c-7b2d24c66689",
    "current_weight": "08ec0542-79af-43a9-8d58-de30e14a6c51",
    "current_fat": "ce9c49a6-c1f9-4169-8833-a3721d6c38b5",
    "current_muscle": "ac156767-3d8e-42d1-bcd9-b78ca84b6d51",
}

LOOKUP_FAILED = object()          # a read that failed is not "no such row"
QUERY_MAX_PAGES = 50              # a stop for the paging loop, far past any real channel

# post row statuses
POSTING, OPEN, CLOSED, REPLACED, FAILED = "posting", "open", "closed", "replaced", "failed"

# --------------------------------------------------------------------------
# Tuning -- every number that shapes a goal is data, not logic
# --------------------------------------------------------------------------

WINDOW_WEEKS = 4                  # finished weeks that describe "a typical week"
MIN_PEOPLE = 2                    # people who logged an activity in that window, for it to get a goal
CAP_SHARE = 0.9                   # a goal never passes this share of the best week on record

# The share of a typical week each level asks for. Past the last, every level adds LEVEL_EXTRA.
SHARE = (0.7, 1.0, 1.3, 1.7, 2.2)
LEVEL_EXTRA = 0.5
MAX_LEVEL = 20
LEVEL_NOTES = {1: "comfortably within reach", 2: "about a typical week",
               3: "a small stretch", 4: "a solid stretch"}
LEVEL_NOTE_TOP = "a big stretch"

# Week to week each challenge moves along a ladder of round figures (next_step, settle_goal), from
# the figure the `level` input gives up to the one level ADAPT_TOP gives. Up is the default, STEP_UP
# rungs a week: a goal that never moves is what this replaced. Last week only decides how far:
# STEP_UP_STRONG when at least ADAPT_UP of the people who took the challenge on did the posted
# goal, STEP_DOWN back when ADAPT_DOWN or fewer did, and the plain step when it was in between or
# fewer than ADAPT_MIN_TAKERS took it on, which is too few to say anything.
# The ceiling is there because the clear rate is read among the people who took it on, who are the
# ones it suits: left alone it would keep rising past what the rest of the crew can do. A higher
# `level` input still sets a higher goal.
ADAPT_UP = 0.75
ADAPT_DOWN = 0.34
ADAPT_MIN_TAKERS = 2
ADAPT_TOP = 3
STEP_UP = 1
STEP_UP_STRONG = 2
STEP_DOWN = 1

# Someone who has accepted a challenge is offered bigger goals of their own to pick from
# (stretch_goals): the next PICK_COUNT figures up the ladder, none more than PICK_CAP_SHARE of the
# best week anyone has had. PICKS, below, names them in order, the goal as posted first.
PICK_COUNT = 2
PICK_CAP_SHARE = 1.0

# Personal challenges (input `personal`, on by default): the post shows each category and no figure,
# and pressing one reveals a target worked out from that person's OWN weeks (personal_challenge).
# A crew of 50 spans a 1 hour a week person and a 4 hour a week one, and one number cannot fit both.
# Figures under the smallest on a grid, for a newcomer's starting points only (starter_sizes) and only
# where the grid has nothing lighter: the minutes grid starts at 15 and the seconds grid at a minute,
# the smallest a challenge is ever set at, but a person whose recent weeks are smaller than that is
# better offered a start they can do than the one figure that is above everything they have done.
# Half the smallest worthwhile goal is as low as a start goes (yoga 20 min -> 10, plank a minute -> 30 sec).
STARTER_FIGURES = {"minutes": (10,), "seconds": (30,)}

PERSONAL_ROOM = 1.25              # a person's best week, with this much room over it, is as high as a target for them goes
PERSONAL_CRUSH = 1.3              # last week's total against its goal: this much or more is two steps up
PERSONAL_CLOSE = 0.8              # this much or more but short of it holds the goal; less eases it a step
PERSONAL_STREAK = 3               # weeks cleared in a row that earn the second step up as well
PERSONAL_RATIO_CAP = 2.0          # one huge week counts for no more than this against its goal

TOP_COUNT = 5                    # activities in the channel message itself
POST_STYLES = (1, 2, 3)           # how a challenge is drawn: see build_blocks
DEFAULT_STYLE = 1
BUTTON_MAX = 75                   # Slack's limit on a button's text
BUTTONS_PER_ROW = 5               # Slack folds an actions block past 5 behind "+N more", so a row each
BUTTON_ROWS = 4                   # rows of buttons the channel message of a grid post holds
MAX_BUTTON_ROWS = 5
THREAD_CHUNK = 8                  # challenges to a reply in its thread
SPILL_MIN = 3                     # a thread of fewer than this is folded into the main message
MAX_CHALLENGES = 20
MAX_GAMES = 8                     # games that get challenges (two each: play it, score in it)
GAME_ACTIVE_DAYS = 28             # a player is "active" in a game if they finished one this recently
NAMES_SHOWN = 3                   # names on a line before "+N more"

VERIFY_PASSES = 2                 # re-reads after an update, to catch a press that landed meanwhile
VERIFY_DELAY = 0.5
TEST_VALUE_MAX = 1900             # bytes in a button value (Slack's limit is 2000)
TEST_INTRO_MAX = 300              # longest intro_text a test post can carry in its buttons
TEST_BANNER_MAX = 400             # longest banner_url a test post can carry in its buttons
BANNER_MAX = 3000                 # Slack's limit on an image block's url
BANNER_ALT = "Weekly challenges"
RECAP_BANNER_ALT = "Weekly challenges: the results"
INTRO_MAX = 2500                  # Slack stops a section's text at 3000 characters
RATE_LIMIT_WAIT = 1.5             # seconds before the one retry of a call Slack rate-limited

# Round figures a goal may take, per kind of amount, in the unit the table stores (minutes,
# seconds of plank, steps, or a plain count). A goal is the largest of these that does not
# pass the figure worked out, so it always rounds down.
COUNT_GRID = (2, 3, 4, 5, 6, 7, 8, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 75, 80,
              90, 100, 110, 120, 125, 140, 150, 175, 200, 225, 250, 275, 300, 350, 400, 450, 500,
              600, 700, 750, 800, 900, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 4000, 5000,
              7500, 10000)
MINUTE_GRID = (15, 20, 25, 30, 40, 45, 50, 60, 75, 90, 105, 120, 135, 150, 165, 180, 210, 240,
               270, 300, 330, 360, 420, 480, 540, 600, 720, 840, 960, 1080, 1200, 1500, 1800,
               2400, 3000, 3600)
SECOND_GRID = (60, 90, 120, 150, 180, 210, 240, 270, 300, 360, 420, 480, 540, 600, 720, 840,
               900, 1080, 1200, 1500, 1800, 2400, 3000, 3600, 4500, 5400, 7200, 10800, 14400,
               21600)
STEP_GRID = (5000, 7500, 10000, 12500, 15000, 17500, 20000, 25000, 30000, 35000, 40000, 45000,
             50000, 55000, 60000, 65000, 70000, 75000, 80000, 90000, 100000, 110000, 120000,
             130000, 140000, 150000, 175000, 200000, 250000, 300000, 400000, 500000)
GRIDS = {"count": COUNT_GRID, "minutes": MINUTE_GRID, "seconds": SECOND_GRID, "steps": STEP_GRID,
         "plays": COUNT_GRID, "score": COUNT_GRID}

# The activities that can get a goal, in the order that breaks a tie. `kind` says how the
# amount is stored and shown; `floor` is the smallest goal worth announcing (it must be a
# round figure from the kind's grid); `phrase` reads as the goal itself. Sleep and fasting
# are left out on purpose: more of either is not something anyone is aiming for. Keep the
# icons in step with ICONS in channel_summary/channel_summary.py.
ACTIVITIES = {
    "pushup":      {"icon": ":plank-3:", "kind": "count", "phrase": "{} pushups", "floor": 20},
    "pullup":      {"icon": ":muscle:", "kind": "count", "phrase": "{} pullups", "floor": 5},
    "squat":       {"icon": ":leg:", "kind": "count", "phrase": "{} squats", "floor": 30},
    "plank":       {"icon": ":plank-4:", "kind": "seconds", "phrase": "{} of plank", "floor": 60},
    "workout":     {"icon": ":weight_lifter:", "kind": "minutes", "phrase": "{} of workouts", "floor": 30},
    "run":         {"icon": ":runner:", "kind": "minutes", "phrase": "{} of running", "floor": 20},
    "swim":        {"icon": ":swimmer:", "kind": "minutes", "phrase": "{} of swimming", "floor": 20},
    "cycle":       {"icon": ":bicyclist::skin-tone-4:", "kind": "minutes", "phrase": "{} of cycling", "floor": 30},
    "cardio":      {"icon": ":heartpulse:", "kind": "minutes", "phrase": "{} of cardio", "floor": 20},
    "step":        {"icon": ":athletic_shoe:", "kind": "steps", "phrase": "{} steps", "floor": 10000},
    "stairs":      {"icon": ":stairs:", "kind": "count", "phrase": "{} flights of stairs", "floor": 20},
    "dance":       {"icon": ":dancer:", "kind": "minutes", "phrase": "{} of dancing", "floor": 20},
    "cold_shower": {"icon": ":cold_face:", "kind": "count", "phrase": "{} cold showers", "floor": 2},
    "hydrate":     {"icon": ":droplet:", "kind": "count", "phrase": "{} glasses of water", "floor": 7},
    "yoga":        {"icon": ":person_in_lotus_position:", "kind": "minutes", "phrase": "{} of yoga", "floor": 20},
    "meditate":    {"icon": ":brain:", "kind": "minutes", "phrase": "{} of meditation", "floor": 15},
    "breathe":     {"icon": ":wind_blowing_face:", "kind": "minutes", "phrase": "{} of pranayama", "floor": 15},
    "chant":       {"icon": ":winter_singing:", "kind": "minutes", "phrase": "{} of chanting", "floor": 15},
    "solitude":    {"icon": ":crescent_moon:", "kind": "minutes", "phrase": "{} of quiet time", "floor": 15},
    "journal":     {"icon": ":writing_hand:", "kind": "minutes", "phrase": "{} of journaling", "floor": 15},
    "write":       {"icon": ":lower_left_fountain_pen:", "kind": "count", "phrase": "{} pages written", "floor": 3},
    "read":        {"icon": ":books:", "kind": "count", "phrase": "{} pages read", "floor": 10},
    "learn":       {"icon": ":bulb:", "kind": "minutes", "phrase": "{} of learning", "floor": 30},
    "sketch":      {"icon": ":pencil2:", "kind": "minutes", "phrase": "{} of sketching", "floor": 20},
    "paint":       {"icon": ":art:", "kind": "minutes", "phrase": "{} of painting", "floor": 20},
    # (`eyepushups` has no leading i: it is the word people type, and it is eye exercises logged in
    # minutes, about three a day, not `ipushup`'s reps)
    "eyepushups":  {"icon": ":eye:", "kind": "minutes", "phrase": "{} of eye pushups", "floor": 15},
}

# The games. Each has two challenges, "<game>_plays" (play it N times) and "<game>_score" (reach a
# score of N in one game). `row` is the player row the game keeps its figures on: personal_best_single_set
# is the best score, total_planks the games played, updated_at the last game, first_seen the first.
# iMath's challenges are about the Easy game (the one with no difficulty picked: it is the one that
# is free and open to everybody); `tag` says so in the words. Keep the icons in step with GAMES in
# imath/imath.py and FLAVOURS in imemory/imemory.py.
GAMES = {
    "iadd":         {"name": "iAdd", "icon": ":heavy_plus_sign:", "row": "math_add_user", "tag": " (Easy)"},
    "isub":         {"name": "iSub", "icon": ":heavy_minus_sign:", "row": "math_sub_user", "tag": " (Easy)"},
    "imultiple":    {"name": "iMultiple", "icon": ":heavy_multiplication_x:", "row": "math_mul_user", "tag": " (Easy)"},
    "iaverage":     {"name": "iAverage", "icon": ":bar_chart:", "row": "math_avg_user", "tag": " (Easy)"},
    "idivide":      {"name": "iDivide", "icon": ":heavy_division_sign:", "row": "math_div_user", "tag": " (Easy)"},
    "imemory":      {"name": "iMemory", "icon": ":brain:", "row": "object_memory_user", "tag": ""},
    "imatch":       {"name": "iMatch", "icon": ":mahjong:", "row": "pairs_memory_user", "tag": ""},
    "imemoryimage": {"name": "iMemoryImage", "icon": ":frame_with_picture:", "row": "image_memory_user", "tag": ""},
}
PLAYS_FLOOR = 2                   # the smallest worthwhile "play it N times"
SCORE_FLOOR = 3                   # and "reach a score of N"

# What each activity is called when the post shows the category and not a figure (personal
# challenges): a game's two are "<game> · games played" and "<game> · best score".
LABELS = {
    "pushup": "Pushups", "pullup": "Pullups", "squat": "Squats", "plank": "Plank",
    "workout": "Workouts", "run": "Running", "swim": "Swimming", "cycle": "Cycling",
    "cardio": "Cardio", "step": "Steps", "stairs": "Stairs", "dance": "Dancing",
    "cold_shower": "Cold showers", "hydrate": "Water", "yoga": "Yoga", "meditate": "Meditation",
    "breathe": "Pranayama", "chant": "Chanting", "solitude": "Quiet time",
    "journal": "Journaling", "write": "Writing", "read": "Reading", "learn": "Learning",
    "sketch": "Sketching", "paint": "Painting", "eyepushups": "Eye pushups",
}

# The most a goal for each activity may EVER ask in a week, in the unit the table stores. However
# far someone climbs -- in a year, in two -- and whatever their own weeks or the crew's best look
# like, no goal, no size on offer, and no `level` goes past these. They are what ordinary healthy
# effort looks like, not what the most dedicated person can do. They are one person-week of one
# category, so they say nothing about a total across categories. Retune them here: nothing else
# encodes them. (A judgment, not medical advice: have whoever looks after the programme check it.)
LIMITS = {
    "pushup": 700,              # 100 a day
    "pullup": 200,
    "squat": 1000,
    "plank": 3600,              # seconds: an hour of holds in a week
    "workout": 360,             # minutes: an hour a day, six days
    "run": 300, "swim": 300, "cardio": 300, "dance": 300,          # five hours
    "cycle": 420, "yoga": 420,                                      # an hour a day
    "step": 140000,             # 20,000 a day
    "stairs": 350,              # flights: 50 a day
    "cold_shower": 7,           # one a day
    "hydrate": 70,              # glasses: ten a day
    "meditate": 420, "solitude": 420, "sketch": 420, "paint": 420,  # an hour a day
    "breathe": 210, "chant": 210, "journal": 210,                   # half an hour a day
    "learn": 840,               # two hours a day
    "write": 100,               # pages
    "read": 1000,               # pages
    "eyepushups": 105,          # minutes: a quarter of an hour a day; it is a few minutes of rest for the eyes
}
PLAYS_LIMIT = 70                # games: ten a day. A score has no limit but the best anyone has had

# Every challenge there can be, by key: activities by their name, games as <game>_plays and
# <game>_score. `row_type` is the row that holds the person's figures (and their entry).
CHALLENGES = {}
for _key, _info in ACTIVITIES.items():
    CHALLENGES[_key] = dict(_info, row_type=_key + "_users", game=None, label=LABELS[_key],
                            limit=LIMITS[_key])
for _key, _info in GAMES.items():
    CHALLENGES[_key + "_plays"] = {
        "icon": _info["icon"], "kind": "plays", "floor": PLAYS_FLOOR, "game": _key,
        "limit": PLAYS_LIMIT, "label": _info["name"] + _info["tag"] + " \u00b7 games played",
        "phrase": "Play " + _info["name"] + " {} times" + _info["tag"], "row_type": _info["row"]}
    CHALLENGES[_key + "_score"] = {
        "icon": _info["icon"], "kind": "score", "floor": SCORE_FLOOR, "game": _key,
        "limit": None, "label": _info["name"] + _info["tag"] + " \u00b7 best score",
        "phrase": "Reach a score of {} in " + _info["name"] + _info["tag"], "row_type": _info["row"]}
ACTIVITY_ORDER = {base: index for index, base in enumerate(CHALLENGES)}
GAME_OF_ROW = {info["row"]: key for key, info in GAMES.items()}
KEYS_OF_ROW = {}
for _key, _info in CHALLENGES.items():
    KEYS_OF_ROW.setdefault(_info["row_type"], []).append(_key)

# Other ways of naming an activity in `only` / `skip`: spotter's keywords, and a few plurals.
ALIASES = {
    "ipushup": "pushup", "ipullup": "pullup", "isquat": "squat", "iworkout": "workout",
    "irun": "run", "iswam": "swim", "icardio": "cardio", "icycle": "cycle", "isteps": "step",
    "istairs": "stairs", "idance": "dance", "iplanked": "plank", "iyoga": "yoga",
    "imeditate": "meditate", "isolitude": "solitude", "ijournal": "journal", "iwrite": "write",
    "iread": "read", "iprayanam": "breathe", "iprayanama": "breathe",
    "ipilates": "workout", "ichant": "chant", "ihydrate": "hydrate",
    "ilearn": "learn", "isketch": "sketch", "ipaint": "paint", "icoldshower": "cold_shower",
    "steps": "step", "planks": "plank", "planked": "plank", "pushups": "pushup",
    "pullups": "pullup", "squats": "squat", "pranayama": "breathe", "coldshower": "cold_shower",
    "cold shower": "cold_shower", "cold-shower": "cold_shower",
    "imultiply": "imultiple", "eyepushups": "eyepushups", "eyepushup": "eyepushups",
}

# --------------------------------------------------------------------------
# Wording
# --------------------------------------------------------------------------

# One line under the title; the week's number picks which, so it does not read the same twice
# running. Keep them plain and workplace-appropriate.
INTRO_LINES = (
    ":wave: New week, new challenges. Who is up for taking on a small one? Pick any below and "
    "press *Accept challenge*.",
    "A fresh week and a fresh set of small challenges, one for each activity the crew logs. See "
    "what you are up for and press *Accept challenge*.",
    "New week! Here are this week's challenges, sized to be doable. Which ones are you taking "
    "on?",
)
# Style 3 has no "Accept challenge" button: each button is the goal itself.
INTRO_LINES_GRID = (
    ":wave: New week, new challenges. Who is up for taking on a small one? Tap any challenge "
    "below to accept it.",
    "A fresh week and a fresh set of small challenges, one for each activity the crew logs. Tap "
    "the ones you are up for.",
    "New week! Here are this week's challenges, sized to be doable. Tap the ones you are taking "
    "on.",
)
RULES = ("\u2022 Each challenge is a weekly total: what you log from the moment you accept until "
         "Sunday counts.\n"
         "\u2022 Clear it and the channel hears about it. Log as usual.")

# The same post when the targets are personal: categories, a hint, no figures. Two short rules, as above.
PERSONAL_INTRO_LINES = (
    ":wave: New week, new challenges. Who is up for taking on a small one? Pick any below and "
    "press *Reveal my challenge*: the target is sized to you.",
    "A fresh week and a fresh set of challenges, one for each category the crew logs. Press "
    "*Reveal my challenge* on the ones you are up for: your target comes from your own recent "
    "weeks.",
    "New week! These are categories, not targets. Press *Reveal my challenge* and you will see a "
    "goal sized to your own pace.",
)
PERSONAL_INTRO_LINES_GRID = (
    ":wave: New week, new challenges. Who is up for taking on a small one? Tap any challenge "
    "below to take it on: the target is sized to you.",
    "A fresh week and a fresh set of challenges, one for each category the crew logs. Tap the "
    "ones you are up for: your target comes from your own recent weeks.",
    "New week! These are categories, not targets. Tap one and you will see a goal sized to your "
    "own pace.",
)
PERSONAL_RULES = ("\u2022 Each challenge is a weekly total: what you log from the moment you press it "
                  "until Sunday counts.\n"
                  "\u2022 Clear it and the channel hears about it. Log as usual.")
REVEAL_TEXT = "Reveal my challenge :dart:"
PERSONAL_HINT = "your target is revealed when you press"
PERSONAL_GRID_HINT = ("_Targets are personal. Tap a challenge to see yours: it is worked out from "
                      "your own recent weeks and shown only to you._")

# The sizes a person can pick once they have accepted: the goal as posted, then each step up. The
# name and icon go on the button; `said` is what they are told when they pick it ({goal} is the goal
# in words). Keep to workplace tone: a climb, not a dare.
PICKS = (
    {"name": "Steady", "icon": ":seedling:",
     "said": "Steady it is: *{goal}* this week."},
    {"name": "Stretch", "icon": ":muscle:",
     "said": "Stretch locked in: *{goal}* this week, a notch above the post."},
    {"name": "Summit", "icon": ":snow_capped_mountain:",
     "said": "Summit it is: *{goal}* this week. The big one."},
)
PICK_ASK = ("*Pick your climb.* Stay steady, stretch, or go for the summit. It changes your own "
            "goal only, not the post.")
# Someone new to a challenge is offered lighter starting points instead, below what suits them: the
# last size is always Steady, the one before it Easy, the one before that Gentle.
LOWER_PICKS = (
    {"name": "Gentle", "icon": ":leaves:", "said": "Gentle start: *{goal}* this week."},
    {"name": "Easy", "icon": ":herb:", "said": "Easy does it: *{goal}* this week."},
)
EVERY_PICK = PICKS + LOWER_PICKS         # a test button's value says which, by its place in this
PICK_ASK_EASE = ("*Ease in.* Start gentle, go easy, or stay steady. It changes your own goal only, "
                 "not the post.")
# What a newcomer who has weeks of their own is told about the buttons under their note, by how many of
# the three are lighter than Steady (none, one, two).
OFFER_POINTERS = (" Bigger sizes are below if you would like more.",
                  " A lighter and a bigger size are below if you would like to change it.",
                  " Lighter starting points are below if you would rather ease in.")
PICK_ASK_MIX = ("*Pick your size.* A little lighter, steady, or a stretch. It changes your own goal "
                "only, not the post.")
GAMES_NOTE = ("Games count once you accept: the free games you finish from then until Sunday "
              "(iMath: Easy; daily games do not count).")
ANONYMOUS = "Someone"
BUTTON_TEXT = "Accept challenge :crossed_swords:"
MORE_IN_THREAD = ":point_down::skin-tone-4:  *{} more challenge{} in the thread*"
ACCEPTED_HEADER = ":crossed_swords: Challenges accepted"      # a header block: plain text, Slack sets it large and bold
TEST_NOTE = (":test_tube: Test post: nothing is saved. A press is counted in this message only.")

SAID_ENDED = (":hourglass: This week's challenges have ended. A new set goes up on Monday.")
SAID_GONE = ":warning: That challenge is not available any more."
SAID_AGAIN = ":warning: Could not save that just now. Please press Accept again."
SAID_PROGRESS_AGAIN = ":warning: Could not read your progress just now. Please press the button again."
SAID_FULL = (":warning: This test post cannot hold any more acceptances. Post a fresh test "
             "to carry on.")
SAID_PICK_AGAIN = ":warning: Could not set that just now. Please press the button again."
SAID_PICK_GONE = ":warning: That size is not available any more."
SAID_PICK_FIRST = (":warning: Press *Accept challenge* on it first, then pick your climb.")
# What someone who presses a challenge they are not in yet is shown on a personal post: the sizes, and
# nothing counted until they pick one (the pick is the acceptance).
# It is only the small grey line over the buttons (no sentence of its own above it): which challenge,
# what the buttons are, and that nothing counts yet. `JOIN_TEXT` is what a client that cannot draw
# blocks shows.
JOIN_ASK = ("stay steady, stretch, or go for the summit.",
            "a little lighter, steady, or a stretch.",
            "start gentle, go easy, or stay steady.")
JOIN_CONTEXT = "*{label}.* Pick a size to take it on: {ask} Nothing is counted until you do."
JOIN_TEXT = ":crossed_swords: {label}: pick a size to take it on."
SAID_JOINED = ":white_check_mark: You are in. "
SAID_PICK_NEW = (":information_source: Bigger goals open up once you have taken this challenge on in "
                 "an earlier week. This one stays as posted.")
SAID_PICK_ONE = (":information_source: There is only one size for this one, so it stays as it is.")
TEST_PICK_ASK = (PICK_ASK + "\n_Test post: on a real post these buttons are shown only to people who "
                 "have taken the challenge on before._")
TEST_PICK_OWN = ("\n_Test post: these figures are yours, worked out from your own weeks. Nothing is "
                 "saved, so none of it is tracked._")
OPTOUT_TEXT = "Opt out of this challenge"
# (Slack's confirmation dialog does not draw mrkdwn: an asterisk would show as an asterisk.)
OPTOUT_CONFIRM = ("You will leave {} for this week. Press it again any time before Sunday to take it "
                  "on again.")
SAID_OUT = (":wave: You are out of *{}* for this week. Press it again any time before Sunday to take it "
            "on again.")
SAID_OUT_NOT_IN = ":information_source: You are not in *{}* this week. Press it to take it on."
SAID_OUT_AGAIN = ":warning: Could not do that just now. Please press the button again."
TEST_SAID_OUT = ":test_tube: Test: you are out of *{}*. Nothing was saved."
SAID_PICK_CLEARED = (":information_source: You have already cleared *{}* this week, so it stays "
                     "as it is.")
SAID_PICK_CLOSED = (":information_source: *{}* has closed for the week, so it stays as it is.")

# --------------------------------------------------------------------------
# Pure helpers -- no I/O below this line until the EDGES section
# --------------------------------------------------------------------------


def as_date(value):
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def local_today(tz_offset=None, now_utc=None):
    """The channel's date, from a UTC offset in seconds."""
    try:
        offset = int(tz_offset)
    except (TypeError, ValueError):
        offset = DEFAULT_TZ_OFFSET
    now = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    return (now + timedelta(seconds=offset)).date()


def monday_of(day):
    return day - timedelta(days=day.weekday())


def nice_date(day):
    return "{} {} {}".format(day.strftime("%a"), day.day, day.strftime("%b"))


def week_label(monday):
    return "{} – {}".format(nice_date(monday), nice_date(monday + timedelta(days=6)))


MAX_AMOUNT = 10 ** 9              # no session, count or score is more than this: a bigger figure is a typo


def _sane(number):
    return math.isfinite(number) and abs(number) <= MAX_AMOUNT


def split_numbers(value):
    """'40,28,45' -> [40.0, 28.0, 45.0]. Anything that is not a sane number ('abc', 'nan', 'inf',
    a figure past MAX_AMOUNT) is left out: one bad cell must not turn a week's total, or a goal,
    into nonsense."""
    out = []
    for part in str(value or "").split(","):
        try:
            number = float(part.strip())
        except ValueError:
            continue
        if _sane(number):
            out.append(number)
    return out


def split_dates(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def stored_sessions(row):
    """The whole session list of a row, joined from every column it is spread over."""
    pieces = [str(row.get(column) or "") for column in TOTAL_COLUMNS]
    held = [piece for piece in pieces if piece.strip()]
    return ",".join(held) if held else str(row.get("total") or "")


def plural_people(n):
    return "{} {}".format(n, "person" if n == 1 else "people")


def median(values):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _float(value):
    """A number, or 0.0 for anything that is not a finite one ('nan', 'inf', text)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _amount(value):
    """An amount a person logged or scored: _float, and 0.0 for one past MAX_AMOUNT. (Not for a Slack
    timestamp, which is about 1.8 billion and is read with _float.)"""
    number = _float(value)
    return number if abs(number) <= MAX_AMOUNT else 0.0


def _switch(value, default=False):
    """yes / true / 1 / on -> True; no / false / 0 / off -> False; anything else: default."""
    text = str(value if value is not None else "").strip().lower()
    if text in ("true", "1", "yes", "y", "on"):
        return True
    if text in ("false", "0", "no", "n", "off"):
        return False
    return default


def _int(value, default, low, high):
    try:
        number = int(float(str(value).strip()))
    except (TypeError, ValueError, OverflowError):                 # (inf, 1e999)
        return default
    return max(low, min(high, number))


def _activity(word):
    """The challenge keys a word names ('ipullup', 'steps', 'cold shower', 'iadd'), or []. A game
    stands for both of its challenges; 'iadd_plays' names just one."""
    compact = word.replace(" ", "").replace("-", "").replace("_", "")
    base = word if word in CHALLENGES or word in GAMES else ALIASES.get(word) or ALIASES.get(compact)
    if base in GAMES:
        return [base + "_plays", base + "_score"]
    return [base] if base in CHALLENGES else []


def activity_names(value, warnings=None):
    """'pushup, ipullup; steps, iadd' -> ['pushup', 'pullup', 'step', 'iadd_plays', 'iadd_score'].
    Commas, semicolons and new lines separate; a piece that is not an activity as a whole
    ('pushup plank') is tried word by word. Unknown names are reported."""
    out = []
    for raw in re.split(r"[,;\n]+", str(value or "")):
        piece = re.sub(r"[\"'`\[\]{}()]", "", raw).strip().lower()   # quotes or brackets from a list
        if not piece:
            continue
        words = [piece] if _activity(piece) else piece.split()
        for word in words:
            keys = _activity(word)
            for key in keys:
                if key not in out:
                    out.append(key)
            if not keys and warnings is not None:
                warnings.append("unknown activity '{}' ignored".format(word))
    return out


# --------------------------------------------------------------------------
# >>> weekly challenge entries
# KEEP THIS SECTION, down to the matching "<<<", IDENTICAL in spotter/spotter.py,
# weekly_challenge/weekly_challenge.py, imath/imath.py and imemory/imemory.py (a Workato step is
# one file, so it is copied, and a test fails if the copies drift). It needs `json`, `timedelta`,
# `as_date` and `and_join` from the file it sits in. weekly_challenge.py writes an entry into a
# person's row when they press Accept on a challenge for the week; spotter settles an activity's
# on their later logs, and the games settle theirs when a game ends, each saying so when one is
# cleared -- with a bigger post (weekly_final_blocks) when it was the last of their week.
#
# The entries live in `content`, a long text column no activity row uses for anything else, as
# one json object. Any other key in that object is left exactly as it was found, and a column
# that holds something that is not a json object is left alone altogether.
#
#     {"wc": [{"post": "2026-10-19-1792400000", "from": "2026-10-19", "to": "2026-10-25",
#              "goal": 100, "text": "100 pushups", "base": 576, "state": "open"}],
#      "wc_counts": {"accepted": 7, "cleared": 5}}
#
#   kind   absent for an activity (a running total: below), or one of the two game kinds:
#            plays   "play the game N times": base is the row's games-played count (total_planks)
#                    at the moment they accepted, and a finished free game inside the week
#                    that takes the count N past it clears it
#            score   "reach a score of N": cleared by one finished free game inside the week
#                    that scores N or more (base is 0; nothing before counts)
#   base   the person's running total of the activity at the moment they accepted. What they
#          have done towards the goal is their running total now, less this: the table keeps
#          no date against a session, so a total at a moment is what can be compared later.
#   state  open, then done (with "done": the day it was cleared) or missed. Only an open
#          entry is ever looked at again.
#   wc_counts  how many weekly challenges this row has taken on, and cleared, EVER. Kept
#          apart from the entries because those are cut to the newest WEEKLY_KEEP. It goes up
#          by one in the same write that adds an entry (accepted) or marks one done (cleared),
#          so it cannot disagree with them. A person's total is the sum over their rows.
WEEKLY_COLUMN = "content"
WEEKLY_KEY = "wc"
WEEKLY_COUNTS_KEY = "wc_counts"
WEEKLY_KEEP = 12
WEEKLY_GAME_KINDS = ("plays", "score")


def weekly_document(raw):
    """The json object held in the column: {} when it is empty, None when it holds anything
    else (which is then never overwritten)."""
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def weekly_entries(raw):
    """The weekly entries in the column, oldest first. One that cannot be read is skipped."""
    out = []
    for entry in (weekly_document(raw) or {}).get(WEEKLY_KEY) or []:
        try:
            if (isinstance(entry, dict) and entry["post"] and as_date(entry["from"])
                    and as_date(entry["to"]) and int(entry["goal"]) > 0
                    and int(entry["base"]) >= 0):
                out.append(entry)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def weekly_entry_from(raw):
    """One entry held on its own as json (as a weekly_accept row holds it), or None."""
    try:
        found = weekly_entries(json.dumps({WEEKLY_KEY: [json.loads(raw or "")]}))
    except ValueError:
        return None
    return found[0] if found else None


def weekly_counts(raw):
    """(accepted, cleared): how many weekly challenges the row has taken on and cleared, ever."""
    counts = (weekly_document(raw) or {}).get(WEEKLY_COUNTS_KEY)
    counts = counts if isinstance(counts, dict) else {}

    def number(name):
        try:
            return max(0, int(counts.get(name) or 0))
        except (TypeError, ValueError):
            return 0
    return number("accepted"), number("cleared")


def weekly_text(raw, entries, accepted_add=0, cleared_add=0):
    """What the column should hold once its weekly entries are `entries` and its counts have
    gone up by the amounts given; None when it holds something that is not a json object,
    which must not be overwritten."""
    document = weekly_document(raw)
    if document is None:
        return None
    document[WEEKLY_KEY] = list(entries)[-WEEKLY_KEEP:]
    accepted, cleared = weekly_counts(raw)
    accepted, cleared = accepted + accepted_add, cleared + cleared_add
    if accepted or cleared:
        document[WEEKLY_COUNTS_KEY] = {"accepted": accepted, "cleared": cleared}
    return json.dumps(document, separators=(",", ":"))


def weekly_entry(post_id, monday, goal, text, base, kind=""):
    """A new, open entry for a goal accepted when the person's running total was `base`."""
    entry = {"post": post_id, "from": monday.isoformat(),
             "to": (monday + timedelta(days=6)).isoformat(), "goal": int(goal),
             "text": text, "base": int(base), "state": "open"}
    if kind in WEEKLY_GAME_KINDS:
        entry["kind"] = kind
    return entry


def weekly_got(entry, total_now):
    """What the person has done towards the goal: their running total now, less the total they
    had when they accepted."""
    return max(0, int(total_now) - int(entry["base"]))


def weekly_progress(entry, before_total, logs):
    """What the person has done towards the goal once the message being logged is counted.
    `before_total` is their running total before it and `logs` is the message as
    [(day, amount)]. Its amounts count only for days inside the entry's week, so a catch-up for
    a day last week does not count towards this week's goal."""
    start, end = as_date(entry["from"]), as_date(entry["to"])
    inside = sum(amount for day, amount in logs if start <= day <= end)
    return weekly_got(entry, before_total) + inside


def weekly_settle(entry, before_total, logs, today):
    """Where an open entry stands after a log: (entry, cleared).

    A message that arrives after the week has ended can still clear the goal with days from
    inside the week; when it cannot, the entry is closed as missed.
    """
    if entry.get("state") != "open" or entry.get("kind") in WEEKLY_GAME_KINDS:
        return entry, False
    if weekly_progress(entry, before_total, logs) >= int(entry["goal"]):
        return dict(entry, state="done", done=today.isoformat()), True
    if today > as_date(entry["to"]):
        return dict(entry, state="missed"), False
    return entry, False
def weekly_game_settle(entry, score, plays_now, today):
    """Where an open game entry stands after a finished free game: (entry, cleared).

    `score` is that game's score and `plays_now` the row's games-played count with it counted.
    Only a game finished inside the entry's week counts; the first one after the week closes
    the entry as missed."""
    if entry.get("state") != "open" or entry.get("kind") not in WEEKLY_GAME_KINDS:
        return entry, False
    start, end = as_date(entry["from"]), as_date(entry["to"])
    if start <= today <= end:
        if entry["kind"] == "plays":
            reached = weekly_got(entry, plays_now) >= int(entry["goal"])
        else:
            reached = int(score) >= int(entry["goal"])
        if reached:
            return dict(entry, state="done", done=today.isoformat()), True
        return entry, False
    if today > end:
        return dict(entry, state="missed"), False
    return entry, False


def weekly_game_update(raw, waiting, score, plays_now, today):
    """Set a game row's weekly entries against the free game that has just finished.

    `waiting` are entries accepted before the row existed. Returns (text, cleared): the
    column's new content when anything changed (else None) and the entries this game cleared.
    The caller adds `text` to the write that saves the game, so the news and the mark are one
    write and cannot be said twice."""
    mine = weekly_entries(raw)
    known = {entry["post"] for entry in mine}
    added = [entry for entry in waiting if entry["post"] not in known]
    settled, cleared, changed = [], [], bool(added)
    for entry in mine + added:
        new, done = weekly_game_settle(entry, score, plays_now, today)
        changed = changed or new is not entry
        settled.append(new)
        if done:
            cleared.append(new)
    if not changed:
        return None, []
    text = weekly_text(raw, settled, len(added), len(cleared))
    return (text, cleared) if text is not None else (None, [])


def weekly_place(value):
    """Where a cleared weekly challenge is told, from the announce_weekly input: "channel" (the
    default), "thread" (a reply under the log or game that cleared it) or "" for nowhere.
    Settings from when it was only on or off still mean what they did: true / yes / on is the
    channel, false / no / off is nowhere."""
    text = str(value if value is not None else "").strip().lower()
    if text in ("thread", "reply", "in thread", "in the thread"):
        return "thread"
    if text in ("false", "0", "no", "off", "none", "never", "nowhere"):
        return ""
    return "channel"


def weekly_dates(entry):
    """'Mon 12 Oct \u2013 Sun 18 Oct' for an entry's week."""
    first, last = as_date(entry.get("from")), as_date(entry.get("to"))
    if not (first and last):
        return ""
    return "{} {} {} \u2013 {} {} {}".format(
        first.strftime("%a"), first.day, first.strftime("%b"),
        last.strftime("%a"), last.day, last.strftime("%b"))


def weekly_cleared_text(user_id, entries):
    return "<@{}> cleared the weekly challenge: {}".format(
        user_id, and_join(e.get("text") or "the goal" for e in entries))


def weekly_cleared_blocks(user_id, entries, cleared_total=0):
    """The post for a weekly challenge cleared -- or several, when one message cleared them.
    Short: the challenge is the news. From a second one on it says how many they have cleared
    so far."""
    goals = and_join("*{}*".format(e.get("text") or "the goal") for e in entries)
    lead = ("<@{}> cleared the weekly challenge: {}. Congratulations!" if len(entries) == 1
            else "<@{}> cleared {} weekly challenges: {}. Congratulations!")
    detail = (lead.format(user_id, goals) if len(entries) == 1
              else lead.format(user_id, len(entries), goals))
    blocks = [{"type": "section", "text": {"type": "mrkdwn",
               "text": ":tada:  *Weekly challenge cleared*"}},
              {"type": "section", "text": {"type": "mrkdwn", "text": detail}}]
    bits = [weekly_dates(entries[0])]
    if cleared_total >= 2:
        bits.append("{} cleared so far".format(cleared_total))
    bits = [b for b in bits if b]
    if bits:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": ":calendar: " + "  \u00b7  ".join(bits)}]})
    return blocks


def weekly_all_done(rows, cleared, accepted, today):
    """Whether every weekly goal the person took on for the week in progress is cleared.

    `accepted` are the entries on their acceptance rows (weekly_challenge.py writes one per goal
    taken on, whether or not a row of theirs holds it too, and never changes it), or None when
    they could not be read; `rows` are their rows and `cleared` the entries just cleared, which
    the rows may not show yet. A goal is known by its post and its words, which every copy of it
    keeps."""
    if not accepted:
        return False
    done = {(e["post"], e.get("text")) for e in cleared or []}
    for row in rows or []:
        for entry in weekly_entries(row.get(WEEKLY_COLUMN)):
            if entry.get("state") == "done" and as_date(entry["to"]) >= today:
                done.add((entry["post"], entry.get("text")))
    return all((e["post"], e.get("text")) in done for e in accepted)


def weekly_week_goals(accepted):
    """The week's goals from the acceptance entries, once each, in the order taken on."""
    seen, goals = set(), []
    for entry in accepted or []:
        key = (entry["post"], entry.get("text"))
        if key not in seen:
            seen.add(key)
            goals.append(entry)
    return goals


def weekly_final_text(user_id, goals):
    return "<@{}> cleared every weekly challenge this week: {}".format(
        user_id, and_join(e.get("text") or "the goal" for e in goals))


def weekly_final_blocks(user_id, goals, cleared_total=0):
    """The post when a log or a game clears the last of somebody's goals for the week: bigger
    than the one for a single goal (weekly_cleared_blocks), with each goal of the week on a line
    of its own. `goals` are the week's goals, all of them done (weekly_week_goals)."""
    n = len(goals)
    blocks = [{"type": "header", "text": {"type": "plain_text", "emoji": True,
               "text": ":trophy:  Every weekly challenge cleared"}},
              {"type": "section", "text": {"type": "mrkdwn", "text":
               "<@{}> cleared every challenge they took on this week \u2014 *{} of {}*. "
               "Congratulations!".format(user_id, n, n)}},
              {"type": "context", "elements": [{"type": "mrkdwn", "text": "\n".join(
                  ":white_check_mark:  {}".format(e.get("text") or "the goal")
                  for e in goals)}]}]
    bits = [weekly_dates(goals[0])] if goals else []
    if cleared_total >= 2:
        bits.append("{} cleared so far".format(cleared_total))
    bits = [b for b in bits if b]
    if bits:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn",
                       "text": ":calendar: " + "  \u00b7  ".join(bits)}]})
    return blocks
# <<< weekly challenge entries


# ------------------------------------------------------------------ the flow of an activity

def day_amounts(row, monday):
    """([(day, amount)], exact) for one person's row of one activity.

    The two lists spotter keeps are lined up from their recent end. When they are the same
    length every session has its day (exact). When `total` is longer, the older part cannot be
    trusted, so only the weeks inside the window are kept. A row with more dates than
    sessions cannot be lined up at all and gives nothing.
    """
    amounts = split_numbers(row.get("total"))
    days = [as_date(text) for text in split_dates(row.get("heatmap_dates"))]
    if not amounts or not days or any(day is None for day in days):
        return [], False
    count, tail = len(amounts), len(days)
    if count < tail:
        return [], False
    pairs = list(zip(days, amounts[count - tail:]))
    if count == tail:
        return pairs, True
    oldest = monday - timedelta(days=7 * WINDOW_WEEKS)
    return [(day, amount) for day, amount in pairs if day >= oldest], False


def weekly_totals(pairs, monday):
    """{Monday of the week: amount} for the weeks that are over. The week in progress is not."""
    weeks = {}
    for day, amount in pairs:
        start = monday_of(day)
        if start < monday:
            weeks[start] = weeks.get(start, 0.0) + amount
    return weeks


def activity_flow(rows, monday):
    """What a week of this activity looks like in the channel.

    people       logged it in the last WINDOW_WEEKS finished weeks
    typical      the median, across those people, of their usual weekly total (the median of
                 the weeks they logged in -- a week off does not pull it down)
    best         the biggest week anyone has had
    person_weeks (person, week) pairs with a log in the window: how busy the activity is
    rows / loose rows read, and how many of them could only be lined up from the recent end
    """
    window = [monday - timedelta(days=7 * k) for k in range(1, WINDOW_WEEKS + 1)]
    usual, best, person_weeks, used, loose = [], 0.0, 0, 0, 0
    for row in rows:
        if row.get("leaderboard_optout"):
            continue
        pairs, exact = day_amounts(row, monday)
        weeks = weekly_totals(pairs, monday)
        if not weeks:
            continue
        used += 1
        loose += 0 if exact else 1
        best = max(best, max(weeks.values()))
        recent = [weeks[start] for start in window if weeks.get(start, 0) > 0]
        if recent:
            usual.append(median(recent))
            person_weeks += len(recent)
    return {"people": len(usual), "typical": median(usual), "best": best,
            "person_weeks": person_weeks, "rows": used, "loose": loose}


# ------------------------------------------------------------------ levels and round figures

def level_share(level):
    level = max(1, int(level))
    if level <= len(SHARE):
        return SHARE[level - 1]
    return SHARE[-1] + LEVEL_EXTRA * (level - len(SHARE))


def level_note(level):
    return LEVEL_NOTES.get(int(level), LEVEL_NOTE_TOP)


def grid_floor(value, grid):
    """The largest figure on the grid that does not pass `value`; None when it is below them all."""
    best = None
    for figure in grid:
        if figure > value:
            break
        best = figure
    return best


def limit_figure(key):
    """The most a goal for this challenge may ask in a week, as a round figure of its grid: its
    LIMITS entry, or the top of the grid for one with none (a score)."""
    grid = GRIDS[CHALLENGES[key]["kind"]]
    limit = CHALLENGES[key]["limit"]
    return grid_floor(limit, grid) if limit else grid[-1]


def target_for(flow, base, level):
    """(goal, capped): the goal for this activity at this level, or (None, capped) when nothing
    sensible fits under the best week. `capped` says the level asked for more than the line --
    the best week, or the most the challenge ever asks in a week (LIMITS)."""
    info = CHALLENGES[base]
    ceiling = min(flow["best"] * CAP_SHARE, limit_figure(base))
    want = flow["typical"] * level_share(level)
    capped = want > ceiling
    goal = grid_floor(min(want, ceiling), GRIDS[info["kind"]])
    if goal is None or goal < info["floor"]:
        if info["floor"] > ceiling:
            return None, capped
        goal = info["floor"]
    return goal, capped


def next_step(taken, cleared):
    """How many rungs a challenge goes this week, negative for back down, from how many people
    took it on last week and how many of them did the goal that was posted.

    Up is the default: a goal that never moves is what this replaced, so last week only decides
    how far. STEP_UP when it was middling, or when too few took it on to say anything (a small
    crew often has one acceptance, or none); STEP_UP_STRONG when most of them did it; back
    STEP_DOWN when few did."""
    if taken >= ADAPT_MIN_TAKERS:
        share = cleared / float(taken)
        if share >= ADAPT_UP:
            return STEP_UP_STRONG
        if share <= ADAPT_DOWN:
            return -STEP_DOWN
    return STEP_UP


def goal_ladder(flow, key, floor):
    """The figures a challenge can take this week, smallest first: the round figures from the one
    level `floor` (the level input) gives up to the one level ADAPT_TOP gives, or the floor's own
    if that is higher. None passes the best-week line, and [] means nothing fits under it."""
    low, _capped = target_for(flow, key, floor)
    if low is None:
        return []
    high, _capped = target_for(flow, key, max(floor, ADAPT_TOP))
    return [figure for figure in GRIDS[CHALLENGES[key]["kind"]]
            if low <= figure <= max(low, high or low)]


def level_of(flow, key, goal):
    """How big a goal is in levels: the highest whose figure does not pass it. Levels that come to
    the same figure (the smallest worthwhile goal, or the best-week line holding several down)
    count as the lowest of them."""
    level, seen = 1, None
    for n in range(1, MAX_LEVEL + 1):
        figure, _capped = target_for(flow, key, n)
        if figure is None or figure > goal:
            break
        if seen is not None and figure == seen:
            break
        level, seen = n, figure
    return level


def settle_goal(flow, key, floor, last):
    """(level, goal, capped) for one challenge this week: its figure, how big that is in levels
    (level_of), and whether the best-week line is what holds it down.

    `floor` is the level input, which gives the lowest figure there is. `last` is how the
    challenge stood last week -- {"goal", "move"}, `move` being the rungs to go -- or None when
    it was not set, and it then starts at the lowest. Otherwise it goes `move` rungs along
    goal_ladder from last week's figure, and never off either end: a figure that cannot go
    further stays where it is, which is the only time the goal repeats."""
    ladder = goal_ladder(flow, key, floor)
    if not ladder:
        return floor, None, target_for(flow, key, floor)[1]
    if last:
        # the rung it stood on (-1: below the lowest, as when the level input has been raised, so a
        # step up lands on the lowest rather than skipping it)
        here = max([i for i, figure in enumerate(ladder) if figure <= int(last["goal"])] or [-1])
        goal = ladder[max(0, min(len(ladder) - 1, here + int(last["move"])))]
    else:
        goal = ladder[0]
    held = target_for(flow, key, max(floor, ADAPT_TOP))[1] and goal == ladder[-1]
    return level_of(flow, key, goal), goal, held


def move_word(target, before):
    """How a goal moved since last week: up, down or same; empty when it was not set then."""
    if not before:
        return ""
    return "up" if target > before else "down" if target < before else "same"


def ladder_edge(flow, key, floor, goal):
    """'top' or 'bottom' when the goal sits at an end of its ladder, and so cannot go further that
    way, else ''. A ladder of one figure is all top."""
    ladder = goal_ladder(flow, key, floor)
    if ladder and goal == ladder[-1]:
        return "top"
    return "bottom" if ladder and goal == ladder[0] else ""


def why_text(last, target, edge):
    """One line, for the run's output, on why a goal is what it is this week."""
    if not last:
        return "nothing from last week to go on: the lowest figure the level input gives"
    taken = last["taken"]
    said = ("{} of {} who took it on did the posted goal".format(last["cleared"], taken)
            if taken >= ADAPT_MIN_TAKERS else
            "too few took it on to judge ({})".format(taken))
    moved = move_word(target, last["goal"])
    if moved == "same":
        return "{}; already at the {} of its range".format(said, edge or "end")
    return "{}; {}".format(said, "a step up" if moved == "up" else "eased a step")


def stretch_goals(flow, key, level, goal, count=PICK_COUNT):
    """The bigger goals a person can pick instead of `goal`, set at `level`: the next `count`
    figures up the ladder, each from a higher level than the one before, so each is really bigger.
    None passes PICK_CAP_SHARE of the best week anyone has had, so every one is something somebody
    in the channel has done; a goal already near that line has fewer above it, or none."""
    grid = GRIDS[CHALLENGES[key]["kind"]]
    ceiling = min(flow["best"] * PICK_CAP_SHARE, limit_figure(key))
    out, above, rung = [], goal, level
    while len(out) < count and rung < MAX_LEVEL:
        rung += 1
        want = flow["typical"] * level_share(rung)
        figure = grid_floor(min(want, ceiling), grid)
        if figure is not None and figure > above:
            out.append(figure)
            above = figure
        if want >= ceiling:
            break                                 # every level above is held to the same line
    return out


def personal_flow(key, row, monday):
    """A person's own weeks of one challenge's activity, from their row: {"typical", "average",
    "best", "weeks", "by_week"}.

        typical   the median of the weeks they logged in the last WINDOW_WEEKS finished weeks
        average   the mean of those weeks
        best      their biggest finished week the row shows
        weeks     how many of those last weeks they logged in: how steady they are
        by_week   {Monday: amount} for every finished week the row shows

    A game row keeps no weeks, so its pace (games a week since the first one) or its best score
    stands in for all three figures."""
    info, row = CHALLENGES[key], row or {}
    if info["game"]:
        if info["kind"] == "plays":
            first = as_date(row.get("first_seen")) or as_date(row.get("updated_at"))
            weeks = max(1.0, (monday - first).days / 7.0) if first else 1.0
            value = _amount(row.get("total_planks")) / weeks
        else:
            value = _amount(row.get("personal_best_single_set"))
        return {"typical": value, "average": value, "best": value,
                "weeks": 1 if value > 0 else 0, "by_week": {}}
    pairs, _exact = day_amounts(row, monday)
    by_week = weekly_totals(pairs, monday)
    window = [monday - timedelta(days=7 * k) for k in range(1, WINDOW_WEEKS + 1)]
    recent = [by_week[start] for start in window if by_week.get(start, 0) > 0]
    return {"typical": median(recent), "average": sum(recent) / len(recent) if recent else 0.0,
            "best": max(by_week.values()) if by_week else 0.0, "weeks": len(recent),
            "by_week": by_week}


def earlier_entries(row, key, post_id, monday):
    """A person's entries for this same challenge from before this week, newest first."""
    row = row or {}
    row_type, here = str(row.get("row_type") or ""), entry_id(post_id, key)
    found = [e for e in weekly_entries(row.get(WEEKLY_COLUMN))
             if e["post"] != here and key_of_entry(row_type, e) == key
             and as_date(e["from"]) < monday]
    return sorted(found, key=lambda e: e["from"], reverse=True)


def personal_step(ratio, streak, steady):
    """How many rungs a person's goal goes after a week, from `ratio` (what they did against it),
    `streak` (weeks cleared in a row) and whether they have been `steady` (logged in two of the
    last weeks): two when they beat it by PERSONAL_CRUSH or have cleared PERSONAL_STREAK in a row,
    one when they cleared it, none when they came close, back one when they fell short. Without a
    steady record it is one step up at most."""
    if ratio >= PERSONAL_CRUSH:
        step = 2
    elif ratio >= 1.0:
        step = 2 if streak >= PERSONAL_STREAK else 1
    elif ratio >= PERSONAL_CLOSE:
        step = 0
    else:
        step = -1
    return step if steady else min(step, 1)


def personal_challenge(row, key, post_id, monday, floor):
    """A person's own challenge for the week, worked out from their own weeks (personal_flow) and
    from how they did the last time they took the same challenge on: {"goal", "sizes", "known",
    "basis"}.

    A first challenge starts at the smallest figure of their own ladder (70% of their typical
    week, with level `floor`); after that it moves along the ladder as a team goal does
    (settle_goal), by personal_step. `sizes` are the goal and the bigger ones they can pick
    instead (stretch_goals). `basis` is the line that says where the goal comes from. Someone
    with nothing logged in the last WINDOW_WEEKS weeks starts at the smallest worthwhile goal, with
    no sizes to pick from."""
    info = CHALLENGES[key]
    mine = personal_flow(key, row, monday)
    if mine["typical"] <= 0:
        return {"goal": info["floor"], "sizes": [], "known": False,
                "basis": "You have not logged this one in the last {} weeks, so it starts small "
                         "and will fit you better from next week.".format(WINDOW_WEEKS)}
    flow = {"typical": mine["typical"], "best": mine["best"] * PERSONAL_ROOM}
    earlier = earlier_entries(row, key, post_id, monday)
    if not goal_ladder(flow, key, floor):
        # even the smallest worthwhile goal is more than they have ever done: the smallest round
        # figure under their level-`floor` share it is
        grid = GRIDS[info["kind"]]
        goal = min(grid_floor(level_share(floor) * mine["typical"], grid) or grid[0], limit_figure(key))
        level, basis = 1, "Your recent weeks are small, so this starts at the smallest round figure."
    elif not earlier:
        level, goal, _held = settle_goal(flow, key, floor, None)
        basis = "You usually log about {} a week, so this starts a little under that.".format(
            logged_text(key, mine["typical"]))
    else:
        last = earlier[0]
        before = int(last["goal"])
        if info["game"]:
            did_it = last.get("state") == "done"
            ratio = 1.25 if did_it else 0.7                  # a game keeps no partial figure
            said = "You cleared it last time" if did_it else "You did not clear it last time"
        else:
            did = mine["by_week"].get(as_date(last["from"]), 0.0)
            ratio = min(did / float(before), PERSONAL_RATIO_CAP)
            if last.get("state") == "done":
                ratio = max(ratio, 1.0)
            said = "Last time you did {} against {}".format(logged_text(key, did),
                                                            amount_text(key, before))
        streak = 0
        for entry in earlier[:PERSONAL_STREAK]:
            if entry.get("state") != "done":
                break
            streak += 1
        step = personal_step(ratio, streak, mine["weeks"] >= 2)
        level, goal, _held = settle_goal(flow, key, floor, {"goal": before, "move": step})
        basis = "{}, so {}.".format(
            said, "this is a step up" if goal > before else
            "it stays about the same" if goal == before else "this eases a little")
    if goal >= limit_figure(key):
        # however far they have climbed, or whatever their weeks look like, a goal stops here
        basis = "You are at the most this challenge asks in a week ({}), so it goes no higher.".format(
            amount_text(key, limit_figure(key)))
    return {"goal": goal, "sizes": [goal] + stretch_goals(flow, key, level, goal),
            "known": True, "basis": basis}


def duration_text(seconds):
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        if not minutes:
            return "{} hour{}".format(hours, "" if hours == 1 else "s")
        return "{} h {} min".format(hours, minutes)
    if minutes:
        return "{} min {} sec".format(minutes, secs) if secs else "{} min".format(minutes)
    return "{} sec".format(secs)


def amount_text(base, value):
    kind = CHALLENGES[base]["kind"]
    if kind == "minutes":
        return duration_text(value * 60)
    if kind == "seconds":
        return duration_text(value)
    return "{:,}".format(int(round(value)))


def logged_text(base, value):
    """An amount somebody has logged, for a sentence about their weeks: a whole number of minutes
    ('23 min'), where a typical week that falls between two logs would read '22 min 30 sec'."""
    if CHALLENGES[base]["kind"] == "minutes":
        value = int(value + 0.5)
    return amount_text(base, value)


def describe(base, goal):
    """The goal as words: '100 pushups', '10 min of plank', '2 hours of yoga'."""
    return CHALLENGES[base]["phrase"].format(amount_text(base, goal))


def plan_week(rows, monday, level, only=None, skip=None, min_people=MIN_PEOPLE,
              max_challenges=MAX_CHALLENGES, memory=None):
    """(goals, left_out): the week's goals, busiest activity first, and why any activity that
    has rows but got no goal did not. `memory` is how each challenge stood last week
    (last_week): with it a challenge starts where it was and `level` is only the lowest it may
    be set at; without it every challenge is set at `level`."""
    by_base = {}
    for row in rows:
        row_type = str(row.get("row_type") or "")
        base = row_type[:-len("_users")] if row_type.endswith("_users") else ""
        if base in ACTIVITIES:
            by_base.setdefault(base, []).append(row)
    goals, left_out = [], []
    for base in ACTIVITIES:
        if not by_base.get(base) or (only and base not in only):
            continue
        if skip and base in skip:
            left_out.append({"activity": base, "reason": "skipped by input"})
            continue
        flow = activity_flow(by_base[base], monday)
        if flow["people"] < min_people:
            left_out.append({"activity": base, "reason": "{} logged it in the last {} weeks, {} "
                             "needed".format(plural_people(flow["people"]), WINDOW_WEEKS,
                                             min_people)})
            continue
        last = (memory or {}).get(base)
        set_at, goal, capped = settle_goal(flow, base, level, last)
        if goal is None:
            left_out.append({"activity": base, "reason": "no goal fits under the best week "
                             "({})".format(amount_text(base, flow["best"]))})
            continue
        goals.append({
            "key": base, "target": goal, "capped": capped, "people": flow["people"],
            "person_weeks": flow["person_weeks"], "typical": flow["typical"],
            "best": flow["best"], "loose": flow["loose"], "level": set_at,
            "prev": int(last["goal"]) if last else 0,
            "edge": ladder_edge(flow, base, level, goal),
            "up": stretch_goals(flow, base, set_at, goal),
            "ladder": [target_for(flow, base, n)[0] for n in range(1, 6)],
        })
    goals.sort(key=lambda g: (-g["people"], -g["person_weeks"], ACTIVITY_ORDER[g["key"]]))
    for extra in goals[max_challenges:]:
        left_out.append({"activity": extra["key"], "reason": "over the limit of {} goals".format(
            max_challenges)})
    return goals[:max_challenges], left_out


def is_game(key):
    return bool(CHALLENGES[key]["game"])


def game_flow(rows, monday):
    """What a game looks like in the channel, from its player rows.

    Active players are those who finished a game in the last GAME_ACTIVE_DAYS. For each of the
    two challenges: `typical` is the median over them of what they do (their games a week since
    they first played; their best score) and `best` the most anyone does (the highest pace, the
    highest score anyone has ever had).
    """
    cutoff = monday - timedelta(days=GAME_ACTIVE_DAYS)
    pace, bests, ever = [], [], 0
    for row in rows:
        if row.get("leaderboard_optout"):
            continue
        played = _amount(row.get("total_planks"))
        score = _amount(row.get("personal_best_single_set"))
        ever = max(ever, score)
        last = as_date(row.get("updated_at"))
        if played < 1 or last is None or last < cutoff:
            continue
        first = as_date(row.get("first_seen")) or last
        weeks = max(1.0, (monday - first).days / 7.0)
        pace.append(played / weeks)
        bests.append(score)
    return {"people": len(pace),
            "plays": {"typical": median(pace), "best": max(pace or [0])},
            "score": {"typical": median(bests), "best": ever}}


def plan_games(rows, monday, level, only=None, skip=None, min_people=MIN_PEOPLE,
               max_games=MAX_GAMES, memory=None):
    """(goals, left_out): the games' challenges -- two for each game with enough players, busiest
    game first, each game's two together. `memory` as in plan_week."""
    by_game = {}
    for row in rows:
        game = GAME_OF_ROW.get(str(row.get("row_type") or ""))
        if game:
            by_game.setdefault(game, []).append(row)
    found, left_out = [], []
    for game in GAMES:
        if not by_game.get(game):
            continue
        flow = game_flow(by_game[game], monday)
        goals = []
        for kind in ("plays", "score"):
            key = game + "_" + kind
            if (only and key not in only) or (skip and key in skip):
                if skip and key in skip:
                    left_out.append({"activity": key, "reason": "skipped by input"})
                continue
            if flow["people"] < min_people:
                left_out.append({"activity": key, "reason": "{} played it in the last {} days, {} "
                                 "needed".format(plural_people(flow["people"]), GAME_ACTIVE_DAYS,
                                                 min_people)})
                continue
            part = flow[kind]
            last = (memory or {}).get(key)
            set_at, goal, capped = settle_goal(part, key, level, last)
            if goal is None:
                left_out.append({"activity": key, "reason": "no challenge fits under the best "
                                 "({})".format(amount_text(key, part["best"]))})
                continue
            goals.append({
                "key": key, "target": goal, "capped": capped, "people": flow["people"],
                "person_weeks": flow["people"], "typical": part["typical"], "best": part["best"],
                "loose": 0, "level": set_at, "prev": int(last["goal"]) if last else 0,
                "edge": ladder_edge(part, key, level, goal),
                "up": stretch_goals(part, key, set_at, goal),
                "ladder": [target_for(part, key, n)[0] for n in range(1, 6)]})
        if goals:
            found.append(goals)
    found.sort(key=lambda goals: (-goals[0]["people"], ACTIVITY_ORDER[goals[0]["key"]]))
    for goals in found[max_games:]:
        for goal in goals:
            left_out.append({"activity": goal["key"], "reason": "over the limit of {} games".format(
                max_games)})
    return [goal for goals in found[:max_games] for goal in goals], left_out


def split_groups(goals, top_count=TOP_COUNT, chunk=THREAD_CHUNK):
    """[[goals in the channel message], [goals in a reply], ...].

    The busiest `top_count` stay in the channel message; the rest go to the thread in replies
    of about equal size. A thread that would hold only one or two is folded back in instead:
    a reply for a single line is more clutter than the line is worth.
    """
    if len(goals) < top_count + SPILL_MIN:
        return [list(goals)]
    groups = [list(goals[:top_count])]
    rest = list(goals[top_count:])
    replies = -(-len(rest) // chunk)                       # ceiling division
    size = -(-len(rest) // replies)
    for start in range(0, len(rest), size):
        groups.append(rest[start:start + size])
    return groups


# ------------------------------------------------------------------ the post, as Block Kit

def _row_size(value):
    """Buttons to a row as a spec carries it: 1 to BUTTONS_PER_ROW, the most Slack shows without folding."""
    return _int(value, BUTTONS_PER_ROW, 1, BUTTONS_PER_ROW)


def _section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _plain(text):
    """Text that goes into Slack mrkdwn without being read as markup."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def short_names(people):
    """First names for a line of text. Two on the line who share one get a last initial."""
    words = [re.sub(r"\([^)]*\)", "", str(p.get("name") or "")).split() for p in people]
    firsts = [w[0] if w else "" for w in words]
    out = []
    for person, parts, first in zip(people, words, firsts):
        if not first:
            out.append("<@{}>".format(person.get("id")))
        elif firsts.count(first) > 1 and len(parts) > 1:
            out.append("{} {}.".format(_plain(first), _plain(parts[-1][0])))
        else:
            out.append(_plain(first))
    return out


def names_text(people, key=None, personal=False):
    """'Priya, Jack and Sam', or 'Priya, Jack, Sam +2 more' past NAMES_SHOWN. On a personal post, given
    the challenge's `key`, each name carries that person's own goal -- 'Priya (3 hours)' -- since the
    category alone ('Yoga, 2 people') says nothing of what each of them took on."""
    shown = short_names(people[:NAMES_SHOWN])
    if personal and key:
        shown = ["{} ({})".format(name, amount_text(key, person["goal"])) if person.get("goal") else name
                 for name, person in zip(shown, people)]
    extra = len(people) - len(shown)
    if extra:
        return ", ".join(shown) + " +{} more".format(extra)
    if len(shown) > 1:
        return ", ".join(shown[:-1]) + " and " + shown[-1]
    return shown[0]


def accepted_line(people, frozen=False, key=None, personal=False):
    """The line under a goal, as a challenge rather than a tally: who has taken it on, and a
    nudge to join them. Once the week is over it just says who did."""
    if not people:
        return "_Nobody took this one on._" if frozen else \
            "_Nobody has taken this on yet. Who's going first?_"
    names = names_text(people, key, personal)
    count = len(people)
    if frozen:
        return "*{}* took it on  \u00b7  {}".format(count, names)
    return "*{}* {} taken it on  \u00b7  {}  \u00b7  _Your move._".format(
        count, "has" if count == 1 else "have", names)


def trend_text(item):
    """'up from 75' or 'down from 100' for a goal that moved since last week; '' when it did not
    (or was not set then)."""
    before = int(item.get("prev") or 0)
    if not before or before == item["target"]:
        return ""
    return "{} from {}".format("up" if item["target"] > before else "down",
                               amount_text(item["key"], before))


def goal_line(item, personal=False, frozen=False):
    """The goal as the post writes it: its icon, the goal, and how it has moved since last week. A
    personal post names the category instead, with a hint that the target is revealed on a press
    (and none once the week is over)."""
    if personal:
        return "{}  *{}*{}".format(CHALLENGES[item["key"]]["icon"], CHALLENGES[item["key"]]["label"],
                                  "" if frozen else "  \u00b7  _{}_".format(PERSONAL_HINT))
    trend = trend_text(item)
    return "{}  *{}*{}".format(CHALLENGES[item["key"]]["icon"],
                              describe(item["key"], item["target"]),
                              "  ·  _{}_".format(trend) if trend else "")


def challenge_block(item, people, value, personal=False):
    """A goal as a line of text with its button, and under it, in small print, who has taken it
    on. Once the week is over there is no button and the line says who did."""
    section = _section(goal_line(item, personal, frozen=value is None))
    section["block_id"] = "wc_" + item["key"]
    if value is not None:
        section["accessory"] = {
            "type": "button", "action_id": "wchallenge_accept_" + item["key"],
            "text": {"type": "plain_text", "text": REVEAL_TEXT if personal else BUTTON_TEXT,
                     "emoji": True}, "value": value}
    line = _context(accepted_line(people, frozen=value is None, key=item["key"], personal=personal))
    line["block_id"] = "wcc_" + item["key"]
    return [section, line]


def accept_button(item, value, text=BUTTON_TEXT):
    return {"type": "button", "action_id": "wchallenge_accept_" + item["key"],
            "text": {"type": "plain_text", "text": text, "emoji": True}, "value": value}


def challenge_block_merged(item, people, value, personal=False):
    """Style 2: the goal and who has taken it on in one block, the button beside it."""
    text = "{}\n{}".format(goal_line(item, personal, frozen=value is None),
                          accepted_line(people, frozen=value is None, key=item["key"], personal=personal))
    section = _section(text)
    section["block_id"] = "wc_" + item["key"]
    if value is not None:
        section["accessory"] = accept_button(item, value, REVEAL_TEXT if personal else BUTTON_TEXT)
    return [section]


def challenge_blocks_grid(challenges, people, value_of, frozen, listed=None, main=True,
                          personal=False, per_row=BUTTONS_PER_ROW):
    """Style 3: the message's buttons in rows of `per_row` (at most BUTTONS_PER_ROW), each labelled with its goal, then,
    under a divider and a heading, only the goals somebody has accepted, one line each. Nobody yet
    says so once, not per goal. Once the week is over there are no buttons and every goal is
    listed with who took it on. Only the channel message carries the list, and it lists the whole
    post (`listed`), so what is accepted in a reply shows at the top; a reply is just its buttons."""
    blocks = []
    if not frozen:
        buttons = [accept_button(c, value_of(c["key"]), "{} {}".format(
                       CHALLENGES[c["key"]]["icon"],
                       CHALLENGES[c["key"]]["label"] if personal else describe(c["key"], c["target"])
                   )[:BUTTON_MAX]) for c in challenges]
        for start in range(0, len(buttons), per_row):
            actions = {"type": "actions", "elements": buttons[start:start + per_row]}
            actions["block_id"] = "wc_buttons" + (str(start // per_row) if start else "")
            blocks.append(actions)
        if personal and main:
            # the buttons carry no figure, so one line under them says why, and where to find it
            hint = _context(PERSONAL_GRID_HINT)
            hint["block_id"] = "wc_hint"
            blocks.append(hint)
    if not main:
        return blocks
    lines = []
    for c in (listed or challenges):
        who = people.get(c["key"], [])
        if not who and not frozen:
            continue
        head = "{}  *{}*".format(CHALLENGES[c["key"]]["icon"],
                               CHALLENGES[c["key"]]["label"] if personal
                               else describe(c["key"], c["target"]))
        if who:
            lines.append("{}  \u00b7  *{}*  \u00b7  {}".format(
                head, len(who), names_text(who, c["key"], personal)))
        else:
            lines.append("{}  \u00b7  _nobody took this one on_".format(head))
    if lines:
        # A divider and a heading, so the list reads as the record of who is in. It shows once
        # somebody has accepted (or in the ended view, which has no buttons above it to part from).
        if not frozen:
            blocks.append({"type": "divider"})
        blocks.append({"type": "header", "text": {"type": "plain_text", "text": ACCEPTED_HEADER,
                                                  "emoji": True}})
        accepted = _section("\n".join(lines))
        accepted["block_id"] = "wc_accepted"
        blocks.append(accepted)
    elif not frozen:
        blocks.append(_context("Nobody has taken one on yet. Who's going first?"))
    return blocks


def accepted_summary(people):
    """The line under the rules: how many challenges have been taken on in all, and by how many
    people -- for the whole post, so it reads the same wherever someone pressed. Someone who has
    opted out is counted, as everywhere, and never named."""
    taken = sum(len(v) for v in people.values())
    who = len({p["id"] for v in people.values() for p in v})
    if not taken:
        return ":crossed_swords: No challenges taken on yet. Be the first."
    return ":crossed_swords: *{}* accepted by *{}* so far".format(
        plural(taken, "challenge"), plural(who, "person", "people"))


def clean_banner(value, warnings):
    """The banner_url input as Slack will take it (a public https link), or "" with a warning."""
    banner = str(value or "").strip()
    if banner and not (banner.startswith("https://") and len(banner) <= BANNER_MAX
                       and " " not in banner):
        warnings.append("banner_url ignored: it must be a public https:// image link "
                        "of at most {} characters, with no spaces".format(BANNER_MAX))
        return ""
    return banner


def intro_line(spec):
    if spec.get("intro"):
        return spec["intro"]
    grid = spec.get("style") == 3
    if spec.get("personal"):
        lines = PERSONAL_INTRO_LINES_GRID if grid else PERSONAL_INTRO_LINES
    else:
        lines = INTRO_LINES_GRID if grid else INTRO_LINES
    return lines[spec["week"].isocalendar()[1] % len(lines)]


def build_blocks(spec, people, value_of=None):
    """One message of the set, as blocks.

    spec    week (the Monday), level, index (0 = the channel message, 1.. = replies), more (how
            many goals are in the thread), challenges [{key, target}], testing, frozen, intro,
            style (1 text + button + status line, 2 status folded in, 3 button grid),
            everything (the channel message only: every challenge of the post, for style 3's list),
            banner (the channel message only: an image url shown above the title)
    people  {activity: [{id, name}, ...]}, who has accepted, earliest first
    value_of  function from an activity to its button's value; not needed once frozen
    """
    frozen = bool(spec.get("frozen"))
    personal = bool(spec.get("personal"))
    label = week_label(spec["week"])
    main = spec["index"] == 0
    if main:
        title = ":checkered_flag:  *Weekly challenges*  ·  {}  ·  ended" if frozen else \
            ":trophy:  *Weekly challenges*  ·  {}"
    elif all(is_game(c["key"]) for c in spec["challenges"]):
        title = ":video_game:  *Brain games*  ·  {}" + ("  ·  ended" if frozen else "")
    else:
        title = ":sparkles:  *More challenges*  ·  {}" + ("  ·  ended" if frozen else "")
    blocks = [_section(title.format(label))]
    if main and spec.get("banner"):
        blocks.insert(0, {"type": "image", "image_url": spec["banner"], "alt_text": BANNER_ALT})
    if not main and not frozen and all(is_game(c["key"]) for c in spec["challenges"]):
        blocks.append(_context(GAMES_NOTE))
    if main and not frozen:
        summary = _context(accepted_summary(people))
        summary["block_id"] = "wc_summary"
        blocks += [_section(intro_line(spec)), _section(PERSONAL_RULES if personal else RULES),
                   summary]
    if spec.get("testing") and not frozen:
        blocks.append(_context(TEST_NOTE))
    style = spec.get("style") or DEFAULT_STYLE
    if style == 3:
        blocks += challenge_blocks_grid(spec["challenges"], people, value_of, frozen,
                                        listed=spec.get("everything"), main=main,
                                        personal=personal,
                                        per_row=_row_size(spec.get("per_row")))
    else:
        one = challenge_block_merged if style == 2 else challenge_block
        for item in spec["challenges"]:
            blocks += one(item, people.get(item["key"], []),
                          None if frozen else value_of(item["key"]), personal=personal)
    if main:
        if frozen:
            blocks.append({"type": "divider"})
            blocks.append(_context(SAID_ENDED.replace(":hourglass: ", "")))
        elif spec.get("more"):
            blocks.append({"type": "divider"})
            blocks.append(_section(MORE_IN_THREAD.format(
                spec["more"], "" if spec["more"] == 1 else "s")))
    return blocks


def fallback_text(spec):
    """What a notification or a screen reader shows in place of the blocks."""
    names = ", ".join(CHALLENGES[c["key"]]["label"] if spec.get("personal")
                      else describe(c["key"], c["target"]) for c in spec["challenges"][:6])
    if len(spec["challenges"]) > 6:
        names += ", ..."
    head = "Weekly challenges" if spec["index"] == 0 else "More challenges"
    return "{} ({}): {}".format(head, week_label(spec["week"]), names)


def game_runs(goals, size=THREAD_CHUNK):
    """Game challenges as runs of about `size`, a run to a message, cut between games only so a game's
    challenges stay together. (A game has one or two: one when there is no figure to set for the
    other, so the total is often odd and a cut at a fixed number can split a pair.) A last run of
    fewer than SPILL_MIN is folded into the one before it: a reply for a button or two, with its own
    title and notes, is more clutter than they are worth."""
    games = []                                          # [[one game's challenges], ...], in order
    for goal in goals:
        if games and CHALLENGES[games[-1][-1]["key"]]["row_type"] == CHALLENGES[goal["key"]]["row_type"]:
            games[-1].append(goal)
        else:
            games.append([goal])
    runs = []
    for game in games:
        if runs and len(runs[-1]) + len(game) <= size:
            runs[-1].extend(game)
        else:
            runs.append(list(game))
    if len(runs) > 1 and len(runs[-1]) < SPILL_MIN:
        runs[-2].extend(runs.pop())
    return runs


def spec_challenge(goal):
    """A goal as a message carries it: its key and figure, last week's figure when the goal has
    moved since (what trend_text reads), and the bigger goals on offer to whoever accepts it."""
    item = {"key": goal["key"], "target": goal["target"]}
    if goal.get("prev") and goal["prev"] != goal["target"]:
        item["prev"] = int(goal["prev"])
    if goal.get("up"):
        item["up"] = [int(figure) for figure in goal["up"]]
    return item


def group_specs(goals, monday, level, testing=False, intro="", top_count=TOP_COUNT,
                style=DEFAULT_STYLE, banner="", personal=False, per_row=BUTTONS_PER_ROW):
    """One spec per message of the set: the activities as split_groups cuts them, then the
    games in messages of their own (game_runs). Fewer than SPILL_MIN game challenges are not worth
    a reply and ride in the channel message; with no activities the games fill the channel message."""
    plain = [g for g in goals if not is_game(g["key"])]
    games = [g for g in goals if is_game(g["key"])]
    groups = split_groups(plain, top_count) if plain else []
    if games and groups and len(games) < SPILL_MIN:
        groups[0] = groups[0] + games
    elif games and groups:
        groups += game_runs(games)
    elif games:
        runs = game_runs(games, top_count + top_count % 2)       # the first run is the channel message
        groups = [runs[0]] + game_runs([goal for run in runs[1:] for goal in run])
    more = sum(len(g) for g in groups[1:])
    everything = [{"key": g["key"], "target": g["target"]} for group in groups for g in group]
    return [{"week": monday, "level": level, "index": index, "more": more if index == 0 else 0,
             "challenges": [spec_challenge(g) for g in group],
             "testing": testing, "intro": intro, "style": style, "personal": personal,
             "per_row": per_row, "everything": everything if index == 0 else None,
             "banner": banner if index == 0 else ""}
            for index, group in enumerate(groups)]


# ------------------------------------------------------------------ what a press carries

TEST_PREFIX = "wct|"
PROGRESS_PREFIX = "wcp|"


def live_value(post_id, key):
    return "wc|{}|{}|accept".format(post_id, key)


def goal_value(post_id, key, goal):
    """What a size button on a real post carries: the post, the challenge and the goal it sets."""
    return "wcg|{}|{}|{}".format(post_id, key, int(goal))


def optout_value(post_id, key):
    """What the opt-out button on a real post carries: the post and the challenge."""
    return "wco|{}|{}".format(post_id, key)


def test_optout_value(key, ts, main_ts):
    """The same on a test post, which keeps its list in its own buttons: the message the person
    pressed Accept in, and the channel message of its post ('-' when it is that one), so the
    message can be read back and the person taken off its list."""
    return "wcot|{}|{}|{}".format(key, ts, main_ts or "-")


def test_goal_value(key, goal, rung, ts="", main_ts=""):
    """The same on a test post, which has no post row to look the sizes up in: the goal and which
    size it is (0 posted, 1 Stretch, 2 Summit) are all that is needed to say it back. On a personal
    post a pick is what takes a person on, so it also says which message to put them on the list of
    (`ts`, and `main_ts` when that was a reply), as test_optout_value does."""
    value = "wcgt|{}|{}|{}".format(key, int(goal), int(rung))       # `rung`: the name's place in EVERY_PICK
    return "{}|{}|{}".format(value, ts, main_ts or "-") if ts else value


def test_value(spec, people, main_ts, key):
    """A test post keeps its state in the button: this message's goals and who has accepted
    each. Every button of the message carries the same state, differing only in `k`."""
    whole = spec.get("everything") or spec["challenges"]      # the channel message holds the whole post
    here = {c["key"] for c in whole}
    # A personal post's buttons show no figure and its notes are worked out for whoever presses, so
    # last week's figure and the team's bigger sizes are not carried: that room goes to the list of
    # who has accepted, which a first message of 20 challenges needs.
    carried = not spec.get("personal")
    state = {"w": spec["week"].isoformat(), "l": spec["level"], "g": spec["index"],
             "n": spec["more"], "m": main_ts,
             "c": [[c["key"], c["target"]]
                   + ([c.get("prev") or 0] + list(c.get("up") or [])
                      if carried and (c.get("prev") or c.get("up")) else [])
                   for c in spec["challenges"]],
             "a": {k: [[p["id"], p["name"]] + ([p["goal"]] if p.get("goal") else []) for p in v]
                   for k, v in people.items() if v and k in here},
             "k": key}
    if spec["index"] == 0 and 0 < len(spec.get("intro") or "") <= TEST_INTRO_MAX:
        state["i"] = spec["intro"]
    if spec.get("style", DEFAULT_STYLE) != DEFAULT_STYLE:
        state["y"] = spec["style"]
    if spec.get("personal"):
        state["pe"] = 1
    if _row_size(spec.get("per_row")) != BUTTONS_PER_ROW:
        state["r"] = _row_size(spec.get("per_row"))
    if spec["index"] == 0 and 0 < len(spec.get("banner") or "") <= TEST_BANNER_MAX:
        state["b"] = spec["banner"]
    if len(whole) > len(spec["challenges"]):
        state["e"] = [[c["key"], c["target"]] for c in whole]
    return TEST_PREFIX + json.dumps(state, separators=(",", ":"), ensure_ascii=False)


def parse_test_value(value):
    """(spec, people, main_ts, key) from a test button's value, or None if it is not one."""
    if not str(value).startswith(TEST_PREFIX):
        return None
    try:
        state = json.loads(value[len(TEST_PREFIX):])
        week = as_date(state["w"])
        challenges = []
        # [key, target], then (when there is any) last week's figure, 0 if it did not move, and the
        # bigger goals on offer
        for k, t, *rest in state["c"]:
            item = {"key": k, "target": int(t)}
            if rest and int(rest[0]) > 0:
                item["prev"] = int(rest[0])
            if len(rest) > 1:
                item["up"] = [int(figure) for figure in rest[1:]]
            challenges.append(item)
        if not week or any(c["key"] not in CHALLENGES for c in challenges) or \
                state["k"] not in {c["key"] for c in challenges}:
            return None
        people = {k: [dict({"id": str(i), "name": str(n)},
                           **({"goal": _int(rest[0], 0, 1, 10 ** 9)} if rest and _int(rest[0], 0, 1, 10 ** 9) else {}))
                      for i, n, *rest in v]
                  for k, v in (state.get("a") or {}).items() if k in CHALLENGES}
        everything = [{"key": k, "target": int(t)} for k, t in state.get("e") or []
                      if k in CHALLENGES]
        spec = {"week": week, "level": int(state["l"]), "index": int(state["g"]),
                "more": int(state["n"]), "challenges": challenges, "testing": True,
                "intro": str(state.get("i") or ""),
                "style": _int(state.get("y"), DEFAULT_STYLE, 1, max(POST_STYLES)),
                "personal": bool(state.get("pe")), "per_row": _row_size(state.get("r")),
                "everything": everything or (challenges if int(state["g"]) == 0 else None),
                "banner": str(state.get("b") or "")}
        return spec, people, str(state.get("m") or ""), state["k"]
    except (ValueError, KeyError, TypeError):
        return None


def parse_value(value):
    """('live', post_id, key) | ('test', parsed) | ('progress', thread ts) | ('goal', post_id, key,
    goal) | ('goal_test', key, goal, rung[, ts, main ts]) | ('optout', post_id, key) |
    ('optout_test', key, ts, main ts) | None."""
    value = str(value or "").strip()
    if value.startswith(PROGRESS_PREFIX):
        thread = value[len(PROGRESS_PREFIX):].strip()
        return ("progress", thread if re.match(r"^\d+(\.\d+)?$", thread) else "")
    if value.startswith(TEST_PREFIX):
        parsed = parse_test_value(value)
        return ("test", parsed) if parsed else None
    parts = value.split("|")
    if len(parts) == 4 and parts[0] == "wc" and parts[3] == "accept" and parts[2] in CHALLENGES \
            and parts[1]:
        return "live", parts[1], parts[2]
    stamp = re.compile(r"^\d+(\.\d+)?$")
    if len(parts) == 3 and parts[0] == "wco" and parts[1] and parts[2] in CHALLENGES:
        return "optout", parts[1], parts[2]
    if len(parts) == 4 and parts[0] == "wcot" and parts[1] in CHALLENGES and stamp.match(parts[2]) \
            and (parts[3] == "-" or stamp.match(parts[3])):
        return "optout_test", parts[1], parts[2], "" if parts[3] == "-" else parts[3]
    figures = re.compile(r"^\d{1,9}$")
    if len(parts) == 4 and parts[0] == "wcg" and parts[1] and parts[2] in CHALLENGES \
            and figures.match(parts[3]):
        return "goal", parts[1], parts[2], int(parts[3])
    if len(parts) in (4, 6) and parts[0] == "wcgt" and parts[1] in CHALLENGES \
            and figures.match(parts[2]) and parts[3] in [str(n) for n in range(len(EVERY_PICK))]:
        if len(parts) == 4:
            return "goal_test", parts[1], int(parts[2]), int(parts[3])
        if stamp.match(parts[4]) and (parts[5] == "-" or stamp.match(parts[5])):
            return "goal_test", parts[1], int(parts[2]), int(parts[3]), parts[4], \
                "" if parts[5] == "-" else parts[5]
    return None


def people_by_key(rows):
    """{activity: [{id, name}]} from acceptance rows: one entry per person, earliest first."""
    ordered = sorted(rows, key=lambda r: (_float(r.get("last_processed_ts")),
                                          str(r.get("group_id") or "")))
    seen, out = set(), {}
    for row in ordered:
        key, who = row.get("grant_type"), row.get("group_id")
        if (row.get("status") or "in") != "in" or key not in CHALLENGES or not who \
                or (key, who) in seen:
            continue
        seen.add((key, who))
        entry = weekly_entry_from(row.get("content"))          # their own goal, which they may have picked
        out.setdefault(key, []).append({"id": who, "name": row.get("member_name") or "",
                                        "goal": int(entry["goal"]) if entry else 0})
    return out


def signature(people, keys):
    """What a message would show for these goals: for telling whether a re-read changed it."""
    return tuple((k, tuple(p["id"] for p in people.get(k, []))) for k in keys)


# ------------------------------------------------------------------ picking your own climb

def kept_sizes(entry):
    """The sizes an acceptance kept when its person was offered them (personal_challenge), as a
    list of figures; [] for one that kept none."""
    sizes = (entry or {}).get("sizes")
    if not isinstance(sizes, list):
        return []
    figures = [_int(size, 0, 0, 10 ** 9) for size in sizes]
    return figures if figures and all(f > 0 for f in figures) else []


def lighter_starts(anchor, floor, grid):
    """Up to two round figures of `grid` lighter than `anchor`, smallest first: about 40% and 70% of
    it, never under the round figure at or below half the smallest worthwhile goal (`floor`), and
    each really bigger than the one before."""
    lowest = grid_floor(floor / 2.0, grid) or grid[0]
    sizes = []
    for share in (0.4, 0.7):
        figure = max(grid_floor(anchor * share, grid) or grid[0], lowest)
        if figure < anchor and (not sizes or figure > sizes[-1]):
            sizes.append(figure)
    return sizes


def starter_sizes(key, anchor):
    """The sizes on offer to someone new to a challenge, smallest first, the last being `anchor`: the
    figure that fits them (their own first target, or the active crew's pace when they have no
    weeks of their own). The lighter ones come from lighter_starts. When the grid has nothing
    lighter than `anchor` -- it is the smallest figure on it, as it is for someone whose recent
    weeks are small -- the figures under the grid's smallest (STARTER_FIGURES) are used, so such a
    person still has something to pick. Fewer than three sizes when the figures run together;
    one when there is nothing lighter at all."""
    if anchor <= 0:
        return []
    info = CHALLENGES[key]
    grid = tuple(GRIDS[info["kind"]])
    anchor = min(anchor, limit_figure(key))
    sizes = lighter_starts(anchor, info["floor"], grid)
    if not sizes:
        sizes = lighter_starts(anchor, info["floor"], tuple(STARTER_FIGURES.get(info["kind"], ())) + grid)
    return sizes + [anchor]


def pick_ask(below):
    """The line over the size buttons, for how many of the three sit under Steady: none (steady,
    stretch, summit), one (a little lighter, steady, a stretch), or two (gentle, easy, steady)."""
    return (PICK_ASK, PICK_ASK_MIX, PICK_ASK_EASE)[min(max(below, 0), 2)]


def lighter_figures(key, anchor):
    """Up to two round figures lighter than `anchor`, smallest first (the lighter ones of
    starter_sizes)."""
    return starter_sizes(key, anchor)[:-1]


def heavier_figures(key, anchor):
    """Up to two round figures bigger than `anchor`, smallest first: about one and two levels up from
    it (the ratio of the level shares), each really bigger than the one before and none past the most
    the challenge ever asks in a week."""
    if anchor <= 0:
        return []
    info = CHALLENGES[key]
    grid, limit = GRIDS[info["kind"]], limit_figure(key)
    out, above = [], anchor
    for share in (SHARE[1] / SHARE[0], SHARE[2] / SHARE[0]):
        figure = grid_floor(min(anchor * share, limit), grid)
        if figure is None or figure <= above:
            figure = next((g for g in grid if g > above), None)          # the next figure up
        if figure is None or figure > limit:
            break
        out.append(figure)
        above = figure
    return out


def three_sizes(key, anchor, safe, prefer):
    """The three sizes a person picks between, smallest first, as (sizes, below): `anchor`, the size
    that suits them (Steady), and its two nearest neighbours, so there are always three. `below` is
    how many sit under it.

    `prefer` says which side the neighbours come from first: "lighter" for someone new to the
    challenge, "bigger" for someone who has taken it on before, whose `safe` sizes above it (what
    their own weeks support) come first. When that side has fewer than two, the other side fills
    in, and when both are short the bigger ones go on past what their weeks support (never past the
    weekly limit): a size they are free to ignore, where a missing one is a missing choice. Only
    where the whole span from the lightest start to the limit holds fewer than three round figures
    are there fewer."""
    lighter = lighter_figures(key, anchor)
    bigger = [figure for figure in safe if figure > anchor][:2]
    if prefer == "lighter":
        below = lighter
        above = bigger[:2 - len(below)]
    else:
        above = bigger
        take = 2 - len(above)
        below = lighter[-take:] if take else []
    short = 2 - len(below) - len(above)
    if short > 0:
        last = above[-1] if above else anchor
        past = [figure for figure in heavier_figures(key, anchor) if figure > last]
        if len(past) < short:                          # their own bigger size is already past those
            past += [figure for figure in heavier_figures(key, last) if figure > (past[-1] if past else last)]
        above = above + past[:short]
    return below + [anchor] + above, len(below)


def tier_pick(tier):
    """The name of the size `tier` steps from Steady (0): Stretch and Summit above it, Easy and
    Gentle below."""
    if tier >= 0:
        return PICKS[min(tier, len(PICKS) - 1)]
    return LOWER_PICKS[len(LOWER_PICKS) + max(tier, -len(LOWER_PICKS))]


def size_picks(sizes, below=0):
    """The names of `sizes`, smallest first, when `below` of them sit under Steady."""
    return [tier_pick(n - below) for n in range(len(sizes))]


def kept_below(entry, count):
    """How many of the `count` sizes an acceptance kept sit under Steady (a newcomer's lighter
    starting points); 0 for one that kept none or whose figure cannot be read."""
    below = _int((entry or {}).get("below"), 0, 0, len(LOWER_PICKS))
    return below if below < count else 0


def personal_offer(row, key, post_id, monday, floor, reference):
    """What a person is offered on a personal post: {"goal", "sizes", "below", "known", "basis"}.

    Always three sizes to pick between (three_sizes), whoever they are and whatever they have done,
    so the note behaves the same every time. They are built round the size that suits the person,
    which is Steady: their own target when they have taken the challenge on before or have weeks of
    their own to size one from (personal_challenge), and `reference` -- the active crew's pace, the
    team figure -- when they have neither. Someone who has taken the challenge on before is offered
    the bigger sizes above it first, someone new to it the lighter ones below it; where that side
    runs short the other fills in. Someone with no weeks of their own starts on the lightest of the
    three. `below` is how many sit under Steady, so a size's tier is its place less `below`. Fewer
    than two sizes means there is nothing to pick between, and the goal is what personal_challenge
    gives."""
    mine = personal_challenge(row, key, post_id, monday, floor)
    veteran = took_before(row, post_id, key)
    own = veteran or mine["known"]                        # a goal of their own, from their own weeks
    anchor = min(mine["goal"] if own else reference, limit_figure(key))
    sizes, below = three_sizes(key, anchor, mine["sizes"][1:], "bigger" if veteran else "lighter") \
        if anchor > 0 else ([], 0)
    if len(sizes) < 2:
        return dict(mine, sizes=[], below=0)
    if not own:
        goal, basis = sizes[0], ("You have not logged this one in the last {} weeks, so it starts "
                                 "as light as it goes, with sizes taken from what the crew logs. Pick "
                                 "the one that suits you.".format(WINDOW_WEEKS))
    else:
        goal, basis = sizes[below], mine["basis"]
        if not veteran:
            basis += OFFER_POINTERS[min(below, 2)]
    return {"goal": goal, "sizes": sizes, "below": below, "known": mine["known"], "basis": basis}


def pick_sizes(posted, options):
    """The goals on offer once somebody has accepted, as [(pick, goal)]: the goal as posted, then
    each step up from it."""
    return list(zip(PICKS, [posted] + list(options)))


def took_before(row, post_id, key):
    """Whether this person has taken this same challenge on in an earlier week: an entry on their
    row for some other post, for this challenge (a game row holds two, told apart by their kind).
    Someone who has not is a newcomer to it, and a bigger goal is not offered yet."""
    if not isinstance(row, dict):
        return False
    row_type = str(row.get("row_type") or "")
    here = entry_id(post_id, key)
    return any(entry["post"] != here and key_of_entry(row_type, entry) == key
               for entry in weekly_entries(row.get(WEEKLY_COLUMN)))


def pick_blocks(said, key, posted, options, current, value_of, ask=None, picks=None):
    """The private note with the sizes to pick from: what was just said (nothing, when `said` is empty),
    a line asking (`ask`, or PICK_ASK), and a button for each size -- the posted goal, then the others -- with the one in
    force marked. `picks` names them in order (PICKS, or lower_picks for a newcomer).
    `value_of(goal, which)` gives a button's value, `which` being the name's place in EVERY_PICK."""
    buttons = []
    for rung, (pick, goal) in enumerate(zip(picks or PICKS, [posted] + list(options))):
        button = {"type": "button", "action_id": "wchallenge_goal_{}_{}".format(key, rung),
                  "text": {"type": "plain_text", "emoji": True,
                           "text": "{} {} · {}".format(
                               pick["icon"], pick["name"], amount_text(key, goal))[:BUTTON_MAX]},
                  "value": value_of(goal, EVERY_PICK.index(pick))}
        if goal == current:
            button["style"] = "primary"
        buttons.append(button)
    return ([_section(said)] if said else []) + [
        _context(ask or PICK_ASK), {"type": "actions", "block_id": "wc_pick_" + key, "elements": buttons}]


def optout_row(key, value, label):
    """The row under the sizes with the one button that takes a person out of the challenge. It asks
    before it does, since a press cannot be taken back (the person can only take the challenge on again)."""
    button = {"type": "button", "action_id": "wchallenge_optout_" + key,
              "text": {"type": "plain_text", "emoji": True, "text": OPTOUT_TEXT},
              "value": value,
              "confirm": {"title": {"type": "plain_text", "text": "Opt out?"},
                          "text": {"type": "plain_text", "text": OPTOUT_CONFIRM.format(label)},
                          "confirm": {"type": "plain_text", "text": "Opt out"},
                          "deny": {"type": "plain_text", "text": "Keep it"}}}
    return {"type": "actions", "block_id": "wc_optout_" + key, "elements": [button]}


def pick_name(plan, key, goal):
    """The name of the size a goal is for this challenge ('Stretch'), or '' when it is the one
    posted or none of the sizes on offer."""
    sizes = [plan["targets"][key]] + plan.get("up", {}).get(key, [])
    return PICKS[sizes.index(goal)]["name"] if goal in sizes[1:] else ""


def picked_note(key, pick, goal, tracking):
    """What somebody is told once their goal is set: the line for the size they picked (`pick`, one
    of PICKS or LOWER_PICKS), then how it is kept (the same note as when they accepted)."""
    notes = GAME_TRACKING_NOTES if is_game(key) else TRACKING_NOTES
    return "{} {} {}".format(pick["icon"], pick["said"].format(goal=describe(key, goal)),
                             notes.get(tracking, "")).strip()


# ------------------------------------------------------------------ progress

BAR_WIDTH = 10
# Emoji squares, not shape characters: an emoji is the same size everywhere, where a shape is
# drawn from whichever font Slack finds and the bar comes out ragged.
BAR_EMPTY = ":white_large_square:"
BAR_FILL = ":large_blue_square:"          # what is done towards a goal that is still open
BAR_DONE = ":large_green_square:"         # a goal that is cleared
PROGRESS_HEADER = ":dart: Your weekly challenges"
PROGRESS_ROOMY = 20                       # up to this many goals each get a title and a line under
                                          # it; past it a block each (Slack takes 50 to a message)
PROGRESS_NONE = (":dart: You have no weekly challenges on right now. A new set goes up on "
                 "Monday: press *Accept challenge* on the ones you fancy.")


def progress_share(got, goal):
    return max(0.0, min(1.0, float(got) / float(goal))) if goal else 0.0


def progress_percent(got, goal):
    """Whole percent, never 100 (that is for a goal that is cleared) and never 0 once there is
    some progress."""
    percent = min(99, int(progress_share(got, goal) * 100))
    return max(1, percent) if got > 0 and goal else percent


def progress_bar(got, goal, done=False):
    """Ten squares: green and full only when the goal is cleared, so 99% does not look done;
    blue while it is open, with one filled as soon as there is any progress."""
    if done:
        return BAR_DONE * BAR_WIDTH
    filled = min(BAR_WIDTH - 1, int(progress_share(got, goal) * BAR_WIDTH))
    if got > 0 and goal:
        filled = max(1, filled)
    return BAR_FILL * filled + BAR_EMPTY * (BAR_WIDTH - filled)


def key_of_entry(row_type, entry):
    """The challenge an entry on a row of this type belongs to, or None. An activity row holds
    one challenge; a game row two, told apart by the entry's kind."""
    kind = entry.get("kind") if entry.get("kind") in WEEKLY_GAME_KINDS else None
    for key in KEYS_OF_ROW.get(row_type) or []:
        if (CHALLENGES[key]["kind"] if CHALLENGES[key]["game"] else None) == kind:
            return key
    return None


def my_goals(rows, waiting, today):
    """The person's goals for the week in progress: [{key, entry, row}], in the order of the
    challenges. `rows` are their rows of the activities and games, `waiting` the entries held
    on acceptance rows for rows they do not have yet ([(key, entry)]).

    `today` is the person's own date from their Slack zone, but when Slack cannot say it is the
    channel's default zone, which can be a day behind them: on Monday morning in India it is still
    Sunday. So a week that starts tomorrow counts as started, and when that leaves two weeks
    (last week's last day and the new week) the newer one is the week in progress."""
    held = [(key_of_entry(str(row.get("row_type") or ""), entry), entry, row)
            for row in rows for entry in weekly_entries(row.get(WEEKLY_COLUMN))]
    held += [(key, entry, None) for key, entry in waiting]
    found, seen = [], set()
    tomorrow = today + timedelta(days=1)
    for key, entry, row in held:
        if key and as_date(entry["from"]) <= tomorrow and today <= as_date(entry["to"]) \
                and (key, entry["post"]) not in seen:
            # an entry's `post` is shared by every activity accepted from one post, so a goal
            # is told apart by the challenge as well
            seen.add((key, entry["post"]))
            found.append({"key": key, "entry": entry, "row": row})
    if found:
        newest = max(as_date(g["entry"]["from"]) for g in found)
        found = [g for g in found if as_date(g["entry"]["from"]) == newest]
    return sorted(found, key=lambda g: ACTIVITY_ORDER[g["key"]])


def days_left_text(entry, today):
    """'5 days left', counting today. Before the goal's week has started (the zone can leave
    `today` a day behind) it is the whole week, never more."""
    first = max(today, as_date(entry["from"]))
    return plural(max(1, (as_date(entry["to"]) - first).days + 1), "day") + " left"


def goal_progress(goal, today):
    """(got, done, line) for one goal: how far along the person is, and the small line that goes
    under its title. The title already says the goal, so the line says how far, not how far of what."""
    key, entry, row = goal["key"], goal["entry"], goal["row"]
    target = int(entry["goal"])
    kind = CHALLENGES[key]["kind"]
    if entry.get("state") == "done":
        return target, True, "{}  *100%*  \u00b7  Cleared :white_check_mark:".format(
            progress_bar(target, target, True))
    if entry.get("state") == "missed":
        return 0, False, "_Closed without being cleared_"
    if kind == "score":
        # nothing partial to show: one game does it, or none has
        return 0, False, ":hourglass_flowing_sand:  Not yet  \u00b7  one free game scoring {} or more".format(
            amount_text(key, target))
    now = _amount((row or {}).get("total_planks")) if kind == "plays" else cumulative(row)
    got = min(target, weekly_got(entry, now))
    if got >= target:
        # reached, and spotter / the game will mark it on the next log or game: full, but not green
        return target, False, "{}  *Goal reached*  \u00b7  counted on your next log".format(
            BAR_FILL * BAR_WIDTH)
    if not got:
        return 0, False, "{}  Not started".format(progress_bar(0, target))
    return got, False, "{}  *{}%*  \u00b7  {} to go  \u00b7  {}".format(
        progress_bar(got, target), progress_percent(got, target), amount_text(key, target - got),
        days_left_text(entry, today))


def cleared_count(goals):
    return sum(1 for goal in goals if goal["entry"].get("state") == "done")


def progress_blocks(goals, monday, today):
    """The private note: a header, the week and how many goals are cleared, then each goal as its
    title with its bar in small print under it. A block to each, not one long block of text, which
    Slack folds behind "Show more"."""
    if goals:
        monday = monday_of(as_date(goals[0]["entry"]["from"]))     # the goals' own week
    cleared = cleared_count(goals)
    body = []
    for goal in goals:
        title = "{}  *{}*".format(
            CHALLENGES[goal["key"]]["icon"],
            goal["entry"].get("text") or describe(goal["key"], goal["entry"]["goal"]))
        line = goal_progress(goal, today)[2]
        body += [_section(title), _context(line)] if len(goals) <= PROGRESS_ROOMY \
            else [_section(title + "\n" + line)]
    everything = bool(goals) and cleared == len(goals)
    summary = ":calendar:  {}  \u00b7  *{} of {}* cleared{}".format(
        week_label(monday), cleared, len(goals), " :tada:" if everything else "")
    footer = ("Well done. A new set goes up on Monday." if everything
              else "Everything you log until Sunday counts")
    return ([{"type": "header", "text": {"type": "plain_text", "text": PROGRESS_HEADER,
                                         "emoji": True}},
             _context(summary), {"type": "divider"}] + body + [_context(footer)])


# ------------------------------------------------------------------ the saved plan

def plan_content(level, monday, goals, specs, intro="", style=DEFAULT_STYLE, banner="",
                 personal=False, per_row=BUTTONS_PER_ROW):
    """The json saved with a post: enough to redraw any of its messages on a press, and what each
    challenge was set at (`lv`, and `cap` when the best-week line held it down), which is where
    next week's goal for it starts from."""
    return json.dumps({
        "v": 1, "level": level, "week": monday.isoformat(), "intro": intro, "style": style,
        "banner": banner, "pe": 1 if personal else 0,
        **({"pr": per_row} if per_row != BUTTONS_PER_ROW else {}),
        "challenges": [dict(spec_challenge(g), lv=g.get("level", level),
                            **({"cap": 1} if g.get("capped") else {})) for g in goals],
        "groups": [{"keys": [c["key"] for c in s["challenges"]], "ts": ""} for s in specs],
        "main_ts": "",
    }, separators=(",", ":"))


def parse_plan(row):
    """The saved plan of a post row, or None when it cannot be read."""
    try:
        data = json.loads(row.get("content") or "")
        week = as_date(data["week"])
        targets = {c["key"]: int(c["target"]) for c in data["challenges"]}
        groups = [{"keys": [k for k in g["keys"] if k in targets], "ts": str(g.get("ts") or "")}
                  for g in data["groups"]]
        if not week or not groups or any(k not in CHALLENGES for k in targets):
            return None
        # What each challenge was set at. A plan saved before levels were kept per challenge has
        # only the one `level`, which is what every challenge in it was set at.
        levels = {c["key"]: _int(c.get("lv"), int(data["level"]), 1, MAX_LEVEL)
                  for c in data["challenges"]}
        capped = {c["key"] for c in data["challenges"] if c.get("cap")}
        prev = {c["key"]: _int(c.get("prev"), 0, 0, 10 ** 9) for c in data["challenges"]}
        # the bigger goals on offer, each really bigger than the one before and than the posted goal
        up = {}
        for c in data["challenges"]:
            above, ladder = targets[c["key"]], []
            for figure in c.get("up") if isinstance(c.get("up"), list) else []:
                figure = _int(figure, 0, 0, 10 ** 9)
                if figure > above and len(ladder) < len(PICKS) - 1:
                    ladder.append(figure)
                    above = figure
            up[c["key"]] = ladder
        return {"week": week, "level": int(data["level"]), "targets": targets, "groups": groups,
                "levels": levels, "capped": capped, "prev": prev, "up": up,
                "personal": bool(data.get("pe")), "per_row": _row_size(data.get("pr")),
                "main_ts": str(data.get("main_ts") or ""), "intro": str(data.get("intro") or ""),
                "style": _int(data.get("style"), DEFAULT_STYLE, 1, max(POST_STYLES)),
                "banner": str(data.get("banner") or "")}
    except (ValueError, KeyError, TypeError):
        return None


def plan_spec(plan, index, testing=False):
    """The spec of one message of a saved plan."""
    keys = plan["groups"][index]["keys"]
    more = sum(len(g["keys"]) for g in plan["groups"][1:])
    return {"week": plan["week"], "level": plan["level"], "index": index,
            "more": more if index == 0 else 0, "testing": testing, "intro": plan.get("intro", ""),
            "style": plan.get("style", DEFAULT_STYLE), "personal": plan.get("personal", False),
            "per_row": plan.get("per_row", BUTTONS_PER_ROW),
            "challenges": [spec_challenge({"key": k, "target": plan["targets"][k],
                                           "prev": plan["prev"].get(k, 0),
                                           "up": plan["up"].get(k)}) for k in keys],
            "everything": [{"key": k, "target": plan["targets"][k]}
                           for g in plan["groups"] for k in g["keys"]] if index == 0 else None,
            "banner": plan.get("banner", "") if index == 0 else ""}


def entry_id(post_id, key):
    """What an entry's `post` says. A game has two challenges on one row of a player, so each is
    told apart by its kind; an activity has one."""
    kind = CHALLENGES[key]["kind"]
    return "{}:{}".format(post_id, kind) if kind in WEEKLY_GAME_KINDS else post_id


def accept_key(post_id, key, user_id):
    return "weekly_accept_{}_{}_{}".format(post_id, key, user_id)


# --------------------------------------------------------------------------
# EDGES -- everything below talks to the network
# --------------------------------------------------------------------------

def _send_json(url, headers, payload, method="POST", timeout=HTTP_TIMEOUT):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        return None, "HTTP {} {} {}: {}".format(error.code, method, url.split("/")[2], detail)
    except Exception as error:                                    # noqa: BLE001
        return None, "{}: {}".format(type(error).__name__, str(error)[:200])


class Table(object):
    """Workato data table access, by column name rather than UUID."""

    def __init__(self, token):
        self.headers = {"Authorization": "Bearer {}".format(token),
                        "Content-Type": "application/json"}
        self.errors = []
        self.written = 0
        self.read_failed = False

    @staticmethod
    def _decode(body):
        """The query endpoint returns schema and data as arrays-of-arrays."""
        columns = [f.get("name") for group in body.get("schema", []) for f in group]
        rows = []
        for row in body.get("data", []):
            decoded = dict(zip(columns, [v for group in row for v in group]))
            if "total" in decoded:
                decoded["total"] = stored_sessions(decoded)    # the whole list, wherever it lives
            rows.append(decoded)
        return rows

    def query(self, where, select=None, limit=200, every=False):
        """Matching rows. `every` follows continuation tokens to the last page. A failed read
        gives [] with read_failed set: half a channel would hand out goals that are not true."""
        if select and "total" in select:
            select = list(select) + [c for c in TOTAL_COLUMNS[1:] if c not in select]
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
                self.errors.append("table.query " + error)
                self.read_failed = True
                return []
            rows.extend(self._decode(body))
            token = body.get("continuation_token") if every else None
            if not token:
                break
            payload["continuation_token"] = token
        return rows

    def _first(self, conditions):
        """The first matching row with its $record_id; LOOKUP_FAILED if the read failed (None
        means there is no such row)."""
        rows = self.query({"$and": conditions}, limit=1)
        if self.read_failed:
            return LOOKUP_FAILED
        return rows[0] if rows else None

    def activity_rows(self):
        """Every row the goals are worked out from: the activities' and the games' player rows."""
        types = [base + "_users" for base in ACTIVITIES] + list(GAME_OF_ROW)
        rows = self.query(
            {"row_type": {"$in": types}},
            select=["id", "name", "row_type", "total", "heatmap_dates", "leaderboard_optout",
                    "personal_best_single_set", "total_planks", "updated_at", "first_seen"],
            every=True)
        return LOOKUP_FAILED if self.read_failed else rows

    def activity_row(self, key, user_id):
        """The person's row that holds a challenge's figures (their row of the activity, or of
        the game), with its $record_id: LOOKUP_FAILED if the read failed, None if they have
        never logged or played it."""
        return self._first([{"row_type": {"$eq": CHALLENGES[key]["row_type"]}},
                            {"id": {"$eq": user_id}}])

    def rows_of(self, keys):
        """Every row of these challenges, whole: a write back needs the $record_id, and a
        narrowed read is not trusted to bring it."""
        types = sorted({CHALLENGES[key]["row_type"] for key in keys})
        rows = self.query({"row_type": {"$in": types}}, every=True)
        return LOOKUP_FAILED if self.read_failed else rows

    def person_rows(self, user_id):
        """Every row of this person's that can hold a weekly goal (their rows of the activities
        and games), whole. LOOKUP_FAILED if the read failed."""
        rows = self.query({"id": {"$eq": user_id}}, every=True)
        if self.read_failed:
            return LOOKUP_FAILED
        return [r for r in rows if str(r.get("row_type") or "") in KEYS_OF_ROW]

    def waiting_entries(self, user_id):
        """[(key, entry)] held on the person's acceptance rows: goals taken on for an activity
        they had no row for. LOOKUP_FAILED if the read failed."""
        rows = self.query({"$and": [{"row_type": {"$eq": ACCEPT_ROW}},
                                    {"group_id": {"$eq": user_id}}]}, every=True)
        if self.read_failed:
            return LOOKUP_FAILED
        out = []
        for row in rows:
            entry = weekly_entry_from(row.get("content"))
            if entry and row.get("grant_type") in CHALLENGES and (row.get("status") or "in") == "in":
                out.append((row["grant_type"], entry))
        return out

    def post_row(self, post_id):
        return self._first([{"row_type": {"$eq": POST_ROW}}, {"id": {"$eq": post_id}}])

    def posts_in(self, channel):
        rows = self.query({"$and": [{"row_type": {"$eq": POST_ROW}},
                                    {"slack_channel_id": {"$eq": channel}}]}, every=True)
        return LOOKUP_FAILED if self.read_failed else rows

    def acceptance(self, post_id, key, user_id):
        return self._first([{"row_type": {"$eq": ACCEPT_ROW}},
                            {"record_key": {"$eq": accept_key(post_id, key, user_id)}}])

    def acceptances(self, post_id):
        rows = self.query({"$and": [{"row_type": {"$eq": ACCEPT_ROW}}, {"id": {"$eq": post_id}}]},
                          select=["grant_type", "group_id", "member_name", "last_processed_ts",
                                  "status", "content"], every=True)
        return LOOKUP_FAILED if self.read_failed else rows

    def _document(self, fields):
        document = {}
        for name, value in fields.items():
            uuid = COLUMNS.get(name)
            if uuid is None:
                self.errors.append("write: unknown column " + name)
            elif value is not None:
                document["$" + uuid] = value if isinstance(value, str) else str(value)
        return document

    def create(self, fields, find=None):
        """(ok, record_id). The create call does not reliably return the id, so `find` -- a
        zero-argument lookup of the new row -- is the fallback. record_id is "" only if both
        fail: written but not addressable, never "not written", for a retry would duplicate."""
        body, error = _send_json(TABLE_RECORDS_URL, self.headers,
                                 {"document": self._document(fields)}, "POST")
        if error:
            self.errors.append("table.create " + error)
            return False, ""
        self.written += 1
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
            self.errors.append("table.update without a $record_id")
            return False
        _body, error = _send_json(TABLE_RECORD_URL.format(record_id), self.headers,
                                  {"document": self._document(fields)}, "PUT")
        if error:
            self.errors.append("table.update " + error)
            return False
        self.written += 1
        return True


def load_local_rows(path):
    """Rows from a JSON file instead of the table (a testing aid)."""
    with open(path, "r", encoding="utf-8") as handle:
        rows = json.load(handle)
    for row in rows:
        row["total"] = stored_sessions(row)
    return rows


def _slack_headers(token):
    return {"Authorization": "Bearer {}".format(token),
            "Content-Type": "application/json; charset=utf-8"}


def _slack_call(token, url, payload):
    """(body, error). A call Slack rate-limits is tried once more after a pause: a channel takes
    about one new message a second, and the Monday set posts several in a row."""
    for attempt in (1, 2):
        body, error = _send_json(url, _slack_headers(token), payload)
        problem = error or ("" if body.get("ok") else "slack: " + str(body.get("error")))
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
    _, error = _slack_call(token, SLACK_UPDATE_URL, {
        "channel": channel, "ts": str(ts), "text": text, "blocks": blocks})
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


def tell(result, token, channel, user, text, thread_ts=None, blocks=None):
    """Send a private note. A note that does not go is a warning: it must never undo a press. One
    whose blocks Slack turns down goes again as its text alone, so the person is still answered."""
    error = slack_ephemeral(token, channel, user, text, thread_ts, blocks)
    if error and blocks and not slack_ephemeral(token, channel, user, text, thread_ts):
        result["warnings"].append("note to {} went without its buttons: {}".format(user, error))
        return
    if error:
        result["warnings"].append("note to {}: {}".format(user, error))


def slack_message(token, channel, ts, thread_ts=None):
    """The message at `ts` as Slack has it (the thread's parent), or None when it cannot be had.
    A reply is asked for through its thread: pass the parent's `thread_ts` and the reply at `ts` comes
    back. Needs the history scope (channels:history, groups:history for a private channel). Never raises."""
    if thread_ts:
        url = "{}?channel={}&ts={}&oldest={}&limit=2&inclusive=true".format(
            SLACK_REPLIES_URL, channel, thread_ts, ts)
    else:
        url = "{}?channel={}&ts={}&limit=1&inclusive=true".format(SLACK_REPLIES_URL, channel, ts)
    request = urllib.request.Request(url, headers={"Authorization": "Bearer {}".format(token)},
                                     method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:                                              # noqa: BLE001
        return None
    messages = body.get("messages") if body.get("ok") else None
    if thread_ts:
        return next((m for m in messages or [] if str(m.get("ts")) == str(ts)), None)
    return messages[0] if messages else None


def test_state_of(message):
    """The parsed test state held in the buttons of a posted message, or None."""
    for block in (message or {}).get("blocks") or []:
        buttons = list(block.get("elements") or [])
        if block.get("accessory"):
            buttons.append(block["accessory"])
        for button in buttons:
            parsed = parse_test_value(button.get("value") or "")
            if parsed:
                return parsed
    return None


def slack_user(token, user_id):
    """The person's real name from users.info; "" when it cannot be had. Never raises."""
    if not token or not user_id:
        return ""
    request = urllib.request.Request(
        "{}?user={}".format(SLACK_USER_URL, user_id),
        headers={"Authorization": "Bearer {}".format(token)}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:                                              # noqa: BLE001
        return ""
    if not body.get("ok"):
        return ""
    user = body.get("user") or {}
    profile = user.get("profile") or {}
    # real_name first: display names here carry pronoun suffixes. user["name"] is the last
    # resort so a Slack Connect guest is not stored as a raw id.
    return (profile.get("real_name") or user.get("real_name")
            or profile.get("display_name") or user.get("name") or "").strip()


def slack_tz_offset(token, user_id):
    """The person's own UTC offset in seconds, from users.info (DST already applied); None when
    it cannot be had. Never raises."""
    if not token or not user_id:
        return None
    request = urllib.request.Request(
        "{}?user={}".format(SLACK_USER_URL, user_id),
        headers={"Authorization": "Bearer {}".format(token)}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
        return int(body["user"]["tz_offset"]) if body.get("ok") else None
    except Exception:                                              # noqa: BLE001
        return None


def clicker_today(input, token, user_id):
    """The presser's own date. A click carries no zone, so it is asked of Slack; a `today` or a
    `tz_offset` mapped on the step still wins, and when Slack cannot say it is the channel's zone."""
    given = as_date(input.get("today"))
    if given:
        return given
    offset = input.get("tz_offset")
    if offset in (None, ""):
        offset = slack_tz_offset(token, user_id)
    return local_today(offset)


# --------------------------------------------------------------------------
# Monday: set the goals and post them
# --------------------------------------------------------------------------

def post_set(token, channel, specs, values_for, result):
    """Post the channel message, then each reply under it. Returns the ts of each message,
    "" for one that did not go (a reply that fails is reported and the rest carry on).

    values_for(spec, main_ts) -> the function that gives each activity's button value.
    """
    stamps, main_ts = [], ""
    for spec in specs:
        blocks = build_blocks(spec, {}, values_for(spec, main_ts))
        ts, error = slack_post(token, channel, fallback_text(spec), blocks,
                               thread_ts=main_ts or None)
        if error:
            result["warnings"].append("{}: {}".format(
                "channel message" if spec["index"] == 0 else "reply {}".format(spec["index"]),
                error))
            if spec["index"] == 0:
                return [""]
        if spec["index"] == 0:
            main_ts = ts
        stamps.append(ts)
    return stamps


def retire_post(table, token, channel, row, replaced, result):
    """Take the buttons off a finished post's messages (leaving the final counts), or delete
    the messages when the post is being replaced. Then mark the row. Best effort throughout."""
    plan = parse_plan(row)
    if plan:
        people = {}
        if not replaced:
            rows = table.acceptances(row.get("id"))
            if rows is LOOKUP_FAILED:
                result["warnings"].append("could not read the acceptances of {}".format(row.get("id")))
            else:
                people = people_by_key(rows)
        for index, group in enumerate(plan["groups"]):
            if not group["ts"]:
                continue
            if replaced:
                slack_delete(token, channel, group["ts"])
                continue
            spec = dict(plan_spec(plan, index), frozen=True)
            error = slack_update(token, channel, group["ts"], fallback_text(spec),
                                 build_blocks(spec, people))
            if error and "message_not_found" not in error:
                result["warnings"].append("could not close a message of {}: {}".format(
                    row.get("id"), error))
    else:
        result["warnings"].append("post {} has no readable plan; only marked closed".format(
            row.get("id")))
    table.update(row.get("$record_id"), {"status": REPLACED if replaced else CLOSED})


def last_week(table, posts, monday, today, result):
    """How each challenge of the channel's newest earlier post stood, which is where this week's
    goal for it starts: {key: {"goal", "move", "taken", "cleared"}}, `move` being the rungs it
    goes (next_step). Empty when there is no earlier post or its plan cannot be read.

    `taken` and `cleared` are how many people took the challenge on and how many of them did the
    goal that was posted, counted as the recap counts them (read_week), so the figures are the
    ones the channel was just told. When they cannot be read every challenge takes the plain
    step, as one nobody took on does."""
    earlier = [p for p in posts if (p.get("status") or "") in (OPEN, CLOSED)
               and (p.get("week_key") or "") < monday.isoformat()]
    if not earlier:
        result["warnings"].append("no earlier post in this channel to set the goals from: every "
                                  "challenge starts at level {}".format(result["level"]))
        return {}
    post = max(earlier, key=lambda p: (p.get("week_key") or "", p.get("id") or ""))
    plan = parse_plan(post)
    if not plan:
        result["warnings"].append("post {} has no readable plan: every challenge starts at "
                                  "level {}".format(post.get("id"), result["level"]))
        return {}
    result["adapted_from"] = plan["week"].isoformat()
    memory = {key: {"goal": plan["targets"][key], "move": STEP_UP, "taken": 0, "cleared": 0}
              for key in plan["targets"]}
    goals, _closing, failed = read_week(table, plan, post.get("id") or "", today)
    if failed:
        result["warnings"].append("could not read the {} of last week's post: each challenge "
                                  "takes the plain step".format(failed))
        return memory
    for goal in goals:
        mine = memory[goal["key"]]
        # judged on whether people did what was POSTED, not the size each picked for themselves:
        # someone who stretched and landed in between has shown the posted goal was within reach
        mine["taken"], mine["cleared"] = len(goal["taken"]), len(goal["met"])
        mine["move"] = next_step(mine["taken"], mine["cleared"])
    return memory


def post_week(input, result, token, table, flags):
    """The Monday run."""
    today = as_date(input.get("today")) or local_today(input.get("tz_offset"))
    monday = monday_of(today)
    level = result["level"]
    result["week"] = monday.isoformat()
    personal = _switch(input.get("personal"), default=True)
    result["personal"] = personal

    if input.get("local_data_file"):
        if not (flags["testing"] or flags["skip_post"]):
            result["error"] = ("local_data_file stands in for the table, so it is for a test: set "
                               "testing = yes or skip_post = yes")
            return
        rows = load_local_rows(input["local_data_file"])
    else:
        rows = table.activity_rows()
        if rows is LOOKUP_FAILED:
            result["error"] = "could not read the activity rows; nothing posted"
            return
    result["rows_read"] = len(rows)

    # Where each challenge starts depends on how last week's went, so that is read first. It is
    # only read, so a test or a preview sees the goals the real run would set.
    memory = {}
    # (A personal post does not need it: each person's own weeks and last result set their target.)
    if not personal and _switch(input.get("adaptive"), default=True) \
            and not input.get("local_data_file"):
        # Every way of not finding last week says so: a goal that comes out the same as last
        # week's, with no word on why, is exactly what this is meant to stop.
        if not result["channel"]:
            result["warnings"].append("adaptive needs `channel` to find last week's post: every "
                                      "challenge starts at level {}".format(level))
        else:
            earlier = table.posts_in(result["channel"])
            if earlier is LOOKUP_FAILED:
                result["warnings"].append("could not read last week's post: every challenge "
                                          "starts at level {}".format(level))
            else:
                memory = last_week(table, earlier, monday, today, result)

    only = activity_names(input.get("only"), result["warnings"])
    skip = activity_names(input.get("skip"), result["warnings"])
    min_people = _int(input.get("min_people"), MIN_PEOPLE, 1, 50)
    goals, left_out = plan_week(
        rows, monday, level, only=only, skip=skip, min_people=min_people,
        max_challenges=_int(input.get("max_challenges"), MAX_CHALLENGES, 1, 30), memory=memory)
    game_goals, game_left = plan_games(
        rows, monday, level, only=only, skip=skip, min_people=min_people,
        max_games=_int(input.get("max_games"), MAX_GAMES, 0, len(GAMES)), memory=memory)
    goals = goals + game_goals
    left_out = left_out + game_left
    result["left_out"] = left_out
    result["rows_loose"] = sum(g["loose"] for g in goals)
    for goal in goals:
        last = memory.get(goal["key"]) or {}
        result["challenges"].append({
            "activity": goal["key"],
            "text": CHALLENGES[goal["key"]]["label"] if personal else describe(goal["key"], goal["target"]),
            "target": goal["target"], "people": goal["people"],
            "typical_week": int(round(goal["typical"])), "best_week": int(round(goal["best"])),
            "capped": goal["capped"], "loose_rows": goal["loose"], "level": goal["level"],
            "limit": limit_figure(goal["key"]),
            "last_target": goal["prev"], "last_taken": last.get("taken", 0),
            "last_cleared": last.get("cleared", 0), "move": move_word(goal["target"], goal["prev"]),
            "why": ("personal: the post shows no figure and each person's target is worked out "
                    "from their own weeks; `target` is the team reference" if personal else
                    why_text(memory.get(goal["key"]), goal["target"], goal["edge"])),
            "level_ups": "  |  ".join("{}: {}".format(PICKS[n]["name"], amount_text(goal["key"], v))
                                      for n, v in enumerate(goal["up"], 1)),
            "ladder": "  |  ".join("{}: {}".format(n, amount_text(goal["key"], v) if v else "-")
                                   for n, v in enumerate(goal["ladder"], 1))})
    if not goals:
        result["ok"] = True
        result["skipped"] = "no activity or game has enough recent logs to set a goal"
        return

    intro = str(input.get("intro_text") or "").strip()[:INTRO_MAX]
    if intro and flags["testing"] and len(intro) > TEST_INTRO_MAX:
        result["warnings"].append(
            "intro_text is longer than {} characters: a test post can carry it on the first "
            "message only, and it reverts to the built-in line after the first press".format(
                TEST_INTRO_MAX))
    banner = clean_banner(input.get("banner_url"), result["warnings"])
    if banner and flags["testing"] and len(banner) > TEST_BANNER_MAX:
        result["warnings"].append(
            "banner_url is longer than {} characters: a test post shows it until the first press, "
            "then it drops off".format(TEST_BANNER_MAX))
    style = _int(input.get("post_style"), DEFAULT_STYLE, min(POST_STYLES), max(POST_STYLES))
    result["post_style"] = style
    per_row = _row_size(input.get("buttons_per_row"))
    if style == 3:
        # a grid post is sized in rows of buttons, and `top_count` (which counts lines of text) is not used
        top_count = per_row * _int(input.get("button_rows"), BUTTON_ROWS, 1, MAX_BUTTON_ROWS)
    else:
        top_count = _int(input.get("top_count"), TOP_COUNT, 1, 10)
    specs = group_specs(goals, monday, level, testing=flags["testing"], intro=intro,
                        top_count=top_count, style=style, banner=banner, personal=personal,
                        per_row=per_row)
    if not flags["skip_post"] and not (token and result["channel"]):
        result["error"] = ("slack_bot_token and channel are both needed to post "
                           "(skip_post = yes previews without them)")
        return
    if flags["skip_post"]:
        result["preview"] = True
        result["preview_json"] = json.dumps([
            {"where": "channel" if s["index"] == 0 else "thread", "text": fallback_text(s),
             "blocks": build_blocks(s, {}, lambda key: live_value("PREVIEW", key))}
            for s in specs])
        result["ok"] = True
        return

    channel = result["channel"]
    if flags["testing"]:
        stamps = post_set(token, channel, specs,
                          lambda spec, main_ts: (lambda key: test_value(spec, {}, main_ts, key)),
                          result)
        result["message_ts"] = stamps[0] if stamps else ""
        result["reply_ts"] = [ts for ts in stamps[1:] if ts]
        result["ok"] = bool(result["message_ts"])
        if not result["ok"]:
            result["error"] = "could not post the test message"
        return

    # ---- the real thing: the post row first, so a press can never find nothing to read
    posts = table.posts_in(channel)
    if posts is LOOKUP_FAILED:
        result["error"] = "could not read the earlier posts; nothing posted"
        return
    live = [p for p in posts if (p.get("status") or "") in (OPEN, POSTING)]
    same_week = [p for p in live if p.get("status") == OPEN and p.get("week_key") == result["week"]]
    if same_week and not flags["force"]:
        result["ok"] = True
        result["skipped"] = ("already posted for the week of {}; pass force = yes to post "
                             "again".format(result["week"]))
        result["post_id"] = same_week[0].get("id") or ""
        return

    post_id = "{}-{}".format(result["week"], int(_now()))
    result["post_id"] = post_id
    content = plan_content(level, monday, goals, specs, intro, style, banner, personal=personal,
                           per_row=per_row)
    fields = {"record_key": "weekly_challenge_" + post_id, "row_type": POST_ROW, "id": post_id,
              "name": "Weekly challenges " + result["week"], "week_key": result["week"],
              "slack_channel_id": channel, "status": POSTING, "created_at": result["week"],
              "day": (monday + timedelta(days=6)).isoformat(), "updated_at": today.isoformat(),
              "content": content}
    saved, record_id = table.create(fields, find=lambda: table.post_row(post_id))
    if not saved or not record_id:
        result["error"] = "could not save the challenge set; nothing posted"
        return

    stamps = post_set(token, channel, specs,
                      lambda spec, main_ts: (lambda key: live_value(post_id, key)), result)
    if not stamps[0]:
        table.update(record_id, {"status": FAILED})
        result["error"] = "could not post the channel message"
        return
    plan = json.loads(content)
    plan["main_ts"] = stamps[0]
    for group, ts in zip(plan["groups"], stamps):
        group["ts"] = ts
    table.update(record_id, {"status": OPEN, "source_ref": stamps[0],
                             "content": json.dumps(plan, separators=(",", ":"))})
    result["message_ts"] = stamps[0]
    result["reply_ts"] = [ts for ts in stamps[1:] if ts]

    # ---- last week's messages lose their buttons. A forced repost always takes this week's old
    # ones down (they are deleted, not frozen: they would only be a second, stale copy).
    for row in live:
        replaced = row in same_week
        if replaced or flags["close_previous"]:
            retire_post(table, token, channel, row, replaced=replaced, result=result)
            result["closed_previous"] += 1
    result["ok"] = True


# --------------------------------------------------------------------------
# Sunday: the results
# --------------------------------------------------------------------------

RECAP_NAMES = 6                   # names on a goal's line before "+N more"
RECAP_TEST_NOTE = ":test_tube: Test recap: nothing is saved and the week is not closed."


def plural(n, one, many=None):
    return "{} {}".format(n, one if n == 1 else (many or one + "s"))


def and_join(names):
    """'a', 'a and b', 'a, b and c'."""
    names = list(names)
    if len(names) < 3:
        return " and ".join(names)
    return "{} and {}".format(", ".join(names[:-1]), names[-1])


def accepted_entries(rows):
    """{(activity, person): entry} from the acceptance rows, which keep the entry as it was made
    -- the copy to fall back on when a person's own row has none."""
    out = {}
    for row in rows:
        entry = weekly_entry_from(row.get("content"))
        if entry and row.get("grant_type") in CHALLENGES and row.get("group_id") \
                and (row.get("status") or "in") == "in":
            out[(row["grant_type"], row["group_id"])] = entry
    return out


def recap_verdict(entry, row, today):
    """('done' | 'short' | 'unknown', got): did this person clear this goal?

    spotter marks an entry done the moment a log clears it, and that stands. An entry still
    open is judged from the running totals, so a week spotter did not watch (or a log it
    could not settle) is still counted -- but only up to the day after the week ends, when
    later logs start to belong to the next week.
    """
    if not entry:
        return "unknown", 0
    goal = int(entry["goal"])
    if entry.get("kind") in WEEKLY_GAME_KINDS:
        # A game settles its own entry when a game ends, and that stands. A game that was not
        # watched cannot be judged afterwards: the row keeps no date against a game.
        return ("done", goal) if entry.get("state") == "done" else ("short", 0)
    got = weekly_got(entry, cumulative(row))
    if entry.get("state") == "done":
        return "done", max(got, goal)
    if entry.get("state") == "missed":
        return "short", got
    if got >= goal and today <= as_date(entry["to"]) + timedelta(days=1):
        return "done", got
    return "short", got


def recap_reached(entry, verdict, got, posted, today):
    """Whether the person did at least the goal that was posted, whatever they set their own goal
    at. Someone who picked a bigger size and fell short of it may still have cleared the posted
    one, and that is what says whether the posted goal was the right size."""
    if not entry:
        return False
    goal = int(entry["goal"])
    if verdict == "done" and goal >= posted:
        return True
    if goal <= posted or entry.get("kind") in WEEKLY_GAME_KINDS or entry.get("state") == "missed":
        return False                      # their goal was the posted one (the verdict has it), or
                                          # a game, or closed: nothing finer can be said
    return got >= posted and today <= as_date(entry["to"]) + timedelta(days=1)


def recap_results(plan, post_id, people, taken, rows, today):
    """Who took on each goal and who cleared it.

    people {activity: [{id, name}]} from the acceptance rows; taken the entries those rows
    hold; rows {(activity, person): the person's row of the activity}.
    Returns (goals, closing). goals: one per goal somebody took on, in the post's order, each
    {key, text, taken, cleared, met} with taken, cleared and met lists of {id, name, hidden, own,
    pick}: cleared is who cleared the goal THEY set (own: the figure, and pick its name, when it
    is not the posted one), met who did at least the posted goal. closing:
    [(row, entries, cleared)], the rows whose entry for this post was still open, with the
    entries as they should now be written back and 1 where that entry was cleared (so the
    row's count of cleared goals goes up with it).
    """
    goals, closing = [], []
    for key in [k for group in plan["groups"] for k in group["keys"]]:
        takers = people.get(key) or []
        if not takers:
            continue
        everyone, cleared, met = [], [], []
        posted = plan["targets"][key]
        personal = plan.get("personal", False)
        for person in takers:
            row = rows.get((key, person["id"]))
            mine = weekly_entries((row or {}).get(WEEKLY_COLUMN))
            on_row = next((e for e in mine if e["post"] == entry_id(post_id, key)), None)
            entry = on_row or taken.get((key, person["id"]))
            verdict, got = recap_verdict(entry, row, today)
            # A personal post has no posted figure to compare with: everyone's goal is their own, and
            # only the size they picked is told. Otherwise a goal that is not the posted one says so.
            # On a personal post it is everyone's own figure that is told ("Dheeraj (3 hours)"): a
            # category and a count ("Yoga, 2 people") says nothing of what each of them took on.
            own = (int(entry["goal"]) if entry else 0) if personal else \
                (int(entry["goal"]) if entry and int(entry["goal"]) != posted else 0)
            # only the bigger sizes are NAMED in the channel: a lighter start is nobody's business
            tier = _int((entry or {}).get("tier"), 0, 0, len(PICKS) - 1)
            who = {"id": person["id"], "name": person["name"],
                   "hidden": bool((row or {}).get("leaderboard_optout")), "own": own,
                   "pick": PICKS[tier]["name"] if tier else (pick_name(plan, key, own) if own else "")}
            everyone.append(who)
            if verdict == "done":
                cleared.append(who)
            if verdict == "done" if personal else recap_reached(entry, verdict, got, posted, today):
                met.append(who)
            if on_row is not None and on_row.get("state") == "open":
                if verdict == "done":
                    settled = dict(on_row, state="done", done=today.isoformat())
                elif today > as_date(on_row["to"]) + timedelta(days=1):
                    settled = dict(on_row, state="missed")
                else:
                    # It may still be the last day for them (logs are dated in each person's
                    # own day): left open, so a late log can still clear it. Their next log
                    # after the week closes it as missed.
                    continue
                closing.append((row, [settled if e is on_row else e for e in mine],
                                1 if verdict == "done" else 0))
        goals.append({"key": key, "text": (CHALLENGES[key]["label"] if personal
                                           else describe(key, plan["targets"][key])),
                      "taken": everyone, "cleared": cleared, "met": met})
    return goals, closing


def read_week(table, plan, post_id, today):
    """(goals, closing, failed): the table read and the results of recap_results for a post.
    `failed` names what could not be read ("acceptances", "activity rows"), and is "" when all of
    it was. The recap and the Monday run both read a week this way, so the numbers agree."""
    accepted = table.acceptances(post_id)
    if accepted is LOOKUP_FAILED:
        return [], [], "acceptances"
    people = people_by_key(accepted)
    keys = [k for k in (key for group in plan["groups"] for key in group["keys"]) if people.get(k)]
    rows = {}
    if keys:
        found = table.rows_of(keys)
        if found is LOOKUP_FAILED:
            return [], [], "activity rows"
        for row in found:
            for key in KEYS_OF_ROW.get(str(row.get("row_type") or ""), []):
                rows[(key, row.get("id"))] = row
    goals, closing = recap_results(plan, post_id, people, accepted_entries(accepted), rows, today)
    return goals, closing, ""


def cleared_line(cleared, key=None):
    """'Priya, Jack and Sam' -- first names, a few of them, and a count for the rest. Someone who
    has opted out is counted but never named. Given the challenge's `key`, a name whose owner
    cleared a goal of their own says which: 'Jack (Summit: 200)'."""
    visible = [p for p in cleared if not p["hidden"]]
    named = visible[:RECAP_NAMES]
    shown = short_names(named)
    if key:
        def tagged(p, name):
            bits = [b for b in [p.get("pick"), amount_text(key, p["own"]) if p.get("own") else ""] if b]
            return "{} ({})".format(name, ": ".join(bits)) if bits else name
        shown = [tagged(p, name) for p, name in zip(named, shown)]
    left = len(cleared) - len(shown)
    if not shown:
        return plural(left, "person", "people")
    return and_join(shown) if not left else ", ".join(shown) + " +{} more".format(left)


def recap_text(plan, goals):
    won = sum(len(g["cleared"]) for g in goals)
    return "Weekly challenges ({}): {} cleared".format(week_label(plan["week"]), won)


def recap_blocks(plan, goals, testing=False, banner=""):
    """The results, as one post: a line on the week, then each goal somebody took on."""
    taken = sum(len(g["taken"]) for g in goals)
    people = len({p["id"] for g in goals for p in g["taken"]})
    won = sum(len(g["cleared"]) for g in goals)
    blocks = [_section(":checkered_flag:  *Weekly challenges: the results*  ·  {}".format(
        week_label(plan["week"])))]
    if banner:
        blocks.insert(0, {"type": "image", "image_url": banner, "alt_text": RECAP_BANNER_ALT})
    if testing:
        blocks.append(_context(RECAP_TEST_NOTE))
    summary = "*{}* took on *{}* between them".format(plural(people, "person", "people"),
                                                       plural(taken, "goal"))
    blocks.append(_section(
        "{}, and *{}* {} cleared. Well done to everyone who joined in.".format(
            summary, won, "was" if won == 1 else "were") if won else
        "{}. None was cleared this time.".format(summary)))
    lines = []
    for goal in sorted(goals, key=lambda g: (-len(g["cleared"]), -len(g["taken"]))):
        head = "{}  *{}*".format(CHALLENGES[goal["key"]]["icon"], goal["text"])
        if goal["cleared"]:
            tail = "cleared by *{}*  ({} of {})".format(
                cleared_line(goal["cleared"], goal["key"]), len(goal["cleared"]),
                len(goal["taken"]))
        else:
            tail = "not cleared this time  (0 of {})".format(len(goal["taken"]))
        lines.append("{}  ·  {}".format(head, tail))
    chunk, size = [], 0
    for line in lines:                       # a section stops at 3000 characters
        if chunk and size + len(line) > 2500:
            blocks.append(_section("\n".join(chunk)))
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        blocks.append(_section("\n".join(chunk)))
    blocks.append({"type": "divider"})
    blocks.append(_context("A new set of goals goes up on Monday."))
    return blocks


def recap_week(input, result, token, table, flags):
    """The recap: who cleared each goal, told to the channel, and the week closed off."""
    channel = result["channel"]
    today = as_date(input.get("today")) or local_today(input.get("tz_offset"))
    posts = table.posts_in(channel)
    if posts is LOOKUP_FAILED:
        result["error"] = "could not read the earlier posts; nothing posted"
        return
    wanted = as_date(input.get("week"))
    if wanted:
        picks = [p for p in posts if p.get("week_key") == wanted.isoformat()
                 and (p.get("status") or "") in (OPEN, POSTING, CLOSED)]
    else:
        # the open post whose week is over -- or ends today, which is when a Sunday run, or a Monday one, is made
        picks = [p for p in posts if (p.get("status") or "") in (OPEN, POSTING)
                 and (as_date(p.get("day")) or today) <= today]
    picks.sort(key=lambda p: (p.get("week_key") or "", p.get("id") or ""))
    if not picks:
        result["ok"] = True
        result["skipped"] = ("no challenge post for that week" if wanted else
                             "no open challenge post whose week is over; pass week = a Monday "
                             "to recap a different one")
        return
    post = picks[-1]
    plan = parse_plan(post)
    if not plan:
        result["error"] = "post {} has no readable plan; nothing posted".format(post.get("id"))
        return
    post_id = post.get("id") or ""
    result["post_id"], result["week"] = post_id, plan["week"].isoformat()

    goals, closing, failed = read_week(table, plan, post_id, today)
    if failed:
        result["error"] = "could not read the {}; nothing posted".format(failed)
        return
    result["recap"] = [{
        "activity": g["key"], "text": g["text"], "accepted": len(g["taken"]),
        "cleared": len(g["cleared"]),
        "names": ", ".join(short_names([p for p in g["cleared"] if not p["hidden"]]))}
        for g in goals]

    live = not (flags["testing"] or flags["skip_post"])
    if not goals:
        result["ok"] = True
        result["skipped"] = "nobody accepted a goal" + ("; the week was closed" if live else "")
    else:
        blocks = recap_blocks(plan, goals, testing=flags["testing"],
                              banner=clean_banner(input.get("banner_url"), result["warnings"]))
        text = recap_text(plan, goals)
        if flags["skip_post"]:
            result["preview"] = True
            result["preview_json"] = json.dumps([{"where": "channel", "text": text, "blocks": blocks}])
            result["ok"] = True
            return
        ts, error = slack_post(token, channel, text, blocks)
        if error:
            result["error"] = "could not post the recap: " + error
            return
        result["message_ts"] = ts
        result["ok"] = True
    if not live:
        return
    # The week is over: the buttons come off its messages, and what each person's entry came to
    # is written down, so nothing is left open to be settled by a log that belongs to next week.
    if (post.get("status") or "") in (OPEN, POSTING):
        retire_post(table, token, channel, post, replaced=False, result=result)
        result["closed_previous"] += 1
    for row, entries, cleared in closing:
        text = weekly_text(row.get(WEEKLY_COLUMN), entries, cleared_add=cleared)
        if text is not None:
            table.update(row.get("$record_id"), {WEEKLY_COLUMN: text})


# --------------------------------------------------------------------------
# A press
# --------------------------------------------------------------------------

# What a person is told about keeping count, by what happened when the goal went on their row.
TRACKING_NOTES = {
    "tracked": "Everything you log from now until Sunday counts.",
    "pending": "You have not logged this one before, so your first log starts it.",
    "blocked": "I could not set up tracking for it just now, so it may not be noticed "
               "automatically.",
    "unwritten": "I could not set up tracking for it just now, so it may not be noticed "
                 "automatically.",
    "unreadable": "I could not set up tracking for it just now, so it may not be noticed "
                  "automatically.",
}


GAME_TRACKING_NOTES = dict(TRACKING_NOTES, **{
    "tracked": "Free games you finish from now until Sunday count.",
    "pending": "You have not played this one before, so your first game starts it."})


def cumulative(row):
    """A person's running total of an activity: every session in their row, added up. The same
    sum spotter takes, so a total read here and a total read there are the same number."""
    return int(sum(split_numbers((row or {}).get("total"))))


def baseline(key, row):
    """What a challenge is measured from, taken at the moment of accepting it: the running
    total of an activity, the games played so far for "play it N times", nothing for a score
    (only a game finished after accepting counts)."""
    kind = CHALLENGES[key]["kind"]
    if kind == "plays":
        return max(0, int(_amount((row or {}).get("total_planks"))))
    if kind == "score":
        return 0
    return cumulative(row)


def track(table, row, entry):
    """Put the accepted goal on the person's row of the activity, where spotter will find it.
    Returns what happened:

        tracked     it is there (now, or already was)
        pending     they have never logged the activity, so there is no row; the entry waits on
                    the acceptance row and their first log picks it up
        blocked     the column holds something that is not ours, which is not overwritten
        unwritten   the write failed
        unreadable  their row could not be read
        none        there was no entry to put
    """
    if not entry:
        return "none"
    if row is LOOKUP_FAILED:
        return "unreadable"
    if row is None:
        return "pending"
    raw = row.get(WEEKLY_COLUMN)
    mine = weekly_entries(raw)
    if any(e["post"] == entry["post"] for e in mine):
        return "tracked"
    text = weekly_text(raw, mine + [entry], accepted_add=1)
    if text is None:
        return "blocked"
    return "tracked" if table.update(row.get("$record_id"), {WEEKLY_COLUMN: text}) else "unwritten"


def weekly_text_without(raw, entries):
    """What the column should hold once the person has left a challenge: `entries` (the ones left),
    and one fewer taken on in its count. weekly_text only ever adds to the counts, and leaves one that
    has fallen to nothing as it was, so this takes the count down itself; None when the column holds
    something that is not ours."""
    text = weekly_text(raw, entries)
    if text is None:
        return None
    document = json.loads(text)
    accepted, cleared = weekly_counts(raw)
    accepted = max(0, accepted - 1)
    if accepted or cleared:
        document[WEEKLY_COUNTS_KEY] = {"accepted": accepted, "cleared": cleared}
    else:
        document.pop(WEEKLY_COUNTS_KEY, None)
    return json.dumps(document, separators=(",", ":"))


def retarget(table, row, entry):
    """Make the person's entry for a goal read `entry`: the same goal at the size they picked.
    Returns what happened, in track()'s words and one more:

        closed      the entry on their row is not open any more (cleared, or the week is over),
                    so it is left as it is
    """
    if row is LOOKUP_FAILED:
        return "unreadable"
    if row is None:
        return "pending"
    raw = row.get(WEEKLY_COLUMN)
    mine = weekly_entries(raw)
    held = next((e for e in mine if e["post"] == entry["post"]), None)
    if held is None:
        return track(table, row, entry)               # it never reached their row: put it there
    if held.get("state") != "open":
        return "closed"
    text = weekly_text(raw, [entry if e is held else e for e in mine])
    if text is None:
        return "blocked"
    return "tracked" if table.update(row.get("$record_id"), {WEEKLY_COLUMN: text}) else "unwritten"


def render_message(token, channel, ts, spec, people, value_of, result):
    """Redraw one message. Returns the error, if any."""
    error = slack_update(token, channel, ts, fallback_text(spec), build_blocks(spec, people, value_of))
    if error:
        result["warnings"].append("update: " + error)
    return error


def render_set(token, channel, ts, spec, plan, people, value_of, result):
    """Redraw the message that was pressed and, when that was a reply in the thread, the channel
    message too: its "accepted so far" line counts the whole post."""
    error = render_message(token, channel, ts, spec, people, value_of, result) if ts else None
    if spec["index"] and plan["main_ts"]:
        render_message(token, channel, plan["main_ts"], plan_spec(plan, 0), people, value_of,
                       result)
    return error


def write_acceptance(input, result, token, table, plan, post_id, key, clicker, row, goal, mine,
                     existing, left, action_ts, thread):
    """Record that `clicker` takes the challenge on at `goal`, on their acceptance row (new, or the
    one they left, which is taken up again). Returns (entry, name), or None once they have been told it
    could not be saved. `mine` is what a personal post offered them, so the sizes they were offered
    are kept with the acceptance; None on a post with a team figure."""
    phrase = describe(key, goal)
    entry = weekly_entry(entry_id(post_id, key), plan["week"], goal, phrase,
                         baseline(key, row), kind=CHALLENGES[key]["kind"])
    # the goal as it stands: Steady (0), or a lighter start for a newcomer, or the size they picked
    entry["tier"] = mine["sizes"].index(goal) - mine["below"] if mine and mine["sizes"] else 0
    offered = {}
    if mine and mine["sizes"]:
        offered["sizes"] = mine["sizes"]
        if mine["below"]:
            offered["below"] = mine["below"]
    # Someone who has opted out of the boards is counted on the post but never named on it.
    name = ANONYMOUS if (row and row.get("leaderboard_optout")) else slack_user(token, clicker)
    fields = {
        "record_key": accept_key(post_id, key, clicker), "row_type": ACCEPT_ROW,
        "id": post_id, "name": name or clicker, "group_id": clicker, "member_name": name,
        "grant_type": key, "status": "in", "week_key": plan["week"].isoformat(),
        "slack_channel_id": result["channel"], "last_processed_ts": action_ts,
        "created_at": clicker_today(input, token, clicker).isoformat(),
        # The entry is kept here as well as on their row: this is the copy spotter finds for
        # someone with no row yet, and the one a recap falls back on. On a personal post it also
        # keeps the sizes they were offered (and how many of them are lighter than Steady), so a
        # press on one later is judged against what was offered then and not against a row that
        # may have moved since.
        "content": json.dumps(dict(entry, **offered), separators=(",", ":"))}
    saved = table.update(existing.get("$record_id"), fields) if left else table.create(fields)[0]
    if not saved:
        result["error"] = "could not save the acceptance; the buttons are unchanged"
        tell(result, token, result["channel"], clicker, SAID_AGAIN, thread_ts=thread)
        return None
    return entry, name


def redraw_after_join(result, token, table, plan, index, post_id, key, clicker, name, ts, goal=0):
    """Draw the post again with `clicker` on its list (even if the table is slow to show them), at
    `goal` when that is given (what they have just set, which a slow table may not show yet).
    Returns (people, verify): the acceptances now, or None when they could not be read, and a function
    to call once the person has been told. A press that landed while this one was being drawn may be
    missing from it, and the later edit wins, so verify reads again and redraws until the message
    agrees with the table."""
    def current():
        """Everyone's acceptances now, with this person in even if the table is slow to show them."""
        rows = table.acceptances(post_id)
        if rows is LOOKUP_FAILED:
            return None
        people = people_by_key(rows)
        if clicker not in [p["id"] for p in people.get(key, [])]:
            people.setdefault(key, []).append({"id": clicker, "name": name, "goal": goal})
        elif goal:
            for person in people[key]:
                if person["id"] == clicker:
                    person["goal"] = goal
        return people

    channel = result["channel"]
    spec, keys = plan_spec(plan, index), plan["groups"][index]["keys"]
    people = current()
    if people is None:
        return None, None
    result["accepted"] = len(people.get(key, []))
    value_of = lambda k: live_value(post_id, k)                      # noqa: E731
    if ts:
        render_set(token, channel, ts, spec, plan, people, value_of, result)
    else:
        result["warnings"].append("no message ts to redraw")
    shown = [signature(people, keys)]

    def verify():
        for _pass in range(VERIFY_PASSES):
            _sleep(VERIFY_DELAY)
            fresh = current()
            if fresh is None or signature(fresh, keys) == shown[0]:
                break
            shown[0] = signature(fresh, keys)
            result["accepted"] = len(fresh.get(key, []))
            if ts:
                render_set(token, channel, ts, spec, plan, fresh, value_of, result)
    return people, verify


def click_live(input, result, token, table, post_id, key):
    channel, clicker = result["channel"], result["user_id"]
    source_ts = str(input.get("source_ts") or "").strip()
    action_ts = str(input.get("action_ts") or "").strip() or "{:.6f}".format(_now())
    result["post_id"], result["activity"] = post_id, key

    post = table.post_row(post_id)
    if post is LOOKUP_FAILED:
        # Nothing has been touched, so the button still works: press again.
        result["error"] = "could not read the challenge; nothing changed"
        tell(result, token, channel, clicker, SAID_AGAIN)
        return
    plan = parse_plan(post) if post else None
    if not plan or key not in plan["targets"]:
        result["ok"] = True
        result["skipped"] = "challenge not found"
        tell(result, token, channel, clicker, SAID_GONE)
        return
    index = next((i for i, g in enumerate(plan["groups"]) if key in g["keys"]), 0)
    # A press inside the thread is answered inside the thread.
    thread = plan["main_ts"] if index and plan["main_ts"] else None
    if (post.get("status") or "") not in (OPEN, POSTING):
        result["ok"] = True
        result["skipped"] = "this week's challenges have ended"
        tell(result, token, channel, clicker, SAID_ENDED, thread_ts=thread)
        return

    result["week"] = plan["week"].isoformat()
    phrase = describe(key, plan["targets"][key])
    posted_goal = plan["targets"][key]               # the team figure: the crew's pace
    personal, mine = plan["personal"], None          # `mine`: what they are offered, on a personal post
    ts = source_ts or plan["groups"][index]["ts"]

    existing = table.acceptance(post_id, key, clicker)
    if existing is LOOKUP_FAILED:
        result["error"] = "could not read the acceptances; nothing changed"
        tell(result, token, channel, clicker, SAID_AGAIN, thread_ts=thread)
        return
    # Someone who opted out earlier has a row still, marked out: pressing again takes them on again, on
    # that row (it is one a person, so it is updated and not made twice), from a fresh starting total.
    left = existing is not None and (existing.get("status") or "in") != "in"
    result["already"] = existing is not None and not left
    if existing is None or left:
        # Their running total of the activity at this moment is what "done towards the goal" is
        # measured from, so it is read before anything is written: without it the goal could
        # not be judged later, and a press is better refused than taken without it.
        row = table.activity_row(key, clicker)
        if row is LOOKUP_FAILED:
            result["error"] = "could not read your row of the activity; nothing changed"
            tell(result, token, channel, clicker, SAID_AGAIN, thread_ts=thread)
            return
        goal = posted_goal
        if personal:
            mine = personal_offer(row, key, post_id, plan["week"], plan["level"], posted_goal)
            goal = mine["goal"]
            phrase = describe(key, goal)
            if mine["sizes"]:
                # Pressing the category only shows what is on offer: nothing is written, and nobody is
                # counted, until they pick a size (click_goal), which is what accepts it.
                result["ok"] = True
                result["skipped"] = "waiting for a size to be picked"
                label = CHALLENGES[key]["label"]
                tell(result, token, channel, clicker, JOIN_TEXT.format(label=label), thread_ts=thread,
                     blocks=pick_blocks("", key, mine["sizes"][0], mine["sizes"][1:], None,
                                        lambda size, _which: goal_value(post_id, key, size),
                                        ask=JOIN_CONTEXT.format(
                                            label=label, ask=JOIN_ASK[min(mine["below"], 2)]),
                                        picks=size_picks(mine["sizes"], mine["below"])))
                return
        written = write_acceptance(input, result, token, table, plan, post_id, key, clicker, row,
                                   goal, mine, existing, left, action_ts, thread)
        if written is None:
            return
        entry, name = written
    else:
        # A second press changes no count, but it does put right a goal that failed to reach their
        # row the first time -- from the entry as first made, so the starting total is not moved.
        name = existing.get("member_name") or ""
        entry = weekly_entry_from(existing.get("content"))
        row = table.activity_row(key, clicker) if entry else None
        if personal and entry:
            phrase = entry.get("text") or describe(key, entry["goal"])      # theirs, not the team's
            offered = kept_sizes(entry)
            if offered:
                mine = {"sizes": offered, "below": kept_below(entry, len(offered)), "known": True}
            elif row is not LOOKUP_FAILED:
                mine = personal_offer(row, key, post_id, plan["week"], plan["level"], posted_goal)
    result["user_name"] = name
    result["tracking"] = track(table, row, entry)
    if result["tracking"] in ("blocked", "unwritten", "unreadable"):
        result["warnings"].append("tracking: {} for {}".format(result["tracking"], key))

    people, verify = redraw_after_join(result, token, table, plan, index, post_id, key, clicker,
                                       name, ts, goal=int((entry or {}).get("goal") or 0))
    if people is None:
        result["warnings"].append("could not read the acceptances to redraw the post")
        result["ok"] = True
        tell(result, token, channel, clicker, ":white_check_mark: You are in for *{}*. The "
                        "count will refresh on the next press.".format(phrase), thread_ts=thread)
        return
    note = (GAME_TRACKING_NOTES if is_game(key) else TRACKING_NOTES).get(result["tracking"], "")
    posted = plan["targets"][key]
    own = int((entry or {}).get("goal") or 0)         # theirs, once they have picked a size
    if personal:
        if result["already"]:
            said = ":information_source: You have already taken this one on. Your challenge: " \
                   "*{}* this week.".format(phrase)
            if result["tracking"] != "tracked":
                said += " " + note
        else:
            said = ":white_check_mark: You are in: *{}* this week. {}".format(phrase, note)
    elif result["already"]:
        said = ":information_source: You have already accepted *{}*.".format(phrase)
        if own and own != posted:
            said += " You are going for *{}*.".format(describe(key, own))
        if result["tracking"] != "tracked":
            said += " " + note
    else:
        said = ":white_check_mark: You are in: *{}* this week. {}".format(phrase, note)
    said = said.strip()
    own_sizes = (mine or {}).get("sizes") or []
    picks = ask = None
    if personal:
        # On a personal post the sizes are theirs: bigger ones for someone who has taken this
        # challenge on before, lighter starting points for a newcomer to it. A pick is kept on their
        # row or, for an activity they have no row of yet, on their acceptance, so both can pick.
        sizes = own_sizes[1:]
        if own_sizes:
            posted = own_sizes[0]                         # the smallest on offer
            below = (mine or {}).get("below", 0)
            picks, ask = size_picks(own_sizes, below), pick_ask(below)
        pickable = bool(sizes) and result["tracking"] in ("tracked", "pending")
    else:
        # The bigger goals on offer ride along with the note -- but only for someone who has taken
        # this same challenge on in an earlier week (a newcomer to it has nothing to level up from
        # yet), and whose goal is kept on their row, where it can change.
        sizes = plan["up"].get(key) or []
        pickable = bool(sizes) and result["tracking"] == "tracked" and took_before(row, post_id, key)
    picker = pick_blocks(said, key, posted, sizes, own or posted,
                         lambda goal, _which: goal_value(post_id, key, goal), ask=ask, picks=picks) \
        if pickable else None
    if result["already"]:
        # pressing a challenge they are already in is the moment to offer the way out
        picker = (picker or [_section(said)]) + [
            optout_row(key, optout_value(post_id, key), CHALLENGES[key]["label"])]
    tell(result, token, channel, clicker, said, thread_ts=thread, blocks=picker)
    verify()
    result["ok"] = True


def click_progress(input, result, token, table, thread):
    """A press on "Show my progress": the presser's goals for the week, with bars, privately.
    Nothing is written."""
    channel, clicker = result["channel"], result["user_id"]
    thread = thread or None
    today = clicker_today(input, token, clicker)
    rows = table.person_rows(clicker)
    waiting = table.waiting_entries(clicker) if rows is not LOOKUP_FAILED else LOOKUP_FAILED
    if rows is LOOKUP_FAILED or waiting is LOOKUP_FAILED:
        result["error"] = "could not read your rows; nothing shown"
        tell(result, token, channel, clicker, SAID_PROGRESS_AGAIN, thread_ts=thread)
        return
    goals = my_goals(rows, waiting, today)
    result["progress_shown"] = len(goals)
    result["week"] = monday_of(today).isoformat()
    if not goals:
        tell(result, token, channel, clicker, PROGRESS_NONE, thread_ts=thread)
    else:
        tell(result, token, channel, clicker, "Your weekly challenges: {} of {} cleared".format(
                 cleared_count(goals), len(goals)),
             thread_ts=thread, blocks=progress_blocks(goals, monday_of(today), today))
    result["ok"] = True


def join_at_size(input, result, token, table, plan, post_id, key, goal, row, existing, thread):
    """A press on a size by someone who is not in the challenge yet (on a personal post): they take it
    on at that size. The sizes are worked out again from their row, as when the note was shown, so a
    button that is no longer one of them is refused; nothing is written then. The post is redrawn with
    them on its list, as a press on a post with a team figure does."""
    channel, clicker = result["channel"], result["user_id"]
    action_ts = str(input.get("action_ts") or "").strip() or "{:.6f}".format(_now())
    left = existing is not None
    offer = personal_offer(row, key, post_id, plan["week"], plan["level"], plan["targets"][key])
    if goal not in offer["sizes"]:
        result["ok"] = True
        result["skipped"] = "not one of the sizes on offer"
        tell(result, token, channel, clicker, SAID_PICK_GONE, thread_ts=thread)
        return
    written = write_acceptance(input, result, token, table, plan, post_id, key, clicker, row, goal,
                               offer, existing, left, action_ts, thread)
    if written is None:
        return
    entry, name = written
    result["user_name"] = name
    result["tracking"] = track(table, row, entry)
    if result["tracking"] in ("blocked", "unwritten", "unreadable"):
        result["warnings"].append("tracking: {} for {}".format(result["tracking"], key))
    result["picked"], result["picked_goal"] = entry["text"], goal
    index = next((i for i, g in enumerate(plan["groups"]) if key in g["keys"]), 0)
    people, verify = redraw_after_join(result, token, table, plan, index, post_id, key, clicker,
                                       name, plan["groups"][index]["ts"], goal=goal)
    if people is None:
        result["warnings"].append("could not read the acceptances to redraw the post")
    tier = offer["sizes"].index(goal) - offer["below"]
    tell(result, token, channel, clicker,
         SAID_JOINED + picked_note(key, tier_pick(tier), goal, result["tracking"]), thread_ts=thread)
    if verify:
        verify()
    result["ok"] = True


def click_goal(input, result, token, table, post_id, key, goal):
    """A press on one of the sizes in the private note: this person's own goal for the challenge
    is set to it. Only their own entry changes; the post, its counts and everyone else's goal stay.

    The entry on their row is changed first -- it is what spotter settles against, and what the
    person is told is theirs -- then the copy on their acceptance row, which a recap and a first
    log fall back on. Only a goal still open can change, and only to a size the post offered."""
    channel, clicker = result["channel"], result["user_id"]
    result["post_id"], result["activity"] = post_id, key
    post = table.post_row(post_id)
    if post is LOOKUP_FAILED:
        result["error"] = "could not read the challenge; nothing changed"
        tell(result, token, channel, clicker, SAID_PICK_AGAIN)
        return
    plan = parse_plan(post) if post else None
    if not plan or key not in plan["targets"]:
        result["ok"] = True
        result["skipped"] = "challenge not found"
        tell(result, token, channel, clicker, SAID_GONE)
        return
    index = next((i for i, g in enumerate(plan["groups"]) if key in g["keys"]), 0)
    thread = plan["main_ts"] if index and plan["main_ts"] else None      # answered where it was pressed
    result["week"] = plan["week"].isoformat()
    if (post.get("status") or "") not in (OPEN, POSTING):
        result["ok"] = True
        result["skipped"] = "this week's challenges have ended"
        tell(result, token, channel, clicker, SAID_ENDED, thread_ts=thread)
        return
    sizes = [plan["targets"][key]] + plan["up"].get(key, [])
    if not plan["personal"] and goal not in sizes:        # (a personal post's are worked out below)
        result["ok"] = True
        result["skipped"] = "not one of the sizes on offer"
        tell(result, token, channel, clicker, SAID_PICK_GONE, thread_ts=thread)
        return
    existing = table.acceptance(post_id, key, clicker)
    row = None if existing is LOOKUP_FAILED else table.activity_row(key, clicker)
    if existing is LOOKUP_FAILED or row is LOOKUP_FAILED:
        result["error"] = "could not read your acceptance; nothing changed"
        tell(result, token, channel, clicker, SAID_PICK_AGAIN, thread_ts=thread)
        return
    if existing is None or (existing.get("status") or "in") != "in":
        if plan["personal"]:
            # Pressing the category showed the sizes and wrote nothing: picking one is what takes the
            # challenge on, at that size.
            join_at_size(input, result, token, table, plan, post_id, key, goal, row, existing, thread)
            return
        result["ok"] = True
        result["skipped"] = "has not accepted this challenge"
        tell(result, token, channel, clicker, SAID_PICK_FIRST, thread_ts=thread)
        return
    copy = weekly_entry_from(existing.get("content"))
    below = 0                                             # sizes under Steady: a newcomer's lighter ones
    if plan["personal"]:
        # the sizes are theirs: the ones their acceptance kept when they were offered, bigger ones for
        # someone who has taken this challenge before and lighter ones for a newcomer. (One from
        # before they were kept is worked out again, which can differ a little for a row whose two
        # lists have drifted apart since.)
        sizes = kept_sizes(copy)
        if sizes:
            below = kept_below(copy, len(sizes))
        else:
            offer = personal_offer(row, key, post_id, plan["week"], plan["level"],
                                   plan["targets"][key])
            sizes, below = offer["sizes"], offer["below"]
        if not sizes or goal not in sizes:
            result["ok"] = True
            result["skipped"] = "not one of the sizes on offer" if sizes else "only one size"
            tell(result, token, channel, clicker, SAID_PICK_GONE if sizes else SAID_PICK_ONE,
                 thread_ts=thread)
            return
    elif not took_before(row, post_id, key):
        result["ok"] = True
        result["skipped"] = "has not taken this challenge on before"
        tell(result, token, channel, clicker, SAID_PICK_NEW, thread_ts=thread)
        return
    held = next((e for e in weekly_entries((row or {}).get(WEEKLY_COLUMN))
                 if e["post"] == entry_id(post_id, key)), None)
    entry = held or copy
    if entry is None:
        result["error"] = "your acceptance has no readable goal; nothing changed"
        tell(result, token, channel, clicker, SAID_PICK_AGAIN, thread_ts=thread)
        return
    if entry.get("state") != "open":
        result["ok"] = True
        result["skipped"] = "the goal is already settled"
        said = SAID_PICK_CLEARED if entry.get("state") == "done" else SAID_PICK_CLOSED
        tell(result, token, channel, clicker,
             said.format(entry.get("text") or describe(key, entry["goal"])), thread_ts=thread)
        return
    tier = sizes.index(goal) - below                      # 0 Steady; above it bigger, below it lighter
    chosen = dict(entry, goal=goal, text=describe(key, goal), tier=tier)
    if held is not None and int(held["goal"]) == goal:
        tracking = "tracked"                              # their row already says so
    else:
        tracking = retarget(table, row, chosen)
    if tracking in ("blocked", "unwritten", "unreadable", "closed"):
        result["error"] = "could not set your goal on your row ({}); nothing changed".format(tracking)
        tell(result, token, channel, clicker, SAID_PICK_AGAIN, thread_ts=thread)
        return
    if copy is None or int(copy["goal"]) != goal:
        kept = table.update(existing.get("$record_id"),
                            {WEEKLY_COLUMN: json.dumps(dict(copy or chosen, goal=goal,
                                                            text=chosen["text"],
                                                            tier=chosen["tier"]),
                                                       separators=(",", ":"))})
        if not kept and tracking == "pending":
            # no row of theirs holds the goal yet, so the acceptance row is the only place it lives
            result["error"] = "could not save your goal; nothing changed"
            tell(result, token, channel, clicker, SAID_PICK_AGAIN, thread_ts=thread)
            return
        if not kept:
            result["warnings"].append("the copy of the goal on your acceptance was not updated")
    result["tracking"] = tracking
    result["picked"], result["picked_goal"] = chosen["text"], goal          # only once it is saved
    if plan["personal"]:
        # a personal post lists what each person took on, so it is drawn again with their new goal
        _people, _verify = redraw_after_join(result, token, table, plan, index, post_id, key, clicker,
                                             existing.get("member_name") or "",
                                             plan["groups"][index]["ts"], goal=goal)
    tell(result, token, channel, clicker, picked_note(key, tier_pick(tier), goal, tracking),
         thread_ts=thread)
    result["ok"] = True


def click_optout(input, result, token, table, post_id, key):
    """A press on "Opt out of this challenge": the person is taken out of it, so nothing is counted for
    them and the post no longer lists them.

    Their entry comes off their row of the activity first -- it is what spotter settles against and
    announces, and the row's count of challenges taken on goes back down -- then their acceptance row
    is marked out and its copy of the entry cleared, because spotter and the game steps pick an
    acceptance's entry up without looking at its status. Pressing the challenge again takes them on
    again. A goal already cleared stays: it was done. Each step can be repeated, so a press that failed
    part way is finished by pressing again."""
    channel, clicker = result["channel"], result["user_id"]
    result["post_id"], result["activity"] = post_id, key
    post = table.post_row(post_id)
    if post is LOOKUP_FAILED:
        result["error"] = "could not read the challenge; nothing changed"
        tell(result, token, channel, clicker, SAID_OUT_AGAIN)
        return
    plan = parse_plan(post) if post else None
    if not plan or key not in plan["targets"]:
        result["ok"] = True
        result["skipped"] = "challenge not found"
        tell(result, token, channel, clicker, SAID_GONE)
        return
    index = next((i for i, g in enumerate(plan["groups"]) if key in g["keys"]), 0)
    thread = plan["main_ts"] if index and plan["main_ts"] else None      # answered where it was pressed
    result["week"] = plan["week"].isoformat()
    if (post.get("status") or "") not in (OPEN, POSTING):
        result["ok"] = True
        result["skipped"] = "this week's challenges have ended"
        tell(result, token, channel, clicker, SAID_ENDED, thread_ts=thread)
        return
    label = CHALLENGES[key]["label"]
    existing = table.acceptance(post_id, key, clicker)
    row = None if existing is None or existing is LOOKUP_FAILED else table.activity_row(key, clicker)
    if existing is LOOKUP_FAILED or row is LOOKUP_FAILED:
        result["error"] = "could not read your acceptance; nothing changed"
        tell(result, token, channel, clicker, SAID_OUT_AGAIN, thread_ts=thread)
        return
    if existing is None or (existing.get("status") or "in") != "in":
        result["ok"] = True
        result["skipped"] = "not in this challenge"
        tell(result, token, channel, clicker, SAID_OUT_NOT_IN.format(label), thread_ts=thread)
        return
    raw = (row or {}).get(WEEKLY_COLUMN)
    mine = weekly_entries(raw)
    held = next((e for e in mine if e["post"] == entry_id(post_id, key)), None)
    entry = held or weekly_entry_from(existing.get("content"))
    if entry is not None and entry.get("state") != "open":
        result["ok"] = True
        result["skipped"] = "the goal is already settled"
        said = SAID_PICK_CLEARED if entry.get("state") == "done" else SAID_PICK_CLOSED
        tell(result, token, channel, clicker, said.format(entry.get("text") or label), thread_ts=thread)
        return
    if held is not None:
        text = weekly_text_without(raw, [e for e in mine if e is not held])
        # (a column holding something that is not ours has no entry of ours to take off it)
        if text is not None and not table.update(row.get("$record_id"), {WEEKLY_COLUMN: text}):
            result["error"] = "could not take it off your row; nothing changed"
            tell(result, token, channel, clicker, SAID_OUT_AGAIN, thread_ts=thread)
            return
    if not table.update(existing.get("$record_id"), {"status": "out", "content": ""}):
        result["error"] = "could not save that you are out; press the button again"
        tell(result, token, channel, clicker, SAID_OUT_AGAIN, thread_ts=thread)
        return
    result["opted_out"] = True
    result["user_name"] = existing.get("member_name") or ""

    keys = plan["groups"][index]["keys"]
    spec, ts = plan_spec(plan, index), plan["groups"][index]["ts"]
    value_of = lambda k: live_value(post_id, k)                      # noqa: E731

    def current():
        """Everyone's acceptances now, with this person off even if the table is slow to show it."""
        rows = table.acceptances(post_id)
        if rows is LOOKUP_FAILED:
            return None
        people = people_by_key(rows)
        people[key] = [p for p in people.get(key, []) if p["id"] != clicker]
        return people

    people = current()
    if people is None:
        result["warnings"].append("could not read the acceptances to redraw the post")
    else:
        result["accepted"] = len(people.get(key, []))
        render_set(token, channel, ts, spec, plan, people, value_of, result)
    tell(result, token, channel, clicker, SAID_OUT.format(label), thread_ts=thread)
    shown = signature(people, keys) if people is not None else None
    for _pass in range(VERIFY_PASSES if people is not None else 0):
        _sleep(VERIFY_DELAY)
        fresh = current()
        if fresh is None or signature(fresh, keys) == shown:
            break
        people, shown = fresh, signature(fresh, keys)
        result["accepted"] = len(people.get(key, []))
        render_set(token, channel, ts, spec, plan, people, value_of, result)
    result["ok"] = True


def click_optout_test(input, result, token, key, ts, main_ts):
    """A press on "Opt out of this challenge" in the note of a TEST post: nothing is saved, but the
    test post keeps its list in its own buttons, so the message the person pressed Accept in is read
    back, they are taken off its list, and it is redrawn (and the channel message too, when that was a
    reply), as a real opt-out redraws the post."""
    channel, clicker = result["channel"], result["user_id"]
    result["activity"], result["testing"] = key, True
    thread = main_ts or None
    parsed = test_state_of(slack_message(token, channel, ts, main_ts or None))
    if not parsed:
        result["warnings"].append("test post: could not read the message to update its list (the bot "
                                  "needs the channels:history scope)")
    else:
        spec, people, mmain, _k = parsed
        people[key] = [p for p in people.get(key, []) if p["id"] != clicker]
        result["accepted"] = len(people.get(key, []))
        render_message(token, channel, ts, spec, people, lambda k: test_value(spec, people, mmain, k), result)
        if spec["index"] and mmain:
            update_test_main(token, channel, mmain, key, clicker, "", result, leave=True)
    tell(result, token, channel, clicker, TEST_SAID_OUT.format(CHALLENGES[key]["label"]), thread_ts=thread)
    result["ok"] = True


def click_goal_test(input, result, token, key, goal, rung, ts="", main_ts=""):
    """A press on a size in the private note of a TEST post: nothing is saved, so it is only said
    back to them, in the words the real one would use. On a personal post it is also what takes them on
    (a press on the category only shows the sizes), so when the message is named they are put on its
    list, and it is redrawn, as a real pick redraws the post."""
    channel, clicker = result["channel"], result["user_id"]
    result["activity"], result["testing"] = key, True
    result["picked"], result["picked_goal"] = describe(key, goal), goal
    thread = main_ts or None
    lead = ""
    if ts:
        parsed = test_state_of(slack_message(token, channel, ts, thread))
        if not parsed:
            result["warnings"].append("test post: could not read the message to update its list (the bot "
                                      "needs the channels:history scope)")
        else:
            spec, people, mmain, _k = parsed
            mine = next((p for p in people.get(key, []) if p["id"] == clicker), None)
            if mine is None or mine.get("goal") != goal:
                # on the list at this goal (it is what the list shows beside their name)
                if mine is None:
                    name = slack_user(token, clicker)
                    result["user_name"] = name
                    mine = {"id": clicker, "name": name}
                    people.setdefault(key, []).append(mine)
                    lead = "you are in. "
                name = mine["name"]
                mine["goal"] = goal
                value_of = lambda k: test_value(spec, people, mmain, k)         # noqa: E731
                if any(len(value_of(c["key"]).encode("utf-8")) > TEST_VALUE_MAX
                       for c in spec["challenges"]):
                    result["ok"] = True
                    result["skipped"] = "test post is full"
                    tell(result, token, channel, clicker, SAID_FULL, thread_ts=thread)
                    return
                render_message(token, channel, ts, spec, people, value_of, result)
                if spec["index"] and mmain:
                    update_test_main(token, channel, mmain, key, clicker, name, result, goal=goal)
            result["accepted"] = len(people.get(key, []))
    said = EVERY_PICK[rung]["said"].format(goal=describe(key, goal))
    tell(result, token, channel, clicker,
         ":test_tube: Test: {}{} {} Nothing was saved, so it is not tracked.".format(
             lead, EVERY_PICK[rung]["icon"], said), thread_ts=thread)
    result["ok"] = True


def update_test_main(token, channel, main_ts, key, clicker, name, result, leave=False, goal=0):
    """A press in a reply of a test post: the channel message holds the whole post's state in its
    own buttons, so it is read back from Slack, the person added (or taken off, when they `leave`),
    and it is redrawn -- its list and its count then include what is accepted in the thread."""
    parsed = test_state_of(slack_message(token, channel, main_ts))
    if not parsed:
        result["warnings"].append("test post: could not read the channel message to update its "
                                  "list (the bot needs the channels:history scope)")
        return
    mspec, mpeople, mmain, _k = parsed
    if leave:
        mpeople[key] = [p for p in mpeople.get(key, []) if p["id"] != clicker]
    else:
        mine = next((p for p in mpeople.get(key, []) if p["id"] == clicker), None)
        if mine is None:
            mine = {"id": clicker, "name": name}
            mpeople.setdefault(key, []).append(mine)
        if goal:
            mine["goal"] = goal

    def value_of(k):
        return test_value(mspec, mpeople, mmain, k)

    if any(len(value_of(c["key"]).encode("utf-8")) > TEST_VALUE_MAX for c in mspec["challenges"]):
        result["warnings"].append("test post: the channel message is full, its list was not updated")
        return
    render_message(token, channel, main_ts, mspec, mpeople, value_of, result)


TEST_POST = "test"                # a test post has no post id; no entry of anybody's is called this


def test_offer(input, table, spec, key, user_id, reference):
    """What a personal TEST post tells whoever pressed: their real offer (personal_offer), worked out
    from their own row of the activity, so the test looks like the real thing. Read only. None when
    there is no table to read or their row cannot be read, and the note then shows no figure."""
    if table is None or not str(input.get("workato_api_token") or "").strip():
        return None
    row = table.activity_row(key, user_id)
    if row is LOOKUP_FAILED:
        return None
    return personal_offer(row, key, TEST_POST, spec["week"], spec["level"], reference)


def click_test(input, result, token, parsed, table=None):
    """A press on a test post: the post's own buttons hold the state and nothing is written. A
    personal post shows the person who pressed their OWN challenge and sizes, worked out from the
    table without changing it (test_offer), not the team figure."""
    spec, people, main_ts, key = parsed
    channel, clicker = result["channel"], result["user_id"]
    ts = str(input.get("source_ts") or "").strip()
    result["activity"], result["testing"] = key, True
    result["week"] = spec["week"].isoformat()
    thread = main_ts if spec["index"] and main_ts else None
    phrase = describe(key, next(c["target"] for c in spec["challenges"] if c["key"] == key))
    if not ts:
        result["error"] = "source_ts is required to edit the test post"
        return
    already = clicker in [p["id"] for p in people.get(key, [])]
    result["already"] = already
    item = next(c for c in spec["challenges"] if c["key"] == key)
    offer = test_offer(input, table, spec, key, clicker, item["target"]) if spec.get("personal") else None
    if offer is not None and offer["sizes"] and not already:
        # As on a real post, a press on the category only shows their sizes: nobody is put on the list
        # until they pick one (click_goal_test).
        label = CHALLENGES[key]["label"]
        tell(result, token, channel, clicker, ":test_tube: Test: " + JOIN_TEXT[len(":crossed_swords: "):].format(label=label),
             thread_ts=thread,
             blocks=pick_blocks("", key, offer["sizes"][0], offer["sizes"][1:], None,
                                lambda size, which: test_goal_value(key, size, which, ts, main_ts),
                                ask=JOIN_CONTEXT.format(label=label, ask=JOIN_ASK[min(offer["below"], 2)])
                                + TEST_PICK_OWN,
                                picks=size_picks(offer["sizes"], offer["below"])))
        result["ok"] = True
        result["skipped"] = "waiting for a size to be picked"
        return
    if not already:
        name = slack_user(token, clicker)
        result["user_name"] = name
        people.setdefault(key, []).append({"id": clicker, "name": name})

    def value_of(k):
        return test_value(spec, people, main_ts, k)

    if any(len(value_of(c["key"]).encode("utf-8")) > TEST_VALUE_MAX for c in spec["challenges"]):
        people[key] = [p for p in people[key] if p["id"] != clicker]
        result["ok"] = True
        result["skipped"] = "test post is full"
        tell(result, token, channel, clicker, SAID_FULL, thread_ts=thread)
        return
    result["accepted"] = len(people.get(key, []))
    if not already:
        if render_message(token, channel, ts, spec, people, value_of, result):
            result["error"] = "could not update the test post"
            return
        if spec["index"] and main_ts:
            update_test_main(token, channel, main_ts, key, clicker, result["user_name"], result)
    said = (":test_tube: Test: you have already accepted *{}*.".format(phrase) if already
            else ":test_tube: Test: you are in for *{}*. Nothing was saved, so it is not "
                 "tracked.".format(phrase))
    picker = None
    if spec.get("personal"):
        if offer is None:
            said = (":test_tube: Test: you have already taken this one on." if already else
                    ":test_tube: Test: you are in. On a real post your own target, sized to your "
                    "recent weeks, appears here. Nothing was saved, so it is not tracked.")
        else:
            figure = describe(key, offer["goal"])
            if already:
                said = (":test_tube: Test: you have already taken this one on. Your challenge: "
                        "*{}* this week.".format(figure))
            else:
                lead = "Your challenge, sized to you" if offer["known"] else "A gentle start for you"
                said = (":test_tube: Test: you are in. {}: *{}* this week. {} Nothing was saved, so "
                        "it is not tracked.".format(lead, figure, offer["basis"]))
            sizes = offer["sizes"]
            if sizes:
                picker = pick_blocks(said, key, sizes[0], sizes[1:], offer["goal"],
                                     lambda goal, which: test_goal_value(key, goal, which, ts, main_ts),
                                     ask=pick_ask(offer["below"]) + TEST_PICK_OWN,
                                     picks=size_picks(sizes, offer["below"]))
    else:
        sizes = item.get("up") or []
        picker = pick_blocks(said, key, item["target"], sizes, item["target"],
                             lambda goal, rung: test_goal_value(key, goal, rung),
                             ask=TEST_PICK_ASK) if sizes else None
    if already:
        picker = (picker or [_section(said)]) + [
            optout_row(key, test_optout_value(key, ts, main_ts), CHALLENGES[key]["label"])]
    tell(result, token, channel, clicker, said, thread_ts=thread, blocks=picker)
    result["ok"] = True


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def main(input):
    """Args:
        input (dict): dictionary containing input field(s) supplied in the recipe step
    Returns:
        dict: dictionary with keys matching the output schema
    """
    value = str(input.get("action_value") or "").strip()
    is_click = bool(value)
    mode = str(input.get("mode") or "post").strip().lower()
    result = {
        "ok": False, "error": "", "warnings": [], "skipped": "",
        "mode": "click" if is_click else mode, "testing": False, "preview": False,
        "week": "", "level": _int(input.get("level"), 1, 1, MAX_LEVEL),
        "channel": str(input.get("channel") or "").strip(), "post_id": "",
        "message_ts": "", "reply_ts": [], "challenges": [], "left_out": [],
        "closed_previous": 0, "rows_read": 0, "rows_loose": 0, "rows_written": 0,
        "user_id": str(input.get("user_id") or "").strip(), "user_name": "",
        "activity": "", "accepted": 0, "already": False, "tracking": "", "recap": [],
        "preview_json": "", "progress_shown": 0, "post_style": DEFAULT_STYLE,
        "picked": "", "picked_goal": 0, "adapted_from": "", "personal": False, "opted_out": False,
    }
    table = Table(input.get("workato_api_token") or "")
    try:
        _run(input, result, table, is_click, value)
    except Exception as error:                                     # noqa: BLE001
        result["ok"] = False
        result["error"] = "unexpected {}: {}".format(type(error).__name__, str(error)[:300])
    result["rows_written"] = table.written
    result["warnings"] += table.errors
    return result


def _run(input, result, table, is_click, value):
    token = str(input.get("slack_bot_token") or "").strip()
    if is_click:
        if not result["user_id"] or not result["channel"]:
            result["error"] = "user_id and channel are both required"
            return
        if not token:
            result["error"] = "slack_bot_token is required"
            return
        parsed = parse_value(value)
        if not parsed:
            result["error"] = "action_value is not a weekly challenge button"
            return
        if parsed[0] == "test":
            click_test(input, result, token, parsed[1], table)
            return
        if parsed[0] == "goal_test":
            click_goal_test(input, result, token, *parsed[1:])
            return
        if parsed[0] == "optout_test":
            click_optout_test(input, result, token, parsed[1], parsed[2], parsed[3])
            return
        if not str(input.get("workato_api_token") or "").strip():
            result["error"] = "workato_api_token is required"
            return
        if parsed[0] == "progress":
            click_progress(input, result, token, table, parsed[1])
            return
        if parsed[0] == "goal":
            click_goal(input, result, token, table, parsed[1], parsed[2], parsed[3])
            return
        if parsed[0] == "optout":
            click_optout(input, result, token, table, parsed[1], parsed[2])
            return
        click_live(input, result, token, table, parsed[1], parsed[2])
        return

    flags = {"testing": _switch(input.get("testing")), "skip_post": _switch(input.get("skip_post")),
             "force": _switch(input.get("force")),
             "close_previous": _switch(input.get("close_previous"), default=True)}
    result["testing"] = flags["testing"]
    if result["mode"] not in ("post", "recap"):
        result["error"] = "mode is post (the default) or recap"
        return
    if result["mode"] == "recap":
        if not str(input.get("workato_api_token") or "").strip():
            result["error"] = "workato_api_token is required"
        elif not result["channel"]:
            result["error"] = "channel is required: it says which post to recap"
        elif not flags["skip_post"] and not token:
            result["error"] = "slack_bot_token is required to post the recap (skip_post = yes previews)"
        else:
            recap_week(input, result, token, table, flags)
        return
    if not input.get("local_data_file") and not str(input.get("workato_api_token") or "").strip():
        result["error"] = "workato_api_token is required"
        return
    post_week(input, result, token, table, flags)


if __name__ == "__main__":
    # Looking at this week's goals from a laptop: python3 weekly_challenge.py [level]
    # Needs WORKATO_API_TOKEN (or LOCAL_DATA_FILE). It posts only if SLACK_CHANNEL and
    # SLACK_BOT_TOKEN are set, and then only as a test post.
    channel = os.environ.get("SLACK_CHANNEL", "")
    print(json.dumps(main({
        "workato_api_token": os.environ.get("WORKATO_API_TOKEN", ""),
        "slack_bot_token": os.environ.get("SLACK_BOT_TOKEN", ""),
        "channel": channel,
        "level": sys.argv[1] if len(sys.argv) > 1 else "1",
        "testing": "yes",
        "skip_post": "" if channel else "yes",
        "local_data_file": os.environ.get("LOCAL_DATA_FILE", ""),
    }), indent=2))
