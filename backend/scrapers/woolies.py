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

# Every Woolworths store in the Auckland region. pickup_address_id comes from
# the /api/v1/addresses/pickup-addresses endpoint; fulfilment_store_id and
# area_id were resolved by selecting each store via
# PUT /api/v1/fulfilment/my/pickup-addresses and reading back the session's
# fulfilment context. fulfilment_store_id is what store-specific pricing keys on.
WOOLWORTHS_AUCKLAND_STORES = [
    # Auckland (Central)
    {"default_address": "Woolworths Auckland Quay Street", "fulfilment_store_id": 9045, "pickup_address_id": 1906035, "area_id": 714},
    {"default_address": "Woolworths Auckland Victoria Street West", "fulfilment_store_id": 9250, "pickup_address_id": 882226, "area_id": 289},
    {"default_address": "Woolworths Greenlane", "fulfilment_store_id": 9039, "pickup_address_id": 577581, "area_id": 142},
    {"default_address": "Woolworths Grey Lynn", "fulfilment_store_id": 9253, "pickup_address_id": 1906063, "area_id": 713},
    {"default_address": "Woolworths Mt Eden", "fulfilment_store_id": 9544, "pickup_address_id": 1906076, "area_id": 710},
    {"default_address": "Woolworths Mt Roskill", "fulfilment_store_id": 9023, "pickup_address_id": 1906079, "area_id": 709},
    {"default_address": "Woolworths Mt Wellington", "fulfilment_store_id": 9046, "pickup_address_id": 1239981, "area_id": 514},
    {"default_address": "Woolworths Newmarket", "fulfilment_store_id": 9405, "pickup_address_id": 1768531, "area_id": 664},
    {"default_address": "Woolworths Onehunga", "fulfilment_store_id": 9567, "pickup_address_id": 1225560, "area_id": 482},
    {"default_address": "Woolworths Ponsonby", "fulfilment_store_id": 9500, "pickup_address_id": 1996677, "area_id": 715},
    {"default_address": "Woolworths St Johns", "fulfilment_store_id": 9561, "pickup_address_id": 1906087, "area_id": 707},
    {"default_address": "Woolworths St Lukes", "fulfilment_store_id": 9108, "pickup_address_id": 1225566, "area_id": 484},
    {"default_address": "Woolworths Three Kings", "fulfilment_store_id": 9270, "pickup_address_id": 1740953, "area_id": 645},
    {"default_address": "Woolworths Waiheke", "fulfilment_store_id": 9517, "pickup_address_id": 4156860, "area_id": 363},
    # Auckland (East)
    {"default_address": "Woolworths Beachlands", "fulfilment_store_id": 9523, "pickup_address_id": 1109324, "area_id": 422},
    {"default_address": "Woolworths Botany", "fulfilment_store_id": 9109, "pickup_address_id": 1225547, "area_id": 473},
    {"default_address": "Woolworths Highland Park", "fulfilment_store_id": 9510, "pickup_address_id": 1224920, "area_id": 471},
    {"default_address": "Woolworths Howick", "fulfilment_store_id": 9024, "pickup_address_id": 1237277, "area_id": 513},
    {"default_address": "Woolworths Meadowbank", "fulfilment_store_id": 9021, "pickup_address_id": 1237264, "area_id": 511},
    {"default_address": "Woolworths Meadowlands", "fulfilment_store_id": 9411, "pickup_address_id": 1906069, "area_id": 712},
    {"default_address": "Woolworths Pakuranga", "fulfilment_store_id": 9204, "pickup_address_id": 1488544, "area_id": 587},
    # Auckland (North)
    {"default_address": "Woolworths Birkenhead", "fulfilment_store_id": 9101, "pickup_address_id": 2124460, "area_id": 720},
    {"default_address": "Woolworths Browns Bay", "fulfilment_store_id": 9254, "pickup_address_id": 2683184, "area_id": 849},
    {"default_address": "Woolworths Glenfield", "fulfilment_store_id": 9443, "pickup_address_id": 1190273, "area_id": 440},
    {"default_address": "Woolworths Greville Road", "fulfilment_store_id": 9171, "pickup_address_id": 3105636, "area_id": 914},
    {"default_address": "Woolworths Mairangi Bay", "fulfilment_store_id": 9248, "pickup_address_id": 2373714, "area_id": 778},
    {"default_address": "Woolworths Milford", "fulfilment_store_id": 9005, "pickup_address_id": 473644, "area_id": 120},
    {"default_address": "Woolworths Northcote", "fulfilment_store_id": 9573, "pickup_address_id": 2124747, "area_id": 721},
    {"default_address": "Woolworths Orewa", "fulfilment_store_id": 9536, "pickup_address_id": 1225662, "area_id": 483},
    {"default_address": "Woolworths Silverdale", "fulfilment_store_id": 9025, "pickup_address_id": 2673963, "area_id": 844},
    {"default_address": "Woolworths Sunnynook", "fulfilment_store_id": 9587, "pickup_address_id": 1231998, "area_id": 504},
    {"default_address": "Woolworths Takapuna", "fulfilment_store_id": 9127, "pickup_address_id": 1229219, "area_id": 496},
    {"default_address": "Woolworths Warkworth", "fulfilment_store_id": 9051, "pickup_address_id": 1716255, "area_id": 596},
    {"default_address": "Woolworths Whangaparaoa", "fulfilment_store_id": 9503, "pickup_address_id": 1248095, "area_id": 518},
    # Auckland (South)
    {"default_address": "Woolworths Auckland Airport", "fulfilment_store_id": 9483, "pickup_address_id": 1189112, "area_id": 439},
    {"default_address": "Woolworths Mangere East", "fulfilment_store_id": 9486, "pickup_address_id": 1600626, "area_id": 606},
    {"default_address": "Woolworths Manukau", "fulfilment_store_id": 9545, "pickup_address_id": 1225677, "area_id": 481},
    {"default_address": "Woolworths Manukau Mall", "fulfilment_store_id": 9574, "pickup_address_id": 1906072, "area_id": 25},
    {"default_address": "Woolworths Manurewa", "fulfilment_store_id": 9029, "pickup_address_id": 1906083, "area_id": 708},
    {"default_address": "Woolworths Papakura", "fulfilment_store_id": 9525, "pickup_address_id": 1224936, "area_id": 485},
    {"default_address": "Woolworths Papatoetoe", "fulfilment_store_id": 9559, "pickup_address_id": 1225052, "area_id": 472},
    {"default_address": "Woolworths Pukekohe", "fulfilment_store_id": 9445, "pickup_address_id": 2686431, "area_id": 851},
    {"default_address": "Woolworths Pukekohe South", "fulfilment_store_id": 9491, "pickup_address_id": 1213289, "area_id": 454},
    {"default_address": "Woolworths Roselands", "fulfilment_store_id": 9014, "pickup_address_id": 2313141, "area_id": 773},
    {"default_address": "Woolworths Takanini", "fulfilment_store_id": 9007, "pickup_address_id": 480066, "area_id": 122},
    {"default_address": "Woolworths Waiata Shores", "fulfilment_store_id": 9464, "pickup_address_id": 3059814, "area_id": 911},
    # Auckland (West)
    {"default_address": "Woolworths Helensville", "fulfilment_store_id": 9104, "pickup_address_id": 870058, "area_id": 269},
    {"default_address": "Woolworths Henderson", "fulfilment_store_id": 9408, "pickup_address_id": 1230712, "area_id": 503},
    {"default_address": "Woolworths Hobsonville", "fulfilment_store_id": 9569, "pickup_address_id": 1223854, "area_id": 470},
    {"default_address": "Woolworths Kelston", "fulfilment_store_id": 9228, "pickup_address_id": 1237272, "area_id": 512},
    {"default_address": "Woolworths Lincoln Road", "fulfilment_store_id": 9053, "pickup_address_id": 620844, "area_id": 167},
    {"default_address": "Woolworths Lynfield", "fulfilment_store_id": 9506, "pickup_address_id": 1225554, "area_id": 474},
    {"default_address": "Woolworths Lynnmall", "fulfilment_store_id": 9519, "pickup_address_id": 1225559, "area_id": 475},
    {"default_address": "Woolworths Northwest", "fulfilment_store_id": 9583, "pickup_address_id": 1230704, "area_id": 502},
    {"default_address": "Woolworths Pt Chevalier", "fulfilment_store_id": 9538, "pickup_address_id": 882224, "area_id": 287},
    {"default_address": "Woolworths Te Atatu South", "fulfilment_store_id": 9592, "pickup_address_id": 1232007, "area_id": 505},
    {"default_address": "Woolworths Westgate", "fulfilment_store_id": 9047, "pickup_address_id": 592572, "area_id": 149},
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
