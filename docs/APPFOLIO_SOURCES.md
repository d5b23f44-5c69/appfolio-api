# AppFolio

**Auth:** None required
**Detail URL pattern:** `https://{subdomain}.appfolio.com/listings/detail/{listable_uid}`

## How to Identify an AppFolio Site

Look for these in the page source:

- "Powered by AppFolio" footer badge or image from `cdn.appfoliowebsites.com`
- Script loading `appfolio-global-scripts.js` from `cdn.appfoliowebsites.com`
- Resident portal links to `{subdomain}.appfolio.com/connect/users/sign_in`
- Duda CMS (`dmAPI`, `cdn-website.com`) with `appfolio-listings` collection references
- Apply links containing `{subdomain}.appfolio.com/listings/rental_applications/new?listable_uid=`

## How to Find a Property's Endpoint

AppFolio property websites built on Duda CMS use a **collections API** that returns JSON directly — no HTML parsing needed.

### Step 1: Find the Duda site alias

View page source and search for `SiteAlias`:
```javascript
SiteAlias: '93b8287b'
```

### Step 2: Hit the collections endpoint

```
GET https://{property-domain}/_dm/s/rt/actions/sites/{site_alias}/collections/appfolio-listings
```

**Required headers:**
- `Referer: https://{property-domain}/`
- `User-Agent: Mozilla/5.0`

The response is JSON with a `value` key containing a JSON-encoded array of listing objects.

### Step 3 (optional): Find the AppFolio subdomain

For detail pages and application links, find the management company's AppFolio subdomain from:
- Apply links on the property website containing `{subdomain}.appfolio.com`
- The `database_name` field in the collections API response

## Data Access

### 1. Duda Collections API (preferred — returns JSON)

```bash
curl -s "https://www.stockyardlofts.com/_dm/s/rt/actions/sites/93b8287b/collections/appfolio-listings" \
  -H "Referer: https://www.stockyardlofts.com/" \
  -H "User-Agent: Mozilla/5.0" | python3 -m json.tool
```

The response wraps the data in a `value` key that must be JSON-parsed:

```python
raw = json.loads(response)
listings = json.loads(raw["value"])
```

**Already filtered by property** — unlike the HTML listings page, the Duda collections API only returns listings for the specific property site.

### 2. AppFolio HTML Listings Page (fallback)

```
GET https://{subdomain}.appfolio.com/listings
```

Returns an HTML page with all available units across the management company's entire portfolio. Must be filtered by address. Use this as a fallback when the property site isn't on Duda.

### 3. Listing Detail Page

```
GET https://{subdomain}.appfolio.com/listings/detail/{listable_uid}
```

Returns a detail page for a single unit with full description, photos, and amenities.

## Response Structure (Collections API)

Each listing in the `value` array contains:

```json
{
  "uuid": "26eb32be2be242f095543e99edd00d7f",
  "data": {
    "address_address1": "215 Willow Avenue - 522-A1",
    "address_city": "Knoxville",
    "address_state": "TN",
    "address_postal_code": "37915",
    "market_rent": 1775.0,
    "square_feet": 635.0,
    "bedrooms": 1,
    "bathrooms": 1.0,
    "available_date": "2026-06-09",
    "available": true,
    "unit_template_name": "A1",
    "marketing_title": "Stockyard Lofts A1 - 1 Bedroom",
    "amenities": "Washer/Dryer, Balcony, Elevator, ...",
    "deposit": 1000.0,
    "application_fee": 75.0,
    "cats": "Cats allowed",
    "dogs": "Dogs allowed",
    "listable_uid": "c87bd36f-6766-4f23-917c-94713bbaef46",
    "database_name": "terminusre",
    "database_url": "https://terminusre.appfolio.com/",
    "portfolio_name": "Terminus Real Estate Incorporated",
    "property_lists": [{"id": 7, "name": "stockyard lofts"}],
    "photos": [{"url": "https://images.cdn.appfolio.com/..."}],
    "rental_application_url": "https://terminusre.appfolio.com/listings/rental_applications/new?listable_uid=...",
    "contact_phone_number": "(865) 383-1117",
    "contact_email_address": "info@stockyardlofts.com",
    "created_at": "2021-04-15T22:03:06.000Z",
    "updated_at": "2026-03-30T13:36:15.000Z"
  },
  "correlationId": "c87bd36f-...",
  "page_item_url": "c87bd36f-..."
}
```

### Key Fields

| Field | Description |
|-------|-------------|
| `address_address1` | Street address with unit number |
| `market_rent` | Monthly rent |
| `square_feet` | Unit square footage |
| `bedrooms` / `bathrooms` | Bed / bath count |
| `available_date` | Move-in date (ISO format) |
| `unit_template_name` | Floor plan code (e.g., "A1", "B2") |
| `marketing_title` | Descriptive name (e.g., "Stockyard Lofts A1 - 1 Bedroom") |
| `amenities` | Comma-separated amenity string |
| `deposit` / `application_fee` | Fee amounts |
| `listable_uid` | Unique ID for detail/apply links |
| `database_name` | AppFolio subdomain |
| `property_lists` | Property groupings (useful for multi-property portfolios) |
| `rent_range` | `[min, max]` array |
| `photos` | Array of `{url}` objects |

## Notes

- **Duda collections are pre-filtered.** Each property's Duda site only returns its own listings, so no address filtering is needed.
- **Requires headers.** The collections endpoint returns 403 without `Referer` and `User-Agent` headers.
- **Double JSON parsing.** The response has a `value` key containing a JSON string that must be parsed again.
- **HTML fallback.** If a property site isn't on Duda (or the collections endpoint changes), the `{subdomain}.appfolio.com/listings` HTML page is always available. Filter by address for multi-property portfolios.

## Known Properties

| Property | Domain | Site Alias | AppFolio Subdomain |
|----------|--------|-----------|-------------------|
| Stockyard Lofts | `www.stockyardlofts.com` | `93b8287b` | `terminusre` |

**Quick test (Stockyard Lofts):**

```bash
curl -s "https://www.stockyardlofts.com/_dm/s/rt/actions/sites/93b8287b/collections/appfolio-listings" \
  -H "Referer: https://www.stockyardlofts.com/" \
  -H "User-Agent: Mozilla/5.0" \
  | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); rows=json.loads(d['value']); print(f'{len(rows)} units'); [print(f\"  {r['data']['address_address1']}: \${r['data']['market_rent']:.0f}\") for r in rows]"
```

### Discovery Notes — Stockyard Lofts

The Stockyard Lofts website ([stockyardlofts.com](https://www.stockyardlofts.com/)) is built on **Duda CMS** with **AppFolio** as the property management backend. The availability page loads listings via Duda's `dmAPI.loadCollectionsAPI()` → `appfolio-listings` external collection.

**How the JSON API was found:**

1. The property site uses Duda CMS (identified by `cdn-website.com`, `dmAPI` references).
2. The listings widget calls `dmAPI.loadCollectionsAPI()` then `.data("appfolio-listings").pageSize(100).get()`.
3. The Duda runtime JS (`d-js-one-runtime-unified-desktop.min.js`) resolves this to:
   ```
   /_dm/s/rt/actions/sites/{SiteAlias}/collections/{collectionName}
   ```
4. `SiteAlias` is `93b8287b` (found in page source as `Parameters.SiteAlias`).
5. The endpoint returns JSON with the full AppFolio listing data — richer than the HTML listings page.

The AppFolio subdomain `terminusre` was confirmed from the `database_name` field in the API response and from application links on the website.
