# Safe application runner

This package is a separate, local/private Playwright worker for application forms. It
does not reuse the scraper browser and it is not invoked by the scheduled GitHub
Actions workflows.

## Candidate profile contract

`profiles.application_profile` is structured JSON. Missing values are never inferred:

```json
{
  "first_name": "Ada",
  "last_name": "Applicant",
  "preferred_name": "Ada",
  "email": "applicant@example.com",
  "phone": "+1 555 010 0200",
  "address_line_1": "123 Example St",
  "address_line_2": "",
  "city": "Example City",
  "state": "NY",
  "postal_code": "08901",
  "country": "United States",
  "linkedin_url": "https://www.linkedin.com/in/example",
  "github_url": "https://github.com/example",
  "portfolio_url": "https://example.com",
  "school": "Example University",
  "degree": "Bachelor of Science",
  "major": "Computer Science",
  "graduation_month": 5,
  "graduation_year": 2027,
  "work_authorization": "...",
  "requires_sponsorship": "..."
}
```

Work authorization, sponsorship, legal attestations, self-identification fields, and
other sensitive answers must also have an explicit `application_answers` record whose
question wording matches the inspected form before they can be filled.
`approved_for_submission` is a separate opt-in from autofill. The worker rescans the
form after filling; newly revealed conditional questions force a fresh review.

The resume stays local. Set `APPLICATION_RESUME_PATH` or pass `--resume`.

## Run the queue

From `agent/` after installing Chromium:

```bash
pip install -r requirements.txt
playwright install chromium
python -m application_runner.cli \
  --watch \
  --browser-profile-dir /a/private/jobs-agent-browser-profile \
  --artifact-dir /a/private/jobs-agent-artifacts \
  --resume /a/private/resume.pdf
```

The default browser is visible. Both the profile and artifact directories must be
private paths outside this repository. Do not point the worker at a normal personal
Chrome profile.

Omit `--watch` to process at most one queue item. In watch mode the worker polls
every 60 seconds while idle; use `--poll-seconds` to change that interval.

Modes are read from the claimed application:

- `track_only`: browser work is skipped.
- `inspect`: reads the form without entering data.
- `autofill`: enters approved values with all POST/PUT/PATCH/DELETE requests blocked,
  records a private screenshot, and never submits.
- `auto_submit_if_safe`: can submit only after every fail-closed guard passes.

Live submit additionally requires this exact environment value:

```bash
APPLICATION_LIVE_SUBMIT_ENABLED=I_UNDERSTAND_THIS_SUBMITS_REAL_APPLICATIONS
```

That switch alone is insufficient. The database policy must explicitly authorize
auto-submit, allowlist the selected adapter, satisfy any company allowlist, set a
positive daily cap no higher than the worker's hard ceiling of 20, use that adapter's
trusted ATS hostname, and contain no
unknown/sensitive review blockers. Alternatively,
a recent application-specific authorization must match the previously inspected form
fingerprint exactly. Any uncertainty after the final click becomes
`submission_unknown` and is never retried automatically.

## Tests

The E2E server binds only to loopback. It proves autofill produces zero POSTs and that
the test-only submit path makes exactly one POST:

```bash
pip install -r requirements-dev.txt
playwright install chromium
python -m pytest -q tests/application_runner
```
