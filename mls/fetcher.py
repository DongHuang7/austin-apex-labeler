import os
import json
import requests
from datetime import datetime, timedelta

API_URL = os.getenv("MLSGRID_API_URL", "https://api.mlsgrid.com/v2")
TOKEN = os.getenv("MLSGRID_TOKEN")
OFFICE_ID = os.getenv("MLSGRID_OFFICE_ID", "ACT704798")  # Austin Apex Real Estate
SEEN_LISTINGS_FILE = "seen_listings.json"

BASE_FILTER = f"OriginatingSystemName eq 'actris' and MlgCanView eq true and ListOfficeMlsId eq '{OFFICE_ID}'"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}

# Fields to fetch for each listing
SELECT_FIELDS = ",".join([
    "ListingId",
    "ListPrice",
    "BedroomsTotal",
    "BathroomsTotalInteger",
    "LivingArea",
    "UnparsedAddress",
    "City",
    "StateOrProvince",
    "PostalCode",
    "PublicRemarks",
    "StandardStatus",
    "ListingContractDate",
    "CloseDate",
    "ClosePrice",
    "DaysOnMarket",
    "CumulativeDaysOnMarket",
    "PropertyType",
    "ListAgentFullName",
    "ListAgentEmail",
    "ListAgentDirectPhone",
])


def _load_seen_listings():
    if os.path.exists(SEEN_LISTINGS_FILE):
        with open(SEEN_LISTINGS_FILE) as f:
            return set(json.load(f))
    return set()


def _save_seen_listings(seen: set):
    with open(SEEN_LISTINGS_FILE, "w") as f:
        json.dump(list(seen), f)


def fetch_active_listings(max_results=50, include_photos=True):
    """Fetch active Austin Apex Real Estate listings with photos."""
    params = {
        "$filter": BASE_FILTER,
        "$top": 500,
        "$select": SELECT_FIELDS,
    }
    if include_photos:
        params["$expand"] = "Media"
    listings = _fetch_listings(params)
    active = [l for l in listings if l.get("StandardStatus") == "Active"]
    print(f"Filtered to {len(active)} active listings.")
    return active[:max_results]


def fetch_new_listings_since(days=1, max_results=50, include_photos=True):
    """Fetch Austin Apex listings modified in the last N days."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "$filter": f"{BASE_FILTER} and ModificationTimestamp ge {since}",
        "$top": max_results,
        "$select": SELECT_FIELDS,
    }
    if include_photos:
        params["$expand"] = "Media"
    listings = _fetch_listings(params)
    return [l for l in listings if l.get("StandardStatus") == "Active"]


def fetch_sold_listings(days=30, max_results=20):
    """Fetch recently sold Austin Apex listings for comps."""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "$filter": f"{BASE_FILTER} and ModificationTimestamp ge {since}",
        "$top": max_results,
        "$select": SELECT_FIELDS,
    }
    listings = _fetch_listings(params)
    return [l for l in listings if l.get("StandardStatus") == "Closed"]


def fetch_only_new(days=1, max_results=50):
    """Fetch new listings and filter out ones already seen."""
    listings = fetch_new_listings_since(days=days, max_results=max_results)
    seen = _load_seen_listings()

    new_listings = [l for l in listings if l["ListingId"] not in seen]
    seen.update(l["ListingId"] for l in new_listings)
    _save_seen_listings(seen)

    print(f"Found {len(new_listings)} new listings (skipped {len(listings) - len(new_listings)} already seen).")
    return new_listings


def _fetch_listings(params):
    """Make API call and return list of listings."""
    response = requests.get(
        f"{API_URL}/Property",
        headers=HEADERS,
        params=params,
    )
    response.raise_for_status()
    data = response.json()
    listings = data.get("value", [])
    print(f"Fetched {len(listings)} listings from MLS-GRID.")
    return listings


def get_email_type(listing: dict) -> str:
    """Determine the email type based on MLS status and ADOM (accumulated days on market)."""
    from datetime import datetime

    status = listing.get("StandardStatus", "")

    if status in ("Active Under Contract", "Pending"):
        return "in_escrow"
    if status == "Closed":
        return "just_sold"
    if status == "Coming Soon":
        return "coming_soon"
    if status == "Active":
        # Use CumulativeDaysOnMarket (ADOM) as primary source.
        # Fall back to ListingContractDate if ADOM looks reset/unreliable
        # (i.e. ADOM < days since contract date).
        adom = listing.get("CumulativeDaysOnMarket") or 0
        contract_date_str = listing.get("ListingContractDate")
        if contract_date_str:
            try:
                contract_days = (datetime.now() - datetime.strptime(contract_date_str[:10], "%Y-%m-%d")).days
                days = max(adom, contract_days)
            except ValueError:
                days = adom
        else:
            days = adom
        return "just_listed" if days <= 30 else "active_selling"
    return "just_listed"


def get_property_url(listing: dict) -> str:
    """
    Build the austinapexre.com property URL from MLS listing data.
    Pattern: /properties/{address}-{city}-{state}-us-{zipcode}-{mls_number}
    Example: /properties/1417-deer-ledge-trl-cedar-park-tx-us-78613-5296155
    """
    def slugify(text):
        import re
        text = text.lower().strip()
        text = re.sub(r'[#,]', '', text)       # remove # and commas
        text = re.sub(r'\s+', '-', text)        # spaces → single hyphen
        text = re.sub(r'-+', '-', text)         # collapse multiple hyphens
        return text.strip('-')

    address = slugify(listing.get("UnparsedAddress", ""))
    city = slugify(listing.get("City", ""))
    state = listing.get("StateOrProvince", "TX").lower()
    zipcode = listing.get("PostalCode", "")
    listing_id = listing.get("ListingId", "").replace("ACT", "")

    slug = f"{address}-{city}-{state}-us-{zipcode}-{listing_id}"
    return f"https://austinapexre.com/properties/{slug}"


def get_photo_urls(listing: dict, max_photos=40) -> list:
    """Extract sorted photo URLs from a listing's Media field."""
    media = listing.get("Media", [])
    if not media:
        return []
    sorted_media = sorted(media, key=lambda m: m.get("Order", 999))
    return [m["MediaURL"] for m in sorted_media if m.get("MediaURL")][:max_photos]


def format_listing(listing: dict) -> str:
    """Format a listing into a human-readable summary."""
    return (
        f"Address: {listing.get('UnparsedAddress', '').strip()}, "
        f"{listing.get('City', '')}, {listing.get('StateOrProvince', '')} "
        f"{listing.get('PostalCode', '')}\n"
        f"Price: ${listing.get('ListPrice', 0):,.0f}\n"
        f"Beds: {listing.get('BedroomsTotal', 'N/A')} | "
        f"Baths: {listing.get('BathroomsTotalInteger', 'N/A')} | "
        f"Sqft: {listing.get('LivingArea', 'N/A'):,}\n"
        f"Status: {listing.get('StandardStatus', 'N/A')}\n"
        f"Days on Market: {listing.get('DaysOnMarket', 'N/A')}\n"
        f"Description: {listing.get('PublicRemarks', '')[:300]}...\n"
        f"Agent: {listing.get('ListAgentFullName', 'N/A')} | "
        f"{listing.get('ListAgentDirectPhone', '')}"
    )
