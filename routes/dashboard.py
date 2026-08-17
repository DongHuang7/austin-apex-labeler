from flask import Blueprint, render_template
from flask_login import login_required

from models import Campaign, ContactReview

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def home():
    pending_count = ContactReview.query.filter_by(status="pending").count()
    recent_campaigns = Campaign.query.order_by(Campaign.created_at.desc()).limit(5).all()
    return render_template(
        "dashboard.html",
        pending_count=pending_count,
        recent_campaigns=recent_campaigns,
    )
