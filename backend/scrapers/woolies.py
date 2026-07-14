import httpx
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .utils import (
    get_path,
    first_value,
    format_price,
    format_unit_price,
    dedupe_products,
    strip_brand_prefix,
)


WOOLWORTHS_BASE_URL = "https://www.woolworths.co.nz"
WOOLWORTHS_PAGE_SIZE = 48
WOOLWORTHS_MAX_PAGES = 250
WOOLWORTHS_PAGE_RETRIES = 4

# Aisle membership is catalog taxonomy (same at every store), so the
# product -> aisle map is crawled once and kept permanently. Delete the
# file to force a rebuild (e.g. to pick up newly added products).
AISLE_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "woolworths_aisle_map.json"
stores_path = Path(__file__).resolve().parent.parent / "data" / "woolworths_auckland_stores.json"


# Promotional pseudo-aisles: only used for a product's aisle if no real
# aisle contains it.
PROMO_AISLES = {"fresh deals", "in season", "the odd bunch", "new"}

# Every Woolworths store in the Auckland region taken from JSON file
WOOLWORTHS_STORES = json.loads(stores_path.read_text(encoding="utf-8"))

# The stores this scraper runs over: Auckland (West)
WOOLWORTHS_AUCKLAND_WEST_STORES = [
    # "helensville",
    # "henderson",
    # "hobsonville",
    # "kelston",
    # "lincoln_road",
    # "pt_chevalier",
    # "te_atatu_south",
    # "lynnmall",
    "lynfield",
    "northwest",
    "westgate",
]

# Used if the department list can't be fetched from the shell API.
WOOLWORTHS_DEPARTMENTS_FALLBACK = [
    ("fruit-veg", "Fruit & Veg"),
    ("meat-poultry", "Meat & Poultry"),
    ("fish-seafood", "Fish & Seafood"),
    ("fridge-deli", "Fridge & Deli"),
    ("bakery", "Bakery"),
    ("frozen", "Frozen"),
    ("pantry", "Pantry"),
    ("beer-wine", "Beer & Wine"),
    ("drinks", "Drinks"),
    ("health-body", "Health & Body"),
    ("household", "Household"),
    ("baby-child", "Baby & Child"),
    ("pet", "Pet"),
]


def woolworths_location_cookie(store):
    if store.get("locationCookie"):
        return store["locationCookie"]

    return (
        f"dm-Pickup,"
        f"f-{store.get('fulfilmentStoreId')},"
        f"a-{store.get('areaId')},"
        f"s-{store.get('pickupAddressId')}"
    )


@contextmanager
def woolworths_client(store):
    store_id = store["fulfilmentStoreId"]
    location_cookie = woolworths_location_cookie(store)

    with httpx.Client(
        headers={
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "OnlineShopping.WebApp",
            "referer": "https://www.woolworths.co.nz/shop/browse",
        },
        timeout=15.0,
    ) as client:
        client.get(WOOLWORTHS_BASE_URL)
        client.cookies.set("fulfilmentStoreId", str(store_id), domain=".woolworths.co.nz")
        if location_cookie:
            client.cookies.set("cw-lrkswrdjp", location_cookie, domain=".woolworths.co.nz")
        yield client


def get_price(p):
    price = p.get("price", {})
    return price.get("salePrice") or price.get("originalPrice")


def product_key(p):
    return (
        p.get("sku")
        or p.get("barcode")
        or p.get("slug")
        or p.get("name")
    )


def fetch_page_with_retries(client, params, label):
    for attempt in range(1, WOOLWORTHS_PAGE_RETRIES + 1):
        try:
            res = client.get(f"{WOOLWORTHS_BASE_URL}/api/v1/products", params=params)
            res.raise_for_status()
            return res.json()
        except httpx.HTTPStatusError as e:
            # 4xx won't get better on retry; 5xx and 429 might
            if e.response.status_code < 500 and e.response.status_code != 429:
                raise
            error = e
        except (httpx.TimeoutException, httpx.TransportError) as e:
            # stalled/dropped connection — retry
            error = e

        if attempt == WOOLWORTHS_PAGE_RETRIES:
            raise error

        wait = 2 ** attempt
        print(f"Woolworths {label} page {params.get('page')}: {type(error).__name__}, retrying in {wait}s (attempt {attempt}/{WOOLWORTHS_PAGE_RETRIES})")
        time.sleep(wait)


def fetch_product_pages(client, params, label):
    raw_products = []
    seen_product_keys = set()
    raw_count = 0
    duplicate_count = 0
    expected_total = None
    page = 1

    while page <= WOOLWORTHS_MAX_PAGES:
        body = fetch_page_with_retries(client, {
            **params,
            "page": page,
        }, label)

        products_data = body.get("products", {})
        if expected_total is None:
            expected_total = products_data.get("totalItems")

        page_products = products_data.get("items", [])
        if not page_products:
            break

        raw_count += len(page_products)
        new_products = []
        for product in page_products:
            key = product_key(product)

            if key in seen_product_keys:
                duplicate_count += 1
                continue

            seen_product_keys.add(key)
            new_products.append(product)

        if not new_products:
            break

        raw_products.extend(new_products)
        print(
            f"Woolworths {label} page {page}: "
            f"page_raw={len(page_products)}, "
            f"new={len(new_products)}, "
            f"duplicates={duplicate_count}, "
            f"deduped_total={len(raw_products)}, "
            f"raw_total={raw_count}, "
            f"api_expected={expected_total}"
        )

        page += 1

    return raw_products


def fetch_das_facets(client, params, label, group):
    body = fetch_page_with_retries(client, {
        **params,
        "page": 1,
    }, label)

    return [
        facet
        for facet in body.get("dasFacets", [])
        if facet.get("group") == group and facet.get("value") and facet.get("name")
    ]


def normalize_product(p, store, store_key, department=None, aisle=None):
    price = p.get("price", {})
    size = p.get("size", {})
    store_id = store["fulfilmentStoreId"]
    product_id = first_value(p, [
        ("sku",),
        ("productId",),
        ("productID",),
        ("stockcode",),
        ("id",),
        ("barcode",),
    ])

    brand = first_value(p, [
        ("brand",),
        ("brandName",),
        ("manufacturer",),
    ])

    return {
        "name": strip_brand_prefix(p.get("name", "Unknown"), brand),
        "price": format_price(get_price(p)),
        "original_price": format_price(price.get("originalPrice")),
        "sale_price": format_price(price.get("salePrice")),
        "store": "Woolworths",
        "product_id": product_id,
        "brand": brand,
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
        "source_store_key": store_key,
        "source_store_id": str(store_id),
        "source_store_address": store["address"],
        "source_area_id": store.get("areaId"),
        "source_pickup_address_id": store.get("pickupAddressId"),
        "department": first_value(p, [
            ("departments", 0, "name"),
        ]) or department,
        "aisle": aisle,
    }


def get_woolworths_departments(client):
    try:
        shell = client.get(f"{WOOLWORTHS_BASE_URL}/api/v1/shell").json()
        departments = []

        for nav in shell.get("mainNavs", []):
            for group in nav.get("navigationItems") or []:
                if group.get("label") != "Department":
                    continue

                for item in group.get("items") or []:
                    slug = (item.get("url") or "").rstrip("/").split("/")[-1]
                    if slug:
                        departments.append((slug, item.get("label")))

        if departments:
            return departments
    except Exception as e:
        print(f"Woolworths department list error: {e}")

    return WOOLWORTHS_DEPARTMENTS_FALLBACK


def build_aisle_map(client):
    """Crawl every department's aisles once, recording product -> aisle.

    Aisle membership is the same at every store, so this runs once and the
    result is reused by every store's department scrape. Real aisles are
    crawled before promotional pseudo-aisles and existing entries are never
    overwritten, so 'Fresh Deals' can't claim a product that lives in 'Fruit'.
    """
    departments = get_woolworths_departments(client)
    aisle_map = {}

    for slug, _ in departments:
        department_params = {
            "target": "browse",
            "dasFilter": f"Department;;{slug};false",
            "size": WOOLWORTHS_PAGE_SIZE,
            "inStockProductsOnly": "false",
            "sort": "PriceAsc",
        }

        try:
            aisle_facets = fetch_das_facets(client, department_params, label=slug, group="Aisle")
        except Exception as e:
            print(f"Woolworths {slug} aisle list error, skipping department in aisle map: {e}")
            continue

        # real aisles first so they win over promotional pseudo-aisles
        aisle_facets.sort(key=lambda f: f["name"].lower() in PROMO_AISLES)

        for aisle in aisle_facets:
            aisle_label = aisle["name"]
            # The aisle filter only works alongside the department filter
            # (a lone Aisle dasFilter returns totalItems=-1), and needs the
            # 4-segment form: Aisle;{value};{name};false
            aisle_params = {
                "target": "browse",
                "dasFilter": [
                    f"Department;;{slug};false",
                    f"Aisle;{aisle['value']};{aisle_label};false",
                ],
                "size": WOOLWORTHS_PAGE_SIZE,
                "inStockProductsOnly": "false",
                "sort": "PriceAsc",
            }

            try:
                raw_products = fetch_product_pages(client, aisle_params, label=f"{slug}/{aisle_label}")
            except Exception as e:
                print(f"Woolworths {slug}/{aisle_label} FAILED after retries, skipping aisle: {e}")
                continue

            for product in raw_products:
                key = str(product_key(product))
                if key not in aisle_map:
                    aisle_map[key] = aisle_label

    return aisle_map


def load_or_build_aisle_map(store):
    """Return the product -> aisle map, building it only when missing."""
    if AISLE_MAP_PATH.exists():
        try:
            cached = json.loads(AISLE_MAP_PATH.read_text(encoding="utf-8"))
            print(f"Using aisle map ({len(cached['aisles'])} products, built {cached.get('built_at', '?')[:10]})")
            return cached["aisles"]
        except Exception as e:
            print(f"Aisle map file unreadable, rebuilding: {e}")

    print("Building aisle map (one-off crawl of every aisle)...")
    with woolworths_client(store) as client:
        aisle_map = build_aisle_map(client)

    AISLE_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    AISLE_MAP_PATH.write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(),
        "aisles": aisle_map,
    }, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Aisle map built: {len(aisle_map)} products, saved to {AISLE_MAP_PATH}")

    return aisle_map


def scrape_store(store_key, aisle_map):
    store = WOOLWORTHS_STORES[store_key]
    print(f"Scraping store: {store['address']} {store['fulfilmentStoreId']}")

    with woolworths_client(store) as client:
        departments = get_woolworths_departments(client)
        print(f"Scraping {len(departments)} departments: {', '.join(slug for slug, _ in departments)}")

        all_products = []
        failed_departments = []
        for slug, department_label in departments:
            department_params = {
                "target": "browse",
                "dasFilter": f"Department;;{slug};false",
                "size": WOOLWORTHS_PAGE_SIZE,
                "inStockProductsOnly": "false",
                "sort": "PriceAsc",
            }

            try:
                raw_products = fetch_product_pages(client, department_params, label=slug)
            except Exception as e:
                print(f"Woolworths {slug} FAILED after retries, skipping department: {e}")
                failed_departments.append(slug)
                continue

            products_with_price = [
                product
                for product in raw_products
                if get_price(product) is not None
            ]

            with_aisle = sum(
                1 for p in products_with_price
                if str(product_key(p)) in aisle_map
            )
            print(
                f"Woolworths {department_label}: "
                f"deduped_raw={len(raw_products)}, "
                f"with_price={len(products_with_price)}, "
                f"with_aisle={with_aisle}"
            )

            all_products.extend(
                normalize_product(
                    p,
                    store,
                    store_key,
                    department=department_label,
                    aisle=aisle_map.get(str(product_key(p))),
                )
                for p in products_with_price
            )

        deduped_products = dedupe_products(all_products)
        print(
            f"Woolworths final: "
            f"normalized={len(all_products)}, "
            f"deduped={len(deduped_products)}, "
            f"removed={len(all_products) - len(deduped_products)}"
        )
        if failed_departments:
            print(f"WARNING: {len(failed_departments)} departments failed and are missing: {', '.join(failed_departments)}")

        return deduped_products


if __name__ == "__main__":
    from .db import upload_products

    started = time.time()
    uploaded_counts = {}
    failed_stores = []

    aisle_map = load_or_build_aisle_map(
        WOOLWORTHS_STORES[WOOLWORTHS_AUCKLAND_WEST_STORES[0]]
    )

    for position, store_key in enumerate(WOOLWORTHS_AUCKLAND_WEST_STORES, 1):
        try:
            store = WOOLWORTHS_STORES[store_key]
            print(f"\n===== [{position}/{len(WOOLWORTHS_AUCKLAND_WEST_STORES)}] {store['address']} ({store_key}) =====")

            products = scrape_store(store_key, aisle_map)
            if not products:
                raise RuntimeError("scrape returned no products")

            upload_products(store_key, store, products)
            uploaded_counts[store_key] = len(products)
        except Exception as e:
            print(f"STORE FAILED, moving on: {store_key}: {e}")
            failed_stores.append(store_key)

    elapsed_minutes = (time.time() - started) / 60
    print(
        f"\nFinished in {elapsed_minutes:.1f} min: "
        f"{len(uploaded_counts)}/{len(WOOLWORTHS_AUCKLAND_WEST_STORES)} stores uploaded, "
        f"{sum(uploaded_counts.values())} products total"
    )
    if failed_stores:
        print(f"Failed stores: {', '.join(failed_stores)}")
