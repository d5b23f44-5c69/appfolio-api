"""Mirror listing photos to local disk and rewrite Listing dicts to include
both the original CDN URL and our local proxy URL."""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
from urllib.parse import urlparse

import httpx

from . import storage
from .config import IMAGES_DIR

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; appfolio-api/0.1)"


def _ext_for(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    if ext:
        return ext.lower()
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed
    return ".bin"


def _hashed_name(url: str, ext: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return f"{digest}{ext}"


def mirror_listing_photos(listing: dict) -> dict:
    """Download any new photos for a listing and fill in `local_url` fields.

    Returns the listing dict with each photo's `local_url` set when available.
    """
    uid = listing["listable_uid"]
    photos = listing.get("photos") or []
    if not photos:
        return listing

    target_dir = IMAGES_DIR / uid
    target_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for photo in photos:
            src = photo.get("source_url")
            if not src:
                continue
            existing = storage.get_image_local_path(src)
            if existing and (IMAGES_DIR / existing).exists():
                photo["local_url"] = f"/images/{existing}"
                continue
            try:
                r = client.get(src)
                if r.status_code != 200:
                    log.warning("Photo %s -> %s", src, r.status_code)
                    continue
                ext = _ext_for(src, r.headers.get("content-type"))
                name = _hashed_name(src, ext)
                rel = f"{uid}/{name}"
                (IMAGES_DIR / uid / name).write_bytes(r.content)
                storage.record_image(src, uid, rel)
                photo["local_url"] = f"/images/{rel}"
            except httpx.HTTPError as exc:
                log.warning("Photo download failed %s: %s", src, exc)
    return listing


def mirror_all(listings: list[dict]) -> list[dict]:
    return [mirror_listing_photos(l) for l in listings]
