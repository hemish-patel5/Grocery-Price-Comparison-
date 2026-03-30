"""Debug script to see raw Pak'nSave API response structure"""
import httpx
import json

PAKNSAVE_STORE_ID = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"

BROWSER_HEADERS = {
    "accept":        "*/*",
    "accept-language": "en-NZ,en;q=0.9",
    "user-agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "content-type":  "application/json",
}

# Step 1: get token
print("Getting token...")
r = httpx.post(
    "https://www.paknsave.co.nz/api/user/get-current-user",
    headers={**BROWSER_HEADERS, "referer": "https://www.paknsave.co.nz/"},
    timeout=10
)
print(f"Token status: {r.status_code}")
token = r.json().get("access_token")
print(f"Got token: {token[:30]}...\n")

# Step 2: search
payload = {
    "algoliaQuery": {
        "attributesToHighlight": [],
        "attributesToRetrieve": ["productID", "Type", "sponsored", "category0NI", "category1NI", "category2NI"],
        "facets": ["brand", "category1NI", "onPromotion", "productFacets"],
        "filters": f"stores:{PAKNSAVE_STORE_ID}",
        "highlightPostTag": "__/ais-highlight__",
        "highlightPreTag": "__ais-highlight__",
        "hitsPerPage": 5,
        "maxValuesPerFacet": 100,
        "page": 0,
        "query": "bread",
        "analyticsTags": ["fs#WEB:desktop"],
    },
    "algoliaFacetQueries": [],
    "hitsPerPage": 5,
    "page": 0,
    "sortOrder": "NI_POPULARITY_ASC",
    "storeId": PAKNSAVE_STORE_ID,
    "tobaccoQuery": False,
}

print("Searching for bread...")
r = httpx.post(
    "https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products",
    json=payload,
    headers={
        **BROWSER_HEADERS,
        "authorization": f"Bearer {token}",
        "origin":  "https://www.paknsave.co.nz",
        "referer": "https://www.paknsave.co.nz/",
    },
    timeout=15,
)
print(f"Search status: {r.status_code}")

# Print the full structure so we can see what keys exist
data = r.json()
print("\nTop-level keys:", list(data.keys()))
print("\nFull response (first 2000 chars):")
print(json.dumps(data, indent=2)[:2000])