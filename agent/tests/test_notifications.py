from datetime import datetime, timezone
from types import SimpleNamespace

from notifications import notifier


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, database, table):
        self.database = database
        self.table = table
        self.operation = "select"
        self.updated = None
        self.ids = []
        self.filters = []

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def order(self, *args, **kwargs):
        return self

    def single(self):
        return self

    def update(self, payload):
        self.operation = "update"
        self.updated = payload
        return self

    def in_(self, column, values):
        self.ids = list(values)
        return self

    def execute(self):
        if self.operation == "update":
            self.database.updated_ids.extend(self.ids)
            return _Result([])
        return _Result(self.database.rows[self.table])


class _Supabase:
    def __init__(self):
        self.updated_ids = []
        self.queries = {}
        self.rows = {
            "user_job_matches": [
                {
                    "id": "match-1",
                    "user_id": "user-1",
                    "score": 91,
                    "reasoning": "Strong fit.",
                    "jobs": {
                        "title": "Software Engineering Intern",
                        "url": "https://example.test/job",
                        "location": "New York",
                        "companies": {"name": "Example"},
                    },
                }
            ],
            "profiles": {
                "email_notifications_enabled": True,
                "job_preferences": {"min_match_score": 80},
            },
        }
        user = SimpleNamespace(email="ada@example.test")
        self.auth = SimpleNamespace(
            admin=SimpleNamespace(get_user_by_id=lambda user_id: SimpleNamespace(user=user))
        )

    def table(self, name):
        query = _Query(self, name)
        self.queries[name] = query
        return query


def test_missing_smtp_does_not_mark_matches_notified(monkeypatch):
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"):
        monkeypatch.delenv(name, raising=False)
    database = _Supabase()

    notifier.send_alerts(database)

    assert database.updated_ids == []
    assert database.queries["user_job_matches"].filters[0][1] == "created_at"


def test_successful_digest_marks_only_delivered_matches(monkeypatch):
    database = _Supabase()
    delivered = []
    monkeypatch.setattr(
        notifier,
        "_send_email",
        lambda email, subject, body: delivered.append((email, subject, body)) or True,
    )

    notifier.send_alerts(database)

    assert database.updated_ids == ["match-1"]
    assert delivered[0][0] == "ada@example.test"
    assert "1 new job match" in delivered[0][1]


def test_recent_digest_throttles_additional_email(monkeypatch):
    database = _Supabase()
    database.rows["profiles"]["last_job_digest_at"] = datetime.now(timezone.utc).isoformat()
    delivered = []
    monkeypatch.setattr(
        notifier,
        "_send_email",
        lambda *args: delivered.append(args) or True,
    )

    notifier.send_alerts(database)

    assert delivered == []
    assert database.updated_ids == []
