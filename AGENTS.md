# Jobs Agent Repository Instructions

This repository owns the job-search product: source ingestion, normalization,
matching, application preparation, application execution, and lifecycle tracking.
Operational job and application state belongs in its database, not in a personal
notes repository.

## Personal context

The repository owner's private personal-context repository is a read-only input
for work that benefits from knowledge of his background or goals. Resolve it in
this order:

1. `$PERSONAL_CONTEXT_REPO`, when set.
2. The sibling directory `../aryanmalik`, when present.

When available, begin with `agents/README.md` there and follow its loading order.
Current instructions from the owner override archived context. Do not copy `dump.md`,
`gemini_dump.md`, relationship, health, financial, or other unrelated personal
material into this repository, prompts, logs, fixtures, or the deployed database.

Runtime workers must use only the explicit job-specific projection stored in the
user's protected profile: resume, experience, job preferences, application
answers, and eligibility constraints. They must never require the whole personal
repository to be mounted or cloned in CI.

## Application safety

- Discovery and tracking may run unattended.
- Browser application work runs only in the dedicated application runner, never
  through the scraping browser singleton.
- Unknown, sensitive, attestation, CAPTCHA, authentication, or consent fields
  require review unless the owner explicitly saved and authorized the exact answer.
- A live final submission requires the repository's explicit submission guards.
  Tests and ordinary development must never submit a real application.
- Never infer work authorization, sponsorship, demographic, disability, veteran,
  compensation, clearance, or signature answers from prose or personal context.

## Engineering workflow

- Preserve existing user and application data. Use additive, versioned database
  migrations; do not run `supabase/delete.sql` against a real project.
- Keep source ingestion idempotent and application submission at-most-once.
- Keep secrets, browser profiles, resumes, screenshots, and traces out of Git.
- Read `web/AGENTS.md` and the relevant local Next.js documentation before editing
  the web application.
