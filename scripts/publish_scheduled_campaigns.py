"""
For a real cron trigger (tighter timing than the dashboard-load check in
scheduler.py): add as a Railway cron-scheduled job running `python
scripts/publish_scheduled_campaigns.py`, same as
scripts/fire_scheduled_templates.py and scripts/publish_scheduled_posts.py.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app  # noqa: E402
from scheduler import send_due_campaigns  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        results = send_due_campaigns()
        if results:
            for line in results:
                print(line)
        else:
            print("No campaigns due.")
