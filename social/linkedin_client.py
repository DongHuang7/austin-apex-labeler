"""
LinkedIn publishing via the Posts API (successor to the old UGC Posts API).

Requires LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET config vars.
IMPORTANT: personal-profile posting (w_member_social) and company-page
posting (needing Marketing/Community Management API partner access) are
different approval paths with very different lead times — see Phase 2 plan
notes. This client supports both call shapes (author is either a member
URN or an organization URN); which one is usable depends entirely on which
approval you actually get.
"""
import os
from datetime import datetime, timedelta, timezone

import requests

API_BASE = "https://api.linkedin.com/rest"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
AUTH_BASE = "https://www.linkedin.com/oauth/v2"
LINKEDIN_VERSION = "202405"

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET")

# w_member_social: post as the logged-in person.
# w_organization_social: post as a Company Page (needs partner access).
SCOPES_MEMBER = ["openid", "profile", "w_member_social"]
SCOPES_ORG = ["w_organization_social", "r_organization_social"]


def is_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def build_oauth_url(redirect_uri: str, state: str, scopes: list = None) -> str:
    if not is_configured():
        raise RuntimeError("LINKEDIN_CLIENT_ID/LINKEDIN_CLIENT_SECRET are not set — LinkedIn app isn't provisioned yet.")
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(scopes or SCOPES_MEMBER),
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{AUTH_BASE}/authorization?{query}"


def exchange_code_for_token(code: str, redirect_uri: str) -> tuple:
    """Returns (access_token, expires_at)."""
    resp = requests.post(f"{AUTH_BASE}/accessToken", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    })
    resp.raise_for_status()
    data = resp.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 5184000))
    return data["access_token"], expires_at


def get_member_urn(access_token: str) -> str:
    """OpenID Connect's userinfo lives under /v2/, not the versioned
    /rest/ Restli API (that's for Posts/Images/Marketing endpoints)."""
    resp = requests.get(USERINFO_URL, headers={
        "Authorization": f"Bearer {access_token}",
    })
    resp.raise_for_status()
    return f"urn:li:person:{resp.json()['sub']}"


def _upload_image(owner_urn: str, access_token: str, image_url: str) -> str:
    """Uploads one image to LinkedIn's Images API and returns its
    urn:li:image:... id, for use as post content. Two-step process:
    initializeUpload gets a pre-signed PUT target, then the raw bytes are
    PUT there directly (image_url must be a publicly fetchable https URL —
    LinkedIn doesn't accept file uploads, and we don't proxy the bytes
    ourselves, so we re-fetch from image_url instead of trusting a local
    copy)."""
    init_resp = requests.post(
        f"{API_BASE}/images?action=initializeUpload",
        json={"initializeUploadRequest": {"owner": owner_urn}},
        headers={
            "Authorization": f"Bearer {access_token}",
            "LinkedIn-Version": LINKEDIN_VERSION,
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    init_resp.raise_for_status()
    value = init_resp.json()["value"]
    upload_url = value["uploadUrl"]
    image_urn = value["image"]

    image_bytes = requests.get(image_url, timeout=15)
    image_bytes.raise_for_status()

    put_resp = requests.put(upload_url, data=image_bytes.content, headers={
        "Authorization": f"Bearer {access_token}",
    })
    put_resp.raise_for_status()
    return image_urn


def publish_post(author_urn: str, access_token: str, text: str,
                 image_url: str = None, image_urls: list = None) -> str:
    """author_urn is either urn:li:person:<id> or urn:li:organization:<id>.
    Returns the created post's id (from the response's x-restli-id header)."""
    body = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
    }
    images = list(dict.fromkeys(image_urls or ([image_url] if image_url else [])))[:3]
    if len(images) > 1:
        body["content"] = {"multiImage": {"images": [
            {"id": _upload_image(author_urn, access_token, url), "altText": "Property photograph"}
            for url in images
        ]}}
    elif images:
        image_urn = _upload_image(author_urn, access_token, images[0])
        body["content"] = {"media": {"id": image_urn}}

    resp = requests.post(f"{API_BASE}/posts", json=body, headers={
        "Authorization": f"Bearer {access_token}",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    })
    resp.raise_for_status()
    return resp.headers.get("x-restli-id", "")
