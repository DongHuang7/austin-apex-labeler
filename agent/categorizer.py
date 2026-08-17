import json
import re
import time
import anthropic
from contacts.gmail_contacts import fetch_all_contacts, apply_labels_bulk, fetch_email_snippets, check_keyword_in_emails

BATCH_SIZE = 10

# Use Haiku for categorization (cheap, fast, accurate enough)
# Use Sonnet for email content generation (better writing quality)
MODEL_CATEGORIZE = "claude-haiku-4-5-20251001"
MODEL_EMAIL = "claude-sonnet-4-6"

client = anthropic.Anthropic()


def _categories_file(account: str) -> str:
    return f"categories_{account}.json"


def _load_progress(account: str) -> dict:
    """Load previously saved progress keyed by email address."""
    path = _categories_file(account)
    try:
        with open(path) as f:
            data = json.load(f)
        # Support both list format (old) and dict format (new checkpoint)
        if isinstance(data, list):
            return {c["email"]: c for c in data if c.get("category")}
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_progress(account: str, progress: dict):
    """Save current progress dict to disk."""
    with open(_categories_file(account), "w") as f:
        json.dump(progress, f, indent=2)


def _has_post_closing_keyword(email_content: str) -> bool:
    """Rule 1: post-closing or post closing keywords → Buyer."""
    return bool(re.search(r"post.?closing", email_content, re.IGNORECASE))


def _looks_like_promotion(email_content: str) -> bool:
    """Rule 2: promotional/listing content → Broker."""
    promo_keywords = [
        "just listed", "just sold", "open house", "price reduced",
        "new listing", "featured listing", "property flyer", "listing flyer",
        "co-broke", "co-op", "commission", "mls#", "mls #",
        "beds", "baths", "sq ft", "sqft", "square feet",
        "call for showing", "showing instructions", "coming soon",
    ]
    content_lower = email_content.lower()
    matches = sum(1 for kw in promo_keywords if kw in content_lower)
    return matches >= 2


def categorize_contacts(account: str = "default"):
    """
    Fetch contacts, pull email history, and categorize using rules + Claude.
    Supports checkpoint/resume — safe to re-run if interrupted.
    """
    contacts = fetch_all_contacts(account)
    if not contacts:
        print("No contacts found.")
        return []

    # Load any previous progress
    progress = _load_progress(account)
    already_done = len([c for c in contacts if c["email"] in progress])
    print(f"\n{len(contacts)} contacts total — {already_done} already categorized, {len(contacts) - already_done} remaining.\n")

    for i, contact in enumerate(contacts, 1):
        email = contact["email"]

        # Resume: skip if already categorized
        if email in progress:
            contact.update(progress[email])
            continue

        print(f"  [{i}/{len(contacts)}] {contact['name'] or email}...", end=" ", flush=True)

        # Rule 1: Gmail search for post-closing keyword
        try:
            if check_keyword_in_emails(email, '"post-closing" OR "post closing"', account):
                contact["category"] = "Buyer"
                contact["reason"] = "Email history contains post-closing keyword"
                contact["email_content"] = ""
                print("→ Buyer (post-closing)")
                progress[email] = contact
                _save_progress(account, progress)
                time.sleep(0.3)
                continue
        except Exception as e:
            print(f"→ (Gmail search error: {e})")

        # Fetch recent email snippets
        try:
            email_content = fetch_email_snippets(email, max_messages=10, account=account)
            contact["email_content"] = email_content
            time.sleep(0.3)
        except Exception as e:
            email_content = ""
            contact["email_content"] = ""

        # Rule 2: promotional content → Broker
        if email_content and _looks_like_promotion(email_content):
            contact["category"] = "Broker"
            contact["reason"] = "Email contains promotional/listing content"
            print("→ Broker (promo)")
            progress[email] = contact
            _save_progress(account, progress)
            continue

        # Needs Claude
        contact["category"] = None
        print("→ queued for Claude")

    # Collect contacts that still need Claude
    needs_claude = [c for c in contacts if c.get("category") is None]
    print(f"\nSending {len(needs_claude)} contacts to Claude for categorization...")

    for i in range(0, len(needs_claude), BATCH_SIZE):
        batch = needs_claude[i:i + BATCH_SIZE]
        print(f"  Batch {i // BATCH_SIZE + 1}: contacts {i + 1}–{i + len(batch)}...")
        _categorize_batch_with_claude(batch)

        # Save after each batch
        for c in batch:
            progress[c["email"]] = c
        _save_progress(account, progress)

    print(f"\nCategories saved to {_categories_file(account)}")
    return contacts


def _categorize_batch_with_claude(batch):
    """Send a batch to Claude with email context included."""
    contact_list = "\n\n".join([
        f"Contact {i + 1}:\n"
        f"  Name: {c['name']}\n"
        f"  Email: {c['email']}\n"
        f"  Job Title: {c['job_title']}\n"
        f"  Company: {c['company']}\n"
        f"  Recent emails:\n{c.get('email_content', 'No email history') or 'No email history'}"
        for i, c in enumerate(batch)
    ])

    response = client.messages.create(
        model=MODEL_CATEGORIZE,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""You are a real estate assistant helping categorize contacts for a real estate agent.

Categorize each contact into one of these groups:
- Buyer: Someone looking to purchase property. Clues: asking about homes, neighborhoods, prices, school districts, scheduling tours.
- Seller: Someone looking to sell their property. Clues: asking about home value, listing process, what their home is worth.
- Broker: A real estate agent, broker, or industry professional. Clues: agent language, referencing MLS, showings, co-op, listings, commission.
- Other: Anyone who doesn't fit the above.

Use job title, company, AND email content to decide. If unsure, use "Other".

Return ONLY a valid JSON array, no explanation:
[
  {{"index": 1, "name": "...", "email": "...", "category": "Buyer/Seller/Broker/Other", "reason": "brief reason"}},
  ...
]

Contacts:
{contact_list}""",
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    results = json.loads(raw.strip())
    for item in results:
        idx = item["index"] - 1
        batch[idx]["category"] = item["category"]
        batch[idx]["reason"] = item["reason"]


def review_and_apply(categorized_contacts, account: str = "default"):
    """Show categorization results, let user review, then apply labels."""
    print("\n" + "=" * 60)
    print("CATEGORIZATION RESULTS — Please review:")
    print("=" * 60)

    categories = {"Buyer": [], "Seller": [], "Broker": [], "Other": []}
    for c in categorized_contacts:
        cat = c.get("category", "Other")
        categories[cat].append(c)

    for cat, members in categories.items():
        print(f"\n{cat.upper()}S ({len(members)}):")
        for m in members:
            print(f"  - {m['name'] or m['email']} <{m['email']}> | {m.get('reason', '')}")

    print("\n" + "=" * 60)
    confirm = input("Apply these labels to Google Contacts? (yes/no): ").strip().lower()

    if confirm != "yes":
        print("Cancelled. No labels applied.")
        return

    print("\nApplying labels in bulk...")
    contacts_by_label = {"Buyer": [], "Seller": [], "Broker": [], "Other": []}
    for c in categorized_contacts:
        cat = c.get("category", "Other")
        contacts_by_label[cat].append(c)

    apply_labels_bulk(contacts_by_label, account=account)
    print("\nDone! All labels applied to Google Contacts.")
