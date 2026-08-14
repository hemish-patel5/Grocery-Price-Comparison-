import re

from flask import Flask, request, jsonify
from flask_cors import CORS

from .scrapers.db import get_client

app = Flask(__name__)
CORS(app)

SEARCH_RESULT_LIMIT = 100


def optional_price(value):
    return f"{value:.2f}" if value is not None else None


def words(value):
    found = set(re.findall(r"[a-z0-9&']+", (value or "").lower()))
    return found | {word[:-1] for word in found if len(word) > 3 and word.endswith("s")}


def combined_result_sort_key(row, stems):
    name_words = words(f"{row.get('name') or ''} {row.get('brand') or ''}")
    aisle_words = words(row.get("aisle"))
    name_hit = any(stem in name_words for stem in stems)
    aisle_hit = any(stem in aisle_words for stem in stems)
    relevance = 0 if name_hit and aisle_hit else 1 if name_hit else 2 if aisle_hit else 3
    price = row.get("price")
    return relevance, price is None, price if price is not None else float("inf")


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


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()

    # split into words so 'free range eggs' matches names with the words in
    # any order; strip a trailing 's' so 'eggs' also matches 'egg'
    terms = re.findall(r"[a-z0-9&']+", query.lower())
    stems = list(dict.fromkeys(
        t[:-1] if len(t) > 3 and t.endswith("s") else t for t in terms
    ))
    if not stems:
        return jsonify([])

    rpc_args = {
        "p_stems": stems,
        "p_limit": SEARCH_RESULT_LIMIT,
    }
    client = get_client()

    # Each retailer is searched in its own tables. Combining and sorting the
    # small, already-ranked result sets here keeps their schemas independent.
    woolworths = client.rpc("search_products", rpc_args).execute().data
    new_world = client.rpc("search_newworld_products", rpc_args).execute().data
    paknsave = client.rpc("search_paknsave_products", rpc_args).execute().data
    products = [
        *(public_search_row(row, "Woolworths") for row in woolworths),
        *(public_search_row(row, "New World") for row in new_world),
        *(public_search_row(row, "PAK'nSAVE") for row in paknsave),
    ]
    products.sort(key=lambda row: combined_result_sort_key(row, stems))

    return jsonify(products[:SEARCH_RESULT_LIMIT])


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
