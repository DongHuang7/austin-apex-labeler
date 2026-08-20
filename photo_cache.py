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

import requests
from flask import url_for

from models import UploadedPhoto, db

TIMEOUT = 10
MAX_BYTES = 15 * 1024 * 1024


def is_cached_url(url: str) -> bool:
    return "/social/photo/" in (url or "")


def _serving_url(token: str) -> str:
    return url_for("social.serve_photo", token=token, _external=True)


def _cache_one(source_url: str):
    """Downloads source_url once, reusing any existing cached copy.
    Returns our own serving URL, or None if the download failed."""
    existing = UploadedPhoto.query.filter_by(source_url=source_url).first()
    if existing:
        return _serving_url(existing.token)

    try:
        resp = requests.get(source_url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
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
