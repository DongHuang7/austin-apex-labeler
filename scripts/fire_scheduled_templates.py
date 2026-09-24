"""
For a real cron trigger (tighter timing than the dashboard-load check in
scheduler.py, which runs the same logic whenever someone opens the app):
add a Railway cron-scheduled service running `python
scripts/fire_scheduled_templates.py`. See the "Cron infrastructure"
section of the scheduling plan for exact dashboard steps — not required to
use this feature at all, just for more precise timing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app  # noqa: E402
from scheduler import fire_due_templates  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        created = fire_due_templates()
        if created:
            for line in created:
                print(line)
        else:
            print("No templates due today.")
