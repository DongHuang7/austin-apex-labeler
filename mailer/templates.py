from html import escape
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from mailer._icons import LOGO_B64, LINKEDIN_ICON_B64, INSTAGRAM_ICON_B64

AGENTS = {
    "yifan": {
        "name": "Yifan Ingle",
        "title": "Broker | Realtor®",
        "brokerage": "Austin Apex Real Estate",
        "phone": "(512) 698-5979",
        "email": "yifan@austinapexre.com",
        "photo": "https://media-production.lp-cdn.com/cdn-cgi/image/format=auto,quality=85,fit=scale-down,width=960/https://media-production.lp-cdn.com/media/3c9c2639-6d9d-4e81-98d4-aed163280c73",
        "linkedin": "https://www.linkedin.com/in/yifan-ingle-8b5182127/",
        "instagram": "https://www.instagram.com/yifaninaustin/",
    },
    "anthony": {
        "name": "Anthony Liu",
        "title": "Realtor®",
        "brokerage": "Austin Apex Real Estate",
        "phone": "(512) 578-8959",
        "email": "anthony@austinapexre.com",
        "photo": "https://media-production.lp-cdn.com/cdn-cgi/image/format=auto,quality=85,fit=scale-down,width=960/https://media-production.lp-cdn.com/media/af714aad-2846-4b2d-9a0c-b20636529114",
        "linkedin": "https://www.linkedin.com/in/shenjun-liu-austinagent/",
        "instagram": "https://www.instagram.com/anthonyl_atxrealtor",
    },
    "sienna": {
        "name": "Sienna Xie",
        "title": "Realtor®",
        "brokerage": "Austin Apex Real Estate",
        "phone": "(480) 319-5858",
        "email": "sienna@austinapexre.com",
        "photo": "https://media-production.lp-cdn.com/cdn-cgi/image/format=auto,quality=85,fit=scale-down,width=960/https://media-production.lp-cdn.com/media/ac054f52-2282-4d14-abe8-5d951e9301ad",
        "linkedin": None,
        "instagram": None,
    },
    "vicky": {
        "name": "Vicky Hao",
        "title": "Realtor®",
        "brokerage": "Austin Apex Real Estate",
        "phone": "(512) 502-2689",
        "email": "vicky@austinapexre.com",
        "photo": "https://media-production.lp-cdn.com/cdn-cgi/image/format=auto,quality=85,fit=scale-down,width=960/https://media-production.lp-cdn.com/media/54b8f687-e7c8-4d1f-a16e-2f140f494fd0",
        "linkedin": None,
        "instagram": None,
    },
}

DISCLAIMER = (
    "Austin Apex Real Estate is a licensed real estate broker. All material is intended for "
    "informational purposes only and is compiled from sources deemed reliable but is subject to "
    "errors, omissions, changes in price, condition, sale, or withdrawal without notice. "
    "No statement is made as to the accuracy of any description or measurements (including "
    "square footage). This is not intended to solicit property already listed. No financial or "
    "legal advice provided. Equal Housing Opportunity. Photos may be virtually staged or "
    "digitally enhanced and may not reflect actual property conditions."
)

EMAIL_TYPES = {
    "just_listed":       "JUST LISTED",
    "active_selling":    "ACTIVE SELLING",
    "price_improvement": "PRICE IMPROVEMENT",
    "open_house":        "OPEN HOUSE",
    "just_sold":         "JUST SOLD",
    "coming_soon":       "COMING SOON",
    "in_escrow":         "IN ESCROW",
}



def _get_agent(listing_agent_email: str, override_email: str = None) -> dict:
    """Pick the right agent profile based on MLS agent email or override."""
    check = (override_email or listing_agent_email or "").lower()
    if "yifan" in check:
        return AGENTS["yifan"]
    if "anthony" in check:
        return AGENTS["anthony"]
    if "sienna" in check or "sixiang" in check:
        return AGENTS["sienna"]
    if "vicky" in check:
        return AGENTS["vicky"]
    return AGENTS["yifan"]  # default


def _photo_grid_html(photo_urls: list) -> str:
    if not photo_urls:
        return ""
    photos = photo_urls[1:5]
    rows = ""
    for i in range(0, len(photos), 2):
        pair = photos[i:i+2]
        tds = "".join(
            f'<td style="padding:4px;width:50%;"><img src="{url}" alt="Property photograph" style="width:100%;height:auto;display:block;border-radius:4px;" /></td>'
            for url in pair
        )
        rows += f"<tr>{tds}</tr>"
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0;">{rows}</table>'


COLUMN_PX = 600  # the email body's fixed column width everything else sizes against
LEGACY_SIZE_PCT = {"small": 33, "medium": 58, "full": 100}


def _photo_width_pct(block: dict) -> int:
    """A photo's width as a percent of the 600px column — continuous
    (dragged by the user in the editor), not the old fixed small/medium/full
    steps. Falls back to converting an old `size` value for anything saved
    before this existed."""
    if isinstance(block.get("width_pct"), (int, float)):
        return max(5, min(100, int(block["width_pct"])))
    return LEGACY_SIZE_PCT.get(block.get("size"), 100)


def _photo_block_html(block: dict) -> str:
    """Renders one standalone photo block at its chosen width/alignment.
    100% always fills the column, centered, same as the old "full" size.
    Anything narrower is wrapped in a table cell with a real `align`
    attribute rather than CSS float/margin tricks — most email clients
    strip float, but table alignment is universally respected."""
    url = block["url"]
    width_pct = _photo_width_pct(block)
    align = block.get("align") if block.get("align") in ("left", "center", "right") else "center"
    px = round(COLUMN_PX * width_pct / 100)

    if width_pct >= 98:
        return (
            f'<img src="{url}" width="{px}" '
            'alt="Property photograph" style="width:100%;height:auto;display:block;border-radius:6px;margin:20px 0;" />'
        )
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;"><tr>'
        f'<td align="{align}">'
        f'<img src="{url}" width="{px}" style="width:{px}px;max-width:100%;display:inline-block;border-radius:6px;" />'
        f'</td></tr></table>'
    )


def _row_cells(block: dict) -> list:
    """Canonical cell list for a row block — accepts the current
    {"cells": [{"type": "photo"|"text", ..., "width_pct": int}]} shape, and
    the older {"photos": [url, ...]} shape (equal-width photo-only rows,
    saved before mixed/resizable rows existed)."""
    if block.get("cells"):
        return block["cells"]
    photos = block.get("photos") or []
    n = len(photos) or 1
    return [{"type": "photo", "url": u, "width_pct": 100 / n} for u in photos]


def _row_html(block: dict) -> str:
    """2-3 items (photo or text, any mix) side by side in one row, each at
    its own independently-set width — a real <table> row so the layout
    survives email clients that strip flex/grid. Column widths are
    normalized to sum to 100% regardless of what the raw width_pct values
    add up to, so the editor's independent per-item resize handles never
    have to fight each other to keep an exact total."""
    cells = [
        c for c in _row_cells(block)
        if isinstance(c, dict) and (
            (c.get("type") == "photo" and c.get("url")) or (c.get("type") == "text" and c.get("content", "").strip())
        )
    ][:3]
    if not cells:
        return ""
    if len(cells) == 1:
        c = cells[0]
        if c["type"] == "photo":
            return _photo_block_html(c)
        return "".join(f'<p style="margin:0 0 16px;">{line}</p>' for line in c["content"].splitlines() if line.strip())

    raw_widths = [max(5, float(c.get("width_pct") or (100 / len(cells)))) for c in cells]
    total = sum(raw_widths) or 1
    tds = []
    for cell, raw in zip(cells, raw_widths):
        pct = raw / total * 100
        px = round(COLUMN_PX * pct / 100)
        if cell["type"] == "photo":
            inner = f'<img src="{cell["url"]}" width="{px}" alt="Property photograph" style="width:100%;height:auto;display:block;border-radius:4px;" />'
        else:
            inner = "".join(f'<p style="margin:0 0 8px;">{line}</p>' for line in cell["content"].splitlines() if line.strip())
        tds.append(f'<td style="padding:4px;width:{pct:.4f}%;vertical-align:top;">{inner}</td>')
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;"><tr>{"".join(tds)}</tr></table>'


def _blocks_html(blocks: list) -> str:
    """Renders an ordered list of {"type": "text"|"photo"|"row", ...}
    blocks into the email body's inner HTML — a text block becomes one <p>
    per line, a photo block becomes an image at its own dragged
    width/alignment, a row block becomes 2-3 items (photo or text, any mix)
    side by side each at its own independently-set width — so content can
    be placed and sized anywhere in the copy (between two paragraphs, at
    the top, at the bottom) instead of only ever at a fixed header/grid
    position. "photo_row" (the old photos-only equal-width row) still
    renders correctly via _row_html's backward-compatible cell reading."""
    parts = []
    for block in blocks or []:
        if block.get("type") == "photo" and block.get("url"):
            parts.append(_photo_block_html(block))
        elif block.get("type") in ("row", "photo_row"):
            parts.append(_row_html(block))
        elif block.get("type") == "text":
            content = block.get("content", "")
            paragraphs = "".join(
                f'<p style="margin:0 0 16px;">{line}</p>'
                for line in content.splitlines() if line.strip()
            )
            if paragraphs:
                parts.append(paragraphs)
    return "".join(parts)


DEFAULT_CTA_URL = "https://www.austinapexre.com"


def build_general_email(
    subject: str,
    body_html: str = "",
    photo_urls: list = None,
    agent_email: str = None,
    cta_url: str = None,
    blocks: list = None,
) -> tuple:
    """
    Build a listing-agnostic email (festival post, announcement, etc.) using
    the same branded header/footer/agent-signature shell as
    build_listing_email, but with a free-text subject/body instead of
    listing fields. Returns (subject, html_body).

    `blocks`, when given, is an ordered list of {"type": "text", "content":
    str} / {"type": "photo", "url": str} dicts — the block-based composer
    (routes/campaigns.py's new_general()/edit_campaign()) — and takes over
    the whole body area, photos included, instead of the older fixed
    hero-image-then-photo-grid layout driven by `body_html`/`photo_urls`.
    Kept as separate params (not folded into one) so campaigns saved before
    this feature existed keep rendering exactly as before.

    `cta_url`, when given, is where the "VISIT OUR WEBSITE" button below the
    body sends the reader — editable per campaign (see Campaign.cta_url),
    falling back to DEFAULT_CTA_URL (the site homepage) when left blank, so
    every manual email gets a working call-to-action button by default
    without Yifan/Anthony needing to set anything.
    """
    agent = _get_agent("", agent_email)
    phone = agent["phone"]

    hero_img = ""
    grid_html = ""
    if blocks:
        body_html = _blocks_html(blocks)
    elif photo_urls:
        hero_img = f'<img src="{photo_urls[0]}" width="600" alt="Property photograph" style="width:100%;height:auto;display:block;border-radius:6px;margin-bottom:32px;" />'
        grid_html = _photo_grid_html(photo_urls)

    property_button = _cta_button_html(cta_url or DEFAULT_CTA_URL, "VISIT OUR WEBSITE")

    _social_cells = ""
    if agent.get("linkedin"):
        _social_cells += f'<td style="padding-right:13px;"><a href="{agent["linkedin"]}" style="display:block;line-height:0;"><img src="{LINKEDIN_ICON_B64}" width="22" height="22" style="display:block;width:22px;height:22px;" /></a></td>'
    if agent.get("instagram"):
        _social_cells += f'<td><a href="{agent["instagram"]}" style="display:block;line-height:0;"><img src="{INSTAGRAM_ICON_B64}" width="22" height="22" style="display:block;width:22px;height:22px;" /></a></td>'
    social_icons = f'<table cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr>{_social_cells}</tr></table>' if _social_cells else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <style>@media only screen and (max-width:620px) {{
    .email-content {{ padding:24px 20px !important; }}
    h1 {{ font-size:28px !important; letter-spacing:1px !important; }}
  }}</style>
  <title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f9f9f9;font-family:Georgia,serif;">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{escape(subject)}</div>
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f9f9f9">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;table-layout:fixed;background:#ffffff;border-radius:8px;overflow:hidden;">

        <!-- HEADER: Logo left, Brokerage Name centered -->
        <tr>
          <td style="background:#264653;padding:24px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="60" style="vertical-align:middle;">
                  <img src="{LOGO_B64}" width="60" height="54" style="display:block;width:60px;height:54px;" />
                </td>
                <td style="vertical-align:middle;text-align:center;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:18px;font-weight:bold;letter-spacing:2px;color:#ffffff;">
                    AUSTIN APEX REAL ESTATE
                  </p>
                </td>
                <td width="60"></td>
              </tr>
            </table>
          </td>
        </tr>

        <tr><td class="email-content" style="padding:32px 40px;">

          <!-- HERO IMAGE -->
          {hero_img}

          <!-- BODY -->
          <div style="font-family:Georgia,serif;font-size:15px;line-height:1.8;color:#333;margin:0 0 24px;">
            {body_html}
          </div>

          <!-- CTA BUTTON -->
          {property_button}

          <!-- PHOTO GRID -->
          {grid_html}

          <!-- REACH OUT -->
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:14px;color:#555;margin:24px 0 40px;">
            <a href="mailto:{agent['email']}" style="color:#1a1a1a;text-decoration:none;border-bottom:1px solid #1a1a1a;padding-bottom:2px;">
              Reach out for more info
            </a>
          </p>

          <hr style="border:none;border-top:1px solid #e0e0e0;margin:0 0 28px;" />

          <!-- AGENT SIGNATURE -->
          <table cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
            <tr>
              <td style="padding-right:24px;vertical-align:top;">
                <img src="{agent['photo']}" width="110" height="140"
                     style="display:block;object-fit:cover;object-position:center center;width:110px;height:140px;" />
              </td>
              <td style="vertical-align:top;">
                <p style="margin:0;font-family:Georgia,serif;font-size:20px;color:#1a1a1a;">{agent['name']}</p>
                <p style="margin:4px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">{agent['title']}</p>
                <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">{agent['brokerage']}</p>
                <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">M: {phone}</p>
                <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">{agent['email']}</p>
                {social_icons}
              </td>
            </tr>
          </table>

          <!-- DISCLAIMER -->
          <p style="font-family:Arial,sans-serif;font-size:10px;color:#aaa;line-height:1.6;margin:0 0 24px;">
            {DISCLAIMER}
          </p>

          <!-- UNSUBSCRIBE — __UNSUBSCRIBE_URL__ is a placeholder substituted
               per-recipient at send time in routes/campaigns.py's
               _send_campaign(), since this HTML is built once and reused
               for every recipient but the unsubscribe link is address-specific. -->
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:11px;color:#aaa;margin:0 0 24px;">
            <a href="__UNSUBSCRIBE_URL__" style="color:#aaa;">Unsubscribe from these emails</a>
          </p>

        </td></tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

    return subject, html


def _description_html(description: str) -> str:
    """Renders a listing description's text as real paragraphs — split on
    blank lines, with single-line-breaks within a paragraph preserved as
    <br> — instead of dropping the whole thing into one <p> where a saved
    description template's blank-line-separated sections and section
    headers (e.g. "ARCHITECTURE & CURB APPEAL") would otherwise collapse
    into one run-on paragraph with no visible structure. A short ALL-CAPS
    line — whether it's alone or leads straight into that section's body
    text on the very next line, both are how the saved templates are
    written — renders as its own bolded section header, separate from the
    body text under it."""
    def is_header(line: str) -> bool:
        return line.isupper() and len(line) <= 60

    paragraphs = []
    for para in (description or "").split("\n\n"):
        lines = [escape(line.strip()) for line in para.splitlines() if line.strip()]
        if not lines:
            continue
        if is_header(lines[0]):
            paragraphs.append(
                f'<p style="font-family:Arial,sans-serif;font-size:12px;font-weight:bold;'
                f'letter-spacing:1px;color:#264653;margin:22px 0 6px;">{lines[0]}</p>'
            )
            lines = lines[1:]
        if lines:
            paragraphs.append(
                f'<p style="font-family:Georgia,serif;font-size:15px;line-height:1.8;'
                f'color:#333;margin:0 0 16px;">{"<br>".join(lines)}</p>'
            )
    return "".join(paragraphs) or '<p style="font-family:Georgia,serif;font-size:15px;line-height:1.8;color:#333;margin:0 0 24px;"></p>'


LISTING_LAYOUTS = {
    "property_showcase": "Property Showcase",
    "lifestyle_spotlight": "Lifestyle Spotlight",
    "listing_collection": "Listing Collection",
}

LISTING_LAYOUT_DESCRIPTIONS = {
    "property_showcase": "A complete property brochure: bold address, photo spread, dark facts bar, and detailed description.",
    "lifestyle_spotlight": "A quieter editorial design: large hero, split story panel, prominent price, and photo mosaic.",
    "listing_collection": "A curated roundup: serif headlines and stacked property cards, each with its own details link.",
}


def _header_banner_html() -> str:
    """Logo-left, brokerage-name-centered brand bar — identical across every
    layout so the email is recognizably Austin Apex regardless of which
    listing-content structure was chosen below it."""
    return f"""
        <tr>
          <td style="background:#264653;padding:24px 32px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="60" style="vertical-align:middle;">
                  <img src="{LOGO_B64}" width="60" height="54" style="display:block;width:60px;height:54px;" />
                </td>
                <td style="vertical-align:middle;text-align:center;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:18px;font-weight:bold;letter-spacing:2px;color:#ffffff;">
                    AUSTIN APEX REAL ESTATE
                  </p>
                </td>
                <td width="60"></td>
              </tr>
            </table>
          </td>
        </tr>"""


def _agent_signature_html(agent: dict, phone: str) -> str:
    _social_cells = ""
    if agent.get("linkedin"):
        _social_cells += f'<td style="padding-right:13px;"><a href="{agent["linkedin"]}" style="display:block;line-height:0;"><img src="{LINKEDIN_ICON_B64}" width="22" height="22" style="display:block;width:22px;height:22px;" /></a></td>'
    if agent.get("instagram"):
        _social_cells += f'<td><a href="{agent["instagram"]}" style="display:block;line-height:0;"><img src="{INSTAGRAM_ICON_B64}" width="22" height="22" style="display:block;width:22px;height:22px;" /></a></td>'
    social_icons = f'<table cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr>{_social_cells}</tr></table>' if _social_cells else ""

    return f"""
          <table cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
            <tr>
              <td style="padding-right:24px;vertical-align:top;">
                <img src="{agent['photo']}" width="110" height="140"
                     style="display:block;object-fit:cover;object-position:center center;width:110px;height:140px;" />
              </td>
              <td style="vertical-align:top;">
                <p style="margin:0;font-family:Georgia,serif;font-size:20px;color:#1a1a1a;">{agent['name']}</p>
                <p style="margin:4px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">{agent['title']}</p>
                <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">{agent['brokerage']}</p>
                <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">M: {phone}</p>
                <p style="margin:2px 0 0;font-family:Arial,sans-serif;font-size:12px;color:#555;">{agent['email']}</p>
                {social_icons}
              </td>
            </tr>
          </table>"""


def _footer_html() -> str:
    """Disclaimer + unsubscribe — __UNSUBSCRIBE_URL__ is a placeholder
    substituted per-recipient at send time in routes/campaigns.py's
    _send_campaign(), since this HTML is built once and reused for every
    recipient but the unsubscribe link is address-specific."""
    return f"""
          <p style="font-family:Arial,sans-serif;font-size:10px;color:#aaa;line-height:1.6;margin:0 0 24px;">
            {DISCLAIMER}
          </p>
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:11px;color:#aaa;margin:0 0 24px;">
            <a href="__UNSUBSCRIBE_URL__" style="color:#aaa;">Unsubscribe from these emails</a>
          </p>"""


def _cta_button_html(url: str, label: str) -> str:
    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 40px;">
      <tr>
        <td align="center">
          <a href="{url}" style="display:inline-block;background:#264653;color:#ffffff;font-family:Arial,sans-serif;font-size:13px;letter-spacing:2px;text-decoration:none;padding:14px 36px;border-radius:2px;">
            {label}
          </a>
        </td>
      </tr>
    </table>"""


def _wrap_email_html(subject: str, body_html: str) -> str:
    """The outer <html lang="en">/<body>/600px-column scaffold every layout shares —
    only what's inside the column (header banner through footer) differs."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <style>@media only screen and (max-width:620px) {{
    .email-content {{ padding:24px 20px !important; }}
    h1 {{ font-size:28px !important; letter-spacing:1px !important; }}
  }}</style>
  <title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f9f9f9;font-family:Georgia,serif;">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{escape(subject)}</div>
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f9f9f9">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;table-layout:fixed;background:#ffffff;border-radius:8px;overflow:hidden;">
        {body_html}
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def _build_original_email(ctx: dict) -> str:
    """Yifan's original layout — header banner, full-width hero, bold
    ALL-CAPS headline badge, centered address/stats, description, price,
    CTA, photo grid, agent signature, footer. The email as it's always
    looked, kept as the default so nothing changes for anyone who doesn't
    pick a different layout."""
    body = f"""
        <tr><td class="email-content" style="padding:32px 40px;">
          {ctx['hero_img']}
          <h1 style="text-align:center;font-family:Arial,sans-serif;font-size:36px;font-weight:900;letter-spacing:6px;color:#1a1a1a;margin:0 0 16px;">
            {ctx['headline']}
          </h1>
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:13px;letter-spacing:3px;color:#1a1a1a;margin:0 0 10px;">
            {ctx['full_address']}
          </p>
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:14px;color:#333;margin:0 0 32px;">
            {ctx['beds']} BD &nbsp;&nbsp; {ctx['baths']} BA &nbsp;&nbsp; {ctx['sqft_formatted']} SF &nbsp;&nbsp; {ctx['price_formatted']}
          </p>
          <hr style="border:none;border-top:1px solid #e0e0e0;margin:0 0 28px;" />
          {ctx['description_html']}
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:13px;letter-spacing:2px;color:#888;margin:0 0 8px;">
            Offered at {ctx['price_formatted']}
          </p>
          {_cta_button_html(ctx['btn_url'], 'VIEW PROPERTY')}
          {ctx['grid_html']}
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:14px;color:#555;margin:24px 0 40px;">
            <a href="mailto:{ctx['agent']['email']}" style="color:#1a1a1a;text-decoration:none;border-bottom:1px solid #1a1a1a;padding-bottom:2px;">
              Reach out for more info
            </a>
          </p>
          <hr style="border:none;border-top:1px solid #e0e0e0;margin:0 0 28px;" />
          {_agent_signature_html(ctx['agent'], ctx['phone'])}
          {_footer_html()}
        </td></tr>"""
    return _wrap_email_html(ctx['subject'], _header_banner_html() + body)


def _build_feature_spotlight_email(ctx: dict) -> str:
    """Detailed feature-by-feature breakdown — icon stat row, a category
    badge above the headline, section-by-section body copy (see
    _description_html's ALL-CAPS-header handling), and a "SCHEDULE A TOUR"
    call to action instead of "VIEW PROPERTY" — modeled on a single-listing
    spotlight email that walks a buyer through the home room by room."""
    body = f"""
        <tr><td style="padding:0;">
          {ctx['hero_img_flush']}
        </td></tr>
        <tr><td class="email-content" style="padding:32px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:18px;"><tr><td align="center">
            <span style="font-family:Arial,sans-serif;font-size:11px;font-weight:bold;letter-spacing:3px;color:#ffffff;background:#264653;padding:7px 18px;border-radius:20px;">{ctx['headline']}</span>
          </td></tr></table>
          <h1 style="text-align:center;font-family:Georgia,serif;font-size:26px;font-weight:normal;color:#1a1a1a;margin:0 0 8px;">
            {ctx['address']}
          </h1>
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:13px;letter-spacing:2px;color:#888;margin:0 0 24px;">
            {ctx['city_state_zip']}
          </p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;background:#f7f8f6;border-radius:6px;">
            <tr>
              <td align="center" style="padding:16px 8px;font-family:Arial,sans-serif;font-size:13px;color:#333;">🛏 {ctx['beds']} Beds</td>
              <td align="center" style="padding:16px 8px;font-family:Arial,sans-serif;font-size:13px;color:#333;border-left:1px solid #e0e0e0;">🛁 {ctx['baths']} Baths</td>
              <td align="center" style="padding:16px 8px;font-family:Arial,sans-serif;font-size:13px;color:#333;border-left:1px solid #e0e0e0;">📐 {ctx['sqft_formatted']} SF</td>
              <td align="center" style="padding:16px 8px;font-family:Arial,sans-serif;font-size:13px;color:#333;border-left:1px solid #e0e0e0;">💲 {ctx['price_formatted']}</td>
            </tr>
          </table>
          {ctx['description_html_spotlight']}
          {_cta_button_html(ctx['btn_url'], 'SCHEDULE A PRIVATE TOUR')}
          {ctx['grid_html']}
          <hr style="border:none;border-top:1px solid #e0e0e0;margin:28px 0;" />
          {_agent_signature_html(ctx['agent'], ctx['phone'])}
          {_footer_html()}
        </td></tr>"""
    return _wrap_email_html(ctx['subject'], _header_banner_html() + body)


def _build_featured_highlight_email(ctx: dict) -> str:
    """Punchy lifestyle-forward spotlight — edge-to-edge hero, a bold
    tagline, the write-up boxed in a tinted "SPOTLIGHT" callout, price
    displayed large, and a "SEE THE PROPERTY" CTA — modeled on a short,
    scannable single-listing highlight rather than a detailed breakdown."""
    body = f"""
        <tr><td style="padding:0;">
          {ctx['hero_img_flush']}
        </td></tr>
        <tr><td class="email-content" style="padding:36px 40px 32px;">
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:11px;font-weight:bold;letter-spacing:3px;color:#264653;margin:0 0 10px;">
            {ctx['headline']}
          </p>
          <h1 style="text-align:center;font-family:Georgia,serif;font-style:italic;font-size:28px;font-weight:normal;color:#1a1a1a;margin:0 0 20px;line-height:1.3;">
            {ctx['address']}
          </h1>
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#f7f8f6;border-radius:6px;margin:0 0 24px;">
            <tr><td style="padding:24px 28px;">
              <p style="font-family:Arial,sans-serif;font-size:11px;font-weight:bold;letter-spacing:2px;color:#888;margin:0 0 10px;">SPOTLIGHT</p>
              {ctx['description_html']}
            </td></tr>
          </table>
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:28px;font-weight:bold;color:#1a1a1a;margin:0 0 4px;">
            {ctx['price_formatted']}
          </p>
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:12px;letter-spacing:2px;color:#888;margin:0 0 8px;">
            {ctx['beds']} BD &nbsp;&nbsp; {ctx['baths']} BA &nbsp;&nbsp; {ctx['sqft_formatted']} SF
          </p>
          {_cta_button_html(ctx['btn_url'], 'SEE THE PROPERTY')}
          {ctx['grid_html']}
          <hr style="border:none;border-top:1px solid #e0e0e0;margin:28px 0;" />
          {_agent_signature_html(ctx['agent'], ctx['phone'])}
          {_footer_html()}
        </td></tr>"""
    return _wrap_email_html(ctx['subject'], _header_banner_html() + body)


def _build_collection_email(ctx: dict, style: str) -> str:
    """Three distinct MLS compositions sharing the existing brand and footer."""
    stats = f"{ctx['beds']} beds &nbsp; / &nbsp; {ctx['baths']} baths &nbsp; / &nbsp; {ctx['sqft_formatted']} sq ft"
    label = f'<p style="font: bold 11px Arial,sans-serif;letter-spacing:3px;color:#526b70;margin:0 0 16px;">{ctx["headline"]}</p>'
    address = f'<h1 style="font:normal 34px Georgia,serif;line-height:1.2;color:#203d46;margin:0 0 12px;">{ctx["address"]}</h1><p style="font:13px Arial,sans-serif;color:#647277;margin:0 0 24px;">{ctx["city_state_zip"]}</p>'
    price = f'<p style="font:normal 28px Georgia,serif;color:#203d46;margin:0 0 16px;">{ctx["price_formatted"]}</p>'
    facts = f'<p style="font:14px Arial,sans-serif;line-height:1.8;color:#43575c;margin:0 0 24px;">{stats}</p>'
    if style == "editorial":
        content = f'<tr><td class="email-content" style="padding:40px;background:#f4f1e9;">{label}{address}{price}{facts}</td></tr><tr><td>{ctx["hero_img_flush"]}</td></tr><tr><td class="email-content" style="padding:32px 40px;">{ctx["description_html"]}{_cta_button_html(ctx["btn_url"], "EXPLORE THE HOME")}{ctx["grid_html"]}</td></tr>'
    elif style == "photo_gallery":
        content = f'<tr><td>{ctx["hero_img_flush"]}</td></tr><tr><td class="email-content" style="padding:32px 40px;">{label}{address}{price}{facts}{_cta_button_html(ctx["btn_url"], "VIEW LISTING & PHOTOS")}{ctx["grid_html"]}<hr style="border:0;border-top:1px solid #dce3e3;margin:28px 0;"/>{ctx["description_html"]}</td></tr>'
    else:
        content = f'<tr><td class="email-content" style="padding:32px 40px;">{label}{address}<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top:3px solid #264653;border-bottom:1px solid #dce3e3;margin-bottom:24px;"><tr><td style="padding:24px 0 0;">{price}{facts}</td></tr></table>{_cta_button_html(ctx["btn_url"], "VIEW PROPERTY DETAILS")}{ctx["hero_img"]}{ctx["description_html"]}</td></tr>'
    closing = f'<tr><td class="email-content" style="padding:8px 40px 32px;"><hr style="border:0;border-top:1px solid #dce3e3;margin:0 0 28px;"/>{_agent_signature_html(ctx["agent"], ctx["phone"])}{_footer_html()}</td></tr>'
    return _wrap_email_html(ctx['subject'], _header_banner_html() + content + closing)


# The three current designs use separate compositions. Older builders above
# remain readable for drafts saved before this template collection launched.
def _collection_brand(dark=False):
    color, background = ("#ffffff", "#203e49") if dark else ("#203e49", "#ffffff")
    return f'''<tr><td align="center" bgcolor="{background}" style="padding:28px 24px;color:{color};">
      <p style="font:bold 22px Georgia,serif;letter-spacing:4px;margin:0;">AUSTIN APEX</p>
      <p style="font:9px Arial,sans-serif;letter-spacing:4px;margin:8px 0 0;">REAL ESTATE</p>
    </td></tr>'''


def _design_photo(url, width=600):
    return f'<img src="{url}" width="{width}" alt="Property photograph" style="display:block;width:100%;max-width:{width}px;height:auto;border:0;"/>' if url else ""


def _design_gallery(photos):
    rows = []
    for offset in range(0, len(photos), 2):
        pair = photos[offset:offset + 2]
        if len(pair) == 1:
            rows.append(f'<tr><td colspan="2" style="padding:3px 0;">{_design_photo(pair[0])}</td></tr>')
        else:
            rows.append('<tr>' + ''.join(f'<td width="50%" valign="top" style="padding:3px;">{_design_photo(url, 300)}</td>' for url in pair) + '</tr>')
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' + ''.join(rows) + '</table>' if rows else ""


def _design_footer(ctx):
    return f'''<tr><td class="email-content" style="padding:32px 40px 24px;">
      <hr style="border:0;border-top:1px solid #dbe0de;margin:0 0 28px;"/>
      {_agent_signature_html(ctx['agent'], ctx['phone'])}{_footer_html()}
    </td></tr>'''


def _design_shell(subject, content):
    html = _wrap_email_html(subject, content)
    # Email clients that ignore media queries still get a fluid table;
    # clients with media-query support also stack the spotlight columns.
    return html.replace('</style>', '''@media only screen and (max-width:620px) {
      .spotlight-column { display:block !important;width:100% !important;box-sizing:border-box !important; }
      .spotlight-copy { padding:24px !important; }
      .collection-heading { font-size:30px !important; }
    }</style>''').replace('border-radius:8px;overflow:hidden;', 'border-radius:0;overflow:hidden;')


def _build_property_showcase(ctx):
    """Reference 1: title/price masthead, photo spread, dark facts, full copy."""
    facts = ''.join(f'''<td width="33%" align="center" style="padding:20px 4px;color:#ffffff;">
      <p style="font:24px Georgia,serif;margin:0 0 6px;">{value}</p>
      <p style="font:9px Arial,sans-serif;letter-spacing:2px;margin:0;">{label}</p></td>'''
      for value, label in ((ctx['beds'], 'BEDROOMS'), (ctx['baths'], 'BATHROOMS'), (ctx['sqft_formatted'], 'SQUARE FEET')))
    body = f'''{_collection_brand(dark=True)}
      <tr><td class="email-content" align="center" bgcolor="#eeefeb" style="padding:34px 40px;">
        <p style="font:bold 11px Arial,sans-serif;letter-spacing:3px;color:#53676b;margin:0 0 16px;">{ctx['headline']}</p>
        <h1 style="font:normal 30px Arial,sans-serif;letter-spacing:2px;line-height:1.3;text-transform:uppercase;color:#203e49;margin:0 0 12px;">{ctx['address']}</h1>
        <p style="font:12px Arial,sans-serif;letter-spacing:2px;color:#53676b;margin:0 0 20px;">{ctx['city_state_zip']}</p>
        <p style="font:bold 18px Arial,sans-serif;color:#203e49;margin:0;">{ctx['price_formatted']}</p>
      </td></tr>
      <tr><td>{ctx['hero_img_flush']}</td></tr>
      <tr><td style="padding:3px 0;">{_design_gallery(ctx['photos'][1:3])}</td></tr>
      <tr><td bgcolor="#203e49"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{facts}</tr></table></td></tr>
      <tr><td class="email-content" style="padding:34px 40px;">
        <p style="font:bold 11px Arial,sans-serif;letter-spacing:3px;color:#53676b;margin:0 0 20px;">THE PROPERTY</p>
        {ctx['description_html']}
        {_cta_button_html(ctx['btn_url'], 'VIEW PROPERTY DETAILS')}
        {_design_gallery(ctx['photos'][3:5])}
      </td></tr>{_design_footer(ctx)}'''
    return _design_shell(ctx['subject'], body)


def _build_lifestyle_spotlight(ctx):
    """Reference 2: quiet brand, hero, asymmetric story panel, price, mosaic."""
    body = f'''{_collection_brand()}
      <tr><td>{ctx['hero_img_flush']}</td></tr>
      <tr><td style="padding:0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td class="spotlight-column spotlight-copy" width="36%" valign="top" bgcolor="#e7ece6" style="padding:32px 24px;">
          <p style="font:10px Arial,sans-serif;letter-spacing:3px;color:#43584f;margin:0 0 22px;">SPOTLIGHT</p>
          <h1 style="font:normal 26px Georgia,serif;line-height:1.3;color:#243b32;margin:0 0 16px;">{ctx['address']}</h1>
          <p style="font:12px Arial,sans-serif;line-height:1.8;color:#43584f;margin:0;">{ctx['city_state_zip']}</p>
        </td>
        <td class="spotlight-column spotlight-copy" width="64%" valign="top" bgcolor="#f5f6f2" style="padding:32px 26px;">
          <p style="font:10px Arial,sans-serif;letter-spacing:2px;color:#53676b;margin:0 0 16px;">{ctx['headline']}</p>
          {ctx['description_html']}
          <p style="font:12px Arial,sans-serif;line-height:1.8;color:#53676b;margin:20px 0 0;">{ctx['beds']} BD &nbsp; · &nbsp; {ctx['baths']} BA &nbsp; · &nbsp; {ctx['sqft_formatted']} SF</p>
        </td>
      </tr></table></td></tr>
      <tr><td class="email-content" align="center" style="padding:8px 40px 30px;">
        {_cta_button_html(ctx['btn_url'], 'SEE THE PROPERTY')}
        <p style="font:italic 30px Georgia,serif;color:#243b32;margin:0;">{ctx['price_formatted']}</p>
      </td></tr>
      <tr><td>{_design_gallery(ctx['photos'][1:5])}</td></tr>
      {_design_footer(ctx)}'''
    return _design_shell(ctx['subject'], body)


def _listing_collection_card(ctx):
    return f'''<tr><td>{ctx['hero_img_flush']}</td></tr>
      <tr><td class="email-content" align="center" style="padding:28px 40px 38px;">
        <p style="font:italic bold 18px Georgia,serif;text-decoration:underline;color:#203e49;margin:0 0 16px;">{ctx['headline']}</p>
        <h2 style="font:italic 27px Georgia,serif;color:#203e49;line-height:1.3;margin:0 0 8px;">{ctx['address']}</h2>
        <p style="font:italic 17px Georgia,serif;color:#53676b;margin:0 0 18px;">{ctx['city_state_zip']}</p>
        <div style="text-align:center;">{ctx['description_html']}</div>
        <p style="font:12px Arial,sans-serif;line-height:1.8;color:#203e49;margin:22px 0 8px;">{ctx['beds']} BD &nbsp; | &nbsp; {ctx['baths']} BA &nbsp; | &nbsp; {ctx['sqft_formatted']} SF</p>
        <p style="font:bold 16px Arial,sans-serif;color:#203e49;margin:0 0 18px;">{ctx['price_formatted']}</p>
        <table role="presentation" align="center" cellpadding="0" cellspacing="0"><tr><td align="center" style="border:1px solid #203e49;padding:13px 28px;">
          <a href="{ctx['btn_url']}" style="font:bold 11px Arial,sans-serif;letter-spacing:2px;color:#203e49;text-decoration:none;">VIEW DETAILS</a>
        </td></tr></table>
      </td></tr>'''


def _build_listing_collection(ctx):
    return _render_listing_collection([ctx], ctx['subject'])


def _render_listing_collection(contexts, subject):
    content = _collection_brand() + '''<tr><td align="center" class="email-content" style="padding:10px 40px 34px;">
      <p style="font:10px Arial,sans-serif;letter-spacing:3px;color:#6a7775;margin:0 0 12px;">THE AUSTIN APEX COLLECTION</p>
      <h1 class="collection-heading" style="font:normal 36px Georgia,serif;line-height:1.2;color:#203e49;margin:0;">Discover your next address.</h1>
    </td></tr>'''
    content += ''.join(_listing_collection_card(ctx) for ctx in contexts)
    return _design_shell(subject, content + _design_footer(contexts[0]))


def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(str(value or ""))
        if parsed.scheme in ("https", "http") and parsed.netloc:
            return escape(str(value), quote=True)
    except ValueError:
        pass
    return ""


def _number(value, money=False):
    try:
        number = Decimal(str(value).replace(",", ""))
        if number.is_finite() and number >= 0 and (not money or number > 0):
            return f"${number:,.0f}" if money else f"{number:,.0f}"
    except (InvalidOperation, ValueError):
        pass
    return "Price on request" if money else "—"


_LAYOUT_BUILDERS = {
    "property_showcase": _build_property_showcase,
    "lifestyle_spotlight": _build_lifestyle_spotlight,
    "listing_collection": _build_listing_collection,
    "editorial": lambda ctx: _build_collection_email(ctx, "editorial"),
    "photo_gallery": lambda ctx: _build_collection_email(ctx, "photo_gallery"),
    "property_brief": lambda ctx: _build_collection_email(ctx, "property_brief"),
    "original": _build_original_email,
    "feature_spotlight": _build_feature_spotlight_email,
    "featured_highlight": _build_featured_highlight_email,
}


def _listing_context(
    listing: dict,
    photo_urls: list = None,
    email_type: str = "just_listed",
    agent_email: str = None,
    property_url: str = None,
    description: str = None,
    layout: str = "original",
) -> tuple:
    """
    Build a listing email. `description`, when given, overrides the MLS
    PublicRemarks text — lets Yifan/Anthony edit the write-up (fix a typo,
    add color commentary) before sending instead of only ever using the
    raw MLS copy verbatim. `layout` picks which full HTML structure to
    render it into — see LISTING_LAYOUTS.
    Returns (subject, html_body).
    """
    address = str(listing.get("UnparsedAddress") or "Property details").strip()
    city = str(listing.get("City") or "")
    state = str(listing.get("StateOrProvince") or "")
    zipcode = str(listing.get("PostalCode") or "")
    price = listing.get("ListPrice", 0)
    beds = listing.get("BedroomsTotal", "N/A")
    baths = listing.get("BathroomsTotalInteger", "N/A")
    sqft = listing.get("LivingArea", "N/A")
    description = description if description is not None else listing.get("PublicRemarks", "")
    description_html = _description_html(description)
    listing_agent_email = listing.get("ListAgentEmail", "")
    listing_phone = listing.get("ListAgentDirectPhone", "")

    agent = _get_agent(listing_agent_email, agent_email)
    headline = EMAIL_TYPES.get(email_type, "JUST LISTED")
    full_address = f"{address}, {city}, {state} {zipcode}".upper()
    price_formatted = _number(price, money=True)
    sqft_formatted = _number(sqft)
    phone = listing_phone or agent["phone"]

    subject = f"{headline.title()} | {address}, {city} — {beds}BD {baths}BA {price_formatted}"

    photo_urls = [url for value in (photo_urls or []) if (url := _safe_url(value))]
    hero_img = ""
    hero_img_flush = ""
    grid_html = ""
    if photo_urls:
        hero_img = f'<img src="{photo_urls[0]}" width="600" alt="Property photograph" style="width:100%;height:auto;display:block;border-radius:6px;margin-bottom:32px;" />'
        hero_img_flush = f'<img src="{photo_urls[0]}" width="600" alt="Property photograph" style="width:100%;height:auto;display:block;" />'
        grid_html = _photo_grid_html(photo_urls)

    btn_url = _safe_url(property_url) or DEFAULT_CTA_URL

    ctx = {
        "subject": subject, "address": address, "full_address": full_address,
        "city_state_zip": f"{city}, {state} {zipcode}".upper(),
        "headline": headline, "beds": beds, "baths": baths, "sqft_formatted": sqft_formatted,
        "price_formatted": price_formatted, "description_html": description_html,
        "description_html_spotlight": description_html,
        "hero_img": hero_img, "hero_img_flush": hero_img_flush, "grid_html": grid_html,
        "btn_url": btn_url, "agent": agent, "phone": phone, "photos": photo_urls,
    }
    for key in ("address", "full_address", "city_state_zip", "beds", "baths", "phone"):
        ctx[key] = escape(str(ctx[key] if ctx[key] is not None else "—"))
    return ctx


def build_listing_email(
    listing: dict, photo_urls: list = None, email_type: str = "just_listed",
    agent_email: str = None, property_url: str = None, description: str = None,
    layout: str = "original", collection_entries: list = None,
) -> tuple:
    """Render a listing or a collection of explicitly selected MLS snapshots.

    Additional collection entries contain listing, photo_urls, email_type,
    property_url and description. All rendering uses the same field escaping.
    Legacy layout keys continue to work for already-saved campaigns.
    """
    ctx = _listing_context(listing, photo_urls, email_type, agent_email, property_url, description, layout)
    if layout == "listing_collection" and collection_entries:
        contexts = [ctx] + [_listing_context(
            entry["listing"], entry.get("photo_urls"), entry.get("email_type", "just_listed"),
            agent_email, entry.get("property_url"), entry.get("description"), layout,
        ) for entry in collection_entries]
        subject = f"The Austin Apex Collection | {len(contexts)} properties to explore"
        return subject, _render_listing_collection(contexts, subject)
    return ctx["subject"], _LAYOUT_BUILDERS.get(layout, _build_original_email)(ctx)
