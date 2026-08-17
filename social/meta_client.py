"""
Facebook Page + Instagram Business publishing via the Meta Graph API.

Requires META_APP_ID / META_APP_SECRET config vars (a "Web application"-
equivalent Meta app, Business-verified, with pages_manage_posts and
instagram_content_publish granted through App Review — see the Phase 2
notes in the project plan). None of this can be exercised end-to-end until
that approval lands; until then routes/social.py's /social/accounts/connect
will fail with a clear "not configured" error rather than a confusing one.
"""
import os
from datetime import datetime, timedelta, timezone

import requests

GRAPH_API_VERSION = "v21.0"
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

APP_ID = os.environ.get("META_APP_ID")
APP_SECRET = os.environ.get("META_APP_SECRET")

SCOPES = ["pages_show_list", "pages_manage_posts", "pages_read_engagement", "instagram_content_publish"]


def is_configured() -> bool:
    return bool(APP_ID and APP_SECRET)


def build_oauth_url(redirect_uri: str, state: str) -> str:
    if not is_configured():
        raise RuntimeError("META_APP_ID/META_APP_SECRET are not set — Meta app isn't provisioned yet.")
    params = {
        "client_id": APP_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": ",".join(SCOPES),
        "response_type": "code",
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?{query}"


def exchange_code_for_user_token(code: str, redirect_uri: str) -> str:
    resp = requests.get(f"{GRAPH_URL}/oauth/access_token", params={
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "redirect_uri": redirect_uri,
        "code": code,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_long_lived_user_token(short_lived_token: str) -> tuple:
    """Returns (token, expires_at). Long-lived user tokens last ~60 days."""
    resp = requests.get(f"{GRAPH_URL}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": short_lived_token,
    })
    resp.raise_for_status()
    data = resp.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 5184000))
    return data["access_token"], expires_at


def list_pages(user_token: str) -> list:
    """Pages this user can manage — used to let them pick which Page/IG
    account to connect after the OAuth dialog."""
    resp = requests.get(f"{GRAPH_URL}/me/accounts", params={"access_token": user_token})
    resp.raise_for_status()
    return resp.json().get("data", [])


def publish_to_facebook_page(page_id: str, page_access_token: str, message: str, image_url: str = None) -> str:
    """Returns the published post's id."""
    if image_url:
        resp = requests.post(f"{GRAPH_URL}/{page_id}/photos", data={
            "url": image_url, "caption": message, "access_token": page_access_token,
        })
    else:
        resp = requests.post(f"{GRAPH_URL}/{page_id}/feed", data={
            "message": message, "access_token": page_access_token,
        })
    resp.raise_for_status()
    return resp.json()["id"]


def publish_to_instagram(ig_user_id: str, page_access_token: str, caption: str, image_url: str) -> str:
    """Two-step publish per Meta's Content Publishing API. Returns the
    published media's id. image_url must be a publicly reachable HTTPS URL —
    MLSGrid's Media URLs should work, but verify resolution/aspect ratio
    meets Instagram's requirements before relying on this for every listing."""
    container_resp = requests.post(f"{GRAPH_URL}/{ig_user_id}/media", data={
        "image_url": image_url, "caption": caption, "access_token": page_access_token,
    })
    container_resp.raise_for_status()
    container_id = container_resp.json()["id"]

    publish_resp = requests.post(f"{GRAPH_URL}/{ig_user_id}/media_publish", data={
        "creation_id": container_id, "access_token": page_access_token,
    })
    publish_resp.raise_for_status()
    return publish_resp.json()["id"]
