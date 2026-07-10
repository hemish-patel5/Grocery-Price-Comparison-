import httpx

from utils import first_value, format_price, find_image_url, absolute_url, dedupe_products

NEWWORLD_STORE_ID = "7508cf88-9fd0-4e71-b2f2-d564b1decf8d"
PAGES_TO_FETCH = 9
FOODSTUFFS_HITS_PER_PAGE = 48


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
