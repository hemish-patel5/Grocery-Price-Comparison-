import httpx

STORE_ID = "7508cf88-9fd0-4e71-b2f2-d564b1decf8d"
SEARCH = input("What are you searching for: ").strip()

HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "content-type": "application/json",
    "accept": "application/json",
    "origin": "https://www.newworld.co.nz",
    "referer": "https://www.newworld.co.nz/",
}

# Step 1: Get token
login = httpx.post("https://www.newworld.co.nz/api/user/get-current-user", headers=HEADERS)
token = login.json()["access_token"]

# Step 2: Search
response = httpx.post(
    "https://api-prod.newworld.co.nz/v1/edge/search/paginated/products",
    headers={**HEADERS, "authorization": f"Bearer {token}"},
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
)
products = response.json().get("products", [])

# Step 3: Print results
print(f"\nResults for '{SEARCH}' at New World:\n")
for product in products:
    name  = product["name"]
    price = product["singlePrice"]["price"] / 100
    print(f"  {name:<48} ${price:.2f}")

if products:
    cheapest = min(products, key=lambda p: p["singlePrice"]["price"])
    print(f"\nCheapest: {cheapest['name']} — ${cheapest['singlePrice']['price'] / 100:.2f}\n")