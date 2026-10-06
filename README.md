# Scheduled scraper

For Four Square store locations, via the store finder on
https://www.foursquare.co.nz/store-finder.

Four Square has no store API; the store finder is server-rendered by Next.js.
Requesting it with an `RSC: 1` header returns the React Server Components
payload, which embeds every store with its address, coordinates, services and
opening hours, so `fetch_stores.py` writes everything in a single daily run:

- `foursquare.co.nz-store-finder.json` — stores array extracted from the page
- `foursquare.co.nz-stores.json` — summary list (id, sitecoreId, name, region, url)
- `store-details/{id}.json` — one file per store (id is the store GUID, lowercased)
- `foursquare.co.nz-store-details.json` — all store details combined
