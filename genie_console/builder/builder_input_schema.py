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
    "hint": "Trigger recipe: start. Click recipe: leave blank (read from payload_json). Inside the Integra REPEAT loop: forge_next (top of the loop) and forge_result (after Assign task to Integra). kb_attach_result: after the recipe attached the knowledge base's documents (with kb_attach_status)."
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
    "hint": "Workato API client token. Needs access to Projects, Export manifests (folder assets) and the genie_console data table."
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
    "hint": "Bot token (xoxb-...) of the Slack app whose button clicks start the click recipe. Scopes: chat:write, users:read, users:read.email."
  },
  {
    "control_type": "text",
    "label": "master_genie_handle",
    "type": "string",
    "name": "master_genie_handle",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "master_genie_handle"
    },
    "hint": "Genie the router sends questions to, e.g. gin-AaXdQ4xr-cegmKw-CD. Stored in the id column. Optional."
  },
  {
    "control_type": "text",
    "label": "payload_json",
    "type": "string",
    "name": "payload_json",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "payload_json"
    },
    "hint": "Click recipe only: the Slack block_actions payload. Map it as a formula with .to_json, e.g. =block_actions_button_pill.to_json. Leave blank on start."
  },
  {
    "control_type": "text",
    "label": "action_value",
    "type": "string",
    "name": "action_value",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "action_value"
    },
    "hint": "Click recipe: only needed when payload_json is not mapped. forge_next / forge_result: step 3's record_key output (draft:<thread_ts>)."
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
    "hint": "Slack member ID of the person running the setup, e.g. U038ZCDAY6P. Trigger recipe: map the message user."
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
    "hint": "Slack channel ID where recipeconfig was typed, e.g. C0A3PGRT3EX. Trigger recipe: map the message channel."
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
    "hint": "ts of the recipeconfig message (trigger recipe) or of the clicked message (click recipe, if payload_json is not mapped). Not needed in the Integra loop: the building card is remembered."
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
    "hint": "Thread the setup runs in. Trigger recipe: map thread_ts if recipeconfig was typed in a thread, otherwise leave blank. forge_result: the setup thread (the details step's thread)."
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
    "hint": "true = read only: nothing is posted to Slack or written to the table; the blocks come back in blocks_json. Leave blank in production."
  },
  {
    "control_type": "text",
    "label": "banner_url",
    "type": "string",
    "name": "banner_url",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "banner_url"
    },
    "hint": "Optional. Public https URL of the Genie Console banner (1200x240 PNG, under 1 MB), shown at the top of the first setup message. Slack must be able to fetch it without a login; if it can't, the message is posted without the banner. Blank = no banner."
  },
  {
    "control_type": "text",
    "label": "analyst_skill_handle",
    "type": "string",
    "name": "analyst_skill_handle",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "analyst_skill_handle"
    },
    "hint": "Handle (skl-...) of the shared 'Workato · Ask integration analyst' skill. Integra attaches it to every genie it builds, so the genie can hand recipe, job and table questions to the master genie. Same value in every Python step of the function recipe."
  },
  {
    "control_type": "text",
    "label": "kb_doc_detail",
    "type": "string",
    "name": "kb_doc_detail",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "kb_doc_detail"
    },
    "hint": "Optional. The documents people can pick for the knowledge base, as JSON: {\"file_name\": \"Doc A,Doc B\", \"file_id\": \"id1,id2\"}. The names and the IDs are each comma-separated, in the same order, so a name that contains a comma cannot be used (the lists then no longer line up and no documents are offered). Up to 100 are listed. Map an object with .to_json, like payload_json. Needed by the Python step that handles the clicks. Blank = no document picker."
  },
  {
    "control_type": "text",
    "label": "forge_folder_id",
    "type": "string",
    "name": "forge_folder_id",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_folder_id"
    },
    "hint": "Optional. Folder Integra builds in. Blank = a 'Genie - <name>' folder is created inside the first chosen project."
  },
  {
    "control_type": "text",
    "label": "forge_status",
    "type": "string",
    "name": "forge_status",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_status"
    },
    "hint": "forge_result: Integra's status output (success, partial or failed). failed shows Try again."
  },
  {
    "control_type": "text",
    "label": "forge_genie_id",
    "type": "string",
    "name": "forge_genie_id",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_genie_id"
    },
    "hint": "forge_result: Integra's genie_id output (gin-...)."
  },
  {
    "control_type": "text",
    "label": "forge_skills_json",
    "type": "string",
    "name": "forge_skills_json",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_skills_json"
    },
    "hint": "forge_result: Integra's skills_json output, a JSON list of {handle, name, recipe_id, ...}."
  },
  {
    "control_type": "text",
    "label": "forge_summary",
    "type": "string",
    "name": "forge_summary",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_summary"
    },
    "hint": "forge_result: Integra's summary output. Shown in Slack."
  },
  {
    "control_type": "text",
    "label": "forge_error",
    "type": "string",
    "name": "forge_error",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_error"
    },
    "hint": "forge_result: Integra's error output, or the catch block's error message. Shows Try again."
  },
  {
    "control_type": "text",
    "label": "forge_plan_json",
    "type": "string",
    "name": "forge_plan_json",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_plan_json"
    },
    "hint": "forge_result: Integra's plan_json output (only filled after the plan job)."
  },
  {
    "control_type": "text",
    "label": "forge_project_knowledge",
    "type": "string",
    "name": "forge_project_knowledge",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "forge_project_knowledge"
    },
    "hint": "forge_result: Integra's project_knowledge output (only filled after the plan job)."
  },
  {
    "control_type": "text",
    "label": "kb_attach_status",
    "type": "string",
    "name": "kb_attach_status",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "kb_attach_status"
    },
    "hint": "Only when action = kb_attach_result. success once the recipe attached selected_kb_file to kb_id; anything else counts as failed. The outcome is shown on the knowledge base line in Slack, then Integra starts either way."
  },
  {
    "control_type": "text",
    "label": "kb_attach_error",
    "type": "string",
    "name": "kb_attach_error",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "kb_attach_error"
    },
    "hint": "Only when action = kb_attach_result. Why attaching failed, shown in Slack. Any text here counts as a failure, whatever kb_attach_status says."
  },
  {
    "control_type": "text",
    "label": "authorized_users",
    "type": "string",
    "name": "authorized_users",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "authorized_users"
    },
    "hint": "Optional. Email addresses of the people allowed to create genies, comma-separated, e.g. a@company.com, b@company.com. Only they can type recipeconfig or click Create a new genie; anyone else gets a polite message that only they can see, and nothing is saved. Matched against the Slack profile email (the Slack app needs the users:read.email scope), ignoring case. Blank = anyone can. If the email can't be read, or the list holds no address, nobody is let through. Needed by the Python step that handles the trigger and the clicks."
  },
  {
    "control_type": "text",
    "label": "persona_picker",
    "type": "string",
    "name": "persona_picker",
    "optional": true,
    "extends_schema": false,
    "details": {
      "real_name": "persona_picker"
    },
    "hint": "Optional. How the first step offers the personas: list (a dropdown, the default) or carousel (one card per persona). If Slack refuses the cards, the dropdown is posted instead."
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
    "hint": "Optional. How the confirm summary looks: new (a table for each kind of thing, the default), single (one combined table) or old (text lists). If Slack refuses a look, the next plainer one is posted."
  }
]
