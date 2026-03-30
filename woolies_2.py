# pip install httpx

import httpx

API_URL = "https://www.woolworths.co.nz/api/v1/products"
BASE_URL = "https://www.woolworths.co.nz"

STORE_ID = 9023  # your store (e.g., Mt Roskill)
SEARCH = input("Search for a product: ").strip()

def init_session(store_id: int):
    """Initialize a session with Woolworths and set the store cookie."""
    client = httpx.Client(
        headers={
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "OnlineShopping.WebApp",
            "referer": "https://www.woolworths.co.nz/shop/searchproducts"
        }
    )
    # Step 1: Hit the homepage to get base cookies
    client.get(BASE_URL)
    # Step 2: Force store selection
    client.cookies.set(
        "fulfilmentStoreId",
        str(store_id),
        domain=".woolworths.co.nz"
    )

    return client

def search_products(client: httpx.Client, query: str):
    """Search for products in the store and return a sorted list by price."""
    params = {
        "target": "search",
        "search": query,
        "size": 48
    }

    response = client.get(API_URL, params=params)
    data = response.json()
    products = data.get("products", {}).get("items", [])

    def get_price(p):
        price_data = p.get("price", {})
        return price_data.get("salePrice") or price_data.get("originalPrice")

    valid_products = [p for p in products if get_price(p) is not None]
    valid_products.sort(key=get_price)

    return valid_products

session = init_session(STORE_ID)
products = search_products(session, SEARCH)

print(f"\nResults for '{SEARCH}' (Store {STORE_ID}):\n")
print(f"{'PRODUCT':<50} PRICE")
print("─" * 58)

for p in products:
    name = p["name"][:48]
    price_data = p["price"]
    price = price_data.get("salePrice") or price_data.get("originalPrice")
    print(f"{name:<50} ${price:.2f}")

print("─" * 58)

if products:
    cheapest = products[0]
    cheapest_price = cheapest["price"].get("salePrice") or cheapest["price"].get("originalPrice")
    print(f"\nCheapest: {cheapest['name']} — ${cheapest_price:.2f}\n")
else:
    print("No products found.")