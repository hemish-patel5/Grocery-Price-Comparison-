from curl_cffi import requests

STORE_ID = "7508cf88-9fd0-4e71-b2f2-d564b1decf8d"
SEARCH   = input("What are you searching for: ").strip()

# Step 1: Get token
token_response = requests.post(
    "https://www.newworld.co.nz/api/user/get-current-user",
    impersonate="chrome120"
)
token = token_response.json()["access_token"]

# Step 2: Search
search_response = requests.post(
    "https://api-prod.newworld.co.nz/v1/edge/search/paginated/products",
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
    headers={"authorization": f"Bearer {token}"},
    impersonate="chrome120"
)

products = search_response.json().get("products", [])

# Step 3: Print
print(f"\nResults for '{SEARCH}' at New World:\n")
print(f"{'PRODUCT':<50} PRICE")
print("─" * 58)

for product in products:
    name  = product["name"][:48]
    price = product["singlePrice"]["price"] / 100
    print(f"{name:<50} ${price:.2f}")

print("─" * 58)
print(f"{len(products)} products found")

if products:
    cheapest = min(products, key=lambda p: p["singlePrice"]["price"])
    print(f"\nCheapest: {cheapest['name']} — ${cheapest['singlePrice']['price']/100:.2f}\n")