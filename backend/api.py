import re

from flask import Flask, request, jsonify
from flask_cors import CORS

from .scrapers.db import get_client

app = Flask(__name__)
CORS(app)

SEARCH_RESULT_LIMIT = 100
SEARCH_QUERY_MAX_LENGTH = 100
SEARCH_TERM_LIMIT = 8

SEARCH_CATEGORIES = (
    ("fruit_vegetables", "Fruit & Vegetables"),
    ("meat_seafood", "Meat, Poultry & Seafood"),
    ("dairy_deli", "Dairy, Deli & Eggs"),
    ("pantry", "Pantry"),
    ("bakery", "Bakery"),
    ("drinks", "Drinks"),
    ("frozen", "Frozen"),
    ("snacks_ready_meals", "Snacks & Easy Meals"),
    ("household", "Household & Cleaning"),
    ("health_body", "Health & Body"),
    ("baby", "Baby & Toddler"),
    ("pets", "Pets"),
    ("beer_wine", "Beer, Wine & Cider"),
    ("featured", "Featured & Deals"),
)
SEARCH_CATEGORY_KEYS = {value for value, _ in SEARCH_CATEGORIES}

SEARCH_SORTS = (
    ("relevance", "Relevance"),
    ("price_asc", "Lowest price"),
    ("price_desc", "Highest price"),
)
SEARCH_SORT_KEYS = {value for value, _ in SEARCH_SORTS}

SEARCH_LOCATION_TABLES = (
    ("woolworths", "Woolworths", "woolies_stores"),
    ("new_world", "New World", "newworld_stores"),
    ("paknsave", "PAK'nSAVE", "paknsave_stores"),
)
SEARCH_LOCATION_RETAILERS = {
    value: retailer for value, retailer, _ in SEARCH_LOCATION_TABLES
}


def optional_price(value):
    return f"{value:.2f}" if value is not None else None


def public_search_row(row, retailer):
    row = dict(row)
    if retailer == "New World":
        # The prefix only tells the detail endpoint which table to query. The
        # ID stored in newworld_products remains the unmodified retailer ID.
        row["product_id"] = f"new_world:{row['product_id']}"
    elif retailer == "PAK'nSAVE":
        row["product_id"] = f"paknsave:{row['product_id']}"
    return {
        **row,
        "store": retailer,
        "original_price": optional_price(row.get("original_price")),
        "sale_price": optional_price(row.get("sale_price")),
        "is_club_price": bool(row.get("is_club_price", False)),
        "is_on_special": bool(row.get("is_on_special", False)),
    }


def search_error(message, status=400):
    return jsonify({"error": message}), status


def normalized_search_query(query):
    terms = re.findall(r"[a-z0-9&']+", query.lower())
    return " ".join(dict.fromkeys(terms[:SEARCH_TERM_LIMIT]))


def parse_search_location(value):
    if not value:
        return None, None

    retailer_key, separator, store_key = value.partition(":")
    retailer = SEARCH_LOCATION_RETAILERS.get(retailer_key)
    if (
        not separator
        or retailer is None
        or not re.fullmatch(r"[a-z0-9_]{1,64}", store_key)
    ):
        raise ValueError("Unknown location")
    return retailer, store_key


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/search/options")
def search_options():
    """Return filter choices backed by stores that exist in Supabase."""
    client = get_client()
    locations = []
    for retailer_key, retailer, table in SEARCH_LOCATION_TABLES:
        try:
            rows = (
                client.table(table)
                .select("store_key,address")
                .order("address")
                .execute()
                .data
            )
        except Exception:
            app.logger.exception("Could not load search locations from %s", table)
            continue

        locations.extend({
            "value": f"{retailer_key}:{row['store_key']}",
            "label": row.get("address") or row["store_key"],
            "retailer": retailer,
        } for row in rows)

    return jsonify({
        "categories": [
            {"value": value, "label": label}
            for value, label in SEARCH_CATEGORIES
        ],
        "sorts": [
            {"value": value, "label": label}
            for value, label in SEARCH_SORTS
        ],
        "locations": locations,
    })


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip() or None
    sort_order = request.args.get("sort", "relevance").strip()
    location = request.args.get("location", "").strip()

    if len(query) > SEARCH_QUERY_MAX_LENGTH:
        return search_error(
            f"Search query must be {SEARCH_QUERY_MAX_LENGTH} characters or fewer"
        )
    if category is not None and category not in SEARCH_CATEGORY_KEYS:
        return search_error("Unknown category")
    if sort_order not in SEARCH_SORT_KEYS:
        return search_error("Unknown sort order")
    try:
        retailer, store_key = parse_search_location(location)
    except ValueError as exc:
        return search_error(str(exc))

    normalized_query = normalized_search_query(query)
    if not normalized_query and category is None and store_key is None:
        return jsonify([])

    rpc_args = {
        "p_query": normalized_query,
        "p_category": category,
        "p_retailer": retailer,
        "p_store_key": store_key,
        "p_sort": sort_order,
        "p_limit": SEARCH_RESULT_LIMIT,
        "p_offset": 0,
    }
    try:
        rows = (
            get_client()
            .rpc("search_grocery_products", rpc_args)
            .execute()
            .data
        )
    except Exception:
        app.logger.exception("Grocery search RPC failed")
        return search_error("Search is temporarily unavailable", status=503)

    products = [
        public_search_row(row, row.get("retailer"))
        for row in (rows or [])
    ]
    response = jsonify(products)
    response.headers["X-Total-Count"] = str(
        rows[0].get("total_count", len(rows)) if rows else 0
    )
    return response


@app.route("/api/product/<product_id>/prices")
def product_prices(product_id):
    """Every store's price for one product, cheapest first. Backs the
    per-store comparison dropdown on the product cards."""
    if product_id.startswith("new_world:"):
        retailer = "New World"
        database_product_id = product_id.split(":", 1)[1]
        price_table = "newworld_store_prices"
        store_relation = "newworld_stores"
        price_columns = (
            "price, is_club_price, "
            "newworld_stores(store_key, address)"
        )
    elif product_id.startswith("paknsave:"):
        retailer = "PAK'nSAVE"
        database_product_id = product_id.split(":", 1)[1]
        price_table = "paknsave_store_prices"
        store_relation = "paknsave_stores"
        price_columns = (
            "price, is_on_special, "
            "paknsave_stores(store_key, address)"
        )
    else:
        retailer = "Woolworths"
        database_product_id = product_id
        price_table = "woolies_store_prices"
        store_relation = "woolies_stores"
        price_columns = (
            "price, original_price, sale_price, unit_price, "
            "woolies_stores(store_key, address)"
        )

    result = (
        get_client()
        .table(price_table)
        .select(price_columns)
        .eq("product_id", database_product_id)
        .order("price")
        .execute()
    )

    prices = []
    for row in result.data:
        row = dict(row)
        store = row.pop(store_relation) or {}
        prices.append({
            **row,
            "store": retailer,
            "store_key": store.get("store_key"),
            "store_address": store.get("address"),
            "original_price": optional_price(row.get("original_price")),
            "sale_price": optional_price(row.get("sale_price")),
            "unit_price": row.get("unit_price"),
            "is_club_price": bool(row.get("is_club_price", False)),
            "is_on_special": bool(row.get("is_on_special", False)),
        })
    return jsonify(prices)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
