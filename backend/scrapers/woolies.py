import httpx
import json
from contextlib import contextmanager
from pathlib import Path

from utils import (
    get_path,
    first_value,
    format_price,
    format_unit_price,
    parse_store_id,
    dedupe_products,
)


WOOLWORTHS_BASE_URL = "https://www.woolworths.co.nz"
WOOLWORTHS_STORE_ID = 9109
WOOLWORTHS_DEFAULT_ADDRESS = "Woolworths Botany"
WOOLWORTHS_PAGE_SIZE = 48
WOOLWORTHS_MAX_PAGES = 250

# Every Woolworths store in the Auckland region. The identifiers are kept in
# JSON so the store list can be updated without editing scraper logic.
WOOLWORTHS_AUCKLAND_STORES = json.loads(
    (Path(__file__).with_name("woolworths_auckland_stores.json")).read_text(
        encoding="utf-8"
    )
)

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


@contextmanager
def woolworths_client(store_id):
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
        yield client


def woolworths_product_url(product_id, slug):
    if not product_id:
        return None

    if slug:
        return f"{WOOLWORTHS_BASE_URL}/shop/productdetails/{product_id}/{slug}"

    return f"{WOOLWORTHS_BASE_URL}/shop/productdetails/{product_id}"


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


def fetch_product_pages(client, params, label):
    raw_products = []
    seen_product_keys = set()
    page = 1

    while page <= WOOLWORTHS_MAX_PAGES:
        res = client.get(f"{WOOLWORTHS_BASE_URL}/api/v1/products", params={
            **params,
            "page": page,
        })
        res.raise_for_status()

        page_products = res.json().get("products", {}).get("items", [])
        if not page_products:
            break

        new_products = []
        for product in page_products:
            key = product_key(product)

            if key in seen_product_keys:
                continue

            seen_product_keys.add(key)
            new_products.append(product)

        if not new_products:
            break

        raw_products.extend(new_products)
        print(f"Woolworths {label} page {page}: raw={len(page_products)}, new={len(new_products)}, total={len(raw_products)}")

        page += 1

    return raw_products


def normalize_product(p, store_id, address, department=None):
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
        ]) or department,
        "availability": p.get("availabilityStatus"),
        "stock_level": p.get("stockLevel"),
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


def scrape_all_woolworths(store_id=WOOLWORTHS_STORE_ID, address=WOOLWORTHS_DEFAULT_ADDRESS):
    try:
        store_id = parse_store_id(store_id, WOOLWORTHS_STORE_ID)

        with woolworths_client(store_id) as client:
            departments = get_woolworths_departments(client)
            print(f"Scraping {len(departments)} departments: {', '.join(slug for slug, _ in departments)}")

            all_products = []
            for slug, department_label in departments:
                raw_products = fetch_product_pages(client, {
                    "target": "browse",
                    "dasFilter": f"Department;;{slug};false",
                    "size": WOOLWORTHS_PAGE_SIZE,
                    "inStockProductsOnly": "false",
                    "sort": "PriceAsc",
                }, label=slug)

                all_products.extend(
                    normalize_product(p, store_id, address, department=department_label)
                    for p in raw_products
                    if get_price(p) is not None
                )

            return dedupe_products(all_products)
    except Exception as e:
        print(f"Woolworths scrape error: {e}")
        return []


if __name__ == "__main__":
    products = scrape_all_woolworths()

    output_path = Path(__file__).resolve().parent.parent / "data" / "woolworths_products.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(products, indent=2), encoding="utf-8")

    print(f"Saved {len(products)} products to {output_path}")
