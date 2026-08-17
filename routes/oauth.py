import secrets

from flask import Blueprint, redirect, request, session, url_for
from flask_login import login_required

from auth.google_auth import build_flow, save_token

bp = Blueprint("oauth", __name__, url_prefix="/oauth")

ALLOWED_ACCOUNTS = {"yifan", "anthony", "default"}


@bp.route("/<account>/start")
@login_required
def start(account):
    if account not in ALLOWED_ACCOUNTS:
        return f"Unknown account '{account}'", 404

    state = secrets.token_urlsafe(24)
    session[f"oauth_state_{account}"] = state

    flow = build_flow(redirect_uri=url_for("oauth.callback", account=account, _external=True), state=state)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # forces a refresh_token even on re-auth
    )
    return redirect(auth_url)


@bp.route("/<account>/callback")
@login_required
def callback(account):
    if account not in ALLOWED_ACCOUNTS:
        return f"Unknown account '{account}'", 404

    expected_state = session.pop(f"oauth_state_{account}", None)
    if not expected_state or request.args.get("state") != expected_state:
        return "Invalid OAuth state — please retry from the dashboard.", 400

    flow = build_flow(
        redirect_uri=url_for("oauth.callback", account=account, _external=True),
        state=expected_state,
    )
    flow.fetch_token(authorization_response=request.url)
    save_token(account, flow.credentials)

    return redirect(url_for("dashboard.home"))
