"""
Shared SocialAccount read/write, same pattern as auth/google_auth.py's
save_token/get_credentials — tokens live encrypted in Postgres, never on
disk, since Heroku dynos are ephemeral.
"""
from datetime import datetime, timezone

from crypto_utils import decrypt, encrypt
from models import SocialAccount, db


def save_account_token(
    platform: str,
    account_owner: str,
    access_token: str,
    external_id: str = None,
    display_name: str = None,
    refresh_token: str = None,
    expires_at: datetime = None,
):
    row = SocialAccount.query.filter_by(platform=platform, account_owner=account_owner).first()
    if row is None:
        row = SocialAccount(platform=platform, account_owner=account_owner)
        db.session.add(row)

    row.access_token_encrypted = encrypt(access_token)
    if refresh_token:
        row.refresh_token_encrypted = encrypt(refresh_token)
    if external_id:
        row.external_id = external_id
    if display_name:
        row.display_name = display_name
    row.token_expires_at = expires_at
    db.session.commit()
    return row


def get_access_token(platform: str, account_owner: str) -> str:
    """Raises LookupError if this platform/owner has never completed the
    connect flow, or if the stored token has expired (Meta Page tokens are
    long-lived but not permanent — a refresh job re-runs the connect flow;
    see Phase 2 plan notes on the 60-day Page token refresh job)."""
    row = SocialAccount.query.filter_by(platform=platform, account_owner=account_owner).first()
    if row is None or not row.access_token_encrypted:
        raise LookupError(
            f"No connected {platform} account for '{account_owner}'. "
            f"Visit /social/accounts to connect it."
        )
    if row.token_expires_at and row.token_expires_at < datetime.now(timezone.utc):
        raise LookupError(
            f"The {platform} connection for '{account_owner}' has expired. "
            f"Visit /social/accounts to reconnect it."
        )
    return decrypt(row.access_token_encrypted)
