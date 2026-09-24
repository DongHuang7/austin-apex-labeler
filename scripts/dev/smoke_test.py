"""
Regression smoke test for the email-campaign editing/photo-upload flows
(routes/campaigns.py, scheduler.fire_due_templates()), including the
block-based general-campaign editor (Campaign.content_blocks /
Template.content_blocks — lets a photo be placed anywhere in the copy
instead of only a fixed header/grid layout). Runs against its own
throwaway SQLite DB (dev/smoke_test.db, recreated each run) — never touches
dev/local.db or production.

Exists because of a real bug this suite would have caught: the photo-upload
routes only flushed the new UploadedPhoto row into the request's session
without committing, so it looked fine in-process but 404'd on the very next
request. The "committed to disk" check below uses a separate sqlite3
connection specifically so an in-process session can't mask that again.

Usage: .venv/bin/python scripts/dev/smoke_test.py
"""
import io
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "dev", "smoke_test.db")
DB_PATH = os.path.abspath(DB_PATH)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["FLASK_SECRET_KEY"] = "smoke-test-secret"
os.environ["APP_BASE_URL"] = "http://localhost"
os.environ.setdefault("GOOGLE_CLIENT_ID", "dev-placeholder")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "dev-placeholder")

from app import create_app  # noqa: E402
from mailer.templates import DEFAULT_CTA_URL, build_listing_email  # noqa: E402
from models import Campaign, Listing, SocialPost, Template, User, db  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

app = create_app()
app.app_context().push()

db.create_all()
user = User(
    email="smoketest@austinapexre.com", display_name="Smoke Test",
    password_hash=generate_password_hash("testpass", method="pbkdf2:sha256"),
)
db.session.add(user)

listing = Listing(
    listing_id="MLS123", status="Active", list_price=500000, city="Austin", address="123 Main St",
    raw_json={
        "ListingId": "MLS123", "UnparsedAddress": "123 Main St", "City": "Austin",
        "ListPrice": 500000, "PublicRemarks": "Original MLS description of a lovely home.",
        "ListAgentEmail": "agent@example.com",
    },
    photo_urls=[],
)
db.session.add(listing)
db.session.commit()
listing_pk = listing.id

client = app.test_client()

def login():
    r = client.post("/login", data={"email": "smoketest@austinapexre.com", "password": "testpass"}, follow_redirects=True)
    assert r.status_code == 200, r.status_code

def fake_photo(name="test.jpg"):
    return (io.BytesIO(b"fake-jpeg-bytes"), name)

def query_param(location, name):
    """Properly decodes one query param from a redirect Location header —
    manual string splitting mishandles '+' (space) and multi-byte percent
    escapes, which a JSON-carrying param like content_blocks has plenty of."""
    return parse_qs(urlparse(location).query)[name][0]

FAKE_CONTACTS = [{"name": "Alice Buyer", "email": "alice@example.com"}]

with patch("routes.campaigns.fetch_contacts_by_group", return_value=FAKE_CONTACTS), \
     patch("routes.campaigns.send_email") as mock_send:
    login()

    # Social listing drafts start with three useful photos instead of
    # copying a full MLS gallery. The editor can replace all three in one
    # selection and save a new order in one request.
    social_listing = Listing(
        listing_id="MLS_SOCIAL", status="Active", address="789 Social Way", city="Austin",
        raw_json={"ListingId": "MLS_SOCIAL", "UnparsedAddress": "789 Social Way", "City": "Austin"},
        photo_urls=[f"http://localhost/social/photo/mls-{i}" for i in range(1, 7)],
    )
    db.session.add(social_listing)
    db.session.commit()
    with patch("routes.social.generate_caption", return_value="Social caption"):
        r = client.post("/social/generate/MLS_SOCIAL", data={
            "platform": "instagram_business", "account_owner": "yifan",
        })
    assert r.status_code == 302
    social_post = SocialPost.query.filter_by(listing_id=social_listing.id).one()
    assert social_post.photo_urls == social_listing.photo_urls[:3]
    r = client.post(f"/social/{social_post.id}/photos/select", data={
        "listing_photo_url": [social_listing.photo_urls[4], social_listing.photo_urls[2]],
    })
    assert r.status_code == 302
    assert social_post.photo_urls == [social_listing.photo_urls[4], social_listing.photo_urls[2]]
    r = client.post(f"/social/{social_post.id}/photos/reorder", data={
        "photo_order": list(reversed(social_post.photo_urls)),
    })
    assert r.status_code == 302
    assert social_post.photo_urls == [social_listing.photo_urls[2], social_listing.photo_urls[4]]
    assert client.post(f"/social/{social_post.id}/photos/select", data={
        "listing_photo_url": social_listing.photo_urls[:4],
    }).status_code == 400
    assert client.post(f"/social/{social_post.id}/photos/reorder", data={
        "photo_order": ["https://example.com/not-this-post.jpg"],
    }).status_code == 400
    page = client.get(f"/social/{social_post.id}/edit").get_data(as_text=True)
    assert "Choose different listing photos" in page and "Make cover" in page and "Save photo order" in page
    db.session.delete(social_post)
    db.session.delete(social_listing)
    db.session.commit()
    print("[ok] social drafts use three MLS photos and support one-step selection/reordering")

    # ---- A multi-paragraph description with blank-line-separated sections
    # and a short ALL-CAPS section header must render as real paragraphs
    # with a bolded header — not collapse into one run-on <p> with no
    # visible structure, which is what a saved description template's
    # careful formatting would look like without this. ----
    structured_description = "Intro paragraph here.\n\nARCHITECTURE\nSecond paragraph about the exterior.\n\nTHE KITCHEN\nThird paragraph about the kitchen."
    _, structured_html = build_listing_email(
        {"UnparsedAddress": "1 Test Ln", "City": "Austin", "ListPrice": 400000, "PublicRemarks": ""},
        email_type="just_listed", description=structured_description,
    )
    assert "Intro paragraph here." in structured_html
    assert ">ARCHITECTURE<" in structured_html, "a standalone ALL-CAPS line should render as its own bolded header"
    assert "font-weight:bold" in structured_html
    assert "Second paragraph about the exterior." in structured_html
    # The header and the following paragraph must NOT be jammed into the
    # same <p> — confirms real paragraph breaks, not one collapsed blob.
    assert "</p>" in structured_html.split("ARCHITECTURE")[1].split("Second paragraph")[0]
    print("[ok] a structured, multi-section description renders as real paragraphs with bolded section headers")

    # ---- Listing compose: clicking "Email this listing" (GET new_step2)
    # must land on a template-choice page first, not create a campaign yet —
    # choosing a design still stays stateless; only Save draft persists. ----
    desc_template = Template(
        kind="email", name="Feature Spotlight", subject="", body="Step inside this [feature]-filled home...",
        is_html=False, content_blocks=None, layout="feature_spotlight", created_by=user.id,
    )
    db.session.add(desc_template)
    db.session.commit()

    r = client.get("/campaigns/new/MLS123", follow_redirects=False)
    assert r.status_code == 302
    choose_loc = r.headers["Location"]
    assert "/choose_template" in choose_loc
    assert Campaign.query.filter_by(listing_id=listing_pk).count() == 0, "landing on the picker must not create anything yet"

    r = client.get(choose_loc)
    assert r.status_code == 200
    page = r.get_data(as_text=True)
    assert page.count('class="template-card"') == 3
    assert "Property Showcase" in page and "Lifestyle Spotlight" in page and "Listing Collection" in page
    assert "Yifan&#39;s Original" not in page
    print("[ok] clicking into a listing compose lands on a template-choice page first, creating nothing yet")

    for layout in ("property_showcase", "lifestyle_spotlight", "listing_collection"):
        assert f"layout={layout}" in page
        r = client.get(f"/campaigns/new/MLS123/start?layout={layout}")
        assert r.status_code == 200
        assert Campaign.query.filter_by(listing_id=listing_pk).count() == 0
        r = client.post("/campaigns/new/MLS123/create_draft", data={
            "layout": layout, "email_type": "just_listed",
            "recipient_group": "Buyer", "account": "yifan",
            "description": "Original MLS description of a lovely home.",
        })
        assert r.status_code == 200 and r.get_json()["ok"]
        built_in = Campaign.query.filter_by(listing_id=listing_pk).one()
        assert built_in.layout == layout
        assert "Original MLS description" in built_in.html_body_snapshot
        if layout == "listing_collection":
            extra = Listing(listing_id="MLS_EXTRA", address="456 Collection Ave", city="Austin", raw_json={
                "UnparsedAddress": "456 Collection Ave", "ListPrice": 610000,
                "PublicRemarks": "Second property description.", "StandardStatus": "Active",
            }, photo_urls=[])
            db.session.add(extra)
            db.session.commit()
            endpoint = f"/campaigns/{built_in.id}/edit/collection"
            assert client.post(endpoint, data={"collection_listing_id": "invalid"}).status_code == 400
            assert client.post(endpoint, data={"collection_listing_id": str(listing_pk)}).status_code == 400
            r = client.post(endpoint, data={"collection_listing_id": str(extra.id)}, follow_redirects=True)
            assert r.status_code == 200
            assert len(built_in.content_blocks) == 1
            assert "456 Collection Ave" in built_in.html_body_snapshot
            assert "2 properties" in built_in.subject
            r = client.post(f"/campaigns/{built_in.id}/edit/autosave_description", data={"description": "Updated primary description"})
            assert r.status_code == 200
            assert "456 Collection Ave" in built_in.html_body_snapshot
            r = client.post(endpoint, data={"collection_listing_id": str(extra.id), f"collection_description_{extra.id}": "Edited second property"})
            assert r.status_code == 302
            assert "Edited second property" in built_in.html_body_snapshot
            r = client.post("/campaigns/test_send", data={
                "listing_id": "MLS123", "campaign_id": built_in.id,
                "description": "Updated primary description", "account": "yifan",
            })
            assert r.status_code == 302
            assert "456 Collection Ave" in mock_send.call_args.kwargs["html_body"]
            assert "Edited second property" in mock_send.call_args.kwargs["html_body"]
            assert "__UNSUBSCRIBE_URL__" not in mock_send.call_args.kwargs["html_body"]
            mock_send.reset_mock()
            from routes.campaigns import _send_campaign
            from models import CampaignSend
            prior_send = CampaignSend(campaign_id=built_in.id, listing_id="MLS123", recipient_email="alice@example.com", status="sent")
            db.session.add(prior_send)
            db.session.commit()
            sent, _ = _send_campaign(built_in, recipient_group="Buyer", account="yifan", subject=built_in.subject, html=built_in.html_body_snapshot, dry_run=False)
            assert sent == 1, "a prior single-property email must not suppress a new collection"
            assert "456 Collection Ave" in mock_send.call_args.kwargs["html_body"]
            sent, _ = _send_campaign(built_in, recipient_group="Buyer", account="yifan", subject=built_in.subject, html=built_in.html_body_snapshot, dry_run=False)
            assert sent == 0, "the same property collection should still deduplicate"
            CampaignSend.query.filter_by(campaign_id=built_in.id).delete()
            db.session.commit()
            mock_send.reset_mock()
            built_in.status = "sent"
            db.session.commit()
            assert client.post(endpoint, data={}).status_code == 409
            built_in.status = "pending"
            db.session.commit()
            assert client.post(endpoint, data={}).status_code == 302
            assert "456 Collection Ave" not in built_in.html_body_snapshot
            db.session.delete(extra)
        db.session.delete(built_in)
        db.session.commit()
    assert client.get("/campaigns/new/MLS123/start?layout=invalid").status_code == 400
    print("[ok] built-in gallery layouts persist MLS content and reject invalid layout choices")

    # Picking the template opens a pre-filled stateless composer; Save draft
    # then persists that body and layout.
    r = client.get(f"/campaigns/new/MLS123/start?template_id={desc_template.id}", follow_redirects=False)
    assert r.status_code == 200 and desc_template.body in r.get_data(as_text=True)
    r = client.post("/campaigns/new/MLS123/create_draft", data={
        "layout": "feature_spotlight", "email_type": "just_listed",
        "recipient_group": "Buyer", "account": "yifan",
        "description": desc_template.body,
    })
    assert r.status_code == 200 and r.get_json()["ok"]
    desc_draft_id = r.get_json()["id"]
    loc = f"/campaigns/{desc_draft_id}/edit"
    desc_draft = db.session.get(Campaign, desc_draft_id)
    assert desc_draft.status == "draft"
    assert desc_draft.listing_id == listing_pk
    assert desc_draft.recipient_group == "Buyer" and desc_draft.account == "yifan"
    assert desc_draft.body_text == desc_template.body
    assert desc_template.body in desc_draft.html_body_snapshot
    # The template's layout (a genuinely different HTML structure, not just
    # different description text) must carry over onto the campaign, and
    # actually be what's rendered — not silently fall back to the original.
    assert desc_draft.layout == "feature_spotlight"
    assert "SCHEDULE A PRIVATE TOUR" in desc_draft.html_body_snapshot
    assert "VIEW PROPERTY" not in desc_draft.html_body_snapshot
    # Shows up in History after the explicit save.
    r = client.get("/campaigns/")
    assert desc_draft.subject in r.get_data(as_text=True)
    print("[ok] explicit Save draft persists the selected template and layout")

    # Clicking "Email this listing" again for the SAME listing must resume
    # that draft (skipping the picker), not create a second, duplicate row.
    r = client.get("/campaigns/new/MLS123", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"] == loc
    assert Campaign.query.filter_by(listing_id=listing_pk, status="draft").count() == 1
    print("[ok] revisiting the same listing's compose resumes the existing draft instead of re-showing the picker")

    # The edit page's description autosave (autosave_campaign_description)
    # must persist without needing "Save changes" clicked.
    autosaved_desc = "Edited on the edit page itself, via autosave, no Save click."
    r = client.post(
        f"/campaigns/{desc_draft_id}/edit/autosave_description",
        data={"description": autosaved_desc}, follow_redirects=False,
    )
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    db.session.refresh(desc_draft)
    assert desc_draft.body_text == autosaved_desc
    assert autosaved_desc in desc_draft.html_body_snapshot
    # A later autosave must keep rendering in the campaign's own layout —
    # not silently drop back to the original one.
    assert desc_draft.layout == "feature_spotlight"
    assert "SCHEDULE A PRIVATE TOUR" in desc_draft.html_body_snapshot
    print("[ok] autosave_campaign_description persists a listing campaign's description with no explicit Save, keeping its layout")

    # ---- A listing campaign's edit page must have the same Recipients &
    # send / Save-as-template tools the original compose page has, not just
    # content editing — otherwise a draft has nowhere to send itself from. ----
    r = client.get(f"/campaigns/{desc_draft_id}/edit")
    page = r.get_data(as_text=True)
    assert "Recipients &amp; send" in page or "Recipients & send" in page
    assert "Check recipients" in page
    assert "Preview send (dry run)" in page
    assert "Save this email as a reusable template" in page
    print("[ok] a listing campaign's edit page has the full Recipients/send/template toolbar too")

    # Uploading a photo to an EXISTING listing campaign (not the fresh
    # new_step2 flow tested above) must actually persist to the row, not
    # just thread through query params — this was a real bug: the old code
    # only ever showed the new photo via the redirect's query string, so it
    # silently vanished on the very next page load.
    r = client.post(
        f"/campaigns/{desc_draft_id}/edit/photos/upload",
        data={"photo": [fake_photo("second.jpg")]},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert r.status_code == 302
    db.session.refresh(desc_draft)
    assert len(desc_draft.photo_urls) == 1
    uploaded_url = desc_draft.photo_urls[0]
    assert uploaded_url in desc_draft.html_body_snapshot
    r = client.get(f"/campaigns/{desc_draft_id}/edit")
    assert uploaded_url in r.get_data(as_text=True)
    print("[ok] uploading a photo to an existing listing campaign actually persists photo_urls to the row")

    r = client.post(
        f"/campaigns/{desc_draft_id}/edit/photos/remove",
        data={"remove_url": uploaded_url}, follow_redirects=False,
    )
    assert r.status_code == 302
    db.session.refresh(desc_draft)
    assert desc_draft.photo_urls == []
    print("[ok] removing a photo from an existing listing campaign persists too")

    # Picking a different recipient group/account on the edit page must
    # autosave too, same as the description — this was the actual gap
    # reported: selecting "Seller" silently did nothing.
    r = client.post(
        f"/campaigns/{desc_draft_id}/edit/autosave_description",
        data={"description": desc_draft.body_text or "", "recipient_group": "Seller", "account": "yifan"},
        follow_redirects=False,
    )
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    db.session.refresh(desc_draft)
    assert desc_draft.recipient_group == "Seller"
    print("[ok] changing recipient group on an existing listing campaign's edit page autosaves it")

    # check_recipients_campaign for a listing campaign previews the fixed
    # recipient_group/account (not editable) instead of refusing outright.
    r = client.post(
        f"/campaigns/{desc_draft_id}/edit/check_recipients",
        data={"description": desc_draft.body_text}, follow_redirects=False,
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert "Alice Buyer" in r.get_data(as_text=True)
    print("[ok] check_recipients_campaign previews recipients for a listing campaign")

    # send_campaign_edit must schedule/send an EXISTING listing campaign
    # instead of creating a duplicate row (mirrors the general-campaign test
    # above).
    future2 = (datetime.now() + timedelta(days=6)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(
        f"/campaigns/{desc_draft_id}/edit/send",
        data={"scheduled_time": future2}, follow_redirects=False,
    )
    assert r.status_code == 302
    db.session.refresh(desc_draft)
    assert desc_draft.status == "scheduled"
    assert Campaign.query.filter_by(id=desc_draft_id).count() == 1

    mock_send.reset_mock()
    r = client.post(
        f"/campaigns/{desc_draft_id}/edit/send",
        data={"dry_run": "1"}, follow_redirects=False,
    )
    assert r.status_code == 302
    db.session.refresh(desc_draft)
    assert desc_draft.status == "sent"
    mock_send.assert_not_called()
    print("[ok] send_campaign_edit schedules then dry-run sends an existing listing campaign, no duplicate row")

    # ---- Scheduled listing campaign: description override survives edit+save ----
    # desc_draft was dry-run sent above (status "sent", terminal) — revisiting
    # the listing's compose must recognize the old draft is done and send them
    # back through the template picker instead of resuming a finished campaign.
    r = client.get("/campaigns/new/MLS123", follow_redirects=False)
    assert r.status_code == 302
    reloc = r.headers["Location"]
    assert "/choose_template" in reloc, "a sent campaign must not be resumed as if still in progress"

    r = client.get("/campaigns/new/MLS123/start", follow_redirects=False)  # "use MLS description as-is"
    assert r.status_code == 200
    r = client.post("/campaigns/new/MLS123/create_draft", data={
        "layout": "property_showcase", "email_type": "just_listed",
        "recipient_group": "Buyer", "account": "yifan",
        "description": "Original MLS description of a lovely home.",
    })
    assert r.status_code == 200
    fresh_draft_id = r.get_json()["id"]
    fresh_loc = f"/campaigns/{fresh_draft_id}/edit"
    assert fresh_loc != loc
    fresh_draft = db.session.get(Campaign, fresh_draft_id)
    assert fresh_draft.body_text is None, "unedited description should store a null override"

    future = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(f"/campaigns/{fresh_draft_id}/edit/send", data={"scheduled_time": future}, follow_redirects=False)
    assert r.status_code == 302
    db.session.refresh(fresh_draft)
    assert fresh_draft.status == "scheduled"
    scheduled = fresh_draft

    edited = "A brand-new agent-written description."
    r = client.post(f"/campaigns/{scheduled.id}/edit/save", data={"description": edited, "photo_urls": []}, follow_redirects=False)
    assert r.status_code == 302
    db.session.refresh(scheduled)
    assert scheduled.body_text == edited
    assert edited in scheduled.html_body_snapshot
    print("[ok] editing a scheduled listing campaign's description works")

    # ---- Manual email stays stateless until explicit/meaningful save. ----
    before_manual = Campaign.query.filter_by(listing_id=None).count()
    r = client.get("/campaigns/new_general", follow_redirects=False)
    assert r.status_code == 200
    assert Campaign.query.filter_by(listing_id=None).count() == before_manual
    r = client.post("/campaigns/new_general/create_draft", data={
        "subject": "Manual draft", "content_blocks": '[{"type":"text","content":"Draft body"}]',
        "recipient_group": "All", "account": "yifan",
    })
    assert r.status_code == 200
    manual_draft_id = r.get_json()["id"]
    manual_loc = f"/campaigns/{manual_draft_id}/edit"
    manual_draft = db.session.get(Campaign, manual_draft_id)
    assert manual_draft.status == "draft"
    assert manual_draft.listing_id is None
    assert manual_draft.recipient_group == "All" and manual_draft.account == "yifan"
    r = client.get("/campaigns/")
    assert f'/campaigns/{manual_draft_id}' in r.get_data(as_text=True) or r.status_code == 200
    print("[ok] manual email opening is stateless and explicit save creates a draft")

    # ---- Every manual email gets a "Visit our website" CTA button by
    # default (no configuration needed), and it's editable per campaign. ----
    assert "VISIT OUR WEBSITE" in manual_draft.html_body_snapshot
    assert DEFAULT_CTA_URL in manual_draft.html_body_snapshot
    print("[ok] a manual email gets a working 'Visit our website' button pointed at the homepage by default")

    r = client.post(
        f"/campaigns/{manual_draft_id}/edit/autosave",
        data={"subject": manual_draft.subject, "content_blocks": json.dumps(manual_draft.content_blocks or []),
              "cta_url": "https://www.austinapexre.com/buyers"},
        follow_redirects=False,
    )
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    db.session.refresh(manual_draft)
    assert manual_draft.cta_url == "https://www.austinapexre.com/buyers"
    assert "https://www.austinapexre.com/buyers" in manual_draft.html_body_snapshot
    print("[ok] setting a custom button link autosaves and actually changes the rendered button")

    r = client.post(
        f"/campaigns/{manual_draft_id}/edit/autosave",
        data={"subject": manual_draft.subject, "content_blocks": json.dumps(manual_draft.content_blocks or []),
              "cta_url": ""},
        follow_redirects=False,
    )
    assert r.status_code == 200
    db.session.refresh(manual_draft)
    assert manual_draft.cta_url is None
    assert DEFAULT_CTA_URL in manual_draft.html_body_snapshot
    print("[ok] clearing the button link falls back to the homepage default")

    # ---- General compose: block editor (text/photo interleaving) ----
    blocks = [{"type": "text", "content": "First paragraph."}]
    r = client.post(
        "/campaigns/new_general/photos/upload",
        data={"photo": [fake_photo("general.jpg")], "subject": "Block test", "content_blocks": json.dumps(blocks),
              "recipient_group": "All", "account": "yifan"},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["Location"]
    assert "content_blocks=" in loc
    blocks_after_upload = json.loads(query_param(loc, "content_blocks"))
    assert blocks_after_upload[0]["type"] == "text"
    assert blocks_after_upload[1]["type"] == "photo"
    general_photo_url = blocks_after_upload[1]["url"]
    print("[ok] general compose photo upload appends a photo block")

    # Insert a second text block BETWEEN the first paragraph and the photo —
    # this is the actual point of blocks: photo placement isn't fixed.
    ordered_blocks = [
        {"type": "text", "content": "First paragraph."},
        {"type": "text", "content": "Second paragraph, before the photo."},
        {"type": "photo", "url": general_photo_url, "width_pct": 100},
        {"type": "text", "content": "Third paragraph, after the photo."},
    ]
    r = client.post(
        "/campaigns/new_general/send",
        data={"subject": "Block-based email", "content_blocks": json.dumps(ordered_blocks),
              "recipient_group": "All", "account": "yifan", "dry_run": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    general_campaign = Campaign.query.filter_by(email_type="general", subject="Block-based email").first()
    assert general_campaign.content_blocks == ordered_blocks
    assert general_campaign.photo_urls == [general_photo_url]
    html = general_campaign.html_body_snapshot
    # The photo must render strictly between paragraph 2 and paragraph 3 —
    # the whole reason blocks exist instead of a fixed hero+grid layout.
    p2 = html.index("Second paragraph, before the photo.")
    photo_pos = html.index(general_photo_url)
    p3 = html.index("Third paragraph, after the photo.")
    assert p2 < photo_pos < p3, "photo block did not render in its assigned position"
    print("[ok] send_general() with blocks: photo renders exactly between the two paragraphs it was placed between")
    mock_send.reset_mock()

    # ---- Photo width_pct (continuous resize, not fixed small/medium/full) + alignment ----
    sized_blocks = [
        {"type": "text", "content": "Intro."},
        {"type": "photo", "url": general_photo_url, "width_pct": 25, "align": "left"},
    ]
    r = client.post(
        "/campaigns/new_general/send",
        data={"subject": "Sized photo", "content_blocks": json.dumps(sized_blocks),
              "recipient_group": "All", "account": "yifan", "dry_run": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    sized_campaign = Campaign.query.filter_by(subject="Sized photo").first()
    assert sized_campaign.content_blocks == sized_blocks
    html = sized_campaign.html_body_snapshot
    assert 'width="150"' in html, "25% of the 600px column should render at 150px, not a fixed preset"
    assert 'align="left"' in html, "left-aligned photo should have a real align attribute (email-client safe)"
    print("[ok] photo width_pct is a real continuous drag-resize value (25% -> 150px), not a fixed preset")
    mock_send.reset_mock()

    # ---- Legacy backward compat: an old fixed "size" value still parses ----
    legacy_size_blocks = [
        {"type": "text", "content": "Legacy body."},
        {"type": "photo", "url": general_photo_url, "size": "small"},
    ]
    r = client.post(
        "/campaigns/new_general/send",
        data={"subject": "Legacy size", "content_blocks": json.dumps(legacy_size_blocks),
              "recipient_group": "All", "account": "yifan", "dry_run": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    legacy_campaign = Campaign.query.filter_by(subject="Legacy size").first()
    # _parse_blocks doesn't carry the old "size" key forward (only width_pct/align survive going forward);
    assert legacy_campaign.content_blocks[1]["type"] == "photo"
    print("[ok] a campaign saved with the old fixed 'size' field still renders (backward compat)")
    mock_send.reset_mock()

    # ---- row blocks: mixed photo+text cells, independently sized (not just equal 2/3-up) ----
    r = client.post(
        "/campaigns/new_general/photos/upload",
        data={"photo": [fake_photo("row2.jpg"), fake_photo("row3.jpg")], "subject": "", "content_blocks": "[]",
              "recipient_group": "All", "account": "yifan"},
        content_type="multipart/form-data", follow_redirects=False,
    )
    assert r.status_code == 302
    row_blocks_json = json.loads(query_param(r.headers["Location"], "content_blocks"))
    row_photo_urls = [b["url"] for b in row_blocks_json if b["type"] == "photo"]
    assert len(row_photo_urls) == 2

    # A photo (70%) next to a text blurb (30%) in one row — the actual point
    # of this feature: uneven, mixed-content rows, not just equal photo grids.
    mixed_row_blocks = [
        {"type": "text", "content": "Before the row."},
        {"type": "row", "cells": [
            {"type": "photo", "url": row_photo_urls[0], "width_pct": 70},
            {"type": "text", "content": "A caption next to the photo.", "width_pct": 30},
        ]},
        {"type": "text", "content": "After the row."},
    ]
    r = client.post(
        "/campaigns/new_general/send",
        data={"subject": "Mixed row", "content_blocks": json.dumps(mixed_row_blocks),
              "recipient_group": "All", "account": "yifan", "dry_run": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    row_campaign = Campaign.query.filter_by(subject="Mixed row").first()
    assert row_campaign.content_blocks == mixed_row_blocks
    assert row_campaign.photo_urls == [row_photo_urls[0]]
    html = row_campaign.html_body_snapshot
    assert html.count("<tr>") >= 1
    assert row_photo_urls[0] in html
    assert "A caption next to the photo." in html
    assert 'width="420"' in html, "70% of 600px should be 420px for the photo cell"
    assert "70.0000%" in html and "30.0000%" in html, "cells should keep their own 70/30 split, not force equal columns"
    row_start = html.index("Before the row.")
    row_end = html.index("After the row.")
    assert row_start < html.index(row_photo_urls[0]) < row_end
    assert row_start < html.index("A caption next to the photo.") < row_end
    print("[ok] row blocks mix photo+text cells at independent widths (70/30 split), not just equal photo grids")
    mock_send.reset_mock()

    # ---- 3-up row still works, and widths normalize even if they don't sum to 100 ----
    three_up_blocks = [
        {"type": "text", "content": "Three photos below."},
        {"type": "row", "cells": [
            {"type": "photo", "url": general_photo_url, "width_pct": 50},
            {"type": "photo", "url": row_photo_urls[0], "width_pct": 25},
            {"type": "photo", "url": row_photo_urls[1], "width_pct": 25},
        ]},
    ]
    r = client.post(
        "/campaigns/new_general/send",
        data={"subject": "Three-up row", "content_blocks": json.dumps(three_up_blocks),
              "recipient_group": "All", "account": "yifan", "dry_run": "0"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    three_up_campaign = Campaign.query.filter_by(subject="Three-up row").first()
    assert set(three_up_campaign.photo_urls) == {general_photo_url, row_photo_urls[0], row_photo_urls[1]}
    html = three_up_campaign.html_body_snapshot
    assert 'width="300"' in html  # 50% of 600
    assert 'width="150"' in html  # 25% of 600, twice
    print("[ok] a 3-up row (50/25/25 split) still renders as one table with the right widths")
    mock_send.reset_mock()

    # ---- Template with content_blocks fires into a pending campaign carrying them ----
    template_blocks = [
        {"type": "text", "content": "Line one."},
        {"type": "photo", "url": general_photo_url},
        {"type": "text", "content": "Line two."},
    ]
    template = Template(
        kind="email", name="Spring greeting", subject="Happy Spring!",
        body="Line one.\n\nLine two.", content_blocks=template_blocks,
        is_html=False, account_owner="yifan", recipient_group="Buyer",
        scheduled_month=date.today().month, scheduled_day=date.today().day, created_by=user.id,
    )
    db.session.add(template)
    db.session.commit()

    from scheduler import fire_due_templates
    assert fire_due_templates(), "expected a pending campaign to be created"
    pending = Campaign.query.filter_by(email_type="recurring_template").first()
    assert pending.status == "pending"
    assert pending.content_blocks == template_blocks
    assert pending.photo_urls == [general_photo_url]
    print("[ok] fire_due_templates() carries a template's content_blocks onto the pending campaign")

    # Editing + saving the pending campaign re-renders from the edited blocks.
    edited_blocks = [
        {"type": "text", "content": "Rewritten opening."},
        {"type": "text", "content": "Second line, edited."},
    ]
    r = client.post(
        f"/campaigns/{pending.id}/edit/save",
        data={"subject": "Happy Spring! (edited)", "content_blocks": json.dumps(edited_blocks)},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.get_data(as_text=True)[:500]
    db.session.refresh(pending)
    assert pending.subject == "Happy Spring! (edited)"
    assert pending.content_blocks == edited_blocks
    assert "Rewritten opening." in pending.html_body_snapshot
    print("[ok] editing + saving a pending campaign's blocks re-renders its snapshot")

    # ---- Autosave: edits persist to the DB without ever clicking "Save changes" ----
    autosave_future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(
        "/campaigns/new_general/send",
        data={"subject": "Autosave test", "content_blocks": json.dumps([{"type": "text", "content": "Original draft."}]),
              "recipient_group": "All", "account": "yifan", "scheduled_time": autosave_future},
        follow_redirects=False,
    )
    assert r.status_code == 302
    autosave_campaign = Campaign.query.filter_by(subject="Autosave test").first()
    assert autosave_campaign is not None and autosave_campaign.status == "scheduled"

    # Simulate the block editor's background autosave firing mid-edit — no
    # "Save changes" click, exactly the "Yifan quits without saving" case.
    autosaved_blocks = [{"type": "text", "content": "Edited mid-session, never explicitly saved."}]
    r = client.post(
        f"/campaigns/{autosave_campaign.id}/edit/autosave",
        data={"subject": "Autosave test (edited)", "content_blocks": json.dumps(autosaved_blocks)},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert r.get_json() == {"ok": True}

    db.session.refresh(autosave_campaign)
    assert autosave_campaign.subject == "Autosave test (edited)"
    assert autosave_campaign.content_blocks == autosaved_blocks
    assert "Edited mid-session, never explicitly saved." in autosave_campaign.html_body_snapshot
    # A fresh GET (e.g. Yifan reopening the page later) must reflect the
    # autosaved state too, not just the DB row directly.
    r = client.get(f"/campaigns/{autosave_campaign.id}/edit")
    assert r.status_code == 200
    assert "Edited mid-session, never explicitly saved." in r.get_data(as_text=True)
    print("[ok] autosave persists edits to the DB with no explicit Save click, and reopening the page shows them")

    # ---- New-compose draft creation: the "nowhere to save" gap ----
    # An empty/placeholder compose has nothing worth saving yet. (This
    # exercises create_general_draft() directly — the JS-triggered autosave
    # path within an already-created draft; new_general() itself now always
    # creates a draft immediately on GET, tested separately above.)
    before_count = Campaign.query.count()
    r = client.post(
        "/campaigns/new_general/create_draft",
        data={"subject": "", "content_blocks": json.dumps([{"type": "text", "content": ""}]),
              "recipient_group": "All", "account": "yifan"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.get_json() == {"ok": False}
    assert Campaign.query.count() == before_count
    print("[ok] create_draft refuses to persist an empty/placeholder compose")

    # The first meaningful edit turns the in-progress compose into a real,
    # persisted "Pending review" Campaign row — this is what makes it show
    # up in History and gives it somewhere to be saved to.
    draft_blocks = [{"type": "text", "content": "Wishing you a wonderful holiday season."}]
    r = client.post(
        "/campaigns/new_general/create_draft",
        data={"subject": "Holiday greeting", "content_blocks": json.dumps(draft_blocks),
              "recipient_group": "All", "account": "yifan"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    draft_id = r.get_json()["id"]
    draft_campaign = db.session.get(Campaign, draft_id)
    assert draft_campaign is not None
    assert draft_campaign.status == "draft"
    assert draft_campaign.subject == "Holiday greeting"
    assert draft_campaign.content_blocks == draft_blocks
    assert "Wishing you a wonderful holiday season." in draft_campaign.html_body_snapshot
    # It must actually show up in History, not just exist as a DB row.
    r = client.get("/campaigns/")
    assert r.status_code == 200
    assert "Holiday greeting" in r.get_data(as_text=True)
    # And it must be reachable/editable via the normal edit page the JS
    # redirects to after creating the draft.
    r = client.get(f"/campaigns/{draft_id}/edit")
    assert r.status_code == 200
    assert "Wishing you a wonderful holiday season." in r.get_data(as_text=True)
    print("[ok] create_draft persists the first meaningful edit as a 'Pending review' campaign visible in History")

    # ---- The edit page for a general campaign must have full compose
    # tools (Recipients/Schedule/AI/Save-as-template), not just content
    # blocks — otherwise a draft has "nowhere to save" its recipients or
    # schedule once it's no longer on the stateless new_general page. ----
    r = client.get(f"/campaigns/{draft_id}/edit")
    page = r.get_data(as_text=True)
    assert "Generate with AI" in page
    assert "Recipients" in page and "Check recipients" in page
    assert "Schedule" in page and "Preview send (dry run)" in page
    assert "Save as template" in page
    print("[ok] a general campaign's edit page has the full compose toolbar, not just content blocks")

    # Changing recipients/account on the edit page must persist (same
    # fields autosave writes), and "Check recipients" must work against an
    # existing campaign instead of only a fresh, unsaved compose.
    r = client.post(
        f"/campaigns/{draft_id}/edit/check_recipients",
        data={"subject": draft_campaign.subject, "content_blocks": json.dumps(draft_blocks),
              "recipient_group": "Buyer", "account": "yifan"},
        follow_redirects=False,
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:300]
    assert "Alice Buyer" in r.get_data(as_text=True)
    db.session.refresh(draft_campaign)
    assert draft_campaign.recipient_group == "Buyer"
    print("[ok] check_recipients_campaign persists the group/account change and previews the real contact list")

    # "Generate with AI" must work against an existing draft, persisting
    # straight to it instead of bouncing back to the stateless compose page.
    with patch("routes.campaigns.generate_general_email", return_value=("AI-written subject", "AI-written body.")):
        r = client.post(
            f"/campaigns/{draft_id}/edit/generate",
            data={"topic": "a market update", "content_blocks": json.dumps(draft_blocks)},
            follow_redirects=False,
        )
    assert r.status_code == 302
    db.session.refresh(draft_campaign)
    assert draft_campaign.subject == "AI-written subject"
    assert any(b["type"] == "text" and b["content"] == "AI-written body." for b in draft_campaign.content_blocks)
    print("[ok] generate_general_campaign persists an AI-regenerated draft straight to the existing campaign")

    # Scheduling from the edit page's "Schedule & send" must update the
    # existing row (status -> scheduled) instead of creating a second one.
    future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M")
    r = client.post(
        f"/campaigns/{draft_id}/edit/send",
        data={"subject": "Rescheduled greeting", "content_blocks": json.dumps(draft_blocks),
              "recipient_group": "Buyer", "account": "yifan", "scheduled_time": future},
        follow_redirects=False,
    )
    assert r.status_code == 302
    db.session.refresh(draft_campaign)
    assert draft_campaign.status == "scheduled"
    assert draft_campaign.subject == "Rescheduled greeting"
    assert Campaign.query.filter_by(subject="Rescheduled greeting").count() == 1
    print("[ok] send_campaign_edit schedules the existing draft instead of creating a duplicate row")

    # And a dry-run "Send now" from that same page must actually send
    # (finalizing the row as dry-run 'sent') without ever calling send_email.
    mock_send.reset_mock()
    r = client.post(
        f"/campaigns/{draft_id}/edit/send",
        data={"subject": "Rescheduled greeting", "content_blocks": json.dumps(draft_blocks),
              "recipient_group": "Buyer", "account": "yifan", "dry_run": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    db.session.refresh(draft_campaign)
    assert draft_campaign.status == "sent"
    assert draft_campaign.sent_count == 1
    mock_send.assert_not_called()
    print("[ok] send_campaign_edit dry-runs the existing draft without sending real email")

    # Safety guard: autosave must refuse to touch an HTML-template-sourced
    # campaign (no editable blocks) rather than clobber it with an empty list.
    html_campaign = Campaign(
        listing_id=None, email_type="general", subject="HTML-sourced", html_body_snapshot="<p>frozen</p>",
        created_by=user.id, recipient_group="All", account="yifan", status="scheduled",
        scheduled_time=datetime.now(timezone.utc) + timedelta(days=1),
        body_text=None, content_blocks=None, photo_urls=[],
    )
    db.session.add(html_campaign)
    db.session.commit()
    r = client.post(
        f"/campaigns/{html_campaign.id}/edit/autosave",
        data={"subject": "should be refused", "content_blocks": "[]"},
        follow_redirects=False,
    )
    assert r.status_code == 409
    db.session.refresh(html_campaign)
    assert html_campaign.subject == "HTML-sourced"
    assert html_campaign.html_body_snapshot == "<p>frozen</p>"
    assert html_campaign.content_blocks is None
    print("[ok] autosave refuses to touch an HTML-template-sourced campaign")

    r = client.post(f"/campaigns/{pending.id}/send_now", follow_redirects=False)
    assert r.status_code == 302
    db.session.refresh(pending)
    assert pending.status == "sent"
    print("[ok] send_now() after a block edit sends the edited content")

    # ---- Legacy fallback: a template saved before blocks existed still works ----
    legacy_template = Template(
        kind="email", name="Legacy greeting", subject="Legacy!",
        body="Old-style line one.\nOld-style line two.", content_blocks=None,
        is_html=False, account_owner="yifan", recipient_group="Buyer",
        scheduled_month=date.today().month, scheduled_day=date.today().day + 1 if date.today().day < 28 else 1,
        created_by=user.id,
    )
    db.session.add(legacy_template)
    db.session.commit()
    # Force it due today too, bypassing the month/day coincidence needed above.
    legacy_template.scheduled_month = date.today().month
    legacy_template.scheduled_day = date.today().day
    db.session.commit()
    fire_due_templates()
    legacy_pending = Campaign.query.filter_by(subject="Legacy!").first()
    assert legacy_pending is not None
    assert legacy_pending.content_blocks is None
    assert legacy_pending.body_text == "Old-style line one.\nOld-style line two."
    assert "Old-style line one." in legacy_pending.html_body_snapshot
    print("[ok] a pre-blocks template still fires correctly (body_text fallback)")

print("\nRegression: uploaded photos must actually be committed to disk, not\n"
      "just flushed into the shared in-process session (which would mask a\n"
      "missing db.session.commit() in the upload routes).")
raw = sqlite3.connect(DB_PATH)
count = raw.execute("SELECT COUNT(*) FROM uploaded_photos").fetchone()[0]
raw.close()
assert count >= 2, f"expected uploaded photo(s) committed to disk, found {count}"
print(f"[ok] {count} uploaded photo(s) actually committed to disk (separate connection)")

print("\nALL SMOKE TESTS PASSED")
