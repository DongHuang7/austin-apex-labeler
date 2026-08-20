"""
Draft a social media caption for a listing. Mirrors scan_helpers.py's
pattern (one Claude call, simple parsing) but uses Sonnet instead of Haiku
for writing quality, matching agent/categorizer.py's existing MODEL_EMAIL
convention for content generation vs. cheap classification.

The draft is never posted directly — routes/social.py always saves it as
SocialPost.draft_caption for a human to edit before approval, same
review-and-approve pattern as the contact review inbox.
"""
import anthropic

MODEL_CAPTION = "claude-sonnet-4-6"

client = anthropic.Anthropic()

PLATFORM_GUIDANCE = {
    "facebook_page": "Friendly and informative, 2-4 short paragraphs, light use of emojis is fine. "
                      "End with a call to action to reach out or view the listing.",
    "instagram_business": "Short, punchy, visual-first. A few lines max, emojis welcome, "
                           "end with 3-6 relevant real estate hashtags on their own line.",
    "linkedin_member": "Professional tone, no emojis, positions the agent as a knowledgeable "
                        "local expert. 2-3 short paragraphs.",
    "linkedin_org": "Professional tone, no emojis, written as the brokerage (not an individual agent). "
                     "2-3 short paragraphs.",
}

PROMPT_TEMPLATE = """You are a real estate marketing assistant writing a social media caption for a listing.

Platform: {platform}
Style guidance: {guidance}

Listing details:
Address: {address}, {city}, {state} {zipcode}
Price: {price}
Beds: {beds} | Baths: {baths} | Sqft: {sqft}
Description: {description}

Write ONLY the caption text, nothing else — no preamble, no quotes around it, no explanation."""


def generate_caption(listing: dict, platform: str) -> str:
    guidance = PLATFORM_GUIDANCE.get(platform, PLATFORM_GUIDANCE["facebook_page"])

    price = listing.get("ListPrice", 0)
    prompt = PROMPT_TEMPLATE.format(
        platform=platform,
        guidance=guidance,
        address=listing.get("UnparsedAddress", "").strip(),
        city=listing.get("City", ""),
        state=listing.get("StateOrProvince", "TX"),
        zipcode=listing.get("PostalCode", ""),
        price=f"${price:,.0f}" if price else "Contact for pricing",
        beds=listing.get("BedroomsTotal", "N/A"),
        baths=listing.get("BathroomsTotalInteger", "N/A"),
        sqft=listing.get("LivingArea", "N/A"),
        description=listing.get("PublicRemarks", ""),
    )

    response = client.messages.create(
        model=MODEL_CAPTION,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


EMAIL_PROMPT_TEMPLATE = """You are a real estate marketing assistant writing a marketing email \
for a local real estate brokerage. This email is NOT about a specific listing \
— it's a general email such as a holiday/festival greeting, a market update, \
or a community announcement.

What the email should be about: {topic}

Respond in EXACTLY this format, nothing else:

Subject: <the subject line>

<the email body, as plain text paragraphs separated by blank lines — no \
subject line repeated, no signature, no preamble>"""


def generate_general_email(topic: str) -> tuple:
    """Drafts a (subject, body) pair for a non-listing marketing email
    (festival post, announcement, etc.) — the campaigns.py equivalent of
    generate_general_caption() above. Body is plain text paragraphs, matching
    what campaigns_new_general.html's body textarea expects."""
    prompt = EMAIL_PROMPT_TEMPLATE.format(topic=topic)

    response = client.messages.create(
        model=MODEL_CAPTION,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()

    subject = ""
    body = text
    if text.lower().startswith("subject:"):
        first_line, _, rest = text.partition("\n")
        subject = first_line.split(":", 1)[1].strip()
        body = rest.strip()

    return subject, body


GENERAL_PROMPT_TEMPLATE = """You are a real estate marketing assistant writing a social media caption \
for a local real estate brokerage. This post is NOT about a specific listing \
— it's a general post such as a holiday/festival greeting, a market update, \
or a community announcement.

Platform: {platform}
Style guidance: {guidance}

What the post should be about: {topic}

Write ONLY the caption text, nothing else — no preamble, no quotes around it, no explanation."""


def generate_general_caption(topic: str, platform: str) -> str:
    """Same platform-specific style guidance as generate_caption(), but for
    posts with no listing behind them (festival posts, announcements, etc.)."""
    guidance = PLATFORM_GUIDANCE.get(platform, PLATFORM_GUIDANCE["facebook_page"])

    prompt = GENERAL_PROMPT_TEMPLATE.format(platform=platform, guidance=guidance, topic=topic)

    response = client.messages.create(
        model=MODEL_CAPTION,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
