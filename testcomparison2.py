# pip install httpx

import httpx

API_URL = "https://www.woolworths.co.nz/api/v1/products"

HEADERS = {
    "accept":           "application/json, text/plain, */*",
    "accept-language":  "en-NZ,en;q=0.9",
    "user-agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "x-requested-with": "OnlineShopping.WebApp",
}

search_item = input("What would you like to sesarch for: ").strip()

PARAMS = {
    "target":              "search",
    "search":              search_item,
    "inStockProductsOnly": "false",
    "size":                48,
}


def fetch_items():
    print("Fetching", search_item, "prices from Woolworths NZ...\n")

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            r = client.get(API_URL, headers=HEADERS, params=PARAMS)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return

    items = data.get("products", {}).get("items") or data.get("items") or []
    products = [p for p in items if p.get("type") == "Product"]

    if not products:
        print("No products returned.")
        return

    def get_price(p):
        pr = p.get("price", {})
        return pr.get("salePrice") or pr.get("originalPrice") or 999

    products.sort(key=get_price)

    print(f"{'PRODUCT':<52} {'PRICE':>7}  {'UNIT PRICE':<18}  NOTE")
    print("─" * 90)

    for p in products:
        name       = p.get("name", "Unknown")[:50]
        price      = p.get("price", {})
        sale_price = price.get("salePrice")
        orig_price = price.get("originalPrice")
        unit       = price.get("comparativePrice", "")
        unit_label = price.get("comparativeSizeMeasure", "")
        on_sale    = price.get("isSpecial", False)

        display    = sale_price or orig_price or 0
        unit_str   = f"${unit}/{unit_label}" if unit and unit_label else ""
        note       = "🔴 SALE" if on_sale else ""

        print(f"{name:<52} ${display:>5.2f}  {unit_str:<18}  {note}")

    print("─" * 90)
    print(f"\n{len(products)} products found.")

    cheapest    = products[0]
    cp          = cheapest.get("price", {})
    cheap_price = cp.get("salePrice") or cp.get("originalPrice")
    print(f"💰 Cheapest: {cheapest.get('name')} — ${cheap_price:.2f}\n")


if __name__ == "__main__":
    fetch_items()