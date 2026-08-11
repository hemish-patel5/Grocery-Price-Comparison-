"""Small live New World sampler for validating stores, categories and prices.

The script fetches a configurable number of products from each top-level
department for three stores, normalizes them with the production scraper, and
writes a single JSON report. It intentionally does not crawl every leaf or
page, so it is safe to use as a quick integration check.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from .newworld import (
        NEWWORLD_HITS_PER_PAGE,
        build_search_payload,
        category_filters,
        fetch_facets,
        fetch_search_page,
        load_newworld_stores,
        newworld_client,
        normalize_newworld_product,
        store_id_from,
    )
except ImportError:  # Allow `python backend/scrapers/newworld_sample.py`.
    from newworld import (
        NEWWORLD_HITS_PER_PAGE,
        build_search_payload,
        category_filters,
        fetch_facets,
        fetch_search_page,
        load_newworld_stores,
        newworld_client,
        normalize_newworld_product,
        store_id_from,
    )


DEFAULT_STORES = ["birkenhead", "ormiston", "new_lynn"]
DEFAULT_ITEMS_PER_CATEGORY = 5
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "newworld_sample_test.json"
)


def product_category(product, department):
    """Use the product's own hierarchy while retaining the requested department."""
    trees = product.get("categoryTrees") or []
    tree = next(
        (item for item in trees if item.get("level0") == department),
        trees[0] if trees else {},
    )
    return {
        "department": tree.get("level0") or department,
        "category": tree.get("level1"),
        "subcategory": tree.get("level2"),
    }


def sample_department(client, store, department, items_per_category):
    filters = category_filters(store, department=department)
    payload = build_search_payload(
        store,
        filters,
        page=0,
        hits_per_page=items_per_category,
    )
    body = fetch_search_page(
        client,
        payload,
        label=f"{store['store_key']} / {department} sample",
    )
    raw_products = body.get("products") or []
    products = [
        normalize_newworld_product(
            product,
            store,
            product_category(product, department),
        )
        for product in raw_products[:items_per_category]
    ]
    return {
        "category": department,
        "available_products": body.get("totalHits"),
        "sample_count": len(products),
        "products": products,
    }


def run_sample(store_keys, items_per_category):
    stores = load_newworld_stores()
    unknown = [key for key in store_keys if key not in stores]
    if unknown:
        raise ValueError(
            f"Unknown store(s): {', '.join(unknown)}. "
            f"Available stores: {', '.join(stores)}"
        )
    if not 1 <= items_per_category <= NEWWORLD_HITS_PER_PAGE:
        raise ValueError(
            f"items_per_category must be between 1 and {NEWWORLD_HITS_PER_PAGE}"
        )

    report_stores = []
    with newworld_client() as client:
        for store_position, store_key in enumerate(store_keys, 1):
            store = {**stores[store_key], "store_key": store_key}
            print(
                f"\n[{store_position}/{len(store_keys)}] {store_key} "
                f"({store_id_from(store)})"
            )
            departments = fetch_facets(
                client,
                store,
                facet="category0NI",
                filters=category_filters(store),
            )

            category_results = []
            failures = []
            for category_position, department in enumerate(departments, 1):
                name = department["name"]
                print(
                    f"  [{category_position}/{len(departments)}] "
                    f"{name}: requesting {items_per_category} products"
                )
                try:
                    category_results.append(
                        sample_department(
                            client,
                            store,
                            name,
                            items_per_category,
                        )
                    )
                except Exception as exc:
                    print(f"    FAILED: {exc}")
                    failures.append({
                        "category": name,
                        "error": str(exc),
                    })

            report_stores.append({
                "store_key": store_key,
                "store_id": store_id_from(store),
                "category_count": len(category_results),
                "product_count": sum(
                    category["sample_count"]
                    for category in category_results
                ),
                "failed_categories": failures,
                "categories": category_results,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items_per_category": items_per_category,
        "requested_stores": store_keys,
        "store_count": len(report_stores),
        "category_sample_count": sum(
            store["category_count"]
            for store in report_stores
        ),
        "product_count": sum(
            store["product_count"]
            for store in report_stores
        ),
        "stores": report_stores,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Sample products from every top-level New World category for "
            "three stores"
        ),
    )
    parser.add_argument(
        "--stores",
        nargs="+",
        default=DEFAULT_STORES,
        help="store keys from newworld_auckland_stores.json",
    )
    parser.add_argument(
        "--items-per-category",
        type=int,
        default=DEFAULT_ITEMS_PER_CATEGORY,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        report = run_sample(args.stores, args.items_per_category)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"\nSaved {report['product_count']} products from "
        f"{report['category_sample_count']} store/category samples to "
        f"{args.output}"
    )


if __name__ == "__main__":
    main()
