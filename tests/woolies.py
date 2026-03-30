# First: pip install httpx

import httpx

API_URL = "https://www.woolworths.co.nz/api/v1/products"

search_item = input("Search for a product: ")

params = {
    "target": "search",
    "search": search_item,
    "size": 48
}

headers = {
    "accept": "application/json",
    "user-agent": "Mozilla/5.0",
    "x-requested-with": "OnlineShopping.WebApp"
}

response = httpx.get(API_URL, headers=headers, params=params)

data = response.json()

products = data.get("products", {}).get("items", [])

valid_products = []

for item in products:
    if "price" in item:
        valid_products.append(item)

def get_price(product):
    price_data = product["price"]
    if price_data.get("salePrice"):
        return price_data["salePrice"]
    return price_data.get("originalPrice")
valid_products.sort(key=get_price)

for product in valid_products:
    name = product["name"]
    price = get_price(product)
    print(name, "-", "$" + str(price))

cheapest = valid_products[0]

cheapest_price = get_price(cheapest)

print("\nCheapest:", cheapest["name"], "-", "$" + str(cheapest_price))