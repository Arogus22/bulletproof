# Framework Init (Bulletproof)

Adopts the current project into the plugin: detects the capabilities and proposes the
layers.

Steps:

1. Run the adoption script (if $ARGUMENTS carries stacks, pass each one with `--stack`):

   Run the platform entry point supplied by the command or skill, with `framework-init .`.

2. Show the user, in plain language, what the script reported: the **proposed layers**,
   the **detected capabilities** (the signals), and the **status**.

3. If the script printed "CONFIRM" questions (what it cannot see from the repository),
   **put those questions to the user** and wait for the answer. Examples: "does this
   project publish to production?", "does it write to a production database?".

4. If the user confirms a capability that detection did not see, update the
   `.framework-version`: add **layer 3** to `layers` and the matching block under
   `config`. Ask which branch deploys to production and which command publishes by hand,
   and write exactly these shapes (the guards read these keys):

   ```json
   "deploy": { "protected_branch": "main", "deploy_cmds": ["wrangler deploy"] }
   "prod_db": { "kind": "d1", "guard_remote_only": true }
   ```

   The database guard only knows Cloudflare D1 today: say so if the project uses another
   database, and add `prod_db` only for D1. If the user confirms nothing new, leave the
   file as the script wrote it.

5. Explain the next step in 1-2 sentences: in `bootstrapping`, run `/bulletproof:testar`;
   on the first green the project becomes `active` and the Exit Lock arms itself. The
   production guards (layer 3), if switched on, start asking for your approval before
   publishing or writing to the production database.

Rules:
- Do NOT modify application code.
- If the script refuses (a legacy `.framework-version` already exists, without the plugin
  marker), do NOT force it: report what the script said and stop.
