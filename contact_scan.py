"""
Find new Gmail senders not already in Google Contacts and categorize them
with Claude. Ported from the root project's run_monitor_new_contacts.py,
writing into the contact_reviews table instead of pending_contacts.json so
nothing is silently dropped and Yifan/Anthony review everything from the
dashboard instead of a CLI + JSON file.

Called both by the dashboard's manual "Check now" button (routes/contacts.py)
and by the Heroku Scheduler job (scripts/scan_new_contacts.py).
"""
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from auth.google_auth import get_credentials
from models import ContactReview, db
from scan_helpers import categorize_batch_with_claude

ACCOUNTS = ["yifan", "anthony"]
DAYS_BACK = 7  # how far back to look if this account has never been scanned


def _get_existing_emails(people_service) -> set:
    emails = set()
    pt = None
    while True:
        r = people_service.people().connections().list(
            resourceName="people/me", pageSize=1000,
            personFields="emailAddresses", pageToken=pt,
        ).execute()
        for p in r.get("connections", []):
            for ea in p.get("emailAddresses", []):
                emails.add(ea.get("value", "").lower())
        pt = r.get("nextPageToken")
        if not pt:
            break
    pt = None
    while True:
        r = people_service.otherContacts().list(
            pageSize=1000, readMask="emailAddresses", pageToken=pt,
        ).execute()
        for p in r.get("otherContacts", []):
            for ea in p.get("emailAddresses", []):
                emails.add(ea.get("value", "").lower())
        pt = r.get("nextPageToken")
        if not pt:
            break
    return emails


def _fetch_new_senders(gmail_service, since_timestamp: int, existing_emails: set) -> dict:
    query = f"after:{since_timestamp}"
    new_senders = {}

    result = gmail_service.users().messages().list(userId="me", q=query, maxResults=500).execute()
    messages = result.get("messages", [])

    for msg in messages:
        detail = gmail_service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject"],
        ).execute()
        headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
        from_header = headers.get("From", "")
        subject = headers.get("Subject", "")
        snippet = detail.get("snippet", "")

        if "<" in from_header:
            name = from_header.split("<")[0].strip().strip('"')
            email = from_header.split("<")[1].rstrip(">").strip().lower()
        else:
            name = ""
            email = from_header.strip().lower()

        if not email or "@" not in email:
            continue
        if email in existing_emails:
            continue
        if any(x in email for x in ["noreply", "no-reply", "donotreply", "notifications@", "mailer-daemon"]):
            continue

        if email not in new_senders:
            new_senders[email] = {"name": name, "email": email, "subjects": [], "snippet": snippet}
        if subject and len(new_senders[email]["subjects"]) < 3:
            new_senders[email]["subjects"].append(subject)

    return new_senders


def scan_account(account: str) -> int:
    """Scan one account for new senders, categorize, and upsert into
    contact_reviews. Returns the number of new/updated pending rows."""
    creds = get_credentials(account)
    gmail_svc = build("gmail", "v1", credentials=creds)
    people_svc = build("people", "v1", credentials=creds)

    existing = _get_existing_emails(people_svc)
    already_pending = {
        r.email for r in ContactReview.query.filter_by(account=account).all()
    }
    existing.update(already_pending)

    last_scan = (
        db.session.query(db.func.max(ContactReview.detected_at))
        .filter_by(account=account)
        .scalar()
    )
    since_dt = last_scan or (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK))
    since_ts = int(since_dt.timestamp())

    new_senders = _fetch_new_senders(gmail_svc, since_ts, existing)
    if not new_senders:
        return 0

    contacts_list = list(new_senders.values())
    for i in range(0, len(contacts_list), 10):
        batch = contacts_list[i:i + 10]
        contact_list_str = "\n\n".join([
            f"Contact {j + 1}:\n  Name: {c['name']}\n  Email: {c['email']}\n"
            f"  Recent subjects: {'; '.join(c['subjects']) or 'none'}\n"
            f"  Snippet: {c['snippet'][:200]}"
            for j, c in enumerate(batch)
        ])
        categorize_batch_with_claude(batch, contact_list_str)

    for c in contacts_list:
        row = ContactReview(
            account=account,
            email=c["email"],
            name=c["name"],
            subjects=c["subjects"],
            snippet=c["snippet"],
            suggested_category=c.get("category", "Other"),
            suggested_reason=c.get("reason", ""),
            status="pending",
        )
        db.session.add(row)
    db.session.commit()

    return len(contacts_list)


def scan_all_accounts() -> dict:
    """Returns {account: {"count": int, "error": str|None}}. Each account is
    scanned independently — one account failing (e.g. not yet connected via
    /oauth/<account>/start) must not stop the others from being scanned."""
    results = {}
    for account in ACCOUNTS:
        try:
            results[account] = {"count": scan_account(account), "error": None}
        except Exception as e:
            results[account] = {"count": 0, "error": str(e)}
    return results
