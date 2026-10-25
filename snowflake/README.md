# Snowflake reporting copy

A one-way, hourly copy of the program pipeline's tables for analytics
(`docs/program-discovery-pipeline.md`, Section 16). Nothing in the app reads it,
and no user-level data (user IDs, ZIP codes, locations) is ever sent.

## Setup (once)

1. **Make a key pair** for the service user. Run this outside the repo, or in
   `fastapi_backend/secrets/`, which is gitignored:

   ```bash
   openssl genrsa 2048 | openssl pkcs8 -topk8 -v2 aes256 -inform PEM -out rsa_key.p8   # asks for a passphrase
   openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
   ```

2. **A Snowflake admin runs `setup.sql`.** First paste the body of `rsa_key.pub`
   (without the `BEGIN`/`END` lines) into `RSA_PUBLIC_KEY`. Passwords aren't used:
   the user is `TYPE = SERVICE` with key-pair auth.

3. **Add the settings to `fastapi_backend/.env`:**

   ```
   SNOWFLAKE_ENABLED=true
   SNOWFLAKE_ACCOUNT=<orgname>-<accountname>
   SNOWFLAKE_PRIVATE_KEY_PATH=/absolute/path/to/rsa_key.p8
   SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=<the passphrase>
   ```

4. **Check the tables, then run the first sync:**

   ```bash
   cd fastapi_backend
   python -m commands.snowflake_sync --print-ddl   # no connection needed
   python -m commands.snowflake_sync --full
   ```

5. **Create the views** as `PROGRAM_PIPELINE_LOADER`: run `views.sql`.

After that, the worker syncs every `SNOWFLAKE_SYNC_INTERVAL_MINUTES` (default 60).
Each run resumes the warehouse for at least 60 seconds of billing, so the interval
drives the cost.

## Views

| View | What it shows |
|---|---|
| `COVERAGE_SUMMARY` | Jurisdictions by level and coverage status |
| `SERPAPI_USAGE_DAILY` | Searches per day, by trigger |
| `DISCOVERY_YIELD` | Published programs per search, per jurisdiction |
| `REVIEW_BACKLOG` | `needs_review` programs by age |
| `PROGRAMS_BY_CATEGORY` | Programs people can see, by category and level |
| `PROGRAMS_BY_STATE` | State and local programs, and people served, per state |
| `FEDERAL_PROGRAMS_BY_AGENCY` | Federal programs people can see, by agency |
