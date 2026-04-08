"""Background scheduling + the scrape pipeline."""
from __future__ import annotations

import logging
import threading
from typing import Iterable

from apscheduler.schedulers.background import BackgroundScheduler

from . import images, storage
from .config import SiteConfig, load_sites
from .scraper.appfolio_html import fetch_site

log = logging.getLogger(__name__)

_locks: dict[str, threading.Lock] = {}
_scheduler: BackgroundScheduler | None = None


def _lock_for(site_key: str) -> threading.Lock:
    if site_key not in _locks:
        _locks[site_key] = threading.Lock()
    return _locks[site_key]


def run_scrape(site: SiteConfig) -> int:
    """Scrape a single site, mirror its images, persist results."""
    lock = _lock_for(site.key)
    if not lock.acquire(blocking=False):
        log.warning("Scrape for %s already in progress — lock contended, skipping this fire", site.key)
        return 0
    try:
        log.info("Scraping site %s", site.key)
        try:
            listings = fetch_site(site.subdomain, site.property_list)
            listings = images.mirror_all(listings)
            count = storage.upsert_listings(site.key, listings)
            storage.record_scrape_run(site.key, "ok", count)
            log.info("Scrape ok: %s -> %d listings", site.key, count)
            return count
        except Exception as exc:  # noqa: BLE001 — record then re-raise
            log.exception("Scrape failed for %s", site.key)
            storage.record_scrape_run(site.key, "error", 0, repr(exc))
            raise
    finally:
        lock.release()


def run_all(sites: Iterable[SiteConfig]) -> None:
    for site in sites:
        try:
            run_scrape(site)
        except Exception:
            continue


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    storage.init()
    sites = load_sites()
    sched = BackgroundScheduler(timezone="UTC")
    for site in sites.values():
        sched.add_job(
            run_scrape,
            "interval",
            minutes=site.refresh_minutes,
            args=[site],
            id=f"scrape-{site.key}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=site.refresh_minutes * 60,
        )
    sched.start()
    _scheduler = sched

    # Kick off an initial scrape on a worker thread so startup isn't blocked.
    threading.Thread(target=run_all, args=(list(sites.values()),), daemon=True).start()
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
