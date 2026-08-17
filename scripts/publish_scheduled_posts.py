"""
Heroku Scheduler entrypoint: `python scripts/publish_scheduled_posts.py`
Publishes every SocialPost whose scheduled_time has passed, using each
post's own account_owner (captured when the draft was created — see
routes/social.py's generate()). Add as a Heroku Scheduler job (10 min+
granularity), same pattern as scan_new_contacts.py.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app  # noqa: E402
from models import SocialPost, db  # noqa: E402
from routes.social import _publish  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        due = SocialPost.query.filter(
            SocialPost.status == "scheduled",
            SocialPost.scheduled_time <= datetime.now(timezone.utc),
        ).all()

        for post in due:
            try:
                _publish(post, post.account_owner)
                print(f"post {post.id}: published")
            except Exception as e:
                post.status = "failed"
                post.error = str(e)
                db.session.commit()
                print(f"post {post.id}: failed — {e}")
