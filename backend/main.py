from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx
from concurrent.futures import ThreadPoolExecutor

from utils import (
    get_path,
    first_value,
    format_price,
    format_unit_price,
    parse_store_id,
    dedupe_products,
)
from paknsave import search_paknsave
from newworld import search_newworld

app = Flask(__name__)
CORS(app)


WOOLWORTHS_STORE_ID = 9109
WOOLWORTHS_DEFAULT_ADDRESS = "Woolworths Botany"
WOOLWORTHS_PAGE_SIZE = 48
WOOLWORTHS_MAX_PAGES = 100


def woolworths_product_url(product_id, slug):
    if not product_id:
        return None

    if slug:
        return f"https://www.woolworths.co.nz/shop/productdetails/{product_id}/{slug}"

    return f"https://www.woolworths.co.nz/shop/productdetails/{product_id}"


def search_woolworths(query, store_id=WOOLWORTHS_STORE_ID, address=WOOLWORTHS_DEFAULT_ADDRESS):
    try:
        store_id = parse_store_id(store_id, WOOLWORTHS_STORE_ID)

        with httpx.Client(
            headers={
                "accept": "application/json",
                "user-agent": "Mozilla/5.0",
                "x-requested-with": "OnlineShopping.WebApp",
                "referer": "https://www.woolworths.co.nz/shop/searchproducts"
            },
            timeout=10.0
        ) as client:
            client.get("https://www.woolworths.co.nz")
            client.cookies.set("fulfilmentStoreId", str(store_id), domain=".woolworths.co.nz")
            raw_products = []
            seen_product_keys = set()
            page = 1

            while page <= WOOLWORTHS_MAX_PAGES:
                res = client.get("https://www.woolworths.co.nz/api/v1/products", params={
                    "target": "search",
                    "search": query,
                    "size": WOOLWORTHS_PAGE_SIZE,
                    "page": page,
                    "inStockProductsOnly": "false",
                    "sort": "PriceAsc",
                })
                res.raise_for_status()

                page_products = res.json().get("products", {}).get("items", [])
                if not page_products:
                    break

                new_products = []
                for product in page_products:
                    product_key = (
                        product.get("sku")
                        or product.get("barcode")
                        or product.get("slug")
                        or product.get("name")
                    )

                    if product_key in seen_product_keys:
                        continue

                    seen_product_keys.add(product_key)
                    new_products.append(product)

                if not new_products:
                    break

                raw_products.extend(new_products)
                print(f"Woolworths page {page}: raw={len(page_products)}, new={len(new_products)}, total={len(raw_products)}")

                page += 1

            def get_price(p):
                price = p.get("price", {})
                return price.get("salePrice") or price.get("originalPrice")

            def normalize_product(p):
                price = p.get("price", {})
                size = p.get("size", {})
                product_id = first_value(p, [
                    ("sku",),
                    ("productId",),
                    ("productID",),
                    ("stockcode",),
                    ("id",),
                    ("barcode",),
                ])
                product_path = first_value(p, [
                    ("url",),
                    ("productUrl",),
                    ("productURL",),
                    ("slug",),
                ])

                return {
                    "name": p.get("name", "Unknown"),
                    "price": format_price(get_price(p)),
                    "original_price": format_price(price.get("originalPrice")),
                    "sale_price": format_price(price.get("salePrice")),
                    "save_price": format_price(price.get("savePrice")),
                    "store": "Woolworths",
                    "product_id": product_id,
                    "brand": first_value(p, [
                        ("brand",),
                        ("brandName",),
                        ("manufacturer",),
                    ]),
                    "size": first_value(p, [
                        ("size", "volumeSize"),
                        ("size", "cupMeasure"),
                        ("packageSize",),
                        ("unit",),
                    ]),
                    "unit_price": format_unit_price(
                        size.get("cupPrice"),
                        size.get("cupMeasure"),
                    ),
                    "image_url": get_path(p, ("images", "big")),
                    "product_url": woolworths_product_url(product_id, product_path),
                    "is_on_special": bool(price.get("isSpecial")),
                    "source_store_id": str(store_id),
                    "source_store_address": address,
                    "barcode": p.get("barcode"),
                    "variety": p.get("variety"),
                    "unit": p.get("unit"),
                    "department": first_value(p, [
                        ("departments", 0, "name"),
                    ]),
                    "availability": p.get("availabilityStatus"),
                    "stock_level": p.get("stockLevel"),
                }

            normalized_products = [
                normalize_product(p)
                for p in raw_products if get_price(p) is not None
            ]
            return dedupe_products(normalized_products)
    except Exception as e:
        print(f"Woolworths error: {e}")
        return []


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    woolworths_store_id = request.args.get("woolworths_store_id")
    woolworths_address = request.args.get("woolworths_address", WOOLWORTHS_DEFAULT_ADDRESS).strip()

    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(search_woolworths, query, woolworths_store_id, woolworths_address),
            #executor.submit(search_paknsave, query),
            #executor.submit(search_newworld, query),
        ]

        results = []
        for future in futures:
            results.extend(future.result())

    print(f"Total products found: {len(results)}")

    results.sort(key=lambda x: float(x["price"]))
    return jsonify(results)


@app.route("/api/debug/search")
def debug_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing q query parameter"}), 400

    woolworths_store_id = request.args.get("woolworths_store_id")
    woolworths_address = request.args.get("woolworths_address", WOOLWORTHS_DEFAULT_ADDRESS).strip()

    with ThreadPoolExecutor() as executor:
        futures = {
            "woolworths": executor.submit(search_woolworths, query, woolworths_store_id, woolworths_address),
            "paknsave": executor.submit(search_paknsave, query),
            "newworld": executor.submit(search_newworld, query),
        }

        supermarkets = {
            store: future.result()
            for store, future in futures.items()
        }

    return jsonify({
        "query": query,
        "counts": {
            store: len(products)
            for store, products in supermarkets.items()
        },
        "results": supermarkets,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
