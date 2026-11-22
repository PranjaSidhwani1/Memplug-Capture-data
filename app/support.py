"""Support requests from the console. Requests from Enterprise accounts are marked priority."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.access import account_doc
from app.config import mail_configured, support_email
from app.plans import PLANS, effective_plan

log = logging.getLogger("memplug.support")

_HOURLY_LIMIT = 5
_ready = False


class SupportError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _requests():
    global _ready
    from app.store import database

    col = database()["support_requests"]
    if not _ready:
        col.create_index([("user_id", 1), ("created_at", -1)])
        _ready = True
    return col


def submit_request(user_id: str, subject: str, body: str) -> dict:
    doc = account_doc(user_id)
    if not doc:
        raise SupportError(401, "Sign in again.")
    subject = " ".join(subject.split())[:120]
    body = body.strip()[:5000]
    if not subject or not body:
        raise SupportError(400, "Add a subject and a message.")
    col = _requests()
    now = datetime.now(timezone.utc)
    recent = col.count_documents({"user_id": user_id, "created_at": {"$gte": now - timedelta(hours=1)}})
    if recent >= _HOURLY_LIMIT:
        raise SupportError(429, f"That is {_HOURLY_LIMIT} requests in the last hour. Try again later.")
    plan = effective_plan(doc, now)
    record = {
        "user_id": user_id,
        "email": doc.get("email") or "",
        "plan": plan,
        "priority": bool(PLANS[plan]["priority_support"]),
        "subject": subject,
        "body": body,
        "status": "open",
        "mailed": False,
        "created_at": now,
    }
    request_id = str(col.insert_one(record).inserted_id)
    emailed = mail_configured()
    if emailed:
        threading.Thread(target=_send, args=(request_id, record), daemon=True).start()
    else:
        log.warning("support request saved without email id=%s", request_id)
    return {"id": request_id, "priority": record["priority"], "emailed": emailed}


def _send(request_id: str, record: dict) -> None:
    from app.mail import MailError, send_mail

    tag = "[Priority] " if record["priority"] else ""
    body = (
        f"From: {record['email']}\n"
        f"Plan: {PLANS[record['plan']]['name']}\n"
        f"Request: {request_id}\n\n"
        f"{record['body']}\n"
    )
    try:
        send_mail(
            support_email(),
            f"{tag}Memplug support: {record['subject']}",
            body,
            reply_to=record["email"] or None,
        )
    except MailError:
        log.warning("support request was not emailed id=%s", request_id)
        return
    _requests().update_one({"_id": ObjectId(request_id)}, {"$set": {"mailed": True}})
