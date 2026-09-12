from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator


TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users"


class GmailError(RuntimeError):
    pass


@dataclass(frozen=True)
class GmailCredentials:
    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    thread_id: str | None
    sender: str | None
    recipients: tuple[str, ...]
    subject: str | None
    received_at: str | None
    html: str
    text: str
    label_ids: tuple[str, ...]


def _request_json(request: urllib.request.Request, timeout: int = 30) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise GmailError(f"Gmail request failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise GmailError(f"Gmail request failed: {exc.reason}") from exc


def refresh_access_token(credentials: GmailCredentials) -> str:
    body = urllib.parse.urlencode({
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "refresh_token": credentials.refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    payload = _request_json(urllib.request.Request(
        TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    ))
    token = payload.get("access_token")
    if not token:
        raise GmailError("Google token response did not include an access token")
    return str(token)


def _gmail_get(access_token: str, user_id: str, path: str, **query: Any) -> dict[str, Any]:
    query_string = urllib.parse.urlencode({key: value for key, value in query.items() if value is not None})
    url = f"{GMAIL_API}/{urllib.parse.quote(user_id, safe='')}/{path}"
    if query_string:
        url += f"?{query_string}"
    return _request_json(urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    ))


def list_message_ids(
    access_token: str,
    *,
    user_id: str = "me",
    query: str,
    max_results: int = 50,
) -> Iterator[str]:
    page_token: str | None = None
    remaining = max_results
    while remaining > 0:
        payload = _gmail_get(
            access_token,
            user_id,
            "messages",
            q=query,
            maxResults=min(remaining, 100),
            pageToken=page_token,
        )
        messages = payload.get("messages") or []
        for message in messages:
            message_id = message.get("id")
            if message_id:
                yield str(message_id)
                remaining -= 1
                if remaining == 0:
                    return
        page_token = payload.get("nextPageToken")
        if not page_token:
            return


def _decode_data(value: str | None) -> str:
    if not value:
        return ""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _collect_parts(part: dict[str, Any], html: list[str], text: list[str]) -> None:
    mime_type = str(part.get("mimeType") or "").lower()
    content = _decode_data((part.get("body") or {}).get("data"))
    if content and mime_type == "text/html":
        html.append(content)
    elif content and mime_type == "text/plain":
        text.append(content)
    for child in part.get("parts") or []:
        _collect_parts(child, html, text)


def get_message(access_token: str, message_id: str, *, user_id: str = "me") -> GmailMessage:
    payload = _gmail_get(access_token, user_id, f"messages/{urllib.parse.quote(message_id, safe='')}", format="full")
    mime_payload = payload.get("payload") or {}
    headers = {
        str(item.get("name") or "").casefold(): str(item.get("value") or "")
        for item in mime_payload.get("headers") or []
    }
    html_parts: list[str] = []
    text_parts: list[str] = []
    _collect_parts(mime_payload, html_parts, text_parts)

    received_at = None
    internal_date = payload.get("internalDate")
    if internal_date:
        received_at = datetime.fromtimestamp(int(internal_date) / 1000, timezone.utc).isoformat()

    recipients = tuple(
        value for value in (headers.get("to"), headers.get("cc")) if value
    )
    return GmailMessage(
        message_id=str(payload.get("id") or message_id),
        thread_id=payload.get("threadId"),
        sender=headers.get("from"),
        recipients=recipients,
        subject=headers.get("subject"),
        received_at=received_at,
        html="\n".join(html_parts),
        text="\n".join(text_parts),
        label_ids=tuple(payload.get("labelIds") or []),
    )
