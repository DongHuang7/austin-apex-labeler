from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, Response, url_for
from flask_login import login_required

from models import Campaign, ContactReview, Listing, SocialAccount, SocialPost, Suppression, Template, UploadedPhoto, db
from photo_cache import cache_cover
from routes.campaigns import ACCOUNTS as EMAIL_ACCOUNTS
from routes.campaigns import RECIPIENT_GROUPS
from routes.social import OWNERS as SOCIAL_OWNERS
from routes.social import PLATFORM_LABELS, PLATFORMS
from scheduler import run_all_due
from social import linkedin_client, meta_client

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def home():
    try:
        results = run_all_due()
        fired = results["templates_fired"] + results["campaigns_sent"] + results["posts_published"]
        if fired:
            flash("Scheduled check: " + "; ".join(fired))
    except Exception as e:
        flash(f"Scheduled check failed: {e}", "error")

    pending_count = ContactReview.query.filter_by(status="pending").count()
    pending_campaigns = Campaign.query.filter(Campaign.status.in_(("draft", "scheduled", "pending"))).count()
    draft_posts = SocialPost.query.filter(SocialPost.status.in_(("draft", "scheduled"))).count()
    recent_campaigns = Campaign.query.order_by(Campaign.created_at.desc()).limit(5).all()
    recent_posts = SocialPost.query.order_by(SocialPost.created_at.desc()).limit(5).all()
    return render_template(
        "dashboard.html",
        pending_count=pending_count,
        pending_campaigns=pending_campaigns,
        draft_posts=draft_posts,
        recent_campaigns=recent_campaigns,
        recent_posts=recent_posts,
        platform_labels=PLATFORM_LABELS,
    )


@bp.route("/history")
@login_required
def history():
    status_filter = request.args.get("status", "all")
    if status_filter not in ("all", "open", "done"):
        status_filter = "all"
    channel_filter = request.args.get("channel", "all")
    if channel_filter not in ("all", "email", "social"):
        channel_filter = "all"

    items = []
    if channel_filter in ("all", "email"):
        for c in Campaign.query.order_by(Campaign.created_at.desc()).limit(200).all():
            items.append({
                "kind": "email",
                "when": c.created_at,
                "what": c.subject,
                "who": c.account or "",
                "status": c.status,
                "url": ("campaigns.detail", {"campaign_id": c.id}),
            })
    if channel_filter in ("all", "social"):
        for p in SocialPost.query.order_by(SocialPost.created_at.desc()).limit(200).all():
            items.append({
                "kind": "social",
                "when": p.created_at,
                "what": (p.final_caption or p.draft_caption or "")[:80],
                "who": p.account_owner,
                "status": p.status,
                "url": ("social.edit", {"post_id": p.id}),
            })

    if status_filter == "open":
        items = [i for i in items if i["status"] in ("draft", "scheduled", "pending", "approved")]
    elif status_filter == "done":
        items = [i for i in items if i["status"] in ("sent", "posted")]

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    items.sort(key=lambda i: i["when"] or epoch, reverse=True)
    return render_template(
        "history.html", items=items, status_filter=status_filter, channel_filter=channel_filter,
    )


@bp.route("/listings")
@login_required
def listings():
    listings = Listing.query.order_by(Listing.updated_at.desc()).all()
    return render_template("listings.html", listings=listings)


@bp.route("/listings/<int:listing_id>/cover")
@login_required
def listing_cover(listing_id):
    """Lazily cache one cover; listing-page JS requests these sequentially."""
    listing = db.get_or_404(Listing, listing_id)
    if listing.cover_photo_url:
        return redirect(listing.cover_photo_url)

    cached = cache_cover(listing.photo_urls or [])
    if cached:
        token = cached.rstrip("/").rsplit("/", 1)[-1]
        photo = UploadedPhoto.query.filter_by(token=token).first()
        used_source = photo.source_url if photo else None
        listing.photo_urls = [cached] + [
            u for u in (listing.photo_urls or []) if u not in (cached, used_source)
        ]
        db.session.commit()
        return redirect(cached)

    placeholder = """<svg xmlns='http://www.w3.org/2000/svg' width='900' height='560' viewBox='0 0 900 560'><rect width='900' height='560' fill='#e1e5df'/><text x='450' y='290' text-anchor='middle' fill='#748683' font-family='Georgia,serif' font-size='32'>Photo unavailable</text></svg>"""
    return Response(placeholder, mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})


@bp.route("/templates")
@login_required
def templates():
    email_templates = Template.query.filter_by(kind="email").order_by(Template.created_at.desc()).all()
    social_templates = Template.query.filter_by(kind="social").order_by(Template.created_at.desc()).all()
    return render_template(
        "templates.html",
        email_templates=email_templates,
        social_templates=social_templates,
        email_accounts=EMAIL_ACCOUNTS,
        recipient_groups=RECIPIENT_GROUPS,
        social_owners=SOCIAL_OWNERS,
        platform_labels=PLATFORM_LABELS,
    )


@bp.route("/settings")
@login_required
def settings():
    connected = {(a.platform, a.account_owner): a for a in SocialAccount.query.all()}
    suppressed = Suppression.query.order_by(Suppression.unsubscribed_at.desc()).all()
    return render_template(
        "settings.html",
        owners=SOCIAL_OWNERS,
        platforms=PLATFORMS,
        platform_labels=PLATFORM_LABELS,
        connected=connected,
        meta_configured=meta_client.is_configured(),
        linkedin_configured=linkedin_client.is_configured(),
        suppressed=suppressed,
    )


@bp.route("/settings/resubscribe/<int:suppression_id>", methods=["POST"])
@login_required
def resubscribe(suppression_id):
    s = db.get_or_404(Suppression, suppression_id)
    email = s.email
    db.session.delete(s)
    db.session.commit()
    flash(f"{email} can receive campaign emails again.")
    return redirect(url_for("dashboard.settings"))
