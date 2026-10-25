# Equa: Equality Finances

**HackTX 2026** · [equalityfin.tech](https://equalityfin.tech)

> Have a problem? Use Equa.

## Inspiration
Most fintech for underserved communities assumes the problem is a lack of financial literacy. The research says something different: scarcity eats cognitive bandwidth. When you live paycheck to paycheck, a budgeting app's pie chart doesn't help. It adds a "cognitive tax" and more anxiety.

People in that spot don't need another graph telling them they're broke. They need a guardrail that does the math, finds the help and writes the paperwork. That's what we built Equa to be.

## What it does
Equa connects to a bank account and turns the data into a few clear next steps. It never shows charts of money you don't have.

- **Safe to Spend.** One ring on the Overview shows your checking balance minus every bill due before your next payday (rent, utilities, loan payments).
- **Money check-up.** Equa grades the last 8 weeks of history against the 50/30/20 and 28/36 rules and shows the result as simple pass/fail rings.
- **Relief programs near you.** Equa finds local, state and federal assistance programs for your ZIP code. Gemini then picks up to 5 you may qualify for and gives a one-line reason for each. It can only choose from programs that are really in our database, so it can't make one up.
- **Application tracking.** Each matched program becomes a progress card with a checked Apply link and a "Mark as done" toggle.
- **AI-filled applications.** On a demo relief form, "Have Equa fill it out" fills in every field from your profile and bank data. You review it and submit it yourself.
- **High-APR debt.** Equa finds your most expensive loan and shows what it costs you each month. It also shows how much sooner you'd pay it off if utility assistance freed up that money. With one click, Gemini writes a rate-reduction request to your lender.
- **My Toyota.** This tab is built around the Toyota Financial Services prompt. For the demo auto loan, Equa:
  - writes a temporary-hardship deferral request
  - suggests moving the due date to payday
  - suggests SmartPath if the car payment is over about 10% of income

  Each card links to TFS's real deferral, due-date and phone resources.
- **Plan.** An ordered to-do list built from your real numbers: free up money first, then lower the cost of debt, then apply for the rest of your matches.
- **Equa chat.** A friendly assistant that answers using your actual bills, loans and check-up results.

## How we built it
- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui and GSAP animations. Mobile first. Server actions call a typed client generated from the backend's OpenAPI schema.
- **Backend:** Python 3.14 + FastAPI, async SQLAlchemy on Postgres, and fastapi-users for auth.
- **Capital One Nessie API:** Our banking backend. "Connect to bank" creates a Nessie customer and fills it with 8 weeks of realistic history: biweekly pay, rent and utility bills, a Toyota auto loan and everyday purchases. Safe to Spend, the check-up, APR impact and chat all read from Nessie, with retries for timeouts, 429s and 5xx errors.
- **Program discovery pipeline:** A background worker that:
  - loads federal programs from GSA's public Assistance Listings and resolves ZIP codes with Census geography data
  - uses **SerpApi** to search for local programs and fetches the pages with an SSRF-safe, polite fetcher
  - has **Gemini** turn each page into structured program records, which are validated and upserted
  - manages its job queue with claims, heartbeats, retries and a SerpApi budget guard
- **Google Gemini:** Our AI layer. It handles program matching (a forced tool call that can only return known program IDs), the lender and deferral letters, application autofill and chat.
- **Snowflake:** An hourly, one-way analytics copy of Postgres, using key-pair auth, staged loads and deduplicating MERGEs. Views on top of it report utility burden and program coverage in aggregate. No user-level data leaves Postgres.
- **Deploy:** The backend runs in Docker on Vultr with Postgres and Caddy (HTTPS at api.equalityfin.tech). The frontend runs on Vercel.
- **Tooling:** We built it with Claude Code during the 24-hour sprint.

## Challenges we ran into
- **Getting the toolchain working.** Python 3.14 and Node versions broke dependencies until we upgraded asyncpg, pydantic, pytest-asyncio and fastapi-users. Vercel also rejected Node 26, so we pinned Node 24 everywhere.
- **Nessie loans have no interest rate field.** We estimate each loan's APR from its credit score and loan type, using published averages.
- **Stopping the AI from making things up.** An LLM will happily invent a grant. We limited matching to known program IDs, dropped any unknown IDs it returned, and checked every application link.
- **Scraping the web politely and safely.** We had to deal with SSRF protection, rate limits and the SerpApi budget, while making sure failed jobs retry instead of disappearing.
- **Tone.** AI sounds clinical when it talks about money. We tuned the prompts so Equa sounds warm and never shames anyone.

## Accomplishments that we're proud of
- An end-to-end flow: connect a bank, see Safe to Spend, get matched to real programs, and have Equa write the letter or fill in the form.
- A real discovery pipeline for programs that pulls actual local, state and federal programs by ZIP code, not a hard-coded list.
- Three sponsor integrations (Capital One Nessie, Snowflake and the Toyota Financial Services prompt) that work together as one product.
- A UI that gives clear next steps instead of dashboards full of numbers.

## What we learned
- How to make LLM output safe enough for people in financial distress, using constrained tool calls, validation and an "unknown means null" rule.
- How to separate the operational database from the analytics warehouse, so Snowflake reporting can never break the app.
- How to turn research on scarcity and compounding APRs into product rules: one number, one next step, no shame.

## What's next for Equa
- Use real bank connections through Plaid instead of Nessie.
- Submit applications directly where programs allow it, and remind users about renewals.
- Turn the Toyota retention flow into a platform that any lender or utility can use to offer hardship options before a customer defaults.

## Run it locally
You need Python 3.14, Node 24 and Docker. See [docs/get-started.md](docs/get-started.md) for the full steps. In short:

```bash
docker compose up -d db db_test
cd fastapi_backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/alembic upgrade head
make start-backend   # API keys go in fastapi_backend/.env
make start-frontend
```

Built on the [Next.js FastAPI Template](https://github.com/vintasoftware/nextjs-fastapi-template) by Vinta Software.
