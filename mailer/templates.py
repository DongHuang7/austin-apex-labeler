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
            f'<td style="padding:4px;width:50%;"><img src="{url}" style="width:100%;display:block;border-radius:4px;" /></td>'
            for url in pair
        )
        rows += f"<tr>{tds}</tr>"
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0;">{rows}</table>'


def build_listing_email(
    listing: dict,
    photo_urls: list = None,
    email_type: str = "just_listed",
    agent_email: str = None,
    property_url: str = None,
) -> tuple:
    """
    Build a listing email.
    Returns (subject, html_body).
    """
    address = listing.get("UnparsedAddress", "").strip()
    city = listing.get("City", "")
    state = listing.get("StateOrProvince", "TX")
    zipcode = listing.get("PostalCode", "")
    price = listing.get("ListPrice", 0)
    beds = listing.get("BedroomsTotal", "N/A")
    baths = listing.get("BathroomsTotalInteger", "N/A")
    sqft = listing.get("LivingArea", "N/A")
    description = listing.get("PublicRemarks", "")
    listing_agent_email = listing.get("ListAgentEmail", "")
    listing_phone = listing.get("ListAgentDirectPhone", "")

    agent = _get_agent(listing_agent_email, agent_email)
    headline = EMAIL_TYPES.get(email_type, "JUST LISTED")
    full_address = f"{address}, {city}, {state} {zipcode}".upper()
    price_formatted = f"${price:,.0f}"
    sqft_formatted = f"{int(sqft):,}" if isinstance(sqft, (int, float)) else sqft
    phone = listing_phone or agent["phone"]

    subject = f"{headline.title()} | {address}, {city} — {beds}BD {baths}BA {price_formatted}"

    hero_img = ""
    grid_html = ""
    if photo_urls:
        hero_img = f'<img src="{photo_urls[0]}" width="600" style="width:100%;display:block;border-radius:6px;margin-bottom:32px;" />'
        grid_html = _photo_grid_html(photo_urls)

    btn_url = property_url or "https://www.austinapexre.com"
    property_button = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:24px 0 40px;">
      <tr>
        <td align="center">
          <a href="{btn_url}" style="display:inline-block;background:#264653;color:#ffffff;font-family:Arial,sans-serif;font-size:13px;letter-spacing:2px;text-decoration:none;padding:14px 36px;border-radius:2px;">
            VIEW PROPERTY
          </a>
        </td>
      </tr>
    </table>"""

    _social_cells = ""
    if agent.get("linkedin"):
        _social_cells += f'<td style="padding-right:13px;"><a href="{agent["linkedin"]}" style="display:block;line-height:0;"><img src="{LINKEDIN_ICON_B64}" width="22" height="22" style="display:block;width:22px;height:22px;" /></a></td>'
    if agent.get("instagram"):
        _social_cells += f'<td><a href="{agent["instagram"]}" style="display:block;line-height:0;"><img src="{INSTAGRAM_ICON_B64}" width="22" height="22" style="display:block;width:22px;height:22px;" /></a></td>'
    social_icons = f'<table cellpadding="0" cellspacing="0" style="margin-top:14px;"><tr>{_social_cells}</tr></table>' if _social_cells else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background:#f9f9f9;font-family:Georgia,serif;">
<table width="100%" cellpadding="0" cellspacing="0" bgcolor="#f9f9f9">
  <tr>
    <td align="center" style="padding:32px 16px;">
      <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:8px;overflow:hidden;">

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

        <tr><td style="padding:32px 40px;">

          <!-- HERO IMAGE -->
          {hero_img}

          <!-- HEADLINE -->
          <h1 style="text-align:center;font-family:Arial,sans-serif;font-size:36px;font-weight:900;letter-spacing:6px;color:#1a1a1a;margin:0 0 16px;">
            {headline}
          </h1>

          <!-- ADDRESS -->
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:13px;letter-spacing:3px;color:#1a1a1a;margin:0 0 10px;">
            {full_address}
          </p>

          <!-- STATS -->
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:14px;color:#333;margin:0 0 32px;">
            {beds} BD &nbsp;&nbsp; {baths} BA &nbsp;&nbsp; {sqft_formatted} SF &nbsp;&nbsp; {price_formatted}
          </p>

          <hr style="border:none;border-top:1px solid #e0e0e0;margin:0 0 28px;" />

          <!-- DESCRIPTION -->
          <p style="font-family:Georgia,serif;font-size:15px;line-height:1.8;color:#333;margin:0 0 24px;">
            {description}
          </p>

          <!-- OFFERED AT -->
          <p style="text-align:center;font-family:Arial,sans-serif;font-size:13px;letter-spacing:2px;color:#888;margin:0 0 8px;">
            Offered at {price_formatted}
          </p>

          <!-- VIEW PROPERTY BUTTON -->
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

        </td></tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

    return subject, html
