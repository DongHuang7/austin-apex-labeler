"""
"What's due right now?" — checked from two places: the dashboard page (so
this works with zero extra infrastructure — it runs whenever Yifan or
Anthony opens the app) and, if a real cron gets set up on Railway later for
tighter timing, scripts/fire_scheduled_templates.py,
scripts/publish_scheduled_campaigns.py, and scripts/publish_scheduled_posts.py.
Every function here is safe to call as often as you like — each check is
itself idempotent (last_triggered_year guard for templates; status flips to
sent/failed/published so nothing fires twice). Must be called inside an
app context.
"""
from datetime import date, datetime, timezone

from mailer.templates import build_general_email
from models import Campaign, SocialPost, Template, db


def fire_due_templates():
    """Recurring templates due today (scheduled_month/day match, not yet
    fired this year) -> auto-create a draft SocialPost or a pending
    Campaign. Never sends/publishes anything itself — a person still has to
    Approve/Publish or click Send."""
    today = date.today()
    due = Template.query.filter(
        Template.scheduled_month == today.month,
        Template.scheduled_day == today.day,
    ).all()

    created = []
    for t in due:
        if t.last_triggered_year == today.year or not t.account_owner:
            continue

        if t.kind == "social" and t.platform:
            post = SocialPost(
                listing_id=None, platform=t.platform, account_owner=t.account_owner,
                draft_caption=t.body, final_caption=t.body, photo_urls=[], status="draft",
            )
            db.session.add(post)
            created.append(f"draft social post from template '{t.name}'")
        elif t.kind == "email" and t.recipient_group:
            content_blocks = None
            body_text = None
            photo_urls = []
            if t.is_html:
                html = t.body
            elif t.content_blocks:
                from routes.campaigns import _flat_photo_urls
                content_blocks = t.content_blocks
                photo_urls = _flat_photo_urls(content_blocks)
                _, html = build_general_email(
                    t.subject, blocks=content_blocks, agent_email=f"{t.account_owner}@austinapexre.com",
                )
            else:
                # Template saved before block-based bodies existed.
                body_text = t.body
                body_html = "".join(f"<p>{line}</p>" for line in t.body.splitlines() if line.strip())
                _, html = build_general_email(
                    t.subject, body_html, agent_email=f"{t.account_owner}@austinapexre.com",
                )
            campaign = Campaign(
                listing_id=None, email_type="recurring_template", subject=t.subject,
                html_body_snapshot=html, recipient_group=t.recipient_group,
                account=t.account_owner, status="pending", dry_run=False,
                recipient_count=0, sent_count=0,
                body_text=body_text, photo_urls=photo_urls, content_blocks=content_blocks,
            )
            db.session.add(campaign)
            created.append(f"pending campaign from template '{t.name}'")
        else:
            continue

        t.last_triggered_year = today.year
        db.session.commit()

    return created


def send_due_campaigns():
    """Campaigns scheduled for a time that's now passed -> actually send them."""
    from routes.campaigns import _send_campaign

    due = Campaign.query.filter(
        Campaign.status == "scheduled",
        Campaign.scheduled_time <= datetime.now(timezone.utc),
    ).all()

    results = []
    for campaign in due:
        only_emails = set(campaign.recipient_emails) if campaign.recipient_emails else None
        try:
            sent, total = _send_campaign(
                campaign, campaign.recipient_group, campaign.account,
                campaign.subject, campaign.html_body_snapshot, dry_run=campaign.dry_run,
                only_emails=only_emails,
            )
            results.append(f"campaign {campaign.id}: sent {sent}/{total}")
        except Exception as e:
            campaign.status = "failed"
            db.session.commit()
            results.append(f"campaign {campaign.id}: failed — {e}")

    return results


def publish_due_posts():
    """SocialPosts scheduled for a time that's now passed -> actually publish them."""
    from routes.social import _publish

    due = SocialPost.query.filter(
        SocialPost.status == "scheduled",
        SocialPost.scheduled_time <= datetime.now(timezone.utc),
    ).all()

    results = []
    for post in due:
        try:
            _publish(post, post.account_owner)
            results.append(f"post {post.id}: published")
        except Exception as e:
            post.status = "failed"
            post.error = str(e)
            db.session.commit()
            results.append(f"post {post.id}: failed — {e}")

    return results


def run_all_due():
    return {
        "templates_fired": fire_due_templates(),
        "campaigns_sent": send_due_campaigns(),
        "posts_published": publish_due_posts(),
    }
