"""
Heroku Scheduler entrypoint: `python scripts/scan_new_contacts.py`
Add as a Heroku Scheduler job (10 min+ granularity). Shares scan_account()
with the dashboard's manual "Check now" button (routes/contacts.py) so both
paths behave identically.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app  # noqa: E402
from contact_scan import scan_all_accounts  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        results = scan_all_accounts()
        for account, count in results.items():
            print(f"{account}: {count} new contact(s) found")
