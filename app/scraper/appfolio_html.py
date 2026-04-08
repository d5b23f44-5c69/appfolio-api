"""Scraper for the AppFolio HTML listings page.

The AppFolio HTML listings index at `https://{subdomain}.appfolio.com/listings`
returns every unit in the management company's portfolio. We filter to a single
property by passing `filters[property_list]={name}` and only retain cards whose
listing IDs are returned by that filtered request. For each card we then GET the
detail page (`/listings/detail/{uid}`) to collect the full photo gallery and
long-form description.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .normalize import normalize_listing

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; appfolio-api/0.1)"
DEFAULT_TIMEOUT = 30.0


def _base_url(subdomain: str) -> str:
    return f"https://{subdomain}.appfolio.com"


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


_BED_BATH_RE = re.compile(r"([\d.]+)\s*bd\s*/\s*([\d.]+)\s*ba", re.I)
_RENT_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)")
_PHOTO_RE = re.compile(
    r"https://images\.cdn\.appfolio\.com/[^\"'\s]+/(?:large|original|medium)\.(?:jpe?g|png)",
    re.I,
)


def _parse_rent(text: str) -> float | None:
    m = _RENT_RE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_bed_bath(text: str) -> tuple[float | None, float | None]:
    m = _BED_BATH_RE.search(text or "")
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None


def _parse_int(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _parse_card(card, base_url: str) -> dict[str, Any] | None:
    detail_anchor = card.select_one("a[href*='/listings/detail/']")
    if not detail_anchor:
        return None
    href = detail_anchor.get("href", "")
    m = re.search(r"/listings/detail/([0-9a-f-]+)", href)
    if not m:
        return None
    uid = m.group(1)

    title_el = card.select_one(".js-listing-title")
    address_el = card.select_one(".js-listing-address")
    description_el = card.select_one(".js-listing-description")
    available_el = card.select_one(".js-listing-available")
    image_el = card.select_one(".js-listing-image")

    # Quick facts in the right-hand box.
    facts: dict[str, str] = {}
    for item in card.select(".detail-box__item"):
        label = _text(item.select_one(".detail-box__label"))
        value = _text(item.select_one(".detail-box__value"))
        if label:
            facts[label.strip().lower()] = value

    rent = _parse_rent(facts.get("rent", "")) or _parse_rent(_text(card.select_one(".js-listing-blurb-rent")))
    beds, baths = _parse_bed_bath(facts.get("bed / bath", "") or _text(card.select_one(".js-listing-blurb-bed-bath")))
    sqft = _parse_int(facts.get("square feet", ""))
    available = facts.get("available") or _text(available_el)

    apply_anchor = card.select_one(".js-listing-apply")
    apply_url = urljoin(base_url, apply_anchor["href"]) if apply_anchor and apply_anchor.has_attr("href") else None

    list_photo = None
    if image_el and image_el.get("data-original"):
        list_photo = image_el["data-original"]

    return {
        "listable_uid": uid,
        "marketing_title": _text(title_el) or None,
        "address": _text(address_el) or None,
        "market_rent": rent,
        "bedrooms": beds,
        "bathrooms": baths,
        "square_feet": sqft,
        "available_text": available or None,
        "short_description": _text(description_el) or None,
        "detail_url": urljoin(base_url, href),
        "rental_application_url": apply_url,
        "list_photo_url": list_photo,
    }


def _ul_after_h3(soup: BeautifulSoup, header_text: str) -> list[str]:
    """Find an `<h3>` whose text matches and return the items of the next `<ul>`."""
    target = header_text.strip().lower()
    for h3 in soup.find_all("h3"):
        if h3.get_text(strip=True).strip().lower() == target:
            ul = h3.find_next("ul")
            if ul:
                return [_text(li) for li in ul.select("li") if _text(li)]
    return []


def _money(text: str) -> float | None:
    return _parse_rent(text)


def _parse_rental_terms(soup: BeautifulSoup) -> dict[str, Any]:
    """Parse the `<ul class="js-show-rental-terms">` block.

    Items look like: `Rent: $1,850`, `Application Fee: $25`,
    `Security Deposit: $1,850`, `Available 5/10/26`.
    """
    out: dict[str, Any] = {
        "application_fee": None,
        "security_deposit": None,
        "rental_terms_raw": [],
    }
    ul = soup.select_one(".js-show-rental-terms")
    if not ul:
        return out
    for li in ul.select("li"):
        line = _text(li)
        out["rental_terms_raw"].append(line)
        low = line.lower()
        if "application fee" in low:
            out["application_fee"] = _money(line)
        elif "security deposit" in low or low.startswith("deposit"):
            out["security_deposit"] = _money(line)
    return out


def _parse_pet_policy(soup: BeautifulSoup) -> list[str]:
    return [_text(li) for li in soup.select(".js-pet-policy-item") if _text(li)]


def _parse_detail(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    desc_el = soup.select_one(".listing-detail__description") or soup.select_one(
        "p.desk-hidden"
    )
    description = _text(desc_el) or None

    # Photo URLs are emitted directly into the markup; the gallery uses the
    # `leads_marketing_photos/.../original.jpg` pattern, plus a fallback
    # `images/.../large.png` for properties that haven't uploaded a gallery.
    photos: list[str] = []
    seen: set[str] = set()
    for url in _PHOTO_RE.findall(html):
        if url in seen:
            continue
        seen.add(url)
        photos.append(url)

    terms = _parse_rental_terms(soup)
    pet_policy = _parse_pet_policy(soup)
    utilities = _ul_after_h3(soup, "Utilities Included")
    appliances = _ul_after_h3(soup, "Appliances")

    return {
        "long_description": description,
        "photo_urls": photos,
        "application_fee": terms["application_fee"],
        "security_deposit": terms["security_deposit"],
        "rental_terms_raw": terms["rental_terms_raw"],
        "pet_policy": pet_policy,
        "utilities_included": utilities,
        "appliances": appliances,
    }


def fetch_site(subdomain: str, property_list: str | None) -> list[dict[str, Any]]:
    """Scrape all listings for a site, returning normalized Listing dicts."""
    base = _base_url(subdomain)
    params: dict[str, str] = {}
    if property_list:
        params["filters[property_list]"] = property_list

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=DEFAULT_TIMEOUT, headers=headers, follow_redirects=True) as client:
        log.info("Fetching listings index for %s (filter=%r)", subdomain, property_list)
        r = client.get(f"{base}/listings", params=params)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select(".js-listing-item")
        log.info("Found %d listing cards", len(cards))

        results: list[dict[str, Any]] = []
        for card in cards:
            raw = _parse_card(card, base)
            if not raw:
                continue
            try:
                detail = client.get(raw["detail_url"])
                if detail.status_code == 200:
                    raw.update(_parse_detail(detail.text))
                else:
                    log.warning("Detail fetch %s -> %s", raw["detail_url"], detail.status_code)
            except httpx.HTTPError as exc:
                log.warning("Detail fetch failed for %s: %s", raw["listable_uid"], exc)
            results.append(normalize_listing(raw, subdomain=subdomain))

    return results
