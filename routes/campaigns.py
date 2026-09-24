import json
import hashlib
import threading
from functools import wraps

from flask import abort, Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from caption_generator import generate_general_email
from contacts.gmail_contacts import fetch_contacts_by_group
from mailer.sender import send_email
from mailer.templates import DEFAULT_CTA_URL, EMAIL_TYPES, LISTING_LAYOUT_DESCRIPTIONS, LISTING_LAYOUTS, build_general_email, build_listing_email
from mls.fetcher import fetch_active_listings, get_email_type, get_photo_urls, get_property_url
from models import Campaign, CampaignSend, Listing, Suppression, Template, db
from photo_cache import ensure_cached, store_uploaded_files
from timeutil import parse_local, to_local
from unsubscribe_tokens import unsubscribe_url

bp = Blueprint("campaigns", __name__, url_prefix="/campaigns")

ACCOUNTS = ["yifan", "anthony"]
# "All" is a union of the other four (see contacts.gmail_contacts.fetch_contacts_by_group),
# not a real Google Contacts group.
RECIPIENT_GROUPS = ["All", "Buyer", "Seller", "Broker", "Other"]
EDITABLE_CAMPAIGN_STATUSES = ("draft", "pending", "scheduled")
SUPPORTED_LISTING_LAYOUTS = set(LISTING_LAYOUTS) | {
    "original", "feature_spotlight", "featured_highlight",
    "editorial", "photo_gallery", "property_brief",
}
_refresh_lock = threading.Lock()


def _single_refresh(view):
    """Prevent repeated clicks from running overlapping MLS refreshes."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _refresh_lock.acquire(blocking=False):
            flash("An MLS refresh is already running. Please wait a moment.")
            return redirect(url_for("dashboard.listings"))
        try:
            return view(*args, **kwargs)
        finally:
            _refresh_lock.release()
    return wrapped


def _clamp_pct(value, default) -> float:
    try:
        return max(5, min(100, float(value)))
    except (TypeError, ValueError):
        return default


def _parse_blocks(raw: str) -> list:
    """Parses a general email's block-editor state (a JSON string carried
    through form fields / redirect query params, same as photo_urls/
    description elsewhere) into a clean list of
    {"type": "text", "content": str} / {"type": "photo", "url": str,
    "width_pct": 5-100, "align": "left"|"center"|"right"} /
    {"type": "row", "cells": [{"type": "photo"|"text", ..., "width_pct":
    5-100}, ...]} (2-3 cells, any mix of photo/text, each independently
    sized — replaces the old photos-only equal-width "photo_row").
    Silently drops anything malformed rather than erroring — the editor
    itself is trusted (it's the only thing that writes this field), so this
    is a safety net, not real validation."""
    if not raw:
        return []
    try:
        blocks = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(blocks, list):
        return []
    cleaned = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and isinstance(b.get("content"), str):
            cleaned.append({"type": "text", "content": b["content"]})
        elif b.get("type") == "photo" and isinstance(b.get("url"), str):
            block = {"type": "photo", "url": b["url"], "width_pct": _clamp_pct(b.get("width_pct"), 100)}
            if b.get("align") in ("left", "center", "right"):
                block["align"] = b["align"]
            cleaned.append(block)
        elif b.get("type") in ("row", "photo_row"):
            cells_raw = b.get("cells")
            if not cells_raw and isinstance(b.get("photos"), list):
                photos = [p for p in b["photos"] if isinstance(p, str) and p]
                n = len(photos) or 1
                cells_raw = [{"type": "photo", "url": u, "width_pct": 100 / n} for u in photos]
            cells = []
            for c in (cells_raw or [])[:3]:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "photo" and isinstance(c.get("url"), str) and c["url"]:
                    cell = {"type": "photo", "url": c["url"]}
                elif c.get("type") == "text" and isinstance(c.get("content"), str) and c["content"].strip():
                    cell = {"type": "text", "content": c["content"]}
                else:
                    continue
                cell["width_pct"] = _clamp_pct(c.get("width_pct"), 100 / max(1, len(cells_raw)))
                cells.append(cell)
            if len(cells) >= 2:
                cleaned.append({"type": "row", "cells": cells})
    return cleaned


def _flat_photo_urls(blocks: list) -> list:
    """All photo URLs referenced by a block list, in order — both standalone
    photo blocks and ones grouped into a row's cells. Used to keep
    Campaign.photo_urls (the legacy flat list some code still reads) in
    sync with whatever's actually in content_blocks."""
    urls = []
    for b in blocks or []:
        if b.get("type") == "photo" and b.get("url"):
            urls.append(b["url"])
        elif b.get("type") == "row":
            urls.extend(c["url"] for c in b.get("cells", []) if c.get("type") == "photo" and c.get("url"))
        elif b.get("type") == "photo_row":
            urls.extend(b.get("photos") or [])
    return urls


def _blocks_have_content(subject: str, blocks: list) -> bool:
    """True once there's actually something worth persisting — used to
    decide whether the compose page's first meaningful edit should turn
    into a real draft Campaign row (see create_general_draft())."""
    if subject.strip():
        return True
    for b in blocks or []:
        if b.get("type") == "text" and b.get("content", "").strip():
            return True
        if b.get("type") == "photo" and b.get("url"):
            return True
        if b.get("type") == "row":
            for c in b.get("cells", []):
                if c.get("type") == "photo" and c.get("url"):
                    return True
                if c.get("type") == "text" and c.get("content", "").strip():
                    return True
    return False


def _persist_general_content(campaign, subject, blocks):
    """Writes a general campaign's edited content straight to its row —
    shared by autosave, photo upload, and the final "Save changes" click,
    so all three ways of editing keep content_blocks/photo_urls/subject/
    html_body_snapshot consistent with each other."""
    campaign.subject = subject
    campaign.content_blocks = blocks
    campaign.photo_urls = _flat_photo_urls(blocks)
    _, html = build_general_email(
        subject, blocks=blocks, agent_email=f"{campaign.account}@austinapexre.com", cta_url=campaign.cta_url,
    )
    campaign.html_body_snapshot = html
    return html


def _collection_entries(campaign):
    if campaign.layout != "listing_collection":
        return []
    return [block for block in (campaign.content_blocks or []) if block.get("type") == "listing"]


@bp.route("/<int:campaign_id>/edit/collection", methods=["POST"])
@login_required
def update_listing_collection(campaign_id):
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.layout != "listing_collection" or campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        abort(409)
    try:
        ids = list(dict.fromkeys(int(value) for value in request.form.getlist("collection_listing_id")))
    except ValueError:
        abort(400)
    if len(ids) > 7 or campaign.listing_id in ids:
        abort(400)
    listings = [db.get_or_404(Listing, listing_id) for listing_id in ids]
    previous = {entry["listing_id"]: entry for entry in _collection_entries(campaign)}
    entries = []
    for listing in listings:
        # Preserve the reviewed snapshot for retained properties.
        entry = previous.get(listing.id)
        if entry is None:
            entry = dict(type="listing", listing_id=listing.id, listing=listing.raw_json,
                         photo_urls=ensure_cached(listing)[:1],
                         property_url=get_property_url(listing.raw_json),
                         email_type=get_email_type(listing.raw_json),
                         description=listing.raw_json.get("PublicRemarks") or "")
        entries.append(dict(entry, description=request.form.get(f"collection_description_{listing.id}", entry["description"])))
    campaign.content_blocks = entries
    description = campaign.body_text if campaign.body_text is not None else campaign.listing.raw_json.get("PublicRemarks", "")
    _persist_listing_campaign_content(campaign, description, campaign.photo_urls or [])
    db.session.commit()
    flash("Listing collection updated.")
    return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign.id))


def _persist_listing_campaign_content(campaign, description, photo_urls):
    """Writes a listing campaign's edited content straight to its row —
    shared by autosave_campaign_description, photo upload/remove, and the
    final "Save changes" click, so all four ways of editing keep
    body_text/photo_urls/subject/html_body_snapshot consistent with each
    other. Mirrors _persist_general_content()'s job for general campaigns."""
    listing = campaign.listing
    own_description = listing.raw_json.get("PublicRemarks", "")
    campaign.body_text = description if description != own_description else None
    campaign.photo_urls = photo_urls
    subject, html = build_listing_email(
        listing.raw_json, photo_urls=photo_urls, email_type=campaign.email_type,
        property_url=get_property_url(listing.raw_json), description=description,
        layout=campaign.layout, collection_entries=_collection_entries(campaign),
        agent_email=f"{campaign.account}@austinapexre.com",
    )
    campaign.subject = subject
    campaign.html_body_snapshot = html
    return html


@bp.route("/")
@login_required
def list_campaigns():
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).limit(50).all()
    return render_template("campaigns_list.html", campaigns=campaigns)


@bp.route("/new")
@login_required
def new_step1():
    """Kept for old links/bookmarks — the listing picker now lives at
    dashboard.listings, its own nav item instead of being buried under
    Campaigns (see the "Listings" section of the nav restructure)."""
    return redirect(url_for("dashboard.listings"))


@bp.route("/refresh_listings", methods=["POST"])
@login_required
@_single_refresh
def refresh_listings():
    try:
        fetched = fetch_active_listings(max_results=100, include_photos=True)
    except Exception as e:
        flash(f"Could not fetch listings from MLS: {e}", "error")
        return redirect(url_for("dashboard.listings"))

    upserted = 0
    for l in fetched:
        listing_id = l.get("ListingId")
        if not listing_id:
            continue
        row = Listing.query.filter_by(listing_id=listing_id).first()
        if row is None:
            row = Listing(listing_id=listing_id)
            db.session.add(row)
        row.status = l.get("StandardStatus")
        row.list_price = l.get("ListPrice")
        row.city = l.get("City")
        row.address = l.get("UnparsedAddress")
        row.raw_json = l
        fresh_photo_urls = get_photo_urls(l)
        # MLS media URLs are signed and rate-limit browser hotlinking. Keep
        # an already-cached cover across refreshes; for a new listing,
        # download only its first photo now. The remaining raw URLs stay in
        # the gallery and are cached on demand when a composer is opened.
        cached_cover = row.cover_photo_url
        row.photo_urls = ([cached_cover] + fresh_photo_urls[1:]) if cached_cover else fresh_photo_urls
        upserted += 1
    db.session.commit()

    flash(f"Refreshed {upserted} active listing(s) from MLS.")
    return redirect(url_for("dashboard.listings"))


def _existing_listing_campaign(listing):
    """A not-yet-sent campaign already in progress for this listing, if any
    — used so re-clicking "Email this listing" resumes work instead of
    starting over (and losing the chance to pick a template again)."""
    return (
        Campaign.query.filter_by(listing_id=listing.id)
        .filter(Campaign.status.in_(EDITABLE_CAMPAIGN_STATUSES))
        .order_by(Campaign.created_at.desc())
        .first()
    )


def _description_templates():
    """Saved, reusable listing-description write-ups (distinct from the
    block-based templates general email saves, which always have
    content_blocks set) — offered on the template-picker page below.
    Filtered in Python, not SQL — a JSON column holding Python None can be
    stored as the JSON literal "null" rather than a real SQL NULL, so
    `.filter(Template.content_blocks.is_(None))` silently matches nothing
    even though `t.content_blocks` reads back as None just fine."""
    return sorted(
        (t for t in Template.query.filter_by(kind="email", is_html=False).all() if not t.content_blocks),
        key=lambda t: t.name,
    )


@bp.route("/new/<listing_id>")
@login_required
def new_step2(listing_id):
    """Clicking "Email this listing" resumes a not-yet-sent campaign already
    in progress for it, or sends a first-time click to the template-picker
    page (choose_listing_template) instead of composing straight away."""
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()

    existing = _existing_listing_campaign(listing)
    if existing:
        return redirect(url_for("campaigns.edit_campaign", campaign_id=existing.id))

    if request.args.get("layout"):
        return start_listing_campaign(listing_id)
    return redirect(url_for("campaigns.choose_listing_template", listing_id=listing_id))


@bp.route("/new/<listing_id>/choose_template")
@login_required
def choose_listing_template(listing_id):
    """Preview exactly three designs with the current MLS listing's data."""
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()

    existing = _existing_listing_campaign(listing)
    if existing:
        return redirect(url_for("campaigns.edit_campaign", campaign_id=existing.id))

    email_type = get_email_type(listing.raw_json)
    photo_urls = ensure_cached(listing)
    property_url = get_property_url(listing.raw_json)
    own_description = listing.raw_json.get("PublicRemarks", "")

    def render_option(name, template_id, description, layout):
        _, html = build_listing_email(
            listing.raw_json, photo_urls=photo_urls, email_type=email_type,
            property_url=property_url, description=description, layout=layout,
        )
        return {"name": name, "template_id": template_id, "html_preview": html, "layout": layout, "hint": LISTING_LAYOUT_DESCRIPTIONS[layout]}

    options = [render_option(name, None, own_description, layout)
               for layout, name in LISTING_LAYOUTS.items()]

    return render_template("campaigns_choose_template.html", listing=listing, options=options)


@bp.route("/new/<listing_id>/start")
@login_required
def start_listing_campaign(listing_id):
    """Open a stateless listing composer for the selected design."""
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()

    existing = _existing_listing_campaign(listing)
    if existing:
        return redirect(url_for("campaigns.edit_campaign", campaign_id=existing.id))

    template_id = request.args.get("template_id", type=int)
    own_description = listing.raw_json.get("PublicRemarks", "")
    if template_id:
        t = db.get_or_404(Template, template_id)
        description = t.body
        layout = t.layout or "original"
    else:
        description = own_description
        layout = request.args.get("layout", "property_showcase")
        if layout not in LISTING_LAYOUTS:
            abort(400)

    email_type = request.args.get("email_type") or get_email_type(listing.raw_json)
    if email_type not in EMAIL_TYPES:
        abort(400)
    account = request.args.get("account", "yifan")
    recipient_group = request.args.get("recipient_group", "Buyer")
    photo_urls = request.args.getlist("photo_urls") or ensure_cached(listing)
    description = request.args.get("description", description)
    subject, html = build_listing_email(
        listing.raw_json, photo_urls=photo_urls, email_type=email_type,
        property_url=get_property_url(listing.raw_json), description=description, layout=layout,
    )
    return render_template(
        "campaigns_new_step2.html", listing=listing, subject=subject,
        html_preview=html, description=description, photo_urls=photo_urls,
        email_type=email_type, email_types=EMAIL_TYPES, accounts=ACCOUNTS,
        recipient_groups=RECIPIENT_GROUPS, recipient_group=recipient_group,
        selected_account=account, recipients=None, layout=layout,
    )


@bp.route("/new/<listing_id>/create_draft", methods=["POST"])
@login_required
def create_step2_draft(listing_id):
    """Persist the stateless listing composer as an explicit draft."""
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()
    existing = _existing_listing_campaign(listing)
    if existing:
        return {"ok": True, "id": existing.id}

    email_type = request.form.get("email_type") or get_email_type(listing.raw_json)
    layout = request.form.get("layout", "property_showcase")
    account = request.form.get("account", "yifan")
    recipient_group = request.form.get("recipient_group", "Buyer")
    if email_type not in EMAIL_TYPES or layout not in SUPPORTED_LISTING_LAYOUTS:
        return {"ok": False, "error": "Unknown email type or layout."}, 400
    if account not in ACCOUNTS or recipient_group not in RECIPIENT_GROUPS:
        return {"ok": False, "error": "Unknown sender or recipient group."}, 400

    description = request.form.get("description")
    own_description = listing.raw_json.get("PublicRemarks", "")
    if description is None:
        description = own_description
    photo_urls = request.form.getlist("photo_urls") or ensure_cached(listing)
    subject, html = build_listing_email(
        listing.raw_json, photo_urls=photo_urls, email_type=email_type,
        property_url=get_property_url(listing.raw_json), description=description,
        layout=layout, agent_email=f"{account}@austinapexre.com",
    )
    campaign = Campaign(
        listing_id=listing.id, email_type=email_type, subject=subject,
        html_body_snapshot=html, status="draft", created_by=current_user.id,
        recipient_group=recipient_group, account=account, dry_run=False,
        body_text=description if description != own_description else None,
        photo_urls=photo_urls, layout=layout,
    )
    db.session.add(campaign)
    db.session.commit()
    return {"ok": True, "id": campaign.id}


def _selected_recipient_emails():
    """Reads the recipient checklist from the compose form, if it was shown
    (see check_recipients_general() / new_step2's ?check_recipients=1) and
    submitted along with the send — returns a set of lowercased emails, or
    None if the checklist was never shown (send to the whole group,
    unchanged pre-existing behavior)."""
    if request.form.get("recipients_checked") != "1":
        return None
    return {e.strip().lower() for e in request.form.getlist("recipient_email") if e.strip()}


def _send_campaign(campaign, recipient_group, account, subject, html, dry_run=False, only_emails=None):
    """Sends a campaign's email to every contact in recipient_group, creating
    a CampaignSend per recipient and marking the campaign sent. Shared by the
    immediate-send routes below and scheduler.send_due_campaigns() (fires
    campaigns whose scheduled_time has passed). Listing-based campaigns get
    cross-campaign dedup against other sends for the same MLS listing;
    general campaigns don't (there's no listing to dedup against).

    only_emails, when given (a set of lowercased addresses), narrows the
    group down to just those people — set from the recipient-preview
    checklist (see recipients_preview()/Campaign.recipient_emails) instead
    of sending to everyone in the group."""
    recipients = fetch_contacts_by_group(recipient_group, account=account)
    if only_emails is not None:
        recipients = [c for c in recipients if (c.get("email") or "").lower() in only_emails]

    dedup_id = campaign.listing.listing_id if campaign.listing else None
    if campaign.layout == "listing_collection" and _collection_entries(campaign):
        # A new roundup must not be skipped just because its first home
        # appeared in a prior single-property email.
        collection_ids = sorted([campaign.listing_id] + [entry["listing_id"] for entry in _collection_entries(campaign)])
        dedup_id = "collection:" + hashlib.sha256(json.dumps(collection_ids).encode()).hexdigest()
    send_listing_id = dedup_id or "general"
    already_sent = set()
    if dedup_id:
        already_sent = {
            s.recipient_email.lower()
            for s in CampaignSend.query.filter_by(listing_id=dedup_id, status="sent").all()
        }
    suppressed = {s.email for s in Suppression.query.all()}

    sent = 0
    for contact in recipients:
        email = contact.get("email", "")
        name = contact.get("name") or email
        if not email:
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=send_listing_id,
                recipient_email="", recipient_name=name,
                status="skipped", error="No email address",
            ))
            continue
        if dedup_id and not dry_run and email.lower() in already_sent:
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=send_listing_id,
                recipient_email=email, recipient_name=name,
                status="skipped", error="Already sent this listing to this recipient",
            ))
            continue
        if not dry_run and email.lower() in suppressed:
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=send_listing_id,
                recipient_email=email, recipient_name=name,
                status="skipped", error="Unsubscribed",
            ))
            continue
        try:
            if not dry_run:
                send_email(
                    to=email, subject=subject,
                    html_body=html.replace("__UNSUBSCRIBE_URL__", unsubscribe_url(email)),
                    account=account,
                )
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=send_listing_id,
                recipient_email=email, recipient_name=name, status="sent",
            ))
            sent += 1
        except Exception as e:
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=send_listing_id,
                recipient_email=email, recipient_name=name,
                status="failed", error=str(e),
            ))

    campaign.sent_count = sent
    campaign.recipient_count = len(recipients)
    campaign.status = "sent"
    db.session.commit()
    return sent, len(recipients)


@bp.route("/new/<listing_id>/send", methods=["POST"])
@login_required
def send(listing_id):
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()
    email_type = request.form.get("email_type", "just_listed")
    agent_email = request.form.get("agent_email") or None
    recipient_group = request.form.get("recipient_group", "Buyer")
    account = request.form.get("account", "yifan")
    dry_run = request.form.get("dry_run") == "1"
    scheduled_time = request.form.get("scheduled_time")
    only_emails = _selected_recipient_emails()
    photo_urls = request.form.getlist("photo_urls") or ensure_cached(listing)
    description = request.form.get("description")
    layout = request.form.get("layout", "original")
    if layout not in SUPPORTED_LISTING_LAYOUTS:
        abort(400)
    if description is None:
        description = listing.raw_json.get("PublicRemarks", "")

    subject, html = build_listing_email(
        listing.raw_json,
        photo_urls=photo_urls,
        email_type=email_type,
        agent_email=agent_email,
        property_url=get_property_url(listing.raw_json),
        description=description,
        layout=layout,
    )

    # body_text only stores an actual override — if it matches the
    # listing's own description verbatim, leave it null so edit_campaign()
    # knows to keep tracking the listing's live description instead of a
    # stale copy frozen at send/schedule time.
    body_text_override = description if description != listing.raw_json.get("PublicRemarks", "") else None

    campaign = Campaign(
        listing_id=listing.id,
        email_type=email_type,
        subject=subject,
        html_body_snapshot=html,
        created_by=current_user.id,
        recipient_group=recipient_group,
        account=account,
        dry_run=dry_run,
        recipient_emails=sorted(only_emails) if only_emails is not None else None,
        body_text=body_text_override,
        photo_urls=photo_urls,
        layout=layout,
    )

    if scheduled_time:
        campaign.status = "scheduled"
        campaign.scheduled_time = parse_local(scheduled_time)
        db.session.add(campaign)
        db.session.commit()
        flash(f"Scheduled for {to_local(campaign.scheduled_time).strftime('%b %d, %Y %I:%M %p %Z')}.")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    db.session.add(campaign)
    db.session.flush()
    try:
        sent, total = _send_campaign(campaign, recipient_group, account, subject, html, dry_run=dry_run, only_emails=only_emails)
    except Exception as e:
        db.session.delete(campaign)
        db.session.commit()
        flash(f"Could not load '{recipient_group}' contacts for {account}: {e}", "error")
        return redirect(url_for("campaigns.new_step2", listing_id=listing_id))

    flash(f"{'[Dry run] ' if dry_run else ''}Campaign sent to {sent}/{total} recipients.")
    return redirect(url_for("campaigns.detail", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>")
@login_required
def detail(campaign_id):
    campaign = db.get_or_404(Campaign, campaign_id)
    sends = CampaignSend.query.filter_by(campaign_id=campaign.id).order_by(CampaignSend.sent_at).all()
    return render_template("campaigns_detail.html", campaign=campaign, sends=sends)


@bp.route("/<int:campaign_id>/send_now", methods=["POST"])
@login_required
def send_now(campaign_id):
    """Actually sends a "scheduled" or "pending" campaign right now instead
    of waiting — pending campaigns (auto-created from a recurring template,
    see scheduler.fire_due_templates()) always need this click since nobody
    reviewed this year's content before it was queued; scheduled ones
    (already reviewed, just waiting on their time) can use it to send early."""
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        flash("This campaign was already sent.", "error")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    only_emails = set(campaign.recipient_emails) if campaign.recipient_emails else None
    try:
        sent, total = _send_campaign(
            campaign, campaign.recipient_group, campaign.account,
            campaign.subject, campaign.html_body_snapshot, dry_run=campaign.dry_run,
            only_emails=only_emails,
        )
    except Exception as e:
        flash(f"Could not send: {e}", "error")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    flash(f"{'[Dry run] ' if campaign.dry_run else ''}Sent to {sent}/{total} recipients.")
    return redirect(url_for("campaigns.detail", campaign_id=campaign.id))


def _general_campaign_blocks(campaign):
    """The block list a general (non-listing) campaign should start editing
    from — its own content_blocks if it has them, a body_text/photo_urls
    fallback for anything saved before blocks existed, or None if this
    campaign's snapshot came from a saved HTML template (nothing
    block-editable in that case)."""
    if campaign.content_blocks is not None:
        return campaign.content_blocks
    if campaign.body_text is not None:
        blocks = [{"type": "text", "content": campaign.body_text}]
        blocks += [{"type": "photo", "url": u} for u in (campaign.photo_urls or [])]
        return blocks
    return None


def _render_campaign_compose(campaign, recipients=None):
    """Renders the same full compose page used for a from-scratch email
    (campaigns_new_general.html) but bound to an existing, not-yet-sent
    general Campaign row — used by edit_campaign() and
    check_recipients_campaign() so a pending/scheduled campaign gets the
    exact same Recipients/Schedule/AI/Template tools a fresh compose has,
    not just content editing."""
    blocks = _general_campaign_blocks(campaign)
    if blocks is not None:
        subject, html_preview = build_general_email(
            campaign.subject or "", blocks=blocks, agent_email=f"{campaign.account}@austinapexre.com",
            cta_url=campaign.cta_url,
        )
    else:
        html_preview = campaign.html_body_snapshot
    return render_template(
        "campaigns_new_general.html",
        campaign=campaign,
        subject=campaign.subject or "", blocks=blocks,
        content_blocks_json=json.dumps(blocks) if blocks is not None else None,
        html_preview=html_preview,
        recipient_group=campaign.recipient_group or "All",
        accounts=ACCOUNTS, recipient_groups=RECIPIENT_GROUPS,
        selected_account=campaign.account or "yifan",
        recipients=recipients, default_cta_url=DEFAULT_CTA_URL,
    )


def _render_listing_campaign_edit(campaign, recipients=None):
    """Renders the listing-campaign edit page — content (description/photos)
    autosaves straight to the Campaign row as each field is touched, and
    Recipients & send / Save as template mirror the same tools the
    template-picker compose flow has, just scoped to this existing campaign
    instead of a stateless listing_id. Used by edit_campaign() and
    check_recipients_campaign()."""
    listing = campaign.listing
    photo_urls = campaign.photo_urls or []
    description = campaign.body_text if campaign.body_text is not None else listing.raw_json.get("PublicRemarks", "")
    subject, html = build_listing_email(
        listing.raw_json, photo_urls=photo_urls, email_type=campaign.email_type,
        property_url=get_property_url(listing.raw_json), description=description,
        layout=campaign.layout, collection_entries=_collection_entries(campaign),
        agent_email=f"{campaign.account}@austinapexre.com",
    )
    return render_template(
        "campaigns_edit.html", campaign=campaign, listing=listing, subject=subject,
        description=description, photo_urls=photo_urls, blocks=None,
        content_blocks_json=None, html_preview=html, recipients=recipients,
        email_types=EMAIL_TYPES, accounts=ACCOUNTS, recipient_groups=RECIPIENT_GROUPS,
        layout_name=LISTING_LAYOUTS.get(campaign.layout, campaign.layout),
        collection_entries=_collection_entries(campaign),
        collection_choices=(Listing.query.filter(Listing.id != listing.id).order_by(Listing.address).all()
                            if campaign.layout == "listing_collection" else []),
        collection_selected={entry["listing_id"] for entry in _collection_entries(campaign)},
    )


@bp.route("/<int:campaign_id>/edit")
@login_required
def edit_campaign(campaign_id):
    """Edit a not-yet-sent campaign before it goes out — for a "scheduled"
    one (already reviewed, just waiting on its time) or a "pending" one
    (either auto-created by scheduler.fire_due_templates() and never
    reviewed by a person yet, or a from-scratch draft created by
    create_general_draft()/create_step2_draft() the moment someone started
    composing). Both branches autosave straight to the Campaign row as each
    field is touched — this page always just reflects what's actually in
    the database, nothing is lost if the tab closes before "Save changes"
    is clicked."""
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        flash("This campaign was already sent and can't be edited.", "error")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    if not campaign.listing_id:
        return _render_campaign_compose(campaign)
    return _render_listing_campaign_edit(campaign)


@bp.route("/<int:campaign_id>/edit/photos/upload", methods=["POST"])
@login_required
def upload_campaign_photo(campaign_id):
    campaign = db.get_or_404(Campaign, campaign_id)
    files = request.files.getlist("photo")
    new_urls, skipped = store_uploaded_files(files, uploaded_by=current_user.id)
    db.session.commit() if new_urls else db.session.rollback()

    if new_urls and not skipped:
        flash(f"Added {len(new_urls)} photo(s).")
    elif new_urls and skipped:
        flash(f"Added {len(new_urls)} photo(s). Skipped: {', '.join(skipped)}", "error")
    elif skipped:
        flash(f"Could not upload: {', '.join(skipped)}", "error")
    else:
        flash("Choose one or more photos to upload.", "error")

    if campaign.listing_id:
        all_urls = (campaign.photo_urls or []) + new_urls
        description = campaign.body_text if campaign.body_text is not None else campaign.listing.raw_json.get("PublicRemarks", "")
        _persist_listing_campaign_content(campaign, description, all_urls)
        db.session.commit()
        return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign_id))

    # General campaign — persist straight to the row (same as autosave)
    # instead of threading through the URL, so an upload is never lost even
    # if the tab closes before "Save changes" is clicked.
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    blocks.extend({"type": "photo", "url": u} for u in new_urls)
    subject = request.form.get("subject") or campaign.subject
    _persist_general_content(campaign, subject, blocks)
    db.session.commit()
    return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign_id))


@bp.route("/<int:campaign_id>/edit/autosave", methods=["POST"])
@login_required
def autosave_campaign_edit(campaign_id):
    """Background save fired from the block editor's JS on every meaningful
    edit (text input, reorder, combine/ungroup a row, subject change) — so
    a general campaign's Campaign row always reflects what's on screen,
    with no "unsaved until you click Save" window where a closed tab loses
    the work. Silent on purpose (no flash, JSON response): this fires
    constantly in the background, not from a user-visible submit."""
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES or campaign.listing_id:
        return {"ok": False}, 409
    if campaign.content_blocks is None and campaign.body_text is None:
        # HTML-template-sourced — never editable as blocks. Refuse rather
        # than let an autosave call clobber the original rendered HTML with
        # an empty block list.
        return {"ok": False}, 409
    # Optional — the full compose page (see _render_campaign_compose) also
    # autosaves recipient group/account from here; older callers that only
    # ever send subject/content_blocks leave these untouched. Set before
    # _persist_general_content() so a changed account's address is reflected
    # in the freshly-built html_body_snapshot instead of the stale one.
    if "recipient_group" in request.form:
        campaign.recipient_group = request.form.get("recipient_group") or campaign.recipient_group
    if "account" in request.form:
        campaign.account = request.form.get("account") or campaign.account
    if "cta_url" in request.form:
        # Blank clears the override — build_general_email() falls back to
        # DEFAULT_CTA_URL (the site homepage) whenever this is None.
        campaign.cta_url = request.form.get("cta_url", "").strip() or None
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    subject = request.form.get("subject", "")
    _persist_general_content(campaign, subject, blocks)
    db.session.commit()
    return {"ok": True}


@bp.route("/<int:campaign_id>/edit/autosave_description", methods=["POST"])
@login_required
def autosave_campaign_description(campaign_id):
    """Listing-campaign counterpart to autosave_campaign_edit() — a listing
    campaign's photo changes already persist immediately (upload/remove
    write straight to the row), so this covers everything else: the
    description text, and (like autosave_campaign_edit does for general
    campaigns) an optional email type / recipient group / account change —
    picking a different audience after the draft already exists is just as
    much an edit as touching the description. Silent background save, fired
    on blur/change from campaigns_edit.html."""
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES or not campaign.listing_id:
        return {"ok": False}, 409
    if "email_type" in request.form:
        campaign.email_type = request.form.get("email_type") or campaign.email_type
    if "recipient_group" in request.form:
        campaign.recipient_group = request.form.get("recipient_group") or campaign.recipient_group
    if "account" in request.form:
        campaign.account = request.form.get("account") or campaign.account
    description = request.form.get("description", campaign.body_text or "")
    _persist_listing_campaign_content(campaign, description, campaign.photo_urls or [])
    db.session.commit()
    return {"ok": True}


@bp.route("/<int:campaign_id>/edit/photos/remove", methods=["POST"])
@login_required
def remove_campaign_photo(campaign_id):
    """Listing campaigns only — a general campaign's photo blocks are
    removed client-side (see campaigns_edit.html), no server round trip
    needed since nothing has to be uploaded."""
    campaign = db.get_or_404(Campaign, campaign_id)
    remove_url = request.form.get("remove_url")
    remaining = [u for u in (campaign.photo_urls or []) if u != remove_url]
    description = campaign.body_text if campaign.body_text is not None else campaign.listing.raw_json.get("PublicRemarks", "")
    _persist_listing_campaign_content(campaign, description, remaining)
    db.session.commit()
    flash("Photo removed.")
    return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign_id))


@bp.route("/<int:campaign_id>/edit/save", methods=["POST"])
@login_required
def save_campaign_edit(campaign_id):
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        flash("This campaign was already sent and can't be edited.", "error")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    if campaign.listing_id:
        photo_urls = request.form.getlist("photo_urls")
        description = request.form.get("description", "")
        _persist_listing_campaign_content(campaign, description, photo_urls)
    else:
        subject = request.form.get("subject", "").strip()
        if "content_blocks" in request.form:
            blocks = _parse_blocks(request.form.get("content_blocks", ""))
            # Persist whatever was submitted first — even if it fails
            # validation below — so a rejected save still isn't lost; the
            # redirect-back reflects exactly what the sender just typed,
            # same as autosave already keeps doing during editing.
            _persist_general_content(campaign, subject, blocks)
            has_text = any(b["type"] == "text" and b.get("content", "").strip() for b in blocks)
            if not subject or not has_text:
                db.session.commit()
                flash("Subject and at least one non-empty text block are required.", "error")
                return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign_id))
        else:
            # HTML-template-sourced — nothing block-editable, only the
            # subject can change; the body stays as originally rendered.
            if not subject:
                flash("Subject is required.", "error")
                return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign_id))
            campaign.subject = subject

    db.session.commit()
    flash("Campaign updated.")
    return redirect(url_for("campaigns.detail", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>/delete", methods=["POST"])
@login_required
def delete_campaign(campaign_id):
    campaign = db.get_or_404(Campaign, campaign_id)
    subject = campaign.subject
    CampaignSend.query.filter_by(campaign_id=campaign.id).delete()
    db.session.delete(campaign)
    db.session.commit()
    flash(f"Deleted campaign '{subject}'.")
    return redirect(url_for("campaigns.list_campaigns"))


@bp.route("/test_send", methods=["POST"])
@login_required
def test_send():
    """Sends the email exactly as composed, but only to the logged-in user
    — lets them see real rendering (fonts, photos, signature) in an actual
    inbox before committing to a real send. Works from either compose
    screen (listing_id present = listing email, absent = manual email).
    Creates no Campaign row and doesn't count against anything."""
    listing_id = request.form.get("listing_id")
    account = request.form.get("account", "yifan")

    if listing_id:
        listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()
        campaign_id = request.form.get("campaign_id", type=int)
        email_type = request.form.get("email_type", "just_listed")
        agent_email = request.form.get("agent_email") or f"{account}@austinapexre.com"
        recipient_group = request.form.get("recipient_group", "Buyer")
        photo_urls = request.form.getlist("photo_urls") or ensure_cached(listing)
        description = request.form.get("description")
        if description is None:
            description = listing.raw_json.get("PublicRemarks", "")
        # The layout was fixed when the campaign was created (see
        # start_listing_campaign) and isn't threaded through the form, so
        # look it up from the row itself when there is one.
        draft = db.get_or_404(Campaign, campaign_id) if campaign_id else None
        layout = draft.layout if draft else "original"
        subject, html = build_listing_email(
            listing.raw_json, photo_urls=photo_urls, email_type=email_type,
            agent_email=agent_email, property_url=get_property_url(listing.raw_json),
            description=description, layout=layout,
            collection_entries=_collection_entries(draft) if draft else None,
        )
        if campaign_id:
            back = url_for("campaigns.edit_campaign", campaign_id=campaign_id)
        else:
            back = url_for(
                "campaigns.new_step2", listing_id=listing_id, email_type=email_type,
                recipient_group=recipient_group, account=account,
                photo_urls=photo_urls, description=description,
            )
    else:
        campaign_id = request.form.get("campaign_id", type=int)
        subject = request.form.get("subject", "").strip()
        blocks = _parse_blocks(request.form.get("content_blocks", ""))
        recipient_group = request.form.get("recipient_group", "All")
        has_text = any(b["type"] == "text" and b.get("content", "").strip() for b in blocks)
        if campaign_id:
            back = url_for("campaigns.edit_campaign", campaign_id=campaign_id)
        else:
            back = url_for(
                "campaigns.new_general", subject=subject, content_blocks=json.dumps(blocks),
                recipient_group=recipient_group, account=account,
            )
        if not subject or not has_text:
            flash("Subject and at least one non-empty text block are required.", "error")
            return redirect(back if campaign_id else url_for("campaigns.new_general", content_blocks=json.dumps(blocks)))
        subject, html = build_general_email(subject, blocks=blocks, agent_email=f"{account}@austinapexre.com")
        if campaign_id:
            # Bound to an existing draft — persist the current edit too,
            # same as autosave, so a test send never looks out of sync with
            # what's about to be saved.
            campaign = db.get_or_404(Campaign, campaign_id)
            campaign.recipient_group = recipient_group
            campaign.account = account
            _persist_general_content(campaign, subject, blocks)
            db.session.commit()

    html = html.replace("__UNSUBSCRIBE_URL__", unsubscribe_url(current_user.email))

    try:
        send_email(to=current_user.email, subject=f"[TEST] {subject}", html_body=html, account=account)
        flash(f"Test email sent to {current_user.email}.")
    except Exception as e:
        flash(f"Could not send test: {e}", "error")

    return redirect(back)


# ── General (non-listing) campaigns: festival posts, announcements, etc. ──

@bp.route("/new_general")
@login_required
def new_general():
    """Render a stateless composer; opening it never creates a DB row."""
    template_id = request.args.get("template_id", type=int)
    account = request.args.get("account", "yifan")
    recipient_group = request.args.get("recipient_group", "All")

    if template_id:
        t = db.get_or_404(Template, template_id)
        subject = t.subject or ""
        blocks = t.content_blocks if t.content_blocks else [{"type": "text", "content": t.body}]
    else:
        subject = ""
        blocks = [{"type": "text", "content": ""}]

    if request.args.get("subject") is not None:
        subject = request.args.get("subject", "")
    if request.args.get("content_blocks") is not None:
        blocks = _parse_blocks(request.args.get("content_blocks", ""))
    _, html_preview = build_general_email(
        subject or "(no subject yet)", blocks=blocks,
        agent_email=f"{account}@austinapexre.com",
    )
    templates = [
        t for t in Template.query.filter_by(kind="email").order_by(Template.name).all()
        if not t.is_html
    ]
    return render_template(
        "campaigns_new_general.html", campaign=None, templates=templates,
        subject=subject, blocks=blocks, content_blocks_json=json.dumps(blocks),
        html_preview=html_preview, recipient_group=recipient_group,
        accounts=ACCOUNTS, recipient_groups=RECIPIENT_GROUPS,
        selected_account=account, recipients=None, default_cta_url=DEFAULT_CTA_URL,
    )


@bp.route("/new_general/check_recipients", methods=["POST"])
@login_required
def check_recipients_general():
    """Re-renders the compose form with the actual fetched contact list
    shown as a checklist, so "Send to Buyers now" isn't a leap of faith —
    doesn't send anything or create a Campaign row."""
    recipient_group = request.form.get("recipient_group", "All")
    account = request.form.get("account", "yifan")
    try:
        recipients = fetch_contacts_by_group(recipient_group, account=account)
    except Exception as e:
        flash(f"Could not load '{recipient_group}' contacts for {account}: {e}", "error")
        recipients = None

    templates = [
        t for t in Template.query.filter_by(kind="email").order_by(Template.name).all()
        if not t.is_html
    ]
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    subject = request.form.get("subject", "")
    _, html_preview = build_general_email(subject or "(no subject yet)", blocks=blocks, agent_email=f"{account}@austinapexre.com")
    return render_template(
        "campaigns_new_general.html",
        templates=templates,
        subject=subject,
        blocks=blocks,
        content_blocks_json=json.dumps(blocks),
        html_preview=html_preview,
        recipient_group=recipient_group,
        accounts=ACCOUNTS,
        recipient_groups=RECIPIENT_GROUPS,
        selected_account=account,
        recipients=recipients,
    )


@bp.route("/<int:campaign_id>/edit/check_recipients", methods=["POST"])
@login_required
def check_recipients_campaign(campaign_id):
    """Same as check_recipients_general() but for an existing, not-yet-sent
    campaign — persists the current edits first (same fields autosave
    writes) so switching groups/accounts to check recipients doesn't lose
    whatever's on screen, then re-renders the same edit page bound to this
    campaign. A listing campaign's recipient_group/account are fixed at
    compose time (see _maybe_create_step2_draft) — this only previews who
    they already resolve to, it doesn't let them be changed here."""
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        flash("This campaign can't be edited.", "error")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    if campaign.listing_id:
        description = request.form.get("description", campaign.body_text or "")
        photo_urls = request.form.getlist("photo_urls") or (campaign.photo_urls or [])
        _persist_listing_campaign_content(campaign, description, photo_urls)
        db.session.commit()
        try:
            recipients = fetch_contacts_by_group(campaign.recipient_group, account=campaign.account)
        except Exception as e:
            flash(f"Could not load '{campaign.recipient_group}' contacts for {campaign.account}: {e}", "error")
            recipients = None
        return _render_listing_campaign_edit(campaign, recipients=recipients)

    campaign.recipient_group = request.form.get("recipient_group", campaign.recipient_group or "All")
    campaign.account = request.form.get("account", campaign.account or "yifan")
    if "cta_url" in request.form:
        campaign.cta_url = request.form.get("cta_url", "").strip() or None
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    subject = request.form.get("subject", "")
    _persist_general_content(campaign, subject, blocks)
    db.session.commit()

    try:
        recipients = fetch_contacts_by_group(campaign.recipient_group, account=campaign.account)
    except Exception as e:
        flash(f"Could not load '{campaign.recipient_group}' contacts for {campaign.account}: {e}", "error")
        recipients = None

    return _render_campaign_compose(campaign, recipients=recipients)


@bp.route("/new_general/generate", methods=["POST"])
@login_required
def generate_general():
    topic = request.form.get("topic", "").strip()
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    photo_blocks = [b for b in blocks if b["type"] == "photo"]
    if not topic:
        flash("Describe a topic to generate an email from.", "error")
        return redirect(url_for("campaigns.new_general", content_blocks=json.dumps(blocks)))

    try:
        subject, body = generate_general_email(topic)
    except Exception as e:
        flash(f"Could not generate an email: {e}", "error")
        return redirect(url_for("campaigns.new_general", content_blocks=json.dumps(blocks)))

    # Replaces the text portion with the fresh draft but keeps any photos
    # already added — regenerating copy shouldn't discard uploaded photos.
    new_blocks = [{"type": "text", "content": body}] + photo_blocks
    return redirect(url_for("campaigns.new_general", subject=subject, content_blocks=json.dumps(new_blocks)))


@bp.route("/<int:campaign_id>/edit/generate", methods=["POST"])
@login_required
def generate_general_campaign(campaign_id):
    """Same as generate_general() but persists the regenerated draft
    straight to an existing campaign instead of threading it through the
    URL back to a stateless compose page."""
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES or campaign.listing_id:
        flash("This campaign can't be edited.", "error")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    topic = request.form.get("topic", "").strip()
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    photo_blocks = [b for b in blocks if b["type"] == "photo"]
    if not topic:
        flash("Describe a topic to generate an email from.", "error")
        return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign.id))

    try:
        subject, body = generate_general_email(topic)
    except Exception as e:
        flash(f"Could not generate an email: {e}", "error")
        return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign.id))

    new_blocks = [{"type": "text", "content": body}] + photo_blocks
    _persist_general_content(campaign, subject, new_blocks)
    db.session.commit()
    return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign.id))


@bp.route("/new_general/create_draft", methods=["POST"])
@login_required
def create_general_draft():
    """Turns an in-progress compose session into a real, persisted Campaign
    row the moment there's anything worth saving — fired silently by the
    compose page's JS on the first meaningful edit (see
    campaigns_new_general.html). Before this, new_general() is entirely
    stateless (subject/blocks only ever lived in the page's form/query
    params), so navigating away or closing the tab lost everything with no
    trace in History. Once this fires, the browser is sent to the normal
    edit page, which autosaves every further change (autosave_campaign_edit)
    — so this route only ever needs to run once per campaign."""
    subject = request.form.get("subject", "").strip()
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    recipient_group = request.form.get("recipient_group", "All")
    account = request.form.get("account", "yifan")
    cta_url = request.form.get("cta_url", "").strip() or None

    if not _blocks_have_content(subject, blocks):
        return {"ok": False}, 400

    campaign = Campaign(
        listing_id=None,
        email_type="general",
        status="draft",
        created_by=current_user.id,
        recipient_group=recipient_group,
        account=account,
        cta_url=cta_url,
        dry_run=False,
    )
    _persist_general_content(campaign, subject, blocks)
    db.session.add(campaign)
    db.session.commit()
    return {"ok": True, "id": campaign.id}


@bp.route("/new_general/send", methods=["POST"])
@login_required
def send_general():
    subject = request.form.get("subject", "").strip()
    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    recipient_group = request.form.get("recipient_group", "All")
    account = request.form.get("account", "yifan")
    dry_run = request.form.get("dry_run") == "1"
    scheduled_time = request.form.get("scheduled_time")
    only_emails = _selected_recipient_emails()

    has_text = any(b["type"] == "text" and b.get("content", "").strip() for b in blocks)
    if not subject or not has_text:
        flash("Subject and at least one non-empty text block are required.", "error")
        return redirect(url_for("campaigns.new_general", subject=subject, content_blocks=json.dumps(blocks)))

    subject, html = build_general_email(subject, blocks=blocks, agent_email=f"{account}@austinapexre.com")
    photo_urls = _flat_photo_urls(blocks)

    campaign = Campaign(
        listing_id=None,
        email_type="general",
        subject=subject,
        html_body_snapshot=html,
        created_by=current_user.id,
        recipient_group=recipient_group,
        account=account,
        dry_run=dry_run,
        recipient_emails=sorted(only_emails) if only_emails is not None else None,
        content_blocks=blocks,
        photo_urls=photo_urls,
    )

    if scheduled_time:
        campaign.status = "scheduled"
        campaign.scheduled_time = parse_local(scheduled_time)
        db.session.add(campaign)
        db.session.commit()
        flash(f"Scheduled for {to_local(campaign.scheduled_time).strftime('%b %d, %Y %I:%M %p %Z')}.")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    db.session.add(campaign)
    db.session.flush()
    try:
        sent, total = _send_campaign(campaign, recipient_group, account, subject, html, dry_run=dry_run, only_emails=only_emails)
    except Exception as e:
        db.session.delete(campaign)
        db.session.commit()
        flash(f"Could not load '{recipient_group}' contacts for {account}: {e}", "error")
        return redirect(url_for(
            "campaigns.new_general", subject=subject, content_blocks=json.dumps(blocks),
            recipient_group=recipient_group, account=account,
        ))

    flash(f"{'[Dry run] ' if dry_run else ''}Campaign sent to {sent}/{total} recipients.")
    return redirect(url_for("campaigns.detail", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>/edit/send", methods=["POST"])
@login_required
def send_campaign_edit(campaign_id):
    """Same job as send_general()/send() — send now, schedule for later, or
    a dry run — but for an existing campaign (reached by editing a draft
    that create_general_draft()/create_step2_draft() already created, or a
    pending/scheduled campaign from History), so it sends/reschedules that
    row instead of creating a second one."""
    campaign = db.get_or_404(Campaign, campaign_id)
    if campaign.status not in EDITABLE_CAMPAIGN_STATUSES:
        flash("This campaign can't be sent from here.", "error")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    dry_run = request.form.get("dry_run") == "1"
    scheduled_time = request.form.get("scheduled_time")
    only_emails = _selected_recipient_emails()

    if campaign.listing_id:
        # Recipients/account are fixed at compose time for a listing
        # campaign (see _maybe_create_step2_draft) — content is already
        # kept current by autosave_campaign_description/upload/remove, so
        # there's nothing left to persist here, just send/schedule it.
        recipient_group = campaign.recipient_group or "Buyer"
        account = campaign.account or "yifan"
        subject = campaign.subject
        html = campaign.html_body_snapshot
        campaign.recipient_emails = sorted(only_emails) if only_emails is not None else None
    else:
        subject = request.form.get("subject", "").strip()
        blocks = _parse_blocks(request.form.get("content_blocks", ""))
        recipient_group = request.form.get("recipient_group", campaign.recipient_group or "All")
        account = request.form.get("account", campaign.account or "yifan")

        has_text = any(b["type"] == "text" and b.get("content", "").strip() for b in blocks)
        if not subject or not has_text:
            flash("Subject and at least one non-empty text block are required.", "error")
            return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign.id))

        campaign.recipient_group = recipient_group
        campaign.account = account
        campaign.recipient_emails = sorted(only_emails) if only_emails is not None else None
        if "cta_url" in request.form:
            campaign.cta_url = request.form.get("cta_url", "").strip() or None
        html = _persist_general_content(campaign, subject, blocks)

    if scheduled_time:
        campaign.status = "scheduled"
        campaign.scheduled_time = parse_local(scheduled_time)
        db.session.commit()
        flash(f"Scheduled for {to_local(campaign.scheduled_time).strftime('%b %d, %Y %I:%M %p %Z')}.")
        return redirect(url_for("campaigns.detail", campaign_id=campaign.id))

    db.session.commit()
    try:
        sent, total = _send_campaign(campaign, recipient_group, account, subject, html, dry_run=dry_run, only_emails=only_emails)
    except Exception as e:
        flash(f"Could not load '{recipient_group}' contacts for {account}: {e}", "error")
        return redirect(url_for("campaigns.edit_campaign", campaign_id=campaign.id))

    flash(f"{'[Dry run] ' if dry_run else ''}Campaign sent to {sent}/{total} recipients.")
    return redirect(url_for("campaigns.detail", campaign_id=campaign.id))


@bp.route("/new_general/photos/upload", methods=["POST"])
@login_required
def upload_general_photo():
    """Photos for a manual/general email, uploaded before any Campaign row
    exists yet (unlike social posts, a general email has nothing to attach
    to until Send is clicked) — so the block list (with the new photo
    block(s) appended) is threaded through as a ?content_blocks= JSON query
    param on the compose page, same way subject already survives Generate/
    Save-template redirects. Removing/reordering a block is pure
    client-side JS (see campaigns_new_general.html) since it needs no
    upload — this route only ever appends."""
    files = request.files.getlist("photo")
    new_urls, skipped = store_uploaded_files(files, uploaded_by=current_user.id)
    db.session.commit() if new_urls else db.session.rollback()

    blocks = _parse_blocks(request.form.get("content_blocks", ""))
    blocks.extend({"type": "photo", "url": u} for u in new_urls)

    if new_urls and not skipped:
        flash(f"Added {len(new_urls)} photo(s).")
    elif new_urls and skipped:
        flash(f"Added {len(new_urls)} photo(s). Skipped: {', '.join(skipped)}", "error")
    elif skipped:
        flash(f"Could not upload: {', '.join(skipped)}", "error")
    else:
        flash("Choose one or more photos to upload.", "error")

    return redirect(url_for(
        "campaigns.new_general",
        subject=request.form.get("subject", ""),
        recipient_group=request.form.get("recipient_group", "All"),
        account=request.form.get("account", "yifan"),
        content_blocks=json.dumps(blocks),
    ))


# ── Email templates ────────────────────────────────────────────────────────

@bp.route("/templates")
@login_required
def templates():
    """Kept for old links — email + social templates now share one page,
    dashboard.templates, instead of two near-identical ones."""
    return redirect(url_for("dashboard.templates"))


@bp.route("/templates/save", methods=["POST"])
@login_required
def save_template():
    name = request.form.get("name", "").strip()
    subject = request.form.get("subject", "").strip()
    is_html = request.form.get("is_html") == "1"
    listing_id = request.form.get("listing_id")
    content_blocks = None

    if listing_id:
        body = request.form.get("body", "").strip()
        campaign_id = request.form.get("campaign_id", type=int)
        if campaign_id:
            back = url_for("campaigns.edit_campaign", campaign_id=campaign_id)
        else:
            back = url_for(
                "campaigns.new_step2", listing_id=listing_id,
                email_type=request.form.get("email_type", ""),
                agent_email=request.form.get("agent_email", ""),
                recipient_group=request.form.get("recipient_group", "Buyer"),
                account=request.form.get("account", "yifan"),
                description=request.form.get("description", ""),
                photo_urls=request.form.getlist("photo_urls"),
            )
    else:
        content_blocks = _parse_blocks(request.form.get("content_blocks", ""))
        # Plain-text join kept in sync for templates.html's listing/preview
        # and as a fallback for anything that reads .body directly.
        body = "\n\n".join(
            b["content"] for b in content_blocks if b["type"] == "text" and b.get("content", "").strip()
        )
        campaign_id = request.form.get("campaign_id", type=int)
        if campaign_id:
            back = url_for("campaigns.edit_campaign", campaign_id=campaign_id)
        else:
            back = url_for("campaigns.new_general", subject=subject, content_blocks=json.dumps(content_blocks))

    if not name or not body:
        flash("A template needs a name and body.", "error")
        return redirect(back)

    db.session.add(Template(
        kind="email", name=name, subject=subject, body=body,
        is_html=is_html, content_blocks=content_blocks, created_by=current_user.id,
    ))
    db.session.commit()
    flash(f"Saved email template '{name}'.")
    return redirect(back)


@bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@login_required
def delete_template(template_id):
    t = db.get_or_404(Template, template_id)
    name = t.name
    db.session.delete(t)
    db.session.commit()
    flash(f"Deleted template '{name}'.")
    return redirect(url_for("campaigns.templates"))


@bp.route("/templates/<int:template_id>/schedule", methods=["POST"])
@login_required
def schedule_template(template_id):
    """Makes this template recur every year on a month/day — see
    scheduler.fire_due_templates(), which auto-creates a pending campaign
    from it each year it's due (still requires a click to actually send)."""
    t = db.get_or_404(Template, template_id)
    month = request.form.get("scheduled_month", type=int)
    day = request.form.get("scheduled_day", type=int)
    account_owner = request.form.get("account_owner") or None
    recipient_group = request.form.get("recipient_group") or None

    if not month or not day:
        flash("Pick a month and day to schedule this template.", "error")
        return redirect(url_for("campaigns.templates"))
    if not account_owner or not recipient_group:
        flash("Pick an account and recipient group so this template knows who to send from/to.", "error")
        return redirect(url_for("campaigns.templates"))

    t.scheduled_month = month
    t.scheduled_day = day
    t.account_owner = account_owner
    t.recipient_group = recipient_group
    db.session.commit()
    flash(f"'{t.name}' will fire every year on {month}/{day}.")
    return redirect(url_for("campaigns.templates"))


@bp.route("/templates/<int:template_id>/unschedule", methods=["POST"])
@login_required
def unschedule_template(template_id):
    t = db.get_or_404(Template, template_id)
    t.scheduled_month = None
    t.scheduled_day = None
    t.last_triggered_year = None
    db.session.commit()
    flash(f"Cleared the schedule for '{t.name}'.")
    return redirect(url_for("campaigns.templates"))
