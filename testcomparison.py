
import httpx

# Copied from site
COOKIES_RAW = "browserSessionId=d6872bbb-db7d-4ad1-b927-1798fb831ae1; ASP.NET_SessionId=dv515mchlikvbhhdyjj2ee4v; XSRF-TOKEN=BeTpCPWq8cCswDj0YdE8EBacaQMxf3DHDq44wUVcRimDceSVAtRAmuF3YGQXVFQU2cyBiuTnt0JxHVyhffSIW3rtmMoEXpYS5UnmCrYy8PU1:iu1-3NjCe7Rnrm0DCgkYTDVW-kV7C5fyAr7NLwTmHscDjsBC6aWkYMxVHG9-Q21OQ-Jlu-R5skecwfRhD4lImkgnFa29y0VrVhE2pcLNg581; cw-laie=7117dc518e4649ec898fa5ba4d00a2d7; AKA_A2=A"

API_URL = "https://www.woolworths.co.nz/api/v1/products"

# Copied from site
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-NZ,en;q=0.9",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "referer": "https://www.woolworths.co.nz/shop/searchproducts?search=milk",
    "x-requested-with": "OnlineShopping.WebApp",
    "x-ui-ver": "7.72.37",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

search_item = input("What would you like to sesarch for?: ").strip()

PARAMS = {
    "target": "search",
    "search": search_item,
    "inStockProductsOnly": "false",
    "size": 48,
}


def parse_cookies(raw: str) -> dict:
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def fetch_items():
    print("Fetching", search_item, "prices from Woolworths NZ...\n")

    cookies = parse_cookies(COOKIES_RAW) if COOKIES_RAW else {}

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            r = client.get(API_URL, headers=HEADERS, params=PARAMS, cookies=cookies)

            if r.status_code == 401:
                print("❌ 401 - Needs auth.")
                print("   DevTools → Network → find the search request")
                print("   → Request Headers → copy 'cookie' into COOKIES_RAW above.\n")
                return

            if r.status_code == 403:
                print("❌ 403 - Access denied.")
                print("   Paste your cookie string into COOKIES_RAW at the top of this script.\n")
                return

            r.raise_for_status()
            data = r.json()

    except Exception as e:
        print(f"❌ Request failed: {e}")
        return

    items = (
        data.get("products", {}).get("items")
        or data.get("items")
        or []
    )
    products = [p for p in items if p.get("type") == "Product"]

    if not products:
        print("No products returned. Raw response preview:")
        print(str(data)[:500])
        return

    def get_price(p):
        pr = p.get("price", {})
        return pr.get("salePrice") or pr.get("originalPrice") or 999

    products.sort(key=get_price)

    print(f"{'PRODUCT':<52} {'PRICE':>7}  {'UNIT PRICE':<18}  NOTE")
    print("─" * 90)

    for p in products:
        name        = p.get("name", "Unknown")[:50]
        price       = p.get("price", {})
        sale_price  = price.get("salePrice")
        orig_price  = price.get("originalPrice")
        unit        = price.get("comparativePrice", "")
        unit_label  = price.get("comparativeSizeMeasure", "")
        on_sale     = price.get("isSpecial", False)

        display     = sale_price or orig_price or 0
        unit_str    = f"${unit}/{unit_label}" if unit and unit_label else ""
        note        = "🔴 SALE" if on_sale else ""

        print(f"{name:<52} ${display:>5.2f}  {unit_str:<18}  {note}")

    print("─" * 90)
    print(f"\n{len(products)} products found.")

    cheapest    = products[0]
    cp          = cheapest.get("price", {})
    cheap_price = cp.get("salePrice") or cp.get("originalPrice")
    print(f"💰 Cheapest: {cheapest.get('name')} — ${cheap_price:.2f}\n")


if __name__ == "__main__":
    fetch_items()