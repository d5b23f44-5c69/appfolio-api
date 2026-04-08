"""FastAPI application — authenticated read API over scraped AppFolio listings."""
from __future__ import annotations

import hmac
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from . import config, scheduler, storage
from .config import IMAGES_DIR, SiteConfig, load_sites

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("apscheduler").setLevel(logging.INFO)
log = logging.getLogger("appfolio-api")

_BOOT_TIME = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init()
    if not config.API_KEY:
        log.warning("APPFOLIO_API_KEY is not set — all authenticated endpoints will reject requests.")
    # Start the scheduler off-loop so APScheduler's BackgroundScheduler is not
    # initialized from inside the running asyncio loop.
    import asyncio
    await asyncio.get_running_loop().run_in_executor(None, scheduler.start)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="AppFolio Listings API", version="0.1.0", lifespan=lifespan)


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if not config.API_KEY:
        raise HTTPException(status_code=503, detail="Server is missing APPFOLIO_API_KEY configuration")
    if not x_api_key or not hmac.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _site_or_404(site_key: str) -> SiteConfig:
    sites = load_sites()
    if site_key not in sites:
        raise HTTPException(status_code=404, detail=f"Unknown site '{site_key}'")
    return sites[site_key]


def _filter_and_sort(
    listings: list[dict],
    available: bool | None,
    min_beds: float | None,
    max_rent: float | None,
    sort: str | None,
) -> list[dict]:
    out = listings
    if available:
        out = [l for l in out if l.get("available_date")]
    if min_beds is not None:
        out = [l for l in out if (l.get("bedrooms") or 0) >= min_beds]
    if max_rent is not None:
        out = [l for l in out if (l.get("market_rent") or 0) <= max_rent]
    if sort == "rent":
        out = sorted(out, key=lambda l: l.get("market_rent") or 0)
    elif sort == "date":
        out = sorted(out, key=lambda l: l.get("available_date") or "9999-99-99")
    return out


@app.get("/healthz")
def healthz() -> JSONResponse:
    runs = {r["site_key"]: r for r in storage.get_scrape_runs()}
    sites = load_sites()
    now = time.time()
    stale: list[str] = []
    missing: list[str] = []
    for key, site in sites.items():
        threshold = max(site.refresh_minutes * 60 * 2, 600)
        run = runs.get(key)
        if not run:
            # Allow a grace period after boot for the initial scrape to land.
            if now - _BOOT_TIME > threshold:
                missing.append(key)
            continue
        if now - run["last_run_at"] > threshold:
            stale.append(key)
    if stale or missing:
        return JSONResponse(
            status_code=503,
            content={
                "status": "stale",
                "stale_sites": stale,
                "missing_sites": missing,
                "scrape_runs": runs,
            },
        )
    return JSONResponse({"status": "ok", "scrape_runs": runs})


@app.get("/sites", dependencies=[Depends(require_api_key)])
def list_sites() -> dict:
    sites = load_sites()
    return {
        "sites": [
            {
                "key": s.key,
                "subdomain": s.subdomain,
                "property_list": s.property_list,
                "refresh_minutes": s.refresh_minutes,
            }
            for s in sites.values()
        ]
    }


@app.get("/sites/{site_key}/listings", dependencies=[Depends(require_api_key)])
def get_listings(
    site_key: str,
    available: bool | None = Query(default=None),
    min_beds: float | None = Query(default=None),
    max_rent: float | None = Query(default=None),
    sort: str | None = Query(default=None, pattern="^(rent|date)$"),
) -> dict:
    _site_or_404(site_key)
    listings = storage.get_active_listings(site_key)
    listings = _filter_and_sort(listings, available, min_beds, max_rent, sort)
    return {"count": len(listings), "listings": listings}


@app.get("/sites/{site_key}/listings/{listable_uid}", dependencies=[Depends(require_api_key)])
def get_listing(site_key: str, listable_uid: str) -> dict:
    _site_or_404(site_key)
    listing = storage.get_listing(site_key, listable_uid)
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@app.post("/sites/{site_key}/refresh", dependencies=[Depends(require_api_key)])
def refresh_site(site_key: str) -> dict:
    site = _site_or_404(site_key)
    count = scheduler.run_scrape(site)
    return {"site": site_key, "count": count}


@app.get("/images/{path:path}", dependencies=[Depends(require_api_key)])
def get_image(path: str) -> FileResponse:
    # Prevent path traversal: resolved file must live under IMAGES_DIR.
    target = (IMAGES_DIR / path).resolve()
    if not str(target).startswith(str(Path(IMAGES_DIR).resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)
