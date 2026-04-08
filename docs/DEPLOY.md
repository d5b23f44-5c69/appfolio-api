# Deployment

You can run this stack three ways: locally with a venv, fully self-contained
in Docker (recommended for production), or as a systemd service on a VPS
without Docker.

## Local development (venv, no Docker)

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
APPFOLIO_API_KEY=test .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Data lives in `./data/` (sqlite + mirrored images).

## Production (Docker compose, recommended)

The compose stack runs two containers:

| Container | Image | Role |
|---|---|---|
| `appfolio-caddy` | `caddy:2-alpine` | Public TLS terminator + reverse proxy on :80/:443 |
| `appfolio-api`   | built locally    | FastAPI + scheduler. Internal network only — never exposed on the host. |

```bash
cp .env.example .env
$EDITOR .env       # set APPFOLIO_API_KEY, CADDY_DOMAIN, CADDY_ACME_EMAIL
cp app/sites.yaml.example app/sites.yaml
$EDITOR app/sites.yaml   # add your properties
docker compose up -d --build
docker compose logs -f
```

### `.env` settings

```bash
APPFOLIO_API_KEY=<openssl rand -hex 32>
CADDY_DOMAIN=api.example.com       # real FQDN → automatic Let's Encrypt
CADDY_ACME_EMAIL=ops@example.com
```

For local Docker without TLS, set `CADDY_DOMAIN=localhost` and curl
`http://localhost`.

### What you get

- **Caddy on :443** with automatic Let's Encrypt certs (HTTP-01 + ALPN-01).
- **HTTP→HTTPS redirect** on :80 (Caddy default for real FQDNs).
- **API not exposed on the host** — only Caddy is. The api container only
  publishes its port to the internal compose network.
- **Healthcheck-gated startup** — Caddy waits until `/healthz` returns 200.
- **Persistent volumes:** `appfolio-data` (sqlite + images), `caddy-data`
  (Let's Encrypt certs and account), `caddy-config`.
- **`sites.yaml` mounted read-only** so editing it + `docker compose restart
  appfolio-api` picks up changes without rebuilding the image.

### Adding a new property

```yaml
# app/sites.yaml
sites:
  my-property:
    subdomain: someappfoliosubdomain
    property_list: "Property Name From AppFolio"
    refresh_minutes: 15
```

```bash
docker compose restart appfolio-api
```

### DNS / firewall

Point your FQDN's A/AAAA records at the VPS. Open ports 80, 443 (TCP + UDP
for HTTP/3) on the host firewall. Nothing else needs to be open.

### Backups

Everything mutable lives in two named volumes:

```bash
docker run --rm -v appfolio-api_appfolio-data:/data -v "$PWD:/backup" \
  alpine tar czf /backup/appfolio-data.tar.gz -C / data
docker run --rm -v appfolio-api_caddy-data:/data -v "$PWD:/backup" \
  alpine tar czf /backup/caddy-data.tar.gz -C / data
```

`appfolio-data.tar.gz` is the only one with state you can't recreate
(scrape history + mirrored photos).

## Cloudflare in front of the API

The frontend (separate repo, hosted on Cloudflare Pages/Workers) calls this
API with a shared secret. Add a Worker (or Transform Rule) on the API
hostname that injects `X-API-Key` so the browser never sees it:

```js
// Cloudflare Worker — bind APPFOLIO_API_KEY as a Worker Secret
export default {
  async fetch(request, env) {
    const upstream = new Request(request);
    upstream.headers.set("X-API-Key", env.APPFOLIO_API_KEY);
    return fetch(upstream);
  },
};
```

The secret on the VPS (`APPFOLIO_API_KEY` in `.env`) and the Worker secret
must match.

For defense-in-depth, restrict inbound 443 on the VPS to Cloudflare IP
ranges (<https://www.cloudflare.com/ips/>) so only Cloudflare can reach
your origin.

See [`FRONTEND.md`](./FRONTEND.md) for the full API contract a frontend
should code against.

## VPS without Docker (systemd)

If you don't want Docker, the `systemd/` directory has a unit file.

```bash
sudo useradd -r -s /usr/sbin/nologin appfolio
sudo mkdir -p /opt/appfolio-api && sudo chown appfolio:appfolio /opt/appfolio-api
sudo -u appfolio git clone <this-repo> /opt/appfolio-api
cd /opt/appfolio-api
sudo -u appfolio python3 -m venv .venv
sudo -u appfolio .venv/bin/pip install -e .

sudo tee /etc/appfolio-api.env >/dev/null <<EOF
APPFOLIO_API_KEY=$(openssl rand -hex 32)
EOF
sudo chmod 600 /etc/appfolio-api.env

sudo cp systemd/appfolio-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now appfolio-api
```

You'll still want a TLS terminator (Caddy or Nginx) in front, the same way
the Docker stack does it.
