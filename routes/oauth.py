import secrets

from flask import Blueprint, flash, redirect, request, session, url_for
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
    # code_verifier is only generated inside authorization_url() (it needs
    # to exist before the code_challenge derived from it can be built), so
    # it has to be captured after that call, not right after build_flow().
    session[f"oauth_code_verifier_{account}"] = flow.code_verifier

    return redirect(auth_url)


@bp.route("/<account>/callback")
@login_required
def callback(account):
    if account not in ALLOWED_ACCOUNTS:
        return f"Unknown account '{account}'", 404

    expected_state = session.pop(f"oauth_state_{account}", None)
    if not expected_state or request.args.get("state") != expected_state:
        return "Invalid OAuth state — please retry from the dashboard.", 400

    code_verifier = session.pop(f"oauth_code_verifier_{account}", None)
    flow = build_flow(
        redirect_uri=url_for("oauth.callback", account=account, _external=True),
        state=expected_state,
        code_verifier=code_verifier,
    )
    try:
        flow.fetch_token(authorization_response=request.url)
        save_token(account, flow.credentials)
    except Exception as e:
        flash(f"Couldn't connect the {account} Google account: {e}", "error")
        return redirect(url_for("dashboard.home"))

    flash(f"Connected {account}'s Google account.")
    return redirect(url_for("dashboard.home"))
