import secrets
from datetime import datetime, timezone

import requests
from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from caption_generator import generate_caption, generate_general_caption
from models import Listing, SocialAccount, SocialPost, Template, UploadedPhoto, db
from photo_cache import ensure_cached, ensure_post_cached
from social import linkedin_client, meta_client
from social.token_store import get_access_token, save_account_token

MAX_PHOTO_BYTES = 8 * 1024 * 1024

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
    ensure_cached(listing)
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

    ensure_cached(listing)

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


# ── General (non-listing) posts: festival posts, announcements, etc. ──────

@bp.route("/new_general")
@login_required
def new_general():
    templates = Template.query.filter_by(kind="social").order_by(Template.name).all()
    template_id = request.args.get("template_id", type=int)
    caption = request.args.get("caption", "")
    if template_id:
        t = db.get_or_404(Template, template_id)
        caption = t.body
    return render_template(
        "social_new_general.html",
        platforms=PLATFORMS, platform_labels=PLATFORM_LABELS,
        templates=templates, caption=caption,
    )


@bp.route("/new_general/generate", methods=["POST"])
@login_required
def generate_general():
    platform = request.form.get("platform")
    account_owner = request.form.get("account_owner")
    topic = request.form.get("topic", "").strip()
    caption = request.form.get("caption", "").strip()

    if platform not in PLATFORMS:
        flash(f"Unknown platform '{platform}'.", "error")
        return redirect(url_for("social.new_general"))
    if account_owner not in OWNERS:
        flash(f"Unknown account owner '{account_owner}'.", "error")
        return redirect(url_for("social.new_general"))

    if not caption:
        if not topic:
            flash("Write a caption, or describe a topic to generate one from.", "error")
            return redirect(url_for("social.new_general"))
        try:
            caption = generate_general_caption(topic, platform)
        except Exception as e:
            flash(f"Could not generate a caption: {e}", "error")
            return redirect(url_for("social.new_general"))

    post = SocialPost(
        listing_id=None,
        platform=platform,
        account_owner=account_owner,
        draft_caption=caption,
        final_caption=caption,
        photo_urls=[],
        status="draft",
        created_by=current_user.id,
    )
    db.session.add(post)
    db.session.commit()

    return redirect(url_for("social.edit", post_id=post.id))


# ── Social caption templates ───────────────────────────────────────────────

@bp.route("/templates")
@login_required
def templates():
    saved = Template.query.filter_by(kind="social").order_by(Template.created_at.desc()).all()
    return render_template("social_templates.html", templates=saved, platform_labels=PLATFORM_LABELS)


@bp.route("/templates/save", methods=["POST"])
@login_required
def save_template():
    name = request.form.get("name", "").strip()
    platform = request.form.get("platform") or None
    body = request.form.get("caption", "").strip()
    post_id = request.form.get("post_id", type=int)

    if not name or not body:
        flash("A template needs a name and caption text.", "error")
        return redirect(url_for("social.edit", post_id=post_id) if post_id else url_for("social.new_general"))

    db.session.add(Template(kind="social", name=name, platform=platform, body=body, created_by=current_user.id))
    db.session.commit()
    flash(f"Saved post template '{name}'.")
    return redirect(url_for("social.edit", post_id=post_id) if post_id else url_for("social.new_general"))


@bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def delete_template(template_id):
    t = db.get_or_404(Template, template_id)
    name = t.name
    db.session.delete(t)
    db.session.commit()
    flash(f"Deleted template '{name}'.")
    return redirect(url_for("social.templates"))


@bp.route("/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = db.get_or_404(SocialPost, post_id)
    label = f"{PLATFORM_LABELS.get(post.platform, post.platform)} post"
    db.session.delete(post)
    db.session.commit()
    flash(f"Deleted {label}.")
    return redirect(url_for("social.list_posts"))


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

    photo_urls = ensure_post_cached(post)
    templates = Template.query.filter_by(kind="social").order_by(Template.name).all()

    return render_template(
        "social_edit.html", post=post, photo_urls=photo_urls,
        platform_labels=PLATFORM_LABELS, owners=OWNERS, templates=templates,
    )


@bp.route("/<int:post_id>/photos/upload", methods=["POST"])
@login_required
def upload_photo(post_id):
    post = db.get_or_404(SocialPost, post_id)
    files = [f for f in request.files.getlist("photo") if f and f.filename]
    if not files:
        flash("Choose one or more photos to upload.", "error")
        return redirect(url_for("social.edit", post_id=post.id))

    new_urls = []
    skipped = []
    for file in files:
        content_type = file.content_type or ""
        if not content_type.startswith("image/"):
            skipped.append(f"{file.filename} (not an image)")
            continue

        data = file.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            skipped.append(f"{file.filename} (over 8MB)")
            continue

        photo = UploadedPhoto(
            token=secrets.token_urlsafe(24),
            content_type=content_type,
            data=data,
            uploaded_by=current_user.id,
            social_post_id=post.id,
        )
        db.session.add(photo)
        db.session.flush()
        new_urls.append(url_for("social.serve_photo", token=photo.token, _external=True))

    if new_urls:
        existing = ensure_post_cached(post)
        post.photo_urls = [*existing, *new_urls]
        db.session.commit()
    else:
        db.session.rollback()

    if new_urls and not skipped:
        flash(f"Added {len(new_urls)} photo(s).")
    elif new_urls and skipped:
        flash(f"Added {len(new_urls)} photo(s). Skipped: {', '.join(skipped)}", "error")
    else:
        flash(f"Could not upload: {', '.join(skipped)}", "error")

    return redirect(url_for("social.edit", post_id=post.id))


@bp.route("/<int:post_id>/photos/remove", methods=["POST"])
@login_required
def remove_photo(post_id):
    post = db.get_or_404(SocialPost, post_id)
    url = request.form.get("url")
    current = ensure_post_cached(post)
    post.photo_urls = [u for u in current if u != url]
    db.session.commit()
    flash("Photo removed.")
    return redirect(url_for("social.edit", post_id=post.id))


@bp.route("/<int:post_id>/photos/restore", methods=["POST"])
@login_required
def restore_photos(post_id):
    """Removing a photo only drops its URL from post.photo_urls — it never
    deletes the underlying UploadedPhoto row or touches the listing's own
    cached photos. This brings back everything available: the listing's
    current photos plus any photo ever manually uploaded to this post."""
    post = db.get_or_404(SocialPost, post_id)
    current = ensure_post_cached(post)
    full = list(current)

    if post.listing:
        for u in ensure_cached(post.listing):
            if u not in full:
                full.append(u)

    for photo in UploadedPhoto.query.filter_by(social_post_id=post.id).all():
        u = url_for("social.serve_photo", token=photo.token, _external=True)
        if u not in full:
            full.append(u)

    added = len(full) - len(current)
    post.photo_urls = full
    db.session.commit()

    flash(f"Restored {added} removed photo(s)." if added else "No removed photos to restore.")
    return redirect(url_for("social.edit", post_id=post.id))


@bp.route("/photo/<token>")
def serve_photo(token):
    """Unauthenticated on purpose: Facebook/Instagram/LinkedIn fetch the
    image server-side from the URL we hand them when publishing. `token` is
    a random, unguessable id, not the row's primary key."""
    photo = UploadedPhoto.query.filter_by(token=token).first_or_404()
    return Response(photo.data, mimetype=photo.content_type)


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
    photo_urls = ensure_post_cached(post)
    image_url = (photo_urls or [None])[0]

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
