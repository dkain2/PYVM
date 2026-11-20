# New columns for the error log table

Table: **Error Notification - TBL** (`c1444a9a-03a7-4c82-8618-7796b7384b37`). These 26 columns are what `error_slack.py`
(the one Slack step: it posts the alert and handles the clicks) writes to say who did what, when, and which job. Add them by hand in Workato (Data
tables, then the table, then Add column). **Nothing was changed in Workato from here.**

- Every column is **optional** (not required), has no default, and must be named **exactly** as below (capital letters and spaces
  matter). Types: `string`, or `date_time` for the five marked.
- No column has to exist for the steps to work: until you add them, error_slack still posts and does its action, writes the old
  columns, and a warning says the tracking columns are missing. Add them in any order, any time.
- Do not rename or remove any existing column. The notifier, the old summary and repeater recipes and the dashboard read them by name.

| # | Column name | Type | Written by | What it holds |
|---|---|---|---|---|
| 1 | Notified Via | string | error_slack (post) | Email, or Email + Slack |
| 2 | Slack Channel | string | error_slack (post) | channel id the alert was posted in |
| 3 | Slack Message TS | string | error_slack (post) | ts of the Slack message; a click finds the row by it when a button carries no job |
| 4 | Slack Message URL | string | error_slack (post) | link to the Slack message |
| 5 | Notified At | date_time | error_slack (post) | when the alert went out |
| 6 | Last Action | string | error_slack (click) | Reprocess, Acknowledge, Resolve or Assign |
| 7 | Last Action By | string | error_slack (click) | name |
| 8 | Last Action By Slack ID | string | error_slack (click) | Slack user id |
| 9 | Last Action By Email | string | error_slack (click) | from Slack (users:read.email) |
| 10 | Last Action At | date_time | error_slack (click) | when |
| 11 | Last Action Result | string | error_slack (click) | for example: queued as job j-... |
| 12 | Action Log | string | error_slack (click) | one line per action, newest last; appended, never replaced |
| 13 | Reprocessed By | string | error_slack (click) | name |
| 14 | Reprocessed By Slack ID | string | error_slack (click) | Slack user id |
| 15 | Reprocessed By Email | string | error_slack (click) |  |
| 16 | Reprocessed At | date_time | error_slack (click) | also what the reprocess cooldown reads |
| 17 | Reprocess Job ID | string | error_slack (click) | the new job Workato queued |
| 18 | Reprocess Source | string | error_slack (click) | "Slack button" |
| 19 | Reprocess Result | string | error_slack (click) | enqueued or failed |
| 20 | Reprocess Error | string | error_slack (click) | why it failed |
| 21 | Acknowledged By | string | error_slack (click) | name |
| 22 | Acknowledged At | date_time | error_slack (click) | when |
| 23 | Resolved By | string | error_slack (click) | name |
| 24 | Resolved At | date_time | error_slack (click) | when |
| 25 | Assigned To | string | error_slack (click) | name (Slack id) |
| 26 | AI Feedback | string | error_slack (click) | positive or negative, on the AI analysis |

## The click recipe (yours to build)

1. In the Slack app's settings turn **Interactivity** on and point the Request URL at the recipe's trigger.
2. Trigger filter: `action_id` **starts with** `error_notification_` (every button that does something has that prefix; link buttons
   and fact chips do not, so they never run the recipe). Slack wants an answer within 3 seconds, so let the trigger answer first
   and do the work after it.
3. One step: the Python in `error_slack.py` (the same step the notification recipe calls to post). Map the trigger's payload to the `payload` input, and pass `workato_api_token` and
   `slack_bot_token`. The bot needs `chat:write`, `users:read` and `users:read.email`. Optional inputs: `allowed_user_ids`
   (who may reprocess or resolve), `cooldown_minutes`, `max_reprocess`. With a generic webhook (not Slack's own trigger), also pass
   `slack_signing_secret`, `raw_body`, `slack_request_timestamp` and `slack_signature` so a forged request is refused.
4. The step does everything else: repeats the job, writes the row, edits the Slack message and replies in the thread.

## The notification recipe

After the `error_notification.py` step, add the `error_slack.py` step with `slack_channel_id`, `slack_bot_token`,
`workato_api_token` and `alert_json` (the notifier's output of that name). Nothing else needs mapping. The email step stays as it is.
