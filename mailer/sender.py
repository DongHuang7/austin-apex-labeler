import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from auth.google_auth import get_credentials

SENT_LOG_FILE = "sent_log.json"


def _load_sent_log() -> dict:
    if os.path.exists(SENT_LOG_FILE):
        with open(SENT_LOG_FILE) as f:
            return json.load(f)
    return {}


def _save_sent_log(log: dict):
    with open(SENT_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def _already_sent(listing_id: str, recipient_email: str) -> bool:
    """Check if this listing was already sent to this recipient."""
    log = _load_sent_log()
    return recipient_email.lower() in log.get(listing_id, [])


def _record_sent(listing_id: str, recipient_email: str):
    """Record that this listing was sent to this recipient."""
    log = _load_sent_log()
    if listing_id not in log:
        log[listing_id] = []
    if recipient_email.lower() not in log[listing_id]:
        log[listing_id].append(recipient_email.lower())
    _save_sent_log(log)


def send_email(to: str, subject: str, html_body: str, sender_name: str = "Austin Apex Real Estate", account: str = "default") -> bool:
    """Send a single HTML email via Gmail API."""
    creds = get_credentials(account)
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{_get_sender_address(service)}>"
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return True


def _get_sender_address(service) -> str:
    """Get the authenticated Gmail address."""
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def send_email_from_account(to: str, subject: str, html_body: str, account: str, sender_name: str = "Austin Apex Real Estate") -> bool:
    """Send email from a specific account."""
    return send_email(to, subject, html_body, sender_name=sender_name, account=account)


def send_campaign(
    listing: dict,
    subject: str,
    html_body: str,
    recipients: list,
    dry_run: bool = True,
):
    """
    Send a listing email campaign to a list of recipients.

    Args:
        listing:    MLS listing dict (used for dedup tracking)
        subject:    Email subject line
        html_body:  HTML email content
        recipients: List of dicts with 'name' and 'email'
        dry_run:    If True, preview only — don't actually send
    """
    listing_id = listing.get("ListingId", "UNKNOWN")
    total = len(recipients)
    sent = 0
    skipped = 0
    failed = 0

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Sending campaign for {listing_id}")
    print(f"Recipients: {total}\n")

    for i, contact in enumerate(recipients, 1):
        email = contact.get("email", "")
        name = contact.get("name", "") or email

        if not email:
            print(f"  [{i}/{total}] ✗ Skipped — no email address")
            skipped += 1
            continue

        if _already_sent(listing_id, email):
            print(f"  [{i}/{total}] ⟳ Skipped {email} — already sent")
            skipped += 1
            continue

        if dry_run:
            print(f"  [{i}/{total}] ✉ [DRY RUN] Would send to {name} <{email}>")
            sent += 1
            continue

        try:
            send_email(to=email, subject=subject, html_body=html_body)
            _record_sent(listing_id, email)
            print(f"  [{i}/{total}] ✓ Sent to {name} <{email}>")
            sent += 1
        except Exception as e:
            print(f"  [{i}/{total}] ✗ Failed {email}: {e}")
            failed += 1

    print(f"\nDone — Sent: {sent} | Skipped: {skipped} | Failed: {failed}")
