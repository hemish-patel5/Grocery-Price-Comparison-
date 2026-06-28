from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

app = Flask(__name__)
CORS(app)


PAKNSAVE_STORE_ID   = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"
NEWWORLD_STORE_ID   = "7508cf88-9fd0-4e71-b2f2-d564b1decf8d"

WOOLWORTHS_STORE_ID = 9109
WOOLWORTHS_DEFAULT_ADDRESS = "Woolworths Botany"
PAGES_TO_FETCH = 9
FOODSTUFFS_HITS_PER_PAGE = 48
WOOLWORTHS_PAGE_SIZE = 48
WOOLWORTHS_MAX_PAGES = 100


def get_path(data, path):
    value = data
    for key in path:
        if isinstance(value, dict):
            value = value.get(key)
            continue

        if isinstance(value, list) and isinstance(key, int):
            if key >= len(value):
                return None
            value = value[key]
            continue

        return None
    return value


def first_value(data, paths):
    for path in paths:
        value = get_path(data, path)
        if value not in (None, ""):
            return value
    return None


def format_price(value):
    if value is None:
        return None

    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return None


def find_image_url(data):
    image_keys = {
        "image",
        "imageUrl",
        "imageURL",
        "imageUri",
        "imagePath",
        "productImage",
        "productImageUrl",
        "thumbnail",
        "thumbnailUrl",
    }
    url_keys = ("url", "href", "src", "big", "large", "medium", "small")

    if isinstance(data, dict):
        for url_key in url_keys:
            value = data.get(url_key)
            if isinstance(value, str) and value:
                return value

        for key in image_keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                for url_key in url_keys:
                    nested_value = value.get(url_key)
                    if isinstance(nested_value, str) and nested_value:
                        return nested_value
            if isinstance(value, list):
                found = find_image_url(value)
                if found:
                    return found

        for key in ("images", "productImages", "media"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for url_key in url_keys:
                            nested_value = item.get(url_key)
                            if isinstance(nested_value, str) and nested_value:
                                return nested_value

                    found = find_image_url(item)
                    if found:
                        return found
            else:
                found = find_image_url(value)
                if found:
                    return found

        for value in data.values():
            found = find_image_url(value)
            if found:
                return found

    if isinstance(data, list):
        for item in data:
            found = find_image_url(item)
            if found:
                return found

    return None


def absolute_url(value, base_url):
    if not value:
        return None
    return urljoin(base_url, str(value))


def woolworths_product_url(product_id, slug):
    if not product_id:
        return None

    if slug:
        return f"https://www.woolworths.co.nz/shop/productdetails/{product_id}/{slug}"

    return f"https://www.woolworths.co.nz/shop/productdetails/{product_id}"


def format_unit_price(price, measure):
    formatted_price = format_price(price)
    if not formatted_price:
        return None
    if not measure:
        return formatted_price
    return f"{formatted_price} / {measure}"


def parse_store_id(value, default_store_id):
    if value in (None, ""):
        return default_store_id

    try:
        return int(value)
    except (TypeError, ValueError):
        return default_store_id


def dedupe_products(products):
    seen = set()
    deduped = []

    for product in products:
        key = (
            product.get("store"),
            product.get("product_id") or product.get("barcode") or product.get("name"),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(product)

    return deduped


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

                products_response = res.json().get("products", {})
                total_items = products_response.get("totalItems")
                page_items = products_response.get("items", [])
                page_products = [
                    item for item in page_items
                    if item.get("type") == "Product"
                ]
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
                print(
                    f"Woolworths page {page}: "
                    f"raw={len(page_items)}, "
                    f"products={len(page_products)}, "
                    f"new={len(new_products)}, "
                    f"total={len(raw_products)}, "
                    f"expected={total_items}"
                )

                if total_items is not None and len(raw_products) >= total_items:
                    break

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
    


def search_paknsave(query):
    try:
        with httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=15.0
        ) as client:
            token_res = client.post("https://www.paknsave.co.nz/api/user/get-current-user")
            token_res.raise_for_status()
            token = token_res.json().get("access_token")

            raw_products = []

            for page in range(PAGES_TO_FETCH):
                search_res = client.post(
                    "https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products",
                    json={
                        "storeId": PAKNSAVE_STORE_ID,
                        "hitsPerPage": FOODSTUFFS_HITS_PER_PAGE,
                        "page": page,
                        "sortOrder": "NI_POPULARITY_ASC",
                        "algoliaFacetQueries": [],
                        "algoliaQuery": {
                            "query": query,
                            "hitsPerPage": FOODSTUFFS_HITS_PER_PAGE,
                            "page": page,
                            "filters": f"stores:{PAKNSAVE_STORE_ID}",
                            "attributesToHighlight": [],
                        },
                    },
                    headers={"authorization": f"Bearer {token}"}
                )
                search_res.raise_for_status()

                page_products = search_res.json().get("products", [])
                if not page_products:
                    break

                raw_products.extend(page_products)

            def normalize_product(p):
                single_price = p.get("singlePrice", {})
                product_path = first_value(p, [
                    ("url",),
                    ("productUrl",),
                    ("productURL",),
                    ("slug",),
                ])

                return {
                    "name": p.get("name", "Unknown"),
                    "price": format_price(single_price.get("price", 0) / 100),
                    "store": "PAK'nSAVE",
                    "product_id": first_value(p, [
                        ("productId",),
                        ("productID",),
                        ("id",),
                        ("sku",),
                        ("barcode",),
                    ]),
                    "brand": first_value(p, [
                        ("brand",),
                        ("brandName",),
                        ("manufacturer",),
                    ]),
                    "size": first_value(p, [
                        ("size",),
                        ("packageSize",),
                        ("displaySize",),
                        ("unit",),
                    ]),
                    "unit_price": first_value(p, [
                        ("unitPrice",),
                        ("pricePerUnit",),
                        ("singlePrice", "unitPrice"),
                        ("singlePrice", "pricePerUnit"),
                    ]),
                    "image_url": absolute_url(find_image_url(p), "https://www.paknsave.co.nz"),
                    "product_url": absolute_url(product_path, "https://www.paknsave.co.nz"),
                    "is_on_special": bool(first_value(p, [
                        ("hasPromotion",),
                        ("promotion",),
                        ("promotions",),
                        ("special",),
                    ])),
                    "source_store_id": PAKNSAVE_STORE_ID,
                }

            return [
                normalize_product(p)
                for p in dedupe_products(raw_products)
            ]
    except Exception as e:
        print(f"PAK'nSAVE error: {e}")
        return []


def search_newworld(query):
    try:
        with httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=15.0
        ) as client:
            token_res = client.post("https://www.newworld.co.nz/api/user/get-current-user")
            token_res.raise_for_status()
            token = token_res.json().get("access_token")

            raw_products = []

            for page in range(PAGES_TO_FETCH):
                search_res = client.post(
                    "https://api-prod.newworld.co.nz/v1/edge/search/paginated/products",
                    json={
                        "storeId": NEWWORLD_STORE_ID,
                        "hitsPerPage": FOODSTUFFS_HITS_PER_PAGE,
                        "page": page,
                        "sortOrder": "NI_POPULARITY_ASC",
                        "algoliaFacetQueries": [],
                        "algoliaQuery": {
                            "query": query,
                            "hitsPerPage": FOODSTUFFS_HITS_PER_PAGE,
                            "page": page,
                            "filters": f"stores:{NEWWORLD_STORE_ID}",
                            "attributesToHighlight": [],
                        },
                    },
                    headers={"authorization": f"Bearer {token}"}
                )
                search_res.raise_for_status()

                page_products = search_res.json().get("products", [])
                if not page_products:
                    break

                raw_products.extend(page_products)

            def normalize_product(p):
                single_price = p.get("singlePrice", {})
                product_path = first_value(p, [
                    ("url",),
                    ("productUrl",),
                    ("productURL",),
                    ("slug",),
                ])

                return {
                    "name": p.get("name", "Unknown"),
                    "price": format_price(single_price.get("price", 0) / 100),
                    "store": "New World",
                    "product_id": first_value(p, [
                        ("productId",),
                        ("productID",),
                        ("id",),
                        ("sku",),
                        ("barcode",),
                    ]),
                    "brand": first_value(p, [
                        ("brand",),
                        ("brandName",),
                        ("manufacturer",),
                    ]),
                    "size": first_value(p, [
                        ("size",),
                        ("packageSize",),
                        ("displaySize",),
                        ("unit",),
                    ]),
                    "unit_price": first_value(p, [
                        ("unitPrice",),
                        ("pricePerUnit",),
                        ("singlePrice", "unitPrice"),
                        ("singlePrice", "pricePerUnit"),
                    ]),
                    "image_url": absolute_url(find_image_url(p), "https://www.newworld.co.nz"),
                    "product_url": absolute_url(product_path, "https://www.newworld.co.nz"),
                    "is_on_special": bool(first_value(p, [
                        ("hasPromotion",),
                        ("promotion",),
                        ("promotions",),
                        ("special",),
                    ])),
                    "source_store_id": NEWWORLD_STORE_ID,
                }

            return [
                normalize_product(p)
                for p in dedupe_products(raw_products)
            ]
    except Exception as e:
        print(f"New World error: {e}")
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
