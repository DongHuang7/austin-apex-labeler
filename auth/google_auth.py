"""
Web-redirect Google OAuth, replacing the old InstalledAppFlow/local-file
approach (auth/google_auth.py at the project root — kept there for reference,
superseded here). Heroku dynos have an ephemeral filesystem and can't open a
browser to localhost, so tokens are stored encrypted in Postgres
(models.GoogleToken) instead of token_<account>.json files, and the OAuth
flow uses an explicit HTTPS redirect_uri via oauth_routes.py.
"""
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from crypto_utils import decrypt, encrypt
from models import GoogleToken, db

SCOPES = [
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/contacts.other.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# NOTE: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET must belong to a "Web
# application" OAuth client in Google Cloud Console with this app's
# /oauth/<account>/callback URL registered as an authorized redirect URI.
# The client_id in the root credentials.json is a "Desktop app" client type,
# which Google restricts to loopback/OOB redirects and will NOT accept a
# custom HTTPS redirect_uri (redirect_uri_mismatch). Confirm/replace the
# GOOGLE_CLIENT_ID/SECRET config vars with a Web-application client's
# credentials before OAuth will work end-to-end on Heroku.
CLIENT_CONFIG = {
    "web": {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def build_flow(redirect_uri: str, state: str = None, code_verifier: str = None) -> Flow:
    # Flow auto-generates a PKCE code_verifier per instance. /start and
    # /callback build two separate Flow objects (different requests), so
    # without passing the same code_verifier back in on /callback, Google
    # rejects the token exchange with "Missing code verifier" — the
    # verifier has to be threaded through the session same as state.
    return Flow.from_client_config(
        CLIENT_CONFIG, scopes=SCOPES, redirect_uri=redirect_uri, state=state,
        code_verifier=code_verifier,
    )


def save_token(account: str, creds: Credentials):
    row = GoogleToken.query.filter_by(account=account).first()
    is_new = row is None
    if is_new:
        row = GoogleToken(account=account)

    if creds.refresh_token:
        row.refresh_token_encrypted = encrypt(creds.refresh_token)
    elif is_new:
        # Google didn't return a refresh_token on a brand-new connection —
        # can happen if a prior grant for this app+account wasn't fully
        # revoked. refresh_token_encrypted is NOT NULL, so inserting here
        # would crash; surface a clear, actionable error instead.
        raise RuntimeError(
            f"Google didn't return a refresh token for '{account}'. "
            f"Revoke this app's access at https://myaccount.google.com/permissions "
            f"and try /oauth/{account}/start again."
        )
    # else: re-authorizing an already-connected account without a fresh
    # refresh_token in the response — keep the one already on file.

    row.access_token_encrypted = encrypt(creds.token) if creds.token else None
    row.token_expiry = creds.expiry
    row.scopes = list(creds.scopes) if creds.scopes else SCOPES
    if is_new:
        db.session.add(row)
    db.session.commit()


def get_credentials(account: str) -> Credentials:
    """Load credentials for an account from Postgres, refreshing if expired.
    Raises LookupError if the account has never completed the OAuth flow —
    the caller should redirect to /oauth/<account>/start."""
    row = GoogleToken.query.filter_by(account=account).first()
    if row is None:
        raise LookupError(
            f"No stored Google token for account '{account}'. "
            f"Visit /oauth/{account}/start to connect it."
        )

    creds = Credentials(
        token=decrypt(row.access_token_encrypted) if row.access_token_encrypted else None,
        refresh_token=decrypt(row.refresh_token_encrypted),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        scopes=row.scopes or SCOPES,
    )

    if not creds.valid:
        creds.refresh(Request())
        save_token(account, creds)

    return creds
