# First: pip install curl_cffi

from curl_cffi import requests
STORE_ID = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"
SEARCH   = input("What are you searching for: ").strip()

# Step 1: Get a login token from Pak'nSave
token_response = requests.post(
    "https://www.paknsave.co.nz/api/user/get-current-user",
    impersonate="chrome120"
    )
token = token_response.json()["access_token"]

# Step 2: Search for products using the token
search_response = requests.post(
    "https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products",
    json={
        "storeId":             STORE_ID,
        "hitsPerPage":         48,
        "page":                0,
        "sortOrder":           "NI_POPULARITY_ASC",
        "algoliaFacetQueries": [],
        "algoliaQuery": {
            "query":                 SEARCH,
            "hitsPerPage":           48,
            "page":                  0,
            "filters":               f"stores:{STORE_ID}",
            "attributesToHighlight": [],
        },
    },
    headers={"authorization": f"Bearer {token}"},
    impersonate="chrome120"
)
products = search_response.json().get("products", [])

# Step 3: Print results
print(f"\nResults for '{SEARCH}' at Pak'nSave:\n")
print(f"{'PRODUCT':<50} PRICE")
print("─" * 58)

for product in products:
    name  = product["name"][:48]
    price = product["singlePrice"]["price"] / 100  # convert cents to dollars
    print(f"{name:<50} ${price:.2f}")

print("─" * 58)
print(f"{len(products)} products found")

cheapest       = min(products, key=lambda p: p["singlePrice"]["price"])
cheapest_name  = cheapest["name"]
cheapest_price = cheapest["singlePrice"]["price"] / 100
print(f"\n Cheapest: {cheapest_name} — ${cheapest_price:.2f}\n")