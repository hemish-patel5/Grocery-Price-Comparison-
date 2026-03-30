"""
NZ Grocery Price Comparison
Compares prices across Woolworths NZ, Pak'nSave, and New World

Install: pip install httpx
Run:     python grocery_compare.py
"""

import httpx
import sys
from typing import Optional

# ── Your Pak'nSave store ID ────────────────────────────────────────────────────
# Found in the search request payload: "storeId": "..."
# Change this to your local store if needed
PAKNSAVE_STORE_ID = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"
NEWWORLD_STORE_ID = "60928d93-06fa-4d8f-92a6-8c359e7e846d"
# ─────────────────────────────────────────────────────────────────────────────

BROWSER_HEADERS = {
    "accept":           "*/*",
    "accept-language":  "en-NZ,en;q=0.9",
    "user-agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "content-type":     "application/json",
}


# ── Token fetching ─────────────────────────────────────────────────────────────

def get_foodstuffs_token(store: str) -> Optional[str]:
    """Get a guest Bearer token from Pak'nSave or New World."""
    base = "https://www.paknsave.co.nz" if store == "paknsave" else "https://www.newworld.co.nz"
    url  = f"{base}/api/user/get-current-user"
    try:
        r = httpx.post(url, headers={**BROWSER_HEADERS, "referer": f"{base}/"}, timeout=10)
        r.raise_for_status()
        return r.json().get("access_token")
    except Exception as e:
        print(f"  ⚠️  Could not get {store} token: {e}")
        return None


# ── Store scrapers ─────────────────────────────────────────────────────────────

def search_woolworths(query: str) -> list:
    try:
        r = httpx.get(
            "https://www.woolworths.co.nz/api/v1/products",
            params={"target": "search", "search": query, "inStockProductsOnly": "false", "size": 48},
            headers={**BROWSER_HEADERS, "x-requested-with": "OnlineShopping.WebApp", "accept": "application/json"},
            timeout=15,
            follow_redirects=True,
        )
        r.raise_for_status()
        items = r.json().get("products", {}).get("items", [])
        return [_parse_woolworths(p) for p in items if p.get("type") == "Product"]
    except Exception as e:
        print(f"  ⚠️  Woolworths error: {e}")
        return []


def _parse_woolworths(item: dict) -> dict:
    price = item.get("price", {})
    return {
        "store":    "Woolworths",
        "name":     item.get("name", ""),
        "brand":    item.get("brand", ""),
        "price":    price.get("salePrice") or price.get("originalPrice") or 0,
        "was":      price.get("originalPrice"),
        "on_sale":  price.get("isSpecial", False),
        "unit_price": price.get("comparativePrice"),
        "unit":     price.get("comparativeSizeMeasure", ""),
        "url":      f"https://www.woolworths.co.nz/shop/productdetails?stockcode={item.get('sku')}",
    }


def search_foodstuffs(query: str, store: str, store_id: str) -> list:
    token = get_foodstuffs_token(store)
    if not token:
        return []

    base        = "https://www.paknsave.co.nz" if store == "paknsave" else "https://www.newworld.co.nz"
    store_label = "Pak'nSave" if store == "paknsave" else "New World"

    payload = {
        "algoliaQuery": {
            "attributesToHighlight": [],
            "attributesToRetrieve": ["productID", "Type", "sponsored", "category0NI", "category1NI", "category2NI"],
            "facets": ["brand", "category1NI", "onPromotion", "productFacets"],
            "filters": f"stores:{store_id}",
            "highlightPostTag": "__/ais-highlight__",
            "highlightPreTag": "__ais-highlight__",
            "hitsPerPage": 48,
            "maxValuesPerFacet": 100,
            "page": 0,
            "query": query,
            "analyticsTags": ["fs#WEB:desktop"],
        },
        "algoliaFacetQueries": [],
        "hitsPerPage": 48,
        "page": 0,
        "sortOrder": "NI_POPULARITY_ASC",
        "storeId": store_id,
        "tobaccoQuery": False,
    }

    try:
        r = httpx.post(
            f"https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products" if store == 'paknsave' else "https://api-prod.newworld.co.nz/v1/edge/search/paginated/products",
            json=payload,
            headers={
                **BROWSER_HEADERS,
                "authorization": f"Bearer {token}",
                "origin":        base,
                "referer":       f"{base}/",
            },
            timeout=15,
        )
        r.raise_for_status()
        products = r.json().get("products", [])
        return [_parse_foodstuffs(p, store_label) for p in products]
    except Exception as e:
        print(f"  ⚠️  {store_label} error: {e}")
        return []


def _parse_foodstuffs(item: dict, store_label: str) -> dict:
    single   = item.get("singlePrice", {})
    raw      = single.get("price", 0)
    price    = raw / 100 if raw > 100 else raw  # API returns cents e.g. 199 = $1.99
    comp     = single.get("comparativePrice", {})
    unit_price = comp.get("pricePerUnit")
    unit_price = unit_price / 100 if unit_price and unit_price > 100 else unit_price
    unit     = comp.get("measureDescription", "")
    multi    = item.get("multiBuyPrice")
    on_sale  = multi is not None
    return {
        "store":      store_label,
        "name":       item.get("name", ""),
        "brand":      item.get("brand", ""),
        "price":      price,
        "was":        None,
        "on_sale":    on_sale,
        "unit_price": unit_price,
        "unit":       unit,
        "url":        "",
    }


# ── Display ────────────────────────────────────────────────────────────────────

STORE_COLOURS = {
    "Woolworths": "\033[92m",   # green
    "Pak'nSave":  "\033[93m",   # yellow
    "New World":  "\033[91m",   # red
}
RESET  = "\033[0m"
BOLD   = "\033[1m"


def display_results(query: str, all_products: list):
    if not all_products:
        print("No results found.")
        return

    # Group by store
    by_store = {}
    for p in all_products:
        by_store.setdefault(p["store"], []).append(p)

    # Sort each store by price
    for store in by_store:
        by_store[store].sort(key=lambda p: p["price"] or 999)

    print(f"\n{BOLD}Results for \"{query}\"{RESET}")
    print(f"{'─' * 95}")

    for store, products in by_store.items():
        colour = STORE_COLOURS.get(store, "")
        print(f"\n{colour}{BOLD}  {store}{RESET}  ({len(products)} products)\n")
        print(f"  {'PRODUCT':<50} {'PRICE':>7}  {'UNIT PRICE':<16}  NOTE")
        print(f"  {'─' * 85}")
        for p in products:
            name      = p["name"][:48]
            price     = p["price"] or 0
            unit_str  = f"${p['unit_price']}/{p['unit']}" if p.get("unit_price") and p.get("unit") else ""
            note      = "🔴 SALE" if p["on_sale"] else ""
            print(f"  {name:<50} ${price:>5.2f}  {unit_str:<16}  {note}")

    # Cross-store cheapest
    print(f"\n{'─' * 95}")
    print(f"{BOLD}💰 Cheapest per store:{RESET}")
    for store, products in by_store.items():
        if products:
            p      = products[0]
            colour = STORE_COLOURS.get(store, "")
            print(f"  {colour}{store:<12}{RESET}  {p['name'][:45]:<45}  ${p['price']:.2f}")

    overall = min(all_products, key=lambda p: p["price"] or 999)
    colour  = STORE_COLOURS.get(overall["store"], "")
    print(f"\n{BOLD}🏆 Overall cheapest:{RESET}  {colour}{overall['store']}{RESET}  —  {overall['name']}  ${overall['price']:.2f}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Search for a product: ").strip()

    if not query:
        print("No search term provided.")
        return

    print(f"\nSearching for \"{query}\" across 3 stores...\n")

    import concurrent.futures
    all_products = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(search_woolworths, query):                                     "Woolworths",
            executor.submit(search_foodstuffs, query, "paknsave", PAKNSAVE_STORE_ID):     "Pak'nSave",
            executor.submit(search_foodstuffs, query, "newworld", NEWWORLD_STORE_ID):     "New World",
        }
        for future in concurrent.futures.as_completed(futures):
            store   = futures[future]
            results = future.result()
            print(f"  ✅ {store}: {len(results)} products found")
            all_products.extend(results)

    display_results(query, all_products)


if __name__ == "__main__":
    main()