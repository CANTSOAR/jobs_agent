import json

from llm import get_client

INITIAL_EXTRACT_PROMPT = """You are reading a company's careers page for the first time
to build an initial list of currently open job postings.

Company: {name}
Careers page: {url}

Page text:
---
{page_text}
---

List every distinct job posting that appears to be a genuinely open role (ignore nav
links, banners, footers, and unrelated content).

Respond with ONLY valid JSON: {{"jobs": [{{"title": "...", "url": "..." or null, "location": "..." or null}}]}}
If there are no job postings, return {{"jobs": []}}.
"""

DIFF_EXTRACT_PROMPT = """You are comparing two snapshots of a company's careers page text to
find newly posted job openings.

Company: {name}
Careers page: {url}

Lines that are new in today's snapshot (not present in yesterday's):
---
{added_lines}
---

From these new lines, list any job postings that appear to be genuinely new openings
(ignore unrelated new lines, e.g. banners, cookie notices, unrelated news).

Respond with ONLY valid JSON: {{"jobs": [{{"title": "...", "url": "..." or null, "location": "..." or null}}]}}
If there are no new job postings, return {{"jobs": []}}.
"""


def _extract(prompt: str) -> list:
    response = get_client().chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    jobs = json.loads(response.choices[0].message.content).get("jobs", [])
    return [job for job in jobs if job.get("title")]


def extract_initial_jobs(name: str, url: str, page_text: str) -> list:
    return _extract(INITIAL_EXTRACT_PROMPT.format(name=name, url=url, page_text=page_text[:12000]))


def extract_new_jobs_from_diff(name: str, url: str, added_lines: str) -> list:
    return _extract(DIFF_EXTRACT_PROMPT.format(name=name, url=url, added_lines=added_lines))
