"""
Creates (or refreshes) the local SQLite dev database at dev/local.db:
tables via db.create_all(), one login user, and one sample listing so the
compose/edit flows have something real to point at. Idempotent — safe to
re-run; skips anything that already exists. Never touches production.

Usage: .venv/bin/python scripts/dev/seed_db.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

DEV_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "dev", "local.db")
os.makedirs(os.path.dirname(DEV_DB_PATH), exist_ok=True)

os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.abspath(DEV_DB_PATH)}")
os.environ.setdefault("FLASK_SECRET_KEY", "dev-only-not-a-real-secret")
os.environ.setdefault("APP_BASE_URL", "http://localhost:5050")
os.environ.setdefault("GOOGLE_CLIENT_ID", "dev-placeholder")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "dev-placeholder")

from app import create_app  # noqa: E402
from models import Listing, User, db  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

DEV_EMAIL = "yifan@austinapexre.com"
DEV_PASSWORD = "devpass123"
DEV_LISTING_ID = "MLS123"

app = create_app()
with app.app_context():
    db.create_all()

    if not User.query.filter_by(email=DEV_EMAIL).first():
        db.session.add(User(
            email=DEV_EMAIL, display_name="Yifan Ingle (dev)",
            password_hash=generate_password_hash(DEV_PASSWORD, method="pbkdf2:sha256"),
        ))
        print(f"Created dev user {DEV_EMAIL} / {DEV_PASSWORD}")
    else:
        print(f"Dev user {DEV_EMAIL} already exists ({DEV_PASSWORD} if you forgot the password)")

    if not Listing.query.filter_by(listing_id=DEV_LISTING_ID).first():
        db.session.add(Listing(
            listing_id=DEV_LISTING_ID,
            status="Active",
            list_price=500000,
            city="Austin",
            address="123 Main St",
            raw_json={
                "ListingId": DEV_LISTING_ID,
                "UnparsedAddress": "123 Main St",
                "City": "Austin",
                "ListPrice": 500000,
                "PublicRemarks": "Sample MLS description for local dev testing.",
                "ListAgentEmail": "agent@example.com",
            },
            photo_urls=[],
        ))
        print(f"Created sample listing {DEV_LISTING_ID}")
    else:
        print(f"Sample listing {DEV_LISTING_ID} already exists")

    db.session.commit()

print(f"\nDev DB ready at {os.path.abspath(DEV_DB_PATH)}")
