import httpx

STORE_ID = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"
SEARCH = input("What are you searching for: ").strip()

headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "content-type": "application/json",
}

# Step 1: Get token
token_response = httpx.post(
    "https://www.paknsave.co.nz/api/user/get-current-user",
    headers=headers
)
token = token_response.json()["access_token"]

# Step 2: Search
search_response = httpx.post(
    "https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products",
    json={
        "storeId": STORE_ID,
        "hitsPerPage": 48,
        "page": 0,
        "sortOrder": "NI_POPULARITY_ASC",
        "algoliaFacetQueries": [],
        "algoliaQuery": {
            "query": SEARCH,
            "hitsPerPage": 48,
            "page": 0,
            "filters": f"stores:{STORE_ID}",
            "attributesToHighlight": [],
        },
    },
    headers={**headers, "authorization": f"Bearer {token}"},
)
products = search_response.json().get("products", [])

# Step 3: Print results
print(f"\nResults for '{SEARCH}' at Pak'nSave:\n")
print(f"{'PRODUCT':<50} PRICE")
print("─" * 58)

for product in products:
    name = product["name"][:48]
    price = product["singlePrice"]["price"] / 100
    print(f"{name:<50} ${price:.2f}")

print("─" * 58)
print(f"{len(products)} products found")

if products:
    cheapest = min(products, key=lambda p: p["singlePrice"]["price"])
    print(f"\nCheapest: {cheapest['name']} — ${cheapest['singlePrice']['price'] / 100:.2f}\n")