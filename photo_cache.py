"""
Downloads MLS listing photos once and re-serves them from our own storage,
instead of ever hotlinking mlsgrid.com's Media URLs directly in a page or
email. Those URLs are technically public but proved unreliable to hotlink
in practice (intermittent 503s depending on the requesting network) — and
since Facebook/Instagram/LinkedIn also fetch the image server-side when
publishing, an unreliable third-party host means unreliable posts too.
Reuses UploadedPhoto/social.serve_photo, same as manually-uploaded photos.
"""
import secrets
import time

import requests
from flask import url_for

from models import UploadedPhoto, db

TIMEOUT = 10
MAX_BYTES = 15 * 1024 * 1024
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def is_cached_url(url: str) -> bool:
    return "/social/photo/" in (url or "")


def _serving_url(token: str) -> str:
    return url_for("social.serve_photo", token=token, _external=True)


def _cache_one(source_url: str, retries: int = 0):
    """Downloads source_url once, reusing any existing cached copy.
    Returns our own serving URL, or None if the download failed."""
    existing = UploadedPhoto.query.filter_by(source_url=source_url).first()
    if existing:
        return _serving_url(existing.token)

    resp = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(source_url, timeout=TIMEOUT)
            resp.raise_for_status()
            break
        except requests.HTTPError as exc:
            # MLS Grid's signed media host has a low burst limit and does
            # not provide Retry-After. A short increasing pause makes the
            # refresh operation reliable instead of caching only whichever
            # cover happened to win the first request slot.
            if exc.response is not None and exc.response.status_code == 429 and attempt < retries:
                time.sleep(1.25 * (attempt + 1))
                continue
            return None
        except requests.RequestException:
            return None

    if resp is None:
        return None

    if len(resp.content) > MAX_BYTES:
        return None

    photo = UploadedPhoto(
        token=secrets.token_urlsafe(24),
        content_type=resp.headers.get("Content-Type", "image/jpeg"),
        data=resp.content,
        source_url=source_url,
    )
    db.session.add(photo)
    db.session.flush()
    return _serving_url(photo.token)


def cache_urls(urls: list) -> list:
    """Caches any raw MLS URLs in `urls`, leaving already-cached URLs
    untouched. Order is preserved; URLs that fail to download are dropped."""
    if not urls:
        return urls
    cached = [u if is_cached_url(u) else _cache_one(u) for u in urls]
    return [u for u in cached if u]


def cache_cover(urls: list):
    """Cache one listing cover without overwhelming the MLS media host.

    A listing occasionally has a broken first media item, so try up to the
    first three. Requests are retried on MLS 429 responses; successful
    covers are retained by the refresh route and never downloaded again.
    """
    for url in (urls or [])[:3]:
        cached = url if is_cached_url(url) else _cache_one(url, retries=3)
        if cached:
            return cached
    return None


def ensure_cached(listing) -> list:
    """Idempotently caches a Listing's photo_urls and persists the cached
    URLs back onto the row, so each MLS photo is only ever downloaded once
    across the listing's whole lifetime."""
    urls = listing.photo_urls or []
    if not urls or all(is_cached_url(u) for u in urls):
        return urls

    cached = cache_urls(urls)
    listing.photo_urls = cached
    db.session.commit()
    return cached


def store_uploaded_files(files, uploaded_by=None, social_post_id=None):
    """Validates and stores a batch of manually-uploaded files (werkzeug
    FileStorage objects, e.g. from request.files.getlist(...)) as
    UploadedPhoto rows. Shared by social posts (routes/social.py's
    upload_photo(), tagged with social_post_id) and campaign emails
    (routes/campaigns.py's upload_general_photo(), untagged — general
    emails have no persisted row to tag until Send is clicked).
    Returns (new_urls, skipped) where skipped is a list of
    "filename (reason)" strings for files that failed validation."""
    new_urls = []
    skipped = []
    for file in files:
        if not file or not file.filename:
            continue

        content_type = file.content_type or ""
        if not content_type.startswith("image/"):
            skipped.append(f"{file.filename} (not an image)")
            continue

        data = file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            skipped.append(f"{file.filename} (over 8MB)")
            continue

        photo = UploadedPhoto(
            token=secrets.token_urlsafe(24),
            content_type=content_type,
            data=data,
            uploaded_by=uploaded_by,
            social_post_id=social_post_id,
        )
        db.session.add(photo)
        db.session.flush()
        new_urls.append(_serving_url(photo.token))

    return new_urls, skipped


def ensure_post_cached(post) -> list:
    """Returns cached photo_urls for a SocialPost. Heals a post's own
    photo_urls if they're still raw MLS links (frozen there before this
    caching existed), and falls back to the listing's current photos only
    if the post's photo_urls has never been set (None) — an explicitly
    emptied list ([], e.g. after removing the last photo) is left alone."""
    if post.photo_urls is None:
        cached = ensure_cached(post.listing) if post.listing else []
    elif all(is_cached_url(u) for u in post.photo_urls):
        return post.photo_urls
    else:
        cached = cache_urls(post.photo_urls)

    post.photo_urls = cached
    db.session.commit()
    return cached
