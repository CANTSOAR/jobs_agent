# Jobs Agent

Jobs Agent is a private job-search pipeline that discovers internship postings,
matches them against an explicit candidate profile, tracks every application, and
can inspect or fill application forms behind strict submission guards.

The primary discovery source is the structured
[SimplifyJobs Summer 2027 feed](https://github.com/SimplifyJobs/Summer2027-Internships).
It contains stable listing IDs and application URLs, so it is more reliable than
scraping links out of the SWEList digest. An optional Gmail connector records the
digest as a trigger and reconciliation signal.

## End-to-end flow

```text
Simplify feed + optional Gmail
            |
            v
  normalize + deduplicate ----> jobs + source history
            |
            v
 preference gates + bounded DeepSeek scoring
            |
            v
 matches + notification digest + guarded application queue
            |
            v
 private Playwright runner ----> review / submitted / interview / outcome
```

- `agent/ingestion`: conditional feed fetches, normalization, and idempotent
  database RPCs.
- `agent/inbox`: read-only Gmail polling and SWEList parsing. Raw message bodies
  are off by default.
- `agent/evaluator`: explicit preference filters, bounded LLM scoring, and policy-
  controlled queueing.
- `agent/application_runner`: a separate local browser with network and final-
  submit guards.
- `web`: a static Next.js dashboard for profile data, preferences, policies,
  queue review, and lifecycle tracking.
- `supabase`: the source of truth, RLS policies, event history, leases, and
  versioned migrations.

The personal-information repository is a read-only input, not the home of this
system. Only job-specific data explicitly saved in the protected Supabase profile
is used at runtime. The worker never copies unrelated personal notes into prompts,
logs, fixtures, or the database.

## Setup

### Database

For a new Supabase project, run `supabase/schema.sql` once. For an existing project,
run the ordered files in `supabase/migrations/`; never run `supabase/delete.sql`
against a database with data you care about.

The Python worker needs the Supabase `service_role` key. The browser dashboard uses
only the public anon key and is constrained by RLS.

### Python worker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r agent/requirements-dev.txt
python -m playwright install chromium
cp .env.example .env
```

Fill the required values in `.env`, then run a feed-only idempotency check:

```bash
PYTHONPATH=agent python -m ingestion.cli
PYTHONPATH=agent python -m ingestion.cli
```

The second call should normally report `not_modified`. Run the frequent discovery
path (feed, optional Gmail, matching, queueing, and notifications) with:

```bash
PYTHONPATH=agent python agent/discovery.py
```

The daily full worker additionally checks configured company and LinkedIn pages:

```bash
PYTHONPATH=agent python agent/main.py
```

### Dashboard

```bash
cd web
npm ci
cp .env.example .env.local
npm run dev
```

The production build is a static export for GitHub Pages. Profile and application
writes happen directly through Supabase RLS and narrow authenticated RPCs.

### Optional Gmail ingestion

Create Google OAuth credentials with the read-only Gmail scope and provide a refresh
token through `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`.
The default query reads only recent mail from `noreply@swelist.com`. Set
`GMAIL_OWNER_USER_ID` when the database contains more than one profile.

Gmail is not required for discovery: the structured feed is polled every 15 minutes
by `.github/workflows/discovery.yml`. Gmail OAuth failures do not stop that feed.
Notification digests only include matches created within
`NOTIFICATION_LOOKBACK_DAYS` (two days by default), so enabling the workflow does
not send a historical backlog. They are also capped at `NOTIFICATION_MAX_MATCHES`
and spaced by `NOTIFICATION_MIN_INTERVAL_MINUTES` (50 matches and four hours by
default) to prevent a newly enabled matcher from flooding the inbox.

## Application runner

Start with inspection or autofill/review mode from the dashboard. The resume remains
local and must be passed as a path:

```bash
cd agent
python -m application_runner.cli \
  --watch \
  --headless \
  --resume "/absolute/private/path/resume.pdf" \
  --browser-profile-dir "/absolute/private/path/jobs-agent-browser" \
  --artifact-dir "/absolute/private/path/jobs-agent-artifacts"
```

The runner installs its mutation firewall before the first navigation and blocks
POST/PUT/PATCH/DELETE during inspection and autofill. Unknown, sensitive, consent,
CAPTCHA, authentication, and ambiguous multi-step forms stop for review. A final
click requires all of the following:

- application mode `auto_submit_if_safe`;
- an allowlisted adapter and exact company;
- a trusted ATS submission hostname for that adapter;
- complete explicitly approved answers;
- a positive daily cap of at most 20, still below its configured limit;
- either current per-application fingerprint authorization or explicit automatic
  policy consent;
- the exact local environment gate below.

```bash
APPLICATION_LIVE_SUBMIT_ENABLED=I_UNDERSTAND_THIS_SUBMITS_REAL_APPLICATIONS
```

Do not put that gate in routine CI. A click with an ambiguous result becomes
`submission_unknown` and is never retried automatically.

## Automation

- `discovery.yml`: structured discovery every 15 minutes; no browser install.
- `agent.yml`: daily full scrape/evaluate/notify run.
- `agent-poll.yml`: handles dashboard run requests.
- `deploy.yml`: builds and deploys the static dashboard.
- `test.yml`: Python unit/mock-ATS tests plus frontend lint, types, and build.

Configure the referenced GitHub Actions secrets and public dashboard variables in
the repository settings. The application runner intentionally stays on a private
machine because it needs a local resume, private artifacts, and potentially a
dedicated browser profile.

## Verification

```bash
PYTHONPATH=agent .venv/bin/python -m pytest -q agent/tests
cd web
npm run lint
npx tsc --noEmit
npm run build
```

The mock ATS suite proves that autofill makes zero mutation requests and that the
dual-gated test submission sends exactly one POST. It never targets a real employer.
