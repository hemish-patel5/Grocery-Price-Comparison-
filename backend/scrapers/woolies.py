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

# Every Woolworths store in the Auckland region, sourced from the
# /api/v1/addresses/pickup-addresses endpoint. store_id is the pickup-address
# id Woolworths uses for each store.
WOOLWORTHS_AUCKLAND_STORES = [
    # Auckland (Central)
    {"store_id": 1906035, "default_address": "Woolworths Auckland Quay Street"},
    {"store_id": 882226, "default_address": "Woolworths Auckland Victoria Street West"},
    {"store_id": 577581, "default_address": "Woolworths Greenlane"},
    {"store_id": 1906063, "default_address": "Woolworths Grey Lynn"},
    {"store_id": 1906076, "default_address": "Woolworths Mt Eden"},
    {"store_id": 1906079, "default_address": "Woolworths Mt Roskill"},
    {"store_id": 1239981, "default_address": "Woolworths Mt Wellington"},
    {"store_id": 1768531, "default_address": "Woolworths Newmarket"},
    {"store_id": 1225560, "default_address": "Woolworths Onehunga"},
    {"store_id": 1996677, "default_address": "Woolworths Ponsonby"},
    {"store_id": 1906087, "default_address": "Woolworths St Johns"},
    {"store_id": 1225566, "default_address": "Woolworths St Lukes"},
    {"store_id": 1740953, "default_address": "Woolworths Three Kings"},
    {"store_id": 4156860, "default_address": "Woolworths Waiheke"},
    # Auckland (East)
    {"store_id": 1109324, "default_address": "Woolworths Beachlands"},
    {"store_id": 1225547, "default_address": "Woolworths Botany"},
    {"store_id": 1224920, "default_address": "Woolworths Highland Park"},
    {"store_id": 1237277, "default_address": "Woolworths Howick"},
    {"store_id": 1237264, "default_address": "Woolworths Meadowbank"},
    {"store_id": 1906069, "default_address": "Woolworths Meadowlands"},
    {"store_id": 1488544, "default_address": "Woolworths Pakuranga"},
    # Auckland (North)
    {"store_id": 2124460, "default_address": "Woolworths Birkenhead"},
    {"store_id": 2683184, "default_address": "Woolworths Browns Bay"},
    {"store_id": 1190273, "default_address": "Woolworths Glenfield"},
    {"store_id": 3105636, "default_address": "Woolworths Greville Road"},
    {"store_id": 2373714, "default_address": "Woolworths Mairangi Bay"},
    {"store_id": 473644, "default_address": "Woolworths Milford"},
    {"store_id": 2124747, "default_address": "Woolworths Northcote"},
    {"store_id": 1225662, "default_address": "Woolworths Orewa"},
    {"store_id": 2673963, "default_address": "Woolworths Silverdale"},
    {"store_id": 1231998, "default_address": "Woolworths Sunnynook"},
    {"store_id": 1229219, "default_address": "Woolworths Takapuna"},
    {"store_id": 1716255, "default_address": "Woolworths Warkworth"},
    {"store_id": 1248095, "default_address": "Woolworths Whangaparaoa"},
    # Auckland (South)
    {"store_id": 1189112, "default_address": "Woolworths Auckland Airport"},
    {"store_id": 1600626, "default_address": "Woolworths Mangere East"},
    {"store_id": 1225677, "default_address": "Woolworths Manukau"},
    {"store_id": 1906072, "default_address": "Woolworths Manukau Mall"},
    {"store_id": 1906083, "default_address": "Woolworths Manurewa"},
    {"store_id": 1224936, "default_address": "Woolworths Papakura"},
    {"store_id": 1225052, "default_address": "Woolworths Papatoetoe"},
    {"store_id": 2686431, "default_address": "Woolworths Pukekohe"},
    {"store_id": 1213289, "default_address": "Woolworths Pukekohe South"},
    {"store_id": 2313141, "default_address": "Woolworths Roselands"},
    {"store_id": 480066, "default_address": "Woolworths Takanini"},
    {"store_id": 3059814, "default_address": "Woolworths Waiata Shores"},
    # Auckland (West)
    {"store_id": 870058, "default_address": "Woolworths Helensville"},
    {"store_id": 1230712, "default_address": "Woolworths Henderson"},
    {"store_id": 1223854, "default_address": "Woolworths Hobsonville"},
    {"store_id": 1237272, "default_address": "Woolworths Kelston"},
    {"store_id": 620844, "default_address": "Woolworths Lincoln Road"},
    {"store_id": 1225554, "default_address": "Woolworths Lynfield"},
    {"store_id": 1225559, "default_address": "Woolworths Lynnmall"},
    {"store_id": 1230704, "default_address": "Woolworths Northwest"},
    {"store_id": 882224, "default_address": "Woolworths Pt Chevalier"},
    {"store_id": 1232007, "default_address": "Woolworths Te Atatu South"},
    {"store_id": 592572, "default_address": "Woolworths Westgate"},
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
