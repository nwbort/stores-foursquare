#!/usr/bin/env python3
"""
Fetch Four Square store locations and details from the store finder page.

Unlike New World and PAK'nSAVE, Four Square has no store API: the store finder
on www.foursquare.co.nz is server-rendered by Next.js. Requesting the page with
an "RSC: 1" header returns the React Server Components payload, which embeds a
"stores" array with every store's address, coordinates, services and opening
hours. That array is extracted in a single request, so there is no separate
per-store details step.

Writes:
  foursquare.co.nz-store-finder.json   stores array extracted from the page
  foursquare.co.nz-stores.json         summary list: id, sitecoreId, name, region, url
  store-details/{id}.json              one file per store
  foursquare.co.nz-store-details.json  all store details combined, sorted by id

Store ids are the store GUIDs, lowercased without braces.

Usage:
  python3 fetch_stores.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

PAGE_URL = "https://www.foursquare.co.nz/store-finder"

ROW_ID = re.compile(rb"([0-9a-f]+):")

RAW_JSON = "foursquare.co.nz-store-finder.json"
STORES_JSON = "foursquare.co.nz-stores.json"
DETAILS_DIR = "store-details"
COMBINED_JSON = "foursquare.co.nz-store-details.json"

# Refuse to overwrite existing data if the response looks truncated
MIN_STORES = 150

MAX_RETRIES = 3
RETRY_BACKOFF = [5, 10, 20]  # seconds between retries

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-NZ,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "RSC": "1",
}


def fetch():
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            delay = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            print(f"Retrying in {delay}s ({last_error})")
            time.sleep(delay)

        req = urllib.request.Request(PAGE_URL, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            if e.code not in (403, 429, 500, 502, 503, 504):
                break  # non-retryable
        except urllib.error.URLError as e:
            last_error = f"URL error: {e.reason}"
        except Exception as e:
            last_error = str(e)

    sys.exit(f"Error: failed to fetch {PAGE_URL}: {last_error}")


def extract_stores(payload):
    """Return the first "stores" array in the RSC payload whose entries have a storeId."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'"stores":\[', payload):
        try:
            stores, _ = decoder.raw_decode(payload, match.end() - 1)
        except json.JSONDecodeError:
            continue
        if stores and all(isinstance(s, dict) and s.get("storeId") for s in stores):
            return stores
    sys.exit("Error: no stores array found in store finder payload")


def text_rows(payload):
    """
    Return {row id: text} for the text ("T") rows of an RSC payload.

    Each row is "<hex id>:<data>". Most rows end at a newline, but a text row
    is "<hex id>:T<hex byte length>,<text>" with no terminator, so the payload
    has to be walked row by row. Long strings such as store descriptions are
    emitted as text rows and referenced from JSON as "$<hex id>".
    """
    rows = {}
    pos = 0
    while pos < len(payload):
        m = ROW_ID.match(payload, pos)
        if not m:
            sys.exit(f"Error: unexpected RSC payload format at byte {pos}")
        pos = m.end()
        if payload[pos:pos + 1] == b"T":
            comma = payload.index(b",", pos)
            length = int(payload[pos + 1:comma], 16)
            rows[m.group(1).decode()] = payload[comma + 1:comma + 1 + length].decode("utf-8")
            pos = comma + 1 + length
        else:
            newline = payload.find(b"\n", pos)
            pos = len(payload) if newline == -1 else newline + 1
    return rows


def resolve(value, texts):
    """Resolve RSC string encodings: text row references, "$undefined" and "$$" escapes."""
    if isinstance(value, dict):
        return {k: resolve(v, texts) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, texts) for v in value]
    if isinstance(value, str) and value.startswith("$"):
        if value == "$undefined":
            return None
        if value.startswith("$$"):
            return value[1:]
        if value[1:] in texts:
            return texts[value[1:]]
    return value


def store_key(store):
    return store["storeId"].strip("{}").lower()


def detail_path(store_id):
    return os.path.join(DETAILS_DIR, f"{store_id}.json")


def main():
    payload = fetch()
    stores_list = resolve(extract_stores(payload.decode("utf-8")), text_rows(payload))

    details = {store_key(s): s for s in stores_list}

    if len(details) < MIN_STORES:
        sys.exit(f"Error: only {len(details)} stores returned, expected at least {MIN_STORES}")

    with open(RAW_JSON, "w") as f:
        json.dump(stores_list, f, indent=2)

    stores = []
    for store_id in sorted(details):
        store = details[store_id]
        contact = store.get("contactDetails") or {}
        stores.append({
            "id": store_id,
            "sitecoreId": store.get("sitecoreId"),
            "name": store.get("title"),
            "region": contact.get("region"),
            "url": store.get("url"),
        })
    with open(STORES_JSON, "w") as f:
        json.dump(stores, f, indent=2)
    print(f"Saved {len(stores)} stores to {STORES_JSON}")

    os.makedirs(DETAILS_DIR, exist_ok=True)
    for store_id, entry in details.items():
        with open(detail_path(store_id), "w") as f:
            json.dump(entry, f, indent=2)

    # Drop detail files for stores no longer listed on the store finder
    removed = 0
    for fname in os.listdir(DETAILS_DIR):
        if fname.endswith(".json") and fname[:-5] not in details:
            os.remove(os.path.join(DETAILS_DIR, fname))
            removed += 1
    print(f"Wrote {len(details)} files to {DETAILS_DIR}/ ({removed} removed)")

    with open(COMBINED_JSON, "w") as f:
        json.dump([details[i] for i in sorted(details)], f, indent=2)
    print(f"Rebuilt {COMBINED_JSON} with {len(details)} stores.")


if __name__ == "__main__":
    main()
