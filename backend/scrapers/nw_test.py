"""Compare the same New World products across exactly three stores."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from .newworld import (
        NEWWORLD_HITS_PER_PAGE,
        algolia_quote,
        build_search_payload,
        category_filters,
        fetch_search_page,
        load_newworld_stores,
        newworld_client,
        normalize_newworld_product,
        store_id_from,
    )
except ImportError:  # Allow `python backend/scrapers/nw_test.py`.
    from newworld import (
        NEWWORLD_HITS_PER_PAGE,
        algolia_quote,
        build_search_payload,
        category_filters,
        fetch_search_page,
        load_newworld_stores,
        newworld_client,
        normalize_newworld_product,
        store_id_from,
    )


DEFAULT_STORES = ["birkenhead", "ormiston", "new_lynn"]
DEFAULT_ITEM_COUNT = 5
DEFAULT_DEPARTMENT = "Pantry"
DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "newworld_price_comparison_test.json"
)


def product_category(product, fallback_department=None):
    tree = (product.get("categoryTrees") or [{}])[0]
    return {
        "department": tree.get("level0") or fallback_department,
        "category": tree.get("level1"),
        "subcategory": tree.get("level2"),
    }


def fetch_candidates(client, store, department):
    """Fetch a candidate pool from the first store."""
    filters = category_filters(store, department=department)
    body = fetch_search_page(
        client,
        build_search_payload(
            store,
            filters,
            page=0,
            hits_per_page=NEWWORLD_HITS_PER_PAGE,
        ),
        label=f"{store['store_key']} / {department} candidates",
    )
    return body.get("products") or []


def fetch_exact_product(client, store, product_id):
    """Fetch one exact retailer product ID at one store."""
    filters = (
        f"{category_filters(store)} "
        f"AND productID:{algolia_quote(product_id)}"
    )
    body = fetch_search_page(
        client,
        build_search_payload(store, filters, page=0, hits_per_page=1),
        label=f"{store['store_key']} / {product_id}",
    )
    products = body.get("products") or []
    if not products:
        return None

    raw_product = products[0]
    return normalize_newworld_product(
        raw_product,
        store,
        product_category(raw_product),
    )


def minimal_store_price(product):
    return {
        "store_key": product["source_store_key"],
        "price": product["price"],
        "is_club_price": product["is_club_price"],
    }


def compare_product(product_id, products):
    prices = [minimal_store_price(product) for product in products]
    distinct_prices = {price["price"] for price in prices}
    return {
        "product_id": product_id,
        "name": products[0]["name"],
        "brand": products[0].get("brand"),
        "size": products[0].get("size"),
        "image_url": products[0].get("image_url"),
        "department": products[0].get("department"),
        "aisle": products[0].get("aisle"),
        "prices_differ": len(distinct_prices) > 1,
        "store_prices": prices,
    }


def validate_options(store_keys, item_count, stores):
    if len(store_keys) != 3:
        raise ValueError("Choose exactly 3 stores with --stores")
    if len(set(store_keys)) != 3:
        raise ValueError("The 3 selected stores must be different")

    unknown = [key for key in store_keys if key not in stores]
    if unknown:
        raise ValueError(
            f"Unknown store(s): {', '.join(unknown)}. "
            f"Available stores: {', '.join(stores)}"
        )
    if not 1 <= item_count <= NEWWORLD_HITS_PER_PAGE:
        raise ValueError(
            f"item_count must be between 1 and {NEWWORLD_HITS_PER_PAGE}"
        )


def run_comparison(store_keys, item_count, department):
    stores = load_newworld_stores()
    validate_options(store_keys, item_count, stores)
    selected_stores = [
        {**stores[key], "store_key": key}
        for key in store_keys
    ]

    comparisons = []
    skipped = []
    with newworld_client() as client:
        candidates = fetch_candidates(client, selected_stores[0], department)
        print(
            f"Found {len(candidates)} candidate products in {department}; "
            f"looking for {item_count} available at all 3 stores"
        )

        for candidate in candidates:
            if len(comparisons) >= item_count:
                break

            product_id = candidate.get("productId")
            if not product_id:
                continue

            store_products = []
            for store in selected_stores:
                product = fetch_exact_product(client, store, product_id)
                if product is None:
                    skipped.append({
                        "product_id": product_id,
                        "name": candidate.get("name"),
                        "missing_from": store["store_key"],
                    })
                    break
                store_products.append(product)

            if len(store_products) != len(selected_stores):
                continue

            comparison = compare_product(product_id, store_products)
            comparisons.append(comparison)
            print(f"\n[{len(comparisons)}/{item_count}] {comparison['name']}")
            for store_price in comparison["store_prices"]:
                club = " (Clubcard)" if store_price["is_club_price"] else ""
                print(
                    f"  {store_price['store_key']}: "
                    f"${store_price['price']}{club}"
                )

    if len(comparisons) < item_count:
        raise RuntimeError(
            f"Only found {len(comparisons)} products available at all 3 stores; "
            f"requested {item_count}"
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "department": department,
        "requested_item_count": item_count,
        "stores": [
            {
                "store_key": store["store_key"],
                "store_id": store_id_from(store),
            }
            for store in selected_stores
        ],
        "comparison_count": len(comparisons),
        "different_price_count": sum(
            item["prices_differ"] for item in comparisons
        ),
        "comparisons": comparisons,
        "skipped_candidates": skipped,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare the same New World products across 3 stores",
    )
    parser.add_argument(
        "--stores",
        nargs=3,
        default=DEFAULT_STORES,
        metavar=("STORE_1", "STORE_2", "STORE_3"),
        help="exactly 3 keys from newworld_auckland_stores.json",
    )
    parser.add_argument(
        "--items",
        type=int,
        default=DEFAULT_ITEM_COUNT,
        help="number of identical products to compare (default: 5)",
    )
    parser.add_argument(
        "--department",
        default=DEFAULT_DEPARTMENT,
        help="department used to select reference products (default: Pantry)",
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
        report = run_comparison(args.stores, args.items, args.department)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"\nSaved {report['comparison_count']} product comparisons to "
        f"{args.output}"
    )
    print(
        f"Products with different prices: "
        f"{report['different_price_count']}/{report['comparison_count']}"
    )


if __name__ == "__main__":
    main()
