"""Normalize raw scraped fields into a stable Listing schema."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_ADDR_PARTS_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Z]{2})\s*(?P<zip>\d{5})?$"
)


def _split_address(addr: str | None) -> dict[str, str | None]:
    if not addr:
        return {"address1": None, "city": None, "state": None, "postal_code": None}
    m = _ADDR_PARTS_RE.match(addr.strip())
    if not m:
        return {"address1": addr, "city": None, "state": None, "postal_code": None}
    return {
        "address1": m.group("street").strip(),
        "city": m.group("city").strip(),
        "state": m.group("state").strip(),
        "postal_code": m.group("zip"),
    }


def _parse_available(text: str | None) -> str | None:
    """Convert AppFolio's `5/10/26` or `NOW`/`Now` into ISO yyyy-mm-dd."""
    if not text:
        return None
    t = text.strip()
    if t.lower() in {"now", "available now"}:
        return datetime.now(timezone.utc).date().isoformat()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    return t  # leave as-is if it's something we don't recognize


def normalize_listing(raw: dict[str, Any], *, subdomain: str) -> dict[str, Any]:
    addr_parts = _split_address(raw.get("address"))
    photos: list[dict[str, str]] = []
    seen: set[str] = set()
    if raw.get("list_photo_url") and raw["list_photo_url"] not in seen:
        seen.add(raw["list_photo_url"])
        photos.append({"source_url": raw["list_photo_url"], "local_url": None})
    for url in raw.get("photo_urls") or []:
        if url in seen:
            continue
        seen.add(url)
        photos.append({"source_url": url, "local_url": None})

    return {
        "listable_uid": raw["listable_uid"],
        "marketing_title": raw.get("marketing_title"),
        "address": raw.get("address"),
        "address_address1": addr_parts["address1"],
        "address_city": addr_parts["city"],
        "address_state": addr_parts["state"],
        "address_postal_code": addr_parts["postal_code"],
        "market_rent": raw.get("market_rent"),
        "bedrooms": raw.get("bedrooms"),
        "bathrooms": raw.get("bathrooms"),
        "square_feet": raw.get("square_feet"),
        "available_date": _parse_available(raw.get("available_text")),
        "available_text": raw.get("available_text"),
        "description": raw.get("long_description") or raw.get("short_description"),
        "application_fee": raw.get("application_fee"),
        "security_deposit": raw.get("security_deposit"),
        "rental_terms_raw": raw.get("rental_terms_raw") or [],
        "pet_policy": raw.get("pet_policy") or [],
        "utilities_included": raw.get("utilities_included") or [],
        "appliances": raw.get("appliances") or [],
        "photos": photos,
        "detail_url": raw.get("detail_url"),
        "rental_application_url": raw.get("rental_application_url"),
        "subdomain": subdomain,
    }
