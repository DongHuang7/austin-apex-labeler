from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

db = SQLAlchemy()


def _utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, nullable=False)
    display_name = db.Column(db.String, nullable=False)
    password_hash = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    last_login_at = db.Column(db.DateTime(timezone=True))

    # Flask-Login expects these
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)


class GoogleToken(db.Model):
    """Replaces token_<account>.json files — tokens must live in Postgres since
    Heroku dynos have an ephemeral filesystem."""
    __tablename__ = "google_tokens"

    id = db.Column(db.Integer, primary_key=True)
    account = db.Column(db.String, unique=True, nullable=False)  # "yifan", "anthony", "default"
    refresh_token_encrypted = db.Column(db.LargeBinary, nullable=False)
    access_token_encrypted = db.Column(db.LargeBinary)
    token_expiry = db.Column(db.DateTime(timezone=True))
    scopes = db.Column(db.JSON)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ContactReview(db.Model):
    """Replaces pending_contacts.json + run_apply_pending.py's buggy one-shot apply.
    Status is persisted per-row so failures are never silently dropped."""
    __tablename__ = "contact_reviews"
    __table_args__ = (UniqueConstraint("account", "email", name="uq_contact_review_account_email"),)

    id = db.Column(db.Integer, primary_key=True)
    account = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=False)
    name = db.Column(db.String)
    subjects = db.Column(db.JSON)
    snippet = db.Column(db.Text)
    suggested_category = db.Column(db.String)
    suggested_reason = db.Column(db.Text)
    final_category = db.Column(db.String)
    status = db.Column(db.String, nullable=False, default="pending")
    # pending, approved, rejected, applied, failed
    error = db.Column(db.Text)
    resource_name = db.Column(db.String)
    detected_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    decided_at = db.Column(db.DateTime(timezone=True))
    applied_at = db.Column(db.DateTime(timezone=True))
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"))


class Listing(db.Model):
    """Replaces seen_listings.json — caches MLS listing data for the campaign composer."""
    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.String, unique=True, nullable=False)
    status = db.Column(db.String)
    list_price = db.Column(db.Numeric)
    city = db.Column(db.String)
    address = db.Column(db.String)
    raw_json = db.Column(db.JSON)
    photo_urls = db.Column(db.JSON)
    fetched_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Campaign(db.Model):
    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    email_type = db.Column(db.String)
    subject = db.Column(db.String)
    html_body_snapshot = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    recipient_count = db.Column(db.Integer, default=0)
    sent_count = db.Column(db.Integer, default=0)
    dry_run = db.Column(db.Boolean, default=True)

    listing = db.relationship("Listing")


class CampaignSend(db.Model):
    """Replaces sent_log.json, keeps per-recipient granularity."""
    __tablename__ = "campaign_sends"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    listing_id = db.Column(db.String, nullable=False)  # MLS ListingId, for cross-campaign dedup
    recipient_email = db.Column(db.String, nullable=False)
    recipient_name = db.Column(db.String)
    status = db.Column(db.String, nullable=False)  # sent, skipped, failed
    error = db.Column(db.Text)
    sent_at = db.Column(db.DateTime(timezone=True), default=_utcnow)

    campaign = db.relationship("Campaign")


class SocialAccount(db.Model):
    """Connected Facebook Page / Instagram Business / LinkedIn account.
    Access tokens are encrypted at rest, same as GoogleToken. Populated by
    the OAuth connect flow in routes/social.py once Meta/LinkedIn app
    approval has landed — until then, no rows exist and social_posts can be
    drafted but not published."""
    __tablename__ = "social_accounts"
    __table_args__ = (UniqueConstraint("platform", "account_owner", name="uq_social_account_platform_owner"),)

    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String, nullable=False)
    # facebook_page, instagram_business, linkedin_member, linkedin_org
    account_owner = db.Column(db.String, nullable=False)  # "yifan", "anthony"
    external_id = db.Column(db.String)  # the Page/Org ID on the platform's side
    display_name = db.Column(db.String)
    access_token_encrypted = db.Column(db.LargeBinary)
    refresh_token_encrypted = db.Column(db.LargeBinary)
    token_expires_at = db.Column(db.DateTime(timezone=True))
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class SocialPost(db.Model):
    """AI-drafted, human-edited social post for a listing. Mirrors
    ContactReview's review-and-approve pattern: nothing publishes without a
    person editing/approving the draft first."""
    __tablename__ = "social_posts"

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    platform = db.Column(db.String, nullable=False)
    account_owner = db.Column(db.String, nullable=False)  # "yifan", "anthony" — which agent's connected account to publish through
    social_account_id = db.Column(db.Integer, db.ForeignKey("social_accounts.id"))
    draft_caption = db.Column(db.Text)
    final_caption = db.Column(db.Text)
    photo_urls = db.Column(db.JSON)
    status = db.Column(db.String, nullable=False, default="draft")
    # draft, approved, scheduled, posted, failed
    scheduled_time = db.Column(db.DateTime(timezone=True))
    posted_at = db.Column(db.DateTime(timezone=True))
    external_post_id = db.Column(db.String)
    error = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    listing = db.relationship("Listing")
    social_account = db.relationship("SocialAccount")


class Selection(db.Model):
    """One-click label selections from confirmation-digest email links.
    Ported as-is from the original server/app.py's `selections` table."""
    __tablename__ = "selections"

    session_id = db.Column(db.String, primary_key=True)
    contact_idx = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
