"""
Regression smoke test for social/linkedin_client.py's image-post support.

Exists because publish_post() previously silently dropped any image_url —
it accepted the parameter but never called LinkedIn's Images API, so a
"post with photo" request quietly became a text-only post. No Flask app or
DB needed: this client is a pure requests-based API wrapper, so LinkedIn's
HTTP calls are mocked directly.

Usage: .venv/bin/python scripts/dev/smoke_test_social.py
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from social import linkedin_client as lc

lc.CLIENT_ID = "smoke-test-id"
lc.CLIENT_SECRET = "smoke-test-secret"

UPLOAD_URL = "https://upload.linkedin.com/mediaUpload/fake-signed-url"
IMAGE_URN = "urn:li:image:C4E10AQfake123"
SHARE_ID = "urn:li:share:fake456"
SOURCE_IMAGE_URL = "https://austin-apex-labeler-production.up.railway.app/social/photo/fake-token"

calls = []


def fake_post(url, json=None, headers=None, **kw):
    calls.append(("POST", url, json, headers))
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    if "initializeUpload" in url:
        resp.json.return_value = {"value": {"uploadUrl": UPLOAD_URL, "image": IMAGE_URN}}
        resp.headers = {}
    elif url.endswith("/posts"):
        resp.headers = {"x-restli-id": SHARE_ID}
    return resp


def fake_get(url, timeout=None, **kw):
    calls.append(("GET", url))
    resp = MagicMock()
    resp.content = b"fake-image-bytes"
    resp.raise_for_status = lambda: None
    return resp


def fake_put(url, data=None, headers=None, **kw):
    calls.append(("PUT", url, data, headers))
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    return resp


with patch("requests.post", side_effect=fake_post), \
     patch("requests.get", side_effect=fake_get), \
     patch("requests.put", side_effect=fake_put):
    post_id = lc.publish_post(
        "urn:li:person:abc123", "fake-access-token", "Check out this new listing!",
        image_url=SOURCE_IMAGE_URL,
    )

assert post_id == SHARE_ID

init_call = next(c for c in calls if c[0] == "POST" and "initializeUpload" in c[1])
assert init_call[2] == {"initializeUploadRequest": {"owner": "urn:li:person:abc123"}}
assert init_call[3]["Authorization"] == "Bearer fake-access-token"

get_call = next(c for c in calls if c[0] == "GET")
assert get_call[1] == SOURCE_IMAGE_URL

put_call = next(c for c in calls if c[0] == "PUT")
assert put_call[1] == UPLOAD_URL
assert put_call[2] == b"fake-image-bytes"
assert put_call[3]["Authorization"] == "Bearer fake-access-token"

posts_call = next(c for c in calls if c[0] == "POST" and c[1].endswith("/posts"))
assert posts_call[2]["content"] == {"media": {"id": IMAGE_URN}}
assert posts_call[2]["commentary"] == "Check out this new listing!"
assert posts_call[2]["author"] == "urn:li:person:abc123"

print("[ok] publish_post(image_url=...) uploads via initializeUpload -> GET source -> PUT bytes -> posts with content.media.id")

calls.clear()
with patch("requests.post", side_effect=fake_post), \
     patch("requests.get", side_effect=fake_get), \
     patch("requests.put", side_effect=fake_put):
    lc.publish_post(
        "urn:li:person:abc123", "fake-access-token", "Three listing photos",
        image_urls=[SOURCE_IMAGE_URL + suffix for suffix in ("-1", "-2", "-3")],
    )
multi_call = next(c for c in calls if c[0] == "POST" and c[1].endswith("/posts"))
images = multi_call[2]["content"]["multiImage"]["images"]
assert len(images) == 3
assert all(image == {"id": IMAGE_URN, "altText": "Property photograph"} for image in images)
assert len([c for c in calls if c[0] == "PUT"]) == 3
print("[ok] LinkedIn receives selected photos as one multi-image post")

calls.clear()
with patch("requests.post", side_effect=fake_post), \
     patch("requests.get", side_effect=fake_get), \
     patch("requests.put", side_effect=fake_put):
    post_id2 = lc.publish_post("urn:li:person:abc123", "fake-access-token", "Text only post")

assert post_id2 == SHARE_ID
posts_call2 = next(c for c in calls if c[0] == "POST" and c[1].endswith("/posts"))
assert "content" not in posts_call2[2]
assert not any(c[0] in ("GET", "PUT") for c in calls)

print("[ok] publish_post() with no image_url makes no upload calls and omits content.media")

print("ALL SOCIAL SMOKE TESTS PASSED")
