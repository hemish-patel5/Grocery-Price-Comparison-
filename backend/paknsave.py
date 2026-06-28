from urllib.parse import urljoin

import httpx


PAKNSAVE_STORE_ID = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"
PAGES_TO_FETCH = 9
FOODSTUFFS_HITS_PER_PAGE = 48


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


def dedupe_products(products):
    seen = set()
    deduped = []

    for product in products:
        key = (
            product.get("productId")
            or product.get("productID")
            or product.get("id")
            or product.get("sku")
            or product.get("barcode")
            or product.get("name")
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(product)

    return deduped


def search_paknsave(query):
    try:
        with httpx.Client(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=15.0,
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
                    headers={"authorization": f"Bearer {token}"},
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
