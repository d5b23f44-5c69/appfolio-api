# Frontend integration guide

This document is the contract between **`appfolio-api`** (this repo) and any
frontend that consumes it. It is meant to be enough information to build a
Cloudflare Worker / SPA / Astro site without reading the Python code.

The frontend lives in a separate repository. The two projects communicate
only over HTTPS + a shared API key.

---

## 1. Authentication

Every endpoint **except `/healthz`** requires the header:

```
X-API-Key: <shared secret>
```

Failure responses:

| Condition | Status | Body |
|---|---|---|
| Missing or wrong key | `401` | `{"detail":"Invalid or missing API key"}` |
| Server has no key configured | `503` | `{"detail":"Server is missing APPFOLIO_API_KEY configuration"}` |

The secret should be stored as a **Cloudflare Worker Secret** (or equivalent
backend env var). It must never be exposed to the browser. The Worker reads
the secret from its env and adds the header before calling the API.

```js
// Cloudflare Worker — secret bound as APPFOLIO_API_KEY
const r = await fetch(`${env.API_ORIGIN}/sites/example-site/listings`, {
  headers: { "X-API-Key": env.APPFOLIO_API_KEY },
});
```

---

## 2. Base URL

In production: `https://api.<your-domain>` (Caddy in front of FastAPI).
In local dev: `http://localhost:8080` or `http://host.docker.internal:8080`
when running `wrangler dev` against a local Docker stack.

---

## 3. Endpoints

### `GET /healthz`

**Open** (no API key). Use for uptime monitoring and to surface "stale data"
banners on the frontend.

```json
{
  "status": "ok",
  "scrape_runs": {
    "example-site": {
      "site_key": "example-site",
      "last_run_at": 1775592938.5,
      "last_status": "ok",
      "last_count": 8,
      "last_error": null
    }
  }
}
```

`last_run_at` is a unix timestamp (float, seconds). `last_status` is `"ok"` or
`"error"`. If `last_error` is non-null, the most recent scrape failed but the
prior cached data is still being served.

### `GET /sites`

List configured sites.

```json
{
  "sites": [
    {
      "key": "example-site",
      "subdomain": "examplepropertymanagement",
      "property_list": "Example Property Name",
      "refresh_minutes": 15
    }
  ]
}
```

`key` is the stable identifier the frontend should hard-code or read from
config.

### `GET /sites/{key}/listings`

Active listings for a site (units that were present in the most recent scrape).

**Query parameters** (all optional):

| Param | Type | Effect |
|---|---|---|
| `available` | bool | When `true`, only listings that have an `available_date` |
| `min_beds` | number | Minimum bedrooms |
| `max_rent` | number | Maximum monthly rent |
| `sort` | `rent` \| `date` | Sort by rent ascending, or by available_date ascending |

Response:

```json
{
  "count": 8,
  "listings": [ /* Listing[] — see §4 */ ]
}
```

### `GET /sites/{key}/listings/{listable_uid}`

Single listing by UID. `404` if not found.

### `POST /sites/{key}/refresh`

Force a scrape now. Returns `{"site": "<key>", "count": <int>}`. If a scrape
is already running for that site, the call returns `count: 0` and exits
immediately (the in-flight scrape continues). Use sparingly — the scheduler
already runs every `refresh_minutes`.

### `GET /images/{listable_uid}/{hash}.{ext}`

Returns the mirrored image bytes from disk. The path comes from
`Listing.photos[].local_url` — frontends should never construct it themselves.

---

## 4. The `Listing` schema

Every listing returned by `/sites/{key}/listings*` has this shape. All fields
may be `null` if AppFolio omitted them on a particular unit.

```ts
type Photo = {
  source_url: string;       // original AppFolio CDN URL (e.g. images.cdn.appfolio.com/...)
  local_url:  string | null; // our mirrored copy, e.g. "/images/<uid>/<sha1>.png"
};

type Listing = {
  // identity
  listable_uid:   string;   // AppFolio's UUID, stable per unit
  marketing_title: string | null; // e.g. "Example Property"
  subdomain:       string;  // e.g. "examplepropertymanagement"

  // address
  address:             string | null; // full single-line: "123 Main St Unit 4, Anytown, ST 00000"
  address_address1:    string | null;
  address_city:        string | null;
  address_state:       string | null;
  address_postal_code: string | null;

  // unit details
  market_rent:    number | null;  // monthly USD
  bedrooms:       number | null;
  bathrooms:      number | null;
  square_feet:    number | null;

  // availability
  available_date: string | null;  // ISO date "YYYY-MM-DD" (or today's date when AppFolio says "NOW")
  available_text: string | null;  // raw text exactly as AppFolio displays it ("5/10/26", "NOW")

  // long-form
  description: string | null;     // full description from the detail page

  // fees
  application_fee:  number | null;
  security_deposit: number | null;
  rental_terms_raw: string[];     // raw lines from the "Rental Terms" list, e.g. ["Rent: $1,850", ...]

  // policies
  pet_policy:         string[];   // ["Cats allowed", "Dogs allowed"]
  utilities_included: string[];   // ["common area snow removal", "Landscaping"]
  appliances:         string[];   // ["Refrigerator", "Range", ...]

  // media
  photos: Photo[];                // 1–N photos, each with both source and mirrored URL

  // links back to AppFolio
  detail_url:             string | null; // canonical AppFolio detail page
  rental_application_url: string | null; // pre-filled apply link
};
```

### Notes on specific fields

- **`available_date`** is the field to sort/filter on. It's normalized to ISO
  format. `available_text` is preserved for human display when AppFolio said
  something non-literal like "NOW" or "TBD".
- **`photos`** — every photo has both `source_url` (AppFolio CDN, may rotate)
  and `local_url` (stable mirrored copy served by `/images/...`). Frontends
  should prefer `local_url` for stability and prefetching, and fall back to
  `source_url` if `local_url` is `null` (image still downloading on first
  scrape).
- **`market_rent`** is a number, not a string. Format with `Intl.NumberFormat`
  on the frontend.
- **Pricing edge cases:** AppFolio sometimes lists units with `market_rent: 0`
  or unusual rental_terms. Treat `market_rent: null` and `0` the same in the
  UI.
- **Stale data:** `/healthz` exposes `last_run_at`. If it's older than ~2× the
  configured `refresh_minutes`, show a "data may be stale" indicator.

---

## 5. Photos and image proxying

Every photo in `Listing.photos[]` has both URLs:

```json
{
  "source_url": "https://images.cdn.appfolio.com/examplepropertymanagement/images/abc.../large.png",
  "local_url":  "/images/7fead5e8-2b02-49ff-bca9-4f048113c74e/3a33f9db….png"
}
```

- **`source_url`** is the original AppFolio CDN. Public, no auth, but URLs
  may rotate when AppFolio re-uploads — your data goes stale silently.
- **`local_url`** is the mirrored copy on the API origin. Stable forever
  (filenames are content-hashed sha1), but the API requires `X-API-Key`, so
  you can't put it directly in `<img src>` for a public site.

### Recommended: proxy `local_url` through the Worker with edge caching

Add a `/img/...` route to your Cloudflare Worker. It fetches the mirrored
image from the API (using the secret the Worker already holds) and serves
the bytes from your own domain. Cloudflare's edge cache stores them
globally, so the API origin is hit at most once per image per PoP.

```ts
// frontend Worker — add to your fetch handler
if (url.pathname.startsWith("/img/")) {
  const cache = caches.default;
  const cacheKey = new Request(url.toString());
  const hit = await cache.match(cacheKey);
  if (hit) return hit;

  // /img/<uid>/<hash>.png  →  ${API_ORIGIN}/images/<uid>/<hash>.png
  const apiUrl = `${env.API_ORIGIN}/images/${url.pathname.slice("/img/".length)}`;
  const upstream = await fetch(apiUrl, {
    headers: { "X-API-Key": env.APPFOLIO_API_KEY },
    cf: { cacheEverything: true, cacheTtl: 31536000 },
  });
  if (!upstream.ok) {
    return new Response("not found", { status: upstream.status });
  }

  const res = new Response(upstream.body, upstream);
  res.headers.set("cache-control", "public, max-age=31536000, immutable");
  res.headers.set("x-content-type-options", "nosniff");
  res.headers.delete("set-cookie");
  ctx.waitUntil(cache.put(cacheKey, res.clone()));
  return res;
}
```

In your listings rendering code, rewrite each photo's `local_url` to the
public `/img/...` path on your own domain, with a fallback to `source_url`
for the rare case where a photo was just discovered and hasn't been mirrored
yet:

```ts
function publicPhotoUrl(photo: Photo): string {
  if (photo.local_url) {
    // "/images/<uid>/<hash>.png"  →  "/img/<uid>/<hash>.png"
    return photo.local_url.replace(/^\/images\//, "/img/");
  }
  return photo.source_url;
}

// usage
listing.photos.map(p => `<img src="${publicPhotoUrl(p)}" loading="lazy" />`);
```

### Why this is the right default

| | |
|---|---|
| **Branding** | All image URLs are `your-domain.com/img/...` — your domain in the page source, not `images.cdn.appfolio.com`. |
| **Cost / performance** | After the first fetch in any PoP, every subsequent request is served from Cloudflare's edge cache — effectively free, globally fast. |
| **Stability** | sha1-hashed filenames mean a given URL points to fixed bytes forever. `cache-control: immutable` is safe. If AppFolio re-uploads a photo, the API mirror gets a new hash and a new URL automatically. |
| **No secret in the browser** | The `X-API-Key` only ever exists in the Worker env. The `<img>` tag is a plain public URL. |
| **Resilience** | If the VPS is briefly down, every cached image keeps serving from the edge with no user-visible failure. |
| **Future transforms** | The same Worker route can later resize / convert to WebP / strip EXIF before returning bytes, without touching the API. |

### When to use `source_url` directly instead

Skip the Worker proxy and point `<img>` at the AppFolio CDN only if:

- You're prototyping and don't care about branding.
- You're OK with `images.cdn.appfolio.com` showing up in DevTools and HTML.
- You're willing to accept that AppFolio could rotate or block URLs.

For a production marketing site, prefer the Worker proxy.

### When to use neither (R2/S3 mirror)

Pre-publishing photos to a Cloudflare R2 bucket and serving from
`https://images.your-domain.com` is overkill for a single property — the
sha1-hashed mirror on the VPS plus edge caching gives you the same
durability properties for zero additional infrastructure. Reach for R2 only
if you outgrow VPS disk, run many properties, or want the API origin to be
optional rather than required.

---

## 6. Rendering `llms.txt` (recommended Worker pattern)

The frontend should generate `/llms.txt` and `/llms-full.txt` dynamically by
calling this API and mixing in static marketing copy. See the architecture
discussion in the project notes — short version:

```js
async function renderLlmsTxt(env) {
  const r = await fetch(
    `${env.API_ORIGIN}/sites/example-site/listings?available=true&sort=rent`,
    { headers: { "X-API-Key": env.APPFOLIO_API_KEY } }
  );
  const { listings } = await r.json();
  const rents = listings.map(l => l.market_rent).filter(Boolean);
  const md = `# Example Property

> Short marketing tagline goes here.

**Units available:** ${listings.length}
**Rent:** $${Math.min(...rents)} – $${Math.max(...rents)}/mo
**Earliest move-in:** ${listings.map(l=>l.available_date).filter(Boolean).sort()[0] ?? "n/a"}

## Available units
${listings.map(l => `- [${l.address}](${l.detail_url}) — $${l.market_rent}/mo, ${l.bedrooms}bd/${l.bathrooms}ba`).join("\n")}
`;
  return new Response(md, {
    headers: {
      "content-type": "text/markdown; charset=utf-8",
      "cache-control": "public, max-age=600, stale-while-revalidate=3600",
    },
  });
}
```

Cache for ~5–15 min on the edge to match the backend scrape cadence.

---

## 7. Local development against this API

```bash
# in this repo
docker compose up -d

# in your frontend repo
export API_ORIGIN=http://localhost     # or http://host.docker.internal for wrangler
export APPFOLIO_API_KEY=<paste from .env>
wrangler dev
```

`/healthz` is open so you can verify connectivity without the key.

---

## 8. Versioning + breaking changes

This API is currently `0.1.0` and unversioned in the URL path. Field
additions are backwards-compatible. Field renames or removals will be
announced in `CHANGELOG.md` and bump the major version. If/when a `/v1/...`
prefix is added, the unversioned routes will continue to work for at least
one minor release.
