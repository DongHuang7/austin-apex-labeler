import secrets
from datetime import datetime, timezone

import requests
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from caption_generator import generate_caption
from models import Listing, SocialAccount, SocialPost, db
from social import linkedin_client, meta_client
from social.token_store import get_access_token, save_account_token

bp = Blueprint("social", __name__, url_prefix="/social")

PLATFORMS = ["facebook_page", "instagram_business", "linkedin_member"]
PLATFORM_LABELS = {
    "facebook_page": "Facebook",
    "instagram_business": "Instagram",
    "linkedin_member": "LinkedIn",
}
OWNERS = ["yifan", "anthony"]


@bp.route("/")
@login_required
def list_posts():
    posts = SocialPost.query.order_by(SocialPost.created_at.desc()).limit(100).all()
    return render_template("social_list.html", posts=posts, platform_labels=PLATFORM_LABELS)


@bp.route("/new/<listing_id>")
@login_required
def new(listing_id):
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()
    return render_template(
        "social_new.html", listing=listing, platforms=PLATFORMS, platform_labels=PLATFORM_LABELS,
    )


@bp.route("/generate/<listing_id>", methods=["POST"])
@login_required
def generate(listing_id):
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()
    platform = request.form.get("platform")
    account_owner = request.form.get("account_owner")
    if platform not in PLATFORMS:
        flash(f"Unknown platform '{platform}'.", "error")
        return redirect(url_for("social.new", listing_id=listing_id))
    if account_owner not in OWNERS:
        flash(f"Unknown account owner '{account_owner}'.", "error")
        return redirect(url_for("social.new", listing_id=listing_id))

    try:
        draft = generate_caption(listing.raw_json, platform)
    except Exception as e:
        flash(f"Could not generate a caption: {e}", "error")
        return redirect(url_for("social.new", listing_id=listing_id))

    post = SocialPost(
        listing_id=listing.id,
        platform=platform,
        account_owner=account_owner,
        draft_caption=draft,
        final_caption=draft,
        photo_urls=listing.photo_urls,
        status="draft",
        created_by=current_user.id,
    )
    db.session.add(post)
    db.session.commit()

    return redirect(url_for("social.edit", post_id=post.id))


@bp.route("/<int:post_id>/edit", methods=["GET", "POST"])
@login_required
def edit(post_id):
    post = db.get_or_404(SocialPost, post_id)

    if request.method == "POST":
        post.final_caption = request.form.get("caption", post.final_caption)
        post.photo_urls = request.form.getlist("photo_url") or post.photo_urls
        scheduled_time = request.form.get("scheduled_time")
        if scheduled_time:
            post.scheduled_time = datetime.fromisoformat(scheduled_time).replace(tzinfo=timezone.utc)
        db.session.commit()
        flash("Draft saved.")
        return redirect(url_for("social.edit", post_id=post.id))

    return render_template(
        "social_edit.html", post=post, platform_labels=PLATFORM_LABELS, owners=OWNERS,
    )


@bp.route("/<int:post_id>/approve", methods=["POST"])
@login_required
def approve(post_id):
    post = db.get_or_404(SocialPost, post_id)
    post.approved_by = current_user.id
    post.status = "scheduled" if post.scheduled_time else "approved"
    db.session.commit()
    flash("Approved." + (" Will publish at the scheduled time." if post.scheduled_time else ""))
    return redirect(url_for("social.list_posts"))


@bp.route("/<int:post_id>/publish_now", methods=["POST"])
@login_required
def publish_now(post_id):
    post = db.get_or_404(SocialPost, post_id)
    account_owner = request.form.get("account_owner") or post.account_owner

    try:
        _publish(post, account_owner)
        flash("Published.")
    except Exception as e:
        post.status = "failed"
        post.error = str(e)
        db.session.commit()
        flash(f"Publish failed: {e}", "error")

    return redirect(url_for("social.list_posts"))


def _publish(post: SocialPost, account_owner: str):
    """Shared by the manual publish_now button and
    scripts/publish_scheduled_posts.py's scheduled-post sweep."""
    image_url = (post.photo_urls or [None])[0]

    if post.platform == "facebook_page":
        token = get_access_token("facebook_page", account_owner)
        account = SocialAccount.query.filter_by(platform="facebook_page", account_owner=account_owner).first()
        external_id = meta_client.publish_to_facebook_page(account.external_id, token, post.final_caption, image_url)
    elif post.platform == "instagram_business":
        token = get_access_token("instagram_business", account_owner)
        account = SocialAccount.query.filter_by(platform="instagram_business", account_owner=account_owner).first()
        if not image_url:
            raise ValueError("Instagram requires at least one photo.")
        external_id = meta_client.publish_to_instagram(account.external_id, token, post.final_caption, image_url)
    elif post.platform == "linkedin_member":
        token = get_access_token("linkedin_member", account_owner)
        account = SocialAccount.query.filter_by(platform="linkedin_member", account_owner=account_owner).first()
        external_id = linkedin_client.publish_post(account.external_id, token, post.final_caption, image_url)
    else:
        raise ValueError(f"Unknown platform '{post.platform}'")

    post.status = "posted"
    post.posted_at = datetime.now(timezone.utc)
    post.external_post_id = external_id
    db.session.commit()


# ── Account connections ──────────────────────────────────────────────────

@bp.route("/accounts")
@login_required
def accounts():
    connected = {(a.platform, a.account_owner): a for a in SocialAccount.query.all()}
    return render_template(
        "social_accounts.html",
        owners=OWNERS,
        platforms=PLATFORMS,
        platform_labels=PLATFORM_LABELS,
        connected=connected,
        meta_configured=meta_client.is_configured(),
        linkedin_configured=linkedin_client.is_configured(),
    )


@bp.route("/accounts/connect/<platform>/<owner>/start")
@login_required
def connect_start(platform, owner):
    if owner not in OWNERS:
        return f"Unknown account '{owner}'", 404

    state = secrets.token_urlsafe(24)
    session[f"social_oauth_state_{platform}_{owner}"] = state
    redirect_uri = url_for("social.connect_callback", platform=platform, owner=owner, _external=True)

    try:
        if platform in ("facebook_page", "instagram_business"):
            auth_url = meta_client.build_oauth_url(redirect_uri, state)
        elif platform == "linkedin_member":
            auth_url = linkedin_client.build_oauth_url(redirect_uri, state)
        else:
            return f"Unsupported platform '{platform}'", 404
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("social.accounts"))

    return redirect(auth_url)


@bp.route("/accounts/connect/<platform>/<owner>/callback")
@login_required
def connect_callback(platform, owner):
    expected_state = session.pop(f"social_oauth_state_{platform}_{owner}", None)
    if not expected_state or request.args.get("state") != expected_state:
        return "Invalid OAuth state — please retry from the dashboard.", 400

    code = request.args.get("code")
    redirect_uri = url_for("social.connect_callback", platform=platform, owner=owner, _external=True)

    if platform in ("facebook_page", "instagram_business"):
        short_token = meta_client.exchange_code_for_user_token(code, redirect_uri)
        user_token, expires_at = meta_client.get_long_lived_user_token(short_token)
        pages = meta_client.list_pages(user_token)
        if not pages:
            flash("No Facebook Pages found for this login.", "error")
            return redirect(url_for("social.accounts"))
        # First page is used automatically. If Yifan/Anthony manage more
        # than one Page, this needs a picker — not built yet since we only
        # know of one Page per agent today.
        page = pages[0]
        page_token = page["access_token"]
        save_account_token(
            "facebook_page", owner, page_token,
            external_id=page["id"], display_name=page.get("name"), expires_at=expires_at,
        )
        if platform == "instagram_business":
            ig_resp = requests.get(
                f"{meta_client.GRAPH_URL}/{page['id']}",
                params={"fields": "instagram_business_account", "access_token": page_token},
            )
            ig_data = ig_resp.json().get("instagram_business_account")
            if ig_data:
                save_account_token(
                    "instagram_business", owner, page_token,
                    external_id=ig_data["id"], display_name=page.get("name"), expires_at=expires_at,
                )
            else:
                flash(f"Connected Facebook Page '{page.get('name')}' but it has no linked Instagram Business account.", "error")

    elif platform == "linkedin_member":
        token, expires_at = linkedin_client.exchange_code_for_token(code, redirect_uri)
        member_urn = linkedin_client.get_member_urn(token)
        save_account_token("linkedin_member", owner, token, external_id=member_urn, expires_at=expires_at)

    else:
        return f"Unsupported platform '{platform}'", 404

    flash(f"Connected {PLATFORM_LABELS.get(platform, platform)} for {owner.title()}.")
    return redirect(url_for("social.accounts"))
