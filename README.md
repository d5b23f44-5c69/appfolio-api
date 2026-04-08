# appfolio-api

A small, self-contained server that scrapes apartment listings from any
AppFolio-hosted property website and serves them as authenticated JSON for a
frontend (typically a Cloudflare Worker) to render.

- **Generic** — any AppFolio site, configured in `app/sites.yaml`.
- **Live** — APScheduler refreshes each site every 15 min by default.
- **Image-mirrored** — every photo is downloaded to disk; the API returns both
  the original CDN URL and a stable local proxy URL.
- **Authenticated** — every endpoint (except `/healthz`) requires a shared
  secret in the `X-API-Key` header.
- **Self-hostable** — single `docker compose up` runs FastAPI + Caddy with
  automatic HTTPS.

## Architecture

```
[ Cloudflare Worker / browser ]
            │  X-API-Key: <secret>
            ▼  HTTPS
   ┌──────────────────────┐
   │ Caddy (TLS, :443)    │  appfolio-api stack
   └──────────┬───────────┘
              │  http (private network)
              ▼
   ┌──────────────────────┐
   │ FastAPI (uvicorn)    │
   │  - APScheduler       │
   │  - HTML scraper      │
   │  - SQLite cache      │
   │  - Image mirror      │
   └──────────┬───────────┘
              │
       /data volume
       ├─ cache.db
       └─ images/
```

## Server prerequisites (one-time, fresh VPS)

On a fresh Linux host (Ubuntu/Debian shown), install Docker via the upstream
convenience script and create a dedicated unprivileged user that owns the
deployment. **Don't run the stack as root.**

```bash
# 1. Install Docker Engine + compose plugin (Docker's official script)
curl -fsSL https://get.docker.com | sudo sh

# 2. Create a non-root user for the deployment
sudo useradd -m -s /bin/bash appfolio
sudo usermod -aG docker appfolio        # lets `appfolio` run docker without sudo

# 3. Become that user from now on
sudo -iu appfolio

# 4. Clone the repo into the user's home
git clone https://github.com/<you>/appfolio-api.git
cd appfolio-api
```

The container itself also runs as a non-root user inside Docker (uid 1000,
defined in the `Dockerfile`), so even if the host user has docker access,
the FastAPI process never runs as root.

> **Why a dedicated user?** Membership in the `docker` group is effectively
> root on the host. Keeping a separate `appfolio` account contains the blast
> radius and makes it obvious which process owns which files.

## Quick start (Docker)

As the `appfolio` user, in the cloned repo:

```bash
cp .env.example .env                       # set APPFOLIO_API_KEY, CADDY_DOMAIN
cp app/sites.yaml.example app/sites.yaml   # then edit to add your properties
docker compose up -d --build
curl -k -H "X-API-Key: $(grep API_KEY .env | cut -d= -f2)" \
     https://localhost/sites/<your-site-key>/listings | jq
```

For production, set `CADDY_DOMAIN=api.yourdomain.com` in `.env`; Caddy will
issue a Let's Encrypt cert automatically. For local dev keep
`CADDY_DOMAIN=localhost` (Caddy issues a self-signed cert — use `curl -k`).

> `app/sites.yaml` is gitignored. The loader falls back to
> `sites.yaml.example` if you don't copy it, so the stack still boots, but
> you'll want your own copy to add properties.

## Local development (no Docker)

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
APPFOLIO_API_KEY=test .venv/bin/uvicorn app.main:app --reload --port 8080
```

## Configuring properties

If you haven't already, copy the example:

```bash
cp app/sites.yaml.example app/sites.yaml
```

Then add a site to `app/sites.yaml`:

```yaml
sites:
  my-property:
    subdomain: someappfoliosubdomain         # https://someappfoliosubdomain.appfolio.com
    property_list: "Property Name In AppFolio"  # null = whole portfolio
    refresh_minutes: 15
```

Then `docker compose restart appfolio-api`. The compose file mounts
`sites.yaml` read-only so you don't need to rebuild the image.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/healthz` | open | Liveness + last scrape per site |
| GET | `/sites` | required | List configured sites |
| GET | `/sites/{key}/listings` | required | Active listings (filters: `available`, `min_beds`, `max_rent`, `sort=rent\|date`) |
| GET | `/sites/{key}/listings/{uid}` | required | Single listing |
| POST | `/sites/{key}/refresh` | required | Force a scrape now |
| GET | `/images/{path}` | required | Mirrored photo bytes |

See [`docs/FRONTEND.md`](./docs/FRONTEND.md) for the full JSON contract that frontends
should code against.

## How the scrape works

The scraper hits `https://{subdomain}.appfolio.com/listings` (filtered by
`property_list` when set), parses the listing cards, then fetches each
`/listings/detail/{uid}` page for the full photo gallery, description,
rental terms, pet policy, utilities, and appliances. See
[`docs/APPFOLIO_SOURCES.md`](./docs/APPFOLIO_SOURCES.md) for the underlying
AppFolio data-source notes (markup classes, fields, URL patterns).

## Repo layout

```
app/
  main.py           # FastAPI app, auth, routes, lifespan
  config.py         # sites.yaml + env loader
  sites.yaml        # site registry (mounted read-only in docker)
  scraper/
    appfolio_html.py  # listings + detail page parser
    normalize.py      # raw → Listing schema
  storage.py        # SQLite cache
  images.py         # photo mirror
  scheduler.py      # APScheduler interval jobs
caddy/
  Caddyfile         # reverse proxy + automatic HTTPS
docker-compose.yml
Dockerfile
systemd/            # bare-metal alternative to docker compose
docs/
  DEPLOY.md            # full production deployment guide
  FRONTEND.md          # API contract for frontend consumers
  APPFOLIO_SOURCES.md  # AppFolio markup / endpoint reference
```

## See also

- [`docs/DEPLOY.md`](./docs/DEPLOY.md) — production deploy (Docker + Caddy + Cloudflare)
- [`docs/FRONTEND.md`](./docs/FRONTEND.md) — API contract for frontend developers
- [`docs/APPFOLIO_SOURCES.md`](./docs/APPFOLIO_SOURCES.md) — AppFolio source notes
