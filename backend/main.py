from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from newworld import search_newworld
from paknsave import search_paknsave

app = Flask(__name__)
CORS(app)

WOOLWORTHS_STORES = {
    "botany": {
        "address": "Woolworths Botany",
        "areaId": 473,
        "fulfilmentStoreId": 9109,
        "pickupAddressId": 1225547,
        "locationCookie": "dm-Pickup,f-9109,a-473,s-1225547",
    },
    "carlyle": {
        "address": "Woolworths Carlyle",
        "areaId": 893,
        "fulfilmentStoreId": 9532,
        "pickupAddressId": 2770176,
        "locationCookie": "dm-Pickup,f-9532,a-893,s-2770176",
    },
}
WOOLWORTHS_DEFAULT_STORE_KEY = "botany"
WOOLWORTHS_STORE_ID = WOOLWORTHS_STORES[WOOLWORTHS_DEFAULT_STORE_KEY]["fulfilmentStoreId"]
WOOLWORTHS_DEFAULT_ADDRESS = WOOLWORTHS_STORES[WOOLWORTHS_DEFAULT_STORE_KEY]["address"]
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


def get_woolworths_store_from_request():
    store_key = request.args.get("woolworths_store", WOOLWORTHS_DEFAULT_STORE_KEY).strip().lower()
    store = dict(WOOLWORTHS_STORES.get(store_key, WOOLWORTHS_STORES[WOOLWORTHS_DEFAULT_STORE_KEY]))

    custom_store_id = request.args.get("woolworths_store_id")
    custom_address = request.args.get("woolworths_address")

    if custom_store_id:
        store["fulfilmentStoreId"] = parse_store_id(custom_store_id, store["fulfilmentStoreId"])

    if custom_address:
        store["address"] = custom_address.strip()

    return store


def woolworths_location_cookie(store):
    if store.get("locationCookie"):
        return store["locationCookie"]

    return (
        f"dm-Pickup,"
        f"f-{store.get('fulfilmentStoreId')},"
        f"a-{store.get('areaId')},"
        f"s-{store.get('pickupAddressId')}"
    )


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


def search_woolworths(query, store=None):
    try:
        store = store or WOOLWORTHS_STORES[WOOLWORTHS_DEFAULT_STORE_KEY]
        store_id = parse_store_id(store.get("fulfilmentStoreId"), WOOLWORTHS_STORE_ID)
        address = store.get("address", WOOLWORTHS_DEFAULT_ADDRESS)

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
            client.cookies.set("cw-lrkswrdjp", woolworths_location_cookie(store), domain=".woolworths.co.nz")
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
                    "source_store_area_id": store.get("areaId"),
                    "source_pickup_address_id": store.get("pickupAddressId"),
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

    woolworths_store = get_woolworths_store_from_request()

    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(search_woolworths, query, woolworths_store),
            #executor.submit(search_paknsave, query),
            #executor.submit(search_newworld, query),
        ]

        results = []
        for future in futures:
            results.extend(future.result())

    print(f"Total products found: {len(results)}")

    results.sort(key=lambda x: float(x["price"]))
    return jsonify(results)





if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
