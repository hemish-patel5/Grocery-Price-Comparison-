import argparse
import json
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

try:
    from .utils import (
        absolute_url,
        dedupe_products,
        find_image_url,
        first_value,
        format_price,
    )
except ImportError:  # Allow `python backend/scrapers/newworld.py` as well.
    from utils import (
        absolute_url,
        dedupe_products,
        find_image_url,
        first_value,
        format_price,
    )

NEWWORLD_BASE_URL = "https://www.newworld.co.nz"
NEWWORLD_SEARCH_URL = (
    "https://api-prod.newworld.co.nz/v1/edge/search/paginated/products"
)
NEWWORLD_TOKEN_URL = f"{NEWWORLD_BASE_URL}/api/user/get-current-user"
NEWWORLD_IMAGE_BASE_URL = "https://a.fsimg.co.nz/product/retail/fan/image"

NEWWORLD_HITS_PER_PAGE = 50
NEWWORLD_MAX_PAGES = 250
NEWWORLD_RESULT_CAP = 1000
NEWWORLD_REQUEST_RETRIES = 4

STORES_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "newworld_auckland_stores.json"
)



def load_newworld_stores(path=STORES_PATH):
    """Load store metadata"""

    stores = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(stores, list):
        stores = {
            store.get("store_key") or store.get("key"): store
            for store in stores
            if store.get("store_key") or store.get("key")
        }
    if not isinstance(stores, dict):
        raise ValueError(f"Expected an object or list in {path}")
    return stores


def store_id_from(store):
    if isinstance(store, str):
        return store

    store_id = first_value(store, [
        ("storeId",),
        ("store_id",),
        ("id",),
    ])
    if not store_id:
        raise ValueError("New World store metadata is missing storeId")
    return str(store_id)


def newworld_image_url(product_id, size=500):
    """Build the primary FSNI CDN image URL from a retailer product ID.

    Category search results do not include images, while the product-detail
    endpoint returns this deterministic URL at 100px through 500px. Deriving
    it here avoids an additional detail request for every scraped product.
    """
    if not product_id:
        return None

    numeric_id = str(product_id).split("-", 1)[0]
    if not numeric_id.isdigit():
        return None
    if size not in {100, 200, 300, 400, 500}:
        raise ValueError("New World image size must be 100, 200, 300, 400 or 500")

    return f"{NEWWORLD_IMAGE_BASE_URL}/{size}x{size}/{numeric_id}.png"


def find_newworld_image_url(product):
    """Return the largest explicit image, or derive the 500px CDN image."""
    primary_images = (
        (product.get("images") or {}).get("primaryImages") or {}
    )
    for size in (500, 400, 300, 200, 100):
        image_url = primary_images.get(f"{size}px")
        if image_url:
            return absolute_url(image_url, NEWWORLD_BASE_URL)

    return (
        absolute_url(find_image_url(product), NEWWORLD_BASE_URL)
        or newworld_image_url(first_value(product, [
            ("productId",),
            ("productID",),
            ("id",),
            ("sku",),
            ("barcode",),
        ]))
    )


def algolia_quote(value):
    """Quote one Algolia filter value, including embedded slashes/quotes."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def category_filters(store, department=None, category=None, subcategory=None):
    filters = [f"stores:{store_id_from(store)}"]
    if department:
        filters.append(f"category0NI:{algolia_quote(department)}")
    if category:
        filters.append(f"category1NI:{algolia_quote(category)}")
    if subcategory:
        filters.append(f"category2NI:{algolia_quote(subcategory)}")
    return " AND ".join(filters)


def authenticate_newworld(client):
    response = client.post(NEWWORLD_TOKEN_URL)
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("New World token response did not include access_token")
    client.headers["authorization"] = f"Bearer {token}"


@contextmanager
def newworld_client():
    with httpx.Client(
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "origin": NEWWORLD_BASE_URL,
            "referer": f"{NEWWORLD_BASE_URL}/",
            "user-agent": "Mozilla/5.0",
        },
        follow_redirects=True,
        timeout=30.0,
    ) as client:
        authenticate_newworld(client)
        yield client


def build_search_payload(
    store,
    filters,
    page=0,
    hits_per_page=NEWWORLD_HITS_PER_PAGE,
    facets=None,
    query="",
):
    store_id = store_id_from(store)
    return {
        "algoliaQuery": {
            "attributesToHighlight": [],
            "facets": facets or [],
            "filters": filters,
            "hitsPerPage": hits_per_page,
            "maxValuesPerFacet": 200,
            "page": page,
            "query": query,
        },
        "algoliaFacetQueries": [],
        "storeId": store_id,
        "hitsPerPage": hits_per_page,
        "page": page,
        "sortOrder": "NI_POPULARITY_ASC",
        "tobaccoQuery": False,
    }


def fetch_search_page(client, payload, label):
    """Post one search request, refreshing auth and retrying transient errors."""
    error = None
    for attempt in range(1, NEWWORLD_REQUEST_RETRIES + 1):
        try:
            response = client.post(NEWWORLD_SEARCH_URL, json=payload)
            if response.status_code == 401:
                authenticate_newworld(client)
                response = client.post(NEWWORLD_SEARCH_URL, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 and exc.response.status_code != 429:
                raise
            error = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            error = exc

        if attempt == NEWWORLD_REQUEST_RETRIES:
            raise error

        wait = 2 ** attempt
        print(
            f"New World {label}: {type(error).__name__}, retrying in "
            f"{wait}s (attempt {attempt}/{NEWWORLD_REQUEST_RETRIES})"
        )
        time.sleep(wait)

    raise RuntimeError(f"New World {label} request failed")


def fetch_facets(client, store, facet, filters):
    payload = build_search_payload(
        store,
        filters,
        page=0,
        hits_per_page=1,
        facets=[facet],
    )
    body = fetch_search_page(client, payload, label=f"facet {facet}")
    values = (
        body.get("algoliaSearchResult", {})
        .get("facets", {})
        .get(facet, {})
    )
    return [
        {"name": name, "count": count}
        for name, count in values.items()
    ]


def get_newworld_departments(client, store):
    """Discover the complete three-level category tree for one store."""
    departments = []
    for department in fetch_facets(
        client,
        store,
        facet="category0NI",
        filters=category_filters(store),
    ):
        department_name = department["name"]
        categories = []
        for category in fetch_facets(
            client,
            store,
            facet="category1NI",
            filters=category_filters(store, department=department_name),
        ):
            category_name = category["name"]
            subcategories = fetch_facets(
                client,
                store,
                facet="category2NI",
                filters=category_filters(
                    store,
                    department=department_name,
                    category=category_name,
                ),
            )
            categories.append({
                **category,
                "subcategories": subcategories,
            })

        departments.append({
            **department,
            "categories": categories,
        })

    return departments


def iter_leaf_categories(store, departments):
    """Flatten the discovered tree into independently pageable filters."""
    for department in departments:
        for category in department["categories"]:
            subcategories = category["subcategories"] or [None]
            for subcategory in subcategories:
                leaf = {
                    "department": department["name"],
                    "category": category["name"],
                    "subcategory": subcategory["name"] if subcategory else None,
                    "count": subcategory["count"] if subcategory else category["count"],
                }
                leaf["filters"] = category_filters(store, **{
                    key: leaf[key]
                    for key in ("department", "category", "subcategory")
                })
                yield leaf


def category_label(category):
    return " / ".join(
        value
        for value in (
            category.get("department"),
            category.get("category"),
            category.get("subcategory"),
        )
        if value
    )


def fetch_newworld_product_pages(client, store, category):
    """Fetch all pages for one leaf category, deduplicated by product ID."""
    label = category_label(category)
    products = []
    seen = set()
    page = 0

    while page < NEWWORLD_MAX_PAGES:
        payload = build_search_payload(
            store,
            category["filters"],
            page=page,
        )
        body = fetch_search_page(client, payload, label=f"{label} page {page}")
        page_products = body.get("products") or []
        if not page_products:
            break

        new_count = 0
        for product in page_products:
            key = first_value(product, [
                ("productId",),
                ("productID",),
                ("id",),
            ])
            if not key or key in seen:
                continue
            seen.add(key)
            products.append(product)
            new_count += 1

        total_hits = body.get("totalHits")
        total_pages = body.get("totalPages")
        print(
            f"New World {label} page {page}: raw={len(page_products)}, "
            f"new={new_count}, total={len(products)}, expected={total_hits}"
        )

        if page == 0 and total_hits is not None and total_hits >= NEWWORLD_RESULT_CAP:
            print(
                f"WARNING: {label} has {total_hits} results and may be capped; "
                "split this category using another facet"
            )

        if new_count == 0:
            break
        if total_pages is not None and page + 1 >= total_pages:
            break
        page += 1

    return products


def cents_to_price(value):
    if value in (None, ""):
        return None
    try:
        return format_price(float(value) / 100)
    except (TypeError, ValueError):
        return None


def normalize_newworld_prices(product):
    """Return only the effective price and whether it is a Clubcard price.

    Clubcard multi-buy rewardValue is the total offer price, so divide it by
    threshold to make the stored product price comparable per item.
    """
    single_price = product.get("singlePrice") or {}
    base_price = cents_to_price(single_price.get("price"))
    club_promotion = next(
        (
            promotion
            for promotion in (product.get("promotions") or [])
            if promotion.get("bestPromotion") is True
            and promotion.get("cardDependencyFlag") is True
            and promotion.get("rewardType") == "NEW_PRICE"
        ),
        None,
    )

    if club_promotion is not None:
        reward_value = club_promotion.get("rewardValue")
        threshold = club_promotion.get("threshold") or 1
        try:
            club_price = cents_to_price(float(reward_value) / float(threshold))
        except (TypeError, ValueError, ZeroDivisionError):
            club_price = None
        if club_price is not None:
            return {
                "price": club_price,
                "is_club_price": True,
            }

    return {
        "price": base_price,
        "is_club_price": False,
    }


def normalize_newworld_product(product, store, category):
    prices = normalize_newworld_prices(product)
    product_id = first_value(product, [
        ("productId",),
        ("productID",),
        ("id",),
        ("sku",),
        ("barcode",),
    ])

    return {
        "product_id": product_id,
        "name": product.get("name") or "Unknown",
        "brand": first_value(product, [
            ("brand",),
            ("brandName",),
            ("manufacturer",),
        ]),
        "size": first_value(product, [
            ("displayName",),
            ("size",),
            ("packageSize",),
            ("displaySize",),
            ("unit",),
        ]),
        "image_url": find_newworld_image_url(product),
        "department": category.get("department"),
        "aisle": category.get("subcategory") or category.get("category"),
        **prices,
        "store": "New World",
        "source_store_key": store.get("store_key") if isinstance(store, dict) else None,
    }


def scrape_newworld_store(store_key, stores=None, department_name=None):
    """Discover and scrape every leaf category for one New World store."""
    stores = stores or load_newworld_stores()
    if store_key not in stores:
        raise KeyError(f"Unknown New World store key: {store_key}")

    store = {**stores[store_key], "store_key": store_key}
    print(
        f"Scraping New World store: "
        f"{store.get('name') or store.get('address') or store_key} "
        f"({store_id_from(store)})"
    )

    with newworld_client() as client:
        departments = get_newworld_departments(client, store)
        if department_name:
            departments = [
                department
                for department in departments
                if department["name"].casefold() == department_name.casefold()
            ]
            if not departments:
                raise ValueError(f"Department not found: {department_name}")

        leaves = list(iter_leaf_categories(store, departments))
        print(
            f"Discovered {len(departments)} departments and "
            f"{len(leaves)} leaf categories"
        )

        normalized = []
        failed_categories = []
        for position, category in enumerate(leaves, 1):
            label = category_label(category)
            print(f"\n[{position}/{len(leaves)}] {label}")
            try:
                raw_products = fetch_newworld_product_pages(
                    client,
                    store,
                    category,
                )
                normalized.extend(
                    normalize_newworld_product(product, store, category)
                    for product in raw_products
                )
            except Exception as exc:
                print(f"New World {label} FAILED: {exc}")
                failed_categories.append(label)

    products = [
        product
        for product in dedupe_products(normalized)
        if product.get("product_id") and product.get("price") is not None
    ]
    print(
        f"\nNew World final: normalized={len(normalized)}, "
        f"deduped_with_price={len(products)}, failed={len(failed_categories)}"
    )
    if failed_categories:
        print(f"Failed categories: {', '.join(failed_categories)}")
    return products


def product_category(product, fallback_department=None):
    """Read the product's category path from a search response."""
    tree = (product.get("categoryTrees") or [{}])[0]
    return {
        "department": tree.get("level0") or fallback_department,
        "category": tree.get("level1"),
        "subcategory": tree.get("level2"),
    }


def scrape_newworld_sample(store_key, limit, stores=None, department_name=None):
    """Fetch a small product sample without crawling every category."""
    if not 1 <= limit <= NEWWORLD_HITS_PER_PAGE:
        raise ValueError(
            f"Sample limit must be between 1 and {NEWWORLD_HITS_PER_PAGE}"
        )

    stores = stores or load_newworld_stores()
    if store_key not in stores:
        raise KeyError(f"Unknown New World store key: {store_key}")

    store = {**stores[store_key], "store_key": store_key}
    filters = category_filters(store, department=department_name)
    with newworld_client() as client:
        body = fetch_search_page(
            client,
            build_search_payload(
                store,
                filters,
                page=0,
                hits_per_page=limit,
            ),
            label=f"{store_key} sample",
        )

    products = [
        normalize_newworld_product(
            product,
            store,
            product_category(product, fallback_department=department_name),
        )
        for product in dedupe_products(body.get("products") or [])
    ]
    products = [
        product
        for product in products
        if product.get("product_id") and product.get("price") is not None
    ][:limit]
    print(f"New World {store_key} sample: {len(products)}/{limit} products")
    return products


def search_newworld(query, store):
    """Compatibility helper for query-based searches against one store."""
    filters = category_filters(store)
    category = {
        "department": None,
        "category": None,
        "subcategory": None,
    }

    try:
        with newworld_client() as client:
            payload = build_search_payload(
                store,
                filters,
                query=query,
            )
            body = fetch_search_page(client, payload, label=f"search {query!r}")
        return [
            normalize_newworld_product(product, store, category)
            for product in dedupe_products(body.get("products") or [])
        ]
    except Exception as exc:
        print(f"New World search error: {exc}")
        return []


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape every Auckland New World store",
    )
    parser.add_argument(
        "--department",
        help="scrape only one department (useful for a test run)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help=(
            f"fetch only a small sample of 1-{NEWWORLD_HITS_PER_PAGE} products "
            "instead of crawling every category"
        ),
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="do not write product JSON files (use with --upload for upload-only runs)",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="print the category tree without downloading product pages",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="upload the scraped products to Supabase",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    stores = load_newworld_stores()
    store_keys = list(stores)
    if not store_keys:
        raise RuntimeError("No Auckland New World stores found")

    if args.discover_only:
        for store_key in store_keys:
            store = {**stores[store_key], "store_key": store_key}
            with newworld_client() as client:
                departments = get_newworld_departments(client, store)
            print(json.dumps({store_key: departments}, indent=2, ensure_ascii=False))
        return

    if args.upload:
        try:
            from .db import upload_newworld_products
        except ImportError:
            from db import upload_newworld_products

    completed = {}
    failed = []
    for position, store_key in enumerate(store_keys, 1):
        store = {**stores[store_key], "store_key": store_key}
        print(f"\n===== [{position}/{len(store_keys)}] New World {store_key} =====")
        try:
            if args.limit is not None:
                products = scrape_newworld_sample(
                    store_key,
                    args.limit,
                    stores=stores,
                    department_name=args.department,
                )
            else:
                products = scrape_newworld_store(
                    store_key,
                    stores=stores,
                    department_name=args.department,
                )
            if not products:
                raise RuntimeError("scrape returned no products")

            if not args.no_json:
                output = (
                    Path(__file__).resolve().parent.parent
                    / "data"
                    / f"newworld_{store_key}_products.json"
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(products, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(f"Saved {len(products)} products to {output}")

            if args.upload:
                upload_newworld_products(store_key, store, products)
            completed[store_key] = len(products)
        except Exception as exc:
            print(f"STORE FAILED, moving on: {store_key}: {exc}")
            failed.append(store_key)

    print(
        f"\nNew World finished: {len(completed)}/{len(store_keys)} stores, "
        f"{sum(completed.values())} products"
    )
    if failed:
        print(f"Failed stores: {', '.join(failed)}")


if __name__ == "__main__":
    main()
