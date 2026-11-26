[
  {
    "control_type": "text",
    "label": "action",
    "type": "string",
    "name": "action",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "action"
    },
    "hint": "ask, reply or feedback -- blank = ask. ask: the Slack message trigger. reply: right after \"Assign task to genie\" answers. feedback: the app's Interactivity Request URL, when someone clicks Good / Bad response."
  },
  {
    "control_type": "text",
    "label": "env",
    "type": "string",
    "name": "env",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "env"
    },
    "hint": "dev or prod: which genie_console table to read and write (same columns in both). Blank = dev, the table this step has always used -- the production recipe must set this to prod explicitly. Map it from a project property or environment variable, not a fixed value, so the same recipe reads dev in dev and prod in prod with no manual change after deployment. Overridden by table_id if that is also set. Must match the env given to the builder and click recipes, or they will read and write different tables."
  },
  {
    "control_type": "text",
    "label": "table_id",
    "type": "string",
    "name": "table_id",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "table_id"
    },
    "hint": "Optional. ID of the genie_console data table (as it appears in the table's URL in Workato), overriding env entirely. Blank = use env instead. Point it at a one-off table (e.g. a sandbox copy) without a code change. Must match the table_id given to the builder and click recipes, or they will read and write different tables."
  },
  {
    "control_type": "text",
    "label": "workato_api_token",
    "type": "string",
    "name": "workato_api_token",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "workato_api_token"
    },
    "hint": "Workato API client token. Needed to read and write the genie_console table, and, when owner_lookup = live, to read a project's recipes to find its owner."
  },
  {
    "control_type": "text",
    "label": "slack_bot_token",
    "type": "string",
    "name": "slack_bot_token",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "slack_bot_token"
    },
    "hint": "Bot token (xoxb-...) used to post, update and look up Slack users. Scopes: chat:write, users:read, users:read.email; usergroups:read as well if fallback_team is a user group handle."
  },
  {
    "control_type": "text",
    "label": "dry_run",
    "type": "string",
    "name": "dry_run",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "dry_run"
    },
    "hint": "true = read only: nothing is posted to Slack or written to the table. Leave blank in production."
  },
  {
    "control_type": "text",
    "label": "text",
    "type": "string",
    "name": "text",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "text"
    },
    "hint": "ask: the Slack message text. Map the trigger's text."
  },
  {
    "control_type": "text",
    "label": "channel",
    "type": "string",
    "name": "channel",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "channel"
    },
    "hint": "ask: the Slack channel ID. Map the trigger's channel. feedback: only needed when payload is not mapped (read from it instead)."
  },
  {
    "control_type": "text",
    "label": "thread_ts",
    "type": "string",
    "name": "thread_ts",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "thread_ts"
    },
    "hint": "ask: the thread the message was posted in, if any. Map the trigger's thread_ts; blank for a top-level message. Also used, when reply_thread_ts is blank, as the thread the reply call posts and saves the conversation in."
  },
  {
    "control_type": "text",
    "label": "message_ts",
    "type": "string",
    "name": "message_ts",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "message_ts"
    },
    "hint": "Used, when reply_thread_ts and thread_ts are both blank, as the thread the reply call posts in (a reply to a top-level message threads off that message). feedback: only needed when payload is not mapped (the clicked message's ts)."
  },
  {
    "control_type": "text",
    "label": "subtype",
    "type": "string",
    "name": "subtype",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "subtype"
    },
    "hint": "ask: map the trigger's message subtype, if any. bot_message, message_changed, message_deleted, channel_join, channel_leave and thread_broadcast are all skipped -- never a question to answer."
  },
  {
    "control_type": "text",
    "label": "bot_id",
    "type": "string",
    "name": "bot_id",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "bot_id"
    },
    "hint": "ask: map the trigger's bot_id. Any value here skips the message -- a genie's own reply must never trigger itself again."
  },
  {
    "control_type": "text",
    "label": "user_id",
    "type": "string",
    "name": "user_id",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "user_id"
    },
    "hint": "ask: the Slack member ID who sent the message (map the trigger's user); looked up and sent to the genie as asker_slack_id / asker_name / asker_email. reply: who to credit as creator_id on a new conversation row. feedback: only needed when payload is not mapped (who clicked)."
  },
  {
    "control_type": "text",
    "label": "look",
    "type": "string",
    "name": "look",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "look"
    },
    "hint": "Optional. new (the default) or old. new: the answer's own first heading becomes a header block, the body is real Slack markdown, every table is a native table block, rules are dividers. old: the sections-and-mrkdwn card from before. If Slack rejects the new look, the old one is sent instead. Needed on both the ask and reply calls."
  },
  {
    "control_type": "text",
    "label": "redact",
    "type": "string",
    "name": "redact",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "redact"
    },
    "hint": "Optional. on (the default) or off. on: the genie is told never to write out a credential (SECRETS_NOTE), and redact_text() wipes anything that looks like one from the question, the answer, the genie's error and the warnings before anything is posted. off: the old behaviour, nothing wiped. Needed on both the ask and reply calls."
  },
  {
    "control_type": "text",
    "label": "bold",
    "type": "string",
    "name": "bold",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "bold"
    },
    "hint": "Optional. on (the default) or off. on: *bold* in the answer becomes **bold** in the new look's markdown blocks (and in table cells), and the genie is asked for bold on what matters, backticks on code. off: the old behaviour; the old look is not affected either way. Needed on both the ask and reply calls."
  },
  {
    "control_type": "text",
    "label": "kb_note",
    "type": "string",
    "name": "kb_note",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "kb_note"
    },
    "hint": "Optional. on (the default) or off. on: when the genie's row has a knowledge base, the task carries it (name / about / use_when) with a note to check it before answering. off: the task is sent exactly as it was. No knowledge base on the row = no change either way. Needed on the ask call."
  },
  {
    "control_type": "text",
    "label": "kb_mention",
    "type": "string",
    "name": "kb_mention",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "kb_mention"
    },
    "hint": "Optional. hide (the default) or say. hide: the genie never tells people its answer came from its knowledge base. say: the old note, which lets it say so. Needed on the ask call."
  },
  {
    "control_type": "text",
    "label": "ids_note",
    "type": "string",
    "name": "ids_note",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "ids_note"
    },
    "hint": "Optional. auto (the default) or off. auto: every persona except developer is told to use names, not recipe / job / connection ids, in its answer. off: no such note (the old behaviour). Needed on the ask call."
  },
  {
    "control_type": "text",
    "label": "offers_note",
    "type": "string",
    "name": "offers_note",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "offers_note"
    },
    "hint": "Optional. on (the default) or off. on: the genie is told not to offer a lookup or action it has no skill for, and not to close with an offer at all. off: no such note (the old behaviour). Needed on the ask call."
  },
  {
    "control_type": "text",
    "label": "thread_start",
    "type": "string",
    "name": "thread_start",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "thread_start"
    },
    "hint": "Optional. on (the default) or off. on: a message that is only the keyword (the hello card) saves its thread as a conversation, so people can reply in the thread without the keyword. off: nothing is saved, so a keyword-only message is not followed up (the old behaviour). Needed on the ask call."
  },
  {
    "control_type": "text",
    "label": "answer_layout",
    "type": "string",
    "name": "answer_layout",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "answer_layout"
    },
    "hint": "Optional. blocks (the default) or card. blocks: the new look's answer is posted as plain message blocks, with no coloured bar down its side, so it reads like a normal reply. An answer too long for that, or one Slack rejects, is posted as the card instead. card: every answer is the card, as before. Errors and the old look are always cards. Needed on the reply call."
  },
  {
    "control_type": "text",
    "label": "genie_name",
    "type": "string",
    "name": "genie_name",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "genie_name"
    },
    "hint": "reply: ask's genie_name output. Shown on the answer card and, if escalated, in the messages sent to the project owners."
  },
  {
    "control_type": "text",
    "label": "persona",
    "type": "string",
    "name": "persona",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "persona"
    },
    "hint": "reply: ask's persona output. Picks the answer card's colour, and is saved on the conversation row."
  },
  {
    "control_type": "text",
    "label": "keyword",
    "type": "string",
    "name": "keyword",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "keyword"
    },
    "hint": "reply: ask's keyword output. Saved on the conversation row, so a bare follow-up finds the right genie; also used, if escalated, to find the project owners to tag."
  },
  {
    "control_type": "text",
    "label": "conversation_id",
    "type": "string",
    "name": "conversation_id",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "conversation_id"
    },
    "hint": "reply: \"Assign task to genie\"'s own conversation_id output (not ask's). Saved against the thread, so the next question in it continues the same conversation."
  },
  {
    "control_type": "text",
    "label": "thinking_ts",
    "type": "string",
    "name": "thinking_ts",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "thinking_ts"
    },
    "hint": "reply: ask's thinking_ts output (the ts of the \"<genie> is thinking...\" message). The first message of the reply edits this one into the answer; blank posts a fresh message instead."
  },
  {
    "control_type": "text",
    "label": "reply_thread_ts",
    "type": "string",
    "name": "reply_thread_ts",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "reply_thread_ts"
    },
    "hint": "reply: the thread to post the reply in and save the conversation against. Map ask's channel / thread_ts outputs, or leave blank to fall back to thread_ts then message_ts."
  },
  {
    "control_type": "text",
    "label": "genie_response",
    "type": "string",
    "name": "genie_response",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "genie_response"
    },
    "hint": "reply: \"Assign task to genie\"'s answer text."
  },
  {
    "control_type": "text",
    "label": "genie_error",
    "type": "string",
    "name": "genie_error",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "genie_error"
    },
    "hint": "reply: \"Assign task to genie\"'s own error, if it failed. Any text here is shown as a red error card and escalated to the project owners, whatever genie_response says."
  },
  {
    "control_type": "text",
    "label": "question",
    "type": "string",
    "name": "question",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "question"
    },
    "hint": "reply: ask's question output, quoted back to the project owners if the genie can't answer."
  },
  {
    "control_type": "text",
    "label": "detect_unanswered",
    "type": "string",
    "name": "detect_unanswered",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "detect_unanswered"
    },
    "hint": "Optional. auto (the default) or marker. auto: an answer that reads like \"I don't have that information\" counts as unanswered even with no [[NEEDS_HUMAN]] marker (checked on the first 350 characters of an answer under 800). marker: the old behaviour -- only the marker, a failure or an empty answer count. Needed on the reply call."
  },
  {
    "control_type": "text",
    "label": "owner_ping",
    "type": "string",
    "name": "owner_ping",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "owner_ping"
    },
    "hint": "Optional. once (the default) or always. once: the project owners are brought in only the first time a thread goes unanswered; a later unanswered question in the same thread posts no tag and sends no DM. always: the old behaviour, an escalation on every unanswered question. A blocked refusal's DM is sent every time regardless. Needed on the reply call."
  },
  {
    "control_type": "text",
    "label": "owner_lookup",
    "type": "string",
    "name": "owner_lookup",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "owner_lookup"
    },
    "hint": "Optional. live (the default) or stored. live: a genie whose projects have no owner stored is looked up now (the author of a recent recipe version from an @coursera.org address) and saved on the row. stored: the old behaviour, read what is saved, never look. Needed on the reply call, together with workato_api_token."
  },
  {
    "control_type": "text",
    "label": "fallback_team",
    "type": "string",
    "name": "fallback_team",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "fallback_team"
    },
    "hint": "Optional. Who the \"couldn't find a project owner\" message points to, when there is truly nobody to tag: a Slack user group ID (S0123ABCD), its handle (needs usergroups:read), a ready <!subteam^ID> mention, or plain text. Blank = \"the IT Integrations team\" as plain words. Needed on the reply call."
  },
  {
    "control_type": "text",
    "label": "payload",
    "type": "string",
    "name": "payload",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "payload"
    },
    "hint": "feedback: the Slack block_actions payload from the Good / Bad response click. Map it as a formula with .to_json, or leave the raw payload= form body as sent. Read instead of user_id / channel / message_ts / thread_ts / feedback_value when those are not mapped."
  },
  {
    "control_type": "text",
    "label": "feedback_value",
    "type": "string",
    "name": "feedback_value",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "feedback_value"
    },
    "hint": "feedback: only needed when payload is not mapped. positive or negative, from the clicked button's value."
  }
]
