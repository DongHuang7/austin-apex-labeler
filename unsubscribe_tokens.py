"""
Signed, non-expiring per-email tokens for one-click unsubscribe links —
built with itsdangerous (already a Flask/Werkzeug dependency, no new
package needed) so a token can't be forged or reused to unsubscribe a
different address. Deliberately non-expiring: an unsubscribe link found in
an old email years later must still work.
"""
from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="unsubscribe")


def make_token(email: str) -> str:
    return _serializer().dumps(email.strip().lower())


def verify_token(token: str):
    """Returns the lowercased email the token was issued for, or None if
    the token is invalid/tampered with."""
    try:
        return _serializer().loads(token)
    except BadSignature:
        return None


def unsubscribe_url(email: str) -> str:
    """Builds the full unsubscribe URL for an email. Deliberately doesn't
    use url_for() — building ANY URL through Flask (relative or absolute)
    requires either an active HTTP request or a configured SERVER_NAME,
    neither of which exist when this runs from the standalone scheduled-
    send scripts (confirmed: even a plain, non-external url_for() raises
    "Unable to build URLs outside an active request" there). The route
    path is fixed (see routes/unsubscribe.py's bp.route), so it's built
    directly against APP_BASE_URL instead."""
    return f"{current_app.config['APP_BASE_URL'].rstrip('/')}/unsubscribe/{make_token(email)}"
