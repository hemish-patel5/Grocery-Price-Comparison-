import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from main import search_woolworths, search_woolworths_category


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STORES_FILE = BASE_DIR / "woolworths_stores.json"
DEFAULT_OUTPUT_DIR = BASE_DIR / "scraped_data"
DEFAULT_SUPABASE_TABLE = "woolworths_prices"


def slugify(value):
    return "".join(
        char.lower() if char.isalnum() else "_"
        for char in str(value)
    ).strip("_")


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_timestamp():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_output(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)


def as_float(value):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value):
    if value in (None, ""):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def das_filter(group, value, name, is_boolean=False):
    return f"{group};{value};{name};{str(bool(is_boolean)).lower()};{group}"


def fetch_woolworths_shell():
    with httpx.Client(
        headers={
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
            "x-requested-with": "OnlineShopping.WebApp",
        },
        timeout=20.0,
    ) as client:
        client.get("https://www.woolworths.co.nz")
        res = client.get("https://www.woolworths.co.nz/api/v1/shell")
        res.raise_for_status()
        return res.json()


def browse_departments(shell):
    browse_nav = next(
        (nav for nav in shell.get("mainNavs", []) if nav.get("label") == "Browse"),
        None,
    )
    if not browse_nav:
        return []

    for navigation_item in browse_nav.get("navigationItems", []):
        if navigation_item.get("label") == "Department":
            return navigation_item.get("items", [])

    return []


def build_woolworths_categories(level="aisle"):
    shell = fetch_woolworths_shell()
    categories = []

    for department in browse_departments(shell):
        department_id = department.get("id")
        department_name = department.get("label")
        department_filter = das_filter("Department", department_id, department_name)
        department_base = {
            "department_id": department_id,
            "department_name": department_name,
            "dasFilters": [department_filter],
        }

        if level == "department":
            categories.append({
                **department_base,
                "key": slugify(f"department_{department_id}_{department_name}"),
                "label": department_name,
                "level": "department",
            })
            continue

        for aisle in department.get("dasFacets") or []:
            aisle_id = aisle.get("value")
            aisle_name = aisle.get("name")
            aisle_filter = das_filter(
                "Aisle",
                aisle_id,
                aisle_name,
                aisle.get("isBooleanValue", False),
            )
            aisle_base = {
                **department_base,
                "aisle_id": aisle_id,
                "aisle_name": aisle_name,
                "dasFilters": [department_filter, aisle_filter],
            }

            if level == "aisle":
                categories.append({
                    **aisle_base,
                    "key": slugify(
                        f"department_{department_id}_{department_name}_"
                        f"aisle_{aisle_id}_{aisle_name}"
                    ),
                    "label": f"{department_name} > {aisle_name}",
                    "level": "aisle",
                })
                continue

            for shelf in aisle.get("shelfResponses") or []:
                shelf_id = shelf.get("id")
                shelf_name = shelf.get("label")
                shelf_filter = das_filter("Shelf", shelf_id, shelf_name)
                categories.append({
                    **aisle_base,
                    "shelf_id": shelf_id,
                    "shelf_name": shelf_name,
                    "dasFilters": [
                        department_filter,
                        aisle_filter,
                        shelf_filter,
                    ],
                    "key": slugify(
                        f"department_{department_id}_{department_name}_"
                        f"aisle_{aisle_id}_{aisle_name}_"
                        f"shelf_{shelf_id}_{shelf_name}"
                    ),
                    "label": f"{department_name} > {aisle_name} > {shelf_name}",
                    "level": "shelf",
                })

    return categories


def create_supabase_client():
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(BASE_DIR / ".env")
    load_dotenv(BASE_DIR / ".env.temp")

    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )

    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
            "or SUPABASE_ANON_KEY in backend/.env"
        )

    return create_client(url, key)


def product_row(run_id, mode, query, scraped_at, store_key, store, product):
    return {
        "scrape_run_id": run_id,
        "mode": mode,
        "query": query,
        "scraped_at": scraped_at,
        "store_key": store_key,
        "store_address": store.get("address"),
        "area_id": as_int(store.get("areaId")),
        "fulfilment_store_id": as_int(store.get("fulfilmentStoreId")),
        "pickup_address_id": as_int(store.get("pickupAddressId")),
        "category_key": product.get("category_key"),
        "category_label": product.get("category_label"),
        "category_level": product.get("category_level"),
        "department_id": as_int(product.get("department_id")),
        "department_name": product.get("department_name"),
        "aisle_id": as_int(product.get("aisle_id")),
        "aisle_name": product.get("aisle_name"),
        "shelf_id": as_int(product.get("shelf_id")),
        "shelf_name": product.get("shelf_name"),
        "product_id": product.get("product_id"),
        "barcode": product.get("barcode"),
        "name": product.get("name"),
        "brand": product.get("brand"),
        "price": as_float(product.get("price")),
        "original_price": as_float(product.get("original_price")),
        "sale_price": as_float(product.get("sale_price")),
        "save_price": as_float(product.get("save_price")),
        "size": product.get("size"),
        "unit_price": product.get("unit_price"),
        "image_url": product.get("image_url"),
        "product_url": product.get("product_url"),
        "is_on_special": product.get("is_on_special"),
        "availability": product.get("availability"),
        "stock_level": as_int(product.get("stock_level")),
        "department": product.get("department"),
        "raw": product,
    }


def upload_products_to_supabase(
    supabase,
    table_name,
    run_id,
    mode,
    query,
    scraped_at,
    store_key,
    store,
    products,
    batch_size=500,
):
    rows = [
        product_row(run_id, mode, query, scraped_at, store_key, store, product)
        for product in products
    ]

    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        supabase.table(table_name).insert(batch).execute()

    return len(rows)


def product_key(product):
    return (
        product.get("product_id")
        or product.get("barcode")
        or product.get("product_url")
        or product.get("name")
    )


def scrape_query_across_stores(
    query,
    stores,
    delay_seconds,
    output_path,
    supabase=None,
    supabase_table=DEFAULT_SUPABASE_TABLE,
):
    run_id = f"woolworths_query_{slugify(query)}_{timestamp()}"
    payload = {
        "run_id": run_id,
        "mode": "query",
        "query": query,
        "started_at": iso_timestamp(),
        "finished_at": None,
        "store_count": len(stores),
        "total_products": 0,
        "uploaded_products": 0,
        "stores": {},
    }

    for store_index, (store_key, store) in enumerate(stores.items(), start=1):
        store_name = store.get("address", store_key)
        print(f"[store {store_index}/{len(stores)}] Query {query}: {store_name}")

        products = search_woolworths(query, store)
        for product in products:
            product["source_store_key"] = store_key

        scraped_at = iso_timestamp()
        payload["stores"][store_key] = {
            "store": store,
            "scraped_at": scraped_at,
            "product_count": len(products),
            "products": products,
        }
        payload["total_products"] += len(products)
        save_output(output_path, payload)

        uploaded_count = 0
        if supabase is not None and products:
            uploaded_count = upload_products_to_supabase(
                supabase=supabase,
                table_name=supabase_table,
                run_id=run_id,
                mode="query",
                query=query,
                scraped_at=scraped_at,
                store_key=store_key,
                store=store,
                products=products,
            )
            payload["uploaded_products"] += uploaded_count
            save_output(output_path, payload)

        print(
            f"[store {store_index}/{len(stores)}] {store_name}: "
            f"{len(products)} products"
            + (f", {uploaded_count} uploaded" if supabase is not None else "")
        )

        if delay_seconds > 0 and store_index < len(stores):
            time.sleep(delay_seconds)

    payload["finished_at"] = iso_timestamp()
    save_output(output_path, payload)
    return payload


def scrape_categories_across_stores(
    categories,
    stores,
    delay_seconds,
    output_path,
    keep_category_duplicates=False,
    supabase=None,
    supabase_table=DEFAULT_SUPABASE_TABLE,
):
    run_id = f"woolworths_categories_{timestamp()}"
    payload = {
        "run_id": run_id,
        "mode": "categories",
        "query": None,
        "started_at": iso_timestamp(),
        "finished_at": None,
        "store_count": len(stores),
        "category_count": len(categories),
        "total_products": 0,
        "uploaded_products": 0,
        "stores": {},
    }

    for store_index, (store_key, store) in enumerate(stores.items(), start=1):
        store_name = store.get("address", store_key)
        seen_products = set()
        store_payload = {
            "store": store,
            "product_count": 0,
            "categories": {},
        }
        payload["stores"][store_key] = store_payload

        for category_index, category in enumerate(categories, start=1):
            print(
                f"[store {store_index}/{len(stores)}] "
                f"[category {category_index}/{len(categories)}] "
                f"{store_name}: {category['label']}"
            )

            raw_products = search_woolworths_category(category, store)
            products = []
            for product in raw_products:
                product["source_store_key"] = store_key
                key = product_key(product)
                if not keep_category_duplicates and key in seen_products:
                    continue
                seen_products.add(key)
                products.append(product)

            scraped_at = iso_timestamp()
            category_payload = {
                "category": category,
                "scraped_at": scraped_at,
                "raw_product_count": len(raw_products),
                "product_count": len(products),
                "products": products,
            }
            store_payload["categories"][category["key"]] = category_payload
            store_payload["product_count"] += len(products)
            payload["total_products"] += len(products)
            save_output(output_path, payload)

            uploaded_count = 0
            if supabase is not None and products:
                uploaded_count = upload_products_to_supabase(
                    supabase=supabase,
                    table_name=supabase_table,
                    run_id=run_id,
                    mode="categories",
                    query=None,
                    scraped_at=scraped_at,
                    store_key=store_key,
                    store=store,
                    products=products,
                )
                payload["uploaded_products"] += uploaded_count
                save_output(output_path, payload)

            print(
                f"[store {store_index}/{len(stores)}] "
                f"[category {category_index}/{len(categories)}] "
                f"{len(products)} new products "
                f"({len(raw_products)} raw), "
                f"{payload['total_products']} total"
                + (
                    f", {uploaded_count} uploaded"
                    if supabase is not None else ""
                )
            )

            if delay_seconds > 0:
                time.sleep(delay_seconds)

    payload["finished_at"] = iso_timestamp()
    save_output(output_path, payload)
    return payload


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Scrape Woolworths NZ products across stores by category "
            "or by one search query."
        ),
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Search query when using --mode query, for example: milk.",
    )
    parser.add_argument(
        "--mode",
        choices=("categories", "query"),
        default="categories",
        help="Scrape all categories by default, or one search query.",
    )
    parser.add_argument(
        "--category-level",
        choices=("department", "aisle", "shelf"),
        default="aisle",
        help="Category depth to scrape. Aisle is the best default.",
    )
    parser.add_argument(
        "--stores-file",
        default=str(DEFAULT_STORES_FILE),
        help="Path to woolworths_stores.json.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path. Defaults to backend/scraped_data/...",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only scrape the first N stores. Useful for testing.",
    )
    parser.add_argument(
        "--category-limit",
        type=int,
        default=None,
        help="Only scrape the first N categories. Useful for testing.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait after each category/store request.",
    )
    parser.add_argument(
        "--keep-category-duplicates",
        action="store_true",
        help="Keep products repeated across multiple categories.",
    )
    parser.add_argument(
        "--upload-supabase",
        action="store_true",
        help="Also insert scraped products into Supabase.",
    )
    parser.add_argument(
        "--supabase-table",
        default=DEFAULT_SUPABASE_TABLE,
        help=f"Supabase table name. Defaults to {DEFAULT_SUPABASE_TABLE}.",
    )
    args = parser.parse_args()

    stores = load_json(Path(args.stores_file))
    if args.limit is not None:
        stores = dict(list(stores.items())[:args.limit])

    supabase = create_supabase_client() if args.upload_supabase else None

    if args.mode == "query":
        if not args.query:
            parser.error("query is required when using --mode query")

        output_path = Path(args.output) if args.output else (
            DEFAULT_OUTPUT_DIR
            / f"woolworths_query_{slugify(args.query)}_{timestamp()}.json"
        )
        result = scrape_query_across_stores(
            query=args.query,
            stores=stores,
            delay_seconds=args.delay,
            output_path=output_path,
            supabase=supabase,
            supabase_table=args.supabase_table,
        )
    else:
        categories = build_woolworths_categories(level=args.category_level)
        if args.category_limit is not None:
            categories = categories[:args.category_limit]

        output_path = Path(args.output) if args.output else (
            DEFAULT_OUTPUT_DIR
            / f"woolworths_categories_{args.category_level}_{timestamp()}.json"
        )
        result = scrape_categories_across_stores(
            categories=categories,
            stores=stores,
            delay_seconds=args.delay,
            output_path=output_path,
            keep_category_duplicates=args.keep_category_duplicates,
            supabase=supabase,
            supabase_table=args.supabase_table,
        )

    print(
        f"Done. Scraped {result['total_products']} products "
        f"from {result['store_count']} stores."
    )
    if args.upload_supabase:
        print(f"Uploaded {result['uploaded_products']} products to Supabase.")
    print(f"Saved results to {output_path}")


if __name__ == "__main__":
    main()
