from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from contacts.gmail_contacts import fetch_contacts_by_group
from mailer.sender import send_email
from mailer.templates import EMAIL_TYPES, build_listing_email
from mls.fetcher import fetch_active_listings, get_email_type, get_photo_urls, get_property_url
from models import Campaign, CampaignSend, Listing, db

bp = Blueprint("campaigns", __name__, url_prefix="/campaigns")

ACCOUNTS = ["yifan", "anthony"]
RECIPIENT_GROUPS = ["Buyer", "Seller", "Broker", "Other"]


@bp.route("/")
@login_required
def list_campaigns():
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).limit(50).all()
    return render_template("campaigns_list.html", campaigns=campaigns)


@bp.route("/new")
@login_required
def new_step1():
    listings = Listing.query.order_by(Listing.updated_at.desc()).all()
    return render_template("campaigns_new_step1.html", listings=listings)


@bp.route("/refresh_listings", methods=["POST"])
@login_required
def refresh_listings():
    try:
        fetched = fetch_active_listings(max_results=100, include_photos=True)
    except Exception as e:
        flash(f"Could not fetch listings from MLS: {e}", "error")
        return redirect(url_for("campaigns.new_step1"))

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
        row.photo_urls = get_photo_urls(l)
        upserted += 1
    db.session.commit()

    flash(f"Refreshed {upserted} active listing(s) from MLS.")
    return redirect(url_for("campaigns.new_step1"))


@bp.route("/new/<listing_id>")
@login_required
def new_step2(listing_id):
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()
    email_type = request.args.get("email_type") or get_email_type(listing.raw_json)
    agent_email = request.args.get("agent_email") or None
    recipient_group = request.args.get("recipient_group", "Buyer")

    subject, html = build_listing_email(
        listing.raw_json,
        photo_urls=listing.photo_urls,
        email_type=email_type,
        agent_email=agent_email,
        property_url=get_property_url(listing.raw_json),
    )

    return render_template(
        "campaigns_new_step2.html",
        listing=listing,
        subject=subject,
        html_preview=html,
        email_type=email_type,
        email_types=EMAIL_TYPES,
        agent_email=agent_email,
        recipient_group=recipient_group,
        recipient_groups=RECIPIENT_GROUPS,
        accounts=ACCOUNTS,
        selected_account=request.args.get("account", "yifan"),
    )


@bp.route("/new/<listing_id>/send", methods=["POST"])
@login_required
def send(listing_id):
    listing = Listing.query.filter_by(listing_id=listing_id).first_or_404()
    email_type = request.form.get("email_type", "just_listed")
    agent_email = request.form.get("agent_email") or None
    recipient_group = request.form.get("recipient_group", "Buyer")
    account = request.form.get("account", "yifan")
    dry_run = request.form.get("dry_run") == "1"

    subject, html = build_listing_email(
        listing.raw_json,
        photo_urls=listing.photo_urls,
        email_type=email_type,
        agent_email=agent_email,
        property_url=get_property_url(listing.raw_json),
    )

    try:
        recipients = fetch_contacts_by_group(recipient_group, account=account)
    except Exception as e:
        flash(f"Could not load '{recipient_group}' contacts for {account}: {e}", "error")
        return redirect(url_for("campaigns.new_step2", listing_id=listing_id))

    campaign = Campaign(
        listing_id=listing.id,
        email_type=email_type,
        subject=subject,
        html_body_snapshot=html,
        created_by=current_user.id,
        recipient_count=len(recipients),
        dry_run=dry_run,
    )
    db.session.add(campaign)
    db.session.flush()

    already_sent = {
        s.recipient_email.lower()
        for s in CampaignSend.query.filter_by(listing_id=listing.listing_id, status="sent").all()
    }

    sent = 0
    for contact in recipients:
        email = contact.get("email", "")
        name = contact.get("name") or email
        if not email:
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=listing.listing_id,
                recipient_email="", recipient_name=name,
                status="skipped", error="No email address",
            ))
            continue
        if not dry_run and email.lower() in already_sent:
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=listing.listing_id,
                recipient_email=email, recipient_name=name,
                status="skipped", error="Already sent this listing to this recipient",
            ))
            continue
        try:
            if not dry_run:
                send_email(to=email, subject=subject, html_body=html, account=account)
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=listing.listing_id,
                recipient_email=email, recipient_name=name, status="sent",
            ))
            sent += 1
        except Exception as e:
            db.session.add(CampaignSend(
                campaign_id=campaign.id, listing_id=listing.listing_id,
                recipient_email=email, recipient_name=name,
                status="failed", error=str(e),
            ))

    campaign.sent_count = sent
    db.session.commit()

    flash(f"{'[Dry run] ' if dry_run else ''}Campaign sent to {sent}/{len(recipients)} recipients.")
    return redirect(url_for("campaigns.detail", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>")
@login_required
def detail(campaign_id):
    campaign = db.get_or_404(Campaign, campaign_id)
    sends = CampaignSend.query.filter_by(campaign_id=campaign.id).order_by(CampaignSend.sent_at).all()
    return render_template("campaigns_detail.html", campaign=campaign, sends=sends)
