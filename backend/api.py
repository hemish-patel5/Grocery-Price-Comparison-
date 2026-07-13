import re

from flask import Flask, request, jsonify
from flask_cors import CORS

from .scrapers.db import get_client

app = Flask(__name__)
CORS(app)

SEARCH_FETCH_LIMIT = 1000
SEARCH_RESULT_LIMIT = 100


def words(text):
    """Lowercase words plus singular forms, so 'eggs' matches 'egg'."""
    found = set(re.findall(r"[a-z0-9&']+", (text or "").lower()))
    return found | {w[:-1] for w in found if w.endswith("s")}


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()

    # match each word separately so 'free range eggs' finds names with the
    # words in any order; strip a trailing 's' so 'eggs' also matches 'egg'.
    # words contain only [a-z0-9&'], so they can't break the or() syntax
    terms = re.findall(r"[a-z0-9&']+", query.lower())
    stems = list(dict.fromkeys(
        t[:-1] if len(t) > 3 and t.endswith("s") else t for t in terms
    ))
    if not stems:
        return jsonify([])

    client = get_client()
    db_query = client.table("products").select(
        "product_id, name, brand, price, original_price, sale_price, "
        "size, unit_price, department, aisle, image_url, "
        "stores(store_key, address)"
    )
    # chained or_() filters are ANDed by PostgREST: every query word must
    # appear somewhere in the product's name, brand, size, or aisle label
    for stem in stems:
        db_query = db_query.or_(
            f"name.ilike.%{stem}%,brand.ilike.%{stem}%,"
            f"size.ilike.%{stem}%,aisle.ilike.%{stem}%"
        )
    result = db_query.order("price").limit(SEARCH_FETCH_LIMIT).execute()

    def sort_key(row):
        name_words = words(f"{row.get('name')} {row.get('brand')}")
        aisle_words = words(row.get("aisle"))
        name_hit = any(s in name_words for s in stems)
        aisle_hit = any(s in aisle_words for s in stems)
        # products named after the query come first, then products merely
        # shelved in a matching aisle (margarine in the Eggs aisle), then
        # substring-only matches ('egg' inside 'eggplant'); cheapest first
        # within each group, matching aisle breaking price ties
        group = 0 if name_hit else 1 if aisle_hit else 2
        price = row["price"] if row["price"] is not None else float("inf")
        return (group, price, not aisle_hit)

    # The same product is stored once per scraped store. Rows arrive sorted
    # cheapest-first, so keeping the first row per product keeps its
    # cheapest store.
    deduped = []
    seen_product_ids = set()
    for row in result.data:
        if row["product_id"] in seen_product_ids:
            continue
        seen_product_ids.add(row["product_id"])
        deduped.append(row)

    deduped.sort(key=sort_key)

    products = []
    for row in deduped[:SEARCH_RESULT_LIMIT]:
        store = row.pop("stores") or {}
        products.append({
            **row,
            "store": "Woolworths",
            "store_key": store.get("store_key"),
            "store_address": store.get("address"),
            "original_price": f"{row['original_price']:.2f}" if row["original_price"] is not None else None,
            "sale_price": f"{row['sale_price']:.2f}" if row["sale_price"] is not None else None,
        })

    return jsonify(products)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
